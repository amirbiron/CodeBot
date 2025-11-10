import types
import pytest

import main as m


class _DummyPersistence:
    def __init__(self, *a, **k):
        pass


class _DummyDefaults:
    def __init__(self, *a, **k):
        pass


class _BuilderFail:
    @staticmethod
    def builder():
        # Force fallback to _MiniApp path inside CodeKeeperBot.__init__
        raise RuntimeError("builder not available in tests")


class _Cmd:
    def __init__(self, *a, **k):
        self.callback = a[0] if a else None


class _Msg:
    def __init__(self, *a, **k):
        self.callback = a[0] if a else None


class _Cbq:
    def __init__(self, *a, **k):
        self.callback = a[0] if a else None
        self.pattern = k.get('pattern') or (a[1] if len(a) > 1 else None)


@pytest.mark.asyncio
async def test_main_registers_back_and_cancel_handlers(monkeypatch):
    # Stub dependencies so CodeKeeperBot uses internal _MiniApp
    monkeypatch.setattr(m, 'PicklePersistence', _DummyPersistence, raising=False)
    monkeypatch.setattr(m, 'Defaults', _DummyDefaults, raising=False)
    monkeypatch.setattr(m, 'Application', _BuilderFail, raising=True)
    monkeypatch.setattr(m, 'CommandHandler', _Cmd, raising=False)
    monkeypatch.setattr(m, 'MessageHandler', _Msg, raising=False)
    monkeypatch.setattr(m, 'CallbackQueryHandler', _Cbq, raising=False)

    bot = m.CodeKeeperBot()
    # Extract recorded handlers from _MiniApp
    patterns = []
    for args, kwargs in bot.application.handlers:
        h = args[0]
        pat = getattr(h, 'pattern', None)
        if isinstance(pat, str):
            patterns.append(pat)
    # Ensure our new callback handlers were registered
    assert r'^community_hub$' in patterns
    assert r'^main_menu$' in patterns
    assert r'^cancel$' in patterns
