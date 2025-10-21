import asyncio
import pytest


@pytest.mark.asyncio
async def test_health_endpoint_ok(monkeypatch):
    from services.webserver import create_app

    app = create_app()
    # Use app's test client via aiohttp
    from aiohttp import web
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="127.0.0.1", port=0)
    await site.start()
    try:
        port = list(site._server.sockets)[0].getsockname()[1]
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.get(f"http://127.0.0.1:{port}/health") as resp:
                assert resp.status == 200
                data = await resp.json()
                assert data.get("status") == "ok"
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_share_not_found_returns_404(monkeypatch):
    from services.webserver import create_app
    import integrations as integ

    # Force code_sharing.get_internal_share to return None
    def _get_none(_id):
        return None
    monkeypatch.setattr(integ.code_sharing, "get_internal_share", _get_none)

    app = create_app()
    from aiohttp import web
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="127.0.0.1", port=0)
    await site.start()
    try:
        port = list(site._server.sockets)[0].getsockname()[1]
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.get(f"http://127.0.0.1:{port}/share/does-not-exist") as resp:
                assert resp.status == 404
                text = await resp.text()
                assert "Share not found" in text
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_share_found_returns_html(monkeypatch):
    from services.webserver import create_app
    import integrations as integ

    def _get_share(_id):
        return {"file_name": "file.py", "code": "print('hi')", "language": "python"}
    monkeypatch.setattr(integ.code_sharing, "get_internal_share", _get_share)

    app = create_app()
    from aiohttp import web
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="127.0.0.1", port=0)
    await site.start()
    try:
        port = list(site._server.sockets)[0].getsockname()[1]
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.get(f"http://127.0.0.1:{port}/share/abc123") as resp:
                assert resp.status == 200
                assert resp.headers.get("Content-Type", "").startswith("text/html")
                text = await resp.text()
                assert "file.py" in text and "print(&#x27;hi&#x27;)" in text
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_alerts_parse_error_emits_event(monkeypatch):
    # Simulate invalid JSON body to trigger alerts_parse_error path
    import services.webserver as ws

    captured = []

    def fake_emit(event: str, severity: str = "info", **fields):
        captured.append((event, severity, fields))

    monkeypatch.setattr(ws, "emit_event", fake_emit)
    app = ws.create_app()

    from aiohttp import web
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="127.0.0.1", port=0)
    await site.start()
    try:
        port = list(site._server.sockets)[0].getsockname()[1]
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"http://127.0.0.1:{port}/alerts", data="{this is not json}"
            ) as resp:
                assert resp.status == 400
    finally:
        await runner.cleanup()

    names = [e[0] for e in captured]
    assert "alerts_parse_error" in names

