import types
import sys

from src.infrastructure.composition.files_facade import FilesFacade


class DummyDB:
    def __init__(self):
        self.saved_snippets = []
        self.saved_large = []
        self.saved_prefs = {}
        self.tokens = {"access_token": "t"}
        self.regular_files = [
            {"file_name": "a.py", "programming_language": "python"},
            {"file_name": "b.py", "programming_language": "text"},
        ]
        self.repo_files = [{"file_name": "repo_file.py", "tag": "repo:me/app"}]
        self.search_results = [{"file_name": "search.py"}]
        self.deleted_rows = [{"_id": "del1", "file_name": "old.py"}]
        self._repo = DummyRepo(self.deleted_rows)

    # Snippet/file API
    def save_file(self, user_id, file_name, code, programming_language, extra_tags=None):
        self.saved_snippets.append((user_id, file_name, code, programming_language, list(extra_tags or [])))
        return True

    def save_code_snippet(self, snippet):
        self.saved_snippets.append(snippet)
        return True

    def save_large_file(self, large_file):
        self.saved_large.append(large_file)
        return True

    def get_latest_version(self, user_id, file_name):
        return {"user_id": user_id, "file_name": file_name, "code": "x", "programming_language": "python", "_id": "OID1", "version": 1}

    def get_all_versions(self, user_id, file_name):
        return [{"version": 1, "code": "x"}, {"version": 2, "code": "y"}]

    def delete_file(self, user_id, file_name):
        return True

    def is_favorite(self, user_id, file_name):
        return True

    def get_file_by_id(self, file_id):
        return {"_id": file_id, "file_name": "a.py", "code": "print(1)", "programming_language": "python"}

    def get_large_file_by_id(self, file_id):
        return {"_id": file_id, "file_name": "big", "content": "data", "programming_language": "text"}

    def get_large_file(self, user_id, file_name):
        return {"_id": "L1", "file_name": file_name, "content": "data", "programming_language": "text"}

    def get_user_files(self, user_id, limit=50, *, skip=0, projection=None):
        return self.regular_files[skip: skip + limit]

    def get_regular_files_paginated(self, user_id, page=1, per_page=10):
        total = len(self.regular_files)
        start = (page - 1) * per_page
        return (self.regular_files[start:start + per_page], total)

    def get_user_large_files(self, user_id, page=1, per_page=8):
        return ([{"file_name": "big"}], 1)

    def get_user_file_names(self, user_id, limit=1000):
        return ["a.py", "b.py"]

    def get_user_files_by_repo(self, user_id, repo_tag, page=1, per_page=50):
        return (self.repo_files, len(self.repo_files))

    def search_code(self, user_id, query, programming_language=None, tags=None, limit=20):
        return list(self.search_results)

    def get_version(self, user_id, file_name, version):
        return {"version": version, "file_name": file_name}

    def get_backup_rating(self, user_id, backup_id):
        return "👍"

    def save_user(self, user_id, username=None):
        self.saved_prefs["user_info"] = (user_id, username)
        return True

    def delete_file_by_id(self, file_id):
        self.saved_prefs["last_deleted_id"] = file_id
        return True

    # Drive/Repo prefs API
    def save_selected_repo(self, user_id, repo_full):
        self.saved_prefs["selected_repo"] = repo_full
        return True

    def get_drive_tokens(self, user_id):
        return dict(self.tokens)

    def get_drive_prefs(self, user_id):
        return dict(self.saved_prefs)

    def save_drive_prefs(self, user_id, update_prefs):
        self.saved_prefs.update(dict(update_prefs or {}))
        return True

    def delete_drive_tokens(self, user_id):
        self.tokens = {}
        return True

    def _get_repo(self):
        return self._repo


class DummyRepo:
    def __init__(self, rows):
        self.rows = rows
        self.restore_calls = []
        self.purge_calls = []

    def list_deleted_files(self, user_id, page=1, per_page=10):
        return (self.rows, len(self.rows))

    def restore_file_by_id(self, user_id, fid):
        self.restore_calls.append((user_id, fid))
        return True

    def purge_file_by_id(self, user_id, fid):
        self.purge_calls.append((user_id, fid))
        return True


def _install_dummy_database(monkeypatch):
    dummy_db = DummyDB()
    db_mod = types.ModuleType("database")
    db_mod.db = dummy_db
    models_mod = types.ModuleType("database.models")

    class CodeSnippet:  # minimal shape
        def __init__(self, user_id, file_name, code, programming_language, description="", tags=None):
            self.user_id = user_id
            self.file_name = file_name
            self.code = code
            self.programming_language = programming_language
            self.description = description
            self.tags = list(tags or [])

    class LargeFile:  # minimal shape
        def __init__(self, user_id, file_name, content, programming_language, file_size, lines_count):
            self.user_id = user_id
            self.file_name = file_name
            self.content = content
            self.programming_language = programming_language
            self.file_size = file_size
            self.lines_count = lines_count

    models_mod.CodeSnippet = CodeSnippet
    models_mod.LargeFile = LargeFile
    sys.modules["database"] = db_mod
    sys.modules["database.models"] = models_mod
    return dummy_db


def test_files_facade_basic_wrappers(monkeypatch):
    dummy_db = _install_dummy_database(monkeypatch)
    fac = FilesFacade()

    assert fac.save_file(1, "a.py", "print(1)", "python")
    assert fac.save_code_snippet(user_id=1, file_name="b.py", code="x", programming_language="python", description="d", tags=["t"])
    assert fac.save_large_file(user_id=1, file_name="big", content="data", programming_language="text", file_size=4, lines_count=1)

    latest = fac.get_latest_version(1, "a.py")
    assert latest and latest.get("file_name") == "a.py"
    vers = fac.get_all_versions(1, "a.py")
    assert len(vers) == 2 and vers[0]["version"] == 1
    assert fac.delete_file(1, "a.py") is True
    assert fac.is_favorite(1, "a.py") is True
    assert fac.get_file_by_id("OID1") and fac.get_large_file(1, "big") and fac.get_large_file_by_id("L1")
    names = fac.get_user_file_names(1)
    assert "a.py" in names
    small = fac.get_user_files(1, limit=1)
    assert isinstance(small, list)
    large, total = fac.get_user_large_files(1, page=1, per_page=1)
    assert isinstance(large, list) and isinstance(total, int)

    # Drive / Repo
    assert fac.save_selected_repo(1, "me/repo")
    tok = fac.get_drive_tokens(1)
    assert tok.get("access_token") == "t"
    prefs = fac.get_drive_prefs(1)
    assert prefs.get("selected_repo") == "me/repo"
    assert fac.save_drive_prefs(1, {"schedule": "daily"})
    assert fac.delete_drive_tokens(1) is True


def test_files_facade_pagination_and_recycle(monkeypatch):
    dummy_db = _install_dummy_database(monkeypatch)
    fac = FilesFacade()

    rows, total = fac.get_regular_files_paginated(1, page=1, per_page=10)
    assert total == len(dummy_db.regular_files)
    assert rows and rows[0]["file_name"] == "a.py"

    repo_rows, repo_total = fac.get_user_files_by_repo(1, "repo:me/app")
    assert repo_total == len(dummy_db.repo_files)

    search = fac.search_code(1, query="print")
    assert search == dummy_db.search_results

    version = fac.get_version(1, "a.py", 2)
    assert version["version"] == 2
    assert fac.get_backup_rating(1, "backup1") == "👍"
    assert fac.save_user(7, "tester")
    assert fac.delete_file_by_id("OID2")

    deleted_rows, deleted_total = fac.list_deleted_files(1, page=1, per_page=10)
    assert deleted_total == len(dummy_db.deleted_rows)
    assert fac.restore_file_by_id(1, "del1")
    assert fac.purge_file_by_id(1, "del1")
    assert dummy_db._repo.restore_calls and dummy_db._repo.purge_calls

    doc, is_large = fac.get_user_document_by_id(1, "OID1")
    assert doc and is_large is False
