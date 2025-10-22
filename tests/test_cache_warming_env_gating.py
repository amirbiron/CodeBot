import asyncio
import importlib
import types


def test_cache_warming_respects_env_disabled(monkeypatch):
    # Capture events
    captured = {"evts": []}
    fake_obs = types.SimpleNamespace(
        setup_structlog_logging=lambda *_a, **_k: None,
        init_sentry=lambda: None,
        bind_request_id=lambda *_a, **_k: None,
        generate_request_id=lambda: "",
        emit_event=lambda evt, severity="info", **kw: captured["evts"].append(evt),
    )
    monkeypatch.setitem(importlib.sys.modules, "observability", fake_obs)

    # Cache disabled or None -> job should no-op
    monkeypatch.setitem(importlib.sys.modules, 'cache_manager', types.SimpleNamespace(cache=None))
    # Minimal webapp.app shims
    monkeypatch.setitem(importlib.sys.modules, 'webapp.app', types.SimpleNamespace(get_db=lambda: None, search_engine=None))

    import main as m

    # Explicitly disable warming
    monkeypatch.setenv('CACHE_WARMING_ENABLED', 'false')

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
    # ensure other cleanup not disabling the flow
    monkeypatch.delenv('DISABLE_BACKGROUND_CLEANUP', raising=False)

    asyncio.get_event_loop().run_until_complete(m.setup_bot_data(app))

    # No warming events expected
    assert not any(evt for evt in captured["evts"] if evt.startswith('cache_warming_'))
