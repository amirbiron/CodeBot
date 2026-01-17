from __future__ import annotations

from dataclasses import dataclass

import pytest

# repo_sync_service מייבא pymongo.ReturnDocument בטופ-לבל.
# בחלק מסביבות הפיתוח (כולל סביבת הסוכן כאן) pymongo לא מותקן,
# אבל לטסטים שלנו מספיק stub מינימלי כדי לאפשר import.
try:
    import pymongo as _pymongo  # noqa: F401
except Exception:  # pragma: no cover
    import sys
    import types

    _pymongo_stub = types.ModuleType("pymongo")

    class ReturnDocument:  # noqa: D401 - stub
        AFTER = object()

    _pymongo_stub.ReturnDocument = ReturnDocument
    sys.modules["pymongo"] = _pymongo_stub


class _FakeRepoMetadataCollection:
    def __init__(self) -> None:
        self.last_update = None

    def update_one(self, filt, update, upsert=False):  # noqa: D401 - test stub
        self.last_update = {"filter": filt, "update": update, "upsert": upsert}
        return None


class _FakeDb:
    def __init__(self) -> None:
        self.repo_metadata = _FakeRepoMetadataCollection()


@dataclass
class _GitCommandResult:
    success: bool
    stdout: str
    stderr: str = ""
    return_code: int = 0


class _StubGitService:
    def __init__(self, *, list_files=None, current_sha=None, head_branch="main") -> None:
        self._list_files = list_files
        self._current_sha = current_sha
        self._head_branch = head_branch

    def init_mirror(self, repo_url: str, repo_name: str):
        return {"success": True, "path": f"/tmp/{repo_name}.git", "already_existed": True}

    def _get_repo_path(self, repo_name: str):
        return f"/tmp/{repo_name}.git"

    def _run_git_command(self, cmd, cwd=None, timeout=60):
        # HEAD branch detection
        if cmd[:3] == ["git", "symbolic-ref", "--short"]:
            return _GitCommandResult(success=True, stdout=self._head_branch)
        # SHA resolution fallback
        if cmd[:2] == ["git", "rev-parse"]:
            # return a stable SHA for tests
            return _GitCommandResult(success=True, stdout="a" * 40)
        return _GitCommandResult(success=False, stdout="", stderr="unsupported", return_code=1)

    def list_all_files(self, repo_name: str, ref: str = "HEAD"):
        return self._list_files

    def get_current_sha(self, repo_name: str, branch: str = "main"):
        return self._current_sha

    def get_file_content(self, repo_name: str, file_path: str, ref: str = "HEAD"):
        return "print('ok')\n"


class _StubIndexer:
    def __init__(self, db=None) -> None:
        self.db = db

    def should_index(self, file_path: str) -> bool:
        return True

    def index_file(self, repo_name: str, file_path: str, content: str, commit_sha: str = "HEAD") -> bool:
        return True


def test_initial_import_fails_fast_when_list_all_files_returns_none(monkeypatch):
    from services import repo_sync_service as rss

    db = _FakeDb()
    monkeypatch.setattr(rss, "get_mirror_service", lambda: _StubGitService(list_files=None, current_sha="b" * 40))
    monkeypatch.setattr(rss, "CodeIndexer", _StubIndexer)

    out = rss.initial_import("https://example.com/repo.git", "Repo", db)
    assert out.get("error") == "Failed to list repository files"


def test_initial_import_never_stores_symbolic_head_sha(monkeypatch):
    from services import repo_sync_service as rss

    db = _FakeDb()
    # get_current_sha returns None => must fall back to rev-parse and store real SHA
    monkeypatch.setattr(rss, "get_mirror_service", lambda: _StubGitService(list_files=["a.py"], current_sha=None))
    monkeypatch.setattr(rss, "CodeIndexer", _StubIndexer)

    out = rss.initial_import("https://example.com/repo.git", "Repo", db)
    assert out["status"] == "completed"
    assert out["sha"] == ("a" * 7)
    saved = (db.repo_metadata.last_update or {}).get("update", {}).get("$set", {})
    assert saved.get("last_synced_sha") == ("a" * 40)


def test_initial_import_counts_read_failures_as_errors(monkeypatch):
    from services import repo_sync_service as rss

    class _Git(_StubGitService):
        def get_file_content(self, repo_name: str, file_path: str, ref: str = "HEAD"):
            return None

    db = _FakeDb()
    monkeypatch.setattr(rss, "get_mirror_service", lambda: _Git(list_files=["a.py"], current_sha="c" * 40))
    monkeypatch.setattr(rss, "CodeIndexer", _StubIndexer)

    out = rss.initial_import("https://example.com/repo.git", "Repo", db)
    assert out["total_files"] == 1
    assert out["indexed"] == 0
    assert out["errors"] == 1

