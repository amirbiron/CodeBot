"""העורך הציבורי (``/markdown-editor``) בדפדפן אמיתי: העורך, התצוגה החיה, הטיוטה, הכפתורים וסרגל ה-MD.

**למה בדפדפן.** כמעט כל מה שהעמוד עושה קורה ב-JS: העורך עולה מ-``EditorManager``, התצוגה מתרנדרת ב-
``LivePreviewController``, והטיוטה נשמרת ב-``localStorage``. בדיקת שרת רואה רק את ה-HTML (היא ב-
``tests/test_markdown_editor_page.py``).

**איך העמוד מוגש.** מהאפליקציה האמיתית: כל בקשה של הדפדפן עוברת דרך ``route`` של Playwright ל-``test_client``
של Flask — העמוד מהראוט, הסטטיקה מ-``static``. בקשה לאתר חיצוני (CDN של גופנים ואייקונים) נחסמת, כדי שהטסט
לא ייגע ברשת; העורך והתצוגה נטענים מקבצים מקומיים (``codemirror.local.js``, ``md_preview.bundle.js``). הערכה
הציבורית מוחלפת בערכה מינימלית, כמו ב-``test_markdown_editor_page.py``.

**מה הבדיקות מוכיחות שלא נראה בקוד:**

- שהעמוד לא פונה לשרת עם הטקסט: לא ל-``/api/preview/live`` (גם כשספריית ה-Markdown לא נטענה), ולא לשמירת
  העדפת העורך.
- שהטיוטה משוחזרת **לפני** הרינדור הראשון של התצוגה, ולא אחריו: הרינדור הראשון כבר מציג אותה.
- ש"התראות ▾" נסגר בלחיצה שנייה. בתפריט של עמוד העריכה תפריט המשנה נפתח בפוקוס, ובשורה הפתוחה זה היה משאיר
  אותו פתוח.

מדולג כשאין Chromium (``chromium_executable`` ב-``tests/conftest.py``).
"""

from __future__ import annotations

from urllib.parse import urlsplit

import pytest

pytest.importorskip("playwright", reason="playwright אינו מותקן")

from playwright.sync_api import sync_playwright  # noqa: E402

HOST = "ck.test"
URL = f"http://{HOST}/markdown-editor"
DRAFT_KEY = "markdownEditorDraft.v1"

#: הבקשות שאסור לעמוד לשלוח: התצוגה החיה בשרת, ושמירת העדפת העורך (שתי הכתובות של ``savePreference``).
FORBIDDEN_PATHS = ("/api/preview/live", "/api/ui_prefs", "/api/user/preferences")

FAKE_THEME = {
    "id": "everforest_dark",
    "name": "Everforest Dark",
    "description": "",
    "colors": {"--bg-primary": "#2d353b"},
    "syntax_css": "",
    "syntax_colors": {},
    "is_featured": False,
}

#: מתעד את התוכן של התצוגה ברגע הראשון שהיא "מעודכנת". נרשם לפני הסקריפטים של העמוד, ולכן המאזין שלו
#: ל-DOMContentLoaded רץ לפני שהבקר של התצוגה נבנה.
FIRST_RENDER_PROBE = """
document.addEventListener('DOMContentLoaded', () => {
  const status = document.querySelector('[data-preview-status]');
  const canvas = document.querySelector('[data-preview-canvas]');
  if (!status || !canvas) return;
  new MutationObserver(() => {
    if (status.dataset.state === 'ready' && window.__firstReady === undefined) {
      window.__firstReady = canvas.textContent;
    }
  }).observe(status, { attributes: true, attributeFilter: ['data-state'] });
});
"""


@pytest.fixture(scope="module")
def browser(chromium_executable):
    import webapp.app as wa

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(
            wa,
            "_get_shared_theme_cached",
            lambda theme_id: dict(FAKE_THEME) if theme_id == "everforest_dark" else None,
        )
        with sync_playwright() as pw:
            try:
                b = (
                    pw.chromium.launch(executable_path=chromium_executable)
                    if chromium_executable
                    else pw.chromium.launch()
                )
            except Exception as exc:  # כשל חולף בהרמה, אחרי שהשער כבר אמר שיש דפדפן
                pytest.skip(f"Chromium לא עלה: {exc}")
            try:
                yield b, wa.app.test_client()
            finally:
                b.close()


class Session:
    """הקשר דפדפן אחד: הבקשות שנשלחו, השגיאות, והדף."""

    def __init__(self, browser, client, *, width=1280, height=900, block=(), mobile=False):
        self.requests: list[tuple[str, str]] = []
        self.errors: list[str] = []
        self.ctx = browser.new_context(
            viewport={"width": width, "height": height},
            accept_downloads=True,
            is_mobile=mobile,
            has_touch=mobile,
        )
        self.ctx.add_init_script(FIRST_RENDER_PROBE)

        def handle(route):
            u = urlsplit(route.request.url)
            if u.hostname != HOST or any(u.path.endswith(name) for name in block):
                return route.abort()
            self.requests.append((route.request.method, u.path))
            r = client.open(
                u.path + (f"?{u.query}" if u.query else ""),
                method=route.request.method,
                data=route.request.post_data_buffer,
                headers={"Content-Type": route.request.headers.get("content-type", "")},
            )
            route.fulfill(
                status=r.status_code,
                body=r.data,
                headers={k: v for k, v in r.headers.items() if k.lower() == "content-type"},
            )

        self.ctx.route("**/*", handle)
        self.page = self.ctx.new_page()
        self.page.on("pageerror", lambda exc: self.errors.append(str(exc)))

    def open(self, *, wait_editor=True, wait_preview=True):
        self.page.goto(URL)
        if wait_editor:
            self.page.wait_for_selector(".cm-editor", timeout=30000)
        if wait_preview:
            self.page.wait_for_function(
                "document.querySelector('[data-preview-status]').dataset.state === 'ready'",
                timeout=30000,
            )

    def reload(self):
        self.page.reload()
        self.page.wait_for_selector(".cm-editor", timeout=30000)
        self.page.wait_for_function("window.__firstReady !== undefined", timeout=30000)

    def editor_text(self) -> str:
        return self.page.evaluate("() => window.editorManager.cmInstance.state.doc.toString()")

    def append(self, text: str):
        self.page.evaluate(
            "(t) => { const v = window.editorManager.cmInstance;"
            " v.dispatch({changes: {from: v.state.doc.length, insert: t}}); }",
            text,
        )

    def stored(self):
        return self.page.evaluate(
            f"() => JSON.parse(localStorage.getItem('{DRAFT_KEY}') || 'null')"
        )

    def wait_stored(self, predicate_js: str):
        self.page.wait_for_function(
            f"() => {{ const d = JSON.parse(localStorage.getItem('{DRAFT_KEY}') || 'null');"
            f" return ({predicate_js}); }}",
            timeout=10000,
        )

    def forbidden_requests(self):
        return [r for r in self.requests if r[1] in FORBIDDEN_PATHS]

    def close(self):
        self.ctx.close()


@pytest.fixture
def session(browser):
    b, client = browser
    s = Session(b, client)
    yield s
    s.close()


def test_the_page_runs_the_editor_and_preview_without_the_server(session):
    # מבקר שבחר בעבר בעורך הפשוט בעמוד העריכה: כאן העורך קבוע, וההעדפה שלו לא משתנה
    session.ctx.add_init_script(
        "try { localStorage.setItem('preferredEditor', 'simple'); } catch (_) {}"
    )
    session.open()

    state = session.page.evaluate(
        """() => {
      const canvas = document.querySelector('[data-preview-canvas]');
      const box = (s) => document.querySelector(s).getBoundingClientRect();
      return {
        theme: document.documentElement.getAttribute('data-theme'),
        previewOn: document.getElementById('livePreviewRoot').classList.contains('is-active'),
        canvasId: canvas.id,
        headings: canvas.querySelectorAll('h1').length,
        switchButton: !!document.querySelector('.btn-switch-editor'),
        clipboardButtons: document.querySelectorAll('.btn-editor-clip').length,
        preference: localStorage.getItem('preferredEditor'),
        editorX: box('.split-panel--editor').x,
        previewX: box('.split-panel--preview').x,
        matchesDemo: window.editorManager.cmInstance.state.doc.toString()
          === document.getElementById('codeTextarea').defaultValue,
      };
    }"""
    )

    assert state["theme"] == "shared:everforest_dark"
    assert state["previewOn"], "התצוגה החיה לא נדלקה מעצמה"
    assert state["canvasId"] == "md-content" and state["headings"] >= 1
    assert state["matchesDemo"], "בכניסה הראשונה העורך אמור להציג את טקסט ההדגמה"
    assert not state["switchButton"], "בעורך הציבורי אין מתג עורך"
    assert state["clipboardButtons"] == 3, "בחר הכל / העתק / הדבק נשארים"
    assert state["preference"] == "simple", "העמוד שינה את העדפת העורך של המבקר"
    # בעברית העורך מימין והתצוגה משמאל
    assert state["editorX"] > state["previewX"], state
    assert session.forbidden_requests() == []
    assert session.errors == []

    # הכפתור "Live Preview" נשאר, ומכבה את התצוגה שנדלקה מעצמה
    session.page.click('[data-action="toggle-live-preview"]')
    assert not session.page.evaluate(
        "() => document.getElementById('livePreviewRoot').classList.contains('is-active')"
    )


def test_without_the_markdown_library_the_page_shows_an_error_and_does_not_call_the_server(browser):
    """בעמוד העריכה, כשהרינדור בדפדפן לא זמין, הבקר פונה ל-``/api/preview/live``. כאן אין לאן לפנות — הנתיב
    דורש התחברות — ולכן העמוד מציג שגיאה ולא שולח את הטקסט."""
    b, client = browser
    s = Session(b, client, block=("md_preview.bundle.js",))
    try:
        s.open(wait_preview=False)
        s.page.wait_for_function(
            "document.querySelector('[data-preview-status]').dataset.state === 'error'",
            timeout=30000,
        )
        assert s.forbidden_requests() == []
    finally:
        s.close()


def test_a_draft_comes_back_after_reload_and_is_the_first_thing_the_preview_shows(session):
    session.open()
    session.append("\n\nטיוטה-לבדיקה-7f3a\n")
    session.wait_stored("d && d.code.includes('טיוטה-לבדיקה-7f3a') && Number.isFinite(d.savedAt)")

    session.reload()

    assert "טיוטה-לבדיקה-7f3a" in session.editor_text()
    first = session.page.evaluate("() => window.__firstReady")
    assert "טיוטה-לבדיקה-7f3a" in first, "הרינדור הראשון אחרי הטעינה הציג את ההדגמה ולא את הטיוטה"
    assert session.forbidden_requests() == []


def test_clear_leaves_the_editor_empty_also_on_the_next_visit(session):
    session.open()
    session.page.once("dialog", lambda d: d.accept())
    session.page.click('[data-md-editor-action="clear"]')

    assert session.editor_text() == ""
    session.wait_stored("d && d.code === ''")
    session.page.reload()
    session.page.wait_for_selector(".cm-editor", timeout=30000)
    assert session.editor_text() == ""


def test_load_demo_brings_back_the_demo_and_forgets_the_draft(session):
    session.open()
    session.append("\nמשהו אחר\n")
    session.wait_stored("d && d.code.includes('משהו אחר')")

    messages = []
    session.page.once("dialog", lambda d: (messages.append(d.message), d.accept()))
    session.page.click('[data-md-editor-action="load-demo"]')

    assert messages, "החלפת טקסט שנכתב בהדגמה צריכה אישור"
    demo = session.page.evaluate("() => document.getElementById('codeTextarea').defaultValue")
    assert session.editor_text() == demo
    # ההדגמה אינה טיוטה: היא נמחקת מהאחסון, כדי שהדגמה מעודכנת תגיע בביקור הבא
    session.page.wait_for_function(
        f"() => localStorage.getItem('{DRAFT_KEY}') === null", timeout=10000
    )


def test_download_saves_exactly_what_is_in_the_editor(session):
    session.open()
    session.append("\nשורה אחרונה ✓\n")
    with session.page.expect_download() as info:
        session.page.click('[data-md-editor-action="download"]')
    download = info.value

    assert download.suggested_filename == "document.md"
    with open(download.path(), encoding="utf-8") as fh:
        assert fh.read() == session.editor_text()


def test_the_inline_toolbar_and_the_alerts_menu(session):
    session.open()
    page = session.page
    toolbar = page.evaluate(
        """() => {
      const g = document.querySelector('.md-toolbar-group');
      return {display: getComputedStyle(g).display, trigger: !!document.querySelector('.md-toolbar-trigger'),
              inEditorRow: g.parentElement.classList.contains('editor-switcher-actions')};
    }"""
    )
    assert toolbar == {"display": "flex", "trigger": False, "inEditorRow": False}

    submenu = ".md-toolbar-submenu"
    visible = f"() => getComputedStyle(document.querySelector('{submenu}')).visibility"
    button = '[data-md-action="toggle-submenu"]'

    page.click(button)
    page.wait_for_function(f"({visible})() === 'visible'")
    assert page.get_attribute(button, "aria-expanded") == "true"
    # לחיצה שנייה סוגרת, גם כשהכפתור עדיין בפוקוס
    page.click(button)
    page.wait_for_function(f"({visible})() === 'hidden'")
    assert page.get_attribute(button, "aria-expanded") == "false"

    page.evaluate(
        "() => { const v = window.editorManager.cmInstance;"
        " v.dispatch({selection: {anchor: v.state.doc.length}}); v.focus(); }"
    )
    page.click(button)
    page.click('[data-md-insert="alert:tip"]')
    page.wait_for_function(f"({visible})() === 'hidden'")
    assert "::: tip" in session.editor_text()

    # Escape סוגר
    page.click(button)
    page.wait_for_function(f"({visible})() === 'visible'")
    page.keyboard.press("Escape")
    page.wait_for_function(f"({visible})() === 'hidden'")

    # וגם לחיצה מחוץ לסרגל
    page.click(button)
    page.wait_for_function(f"({visible})() === 'visible'")
    page.click("h1.md-editor-page__title")
    page.wait_for_function(f"({visible})() === 'hidden'")


def test_on_a_phone_nothing_overflows_and_the_alerts_menu_stays_on_screen(browser):
    b, client = browser
    s = Session(b, client, width=390, height=844, mobile=True)
    try:
        s.open()
        s.page.tap('[data-md-action="toggle-submenu"]')
        s.page.wait_for_function(
            "getComputedStyle(document.querySelector('.md-toolbar-submenu')).visibility === 'visible'"
        )
        geo = s.page.evaluate(
            """() => {
          const r = document.querySelector('.md-toolbar-submenu').getBoundingClientRect();
          return {left: r.left, right: r.right, vw: window.innerWidth, docW: document.documentElement.scrollWidth};
        }"""
        )
        assert geo["docW"] <= geo["vw"], geo
        assert geo["left"] >= 0 and geo["right"] <= geo["vw"], geo
    finally:
        s.close()


# ---------------------------------------------------------------------------
# הפריסה, הכיוון והצ'קליסט (אוקטובר 2026 — התיקונים אחרי ההעלאה לאוויר)
# ---------------------------------------------------------------------------

DIRECTION_DOC = (
    "# כותרת\n\n- [x] התקנת ספריות Markdown\n- [Task Lists](#task-lists)\n\n"
    "| ימין | מרכז |\n|-----:|:----:|\n| טקסט | טקסט |\n\n"
    "```python\ndef f(x):\n    return x\n```\n\n    indented code\n\nשורה אחרונה\n"
)

#: הכיוון של שורה בעורך, והמרחק של התו הראשון שלה מהקצה של אזור הטקסט שבו השורה מתחילה. השורה היא הראשונה
#: שמתחילה ב-``prefix``; ``prefix`` שמסתיים ב-``$`` — השורה שזה כל הטקסט שלה.
LINE_START = """(prefix) => {
  const exact = prefix.endsWith('$') ? prefix.slice(0, -1) : null;
  const line = Array.from(document.querySelectorAll('.cm-line'))
    .find((l) => (exact !== null ? l.textContent === exact : l.textContent.startsWith(prefix)));
  if (!line) return null;
  const node = document.createTreeWalker(line, NodeFilter.SHOW_TEXT).nextNode();
  const range = document.createRange();
  range.setStart(node, 0);
  range.setEnd(node, 1);
  const ch = range.getBoundingClientRect();
  const content = document.querySelector('.cm-content').getBoundingClientRect();
  const direction = getComputedStyle(line).direction;
  return {direction, gap: direction === 'rtl' ? content.right - ch.right : ch.left - content.left};
}"""


def _set_editor(page, text):
    page.evaluate(
        "(t) => { const v = window.editorManager.cmInstance;"
        " v.dispatch({changes: {from: 0, to: v.state.doc.length, insert: t}}); }",
        text,
    )


def test_the_editor_is_right_to_left_except_code_blocks(session):
    """כל העורך מימין לשמאל, ורק בלוק קוד — עם הגדרות שלו, או מוזח — משמאל לימין. עד התיקון כל שורה קיבלה את
    הכיוון של האות החזקה הראשונה בה, ולכן ``- [x] משימה`` (x היא אות לטינית), שורת היישור של טבלה (בלי אותיות
    בכלל) וקישור באנגלית בתוכן העניינים יצאו משמאל לימין בתוך מסמך עברי."""
    session.open()
    page = session.page
    _set_editor(page, DIRECTION_DOC)
    page.wait_for_timeout(300)

    for prefix in ("- [x] התקנת", "|-----:|", "- [Task Lists]", "| ימין", "שורה אחרונה"):
        line = page.evaluate(LINE_START, prefix)
        assert line and line["direction"] == "rtl", (prefix, line)
    for prefix in ("```python", "def f(x):", "    return x", "```$", "    indented code"):
        line = page.evaluate(LINE_START, prefix)
        assert line and line["direction"] == "ltr", (prefix, line)


def test_the_editor_has_no_gutter_and_the_text_keeps_off_the_edge(session):
    """בלי מספרי שורות ובלי חיצי קיפול. והטקסט מתחיל 6px מהקצה, בשני הכיוונים: הריווח של CodeMirror לשורה הוא
    ``0 2px 0 6px`` — 6px משמאל — ובעורך מימין לשמאל ההתחלה היא דווקא הצד עם 2px, והטקסט נצמד לגבול.
    """
    session.open()
    page = session.page
    _set_editor(page, DIRECTION_DOC)
    page.wait_for_timeout(300)

    assert page.evaluate("() => document.querySelectorAll('.cm-gutters').length") == 0
    for prefix in ("- [x] התקנת", "def f(x):"):
        line = page.evaluate(LINE_START, prefix)
        assert line and 5 <= line["gap"] <= 8, (prefix, line)


def test_the_editor_and_preview_have_no_dead_rows(session):
    session.open()
    state = session.page.evaluate(
        """() => {
      const box = (s) => { const e = document.querySelector(s); return e ? e.getBoundingClientRect() : null; };
      const toggle = box('.split-toggle'), tools = box('.md-toolbar-group');
      const canvas = box('.split-preview-canvas'), panel = box('.split-panel--preview');
      const first = box('[data-preview-canvas] > :first-child');
      const canvasEl = document.querySelector('.split-preview-canvas');
      return {
        toggleInToolbar: !!document.querySelector('.split-toolbar .split-toggle'),
        toolsInToolbar: !!document.querySelector('.split-toolbar .md-toolbar-group'),
        sameRow: Math.abs((toggle.top + toggle.height / 2) - (tools.top + tools.height / 2)) < 10,
        toggleLeftOfTools: toggle.right <= tools.left,
        labelWidth: box('#editorContainer > label').width,
        separateStatusRow: !!document.querySelector('.editor-info'),
        metaDisplay: getComputedStyle(document.querySelector('[data-preview-meta]')).display,
        statusDisplay: getComputedStyle(document.querySelector('[data-preview-status]')).display,
        // הפאנל נושא גבול של פיקסל אחד בצד שלו (border-inline-start), ולכן ההשוואה היא לרוחב שבתוך הגבול
        canvasFillsPanel: Math.abs(canvas.left - panel.left) < 1
          && Math.abs(canvas.width - document.querySelector('.split-panel--preview').clientWidth) < 1,
        firstGap: first.top - canvas.top,
        canvasPadTop: parseFloat(getComputedStyle(canvasEl).paddingTop),
        card: !!document.querySelector('.md-editor-page__card'),
      };
    }"""
    )

    assert state["toggleInToolbar"] and state["toolsInToolbar"]
    assert state["sameRow"], "Live Preview אמור לשבת בשורה של כלי ה-MD"
    assert state["toggleLeftOfTools"], "Live Preview בקצה השמאלי של השורה"
    assert state["labelWidth"] <= 1, "התווית של העורך מוסתרת ויזואלית"
    assert not state["separateStatusRow"], "אין שורה נפרדת להודעה הזמנית"
    assert state["metaDisplay"] == "none" and state["statusDisplay"] == "none"
    # פס הגלילה של התצוגה על קצה הפאנל: מי שגולל הוא ה-canvas, והוא ממלא את הפאנל
    assert state["canvasFillsPanel"], state
    # בלי margin מעל האלמנט הראשון: הרווח הוא רק הריפוד של ה-canvas
    assert abs(state["firstGap"] - state["canvasPadTop"]) < 1, state
    assert not state["card"]


def test_a_notice_in_the_editor_row_does_not_move_the_editor(session):
    session.open()
    page = session.page
    before = page.evaluate(
        "() => ({row: document.querySelector('.editor-switcher-row').getBoundingClientRect().height,"
        " cm: document.querySelector('.codemirror-container').getBoundingClientRect().top})"
    )
    page.click(".btn-editor-select")
    page.wait_for_function(
        "document.querySelector('.editor-info-status').textContent.trim() !== ''"
    )
    after = page.evaluate(
        """() => {
      const status = document.querySelector('.editor-info-status').getBoundingClientRect();
      const hint = document.querySelector('.editor-info-primary');
      const h = hint.getBoundingClientRect();
      return {
        row: document.querySelector('.editor-switcher-row').getBoundingClientRect().height,
        cm: document.querySelector('.codemirror-container').getBoundingClientRect().top,
        inRow: !!document.querySelector('.editor-switcher-row .editor-info-status'),
        hintHidden: getComputedStyle(hint).visibility === 'hidden',
        // ההודעה יושבת במקום התווית "קיצורי מקלדת זמינים", לא לצידה ולא מתחתיה
        overlaps: status.top < h.bottom && status.bottom > h.top && status.left < h.right && status.right > h.left,
      };
    }"""
    )
    assert after["inRow"] and after["hintHidden"] and after["overlaps"], after
    assert after["row"] == before["row"] and after["cm"] == before["cm"], (before, after)


TASK_DOC = '# משימות\n\n<a id="top"></a>\n\n- [ ] ראשונה\n- [x] שנייה\n\n> - [ ] בציטוט\n\n1. [ ] ממוספרת\n'


def test_clicking_a_task_in_the_preview_changes_its_line_in_the_editor(session):
    """הטקסט הוא מקור האמת: לחיצה בתצוגה משנה את ``[ ]`` / ``[x]`` בשורה הנכונה בעורך. שורת העוגן שמעל
    המשימות מוסרת לפני הפענוח, ולכן מספרי השורות של markdown-it זזים — והטסט מוודא שהשורה בעורך נכונה בכל זאת.
    והפוקוס לא עובר לעורך (בנייד, הוא היה פותח מקלדת)."""
    session.open()
    page = session.page
    page.evaluate("(t) => window.editorManager.setEditorContent(t)", TASK_DOC)
    boxes = "#md-content input.task-list-item-checkbox"
    page.wait_for_function(f"document.querySelectorAll('{boxes}').length === 4")
    assert page.evaluate(
        f"() => Array.from(document.querySelectorAll('{boxes}')).every((b) => !b.disabled)"
    )

    def lines():
        return session.editor_text().split("\n")

    page.locator(boxes).nth(0).click()
    page.wait_for_function("() => window.editorManager.getEditorContent().includes('- [x] ראשונה')")
    assert not page.evaluate("() => document.activeElement.isContentEditable")
    # מחוץ לתצוגה החיה — דפדפן הריפו וכרטיסי החיפוש, שאין להם טקסט לשנות — הצ'קבוקס נשאר לקריאה בלבד
    readonly = page.evaluate(
        """async () => {
      const div = document.createElement('div');
      const rendered = await window.MarkdownLiveRenderer.renderWithAnchors('- [ ] a');
      div.innerHTML = rendered.html;
      await window.MarkdownLiveRenderer.enhance(div, rendered.anchors, {});
      return div.querySelector('input').disabled;
    }"""
    )
    assert readonly
    page.locator(boxes).nth(1).click()
    page.locator(boxes).nth(2).click()
    page.locator(boxes).nth(3).click()
    page.wait_for_function(
        "() => window.editorManager.getEditorContent().includes('1. [x] ממוספרת')"
    )
    assert lines()[4:10] == [
        "- [x] ראשונה",
        "- [ ] שנייה",
        "",
        "> - [x] בציטוט",
        "",
        "1. [x] ממוספרת",
    ]


def test_a_task_click_on_a_stale_preview_does_not_write(session):
    """המיפוי לשורות נכון רק לטקסט שממנו התצוגה רונדרה. כשהטקסט השתנה ועוד לא רונדר מחדש — כאן נוספה משימה
    בראש המסמך — השורה שהצ'קבוקס של "ב" ממופה אליה היא עכשיו "א", ולחיצה הייתה מסמנת את "א". במקום זה היא לא
    כותבת, והצ'קבוקס חוזר למצבו. ואחרי שהתצוגה מתרנדרת מהטקסט החדש, הלחיצה עובדת על השורה הנכונה."""
    session.open()
    page = session.page
    page.evaluate("(t) => window.editorManager.setEditorContent(t)", "- [ ] א\n- [ ] ב\n")
    boxes = "#md-content input.task-list-item-checkbox"
    page.wait_for_function(f"document.querySelectorAll('{boxes}').length === 2")
    page.wait_for_timeout(700)

    page.evaluate(
        "() => { const v = window.editorManager.cmInstance;"
        " v.dispatch({changes: {from: 0, insert: '- [ ] חדש\\n'}});"
        f" document.querySelectorAll('{boxes}')[1].click(); }}"
    )
    assert page.evaluate(f"() => document.querySelectorAll('{boxes}')[1].checked") is False
    assert session.editor_text() == "- [ ] חדש\n- [ ] א\n- [ ] ב\n"

    page.wait_for_function(f"document.querySelectorAll('{boxes}').length === 3")
    page.locator(boxes).nth(2).click()
    page.wait_for_function(
        "() => window.editorManager.getEditorContent() === '- [ ] חדש\\n- [ ] א\\n- [x] ב\\n'"
    )


def test_the_alerts_menu_is_not_clipped_by_the_split_view(browser):
    """שורת הכלים יושבת בראש ה-Split View, וה-Split View חותך את מה שיוצא ממנו (overflow: hidden). במסך נמוך
    תפריט ההתראות ארוך מה-Split View כולו, ובלי ``md-toolbar-open`` החלק התחתון שלו היה נחתך."""
    b, client = browser
    s = Session(b, client, width=1100, height=460)
    try:
        s.open()
        page = s.page
        page.evaluate(
            "() => document.getElementById('livePreviewRoot').scrollIntoView({block: 'start'})"
        )
        page.click('[data-md-action="toggle-submenu"]')
        page.wait_for_function(
            "getComputedStyle(document.querySelector('.md-toolbar-submenu')).visibility === 'visible'"
        )
        geo = page.evaluate(
            """() => {
          const menu = document.querySelector('.md-toolbar-submenu').getBoundingClientRect();
          const root = document.getElementById('livePreviewRoot').getBoundingClientRect();
          window.scrollBy(0, menu.bottom - window.innerHeight + 20);
          const m = document.querySelector('.md-toolbar-submenu').getBoundingClientRect();
          const hit = document.elementFromPoint(m.left + m.width / 2, m.bottom - 12);
          const visible = !!(hit && hit.closest('.md-toolbar-submenu'));
          return {menuBottom: menu.bottom, rootBottom: root.bottom, visible};
        }"""
        )
        # התנאי של הבדיקה: התפריט באמת יוצא מה-Split View
        assert geo["menuBottom"] > geo["rootBottom"], geo
        assert geo["visible"], "החלק התחתון של תפריט ההתראות נחתך"
    finally:
        s.close()


# ---------------------------------------------------------------------------
# סבב שלישי (אוקטובר 2026): התצוגה, הכפתור, הגובה, ההדבקה והקו בין הפאנלים
# ---------------------------------------------------------------------------

HEADINGS_DOC = "# ראשית\n\n## משנה\n\n#### רביעית\n\n##### חמישית\n\n###### שישית\n\nסוף\n"


def _wait_preview_text(page, text):
    page.wait_for_function(
        "(t) => document.querySelector('[data-preview-canvas]').textContent.includes(t)",
        arg=text,
        timeout=10000,
    )


def test_the_preview_has_no_pilcrows_and_shows_h5_h6_as_written(session):
    """בתצוגה החיה אין ``¶`` ליד כותרת, ו-H5 ו-H6 אינן כותרות: הן נשארות כמו שנכתבו, ``##### טקסט``, כפסקה —
    הגופן שלהן היה קטן מטקסט רגיל. H1 עד H4 נשארות כותרות, עם מזהה שקישור בתוכן עניינים קופץ אליו.
    """
    session.open()
    page = session.page
    _set_editor(page, HEADINGS_DOC)
    _wait_preview_text(page, "שישית")
    state = page.evaluate(
        """() => {
      const c = document.querySelector('[data-preview-canvas]');
      return {
        pilcrows: c.querySelectorAll('.header-anchor').length,
        h4: !!c.querySelector('h4'),
        h5h6: c.querySelectorAll('h5, h6').length,
        paragraphs: Array.from(c.querySelectorAll('p')).map((p) => p.textContent.trim()),
        h1Id: c.querySelector('h1').id,
      };
    }"""
    )
    assert state["pilcrows"] == 0, state
    assert state["h4"] and state["h5h6"] == 0, state
    assert "##### חמישית" in state["paragraphs"] and "###### שישית" in state["paragraphs"], state
    assert state["h1Id"], state


def test_the_repo_browser_renderer_keeps_its_pilcrows_and_h5_h6(session):
    """הבחירה של התצוגה החיה היא וריאנט משלה (``livePreview`` ב-``RENDERER_VARIANTS``): הרינדור שדפדפן הריפו
    וכרטיסי החיפוש בתיעוד משתמשים בו — בלי ``variant`` — לא השתנה."""
    session.open()
    html = session.page.evaluate(
        "async () => (await window.MarkdownLiveRenderer.renderWithAnchors('# א\\n\\n##### ה')).html"
    )
    assert "header-anchor" in html and "<h5" in html, html


def _rgb(colour: str) -> list[float]:
    """הערוצים של צבע מחושב — ``rgb(...)`` / ``rgba(...)``, או ``color(srgb r g b / a)`` (מה ש-color-mix מחזיר)."""
    import re

    numbers = [float(n) for n in re.findall(r"[\d.]+", colour)]
    if colour.startswith("color(srgb"):
        return [round(n * 255, 1) for n in numbers[:3]] + numbers[3:4]
    return numbers


def test_a_separator_is_a_thin_line_in_the_paper_ink_and_headings_have_no_underline(session):
    """``---`` הוא קו של פיקסל אחד, בצבע הדיו של הנייר בשקיפות, עם מרווח. עד התיקון לא היה לו כלל, והדפדפן צייר
    קו "בולט" אפור. ול-H1 ול-H2 אין קו תחתון — הוא היה בצבע אפור-בהיר קבוע, שלא עקב אחרי הערכה."""
    session.open()
    page = session.page
    _set_editor(page, "# ראשית\n\n## משנה\n\nלפני\n\n---\n\nאחרי\n")
    _wait_preview_text(page, "אחרי")
    state = page.evaluate(
        """() => {
      const c = document.querySelector('[data-preview-canvas]');
      const hr = getComputedStyle(c.querySelector('hr'));
      return {
        height: hr.height, borderTop: hr.borderTopWidth, borderBottom: hr.borderBottomWidth,
        background: hr.backgroundColor, marginTop: parseFloat(hr.marginTop),
        ink: getComputedStyle(c).color,
        h1: getComputedStyle(c.querySelector('h1')).borderBottomWidth,
        h2: getComputedStyle(c.querySelector('h2')).borderBottomWidth,
      };
    }"""
    )
    assert (
        state["height"] == "1px" and state["borderTop"] == "0px" and state["borderBottom"] == "0px"
    ), state
    background, ink = _rgb(state["background"]), _rgb(state["ink"])
    assert all(abs(a - b) <= 1 for a, b in zip(background[:3], ink[:3])), state
    assert len(background) == 4 and 0.1 < background[3] < 0.4, state
    assert state["marginTop"] > 8, state
    assert state["h1"] == "0px" and state["h2"] == "0px", state


def test_the_toggle_says_what_it_does(session):
    """כשהתצוגה פתוחה הכפתור אומר "הסתר תצוגה", עם עין חצויה; כשהיא סגורה — "Live Preview". בלי ``aria-pressed``:
    הכיתוב כבר אומר מה הלחיצה תעשה."""
    session.open()
    page = session.page
    read = """() => { const b = document.querySelector('.split-toggle'); return {
      text: b.querySelector('.split-toggle__text').textContent.trim(), icon: b.querySelector('i').className,
      pressed: b.getAttribute('aria-pressed'),
      active: document.getElementById('livePreviewRoot').classList.contains('is-active')}; }"""
    on = page.evaluate(read)
    assert on["active"] and on["text"] == "הסתר תצוגה" and "fa-eye-slash" in on["icon"], on
    assert on["pressed"] is None, on
    page.click('[data-action="toggle-live-preview"]')
    off = page.evaluate(read)
    assert not off["active"] and off["text"] == "Live Preview" and "fa-columns" in off["icon"], off
    assert off["pressed"] is None, off


def test_the_area_below_the_editor_is_folded_and_scrolling_stays_inside(session):
    """מה שמתחת לעורך בבלוק מתקפל, סגור כברירת מחדל; והגלילה בעורך ובתצוגה לא עוברת לעמוד כשמגיעים לסוף."""
    session.open()
    state = session.page.evaluate(
        """() => {
      const d = document.querySelector('details.md-editor-page__about');
      return {
        open: d ? d.open : null,
        inside: d ? !!d.querySelector('#mdEditorAboutTitle') : false,
        editor: getComputedStyle(document.querySelector('.cm-scroller')).overscrollBehaviorY,
        preview: getComputedStyle(document.querySelector('.split-preview-canvas')).overscrollBehaviorY,
      };
    }"""
    )
    assert state["open"] is False and state["inside"], state
    assert state["editor"] == "contain" and state["preview"] == "contain", state


PANEL_HEIGHTS = """() => {
  const h = (s) => Math.round(document.querySelector(s).getBoundingClientRect().height);
  return {panels: h('.split-panels'), editor: h('.codemirror-container'), preview: h('.split-preview-canvas')};
}"""


def test_an_empty_document_keeps_the_panels_full_height(session):
    """אחרי "ניקוי" העורך והתצוגה נשארים בגובה שלהם. עד התיקון הגובה נקבע לפי אורך התוכן, ומסמך ריק כיווץ אותם
    (נמדד: העורך מ-459px ל-179px)."""
    session.open()
    page = session.page
    before = page.evaluate(PANEL_HEIGHTS)
    page.once("dialog", lambda d: d.accept())
    page.click('[data-md-editor-action="clear"]')
    assert session.editor_text() == ""
    page.wait_for_timeout(600)
    assert page.evaluate(PANEL_HEIGHTS) == before, before


LONG_DOC = "# התחלה\n\n" + "\n\n".join(f"פסקה {i}" for i in range(150)) + "\n\n# סוף\n"

#: הדבקה כמו של הדפדפן: אירוע ``paste`` עם הטקסט בלוח, שה-handler של CodeMirror קורא.
PASTE = """(text) => {
  const dt = new DataTransfer();
  dt.setData('text/plain', text);
  document.querySelector('.cm-content').dispatchEvent(
    new ClipboardEvent('paste', {clipboardData: dt, bubbles: true, cancelable: true}));
}"""

SCROLL_STATE = """() => {
  const v = window.editorManager.cmInstance;
  const canvas = document.querySelector('.split-preview-canvas');
  return {head: v.state.selection.main.head, editorTop: Math.round(document.querySelector('.cm-scroller').scrollTop),
          previewTop: Math.round(canvas.scrollTop), previewScrolls: canvas.scrollHeight > canvas.clientHeight};
}"""


def test_pasting_over_the_whole_document_shows_its_start(session):
    """הדבקה שמחליפה את כל המסמך משאירה את העורך ואת התצוגה בתחילת המסמך. עד התיקון הסמן נשאר בסוף מה שהודבק,
    והעורך גלל אליו, בזמן שהתצוגה הייתה בראש המסמך. הדבקה לתוך טקסט קיים לא משתנה: הסמן אחרי מה שהודבק.
    """
    session.open()
    page = session.page
    page.evaluate("() => { document.querySelector('.split-preview-canvas').scrollTop = 200; }")
    page.evaluate(
        "() => { const v = window.editorManager.cmInstance; v.focus();"
        " v.dispatch({selection: {anchor: 0, head: v.state.doc.length}}); }"
    )
    page.evaluate(PASTE, LONG_DOC)
    _wait_preview_text(page, "פסקה 149")
    state = page.evaluate(SCROLL_STATE)
    assert state["previewScrolls"], "התנאי של הבדיקה: המסמך ארוך מהתצוגה"
    assert state["head"] == 0 and state["editorTop"] == 0 and state["previewTop"] == 0, state

    page.evaluate("() => window.editorManager.cmInstance.dispatch({selection: {anchor: 10}})")
    page.evaluate(PASTE, "הודבק")
    assert page.evaluate(SCROLL_STATE)["head"] == 10 + len("הודבק")


def test_there_is_no_divider_and_a_swipe_does_not_resize_the_panels(browser):
    """בין העורך לתצוגה אין יותר קו גרירה. עד התיקון, אחרי גרירה אחת במגע, הגרירה הסתיימה ב-``pointercancel``,
    מאזין התזוזה נשאר רשום, וכל גלילה אחר כך שינתה את רוחב הפאנלים. הבדיקה עושה את מה שהמשתמש עשה, במגע אמיתי:
    לחיצה ממושכת וגרירה על הגבול בין הפאנלים, ואחריה החלקה אנכית בתצוגה."""
    b, client = browser
    s = Session(b, client, width=1100, height=760, mobile=True)
    try:
        s.open()
        page = s.page
        page.evaluate(
            "() => document.getElementById('livePreviewRoot').scrollIntoView({block: 'start'})"
        )
        assert not page.evaluate("() => !!document.querySelector('.split-resizer')")
        width = "() => Math.round(document.querySelector('.split-panel--editor').getBoundingClientRect().width)"
        geo = page.evaluate(
            """() => { const e = document.querySelector('.split-panel--editor').getBoundingClientRect();
          const p = document.querySelector('.split-panel--preview').getBoundingClientRect();
          return {seam: (e.left + p.right) / 2, y: e.top + e.height / 2, previewX: p.left + p.width / 2}; }"""
        )
        before = page.evaluate(width)
        cdp = s.ctx.new_cdp_session(page)

        def touch(kind, x=0, y=0):
            points = [] if kind == "touchEnd" else [{"x": x, "y": y, "id": 1}]
            cdp.send("Input.dispatchTouchEvent", {"type": kind, "touchPoints": points})

        x, y = geo["seam"], geo["y"]
        touch("touchStart", x, y)
        page.wait_for_timeout(600)
        for i in range(1, 8):
            touch("touchMove", x - 15 * i, y)
        touch("touchEnd")
        x = geo["previewX"]
        touch("touchStart", x, y + 100)
        for i in range(1, 10):
            touch("touchMove", x + 4 * i, y + 100 - 30 * i)
        touch("touchEnd")
        page.wait_for_timeout(300)
        assert page.evaluate(width) == before
    finally:
        s.close()


def test_an_anchor_after_an_h5_lands_on_its_own_heading(session):
    """עוגן מפורש (``<a id>``) מוחל על הכותרת לפי המספר הסידורי שלה. בתצוגה החיה ``#####`` הוא פסקה, ולכן
    החילוץ (``MdAnchors.extractExplicitAnchors``) חייב לספור כותרות כמו ה-renderer — אחרת העוגן של "יעד" הוחל
    על הכותרת שאחריה."""
    session.open()
    page = session.page
    _set_editor(page, '# ראשית\n\n##### עמוקה\n\n## יעד <a id="target"></a>\n\n## הבאה\n')
    _wait_preview_text(page, "הבאה")
    after = page.evaluate(
        "() => { const a = document.getElementById('target');"
        " return a && a.nextElementSibling ? a.nextElementSibling.textContent.trim() : null; }"
    )
    assert after == "יעד", after
