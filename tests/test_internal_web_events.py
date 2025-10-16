import importlib
import types
import os
import asyncio
import pytest


@pytest.mark.asyncio
async def test_internal_web_events_emitted(monkeypatch):
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

    # Enable internal web branch
    monkeypatch.setenv("ENABLE_INTERNAL_SHARE_WEB", "true")

    # Stub aiohttp server constructs to avoid network
    import main as m
    class _Runner:
        def __init__(self, app):  # noqa: ARG002
            pass
        async def setup(self):
            return None
    class _Site:
        def __init__(self, runner, host, port):  # noqa: ARG002
            self.port = port
        async def start(self):
            return None
    monkeypatch.setattr(m, "web", types.SimpleNamespace(AppRunner=_Runner, TCPSite=_Site))

    # Ensure PUBLIC_BASE_URL is truthy
    monkeypatch.setattr(m, "config", types.SimpleNamespace(PUBLIC_BASE_URL="http://localhost"), raising=False)

    # Rebind job_queue.run_once to run immediately
    class _JobQ:
        def run_once(self, fn, when=0, name=None):  # noqa: ARG002
            return asyncio.get_event_loop().create_task(fn(None))
    class _Bot:
        async def delete_my_commands(self):
            return None
        async def set_my_commands(self, *a, **k):  # noqa: ARG002
            return None
    class _App:
        job_queue = _JobQ()
        bot = _Bot()
    app = _App()

    # Call setup_bot_data to trigger scheduling immediately
    await m.setup_bot_data(app)

    assert any(e[0] == "internal_web_started" for e in captured["evts"])  # event emitted
