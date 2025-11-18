import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.mark.asyncio
async def test_get_filename_existing_shows_conflict_menu(monkeypatch):
    monkeypatch.setenv('USE_NEW_SAVE_FLOW', '1')

    from handlers import save_flow

    class DummyEntity:
        pass

    class DummyService:
        async def get_snippet(self, user_id, filename):
            return DummyEntity()

    monkeypatch.setattr(save_flow, '_build_layered_snippet_service', lambda: DummyService())

    update = MagicMock()
    update.message = MagicMock()
    update.message.text = 'dup.py'
    update.message.reply_text = AsyncMock()
    update.message.from_user.id = 5

    context = MagicMock()
    context.user_data = {}

    result = await save_flow.get_filename(update, context)

    assert result == save_flow.GET_FILENAME
    update.message.reply_text.assert_awaited()
