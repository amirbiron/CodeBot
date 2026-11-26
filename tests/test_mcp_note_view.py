"""MCP App: ``codekeeper_show_note`` והדף ``ui://`` שהוא מצביע עליו (``mcp_server/note_view.py``).

**מה נבדק כאן, ודרך מה.** החוזה של MCP Apps עובר כולו דרך הפרוטוקול: ``_meta`` של הכלי ב-``tools/list``,
המשאב ב-``resources/list`` וב-``resources/read`` (עם ``mimeType`` ו-``_meta.ui`` על הפריט שבתשובה),
ותשובת הכלי. לכן הבדיקות המרכזיות רצות דרך session אמיתי של הפרוטוקול, על ``build_mcp`` של
הייצור **עם האינסטרומנטציה של PostHog דלוקה** — התצורה שהשרת רץ בה, שעוטפת את ``tools/list``
ואת קריאת הכלים. הכתובת שנקראת היא זו שהכלי מצהיר עליה, ולא מחרוזת שהטסט מקליד.

מה שכאן לא נבדק, ואיפה כן: הלוגיקה של הדף — ``tests/mcp-note-view.test.js``; הדף בדפדפן אמיתי,
תחת ה-CSP שהמפרט מחייב — ``tests/test_mcp_note_view_browser.py``.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import re
import shutil
from pathlib import Path

import pytest

pytest.importorskip("mcp")

from mcp.shared.exceptions import McpError  # noqa: E402
from mcp.shared.memory import create_connected_server_and_client_session  # noqa: E402

import mcp_server.server as srv  # noqa: E402
from mcp_server import analytics, answer_size, handlers, note_view  # noqa: E402
from sticky_notes_target import MAX_NOTE_CHARS, MAX_NOTE_TITLE  # noqa: E402

_REPO = Path(__file__).resolve().parent.parent
_USER = 7
_NOTE_ID = "6a8cfe7e35f97a799c443651"
_BOARD_ID = "b" * 24
_BODY_MARKER = "גוף-הפתק-שאסור-שיגיע-לאנליטיקה"


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


_BODY = "# " + _BODY_MARKER + "\nשורה שנייה"


class _NoteBackend:
    """backend שמחזיק פתק אחד ורושם כל קריאה. ``get_note`` ו-``update_note`` בצורה של ``ProductionBackend``
    כשהם נקראים מהתצוגה (``for_note_view=True``): הצבע ``hex`` בלבד, היעד מחוץ ל-``note``, והגוף בתשובת
    השמירה. ``for_note_view`` נרשם בצד (``views``), כך שצורת הרשומות שהטסטים משווים לא זזה."""

    def __init__(self, answer=None, orphaned=False):
        self.calls = []
        self.views = []
        self.orphaned = orphaned
        self.answer = answer if answer is not None else {
            "ok": True,
            "note": {
                "id": _NOTE_ID,
                "title": "רשימה",
                "content": _BODY,
                "color": "#ffeddb",
                "content_sha256": _sha(_BODY),
            },
            "target": "board",
            "board_id": _BOARD_ID,
        }

    def get_note(self, user_id, *, note_id, with_version=False, for_note_view=False):
        self.calls.append(("get_note", user_id, note_id, with_version))
        self.views.append(("get_note", for_note_view))
        return self.answer

    def update_note(self, user_id, *, note_id, fields, expected_content=None, for_note_view=False):
        self.calls.append(("update_note", user_id, note_id, expected_content))
        self.views.append(("update_note", for_note_view))
        body = fields["content"]
        return {"ok": True, "note": {**self.answer["note"], "content": body, "content_sha256": _sha(body)}}

    def repo_path_orphaned(self, *, repo_name, repo_path):
        self.calls.append(("repo_path_orphaned", repo_name, repo_path))
        return self.orphaned


def _repo_note_answer():
    return {
        "ok": True,
        "note": {"id": _NOTE_ID, "content": "x", "color": "#ffffcc"},
        "target": "repo",
        "repo_name": "CodeBot",
        "repo_path": "a.py",
    }


@pytest.fixture
def production_like_mcp(monkeypatch):
    """``build_mcp`` של הייצור, עם לקוח PostHog אמיתי (``send=False``) שמקליט מה היה נשלח."""
    from posthog import Posthog

    about_to_send = []

    def recording_gate(event):
        result = analytics.scrub_mcp_payload(event)
        if result is not None:
            about_to_send.append(result)
        return result

    client = Posthog("phc_test_token_not_real", host="https://us.i.posthog.com", send=False,
                     before_send=recording_gate, enable_exception_autocapture=False,
                     capture_exception_code_variables=False)
    monkeypatch.setattr(analytics, "_CLIENT", client)
    monkeypatch.setattr(analytics, "_ANALYTICS", None)
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setattr(srv, "current_user_id", lambda ctx=None: _USER)
    monkeypatch.setattr(srv, "is_admin_user", lambda user_id: False)
    backend = _NoteBackend()
    mcp = srv.build_mcp(backend, rate_limit_per_minute=0)
    try:
        yield mcp, backend, about_to_send
    finally:
        client.shutdown()


# ===========================================================================
# החוזה של MCP Apps, דרך הפרוטוקול
# ===========================================================================


async def test_the_tool_points_at_a_resource_the_server_serves_as_an_mcp_app(production_like_mcp):
    """הכלי מצהיר על ``ui://``, והכתובת הזו — כפי שהלקוח קרא אותה — נענית בדף, ב-MIME וב-``_meta`` של המפרט.

    שלושה דברים שהמארח נשען עליהם (``specification/2026-01-26/apps.mdx``): ``_meta.ui.resourceUri``
    על הכלי, ``mimeType: text/html;profile=mcp-app`` על התוכן, ו-``_meta.ui`` על הפריט שבתשובה של
    ``resources/read`` — שם, ולא ברשימה, Claude קורא אותו. ושני המפתחות של הכלי — גם השטוח הישן,
    כמו ``registerAppTool`` של ה-SDK.
    """
    mcp, _backend, _sent = production_like_mcp
    expected = note_view.build_note_view()
    async with create_connected_server_and_client_session(mcp._mcp_server) as session:
        tool = next(t for t in (await session.list_tools()).tools if t.name == "codekeeper_show_note")
        uri = tool.meta["ui"]["resourceUri"]
        assert tool.meta == {"ui": {"resourceUri": uri}, "ui/resourceUri": uri,
                             **answer_size.declared_size_meta()}
        assert uri == expected.uri and uri.startswith("ui://")
        assert tool.annotations.readOnlyHint is True

        listed = {str(r.uri): r for r in (await session.list_resources()).resources}
        assert listed[uri].mimeType == "text/html;profile=mcp-app"

        read = (await session.read_resource(uri)).contents
        assert len(read) == 1
        assert read[0].mimeType == "text/html;profile=mcp-app"
        assert read[0].meta == {"ui": {"prefersBorder": False}}
        assert read[0].text == expected.html


async def test_every_published_version_stays_readable_and_nothing_else_is(production_like_mcp):
    """כתובת של גרסה קודמת נענית בדף הנוכחי; כתובת שאינה גרסה — שגיאה.

    שיחה ישנה שטוענת מחדש את התצוגה שלה מבקשת את הכתובת שנרשמה אז. בלי התבנית, כל דיפלוי
    שמשנה את הדף היה שובר אותה. מוטציה שמפילה: רישום המשאב הקונקרטי בלבד, בלי התבנית.
    """
    mcp, _backend, _sent = production_like_mcp
    current = note_view.build_note_view()
    old_uri = "ui://codekeeper/note-view/" + "0" * note_view.VERSION_HEX_CHARS + ".html"
    assert old_uri != current.uri
    async with create_connected_server_and_client_session(mcp._mcp_server) as session:
        old = (await session.read_resource(old_uri)).contents[0]
        assert old.text == current.html
        assert old.mimeType == "text/html;profile=mcp-app"
        assert old.meta == {"ui": {"prefersBorder": False}}
        templates = (await session.list_resource_templates()).resourceTemplates
        assert [t.uriTemplate for t in templates] == [note_view.URI_TEMPLATE]
        for bad in ("not-a-version", "0" * (note_view.VERSION_HEX_CHARS - 1),
                    "0" * (note_view.VERSION_HEX_CHARS + 1), "A" * note_view.VERSION_HEX_CHARS):
            with pytest.raises(McpError):
                await session.read_resource(f"ui://codekeeper/note-view/{bad}.html")


async def test_the_tool_answers_with_the_full_note_as_text(production_like_mcp):
    """לקוח שאינו מציג תצוגה — והמודל — מקבלים את הפתק המלא כטקסט. המפרט: "Tools MUST return
    meaningful content array even when UI is available"."""
    mcp, backend, _sent = production_like_mcp
    async with create_connected_server_and_client_session(mcp._mcp_server) as session:
        result = await session.call_tool(
            "codekeeper_show_note", {"note_id": _NOTE_ID}
        )
    answer = json.loads(result.content[0].text)
    # ``editable`` — ה-session בזיכרון אינו נושא טוקן, ולכן אין הרשאת כתיבה.
    assert answer == {"ok": True, **backend.answer, "editable": False}
    assert result.structuredContent is None
    assert backend.calls == [("get_note", _USER, _NOTE_ID, False)]


async def test_layout_debug_is_off_by_default_and_reaches_the_view_only_when_asked(production_like_mcp):
    """**מצב מדידה** — ``layout_debug``: בוליאני בסכמה, כבוי כברירת מחדל, עם תיאור שנפתח ב"מתי".
    כשהוא מבוקש, התשובה נושאת ``layout_debug: true`` — וזה כל השינוי בה. בלעדיו התשובה זהה לתשובה
    הרגילה, בלי המפתח בכלל."""
    mcp, backend, _sent = production_like_mcp
    async with create_connected_server_and_client_session(mcp._mcp_server) as session:
        tool = next(t for t in (await session.list_tools()).tools if t.name == "codekeeper_show_note")
        asked = await session.call_tool("codekeeper_show_note", {"note_id": _NOTE_ID, "layout_debug": True})
        plain = await session.call_tool("codekeeper_show_note", {"note_id": _NOTE_ID})
    schema = tool.inputSchema["properties"]["layout_debug"]
    assert schema["type"] == "boolean" and schema["default"] is False, schema
    assert schema["description"].startswith("Only when the user asks"), schema
    assert "layout_debug" not in tool.inputSchema.get("required", []), tool.inputSchema
    assert json.loads(asked.content[0].text) == {"ok": True, **backend.answer, "editable": False, "layout_debug": True}
    assert json.loads(plain.content[0].text) == {"ok": True, **backend.answer, "editable": False}


def test_layout_debug_enters_the_answer_only_as_true():
    """רק ``True`` ממש מוסיף את המפתח — כמו ``editable`` (K12 §3)."""
    for value, expected in ((True, True), (False, None), (None, None), (1, None), ("yes", None)):
        shown = handlers.show_note(_NoteBackend(), _USER, note_id=_NOTE_ID, is_admin=False, can_write=False, layout_debug=value)
        assert shown.get("layout_debug") is expected, value


# ===========================================================================
# סימון קטע — ``section`` / ``query`` של ``codekeeper_show_note``
# ===========================================================================

#: פתק עם כותרות בשלוש רמות. השורות ממוספרות מ-1, כמו ``line_range`` של ``codekeeper_get_file``.
_SECTIONED = "\n".join([
    "# מדריך",        # 1
    "פתיחה",          # 2
    "## התקנה",       # 3
    "שלב ראשון",      # 4
    "### פרטים",      # 5
    "פרט פנימי",      # 6
    "## שימוש",       # 7
    "הפעלה של Tool",  # 8
])


def _show(body, **params):
    backend = _NoteBackend()
    backend.answer = {**backend.answer, "note": {**backend.answer["note"], "content": body, "content_sha256": _sha(body)}}
    return backend, handlers.show_note(backend, _USER, note_id=_NOTE_ID, is_admin=False, can_write=False, **params)


def test_a_section_that_is_found_marks_it_down_to_the_next_heading_of_its_level():
    """``section`` שנמצא: הקטע מהכותרת ועד לפני הכותרת הבאה מאותה רמה או גבוהה ממנה — כולל תת-הקטע
    שבתוכו — ושם הכותרת. הפתק עצמו בתשובה כמו תמיד."""
    _, shown = _show(_SECTIONED, section="התקנה")
    assert shown["ok"] is True and shown["note"]["content"] == _SECTIONED, shown
    assert shown["highlight"] == {"kind": "section", "title": "התקנה", "line_range": [3, 6]}, shown


def test_a_section_answers_from_the_same_function_as_get_file():
    """**אותה התאמה כמו ``codekeeper_get_file``** — ``docs_handlers.answer_section`` על אותו טקסט נותן
    את אותו ``line_range``. ההשוואה היא מול הפונקציה עצמה, ולא מול מספרים שהבדיקה מחשבת."""
    from mcp_server import docs_handlers
    from services import md_parser

    context = {"note_id": _NOTE_ID}
    for heading in ("מדריך", "התקנה", "פרטים", "שימוש"):
        direct = docs_handlers.answer_section(
            docs_handlers.LoadedDocument(docs_handlers.parse_with_refusals(md_parser, _SECTIONED, context), context),
            section=heading)
        _, shown = _show(_SECTIONED, section=heading)
        assert shown["highlight"]["line_range"] == direct["line_range"], (heading, shown, direct)


def test_a_section_that_is_not_found_is_refused_with_suggestions_and_no_note():
    """כותרת שלא נמצאה — ``section_not_found`` עם הצעות, כמו ב-``get_file``, **ובלי הפתק**: כרטיס בלי סימון
    היה נראה לסוכן כמו סימון שעבד."""
    _, shown = _show(_SECTIONED, section="התקנת")
    assert shown["ok"] is False and shown["error"] == "section_not_found", shown
    assert "התקנה" in json.dumps(shown, ensure_ascii=False), shown
    assert "note" not in shown and "highlight" not in shown, shown


def test_a_heading_that_appears_twice_is_ambiguous_with_candidates():
    """כותרת שמופיעה פעמיים — ``ambiguous_section`` עם המועמדים, מאותה פונקציה."""
    body = "## שלבים\nא\n## שלבים\nב"
    _, shown = _show(body, section="שלבים")
    assert shown["ok"] is False and shown["error"] == "ambiguous_section", shown
    assert len(shown["candidates"]) == 2 and "note" not in shown, shown


def test_a_query_marks_its_text_and_one_that_is_missing_is_no_match():
    """``query`` שנמצא — ``highlight`` מסוג query (בלי רגישות לרישיות, כמו ``get_file``); ``query`` שלא
    נמצא — ``no_match``, ולא תשובה ריקה כמו ב-``get_file``, ובלי הפתק."""
    _, shown = _show(_SECTIONED, query="tool")
    assert shown["ok"] is True and shown["highlight"] == {"kind": "query", "query": "tool"}, shown
    _, missing = _show(_SECTIONED, query="לא קיים בפתק")
    assert missing["ok"] is False and missing["error"] == "no_match" and "note" not in missing, missing


def test_section_and_query_together_are_refused_before_the_note_is_read():
    """שני הפרמטרים יחד — ``section_and_query``, כמו ב-``get_file``, **לפני** קריאת הפתק. וגם ערך ריק
    נדחה באותן פונקציות של ``get_file`` (``file_section_error`` / ``file_query_error``)."""
    backend, shown = _show(_SECTIONED, section="התקנה", query="שלב")
    assert shown == handlers.file_read_refusal(handlers.SECTION_AND_QUERY) and backend.calls == [], (shown, backend.calls)
    backend, empty_section = _show(_SECTIONED, section="  ")
    assert empty_section == handlers.file_read_refusal(handlers.file_section_error("  ")) and backend.calls == [], empty_section
    backend, multiline = _show(_SECTIONED, query="שלב\nראשון")
    assert multiline == handlers.file_read_refusal(handlers.file_query_error("שלב\nראשון")) and backend.calls == [], multiline


def test_a_note_without_headings_takes_query_and_refuses_section():
    """פתק בלי כותרות: ``query`` עובד, ו-``section`` — ``section_not_found``."""
    body = "רק טקסט\nבלי כותרות בכלל"
    _, by_query = _show(body, query="כותרות")
    assert by_query["ok"] is True and by_query["highlight"]["kind"] == "query", by_query
    _, by_section = _show(body, section="טקסט")
    assert by_section["ok"] is False and by_section["error"] == "section_not_found", by_section


def test_an_archived_note_is_marked_like_any_other():
    """פתק בארכיון עובר באותו שער (``get_note`` מחזיר אותו), והסימון עליו זהה."""
    backend = _NoteBackend()
    backend.answer = {"ok": True, "target": "archive", "note": {
        **backend.answer["note"], "content": _SECTIONED, "content_sha256": _sha(_SECTIONED),
        "archived_at": "2026-11-01T00:00:00+00:00"}}
    shown = handlers.show_note(backend, _USER, note_id=_NOTE_ID, is_admin=False, can_write=False, section="שימוש")
    assert shown["ok"] is True and shown["highlight"]["line_range"] == [7, 8], shown


async def test_section_and_query_reach_the_tool_schema_with_when_to_use_descriptions(production_like_mcp):
    """דרך הפרוטוקול: שני הפרמטרים אופציונליים (``null``), והתיאור של כל אחד נפתח ב"מתי להשתמש"."""
    mcp, _, _ = production_like_mcp
    async with create_connected_server_and_client_session(mcp._mcp_server) as session:
        tools = {t.name: t for t in (await session.list_tools()).tools}
    props = tools["codekeeper_show_note"].inputSchema["properties"]
    for name in ("section", "query"):
        assert props[name].get("default") is None and props[name]["description"].startswith("When you are explaining"), props[name]
        assert name not in tools["codekeeper_show_note"].inputSchema.get("required", []), name


async def test_the_largest_possible_note_fits_the_declared_ceiling_whole(production_like_mcp):
    """הכלי מצהיר על תקרת התשובה (כמו ``codekeeper_get_note``), ועומד בה בלי חיתוך גם במקרה הגרוע.

    כל שדה שחסום בכותבים — בתקרה שלו, ובתו בקרה, שהוא הכי יקר כ-JSON (``\\u0001``, שישה בתים
    לתו): הגוף ב-``MAX_NOTE_CHARS``, הכותרת ב-``MAX_NOTE_TITLE``, ו-``anchor_text`` ב-256 (החיתוך
    ב-``webapp/sticky_notes_api.py``). התשובה עוברת את הרשת של ``AdminAwareFastMCP.call_tool``
    בלי ``answer_too_large``, והפתק חוזר שלם.
    """
    mcp, backend, _sent = production_like_mcp
    heavy = "\x01"
    backend.answer = {
        "ok": True,
        "note": {"id": _NOTE_ID, "title": heavy * MAX_NOTE_TITLE, "content": heavy * MAX_NOTE_CHARS,
                 "anchor_text": heavy * 256, "color": "#ffffcc"},
        "target": "board",
        "board_id": _BOARD_ID,
    }
    async with create_connected_server_and_client_session(mcp._mcp_server) as session:
        result = await session.call_tool("codekeeper_show_note", {"note_id": _NOTE_ID})
    sent = len(result.content[0].text.encode("utf-8"))
    answer = json.loads(result.content[0].text)
    assert answer["ok"] is True, answer.get("error")
    assert answer["note"]["content"] == heavy * MAX_NOTE_CHARS
    assert sent < answer_size.OUTPUT_BYTE_BUDGET


async def test_through_the_tool_a_repo_note_is_still_hidden_from_a_non_admin(production_like_mcp):
    """השער נבדק גם בכלי עצמו, לא רק ב-handler: הכלי חייב להעביר את ``is_admin`` של הקורא.

    מוטציה שמפילה: ``is_admin=True`` קבוע ברישום הכלי — הבדיקות של ה-handler היו נשארות ירוקות.
    """
    mcp, backend, _sent = production_like_mcp
    backend.answer = _repo_note_answer()
    async with create_connected_server_and_client_session(mcp._mcp_server) as session:
        result = await session.call_tool(
            "codekeeper_show_note", {"note_id": _NOTE_ID}
        )
    assert json.loads(result.content[0].text) == {"ok": False, "error": "not_found"}


async def test_neither_the_note_nor_the_page_reaches_posthog(production_like_mcp):
    """הגוף של הפתק והדף עצמו אינם בשום אירוע שהיה נשלח — דרך החיווט של הייצור.

    הכלי החדש עובר באותו שער של כל כלי (``$mcp_parameters`` ו-``$mcp_response`` חסומים). קריאת
    המשאב: ``posthog.mcp`` (7.45.3) אינו עוטף את ``resources/read`` בשרת FastMCP 1.x — כך נקרא
    בקוד שלו, ולכן הטסט אינו מניח את זה אלא בודק שאף אירוע אינו נושא את ה-HTML.
    """
    mcp, _backend, about_to_send = production_like_mcp
    view = note_view.build_note_view()
    async with create_connected_server_and_client_session(mcp._mcp_server) as session:
        await session.call_tool("codekeeper_show_note", {"note_id": _NOTE_ID})
        await session.read_resource(view.uri)
    await analytics._drain()

    calls = [e for e in about_to_send if e.get("event") == "$mcp_tool_call"]
    assert calls, "האינסטרומנטציה לא הקליטה כלום — החיווט שבור, והטסט היה עובר בלי לבדוק"
    properties = calls[0]["properties"]
    assert properties["$mcp_tool_name"] == "codekeeper_show_note"
    assert "$mcp_parameters" not in properties and "$mcp_response" not in properties
    wire = json.dumps(about_to_send, ensure_ascii=False, default=str)
    assert _BODY_MARKER not in wire
    assert _NOTE_ID not in wire
    assert "ck-note-root" not in wire


async def test_the_body_of_a_save_from_the_view_never_reaches_posthog(production_like_mcp, monkeypatch):
    """השמירה מהתצוגה נושאת את כל גוף הפתק כארגומנט — והוא אינו בשום אירוע שהיה נשלח, גם לא
    בתשובה (שמחזירה את הפתק השמור). דרך החיווט של הייצור, כמו הטסט שלמעלה."""
    import mcp.server.auth.middleware.auth_context as auth_context
    from types import SimpleNamespace

    mcp, backend, about_to_send = production_like_mcp
    monkeypatch.setattr(auth_context, "get_access_token", lambda: SimpleNamespace(scopes=["read", "write"]))
    sent_body = "נשמר-מהתצוגה " + _BODY_MARKER
    async with create_connected_server_and_client_session(mcp._mcp_server) as session:
        result = await session.call_tool("codekeeper_note_view_save", {
            "note_id": _NOTE_ID, "content": sent_body, "expected_content_sha256": _sha(_BODY)})
    await analytics._drain()

    assert json.loads(result.content[0].text)["ok"] is True
    assert ("update_note", _USER, _NOTE_ID, _BODY) in backend.calls
    calls = [e for e in about_to_send if e.get("event") == "$mcp_tool_call"]
    assert [c["properties"]["$mcp_tool_name"] for c in calls] == ["codekeeper_note_view_save"]
    assert "$mcp_parameters" not in calls[0]["properties"] and "$mcp_response" not in calls[0]["properties"]
    wire = json.dumps(about_to_send, ensure_ascii=False, default=str)
    assert _BODY_MARKER not in wire and "נשמר-מהתצוגה" not in wire


# ===========================================================================
# השער — אותו של codekeeper_get_note
# ===========================================================================


def test_an_invalid_note_id_never_reaches_the_backend():
    backend = _NoteBackend()
    for bad in ("", "xyz", "a" * 25, None, 5):
        assert handlers.show_note(backend, _USER, note_id=bad, is_admin=True, can_write=True) == {
            "ok": False, "error": "invalid_note_id"}
    assert backend.calls == []


def test_a_refusal_from_the_backend_comes_back_as_it_is():
    backend = _NoteBackend(answer={"ok": False, "error": "not_found"})
    assert handlers.show_note(backend, _USER, note_id=_NOTE_ID, is_admin=True, can_write=True) == {
        "ok": False, "error": "not_found"}


def test_a_repo_note_is_for_the_admin_only_like_get_note():
    """פתק ריפו למי שאינו אדמין — ``not_found``, אותה תשובה כמו לפתק שאינו קיים. רק ``True`` ממש פותח."""
    for not_admin in (False, None, 1, "yes"):
        backend = _NoteBackend(answer=_repo_note_answer())
        assert handlers.show_note(backend, _USER, note_id=_NOTE_ID, is_admin=not_admin, can_write=True) == {
            "ok": False, "error": "not_found"}, not_admin
    admin = handlers.show_note(_NoteBackend(answer=_repo_note_answer(), orphaned=True), _USER,
                               note_id=_NOTE_ID, is_admin=True, can_write=True)
    assert admin["ok"] is True and admin["orphaned"] is True
    assert (admin["target"], admin["repo_name"], admin["repo_path"]) == ("repo", "CodeBot", "a.py")


def test_show_note_is_get_note_without_threads_and_version(monkeypatch):
    """אותה צורה של ``get_note(part="all")`` — חוץ מהשרשורים ומ-``version``, שהכלי הזה אינו מבקש,
    ועוד ``editable``, שאינו בפתק אלא בחיבור.

    נבנה מאותו backend בשני המסלולים, ולכן שדה שיתווסף לפתק או ליעד יגיע לשניהם. ``_with_threads``
    מוחלף כאן בזהות, כי השרשורים אינם חלק ממה שנבדק.
    """
    monkeypatch.setattr(handlers, "_with_threads", lambda backend, user_id, out, **kw: out)
    answer = {**_NoteBackend().answer, "version": 3}
    via_get = handlers.get_note(_NoteBackend(answer=answer), _USER, note_id=_NOTE_ID, is_admin=False)
    shown_backend = _NoteBackend(answer={k: v for k, v in answer.items() if k != "version"})
    shown = handlers.show_note(shown_backend, _USER, note_id=_NOTE_ID, is_admin=False, can_write=True)
    assert {k: v for k, v in shown.items() if k != "editable"} == {k: v for k, v in via_get.items() if k != "version"}
    assert shown_backend.calls == [("get_note", _USER, _NOTE_ID, False)]


def test_editable_is_the_write_scope_of_the_connection_and_only_true_opens_it():
    """``editable`` — האם החיבור יכול לשמור. רק ``True`` ממש פותח, כמו ``is_admin`` (K12 §3):
    ערך אחר שהגיע בטעות אינו מציג כפתור שכל לחיצה עליו נדחית."""
    for can_write, expected in ((True, True), (False, False), (None, False), (1, False), ("yes", False)):
        shown = handlers.show_note(_NoteBackend(), _USER, note_id=_NOTE_ID, is_admin=False, can_write=can_write)
        assert shown["ok"] is True and shown["editable"] is expected, can_write


# ===========================================================================
# בניית הדף
# ===========================================================================


def _copy_assets(tmp_path: Path) -> tuple[Path, Path]:
    """עותק של כל מה שהדף נבנה ממנו: הקבצים של התצוגה, והחלקים של הוובאפ (בלבד) באותו מבנה."""
    apps = tmp_path / "apps"
    shutil.copytree(_REPO / "mcp_server" / "apps", apps)
    webapp = tmp_path / "static"
    for root, rel in note_view.STYLE_PARTS + note_view.SCRIPT_PARTS:
        if root == "webapp":
            (webapp / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(_REPO / "webapp" / "static" / rel, webapp / rel)
    return apps, webapp


def _part_path(apps: Path, webapp: Path, root: str, rel: str) -> Path:
    return (apps if root == "apps" else webapp) / rel


#: כל קובץ שהדף נבנה ממנו: השלד, וכל חלק של הסגנון ושל הסקריפט.
_ALL_PARTS = [("apps", "note_view.html")] + list(note_view.STYLE_PARTS) + list(note_view.SCRIPT_PARTS)


def test_the_version_is_the_hash_of_the_page_as_sent():
    view = note_view.build_note_view()
    assert view.version == hashlib.sha256(view.html.encode("utf-8")).hexdigest()[:note_view.VERSION_HEX_CHARS]
    assert view.uri == f"ui://codekeeper/note-view/{view.version}.html"
    assert note_view.STYLE_SLOT not in view.html and note_view.SCRIPT_SLOT not in view.html
    assert "ck-note-root" in view.html


@pytest.mark.parametrize("root,rel", _ALL_PARTS)
def test_any_change_to_any_part_changes_the_address(tmp_path, root, rel):
    """הכתובת משתנה עם כל קובץ שהדף נבנה ממנו — גם המנוע והעיצוב שהוובאפ משתף — אחרת מארח שמחזיק
    את הדף בקאש לפי כתובת היה מגיש את הישן (``stale-asset-cache-policy``)."""
    apps, webapp = _copy_assets(tmp_path)
    before = note_view.build_note_view(apps, webapp)
    path = _part_path(apps, webapp, root, rel)
    text = path.read_text(encoding="utf-8")
    marker = "<!-- changed -->" if rel.endswith(".html") else "/* changed */"
    path.write_text(text + "\n" + marker + "\n", encoding="utf-8")
    after = note_view.build_note_view(apps, webapp)
    assert after.version != before.version


@pytest.mark.parametrize("name,slot,body", [
    ("note_view.html", note_view.STYLE_SLOT, None),
    ("note_view.html", note_view.SCRIPT_SLOT, None),
])
def test_a_shell_without_exactly_one_slot_stops_the_server(tmp_path, name, slot, body):
    apps, webapp = _copy_assets(tmp_path)
    shell = (apps / name).read_text(encoding="utf-8")
    (apps / name).write_text(shell.replace(slot, ""), encoding="utf-8")
    with pytest.raises(RuntimeError, match="exactly once"):
        note_view.build_note_view(apps, webapp)
    (apps / name).write_text(shell.replace(slot, slot + slot), encoding="utf-8")
    with pytest.raises(RuntimeError, match="exactly once"):
        note_view.build_note_view(apps, webapp)


@pytest.mark.parametrize("root,rel,closing",
    [(r, p, "</STYLE>") for r, p in note_view.STYLE_PARTS] + [(r, p, "</ScRiPt>") for r, p in note_view.SCRIPT_PARTS])
def test_code_that_would_close_its_own_block_stops_the_server(tmp_path, root, rel, closing):
    """``</script`` בתוך הסקריפט סוגר את הבלוק בדפדפן, בכל רישיות — ושאר הקוד היה מוצג כטקסט. כל
    חלק נבדק, גם אלה של הוובאפ, והשגיאה נוקבת בקובץ."""
    apps, webapp = _copy_assets(tmp_path)
    path = _part_path(apps, webapp, root, rel)
    path.write_text(path.read_text(encoding="utf-8") + f"\n/* {closing} */\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match=re.escape(rel) + ".*would end the inline block"):
        note_view.build_note_view(apps, webapp)


def _board_load_order(suffix: str) -> list[str]:
    """הנכסים של הוובאפ בסיומת ``suffix``, בסדר שבו הם מגיעים לדפדפן בלוח הפתקים.

    ``note_board.html`` יורש מ-``base.html`` (דרך ``base_boards.html``), ולכן הסדר בעמוד הוא הסדר
    של התבנית הבסיסית, כשבמקום כל ``{% block X %}`` נכנס התוכן של הבלוק בלוח. זה מה שהפונקציה
    עושה — בלי מנוע תבניות, רק לפי מיקום בטקסט, ורק לבלוקים שהלוח ממלא.
    """
    base = (_REPO / "webapp" / "templates" / "base.html").read_text(encoding="utf-8")
    board = (_REPO / "webapp" / "templates" / "note_board.html").read_text(encoding="utf-8")
    assert '{% extends "base_boards.html" %}' in board
    assert '{% extends "base.html" %}' in (_REPO / "webapp" / "templates" / "base_boards.html").read_text(encoding="utf-8")
    pattern = re.compile(r"filename='([^']+" + re.escape(suffix) + r")'")
    blocks = dict(re.findall(r"{% block (\w+) %}(.*?){% endblock %}", board, flags=re.S))
    order: list[str] = []
    for piece in re.split(r"({% block \w+ %}{% endblock %})", base):
        name = re.fullmatch(r"{% block (\w+) %}{% endblock %}", piece)
        order += pattern.findall(blocks.get(name.group(1), "") if name else piece)
    return order


def test_the_page_holds_every_part_in_the_order_the_board_loads_them():
    """הדף כולל את המנוע והעיצוב של הוובאפ כמו שהם, ובסדר שבו לוח הפתקים טוען אותם.

    ``note_view.css`` ו-``note_view.js`` אחרונים: התצוגה מוסיפה על העיצוב המשותף ולא להפך, והסקריפט
    שלה קורא למנוע. הסדר של החלקים מהוובאפ נגזר מהתבניות (ההסבר ליד ``STYLE_PARTS``), כדי שתבנית
    שתשנה אותו תפיל כאן ולא תיפרד מהתצוגה בשקט.
    """
    view = note_view.build_note_view()
    for kind, parts in (("style", note_view.STYLE_PARTS), ("script", note_view.SCRIPT_PARTS)):
        positions = [view.html.index(f"/* ---- {rel} ---- */") for _root, rel in parts]
        assert positions == sorted(positions), kind
        assert parts[-1][0] == "apps" and all(root == "webapp" for root, _rel in parts[:-1]), kind
        for root, rel in parts:
            text = (_REPO / ("mcp_server/apps" if root == "apps" else "webapp/static") / rel).read_text(encoding="utf-8")
            assert text in view.html, rel
    for suffix, parts in ((".css", note_view.STYLE_PARTS), (".js", note_view.SCRIPT_PARTS)):
        ours = [rel for root, rel in parts if root == "webapp"]
        board = _board_load_order(suffix)
        assert set(ours) <= set(board), (ours, board)
        assert [rel for rel in board if rel in ours] == ours, board


def test_importing_the_module_reads_no_file(monkeypatch):
    """הדף נבנה ב-``build_mcp``, לא בייבוא (``import-time-side-effects``): ייבוא שקורא קובץ היה רץ
    גם באיסוף טסטים ובכל סקריפט שנוגע במודול."""
    def refuse(*_a, **_k):
        raise AssertionError("read a file at import time")

    monkeypatch.setattr(Path, "read_text", refuse)
    importlib.reload(note_view)


# ===========================================================================
# הערכים שהדף מעתיק מהפתק בוובאפ — מושווים, לא נזכרים
# ===========================================================================


def _css_block(css: str, selector: str) -> str:
    """הבלוק הראשון של כלל ש**מתחיל** ב-``selector`` — בתחילת שורה, כדי ש-``.sticky-note-content``
    לא יימצא בתוך ``.sticky-note.is-minimized .sticky-note-content``, שמופיע לפניו בקובץ."""
    match = re.search(r"(?m)^" + re.escape(selector) + r"\s*\{(?P<body>[^}]*)\}", css)
    assert match, f"{selector} not found"
    return match.group("body")


def _css_value(block: str, prop: str) -> str:
    match = re.search(r"(?:^|[;\s])" + re.escape(prop) + r"\s*:\s*(?P<value>[^;]+);", block)
    assert match, f"{prop} not found"
    return match.group("value").strip()


def test_the_view_copies_the_ink_spacing_and_default_size_of_a_webapp_note():
    """הדיו, ריווח השורות וגודל הטקסט של התצוגה הם של פתק בוובאפ, בגודל ברירת המחדל שלו.

    "גדול מאוד" הוא המינימום הקריא — החלטת המשתמש — והוא ברירת המחדל של הוובאפ
    (``NOTE_FONT_SIZE_DEFAULT``). הדף אינו טוען את ``sticky-notes.css``, ולכן הערכים משוכפלים
    ב-``note_view.css``; הטסט הזה הוא מה שמונע מהם להיסחף. אם ברירת המחדל בוובאפ תשתנה, הוא
    ייפול — וההחלטה אם התצוגה עוברת איתה חוזרת למשתמש.
    """
    from webapp.app import NOTE_FONT_SIZE_DEFAULT

    webapp_css = (_REPO / "webapp" / "static" / "css" / "sticky-notes.css").read_text(encoding="utf-8")
    view_css = (_REPO / "mcp_server" / "apps" / "note_view.css").read_text(encoding="utf-8")
    paper = _css_block(view_css, ".ck-paper")
    content = _css_block(webapp_css, ".sticky-note-content")
    # המכל של התוכן בוובאפ — מה שהמנוע בונה לתוכו, והקובץ שלו אינו בדף של התצוגה.
    tasks = _css_block(webapp_css, ".sticky-note-tasks")
    view_body = _css_block(view_css, ".ck-body")
    size_selector = ":root" if NOTE_FONT_SIZE_DEFAULT == "normal" else f":root.sticky-font-{NOTE_FONT_SIZE_DEFAULT}"
    size = _css_block(webapp_css, size_selector)

    assert NOTE_FONT_SIZE_DEFAULT == "xlarge"
    assert _css_value(paper, "--ck-font") == _css_value(size, "--sticky-note-font") == "20px"
    assert _css_value(paper, "--ck-ink").lower() == _css_value(content, "color").lower() == _css_value(tasks, "color").lower()
    assert _css_value(paper, "--ck-line-height") == _css_value(content, "line-height") == _css_value(tasks, "line-height")
    # שבירת השורות של התוכן — כמו המכל בוובאפ, שהשורות של המנוע יורשות ממנו.
    assert _css_value(view_body, "white-space") == _css_value(tasks, "white-space") == "pre-wrap"
    assert _css_value(view_body, "overflow-wrap") == _css_value(tasks, "overflow-wrap")
    # הדיו של הכותרת ושל הפתק הריק — הטוקנים עצמם, מהעיצוב המשותף שבדף, ולא עותק שלהם.
    assert _css_value(_css_block(view_css, ".ck-paper.has-note-color .ck-title"), "color") == "var(--note-ink)"
    assert _css_value(_css_block(view_css, ".ck-paper.has-note-color .ck-empty"), "color") == "var(--note-ink-muted)"
    assert ("webapp", "css/sticky-md-render.css") in note_view.STYLE_PARTS
    shared = (_REPO / "webapp" / "static" / "css" / "sticky-md-render.css").read_text(encoding="utf-8")
    assert "--note-ink:" in _css_block(shared, ".sticky-note") and "--note-ink-muted:" in _css_block(shared, ".sticky-note")
    assert _css_value(_css_block(view_css, ".ck-body"), "font-size") == "calc(var(--ck-font) / var(--ck-text-scale, 1))"
    # הכותרת כמו בוובאפ — החלטת המשתמש — ולא בגודל של הגוף.
    webapp_title = _css_block(webapp_css, ".sticky-note-title")
    view_title = _css_block(view_css, ".ck-title")
    assert _css_value(paper, "--ck-title-font") == _css_value(webapp_title, "font-size")
    assert _css_value(paper, "--ck-title-weight") == _css_value(webapp_title, "font-weight")
    assert _css_value(view_title, "font-size") == "calc(var(--ck-title-font) / var(--ck-text-scale, 1))"
    assert _css_value(view_title, "font-weight") == "var(--ck-title-weight)"


def _declarations(block: str) -> list[str]:
    """ההצהרות של בלוק, אחת לשורה, בלי רווחים מסביב — כדי להשוות שני בלוקים בלי תלות בהזחה."""
    return [d.strip() for d in block.split(";") if d.strip()]


def test_the_view_copies_the_in_note_search_highlight_of_the_webapp():
    """הסימון של ``query`` בתצוגה נראה כמו החיפוש בתוך פתק בוובאפ — אותה מחלקה, ואותם כללים.

    ``note_view.js`` מדגיש עם ``NOTE_SEARCH_HIT_CLASS`` של ``sticky-notes.js``, והכללים שלה יושבים ב-
    ``sticky-notes.css``, שהדף אינו כולל (הוא מביא איתו את השלד של הפתק בלוח). ולכן הם מועתקים ל-
    ``note_view.css``, והטסט הזה משווה את שני הבלוקים — הרגיל והפעיל — הצהרה מול הצהרה.
    """
    webapp_js = (_REPO / "webapp" / "static" / "js" / "sticky-notes.js").read_text(encoding="utf-8")
    view_js = (_REPO / "mcp_server" / "apps" / "note_view.js").read_text(encoding="utf-8")
    webapp_class = re.search(r"const NOTE_SEARCH_HIT_CLASS = '([\w-]+)';", webapp_js).group(1)
    assert re.search(r"var MARK_HIT_CLASS = '([\w-]+)';", view_js).group(1) == webapp_class
    webapp_css = (_REPO / "webapp" / "static" / "css" / "sticky-notes.css").read_text(encoding="utf-8")
    view_css = (_REPO / "mcp_server" / "apps" / "note_view.css").read_text(encoding="utf-8")
    for selector in (f".{webapp_class}", f".{webapp_class}.is-active"):
        assert _declarations(_css_block(view_css, selector)) == _declarations(_css_block(webapp_css, selector)), selector


def _new_note_height() -> int:
    """``NEW_NOTE_H`` מ-``sticky-notes.js`` — הגובה של פתק חדש בוובאפ, הבעלים של הגובה הקבוע בתצוגה."""
    js = (_REPO / "webapp" / "static" / "js" / "sticky-notes.js").read_text(encoding="utf-8")
    found = re.findall(r"\bNEW_NOTE_H\s*=\s*(\d+)\b", js)
    assert len(found) == 1, found
    return int(found[0])


def test_the_fixed_height_of_the_view_is_the_height_of_a_new_webapp_note():
    """הגובה הקבוע של התצוגה (``--ck-cap``) הוא הגובה של פתק חדש בוובאפ — החלטת המשתמש.

    הדף אינו טוען את ה-JS של הוובאפ, ולכן המספר משוכפל ב-``note_view.css``. אם ``NEW_NOTE_H``
    ישתנה, הטסט ייפול, וההחלטה אם התצוגה עוברת איתו חוזרת למשתמש.
    """
    view_css = (_REPO / "mcp_server" / "apps" / "note_view.css").read_text(encoding="utf-8")
    assert _css_value(_css_block(view_css, ":root"), "--ck-cap") == f"{_new_note_height()}px"
    # התקרה חלה דרך הנוסחה האחת, ולא דרך ערך שני שהוקלד במקום אחר.
    assert _css_value(_css_block(view_css, "#ck-note-root"), "max-height") == (
        "min(var(--ck-cap), var(--ck-host-max, var(--ck-cap)))"
    )


def test_every_font_size_in_the_view_undoes_the_system_text_zoom():
    """כל ``font-size`` בתצוגה מחולק ב-``--ck-text-scale`` — ההגדלה של המערכת שהדף מודד.

    WebView של אנדרואיד מכפיל כל גופן בגודל הגופן של המערכת, בזמן שהגובה הקבוע של התצוגה אינו גדל.
    ``note_view.js`` מודד את ההכפלה ומעביר אותה כמשתנה, והחלוקה כאן מחזירה כל גופן לגודל של
    הוובאפ. גופן חדש שנכתב בלי החלוקה היה גדל לבדו בטאבלט, בלי שום סימן בדסקטופ — ולכן הטסט עובר
    על **כל** ההצהרות בקובץ, ולא על רשימה של סלקטורים.
    """
    view_css = (_REPO / "mcp_server" / "apps" / "note_view.css").read_text(encoding="utf-8")
    rules = re.sub(r"/\*.*?\*/", "", view_css, flags=re.S)
    sizes = re.findall(r"(?:^|[;{\s])font-size\s*:\s*([^;]+);", rules)
    assert sizes, "no font-size declarations found"
    off = [value for value in sizes if not re.fullmatch(r"calc\(.+ / var\(--ck-text-scale, 1\)\)", value.strip())]
    assert not off, off
    # המשתנה מוצב רק מה-JS: ערך שהוקלד ב-CSS היה חל גם בלי הגדלה.
    assert "--ck-text-scale:" not in rules.replace(" ", "")
