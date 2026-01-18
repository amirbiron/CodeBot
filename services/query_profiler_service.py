from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import weakref
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Deque, Dict, List, Optional

try:
    # Structured logging events (fail-open)
    from observability import emit_event  # type: ignore
except Exception:  # pragma: no cover
    def emit_event(_event: str, severity: str = "info", **_fields: Any) -> None:  # type: ignore
        return None

logger = logging.getLogger(__name__)


class QueryStage(Enum):
    """שלבי ביצוע שאילתה ב-MongoDB"""

    COLLSCAN = "COLLSCAN"  # סריקת collection מלאה
    IXSCAN = "IXSCAN"  # סריקת אינדקס
    FETCH = "FETCH"  # שליפת מסמכים
    SORT = "SORT"  # מיון
    PROJECTION = "PROJECTION"  # projection
    LIMIT = "LIMIT"  # הגבלת תוצאות
    SKIP = "SKIP"  # דילוג על תוצאות
    SHARD_MERGE = "SHARD_MERGE"  # מיזוג shards


class SeverityLevel(Enum):
    """רמת חומרה של בעיית ביצועים"""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class QueryStats:
    """סטטיסטיקות ביצוע של שאילתה"""

    execution_time_ms: float
    docs_examined: int
    docs_returned: int
    keys_examined: int
    index_used: Optional[str] = None
    is_covered_query: bool = False
    memory_usage_bytes: int = 0

    @property
    def efficiency_ratio(self) -> float:
        """יחס יעילות - docs_returned / docs_examined"""
        if self.docs_examined == 0:
            return 1.0
        return self.docs_returned / self.docs_examined


@dataclass
class ExplainStage:
    """שלב בודד ב-explain plan"""

    stage: QueryStage
    input_stage: Optional["ExplainStage"] = None
    docs_examined: int = 0
    keys_examined: int = 0
    execution_time_ms: float = 0
    index_name: Optional[str] = None
    direction: str = "forward"
    filter_condition: Optional[Dict[str, Any]] = None
    children: List["ExplainStage"] = field(default_factory=list)


@dataclass
class ExplainPlan:
    """תוכנית ביצוע מלאה של שאילתה"""

    query_id: str
    collection: str
    query_shape: Dict[str, Any]
    winning_plan: ExplainStage
    rejected_plans: List[ExplainStage] = field(default_factory=list)
    stats: Optional[QueryStats] = None
    server_info: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class OptimizationRecommendation:
    """המלצת אופטימיזציה בודדת"""

    id: str
    title: str
    description: str
    severity: SeverityLevel
    category: str  # "index", "query", "schema", "connection"
    suggested_action: str
    estimated_improvement: str
    code_example: Optional[str] = None
    documentation_link: Optional[str] = None


@dataclass
class SlowQueryRecord:
    """רשומת שאילתה איטית"""

    query_id: str
    collection: str
    operation: str  # "find", "aggregate", "update", etc.
    query_shape: Dict[str, Any]
    execution_time_ms: float
    timestamp: datetime
    client_info: Optional[Dict[str, Any]] = None
    explain_plan: Optional[ExplainPlan] = None
    recommendations: List[OptimizationRecommendation] = field(default_factory=list)


class AggregationStage(Enum):
    """שלבי אגרגציה נפוצים"""

    COLLSCAN = "COLLSCAN"
    IXSCAN = "IXSCAN"
    FETCH = "FETCH"
    SORT = "SORT"
    MATCH = "$match"
    GROUP = "$group"
    LOOKUP = "$lookup"
    UNWIND = "$unwind"
    PROJECT = "$project"
    LIMIT = "$limit"
    SKIP = "$skip"
    SORT_KEY_GENERATOR = "SORT_KEY_GENERATOR"


@dataclass
class AggregationExplainStage:
    """שלב באגרגציה עם מידע מפורט"""

    stage_name: str
    execution_time_ms: float = 0
    docs_examined: int = 0
    n_returned: int = 0

    # מידע ספציפי לשלב
    uses_disk: bool = False  # האם השלב משתמש בדיסק (למשל $sort גדול)
    memory_usage_bytes: int = 0
    index_used: Optional[str] = None

    # עבור $lookup
    lookup_collection: Optional[str] = None
    lookup_strategy: Optional[str] = None  # "nestedLoopJoin" vs "indexedLoopJoin"


@dataclass
class AggregationExplainPlan:
    """תוכנית ביצוע מלאה לאגרגציה"""

    query_id: str
    collection: str
    pipeline_shape: List[Dict[str, Any]]
    stages: List[AggregationExplainStage]
    total_execution_time_ms: float
    server_info: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.utcnow)


class RateLimiter:
    """הגבלת קצב בקשות לפרופיילר"""

    def __init__(self, requests_per_minute: int = 60):
        self.requests_per_minute = max(1, int(requests_per_minute))
        self._request_counts: Dict[str, List[datetime]] = defaultdict(list)

    def is_allowed(self, client_id: str) -> bool:
        now = datetime.utcnow()
        minute_ago = now - timedelta(minutes=1)

        # ניקוי בקשות ישנות
        self._request_counts[client_id] = [t for t in self._request_counts[client_id] if t > minute_ago]

        # בדיקת מגבלה
        if len(self._request_counts[client_id]) >= self.requests_per_minute:
            return False

        self._request_counts[client_id].append(now)
        return True


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        return int(float(raw))
    except Exception:
        return default


class QueryProfilerService:
    """
    שירות לניתוח ביצועי שאילתות MongoDB.

    מספק:
    - איסוף שאילתות איטיות בזמן אמת
    - יצירת explain plans
    - ניתוח והמלצות אופטימיזציה
    """

    # סף ברירת מחדל לשאילתה איטית (במילישניות)
    DEFAULT_SLOW_THRESHOLD_MS = 1000

    # מספר מקסימלי של שאילתות איטיות לשמור בזיכרון
    MAX_SLOW_QUERIES_BUFFER = 1000

    def __init__(self, db_manager: Any, slow_threshold_ms: int = DEFAULT_SLOW_THRESHOLD_MS):
        self.db_manager = db_manager
        self.slow_threshold_ms = int(slow_threshold_ms)

        max_buffer = _env_int("PROFILER_MAX_BUFFER_SIZE", self.MAX_SLOW_QUERIES_BUFFER)
        self._slow_queries: Deque[SlowQueryRecord] = deque(maxlen=max(1, int(max_buffer)))
        self._query_patterns: Dict[str, int] = {}

        # Metrics (best-effort)
        self._metrics_enabled = _env_bool("PROFILER_METRICS_ENABLED", True)
        if self._metrics_enabled:
            try:
                from monitoring.profiler_metrics import (  # type: ignore
                    ACTIVE_PROFILER_BUFFER_SIZE,
                    COLLSCAN_DETECTED,
                    QUERY_DURATION,
                    SLOW_QUERIES_TOTAL,
                )
            except Exception:  # pragma: no cover
                SLOW_QUERIES_TOTAL = None  # type: ignore
                QUERY_DURATION = None  # type: ignore
                ACTIVE_PROFILER_BUFFER_SIZE = None  # type: ignore
                COLLSCAN_DETECTED = None  # type: ignore
            self._SLOW_QUERIES_TOTAL = SLOW_QUERIES_TOTAL
            self._QUERY_DURATION = QUERY_DURATION
            self._ACTIVE_PROFILER_BUFFER_SIZE = ACTIVE_PROFILER_BUFFER_SIZE
            self._COLLSCAN_DETECTED = COLLSCAN_DETECTED
        else:
            self._SLOW_QUERIES_TOTAL = None
            self._QUERY_DURATION = None
            self._ACTIVE_PROFILER_BUFFER_SIZE = None
            self._COLLSCAN_DETECTED = None

    def _generate_query_id(self, collection: str, query_shape: Dict[str, Any]) -> str:
        """יצירת מזהה ייחודי לשאילתה"""
        content = f"{collection}:{json.dumps(query_shape, sort_keys=True)}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    def _is_broken_query_shape(self, query: Any) -> bool:
        """
        בדיקה אם query_shape מכיל נרמול שבור מגרסה ישנה.

        גרסאות ישנות היו מקצרות מערכים ל-["<N items>"] במקום לשמור על אורך המערך.
        זה שובר את explain() כי אופרטורים כמו $eq מצפים למספר ארגומנטים מדויק.
        """
        if isinstance(query, dict):
            for v in query.values():
                if self._is_broken_query_shape(v):
                    return True
        elif isinstance(query, list):
            for item in query:
                # זיהוי פלייסהולדר שבור: "<N items>" (N הוא מספר)
                if isinstance(item, str) and item.startswith("<") and item.endswith(" items>"):
                    return True
                if self._is_broken_query_shape(item):
                    return True
        return False

    def _normalize_query_shape(self, query: Dict[str, Any]) -> Dict[str, Any]:
        """
        נרמול צורת השאילתה - החלפת ערכים בפלייסהולדרים.
        מאפשר זיהוי דפוסי שאילתות דומים.

        🔒 אבטחה: פונקציה זו מונעת דליפת מידע אישי (PII) לדשבורד/לוגים
        על ידי החלפת כל הערכים בפלייסהולדרים.

        חשוב: מטפלת גם במערכים מקוננים (למשל $in, $or)!

        ⚠️ מקרים מיוחדים:
        - $sort: ערכי 1/-1 נשמרים כפי שהם (חיוניים למבנה ה-query)
        - מערכים באופרטורים: אורך נשמר, איברים מנורמלים רקורסיבית
        """

        # מפתחות שבהם לא מנרמלים ערכים מספריים (1/-1) – קריטיים לתחביר MongoDB
        SORT_LIKE_KEYS = {"$sort", "$orderby"}

        def normalize_value(value: Any, parent_key: Optional[str] = None) -> Any:
            """
            נרמול ערך לשם "query shape" ללא דליפת PII.

            ⚠️ חשוב: לא משנים מבנה/אורך של מערכים, כדי לא לשבור ביטויי $expr
            ואופרטורים שמצפים למספר ארגומנטים מדויק (למשל $eq).

            Args:
                value: הערך לנרמול
                parent_key: המפתח ההורה (לזיהוי הקשרים כמו $sort)
            """
            if isinstance(value, dict):
                result: Dict[str, Any] = {}
                for k, v in value.items():
                    str_k = str(k)
                    # אם זה $sort – נעביר את ה-key כהקשר לילדים
                    if str_k in SORT_LIKE_KEYS:
                        result[str_k] = normalize_value(v, parent_key=str_k)
                    else:
                        result[str_k] = normalize_value(v, parent_key=parent_key)
                return result

            if isinstance(value, list):
                if not value:
                    return []

                # אם כל האיברים פרימיטיביים – אפשר לנרמל מהר בלי רקורסיה עמוקה,
                # תוך שמירה על אורך המערך.
                if all(isinstance(v, (str, int, float, bool, type(None))) for v in value):
                    out: List[Any] = []
                    for v in value:
                        if v is None:
                            out.append("<null>")
                        elif isinstance(v, str) and v.startswith("$"):
                            # השארת field-paths / operator tokens (למשל "$user_id", "$eq") כפי שהם
                            out.append(v)
                        elif parent_key in SORT_LIKE_KEYS and isinstance(v, (int, float)) and v in (1, -1, 1.0, -1.0):
                            # ב-$sort: שומרים על 1/-1
                            out.append(int(v))
                        else:
                            out.append("<value>")
                    return out

                # מערך מורכב (dicts / lists): נרמול רקורסיבי *לכל* האיברים (שומר אורך)
                return [normalize_value(v, parent_key=parent_key) for v in value]

            if value is None:
                return "<null>"

            # שמירת מחרוזות שמתחילות ב-$ (field paths / operator markers) – זה לא PII
            if isinstance(value, str):
                return value if value.startswith("$") else "<value>"

            # ב-$sort: שומרים על 1/-1 (כיוון מיון)
            if parent_key in SORT_LIKE_KEYS and isinstance(value, (int, float)) and value in (1, -1, 1.0, -1.0):
                return int(value)

            if isinstance(value, (int, float, bool, datetime, bytes)):
                return "<value>"

            # ObjectId, Decimal128, UUID וכו' — best-effort
            return "<value>"

        # נקודת כניסה: כל מפתח ברמה העליונה מנורמל עם ה-key שלו כהקשר
        result: Dict[str, Any] = {}
        for k, v in (query or {}).items():
            str_k = str(k)
            if str_k in SORT_LIKE_KEYS:
                result[str_k] = normalize_value(v, parent_key=str_k)
            else:
                result[str_k] = normalize_value(v, parent_key=None)
        return result

    def record_slow_query_sync(
        self,
        collection: str,
        operation: str,
        query: Dict[str, Any],
        execution_time_ms: float,
        client_info: Optional[Dict[str, Any]] = None,
    ) -> SlowQueryRecord:
        """רישום שאילתה איטית (סינכרוני) - נוח לשימוש מאזין PyMongo."""
        query_shape = self._normalize_query_shape(query or {})
        query_id = self._generate_query_id(collection, query_shape)

        record = SlowQueryRecord(
            query_id=query_id,
            collection=collection,
            operation=operation,
            query_shape=query_shape,
            execution_time_ms=float(execution_time_ms),
            timestamp=datetime.utcnow(),
            client_info=client_info,
        )

        self._slow_queries.append(record)

        # עדכון מונה דפוסי שאילתות
        pattern_key = f"{collection}:{operation}:{json.dumps(query_shape, sort_keys=True)}"
        self._query_patterns[pattern_key] = self._query_patterns.get(pattern_key, 0) + 1

        # Metrics (best-effort)
        try:
            if self._SLOW_QUERIES_TOTAL is not None:
                self._SLOW_QUERIES_TOTAL.labels(collection=record.collection, operation=record.operation).inc()
            if self._QUERY_DURATION is not None:
                self._QUERY_DURATION.labels(collection=record.collection, operation=record.operation).observe(
                    float(record.execution_time_ms) / 1000.0
                )
            if self._ACTIVE_PROFILER_BUFFER_SIZE is not None:
                self._ACTIVE_PROFILER_BUFFER_SIZE.set(len(self._slow_queries))
        except Exception:
            pass

        # Observability event (best-effort) – לא שולח את השאילתה הגולמית אלא query_shape בלבד
        try:
            emit_event(
                "slow_query_detected",
                severity="warning",
                query_id=record.query_id,
                collection=record.collection,
                operation=record.operation,
                execution_time_ms=record.execution_time_ms,
                query_shape=record.query_shape,
            )
        except Exception:
            pass

        # NOTE: We intentionally avoid a second free-form log line here.
        # The structured JSON event above (emit_event) is the source of truth
        # and prevents duplicate log lines in container logs.

        return record

    async def record_slow_query(
        self,
        collection: str,
        operation: str,
        query: Dict[str, Any],
        execution_time_ms: float,
        client_info: Optional[Dict[str, Any]] = None,
    ) -> SlowQueryRecord:
        """
        רישום שאילתה איטית.
        נקרא אוטומטית על ידי ה-CommandListener.
        """
        return self.record_slow_query_sync(collection, operation, query, execution_time_ms, client_info)

    async def get_slow_queries(
        self,
        limit: int = 50,
        collection_filter: Optional[str] = None,
        min_execution_time_ms: Optional[float] = None,
        since: Optional[datetime] = None,
    ) -> List[SlowQueryRecord]:
        """קבלת רשימת שאילתות איטיות עם אפשרויות סינון."""
        queries = list(self._slow_queries)

        # סינון לפי collection
        if collection_filter:
            queries = [q for q in queries if q.collection == collection_filter]

        # סינון לפי זמן ביצוע מינימלי
        if min_execution_time_ms is not None:
            queries = [q for q in queries if q.execution_time_ms >= float(min_execution_time_ms)]

        # סינון לפי זמן
        if since:
            queries = [q for q in queries if q.timestamp >= since]

        # מיון לפי זמן ביצוע (הכי איטיות קודם)
        queries.sort(key=lambda q: q.execution_time_ms, reverse=True)

        return queries[: max(1, int(limit))]

    async def get_explain_plan(
        self,
        collection: str,
        query: Dict[str, Any],
        verbosity: str = "queryPlanner",  # ⚠️ ברירת מחדל בטוחה - לא מריצה את השאילתה!
    ) -> ExplainPlan:
        """
        קבלת explain plan מפורט לשאילתה.

        ⚠️ אזהרה: executionStats ו-allPlansExecution מריצים את השאילתה בפועל!
        """
        # בדיקה אם ה-query הוא query_shape שבור מגרסה ישנה
        if self._is_broken_query_shape(query):
            raise ValueError(
                "Query shape contains broken array normalization from old version. "
                "Arrays like '<N items>' cannot be used with explain(). "
                "Please use the original query or re-record this slow query."
            )

        def _run_explain() -> Dict[str, Any]:
            db = getattr(self.db_manager, "db", None)
            if db is None:
                raise RuntimeError("No MongoDB database available")
            coll = db[collection]

            cursor = coll.find(query)
            try:
                # נסיון להריץ עם רמת הפירוט המבוקשת
                return cursor.explain(verbosity)
            except TypeError:
                # Fallback לגרסאות ישנות של pymongo שלא מקבלות ארגומנטים
                logger.warning(
                    "Profiler: PyMongo Cursor.explain() does not support verbosity=%r; "
                    "falling back to default explain() without execution stats.",
                    verbosity,
                    exc_info=True,
                )
                return cursor.explain()

        explain_result = await asyncio.to_thread(_run_explain)
        return self._parse_explain_result(collection, query, explain_result)

    def _parse_explain_result(self, collection: str, query: Dict[str, Any], explain_result: Dict[str, Any]) -> ExplainPlan:
        """פרסור תוצאת explain ליצירת ExplainPlan"""
        query_planner = explain_result.get("queryPlanner", {}) if isinstance(explain_result, dict) else {}
        execution_stats = explain_result.get("executionStats", {}) if isinstance(explain_result, dict) else {}

        winning_plan_raw = query_planner.get("winningPlan", {}) if isinstance(query_planner, dict) else {}
        winning_plan = self._parse_stage(winning_plan_raw if isinstance(winning_plan_raw, dict) else {})

        rejected_plans: List[ExplainStage] = []
        for plan in (query_planner.get("rejectedPlans", []) if isinstance(query_planner, dict) else []) or []:
            if isinstance(plan, dict):
                rejected_plans.append(self._parse_stage(plan))

        stats = None
        if execution_stats and isinstance(execution_stats, dict):
            stats = QueryStats(
                execution_time_ms=float(execution_stats.get("executionTimeMillis", 0) or 0),
                docs_examined=int(execution_stats.get("totalDocsExamined", 0) or 0),
                docs_returned=int(execution_stats.get("nReturned", 0) or 0),
                keys_examined=int(execution_stats.get("totalKeysExamined", 0) or 0),
                index_used=self._extract_index_name(winning_plan_raw if isinstance(winning_plan_raw, dict) else {}),
                is_covered_query=self._is_covered_query(execution_stats),
            )

        query_shape = self._normalize_query_shape(query)
        query_id = self._generate_query_id(collection, query_shape)

        return ExplainPlan(
            query_id=query_id,
            collection=collection,
            query_shape=query_shape,
            winning_plan=winning_plan,
            rejected_plans=rejected_plans,
            stats=stats,
            server_info=explain_result.get("serverInfo", {}) if isinstance(explain_result, dict) else {},
        )

    def _parse_stage(self, stage_data: Dict[str, Any]) -> ExplainStage:
        """פרסור שלב בודד ב-explain plan"""
        stage_name = str(stage_data.get("stage", "UNKNOWN") or "UNKNOWN")
        try:
            stage_type = QueryStage(stage_name)
        except ValueError:
            stage_type = QueryStage.FETCH

        input_stage = None
        if "inputStage" in stage_data and isinstance(stage_data.get("inputStage"), dict):
            input_stage = self._parse_stage(stage_data["inputStage"])

        children: List[ExplainStage] = []
        if "inputStages" in stage_data and isinstance(stage_data.get("inputStages"), list):
            for child_stage in stage_data["inputStages"]:
                if isinstance(child_stage, dict):
                    children.append(self._parse_stage(child_stage))

        return ExplainStage(
            stage=stage_type,
            input_stage=input_stage,
            index_name=stage_data.get("indexName"),
            direction=str(stage_data.get("direction", "forward") or "forward"),
            filter_condition=stage_data.get("filter") if isinstance(stage_data.get("filter"), dict) else None,
            children=children,
        )

    def _extract_index_name(self, plan: Dict[str, Any]) -> Optional[str]:
        """חילוץ שם האינדקס מתוכנית הביצוע"""
        if "indexName" in plan:
            try:
                return str(plan["indexName"])
            except Exception:
                return None
        if "inputStage" in plan and isinstance(plan.get("inputStage"), dict):
            return self._extract_index_name(plan["inputStage"])
        return None

    def _is_covered_query(self, execution_stats: Dict[str, Any]) -> bool:
        """בדיקה האם השאילתה היא covered query"""
        docs_examined = int(execution_stats.get("totalDocsExamined", 0) or 0)
        keys_examined = int(execution_stats.get("totalKeysExamined", 0) or 0)
        n_returned = int(execution_stats.get("nReturned", 0) or 0)
        return docs_examined == 0 and keys_examined >= n_returned and n_returned > 0

    async def analyze_and_recommend(self, explain_plan: ExplainPlan) -> List[OptimizationRecommendation]:
        """ניתוח explain plan ויצירת המלצות אופטימיזציה."""
        recommendations: List[OptimizationRecommendation] = []

        if self._has_collscan(explain_plan.winning_plan):
            try:
                if self._COLLSCAN_DETECTED is not None:
                    self._COLLSCAN_DETECTED.labels(collection=explain_plan.collection).inc()
            except Exception:
                pass
            recommendations.append(self._create_collscan_recommendation(explain_plan))

        if explain_plan.stats and explain_plan.stats.efficiency_ratio < 0.1:
            recommendations.append(self._create_efficiency_recommendation(explain_plan))

        if self._has_in_memory_sort(explain_plan.winning_plan):
            recommendations.append(self._create_sort_recommendation(explain_plan))

        if explain_plan.stats and not explain_plan.stats.is_covered_query:
            if self._could_be_covered_query(explain_plan):
                recommendations.append(self._create_covered_query_recommendation(explain_plan))

        pattern_count = self._get_pattern_frequency(explain_plan)
        if pattern_count > 10:
            recommendations.append(self._create_frequent_query_recommendation(explain_plan, pattern_count))

        return recommendations

    async def generate_recommendations(self, explain_plan: ExplainPlan) -> List[OptimizationRecommendation]:
        """
        אלגוריתם יצירת המלצות:

        1. ניתוח שלבי הביצוע (stages)
        2. בדיקת יחסי יעילות
        3. זיהוי דפוסים בעייתיים
        4. יצירת המלצות עם עדיפויות
        """
        recommendations = await self.analyze_and_recommend(explain_plan)
        severity_order = {SeverityLevel.CRITICAL: 0, SeverityLevel.WARNING: 1, SeverityLevel.INFO: 2}
        return sorted(recommendations, key=lambda r: severity_order.get(r.severity, 999))

    def _has_collscan(self, stage: ExplainStage) -> bool:
        """בדיקה האם יש COLLSCAN בתוכנית"""
        if stage.stage == QueryStage.COLLSCAN:
            return True
        if stage.input_stage and self._has_collscan(stage.input_stage):
            return True
        for child in stage.children:
            if self._has_collscan(child):
                return True
        return False

    def _has_in_memory_sort(self, stage: ExplainStage) -> bool:
        """בדיקה האם יש מיון בזיכרון"""
        if stage.stage == QueryStage.SORT:
            return True
        if stage.input_stage:
            return self._has_in_memory_sort(stage.input_stage)
        return False

    def _could_be_covered_query(self, explain_plan: ExplainPlan) -> bool:
        """בדיקה האם השאילתה יכולה להיות covered query"""
        return explain_plan.stats is not None and explain_plan.stats.index_used is not None

    def _get_pattern_frequency(self, explain_plan: ExplainPlan) -> int:
        """קבלת תדירות דפוס השאילתה"""
        pattern_key = f"{explain_plan.collection}:find:{json.dumps(explain_plan.query_shape, sort_keys=True)}"
        return int(self._query_patterns.get(pattern_key, 0))

    def _create_collscan_recommendation(self, explain_plan: ExplainPlan) -> OptimizationRecommendation:
        """יצירת המלצה לטיפול ב-COLLSCAN"""
        fields = list((explain_plan.query_shape or {}).keys())
        index_suggestion = ", ".join(f'"{f}": 1' for f in fields[:3])
        return OptimizationRecommendation(
            id=f"collscan_{explain_plan.query_id}",
            title="🔴 COLLSCAN זוהה - נדרש אינדקס",
            description=(
                f"השאילתה על collection '{explain_plan.collection}' מבצעת סריקה מלאה. "
                f"זה עלול להיות איטי מאוד על collections גדולים."
            ),
            severity=SeverityLevel.CRITICAL,
            category="index",
            suggested_action="צור אינדקס מתאים לשאילתה",
            estimated_improvement="יכול לשפר פי 10-100 בהתאם לגודל ה-collection",
            code_example=f"""db.{explain_plan.collection}.createIndex({{ {index_suggestion} }})""",
            documentation_link="https://www.mongodb.com/docs/manual/indexes/",
        )

    def _create_efficiency_recommendation(self, explain_plan: ExplainPlan) -> OptimizationRecommendation:
        """יצירת המלצה ליחס יעילות נמוך"""
        stats = explain_plan.stats
        assert stats is not None
        return OptimizationRecommendation(
            id=f"efficiency_{explain_plan.query_id}",
            title="🟡 יחס יעילות נמוך",
            description=(
                f"השאילתה סורקת {stats.docs_examined:,} מסמכים אך מחזירה רק {stats.docs_returned:,}. "
                f"יחס יעילות: {stats.efficiency_ratio:.1%}"
            ),
            severity=SeverityLevel.WARNING,
            category="query",
            suggested_action="בדוק את האינדקסים הקיימים או צמצם את הנתונים המוחזרים",
            estimated_improvement=f"צמצום סריקה מ-{stats.docs_examined:,} ל-~{stats.docs_returned:,} מסמכים",
        )

    def _create_sort_recommendation(self, explain_plan: ExplainPlan) -> OptimizationRecommendation:
        """יצירת המלצה למיון בזיכרון"""
        return OptimizationRecommendation(
            id=f"sort_{explain_plan.query_id}",
            title="🟠 מיון בזיכרון",
            description=(
                "השאילתה מבצעת מיון בזיכרון במקום להשתמש באינדקס. "
                "זה עלול להיות איטי ולצרוך זיכרון רב."
            ),
            severity=SeverityLevel.WARNING,
            category="index",
            suggested_action="צור אינדקס שכולל את שדה המיון",
            estimated_improvement="חיסכון בזיכרון ושיפור מהירות",
        )

    def _create_covered_query_recommendation(self, explain_plan: ExplainPlan) -> OptimizationRecommendation:
        """יצירת המלצה ל-covered query"""
        return OptimizationRecommendation(
            id=f"covered_{explain_plan.query_id}",
            title="🟢 אפשרות ל-Covered Query",
            description=(
                "השאילתה משתמשת באינדקס אבל עדיין ניגשת למסמכים. "
                "ניתן לשפר על ידי הוספת שדות ה-projection לאינדקס."
            ),
            severity=SeverityLevel.INFO,
            category="index",
            suggested_action="הוסף את שדות ה-projection לאינדקס או הגבל את השדות המוחזרים",
            estimated_improvement="עד 50% שיפור בגישה לנתונים",
        )

    def _create_frequent_query_recommendation(self, explain_plan: ExplainPlan, count: int) -> OptimizationRecommendation:
        """יצירת המלצה לשאילתות תכופות"""
        return OptimizationRecommendation(
            id=f"frequent_{explain_plan.query_id}",
            title="📊 דפוס שאילתה תכופה",
            description=f"שאילתה זו הופיעה {count} פעמים. שקול אופטימיזציה או caching.",
            severity=SeverityLevel.INFO,
            category="query",
            suggested_action="שקול caching ברמת האפליקציה או אופטימיזציה נוספת",
            estimated_improvement="הפחתת עומס על בסיס הנתונים",
        )

    async def get_collection_stats(self, collection: str) -> Dict[str, Any]:
        """קבלת סטטיסטיקות collection לצורך המלצות"""

        def _get_stats() -> Dict[str, Any]:
            db = getattr(self.db_manager, "db", None)
            if db is None:
                raise RuntimeError("No MongoDB database available")
            stats = db.command("collStats", collection)
            indexes = list(db[collection].list_indexes())
            return {
                "size_bytes": stats.get("size", 0),
                "count": stats.get("count", 0),
                "avg_obj_size": stats.get("avgObjSize", 0),
                "index_count": len(indexes),
                "indexes": [idx.get("name") for idx in indexes if isinstance(idx, dict) and idx.get("name")],
                "total_index_size": stats.get("totalIndexSize", 0),
            }

        return await asyncio.to_thread(_get_stats)

    def get_summary(self) -> Dict[str, Any]:
        """קבלת סיכום מצב הפרופיילר"""
        queries = list(self._slow_queries)
        if not queries:
            return {
                "total_slow_queries": 0,
                "collections_affected": [],
                "avg_execution_time_ms": 0,
                "max_execution_time_ms": 0,
                "unique_patterns": 0,
            }

        collections = set(q.collection for q in queries)
        avg_time = sum(q.execution_time_ms for q in queries) / len(queries)
        max_time = max(q.execution_time_ms for q in queries)

        return {
            "total_slow_queries": len(queries),
            "collections_affected": list(collections),
            "avg_execution_time_ms": round(avg_time, 2),
            "max_execution_time_ms": round(max_time, 2),
            "unique_patterns": len(self._query_patterns),
            "threshold_ms": self.slow_threshold_ms,
        }

    async def get_summary_async(self) -> Dict[str, Any]:
        """
        גרסה אסינכרונית לסיכום.

        בבסיס (in-memory) אין I/O, אז אין צורך ב-to_thread.
        מחלקות יורשות (למשל Persistent*) יכולות לדרוס כדי להימנע מחסימה על I/O סינכרוני.
        """
        return self.get_summary()

    # --- Aggregations ---
    def _fix_pipeline_for_explain(self, pipeline: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        תיקון ערכי placeholder ב-pipeline לפני שליחה ל-explain.

        כאשר ה-pipeline עבר נרמול (להגנת PII), ערכים מספריים הוחלפו ב-"<value>".
        MongoDB explain ייכשל אם יקבל "$limit": "<value>" במקום מספר.
        בנוסף, ייתכן שנרמול ישן/סניטייזר החליף כיוון מיון ב-$sort למחרוזת ריקה (""), מה שגורם ל:
        pymongo.errors.OperationFailure: Illegal key in $sort specification: <field>: "".

        פונקציה זו מחליפה את ה-placeholders בערכי ברירת מחדל תקינים.
        """
        def _fix_sort_spec_for_explain(sort_spec: Any) -> Any:
            if not isinstance(sort_spec, dict):
                return sort_spec

            fixed_sort: Dict[str, Any] = {}
            for field, order in sort_spec.items():
                # MongoDB מקבל כאן 1/-1 (או {$meta: ...}).
                # אם הסניטייזר הפך את הכיוון למחרוזת (כמו "" או "<value>") נחליף לברירת מחדל 1,
                # כדי ש-explain יצליח לרוץ.
                if isinstance(order, str):
                    s = order.strip()
                    if s in ("-1", "desc", "descending"):
                        fixed_sort[field] = -1
                    elif s in ("1", "+1", "asc", "ascending"):
                        fixed_sort[field] = 1
                    else:
                        fixed_sort[field] = 1
                elif isinstance(order, bool):
                    # bool הוא subclass של int - לא רוצים להעביר True/False ככיוון מיון
                    fixed_sort[field] = 1
                elif isinstance(order, (int, float)):
                    fixed_sort[field] = -1 if float(order) < 0 else 1
                else:
                    # למשל {"$meta": "textScore"} - נשאיר כמות שזה
                    fixed_sort[field] = order
            return fixed_sort

        def _fix_sort_placeholders_in_obj(obj: Any) -> Any:
            """תיקון $sort גם במבנים מקוננים (למשל בתוך $facet/$lookup pipeline)."""
            if isinstance(obj, list):
                return [_fix_sort_placeholders_in_obj(x) for x in obj]
            if isinstance(obj, dict):
                new_obj: Dict[str, Any] = {}
                for k, v in obj.items():
                    if k == "$sort":
                        new_obj[k] = _fix_sort_spec_for_explain(v)
                    else:
                        new_obj[k] = _fix_sort_placeholders_in_obj(v)
                return new_obj
            return obj

        fixed: List[Dict[str, Any]] = []
        for stage in (pipeline or []):
            if not isinstance(stage, dict):
                fixed.append(stage)
                continue

            new_stage = {}
            for key, value in stage.items():
                # תיקון $limit - חייב להיות מספר שלם חיובי
                if key == "$limit":
                    if not isinstance(value, (int, float)) or value <= 0:
                        new_stage[key] = 10  # ערך דמי לבדיקה
                    else:
                        new_stage[key] = int(value)
                # תיקון $skip - חייב להיות מספר שלם לא-שלילי
                elif key == "$skip":
                    if not isinstance(value, (int, float)) or value < 0:
                        new_stage[key] = 0
                    else:
                        new_stage[key] = int(value)
                # תיקון $sample - size חייב להיות מספר שלם חיובי
                elif key == "$sample":
                    # מקרה 1: זה מילון, אבל ה-size אולי לא תקין
                    if isinstance(value, dict):
                        sample_val = value.copy()
                        # וידוא ש-size הוא מספר חיובי
                        if "size" in sample_val and not (
                            isinstance(sample_val["size"], (int, float)) and sample_val["size"] > 0
                        ):
                            sample_val["size"] = 10
                        new_stage[key] = sample_val
                    # מקרה 2: זה מחרוזת (Placeholder), צריך להמציא מילון חדש
                    else:
                        new_stage[key] = {"size": 10}
                # תיקון $sort - כיוון מיון חייב להיות 1/-1 (או {$meta: ...})
                elif key == "$sort":
                    new_stage[key] = _fix_sort_spec_for_explain(value)
                else:
                    new_stage[key] = _fix_sort_placeholders_in_obj(value)

            fixed.append(new_stage)
        return fixed

    async def get_aggregation_explain(
        self,
        collection: str,
        pipeline: List[Dict[str, Any]],
        verbosity: str = "queryPlanner",  # ברירת מחדל בטוחה!
    ) -> AggregationExplainPlan:
        """
        קבלת explain plan לאגרגציה.
        """
        # בדיקה אם ה-pipeline מכיל query_shape שבור מגרסה ישנה
        for stage in (pipeline or []):
            if self._is_broken_query_shape(stage):
                raise ValueError(
                    "Pipeline contains broken array normalization from old version. "
                    "Arrays like '<N items>' cannot be used with explain(). "
                    "Please use the original pipeline or re-record this slow query."
                )

        # תיקון ערכי placeholder לפני שליחה ל-MongoDB
        fixed_pipeline = self._fix_pipeline_for_explain(pipeline)

        def _run_explain() -> Dict[str, Any]:
            db = getattr(self.db_manager, "db", None)
            if db is None:
                raise RuntimeError("No MongoDB database available")
            # MongoDB command API ל-aggregate explain
            return db.command(
                "aggregate",
                collection,
                pipeline=fixed_pipeline,
                explain=True,
                cursor={},
            )

        explain_result = await asyncio.to_thread(_run_explain)
        return self._parse_aggregation_explain(collection, pipeline, explain_result)

    def _parse_aggregation_explain(
        self,
        collection: str,
        pipeline: List[Dict[str, Any]],
        explain_result: Dict[str, Any],
    ) -> AggregationExplainPlan:
        """פרסור explain של אגרגציה"""
        stages: List[AggregationExplainStage] = []

        explain_stages = explain_result.get("stages", []) if isinstance(explain_result, dict) else []

        if not explain_stages:
            query_planner = explain_result.get("queryPlanner", {}) if isinstance(explain_result, dict) else {}
            if query_planner:
                stages.append(
                    AggregationExplainStage(
                        stage_name="OPTIMIZED_PIPELINE",
                        index_used=self._extract_index_from_planner(query_planner),
                    )
                )
        else:
            for stage_data in explain_stages:
                if isinstance(stage_data, dict):
                    stages.append(self._parse_aggregation_stage(stage_data))

        total_time = sum(float(s.execution_time_ms) for s in stages)

        pipeline_shape = self._normalize_pipeline_shape(pipeline)
        query_id = self._generate_query_id(collection, {"pipeline": pipeline_shape})

        return AggregationExplainPlan(
            query_id=query_id,
            collection=collection,
            pipeline_shape=pipeline_shape,
            stages=stages,
            total_execution_time_ms=total_time,
            server_info=explain_result.get("serverInfo", {}) if isinstance(explain_result, dict) else {},
        )

    def _extract_index_from_planner(self, query_planner: Dict[str, Any]) -> Optional[str]:
        try:
            winning_plan = query_planner.get("winningPlan", {})
            if isinstance(winning_plan, dict):
                return self._extract_index_name(winning_plan)
        except Exception:
            pass
        return None

    def _parse_aggregation_stage(self, stage_data: Dict[str, Any]) -> AggregationExplainStage:
        """פרסור שלב אגרגציה בודד"""
        stage_name = next((k for k in stage_data.keys() if str(k).startswith("$")), "UNKNOWN")
        stage_info = stage_data.get(stage_name, {}) if isinstance(stage_data.get(stage_name), dict) else {}

        execution_time = float(stage_data.get("executionTimeMillis", 0) or 0)
        docs_examined = int(stage_data.get("docsExamined", 0) or 0)
        n_returned = int(stage_data.get("nReturned", 0) or 0)
        uses_disk = bool(stage_data.get("usedDisk", False))
        memory_usage = int(stage_data.get("memUsage", 0) or 0)
        index_used = None
        lookup_collection = None
        lookup_strategy = None

        if stage_name == "$lookup":
            lookup_collection = stage_info.get("from")
            if "indexesUsed" in stage_data:
                indexes_used = stage_data.get("indexesUsed") or []
                if isinstance(indexes_used, list) and indexes_used:
                    index_used = indexes_used[0]
                lookup_strategy = "indexedLoopJoin"
            else:
                lookup_strategy = "nestedLoopJoin"

        if stage_name == "$match":
            input_stage = stage_data.get("inputStage", {}) if isinstance(stage_data.get("inputStage"), dict) else {}
            if input_stage.get("stage") == "IXSCAN":
                index_used = input_stage.get("indexName")

        return AggregationExplainStage(
            stage_name=str(stage_name),
            execution_time_ms=execution_time,
            docs_examined=docs_examined,
            n_returned=n_returned,
            uses_disk=uses_disk,
            memory_usage_bytes=memory_usage,
            index_used=index_used,
            lookup_collection=lookup_collection,
            lookup_strategy=lookup_strategy,
        )

    def _normalize_pipeline_shape(self, pipeline: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        נרמול צורת ה-pipeline - החלפת ערכים בפלייסהולדרים.

        ⚠️ מקרים מיוחדים:
        - $sort / $orderby: ערכים מוחזרים כמו שהם (1/-1 חייבים להישאר!)
        - שאר השלבים: נרמול רגיל
        """
        # מפתחות שבהם לא מנרמלים ערכים מספריים (1/-1) – קריטיים לתחביר MongoDB
        SORT_LIKE_KEYS = {"$sort", "$orderby"}

        normalized: List[Dict[str, Any]] = []
        for stage in pipeline or []:
            if not isinstance(stage, dict):
                continue
            normalized_stage: Dict[str, Any] = {}
            for key, value in stage.items():
                if key in SORT_LIKE_KEYS:
                    # ⚠️ קריטי: לא מנרמלים $sort - ערכי 1/-1 חייבים להישאר!
                    normalized_stage[key] = value
                elif isinstance(value, dict):
                    normalized_stage[key] = self._normalize_query_shape(value)
                else:
                    normalized_stage[key] = "<value>"
            normalized.append(normalized_stage)
        return normalized

    async def analyze_aggregation_and_recommend(self, explain: AggregationExplainPlan) -> List[OptimizationRecommendation]:
        """המלצות ספציפיות לאגרגציות"""
        recommendations: List[OptimizationRecommendation] = []

        for i, stage in enumerate(explain.stages):
            if stage.stage_name == "$lookup" and stage.lookup_strategy == "nestedLoopJoin":
                recommendations.append(
                    OptimizationRecommendation(
                        id=f"lookup_no_index_{explain.query_id}_{i}",
                        title=f"🔴 $lookup ללא אינדקס על '{stage.lookup_collection}'",
                        description=(
                            f"ה-$lookup מבצע nested loop join שהוא איטי מאוד. "
                            f"צור אינדקס על השדה המקושר ב-collection '{stage.lookup_collection}'."
                        ),
                        severity=SeverityLevel.CRITICAL,
                        category="index",
                        suggested_action=f"צור אינדקס על שדה ה-foreign field ב-{stage.lookup_collection}",
                        estimated_improvement="יכול לשפר פי 10-100",
                        code_example=f"db.{stage.lookup_collection}.createIndex({{ <foreignField>: 1 }})",
                    )
                )

            if stage.stage_name == "$sort" and stage.uses_disk:
                recommendations.append(
                    OptimizationRecommendation(
                        id=f"sort_disk_{explain.query_id}_{i}",
                        title="🟠 $sort משתמש בדיסק",
                        description=(
                            "פעולת המיון חרגה ממגבלת הזיכרון (100MB) והשתמשה בדיסק. "
                            "זה מאט משמעותית את השאילתה."
                        ),
                        severity=SeverityLevel.WARNING,
                        category="index",
                        suggested_action="הוסף $match לפני ה-$sort להקטנת כמות הנתונים, או צור אינדקס על שדה המיון",
                        estimated_improvement="מניעת I/O לדיסק",
                    )
                )

            if stage.stage_name == "$unwind":
                recommendations.append(
                    OptimizationRecommendation(
                        id=f"unwind_warning_{explain.query_id}_{i}",
                        title="⚠️ שימוש ב-$unwind",
                        description=(
                            "$unwind יכול להכפיל את מספר המסמכים פי גודל המערך. "
                            "ודא שאתה מסנן לפני ה-$unwind."
                        ),
                        severity=SeverityLevel.INFO,
                        category="query",
                        suggested_action="הוסף $match לפני $unwind להגבלת כמות המסמכים",
                        estimated_improvement="תלוי בגודל המערכים",
                    )
                )

            if stage.stage_name == "$match" and i > 0:
                has_early_match = any(s.stage_name == "$match" for s in explain.stages[:i])
                if not has_early_match:
                    recommendations.append(
                        OptimizationRecommendation(
                            id=f"match_order_{explain.query_id}_{i}",
                            title="🟡 $match לא בהתחלת ה-Pipeline",
                            description="כדאי לשים $match כמה שיותר מוקדם ב-pipeline כדי לסנן מסמכים מוקדם.",
                            severity=SeverityLevel.WARNING,
                            category="query",
                            suggested_action="העבר את ה-$match להתחלת ה-pipeline אם אפשר",
                            estimated_improvement="הפחתת כמות הנתונים בשלבים הבאים",
                        )
                    )

        severity_order = {SeverityLevel.CRITICAL: 0, SeverityLevel.WARNING: 1, SeverityLevel.INFO: 2}
        return sorted(recommendations, key=lambda r: severity_order.get(r.severity, 999))


class PersistentQueryProfilerService(QueryProfilerService):
    """
    גרסה משופרת של הפרופיילר עם שמירה ב-MongoDB.
    מתאימה ל-Production.
    """

    COLLECTION_NAME = "slow_queries_log"

    def __init__(self, db_manager: Any, slow_threshold_ms: int = QueryProfilerService.DEFAULT_SLOW_THRESHOLD_MS):
        super().__init__(db_manager=db_manager, slow_threshold_ms=slow_threshold_ms)

        # Cache/locks ברמת instance (לא משותף בין instances),
        # ובנוסף מבודד פר-event-loop כדי למנוע שימוש ב-asyncio.Lock בין לופים שונים
        # (למשל ב-Flask כשמריצים asyncio.run() שעשוי ליצור loop חדש).
        self._summary_cache_by_loop: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, Dict[str, Any]]" = (
            weakref.WeakKeyDictionary()
        )
        self._summary_cache_expires_at_by_loop: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, datetime]" = (
            weakref.WeakKeyDictionary()
        )
        self._summary_lock_by_loop: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Lock]" = (
            weakref.WeakKeyDictionary()
        )
        self._CACHE_TTL_SECONDS = 60

    async def record_slow_query(
        self,
        collection: str,
        operation: str,
        query: Dict[str, Any],
        execution_time_ms: float,
        client_info: Optional[Dict[str, Any]] = None,
    ) -> SlowQueryRecord:
        record = await super().record_slow_query(collection, operation, query, execution_time_ms, client_info)
        await self._persist_record(record)
        return record

    async def _persist_record(self, record: SlowQueryRecord) -> None:
        doc = {
            "query_id": record.query_id,
            "collection": record.collection,
            "operation": record.operation,
            "query_shape": record.query_shape,
            "execution_time_ms": record.execution_time_ms,
            "timestamp": record.timestamp,
            "client_info": record.client_info,
        }

        def _insert() -> None:
            db = getattr(self.db_manager, "db", None)
            if db is None:
                return None
            db[self.COLLECTION_NAME].insert_one(doc)
            return None

        await asyncio.to_thread(_insert)

    async def get_slow_queries(
        self,
        limit: int = 50,
        collection_filter: Optional[str] = None,
        min_execution_time_ms: Optional[float] = None,
        since: Optional[datetime] = None,
    ) -> List[SlowQueryRecord]:
        query: Dict[str, Any] = {}
        if collection_filter:
            query["collection"] = collection_filter
        if min_execution_time_ms is not None:
            query["execution_time_ms"] = {"$gte": float(min_execution_time_ms)}
        if since:
            query["timestamp"] = {"$gte": since}

        limit_n = max(1, int(limit))

        def _fetch() -> List[Dict[str, Any]]:
            db = getattr(self.db_manager, "db", None)
            if db is None:
                return []
            cursor = db[self.COLLECTION_NAME].find(query, sort=[("execution_time_ms", -1)], limit=limit_n)
            return list(cursor)

        docs = await asyncio.to_thread(_fetch)

        out: List[SlowQueryRecord] = []
        for doc in docs:
            if not isinstance(doc, dict):
                continue
            out.append(
                SlowQueryRecord(
                    query_id=str(doc.get("query_id") or ""),
                    collection=str(doc.get("collection") or ""),
                    operation=str(doc.get("operation") or ""),
                    query_shape=doc.get("query_shape") if isinstance(doc.get("query_shape"), dict) else {},
                    execution_time_ms=float(doc.get("execution_time_ms", 0) or 0),
                    timestamp=doc.get("timestamp") if isinstance(doc.get("timestamp"), datetime) else datetime.utcnow(),
                    client_info=doc.get("client_info") if isinstance(doc.get("client_info"), dict) else None,
                )
            )
        return out

    async def get_pattern_statistics(self, days: int = 7) -> List[Dict[str, Any]]:
        since = datetime.utcnow() - timedelta(days=max(1, int(days)))
        pipeline = [
            {"$match": {"timestamp": {"$gte": since}}},
            {
                "$group": {
                    "_id": {"query_id": "$query_id", "collection": "$collection", "operation": "$operation"},
                    "count": {"$sum": 1},
                    "avg_time_ms": {"$avg": "$execution_time_ms"},
                    "max_time_ms": {"$max": "$execution_time_ms"},
                    "min_time_ms": {"$min": "$execution_time_ms"},
                    "last_seen": {"$max": "$timestamp"},
                    "query_shape": {"$first": "$query_shape"},
                }
            },
            {"$sort": {"count": -1}},
            {"$limit": 50},
        ]

        def _aggregate() -> List[Dict[str, Any]]:
            db = getattr(self.db_manager, "db", None)
            if db is None:
                return []
            return list(db[self.COLLECTION_NAME].aggregate(pipeline))

        return await asyncio.to_thread(_aggregate)

    async def get_summary_async(self) -> Dict[str, Any]:
        """
        סיכום אסינכרוני שלא חוסם את ה-Event Loop:
        - Cache קצר (TTL) כדי לא להעמיס על ה-DB
        - חישוב כבד ב-thread (asyncio.to_thread)
        """
        now = datetime.utcnow()
        loop = asyncio.get_running_loop()

        cached = self._summary_cache_by_loop.get(loop)
        expires_at = self._summary_cache_expires_at_by_loop.get(loop)
        if cached is not None and expires_at is not None and expires_at > now:
            return cached

        lock = self._summary_lock_by_loop.get(loop)
        if lock is None:
            lock = asyncio.Lock()
            self._summary_lock_by_loop[loop] = lock

        async with lock:
            # Double-check בתוך הנעילה כדי למנוע cache stampede
            now = datetime.utcnow()
            cached = self._summary_cache_by_loop.get(loop)
            expires_at = self._summary_cache_expires_at_by_loop.get(loop)
            if cached is not None and expires_at is not None and expires_at > now:
                return cached

            try:
                result = await asyncio.to_thread(self._calculate_summary_sync)
            except Exception as e:
                logger.error("Error calculating profiler summary", exc_info=True, extra={"error": str(e)})
                return super().get_summary()

            self._summary_cache_by_loop[loop] = result
            self._summary_cache_expires_at_by_loop[loop] = now + timedelta(seconds=self._CACHE_TTL_SECONDS)
            return result

    def _calculate_summary_sync(self) -> Dict[str, Any]:
        """חישוב סינכרוני (רץ ב-thread דרך asyncio.to_thread) – כולל כל הלוגיקה המלאה."""
        try:
            db = getattr(self.db_manager, "db", None)
            if db is None:
                return super().get_summary()
            # חישוב lightweight על חלון קצר (24h) כדי להימנע מעומס
            since = datetime.utcnow() - timedelta(hours=24)
            query = {"timestamp": {"$gte": since}}
            total = int(db[self.COLLECTION_NAME].count_documents(query))
            if total <= 0:
                return {
                    "total_slow_queries": 0,
                    "collections_affected": [],
                    "avg_execution_time_ms": 0,
                    "max_execution_time_ms": 0,
                    "unique_patterns": 0,
                    "threshold_ms": self.slow_threshold_ms,
                }
            agg = list(
                db[self.COLLECTION_NAME].aggregate(
                    [
                        {"$match": query},
                        {
                            "$group": {
                                "_id": None,
                                "avg_ms": {"$avg": "$execution_time_ms"},
                                "max_ms": {"$max": "$execution_time_ms"},
                                "collections": {"$addToSet": "$collection"},
                                "unique_patterns": {"$addToSet": "$query_id"},
                            }
                        },
                    ]
                )
            )
            doc = agg[0] if agg else {}
            collections = doc.get("collections") if isinstance(doc.get("collections"), list) else []
            patterns = doc.get("unique_patterns") if isinstance(doc.get("unique_patterns"), list) else []
            return {
                "total_slow_queries": total,
                "collections_affected": collections,
                "avg_execution_time_ms": round(float(doc.get("avg_ms", 0) or 0), 2),
                "max_execution_time_ms": round(float(doc.get("max_ms", 0) or 0), 2),
                "unique_patterns": len(patterns),
                "threshold_ms": self.slow_threshold_ms,
            }
        except Exception:
            return super().get_summary()

    def get_summary(self) -> Dict[str, Any]:
        """
        תאימות לאחור (סינכרוני).

        ⚠️ חשוב: בשרת אסינכרוני, עדיף לקרוא ל-get_summary_async() כדי לא לחסום את ה-Event Loop.
        """
        return self._calculate_summary_sync()

