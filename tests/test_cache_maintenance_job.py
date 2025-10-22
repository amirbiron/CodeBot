import types
import importlib
import asyncio


def test_cache_maintenance_job_schedules_and_emits(monkeypatch):
    # Shim observability (collect events)
    captured = {"evts": []}
    fake_obs = types.SimpleNamespace(
        setup_structlog_logging=lambda *_a, **_k: None,
        init_sentry=lambda: None,
        bind_request_id=lambda *_a, **_k: None,
        generate_request_id=lambda: "",
        emit_event=lambda evt, severity="info", **kw: captured["evts"].append((evt, severity, kw)),
    )
    monkeypatch.setitem(importlib.sys.modules, "observability", fake_obs)

    # Fake cache that tracks calls to clear_stale
    called = {"n": 0}
    fake_cache = types.SimpleNamespace(clear_stale=lambda **_k: (called.__setitem__('n', called['n'] + 1) or 0))
    monkeypatch.setitem(importlib.sys.modules, "cache_manager", types.SimpleNamespace(cache=fake_cache))

    import main as m

    class _JobQ:
        def run_repeating(self, fn, interval, first, name=None):  # noqa: ARG002
            # Trigger once immediately
            asyncio.get_event_loop().run_until_complete(fn(None))

    class _Bot:
        async def delete_my_commands(self):
            return None
        async def set_my_commands(self, *a, **k):  # noqa: ARG002
            return None

    class _App:
        job_queue = _JobQ()
        bot = _Bot()

    app = _App()

    # Ensure background cleanup not disabled
    monkeypatch.delenv('DISABLE_BACKGROUND_CLEANUP', raising=False)

    asyncio.get_event_loop().run_until_complete(m.setup_bot_data(app))

    # The cache job should have run once and emitted a done or error event
    assert called['n'] >= 1
    evts = [e[0] for e in captured['evts']]
    assert any(evt in {"cache_maintenance_done", "cache_maintenance_error"} for evt in evts)
