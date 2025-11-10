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
        # Force fallback to _MiniApp
        raise RuntimeError("no builder in tests")


class _Cbq:
    def __init__(self, *a, **k):
        self.callback = a[0] if a else None
        self.pattern = k.get('pattern') or (a[1] if len(a) > 1 else None)


class DummyConv:
    def __init__(self, *a, **k):
        # capture fallbacks list
        self.fallbacks = list(k.get('fallbacks') or [])


@pytest.mark.asyncio
async def test_conversation_fallbacks_include_cancel(monkeypatch):
    # Stub telegram app and handlers
    monkeypatch.setattr(m, 'PicklePersistence', _DummyPersistence, raising=False)
    monkeypatch.setattr(m, 'Defaults', _DummyDefaults, raising=False)
    monkeypatch.setattr(m, 'Application', _BuilderFail, raising=True)
    monkeypatch.setattr(m, 'CallbackQueryHandler', _Cbq, raising=False)
    # Intercept ConversationHandler to our dummy
    monkeypatch.setattr(m, 'ConversationHandler', DummyConv, raising=False)

    bot = m.CodeKeeperBot()

    # Find DummyConv handlers recorded in application
    convs = [args[0] for args, _ in bot.application.handlers if isinstance(args[0], DummyConv)]
    assert convs, "expected ConversationHandlers to be registered"

    # Extract patterns from fallbacks
    patterns = []
    for conv in convs:
        for fb in conv.fallbacks:
            pat = getattr(fb, 'pattern', None)
            if isinstance(pat, str):
                patterns.append(pat)
    assert r'^cancel$' in patterns
