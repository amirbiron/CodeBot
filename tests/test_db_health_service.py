import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.db_health_service import (
    AsyncDatabaseHealthService,
    CollectionStat,
    PoolStatus,
    SlowOperation,
    ThreadPoolDatabaseHealthService,
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

