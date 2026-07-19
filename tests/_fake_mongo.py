"""Shared in-memory fake for the pymongo handle used by the OAuth store tests.

Repo convention is hand-rolled fakes (no mongomock). The OAuth store, provider
and consent-route tests all need the same duck-typed Mongo stand-in, so the
collection semantics — filter matching (incl. ``$ne``), upsert, and the
delete/modify counts our store now reads — live here in one place.

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
            if isinstance(v, dict) and "$ne" in v:
                if doc.get(k) == v["$ne"]:
                    return False
            elif doc.get(k) != v:
                return False
        return True

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


class FakeDB:
    """Duck-typed ``db[name]`` handle returning per-name FakeCollections."""

    def __init__(self) -> None:
        self.c: dict[str, FakeCollection] = {}

    def __getitem__(self, name):
        return self.c.setdefault(name, FakeCollection())
