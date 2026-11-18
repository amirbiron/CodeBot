"""הג'וב ``predictive_sampler`` ב-``main.py``, מקצה לקצה: הסמפלר האמיתי, מול שרת ``/metrics`` אמיתי על ``127.0.0.1``.

``setup_bot_data`` רץ עם JobQueue מזויף שרק אוסף את הג'ובים (כמו ``tests/test_cache_maintenance_job.py``), ואז הטסט
מריץ את ``predictive_sampler`` בעצמו, הרצה אחרי הרצה — כך שנבדק גם החיווט ב-``main.py``: שהתדירות מהתזמון מגיעה
למונה, שהמונה נשמר בין הרצות, ושהכישלון הבודד לא יוצא כ-``error``.
"""

from __future__ import annotations

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

import http_async
import resilience


@pytest.fixture
async def metrics_server():
    state = {"status": 200}

    async def _handler(_request):
        return web.Response(status=state["status"], text="adaptive_current_error_rate_percent 0.5\n")

    app = web.Application()
    app.router.add_get("/metrics", _handler)
    server = TestServer(app, host="127.0.0.1")
    await server.start_server()
    try:
        yield server, state
    finally:
        await server.close()


async def _sampler_job(monkeypatch, base_url: str):
    """מריץ את ``setup_bot_data`` ומחזיר את הג'וב ``predictive_sampler`` שהוא תזמן, יחד עם התדירות שנמסרה."""
    import main as m

    scheduled: dict = {}

    class _JobQ:
        def run_repeating(self, fn, interval, first, name=None):  # noqa: ARG002
            scheduled[name] = (fn, interval)

        def run_once(self, fn, when, name=None, **_k):  # noqa: ARG002
            scheduled.setdefault(name, (fn, None))

        def run_daily(self, fn, *_a, name=None, **_k):
            scheduled.setdefault(name, (fn, None))

    class _Bot:
        async def delete_my_commands(self, *a, **k):  # noqa: ARG002
            return None

        async def set_my_commands(self, *a, **k):  # noqa: ARG002
            return None

    class _App:
        job_queue = _JobQ()
        bot = _Bot()
        bot_data: dict = {}

    monkeypatch.setenv("PREDICTIVE_SAMPLER_RUN_IN_TESTS", "true")
    monkeypatch.setenv("PREDICTIVE_SAMPLER_ENABLED", "true")
    monkeypatch.setenv("PREDICTIVE_SAMPLER_METRICS_URL", base_url)
    monkeypatch.delenv("PREDICTIVE_SAMPLER_INTERVAL_SECS", raising=False)
    monkeypatch.delenv("PREDICTIVE_SAMPLER_OUTAGE_ALERT_SECS", raising=False)

    await m.setup_bot_data(_App())
    assert "predictive_sampler" in scheduled, sorted(k for k in scheduled if k)
    return scheduled["predictive_sampler"]


async def test_sampler_alerts_only_after_two_minutes_of_failures(monkeypatch, metrics_server):
    import internal_alerts

    server, state = metrics_server
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(
        internal_alerts,
        "emit_internal_alert",
        lambda name, severity="info", summary="", **_d: sent.append((name, severity)),
    )
    http_events: list[dict] = []
    monkeypatch.setattr(http_async, "_emit_event", lambda event, **f: http_events.append({"event": event, **f}))
    monkeypatch.setattr(resilience, "_CIRCUITS", {})

    job, interval = await _sampler_job(monkeypatch, str(server.make_url("/")).rstrip("/"))
    assert interval == 60

    # דיפלוי: הרצה אחת נכשלת, הבאה מצליחה — בלי התראה.
    state["status"] = 503
    await job(None)
    state["status"] = 200
    await job(None)
    assert sent == []

    # השבתה: שתי הרצות כושלות עוד לא מתריעות; השלישית (2 דקות בתדירות 60) מתריעה, והרביעית לא שוב.
    state["status"] = 503
    await job(None)
    await job(None)
    assert sent == []
    await job(None)
    assert sent == [("webapp_metrics_unreachable", "error")]
    await job(None)
    assert sent == [("webapp_metrics_unreachable", "error")]

    # חזרה.
    state["status"] = 200
    await job(None)
    assert sent == [("webapp_metrics_unreachable", "error"), ("webapp_metrics_recovered", "info")]

    # אף כישלון בודד לא יצא כ-error — זה מה שפתח issue ב-Sentry ושלח לטלגרם בכל דיפלוי.
    failures = [e for e in http_events if e["event"] == "external_request_failure"]
    assert len(failures) == 5
    assert {e["severity"] for e in failures} == {"warning"}
