import pytest

from services.code_indexer import CodeIndexer


@pytest.fixture
def indexer():
    return CodeIndexer()


def test_should_index_python(indexer):
    assert indexer.should_index("src/main.py") is True
    assert indexer.should_index("node_modules/pkg/index.js") is False
    assert indexer.should_index(".coverage") is False
    assert indexer.should_index(".coveragerc") is True


def test_detect_language(indexer):
    assert indexer._detect_language("test.py") == "python"
    assert indexer._detect_language("app.tsx") == "typescript"


def test_extract_imports_python(indexer):
    content = """
import os
from typing import Dict, List
from services.git import GitService
"""
    imports = indexer._extract_imports(content, "python")

    assert "os" in imports
    assert "typing" in imports
    assert "services.git" in imports


def test_extract_functions_python(indexer):
    content = """
def hello():
    pass

async def fetch_data():
    pass
"""
    functions = indexer._extract_functions(content, "python")

    assert "hello" in functions
    assert "fetch_data" in functions


def test_line_count_splitlines_behavior(indexer):
    class _FakeRepoFiles:
        def __init__(self):
            self.last_set = None

        def update_one(self, filt, update, upsert=False):
            self.last_set = update.get("$set", {})
            return None

    class _FakeDb:
        def __init__(self):
            self.repo_files = _FakeRepoFiles()

    db = _FakeDb()
    idx = CodeIndexer(db=db)

    assert idx.index_file("Repo", "a.txt", "", commit_sha="a" * 40) is True
    assert db.repo_files.last_set["lines"] == 0

    assert idx.index_file("Repo", "b.txt", "hello\n", commit_sha="b" * 40) is True
    assert db.repo_files.last_set["lines"] == 1

