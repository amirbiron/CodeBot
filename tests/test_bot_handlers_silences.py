import types
import importlib


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


def test_silence_command_parsing_and_success(monkeypatch):
    # Fake silences.create_silence
    fake_sil = types.SimpleNamespace(
        create_silence=lambda **kw: {"_id": "abc", "until_ts": "2099-01-01"}
    )
    monkeypatch.setitem(importlib.sys.modules, 'monitoring.silences', fake_sil)

    import bot_handlers as bh
    h = bh.AdvancedBotHandlers(application=types.SimpleNamespace(add_handler=lambda *a, **k: None))

    upd = _Update()
    ctx = _Context(args=['High.*', '30m', 'reason=maintenance'])

    _out.clear()
    import asyncio
    asyncio.run(h.silence_command(upd, ctx))

    assert any("הושתק" in s for s in _out)


def test_unsilence_by_id_and_pattern(monkeypatch):
    fake_calls = {"by_id": [], "by_pat": []}
    def _unsilence_by_id(x):
        fake_calls["by_id"].append(x)
        return True
    def _unsilence_by_pattern(p):
        fake_calls["by_pat"].append(p)
        return 2
    fake_sil = types.SimpleNamespace(unsilence_by_id=_unsilence_by_id, unsilence_by_pattern=_unsilence_by_pattern)
    monkeypatch.setitem(importlib.sys.modules, 'monitoring.silences', fake_sil)

    import bot_handlers as bh
    h = bh.AdvancedBotHandlers(application=types.SimpleNamespace(add_handler=lambda *a, **k: None))

    import asyncio
    upd = _Update()
    _out.clear()
    asyncio.run(h.unsilence_command(upd, _Context(args=['0123456789abcdef0123456789abcdef'])))
    asyncio.run(h.unsilence_command(upd, _Context(args=['High.*'])))

    assert fake_calls["by_id"] and fake_calls["by_pat"]


def test_silences_list(monkeypatch):
    fake_sil = types.SimpleNamespace(list_active_silences=lambda limit=50: [
        {"_id": "a", "pattern": "High.*", "severity": "critical", "until_ts": "2099", "reason": "m"}
    ])
    monkeypatch.setitem(importlib.sys.modules, 'monitoring.silences', fake_sil)

    import bot_handlers as bh
    h = bh.AdvancedBotHandlers(application=types.SimpleNamespace(add_handler=lambda *a, **k: None))

    import asyncio
    _out.clear()
    asyncio.run(h.silences_command(_Update(), _Context()))

    assert any("השתקות פעילות" in s for s in _out)
