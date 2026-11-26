"""מה תשובות הפתקים והשרשורים נושאות — ומה כבר לא.

**דרך הממשק, מעל ``ProductionBackend`` אמיתי** (``testing.md`` §1): כל קריאה עוברת ב-session של
הפרוטוקול מול ``build_mcp`` של הייצור, והתשובה נקראת כמו שהיא עוברת בחוט (``content[0].text``).
ה-handlers בונים את התשובה מחדש אחרי ה-backend (``save_note_from_view``, ``show_note``,
``_with_threads``), ולכן בדיקה על ``_note_write_answer`` או על ``_thread_row`` לבדם לא הייתה רואה את
מה שנשלח. רק האוספים הם הדמה המשותפת (``tests/_fake_mongo.py``), ומה שנשמר נקרא מהאוסף.

**כל בדיקה של "שדה לא חוזר" יושבת ליד עוגן חיובי** — ``ok: true``, המזהה, ושדה שחייב להישאר —
כי בדיקה ש-``content`` אינו ב-``note`` עוברת גם על תשובת שגיאה וגם על תשובה שאין בה ``note``.
**והציפיות כתובות ביד**, ולא מיובאות מהקבועים שהסריאלייזרים נבנים מהם (``_NOTE_FIELDS``,
``LEAN_NOTE_FIELDS``): טסט שגוזר את הציפייה ואת הבדיקה מאותו מקור עובר גם על קריסה.

מה שלא כאן: הדף של התצוגה מול תשובה אמיתית של השרת — ``tests/test_mcp_note_view_browser.py``;
השרשורים מול מונגו אמיתי — ``tests/test_note_threads_mcp.py``; הצינור הרזה מול מונגו אמיתי —
``tests/test_note_boards_mongo.py``.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from types import SimpleNamespace
from typing import Any

import pytest

pytest.importorskip("mcp")

from bson import ObjectId  # noqa: E402

# ``tests`` אינו חבילה — ראה את ה-docstring של ``tests/conftest.py``.
from _save_layer_harness import clear_local_cache, install_fake_collections, load_production_config  # noqa: E402
from test_note_content_preserved_mcp import _ObjectIdCollection, _RepoListing  # noqa: E402

import note_threads as nt  # noqa: E402

USER = 6161
STAMP = dt.datetime(2026, 11, 26, 9, 0, tzinfo=dt.timezone.utc)

#: השדות שאסור שיופיעו בפתק לוח — בשום תשובה — כשהקריאה לא כתבה אותם: עיגון של פתק קובץ, יעד
#: של ריפו, ארכיון ונעיצה ריקים, ומצב ממשק. כתוב ביד, ולא נגזר מ-``backend._NOTE_FIELDS``.
NOT_ON_A_BOARD_NOTE = {
    "line_start", "anchor_text", "repo_name", "repo_path", "archived_at", "files_page_pinned_at",
    "is_minimized", "mode",
}


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _one_colour(note: dict) -> None:
    """הצבע חוזר פעם אחת: ``color_id`` או ``color``, לא שניהם."""
    assert ("color" in note) != ("color_id" in note), note


class _NotesColl(_ObjectIdCollection):
    """``sticky_notes`` עם ``aggregate`` שמחזיר את מה שהצינור הרזה היה מחזיר (``_lean_notes_pipeline``).

    הצינור עצמו — ``$strLenBytes`` ו-``$type`` — נבדק מול mongod אמיתי
    (``tests/test_note_boards_mongo.py``); כאן נבדקת השורה שה-MCP בונה ממה שחזר. ``content_bytes`` הוא
    ``None`` לגוף שאינו מחרוזת, כמו ש-``$cond`` על ``$type`` מחזיר."""

    def aggregate(self, pipeline):
        match = pipeline[0]["$match"]
        rows = []
        for doc in sorted(self.docs, key=lambda d: d.get("created_at") or STAMP):
            if not self._match(doc, match):
                continue
            body = doc.get("content")
            rows.append({
                "_id": doc["_id"], "title": doc.get("title"), "color": doc.get("color"),
                "updated_at": doc.get("updated_at"), "created_at": doc.get("created_at"),
                "content_bytes": len(body.encode("utf-8")) if isinstance(body, str) else None,
            })
        return iter(rows)


class _ThreadsColl(_ObjectIdCollection):
    """``note_threads`` שהספירה המקובצת שלו נכשלת בשגיאת מסד — ``open_threads`` של השורה הרזה."""

    def aggregate(self, pipeline):
        from pymongo.errors import AutoReconnect

        raise AutoReconnect("counting open threads failed")


def build_store(monkeypatch: Any) -> Any:
    """האוספים של הבדיקות כאן — פונקציה ולא fixture, כדי שגם ``tests/test_mcp_note_view_browser.py`` ייבנה
    עליה בלי לייבא fixture (``TESTING-PATTERNS.md`` T3). הקורא קורא ל-``clear_local_cache`` בסוף."""
    load_production_config(monkeypatch)
    installed = install_fake_collections(monkeypatch)
    installed.raw.c["sticky_notes"] = _NotesColl()
    for name in ("note_boards", "sticky_note_versions"):
        installed.raw.c[name] = _ObjectIdCollection()
    installed.raw.c[nt.NOTE_THREADS_COLLECTION] = _ThreadsColl()
    installed.raw.c["repo_metadata"] = _RepoListing()
    installed.raw["repo_metadata"].insert_one({"repo_name": "repo"})
    installed.raw["repo_files"].insert_one({"repo_name": "repo", "path": "a.py"})
    return installed


@pytest.fixture
def store(monkeypatch):
    yield build_store(monkeypatch)
    clear_local_cache()


class _Server:
    """``build_mcp`` של הייצור, עם כלי הריפו, מעל ``ProductionBackend`` אמיתי. הקורא אדמין כש-``admin``."""

    def __init__(self, monkeypatch: Any, store: Any) -> None:
        import mcp.server.auth.middleware.auth_context as auth_context

        import mcp_server.server as srv
        from mcp_server.backend import ProductionBackend

        self.store = store
        self.admin = True
        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.setattr(srv, "current_user_id", lambda ctx=None: USER)
        monkeypatch.setattr(srv, "require_admin", lambda ctx=None: USER)
        monkeypatch.setattr(srv, "is_admin_user", lambda user_id: self.admin)
        monkeypatch.setattr(auth_context, "get_access_token", lambda: SimpleNamespace(scopes=["read", "write"]))
        self.backend = ProductionBackend(db_manager=store.dbm, mongo_db=store.raw)
        self.mcp = srv.build_mcp(self.backend, repo_backend=object())
        self.mcp._request_is_admin = lambda: True

    async def call_raw(self, tool: str, arguments: dict, *, client: str = "claude-code") -> dict:
        """ה-``CallToolResult`` כמו שהוא עובר בחוט — מה שמארח מעביר לדף של התצוגה."""
        from mcp import types
        from mcp.shared.memory import create_connected_server_and_client_session

        async with create_connected_server_and_client_session(
            self.mcp._mcp_server, client_info=types.Implementation(name=client, version="1.0"),
        ) as session:
            result = await session.call_tool(tool, arguments)
        return result.model_dump(mode="json", by_alias=True, exclude_none=True)

    async def call(self, tool: str, *, client: str = "claude-code", **arguments: Any) -> dict:
        result = await self.call_raw(tool, arguments, client=client)
        text = result["content"][0]["text"]
        if result.get("isError"):
            return {"tool_error": text}
        return json.loads(text)

    async def ok(self, tool: str, **arguments: Any) -> dict:
        res = await self.call(tool, **arguments)
        assert res.get("ok") is True, (tool, res)
        return res

    async def board(self) -> str:
        return (await self.ok("codekeeper_list_boards"))["boards"][0]["id"]

    def notes(self) -> Any:
        return self.store.raw["sticky_notes"]

    def threads(self) -> Any:
        return self.store.raw[nt.NOTE_THREADS_COLLECTION]

    def stored(self, note_id: str) -> dict:
        return self.notes().find_one({"_id": ObjectId(note_id)})

    def insert_note(self, **fields: Any) -> str:
        doc = {"user_id": USER, "content": "גוף", "color": "yellow", "created_at": STAMP,
               "updated_at": STAMP, **fields}
        return str(self.notes().insert_one(doc).inserted_id)


@pytest.fixture
def server(monkeypatch, store):
    return _Server(monkeypatch, store)


# == 1. תשובת כתיבה בלי הגוף ======================================================


async def test_a_write_answer_carries_the_hash_and_the_place_but_not_the_body(server):
    """הגוף אינו חוזר בתשובת כתיבה של כלי שהמודל רואה — ``content_sha256`` ו-``content_changed``
    כבר אומרים אם מה שנשמר הוא מה שנשלח, והגוף נקרא בחזרה ב-``codekeeper_get_note``. התשובה עדיין
    אומרת איפה הפתק יושב: הלוח, הריפו והנתיב, או השורה בקובץ. כל כתיבה נבדקת מיד אחריה, מול האוסף
    ומול קריאה חוזרת."""
    board = await server.board()
    await server.ok("codekeeper_save_file", file_name="a.md", code="# a\nb\n")
    on_board = {"board_id": board}
    written: dict = {}  # כלי ← מזהה הפתק שכתב

    async def check(tool: str, arguments: dict, body: str, place: dict) -> None:
        res = await server.ok(tool, **arguments)
        note = res["note"]
        assert res["content_changed"] is False and ObjectId.is_valid(note["id"]), (tool, res)
        assert note["content_sha256"] == _sha(body), (tool, res)
        assert {key: note.get(key) for key in place} == place, (tool, note)
        assert "content" not in note, (tool, note)
        assert server.stored(note["id"])["content"] == body
        read = await server.ok("codekeeper_get_note", note_id=note["id"])
        assert read["note"]["content"] == body and read["note"]["content_sha256"] == note["content_sha256"]
        written.setdefault(tool, note["id"])

    await check("codekeeper_create_board_note", {"board_id": board, "content": "על לוח", "title": "שם"},
                "על לוח", on_board)
    await check("codekeeper_create_note", {"file_name": "a.md", "content": "על קובץ", "line": 2},
                "על קובץ", {"line_start": 2})
    await check("codekeeper_create_repo_note", {"repo_name": "repo", "repo_path": "a.py", "content": "על ריפו"},
                "על ריפו", {"repo_name": "repo", "repo_path": "a.py"})
    note_id = written["codekeeper_create_board_note"]
    await check("codekeeper_update_note", {"note_id": note_id, "content": "אחרי עדכון"}, "אחרי עדכון", on_board)
    await check("codekeeper_note_str_replace", {"note_id": note_id, "old_string": "עדכון", "new_string": "החלפה"},
                "אחרי החלפה", on_board)


class _RewritingNotes(_NotesColl):
    """``sticky_notes`` שבו שכבה בדרך משנה את הגוף לפני שהוא נכתב — מה שהרשת נועדה לתפוס."""

    def insert_one(self, d):
        written = {**d, "content": d["content"].upper()}
        res = super().insert_one(written)
        d["_id"] = written["_id"]  # כמו pymongo, שמוסיף את ה-``_id`` למסמך של הקורא
        return res

    def find_one_and_update(self, q, u, *a, **k):
        sets = dict(u.get("$set") or {})
        if "content" in sets:
            sets["content"] = sets["content"].upper()
        return super().find_one_and_update(q, {**u, "$set": sets}, *a, **k)


async def test_a_body_stored_differently_comes_back_as_a_diff_and_not_as_the_body(server, store):
    """גם כשמה שנשמר שונה ממה שנשלח הגוף אינו חוזר: ``content_changed: true`` ו-``content_diff``
    אומרים איפה, וה-hash הוא של מה שנשמר. כך נשאר חוזה אחד לקבצים ולפתקים (``_content_verdict``)."""
    board = await server.board()
    store.raw.c["sticky_notes"] = _RewritingNotes()

    created = await server.ok("codekeeper_create_board_note", board_id=board, content="abc")
    updated = await server.ok("codekeeper_update_note", note_id=created["note"]["id"], content="xyz")

    for res, stored in ((created, "ABC"), (updated, "XYZ")):
        assert res["content_changed"] is True and res["content_diff"]["line"] == 1, res
        assert res["note"]["content_sha256"] == _sha(stored) and res["note"]["board_id"] == board
        assert "content" not in res["note"], res


async def test_the_view_save_answer_carries_what_the_page_reads(server):
    """``codekeeper_note_view_save`` חוזר לדף ולא למודל, והדף בודק ``note.content`` ומעדכן ממנו את
    הגרסה שהוא מחזיק (``readNote`` ב-``mcp_server/apps/note_view.js``). לכן שם — ורק שם — הגוף חוזר,
    עם ה-hash, השם, וצבע ב-``hex`` שהדף צובע לפיו."""
    board = await server.board()
    note_id = (await server.ok("codekeeper_create_board_note", board_id=board, content="לפני",
                               title="שם", color="orange_light"))["note"]["id"]
    shown = await server.ok("codekeeper_show_note", note_id=note_id)

    saved = await server.ok("codekeeper_note_view_save", note_id=note_id, content="אחרי",
                            expected_content_sha256=shown["note"]["content_sha256"])

    note = saved["note"]
    assert (note["id"], note["content"], note["content_sha256"], note["title"]) == (
        note_id, "אחרי", _sha("אחרי"), "שם"), saved
    assert note["color"] == "#ffeddb" and "color_id" not in note, note
    assert saved["content_changed"] is False


async def test_show_note_paints_by_a_hex_colour_and_get_note_names_the_palette_colour(server):
    """``codekeeper_show_note`` — ``color`` ב-``hex``, שהדף צובע לפיו; ``codekeeper_get_note`` —
    ``color_id`` של הפלטה. בשתיהן הצבע פעם אחת."""
    board = await server.board()
    note_id = (await server.ok("codekeeper_create_board_note", board_id=board, content="x",
                               color="orange_light"))["note"]["id"]

    shown = (await server.ok("codekeeper_show_note", note_id=note_id))["note"]
    read = (await server.ok("codekeeper_get_note", note_id=note_id))["note"]

    assert shown["color"] == "#ffeddb" and "color_id" not in shown
    assert read["color_id"] == "orange_light" and "color" not in read
    legacy = (await server.ok("codekeeper_get_note", note_id=server.insert_note(board_id=board, color="#123456")))
    assert legacy["note"]["color"] == "#123456" and "color_id" not in legacy["note"]


async def test_a_write_that_leaves_the_body_carries_the_hash_and_the_field_it_wrote(server):
    """צבע, מזעור, שורה: אין גוף שהכלי התכוון לשמור, ולכן אין ``content_changed`` — רק ה-hash, ומה
    שהקריאה כתבה. מצב ממשק (``is_minimized``) חוזר כאן כי הקריאה כתבה אותו."""
    board = await server.board()
    note_id = (await server.ok("codekeeper_create_board_note", board_id=board, content="גוף"))["note"]["id"]

    colour = await server.ok("codekeeper_update_note", note_id=note_id, color="pink_light")
    minimized = await server.ok("codekeeper_update_note", note_id=note_id, is_minimized=True)

    for res in (colour, minimized):
        assert res["note"]["content_sha256"] == _sha("גוף") and res["note"]["board_id"] == board
        assert "content_changed" not in res and "content" not in res["note"], res
    assert colour["note"]["color_id"] == "pink_light" and "is_minimized" not in colour["note"]
    assert minimized["note"]["is_minimized"] is True


async def test_a_create_whose_read_back_fails_has_only_the_id_and_a_null_verdict(server, monkeypatch):
    """הכתיבה קרתה, ולכן ``ok: true``; ``note`` נושא רק ``id`` ו-``content_changed`` הוא ``null`` — כמו
    היום. ``ok: false`` היה שולח את הסוכן ליצור פתק שני."""
    from pymongo.errors import AutoReconnect

    board = await server.board()
    coll = server.notes()

    def failing_find_one(q=None, *a, **k):
        raise AutoReconnect("the primary went away")

    monkeypatch.setattr(coll, "with_options", lambda **kw: SimpleNamespace(find_one=failing_find_one))
    res = await server.call("codekeeper_create_board_note", board_id=board, content="גוף")

    (doc,) = coll.docs
    assert res == {"ok": True, "note": {"id": str(doc["_id"])}, "content_changed": None}


# == 2. שדות שאין להם משמעות לסוכן =================================================


async def test_a_board_note_carries_no_field_of_another_kind_in_any_answer(server):
    """פתק לוח, בקריאה ובכתיבה: בלי שדות של פתק קובץ או ריפו, בלי ארכיון ונעיצה ריקים, בלי מצב
    ממשק שהקריאה לא כתבה, והצבע פעם אחת."""
    board = await server.board()
    created = await server.ok("codekeeper_create_board_note", board_id=board, content="גוף", title="שם")
    note_id = created["note"]["id"]
    answers = {
        "create": created["note"],
        "get": (await server.ok("codekeeper_get_note", note_id=note_id))["note"],
        "show": (await server.ok("codekeeper_show_note", note_id=note_id))["note"],
        "list": (await server.ok("codekeeper_list_board_notes", board_id=board))["notes"][0],
        "update": (await server.ok("codekeeper_update_note", note_id=note_id, content="חדש"))["note"],
        "replace": (await server.ok("codekeeper_note_str_replace", note_id=note_id, old_string="חדש",
                                    new_string="ישן"))["note"],
    }
    for where, note in answers.items():
        assert note["id"] == note_id and note["title"] == "שם", (where, note)
        assert not NOT_ON_A_BOARD_NOTE & set(note), (where, note)
        _one_colour(note)


async def test_mode_returns_on_create_only_when_the_agent_chose_it(server):
    """``mode`` הוא מצב ממשק: חוזר רק כשהקריאה קבעה אותו — כאן, כשהסוכן שלח אותו ביצירה."""
    board = await server.board()

    chosen = await server.ok("codekeeper_create_board_note", board_id=board, content="x", mode="screen")
    default = await server.ok("codekeeper_create_board_note", board_id=board, content="y")

    assert chosen["note"]["mode"] == "screen" and server.stored(chosen["note"]["id"])["mode"] == "screen"
    assert "mode" not in default["note"] and server.stored(default["note"]["id"])["mode"] == "surface"


async def test_nulls_that_carry_meaning_still_come_back_as_null(server):
    """``null`` ושדה נעדר הם שני דברים: שדה ש-``null`` בו נושא משמעות ממשיך לחזור כ-``null``.
    ``line_start`` של פתק קובץ צף ("לא מעוגן לשורה"), ``version`` של גוף ריק, ובשורה הרזה —
    ``content_bytes`` של גוף שאינו מחרוזת ו-``open_threads`` כשהספירה נכשלה ("לא ידוע", לא אפס)."""
    board = await server.board()
    await server.ok("codekeeper_save_file", file_name="a.md", code="x")
    floating = await server.ok("codekeeper_create_note", file_name="a.md", content="צף")
    empty = server.insert_note(board_id=board, content="")
    server.insert_note(board_id=board, content=None)

    read = await server.ok("codekeeper_get_note", note_id=floating["note"]["id"])
    lean = await server.ok("codekeeper_list_board_notes", board_id=board, include_content=False)

    assert "line_start" in floating["note"] and floating["note"]["line_start"] is None
    assert "line_start" in read["note"] and read["note"]["line_start"] is None
    assert (await server.ok("codekeeper_get_note", note_id=empty))["version"] is None
    rows = {row["id"]: row for row in lean["notes"]}
    assert rows[empty]["content_bytes"] == 0
    assert [row["content_bytes"] for row in lean["notes"] if row["id"] != empty] == [None]
    assert all("open_threads" in row and row["open_threads"] is None for row in lean["notes"]), lean


async def test_get_and_show_name_the_place_once_outside_the_note(server):
    """בפתק בודד היעד חוזר מחוץ ל-``note`` — ``target`` עם שדות הזיהוי, בצורה שכלי הרשימה מקבל — ולא
    בתוכו: ``board_id`` פעם אחת, ובפתק ריפו ``repo_name`` ו-``repo_path`` פעם אחת."""
    board = await server.board()
    on_board = (await server.ok("codekeeper_create_board_note", board_id=board, content="x"))["note"]["id"]
    on_repo = (await server.ok("codekeeper_create_repo_note", repo_name="repo", repo_path="a.py",
                               content="y"))["note"]["id"]

    for tool in ("codekeeper_get_note", "codekeeper_show_note"):
        board_answer = await server.ok(tool, note_id=on_board)
        repo_answer = await server.ok(tool, note_id=on_repo)
        assert (board_answer["target"], board_answer["board_id"]) == ("board", board), board_answer
        assert "board_id" not in board_answer["note"], board_answer
        assert (repo_answer["target"], repo_answer["repo_name"], repo_answer["repo_path"]) == ("repo", "repo", "a.py")
        assert not {"repo_name", "repo_path"} & set(repo_answer["note"]), repo_answer


async def test_a_listing_names_its_board_or_file_once_at_the_top(server):
    """ברשימה עם גופים היעד בראש התשובה, ולא בכל פתק. פתק קובץ ברשימה עדיין נושא את העיגון שלו."""
    board = await server.board()
    await server.ok("codekeeper_create_board_note", board_id=board, content="x")
    await server.ok("codekeeper_create_repo_note", repo_name="repo", repo_path="a.py", content="y")
    await server.ok("codekeeper_save_file", file_name="a.md", code="# a\nb\n")
    await server.ok("codekeeper_create_note", file_name="a.md", content="z", line=2)

    on_board = await server.ok("codekeeper_list_board_notes", board_id=board)
    on_repo = await server.ok("codekeeper_list_repo_notes", repo_name="repo", repo_path="a.py")
    on_file = await server.ok("codekeeper_list_notes", file_name="a.md")

    assert on_board["board_id"] == board and [n["content"] for n in on_board["notes"]] == ["x"]
    assert "board_id" not in on_board["notes"][0]
    assert (on_repo["repo_name"], on_repo["repo_path"], on_repo["notes"][0]["content"]) == ("repo", "a.py", "y")
    assert not {"repo_name", "repo_path"} & set(on_repo["notes"][0])
    assert on_file["file_name"] == "a.md" and on_file["notes"][0]["line_start"] == 2


async def test_an_archived_note_and_a_pinned_note_carry_their_stamps(server):
    """``archived_at`` כשהוא לא ריק אומר שהרעיון נסגר, ו-``files_page_pinned_at`` אומר שהפתק נעוץ —
    שניהם חוזרים, בקריאה ובכתיבה. ריקים — לא (``test_a_board_note_carries_no_field_...``)."""
    board = await server.board()
    archived = server.insert_note(archived_at=STAMP)
    pinned = server.insert_note(board_id=board, files_page_pinned_at=STAMP)

    read_archived = await server.ok("codekeeper_get_note", note_id=archived)
    write_archived = await server.ok("codekeeper_update_note", note_id=archived, content="חדש")
    read_pinned = await server.ok("codekeeper_get_note", note_id=pinned)

    assert read_archived["target"] == "archive" and read_archived["note"]["archived_at"] == STAMP.isoformat()
    assert write_archived["note"]["archived_at"] == STAMP.isoformat()
    assert read_pinned["note"]["files_page_pinned_at"] == STAMP.isoformat()


async def test_a_half_repo_note_is_still_gated_and_keeps_its_fields_inside(server):
    """פתק שנושא רק חצי יעד ריפו (``target: "unknown"``): אין שדות יעד מחוץ ל-``note``, ולכן הם חוזרים
    בתוכו — ושער פתקי הריפו נסגר עליו בפני מי שאינו אדמין."""
    half = server.insert_note(repo_name="repo")

    server.admin = False
    assert await server.call("codekeeper_get_note", note_id=half) == {"ok": False, "error": "not_found"}
    server.admin = True
    read = await server.ok("codekeeper_get_note", note_id=half)
    assert read["target"] == "unknown" and read["note"]["repo_name"] == "repo"


async def test_the_lean_row_keeps_its_shape(server):
    """השורה הרזה לא השתנתה — גם הצבע בה נשאר זוג (``color`` ו-``color_id``). כתוב ביד, בסדר שלו."""
    board = await server.board()
    await server.ok("codekeeper_create_board_note", board_id=board, content="x", title="שם")

    (row,) = (await server.ok("codekeeper_list_board_notes", board_id=board, include_content=False))["notes"]

    assert tuple(row) == ("id", "title", "color", "color_id", "content_bytes", "updated_at", "open_threads")


#: ההכרעה על כל שדה במודל של פתק, **כתובה ביד** — לא נגזרת מ-``backend._NOTE_FIELDS``. שדה חדש
#: ב-``_NOTE_FIELDS`` בלי הכרעה כאן מפיל את ``test_every_note_field_has_a_decision``.
DECISIONS = {
    "title": "when_set",
    "color": "color",
    "board_id": "board_target",
    "repo_name": "repo_target",
    "repo_path": "repo_target",
    "line_start": "file_anchor",
    "anchor_text": "file_anchor",
    "archived_at": "when_set",
    "files_page_pinned_at": "when_set",
    "is_minimized": "ui_state",
    "mode": "ui_state",
    "created_at": "always",
    "updated_at": "always",
    "content": "body",
}


def test_every_note_field_has_a_decision():
    """כל שדה ב-``_NOTE_FIELDS`` — נשאר תמיד, לפי סוג, כשיש בו ערך, או רק כשנכתב — ויש עליו הכרעה כאן."""
    from mcp_server.backend import _NOTE_FIELDS

    assert set(_NOTE_FIELDS) == set(DECISIONS)


async def test_each_decision_holds_in_a_read_and_in_a_write(server):
    """כל הכרעה ב-``DECISIONS`` נבדקת על פתק מכל סוג, בקריאה (``codekeeper_get_note``) ובכתיבה
    (``codekeeper_update_note`` עם גוף), כשכל השדות במסמך מלאים — כך ששדה שלא חזר לא חזר בגלל הכלל,
    ולא בגלל שהיה ריק."""
    board = await server.board()
    full = {"title": "שם", "line_start": 4, "anchor_text": "## כותרת", "is_minimized": True,
            "mode": "screen", "files_page_pinned_at": STAMP}
    kinds = {
        "file": server.insert_note(file_id=str(ObjectId()), file_name="a.md", **full),
        "board": server.insert_note(board_id=board, **full),
        "repo": server.insert_note(repo_name="repo", repo_path="a.py", **full),
        "archive": server.insert_note(archived_at=STAMP, **full),
    }
    for kind, note_id in kinds.items():
        read = (await server.ok("codekeeper_get_note", note_id=note_id))["note"]
        write = (await server.ok("codekeeper_update_note", note_id=note_id, content="חדש " + kind))["note"]
        for field, decision in DECISIONS.items():
            shown = {"read": field in read, "write": field in write}
            if decision == "always":
                expected = {"read": True, "write": True}
            elif decision == "body":
                expected = {"read": True, "write": False}
            elif decision == "when_set":
                is_set = field != "archived_at" or kind == "archive"
                expected = {"read": is_set, "write": is_set}
            elif decision == "color":
                expected = {"read": False, "write": False}  # המזהה: ``color_id`` — למטה
            elif decision == "file_anchor":
                expected = {"read": kind == "file", "write": kind == "file"}
            elif decision == "board_target":
                expected = {"read": False, "write": kind == "board"}
            elif decision == "repo_target":
                expected = {"read": False, "write": kind == "repo"}
            elif decision == "ui_state":
                expected = {"read": False, "write": False}
            else:  # pragma: no cover
                raise AssertionError(decision)
            assert shown == expected, (kind, field, decision, read, write)
        assert read["color_id"] == write["color_id"] == "yellow", (kind, read, write)
        assert read["content"] == "גוף" and read["content_sha256"] == _sha("גוף")
        assert write["content_sha256"] == _sha("חדש " + kind)


# == 3. שרשורי תגובות ==============================================================


def _agent(client: Any = "claude-code", working_on: str = "בדיקה") -> dict:
    return nt.agent_author(client=client, working_on=working_on)


async def test_the_author_fields_follow_the_kind_and_not_the_value(server):
    """תגובה של משתמש — ``kind`` בלבד. תגובה של סוכן — ``kind``, ``client`` ו-``working_on``, גם כש-
    ``client`` הוא ``null`` ("סוכן ששמו לא ידוע"). וכך גם ``resolved_by``."""
    board = await server.board()
    note = server.insert_note(board_id=board)
    coll = server.threads()
    tid = nt.create_thread(coll, user_id=USER, note_id=note, author=nt.user_author(), body="של המשתמש")["thread_id"]
    nt.add_comment(coll, user_id=USER, note_id=note, thread_id=tid, author=_agent(client=None), body="בלי שם")
    nt.add_comment(coll, user_id=USER, note_id=note, thread_id=tid, author=_agent(), body="עם שם")
    nt.resolve_thread(coll, user_id=USER, note_id=note, thread_id=tid, author=nt.user_author())

    (row,) = (await server.ok("codekeeper_get_note", note_id=note, part="threads"))["threads"]

    assert [c["author"] for c in row["comments"]] == [
        {"kind": "user"},
        {"kind": "agent", "client": None, "working_on": "בדיקה"},
        {"kind": "agent", "client": "claude-code", "working_on": "בדיקה"},
    ]
    assert [c["body"] for c in row["comments"]] == ["של המשתמש", "בלי שם", "עם שם"]
    assert row["resolved_by"] == {"kind": "user"} and row["resolved_at"]


async def test_the_summaries_come_back_only_when_not_every_comment_is_in_the_row(server):
    """``comment_count``, ``last_author_kind``, ``last_at`` ו-``created_at`` של שרשור הם סיכומים של
    התגובות. שרשור שכל התגובות שלו בשורה — בלעדיהם; שורה מקופלת או עם ``earlier_comments`` — איתם,
    כי שם הם כל מה שידוע על מה שלא הוצג. כל ערך נבדק מול התגובות במסמך שבמסד."""
    from mcp_server.handlers import NOTE_THREAD_DEFAULT_TAIL

    summaries = {"comment_count", "last_author_kind", "last_at", "created_at"}
    board = await server.board()
    note = server.insert_note(board_id=board)
    coll = server.threads()
    whole = nt.create_thread(coll, user_id=USER, note_id=note, author=_agent(), body="פתוח")["thread_id"]
    closed = nt.create_thread(coll, user_id=USER, note_id=note, author=_agent(), body="ייסגר")["thread_id"]
    nt.resolve_thread(coll, user_id=USER, note_id=note, thread_id=closed, author=_agent())
    nt.add_comment(coll, user_id=USER, note_id=note, thread_id=closed, author=nt.user_author(),
                   body="אחרי הסגירה", reopen=False)
    long = nt.create_thread(coll, user_id=USER, note_id=note, author=_agent(), body="0")["thread_id"]
    for i in range(1, NOTE_THREAD_DEFAULT_TAIL + 3):
        nt.add_comment(coll, user_id=USER, note_id=note, thread_id=long, author=nt.user_author(), body=str(i))

    rows = {row["id"]: row for row in (await server.ok("codekeeper_get_note", note_id=note))["threads"]}
    full = {row["id"]: row for row in (await server.ok("codekeeper_get_note", note_id=note, part="threads"))["threads"]}

    assert rows[whole]["comments"] and not summaries & set(rows[whole]), rows[whole]
    stored_closed = coll.find_one({"_id": ObjectId(closed)})
    assert "comments" not in rows[closed]
    assert (rows[closed]["comment_count"], rows[closed]["last_author_kind"]) == (2, "user")
    assert rows[closed]["last_at"] == stored_closed["comments"][-1]["created_at"].isoformat()
    assert rows[closed]["created_at"] == stored_closed["comments"][0]["created_at"].isoformat()
    assert rows[long]["earlier_comments"] == 3 and summaries <= set(rows[long]), rows[long]
    assert full[closed]["comments"] and not summaries & set(full[closed]), full[closed]
    assert full[closed]["resolved_by"] == {"kind": "agent", "client": "claude-code", "working_on": "בדיקה"}
    assert full[closed]["resolved_at"] and full[long]["comments"] and not summaries & set(full[long])


async def test_a_thread_that_did_not_fit_the_budget_keeps_its_summaries(server):
    """שרשור שקופל בגלל התקציב (``comments_truncated``) מוצג בלי תגובות — ועם הסיכומים."""
    board = await server.board()
    note = server.insert_note(board_id=board)
    coll = server.threads()
    big = "ש" * nt.MAX_COMMENT_CHARS
    for _ in range(6):
        tid = nt.create_thread(coll, user_id=USER, note_id=note, author=nt.user_author(), body=big)["thread_id"]
        for _ in range(8):
            nt.add_comment(coll, user_id=USER, note_id=note, thread_id=tid, author=nt.user_author(), body=big)

    read = await server.ok("codekeeper_get_note", note_id=note, part="threads")

    collapsed = [row for row in read["threads"] if "comments" not in row]
    assert read["comments_truncated"] is True and collapsed
    assert all(row["comment_count"] == 9 and row["last_author_kind"] == "user" for row in collapsed), collapsed


async def test_threads_say_none_and_unknown_as_before_and_hint_only_when_something_is_hidden(server, monkeypatch):
    """``threads: []`` — "נבדק, ואין"; ``threads: null`` עם ``threads_error`` — "לא ידוע". ``threads_hint``
    מופיע רק כשמשהו לא הוצג."""
    from pymongo.errors import AutoReconnect

    board = await server.board()
    bare = server.insert_note(board_id=board)
    talked = server.insert_note(board_id=board)
    nt.create_thread(server.threads(), user_id=USER, note_id=talked, author=_agent(), body="פתוח")

    empty = await server.ok("codekeeper_get_note", note_id=bare)
    open_only = await server.ok("codekeeper_get_note", note_id=talked)
    assert empty["threads"] == [] and "threads_hint" not in empty
    assert len(open_only["threads"]) == 1 and "threads_hint" not in open_only

    def failing_find(*a, **k):
        raise AutoReconnect("threads are unavailable")

    monkeypatch.setattr(server.threads(), "find", failing_find)
    unknown = await server.ok("codekeeper_get_note", note_id=talked)
    assert unknown["threads"] is None and unknown["threads_error"] == "threads_unavailable"
    assert unknown["note"]["content"] == "גוף"


async def test_a_comment_answer_carries_what_the_agent_does_not_know(server):
    """תשובת ``codekeeper_comment_note``: ``thread.id``, ``comment.id``, ``body_sha256`` ו-``client`` — בלי
    ``working_on`` שנשלח, בלי ``kind`` של הכותב, בלי ``last_author_kind``, ``note_id`` ו-``action``, ובלי
    אותו זמן פעמיים. בשרשור קיים — גם ``status`` ו-``comment_count``."""
    board = await server.board()
    note = server.insert_note(board_id=board)

    created = await server.ok("codekeeper_comment_note", note_id=note, working_on="משימה", body="שלום")
    (stored,) = server.threads().docs
    tid = str(stored["_id"])
    nt.add_comment(server.threads(), user_id=USER, note_id=note, thread_id=tid, author=nt.user_author(), body="ענה")
    replied = await server.ok("codekeeper_comment_note", note_id=note, working_on="משימה", body="שוב",
                              thread_id=tid)

    assert created["thread"] == {"id": tid}, created
    assert created["comment"] == {
        "id": stored["comments"][0]["id"], "author": {"client": "claude-code"},
        "created_at": stored["comments"][0]["created_at"].isoformat(), "body_sha256": _sha("שלום"),
    }, created
    assert set(created) == {"ok", "thread", "comment"}
    assert replied["thread"] == {"id": tid, "status": "open", "comment_count": 3}, replied
    assert replied["comment"]["author"] == {"client": "claude-code"} and replied["comment"]["created_at"]
    assert "משימה" not in json.dumps(created, ensure_ascii=False) + json.dumps(replied, ensure_ascii=False)


async def test_an_unknown_client_name_is_kept_as_null_in_the_comment_answer(server):
    """``client`` נקבע מהחיבור ולא נשלח — ולכן הוא נשאר גם כשהוא ``null``: זו הדרך היחידה של הסוכן לדעת
    שהתגובה שלו מוצגת בוובאפ "סוכן"."""
    board = await server.board()
    note = server.insert_note(board_id=board)

    res = await server.ok("codekeeper_comment_note", client=" ", note_id=note, working_on="x", body="y")

    assert res["comment"]["author"] == {"client": None}, res
    assert server.threads().docs[0]["comments"][0]["author"]["client"] is None


async def test_closing_answers_once_with_the_close_time_and_the_client(server):
    """סגירה עם משפט סיכום ובלי: ``status``, ``comment_count`` ו-``resolved_at``, בלי ``working_on`` שנשלח
    (גם לא ב-``resolved_by``). עם סיכום — ``client`` ב-``comment.author``, והזמן הוא ``resolved_at`` בלבד;
    בלי סיכום ``comment`` הוא ``null``, ו-``client`` ב-``thread.resolved_by``."""
    board = await server.board()
    note = server.insert_note(board_id=board)
    coll = server.threads()
    with_summary = nt.create_thread(coll, user_id=USER, note_id=note, author=_agent(), body="א")["thread_id"]
    without = nt.create_thread(coll, user_id=USER, note_id=note, author=_agent(), body="ב")["thread_id"]

    summed = await server.ok("codekeeper_comment_note", note_id=note, working_on="סגירה", thread_id=with_summary,
                             resolve=True, body="נפתר")
    closed = await server.ok("codekeeper_comment_note", note_id=note, working_on="סגירה", thread_id=without,
                             resolve=True)

    stored = coll.find_one({"_id": ObjectId(with_summary)})
    assert summed["thread"] == {"id": with_summary, "status": "resolved", "comment_count": 2,
                                "resolved_at": stored["resolved_at"].isoformat()}, summed
    assert summed["comment"] == {"id": stored["comments"][-1]["id"], "author": {"client": "claude-code"},
                                 "body_sha256": _sha("נפתר")}, summed
    assert closed["comment"] is None
    assert closed["thread"]["resolved_by"] == {"client": "claude-code"} and closed["thread"]["resolved_at"]
    assert (closed["thread"]["status"], closed["thread"]["comment_count"]) == ("resolved", 1)
    assert "סגירה" not in json.dumps(summed, ensure_ascii=False) + json.dumps(closed, ensure_ascii=False)


async def test_answering_a_thread_someone_else_closed_says_who_closed_it(server):
    """תשובה עם ``reopen=false`` בשרשור שהמשתמש סגר: השרשור נשאר סגור, והתשובה אומרת מי סגר ומתי —
    לפי הסוג (משתמש: ``kind`` בלבד)."""
    board = await server.board()
    note = server.insert_note(board_id=board)
    coll = server.threads()
    tid = nt.create_thread(coll, user_id=USER, note_id=note, author=_agent(), body="א")["thread_id"]
    nt.resolve_thread(coll, user_id=USER, note_id=note, thread_id=tid, author=nt.user_author())

    res = await server.ok("codekeeper_comment_note", note_id=note, working_on="x", thread_id=tid, body="לתיעוד",
                          reopen=False)

    assert res["thread"]["status"] == "resolved" and res["thread"]["comment_count"] == 2
    assert res["thread"]["resolved_by"] == {"kind": "user"} and res["thread"]["resolved_at"], res


async def test_a_comment_that_was_not_read_back_has_a_null_hash_and_only_ids(server, monkeypatch):
    """כשהשרשור החדש לא נקרא בחזרה — ``body_sha256: null`` ורק מזהים, כמו היום."""
    from pymongo.errors import AutoReconnect

    board = await server.board()
    note = server.insert_note(board_id=board)
    coll = server.threads()

    def failing_find_one(*a, **k):
        raise AutoReconnect("the primary went away")

    monkeypatch.setattr(coll, "with_options", lambda **kw: SimpleNamespace(find_one=failing_find_one))
    res = await server.ok("codekeeper_comment_note", note_id=note, working_on="x", body="y")

    (stored,) = coll.docs
    assert res["thread"] == {"id": str(stored["_id"])}
    assert res["comment"] == {"id": stored["comments"][0]["id"], "body_sha256": None}


async def test_the_answer_net_measures_the_rows_that_are_sent(server, monkeypatch):
    """הצורה הרזה של שורת שרשור נבנית ב-``_thread_row``, **לפני** המדידה — ולא כהשמטה אחריה.

    בדרך כלל הרשת (``fit_lists`` ב-``_with_threads``) אינה חותכת, כי ``_plan_threads`` מתכנן לפי חסמים
    עליונים. כאן החסמים מוקטנים בכוונה, כדי שהרשת היא שתחתוך — על מאות שרשורים קטנים, שבהם ההבדל בין
    שורה עם הסיכומים לשורה בלעדיהם גדול משורה שלמה. אילו נמדדה שורה כבדה ממה שנשלח, הרשת הייתה
    משאירה בחוץ שרשורים שנכנסים: התשובה שיצאה, ועוד השרשור הראשון שירד, היו עדיין בתוך התקציב.
    """
    from mcp_server import handlers
    from mcp_server.answer_size import OUTPUT_BYTE_BUDGET, list_item_cost, wire_json

    board = await server.board()
    note = server.insert_note(board_id=board)
    coll = server.threads()
    for _ in range(900):
        nt.create_thread(coll, user_id=USER, note_id=note, author=_agent(), body="x")
    monkeypatch.setattr(handlers, "_thread_cost_bounds", lambda: (1, 1, 1, 1))

    read = await server.ok("codekeeper_get_note", note_id=note, part="threads")

    kept = [row["id"] for row in read["threads"]]
    order = [meta["id"] for meta in server.backend.note_threads(USER, note_id=note)]
    assert read["threads_truncated"] is True and kept == order[:len(kept)] and len(kept) < len(order)
    sent = len(wire_json(read))
    assert sent <= OUTPUT_BYTE_BUDGET
    (first_dropped,) = (await server.ok("codekeeper_get_note", note_id=note, part="threads",
                                        thread_id=order[len(kept)]))["threads"]
    assert "comment_count" not in first_dropped  # השורה בצורה שבה היא נשלחת
    assert sent + list_item_cost(first_dropped, depth=0) > OUTPUT_BYTE_BUDGET - 64, (sent, len(kept))
