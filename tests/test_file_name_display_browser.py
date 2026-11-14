"""שם קובץ בשורה עברית בממשק — נמדד בכרומיום: הסיומת בקצה השמאלי, והשם מבודד מהטקסט שסביבו.

``utils/file-name.js`` (ב-JS) והפילטר ``file_name`` (``webapp/file_name_display.py``, בשרת) בונים את השם כ-``<bdi>``.
כאן נמדד הסדר של התווים על המסך, ולא ה-DOM: השם מימין, החלק הלטיני משמאל לעברית, הנקודה משמאל לו, והסיומת
משמאל לנקודה (``FILE_NAME_SHAPE_JS`` ב-``tests/_browser_harness.py``).

- **בשרת** — הקטעים האמיתיים של התבניות, עם ה-CSS שלהן: הכרטיס בעמוד הקבצים (שנחתך אחרי שתי שורות), הכותרות של
  תצוגת הקוד, ה-Markdown וה-HTML, והדשבורד: נעוצים, "קבצים שדורשים טיפול", הפיד ו"פתקים אחרונים".
- **ב-JS** — ``global_search.js`` ו-``notes_search.js`` האמיתיים, על עמוד עם ה-CSS שלהם ותשובת API מדומה. כרטיס
  תוצאת החיפוש הוא ``direction: ltr`` (``global_search.css``), ושם נשבר גם ``ערכות.md`` בלי בידוד.

**כל מדידה רצה גם בלי התיקון, ונכשלת שם** — בשרת עם פילטר שמחזיר את השם כמו שהוא (מה שהתבניות הציגו עד היום),
וב-JS עם ``FileName.fill`` שכותב את השם כטקסט. בדיקה שאינה נופלת בלי התיקון אינה בודקת כלום.

מדולג כשאין Chromium (``chromium_executable`` ב-``tests/conftest.py``).
"""

from __future__ import annotations

import contextlib
import json
import re
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest

pytest.importorskip("playwright", reason="playwright אינו מותקן")

from playwright.sync_api import sync_playwright  # noqa: E402

from _browser_harness import FILE_NAME_SHAPE_JS, copied_to_clipboard  # noqa: E402
from _dashboard_render import render_dashboard  # noqa: E402
from test_file_name_colors_hook_browser import FILE, FRAGMENTS, _content_styles, _lang_icon  # noqa: E402
from test_live_preview_blockquote_browser import TEMPLATES_DIR, _render_fragment  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
STATIC_DIR = REPO_ROOT / "webapp" / "static"
BASE_TEMPLATE = TEMPLATES_DIR / "base.html"
ORIGIN = "http://127.0.0.1:8765"

SPLIT = "מדריך-תצוגת-Markdown-RTL.md"
SHORT_SPLIT = "מדריך-RTL.md"
HEBREW_END = "ערכות.md"

#: מה ששם מפורק צריך להראות.
SPLIT_RIGHT = {"one_line": True, "starts_right": True, "tail_left_of_hebrew": True, "dot_left_of_tail": True,
               "extension_left_of_dot": True}

#: הפילטר "של פעם": השם כמו שהוא — מה שהתבניות הציגו לפני ``|file_name``. לריצת הבקרה.
PLAIN_FILTERS = {"file_name": lambda value: value}

#: ``(el) => bool``: בשם שנגמר בעברית — האם הסיומת משמאל לעברית. בהקשר שמאל-לימין, בלי בידוד, היא יוצאת מימין.
EXTENSION_LEFT_OF_HEBREW_JS = """(el) => {
  const rect = (i) => {
    const w = document.createTreeWalker(el, NodeFilter.SHOW_TEXT); let n, seen = 0;
    while ((n = w.nextNode())) {
      if (i < seen + n.data.length) { const r = document.createRange(); r.setStart(n, i - seen); r.setEnd(n, i - seen + 1);
        const b = r.getBoundingClientRect(); return b.left + b.width / 2; }
      seen += n.data.length;
    }
    return null;
  };
  const t = el.textContent, dot = t.lastIndexOf('.');
  return rect(dot + 1) < rect(dot - 1);
}"""

#: האלמנט שמודדים: ה-``<bdi>`` החיצוני כשהוא קיים, ואחרת המארח עצמו (בריצת הבקרה אין ``<bdi>``).
NAME_EL_JS = "(host) => host.querySelector(':scope > bdi') || host"


def _shape(page, selector: str) -> dict:
    host = page.locator(selector).first
    host.wait_for(state="attached")
    return host.evaluate(f"(host) => ({FILE_NAME_SHAPE_JS})(({NAME_EL_JS})(host))")


def _extension_left(page, selector: str) -> bool:
    host = page.locator(selector).first
    return host.evaluate(f"(host) => ({EXTENSION_LEFT_OF_HEBREW_JS})(({NAME_EL_JS})(host))")


#: התג של ``utils/file-name.js`` ב-``base.html``.
FILE_NAME_TAG_RE = re.compile(
    r'<script src="\{\{ url_for\(\'static\', filename=\'js/utils/file-name\.js\'\) \}\}[^"]*"[^>]*></script>'
)


def _script_tag(name: str) -> str:
    """התג האמיתי של ``utils/file-name.js`` מ-``base.html``, עם ``src`` שאפשר להגיש (``/static/<name>``) — כך
    ``defer`` שיחזור לתג יופיע גם כאן."""
    match = FILE_NAME_TAG_RE.search(BASE_TEMPLATE.read_text(encoding="utf-8"))
    assert match, "לא נמצא התג של file-name.js ב-base.html"
    return re.sub(r'src="[^"]*"', f'src="/static/{name}"', match.group(0))


@contextlib.contextmanager
def _browser(executable):
    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(executable_path=executable) if executable else pw.chromium.launch()
        except Exception as exc:  # noqa: BLE001 — כל כשל השקה פירושו אין דפדפן
            pytest.skip(f"אין Chromium זמין: {exc}")
        try:
            yield browser
        finally:
            browser.close()


def _open(browser, pages: dict[str, str], path: str, *, api: dict | None = None, viewport=None):
    """עמוד מ-``pages`` (נתיב ← HTML), קבצים סטטיים מהדיסק, ו-``api`` (נתיב ← JSON). שום דבר לא נכתב לעץ הקוד."""
    context = browser.new_context(viewport=viewport or {"width": 1280, "height": 900}, locale="he-IL")
    page = context.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    # ``alert`` של שגיאה (החיפוש מציג כך כשל) — נרשם כשגיאה ונסגר, כדי שלא ייראה כ-timeout.
    page.on("dialog", lambda dialog: (errors.append(f"dialog: {dialog.message}"), dialog.dismiss()))

    def serve(route):
        url_path = urlsplit(route.request.url).path
        if url_path in pages:
            route.fulfill(status=200, content_type="text/html; charset=utf-8", body=pages[url_path])
            return
        if api and url_path in api:
            route.fulfill(status=200, content_type="application/json", body=json.dumps(api[url_path]))
            return
        if url_path.startswith("/static/"):
            target = (STATIC_DIR / url_path[len("/static/"):]).resolve()
            if target.is_file() and STATIC_DIR.resolve() in target.parents:
                kind = {".js": "application/javascript", ".css": "text/css", ".json": "application/json"}
                route.fulfill(status=200, content_type=kind.get(target.suffix, "text/plain"),
                              body=target.read_text(encoding="utf-8"))
                return
        route.fulfill(status=404, body="")

    page.route("**/*", serve)
    page.goto(f"{ORIGIN}{path}", wait_until="load")
    page.js_errors = errors
    return page


def _rtl_page(body: str, styles: str = "") -> str:
    return (f'<!doctype html><html dir="rtl" lang="he"><head><meta charset="utf-8">{styles}</head>'
            f'<body style="font-family: Arial, sans-serif">{body}</body></html>')


# ------------------------------------------------------------------------------------------- בשרת


def _server_pages(filters):
    # הקובץ של הבדיקה הקיימת לווי הצבע של שם הקובץ — כל השדות שהקטעים קוראים — עם שם שמפורק.
    file = {**FILE, "file_name": SPLIT}
    pages = {}
    for name, (template_name, start, end, closing) in FRAGMENTS.items():
        source = (TEMPLATES_DIR / template_name).read_text(encoding="utf-8")
        begin = source.index(start)
        stop = source.index(end, begin) + len(end)
        body = _render_fragment(source[begin:stop] + closing, filters=filters, file=file, files=[file],
                                files_compact_view=False, lang_icon=_lang_icon, LANG_ICON_SIZES={"file_row": 48})
        pages[f"/{name}"] = _rtl_page(body, _content_styles(template_name))
    return pages


@pytest.mark.parametrize("fixed", [True, False], ids=["fixed", "control"])
def test_the_name_in_the_files_card_and_the_file_page_headings(fixed, chromium_executable):
    """הכרטיס בעמוד הקבצים והכותרות של תצוגת הקוד, ה-Markdown וה-HTML — ``.file-name-text`` בכל אחד מהם."""
    pages = _server_pages(None if fixed else PLAIN_FILTERS)
    with _browser(chromium_executable) as browser:
        shapes = {}
        for name in FRAGMENTS:
            page = _open(browser, pages, f"/{name}")
            shapes[name] = _shape(page, ".file-name-text")
            assert page.locator(".file-name-text").first.evaluate("(el) => el.textContent.trim()") == SPLIT, name
            assert not page.js_errors, page.js_errors
            page.context.close()
    for name, shape in shapes.items():
        if fixed:
            # כולל ``one_line``: בשם שנשבר לכמה שורות ההשוואה בין המיקומים אינה אומרת דבר.
            assert shape == SPLIT_RIGHT, f"{name}: {shape}"
        else:
            assert not shape["dot_left_of_tail"], f"{name}: בקרה — בלי הפילטר הסיומת באמצע; אחרת המדידה אינה מבחינה: {shape}"


def _dashboard_html(filters) -> str:
    event = {"group": "files", "accent": "", "icon": "", "title": f"עודכן {SHORT_SPLIT}", "subtitle": "",
             "relative_time": "עכשיו", "meta": {"action": "עודכן", "file_name": SHORT_SPLIT}}
    body = render_dashboard(
        filters=filters,
        pinned_files=[{"id": "p1", "file_name": SHORT_SPLIT, "language": "markdown"}],
        activity_timeline={"has_events": True, "compact_limit": 5, "feed": [event], "groups": [],
                           "filters": [], "settings": {}},
        notes_snapshot={"has_notes": True, "notes": [
            {"title": "פתק", "url": "/note/n1", "location": SHORT_SPLIT, "location_kind": "file", "relative_time": "עכשיו"}]},
        files_need_attention={"has_items": True, "missing_metadata": [{"id": "a1", "file_name": SHORT_SPLIT,
                                                                       "language": "markdown", "reason_text": "חסר תיאור",
                                                                       "description": "", "tags_full": []}],
                              "total_missing": 1, "shown_missing": 1, "settings": {"max_items": 10}},
        LANG_ICON_SIZES=SimpleNamespace(file_row=16, list=16, timeline=16),
    )
    return _rtl_page(body)


#: המקומות בדשבורד, והאלמנט שמחזיק את השם. הפיד והמיקום של פתק מחזיקים גם טקסט אחר ("עודכן", " · עכשיו"), ולכן שם
#: מודדים את ה-``<bdi>`` — בריצת הבקרה אין ``<bdi>``, והמדידה על השורה כולה.
DASHBOARD_PLACES = {
    "pinned": ".pinned-card__name",
    "attention": ".attention-item__name",
    "feed": ".timeline-feed .timeline-title",
    "notes": ".note-meta",
}


@pytest.mark.parametrize("fixed", [True, False], ids=["fixed", "control"])
def test_the_name_in_the_dashboard(fixed, chromium_executable):
    pages = {"/dashboard": _dashboard_html(None if fixed else PLAIN_FILTERS)}
    with _browser(chromium_executable) as browser:
        # רוחב של טלפון: שם הפיד המקוצר (``mobile-only``) מוצג רק שם.
        page = _open(browser, pages, "/dashboard", viewport={"width": 390, "height": 1400})
        shapes = {place: _shape(page, sel) for place, sel in DASHBOARD_PLACES.items()}
        texts = {place: page.locator(sel).first.evaluate("(el) => el.textContent.replace(/\\s+/g, ' ').trim()")
                 for place, sel in DASHBOARD_PLACES.items()}
        assert not page.js_errors, page.js_errors
    assert texts["feed"] == f"עודכן {SHORT_SPLIT}", texts
    assert texts["notes"].startswith(SHORT_SPLIT), texts
    for place, shape in shapes.items():
        if fixed:
            assert shape == SPLIT_RIGHT, f"{place}: {shape}"
        else:
            # בבקרה אין ``<bdi>``, ונמדדת השורה כולה — עם הרווחים ו-" · עכשיו" של מיקום הפתק, ולכן בלי ``one_line``.
            assert not shape["dot_left_of_tail"], f"{place}: בקרה — {shape}"


# --------------------------------------------------------------------------------------------- ב-JS


#: ``FileName.fill`` "של פעם" — השם כטקסט, כמו שהמקומות האלה כתבו אותו עד היום. לריצת הבקרה.
PLAIN_FILL_JS = """window.FileName = Object.freeze(Object.assign({}, window.FileName, {
  fill(el, name) { el.textContent = name == null ? '' : String(name); return el; },
  element(name) { return document.createTextNode(name == null ? '' : String(name)); },
}));"""


def _search_page(control: bool) -> str:
    return _rtl_page(
        '<input id="globalSearchInput" value="מדריך"><button id="searchBtn">חפש</button>'
        '<div id="searchSuggestions" hidden></div>'
        '<div id="searchResultsContainer" style="display:none"><div id="searchInfo"></div>'
        '<div id="searchResults"></div><div id="searchPagination"></div></div>'
        + (f"<script>{PLAIN_FILL_JS}</script>" if control else "")
        + '<script src="/static/js/global_search.js" defer></script>',
        # ``size-format.js`` — גם הוא נטען ב-``base.html``, ו-``humanSize`` בכרטיס קורא ממנו.
        _script_tag("js/utils/file-name.js") + '<script src="/static/js/utils/size-format.js"></script>'
        '<link rel="stylesheet" href="/static/css/global_search.css">',
    )


SEARCH_API = {"/api/search/global": {
    "success": True, "query": "מדריך", "total_results": 2, "page": 1, "total_pages": 1,
    "results": [
        {"file_id": "f1", "file_name": SPLIT, "language": "markdown", "snippet": "x", "highlights": [], "score": 1.0,
         "size": 10, "updated_at": "2026-11-14T10:00:00+00:00"},
        {"file_id": "f2", "file_name": HEBREW_END, "language": "markdown", "snippet": "y", "highlights": [],
         "score": 0.5, "size": 10, "updated_at": "2026-11-14T10:00:00+00:00"},
    ],
}}


@pytest.mark.parametrize("fixed", [True, False], ids=["fixed", "control"])
def test_the_name_in_a_search_result_card_which_is_left_to_right(fixed, chromium_executable):
    """הכרטיס הוא ``direction: ltr``: בלי הבידוד גם ``ערכות.md`` יוצא עם הסיומת מימין לשם. והעתקה ללוח מחזירה את
    השם בדיוק."""
    pages = {"/search": _search_page(control=not fixed)}
    with _browser(chromium_executable) as browser:
        page = _open(browser, pages, "/search", api=SEARCH_API)
        assert page.evaluate("() => getComputedStyle(document.body).direction") == "rtl"
        page.evaluate("() => window.performGlobalSearch()")
        page.locator(".search-result-card .file-name").nth(1).wait_for(state="attached")
        assert page.locator(".search-result-card").first.evaluate("(el) => getComputedStyle(el).direction") == "ltr", \
            "הכרטיס אמור להיות בהקשר שמאל-לימין — אחרת הבדיקה אינה בודקת את מה שהיא מתיימרת"
        split_shape = _shape(page, ".search-result-card .file-name")
        hebrew_end_left = _extension_left(page, ".search-result-card:nth-of-type(2) .file-name")
        clipboard = copied_to_clipboard(page, ORIGIN, ".search-result-card .file-name", SPLIT) if fixed else None
        assert not page.js_errors, page.js_errors
    if fixed:
        assert split_shape == SPLIT_RIGHT, split_shape
        assert hebrew_end_left, "ערכות.md: הסיומת צריכה להיות משמאל לשם"
        assert clipboard == SPLIT, f"Ctrl+C וקריאה מהלוח מחזירים את השם כמו שנכתב: {clipboard!r}"
    else:
        assert not split_shape["dot_left_of_tail"], f"בקרה: {split_shape}"
        assert not hebrew_end_left, "בקרה: בהקשר שמאל-לימין, בלי בידוד, הסיומת של ערכות.md יוצאת מימין"


#: שם קובץ עם מרכאות שמנסה לצאת מה-``title`` ולהוסיף מאפיין משלו.
QUOTED_NAME = 'דוח "x" onmouseover="window.__escaped = 1" data-x="y.md'


def test_a_file_name_with_quotes_stays_inside_the_title_of_its_search_card(chromium_executable):
    """ה-``title`` של שם הקובץ בכרטיס נבנה במחרוזת, ב-``escapeHtml`` של ``global_search.js``. עד התיקון הפונקציה לא קודדה
    מרכאות, ושם עם ``"`` יצא מהמאפיין: מה שאחריו נקרא כמאפיינים חדשים של הקישור."""
    api = {"/api/search/global": dict(SEARCH_API["/api/search/global"], total_results=1, results=[
        dict(SEARCH_API["/api/search/global"]["results"][0], file_name=QUOTED_NAME)])}
    with _browser(chromium_executable) as browser:
        page = _open(browser, {"/search": _search_page(control=False)}, "/search", api=api)
        page.evaluate("() => window.performGlobalSearch()")
        link = page.locator(".search-result-card .file-name").first
        link.wait_for(state="attached")
        attrs = link.evaluate("(el) => el.getAttributeNames()")
        title = link.get_attribute("title")
        text = link.evaluate("(el) => el.textContent")
        assert not page.js_errors, page.js_errors
    assert title == QUOTED_NAME, title
    assert text == QUOTED_NAME, text
    assert sorted(attrs) == ["class", "href", "target", "title"], attrs


def _notes_search_page(control: bool) -> str:
    return _rtl_page(
        '<form id="noteSearchForm"><input id="noteSearchInput"><input type="checkbox" id="noteSearchArchive"></form>'
        '<p id="noteSearchMsg" hidden></p><ol class="notes-search-results" id="noteSearchResults"></ol>'
        + (f"<script>{PLAIN_FILL_JS}</script>" if control else "")
        + '<script src="/static/js/utils/text-highlight.js"></script>'
        + '<script src="/static/js/notes_search.js" defer></script>',
        _script_tag("js/utils/file-name.js") + '<link rel="stylesheet" href="/static/css/notes-search.css">',
    )


NOTES_API = {"/api/sticky-notes/search": {"ok": True, "results": [
    {"id": "n1", "title": "מדריך", "preview": "גוף", "color": "#FFFFCC", "target": "file", "file_name": SHORT_SPLIT,
     "url": "/note/n1"},
]}}


@pytest.mark.parametrize("fixed", [True, False], ids=["fixed", "control"])
def test_the_name_in_a_notes_search_result(fixed, chromium_executable):
    pages = {"/notes/search": _notes_search_page(control=not fixed)}
    with _browser(chromium_executable) as browser:
        page = _open(browser, pages, "/notes/search?q=%D7%9E%D7%93%D7%A8%D7%99%D7%9A", api=NOTES_API)
        page.locator(".notes-search-meta").first.wait_for(state="attached")
        shape = _shape(page, ".notes-search-meta")
        text = page.locator(".notes-search-meta").first.evaluate("(el) => el.textContent")
        assert not page.js_errors, page.js_errors
    assert text == f"קובץ · {SHORT_SPLIT}", f"הטקסט של השורה לא משתנה: {text!r}"
    if fixed:
        assert shape == SPLIT_RIGHT, shape
    else:
        assert not shape["dot_left_of_tail"], f"בקרה: {shape}"


# ------------------------------------------------- ב-JS, בעמודים האמיתיים של האפליקציה

#: ``utils/file-name.js`` "של פעם" לריצת הבקרה: ``fill`` כותב את השם כטקסט ו-``element`` מחזיר צומת טקסט — מה
#: שהמקומות האלה עשו עד היום. מוגש במקום הקובץ האמיתי, כך שכל עמוד טוען אותו מאותו תג ב-``base.html``.
PLAIN_FILE_NAME_JS = (STATIC_DIR / "js" / "utils" / "file-name.js").read_text(encoding="utf-8") + "\n" + PLAIN_FILL_JS

_COLLECTION = {"id": "c1", "name": "אוסף", "icon": "📁", "color": "blue", "items_count": 1, "is_favorite": False}
_WORKSPACE = {"id": "w1", "name": "שולחן עבודה", "slug": "workspace", "icon": "🖥️", "color": "blue", "items_count": 1,
              "is_favorite": False}


def _items(**extra):
    return {"ok": True, "items": [{"source": "regular", "file_name": SHORT_SPLIT, "id": "i1", **extra}], "total": 1,
            "page": 1, "per_page": 20}


#: עמוד באפליקציה, תשובות API מדומות (קידומת נתיב ← JSON, הספציפית קודם), פעולה שמציגה את השם, והאלמנט שמחזיק אותו.
JS_PAGES = {
    "recent_files_modal": ("/collections", {"/api/files/recent": [
        {"id": "x1", "filename": SHORT_SPLIT, "language": "markdown", "accessed_at": "2026-11-14T10:00:00Z"}]},
        "() => showRecentFiles()", ".recent-files-modal .file-name"),
    "collection_card": ("/collections/c1", {"/api/collections/c1/items": _items(),
                                            "/api/collections/c1": {"ok": True, "collection": _COLLECTION},
                                            "/api/collections": {"ok": True, "collections": [_COLLECTION]}},
                        None, ".collection-card__link"),
    "workspace_card": ("/collections/w1", {"/api/collections/w1/items": _items(workspace_state="todo"),
                                           "/api/collections/w1": {"ok": True, "collection": _WORKSPACE},
                                           "/api/collections": {"ok": True, "collections": [_WORKSPACE]}},
                       None, ".workspace-card__link"),
    "shared_collection_item": ("/collections/shared/tok", {
        "/api/collections/shared/tok/files/f1": {"ok": True, "file": {"id": "f1", "file_name": SHORT_SPLIT, "content": "x"}},
        "/api/collections/shared/tok": {"ok": True, "collection": {"name": "משותף"}, "items_total": 1, "items": [
            {"file_name": SHORT_SPLIT, "share": {"file_id": "f1", "view_url": "/api/collections/shared/tok/files/f1"}}]}},
        None, ".shared-item-name"),
    "shared_collection_viewer": ("/collections/shared/tok", {
        "/api/collections/shared/tok/files/f1": {"ok": True, "file": {"id": "f1", "file_name": SHORT_SPLIT, "content": "x"}},
        "/api/collections/shared/tok": {"ok": True, "collection": {"name": "משותף"}, "items_total": 1, "items": [
            {"file_name": SHORT_SPLIT, "share": {"file_id": "f1", "view_url": "/api/collections/shared/tok/files/f1"}}]}},
        None, ".shared-viewer-header .file-name"),
    # הכותרת של צד בתוצאת ההשוואה יושבת בהקשר שמאל-לימין (``.compare-sides`` ב-``compare.css``).
    "compare_side_label": ("/compare", {"/api/compare/files": {
        "left_info": {"file_name": SHORT_SPLIT}, "right_info": {"file_name": HEBREW_END}, "lines": [], "stats": {}}},
        "() => { window.CompareView.initFilesMode({files: ["
        "{_id: 'a', file_name: 'a', programming_language: 'markdown', file_size: 1, lines_count: 1},"
        "{_id: 'b', file_name: 'b', programming_language: 'markdown', file_size: 1, lines_count: 1}],"
        " selectedLeft: 'a', selectedRight: 'b'}); document.getElementById('btn-compare').click(); }",
        "#left-file-label"),
}


@pytest.mark.parametrize("fixed", [True, False], ids=["fixed", "control"])
@pytest.mark.parametrize("place", sorted(JS_PAGES))
def test_the_name_in_pages_that_build_it_in_javascript(place, fixed, admin_live_server, chromium_executable):
    """העמוד האמיתי מהאפליקציה (``admin_live_server``), עם הסקריפטים שלו ותשובות API מדומות — שם ה-JS בונה את השם
    אחרי שה-HTML נכנס (``FileName.fill``), ולא כמחרוזת ב-``innerHTML``."""
    path, api, action, selector = JS_PAGES[place]
    prefixes = sorted(api, key=len, reverse=True)
    with _browser(chromium_executable) as browser:
        context = browser.new_context(viewport={"width": 1280, "height": 900}, locale="he-IL")
        context.add_cookies([{"name": "session", "value": admin_live_server.session_cookie,
                              "domain": "127.0.0.1", "path": "/"}])
        page = context.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.on("dialog", lambda dialog: (errors.append(f"dialog: {dialog.message}"), dialog.dismiss()))

        def api_route(route):
            url_path = urlsplit(route.request.url).path
            for prefix in prefixes:
                if url_path.startswith(prefix):
                    route.fulfill(status=200, content_type="application/json", body=json.dumps(api[prefix]))
                    return
            route.continue_()

        page.route("**/api/**", api_route)
        if not fixed:
            page.route("**/static/js/utils/file-name.js*", lambda route: route.fulfill(
                status=200, content_type="application/javascript", body=PLAIN_FILE_NAME_JS))
        page.goto(f"{admin_live_server.base_url}{path}", wait_until="load")
        if action:
            page.evaluate(action)
        page.locator(selector).first.wait_for(state="attached")
        text = page.locator(selector).first.evaluate("(el) => el.textContent.trim()")
        shape = _shape(page, selector)
        assert not errors, errors
    assert text == SHORT_SPLIT, text
    if fixed:
        assert shape == SPLIT_RIGHT, shape
    else:
        assert not shape["dot_left_of_tail"], f"בקרה: {shape}"


def test_a_file_name_with_quotes_is_shown_whole_in_a_collection_card(admin_live_server, chromium_executable):
    """בכרטיס של אוסף השם נקרא מ-``data-open`` (``fillCardNames`` ב-``collections.js``), והמאפיין נבנה ב-``escapeHtml`` של
    אותו קובץ. בלי קידוד של מרכאות, שם עם ``"`` היה נחתך במאפיין — ונחתך גם בכרטיס, וגם בפתיחה."""
    api = {"/api/collections/c1/items": {"ok": True, "items": [{"source": "regular", "file_name": QUOTED_NAME, "id": "i1"}],
                                         "total": 1, "page": 1, "per_page": 20},
           "/api/collections/c1": {"ok": True, "collection": _COLLECTION},
           "/api/collections": {"ok": True, "collections": [_COLLECTION]}}
    prefixes = sorted(api, key=len, reverse=True)
    with _browser(chromium_executable) as browser:
        context = browser.new_context(viewport={"width": 1280, "height": 900}, locale="he-IL")
        context.add_cookies([{"name": "session", "value": admin_live_server.session_cookie,
                              "domain": "127.0.0.1", "path": "/"}])
        page = context.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))

        def api_route(route):
            url_path = urlsplit(route.request.url).path
            for prefix in prefixes:
                if url_path.startswith(prefix):
                    route.fulfill(status=200, content_type="application/json", body=json.dumps(api[prefix]))
                    return
            route.continue_()

        page.route("**/api/**", api_route)
        page.goto(f"{admin_live_server.base_url}/collections/c1", wait_until="load")
        link = page.locator(".collection-card__link").first
        link.wait_for(state="attached")
        text = link.evaluate("(el) => el.textContent")
        data_open = link.get_attribute("data-open")
        attrs = link.evaluate("(el) => el.getAttributeNames()")
        assert not errors, errors
    assert data_open == QUOTED_NAME, data_open
    assert text == QUOTED_NAME, text
    assert "onmouseover" not in attrs, attrs
