"""טעינה לפני עריכה ועדכון בזמן אמת של הפתקים — בכרומיום אמיתי, מול הראוטים האמיתיים של השרת.

**מה קרה.** סוכן עדכן פתק דרך ה-MCP; המשתמש נכנס לעריכה בלי לרענן, התיבה הציגה את הגרסה שלפני
העדכון, והשמירה האוטומטית שמרה אותה מעליו. השרת דווקא זיהה את הדריסה (409 על ``prev_updated_at``
ישן), אבל הלקוח שלח שוב את אותו טקסט עם האסימון שבתשובה.

**העמוד.** ``sticky-notes.js`` ו-``utils/visible-poll.js`` מהדיסק, בדפדפן אמיתי. כל בקשה ל-
``/api/sticky-notes/...`` עוברת ל-blueprint האמיתי (``webapp/sticky_notes_api.py``) דרך
``test_client`` של Flask, מול הדמה של המסד (``tests/_notes_mongo_fake.py``) — כך ש-409,
``?versions=1``, ``GET /note/<id>`` וההחלטה מה זז ב-``updated_at`` הם של השרת, לא של העתק.
**"עדכון מה-MCP" הוא כתיבה ישירה למסמך שבדמה**, כמו ש-``ProductionBackend.update_note`` כותב:
גוף חדש ו-``updated_at`` של עכשיו (ברזולוציה של המסד).

**הדגימה מופעלת מהבדיקה** (``_livePoll.pollNow()``) ולא בהמתנה של 15 שניות; ``test_the_poll_runs_*``
מודד את הקצב עצמו בשעון מדומה. **מה לא נבדק כאן:** מונגו אמיתי (``tests/test_sticky_notes_live_sync_api.py``
בודק את החיתוך מול ``bson``), ומכשיר מגע אמיתי.

מדולג כשאין Chromium.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from urllib.parse import urlsplit

import pytest

flask = pytest.importorskip("flask")
pytest.importorskip("playwright", reason="playwright אינו מותקן")

# ``tests`` אינו חבילה — ראה את ה-docstring של ``tests/conftest.py``.
from _notes_mongo_fake import USER, make_client  # noqa: E402
# **הפיקסצ'רים של הדפדפן, ולא עותק שלהם** — כמו ב-``tests/test_sticky_md_tools_browser.py``.
from test_sticky_note_search_browser import browser, playwright_instance  # noqa: E402,F401

REPO_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = REPO_ROOT / "webapp" / "static"
MIME = {".js": "application/javascript", ".css": "text/css", ".svg": "image/svg+xml"}
STYLESHEETS = ("css/markdown-enhanced.css", "css/high-contrast.css", "css/dark-mode.css", "css/sticky-notes.css")
SCRIPTS = ("js/admonition-icons.js", "js/utils/file-name.js", "js/utils/rtl-code.js", "js/utils/text-highlight.js",
           "js/utils/visible-poll.js", "js/sticky-notes.js")

BOARD = "b" * 24
N1, N2, N3 = "1" * 24, "2" * 24, "3" * 24
T0 = dt.datetime(2026, 11, 14, 10, 0, 0, 123000, tzinfo=dt.timezone.utc)


def _doc(note_id, content, **extra):
    doc = {"_id": note_id, "user_id": USER, "board_id": BOARD, "content": content, "color": "yellow",
           "mode": "surface", "position_x": 40, "position_y": 40, "width": 360, "height": 260,
           "is_minimized": False, "created_at": T0, "updated_at": T0}
    doc.update(extra)
    return doc


def _stored_now():
    now = dt.datetime.now(dt.timezone.utc)
    return now.replace(microsecond=now.microsecond - now.microsecond % 1000)


#: משטח הלוח — האלמנט שהמנהל מקבל כ-``container``.
BOARD_HOST = '<div id="boardSurface" style="position:relative;min-height:600px"></div>'


class LivePage:
    """עמוד אמיתי עם מנהל פתקים, שהבקשות שלו נענות מה-blueprint האמיתי מול הדמה."""

    def __init__(self, browser, client, manager_js, host_html=None, viewport=(1100, 760), context_opts=None,
                 before_goto=None, hold_list=False):
        host_html = host_html or BOARD_HOST
        self.client = client
        self.db = client.db
        self.requests: list[tuple[str, str]] = []
        #: (שיטה, נתיב, סטטוס) של כל תשובה שה-blueprint החזיר — כולל 409 בתוך תשובה מרוכזת.
        self.answers: list[tuple[str, str, int]] = []
        self.fail_note_get = 0
        #: שמירות שהשרת **כותב**, והתשובה עליהן הולכת לאיבוד בדרך (חיבור שנקטע אחרי הכתיבה).
        self.drop_save_responses = 0
        #: רשימה מלאה (לא דגימה) שנעצרת עד ``release_list`` — לבדוק מה קורה לפני שהיא מגיעה.
        self.hold_list = hold_list
        self.held = []
        links = "\n".join(f'<link rel="stylesheet" href="/static/{s}">' for s in STYLESHEETS)
        tags = "\n".join(f'<script src="/static/{s}"></script>' for s in SCRIPTS)
        self.html = f"""<!doctype html><html dir="rtl" lang="he"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>* {{ margin:0; padding:0; box-sizing:border-box; }} body {{ font-family: sans-serif; }}</style>
{links}</head><body>{host_html}{tags}<script>{manager_js}</script></body></html>"""
        self.ctx = browser.new_context(viewport={"width": viewport[0], "height": viewport[1]}, **(context_opts or {}))
        self.page = self.ctx.new_page()
        self.errors: list[str] = []
        self.console: list[tuple[str, str]] = []
        self.page.on("pageerror", lambda e: self.errors.append(str(e)))
        self.page.on("console", lambda m: self.console.append((m.type, m.text)))
        self.page.route("**/*", self._serve)
        if before_goto:
            before_goto(self.page)
        self.page.goto("http://notes.test/page.html")

    def _serve(self, route):
        req = route.request
        parts = urlsplit(req.url)
        path = parts.path
        if path == "/page.html":
            route.fulfill(status=200, content_type="text/html", body=self.html)
            return
        if path.startswith("/static/"):
            target = (STATIC_DIR / path[len("/static/"):]).resolve()
            if not target.is_file() or STATIC_DIR.resolve() not in target.parents:
                route.fulfill(status=404, body="")
                return
            route.fulfill(status=200, content_type=MIME.get(target.suffix, "text/plain"),
                          body=target.read_text(encoding="utf-8"))
            return
        if path.startswith("/api/sticky-notes/"):
            self.requests.append((req.method, path + (("?" + parts.query) if parts.query else "")))
            if self.fail_note_get and req.method == "GET" and path.startswith("/api/sticky-notes/note/"):
                self.fail_note_get -= 1
                route.fulfill(status=500, content_type="application/json", body='{"ok": false}')
                return
            if (self.hold_list and req.method == "GET" and "versions=1" not in parts.query
                    and path.startswith("/api/sticky-notes/board/")):
                self.held.append(route)
                return
            if self.drop_save_responses and req.method in ("POST", "PUT") and (
                    path.endswith("/batch") or path.startswith("/api/sticky-notes/note/")):
                self.drop_save_responses -= 1
                self._answer(route, deliver=False)
                route.abort("connectionreset")
                return
            self._answer(route)
            return
        route.fulfill(status=404, body="")

    def _answer(self, route, deliver=True):
        req = route.request
        parts = urlsplit(req.url)
        path = parts.path
        if True:
            data = req.post_data_buffer if req.method in ("POST", "PUT") else None
            res = self.client.open(path, method=req.method, query_string=parts.query, data=data,
                                   headers={"Content-Type": req.headers.get("content-type", "application/json")})
            body = res.get_data()
            status = res.status_code
            if path.endswith("/batch") and status == 200:
                try:
                    status = max([status] + [int(r.get("status") or 200) for r in json.loads(body).get("results", [])])
                except (ValueError, AttributeError):
                    pass  # גוף שאינו תשובה מרוכזת — הסטטוס של הבקשה עצמה
            self.answers.append((req.method, path, status))
            if not deliver:
                return
            route.fulfill(status=res.status_code,
                          headers={"Content-Type": res.headers.get("Content-Type", "application/json")}, body=body)

    def release_list(self):
        held, self.held = self.held, []
        self.hold_list = False
        for route in held:
            self._answer(route)

    # --- השרת -----------------------------------------------------------

    def doc(self, note_id):
        return next(d for d in self.db.sticky_notes.docs if d["_id"] == note_id)

    def agent_writes(self, note_id, content):
        """כמו ``ProductionBackend.update_note`` של ה-MCP: גוף חדש ו-``updated_at`` של עכשיו."""
        d = self.doc(note_id)
        d["content"] = content
        d["updated_at"] = _stored_now()

    # --- הדפדפן ---------------------------------------------------------

    def sel(self, nid, inner=""):
        return f'.sticky-note[data-note-id="{nid}"] {inner}'.strip()

    def wait_note(self, nid):
        self.page.wait_for_function(
            """(nid) => { const n = document.querySelector(`.sticky-note[data-note-id="${nid}"]`);
                return !!n && n.getAnimations().every(a => a.playState === 'finished'); }""", arg=nid)

    def poll_now(self):
        """סבב דגימה אחד, וממתינים שיסתיים — בלי לחכות 15 שניות."""
        self.page.evaluate("""() => new Promise((resolve) => {
            const before = (window.__polls = (window.__polls || 0));
            window.__mgr._livePoll.pollNow();
            const t0 = Date.now();
            (function wait(){
              // הסבב נגמר כשאין בקשה באוויר; ``pollNow`` אינו מחזיר promise, ולכן דוגמים.
              setTimeout(() => { if (Date.now() - t0 > 300) resolve(); else wait(); }, 50);
            })();
        })""")

    def textarea(self, nid):
        return self.page.eval_on_selector(self.sel(nid, ".sticky-note-content"), "e => e.value")

    def wait_saved(self, nid, expected, timeout_s=8.0):
        import time
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if self.doc(nid)["content"] == expected:
                return
            self.page.wait_for_timeout(100)
        raise AssertionError(f"השרת לא קיבל את התוכן הצפוי: {self.doc(nid)['content']!r} במקום {expected!r}")

    def close(self):
        self.ctx.close()


BOARD_MANAGER = ("window.__mgr = new window.StickyNotesManager({ board: '%s', "
                 "container: document.getElementById('boardSurface'), anchorHost: null });" % BOARD)


@pytest.fixture
def client(monkeypatch):
    c = make_client(monkeypatch, flask)
    c.db.note_boards.docs.append({"_id": BOARD, "user_id": USER, "name": "לוח"})
    return c


@pytest.fixture
def board(browser, client):
    client.db.sticky_notes.docs.append(_doc(N1, "גרסה ישנה"))
    lp = LivePage(browser, client, BOARD_MANAGER)
    lp.wait_note(N1)
    yield lp
    assert not lp.errors, lp.errors
    lp.close()


def test_entering_edit_after_an_agent_update_edits_the_new_content_and_overwrites_nothing(board):
    """התרחיש שקרה: פתק פתוח, סוכן מעדכן אותו, נכנסים לעריכה בלי רענון — והעריכה על הגרסה החדשה."""
    board.agent_writes(N1, "גרסה חדשה מהסוכן")
    board.page.click(board.sel(N1, ".sticky-note-content"))
    board.page.wait_for_function(
        """(sel) => document.querySelector(sel).value === 'גרסה חדשה מהסוכן'""", arg=board.sel(N1, ".sticky-note-content"))
    board.page.keyboard.press("End")
    board.page.keyboard.type(" + שלי")
    board.page.locator(board.sel(N1, ".sticky-note-content")).blur()
    board.wait_saved(N1, "גרסה חדשה מהסוכן + שלי")


def test_a_save_on_a_stale_screen_is_refused_and_does_not_overwrite(board):
    """שכבת הביטחון: הרענון בכניסה נכשל, המשתמש מקליד על הגרסה הישנה — 409, והשרת שומר את מה שהסוכן כתב."""
    board.agent_writes(N1, "גרסה חדשה מהסוכן")
    board.fail_note_get = 1  # הרענון בכניסה לעריכה נכשל
    board.page.click(board.sel(N1, ".sticky-note-content"))
    board.page.keyboard.press("End")
    board.page.keyboard.type(" + שלי")
    board.page.wait_for_selector(board.sel(N1, ".sticky-note-remote"), timeout=8000)
    board.page.wait_for_timeout(1500)
    assert board.doc(N1)["content"] == "גרסה חדשה מהסוכן", "השמירה דרסה את העדכון"
    assert board.textarea(N1) == "גרסה ישנה + שלי", "מה שהמשתמש הקליד לא נגעו בו"


def test_an_update_while_typing_does_not_replace_the_text_and_update_brings_it_with_undo(board):
    board.page.click(board.sel(N1, ".sticky-note-content"))
    board.page.wait_for_timeout(400)
    board.page.keyboard.press("End")
    board.page.keyboard.type(" — טיוטה")
    board.wait_saved(N1, "גרסה ישנה — טיוטה")
    board.agent_writes(N1, "גרסה חדשה מהסוכן")
    board.poll_now()
    board.page.wait_for_selector(board.sel(N1, ".sticky-note-remote"), timeout=8000)
    assert board.textarea(N1) == "גרסה ישנה — טיוטה", "התיבה הוחלפה מתחת לידיים"
    board.page.click(board.sel(N1, ".sticky-note-remote-update"))
    assert board.textarea(N1) == "גרסה חדשה מהסוכן"
    assert board.page.query_selector(board.sel(N1, ".sticky-note-remote")) is None


def test_ignore_keeps_my_version_and_saves_it_over_the_update(board):
    board.page.click(board.sel(N1, ".sticky-note-content"))
    board.page.wait_for_timeout(400)
    board.page.keyboard.press("End")
    board.page.keyboard.type(" — שלי")
    board.wait_saved(N1, "גרסה ישנה — שלי")
    board.agent_writes(N1, "גרסה חדשה מהסוכן")
    board.poll_now()
    board.page.wait_for_selector(board.sel(N1, ".sticky-note-remote"), timeout=8000)
    board.page.keyboard.type("!")
    before = len(board.answers)
    board.page.click(board.sel(N1, ".sticky-note-remote-ignore"))
    board.wait_saved(N1, "גרסה ישנה — שלי!")
    # הבחירה עצמה מיישרת את האסימון — השמירה עוברת בבקשה אחת, בלי 409 בדרך.
    assert not [a for a in board.answers[before:] if a[2] == 409], board.answers[before:]


def test_a_note_that_is_not_being_edited_updates_without_reload(board):
    board.agent_writes(N1, "עודכן ברקע")
    board.poll_now()
    board.page.wait_for_function("(sel) => document.querySelector(sel).value === 'עודכן ברקע'",
                                 arg=board.sel(N1, ".sticky-note-content"))


def test_a_new_note_from_an_agent_appears_and_a_deleted_one_goes(board):
    board.db.sticky_notes.docs.append(_doc(N2, "פתק חדש מהסוכן", position_x=420, updated_at=_stored_now()))
    board.poll_now()
    board.page.wait_for_selector(board.sel(N2), timeout=8000)
    board.db.sticky_notes.docs[:] = [d for d in board.db.sticky_notes.docs if d["_id"] != N1]
    board.poll_now()
    board.page.wait_for_selector(board.sel(N1), state="detached", timeout=8000)


# ---------------------------------------------------------------------------
# הסמן, הלחיצה, הביטול והיציאה מעריכה
# ---------------------------------------------------------------------------

MD_OLD = "# כותרת\nשורה ראשונה\nשורה שנייה"
MD_NEW = "# כותרת\nשורה חדשה\nשורה ראשונה\nשורה שנייה"

ROW_JS = """(args) => { const [sel, text] = args;
  const row = [...document.querySelectorAll(sel + ' .sticky-task-line')].find(r => r.textContent.trim() === text);
  if (!row) return null; const r = row.getBoundingClientRect();
  return { x: r.left + Math.min(20, r.width / 2), y: r.top + r.height / 2 }; }"""
CARET_JS = """(sel) => { const t = document.querySelector(sel);
  return { value: t.value, after: t.value.slice(t.selectionStart, t.selectionStart + 10),
           focused: document.activeElement === t }; }"""


@pytest.fixture
def md_board(browser, client):
    client.db.sticky_notes.docs.append(_doc(N1, MD_OLD))
    lp = LivePage(browser, client, BOARD_MANAGER)
    lp.wait_note(N1)
    yield lp
    assert not lp.errors, lp.errors
    lp.close()


def test_the_caret_lands_on_the_clicked_line_after_the_content_was_swapped(md_board):
    """הלחיצה חושבה מול התצוגה הישנה; אחרי שהתוכן מתחלף, הסמן על אותו טקסט ולא באותו היסט."""
    md_board.agent_writes(N1, MD_NEW)
    pos = md_board.page.evaluate(ROW_JS, [md_board.sel(N1), "שורה שנייה"])
    md_board.page.mouse.click(pos["x"], pos["y"])
    md_board.page.wait_for_function("(sel) => document.querySelector(sel).value.includes('שורה חדשה')",
                                    arg=md_board.sel(N1, ".sticky-note-content"))
    caret = md_board.page.evaluate(CARET_JS, md_board.sel(N1, ".sticky-note-content"))
    assert caret["focused"] and caret["after"].startswith("שורה שנייה"), caret


def test_an_update_during_a_press_waits_for_the_press_to_end(md_board):
    """עדכון שמגיע כשהאצבע על התצוגה אינו בונה אותה מחדש מתחת לאצבע."""
    md_board.agent_writes(N1, MD_NEW)
    pos = md_board.page.evaluate(ROW_JS, [md_board.sel(N1), "שורה שנייה"])
    md_board.page.mouse.move(pos["x"], pos["y"])
    md_board.page.mouse.down()
    md_board.poll_now()
    view = md_board.page.eval_on_selector(md_board.sel(N1, ".sticky-note-tasks"), "e => e.textContent")
    assert "שורה חדשה" not in view, "התצוגה נבנתה מחדש באמצע לחיצה"
    md_board.page.mouse.up()
    md_board.page.wait_for_function("(sel) => document.querySelector(sel).value.includes('שורה חדשה')",
                                    arg=md_board.sel(N1, ".sticky-note-content"))
    caret = md_board.page.evaluate(CARET_JS, md_board.sel(N1, ".sticky-note-content"))
    assert caret["after"].startswith("שורה שנייה"), caret
    md_board.page.wait_for_timeout(500)
    assert md_board.page.query_selector(md_board.sel(N1, ".sticky-note-remote")) is None, "התראה על עדכון שכבר הוחל"


def test_undo_after_an_applied_update_does_not_bring_back_the_old_version(board):
    board.page.click(board.sel(N1, ".sticky-note-content"))
    board.page.wait_for_timeout(400)
    board.page.keyboard.press("End")
    board.page.keyboard.type(" — שלי")
    board.wait_saved(N1, "גרסה ישנה — שלי")
    board.page.locator(board.sel(N1, ".sticky-note-content")).blur()
    board.page.wait_for_timeout(800)  # ההתפרצות נסגרת ונדחפת למחסנית
    assert board.page.eval_on_selector(board.sel(N1, ".sticky-note-undo"), "b => b.disabled") is False
    board.agent_writes(N1, "גרסה חדשה מהסוכן")
    board.poll_now()
    board.page.wait_for_function("(sel) => document.querySelector(sel).value === 'גרסה חדשה מהסוכן'",
                                 arg=board.sel(N1, ".sticky-note-content"))
    assert board.page.eval_on_selector(board.sel(N1, ".sticky-note-undo"), "b => b.disabled") is True
    board.page.click(board.sel(N1, ".sticky-note-undo"), force=True)
    board.page.wait_for_timeout(1200)
    assert board.doc(N1)["content"] == "גרסה חדשה מהסוכן"


def test_leaving_edit_without_changes_loads_the_waiting_update(board):
    board.page.click(board.sel(N1, ".sticky-note-content"))
    board.page.wait_for_timeout(400)
    board.agent_writes(N1, "גרסה חדשה מהסוכן")
    board.poll_now()
    board.page.wait_for_selector(board.sel(N1, ".sticky-note-remote"), timeout=8000)
    assert board.textarea(N1) == "גרסה ישנה", "פתק בעריכה הוחלף מתחת לידיים"
    board.page.mouse.click(1000, 700)  # מחוץ לפתק
    board.page.wait_for_function("(sel) => document.querySelector(sel).value === 'גרסה חדשה מהסוכן'",
                                 arg=board.sel(N1, ".sticky-note-content"))
    assert board.page.query_selector(board.sel(N1, ".sticky-note-remote")) is None


def test_closing_the_tab_with_a_held_change_asks_first(board):
    ask = """() => { const e = new Event('beforeunload', { cancelable: true });
                     window.dispatchEvent(e); return e.defaultPrevented; }"""
    assert board.page.evaluate(ask) is False, "אין מה לאבד — אין סיבה לשאול"
    board.page.click(board.sel(N1, ".sticky-note-content"))
    board.page.wait_for_timeout(400)
    board.page.keyboard.press("End")
    board.page.keyboard.type(" — שלי")
    board.wait_saved(N1, "גרסה ישנה — שלי")
    board.agent_writes(N1, "גרסה חדשה מהסוכן")
    board.poll_now()
    board.page.wait_for_selector(board.sel(N1, ".sticky-note-remote"), timeout=8000)
    board.page.keyboard.type("!")
    assert board.page.evaluate(ask) is True


# ---------------------------------------------------------------------------
# המשטחים
# ---------------------------------------------------------------------------

FILE_ID = "f" * 24


def test_a_note_on_a_markdown_file_updates_live(browser, client):
    client.db.sticky_notes.docs.append(_doc(N1, "על הקובץ", board_id=None, file_id=FILE_ID, mode=""))
    lp = LivePage(browser, client, f"window.__mgr = new window.StickyNotesManager('{FILE_ID}');",
                  host_html='<div id="md-content"><p data-source-line="0">שורה</p></div>')
    lp.wait_note(N1)
    lp.agent_writes(N1, "על הקובץ — עודכן")
    lp.poll_now()
    lp.page.wait_for_function("(sel) => document.querySelector(sel).value === 'על הקובץ — עודכן'",
                              arg=lp.sel(N1, ".sticky-note-content"))
    assert ("GET", f"/api/sticky-notes/{FILE_ID}?versions=1") in lp.requests
    assert not lp.errors, lp.errors
    lp.close()


def test_a_note_in_the_repo_browser_updates_live(browser, client, monkeypatch):
    monkeypatch.setattr(client.api, "repo_file_exists", lambda *a, **k: True)
    client.db.sticky_notes.docs.append(_doc(N1, "בריפו", board_id=None, repo_name="CodeBot", repo_path="docs/a.md"))
    lp = LivePage(browser, client,
                  "window.__mgr = new window.StickyNotesManager({ repo: 'CodeBot', path: 'docs/a.md', "
                  "container: document.getElementById('host') });",
                  host_html='<div id="host" style="position:relative;height:700px;overflow:hidden"></div>')
    lp.wait_note(N1)
    lp.agent_writes(N1, "בריפו — עודכן")
    lp.poll_now()
    lp.page.wait_for_function("(sel) => document.querySelector(sel).value === 'בריפו — עודכן'",
                              arg=lp.sel(N1, ".sticky-note-content"))
    assert not lp.errors, lp.errors
    lp.close()


OVERLAY_HOST = '<div id="overlay" style="position:fixed;inset:0"></div>'
OPEN_JS = """async (url) => { const r = await fetch(url); const d = await r.json();
  window.__mgr.openOverlayNote(d.note); return true; }"""


@pytest.mark.parametrize("surface", ["archive", "filesPage"])
def test_the_note_open_over_a_page_updates_live_and_closes_when_it_is_gone(browser, client, surface):
    if surface == "archive":
        client.db.sticky_notes.docs.append(_doc(N1, "בארכיון", board_id=None, title="שם", archived_at=T0))
        open_url = f"/api/sticky-notes/archive/{N1}"
    else:
        client.db.sticky_notes.docs.append(_doc(N1, "נעוץ", files_page_pinned_at=T0))
        open_url = f"/api/sticky-notes/files-page/{N1}"
    manager = ("window.__gone = []; window.__mgr = new window.StickyNotesManager({ %s: true, "
               "container: document.getElementById('overlay'), anchorHost: null, "
               "onOverlayNoteGone: (id) => window.__gone.push(id) });" % surface)
    lp = LivePage(browser, client, manager, host_html=OVERLAY_HOST)
    lp.page.evaluate(OPEN_JS, open_url)
    lp.wait_note(N1)
    lp.agent_writes(N1, "עודכן ממקום אחר")
    lp.poll_now()
    lp.page.wait_for_function("(sel) => document.querySelector(sel).value === 'עודכן ממקום אחר'",
                              arg=lp.sel(N1, ".sticky-note-content"))
    lp.db.sticky_notes.docs[:] = []
    lp.poll_now()
    lp.page.wait_for_selector(lp.sel(N1), state="detached", timeout=8000)
    assert lp.page.evaluate("window.__gone") == [N1]
    assert not lp.errors, lp.errors
    lp.close()


# ---------------------------------------------------------------------------
# הקצב, 401, וההתראה בעין
# ---------------------------------------------------------------------------

def _versions_calls(lp):
    return sum(1 for m, p in lp.requests if m == "GET" and p.endswith("?versions=1"))


def test_the_poll_runs_every_fifteen_seconds_only_while_the_tab_is_visible(browser, client):
    client.db.sticky_notes.docs.append(_doc(N1, "גוף"))
    # השעון המדומה מותקן לפני הטעינה: טיימר שנדרך בשעון האמיתי אינו נורה ב-``run_for``.
    lp = LivePage(browser, client, BOARD_MANAGER, before_goto=lambda page: page.clock.install())
    lp.page.wait_for_timeout(300)
    start = _versions_calls(lp)
    assert start == 1, "הדגימה הראשונה רצה מיד אחרי הטעינה"
    lp.page.clock.run_for(14_000)
    lp.page.wait_for_timeout(200)
    assert _versions_calls(lp) == start, "דגמה לפני 15 שניות"
    lp.page.clock.run_for(1_500)
    lp.page.wait_for_timeout(200)
    assert _versions_calls(lp) == start + 1
    lp.page.evaluate("Object.defineProperty(document, 'visibilityState', { get: () => 'hidden', configurable: true })")
    lp.page.clock.run_for(5 * 60_000)
    lp.page.wait_for_timeout(200)
    assert _versions_calls(lp) == start + 1, "לשונית מוסתרת דגמה"
    lp.page.evaluate("""() => {
        Object.defineProperty(document, 'visibilityState', { get: () => 'visible', configurable: true });
        document.dispatchEvent(new Event('visibilitychange')); }""")
    lp.page.wait_for_timeout(300)
    assert _versions_calls(lp) == start + 2, "החזרה ללשונית לא שאלה מיד"
    lp.page.evaluate("window.dispatchEvent(new Event('focus'))")
    lp.page.wait_for_timeout(200)
    assert _versions_calls(lp) == start + 2, "חזרה לחלון בתוך הרצפה שאלה שוב"
    lp.page.clock.run_for(5_500)
    lp.page.evaluate("window.dispatchEvent(new Event('focus'))")
    lp.page.wait_for_timeout(300)
    assert _versions_calls(lp) == start + 3, "חזרה לחלון אחרי הרצפה לא שאלה"
    assert not lp.errors, lp.errors
    lp.close()


def test_a_401_stops_the_poll(board, monkeypatch):
    with board.client.session_transaction() as sess:
        sess.clear()
    board.poll_now()
    assert board.page.evaluate("window.__mgr._livePoll.stopped") is True
    assert any("session ended (401)" in text for kind, text in board.console if kind == "warning")


def _show_notice(lp):
    lp.page.click(lp.sel(N1, ".sticky-note-content"))
    lp.page.wait_for_timeout(300)
    lp.page.keyboard.press("End")
    lp.page.keyboard.type(" שלי")
    lp.wait_saved(N1, lp.doc(N1)["content"].split(" שלי")[0] + " שלי")
    lp.agent_writes(N1, "עדכון")
    lp.poll_now()
    lp.page.wait_for_selector(lp.sel(N1, ".sticky-note-remote"), timeout=8000)


from test_sticky_note_search_browser import PAPERS, _contrast, _darkest, _mode, _pixels  # noqa: E402


@pytest.mark.parametrize("paper", PAPERS)
@pytest.mark.parametrize("theme", [None, "high-contrast"])
def test_the_notice_is_readable_and_fits_on_every_paper(browser, client, paper, theme):
    client.db.sticky_notes.docs.append(_doc(N1, "גוף", color=paper, width=260, height=220))
    lp = LivePage(browser, client, BOARD_MANAGER.replace("window.__mgr", (
        f"document.documentElement.setAttribute('data-theme', '{theme}'); window.__mgr") if theme else "window.__mgr"),
        viewport=(700, 600), context_opts={"device_scale_factor": 2})
    lp.wait_note(N1)
    _show_notice(lp)
    box_js = "e => { const r = e.getBoundingClientRect(); return [r.left, r.top, r.right, r.bottom]; }"
    note = lp.page.eval_on_selector(lp.sel(N1), box_js)
    bar = lp.page.eval_on_selector(lp.sel(N1, ".sticky-note-remote"), box_js)
    text = lp.page.eval_on_selector(lp.sel(N1, ".sticky-note-remote-text"), box_js)
    btns = lp.page.eval_on_selector_all(lp.sel(N1, ".sticky-note-remote-btn"), f"bs => bs.map({box_js})")
    im = _pixels(lp.page)
    bg = _mode(im, (bar[0] + 2, bar[1] + 1, bar[0] + 5, bar[1] + 3), 2)
    # טקסט כהה על רקע בהיר — הפיקסל הכהה ביותר; בניגודיות הגבוהה (לבן על שחור) — הבהיר ביותר.
    span = [(x, y) for y in range(int(text[1] * 2), int(text[3] * 2)) for x in range(int(text[0] * 2), int(text[2] * 2))]
    ink = _darkest(im, text, 2) if sum(bg) > 380 else max((im.getpixel(pt) for pt in span), key=sum)
    lp.close()
    # הרצועה והכפתורים בתוך הפתק — שום דבר לא גולש מהרוחב שלו.
    for box in [bar] + btns:
        assert note[0] - 0.5 <= box[0] and box[2] <= note[2] + 0.5, (box, note)
    assert _contrast(ink, bg) >= 7, (paper, theme, ink, bg)


# ---------------------------------------------------------------------------
# ירידה מהמסך, והטעינה הראשונה מהקאש
# ---------------------------------------------------------------------------

def test_a_poll_that_knows_none_of_the_notes_removes_nothing(board, monkeypatch):
    """דגימה ריקה או של מקום אחר אינה ראיה שהפתקים עזבו (``one-way-sync-orphans``)."""
    import sticky_notes_target as snt

    monkeypatch.setattr(snt, "board_notes_filter", lambda user_id, board_id: {"user_id": user_id, "board_id": "אין-כזה"})
    before = len(board.requests)
    board.poll_now()
    assert board.page.query_selector(board.sel(N1)) is not None
    assert not [r for r in board.requests[before:] if r[1].startswith("/api/sticky-notes/note/")], "נבדק פתק על סמך דגימה ריקה"
    assert any("knows none" in text for kind, text in board.console if kind == "warning")


def test_a_note_deleted_elsewhere_while_being_edited_stays_on_screen(board):
    # פתק שני בלוח — אחרת הדגימה אחרי המחיקה ריקה, ובדיקת החפיפה לבדה הייתה משאירה את הפתק.
    board.db.sticky_notes.docs.append(_doc(N2, "פתק שני", position_x=420, updated_at=_stored_now()))
    board.poll_now()
    board.page.wait_for_selector(board.sel(N2), timeout=8000)
    board.page.click(board.sel(N1, ".sticky-note-content"))
    board.page.wait_for_timeout(300)
    board.page.keyboard.press("End")
    board.page.keyboard.type(" — שלי")
    board.page.wait_for_timeout(1200)
    board.db.sticky_notes.docs[:] = [d for d in board.db.sticky_notes.docs if d["_id"] != N1]
    board.poll_now()
    board.page.wait_for_timeout(500)
    assert board.page.query_selector(board.sel(N1)) is not None, "פתק בעריכה ירד מתחת לידיים"
    assert board.textarea(N1) == "גרסה ישנה — שלי"


def test_a_note_opened_for_editing_from_the_cache_is_not_rebuilt_when_the_list_arrives(browser, client):
    """הפתקים מוצגים קודם מהקאש; מי שנכנס לעריכה לפני שהרשימה הגיעה אינו מאבד אותה."""
    # הסוכן כתב אחרי שהקאש נשמר — ולכן לשרת אסימון חדש יותר (כל שינוי תוכן מזיז אותו).
    client.db.sticky_notes.docs.append(_doc(N1, "בשרת", updated_at=_stored_now()))
    cached = {"ts": 4102444800000, "notes": [{
        "id": N1, "board_id": BOARD, "content": "מהקאש", "title": "", "color": "#ffffcc", "mode": "surface",
        "position": {"x": 40, "y": 40}, "size": {"width": 360, "height": 260}, "updated_at": T0.isoformat()}]}
    seed = ("localStorage.setItem('sticky-notes:board:%s', %s);" % (BOARD, json.dumps(json.dumps(cached, ensure_ascii=False))))

    def hold(page):
        page.add_init_script(seed)

    lp = LivePage(browser, client, BOARD_MANAGER, before_goto=hold, hold_list=True)
    # הרענון בכניסה לעריכה נכשל — כך ההקלדה נשארת על הגרסה מהקאש, והטעינה פוגשת פתק שנגעו בו.
    lp.fail_note_get = 1
    lp.page.wait_for_selector(lp.sel(N1), timeout=8000)
    assert lp.held, "הרשימה המלאה לא נעצרה — הבדיקה אינה בודקת את מה שהיא מתיימרת"
    lp.page.click(lp.sel(N1, ".sticky-note-content"))
    lp.page.keyboard.press("End")
    lp.page.keyboard.type(" + שלי")
    lp.page.wait_for_timeout(1500)
    lp.release_list()
    lp.page.wait_for_timeout(800)
    state = lp.page.evaluate("""(sel) => { const t = document.querySelector(sel);
        return { value: t.value, focused: document.activeElement === t,
                 count: document.querySelectorAll('.sticky-note').length }; }""",
                             lp.sel(N1, ".sticky-note-content"))
    assert state["count"] == 1 and state["focused"], state
    assert state["value"] == "מהקאש + שלי", "הטקסט שהוקלד הוחלף"
    assert lp.page.query_selector(lp.sel(N1, ".sticky-note-remote")) is not None, "השרת מחזיק גרסה אחרת — צריך התראה"
    assert lp.doc(N1)["content"] == "בשרת", "הקלדה על הקאש נשמרה מעל השרת"
    assert not lp.errors, lp.errors
    lp.close()


def test_a_cached_note_deleted_on_the_server_stays_while_it_is_being_edited(browser, client):
    """הרשימה מהשרת אינה מכירה את הפתק — אבל המשתמש כבר עורך אותו מהקאש, והוא אינו נעלם מתחת לידיים."""
    client.db.sticky_notes.docs.append(_doc(N1, "נשאר בשרת"))
    cached = {"ts": 4102444800000, "notes": [
        {"id": nid, "board_id": BOARD, "content": text, "title": "", "color": "#ffffcc", "mode": "surface",
         "position": {"x": x, "y": 40}, "size": {"width": 300, "height": 220}, "updated_at": T0.isoformat()}
        for nid, text, x in ((N1, "נשאר בשרת", 40), (N2, "נמחק בשרת", 380))]}
    seed = ("localStorage.setItem('sticky-notes:board:%s', %s);" % (BOARD, json.dumps(json.dumps(cached, ensure_ascii=False))))
    lp = LivePage(browser, client, BOARD_MANAGER, before_goto=lambda page: page.add_init_script(seed), hold_list=True)
    lp.fail_note_get = 1
    lp.page.wait_for_selector(lp.sel(N2), timeout=8000)
    assert lp.held, "הרשימה המלאה לא נעצרה"
    lp.page.click(lp.sel(N2, ".sticky-note-content"))
    lp.page.keyboard.press("End")
    lp.page.keyboard.type(" + שלי")
    lp.release_list()
    lp.page.wait_for_timeout(800)
    assert lp.page.query_selector(lp.sel(N2)) is not None, "פתק בעריכה ירד בטעינה"
    assert lp.textarea(N2) == "נמחק בשרת + שלי"
    assert not lp.errors, lp.errors
    lp.close()


def test_a_destroyed_manager_stops_polling(board):
    """החלפת קובץ בדפדפן הריפו מפרקת את המנהל — הדגימה שלו נעצרת איתו, ואינה ממשיכה לשאול על משטח שאינו."""
    board.page.evaluate("window.__mgr.destroy()")
    before = _versions_calls(board)
    board.page.evaluate("""() => { window.dispatchEvent(new Event('focus'));
                                   document.dispatchEvent(new Event('visibilitychange')); }""")
    board.page.wait_for_timeout(5600)
    board.page.evaluate("window.dispatchEvent(new Event('focus'))")
    board.page.wait_for_timeout(300)
    assert _versions_calls(board) == before



def test_a_save_whose_answer_was_lost_is_recognized_as_ours_and_not_shown_as_an_update(board):
    """השרת כתב, החיבור נקטע לפני התשובה: הניסיון החוזר מקבל 409 על הכתיבה **שלנו** — ולא מוצגת התראה."""
    board.page.click(board.sel(N1, ".sticky-note-content"))
    board.page.wait_for_timeout(300)
    board.drop_save_responses = 1
    board.page.keyboard.press("End")
    board.page.keyboard.type(" — שלי")
    board.page.wait_for_timeout(400)
    board.page.keyboard.type("!")
    board.wait_saved(N1, "גרסה ישנה — שלי!")
    assert [a for a in board.answers if a[2] == 409], "הניסיון החוזר לא עבר במסלול ה-409 — הבדיקה אינה בודקת את מה שהיא מתיימרת"
    assert board.page.query_selector(board.sel(N1, ".sticky-note-remote")) is None, "התראה על הטקסט של המשתמש עצמו"
    assert board.textarea(N1) == "גרסה ישנה — שלי!"


def test_an_update_during_a_touch_press_waits_for_the_finger_to_lift(browser, client):
    """במגע הלחיצה יכולה להגיע במשימה נפרדת אחרי ``pointerup`` — העדכון ממתין גם לה."""
    from _browser_harness import Touch

    client.db.sticky_notes.docs.append(_doc(N1, MD_OLD))
    lp = LivePage(browser, client, BOARD_MANAGER, context_opts={"has_touch": True, "is_mobile": True})
    lp.wait_note(N1)
    lp.agent_writes(N1, MD_NEW)
    pos = lp.page.evaluate(ROW_JS, [lp.sel(N1), "שורה שנייה"])
    touch = Touch(lp.page.context.new_cdp_session(lp.page))
    touch.start(pos["x"], pos["y"])
    lp.poll_now()
    view = lp.page.eval_on_selector(lp.sel(N1, ".sticky-note-tasks"), "e => e.textContent")
    assert "שורה חדשה" not in view, "התצוגה נבנתה מחדש מתחת לאצבע"
    touch.end()
    lp.page.wait_for_function("(sel) => document.querySelector(sel).value.includes('שורה חדשה')",
                              arg=lp.sel(N1, ".sticky-note-content"))
    caret = lp.page.evaluate(CARET_JS, lp.sel(N1, ".sticky-note-content"))
    assert caret["after"].startswith("שורה שנייה"), caret
    assert not lp.errors, lp.errors
    lp.close()
