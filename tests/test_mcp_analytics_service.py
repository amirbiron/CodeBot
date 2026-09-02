"""בדיקות לשירות ה-MCP analytics (``services/mcp_analytics_service.py``).

הדגש כאן הוא על ההבחנות שקל לאבד: הצלחה בלי שורות מול כשל, קונפיגורציה
שגויה מול אנדפוינט חסר, והיחס בין שלושת מספרי תקציב הזמן.
"""

from __future__ import annotations

import time

import pytest

import services.mcp_analytics_service as mcp
from services.mcp_analytics_service import EndpointResult, McpAnalyticsService

ENV_KEYS = ("POSTHOG_PERSONAL_API_KEY", "POSTHOG_PROJECT_ID", "POSTHOG_HOST")


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv("POSTHOG_PERSONAL_API_KEY", "phx_TEST_ONLY_NOT_REAL")
    monkeypatch.setenv("POSTHOG_PROJECT_ID", "567754")
    monkeypatch.setenv("POSTHOG_HOST", "https://us.posthog.com")
    return McpAnalyticsService()


class _Resp:
    """תשובת HTTP מזויפת בצורת ``requests.Response`` שהשירות באמת נוגע בה."""

    def __init__(self, status, payload=None, json_raises=False):
        self.status_code = status
        self._payload = payload
        self._json_raises = json_raises

    def json(self):
        if self._json_raises:
            raise ValueError("not json")
        return self._payload


# --------------------------------------------------------------------------
# קונפיגורציה — שלוש הבדיקות שרצות לפני שנשלחת בקשה
# --------------------------------------------------------------------------


@pytest.mark.parametrize("missing", ENV_KEYS)
def test_missing_env_var_is_a_configuration_error(monkeypatch, missing):
    for key in ENV_KEYS:
        monkeypatch.setenv(key, "https://us.posthog.com" if key == "POSTHOG_HOST" else "v")
    monkeypatch.delenv(missing, raising=False)

    result = McpAnalyticsService().run_endpoint(mcp.ENDPOINT_TOOL_HEALTH)

    assert result.error_code == "config_missing"
    assert missing in result.error_detail, "ההודעה חייבת לומר איזה משתנה חסר"


def test_ingestion_host_is_rejected_before_the_request_is_sent(monkeypatch):
    """הכשל שהכי קל לאבחן לא נכון.

    ``POSTHOG_HOST`` נושא ערכים שונים בשני שירותים. ערך של שירות ה-MCP
    (כתובת הבליעה) היה מחזיר 404 מ-PostHog, וההודעה על 404 מפנה לחפש
    אנדפוינט חסר — כלומר בדיוק למקום הלא נכון.
    """
    monkeypatch.setenv("POSTHOG_PERSONAL_API_KEY", "phx_TEST")
    monkeypatch.setenv("POSTHOG_PROJECT_ID", "1")
    monkeypatch.setenv("POSTHOG_HOST", "https://us.i.posthog.com")

    def _must_not_be_called(*args, **kwargs):  # pragma: no cover
        raise AssertionError("בקשה נשלחה למרות ש-host שגוי")

    monkeypatch.setattr("http_sync.request", _must_not_be_called)

    result = McpAnalyticsService().run_endpoint(mcp.ENDPOINT_TOOL_HEALTH)

    assert result.error_code == "host_is_ingestion"
    assert result.error_code != "endpoint_not_found"
    assert "us.posthog.com" in result.error_detail


def test_trailing_slash_in_host_does_not_double_up(monkeypatch):
    monkeypatch.setenv("POSTHOG_PERSONAL_API_KEY", "phx_TEST")
    monkeypatch.setenv("POSTHOG_PROJECT_ID", "1")
    monkeypatch.setenv("POSTHOG_HOST", "https://us.posthog.com/")

    host, _, _, error = McpAnalyticsService().resolve_config()

    assert error is None
    assert host == "https://us.posthog.com"


# --------------------------------------------------------------------------
# ההבחנה המרכזית: ריק אינו שגיאה
# --------------------------------------------------------------------------


def test_zero_rows_is_success_not_failure(configured):
    """הטאב "כלים חסרים" מציג ריק בהשקה. אם ריק ייחשב לכשל, העמוד ידווח
    תקלה על מצב תקין לחלוטין."""
    payload = {"results": [], "columns": ["reported_at", "capability"]}

    result = configured._result_from_response(
        _Resp(200, payload), mcp.ENDPOINT_MISSING_CAPABILITIES
    )

    assert result.rows == []
    assert result.error_code == ""
    assert result.ok is True


def test_empty_rows_with_an_error_code_is_a_failure():
    assert EndpointResult(rows=[]).ok is True
    assert EndpointResult(rows=[], error_code="unavailable").ok is False


# --------------------------------------------------------------------------
# פירסור התשובה
# --------------------------------------------------------------------------


def test_real_navigation_payload_yields_the_full_count_not_the_returned_count(configured):
    """``total_sessions`` נגזר ב-``count() OVER ()`` ולכן אינו ספירת המוחזר."""
    payload = {
        "columns": [
            "session", "started", "client", "calls", "searches",
            "file_reads", "errors", "total_ms", "total_sessions",
        ],
        "results": [
            ["ses_a", "2026-09-02T08:15:00.843000Z", "claude-code", 15, 0, 14, 0, 2574.0, 10],
            ["ses_b", "2026-09-02T07:37:28.908000Z", "Anthropic/ClaudeAI", 6, 1, 1, 0, 5052.0, 10],
        ],
        "error": None,
        "hasMore": True,
        "is_cached": False,
        "last_refresh": "2026-09-02T09:05:34.188266Z",
    }

    result = configured._result_from_response(_Resp(200, payload), mcp.ENDPOINT_NAVIGATION_COST)

    assert result.ok
    assert len(result.rows) == 2
    assert result.total == 10, "total חייב להיות הספירה המלאה ולא len(rows)"
    assert result.rows[0]["file_reads"] == 14
    assert result.has_more is True
    assert result.last_refresh.startswith("2026-09-02")


def test_nullable_columns_survive_as_none(configured):
    """שש עמודות מוצהרות Nullable ב-PostHog; None הוא ערך תקין."""
    payload = {
        "columns": ["tool", "calls", "p50_ms", "p95_ms"],
        "results": [[None, 1, None, None]],
    }

    result = configured._result_from_response(_Resp(200, payload), mcp.ENDPOINT_TOOL_HEALTH)

    assert result.ok
    assert result.rows[0]["tool"] is None
    assert result.rows[0]["p50_ms"] is None


def test_missing_columns_is_an_explicit_failure(configured):
    """ה-spec מבטיח רק את ``results``; ``columns`` אינו מובטח חוזית."""
    result = configured._result_from_response(_Resp(200, {"results": [["x"]]}), "x")

    assert result.error_code == "bad_payload"
    assert result.rows == []


def test_row_length_mismatch_is_not_silently_truncated(configured):
    """``zip`` על אורכים שונים חותך בשקט ומייצר שורה חסרת עמודה."""
    payload = {"columns": ["a", "b"], "results": [["v1", "v2", "v3"]]}

    result = configured._result_from_response(_Resp(200, payload), "x")

    assert result.error_code == "bad_payload"


def test_error_field_in_a_200_body_is_still_a_failure(configured):
    """קוד סטטוס 200 אינו ראיה להצלחה — ``error`` הוא ערוץ כשל נפרד."""
    payload = {"results": [], "columns": ["a"], "error": "boom"}

    result = configured._result_from_response(_Resp(200, payload), "x")

    assert result.error_code == "query_failed"
    assert "boom" in result.error_detail


# --------------------------------------------------------------------------
# מיפוי קודי סטטוס
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (_Resp(401), "unauthorized"),
        (_Resp(403), "unauthorized"),
        (_Resp(404), "endpoint_not_found"),
        (_Resp(503, {"code": "query_capacity", "detail": "busy"}), "unavailable"),
        (_Resp(400, {"code": "query_timeout", "detail": "slow"}), "query_failed"),
        (_Resp(200, None), "bad_payload"),
        (_Resp(200, {}, json_raises=True), "bad_payload"),
    ],
)
def test_status_codes_map_to_distinct_failure_modes(configured, response, expected):
    result = configured._result_from_response(response, mcp.ENDPOINT_TOOL_HEALTH)

    assert result.error_code == expected
    assert result.ok is False
    assert result.error_detail, "לכל מצב כשל חייבת להיות הודעה"


def test_query_failures_branch_on_code_not_on_type(configured):
    """ה-spec של PostHog מורה במפורש: branch on ``code``, not ``type``."""
    same_type = {"type": "validation_error"}
    timeout = configured._result_from_response(
        _Resp(400, {**same_type, "code": "query_timeout"}), "x"
    )
    too_large = configured._result_from_response(
        _Resp(400, {**same_type, "code": "query_too_large"}), "x"
    )

    assert timeout.error_detail != too_large.error_detail


def test_401_is_never_reported_as_a_generic_outage(configured):
    """איחוד 401 עם 5xx מסתיר תקלת הרשאה מאחורי "נסה שוב"."""
    unauthorized = configured._result_from_response(_Resp(401), "x")
    outage = configured._result_from_response(_Resp(503, {"code": "query_capacity"}), "x")

    assert unauthorized.error_code != outage.error_code
    assert "endpoint:read" in unauthorized.error_detail


# --------------------------------------------------------------------------
# סודות
# --------------------------------------------------------------------------


def test_the_api_key_never_appears_in_any_failure_message(configured):
    responses = [
        _Resp(401), _Resp(404), _Resp(503, {"code": "query_capacity"}),
        _Resp(400, {"code": "query_timeout", "detail": "d"}), _Resp(200, None),
    ]
    for response in responses:
        result = configured._result_from_response(response, mcp.ENDPOINT_TOOL_HEALTH)
        assert "phx_" not in result.error_detail
        assert "TEST_ONLY_NOT_REAL" not in result.error_detail


def test_the_key_travels_in_the_header_and_the_url_carries_no_query_string(monkeypatch, configured):
    """הבסיס להגנה מפני רישום שורת השאילתה על ידי SDK הניטור."""
    seen = {}

    def _capture(method, url, **kwargs):
        seen["method"] = method
        seen["url"] = url
        seen["kwargs"] = kwargs
        return _Resp(200, {"results": [], "columns": ["a"]})

    monkeypatch.setattr("http_sync.request", _capture)
    configured.run_endpoint(mcp.ENDPOINT_NAVIGATION_COST, limit=50)

    assert seen["method"] == "POST"
    assert "?" not in seen["url"], "אסור שתהיה שורת שאילתה בכתובת"
    assert "phx_" not in seen["url"]
    assert seen["kwargs"]["headers"]["Authorization"].startswith("Bearer ")
    assert seen["kwargs"]["json"] == {"limit": 50}, "limit חייב לשבת בגוף ולא בכתובת"


def test_circuit_labels_are_explicit_and_distinct_per_endpoint(monkeypatch, configured):
    """בלי תוויות נפרדות, כשל של אנדפוינט אחד פותח מפסק שחוסם את השאר."""
    labels = []

    def _capture(method, url, **kwargs):
        labels.append((kwargs.get("service"), kwargs.get("endpoint")))
        return _Resp(200, {"results": [], "columns": ["a"]})

    monkeypatch.setattr("http_sync.request", _capture)
    for name in (mcp.ENDPOINT_TOOL_HEALTH, mcp.ENDPOINT_NAVIGATION_COST):
        configured.run_endpoint(name)

    assert all(service == "posthog" for service, _ in labels)
    assert len({endpoint for _, endpoint in labels}) == 2, "שני האנדפוינטים חולקים תווית מפסק"


def test_request_overrides_the_projects_slow_retry_defaults(monkeypatch, configured):
    seen = {}

    def _capture(method, url, **kwargs):
        seen.update(kwargs)
        return _Resp(200, {"results": [], "columns": ["a"]})

    monkeypatch.setattr("http_sync.request", _capture)
    configured.run_endpoint(mcp.ENDPOINT_TOOL_HEALTH)

    assert seen["timeout"] == mcp.REQUEST_TIMEOUT_SECONDS
    assert seen["max_attempts"] == mcp.REQUEST_MAX_ATTEMPTS


# --------------------------------------------------------------------------
# תקציב הזמן
# --------------------------------------------------------------------------


def test_the_three_timing_constants_stay_coherent():
    """התקציב חייב להיות מעל המקרה הגרוע של קריאה בודדת.

    אחרת הוא חותך קריאה שעוד עשויה להצליח ומשאיר אחריה thread רץ. זה לא
    היה תיאורטי: בגרסה הראשונה של המימוש התקציב היה 6 שניות מול מקרה גרוע
    של 8.25, והמדידה היא שחשפה את זה.
    """
    backoff_allowance = 0.25
    worst_case = mcp.REQUEST_TIMEOUT_SECONDS * mcp.REQUEST_MAX_ATTEMPTS + backoff_allowance

    assert worst_case < mcp.TOTAL_BUDGET_SECONDS


def test_a_stuck_endpoint_cannot_hang_the_page(monkeypatch):
    """התקציב העליון חותך בוודאות, בלי תלות ב-timeout שעלול להידרס מ-ENV."""
    monkeypatch.setattr(mcp, "TOTAL_BUDGET_SECONDS", 1.0)
    service = McpAnalyticsService()
    monkeypatch.setattr(service, "run_endpoint", lambda name, limit=None: time.sleep(30))

    started = time.monotonic()
    results = service.get_dashboard()
    elapsed = time.monotonic() - started

    assert elapsed < 3.0, f"התקציב לא נאכף: {elapsed:.2f}s"
    assert len(results) == 3
    assert all(r.error_code == "unavailable" for r in results.values())


def test_a_call_that_finishes_within_the_worst_case_is_not_cut(monkeypatch):
    monkeypatch.setattr(mcp, "TOTAL_BUDGET_SECONDS", 1.0)
    service = McpAnalyticsService()
    monkeypatch.setattr(
        service, "run_endpoint",
        lambda name, limit=None: (time.sleep(0.2), EndpointResult(rows=[{"a": 1}]))[1],
    )

    results = service.get_dashboard()

    assert all(r.ok for r in results.values())


def test_one_failing_endpoint_does_not_take_down_the_others(monkeypatch):
    """זו ההבטחה של "שגיאה פר-טאב". כל שאר מצבי הכשל נבדקים בבידוד ולכן
    אף אחד מהם אינו מוכיח אותה."""
    service = McpAnalyticsService()

    def _partial(name, limit=None):
        if name == mcp.ENDPOINT_NAVIGATION_COST:
            return EndpointResult(error_code="query_failed", error_detail="נכשל")
        return EndpointResult(rows=[{"tool": "t", "calls": 1}])

    monkeypatch.setattr(service, "run_endpoint", _partial)
    results = service.get_dashboard()

    assert results[mcp.ENDPOINT_NAVIGATION_COST].ok is False
    assert results[mcp.ENDPOINT_TOOL_HEALTH].ok is True
    assert results[mcp.ENDPOINT_MISSING_CAPABILITIES].ok is True


def test_a_breach_of_the_no_raise_contract_is_contained_and_logged(monkeypatch):
    service = McpAnalyticsService()

    def _throws(name, limit=None):
        raise RuntimeError("contract violated")

    monkeypatch.setattr(service, "run_endpoint", _throws)
    results = service.get_dashboard()

    assert len(results) == 3
    assert all(r.error_code == "unavailable" for r in results.values())


def test_a_network_error_does_not_escape_the_service(monkeypatch, configured):
    import requests

    def _boom(method, url, **kwargs):
        raise requests.ConnectionError("down")

    monkeypatch.setattr("http_sync.request", _boom)
    result = configured.run_endpoint(mcp.ENDPOINT_TOOL_HEALTH)

    assert result.error_code == "unavailable"
    assert result.ok is False


def test_an_open_circuit_is_reported_as_a_temporary_outage(monkeypatch, configured):
    from http_sync import CircuitOpenError

    def _open(method, url, **kwargs):
        raise CircuitOpenError("posthog", "mcp_analytics.x")

    monkeypatch.setattr("http_sync.request", _open)
    result = configured.run_endpoint(mcp.ENDPOINT_TOOL_HEALTH)

    assert result.error_code == "unavailable"
