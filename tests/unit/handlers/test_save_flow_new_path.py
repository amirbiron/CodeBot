import types
import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.mark.asyncio
async def test_save_flow_new_path_saves_and_replies(monkeypatch):
    # Enable new flow
    monkeypatch.setenv('USE_NEW_SAVE_FLOW', '1')

    # Stub modules imported inside save_flow function
    class DummyService:
        def __init__(self, snippet_repository=None, code_normalizer=None):
            self.repo = snippet_repository
            self.norm = code_normalizer

        async def create_snippet(self, dto):
            class _S:
                language = 'python'
            return _S()

        async def get_snippet(self, user_id, filename):
            return None

    dummy_service_mod = types.SimpleNamespace(SnippetService=DummyService)
    dummy_dto_mod = types.SimpleNamespace(CreateSnippetDTO=object)
    dummy_norm_mod = types.SimpleNamespace(CodeNormalizer=object)
    dummy_repo_mod = types.SimpleNamespace(SnippetRepository=object)

    fake_db = types.SimpleNamespace(get_latest_version=lambda u, f: {'_id': 'abc123'})
    dummy_database_mod = types.SimpleNamespace(db=fake_db)

    monkeypatch.setitem(__import__('sys').modules, 'src.application.services.snippet_service', dummy_service_mod)
    monkeypatch.setitem(__import__('sys').modules, 'src.application.dto.create_snippet_dto', dummy_dto_mod)
    monkeypatch.setitem(__import__('sys').modules, 'src.domain.services.code_normalizer', dummy_norm_mod)
    monkeypatch.setitem(
        __import__('sys').modules,
        'src.infrastructure.database.mongodb.repositories.snippet_repository',
        dummy_repo_mod,
    )
    monkeypatch.setitem(__import__('sys').modules, 'database', dummy_database_mod)

    # Import target after stubbing
    from handlers import save_flow

    update = MagicMock()
    update.message = MagicMock()
    update.message.reply_text = AsyncMock()

    context = MagicMock()
    context.user_data = {'code_to_save': 'print(1)', 'note_to_save': 'hi'}

    result = await save_flow.save_file_final(update, context, filename='t.py', user_id=1)

    assert result == save_flow.ConversationHandler.END
    update.message.reply_text.assert_awaited()
