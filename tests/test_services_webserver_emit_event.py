import asyncio
import pytest
import sys


@pytest.mark.asyncio
async def test_metrics_view_error_emits_event(monkeypatch):
    from aiohttp import web
    import services.webserver as sv

    # Force metrics to raise
    def _boom():
        raise RuntimeError("no metrics")
    monkeypatch.setattr(sv, "metrics_endpoint_bytes", _boom, raising=False)

    captured = {}
    def _emit(event, severity="info", **fields):
        captured.setdefault("events", []).append((event, severity, fields))

    # monkeypatch observability.emit_event imported inside the handler
    import types
    fake_obs = types.SimpleNamespace(emit_event=_emit)
    monkeypatch.setitem(sys.modules, 'observability', fake_obs)

    app = sv.create_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="127.0.0.1", port=0)
    await site.start()
    try:
        port = list(site._server.sockets)[0].getsockname()[1]
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.get(f"http://127.0.0.1:{port}/metrics") as resp:
                assert resp.status == 500
    finally:
        await runner.cleanup()

    assert any(e[0] == "metrics_view_error" for e in captured.get("events", []))
