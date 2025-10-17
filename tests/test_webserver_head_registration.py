import pytest
from aiohttp import web

from services.webserver import create_app


@pytest.mark.asyncio
async def test_routes_register_once_without_head_conflicts():
    app = create_app()
    runner = web.AppRunner(app)
    await runner.setup()
    try:
        # collecting route names/methods ensures no duplicates (HEAD will be auto-provided by aiohttp once)
        routes = [(r.method, r.resource.canonical) for r in app.router.routes()]
        # there should be exactly one GET for '/health' (don't match '/healthz')
        get_health = [r for r in routes if r[0] == 'GET' and r[1] == '/health']
        get_metrics = [r for r in routes if r[0] == 'GET' and '/metrics' in r[1]]
        get_share = [r for r in routes if r[0] == 'GET' and '/share/' in r[1]]
        assert len(get_health) == 1
        assert len(get_metrics) == 1
        assert len(get_share) == 1
    finally:
        await runner.cleanup()
