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
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from _browser_harness import poll
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
    # "גדול מאוד" — 20px — גם לכותרת וגם לכל שורה
    assert state["titleSize"] == "20px"
    assert {line["size"] for line in state["lines"]} == {"20px"}
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
