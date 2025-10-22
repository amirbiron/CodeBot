import asyncio
import importlib
import types


def test_cache_warming_scheduler_fallback_runs_once(monkeypatch):
    # Shim observability
    captured = {"evts": []}
    fake_obs = types.SimpleNamespace(
        setup_structlog_logging=lambda *_a, **_k: None,
        init_sentry=lambda: None,
        bind_request_id=lambda *_a, **_k: None,
        generate_request_id=lambda: "",
        emit_event=lambda evt, severity="info", **kw: captured["evts"].append(evt),
    )
    monkeypatch.setitem(importlib.sys.modules, 'observability', fake_obs)

    # Fake job queue that raises on scheduling to trigger fallback (run once immediately)
    class _JobQ:
        def run_repeating(self, fn, interval, first, name=None):  # noqa: ARG002
            raise RuntimeError('schedule not available')
    class _Bot:
        async def delete_my_commands(self):
            return None
        async def set_my_commands(self, *a, **k):  # noqa: ARG002
            return None
    class _App:
        job_queue = _JobQ()
        bot = _Bot()

    # Provide minimal deps for warming job
    class _Coll:
        def aggregate(self, *a, **k):  # noqa: ARG002
            return []
        def count_documents(self, *a, **k):  # noqa: ARG002
            return 0
        def distinct(self, *a, **k):  # noqa: ARG002
            return []
        def find(self, *a, **k):  # noqa: ARG002
            class _C:
                def sort(self, *a, **k):
                    return self
                def limit(self, *a, **k):
                    return []
            return _C()
    class _DB:
        code_snippets = _Coll()

    monkeypatch.setitem(importlib.sys.modules, 'webapp.app', types.SimpleNamespace(get_db=lambda: _DB(), search_engine=None))
    class _Cache:
        is_enabled = True
        def set_dynamic(self, *a, **k):  # noqa: ARG002
            return True
    monkeypatch.setitem(importlib.sys.modules, 'cache_manager', types.SimpleNamespace(cache=_Cache()))

    import main as m

    # Enable warming and run setup
    monkeypatch.setenv('CACHE_WARMING_ENABLED', '1')
    monkeypatch.delenv('DISABLE_BACKGROUND_CLEANUP', raising=False)

    # Should fall back and run once
    asyncio.get_event_loop().run_until_complete(m.setup_bot_data(_App()))

    assert any(evt for evt in captured["evts"] if evt in {"cache_warming_done", "cache_warming_error"})
