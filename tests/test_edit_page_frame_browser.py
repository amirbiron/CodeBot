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


#: גובה שורת הכפתורים, ומיקום העורך יחסית לשורה — מה שהודעה זמנית אסור לה להזיז.
ROW_AND_EDITOR = (
    "() => ({row: document.querySelector('.editor-switcher-row').getBoundingClientRect().height,"
    " cm: document.querySelector('.codemirror-container').getBoundingClientRect().top"
    " - document.querySelector('.editor-switcher').getBoundingClientRect().top})"
)

#: הכפתורים בשורה שההודעה חופפת להם — לפי ה-``class`` של הראשון בכל כפתור. ``selector`` מצמצם את הבדיקה.
NOTICE_COVERS = """(selector) => {
  const s = document.querySelector('.editor-info-status').getBoundingClientRect();
  return [...document.querySelectorAll(selector)].filter((b) => b.offsetParent).filter((b) => {
    const m = b.getBoundingClientRect();
    const across = Math.min(s.right, m.right) > Math.max(s.left, m.left);
    return across && Math.min(s.bottom, m.bottom) > Math.max(s.top, m.top);
  }).map((b) => b.className.split(' ')[0]);
}"""


#: שורת הכפתורים כפי שהיא על המסך: ``lines`` — השורות מלמעלה למטה, ובכל אחת הכפתורים לפי סדר הקריאה (בעמוד
#: מימין לשמאל — מימין); ``groups`` — לכל פריט בשורה (המתג, הקבוצות, MD, כלי הקוד): השם, אם יש לפניו קו, ואם
#: הוא הראשון בשורה שלו. ``heights`` — הגבהים השונים של כפתורי "בחר הכל" עד "בצע שוב". קו הפרדה הוא קו בתחילת
#: הפריט ורווח לפניו (``.editor-switcher-actions`` ב-``codemirror-custom.css``) — ולא המסגרת של כפתור.
ROW_LAYOUT = """() => {
  const row = document.querySelector('.editor-switcher-actions');
  const rtl = getComputedStyle(row).direction === 'rtl';
  const nameOf = (e) => e.matches('.btn-switch-editor') ? 'switch' : e.matches('.md-toolbar-trigger') ? 'MD'
    : e.closest('.code-tools-group') ? 'tools'
    : (e.className.toString().match(/btn-editor-(select|copy|paste|undo|redo)/) || [])[1];
  const selector = '.btn-switch-editor, .btn-editor-clip, .md-toolbar-trigger,'
    + ' .code-tools-group > .btn, .code-tools-group > a';
  const buttons = [...row.querySelectorAll(selector)]
    .filter((e) => e.getClientRects().length).map((e) => ({n: nameOf(e), box: e.getBoundingClientRect()}));
  const lines = [];
  [...buttons].sort((a, b) => a.box.top - b.box.top).forEach((it) => {
    const line = lines.find((l) => it.box.top < l.bottom && it.box.bottom > l.top);
    if (line) { line.items.push(it); line.bottom = Math.max(line.bottom, it.box.bottom); }
    else lines.push({top: it.box.top, bottom: it.box.bottom, items: [it]});
  });
  const order = (a, b) => rtl ? b.box.right - a.box.right : a.box.left - b.box.left;
  lines.forEach((l) => l.items.sort(order));
  const items = [...row.children].filter((c) => !c.matches('.editor-info-slot') && c.getClientRects().length);
  const groups = items.map((c) => {
    const s = getComputedStyle(c);
    const box = c.getBoundingClientRect();
    const sameLine = items.filter((o) => o !== c).map((o) => o.getBoundingClientRect())
      .filter((o) => o.top < box.bottom && o.bottom > box.top);
    const first = sameLine.every((o) => rtl ? o.right <= box.left + 1 : o.left >= box.right - 1);
    const name = c.matches('.btn-switch-editor') ? 'switch' : c.matches('.editor-clipboard-actions') ? 'clipboard'
      : c.matches('.editor-history-actions') ? 'history' : c.matches('.md-toolbar-group') ? 'MD' : 'tools';
    // קו הפרדה = קו בתחילת הפריט ורווח לפניו. בלי הרווח זו המסגרת של הפריט עצמו (כמו של "עורך פשוט")
    const divider = s.borderInlineStartStyle !== 'none' && parseFloat(s.borderInlineStartWidth) > 0
      && parseFloat(s.marginInlineStart) > 0;
    return {name, divider, first};
  });
  const heights = buttons.filter((b) => ['select', 'copy', 'paste', 'undo', 'redo'].includes(b.n))
    .map((b) => b.box.height);
  return {
    lines: lines.map((l) => l.items.map((i) => i.n).filter((n, i, all) => n !== 'tools' || all[i - 1] !== 'tools')),
    groups, heights: [...new Set(heights.map((h) => Math.round(h * 10) / 10))],
    overflow: document.documentElement.scrollWidth > document.documentElement.clientWidth,
  };
}"""


def _row(page) -> dict:
    """השורה (``ROW_LAYOUT``), אחרי שבדקנו את הכלל של קווי ההפרדה: לכל פריט יש קו לפניו, חוץ מהראשון בכל שורה.

    מחכים קודם שני פריימים: אחרי שינוי ברוחב (תצוגה חיה, חלון) ``watchSwitcherRow`` מסדר מחדש ב-
    ``requestAnimationFrame`` — בכוונה, כי סידור בתוך ה-callback של ``ResizeObserver`` משנה את גובה השורה, שהוא
    עצמו מאזין לה, והדפדפן מדווח על כך כשגיאת "ResizeObserver loop"."""
    page.evaluate(
        "() => new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(done)))"
    )
    layout = page.evaluate(ROW_LAYOUT)
    for group in layout["groups"]:
        assert group["divider"] == (not group["first"]), layout
    return layout


def _set_preview(page, on: bool) -> None:
    """מדליק או מכבה את התצוגה החיה. כשהיא דלוקה, שורת הכפתורים יושבת בחצי של העורך, ולכן היא צרה."""
    state = "() => document.getElementById('livePreviewRoot').classList.contains('is-active')"
    if page.evaluate(state) != on:
        page.click('[data-action="toggle-live-preview"]')
        page.wait_for_function(f"({state})() === {'true' if on else 'false'}", timeout=10000)


def _notice(page) -> None:
    page.click(".btn-editor-select")
    page.wait_for_function(
        "document.querySelector('.editor-info-status').textContent.trim() !== ''"
    )


def test_a_notice_does_not_move_the_editor(edit_page):
    """ההודעה הזמנית צפה ברווח שאחרי הכפתור האחרון בשורה — סרגל ה-MD — ולכן העורך לא זז והיא לא מכסה את כפתור
    ה-MD. עד התיקון הראשון היא ישבה בשורה משלה, שגדלה כשהטקסט הופיע (נמדד כאן: כפיקסל אחד); אחריו — במקום התווית
    "קיצורי מקלדת זמינים", שהוסרה בנובמבר 2026. בלי ההודעה הצפה, ברוחב 820 הודעה הורידה את העורך 31px; ובקצה
    השורה, היכן שהתווית הייתה, היא כיסתה את כפתור ה-MD בכל רוחב (נמדד). כל מצב נקבע כאן במפורש: שורה רחבה
    (התצוגה החיה כבויה), שורה צרה (התצוגה דלוקה, והשורה בחצי של העורך), ודף ברוחב 820. בשורה צרה ההודעה מכסה
    חלק מהכפתור שלפניה — זו ההחלטה של המשתמש — אבל לא את כפתור ה-MD."""
    page = edit_page
    assert page.evaluate(
        "() => !document.querySelector('.editor-switcher').textContent.includes('קיצורי מקלדת')"
    ), 'התווית "קיצורי מקלדת זמינים" הוסרה'
    for preview_on, covered in ((False, ".editor-switcher button"), (True, ".md-toolbar-trigger")):
        _set_preview(page, preview_on)
        # MD אחרון בשורה שלו — אחריו רק הרווח שבו ההודעה צפה
        assert [line[-1] for line in _row(page)["lines"] if "MD" in line] == ["MD"], preview_on
        before = page.evaluate(ROW_AND_EDITOR)
        _notice(page)
        assert page.evaluate(ROW_AND_EDITOR) == before, preview_on
        assert page.evaluate(NOTICE_COVERS, covered) == [], preview_on

    narrow = edit_page.context.new_page()
    try:
        narrow.set_viewport_size({"width": 820, "height": 620})
        narrow.goto(f"{ORIGIN}/edit")
        narrow.wait_for_selector(".cm-editor", timeout=30000)
        before = narrow.evaluate(ROW_AND_EDITOR)
        _notice(narrow)
        assert narrow.evaluate(ROW_AND_EDITOR) == before
        assert narrow.evaluate(NOTICE_COVERS, ".md-toolbar-trigger") == []
    finally:
        narrow.close()


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


def _forget_editor_choice(page) -> None:
    """מוחק את בחירת העורך שהחלפת עורך שמרה. ``savePreference`` ב-``editor-manager.js`` כותב אותה ל-``localStorage``,
    שמשותף לכל הדפים בהקשר של ה-fixture — ודף חדש שנפתח אחרי טסט שעבר לעורך הפשוט עלה בעורך הפשוט, בלי
    ``.cm-editor``. כל טסט שמחליף עורך קורא לזה בסיום."""
    page.evaluate("() => localStorage.removeItem('preferredEditor')")


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
        _forget_editor_choice(page)
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


#: הכפתורים "בטל" ו"בצע שוב": המקום בשורה, המצב, אם הם מוצגים, וכיוון האייקון.
HISTORY_BUTTONS = """() => {
  const group = document.querySelector('.editor-history-actions');
  const undo = group.querySelector('.btn-editor-undo');
  const redo = group.querySelector('.btn-editor-redo');
  const buttons = [...group.querySelectorAll('button')];
  return {
    first: buttons.indexOf(undo) === 0 && buttons.indexOf(redo) === 1,
    shown: [undo, redo].map((b) => b.getClientRects().length > 0),
    disabled: [undo.disabled, redo.disabled],
    icon: getComputedStyle(undo.querySelector('i')).transform,
  };
}"""


def test_undo_and_redo_on_the_edit_page_and_none_in_the_simple_editor(edit_page):
    """בעמוד העריכה הכפתורים עובדים על ההיסטוריה של CodeMirror, כמו בעורך הציבורי, והחץ בתמונת ראי גם כאן — השורה
    מימין לשמאל, גם כשהעורך עצמו משמאל לימין. **בעורך הפשוט הם מוסתרים:** ה"בטל" של הדפדפן הוא מחסנית אחת לכל
    העמוד, ונמדד שהוא ביטל הקלדה בשדה שם הקובץ במקום בעורך (ההסבר ב-``runHistoryCommand`` ב-``editor-manager.js``).
    בחזרה לעורך המתקדם הם שוב מוצגים, ומושבתים — לעורך החדש עוד אין היסטוריה. בדף נפרד באותו הקשר, כדי שהמעבר
    לעורך הפשוט לא יגיע לבדיקות אחרות בקובץ."""
    page = edit_page.context.new_page()
    try:
        page.goto(f"{ORIGIN}/edit")
        page.wait_for_selector(".cm-editor", timeout=30000)
        state = page.evaluate(HISTORY_BUTTONS)
        assert state == {
            "first": True,
            "shown": [True, True],
            "disabled": [True, True],
            "icon": "matrix(-1, 0, 0, 1, 0, 0)",
        }, state

        text = "() => window.editorManager.cmInstance.state.doc.toString()"
        before = page.evaluate(text)
        page.evaluate(
            "() => { const v = window.editorManager.cmInstance;"
            " v.dispatch({changes: {from: v.state.doc.length, insert: '\\nנוסף'}}); }"
        )
        assert page.evaluate(HISTORY_BUTTONS)["disabled"] == [False, True]
        page.click(".btn-editor-undo")
        assert page.evaluate(text) == before
        assert page.evaluate(HISTORY_BUTTONS)["disabled"] == [True, False]
        page.click(".btn-editor-redo")
        assert page.evaluate(text) == before + "\nנוסף"

        page.click(".btn-switch-editor")
        page.wait_for_function("window.editorManager.currentEditor === 'simple'", timeout=10000)
        assert page.evaluate(HISTORY_BUTTONS)["shown"] == [False, False]
        # הקבוצה כולה מוסתרת, ולכן גם הקו שלפניה; MD אחרי "הדבק", עם קו (``_row`` בודק את הקווים)
        page.wait_for_function(
            "() => !document.querySelector('.editor-history-actions').getClientRects().length"
        )
        assert _row(page)["lines"] == [["switch", "select", "copy", "paste", "MD"]]
        # התווית של העורך הפשוט נשארה; רק "קיצורי מקלדת זמינים" של העורך המתקדם הוסרה
        label = (
            "() => { const l = document.querySelector('.editor-info-primary');"
            " return l.hidden ? null : l.textContent.trim(); }"
        )
        assert page.evaluate(label) == "עורך טקסט בסיסי"

        page.click(".btn-switch-editor")
        page.wait_for_function(
            "window.editorManager.currentEditor === 'codemirror' && !!window.editorManager.cmInstance",
            timeout=30000,
        )
        state = page.evaluate(HISTORY_BUTTONS)
        assert state["shown"] == [True, True] and state["disabled"] == [True, True], state
        assert page.evaluate(label) is None
        assert _row(page)["lines"] == [["switch", "select", "copy", "paste", "undo", "redo", "MD"]]
    finally:
        _forget_editor_choice(page)
        page.close()


# ---------------------------------------------------------------------------
# סבב חמישי ושישי (נובמבר 2026): שורת הכפתורים — הסדר, קווי ההפרדה והסידור בשורות — התווית "קוד", והלשוניות
# "עורך" / "תצוגה מקדימה".
# ---------------------------------------------------------------------------

#: התווית של שדה הקוד: הגודל שלה על המסך, ומה קורא מסך מקריא כשם השדה.
CODE_LABEL = """() => {
  const l = document.querySelector('label[for="codeTextarea"]').getBoundingClientRect();
  return {size: [l.width, l.height], of: document.getElementById('codeTextarea').labels[0].textContent.trim()};
}"""


def _page_at(edit_page, width=390):
    page = edit_page.context.new_page()
    page.set_viewport_size({"width": width, "height": 844})
    page.goto(f"{ORIGIN}/edit")
    page.wait_for_selector(".cm-editor", timeout=30000)
    return page


def _set_language(page, language: str, file_name: str) -> None:
    """מחליף שפה ושם קובץ בטופס, כמו משתמש — עם האירועים שהעמוד מאזין להם."""
    page.evaluate(
        """([language, fileName]) => {
          const select = document.getElementById('languageSelect');
          select.value = language;
          select.dispatchEvent(new Event('change', {bubbles: true}));
          const name = document.querySelector('input[name="file_name"]');
          name.value = fileName;
          name.dispatchEvent(new Event('input', {bubbles: true}));
        }""",
        [language, file_name],
    )


#: מספר השורות שבחר ``layoutSwitcherRow`` — נקבע אחרי ``requestAnimationFrame``, ולכן מחכים לו.
ROWS = "() => document.querySelector('.editor-switcher-actions').dataset.rows"


def test_on_a_computer_the_row_is_switch_copy_history_then_md(edit_page):
    """במחשב, מימין לשמאל: "עורך פשוט" | "בחר הכל, העתק, הדבק" | "בטל, בצע שוב" | MD — כל הכפתורים צמודים, קו הפרדה
    בין כל שני פריטים ולא לפני הראשון, וכולם באותו גובה. בקובץ שאינו Markdown אין MD, ובקובץ פייתון כלי הקוד
    באים במקומו. עד נובמבר 2026 "בטל / בצע שוב" ישבו לפני "בחר הכל", בלי קווים, ו-MD בקצה השני של השורה. כשהשורה
    צרה מכדי שהכול ייכנס בשורה אחת — התצוגה החיה דלוקה, או החלון הוקטן — אותו סידור כמו בטלפון: המתג, "בטל /
    בצע שוב" ו-MD למעלה, "בחר הכל / העתק / הדבק" למטה. ``_row`` בודק שאין קו בתחילת שורה."""
    page = _page_at(edit_page, 1000)
    try:
        # שגיאות בחלון לאורך כל השינויים בבדיקה — ובפרט "ResizeObserver loop", שסידור בתוך ה-callback גורם לה
        page.evaluate(
            "() => { window.__rowErrors = [];"
            " window.addEventListener('error', (e) => window.__rowErrors.push(String(e.message))); }"
        )
        layout = _row(page)
        assert layout["lines"] == [
            ["switch", "select", "copy", "paste", "undo", "redo", "MD"]
        ], layout
        assert [g["name"] for g in layout["groups"]] == [
            "switch",
            "clipboard",
            "history",
            "MD",
        ], layout
        assert len(layout["heights"]) == 1, layout
        # הראשון בשורה בלי קו — אבל המסגרת והריפוד שלו נשארים (נמדד בזמן הפיתוח: כלל שאיפס את הקו בתחילת שורה
        # מחק ל"עורך פשוט" את הצד הימני של המסגרת ואת הריפוד שם)
        switch = page.evaluate(
            "() => { const s = getComputedStyle(document.querySelector('.btn-switch-editor'));"
            " return [s.borderInlineStartWidth, s.borderInlineEndWidth, s.paddingInlineStart, s.paddingInlineEnd]; }"
        )
        assert switch[0] == switch[1] and switch[2] == switch[3], switch

        space = (
            "() => parseFloat(getComputedStyle(document.querySelector('.editor-history-actions'))"
            ".marginInlineStart)"
        )
        wide_space = page.evaluate(space)
        _set_preview(page, True)
        page.wait_for_function(f"({ROWS})() !== '1'")
        layout = _row(page)
        assert layout["lines"][0][:3] == ["switch", "undo", "redo"], layout
        assert layout["lines"][-1] == ["select", "copy", "paste"], layout
        # בכמה שורות הרווח סביב הקו קטן יותר — כך MD נכנס לשורה הראשונה כבר ברוחב 390 (ההערה ב-
        # ``codemirror-custom.css``; בבדיקה, בלי אייקונים, הכפתורים צרים מכדי שהרוחב יכריע)
        assert 0 < page.evaluate(space) < wide_space
        _set_preview(page, False)
        page.wait_for_function(f"({ROWS})() === '1'")

        # חלון שהוקטן: הסידור מתעדכן לבד (``ResizeObserver``)
        page.set_viewport_size({"width": 390, "height": 844})
        page.wait_for_function(f"({ROWS})() !== '1'")
        assert _row(page)["lines"][-1] == ["select", "copy", "paste"]
        page.set_viewport_size({"width": 1366, "height": 844})
        page.wait_for_function(f"({ROWS})() === '1'")

        _set_language(page, "text", "notes.txt")
        page.wait_for_function(
            "() => !document.querySelector('.md-toolbar-group').getClientRects().length"
        )
        assert _row(page)["lines"] == [["switch", "select", "copy", "paste", "undo", "redo"]]

        _set_language(page, "python", "tool.py")
        page.wait_for_function(
            "() => document.querySelector('.code-tools-group').getClientRects().length > 0"
        )
        layout = _row(page)
        assert layout["lines"] == [
            ["switch", "select", "copy", "paste", "undo", "redo", "tools"]
        ], layout
        assert [g["name"] for g in layout["groups"]] == [
            "switch",
            "clipboard",
            "history",
            "tools",
        ], layout
        assert page.evaluate("() => window.__rowErrors") == []
    finally:
        page.close()


def test_on_a_phone_the_switch_and_history_come_first_and_the_copy_buttons_below(edit_page):
    """בטלפון: בשורה הראשונה "עורך פשוט" | "בטל, בצע שוב" | MD, ובשנייה "בחר הכל, העתק, הדבק". ברוחב שבו MD לא
    נכנס לשורה הראשונה הוא יורד לשורה משלו, בין השתיים (החלטת המשתמש). בלי קו בתחילת שורה, וכל הכפתורים באותו
    גובה. **הרוחבים כאן אינם אלה של המכשיר:** בבדיקה גופן האייקונים (Font Awesome, מ-CDN) לא נטען, ולכן הכפתורים
    צרים יותר; עם האייקונים MD יורד כבר ב-360 (נמדד). ובאותו דף: התווית "קוד" שמעל העורך מוסתרת מהעין ונשארת
    לקורא מסך."""
    cases = (
        (390, [["switch", "undo", "redo", "MD"], ["select", "copy", "paste"]]),
        (320, [["switch", "undo", "redo"], ["MD"], ["select", "copy", "paste"]]),
    )
    for width, expected in cases:
        page = _page_at(edit_page, width)
        try:
            layout = _row(page)
            assert layout["lines"] == expected, (width, layout)
            assert len(layout["heights"]) == 1 and not layout["overflow"], (width, layout)
            assert page.evaluate(CODE_LABEL) == {"size": [1, 1], "of": "קוד"}, width
        finally:
            page.close()


def test_in_the_simple_editor_the_label_goes_to_the_first_row_with_room(edit_page):
    """בעורך הפשוט יש בקצה השורה תווית, "עורך טקסט בסיסי", והיא תופסת רוחב. ``layoutSwitcherRow`` מציב אותה בשורה
    הראשונה שיש בה מקום — כאן ליד "עורך פשוט" ו-MD — ורק כשאין, בשורה משלה. עד התיקון היא תמיד הייתה אחרונה, ולכן
    ירדה לשורה שלישית גם כשהיה לה מקום למעלה (נמדד, עם אייקונים, ברוחב 460 עד 500: 130px במקום 99px). הרוחב כאן
    אחר, כי בבדיקה האייקונים לא נטענים. בדף נפרד, כדי שהמעבר לעורך הפשוט לא יגיע לבדיקות אחרות בקובץ.
    """
    page = _page_at(edit_page, 420)
    try:
        page.click(".btn-switch-editor")
        page.wait_for_function("window.editorManager.currentEditor === 'simple'", timeout=10000)
        page.wait_for_function("() => !document.querySelector('.editor-info-primary').hidden")
        assert _row(page)["lines"] == [["switch", "MD"], ["select", "copy", "paste"]]
        beside_switch = page.evaluate(
            """() => { const label = document.querySelector('.editor-info-primary').getBoundingClientRect();
              const switchBtn = document.querySelector('.btn-switch-editor').getBoundingClientRect();
              return label.top < switchBtn.bottom && label.bottom > switchBtn.top; }"""
        )
        assert beside_switch
    finally:
        _forget_editor_choice(page)
        page.close()


DIVIDER = """(selector) => {
  const g = document.querySelector(selector);
  const box = g.getBoundingClientRect();
  const s = getComputedStyle(g);
  const rtl = getComputedStyle(g.parentElement).direction === 'rtl';
  const w = parseFloat(s.borderInlineStartWidth) || 0;
  return {x: rtl ? box.right - w / 2 : box.left + w / 2, outside: rtl ? 3 : -3,
          top: box.top + 4, bottom: box.bottom - 4};
}"""


def test_the_dividers_show_also_in_a_light_theme(edit_page):
    """קו ההפרדה בצבע הטקסט של השורה, בעוצמה נמוכה, ולכן הוא נראה בכל ערכה. עד נובמבר 2026 היה רק קו אחד, לפני
    MD, לבן ב-15%: ב-Rose Pine Dawn ניגודיות 1.03 מול הרקע — לא נראה; עכשיו 1.69 (נמדד בדגימת פיקסלים, כמו
    כאן)."""
    import io
    import statistics

    from PIL import Image

    page = _page_at(edit_page, 1100)
    try:
        page.evaluate("() => document.documentElement.setAttribute('data-theme', 'rose-pine-dawn')")
        page.wait_for_timeout(250)
        shot = Image.open(io.BytesIO(page.screenshot())).convert("RGB")
        dpr = 2  # ה-``device_scale_factor`` של ההקשר ב-``edit_page``
        for selector in (
            ".editor-clipboard-actions",
            ".editor-history-actions",
            ".md-toolbar-group",
        ):
            d = page.evaluate(DIVIDER, selector)
            ys = range(round(d["top"] * dpr), round(d["bottom"] * dpr))

            def column(x, ys=ys):
                return tuple(
                    statistics.median(shot.getpixel((round(x * dpr), y))[i] for y in ys)
                    for i in range(3)
                )

            line, beside = column(d["x"]), column(d["x"] + d["outside"])
            assert _contrast(line, beside) >= 1.5, (selector, line, beside)
    finally:
        page.close()


#: ערכות מיובאות לדוגמה — המשתנים שהמפרסר מייצר, על ``:root`` (כמו הבלוק ``user-custom-theme`` של ``base.html``).
LIGHT_IMPORTED = (
    "--bg-primary:#f5efe6;--bg-secondary:#efe6d8;--bg-tertiary:#e8dcc8;--text-primary:#3b2f2a;"
    "--text-secondary:#6b5a50;--primary:#8a5a44;--glass:rgba(0,0,0,.04);--glass-border:rgba(0,0,0,.12)"
)
DARK_IMPORTED = (
    "--bg-primary:#1e1e1e;--bg-secondary:#252526;--bg-tertiary:#2d2d30;--text-primary:#d4d4d4;"
    "--text-secondary:#a0a0a0;--primary:#569cd6;--glass:rgba(255,255,255,.04);--glass-border:rgba(255,255,255,.12)"
)
TAB_THEMES = [
    ("classic", None),
    ("dark", None),
    ("forest", None),
    ("rose-pine-dawn", None),
    ("high-contrast", None),
    ("custom", LIGHT_IMPORTED),
    ("custom", DARK_IMPORTED),
]

TABS = """() => {
  const list = document.querySelector('.split-tabs');
  return [...list.querySelectorAll('[role=tab]')].map((t) => {
    const s = getComputedStyle(t);
    return {text: t.textContent.trim(), shown: !!t.offsetParent, selected: t.getAttribute('aria-selected') === 'true',
            color: s.color, listColor: getComputedStyle(list).color, opacity: s.opacity, weight: s.fontWeight,
            shadow: s.boxShadow, border: parseFloat(s.borderBottomWidth) || 0};
  });
}"""


def _rgb(css: str) -> tuple[float, float, float]:
    import re

    nums = [float(v) for v in re.findall(r"[\d.]+", css)]
    return tuple(nums[:3])


def _contrast(a, b) -> float:
    def lum(c):
        def f(v):
            v /= 255
            return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

        return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2])

    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _tab_pixels(page, border: float):
    """הרקע של הלשונית הנבחרת והקו שבתחתיתה, כפי שהם בצילום: חציון של שורת פיקסלים ליד הקצה העליון (מעל הטקסט),
    ושל שורה בתוך שלושת הפיקסלים התחתונים שמעל המסגרת — הקו (``box-shadow`` פנימי) מצויר בתוך המסגרת, ובניגודיות
    גבוהה יש לכפתור מסגרת לבנה. לא מחשבים את הרקע מה-CSS: בערכה Classic יש מאחורי הלשוניות מעבר צבעים, ושכבות
    שקופות מעליו."""
    import io
    import statistics

    from PIL import Image

    shot = Image.open(
        io.BytesIO(page.locator('.split-tabs [aria-selected="true"]').screenshot())
    ).convert("RGB")
    w, h = shot.size
    dpr = 2  # ה-``device_scale_factor`` של ההקשר ב-``edit_page``

    def row(y):
        px = [shot.getpixel((x, y)) for x in range(8 * dpr, w - 8 * dpr)]
        return tuple(statistics.median(p[i] for p in px) for i in range(3))

    return row(round((border + 3) * dpr)), row(round(h - (border + 1.5) * dpr))


def test_on_a_phone_the_tabs_come_with_the_preview_and_the_selected_one_stands_out_in_every_theme(
    edit_page,
):
    """הלשוניות מופיעות רק כשהתצוגה החיה דלוקה, והשנייה נקראת בקובץ Markdown "תצוגה מקדימה" ובקובץ HTML "תצוגה
    חיה" (נובמבר 2026, החלטת המשתמש; הכיתוב מתעדכן כשמשנים שפה). הנבחרת מסומנת בכל ערכה, גם מיובאת:
    הטקסט בצבע של שורת הכלים, מודגש, וקו תחתון באותו צבע — ולכן הקו נראה בכל מקום שבו הטקסט נקרא. הלא נבחרת באותו
    צבע, בלי קו ובלי דהייה. **הבאג:** הנבחרת קיבלה את צבע הטקסט של התצוגה החיה, כמעט לבן, ובערכה בהירה היא כמעט
    נעלמה — ניגודיות 1.42 ב-Rose Pine Dawn (נמדד); ובניגודיות גבוהה שתי הלשוניות נראו אותו דבר. הלשוניות גם הוצגו
    כשהתצוגה כבויה, ו"תצוגה חיה" פתחה פאנל ריק."""
    page = _page_at(edit_page)
    try:
        _set_preview(page, False)
        assert [t["shown"] for t in page.evaluate(TABS)] == [False, False]
        _set_preview(page, True)
        tabs = page.evaluate(TABS)
        assert [t["text"] for t in tabs] == ["עורך", "תצוגה מקדימה"], tabs
        assert [t["shown"] for t in tabs] == [True, True], tabs
        _set_language(page, "html", "page.html")
        assert [t["text"] for t in page.evaluate(TABS)] == ["עורך", "תצוגה חיה"]
        _set_language(page, "markdown", "notes.md")
        assert [t["text"] for t in page.evaluate(TABS)] == ["עורך", "תצוגה מקדימה"]

        for theme, variables in TAB_THEMES:
            page.evaluate(
                """([t, v]) => { const r = document.documentElement; r.setAttribute('data-theme', t);
                  if (t === 'custom') r.setAttribute('data-theme-type', 'custom');
                  else r.removeAttribute('data-theme-type');
                  r.style.cssText = v || ''; }""",
                [theme, variables],
            )
            page.wait_for_timeout(250)  # ה-``transition`` של הרקע
            selected, other = page.evaluate(TABS)
            name = (
                theme
                if variables is None
                else ("imported-light" if variables == LIGHT_IMPORTED else "imported-dark")
            )
            assert selected["selected"] and not other["selected"], name
            assert (selected["weight"], other["weight"]) == ("700", "400"), (name, selected, other)
            assert "inset" in selected["shadow"] and selected["shadow"].startswith(
                selected["color"]
            ), (name, selected)
            assert other["shadow"] == "none" and other["opacity"] == "1", (name, other)
            bg, line = _tab_pixels(page, selected["border"])
            assert _contrast(line, bg) >= 3, (name, bg, line)
            if theme == "high-contrast":
                # הפוכה: לבן, ושחור עליו (``--split-tabs-selected-*`` של הערכה)
                assert bg == (255, 255, 255) and _rgb(selected["color"]) == (0, 0, 0), (
                    name,
                    bg,
                    selected,
                )
            else:
                assert selected["color"] == selected["listColor"] == other["color"], (
                    name,
                    selected,
                    other,
                )
            if theme == "rose-pine-dawn":
                assert _contrast(_rgb(selected["color"]), bg) >= 4.5, (name, bg, selected)
    finally:
        page.close()
