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


class _CursorSortSkipLimit:
    def __init__(self, docs):
        self._docs = list(docs)
        self._skip = 0
        self._limit = None

    def sort(self, sort_spec):
        spec = list(sort_spec or [])
        # stable multi-key sort: apply from last to first
        for key, direction in reversed(spec):
            self._docs.sort(key=lambda d: d.get(key), reverse=(int(direction) == -1))
        return self

    def skip(self, n):
        self._skip = int(n or 0)
        return self

    def limit(self, n):
        self._limit = int(n or 0)
        return self

    def __iter__(self):
        data = self._docs[self._skip :]
        if self._limit is not None:
            data = data[: self._limit]
        return iter(data)


class _CodeSnippetsAggregateMemoryLimitWithFind:
    """
    Simulates OperationFailure(code=292) on the main /files cursor aggregation,
    while still supporting fallback .find() and metadata enrichment aggregation.
    """

    def __init__(self):
        self.calls = 0
        self._doc_full = {
            "_id": "aaaaaaaaaaaaaaaaaaaaaaaa",
            "user_id": 123,
            "is_active": True,
            "file_name": "old_doc.py",
            "programming_language": "python",
            "description": "old",
            "tags": [],
            "code": "a\nb",
            # legacy docs deliberately missing file_size/lines_count
            "created_at": datetime(2026, 2, 10, tzinfo=timezone.utc),
            "updated_at": datetime(2026, 2, 10, tzinfo=timezone.utc),
            "version": 1,
        }

    def aggregate(self, pipeline, allowDiskUse=False):
        from pymongo.errors import OperationFailure

        self.calls += 1
        stages = list(pipeline or [])

        # Fail only on the cursor pagination list pipeline that sorts by created_at/_id.
        for st in stages:
            if isinstance(st, dict) and "$sort" in st:
                sort = st.get("$sort") or {}
                if isinstance(sort, dict) and "created_at" in sort and "_id" in sort:
                    raise OperationFailure("ExceededMemoryLimit", code=292)

        # Count pipelines should still work.
        for st in stages:
            if isinstance(st, dict) and "$count" in st:
                return [{"total": 1}]

        # Metadata enrichment: match by _id list and project file_size/lines_count.
        match_ids = None
        for st in stages:
            if isinstance(st, dict) and "$match" in st:
                m = st.get("$match") or {}
                try:
                    match_ids = (m.get("_id") or {}).get("$in")
                except Exception:
                    match_ids = None
                break
        if match_ids:
            code = self._doc_full.get("code") or ""
            file_size = len(code.encode("utf-8", errors="ignore")) if code else 0
            lines_count = len(code.split("\n")) if code else 0
            if self._doc_full.get("_id") in set(match_ids):
                return [{"_id": self._doc_full["_id"], "file_size": file_size, "lines_count": lines_count}]
            return []

        # Any other aggregation can return a doc-shaped payload.
        return [dict(self._doc_full)]

    def find(self, query, projection):
        # basic query filtering for user_id/is_active, ignore other operators for this test
        q = dict(query or {})
        and_list = list(q.get("$and") or [])
        user_id = q.get("user_id")
        is_active = None
        for cond in and_list:
            if isinstance(cond, dict) and "is_active" in cond:
                is_active = cond.get("is_active")

        ok = True
        if user_id is not None:
            ok = ok and (self._doc_full.get("user_id") == user_id)
        if is_active is not None:
            ok = ok and (self._doc_full.get("is_active") == is_active)
        docs = [dict(self._doc_full)] if ok else []

        # Apply exclusion projection (e.g., {"code": 0, ...})
        proj = dict(projection or {})
        if proj and all(int(v) == 0 for v in proj.values()):
            for d in docs:
                for k, v in proj.items():
                    if int(v) == 0:
                        d.pop(k, None)

        return _CursorSortSkipLimit(docs)

    def distinct(self, _field, _query):
        return ["python"]


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


def test_files_page_memory_limit_fallback_enriches_legacy_size_and_lines(monkeypatch):
    collection = _CodeSnippetsAggregateMemoryLimitWithFind()
    monkeypatch.setattr(webapp_app, "get_db", lambda: _StubDB(collection), raising=True)
    monkeypatch.setattr(webapp_app, "cache", _CacheDisabled(), raising=True)

    flask_app = webapp_app.app
    with flask_app.test_client() as client:
        _login(client)
        resp = client.get("/files")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert "old_doc.py" in html
        # Legacy docs missing file_size/lines_count should still show computed values in fallback mode
        assert "2 שורות" in html
        assert "3.0 B" in html
