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

from _browser_harness import WAIT_S, poll
from mcp_server import note_view

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
                const lines = [...paper.querySelectorAll('.ck-line')];
                return {
                    title: title.textContent,
                    titleSize: getComputedStyle(title).fontSize,
                    lines: lines.map((l) => ({text: l.textContent, dir: getComputedStyle(l).direction,
                                              size: getComputedStyle(l).fontSize})),
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
    # הפתק — כותרת, שורה לכל שורת מקור, וצבע הנייר
    assert state["title"] == "רשימה " + _EVIL
    texts = [line["text"] for line in state["lines"]]
    assert texts == ["# כותרת בעברית", " ", "English line first", "שורה בעברית עם English באמצע", _EVIL]
    assert state["paperBg"] == "rgb(255, 237, 219)"
    assert state["paperInk"] == "rgb(34, 34, 34)"
    # כל שורה מחליטה את הכיוון שלה (dir="auto"), כמו במנוע של הפתק
    directions = {line["text"]: line["dir"] for line in state["lines"]}
    assert directions["# כותרת בעברית"] == "rtl"
    assert directions["English line first"] == "ltr"
    assert directions["שורה בעברית עם English באמצע"] == "rtl"
    # הגוף ב"גדול מאוד" (20px), והכותרת כמו בוובאפ (13px) — הערכים שהטסט של ה-CSS משווה לוובאפ
    assert {line["size"] for line in state["lines"]} == {"20px"}
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
    "short-safe-area": (_SHORT, {"containerDimensions": {"width": 600, "maxHeight": 900},
                                 "availableDisplayModes": ["inline"], "displayMode": "inline",
                                 "safeAreaInsets": {"top": 0, "right": 0, "bottom": 48, "left": 0}}, 600),
}

#: מארח שמחיל כל ``size-changed`` על המסגרת — מה שהמפרט מחייב במסגרת גמישה ("hosts MUST listen
#: for ``ui/notifications/size-changed`` ... and update the iframe dimensions accordingly"). על
#: בקשת מסך מלא הוא עונה ``{mode}``, ואחריה ``host-context-changed``, באחת משתי הצורות שמארחים
#: אמיתיים נוקטים: מסגרת בגובה קבוע, כמו Claude ("Display modes": ``width`` ו-``height``) — ומאז
#: אינו מחיל דיווחים, כי הגובה שלו; או גובה גמיש עם תקרה, כמו ``basic-host`` של ext-apps
#: (``{ width, maxHeight: 6000 }``) — ואז ממשיך להחיל.
_FRAME_HOST = """<!doctype html><html><head><meta charset="utf-8"></head><body style="margin:0">
<iframe id="view" src="/view.html" sandbox="allow-scripts"
        style="width:%(width)dpx;height:80px;border:0;display:block"></iframe>
<script>
const NOTE_RESULT = {content: [{type: 'text', text: JSON.stringify(%(note)s)}]};
const HOST_CONTEXT = %(context)s;
const iframe = document.getElementById('view');
window.sizes = [];
window.modeRequests = [];
window.fixedFrame = false;
window.addEventListener('message', (event) => {
  if (event.source !== iframe.contentWindow) return;
  const m = event.data;
  const view = iframe.contentWindow;
  if (m.method === 'ui/initialize') {
    view.postMessage({jsonrpc: '2.0', id: m.id, result: {protocolVersion: '2026-01-26',
      hostInfo: {name: 'test-host', version: '1'}, hostCapabilities: {}, hostContext: HOST_CONTEXT}}, '*');
  } else if (m.method === 'ui/notifications/initialized') {
    view.postMessage({jsonrpc: '2.0', method: 'ui/notifications/tool-result', params: NOTE_RESULT}, '*');
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
            "fixed_fullscreen": "false" if name.endswith("-flexible") else "true",
        }

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


def _open(pw, chromium_executable, url, *, reduced_motion=None):
    browser = (pw.chromium.launch(executable_path=chromium_executable)
               if chromium_executable else pw.chromium.launch())
    page = browser.new_page(device_scale_factor=1, viewport={"width": 1000, "height": 1000})
    if reduced_motion:
        page.emulate_media(reduced_motion=reduced_motion)
    page.goto(url)
    view = None
    for _ in range(100):
        view = next((f for f in page.frames if f.url.endswith("/view.html")), None)
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
            step = round(top["clientHeight"] * 0.75)
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
    assert body["scroll"] and body["scrollHeight"] > body["clientHeight"], body


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
