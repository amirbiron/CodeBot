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


def test_get_latest_version_inmemory_ignores_absence(repo):
    # docs list exists but empty; should return None
    assert repo.get_latest_version(1, 'empty.py') is None

