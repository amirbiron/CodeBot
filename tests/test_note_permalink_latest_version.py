"""הקישור הקבוע של פתק על קובץ (``/note/<id>``) מפנה לגרסה האחרונה של הקובץ.

``file_id`` שבפתק הוא הגרסה שעליה הפתק נוצר, וכל שמירה של קובץ יוצרת מסמך חדש עם מזהה חדש.
עד נובמבר 2026 הקישור הפנה ל-``/md/<file_id>`` השמור, כלומר לחיצה על התראה או על הפעמון
הובילה לגרסה ישנה. עכשיו ``_note_file_target_id`` מוצא את הגרסה הפעילה האחרונה בזמן
הקריאה — לפי השם שבפתק, או לפי השם של המסמך השמור כשלפתק ישן אין שם.

הדמה של ``code_snippets`` מסננת כמו מונגו (שוויון, ``is_active``, ``user_id``) וממיינת לפי
מפרט המיון שהיא מקבלת — כדי שהטסט יבדוק *איזו* גרסה נבחרה, ולא רק שנבחרה אחת.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import pytest
from bson import ObjectId

pytest.importorskip("flask")

USER = 7
OTHER = 99
T0 = datetime(2026, 11, 1, tzinfo=timezone.utc)


def _oid(n: int) -> ObjectId:
    return ObjectId(f"{n:024x}")


#: גרסאות של ``a.md`` למשתמש — v1 (שעליה הפתק נוצר), v2, ו-v3 האחרונה.
V1, V2, V3 = _oid(0xA1), _oid(0xA2), _oid(0xA3)
#: קובץ באותו שם של משתמש אחר, בגרסה גבוהה יותר — אסור שישמש כיעד.
FOREIGN = _oid(0xF9)
#: קובץ ששמו שונה ל-``new.md``: כל הגרסאות נושאות את השם החדש.
R1, R2 = _oid(0xB1), _oid(0xB2)
#: קובץ בסל: כל הגרסאות לא פעילות.
TRASH1, TRASH2 = _oid(0xC1), _oid(0xC2)
#: שתי שמירות מקבילות שקיבלו אותו מספר גרסה — מכריעים ``updated_at`` ואז ``_id``.
TIE_OLD, TIE_NEW = _oid(0xD1), _oid(0xD2)

SNIPPETS = [
    {"_id": V1, "user_id": USER, "file_name": "a.md", "version": 1, "is_active": True, "updated_at": T0},
    {"_id": V2, "user_id": USER, "file_name": "a.md", "version": 2, "is_active": True,
     "updated_at": T0 + timedelta(hours=1)},
    {"_id": V3, "user_id": USER, "file_name": "a.md", "version": 3, "is_active": True,
     "updated_at": T0 + timedelta(hours=2)},
    {"_id": FOREIGN, "user_id": OTHER, "file_name": "a.md", "version": 9, "is_active": True,
     "updated_at": T0 + timedelta(hours=9)},
    {"_id": R1, "user_id": USER, "file_name": "new.md", "version": 1, "is_active": True, "updated_at": T0},
    {"_id": R2, "user_id": USER, "file_name": "new.md", "version": 2, "is_active": True,
     "updated_at": T0 + timedelta(hours=1)},
    {"_id": TRASH1, "user_id": USER, "file_name": "gone.md", "version": 1, "is_active": False, "updated_at": T0},
    {"_id": TRASH2, "user_id": USER, "file_name": "gone.md", "version": 2, "is_active": False,
     "updated_at": T0 + timedelta(hours=1)},
    {"_id": TIE_OLD, "user_id": USER, "file_name": "tie.md", "version": 4, "is_active": True, "updated_at": T0},
    {"_id": TIE_NEW, "user_id": USER, "file_name": "tie.md", "version": 4, "is_active": True,
     "updated_at": T0 + timedelta(minutes=1)},
]

NOTE_ON_OLD_VERSION = _oid(0x101)
NOTE_ON_RENAMED_FILE = _oid(0x102)
OLD_NOTE_WITHOUT_NAME = _oid(0x103)
NOTE_ON_TRASHED_FILE = _oid(0x104)
NOTE_OF_OTHER_USER = _oid(0x105)
NOTE_ON_A_TIE = _oid(0x106)
NOTE_ON_A_LARGE_FILE = _oid(0x107)

NOTES = [
    {"_id": NOTE_ON_OLD_VERSION, "user_id": USER, "file_id": str(V1), "file_name": "a.md"},
    # שינוי שם מעדכן את ``file_name`` בפתק (``sync_sticky_notes_on_rename``), ולא את ``file_id``.
    {"_id": NOTE_ON_RENAMED_FILE, "user_id": USER, "file_id": str(R1), "file_name": "new.md"},
    {"_id": OLD_NOTE_WITHOUT_NAME, "user_id": USER, "file_id": str(V1)},
    {"_id": NOTE_ON_TRASHED_FILE, "user_id": USER, "file_id": str(TRASH1), "file_name": "gone.md"},
    {"_id": NOTE_OF_OTHER_USER, "user_id": OTHER, "file_id": str(FOREIGN), "file_name": "a.md"},
    {"_id": NOTE_ON_A_TIE, "user_id": USER, "file_id": str(TIE_OLD), "file_name": "tie.md"},
    # קובץ גדול (``large_files``) — אין לו גרסאות ב-``code_snippets``.
    {"_id": NOTE_ON_A_LARGE_FILE, "user_id": USER, "file_id": "big-file-1", "file_name": "big.log"},
]


def _matches(doc, query):
    return all(doc.get(k) == v for k, v in query.items())


def _project(doc, projection):
    if not projection:
        return dict(doc)
    return {k: v for k, v in doc.items() if k == "_id" or projection.get(k)}


class _Coll:
    """``find_one`` בסמנטיקה של מונגו: סינון בשוויון, מיון לפי המפרט שהתקבל, והיטלה."""

    def __init__(self, docs):
        self.docs = list(docs)
        self.queries = []

    def find_one(self, query, projection=None, sort=None):
        self.queries.append(query)
        found = [d for d in self.docs if _matches(d, query)]
        for key, direction in reversed(sort or []):
            found.sort(key=lambda d: d.get(key), reverse=direction < 0)
        return _project(found[0], projection) if found else None


class _Broken(_Coll):
    def find_one(self, *_a, **_k):
        from pymongo.errors import ServerSelectionTimeoutError

        raise ServerSelectionTimeoutError("mongo is down")


class _DB:
    def __init__(self, snippets):
        self.sticky_notes = _Coll(NOTES)
        self.code_snippets = snippets


def _client(monkeypatch, snippets=None):
    import webapp.app as webapp_app
    from webapp.app import app

    db = _DB(snippets if snippets is not None else _Coll(SNIPPETS))
    monkeypatch.setattr(webapp_app, "get_db", lambda: db)
    app.config["TESTING"] = True
    c = app.test_client()
    with c.session_transaction() as sess:
        sess["user_id"] = USER
    return c, db


def _location(client, note_id, query=""):
    res = client.get(f"/note/{note_id}{query}")
    assert res.status_code == 302, res.status_code
    return res.headers["Location"]


def test_a_note_made_on_an_old_version_opens_the_latest_one(monkeypatch):
    client, _db = _client(monkeypatch)
    assert _location(client, NOTE_ON_OLD_VERSION) == f"/md/{V3}?note={NOTE_ON_OLD_VERSION}"


def test_the_note_and_the_thread_are_kept(monkeypatch):
    client, _db = _client(monkeypatch)
    thread = "c" * 24
    assert _location(client, NOTE_ON_OLD_VERSION, f"?thread={thread}") == (
        f"/md/{V3}?note={NOTE_ON_OLD_VERSION}&thread={thread}"
    )


def test_a_note_on_a_renamed_file_opens_the_latest_version_under_the_new_name(monkeypatch):
    client, _db = _client(monkeypatch)
    assert _location(client, NOTE_ON_RENAMED_FILE) == f"/md/{R2}?note={NOTE_ON_RENAMED_FILE}"


def test_an_old_note_without_a_name_finds_it_through_the_stored_version(monkeypatch):
    """השם נגזר מהמסמך השמור — והשאילתה עליו תחומה למשתמש."""
    client, db = _client(monkeypatch)
    assert _location(client, OLD_NOTE_WITHOUT_NAME) == f"/md/{V3}?note={OLD_NOTE_WITHOUT_NAME}"
    by_id = [q for q in db.code_snippets.queries if "_id" in q]
    assert by_id == [{"_id": V1, "user_id": USER}], by_id


def test_a_file_in_the_recycle_bin_opens_the_stored_version_as_before(monkeypatch):
    client, _db = _client(monkeypatch)
    assert _location(client, NOTE_ON_TRASHED_FILE) == f"/md/{TRASH1}?note={NOTE_ON_TRASHED_FILE}"


def test_a_large_file_without_versions_opens_the_stored_id_as_before(monkeypatch):
    client, _db = _client(monkeypatch)
    assert _location(client, NOTE_ON_A_LARGE_FILE) == f"/md/big-file-1?note={NOTE_ON_A_LARGE_FILE}"


def test_a_note_of_another_user_is_not_exposed(monkeypatch):
    client, _db = _client(monkeypatch)
    assert _location(client, NOTE_OF_OTHER_USER) == "/boards"


def test_a_file_with_the_same_name_of_another_user_is_never_the_target(monkeypatch):
    """ל-``a.md`` של משתמש אחר יש גרסה 9 — והיעד הוא בכל זאת v3 של המשתמש."""
    client, db = _client(monkeypatch)
    _location(client, NOTE_ON_OLD_VERSION)
    by_name = [q for q in db.code_snippets.queries if "file_name" in q]
    assert by_name and all(q.get("user_id") == USER for q in by_name), by_name


def test_two_saves_with_the_same_version_are_decided_by_updated_at(monkeypatch):
    """אין אינדקס ייחודי על מספר הגרסה, ולכן ``version`` לבדו אינו מכריע (``_LATEST_VERSION_SORT``)."""
    client, _db = _client(monkeypatch)
    assert _location(client, NOTE_ON_A_TIE) == f"/md/{TIE_NEW}?note={NOTE_ON_A_TIE}"


def test_a_database_failure_keeps_the_link_working(monkeypatch, caplog):
    """כשל בחיפוש הגרסה האחרונה — הקישור לגרסה השמורה, כמו קודם, ועקבה בלוג."""
    client, _db = _client(monkeypatch, snippets=_Broken([]))
    with caplog.at_level(logging.WARNING, logger="webapp.app"):
        assert _location(client, NOTE_ON_OLD_VERSION) == f"/md/{V1}?note={NOTE_ON_OLD_VERSION}"
    assert any("latest file version lookup failed" in r.getMessage() and r.exc_info for r in caplog.records)


def test_redirecting_to_the_stored_version_breaks_the_test(monkeypatch):
    """ריצת בקרה: ההפניה הישנה — ל-``file_id`` השמור — מחזירה את הגרסה הישנה."""
    import webapp.app as webapp_app

    monkeypatch.setattr(webapp_app, "_note_file_target_id", lambda _db, _uid, note: str(note.get("file_id")))
    client, _db = _client(monkeypatch)
    assert _location(client, NOTE_ON_OLD_VERSION) == f"/md/{V1}?note={NOTE_ON_OLD_VERSION}"


def test_sorting_by_version_alone_breaks_the_tie_test(monkeypatch):
    """ריצת בקרה: מיון לפי ``version`` בלבד — בתיקו הנבחרת היא הראשונה בסדר הטבעי, הישנה."""
    import webapp.app as webapp_app

    monkeypatch.setattr(webapp_app, "_LATEST_VERSION_SORT", [("version", -1)])
    client, _db = _client(monkeypatch)
    assert _location(client, NOTE_ON_A_TIE) == f"/md/{TIE_OLD}?note={NOTE_ON_A_TIE}"
