import pytest
from types import SimpleNamespace
import telegram.error


@pytest.mark.asyncio
async def test_media_fallback_when_no_text_in_message(monkeypatch):
    mod = __import__('bot_handlers')
    H = getattr(mod, 'AdvancedBotHandlers')

    class _App:
        def add_handler(self, *a, **k):
            pass

    captured = {}

    class _Query:
        message = SimpleNamespace(reply_text=lambda *a, **k: None)
        async def edit_message_text(self, *a, **k):
            raise telegram.error.BadRequest("There is no text in the message to edit")
        async def edit_message_caption(self, *a, **k):
            captured['caption'] = (a, k)

    h = H(_App())
    await h._edit_message_with_media_fallback(_Query(), text="hi")
    assert 'caption' in captured


@pytest.mark.asyncio
async def test_media_fallback_ignores_not_modified(monkeypatch):
    mod = __import__('bot_handlers')
    H = getattr(mod, 'AdvancedBotHandlers')

    class _App:
        def add_handler(self, *a, **k):
            pass

    captured = {}

    class _Query:
        message = SimpleNamespace(reply_text=lambda *a, **k: None)
        async def edit_message_text(self, *a, **k):
            raise telegram.error.BadRequest("message is not modified")
        async def edit_message_caption(self, *a, **k):
            captured['caption'] = (a, k)

    h = H(_App())
    # Should return without attempting caption
    await h._edit_message_with_media_fallback(_Query(), text="hi")
    assert 'caption' not in captured
