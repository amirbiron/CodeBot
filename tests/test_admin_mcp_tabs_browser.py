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
def live_server():
    """מריץ את הוובאפ האמיתי עם שירות מזויף, בלי לגעת ברשת.

    כל שינוי גלובלי עובר דרך ``MonkeyPatch`` ומשוחזר בסיום, והשרת נעצר
    במפורש. pytest מריץ את כל הקבצים בתהליך אחד, ולכן מצב שלא שוחזר
    היה מדליף לטסטים אחרים ויוצר תלות בסדר.
    """
    import webapp.app as app_mod
    from werkzeug.serving import make_server

    fake = types.SimpleNamespace(
        get_dashboard=lambda: {
            mcp.ENDPOINT_TOOL_HEALTH: EndpointResult(rows=list(HEALTH_ROWS)),
            mcp.ENDPOINT_TOOL_FAILURES: EndpointResult(rows=list(FAILURE_ROWS)),
            # ``_nav_rows()`` ולא ``NAV_ROWS`` ישירות: כך טסט יכול להחליף את
            # השורות **בשרת** לפני הרינדור, במקום לשתול ערך ב-DOM אחרי כן.
            mcp.ENDPOINT_NAVIGATION_COST: EndpointResult(rows=_nav_rows(), total=10),
            mcp.ENDPOINT_MISSING_CAPABILITIES: EndpointResult(rows=[]),
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


@pytest.fixture
def page(live_server):
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
        # מודאל ה-onboarding של הוובאפ נפתח למשתמש חדש וחוסם קליקים
        p.add_init_script(
            "try{localStorage.setItem('welcomeModalSeen','1');"
            "localStorage.setItem('onboarding_completed','1');}catch(e){}"
        )
        p.goto(f"{base_url}/admin/mcp", wait_until="domcontentloaded")
        p.wait_for_timeout(400)
        p.evaluate(
            "document.querySelectorAll('.welcome-modal, .welcome-modal__backdrop, #welcomeModal')"
            ".forEach(e => e.remove())"
        )
        try:
            yield p
        finally:
            context.close()
            browser.close()


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
    page.set_viewport_size({"width": 390, "height": 844})
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
    page.set_viewport_size({"width": 390, "height": 844})
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


def _fresh_page(live_server, local_storage=None):
    """פותח את העמוד בהקשר דפדפן נקי, אופציונלית עם ערך ב-localStorage.

    ``add_init_script`` רץ **לפני** קוד העמוד, ולכן הערך כבר שם כשהבאנר
    מחשב. כתיבה אחרי ``goto`` הייתה מגיעה מאוחר מדי והטסט היה בודק כלום.
    """
    base_url, session_cookie = live_server
    executable = _find_chromium()
    pw = sync_playwright().start()
    try:
        browser = (
            pw.chromium.launch(executable_path=executable)
            if executable
            else pw.chromium.launch()
        )
    except Exception as exc:  # pragma: no cover
        pw.stop()
        pytest.skip(f"אין Chromium זמין: {exc}")
    context = browser.new_context(viewport={"width": 1280, "height": 900})
    context.add_cookies([{
        "name": "session", "value": session_cookie,
        "domain": "127.0.0.1", "path": "/",
    }])
    page = context.new_page()
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
    page.goto(f"{base_url}/admin/mcp", wait_until="domcontentloaded")
    page.wait_for_timeout(400)
    page.evaluate(
        "document.querySelectorAll('.welcome-modal, .welcome-modal__backdrop, #welcomeModal')"
        ".forEach(e => e.remove())"
    )
    return pw, browser, context, page


def test_clicking_a_clipped_intent_opens_a_modal_with_the_full_text(live_server):
    """הקיצוץ הוא של התצוגה; המודאל הוא איך מגיעים לטקסט המלא.

    נמדד בדפדפן ולא ב-DOM המרונדר, כי המודאל נבנה כולו ב-JS: השרת שולח
    אותו ריק ומוסתר.
    """
    pw, browser, context, page = _fresh_page(live_server)
    try:
        page.click('button.mcp-tab[data-panel="navigation"]')
        page.wait_for_timeout(150)
        before = page.evaluate("() => document.getElementById('mcpIntentModal').hidden")
        page.click(".mcp-clip")
        page.wait_for_timeout(150)
        opened = page.evaluate("""() => {
            const modal = document.getElementById('mcpIntentModal');
            const text = document.getElementById('mcpIntentModalText');
            return {
                hidden: modal.hidden,
                text: text.textContent,
                childElements: text.children.length,
                focusOnClose: document.activeElement.id,
            };
        }""")
        # Escape סוגר, והפוקוס חוזר לכפתור שפתח.
        page.keyboard.press("Escape")
        page.wait_for_timeout(150)
        closed = page.evaluate("""() => ({
            hidden: document.getElementById('mcpIntentModal').hidden,
            focusIsClip: document.activeElement.classList.contains('mcp-clip'),
        })""")
    finally:
        context.close()
        browser.close()
        pw.stop()

    assert before is True, "המודאל היה פתוח עוד לפני הלחיצה"
    assert opened["hidden"] is False
    assert opened["text"] == NAV_ROWS[0]["intent"]
    # נכתב עם ``textContent`` — אין אלמנטים בפנים גם על טקסט שנראה כמו תגית.
    assert opened["childElements"] == 0
    assert opened["focusOnClose"] == "mcpIntentModalClose"
    assert closed["hidden"] is True
    assert closed["focusIsClip"] is True


def test_a_hostile_intent_stays_text_inside_the_modal_too(live_server):
    """המודאל הוא מסלול שני לאותו טקסט, ולכן הוא צריך את אותה הוכחה.

    ה-escape של Jinja שומר על **הטבלה**; המודאל נבנה ב-JS, ולכן שם מה
    שמגן הוא ``textContent``. שני מסלולים, שתי בדיקות.
    """
    hostile = "<img src=x onerror=window.__pwned=1>"
    with _hostile_intent(hostile):
        pw, browser, context, page = _fresh_page(live_server)
    try:
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
    finally:
        context.close()
        browser.close()
        pw.stop()

    assert measured["text"] == hostile
    assert measured["childElements"] == 0
    assert measured["images"] == 0
    assert measured["pwned"] is False


def test_the_banner_stays_quiet_on_a_first_visit(live_server):
    """בביקור ראשון הכול "חדש", ומספר כזה אינו אומר דבר."""
    pw, browser, context, page = _fresh_page(live_server, local_storage=None)
    try:
        page.wait_for_timeout(200)
        measured = page.evaluate("""() => ({
            hidden: document.getElementById('mcpFreshBanner').hidden,
            stored: localStorage.getItem('mcpFailuresLastSeenAt'),
        })""")
    finally:
        context.close()
        browser.close()
        pw.stop()

    assert measured["hidden"] is True
    # אבל הביקור כן נרשם, אחרת הבא אחריו גם הוא יהיה "ראשון".
    assert measured["stored"] is not None


def test_the_banner_counts_only_failures_newer_than_the_last_visit(live_server):
    """זו כל הנקודה: החלון של 30 יום מזיז שורות החוצה, ולכן המספר הכולל
    יורד מעצמו ואינו יכול לשמש איתות. ההשוואה היא מול חותמת."""
    # אחרי השורה הישנה (03.09) ולפני החדשה (05.09) — כלומר אחת חדשה.
    pw, browser, context, page = _fresh_page(live_server, local_storage="2026-09-04T00:00:00.000Z")
    try:
        page.wait_for_timeout(200)
        measured = page.evaluate("""() => ({
            hidden: document.getElementById('mcpFreshBanner').hidden,
            text: document.getElementById('mcpFreshText').textContent,
            stored: localStorage.getItem('mcpFailuresLastSeenAt'),
        })""")
    finally:
        context.close()
        browser.close()
        pw.stop()

    assert measured["hidden"] is False
    assert "אחת" in measured["text"], measured["text"]
    # נשמרה החדשה ביותר, ולכן רענון מיידי כבר לא יציג את הבאנר.
    assert measured["stored"].startswith("2026-09-05")


def test_nothing_is_new_when_the_last_visit_is_after_every_failure(live_server):
    pw, browser, context, page = _fresh_page(live_server, local_storage="2026-09-30T00:00:00.000Z")
    try:
        page.wait_for_timeout(200)
        hidden = page.evaluate("() => document.getElementById('mcpFreshBanner').hidden")
    finally:
        context.close()
        browser.close()
        pw.stop()

    assert hidden is True
