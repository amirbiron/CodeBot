import types
from typing import Any, Dict, List

import pytest

class InMemoryCollection:
    def __init__(self):
        self.docs: List[Dict[str, Any]] = []

class FakeManager:
    def __init__(self):
        self.collection = InMemoryCollection()
        self.db = types.SimpleNamespace()

@pytest.fixture()
def repo():
    from database.repository import Repository
    return Repository(FakeManager())


def test_get_latest_version_none_when_empty(repo):
    res = repo.get_latest_version(1, 'missing.py')
    assert res is None
