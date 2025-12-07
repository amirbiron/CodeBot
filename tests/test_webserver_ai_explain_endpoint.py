import pytest


@pytest.mark.asyncio
async def test_ai_explain_endpoint_requires_token(monkeypatch):
    import services.webserver as ws

    monkeypatch.setattr(ws, "_AI_ROUTE_TOKEN", "secret-token")

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
            async with session.post(f"http://127.0.0.1:{port}/api/ai/explain", json={"context": {}}) as resp:
                assert resp.status == 401
                data = await resp.json()
                assert data["error"] == "unauthorized"
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_ai_explain_endpoint_returns_payload(monkeypatch):
    import services.webserver as ws

    monkeypatch.setattr(ws, "_AI_ROUTE_TOKEN", "")

    async def fake_generate(context, *, expected_sections=None, request_id=None):  # noqa: ARG001
        return {
            "root_cause": "DB locks",
            "actions": ["restart db"],
            "signals": ["latency spike"],
            "provider": "claude",
            "generated_at": "2025-01-01T00:00:00Z",
            "cached": False,
            "alert_uid": context.get("alert_uid"),
        }

    monkeypatch.setattr(ws.ai_explain_service, "generate_ai_explanation", fake_generate)

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
            payload = {"context": {"alert_uid": "uid-123"}}
            async with session.post(f"http://127.0.0.1:{port}/api/ai/explain", json=payload) as resp:
                assert resp.status == 200
                data = await resp.json()
                assert data["root_cause"] == "DB locks"
                assert data["alert_uid"] == "uid-123"
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_ai_explain_endpoint_maps_provider_error(monkeypatch):
    import services.webserver as ws

    monkeypatch.setattr(ws, "_AI_ROUTE_TOKEN", "")

    async def fake_generate(context, *, expected_sections=None, request_id=None):  # noqa: ARG001
        raise ws.ai_explain_service.AiExplainError("anthropic_api_key_missing")

    monkeypatch.setattr(ws.ai_explain_service, "generate_ai_explanation", fake_generate)

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
            payload = {"context": {"alert_uid": "uid-err"}}
            async with session.post(f"http://127.0.0.1:{port}/api/ai/explain", json=payload) as resp:
                assert resp.status == 503
                data = await resp.json()
                assert data["error"] == "anthropic_api_key_missing"
    finally:
        await runner.cleanup()
