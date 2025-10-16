import asyncio
import json
import types
import importlib
import pytest

from services.webserver import create_app


@pytest.mark.asyncio
async def test_alerts_endpoint_forwards_and_responds(monkeypatch):
    from aiohttp import web

    # Capture forwarding
    forwarded = {"count": 0, "alerts": []}
    def _forward(alerts):
        forwarded["count"] += len(alerts)
        forwarded["alerts"].extend(alerts)
    import services.webserver as sv
    monkeypatch.setitem(importlib.sys.modules, "alert_forwarder", types.SimpleNamespace(forward_alerts=_forward))

    app = create_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="127.0.0.1", port=0)
    await site.start()
    try:
        port = list(site._server.sockets)[0].getsockname()[1]
        import aiohttp
        async with aiohttp.ClientSession() as session:
            payload = {"alerts": [{"status": "firing", "labels": {"alertname": "Ping"}}]}
            async with session.post(f"http://127.0.0.1:{port}/alerts", data=json.dumps(payload)) as resp:
                assert resp.status == 200
                data = await resp.json()
                assert data.get("forwarded") == 1
        # Ensure our forwarder was called
        assert forwarded["count"] == 1
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_alerts_endpoint_handles_bad_json(monkeypatch):
    from aiohttp import web
    app = create_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="127.0.0.1", port=0)
    await site.start()
    try:
        port = list(site._server.sockets)[0].getsockname()[1]
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.post(f"http://127.0.0.1:{port}/alerts", data="{not-json}") as resp:
                assert resp.status == 400
    finally:
        await runner.cleanup()
