"""תור העיבוד של ה-EmbeddingWorker, וההגנות סביבו.

הרקע (אישו #3332):

* ``chunkerVersion`` הוא מה שמחליף פקודת re-index ידנית: ה-worker מזהה
  לבד קבצים שנחתכו לפי כלל ישן. אבל אם ה-backlog הזה היה מתערבב עם
  הדגלים המפורשים ב-``$or`` אחד, re-index מלא של הקורפוס (שעות) היה
  חוסם קובץ שנשמר לפני רגע.
* שמירת גרסה חדשה אינה מכבה את הקודמת, ולכן ``is_active: True`` לבדו
  מחזיר גם גרסאות היסטוריות.
"""

import asyncio

import pytest
from bson import ObjectId

import database.manager as manager_mod
from services.chunking_service import CHUNKER_VERSION


class _Cursor(list):
    def limit(self, n):
        return _Cursor(self[:n])


class _Files:
    def __init__(self, docs):
        self.docs = list(docs)
        self.queries = []

    def find(self, query, projection=None):
        self.queries.append((query, projection))
        return _Cursor(self._match(query))

    def find_one(self, query, projection=None, sort=None):
        rows = self._match(query)
        if sort:
            for field, direction in reversed(sort):
                rows.sort(key=lambda d: d.get(field, 0), reverse=direction < 0)
        return dict(rows[0]) if rows else None

    def _match(self, query):
        out = []
        for doc in self.docs:
            if self._matches(doc, query):
                out.append(dict(doc))
        return out

    @staticmethod
    def _matches(doc, query):
        for key, cond in query.items():
            if key == "$or":
                if not any(_Files._matches(doc, c) for c in cond):
                    return False
                continue
            if isinstance(cond, dict):
                if "$ne" in cond and doc.get(key) == cond["$ne"]:
                    return False
                if "$exists" in cond and (key in doc) != cond["$exists"]:
                    return False
                continue
            if doc.get(key) != cond:
                return False
        return True


class _DB:
    def __init__(self, files):
        self.code_snippets = files


@pytest.fixture()
def files(monkeypatch):
    def _install(docs):
        coll = _Files(docs)
        monkeypatch.setattr(manager_mod, "_get_raw_db", lambda: _DB(coll))
        return coll
    return _install


class TestQueuePriority:
    def test_explicit_flags_come_before_the_rechunk_backlog(self, files):
        """קובץ שנשמר או שוחזר עכשיו לא ממתין מאחורי re-index של כל הקורפוס."""
        backlog = [
            {"_id": f"old{i}", "is_active": True, "contentHash": "h",
             "needs_embedding": False, "needs_chunking": False, "chunkerVersion": 1}
            for i in range(20)
        ]
        urgent = {"_id": "fresh", "is_active": True, "needs_embedding": True,
                  "chunkerVersion": CHUNKER_VERSION}
        files(backlog + [urgent])

        picked = asyncio.run(manager_mod.get_snippets_needing_processing(limit=5))

        assert "fresh" in [d["_id"] for d in picked]

    def test_backlog_fills_the_remaining_slots(self, files):
        files([
            {"_id": "old1", "is_active": True, "contentHash": "h",
             "needs_embedding": False, "needs_chunking": False, "chunkerVersion": 1},
            {"_id": "old2", "is_active": True, "contentHash": "h",
             "needs_embedding": False, "needs_chunking": False},  # no field at all
        ])

        picked = asyncio.run(manager_mod.get_snippets_needing_processing(limit=5))

        assert {d["_id"] for d in picked} == {"old1", "old2"}

    def test_a_current_file_is_not_picked_up_again(self, files):
        """זו הנקודה שמונעת מהתור להיסתם: מסמך מטופל לא חוזר בכל סבב."""
        files([{
            "_id": "done", "is_active": True, "contentHash": "h",
            "needs_embedding": False, "needs_chunking": False,
            "chunkerVersion": CHUNKER_VERSION,
        }])

        assert asyncio.run(manager_mod.get_snippets_needing_processing(limit=5)) == []

    def test_no_duplicates_across_the_two_queries(self, files):
        files([{
            "_id": "both", "is_active": True, "needs_embedding": True, "chunkerVersion": 1,
        }])

        picked = asyncio.run(manager_mod.get_snippets_needing_processing(limit=5))

        assert [d["_id"] for d in picked] == ["both"]

    def test_projection_carries_the_fields_the_worker_reads(self, files):
        coll = files([{"_id": "x", "is_active": True, "needs_embedding": True}])
        asyncio.run(manager_mod.get_snippets_needing_processing(limit=5))

        projection = coll.queries[0][1]
        for field in ("chunkerVersion", "contentHash", "needs_embedding", "file_name", "code"):
            assert projection.get(field) == 1, f"worker reads {field} but it is not projected"


class TestLatestVersion:
    def test_latest_active_version_is_recognised(self, files):
        newest = ObjectId()
        files([
            {"_id": newest, "user_id": 7, "file_name": "a.py", "is_active": True, "version": 3},
            {"_id": ObjectId(), "user_id": 7, "file_name": "a.py", "is_active": True, "version": 2},
        ])

        assert asyncio.run(manager_mod.is_latest_active_snippet(7, "a.py", newest)) is True

    def test_superseded_version_is_rejected(self, files):
        older = ObjectId()
        files([
            {"_id": ObjectId(), "user_id": 7, "file_name": "a.py", "is_active": True, "version": 3},
            {"_id": older, "user_id": 7, "file_name": "a.py", "is_active": True, "version": 2},
        ])

        assert asyncio.run(manager_mod.is_latest_active_snippet(7, "a.py", older)) is False

    def test_unknown_file_defaults_to_processing(self, files):
        """בספק — מעבדים. עדיף קובץ מיותר מאשר לדלג על קובץ אמיתי."""
        files([])
        assert asyncio.run(manager_mod.is_latest_active_snippet(7, "a.py", ObjectId())) is True

    def test_missing_file_name_defaults_to_processing(self, files):
        files([])
        assert asyncio.run(manager_mod.is_latest_active_snippet(7, "", ObjectId())) is True
