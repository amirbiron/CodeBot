"""Shared in-memory fake for the pymongo handle used by the OAuth store tests.

Repo convention is hand-rolled fakes (no mongomock). The OAuth store, provider
and consent-route tests all need the same duck-typed Mongo stand-in, so the
collection semantics — filter matching (``$ne``, ``$in`` and the range
operators), upsert, ``update_many``, counting, and the delete/modify counts
our store now reads — live here in one place. The migration-script tests
reach the DB as ``db.note_reminders`` and read ``db.name``, so ``FakeDB``
also answers attribute access like a real ``Database`` handle.

Usage::

    from tests._fake_mongo import FakeDB
    store = OAuthStore(FakeDB())
"""

from __future__ import annotations

import copy
from typing import Any


class _Res:
    """Mimics pymongo write results (only the fields our store inspects)."""

    def __init__(self, modified: int = 0, upserted: Any = None, deleted: int = 0) -> None:
        self.modified_count = modified
        self.upserted_id = upserted
        self.deleted_count = deleted


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
        return _FakeCursor([copy.deepcopy(d) for d in self.docs if self._match(d, q)])

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

    def update_one(self, q, u, upsert=False):
        for d in self.docs:
            if self._match(d, q):
                d.update(u.get("$set", {}))
                return _Res(modified=1)
        if upsert:
            self._id += 1
            nd = {"_id": self._id}
            for k, v in q.items():
                if not isinstance(v, dict):
                    nd[k] = v
            nd.update(u.get("$set", {}))
            self.docs.append(nd)
            return _Res(upserted=self._id)
        return _Res()

    def delete_one(self, q):
        for i, d in enumerate(self.docs):
            if self._match(d, q):
                self.docs.pop(i)
                return _Res(deleted=1)
        return _Res()


class _FakeCursor:
    """Iteration plus ``limit`` — what a report-only pass over a filter uses."""

    def __init__(self, docs: list[dict]) -> None:
        self._docs = docs

    def limit(self, n):
        self._docs = self._docs[: max(0, int(n))]
        return self

    def __iter__(self):
        return iter(self._docs)


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
