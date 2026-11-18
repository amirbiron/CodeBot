"""MCP App: הדף של תצוגת הפתק בדפדפן אמיתי — מה שהדפדפן אוכף ושום בדיקת שרת אינה רואה.

**המארח כאן מינימלי, וכתוב לפי המפרט** (``specification/2026-01-26/apps.mdx``, "Lifecycle"): הוא
מריץ את הדף ב-iframe עם ``sandbox="allow-scripts"`` (origin אטום, כמו מסגרת של מארח אמיתי), עונה
ל-``ui/initialize`` עם ``hostContext`` של ערכה כהה, ושולח ``tool-input`` ואחריו ``tool-result``.
הדף עצמו מוגש **עם ה-CSP שהמפרט מחייב כשהמשאב אינו מצהיר על ``csp``** — כך נבדק שהסקריפט והסגנון
שכתובים בתוך הדף באמת רצים תחת המדיניות הזו, ולא רק שהם נראים תקינים.

מה נבדק כאן ולא ב-``tests/mcp-note-view.test.js``: הודעה ממסגרת אחרת באותו עמוד (``event.source``
מול חלון אמיתי), ``dir="auto"`` כפי שהדפדפן מחשב אותו לכל שורה, גודל הטקסט המחושב, הרקע השקוף
של הדף, ושתוכן הפתק אינו מריץ דבר. מה שלא נבדק כאן: המארח האמיתי של Claude — ראו את ה-PR.
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from _browser_harness import WAIT_S, Touch, poll
from mcp_server import note_view
from sticky_notes_target import NOTE_COLORS

#: ברירת המחדל של המפרט כשהמשאב אינו מצהיר על ``ui.csp``: "If `ui.csp` is omitted, Host MUST use"
#: (``specification/2026-01-26/apps.mdx``, "Host Behavior").
_SPEC_DEFAULT_CSP = (
    "default-src 'none'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; media-src 'self' data:; connect-src 'none';"
)

_EVIL = '<img src=x onerror="window.top.pwned=1"><script>window.top.pwned=2</script>'

_NOTE = {
    "ok": True,
    "note": {
        "id": "a" * 24,
        "title": "רשימה " + _EVIL,
        "content": "# כותרת בעברית\n\nEnglish line first\nשורה בעברית עם English באמצע\n" + _EVIL,
        "color": "#ffeddb",
        "color_id": "orange_light",
    },
    "target": "board",
    "board_id": "b" * 24,
}

_HOST_CONTEXT = {
    "theme": "dark",
    "styles": {"variables": {"--color-text-primary": "#fafafa", "--color-background-secondary": "#30302e"}},
}

_HOST_PAGE = """<!doctype html><html><head><meta charset="utf-8"></head><body>
<iframe id="view" src="/view.html" sandbox="allow-scripts" style="width:560px;height:80px;border:0"></iframe>
<script>
const NOTE_RESULT = {content: [{type: 'text', text: JSON.stringify(%(note)s, null, 2)}]};
const HOST_CONTEXT = %(context)s;
const iframe = document.getElementById('view');
window.received = [];
window.strangerSent = false;
function startStranger() {
  // מסגרת אחרת באותו עמוד שולחת לדף תוצאה מזויפת. ``parent.frames[0]`` מותר גם מ-origin אטום.
  const s = document.createElement('iframe');
  s.setAttribute('sandbox', 'allow-scripts');
  s.srcdoc = "<script>parent.frames[0].postMessage({jsonrpc:'2.0',method:'ui/notifications/tool-result'," +
    "params:{content:[{type:'text',text:JSON.stringify({ok:true," +
    "note:{title:'FORGED',content:'FORGED',color:'#000000'}})}]}}, '*');" +
    "parent.postMessage('stranger-done', '*');<\\/script>";
  document.body.appendChild(s);
}
// **הסדר הוא כל הבדיקה:** הפתק האמיתי קודם, המזויף אחריו, ואז ``ping`` הלוך-חזור כמחסום. מזויף
// שהיה מגיע לפני האמיתי היה נדרס ממילא, והבדיקה הייתה עוברת גם בלי בדיקת המקור.
window.addEventListener('message', (event) => {
  if (event.data === 'stranger-done') {
    window.strangerSent = true;
    iframe.contentWindow.postMessage({jsonrpc: '2.0', id: 'barrier', method: 'ping', params: {}}, '*');
    return;
  }
  if (event.source !== iframe.contentWindow) return;
  const m = event.data;
  window.received.push(m);
  if (m.method === 'ui/initialize') {
    iframe.contentWindow.postMessage({jsonrpc: '2.0', id: m.id, result: {protocolVersion: '2026-01-26',
      hostInfo: {name: 'test-host', version: '1'}, hostCapabilities: {}, hostContext: HOST_CONTEXT}}, '*');
  } else if (m.method === 'ui/notifications/initialized') {
    const view = iframe.contentWindow;
    view.postMessage({jsonrpc: '2.0', method: 'ui/notifications/tool-input', params: {arguments: {note_id: 'x'}}}, '*');
    view.postMessage({jsonrpc: '2.0', method: 'ui/notifications/tool-result', params: NOTE_RESULT}, '*');
    startStranger();
  } else if (m.id === 'barrier') {
    window.barrierDone = true;
  } else if (m.method === 'ui/notifications/size-changed') {
    window.lastSize = m.params;
    iframe.style.height = m.params.height + 'px';
  }
});
</script></body></html>"""


@pytest.fixture
def host_server():
    """שרת מקומי: עמוד המארח, והדף עצמו עם ה-CSP של המפרט."""
    view = note_view.build_note_view()
    # ``<`` מקודד כ-``<``: הפתק נושא ``</script>``, ובתוך ``<script>`` של המארח הוא היה סוגר את
    # הבלוק — אותה תקלה ש-``note_view._inline`` מונע בדף עצמו.
    note_json = json.dumps(_NOTE, ensure_ascii=False).replace("<", "\\u003c")
    host = _HOST_PAGE % {"note": note_json, "context": json.dumps(_HOST_CONTEXT)}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - שם שה-stdlib מחייב
            if self.path == "/host.html":
                body, headers = host, {}
            elif self.path == "/view.html":
                body, headers = view.html, {"Content-Security-Policy": _SPEC_DEFAULT_CSP}
            else:
                self.send_error(404)
                return
            data = body.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            for key, value in headers.items():
                self.send_header(key, value)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *_args):  # שקט בפלט הבדיקות
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


def test_the_view_renders_the_note_under_the_spec_default_csp(chromium_executable, host_server):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = (pw.chromium.launch(executable_path=chromium_executable)
                   if chromium_executable else pw.chromium.launch())
        try:
            page = browser.new_page(device_scale_factor=1)
            console = []
            page.on("console", lambda msg: console.append(f"{msg.type}: {msg.text}"))
            page.goto(f"{host_server}/host.html")
            poll(page, "() => window.barrierDone === true",
                 "the stranger frame posted its forged result, and the view answered the ping after it")
            view = next(f for f in page.frames if f.url.endswith("/view.html"))
            poll(view, "() => !!document.querySelector('.ck-paper')", "the note was rendered")
            poll(page, "() => !!window.lastSize && window.lastSize.height > 100",
                 "size-changed reported the rendered height")

            state = view.evaluate("""() => {
                const paper = document.querySelector('.ck-paper');
                const title = paper.querySelector('.ck-title');
                const lines = [...paper.querySelectorAll('.ck-content > .sticky-task-line')];
                return {
                    title: title.textContent,
                    titleSize: getComputedStyle(title).fontSize,
                    lines: lines.map((l) => {
                        // איפה הטקסט עצמו יושב בשורה — יישור לימין הוא מה שרואים, ולא רק ``direction``.
                        const range = document.createRange();
                        range.selectNodeContents(l);
                        const run = range.getBoundingClientRect();
                        const box = l.getBoundingClientRect();
                        return {text: l.textContent, cls: l.className, dir: getComputedStyle(l).direction,
                                attr: l.getAttribute('dir'), size: getComputedStyle(l).fontSize,
                                rightGap: Math.round(box.right - run.right)};
                    }),
                    titleDir: getComputedStyle(title).direction,
                    dirAttrs: [...document.querySelectorAll('[dir]')].map((e) => e.tagName),
                    paperBg: getComputedStyle(paper).backgroundColor,
                    paperInk: getComputedStyle(paper).color,
                    bodyBg: getComputedStyle(document.body).backgroundColor,
                    htmlBg: getComputedStyle(document.documentElement).backgroundColor,
                    theme: document.documentElement.getAttribute('data-theme'),
                    scheme: getComputedStyle(document.documentElement).colorScheme,
                    imgs: document.querySelectorAll('img').length,
                    scripts: document.querySelectorAll('body script').length,
                    forged: document.body.textContent.includes('FORGED'),
                    docHeight: Math.ceil(document.documentElement.getBoundingClientRect().height),
                };
            }""")
            pwned = page.evaluate("() => window.pwned")
            received = page.evaluate("() => window.received.map((m) => m.method || 'response')")
            last_size = page.evaluate("() => window.lastSize")
        finally:
            browser.close()

    # לחיצת היד, בסדר של המפרט
    assert received[:2] == ["ui/initialize", "ui/notifications/initialized"], received
    assert "response" in received, received  # התשובה ל-ping, שהיא המחסום
    # הפתק — כותרת, שורה לכל שורת מקור (המנוע: הכותרת כותרת, והתג של המשתמש טקסט), וצבע הנייר
    assert state["title"] == "רשימה " + _EVIL
    texts = [line["text"] for line in state["lines"]]
    assert texts == ["כותרת בעברית", " ", "English line first", "שורה בעברית עם English באמצע", _EVIL]
    assert "sticky-md-h1" in state["lines"][0]["cls"].split(), state["lines"][0]
    assert state["paperBg"] == "rgb(255, 237, 219)"
    assert state["paperInk"] == "rgb(34, 34, 34)"
    # כל שורה יורשת rtl מהדף, כמו בפתק בוובאפ — גם שורה שמתחילה באנגלית, והיא מיושרת לימין.
    # נמדד בוובאפ בכרום (תיבת הטקסט ותצוגת ה-Markdown): ``direction: rtl`` בלי תכונת ``dir``.
    assert {line["dir"] for line in state["lines"]} == {"rtl"}, state["lines"]
    assert {line["attr"] for line in state["lines"]} == {None}, state["lines"]
    english = next(line for line in state["lines"] if line["text"] == "English line first")
    assert abs(english["rightGap"]) <= 1, english
    assert state["titleDir"] == "rtl"
    assert state["dirAttrs"] == ["HTML"], state["dirAttrs"]
    # הגוף ב"גדול מאוד" (20px), והכותרת כמו בוובאפ (13px) — הערכים שהטסט של ה-CSS משווה לוובאפ.
    # שורת כותרת של Markdown בגודל שלה; ההשוואה המלאה לפתק בלוח — ``test_the_markdown_looks_like_*``.
    assert {line["size"] for line in state["lines"] if "is-text" in line["cls"].split()} == {"20px"}
    assert state["titleSize"] == "13px"
    # הדף שקוף, והערכה של המארח הוחלה
    assert state["bodyBg"] == "rgba(0, 0, 0, 0)" and state["htmlBg"] == "rgba(0, 0, 0, 0)"
    assert state["theme"] == "dark" and state["scheme"] == "dark"
    # תוכן הפתק לא יצר אלמנט ולא הריץ דבר, והתוצאה המזויפת מהמסגרת הזרה נזרקה
    assert state["imgs"] == 0 and state["scripts"] == 1
    assert pwned is None
    assert state["forged"] is False
    # הגודל שדווח הוא גובה התוכן כפי שהדפדפן מדד אותו
    assert last_size["height"] == state["docHeight"] and last_size["width"] > 0
    # ושום הפרת CSP: הסקריפט והסגנון שבתוך הדף רצים תחת ברירת המחדל של המפרט
    assert not [line for line in console if "Content Security Policy" in line or "Refused to" in line], console


# ===========================================================================
# הגובה, הגלילה והמסגרת — מה שהדפדפן פורס, ושום בדיקה בלי דפדפן אינה רואה
# ===========================================================================

#: פתק שגבוה בהרבה מהגובה הקבוע, ופתק שנכנס בו בשפע.
_LONG = {"ok": True, "note": {"id": "c" * 24, "title": "פתק ארוך", "color": "#ffeddb",
                              "content": "\n".join(f"שורה {i}: טקסט של פתק ארוך" for i in range(1, 41))}}
_SHORT = {"ok": True, "note": {"id": "d" * 24, "title": "קצר", "color": "#d7f5dd",
                               "content": "שורה אחת\nשורה שתיים"}}

#: הקורפוס של ה-Markdown: כל סוג שורה שהמנוע מרנדר בפתק — כותרות, הדגשות, קוד בשורה, מרקר,
#: קישורים (וכתובת חשופה, שהמנוע משאיר טקסט — רק ``[טקסט](כתובת)`` הוא קישור), ציטוט, קו מפריד, רשימות מקוננות, משימות, בלוקי קוד (גם בעברית ובלי שפה), טבלה עם יישור
#: ושם קובץ בתא, אלרטים בשני התחבירים, ובלוק מתקפל עם אלרט בתוכו.
_MD_CORPUS = "\n\n".join([
    "# כותרת ראשית\n## כותרת משנה\n### שלישית\nטקסט **מודגש** ו*נטוי* ו~~מחוק~~ ו`קוד בשורה` ו==מרקר==.\n"
    "קישור: [אתר](https://example.com/page) ו-[עוד אחד](https://example.org), וכתובת חשופה https://example.net\n"
    "> ציטוט בעברית\n---\nEnglish line `code` here",
    "- פריט\n  - פריט מקונן\n    - עמוק\n- [ ] משימה פתוחה\n- [x] משימה סגורה\n  - [ ] תת-משימה\n1. ממוספר\n2. שני",
    "```python\nprint('שלום')\nx = 1\n```\n```\nשורה בעברית בבלוק\nעוד שורה בעברית\n```",
    "| עמודה | Column |\n|:--|--:|\n| תא | `push_api.py:569` |\n| 12 | שורה |",
    "> [!NOTE]\n> הערה עם `קוד`\n\n> [!WARNING]\n> אזהרה\n\n> [!TIP]\n> טיפ\n\n> [!IMPORTANT]\n> חשוב\n\n> [!CAUTION]\n> זהירות",
    "::: note כותרת\nתוכן הערה\n:::\n::: danger\nסכנה\n:::\n::: success\nהצלחה\n:::\n::: question\nשאלה\n:::",
    "::: details פרטים נוספים\nתוכן מוסתר עם **הדגשה**\n::: note\nאלרט בתוך details\n:::\n:::\nאחרי",
])
_MD = {"ok": True, "note": {"id": "e" * 24, "title": "Markdown", "color": NOTE_COLORS["yellow"]["hex"],
                            "color_id": "yellow", "content": _MD_CORPUS}}
#: פתק קצר שנכנס בגובה, עם בלוק מתקפל שארוך ממנו כשהוא נפתח.
_MD_DETAILS = {"ok": True, "note": {"id": "f" * 24, "title": "מתקפל", "color": NOTE_COLORS["blue_light"]["hex"],
                                    "content": "שורה לפני\n::: details לחצו לפתיחה\n"
                                               + "\n".join(f"שורה מוסתרת {i}" for i in range(1, 31)) + "\n:::"}}
#: פתק ארוך מהגובה, עם בלוק מתקפל בסופו — כשגוללים עד הסוף ופותחים אותו, רק התוכן גדל: הגוף כבר
#: בגובה הקבוע, והדף כולו אינו משנה גודל.
_MD_DETAILS_LONG = {"ok": True, "note": {"id": "8" * 24, "title": "מתקפל בסוף", "color": NOTE_COLORS["ivory"]["hex"],
                                         "content": "\n".join(f"שורה גלויה {i}" for i in range(1, 31))
                                         + "\n::: details לחצו לפתיחה\n"
                                         + "\n".join(f"שורה מוסתרת {i}" for i in range(1, 21)) + "\n:::"}}

#: מקרה לכל בדיקה: הפתק, ההקשר שהמארח מוסר בלחיצת היד, ורוחב המסגרת. הצורה של
#: ``containerDimensions`` בתוך השיחה — ``width`` ו-``maxHeight`` — היא מה ש-Claude מוסר שם
#: (עמוד "Display modes" בתיעוד של Claude, נקרא ב-15.11.2026).
_CASES = {
    "long": (_LONG, {"containerDimensions": {"width": 600, "maxHeight": 900},
                     "availableDisplayModes": ["inline"], "displayMode": "inline"}, 600),
    "long-low-cap": (_LONG, {"containerDimensions": {"width": 600, "maxHeight": 250},
                             "availableDisplayModes": ["inline"], "displayMode": "inline"}, 600),
    "short": (_SHORT, {"containerDimensions": {"width": 600, "maxHeight": 900},
                       "availableDisplayModes": ["inline"], "displayMode": "inline"}, 600),
    "long-fullscreen": (_LONG, {"containerDimensions": {"width": 600, "maxHeight": 900},
                                "availableDisplayModes": ["inline", "fullscreen"], "displayMode": "inline"}, 600),
    "long-fullscreen-flexible": (_LONG, {"containerDimensions": {"width": 600, "maxHeight": 900},
                                         "availableDisplayModes": ["inline", "fullscreen"], "displayMode": "inline"}, 600),
    "long-zoomed": (_LONG, {"containerDimensions": {"width": 600, "maxHeight": 900},
                            "availableDisplayModes": ["inline"], "displayMode": "inline"}, 600),
    "short-safe-area": (_SHORT, {"containerDimensions": {"width": 600, "maxHeight": 900},
                                 "availableDisplayModes": ["inline"], "displayMode": "inline",
                                 "safeAreaInsets": {"top": 0, "right": 0, "bottom": 48, "left": 0}}, 600),
    "md": (_MD, {"containerDimensions": {"width": 600, "maxHeight": 900},
                 "availableDisplayModes": ["inline"], "displayMode": "inline"}, 600),
    "md-links": (_MD, {"containerDimensions": {"width": 600, "maxHeight": 900},
                       "availableDisplayModes": ["inline"], "displayMode": "inline"}, 600),
    "md-dark": (_MD, {"containerDimensions": {"width": 600, "maxHeight": 900},
                      "availableDisplayModes": ["inline"], "displayMode": "inline", **_HOST_CONTEXT}, 600),
    "md-zoomed": (_MD, {"containerDimensions": {"width": 600, "maxHeight": 900},
                        "availableDisplayModes": ["inline"], "displayMode": "inline"}, 600),
    "md-details": (_MD_DETAILS, {"containerDimensions": {"width": 600, "maxHeight": 900},
                                 "availableDisplayModes": ["inline"], "displayMode": "inline"}, 600),
    "md-details-long": (_MD_DETAILS_LONG, {"containerDimensions": {"width": 600, "maxHeight": 900},
                                           "availableDisplayModes": ["inline"], "displayMode": "inline"}, 600),
}

#: ``hostCapabilities`` שהמארח מוסר בלחיצת היד, כשהוא אינו ריק. ``openLinks`` — "Host supports opening
#: external URLs" (``specification/2026-01-26/apps.mdx``, ``HostCapabilities``).
_CAPS = {"md-links": {"openLinks": {}}}

#: מארח שמחיל כל ``size-changed`` על המסגרת — מה שהמפרט מחייב במסגרת גמישה ("hosts MUST listen
#: for ``ui/notifications/size-changed`` ... and update the iframe dimensions accordingly"). על
#: בקשת מסך מלא הוא עונה ``{mode}``, ואחריה ``host-context-changed``, באחת משתי הצורות שמארחים
#: אמיתיים נוקטים: מסגרת בגובה קבוע, כמו Claude ("Display modes": ``width`` ו-``height``) — ומאז
#: אינו מחיל דיווחים, כי הגובה שלו; או גובה גמיש עם תקרה, כמו ``basic-host`` של ext-apps
#: (``{ width, maxHeight: 6000 }``) — ואז ממשיך להחיל.
_FRAME_HOST = """<!doctype html><html><head><meta charset="utf-8"></head><body style="margin:0">
<iframe id="view" src="%(view)s" sandbox="allow-scripts"
        style="width:%(width)dpx;height:80px;border:0;display:block"></iframe>
<script>
const NOTE_RESULT = {content: [{type: 'text', text: JSON.stringify(%(note)s)}]};
const HOST_CONTEXT = %(context)s;
const iframe = document.getElementById('view');
window.sizes = [];
window.modeRequests = [];
window.openLinks = [];
window.fixedFrame = false;
// מחסום: ``ping`` הלוך-חזור. הודעות מאותה מסגרת מגיעות בסדר שנשלחו, ולכן כשהתשובה כאן — כל מה
// שהדף שלח לפניה כבר הגיע.
window.barrier = () => {
  window.barrierDone = false;
  iframe.contentWindow.postMessage({jsonrpc: '2.0', id: 'barrier', method: 'ping', params: {}}, '*');
};
window.addEventListener('message', (event) => {
  if (event.source !== iframe.contentWindow) return;
  const m = event.data;
  const view = iframe.contentWindow;
  if (m.method === 'ui/initialize') {
    view.postMessage({jsonrpc: '2.0', id: m.id, result: {protocolVersion: '2026-01-26',
      hostInfo: {name: 'test-host', version: '1'}, hostCapabilities: %(caps)s, hostContext: HOST_CONTEXT}}, '*');
  } else if (m.method === 'ui/notifications/initialized') {
    view.postMessage({jsonrpc: '2.0', method: 'ui/notifications/tool-result', params: NOTE_RESULT}, '*');
  } else if (m.method === 'ui/open-link') {
    // התשובה של המפרט להצלחה: ``result: {}  // Empty result on success`` ("Requests (View → Host)").
    window.openLinks.push(m.params);
    view.postMessage({jsonrpc: '2.0', id: m.id, result: {}}, '*');
  } else if (m.id === 'barrier') {
    window.barrierDone = true;
  } else if (m.method === 'ui/notifications/size-changed') {
    window.sizes.push(m.params);
    if (!window.fixedFrame) iframe.style.height = m.params.height + 'px';
  } else if (m.method === 'ui/request-display-mode') {
    window.modeRequests.push(m.params);
    iframe.style.width = '800px';
    view.postMessage({jsonrpc: '2.0', id: m.id, result: {mode: 'fullscreen'}}, '*');
    if (%(fixed_fullscreen)s) {
      window.fixedFrame = true;
      iframe.style.height = '600px';
      view.postMessage({jsonrpc: '2.0', method: 'ui/notifications/host-context-changed',
        params: {displayMode: 'fullscreen', containerDimensions: {width: 800, height: 600}}}, '*');
    } else {
      view.postMessage({jsonrpc: '2.0', method: 'ui/notifications/host-context-changed',
        params: {displayMode: 'fullscreen', containerDimensions: {width: 800, maxHeight: 6000}}}, '*');
    }
  }
});
</script></body></html>"""


@pytest.fixture
def frame_host():
    """שרת מקומי ל-``_CASES``: ``/<מקרה>.html`` הוא המארח, ו-``/view.html`` הדף עם ה-CSP של המפרט."""
    view = note_view.build_note_view()
    pages = {}
    for name, (note, context, width) in _CASES.items():
        note_json = json.dumps(note, ensure_ascii=False).replace("<", "\\u003c")
        pages[f"/{name}.html"] = _FRAME_HOST % {
            "note": note_json, "context": json.dumps(context), "width": width,
            "view": _ZOOMED_VIEW_PATH if name.endswith("-zoomed") else "/view.html",
            "fixed_fullscreen": "false" if name.endswith("-flexible") else "true",
            "caps": json.dumps(_CAPS.get(name, {})),
        }

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - שם שה-stdlib מחייב
            if self.path in pages:
                body, headers = pages[self.path], {}
            elif self.path == "/view.html":
                body, headers = view.html, {"Content-Security-Policy": _SPEC_DEFAULT_CSP}
            elif self.path == _ZOOMED_VIEW_PATH:
                body, headers = _zoomed(view.html), {"Content-Security-Policy": _SPEC_DEFAULT_CSP}
            else:
                self.send_error(404)
                return
            data = body.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            for key, value in headers.items():
                self.send_header(key, value)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *_args):  # שקט בפלט הבדיקות
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


#: **הגדלת הטקסט של WebView, בכרום של שולחן העבודה — דרך ``TextZoomFactor`` האמיתי.** אנדרואיד
#: מגדיל כל גופן ב-WebView לפי גודל הגופן של המערכת (``AwSettings.java``), דרך ``TextZoomFactor`` של
#: המסגרת. ל-DevTools אין פקודה בשבילו, אבל ל-Blink יש מסלול שקובע אותו מתוך הדף: כש-
#: ``scaleAllFontsIfNoMetaTextScaleTag`` דלוק, הוספה או הסרה של ``<meta name="text-scale">`` קוראת ל-
#: ``frame->SetTextZoomFactor(GetSettings()->GetAccessibilityFontScaleFactor())``
#: (``Document::SetTextScaleMetaTagPresent``), ו-``LocalFrame::SetTextZoomFactor`` מאפס את הגורם רק
#: כשהתגית קיימת. לכן הדפדפן עולה עם שתי ההגדרות, והדף מקבל בראשו סקריפט שמוסיף את התגית ומסיר
#: אותה — ומשם המסגרת מוגדלת ב-``_TEXT_ZOOM``, בדיוק במנגנון של WebView. ``textSizeAdjustEnabled`` —
#: מה ש-WebView מודרני מציב ("The modern approach is for CSS to always honor text-size-adjust",
#: ``aw_settings.cc``); ``_TEXT_ZOOM_ARGS_OLD`` בלעדיו, כמו WebView ישן שמתעלם מהתכונה.
_TEXT_ZOOM = 1.3
_ZOOMED_VIEW_PATH = "/view-zoomed.html"
_ZOOM_SETTINGS = f"scaleAllFontsIfNoMetaTextScaleTag=true,accessibilityFontScaleFactor={_TEXT_ZOOM}"
_TEXT_ZOOM_ARGS = [f"--blink-settings={_ZOOM_SETTINGS},textSizeAdjustEnabled=true"]
_TEXT_ZOOM_ARGS_OLD = [f"--blink-settings={_ZOOM_SETTINGS}"]
_ZOOM_FLIP = ("<script>(function () { var m = document.createElement('meta'); m.name = 'text-scale';"
              " m.content = 'scale'; document.head.appendChild(m); m.remove(); })();</script>")


def _zoomed(html):
    # ה-``<head>`` של השלד — הראשון בדף, לפני כל חלק שנכנס לתוכו (המנוע של הוובאפ מכיל את המחרוזת).
    # הסקריפט ראשון, כדי שהמסגרת תהיה מוגדלת כבר כשהדף מודד בעלייה, כמו ב-WebView.
    marker = "<head>"
    at = html.index(marker) + len(marker)
    assert "/* ---- " not in html[:at], "the first <head> is not the shell's"
    return html[:at] + _ZOOM_FLIP + html[at:]


def _launch(pw, chromium_executable, args=None):
    launch = {"args": args} if args else {}
    return (pw.chromium.launch(executable_path=chromium_executable, **launch)
            if chromium_executable else pw.chromium.launch(**launch))


def _open(pw, chromium_executable, url, *, reduced_motion=None, args=None, console=None, screen=None, init_script=None,
          touch=False):
    """``touch=True`` — מסך מגע: ``has_touch`` של Playwright מדליק ``(pointer: coarse)``, ונמדד שגם בתוך
    המסגרת המבודדת (בלעדיו — ``fine``)."""
    browser = _launch(pw, chromium_executable, args)
    page = browser.new_page(device_scale_factor=1, viewport={"width": 1000, "height": 1000}, has_touch=touch,
                            **({"screen": screen} if screen else {}))
    if init_script:
        page.add_init_script(init_script)
    if console is not None:
        page.on("console", lambda msg: console.append(f"{msg.type}: {msg.text}"))
    if reduced_motion:
        page.emulate_media(reduced_motion=reduced_motion)
    page.goto(url)
    view = None
    for _ in range(100):
        view = next((f for f in page.frames if f.url.endswith(("/view.html", _ZOOMED_VIEW_PATH))), None)
        if view:
            break
        page.wait_for_timeout(50)
    assert view, "the view frame never loaded"
    poll(view, "() => !!document.querySelector('.ck-paper')", "the note was rendered")
    return browser, page, view


def _settled(page, view, what):
    """הדיווח האחרון הוא הגובה שהדף מודד **עכשיו**, והמסגרת בגובה הזה — הדף והמארח הסכימו.

    השוואה לגובה שהדף מודד, ולא רק בין הדיווח למסגרת: מיד אחרי הרינדור המסגרת עוד בגובה של
    "טוען…", שגם הוא דווח, והסכמה עליו אינה הסכמה על הפתק. שני ההקשרים (המארח והדף) נדגמים מכאן,
    כי המארח אינו יכול לקרוא מסגרת מ-origin אחר.
    """
    deadline = time.monotonic() + WAIT_S
    while True:
        doc = view.evaluate("() => Math.ceil(document.documentElement.getBoundingClientRect().height)")
        state = page.evaluate("""() => ({
            last: window.sizes[window.sizes.length - 1] || null,
            frame: Math.round(document.getElementById('view').getBoundingClientRect().height),
            count: window.sizes.length})""")
        if state["last"] and state["last"]["height"] == doc == state["frame"]:
            return state
        if time.monotonic() > deadline:
            raise AssertionError(f"לא התקיים תוך {WAIT_S} שניות: {what} — נצפה לאחרונה: {state!r}, doc={doc}")
        time.sleep(0.1)


_BODY_STATE = """() => {
    const body = document.querySelector('.ck-body');
    const shown = (sel) => getComputedStyle(document.querySelector(sel)).display !== 'none';
    return {scrollTop: body.scrollTop, clientHeight: body.clientHeight, scrollHeight: body.scrollHeight,
            bar: shown('.ck-controls'), scroll: shown('.ck-scroll-btns'), expand: shown('.ck-expand'),
            up: document.querySelector('.ck-up').disabled, down: document.querySelector('.ck-down').disabled,
            doc: Math.ceil(document.documentElement.getBoundingClientRect().height)};
}"""


def test_a_long_note_stops_at_the_fixed_height_and_scrolls_inside(chromium_executable, frame_host):
    """פתק ארוך: התצוגה בגובה של פתק חדש בוובאפ, הגוף נגלל בתוכה, ו-▼ זז שלושה רבעים מהגובה הגלוי —
    ברכות. לפני התיקון התצוגה ביקשה את כל הגובה, ו-Claude חתך אותה בלי גלילה."""
    from playwright.sync_api import sync_playwright
    from test_mcp_note_view import _new_note_height

    with sync_playwright() as pw:
        browser, page, view = _open(pw, chromium_executable, f"{frame_host}/long.html")
        try:
            settled = _settled(page, view, "the frame took the reported height")
            top = view.evaluate(_BODY_STATE)
            inside = view.evaluate("""() => ({
                controlsBottom: document.querySelector('.ck-controls').getBoundingClientRect().bottom,
                viewport: innerHeight})""")
            # **העיגול של הדפדפן, ולא של פייתון:** ``Math.round`` מעגל חצי כלפי מעלה, ו-``round`` של
            # פייתון לזוגי — בגובה 286 הצעד הוא 214.5, הדף גולל 215 ופייתון ציפה ל-214 (נמדד).
            step = view.evaluate("(h) => Math.round(h * 0.75)", top["clientHeight"])
            # **רכות, בלי תלות בתזמון:** הלחיצה והדגימה באותו סקריפט. גלילה רכה מתחילה לזוז רק
            # בפריים הבא, ולכן מיד אחרי הלחיצה המיקום עוד לא זז; קפיצה הייתה כבר ב-``step`` (ראו
            # ``test_reduced_motion_makes_the_step_a_jump``, שבודק את אותה דגימה בכיוון ההפוך).
            early = view.evaluate("""() => {
                document.querySelector('.ck-down').click();
                return document.querySelector('.ck-body').scrollTop;
            }""")
            poll(view, "(step) => document.querySelector('.ck-body').scrollTop === step",
                 "the ▼ step settled at three quarters of the visible height", step)
            view.evaluate("() => { const b = document.querySelector('.ck-body'); "
                          "b.style.scrollBehavior = 'auto'; b.scrollTop = b.scrollHeight; }")
            poll(view, "() => document.querySelector('.ck-down').disabled === true", "▼ is disabled at the bottom")
            bottom = view.evaluate(_BODY_STATE)
            # גלגלת מעל הגוף גוללת אותו — הגלילה במחשב, בלי הכפתורים. אחרונה בבדיקה: גלילת הגלגלת
            # רכה בכרום וממשיכה ברקע, ולכן שום צעד אחריה אינו נשען על המיקום.
            box = page.locator("#view").bounding_box()
            page.mouse.move(box["x"] + box["width"] / 2, box["y"] + 150)
            page.mouse.wheel(0, -120)
            poll(view, "(at) => document.querySelector('.ck-body').scrollTop < at",
                 "the wheel scrolled the body up", bottom["scrollTop"])
        finally:
            browser.close()

    assert settled["last"]["height"] == _new_note_height(), settled
    assert top["scrollHeight"] > top["clientHeight"] * 2, top
    assert top["bar"] and top["scroll"] and not top["expand"], top
    assert top["up"] is True and top["down"] is False, top
    # הכפתורים בתוך המסגרת, ולא מתחת לה — שם המארח היה חותך אותם.
    assert inside["controlsBottom"] <= inside["viewport"], inside
    assert early == 0 and step > 0, (early, step)
    assert bottom["up"] is False and bottom["down"] is True, bottom


def test_reduced_motion_makes_the_step_a_jump(chromium_executable, frame_host):
    """מי שביקש במערכת פחות תנועה מקבל קפיצה מיידית — אותו צעד, בלי אנימציה."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser, page, view = _open(pw, chromium_executable, f"{frame_host}/long.html", reduced_motion="reduce")
        try:
            _settled(page, view, "the frame took the reported height")
            result = view.evaluate("""() => {
                const body = document.querySelector('.ck-body');
                const step = Math.round(body.clientHeight * 0.75);
                document.querySelector('.ck-down').click();
                return {now: body.scrollTop, step};
            }""")
        finally:
            browser.close()

    assert result["now"] == result["step"], result


def test_a_lower_host_cap_wins_over_the_fixed_height(chromium_executable, frame_host):
    """``maxHeight`` של המארח נמוך מהגובה הקבוע — התצוגה מצייתת לו, כדי שלא תיחתך."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser, page, view = _open(pw, chromium_executable, f"{frame_host}/long-low-cap.html")
        try:
            settled = _settled(page, view, "the frame took the reported height")
            state = view.evaluate(_BODY_STATE)
        finally:
            browser.close()

    assert settled["last"]["height"] == 250, settled
    assert state["scroll"] and state["scrollHeight"] > state["clientHeight"], state


def test_a_short_note_shrinks_to_its_last_line(chromium_executable, frame_host):
    """פתק קצר מהגובה הקבוע: התצוגה בגובה התוכן, בלי שורת כפתורים."""
    from playwright.sync_api import sync_playwright
    from test_mcp_note_view import _new_note_height

    with sync_playwright() as pw:
        browser, page, view = _open(pw, chromium_executable, f"{frame_host}/short.html")
        try:
            settled = _settled(page, view, "the frame took the reported height")
            state = view.evaluate(_BODY_STATE)
        finally:
            browser.close()

    assert settled["last"]["height"] < _new_note_height() / 2, settled
    assert settled["last"]["height"] == state["doc"], (settled, state)
    assert state["scrollHeight"] == state["clientHeight"], state
    assert not state["bar"], state


def test_a_stale_frame_height_from_the_host_is_corrected(chromium_executable, frame_host):
    """**השטח המת.** המארח מציב למסגרת גובה ישן, בלי שהתוכן זז — והתצוגה מדווחת שוב את הגובה שלה.

    כך נראה ב-Claude אחרי סגירה ופתיחה של האפליקציה: שטח ריק מתחת לפתק, שנעלם רק בפתיחה מחדש של
    התצוגה. לפני התיקון הדף שתק כאן — ``ResizeObserver`` על ``html``/``body`` אינו רואה מסגרת
    שגדלה מעל תוכן שלא השתנה.
    """
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser, page, view = _open(pw, chromium_executable, f"{frame_host}/short.html")
        try:
            before = _settled(page, view, "the frame took the reported height")
            page.evaluate("() => { document.getElementById('view').style.height = '700px'; }")
            after = poll(page, """(count) => {
                const frame = document.getElementById('view').getBoundingClientRect().height;
                const last = window.sizes[window.sizes.length - 1];
                return {ok: window.sizes.length > count && Math.round(frame) === last.height, frame, last,
                        count: window.sizes.length};
            }""", "the view reported its height again, and the frame shrank back", before["count"])
        finally:
            browser.close()

    assert after["last"]["height"] == before["last"]["height"], (before, after)
    assert after["frame"] < 700, after


def test_a_long_note_keeps_its_height_when_the_width_changes(chromium_executable, frame_host):
    """פתק ארוך מדווח את אותו גובה בכל רוחב — עמודה שהצטרה (רשימת השיחות שנפתחה בצד) אינה
    משנה את הגובה שלו, ולכן אינה יכולה להשאיר מסגרת ישנה בגובה אחר."""
    from playwright.sync_api import sync_playwright
    from test_mcp_note_view import _new_note_height

    heights = []
    with sync_playwright() as pw:
        browser, page, view = _open(pw, chromium_executable, f"{frame_host}/long.html")
        try:
            for width in (600, 360, 900, 420):
                page.evaluate("(w) => { document.getElementById('view').style.width = w + 'px'; }", width)
                poll(view, "(w) => window.innerWidth === w", "the frame took the new width", width)
                heights.append(_settled(page, view, f"settled at width {width}")["last"]["height"])
        finally:
            browser.close()

    assert heights == [_new_note_height()] * 4, heights


def test_fullscreen_appears_only_when_offered_and_fills_the_fixed_frame(chromium_executable, frame_host):
    """המארח מונה ``fullscreen`` — הכפתור מוצג; לחיצה מבקשת מסך מלא, והפתק ממלא את המסגרת הקבועה,
    עם הגוף שנגלל בתוכה. כשהמארח אינו מונה אותו (``long.html``) — אין כפתור (נבדק למעלה)."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser, page, view = _open(pw, chromium_executable, f"{frame_host}/long-fullscreen.html")
        try:
            _settled(page, view, "the frame took the reported height")
            inline = view.evaluate(_BODY_STATE)
            view.click(".ck-expand")
            # שני התנאים: המחלקה מגיעה בהודעה, והגובה החדש של המסגרת מגיע לחלון הפנימי בפריסה הבאה.
            poll(view, "() => document.documentElement.classList.contains('ck-fill') && innerHeight === 600",
                 "the view got the fixed frame and filled it")
            full = view.evaluate("""() => {
                const root = document.getElementById('ck-note-root').getBoundingClientRect();
                const paper = document.querySelector('.ck-paper').getBoundingClientRect();
                return {rootH: root.height, paperBottom: paper.bottom, viewport: innerHeight,
                        expandShown: getComputedStyle(document.querySelector('.ck-expand')).display !== 'none'};
            }""")
            body = view.evaluate(_BODY_STATE)
            requests = page.evaluate("() => window.modeRequests")
        finally:
            browser.close()

    assert inline["expand"] is True, inline
    assert requests == [{"mode": "fullscreen"}], requests
    assert full["viewport"] == 600 and full["rootH"] == 600, full
    assert abs(full["paperBottom"] - (600 - 4)) <= 1, full
    assert full["expandShown"] is False, full
    # במסך מלא אין שורת כפתורים — לא ▲▼ — והגוף נגלל בעצמו (באצבע או בגלגלת).
    assert body["bar"] is False and body["scroll"] is False and body["scrollHeight"] > body["clientHeight"], body


def test_the_bottom_safe_area_pads_the_view(chromium_executable, frame_host):
    """``safeAreaInsets.bottom`` נכנס כריפוד בתחתית — מה שמכסה שם (שורת ההודעה) אינו מסתיר את הפתק."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser, page, view = _open(pw, chromium_executable, f"{frame_host}/short-safe-area.html")
        try:
            pads = view.evaluate("""() => {
                const s = getComputedStyle(document.getElementById('ck-note-root'));
                return [s.paddingTop, s.paddingBottom];
            }""")
        finally:
            browser.close()

    assert pads == ["4px", "52px"], pads


def test_flexible_fullscreen_drops_the_conversation_height(chromium_executable, frame_host):
    """מסך מלא שהמארח משאיר בגובה גמיש: הגובה הקבוע של השיחה אינו חל, והפתק גדל לכל הגובה שלו —
    במקום כרטיס של שיחה בתוך מסך ריק. כך נמצא ב-``basic-host`` של ext-apps."""
    from playwright.sync_api import sync_playwright
    from test_mcp_note_view import _new_note_height

    with sync_playwright() as pw:
        browser, page, view = _open(pw, chromium_executable, f"{frame_host}/long-fullscreen-flexible.html")
        try:
            inline = _settled(page, view, "the inline frame took the reported height")
            view.click(".ck-expand")
            poll(view, "() => document.documentElement.classList.contains('ck-expanded')", "the view left the conversation height")
            full = poll(page, """(cap) => {
                const last = window.sizes[window.sizes.length - 1];
                const frame = document.getElementById('view').getBoundingClientRect().height;
                return {ok: last.height > cap && Math.round(frame) === last.height, last, frame};
            }""", "the view reported its full height and the frame grew", _new_note_height())
            state = view.evaluate(_BODY_STATE)
        finally:
            browser.close()

    assert inline["last"]["height"] == _new_note_height(), inline
    assert state["scrollHeight"] == state["clientHeight"] and not state["scroll"], state
    assert full["last"]["height"] == state["doc"], (full, state)


@pytest.mark.parametrize("webview", ["modern", "old"])
def test_the_system_text_zoom_is_measured_and_undone(chromium_executable, frame_host, webview):
    """WebView שמגדיל כל גופן ב-130% (גודל הגופן של המערכת באנדרואיד): הדף מודד את ההגדלה ומבטל
    אותה, והפתק בגודל של הוובאפ — גוף, כותרת וכפתורים. לפני התיקון הגוף יצא 26px, ובגובה הקבוע
    נכנסו פחות שורות.

    **WebView מודרני** מכבד ``text-size-adjust``, והפיצוי עובר דרכו: גם הגופן וגם מה שנגזר ממנו ב-
    ``em`` (הגובה המינימלי של שורה, 1.35em) כמו בוובאפ. **WebView ישן** מתעלם מהתכונה, והדף חוזר
    לחלוקה של הגופנים: הגופן כמו בוובאפ, וה-``em`` נשאר של הגודל שלפני ההגדלה — המגבלה שבגללה
    החלוקה אינה הדרך הראשית. נבדק גם שהאמולציה עצמה פעילה: בלעדיה הבדיקה הייתה עוברת על כלום."""
    from playwright.sync_api import sync_playwright
    from test_mcp_note_view import _new_note_height

    args = _TEXT_ZOOM_ARGS if webview == "modern" else _TEXT_ZOOM_ARGS_OLD
    with sync_playwright() as pw:
        browser, page, view = _open(pw, chromium_executable, f"{frame_host}/long-zoomed.html", args=args)
        try:
            settled = _settled(page, view, "the frame took the reported height")
            state = view.evaluate("""() => {
                // ``auto`` — בלי לרשת את הפיצוי, כלומר ההגדלה של המסגרת כמו שהיא.
                const probe = document.createElement('span');
                probe.style.cssText = 'font-size: 100px; text-size-adjust: auto';
                document.body.appendChild(probe);
                const zoomed = getComputedStyle(probe).fontSize;
                probe.remove();
                const root = getComputedStyle(document.documentElement);
                const line = getComputedStyle(document.querySelector('.ck-content .sticky-task-line'));
                const size = (sel) => getComputedStyle(document.querySelector(sel)).fontSize;
                return {zoomed, scale: root.getPropertyValue('--ck-text-scale').trim(), adjust: root.textSizeAdjust,
                        line: line.fontSize, lineMin: line.minHeight, title: size('.ck-title'), button: size('.ck-down')};
            }""")
        finally:
            browser.close()

    assert state["zoomed"] == f"{round(100 * _TEXT_ZOOM)}px", state  # האמולציה פעילה
    # ``.ck-down`` הוא כפתור אייקון (``.ck-btn.ck-icon``, 18px), ולא כפתור טקסט (16px).
    assert (state["line"], state["title"], state["button"]) == ("20px", "13px", "18px"), state
    if webview == "modern":
        assert state["adjust"].endswith("%") and abs(float(state["adjust"][:-1]) - 100 / _TEXT_ZOOM) < 1e-3, state
        assert state["scale"] == "", state
        assert state["lineMin"] == "27px", state  # 1.35em של 20px — כמו בוובאפ
    else:
        assert state["adjust"] == "auto", state
        assert float(state["scale"]) == _TEXT_ZOOM, state
        assert state["lineMin"] != "27px", state  # המגבלה של החלוקה: ה-em של הגודל שלפני ההגדלה
    assert settled["last"]["height"] == _new_note_height(), settled


# ===========================================================================
# ה-Markdown — אותו פתק כמו בוובאפ
# ===========================================================================

#: מה שמודד את המכל ולא את הסגנון: רוחב וגובה מחושבים, ונקודות מוצא שנגזרות מהם. התצוגה והפתק
#: בלוח ברוחב שונה, וההבדל הזה אינו "פתק אחר".
_GEOMETRY = ("width", "height", "inline-size", "block-size", "transform-origin", "perspective-origin")

#: הסגנון המחושב של כל אלמנט מתחת לשורש התוכן, בסדר המסמך, עם ``::before``, ``::after`` ו-
#: ``::marker``. ``font-family`` שזהה לזה של השורש נרשם כ"עובר בירושה": הגופן של הגוף הוא של
#: המשטח (בתצוגה — של Claude, ``--font-sans``), ומה שנבדק הוא שהתוכן אינו מחליף אותו אלא איפה
#: שהמנוע מחליף אותו (קוד). ``skip`` — אלמנטים שקיימים רק בצד אחד, בכוונה.
_DUMP = """([selector, geometry, skip]) => {
  const root = document.querySelector(selector);
  const rootFont = getComputedStyle(root).fontFamily;
  const omit = new Set(geometry);
  const read = (cs) => { const o = {};
    for (let i = 0; i < cs.length; i++) { const p = cs[i]; if (omit.has(p) || p.startsWith('--')) continue;
      const v = cs.getPropertyValue(p); o[p] = (p === 'font-family' && v === rootFont) ? '<inherited>' : v; }
    return o; };
  const pseudo = (el, which) => { const cs = getComputedStyle(el, which);
    return (cs.content === 'none' || cs.content === 'normal') ? null : read(cs); };
  const out = [];
  const walk = (el, path) => {
    const cs = getComputedStyle(el);
    out.push({path, tag: el.tagName, cls: typeof el.className === 'string' ? el.className : '',
              s: read(cs), before: pseudo(el, '::before'), after: pseudo(el, '::after'),
              marker: cs.display === 'list-item' ? read(getComputedStyle(el, '::marker')) : null});
    [...el.children].filter((kid) => !skip.some((sel) => kid.matches(sel)))
      .forEach((kid, i) => walk(kid, path + '/' + i));
  };
  [...root.children].forEach((kid, i) => walk(kid, String(i)));
  // ערכת הצבעים שבשימוש, ולא הערך המוצהר: צבעי המערכת נפתרים לפיה ("Effects of the Used Color
  // Scheme", CSS Color Adjustment 1).
  const probe = document.createElement('span');
  probe.style.cssText = 'color: CanvasText; background-color: Canvas';
  root.appendChild(probe);
  const scheme = [getComputedStyle(probe).color, getComputedStyle(probe).backgroundColor];
  probe.remove();
  return {elements: out, scheme, paper: getComputedStyle(root.closest('.sticky-note')).backgroundColor};
}"""

#: **מה שקיים רק בלוח, בכוונה.** כפתור ההעתקה של בלוק קוד — מחוץ לתחום של התצוגה (``read-only``
#: במנוע אינו בונה אותו).
_WEBAPP_ONLY = [".sticky-md-code-copy"]

#: **ההבדלים שמכוונים, ולמה.** כל אחד מהם חייב גם להופיע בהשוואה — אחרת הרשימה התיישנה ומסתירה
#: מקום שבו אין הבדל בכלל. ``(מאפיין, בתצוגה, בלוח)``:
_INTENDED = {
    # ``.sticky-note-tasks { cursor: text }`` ב-``sticky-notes.css`` — "הרמז שאפשר ללחוץ ולחזור
    # לעריכה". התצוגה לקריאה בלבד, ואין לאן לחזור.
    ("cursor", "auto", "text"): "the board hints that a click returns to editing",
    # ``.sticky-task-box[disabled] { cursor: progress }`` ב-``sticky-notes.css``: בלוח צ'קבוקס מושבת
    # פירושו "שמירה ממתינה". בתצוגה הוא מושבת כי היא לקריאה בלבד, ואין שם שמירה.
    ("cursor", "default", "progress"): "on the board a disabled checkbox means a save is pending",
    # הלוח אינו מצהיר על ערכת צבעים כלל (``normal``), והנייר בתצוגה מצהיר ``light`` כי הדף כולו
    # ``light dark``. מה שקובע הוא הערכה שבשימוש — ``scheme`` — והיא נבדקת בנפרד, שווה בשני הצדדים.
    ("color-scheme", "light", "normal"): "the board declares no scheme; the paper declares light",
}


def _webapp_note(pw, chromium_executable, monkeypatch, content, color_id):
    """אותו תוכן, כפי שהלוח בוובאפ מציג אותו: ``sticky-notes.js`` האמיתי, מול ה-blueprint האמיתי
    ודמה של המסד (``tests/test_sticky_notes_live_sync_browser.py``), בגודל הטקסט של ברירת המחדל
    ועם קבצי העיצוב בסדר של הלוח."""
    flask = pytest.importorskip("flask")
    import test_sticky_notes_live_sync_browser as live
    from _notes_mongo_fake import USER, make_client
    from test_mcp_note_view import _board_load_order
    from webapp.app import NOTE_FONT_SIZE_DEFAULT

    monkeypatch.setattr(live, "STYLESHEETS", tuple(s for s in _board_load_order(".css") if s in live.STYLESHEETS))
    client = make_client(monkeypatch, flask)
    client.db.note_boards.docs.append({"_id": live.BOARD, "user_id": USER, "name": "לוח"})
    client.pages = []
    note_id = "9" * 24
    client.db.sticky_notes.docs.append(live._doc(note_id, content, color=color_id, width=560, height=700))
    # כמו ``_note_fonts_head.html``: המחלקה של הגודל על ``<html>``, ו"רגיל" הוא היעדר מחלקה.
    size_class = "" if NOTE_FONT_SIZE_DEFAULT == "normal" else f"sticky-font-{NOTE_FONT_SIZE_DEFAULT}"
    script = f"document.addEventListener('DOMContentLoaded', () => document.documentElement.classList.add('{size_class}'))"
    browser = _launch(pw, chromium_executable)
    try:
        lp = live.LivePage(browser, client, live.BOARD_MANAGER, before_goto=lambda p: p.add_init_script(script))
        try:
            lp.wait_note(note_id)
            # **הצ'קבוקס במצב של התצוגה — מושבת** (המנוע במצב קריאה בלבד). זה מצב של ה-DOM, לא
            # עיצוב, ובלעדיו ההשוואה הייתה מודדת את ההבדל בין פקד פעיל למושבת.
            lp.page.evaluate("(sel) => document.querySelectorAll(sel).forEach((box) => { box.disabled = true; })",
                             lp.sel(note_id, ".sticky-task-box"))
            dump = lp.page.evaluate(_DUMP, [lp.sel(note_id, ".sticky-note-tasks"), list(_GEOMETRY), _WEBAPP_ONLY])
            assert not lp.errors, lp.errors
        finally:
            lp.close()
    finally:
        browser.close()
    return dump


def _style_diffs(view, webapp, extra=None):
    """כל מאפיין שבו אלמנט בתצוגה שונה מהאלמנט המקביל בלוח — אחרי שהמבנה עצמו זהה. ההבדלים
    שב-``_INTENDED`` מוחזרים בנפרד, כדי שהבדיקה תוודא שהם באמת שם."""
    shape = lambda dump: [(e["path"], e["tag"], e["cls"]) for e in dump["elements"]]  # noqa: E731
    assert shape(view) == shape(webapp), "the engine built a different structure"
    diffs = []
    for mine, theirs in zip(view["elements"], webapp["elements"]):
        for part in ("s", "before", "after", "marker"):
            a, b = mine[part] or {}, theirs[part] or {}
            if (mine[part] is None) != (theirs[part] is None):
                diffs.append((mine["path"], mine["cls"], part, "exists" if mine[part] else None,
                              "exists" if theirs[part] else None))
                continue
            diffs += [(mine["path"], mine["cls"], part + ":" + prop, a.get(prop), b.get(prop))
                      for prop in sorted(set(a) | set(b)) if a.get(prop) != b.get(prop)]
    intended = {key: 0 for key in {**_INTENDED, **(extra or {})}}
    real = []
    for diff in diffs:
        key = (diff[2].split(":", 1)[1], diff[3], diff[4])
        if key in intended:
            intended[key] += 1
        else:
            real.append(diff)
    return real, intended


@pytest.mark.parametrize("case", ["md", "md-dark", "md-zoomed"])
def test_the_markdown_looks_like_the_same_note_on_the_board(chromium_executable, frame_host, monkeypatch, case):
    """כל אלמנט שהמנוע בונה בתצוגה מקבל **אותו סגנון מחושב** כמו האלמנט המקביל בפתק בלוח — מאפיין
    מול מאפיין, כולל ``::before``/``::after``/``::marker``. הלוח הוא הקוד האמיתי של הוובאפ, לא עמוד
    שנבנה ביד לבדיקה. נבדק גם בערכה הכהה של המארח (הנייר בצבע קבוע, ולכן התוכן אינו משתנה), וגם
    בהגדלת הטקסט של אנדרואיד (הפיצוי חל על כל ה-Markdown, לא רק על הגוף). ולצד זה — אפס הפרות CSP:
    הסגנון והמנוע שנכנסו לדף רצים תחת ברירת המחדל של המפרט."""
    from playwright.sync_api import sync_playwright

    note = _CASES[case][0]["note"]
    console: list[str] = []
    with sync_playwright() as pw:
        webapp = _webapp_note(pw, chromium_executable, monkeypatch, note["content"], note["color_id"])
        zoomed = case.endswith("-zoomed")
        browser, page, view = _open(pw, chromium_executable, f"{frame_host}/{case}.html",
                                    args=_TEXT_ZOOM_ARGS if zoomed else None, console=console)
        try:
            _settled(page, view, "the frame took the reported height")
            mine = view.evaluate(_DUMP, [".ck-content", list(_GEOMETRY), []])
            zoom = view.evaluate("""() => { const probe = document.createElement('span');
                probe.style.cssText = 'font-size: 100px; text-size-adjust: auto'; document.body.appendChild(probe);
                const raw = getComputedStyle(probe).fontSize; probe.remove();
                return {raw, adjust: getComputedStyle(document.documentElement).textSizeAdjust}; }""")
        finally:
            browser.close()

    extra = {}
    if zoomed:  # האמולציה פעילה, אחרת ההשוואה הייתה עוברת על כלום
        assert zoom["raw"] == f"{round(100 * _TEXT_ZOOM)}px", zoom
        # הפיצוי עצמו: ``text-size-adjust`` שעובר בירושה לכל אלמנט, ובלוח הוא ``auto``.
        extra[("text-size-adjust", zoom["adjust"], "auto")] = "the compensation for the system text zoom"
    assert len(mine["elements"]) > 80, len(mine["elements"])
    assert mine["paper"] == webapp["paper"]
    assert mine["scheme"] == webapp["scheme"] == ["rgb(0, 0, 0)", "rgb(255, 255, 255)"], (mine["scheme"], webapp["scheme"])
    diffs, intended = _style_diffs(mine, webapp, extra)
    assert not diffs, "\n".join(map(repr, diffs[:60])) + f"\n... {len(diffs)} in total"
    assert all(intended.values()), intended
    assert not [line for line in console if "Content Security Policy" in line or "Refused to" in line], console


_LINKS = """() => [...document.querySelectorAll('.ck-content a.sticky-md-link')]
    .map((a) => ({href: a.getAttribute('href'), title: a.getAttribute('title')}))"""


def _click_links(page, view):
    """לוחץ על כל קישור בפתק, ומחכה למחסום — מה שהדף שלח בעקבות הלחיצות כבר אצל המארח."""
    links = view.locator(".ck-content a.sticky-md-link")
    for i in range(links.count()):
        links.nth(i).click()
    page.evaluate("() => window.barrier()")
    poll(page, "() => window.barrierDone === true", "the view answered the ping after the clicks")
    return page.evaluate("() => window.openLinks")


@pytest.mark.parametrize("case,expected", [
    # המארח מודיע ``openLinks`` — כל לחיצה היא בקשה אחת, עם הכתובת כמו שהיא בפתק.
    ("md-links", [{"url": "https://example.com/page"}, {"url": "https://example.org"}]),
    # המארח אינו מודיע — הקישור אינו עושה דבר, והכתובת שבריחוף היא כל מה שיש.
    ("md", []),
])
def test_a_link_goes_through_the_host_and_the_view_never_navigates(chromium_executable, frame_host, case, expected):
    """קישור בפתק: ``ui/open-link`` כשהמארח תומך, ושום דבר כשלא — ובשני המקרים הדפדפן אינו מנווט
    ואינו מנסה לפתוח חלון (``target="_blank"`` של המנוע במסגרת בלי ``allow-popups`` היה נחסם עם
    הודעה בקונסול). הכתובת מופיעה בריחוף על כל קישור."""
    from playwright.sync_api import sync_playwright

    console: list[str] = []
    with sync_playwright() as pw:
        browser, page, view = _open(pw, chromium_executable, f"{frame_host}/{case}.html", console=console)
        try:
            _settled(page, view, "the frame took the reported height")
            links = view.evaluate(_LINKS)
            opened = _click_links(page, view)
            still_here = view.evaluate("() => location.pathname + '|' + !!document.querySelector('.ck-paper')")
            frames = [f.url for f in page.frames]
        finally:
            browser.close()

    assert links == [{"href": "https://example.com/page", "title": "https://example.com/page"},
                     {"href": "https://example.org", "title": "https://example.org"}], links
    assert opened == expected
    assert still_here == "/view.html|true", still_here
    assert len(frames) == 2, frames
    assert not [line for line in console if "Blocked opening" in line or "Not allowed to navigate" in line], console


def test_opening_a_folded_block_brings_the_scroll_buttons(chromium_executable, frame_host):
    """פתק קצר עם בלוק מתקפל: סגור — אין ▲▼, כי הכול נכנס. נפתח — הוא ארוך מהגובה, ו-▲▼ מופיעים.
    גוף הפתק בגובה קבוע ואינו משנה גודל כשהתוכן שבתוכו גדל, ולכן רק צפייה בתוכן עצמו
    (``.ck-content``) רואה את זה."""
    from playwright.sync_api import sync_playwright
    from test_mcp_note_view import _new_note_height

    with sync_playwright() as pw:
        browser, page, view = _open(pw, chromium_executable, f"{frame_host}/md-details.html")
        try:
            _settled(page, view, "the frame took the reported height")
            closed = view.evaluate(_BODY_STATE)
            view.locator(".ck-content summary").click()
            poll(view, "() => getComputedStyle(document.querySelector('.ck-scroll-btns')).display !== 'none'",
                 "the scroll buttons appeared after the block opened")
            settled = _settled(page, view, "the frame took the reported height after the block opened")
            opened = view.evaluate(_BODY_STATE)
        finally:
            browser.close()

    assert closed["scroll"] is False and closed["scrollHeight"] <= closed["clientHeight"], closed
    assert opened["scroll"] is True and opened["down"] is False and opened["up"] is True, opened
    assert opened["scrollHeight"] > opened["clientHeight"], opened
    assert settled["last"]["height"] == _new_note_height(), settled


def test_a_folded_block_opened_at_the_bottom_enables_scrolling_down(chromium_executable, frame_host):
    """פתק ארוך, גלול עד הסוף (▼ מושבת), ובלוק מתקפל בתחתית. פתיחת הבלוק מוסיפה תוכן מתחת למה
    שרואים — ו-▼ חייב לחזור לפעול. **זה המקרה שרק הצפייה בתוכן רואה:** הגוף כבר בגובה הקבוע,
    ולכן לא הוא, לא ``body`` ולא ``html`` משנים גודל. בפתק קצר (הבדיקה הקודמת) גם הדף כולו גדל,
    והצפייה הישנה הייתה רואה אותו בלי קשר."""
    from playwright.sync_api import sync_playwright
    from test_mcp_note_view import _new_note_height

    with sync_playwright() as pw:
        browser, page, view = _open(pw, chromium_executable, f"{frame_host}/md-details-long.html")
        try:
            settled = _settled(page, view, "the frame took the reported height")
            # עד הסוף, דרך ``scrollTop`` (בלי ``smooth``): אירוע הגלילה מעדכן את הכפתורים.
            view.evaluate("() => { const b = document.querySelector('.ck-body'); b.style.scrollBehavior = 'auto'; b.scrollTop = b.scrollHeight; }")
            poll(view, "() => document.querySelector('.ck-down').disabled === true", "▼ is disabled at the bottom")
            bottom = view.evaluate(_BODY_STATE)
            view.locator(".ck-content summary").click()
            poll(view, "() => document.querySelector('.ck-down').disabled === false", "▼ works again after the block opened")
            opened = view.evaluate(_BODY_STATE)
        finally:
            browser.close()

    assert settled["last"]["height"] == _new_note_height(), settled
    assert bottom["scroll"] is True and bottom["down"] is True, bottom
    assert opened["scrollHeight"] > bottom["scrollHeight"] and opened["clientHeight"] == bottom["clientHeight"], (bottom, opened)
    assert opened["doc"] == bottom["doc"], (bottom, opened)  # הדף לא שינה גודל — רק התוכן


# ── עריכה ────────────────────────────────────────────────────────────────────────

#: **מארח שעורכים מולו.** מעביר קריאות לכלים (``serverTools``) ומחזיק את "השרת" בעצמו: פתק אחד,
#: ``codekeeper_show_note`` מחזיר אותו, ו-``codekeeper_note_view_save`` כותב רק כשה-hash שנשלח הוא
#: של הגרסה הנוכחית — אחרת ``conflict``, כמו ``handlers.save_note_from_view``. ה-hash כאן הוא מונה
#: גרסה בצורת 64 ספרות: לדף הוא אטום, והשוויון הוא כל מה שהוא בודק. השרת האמיתי, עם ה-hash האמיתי
#: והגרסאות, נבדק ב-``tests/test_mcp_note_view_save.py``. ``externalEdit`` — עריכה מבחוץ (הוובאפ,
#: סוכן), בשביל התנגשות. ``holdSave`` מחזיק את התשובה על שמירה עד ``releaseSave`` — שמירה שבדרך —
#: ו-``leaveFullscreen`` יוצא ממסך מלא כמו הכפתור של המארח. מסך מלא כמו ב-``_FRAME_HOST``: מסגרת
#: קבועה של 600px, או גובה גמיש.
_EDIT_HOST = """<!doctype html><html><head><meta charset="utf-8"></head><body style="margin:0">
<iframe id="view" src="/view.html" sandbox="allow-scripts"
        style="width:600px;height:80px;border:0;display:block"></iframe>
<script>
const iframe = document.getElementById('view');
const FIXED = %(fixed)s;
const shaOf = (v) => String(v).padStart(64, '0');
window.server = {version: 1, note: Object.assign(%(note)s, {content_sha256: shaOf(1)})};
window.sizes = []; window.toolCalls = []; window.modelContexts = []; window.modeRequests = [];
window.fixedFrame = false;
window.holdSave = false;
window.heldSave = null;
window.externalEdit = (content) => {
  server.version += 1;
  server.note = Object.assign({}, server.note, {content: content, content_sha256: shaOf(server.version)});
};
const answer = (obj) => ({content: [{type: 'text', text: JSON.stringify(obj)}]});
// השמירה בצד "השרת": כותבת רק כשה-hash שנשלח הוא של הגרסה הנוכחית.
function serverSave(a) {
  if (a.expected_content_sha256 !== server.note.content_sha256) {
    return answer({ok: false, error: 'conflict', hint: 'the note changed since the view received it'});
  }
  window.externalEdit(a.content);
  return answer({ok: true, note: server.note, content_changed: false});
}
window.releaseSave = () => {
  const held = window.heldSave;
  window.heldSave = null;
  window.holdSave = false;
  iframe.contentWindow.postMessage({jsonrpc: '2.0', id: held.id, result: serverSave(held.params.arguments)}, '*');
};
window.leaveFullscreen = () => {
  window.fixedFrame = false;
  iframe.contentWindow.postMessage({jsonrpc: '2.0', method: 'ui/notifications/host-context-changed',
    params: {displayMode: 'inline', containerDimensions: {width: 600, maxHeight: 900}}}, '*');
};
window.addEventListener('message', (event) => {
  if (event.source !== iframe.contentWindow) return;
  const m = event.data;
  const view = iframe.contentWindow;
  const reply = (result) => view.postMessage({jsonrpc: '2.0', id: m.id, result: result}, '*');
  if (m.method === 'ui/initialize') {
    reply({protocolVersion: '2026-01-26', hostInfo: {name: 'test-host', version: '1'},
      hostCapabilities: {serverTools: {}, updateModelContext: {text: {}}},
      hostContext: {availableDisplayModes: ['inline', 'fullscreen'], displayMode: 'inline',
                    containerDimensions: {width: 600, maxHeight: 900}}});
  } else if (m.method === 'ui/notifications/initialized') {
    view.postMessage({jsonrpc: '2.0', method: 'ui/notifications/tool-result',
      params: answer(Object.assign({ok: true, editable: true, note: server.note, target: 'board'}, %(extra)s))}, '*');
  } else if (m.method === 'tools/call') {
    window.toolCalls.push(m.params);
    const a = m.params.arguments;
    if (m.params.name === 'codekeeper_show_note') {
      reply(answer({ok: true, editable: true, note: server.note, target: 'board'}));
    } else if (m.params.name === 'codekeeper_note_view_save') {
      if (window.holdSave) window.heldSave = m;
      else reply(serverSave(a));
    }
  } else if (m.method === 'ui/update-model-context') {
    window.modelContexts.push(m.params);
    reply({});
  } else if (m.method === 'ui/notifications/size-changed') {
    window.sizes.push(m.params);
    if (!window.fixedFrame) iframe.style.height = m.params.height + 'px';
  } else if (m.method === 'ui/request-display-mode') {
    window.modeRequests.push(m.params);
    iframe.style.width = '800px';
    reply({mode: 'fullscreen'});
    if (FIXED) {
      window.fixedFrame = true;
      iframe.style.height = '600px';
      view.postMessage({jsonrpc: '2.0', method: 'ui/notifications/host-context-changed',
        params: {displayMode: 'fullscreen', containerDimensions: {width: 800, height: 600}}}, '*');
    } else {
      view.postMessage({jsonrpc: '2.0', method: 'ui/notifications/host-context-changed',
        params: {displayMode: 'fullscreen', containerDimensions: {width: 800, maxHeight: 6000}}}, '*');
    }
  }
});
</script></body></html>"""

#: שורה לכל צורה שהמנוע בונה לה שורה משלו — כותרת, פסקה, רשימה, משימה, שורת טבלה, שורת קוד ובלוק
#: מתקפל — כדי שהלחיצה תיבדק מול ההיסט של כל אחת מהן, בטקסט שהבדיקה מחשבת בעצמה ולא מהמנוע.
_EDIT_LINES = [
    "# כותרת ראשית",
    "שורה רגילה בעברית",
    "- פריט ברשימה",
    "- [ ] משימה פתוחה",
    "| עמודה | ערך |",
    "| --- | --- |",
    "| תא ראשון | 1 |",
    "```js",
    "const answer = 42;",
    "```",
    "::: details פרטים נוספים",
    "בתוך הבלוק",
    ":::",
    "שורה אחרונה",
]
_EDIT_NOTE = {"id": "9" * 24, "title": "עריכה", "color": "#ffeddb", "content": "\n".join(_EDIT_LINES)}
_EDIT_LONG = {"id": "7" * 24, "title": "ארוך", "color": "#ffeddb",
              "content": "\n".join(f"שורה מספר {i} בפתק הארוך" for i in range(1, 81))}


def _line_start(lines, index):
    return sum(len(line) + 1 for line in lines[:index])


@pytest.fixture
def edit_host():
    """שרת מקומי: ``/<מקרה>.html`` מארח שעורכים מולו, ו-``/view.html`` הדף עם ה-CSP של המפרט."""
    view = note_view.build_note_view()
    pages = {}
    for name, note, fixed, extra in (("edit", _EDIT_NOTE, True, {}), ("edit-long", _EDIT_LONG, True, {}),
                                     ("edit-long-flexible", _EDIT_LONG, False, {}),
                                     ("edit-long-debug", _EDIT_LONG, True, {"layout_debug": True})):
        pages[f"/{name}.html"] = _EDIT_HOST % {
            "note": json.dumps(note, ensure_ascii=False).replace("<", "\\u003c"), "fixed": "true" if fixed else "false",
            "extra": json.dumps(extra)}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - שם שה-stdlib מחייב
            if self.path in pages:
                body, headers = pages[self.path], {}
            elif self.path == "/view.html":
                body, headers = view.html, {"Content-Security-Policy": _SPEC_DEFAULT_CSP}
            else:
                self.send_error(404)
                return
            data = body.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            for key, value in headers.items():
                self.send_header(key, value)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *_args):  # שקט בפלט הבדיקות
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


_EDITOR_STATE = """() => {
    const ta = document.querySelector('.ck-editor');
    const shown = (el) => !!el && getComputedStyle(el).display !== 'none';
    return {open: shown(ta), focused: document.activeElement === ta, value: ta ? ta.value : null,
            caret: ta ? [ta.selectionStart, ta.selectionEnd] : null,
            body: shown(document.querySelector('.ck-body')), bar: shown(document.querySelector('.ck-edit-bar'))};
}"""


def _open_editor_on(page, view, locator):
    view.locator(locator["selector"], has_text=locator["text"]).first.click()
    return poll(view, "() => { const ta = document.querySelector('.ck-editor');"
                      " return !!ta && getComputedStyle(ta).display !== 'none' && document.activeElement === ta; }",
                f"the editor opened from {locator['text']!r}")


def test_a_click_on_any_line_opens_the_editor_in_fullscreen_with_the_caret_on_that_line(chromium_executable, edit_host):
    """הלחיצה על שורה פותחת את העורך במסך מלא, והסמן בתחילת אותה שורה **במקור** — לכל צורה שהמנוע
    בונה: כותרת, פסקה, פריט, משימה, שורת טבלה, שורת קוד ושורה בתוך בלוק מתקפל. ההיסט הצפוי מחושב כאן
    מהטקסט, ולא נקרא מהמנוע. לחיצה על כותרת של בלוק מתקפל מקפלת ואינה פותחת עורך."""
    from playwright.sync_api import sync_playwright

    targets = [
        (".sticky-task-line", "כותרת ראשית", 0),
        (".sticky-task-line", "שורה רגילה בעברית", 1),
        (".sticky-task-line", "פריט ברשימה", 2),
        (".sticky-task-line", "משימה פתוחה", 3),
        ("tr.sticky-task-line", "תא ראשון", 6),
        (".sticky-task-line", "const answer = 42;", 8),
        (".sticky-task-line", "בתוך הבלוק", 11),
        (".sticky-task-line", "שורה אחרונה", 13),
    ]
    results = []
    with sync_playwright() as pw:
        browser, page, view = _open(pw, chromium_executable, f"{edit_host}/edit.html")
        try:
            view.click("summary.sticky-md-details-summary")
            folded = view.evaluate("() => ({open: document.querySelector('details').open,"
                                   " editor: !!document.querySelector('.ck-editor'), calls: 0})")
            folded["calls"] = page.evaluate("() => window.toolCalls.length")
            for selector, text, index in targets:
                # סגירת העורך בונה את הפתק מחדש, והבלוק המתקפל חוזר סגור — פותחים אותו לפני השורה שבתוכו.
                if text == "בתוך הבלוק" and not view.evaluate("() => document.querySelector('details').open"):
                    view.click("summary.sticky-md-details-summary")
                _open_editor_on(page, view, {"selector": selector, "text": text})
                state = view.evaluate(_EDITOR_STATE)
                results.append((text, state["caret"], _line_start(_EDIT_LINES, index), state["value"] == _EDIT_NOTE["content"],
                                state["body"], state["bar"]))
                view.click(".ck-cancel")
                poll(view, "() => !document.querySelector('.ck-editor')", "the clean editor closed")
            calls = page.evaluate("() => window.toolCalls")
            modes = page.evaluate("() => window.modeRequests")
            saved = page.evaluate("() => window.server.version")
        finally:
            browser.close()

    assert folded == {"open": True, "editor": False, "calls": 0}, folded
    for text, caret, expected, same, body, bar in results:
        assert caret == [expected, expected], (text, caret, expected)
        assert same and body is False and bar is True, (text, same, body, bar)
    # מסך מלא נתבקש פעם אחת — אחר כך הדף כבר שם; וכל פתיחה קראה את הפתק מחדש, ואף אחת לא שמרה.
    assert modes == [{"mode": "fullscreen"}], modes
    assert [c["name"] for c in calls] == ["codekeeper_show_note"] * len(targets), calls
    assert all(c["arguments"] == {"note_id": _EDIT_NOTE["id"]} for c in calls), calls
    assert saved == 1


def test_typing_lands_on_the_clicked_line_and_ctrl_s_saves_and_tells_the_model(chromium_executable, edit_host):
    """הקלדה אמיתית נכנסת בשורה שנלחצה, Ctrl+S שומר את הגוף כולו עם ה-hash שהעריכה נבנתה עליו, העורך
    נסגר על הגרסה השמורה, והמודל מקבל את הגוף החדש."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser, page, view = _open(pw, chromium_executable, f"{edit_host}/edit.html")
        try:
            _open_editor_on(page, view, {"selector": ".sticky-task-line", "text": "שורה רגילה בעברית"})
            page.keyboard.type("חדש: ")
            page.keyboard.press("Control+s")
            poll(view, "() => !document.querySelector('.ck-editor') && !!document.querySelector('.ck-notice')"
                       " && document.querySelector('.ck-notice').textContent === 'נשמר.'", "the save went through and the editor closed")
            rendered = view.evaluate("() => document.querySelector('.ck-content').textContent")
            saves = page.evaluate("() => window.toolCalls.filter((c) => c.name === 'codekeeper_note_view_save')")
            server = page.evaluate("() => window.server")
            contexts = page.evaluate("() => window.modelContexts")
        finally:
            browser.close()

    expected = list(_EDIT_LINES)
    expected[1] = "חדש: " + expected[1]
    body = "\n".join(expected)
    assert saves == [{"name": "codekeeper_note_view_save",
                      "arguments": {"note_id": _EDIT_NOTE["id"], "content": body, "expected_content_sha256": "0" * 63 + "1"}}], saves
    assert server["note"]["content"] == body and server["version"] == 2, server
    assert "חדש: שורה רגילה בעברית" in rendered, rendered
    assert len(contexts) == 1 and contexts[0]["content"][0]["text"].endswith("\n" + body), contexts
    assert "content_sha256: " + "0" * 63 + "2" in contexts[0]["content"][0]["text"], contexts


def test_the_editor_fills_the_fixed_fullscreen_frame_and_scrolls_inside(chromium_executable, edit_host):
    """במסגרת הקבועה של מסך מלא: שורת "שמור/בטל" למעלה, תיבת הטקסט ממלאת את שאר הנייר עד התחתית,
    הדף עצמו אינו גולש, ופתק ארוך נגלל בתוך התיבה. הטקסט בגודל, בריווח ובדיו של הגוף, ובכיוון של
    הדף (rtl)."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser, page, view = _open(pw, chromium_executable, f"{edit_host}/edit-long.html")
        try:
            body_style = view.evaluate("""() => { const s = getComputedStyle(document.querySelector('.ck-body'));
                return [s.fontSize, s.lineHeight, s.color]; }""")
            view.click(".ck-edit")
            poll(view, "() => document.documentElement.classList.contains('ck-fill') && innerHeight === 600"
                       " && !!document.querySelector('.ck-editor')", "the editor opened in the fixed frame")
            geo = view.evaluate("""() => {
                const r = (sel) => document.querySelector(sel).getBoundingClientRect();
                const ta = document.querySelector('.ck-editor');
                const s = getComputedStyle(ta);
                return {bar: r('.ck-edit-bar'), ta: r('.ck-editor'), paper: r('.ck-paper'),
                        doc: Math.ceil(document.documentElement.getBoundingClientRect().height),
                        scrollable: ta.scrollHeight > ta.clientHeight, style: [s.fontSize, s.lineHeight, s.color],
                        direction: s.direction, paddingBottom: parseFloat(getComputedStyle(document.querySelector('.ck-paper')).paddingBottom),
                        noticeH: document.querySelector('.ck-notice').getBoundingClientRect().height};
            }""")
        finally:
            browser.close()

    assert geo["bar"]["bottom"] <= geo["ta"]["top"], geo
    assert abs(geo["paper"]["bottom"] - (600 - 4)) <= 1, geo
    assert abs(geo["ta"]["bottom"] - (geo["paper"]["bottom"] - 1 - geo["paddingBottom"] - geo["noticeH"])) <= 1, geo
    assert geo["doc"] <= 600, geo
    assert geo["scrollable"] is True, geo
    assert geo["style"] == body_style, (geo["style"], body_style)
    assert geo["direction"] == "rtl", geo


def test_in_flexible_fullscreen_the_editor_has_a_height_and_the_frame_follows(chromium_executable, edit_host):
    """מסך מלא בגובה גמיש (כמו ``basic-host``): לתיבה גובה התחלתי משלה (``flex-basis`` ב-CSS), הדף
    מדווח אותו, והמסגרת גדלה אליו."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser, page, view = _open(pw, chromium_executable, f"{edit_host}/edit-long-flexible.html")
        try:
            view.click(".ck-edit")
            poll(view, "() => document.documentElement.classList.contains('ck-expanded') && !!document.querySelector('.ck-editor')",
                 "the editor opened in the flexible frame")
            state = _settled(page, view, "the frame took the editor height")
            ta = view.evaluate("""() => { const ta = document.querySelector('.ck-editor');
                return {h: ta.getBoundingClientRect().height, font: parseFloat(getComputedStyle(ta).fontSize),
                        scrollable: ta.scrollHeight > ta.clientHeight}; }""")
        finally:
            browser.close()

    assert abs(ta["h"] - 24 * ta["font"]) <= 1, ta
    assert ta["scrollable"] is True, ta
    assert state["last"]["height"] > ta["h"], (state, ta)


def test_a_conflict_keeps_my_text_and_offers_update_or_save_anyway(chromium_executable, edit_host):
    """הפתק נערך מבחוץ בזמן שאני עורך: השמירה נדחית, הטקסט שלי נשאר, ושורה מציעה "עדכן" או "שמור בכל
    זאת". "עדכן" טוען את הגרסה שבשרת, "החזר את הטקסט שלי" מחזיר אותו, ושמירה אחריו כותבת אותו מעל
    הגרסה שנטענה — בלי לדרוס אף גרסה שלא ראיתי."""
    from playwright.sync_api import sync_playwright

    shown = "(sel) => getComputedStyle(document.querySelector(sel)).display !== 'none'"
    with sync_playwright() as pw:
        browser, page, view = _open(pw, chromium_executable, f"{edit_host}/edit.html")
        try:
            _open_editor_on(page, view, {"selector": ".sticky-task-line", "text": "שורה אחרונה"})
            page.evaluate("() => window.externalEdit('גרסה מהוובאפ')")
            page.keyboard.type("שלי ")
            view.click(".ck-save")
            poll(view, f"() => ({shown})('.ck-conflict')", "the conflict bar appeared")
            mine = view.evaluate("() => document.querySelector('.ck-editor').value")
            view.click(".ck-accept")
            after_accept = view.evaluate(f"() => ({{value: document.querySelector('.ck-editor').value,"
                                         f" restore: ({shown})('.ck-restore'), conflict: ({shown})('.ck-conflict')}})")
            view.click(".ck-restore")
            restored = view.evaluate("() => document.querySelector('.ck-editor').value")
            view.click(".ck-save")
            poll(view, "() => !document.querySelector('.ck-editor')", "the save over the loaded version went through")
            saves = page.evaluate("() => window.toolCalls.filter((c) => c.name === 'codekeeper_note_view_save')"
                                  ".map((c) => c.arguments.expected_content_sha256)")
            server = page.evaluate("() => window.server")
        finally:
            browser.close()

    expected_mine = "\n".join(_EDIT_LINES[:-1] + ["שלי " + _EDIT_LINES[-1]])
    assert mine == expected_mine, mine
    assert after_accept == {"value": "גרסה מהוובאפ", "restore": True, "conflict": False}, after_accept
    assert restored == expected_mine, restored
    assert saves == ["0" * 63 + "1", "0" * 63 + "2"], saves
    assert server["note"]["content"] == expected_mine and server["version"] == 3, server


def test_a_save_that_lands_after_the_editor_closed_still_updates_the_view_and_claude(chromium_executable, edit_host):
    """**שמירה שבדרך, ועורך שנסגר לפני התשובה.** מקלידים, Ctrl+S, ובזמן שהשמירה בדרך — Ctrl+Z של
    הדפדפן מחזיר את הטקסט למקור, והמארח יוצא ממסך מלא. העורך נקי, ולכן נסגר; אבל השמירה כבר יצאה,
    והשרת כותב אותה. כשהתשובה מגיעה, הפתק שמוצג הוא מה שבשרת, ו-Claude מקבל אותו. לפני התיקון התשובה
    נזרקה: בשרת הגוף החדש, ובתצוגה ובמודל — הישן."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser, page, view = _open(pw, chromium_executable, f"{edit_host}/edit.html")
        try:
            _open_editor_on(page, view, {"selector": ".sticky-task-line", "text": "שורה רגילה בעברית"})
            page.evaluate("() => { window.holdSave = true; }")
            page.keyboard.type("נוסף ")
            page.keyboard.press("Control+s")
            poll(page, "() => !!window.heldSave", "the save request reached the host")
            # הביטול של הדפדפן הולך מילה-מילה: לוחצים עד שהטקסט חוזר למקור, ולא יותר מכמה פעמים.
            for _ in range(10):
                if view.evaluate("(original) => document.querySelector('.ck-editor').value === original", _EDIT_NOTE["content"]):
                    break
                page.keyboard.press("Control+z")
            undone = view.evaluate("() => document.querySelector('.ck-editor').value")
            page.evaluate("() => window.leaveFullscreen()")
            poll(view, "() => !document.querySelector('.ck-editor')", "the clean editor closed when the host left fullscreen")
            during = view.evaluate("() => ({edit: getComputedStyle(document.querySelector('.ck-edit')).display !== 'none',"
                                   " shown: document.querySelector('.ck-content').textContent})")
            page.evaluate("() => window.releaseSave()")
            poll(view, "() => document.querySelector('.ck-notice').textContent === 'נשמר.'", "the late answer reached the page")
            after = view.evaluate("() => ({shown: document.querySelector('.ck-content').textContent,"
                                  " edit: getComputedStyle(document.querySelector('.ck-edit')).display !== 'none'})")
            server = page.evaluate("() => window.server")
            contexts = page.evaluate("() => window.modelContexts")
        finally:
            browser.close()

    sent = "\n".join([_EDIT_LINES[0], "נוסף " + _EDIT_LINES[1]] + _EDIT_LINES[2:])
    assert undone == _EDIT_NOTE["content"], undone
    assert during["edit"] is False and "נוסף" not in during["shown"], during
    assert server["note"]["content"] == sent and server["version"] == 2, server
    assert "נוסף שורה רגילה בעברית" in after["shown"] and after["edit"] is True, after
    assert len(contexts) == 1 and contexts[0]["content"][0]["text"].endswith("\n" + sent), contexts


# ── מסך נייד: השטח הגלוי, הסמן, טלפון ─────────────────────────────────────────────────

#: **השטח הגלוי, בשליטת הבדיקה.** המקלדת במכשיר מקטינה את השטח הגלוי (``visualViewport``) בלי לגעת
#: בפריסה; לכרום של שולחן העבודה אין מקלדת. הסקריפט רץ בתוך מסגרת התצוגה לפני הקוד שלה, ומחליף את
#: ``visualViewport`` באובייקט עם אותו ממשק: ``height`` / ``offsetTop``, ``resize`` כשהגובה משתנה ו-
#: ``scroll`` כשהמרחק משתנה, כמו בדפדפן (MDN, ``VisualViewport``). כל השאר — הדף, ה-CSS, הפריסה
#: והגלילה — אמיתי. ``__vv.set(height, top)`` הוא "המקלדת נפתחה".
_FAKE_VISUAL_VIEWPORT = """(() => {
  if (!location.pathname.endsWith('/view.html')) return;
  const target = new EventTarget();
  let forced = null;
  Object.defineProperty(target, 'height', { get: () => forced ? forced.h : window.innerHeight });
  Object.defineProperty(target, 'width', { get: () => window.innerWidth });
  Object.defineProperty(target, 'offsetTop', { get: () => forced ? forced.top : 0 });
  Object.defineProperty(target, 'pageTop', { get: () => forced ? forced.top : 0 });
  Object.defineProperty(target, 'scale', { get: () => 1 });
  Object.defineProperty(window, 'visualViewport', { configurable: true, get: () => target });
  window.__vv = { set(h, top) {
    const prev = forced || { h: window.innerHeight, top: 0 };
    forced = { h: h, top: top };
    if (h !== prev.h) target.dispatchEvent(new Event('resize'));
    if (top !== prev.top) target.dispatchEvent(new Event('scroll'));
  } };
})();"""

_GEOMETRY_STATE = """() => {
    const r = (sel) => { const el = document.querySelector(sel); const b = el.getBoundingClientRect(); return {top: b.top, bottom: b.bottom, height: b.height}; };
    const ta = document.querySelector('.ck-editor');
    const scroller = document.scrollingElement || document.documentElement;
    return {root: r('#ck-note-root'), paper: r('.ck-paper'), head: r('.ck-head'), save: r('.ck-save'), ta: r('.ck-editor'),
            scrollY: scroller.scrollTop, docH: scroller.scrollHeight, inner: innerHeight,
            taScrollable: ta.scrollHeight > ta.clientHeight};
}"""


def _caret_visible(page, view):
    """**האם הסמן גלוי בתיבה — לפי הדפדפן עצמו, ולא לפי המדידה של הדף.** הקלדה של תו גוללת את התיבה
    אל הסמן אם הוא מחוץ לה; אם ``scrollTop`` לא זז, הסמן כבר היה גלוי."""
    before = view.evaluate("() => document.querySelector('.ck-editor').scrollTop")
    page.keyboard.type("x")
    after = view.evaluate("() => document.querySelector('.ck-editor').scrollTop")
    return before, after


def _frames(view, count):
    """מחכה ``count`` פריימים של אנימציה בתוך מסגרת התצוגה — עד שהעבודה ששינוי כבר התחיל נגמרת:
    ``ResizeObserver`` מודיע בפריים הראשון, והמדידה שהוא מתזמן (``scheduleSize``) רצה ב-
    ``requestAnimationFrame`` של הפריים שאחריו.

    **תקרה משלו** (``wait-without-own-deadline``): ל-``evaluate`` אין תקרה שמצאתי בתיעוד, ומסגרת
    שאינה מציירת (מוסתרת, או דפדפן תקוע) לא הייתה מריצה אף פריים — והבדיקה, ואיתה ה-CI, היו תלויות.
    אחרי ``WAIT_S`` ההמתנה נכשלת בהודעה, ולא ממשיכה כאילו הפריימים עברו."""
    view.evaluate("""([n, ms]) => new Promise((done, fail) => {
        const timer = setTimeout(() => fail(new Error('no animation frames within ' + ms + 'ms')), ms);
        const step = () => { n -= 1; if (n <= 0) { clearTimeout(timer); done(true); } else requestAnimationFrame(step); };
        requestAnimationFrame(step);
    })""", [count, int(WAIT_S * 1000)])


def test_with_the_keyboard_open_the_editor_fits_the_visible_area_and_only_the_box_scrolls(chromium_executable, edit_host):
    """**המקלדת נפתחה** — השטח הגלוי קטן ל-300 וזז 120 מראש הפריסה. הפתק מוצמד אליו: ראש הנייר
    ("שמור" ו"בטל" עם הכותרת) בראש השטח הגלוי, תיבת הטקסט ממלאת את השאר ונגללת בעצמה, והדף עצמו לא
    נגלל.

    **והסמן נשאר גלוי** — המקרה מהטאבלט: הסמן בשורה התחתונה של התיבה המלאה, והמקלדת מכווצת את התיבה
    מעליו. לכן לפני הכיווץ הסמן מוצב בשורה האחרונה שגלויה כולה, כשהתיבה בראשה, והבדיקה מוודאת שבלי
    גלילה הוא היה מחוץ לתיבה שהתכווצה — אחרת היא לא בודקת כלום (``revealCaret``). ``setSelectionRange``
    על תיבה בפוקוס אינו גולל (נמדד), ולכן ההצבה אינה משנה את ``scrollTop``."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser, page, view = _open(pw, chromium_executable, f"{edit_host}/edit-long.html", init_script=_FAKE_VISUAL_VIEWPORT)
        try:
            view.locator(".ck-content .sticky-task-line", has_text="שורה מספר 18 בפתק הארוך").first.click()
            poll(view, "() => document.documentElement.classList.contains('ck-fill') && innerHeight === 600"
                       " && !!document.querySelector('.ck-editor') && document.activeElement === document.querySelector('.ck-editor')",
                 "the editor opened in the fixed frame")
            page.wait_for_timeout(100)
            full = view.evaluate(_GEOMETRY_STATE)
            placed = view.evaluate("""() => {
                const t = document.querySelector('.ck-editor');
                const lh = parseFloat(getComputedStyle(t).lineHeight);
                const last = Math.floor(t.clientHeight / lh) - 1;
                const lines = t.value.split('\\n');
                let pos = 0;
                for (let i = 0; i < last; i += 1) pos += lines[i].length + 1;
                t.scrollTop = 0;
                t.setSelectionRange(pos, pos);
                return {top: last * lh, bottom: (last + 1) * lh, clientHeight: t.clientHeight, scrollTop: t.scrollTop,
                        padding: getComputedStyle(t).paddingTop};
            }""")
            view.evaluate("() => window.__vv.set(300, 120)")
            poll(view, "() => Math.abs(document.getElementById('ck-note-root').getBoundingClientRect().top - 120) < 1",
                 "the note moved to the visible area")
            page.wait_for_timeout(100)
            shrunk = view.evaluate(_GEOMETRY_STATE)
            caret = _caret_visible(page, view)
        finally:
            browser.close()

    assert abs(full["root"]["height"] - 600) <= 1, full
    assert abs(shrunk["root"]["top"] - 120) <= 1 and abs(shrunk["root"]["height"] - 300) <= 1, shrunk
    assert shrunk["save"]["top"] >= 120 and shrunk["head"]["bottom"] <= shrunk["ta"]["top"] + 1, shrunk
    assert shrunk["ta"]["bottom"] <= shrunk["paper"]["bottom"] + 0.5 and shrunk["paper"]["bottom"] <= 420 + 0.5, shrunk
    assert shrunk["taScrollable"] is True, shrunk
    assert shrunk["scrollY"] == 0 and shrunk["docH"] <= shrunk["inner"], shrunk
    assert placed["padding"] == "0px" and placed["scrollTop"] == 0 and placed["bottom"] <= placed["clientHeight"], placed
    assert placed["top"] >= shrunk["ta"]["height"], (placed, shrunk["ta"])
    assert caret[0] == caret[1] and caret[0] > 0, caret


def test_a_tiny_visible_area_keeps_the_box_inside_the_note(chromium_executable, edit_host):
    """שטח גלוי קטן מאוד (כמו בטלפון עם מקלדת): תיבת הטקסט מתכווצת עם הנייר ואינה בולטת מתחת לגבול
    שלו — לפני התיקון ``min-height: 4em`` דחף אותה החוצה."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser, page, view = _open(pw, chromium_executable, f"{edit_host}/edit-long.html", init_script=_FAKE_VISUAL_VIEWPORT)
        try:
            view.click(".ck-edit")
            poll(view, "() => document.documentElement.classList.contains('ck-fill') && !!document.querySelector('.ck-editor')",
                 "the editor opened in the fixed frame")
            view.evaluate("() => window.__vv.set(90, 0)")
            poll(view, "() => document.getElementById('ck-note-root').getBoundingClientRect().height < 100", "the note shrank")
            geo = view.evaluate(_GEOMETRY_STATE)
        finally:
            browser.close()

    assert geo["ta"]["bottom"] <= geo["paper"]["bottom"] + 0.5, geo
    assert geo["paper"]["bottom"] <= geo["root"]["bottom"] + 0.5, geo


#: השוליים התחתונים שהמארח המזויף מוסר כשהמקלדת "נפתחת", מתוך מסגרת של 600 — באפליקציה של Claude
#: בטאבלט נמדד 543 מתוך 924 (מצב המדידה, 18.11.2026).
_KEYBOARD_INSET = 300

#: המקום של תחתית שורת הסמן במסגרת, בחשבון של הבדיקה ולא במדידה של הדף: מספר השורה שלפני הסמן כפול
#: גובה שורה, מראש התיבה ובניכוי הגלילה. השורות של ``_EDIT_LONG`` ושל מה שהבדיקה מקלידה קצרות, ולא
#: נשברות ברוחב של 800.
_CARET_BOTTOM = """() => {
    const t = document.querySelector('.ck-editor');
    const cs = getComputedStyle(t);
    const lines = t.value.slice(0, t.selectionStart).split('\\n').length;
    return t.getBoundingClientRect().top + parseFloat(cs.paddingTop) + lines * parseFloat(cs.lineHeight) - t.scrollTop;
}"""


#: **מה היה ברגע הפוקוס** — כלומר רגע לפני שהמקלדת נקראת. ``focusin`` יורה בתוך ``focus()`` עצמו, ולכן
#: מה שנרשם כאן הוא המצב שאנדרואיד רואה כשהוא מחליט אם לדחוף את המסגרת. ``caretTop`` — המרחק של ראש
#: שורת הסמן מראש התיבה הגלויה, בחשבון של הבדיקה (מספר שורה כפול גובה שורה, פחות הגלילה).
_AT_FOCUS = """(() => {
  if (!location.pathname.endsWith('/view.html')) return;
  document.addEventListener('focusin', (event) => {
    const t = event.target;
    if (!t.matches || !t.matches('.ck-editor')) return;
    const cs = getComputedStyle(t);
    const lines = t.value.slice(0, t.selectionStart).split('\\n').length;
    window.__atFocus = {opening: t.classList.contains('ck-opening'), scrollTop: t.scrollTop, line: parseFloat(cs.lineHeight),
                        caretTop: parseFloat(cs.paddingTop) + (lines - 1) * parseFloat(cs.lineHeight) - t.scrollTop};
  }, true);
})();"""


def _post_context(page, params):
    """המארח המזויף שולח ``host-context-changed`` — למשל השוליים של המקלדת, כמו שהאפליקציה של Claude
    מוסרת אותה (``safeAreaInsets.bottom``)."""
    page.evaluate("""(params) => document.getElementById('view').contentWindow.postMessage({jsonrpc: '2.0',
        method: 'ui/notifications/host-context-changed', params}, '*')""", params)


def _keyboard(bottom, top=0):
    return {"safeAreaInsets": {"top": top, "right": 0, "bottom": bottom, "left": 0}}


_PAPER_BOTTOM = "() => document.querySelector('.ck-paper').getBoundingClientRect().bottom"


@pytest.mark.parametrize("line", [1, 40, 80])
def test_on_a_touch_screen_the_caret_line_reaches_the_top_before_the_keyboard_and_the_note_ends_at_its_line(
        chromium_executable, edit_host, line):
    """**כניסה לעריכה במסך מגע — בלי דחיפה של המסגרת.** אנדרואיד מזיז את כל החלון כשהמקלדת נפתחת, כדי
    שהסמן לא יוסתר (נמדד במכשיר: מהשורה הראשונה — לא זז; מהשורה התחתונה — נדחף). לכן ברגע הפוקוס שורת
    הסמן כבר בראש התיבה, עם שורה אחת מעליה — לשורה הראשונה, בלי גלילה; לאחרונה, בזכות הריפוד הזמני.
    אחרי שהמקלדת מדווחת: הריפוד הזמני יורד (``kb=reported`` במצב המדידה, ולא תקרת הזמן), הנייר נגמר על
    הקו שלה, והסמן מעליו."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser, page, view = _open(pw, chromium_executable, f"{edit_host}/edit-long-debug.html", touch=True, init_script=_AT_FOCUS)
        try:
            view.locator(".ck-content .sticky-task-line", has_text=f"שורה מספר {line} בפתק הארוך").first.click()
            poll(view, "() => document.documentElement.classList.contains('ck-fill') && innerHeight === 600"
                       " && !!window.__atFocus && document.activeElement === document.querySelector('.ck-editor')",
                 "the editor opened in the fixed frame")
            at_focus = view.evaluate("() => window.__atFocus")
            _post_context(page, _keyboard(_KEYBOARD_INSET))
            poll(view, "() => !document.querySelector('.ck-editor').classList.contains('ck-opening')"
                       " && /kb=reported/.test(document.querySelector('.ck-debug').textContent)",
                 "the keyboard report took the temporary room away")
            _frames(view, 4)
            paper = view.evaluate(_PAPER_BOTTOM)
            caret = view.evaluate(_CARET_BOTTOM)
        finally:
            browser.close()

    expected_top = 0 if line == 1 else at_focus["line"]
    assert at_focus["opening"] is True and abs(at_focus["caretTop"] - expected_top) <= 1, at_focus
    keyboard_line = 600 - _KEYBOARD_INSET
    assert abs(paper - (keyboard_line - 4)) <= 0.5, paper
    assert caret <= keyboard_line - 4 + 0.5, caret


def test_without_a_keyboard_report_the_temporary_room_goes_away_on_its_own(chromium_executable, edit_host):
    """**בלי דיווח על מקלדת** (מקלדת פיזית מחוברת, או מקלדת שלא נפתחה) הריפוד הזמני לא נשאר: להמתנה
    לדיווח יש תקרת זמן משלה (``KEYBOARD_REPORT_DEADLINE_MS``), ואחריה התיבה בלי ריפוד, ואין שטח ריק
    מתחת לשורה האחרונה."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser, page, view = _open(pw, chromium_executable, f"{edit_host}/edit-long.html", touch=True, init_script=_AT_FOCUS)
        try:
            view.locator(".ck-content .sticky-task-line", has_text="שורה מספר 80 בפתק הארוך").first.click()
            poll(view, "() => !!window.__atFocus", "the editor opened")
            at_focus = view.evaluate("() => window.__atFocus")
            poll(view, "() => !document.querySelector('.ck-editor').classList.contains('ck-opening')",
                 "the temporary room went away without a keyboard report")
            pad = view.evaluate("() => getComputedStyle(document.querySelector('.ck-editor')).paddingBottom")
        finally:
            browser.close()

    assert at_focus["opening"] is True, at_focus
    assert pad == "0px", pad


def test_after_the_keyboard_the_note_keeps_its_line_until_the_frame_changes(chromium_executable, edit_host):
    """**אחרי שהמקלדת דווחה:** הנייר נגמר על הקו שלה, והקלדה של שורות חדשות בסוף התיבה משאירה את הסמן
    מעליו — התיבה נגמרת שם, והדפדפן שומר את הסמן בתוכה. **המקלדת נסגרת באמצע עריכה** (השוליים קטנים):
    הקו נשאר, כדי שלחיצה על שורה תמיד תניח את הסמן מעל המקלדת כשהיא תיפתח שוב. אותה מסגרת שנשלחה שוב
    אינה מאפסת אותו; **מסגרת בגודל אחר** (סיבוב) — כן."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser, page, view = _open(pw, chromium_executable, f"{edit_host}/edit-long.html")
        try:
            view.click(".ck-edit")
            poll(view, "() => document.documentElement.classList.contains('ck-fill') && innerHeight === 600"
                       " && document.activeElement === document.querySelector('.ck-editor')", "the editor opened in the fixed frame")
            _post_context(page, _keyboard(_KEYBOARD_INSET))
            poll(view, "(b) => Math.abs(document.querySelector('.ck-paper').getBoundingClientRect().bottom - b) < 1",
                 "the note ended at the keyboard's line", 600 - _KEYBOARD_INSET - 4)
            page.keyboard.press("Control+End")
            for _ in range(10):
                page.keyboard.press("Enter")
            page.keyboard.type("x")
            _frames(view, 4)
            typed = view.evaluate(_CARET_BOTTOM)
            _post_context(page, _keyboard(48))
            _frames(view, 4)
            closed = view.evaluate(_PAPER_BOTTOM)
            _post_context(page, {"containerDimensions": {"width": 800, "height": 600}, **_keyboard(48)})
            _frames(view, 4)
            resent = view.evaluate(_PAPER_BOTTOM)
            _post_context(page, {"containerDimensions": {"width": 800, "height": 599}, **_keyboard(48)})
            _frames(view, 4)
            rotated = view.evaluate(_PAPER_BOTTOM)
        finally:
            browser.close()

    keyboard_line = 600 - _KEYBOARD_INSET
    assert typed <= keyboard_line - 4 + 0.5, typed
    assert abs(closed - (keyboard_line - 4)) <= 0.5 and abs(resent - (keyboard_line - 4)) <= 0.5, (closed, resent)
    assert abs(rotated - (600 - 48 - 4)) <= 0.5, rotated


def test_on_a_computer_the_editor_opens_without_the_temporary_room(chromium_executable, edit_host):
    """**במחשב אין מקלדת שתדחוף את המסגרת** (מצביע מדויק, ``pointer: fine``): אין ריפוד זמני, והתיבה
    נגללת אל הסמן בדרך הרגילה של הדפדפן."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser, page, view = _open(pw, chromium_executable, f"{edit_host}/edit-long.html", init_script=_AT_FOCUS)
        try:
            view.locator(".ck-content .sticky-task-line", has_text="שורה מספר 40 בפתק הארוך").first.click()
            poll(view, "() => !!window.__atFocus", "the editor opened")
            at_focus = view.evaluate("() => window.__atFocus")
            pad = view.evaluate("() => getComputedStyle(document.querySelector('.ck-editor')).paddingBottom")
        finally:
            browser.close()

    assert at_focus["opening"] is False and pad == "0px", (at_focus, pad)


def test_while_editing_the_head_row_sits_in_the_banner_area_and_the_box_starts_below_it(chromium_executable, edit_host):
    """**עוד מקום לעריכה** (החלטת המשתמש): בזמן עריכה הנייר מתחיל בראש המסגרת, שורת הראש — "שמור" ו"בטל"
    — ממלאת את השטח שהמארח שומר לבאנר (``safeAreaInsets.top``), ותיבת הטקסט מתחילה בדיוק מתחתיו. שם
    הפתק מוסתר בעריכה: בקצה הימני של השורה הוא היה מתחת לכפתור הסגירה של Claude. בתצוגה, בלי עריכה,
    הנייר מתחיל מתחת לשוליים."""
    from playwright.sync_api import sync_playwright

    banner = 120
    with sync_playwright() as pw:
        browser, page, view = _open(pw, chromium_executable, f"{edit_host}/edit-long.html")
        try:
            view.click(".ck-expand")
            poll(view, "() => document.documentElement.classList.contains('ck-fill') && innerHeight === 600", "fullscreen")
            _post_context(page, _keyboard(0, top=banner))
            poll(view, "(t) => Math.abs(document.querySelector('.ck-paper').getBoundingClientRect().top - t) < 1",
                 "the view took the top inset", banner + 4)
            view.locator(".ck-content .sticky-task-line", has_text="שורה מספר 2 בפתק הארוך").first.click()
            poll(view, "() => document.activeElement === document.querySelector('.ck-editor')", "the editor opened")
            _frames(view, 4)
            geo = view.evaluate("""() => {
                const r = (sel) => document.querySelector(sel).getBoundingClientRect();
                return {paper: r('.ck-paper').top, editor: r('.ck-editor').top, save: [r('.ck-save').top, r('.ck-save').bottom],
                        title: getComputedStyle(document.querySelector('.ck-title')).display};
            }""")
        finally:
            browser.close()

    assert abs(geo["paper"] - 4) <= 0.5, geo
    assert abs(geo["editor"] - banner) <= 0.5, geo
    assert geo["save"][0] >= 4 and geo["save"][1] <= banner, geo
    assert geo["title"] == "none", geo


def test_while_editing_a_swipe_outside_the_box_does_not_reach_the_page_behind(chromium_executable, edit_host):
    """**גלילה מחוץ לתיבה לא עוברת הלאה.** במכשיר, גלילה על השטח שמחוץ לתיבה דחפה את המסגרת. כאן הדף של
    המארח גליל, כדי שאפשר יהיה לראות זליגה: החלקה במגע אמיתי על השטח שמתחת לנייר (אחרי שהמקלדת דווחה)
    אינה מזיזה אותו, והחלקה על התיבה גוללת את התיבה — ולא את הדף שמאחור. **מה הבדיקה מבחינה בו:** בלי
    ``touch-action: none`` ובלי ``overscroll-behavior: none`` הדף שמאחור זז (נמדד: 285 פיקסלים); בכרום
    כל אחת מהן לבדה כבר עוצרת את זה, ולכן הבדיקה אינה מכריעה איזו מהן האפליקציה של Claude צריכה — זה
    נבדק במכשיר."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser, page, view = _open(pw, chromium_executable, f"{edit_host}/edit-long.html", touch=True)
        try:
            view.click(".ck-edit")
            poll(view, "() => document.documentElement.classList.contains('ck-fill') && innerHeight === 600"
                       " && document.activeElement === document.querySelector('.ck-editor')", "the editor opened in the fixed frame")
            _post_context(page, _keyboard(_KEYBOARD_INSET))
            poll(view, "() => !document.querySelector('.ck-editor').classList.contains('ck-opening')", "the keyboard was reported")
            page.evaluate("() => { const s = document.createElement('div'); s.style.height = '3000px'; document.body.appendChild(s); scrollTo(0, 0); }")
            box = page.locator("#view").bounding_box()
            touch = Touch(page.context.new_cdp_session(page))
            touch.swipe(box["x"] + 400, box["y"] + 500, 0, -200)
            page.wait_for_timeout(400)
            outside = page.evaluate("() => scrollY")
            before = view.evaluate("() => document.querySelector('.ck-editor').scrollTop")
            touch.swipe(box["x"] + 400, box["y"] + 200, 0, -100)
            page.wait_for_timeout(400)
            inside = [view.evaluate("() => document.querySelector('.ck-editor').scrollTop"), page.evaluate("() => scrollY")]
        finally:
            browser.close()

    assert outside == 0, outside
    assert inside[0] > before and inside[1] == 0, (before, inside)


def test_opening_a_far_line_of_a_long_note_shows_the_caret(chromium_executable, edit_host):
    """לחיצה על שורה רחוקה בפתק ארוך: התיבה נגללת אל הסמן. **השורה באמצע הפתק — רחוקה גם מההתחלה
    וגם מהסוף.** נמדד בכרום: אחרי הצבה של ``value`` הסמן בסוף הטקסט, ו-``focus()`` גולל לשם. בסדר
    הישן (פוקוס ואז ``setSelectionRange``, שאינו גולל) התיבה הציגה את הסוף — ושורה קרובה לסוף נראתה
    במקרה; כך הבדיקה עברה גם על הקוד הישן כשהיא לחצה על שורה קרובה לסוף ``_EDIT_LONG``. בקוד החדש שני דברים מביאים
    את הסמן לתצוגה — הסדר (קודם הסמן, ואז הפוקוס) ו-``revealCaret`` — והבדיקה כאן היא על התוצאה; הסדר
    עצמו נעול ב-``tests/mcp-note-view.test.js``."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser, page, view = _open(pw, chromium_executable, f"{edit_host}/edit-long.html")
        try:
            view.click(".ck-expand")
            poll(view, "() => document.documentElement.classList.contains('ck-fill') && innerHeight === 600", "fullscreen")
            view.locator(".ck-content .sticky-task-line", has_text="שורה מספר 40 בפתק הארוך").first.click()
            poll(view, "() => !!document.querySelector('.ck-editor') && document.activeElement === document.querySelector('.ck-editor')",
                 "the editor opened")
            page.wait_for_timeout(100)
            start = view.evaluate("() => document.querySelector('.ck-editor').scrollTop")
            caret = _caret_visible(page, view)
        finally:
            browser.close()

    assert start > 0, start
    assert caret[0] == caret[1], caret


def _fake_screen(width, height):
    """**המסך, בתוך מסגרת התצוגה.** נמדד: ``screen`` של Playwright מגיע לעמוד הראשי ולמסגרת מאותו
    origin, אבל לא למסגרת המבודדת (``sandbox``) — שם ``screen`` הוא המסך האמיתי של הדפדפן, 800×600.
    לכן המסך מוחלף בתוך המסגרת, באותה דרך כמו השטח הגלוי (``_FAKE_VISUAL_VIEWPORT``)."""
    return ("(() => { if (!location.pathname.endsWith('/view.html')) return;"
            f" Object.defineProperty(window, 'screen', {{ configurable: true, get: () => ({{ width: {width}, height: {height} }}) }}); }})();")


@pytest.mark.parametrize("screen,editable", [((390, 844), False), ((844, 390), False), ((800, 1280), True)])
def test_a_phone_screen_shows_the_note_without_editing(chromium_executable, edit_host, screen, editable):
    """**טלפון: תצוגה בלבד** — לפי הצלע הקצרה של המסך. טלפון לרוחב (844 רוחב) אינו טאבלט; טאבלט
    לאורך (800 רוחב) כן."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser, page, view = _open(pw, chromium_executable, f"{edit_host}/edit.html", init_script=_fake_screen(*screen))
        try:
            shown = view.evaluate("() => getComputedStyle(document.querySelector('.ck-edit')).display !== 'none'")
            view.locator(".ck-content .sticky-task-line", has_text="שורה רגילה בעברית").first.click()
            page.wait_for_timeout(300)
            calls = page.evaluate("() => window.toolCalls.length")
        finally:
            browser.close()

    assert shown is editable and (calls > 0) is editable, (shown, calls)


def test_the_conversation_row_is_icons_close_to_the_bottom_with_a_full_tap_area(chromium_executable, edit_host):
    """בתוך השיחה: "מסך מלא" (SVG) ו"עריכה" (✎) — אייקונים בלבד, בגודל 36, ואזור הלחיצה 44: נקודה 3
    פיקסלים מחוץ לקופסה הנראית עדיין פוגעת בכפתור. השורה צמודה לתחתית הנייר.

    ``elementFromPoint`` מחזיר ``null`` לנקודה שמחוץ לחלון של המסגרת, ומיד אחרי הרינדור המסגרת עוד
    בגובה של "טוען…" — לכן קודם מחכים שהמסגרת תקבל את הגובה שהדף מודד עכשיו (``_settled``), ואז
    לתנאי שהמדידה עצמה צריכה: כל אזור הלחיצה בתוך החלון של המסגרת. ``hit`` בתוצאה — מה נפגע."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser, page, view = _open(pw, chromium_executable, f"{edit_host}/edit.html")
        try:
            _settled(page, view, "the frame took the reported height")
            poll(view, """() => { const b = document.querySelector('.ck-edit').getBoundingClientRect();
                                  return b.top - 4 >= 0 && b.bottom + 4 <= innerHeight; }""",
                 "the whole tap area of the edit button is inside the frame")
            state = view.evaluate("""() => {
                const expand = document.querySelector('.ck-expand');
                const edit = document.querySelector('.ck-edit');
                const b = edit.getBoundingClientRect();
                const outside = document.elementFromPoint(b.left + b.width / 2, b.top - 3);
                const paper = document.querySelector('.ck-paper').getBoundingClientRect();
                const row = document.querySelector('.ck-controls').getBoundingClientRect();
                return {svg: !!expand.querySelector('svg path'), expandText: expand.textContent.trim(), editText: edit.textContent,
                        size: [Math.round(b.width), Math.round(b.height)], hitsEdit: outside === edit,
                        gap: paper.bottom - row.bottom, label: edit.getAttribute('aria-label'),
                        hit: outside ? (outside.className || outside.tagName) : null};
            }""")
        finally:
            browser.close()

    assert state["svg"] is True and state["expandText"] == "" and state["editText"] == "✎" and state["label"] == "עריכה", state
    assert state["size"] == [36, 36] and state["hitsEdit"] is True, state
    assert state["gap"] <= 8, state


def test_layout_debug_shows_live_numbers_over_the_view(chromium_executable, edit_host):
    """מצב מדידה בדפדפן אמיתי: השורה מציגה את השטח הגלוי, החלון והמסך, ומתעדכנת כשהשטח הגלוי משתנה —
    **גם כשרק המרחק שלו זז** (``scroll`` בלי ``resize``). אז שום דבר אינו משנה גודל, ``ResizeObserver``
    שקט, והעדכון הוא רק מ-``syncVisibleArea``. לפני הצעד הזה מחכים שהעבודה של הצעד הקודם תיגמר
    (``_frames``): המדידה שהוא תזמן רצה אחריו, קוראת את המרחק החדש ומעדכנת את השורה — ואז הבדיקה
    עוברת גם בלי ``syncVisibleArea`` (נמדד: כך שתי מוטציות שרדו)."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser, page, view = _open(pw, chromium_executable, f"{edit_host}/edit-long-debug.html", init_script=_FAKE_VISUAL_VIEWPORT)
        try:
            first = view.evaluate("() => document.querySelector('.ck-debug').textContent")
            view.click(".ck-edit")
            poll(view, "() => !!document.querySelector('.ck-editor')", "the editor opened")
            view.evaluate("() => window.__vv.set(300, 120)")
            poll(view, "() => /vv h=300 top=120/.test(document.querySelector('.ck-debug').textContent)", "the numbers followed the visible area")
            _frames(view, 4)
            settled = view.evaluate("() => document.querySelector('.ck-debug').textContent.split('\\n')[0]")
            view.evaluate("() => window.__vv.set(300, 60)")
            poll(view, "() => /vv h=300 top=60/.test(document.querySelector('.ck-debug').textContent)",
                 "the numbers followed a move of the visible area without a resize")
            after = view.evaluate("() => document.querySelector('.ck-debug').textContent")
            direction = view.evaluate("() => getComputedStyle(document.querySelector('.ck-debug')).direction")
        finally:
            browser.close()

    assert "screen " in first and "edit=true" in first and "inner 600x" in first, first
    assert "editor " in after and "focus=true" in after, after
    assert settled.startswith("vv h=300 top=120 "), settled
    assert direction == "ltr", direction
