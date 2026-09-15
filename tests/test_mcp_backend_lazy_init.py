"""Lazily built backend state, now that two reads can arrive at once (#3379).

Before tool bodies moved onto worker threads, the event loop made every body
exclusive and ``if self._x is None: self._x = ...`` could not be entered twice.
It can now. These tests cover the two lazy paths whose construction is not free
— both touch Mongo — and each one fails without the lock it is testing.

The other lazy paths in ``mcp_server`` are deliberately unlocked because
building them twice costs nothing; the reasoning is written beside each of them
rather than asserted here, since there is no behaviour to assert.
"""

import threading
import time

import pytest

pytest.importorskip("mcp")

from mcp_server.backend import ProductionBackend  # noqa: E402


class _CountingCollection:
    """A sticky-notes collection that records how often indexes were built."""

    def __init__(self):
        self.created = []
        self._guard = threading.Lock()

    def create_index(self, keys, name=None):
        time.sleep(0.01)  # widen the window a racing thread would slip through
        with self._guard:
            self.created.append(name)


class _CountingMongo:
    def __init__(self):
        self.notes = _CountingCollection()

    def __getitem__(self, key):
        assert key == "sticky_notes", key
        return self.notes


def _run_concurrently(fn, threads=8):
    """Call ``fn`` from several threads released at the same moment."""
    start = threading.Barrier(threads)
    errors = []

    def worker():
        try:
            start.wait(5.0)
            fn()
        except Exception as exc:  # pragma: no cover - surfaced by the assert
            errors.append(exc)

    workers = [threading.Thread(target=worker) for _ in range(threads)]
    for w in workers:
        w.start()
    for w in workers:
        w.join(10.0)
    assert not errors, errors


def test_concurrent_readers_build_the_notes_indexes_once():
    """Four indexes, not eight, and nobody queries before they exist.

    Two things were wrong here and both are visible from this test. The flag was
    set *before* the loop, so a second thread arriving mid-build skipped it and
    went on to query an index that was not there yet. And nothing stopped two
    threads from running the four ``create_index`` calls at the same time.

    Without the fix this reports eight or more index builds. ``_notes_coll`` is
    reached by ``list_notes`` and ``list_board_notes``, which are read tools —
    so concurrent arrival is the ordinary case, not a contrived one.
    """
    mongo = _CountingMongo()
    backend = ProductionBackend(mongo_db=mongo)

    _run_concurrently(backend._notes_coll)

    assert sorted(mongo.notes.created) == [
        "user_board_idx",
        "user_repo_idx",
        "user_scope_idx",
        "user_title_idx",
    ], mongo.notes.created


def test_the_index_flag_is_only_set_once_the_indexes_exist():
    """The flag must not be a promise made in advance.

    A reader that sees ``_notes_idx_done`` is entitled to assume the indexes are
    there. Setting the flag first made that assumption false for the length of
    four round trips, which is exactly when a burst of concurrent reads arrives.
    """
    mongo = _CountingMongo()
    backend = ProductionBackend(mongo_db=mongo)
    seen: list[tuple[bool, int]] = []

    original = mongo.notes.create_index

    def watching_create_index(keys, name=None):
        seen.append((backend._notes_idx_done, len(mongo.notes.created)))
        return original(keys, name=name)

    mongo.notes.create_index = watching_create_index
    backend._notes_coll()

    assert seen, "no index was built"
    assert all(done is False for done, _ in seen), seen


def test_concurrent_readers_build_the_collections_manager_once(monkeypatch):
    """``CollectionsManager`` construction is not free, so it happens once.

    Its ``__init__`` issues ``create_indexes`` against Mongo and then runs a
    one-time migration behind a class attribute that is itself a check-then-act;
    two constructions can mean two full-collection backfills. Without the lock
    this builds one per thread.
    """
    import database.collections_manager as cm_module

    built = []
    guard = threading.Lock()

    class _SlowManager:
        def __init__(self, db):
            time.sleep(0.02)  # stand in for the index round trips
            with guard:
                built.append(db)

    monkeypatch.setattr(cm_module, "CollectionsManager", _SlowManager)

    backend = ProductionBackend(mongo_db=object())
    _run_concurrently(backend._collections)

    assert len(built) == 1, f"built {len(built)} collection managers"
