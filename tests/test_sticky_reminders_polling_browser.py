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


def _with_fetch_timeout(script: str, ms: int) -> str:
    """תקרת הבקשה מקוצרת בעותק.

    ``AbortSignal.timeout`` הוא של הדפדפן ואינו ניתן לזיוף ב-``page.clock`` —
    אבל הקבוע שמוזן לו ניתן לקיצור, וכך טסט שממתין לתקרה נמשך מילישניות ולא
    15 שניות.
    """
    return _mutate(script, FETCH_TIMEOUT_LINE, f"const FETCH_TIMEOUT_MS = {ms};")


def _summary(**overrides):
    reply = {
        "ok": True,
        "has_due": False,
        "count_due": 0,
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
# Date/setTimeout/rAF/performance בלבד). לכן הקבוע שמוזן לו מקוצר בעותק
# (``_with_fetch_timeout``), והערך האמיתי נאכף ב-``test_sticky_reminders_polling_source.py``
# — קובץ שאינו דפדפן, כי כאן כל בדיקה חייבת להגיע לשער ``chromium_executable``.
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
  const res = {
    ok: status < 400, status,
    headers: { get: () => null },
    json: async () => { if (mode === 'bad_json') { throw new SyntaxError('Unexpected token'); } return body; }
  };
  // 'hold': התשובה מוכנה אבל ממתינה עד ש-window.__release() נקרא — כדי למדוד
  // מה קורה לתשובה שמגיעה אחרי שהשרשרת כבר נעצרה.
  if (mode === 'hold') { return new Promise((resolve) => { window.__release = () => resolve(res); }); }
  return res;
};
Object.defineProperty(document, 'visibilityState', { get: () => 'visible', configurable: true });
"""

#: עמוד שכבר יש בו בועה, כדי ש"הבועה הוסרה" יהיה טענה ולא תיאור של כלום.
PAGE_WITH_BUBBLE = PAGE.replace(
    '<a class="nav-link" href="/settings">הגדרות</a>',
    '<a class="nav-link" href="/settings">הגדרות<span class="notif-bubble" data-kind="reminder">1</span></a>',
)
assert PAGE_WITH_BUBBLE != PAGE, "העוגן לזריעת הבועה לא נמצא ב-PAGE — 'הבועה הוסרה' היה עובר על עמוד ריק"

#: השורות שהמוטציות תופסות. כולן חייבות להופיע פעם אחת בדיוק בסקריפט.
MIN_LINE = "const MIN_POLL_MS = 60 * 1000;"
MAX_LINE = "const MAX_POLL_MS = 30 * 60 * 1000;"
ESCALATION = "MIN_POLL_MS * 2 ** (consecutiveFailures - 1)"
RESET_ON_SUCCESS = "consecutiveFailures = 0;\n      if (!j.has_due) {"
STOP_ON_401 = (
    "if (r.status === 401) { console.warn('[sticky-reminders] session ended (401); "
    "polling stops until the next tab focus'); removeDot(); return POLL_STOP; }"
)
SIGNAL_LINE = "o.signal = AbortSignal.timeout(FETCH_TIMEOUT_MS);"
INFLIGHT_GUARD = "if (inFlight) { return; }"
STAMP_THEN_FETCH = (
    "lastPollAt = Date.now();\n"
    "      const r = await fetch('/api/sticky-notes/reminders/summary', fetchOpts());"
)
CATCH_BACKS_OFF = "} catch (e) { if (gen !== chainGen) { return staleAfterStop(); } return failAndBackOff(e); }"
STOP_BUMPS_GEN = "    stopped = true;\n    chainGen += 1;"
KEEP_BADGE_ON_429 = (
    "        window.__stickyRemindersBackoffUntil = Date.now() + backoffMs;\n"
    "        return backoffMs;"
)
DUE_USES_SERVER_DELAY = (
    "      // ייראו תוך כדי, ולא אחרי חצי שעה. שרת ישן שלא שולח ערך ← התקרה.\n"
    "      return requestedDelay(j);"
)
POPOVER_UNKNOWN = "openPopover(target, (lj && lj.ok) ? lj : { error: true });"
FLOOR_SKIPS_WHEN_STOPPED = "if (!stopped && Date.now() - lastPollAt < MIN_POLL_MS) { return; }"
LOG_ON_FAILURE = (
    "    console.warn(`[sticky-reminders] poll failed (#${consecutiveFailures}) — "
    "retry in ${backoffMs} ms:`, reason);"
)
BACKOFF_RETURNS = LOG_ON_FAILURE + "\n    return backoffMs;"
FETCH_TIMEOUT_LINE = "const FETCH_TIMEOUT_MS = 15 * 1000;"
ABORT_FALLBACK = "} else if (typeof AbortController === 'function') {"
BAD_BODY_CHECK = "if (!j || !j.ok) { return failAndBackOff('bad body'); }"
LATEST_CLICK = "const gen = ++listGen;"
LIST_CATCH_REPORTS = (
    "          console.warn('[sticky-reminders] list fetch failed:', e);\n"
    "          openPopover(target, { error: true });"
)
NO_ABORT_TIMEOUT = "AbortSignal.timeout = undefined;"
STOP_CLEARS_TIMER = "    try { if (pollTimer) { clearTimeout(pollTimer); } } catch(_) {}\n    pollTimer = null;"
LIST_401_STOPS = (
    "if (lr.status === 401) { removeDot(); stopChain(); "
    "openPopover(target, { unauthorized: true }); return; }"
)


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


@contextmanager
def _chain(
    chromium_executable, script: str, *, seed_bubble: bool = False, setup_js: str = "",
    console_sink: list | None = None, **window_vars,
):
    """מרים דפדפן, מזריק את ה-harness ואת המשתנים, ומריץ את הסקריפט.

    ``setup_js`` רץ אחרי ה-harness ולפני הסקריפט (למשל מחיקת יכולת דפדפן), ו-``console_sink``
    אוסף את הודעות הקונסול כזוגות ``(type, text)`` — כולל אלה שנרשמות בזמן ההרצה הראשונה.
    """
    with sync_playwright() as p:
        browser = (
            p.chromium.launch(executable_path=chromium_executable) if chromium_executable else p.chromium.launch()
        )
        try:
            page = browser.new_page()
            if console_sink is not None:
                page.on("console", lambda m: console_sink.append((m.type, m.text)))
            page.set_content(PAGE_WITH_BUBBLE if seed_bubble else PAGE)
            page.evaluate(CHAIN_HARNESS)
            if setup_js:
                page.evaluate(setup_js)
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
    """"מתי הניסיון הבא כן יוצא": בחזרה ללשונית, מיד, ועדיין בלי טיימר.

    ברצפה האמיתית של דקה, בכוונה. הרצפה נועדה למעברים בין אפליקציות בזמן
    ששרשרת חיה; במצב עצור אין שרשרת, והפוקוס הוא המסלול היחיד חזרה — ולכן
    הוא מנסה גם שניות אחרי ה-401. כך התחברות בלשונית אחרת מחיה את הבועה
    בלי רענון. לפני התיקון פוקוס בתוך הדקה נבלע ברצפה, בעוד התיעוד ושתי
    הערות בקוד הבטיחו "פעם אחת בכל חזרה ללשונית".
    """
    with _chain(chromium_executable, _polling_script(), __status=401) as page:
        page.wait_for_function("window.__calls.length >= 1", timeout=8000)
        page.wait_for_timeout(300)
        _focus(page)
        page.wait_for_timeout(500)
        assert len(_calls(page)) == 2, len(_calls(page))
        assert _delays(page) == [], _delays(page)


def test_applying_the_floor_while_stopped_breaks_the_test(chromium_executable):
    """ריצת בקרה: הרצפה חלה גם במצב עצור — הפוקוס בתוך הדקה נבלע."""
    script = _mutate(
        _polling_script(), FLOOR_SKIPS_WHEN_STOPPED, "if (Date.now() - lastPollAt < MIN_POLL_MS) { return; }"
    )
    with _chain(chromium_executable, script, __status=401) as page:
        page.wait_for_function("window.__calls.length >= 1", timeout=8000)
        page.wait_for_timeout(300)
        _focus(page)
        page.wait_for_timeout(500)
        assert len(_calls(page)) == 1, len(_calls(page))


def test_the_inflight_guard_holds_while_the_floor_is_bypassed(chromium_executable):
    """במצב עצור הרצפה עקופה — אבל בקשה באוויר עדיין חוסמת פוקוס נוסף.

    401 עוצר; הפוקוס הבא שולח בקשה שנתקעת; שלושה פוקוסים נוספים בזמן שהיא
    באוויר אינם שולחים כלום. הגארד inFlight אינו תלוי ברצפה.
    """
    with _chain(chromium_executable, _polling_script(), __status=401) as page:
        page.wait_for_function("window.__calls.length >= 1", timeout=8000)
        page.wait_for_timeout(200)
        page.evaluate("window.__mode = 'stall'")
        _focus(page)
        page.wait_for_function("window.__calls.length >= 2", timeout=8000)
        for _ in range(3):
            _focus(page)
        page.wait_for_timeout(300)
        assert len(_calls(page)) == 2, len(_calls(page))


def test_dropping_the_inflight_guard_while_stopped_breaks_the_test(chromium_executable):
    """ריצת בקרה: בלי הגארד, במצב עצור כל פוקוס פותח עוד בקשה תקועה."""
    script = _mutate(_polling_script(), INFLIGHT_GUARD, "")
    with _chain(chromium_executable, script, __status=401) as page:
        page.wait_for_function("window.__calls.length >= 1", timeout=8000)
        page.wait_for_timeout(200)
        page.evaluate("window.__mode = 'stall'")
        _focus(page)
        page.wait_for_function("window.__calls.length >= 2", timeout=8000)
        for _ in range(3):
            _focus(page)
        page.wait_for_function("window.__calls.length >= 3", timeout=8000)
        assert len(_calls(page)) >= 3, len(_calls(page))


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
    מגיעה ללקוח. ``AbortSignal.timeout`` הוא של הדפדפן ולא ניתן לזיוף, ולכן
    התקרה מקוצרת בעותק ל-300 מ"ש. הדחייה חייבת להיות ``TimeoutError`` —
    נמדד ב-Chromium 141 מול MDN.
    """
    with _chain(chromium_executable, _with_fetch_timeout(_polling_script(), 300), __mode="stall") as page:
        page.wait_for_function("window.__delays.length >= 1", timeout=5000)
        assert _calls(page)[0]["hasSignal"] is True
        assert page.evaluate("window.__abortReason") == "TimeoutError"
        assert _delays(page) == [MIN_POLL_MS], _delays(page)


def test_dropping_the_signal_breaks_the_test(chromium_executable):
    """ריצת בקרה: בלי סיגנל — הבקשה תלויה, ואין טיימר גם אחרי הזמן."""
    script = _mutate(_with_fetch_timeout(_polling_script(), 300), SIGNAL_LINE, "")
    with _chain(chromium_executable, script, __mode="stall") as page:
        page.wait_for_timeout(2000)
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

_DUE = dict(has_due=True, count_due=2)


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


@pytest.mark.parametrize(
    "list_failure",
    [{"__listStatus": 500}, {"__listMode": "reject"}, {"__listMode": "bad_json"}],
    ids=["status-500", "network-error", "bad-json"],
)
def test_badge_click_says_unknown_when_the_list_cannot_be_read(chromium_executable, list_failure):
    """הרשימה נכשלה: החלונית אומרת זאת, בלי פריטים ובלי "דחה", והבועה נשארת.

    ה-summary אמר שיש תזכורות — זו הסיבה שהבועה קיימת. כשל ברשימה הוא "לא
    ידוע", לא "אפס פתקים", ו"סגור" לא מבטל בועה שהיא נכונה. 500, שגיאת רשת
    ו-JSON פגום עוברים בשלושה מסלולים שונים בקוד (lr.ok, ה-catch, lr.json),
    ולכן שלושתם נמדדים.
    """
    due = _summary(**_DUE)
    with _chain(chromium_executable, _polling_script(), __status=200, __reply=due, **list_failure) as page:
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


# --- הבועה כמצב אחרון ידוע, ועצירה שמבטלת את הטיימר --------------------------

def test_a_failed_poll_keeps_the_badge_it_cannot_refute(chromium_executable):
    """500 אחרי "יש תזכורות": הבועה נשארת — כשל אינו ראיה שהתזכורות נעלמו.

    לפני התיקון failAndBackOff מחקה את הבועה, ועם ה-backoff המעריכי היא
    נעלמה עד חצי שעה על תקלה חולפת; והחלונית "לא הצלחתי לבדוק" לא הייתה
    נגישה, כי מה שפותח אותה נמחק. רק 401 ו"אין תזכורות" מסירים בועה.
    """
    script = _shrunk(_polling_script(), 1, 40)
    with _chain(chromium_executable, script, __statuses=[200, 500], __reply=_summary(**_DUE), __fireFirst=1) as page:
        page.wait_for_function("window.__calls.length >= 2", timeout=8000)
        page.wait_for_timeout(100)
        assert _delays(page) == [40, 1], _delays(page)
        assert page.evaluate("!!document.querySelector('.notif-bubble[data-kind=\"reminder\"]')") is True


def test_removing_the_badge_on_failure_breaks_the_test(chromium_executable):
    """ריצת בקרה: removeDot() בחזרה לתוך failAndBackOff — הבועה נמחקת על 500."""
    script = _mutate(
        _shrunk(_polling_script(), 1, 40), BACKOFF_RETURNS, LOG_ON_FAILURE + "\n    removeDot();\n    return backoffMs;"
    )
    with _chain(chromium_executable, script, __statuses=[200, 500], __reply=_summary(**_DUE), __fireFirst=1) as page:
        page.wait_for_function("window.__calls.length >= 2", timeout=8000)
        page.wait_for_timeout(100)
        assert page.evaluate("!!document.querySelector('.notif-bubble[data-kind=\"reminder\"]')") is False


def test_a_401_on_a_focus_poll_cancels_the_pending_timer(chromium_executable):
    """401 שמגיע בפוקוס, בזמן שטיימר מהדגימה הקודמת תלוי: הטיימר מבוטל.

    לפני התיקון העצירה איפסה רק את הידית, והטיימר התלוי ירה ושלח עוד בקשה.
    הרצפה מאופסת כי הטיימר כאן הוא של 400 מ"ש ולא של 30 דקות.
    """
    script = _shrunk(_polling_script(), 0, 400)
    with _chain(chromium_executable, script, __statuses=[200, 401], __reply=_summary(), __fireFirst=1) as page:
        page.wait_for_function("window.__calls.length >= 1", timeout=8000)
        page.wait_for_timeout(50)
        _focus(page)
        page.wait_for_function("window.__calls.length >= 2", timeout=8000)
        page.wait_for_timeout(700)
        assert len(_calls(page)) == 2, len(_calls(page))
        assert _delays(page) == [400], _delays(page)


def test_dropping_the_clear_on_stop_breaks_the_test(chromium_executable):
    """ריצת בקרה: בלי clearTimeout בעצירה — הטיימר התלוי יורה ושולח בקשה שלישית."""
    script = _mutate(_shrunk(_polling_script(), 0, 400), STOP_CLEARS_TIMER, "    pollTimer = null;")
    with _chain(chromium_executable, script, __statuses=[200, 401], __reply=_summary(), __fireFirst=1) as page:
        page.wait_for_function("window.__calls.length >= 1", timeout=8000)
        page.wait_for_timeout(50)
        _focus(page)
        page.wait_for_function("window.__calls.length >= 3", timeout=8000)
        assert len(_calls(page)) == 3, len(_calls(page))


# --- 401 ברשימה: הסשן נגמר, לא "לא ידוע" ---------------------------------------

def test_a_401_on_the_list_says_the_session_ended(chromium_executable):
    """הסשן פג בין הדגימה ללחיצה: החלונית אומרת זאת, הבועה יורדת, והשרשרת נעצרת.

    לפני התיקון 401 ברשימה קיבל את הטיפול הגנרי — "לא הצלחתי לבדוק" ובועה
    שנשארת — בעוד אותו 401 בדגימה מסיר את הבועה ועוצר את השרשרת.
    """
    due = _summary(**_DUE)
    with _chain(chromium_executable, _polling_script(), __status=200, __reply=due, __listStatus=401) as page:
        page.wait_for_function("!!document.querySelector('.notif-bubble[data-kind=\"reminder\"]')", timeout=8000)
        armed = _delays(page)
        pop = _click_bubble_and_read_popover(page)
        assert "ההתחברות פגה" in pop["title"], pop
        assert pop["links"] == 0 and pop["snooze"] is False and pop["close"] is True, pop
        assert page.evaluate("!!document.querySelector('.notif-bubble[data-kind=\"reminder\"]')") is False
        page.click(".notif-popover [data-action='close-ui']")
        page.wait_for_timeout(200)
        # השרשרת עצורה: אין טיימר חדש, והפוקוס הבא מנסה מיד ומקבל 401 גם בדגימה.
        page.evaluate("window.__status = 401")
        before = len([c for c in _calls(page) if "/summary" in c["url"]])
        _focus(page)
        page.wait_for_timeout(400)
        after = len([c for c in _calls(page) if "/summary" in c["url"]])
        assert after == before + 1, (before, after)
        assert _delays(page) == armed, _delays(page)


def test_treating_a_list_401_as_unknown_breaks_the_test(chromium_executable):
    """ריצת בקרה: 401 ברשימה במסלול הגנרי — "לא הצלחתי", והבועה נשארת."""
    script = _mutate(_polling_script(), LIST_401_STOPS, "")
    due = _summary(**_DUE)
    with _chain(chromium_executable, script, __status=200, __reply=due, __listStatus=401) as page:
        page.wait_for_function("!!document.querySelector('.notif-bubble[data-kind=\"reminder\"]')", timeout=8000)
        pop = _click_bubble_and_read_popover(page)
        assert "לא הצלחתי" in pop["title"], pop
        page.click(".notif-popover [data-action='close-ui']")
        page.wait_for_timeout(200)
        assert page.evaluate("!!document.querySelector('.notif-bubble[data-kind=\"reminder\"]')") is True


# --- timeout בכל דפדפן, לוג על כל כשל, גוף שאינו תשובה, והלחיצה האחרונה מנצחת ---

def _popover_title(page):
    return page.evaluate("(document.querySelector('.notif-popover__title') || {}).textContent || ''")


def test_a_browser_without_abortsignal_timeout_still_gets_a_timeout(chromium_executable):
    """בלי AbortSignal.timeout הבקשה מקבלת את אותה תקרה מ-AbortController.

    לפני התיקון דפדפן כזה שלח בלי סיגנל: בקשה תקועה השאירה את inFlight דלוק
    לנצח וכל פוקוס נחסם — בעוד שבקוד שלפני הגארד הפוקוס פתח בקשה חדשה.
    הגארד אינו יכול לחיות יותר מהבקשה שהוא שומר. התקרה מקוצרת בעותק; טיימר
    ה-abort הוא setTimeout רגיל, ולכן ה-harness מפעיל אותו.
    """
    script = _with_fetch_timeout(_polling_script(), 300)
    with _chain(chromium_executable, script, setup_js=NO_ABORT_TIMEOUT, __mode="stall", __fireFirst=1) as page:
        page.wait_for_function("window.__calls.length >= 1", timeout=8000)
        page.wait_for_timeout(1500)
        assert _calls(page)[0]["hasSignal"] is True
        assert page.evaluate("window.__abortReason") == "AbortError"
        assert _delays(page) == [300, MIN_POLL_MS], _delays(page)


def test_disabling_the_abort_fallback_breaks_the_test(chromium_executable):
    """ריצת בקרה: בלי ענף ה-AbortController — בלי סיגנל, ובלי טיימר אחרי התקרה."""
    script = _mutate(_with_fetch_timeout(_polling_script(), 300), ABORT_FALLBACK, "} else if (false) {")
    with _chain(chromium_executable, script, setup_js=NO_ABORT_TIMEOUT, __mode="stall", __fireFirst=1) as page:
        page.wait_for_function("window.__calls.length >= 1", timeout=8000)
        page.wait_for_timeout(1500)
        assert _calls(page)[0]["hasSignal"] is False
        assert _delays(page) == [], _delays(page)


def test_every_poll_failure_is_logged(chromium_executable):
    """כשל בדגימה משאיר שורה בקונסול: מספר הכשל, ההמתנה הבאה והסיבה.

    לפני התיקון אפס console.* ב-IIFE מול 14 catch(_): הבועה נעלמה בשקט וגם
    צילום מסך של הקונסול לא אמר למה. הקובץ עצמו כבר רושם console.error
    בארבעה מקומות אחרים — זו הצורה הקיימת.
    """
    sink = []
    with _chain(chromium_executable, _polling_script(), console_sink=sink, __status=500) as page:
        page.wait_for_function("window.__delays.length >= 1", timeout=8000)
    warnings = [text for kind, text in sink if kind == "warning"]
    assert len(warnings) == 1, sink
    assert "(#1)" in warnings[0] and f"retry in {MIN_POLL_MS} ms" in warnings[0] and "500" in warnings[0], warnings


def test_the_401_stop_is_logged(chromium_executable):
    """גם העצירה על 401 נרשמת — אחרת "הפעמון הפסיק לעבוד" בלי שום עקבה."""
    sink = []
    with _chain(chromium_executable, _polling_script(), console_sink=sink, __status=401) as page:
        page.wait_for_function("window.__calls.length >= 1", timeout=8000)
        page.wait_for_timeout(200)
    warnings = [text for kind, text in sink if kind == "warning"]
    assert len(warnings) == 1 and "401" in warnings[0], sink


def test_dropping_the_failure_log_breaks_the_test(chromium_executable):
    """ריצת בקרה: בלי console.warn — אפס אזהרות על 500."""
    sink = []
    script = _mutate(_polling_script(), LOG_ON_FAILURE, "")
    with _chain(chromium_executable, script, console_sink=sink, __status=500) as page:
        page.wait_for_function("window.__delays.length >= 1", timeout=8000)
    assert [text for kind, text in sink if kind == "warning"] == [], sink


def test_a_body_that_is_not_a_summary_is_a_failure(chromium_executable):
    """200 עם גוף שאינו תשובה — {} — הוא "לא ידוע": backoff של דקה, לא שינה של חצי שעה.

    לפני התיקון הבדיקה הייתה ``j.ok === false`` בלבד ו-{} עבר כהצלחה: המונה
    אופס והשרשרת נרדמה 30 דקות, בעוד ההערה מעל השורה קראה לגוף ריק "לא ידוע"
    ומסלול הרשימה כבר בדק ``lj.ok``. השרת אינו מייצר גוף כזה היום.
    """
    with _chain(chromium_executable, _polling_script(), __status=200, __reply={}) as page:
        page.wait_for_function("window.__delays.length >= 1", timeout=8000)
        assert _delays(page) == [MIN_POLL_MS], _delays(page)
        assert page.evaluate("typeof window.__stickyRemindersBackoffUntil") == "number"


def test_accepting_any_truthy_body_breaks_the_test(chromium_executable):
    """ריצת בקרה: ``j.ok === false`` בלבד — {} נרדם חצי שעה בלי backoff."""
    script = _mutate(
        _polling_script(), BAD_BODY_CHECK, "if (!j || j.ok === false) { return failAndBackOff('bad body'); }"
    )
    with _chain(chromium_executable, script, __status=200, __reply={}) as page:
        page.wait_for_function("window.__delays.length >= 1", timeout=8000)
        assert _delays(page) == [MAX_POLL_MS], _delays(page)


def _click_twice_first_stalls(page):
    """לחיצה ראשונה שנתקעת, ואז לחיצה שנייה שמחזירה רשימה של פריט אחד."""
    page.click(".notif-bubble[data-kind='reminder']")
    page.wait_for_timeout(100)
    page.evaluate(
        "window.__listMode = 'status'; "
        "window.__listReply = {ok: true, count: 1, items: [{note_id: 'n1', file_id: 'f1', preview: 'שלום'}]};"
    )
    page.click(".notif-bubble[data-kind='reminder']")
    page.wait_for_selector(".notif-popover[data-kind='reminder']", timeout=8000)


def test_a_late_failure_does_not_overwrite_a_list_already_shown(chromium_executable):
    """לחיצה ראשונה נתקעת, השנייה מחזירה רשימה; כשהתקרה של הראשונה נגמרת — הרשימה נשארת.

    לפני התיקון הכשל המאוחר של הלחיצה הראשונה החליף רשימה נכונה ב"לא הצלחתי
    לבדוק". הלחיצה האחרונה מנצחת. התקרה מקוצרת בעותק כדי לא להמתין 15 שניות.
    """
    script = _with_fetch_timeout(_polling_script(), 300)
    with _chain(chromium_executable, script, __status=200, __reply=_summary(**_DUE), __listMode="stall") as page:
        page.wait_for_function("!!document.querySelector('.notif-bubble[data-kind=\"reminder\"]')", timeout=8000)
        _click_twice_first_stalls(page)
        assert "יש לך 1" in _popover_title(page), _popover_title(page)
        page.wait_for_timeout(800)
        assert "יש לך 1" in _popover_title(page), _popover_title(page)


def test_letting_every_click_render_breaks_the_test(chromium_executable):
    """ריצת בקרה: בלי "האחרונה מנצחת" — הכשל המאוחר דורס את הרשימה."""
    script = _mutate(_with_fetch_timeout(_polling_script(), 300), LATEST_CLICK, "const gen = listGen;")
    with _chain(chromium_executable, script, __status=200, __reply=_summary(**_DUE), __listMode="stall") as page:
        page.wait_for_function("!!document.querySelector('.notif-bubble[data-kind=\"reminder\"]')", timeout=8000)
        _click_twice_first_stalls(page)
        assert "יש לך 1" in _popover_title(page), _popover_title(page)
        page.wait_for_timeout(800)
        assert "לא הצלחתי" in _popover_title(page), _popover_title(page)


def test_ignoring_a_thrown_list_error_breaks_the_test(chromium_executable):
    """ריצת בקרה: catch שבולע (``/* ignore */``, כמו ב-main לפני #3438) — שגיאת רשת ברשימה
    לא פותחת חלונית בכלל, ולכן המקרה network-error של הטסט הראשי נופל."""
    script = _mutate(_polling_script(), LIST_CATCH_REPORTS, "          /* ignore */")
    due = _summary(**_DUE)
    with _chain(chromium_executable, script, __status=200, __reply=due, __listMode="reject") as page:
        page.wait_for_function("!!document.querySelector('.notif-bubble[data-kind=\"reminder\"]')", timeout=8000)
        page.click(".notif-bubble[data-kind='reminder']")
        page.wait_for_timeout(500)
        assert page.evaluate("!!document.querySelector('.notif-popover[data-kind=\"reminder\"]')") is False


# --- 429, ותשובה שחוזרת אחרי שהשרשרת נעצרה ---------------------------------------


def test_a_429_keeps_the_badge_and_is_not_counted_as_a_failure(chromium_executable):
    """429 אחרי "יש תזכורות": הבועה נשארת, החלון נכתב, והמונה לא זז.

    429 אינו כשל ואינו "אין" — השרת נקב בעצמו בהמתנה. לפני התיקון הענף מחק
    את הבועה, בניגוד לכלל שרק "אין" ו-401 מסירים אותה. ה-500 שאחריו הוא
    הכשל הראשון (המתנה של MIN, לא של 2·MIN).
    """
    script = _shrunk(_polling_script(), 1, 40)
    with _chain(
        chromium_executable, script, __statuses=[200, 429, 500], __reply=_summary(**_DUE), __fireFirst=1
    ) as page:
        page.wait_for_function("window.__calls.length >= 2", timeout=8000)
        page.wait_for_timeout(100)
        assert page.evaluate("!!document.querySelector('.notif-bubble[data-kind=\"reminder\"]')") is True
        assert page.evaluate("window.__stickyRemindersBackoffUntil > Date.now()") is True
        # חלון ה-429 חוסם את הבקשה הבאה בתוך poll(); מנקים אותו כדי שה-500 יצא בפוקוס.
        page.evaluate("window.__stickyRemindersBackoffUntil = 0")
        _focus(page)
        page.wait_for_function("window.__calls.length >= 3", timeout=8000)
        page.wait_for_timeout(100)
        assert _delays(page) == [40, 40, 1], _delays(page)
        assert page.evaluate("!!document.querySelector('.notif-bubble[data-kind=\"reminder\"]')") is True


def test_removing_the_badge_on_429_breaks_the_test(chromium_executable):
    """ריצת בקרה: removeDot() בחזרה לענף ה-429 — הבועה נמחקת."""
    script = _mutate(
        _shrunk(_polling_script(), 1, 40), KEEP_BADGE_ON_429,
        KEEP_BADGE_ON_429.replace("        return backoffMs;", "        removeDot();\n        return backoffMs;"),
    )
    with _chain(chromium_executable, script, __statuses=[200, 429], __reply=_summary(**_DUE), __fireFirst=1) as page:
        page.wait_for_function("window.__calls.length >= 2", timeout=8000)
        page.wait_for_timeout(100)
        assert page.evaluate("!!document.querySelector('.notif-bubble[data-kind=\"reminder\"]')") is False


def _stop_by_list_401_during_a_pending_poll(page, mode):
    """דגימה שנייה שנשארת באוויר (``hold`` או ``stall``), ובינתיים לחיצה על הבועה מקבלת 401.

    מחזיר את רשימת הטיימרים ברגע העצירה — הטענה של הקורא היא שהיא לא גדלה.
    """
    page.wait_for_function("!!document.querySelector('.notif-bubble[data-kind=\"reminder\"]')", timeout=8000)
    page.evaluate(f"window.__mode = '{mode}'")
    _focus(page)
    page.wait_for_function(
        "window.__calls.filter(c => c.url.indexOf('/summary') !== -1).length >= 2", timeout=8000
    )
    pop = _click_bubble_and_read_popover(page)
    assert "ההתחברות פגה" in pop["title"], pop
    assert page.evaluate("!!document.querySelector('.notif-bubble[data-kind=\"reminder\"]')") is False
    return _delays(page)


def test_a_stale_summary_after_a_stop_does_not_revive_the_chain(chromium_executable):
    """דגימה שהייתה באוויר כשלחיצה קיבלה 401: תשובתה המאוחרת נזרקת.

    לפני התיקון "יש תזכורות" שהגיע אחרי "ההתחברות פגה" החזיר את הבועה ודרך
    טיימר — השרשרת קמה לתחייה מתשובה ישנה. ההשוואה אחרי ה-await היא הגבול.
    """
    sink = []
    script = _shrunk(_polling_script(), 1, 40)
    with _chain(
        chromium_executable, script, console_sink=sink, __status=200, __reply=_summary(**_DUE), __listStatus=401
    ) as page:
        armed = _stop_by_list_401_during_a_pending_poll(page, "hold")
        page.evaluate("window.__release()")
        page.wait_for_timeout(300)
        assert page.evaluate("!!document.querySelector('.notif-bubble[data-kind=\"reminder\"]')") is False
        assert _delays(page) == armed, (armed, _delays(page))
        title = page.evaluate("(document.querySelector('.notif-popover__title') || {}).textContent || ''")
        assert "ההתחברות פגה" in title, title
        assert [t for _, t in sink if "outlived a stop" in t], sink


def test_dropping_the_generation_bump_breaks_the_test(chromium_executable):
    """ריצת בקרה: העצירה לא מעלה את הדור — התשובה הישנה מחזירה בועה ודורכת טיימר."""
    script = _mutate(_shrunk(_polling_script(), 1, 40), STOP_BUMPS_GEN, "    stopped = true;")
    with _chain(chromium_executable, script, __status=200, __reply=_summary(**_DUE), __listStatus=401) as page:
        armed = _stop_by_list_401_during_a_pending_poll(page, "hold")
        page.evaluate("window.__release()")
        page.wait_for_timeout(300)
        assert page.evaluate("!!document.querySelector('.notif-bubble[data-kind=\"reminder\"]')") is True
        assert len(_delays(page)) == len(armed) + 1, (armed, _delays(page))


def test_a_stale_timeout_after_a_stop_is_not_a_failure(chromium_executable):
    """הדגימה שהייתה באוויר נחתכת ב-timeout אחרי העצירה: לא כשל, לא backoff, לא טיימר.

    לפני התיקון ה-TimeoutError המאוחר נכנס ל-failAndBackOff — אזהרת "poll
    failed", חלון backoff, וטיימר שמחיה שרשרת שנעצרה בגלל 401. התקרה מקוצרת
    בעותק ל-300 מ"ש.
    """
    sink = []
    script = _with_fetch_timeout(_shrunk(_polling_script(), 1, 40), 300)
    with _chain(
        chromium_executable, script, console_sink=sink, __status=200, __reply=_summary(**_DUE), __listStatus=401
    ) as page:
        armed = _stop_by_list_401_during_a_pending_poll(page, "stall")
        page.wait_for_function("window.__abortReason === 'TimeoutError'", timeout=5000)
        page.wait_for_timeout(200)
        assert _delays(page) == armed, (armed, _delays(page))
        assert not [t for _, t in sink if "poll failed" in t], sink


def test_dropping_the_generation_bump_breaks_the_timeout_test(chromium_executable):
    """ריצת בקרה: בלי העלאת הדור, ה-timeout המאוחר נספר ככשל ודורך טיימר."""
    sink = []
    script = _mutate(_with_fetch_timeout(_shrunk(_polling_script(), 1, 40), 300), STOP_BUMPS_GEN, "    stopped = true;")
    with _chain(
        chromium_executable, script, console_sink=sink, __status=200, __reply=_summary(**_DUE), __listStatus=401
    ) as page:
        armed = _stop_by_list_401_during_a_pending_poll(page, "stall")
        page.wait_for_function("window.__abortReason === 'TimeoutError'", timeout=5000)
        page.wait_for_timeout(200)
        assert len(_delays(page)) == len(armed) + 1, (armed, _delays(page))
        assert [t for _, t in sink if "poll failed" in t], sink


# --- יש בועה: השרת אומר מתי לחזור, והלקוח מקשיב ---------------------------------


def test_a_due_reminder_uses_the_servers_refresh_interval(chromium_executable):
    """יש בועה והשרת אמר לחזור בעוד חמש דקות: הטיימר הוא חמש דקות, לא התקרה.

    לפני התיקון הענף של "יש בשלה" התעלם מ-next_in_seconds ונרדם לחצי שעה —
    בועה שנוקתה ממכשיר אחר, או מונה שהשתנה, חיכו עד אז.
    """
    reply = _summary(**_DUE, next_in_seconds=300)
    with _chain(chromium_executable, _polling_script(), __status=200, __reply=reply) as page:
        page.wait_for_function("window.__delays.length >= 1", timeout=8000)
        assert _delays(page) == [300 * 1000], _delays(page)
        assert page.evaluate("!!document.querySelector('.notif-bubble[data-kind=\"reminder\"]')") is True


def test_ignoring_the_interval_while_a_badge_is_up_breaks_the_test(chromium_executable):
    """ריצת בקרה: הענף חוזר להחזיר את התקרה — הטיימר הוא חצי שעה."""
    script = _mutate(_polling_script(), DUE_USES_SERVER_DELAY, "      return MAX_POLL_MS;")
    reply = _summary(**_DUE, next_in_seconds=300)
    with _chain(chromium_executable, script, __status=200, __reply=reply) as page:
        page.wait_for_function("window.__delays.length >= 1", timeout=8000)
        assert _delays(page) == [MAX_POLL_MS], _delays(page)
