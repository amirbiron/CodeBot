import pytest


@pytest.mark.asyncio
async def test_safe_edit_message_text_ignores_not_modified(monkeypatch):
    from utils import TelegramUtils

    class Q:
        async def edit_message_text(self, *a, **k):
            raise Exception("Message is not modified: no changes")

    # Should not raise
    await TelegramUtils.safe_edit_message_text(Q(), text="x")
