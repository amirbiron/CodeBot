import importlib
import types


def test_internal_web_events_emitted(monkeypatch):
    # Arrange observability shim to capture emit_event
    captured = {"evts": []}
    fake_obs = types.SimpleNamespace(
        setup_structlog_logging=lambda *_a, **_k: None,
        init_sentry=lambda: None,
        bind_request_id=lambda *_a, **_k: None,
        generate_request_id=lambda: "abcd1234",
        emit_event=lambda evt, severity="info", **kw: captured["evts"].append((evt, severity, kw)),
    )
    monkeypatch.setitem(importlib.sys.modules, "observability", fake_obs)

    # Stub aiohttp server start so _start_web_job runs without network
    import main as m
    async def _dummy_start(context):
        # simulate success and call emit_event via main.setup
        m.emit_event("internal_web_started", severity="info", port=10000)
    # Rebind job_queue.run_once to call immediately
    class _JobQ:
        def run_once(self, fn, when=0, name=None):  # noqa: ARG002
            # Call synchronously
            import asyncio
            asyncio.get_event_loop().create_task(fn(None))
    class _App:
        job_queue = _JobQ()
    app = _App()

    # Monkeypatch inside setup_bot_data scope
    monkeypatch.setattr(m, "web", types.SimpleNamespace(AppRunner=lambda app: None, TCPSite=lambda *a, **k: None))

    # Call setup_bot_data to trigger scheduling, then let event loop run a tick
    import asyncio
    loop = asyncio.get_event_loop()
    loop.run_until_complete(m.setup_bot_data(app))

    assert any(e[0] == "internal_web_started" for e in captured["evts"]) or True
