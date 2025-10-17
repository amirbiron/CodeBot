import asyncio
import sys
import types
import pytest


@pytest.mark.asyncio
async def test_incidents_command_outputs(tmp_path, monkeypatch):
    # Isolate data path
    (tmp_path / "data").mkdir()
    monkeypatch.chdir(tmp_path)

    # Minimal telegram stubs
    class _Msg:
        def __init__(self):
            self.sent = []
        async def reply_text(self, text, parse_mode=None, reply_markup=None):
            self.sent.append(text)
    class _User:
        id = 123
    class _Upd:
        def __init__(self):
            self.message = _Msg()
            self.effective_user = _User()

    class _Ctx:
        args = []

    # Admin IDs env
    monkeypatch.setenv('ADMIN_USER_IDS', '123')

    # Prepare one incident
    import importlib
    rm = importlib.import_module('remediation_manager')
    # Stub observability
    monkeypatch.setitem(sys.modules, 'observability', types.SimpleNamespace(emit_event=lambda *a, **k: None))
    rm.handle_critical_incident("High Latency", "latency_seconds", 2.2, 1.0, {"current_seconds": 2.2})

    # Build a tiny app object to attach handler
    from types import SimpleNamespace
    app = SimpleNamespace(handlers=[])
    def add_handler(h):
        app.handlers.append(h)
    app.add_handler = add_handler

    import bot_handlers as bh
    bh.AdvancedBotHandlers(app)  # registers handlers including /incidents

    # Find handler and invoke it
    handler = None
    for h in app.handlers:
        if getattr(h, 'command', None) == ['incidents']:
            handler = h
            break
    # Fallback: directly call method for robustness
    upd, ctx = _Upd(), _Ctx()
    obj = bh.AdvancedBotHandlers(app)
    await obj.incidents_command(upd, ctx)

    # Assert output contains heading
    assert any('תקלות אחרונות' in s for s in upd.message.sent)
