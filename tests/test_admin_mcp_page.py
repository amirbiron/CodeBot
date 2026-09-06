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
        "client": "claude-code", "calls": 15, "searches": 0,
        "outline_reads": 2, "content_reads": 12,
        "errors": 0, "total_ms": 2574.0,
        "intent": "mapping webapp/app.py before reading the admin routes",
        "total_sessions": 10,
    }
]
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
        "session": "ses_01a05ed4",
    },
    {
        # נקלטה לפני שההודעות נשמרו כלל. התא יציג "—", וזה מצב תקין.
        "failed_at": "2026-09-01T21:01:34.441000Z",
        "tool": "codekeeper_get_repo_file", "client": None,
        "error_type": "ValidationError", "error_message": None,
        "session": "ses_01a05ec0",
    },
]
POSTHOG_LINKS = {
    "intent_clusters": "https://us.posthog.com/project/567754/mcp-analytics/intent-clustering",
    "sessions": "https://us.posthog.com/project/567754/mcp-analytics/sessions",
}


def _install(monkeypatch, health=None, navigation=None, missing=None, failures=None, links=None):
    """מחליף את השירות כולו, כדי שהבדיקה לא תיגע ברשת ולא תישבר על נתונים."""
    fake = types.SimpleNamespace(
        get_dashboard=lambda: {
            mcp.ENDPOINT_TOOL_HEALTH: (
                health if health is not None else EndpointResult(rows=list(HEALTH_ROWS))
            ),
            mcp.ENDPOINT_TOOL_FAILURES: (
                failures if failures is not None else EndpointResult(rows=list(FAILURE_ROWS))
            ),
            mcp.ENDPOINT_NAVIGATION_COST: (
                navigation
                if navigation is not None
                else EndpointResult(rows=list(NAV_ROWS), total=10)
            ),
            mcp.ENDPOINT_MISSING_CAPABILITIES: (
                missing if missing is not None else EndpointResult(rows=[])
            ),
        },
        posthog_links=lambda: (POSTHOG_LINKS if links is None else links),
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


def test_one_failing_tab_does_not_blank_the_others(admin, monkeypatch):
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

    fake = types.SimpleNamespace(get_dashboard=_explode, posthog_links=lambda: POSTHOG_LINKS)
    monkeypatch.setattr(mcp, "get_mcp_analytics_service", lambda: fake)
    response = admin.get("/admin/mcp")
    body = response.get_data(as_text=True)

    assert response.status_code == 500
    assert "Traceback" not in body
    assert "RuntimeError" not in body
    assert "אירעה שגיאה בטעינת הנתונים" in body
    assert len(BeautifulSoup(body, "html.parser").select("button.mcp-tab")) == 3


# --------------------------------------------------------------------------
# הודעות השגיאה בטאב הבריאות
# --------------------------------------------------------------------------


def test_the_failure_message_itself_reaches_the_page(admin, monkeypatch):
    """הטבלה למעלה אומרת "20% שגיאות"; הפאנל הזה אומר למה.

    בלעדיו הדף הוא דוח מסירה בלי פתק המסירה: מספר כשלים בלי שם השדה שנדחה.
    """
    _install(monkeypatch)
    panel = _soup(admin.get("/admin/mcp")).select_one('.mcp-panel[data-panel="health"]')
    text = panel.get_text(" ", strip=True)

    assert "lines.1" in text
    assert "Input should be a valid integer" in text


def test_the_failures_panel_lives_under_the_tool_table_and_not_in_a_new_tab(admin, monkeypatch):
    """הוא הפירוט של עמודת השגיאות שכבר שם, ולכן הוא שייך לאותו טאב."""
    _install(monkeypatch)
    soup = _soup(admin.get("/admin/mcp"))

    assert len(soup.select("button.mcp-tab")) == 3
    assert len(soup.select(".mcp-panel")) == 3
    health = soup.select_one('.mcp-panel[data-panel="health"]')
    assert health.select_one(".mcp-errmsg") is not None


def test_a_failure_with_no_message_shows_a_dash_and_not_an_error(admin, monkeypatch):
    """**מצב תקין, לא כשל.**

    הצינזור קרה בזמן השליחה ואינו הפיך, ולכן קריאות שנכשלו לפני פתיחת השער
    נספרות אבל אין להן טקסט. תא ריק הוא התשובה הנכונה; ``.mcp-alert`` היה
    אומר שהשליפה נכשלה, וזה שקר.
    """
    _install(monkeypatch)
    health = _soup(admin.get("/admin/mcp")).select_one('.mcp-panel[data-panel="health"]')
    cells = [td.get_text(" ", strip=True) for td in health.select("td.mcp-errmsg")]

    # התא נושא גם טקסט ל-screen reader לצד המקף, ולכן ההשוואה על התחלת התא.
    assert any(cell.startswith("—") for cell in cells), cells
    assert "None" not in health.get_text(" ", strip=True)
    assert health.select_one(".mcp-alert") is None


def test_a_failing_failures_endpoint_does_not_blank_the_tool_table(admin, monkeypatch):
    """אנדפוינט נפרד, ולכן כשל נפרד — בתוך אותו טאב."""
    _install(
        monkeypatch,
        failures=EndpointResult(error_code="unavailable", error_detail="PostHog עמוס כרגע."),
    )
    health = _soup(admin.get("/admin/mcp")).select_one('.mcp-panel[data-panel="health"]')

    assert health.select_one(".mcp-alert") is not None
    assert "codekeeper_get_repo_file" in health.get_text()


def test_no_failures_at_all_reads_as_empty_and_not_as_a_failure(admin, monkeypatch):
    _install(monkeypatch, failures=EndpointResult(rows=[]))
    health = _soup(admin.get("/admin/mcp")).select_one('.mcp-panel[data-panel="health"]')

    assert health.select_one(".mcp-alert") is None
    assert "אף קריאה לא נכשלה" in health.get_text()


# --------------------------------------------------------------------------
# הפרדת האאוטליין מקריאת התוכן
# --------------------------------------------------------------------------


def test_outline_and_content_are_two_columns_and_not_one(admin, monkeypatch):
    """המדד כולו: טור אחד שסופר את שניהם לא יכול להראות שהאחת החליפה את השנייה."""
    _install(monkeypatch)
    nav = _soup(admin.get("/admin/mcp")).select_one('.mcp-panel[data-panel="navigation"]')
    headers = [th.get_text(strip=True) for th in nav.select("thead th")]

    assert "אאוטליין" in headers
    assert "קריאת תוכן" in headers
    assert "קריאות קובץ" not in headers
    row = [td.get_text(" ", strip=True) for td in nav.select("tbody tr td")]
    assert "2" in row and "12" in row


def test_the_table_says_sessions_are_not_comparable(admin, monkeypatch):
    """ההערה שחייבת להיכנס: הטור מודד עלות, לא איכות."""
    _install(monkeypatch)
    nav = _soup(admin.get("/admin/mcp")).select_one('.mcp-panel[data-panel="navigation"]')
    text = nav.get_text(" ", strip=True)

    assert "אין להשוות בין סשנים בלי לדעת מה הייתה המשימה" in text
    assert "מודד עלות, לא איכות" in text


# --------------------------------------------------------------------------
# טור הכוונה
# --------------------------------------------------------------------------


def test_the_intent_column_shows_what_the_agent_wrote(admin, monkeypatch):
    """במקום ``ses_01a06104-b1e2...`` יופיע מה הסוכן ניסה לעשות."""
    _install(monkeypatch)
    nav = _soup(admin.get("/admin/mcp")).select_one('.mcp-panel[data-panel="navigation"]')

    assert "מה הסוכן ניסה לעשות" in [th.get_text(strip=True) for th in nav.select("thead th")]
    assert "mapping webapp/app.py" in nav.get_text(" ", strip=True)


def test_a_long_intent_is_clipped_in_view_with_the_whole_text_in_the_title(admin, monkeypatch):
    """הקיצוץ הוא החלטה של התצוגה בלבד — הטקסט המלא נשאר נגיש ב-``title``.

    נבדק דרך העמוד ולא דרך המאקרו: ``title`` הוא תכונת DOM, ומה שנשבר בה
    נשבר בדפדפן. קריאה ישירה למאקרו הייתה מוכיחה שהוא לא קורס, לא שהתא נכון.
    """
    long_intent = (
        "mapping the admin routes in webapp/app.py before reading the exact line "
        "range, so the outline call replaces a full file read of twenty thousand lines"
    )
    _install(
        monkeypatch,
        navigation=EndpointResult(rows=[{**NAV_ROWS[0], "intent": long_intent}], total=1),
    )
    nav = _soup(admin.get("/admin/mcp")).select_one('.mcp-panel[data-panel="navigation"]')
    span = nav.select_one(".mcp-clip")

    assert span is not None
    assert span["title"] == long_intent
    assert len(span.get_text()) < len(long_intent)
    assert span.get_text().endswith("…")


def test_an_intent_that_contains_a_script_tag_is_shown_as_text(admin, monkeypatch):
    """``$mcp_intent`` הוא טקסט חופשי שסוכן כתב, בדיוק כמו ``capability``.

    ההגנה היא ה-escape של Jinja: אין ``|safe`` ואין הזרקה ל-``innerHTML``.
    הבדיקה על ה-DOM המרונדר ולא על המחרוזת, כי מה שקובע הוא מה שהדפדפן בונה.
    """
    hostile = "<script>alert(1)</script>"
    _install(
        monkeypatch,
        navigation=EndpointResult(
            rows=[{**NAV_ROWS[0], "intent": hostile}], total=1
        ),
    )
    response = admin.get("/admin/mcp")
    body = response.get_data(as_text=True)
    soup = BeautifulSoup(body, "html.parser")

    assert hostile not in body
    assert "&lt;script&gt;" in body
    assert not [s for s in soup.select("script") if "alert(1)" in (s.string or "")]
    # גם בתוך ``title``: תכונה לא מצוטטת או לא ממולטת היא אותו חור בדיוק.
    assert soup.select_one(".mcp-clip")["title"] == hostile


def test_a_session_with_no_intent_renders_empty_and_not_as_an_error(admin, monkeypatch):
    """אירועים שנאספו לפני הפתיחה לא נושאים כוונה. זה צפוי."""
    _install(
        monkeypatch,
        navigation=EndpointResult(rows=[{**NAV_ROWS[0], "intent": None}], total=1),
    )
    nav = _soup(admin.get("/admin/mcp")).select_one('.mcp-panel[data-panel="navigation"]')

    assert nav.select_one(".mcp-alert") is None
    assert "None" not in nav.get_text(" ", strip=True)
    assert "—" in nav.get_text(" ", strip=True)


# --------------------------------------------------------------------------
# הקישורים היוצאים
# --------------------------------------------------------------------------


def test_the_page_links_out_to_what_it_cannot_fetch(admin, monkeypatch):
    """אשכולות הכוונות וסיכומי הסשן הם כלי API של PostHog ולא שאילתות."""
    _install(monkeypatch)
    soup = _soup(admin.get("/admin/mcp"))
    links = soup.select("a.mcp-outlink")

    assert {a["href"] for a in links} == set(POSTHOG_LINKS.values())
    for link in links:
        # יעד חיצוני שנפתח בלשונית חדשה חייב את שניהם: בלי ``noopener``
        # לדף היעד יש ``window.opener`` לעמוד האדמין.
        assert link["target"] == "_blank"
        assert "noopener" in link["rel"] and "noreferrer" in link["rel"]


def test_a_broken_configuration_drops_the_links_instead_of_building_a_dead_one(admin, monkeypatch):
    """כתובת שנבנתה מערך פסול מובילה לשום מקום, וההודעה על הקונפיגורציה כבר מוצגת."""
    _install(monkeypatch, links={})
    soup = _soup(admin.get("/admin/mcp"))

    assert soup.select("a.mcp-outlink") == []


def test_the_failures_panel_survives_a_failing_tool_health_endpoint(admin, monkeypatch):
    """שני אנדפוינטים נפרדים, ולכן שני מצבי כשל נפרדים — גם בתוך אותו טאב.

    עד לתיקון, פאנל הכשלים ישב בתוך ה-``else`` של ``tool_health.ok``: כשל
    בשליפת בריאות הכלים החביא גם פירוט שהגיע בהצלחה. זו אותה הבטחה של
    "שגיאה פר-אנדפוינט" שכבר נאכפת בין הטאבים, רק בתוך טאב.
    """
    _install(
        monkeypatch,
        health=EndpointResult(error_code="unavailable", error_detail="PostHog עמוס כרגע."),
    )
    health = _soup(admin.get("/admin/mcp")).select_one('.mcp-panel[data-panel="health"]')

    assert health.select_one(".mcp-alert") is not None
    # ...והפירוט עדיין שם.
    assert "lines.1" in health.get_text(" ", strip=True)
    assert health.select_one(".mcp-errmsg") is not None


def test_the_outbound_links_survive_a_failing_navigation_endpoint(admin, monkeypatch):
    """הקישורים אינם תלויים בנתונים — והם בדיוק מה שאדמין צריך כשאין נתונים."""
    _install(
        monkeypatch,
        navigation=EndpointResult(error_code="query_failed", error_detail="השאילתה נכשלה."),
    )
    nav = _soup(admin.get("/admin/mcp")).select_one('.mcp-panel[data-panel="navigation"]')

    assert nav.select_one(".mcp-alert") is not None
    assert len(nav.select("a.mcp-outlink")) == 2


def test_the_outbound_links_survive_an_empty_navigation_table(admin, monkeypatch):
    _install(monkeypatch, navigation=EndpointResult(rows=[]))
    nav = _soup(admin.get("/admin/mcp")).select_one('.mcp-panel[data-panel="navigation"]')

    assert nav.select_one(".mcp-state") is not None
    assert len(nav.select("a.mcp-outlink")) == 2


def test_a_clipped_intent_is_a_real_button_and_not_a_faked_one(admin, monkeypatch):
    """``title`` נחשף רק ב-hover, ולחיצה פותחת מודאל — כלומר זה כפתור.

    ``<button>`` ולא ``<span tabindex="0">``: כך Enter ו-Space עובדים בלי
    JS משלנו, וקורא מסך מכריז "כפתור" במקום להשמיע טקסט שלא ברור שאפשר
    ללחוץ עליו. הטקסט המלא נשאר גם ב-``aria-label``, כי ``title`` אינו
    נגיש במגע ובמקלדת.
    """
    _install(monkeypatch)
    clip = _soup(admin.get("/admin/mcp")).select_one(".mcp-clip")

    assert clip.name == "button"
    assert clip["type"] == "button"
    assert clip["aria-label"] == NAV_ROWS[0]["intent"]
    assert clip["title"] == NAV_ROWS[0]["intent"]


def test_the_template_does_not_point_at_a_file_that_is_not_in_this_repo(admin, monkeypatch):
    """``bugbot-rules/xss-innerhtml.md`` חי ב-``amir-bug-patterns``, לא כאן.

    הפניה שנראית כמו נתיב מקומי שולחת את הקורא הבא לחפש קובץ שאינו קיים.
    התיקון הוא לנקוב בשם הריפו — לא למחוק הפניה נכונה, ולא להמציא קובץ.
    """
    import pathlib

    template = pathlib.Path("webapp/templates/admin_mcp.html").read_text(encoding="utf-8")

    assert "bugbot-rules/xss-innerhtml.md" in template
    assert "amir-bug-patterns" in template
    assert not pathlib.Path("bugbot-rules/xss-innerhtml.md").exists()


# --------------------------------------------------------------------------
# ניקוי ההודעה, כיווניות, מודאל ובאנר
# --------------------------------------------------------------------------


def test_the_error_message_cell_shows_the_cleaned_line(admin, monkeypatch):
    """הרעש של Pydantic לא מגיע לטבלה: כותרת, הזחה וקישור לתיעוד."""
    _install(monkeypatch)
    cell = _soup(admin.get("/admin/mcp")).select_one("td.mcp-errmsg")
    text = cell.get_text(" ", strip=True)

    assert "lines.1" in text
    assert "Input should be a valid integer" in text
    assert "validation error for" not in text
    assert "errors.pydantic.dev" not in text


def test_technical_text_is_forced_ltr_inside_the_rtl_page(admin, monkeypatch):
    """העמוד כולו RTL, וההודעה והכוונה הן טקסט טכני באנגלית.

    בלי בידוד כיווניות הדפדפן מזיז סוגריים וסימני שוויון לקצה הלא נכון —
    ``[input_value='9']`` נראה שבור. זו תכונה של הטקסט, ולכן היא על התא.
    """
    _install(monkeypatch)
    soup = _soup(admin.get("/admin/mcp"))

    assert "mcp-ltr" in soup.select_one("td.mcp-errmsg")["class"]
    assert "mcp-ltr" in soup.select_one(".mcp-clip")["class"]
    # והכלל עצמו קיים ב-CSS, אחרת המחלקה היא קישוט.
    # מחפשים את הבלוק **של העמוד הזה**: ``base.html`` מזריק ``<style>`` משלו,
    # ו-``select_one("style")`` היה בוחר אותו ומכשיל את הטסט על הקובץ הלא נכון.
    styles = [tag.get_text() for tag in soup.select("style") if ".mcp-ltr" in tag.get_text()]
    assert styles, "כלל ה-LTR לא נמצא באף בלוק סגנון בעמוד"
    assert "direction: ltr" in styles[0]


def test_the_intent_modal_is_a_native_dialog_and_starts_closed(admin, monkeypatch):
    """``<dialog>`` ולא ``div``: נעילת הפוקוס, Escape והחזרת הפוקוס לכפתור
    שפתח מגיעות מהדפדפן, ולא מקוד שאפשר לשבור בלי לשים לב.

    ``role`` ו-``aria-modal`` **אינם** נכתבים ידנית — הדפדפן נותן אותם
    ל-``<dialog>`` שנפתח ב-``showModal()``, וכתיבה כפולה יכולה לסתור אותו.
    """
    _install(monkeypatch)
    soup = _soup(admin.get("/admin/mcp"))
    modal = soup.select_one("#mcpIntentModal")

    assert modal is not None
    assert modal.name == "dialog"
    # ``open`` הוא מה שמסמן דיאלוג פתוח, והוא אינו אמור להיות שם בטעינה.
    assert not modal.has_attr("open")
    assert not modal.has_attr("role")
    assert not modal.has_attr("aria-modal")
    assert modal["aria-labelledby"] == "mcpIntentModalTitle"
    # הטקסט **אינו** מרונדר בשרת — הוא נכתב ב-JS מהכפתור שנלחץ.
    assert soup.select_one("#mcpIntentModalText").get_text(strip=True) == ""


def test_the_mcp_script_never_assigns_to_innerhtml(admin, monkeypatch):
    """ההגנה היחידה שמפרידה בין טקסט שסוכן כתב לבין קוד שרץ.

    מוגבל ל-``<script>`` **של העמוד הזה**, שמזוהה לפי ``.mcp-tab``. גרסה
    קודמת של הטסט סרקה את כל הסקריפטים ונפלה על מודאל הפתיחה של
    ``base.html``, שמשתמש ב-``innerHTML`` על טקסט משלו — כלומר היא בדקה קוד
    שאינה אחראית עליו, והייתה מכריחה לשנות קובץ אחר כדי לעבור.
    """
    _install(monkeypatch)
    scripts = [
        script.string or ""
        for script in _soup(admin.get("/admin/mcp")).select("script")
        if ".mcp-tab" in (script.string or "")
    ]

    assert scripts, "הסקריפט של העמוד לא נמצא — הטסט לא בדק דבר"
    for code in scripts:
        assert ".innerHTML" not in code
        assert "insertAdjacentHTML" not in code
        assert "document.write" not in code


def test_failure_rows_carry_a_raw_timestamp_for_the_new_since_last_visit_count(admin, monkeypatch):
    """הבאנר סופר מול חותמת גולמית ולא מול המחרוזת המוצגת.

    התצוגה מעוגלת לדקה ומנוסחת בעברית; אי אפשר להשוות לפיה. וזו גם הסיבה
    שהספירה עמידה לחלון ה-30 יום שמחליק: היא מול "החדשה ביותר שנראתה",
    לא מול המספר הכולל, שיורד מעצמו כששגיאות ישנות נושרות.
    """
    _install(monkeypatch)
    soup = _soup(admin.get("/admin/mcp"))
    rows = soup.select("tr[data-at]")

    assert len(rows) == len(FAILURE_ROWS)
    assert [row["data-at"] for row in rows] == [r["failed_at"] for r in FAILURE_ROWS]
    banner = soup.select_one("#mcpFreshBanner")
    assert banner is not None
    # מתחיל סגור: השרת אינו יודע מתי הביקור הקודם היה.
    assert banner.has_attr("hidden")
