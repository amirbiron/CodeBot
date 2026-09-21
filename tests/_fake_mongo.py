"""Shared in-memory fake for the Mongo handles the tests drive.

Repo convention is hand-rolled fakes (no mongomock). Several suites need the
same duck-typed stand-in, so the collection semantics — filter matching
(``$ne``, ``$in``, ``$nin``, ``$exists`` and the range operators), inclusion
projections, upsert, ``$push`` with ``$each``/``$slice``, ``$unset``,
``update_many``, counting, and the matched/modified/deleted counts the callers
read — live here in one place. The migration-script tests reach the DB as
``db.note_reminders`` and read ``db.name``, so ``FakeDB`` also answers
attribute access like a real ``Database`` handle.

``AsyncFakeCollection`` is the motor-shaped facade over the same object: the
jobs code awaits its writes and drains ``find`` with ``to_list``. It delegates,
so there is one matcher and one set of write semantics, not two that drift.

Usage::

    from tests._fake_mongo import FakeDB
    store = OAuthStore(FakeDB())
"""

from __future__ import annotations

import copy
from typing import Any


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
    ) -> None:
        self.modified_count = modified
        self.upserted_id = upserted
        self.deleted_count = deleted
        self.matched_count = modified if matched is None else matched


class FakeCollection:
    """A minimal, list-backed stand-in for a pymongo collection."""

    def __init__(self) -> None:
        self.docs: list[dict] = []
        self._id = 0

    def create_index(self, *a, **k):
        return "i"

    def insert_one(self, d):
        self._id += 1
        d = dict(d)
        d.setdefault("_id", self._id)
        self.docs.append(d)
        return _Res()

    @staticmethod
    def _match(doc, q):
        for k, v in q.items():
            actual = doc.get(k)
            if isinstance(v, dict) and any(str(op).startswith("$") for op in v):
                # ``$ne: None`` treats a missing field as null (excluded), like Mongo.
                if "$ne" in v and actual == v["$ne"]:
                    return False
                if "$in" in v and actual not in v["$in"]:
                    return False
                if "$nin" in v and actual in v["$nin"]:
                    return False
                if "$exists" in v and bool(k in doc) is not bool(v["$exists"]):
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

    def find(self, q, projection=None, *a, **k):
        docs = [copy.deepcopy(d) for d in self.docs if self._match(d, q)]
        if projection:
            # Inclusion projections only — that is all this repo's queries use.
            # Honouring it matters: a caller that reads a field it did not ask
            # for passes against a fake that ignores projection and fails for
            # real.
            keep = {str(f) for f, on in projection.items() if on}
            if keep:
                keep.add("_id")
                docs = [{f: v for f, v in d.items() if f in keep} for d in docs]
        return _FakeCursor(docs)

    def update_many(self, q, u):
        modified = 0
        for d in self.docs:
            if self._match(d, q):
                d.update(u.get("$set", {}))
                modified += 1
        return _Res(modified=modified)

    def find_one(self, q):
        # Return an independent copy (like real pymongo) so a caller mutating the
        # result — e.g. oauth_store popping "_id" — can't corrupt stored docs.
        match = next((d for d in self.docs if self._match(d, q)), None)
        return copy.deepcopy(match) if match is not None else None

    @staticmethod
    def _apply(doc, u):
        doc.update(u.get("$set", {}))
        for field in u.get("$unset", {}):
            doc.pop(field, None)
        for field, spec in (u.get("$push") or {}).items():
            current = list(doc.get(field) or [])
            if isinstance(spec, dict) and "$each" in spec:
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
        for d in self.docs:
            if self._match(d, q):
                self._apply(d, u)
                return _Res(modified=1, matched=1)
        if upsert:
            self._id += 1
            nd = {"_id": self._id}
            for k, v in q.items():
                if not isinstance(v, dict):
                    nd[k] = v
            self._apply(nd, u)
            self.docs.append(nd)
            return _Res(upserted=self._id, matched=0)
        return _Res(matched=0)

    def delete_one(self, q):
        for i, d in enumerate(self.docs):
            if self._match(d, q):
                self.docs.pop(i)
                return _Res(deleted=1)
        return _Res()


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
