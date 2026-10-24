"""תפריט ⋮ בעמודים האמיתיים — הלוח ודפדפן הריפו — במגע של טאבלט, מול הוובאפ האמיתי.

**למה בנוסף לעמוד הסינתטי** (``tests/test_sticky_note_menu_browser.py``). שם המשטח אינו חותך,
וכאן כן: ``.board-surface`` הוא ``overflow: auto`` (``note-boards.css``), ו-``#code-viewer-container``
הוא ``overflow: hidden`` (``repo-browser.css``). ``_noteMenuBounds`` גוזר מה-CSS את מי שחותך את
הפתק, ולכן רק העמוד האמיתי בודק את הענף שבו הוא חותך — יחד עם ה-CSS של העמוד, הערכה,
והמנהל כפי שהעמוד מרכיב אותו.

**מה נמדד בבניית הקובץ** (כרומיום 153, טאבלט 1280×800): בדפדפן הריפו המסגרת נמשכת **מתחת**
לתחתית המסך (``bottom`` ‏844), ולכן שם המסך הוא שקובע; בלוח המשטח נגמר מעט מעל התחתית,
ושם המשטח קובע.

**רק ה-API מזויף**, כמו ב-``tests/test_repo_notes_browser.py``: רשימת הלוחות, הפתקים, ובדפדפן
הריפו גם העץ והקובץ. אין כאן מסד.

**מה לא נבדק כאן:** טאבלט אמיתי — זו אמולציית מגע בכרומיום.

מדולג כשאין Chromium (וב-CI אין: ראו ``docs/testing.rst``).
"""

from __future__ import annotations

import contextlib
import json
from urllib.parse import urlsplit

import pytest

# ``tests`` אינו חבילה — ראה את ה-docstring של ``tests/conftest.py``.
from _browser_harness import poll

pytest.importorskip("playwright", reason="playwright אינו מותקן")

from playwright.sync_api import sync_playwright  # noqa: E402

from test_repo_notes_browser import CODE_PATH, LANDSCAPE, FakeRepoApi, code_file, repo_note, repo_page  # noqa: E402
from test_sticky_note_menu_browser import EDGE_GAP, MENU_JS  # noqa: E402

BOARD = "b1"


def board_note(nid: str, *, y: int, minimized: bool = False) -> dict:
    """פתק לוח בצורה שהשרת מחזיר ברשימה."""
    return {"id": nid, "board_id": BOARD, "content": "תוכן", "title": "",
            "position": {"x": 300, "y": y}, "size": {"width": 360, "height": 260},
            "color": "#FFFFCC", "mode": "surface", "is_minimized": minimized}


@contextlib.contextmanager
def board_page(server, executable, notes):
    """עמוד ``/boards/b1`` האמיתי במגע של טאבלט — **המקום היחיד בקובץ שמרים דפדפן ללוח**."""
    def handle(route):
        url = urlsplit(route.request.url)
        if url.hostname != "127.0.0.1":
            route.abort()
        elif url.path == "/api/note-boards":
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps({"ok": True, "boards": [{"id": BOARD, "name": "לוח"}]}))
        elif url.path == f"/api/sticky-notes/board/{BOARD}":
            route.fulfill(status=200, content_type="application/json", body=json.dumps({"ok": True, "notes": notes}))
        else:
            route.continue_()

    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(executable_path=executable,
                                         args=[f"--window-size={LANDSCAPE['width']},{LANDSCAPE['height']}"])
        except Exception as exc:  # pragma: no cover - תלוי בסביבה
            pytest.skip(f"אין Chromium זמין: {exc}")
        try:
            context = browser.new_context(viewport=LANDSCAPE, device_scale_factor=2, is_mobile=True,
                                          has_touch=True, locale="he-IL")
            context.add_cookies([{"name": "session", "value": server.session_cookie,
                                  "domain": "127.0.0.1", "path": "/"}])
            page = context.new_page()
            page.route("**/*", handle)
            page.goto(f"{server.base_url}/boards/{BOARD}", wait_until="load")
            for n in notes:
                page.wait_for_selector(f'#boardSurface .sticky-note[data-note-id="{n["id"]}"]', timeout=20000)
            yield page
        finally:
            browser.close()


def tap_menu(page, nid):
    page.tap(f'.sticky-note[data-note-id="{nid}"] .sticky-note-more')
    page.wait_for_selector(f'.sticky-note[data-note-id="{nid}"] .sticky-note-menu')
    return page.evaluate(MENU_JS, nid)


#: המלבן של ה-client של אלמנט — מה שהוא חותך — בקואורדינטות החלון.
CLIENT_BOX_JS = """(sel) => { const e = document.querySelector(sel); const r = e.getBoundingClientRect();
  const left = r.left + e.clientLeft, top = r.top + e.clientTop;
  return { left, top, right: left + e.clientWidth, bottom: top + e.clientHeight }; }"""


def assert_inside(m, box):
    menu = m["menu"]
    assert (menu["left"] >= box["left"] + EDGE_GAP - 0.5 and menu["right"] <= box["right"] - EDGE_GAP + 0.5
            and menu["top"] >= box["top"] + EDGE_GAP - 0.5 and menu["bottom"] <= box["bottom"] - EDGE_GAP + 0.5), (m, box)
    assert m["hitsItem"], f"הפריט אינו מצויר למעלה: {m}"


def visible_box(page, sel):
    """החיתוך של אזור התצוגה עם תיבת ה-client של ``sel``."""
    box = page.evaluate(CLIENT_BOX_JS, sel)
    vw, vh = page.evaluate("() => [document.documentElement.clientWidth, window.innerHeight]")
    return {"left": max(0, box["left"]), "top": max(0, box["top"]),
            "right": min(vw, box["right"]), "bottom": min(vh, box["bottom"])}


# ---------------------------------------------------------------------------
# הלוח
# ---------------------------------------------------------------------------

def test_on_the_board_the_menu_opens_down_and_the_bell_opens_the_reminder_window(admin_live_server, chromium_executable):
    with board_page(admin_live_server, chromium_executable, [board_note("top", y=40)]) as page:
        m = tap_menu(page, "top")
        assert not m["above"] and m["menu"]["top"] >= m["more"]["bottom"], m
        assert_inside(m, visible_box(page, "#boardSurface"))
        page.tap('.sticky-note[data-note-id="top"] .sticky-note-menu-item[data-menu-item="reminder"]')
        page.wait_for_selector(".sticky-reminder-modal")
        assert page.evaluate(MENU_JS, "top")["menu"] is None


def test_on_the_board_a_minimized_note_at_the_bottom_opens_the_menu_up(admin_live_server, chromium_executable):
    """פתק ממוזער שהכותרת שלו בתחתית המשטח הגלוי: התפריט היה נחתך בקצה המשטח, ולכן נפתח כלפי מעלה."""
    with board_page(admin_live_server, chromium_executable, []) as page:
        surface = page.evaluate(CLIENT_BOX_JS, "#boardSurface")
        y = round(surface["bottom"] - surface["top"]) - 70
        page.evaluate("""([y]) => window._boardNotes._renderNote({ id: 'low', board_id: 'b1', content: 'תוכן',
            title: '', position: { x: 300, y }, size: { width: 360, height: 260 }, color: '#FFFFCC',
            mode: 'surface', is_minimized: true })""", [y])
        poll(page, """() => { const n = document.querySelector('.sticky-note[data-note-id="low"]');
                              return !!n && n.getAnimations().every((a) => a.playState === 'finished'); }""",
             "הפתק התייצב")
        box = visible_box(page, "#boardSurface")
        more = page.evaluate(MENU_JS, "low")["more"]
        assert box["bottom"] - more["bottom"] < 60, f"בקרה: ⋮ אמור לשבת בתחתית המשטח הגלוי: {more}, {box}"
        m = tap_menu(page, "low")
        assert m["above"] and m["menu"]["bottom"] <= m["more"]["top"], m
        assert_inside(m, box)


# ---------------------------------------------------------------------------
# דפדפן הריפו
# ---------------------------------------------------------------------------

#: גולל את הקוד כך שהכותרת של הפתק תשב ``from_bottom`` פיקסלים מעל תחתית המסך.
SCROLL_NOTE_TO_BOTTOM_JS = """([nid, fromBottom]) => {
  const sc = document.querySelector('#code-viewer-container .cm-scroller');
  const n = document.querySelector(`.sticky-note[data-note-id="${nid}"]`);
  sc.scrollTop += n.getBoundingClientRect().top - (window.innerHeight - fromBottom);
}"""


@pytest.mark.parametrize("where", ["top", "bottom"])
def test_in_the_repo_browser_the_menu_stays_inside_what_is_seen(admin_live_server, chromium_executable, where):
    """המסגרת של דפדפן הריפו חותכת את מה שיוצא ממנה. פתק למעלה — התפריט נפתח כלפי מטה; פתק שהכותרת
    שלו בתחתית החלק הנראה — כלפי מעלה. בשניהם התפריט כולו בתוך מה שרואים, ומצויר מעל הקוד."""
    note = dict(repo_note("r1", y=60 if where == "top" else 1200), is_minimized=where == "bottom")
    api = FakeRepoApi(CODE_PATH, code_file(400), [note])
    with repo_page(admin_live_server, chromium_executable, api, LANDSCAPE) as (page, _touch):
        # ``attached`` ולא ``visible``: בעומק 1200 הפתק עוד מחוץ למה שרואים, עד הגלילה שלמטה.
        page.wait_for_selector('#code-viewer-container .sticky-note[data-note-id="r1"]', state="attached")
        if where == "bottom":
            page.evaluate(SCROLL_NOTE_TO_BOTTOM_JS, ["r1", 50])
            # **עד שהמיקום יציב, ולא רק עד שהגיע.** נמדד בבניית הבדיקה: מיד אחרי הגלילה הפתק
            # הגיע למקום, ו-CodeMirror הזיז את הגלילה שוב כשמדד את השורות שנחשפו — והתפריט נפתח
            # מול מיקום שכבר השתנה. שלוש דגימות זהות ברצף הן הסימן שהגלילה נרגעה.
            poll(page, """() => { const t = Math.round(document.querySelector('.sticky-note[data-note-id="r1"]')
                                    .getBoundingClientRect().top);
                                  const s = window.__noteTops = (window.__noteTops || []).concat(t).slice(-3);
                                  return s.length === 3 && s.every((v) => v === s[0]); }""",
                 "הגלילה נרגעה")
        box = visible_box(page, "#code-viewer-container")
        if where == "bottom":
            more = page.evaluate(MENU_JS, "r1")["more"]
            assert box["bottom"] - more["bottom"] < 60, f"בקרה: ⋮ אמור לשבת בתחתית מה שרואים: {more}, {box}"
        m = tap_menu(page, "r1")
        if where == "bottom":
            assert m["above"] and m["menu"]["bottom"] <= m["more"]["top"], m
        else:
            assert not m["above"] and m["menu"]["top"] >= m["more"]["bottom"], m
        assert_inside(m, box)
