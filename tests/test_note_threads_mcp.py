"""שרשורי התגובות דרך כלי ה-MCP — טבלת הבדיקות של האפיון, מול מונגו אמיתי.

**דרך הממשק שהסוכן מפעיל** (``testing.md`` §1): session אמיתי של הפרוטוקול מול ``build_mcp``
— ``initialize`` עם ``clientInfo`` ואז ``tools/call`` — מעל ``ProductionBackend`` אמיתי ומסד
אמיתי. וזהות הלקוח נבדקת **גם ב-HTTP**, באפליקציה במצב OAuth (הייצור), עם PostHog מוגדר
(``send=False``): השרת רץ ``stateless_http``, ושם השם מגיע רק מהטוקן שבכותרת
``Mcp-Session-Id`` — המסלול שבו רץ הייצור, ולא הקל לבנייה.

סדר הקובץ הוא סדר הסיכון: IDOR ושער האדמין קודם, אחר כך מה שנכתב ומה שנקרא.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

import pytest

pytest.importorskip("pymongo")
pytest.importorskip("mcp")

from bson import ObjectId  # noqa: E402

# ``tests`` אינו חבילה — ראה את ה-docstring של ``tests/conftest.py``.
from _note_threads_harness import (  # noqa: E402
    insert_board,
    insert_file,
    insert_note,
    mongo_reachable,
    temp_database,
)

import note_threads as nt  # noqa: E402

USER, OTHER, ADMIN = 7, 99, 1

pytestmark = pytest.mark.skipif(not mongo_reachable(), reason="דורש MONGODB_URL עם שרת מונגו נגיש")


@pytest.fixture
def db():
    with temp_database("codebot_threads_mcp_it_") as database:
        yield database


class _Server:
    """``build_mcp`` אמיתי מעל ``ProductionBackend`` אמיתי — ומי שואל, משתנה בין קריאות."""

    def __init__(self, monkeypatch: Any, db: Any) -> None:
        import mcp.server.auth.middleware.auth_context as auth_context

        import mcp_server.server as srv
        from mcp_server.backend import ProductionBackend

        self.db = db
        self.user = USER
        self.scopes = ["read", "write"]
        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.setattr(srv, "current_user_id", lambda ctx=None: self.user)
        monkeypatch.setattr(srv, "is_admin_user", lambda uid: uid == ADMIN)
        monkeypatch.setattr(auth_context, "get_access_token",
                            lambda: SimpleNamespace(scopes=list(self.scopes)))
        self.backend = ProductionBackend(mongo_db=db)
        self.mcp = srv.build_mcp(self.backend)

    async def call(self, tool: str, *, client: str = "claude-code", **arguments: Any) -> dict:
        """``tools/call`` דרך session של הפרוטוקול, אחרי ``initialize`` עם ``clientInfo.name``."""
        from mcp import types
        from mcp.shared.memory import create_connected_server_and_client_session

        async with create_connected_server_and_client_session(
            self.mcp._mcp_server, client_info=types.Implementation(name=client, version="1.0"),
        ) as session:
            result = await session.call_tool(tool, arguments)
        text = result.content[0].text
        if result.isError:
            return {"tool_error": text}
        return json.loads(text)

    def threads(self) -> list[dict]:
        return list(self.db[nt.NOTE_THREADS_COLLECTION].find({}).sort("_id", 1))

    def events(self) -> list[dict]:
        return list(self.db.push_events.find({}).sort("_id", 1))


@pytest.fixture
def server(monkeypatch, db):
    return _Server(monkeypatch, db)


def _board_note(db, user_id: int = USER, **kwargs) -> str:
    return insert_note(db, user_id, board_id=insert_board(db, user_id), **kwargs)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


async def _new_thread(server: _Server, note_id: str, body: str = "פתיחה", **kwargs) -> str:
    res = await server.call("codekeeper_comment_note", note_id=note_id, working_on="בדיקה",
                            body=body, **kwargs)
    assert res.get("ok") is True, res
    return res["thread"]["id"]


# == IDOR — קודם לכל ===============================================================


async def test_commenting_on_another_users_note_is_not_found_and_writes_nothing(server, db):
    """פתק של משתמש אחר: ``not_found`` — לשרשור חדש, לתשובה בשרשור שלו ולסגירה שלו — ושום
    דבר לא נכתב: לא שרשור, לא תגובה, לא אירוע התראה. השער נבדק על הפתק לפני כל כתיבה."""
    foreign_note = _board_note(db, OTHER)
    server.user = OTHER
    foreign_thread = await _new_thread(server, foreign_note)
    before_threads, before_events = server.threads(), server.events()

    server.user = USER
    for extra in ({}, {"thread_id": foreign_thread}, {"thread_id": foreign_thread, "resolve": True}):
        res = await server.call("codekeeper_comment_note", note_id=foreign_note, working_on="ניסיון",
                                body="זה שלי?", **extra)
        assert res == {"ok": False, "error": "not_found"}, (extra, res)
    assert await server.call("codekeeper_get_note", note_id=foreign_note) == {"ok": False, "error": "not_found"}

    assert server.threads() == before_threads
    assert server.events() == before_events


async def test_a_thread_id_of_another_user_on_my_note_is_refused_and_writes_nothing(server, db):
    """``thread_id`` של משתמש אחר, עם ``note_id`` של פתק **שלי**: השער עובר (הפתק שלי), אבל
    הכתיבה תחומה ל-``(user_id, note_id)`` — ולכן ``thread_not_found``, ושום דבר לא נכתב.
    הלקח של 4.13: ההרשאה אינה נגזרת מקיום ה-``thread_id``."""
    mine = _board_note(db, USER)
    foreign_note = _board_note(db, OTHER)
    server.user = OTHER
    foreign_thread = await _new_thread(server, foreign_note)
    before_threads, before_events = server.threads(), server.events()

    server.user = USER
    for extra in ({}, {"resolve": True}, {"reopen": False}):
        res = await server.call("codekeeper_comment_note", note_id=mine, working_on="ניסיון",
                                body="תשובה", thread_id=foreign_thread, **extra)
        assert res["ok"] is False and res["error"] == "thread_not_found", (extra, res)
    read = await server.call("codekeeper_get_note", note_id=mine, part="threads", thread_id=foreign_thread)
    assert read["ok"] is False and read["error"] == "thread_not_found"

    assert server.threads() == before_threads
    assert server.events() == before_events


async def test_a_thread_on_another_note_of_mine_is_not_reachable_through_this_note(server, db):
    first, second = _board_note(db), _board_note(db)
    thread = await _new_thread(server, first)

    res = await server.call("codekeeper_comment_note", note_id=second, working_on="x", body="y",
                            thread_id=thread)

    assert res["error"] == "thread_not_found"
    assert [len(t["comments"]) for t in server.threads()] == [1]


async def test_a_repo_note_is_not_found_for_a_non_admin_and_open_to_the_admin(server, db):
    """פתק ריפו: ``not_found`` למי שאינו אדמין — בקריאה ובתגובה, מאותו קוד — ופתוח לאדמין."""
    repo_note = insert_note(db, USER, repo_name="CodeBot", repo_path="a.py")

    res = await server.call("codekeeper_comment_note", note_id=repo_note, working_on="x", body="y")
    assert res == {"ok": False, "error": "not_found"}
    assert await server.call("codekeeper_get_note", note_id=repo_note, part="threads") == {
        "ok": False, "error": "not_found"}
    assert server.threads() == [] and server.events() == []

    # אותו פתק, של האדמין — עובר.
    admin_note = insert_note(db, ADMIN, repo_name="CodeBot", repo_path="a.py")
    server.user = ADMIN
    res = await server.call("codekeeper_comment_note", note_id=admin_note, working_on="x", body="y")
    assert res["ok"] is True
    read = await server.call("codekeeper_get_note", note_id=admin_note, part="threads")
    assert read["ok"] is True and read["target"] == "repo" and len(read["threads"]) == 1


async def test_commenting_needs_write_permission(server, db):
    note = _board_note(db)
    server.scopes = ["read"]

    res = await server.call("codekeeper_comment_note", note_id=note, working_on="x", body="y")

    assert "insufficient_scope" in res["tool_error"]
    assert server.threads() == []


# == מה שנכתב ===================================================================


async def test_a_comment_is_saved_as_sent_and_the_answer_is_read_back(server, db):
    note = _board_note(db)
    body = "  &amp; <b>\r\nשורה שנייה \x07 "

    res = await server.call("codekeeper_comment_note", note_id=note, working_on="  העברת תיקון\nbidi  ",
                            body=body)

    (stored,) = server.threads()
    comment = stored["comments"][0]
    assert comment["body"] == body
    assert comment["author"] == {"kind": "agent", "client": "claude-code", "working_on": "העברת תיקון bidi"}
    assert res["ok"] is True and res["action"] == "created" and res["note_id"] == note
    assert res["comment"]["body_sha256"] == _sha(body)
    assert res["comment"]["id"] == comment["id"]
    assert res["thread"]["id"] == str(stored["_id"]) and res["thread"]["status"] == "open"
    assert "comments" not in res["thread"] and "body_bytes" not in res["thread"]


async def test_the_author_is_the_connected_client_not_a_parameter(server, db):
    """שם הכותב מהחיבור. ארגומנט ``client`` שהסוכן "מוסיף" אינו משנה דבר — אין פרמטר כזה."""
    note = _board_note(db)

    res = await server.call("codekeeper_comment_note", client="Gemini", note_id=note,
                            working_on="בדיקת זהות", body="שלום", author="claude-code")

    assert res.get("ok") is True, res
    (stored,) = server.threads()
    assert stored["comments"][0]["author"]["client"] == "Gemini"
    assert res["comment"]["author"]["client"] == "Gemini"


async def test_working_on_missing_or_too_long_is_refused_and_writes_nothing(server, db):
    note = _board_note(db)

    missing = await server.call("codekeeper_comment_note", note_id=note, body="x")
    too_long = await server.call("codekeeper_comment_note", note_id=note, body="x",
                                 working_on="ת" * (nt.MAX_WORKING_ON_CHARS + 1))
    blank = await server.call("codekeeper_comment_note", note_id=note, body="x", working_on=" \n ")

    assert "working_on" in missing["tool_error"]  # חובה בסכמה — נדחה לפני הכלי
    assert too_long == {"ok": False, "error": "working_on_too_long", "max": nt.MAX_WORKING_ON_CHARS}
    assert blank["error"] == "working_on_required"
    assert server.threads() == [] and server.events() == []


async def test_the_write_arguments_are_checked_before_anything_is_read(server, db):
    note = _board_note(db)
    assert (await server.call("codekeeper_comment_note", note_id=note, working_on="x"))["error"] == "body_required"
    assert (await server.call("codekeeper_comment_note", note_id=note, working_on="x",
                              resolve=True))["error"] == "resolve_needs_thread_id"
    assert (await server.call("codekeeper_comment_note", note_id=note, working_on="x", body="y",
                              thread_id="nope"))["error"] == "invalid_thread_id"
    assert (await server.call("codekeeper_comment_note", note_id=note, working_on="x",
                              body="ש" * (nt.MAX_COMMENT_CHARS + 1)))["error"] == "body_too_long"
    assert server.threads() == []


async def test_answering_a_resolved_thread_reopens_it_with_the_new_last_author(server, db):
    note = _board_note(db)
    thread = await _new_thread(server, note)
    resolved = await server.call("codekeeper_comment_note", note_id=note, working_on="סגירה",
                                 thread_id=thread, resolve=True)
    assert resolved["thread"]["status"] == "resolved" and resolved["comment"] is None

    nt.add_comment(db[nt.NOTE_THREADS_COLLECTION], user_id=USER, note_id=note, thread_id=thread,
                   author=nt.user_author(), body="עדיין שבור", reopen=False)  # המשתמש, מהוובאפ
    res = await server.call("codekeeper_comment_note", note_id=note, working_on="תיקון",
                            thread_id=thread, body="עכשיו?")

    assert res["action"] == "replied" and res["thread"]["status"] == "open"
    (stored,) = server.threads()
    assert (stored["status"], stored["last_author_kind"], stored["resolved_by"]) == ("open", "agent", None)

    kept = await server.call("codekeeper_comment_note", note_id=note, working_on="x", thread_id=thread,
                             resolve=True)
    assert kept["thread"]["status"] == "resolved"
    res = await server.call("codekeeper_comment_note", note_id=note, working_on="x", thread_id=thread,
                            body="רק לתיעוד", reopen=False)
    assert res["thread"]["status"] == "resolved"


async def test_a_full_thread_points_to_a_new_thread(server, db):
    note = _board_note(db)
    thread = await _new_thread(server, note)
    coll = db[nt.NOTE_THREADS_COLLECTION]
    for i in range(nt.MAX_COMMENTS_PER_THREAD - 1):
        nt.add_comment(coll, user_id=USER, note_id=note, thread_id=thread, author=nt.user_author(), body=f"{i}")
    events = len(server.events())

    res = await server.call("codekeeper_comment_note", note_id=note, working_on="x", body="y", thread_id=thread)

    assert res["error"] == "thread_full" and "new thread" in res["hint"]
    assert len(server.events()) == events


# == התראה ======================================================================


async def test_a_push_event_follows_a_successful_agent_comment_only(server, db, monkeypatch):
    """``push_events``: אירוע אחד לכל תגובת סוכן **שנכתבה**, עם היעד והכותב; כלום על סירוב, על
    סגירה בלי סיכום, על תגובת משתמש — וכלום כשהדגל כבוי (בצד הכותב)."""
    board = insert_board(db, USER, "CodeBot")
    note = insert_note(db, USER, board_id=board, title="תיקון כיוון קוד")
    thread = await _new_thread(server, note, body="ראשונה")

    (event,) = server.events()
    (stored,) = server.threads()
    assert {k: event[k] for k in ("user_id", "kind", "note_id", "thread_id", "comment_id", "target",
                                  "board_id", "needs_push")} == {
        "user_id": USER, "kind": "note_comment", "note_id": note, "thread_id": thread,
        "comment_id": stored["comments"][0]["id"], "target": "board", "board_id": board, "needs_push": True,
    }
    assert event["author"] == {"kind": "agent", "client": "claude-code", "working_on": "בדיקה"}
    assert event["created_at"] >= stored["created_at"]

    await server.call("codekeeper_comment_note", note_id=note, working_on="x", thread_id=thread, resolve=True)
    await server.call("codekeeper_comment_note", note_id=note, working_on="x" * 99, body="y")
    nt.add_comment(db[nt.NOTE_THREADS_COLLECTION], user_id=USER, note_id=note, thread_id=thread,
                   author=nt.user_author(), body="של המשתמש")
    assert len(server.events()) == 1

    monkeypatch.setenv("MCP_PUSH_NOTIFICATIONS_ENABLED", "false")
    assert (await server.call("codekeeper_comment_note", note_id=note, working_on="x", body="y"))["ok"]
    assert len(server.events()) == 1


# == מה שנקרא ===================================================================


async def test_get_note_shows_open_threads_in_full_and_resolved_ones_collapsed(server, db):
    note = _board_note(db, content="גוף הפתק")
    first = await _new_thread(server, note, body="ראשון")
    second = await _new_thread(server, note, body="שני")
    await server.call("codekeeper_comment_note", note_id=note, working_on="x", thread_id=second, body="המשך")
    await server.call("codekeeper_comment_note", note_id=note, working_on="סגירה", thread_id=first,
                      resolve=True, body="נפתר")

    read = await server.call("codekeeper_get_note", note_id=note)

    assert read["note"]["content"] == "גוף הפתק" and "version" in read
    open_row, resolved_row = read["threads"]
    assert (open_row["id"], open_row["number"], open_row["status"]) == (second, 2, "open")
    assert [c["body"] for c in open_row["comments"]] == ["שני", "המשך"]
    assert "earlier_comments" not in open_row
    assert (resolved_row["id"], resolved_row["number"], resolved_row["status"]) == (first, 1, "resolved")
    assert "comments" not in resolved_row  # שורה מקופלת
    assert resolved_row["resolved_by"] == {"kind": "agent", "client": "claude-code", "working_on": "סגירה"}
    assert resolved_row["comment_count"] == 2 and resolved_row["resolved_at"]
    assert "part=\"threads\"" in read["threads_hint"]
    assert "threads_truncated" not in read and "comments_truncated" not in read


async def test_a_thread_longer_than_the_default_view_shows_its_latest_comments(server, db):
    note = _board_note(db)
    thread = await _new_thread(server, note, body="0")
    coll = db[nt.NOTE_THREADS_COLLECTION]
    extra = 4
    from mcp_server.handlers import NOTE_THREAD_DEFAULT_TAIL

    for i in range(1, NOTE_THREAD_DEFAULT_TAIL + extra):
        nt.add_comment(coll, user_id=USER, note_id=note, thread_id=thread, author=nt.user_author(), body=str(i))

    (row,) = (await server.call("codekeeper_get_note", note_id=note))["threads"]
    full = (await server.call("codekeeper_get_note", note_id=note, part="threads"))["threads"][0]

    assert row["earlier_comments"] == extra
    assert [c["body"] for c in row["comments"]] == [str(i) for i in range(extra, NOTE_THREAD_DEFAULT_TAIL + extra)]
    assert [c["body"] for c in full["comments"]] == [str(i) for i in range(NOTE_THREAD_DEFAULT_TAIL + extra)]


async def test_part_threads_drops_the_body_and_includes_resolved_threads_in_full(server, db):
    note = _board_note(db, content="גוף שלא אמור לחזור", title="כותרת")
    first = await _new_thread(server, note, body="א")
    await server.call("codekeeper_comment_note", note_id=note, working_on="x", thread_id=first,
                      resolve=True, body="ב")
    second = await _new_thread(server, note, body="ג")

    read = await server.call("codekeeper_get_note", note_id=note, part="threads")
    one = await server.call("codekeeper_get_note", note_id=note, part="threads", thread_id=first)

    assert "note" not in read and "version" not in read
    assert (read["note_id"], read["title"], read["target"]) == (note, "כותרת", "board")
    assert "גוף שלא אמור לחזור" not in json.dumps(read, ensure_ascii=False)
    by_id = {row["id"]: row for row in read["threads"]}
    assert [c["body"] for c in by_id[first]["comments"]] == ["א", "ב"]
    assert [c["body"] for c in by_id[second]["comments"]] == ["ג"]
    assert [row["id"] for row in one["threads"]] == [first]
    assert "threads_hint" not in read


async def test_get_note_refuses_parts_and_thread_ids_it_does_not_know(server, db):
    note = _board_note(db)
    thread = await _new_thread(server, note)
    assert (await server.call("codekeeper_get_note", note_id=note, part="comments")) == {
        "ok": False, "error": "invalid_part", "allowed": ["all", "threads"]}
    assert (await server.call("codekeeper_get_note", note_id=note, thread_id=thread))["error"] == "thread_id_needs_part_threads"
    assert (await server.call("codekeeper_get_note", note_id=note, part="threads", thread_id="x"))["error"] == "invalid_thread_id"
    assert (await server.call("codekeeper_get_note", note_id=note, part="threads",
                              thread_id=str(ObjectId())))["error"] == "thread_not_found"


async def test_the_largest_possible_thread_fits_one_answer(server, db):
    """``MAX_THREAD_BODY_BYTES`` נבחר כך ששרשור אחד תמיד נכנס בתשובה אחת — כאן הוא נבנה
    במקרה הגרוע: כל התגובות, גופים של תווי בקרה (שישה בתים לתו ב-JSON) עד התקרה, ושם לקוח
    ו-``working_on`` בתקרה ובתווי בקרה. נמדד כפי שהתשובה נשלחת."""
    from mcp_server.answer_size import OUTPUT_BYTE_BUDGET, wire_json

    note = _board_note(db)
    coll = db[nt.NOTE_THREADS_COLLECTION]
    worst = nt.agent_author(client="\x01" * nt.MAX_CLIENT_NAME_CHARS,
                            working_on="\x01" * nt.MAX_WORKING_ON_CHARS)
    per_comment = nt.MAX_THREAD_BODY_BYTES // nt.MAX_COMMENTS_PER_THREAD
    body = "\x02" * ((per_comment - 2) // 6)
    thread = nt.create_thread(coll, user_id=USER, note_id=note, author=worst, body=body)["thread_id"]
    for _ in range(nt.MAX_COMMENTS_PER_THREAD - 1):
        assert nt.add_comment(coll, user_id=USER, note_id=note, thread_id=thread, author=worst, body=body)["ok"]
    stored = coll.find_one({"_id": ObjectId(thread)})
    assert stored["comment_count"] == nt.MAX_COMMENTS_PER_THREAD
    assert stored["body_bytes"] > nt.MAX_THREAD_BODY_BYTES - per_comment

    read = await server.call("codekeeper_get_note", note_id=note, part="threads", thread_id=thread)

    assert len(wire_json(read)) <= OUTPUT_BYTE_BUDGET
    (row,) = read["threads"]
    assert len(row["comments"]) == nt.MAX_COMMENTS_PER_THREAD
    assert "comments_truncated" not in read and "threads_truncated" not in read


async def test_threads_beyond_the_answer_budget_collapse_with_a_sign_and_a_way_back(server, db):
    """הרבה שרשורים גדולים: מה שאינו נכנס מוצג מקופל (עם המזהה שלו), התשובה נושאת
    ``comments_truncated`` והפניה ל-``thread_id`` — ונשארת בתוך התקציב. רשת התשובה של השרת
    אינה צריכה לסרב (``answer_size_net``), ופנקס החיתוכים תואם (``conftest``)."""
    from mcp_server.answer_size import OUTPUT_BYTE_BUDGET, wire_json

    note = _board_note(db)
    coll = db[nt.NOTE_THREADS_COLLECTION]
    big = "ש" * nt.MAX_COMMENT_CHARS
    ids = []
    for _ in range(6):
        tid = nt.create_thread(coll, user_id=USER, note_id=note, author=nt.user_author(), body=big)["thread_id"]
        for _ in range(8):
            nt.add_comment(coll, user_id=USER, note_id=note, thread_id=tid, author=nt.user_author(), body=big)
        ids.append(tid)

    read = await server.call("codekeeper_get_note", note_id=note, part="threads")

    assert read["ok"] is True and len(wire_json(read)) <= OUTPUT_BYTE_BUDGET
    assert {row["id"] for row in read["threads"]} == set(ids)  # כולם ברשימה
    shown = [row for row in read["threads"] if "comments" in row]
    collapsed = [row for row in read["threads"] if "comments" not in row]
    assert shown and collapsed
    assert read["comments_truncated"] is True and "thread_id" in read["threads_hint"]
    one = await server.call("codekeeper_get_note", note_id=note, part="threads", thread_id=collapsed[0]["id"])
    assert len(one["threads"][0]["comments"]) == 9


async def test_the_lean_listing_counts_open_threads_per_note_for_this_user_only(server, db):
    board = insert_board(db, USER)
    a = insert_note(db, USER, board_id=board, minutes=1)
    b = insert_note(db, USER, board_id=board, minutes=2)
    c = insert_note(db, USER, board_id=board, minutes=3)
    for _ in range(2):
        await _new_thread(server, a)
    resolved = await _new_thread(server, a)
    await server.call("codekeeper_comment_note", note_id=a, working_on="x", thread_id=resolved, resolve=True)
    await _new_thread(server, c)
    # שרשור של משתמש אחר עם אותו note_id (מסמך שאינו אמור להיות — הספירה תחומה למשתמש).
    db[nt.NOTE_THREADS_COLLECTION].insert_one({"user_id": OTHER, "note_id": b, "status": "open"})

    lean = await server.call("codekeeper_list_board_notes", board_id=board, include_content=False)

    assert [(n["id"], n["open_threads"]) for n in lean["notes"]] == [(a, 2), (b, 0), (c, 1)]


# == זהות הלקוח ב-HTTP — המסלול של הייצור ============================================


def _posthog(monkeypatch):
    """PostHog מוגדר, בלי רשת (``send=False``) — כמו ב-``tests/test_mcp_instructions.py``."""
    from posthog import Posthog

    from mcp_server import analytics

    client = Posthog("phc_test_token_not_real", host="https://us.i.posthog.com", send=False,
                     before_send=analytics.scrub_mcp_payload, enable_exception_autocapture=False,
                     capture_exception_code_variables=False)
    monkeypatch.setattr(analytics, "_CLIENT", client)
    monkeypatch.setattr(analytics, "_ANALYTICS", None)
    monkeypatch.setenv("ENVIRONMENT", "production")
    return client


def _sse_result(response) -> dict:
    """תשובת JSON-RPC מגוף ``text/event-stream`` (או JSON) — כמו שלקוח קורא אותה."""
    assert response.status_code == 200, response.text
    if response.headers.get("content-type", "").startswith("application/json"):
        return response.json()
    for line in response.text.splitlines():
        if line.startswith("data:"):
            return json.loads(line[len("data:"):].strip())
    raise AssertionError(f"no data line in {response.text!r}")


async def _http_comment(db, monkeypatch, *, replay_session: bool) -> tuple[dict, Any]:
    import httpx
    from mcp import types

    from _mcp_apps import OAUTH_BASE, PatTokens, oauth_app
    from mcp_server.backend import ProductionBackend

    note = _board_note(db)
    client = _posthog(monkeypatch)
    app = oauth_app(ProductionBackend(mongo_db=db),
                    tokens=PatTokens({"ckmcp_tok": {"user_id": USER, "scopes": ["read", "write"]}}))
    headers = {"Authorization": "Bearer ckmcp_tok", "Accept": "application/json, text/event-stream",
               "Content-Type": "application/json"}
    version = types.LATEST_PROTOCOL_VERSION
    try:
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=OAUTH_BASE) as http:
                init = await http.post("/mcp", headers=headers, json={
                    "jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {"protocolVersion": version, "capabilities": {},
                               "clientInfo": {"name": "claude-code", "version": "2.1.296"}}})
                assert _sse_result(init)["result"]["serverInfo"]
                session_id = init.headers.get("mcp-session-id")
                follow = {**headers, "mcp-protocol-version": version}
                if replay_session:
                    assert session_id, "the PostHog middleware minted no session token"
                    follow["mcp-session-id"] = session_id
                await http.post("/mcp", headers=follow, json={"jsonrpc": "2.0", "method": "notifications/initialized"})
                call = await http.post("/mcp", headers=follow, json={
                    "jsonrpc": "2.0", "id": 2, "method": "tools/call",
                    "params": {"name": "codekeeper_comment_note",
                               "arguments": {"note_id": note, "working_on": "בדיקה ב-HTTP", "body": "שלום"}}})
                result = _sse_result(call)["result"]
    finally:
        client.shutdown()
    assert result.get("isError") is not True, result
    return json.loads(result["content"][0]["text"]), db[nt.NOTE_THREADS_COLLECTION].find_one({})


async def test_over_stateless_http_the_author_is_the_client_that_initialized(db, monkeypatch):
    """הייצור: כל בקשה session חדש, ו-``client_params`` ריק ב-``tools/call``. השם מגיע מהטוקן
    ש-PostHog הטביע ב-``Mcp-Session-Id`` ב-``initialize`` והלקוח שולח בחזרה."""
    answer, stored = await _http_comment(db, monkeypatch, replay_session=True)

    assert answer["ok"] is True
    assert stored["comments"][0]["author"]["client"] == "claude-code"


async def test_without_a_session_token_the_author_is_unknown_and_said_so(db, monkeypatch, caplog):
    """לקוח שאינו שולח את הכותרת: התגובה נשמרת עם ``client: null`` (מוצגת "סוכן") — ו-WARNING."""
    caplog.set_level(logging.WARNING, logger="mcp_server.client_identity")

    answer, stored = await _http_comment(db, monkeypatch, replay_session=False)

    assert answer["ok"] is True
    assert stored["comments"][0]["author"]["client"] is None
    assert nt.author_label(stored["comments"][0]["author"], user_name="x") == nt.UNKNOWN_AGENT_LABEL
    assert any("connected client name unknown" in r.getMessage() for r in caplog.records)


# == שורת הפריימר =================================================================


def _primer(backend, *, user_id: int = USER):
    from starlette.applications import Starlette
    from starlette.testclient import TestClient

    from mcp_server.primer import PrimerCache, agent_primer_route

    class _Store:
        def verify(self, token):
            return {"user_id": user_id, "scopes": ["read"]} if token == "good" else None

    app = Starlette(routes=[agent_primer_route(backend, token_store=_Store(), cache=PrimerCache())])
    return TestClient(app).get("/api/agent/primer", headers={"Authorization": "Bearer good"})


def _pending_line(body: str) -> str:
    lines = [line for line in body.splitlines() if line.startswith("תגובות שממתינות לסוכן: ")]
    assert len(lines) <= 1
    return lines[0] if lines else ""


def _agent() -> dict:
    return nt.agent_author(client="claude-code", working_on="x")


def test_the_primer_lists_only_open_threads_whose_last_comment_is_the_users(db, monkeypatch):
    """פתוח והאחרונה של המשתמש — כן (גם שרשור שהמשתמש פתח וגם תשובה שלו לסוכן); הסוכן ענה
    אחרון, נפתר, פתק שנמחק, ופתק ריפו למי שאינו אדמין — לא. הסדר: החדש ביותר קודם."""
    from mcp_server import primer
    from mcp_server.backend import ProductionBackend

    monkeypatch.setattr(primer, "is_admin_user", lambda uid: uid == ADMIN)
    coll = db[nt.NOTE_THREADS_COLLECTION]
    db.user_preferences.insert_one({"user_id": USER, "agent_instructions": "כללים"})
    board = insert_board(db, USER, "CodeBot")
    file_id = insert_file(db, USER, "x.md")
    t0 = datetime(2026, 10, 13, 9, 0, tzinfo=timezone.utc)

    def thread(note_id, *authors, resolve=False, minute=0):
        tid = nt.create_thread(coll, user_id=USER, note_id=note_id, author=authors[0], body="a",
                               now=t0 + timedelta(minutes=minute))["thread_id"]
        for i, who in enumerate(authors[1:], start=1):
            nt.add_comment(coll, user_id=USER, note_id=note_id, thread_id=tid, author=who, body="b",
                           now=t0 + timedelta(minutes=minute, seconds=i))
        if resolve:
            nt.resolve_thread(coll, user_id=USER, note_id=note_id, thread_id=tid, author=nt.user_author())

    user_opened = insert_note(db, USER, board_id=board, title="תיקון כיוון קוד")
    user_answered = insert_note(db, USER, file_id=file_id, title="צבע קישורים")
    agent_last = insert_note(db, USER, board_id=board, title="טופל")
    resolved = insert_note(db, USER, board_id=board, title="נסגר")
    repo = insert_note(db, USER, repo_name="CodeBot", repo_path="a.py", title="בריפו")
    deleted = str(ObjectId())
    thread(user_opened, nt.user_author(), minute=1)
    thread(user_answered, _agent(), nt.user_author(), minute=2)
    thread(agent_last, nt.user_author(), _agent(), minute=3)
    thread(resolved, nt.user_author(), resolve=True, minute=4)
    thread(repo, nt.user_author(), minute=5)
    thread(deleted, nt.user_author(), minute=6)

    line = _pending_line(_primer(ProductionBackend(mongo_db=db)).text)

    assert line == (
        f'תגובות שממתינות לסוכן: "צבע קישורים" בקובץ x.md (note_id {user_answered}), '
        f'"תיקון כיוון קוד" בלוח CodeBot (note_id {user_opened})'
    )
    # האדמין רואה גם את פתק הריפו — אותו שער של ``get_note``.
    db.user_preferences.insert_one({"user_id": ADMIN, "agent_instructions": "כללים"})
    admin_repo = insert_note(db, ADMIN, repo_name="CodeBot", repo_path="a.py", title="בריפו")
    nt.create_thread(coll, user_id=ADMIN, note_id=admin_repo, author=nt.user_author(), body="a")
    admin_line = _pending_line(_primer(ProductionBackend(mongo_db=db), user_id=ADMIN).text)
    assert f'"בריפו" בקובץ a.py בריפו CodeBot (note_id {admin_repo})' in admin_line


def test_long_titles_keep_the_files_line_and_the_body_within_24kb(db):
    """כותרות ושמות לוחות ארוכים, הרבה פתקים ממתינים, והוראות כמעט בתקרה: שורת הקבצים במקומה
    ושלמה, שורת התגובות בתקציב שלה בלבד ועם ``note_id`` שלמים, ו"ועוד N" מדויק; הגוף ≤ 24KB."""
    from mcp_server.backend import ProductionBackend
    from mcp_server.primer import MAX_BYTES, MAX_PENDING_STATUS_BYTES

    coll = db[nt.NOTE_THREADS_COLLECTION]
    db.user_preferences.insert_one({"user_id": USER, "agent_instructions": "א" * 12_000})
    insert_file(db, USER, "קובץ-אחרון-שנשמר.md")
    board = insert_board(db, USER, "ל" * 200)
    # כותרות שונות זו מזו: בלוח אחד השם ייחודי (``one_title_per_board``), כמו בייצור.
    notes = [insert_note(db, USER, board_id=board, title="כ" * 78 + f"{i:02d}", minutes=i)
             for i in range(9)]
    for i, note_id in enumerate(notes):
        nt.create_thread(coll, user_id=USER, note_id=note_id, author=nt.user_author(), body="?",
                         now=datetime(2026, 10, 13, tzinfo=timezone.utc) + timedelta(minutes=i))

    resp = _primer(ProductionBackend(mongo_db=db))
    body = resp.text
    line = _pending_line(body)

    assert resp.status_code == 200 and len(resp.content) <= MAX_BYTES
    assert any(row.startswith("קבצים אחרונים שנשמרו ב-CodeKeeper: קובץ-אחרון-שנשמר.md")
               for row in body.splitlines())
    assert 0 < len(line.encode("utf-8")) <= MAX_PENDING_STATUS_BYTES
    shown = re.findall(r"\(note_id ([0-9a-f]+)\)", line)  # בסדר שבשורה
    assert shown and all(len(n) == 24 for n in shown)  # אף מזהה לא נחתך
    assert line.endswith(f", ועוד {len(notes) - len(shown)}")
    assert shown == list(reversed(notes))[: len(shown)]  # החדש ביותר קודם


def test_without_instructions_there_is_no_primer_and_no_threads_query(db):
    """בלי הוראות אין פריימר (204) — ולכן גם לא שורת תגובות, ואפילו לא השאילתה שלה. אותו
    פתק עם הוראות: השאילתה רצה פעם אחת והשורה שם. (החצי השני הוא מה שהופך את הטסט לראיה:
    בלעדיו "אין שאילתה" נכון גם בקוד שאין בו שורת תגובות בכלל.)"""
    from mcp_server.backend import ProductionBackend

    class _Counting(ProductionBackend):
        asked = 0

        def pending_note_threads(self, *args, **kwargs):
            type(self).asked += 1
            return super().pending_note_threads(*args, **kwargs)

    note = _board_note(db, title="ממתין")
    nt.create_thread(db[nt.NOTE_THREADS_COLLECTION], user_id=USER, note_id=note,
                     author=nt.user_author(), body="?")

    resp = _primer(_Counting(mongo_db=db))
    assert resp.status_code == 204 and _Counting.asked == 0

    db.user_preferences.insert_one({"user_id": USER, "agent_instructions": "כללים"})
    resp = _primer(_Counting(mongo_db=db))
    assert resp.status_code == 200 and _Counting.asked == 1
    assert f'"ממתין" בלוח CodeBot (note_id {note})' in _pending_line(resp.text)


def test_a_secret_in_a_title_is_redacted_before_the_title_is_cut(db):
    """כותרת עם טוקן שנחתך בגבול התווית: הסינון רץ על הכותרת **המלאה**, ולכן גם תחילת הטוקן
    אינה יוצאת. קיצוץ לפני הסינון היה משאיר ``ghp_`` ועוד 14 תווים — קצר מכדי להיות מזוהה —
    בפריימר. וה-``note_id`` שליד התווית נשאר שלם."""
    from mcp_server.backend import ProductionBackend

    db.user_preferences.insert_one({"user_id": USER, "agent_instructions": "כללים"})
    title = "x" * 20 + " ghp_" + "A1b2C3d4E5" * 3
    note = _board_note(db, title=title)
    nt.create_thread(db[nt.NOTE_THREADS_COLLECTION], user_id=USER, note_id=note,
                     author=nt.user_author(), body="?")

    line = _pending_line(_primer(ProductionBackend(mongo_db=db)).text)

    assert "ghp_" not in line and "A1b2" not in line
    assert f"(note_id {note})" in line


def test_a_board_id_that_is_not_an_object_id_only_drops_the_board_name(db):
    """פתק לוח שה-``board_id`` שלו אינו ObjectId (מסמך ישן או פגום): הפריט נשאר בשורה, עם
    ה-``note_id`` ובלי שם לוח, והפריימר מוגש. זה המצב שהוצהר ל-``InvalidId``."""
    from mcp_server.backend import ProductionBackend

    db.user_preferences.insert_one({"user_id": USER, "agent_instructions": "כללים"})
    note = insert_note(db, USER, board_id="not-an-object-id", title="לוח שבור")
    nt.create_thread(db[nt.NOTE_THREADS_COLLECTION], user_id=USER, note_id=note,
                     author=nt.user_author(), body="?")

    resp = _primer(ProductionBackend(mongo_db=db))

    assert resp.status_code == 200
    assert _pending_line(resp.text) == f'תגובות שממתינות לסוכן: "לוח שבור" בלוח (note_id {note})'


def test_a_bug_while_reading_the_board_id_is_not_swallowed_as_a_broken_id(db, monkeypatch):
    """רק ``InvalidId`` נתפס שם (``widened-exception-scope`` §5): חריגה אחרת היא באג, והיא עולה
    הלאה — ולא מתחפשת ל"מזהה לוח פגום" ומעלימה את שם הלוח בשקט."""
    import bson

    from mcp_server.backend import ProductionBackend

    real = bson.ObjectId

    def object_id(value=None):
        if value == "boom-board-id":
            raise RuntimeError("bug in the conversion, not a malformed id")
        return real(value)

    note = insert_note(db, USER, board_id="boom-board-id", title="באג")
    nt.create_thread(db[nt.NOTE_THREADS_COLLECTION], user_id=USER, note_id=note,
                     author=nt.user_author(), body="?")
    monkeypatch.setattr(bson, "ObjectId", object_id)

    with pytest.raises(RuntimeError, match="bug in the conversion"):
        ProductionBackend(mongo_db=db).pending_note_threads(
            USER, limit=3, include_repo_notes=False, preview_chars=40
        )
