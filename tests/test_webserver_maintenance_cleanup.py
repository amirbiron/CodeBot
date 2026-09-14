import types

import pytest


class _StubDBBase:
    """גישת ``db["name"]`` בנוסף ל-``db.name``.

    ב-pymongo 4.15.3 גם ``Database.__getitem__`` וגם ``Database.__getattr__``
    מחזירות ``Collection(self, name)`` — אומת מול קוד המקור המותקן. דמה שתומכת
    רק בגישת תכונה נשברת ברגע שקוד הייצור קורא את שם האוסף ממשתנה.
    """

    def __getitem__(self, name):
        return getattr(self, str(name))


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
        """דמה של אוסף שההתנגשות בה היא **לפי מפתח**, כמו במונגו.

        קודם הדמה התנגשה לפי דגל בוליאני שנקשר לשם אחד קשיח (``metrics_ttl``),
        ולכן היא לא יכלה לתפוס את המקרה האמיתי: אינדקס TTL ישן בשם **אחר** על
        אותו מפתח. ‏``IndexOptionsConflict`` נובע משיתוף מפתח עם אופציות שונות,
        לא משיתוף שם.
        """

        def __init__(self, deleted_count: int, *, indexes: dict | None = None):
            self.deleted_count = deleted_count
            self.calls: list[dict] = []
            self.created_indexes: list[dict] = []
            self.dropped_indexes: list[str] = []
            self._idx: dict = dict(indexes or {})

        def delete_many(self, query):
            self.calls.append(query)
            return types.SimpleNamespace(deleted_count=self.deleted_count)

        def index_information(self):
            return dict(self._idx)

        def drop_index(self, name: str):
            self.dropped_indexes.append(str(name))
            self._idx.pop(str(name), None)

        def create_index(self, keys, **kwargs):
            want_key = [(str(k), int(v)) for k, v in list(keys)]
            for existing_name, meta in self._idx.items():
                if list(meta.get("key") or []) != want_key:
                    continue
                same_name = str(existing_name) == str(kwargs.get("name") or "")
                same_ttl = meta.get("expireAfterSeconds") == kwargs.get("expireAfterSeconds")
                if not (same_name and same_ttl):
                    raise RuntimeError("IndexOptionsConflict: index on the same key already exists")
            self.created_indexes.append({"keys": keys, **kwargs})
            name = str(kwargs.get("name") or "idx")
            meta = {"key": want_key}
            if kwargs.get("expireAfterSeconds") is not None:
                meta["expireAfterSeconds"] = kwargs["expireAfterSeconds"]
            self._idx[name] = meta
            return name

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
            self.created: list[dict] = []

        def index_information(self):
            return dict(self._idx)

        def drop_index(self, name: str):
            self.dropped.append(name)
            if name in self._idx:
                del self._idx[name]

        def create_index(self, keys, **kwargs):
            self.created.append({"keys": keys, **kwargs})
            # Record creation by name for subsequent index_information
            name = str(kwargs.get("name") or "idx")
            self._idx[name] = {"key": list(keys)}
            return name

    class _StubDB(_StubDBBase):
        def __init__(self):
            self.slow_queries_log = _StubDeleteColl(3)
            # אינדקס TTL ישן של 24 שעות בשם שגרסה קודמת של ה-endpoint יצרה.
            # הוא על אותו מפתח, ולכן חוסם את היצירה עד שמפילים אותו.
            self.service_metrics = _StubDeleteColl(
                5,
                indexes={
                    # חוסם: אותו מפתח, שם אחר
                    "ttl_cleanup_ts": {"key": [("ts", 1)], "expireAfterSeconds": 86400},
                    # אינרטי: אין שום כותב לשדה ``timestamp`` באוסף הזה
                    "ttl_cleanup": {"key": [("timestamp", 1)], "expireAfterSeconds": 86400},
                },
            )
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
        # 30 יום, מהקבוע שגם יוצר את האינדקס בעלייה — ולא 86400 קשיח, שסתר את
        # טווח ה-30 יום של הדשבורד ושל ה-warmup (אישיו #3331).
        assert (ttl.get("service_metrics_ts") or {}).get("expireAfterSeconds") == 30 * 24 * 3600
        assert (ttl.get("service_metrics_ts") or {}).get("name") == "metrics_ttl"
        # ה-TTL על ``timestamp`` הוסר: אין לשדה הזה כותב, והאינדקס לא מחק כלום.
        assert "service_metrics_timestamp" not in ttl
        # שני השרידים הופלו — החוסם וגם האינרטי, שאיש לא מרגיש בו
        assert sorted((ttl.get("service_metrics_pre_drop") or {}).get("dropped", [])) == [
            "ttl_cleanup",
            "ttl_cleanup_ts",
        ]

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
        # אינדקס TTL חייב להיות חד-שדה (MongoDB Manual, TTL Indexes; מול
        # mongod 7.0.14 נמדד שהשרת דוחה יצירת TTL על אינדקס מורכב).
        metrics_ttl_created = [
            ci for ci in stub_db.service_metrics.created_indexes if ci.get("expireAfterSeconds") is not None
        ]
        assert [ci.get("expireAfterSeconds") for ci in metrics_ttl_created] == [30 * 24 * 3600]
        assert list(metrics_ttl_created[0]["keys"]) == [("ts", 1)]

        # Ensure UI sort index was ensured
        ensured = idx.get("ensured") or {}
        assert ensured.get("name") == "user_updated_at"
        assert any((ci.get("name") == "user_updated_at") for ci in stub_db.code_snippets.created)
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_maintenance_cleanup_preview_does_not_mutate(monkeypatch):
    import services.webserver as ws

    monkeypatch.setattr(ws, "DB_HEALTH_TOKEN", "test-db-health-token", raising=True)

    class _StubDeleteColl:
        def __init__(self):
            self.calls = []

        def delete_many(self, query):
            self.calls.append(query)
            return types.SimpleNamespace(deleted_count=123)

        def index_information(self):
            return {}

        def drop_index(self, _name: str):
            raise AssertionError("drop_index should not be called in preview")

        def create_index(self, _keys, **_kwargs):
            raise AssertionError("create_index should not be called in preview")

    class _StubCodeSnippetsColl:
        def __init__(self):
            self._idx = {"_id_": {"key": [("_id", 1)]}, "junk": {"key": [("x", 1)]}}

        def index_information(self):
            return dict(self._idx)

        def drop_index(self, _name: str):
            raise AssertionError("drop_index should not be called in preview")

    class _StubDB(_StubDBBase):
        slow_queries_log = _StubDeleteColl()
        service_metrics = _StubDeleteColl()
        code_snippets = _StubCodeSnippetsColl()

    import services.db_provider as dbp
    monkeypatch.setattr(dbp, "get_db", lambda: _StubDB(), raising=True)

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
                f"http://127.0.0.1:{port}/api/debug/maintenance_cleanup?preview=1",
                headers=headers,
            ) as resp:
                assert resp.status == 200
                payload = await resp.json()
                assert payload.get("ok") is True
                assert payload.get("preview") is True
                deleted = payload.get("deleted_documents") or {}
                assert deleted.get("total") == 0
                idx = payload.get("indexes") or {}
                assert "before_details" in idx
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_maintenance_cleanup_allows_token_via_query_param(monkeypatch):
    import services.webserver as ws

    monkeypatch.setattr(ws, "DB_HEALTH_TOKEN", "test-db-health-token", raising=True)

    class _StubDeleteColl:
        def delete_many(self, _q):
            return types.SimpleNamespace(deleted_count=0)

        def index_information(self):
            return {}

        def drop_index(self, _name: str):
            return None

        def create_index(self, _keys, **_kwargs):
            return _kwargs.get("name") or "idx"

    class _StubCodeSnippetsColl:
        def index_information(self):
            return {"_id_": {"key": [("_id", 1)]}}

        def drop_index(self, _name: str):
            return None

    class _StubDB(_StubDBBase):
        slow_queries_log = _StubDeleteColl()
        service_metrics = _StubDeleteColl()
        code_snippets = _StubCodeSnippetsColl()

    import services.db_provider as dbp

    monkeypatch.setattr(dbp, "get_db", lambda: _StubDB(), raising=True)

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
            async with session.get(
                f"http://127.0.0.1:{port}/api/debug/maintenance_cleanup?token=test-db-health-token"
            ) as resp:
                assert resp.status == 200
                payload = await resp.json()
                assert payload.get("ok") is True

            # Query token should NOT authorize /api/db/*
            async with session.get(
                f"http://127.0.0.1:{port}/api/db/pool?token=test-db-health-token"
            ) as resp_db:
                assert resp_db.status == 401
                payload_db = await resp_db.json()
                assert payload_db.get("error") == "unauthorized"

            async with session.get(
                f"http://127.0.0.1:{port}/api/debug/maintenance_cleanup?token=wrong"
            ) as resp2:
                assert resp2.status == 401
                payload2 = await resp2.json()
                assert payload2.get("error") == "unauthorized"
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_failed_ttl_creation_returns_500_and_restores_the_index(monkeypatch):
    """אותה התנהגות כמו במראה ב-Flask: כשל ביצירת TTL אינו 200.

    הסדר הוא drop ואז create, ולכן כשל ביצירה משאיר את האוסף בלי TTL בכלל —
    מצב גרוע מזה שלפני הקריאה. ההגדרה הישנה חוזרת, והתשובה אומרת שנכשלה.
    """
    import services.webserver as ws

    monkeypatch.setattr(ws, "DB_HEALTH_TOKEN", "test-db-health-token", raising=True)

    class _RefusingColl:
        def __init__(self, indexes=None):
            self._idx = dict(indexes or {})

        def delete_many(self, _q):
            return types.SimpleNamespace(deleted_count=0)

        def index_information(self):
            return dict(self._idx)

        def drop_index(self, name):
            self._idx.pop(str(name), None)

        def create_index(self, keys, **kwargs):
            if kwargs.get("expireAfterSeconds") == 30 * 24 * 3600:
                raise RuntimeError("IndexOptionsConflict: simulated")
            name = str(kwargs.get("name") or "idx")
            meta = {"key": [(str(k), v) for k, v in list(keys)]}
            if kwargs.get("expireAfterSeconds") is not None:
                meta["expireAfterSeconds"] = kwargs["expireAfterSeconds"]
            self._idx[name] = meta
            return name

    metrics = _RefusingColl({"metrics_ttl": {"key": [("ts", 1)], "expireAfterSeconds": 86400}})

    class _StubDB(_StubDBBase):
        def __init__(self):
            self.slow_queries_log = _RefusingColl()
            self.service_metrics = metrics
            self.code_snippets = _RefusingColl({"_id_": {"key": [("_id", 1)]}})

    import services.db_provider as dbp

    monkeypatch.setattr(dbp, "get_db", lambda: _StubDB(), raising=True)

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
                assert resp.status == 500, "כשל ביצירת TTL חזר כ-200"
                payload = await resp.json()

        assert payload.get("ok") is False
        assert "service_metrics_ts" in (payload.get("ttl_failures") or [])
        entry = (payload.get("ttl") or {}).get("service_metrics_ts") or {}
        assert entry.get("restored_previous_index") == "restored"
        assert metrics.index_information().get("metrics_ttl", {}).get("expireAfterSeconds") == 86400
    finally:
        await runner.cleanup()
