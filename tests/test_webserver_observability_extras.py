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
    # Ensure cleanup after test via monkeypatch fixture
    monkeypatch.setitem(sys.modules, "alert_forwarder", mod)

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


@pytest.mark.asyncio
async def test_access_logs_includes_queue_delay_when_header_missing(monkeypatch):
    import services.webserver as ws

    events: list[tuple[str, str, dict]] = []

    def fake_emit(event: str, severity: str = "info", **fields):
        events.append((event, severity, fields))

    # Freeze wall clock to make queue_delay deterministic
    monkeypatch.setattr(ws, "emit_event", fake_emit)
    monkeypatch.setattr(ws.time, "time", lambda: 1700000000.0)

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
            async with session.get(f"http://127.0.0.1:{port}/incidents") as resp:
                assert resp.status == 200
    finally:
        await runner.cleanup()

    access = [e for e in events if e[0] == "access_logs"]
    assert access, "expected an access_logs structured event"
    _name, sev, fields = access[-1]
    assert sev == "info"
    assert fields.get("queue_delay") == 0


@pytest.mark.asyncio
async def test_queue_delay_parses_x_request_start_and_emits_warning(monkeypatch):
    import services.webserver as ws

    events: list[tuple[str, str, dict]] = []

    def fake_emit(event: str, severity: str = "info", **fields):
        events.append((event, severity, fields))

    # now=1700000000.0, header=1699999999.4 -> 600ms delay
    monkeypatch.setattr(ws, "emit_event", fake_emit)
    monkeypatch.setattr(ws.time, "time", lambda: 1700000000.0)

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
            async with session.get(
                f"http://127.0.0.1:{port}/incidents",
                headers={"X-Request-Start": "t=1699999999.4"},
            ) as resp:
                assert resp.status == 200
    finally:
        await runner.cleanup()

    access = [e for e in events if e[0] == "access_logs"]
    assert access, "expected an access_logs structured event"
    _name, sev, fields = access[-1]
    assert sev == "info"
    assert fields.get("queue_delay") == 600
    assert fields.get("queue_delay_source") == "X-Request-Start"

    warns = [e for e in events if e[0] == "queue_delay_high"]
    assert warns, "expected a queue_delay_high warning event"
    _n, wsev, wfields = warns[-1]
    assert wsev in {"warn", "warning"}
    assert wfields.get("queue_delay") == 600
    assert wfields.get("threshold_ms") == 500


@pytest.mark.asyncio
async def test_queue_delay_prefers_x_queue_start_ms(monkeypatch):
    import services.webserver as ws

    events: list[tuple[str, str, dict]] = []

    def fake_emit(event: str, severity: str = "info", **fields):
        events.append((event, severity, fields))

    # now=1700000000.0s -> 1700000000000ms, header=1699999999400ms -> 600ms delay
    monkeypatch.setattr(ws, "emit_event", fake_emit)
    monkeypatch.setattr(ws.time, "time", lambda: 1700000000.0)

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
            async with session.get(
                f"http://127.0.0.1:{port}/incidents",
                headers={
                    "X-Queue-Start": "1699999999400",
                    "X-Request-Start": "t=1699999990.0",
                },
            ) as resp:
                assert resp.status == 200
    finally:
        await runner.cleanup()

    access = [e for e in events if e[0] == "access_logs"]
    assert access, "expected an access_logs structured event"
    _name, _sev, fields = access[-1]
    assert fields.get("queue_delay") == 600
    assert fields.get("queue_delay_source") == "X-Queue-Start"


@pytest.mark.asyncio
async def test_access_logs_silenced_for_monitoring_endpoints_when_ok(monkeypatch):
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
            async with session.get(f"http://127.0.0.1:{port}/health") as resp:
                assert resp.status == 200
            async with session.get(f"http://127.0.0.1:{port}/healthz") as resp:
                assert resp.status == 200
            async with session.get(f"http://127.0.0.1:{port}/metrics") as resp:
                assert resp.status == 200
            # favicon usually 404 -> should still be silenced
            async with session.get(f"http://127.0.0.1:{port}/favicon.ico") as resp:
                assert resp.status in (200, 404)
    finally:
        await runner.cleanup()

    access = [e for e in events if e[0] == "access_logs"]
    assert not access, "expected monitoring endpoints to be silenced when ok"
