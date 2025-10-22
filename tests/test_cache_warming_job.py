import asyncio
import importlib
import types


def test_cache_warming_job_runs_and_emits(monkeypatch):
    # Shim observability to capture events
    captured = {"evts": []}
    fake_obs = types.SimpleNamespace(
        setup_structlog_logging=lambda *_a, **_k: None,
        init_sentry=lambda: None,
        bind_request_id=lambda *_a, **_k: None,
        generate_request_id=lambda: "",
        emit_event=lambda evt, severity="info", **kw: captured["evts"].append((evt, severity, kw)),
    )
    monkeypatch.setitem(importlib.sys.modules, "observability", fake_obs)

    # Fake DB and search engine
    class _Coll:
        def __init__(self):
            self.docs = [
                {"_id": 1, "user_id": 7, "file_name": "a.py", "updated_at": __import__('datetime').datetime.now(__import__('datetime').timezone.utc)},
            ]
        def aggregate(self, pipeline, allowDiskUse=False):  # noqa: ARG002
            # top users or tags
            if any("$group" in s and s["$group"].get("_id") == "$user_id" for s in pipeline if isinstance(s, dict)):
                return [{"_id": 7, "cnt": 1}]
            if any("$unwind" in s for s in pipeline if isinstance(s, dict)):
                return [{"_id": "todo", "cnt": 1}]
            return []
        def count_documents(self, q):  # noqa: ARG001
            return 1
        def distinct(self, field, q):  # noqa: ARG002
            return ["python"]
        def find(self, *a, **k):  # noqa: ARG002
            class _C:
                def sort(self, *a, **k):
                    return self
                def limit(self, *a, **k):
                    return [{"file_name": "a.py", "created_at": __import__('datetime').datetime.now(__import__('datetime').timezone.utc)}]
            return _C()
    class _DB:
        code_snippets = _Coll()
    def _get_db():
        return _DB()

    class _Cache:
        is_enabled = True
        def set_dynamic(self, *a, **k):  # noqa: ARG002
            return True
    monkeypatch.setitem(importlib.sys.modules, "cache_manager", types.SimpleNamespace(cache=_Cache()))

    # Shim webapp.app exports used by main
    monkeypatch.setitem(importlib.sys.modules, "webapp.app", types.SimpleNamespace(get_db=_get_db, search_engine=None))

    import main as m

    # Force enabled and short budget
    monkeypatch.setenv('CACHE_WARMING_ENABLED', '1')
    monkeypatch.setenv('CACHE_WARMING_BUDGET_SECONDS', '1')

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

    # Run setup to schedule and execute warming once
    asyncio.get_event_loop().run_until_complete(m.setup_bot_data(app))

    # Assert an event was emitted
    assert any(evt for evt, sev, _ in captured["evts"] if evt in {"cache_warming_done", "cache_warming_error"})
