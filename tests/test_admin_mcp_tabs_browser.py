"""בדיקת אינטראקציה אמיתית לטאבים של ``/admin/mcp``.

בדיקת שרת מאמתת שה-HTML נוצר. היא **אינה** יכולה לאמת שהלחיצה עובדת:
ה-JS שמחליף פאנלים רץ רק בדפדפן, ומחלקת ``active`` על האלמנט הנכון היא
הדבר היחיד שמפריד בין "שלושה טאבים" לבין "טאב אחד ושני אלמנטים מתים".

הטסט מדולג בשקט כשאין Chromium — הוא נועד לרוץ מקומית ובכל סביבה שיש בה
דפדפן, ולא להפיל CI שאין בו אחד.
"""

from __future__ import annotations

import contextlib
import os
import socket
import sys
import threading
import types

import pytest

import services.mcp_analytics_service as mcp
from services.mcp_analytics_service import EndpointResult

pytest.importorskip("playwright", reason="playwright אינו מותקן")

from playwright.sync_api import sync_playwright  # noqa: E402

HEALTH_ROWS = [
    {
        "tool": "codekeeper_get_repo_file", "calls": 52, "errors": 2,
        "error_rate_pct": 3.8, "p50_ms": 169.0, "p95_ms": 612.0,
        "sessions": 8, "last_seen": "2026-09-02T08:16:17.587000Z",
    },
    {
        "tool": None, "calls": 1, "errors": 0, "error_rate_pct": 0.0,
        "p50_ms": None, "p95_ms": None, "sessions": 1, "last_seen": None,
    },
]
NAV_ROWS = [{
    "session": "ses_x", "started": "2026-09-02T08:15:00.843000Z",
    "client": "claude-code", "calls": 15, "searches": 0,
    "outline_reads": 2, "content_reads": 12,
    "errors": 0, "total_ms": 2574.0,
    # ארוך בכוונה: הטור הזה הוא מה שיכול להרחיב את הטבלה מעבר למסך.
    "intent": (
        "mapping the admin routes in webapp/app.py before reading the exact line range, "
        "so a single outline call replaces a full read of twenty thousand lines"
    ),
    "total_sessions": 10,
}]
FAILURE_ROWS = [
    {
        "failed_at": "2026-09-05T00:43:14.487000Z",
        "tool": "codekeeper_get_file", "client": "claude-code",
        "error_type": "ValidationError",
        "error_message": (
            "1 validation error for get_fileArguments\nlines.1\n"
            "  Input should be a valid integer "
            "[type=int_type, input_value='9', input_type=str]"
        ),
        "session": "ses_x",
    },
    {
        "failed_at": "2026-09-03T21:01:34.441000Z",
        "tool": "codekeeper_get_repo_file", "client": None,
        "error_type": "ValidationError", "error_message": None,
        "session": "ses_y",
    },
]
POSTHOG_LINKS = {
    "intent_clusters": "https://us.posthog.com/project/567754/mcp-analytics/intent-clustering",
    "sessions": "https://us.posthog.com/project/567754/mcp-analytics/sessions",
}


# --------------------------------------------------------------------------
# החלפת שורות בשרת, לפני הרינדור
#
# בדיקת escape חייבת לקרוא את מה ש-Jinja הוציאה. טסט ששותל מחרוזת ב-DOM אחרי
# הרינדור בודק את הדפדפן, לא את התבנית — וזו בדיוק הטעות שהגרסה הקודמת של
# בדיקת ה-XSS כאן עשתה.
# --------------------------------------------------------------------------

_NAV_ROWS_OVERRIDE: list | None = None


def _nav_rows():
    return list(_NAV_ROWS_OVERRIDE if _NAV_ROWS_OVERRIDE is not None else NAV_ROWS)


#: ``hasMore`` מגיע מ-PostHog כשהשאילתה נחתכה בתקרה. הוא מוחלף כאן ולא
#: ב-DOM, כי מה שנבדק הוא מה שהתבנית עושה עם הערך הזה.
_FAILURES_HAS_MORE = False


def _failures_result():
    return EndpointResult(rows=list(FAILURE_ROWS), has_more=_FAILURES_HAS_MORE)


@contextlib.contextmanager
def _truncated_failures():
    """מסמן שהטבלה נחתכה בתקרה, כלומר יש עוד שורות שלא הוחזרו."""
    global _FAILURES_HAS_MORE
    previous = _FAILURES_HAS_MORE
    _FAILURES_HAS_MORE = True
    try:
        yield
    finally:
        _FAILURES_HAS_MORE = previous


#: הטאב השלישי ריק כברירת מחדל — וזה מצב תקין שנבדק במקום אחר. כדי לבדוק
#: את כפתור ההעתקה שבשורה צריך שורה, ולכן היא מוחלפת בשרת לפני הרינדור.
_MISSING_ROWS_OVERRIDE: list = []

CAPABILITY_TEXT = (
    "לחפש בתוך תוצאות של חיפוש קודם | בלי להריץ את החיפוש מחדש\n"
    "היום צריך לשמור את התוצאות בצד"
)


def _missing_rows():
    return list(_MISSING_ROWS_OVERRIDE)


@contextlib.contextmanager
def _one_missing_capability():
    """שורה אחת בטאב "כלים חסרים", עם צינור ושורה חדשה בתוך הטקסט.

    שני התווים האלה הם מה ששובר טבלת Markdown, ולכן הם בטקסט הבדיקה ולא
    בהערה עליו.
    """
    global _MISSING_ROWS_OVERRIDE
    previous = _MISSING_ROWS_OVERRIDE
    _MISSING_ROWS_OVERRIDE = [{
        "reported_at": "2026-09-02T10:00:00Z",
        "capability": CAPABILITY_TEXT,
        "intent_source": "agent",
        "client": "claude-code",
        "session": "ses_x",
    }]
    try:
        yield
    finally:
        _MISSING_ROWS_OVERRIDE = previous


#: שורות סשן נוספות, כדי שיהיה מה למיין ומה לחתוך בהעתקה.
_EXTRA_NAV_ROWS = 6


@contextlib.contextmanager
def _many_sessions():
    """שש שורות שבהן הזמן הכולל **עולה** עם האינדקס.

    כלומר סדר ברירת המחדל (החדש קודם) הפוך לסדר של "זמן כולל, יורד" —
    וזה מה שמאפשר לבדוק שההעתקה לוקחת את הסדר שעל המסך ולא את המקורי.
    """
    global _NAV_ROWS_OVERRIDE
    previous = _NAV_ROWS_OVERRIDE
    _NAV_ROWS_OVERRIDE = [
        {
            **NAV_ROWS[0],
            "session": f"ses_{index}",
            "total_ms": 1000.0 + index * 100,
            "calls": index,
            "intent": f"intent {index}",
        }
        for index in range(_EXTRA_NAV_ROWS)
    ]
    try:
        yield
    finally:
        _NAV_ROWS_OVERRIDE = previous


@contextlib.contextmanager
def _hostile_intent(text):
    """מחליף את הכוונה בשורת הניווט לאורך הבקשה, ומשחזר בסיום."""
    global _NAV_ROWS_OVERRIDE
    previous = _NAV_ROWS_OVERRIDE
    _NAV_ROWS_OVERRIDE = [{**NAV_ROWS[0], "intent": text}]
    try:
        yield
    finally:
        _NAV_ROWS_OVERRIDE = previous


# ``_find_chromium`` ו-``live_server`` שלהלן מחזיקים כאן עותק משלהם, בניגוד
# לשאר קבצי הדפדפן שמשתמשים ב-``admin_live_server`` מ-``tests/conftest.py``.
# הסיבה: הפיקסצ'ר כאן מזייף את ``get_mcp_analytics_service`` **לפני** שהשרת
# מתחיל להגיש בקשות, ולכן הוא צריך שליטה על סדר ההקמה שהפיקסצ'ר המשותף אינו
# נותן.
#
# מה שכן משותף הוא **השער**: ``live_server`` מבקש את ``chromium_executable``
# מ-``tests/conftest.py``, ששם מוכרע פעם אחת לכל הריצה אם יש דפדפן. השליטה
# על סדר ההקמה והשאלה "יש דפדפן בכלל" הן שתי שאלות נפרדות, ורק הראשונה היא
# הסיבה לעותק המקומי.
def _find_chromium():
    """מאתר Chromium מותקן. מחזיר ``None`` אם אין — הטסט ידולג."""
    from pathlib import Path

    root = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "")) if os.environ.get(
        "PLAYWRIGHT_BROWSERS_PATH"
    ) else None
    if root and root.is_dir():
        for candidate in sorted(root.glob("chromium*/chrome-linux/chrome")):
            if candidate.exists():
                return str(candidate)
    return None


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def live_server(chromium_executable):
    """מריץ את הוובאפ האמיתי עם שירות מזויף, בלי לגעת ברשת.

    כל שינוי גלובלי עובר דרך ``MonkeyPatch`` ומשוחזר בסיום, והשרת נעצר
    במפורש. pytest מריץ את כל הקבצים בתהליך אחד, ולכן מצב שלא שוחזר
    היה מדליף לטסטים אחרים ויוצר תלות בסדר.

    **``chromium_executable`` כאן הוא השער ולא הנתיב, וזאת הסיבה שהוא
    מבוקש דווקא כאן.** כל שמונה-עשר הטסטים בקובץ נשענים על הפיקסצ'ר הזה,
    ישירות או דרך ``page``, ולכן זו הנקודה האחת שמכריעה עבור כולם. אין
    דפדפן ← הם מדולגים לפני שהשרת עולה בכלל, ולפני שמישהו מרים תהליך
    דרייבר של Playwright. הערך המוחזר אינו בשימוש כאן; ``_find_chromium``
    המקומי הוא זה שנותן את הנתיב, מהסיבה שכתובה למעלה.
    """
    import webapp.app as app_mod
    from werkzeug.serving import make_server

    fake = types.SimpleNamespace(
        # ``**_`` — ראו ההסבר ב-``tests/test_admin_mcp_page.py``.
        get_dashboard=lambda **_: {
            mcp.ENDPOINT_TOOL_HEALTH: EndpointResult(rows=list(HEALTH_ROWS)),
            mcp.ENDPOINT_TOOL_FAILURES: _failures_result(),
            # ``_nav_rows()`` ולא ``NAV_ROWS`` ישירות: כך טסט יכול להחליף את
            # השורות **בשרת** לפני הרינדור, במקום לשתול ערך ב-DOM אחרי כן.
            # ``total`` נגזר מהשורות ולא קבוע: אחרת כל מיון היה מסומן
            # חלקי, והבדיקה של התווית הייתה עוברת בלי קשר לקוד.
            mcp.ENDPOINT_NAVIGATION_COST: (
                lambda rows: EndpointResult(rows=rows, total=len(rows))
            )(_nav_rows()),
            mcp.ENDPOINT_MISSING_CAPABILITIES: EndpointResult(rows=_missing_rows()),
        },
        posthog_links=lambda: dict(POSTHOG_LINKS),
    )

    patch = pytest.MonkeyPatch()
    patch.setattr(mcp, "get_mcp_analytics_service", lambda: fake)
    patch.setenv("ADMIN_USER_IDS", "1")

    app = app_mod.app
    patch.setitem(app.config, "SECRET_KEY", "browser-tab-test")

    # ה-session נבנה דרך ``test_client`` ולא דרך route עזר. Flask אוסר
    # ``@app.route`` אחרי שהאפליקציה טיפלה בבקשה הראשונה, ובריצת סוויטה
    # מלאה טסט אחר כבר עשה זאת — ולכן route שנרשם כאן היה מפיל את הטסט
    # בהתאם לסדר הריצה.
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess["user_id"] = 1
            sess["user_data"] = {"id": 1, "is_admin": True, "is_premium": False}
        cookie = client.get_cookie("session")
        assert cookie is not None, "לא נוצר session cookie"
        session_cookie = cookie.value

    # ``make_server`` ולא ``app.run``: הוא מחזיר אובייקט שאפשר לעצור.
    httpd = make_server("127.0.0.1", 0, app, threaded=True)
    port = httpd.server_port
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()

    import time
    import urllib.request

    for _ in range(60):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=1)
            break
        except Exception as exc:
            if "HTTP Error" in str(exc):  # השרת עונה, גם אם 404
                break
            time.sleep(0.25)
    else:  # pragma: no cover
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)
        patch.undo()
        pytest.skip("שרת הבדיקה לא עלה")

    try:
        yield f"http://127.0.0.1:{port}", session_cookie
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)
        patch.undo()


DESKTOP_VIEWPORT = {"width": 1280, "height": 900}
#: פיקסלים לוגיים של מכשירי אנדרואיד נפוצים. העמוד נצרך מטאבלט, ולכן
#: "עובר בדסקטופ" אינו ראיה — הטבלאות רחבות והמודאל נפתח מעל מסך צר.
PHONE_VIEWPORT = {"width": 390, "height": 844}


@contextlib.contextmanager
def _browser_page(live_server, local_storage=None, viewport=None, query="", init_script=None):
    """פותח את העמוד בהקשר דפדפן נקי — **המקום היחיד** שמרים דפדפן בקובץ הזה.

    ``local_storage`` הוא הערך של ``mcpFailuresLastSeenAt``; ``None`` מוחק
    אותו, כלומר "ביקור ראשון". הכתיבה עוברת ב-``add_init_script`` שרץ
    **לפני** קוד העמוד, כי כתיבה אחרי ``goto`` מגיעה אחרי שהבאנר כבר חישב.

    ``init_script`` הוא JS נוסף שרץ באותה נקודה — לזריעת אחסון קיים או
    לחסימת האחסון. אותו נימוק בדיוק: אחרי ``goto`` זה כבר מאוחר.

    כל הניקוי יושב כאן ב-``finally``: כשהוא ישב אצל הקורא, כשל של ``goto``
    היה מדליף דפדפן שלם ואת סשן ה-Playwright איתו.
    """
    base_url, session_cookie = live_server
    executable = _find_chromium()
    pw = sync_playwright().start()
    browser = None
    try:
        try:
            browser = (
                pw.chromium.launch(executable_path=executable)
                if executable
                else pw.chromium.launch()
            )
        except Exception as exc:  # pragma: no cover
            pytest.skip(f"אין Chromium זמין: {exc}")
        # ``clipboard-read`` נדרש כדי **לקרוא בחזרה** את מה שנכתב ללוח.
        # בלי קריאה חוזרת הבדיקה בודקת שהקריאה לא זרקה, ולא שמשהו הועתק —
        # וזו בדיוק ההבחנה בין ירוק אמיתי לירוק שקרי.
        context = browser.new_context(
            viewport=viewport or DESKTOP_VIEWPORT,
            permissions=["clipboard-read", "clipboard-write"],
        )
        context.add_cookies([{
            "name": "session", "value": session_cookie,
            "domain": "127.0.0.1", "path": "/",
        }])
        page = context.new_page()
        # מודאל ה-onboarding של הוובאפ נפתח למשתמש חדש וחוסם קליקים
        setup = (
            "try{localStorage.setItem('welcomeModalSeen','1');"
            "localStorage.setItem('onboarding_completed','1');"
        )
        if local_storage is not None:
            setup += f"localStorage.setItem('mcpFailuresLastSeenAt','{local_storage}');"
        else:
            setup += "localStorage.removeItem('mcpFailuresLastSeenAt');"
        setup += "}catch(e){}"
        page.add_init_script(setup)
        if init_script:
            page.add_init_script(init_script)
        page.goto(f"{base_url}/admin/mcp{query}", wait_until="domcontentloaded")
        page.wait_for_timeout(400)
        page.evaluate(
            "document.querySelectorAll('.welcome-modal, .welcome-modal__backdrop, #welcomeModal')"
            ".forEach(e => e.remove())"
        )
        yield page
    finally:
        if browser is not None:
            browser.close()
        pw.stop()


@pytest.fixture
def page(live_server):
    """הפיקסצ'ר הוא רק שם נוח ל-``_browser_page`` עם ברירות המחדל."""
    with _browser_page(live_server) as p:
        yield p


def _state(page):
    return page.evaluate("""() => ({
        activePanels: [...document.querySelectorAll('.mcp-panel')]
            .filter(p => p.classList.contains('active')).map(p => p.dataset.panel),
        visiblePanels: [...document.querySelectorAll('.mcp-panel')]
            .filter(p => p.offsetParent !== null).map(p => p.dataset.panel),
        selectedTabs: [...document.querySelectorAll('.mcp-tab')]
            .filter(t => t.getAttribute('aria-selected') === 'true').map(t => t.dataset.panel),
    })""")


def test_clicking_each_tab_switches_the_panel_and_the_selected_state(page):
    """זה מה שבדיקת שרת אינה יכולה להוכיח."""
    assert len(page.query_selector_all("button.mcp-tab")) == 3

    for name in ("navigation", "missing", "health"):
        page.click(f'button.mcp-tab[data-panel="{name}"]')
        page.wait_for_timeout(120)
        state = _state(page)

        assert state["activePanels"] == [name], f"{name}: פאנלים פעילים {state['activePanels']}"
        assert state["visiblePanels"] == [name], f"{name}: פאנלים גלויים {state['visiblePanels']}"
        assert state["selectedTabs"] == [name], f"{name}: aria-selected על {state['selectedTabs']}"


def test_each_tab_shows_its_own_content(page):
    page.click('button.mcp-tab[data-panel="navigation"]')
    page.wait_for_timeout(120)
    assert "claude-code" in page.inner_text('.mcp-panel[data-panel="navigation"]')

    page.click('button.mcp-tab[data-panel="missing"]')
    page.wait_for_timeout(120)
    missing = page.inner_text('.mcp-panel[data-panel="missing"]')
    assert "get_more_tools" in missing
    assert "לא ניתן לטעון" not in missing, "מצב ריק הוצג כשגיאה"


def test_the_page_does_not_scroll_horizontally_on_a_phone(page):
    page.set_viewport_size(PHONE_VIEWPORT)
    page.wait_for_timeout(200)
    doc_width = page.evaluate("document.documentElement.scrollWidth")
    viewport = page.evaluate("document.documentElement.clientWidth")

    assert doc_width <= viewport + 1, f"גלישה אופקית: {doc_width} > {viewport}"


def test_null_cells_never_render_the_word_none(page):
    text = page.inner_text('.mcp-panel[data-panel="health"]')

    assert "None" not in text
    assert "—" in text


def test_the_wider_navigation_table_scrolls_inside_its_own_card(page):
    """כשהטבלה רחבה מהכרטיס — **הכרטיס** גולל, לא גוף העמוד.

    **הגרסה הקודמת של הטסט הזה הבטיחה יותר ממה שהיא בדקה, ובדיעבד גם יותר
    ממה שנכון.** היא חישבה ``wrapperScrolls`` ולא אישרה אותו. כשהוספתי את
    האסרשן הוא נפל — ב-1280 פיקסלים הטבלה בת עשר העמודות פשוט **נכנסת**,
    ואין שום גלילה להוכיח. כלומר גם השם היה שגוי, לא רק האסרשן חסר.

    לכן המדידה עברה לרוחב שבו הגלישה אמיתית. המבנה כאן הוא שלוש טענות
    שכל אחת מהן מסוגלת ליפול: קודם שיש בכלל גלישה (אחרת הטסט חסר משמעות
    ועדיף שיצעק), אחר כך שהכרטיס הוא זה שגולל, ולבסוף שגוף העמוד אינו.
    """
    page.click('button.mcp-tab[data-panel="navigation"]')
    page.wait_for_timeout(150)
    # רוחב טלפון: כאן עשר עמודות בוודאות אינן נכנסות.
    page.set_viewport_size(PHONE_VIEWPORT)
    page.wait_for_timeout(250)

    measured = page.evaluate("""() => {
        const panel = '.mcp-panel[data-panel="navigation"]';
        const wrap = document.querySelector(panel + ' .mcp-table-wrapper');
        const table = wrap.querySelector('table');
        return {
            tableWidth: table.scrollWidth,
            cardWidth: wrap.clientWidth,
            wrapperScrolls: wrap.scrollWidth > wrap.clientWidth,
            overflowX: getComputedStyle(wrap).overflowX,
            docWidth: document.documentElement.scrollWidth,
            viewport: document.documentElement.clientWidth,
        };
    }""")

    # 1. יש גלישה בכלל — בלי זה שתי הטענות הבאות ריקות מתוכן.
    assert measured["tableWidth"] > measured["cardWidth"], measured
    # 2. הכרטיס הוא שגולל.
    assert measured["overflowX"] == "auto"
    assert measured["wrapperScrolls"] is True, measured
    # 3. וגוף העמוד לא — זו ההבטחה שהמשתמש מרגיש.
    assert measured["docWidth"] <= measured["viewport"] + 1, measured


def test_a_long_intent_keeps_its_full_text_in_the_title_attribute(page):
    """הקיצוץ הוא של התצוגה בלבד. מה שהדפדפן באמת מציג ב-hover נמדד כאן."""
    page.click('button.mcp-tab[data-panel="navigation"]')
    page.wait_for_timeout(150)

    measured = page.evaluate("""() => {
        const el = document.querySelector('.mcp-panel[data-panel="navigation"] .mcp-clip');
        return {title: el.getAttribute('title'), shown: el.textContent};
    }""")

    assert measured["title"] == NAV_ROWS[0]["intent"]
    assert len(measured["shown"]) < len(measured["title"])
    assert measured["shown"].endswith("…")


def test_an_intent_that_looks_like_markup_is_never_a_live_element(live_server):
    """``<script>`` בכוונה חייב להישאר טקסט — בדפדפן, לא רק במחרוזת.

    **הגרסה הקודמת של הטסט הזה לא בדקה כלום.** היא דחפה את המחרוזת העוינת
    ל-DOM עם ``setAttribute('title', hostile)`` ואז אישרה שאין ילדים ואין
    ``window.__pwned``. אבל ``setAttribute`` **לעולם אינו מפרסר HTML**, ולכן
    שתי האסרשנים היו נכונים תמיד — גם אילו Jinja הייתה שבורה לחלוטין. טסט
    XSS שאינו מסוגל להיכשל גרוע מהיעדר טסט, כי הוא נותן ביטחון במקום שאין בו.

    הגרסה הזו מזריקה את המחרוזת דרך **הנתונים**, נותנת לשרת לרנדר, ובודקת את
    ה-DOM שהדפדפן בנה בפועל: אפס אלמנטי ילד, הטקסט שרד כטקסט, ושום סקריפט
    לא רץ.
    """
    hostile = "<script>window.__pwned = 1</script>"
    base_url, session_cookie = live_server
    executable = _find_chromium()

    with sync_playwright() as pw:
        try:
            browser = (
                pw.chromium.launch(executable_path=executable)
                if executable
                else pw.chromium.launch()
            )
        except Exception as exc:  # pragma: no cover
            pytest.skip(f"אין Chromium זמין: {exc}")
        context = browser.new_context(viewport={"width": 1280, "height": 900})
        context.add_cookies([{
            "name": "session", "value": session_cookie,
            "domain": "127.0.0.1", "path": "/",
        }])
        p = context.new_page()
        p.add_init_script(
            "try{localStorage.setItem('welcomeModalSeen','1');"
            "localStorage.setItem('onboarding_completed','1');}catch(e){}"
        )
        # ``_hostile_intent`` מחליף את הכוונה בשרת לפני הרינדור, ולכן מה
        # שנבדק הוא הפלט האמיתי של Jinja ולא ערך שהטסט שתל ב-DOM אחרי כן.
        with _hostile_intent(hostile):
            p.goto(f"{base_url}/admin/mcp", wait_until="domcontentloaded")
        p.wait_for_timeout(400)
        p.evaluate(
            "document.querySelectorAll('.welcome-modal, .welcome-modal__backdrop, #welcomeModal')"
            ".forEach(e => e.remove())"
        )
        try:
            p.click('button.mcp-tab[data-panel="navigation"]')
            p.wait_for_timeout(150)
            measured = p.evaluate("""() => {
                const el = document.querySelector('.mcp-panel[data-panel="navigation"] .mcp-clip');
                return {
                    found: !!el,
                    pwned: window.__pwned === 1,
                    childElements: el ? el.children.length : -1,
                    scriptsWithPayload: [...document.querySelectorAll('script')]
                        .filter(s => (s.textContent || '').includes('__pwned')).length,
                    title: el ? el.getAttribute('title') : null,
                };
            }""")
        finally:
            context.close()
            browser.close()

    assert measured["found"], "תא הכוונה לא רונדר — הטסט לא בדק דבר"
    # לא נוצר אלמנט: המחרוזת נשארה טקסט, לא markup.
    assert measured["childElements"] == 0
    assert measured["scriptsWithPayload"] == 0
    assert measured["pwned"] is False
    # ועדיין נגיש כטקסט מלא — escape ולא מחיקה.
    assert measured["title"] == hostile


def test_the_failure_messages_render_under_the_tool_table(page):
    """הפאנל שייך לטאב הבריאות, ולא לטאב רביעי."""
    page.click('button.mcp-tab[data-panel="health"]')
    page.wait_for_timeout(150)
    text = page.inner_text('.mcp-panel[data-panel="health"]')

    assert len(page.query_selector_all("button.mcp-tab")) == 3
    assert "lines.1" in text
    assert "Input should be a valid integer" in text
    assert "לא ניתן לטעון" not in text, "הודעה חסרה הוצגה ככשל"


def test_the_multiline_error_message_wraps_instead_of_stretching_the_table(page):
    """ההודעה של Pydantic היא רב-שורתית ובעלת מקטעים ארוכים בלי רווח.

    בלי ``overflow-wrap`` היא הייתה מותחת את הטבלה על פני המסך. זו תכונת
    פריסה — היא קיימת רק אחרי שהדפדפן חישב אותה.
    """
    page.click('button.mcp-tab[data-panel="health"]')
    page.wait_for_timeout(150)

    measured = page.evaluate("""() => {
        const cell = document.querySelector('.mcp-errmsg');
        const style = getComputedStyle(cell);
        return {
            whiteSpace: style.whiteSpace,
            overflowWrap: style.overflowWrap,
            lines: cell.getClientRects().length,
            docWidth: document.documentElement.scrollWidth,
            viewport: document.documentElement.clientWidth,
        };
    }""")

    assert measured["whiteSpace"] == "pre-wrap"
    assert measured["overflowWrap"] == "anywhere"
    assert measured["docWidth"] <= measured["viewport"] + 1, measured


def test_the_outbound_links_open_safely_in_a_new_tab(page):
    page.click('button.mcp-tab[data-panel="navigation"]')
    page.wait_for_timeout(150)

    links = page.evaluate("""() => [...document.querySelectorAll('a.mcp-outlink')].map(a => ({
        href: a.href, target: a.target, rel: a.rel,
    }))""")

    assert len(links) == 2
    for link in links:
        assert link["href"] in POSTHOG_LINKS.values()
        assert link["target"] == "_blank"
        assert "noopener" in link["rel"] and "noreferrer" in link["rel"]


def test_clicking_a_clipped_intent_opens_a_modal_with_the_full_text(live_server):
    """הקיצוץ הוא של התצוגה; המודאל הוא איך מגיעים לטקסט המלא.

    נמדד בדפדפן ולא ב-DOM המרונדר, כי המודאל נבנה כולו ב-JS: השרת שולח
    אותו ריק ומוסתר.
    """
    with _browser_page(live_server) as page:
        page.click('button.mcp-tab[data-panel="navigation"]')
        page.wait_for_timeout(150)
        # ``open`` ולא ``hidden``: זהו ``<dialog>`` נייטיב, והמצב שלו הוא
        # מה שהדפדפן מדווח — לא מחלקה או תכונה שאנחנו מתחזקים.
        before = page.evaluate("() => document.getElementById('mcpIntentModal').open")
        page.click(".mcp-clip")
        page.wait_for_timeout(150)
        opened = page.evaluate("""() => {
            const modal = document.getElementById('mcpIntentModal');
            const text = document.getElementById('mcpIntentModalText');
            return {
                open: modal.open,
                text: text.textContent,
                childElements: text.children.length,
                focusOnClose: document.activeElement.id,
            };
        }""")
        page.click("#mcpIntentModalClose")
        page.wait_for_timeout(150)
        closed = page.evaluate("""() => ({
            open: document.getElementById('mcpIntentModal').open,
            focusIsClip: document.activeElement.classList.contains('mcp-clip'),
        })""")

    assert before is False, "המודאל היה פתוח עוד לפני הלחיצה"
    assert opened["open"] is True
    assert opened["text"] == NAV_ROWS[0]["intent"]
    # נכתב עם ``textContent`` — אין אלמנטים בפנים גם על טקסט שנראה כמו תגית.
    assert opened["childElements"] == 0
    assert opened["focusOnClose"] == "mcpIntentModalClose"
    assert closed["open"] is False
    # הפוקוס חזר לכפתור שפתח — ``<dialog>`` עושה את זה לבד, בלי קוד משלנו.
    assert closed["focusIsClip"] is True


def test_a_hostile_intent_stays_text_inside_the_modal_too(live_server):
    """המודאל הוא מסלול שני לאותו טקסט, ולכן הוא צריך את אותה הוכחה.

    ה-escape של Jinja שומר על **הטבלה**; המודאל נבנה ב-JS, ולכן שם מה
    שמגן הוא ``textContent``. שני מסלולים, שתי בדיקות.
    """
    hostile = "<img src=x onerror=window.__pwned=1>"
    with _hostile_intent(hostile), _browser_page(live_server) as page:
        page.click('button.mcp-tab[data-panel="navigation"]')
        page.wait_for_timeout(150)
        page.click(".mcp-clip")
        page.wait_for_timeout(200)
        measured = page.evaluate("""() => {
            const text = document.getElementById('mcpIntentModalText');
            return {
                text: text.textContent,
                childElements: text.children.length,
                images: document.querySelectorAll('#mcpIntentModal img').length,
                pwned: window.__pwned === 1,
            };
        }""")

    assert measured["text"] == hostile
    assert measured["childElements"] == 0
    assert measured["images"] == 0
    assert measured["pwned"] is False


def test_the_banner_stays_quiet_on_a_first_visit(live_server):
    """בביקור ראשון הכול "חדש", ומספר כזה אינו אומר דבר."""
    with _browser_page(live_server, local_storage=None) as page:
        page.wait_for_timeout(200)
        measured = page.evaluate("""() => ({
            hidden: document.getElementById('mcpFreshBanner').hidden,
            stored: localStorage.getItem('mcpFailuresLastSeenAt'),
        })""")

    assert measured["hidden"] is True
    # אבל הביקור כן נרשם, אחרת הבא אחריו גם הוא יהיה "ראשון".
    assert measured["stored"] is not None


def test_the_banner_counts_only_failures_newer_than_the_last_visit(live_server):
    """זו כל הנקודה: החלון של 30 יום מזיז שורות החוצה, ולכן המספר הכולל
    יורד מעצמו ואינו יכול לשמש איתות. ההשוואה היא מול חותמת."""
    # אחרי השורה הישנה (03.09) ולפני החדשה (05.09) — כלומר אחת חדשה.
    with _browser_page(live_server, local_storage="2026-09-04T00:00:00.000Z") as page:
        page.wait_for_timeout(200)
        measured = page.evaluate("""() => ({
            hidden: document.getElementById('mcpFreshBanner').hidden,
            text: document.getElementById('mcpFreshText').textContent,
            stored: localStorage.getItem('mcpFailuresLastSeenAt'),
        })""")

    assert measured["hidden"] is False
    assert "אחת" in measured["text"], measured["text"]
    # נשמרה החדשה ביותר, ולכן רענון מיידי כבר לא יציג את הבאנר.
    assert measured["stored"].startswith("2026-09-05")


def test_nothing_is_new_when_the_last_visit_is_after_every_failure(live_server):
    with _browser_page(live_server, local_storage="2026-09-30T00:00:00.000Z") as page:
        page.wait_for_timeout(200)
        hidden = page.evaluate("() => document.getElementById('mcpFreshBanner').hidden")

    assert hidden is True


def test_a_truncated_table_makes_the_banner_say_at_least(live_server):
    """הבאנר סופר שורות ב-DOM, והטבלה חתוכה בתקרה.

    כשכל השורות שהוצגו חדשות **וידוע שיש עוד** — המספר שנספר הוא רצפה
    ולא ספירה, ולהצהיר עליו כמספר מדויק זה להמציא נתון. הניסוח משתנה,
    ולא הספירה: אין דרך לספור מה שהשאילתה לא החזירה.
    """
    with _truncated_failures():
        with _browser_page(live_server, local_storage="2026-01-01T00:00:00.000Z") as page:
            page.wait_for_timeout(200)
            measured = page.evaluate("""() => ({
                hidden: document.getElementById('mcpFreshBanner').hidden,
                text: document.getElementById('mcpFreshText').textContent,
                hasMore: document.getElementById('mcpFreshBanner').dataset.hasMore,
            })""")

    assert measured["hasMore"] == "1", "התבנית לא העבירה את הסימון לדפדפן"
    assert measured["hidden"] is False
    assert measured["text"].startswith("לפחות "), measured["text"]
    assert "2" in measured["text"], measured["text"]


def test_a_complete_table_states_the_count_without_hedging(live_server):
    """התמונה ההפוכה: הטבלה שלמה, ולכן המספר מדויק ואין "לפחות".

    בלי הטסט הזה, ניסוח שמוסיף "לפחות" תמיד היה עובר את הטסט שמעל.
    """
    with _browser_page(live_server, local_storage="2026-01-01T00:00:00.000Z") as page:
        page.wait_for_timeout(200)
        measured = page.evaluate("""() => ({
            text: document.getElementById('mcpFreshText').textContent,
            hasMore: document.getElementById('mcpFreshBanner').dataset.hasMore,
        })""")

    assert measured["hasMore"] == "0"
    assert not measured["text"].startswith("לפחות"), measured["text"]
    assert measured["text"].startswith("2 שגיאות חדשות"), measured["text"]


def test_a_failed_page_load_still_shuts_the_browser_down(live_server):
    """הכשל שמנהל ההקשר נועד למנוע: נפילה **אחרי** שהדפדפן כבר עלה.

    כשהניקוי ישב אצל הקורא — ב-``finally`` שאחרי הקריאה — נפילה בתוך
    ההרמה עצמה דילגה עליו לגמרי, ודפדפן שלם וסשן Playwright נשארו תלויים
    עד סוף התהליך. כאן ``goto`` פונה לפורט סגור, כלומר הדפדפן עולה ואז
    הטעינה נכשלת, ונמדד שהסגירה בכל זאת רצה.
    """
    _, session_cookie = live_server
    stopped = []
    real_factory = sync_playwright

    class _Recorder:
        """עוטף את המפעל האמיתי ורושם מתי ``stop`` נקרא — בלי להחליף אותו."""

        def __init__(self, inner):
            self._inner = inner

        def start(self):
            pw = self._inner.start()
            original = pw.stop

            def stop():
                stopped.append(True)
                original()

            pw.stop = stop
            return pw

    patch = pytest.MonkeyPatch()
    patch.setattr(sys.modules[__name__], "sync_playwright", lambda: _Recorder(real_factory()))
    try:
        with pytest.raises(Exception):
            # פורט 9 סגור, ולכן ``goto`` נכשל אחרי ``launch``.
            with _browser_page(("http://127.0.0.1:9", session_cookie)):
                pass  # pragma: no cover
    finally:
        patch.undo()

    assert stopped == [True], "‏Playwright לא נסגר אחרי כשל בטעינת העמוד"


# --------------------------------------------------------------------------
# העתקה
#
# בדיקת שרת יכולה לאמת שה-``data-v`` נכתב. היא **אינה** יכולה לאמת שמשהו
# הגיע ללוח: ``navigator.clipboard`` חי רק בדפדפן, והוא גם דורש secure
# context והרשאה. לכן כל בדיקה כאן **קוראת את הלוח בחזרה** — ערך ההחזרה
# של הכתיבה אינו אימות שלה.
# --------------------------------------------------------------------------


def _clipboard(page):
    return page.evaluate("() => navigator.clipboard.readText()")


def _copy_all(page, table):
    page.click(f'.mcp-copy[data-copy-for="{table}"] .mcp-copy-main')
    page.wait_for_timeout(250)
    return _clipboard(page)


def _shown_sessions(page):
    return page.eval_on_selector_all(
        '[data-copy-table="sessions"] tbody tr td:last-child',
        "cells => cells.map(cell => cell.textContent.trim())",
    )


def test_copying_a_table_puts_a_markdown_table_on_the_clipboard(live_server):
    """היעד הוא הדבקה לצ'אט עם סוכן, ולכן הפורמט הוא טבלת Markdown עם כותרת."""
    with _many_sessions(), _browser_page(live_server, query="?tab=navigation") as page:
        text = _copy_all(page, "sessions")

    lines = text.split("\n")

    assert lines[0].startswith("| התחיל |"), lines[0]
    assert set(lines[1].replace("|", "").split()) == {"---"}, lines[1]
    body = [line for line in lines[2:] if line.startswith("|")]
    assert len(body) == _EXTRA_NAV_ROWS, body


def test_the_copy_takes_the_order_that_is_on_the_screen(live_server):
    """ההעתקה מכבדת את המיון מפני שהיא קוראת את ה-DOM, ולא את הסדר המקורי.

    סדר ברירת המחדל כאן הפוך לסדר של "זמן כולל, יורד", ולכן השוואה מול
    המסך מסוגלת ליפול — לא כמו השוואה מול רשימה קבועה בבדיקה.
    """
    query = "?tab=navigation&sessions_sort=total_ms&sessions_dir=desc"
    with _many_sessions(), _browser_page(live_server, query=query) as page:
        shown = _shown_sessions(page)
        text = _copy_all(page, "sessions")

    copied = [
        line.split("|")[-2].strip()
        for line in text.split("\n")
        if line.startswith("|")
    ][2:]

    assert shown[0] == f"ses_{_EXTRA_NAV_ROWS - 1}", f"הטבלה לא מוינה: {shown}"
    assert copied == shown, f"ההעתקה לא בסדר התצוגה\nמסך: {shown}\nלוח: {copied}"


def test_the_copied_numbers_carry_no_units_and_the_unit_sits_in_the_header(live_server):
    """מי שמדביק לניתוח רוצה מספרים. ``2574ms`` אינו מספר."""
    with _many_sessions(), _browser_page(live_server, query="?tab=navigation") as page:
        text = _copy_all(page, "sessions")

    header = text.split("\n")[0]
    body = [line for line in text.split("\n")[2:] if line.startswith("|")]

    assert "זמן כולל (ms)" in header, header
    for line in body:
        assert "ms" not in line, line


def test_the_caveat_travels_with_the_copy(live_server):
    """בלי זה, מי שמדביק מספרי סשנים לצ'אט מאבד בדיוק את הסייג שהעמוד
    נבנה כדי לשמר."""
    with _many_sessions(), _browser_page(live_server, query="?tab=navigation") as page:
        text = _copy_all(page, "sessions")

    assert "> אין להשוות בין סשנים" in text, text[-200:]
    assert "מודד עלות, לא איכות" in text


def test_the_menu_never_offers_more_rows_than_the_table_holds(live_server):
    """הרשימה נבנית מהשורות שיש, ולא מרשימה קשיחה שצריך לסנכרן."""
    with _many_sessions(), _browser_page(live_server, query="?tab=navigation") as page:
        page.click('.mcp-copy[data-copy-for="sessions"] .mcp-copy-more')
        page.wait_for_timeout(150)
        labels = page.eval_on_selector_all(
            '.mcp-copy[data-copy-for="sessions"] .mcp-copy-option',
            "items => items.map(item => item.textContent.trim())",
        )

    assert labels[0] == f"העתק הכל ({_EXTRA_NAV_ROWS})", labels
    assert labels[1:] == ["5 השורות הראשונות"], labels


def test_copying_n_rows_takes_the_first_n_of_the_current_order(live_server):
    query = "?tab=navigation&sessions_sort=total_ms&sessions_dir=desc"
    with _many_sessions(), _browser_page(live_server, query=query) as page:
        shown = _shown_sessions(page)
        page.click('.mcp-copy[data-copy-for="sessions"] .mcp-copy-more')
        page.wait_for_timeout(150)
        page.click('.mcp-copy[data-copy-for="sessions"] .mcp-copy-option:last-child')
        page.wait_for_timeout(250)
        text = _clipboard(page)

    copied = [
        line.split("|")[-2].strip()
        for line in text.split("\n")
        if line.startswith("|")
    ][2:]

    assert copied == shown[:5], f"מסך: {shown}\nלוח: {copied}"


def test_a_pipe_or_a_newline_in_agent_text_does_not_break_the_table(live_server):
    """שני התווים שמפרקים טבלת Markdown, בטקסט שסוכן חיצוני כתב."""
    with _one_missing_capability(), _browser_page(live_server, query="?tab=missing") as page:
        page.click("td.mcp-capability button.mcp-copy-cell")
        page.wait_for_timeout(250)
        text = _clipboard(page)

    # העתקת תא בודד מעתיקה את הטקסט **כמו שהוא**: אין כאן טבלה לשבור.
    assert text == CAPABILITY_TEXT, repr(text)


def test_the_icon_only_button_copies_the_whole_capability(live_server):
    with _one_missing_capability(), _browser_page(live_server, query="?tab=missing") as page:
        label = page.get_attribute("td.mcp-capability button.mcp-copy-cell", "aria-label")
        page.click("td.mcp-capability button.mcp-copy-cell")
        page.wait_for_timeout(250)
        text = _clipboard(page)
        icon = page.get_attribute("td.mcp-capability button.mcp-copy-cell i", "class")

    assert label, "כפתור אייקון בלי aria-label הוא כפתור אילם"
    assert text == CAPABILITY_TEXT
    assert "fa-check" in icon, "אין שום חיווי שההעתקה קרתה"


def test_the_copy_menu_is_not_clipped_by_the_card_that_holds_the_table(live_server):
    """הכרטיס גולל את הטבלה, ותפריט שנפתח בתוך אזור גלילה נחתך בו.

    המדידה היא מול המלבנים עצמם ולא מול "נראה בסדר": תפריט שחציו התחתון
    מעבר לגבול הכרטיס הוא תפריט שאי אפשר ללחוץ על האופציה האחרונה שלו.
    """
    with _many_sessions(), _browser_page(
        live_server, viewport=PHONE_VIEWPORT, query="?tab=navigation"
    ) as page:
        page.click('.mcp-copy[data-copy-for="sessions"] .mcp-copy-more')
        page.wait_for_timeout(200)
        measured = page.evaluate("""() => {
            const control = document.querySelector('.mcp-copy[data-copy-for="sessions"]');
            const menu = control.querySelector('.mcp-copy-menu');
            const rect = menu.getBoundingClientRect();
            let node = menu.parentElement;
            let clippedBy = null;
            while (node && node !== document.body) {
                const style = getComputedStyle(node);
                const clips = style.overflowX !== 'visible' || style.overflowY !== 'visible';
                if (clips) {
                    const box = node.getBoundingClientRect();
                    if (rect.bottom > box.bottom + 1 || rect.top < box.top - 1) {
                        clippedBy = node.className;
                    }
                    break;
                }
                node = node.parentElement;
            }
            return {
                clippedBy: clippedBy,
                height: rect.height,
                docWidth: document.documentElement.scrollWidth,
                viewport: document.documentElement.clientWidth,
            };
        }""")

    assert measured["height"] > 0, "התפריט לא נפתח — הבדיקה לא בדקה דבר"
    assert measured["clippedBy"] is None, f"התפריט נחתך על ידי {measured['clippedBy']}"
    assert measured["docWidth"] <= measured["viewport"] + 1, measured


def test_opening_the_menu_does_not_move_the_table(live_server):
    """``position: absolute`` — התפריט אינו משתתף בזרימה. במסך צר זה ההבדל
    בין תפריט לבין טבלה שקופצת למטה."""
    with _many_sessions(), _browser_page(
        live_server, viewport=PHONE_VIEWPORT, query="?tab=navigation"
    ) as page:
        box = "() => { const t = document.querySelector('[data-copy-table=\"sessions\"]');" \
              " const r = t.getBoundingClientRect(); return {top: r.top, width: r.width}; }"
        before = page.evaluate(box)
        page.click('.mcp-copy[data-copy-for="sessions"] .mcp-copy-more')
        page.wait_for_timeout(200)
        after = page.evaluate(box)

    assert abs(after["top"] - before["top"]) < 1, (before, after)
    assert abs(after["width"] - before["width"]) < 1, (before, after)


def test_the_copy_control_only_appears_once_javascript_is_running(live_server):
    """בשרת הוא נשלח ``hidden``. אם הוא נשאר כך — אין העתקה, וכפתור מת
    גרוע מכפתור שאינו שם."""
    with _many_sessions(), _browser_page(live_server, query="?tab=navigation") as page:
        visible = page.is_visible('.mcp-copy[data-copy-for="sessions"] .mcp-copy-main')
        label = page.inner_text('.mcp-copy[data-copy-for="sessions"] .mcp-copy-label')

    assert visible
    assert label == f"העתק הכל ({_EXTRA_NAV_ROWS})", label


def test_two_quick_clicks_leave_the_button_back_in_its_resting_state(live_server):
    """שתי לחיצות מהירות השאירו את הכפתור על סימן הווי לתמיד.

    הלחיצה השנייה שמרה כ"מקורי" את מה שהראשונה כתבה, ואף אחת לא ביטלה את
    הטיימר של קודמתה: הטיימר הראשון החזיר את המצב האמיתי, והשני דרס אותו
    חזרה בסימן הווי — אחרי שכבר לא היה מי שישחזר.

    ההמתנה כאן ארוכה משני משכי ההבהוב יחד, אחרת הבדיקה מודדת את החלון שבו
    ההבהוב עדיין אמור להיות מוצג ועוברת מהסיבה הלא נכונה.
    """
    with _many_sessions(), _browser_page(live_server, query="?tab=navigation") as page:
        control = '.mcp-copy[data-copy-for="sessions"]'
        resting = page.inner_text(f"{control} .mcp-copy-label")

        page.click(f"{control} .mcp-copy-main")
        page.wait_for_timeout(300)
        page.click(f"{control} .mcp-copy-main")
        page.wait_for_timeout(2600)

        icon = page.get_attribute(f"{control} .mcp-copy-main i", "class")
        label = page.inner_text(f"{control} .mcp-copy-label")

    assert resting == f"העתק הכל ({_EXTRA_NAV_ROWS})", resting
    assert "fa-copy" in icon, f"האייקון נתקע על {icon}"
    assert label == resting, f"התווית נתקעה על {label!r}"


def test_two_quick_clicks_on_a_row_icon_also_settle_back(live_server):
    """אותו כשל בדיוק בכפתור שבשורה, שם הוא בולט יותר: אייקון ווי קבוע
    נראה כמו "כבר העתקתי את זה" בכל פעם שפותחים את העמוד."""
    with _one_missing_capability(), _browser_page(live_server, query="?tab=missing") as page:
        button = "td.mcp-capability button.mcp-copy-cell"
        page.click(button)
        page.wait_for_timeout(300)
        page.click(button)
        page.wait_for_timeout(2600)
        icon = page.get_attribute(f"{button} i", "class")

    assert "fa-copy" in icon, f"האייקון נתקע על {icon}"


# --------------------------------------------------------------------------
# סימון "טופל" / "נדחה"
#
# הסימון נשמר ב-``localStorage`` של הדפדפן, ולכן **רק** דפדפן יכול להוכיח
# שהוא עובד. בדיקת שרת רואה כפתור; היא אינה יכולה לראות שהלחיצה נשמרה, ששרדה
# רענון, ושלחיצה שלא נשמרה אינה מוצגת כאילו כן.
# --------------------------------------------------------------------------

#: המפתח שהשורה של ``_one_missing_capability`` מקבלת: זמן הדיווח והסשן.
MARK_ROW_KEY = "2026-09-02T10:00:00Z|ses_x"
MARK_STORAGE_KEY = "mcpMissingMarks"
#: אותה תקרה שבתבנית. הטסט מייצר אותה, ולכן הוא נשבר אם מישהו משנה אותה
#: בצד אחד בלבד — וזה בדיוק מה שצריך לקרות.
MARK_LIMIT = 500


def _marks(page):
    """מה ששמור **באחסון** — לא מה שמצויר על המסך."""
    return page.evaluate(
        "() => { try { return JSON.parse(localStorage.getItem('%s')) || {}; }"
        " catch (e) { return {}; } }" % MARK_STORAGE_KEY
    )


def _mark_state(page):
    """מה שמצויר: המצב על השורה, ואיזה כפתור לחוץ."""
    return page.evaluate("""() => {
        const row = document.querySelector('tr[data-cap-key]');
        return {
            row: row ? (row.dataset.mark || '') : null,
            pressed: [...document.querySelectorAll('.mcp-mark-btn')]
                .filter(b => b.getAttribute('aria-pressed') === 'true')
                .map(b => b.dataset.mark),
            noteVisible: !document.getElementById('mcpMarkNote').hidden,
        };
    }""")


def _mark_button(value):
    return f'tr[data-cap-key] .mcp-mark-btn[data-mark="{value}"]'


def test_marking_a_capability_as_handled_survives_a_reload(live_server):
    """זה כל הפיצ'ר: סימון שנעלם ברענון אינו סימון.

    שתי הטענות נפרדות בכוונה — מה שנשמר באחסון, ומה שמצויר אחרי הטעינה
    מחדש. סימון שנכתב ולא נקרא חזרה היה עובר בדיקה שבודקת רק את הראשון.
    """
    with _one_missing_capability(), _browser_page(live_server, query="?tab=missing") as page:
        page.click(_mark_button("handled"))
        page.wait_for_timeout(200)
        stored = _marks(page)

        page.reload(wait_until="domcontentloaded")
        page.wait_for_timeout(400)
        after = _mark_state(page)

    assert stored == {MARK_ROW_KEY: "handled"}, stored
    assert after["row"] == "handled"
    assert after["pressed"] == ["handled"]


def test_clicking_the_active_mark_again_clears_it(live_server):
    """בלי זה אי אפשר לחזור מ"נדחה" ל"לא טופל" אלא בניקוי אחסון ביד."""
    with _one_missing_capability(), _browser_page(live_server, query="?tab=missing") as page:
        page.click(_mark_button("rejected"))
        page.wait_for_timeout(200)
        page.click(_mark_button("rejected"))
        page.wait_for_timeout(200)
        state = _mark_state(page)
        stored = _marks(page)

    assert state["row"] == ""
    assert state["pressed"] == []
    # נמחק מהאחסון ולא נשמר כערך ריק: רשומה ריקה היא רשומה שתיספר בתקרה.
    assert stored == {}, stored


def test_the_two_marks_replace_each_other(live_server):
    """דיווח אינו יכול להיות גם טופל וגם נדחה."""
    with _one_missing_capability(), _browser_page(live_server, query="?tab=missing") as page:
        page.click(_mark_button("handled"))
        page.wait_for_timeout(200)
        page.click(_mark_button("rejected"))
        page.wait_for_timeout(200)
        state = _mark_state(page)
        stored = _marks(page)

    assert state["pressed"] == ["rejected"]
    assert stored == {MARK_ROW_KEY: "rejected"}, stored


def test_a_mark_that_was_not_stored_is_not_drawn_as_stored(live_server):
    """האחסון חסום ← הכפתור **אינו** נדלק, והעמוד אומר זאת.

    זו ההבחנה שכל הקוד הזה עומד עליה: "``setItem`` לא זרק" אינו "נשמר",
    ולכן מה שמצויר הוא מה שנקרא חזרה מהאחסון. בלי הקריאה החוזרת הלחיצה
    הייתה נראית בדיוק כמו לחיצה שנשמרה — עד הרענון הבא, שבו הסימון נעלם
    בלי הסבר.
    """
    refuse = (
        "(function(){var real=Storage.prototype.setItem;"
        "Storage.prototype.setItem=function(key,value){"
        f"if(key==='{MARK_STORAGE_KEY}'){{throw new Error('QuotaExceededError');}}"
        "return real.call(this,key,value);};})();"
    )
    with _one_missing_capability(), _browser_page(
        live_server, query="?tab=missing", init_script=refuse
    ) as page:
        page.click(_mark_button("handled"))
        page.wait_for_timeout(200)
        state = _mark_state(page)
        note = page.inner_text("#mcpMarkNote")

    assert state["pressed"] == [], "לחיצה שלא נשמרה הוצגה כאילו נשמרה"
    assert state["row"] == ""
    assert state["noteVisible"], "הכישלון נבלע בשקט"
    assert "לא נשמר" in note


def test_the_stored_marks_do_not_grow_past_their_limit(live_server):
    """דיווח נושר מהשאילתה אחרי 90 יום, אבל הסימון שלו נשאר באחסון.

    בלי תקרה זו צמיחה בלי סוף. הבדיקה מוודאת גם את הצד השני: הסימון שנלחץ
    זה עתה **שורד** את הגזירה — אחרת הגזירה הייתה מוחקת בדיוק את מה
    שהמשתמש ביקש, והלחיצה הייתה מדווחת ככשל.
    """
    seed = (
        "(function(){try{var marks={};"
        f"for(var i=0;i<{MARK_LIMIT};i++){{marks['2020-01-01T00:00:00Z|old'+i]='handled';}}"
        f"localStorage.setItem('{MARK_STORAGE_KEY}',JSON.stringify(marks));"
        "}catch(e){}})();"
    )
    with _one_missing_capability(), _browser_page(
        live_server, query="?tab=missing", init_script=seed
    ) as page:
        page.click(_mark_button("handled"))
        page.wait_for_timeout(200)
        stored = _marks(page)
        state = _mark_state(page)

    assert len(stored) == MARK_LIMIT, f"{len(stored)} רשומות באחסון"
    assert stored.get(MARK_ROW_KEY) == "handled", "הסימון החדש נגזר"
    assert state["pressed"] == ["handled"]
    assert not state["noteVisible"]
