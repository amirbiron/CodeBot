"""החיפוש בתוך פתק דביק — בכרומיום אמיתי, דרך הממשק.

**למה דפדפן.** החיווט של החיפוש נשען על דברים שרק דפדפן עונה עליהם: איך
``TreeWalker`` עובר על התצוגה, מה ``IntersectionObserver`` רואה כשהפתק בקצה
העליון של המשטח, איך ``overflow`` ו-``clip-path`` חותכים, ואילו אירועים
מגיעים בלחיצה ממושכת. בסנדבוקס של ``tests/sticky-notes-target.test.js`` אין
``TreeWalker`` ואפילו לא ``childNodes`` — שם נבדקים רק החלקים הטהורים.

**העמוד.** CSS ו-JS אמיתיים מהדיסק, בסדר הטעינה של התבניות (``text-highlight.js``
לפני ``sticky-notes.js``), ו-``fetch`` מדומה שמחזיק את תוכן הפתקים ויודע לסמן
משימה כמו השרת — כך שסימון צ'קבוקס עובר במסלול האמיתי
(``_onTaskToggle`` ← ``_applyServerContent`` ← בנייה מחדש).

**מה נבדק רק באמולציה, ונאמר כאן במפורש:** לחיצה ממושכת במגע. כרומיום בלי
ממשק אינו מייצר את תפריט ההקשר ואת בחירת הטקסט המקוריים של לחיצה ממושכת
(נמדד), ולכן נבדק שהכניסה לעריכה קורית בשחרור, ושמאזין ה-``contextmenu``
מבטל אירוע כזה בזמן לחיצה פעילה — לא שהדפדפן במכשיר אמיתי אכן לא יציג
אותם.

מדולג כשאין Chromium.
"""

from __future__ import annotations

import io
import json
import math
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

import pytest

pytest.importorskip("playwright", reason="playwright אינו מותקן")

from playwright.sync_api import sync_playwright  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = REPO_ROOT / "webapp" / "static"

STYLESHEETS = ("css/markdown-enhanced.css", "css/high-contrast.css", "css/dark-mode.css", "css/sticky-notes.css")
MODULE = "js/utils/text-highlight.js"
MIME = {".js": "application/javascript", ".css": "text/css"}

#: ``fetch`` מדומה. שומר את התוכן האחרון של כל פתק (מה-``PUT`` של הלקוח,
#: שנשלח כ-``content_b64``), ועל ``POST .../task`` הופך את המשימה במקום
#: ``index`` ומחזיר את התוכן החדש — מה שהשרת עושה.
FETCH_STUB = """
window.__requests = [];
window.__contents = {};
(window.__NOTES || []).forEach(n => { window.__contents[n.id] = n.content; });
const __resp = (obj) => ({ ok: true, status: 200, json: async () => obj });
window.fetch = async (url, opts) => {
  const u = String(url); const method = (opts && opts.method) || 'GET';
  let body = null;
  try { body = opts && opts.body ? JSON.parse(String(opts.body)) : null; } catch (_) {}
  window.__requests.push({ url: u, method, body });
  if (method === 'GET') return __resp({ ok: true, notes: window.__NOTES || [] });
  const toggle = /\\/note\\/([^/?]+)\\/task/.exec(u);
  if (toggle && method === 'POST') {
    const id = decodeURIComponent(toggle[1]);
    const lines = String(window.__contents[id] || '').split('\\n');
    let seen = -1;
    for (let i = 0; i < lines.length; i++) {
      const m = /^([ \\t]*[-*][ \\t]\\[)([ xX])(\\].*)$/.exec(lines[i]);
      if (!m) continue;
      seen += 1;
      if (seen === body.index) { lines[i] = m[1] + (body.checked ? 'x' : ' ') + m[3]; break; }
    }
    window.__contents[id] = lines.join('\\n');
    return __resp({ ok: true, content: window.__contents[id], updated_at: new Date().toISOString() });
  }
  const save = /\\/note\\/([^/?]+)$/.exec(u);
  if (save && body && typeof body.content_b64 === 'string') {
    const bytes = Uint8Array.from(atob(body.content_b64), c => c.charCodeAt(0));
    window.__contents[decodeURIComponent(save[1])] = new TextDecoder().decode(bytes);
  }
  return __resp({ ok: true });
};
"""


def note(nid, content, *, w=260, h=220, x=40, y=160, mode="surface", color="yellow", minimized=False, **extra):
    data = {"id": nid, "board_id": "b1", "content": content, "title": "",
            "position": {"x": x, "y": y}, "size": {"width": w, "height": h},
            "color": color, "mode": mode, "is_minimized": minimized}
    data.update(extra)
    return data


def build_page(notes, *, theme=None, with_module=True, file_mode=False, md_html="",
               surface_style="position:relative;", tail_px=0):
    theme_attr = f' data-theme="{theme}"' if theme else ""
    links = "\n".join(f'<link rel="stylesheet" href="/{s}">' for s in STYLESHEETS)
    scripts = ["js/admonition-icons.js", "js/utils/rtl-code.js"]
    if with_module:
        scripts.append(MODULE)
    scripts.append("js/sticky-notes.js")
    tags = "\n".join(f'<script src="/{s}"></script>' for s in scripts)
    host = (f'<div id="md-content">{md_html}</div>' if file_mode
            else f'<div id="boardSurface" style="{surface_style}"></div>')
    # **גובה העמוד בא מריווח אחרי המשטח, ולא מ-``min-height`` עליו:** המנהל
    # מציב את ``min-height`` של המשטח בעצמו לפי הפתקים (``_updateSurfaceExtent``).
    if tail_px:
        host += f'<div style="height:{tail_px}px"></div>'

    manager = ("window.__mgr = new window.StickyNotesManager('file1');" if file_mode else
               "window.__mgr = new window.StickyNotesManager({ board: 'b1', "
               "container: document.getElementById('boardSurface'), anchorHost: null });")
    return f"""<!doctype html>
<html dir="rtl" lang="he"{theme_attr}><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>* {{ margin:0; padding:0; box-sizing:border-box; }} body {{ font-family: sans-serif; }}</style>
{links}
</head><body>
{host}
<script>window.__NOTES = {json.dumps(notes, ensure_ascii=False)};{FETCH_STUB}</script>
{tags}
<script>{manager}</script>
</body></html>"""


@pytest.fixture(scope="module")
def playwright_instance():
    """מופע אחד לכל הקובץ: ``sync_playwright`` שני בזמן שהראשון פתוח נכשל."""
    with sync_playwright() as p:
        yield p


def _launch(pw, chromium_executable, **kwargs):
    try:
        return (pw.chromium.launch(executable_path=chromium_executable, **kwargs) if chromium_executable
                else pw.chromium.launch(**kwargs))
    except Exception as exc:  # noqa: BLE001 — כל כשל השקה פירושו אין דפדפן
        pytest.skip(f"אין Chromium זמין: {exc}")


@pytest.fixture(scope="module")
def browser(playwright_instance, chromium_executable):
    b = _launch(playwright_instance, chromium_executable)
    try:
        yield b
    finally:
        b.close()


class NotePage:
    """עמוד עם פתקים, ועזרים קטנים שמדברים בשפת הממשק."""

    def __init__(self, browser, notes, *, viewport=(900, 700), context_opts=None, **page_opts):
        self.html = build_page(notes, **page_opts)
        self.ctx = browser.new_context(viewport={"width": viewport[0], "height": viewport[1]},
                                       **(context_opts or {}))
        self.page = self.ctx.new_page()
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.page.on("pageerror", lambda e: self.errors.append(str(e)))
        self.page.on("console", lambda m: self.warnings.append(m.text) if m.type == "warning" else None)
        self.page.route("**/*", self._serve)
        self.page.goto("http://notes.test/page.html")
        for n in notes:
            self.wait_settled(n["id"])

    def _serve(self, route):
        path = urlsplit(route.request.url).path
        if path == "/page.html":
            route.fulfill(status=200, content_type="text/html", body=self.html)
            return
        target = (STATIC_DIR / path.lstrip("/")).resolve()
        if not target.is_file() or STATIC_DIR.resolve() not in target.parents:
            route.fulfill(status=404, body="")
            return
        route.fulfill(status=200, content_type=MIME.get(target.suffix, "text/plain"),
                      body=target.read_text(encoding="utf-8"))

    def sel(self, nid, inner=""):
        return f'.sticky-note[data-note-id="{nid}"] {inner}'.strip()

    def wait_settled(self, nid):
        # אנימציית ההופעה של הפתק (``noteAppear``) משנה את המלבן בזמן שהיא רצה.
        self.page.wait_for_function(
            """(nid) => { const n = document.querySelector(`.sticky-note[data-note-id="${nid}"]`);
                return !!n && n.getAnimations().every(a => a.playState === 'finished'); }""", arg=nid)

    def rect(self, selector):
        return self.page.eval_on_selector(selector, """e => { const r = e.getBoundingClientRect();
            return { left: r.left, top: r.top, right: r.right, bottom: r.bottom, width: r.width, height: r.height }; }""")

    def open_search(self, nid, term=None):
        self.page.click(self.sel(nid, ".sticky-note-search-btn"))
        self.page.wait_for_selector(self.sel(nid, ".sticky-note-search-input"))
        if term is not None:
            self.page.fill(self.sel(nid, ".sticky-note-search-input"), term)

    def state(self, nid):
        return self.page.evaluate(
            """(nid) => { const n = document.querySelector(`.sticky-note[data-note-id="${nid}"]`);
                const hits = [...n.querySelectorAll('.sticky-note-search-hit')];
                const view = n.querySelector('.sticky-note-tasks');
                const count = n.querySelector('.sticky-note-search-count');
                return { count: count ? count.textContent : null, hits: hits.map(h => h.textContent),
                         tags: [...new Set(hits.map(h => h.tagName))],
                         active: hits.findIndex(h => h.classList.contains('is-active')),
                         bar: !!n.querySelector('.sticky-note-search'),
                         searching: n.classList.contains('is-searching'),
                         inside: n.classList.contains('is-search-inside'),
                         viewHidden: !!view && view.hidden,
                         focus: document.activeElement ? document.activeElement.className : null }; }""", nid)

    def close(self):
        self.ctx.close()


# ---------------------------------------------------------------------------
# הכפתור
# ---------------------------------------------------------------------------

def test_button_is_disabled_with_a_reason_for_plain_and_minimized_notes(browser):
    np = NotePage(browser, [
        note("md", "# כותרת\nמילה", x=40),
        note("plain", "טקסט רגיל בלבד", x=320),
        note("mini", "# כותרת\nמילה", x=600, minimized=True),
    ])
    btn = lambda nid: np.page.eval_on_selector(np.sel(nid, ".sticky-note-search-btn"), "b => [b.disabled, b.title]")
    assert btn("md") == [False, "חיפוש בפתק"]
    plain_disabled, plain_title = btn("plain")
    assert plain_disabled and "טקסט רגיל" in plain_title
    mini_disabled, mini_title = btn("mini")
    assert mini_disabled and "ממוזער" in mini_title

    # מזעור סוגר חיפוש פתוח, ופתיחה מחזירה את הכפתור.
    np.open_search("md", "מילה")
    np.page.click(np.sel("md", '.sticky-note-actions .sticky-note-btn[title="מזער"]'))
    st = np.state("md")
    assert not st["bar"] and not st["searching"] and st["hits"] == []
    assert btn("md")[0] is True
    np.page.click(np.sel("md", '.sticky-note-actions .sticky-note-btn[title="מזער"]'))
    assert btn("md")[0] is False
    assert np.errors == []
    np.close()


def test_without_the_module_the_button_is_disabled_and_warns_once(browser):
    np = NotePage(browser, [note("a", "# א\nמילה"), note("b", "# ב\nמילה", x=320)], with_module=False)
    disabled, title = np.page.eval_on_selector(np.sel("a", ".sticky-note-search-btn"), "b => [b.disabled, b.title]")
    assert disabled and "אינו זמין" in title
    assert sum("text-highlight.js" in w for w in np.warnings) == 1, np.warnings
    assert np.errors == []
    np.close()


# ---------------------------------------------------------------------------
# הקלדה, מונה, ניווט, סגירה
# ---------------------------------------------------------------------------

CONTENT = "- [ ] משימה עם מילה\nטקסט **מילה** מודגשת\nשורה שלישית עם מילה"


def test_typing_counts_navigates_like_the_document_search_and_escape_restores(browser):
    np = NotePage(browser, [note("n", CONTENT)])
    view_html = np.page.eval_on_selector(np.sel("n", ".sticky-note-tasks"), "v => v.innerHTML")
    np.open_search("n")
    assert np.state("n")["focus"] == "sticky-note-search-input"
    np.page.keyboard.type("מילה")
    st = np.state("n")
    assert st["count"] == "1/3" and st["active"] == 0
    assert st["hits"] == ["מילה"] * 3
    # ``span`` ולא ``mark``: המרקר של המשתמש הוא ``mark``, ויש כללי ערכה עליו.
    assert st["tags"] == ["SPAN"]

    # כמו בחיפוש במסמך: ה-Enter הראשון נשאר על ההתאמה שסומנה בהקלדה.
    np.page.keyboard.press("Enter")
    assert np.state("n")["count"] == "1/3"
    np.page.keyboard.press("Enter")
    assert np.state("n")["count"] == "2/3"
    np.page.keyboard.press("Shift+Enter")
    assert np.state("n")["count"] == "1/3"
    np.page.keyboard.press("Shift+Enter")
    assert np.state("n")["count"] == "3/3", "מעגלי אחורה"
    np.page.click(np.sel("n", ".sticky-note-search-next"))
    assert np.state("n")["count"] == "1/3", "מעגלי קדימה"
    np.page.click(np.sel("n", ".sticky-note-search-prev"))
    assert np.state("n")["count"] == "3/3"

    np.page.fill(np.sel("n", ".sticky-note-search-input"), "אין-כזה")
    assert np.state("n")["count"] == "אין תוצאות"

    np.page.focus(np.sel("n", ".sticky-note-search-input"))
    np.page.keyboard.press("Escape")
    st = np.state("n")
    assert not st["bar"] and not st["searching"] and st["hits"] == []
    assert "sticky-note-search-btn" in st["focus"], "הפוקוס חוזר לכפתור"
    # הניקוי מחזיר את התצוגה בדיוק למה שהייתה (כולל איחוד צמתי הטקסט).
    assert np.page.eval_on_selector(np.sel("n", ".sticky-note-tasks"), "v => v.innerHTML") == view_html
    assert np.errors == []
    np.close()


def test_highlight_does_not_change_text_metrics(browser):
    """בלי ``padding`` ובלי שינוי משקל: בפתק צר שינוי רוחב של מילה שובר שורות מחדש.

    המדד הוא **המיקום של כל מופע**: לפני ההדגשה — טווח על צומת הטקסט, ואחריה —
    העטיפה עצמה. מופע שזז אפילו בחצי פיקסל פירושו שההדגשה שינתה את הפריסה.
    """
    np = NotePage(browser, [note("n", "- [ ] מילה מילה מילה מילה מילה מילה מילה מילה מילה", w=160)])
    before = np.page.evaluate("""(sel) => {
        const view = document.querySelector(sel + ' .sticky-note-tasks'); const out = [];
        const w = document.createTreeWalker(view, NodeFilter.SHOW_TEXT); let t;
        while ((t = w.nextNode())) {
          const re = /מילה/g; let m;
          while ((m = re.exec(t.nodeValue))) {
            const r = document.createRange(); r.setStart(t, m.index); r.setEnd(t, m.index + m[0].length);
            const b = r.getBoundingClientRect(); out.push([b.left, b.top, b.width, b.height].map(v => Math.round(v * 10)));
          }
        }
        return out; }""", np.sel("n"))
    np.open_search("n", "מילה")
    after = np.page.eval_on_selector_all(np.sel("n", ".sticky-note-search-hit"), """hs => hs.map(h => {
        const b = h.getBoundingClientRect(); return [b.left, b.top, b.width, b.height].map(v => Math.round(v * 10)); })""")
    assert np.state("n")["count"] == "1/9"
    assert len(before) == 9 and after == before
    np.close()


def test_text_the_engine_generates_is_not_matched(browser):
    content = ("::: note\nגוף\n:::\n::: tip כותרת שלי\nגוף\n:::\n::: details\nגוף\n:::\n"
               "- פריט\n1. ממוספר\n```js\nx\n```")
    np = NotePage(browser, [note("n", content, h=420)])
    labels = np.page.evaluate("() => [window.ADMONITION_TITLES.note, window.DETAILS_DEFAULT_TITLE]")
    np.open_search("n")
    expectations = [
        (labels[0], 0, "תווית ברירת המחדל של אלרט"),
        (labels[1], 0, "כותרת ברירת המחדל של details"),
        ("•", 0, "התבליט של רשימה לא ממוספרת"),
        ("כותרת שלי", 1, "כותרת מותאמת היא טקסט שנכתב"),
        ("js", 1, "תווית השפה נגזרת ממה שנכתב"),
        ("1.", 1, "המספר שהוקלד ברשימה ממוספרת"),
    ]
    for term, expected, why in expectations:
        np.page.fill(np.sel("n", ".sticky-note-search-input"), term)
        assert len(np.state("n")["hits"]) == expected, why
    np.close()


# ---------------------------------------------------------------------------
# שרידות לבנייה מחדש
# ---------------------------------------------------------------------------

TASKS = "- [ ] אחת מילה\n- [ ] שתיים מילה\n- [ ] שלוש מילה"


def test_highlight_survives_a_checkbox_toggle_and_keeps_the_active_match(browser):
    np = NotePage(browser, [note("n", TASKS)])
    np.open_search("n", "מילה")
    np.page.keyboard.press("Enter")
    np.page.keyboard.press("Enter")
    assert np.state("n")["count"] == "2/3"
    np.page.click(np.sel("n", ".sticky-task-box"))
    np.page.wait_for_function(
        """(sel) => { const b = document.querySelector(sel + ' .sticky-task-box'); return b && b.checked && !b.disabled; }""",
        arg=np.sel("n"))
    st = np.state("n")
    assert st["hits"] == ["מילה"] * 3, "ההדגשה חזרה אחרי הבנייה מחדש"
    assert st["active"] == 1 and st["count"] == "2/3", "ההתאמה הפעילה נשמרה לפי מספר סידורי"
    assert np.errors == []
    np.close()


def test_short_click_does_not_edit_but_long_press_and_enter_do(browser):
    np = NotePage(browser, [note("n", TASKS)])
    np.open_search("n", "מילה")
    second = np.rect(np.sel("n", ".sticky-task-line:nth-child(2) .sticky-task-text"))
    x, y = second["left"] + 5, second["top"] + second["height"] / 2
    np.page.mouse.click(x, y)
    st = np.state("n")
    assert not st["viewHidden"] and st["hits"] == ["מילה"] * 3, "לחיצה רגילה לא נכנסת לעריכה"

    np.page.mouse.move(x, y)
    np.page.mouse.down()
    np.page.wait_for_timeout(650)
    np.page.mouse.up()
    st = np.state("n")
    assert st["viewHidden"] and st["focus"] == "sticky-note-content", "לחיצה ממושכת נכנסת לעריכה"
    assert st["bar"] and st["count"] == "", "התיבה נשארת פתוחה, והמונה ממתין"
    caret = np.page.eval_on_selector(np.sel("n", ".sticky-note-content"), "t => t.selectionStart")
    assert caret == TASKS.index("- [ ] שתיים"), "הסמן נוחת בשורה שנלחצה"

    # הקלדה בעריכה, ויציאה דרך תיבת החיפוש: ההדגשה חוזרת, כולל ההתאמה החדשה.
    np.page.keyboard.press("End")
    np.page.keyboard.type(" מילה")
    np.page.click(np.sel("n", ".sticky-note-search-input"))
    st = np.state("n")
    assert not st["viewHidden"] and len(st["hits"]) == 4

    # מקלדת: Enter על התצוגה נכנס לעריכה גם בזמן חיפוש (אין לה לחיצה ממושכת).
    np.page.focus(np.sel("n", ".sticky-note-tasks"))
    np.page.keyboard.press("Enter")
    assert np.state("n")["viewHidden"]
    assert np.errors == []
    np.close()


def test_opening_search_while_editing_saves_the_last_keystrokes(browser):
    """פתיחת חיפוש יוצאת מעריכה דרך ה-``blur`` — המסלול שמריץ ``_flushFor``."""
    np = NotePage(browser, [note("n", TASKS)])
    np.page.click(np.sel("n", ".sticky-task-line:nth-child(3) .sticky-task-text"))
    np.page.keyboard.press("End")
    np.page.keyboard.type(" חדש")
    np.open_search("n", "חדש")
    np.page.wait_for_function("() => (window.__contents.n || '').includes('שלוש מילה חדש')")
    assert np.state("n")["hits"] == ["חדש"]

    # ובלי לחיצת עכבר (שבכרומיום כבר מוציאה את הפוקוס ב-mousedown): הפתיחה
    # עצמה מעבירה את הפוקוס לשדה, וזה מה שמוציא מעריכה ושומר.
    np.page.focus(np.sel("n", ".sticky-note-search-input"))
    np.page.keyboard.press("Escape")
    np.page.click(np.sel("n", ".sticky-task-line:nth-child(1) .sticky-task-text"), modifiers=[])
    np.page.wait_for_function("(sel) => !document.querySelector(sel).hidden", arg=np.sel("n", ".sticky-note-content"))
    np.page.keyboard.press("End")
    np.page.keyboard.type(" עוד")
    np.page.evaluate("(sel) => window.__mgr._openNoteSearch(document.querySelector(sel))", np.sel("n"))
    np.page.wait_for_function("() => (window.__contents.n || '').includes('אחת מילה עוד')")
    st = np.state("n")
    assert st["focus"] == "sticky-note-search-input" and not st["viewHidden"]
    np.close()


def test_a_note_that_becomes_plain_text_closes_its_search(browser):
    np = NotePage(browser, [note("n", TASKS)])
    np.open_search("n", "מילה")
    line = np.rect(np.sel("n", ".sticky-task-line:nth-child(1) .sticky-task-text"))
    np.page.mouse.move(line["left"] + 5, line["top"] + line["height"] / 2)
    np.page.mouse.down()
    np.page.wait_for_timeout(650)
    np.page.mouse.up()
    np.page.keyboard.press("Control+A")
    np.page.keyboard.type("טקסט רגיל בלבד")
    np.page.click(np.sel("n", ".sticky-note-search-input"))
    np.page.wait_for_function("(sel) => !document.querySelector(sel + ' .sticky-note-search')", arg=np.sel("n"))
    st = np.state("n")
    assert not st["searching"] and st["hits"] == []
    assert np.page.eval_on_selector(np.sel("n", ".sticky-note-search-btn"), "b => b.disabled")
    assert np.errors == []
    np.close()


def test_details_opened_by_search_close_again_and_are_not_remembered(browser):
    content = "- [ ] משימה\n::: details\nבפנים מילה\n:::\n::: details\nאחר\n:::"
    np = NotePage(browser, [note("n", content, h=320)])
    boxes = lambda: np.page.eval_on_selector_all(np.sel("n", "details.sticky-md-details"), "ds => ds.map(d => d.open)")
    np.page.click(np.sel("n", "details.sticky-md-details:nth-of-type(2) summary"))
    assert boxes() == [False, True]

    np.open_search("n", "מילה")
    assert boxes() == [True, True], "הבלוק שבו ההתאמה נפתח"
    np.page.click(np.sel("n", ".sticky-task-box"))
    np.page.wait_for_function("(sel) => document.querySelector(sel + ' .sticky-task-box').checked", arg=np.sel("n"))
    assert boxes() == [True, True], "ושורד את הבנייה מחדש"

    np.page.focus(np.sel("n", ".sticky-note-search-input"))
    np.page.keyboard.press("Escape")
    assert boxes() == [False, True], "הסגירה סוגרת רק את מה שהחיפוש פתח"
    np.page.click(np.sel("n", ".sticky-task-box"))
    np.page.wait_for_function("(sel) => !document.querySelector(sel + ' .sticky-task-box').checked", arg=np.sel("n"))
    assert boxes() == [False, True], "והוא לא נכנס לזיכרון הפתיחה"
    assert np.errors == []
    np.close()


def test_a_failing_highlight_pass_is_logged_and_keeps_the_markdown(browser):
    np = NotePage(browser, [note("n", "# כותרת\n" + TASKS)])
    np.open_search("n", "מילה")
    np.page.evaluate("""() => { window.TextHighlight = Object.assign({}, window.TextHighlight,
        { highlightWithin() { throw new Error('boom'); } }); }""")
    np.page.click(np.sel("n", ".sticky-task-box"))
    np.page.wait_for_function("(sel) => document.querySelector(sel + ' .sticky-task-box').checked", arg=np.sel("n"))
    assert np.page.eval_on_selector(np.sel("n"), "n => !!n.querySelector('.sticky-md-h1')"), "המארקדאון נשאר"
    assert any("in-note search failed" in w for w in np.warnings), np.warnings
    np.close()


# ---------------------------------------------------------------------------
# גלילה ומיקום
# ---------------------------------------------------------------------------

def test_navigation_scrolls_the_note_and_not_the_page(browser):
    long = "\n".join(f"- שורה {i}" for i in range(60)) + "\n- בסוף יש מטרה"
    table = "| " + " | ".join(f"עמודה {i}" for i in range(14)) + " | יעד |\n|" + "---|" * 15 + "\n|" + " x |" * 15
    np = NotePage(browser, [note("long", long, y=300), note("wide", table, x=340, y=300, w=220)], tail_px=1500)
    np.page.evaluate("() => window.scrollTo(0, 120)")
    page_y = np.page.evaluate("() => window.scrollY")
    assert page_y > 0

    np.open_search("long", "מטרה")
    view = np.rect(np.sel("long", ".sticky-note-tasks"))
    hit = np.rect(np.sel("long", ".sticky-note-search-hit"))
    assert np.page.eval_on_selector(np.sel("long", ".sticky-note-tasks"), "v => v.scrollTop") > 0
    assert view["top"] <= hit["top"] and hit["bottom"] <= view["bottom"]
    assert np.page.evaluate("() => window.scrollY") == page_y, "העמוד לא זז"

    # טבלה רחבה ב-RTL: העטיפה נגללת אופקית, ולא העמוד.
    np.open_search("wide", "יעד")
    wrap = np.rect(np.sel("wide", ".sticky-md-table-wrap"))
    hit = np.rect(np.sel("wide", ".sticky-note-search-hit"))
    assert np.page.eval_on_selector(np.sel("wide", ".sticky-md-table-wrap"), "w => w.scrollLeft") < 0
    assert wrap["left"] <= hit["left"] and hit["right"] <= wrap["right"]
    assert np.page.evaluate("() => [window.scrollX, window.scrollY]") == [0, page_y]
    np.close()


def test_the_bar_sits_above_the_note_and_moves_inside_at_the_top_edge(browser):
    np = NotePage(browser, [note("mid", TASKS, y=220), note("top", TASKS, x=340, y=0)])
    before = np.rect(np.sel("mid"))
    np.open_search("mid", "מילה")
    bar = np.rect(np.sel("mid", ".sticky-note-search"))
    after = np.rect(np.sel("mid"))
    assert after == before, "התיבה אינה משנה את המלבן של הפתק"
    assert abs(bar["bottom"] - after["top"]) <= 1.5 and not np.state("mid")["inside"]
    # ‏``box-sizing: border-box``: הרוחב של הפתק כבר כולל את הגבול, והתיבה
    # (``inset-inline: -1px`` מקופסת הריפוד) שווה לו בדיוק.
    assert abs(bar["width"] - after["width"]) <= 0.5, "ברוחב הפתק"

    np.open_search("top", "אחת")
    np.page.wait_for_function("(sel) => document.querySelector(sel).classList.contains('is-search-inside')",
                              arg=np.sel("top"))
    note_rect = np.rect(np.sel("top"))
    bar = np.rect(np.sel("top", ".sticky-note-search"))
    header = np.rect(np.sel("top", ".sticky-note-header"))
    assert note_rect["top"] <= bar["top"] and bar["bottom"] <= note_rect["bottom"]
    assert bar["top"] >= header["bottom"] - 0.5, "מתחת לכותרת"
    # התיבה דוחפת את התוכן ואינה מכסה אותו: ההתאמה בשורה הראשונה נראית.
    covered = np.page.eval_on_selector(np.sel("top", ".sticky-note-search-hit"), """h => {
        const r = h.getBoundingClientRect();
        return document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2) === h; }""")
    assert covered, "ההתאמה הראשונה אינה מוסתרת"

    # גרירה למטה מפנה מקום מעל, והתיבה חוזרת החוצה.
    header = np.rect(np.sel("top", ".sticky-note-header"))
    np.page.mouse.move(header["left"] + 30, header["bottom"] - 4)
    np.page.mouse.down()
    np.page.mouse.move(header["left"] + 30, header["bottom"] + 150, steps=6)
    np.page.mouse.up()
    np.page.wait_for_function("(sel) => !document.querySelector(sel).classList.contains('is-search-inside')",
                              arg=np.sel("top"))
    assert np.errors == []
    np.close()


def test_opening_the_search_does_not_scroll_the_page(browser):
    """‏``focus({ preventScroll: true })``: כשאין מקום מעל הפתק, התיבה עוד לא עברה
    פנימה ברגע הפוקוס, ופוקוס רגיל היה גולל את העמוד כדי לחשוף אותה."""
    np = NotePage(browser, [note("n", TASKS, y=140)], tail_px=1500)
    np.page.evaluate("() => window.scrollTo(0, 120)")
    np.page.wait_for_function("() => window.scrollY === 120")
    np.open_search("n", "מילה")
    np.page.wait_for_function("(sel) => document.querySelector(sel).classList.contains('is-search-inside')",
                              arg=np.sel("n"))
    assert np.page.evaluate("() => window.scrollY") == 120
    np.close()


def test_nothing_the_note_clipped_leaks_out_while_searching(playwright_instance, chromium_executable):
    """בזמן חיפוש לפתק אין ``overflow: hidden``; מה שהוא חתך נחתך עכשיו על ידי הילדים.

    פתק צר, כך ששורת הכפתורים גולשת מהכותרת (היא אינה נשברת), ותוכן ארוך, כך
    שיש פס גלילה. **פסי הגלילה גלויים** — Playwright מסתיר אותם כברירת מחדל
    (``--hide-scrollbars``), ובלעדיהם הקצה המרובע של הפס לא היה מצויר כלל.
    משווים את מה שמחוץ לפתק (בצדדים ומתחת; מעל יושבת התיבה בכוונה) ואת
    הפינות התחתונות מחוץ לקשת — לפני ואחרי הפתיחה.
    """
    from PIL import Image, ImageChops  # מוצמד ב-requirements/base.txt
    long = "\n".join(f"- [ ] משימה ארוכה {i}" for i in range(30))
    b = _launch(playwright_instance, chromium_executable, ignore_default_args=["--hide-scrollbars"])
    try:
        np = NotePage(b, [note("n", long, w=140, h=220, x=150, y=160)], viewport=(520, 520),
                      context_opts={"device_scale_factor": 2})
        assert np.page.eval_on_selector(np.sel("n", ".sticky-note-actions"),
                                        "a => a.scrollWidth > a.parentElement.clientWidth"), "הכותרת גולשת"
        assert np.page.eval_on_selector(np.sel("n", ".sticky-note-tasks"), "v => v.offsetWidth - v.clientWidth") > 0
        r = np.rect(np.sel("n"))
        clip = {"x": r["left"] - 50, "y": r["top"], "width": r["width"] + 100, "height": r["height"] + 20}
        shot = lambda: Image.open(io.BytesIO(np.page.screenshot(clip=clip))).convert("RGB")
        before = shot()
        np.open_search("n")
        np.page.focus(np.sel("n", ".sticky-note-search-next"))
        after = shot()
        np.close()
    finally:
        b.close()
    diff = ImageChops.difference(before, after).load()
    s, R = 2, 10 * 2
    nx0, nx1, ny1 = 50 * s, (50 + r["width"]) * s, r["height"] * s
    leaks = 0
    for y in range(int(clip["height"] * s)):
        for x in range(int(clip["width"] * s)):
            if sum(diff[x, y]) <= 12:
                continue
            outside = not (nx0 <= x < nx1 and y < ny1)
            corner = y >= ny1 - R and (x < nx0 + R or x >= nx1 - R)
            if corner:
                cx = nx0 + R if x < nx0 + R else nx1 - R
                corner = ((x - cx) ** 2 + (y - (ny1 - R)) ** 2) ** 0.5 > R
            leaks += outside or corner
    assert leaks == 0


def _drag_and_saved_position(np, nid, dx, dy):
    header = np.rect(np.sel(nid, ".sticky-note-header"))
    x0, y0 = header["left"] + 20, header["bottom"] - 4
    np.page.evaluate("() => { window.__requests = []; }")
    np.page.mouse.move(x0, y0)
    np.page.mouse.down()
    np.page.mouse.move(x0 + dx, y0 + dy, steps=6)
    np.page.mouse.up()
    np.page.wait_for_function(
        "(nid) => window.__requests.some(r => r.method === 'PUT' && r.url.endsWith('/' + nid) && r.body && r.body.position)",
        arg=nid)
    puts = [r for r in np.page.evaluate("() => window.__requests")
            if r["method"] == "PUT" and r["url"].endswith("/" + nid) and r["body"] and r["body"].get("position")]
    return puts[-1]["body"]["position"]


@pytest.mark.parametrize("mode", ["surface", "screen", "anchored"])
def test_the_bar_moves_with_the_note_and_does_not_change_what_is_saved(browser, mode):
    md = "".join(f'<p data-source-line="{i}">שורת מסמך {i}</p>' for i in range(40))
    extra = {"line_start": 3} if mode == "anchored" else {}
    opts = {"file_mode": True, "md_html": md} if mode == "anchored" else {}
    saved = {}
    for with_search in (False, True):
        np = NotePage(browser, [note("n", TASKS, mode=mode, y=200, **extra)], **opts)
        if with_search:
            np.open_search("n", "מילה")
            np.page.focus(np.sel("n", ".sticky-note-tasks"))
        saved[with_search] = _drag_and_saved_position(np, "n", 40, 30)
        if with_search:
            bar = np.rect(np.sel("n", ".sticky-note-search"))
            assert abs(bar["bottom"] - np.rect(np.sel("n"))["top"]) <= 1.5, "התיבה זזה עם הפתק"
        assert np.errors == []
        np.close()
    assert saved[True] == saved[False], f"המיקום שנשמר זהה עם התיבה ובלעדיה ({mode})"


def test_narrow_screen_the_bar_wraps_inside_the_note_width(browser):
    np = NotePage(browser, [note("n", TASKS, w=160, x=150, y=200)], viewport=(360, 640))
    np.open_search("n", "מילה")
    bar = np.rect(np.sel("n", ".sticky-note-search"))
    note_rect = np.rect(np.sel("n"))
    input_rect = np.rect(np.sel("n", ".sticky-note-search-input"))
    assert abs(bar["width"] - note_rect["width"]) <= 0.5
    assert bar["height"] > input_rect["height"] * 1.7, "נשברת לשתי שורות"
    assert np.page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth")
    np.close()


# ---------------------------------------------------------------------------
# מקלדת, מגע, והחיפוש של עמוד המסמך
# ---------------------------------------------------------------------------

def test_keys_in_the_bar_do_not_reach_the_page_and_ime_enter_is_ignored(browser):
    np = NotePage(browser, [note("n", TASKS)])
    # ‏``keyup`` נספר רק כשהוא יוצא מהתיבה: ה-``keyup`` של ה-Escape שסגר אותה
    # נוחת כבר על כפתור החיפוש, שאליו חזר הפוקוס — התיבה אינה קיימת עוד.
    np.page.evaluate("""() => { window.__pageKeys = 0;
        ['keydown', 'keypress'].forEach(t => document.addEventListener(t, () => { window.__pageKeys++; }));
        document.addEventListener('keyup', (e) => {
          if (e.target.closest && e.target.closest('.sticky-note-search')) window.__pageKeys++; }); }""")
    np.open_search("n", "")
    np.page.keyboard.type("מילה ")
    np.page.keyboard.press("Enter")
    np.page.keyboard.press("Enter")
    assert np.state("n")["count"] == "2/3"
    composing = np.page.eval_on_selector(np.sel("n", ".sticky-note-search-input"), """i => {
        i.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', isComposing: true, bubbles: true, cancelable: true }));
        return document.querySelector('.sticky-note-search-count').textContent; }""")
    assert composing == "2/3", "Enter בזמן הרכבת IME שייך להרכבה"
    np.page.keyboard.press("Escape")
    assert not np.state("n")["bar"]
    assert np.page.evaluate("() => window.__pageKeys") == 0
    np.close()


def test_touch_long_press_enters_edit_in_emulation(browser):
    """**אמולציה בלבד** — ראו את ההערה בראש הקובץ."""
    np = NotePage(browser, [note("n", TASKS)], viewport=(420, 640),
                  context_opts={"has_touch": True, "is_mobile": True})
    np.open_search("n", "מילה")
    cdp = np.ctx.new_cdp_session(np.page)
    line = np.rect(np.sel("n", ".sticky-task-line:nth-child(2) .sticky-task-text"))
    x, y = line["left"] + 6, line["top"] + line["height"] / 2

    cdp.send("Input.synthesizeTapGesture", {"x": x, "y": y, "duration": 60, "tapCount": 1, "gestureSourceType": "touch"})
    np.page.wait_for_timeout(200)
    assert not np.state("n")["viewHidden"], "הקשה קצרה לא נכנסת לעריכה"

    # בזמן לחיצה פעילה במגע, מאזין ה-contextmenu מבטל את האירוע.
    cdp.send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": x, "y": y, "id": 1}]})
    prevented = np.page.eval_on_selector(np.sel("n", ".sticky-note-tasks"), """v => {
        const ev = new MouseEvent('contextmenu', { bubbles: true, cancelable: true });
        v.querySelector('.sticky-task-line').dispatchEvent(ev); return ev.defaultPrevented; }""")
    assert prevented
    assert np.page.eval_on_selector(np.sel("n", ".sticky-note-tasks"), "v => v.classList.contains('is-pressing')")
    cdp.send("Input.dispatchTouchEvent", {"type": "touchCancel", "touchPoints": []})

    cdp.send("Input.synthesizeTapGesture", {"x": x, "y": y, "duration": 900, "tapCount": 1, "gestureSourceType": "touch"})
    np.page.wait_for_function("(sel) => document.querySelector(sel).hidden", arg=np.sel("n", ".sticky-note-tasks"))
    st = np.state("n")
    assert st["focus"] == "sticky-note-content" and st["bar"]
    assert np.page.evaluate("() => String(getSelection())") == ""
    np.close()


def test_notes_live_outside_the_document_search_container(browser):
    md = '<p data-source-line="0">מילה במסמך</p>'
    np = NotePage(browser, [note("n", TASKS, mode="screen")], file_mode=True, md_html=md)
    assert np.page.evaluate("""() => !document.getElementById('md-content')
        .contains(document.querySelector('.sticky-note'))""")
    np.open_search("n", "מילה")
    # החיפוש של העמוד מנקה לפי ``md-highlight`` — שאינה המחלקה שלנו.
    np.page.evaluate("() => TextHighlight.clearHighlights(document.body, 'md-highlight')")
    assert len(np.state("n")["hits"]) == 3
    np.close()


def test_deleting_a_note_with_open_search_disconnects_the_observers(browser):
    np = NotePage(browser, [note("n", TASKS)])
    np.page.evaluate("""() => { window.__disc = 0; const orig = IntersectionObserver.prototype.disconnect;
        IntersectionObserver.prototype.disconnect = function () { window.__disc++; return orig.apply(this, arguments); }; }""")
    np.open_search("n", "מילה")
    np.page.evaluate("() => window.__mgr._deleteNoteEl(document.querySelector('.sticky-note'))")
    np.page.wait_for_function("() => !document.querySelector('.sticky-note')")
    assert np.page.evaluate("() => window.__disc") >= 1
    assert np.errors == []
    np.close()


# ---------------------------------------------------------------------------
# צבעים — בדגימת פיקסל
# ---------------------------------------------------------------------------

PAPERS = ("yellow", "yellow_light", "green_light", "orange_light", "blue_light", "purple_light", "pink_light")


def _lum(c):
    def f(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2])


def _contrast(a, b):
    hi, lo = sorted((_lum(a), _lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _pixels(page):
    from PIL import Image  # מוצמד ב-requirements/base.txt
    return Image.open(io.BytesIO(page.screenshot())).convert("RGB")


def _mode(im, box, scale):
    x0, y0, x1, y1 = (int(round(v * scale)) for v in box)
    return Counter(im.getpixel((x, y)) for y in range(y0, y1) for x in range(x0, x1)).most_common(1)[0][0]


def _darkest(im, box, scale):
    x0, y0, x1, y1 = (int(round(v * scale)) for v in box)
    return min((im.getpixel((x, y)) for y in range(y0, y1) for x in range(x0, x1)), key=sum)


@pytest.mark.parametrize("paper", PAPERS)
def test_highlight_colors_by_pixel_sampling(browser, paper):
    """הספים נגזרים מהמדידה שמתועדת במסמך הפיתוח, עם שוליים — לא מספרים עגולים."""
    np = NotePage(browser, [note("n", "אחת מילה\n==סימון== ועוד\nשלוש מילה", w=300, color=paper)],
                  viewport=(420, 480), context_opts={"device_scale_factor": 2})
    np.open_search("n", "מילה")
    hits = np.page.eval_on_selector_all(np.sel("n", ".sticky-note-search-hit"), """hs => hs.map(h => {
        const r = h.getBoundingClientRect(); return [r.left, r.top, r.right, r.bottom, h.classList.contains('is-active')]; })""")
    active = next(h for h in hits if h[4])
    regular = next(h for h in hits if not h[4])
    view = np.rect(np.sel("n", ".sticky-note-tasks"))
    mark = np.rect(np.sel("n", ".sticky-md-mark"))
    im = _pixels(np.page)
    paper_px = _mode(im, (view["left"] + 2, view["bottom"] - 20, view["left"] + 40, view["bottom"] - 4), 2)
    fill = _mode(im, regular[:4], 2)
    text = _darkest(im, regular[:4], 2)
    ring = _mode(im, (active[0] - 3, active[1] + 2, active[0] - 1, active[3] - 2), 2)
    marker = _mode(im, (mark["left"], mark["top"], mark["right"], mark["bottom"]), 2)
    np.close()
    # המילוי נבדל מהנייר ומהמרקר של המשתמש (מרחק RGB — המדד של המרקר).
    assert math.dist(fill, paper_px) >= 150
    assert math.dist(fill, marker) >= 150
    assert _contrast(text, fill) >= 7
    # ההתאמה הפעילה מסומנת בטבעת שנראית גם מול המילוי וגם מול הנייר.
    assert _contrast(ring, fill) >= 4.5
    assert _contrast(ring, paper_px) >= 4.5


@pytest.mark.parametrize("theme", [None, "high-contrast"])
def test_the_bar_is_readable_in_every_theme(browser, theme):
    """ב-high-contrast הערכה כופה ``!important`` על השדה ועל הכפתורים; התיבה מצטרפת אליה."""
    np = NotePage(browser, [note("n", TASKS, w=300, color="pink_light")], theme=theme,
                  viewport=(460, 420), context_opts={"device_scale_factor": 2})
    np.open_search("n")
    inp = np.rect(np.sel("n", ".sticky-note-search-input"))
    box = (inp["left"] + 6, inp["top"] + 4, inp["right"] - 6, inp["bottom"] - 4)
    im = _pixels(np.page)
    in_bg = _mode(im, box, 2)
    placeholder = _darkest(im, box, 2) if sum(in_bg) > 380 else max(
        (im.getpixel((x, y)) for y in range(int(box[1] * 2), int(box[3] * 2)) for x in range(int(box[0] * 2), int(box[2] * 2))), key=sum)
    bar = np.rect(np.sel("n", ".sticky-note-search"))
    bar_bg = _mode(im, (bar["left"] + 3, bar["top"] + 3, bar["left"] + 5, bar["bottom"] - 3), 2)
    ring = _mode(im, (inp["left"] - 4, inp["top"] + 4, inp["left"] - 2, inp["bottom"] - 4), 2)
    np.page.keyboard.type("מילה")
    im = _pixels(np.page)
    typed = _darkest(im, box, 2) if sum(in_bg) > 380 else max(
        (im.getpixel((x, y)) for y in range(int(box[1] * 2), int(box[3] * 2)) for x in range(int(box[0] * 2), int(box[2] * 2))), key=sum)
    np.close()
    assert _contrast(typed, in_bg) >= 7
    assert _contrast(placeholder, in_bg) >= 4.5
    # טבעת הפוקוס נראית מול התיבה — זה מה שנכשל ב-high-contrast על נייר (1.04:1).
    assert _contrast(ring, bar_bg) >= 3
