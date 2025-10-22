import types
import importlib
import asyncio


def test_backups_cleanup_disabled_by_default(monkeypatch):
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

    # Ensure BACKUPS_CLEANUP_ENABLED is not set/false
    monkeypatch.delenv('BACKUPS_CLEANUP_ENABLED', raising=False)

    import main as m

    class _JobQ:
        def run_repeating(self, fn, interval, first, name=None):  # noqa: ARG002
            # If the backups job was scheduled, it would trigger here.
            asyncio.get_event_loop().run_until_complete(fn(None))

    class _Bot:
        async def delete_my_commands(self):
            return None
        async def set_my_commands(self, *a, **_k):  # noqa: ARG002
            return None

    class _App:
        job_queue = _JobQ()
        bot = _Bot()

    app = _App()

    # To prevent executing any actual cleanup, stub file_manager.backup_manager
    fake_mgr = types.SimpleNamespace(cleanup_expired_backups=lambda *a, **k: {"fs_deleted": 0, "gridfs_deleted": 0})
    monkeypatch.setitem(importlib.sys.modules, "file_manager", types.SimpleNamespace(backup_manager=fake_mgr))

    # Run setup (should not schedule backups cleanup; instead emit disabled event)
    asyncio.get_event_loop().run_until_complete(m.setup_bot_data(app))

    # Expect an event stating backups cleanup is disabled by default
    assert any(evt[0] == "backups_cleanup_disabled" for evt in captured["evts"])  # noqa: SIM101
