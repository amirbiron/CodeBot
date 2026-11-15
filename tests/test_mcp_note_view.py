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


class _NoteBackend:
    """backend שמחזיק פתק אחד ורושם כל קריאה. ``get_note`` מחזיר את הצורה של ``ProductionBackend``."""

    def __init__(self, answer=None, orphaned=False):
        self.calls = []
        self.orphaned = orphaned
        self.answer = answer if answer is not None else {
            "ok": True,
            "note": {
                "id": _NOTE_ID,
                "title": "רשימה",
                "content": "# " + _BODY_MARKER + "\nשורה שנייה",
                "color": "#ffeddb",
                "color_id": "orange_light",
            },
            "target": "board",
            "board_id": _BOARD_ID,
        }

    def get_note(self, user_id, *, note_id, with_version=False):
        self.calls.append(("get_note", user_id, note_id, with_version))
        return self.answer

    def repo_path_orphaned(self, *, repo_name, repo_path):
        self.calls.append(("repo_path_orphaned", repo_name, repo_path))
        return self.orphaned


def _repo_note_answer():
    return {
        "ok": True,
        "note": {"id": _NOTE_ID, "title": None, "content": "x", "color": "#ffffcc",
                 "repo_name": "CodeBot", "repo_path": "a.py"},
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
    assert answer == {"ok": True, **backend.answer}
    assert result.structuredContent is None
    assert backend.calls == [("get_note", _USER, _NOTE_ID, False)]


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


# ===========================================================================
# השער — אותו של codekeeper_get_note
# ===========================================================================


def test_an_invalid_note_id_never_reaches_the_backend():
    backend = _NoteBackend()
    for bad in ("", "xyz", "a" * 25, None, 5):
        assert handlers.show_note(backend, _USER, note_id=bad, is_admin=True) == {
            "ok": False, "error": "invalid_note_id"}
    assert backend.calls == []


def test_a_refusal_from_the_backend_comes_back_as_it_is():
    backend = _NoteBackend(answer={"ok": False, "error": "not_found"})
    assert handlers.show_note(backend, _USER, note_id=_NOTE_ID, is_admin=True) == {
        "ok": False, "error": "not_found"}


def test_a_repo_note_is_for_the_admin_only_like_get_note():
    """פתק ריפו למי שאינו אדמין — ``not_found``, אותה תשובה כמו לפתק שאינו קיים. רק ``True`` ממש פותח."""
    for not_admin in (False, None, 1, "yes"):
        backend = _NoteBackend(answer=_repo_note_answer())
        assert handlers.show_note(backend, _USER, note_id=_NOTE_ID, is_admin=not_admin) == {
            "ok": False, "error": "not_found"}, not_admin
    admin = handlers.show_note(_NoteBackend(answer=_repo_note_answer(), orphaned=True), _USER,
                               note_id=_NOTE_ID, is_admin=True)
    assert admin["ok"] is True and admin["orphaned"] is True
    assert (admin["target"], admin["repo_name"], admin["repo_path"]) == ("repo", "CodeBot", "a.py")


def test_show_note_is_get_note_without_threads_and_version(monkeypatch):
    """אותה צורה של ``get_note(part="all")`` — חוץ מהשרשורים ומ-``version``, שהכלי הזה אינו מבקש.

    נבנה מאותו backend בשני המסלולים, ולכן שדה שיתווסף לפתק או ליעד יגיע לשניהם. ``_with_threads``
    מוחלף כאן בזהות, כי השרשורים אינם חלק ממה שנבדק.
    """
    monkeypatch.setattr(handlers, "_with_threads", lambda backend, user_id, out, **kw: out)
    answer = {**_NoteBackend().answer, "version": 3}
    via_get = handlers.get_note(_NoteBackend(answer=answer), _USER, note_id=_NOTE_ID, is_admin=False)
    shown_backend = _NoteBackend(answer={k: v for k, v in answer.items() if k != "version"})
    shown = handlers.show_note(shown_backend, _USER, note_id=_NOTE_ID, is_admin=False)
    assert shown == {k: v for k, v in via_get.items() if k != "version"}
    assert shown_backend.calls == [("get_note", _USER, _NOTE_ID, False)]


# ===========================================================================
# בניית הדף
# ===========================================================================


def _copy_assets(tmp_path: Path) -> Path:
    target = tmp_path / "apps"
    shutil.copytree(_REPO / "mcp_server" / "apps", target)
    return target


def test_the_version_is_the_hash_of_the_page_as_sent():
    view = note_view.build_note_view()
    assert view.version == hashlib.sha256(view.html.encode("utf-8")).hexdigest()[:note_view.VERSION_HEX_CHARS]
    assert view.uri == f"ui://codekeeper/note-view/{view.version}.html"
    assert note_view.STYLE_SLOT not in view.html and note_view.SCRIPT_SLOT not in view.html
    assert "ck-note-root" in view.html


@pytest.mark.parametrize("name", ["note_view.html", "note_view.css", "note_view.js"])
def test_any_change_to_any_part_changes_the_address(tmp_path, name):
    """הכתובת משתנה עם כל קובץ שהדף נבנה ממנו — אחרת מארח שמחזיק את הדף בקאש לפי כתובת היה
    מגיש את הישן (``stale-asset-cache-policy``)."""
    assets = _copy_assets(tmp_path)
    before = note_view.build_note_view(assets)
    path = assets / name
    text = path.read_text(encoding="utf-8")
    marker = "<!-- changed -->" if name.endswith(".html") else "/* changed */"
    path.write_text(text + "\n" + marker + "\n", encoding="utf-8")
    after = note_view.build_note_view(assets)
    assert after.version != before.version


@pytest.mark.parametrize("name,slot,body", [
    ("note_view.html", note_view.STYLE_SLOT, None),
    ("note_view.html", note_view.SCRIPT_SLOT, None),
])
def test_a_shell_without_exactly_one_slot_stops_the_server(tmp_path, name, slot, body):
    assets = _copy_assets(tmp_path)
    shell = (assets / name).read_text(encoding="utf-8")
    (assets / name).write_text(shell.replace(slot, ""), encoding="utf-8")
    with pytest.raises(RuntimeError, match="exactly once"):
        note_view.build_note_view(assets)
    (assets / name).write_text(shell.replace(slot, slot + slot), encoding="utf-8")
    with pytest.raises(RuntimeError, match="exactly once"):
        note_view.build_note_view(assets)


@pytest.mark.parametrize("name,closing", [
    ("note_view.js", "</ScRiPt>"),
    ("note_view.css", "</STYLE>"),
])
def test_code_that_would_close_its_own_block_stops_the_server(tmp_path, name, closing):
    """``</script`` בתוך הסקריפט סוגר את הבלוק בדפדפן, בכל רישיות — ושאר הקוד היה מוצג כטקסט."""
    assets = _copy_assets(tmp_path)
    path = assets / name
    path.write_text(path.read_text(encoding="utf-8") + f"\n/* {closing} */\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="would end the inline block"):
        note_view.build_note_view(assets)


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
    # הדיו של הפתק מוצהר בקובץ העיצוב של המנוע, שנטען לפני ``sticky-notes.css`` בכל תבנית.
    ink_css = (_REPO / "webapp" / "static" / "css" / "sticky-md-render.css").read_text(encoding="utf-8")
    note = _css_block(ink_css, ".sticky-note")
    size_selector = ":root" if NOTE_FONT_SIZE_DEFAULT == "normal" else f":root.sticky-font-{NOTE_FONT_SIZE_DEFAULT}"
    size = _css_block(webapp_css, size_selector)

    assert NOTE_FONT_SIZE_DEFAULT == "xlarge"
    assert _css_value(paper, "--ck-font") == _css_value(size, "--sticky-note-font") == "20px"
    assert _css_value(paper, "--ck-ink").lower() == _css_value(content, "color").lower()
    assert _css_value(paper, "--ck-line-height") == _css_value(content, "line-height")
    assert _css_value(paper, "--ck-title-ink").lower() == _css_value(note, "--note-ink").lower()
    assert _css_value(paper, "--ck-muted-ink").lower() == _css_value(note, "--note-ink-muted").lower()
    assert _css_value(_css_block(view_css, ".ck-body"), "font-size") == "calc(var(--ck-font) / var(--ck-text-scale, 1))"
    # הכותרת כמו בוובאפ — החלטת המשתמש — ולא בגודל של הגוף.
    webapp_title = _css_block(webapp_css, ".sticky-note-title")
    view_title = _css_block(view_css, ".ck-title")
    assert _css_value(paper, "--ck-title-font") == _css_value(webapp_title, "font-size")
    assert _css_value(paper, "--ck-title-weight") == _css_value(webapp_title, "font-weight")
    assert _css_value(view_title, "font-size") == "calc(var(--ck-title-font) / var(--ck-text-scale, 1))"
    assert _css_value(view_title, "font-weight") == "var(--ck-title-weight)"


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
