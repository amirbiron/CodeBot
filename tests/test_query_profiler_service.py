import pytest
from datetime import datetime
from unittest.mock import MagicMock

from services.query_profiler_service import (
    QueryProfilerService,
    QueryStage,
    SeverityLevel,
    ExplainPlan,
    ExplainStage,
    QueryStats,
    RateLimiter,
)


@pytest.fixture
def mock_db_manager():
    """יצירת mock ל-DatabaseManager"""
    manager = MagicMock()
    manager.db = MagicMock()
    return manager


@pytest.fixture
def profiler_service(mock_db_manager):
    """יצירת שירות פרופיילר לבדיקות"""
    return QueryProfilerService(db_manager=mock_db_manager, slow_threshold_ms=100)


class TestQueryProfilerService:
    """בדיקות לשירות הפרופיילר"""

    @pytest.mark.asyncio
    async def test_record_slow_query(self, profiler_service):
        """בדיקת רישום שאילתה איטית"""
        record = await profiler_service.record_slow_query(
            collection="test_collection",
            operation="find",
            query={"user_id": "123"},
            execution_time_ms=250.5,
        )

        assert record.collection == "test_collection"
        assert record.operation == "find"
        assert record.execution_time_ms == 250.5
        assert record.query_id is not None

    @pytest.mark.asyncio
    async def test_get_slow_queries_with_filter(self, profiler_service):
        """בדיקת קבלת שאילתות עם סינון"""
        await profiler_service.record_slow_query(
            collection="users",
            operation="find",
            query={"name": "test"},
            execution_time_ms=200,
        )
        await profiler_service.record_slow_query(
            collection="snippets",
            operation="find",
            query={"code": "test"},
            execution_time_ms=300,
        )

        queries = await profiler_service.get_slow_queries(collection_filter="users")

        assert len(queries) == 1
        assert queries[0].collection == "users"

    @pytest.mark.asyncio
    async def test_normalize_query_shape(self, profiler_service):
        """בדיקת נרמול צורת שאילתה"""
        query = {"user_id": "abc123", "status": True, "count": 42}
        normalized = profiler_service._normalize_query_shape(query)

        assert normalized["user_id"] == "<value>"
        assert normalized["status"] == "<value>"
        assert normalized["count"] == "<value>"

    @pytest.mark.asyncio
    async def test_normalize_query_shape_with_arrays(self, profiler_service):
        """בדיקת נרמול שאילתה עם מערכים - חשוב לאבטחה!"""
        query_in = {"status": {"$in": ["active", "pending", "draft"]}}
        normalized = profiler_service._normalize_query_shape(query_in)
        assert normalized["status"]["$in"] == ["<3 items>"]

        query_or = {"$or": [{"user_id": "secret_user_123"}, {"email": "secret@email.com"}]}
        normalized_or = profiler_service._normalize_query_shape(query_or)
        assert "$or" in normalized_or
        assert normalized_or["$or"][0].get("user_id") == "<value>" or "<" in str(normalized_or["$or"])

        query_nested = {"tags": {"$all": ["tag1", "tag2", "secret_tag"]}}
        normalized_nested = profiler_service._normalize_query_shape(query_nested)
        assert "secret_tag" not in str(normalized_nested)

    @pytest.mark.asyncio
    async def test_normalize_prevents_pii_leak(self, profiler_service):
        """בדיקה שנרמול מונע דליפת PII"""
        sensitive_query = {
            "email": "john.doe@company.com",
            "phone": "+1-555-123-4567",
            "ssn": "123-45-6789",
            "credit_card": {"$in": ["4111111111111111", "5500000000000004"]},
            "$or": [{"password_hash": "abc123hash"}, {"api_key": "sk_live_secret_key"}],
        }

        normalized = profiler_service._normalize_query_shape(sensitive_query)
        normalized_str = str(normalized)

        assert "john.doe" not in normalized_str
        assert "555-123" not in normalized_str
        assert "123-45-6789" not in normalized_str
        assert "4111111111111111" not in normalized_str
        assert "abc123hash" not in normalized_str
        assert "sk_live" not in normalized_str

    @pytest.mark.asyncio
    async def test_generate_query_id_consistency(self, profiler_service):
        """בדיקת עקביות יצירת מזהה שאילתה"""
        query1 = {"a": 1, "b": 2}
        query2 = {"b": 2, "a": 1}

        id1 = profiler_service._generate_query_id("test", query1)
        id2 = profiler_service._generate_query_id("test", query2)

        assert id1 == id2

    def test_has_collscan_detection(self, profiler_service):
        """בדיקת זיהוי COLLSCAN"""
        collscan_stage = ExplainStage(stage=QueryStage.COLLSCAN)
        assert profiler_service._has_collscan(collscan_stage) is True

        ixscan_stage = ExplainStage(stage=QueryStage.IXSCAN)
        assert profiler_service._has_collscan(ixscan_stage) is False

        nested_stage = ExplainStage(stage=QueryStage.FETCH, input_stage=ExplainStage(stage=QueryStage.COLLSCAN))
        assert profiler_service._has_collscan(nested_stage) is True


class TestOptimizationRecommendations:
    """בדיקות להמלצות אופטימיזציה"""

    @pytest.mark.asyncio
    async def test_collscan_recommendation(self, profiler_service):
        """בדיקת המלצה ל-COLLSCAN"""
        explain_plan = ExplainPlan(
            query_id="test123",
            collection="test_collection",
            query_shape={"field1": "<value>"},
            winning_plan=ExplainStage(stage=QueryStage.COLLSCAN),
            stats=QueryStats(
                execution_time_ms=500,
                docs_examined=10000,
                docs_returned=10,
                keys_examined=0,
            ),
        )

        recommendations = await profiler_service.analyze_and_recommend(explain_plan)
        collscan_rec = next((r for r in recommendations if "COLLSCAN" in r.title), None)
        assert collscan_rec is not None
        assert collscan_rec.severity == SeverityLevel.CRITICAL

    @pytest.mark.asyncio
    async def test_efficiency_recommendation(self, profiler_service):
        """בדיקת המלצה ליחס יעילות נמוך"""
        explain_plan = ExplainPlan(
            query_id="test456",
            collection="test_collection",
            query_shape={"field1": "<value>"},
            winning_plan=ExplainStage(stage=QueryStage.FETCH, input_stage=ExplainStage(stage=QueryStage.IXSCAN)),
            stats=QueryStats(
                execution_time_ms=200,
                docs_examined=10000,
                docs_returned=5,
                keys_examined=10000,
            ),
        )

        recommendations = await profiler_service.analyze_and_recommend(explain_plan)
        efficiency_rec = next((r for r in recommendations if "יעילות" in r.title), None)
        assert efficiency_rec is not None


class TestExplainPlanParsing:
    """בדיקות לפרסור Explain Plans"""

    def test_parse_simple_stage(self, profiler_service):
        stage_data = {"stage": "IXSCAN", "indexName": "user_id_1", "direction": "forward"}
        stage = profiler_service._parse_stage(stage_data)

        assert stage.stage == QueryStage.IXSCAN
        assert stage.index_name == "user_id_1"
        assert stage.direction == "forward"

    def test_parse_nested_stages(self, profiler_service):
        stage_data = {"stage": "FETCH", "inputStage": {"stage": "IXSCAN", "indexName": "idx_test"}}
        stage = profiler_service._parse_stage(stage_data)

        assert stage.stage == QueryStage.FETCH
        assert stage.input_stage is not None
        assert stage.input_stage.stage == QueryStage.IXSCAN


class TestRateLimiting:
    """בדיקות להגבלת קצב"""

    def test_rate_limiter_allows_within_limit(self):
        limiter = RateLimiter(requests_per_minute=5)
        for _ in range(5):
            assert limiter.is_allowed("client1") is True
        assert limiter.is_allowed("client1") is False

    def test_rate_limiter_different_clients(self):
        limiter = RateLimiter(requests_per_minute=2)
        assert limiter.is_allowed("client1") is True
        assert limiter.is_allowed("client1") is True
        assert limiter.is_allowed("client1") is False

        assert limiter.is_allowed("client2") is True

