import sys
import types
import pytest
from unittest.mock import AsyncMock, MagicMock


def test_safe_construct_branches():
    from handlers import save_flow

    sentinel = object()
    assert save_flow._safe_construct(None) is None
    assert save_flow._safe_construct(sentinel) is sentinel

    class Constructor:
        def __init__(self):
            self.flag = True

    instance = save_flow._safe_construct(Constructor, object())
    assert isinstance(instance, Constructor)

    class FailingConstructor:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("boom")

    assert save_flow._safe_construct(FailingConstructor) is None


@pytest.mark.asyncio
async def test_call_service_method_branches():
    from handlers import save_flow

    assert await save_flow._call_service_method(None, "foo") is None
    assert await save_flow._call_service_method(object(), "foo") is None

    class Dummy:
        def method(self, value):
            return value + 1

    assert await save_flow._call_service_method(Dummy(), "method", 2) == 3

    class AsyncDummy:
        async def method(self):
            return "done"

    assert await save_flow._call_service_method(AsyncDummy(), "method") == "done"

    class Failing:
        def method(self):
            raise RuntimeError

    assert await save_flow._call_service_method(Failing(), "method") is None


def test_build_layered_service_handles_missing_deps(monkeypatch):
    from handlers import save_flow

    monkeypatch.setitem(sys.modules, 'src.application.services.snippet_service', types.SimpleNamespace(SnippetService=None))
    monkeypatch.setitem(sys.modules, 'src.domain.services.code_normalizer', types.SimpleNamespace(CodeNormalizer=object))
    monkeypatch.setitem(sys.modules, 'src.infrastructure.database.mongodb.repositories.snippet_repository', types.SimpleNamespace(SnippetRepository=object))
    monkeypatch.setitem(sys.modules, 'database', types.SimpleNamespace(db=object()))

    assert save_flow._build_layered_snippet_service() is None


def test_cleanup_save_flow_state():
    from handlers import save_flow

    context = MagicMock()
    context.user_data = {key: f"value-{idx}" for idx, key in enumerate(save_flow._SAVE_FLOW_STATE_KEYS)}
    context.user_data['keep'] = 'value'

    save_flow._cleanup_save_flow_state(context)

    assert context.user_data == {'keep': 'value'}


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


@pytest.mark.asyncio
async def test_save_file_final_layered_flow_success(monkeypatch):
    monkeypatch.setenv('USE_NEW_SAVE_FLOW', '1')

    class DummyRepo:
        def __init__(self):
            # נזרוק שגיאה אם יעדיפו להעביר פרמטרים כדי לכסות את מסלול ה-TypeError
            if getattr(self, "_init_called", False):
                raise RuntimeError("should not be re-used")
            self._init_called = True

    class DummyNormalizer:
        def __init__(self):
            pass

    class DummyService:
        def __init__(self, snippet_repository=None, code_normalizer=None):
            self.repo = snippet_repository
            self.normalizer = code_normalizer
        async def create_snippet(self, dto):
            self.dto = dto
            return types.SimpleNamespace(language='python')

    class DummyDTO:
        def __init__(self, user_id, filename, code, note=None):
            self.user_id = user_id
            self.filename = filename
            self.code = code
            self.note = note

    dummy_db = types.SimpleNamespace(
        get_latest_version=lambda user_id, filename: {
            '_id': 'fid123',
            'user_id': user_id,
            'file_name': filename,
            'programming_language': 'python',
        }
    )

    monkeypatch.setitem(
        __import__('sys').modules,
        'database',
        types.SimpleNamespace(db=dummy_db),
    )
    monkeypatch.setitem(
        __import__('sys').modules,
        'src.application.services.snippet_service',
        types.SimpleNamespace(SnippetService=DummyService),
    )
    monkeypatch.setitem(
        __import__('sys').modules,
        'src.domain.services.code_normalizer',
        types.SimpleNamespace(CodeNormalizer=DummyNormalizer),
    )
    monkeypatch.setitem(
        __import__('sys').modules,
        'src.infrastructure.database.mongodb.repositories.snippet_repository',
        types.SimpleNamespace(SnippetRepository=DummyRepo),
    )
    monkeypatch.setitem(
        __import__('sys').modules,
        'src.application.dto.create_snippet_dto',
        types.SimpleNamespace(CreateSnippetDTO=DummyDTO),
    )

    from handlers import save_flow

    monkeypatch.setattr(save_flow.TextUtils, 'escape_markdown', lambda text, version=1: text, raising=False)

    update = MagicMock()
    update.message = MagicMock()
    update.message.reply_text = AsyncMock()

    context = MagicMock()
    context.user_data = {
        'code_to_save': 'print("hello")',
        'note_to_save': 'note',
        'pending_filename': 'dup.py',
        'long_collect_parts': ['part'],
        'long_collect_job': object(),
        'long_collect_active': True,
    }

    result = await save_flow.save_file_final(update, context, 'dup.py', 7)

    assert result == save_flow.ConversationHandler.END
    update.message.reply_text.assert_awaited()
    assert context.user_data.get('last_save_success')['file_name'] == 'dup.py'
    assert 'code_to_save' not in context.user_data
    assert 'long_collect_parts' not in context.user_data


@pytest.mark.asyncio
async def test_save_file_final_legacy_flow_fallback(monkeypatch):
    monkeypatch.delenv('USE_NEW_SAVE_FLOW', raising=False)

    saved_snippets = {}

    class DummyCodeSnippet:
        def __init__(self, **kwargs):
            saved_snippets['snippet'] = types.SimpleNamespace(**kwargs)

    dummy_db = types.SimpleNamespace(
        save_code_snippet=lambda snippet: True,
        get_latest_version=lambda user_id, filename: {
            '_id': 'legacy123',
            'user_id': user_id,
            'file_name': filename,
            'programming_language': 'python',
        },
    )

    monkeypatch.setitem(
        __import__('sys').modules,
        'database',
        types.SimpleNamespace(db=dummy_db, CodeSnippet=DummyCodeSnippet),
    )

    from handlers import save_flow

    monkeypatch.setattr(save_flow.TextUtils, 'escape_markdown', lambda text, version=1: text, raising=False)
    monkeypatch.setattr(save_flow.code_service, 'detect_language', lambda code, filename: 'python', raising=False)

    update = MagicMock()
    update.message = MagicMock()
    update.message.reply_text = AsyncMock()

    context = MagicMock()
    context.user_data = {
        'code_to_save': 'print("world")',
        'note_to_save': 'legacy note',
        'pending_filename': 'legacy.py',
    }

    result = await save_flow.save_file_final(update, context, 'legacy.py', 9)

    assert result == save_flow.ConversationHandler.END
    update.message.reply_text.assert_awaited()
    assert saved_snippets['snippet'].description == 'legacy note'
    assert context.user_data.get('last_save_success')['file_name'] == 'legacy.py'
    assert 'pending_filename' not in context.user_data
