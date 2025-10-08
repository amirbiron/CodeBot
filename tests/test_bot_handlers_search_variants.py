import sys
import pytest
import types


@pytest.mark.asyncio
async def test_search_command_only_languages(monkeypatch):
    sys.modules.pop('bot_handlers', None)
    mod = __import__('bot_handlers')
    HB = getattr(mod, 'AdvancedBotHandlers')
    hb = HB(types.SimpleNamespace(add_handler=lambda *a, **k: None))
    class _Msg:
        async def reply_text(self, text, parse_mode=None):
            assert 'שפות' in text or 'חיפוש' in text
    class _Upd:
        effective_user = type('U', (), {'id': 1})()
        message = _Msg()
    class _Ctx:
        args = ["python", "javascript"]
    await hb.search_command(_Upd(), _Ctx())


@pytest.mark.asyncio
async def test_search_command_only_tags(monkeypatch):
    sys.modules.pop('bot_handlers', None)
    mod = __import__('bot_handlers')
    HB = getattr(mod, 'AdvancedBotHandlers')
    hb = HB(types.SimpleNamespace(add_handler=lambda *a, **k: None))
    class _Msg:
        async def reply_text(self, text, parse_mode=None):
            assert '#' in text or 'חיפוש' in text
    class _Upd:
        effective_user = type('U', (), {'id': 1})()
        message = _Msg()
    class _Ctx:
        args = ["#backend", "#api"]
    await hb.search_command(_Upd(), _Ctx())

