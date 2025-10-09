import types
import pytest

class InMemoryCollection:
    def __init__(self):
        self.docs = []

class FakeManager:
    def __init__(self):
        self.collection = InMemoryCollection()
        self.db = types.SimpleNamespace()

@pytest.fixture()
def repo():
    from database.repository import Repository
    return Repository(FakeManager())


def test_toggle_favorite_invalid_filename_returns_none(repo):
    assert repo.toggle_favorite(1, 'bad/name.py') is None
    assert repo.toggle_favorite(1, 'evil*name.py') is None
    assert repo.toggle_favorite(1, '') is None
