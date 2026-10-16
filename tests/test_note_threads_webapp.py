"""ראוטי שרשורי התגובות בוובאפ — מול מונגו אמיתי, דרך ה-API שהממשק קורא.

**למה מונגו אמיתי:** ההבטחות כאן הן על מה שנכתב ונשאר במסד — "פתק של משתמש אחר מחזיר 404
ושום דבר לא נכתב", "התשובה נבנית ממה שהמסד החזיר", "השרשורים נמחקים רק אחרי שהפתק נמחק". דמה
של אוסף הייתה בודקת את הדמה. הקבצים האלה מדלגים ב-CI של ה-PR (``docs/testing.rst``), ורצים אחרי
מיזוג ב-``deploy.yml``.

**הדילוג הוא ב-fixture ולא ב-``pytestmark``** (``bugbot-rules/import-time-side-effects.md`` §3):
בדיקת נגישות ברמת המודול פונה לרשת בכל איסוף. ומדלגים רק על "אין שרת" (``mongo_reachable``).

סדר הקובץ הוא סדר הסיכון: IDOR קודם, אחר כך מחיקה, אחר כך מה שנכתב ומה שנקרא.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("pymongo")
pytest.importorskip("flask")

from bson import ObjectId  # noqa: E402
from flask import Flask  # noqa: E402
from pymongo.errors import PyMongoError  # noqa: E402

# ``tests`` אינו חבילה — ראה את ה-docstring של ``tests/conftest.py``.
from _note_threads_harness import (  # noqa: E402
    insert_board,
    insert_file,
    insert_note,
    mongo_reachable,
    temp_database,
)

import note_threads as nt  # noqa: E402

USER, OTHER = 7, 99
REPO_ROOT = Path(__file__).resolve().parent.parent
T0 = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def _mongo():
    if not mongo_reachable():
        pytest.skip("דורש MONGODB_URL עם שרת מונגו נגיש")


@pytest.fixture
def db(_mongo):
    with temp_database("codebot_threads_web_it_") as database:
        yield database


class _Api:
    """ה-blueprint האמיתי מעל המסד הזמני — אותם ראוטים שהממשק קורא."""

    def __init__(self, monkeypatch: Any, db: Any) -> None:
        import webapp.sticky_notes_api as sticky_notes_api

        self.module = sticky_notes_api
        self.db = db
        self._monkeypatch = monkeypatch
        monkeypatch.setattr(sticky_notes_api, "get_db", lambda: self.current_db)
        # בניית האינדקסים של הפתקים אינה חלק ממה שנבדק כאן, ומצבה גלובלי לתהליך.
        monkeypatch.setattr(sticky_notes_api, "_ensure_indexes", lambda *a, **k: None)
        self.current_db = db
        app = Flask(__name__)
        app.secret_key = "threads-webapp-tests"
        app.register_blueprint(sticky_notes_api.sticky_notes_bp)
        self.client = app.test_client()
        self.login(USER)

    def login(self, user_id: int, first_name: Any = "אמיר") -> None:
        with self.client.session_transaction() as sess:
            sess["user_id"] = user_id
            sess["user_data"] = {"first_name": first_name}

    def get(self, path: str):
        return self.client.get("/api/sticky-notes" + path)

    def post(self, path: str, body: Any = None):
        return self.client.post("/api/sticky-notes" + path, json={} if body is None else body)

    def delete(self, path: str):
        return self.client.delete("/api/sticky-notes" + path)

    def threads(self) -> list[dict]:
        return list(self.db[nt.NOTE_THREADS_COLLECTION].find({}).sort("_id", 1))

    def thread(self, thread_id: str) -> dict:
        return self.db[nt.NOTE_THREADS_COLLECTION].find_one({"_id": ObjectId(thread_id)})


@pytest.fixture
def api(monkeypatch, db):
    return _Api(monkeypatch, db)


def _board_note(db: Any, user_id: int = USER, **kwargs: Any) -> str:
    return insert_note(db, user_id, board_id=insert_board(db, user_id), **kwargs)


def _thread(db: Any, note_id: str, *, user_id: int = USER, author: Any = None, body: str = "פתיחה",
            minutes: int = 0) -> str:
    """שרשור שנכתב דרך המודול — כמו שה-MCP כותב (סוכן) או הוובאפ (משתמש)."""
    res = nt.create_thread(
        db[nt.NOTE_THREADS_COLLECTION], user_id=user_id, note_id=note_id,
        author=author or nt.user_author(), body=body, now=T0 + timedelta(minutes=minutes),
    )
    assert res["ok"], res
    return res["thread_id"]


def _agent(client: Any = "claude-code", working_on: str = "תיקון bidi") -> dict:
    return nt.agent_author(client=client, working_on=working_on)


# -- הרשאה: פתק של אחר, שרשור של אחר ------------------------------------------------


def test_a_foreign_note_is_404_on_every_route_and_nothing_is_written(api, db):
    """IDOR: כל ראוט על פתק של משתמש אחר עונה 404 ``note_not_found``, והמסד לא זז.

    המזהים אמיתיים — הפתק קיים והשרשור קיים — כך שה-404 אינו "לא נמצא" מקרי אלא ההרשאה.
    """
    foreign_note = _board_note(db, OTHER)
    foreign_thread = _thread(db, foreign_note, user_id=OTHER, author=_agent())
    before = api.threads()
    base = f"/note/{foreign_note}/threads"
    answers = [
        api.get(base),
        api.get(f"{base}/{foreign_thread}"),
        api.post(base, {"body": "ניסיון"}),
        api.post(f"{base}/{foreign_thread}/comments", {"body": "ניסיון"}),
        api.post(f"{base}/{foreign_thread}/resolve", {"body": "ניסיון"}),
        api.post(f"{base}/{foreign_thread}/reopen"),
    ]
    assert [(r.status_code, r.get_json()) for r in answers] == [
        (404, {"ok": False, "error": "note_not_found"})
    ] * len(answers)
    assert api.threads() == before


def test_a_thread_of_another_note_is_not_found_and_nothing_is_written(api, db):
    """``thread_id`` אמיתי — של משתמש אחר, או של פתק אחר של אותו משתמש — על הפתק שלי: 404."""
    mine = _board_note(db)
    my_other_note = _board_note(db)
    foreign_note = _board_note(db, OTHER)
    foreign_thread = _thread(db, foreign_note, user_id=OTHER)
    sibling_thread = _thread(db, my_other_note)
    before = api.threads()
    for thread_id in (foreign_thread, sibling_thread):
        base = f"/note/{mine}/threads/{thread_id}"
        answers = [
            api.get(base),
            api.post(f"{base}/comments", {"body": "ניסיון"}),
            api.post(f"{base}/resolve", {"body": "ניסיון"}),
            api.post(f"{base}/reopen"),
        ]
        assert [(r.status_code, r.get_json()["error"]) for r in answers] == [(404, "thread_not_found")] * 4
    assert api.threads() == before


def test_the_user_id_in_the_body_is_ignored(api, db):
    """``user_id`` מגיע רק מה-session: גוף שמנסה לכתוב בשם אחר כותב בשם המחובר."""
    note = _board_note(db)
    res = api.post(f"/note/{note}/threads", {"body": "שלום", "user_id": OTHER})
    assert res.status_code == 201, res.get_json()
    assert [t["user_id"] for t in api.threads()] == [USER]


# -- מחיקה ---------------------------------------------------------------------------


def test_deleting_a_note_deletes_its_threads_and_only_its_threads(api, db):
    note = _board_note(db)
    kept_note = _board_note(db)
    _thread(db, note)
    _thread(db, note, author=_agent(), minutes=1)
    kept = _thread(db, kept_note)
    res = api.delete(f"/note/{note}")
    assert res.status_code == 200, res.get_json()
    assert db.sticky_notes.find_one({"_id": ObjectId(note)}) is None
    assert [str(t["_id"]) for t in api.threads()] == [kept]


class _DeleteOutcome:
    """``sticky_notes`` שמחיקה בו נכשלת — אחרי שכל השאר עובר למסד האמיתי."""

    def __init__(self, coll: Any, outcome: str) -> None:
        self._coll = coll
        self._outcome = outcome

    def delete_one(self, *args: Any, **kwargs: Any):
        if self._outcome == "raises":
            raise PyMongoError("simulated: the delete did not reach the server")
        return type("R", (), {"deleted_count": 0})()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._coll, name)


class _DbWithFailingDelete:
    def __init__(self, db: Any, outcome: str) -> None:
        self._db = db
        self.sticky_notes = _DeleteOutcome(db.sticky_notes, outcome)

    def __getitem__(self, name: str) -> Any:
        return self._db[name]

    def __getattr__(self, name: str) -> Any:
        return getattr(self._db, name)


@pytest.mark.parametrize("outcome", ["raises", "deleted_nothing"])
def test_a_failed_delete_leaves_both_the_note_and_its_threads(api, db, outcome):
    """**השרשורים נמחקים רק אחרי ``deleted_count == 1``.** מחיקה שנכשלה — חריגה, או מחיקה שלא
    מחקה כלום — משאירה גם את הפתק וגם את השרשורים. בסדר ההפוך (שרשורים קודם) השרשורים של
    פתק שנשאר היו נעלמים, וזה בדיוק מה שהטסט הזה תופס."""
    note = _board_note(db)
    thread_id = _thread(db, note)
    api.current_db = _DbWithFailingDelete(db, outcome)
    res = api.delete(f"/note/{note}")
    assert res.status_code == (500 if outcome == "raises" else 404), res.get_json()
    assert db.sticky_notes.find_one({"_id": ObjectId(note)}) is not None
    assert [str(t["_id"]) for t in api.threads()] == [thread_id]


def test_deleting_a_foreign_note_leaves_it_and_its_threads(api, db):
    foreign = _board_note(db, OTHER)
    foreign_thread = _thread(db, foreign, user_id=OTHER)
    res = api.delete(f"/note/{foreign}")
    assert res.status_code == 404
    assert db.sticky_notes.find_one({"_id": ObjectId(foreign)}) is not None
    assert [str(t["_id"]) for t in api.threads()] == [foreign_thread]


# -- כתיבה: התשובה היא מה שהמסד החזיר ---------------------------------------------------


def test_creating_a_thread_answers_from_what_was_stored(api, db):
    note = _board_note(db)
    res = api.post(f"/note/{note}/threads", {"body": "כשיש קוד באנגלית, השורות מתהפכות 🙂"})
    assert res.status_code == 201, res.get_json()
    data = res.get_json()
    stored = api.threads()
    assert len(stored) == 1
    doc = stored[0]
    stored_comment = doc["comments"][0]
    assert data["thread_id"] == str(doc["_id"])
    assert data["thread"] == {
        "id": str(doc["_id"]), "number": 1, "status": "open", "comment_count": 1,
        "awaits_user": False, "resolved_by_label": "", "resolved_at": None,
    }
    assert data["comment"] == {
        "id": stored_comment["id"],
        "author_kind": "user",
        "author_label": "אמיר",
        "author_initials": "אמ",
        "author_tone": "user",
        "working_on": "",
        "body": stored_comment["body"],
        "created_at": stored_comment["created_at"].astimezone(timezone.utc).isoformat(),
    }
    assert data["comment"]["created_at"].endswith("+00:00"), "בלי היסט הדפדפן קורא את הזמן כמקומי (R7)"
    assert data["threads"] == [{"id": str(doc["_id"]), "number": 1, "status": "open",
                                "comment_count": 1, "awaits_user": False}]
    assert doc["last_author_kind"] == "user"


def test_a_second_thread_gets_the_next_number(api, db):
    note = _board_note(db)
    _thread(db, note, author=_agent())
    data = api.post(f"/note/{note}/threads", {"body": "נושא אחר"}).get_json()
    assert data["thread"]["number"] == 2
    assert [t["number"] for t in data["threads"]] == [1, 2]
    assert [t["awaits_user"] for t in data["threads"]] == [True, False]


def test_reply_resolve_reply_without_reopen_and_reopen_are_stored_and_read_back(api, db):
    """הזרימה המלאה של כפתורי החלונית, כל צעד נקרא שוב מהמסד."""
    note = _board_note(db)
    tid = _thread(db, note, author=_agent())
    base = f"/note/{note}/threads/{tid}"

    res = api.post(f"{base}/comments", {"body": "תודה, בודק"})
    assert res.status_code == 200, res.get_json()
    doc = api.thread(tid)
    assert (doc["status"], doc["comment_count"], doc["last_author_kind"]) == ("open", 2, "user")
    assert res.get_json()["comment"]["id"] == doc["comments"][-1]["id"]

    # "✓ נפתר" עם טקסט בתיבה: הסיכום נשמר כתגובה, באותה כתיבה.
    res = api.post(f"{base}/resolve", {"body": "סגור — תוקן ב-PR"})
    assert res.status_code == 200, res.get_json()
    doc = api.thread(tid)
    assert doc["status"] == "resolved"
    assert doc["resolved_by"] == {"kind": "user", "client": None, "working_on": None}
    assert (doc["comment_count"], doc["comments"][-1]["body"]) == (3, "סגור — תוקן ב-PR")
    answer = res.get_json()
    assert answer["thread"]["status"] == "resolved"
    assert answer["thread"]["resolved_by_label"] == "אמיר"
    assert answer["thread"]["resolved_at"] == doc["resolved_at"].astimezone(timezone.utc).isoformat()

    # "שליחה בלי פתיחה" — התגובה נשמרת, השרשור נשאר נפתר.
    res = api.post(f"{base}/comments", {"body": "לתיעוד: גם במובייל", "reopen": False})
    assert res.status_code == 200, res.get_json()
    doc = api.thread(tid)
    assert (doc["status"], doc["comment_count"]) == ("resolved", 4)
    assert res.get_json()["thread"]["status"] == "resolved"

    # "פתיחה מחדש" — בלי תגובה.
    res = api.post(f"{base}/reopen")
    assert res.status_code == 200, res.get_json()
    doc = api.thread(tid)
    assert (doc["status"], doc["resolved_by"], doc["comment_count"]) == ("open", None, 4)

    # סגירה בלי טקסט, ו"שליחה ופתיחה מחדש" (ברירת המחדל).
    assert api.post(f"{base}/resolve").status_code == 200
    assert api.thread(tid)["status"] == "resolved"
    res = api.post(f"{base}/comments", {"body": "חוזר לזה"})
    assert res.status_code == 200
    doc = api.thread(tid)
    assert (doc["status"], doc["comment_count"]) == ("open", 5)


def test_state_refusals_are_409_and_write_nothing(api, db):
    note = _board_note(db)
    tid = _thread(db, note)
    base = f"/note/{note}/threads/{tid}"
    res = api.post(f"{base}/reopen")
    assert (res.status_code, res.get_json()["error"]) == (409, "not_resolved")
    assert api.post(f"{base}/resolve").status_code == 200
    before = api.threads()
    res = api.post(f"{base}/resolve", {"body": "שוב"})
    assert (res.status_code, res.get_json()["error"]) == (409, "already_resolved")
    assert api.threads() == before


def test_a_full_thread_is_409_with_the_ceiling(api, db, monkeypatch):
    note = _board_note(db)
    tid = _thread(db, note)
    monkeypatch.setattr(nt, "MAX_COMMENTS_PER_THREAD", 1)
    before = api.threads()
    res = api.post(f"/note/{note}/threads/{tid}/comments", {"body": "עוד"})
    assert (res.status_code, res.get_json()) == (409, {"ok": False, "error": "thread_full", "max": 1})
    assert api.threads() == before


@pytest.mark.parametrize(
    "payload, error",
    [
        ({"body": "   "}, "empty_body"),
        ({"body": 123}, "invalid_body"),
        ({}, "invalid_body"),
        ({"body": "😀" * (nt.MAX_COMMENT_CHARS + 1)}, "body_too_long"),
    ],
)
def test_body_refusals_write_nothing(api, db, payload, error):
    note = _board_note(db)
    tid = _thread(db, note)
    before = api.threads()
    for path in (f"/note/{note}/threads", f"/note/{note}/threads/{tid}/comments"):
        res = api.post(path, payload)
        assert (res.status_code, res.get_json()["error"]) == (400, error), path
    assert api.threads() == before


def test_the_ceiling_counts_code_points_like_the_counter(api, db):
    """4,000 אימוג'ים עוברים: התקרה סופרת נקודות קוד (``len`` של פייתון) — ``[...s].length`` בממשק,
    ולא ``s.length``, שהיה סופר כל אימוג'י כשניים ועוצר ב-2,000."""
    note = _board_note(db)
    res = api.post(f"/note/{note}/threads", {"body": "😀" * nt.MAX_COMMENT_CHARS})
    assert res.status_code == 201, res.get_json()
    res = api.post(f"/note/{note}/threads", {"body": "😀" * (nt.MAX_COMMENT_CHARS + 1)})
    assert res.get_json() == {"ok": False, "error": "body_too_long", "max": nt.MAX_COMMENT_CHARS}


@pytest.mark.parametrize("reopen", ["false", 0, None, [False]])
def test_reopen_that_is_not_a_boolean_is_refused(api, db, reopen):
    """``"false"`` כמחרוזת אינו ``False`` — בלי הבדיקה הוא היה נקרא כאמת ופותח את השרשור."""
    note = _board_note(db)
    tid = _thread(db, note)
    assert api.post(f"/note/{note}/threads/{tid}/resolve").status_code == 200
    before = api.threads()
    res = api.post(f"/note/{note}/threads/{tid}/comments", {"body": "x", "reopen": reopen})
    assert (res.status_code, res.get_json()) == (400, {"ok": False, "error": "invalid_reopen"})
    assert api.threads() == before


@pytest.mark.parametrize("body", [["x"], "x", 5])
def test_a_body_that_is_not_an_object_is_invalid_payload(api, db, body):
    note = _board_note(db)
    res = api.post(f"/note/{note}/threads", body)
    assert (res.status_code, res.get_json()) == (400, {"ok": False, "error": "invalid_payload"})
    assert api.threads() == []


def test_a_malformed_thread_id_is_400(api, db):
    note = _board_note(db)
    for res in (api.get(f"/note/{note}/threads/xyz"), api.post(f"/note/{note}/threads/xyz/reopen")):
        assert (res.status_code, res.get_json()["error"]) == (400, "invalid_thread_id")


# -- קריאה ---------------------------------------------------------------------------


def test_a_thread_is_read_with_labels_initials_and_tones_from_the_server(api, db):
    note = _board_note(db)
    tid = _thread(db, note, author=_agent("claude-code", "תיקון כיוון קוד"), body="מצאתי את המקור")
    coll = db[nt.NOTE_THREADS_COLLECTION]
    for minutes, author, body in [
        (1, nt.user_author(), "תודה"),
        (2, _agent("Gemini", "בדיקת נגישות"), "בדקתי"),
        (3, _agent("Anthropic/ClaudeAI", "סקירת קוד"), "מאשר"),
        (4, _agent("Cursor", "משהו"), "גם אני"),
        (5, _agent(None, "בלי שם"), "אנונימי"),
    ]:
        res = nt.add_comment(coll, user_id=USER, note_id=note, thread_id=tid, author=author, body=body,
                             now=T0 + timedelta(minutes=minutes))
        assert res["ok"], res
    res = api.get(f"/note/{note}/threads/{tid}")
    assert res.status_code == 200, res.get_json()
    thread = res.get_json()["thread"]
    assert (thread["number"], thread["comment_count"], thread["awaits_user"]) == (1, 6, True)
    rows = [(c["author_label"], c["author_initials"], c["author_tone"], c["working_on"], c["body"])
            for c in thread["comments"]]
    assert rows == [
        ("CC", "CC", "cc", "תיקון כיוון קוד", "מצאתי את המקור"),
        ("אמיר", "אמ", "user", "", "תודה"),
        ("Gemini", "G", "gemini", "בדיקת נגישות", "בדקתי"),
        ("Claude", "C", "claude", "סקירת קוד", "מאשר"),
        ("Cursor", "C", "agent", "משהו", "גם אני"),
        (nt.UNKNOWN_AGENT_LABEL, "ס", "agent", "בלי שם", "אנונימי"),
    ]
    assert all(c["created_at"].endswith("+00:00") for c in thread["comments"])


@pytest.mark.parametrize("first_name, label", [("", "אני"), (None, "אני"), (17, "אני"), ("  דנה ", "דנה")])
def test_the_user_label_comes_from_the_session(api, db, first_name, label):
    """הפיצ'ר פתוח לכל המשתמשים: השם הוא ``first_name`` של המחובר, ובלעדיו — "אני"."""
    api.login(USER, first_name=first_name)
    note = _board_note(db)
    data = api.post(f"/note/{note}/threads", {"body": "שלום"}).get_json()
    assert data["comment"]["author_label"] == label


def test_lists_carry_thread_summaries_on_every_surface(api, db):
    """הבועות מגיעות עם רשימת הפתקים — בלוח, בקובץ ובריפו — בשאילתה אחת, בלי התגובות."""
    board = insert_board(db, USER)
    board_note = insert_note(db, USER, board_id=board)
    file_id = insert_file(db, USER, "notes.md")
    file_note = insert_note(db, USER, file_id=file_id)
    repo_note = insert_note(db, USER, repo_name="CodeBot", repo_path="docs/a.rst")
    open_thread = _thread(db, board_note, author=_agent())
    resolved = _thread(db, board_note, minutes=1)
    nt.resolve_thread(db[nt.NOTE_THREADS_COLLECTION], user_id=USER, note_id=board_note,
                      thread_id=resolved, author=nt.user_author())
    file_thread = _thread(db, file_note)
    repo_thread = _thread(db, repo_note, author=_agent("Gemini", "x"))
    # שרשור של משתמש אחר על **אותו** ``note_id`` — אינו יכול להיווצר דרך ה-API, ולכן הוא בודק
    # שהשאילתה תחומה למשתמש ולא רק לפתק.
    _thread(db, board_note, user_id=OTHER)

    notes = api.get(f"/board/{board}").get_json()["notes"]
    assert notes[0]["threads"] == [
        {"id": open_thread, "number": 1, "status": "open", "comment_count": 1, "awaits_user": True},
        {"id": resolved, "number": 2, "status": "resolved", "comment_count": 1, "awaits_user": False},
    ]
    notes = api.get(f"/{file_id}").get_json()["notes"]
    assert [t["id"] for t in notes[0]["threads"]] == [file_thread]
    notes = api.get("/repo/CodeBot/docs/a.rst").get_json()["notes"]
    assert [(t["id"], t["awaits_user"]) for t in notes[0]["threads"]] == [(repo_thread, True)]


def test_a_note_without_threads_has_an_empty_list(api, db):
    board = insert_board(db, USER)
    insert_note(db, USER, board_id=board)
    data = api.get(f"/board/{board}").get_json()
    assert data["notes"][0]["threads"] == []
    assert "threads_unavailable" not in data


def test_a_database_failure_on_summaries_is_reported_not_hidden(api, db, monkeypatch):
    """כשל בשליפת השרשורים: הפתקים חוזרים, בלי ``threads``, ועם ``threads_unavailable`` — כדי
    שהממשק לא יציג "אין שרשורים" על פתק שיש עליו שיחה (``silent-fallback-to-worse-path``)."""
    board = insert_board(db, USER)
    note = insert_note(db, USER, board_id=board)
    _thread(db, note)

    def _broken(*args, **kwargs):
        raise PyMongoError("simulated")

    monkeypatch.setattr(nt, "list_threads_for_notes", _broken)
    res = api.get(f"/board/{board}")
    assert res.status_code == 200, res.get_json()
    data = res.get_json()
    assert data["threads_unavailable"] is True
    assert [n["id"] for n in data["notes"]] == [note]
    assert "threads" not in data["notes"][0]


def test_a_bug_in_the_summaries_is_not_reported_as_a_database_failure(api, db, monkeypatch):
    """רק ``PyMongoError`` נכנס למצב "לא נטענו". באג אחר עולה (``widened-exception-scope``)."""
    board = insert_board(db, USER)
    insert_note(db, USER, board_id=board)

    def _bug(*args, **kwargs):
        raise AttributeError("a bug, not the database")

    monkeypatch.setattr(nt, "list_threads_for_notes", _bug)
    assert api.get(f"/board/{board}").status_code == 500


# -- המיפויים מסונכרנים עם המודול (R6) ---------------------------------------------------


def test_every_refusal_of_the_module_has_an_http_status():
    """כל קוד סירוב ש-``note_threads.py`` יכול להחזיר ממופה לסטטוס — נגזר מהמקור, לא מרשימה."""
    import webapp.sticky_notes_api as sticky_notes_api

    source = (REPO_ROOT / "note_threads.py").read_text(encoding="utf-8")
    codes = set(re.findall(r'"error": "([a-z_]+)"', source))
    assert codes, "לא נמצאו קודי סירוב במקור — הדפוס של החיפוש השתנה"
    assert codes <= set(sticky_notes_api._THREAD_ERROR_STATUS), codes - set(sticky_notes_api._THREAD_ERROR_STATUS)


def test_every_known_agent_client_has_a_tone():
    """לקוח שנוסף ל-``AGENT_CLIENT_LABELS`` בלי גוון היה מקבל בשקט את הגוון של "סוכן אחר"."""
    import webapp.sticky_notes_api as sticky_notes_api

    assert set(sticky_notes_api._AGENT_CLIENT_TONES) == set(nt.AGENT_CLIENT_LABELS)
