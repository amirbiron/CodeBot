"""השמירה מהתצוגה של פתק בתוך Claude — ``codekeeper_note_view_save``.

**דרך הממשק, מעל ``ProductionBackend`` אמיתי** (``testing.md`` §1): כל קריאה עוברת ב-session של
הפרוטוקול מול ``build_mcp`` — ``tools/list``, ``tools/call`` — ומה שנשמר נקרא מהאוסף עצמו, לא
מתשובת הכלי. רק האוספים הם הדמה המשותפת (``tests/_fake_mongo.py``), כמו ב-
``tests/test_note_content_preserved_mcp.py``, שממנו גם המחלקה שנותנת ``ObjectId``.

**מה שנבדק כאן הוא החוזה של "לא מסלול כתיבה שלישי":** השמירה עוברת באותה בדיקת גוף, באותה דריסה
מותנית ובאותה היסטוריה של ``codekeeper_note_str_replace`` (``handlers._write_note_body``), ובשער של
``codekeeper_show_note``. הדריסה המותנית עצמה מול מונגו אמיתי — ``find_one_and_update`` עם הגוף
שנקרא במסנן — נבדקת על ``backend.update_note`` בטסטים של המונגו האמיתי; כאן היא נבדקת דרך הכלי.

מה שלא כאן: מה הדף עושה עם התשובות — ``tests/mcp-note-view.test.js``; העורך בדפדפן —
``tests/test_mcp_note_view_browser.py``.
"""

from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace
from typing import Any

import pytest

pytest.importorskip("mcp")

from bson import ObjectId  # noqa: E402

# ``tests`` אינו חבילה — ראה את ה-docstring של ``tests/conftest.py``.
from _save_layer_harness import clear_local_cache, install_fake_collections, load_production_config  # noqa: E402
from test_note_content_preserved_mcp import _ObjectIdCollection  # noqa: E402

from mcp_server import handlers  # noqa: E402
from sticky_notes_target import MAX_NOTE_CHARS  # noqa: E402

USER, OTHER = 6161, 7272
TOOL = "codekeeper_note_view_save"


@pytest.fixture
def store(monkeypatch):
    load_production_config(monkeypatch)
    installed = install_fake_collections(monkeypatch)
    for name in ("sticky_notes", "note_boards", "sticky_note_versions"):
        installed.raw.c[name] = _ObjectIdCollection()
    yield installed
    clear_local_cache()


class _Server:
    """``build_mcp`` של הייצור מעל ``ProductionBackend`` אמיתי — ומי שואל, ובאיזו הרשאה, משתנה."""

    def __init__(self, monkeypatch: Any, store: Any) -> None:
        import mcp.server.auth.middleware.auth_context as auth_context

        import mcp_server.server as srv
        from mcp_server.backend import ProductionBackend

        self.store = store
        self.user = USER
        self.scopes = ["read", "write"]
        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.setattr(srv, "current_user_id", lambda ctx=None: self.user)
        monkeypatch.setattr(srv, "is_admin_user", lambda user_id: False)
        monkeypatch.setattr(auth_context, "get_access_token", lambda: SimpleNamespace(scopes=list(self.scopes)))
        self.backend = ProductionBackend(db_manager=store.dbm, mongo_db=store.raw)
        self.mcp = srv.build_mcp(self.backend)

    async def call(self, tool: str, **arguments: Any) -> dict:
        from mcp.shared.memory import create_connected_server_and_client_session

        async with create_connected_server_and_client_session(self.mcp._mcp_server) as session:
            result = await session.call_tool(tool, arguments)
        text = result.content[0].text
        if result.isError:
            return {"tool_error": text}
        return json.loads(text)

    async def tools(self) -> dict:
        from mcp.shared.memory import create_connected_server_and_client_session

        async with create_connected_server_and_client_session(self.mcp._mcp_server) as session:
            return {tool.name: tool for tool in (await session.list_tools()).tools}

    def stored(self, note_id: str) -> str:
        return self.store.raw["sticky_notes"].find_one({"_id": ObjectId(note_id)})["content"]

    def versions(self, note_id: str) -> list[str]:
        """הגופים שבהיסטוריה של הפתק, לפי הסדר שנשמרו."""
        docs = self.store.raw["sticky_note_versions"].find({"note_id": note_id})
        return [d["content"] for d in sorted(docs, key=lambda d: d["version"])]

    async def note(self, content: str) -> tuple[str, str]:
        """פתק חדש על לוח ברירת המחדל — ``(id, content_sha256)`` כפי שהתצוגה מקבלת אותם."""
        boards = await self.call("codekeeper_list_boards")
        created = await self.call("codekeeper_create_board_note", board_id=boards["boards"][0]["id"], content=content)
        assert created.get("ok") is True, created
        shown = await self.call("codekeeper_show_note", note_id=created["note"]["id"])
        return created["note"]["id"], shown["note"]["content_sha256"]


@pytest.fixture
def server(monkeypatch, store):
    return _Server(monkeypatch, store)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# == החוזה של MCP Apps ===========================================================


async def test_the_tool_is_hidden_from_the_agent_and_points_at_the_note_view(server):
    """``visibility: ["app"]`` — Claude מסתיר את הכלי מהמודל ומעביר אליו רק קריאות מהדף — והקישור
    לאותו דף של ``codekeeper_show_note``, בשני המפתחות, כמו ש-``registerAppTool`` של ext-apps כותב."""
    tools = await server.tools()
    save, show = tools[TOOL], tools["codekeeper_show_note"]

    assert save.meta["ui"]["visibility"] == ["app"]
    assert save.meta["ui"]["resourceUri"] == show.meta["ui"]["resourceUri"] == save.meta["ui/resourceUri"]
    assert "visibility" not in show.meta["ui"]  # התצוגה עצמה נשארת של המודל
    assert save.annotations.readOnlyHint is False and save.annotations.idempotentHint is False


async def test_editable_follows_the_write_permission_of_the_connection(server):
    note_id, _sha256 = await server.note("גוף")
    assert (await server.call("codekeeper_show_note", note_id=note_id))["editable"] is True
    server.scopes = ["read"]
    assert (await server.call("codekeeper_show_note", note_id=note_id))["editable"] is False


# == השמירה ======================================================================


async def test_a_save_on_the_hash_the_view_received_writes_the_body_as_sent_and_keeps_the_old_one(server):
    """הגוף נשמר כמו שנשלח (בלי ניקוי, כמו כל כלי פתק), הגוף הקודם נשמר כגרסה, והתשובה נבנית ממה
    שנשמר — עם ה-hash שהשמירה הבאה מהתצוגה נבנית עליו."""
    note_id, sha256 = await server.note("לפני")
    sent = "אחרי\r\nעם &amp; ישות ורווח בסוף  "

    res = await server.call(TOOL, note_id=note_id, content=sent, expected_content_sha256=sha256)

    assert res.get("ok") is True and res["content_changed"] is False, res
    assert server.stored(note_id) == sent
    assert res["note"]["content"] == sent and res["note"]["content_sha256"] == _sha(sent)
    assert server.versions(note_id) == ["לפני"]
    listed = await server.call("codekeeper_list_note_versions", note_id=note_id)
    assert [v["length"] for v in listed["versions"]] == [len("לפני")]


async def test_the_hash_from_the_answer_carries_the_next_save_and_the_old_one_is_a_conflict(server):
    """שמירה שנייה נבנית על ה-hash שהתשובה הראשונה החזירה. שליחה חוזרת עם ה-hash הישן היא
    ``conflict`` — ולכן הכלי אינו אידמפוטנטי (``_REPLACE_IN_PLACE_TOOL``)."""
    note_id, sha256 = await server.note("אחת")
    first = await server.call(TOOL, note_id=note_id, content="שתיים", expected_content_sha256=sha256)

    again = await server.call(TOOL, note_id=note_id, content="שתיים", expected_content_sha256=sha256)
    second = await server.call(TOOL, note_id=note_id, content="שלוש",
                               expected_content_sha256=first["note"]["content_sha256"])

    assert again["error"] == "conflict"
    assert second.get("ok") is True and server.stored(note_id) == "שלוש"
    assert server.versions(note_id) == ["אחת", "שתיים"]


async def test_saving_the_same_body_writes_nothing_and_adds_no_version(server):
    """גוף זהה לשמור אינו עריכה (``drop_unchanged_edits``): אין כתיבה, אין גרסה שדוחפת ישנה החוצה."""
    note_id, sha256 = await server.note("כמו שהוא")
    res = await server.call(TOOL, note_id=note_id, content="כמו שהוא", expected_content_sha256=sha256)
    assert res.get("ok") is True and res["note"]["content_sha256"] == sha256
    assert server.versions(note_id) == []


async def test_an_empty_note_can_be_filled_from_the_view(server):
    """פתק ריק — הוובאפ שומר גוף ריק — מקבל hash כמו כל גוף, והתצוגה יכולה למלא אותו."""
    note_id, _sha256 = await server.note("זמני")
    server.store.raw["sticky_notes"].update_one({"_id": ObjectId(note_id)}, {"$set": {"content": ""}})
    shown = await server.call("codekeeper_show_note", note_id=note_id)
    assert shown["note"]["content_sha256"] == _sha("")

    res = await server.call(TOOL, note_id=note_id, content="מלא", expected_content_sha256=_sha(""))

    assert res.get("ok") is True and server.stored(note_id) == "מלא"


# == התנגשות ======================================================================


async def test_a_stale_hash_is_a_conflict_and_nothing_is_written(server):
    """הפתק השתנה מאז שהתצוגה קיבלה אותו — סוכן, או הוובאפ. השמירה אינה דורסת את השינוי."""
    note_id, stale = await server.note("לפני")
    assert (await server.call("codekeeper_update_note", note_id=note_id, content="שלהם")).get("ok") is True
    versions_before = server.versions(note_id)

    res = await server.call(TOOL, note_id=note_id, content="שלי", expected_content_sha256=stale)

    assert res["ok"] is False and res["error"] == "conflict" and res["hint"], res
    assert server.stored(note_id) == "שלהם"
    assert server.versions(note_id) == versions_before


async def test_a_change_between_the_read_and_the_write_is_a_conflict(server, monkeypatch):
    """**הדריסה מותנית בגוף שנקרא.** כתיבה מקבילה שנוחתת בין הקריאה של הכלי לכתיבה שלו — ה-hash
    עבר, והגוף כבר אחר — מפסידה את הכתיבה ולא נדרסת. בלי ``expected_content`` הכתיבה הייתה מצליחה
    ומוחקת את מה שנכתב באמצע; והגרסה שנשמרה לפני הדריסה נמחקת, כי הדריסה לא קרתה."""
    note_id, sha256 = await server.note("לפני")
    real_update = server.backend.update_note

    def racing_update(user_id, *, note_id, fields, expected_content=None):
        server.store.raw["sticky_notes"].update_one({"_id": ObjectId(note_id)}, {"$set": {"content": "באמצע"}})
        return real_update(user_id, note_id=note_id, fields=fields, expected_content=expected_content)

    monkeypatch.setattr(server.backend, "update_note", racing_update)

    res = await server.call(TOOL, note_id=note_id, content="שלי", expected_content_sha256=sha256)

    assert res["ok"] is False and res["error"] == "conflict", res
    assert server.stored(note_id) == "באמצע"
    assert server.versions(note_id) == []


# == מה נכנס =====================================================================


@pytest.mark.parametrize("bad", ["", "xyz", "g" * 64, "a" * 63, "a" * 65])
async def test_a_hash_that_is_not_a_hash_is_refused_before_anything_is_read(server, bad):
    """קוד משלו ולא ``conflict``: שגיאת צורה הייתה נקראת אחרת כ"הפתק השתנה". ההפניה בתשובה היא
    לתצוגה, ולא ל-``codekeeper_get_file`` של כלי הקבצים."""
    note_id, _sha256 = await server.note("לפני")
    res = await server.call(TOOL, note_id=note_id, content="שלי", expected_content_sha256=bad)
    assert res == {"ok": False, "error": "invalid_expected_content_sha256", "hint": handlers._NOTE_SHA256_HINT}
    assert "codekeeper_show_note" in res["hint"]
    assert server.stored(note_id) == "לפני"


async def test_the_hash_is_required(server):
    """בלי hash השמירה הייתה דורסת עדכון שהגיע בזמן ההקלדה — ולכן הוא חובה, כבר בסכמה."""
    note_id, _sha256 = await server.note("לפני")
    res = await server.call(TOOL, note_id=note_id, content="שלי")
    assert "expected_content_sha256" in res["tool_error"]
    assert server.stored(note_id) == "לפני"
    # וגם ה-handler עצמו, למי שיקרא לו בלי הסכמה:
    assert handlers.save_note_from_view(server.backend, USER, note_id=note_id, content="שלי",
                                        expected_content_sha256=None, is_admin=False) == {
        "ok": False, "error": "invalid_expected_content_sha256", "hint": handlers._NOTE_SHA256_HINT}


@pytest.mark.parametrize("body,error", [
    ("", {"ok": False, "error": "empty_content"}),
    (" \n\t ", {"ok": False, "error": "empty_content"}),
    ("x" * (MAX_NOTE_CHARS + 1), {"ok": False, "error": "content_too_long", "max": MAX_NOTE_CHARS}),
])
async def test_the_body_goes_through_the_check_of_every_note_tool(server, body, error):
    """אותה ``_note_content_error`` של כל כלי שכותב פתק — ושום דבר לא נכתב."""
    note_id, sha256 = await server.note("לפני")
    assert await server.call(TOOL, note_id=note_id, content=body, expected_content_sha256=sha256) == error
    assert server.stored(note_id) == "לפני" and server.versions(note_id) == []


async def test_an_invalid_note_id_is_refused(server):
    assert await server.call(TOOL, note_id="xyz", content="שלי", expected_content_sha256=_sha("x")) == {
        "ok": False, "error": "invalid_note_id"}


# == השער ========================================================================


async def test_another_users_note_is_not_found_and_nothing_is_written(server):
    """IDOR: גם עם ה-hash הנכון — ``not_found``, אותה תשובה כמו למזהה שאינו קיים."""
    server.user = OTHER
    note_id, sha256 = await server.note("של אחר")
    server.user = USER

    res = await server.call(TOOL, note_id=note_id, content="שלי", expected_content_sha256=sha256)

    assert res == {"ok": False, "error": "not_found"}
    assert server.stored(note_id) == "של אחר" and server.versions(note_id) == []


async def test_saving_needs_write_permission(server):
    note_id, sha256 = await server.note("לפני")
    server.scopes = ["read"]
    res = await server.call(TOOL, note_id=note_id, content="שלי", expected_content_sha256=sha256)
    assert "insufficient_scope" in res["tool_error"]
    assert server.stored(note_id) == "לפני"


class _RepoNoteBackend:
    """פתק ריפו — ``get_note`` בצורה של ``ProductionBackend``. ``update_note`` רושם, כדי לראות שהשער
    עצר לפני כל כתיבה."""

    def __init__(self):
        self.writes = []
        self.content = "x"

    def get_note(self, user_id, *, note_id, with_version=False):
        return {"ok": True, "note": {"id": note_id, "content": self.content, "content_sha256": _sha(self.content),
                                     "repo_name": "CodeBot", "repo_path": "a.py"},
                "target": "repo", "repo_name": "CodeBot", "repo_path": "a.py"}

    def update_note(self, user_id, *, note_id, fields, expected_content=None):
        self.writes.append((note_id, fields, expected_content))
        return {"ok": True, "note": {"id": note_id, "content": fields["content"], "content_sha256": _sha(fields["content"])}}


def test_a_repo_note_is_for_the_admin_only_like_the_view():
    """אותו שער של ``codekeeper_show_note`` (``_readable_note``): פתק ריפו פתוח לאדמין בלבד, ורק
    ``True`` ממש פותח."""
    note_id = "6a8cfe7e35f97a799c443651"
    for not_admin in (False, None, 1, "yes"):
        backend = _RepoNoteBackend()
        assert handlers.save_note_from_view(backend, USER, note_id=note_id, content="y",
                                            expected_content_sha256=_sha("x"), is_admin=not_admin) == {
            "ok": False, "error": "not_found"}, not_admin
        assert backend.writes == []
    backend = _RepoNoteBackend()
    res = handlers.save_note_from_view(backend, USER, note_id=note_id, content="y",
                                       expected_content_sha256=_sha("x"), is_admin=True)
    assert res.get("ok") is True
    assert backend.writes == [(note_id, {"content": "y"}, "x")]
