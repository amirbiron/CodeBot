"""Shared in-memory fake for the Mongo handles the tests drive.

Repo convention is hand-rolled fakes (no mongomock). Several suites need the
same duck-typed stand-in, so the collection semantics — filter matching
(``$ne``, ``$in``, ``$nin``, ``$exists`` and the range operators), inclusion
projections, ``find_one`` with pymongo's positional projection and ``sort``,
upsert with ``$setOnInsert``, ``$push`` with ``$each``/``$slice``, ``$unset``,
``update_many``, ``delete_many``, ``bulk_write`` of ``ReplaceOne``, counting, and
the matched/modified/upserted/deleted counts and ``inserted_id`` the callers
read — live here in one place. An operator outside those sets raises
``NotImplementedError`` rather than matching everything or ignoring the
write. ``FakeTrackerDB`` is the ``DatabaseManager``
shape the job tracker reaches its collection through. The migration-script tests reach the DB as
``db.note_reminders`` and read ``db.name``, so ``FakeDB`` also answers
attribute access like a real ``Database`` handle.

``AsyncFakeCollection`` is the motor-shaped facade over the same object: the
jobs code awaits its writes and drains ``find`` with ``to_list``. It delegates,
so there is one matcher and one set of write semantics, not two that drift.

Dotted paths (``"prefs.schedule_key"``) are resolved into nested documents in
filters, ``$set`` and ``$unset`` — as Mongo does — because the webapp's Drive
code writes and claims single fields inside a sub-document. ``find_one_and_update``
runs under the collection's lock, so a test that fires it from several threads
measures what Mongo guarantees for a single document: one caller wins the match.

Usage::

    from tests._fake_mongo import FakeDB
    store = OAuthStore(FakeDB())
"""

from __future__ import annotations

import copy
import threading
from typing import Any

_MISSING = object()


def _get_path(doc: dict, key: str) -> Any:
    """The value at ``key`` — a dotted path walks sub-documents — or ``_MISSING``."""
    current: Any = doc
    for part in str(key).split("."):
        if not isinstance(current, dict) or part not in current:
            return _MISSING
        current = current[part]
    return current


def _set_path(doc: dict, key: str, value: Any) -> None:
    parts = str(key).split(".")
    current = doc
    for part in parts[:-1]:
        nxt = current.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            current[part] = nxt
        current = nxt
    current[parts[-1]] = value


def _unset_path(doc: dict, key: str) -> None:
    parts = str(key).split(".")
    current: Any = doc
    for part in parts[:-1]:
        current = current.get(part) if isinstance(current, dict) else None
        if not isinstance(current, dict):
            return
    current.pop(parts[-1], None)


class _Res:
    """Mimics pymongo write results (only the fields our callers inspect).

    ``matched_count`` is what a guarded write reads: an update whose filter
    matched nothing is a rejection, not an error, and it is indistinguishable
    from success unless the caller counts.
    """

    def __init__(
        self,
        modified: int = 0,
        upserted: Any = None,
        deleted: int = 0,
        matched: int | None = None,
        inserted: Any = None,
    ) -> None:
        self.modified_count = modified
        self.upserted_id = upserted
        self.deleted_count = deleted
        self.matched_count = modified if matched is None else matched
        # ``Repository.save_code_snippet`` reads ``inserted_id`` to decide the
        # save happened; a result without it reads as a failed insert.
        self.inserted_id = inserted
        # ``ProductionBackend.create_upload`` refuses an unacknowledged insert
        # (``w=0``) — pymongo's ``_WriteResult.acknowledged``, ``False`` only
        # there (``pymongo/results.py``, 4.15.3). The fake's writes all happen.
        self.acknowledged = True


class _BulkRes:
    """pymongo's ``BulkWriteResult`` counts that the callers read (4.15.3, ``pymongo/results.py``)."""

    def __init__(self, matched: int = 0, upserted: int = 0, deleted: int = 0) -> None:
        self.matched_count = matched
        # The fake replaces whole documents, so every matched replacement counts as modified.
        self.modified_count = matched
        self.upserted_count = upserted
        self.deleted_count = deleted
        self.inserted_count = 0
        self.acknowledged = True


#: What the matcher and the writer implement. Anything else raises instead of
#: silently matching everything (or silently doing nothing): a test that reaches
#: the fake with ``$regex`` must fail loudly, not pass for the wrong reason.
QUERY_OPERATORS = frozenset({"$ne", "$in", "$nin", "$exists", "$lt", "$lte", "$gt", "$gte"})
UPDATE_OPERATORS = frozenset({"$set", "$unset", "$push", "$setOnInsert"})
PUSH_MODIFIERS = frozenset({"$each", "$slice"})


def _unsupported(kind: str, names) -> NotImplementedError:
    return NotImplementedError(
        f"tests/_fake_mongo.py does not implement the {kind} {sorted(names)}; "
        "add it to the fake (and to the operator set) so the test measures "
        "something, instead of matching every document or ignoring the write"
    )


class FakeCollection:
    """A minimal, list-backed stand-in for a pymongo collection."""

    def __init__(self) -> None:
        self.docs: list[dict] = []
        self._id = 0
        # writes that read-then-modify one document hold it, like Mongo's per-document atomicity
        self._lock = threading.RLock()

    def create_index(self, *a, **k):
        return "i"

    def with_options(self, codec_options=None, read_preference=None, write_concern=None,
                     read_concern=None):
        """pymongo's ``Collection.with_options``: a clone over the **same** documents.

        The keyword names are pymongo's (4.15.3, ``synchronous/collection.py``), so
        a caller that misspells one fails here as it would against a real
        collection. The options themselves change nothing in memory — there is
        one copy of the data and no replica to read from. The save path's
        read-back asks for ``ReadPreference.PRIMARY`` through this, and without
        it the read-back raised ``AttributeError`` against the fake.
        """
        return self

    def insert_one(self, d):
        self._id += 1
        d = dict(d)
        d.setdefault("_id", self._id)
        self.docs.append(d)
        return _Res(inserted=d["_id"])

    @staticmethod
    def _match(doc, q):
        top = [k for k in q if str(k).startswith("$")]
        if top:  # $or / $and / $expr / $where …
            raise _unsupported("query operator(s)", top)
        for k, v in q.items():
            found = _get_path(doc, k)
            actual = None if found is _MISSING else found
            if isinstance(v, dict) and any(str(op).startswith("$") for op in v):
                unknown = [op for op in v if str(op).startswith("$") and op not in QUERY_OPERATORS]
                if unknown:
                    raise _unsupported("query operator(s)", unknown)
                # ``$ne: None`` treats a missing field as null (excluded), like Mongo.
                if "$ne" in v and actual == v["$ne"]:
                    return False
                if "$in" in v and actual not in v["$in"]:
                    return False
                if "$nin" in v and actual in v["$nin"]:
                    return False
                if "$exists" in v and bool(found is not _MISSING) is not bool(v["$exists"]):
                    return False
                if "$lte" in v and not (actual is not None and actual <= v["$lte"]):
                    return False
                if "$lt" in v and not (actual is not None and actual < v["$lt"]):
                    return False
                if "$gte" in v and not (actual is not None and actual >= v["$gte"]):
                    return False
                if "$gt" in v and not (actual is not None and actual > v["$gt"]):
                    return False
            elif actual != v:
                return False
        return True

    def count_documents(self, q, *a, **k):
        return sum(1 for d in self.docs if self._match(d, q))

    def estimated_document_count(self):
        return len(self.docs)

    @staticmethod
    def _project(docs, projection):
        if projection:
            # Inclusion projections only — that is all this repo's queries use.
            # Honouring it matters: a caller that reads a field it did not ask
            # for passes against a fake that ignores projection and fails for
            # real.
            keep = {str(f) for f, on in projection.items() if on}
            if keep:
                keep.add("_id")
                docs = [{f: v for f, v in d.items() if f in keep} for d in docs]
        return docs

    def find(self, q, projection=None, *a, **k):
        docs = [copy.deepcopy(d) for d in self.docs if self._match(d, q)]
        return _FakeCursor(self._project(docs, projection))

    def update_many(self, q, u):
        modified = 0
        for d in self.docs:
            if self._match(d, q):
                self._apply(d, u)
                modified += 1
        return _Res(modified=modified)

    def find_one(self, q=None, projection=None, *a, sort=None, **k):
        """pymongo's shape: the projection is the **second positional** argument,
        and ``sort`` is a list of ``(key, direction)`` pairs.

        The repository's save path uses both — ``find_one(query, {"version": 1},
        sort=[("version", -1)])`` — so a fake that took only the query would
        raise ``TypeError`` there, and the save would report failure. As in
        Mongo, the sort runs before the projection, and a missing or ``None``
        field sorts lowest.
        """
        matches = [d for d in self.docs if self._match(d, q or {})]
        for key, direction in reversed(list(sort or [])):
            matches.sort(
                key=lambda d: (d.get(key) is not None, d.get(key)),
                reverse=int(direction) < 0,
            )
        if not matches:
            return None
        # Return an independent copy (like real pymongo) so a caller mutating the
        # result — e.g. oauth_store popping "_id" — can't corrupt stored docs.
        return self._project([copy.deepcopy(matches[0])], projection)[0]

    @staticmethod
    def _apply(doc, u, inserting=False):
        """``$setOnInsert`` writes only when the update inserts (an upsert that matched
        nothing), as in Mongo; on an existing document it is a no-op."""
        unknown = [op for op in u if op not in UPDATE_OPERATORS]
        if unknown:  # $inc / $addToSet / $pull …
            raise _unsupported("update operator(s)", unknown)
        if inserting:
            for field, value in u.get("$setOnInsert", {}).items():
                _set_path(doc, field, value)
        for field, value in u.get("$set", {}).items():
            _set_path(doc, field, value)
        for field in u.get("$unset", {}):
            _unset_path(doc, field)
        for field, spec in (u.get("$push") or {}).items():
            current = list(doc.get(field) or [])
            if isinstance(spec, dict) and "$each" in spec:
                modifiers = [m for m in spec if str(m).startswith("$") and m not in PUSH_MODIFIERS]
                if modifiers:  # $position / $sort
                    raise _unsupported("$push modifier(s)", modifiers)
                current.extend(spec["$each"])
                slice_n = spec.get("$slice")
                if isinstance(slice_n, int) and slice_n < 0:
                    current = current[slice_n:]
                elif isinstance(slice_n, int):
                    current = current[:slice_n]
            else:
                current.append(spec)
            doc[field] = current

    def update_one(self, q, u, upsert=False):
        with self._lock:
            for d in self.docs:
                if self._match(d, q):
                    self._apply(d, u)
                    return _Res(modified=1, matched=1)
            if upsert:
                self._id += 1
                nd = {"_id": self._id}
                for k, v in q.items():
                    if not isinstance(v, dict):
                        _set_path(nd, k, v)
                self._apply(nd, u, inserting=True)
                self.docs.append(nd)
                return _Res(upserted=nd["_id"], matched=0)
            return _Res(matched=0)

    def find_one_and_update(self, q, u, projection=None, sort=None, upsert=False,
                            return_document=False, **_kw):
        """pymongo's shape (4.15.3, ``synchronous/collection.py``): ``None`` when nothing
        matches and no upsert, the document **before** the update by default, the one
        after when ``return_document`` is ``ReturnDocument.AFTER`` (``True``).

        The match and the write happen under one lock, so two threads racing for the
        same document cannot both match it — the guarantee a single-use claim relies on.
        """
        if sort:
            raise _unsupported("find_one_and_update option(s)", ["sort"])
        with self._lock:
            for d in self.docs:
                if self._match(d, q):
                    before = copy.deepcopy(d)
                    self._apply(d, u)
                    chosen = copy.deepcopy(d) if return_document else before
                    return self._project([chosen], projection)[0]
            if not upsert:
                return None
            res = self.update_one(q, u, upsert=True)
            created = next(d for d in self.docs if d.get("_id") == res.upserted_id)
            return self._project([copy.deepcopy(created)], projection)[0] if return_document else None

    def delete_one(self, q):
        for i, d in enumerate(self.docs):
            if self._match(d, q):
                self.docs.pop(i)
                return _Res(deleted=1)
        return _Res()

    def delete_many(self, q):
        with self._lock:
            kept = [d for d in self.docs if not self._match(d, q)]
            deleted = len(self.docs) - len(kept)
            self.docs[:] = kept
        return _Res(deleted=deleted)

    def bulk_write(self, requests, ordered=True, **_kw):
        """pymongo's ``bulk_write``, for ``ReplaceOne`` — the operation this repo's writers send.

        The fields are read from pymongo's own operation object (``_filter``, ``_doc``,
        ``_upsert`` — ``pymongo/operations.py``, 4.15.3), so a test builds the request
        exactly as production does. Any other operation type raises.
        """
        from pymongo import ReplaceOne

        matched = upserted = 0
        with self._lock:
            for op in requests:
                if not isinstance(op, ReplaceOne):
                    raise _unsupported("bulk_write operation(s)", [type(op).__name__])
                replacement = copy.deepcopy(op._doc)
                for index, doc in enumerate(self.docs):
                    if self._match(doc, op._filter):
                        replacement.setdefault("_id", doc["_id"])
                        self.docs[index] = replacement
                        matched += 1
                        break
                else:
                    if op._upsert:
                        if "_id" not in replacement:
                            self._id += 1
                            replacement["_id"] = op._filter.get("_id", self._id)
                        self.docs.append(replacement)
                        upserted += 1
        return _BulkRes(matched=matched, upserted=upserted)


class _FakeCursor:
    """Iteration plus ``limit``/``sort`` — what a pass over a filter uses."""

    def __init__(self, docs: list[dict]) -> None:
        self._docs = docs

    def limit(self, n):
        self._docs = self._docs[: max(0, int(n))]
        return self

    def sort(self, key, direction=1):
        self._docs.sort(key=lambda d: d.get(key), reverse=int(direction) < 0)
        return self

    def __iter__(self):
        return iter(self._docs)


class AsyncFakeCollection:
    """Motor-shaped facade over :class:`FakeCollection`.

    Motor's surface differs from pymongo's in exactly two ways the jobs code
    touches: the writes are awaitable, and ``find`` returns a cursor drained
    with ``to_list``. The filter matching, the projection and the write
    semantics stay in one place — this only changes how they are reached, so
    a fix to the matcher cannot apply to one half and miss the other.
    """

    def __init__(self, sync: "FakeCollection | None" = None) -> None:
        self.sync = sync if sync is not None else FakeCollection()

    @property
    def docs(self):
        return self.sync.docs

    def find(self, q, projection=None, *a, **k):
        return _AsyncFakeCursor(self.sync.find(q, projection, *a, **k))

    async def update_one(self, q, u, upsert=False):
        return self.sync.update_one(q, u, upsert=upsert)

    async def find_one(self, q):
        return self.sync.find_one(q)

    async def insert_one(self, d):
        return self.sync.insert_one(d)


class _AsyncFakeCursor:
    """``limit`` then ``to_list`` — the shape motor callers use."""

    def __init__(self, cursor: _FakeCursor) -> None:
        self._cursor = cursor

    def limit(self, n):
        self._cursor.limit(n)
        return self

    def sort(self, key, direction=1):
        self._cursor.sort(key, direction)
        return self

    async def to_list(self, length=None):
        docs = list(self._cursor)
        if length is not None:
            docs = docs[: max(0, int(length))]
        return docs


class FakeTrackerDB:
    """The ``db.client[db_name]["job_runs"]`` shape ``JobTracker`` reaches its
    collection through — a ``DatabaseManager`` stand-in. ``runs`` is the same
    collection object, for reading a write back. To inject a misbehaving
    collection, assign into ``db.c["job_runs"]`` before the tracker's first
    write.
    """

    def __init__(self, name: str = "test") -> None:
        self.db = FakeDB(name)
        self.client = {name: self.db}
        self.db_name = name

    @property
    def runs(self) -> "FakeCollection":
        return self.db["job_runs"]


class FakeDB:
    """Duck-typed ``db[name]`` / ``db.name`` handle returning per-name FakeCollections."""

    def __init__(self, name: str = "fake_db") -> None:
        self.c: dict[str, FakeCollection] = {}
        self.name = name

    def __getitem__(self, name):
        return self.c.setdefault(name, FakeCollection())

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return self[name]
