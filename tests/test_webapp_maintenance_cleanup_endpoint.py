import types


def test_webapp_maintenance_cleanup_route_registered_and_allows_query_token(monkeypatch):
    # Import the Flask webapp module
    import webapp.app as webapp_app

    monkeypatch.setenv("DB_HEALTH_TOKEN", "test-db-health-token")

    class _StubDeleteColl:
        def __init__(self):
            self.created_indexes = []

        def delete_many(self, _q):
            return types.SimpleNamespace(deleted_count=0)

        def index_information(self):
            return {}

        def drop_index(self, _name: str):
            return None

        def create_index(self, _keys, **kwargs):
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

        def index_information(self):
            return dict(self._idx)

        def drop_index(self, name: str):
            self._idx.pop(name, None)

    class _StubDB:
        slow_queries_log = _StubDeleteColl()
        service_metrics = _StubDeleteColl()
        code_snippets = _StubCodeSnippetsColl()

    monkeypatch.setattr(webapp_app, "get_db", lambda: _StubDB(), raising=True)

    with webapp_app.app.test_client() as client:
        # Query param auth should work for maintenance_cleanup
        resp = client.get("/api/debug/maintenance_cleanup?token=test-db-health-token")
        assert resp.status_code == 200
        payload = resp.get_json()
        assert payload and payload.get("ok") is True

        # But query token should NOT authorize /api/db/*
        resp2 = client.get("/api/db/pool?token=test-db-health-token")
        assert resp2.status_code == 401
        payload2 = resp2.get_json()
        assert payload2 and payload2.get("error") == "unauthorized"

