import types
import pytest


@pytest.mark.asyncio
async def test_snippet_repository_adapter_mapping(monkeypatch):
    # Prepare env/modules to avoid real DB/config imports
    # Stub database.manager before importing the adapter
    fake_manager = types.SimpleNamespace(DatabaseManager=object)
    monkeypatch.setitem(__import__("sys").modules, 'database.manager', fake_manager)

    # Import after stubbing
    from src.infrastructure.database.mongodb.repositories.snippet_repository import SnippetRepository
    from src.domain.entities.snippet import Snippet

    class FakeDB:
        def __init__(self):
            self.saved = None

        def save_code_snippet(self, code_snippet):
            self.saved = code_snippet
            return True

        def get_latest_version(self, user_id, filename):
            return {
                'user_id': user_id,
                'file_name': filename,
                'code': self.saved.code if self.saved else '',
                'programming_language': self.saved.programming_language if self.saved else 'text',
                'description': self.saved.description if self.saved else '',
                'tags': self.saved.tags if self.saved else [],
                'version': 2,
                'is_favorite': False,
                'created_at': __import__('datetime').datetime.now(__import__('datetime').timezone.utc),
                'updated_at': __import__('datetime').datetime.now(__import__('datetime').timezone.utc),
                'is_active': True,
            }

        def search_code(self, user_id, query, programming_language=None, tags=None, limit=20):
            return [
                {
                    'user_id': user_id,
                    'file_name': 'a.py',
                    'code': 'print(1)',
                    'programming_language': 'python',
                    'description': '',
                    'tags': [],
                    'version': 1,
                    'is_favorite': False,
                    'created_at': __import__('datetime').datetime.now(__import__('datetime').timezone.utc),
                    'updated_at': __import__('datetime').datetime.now(__import__('datetime').timezone.utc),
                    'is_active': True,
                }
            ]

    repo = SnippetRepository(FakeDB())

    domain_snippet = Snippet(user_id=10, filename='t.py', code='print(1)', language='python')
    saved = await repo.save(domain_snippet)

    assert saved.user_id == 10
    assert saved.filename == 't.py'
    assert saved.language == 'python'
    assert saved.version == 2  # from fake DB latest

    latest = await repo.get_latest_version(10, 't.py')
    assert latest is not None
    assert latest.filename == 't.py'

    results = await repo.search(10, query='')
    assert results and results[0].filename == 'a.py'
