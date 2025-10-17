import pytest
import re


def _parse_prometheus_text(data: bytes) -> dict:
    """Very simple Prometheus text parser: collects metric names found."""
    names = set()
    for line in data.decode("utf-8", errors="ignore").splitlines():
        if not line or line.startswith("#"):
            continue
        # metric name until first '{' or space
        m = re.match(r"^([a-zA-Z_:][a-zA-Z0-9_:]*)(?:\{|\s)", line)
        if m:
            names.add(m.group(1))
    return {"names": names}


def test_metrics_contains_new_observability_v3(monkeypatch):
    try:
        import webapp.app as flask_app
    except Exception:
        pytest.skip("Flask app not importable")

    app = flask_app.app
    try:
        client = app.test_client()
    except Exception:
        pytest.skip("Flask test client not available")

    resp = client.get("/metrics")
    assert resp.status_code in (200, 503)
    data = resp.data

    # If metrics are disabled (503), skip parsing assertions
    if resp.status_code != 200:
        pytest.skip("metrics disabled or unavailable")

    parsed = _parse_prometheus_text(data)
    names = parsed["names"]
    # New metrics
    assert "codebot_uptime_seconds_total" in names
    assert "codebot_alerts_total" in names
    assert "codebot_error_rate_percent" in names


def test_alerts_json_endpoint_available_aiohttp():
    # Validate /alerts returns JSON on aiohttp service
    try:
        from services.webserver import create_app
        from aiohttp import web
    except Exception:
        pytest.skip("aiohttp not available")

    app = create_app()
    runner = web.AppRunner(app)
    import asyncio
    async def _run():
        await runner.setup()
        site = web.TCPSite(runner, host="127.0.0.1", port=0)
        await site.start()
        try:
            port = list(site._server.sockets)[0].getsockname()[1]
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(f"http://127.0.0.1:{port}/alerts") as resp:
                    assert resp.status == 200
                    js = await resp.json()
                    assert "alerts" in js
        finally:
            await runner.cleanup()
    asyncio.get_event_loop().run_until_complete(_run())
