from datetime import datetime, timezone
from webapp import app as webapp_app


def _has_count_stage(pipeline):
    for stage in pipeline:
        if isinstance(stage, dict) and "$count" in stage:
            return True
    return False


class _CacheDisabled:
    is_enabled = False


class _CodeSnippetsAllowDiskUse:
    def __init__(self):
        self.allow_disk_use_values = []
        self.calls = 0
        self._doc = {
            "_id": "0123456789abcdef01234567",
            "file_name": "demo.py",
            "programming_language": "python",
            "description": "demo",
            "tags": [],
            "file_size": 10,
            "lines_count": 1,
            "created_at": datetime(2026, 2, 10, tzinfo=timezone.utc),
            "updated_at": datetime(2026, 2, 10, tzinfo=timezone.utc),
        }

    def aggregate(self, pipeline, allowDiskUse=False):
        self.calls += 1
        self.allow_disk_use_values.append(bool(allowDiskUse))
        if _has_count_stage(pipeline):
            return [{"total": 1}]
        return [dict(self._doc)]

    def distinct(self, _field, _query):
        return ["python"]


class _CodeSnippetsNoAllowDiskUseArg:
    def __init__(self):
        self.calls = 0
        self._doc = {
            "_id": "fedcba987654321001234567",
            "file_name": "fallback.py",
            "programming_language": "python",
            "description": "fallback",
            "tags": [],
            "file_size": 20,
            "lines_count": 2,
            "created_at": datetime(2026, 2, 10, tzinfo=timezone.utc),
            "updated_at": datetime(2026, 2, 10, tzinfo=timezone.utc),
        }

    def aggregate(self, pipeline):
        self.calls += 1
        if _has_count_stage(pipeline):
            return [{"total": 1}]
        return [dict(self._doc)]

    def distinct(self, _field, _query):
        return ["python"]


class _StubDB:
    def __init__(self, code_snippets):
        self.code_snippets = code_snippets


def _login(client):
    with client.session_transaction() as sess:
        sess["user_id"] = 123
        sess["user_data"] = {"id": 123, "first_name": "Test"}


def test_files_page_uses_allow_disk_use_when_supported(monkeypatch):
    collection = _CodeSnippetsAllowDiskUse()
    monkeypatch.setattr(webapp_app, "get_db", lambda: _StubDB(collection), raising=True)
    monkeypatch.setattr(webapp_app, "cache", _CacheDisabled(), raising=True)

    flask_app = webapp_app.app
    with flask_app.test_client() as client:
        _login(client)
        resp = client.get("/files")
        assert resp.status_code == 200
        assert "demo.py" in resp.get_data(as_text=True)

    assert collection.calls >= 2
    assert collection.allow_disk_use_values
    assert all(collection.allow_disk_use_values)


def test_files_page_falls_back_when_aggregate_stub_has_no_allow_disk_use(monkeypatch):
    collection = _CodeSnippetsNoAllowDiskUseArg()
    monkeypatch.setattr(webapp_app, "get_db", lambda: _StubDB(collection), raising=True)
    monkeypatch.setattr(webapp_app, "cache", _CacheDisabled(), raising=True)

    flask_app = webapp_app.app
    with flask_app.test_client() as client:
        _login(client)
        resp = client.get("/files")
        assert resp.status_code == 200
        assert "fallback.py" in resp.get_data(as_text=True)

    assert collection.calls >= 2
