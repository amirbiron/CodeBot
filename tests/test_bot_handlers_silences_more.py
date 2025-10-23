import types
import importlib
import asyncio

from bot_handlers import AdvancedBotHandlers


class _Update:
    def __init__(self, text: str = "", user_id: int = 1):
        self.effective_user = types.SimpleNamespace(id=user_id)
        self.effective_chat = types.SimpleNamespace(id=100)
        self.message = types.SimpleNamespace(text=text)
        async def _reply_text(msg, parse_mode=None):  # noqa: ARG001
            _out.append(msg)
        self.message.reply_text = _reply_text


class _Context:
    def __init__(self, args=None):
        self.args = args or []


_out = []


def _app_stub():
    return types.SimpleNamespace(add_handler=lambda *a, **k: None)


def test_silence_invalid_usage():
    h = AdvancedBotHandlers(application=_app_stub())
    _out.clear()
    asyncio.run(h.silence_command(_Update(), _Context(args=['only-one-arg'])))
    assert any('שימוש' in s for s in _out)


def test_silence_invalid_duration(monkeypatch):
    fake_sil = types.SimpleNamespace(create_silence=lambda **kw: None)
    monkeypatch.setitem(importlib.sys.modules, 'monitoring.silences', fake_sil)
    h = AdvancedBotHandlers(application=_app_stub())
    _out.clear()
    asyncio.run(h.silence_command(_Update(), _Context(args=['High', 'oops'])))
    assert any('משך זמן לא תקין' in s for s in _out)


def test_silence_force_allows_dangerous_pattern(monkeypatch):
    created = {"count": 0}
    def _create(**kw):
        created["count"] += 1
        return {"_id": "a", "until_ts": "2099"}
    fake_sil = types.SimpleNamespace(create_silence=_create)
    monkeypatch.setitem(importlib.sys.modules, 'monitoring.silences', fake_sil)
    h = AdvancedBotHandlers(application=_app_stub())
    _out.clear()
    asyncio.run(h.silence_command(_Update(), _Context(args=['.*', '10m', '--force'])))
    assert created["count"] == 1
