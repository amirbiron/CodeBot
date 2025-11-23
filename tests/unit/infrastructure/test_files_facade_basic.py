import types
import sys

from src.infrastructure.composition.files_facade import FilesFacade


class DummyDB:
    def __init__(self):
        self.saved_snippets = []
        self.saved_large = []
        self.saved_prefs = {}
        self.tokens = {"access_token": "t"}

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
        return [{"file_name": "a.py", "programming_language": "python"}]

    def get_user_large_files(self, user_id, page=1, per_page=8):
        return ([{"file_name": "big"}], 1)

    def get_user_file_names(self, user_id, limit=1000):
        return ["a.py", "b.py"]

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
