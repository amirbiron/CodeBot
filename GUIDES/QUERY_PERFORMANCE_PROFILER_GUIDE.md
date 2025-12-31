# 🐢 Query Performance Profiler - מדריך מימוש מלא

> **מדריך זה מתאר כיצד לממש ממשק לניתוח שאילתות MongoDB איטיות עם explain plans ויזואליים והמלצות אופטימיזציה.**  
> המדריך תואם לארכיטקטורה הקיימת ומתבסס על התשתיות הקיימות במערכת.

---

## 📋 תוכן עניינים

1. [סקירה כללית](#סקירה-כללית)
2. [ארכיטקטורה](#ארכיטקטורה)
3. [שכבת השירות - QueryProfilerService](#שכבת-השירות)
4. [מבני נתונים](#מבני-נתונים)
5. [יצירת Explain Plans](#יצירת-explain-plans)
6. [המלצות אופטימיזציה](#המלצות-אופטימיזציה)
7. [נקודות קצה API](#נקודות-קצה-api)
8. [ממשק משתמש ויזואלי](#ממשק-משתמש-ויזואלי)
9. [אבטחה](#אבטחה)
10. [משתני סביבה](#משתני-סביבה)
11. [בדיקות יחידה](#בדיקות-יחידה)
12. [אינטגרציה עם Observability](#אינטגרציה-עם-observability)
13. [טיפים לפתרון בעיות](#טיפים-לפתרון-בעיות)

---

## סקירה כללית

### מטרת המודול

Query Performance Profiler מספק:

1. **זיהוי שאילתות איטיות** - מעקב בזמן אמת אחרי שאילתות שחורגות מסף זמן מוגדר
2. **ניתוח Explain Plans** - הצגה ויזואלית של תוכנית הביצוע של MongoDB
3. **המלצות אופטימיזציה** - הצעות אוטומטיות לשיפור ביצועים
4. **היסטוריית שאילתות** - שמירה וניתוח של דפוסי שאילתות לאורך זמן

### תאימות לקוד קיים

המודול מתבסס על:

- **`_SlowMongoListener`** מ-`database/manager.py` - ליסנר קיים לשאילתות איטיות
- **`AsyncDatabaseHealthService`** מ-`services/db_health_service.py` - שירות בריאות DB קיים
- **`track_performance`** מ-`database/repository.py` - מנגנון מעקב ביצועים קיים

---

## ארכיטקטורה

```
┌─────────────────────────────────────────────────────────────────┐
│                        Web Dashboard                             │
│   ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐ │
│   │ Slow Query  │  │   Explain   │  │    Optimization         │ │
│   │    List     │  │    Plan     │  │    Recommendations      │ │
│   │             │  │  Visualizer │  │                         │ │
│   └──────┬──────┘  └──────┬──────┘  └────────────┬────────────┘ │
└──────────┼────────────────┼─────────────────────┼───────────────┘
           │                │                     │
           ▼                ▼                     ▼
┌─────────────────────────────────────────────────────────────────┐
│                     aiohttp API Layer                            │
│   GET /api/profiler/slow-queries                                │
│   GET /api/profiler/explain/{query_id}                          │
│   GET /api/profiler/recommendations                             │
│   POST /api/profiler/analyze                                    │
└─────────────────────────────────────────────────────────────────┘
           │
           ▼
┌─────────────────────────────────────────────────────────────────┐
│                  QueryProfilerService                            │
│   ┌───────────────┐  ┌───────────────┐  ┌───────────────────┐   │
│   │ SlowQuery     │  │ ExplainPlan   │  │ Optimization      │   │
│   │ Collector     │  │ Analyzer      │  │ Engine            │   │
│   └───────┬───────┘  └───────┬───────┘  └─────────┬─────────┘   │
└───────────┼──────────────────┼────────────────────┼─────────────┘
            │                  │                    │
            ▼                  ▼                    ▼
┌─────────────────────────────────────────────────────────────────┐
│                      MongoDB Driver                              │
│   • PyMongo CommandMonitoring                                   │
│   • explain() API                                               │
│   • system.profile collection                                   │
└─────────────────────────────────────────────────────────────────┘
```

---

## מבני נתונים

### Dataclasses להגדרת מבני הנתונים

```python
# services/query_profiler_service.py

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum


class QueryStage(Enum):
    """שלבי ביצוע שאילתה ב-MongoDB"""
    COLLSCAN = "COLLSCAN"      # סריקת collection מלאה
    IXSCAN = "IXSCAN"          # סריקת אינדקס
    FETCH = "FETCH"            # שליפת מסמכים
    SORT = "SORT"              # מיון
    PROJECTION = "PROJECTION"  # projection
    LIMIT = "LIMIT"            # הגבלת תוצאות
    SKIP = "SKIP"              # דילוג על תוצאות
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
    input_stage: Optional['ExplainStage'] = None
    docs_examined: int = 0
    keys_examined: int = 0
    execution_time_ms: float = 0
    index_name: Optional[str] = None
    direction: str = "forward"
    filter_condition: Optional[Dict[str, Any]] = None
    children: List['ExplainStage'] = field(default_factory=list)


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
```

---

## שכבת השירות

### QueryProfilerService - מימוש מלא

```python
# services/query_profiler_service.py

import asyncio
import hashlib
import json
import logging
from collections import deque
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Deque

from pymongo import monitoring
from pymongo.command_cursor import CommandCursor

from database.manager import DatabaseManager

logger = logging.getLogger(__name__)


class QueryProfilerService:
    """
    שירות לניתוח ביצועי שאילתות MongoDB.
    
    מספק:
    - איסוף שאילתות איטיות בזמן אמת
    - יצירת explain plans
    - ניתוח והמלצות אופטימיזציה
    """
    
    # סף ברירת מחדל לשאילתה איטית (במילישניות)
    DEFAULT_SLOW_THRESHOLD_MS = 100
    
    # מספר מקסימלי של שאילתות איטיות לשמור בזיכרון
    MAX_SLOW_QUERIES_BUFFER = 1000
    
    def __init__(
        self,
        db_manager: DatabaseManager,
        slow_threshold_ms: int = DEFAULT_SLOW_THRESHOLD_MS
    ):
        self.db_manager = db_manager
        self.slow_threshold_ms = slow_threshold_ms
        self._slow_queries: Deque[SlowQueryRecord] = deque(maxlen=self.MAX_SLOW_QUERIES_BUFFER)
        self._query_patterns: Dict[str, int] = {}  # מעקב אחר דפוסי שאילתות
        
    def _generate_query_id(self, collection: str, query_shape: Dict) -> str:
        """יצירת מזהה ייחודי לשאילתה"""
        content = f"{collection}:{json.dumps(query_shape, sort_keys=True)}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]
    
    def _normalize_query_shape(self, query: Dict[str, Any]) -> Dict[str, Any]:
        """
        נרמול צורת השאילתה - החלפת ערכים בפלייסהולדרים.
        מאפשר זיהוי דפוסי שאילתות דומים.
        """
        def normalize_value(value: Any) -> Any:
            if isinstance(value, dict):
                return {k: normalize_value(v) for k, v in value.items()}
            elif isinstance(value, list):
                return [normalize_value(v) for v in value]
            elif isinstance(value, (str, int, float, bool)):
                return "<value>"
            return "<value>"
        
        return {k: normalize_value(v) for k, v in query.items()}
    
    async def record_slow_query(
        self,
        collection: str,
        operation: str,
        query: Dict[str, Any],
        execution_time_ms: float,
        client_info: Optional[Dict[str, Any]] = None
    ) -> SlowQueryRecord:
        """
        רישום שאילתה איטית.
        נקרא אוטומטית על ידי ה-CommandListener.
        """
        query_shape = self._normalize_query_shape(query)
        query_id = self._generate_query_id(collection, query_shape)
        
        record = SlowQueryRecord(
            query_id=query_id,
            collection=collection,
            operation=operation,
            query_shape=query_shape,
            execution_time_ms=execution_time_ms,
            timestamp=datetime.utcnow(),
            client_info=client_info
        )
        
        self._slow_queries.append(record)
        
        # עדכון מונה דפוסי שאילתות
        pattern_key = f"{collection}:{operation}:{json.dumps(query_shape, sort_keys=True)}"
        self._query_patterns[pattern_key] = self._query_patterns.get(pattern_key, 0) + 1
        
        logger.warning(
            f"Slow query recorded: {collection}.{operation} "
            f"took {execution_time_ms:.2f}ms (threshold: {self.slow_threshold_ms}ms)"
        )
        
        return record
    
    async def get_slow_queries(
        self,
        limit: int = 50,
        collection_filter: Optional[str] = None,
        min_execution_time_ms: Optional[float] = None,
        since: Optional[datetime] = None
    ) -> List[SlowQueryRecord]:
        """
        קבלת רשימת שאילתות איטיות עם אפשרויות סינון.
        """
        queries = list(self._slow_queries)
        
        # סינון לפי collection
        if collection_filter:
            queries = [q for q in queries if q.collection == collection_filter]
        
        # סינון לפי זמן ביצוע מינימלי
        if min_execution_time_ms:
            queries = [q for q in queries if q.execution_time_ms >= min_execution_time_ms]
        
        # סינון לפי זמן
        if since:
            queries = [q for q in queries if q.timestamp >= since]
        
        # מיון לפי זמן ביצוע (הכי איטיות קודם)
        queries.sort(key=lambda q: q.execution_time_ms, reverse=True)
        
        return queries[:limit]
    
    async def get_explain_plan(
        self,
        collection: str,
        query: Dict[str, Any],
        verbosity: str = "executionStats"
    ) -> ExplainPlan:
        """
        קבלת explain plan מפורט לשאילתה.
        
        Args:
            collection: שם ה-collection
            query: השאילתה לניתוח
            verbosity: רמת פירוט ("queryPlanner", "executionStats", "allPlansExecution")
        
        Returns:
            ExplainPlan עם כל פרטי תוכנית הביצוע
        """
        def _run_explain():
            db = self.db_manager.db
            coll = db[collection]
            
            # הרצת explain
            explain_result = coll.find(query).explain(verbosity)
            return explain_result
        
        # הרצה ב-thread נפרד כדי לא לחסום את ה-event loop
        explain_result = await asyncio.to_thread(_run_explain)
        
        # פרסור התוצאה
        return self._parse_explain_result(collection, query, explain_result)
    
    def _parse_explain_result(
        self,
        collection: str,
        query: Dict[str, Any],
        explain_result: Dict[str, Any]
    ) -> ExplainPlan:
        """פרסור תוצאת explain ליצירת ExplainPlan"""
        
        query_planner = explain_result.get("queryPlanner", {})
        execution_stats = explain_result.get("executionStats", {})
        
        winning_plan_raw = query_planner.get("winningPlan", {})
        winning_plan = self._parse_stage(winning_plan_raw)
        
        # פרסור תוכניות שנדחו
        rejected_plans = []
        for plan in query_planner.get("rejectedPlans", []):
            rejected_plans.append(self._parse_stage(plan))
        
        # יצירת סטטיסטיקות
        stats = None
        if execution_stats:
            stats = QueryStats(
                execution_time_ms=execution_stats.get("executionTimeMillis", 0),
                docs_examined=execution_stats.get("totalDocsExamined", 0),
                docs_returned=execution_stats.get("nReturned", 0),
                keys_examined=execution_stats.get("totalKeysExamined", 0),
                index_used=self._extract_index_name(winning_plan_raw),
                is_covered_query=self._is_covered_query(execution_stats)
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
            server_info=explain_result.get("serverInfo", {})
        )
    
    def _parse_stage(self, stage_data: Dict[str, Any]) -> ExplainStage:
        """פרסור שלב בודד ב-explain plan"""
        stage_name = stage_data.get("stage", "UNKNOWN")
        
        try:
            stage_type = QueryStage(stage_name)
        except ValueError:
            stage_type = QueryStage.FETCH  # ברירת מחדל
        
        # פרסור שלב קלט (אם קיים)
        input_stage = None
        if "inputStage" in stage_data:
            input_stage = self._parse_stage(stage_data["inputStage"])
        
        # פרסור שלבי ילדים (למקרים של $or וכו')
        children = []
        if "inputStages" in stage_data:
            for child_stage in stage_data["inputStages"]:
                children.append(self._parse_stage(child_stage))
        
        return ExplainStage(
            stage=stage_type,
            input_stage=input_stage,
            index_name=stage_data.get("indexName"),
            direction=stage_data.get("direction", "forward"),
            filter_condition=stage_data.get("filter"),
            children=children
        )
    
    def _extract_index_name(self, plan: Dict[str, Any]) -> Optional[str]:
        """חילוץ שם האינדקס מתוכנית הביצוע"""
        if "indexName" in plan:
            return plan["indexName"]
        if "inputStage" in plan:
            return self._extract_index_name(plan["inputStage"])
        return None
    
    def _is_covered_query(self, execution_stats: Dict[str, Any]) -> bool:
        """בדיקה האם השאילתה היא covered query"""
        docs_examined = execution_stats.get("totalDocsExamined", 0)
        keys_examined = execution_stats.get("totalKeysExamined", 0)
        n_returned = execution_stats.get("nReturned", 0)
        
        # Covered query = כל הנתונים נמצאים באינדקס
        return docs_examined == 0 and keys_examined >= n_returned and n_returned > 0
    
    async def analyze_and_recommend(
        self,
        explain_plan: ExplainPlan
    ) -> List[OptimizationRecommendation]:
        """
        ניתוח explain plan ויצירת המלצות אופטימיזציה.
        """
        recommendations = []
        
        # בדיקה 1: COLLSCAN - סריקה מלאה
        if self._has_collscan(explain_plan.winning_plan):
            recommendations.append(self._create_collscan_recommendation(explain_plan))
        
        # בדיקה 2: יחס יעילות נמוך
        if explain_plan.stats and explain_plan.stats.efficiency_ratio < 0.1:
            recommendations.append(self._create_efficiency_recommendation(explain_plan))
        
        # בדיקה 3: SORT בזיכרון
        if self._has_in_memory_sort(explain_plan.winning_plan):
            recommendations.append(self._create_sort_recommendation(explain_plan))
        
        # בדיקה 4: המלצה ל-covered query
        if explain_plan.stats and not explain_plan.stats.is_covered_query:
            if self._could_be_covered_query(explain_plan):
                recommendations.append(self._create_covered_query_recommendation(explain_plan))
        
        # בדיקה 5: שאילתות תכופות
        pattern_count = self._get_pattern_frequency(explain_plan)
        if pattern_count > 10:
            recommendations.append(self._create_frequent_query_recommendation(explain_plan, pattern_count))
        
        return recommendations
    
    def _has_collscan(self, stage: ExplainStage) -> bool:
        """בדיקה האם יש COLLSCAN בתוכנית"""
        if stage.stage == QueryStage.COLLSCAN:
            return True
        if stage.input_stage:
            return self._has_collscan(stage.input_stage)
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
        # אם יש אינדקס ושדות ה-projection מוגבלים
        return explain_plan.stats is not None and explain_plan.stats.index_used is not None
    
    def _get_pattern_frequency(self, explain_plan: ExplainPlan) -> int:
        """קבלת תדירות דפוס השאילתה"""
        pattern_key = f"{explain_plan.collection}:find:{json.dumps(explain_plan.query_shape, sort_keys=True)}"
        return self._query_patterns.get(pattern_key, 0)
    
    def _create_collscan_recommendation(self, explain_plan: ExplainPlan) -> OptimizationRecommendation:
        """יצירת המלצה לטיפול ב-COLLSCAN"""
        # חילוץ שדות מהשאילתה
        fields = list(explain_plan.query_shape.keys())
        index_suggestion = ", ".join(f'"{f}": 1' for f in fields[:3])  # עד 3 שדות
        
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
            code_example=f'''db.{explain_plan.collection}.createIndex({{ {index_suggestion} }})''',
            documentation_link="https://www.mongodb.com/docs/manual/indexes/"
        )
    
    def _create_efficiency_recommendation(self, explain_plan: ExplainPlan) -> OptimizationRecommendation:
        """יצירת המלצה ליחס יעילות נמוך"""
        stats = explain_plan.stats
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
            estimated_improvement=f"צמצום סריקה מ-{stats.docs_examined:,} ל-~{stats.docs_returned:,} מסמכים"
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
            estimated_improvement="חיסכון בזיכרון ושיפור מהירות"
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
            estimated_improvement="עד 50% שיפור בגישה לנתונים"
        )
    
    def _create_frequent_query_recommendation(
        self, 
        explain_plan: ExplainPlan, 
        count: int
    ) -> OptimizationRecommendation:
        """יצירת המלצה לשאילתות תכופות"""
        return OptimizationRecommendation(
            id=f"frequent_{explain_plan.query_id}",
            title="📊 דפוס שאילתה תכופה",
            description=f"שאילתה זו הופיעה {count} פעמים. שקול אופטימיזציה או caching.",
            severity=SeverityLevel.INFO,
            category="query",
            suggested_action="שקול caching ברמת האפליקציה או אופטימיזציה נוספת",
            estimated_improvement="הפחתת עומס על בסיס הנתונים"
        )
    
    async def get_collection_stats(self, collection: str) -> Dict[str, Any]:
        """קבלת סטטיסטיקות collection לצורך המלצות"""
        def _get_stats():
            db = self.db_manager.db
            stats = db.command("collStats", collection)
            indexes = list(db[collection].list_indexes())
            return {
                "size_bytes": stats.get("size", 0),
                "count": stats.get("count", 0),
                "avg_obj_size": stats.get("avgObjSize", 0),
                "index_count": len(indexes),
                "indexes": [idx["name"] for idx in indexes],
                "total_index_size": stats.get("totalIndexSize", 0)
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
                "unique_patterns": 0
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
            "threshold_ms": self.slow_threshold_ms
        }
```

---

## יצירת Explain Plans

### שימוש ב-explain() API

MongoDB מספקת שלוש רמות פירוט ל-explain:

| רמה | תיאור | מתי להשתמש |
|-----|-------|------------|
| `queryPlanner` | תוכנית בלבד, ללא הרצה | לבדיקת אינדקסים |
| `executionStats` | כולל סטטיסטיקות ביצוע | ניתוח ביצועים מלא |
| `allPlansExecution` | כל התוכניות שנבחנו | debug מתקדם |

### דוגמת שימוש

```python
# קבלת explain plan לשאילתה ספציפית
profiler = QueryProfilerService(db_manager)

explain = await profiler.get_explain_plan(
    collection="code_snippets",
    query={"user_id": "user123", "is_deleted": False},
    verbosity="executionStats"
)

print(f"Collection: {explain.collection}")
print(f"Index Used: {explain.stats.index_used}")
print(f"Docs Examined: {explain.stats.docs_examined}")
print(f"Execution Time: {explain.stats.execution_time_ms}ms")
```

---

## המלצות אופטימיזציה

### קטגוריות המלצות

| קטגוריה | תיאור | דוגמאות |
|---------|-------|---------|
| `index` | בעיות אינדקסים | COLLSCAN, missing index |
| `query` | מבנה שאילתה | יחס יעילות, regex |
| `schema` | מבנה נתונים | embedding vs referencing |
| `connection` | חיבורים | pool size, timeouts |

### אלגוריתם המלצות

```python
async def generate_recommendations(self, explain_plan: ExplainPlan) -> List[OptimizationRecommendation]:
    """
    אלגוריתם יצירת המלצות:
    
    1. ניתוח שלבי הביצוע (stages)
    2. בדיקת יחסי יעילות
    3. זיהוי דפוסים בעייתיים
    4. יצירת המלצות עם עדיפויות
    """
    recommendations = await self.analyze_and_recommend(explain_plan)
    
    # מיון לפי חומרה
    severity_order = {
        SeverityLevel.CRITICAL: 0,
        SeverityLevel.WARNING: 1,
        SeverityLevel.INFO: 2
    }
    
    return sorted(recommendations, key=lambda r: severity_order[r.severity])
```

### טבלת בעיות נפוצות והמלצות

| בעיה | סימפטום | המלצה |
|------|---------|-------|
| COLLSCAN | `stage: "COLLSCAN"` | צור אינדקס על שדות הסינון |
| Sort בזיכרון | `stage: "SORT"` | הוסף שדה מיון לאינדקס |
| יחס יעילות נמוך | `docsExamined >> nReturned` | שפר selectivity של האינדקס |
| שאילתות $regex | `$regex` בהתחלה | הימנע מ-regex או השתמש ב-text index |
| $or לא אופטימלי | מספר COLLSCANs | צור אינדקסים לכל תנאי |

---

## נקודות קצה API

### הגדרת Routes

```python
# handlers/profiler_handler.py

import json
from datetime import datetime, timedelta
from aiohttp import web
from typing import Dict, Any

from services.query_profiler_service import QueryProfilerService


def setup_profiler_routes(app: web.Application, profiler_service: QueryProfilerService):
    """הגדרת routes לפרופיילר"""
    
    async def get_slow_queries(request: web.Request) -> web.Response:
        """GET /api/profiler/slow-queries"""
        limit = int(request.query.get("limit", 50))
        collection = request.query.get("collection")
        min_time = request.query.get("min_time")
        hours = request.query.get("hours")
        
        since = None
        if hours:
            since = datetime.utcnow() - timedelta(hours=int(hours))
        
        queries = await profiler_service.get_slow_queries(
            limit=limit,
            collection_filter=collection,
            min_execution_time_ms=float(min_time) if min_time else None,
            since=since
        )
        
        return web.json_response({
            "status": "success",
            "data": [_serialize_slow_query(q) for q in queries],
            "count": len(queries)
        })
    
    async def get_explain_plan(request: web.Request) -> web.Response:
        """POST /api/profiler/explain"""
        body = await request.json()
        
        collection = body.get("collection")
        query = body.get("query", {})
        verbosity = body.get("verbosity", "executionStats")
        
        if not collection:
            return web.json_response(
                {"status": "error", "message": "collection is required"},
                status=400
            )
        
        explain = await profiler_service.get_explain_plan(
            collection=collection,
            query=query,
            verbosity=verbosity
        )
        
        return web.json_response({
            "status": "success",
            "data": _serialize_explain_plan(explain)
        })
    
    async def get_recommendations(request: web.Request) -> web.Response:
        """POST /api/profiler/recommendations"""
        body = await request.json()
        
        collection = body.get("collection")
        query = body.get("query", {})
        
        if not collection:
            return web.json_response(
                {"status": "error", "message": "collection is required"},
                status=400
            )
        
        explain = await profiler_service.get_explain_plan(
            collection=collection,
            query=query
        )
        
        recommendations = await profiler_service.analyze_and_recommend(explain)
        
        return web.json_response({
            "status": "success",
            "data": {
                "explain": _serialize_explain_plan(explain),
                "recommendations": [_serialize_recommendation(r) for r in recommendations]
            }
        })
    
    async def get_summary(request: web.Request) -> web.Response:
        """GET /api/profiler/summary"""
        summary = profiler_service.get_summary()
        return web.json_response({
            "status": "success",
            "data": summary
        })
    
    async def get_collection_stats(request: web.Request) -> web.Response:
        """GET /api/profiler/collection/{name}/stats"""
        collection = request.match_info["name"]
        stats = await profiler_service.get_collection_stats(collection)
        return web.json_response({
            "status": "success",
            "data": stats
        })
    
    # רישום routes
    app.router.add_get("/api/profiler/slow-queries", get_slow_queries)
    app.router.add_post("/api/profiler/explain", get_explain_plan)
    app.router.add_post("/api/profiler/recommendations", get_recommendations)
    app.router.add_get("/api/profiler/summary", get_summary)
    app.router.add_get("/api/profiler/collection/{name}/stats", get_collection_stats)


def _serialize_slow_query(query) -> Dict[str, Any]:
    """המרת SlowQueryRecord ל-dict"""
    return {
        "query_id": query.query_id,
        "collection": query.collection,
        "operation": query.operation,
        "query_shape": query.query_shape,
        "execution_time_ms": query.execution_time_ms,
        "timestamp": query.timestamp.isoformat()
    }


def _serialize_explain_plan(plan) -> Dict[str, Any]:
    """המרת ExplainPlan ל-dict"""
    return {
        "query_id": plan.query_id,
        "collection": plan.collection,
        "query_shape": plan.query_shape,
        "winning_plan": _serialize_stage(plan.winning_plan),
        "rejected_plans": [_serialize_stage(p) for p in plan.rejected_plans],
        "stats": {
            "execution_time_ms": plan.stats.execution_time_ms,
            "docs_examined": plan.stats.docs_examined,
            "docs_returned": plan.stats.docs_returned,
            "keys_examined": plan.stats.keys_examined,
            "index_used": plan.stats.index_used,
            "is_covered_query": plan.stats.is_covered_query,
            "efficiency_ratio": round(plan.stats.efficiency_ratio, 4)
        } if plan.stats else None,
        "timestamp": plan.timestamp.isoformat()
    }


def _serialize_stage(stage) -> Dict[str, Any]:
    """המרת ExplainStage ל-dict"""
    return {
        "stage": stage.stage.value,
        "index_name": stage.index_name,
        "direction": stage.direction,
        "filter_condition": stage.filter_condition,
        "input_stage": _serialize_stage(stage.input_stage) if stage.input_stage else None,
        "children": [_serialize_stage(c) for c in stage.children]
    }


def _serialize_recommendation(rec) -> Dict[str, Any]:
    """המרת OptimizationRecommendation ל-dict"""
    return {
        "id": rec.id,
        "title": rec.title,
        "description": rec.description,
        "severity": rec.severity.value,
        "category": rec.category,
        "suggested_action": rec.suggested_action,
        "estimated_improvement": rec.estimated_improvement,
        "code_example": rec.code_example,
        "documentation_link": rec.documentation_link
    }
```

---

## ממשק משתמש ויזואלי

### תבנית HTML - דשבורד הפרופיילר

```html
<!-- webapp/templates/profiler_dashboard.html -->
{% extends "base.html" %}

{% block title %}Query Performance Profiler{% endblock %}

{% block content %}
<div class="container-fluid py-4">
    <h1 class="mb-4">🐢 Query Performance Profiler</h1>
    
    <!-- סיכום מצב -->
    <div class="row mb-4" id="summary-section">
        <div class="col-md-3">
            <div class="card bg-danger text-white">
                <div class="card-body">
                    <h5 class="card-title">שאילתות איטיות</h5>
                    <h2 id="total-slow-queries">--</h2>
                </div>
            </div>
        </div>
        <div class="col-md-3">
            <div class="card bg-warning">
                <div class="card-body">
                    <h5 class="card-title">זמן ממוצע (ms)</h5>
                    <h2 id="avg-time">--</h2>
                </div>
            </div>
        </div>
        <div class="col-md-3">
            <div class="card bg-info text-white">
                <div class="card-body">
                    <h5 class="card-title">Collections מושפעים</h5>
                    <h2 id="collections-count">--</h2>
                </div>
            </div>
        </div>
        <div class="col-md-3">
            <div class="card bg-secondary text-white">
                <div class="card-body">
                    <h5 class="card-title">דפוסים ייחודיים</h5>
                    <h2 id="unique-patterns">--</h2>
                </div>
            </div>
        </div>
    </div>
    
    <!-- טבלת שאילתות איטיות -->
    <div class="card mb-4">
        <div class="card-header d-flex justify-content-between align-items-center">
            <h5 class="mb-0">📋 שאילתות איטיות אחרונות</h5>
            <div>
                <select id="collection-filter" class="form-select form-select-sm d-inline-block w-auto">
                    <option value="">כל ה-Collections</option>
                </select>
                <button class="btn btn-sm btn-primary" onclick="refreshSlowQueries()">
                    🔄 רענן
                </button>
            </div>
        </div>
        <div class="card-body">
            <div class="table-responsive">
                <table class="table table-hover" id="slow-queries-table">
                    <thead>
                        <tr>
                            <th>Collection</th>
                            <th>פעולה</th>
                            <th>צורת שאילתה</th>
                            <th>זמן (ms)</th>
                            <th>זמן</th>
                            <th>פעולות</th>
                        </tr>
                    </thead>
                    <tbody>
                        <!-- ימולא דינמית -->
                    </tbody>
                </table>
            </div>
        </div>
    </div>
    
    <!-- אזור ניתוח שאילתה -->
    <div class="card mb-4">
        <div class="card-header">
            <h5 class="mb-0">🔍 ניתוח שאילתה</h5>
        </div>
        <div class="card-body">
            <div class="row">
                <div class="col-md-4">
                    <label class="form-label">Collection</label>
                    <input type="text" id="analyze-collection" class="form-control" placeholder="code_snippets">
                </div>
                <div class="col-md-6">
                    <label class="form-label">שאילתה (JSON)</label>
                    <textarea id="analyze-query" class="form-control" rows="3" placeholder='{"user_id": "123"}'></textarea>
                </div>
                <div class="col-md-2 d-flex align-items-end">
                    <button class="btn btn-success w-100" onclick="analyzeQuery()">
                        נתח שאילתה
                    </button>
                </div>
            </div>
        </div>
    </div>
    
    <!-- תוצאות הניתוח -->
    <div class="row" id="analysis-results" style="display: none;">
        <!-- Explain Plan ויזואלי -->
        <div class="col-md-6">
            <div class="card">
                <div class="card-header">
                    <h5 class="mb-0">📊 Explain Plan</h5>
                </div>
                <div class="card-body">
                    <div id="explain-plan-visual"></div>
                    <div id="explain-stats" class="mt-3"></div>
                </div>
            </div>
        </div>
        
        <!-- המלצות אופטימיזציה -->
        <div class="col-md-6">
            <div class="card">
                <div class="card-header">
                    <h5 class="mb-0">💡 המלצות אופטימיזציה</h5>
                </div>
                <div class="card-body">
                    <div id="recommendations-list"></div>
                </div>
            </div>
        </div>
    </div>
</div>

<style>
/* עיצוב Explain Plan */
.stage-node {
    padding: 10px 15px;
    border-radius: 8px;
    margin: 5px 0;
    position: relative;
}

.stage-collscan {
    background-color: #f8d7da;
    border: 2px solid #dc3545;
}

.stage-ixscan {
    background-color: #d4edda;
    border: 2px solid #28a745;
}

.stage-fetch {
    background-color: #fff3cd;
    border: 2px solid #ffc107;
}

.stage-sort {
    background-color: #cce5ff;
    border: 2px solid #007bff;
}

.stage-default {
    background-color: #e9ecef;
    border: 2px solid #6c757d;
}

.stage-connector {
    width: 2px;
    height: 20px;
    background-color: #6c757d;
    margin: 0 auto;
}

/* המלצות */
.recommendation-card {
    border-radius: 8px;
    padding: 15px;
    margin-bottom: 10px;
}

.recommendation-critical {
    background-color: #f8d7da;
    border-left: 4px solid #dc3545;
}

.recommendation-warning {
    background-color: #fff3cd;
    border-left: 4px solid #ffc107;
}

.recommendation-info {
    background-color: #d1ecf1;
    border-left: 4px solid #17a2b8;
}

.code-example {
    background-color: #2d2d2d;
    color: #f8f8f2;
    padding: 10px;
    border-radius: 4px;
    font-family: monospace;
    overflow-x: auto;
}
</style>

<script>
// טעינת נתונים התחלתית
document.addEventListener('DOMContentLoaded', function() {
    loadSummary();
    refreshSlowQueries();
});

async function loadSummary() {
    try {
        const response = await fetch('/api/profiler/summary');
        const result = await response.json();
        
        if (result.status === 'success') {
            const data = result.data;
            document.getElementById('total-slow-queries').textContent = data.total_slow_queries;
            document.getElementById('avg-time').textContent = data.avg_execution_time_ms.toFixed(2);
            document.getElementById('collections-count').textContent = data.collections_affected.length;
            document.getElementById('unique-patterns').textContent = data.unique_patterns;
            
            // מילוי dropdown של collections
            const select = document.getElementById('collection-filter');
            data.collections_affected.forEach(coll => {
                const option = document.createElement('option');
                option.value = coll;
                option.textContent = coll;
                select.appendChild(option);
            });
        }
    } catch (error) {
        console.error('Error loading summary:', error);
    }
}

async function refreshSlowQueries() {
    const collection = document.getElementById('collection-filter').value;
    let url = '/api/profiler/slow-queries?limit=50';
    if (collection) {
        url += `&collection=${encodeURIComponent(collection)}`;
    }
    
    try {
        const response = await fetch(url);
        const result = await response.json();
        
        if (result.status === 'success') {
            renderSlowQueriesTable(result.data);
        }
    } catch (error) {
        console.error('Error loading slow queries:', error);
    }
}

function renderSlowQueriesTable(queries) {
    const tbody = document.querySelector('#slow-queries-table tbody');
    tbody.innerHTML = '';
    
    queries.forEach(query => {
        const row = document.createElement('tr');
        row.innerHTML = `
            <td><code>${escapeHtml(query.collection)}</code></td>
            <td>${escapeHtml(query.operation)}</td>
            <td><code class="small">${escapeHtml(JSON.stringify(query.query_shape).substring(0, 50))}...</code></td>
            <td class="${query.execution_time_ms > 1000 ? 'text-danger fw-bold' : ''}">${query.execution_time_ms.toFixed(2)}</td>
            <td>${new Date(query.timestamp).toLocaleString('he-IL')}</td>
            <td>
                <button class="btn btn-sm btn-outline-primary" onclick="analyzeQueryById('${query.collection}', ${JSON.stringify(JSON.stringify(query.query_shape))})">
                    🔍 נתח
                </button>
            </td>
        `;
        tbody.appendChild(row);
    });
}

function analyzeQueryById(collection, queryJson) {
    document.getElementById('analyze-collection').value = collection;
    document.getElementById('analyze-query').value = queryJson;
    analyzeQuery();
}

async function analyzeQuery() {
    const collection = document.getElementById('analyze-collection').value;
    const queryText = document.getElementById('analyze-query').value;
    
    if (!collection) {
        alert('נא להזין שם collection');
        return;
    }
    
    let query;
    try {
        query = queryText ? JSON.parse(queryText) : {};
    } catch (e) {
        alert('JSON לא תקין');
        return;
    }
    
    try {
        const response = await fetch('/api/profiler/recommendations', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ collection, query })
        });
        
        const result = await response.json();
        
        if (result.status === 'success') {
            document.getElementById('analysis-results').style.display = 'flex';
            renderExplainPlan(result.data.explain);
            renderRecommendations(result.data.recommendations);
        }
    } catch (error) {
        console.error('Error analyzing query:', error);
        alert('שגיאה בניתוח השאילתה');
    }
}

function renderExplainPlan(explain) {
    const container = document.getElementById('explain-plan-visual');
    container.innerHTML = '';
    
    // יצירת ויזואליזציה של שלבי הביצוע
    function renderStage(stage, depth = 0) {
        const stageClass = getStageClass(stage.stage);
        const html = `
            <div class="stage-node ${stageClass}" style="margin-left: ${depth * 20}px">
                <strong>${stage.stage}</strong>
                ${stage.index_name ? `<br><small>Index: ${stage.index_name}</small>` : ''}
                ${stage.filter_condition ? `<br><small>Filter: ${JSON.stringify(stage.filter_condition).substring(0, 30)}...</small>` : ''}
            </div>
        `;
        
        let result = html;
        
        if (stage.input_stage) {
            result += '<div class="stage-connector"></div>';
            result += renderStage(stage.input_stage, depth);
        }
        
        stage.children.forEach(child => {
            result += '<div class="stage-connector"></div>';
            result += renderStage(child, depth + 1);
        });
        
        return result;
    }
    
    container.innerHTML = renderStage(explain.winning_plan);
    
    // סטטיסטיקות
    const statsContainer = document.getElementById('explain-stats');
    if (explain.stats) {
        const stats = explain.stats;
        const efficiencyClass = stats.efficiency_ratio < 0.1 ? 'text-danger' : 
                               stats.efficiency_ratio < 0.5 ? 'text-warning' : 'text-success';
        
        statsContainer.innerHTML = `
            <table class="table table-sm">
                <tr><td>זמן ביצוע</td><td><strong>${stats.execution_time_ms} ms</strong></td></tr>
                <tr><td>מסמכים שנסרקו</td><td>${stats.docs_examined.toLocaleString()}</td></tr>
                <tr><td>מסמכים שהוחזרו</td><td>${stats.docs_returned.toLocaleString()}</td></tr>
                <tr><td>מפתחות שנסרקו</td><td>${stats.keys_examined.toLocaleString()}</td></tr>
                <tr><td>אינדקס בשימוש</td><td>${stats.index_used || '<span class="text-danger">אין</span>'}</td></tr>
                <tr><td>Covered Query</td><td>${stats.is_covered_query ? '✅' : '❌'}</td></tr>
                <tr><td>יחס יעילות</td><td class="${efficiencyClass}"><strong>${(stats.efficiency_ratio * 100).toFixed(1)}%</strong></td></tr>
            </table>
        `;
    }
}

function getStageClass(stage) {
    switch (stage) {
        case 'COLLSCAN': return 'stage-collscan';
        case 'IXSCAN': return 'stage-ixscan';
        case 'FETCH': return 'stage-fetch';
        case 'SORT': return 'stage-sort';
        default: return 'stage-default';
    }
}

function renderRecommendations(recommendations) {
    const container = document.getElementById('recommendations-list');
    
    if (recommendations.length === 0) {
        container.innerHTML = '<div class="alert alert-success">✅ לא נמצאו בעיות - השאילתה נראית מיטבית!</div>';
        return;
    }
    
    container.innerHTML = recommendations.map(rec => `
        <div class="recommendation-card recommendation-${rec.severity}">
            <h6>${rec.title}</h6>
            <p>${rec.description}</p>
            <p><strong>פעולה מומלצת:</strong> ${rec.suggested_action}</p>
            <p><small>שיפור משוער: ${rec.estimated_improvement}</small></p>
            ${rec.code_example ? `<pre class="code-example">${escapeHtml(rec.code_example)}</pre>` : ''}
            ${rec.documentation_link ? `<a href="${rec.documentation_link}" target="_blank" class="btn btn-sm btn-outline-info">📚 תיעוד</a>` : ''}
        </div>
    `).join('');
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// רענון אוטומטי כל 30 שניות
setInterval(loadSummary, 30000);
</script>
{% endblock %}
```

---

## אבטחה

### הגנה על נקודות הקצה

```python
# handlers/profiler_handler.py - תוספת אבטחה

import hmac
import os
from functools import wraps
from aiohttp import web


def require_profiler_auth(handler):
    """
    Middleware לאימות גישה לפרופיילר.
    
    אפשרויות:
    1. Token באמצעות header
    2. הגבלת IP
    3. Basic Auth
    """
    @wraps(handler)
    async def wrapper(request: web.Request) -> web.Response:
        # בדיקת token
        auth_token = os.environ.get("PROFILER_AUTH_TOKEN")
        if auth_token:
            provided_token = request.headers.get("X-Profiler-Token", "")
            if not hmac.compare_digest(provided_token, auth_token):
                return web.json_response(
                    {"status": "error", "message": "Unauthorized"},
                    status=401
                )
        
        # הגבלת IP (אופציונלי)
        allowed_ips = os.environ.get("PROFILER_ALLOWED_IPS", "").split(",")
        if allowed_ips and allowed_ips[0]:  # רק אם מוגדר
            client_ip = request.remote
            if client_ip not in allowed_ips:
                return web.json_response(
                    {"status": "error", "message": "IP not allowed"},
                    status=403
                )
        
        return await handler(request)
    
    return wrapper


# שימוש:
@require_profiler_auth
async def get_slow_queries(request: web.Request) -> web.Response:
    # ...
    pass
```

### הגבלת קצב (Rate Limiting)

```python
from collections import defaultdict
from datetime import datetime, timedelta


class RateLimiter:
    """הגבלת קצב בקשות לפרופיילר"""
    
    def __init__(self, requests_per_minute: int = 60):
        self.requests_per_minute = requests_per_minute
        self._request_counts: Dict[str, List[datetime]] = defaultdict(list)
    
    def is_allowed(self, client_id: str) -> bool:
        now = datetime.utcnow()
        minute_ago = now - timedelta(minutes=1)
        
        # ניקוי בקשות ישנות
        self._request_counts[client_id] = [
            t for t in self._request_counts[client_id] if t > minute_ago
        ]
        
        # בדיקת מגבלה
        if len(self._request_counts[client_id]) >= self.requests_per_minute:
            return False
        
        self._request_counts[client_id].append(now)
        return True
```

---

## משתני סביבה

| משתנה | תיאור | ברירת מחדל |
|-------|-------|------------|
| `PROFILER_SLOW_THRESHOLD_MS` | סף זמן לשאילתה איטית | `100` |
| `PROFILER_MAX_BUFFER_SIZE` | מקסימום שאילתות בזיכרון | `1000` |
| `PROFILER_AUTH_TOKEN` | טוקן אימות | (ריק = ללא אימות) |
| `PROFILER_ALLOWED_IPS` | רשימת IP מורשים | (ריק = הכל מורשה) |
| `PROFILER_RATE_LIMIT` | בקשות לדקה | `60` |
| `PROFILER_ENABLED` | האם הפרופיילר פעיל | `true` |

### דוגמת קונפיגורציה

```bash
# .env או docker-compose.yml
PROFILER_SLOW_THRESHOLD_MS=100
PROFILER_MAX_BUFFER_SIZE=1000
PROFILER_AUTH_TOKEN=your-secret-token
PROFILER_ALLOWED_IPS=127.0.0.1,10.0.0.1
PROFILER_RATE_LIMIT=60
PROFILER_ENABLED=true
```

---

## בדיקות יחידה

### מבנה הבדיקות

```python
# tests/test_query_profiler_service.py

import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from services.query_profiler_service import (
    QueryProfilerService,
    QueryStage,
    SeverityLevel,
    ExplainPlan,
    ExplainStage,
    QueryStats,
    SlowQueryRecord,
    OptimizationRecommendation
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
    return QueryProfilerService(
        db_manager=mock_db_manager,
        slow_threshold_ms=100
    )


class TestQueryProfilerService:
    """בדיקות לשירות הפרופיילר"""
    
    @pytest.mark.asyncio
    async def test_record_slow_query(self, profiler_service):
        """בדיקת רישום שאילתה איטית"""
        record = await profiler_service.record_slow_query(
            collection="test_collection",
            operation="find",
            query={"user_id": "123"},
            execution_time_ms=250.5
        )
        
        assert record.collection == "test_collection"
        assert record.operation == "find"
        assert record.execution_time_ms == 250.5
        assert record.query_id is not None
    
    @pytest.mark.asyncio
    async def test_get_slow_queries_with_filter(self, profiler_service):
        """בדיקת קבלת שאילתות עם סינון"""
        # רישום שאילתות
        await profiler_service.record_slow_query(
            collection="users", operation="find",
            query={"name": "test"}, execution_time_ms=200
        )
        await profiler_service.record_slow_query(
            collection="snippets", operation="find",
            query={"code": "test"}, execution_time_ms=300
        )
        
        # סינון לפי collection
        queries = await profiler_service.get_slow_queries(
            collection_filter="users"
        )
        
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
    async def test_generate_query_id_consistency(self, profiler_service):
        """בדיקת עקביות יצירת מזהה שאילתה"""
        query1 = {"a": 1, "b": 2}
        query2 = {"b": 2, "a": 1}  # סדר שונה
        
        id1 = profiler_service._generate_query_id("test", query1)
        id2 = profiler_service._generate_query_id("test", query2)
        
        assert id1 == id2  # צריך להיות זהה
    
    def test_has_collscan_detection(self, profiler_service):
        """בדיקת זיהוי COLLSCAN"""
        # שלב עם COLLSCAN
        collscan_stage = ExplainStage(stage=QueryStage.COLLSCAN)
        assert profiler_service._has_collscan(collscan_stage) is True
        
        # שלב עם IXSCAN
        ixscan_stage = ExplainStage(stage=QueryStage.IXSCAN)
        assert profiler_service._has_collscan(ixscan_stage) is False
        
        # שלב מקונן עם COLLSCAN
        nested_stage = ExplainStage(
            stage=QueryStage.FETCH,
            input_stage=ExplainStage(stage=QueryStage.COLLSCAN)
        )
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
                keys_examined=0
            )
        )
        
        recommendations = await profiler_service.analyze_and_recommend(explain_plan)
        
        # צריכה להיות לפחות המלצת COLLSCAN
        collscan_rec = next(
            (r for r in recommendations if "COLLSCAN" in r.title),
            None
        )
        assert collscan_rec is not None
        assert collscan_rec.severity == SeverityLevel.CRITICAL
    
    @pytest.mark.asyncio
    async def test_efficiency_recommendation(self, profiler_service):
        """בדיקת המלצה ליחס יעילות נמוך"""
        explain_plan = ExplainPlan(
            query_id="test456",
            collection="test_collection",
            query_shape={"field1": "<value>"},
            winning_plan=ExplainStage(
                stage=QueryStage.FETCH,
                input_stage=ExplainStage(stage=QueryStage.IXSCAN)
            ),
            stats=QueryStats(
                execution_time_ms=200,
                docs_examined=10000,
                docs_returned=5,  # יחס יעילות 0.05%
                keys_examined=10000
            )
        )
        
        recommendations = await profiler_service.analyze_and_recommend(explain_plan)
        
        efficiency_rec = next(
            (r for r in recommendations if "יעילות" in r.title),
            None
        )
        assert efficiency_rec is not None


class TestExplainPlanParsing:
    """בדיקות לפרסור Explain Plans"""
    
    def test_parse_simple_stage(self, profiler_service):
        """בדיקת פרסור שלב פשוט"""
        stage_data = {
            "stage": "IXSCAN",
            "indexName": "user_id_1",
            "direction": "forward"
        }
        
        stage = profiler_service._parse_stage(stage_data)
        
        assert stage.stage == QueryStage.IXSCAN
        assert stage.index_name == "user_id_1"
        assert stage.direction == "forward"
    
    def test_parse_nested_stages(self, profiler_service):
        """בדיקת פרסור שלבים מקוננים"""
        stage_data = {
            "stage": "FETCH",
            "inputStage": {
                "stage": "IXSCAN",
                "indexName": "idx_test"
            }
        }
        
        stage = profiler_service._parse_stage(stage_data)
        
        assert stage.stage == QueryStage.FETCH
        assert stage.input_stage is not None
        assert stage.input_stage.stage == QueryStage.IXSCAN


class TestRateLimiting:
    """בדיקות להגבלת קצב"""
    
    def test_rate_limiter_allows_within_limit(self):
        """בדיקה שמאפשר בקשות בתוך המגבלה"""
        from services.query_profiler_service import RateLimiter
        
        limiter = RateLimiter(requests_per_minute=5)
        
        for i in range(5):
            assert limiter.is_allowed("client1") is True
        
        # בקשה שישית צריכה להיחסם
        assert limiter.is_allowed("client1") is False
    
    def test_rate_limiter_different_clients(self):
        """בדיקה שלקוחות שונים נספרים בנפרד"""
        from services.query_profiler_service import RateLimiter
        
        limiter = RateLimiter(requests_per_minute=2)
        
        assert limiter.is_allowed("client1") is True
        assert limiter.is_allowed("client1") is True
        assert limiter.is_allowed("client1") is False  # נחסם
        
        assert limiter.is_allowed("client2") is True  # לקוח אחר עדיין מותר
```

---

## אינטגרציה עם Observability

### מטריקות Prometheus

```python
# monitoring/profiler_metrics.py

from prometheus_client import Counter, Histogram, Gauge

# מטריקות
SLOW_QUERIES_TOTAL = Counter(
    'mongodb_slow_queries_total',
    'Total number of slow queries',
    ['collection', 'operation']
)

QUERY_DURATION = Histogram(
    'mongodb_query_duration_seconds',
    'Query duration in seconds',
    ['collection', 'operation'],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]
)

COLLSCAN_DETECTED = Counter(
    'mongodb_collscan_detected_total',
    'Number of COLLSCAN operations detected',
    ['collection']
)

ACTIVE_PROFILER_BUFFER_SIZE = Gauge(
    'query_profiler_buffer_size',
    'Current number of queries in profiler buffer'
)


# שימוש בשירות:
async def record_slow_query_with_metrics(self, ...):
    """רישום שאילתה עם עדכון מטריקות"""
    record = await self.record_slow_query(...)
    
    # עדכון מטריקות
    SLOW_QUERIES_TOTAL.labels(
        collection=record.collection,
        operation=record.operation
    ).inc()
    
    QUERY_DURATION.labels(
        collection=record.collection,
        operation=record.operation
    ).observe(record.execution_time_ms / 1000)
    
    ACTIVE_PROFILER_BUFFER_SIZE.set(len(self._slow_queries))
    
    return record
```

### לוגים מובנים

```python
# שימוש ב-emit_event הקיים במערכת

from src.event_logger import emit_event

async def record_slow_query(self, ...):
    record = await super().record_slow_query(...)
    
    emit_event(
        event_type="slow_query_detected",
        data={
            "query_id": record.query_id,
            "collection": record.collection,
            "operation": record.operation,
            "execution_time_ms": record.execution_time_ms,
            "query_shape": record.query_shape
        },
        severity="warning"
    )
    
    return record
```

---

## טיפים לפתרון בעיות

### בעיה: שאילתות לא נרשמות

**סימפטומים:** הפרופיילר לא מציג שאילתות איטיות

**פתרונות:**
1. ודא שסף הזמן (`PROFILER_SLOW_THRESHOLD_MS`) מוגדר נכון
2. בדוק שה-CommandListener רשום נכון ב-`DatabaseManager`
3. ודא שהפרופיילר פעיל (`PROFILER_ENABLED=true`)

### בעיה: Explain Plan נכשל

**סימפטומים:** שגיאת timeout או authorization

**פתרונות:**
1. ודא הרשאות מתאימות למשתמש MongoDB
2. הגדל את ה-timeout עבור explain
3. הקטן את גודל השאילתה

### בעיה: צריכת זיכרון גבוהה

**סימפטומים:** השירות צורך יותר מדי RAM

**פתרונות:**
1. הקטן את `PROFILER_MAX_BUFFER_SIZE`
2. הפעל cleanup תקופתי
3. שקול שמירה ל-MongoDB במקום בזיכרון

### בעיה: ביצועים איטיים של הפרופיילר עצמו

**סימפטומים:** ה-API של הפרופיילר מגיב לאט

**פתרונות:**
1. הוסף caching לתוצאות explain
2. הגבל את תדירות הרענון האוטומטי בדשבורד
3. השתמש ב-pagination בטבלאות

---

## סיכום ושלבים הבאים

### צ'קליסט מימוש

- [ ] יצירת `services/query_profiler_service.py` עם כל ה-dataclasses
- [ ] הוספת מתודות לאיסוף וניתוח שאילתות
- [ ] מימוש פרסור Explain Plans
- [ ] יצירת מנוע המלצות
- [ ] הגדרת Routes API ב-`handlers/profiler_handler.py`
- [ ] יצירת תבנית HTML לדשבורד
- [ ] הוספת אבטחה (token, rate limiting)
- [ ] כתיבת בדיקות יחידה
- [ ] אינטגרציה עם מטריקות ולוגים
- [ ] תיעוד משתני סביבה

### הרחבות עתידיות

1. **שמירת היסטוריה** - שמירה ארוכת טווח של שאילתות ב-MongoDB
2. **התראות** - שליחת התראות על שאילתות קריטיות
3. **השוואת זמנים** - השוואת ביצועים לפני ואחרי שינויים
4. **ניתוח מגמות** - זיהוי שאילתות שמחמירות לאורך זמן
5. **אינטגרציה עם CI** - בדיקת ביצועי שאילתות ב-pipeline

---

## קישורים רלוונטיים

- [MongoDB Explain Documentation](https://www.mongodb.com/docs/manual/reference/command/explain/)
- [MongoDB Index Strategies](https://www.mongodb.com/docs/manual/applications/indexes/)
- [Query Optimization](https://www.mongodb.com/docs/manual/tutorial/analyze-query-plan/)
- [Database Health Dashboard Guide](./DATABASE_HEALTH_DASHBOARD_GUIDE.md)
- [Connection Pooling Guide](./GUIDE_CONNECTION_POOLING.md)

---

> 📝 **הערה:** מדריך זה נכתב בהתאם לארכיטקטורה הקיימת של הפרויקט ומתבסס על התשתיות הקיימות ב-`database/manager.py`, `services/db_health_service.py` ו-`database/repository.py`.
