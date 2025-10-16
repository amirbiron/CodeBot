import types
import importlib
import asyncio


def test_weekly_report_emits_and_notifies(monkeypatch):
    # Shim observability
    captured = {"evts": []}
    fake_obs = types.SimpleNamespace(
        setup_structlog_logging=lambda *_a, **_k: None,
        init_sentry=lambda: None,
        bind_request_id=lambda *_a, **_k: None,
        generate_request_id=lambda: "abcd1234",
        emit_event=lambda evt, severity="info", **kw: captured["evts"].append((evt, severity, kw)),
    )
    monkeypatch.setitem(importlib.sys.modules, "observability", fake_obs)

    # Stub user_stats and notify_admins
    import main as m
    monkeypatch.setattr(m, "user_stats", types.SimpleNamespace(
        get_all_time_stats=lambda: {"total_users": 10},
        get_weekly_stats=lambda: [1,2,3]
    ), raising=False)

    notified = {"msgs": []}
    async def _notify(_ctx, text):
        notified["msgs"].append(text)
    monkeypatch.setattr(m, "notify_admins", _notify)

    # Build app with job_queue that triggers immediately
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

    # Call setup to register and fire the job once
    asyncio.get_event_loop().run_until_complete(m.setup_bot_data(app))

    assert any(e[0] == "weekly_report_sent" for e in captured["evts"])  # event emitted
    assert notified["msgs"] and "📊 דו" in notified["msgs"][0]
