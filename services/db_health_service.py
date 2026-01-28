"""
Database Health Service - ניטור בריאות MongoDB (Async).

שימוש בפקודות ניהול מובנות: serverStatus, currentOp, collStats.
גרסה אסינכרונית עם Motor - מומלצת לשימוש עם aiohttp.

הקובץ כולל גם fallback לגרסה סינכרונית (PyMongo) עטופה ב-thread pool,
כדי למנוע חסימת event loop במקרה ש-Motor לא זמין.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

# Motor - async MongoDB driver
try:
    from motor.motor_asyncio import AsyncIOMotorClient

    MOTOR_AVAILABLE = True
except ImportError:  # pragma: no cover
    MOTOR_AVAILABLE = False
    AsyncIOMotorClient = None  # type: ignore

from bson import ObjectId
from bson.json_util import dumps as bson_dumps

logger = logging.getLogger(__name__)

# סף לזיהוי slow queries (באלפיות שנייה)
SLOW_QUERY_THRESHOLD_MS = int(os.getenv("DB_HEALTH_SLOW_THRESHOLD_MS", "1000"))

# מגבלות Pagination
DEFAULT_DOCUMENTS_LIMIT = 20
MAX_DOCUMENTS_LIMIT = 100
MAX_SKIP = 10000  # מניעת DoS - MongoDB skip סורק כל מסמך עד ה-offset

# ========== הגדרות אבטחה ==========

# רשימת collections מותרים לצפייה (None = הכל מותר)
# שנה לפי הצורך שלך!
ALLOWED_COLLECTIONS: Optional[Set[str]] = None
# דוגמה להגבלה: ALLOWED_COLLECTIONS = {"users", "logs", "snippets", "configs"}

# רשימת collections חסומים (אם ALLOWED_COLLECTIONS הוא None)
DENIED_COLLECTIONS: Set[str] = {
    "sessions",
    "tokens",
    "api_keys",
    "secrets",
}

# שדות רגישים שיוסתרו מהתצוגה (redaction)
SENSITIVE_FIELDS: Set[str] = {
    "password",
    "password_hash",
    "hashed_password",
    "token",
    "access_token",
    "refresh_token",
    "api_key",
    "apiKey",
    "secret",
    "secret_key",
    "private_key",
    "credentials",
}


@dataclass
class PoolStatus:
    """מצב Connection Pool."""

    current: int = 0  # חיבורים פעילים כרגע
    available: int = 0  # חיבורים זמינים ב-pool
    total_created: int = 0  # סה"כ חיבורים שנוצרו
    max_pool_size: int = 50  # מקסימום מוגדר
    wait_queue_size: int = 0  # ממתינים לחיבור
    utilization_pct: float = 0.0
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "current": self.current,
            "available": self.available,
            "total_created": self.total_created,
            "max_pool_size": self.max_pool_size,
            "wait_queue_size": self.wait_queue_size,
            "utilization_pct": round(self.utilization_pct, 1),
            "timestamp": self.timestamp,
            "status": self._health_status(),
        }

    def _health_status(self) -> str:
        """מחזיר סטטוס בריאות: healthy/warning/critical."""
        if self.utilization_pct >= 90 or self.wait_queue_size > 10:
            return "critical"
        if self.utilization_pct >= 70 or self.wait_queue_size > 0:
            return "warning"
        return "healthy"


@dataclass
class SlowOperation:
    """פעולה איטית פעילה."""

    op_id: str
    operation_type: str  # query, update, insert, command
    namespace: str  # db.collection
    running_secs: float
    query: Dict[str, Any]
    client_ip: str = ""
    description: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "op_id": self.op_id,
            "type": self.operation_type,
            "namespace": self.namespace,
            "running_secs": round(self.running_secs, 2),
            "running_ms": int(self.running_secs * 1000),
            "query": self.query,
            "client_ip": self.client_ip,
            "description": self.description,
            "severity": self._severity(),
        }

    def _severity(self) -> str:
        """קביעת חומרת האיטיות."""
        if self.running_secs >= 10:
            return "critical"
        if self.running_secs >= 5:
            return "warning"
        return "info"


@dataclass
class CollectionStat:
    """סטטיסטיקות collection."""

    name: str
    count: int = 0
    size_bytes: int = 0
    storage_size_bytes: int = 0
    index_count: int = 0
    total_index_size_bytes: int = 0
    avg_obj_size_bytes: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "count": self.count,
            "size_mb": round(self.size_bytes / (1024 * 1024), 2),
            "storage_size_mb": round(self.storage_size_bytes / (1024 * 1024), 2),
            "index_count": self.index_count,
            "total_index_size_mb": round(self.total_index_size_bytes / (1024 * 1024), 2),
            "avg_obj_size_kb": round(self.avg_obj_size_bytes / 1024, 2),
        }


# ========== Custom Exceptions ==========

class CollectionAccessDeniedError(Exception):
    """נזרקת כשגישה ל-collection חסומה."""
    pass


class InvalidCollectionNameError(Exception):
    """נזרקת כששם collection לא תקין."""
    pass


def _redact_sensitive_fields(doc: Any, sensitive: Set[str] = SENSITIVE_FIELDS) -> Any:
    """הסתרת שדות רגישים ממסמך (רקורסיבי מלא).
    
    מטפל ב:
    - מילונים (dict) - בודק מפתחות רגישים
    - רשימות (list) - רקורסיה על כל איבר (כולל רשימות מקוננות)
    - ערכים פשוטים - מחזיר כמו שהם
    
    Args:
        doc: המסמך/ערך המקורי
        sensitive: קבוצת שמות שדות להסתרה
        
    Returns:
        עותק עם שדות רגישים מוחלפים ב-"[REDACTED]"
    """
    # טיפול ברשימות - רקורסיה על כל איבר (כולל רשימות מקוננות!)
    if isinstance(doc, list):
        return [_redact_sensitive_fields(item, sensitive) for item in doc]
    
    # ערכים שאינם dict - החזר כמו שהם
    if not isinstance(doc, dict):
        return doc
    
    # טיפול במילון
    sensitive_lower = {s.lower() for s in sensitive}
    result = {}
    for key, value in doc.items():
        if key.lower() in sensitive_lower:
            result[key] = "[REDACTED]"
        else:
            # רקורסיה על הערך (יטפל ב-dict, list, או יחזיר כמו שהוא)
            result[key] = _redact_sensitive_fields(value, sensitive)
    return result


def clean_db_health_filter_value(value: Any, max_len: int = 120) -> str:
    if value is None:
        return ""
    try:
        text = str(value).strip()
    except Exception:
        return ""
    if not text:
        return ""
    return text[:max_len]


def _iso_from_millis(value: Any) -> Any:
    """המרת millis מאז epoch ל-ISO 8601 (UTC), best-effort."""
    try:
        millis = int(value)
    except Exception:
        return value
    try:
        return datetime.fromtimestamp(millis / 1000.0, tz=timezone.utc).isoformat()
    except Exception:
        return value


def _normalize_extended_date(value: Any) -> Any:
    """המרת Extended JSON date לערך ISO string."""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        return _iso_from_millis(value)
    if isinstance(value, dict):
        number_val = value.get("$numberLong")
        if number_val is not None:
            return _iso_from_millis(number_val)
    return value


def _flatten_extended_json(value: Any) -> Any:
    """המרת Extended JSON לפורמט קריא (ללא $oid/$date)."""
    if isinstance(value, list):
        return [_flatten_extended_json(item) for item in value]
    if not isinstance(value, dict):
        return value
    if len(value) == 1:
        if "$oid" in value:
            return value.get("$oid")
        if "$date" in value:
            return _normalize_extended_date(value.get("$date"))
    return {key: _flatten_extended_json(val) for key, val in value.items()}


def _build_documents_sort(sort: Optional[str]) -> List[Tuple[str, int]]:
    """בניית sort spec בטוח למסמכי DB Health."""
    try:
        raw = str(sort or "").strip().lower()
    except Exception:
        raw = ""
    if raw in {"oldest", "asc", "created_at_asc"}:
        return [("created_at", 1), ("_id", 1)]
    if raw in {"newest", "desc", "created_at_desc"}:
        return [("created_at", -1), ("_id", -1)]
    return [("created_at", -1), ("_id", -1)]


def _validate_collection_name(name: str) -> None:
    """וולידציה של שם collection.
    
    MongoDB naming rules:
    - לא יכול להתחיל ב-$ או להכיל \0
    - לא יכול להיות ריק
    - מומלץ להימנע מ-.. או תווים מיוחדים
    
    Raises:
        InvalidCollectionNameError: אם השם לא תקין
        CollectionAccessDeniedError: אם הגישה חסומה
    """
    if not name or not isinstance(name, str):
        raise InvalidCollectionNameError("Collection name cannot be empty")
    
    # תווים אסורים ב-MongoDB
    if name.startswith("$"):
        raise InvalidCollectionNameError("Collection name cannot start with $")
    if "\0" in name or ".." in name:
        raise InvalidCollectionNameError("Collection name contains invalid characters")
    
    # הגבלת אורך סבירה
    if len(name) > 120:
        raise InvalidCollectionNameError("Collection name too long")
    
    # בדיקת whitelist/denylist
    if ALLOWED_COLLECTIONS is not None:
        if name not in ALLOWED_COLLECTIONS:
            raise CollectionAccessDeniedError(f"Access to collection '{name}' is not allowed")
    elif name in DENIED_COLLECTIONS:
        raise CollectionAccessDeniedError(f"Access to collection '{name}' is denied")


def _is_permission_error(e: Exception) -> bool:
    """בדיקה אם השגיאה היא שגיאת הרשאה (לא קריטית).
    
    פקודות admin כמו serverStatus ו-currentOp דורשות הרשאות מיוחדות
    (clusterMonitor role). אם המשתמש לא מורשה, זו לא שגיאה קריטית.
    """
    error_str = str(e).lower()
    permission_indicators = [
        "not authorized",
        "unauthorized",
        "permission denied",
        "requires authentication",
        "command serverstatus requires authentication",
        "command currentop requires authentication",
    ]
    return any(indicator in error_str for indicator in permission_indicators)


class AsyncDatabaseHealthService:
    """שירות ניטור בריאות MongoDB - גרסה אסינכרונית.

    משתמש ב-Motor (AsyncIOMotorClient) לגישה non-blocking ל-MongoDB.
    מתאים לשימוש עם aiohttp ו-asyncio.

    Usage:
        svc = AsyncDatabaseHealthService()
        await svc.connect()
        pool_status = await svc.get_pool_status()
    """

    def __init__(self, mongo_url: Optional[str] = None, database_name: Optional[str] = None):
        """
        Args:
            mongo_url: MongoDB connection string (או מ-ENV: MONGODB_URL)
            database_name: שם ה-database (או מ-ENV: DATABASE_NAME)
        """
        if not MOTOR_AVAILABLE:
            raise RuntimeError("Motor is not installed. Run: pip install motor")

        self._mongo_url = mongo_url or os.getenv("MONGODB_URL")
        self._db_name = database_name or os.getenv("DATABASE_NAME", "code_keeper_bot")
        self._client: Optional[AsyncIOMotorClient] = None
        self._db = None

    async def connect(self) -> None:
        """יצירת חיבור ל-MongoDB."""
        if not self._mongo_url:
            raise RuntimeError("MONGODB_URL is not configured")

        self._client = AsyncIOMotorClient(self._mongo_url)
        self._db = self._client[self._db_name]

        # בדיקת חיבור
        await self._client.admin.command("ping")
        logger.info("AsyncDatabaseHealthService connected to MongoDB")

    async def close(self) -> None:
        """סגירת החיבור."""
        if self._client:
            self._client.close()
            self._client = None
            self._db = None

    async def get_pool_status(self) -> PoolStatus:
        """שליפת מצב Connection Pool באמצעות serverStatus.

        Returns:
            PoolStatus עם פרטי ה-pool הנוכחיים.

        Raises:
            RuntimeError: אם אין חיבור פעיל למסד.
        """
        if self._client is None:
            raise RuntimeError("No MongoDB client available - call connect() first")

        try:
            # await חובה! - Motor הוא אסינכרוני
            status = await self._client.admin.command("serverStatus")
            connections = status.get("connections", {})

            current = int(connections.get("current", 0))
            available = int(connections.get("available", 0))
            total_created = int(connections.get("totalCreated", 0))

            # חישוב ניצולת
            max_pool = current + available
            if max_pool > 0:
                utilization = (current / max_pool) * 100
            else:
                utilization = 0.0

            return PoolStatus(
                current=current,
                available=available,
                total_created=total_created,
                max_pool_size=max_pool,
                wait_queue_size=0,  # Motor לא חושף את זה ישירות
                utilization_pct=utilization,
            )

        except Exception as e:
            logger.error(f"Failed to get pool status: {e}")
            raise RuntimeError(f"serverStatus failed: {e}") from e

    async def get_current_operations(
        self,
        threshold_ms: int = SLOW_QUERY_THRESHOLD_MS,
        include_system: bool = False,
    ) -> List[SlowOperation]:
        """זיהוי פעולות איטיות באמצעות currentOp.

        Args:
            threshold_ms: סף מינימלי באלפיות שנייה (ברירת מחדל: 1000ms = 1 שנייה)
            include_system: האם לכלול פעולות מערכת פנימיות

        Returns:
            רשימת SlowOperation ממוינת לפי זמן ריצה (הארוך ביותר קודם).
        """
        if self._client is None:
            raise RuntimeError("No MongoDB client available - call connect() first")

        try:
            threshold_secs = threshold_ms / 1000.0

            # await חובה! - currentOp אסינכרוני
            result = await self._client.admin.command("currentOp", {"$all": True})

            slow_ops: List[SlowOperation] = []

            for op in result.get("inprog", []):
                # דילוג על פעולות מערכת אם לא התבקש
                if not include_system:
                    ns = op.get("ns", "")
                    if ns.startswith("admin.") or ns.startswith("local.") or ns.startswith("config."):
                        continue
                    if op.get("desc", "").startswith("conn") and op.get("op") == "none":
                        continue

                # חישוב זמן ריצה
                secs_running = op.get("secs_running", 0)
                microsecs = op.get("microsecs_running", 0)
                if microsecs and not secs_running:
                    secs_running = microsecs / 1_000_000

                # סינון לפי סף
                if secs_running < threshold_secs:
                    continue

                # חילוץ פרטי השאילתה
                command = op.get("command", {})
                query = command.get("filter", command.get("query", command))

                slow_ops.append(
                    SlowOperation(
                        op_id=str(op.get("opid", "")),
                        operation_type=op.get("op", "unknown"),
                        namespace=op.get("ns", "unknown"),
                        running_secs=float(secs_running),
                        query=query if isinstance(query, dict) else {"raw": str(query)},
                        client_ip=op.get("client_s", op.get("client", "")),
                        description=op.get("desc", ""),
                    )
                )

            # מיון לפי זמן ריצה (הארוך ביותר קודם)
            slow_ops.sort(key=lambda x: x.running_secs, reverse=True)

            return slow_ops

        except Exception as e:
            logger.error(f"Failed to get current operations: {e}")
            raise RuntimeError(f"currentOp failed: {e}") from e

    async def get_collection_stats(self, collection_name: Optional[str] = None) -> List[CollectionStat]:
        """שליפת סטטיסטיקות collections באמצעות collStats.

        Args:
            collection_name: שם collection ספציפי, או None לכל ה-collections.

        Returns:
            רשימת CollectionStat ממוינת לפי גודל (הגדול ביותר קודם).
        """
        if self._db is None:
            raise RuntimeError("No MongoDB database available - call connect() first")

        try:
            if collection_name:
                collections = [collection_name]
            else:
                # await חובה! - list_collection_names אסינכרוני
                collections = [name for name in await self._db.list_collection_names() if not name.startswith("system.")]

            stats: List[CollectionStat] = []

            for coll_name in collections:
                try:
                    # await חובה! - command אסינכרוני
                    result = await self._db.command("collStats", coll_name)

                    stats.append(
                        CollectionStat(
                            name=coll_name,
                            count=int(result.get("count", 0)),
                            size_bytes=int(result.get("size", 0)),
                            storage_size_bytes=int(result.get("storageSize", 0)),
                            index_count=int(result.get("nindexes", 0)),
                            total_index_size_bytes=int(result.get("totalIndexSize", 0)),
                            avg_obj_size_bytes=int(result.get("avgObjSize", 0)),
                        )
                    )
                except Exception as e:
                    logger.warning(f"Failed to get stats for {coll_name}: {e}")
                    continue

            # מיון לפי גודל (הגדול ביותר קודם)
            stats.sort(key=lambda x: x.size_bytes, reverse=True)

            return stats

        except Exception as e:
            logger.error(f"Failed to get collection stats: {e}")
            raise RuntimeError(f"collStats failed: {e}") from e

    async def get_documents(
        self,
        collection_name: str,
        skip: int = 0,
        limit: int = DEFAULT_DOCUMENTS_LIMIT,
        redact_sensitive: bool = True,
        filters: Optional[Dict[str, Any]] = None,
        sort: Optional[str] = None,
    ) -> Dict[str, Any]:
        """שליפת מסמכים מ-collection עם pagination.

        Args:
            collection_name: שם ה-collection
            skip: כמה מסמכים לדלג (ברירת מחדל: 0)
            limit: כמה מסמכים להחזיר (ברירת מחדל: 20, מקסימום: 100)
            redact_sensitive: האם להסתיר שדות רגישים (ברירת מחדל: True)
            filters: פילטרים אופציונליים (למשל user_id/status/file_id)
            sort: מיון אופציונלי (newest/oldest)

        Returns:
            מילון עם:
            - collection: שם ה-collection
            - documents: רשימת המסמכים (כ-JSON-serializable dicts)
            - total: סה"כ מסמכים ב-collection
            - skip: ה-skip שהתקבל
            - limit: ה-limit שהתקבל
            - has_more: האם יש עוד מסמכים אחרי
            - returned_count: כמה מסמכים הוחזרו בפועל

        Raises:
            RuntimeError: אם אין חיבור פעיל למסד
            InvalidCollectionNameError: אם שם ה-collection לא תקין
            CollectionAccessDeniedError: אם הגישה ל-collection חסומה
        """
        if self._db is None:
            raise RuntimeError("No MongoDB database available - call connect() first")

        # וולידציה של שם ה-collection (כולל whitelist/denylist)
        _validate_collection_name(collection_name)

        # הגבלת limit ו-skip למניעת עומס/DoS
        limit = min(max(1, limit), MAX_DOCUMENTS_LIMIT)
        skip = min(max(0, skip), MAX_SKIP)  # ⚠️ הגבלה עליונה למניעת DoS

        try:
            collection = self._db[collection_name]
            query: Dict[str, Any] = dict(filters) if isinstance(filters, dict) else {}
            sort_spec = _build_documents_sort(sort)

            # ספירת סה"כ מסמכים
            # הערה: count_documents({}) יחזיר 0 אם ה-collection לא קיים (זה בסדר)
            total = await collection.count_documents(query)

            # שליפת מסמכים עם pagination + SORT לדטרמיניזם!
            # ⚠️ חשוב: מיון לפי created_at ואז _id מבטיח סדר עקבי בין עמודים
            cursor = collection.find(query).sort(sort_spec).skip(skip).limit(limit)
            documents = await cursor.to_list(length=limit)

            # המרת ObjectId ו-datetime לפורמט JSON-safe
            serialized = json.loads(bson_dumps(documents))
            serialized = _flatten_extended_json(serialized)

            # הסתרת שדות רגישים
            if redact_sensitive:
                serialized = [_redact_sensitive_fields(doc) for doc in serialized]

            # ⚠️ חישוב has_more: בודקים אם קיבלנו עמוד מלא
            # זה יותר אמין מ-(skip + len) < total כי count יכול להשתנות
            # בין הקריאה ל-count_documents לבין ה-find
            has_more = len(documents) == limit

            return {
                "collection": collection_name,
                "documents": serialized,
                "total": total,
                "skip": skip,
                "limit": limit,
                "has_more": has_more,
                "returned_count": len(documents),
            }

        except Exception as e:
            logger.error(f"Failed to get documents from {collection_name}: {e}")
            raise RuntimeError(f"get_documents failed: {e}") from e

    async def get_health_summary(self) -> Dict[str, Any]:
        """סיכום בריאות כללי לדשבורד.

        מבחין בין שגיאות קריטיות (אין חיבור ל-DB) לבין שגיאות הרשאה
        (פקודות admin לא זמינות) כדי להציג סטטוס מדויק יותר.

        Returns:
            מילון עם כל המטריקות הקריטיות.
        """
        summary: Dict[str, Any] = {
            "timestamp": time.time(),
            "status": "unknown",
            "pool": None,
            "slow_queries_count": 0,
            "collections_count": 0,
            "errors": [],
            "warnings": [],  # שגיאות לא קריטיות (הרשאות)
        }

        has_critical_error = False
        has_permission_error = False

        # בדיקת חיבור בסיסי
        if self._client is None:
            summary["errors"].append("no_client: MongoDB client not available")
            has_critical_error = True
        elif self._db is None:
            summary["errors"].append("no_db: MongoDB database not available")
            has_critical_error = True

        # Pool status
        if not has_critical_error:
            try:
                pool = await self.get_pool_status()
                summary["pool"] = pool.to_dict()
            except Exception as e:
                if _is_permission_error(e):
                    summary["warnings"].append("pool: serverStatus requires clusterMonitor role")
                    has_permission_error = True
                else:
                    summary["errors"].append(f"pool: {e}")
                    has_critical_error = True

        # Slow queries count
        if not has_critical_error:
            try:
                ops = await self.get_current_operations()
                summary["slow_queries_count"] = len(ops)
            except Exception as e:
                if _is_permission_error(e):
                    summary["warnings"].append("ops: currentOp requires inprog privilege")
                    has_permission_error = True
                else:
                    summary["errors"].append(f"ops: {e}")
                    has_critical_error = True

        # Collections count
        if not has_critical_error:
            try:
                if self._db is not None:
                    coll_names = await self._db.list_collection_names()
                    summary["collections_count"] = len([n for n in coll_names if not n.startswith("system.")])
            except Exception as e:
                if _is_permission_error(e):
                    summary["warnings"].append("collections: list_collection_names failed")
                    has_permission_error = True
                else:
                    summary["errors"].append(f"collections: {e}")
                    has_critical_error = True

        # קביעת סטטוס כללי
        if has_critical_error:
            summary["status"] = "error"
        elif (summary.get("pool") or {}).get("status") == "critical":
            summary["status"] = "critical"
        elif summary["slow_queries_count"] > 5:
            summary["status"] = "warning"
        elif (summary.get("pool") or {}).get("status") == "warning":
            summary["status"] = "warning"
        elif has_permission_error:
            summary["status"] = "healthy"
        else:
            summary["status"] = "healthy"

        return summary


# Singleton instance לשימוש גלובלי עם הגנה מפני race condition
_async_health_service: Optional[AsyncDatabaseHealthService] = None
_async_health_service_lock: asyncio.Lock = asyncio.Lock()


async def get_async_db_health_service() -> AsyncDatabaseHealthService:
    """מחזיר את ה-singleton של AsyncDatabaseHealthService.

    משתמש ב-asyncio.Lock למניעת race condition בזמן אתחול.

    Usage:
        from services.db_health_service import get_async_db_health_service
        svc = await get_async_db_health_service()
        pool = await svc.get_pool_status()
    """
    global _async_health_service

    # בדיקה מהירה לפני נעילה (double-checked locking)
    if _async_health_service is not None:
        return _async_health_service

    # נעילה למניעת race condition בזמן אתחול
    async with _async_health_service_lock:
        # בדיקה נוספת אחרי הנעילה
        if _async_health_service is not None:
            return _async_health_service

        # אתחול מלא בתוך הנעילה
        service = AsyncDatabaseHealthService()
        await service.connect()
        _async_health_service = service

    return _async_health_service


class SyncDatabaseHealthService:
    """גרסה סינכרונית (PyMongo) - פנימית."""

    def __init__(self, db_manager):
        self.db_manager = db_manager

    @property
    def _client(self):
        # תמיכה גם ב-class attributes וגם ב-instance attributes
        client = getattr(self.db_manager, "client", None)
        if client is None and hasattr(self.db_manager, "__class__"):
            client = getattr(self.db_manager.__class__, "client", None)
        return client

    @property
    def _db(self):
        # תמיכה גם ב-class attributes וגם ב-instance attributes
        db = getattr(self.db_manager, "db", None)
        if db is None and hasattr(self.db_manager, "__class__"):
            db = getattr(self.db_manager.__class__, "db", None)
        return db

    def _is_permission_error(self, e: Exception) -> bool:
        """בדיקה אם השגיאה היא שגיאת הרשאה (לא קריטית)."""
        return _is_permission_error(e)

    def get_pool_status_sync(self) -> PoolStatus:
        """גרסה סינכרונית - לא לקרוא ישירות מ-aiohttp!"""
        client = self._client
        if client is None:
            raise RuntimeError("No MongoDB client available")

        status = client.admin.command("serverStatus")
        connections = status.get("connections", {})

        current = int(connections.get("current", 0))
        available = int(connections.get("available", 0))
        total_created = int(connections.get("totalCreated", 0))

        max_pool = current + available
        utilization = (current / max_pool * 100) if max_pool > 0 else 0.0

        return PoolStatus(
            current=current,
            available=available,
            total_created=total_created,
            max_pool_size=max_pool,
            utilization_pct=utilization,
        )

    def get_pool_status(self) -> PoolStatus:
        """Alias סינכרוני לשימוש ב-WebApp."""
        return self.get_pool_status_sync()

    def get_current_operations_sync(
        self,
        threshold_ms: int = SLOW_QUERY_THRESHOLD_MS,
        include_system: bool = False,
    ) -> List[SlowOperation]:
        """גרסה סינכרונית - לא לקרוא ישירות מ-aiohttp!"""
        client = self._client
        if client is None:
            raise RuntimeError("No MongoDB client available")

        threshold_secs = threshold_ms / 1000.0
        result = client.admin.command("currentOp", {"$all": True})

        slow_ops: List[SlowOperation] = []
        for op in result.get("inprog", []):
            if not include_system:
                ns = op.get("ns", "")
                if ns.startswith(("admin.", "local.", "config.")):
                    continue
                if op.get("desc", "").startswith("conn") and op.get("op") == "none":
                    continue

            secs_running = op.get("secs_running", 0) or (op.get("microsecs_running", 0) / 1_000_000)
            if secs_running < threshold_secs:
                continue

            command = op.get("command", {})
            query = command.get("filter", command.get("query", command))

            slow_ops.append(
                SlowOperation(
                    op_id=str(op.get("opid", "")),
                    operation_type=op.get("op", "unknown"),
                    namespace=op.get("ns", "unknown"),
                    running_secs=float(secs_running),
                    query=query if isinstance(query, dict) else {"raw": str(query)},
                    client_ip=op.get("client_s", op.get("client", "")),
                    description=op.get("desc", ""),
                )
            )

        slow_ops.sort(key=lambda x: x.running_secs, reverse=True)
        return slow_ops

    def get_current_operations(
        self,
        threshold_ms: int = SLOW_QUERY_THRESHOLD_MS,
        include_system: bool = False,
    ) -> List[SlowOperation]:
        """Alias סינכרוני לשימוש ב-WebApp."""
        return self.get_current_operations_sync(threshold_ms=threshold_ms, include_system=include_system)

    def get_collection_stats_sync(self, collection_name: Optional[str] = None) -> List[CollectionStat]:
        """גרסה סינכרונית - לא לקרוא ישירות מ-aiohttp!"""
        db = self._db
        if db is None:
            raise RuntimeError("No MongoDB database available")

        if collection_name:
            collections = [collection_name]
        else:
            collections = [n for n in db.list_collection_names() if not n.startswith("system.")]

        stats: List[CollectionStat] = []
        for coll_name in collections:
            try:
                result = db.command("collStats", coll_name)
                stats.append(
                    CollectionStat(
                        name=coll_name,
                        count=int(result.get("count", 0)),
                        size_bytes=int(result.get("size", 0)),
                        storage_size_bytes=int(result.get("storageSize", 0)),
                        index_count=int(result.get("nindexes", 0)),
                        total_index_size_bytes=int(result.get("totalIndexSize", 0)),
                        avg_obj_size_bytes=int(result.get("avgObjSize", 0)),
                    )
                )
            except Exception as e:
                logger.warning(f"Failed to get stats for {coll_name}: {e}")

        stats.sort(key=lambda x: x.size_bytes, reverse=True)
        return stats

    def get_collection_stats(self, collection_name: Optional[str] = None) -> List[CollectionStat]:
        """Alias סינכרוני לשימוש ב-WebApp."""
        return self.get_collection_stats_sync(collection_name=collection_name)

    def get_health_summary(self) -> Dict[str, Any]:
        """סיכום בריאות כללי לדשבורד (סינכרוני).

        מבחין בין שגיאות קריטיות (אין חיבור ל-DB) לבין שגיאות הרשאה
        (פקודות admin לא זמינות) כדי להציג סטטוס מדויק יותר.
        """
        summary: Dict[str, Any] = {
            "timestamp": time.time(),
            "status": "unknown",
            "pool": None,
            "slow_queries_count": 0,
            "collections_count": 0,
            "errors": [],
            "warnings": [],  # שגיאות לא קריטיות (הרשאות)
        }

        has_critical_error = False
        has_permission_error = False

        # בדיקת חיבור בסיסי - אם נכשל, זו שגיאה קריטית
        if self._client is None:
            summary["errors"].append("no_client: MongoDB client not available")
            has_critical_error = True
        elif self._db is None:
            summary["errors"].append("no_db: MongoDB database not available")
            has_critical_error = True

        # בדיקת pool status
        if not has_critical_error:
            try:
                pool = self.get_pool_status_sync()
                summary["pool"] = pool.to_dict()
            except Exception as e:
                if self._is_permission_error(e):
                    summary["warnings"].append(f"pool: serverStatus requires clusterMonitor role")
                    has_permission_error = True
                else:
                    summary["errors"].append(f"pool: {e}")
                    has_critical_error = True

        # בדיקת slow queries
        if not has_critical_error:
            try:
                ops = self.get_current_operations_sync()
                summary["slow_queries_count"] = len(ops)
            except Exception as e:
                if self._is_permission_error(e):
                    summary["warnings"].append(f"ops: currentOp requires inprog privilege")
                    has_permission_error = True
                else:
                    summary["errors"].append(f"ops: {e}")
                    has_critical_error = True

        # ספירת collections - פעולה בסיסית שלא דורשת הרשאות מיוחדות
        if not has_critical_error:
            try:
                if self._db is not None:
                    coll_names = self._db.list_collection_names()
                    summary["collections_count"] = len([n for n in coll_names if not n.startswith("system.")])
            except Exception as e:
                if self._is_permission_error(e):
                    summary["warnings"].append(f"collections: list_collection_names failed")
                    has_permission_error = True
                else:
                    summary["errors"].append(f"collections: {e}")
                    has_critical_error = True

        # קביעת סטטוס כללי
        if has_critical_error:
            summary["status"] = "error"
        elif (summary.get("pool") or {}).get("status") == "critical":
            summary["status"] = "critical"
        elif summary["slow_queries_count"] > 5:
            summary["status"] = "warning"
        elif (summary.get("pool") or {}).get("status") == "warning":
            summary["status"] = "warning"
        elif has_permission_error:
            # אם יש רק שגיאות הרשאה, הסטטוס הוא "healthy" עם אזהרות
            summary["status"] = "healthy"
        else:
            summary["status"] = "healthy"

        return summary

    def get_documents_sync(
        self,
        collection_name: str,
        skip: int = 0,
        limit: int = DEFAULT_DOCUMENTS_LIMIT,
        redact_sensitive: bool = True,
        filters: Optional[Dict[str, Any]] = None,
        sort: Optional[str] = None,
    ) -> Dict[str, Any]:
        """גרסה סינכרונית - לא לקרוא ישירות מ-aiohttp!"""
        db = self._db
        if db is None:
            raise RuntimeError("No MongoDB database available")

        # וולידציה
        _validate_collection_name(collection_name)

        # הגבלת limit ו-skip למניעת עומס/DoS
        limit = min(max(1, limit), MAX_DOCUMENTS_LIMIT)
        skip = min(max(0, skip), MAX_SKIP)  # ⚠️ הגבלה עליונה

        try:
            collection = db[collection_name]
            query: Dict[str, Any] = dict(filters) if isinstance(filters, dict) else {}
            sort_spec = _build_documents_sort(sort)
            total = collection.count_documents(query)
            
            # ⚠️ חשוב: מיון לפי created_at ואז _id לדטרמיניזם!
            documents = list(collection.find(query).sort(sort_spec).skip(skip).limit(limit))

            # סריאליזציה
            serialized = json.loads(bson_dumps(documents))
            serialized = _flatten_extended_json(serialized)

            # הסתרת שדות רגישים
            if redact_sensitive:
                serialized = [_redact_sensitive_fields(doc) for doc in serialized]

            # ⚠️ חישוב has_more: בודקים אם קיבלנו עמוד מלא
            has_more = len(documents) == limit

            return {
                "collection": collection_name,
                "documents": serialized,
                "total": total,
                "skip": skip,
                "limit": limit,
                "has_more": has_more,
                "returned_count": len(documents),
            }
        except Exception as e:
            logger.error(f"Failed to get documents from {collection_name}: {e}")
            raise RuntimeError(f"get_documents failed: {e}") from e

    def get_documents(
        self,
        collection_name: str,
        skip: int = 0,
        limit: int = DEFAULT_DOCUMENTS_LIMIT,
        redact_sensitive: bool = True,
        filters: Optional[Dict[str, Any]] = None,
        sort: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Alias סינכרוני לשימוש ב-WebApp."""
        return self.get_documents_sync(
            collection_name=collection_name,
            skip=skip,
            limit=limit,
            redact_sensitive=redact_sensitive,
            filters=filters,
            sort=sort,
        )


class ThreadPoolDatabaseHealthService:
    """Async wrapper שמריץ PyMongo ב-thread pool.

    משתמש ב-asyncio.to_thread (Python 3.9+) או run_in_executor
    כדי להריץ קוד סינכרוני בלי לחסום את ה-event loop.

    Usage:
        from database import db_manager
        svc = ThreadPoolDatabaseHealthService(db_manager)
        pool = await svc.get_pool_status()  # לא חוסם!
    """

    def __init__(self, db_manager):
        self._sync_service = SyncDatabaseHealthService(db_manager)

    async def get_pool_status(self) -> PoolStatus:
        """שליפת מצב pool - רץ ב-thread pool."""
        return await asyncio.to_thread(self._sync_service.get_pool_status_sync)

    async def get_current_operations(
        self,
        threshold_ms: int = SLOW_QUERY_THRESHOLD_MS,
        include_system: bool = False,
    ) -> List[SlowOperation]:
        """שליפת פעולות איטיות - רץ ב-thread pool."""
        return await asyncio.to_thread(self._sync_service.get_current_operations_sync, threshold_ms, include_system)

    async def get_collection_stats(self, collection_name: Optional[str] = None) -> List[CollectionStat]:
        """שליפת סטטיסטיקות - רץ ב-thread pool."""
        return await asyncio.to_thread(self._sync_service.get_collection_stats_sync, collection_name)

    async def get_documents(
        self,
        collection_name: str,
        skip: int = 0,
        limit: int = DEFAULT_DOCUMENTS_LIMIT,
        redact_sensitive: bool = True,
        filters: Optional[Dict[str, Any]] = None,
        sort: Optional[str] = None,
    ) -> Dict[str, Any]:
        """שליפת מסמכים - רץ ב-thread pool."""
        return await asyncio.to_thread(
            self._sync_service.get_documents_sync,
            collection_name,
            skip,
            limit,
            redact_sensitive,
            filters,
            sort,
        )

    async def get_health_summary(self) -> Dict[str, Any]:
        """סיכום בריאות - רץ ב-thread pool.
        
        מאציל ל-SyncDatabaseHealthService.get_health_summary שכבר מכיל
        את כל הלוגיקה לטיפול בשגיאות הרשאה.
        """
        return await asyncio.to_thread(self._sync_service.get_health_summary)


# Factory function לבחירת הגרסה המתאימה עם הגנה מפני race condition
_health_service_instance = None
_health_service_lock = asyncio.Lock()


def _is_truthy_env(name: str) -> bool:
    val = os.getenv(name)
    if val is None:
        return False
    return str(val).strip().lower() in {"1", "true", "yes", "y", "on"}


def _db_health_disabled() -> bool:
    # NOTE: חשוב במיוחד לטסטים – כדי להימנע מ-timeout על ping ל-MongoDB בזמן import/startup.
    # קובץ tests/conftest.py כבר מגדיר DISABLE_DB=1 כברירת מחדל.
    if _is_truthy_env("DISABLE_DB"):
        return True
    if _is_truthy_env("DB_HEALTH_DISABLED"):
        return True
    if _is_truthy_env("TESTING"):
        return True
    # Pytest מספק ENV ייחודי בזמן ריצה – שימוש בו כ"רשת ביטחון"
    if os.getenv("PYTEST_CURRENT_TEST"):
        return True
    return False


class _NoopDatabaseHealthService:
    """שירות DB Health מושבת (למשל בטסטים).

    מחזיר תשובות "ריקות" מהר כדי למנוע IO חיצוני / timeouts.
    """

    async def close(self) -> None:
        return None

    async def get_pool_status(self) -> PoolStatus:
        return PoolStatus(current=0, available=0, total_created=0, max_pool_size=0, wait_queue_size=0, utilization_pct=0.0)

    async def get_current_operations(
        self,
        threshold_ms: int = SLOW_QUERY_THRESHOLD_MS,
        include_system: bool = False,
    ) -> List[SlowOperation]:
        return []

    async def get_collection_stats(self, collection_name: Optional[str] = None) -> List[CollectionStat]:
        return []

    async def get_documents(
        self,
        collection_name: str,
        skip: int = 0,
        limit: int = DEFAULT_DOCUMENTS_LIMIT,
        redact_sensitive: bool = True,
        filters: Optional[Dict[str, Any]] = None,
        sort: Optional[str] = None,
    ) -> Dict[str, Any]:
        _validate_collection_name(collection_name)
        limit = min(max(1, limit), MAX_DOCUMENTS_LIMIT)
        skip = min(max(0, skip), MAX_SKIP)
        return {
            "collection": collection_name,
            "documents": [],
            "total": 0,
            "skip": skip,
            "limit": limit,
            "has_more": False,
            "returned_count": 0,
        }

    async def get_health_summary(self) -> Dict[str, Any]:
        return {
            "timestamp": time.time(),
            "status": "disabled",
            "pool": None,
            "slow_queries_count": 0,
            "errors": ["disabled"],
            "warnings": [],
        }


async def get_db_health_service():
    """מחזיר את ה-service המתאים לפי הקונפיגורציה.

    משתמש ב-asyncio.Lock למניעת race condition בזמן אתחול.

    - אם Motor מותקן ו-MONGODB_URL מוגדר: AsyncDatabaseHealthService
    - אחרת: ThreadPoolDatabaseHealthService עם DatabaseManager הקיים
    """
    global _health_service_instance

    # מצב בדיקות / DISABLE_DB: לא מנסים להתחבר ל-MongoDB בכלל (מונע timeouts).
    if _db_health_disabled():
        if not isinstance(_health_service_instance, _NoopDatabaseHealthService):
            _health_service_instance = _NoopDatabaseHealthService()
        return _health_service_instance

    # בדיקה מהירה לפני נעילה (double-checked locking)
    if _health_service_instance is not None:
        return _health_service_instance

    # נעילה למניעת race condition
    async with _health_service_lock:
        # בדיקה נוספת אחרי הנעילה
        if _health_service_instance is not None:
            return _health_service_instance

        # נסה Motor קודם (מומלץ)
        try:
            # Validate import and configured URL
            if MOTOR_AVAILABLE and os.getenv("MONGODB_URL"):
                service = AsyncDatabaseHealthService()
                await service.connect()  # אתחול מלא בתוך הנעילה
                _health_service_instance = service
                logger.info("Using AsyncDatabaseHealthService (Motor)")
                return _health_service_instance
        except ImportError:  # pragma: no cover
            pass

        # Fallback ל-PyMongo עם thread pool
        try:
            from database import db_manager

            _health_service_instance = ThreadPoolDatabaseHealthService(db_manager)
            logger.info("Using ThreadPoolDatabaseHealthService (PyMongo)")
            return _health_service_instance
        except Exception as e:
            raise RuntimeError(f"Could not initialize health service: {e}") from e

