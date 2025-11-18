import importlib
from types import SimpleNamespace

import pytest


def _svc():
    return importlib.import_module("services.snippet_library_service")


def test_title_normalization_and_map_deduplication(monkeypatch):
    svc = _svc()
    title_map = svc._build_builtin_title_map([
        {"title": "  Foo  "},
        {"title": "foo"},  # duplicate – should be skipped
        {"title": "Bar"},
        {"title": None},
    ])
    assert title_map == {"foo": "Foo", "bar": "Bar"}
    assert svc._normalize_title_value("  Baz  ") == "baz"


def test_collect_existing_titles_hits_collection(monkeypatch):
    svc = _svc()

    class _Coll:
        def __init__(self):
            self.last_query = None

        def find(self, query, projection):
            self.last_query = query
            return [{"title": "Foo"}]

    coll = _Coll()
    db_stub = SimpleNamespace(snippets_collection=coll, db=None)
    monkeypatch.setattr(svc, "_db", db_stub, raising=False)

    title_map = {"foo": "Foo", "bar": "Bar"}
    found, has_lookup = svc._collect_existing_builtin_titles(
        title_map, q="Foo", language="python"
    )

    assert has_lookup is True
    assert found == {"foo"}
    assert isinstance(coll.last_query, dict)
    and_filters = coll.last_query.get("$and")
    assert and_filters and {"status": "approved"} in and_filters


def test_collect_existing_titles_without_collection(monkeypatch):
    svc = _svc()
    db_stub = SimpleNamespace(snippets_collection=None, db=None)
    monkeypatch.setattr(svc, "_db", db_stub, raising=False)
    found, has_lookup = svc._collect_existing_builtin_titles({"foo": "Foo"}, q=None, language=None)
    assert found == set()
    assert has_lookup is False


def test_filtered_builtins_and_language_match(monkeypatch):
    svc = _svc()
    monkeypatch.setattr(
        svc,
        "BUILTIN_SNIPPETS",
        [
            {"title": "Python Foo", "description": "alpha", "language": "python", "code": "print(1)"},
            {"title": "JS Bar", "description": "beta", "language": "javascript", "code": "console.log(1)"},
        ],
        raising=False,
    )
    filtered = svc._filtered_builtins(q="alpha", language="python")
    assert len(filtered) == 1 and filtered[0]["title"] == "Python Foo"


def test_merge_builtins_with_db_dedupes_titles():
    svc = _svc()
    db_items = [{"title": "Foo"}, {"title": "DB Only"}]
    builtins = [{"title": "foo"}, {"title": "Bar"}]
    merged = svc._merge_builtins_with_db(db_items, builtins)
    titles = [it["title"] for it in merged]
    assert titles.count("Foo") == 1
    assert "Bar" in titles


def test_approve_and_reject_snippet_proxy_repo(monkeypatch):
    svc = _svc()

    class _Repo:
        def __init__(self):
            self.approved = None
            self.rejected = None

        def approve_snippet(self, item_id, admin_id):
            self.approved = (item_id, admin_id)
            return True

        def reject_snippet(self, item_id, admin_id, reason):
            self.rejected = (item_id, admin_id, reason)
            return True

    repo = _Repo()
    monkeypatch.setattr(svc, "_db", SimpleNamespace(_get_repo=lambda: repo), raising=False)
    events = []
    monkeypatch.setattr(svc, "emit_event", lambda *a, **k: events.append((a, k)), raising=False)

    assert svc.approve_snippet("abc", 7) is True
    assert svc.reject_snippet("xyz", 9, "nope") is True
    assert repo.approved == ("abc", 7)
    assert repo.rejected == ("xyz", 9, "nope")
    assert events  # ensure emit_event was called


def test_list_public_snippets_without_builtins(monkeypatch):
    svc = _svc()

    class _Repo:
        include_builtin_snippets = False

        def list_public_snippets(self, **kw):
            return ([{"title": "From DB"}], 1)

    monkeypatch.setattr(svc, "_db", SimpleNamespace(_get_repo=lambda: _Repo()), raising=False)
    items, total = svc.list_public_snippets(page=1, per_page=5)
    assert items == [{"title": "From DB"}]
    assert total == 1


def test_list_public_snippets_non_paginated_repo(monkeypatch):
    svc = _svc()

    class _Repo:
        include_builtin_snippets = True

        def list_public_snippets(self, *, q=None, language=None):
            return (
                [
                    {"title": "Slice1"},
                    {"title": "Slice2"},
                ],
                2,
            )

    repo = _Repo()
    monkeypatch.setattr(
        svc,
        "_db",
        SimpleNamespace(_get_repo=lambda: repo, snippets_collection=None, db=None),
        raising=False,
    )
    monkeypatch.setattr(
        svc,
        "BUILTIN_SNIPPETS",
        [{"title": "Builtin A"}, {"title": "Builtin B"}],
        raising=False,
    )

    items, total = svc.list_public_snippets(page=2, per_page=1)
    assert any(item["title"] == "Slice2" for item in items)
    assert total >= 2


def test_list_public_snippets_chunk_probe_dedup(monkeypatch):
    svc = _svc()

    class _Repo:
        include_builtin_snippets = True

        def list_public_snippets(self, **kw):
            page = kw.get("page", 1)
            if page == 1:
                return ([{"title": "DB#1"}], 3)
            if page == 2:
                return ([{"title": "DB#2"}], 3)
            return ([], 3)

    repo = _Repo()
    monkeypatch.setattr(
        svc,
        "_db",
        SimpleNamespace(_get_repo=lambda: repo, snippets_collection=None, db=None),
        raising=False,
    )
    monkeypatch.setattr(
        svc,
        "BUILTIN_SNIPPETS",
        [{"title": "DB#1"}, {"title": "UniqueBuiltin"}],
        raising=False,
    )

    items, total = svc.list_public_snippets(page=3, per_page=1)
    titles = [it["title"] for it in items]
    assert "DB#1" not in titles  # deduped by chunk probe
    assert "UniqueBuiltin" in titles
    assert total >= 3
