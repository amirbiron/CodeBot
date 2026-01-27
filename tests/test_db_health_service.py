import os
from unittest.mock import AsyncMock, MagicMock

import pytest
from bson import ObjectId

from services.db_health_service import (
    AsyncDatabaseHealthService,
    CollectionStat,
    CollectionAccessDeniedError,
    InvalidCollectionNameError,
    PoolStatus,
    SlowOperation,
    ThreadPoolDatabaseHealthService,
    SENSITIVE_FIELDS,
    _redact_sensitive_fields,
    _validate_collection_name,
)


class TestPoolStatus:
    """בדיקות ל-PoolStatus dataclass."""

    def test_health_status_healthy(self):
        status = PoolStatus(current=10, available=90, utilization_pct=10)
        assert status._health_status() == "healthy"

    def test_health_status_warning(self):
        status = PoolStatus(current=70, available=30, utilization_pct=70)
        assert status._health_status() == "warning"

    def test_health_status_critical(self):
        status = PoolStatus(current=95, available=5, utilization_pct=95)
        assert status._health_status() == "critical"

    def test_health_status_critical_with_queue(self):
        status = PoolStatus(current=50, available=50, wait_queue_size=15, utilization_pct=50)
        assert status._health_status() == "critical"

    def test_to_dict(self):
        status = PoolStatus(current=10, available=40, total_created=100, utilization_pct=20.0)
        result = status.to_dict()

        assert result["current"] == 10
        assert result["available"] == 40
        assert result["utilization_pct"] == 20.0
        assert result["status"] == "healthy"


class TestSlowOperation:
    """בדיקות ל-SlowOperation dataclass."""

    def test_severity_info(self):
        op = SlowOperation(op_id="1", operation_type="query", namespace="test.users", running_secs=2.0, query={})
        assert op._severity() == "info"

    def test_severity_warning(self):
        op = SlowOperation(op_id="1", operation_type="query", namespace="test.users", running_secs=7.0, query={})
        assert op._severity() == "warning"

    def test_severity_critical(self):
        op = SlowOperation(op_id="1", operation_type="query", namespace="test.users", running_secs=15.0, query={})
        assert op._severity() == "critical"


@pytest.mark.asyncio
class TestAsyncDatabaseHealthService:
    """בדיקות יחידה ל-AsyncDatabaseHealthService."""

    @pytest.fixture
    def mock_motor_client(self):
        """Mock של Motor AsyncIOMotorClient."""
        client = AsyncMock()
        client.admin.command = AsyncMock()
        return client

    @pytest.fixture
    async def service(self, mock_motor_client):
        """Service עם client מוק."""
        svc = AsyncDatabaseHealthService.__new__(AsyncDatabaseHealthService)
        svc._client = mock_motor_client
        svc._db = AsyncMock()
        return svc

    async def test_get_pool_status_success(self, service, mock_motor_client):
        """בדיקת שליפת מצב pool תקינה."""
        mock_motor_client.admin.command.return_value = {
            "connections": {
                "current": 10,
                "available": 40,
                "totalCreated": 150,
            }
        }

        result = await service.get_pool_status()

        assert result.current == 10
        assert result.available == 40
        assert result.total_created == 150
        assert result.utilization_pct == 20.0  # 10/50 * 100

        # וודא שהקריאה נעשתה עם await
        mock_motor_client.admin.command.assert_awaited_once_with("serverStatus")

    async def test_get_pool_status_no_client(self):
        """בדיקת שגיאה כשאין client."""
        svc = AsyncDatabaseHealthService.__new__(AsyncDatabaseHealthService)
        svc._client = None

        with pytest.raises(RuntimeError, match="No MongoDB client"):
            await svc.get_pool_status()

    async def test_get_current_operations_filters_by_threshold(self, service, mock_motor_client):
        """בדיקת סינון לפי סף זמן."""
        mock_motor_client.admin.command.return_value = {
            "inprog": [
                {"opid": 1, "op": "query", "ns": "test.users", "secs_running": 2.5},
                {"opid": 2, "op": "query", "ns": "test.logs", "secs_running": 0.5},  # מתחת לסף
                {"opid": 3, "op": "update", "ns": "test.data", "secs_running": 5.0},
            ]
        }

        result = await service.get_current_operations(threshold_ms=1000)

        assert len(result) == 2
        assert result[0].running_secs == 5.0  # ממוין לפי זמן (הארוך קודם)
        assert result[1].running_secs == 2.5

    async def test_get_current_operations_excludes_system(self, service, mock_motor_client):
        """בדיקת סינון פעולות מערכת."""
        mock_motor_client.admin.command.return_value = {
            "inprog": [
                {"opid": 1, "op": "query", "ns": "test.users", "secs_running": 2.5},
                {"opid": 2, "op": "query", "ns": "admin.system", "secs_running": 3.0},  # מערכת
                {"opid": 3, "op": "query", "ns": "local.oplog", "secs_running": 4.0},  # מערכת
            ]
        }

        result = await service.get_current_operations(threshold_ms=1000, include_system=False)

        assert len(result) == 1
        assert result[0].namespace == "test.users"

    async def test_get_collection_stats_success(self, service):
        """בדיקת שליפת סטטיסטיקות collections."""
        service._db.list_collection_names = AsyncMock(return_value=["users", "logs"])
        service._db.command = AsyncMock(
            side_effect=[
                {
                    "count": 1000,
                    "size": 1024 * 1024,
                    "nindexes": 3,
                    "storageSize": 2 * 1024 * 1024,
                    "totalIndexSize": 512 * 1024,
                    "avgObjSize": 512,
                },
                {
                    "count": 5000,
                    "size": 5 * 1024 * 1024,
                    "nindexes": 2,
                    "storageSize": 6 * 1024 * 1024,
                    "totalIndexSize": 256 * 1024,
                    "avgObjSize": 256,
                },
            ]
        )

        result = await service.get_collection_stats()

        assert len(result) == 2
        assert result[0].name == "logs"  # ממוין לפי גודל (הגדול קודם)
        assert result[0].count == 5000
        assert result[1].name == "users"
        assert result[1].count == 1000

    async def test_get_health_summary_healthy(self, service, mock_motor_client):
        """בדיקת סיכום בריאות תקין."""
        # Pool תקין
        mock_motor_client.admin.command.side_effect = [
            {"connections": {"current": 10, "available": 90, "totalCreated": 100}},  # serverStatus
            {"inprog": []},  # currentOp - אין slow queries
        ]
        service._db.list_collection_names = AsyncMock(return_value=["users", "logs"])

        result = await service.get_health_summary()

        assert result["status"] == "healthy"
        assert result["slow_queries_count"] == 0
        assert result["collections_count"] == 2
        assert len(result["errors"]) == 0


@pytest.mark.asyncio
class TestThreadPoolDatabaseHealthService:
    """בדיקות ל-ThreadPoolDatabaseHealthService (PyMongo wrapper)."""

    @pytest.fixture
    def mock_db_manager(self):
        """Mock של DatabaseManager הסינכרוני."""
        manager = MagicMock()
        manager.client = MagicMock()
        manager.db = MagicMock()
        return manager

    @pytest.fixture
    def service(self, mock_db_manager):
        return ThreadPoolDatabaseHealthService(mock_db_manager)

    async def test_get_pool_status_runs_in_thread(self, service, mock_db_manager):
        """בדיקה שהקריאה רצה ב-thread pool ולא חוסמת."""
        mock_db_manager.client.admin.command.return_value = {
            "connections": {"current": 5, "available": 45, "totalCreated": 50}
        }

        result = await service.get_pool_status()

        assert result.current == 5
        assert result.available == 45
        # הקריאה הסינכרונית נעשתה
        mock_db_manager.client.admin.command.assert_called_once_with("serverStatus")


# Integration test (דורש MongoDB אמיתי)
@pytest.mark.integration
@pytest.mark.asyncio
class TestDatabaseHealthServiceIntegration:
    """בדיקות אינטגרציה - רצות רק עם MongoDB אמיתי."""

    @pytest.fixture
    async def service(self):
        """יצירת service אמיתי."""
        enabled = str(os.getenv("RUN_DB_HEALTH_INTEGRATION", "") or "").strip().lower() in {"1", "true", "yes"}
        if not enabled:
            pytest.skip("DB health integration tests are disabled (set RUN_DB_HEALTH_INTEGRATION=1)")
        if not os.getenv("MONGODB_URL"):
            pytest.skip("MONGODB_URL not set")

        svc = AsyncDatabaseHealthService()
        await svc.connect()
        yield svc
        await svc.close()

    async def test_real_pool_status(self, service):
        """בדיקת שליפת pool אמיתית."""
        result = await service.get_pool_status()

        assert result.current >= 0
        assert result.available >= 0
        assert result.to_dict()["status"] in ("healthy", "warning", "critical")

    async def test_real_current_ops(self, service):
        """בדיקת שליפת ops אמיתית."""
        result = await service.get_current_operations(threshold_ms=0)

        assert isinstance(result, list)
        for op in result:
            assert isinstance(op, SlowOperation)

    async def test_real_collection_stats(self, service):
        """בדיקת שליפת stats אמיתית."""
        result = await service.get_collection_stats()

        assert isinstance(result, list)
        for stat in result:
            assert isinstance(stat, CollectionStat)
            assert stat.name
            assert stat.count >= 0


class TestRedactSensitiveFields:
    """בדיקות לפונקציית _redact_sensitive_fields."""

    def test_sensitive_fields_contains_password(self):
        assert "password" in SENSITIVE_FIELDS

    def test_redacts_password_field(self):
        doc = {"name": "Alice", "password": "secret123"}
        result = _redact_sensitive_fields(doc)
        assert result["name"] == "Alice"
        assert result["password"] == "[REDACTED]"

    def test_redacts_nested_fields(self):
        doc = {"user": {"name": "Bob", "api_key": "key123"}}
        result = _redact_sensitive_fields(doc)
        assert result["user"]["name"] == "Bob"
        assert result["user"]["api_key"] == "[REDACTED]"

    def test_redacts_in_arrays(self):
        doc = {"users": [{"name": "A", "token": "t1"}, {"name": "B", "token": "t2"}]}
        result = _redact_sensitive_fields(doc)
        assert result["users"][0]["token"] == "[REDACTED]"
        assert result["users"][1]["token"] == "[REDACTED]"

    def test_case_insensitive_redaction(self):
        doc = {"Password": "secret", "API_KEY": "key"}
        result = _redact_sensitive_fields(doc)
        assert result["Password"] == "[REDACTED]"
        assert result["API_KEY"] == "[REDACTED]"


class TestValidateCollectionName:
    """בדיקות לפונקציית _validate_collection_name."""

    def test_valid_name_passes(self):
        _validate_collection_name("users")  # לא זורק

    def test_empty_name_raises(self):
        with pytest.raises(InvalidCollectionNameError):
            _validate_collection_name("")

    def test_dollar_prefix_raises(self):
        with pytest.raises(InvalidCollectionNameError):
            _validate_collection_name("$system")

    def test_null_char_raises(self):
        with pytest.raises(InvalidCollectionNameError):
            _validate_collection_name("users\0test")

    def test_double_dot_raises(self):
        with pytest.raises(InvalidCollectionNameError):
            _validate_collection_name("users..test")


@pytest.mark.asyncio
class TestGetDocuments:
    """בדיקות לפונקציית get_documents."""

    @pytest.fixture
    async def service_with_mock_db(self):
        """Service עם DB מוק."""
        svc = AsyncDatabaseHealthService.__new__(AsyncDatabaseHealthService)
        svc._client = AsyncMock()
        svc._db = AsyncMock()
        return svc

    async def test_get_documents_success_with_more_pages(self, service_with_mock_db):
        """בדיקת שליפה תקינה עם עמודים נוספים (עמוד מלא)."""
        svc = service_with_mock_db

        # Mock collection
        mock_collection = MagicMock()
        mock_collection.count_documents = AsyncMock(return_value=100)

        # Mock cursor with sort - מחזיר עמוד מלא (20 מסמכים)
        mock_cursor = AsyncMock()
        mock_docs = [{'_id': ObjectId(), 'name': f'User{i}'} for i in range(20)]
        mock_cursor.to_list = AsyncMock(return_value=mock_docs)
        mock_collection.find.return_value.sort.return_value.skip.return_value.limit.return_value = mock_cursor

        svc._db.__getitem__ = MagicMock(return_value=mock_collection)

        result = await svc.get_documents('users', skip=0, limit=20)

        assert result['collection'] == 'users'
        assert result['total'] == 100
        assert len(result['documents']) == 20
        # has_more=True כי קיבלנו עמוד מלא (len == limit)
        assert result['has_more'] is True
        assert result['skip'] == 0
        assert result['limit'] == 20

    async def test_get_documents_last_page(self, service_with_mock_db):
        """בדיקת שליפה בעמוד האחרון (עמוד חלקי)."""
        svc = service_with_mock_db

        mock_collection = MagicMock()
        mock_collection.count_documents = AsyncMock(return_value=25)

        # Mock cursor - מחזיר רק 5 מסמכים (עמוד חלקי)
        mock_cursor = AsyncMock()
        mock_docs = [{'_id': ObjectId(), 'name': f'User{i}'} for i in range(5)]
        mock_cursor.to_list = AsyncMock(return_value=mock_docs)
        mock_collection.find.return_value.sort.return_value.skip.return_value.limit.return_value = mock_cursor

        svc._db.__getitem__ = MagicMock(return_value=mock_collection)

        result = await svc.get_documents('users', skip=20, limit=20)

        assert len(result['documents']) == 5
        # has_more=False כי קיבלנו פחות מ-limit
        assert result['has_more'] is False
        assert result['returned_count'] == 5

    async def test_get_documents_with_redaction(self, service_with_mock_db):
        """בדיקה שהשדות הרגישים מוסתרים."""
        svc = service_with_mock_db

        mock_collection = MagicMock()
        mock_collection.count_documents = AsyncMock(return_value=1)

        mock_cursor = AsyncMock()
        mock_cursor.to_list = AsyncMock(return_value=[
            {'_id': ObjectId(), 'name': 'Alice', 'password': 'secret123'},
        ])
        mock_collection.find.return_value.sort.return_value.skip.return_value.limit.return_value = mock_cursor

        svc._db.__getitem__ = MagicMock(return_value=mock_collection)

        result = await svc.get_documents('users', skip=0, limit=20, redact_sensitive=True)

        assert result['documents'][0]['name'] == 'Alice'
        assert result['documents'][0]['password'] == '[REDACTED]'

    async def test_get_documents_invalid_name(self, service_with_mock_db):
        """בדיקת שגיאה עם שם collection לא תקין."""
        svc = service_with_mock_db

        with pytest.raises(InvalidCollectionNameError):
            await svc.get_documents("$system", skip=0, limit=20)

    async def test_get_documents_limit_capping(self, service_with_mock_db):
        """בדיקה שה-limit מוגבל ל-100."""
        svc = service_with_mock_db

        mock_collection = MagicMock()
        mock_collection.count_documents = AsyncMock(return_value=500)
        mock_cursor = AsyncMock()
        mock_cursor.to_list = AsyncMock(return_value=[])
        mock_collection.find.return_value.sort.return_value.skip.return_value.limit.return_value = mock_cursor
        svc._db.__getitem__ = MagicMock(return_value=mock_collection)

        result = await svc.get_documents('users', skip=0, limit=500)

        # וודא שה-limit הוגבל ל-100
        assert result['limit'] == 100

    async def test_get_documents_empty_collection(self, service_with_mock_db):
        """בדיקה של collection ריק."""
        svc = service_with_mock_db

        mock_collection = MagicMock()
        mock_collection.count_documents = AsyncMock(return_value=0)
        mock_cursor = AsyncMock()
        mock_cursor.to_list = AsyncMock(return_value=[])
        mock_collection.find.return_value.sort.return_value.skip.return_value.limit.return_value = mock_cursor
        svc._db.__getitem__ = MagicMock(return_value=mock_collection)

        result = await svc.get_documents('empty_collection', skip=0, limit=20)

        assert result['total'] == 0
        assert result['documents'] == []
        assert result['has_more'] is False
        assert result['returned_count'] == 0


@pytest.mark.asyncio
class TestDocumentsEndpoint:
    """בדיקות ל-API endpoint."""

    async def test_invalid_skip_returns_400(self, monkeypatch):
        """skip שלילי מחזיר 400."""
        import services.webserver as ws
        from aiohttp import web
        import aiohttp

        monkeypatch.setattr(ws, "DB_HEALTH_TOKEN", "test-db-health-token", raising=True)

        app = ws.create_app()
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, host="127.0.0.1", port=0)
        await site.start()
        try:
            port = list(site._server.sockets)[0].getsockname()[1]
            async with aiohttp.ClientSession() as session:
                resp = await session.get(
                    f"http://127.0.0.1:{port}/api/db/users/documents?skip=-1",
                    headers={"Authorization": "Bearer test-db-health-token"},
                )
                assert resp.status == 400
        finally:
            await runner.cleanup()

    async def test_access_denied_returns_403(self, monkeypatch):
        """גישה ל-collection חסום מחזירה 403."""
        import services.webserver as ws
        from aiohttp import web
        import aiohttp

        monkeypatch.setattr(ws, "DB_HEALTH_TOKEN", "test-db-health-token", raising=True)

        class _Svc:
            async def get_documents(self, *args, **kwargs):
                raise CollectionAccessDeniedError("denied")

        async def _get_service():
            return _Svc()

        monkeypatch.setattr(ws, "get_db_health_service", _get_service, raising=True)

        app = ws.create_app()
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, host="127.0.0.1", port=0)
        await site.start()
        try:
            port = list(site._server.sockets)[0].getsockname()[1]
            async with aiohttp.ClientSession() as session:
                resp = await session.get(
                    f"http://127.0.0.1:{port}/api/db/secrets/documents?skip=0&limit=20",
                    headers={"Authorization": "Bearer test-db-health-token"},
                )
                assert resp.status == 403
                payload = await resp.json()
                assert payload.get("error") == "access_denied"
        finally:
            await runner.cleanup()

