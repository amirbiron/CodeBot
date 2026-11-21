"""השרת הפנימי של הבוט (``services/webserver.py``): כל בקשה בהקשר לוגים ו-scope של Sentry משלה.

השרת עולה מתוך ג'וב (``_start_web_job`` ב-``main.py``), ו-aiohttp פותח משימה לכל בקשה בתוך ההקשר שבו השרת עלה. מאז שכל
ריצת ג'וב מקבלת הקשר משלה (``IsolatedJobQueue``, ``services/telegram_observability_scope.py``), ההקשר הזה כולל
``command=job:_start_web_job`` — ובלי ``_observability_scope_mw`` כל בקשה הייתה נושאת אותו, וחולקת איתו את ה-isolation
scope של Sentry. הטסטים מעלים את השרת בתוך הקשר כזה, ובודקים מה הבקשה רואה, ובאיזה הקשר נרשמת חריגה שלה.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from http import HTTPStatus

import aiohttp
import pytest
import sentry_sdk
import structlog
from aiohttp import web


@contextlib.asynccontextmanager
async def _server_started_in_a_job_context(routes):
    """מעלה את ``create_app`` בתוך ההקשר שג'וב כורך (``bind_job_context``), ומחזיר את הכתובת ואת ה-scope של "הג'וב"."""
    import services.webserver as ws

    structlog.contextvars.bind_contextvars(command="job:_start_web_job", request_id="startjob")
    server_scope = sentry_sdk.get_isolation_scope()
    runner = None
    try:
        app = ws.create_app()
        for path, handler in routes.items():
            app.router.add_get(path, handler)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, host="127.0.0.1", port=0)
        await site.start()
        port = list(site._server.sockets)[0].getsockname()[1]
        yield f"http://127.0.0.1:{port}", server_scope
    finally:
        if runner is not None:
            await runner.cleanup()
        # ההקשר נכרך במשימה של הטסט; בלי ניקוי הוא נשאר לטסטים שרצים אחריו באותה לולאה.
        structlog.contextvars.clear_contextvars()


@pytest.mark.asyncio
async def test_a_request_does_not_inherit_the_context_the_server_started_in():
    seen: list[dict] = []

    async def probe_context(_request: web.Request) -> web.Response:
        seen.append(
            {
                "context": dict(structlog.contextvars.get_contextvars()),
                "isolation_scope": sentry_sdk.get_isolation_scope(),
            }
        )
        return web.json_response({})

    async with _server_started_in_a_job_context({"/probe-context": probe_context}) as (base, server_scope):
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
        assert observed["isolation_scope"] is not server_scope
    assert seen[0]["isolation_scope"] is not seen[1]["isolation_scope"]


class _RecordWithContext(logging.Handler):
    """שומר כל רשומה של ``aiohttp.server``, עם ההקשר של structlog וה-scope של Sentry ברגע הרישום — מה ש-
    ``LoggingIntegration`` היה מצרף לאירוע."""

    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.records: list[dict] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(
            {
                "message": record.getMessage(),
                "level": record.levelno,
                "context": dict(structlog.contextvars.get_contextvars()),
                "isolation_scope": sentry_sdk.get_isolation_scope(),
            }
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "status"),
    [(RuntimeError("probe: handler failed"), 500), (asyncio.TimeoutError(), 504)],
    ids=["exception", "timeout"],
)
async def test_a_failing_request_is_reported_once_inside_its_own_scope(error, status):
    inside: dict = {}

    async def failing(_request: web.Request) -> web.Response:
        inside["request_id"] = structlog.contextvars.get_contextvars().get("request_id")
        inside["isolation_scope"] = sentry_sdk.get_isolation_scope()
        raise error

    recorder = _RecordWithContext()
    server_logger = logging.getLogger("aiohttp.server")
    server_logger.addHandler(recorder)
    try:
        async with _server_started_in_a_job_context({"/fail": failing}) as (base, server_scope):
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{base}/fail") as resp:
                    body = await resp.text()
                    response_status = resp.status
    finally:
        server_logger.removeHandler(recorder)

    # התשובה כמו שהייתה: זו ש-``RequestHandler.handle_error`` של aiohttp בונה.
    assert response_status == status, body
    if status == 500:
        reason = HTTPStatus.INTERNAL_SERVER_ERROR
        assert body == f"{reason.value} {reason.phrase}\n\n{reason.description}", body

    errors = [rec for rec in recorder.records if rec["message"].startswith("Error handling request")]
    assert len(errors) == 1, recorder.records  # פעם אחת — לא גם כאן וגם ב-aiohttp
    (logged,) = errors
    assert logged["level"] == logging.ERROR, logged
    # נרשם בזמן שה-scope של הבקשה עוד פעיל: עם ה-request_id שלה ובלי ה-command של הג'וב שהעלה את השרת.
    assert inside["request_id"] and logged["context"].get("request_id") == inside["request_id"], (inside, logged)
    assert "command" not in logged["context"], logged
    assert logged["isolation_scope"] is inside["isolation_scope"]
    assert logged["isolation_scope"] is not server_scope


@pytest.mark.asyncio
async def test_an_http_exception_stays_the_response_and_is_not_reported():
    async def not_found(_request: web.Request) -> web.Response:
        raise web.HTTPNotFound(text="probe: no such thing")

    recorder = _RecordWithContext()
    server_logger = logging.getLogger("aiohttp.server")
    server_logger.addHandler(recorder)
    try:
        async with _server_started_in_a_job_context({"/missing": not_found}) as (base, _server_scope):
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{base}/missing") as resp:
                    assert resp.status == 404
                    assert await resp.text() == "probe: no such thing"
    finally:
        server_logger.removeHandler(recorder)

    assert not [rec for rec in recorder.records if rec["message"].startswith("Error handling request")], recorder.records
