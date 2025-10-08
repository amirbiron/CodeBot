import sys
import types
import pytest


@pytest.mark.asyncio
async def test_search_command_no_args_shows_usage(monkeypatch):
    sys.modules.pop('bot_handlers', None)
    mod = __import__('bot_handlers')
    HB = getattr(mod, 'AdvancedBotHandlers')

    class _App:
        def __init__(self):
            self.handlers = []
        def add_handler(self, *a, **k):
            self.handlers.append((a, k))

    app = _App()
    hb = HB(app)

    captured = {}
    class _Msg:
        async def reply_text(self, text, parse_mode=None):
            captured['text'] = text
            captured['parse_mode'] = parse_mode
    class _User: id = 1
    class _Upd:
        effective_user = _User()
        message = _Msg()
    class _Ctx:
        args = []

    await hb.search_command(_Upd(), _Ctx())
    assert 'search' in captured.get('text', '').lower()


@pytest.mark.asyncio
async def test_search_command_with_filters(monkeypatch):
    sys.modules.pop('bot_handlers', None)
    mod = __import__('bot_handlers')
    HB = getattr(mod, 'AdvancedBotHandlers')

    class _App:
        def add_handler(self, *a, **k):
            return None

    hb = HB(_App())

    class _Msg:
        async def reply_text(self, text, parse_mode=None):
            # וידוא שאין חריגה, ושהטקסט נשלח
            assert isinstance(text, str)
    class _User: id = 2
    class _Upd:
        effective_user = _User()
        message = _Msg()
    class _Ctx:
        args = ["python", "#utils", "api"]

    await hb.search_command(_Upd(), _Ctx())

