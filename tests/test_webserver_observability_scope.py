"""השרת הפנימי של הבוט (``services/webserver.py``): כל בקשה מתחילה בלי ההקשר של הג'וב שהעלה את השרת.

השרת עולה מתוך ג'וב (``_start_web_job`` ב-``main.py``), והג'וב רץ ב-``isolated_observability_scope`` עם
``command=job:_start_web_job`` ו-scope משלו ב-Sentry. aiohttp פותח משימה לכל בקשה בתוך ההקשר שבו השרת התחיל להאזין, ולכן
``start_site_in_empty_context`` מעלה אותו בהקשר ריק. כאן השרת עולה בדיוק כך — מתוך "ג'וב" עם הקשר — ונבדק מה הבקשה רואה,
ומה מגיע ל-Sentry כשה-handler זורק.

Sentry: לקוח אמיתי עם transport שאוסף את האירועים, ושתי האינטגרציות שקובעות את המסלול הזה בפרודקשן: ``LoggingIntegration``
באותה תצורה כמו ב-``observability.init_sentry``, ו-``AioHttpIntegration`` — ש-``init_sentry`` לא מכבה, ו-sentry-sdk 2.42.1
מדליק לבד כש-aiohttp מותקן (``_AUTO_ENABLING_INTEGRATIONS``). שאר האינטגרציות כבויות, כמו שממליץ ``tests/_sentry_isolation.py``,
ובסוף כל טסט הלקוח מנותק ב-``shut_down_sentry``.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from http import HTTPStatus

import _sentry_isolation
import aiohttp
import pytest
import sentry_sdk
import structlog
from aiohttp import web
from sentry_sdk.integrations.aiohttp import AioHttpIntegration
from sentry_sdk.integrations.logging import LoggingIntegration
from sentry_sdk.transport import Transport

import observability


@pytest.fixture
def sentry_events():
    events: list[dict] = []

    class _Collect(Transport):
        def capture_envelope(self, envelope) -> None:
            event = envelope.get_event()
            if event is not None:
                events.append(event)

    sentry_sdk.init(
        dsn="https://public@127.0.0.1/1",
        transport=_Collect(),
        default_integrations=False,
        auto_enabling_integrations=False,
        integrations=[LoggingIntegration(level=logging.INFO, event_level=logging.ERROR), AioHttpIntegration()],
    )
    try:
        yield events
    finally:
        _sentry_isolation.shut_down_sentry()


@contextlib.asynccontextmanager
async def _server_started_from_a_job(routes):
    """מעלה את ``create_app`` כמו ``_start_web_job``: מתוך ``isolated_observability_scope`` עם ההקשר של ג'וב, דרך
    ``start_site_in_empty_context``. מחזיר את הכתובת ואת ה-scope של "הג'וב"."""
    import services.webserver as ws

    runner = None
    with observability.isolated_observability_scope():
        observability.bind_request_id("startjob")
        observability.bind_command("job:_start_web_job")
        job_scope = sentry_sdk.get_isolation_scope()
        try:
            app = ws.create_app()
            for path, handler in routes.items():
                app.router.add_get(path, handler)
            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, host="127.0.0.1", port=0)
            await ws.start_site_in_empty_context(site)
            port = list(site._server.sockets)[0].getsockname()[1]
            yield f"http://127.0.0.1:{port}", job_scope
        finally:
            if runner is not None:
                await runner.cleanup()


def _tags(event: dict) -> dict:
    return event.get("tags") or {}


@pytest.mark.asyncio
async def test_a_request_does_not_inherit_the_context_of_the_job_that_started_the_server(sentry_events):
    seen: list[dict] = []

    async def probe_context(_request: web.Request) -> web.Response:
        seen.append(
            {
                "context": dict(structlog.contextvars.get_contextvars()),
                "isolation_scope": sentry_sdk.get_isolation_scope(),
            }
        )
        sentry_sdk.capture_message("probe: inside the request")
        return web.json_response({})

    async with _server_started_from_a_job({"/probe-context": probe_context}) as (base, job_scope):
        request_ids = []
        # שתי בקשות על אותו חיבור (keep-alive של ``ClientSession``): גם השנייה מתחילה נקייה, ולא רק הראשונה.
        async with aiohttp.ClientSession() as session:
            for _ in range(2):
                async with session.get(f"{base}/probe-context") as resp:
                    assert resp.status == 200
                    request_ids.append(resp.headers.get("X-Request-ID"))

    assert len(seen) == 2 and all(request_ids) and request_ids[0] != request_ids[1], (seen, request_ids)
    for observed, request_id in zip(seen, request_ids):
        assert "command" not in observed["context"], observed
        assert observed["context"].get("request_id") == request_id, (observed, request_id)
        assert observed["isolation_scope"] is not job_scope
    assert seen[0]["isolation_scope"] is not seen[1]["isolation_scope"]

    messages = [event for event in sentry_events if event.get("message") == "probe: inside the request"]
    assert [_tags(event).get("request_id") for event in messages] == request_ids, messages
    assert all("command" not in _tags(event) for event in messages), messages


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "status"),
    [(RuntimeError("probe: handler failed"), 500), (asyncio.TimeoutError(), 504)],
    ids=["exception", "timeout"],
)
async def test_a_failing_request_reaches_sentry_once_with_its_own_request_id(sentry_events, error, status):
    inside: dict = {}

    async def failing(_request: web.Request) -> web.Response:
        inside["request_id"] = structlog.contextvars.get_contextvars().get("request_id")
        raise error

    async with _server_started_from_a_job({"/fail": failing}) as (base, _job_scope):
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{base}/fail") as resp:
                body = await resp.text()
                response_status = resp.status

    # התשובה של aiohttp עצמו (``RequestHandler.handle_error``), כמו לפני שהשרת עלה בהקשר ריק.
    assert response_status == status, body
    if status == 500:
        reason = HTTPStatus.INTERNAL_SERVER_ERROR
        assert body == f"{reason.value} {reason.phrase}\n\n{reason.description}", body

    # אירוע אחד: ``AioHttpIntegration`` תפס את החריגה, והלוג של aiohttp על אותה חריגה מושתק ב-``LoggingIntegration``.
    assert len(sentry_events) == 1, [(e.get("message"), e.get("exception"), _tags(e)) for e in sentry_events]
    (event,) = sentry_events
    assert inside["request_id"] and _tags(event).get("request_id") == inside["request_id"], (inside, _tags(event))
    assert "command" not in _tags(event), _tags(event)
    assert event["exception"]["values"][-1]["type"] == type(error).__name__, event["exception"]


@pytest.mark.asyncio
async def test_an_http_exception_stays_the_response_and_is_not_reported(sentry_events):
    async def not_found(_request: web.Request) -> web.Response:
        raise web.HTTPNotFound(text="probe: no such thing")

    async with _server_started_from_a_job({"/missing": not_found}) as (base, _job_scope):
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{base}/missing") as resp:
                assert resp.status == 404
                assert await resp.text() == "probe: no such thing"

    assert sentry_events == [], sentry_events
