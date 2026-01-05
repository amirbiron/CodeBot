import types


def test_webapp_maintenance_cleanup_route_registered_and_allows_query_token(monkeypatch):
    # Import the Flask webapp module
    import webapp.app as webapp_app

    monkeypatch.setenv("DB_HEALTH_TOKEN", "test-db-health-token")

    class _StubDeleteColl:
        def __init__(self, *, has_legacy_metrics_ttl: bool):
            self.created_indexes = []
            self.deleted_calls = 0
            self.metrics_ttl_dropped = False
            self.has_legacy_metrics_ttl = bool(has_legacy_metrics_ttl)

        def delete_many(self, _q):
            self.deleted_calls += 1
            return types.SimpleNamespace(deleted_count=0)

        def index_information(self):
            if self.has_legacy_metrics_ttl:
                return {"metrics_ttl": {"key": [("ts", 1)], "expireAfterSeconds": 2592000}}
            return {}

        def drop_index(self, _name: str):
            if str(_name) == "metrics_ttl":
                self.metrics_ttl_dropped = True
            return None

        def create_index(self, _keys, **kwargs):
            if self.has_legacy_metrics_ttl and kwargs.get("expireAfterSeconds") is not None and not self.metrics_ttl_dropped:
                raise RuntimeError("IndexOptionsConflict: legacy metrics_ttl still exists")
            self.created_indexes.append(kwargs)
            return kwargs.get("name") or "idx"

    class _StubCodeSnippetsColl:
        def __init__(self):
            self._idx = {
                "_id_": {"key": [("_id", 1)]},
                "search_text_idx": {"key": [("file_name", "text")]},
                "user_id_1": {"key": [("user_id", 1)]},
                "user_file_unique": {"key": [("user_id", 1), ("file_name", 1)], "unique": True},
                "junk_idx": {"key": [("x", 1)]},
            }
            self.created = []

        def index_information(self):
            return dict(self._idx)

        def drop_index(self, name: str):
            self._idx.pop(name, None)

        def create_index(self, keys, **kwargs):
            self.created.append({"keys": keys, **kwargs})
            name = str(kwargs.get("name") or "idx")
            self._idx[name] = {"key": list(keys)}
            return name

    class _StubDB:
        def __init__(self):
            self.slow_queries_log = _StubDeleteColl(has_legacy_metrics_ttl=False)
            self.service_metrics = _StubDeleteColl(has_legacy_metrics_ttl=True)
            self.code_snippets = _StubCodeSnippetsColl()

    shared_db = _StubDB()
    monkeypatch.setattr(webapp_app, "get_db", lambda: shared_db, raising=True)

    with webapp_app.app.test_client() as client:
        # Query param auth should work for maintenance_cleanup
        resp = client.get("/api/debug/maintenance_cleanup?token=test-db-health-token")
        assert resp.status_code == 200
        payload = resp.get_json()
        assert payload and payload.get("ok") is True
        assert "metrics_ttl" in (payload.get("ttl", {}).get("service_metrics_pre_drop", {}) or {}).get("dropped", [])
        ensured = (payload.get("indexes") or {}).get("ensured") or {}
        assert ensured.get("name") == "user_updated_at"

        # But query token should NOT authorize /api/db/*
        resp2 = client.get("/api/db/pool?token=test-db-health-token")
        assert resp2.status_code == 401
        payload2 = resp2.get_json()
        assert payload2 and payload2.get("error") == "unauthorized"

        # Preview should not mutate (no deletes)
        before_deletes = shared_db.slow_queries_log.deleted_calls + shared_db.service_metrics.deleted_calls
        resp3 = client.get("/api/debug/maintenance_cleanup?token=test-db-health-token&preview=1")
        assert resp3.status_code == 200
        payload3 = resp3.get_json()
        assert payload3 and payload3.get("preview") is True
        assert payload3.get("deleted_documents", {}).get("total") == 0
        after_deletes = shared_db.slow_queries_log.deleted_calls + shared_db.service_metrics.deleted_calls
        assert after_deletes == before_deletes

