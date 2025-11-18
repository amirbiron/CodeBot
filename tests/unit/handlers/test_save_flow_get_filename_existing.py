import types
import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.mark.asyncio
async def test_get_filename_existing_shows_conflict_menu(monkeypatch):
    monkeypatch.setenv('USE_NEW_SAVE_FLOW', '1')

    class DummyEntity:
        pass

    class DummyService:
        def __init__(self, *args, **kwargs):
            pass
        async def get_snippet(self, user_id, filename):
            return DummyEntity()

    dummy_service_mod = types.SimpleNamespace(SnippetService=DummyService)
    dummy_norm_mod = types.SimpleNamespace(CodeNormalizer=object)
    dummy_repo_mod = types.SimpleNamespace(SnippetRepository=object)
    # DB fallback not used in this path but keep stub
    dummy_database_mod = types.SimpleNamespace(db=types.SimpleNamespace())

    monkeypatch.setitem(__import__('sys').modules, 'src.application.services.snippet_service', dummy_service_mod)
    monkeypatch.setitem(__import__('sys').modules, 'src.domain.services.code_normalizer', dummy_norm_mod)
    monkeypatch.setitem(
        __import__('sys').modules,
        'src.infrastructure.database.mongodb.repositories.snippet_repository',
        dummy_repo_mod,
    )
    monkeypatch.setitem(__import__('sys').modules, 'database', dummy_database_mod)

    from handlers import save_flow

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
