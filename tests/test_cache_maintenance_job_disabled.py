import types
import importlib
import asyncio


def test_cache_maintenance_job_skips_when_disabled(monkeypatch):
    # Observability capture
    captured = {"evts": []}
    fake_obs = types.SimpleNamespace(
        setup_structlog_logging=lambda *_a, **_k: None,
        init_sentry=lambda: None,
        bind_request_id=lambda *_a, **_k: None,
        generate_request_id=lambda: "",
        emit_event=lambda evt, severity="info", **kw: captured["evts"].append((evt, severity, kw)),
    )
    monkeypatch.setitem(importlib.sys.modules, "observability", fake_obs)

    # Ensure background cleanup disabled
    monkeypatch.setenv('DISABLE_BACKGROUND_CLEANUP', 'true')

    # Fake cache; if job would run it increments
    called = {"n": 0}
    fake_cache = types.SimpleNamespace(clear_stale=lambda **_k: (called.__setitem__('n', called['n'] + 1) or 1))
    monkeypatch.setitem(importlib.sys.modules, "cache_manager", types.SimpleNamespace(cache=fake_cache))

    import main as m

    class _JobQ:
        def run_repeating(self, fn, interval, first, name=None):  # noqa: ARG002
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

    asyncio.get_event_loop().run_until_complete(m.setup_bot_data(app))

    # Because DISABLE_BACKGROUND_CLEANUP=true, job body should early return and not call clear_stale
    assert called['n'] == 0
