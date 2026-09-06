import inspect

import pytest
from datetime import datetime
from unittest.mock import MagicMock

from services.query_profiler_service import (
    QueryProfilerService,
    PersistentQueryProfilerService,
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

    def test_record_slow_query(self, profiler_service):
        """בדיקת רישום שאילתה איטית"""
        record = profiler_service.record_slow_query_sync(
            collection="test_collection",
            operation="find",
            query={"user_id": "123"},
            execution_time_ms=250.5,
        )

        assert record.collection == "test_collection"
        assert record.operation == "find"
        assert record.execution_time_ms == 250.5
        assert record.query_id is not None

    def test_get_slow_queries_with_filter(self, profiler_service):
        """בדיקת קבלת שאילתות עם סינון"""
        profiler_service.record_slow_query_sync(
            collection="users",
            operation="find",
            query={"name": "test"},
            execution_time_ms=200,
        )
        profiler_service.record_slow_query_sync(
            collection="snippets",
            operation="find",
            query={"code": "test"},
            execution_time_ms=300,
        )

        queries = profiler_service.get_slow_queries(collection_filter="users")

        assert len(queries) == 1
        assert queries[0].collection == "users"

    def test_get_summary_is_sync_and_stable(self, profiler_service):
        """get_summary סינכרוני ומחזיר את אותו סיכום בקריאות חוזרות.

        בעבר היו שתי מתודות (get_summary + get_summary_async); הן אוחדו לאחת סינכרונית.
        """
        profiler_service.record_slow_query_sync(
            collection="users",
            operation="find",
            query={"name": "test"},
            execution_time_ms=200,
        )
        assert not inspect.iscoroutinefunction(profiler_service.get_summary)
        assert profiler_service.get_summary() == profiler_service.get_summary()

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
        assert normalized["status"]["$in"] == ["<value>", "<value>", "<value>"]

        query_or = {"$or": [{"user_id": "secret_user_123"}, {"email": "secret@email.com"}]}
        normalized_or = profiler_service._normalize_query_shape(query_or)
        assert "$or" in normalized_or
        assert isinstance(normalized_or["$or"], list)
        assert len(normalized_or["$or"]) == 2
        assert normalized_or["$or"][0].get("user_id") == "<value>"
        assert normalized_or["$or"][1].get("email") == "<value>"

        query_nested = {"tags": {"$all": ["tag1", "tag2", "secret_tag"]}}
        normalized_nested = profiler_service._normalize_query_shape(query_nested)
        assert "secret_tag" not in str(normalized_nested)
        assert normalized_nested["tags"]["$all"] == ["<value>", "<value>", "<value>"]

    @pytest.mark.asyncio
    async def test_normalize_query_shape_preserves_operator_array_arity(self, profiler_service):
        """ודא שמערכי ארגומנטים לאופרטורים לא "מתכווצים" (למשל $eq בתוך $expr)."""
        q1 = {"$expr": {"$eq": ["$a", 123]}}
        n1 = profiler_service._normalize_query_shape(q1)
        assert "$expr" in n1 and "$eq" in n1["$expr"]
        assert isinstance(n1["$expr"]["$eq"], list)
        assert len(n1["$expr"]["$eq"]) == 2
        assert "123" not in str(n1)

        # גם אם מגיע "AST" בצורת מערך שמתחיל באופרטור – נשמור מבנה ואורך
        q2 = {"$expr": ["$eq", "$a", 123]}
        n2 = profiler_service._normalize_query_shape(q2)
        assert isinstance(n2["$expr"], list)
        assert len(n2["$expr"]) == 3
        assert n2["$expr"][0] == "$eq"
        assert "123" not in str(n2)

    @pytest.mark.asyncio
    async def test_normalize_query_shape_preserves_sort_direction(self, profiler_service):
        """ודא שערכי 1/-1 ב-$sort נשמרים כפי שהם (קריטי למבנה ה-query)."""
        # $sort פשוט
        q1 = {"$sort": {"created_at": -1, "name": 1}}
        n1 = profiler_service._normalize_query_shape(q1)
        assert n1["$sort"]["created_at"] == -1
        assert n1["$sort"]["name"] == 1

        # $sort מקונן בתוך pipeline
        q2 = {"$match": {"status": "active"}, "$sort": {"score": -1}}
        n2 = profiler_service._normalize_query_shape(q2)
        assert n2["$match"]["status"] == "<value>"
        assert n2["$sort"]["score"] == -1

        # $orderby (אליאס ישן)
        q3 = {"$orderby": {"timestamp": 1}}
        n3 = profiler_service._normalize_query_shape(q3)
        assert n3["$orderby"]["timestamp"] == 1

        # ודא שערכים אחרים (לא 1/-1) עדיין מנורמלים
        q4 = {"$sort": {"field": 1}, "limit": 100}
        n4 = profiler_service._normalize_query_shape(q4)
        assert n4["$sort"]["field"] == 1
        assert n4["limit"] == "<value>"

    @pytest.mark.asyncio
    async def test_is_broken_query_shape_detects_old_format(self, profiler_service):
        """בדיקה שזיהוי query_shapes שבורים עובד נכון."""
        # query_shape תקין - לא שבור
        valid = {"$expr": {"$eq": ["$status", "<value>"]}}
        assert profiler_service._is_broken_query_shape(valid) is False

        # query_shape שבור - מכיל "<N items>"
        broken = {"$expr": {"$eq": ["<2 items>"]}}
        assert profiler_service._is_broken_query_shape(broken) is True

        # מקרה מקונן
        nested_broken = {"$and": [{"$expr": {"$in": ["<3 items>"]}}]}
        assert profiler_service._is_broken_query_shape(nested_broken) is True

        # מקרה עם מספר גדול
        broken_large = {"status": {"$in": ["<100 items>"]}}
        assert profiler_service._is_broken_query_shape(broken_large) is True

    def test_get_explain_plan_rejects_broken_query_shape(self, profiler_service):
        """בדיקה שget_explain_plan דוחה query_shapes שבורים."""
        broken_query = {"$expr": {"$eq": ["<2 items>"]}}
        with pytest.raises(ValueError, match="broken array normalization"):
            profiler_service.get_explain_plan(
                collection="test",
                query=broken_query,
            )

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

        recommendations = profiler_service.analyze_and_recommend(explain_plan)
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

        recommendations = profiler_service.analyze_and_recommend(explain_plan)
        efficiency_rec = next((r for r in recommendations if "יעילות" in r.title), None)
        assert efficiency_rec is not None


    def _indexed_fetch_plan(self, *, docs_returned: int, docs_examined: int) -> ExplainPlan:
        """שאילתה שעברה דרך אינדקס ואז FETCH — המועמדת הקלאסית ל-Covered Query."""
        return ExplainPlan(
            query_id="test789",
            collection="test_collection",
            query_shape={"user_id": "<value>"},
            winning_plan=ExplainStage(stage=QueryStage.FETCH, input_stage=ExplainStage(stage=QueryStage.IXSCAN)),
            stats=QueryStats(
                execution_time_ms=3,
                docs_examined=docs_examined,
                docs_returned=docs_returned,
                keys_examined=docs_examined,
                index_used="user_id_1",
            ),
        )

    def test_no_covered_query_recommendation_when_nothing_was_returned(self, profiler_service):
        """אפס תוצאות אינו "אפשרות ל-Covered Query".

        ההמלצה אומרת "הוסף את שדות ה-projection לאינדקס" — וזה עוזר רק
        למסמכים שמוחזרים. שאילתה שלא החזירה כלום (השלד ``<value>`` של
        כפתור הניתוח, למשל) אינה יכולה להרוויח מזה, וההמלצה עליה שגויה.
        ``_is_covered_query`` דורשת ``n_returned > 0`` כדי להכריז covered,
        ולכן בלי התנאי המקביל כאן כל תוצאה ריקה עם אינדקס נורית.
        """
        recommendations = profiler_service.analyze_and_recommend(
            self._indexed_fetch_plan(docs_returned=0, docs_examined=0)
        )
        covered = [r for r in recommendations if "Covered" in r.title]
        assert covered == [], f"המלצת Covered Query על תוצאה ריקה: {covered!r}"

    def test_covered_query_recommendation_still_fires_when_documents_were_fetched(self, profiler_service):
        """המקרה האמיתי — אינדקס, FETCH, ותוצאות — עדיין מקבל את ההמלצה.

        שומר שהתיקון לא מחק את ההמלצה לגמרי.
        """
        recommendations = profiler_service.analyze_and_recommend(
            self._indexed_fetch_plan(docs_returned=5, docs_examined=5)
        )
        covered = next((r for r in recommendations if "Covered" in r.title), None)
        assert covered is not None, "ההמלצה נעלמה גם כשיש מסמכים שהוחזרו"
        assert covered.severity == SeverityLevel.INFO


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


class TestPersistentQueryProfilerServiceSummary:
    def test_get_summary_uses_cache(self, mock_db_manager, monkeypatch):
        """ודא ש-Persistent get_summary עושה caching כדי לא להעמיס על DB."""
        svc = PersistentQueryProfilerService(db_manager=mock_db_manager, slow_threshold_ms=100)
        calls = {"n": 0}

        monkeypatch.setattr(
            svc,
            "_calculate_summary_sync",
            lambda: {"total_slow_queries": calls.__setitem__("n", calls["n"] + 1) or calls["n"]},
        )

        r1 = svc.get_summary()
        r2 = svc.get_summary()
        assert calls["n"] == 1
        assert r1 == r2

    def test_a_new_record_invalidates_the_cache_even_without_a_db(self, monkeypatch):
        """ביטול ה-cache חייב לכסות גם את המסלול שאין בו DB.

        כשאין DB, ``_persist_record`` יוצאת מוקדם ואין כתיבה — אבל הרשומה כן
        נוספה לזיכרון, והסיכום במסלול הזה נבנה בדיוק מהזיכרון. אם הביטול יושב
        בסוף ``_persist_record``, הוא מדולג, והדשבורד מציג מספר ישן עד 60 שניות.
        """
        manager = MagicMock()
        manager.db = None  # אין DB — מסלול ה-fallback לזיכרון
        svc = PersistentQueryProfilerService(db_manager=manager, slow_threshold_ms=100)

        calls = {"n": 0}

        def _calc():
            calls["n"] += 1
            return {"total_slow_queries": calls["n"]}

        monkeypatch.setattr(svc, "_calculate_summary_sync", _calc)

        assert svc.get_summary()["total_slow_queries"] == 1
        assert svc.get_summary()["total_slow_queries"] == 1, "ה-cache אמור לתפוס"

        svc.record_slow_query_sync(
            collection="code_snippets",
            operation="find",
            query={"user_id": 1},
            execution_time_ms=1500.0,
        )

        assert svc.get_summary()["total_slow_queries"] == 2, (
            "רשומה חדשה בזיכרון לא ביטלה את ה-cache"
        )

    def test_a_failed_db_write_still_invalidates_the_cache(self, monkeypatch):
        """גם כתיבה שנכשלה השאירה רשומה בזיכרון, אז ה-cache חייב להתבטל."""
        manager = MagicMock()
        svc = PersistentQueryProfilerService(db_manager=manager, slow_threshold_ms=100)

        calls = {"n": 0}

        def _calc():
            calls["n"] += 1
            return {"total_slow_queries": calls["n"]}

        monkeypatch.setattr(svc, "_calculate_summary_sync", _calc)
        monkeypatch.setattr(
            svc,
            "_persist_record",
            lambda record: (_ for _ in ()).throw(RuntimeError("mongo down")),
        )

        assert svc.get_summary()["total_slow_queries"] == 1

        with pytest.raises(RuntimeError):
            svc.record_slow_query_sync(
                collection="code_snippets",
                operation="find",
                query={"user_id": 1},
                execution_time_ms=1500.0,
            )

        assert svc.get_summary()["total_slow_queries"] == 2, (
            "כתיבה שנכשלה השאירה רשומה בזיכרון אבל ה-cache נשאר ישן"
        )

