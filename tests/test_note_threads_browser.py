"""שרשורי התגובות על פתקים — בכרומיום אמיתי, בעמודים האמיתיים, מול השרת האמיתי ומונגו אמיתי.

**מה נבדק, ולמה כך (T1 ב-``TESTING-PATTERNS.md``).** המשתמש נוגע בשרשורים דרך הבועות שמעל
הפתק ודרך החלונית, בשלושה משטחים: לוח, תצוגת Markdown של קובץ, ודפדפן הריפו. לכן כל פעולה
כאן נעשית דרך הממשק — לחיצה, הקלדה, מקש — מול הוובאפ האמיתי (``admin_live_server``) ומונגו
אמיתי (``wired_mongo``), ובסוף כל פעולה המסד נקרא ישירות: מה שנשמר, ולא מה שהממשק אמר. אין
כאן דמה של ה-API: דמה הייתה בודקת את עצמה, וכל פער בינה לבין השרת היה נשאר בלתי נראה.

**מה כן מוזרק, ורק בנקודה אחת כל פעם** (``page.route`` על בקשה אחת): כשל רשת, בקשה שנתקעת,
ורשימת פתקים שחזרה בלי תקצירי השרשורים (``threads_unavailable``) — התשובה האמיתית מהשרת, עם
שדה אחד ששונה. ובדפדפן הריפו ה-API של הריפו עצמו מזויף, כמו ב-``tests/test_repo_notes_browser.py``
— הפתקים והשרשורים שם עוברים לשרת האמיתי.

**השרשורים נזרעים דרך ``note_threads``** — המקום היחיד שכותב לאוסף, כמו ש-MCP כותב תגובה של
סוכן. כך "סוכן ענה בינתיים" או "השרשור נסגר מאחורי הגב של הממשק" הם מצבים אמיתיים של המסד, ולא
תשובה מפוברקת.

**הערכים מהעיצוב** (``NoteThreads.html`` ב-Ck, "לוח ערכים למפתח" ומצבים 1–10), ולא מה-CSS: מה
שנבדק הוא שהעמוד נראה כמו העיצוב, ולכן העיצוב הוא המקור. שתי סטיות מכוונות מסומנות במקומן.

**מה לא נבדק כאן:** מכשיר מגע אמיתי, מקלדת IME, ותצוגת התראות push (``tests/test_note_comment_push.py``
ו-``tests/test_sw_snooze_refusal_browser.py``). מדולג כשאין Chromium או מונגו — וב-CI אין
(``docs/testing.rst``).
"""

from __future__ import annotations

import contextlib
import io
import json
import re
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import unquote, urlsplit

import pytest
from bson import ObjectId

# ``tests`` אינו חבילה — ראה את ה-docstring של ``tests/conftest.py``.
from _browser_harness import WAIT_S, poll, top_note_in_overlap

pytest.importorskip("playwright", reason="playwright אינו מותקן")

from playwright.sync_api import Error as PlaywrightError  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

import note_threads as nt  # noqa: E402

#: המשתמש של ``admin_live_server``. ב-session שלו אין ``first_name``, ולכן השם שמוצג ליד
#: התגובות שלו הוא ``_THREAD_USER_FALLBACK_NAME`` ("אני"), וראשי התיבות "אנ".
USER_ID = 1
ME, ME_INITIALS = "אני", "אנ"

DESKTOP = {"width": 1280, "height": 800}
#: צפיפות הפיקסלים של הטאבלט שהמשתמש עובד עליו — כמו ``open_admin_page``. משנה מדידות: כרומיום
#: מעגל עובי גבול לפיקסל שלם של המכשיר, ולכן 1.5px נמדד 1.5 רק כשיש שני פיקסלים לכל פיקסל CSS.
DPR = 2

# --- הערכים מהעיצוב ------------------------------------------------------------
#: גווני השרשור לפי המספר, מחזורי: (N − 1) % 3. שרשור שנפתר — אותו גוון, כרומה 0.03.
TONES = ("oklch(0.8 0.1 200)", "oklch(0.8 0.1 70)", "oklch(0.8 0.1 300)")
RESOLVED_TONES = ("oklch(0.8 0.03 200)", "oklch(0.8 0.03 70)", "oklch(0.8 0.03 300)")
WAITING_RED = "rgb(255, 93, 79)"     # #ff5d4f
PAPER = "rgb(252, 251, 248)"         # #fcfbf8 — נייר החלונית, וגם הטבעת של בועה פעילה
INK = "rgb(36, 49, 79)"              # #24314f
MUTED = "rgb(91, 104, 133)"          # #5b6885 — שם שרשור שנפתר
CHIP_BG = "rgb(230, 233, 239)"       # #e6e9ef — "+N"
PRESSED_BG = "rgba(43, 63, 106, 0.12)"
#: רקע תגובה ועיגול לפי הכותב. ``agent`` — סוכן שאין לו גוון בעיצוב: אפור ניטרלי, באותה
#: בהירות (סטייה מכוונת, מאושרת בתוכנית: העיצוב לא הגדיר לו צבע).
AUTHOR_BG = {"user": "oklch(0.965 0.035 85)", "cc": "oklch(0.95 0.03 245)",
             "claude": "oklch(0.95 0.03 265)", "gemini": "oklch(0.95 0.03 225)", "agent": "oklch(0.95 0 0)"}
AVATAR_BG = {"user": "oklch(0.55 0.11 60)", "cc": "oklch(0.5 0.1 245)", "claude": "oklch(0.5 0.1 265)",
             "gemini": "oklch(0.5 0.1 225)", "agent": "oklch(0.5 0 0)"}
PILL_W, PILL_H, PILL_RADIUS = 36, 26, "13px"
PITCH = 44            # בועה 36 וריווח 8 — וזה גם שטח הלחיצה
#: 14px מקצה הפתק. **נמדד מהקופסה הפנימית** (בתוך הגבול של 1px): לפתק בעיצוב אין גבול.
EDGE = 14
STICK_W, STICK_H, ANCHOR = 2, 10, 7
ZONE = 44             # שטח הלחיצה לגובה, וגם "פחות מ-44px מהקצה העליון"
PANEL_W, PANEL_NARROW_W, NARROW_BELOW = 360, 280, 376
PANEL_TOP, PANEL_SIDE = 10, 8
COMMENT_CAP = nt.MAX_COMMENT_CHARS   # התקרה של השרת, בנקודות קוד — המונה מציג אותה
#: שוליים מקצה המסך — ``NOTE_EDGE_GAP`` ב-``sticky-notes.js``, אותו מרווח שהפתקים נצמדים אליו.
SCREEN_GAP = 12

#: הכותבים, כמו שה-MCP בונה אותם (``client`` מהחיבור).
CC = nt.agent_author(client="claude-code", working_on="תיקון כיוון קוד")
CLAUDE = nt.agent_author(client="Anthropic/ClaudeAI", working_on="סקירת קוד")
GEMINI = nt.agent_author(client="Gemini", working_on="בדיקת נגישות")
CURSOR = nt.agent_author(client="Cursor", working_on="בדיקה")       # לקוח שאינו בטבלה — בשמו
NAMELESS = nt.agent_author(client=None, working_on="בדיקה")         # חיבור בלי שם — "סוכן"
USER = nt.user_author()

#: התגובה הארוכה מהעיצוב (מצב 4) — 448 תווים, נחתכת ב-6 שורות.
LONG_TEXT = (
    'מצאתי את המקור: גוף הפתק מקבל dir="rtl" ברמת הקונטיינר, והירושה עוברת גם לבלוקי קוד. הוספתי '
    'dir="ltr" ל-pre ול-code, ושמרתי יישור לימין לטקסט הרגיל. בדקתי על שלושה פתקים עם תוכן מעורב, '
    'כולל שורות שמתחילות במספר ושורות שמתחילות בסוגריים. נשאר מקרה אחד: קוד inline בתוך משפט עברי '
    'עדיין קופץ לסוף השורה כשהוא אחרון. אפשר לפתור עם unicode-bidi: isolate על code, אבל זה משפיע '
    'גם על תצוגת החיפוש, אז עוד לא נגעתי בזה. השינויים ב-NoteBody.tsx וב-note.css.'
)


# --- הדפדפן והעמוד ----------------------------------------------------------------


@contextlib.contextmanager
def _browser(executable, viewport, *, scrollbars=False):
    """**המקום היחיד שמרים דפדפן בקובץ.** ``--window-size`` כמו האזור, כמו בשאר קובצי הדפדפן."""
    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(
                executable_path=executable,
                args=[f"--window-size={viewport['width']},{viewport['height']}"],
                # פסי גלילה גלויים — Playwright מסתיר אותם כברירת מחדל, ובלעדיהם בדיקת
                # הדליפה לא הייתה רואה את הקצה המרובע של הפס.
                ignore_default_args=["--hide-scrollbars"] if scrollbars else None,
            )
        except PlaywrightError as exc:  # pragma: no cover - תלוי בסביבה
            pytest.skip(f"אין Chromium זמין: {exc}")
        try:
            yield browser
        finally:
            browser.close()


#: אין אנימציה שרצה — הפתק נכנס באנימציית קנה מידה (``noteAppear``), ובזמנה כל המלבנים קטנים.
SETTLED_JS = "() => !document.getAnimations().some(a => a.playState === 'running')"

NOTE_SEL = '.sticky-note[data-note-id="{}"]'

_RECT = ("(el) => { const q = el.getBoundingClientRect(); return {left: q.left, right: q.right, top: q.top,"
         " bottom: q.bottom, width: q.width, height: q.height}; }")

#: שורת הבועות של פתק, כפי שהיא מצוירת.
BUBBLES_JS = """(nid) => {
  const rect = %s;
  const note = document.querySelector(`.sticky-note[data-note-id="${nid}"]`);
  if (!note) return {ok: false, why: 'הפתק אינו בעמוד'};
  const ncs = getComputedStyle(note);
  const r = note.getBoundingClientRect();
  const bw = (s) => parseFloat(ncs[s]) || 0;
  const pad = {left: r.left + bw('borderLeftWidth'), right: r.right - bw('borderRightWidth'),
               top: r.top + bw('borderTopWidth'), bottom: r.bottom - bw('borderBottomWidth')};
  const row = note.querySelector(':scope > .sticky-threads');
  const slots = row ? [...row.children].map((slot) => {
    const b = slot.querySelector('.sticky-thread-bubble');
    const bcs = getComputedStyle(b);
    const w = b.querySelector('.sticky-thread-waiting');
    const wcs = w && getComputedStyle(w);
    const stick = slot.querySelector('.sticky-thread-stick');
    const scs = getComputedStyle(stick);
    return {
      id: b.dataset.threadId,
      text: [...b.childNodes].filter((n) => n.nodeType === 3).map((n) => n.textContent).join(''),
      label: b.getAttribute('aria-label'), expanded: b.getAttribute('aria-expanded'),
      active: b.classList.contains('is-active'),
      kind: slot.classList.contains('is-chip') ? 'chip' : (slot.classList.contains('is-new') ? 'new' : 'thread'),
      resolved: slot.classList.contains('is-resolved'),
      rect: rect(b), radius: bcs.borderTopLeftRadius, bg: bcs.backgroundColor, color: bcs.color,
      border: `${bcs.borderTopStyle} ${bcs.borderTopWidth} ${bcs.borderTopColor}`,
      shadow: bcs.boxShadow, opacity: getComputedStyle(slot).opacity,
      waiting: w ? {rect: rect(w), bg: wcs.backgroundColor, borderWidth: wcs.borderTopWidth,
                    borderColor: wcs.borderTopColor} : null,
      stick: rect(stick), stickBg: scs.backgroundColor,
      stickBorder: `${scs.borderInlineStartStyle} ${scs.borderInlineStartWidth}`,
      anchor: rect(slot.querySelector('.sticky-thread-anchor')),
      anchorBg: getComputedStyle(slot.querySelector('.sticky-thread-anchor')).backgroundColor,
    };
  }) : [];
  const surface = document.querySelector('.board-surface');
  return {ok: true, note: rect(note), pad, cls: note.className, slots,
          rowShown: !!row && getComputedStyle(row).display !== 'none',
          surfaceBg: surface ? getComputedStyle(surface).backgroundColor : null};
}""" % _RECT

#: החלונית הפתוחה של פתק — ``{open: false}`` כשאין.
PANEL_JS = """(nid) => {
  const rect = %s;
  const note = document.querySelector(`.sticky-note[data-note-id="${nid}"]`);
  const p = note && note.querySelector(':scope > [data-testid="thread-panel"]');
  if (!p) return {open: false};
  const cs = getComputedStyle(p);
  const q = (sel) => p.querySelector(sel);
  const text = (sel) => { const el = q(sel); return el ? el.textContent : null; };
  const shown = (el) => !!el && !el.hidden && getComputedStyle(el).display !== 'none';
  const arrow = q(':scope > .sticky-thread-arrow');
  const input = q('.sticky-thread-input');
  const ics = getComputedStyle(input);
  const dot = q('.sticky-thread-head .sticky-thread-dot');
  const dcs = getComputedStyle(dot);
  const counter = q('.sticky-thread-counter');
  const err = q('[data-testid="thread-error"]');
  const body = q('.sticky-thread-body');
  return {
    open: true, state: p.dataset.state, narrow: p.classList.contains('is-narrow'),
    busy: p.classList.contains('is-busy'), focused: p.contains(document.activeElement),
    rect: rect(p), bg: cs.backgroundColor, color: cs.color, radius: cs.borderTopLeftRadius,
    border: `${cs.borderTopStyle} ${cs.borderTopWidth} ${cs.borderTopColor}`,
    title: text('.sticky-thread-title'), titleColor: getComputedStyle(q('.sticky-thread-title')).color,
    meta: text('.sticky-thread-meta'),
    dot: {bg: dcs.backgroundColor, border: `${dcs.borderTopStyle} ${dcs.borderTopWidth} ${dcs.borderTopColor}`},
    arrow: shown(arrow) ? rect(arrow) : null,
    status: text('.sticky-thread-status'), hint: text('.sticky-thread-hint'),
    bodyMaxHeight: getComputedStyle(body).maxHeight,
    comments: [...p.querySelectorAll('.sticky-thread-comment')].map((c) => {
      const b = c.querySelector('.sticky-thread-comment-body');
      const av = c.querySelector('.sticky-thread-avatar');
      const work = c.querySelector('.sticky-thread-working-on');
      const more = c.querySelector('.sticky-thread-more-text');
      return {tone: c.dataset.authorTone || '', bg: getComputedStyle(c).backgroundColor,
              avatar: av.textContent, avatarBg: getComputedStyle(av).backgroundColor,
              author: c.querySelector('.sticky-thread-author').textContent,
              workingOn: work ? work.textContent : '', time: c.querySelector('.sticky-thread-time').textContent,
              body: b.textContent, clamped: b.classList.contains('is-clamped'),
              bodyHeight: b.getBoundingClientRect().height, lineHeight: parseFloat(getComputedStyle(b).lineHeight),
              more: more ? more.textContent : null};
    }),
    resolvedLabel: text('.sticky-thread-resolved-label'), resolvedCount: text('.sticky-thread-resolved-count'),
    resolvedExpanded: q('.sticky-thread-resolved-row')
      ? q('.sticky-thread-resolved-row').getAttribute('aria-expanded') : null,
    reopen: q('.sticky-thread-reopen') ? {disabled: q('.sticky-thread-reopen').disabled} : null,
    composer: shown(q('.sticky-thread-composer')),
    input: {value: input.value, placeholder: input.placeholder, readOnly: input.readOnly,
            bg: ics.backgroundColor, color: ics.color,
            border: `${ics.borderTopStyle} ${ics.borderTopWidth} ${ics.borderTopColor}`,
            outline: ics.outlineStyle, shadow: ics.boxShadow,
            height: input.getBoundingClientRect().height, focused: document.activeElement === input},
    counter: {text: counter.textContent, over: counter.classList.contains('is-over'), shown: shown(counter),
              color: getComputedStyle(counter).color},
    buttons: [...p.querySelectorAll('.sticky-thread-actions .sticky-thread-btn')].filter(shown)
      .map((b) => [b.textContent, b.disabled]),
    inputRect: rect(input), actionsRect: rect(q('.sticky-thread-actions')),
    error: shown(err) ? err.textContent : '',
  };
}""" % _RECT

#: מה נמצא בנקודה: מזהה הבועה (או "+N"/"new"), או שם המחלקה של מה שיש שם.
#: נקודה ריקה בלוח — לא פתק, לא שרשור, לא כפתור: "לחיצה בחוץ" שלא מפעילה שום דבר אחר.
EMPTY_POINT_JS = """() => {
  const s = document.querySelector('.board-surface').getBoundingClientRect();
  for (let y = s.bottom - 10; y > s.top + 10; y -= 15) {
    for (let x = s.left + 10; x < s.right - 10; x += 15) {
      const el = document.elementFromPoint(x, y);
      if (el && el.closest('.board-surface') && !el.closest('.sticky-note, a, button, input, textarea')) {
        return {ok: true, x, y};
      }
    }
  }
  return {ok: false};
}"""

HIT_JS = """([x, y]) => {
  const el = document.elementFromPoint(x, y);
  const b = el && el.closest && el.closest('.sticky-thread-bubble');
  return b ? b.dataset.threadId : (el ? (el.className || el.tagName) : null);
}"""


class ThreadsPage:
    """עמוד אמיתי של המשתמש המחובר, עם רישום של כל שגיאת JS שבו."""

    def __init__(self, browser, server, db, viewport, *, local_storage=None, route=None):
        self.server = server
        self.db = db
        self.context = browser.new_context(viewport=viewport, device_scale_factor=DPR, locale="he-IL")
        self.context.add_cookies([{"name": "session", "value": server.session_cookie,
                                   "domain": "127.0.0.1", "path": "/"}])
        seed = {"welcomeModalSeen": "1", "onboarding_completed": "1", **(local_storage or {})}
        self.context.add_init_script(
            "try{" + "".join(f"localStorage.setItem({json.dumps(k)},{json.dumps(v)});" for k, v in seed.items())
            + "}catch(e){}"
        )
        self.page = self.context.new_page()
        self._errors: list[str] = []
        self.page.on("pageerror", lambda e: self._errors.append(f"pageerror: {e}"))
        self.page.on("console", self._on_console)
        # תשובת 5xx מהשרת שלנו היא כשל, גם כשהממשק בלע אותה: הקונסול מדווח עליה רק כ-"Failed
        # to load resource", שמסונן למטה — ולכן היא נספרת כאן, מהרשת עצמה.
        self.page.on("response", lambda r: self._errors.append(f"HTTP {r.status}: {r.url}")
                     if r.status >= 500 and urlsplit(r.url).hostname == "127.0.0.1" else None)
        # בקשות לכל מארח אחר נקטעות (גופנים, CDN) — כמו ב-``open_admin_page``. ``route`` של
        # בדיקה, כשיש, מחליט על השאר; הראוט שנרשם אחרון מנצח (``stub_profiler_api``).
        self.page.route("**/*", route or self._local_only)

    @staticmethod
    def _local_only(route):
        if urlsplit(route.request.url).hostname != "127.0.0.1":
            route.abort()
        else:
            route.continue_()

    def _on_console(self, msg):
        """שגיאת קונסול נספרת — חוץ משני דיווחים שהדפדפן עצמו כותב, ולא קוד:

        - "Failed to load resource" — בקשה שנכשלה: מארח חיצוני שנקטע, או 4xx שהבדיקה גרמה לו
          בכוונה (5xx נספר בנפרד, מהרשת).
        - "Refused to load" של משאב **ממארח חיצוני** — ה-CSP של העמוד חוסם אותו גם בייצור (דפדפן
          הריפו מפנה ל-CodeMirror 5 ב-cdnjs; ``tests/test_repo_notes_browser.py``). משאב שלנו
          שנחסם היה נספר: הכתובת שלו היא של השרת הזה.
        """
        if msg.type != "error":
            return
        text = msg.text
        if text.startswith("Failed to load resource"):
            return
        if text.startswith("Refused to load") and "'http://127.0.0.1" not in text:
            return
        self._errors.append(f"console.error: {text}")

    def api(self, method, path, body=None):
        res = self.context.request.fetch(
            self.server.base_url + path, method=method,
            data=None if body is None else json.dumps(body),
            headers={"Content-Type": "application/json"},
        )
        assert res.ok, (method, path, res.status, res.text())
        return res.json()

    def goto(self, path):
        self.page.goto(self.server.base_url + path, wait_until="load")
        # מודאל הפתיחה מכסה את העמוד ובולע לחיצות — כמו ב-``open_admin_page``.
        self.page.evaluate("document.querySelectorAll('.welcome-modal, .welcome-modal__backdrop,"
                           " #welcomeModal').forEach(e => e.remove())")

    def settle(self):
        poll(self.page, SETTLED_JS, "אין אנימציה שרצה")

    def bubbles(self, nid):
        return self.page.evaluate(BUBBLES_JS, nid)

    def wait_bubbles(self, nid, count):
        poll(self.page, "([nid, n]) => { const r = document.querySelector(`.sticky-note[data-note-id=\"${nid}\"]"
                        " > .sticky-threads`); const k = r ? r.children.length : 0; return {ok: k === n, k}; }",
             f"{count} בועות מעל הפתק", [nid, count])
        self.settle()
        return self.bubbles(nid)

    def panel(self, nid):
        return self.page.evaluate(PANEL_JS, nid)

    def wait_panel(self, nid, state, comments=None):
        """החלונית במצב ``state``, לא באמצע שליחה, ועם ``comments`` תגובות (כשנמסר)."""
        poll(self.page, """([nid, state, n]) => {
              const p = document.querySelector(`.sticky-note[data-note-id="${nid}"] > [data-testid="thread-panel"]`);
              if (!p) return {ok: false, panel: 'אין'};
              const k = p.querySelectorAll('.sticky-thread-comment').length;
              return {ok: p.dataset.state === state && !p.classList.contains('is-busy') && (n === null || k === n),
                      state: p.dataset.state, busy: p.classList.contains('is-busy'), comments: k};
            }""", f"חלונית במצב {state}", [nid, state, comments])
        self.settle()
        return self.panel(nid)

    def hit(self, x, y):
        return self.page.evaluate(HIT_JS, [x, y])

    def note(self, nid):
        return self.page.locator(NOTE_SEL.format(nid))

    def bubble(self, nid, thread_id):
        return self.note(nid).locator(f':scope > .sticky-threads [data-thread-id="{thread_id}"]')

    def panel_button(self, nid, name):
        return self.note(nid).locator(':scope > [data-testid="thread-panel"]').get_by_role(
            "button", name=name, exact=True)

    def panel_input(self, nid):
        return self.note(nid).locator(':scope > [data-testid="thread-panel"] .sticky-thread-input')

    def js_errors(self):
        return list(self._errors)


@contextlib.contextmanager
def threads_page(server, executable, db, viewport=DESKTOP, **kwargs):
    with _browser(executable, viewport, scrollbars=kwargs.pop("scrollbars", False)) as browser:
        yield ThreadsPage(browser, server, db, viewport, **kwargs)


# --- נתונים: דרך ה-API של הממשק, והשרשורים דרך המודול שכותב אותם -----------------------


@pytest.fixture(autouse=True)
def _fresh_rate_limits(monkeypatch):
    """מגבלות הקצב של ראוטי הפתקים חיות בזיכרון התהליך (``_RATE_LOG``), והשרת משותף לכל
    הקובץ — בלי איפוס, בדיקה מאוחרת הייתה נחסמת בגלל כתיבות של קודמותיה (T3: מצב משותף בלי
    איפוס בין בדיקות). ``_rate_limit_check`` קורא את השם בזמן הקריאה, ולכן החלפת המילון מספיקה."""
    import webapp.sticky_notes_api as sticky_notes_api

    monkeypatch.setattr(sticky_notes_api, "_RATE_LOG", {})


def _board(tp, name="שרשורים"):
    return tp.api("POST", "/api/note-boards", {"name": name})["board"]["id"]


def _board_note(tp, board, *, x, y, w, h=200, content="פתק על לוח"):
    body = {"content": content, "position": {"x": x, "y": y}, "size": {"width": w, "height": h}}
    return tp.api("POST", f"/api/sticky-notes/board/{board}", body)["id"]


def _thread(db, note_id, *comments, resolved_by=None):
    """שרשור כמו שהמודול כותב אותו. ``comments`` — ``(כותב, גוף, לפני כמה דקות)``, לפי הסדר;
    ``resolved_by`` — ``(כותב, לפני כמה דקות)``. המספר "שרשור N" נקבע לפי זמן היצירה, ולכן
    שרשורים נזרעים מהישן לחדש."""
    coll = db[nt.NOTE_THREADS_COLLECTION]
    now = datetime.now(timezone.utc)
    (author, body, ago), *rest = comments
    res = nt.create_thread(coll, user_id=USER_ID, note_id=note_id, author=author, body=body,
                           now=now - timedelta(minutes=ago))
    assert res["ok"], res
    tid = res["thread_id"]
    for author, body, ago in rest:
        res = nt.add_comment(coll, user_id=USER_ID, note_id=note_id, thread_id=tid, author=author,
                             body=body, now=now - timedelta(minutes=ago))
        assert res["ok"], res
    if resolved_by is not None:
        author, ago = resolved_by
        res = nt.resolve_thread(coll, user_id=USER_ID, note_id=note_id, thread_id=tid, author=author,
                                now=now - timedelta(minutes=ago))
        assert res["ok"], res
    return tid


def _doc(db, tid):
    return db[nt.NOTE_THREADS_COLLECTION].find_one({"_id": ObjectId(tid)})


def _wait_doc(db, tid, check, what):
    """השרשור במסד, כשהוא כבר במצב ש-``check`` מאשר — המסד הוא מה שנבדק, לא התשובה."""
    deadline = time.monotonic() + WAIT_S
    while True:
        doc = _doc(db, tid)
        if doc is not None and check(doc):
            return doc
        if time.monotonic() > deadline:
            seen = None if doc is None else {k: doc.get(k) for k in
                                             ("status", "comment_count", "last_author_kind", "resolved_by")}
            raise AssertionError(f"המסד לא הגיע למצב תוך {WAIT_S} שניות: {what} — נצפה: {seen!r}")
        time.sleep(0.1)


def _bodies(doc):
    return [c["body"] for c in doc["comments"]]


def _near(a, b, tol=0.5):
    return abs(a - b) <= tol


def _center_x(rect):
    return (rect["left"] + rect["right"]) / 2


def _assert_clean(tp):
    assert tp.js_errors() == [], f"שגיאות JS בעמוד: {tp.js_errors()}"


# --- בועות ----------------------------------------------------------------------------


def test_bubbles_sit_on_the_note_as_designed(wired_mongo, admin_live_server, chromium_executable):
    """מצבים 2–3 בעיצוב: גוון לפי המספר, ✓ לשרשור שנפתר, "מחכה לך", ומידות — ושטח לחיצה 44×44
    לכל בועה, בלי חפיפה בין שכנות."""
    db = wired_mongo.get_db()
    with threads_page(admin_live_server, chromium_executable, db) as tp:
        board = _board(tp)
        nid = _board_note(tp, board, x=300, y=240, w=260)
        t1 = _thread(db, nid, (USER, "כשיש בפתק קוד באנגלית, השורות מתהפכות.", 30),
                     (CC, "מצאתי את המקור.", 12))
        t2 = _thread(db, nid, (GEMINI, "בדקתי ניגודיות.", 28), (USER, "מעולה, תודה.", 27),
                     resolved_by=(USER, 26))
        t3 = _thread(db, nid, (USER, "עוד שאלה.", 5))
        tp.goto(f"/boards/{board}")
        row = tp.wait_bubbles(nid, 3)
        slots, pad = row["slots"], row["pad"]

        assert [s["id"] for s in slots] == [t1, t2, t3]
        assert [s["kind"] for s in slots] == ["thread"] * 3
        assert [s["text"] for s in slots] == ["2", "✓", "1"]
        assert [s["label"] for s in slots] == [
            "שרשור 1 · 2 תגובות · מחכה לך", "שרשור 2 · 2 תגובות · נפתר", "שרשור 3 · 1 תגובה"]
        for s in slots:
            assert _near(s["rect"]["width"], PILL_W) and _near(s["rect"]["height"], PILL_H), s["rect"]
            assert s["radius"] == PILL_RADIUS
        # גוון לפי המספר; נפתר — כרומה 0.03 ושקיפות .6
        assert [s["bg"] for s in slots] == [TONES[0], RESOLVED_TONES[1], TONES[2]]
        assert [s["opacity"] for s in slots] == ["1", "0.6", "1"]
        # "מחכה לך": 10px, מסגרת 2px בצבע הלוח, 4px מעל ומחוץ לפינה (שמאל, ב-RTL)
        waiting = slots[0]["waiting"]
        assert waiting is not None and slots[1]["waiting"] is None and slots[2]["waiting"] is None
        assert waiting["bg"] == WAITING_RED and waiting["borderWidth"] == "2px"
        assert waiting["borderColor"] == row["surfaceBg"], (waiting, row["surfaceBg"])
        assert _near(waiting["rect"]["width"], 14) and _near(waiting["rect"]["height"], 14)
        assert _near(waiting["rect"]["top"], slots[0]["rect"]["top"] - 4)
        assert _near(waiting["rect"]["left"], slots[0]["rect"]["left"] - 4)

        # 14px מהקצה (מימין, ב-RTL), ו-44 בין מרכזים — מימין ← לשמאל
        assert _near(slots[0]["rect"]["right"], pad["right"] - EDGE), (slots[0]["rect"], pad)
        centers = [_center_x(s["rect"]) for s in slots]
        assert all(_near(a - b, PITCH) for a, b in zip(centers, centers[1:])), centers
        for s in slots:
            # מקל 2×10 מתחת לבועה, ונקודת עיגון 7px שמרכזה על קו הפתק
            assert _near(s["stick"]["width"], STICK_W) and _near(s["stick"]["height"], STICK_H), s["stick"]
            assert _near(s["stick"]["top"], s["rect"]["bottom"]) and _near(_center_x(s["stick"]), _center_x(s["rect"]))
            assert _near(s["anchor"]["width"], ANCHOR) and _near(s["anchor"]["top"], s["stick"]["bottom"])
            assert _near((s["anchor"]["top"] + s["anchor"]["bottom"]) / 2, pad["top"]), (s["anchor"], pad)
        assert slots[1]["stickBorder"] == "dotted 2px"   # מקל מנוקד לשרשור שנפתר

        # שטח הלחיצה: 44×44 לכל בועה — מראש אזור הבועות עד קו הפתק — ונוגע בשכנה בלי לחפוף.
        # **בדיקת הפגיעה של כרומיום מעגלת את הקופסאות לפיקסלים שלמים** (נמדד: הפתק עצמו נתפס
        # מ-0.8px לפני המלבן שלו), ולכן הגבולות החיצוניים נבדקים בפער של 1.5px. הגבול בין שתי
        # שכנות נבדק בחצי פיקסל: שתיהן באותה שכבה, והעיגול זהה לשתיהן.
        for s, cx in zip(slots, centers):
            for dx in (-21.5, 21.5):
                for y in (pad["top"] - ZONE + 0.5, pad["top"] - 0.5):
                    assert tp.hit(cx + dx, y) == s["id"], (s["id"], dx, y)
            assert tp.hit(cx, pad["top"] - ZONE - 1.5) != s["id"]
        mid = pad["top"] - ZONE / 2
        for (a, ca), (b, _cb) in zip(zip(slots, centers), zip(slots[1:], centers[1:])):
            boundary = ca - PITCH / 2
            assert tp.hit(boundary + 0.5, mid) == a["id"] and tp.hit(boundary - 0.5, mid) == b["id"]
        assert tp.hit(centers[0] + PITCH / 2 + 1.5, mid) not in {s["id"] for s in slots}
        assert tp.hit(centers[-1] - PITCH / 2 - 1.5, mid) not in {s["id"] for s in slots}

        # 💬 בשורת הפעולות, בין 🔔 ל-↶ (העיצוב; הכרעה 1-ב)
        order = tp.page.evaluate("""(nid) => [...document.querySelector(`.sticky-note[data-note-id="${nid}"]`
            + ' .sticky-note-actions').children].map((b) => b.textContent.trim())""", nid)
        i = order.index("💬")
        assert order[i - 1] == "🔔" and order[i + 1] == "↶", order

        # לחיצה בשטח הלחיצה, מעל הבועה הגלויה — פותחת את השרשור שלה
        tp.page.mouse.click(centers[2] + 19, slots[2]["rect"]["top"] - 3)
        panel = tp.wait_panel(nid, "open", 1)
        assert panel["title"] == "שרשור 3"
        _assert_clean(tp)


def test_overflow_bubble_follows_the_design_formula_and_lists_the_rest(
        wired_mongo, admin_live_server, chromium_executable):
    """מצב 7: מספר הבועות הגלויות הוא floor((רוחב − 20) / 44) − 1, ואחריהן "+N" עם הרשימה —
    ונקודת "מחכה לך" על "+N" כשאחד המוסתרים מחכה. ובגבולות: כשהכול נכנס — אין "+N"."""
    db = wired_mongo.get_db()
    with threads_page(admin_live_server, chromium_executable, db) as tp:
        board = _board(tp)
        narrow = _board_note(tp, board, x=500, y=240, w=260, h=230)
        ids = [
            _thread(db, narrow, (USER, "א", 70), (CC, "ב", 69), (USER, "ג", 68)),   # 1: 3
            _thread(db, narrow, (USER, "א", 60), resolved_by=(USER, 59)),        # 2: ✓
            _thread(db, narrow, (USER, "א", 50), (USER, "ב", 49)),               # 3: 2
            _thread(db, narrow, (USER, "א", 40)),                                # 4: 1
            _thread(db, narrow, (USER, "א", 30)),                                # 5 — מוסתר
            _thread(db, narrow, (USER, "א", 20), (GEMINI, "ב", 19)),             # 6 — מוסתר, מחכה
            _thread(db, narrow, (USER, "א", 10), resolved_by=(CC, 9)),           # 7 — מוסתר, נפתר
        ]
        # שני פתקים על גבול הנוסחה, עם ארבעה שרשורים: 196 = 20 + 4·44 — נכנסים בדיוק; 195 — לא.
        exact = _board_note(tp, board, x=80, y=560, w=196)
        short = _board_note(tp, board, x=420, y=560, w=195)
        for nid in (exact, short):
            for k in range(4):
                _thread(db, nid, (USER, f"שרשור {k}", 40 - k))
        tp.goto(f"/boards/{board}")

        row = tp.wait_bubbles(narrow, 5)
        visible = (260 - 20) // PITCH - 1
        assert visible == 4
        slots = row["slots"]
        assert [s["kind"] for s in slots] == ["thread"] * visible + ["chip"]
        assert [s["text"] for s in slots] == ["3", "✓", "2", "1", "+3"]
        assert [s["id"] for s in slots[:visible]] == ids[:visible]
        chip = slots[-1]
        assert chip["bg"] == CHIP_BG and _near(chip["rect"]["width"], PILL_W)
        assert chip["waiting"] is not None and chip["waiting"]["bg"] == WAITING_RED
        centers = [_center_x(s["rect"]) for s in slots]
        assert all(_near(a - b, PITCH) for a, b in zip(centers, centers[1:])), centers
        assert tp.wait_bubbles(exact, 4)["slots"][-1]["kind"] == "thread"          # כולם נכנסים
        assert [s["kind"] for s in tp.bubbles(short)["slots"]] == ["thread", "thread", "chip"]
        assert tp.bubbles(short)["slots"][-1]["text"] == "+2"

        # הרשימה: יושרה לקצה של "+N" (ימין, ב-RTL), 10px מתחת לראש הפתק, והחץ מעל מרכזו
        tp.bubble(narrow, "more").click()
        menu = poll(tp.page, """(nid) => {
            const m = document.querySelector(`.sticky-note[data-note-id="${nid}"] > .sticky-thread-menu`);
            if (!m) return {ok: false};
            const r = m.getBoundingClientRect();
            const a = m.querySelector('.sticky-thread-arrow').getBoundingClientRect();
            return {ok: true, left: r.left, right: r.right, top: r.top, width: r.width, arrow: (a.left + a.right) / 2,
                    items: [...m.querySelectorAll('[role="menuitem"]')].map((i) => [
                      i.dataset.threadId, i.querySelector('.sticky-thread-menu-name').textContent,
                      i.querySelector('.sticky-thread-menu-meta').textContent,
                      !!i.querySelector('.sticky-thread-menu-waiting')]),
                    focused: document.activeElement && document.activeElement.dataset.threadId};
        }""", "רשימת +N נפתחה", narrow)
        assert menu["items"] == [[ids[4], "שרשור 5", "1 תגובה", False],
                                 [ids[5], "שרשור 6", "2 תגובות", True],
                                 [ids[6], "שרשור 7", "✓ נפתר", False]]
        chip = tp.bubbles(narrow)["slots"][-1]
        assert chip["expanded"] == "true" and PAPER + " 0px 0px 0px 2px" in chip["shadow"]
        assert _near(menu["right"], chip["rect"]["right"], 1) and _near(menu["width"], 200)
        assert _near(menu["top"], row["pad"]["top"] + PANEL_TOP, 1)
        assert _near(menu["arrow"], _center_x(chip["rect"]), 1)
        assert menu["focused"] == ids[4]                       # הפוקוס על הפריט הראשון

        # Escape סוגר ומחזיר את הפוקוס ל-"+N"; לחיצה מחוץ לרשימה סוגרת גם היא
        tp.page.keyboard.press("Escape")
        poll(tp.page, "() => !document.querySelector('.sticky-thread-menu')", "הרשימה נסגרה")
        assert tp.page.evaluate("() => document.activeElement.dataset.threadId") == "more"
        tp.bubble(narrow, "more").click()
        tp.page.wait_for_selector(".sticky-thread-menu")
        spot = poll(tp.page, EMPTY_POINT_JS, "נקודה ריקה בלוח")
        tp.page.mouse.click(spot["x"], spot["y"])
        poll(tp.page, "() => !document.querySelector('.sticky-thread-menu')", "לחיצה בחוץ סגרה את הרשימה")

        # בחירה מהרשימה פותחת את השרשור; "+N" פעיל, והחלונית מצביעה עליו
        tp.bubble(narrow, "more").click()
        tp.page.locator(f'.sticky-thread-menu [data-thread-id="{ids[5]}"]').click()
        panel = tp.wait_panel(narrow, "open", 2)
        assert panel["title"] == "שרשור 6"
        chip = tp.bubbles(narrow)["slots"][-1]
        assert chip["active"] and _near(_center_x(panel["arrow"]), _center_x(chip["rect"]), 1)

        # הפתק הורחב (כמו בשינוי גודל ביד) — הכול נכנס, ו-"+N" נעלם
        tp.page.evaluate("(nid) => { document.querySelector(`.sticky-note[data-note-id=\"${nid}\"]`)"
                         ".style.width = '360px'; }", narrow)
        assert [s["kind"] for s in tp.wait_bubbles(narrow, 7)["slots"]] == ["thread"] * 7
        _assert_clean(tp)


# --- החלונית --------------------------------------------------------------------------


def test_open_thread_panel_matches_the_design_wide_and_narrow(
        wired_mongo, admin_live_server, chromium_executable):
    """מצבים 4, 6a ו-6b: החלונית בפתק רחב (360) ובפתק צר מ-376 (280), כל כותב בצבע שלו, זמן יחסי
    (מקוצר בחלונית הצרה), ותגובה ארוכה שנחתכת ב-6 שורות עם "הצגת הכול"."""
    db = wired_mongo.get_db()
    with threads_page(admin_live_server, chromium_executable, db) as tp:
        board = _board(tp)
        wide = _board_note(tp, board, x=60, y=260, w=420, h=260)
        narrow = _board_note(tp, board, x=760, y=260, w=NARROW_BELOW - 1, h=260)
        t1 = _thread(db, wide, (USER, "כשיש בפתק קוד באנגלית, השורות מתהפכות. אפשר לבדוק למה?", 20),
                     (CC, LONG_TEXT, 12), (CLAUDE, "עברתי על השינוי. ממליץ להוסיף.", 4),
                     (GEMINI, "בדקתי.", 4), (CURSOR, "גם אני.", 4), (NAMELESS, "ואני.", 4))
        t2 = _thread(db, narrow, (USER, "שאלה קצרה", 20), (CC, "תשובה קצרה", 12))
        tp.goto(f"/boards/{board}")
        row = tp.wait_bubbles(wide, 1)
        tp.bubble(wide, t1).click()
        panel = tp.wait_panel(wide, "open", 6)
        pad = row["pad"]
        bubble = tp.bubbles(wide)["slots"][0]

        assert not panel["narrow"] and _near(panel["rect"]["width"], PANEL_W)
        assert _near(panel["rect"]["top"], pad["top"] + PANEL_TOP)
        assert _near(panel["rect"]["right"], pad["right"] - PANEL_SIDE)
        assert (panel["bg"], panel["color"], panel["radius"]) == (PAPER, INK, "12px")
        assert _near(_center_x(panel["arrow"]), _center_x(bubble["rect"]), 1)          # החץ מעל הבועה
        # החץ: ריבוע 12px מסובב, ``top: -6px`` — מרכזו על הקצה העליון של החלונית (המלבן של
        # ריבוע מסובב גדול ממנו, ולכן נמדד המרכז)
        assert _near((panel["arrow"]["top"] + panel["arrow"]["bottom"]) / 2, panel["rect"]["top"], 1)
        assert bubble["active"] and PAPER + " 0px 0px 0px 2px" in bubble["shadow"]     # טבעת 2px בצבע החלונית
        assert (panel["title"], panel["meta"], panel["dot"]["bg"]) == ("שרשור 1", "· 6 תגובות", TONES[0])
        assert panel["bodyMaxHeight"] == "420px"

        comments = panel["comments"]
        assert [c["tone"] for c in comments] == ["user", "cc", "claude", "gemini", "agent", "agent"]
        assert [c["bg"] for c in comments] == [AUTHOR_BG[c["tone"]] for c in comments]
        assert [c["avatarBg"] for c in comments] == [AVATAR_BG[c["tone"]] for c in comments]
        assert [c["author"] for c in comments] == [ME, "CC", "Claude", "Gemini", "Cursor", nt.UNKNOWN_AGENT_LABEL]
        assert [c["avatar"] for c in comments] == [ME_INITIALS, "CC", "C", "G", "C", nt.UNKNOWN_AGENT_LABEL[0]]
        assert [c["workingOn"] for c in comments] == [
            "", "· תיקון כיוון קוד", "· סקירת קוד", "· בדיקת נגישות", "· בדיקה", "· בדיקה"]
        assert [c["time"] for c in comments[:3]] == ["לפני 20 דק׳", "לפני 12 דק׳", "לפני 4 דק׳"]

        # התגובה הארוכה: 6 שורות, ו"הצגת הכול · N תווים" — N בנקודות קוד, כמו בעיצוב
        long = comments[1]
        assert long["clamped"] and _near(long["bodyHeight"], 6 * long["lineHeight"], 1), long
        assert long["more"] == f"הצגת הכול · {len(LONG_TEXT)} תווים"
        assert [c["more"] for c in comments if c is not long] == [None] * 5
        tp.note(wide).get_by_role("button", name=long["more"]).click()
        opened = tp.panel(wide)["comments"][1]
        assert not opened["clamped"] and opened["bodyHeight"] > 6 * opened["lineHeight"]
        assert opened["more"] == "הצגת פחות"
        tp.note(wide).get_by_role("button", name="הצגת פחות").click()
        assert tp.panel(wide)["comments"][1]["clamped"]

        # תיבת הכתיבה (מצב 4)
        assert panel["input"]["placeholder"] == "כתיבת תשובה…" and panel["input"]["bg"] == "rgb(255, 255, 255)"
        assert panel["input"]["color"] == INK
        assert panel["counter"]["text"] == f"0 / {COMMENT_CAP:,}"
        assert panel["buttons"] == [["✓ נפתר", False], ["שליחה", True]]

        # פתק צר מ-376: חלונית של 280, זמן מקוצר. ופתיחתה סוגרת את החלונית בפתק השני.
        tp.bubble(narrow, t2).click()
        small = tp.wait_panel(narrow, "open", 2)
        assert tp.panel(wide) == {"open": False}
        npad = tp.bubbles(narrow)["pad"]
        assert small["narrow"] and _near(small["rect"]["width"], PANEL_NARROW_W)
        assert _near(small["rect"]["right"], npad["right"] - PANEL_SIDE)
        assert [c["time"] for c in small["comments"]] == ["20 דק׳", "12 דק׳"]
        assert small["bodyMaxHeight"] == "400px"
        _assert_clean(tp)


def test_new_thread_is_saved_only_with_its_first_comment(wired_mongo, admin_live_server, chromium_executable):
    """מצב 8: 💬 פותח שרשור חדש — בועה מקווקוות עם "+" בגוון הבא — ושום דבר אינו נכתב עד
    התגובה הראשונה. סגירה בלי שליחה מבטלת אותו, והטיוטה נשמרת. ואחרי השליחה — נקרא מהמסד."""
    db = wired_mongo.get_db()
    coll = db[nt.NOTE_THREADS_COLLECTION]
    with threads_page(admin_live_server, chromium_executable, db) as tp:
        board = _board(tp)
        nid = _board_note(tp, board, x=200, y=260, w=420, h=260)
        _thread(db, nid, (USER, "א", 30), (CC, "ב", 29))
        _thread(db, nid, (USER, "א", 20), (USER, "ב", 19), (USER, "ג", 18))
        tp.goto(f"/boards/{board}")
        tp.wait_bubbles(nid, 2)
        threads_btn = tp.note(nid).locator(".sticky-note-threads-btn")
        threads_btn.click()
        row = tp.wait_bubbles(nid, 3)
        new = row["slots"][-1]
        panel = tp.wait_panel(nid, "new", 0)

        assert threads_btn.get_attribute("aria-pressed") == "true"
        assert tp.page.evaluate("(b) => [getComputedStyle(b).backgroundColor, getComputedStyle(b).borderRadius]",
                                threads_btn.element_handle()) == [PRESSED_BG, "7px"]
        assert (new["kind"], new["text"], new["active"]) == ("new", "+", True)
        assert new["border"] == f"dashed 2px {TONES[2]}" and new["color"] == TONES[2]   # הגוון הבא בתור
        assert new["bg"] == row["surfaceBg"] and PAPER + " 0px 0px 0px 2px" in new["shadow"]
        assert new["stickBorder"] == "dashed 2px"
        assert (panel["title"], panel["meta"]) == ("שרשור 3", "· חדש")
        assert panel["dot"]["border"] == "dashed 2px oklch(0.62 0.1 300)"
        assert panel["hint"] == "השרשור נשמר עם שליחת התגובה הראשונה. סגירה בלי שליחה מבטלת אותו."
        assert panel["input"]["placeholder"] == "על מה השרשור?" and panel["input"]["focused"]
        assert panel["buttons"] == [["ביטול", False], ["שליחה", True]]
        assert _near(_center_x(panel["arrow"]), _center_x(new["rect"]), 1)
        assert coll.count_documents({"note_id": nid}) == 2                     # שום דבר לא נכתב

        # ביטול: הבועה החדשה נעלמת, שום דבר לא נכתב — והטיוטה חוזרת בפתיחה הבאה
        tp.panel_input(nid).fill("טיוטה")
        tp.panel_button(nid, "ביטול").click()
        tp.wait_bubbles(nid, 2)
        assert tp.panel(nid) == {"open": False} and threads_btn.get_attribute("aria-pressed") == "false"
        threads_btn.click()
        assert tp.wait_panel(nid, "new", 0)["input"]["value"] == "טיוטה"
        assert coll.count_documents({"note_id": nid}) == 2

        text = "האם צריך גם בדיקה בדפדפן?"
        tp.panel_input(nid).fill(text)
        tp.panel_button(nid, "שליחה").click()
        panel = tp.wait_panel(nid, "open", 1)
        assert (panel["title"], panel["meta"]) == ("שרשור 3", "· 1 תגובה")
        assert panel["comments"][0]["body"] == text and panel["comments"][0]["author"] == ME
        assert panel["input"]["value"] == ""
        created = coll.find_one({"note_id": nid, "comment_count": 1})
        assert created is not None, list(coll.find({"note_id": nid}, {"comments": 0}))
        assert (created["status"], created["last_author_kind"], _bodies(created)) == ("open", "user", [text])
        assert created["comments"][0]["author"]["kind"] == "user"
        row = tp.bubbles(nid)
        assert [s["kind"] for s in row["slots"]] == ["thread"] * 3
        assert row["slots"][-1]["id"] == str(created["_id"]) and row["slots"][-1]["bg"] == TONES[2]
        assert threads_btn.get_attribute("aria-pressed") == "false"

        # נקרא שוב מהמסד: אחרי טעינה מחדש — שלוש בועות, והשרשור החדש עם התגובה שלו
        tp.goto(f"/boards/{board}")
        assert [s["text"] for s in tp.wait_bubbles(nid, 3)["slots"]] == ["2", "3", "1"]
        _assert_clean(tp)


def test_reply_resolve_and_reopen_are_saved_and_read_back(wired_mongo, admin_live_server, chromium_executable):
    """הסבב המלא, דרך הכפתורים: תשובה, "✓ נפתר" עם משפט סיכום, תשובה בלי פתיחה, תשובה שפותחת
    (Ctrl+Enter), סגירה בלי טקסט, ו"פתיחה מחדש" — וכל צעד נקרא מהמסד, וגם אחרי טעינה מחדש."""
    db = wired_mongo.get_db()
    with threads_page(admin_live_server, chromium_executable, db) as tp:
        board = _board(tp)
        nid = _board_note(tp, board, x=200, y=260, w=420, h=260)
        tid = _thread(db, nid, (USER, "שאלה", 40), (CC, "תשובה", 30))
        tp.goto(f"/boards/{board}")
        assert tp.wait_bubbles(nid, 1)["slots"][0]["waiting"] is not None
        tp.bubble(nid, tid).click()
        tp.wait_panel(nid, "open", 2)

        # 1. תשובה ("שליחה")
        tp.panel_input(nid).fill("תשובה ראשונה")
        tp.panel_button(nid, "שליחה").click()
        panel = tp.wait_panel(nid, "open", 3)
        doc = _wait_doc(db, tid, lambda d: d["comment_count"] == 3, "התשובה נשמרה")
        assert (doc["status"], doc["last_author_kind"], _bodies(doc)[-1]) == ("open", "user", "תשובה ראשונה")
        assert panel["input"]["value"] == "" and panel["counter"]["text"] == f"0 / {COMMENT_CAP:,}"
        bubble = tp.bubbles(nid)["slots"][0]
        assert bubble["text"] == "3" and bubble["waiting"] is None              # כבר לא מחכה לי

        # 2. "✓ נפתר" עם טקסט: נשלח כמשפט סיכום, והשרשור נסגר באותה כתיבה (הכרעה 2-א)
        tp.panel_input(nid).fill("סיכום: תוקן")
        tp.panel_button(nid, "✓ נפתר").click()
        panel = tp.wait_panel(nid, "resolved", 0)
        doc = _wait_doc(db, tid, lambda d: d["status"] == "resolved", "השרשור נסגר")
        assert doc["comment_count"] == 4 and _bodies(doc)[-1] == "סיכום: תוקן"
        assert doc["resolved_by"]["kind"] == "user"
        assert (panel["title"], panel["titleColor"], panel["meta"]) == ("שרשור 1", MUTED, "")
        assert panel["resolvedLabel"] == f"נפתר ע״י {ME}, עכשיו" and panel["resolvedCount"] == "4 תגובות"
        assert panel["buttons"] == [["שליחה בלי פתיחה", True], ["שליחה ופתיחה מחדש", True]]
        bubble = tp.bubbles(nid)["slots"][0]
        assert (bubble["text"], bubble["resolved"], bubble["bg"]) == ("✓", True, RESOLVED_TONES[0])

        # 3. תשובה בלי פתיחה — המונה בעיצוב (מצב 9): "41 / 4,000"
        text = "לתיעוד: אותו תיקון נכנס גם לגרסת המובייל."
        tp.panel_input(nid).fill(text)
        panel = tp.panel(nid)
        assert panel["counter"]["text"] == f"41 / {COMMENT_CAP:,}"
        assert panel["buttons"] == [["שליחה בלי פתיחה", False], ["שליחה ופתיחה מחדש", False]]
        tp.panel_button(nid, "שליחה בלי פתיחה").click()
        poll(tp.page, """(nid) => { const c = document.querySelector(`.sticky-note[data-note-id="${nid}"]
              .sticky-thread-resolved-count`);
              return {ok: !!c && c.textContent === '5 תגובות', seen: c && c.textContent}; }""",
             "המונה בשורת 'נפתר' עלה ל-5", nid)
        doc = _wait_doc(db, tid, lambda d: d["comment_count"] == 5, "התשובה בלי פתיחה נשמרה")
        assert doc["status"] == "resolved" and doc["resolved_by"]["kind"] == "user"
        assert _bodies(doc)[-1] == text and doc["last_author_kind"] == "user"
        assert tp.panel(nid)["state"] == "resolved" and tp.bubbles(nid)["slots"][0]["text"] == "✓"

        # 4. תשובה שפותחת — הפעולה הראשית של המצב, ב-Ctrl+Enter
        tp.panel_input(nid).fill("עוד שאלה")
        tp.panel_input(nid).press("Control+Enter")
        tp.wait_panel(nid, "open", 6)
        doc = _wait_doc(db, tid, lambda d: d["comment_count"] == 6, "התשובה שפותחת נשמרה")
        assert (doc["status"], doc["resolved_by"], doc["resolved_at"]) == ("open", None, None)
        assert tp.bubbles(nid)["slots"][0]["text"] == "6"

        # 5. "✓ נפתר" בלי טקסט: אין תגובה חדשה, ומי שכתב אחרון לא זז
        tp.panel_button(nid, "✓ נפתר").click()
        tp.wait_panel(nid, "resolved", 0)
        doc = _wait_doc(db, tid, lambda d: d["status"] == "resolved", "נסגר בלי סיכום")
        assert doc["comment_count"] == 6 and doc["last_author_kind"] == "user"

        # 6. "פתיחה מחדש" — בשורה המקופלת
        tp.note(nid).locator(".sticky-thread-resolved-row").click()
        panel = tp.wait_panel(nid, "resolved", 6)
        assert panel["resolvedExpanded"] == "true" and panel["reopen"] == {"disabled": False}
        tp.panel_button(nid, "פתיחה מחדש").click()
        tp.wait_panel(nid, "open", 6)
        doc = _wait_doc(db, tid, lambda d: d["status"] == "open", "נפתח מחדש")
        assert doc["resolved_by"] is None and doc["comment_count"] == 6

        # נקרא שוב מהמסד, דרך העמוד: הבועה והתגובות — כפי שנשמרו, בסדר שנשמרו
        tp.goto(f"/boards/{board}")
        assert tp.wait_bubbles(nid, 1)["slots"][0]["text"] == "6"
        tp.bubble(nid, tid).click()
        panel = tp.wait_panel(nid, "open", 6)
        assert [c["body"] for c in panel["comments"]] == _bodies(_doc(db, tid))
        assert [c["author"] for c in panel["comments"]] == [ME, "CC", ME, ME, ME, ME]
        _assert_clean(tp)


def test_failures_keep_the_text_and_say_what_happened(wired_mongo, admin_live_server, chromium_executable):
    """כשל רשת, שרשור שנסגר בינתיים (409 אמיתי מהשרת), וסוכן שענה בינתיים — הטקסט נשאר, ההודעה
    בעברית, הכפתורים משתחררים, והמוצג תואם למסד. והמונה סופר נקודות קוד, כמו השרת."""
    db = wired_mongo.get_db()
    coll = db[nt.NOTE_THREADS_COLLECTION]
    with threads_page(admin_live_server, chromium_executable, db) as tp:
        board = _board(tp)
        nid = _board_note(tp, board, x=200, y=260, w=420, h=260)
        tid = _thread(db, nid, (USER, "שאלה", 40), (CC, "תשובה", 30))
        other = _thread(db, nid, (USER, "שרשור שני", 20))
        tp.goto(f"/boards/{board}")
        tp.wait_bubbles(nid, 2)
        tp.bubble(nid, tid).click()
        tp.wait_panel(nid, "open", 2)

        # כשל רשת: ההודעה, הטקסט נשאר, הכפתורים משתחררים — ושום דבר לא נכתב
        pattern = f"**/api/sticky-notes/note/{nid}/threads/{tid}/comments"
        tp.page.route(pattern, lambda route: route.abort())
        tp.panel_input(nid).fill("טקסט שלא יאבד")
        tp.panel_button(nid, "שליחה").click()
        poll(tp.page, """(nid) => { const e = document.querySelector(`.sticky-note[data-note-id="${nid}"]
              [data-testid="thread-error"]`); return !!e && !e.hidden && !!e.textContent; }""", "הודעת שגיאה", nid)
        panel = tp.panel(nid)
        assert panel["error"] == "השליחה לא הגיעה לשרת — הטקסט נשאר בתיבה, נסו שוב."
        assert panel["input"]["value"] == "טקסט שלא יאבד" and not panel["busy"] and not panel["input"]["readOnly"]
        assert panel["buttons"] == [["✓ נפתר", False], ["שליחה", False]]
        assert _doc(db, tid)["comment_count"] == 2
        tp.page.unroute(pattern)
        tp.panel_button(nid, "שליחה").click()                     # ניסיון חוזר — עובר
        panel = tp.wait_panel(nid, "open", 3)
        assert panel["error"] == "" and _bodies(_doc(db, tid))[-1] == "טקסט שלא יאבד"

        # השרשור נסגר בינתיים (סוכן סגר דרך ה-MCP): השרת עונה 409, ההודעה נשארת, והחלונית
        # נטענת מחדש למצב שבמסד — נפתר.
        res = nt.resolve_thread(coll, user_id=USER_ID, note_id=nid, thread_id=tid, author=CC)
        assert res["ok"], res
        tp.panel_input(nid).fill("סיכום שאיחר")
        tp.panel_button(nid, "✓ נפתר").click()
        panel = tp.wait_panel(nid, "resolved", 0)
        assert panel["error"] == "השרשור כבר נסגר בינתיים."
        assert panel["resolvedLabel"].startswith("נפתר ע״י CC")
        assert panel["input"]["value"] == "סיכום שאיחר"
        assert _doc(db, tid)["comment_count"] == 3                # הסיכום לא נכתב

        # סוכן ענה בינתיים: אחרי השליחה מוצגות גם התגובה שלו וגם שלי — מהמסד
        tp.bubble(nid, other).click()
        tp.wait_panel(nid, "open", 1)
        res = nt.add_comment(coll, user_id=USER_ID, note_id=nid, thread_id=other, author=CLAUDE, body="ענה בינתיים")
        assert res["ok"], res
        tp.panel_input(nid).fill("התשובה שלי")
        tp.panel_button(nid, "שליחה").click()
        panel = tp.wait_panel(nid, "open", 3)
        assert [c["body"] for c in panel["comments"]] == ["שרשור שני", "ענה בינתיים", "התשובה שלי"]
        assert [c["body"] for c in panel["comments"]] == _bodies(_doc(db, other))

        # המונה סופר נקודות קוד (``[...s].length``), כמו השרת: אימוג'י אחד הוא תו אחד
        tp.panel_input(nid).fill("😀" * 3)
        assert tp.panel(nid)["counter"]["text"] == f"3 / {COMMENT_CAP:,}"
        tp.panel_input(nid).fill("😀" * (COMMENT_CAP + 1))
        panel = tp.panel(nid)
        assert panel["counter"]["text"] == f"{COMMENT_CAP + 1:,} / {COMMENT_CAP:,}" and panel["counter"]["over"]
        assert panel["counter"]["color"] == "rgb(185, 28, 28)"
        assert panel["buttons"] == [["✓ נפתר", True], ["שליחה", True]]
        # בדיוק בתקרה — עובר, והשרת מסכים: 4,000 אימוג'י הם 4,000 תווים גם שם
        tp.panel_input(nid).fill("😀" * COMMENT_CAP)
        assert tp.panel(nid)["buttons"] == [["✓ נפתר", False], ["שליחה", False]]
        tp.panel_button(nid, "שליחה").click()
        tp.wait_panel(nid, "open", 4)
        assert _bodies(_doc(db, other))[-1] == "😀" * COMMENT_CAP
        _assert_clean(tp)


def test_a_stuck_request_releases_the_panel_at_its_own_deadline(
        wired_mongo, admin_live_server, chromium_executable):
    """בקשה שאינה חוזרת לעולם אינה משאירה את החלונית נעולה: יש לה תקרה משלה
    (``THREAD_FETCH_TIMEOUT_MS``, 15 שניות), ואחריה ההודעה, הטקסט נשאר, והכפתורים משתחררים
    (``bugbot-rules/wait-without-own-deadline.md``)."""
    db = wired_mongo.get_db()
    with threads_page(admin_live_server, chromium_executable, db) as tp:
        board = _board(tp)
        nid = _board_note(tp, board, x=200, y=260, w=420, h=260)
        tid = _thread(db, nid, (USER, "שאלה", 40))
        tp.goto(f"/boards/{board}")
        tp.wait_bubbles(nid, 1)
        tp.bubble(nid, tid).click()
        tp.wait_panel(nid, "open", 1)
        held = []
        # הראוט לא עונה לעולם — לא ``fulfill``, לא ``continue_`` ולא ``abort``
        tp.page.route(f"**/api/sticky-notes/note/{nid}/threads/{tid}/comments", lambda route: held.append(route))
        tp.panel_input(nid).fill("נתקע")
        started = time.monotonic()
        tp.panel_button(nid, "שליחה").click()
        poll(tp.page, """(nid) => {
              const p = document.querySelector(`.sticky-note[data-note-id="${nid}"] > [data-testid="thread-panel"]`);
              return !!p && p.classList.contains('is-busy'); }""", "החלונית בשליחה", nid)
        assert tp.panel(nid)["input"]["readOnly"]
        deadline = time.monotonic() + 25
        while tp.panel(nid)["busy"]:
            assert time.monotonic() < deadline, "החלונית נשארה נעולה אחרי התקרה"
            time.sleep(0.25)
        waited = time.monotonic() - started
        assert held, "הבקשה לא הגיעה לראוט שעצר אותה"
        assert 14 <= waited <= 20, waited
        panel = tp.panel(nid)
        assert panel["error"] == "השליחה לא הגיעה לשרת — הטקסט נשאר בתיבה, נסו שוב."
        assert panel["input"]["value"] == "נתקע" and not panel["input"]["readOnly"]
        assert panel["buttons"] == [["✓ נפתר", False], ["שליחה", False]]
        assert _doc(db, tid)["comment_count"] == 1
        _assert_clean(tp)


def test_top_edge_moves_the_bubbles_below_and_opens_the_panel_upwards(
        wired_mongo, admin_live_server, chromium_executable):
    """מצב 10: פתק בפחות מ-44px מהקצה העליון — הבועות בתחתית, הפוכות, והחלונית נפתחת כלפי מעלה
    (bottom 10px, ולכל היותר גובה הפתק פחות 20), עם תיבת כתיבה מצומצמת. וההכרעה מתעדכנת גם
    כשהלוח נגלל."""
    db = wired_mongo.get_db()
    with threads_page(admin_live_server, chromium_executable, db) as tp:
        board = _board(tp)
        # y=1 ולא 0: ``_as_note_response`` מחזיר ``position_y or 100``, כלומר פתק שנשמר ב-0 חוזר
        # ב-100 (באג קיים, מדווח בנפרד). 1px מהקצה — עדיין "פחות מ-44px מהקצה העליון".
        top = _board_note(tp, board, x=200, y=1, w=420, h=260)
        lower = _board_note(tp, board, x=760, y=320, w=300, h=200)
        _board_note(tp, board, x=80, y=1800, w=200, h=200)       # מאריך את הלוח, כדי שאפשר לגלול
        t1 = _thread(db, top, (USER, "איפה נשמרת ההעדפה של רשת הנקודות?", 60),
                     (CLAUDE, "ב-board.settings.grid, לכל לוח בנפרד.", 40))
        _thread(db, top, (USER, "א", 30), (CC, "ב", 20))
        _thread(db, lower, (USER, "א", 30))
        tp.goto(f"/boards/{board}")
        row = tp.wait_bubbles(top, 2)
        pad = row["pad"]
        assert "is-threads-below" in row["cls"], row["cls"]
        for s in row["slots"]:
            # הפוך: נקודה על קו הפתק התחתון, מקל, ואז הבועה
            assert _near((s["anchor"]["top"] + s["anchor"]["bottom"]) / 2, pad["bottom"])
            assert _near(s["stick"]["top"], s["anchor"]["bottom"]) and _near(s["rect"]["top"], s["stick"]["bottom"])
            cx = _center_x(s["rect"])
            for y in (pad["bottom"] + 0.5, pad["bottom"] + ZONE - 0.5):
                assert tp.hit(cx, y) == s["id"], (s["id"], y)
        assert "is-threads-below" not in tp.bubbles(lower)["cls"]

        tp.bubble(top, t1).click()
        panel = tp.wait_panel(top, "open", 2)
        bubble = tp.bubbles(top)["slots"][0]
        assert _near(panel["rect"]["bottom"], pad["bottom"] - PANEL_TOP)
        assert _near(panel["rect"]["right"], pad["right"] - PANEL_SIDE)
        assert panel["rect"]["height"] <= (pad["bottom"] - pad["top"]) - 20 + 0.5
        assert _near((panel["arrow"]["top"] + panel["arrow"]["bottom"]) / 2, panel["rect"]["bottom"], 1)
        assert _near(_center_x(panel["arrow"]), _center_x(bubble["rect"]), 1)
        assert [c["time"] for c in panel["comments"]] == ["לפני שעה", "לפני 40 דק׳"]
        # תיבה מצומצמת: שדה של 36px ו"✓ נפתר" לצידו, באותה שורה — בלי מונה ובלי "שליחה"
        assert _near(panel["input"]["height"], 36) and not panel["counter"]["shown"]
        assert panel["buttons"] == [["✓ נפתר", False]]
        field, actions = panel["inputRect"], panel["actionsRect"]
        assert actions["top"] >= field["top"] - 1 and actions["bottom"] <= field["bottom"] + 1, (field, actions)
        # בפוקוס — התיבה המלאה: השדה, ומתחתיו המונה והכפתורים
        tp.panel_input(top).click()
        panel = tp.panel(top)
        assert panel["input"]["height"] >= 64 and panel["counter"]["shown"]
        assert panel["buttons"] == [["✓ נפתר", False], ["שליחה", True]]
        assert panel["actionsRect"]["top"] >= panel["inputRect"]["bottom"], (panel["inputRect"], panel["actionsRect"])

        # גלילה בגלגלת מביאה את הפתק השני 20px מראש המסך — והבועות שלו עוברות למטה. (בעמוד
        # הלוח ה-``body`` הוא שנגלל; המשטח גדל לגובה הפתקים. הגלגלת מגיעה למי שנגלל בפועל.)
        spot = poll(tp.page, EMPTY_POINT_JS, "נקודה ריקה בלוח")
        tp.page.mouse.move(spot["x"], spot["y"])
        tp.page.mouse.wheel(0, tp.bubbles(lower)["note"]["top"] - 20)
        poll(tp.page, "(nid) => document.querySelector(`.sticky-note[data-note-id=\"${nid}\"]`)"
                      "?.classList.contains('is-threads-below')", "הבועות של הפתק שנגלל עברו למטה", lower)
        _assert_clean(tp)


def test_search_and_minimize_take_the_bubbles_away(wired_mongo, admin_live_server, chromium_executable):
    """החיפוש בפתק יושב באותו מקום מעל הפתק — בזמנו הבועות מוסתרות והחלונית נסגרת. פתק ממוזער:
    אין בועות, 💬 מושבת עם הסבר. ובחזרה — הכול חוזר."""
    db = wired_mongo.get_db()
    with threads_page(admin_live_server, chromium_executable, db) as tp:
        board = _board(tp)
        nid = _board_note(tp, board, x=200, y=260, w=420, h=260, content="- [ ] משימה\n- [ ] עוד משימה")
        tid = _thread(db, nid, (USER, "שאלה", 40))
        _thread(db, nid, (USER, "שאלה", 30))
        tp.goto(f"/boards/{board}")
        tp.wait_bubbles(nid, 2)
        tp.bubble(nid, tid).click()
        tp.wait_panel(nid, "open", 1)

        # **החלונית מכסה את כותרת הפתק** — היא נפתחת 10px מתחת לראשו (העיצוב) — ולכן עכבר אינו
        # מגיע לכפתורים שבה. המקלדת כן: זה המסלול שבו החיפוש נפתח מעל חלונית פתוחה.
        tp.note(nid).locator(".sticky-note-search-btn").focus()
        tp.page.keyboard.press("Enter")
        poll(tp.page, "(nid) => document.querySelector(`.sticky-note[data-note-id=\"${nid}\"]`)"
                      "?.classList.contains('is-searching')", "החיפוש נפתח", nid)
        row = tp.bubbles(nid)
        assert tp.panel(nid) == {"open": False} and not row["rowShown"]
        tp.page.keyboard.press("Escape")
        poll(tp.page, "(nid) => !document.querySelector(`.sticky-note[data-note-id=\"${nid}\"]`)"
                      "?.classList.contains('is-searching')", "החיפוש נסגר", nid)
        row = tp.bubbles(nid)
        assert row["rowShown"] and "is-unclipped" in row["cls"]      # הבועות עדיין מחוץ לפתק

        tp.bubble(nid, tid).click()
        tp.wait_panel(nid, "open", 1)
        threads_btn = tp.note(nid).locator(".sticky-note-threads-btn")
        tp.note(nid).get_by_title("מזער").focus()                 # מכוסה בחלונית — כמו החיפוש
        tp.page.keyboard.press("Enter")
        poll(tp.page, "(nid) => document.querySelector(`.sticky-note[data-note-id=\"${nid}\"]`)"
                      "?.classList.contains('is-minimized')", "הפתק מוזער", nid)
        assert tp.panel(nid) == {"open": False} and not tp.bubbles(nid)["slots"]
        assert threads_btn.is_disabled()
        assert threads_btn.get_attribute("title") == "הפתק ממוזער — פתחו אותו כדי לנהל שרשורים"
        tp.note(nid).get_by_title("מזער").click()
        assert len(tp.wait_bubbles(nid, 2)["slots"]) == 2 and not threads_btn.is_disabled()
        _assert_clean(tp)


def test_nothing_the_note_clipped_leaks_out_once_it_has_bubbles(
        wired_mongo, admin_live_server, chromium_executable):
    """פתק עם בועות אינו חותך (``.is-unclipped``) — ומה שהחיתוך הסתיר נחתך עכשיו על ידי הילדים.

    פתק צר, כך ששורת הכפתורים (עם 💬) גולשת מהכותרת, ותוכן ארוך עם פס גלילה גלוי. משווים לפני
    ואחרי שיש בועות: כל מה שמחוץ לפתק בצדדים ומתחת, והפינות מחוץ לקשת — למעלה ולמטה. מעל הפתק
    יושבות הבועות, ולכן הפס שמעליו אינו בהשוואה.
    """
    from PIL import Image, ImageChops  # מוצמד ב-requirements/base.txt

    db = wired_mongo.get_db()
    tasks = "\n".join(f"- [ ] משימה ארוכה {i}" for i in range(30))
    with threads_page(admin_live_server, chromium_executable, db, viewport={"width": 700, "height": 700},
                      scrollbars=True) as tp:
        board = _board(tp)
        nid = _board_note(tp, board, x=260, y=200, w=140, h=220, content=tasks)
        tp.goto(f"/boards/{board}")
        tp.page.wait_for_selector(NOTE_SEL.format(nid))
        tp.settle()
        overflow = tp.page.evaluate("(nid) => { const a = document.querySelector(`.sticky-note[data-note-id=\"${nid}\"]"
                                    " .sticky-note-actions`);"
                                    " return a.scrollWidth > a.parentElement.clientWidth; }", nid)
        assert overflow, "שורת הכפתורים אמורה לגלוש מהכותרת בפתק הצר"
        r = tp.bubbles(nid)["note"]
        radius = tp.page.evaluate("(nid) => parseFloat(getComputedStyle(document.querySelector("
                                  "`.sticky-note[data-note-id=\"${nid}\"]`)).borderTopLeftRadius)", nid)
        clip = {"x": r["left"] - 50, "y": r["top"], "width": r["width"] + 100, "height": r["height"] + 20}

        def shot():
            return Image.open(io.BytesIO(tp.page.screenshot(clip=clip))).convert("RGB")

        before = shot()
        _thread(db, nid, (USER, "שאלה", 10))
        tp.goto(f"/boards/{board}")
        row = tp.wait_bubbles(nid, 1)
        assert "is-unclipped" in row["cls"]
        assert row["note"] == r, (row["note"], r)
        after = shot()
    diff = ImageChops.difference(before, after)
    pixels = diff.load()
    # בפיקסלי CSS, יחסית לחיתוך: הפתק מתחיל 50px מימין לקצה השמאלי שלו ובראש החיתוך.
    nx0, nx1, ny1 = 50, 50 + r["width"], r["height"]
    leaks = []
    for py in range(diff.height):
        for px in range(diff.width):
            if sum(pixels[px, py]) <= 12:
                continue
            x, y = (px + 0.5) / DPR, (py + 0.5) / DPR        # מרכז הפיקסל, בפיקסלי CSS
            outside = not (nx0 <= x < nx1 and y < ny1)
            corner_y = radius if y < radius else (ny1 - radius if y >= ny1 - radius else None)
            corner = False
            if corner_y is not None and (x < nx0 + radius or x >= nx1 - radius):
                cx = nx0 + radius if x < nx0 + radius else nx1 - radius
                corner = ((x - cx) ** 2 + (y - corner_y) ** 2) ** 0.5 > radius + 0.5
            if outside or corner:
                leaks.append((round(x, 1), round(y, 1)))
    assert leaks == [], f"{len(leaks)} פיקסלים השתנו מחוץ לפתק, למשל {leaks[:10]}"


#: הפוקוס על החלונית: האם היא האלמנט הפעיל, ואיזו טבעת מצוירת סביבה.
PANEL_FOCUS_JS = """(nid) => {
  const p = document.querySelector(`.sticky-note[data-note-id="${nid}"] > [data-testid="thread-panel"]`);
  if (!p) return null;
  const cs = getComputedStyle(p);
  return {active: document.activeElement === p, visible: p.matches(':focus-visible'),
          style: cs.outlineStyle, color: cs.outlineColor, width: cs.outlineWidth};
}"""


def test_the_panel_shows_keyboard_focus_but_not_mouse_focus(wired_mongo, admin_live_server, chromium_executable):
    """החלונית מקבלת את הפוקוס כשהיא נפתחת. **במקלדת היא מסמנת אותו** — כמו כל כפתור בה — ובעכבר
    לא: פוקוס מסקריפט אחרי לחיצה אינו ``:focus-visible``. עד התיקון ``outline: none`` הסתיר אותו
    גם ממי שפתח את השרשור ב-Enter."""
    db = wired_mongo.get_db()
    with threads_page(admin_live_server, chromium_executable, db) as tp:
        board = _board(tp)
        nid = _board_note(tp, board, x=200, y=260, w=420, h=260)
        tid = _thread(db, nid, (USER, "שאלה", 40))
        tp.goto(f"/boards/{board}")
        tp.wait_bubbles(nid, 1)

        tp.bubble(nid, tid).click()
        tp.wait_panel(nid, "open", 1)
        mouse = tp.page.evaluate(PANEL_FOCUS_JS, nid)
        assert mouse["active"] and not mouse["visible"] and mouse["style"] == "none", mouse

        tp.page.keyboard.press("Escape")                   # סוגר, והפוקוס חוזר לבועה
        poll(tp.page, "([nid, tid]) => document.activeElement === document.querySelector("
                      "`.sticky-note[data-note-id=\"${nid}\"] .sticky-threads [data-thread-id=\"${tid}\"]`)",
             "הפוקוס חזר לבועה", [nid, tid])
        tp.page.keyboard.press("Enter")
        tp.wait_panel(nid, "open", 1)
        keyboard = tp.page.evaluate(PANEL_FOCUS_JS, nid)
        assert keyboard["active"] and keyboard["visible"], keyboard
        ring = (keyboard["style"], keyboard["color"], keyboard["width"])
        assert ring == ("solid", "rgb(29, 78, 216)", "2px"), keyboard
        _assert_clean(tp)


@pytest.mark.parametrize("theme", ["dark", "rose-pine-dawn", "high-contrast"])
def test_the_panel_in_other_themes(theme, wired_mongo, admin_live_server, chromium_executable):
    """החלונית היא חלק מ"נייר" הפתק: בערכה כהה וב-Rose Pine Dawn היא נשארת כמו בעיצוב, וכללי
    הערכה על ``textarea`` אינם נוגעים בתיבה. בניגודיות גבוהה היא מצטרפת לערכה — שחור ולבן."""
    db = wired_mongo.get_db()
    db.users.update_one({"user_id": USER_ID}, {"$set": {"ui_prefs.theme": theme}}, upsert=True)
    with threads_page(admin_live_server, chromium_executable, db) as tp:
        board = _board(tp)
        nid = _board_note(tp, board, x=200, y=260, w=420, h=260)
        tid = _thread(db, nid, (USER, "שאלה", 40), (CC, "תשובה", 30))
        tp.goto(f"/boards/{board}")
        assert tp.page.evaluate("() => document.documentElement.getAttribute('data-theme')") == theme
        row = tp.wait_bubbles(nid, 1)
        tp.bubble(nid, tid).click()
        tp.panel_input(nid).click()
        panel = tp.wait_panel(nid, "open", 2)
        if theme == "high-contrast":
            assert (panel["bg"], panel["color"]) == ("rgb(0, 0, 0)", "rgb(255, 255, 255)")
            assert panel["border"] == "solid 2px rgb(255, 255, 255)"
            assert {c["bg"] for c in panel["comments"]} == {"rgb(0, 0, 0)"}
            assert panel["counter"]["color"] == "rgb(255, 255, 255)"
            # הערכה כופה ``!important`` על כל ``button`` ו-``textarea`` — והבועה היא הכפתור עצמו,
            # ולכן היא בועה שחורה עם גבול לבן (ולא קופסה של 44×44), והשדה מצטרף לערכה.
            bubble = row["slots"][0]
            assert (bubble["bg"], bubble["color"], bubble["border"]) == (
                "rgb(0, 0, 0)", "rgb(255, 255, 255)", "solid 2px rgb(255, 255, 255)")
            assert _near(bubble["rect"]["width"], PILL_W) and _near(bubble["rect"]["height"], PILL_H)
            assert (panel["input"]["bg"], panel["input"]["color"]) == ("rgb(0, 0, 0)", "rgb(255, 255, 255)")
        else:
            assert (panel["bg"], panel["color"]) == (PAPER, INK)
            assert (panel["input"]["bg"], panel["input"]["color"]) == ("rgb(255, 255, 255)", INK)
            # הפוקוס של העיצוב — גבול כהה וטבעת — ולא של הערכה: בלי מתאר, ובלי צבע הגבול שלה.
            # (העובי לא נבדק: כרומיום מעגל עובי גבול, ו-1.5px נמדד כאן 1px.)
            assert panel["input"]["focused"] and panel["input"]["outline"] == "none", panel["input"]
            border = panel["input"]["border"]
            assert border.startswith("solid ") and border.endswith("rgb(43, 63, 106)"), border
            assert panel["input"]["shadow"] == "rgba(43, 63, 106, 0.12) 0px 0px 0px 3px"
            assert [c["bg"] for c in panel["comments"]] == [AUTHOR_BG["user"], AUTHOR_BG["cc"]]
            assert row["slots"][0]["bg"] == TONES[0]
            assert row["slots"][0]["waiting"]["borderColor"] == row["surfaceBg"]
        _assert_clean(tp)


#: ניגודיות של טקסט מול הרקע שהוא יושב עליו, לפי WCAG — הצבעים מומרים ל-sRGB דרך canvas
#: (גם ``oklch``), ורקע שקוף-למחצה מורכב מעל הרקע שמתחתיו.
CONTRAST_JS = """(nid) => {
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = 1;
  const ctx = canvas.getContext('2d', {willReadFrequently: true});
  const rgba = (color) => {
    ctx.clearRect(0, 0, 1, 1); ctx.fillStyle = '#000'; ctx.fillStyle = color; ctx.fillRect(0, 0, 1, 1);
    const d = ctx.getImageData(0, 0, 1, 1).data; return [d[0], d[1], d[2], d[3] / 255];
  };
  const over = (top, under) => top.slice(0, 3).map((c, i) => c * top[3] + under[i] * (1 - top[3]));
  const lum = (rgb) => { const f = (c) => { c /= 255; return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4; };
                         return 0.2126 * f(rgb[0]) + 0.7152 * f(rgb[1]) + 0.0722 * f(rgb[2]); };
  const ratio = (a, b) => { const x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };
  // הרקע האפקטיבי: עולים באבות עד רקע אטום, ומרכיבים בדרך את מה שקוף-למחצה.
  const background = (el) => {
    const layers = [];
    for (let e = el; e; e = e.parentElement) {
      const c = rgba(getComputedStyle(e).backgroundColor);
      if (c[3] > 0) layers.push(c);
      if (c[3] >= 1) break;
    }
    let base = [255, 255, 255];
    for (const layer of layers.reverse()) base = over(layer, base);
    return base;
  };
  const note = document.querySelector(`.sticky-note[data-note-id="${nid}"]`);
  const out = [];
  const check = (what, el, color) => {
    if (!el) return;
    const fg = over(rgba(color || getComputedStyle(el).color), background(el));
    out.push([what, Math.round(ratio(fg, background(el)) * 100) / 100]);
  };
  const p = note.querySelector(':scope > [data-testid="thread-panel"]');
  if (p) {
    for (const sel of ['.sticky-thread-title', '.sticky-thread-meta', '.sticky-thread-counter', '.sticky-thread-hint',
                       '.sticky-thread-resolved-label', '.sticky-thread-resolved-count', '.sticky-thread-status']) {
      check(sel, p.querySelector(sel));
    }
    for (const c of p.querySelectorAll('.sticky-thread-comment')) {
      const tone = c.dataset.authorTone;
      for (const sel of ['.sticky-thread-author', '.sticky-thread-working-on', '.sticky-thread-time',
                         '.sticky-thread-comment-body']) {
        check(`${tone} ${sel}`, c.querySelector(sel));
      }
    }
    const input = p.querySelector('.sticky-thread-input');
    if (!input.value) check('placeholder', input, getComputedStyle(input, '::placeholder').color);
  }
  const menu = note.querySelector(':scope > .sticky-thread-menu');
  if (menu) {
    for (const m of menu.querySelectorAll('.sticky-thread-menu-name, .sticky-thread-menu-meta')) check(m.className, m);
  }
  return out;
}"""


def test_text_in_the_panel_is_readable(wired_mongo, admin_live_server, chromium_executable):
    """כל טקסט בחלונית וברשימה עומד ב-4.5:1 מול הרקע שהוא יושב עליו (WCAG 1.4.3) — גם על כרטיס
    התגובה הצבעוני של כל כותב. **כאן העמוד סוטה מהעיצוב בכוונה:** הזמן, המונה, "N תגובות"
    וה-placeholder נמדדו בעיצוב 3.0–4.2 (ראו ההערה בראש סעיף השרשורים ב-``sticky-notes.css``)."""
    db = wired_mongo.get_db()
    with threads_page(admin_live_server, chromium_executable, db) as tp:
        board = _board(tp)
        nid = _board_note(tp, board, x=400, y=240, w=260, h=230)
        t1 = _thread(db, nid, (USER, "שאלה", 30), (CC, "תשובה", 29), (CLAUDE, "סקירה", 28), (GEMINI, "נגישות", 27),
                     (CURSOR, "עוד", 26), (NAMELESS, "ועוד", 25))
        t2 = _thread(db, nid, (USER, "א", 24), resolved_by=(CC, 23))
        for k in range(4):                                    # שישה שרשורים בפתק של 260 — שניים ב-"+N"
            _thread(db, nid, (USER, f"שרשור {k + 3}", 20 - k))
        tp.goto(f"/boards/{board}")
        tp.wait_bubbles(nid, 5)
        measured = []
        tp.bubble(nid, t1).click()
        tp.wait_panel(nid, "open", 6)
        measured += tp.page.evaluate(CONTRAST_JS, nid)
        tp.bubble(nid, t2).click()
        tp.wait_panel(nid, "resolved", 0)
        measured += tp.page.evaluate(CONTRAST_JS, nid)
        tp.panel_button(nid, "סגירת השרשור").click()
        tp.bubble(nid, "more").click()
        tp.page.wait_for_selector(".sticky-thread-menu")
        measured += tp.page.evaluate(CONTRAST_JS, nid)
    names = {name for name, _ in measured}
    for expected in ("placeholder", ".sticky-thread-counter", ".sticky-thread-resolved-count",
                     "user .sticky-thread-time", "agent .sticky-thread-time", "sticky-thread-menu-meta"):
        assert expected in names, (expected, sorted(names))
    low = [(name, value) for name, value in measured if value < 4.5]
    assert low == [], f"טקסט מתחת ל-4.5:1: {low}"


# --- קדמת הערימה ----------------------------------------------------------------------


def test_a_new_note_opens_above_a_note_with_an_open_thread(wired_mongo, admin_live_server, chromium_executable):
    """פתיחת שרשור מעלה את הפתק שלו לקדמת הערימה (``_openThread``), ופתק שנוצר אחרי זה נפתח
    **מעליו**: הוא הפתק האחרון שנוצר. לפני התיקון ``createNote`` לא העלה את הפתק החדש — הוא נכנס
    אחרון ל-DOM, וזה מספיק רק מול פתקים שלא הועלו — ולכן נפתח מתחת לפתק שהשרשור שלו פתוח.

    "מעליו" נמדד במה שהדפדפן מוצא באמצע החפיפה (``top_note_in_overlap``), ולא ב-``z-index``.
    החלונית נשארת פתוחה בכוונה, כי זה התרחיש. היא ילד של A, ולכן כשהיא מה שמצויר באמצע החפיפה,
    ``top_note_in_overlap`` מחזיר את A — וזה בדיוק מה שנמדד לפני התיקון."""
    db = wired_mongo.get_db()
    with threads_page(admin_live_server, chromium_executable, db) as tp:
        board = _board(tp)
        # פתק חדש נולד במרחק קבוע מהפינה הנראית של הלוח (``_newNotePosition``). A יושב כך שהחדש,
        # בגודל של פתק חדש במסך רחב, יחפוף אותו — והבקרה שבתוך ``top_note_in_overlap`` מוודאת.
        a = _board_note(tp, board, x=300, y=260, w=420, h=260, content="פתק A")
        tid = _thread(db, a, (USER, "שאלה", 10), (CC, "תשובה", 5))
        tp.goto(f"/boards/{board}")
        tp.wait_bubbles(a, 1)
        tp.bubble(a, tid).click()
        tp.wait_panel(a, "open", 2)
        tp.page.locator(".sticky-note-fab").click()
        b = poll(tp.page, """(a) => {
              const ids = [...document.querySelectorAll('.sticky-note')].map((n) => n.dataset.noteId);
              const fresh = ids.filter((id) => id !== a);
              return fresh.length === 1 ? {ok: true, id: fresh[0]} : {ok: false, ids};
            }""", "הפתק החדש נוצר", a)["id"]
        tp.settle()

        assert tp.panel(a)["open"], "בקרה: החלונית של A נסגרה, והתרחיש כבר אינו של שרשור פתוח"
        res = top_note_in_overlap(tp.page, a, b)
        assert res["top"] == b, f"הפתק החדש נפתח מתחת ל-A: {res}"
        _assert_clean(tp)


# --- קישור ישיר ושלושת המשטחים ------------------------------------------------------------


def test_a_link_to_a_thread_opens_it_once(wired_mongo, admin_live_server, chromium_executable):
    """``/note/<id>?thread=<id>`` (הקישור שבהתראה) פותח את השרשור — פעם אחת. שרשור של פתק אחר
    נענה בשרת ב-404, והחלונית אומרת שהוא לא קיים; ופרמטר פגום נזרק בקישור הקבוע."""
    db = wired_mongo.get_db()
    with threads_page(admin_live_server, chromium_executable, db) as tp:
        board = _board(tp)
        nid = _board_note(tp, board, x=200, y=260, w=420, h=260)
        far = _board_note(tp, board, x=760, y=260, w=300, h=200)
        _thread(db, nid, (USER, "ראשון", 40))
        t2 = _thread(db, nid, (USER, "שני", 30), (CC, "תשובה", 20))
        foreign = _thread(db, far, (USER, "של פתק אחר", 30))

        tp.goto(f"/note/{nid}?thread={t2}")
        assert urlsplit(tp.page.url).path == f"/boards/{board}"
        panel = tp.wait_panel(nid, "open", 2)
        assert panel["title"] == "שרשור 2"
        tp.goto(f"/boards/{board}")                              # בלי הפרמטר — אין חלונית
        tp.wait_bubbles(nid, 2)
        time.sleep(0.5)
        assert tp.panel(nid) == {"open": False}

        tp.goto(f"/note/{nid}?thread={foreign}")
        panel = tp.wait_panel(nid, "error")
        assert panel["status"] == "השרשור הזה כבר לא קיים." and not panel["composer"]

        tp.goto(f"/note/{nid}?thread=../../x")
        assert "thread" not in tp.page.url
        tp.wait_bubbles(nid, 2)
        time.sleep(0.5)
        assert tp.panel(nid) == {"open": False}
        _assert_clean(tp)


def test_threads_that_did_not_load_are_retried_from_the_button(
        wired_mongo, admin_live_server, chromium_executable):
    """רשימת פתקים שחזרה בלי תקצירים (``threads_unavailable``) אינה "אין שרשורים": 💬 אומר
    שהם לא נטענו, ולחיצה עליו קוראת שוב. והקאש המקומי אינו שומר תקצירים בכלל."""
    db = wired_mongo.get_db()
    with threads_page(admin_live_server, chromium_executable, db) as tp:
        board = _board(tp)
        nid = _board_note(tp, board, x=200, y=260, w=420, h=260)
        _thread(db, nid, (USER, "שאלה", 40), (CC, "תשובה", 30))

        def without_summaries(route):
            # התשובה האמיתית מהשרת, ושדה אחד שונה — כמו כשהשאילתה של התקצירים נכשלה בשרת
            response = route.fetch()
            data = response.json()
            for note in data.get("notes", []):
                note.pop("threads", None)
            data["threads_unavailable"] = True
            # בלי ``content-length`` המקורי: הגוף החדש באורך אחר, ואורך ישן היה חותך אותו.
            headers = {k: v for k, v in response.headers.items() if k.lower() != "content-length"}
            route.fulfill(status=response.status, headers=headers, body=json.dumps(data))

        # ביטוי רגולרי ולא glob: רשימת הפתקים נטענת עם ``?_=<זמן>``, ובכתובת יש ``?``.
        tp.page.route(re.compile(rf"/api/sticky-notes/board/{board}(\?|$)"), without_summaries)
        tp.goto(f"/boards/{board}")
        threads_btn = tp.note(nid).locator(".sticky-note-threads-btn")
        poll(tp.page, "(nid) => document.querySelector(`.sticky-note[data-note-id=\"${nid}\"]"
                      " .sticky-note-threads-btn`)?.classList.contains('is-unavailable')", "💬 מסומן 'לא נטענו'", nid)
        assert threads_btn.get_attribute("title") == "השרשורים לא נטענו — לחיצה תנסה שוב"
        assert tp.bubbles(nid)["slots"] == []
        threads_btn.click()
        assert tp.wait_bubbles(nid, 1)["slots"][0]["text"] == "2"
        assert "is-unavailable" not in threads_btn.get_attribute("class")
        assert threads_btn.get_attribute("title") == "שרשור חדש"
        assert tp.panel(nid) == {"open": False}                  # הניסיון החוזר אינו פותח שרשור חדש

        cached = tp.page.evaluate("(key) => localStorage.getItem(key)", f"sticky-notes:board:{board}")
        assert cached and '"threads"' not in cached, cached
        _assert_clean(tp)


def test_a_narrow_screen_shrinks_the_panel_before_moving_it(wired_mongo, admin_live_server, chromium_executable):
    """H7: כשהמסך צר מהחלונית ומהשוליים, החלונית מתכווצת קודם — ורק אז זזה אל תוך המסך."""
    db = wired_mongo.get_db()
    screen = {"width": 300, "height": 700}
    with threads_page(admin_live_server, chromium_executable, db, viewport=screen) as tp:
        board = _board(tp)
        nid = _board_note(tp, board, x=10, y=200, w=260, h=200)
        tid = _thread(db, nid, (USER, "שאלה", 40))
        tp.goto(f"/boards/{board}")
        tp.wait_bubbles(nid, 1)
        tp.bubble(nid, tid).click()
        panel = tp.wait_panel(nid, "open", 1)
        room = screen["width"] - 2 * SCREEN_GAP
        assert room < PANEL_NARROW_W
        assert _near(panel["rect"]["width"], room, 1), panel["rect"]
        assert panel["rect"]["left"] >= SCREEN_GAP - 1 and panel["rect"]["right"] <= screen["width"] - SCREEN_GAP + 1
        bubble = tp.bubbles(nid)["slots"][0]
        assert panel["rect"]["left"] + 10 <= _center_x(panel["arrow"]) <= panel["rect"]["right"] - 10
        assert _near(_center_x(panel["arrow"]), _center_x(bubble["rect"]), 1)
        _assert_clean(tp)


def _md_file(db, name="threads.md"):
    oid = ObjectId()
    db.code_snippets.insert_one({
        "_id": oid, "user_id": USER_ID, "file_name": name, "code": "# כותרת\n\nפסקה ראשונה.\n",
        "programming_language": "markdown", "version": 1, "is_active": True,
    })
    return str(oid)


def test_markdown_file_surface(wired_mongo, admin_live_server, chromium_executable):
    """תצוגת Markdown של קובץ: אותן בועות, ותשובה שנשמרת — וגם הקישור הישיר לשרשור."""
    db = wired_mongo.get_db()
    with threads_page(admin_live_server, chromium_executable, db) as tp:
        fid = _md_file(db)
        nid = tp.api("POST", f"/api/sticky-notes/{fid}",
                     {"content": "פתק על קובץ", "position": {"x": 300, "y": 260},
                      "size": {"width": 260, "height": 200}})["id"]
        tid = _thread(db, nid, (USER, "שאלה על הקובץ", 40), (CC, "תשובה", 30))
        tp.goto(f"/md/{fid}")
        row = tp.wait_bubbles(nid, 1)
        bubble = row["slots"][0]
        assert (bubble["text"], bubble["bg"]) == ("2", TONES[0]) and bubble["waiting"] is not None
        assert _near(bubble["rect"]["width"], PILL_W) and _near(bubble["rect"]["right"], row["pad"]["right"] - EDGE)
        assert _near((bubble["anchor"]["top"] + bubble["anchor"]["bottom"]) / 2, row["pad"]["top"])
        tp.bubble(nid, tid).click()
        tp.wait_panel(nid, "open", 2)
        tp.panel_input(nid).fill("תשובה מה-Markdown")
        tp.panel_button(nid, "שליחה").click()
        tp.wait_panel(nid, "open", 3)
        assert _bodies(_wait_doc(db, tid, lambda d: d["comment_count"] == 3, "נשמר"))[-1] == "תשובה מה-Markdown"

        tp.goto(f"/note/{nid}?thread={tid}")
        assert urlsplit(tp.page.url).path == f"/md/{fid}"
        assert tp.wait_panel(nid, "open", 3)["title"] == "שרשור 1"
        _assert_clean(tp)


REPO = "CodeBot"
REPO_PATH = "docs/threads.md"


def _repo_api(route):
    """ה-API של דפדפן הריפו מזויף, כמו ב-``tests/test_repo_notes_browser.py`` — וכל השאר, כולל
    הפתקים והשרשורים, עובר לשרת האמיתי."""
    url = urlsplit(route.request.url)
    if url.hostname != "127.0.0.1":
        route.abort()
        return
    path = unquote(url.path)
    body = None
    if path == f"/repo/api/file/{REPO_PATH}":
        body = {"content": "# מסמך\n\n" + "\n".join(f"שורה {i}" for i in range(40)),
                "language": "markdown", "path": REPO_PATH}
    elif path == "/repo/api/tree":
        body = [{"name": REPO_PATH.rsplit("/", 1)[-1], "path": REPO_PATH, "type": "file"}]
    elif path == "/repo/api/repos":
        body = {"success": True, "repos": [{"repo_name": REPO}], "current": REPO, "current_source": "default"}
    elif path.startswith("/repo/api/"):
        body = {"success": True, "types": []}
    if body is None:
        route.continue_()
    else:
        route.fulfill(status=200, content_type="application/json", body=json.dumps(body))


def test_repo_browser_surface(wired_mongo, admin_live_server, chromium_executable):
    """דפדפן הריפו: אותן בועות ותשובה שנשמרת. והקישור הישיר מהתראה פותח את השרשור ויורד
    מהכתובת יחד עם ``repo`` ו-``note`` (``consumeOneShotUrlParams``), כשה-hash נשאר."""
    db = wired_mongo.get_db()
    # הריפו ממורר והקובץ בעץ — מה שיצירת פתק ריפו דורשת (``mirrored_repo_names``,
    # ``repo_file_exists``).
    db.repo_metadata.insert_one({"repo_name": REPO})
    db.repo_files.insert_one({"repo_name": REPO, "path": REPO_PATH})
    with threads_page(admin_live_server, chromium_executable, db, route=_repo_api,
                      local_storage={f"repo-notes:{REPO}:{REPO_PATH}": "1"}) as tp:
        nid = tp.api("POST", f"/api/sticky-notes/repo/{REPO}/{REPO_PATH}",
                     {"content": "פתק על קובץ בריפו", "position": {"x": 300, "y": 200},
                      "size": {"width": 260, "height": 200}})["id"]
        tid = _thread(db, nid, (USER, "שאלה על הריפו", 40), (CC, "תשובה", 30))
        tp.goto(f"/repo/#file={REPO_PATH}")
        poll(tp.page, "() => !!(window.repoNotes && window.repoNotes.hasManager())", "מנהל הפתקים הורכב")
        row = tp.wait_bubbles(nid, 1)
        bubble = row["slots"][0]
        assert (bubble["text"], bubble["bg"]) == ("2", TONES[0]) and _near(bubble["rect"]["height"], PILL_H)
        tp.bubble(nid, tid).click()
        tp.wait_panel(nid, "open", 2)
        tp.panel_input(nid).fill("תשובה מדפדפן הריפו")
        tp.panel_button(nid, "שליחה").click()
        tp.wait_panel(nid, "open", 3)
        assert _bodies(_wait_doc(db, tid, lambda d: d["comment_count"] == 3, "נשמר"))[-1] == "תשובה מדפדפן הריפו"

        tp.goto(f"/note/{nid}?thread={tid}")
        assert tp.wait_panel(nid, "open", 3)["title"] == "שרשור 1"
        url = urlsplit(tp.page.url)
        assert url.path == "/repo/" and url.query == "", tp.page.url
        assert unquote(url.fragment) == f"file={REPO_PATH}"
        _assert_clean(tp)
