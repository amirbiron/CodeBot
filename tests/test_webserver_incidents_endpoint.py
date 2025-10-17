import asyncio
import pytest


@pytest.mark.asyncio
async def test_webserver_incidents_endpoint(tmp_path, monkeypatch):
    (tmp_path / "data").mkdir()
    monkeypatch.chdir(tmp_path)

    # Seed an incident via remediation manager (avoid network calls)
    import sys, types, importlib
    monkeypatch.setitem(sys.modules, 'observability', types.SimpleNamespace(emit_event=lambda *a, **k: None))
    rm = importlib.import_module('remediation_manager')
    rm.handle_critical_incident("High Error Rate", "error_rate_percent", 11.0, 10.0, {"current_percent": 11.0})

    from aiohttp import web
    import services.webserver as sv

    app = sv.create_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="127.0.0.1", port=0)
    await site.start()
    try:
        port = list(site._server.sockets)[0].getsockname()[1]
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.get(f"http://127.0.0.1:{port}/incidents?limit=1") as resp:
                assert resp.status == 200
                data = await resp.json()
                assert isinstance(data.get('incidents'), list)
    finally:
        await runner.cleanup()
}