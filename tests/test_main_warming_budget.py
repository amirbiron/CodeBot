import asyncio
import importlib
import types


def test_warming_budget_limits_cycles(monkeypatch):
    # Capture timings by making search/DB slow to loop
    class _SlowColl:
        def aggregate(self, *a, **k):  # noqa: ARG002
            return [{"_id": 1, "cnt": 1}]
        def count_documents(self, *a, **k):  # noqa: ARG002
            return 1
        def distinct(self, *a, **k):  # noqa: ARG002
            return ["python"]
        def find(self, *a, **k):  # noqa: ARG002
            class _C:
                def sort(self, *a, **k):
                    return self
                def limit(self, *a, **k):
                    return [{"file_name": "a.py", "created_at": __import__('datetime').datetime.now(__import__('datetime').timezone.utc)}]
            return _C()
    class _DB:
        code_snippets = _SlowColl()
    def _get_db():
        return _DB()

    # Shim cache/search_engine
    class _Cache:
        is_enabled = True
        def set_dynamic(self, *a, **k):  # noqa: ARG002
            return True
    monkeypatch.setitem(importlib.sys.modules, 'cache_manager', types.SimpleNamespace(cache=_Cache()))
    monkeypatch.setitem(importlib.sys.modules, 'webapp.app', types.SimpleNamespace(get_db=_get_db, search_engine=None))

    # Capture events
    captured = {"evts": []}
    fake_obs = types.SimpleNamespace(
        setup_structlog_logging=lambda *_a, **_k: None,
        init_sentry=lambda: None,
        bind_request_id=lambda *_a, **_k: None,
        generate_request_id=lambda: "",
        emit_event=lambda evt, severity="info", **kw: captured["evts"].append(evt),
    )
    monkeypatch.setitem(importlib.sys.modules, 'observability', fake_obs)

    import main as m

    # Short budget and immediate run
    monkeypatch.setenv('CACHE_WARMING_ENABLED', '1')
    monkeypatch.setenv('CACHE_WARMING_BUDGET_SECONDS', '0.001')

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
    monkeypatch.delenv('DISABLE_BACKGROUND_CLEANUP', raising=False)

    asyncio.get_event_loop().run_until_complete(m.setup_bot_data(app))

    # Should emit (done or error) even under tight budget
    assert any(evt for evt in captured["evts"] if evt in {"cache_warming_done", "cache_warming_error"})
