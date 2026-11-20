"""השרת הפנימי של הבוט (``services/webserver.py``): כל בקשה בהקשר לוגים ו-scope של Sentry משלה.

השרת עולה מתוך ג'וב (``_start_web_job`` ב-``main.py``), ו-aiohttp פותח משימה לכל בקשה בתוך ההקשר שבו השרת עלה. מאז שכל
ריצת ג'וב מקבלת הקשר משלה (``IsolatedJobQueue``, ‏``services/telegram_observability_scope.py``), ההקשר הזה כולל
``command=job:_start_web_job`` — ובלי ``_observability_scope_mw`` כל בקשה הייתה נושאת אותו, וחולקת איתו את ה-isolation
scope של Sentry. הטסט מעלה את השרת בתוך הקשר כזה, ובודק מה הבקשה רואה.
"""

from __future__ import annotations

import aiohttp
import pytest
import sentry_sdk
import structlog
from aiohttp import web


@pytest.mark.asyncio
async def test_a_request_does_not_inherit_the_context_the_server_started_in():
    import services.webserver as ws

    seen: dict = {}

    async def probe_context(_request: web.Request) -> web.Response:
        seen["context"] = dict(structlog.contextvars.get_contextvars())
        seen["isolation_scope"] = sentry_sdk.get_isolation_scope()
        return web.json_response({})

    # ההקשר של הג'וב שהעלה את השרת, כמו ש-``bind_job_context`` כורך אותו.
    structlog.contextvars.bind_contextvars(command="job:_start_web_job", request_id="startjob")
    server_scope = sentry_sdk.get_isolation_scope()
    runner = None
    try:
        app = ws.create_app()
        app.router.add_get("/probe-context", probe_context)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, host="127.0.0.1", port=0)
        await site.start()
        port = list(site._server.sockets)[0].getsockname()[1]
        async with aiohttp.ClientSession() as session:
            async with session.get(f"http://127.0.0.1:{port}/probe-context") as resp:
                assert resp.status == 200
                request_id = resp.headers.get("X-Request-ID")
    finally:
        if runner is not None:
            await runner.cleanup()
        # ההקשר נכרך במשימה של הטסט; בלי ניקוי הוא נשאר לטסטים שרצים אחריו באותה לולאה.
        structlog.contextvars.clear_contextvars()

    context = seen["context"]
    assert "command" not in context, context
    assert request_id and context.get("request_id") == request_id, (request_id, context)
    assert seen["isolation_scope"] is not server_scope
