import asyncio
import sys
import types
import pytest


@pytest.mark.asyncio
async def test_request_id_middleware_emits_event_on_bind_failure(monkeypatch):
    import services.webserver as ws

    events: list[tuple[str, str, dict]] = []

    def fake_emit(event: str, severity: str = "info", **fields):
        events.append((event, severity, fields))

    def boom_bind(_rid: str) -> None:
        raise RuntimeError("bind failed")

    monkeypatch.setattr(ws, "generate_request_id", lambda: "test-rid")
    monkeypatch.setattr(ws, "emit_event", fake_emit)
    monkeypatch.setattr(ws, "bind_request_id", boom_bind)

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
            async with session.get(f"http://127.0.0.1:{port}/health") as resp:
                assert resp.status == 200
                assert resp.headers.get("X-Request-ID") == "test-rid"
    finally:
        await runner.cleanup()

    names = [e[0] for e in events]
    assert "bind_request_id_failed" in names
    idx = names.index("bind_request_id_failed")
    _, sev, fields = events[idx]
    assert sev == "anomaly"
    assert fields.get("handled") is True
    assert fields.get("request_id") == "test-rid"


@pytest.mark.asyncio
async def test_alerts_forward_failure_emits_anomaly_event(monkeypatch):
    # Inject a dummy alert_forwarder that raises
    mod = types.ModuleType("alert_forwarder")

    def forward_alerts(_alerts):  # type: ignore
        raise RuntimeError("forward boom")

    mod.forward_alerts = forward_alerts  # type: ignore[attr-defined]
    sys.modules["alert_forwarder"] = mod

    import services.webserver as ws

    events: list[tuple[str, str, dict]] = []

    def fake_emit(event: str, severity: str = "info", **fields):
        events.append((event, severity, fields))

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
                f"http://127.0.0.1:{port}/alerts", json={"alerts": [{"labels": {}, "annotations": {}}]}
            ) as resp:
                assert resp.status == 200
                data = await resp.json()
                assert data.get("status") == "ok"
    finally:
        await runner.cleanup()

    names = [e[0] for e in events]
    assert "alert_received" in names  # baseline counter
    assert "alerts_forward_failed" in names
    idx = names.index("alerts_forward_failed")
    _, sev, fields = events[idx]
    assert sev == "anomaly" and fields.get("handled") is True


@pytest.mark.asyncio
async def test_record_request_outcome_failure_emits_anomaly_event(monkeypatch):
    import services.webserver as ws

    events: list[tuple[str, str, dict]] = []

    def fake_emit(event: str, severity: str = "info", **fields):
        events.append((event, severity, fields))

    def boom_record(_status: int, _dur: float) -> None:
        raise RuntimeError("metrics boom")

    monkeypatch.setattr(ws, "emit_event", fake_emit)
    monkeypatch.setattr(ws, "record_request_outcome", boom_record)

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
            async with session.get(f"http://127.0.0.1:{port}/health") as resp:
                assert resp.status == 200
    finally:
        await runner.cleanup()

    names = [e[0] for e in events]
    assert "record_request_outcome_failed" in names
    idx = names.index("record_request_outcome_failed")
    _, sev, fields = events[idx]
    assert sev == "anomaly" and fields.get("handled") is True


@pytest.mark.asyncio
async def test_metrics_view_error_emits_event_and_returns_500(monkeypatch):
    import services.webserver as ws

    events: list[tuple[str, str, dict]] = []

    def fake_emit(event: str, severity: str = "info", **fields):
        events.append((event, severity, fields))

    def boom_metrics():  # type: ignore
        raise RuntimeError("metrics boom")

    monkeypatch.setattr(ws, "emit_event", fake_emit)
    monkeypatch.setattr(ws, "metrics_endpoint_bytes", boom_metrics)

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
            async with session.get(f"http://127.0.0.1:{port}/metrics") as resp:
                assert resp.status == 500
                text = await resp.text()
                assert "metrics error" in text
    finally:
        await runner.cleanup()

    names = [e[0] for e in events]
    assert "metrics_view_error" in names


@pytest.mark.asyncio
async def test_share_view_error_and_not_found_events(monkeypatch):
    import services.webserver as ws
    import integrations as integ

    events: list[tuple[str, str, dict]] = []

    def fake_emit(event: str, severity: str = "info", **fields):
        events.append((event, severity, fields))

    def boom_share(_share_id: str):
        raise RuntimeError("share boom")

    monkeypatch.setattr(ws, "emit_event", fake_emit)
    monkeypatch.setattr(integ.code_sharing, "get_internal_share", boom_share)

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
            async with session.get(f"http://127.0.0.1:{port}/share/boom") as resp:
                # Handler should degrade to 404 after logging and anomaly
                assert resp.status == 404
    finally:
        await runner.cleanup()

    names = [e[0] for e in events]
    assert "share_view_error" in names
    assert "share_view_not_found" in names
