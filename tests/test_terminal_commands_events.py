import types
import pytest

import terminal_commands as tc


@pytest.mark.asyncio
async def test_terminal_command_failed_emits(monkeypatch):
    captured = {"evts": []}

    def _emit(event: str, severity: str = "info", **fields):
        captured["evts"].append((event, severity, fields))

    # Patch emit_event and run_in_sandbox to raise
    monkeypatch.setattr(tc, "emit_event", _emit, raising=False)

    async def _boom(*a, **k):
        raise RuntimeError("exec failed")

    monkeypatch.setattr(tc, "run_in_sandbox", _boom, raising=False)

    class _Msg:
        message_id = 1
        text = "echo hi"
        async def reply_text(self, *a, **k):
            return None

    class _Bot:
        async def get_file(self, *a, **k):
            return types.SimpleNamespace(download_as_bytearray=lambda: b"x")

    class _Update:
        message = _Msg()

    class _Ctx:
        application = types.SimpleNamespace(bot_data={"MAIN_KEYBOARD": [["home"]]})
        bot = _Bot()

    await tc.terminal_run_command(_Update(), _Ctx())

    assert any(e[0] == "terminal_command_failed" for e in captured["evts"])  # event emitted
