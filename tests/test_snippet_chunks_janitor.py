"""ג'וב ניקוי הצ'אנקים היתומים.

הרקע (אישו #3332): שני מקורות של יתומים אינם עוברים דרך קוד אפליקציה בכלל.

1. **פקיעת סל המיחזור** נעשית ב-TTL index על ``deleted_expires_at``. מונגו
   מוחק את מסמך הקובץ בצד השרת, ואף שורת קוד שלנו לא רצה.
2. **גרסאות שהוחלפו** — שמירת גרסה חדשה אינה מכבה את הקודמת, ולכן כל גרסה
   היסטורית נשארת מאונדקסת. נמדד בפרודקשן: ל-``Programming.svg`` שלושה
   מסמכי צ'אנק פעילים, אחד לכל גרסה.

הדמות כאן מממשת בפועל את השאילתות שהג'וב מריץ, ולא מחזירה תשובה קבועה —
אחרת הטסט היה עובר גם על ג'וב שאינו מסנן כלום.
"""

import pytest
from bson import ObjectId

import services.snippet_chunks_janitor as janitor


class _Result:
    def __init__(self, deleted=0):
        self.deleted_count = deleted


class _Chunks:
    def __init__(self, docs):
        self.docs = list(docs)
        self.deleted_filters = []

    def aggregate(self, pipeline):
        assert "$group" in pipeline[0], pipeline
        groups = {}
        for doc in self.docs:
            key = (doc["userId"], doc["snippetId"])
            groups[key] = groups.get(key, 0) + 1
        return [
            {"_id": {"userId": u, "snippetId": s}, "chunks": n}
            for (u, s), n in groups.items()
        ]

    def delete_many(self, query):
        self.deleted_filters.append(query)
        user_id = query["userId"]
        ids = set(query["snippetId"]["$in"])
        before = len(self.docs)
        self.docs = [
            d for d in self.docs
            if not (d["userId"] == user_id and d["snippetId"] in ids)
        ]
        return _Result(deleted=before - len(self.docs))


class _Files:
    def __init__(self, docs):
        self.docs = list(docs)

    def find(self, query, projection=None):
        wanted = set(query["_id"]["$in"])
        return [dict(d) for d in self.docs if d["_id"] in wanted]

    def aggregate(self, pipeline):
        match = pipeline[0]["$match"]
        rows = [
            d for d in self.docs
            if d.get("is_active")
            and d["user_id"] in match["user_id"]["$in"]
            and d["file_name"] in match["file_name"]["$in"]
        ]
        rows.sort(
            key=lambda d: (d["user_id"], d["file_name"], -d.get("version", 0)),
        )
        out, seen = [], set()
        for row in rows:
            key = (row["user_id"], row["file_name"])
            if key in seen:
                continue
            seen.add(key)
            out.append({"_id": {"user_id": key[0], "file_name": key[1]}, "latest": row["_id"]})
        return out


class _DB:
    def __init__(self, chunks, files):
        self._c = {"snippet_chunks": chunks, "code_snippets": files}

    def __getitem__(self, name):
        return self._c[name]


LIVE = ObjectId()
OLD_VERSION = ObjectId()
TRASHED = ObjectId()
GONE = ObjectId()


def _build(monkeypatch, chunk_docs, file_docs):
    chunks = _Chunks(chunk_docs)
    files = _Files(file_docs)
    monkeypatch.setattr(janitor, "_get_raw_db", lambda: _DB(chunks, files))
    return chunks, files


@pytest.fixture()
def world(monkeypatch):
    chunk_docs = (
        [{"userId": 7, "snippetId": LIVE}] * 3
        + [{"userId": 7, "snippetId": OLD_VERSION}] * 2
        + [{"userId": 7, "snippetId": TRASHED}] * 4
        + [{"userId": 7, "snippetId": GONE}] * 5
    )
    file_docs = [
        {"_id": LIVE, "user_id": 7, "file_name": "a.py", "is_active": True, "version": 2},
        {"_id": OLD_VERSION, "user_id": 7, "file_name": "a.py", "is_active": True, "version": 1},
        {"_id": TRASHED, "user_id": 7, "file_name": "b.py", "is_active": False, "version": 1},
        # GONE אינו קיים ב-code_snippets כלל — פקע ב-TTL של סל המיחזור.
    ]
    return _build(monkeypatch, chunk_docs, file_docs)


def test_orphans_are_deleted_and_the_live_version_survives(world):
    chunks, _files = world

    report = janitor.cleanup_orphan_snippet_chunks()

    assert report["ok"] is True
    assert report["orphan_snippets"] == 3  # old version + trashed + gone
    assert report["deleted_chunks"] == 2 + 4 + 5
    assert [d["snippetId"] for d in chunks.docs] == [LIVE] * 3


def test_superseded_version_is_an_orphan(world):
    """זה החלק שהגדרת "אין מסמך" הייתה מפספסת: המסמך קיים, פעיל, ופשוט
    אינו הגרסה האחרונה."""
    chunks, _files = world
    janitor.cleanup_orphan_snippet_chunks()
    assert OLD_VERSION not in {d["snippetId"] for d in chunks.docs}


def test_dry_run_reports_without_deleting(world):
    chunks, _files = world

    report = janitor.cleanup_orphan_snippet_chunks(dry_run=True)

    assert report["orphan_snippets"] == 3
    assert report["deleted_chunks"] == 0
    assert len(chunks.docs) == 14, "dry run deleted data"


def test_every_delete_is_scoped_to_a_user(world):
    """מחיקה חוצת-משתמשים היא בדיוק סוג התקלה שאסור לג'וב תחזוקה."""
    chunks, _files = world
    janitor.cleanup_orphan_snippet_chunks()

    assert chunks.deleted_filters
    for query in chunks.deleted_filters:
        assert "userId" in query and "snippetId" in query


def test_non_objectid_snippet_ids_are_reported_not_deleted(monkeypatch):
    """מזהה מסוג אחר לא יימצא ב-``$lookup`` ולכן ייראה יתום.

    זה בדיוק הכשל השקט שאסור לנו — מדווחים ולא מוחקים.
    """
    chunks, _files = _build(
        monkeypatch,
        [{"userId": 7, "snippetId": "legacy-string-id"}] * 3,
        [],
    )

    report = janitor.cleanup_orphan_snippet_chunks()

    assert report["skipped_non_objectid"] == 1
    assert report["deleted_chunks"] == 0
    assert len(chunks.docs) == 3


def test_no_database_is_reported_as_not_ok(monkeypatch):
    """``ok=False`` אינו "אין מה לנקות" — הוא "לא הצלחתי לבדוק".

    ה-job runner ב-main.py מסתמך על זה כדי לא לרשום ריצה כושלת כהצלחה.
    """
    monkeypatch.setattr(janitor, "_get_raw_db", lambda: None)

    report = janitor.cleanup_orphan_snippet_chunks()

    assert report["ok"] is False
    assert report["reason"] == "no_db"


def test_empty_collection_is_ok(monkeypatch):
    _build(monkeypatch, [], [])
    report = janitor.cleanup_orphan_snippet_chunks()
    assert report["ok"] is True and report["orphan_snippets"] == 0
