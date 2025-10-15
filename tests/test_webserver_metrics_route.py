import asyncio
import pytest

from services.webserver import create_app


@pytest.mark.asyncio
async def test_metrics_endpoint_works(monkeypatch):
    from aiohttp import web

    # Make metrics return deterministic content
    def _payload():
        return b"metric_a 1\n"
    def _ctype():
        return "text/plain; charset=utf-8"

    import services.webserver as sv
    monkeypatch.setattr(sv, "metrics_endpoint_bytes", _payload, raising=False)
    monkeypatch.setattr(sv, "metrics_content_type", _ctype, raising=False)

    app = create_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="127.0.0.1", port=0)
    await site.start()
    try:
        port = list(site._server.sockets)[0].getsockname()[1]
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.get(f"http://127.0.0.1:{port}/metrics") as resp:
                assert resp.status == 200
                text = await resp.text()
                assert "metric_a 1" in text
    finally:
        await runner.cleanup()
