"""``services/webapp_metrics_outage.py``: מתי כישלון של הסמפלר בקריאת ``/metrics`` של הוובאפ הופך להתראה.

הרקע: בכל דיפלוי של הוובאפ הסמפלר של הבוט נכשל בבדיקה אחת (Render מכבה את המופע הישן לפני שהחדש עולה, כי לשירות
מחובר דיסק), וזה הגיע לטלגרם דרך Sentry. הטסטים כאן מקבעים שהשבתה של דיפלוי אינה מתריעה, שהשבתה שנמשכת לאורך הסף
מתריעה פעם אחת, ושאחרי חזרה השבתה חדשה מתריעה שוב.

הבדיקות של :func:`scrape_metrics` ושל :func:`scrape_and_track` יוצאות לשרת HTTP אמיתי על ``127.0.0.1``, דרך
``http_async`` האמיתי — אותו מסלול שהסמפלר מריץ.
"""

from __future__ import annotations

import logging
import socket
from pathlib import Path

import pytest
import yaml
from aiohttp import web
from aiohttp.test_utils import TestServer

import http_async
import resilience
from services import webapp_metrics_outage as wmo


class _Clock:
    """שעון ידני: הבדיקה הבאה של הסמפלר היא ``advance(60)``."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


FAIL = wmo.ScrapeResult.failure("HTTP 503")
OK = wmo.ScrapeResult.success("adaptive_current_error_rate_percent 0.5\n")


def _tracker(clock: _Clock, *, threshold: int = 120, interval: float = 60) -> wmo.OutageTracker:
    return wmo.OutageTracker(threshold_secs=threshold, interval_secs=interval, clock=clock)


def _run(tracker: wmo.OutageTracker, clock: _Clock, results) -> list:
    """מריץ רצף תוצאות, בדיקה כל 60 שניות, ומחזיר את האירוע (או ``None``) של כל בדיקה."""
    events = []
    for index, result in enumerate(results):
        if index:
            clock.advance(60)
        events.append(tracker.record(result))
    return events


# --- כמה בדיקות הן הסף ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "threshold, interval, expected",
    [
        (120, 60, 3),  # 0, 60, 120
        (120, 45, 4),  # 0, 45, 90, 135 — שלוש היו מכסות רק 90 שניות
        (60, 60, 2),
        (0, 60, 1),  # 0 = כבר בכישלון הראשון
        (120, 15, 9),
    ],
)
def test_required_failures_cover_the_threshold(threshold, interval, expected):
    assert wmo.required_failures(threshold, interval) == expected
    # הבדיקה האחרונה מגיעה לסף, והאחת שלפניה עוד לא.
    assert (expected - 1) * interval >= threshold
    assert expected == 1 or (expected - 2) * interval < threshold


@pytest.mark.parametrize("interval", [0, -60])
def test_required_failures_rejects_a_non_positive_interval(interval):
    with pytest.raises(ValueError):
        wmo.required_failures(120, interval)


# --- הסף ממשתנה הסביבה ----------------------------------------------------------------------------------------------


def test_threshold_defaults_when_unset(monkeypatch):
    monkeypatch.delenv(wmo.OUTAGE_ALERT_SECS_ENV, raising=False)
    assert wmo.read_outage_alert_secs() == wmo.DEFAULT_OUTAGE_ALERT_SECS == 120


@pytest.mark.parametrize("raw, expected", [("90", 90), (" 300 ", 300), ("0", 0)])
def test_threshold_from_env(monkeypatch, raw, expected):
    monkeypatch.setenv(wmo.OUTAGE_ALERT_SECS_ENV, raw)
    assert wmo.read_outage_alert_secs() == expected


@pytest.mark.parametrize("raw", ["abc", "1.5", "-5"])
def test_invalid_threshold_falls_back_with_a_warning(monkeypatch, caplog, raw):
    monkeypatch.setenv(wmo.OUTAGE_ALERT_SECS_ENV, raw)
    with caplog.at_level(logging.WARNING, logger=wmo.__name__):
        assert wmo.read_outage_alert_secs() == wmo.DEFAULT_OUTAGE_ALERT_SECS
    assert any(wmo.OUTAGE_ALERT_SECS_ENV in rec.getMessage() for rec in caplog.records)


# --- המונה --------------------------------------------------------------------------------------------------------


def test_a_deploy_sized_outage_does_not_alert():
    """הדיפלוי של 18.11.2026: בדיקה אחת נכשלה, הבאה הצליחה."""
    clock = _Clock()
    assert _run(_tracker(clock), clock, [OK, FAIL, OK]) == [None, None, None]


def test_two_failures_in_a_row_do_not_alert():
    """שתי בדיקות מכסות רק דקה — דיפלוי קצת ארוך יותר מזה של היום."""
    clock = _Clock()
    assert _run(_tracker(clock), clock, [FAIL, FAIL, OK]) == [None, None, None]


def test_two_minutes_of_failures_alert_once_then_recovery():
    clock = _Clock()
    events = _run(
        _tracker(clock),
        clock,
        [FAIL, FAIL, wmo.ScrapeResult.failure("ClientConnectorError"), FAIL, FAIL, OK],
    )

    alert = events[2]
    assert alert is not None
    assert alert.kind == wmo.ALERT_UNREACHABLE
    assert alert.consecutive_failures == 3
    assert alert.outage_seconds == 120
    assert alert.last_reason == "ClientConnectorError"
    assert alert.threshold_seconds == 120

    # אין התראה נוספת על אותה השבתה.
    assert events[3] is None and events[4] is None

    recovered = events[5]
    assert recovered is not None
    assert recovered.kind == wmo.ALERT_RECOVERED
    assert recovered.consecutive_failures == 5
    # נמדד מהכישלון הראשון, לא מההתראה ולא מהכישלון האחרון.
    assert recovered.outage_seconds == 300
    assert recovered.last_reason == "HTTP 503"


def test_the_next_outage_alerts_again_after_recovery():
    """המצב שמדכא התראה נוספת מתאפס בחזרה — אחרת השבתה שנייה הייתה עוברת בשקט."""
    clock = _Clock()
    tracker = _tracker(clock)
    first = _run(tracker, clock, [FAIL, FAIL, FAIL, OK])
    clock.advance(600)
    second = _run(tracker, clock, [FAIL, FAIL, FAIL])

    assert [e.kind if e else None for e in first] == [None, None, wmo.ALERT_UNREACHABLE, wmo.ALERT_RECOVERED]
    assert [e.kind if e else None for e in second] == [None, None, wmo.ALERT_UNREACHABLE]
    # ההשבתה השנייה נמדדת מתחילתה שלה.
    assert second[2].outage_seconds == 120


def test_a_success_in_the_middle_restarts_the_count():
    clock = _Clock()
    events = _run(_tracker(clock), clock, [FAIL, FAIL, OK, FAIL, FAIL])
    assert events == [None, None, None, None, None]


def test_zero_threshold_alerts_on_the_first_failure():
    clock = _Clock()
    events = _run(_tracker(clock, threshold=0), clock, [FAIL, OK])
    assert events[0].kind == wmo.ALERT_UNREACHABLE
    assert events[0].outage_seconds == 0
    assert events[1].kind == wmo.ALERT_RECOVERED


# --- הדיווח -------------------------------------------------------------------------------------------------------


@pytest.fixture
def sent_alerts(monkeypatch):
    import internal_alerts

    sent: list[dict] = []

    def _capture(name, severity="info", summary="", **details):
        sent.append({"name": name, "severity": severity, "summary": summary, **details})

    monkeypatch.setattr(internal_alerts, "emit_internal_alert", _capture)
    return sent


def test_unreachable_alert_is_an_error_with_the_reason(sent_alerts):
    wmo.report_outage_event(
        wmo.OutageEvent(
            kind=wmo.ALERT_UNREACHABLE,
            consecutive_failures=3,
            outage_seconds=120.4,
            last_reason="HTTP 503",
            threshold_seconds=120,
        )
    )
    (alert,) = sent_alerts
    assert alert["name"] == "webapp_metrics_unreachable"
    assert alert["severity"] == "error"
    assert "HTTP 503" in alert["summary"] and "/metrics" in alert["summary"]
    assert alert["details"] == {
        "alert_type": "webapp_metrics_unreachable",
        "consecutive_failures": 3,
        "outage_seconds": 120,
        "last_reason": "HTTP 503",
        "threshold_seconds": 120,
    }


def test_recovered_alert_is_info(sent_alerts):
    wmo.report_outage_event(
        wmo.OutageEvent(
            kind=wmo.ALERT_RECOVERED,
            consecutive_failures=5,
            outage_seconds=300,
            last_reason="HTTP 503",
            threshold_seconds=120,
        )
    )
    (alert,) = sent_alerts
    assert alert["name"] == "webapp_metrics_recovered"
    assert alert["severity"] == "info"
    assert alert["details"]["alert_type"] == "webapp_metrics_recovered"


def test_a_failing_alert_sink_is_logged_and_does_not_raise(monkeypatch, caplog):
    import internal_alerts

    def _boom(*_a, **_k):
        raise RuntimeError("sink down")

    monkeypatch.setattr(internal_alerts, "emit_internal_alert", _boom)
    event = wmo.OutageEvent(wmo.ALERT_UNREACHABLE, 3, 120, "HTTP 503", 120)
    with caplog.at_level(logging.ERROR, logger=wmo.__name__):
        wmo.report_outage_event(event)
    assert any("webapp_metrics_unreachable" in rec.getMessage() and rec.exc_info for rec in caplog.records)


# --- קריאה אמיתית מול שרת HTTP ----------------------------------------------------------------------------------


@pytest.fixture
def clean_http(monkeypatch):
    """מעגלים נקיים, ואירועי ``http_async`` נאספים במקום ללכת ל-``observability``."""
    events: list[dict] = []
    monkeypatch.setattr(resilience, "_CIRCUITS", {})
    monkeypatch.setattr(http_async, "_emit_event", lambda event, **f: events.append({"event": event, **f}))
    return events


@pytest.fixture
async def metrics_server():
    """שרת ``/metrics`` שהסטטוס והגוף שלו נקבעים מהטסט: ``state["status"]``, ``state["body"]``."""
    state = {"status": 200, "body": b"adaptive_current_error_rate_percent 0.5\n"}

    async def _handler(_request):
        return web.Response(status=state["status"], body=state["body"], content_type="text/plain")

    app = web.Application()
    app.router.add_get("/metrics", _handler)
    server = TestServer(app, host="127.0.0.1")
    await server.start_server()
    try:
        yield server, state
    finally:
        await server.close()


def _closed_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


async def test_scrape_success_returns_the_text(clean_http, metrics_server):
    server, _state = metrics_server
    result = await wmo.scrape_metrics(str(server.make_url("/metrics")))
    assert result.ok
    assert result.text == "adaptive_current_error_rate_percent 0.5\n"
    assert clean_http == []


async def test_scrape_503_is_a_failure_logged_as_warning_not_error(clean_http, metrics_server):
    """זה כל התיקון: הכישלון הבודד לא יוצא כ-error, ולכן לא נפתח עליו issue ב-Sentry."""
    server, state = metrics_server
    state["status"] = 503
    result = await wmo.scrape_metrics(str(server.make_url("/metrics")))
    assert not result.ok
    assert result.failure_reason == "HTTP 503"
    failures = [e for e in clean_http if e["event"] == "external_request_failure"]
    assert [e["severity"] for e in failures] == ["warning"]


async def test_a_single_failure_does_not_reach_sentry(monkeypatch, metrics_server):
    """הקצה של השרשרת: ``observability.emit_event`` האמיתי, עם ``sentry_sdk`` מזויף שאוסף את מה שנשלח אליו.

    ריצת הבקרה בסוף — אותה בקשה בלי ``failure_severity`` — מגיעה ל-Sentry, וכך הטסט מוכיח שהוא מסוגל לראות את מה
    שהוא בודק שלא קורה.
    """
    import sys
    import types

    import observability

    assert http_async._emit_event is observability.emit_event, "http_async must report through the real emit_event"

    captured: list[tuple] = []

    class _Scope:
        def set_tag(self, *_a):
            return None

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

    fake_sentry = types.ModuleType("sentry_sdk")
    fake_sentry.push_scope = lambda: _Scope()
    fake_sentry.capture_message = lambda msg, level=None: captured.append((msg, level))
    monkeypatch.setitem(sys.modules, "sentry_sdk", fake_sentry)
    monkeypatch.setattr(resilience, "_CIRCUITS", {})

    server, state = metrics_server
    state["status"] = 503
    url = str(server.make_url("/metrics"))

    result = await wmo.scrape_metrics(url)
    assert result.failure_reason == "HTTP 503"
    assert captured == []

    async with http_async.request("GET", url, service="webapp", endpoint="/metrics") as resp:
        assert resp.status == 503
    assert captured == [("external_request_failure", "error")]


async def test_scrape_404_is_a_failure_with_its_status(clean_http, metrics_server):
    server, state = metrics_server
    state["status"] = 404
    result = await wmo.scrape_metrics(str(server.make_url("/metrics")))
    assert result.failure_reason == "HTTP 404"


async def test_scrape_refused_connection_is_a_failure(clean_http):
    result = await wmo.scrape_metrics(f"http://127.0.0.1:{_closed_port()}/metrics")
    assert not result.ok
    assert result.failure_reason == "ClientConnectorError"


async def test_scrape_invalid_utf8_does_not_fail(clean_http, metrics_server):
    server, state = metrics_server
    state["body"] = b"metric_a 1\n\xff\xfe broken\n"
    result = await wmo.scrape_metrics(str(server.make_url("/metrics")))
    assert result.ok
    assert result.text.startswith("metric_a 1\n")


async def test_a_bug_propagates_and_is_not_counted(monkeypatch):
    """באג (כאן ``TypeError`` מתוך הבקשה) עולה, ולא נרשם במונה כ"הוובאפ לא זמין"."""

    class _Broken:
        async def __aenter__(self):
            raise TypeError("bug in our code")

        async def __aexit__(self, *_exc):
            return False

    monkeypatch.setattr(http_async, "request", lambda *a, **k: _Broken())
    clock = _Clock()
    tracker = _tracker(clock, threshold=0)
    with pytest.raises(TypeError):
        await wmo.scrape_and_track("http://127.0.0.1:9/metrics", tracker)
    # עם סף 0 כישלון אחד שנספר היה מתריע מיד; ההצלחה הבאה הייתה מחזירה התראת חזרה.
    assert tracker.record(OK) is None


async def test_scrape_and_track_end_to_end(clean_http, metrics_server, sent_alerts):
    """שלוש בדיקות כושלות מול שרת אמיתי ← התראה אחת; חזרה ל-200 ← התראת חזרה."""
    server, state = metrics_server
    url = str(server.make_url("/metrics"))
    clock = _Clock()
    tracker = _tracker(clock)

    state["status"] = 503
    for index in range(4):
        if index:
            clock.advance(60)
        result = await wmo.scrape_and_track(url, tracker)
        assert result.failure_reason == "HTTP 503"
    state["status"] = 200
    clock.advance(60)
    result = await wmo.scrape_and_track(url, tracker)
    assert result.ok

    assert [(a["name"], a["severity"]) for a in sent_alerts] == [
        ("webapp_metrics_unreachable", "error"),
        ("webapp_metrics_recovered", "info"),
    ]
    # ארבעת הכישלונות נרשמו ב-http_async כאזהרה, ואף אחד לא כ-error.
    severities = {e["severity"] for e in clean_http if e["event"] == "external_request_failure"}
    assert severities == {"warning"}


async def test_scrape_and_track_without_a_tracker_only_scrapes(clean_http, metrics_server, sent_alerts):
    server, state = metrics_server
    state["status"] = 503
    result = await wmo.scrape_and_track(str(server.make_url("/metrics")), None)
    assert result.failure_reason == "HTTP 503"
    assert sent_alerts == []


# --- עותקים שחייבים להישאר זהים -------------------------------------------------------------------------------------


def test_config_inspector_default_matches_the_code():
    from services.config_inspector_service import ConfigService

    definition = ConfigService.CONFIG_DEFINITIONS[wmo.OUTAGE_ALERT_SECS_ENV]
    assert definition.default == str(wmo.DEFAULT_OUTAGE_ALERT_SECS)


def test_the_unreachable_alert_has_a_runbook():
    path = Path(__file__).resolve().parents[1] / "config" / "observability_runbooks.yml"
    runbooks = yaml.safe_load(path.read_text(encoding="utf-8"))["runbooks"]
    assert wmo.ALERT_UNREACHABLE in runbooks
