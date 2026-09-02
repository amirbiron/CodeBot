"""בדיקת אינטראקציה אמיתית לטאבים של ``/admin/mcp``.

בדיקת שרת מאמתת שה-HTML נוצר. היא **אינה** יכולה לאמת שהלחיצה עובדת:
ה-JS שמחליף פאנלים רץ רק בדפדפן, ומחלקת ``active`` על האלמנט הנכון היא
הדבר היחיד שמפריד בין "שלושה טאבים" לבין "טאב אחד ושני אלמנטים מתים".

הטסט מדולג בשקט כשאין Chromium — הוא נועד לרוץ מקומית ובכל סביבה שיש בה
דפדפן, ולא להפיל CI שאין בו אחד.
"""

from __future__ import annotations

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
        "failed_at": "2026-09-02T00:43:14.487000Z",
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
        "failed_at": "2026-09-01T21:01:34.441000Z",
        "tool": "codekeeper_get_repo_file", "client": None,
        "error_type": "ValidationError", "error_message": None,
        "session": "ses_y",
    },
]
POSTHOG_LINKS = {
    "intent_clusters": "https://us.posthog.com/project/567754/mcp-analytics/intent-clustering",
    "sessions": "https://us.posthog.com/project/567754/mcp-analytics/sessions",
}


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
            mcp.ENDPOINT_NAVIGATION_COST: EndpointResult(rows=list(NAV_ROWS), total=10),
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
    """הטבלה גדלה משמונה עמודות לעשר, והכוונה היא טקסט חופשי באורך לא ידוע.

    זה בדיוק מה שמפיל פריסות: הרוחב נקבע בזמן הרינדור, ולא ב-CSS שנקרא.
    ההבטחה היא ש**הכרטיס** גולל ולא גוף העמוד, ואת זה אפשר למדוד רק בדפדפן.
    """
    page.click('button.mcp-tab[data-panel="navigation"]')
    page.wait_for_timeout(150)

    measured = page.evaluate("""() => {
        const panel = '.mcp-panel[data-panel="navigation"]';
        const wrap = document.querySelector(panel + ' .mcp-table-wrapper');
        return {
            docWidth: document.documentElement.scrollWidth,
            viewport: document.documentElement.clientWidth,
            wrapperScrolls: wrap.scrollWidth > wrap.clientWidth,
            overflowX: getComputedStyle(wrap).overflowX,
        };
    }""")

    assert measured["docWidth"] <= measured["viewport"] + 1, measured
    assert measured["overflowX"] == "auto"


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


def test_an_intent_that_looks_like_markup_is_never_a_live_element(page):
    """``<script>`` בכוונה חייב להישאר טקסט — בדפדפן, לא רק במחרוזת.

    בדיקת שרת מוכיחה ש-Jinja עשה escape. רק הדפדפן מוכיח שמה שנבנה בפועל
    ב-DOM הוא צומת טקסט ולא אלמנט.
    """
    hostile = "<script>window.__pwned = 1</script>"
    measured = page.evaluate(
        """(hostile) => {
            const el = document.querySelector('.mcp-panel[data-panel="navigation"] .mcp-clip');
            el.setAttribute('title', hostile);
            return {
                pwned: window.__pwned === 1,
                childElements: el.children.length,
            };
        }""",
        hostile,
    )

    assert measured["pwned"] is False
    assert measured["childElements"] == 0


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
