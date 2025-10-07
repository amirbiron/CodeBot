import asyncio
import types
import pytest


@pytest.mark.asyncio
async def test_safe_edit_message_text_ignores_message_not_modified(monkeypatch):
    from utils import TelegramUtils
    import telegram

    class _Q:
        def __init__(self):
            self.called = []
        async def edit_message_text(self, **kwargs):
            raise telegram.error.BadRequest("Message is not modified")

    q = _Q()
    # Should not raise
    await TelegramUtils.safe_edit_message_text(q, text="hi")


@pytest.mark.asyncio
async def test_safe_edit_message_text_raises_other_badrequest(monkeypatch):
    from utils import TelegramUtils
    import telegram

    class _Q:
        async def edit_message_text(self, **kwargs):
            raise telegram.error.BadRequest("other error")

    q = _Q()
    with pytest.raises(telegram.error.BadRequest):
        await TelegramUtils.safe_edit_message_text(q, text="hi")


@pytest.mark.asyncio
async def test_safe_edit_message_reply_markup_ignores_message_not_modified(monkeypatch):
    from utils import TelegramUtils
    import telegram

    class _Q:
        async def edit_message_reply_markup(self, **kwargs):
            raise telegram.error.BadRequest("message is not modified")

    q = _Q()
    # Should not raise
    await TelegramUtils.safe_edit_message_reply_markup(q, reply_markup=None)


@pytest.mark.asyncio
async def test_safe_edit_message_reply_markup_raises_other(monkeypatch):
    from utils import TelegramUtils
    import telegram

    class _Q:
        async def edit_message_reply_markup(self, **kwargs):
            raise telegram.error.BadRequest("boom")

    q = _Q()
    with pytest.raises(telegram.error.BadRequest):
        await TelegramUtils.safe_edit_message_reply_markup(q, reply_markup=None)


def test_split_long_message_basic():
    from utils import TelegramUtils

    text = "a\n" * 10
    parts = TelegramUtils.split_long_message(text, max_length=5)
    # Should split into multiple small chunks preserving line boundaries
    assert isinstance(parts, list) and parts
    assert all(len(p) <= 5 for p in parts)


def test_split_long_message_no_split_needed():
    from utils import TelegramUtils
    text = "short"
    parts = TelegramUtils.split_long_message(text, max_length=100)
    assert parts == ["short"]

