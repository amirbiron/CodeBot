"""הקישור הקבוע של פתק על קובץ (``/note/<id>``) מפנה לגרסה האחרונה של הקובץ.

``file_id`` שבפתק הוא הגרסה שעליה הפתק נוצר, וכל שמירה של קובץ יוצרת מסמך חדש עם מזהה חדש.
עד נובמבר 2026 הקישור הפנה ל-``/md/<file_id>`` השמור, כלומר לחיצה על התראה או על הפעמון
הובילה לגרסה ישנה. עכשיו ``_note_file_target`` מוצא את הגרסה הפעילה האחרונה בזמן
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
#: קובץ גדול (``large_files``) — **באותו שם** של קובץ רגיל, ``a.md``. אין לו גרסאות.
LARGE = _oid(0xE1)

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

#: קבצי HTML — הפתקים שלהם יושבים על ``/html/<id>`` (``_file_view_endpoint``).
#: ``page.html`` בשתי גרסאות; ``landing`` הוא HTML לפי השפה בלבד, בלי סיומת; ``both.md`` עונה על שני הכללים.
H1, H2 = _oid(0x1A1), _oid(0x1A2)
LANDING1, LANDING2 = _oid(0x1B1), _oid(0x1B2)
BOTH = _oid(0x1C1)
HTML_TRASH = _oid(0x1D1)
LARGE_HTML = _oid(0x1E1)

SNIPPETS += [
    {"_id": H1, "user_id": USER, "file_name": "page.html", "version": 1, "is_active": True, "updated_at": T0,
     "programming_language": "html"},
    {"_id": H2, "user_id": USER, "file_name": "page.html", "version": 2, "is_active": True,
     "updated_at": T0 + timedelta(hours=1), "programming_language": "html"},
    {"_id": LANDING1, "user_id": USER, "file_name": "landing", "version": 1, "is_active": True, "updated_at": T0,
     "programming_language": "html"},
    {"_id": LANDING2, "user_id": USER, "file_name": "landing", "version": 2, "is_active": True,
     "updated_at": T0 + timedelta(hours=1), "programming_language": "html"},
    {"_id": BOTH, "user_id": USER, "file_name": "both.md", "version": 1, "is_active": True, "updated_at": T0,
     "programming_language": "html"},
    {"_id": HTML_TRASH, "user_id": USER, "file_name": "old.html", "version": 1, "is_active": False,
     "updated_at": T0, "programming_language": "html"},
]

NOTE_ON_OLD_VERSION = _oid(0x101)
NOTE_ON_RENAMED_FILE = _oid(0x102)
OLD_NOTE_WITHOUT_NAME = _oid(0x103)
NOTE_ON_TRASHED_FILE = _oid(0x104)
NOTE_OF_OTHER_USER = _oid(0x105)
NOTE_ON_A_TIE = _oid(0x106)
NOTE_ON_A_LARGE_FILE = _oid(0x107)
NOTE_ON_A_LARGE_FILE_IN_THE_BIN = _oid(0x108)

NOTES = [
    {"_id": NOTE_ON_OLD_VERSION, "user_id": USER, "file_id": str(V1), "file_name": "a.md"},
    # שינוי שם מעדכן את ``file_name`` בפתק (``sync_sticky_notes_on_rename``), ולא את ``file_id``.
    {"_id": NOTE_ON_RENAMED_FILE, "user_id": USER, "file_id": str(R1), "file_name": "new.md"},
    {"_id": OLD_NOTE_WITHOUT_NAME, "user_id": USER, "file_id": str(V1)},
    {"_id": NOTE_ON_TRASHED_FILE, "user_id": USER, "file_id": str(TRASH1), "file_name": "gone.md"},
    {"_id": NOTE_OF_OTHER_USER, "user_id": OTHER, "file_id": str(FOREIGN), "file_name": "a.md"},
    {"_id": NOTE_ON_A_TIE, "user_id": USER, "file_id": str(TIE_OLD), "file_name": "tie.md"},
    # קובץ גדול ששמו ``a.md`` — כמו הקובץ הרגיל. החיפוש לפי שם רואה רק את ``code_snippets``.
    {"_id": NOTE_ON_A_LARGE_FILE, "user_id": USER, "file_id": str(LARGE), "file_name": "a.md"},
    {"_id": NOTE_ON_A_LARGE_FILE_IN_THE_BIN, "user_id": USER, "file_id": str(_oid(0xE2)), "file_name": "a.md"},
]

NOTE_ON_HTML = _oid(0x201)
NOTE_ON_HTML_BY_LANGUAGE = _oid(0x202)
NOTE_ON_BOTH = _oid(0x203)
NOTE_ON_HTML_IN_THE_BIN = _oid(0x204)
NOTE_ON_LARGE_HTML = _oid(0x205)
OLD_NOTE_ON_HTML_WITHOUT_NAME = _oid(0x206)

NOTES += [
    {"_id": NOTE_ON_HTML, "user_id": USER, "file_id": str(H1), "file_name": "page.html"},
    {"_id": NOTE_ON_HTML_BY_LANGUAGE, "user_id": USER, "file_id": str(LANDING1), "file_name": "landing"},
    {"_id": NOTE_ON_BOTH, "user_id": USER, "file_id": str(BOTH), "file_name": "both.md"},
    {"_id": NOTE_ON_HTML_IN_THE_BIN, "user_id": USER, "file_id": str(HTML_TRASH), "file_name": "old.html"},
    {"_id": NOTE_ON_LARGE_HTML, "user_id": USER, "file_id": str(LARGE_HTML), "file_name": "big.html"},
    {"_id": OLD_NOTE_ON_HTML_WITHOUT_NAME, "user_id": USER, "file_id": str(LANDING1)},
]

LARGE_FILES = [
    {"_id": LARGE, "user_id": USER, "file_name": "a.md", "is_active": True},
    {"_id": _oid(0xE2), "user_id": USER, "file_name": "a.md", "is_active": False},
    {"_id": LARGE_HTML, "user_id": USER, "file_name": "big.html", "is_active": True, "programming_language": "html"},
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
        self.large_files = _Coll(LARGE_FILES)


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


def test_a_large_file_opens_itself_and_not_a_regular_file_with_the_same_name(monkeypatch):
    """לקובץ גדול אין גרסאות, והחיפוש לפי שם רואה רק את ``code_snippets`` — ולכן ``a.md`` הרגיל
    (v3) היה נבחר במקומו. הבדיקה של ``large_files`` באה לפני החיפוש לפי שם, תחומה למשתמש,
    ומבקשת רק את ``_id``."""
    client, db = _client(monkeypatch)
    assert _location(client, NOTE_ON_A_LARGE_FILE) == f"/md/{LARGE}?note={NOTE_ON_A_LARGE_FILE}"
    assert db.large_files.queries == [{"_id": LARGE, "user_id": USER}], db.large_files.queries
    assert not [q for q in db.code_snippets.queries if "file_name" in q], db.code_snippets.queries


def test_a_large_file_in_the_recycle_bin_opens_itself_as_before(monkeypatch):
    client, _db = _client(monkeypatch)
    assert _location(client, NOTE_ON_A_LARGE_FILE_IN_THE_BIN) == (
        f"/md/{_oid(0xE2)}?note={NOTE_ON_A_LARGE_FILE_IN_THE_BIN}"
    )


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

    monkeypatch.setattr(webapp_app, "_note_file_target",
                        lambda _db, _uid, note: (str(note.get("file_id")), "md_preview"))
    client, _db = _client(monkeypatch)
    assert _location(client, NOTE_ON_OLD_VERSION) == f"/md/{V1}?note={NOTE_ON_OLD_VERSION}"


def test_sorting_by_version_alone_breaks_the_tie_test(monkeypatch):
    """ריצת בקרה: מיון לפי ``version`` בלבד — בתיקו הנבחרת היא הראשונה בסדר הטבעי, הישנה."""
    import webapp.app as webapp_app

    monkeypatch.setattr(webapp_app, "_LATEST_VERSION_SORT", [("version", -1)])
    client, _db = _client(monkeypatch)
    assert _location(client, NOTE_ON_A_TIE) == f"/md/{TIE_OLD}?note={NOTE_ON_A_TIE}"


# -- פתק על קובץ HTML: לתצוגת הדפדפן, שעליה הפתקים שלו יושבים (``_file_view_endpoint``) --


def test_a_note_on_an_html_file_opens_the_browser_view_of_the_latest_version(monkeypatch):
    client, _db = _client(monkeypatch)
    assert _location(client, NOTE_ON_HTML) == f"/html/{H2}?note={NOTE_ON_HTML}"


def test_an_html_file_without_the_extension_is_recognised_by_its_language(monkeypatch):
    """השפה באה מהמסמך שהשאילתה כבר מביאה — אין שאילתה נוספת בשבילה."""
    client, db = _client(monkeypatch)
    assert _location(client, NOTE_ON_HTML_BY_LANGUAGE) == f"/html/{LANDING2}?note={NOTE_ON_HTML_BY_LANGUAGE}"
    assert not [q for q in db.code_snippets.queries if "_id" in q], db.code_snippets.queries


def test_an_old_html_note_without_a_name_reads_the_language_from_the_latest_version(monkeypatch):
    """אותן שתי שאילתות כמו לפתק Markdown בלי שם: לפי ``_id`` לשם, ולפי השם לגרסה האחרונה."""
    client, db = _client(monkeypatch)
    assert _location(client, OLD_NOTE_ON_HTML_WITHOUT_NAME) == (
        f"/html/{LANDING2}?note={OLD_NOTE_ON_HTML_WITHOUT_NAME}"
    )
    by_id = [q for q in db.code_snippets.queries if "_id" in q]
    assert by_id == [{"_id": LANDING1, "user_id": USER}], by_id


def test_a_file_that_is_both_markdown_and_html_keeps_opening_in_the_markdown_view(monkeypatch):
    """עד היום פתק על קובץ נפתח תמיד ב-``/md/``; קובץ שעונה על שני הכללים לא זז."""
    client, _db = _client(monkeypatch)
    assert _location(client, NOTE_ON_BOTH) == f"/md/{BOTH}?note={NOTE_ON_BOTH}"


def test_an_html_file_in_the_recycle_bin_opens_the_stored_version_in_the_browser_view(monkeypatch):
    client, _db = _client(monkeypatch)
    assert _location(client, NOTE_ON_HTML_IN_THE_BIN) == f"/html/{HTML_TRASH}?note={NOTE_ON_HTML_IN_THE_BIN}"


def test_a_large_html_file_opens_itself_in_the_browser_view(monkeypatch):
    client, db = _client(monkeypatch)
    assert _location(client, NOTE_ON_LARGE_HTML) == f"/html/{LARGE_HTML}?note={NOTE_ON_LARGE_HTML}"
    assert db.large_files.queries == [{"_id": LARGE_HTML, "user_id": USER}], db.large_files.queries


def test_a_database_failure_on_an_html_note_still_opens_the_browser_view(monkeypatch, caplog):
    """בלי מסמך — לפי השם שבפתק. הסיומת ``.html`` מספיקה."""
    client, _db = _client(monkeypatch, snippets=_Broken([]))
    with caplog.at_level(logging.WARNING, logger="webapp.app"):
        assert _location(client, NOTE_ON_HTML) == f"/html/{H1}?note={NOTE_ON_HTML}"
