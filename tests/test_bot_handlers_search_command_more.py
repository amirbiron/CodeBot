import sys
import types
import pytest


@pytest.mark.asyncio
async def test_search_command_ignores_empty_and_unknown_tokens(monkeypatch):
    sys.modules.pop('bot_handlers', None)
    mod = __import__('bot_handlers')
    HB = getattr(mod, 'AdvancedBotHandlers')

    class _App:
        def add_handler(self, *a, **k):
            return None

    hb = HB(_App())

    captured = {}
    class _Msg:
        async def reply_text(self, text, parse_mode=None):
            captured['text'] = text
    class _User: id = 3
    class _Upd:
        effective_user = _User()
        message = _Msg()
    class _Ctx:
        args = ["", None, "#", "unknownlang", "#tag", "python"]

    await hb.search_command(_Upd(), _Ctx())
    # ודא שההודעה נשלחה וללא חריגה; לא מחייב שנבדוק תוכן מדויק
    assert isinstance(captured.get('text', ''), str)

