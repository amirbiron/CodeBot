"""קצב הדגימה של בועת התזכורות — נמדד בדפדפן אמיתי.

**למה זו חייבת להיות בדיקת דפדפן.** ההשהיה שהסקריפט מבקש מגיעה ל-
``setTimeout``, וזו פונקציה של הדפדפן עם התנהגות שאינה בחתימה: הארגומנט
מומר ל-int32 חתום, ולכן כל ערך מעל 2,147,483,647 מילישניות (כ-24.8 ימים)
**גולש**. תזכורת שנקבעה לעוד חודשיים מייצרת בדיוק ערך כזה, והתוצאה היא
טיימר שנורה בזמן שרירותי — או מיד. מקור: MDN, ``Window.setTimeout``, סעיף
"Maximum delay value".

בדיקת יחידה על חישוב ההשהיה הייתה עוברת בשמחה על הערך הגולש, כי בפייתון
אין גבול כזה. רק הדפדפן אוכף אותו.

**ריצת הבקרה.** ``test_removing_the_clamp_breaks_the_long_delay`` מריץ את
אותו סקריפט בלי ה-clamp ודורש שהערך **כן** יחרוג. בלי זה, שינוי עתידי היה
יכול להפוך את הבדיקה לחסרת משמעות בשקט — היא הייתה ממשיכה לעבור בלי לבדוק
כלום.

הסקריפט נחלץ מ-``base.html`` עצמו ולא מועתק לכאן, כדי שהבדיקה תיפול כשהוא
משתנה. מדולג בשקט כשאין Chromium; ``chromium_executable`` מגיע מ-
``tests/conftest.py``.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path

import pytest

pytest.importorskip("playwright", reason="playwright אינו מותקן")

from playwright.sync_api import sync_playwright  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
BASE_TEMPLATE = REPO_ROOT / "webapp" / "templates" / "base.html"

#: הגבול שמעליו ``setTimeout`` גולש. ראו את הדוקסטרינג למעלה.
INT32_MAX_MS = 2147483647

MIN_POLL_MS = 60 * 1000
MAX_POLL_MS = 30 * 60 * 1000

#: ה-DOM המינימלי שהסקריפט מחפש כדי לתלות עליו את הבועה.
PAGE = """<!doctype html><html lang="he"><head><meta charset="utf-8"></head><body>
  <a class="nav-link" href="/settings">הגדרות</a>
  <button class="mobile-menu-toggle">תפריט</button>
</body></html>"""

#: מחליף את ``fetch`` ואת ``setTimeout`` לפני שהסקריפט רץ, כדי לקרוא את
#: ההשהיה שהוא באמת ביקש. ה-``setTimeout`` האמיתי נקרא עם שעה, כדי שהטיימר
#: לא יירה בזמן הבדיקה ויציף את הרשימה.
HARNESS = """
window.__delays = [];
const _st = window.setTimeout;
window.setTimeout = function(fn, ms){ window.__delays.push(ms); return _st(fn, 3600000); };
window.fetch = async function(){
  const status = window.__status || 200;
  return { ok: status < 400, status, headers: { get: () => null }, json: async () => window.__reply };
};
"""


def _polling_script() -> str:
    """הסקריפט האמיתי מתוך ``base.html``, לא העתק שלו."""
    src = BASE_TEMPLATE.read_text(encoding="utf-8")
    marker = "(function initStickyRemindersIndicator(){"
    start = src.index(marker)
    end = src.index("})();", start) + len("})();")
    script = src[start:end]
    assert "{%" not in script and "{{" not in script, "תחביר Jinja דלף לתוך בלוק ה-JS"
    return script


def _summary(**overrides):
    reply = {
        "ok": True,
        "has_due": False,
        "count_due": 0,
        "next": None,
        "next_in_seconds": None,
    }
    reply.update(overrides)
    return reply


def _requested_delay(chromium_executable, reply, script, status: int = 200) -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=chromium_executable)
        try:
            page = browser.new_page()
            page.set_content(PAGE)
            page.evaluate(HARNESS)
            page.evaluate(f"window.__reply = {json.dumps(reply)};")
            page.evaluate(f"window.__status = {int(status)};")
            page.evaluate(script)
            page.wait_for_function("window.__delays.length > 0", timeout=5000)
            return page.evaluate("window.__delays")[-1]
        finally:
            browser.close()


@pytest.mark.parametrize(
    "name,reply,expected",
    [
        ("אין תזכורות כלל", _summary(), MAX_POLL_MS),
        ("התזכורת הבאה בעוד שתי דקות", _summary(next_in_seconds=120), 120 * 1000),
        ("קרובה מדי — נתפסת ברצפה", _summary(next_in_seconds=10), MIN_POLL_MS),
        ("רחוקה מדי — נתפסת בתקרה", _summary(next_in_seconds=5_184_000), MAX_POLL_MS),
        (
            "יש תזכורת בשלה",
            _summary(has_due=True, count_due=3, next={"note_id": "n1", "file_id": "f1", "remind_at": None}),
            MAX_POLL_MS,
        ),
    ],
)
def test_client_schedules_from_the_server_answer(chromium_executable, name, reply, expected):
    """הלקוח דוגם לפי מה שהשרת אמר, ובתוך גבולות בטוחים."""
    delay = _requested_delay(chromium_executable, reply, _polling_script())
    assert delay == expected, f"{name}: ביקש {delay}, ציפינו ל-{expected}"
    assert delay <= INT32_MAX_MS, f"{name}: {delay} חורג מגבול ה-int32 של setTimeout"


def test_a_server_error_retries_soon_rather_than_sleeping(chromium_executable):
    """500 אינו "אין תזכורות" — הלקוח חוזר לרצפה, לא לתקרה.

    כשל בצד השרת הוא "לא ידוע". לקוח שנרדם לחצי שעה על תקלה חולפת מאריך
    אותה בדיוק בחצי שעה מבחינת המשתמש.
    """
    delay = _requested_delay(chromium_executable, _summary(), _polling_script(), status=500)
    assert delay == MIN_POLL_MS, f"אחרי 500 ביקש {delay} במקום {MIN_POLL_MS}"


def test_removing_the_clamp_breaks_the_long_delay(chromium_executable):
    """ריצת בקרה: בלי ה-clamp, תזכורת רחוקה חורגת מגבול ה-int32.

    זה מה שהופך את הבדיקה שמעליה לראיה ולא לירוק. אם המוטציה הזו מפסיקה
    לחרוג, הבדיקה כבר אינה מודדת את מה שהיא מתיימרת למדוד.
    """
    script = _polling_script()
    clamped = "const delay = Math.min(MAX_POLL_MS, Math.max(MIN_POLL_MS, safe));"
    assert script.count(clamped) == 1, "ה-clamp לא נמצא בסקריפט — הבדיקה אינה תקפה יותר"
    mutated = script.replace(clamped, "const delay = safe;")

    delay = _requested_delay(chromium_executable, _summary(next_in_seconds=5_184_000), mutated)
    assert delay > INT32_MAX_MS, (
        "המוטציה לא ייצרה חריגה — כלומר הבדיקה למעלה אינה מסוגלת לתפוס את הבאג"
    )


# ---------------------------------------------------------------------------
# שרשרת הדגימה במצבי כשל — ההסלמה, 401, timeout, חפיפה, והחלונית.
#
# ה-harness כאן שונה מזה שלמעלה: ה-``setTimeout`` המדומה **מפעיל** את
# ``fireFirst`` הטיימרים הראשונים אחרי ההשהיה האמיתית שביקשו, כדי שהשרשרת
# תתקדם ונמדוד רצף, ואז חונה. ``fetch`` המדומה יודע להיכשל בכל הצורות
# שהקוד מבחין ביניהן, ומכבד ``opts.signal`` — כי ``AbortSignal.timeout`` הוא
# של הדפדפן, ו-``page.clock`` של Playwright אינו מזייף אותו (מתועד: הוא מכסה
# Date/setTimeout/rAF/performance בלבד). לכן טסט ה-stall ממתין זמן אמיתי.
# ---------------------------------------------------------------------------

CHAIN_HARNESS = """
window.__delays = [];
window.__calls = [];
window.__fired = 0;
window.__abortReason = null;
const _st = window.setTimeout;
window.setTimeout = function(fn, ms){
  window.__delays.push(ms);
  if (window.__fired < (window.__fireFirst || 0)) { window.__fired++; return _st(fn, ms); }
  return _st(fn, 3600000);
};
window.fetch = async function(url, opts){
  const u = String(url);
  const isList = u.indexOf('/reminders/list') !== -1;
  window.__calls.push({ url: u, hasSignal: !!(opts && opts.signal), t: Date.now() });
  const mode = isList ? (window.__listMode || 'status') : (window.__mode || 'status');
  if (mode === 'reject') { throw new TypeError('Failed to fetch'); }
  if (mode === 'stall') {
    return new Promise((resolve, reject) => {
      if (opts && opts.signal) {
        opts.signal.addEventListener('abort', () => {
          window.__abortReason = opts.signal.reason && opts.signal.reason.name;
          reject(opts.signal.reason);
        });
      }
    });
  }
  let status;
  if (isList) { status = window.__listStatus || 200; }
  else if (Array.isArray(window.__statuses)) {
    const i = window.__statusIdx || 0; window.__statusIdx = i + 1;
    status = window.__statuses[Math.min(i, window.__statuses.length - 1)];
  } else { status = window.__status || 200; }
  const body = isList ? (window.__listReply || null) : (window.__reply || null);
  return {
    ok: status < 400, status,
    headers: { get: () => null },
    json: async () => { if (mode === 'bad_json') { throw new SyntaxError('Unexpected token'); } return body; }
  };
};
Object.defineProperty(document, 'visibilityState', { get: () => 'visible', configurable: true });
"""

#: עמוד שכבר יש בו בועה, כדי ש"הבועה הוסרה" יהיה טענה ולא תיאור של כלום.
PAGE_WITH_BUBBLE = PAGE.replace(
    '<a class="nav-link" href="/settings">הגדרות</a>',
    '<a class="nav-link" href="/settings">הגדרות<span class="notif-bubble" data-kind="reminder">1</span></a>',
)

#: השורות שהמוטציות תופסות. כולן חייבות להופיע פעם אחת בדיוק בסקריפט.
MIN_LINE = "const MIN_POLL_MS = 60 * 1000;"
MAX_LINE = "const MAX_POLL_MS = 30 * 60 * 1000;"
ESCALATION = "MIN_POLL_MS * 2 ** (consecutiveFailures - 1)"
RESET_ON_SUCCESS = "consecutiveFailures = 0;\n      if (!j.has_due) {"
STOP_ON_401 = "if (r.status === 401) { removeDot(); return POLL_STOP; }"
SIGNAL_LINE = "o.signal = AbortSignal.timeout(FETCH_TIMEOUT_MS);"
INFLIGHT_GUARD = "if (inFlight) { return; }"
STAMP_THEN_FETCH = (
    "lastPollAt = Date.now();\n"
    "      const r = await fetch('/api/sticky-notes/reminders/summary', fetchOpts());"
)
CATCH_BACKS_OFF = "} catch(_) { return failAndBackOff(); }"
POPOVER_UNKNOWN = "openPopover(target, (lj && lj.ok) ? lj : { error: true });"


def _mutate(script: str, anchor: str, replacement: str) -> str:
    """החלפה על עותק בזיכרון, עם אימות שהעוגן נתפס ושמשהו באמת השתנה."""
    assert script.count(anchor) == 1, f"העוגן לא נמצא פעם אחת בדיוק: {anchor[:70]!r}"
    out = script.replace(anchor, replacement)
    assert out != script, "המוטציה לא שינתה כלום"
    return out


def _shrunk(script: str, min_ms: int, max_ms: int) -> str:
    """קבועים קטנים כדי שהשרשרת תתקדם בזמן אמיתי.

    אי אפשר להמתין חצי שעה בטסט. הצורה — כפול בכל כשל עד תקרה — היא מה
    שנמדד כאן; הערכים 60000 ו-1800000 עצמם נבדקים בטסטי הרצפה והתקרה שלמעלה.
    """
    s = _mutate(script, MIN_LINE, f"const MIN_POLL_MS = {min_ms};")
    return _mutate(s, MAX_LINE, f"const MAX_POLL_MS = {max_ms};")


def _summary(**overrides):
    return _summary_reply(**overrides)


def _summary_reply(**overrides):
    reply = {"ok": True, "has_due": False, "count_due": 0, "next": None, "next_in_seconds": None}
    reply.update(overrides)
    return reply


@contextmanager
def _chain(chromium_executable, script: str, *, seed_bubble: bool = False, **window_vars):
    """מרים דפדפן, מזריק את ה-harness ואת המשתנים, ומריץ את הסקריפט."""
    with sync_playwright() as p:
        browser = (
            p.chromium.launch(executable_path=chromium_executable) if chromium_executable else p.chromium.launch()
        )
        try:
            page = browser.new_page()
            page.set_content(PAGE_WITH_BUBBLE if seed_bubble else PAGE)
            page.evaluate(CHAIN_HARNESS)
            page.evaluate(f"Object.assign(window, {json.dumps(window_vars)});")
            page.evaluate(script)
            yield page
        finally:
            browser.close()


def _delays(page):
    return page.evaluate("window.__delays")


def _calls(page):
    return page.evaluate("window.__calls")


def _focus(page):
    page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")


# --- הסלמה ואיפוס -----------------------------------------------------------

def test_server_errors_escalate_toward_the_ceiling(chromium_executable):
    """500 אחרי 500: ההמתנה מכפילה את עצמה עד התקרה, ולא נשארת ברצפה.

    לפני התיקון כל כשל החזיר את הרצפה — 60 שניות, לנצח — כלומר 1440 בקשות
    ביממה לטאב מול 288 של ה-``setInterval`` שהוחלף, ודווקא כשהשרת נופל.
    """
    script = _shrunk(_polling_script(), 1, 40)
    with _chain(chromium_executable, script, __status=500, __fireFirst=7) as page:
        page.wait_for_function("window.__delays.length >= 8", timeout=8000)
        assert _delays(page) == [1, 2, 4, 8, 16, 32, 40, 40], _delays(page)
        # בקרת שפיות: כל מחזור באמת שלח בקשה — ה-backoff לא קיצר את הדרך.
        assert len(_calls(page)) == 8, len(_calls(page))


def test_a_success_resets_the_escalation(chromium_executable):
    """תשובה תקינה אחרי כשלים מאפסת את המונה — הכשל הבא מתחיל מהרצפה.

    בלי האיפוס, מצב הדיכוי מהתקלה הקודמת מרעיל את החלון הבא: כשל בודד
    שבועיים אחרי outage היה נענש כאילו הוא החמישי ברצף.
    """
    script = _shrunk(_polling_script(), 1, 40)
    statuses = [500, 500, 200, 500]
    with _chain(chromium_executable, script, __statuses=statuses, __reply=_summary(), __fireFirst=3) as page:
        page.wait_for_function("window.__delays.length >= 4", timeout=8000)
        assert _delays(page) == [1, 2, 40, 1], _delays(page)


def test_flattening_the_escalation_breaks_the_test(chromium_executable):
    """ריצת בקרה: בלי הכפלה — הרצף שטוח, והטסט למעלה חייב ליפול."""
    script = _mutate(_shrunk(_polling_script(), 1, 40), ESCALATION, "MIN_POLL_MS * 1")
    with _chain(chromium_executable, script, __status=500, __fireFirst=7) as page:
        page.wait_for_function("window.__delays.length >= 8", timeout=8000)
        assert _delays(page) == [1] * 8, _delays(page)


def test_dropping_the_reset_breaks_the_test(chromium_executable):
    """ריצת בקרה: בלי איפוס — הכשל שאחרי ההצלחה ממשיך את ההסלמה."""
    script = _mutate(_shrunk(_polling_script(), 1, 40), RESET_ON_SUCCESS, "if (!j.has_due) {")
    statuses = [500, 500, 200, 500]
    with _chain(chromium_executable, script, __statuses=statuses, __reply=_summary(), __fireFirst=3) as page:
        page.wait_for_function("window.__delays.length >= 4", timeout=8000)
        assert _delays(page) == [1, 2, 40, 4], _delays(page)


# --- 401 ---------------------------------------------------------------------

def test_401_stops_the_chain_and_removes_the_badge(chromium_executable):
    """הסשן נגמר: אין טיימר, והבועה יורדת. לא "עוד ניסיון בעוד דקה".

    ``require_auth`` עונה 401 לפני מגביל הקצב, ולכן טאב שנשאר פתוח אחרי
    התנתקות היה שולח בקשה בכל דקה עד שייסגר, ושום דבר לא בלם אותו.
    """
    with _chain(chromium_executable, _polling_script(), seed_bubble=True, __status=401) as page:
        page.wait_for_function("window.__calls.length >= 1", timeout=8000)
        page.wait_for_timeout(300)
        assert _delays(page) == [], _delays(page)
        assert page.evaluate("document.querySelector('.notif-bubble[data-kind=\"reminder\"]')") is None


def test_after_401_the_next_attempt_is_the_next_focus(chromium_executable):
    """"מתי הניסיון הבא כן יוצא": בחזרה ללשונית, פעם אחת, ועדיין בלי טיימר.

    כך התחברות בלשונית אחרת מחיה את הבועה בלי רענון, ובלי התחברות זו
    בקשה אחת לכל פוקוס ולא אחת לדקה. הרצפה מאופסת כאן כי אי אפשר להמתין
    דקה בטסט; מה שנמדד הוא שהפוקוס עצמו מנסה שוב ושהתוצאה שוב עוצרת.
    """
    script = _mutate(_polling_script(), MIN_LINE, "const MIN_POLL_MS = 0;")
    with _chain(chromium_executable, script, __status=401) as page:
        page.wait_for_function("window.__calls.length >= 1", timeout=8000)
        page.wait_for_timeout(200)
        _focus(page)
        page.wait_for_function("window.__calls.length >= 2", timeout=8000)
        page.wait_for_timeout(200)
        assert len(_calls(page)) == 2, len(_calls(page))
        assert _delays(page) == [], _delays(page)


def test_dropping_the_401_branch_breaks_the_test(chromium_executable):
    """ריצת בקרה: בלי הענף — 401 מסלים כמו כל כשל ודורך טיימר."""
    script = _mutate(_polling_script(), STOP_ON_401, "")
    with _chain(chromium_executable, script, seed_bubble=True, __status=401) as page:
        page.wait_for_function("window.__delays.length >= 1", timeout=8000)
        assert _delays(page) == [MIN_POLL_MS], _delays(page)


# --- timeout על בקשה תקועה ------------------------------------------------------

def test_a_stalled_request_times_out_and_the_chain_survives(chromium_executable):
    """בקשה שלא נפתרת לעולם נחתכת אחרי FETCH_TIMEOUT_MS, ונדרך טיימר.

    לפני התיקון: אפס טיימרים — השרשרת מתה עד רענון. השרת לא יכול להציל:
    worker של gevent אינו מודד אורך בקשה, ובחיבור half-open שום חבילה לא
    מגיעה ללקוח. ממתין 15 שניות אמיתיות, כי ``AbortSignal.timeout`` הוא של
    הדפדפן ולא ניתן לזיוף. הדחייה חייבת להיות ``TimeoutError`` — נמדד
    ב-Chromium 141 מול MDN.
    """
    with _chain(chromium_executable, _polling_script(), __mode="stall") as page:
        page.wait_for_function("window.__delays.length >= 1", timeout=25000)
        assert _calls(page)[0]["hasSignal"] is True
        assert page.evaluate("window.__abortReason") == "TimeoutError"
        assert _delays(page) == [MIN_POLL_MS], _delays(page)


def test_dropping_the_signal_breaks_the_test(chromium_executable):
    """ריצת בקרה: בלי סיגנל — הבקשה תלויה, ואין טיימר גם אחרי הזמן."""
    script = _mutate(_polling_script(), SIGNAL_LINE, "")
    with _chain(chromium_executable, script, __mode="stall") as page:
        page.wait_for_timeout(18000)
        assert _calls(page)[0]["hasSignal"] is False
        assert _delays(page) == [], _delays(page)


# --- חפיפה ורצפה ---------------------------------------------------------------

def test_a_focus_during_an_inflight_poll_does_not_start_a_second_one(chromium_executable):
    """בקשה באוויר + visibilitychange = עדיין בקשה אחת.

    בלי הגארד, התשובה שהגיעה אחרונה ניצחה: "אין תזכורות" ישן דרס "יש"
    טרי. הרצפה מאופסת כדי לבודד את הגארד — הרצפה נבדקת בטסט שאחריו.
    """
    script = _mutate(_polling_script(), MIN_LINE, "const MIN_POLL_MS = 0;")
    with _chain(chromium_executable, script, __mode="stall") as page:
        page.wait_for_function("window.__calls.length >= 1", timeout=8000)
        _focus(page)
        page.wait_for_timeout(300)
        assert len(_calls(page)) == 1, len(_calls(page))


def test_dropping_the_inflight_guard_breaks_the_test(chromium_executable):
    """ריצת בקרה: בלי הגארד — הפוקוס שולח בקשה שנייה במקביל."""
    script = _mutate(_mutate(_polling_script(), MIN_LINE, "const MIN_POLL_MS = 0;"), INFLIGHT_GUARD, "")
    with _chain(chromium_executable, script, __mode="stall") as page:
        page.wait_for_function("window.__calls.length >= 1", timeout=8000)
        _focus(page)
        page.wait_for_function("window.__calls.length >= 2", timeout=8000)
        assert len(_calls(page)) == 2, len(_calls(page))


def test_the_floor_holds_when_the_request_fails(chromium_executable):
    """רשת מנותקת + מעברים בין אפליקציות = בקשה אחת וטיימר אחד, לא שישה.

    שתי שכבות. החותמת נכתבת לפני הבקשה, ולכן הרצפה נמדדת מתחילת הניסיון
    גם כשהוא נכשל — ה-visibilitychange נעצר בכניסה ואינו נוגע בטיימר. ומתחתיה
    שער ה-backoff: גם מי שעובר את הרצפה לא שולח בקשה בזמן ההמתנה. בקוד הישן
    לא הייתה אף שכבה — כשל השאיר את החותמת ב-0, וכל אירוע שלח בקשה: נמדד,
    5 אירועים ו-5 בקשות נוספות.
    """
    with _chain(chromium_executable, _polling_script(), __mode="reject") as page:
        page.wait_for_function("window.__delays.length >= 1", timeout=8000)
        for _ in range(5):
            _focus(page)
        page.wait_for_timeout(300)
        assert len(_calls(page)) == 1, len(_calls(page))
        assert _delays(page) == [MIN_POLL_MS], _delays(page)


def test_stamping_after_the_await_breaks_the_test(chromium_executable):
    """ריצת בקרה: החותמת אחרי ה-await — הרצפה לא מחזיקה, וכל פוקוס דורך טיימר.

    הבקשה עצמה עדיין נחסמת, כי שער ה-backoff הוא שכבה נפרדת. מה שהמוטציה
    חושפת הוא בדיוק מה שהחותמת מונעת: חמש כניסות ל-poll() וחמישה re-arm.
    """
    script = _mutate(
        _polling_script(), STAMP_THEN_FETCH,
        "const r = await fetch('/api/sticky-notes/reminders/summary', fetchOpts());\n      lastPollAt = Date.now();",
    )
    with _chain(chromium_executable, script, __mode="reject") as page:
        page.wait_for_function("window.__delays.length >= 1", timeout=8000)
        for _ in range(5):
            _focus(page)
        page.wait_for_function("window.__delays.length >= 6", timeout=8000)
        assert len(_calls(page)) == 1, len(_calls(page))
        assert len(_delays(page)) == 6, _delays(page)


# --- שגיאת רשת ו-JSON פגום — לא חצי שעה ----------------------------------------

@pytest.mark.parametrize("mode", ["reject", "bad_json"])
def test_a_network_or_parse_error_retries_soon_not_in_half_an_hour(chromium_executable, mode):
    """"לא הצלחתי לברר" אינו "אין מה לתזמן". לפני התיקון: 30 דקות שקט."""
    with _chain(chromium_executable, _polling_script(), __mode=mode, __status=200, __reply=_summary()) as page:
        page.wait_for_function("window.__delays.length >= 1", timeout=8000)
        assert _delays(page) == [MIN_POLL_MS], _delays(page)


def test_a_catch_that_returns_the_ceiling_breaks_the_test(chromium_executable):
    """ריצת בקרה: ה-catch הישן — התקרה, לא הרצפה."""
    script = _mutate(_polling_script(), CATCH_BACKS_OFF, "} catch(_) { removeDot(); return MAX_POLL_MS; }")
    with _chain(chromium_executable, script, __mode="reject") as page:
        page.wait_for_function("window.__delays.length >= 1", timeout=8000)
        assert _delays(page) == [MAX_POLL_MS], _delays(page)


# --- החלונית: "לא ידוע" אינו "אין" ----------------------------------------------

_DUE = dict(has_due=True, count_due=2, next={"note_id": "n1", "file_id": "f1", "remind_at": None})


def _click_bubble_and_read_popover(page):
    bubble = "'.notif-bubble[data-kind=\"reminder\"]'"
    assert page.evaluate(f"!!document.querySelector({bubble})"), "בקרת שפיות: אין בועה ללחוץ עליה"
    page.click(".notif-bubble[data-kind='reminder']")
    page.wait_for_selector(".notif-popover[data-kind='reminder']", timeout=8000)
    return page.evaluate("""() => ({
      title: (document.querySelector('.notif-popover__title') || {}).textContent || '',
      links: document.querySelectorAll('.notif-popover a.reminder-link').length,
      snooze: !!document.querySelector('.notif-popover [data-action="snooze-ui"]'),
      close: !!document.querySelector('.notif-popover [data-action="close-ui"]'),
    })""")


def test_badge_click_says_unknown_when_the_list_cannot_be_read(chromium_executable):
    """הרשימה נכשלה: החלונית אומרת זאת, בלי פריטים ובלי "דחה", והבועה נשארת.

    ה-summary אמר שיש תזכורות — זו הסיבה שהבועה קיימת. 500 ברשימה הוא "לא
    ידוע", לא "אפס פתקים", ו"סגור" לא מבטל בועה שהיא נכונה.
    """
    due = _summary(**_DUE)
    with _chain(chromium_executable, _polling_script(), __status=200, __reply=due, __listStatus=500) as page:
        page.wait_for_function("!!document.querySelector('.notif-bubble[data-kind=\"reminder\"]')", timeout=8000)
        pop = _click_bubble_and_read_popover(page)
        assert "לא הצלחתי" in pop["title"], pop
        assert pop["links"] == 0 and pop["snooze"] is False and pop["close"] is True, pop
        page.click(".notif-popover [data-action='close-ui']")
        page.wait_for_timeout(200)
        assert page.evaluate("!!document.querySelector('.notif-popover[data-kind=\"reminder\"]')") is False
        bubble_left = page.evaluate("!!document.querySelector('.notif-bubble[data-kind=\"reminder\"]')")
        assert bubble_left is True, "סגור מחק בועה שהיא נכונה"


def test_falling_back_to_an_empty_list_breaks_the_test(chromium_executable):
    """ריצת בקרה: ההתנהגות הישנה — 500 מוצג כ"0 פתקים", עם כפתור דחייה."""
    old_fallback = "openPopover(target, (lj && lj.ok) ? lj : { items: [], count: 0 });"
    script = _mutate(_polling_script(), POPOVER_UNKNOWN, old_fallback)
    due = _summary(**_DUE)
    with _chain(chromium_executable, script, __status=200, __reply=due, __listStatus=500) as page:
        page.wait_for_function("!!document.querySelector('.notif-bubble[data-kind=\"reminder\"]')", timeout=8000)
        pop = _click_bubble_and_read_popover(page)
        assert "0 פתקים" in pop["title"] and pop["snooze"] is True, pop
