import types
import importlib
import asyncio


def test_backups_cleanup_schedules_when_enabled(monkeypatch):
    # Shim observability
    captured = {"evts": []}
    fake_obs = types.SimpleNamespace(
        setup_structlog_logging=lambda *_a, **_k: None,
        init_sentry=lambda: None,
        bind_request_id=lambda *_a, **_k: None,
        generate_request_id=lambda: "",
        emit_event=lambda evt, severity="info", **kw: captured["evts"].append((evt, severity, kw)),
    )
    monkeypatch.setitem(importlib.sys.modules, "observability", fake_obs)

    # Enable backups cleanup
    monkeypatch.setenv('BACKUPS_CLEANUP_ENABLED', 'true')

    # Prevent actual cleanup execution
    fake_mgr = types.SimpleNamespace(cleanup_expired_backups=lambda *a, **k: {"fs_deleted": 0, "gridfs_deleted": 0})
    monkeypatch.setitem(importlib.sys.modules, "file_manager", types.SimpleNamespace(backup_manager=fake_mgr))

    # Track scheduling calls
    scheduled = {"called": 0}

    import main as m

    class _JobQ:
        def run_repeating(self, fn, interval, first, name=None):  # noqa: ARG002
            scheduled["called"] += 1
            # Trigger once to simulate execution
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

    # Job scheduled
    assert scheduled["called"] >= 1
    # Should emit either done or error during simulated run
    evts = [e[0] for e in captured["evts"]]
    assert any(evt in {"backups_cleanup_done", "backups_cleanup_error"} for evt in evts)
