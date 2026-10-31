"""עמוד העריכה בדפדפן אמיתי: נגיעה במסגרת של העורך, וההודעה הזמנית בשורת הכפתורים.

התיקונים יושבים בקבצים המשותפים לכל עמודי העורך (``split-view.css``, ``editor-manager.js`` ו-
``codemirror-custom.css``), ונמדדו קודם בעורך הציבורי (``tests/test_markdown_editor_browser.py``). כאן הם
נבדקים בעמוד העריכה, כי שם הם נראים במלואם:

- **המסגרת.** בעמוד העריכה העורך משמאל לימין, ושורות הטקסט נמשכות עד הצד הימני שלו. נגיעה במסגרת שמימין
  לעורך — הריפוד של הפאנל, או הגבול של ה-Split View — הכניסה את הסמן לטקסט, ובנייד פתחה מקלדת: Chrome מציב את
  הסמן בטקסט הקרוב לנגיעה. בעורך הציבורי אין מסגרת כזו: מאז שהוסרו שם מספרי השורות (אוקטובר 2026) הטקסט מתחיל
  9px מהגבול של ה-Split View (נמדד בחלון 1000x620), וכל נגיעה בטווח הזה נכנסת לעורך — כמו נגיעה ליד כל שדה טקסט.
  לכן הבדיקה של המנגנון כאן, בעמוד שבו המסגרת רחבה.
- **ההודעה הזמנית** ("כל הקוד סומן"). היא מופיעה במקום התווית שבשורת הכפתורים, ולכן העורך לא זז.

העמוד מרונדר מ-``edit_file.html`` עם ``render_template`` ונתוני דוגמה, בלי מסד: ``get_db`` זורק, ו-
``inject_globals`` ממשיך בלי מסמך משתמש, כמו בכל כשל מסד. מדולג כשאין Chromium.
"""

from __future__ import annotations

from urllib.parse import urlsplit

import pytest

pytest.importorskip("playwright", reason="playwright אינו מותקן")

from playwright.sync_api import sync_playwright  # noqa: E402

HOST = "ck.test"
ORIGIN = f"https://{HOST}"
CODE = "# כותרת\n\n" + "\n\n".join(
    f"line {i} with some text that runs to the right edge" for i in range(40)
)


def _render_edit_page(wa) -> str:
    from flask import render_template, session

    user = {"id": 1, "first_name": "x", "username": "x"}
    file = {
        "id": "1",
        "file_name": "notes.md",
        "language": "markdown",
        "description": "",
        "tags": [],
        "is_large": False,
        "source_url": "",
    }
    with wa.app.test_request_context("/edit/1"):
        session["user_id"] = 1
        session["user_data"] = user
        return render_template(
            "edit_file.html",
            user=user,
            file=file,
            code_value=CODE,
            languages=["python", "markdown"],
            existing_images=[],
            error=None,
            success=None,
        )


@pytest.fixture(scope="module")
def edit_page(chromium_executable):
    import webapp.app as wa

    def _no_db(*args, **kwargs):
        raise RuntimeError("no database in this test")

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(wa, "get_db", _no_db)
        html = _render_edit_page(wa)
        client = wa.app.test_client()
        with sync_playwright() as pw:
            try:
                browser = (
                    pw.chromium.launch(executable_path=chromium_executable)
                    if chromium_executable
                    else pw.chromium.launch()
                )
            except Exception as exc:  # כשל חולף בהרמה, אחרי שהשער כבר אמר שיש דפדפן
                pytest.skip(f"Chromium לא עלה: {exc}")
            ctx = browser.new_context(
                viewport={"width": 1000, "height": 620},
                device_scale_factor=2,
                is_mobile=True,
                has_touch=True,
            )
            # https: הלוח (``navigator.clipboard``) זמין רק בהקשר מאובטח, וכפתור "הדבק" קורא ממנו
            ctx.grant_permissions(["clipboard-read", "clipboard-write"], origin=ORIGIN)

            def handle(route):
                u = urlsplit(route.request.url)
                if u.hostname != HOST:
                    return route.abort()
                if u.path == "/edit":
                    return route.fulfill(
                        status=200, body=html, content_type="text/html; charset=utf-8"
                    )
                r = client.get(u.path + (f"?{u.query}" if u.query else ""))
                route.fulfill(
                    status=r.status_code,
                    body=r.data,
                    headers={k: v for k, v in r.headers.items() if k.lower() == "content-type"},
                )

            ctx.route("**/*", handle)
            page = ctx.new_page()
            page.goto(f"{ORIGIN}/edit")
            page.wait_for_selector(".cm-editor", timeout=30000)
            try:
                yield page
            finally:
                browser.close()


def test_tapping_the_frame_beside_the_editor_does_not_put_the_caret_in_it(edit_page):
    page = edit_page
    page.click('[data-action="toggle-live-preview"]')
    page.wait_for_function(
        "document.querySelector('[data-preview-status]').dataset.state === 'ready'", timeout=30000
    )
    page.evaluate(
        "() => document.getElementById('livePreviewRoot').scrollIntoView({block: 'start'})"
    )
    geo = page.evaluate(
        """() => {
      const q = (sel) => document.querySelector(sel).getBoundingClientRect();
      return {root: q('#livePreviewRoot'), panel: q('.split-panel--editor'), cm: q('.codemirror-container')};
    }"""
    )
    y = int(min(geo["cm"]["y"] + 60, 600))
    assert (
        page.evaluate("() => getComputedStyle(document.querySelector('.cm-content')).direction")
        == "ltr"
    )

    points = {
        "split-view border": int(geo["root"]["x"] + geo["root"]["width"] - 1),
        "editor panel padding": int(geo["panel"]["x"] + geo["panel"]["width"] - 4),
    }
    for name, x in points.items():
        page.evaluate("() => document.activeElement && document.activeElement.blur()")
        page.touchscreen.tap(x, y)
        page.wait_for_timeout(250)
        editable = page.evaluate(
            "() => { const a = document.activeElement;"
            " return !!a && (a.isContentEditable || a.tagName === 'TEXTAREA'); }"
        )
        assert not editable, f"נגיעה ב-{name} ({x}, {y}) הכניסה את הסמן לעורך"

    # בקרה: נגיעה בטקסט עצמו כן נכנסת לעורך — אחרת הבדיקה הייתה עוברת גם על עורך שאינו מגיב
    page.touchscreen.tap(int(geo["cm"]["x"] + 120), y)
    page.wait_for_timeout(250)
    assert page.evaluate("() => document.activeElement.isContentEditable")


def test_a_notice_does_not_move_the_editor(edit_page):
    """ההודעה מופיעה במקום התווית "קיצורי מקלדת זמינים", ולכן העורך לא זז. עד התיקון היא ישבה בשורה משלה,
    שגדלה כשהטקסט הופיע (נמדד כאן: כפיקסל אחד), וכששורת הכפתורים נשברת לכמה שורות — שורה שלמה."""
    page = edit_page
    before = page.evaluate(
        "() => ({row: document.querySelector('.editor-switcher-row').getBoundingClientRect().height,"
        " cm: document.querySelector('.codemirror-container').getBoundingClientRect().top"
        " - document.querySelector('.editor-switcher').getBoundingClientRect().top})"
    )
    page.click(".btn-editor-select")
    page.wait_for_function(
        "document.querySelector('.editor-info-status').textContent.trim() !== ''"
    )
    after = page.evaluate(
        "() => ({row: document.querySelector('.editor-switcher-row').getBoundingClientRect().height,"
        " cm: document.querySelector('.codemirror-container').getBoundingClientRect().top"
        " - document.querySelector('.editor-switcher').getBoundingClientRect().top})"
    )
    assert after == before, (before, after)


# ---------------------------------------------------------------------------
# סבב שלישי (אוקטובר 2026). הדף משותף לכל הבדיקות בקובץ, ולכן כל בדיקה כאן קובעת לעצמה את המסמך ואת מצב
# התצוגה, ולא נשענת על מה שבדיקה קודמת השאירה.
# ---------------------------------------------------------------------------

LONG_DOC = "# התחלה\n\n" + "\n\n".join(f"פסקה {i}" for i in range(150)) + "\n\n# סוף\n"


def _with_preview(page, text):
    page.evaluate(
        "(t) => { const v = window.editorManager.cmInstance;"
        " v.dispatch({changes: {from: 0, to: v.state.doc.length, insert: t}}); }",
        text,
    )
    if not page.evaluate(
        "() => document.getElementById('livePreviewRoot').classList.contains('is-active')"
    ):
        page.click('[data-action="toggle-live-preview"]')
    page.wait_for_function(
        "document.querySelector('[data-preview-status]').dataset.state === 'ready'", timeout=30000
    )
    page.evaluate(
        "() => document.getElementById('livePreviewRoot').scrollIntoView({block: 'start'})"
    )


def test_the_edit_page_keeps_its_gutter_direction_and_toggle(edit_page):
    """מה שהשתנה בעורך הציבורי בלבד נשאר כאן כמו שהיה: מספרי שורות וחיצי קיפול, עורך משמאל לימין, והכפתור
    "Live Preview" עם ``aria-pressed``. ומה שמשותף השתנה גם כאן: בתצוגה החיה אין ``¶``, ואין קו בין הפאנלים.
    """
    page = edit_page
    _with_preview(page, "# כותרת\n\n## משנה\n\nטקסט\n")
    state = page.evaluate(
        """() => ({
      numbers: document.querySelectorAll('.cm-lineNumbers').length,
      fold: document.querySelectorAll('.cm-foldGutter').length,
      direction: getComputedStyle(document.querySelector('.cm-content')).direction,
      pressed: document.querySelector('.split-toggle').getAttribute('aria-pressed'),
      label: document.querySelector('.split-toggle__text').textContent.trim(),
      pilcrows: document.querySelectorAll('[data-preview-canvas] .header-anchor').length,
      divider: !!document.querySelector('.split-resizer'),
    })"""
    )
    assert state == {
        "numbers": 1,
        "fold": 1,
        "direction": "ltr",
        "pressed": "true",
        "label": "Live Preview",
        "pilcrows": 0,
        "divider": False,
    }, state


PANEL_HEIGHTS = """() => {
  const h = (s) => Math.round(document.querySelector(s).getBoundingClientRect().height);
  return {panels: h('.split-panels'), editor: h('.codemirror-container'), preview: h('.split-preview-canvas')};
}"""


def test_an_empty_document_keeps_the_panels_full_height(edit_page):
    """מחיקה של כל הטקסט לא מכווצת את העורך ואת התצוגה. עד התיקון הגובה נקבע לפי אורך התוכן: אזור הפאנלים ירד
    מ-560px ל-280px, והעורך מ-369px ל-89px (נמדד בחלון 1100x760)."""
    page = edit_page
    _with_preview(page, LONG_DOC)
    before = page.evaluate(PANEL_HEIGHTS)
    page.evaluate(
        "() => { const v = window.editorManager.cmInstance;"
        " v.dispatch({changes: {from: 0, to: v.state.doc.length, insert: ''}}); }"
    )
    page.wait_for_function(
        "document.querySelector('[data-preview-canvas]').textContent.includes('אין תוכן')",
        timeout=10000,
    )
    assert page.evaluate(PANEL_HEIGHTS) == before, before


SCROLL_STATE = """() => {
  const canvas = document.querySelector('.split-preview-canvas');
  return {editorTop: Math.round(document.querySelector('.cm-scroller').scrollTop),
          previewTop: Math.round(canvas.scrollTop), previewScrolls: canvas.scrollHeight > canvas.clientHeight};
}"""


def test_the_paste_button_over_the_whole_document_shows_its_start(edit_page):
    """כפתור "הדבק" אחרי "בחר הכל" מתנהג כמו הדבקה מהמקלדת: העורך והתצוגה בתחילת המסמך החדש, והסמן שם."""
    page = edit_page
    _with_preview(page, "טקסט קיים\n" * 80)
    page.evaluate("(t) => navigator.clipboard.writeText(t)", LONG_DOC)
    page.evaluate("() => { document.querySelector('.split-preview-canvas').scrollTop = 200; }")
    page.evaluate(
        "() => { const v = window.editorManager.cmInstance;"
        " v.dispatch({selection: {anchor: 0, head: v.state.doc.length}}); }"
    )
    page.click(".btn-editor-paste")
    page.wait_for_function(
        "document.querySelector('[data-preview-canvas]').textContent.includes('פסקה 149')",
        timeout=10000,
    )
    state = page.evaluate(SCROLL_STATE)
    head = page.evaluate("() => window.editorManager.cmInstance.state.selection.main.head")
    assert state["previewScrolls"], "התנאי של הבדיקה: המסמך ארוך מהתצוגה"
    assert head == 0 and state["editorTop"] == 0 and state["previewTop"] == 0, (head, state)


def test_a_paste_over_the_whole_simple_editor_shows_its_start(edit_page):
    """אותו דבר בעורך הפשוט (textarea), בהדבקה אמיתית מהלוח — Ctrl+A ואז Ctrl+V. בדף נפרד באותו הקשר, כדי שהמעבר
    לעורך הפשוט לא יגיע לבדיקות אחרות בקובץ."""
    page = edit_page.context.new_page()
    try:
        page.goto(f"{ORIGIN}/edit")
        page.wait_for_selector(".cm-editor", timeout=30000)
        page.click(".btn-switch-editor")
        page.wait_for_function("window.editorManager.currentEditor === 'simple'", timeout=10000)
        page.click('[data-action="toggle-live-preview"]')
        page.wait_for_function(
            "document.querySelector('[data-preview-status]').dataset.state === 'ready'",
            timeout=30000,
        )
        page.evaluate("(t) => navigator.clipboard.writeText(t)", LONG_DOC)
        page.focus('textarea[name="code"]')
        page.keyboard.press("Control+A")
        page.keyboard.press("Control+V")
        page.wait_for_function(
            "document.querySelector('[data-preview-canvas]').textContent.includes('פסקה 149')",
            timeout=10000,
        )
        state = page.evaluate(
            """() => { const ta = document.querySelector('textarea[name="code"]');
          return {start: ta.selectionStart, end: ta.selectionEnd, top: Math.round(ta.scrollTop),
                  scrolls: ta.scrollHeight > ta.clientHeight,
                  previewTop: Math.round(document.querySelector('.split-preview-canvas').scrollTop)}; }"""
        )
        assert state["scrolls"], "התנאי של הבדיקה: הטקסט ארוך מהעורך"
        assert state["start"] == 0 and state["end"] == 0 and state["top"] == 0, state
        assert state["previewTop"] == 0, state
    finally:
        page.close()


def test_a_swipe_after_dragging_the_seam_does_not_resize_the_panels(edit_page):
    """בין העורך לתצוגה אין קו גרירה. עד התיקון, אחרי גרירה אחת במגע, כל החלקה בתצוגה שינתה את רוחב הפאנלים
    (``pointercancel`` במקום ``pointerup`` השאיר את מאזין התזוזה רשום). מגע אמיתי: גרירה על הגבול, ואחריה החלקה.
    """
    page = edit_page
    _with_preview(page, LONG_DOC)
    width = "() => Math.round(document.querySelector('.split-panel--editor').getBoundingClientRect().width)"
    geo = page.evaluate(
        """() => { const e = document.querySelector('.split-panel--editor').getBoundingClientRect();
      const p = document.querySelector('.split-panel--preview').getBoundingClientRect();
      const [first, second] = e.left < p.left ? [e, p] : [p, e];
      return {seam: (first.right + second.left) / 2, y: e.top + Math.min(e.height / 2, 200),
              previewX: p.left + p.width / 2}; }"""
    )
    before = page.evaluate(width)
    cdp = page.context.new_cdp_session(page)

    def touch(kind, x=0, y=0):
        points = [] if kind == "touchEnd" else [{"x": x, "y": y, "id": 1}]
        cdp.send("Input.dispatchTouchEvent", {"type": kind, "touchPoints": points})

    try:
        x, y = geo["seam"], geo["y"]
        touch("touchStart", x, y)
        page.wait_for_timeout(600)
        for i in range(1, 8):
            touch("touchMove", x + 15 * i, y)
        touch("touchEnd")
        x = geo["previewX"]
        touch("touchStart", x, y + 100)
        for i in range(1, 10):
            touch("touchMove", x + 4 * i, y + 100 - 30 * i)
        touch("touchEnd")
        page.wait_for_timeout(300)
        assert page.evaluate(width) == before
    finally:
        cdp.detach()
