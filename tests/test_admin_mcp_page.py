"""בדיקות למסך ``/admin/mcp``.

הבדיקות עוברות דרך אותו ממשק שהמשתמש עובר בו — בקשת HTTP וה-HTML שחוזר —
ולא דרך קריאה ישירה לפונקציות. הטענות נבדקות מול ה-DOM המרונדר.
"""

from __future__ import annotations

import types

import pytest
from bs4 import BeautifulSoup

import services.mcp_analytics_service as mcp
from services.mcp_analytics_service import EndpointResult

HEALTH_ROWS = [
    {
        "tool": "codekeeper_get_repo_file", "calls": 52, "errors": 2,
        "error_rate_pct": 3.8, "p50_ms": 169.0, "p95_ms": 612.0,
        "sessions": 8, "last_seen": "2026-09-02T08:16:17.587000Z",
    },
    {
        "tool": "codekeeper_get_file", "calls": 5, "errors": 1,
        "error_rate_pct": 20.0, "p50_ms": 150.0, "p95_ms": 4144.0,
        "sessions": 4, "last_seen": "2026-09-02T00:45:20.830000Z",
    },
]
NAV_ROWS = [
    {
        "session": "ses_01a0612c", "started": "2026-09-02T08:15:00.843000Z",
        "client": "claude-code", "calls": 15, "searches": 0, "file_reads": 14,
        "errors": 0, "total_ms": 2574.0, "total_sessions": 10,
    }
]


def _install(monkeypatch, health=None, navigation=None, missing=None):
    """מחליף את השירות כולו, כדי שהבדיקה לא תיגע ברשת ולא תישבר על נתונים."""
    fake = types.SimpleNamespace(
        get_dashboard=lambda: {
            mcp.ENDPOINT_TOOL_HEALTH: (
                health if health is not None else EndpointResult(rows=list(HEALTH_ROWS))
            ),
            mcp.ENDPOINT_NAVIGATION_COST: (
                navigation
                if navigation is not None
                else EndpointResult(rows=list(NAV_ROWS), total=10)
            ),
            mcp.ENDPOINT_MISSING_CAPABILITIES: (
                missing if missing is not None else EndpointResult(rows=[])
            ),
        }
    )
    monkeypatch.setattr(mcp, "get_mcp_analytics_service", lambda: fake)


@pytest.fixture
def client(monkeypatch):
    import webapp.app as app_mod

    # ``monkeypatch`` משחזר לבד בסיום. השמה ישירה הייתה מדליפה את המצב
    # לטסטים שרצים אחרי הקובץ הזה, ויוצרת תלות בסדר.
    monkeypatch.setattr(app_mod.app, "testing", True)
    monkeypatch.setitem(app_mod.app.config, "SECRET_KEY", "test")
    monkeypatch.setenv("ADMIN_USER_IDS", "1")
    with app_mod.app.test_client() as test_client:
        yield test_client


@pytest.fixture
def admin(client):
    with client.session_transaction() as sess:
        sess["user_id"] = 1
        sess["user_data"] = {"id": 1, "is_admin": True, "is_premium": False}
    return client


def _soup(response):
    return BeautifulSoup(response.get_data(as_text=True), "html.parser")


# --------------------------------------------------------------------------
# הרשאות
# --------------------------------------------------------------------------


def test_a_regular_user_is_refused(client, monkeypatch):
    _install(monkeypatch)
    with client.session_transaction() as sess:
        sess["user_id"] = 2
        sess["user_data"] = {"id": 2, "is_admin": False, "is_premium": False}

    assert client.get("/admin/mcp").status_code == 403


def test_an_anonymous_visitor_is_redirected(client, monkeypatch):
    _install(monkeypatch)
    response = client.get("/admin/mcp")

    assert response.status_code in (301, 302)


# --------------------------------------------------------------------------
# רינדור
# --------------------------------------------------------------------------


def test_all_three_tabs_render_with_one_active(admin, monkeypatch):
    _install(monkeypatch)
    soup = _soup(admin.get("/admin/mcp"))

    tabs = soup.select("button.mcp-tab")
    panels = soup.select(".mcp-panel")

    assert len(tabs) == 3
    assert len(panels) == 3
    assert len(soup.select(".mcp-panel.active")) == 1
    assert {tab["data-panel"] for tab in tabs} == {p["data-panel"] for p in panels}


def test_rows_reach_the_page(admin, monkeypatch):
    _install(monkeypatch)
    body = admin.get("/admin/mcp").get_data(as_text=True)

    assert "codekeeper_get_repo_file" in body
    assert "claude-code" in body


def test_error_rate_is_shown_beside_the_absolute_count(admin, monkeypatch):
    """על מדגם קטן האחוז מטעה: 20% על חמש קריאות הוא שגיאה אחת."""
    _install(monkeypatch)
    soup = _soup(admin.get("/admin/mcp"))
    rates = [el.get_text(" ", strip=True) for el in soup.select(".mcp-rate")]

    assert any("20.0%" in text and "(1)" in text for text in rates)


def test_the_navigation_tab_reports_the_full_total_not_the_page_size(admin, monkeypatch):
    _install(monkeypatch, navigation=EndpointResult(rows=list(NAV_ROWS), total=10))
    body = admin.get("/admin/mcp").get_data(as_text=True)

    assert "מתוך 10" in body


def test_null_values_render_as_a_dash_and_never_as_the_word_none(admin, monkeypatch):
    """שש עמודות מוצהרות Nullable ב-PostHog."""
    _install(
        monkeypatch,
        health=EndpointResult(rows=[{
            "tool": None, "calls": 1, "errors": 0, "error_rate_pct": 0.0,
            "p50_ms": None, "p95_ms": None, "sessions": 1, "last_seen": None,
        }]),
    )
    soup = _soup(admin.get("/admin/mcp"))
    text = soup.get_text(" ", strip=True)

    assert "None" not in text
    assert "—" in text


# --------------------------------------------------------------------------
# ריק מול שגיאה — ההבחנה שהעמוד עומד או נופל עליה
# --------------------------------------------------------------------------


def test_no_reports_yet_reads_as_empty_and_not_as_a_failure(admin, monkeypatch):
    _install(monkeypatch, missing=EndpointResult(rows=[]))
    soup = _soup(admin.get("/admin/mcp"))
    panel = soup.select_one('.mcp-panel[data-panel="missing"]')

    assert panel.select_one(".mcp-state") is not None
    assert panel.select_one(".mcp-alert") is None
    assert "get_more_tools" in panel.get_text()


def test_a_failing_endpoint_reads_as_a_failure_and_not_as_empty(admin, monkeypatch):
    _install(
        monkeypatch,
        missing=EndpointResult(error_code="unavailable", error_detail="PostHog עמוס כרגע."),
    )
    panel = _soup(admin.get("/admin/mcp")).select_one('.mcp-panel[data-panel="missing"]')

    assert panel.select_one(".mcp-alert") is not None
    assert "PostHog עמוס כרגע." in panel.get_text()


def test_one_failing_tab_does_not_blank_the_other_two(admin, monkeypatch):
    """ההבטחה של "שגיאה פר-טאב", דרך ה-DOM ולא דרך השירות."""
    _install(
        monkeypatch,
        navigation=EndpointResult(error_code="query_failed", error_detail="השאילתה נכשלה."),
    )
    soup = _soup(admin.get("/admin/mcp"))

    assert len(soup.select(".mcp-alert")) == 1
    assert soup.select_one('.mcp-panel[data-panel="navigation"] .mcp-alert') is not None
    health_panel = soup.select_one('.mcp-panel[data-panel="health"]')
    assert "codekeeper_get_repo_file" in health_panel.get_text()
    assert soup.select_one('.mcp-panel[data-panel="missing"] .mcp-alert') is None


def test_a_configuration_error_names_the_missing_variable(admin, monkeypatch):
    """כדי שהודעה על משתנה חסר לא תישלח לחפש אנדפוינט."""
    _install(
        monkeypatch,
        health=EndpointResult(
            error_code="config_missing",
            error_detail="המדידה אינה מוגדרת בשירות הוובאפ. חסר: POSTHOG_PROJECT_ID",
        ),
    )
    text = _soup(admin.get("/admin/mcp")).select_one('.mcp-panel[data-panel="health"]').get_text()

    assert "POSTHOG_PROJECT_ID" in text


# --------------------------------------------------------------------------
# אבטחה
# --------------------------------------------------------------------------


def test_agent_authored_text_is_escaped(admin, monkeypatch):
    """``capability`` הוא טקסט חופשי שסוכן חיצוני כתב. "רק אדמינים רואים"
    אינו הגנה — אדמינים הם היעד."""
    _install(
        monkeypatch,
        missing=EndpointResult(rows=[{
            "reported_at": "2026-09-02T10:00:00Z",
            "capability": "<script>alert(1)</script>",
            "intent_source": '<img src=x onerror=alert(2)>',
            "client": "claude-code", "session": "s1",
        }]),
    )
    response = admin.get("/admin/mcp")
    body = response.get_data(as_text=True)
    soup = BeautifulSoup(body, "html.parser")

    assert "<script>alert(1)</script>" not in body
    assert "&lt;script&gt;" in body
    injected = [s for s in soup.select("script") if "alert(1)" in (s.string or "")]
    assert not injected, "טקסט של סוכן הפך לתגית script חיה"
    assert not soup.select("img[onerror]")


def test_the_api_key_never_reaches_the_html(admin, monkeypatch):
    monkeypatch.setenv("POSTHOG_PERSONAL_API_KEY", "phx_MUST_NOT_APPEAR")
    _install(monkeypatch)
    body = admin.get("/admin/mcp").get_data(as_text=True)

    assert "phx_MUST_NOT_APPEAR" not in body
    assert "phx_" not in body


def test_the_page_never_leaks_a_traceback(admin, monkeypatch):
    """כשל בשירות מגיע כהודעה בעברית, לא כ-500 גנרי ולא כ-stack trace."""
    def _explode():
        raise RuntimeError("boom")

    fake = types.SimpleNamespace(get_dashboard=_explode)
    monkeypatch.setattr(mcp, "get_mcp_analytics_service", lambda: fake)
    response = admin.get("/admin/mcp")
    body = response.get_data(as_text=True)

    assert response.status_code == 500
    assert "Traceback" not in body
    assert "RuntimeError" not in body
    assert "אירעה שגיאה בטעינת הנתונים" in body
    assert len(BeautifulSoup(body, "html.parser").select("button.mcp-tab")) == 3
