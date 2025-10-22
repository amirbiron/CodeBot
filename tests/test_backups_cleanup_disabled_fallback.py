import types
import importlib
import asyncio


def test_backups_cleanup_disabled_fallback(monkeypatch):
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
    monkeypatch.delenv("BACKUPS_CLEANUP_ENABLED", raising=False)

    import main as m

    # Force the global emit_event to fail so the code uses the dynamic import fallback
    def boom(*_a, **_k):
        raise RuntimeError("boom")

    monkeypatch.setattr(m, "emit_event", boom)

    class _JobQ:
        def run_repeating(self, fn, interval, first, name=None):  # noqa: ARG002
            # Not needed for this test
            return None

    class _Bot:
        async def delete_my_commands(self):
            return None

        async def set_my_commands(self, *a, **_k):  # noqa: ARG002
            return None

    class _App:
        job_queue = _JobQ()
        bot = _Bot()

    app = _App()

    # Run setup (should emit disabled event via fallback path)
    asyncio.get_event_loop().run_until_complete(m.setup_bot_data(app))

    # Expect an event stating backups cleanup is disabled (via fallback)
    assert any(evt[0] == "backups_cleanup_disabled" for evt in captured["evts"])  # noqa: SIM101
