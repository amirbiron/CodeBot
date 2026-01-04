import types
import pytest


@pytest.mark.asyncio
async def test_maintenance_cleanup_disabled_without_token(monkeypatch):
    import services.webserver as ws

    # Token-based protection is enforced by middleware; if not configured -> disabled
    monkeypatch.setattr(ws, "DB_HEALTH_TOKEN", "", raising=True)

    app = ws.create_app()
    from aiohttp import web

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="127.0.0.1", port=0)
    await site.start()
    try:
        port = list(site._server.sockets)[0].getsockname()[1]
        import aiohttp

        async with aiohttp.ClientSession() as session:
            async with session.get(f"http://127.0.0.1:{port}/api/debug/maintenance_cleanup") as resp:
                assert resp.status == 403
                payload = await resp.json()
                assert payload.get("error") == "disabled"
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_maintenance_cleanup_purges_logs_and_drops_non_critical_indexes(monkeypatch):
    import services.webserver as ws

    monkeypatch.setattr(ws, "DB_HEALTH_TOKEN", "test-db-health-token", raising=True)

    class _StubDeleteColl:
        def __init__(self, deleted_count: int):
            self.deleted_count = deleted_count
            self.calls: list[dict] = []
            self.created_indexes: list[dict] = []
            self.dropped_indexes: list[str] = []

        def delete_many(self, query):
            self.calls.append(query)
            return types.SimpleNamespace(deleted_count=self.deleted_count)

        def index_information(self):
            # Simulate no indexes initially
            return {}

        def drop_index(self, name: str):
            self.dropped_indexes.append(str(name))

        def create_index(self, keys, **kwargs):
            self.created_indexes.append({"keys": keys, **kwargs})
            return kwargs.get("name") or "idx"

    class _StubCodeSnippetsColl:
        def __init__(self):
            # Mimic PyMongo index_information() format: name -> options dict
            self._idx = {
                "_id_": {"key": [("_id", 1)]},
                "search_text_idx": {"key": [("file_name", "text")]},
                # keep: single-field user_id index (name can vary)
                "user_id_1": {"key": [("user_id", 1)]},
                # keep: unique file name per user
                "user_file_unique": {"key": [("user_id", 1), ("file_name", 1)], "unique": True},
                "junk_idx_1": {"key": [("x", 1)]},
                "junk_idx_2": {"key": [("y", 1)]},
            }
            self.dropped: list[str] = []

        def index_information(self):
            return dict(self._idx)

        def drop_index(self, name: str):
            self.dropped.append(name)
            if name in self._idx:
                del self._idx[name]

    class _StubDB:
        def __init__(self):
            self.slow_queries_log = _StubDeleteColl(3)
            self.service_metrics = _StubDeleteColl(5)
            self.code_snippets = _StubCodeSnippetsColl()

    stub_db = _StubDB()

    import services.db_provider as dbp

    monkeypatch.setattr(dbp, "get_db", lambda: stub_db, raising=True)

    app = ws.create_app()
    from aiohttp import web

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="127.0.0.1", port=0)
    await site.start()
    try:
        port = list(site._server.sockets)[0].getsockname()[1]
        import aiohttp

        headers = {"Authorization": "Bearer test-db-health-token"}
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"http://127.0.0.1:{port}/api/debug/maintenance_cleanup", headers=headers
            ) as resp:
                assert resp.status == 200
                payload = await resp.json()

        assert payload.get("ok") is True
        deleted = payload.get("deleted_documents") or {}
        assert deleted.get("slow_queries_log") == 3
        assert deleted.get("service_metrics") == 5
        assert deleted.get("total") == 8

        ttl = payload.get("ttl") or {}
        # Ensure TTL indexes were attempted/created
        assert (ttl.get("slow_queries_log") or {}).get("expireAfterSeconds") == 604800
        assert (ttl.get("service_metrics_ts") or {}).get("expireAfterSeconds") == 86400

        idx = payload.get("indexes") or {}
        dropped = set(idx.get("dropped") or [])
        kept = set(idx.get("kept") or [])

        assert {"junk_idx_1", "junk_idx_2"} <= dropped
        assert {"_id_", "search_text_idx", "user_id_1", "user_file_unique"} <= kept

        # Ensure delete_many was called with {}
        assert stub_db.slow_queries_log.calls == [{}]
        assert stub_db.service_metrics.calls == [{}]

        # Ensure TTL create_index was called for both collections
        assert any(ci.get("expireAfterSeconds") == 604800 for ci in stub_db.slow_queries_log.created_indexes)
        assert any(ci.get("expireAfterSeconds") == 86400 for ci in stub_db.service_metrics.created_indexes)
    finally:
        await runner.cleanup()

