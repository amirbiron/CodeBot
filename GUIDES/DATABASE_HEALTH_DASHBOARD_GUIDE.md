# מדריך מימוש Database Health Dashboard

מסמך טכני למימוש דשבורד ניטור בריאות MongoDB במערכת Flask/aiohttp + PyMongo.  
הדשבורד מספק שקיפות מלאה לביצועי מסד הנתונים עם 3 מטריקות קריטיות.

---

## 🎯 סקירה כללית

| מטריקה | פקודת MongoDB | תדירות רענון | תיאור |
|:---|:---|:---:|:---|
| **Connection Pool Monitor** | `serverStatus` | 5 שניות | מעקב אחר חיבורים פעילים/זמינים |
| **Current Operations** | `currentOp` | 10 שניות | זיהוי slow queries (מעל 1 שנייה) |
| **Collection Stats** | `collStats` | לחיצה ידנית | גודל data ואינדקסים לכל collection |

---

## 1. ארכיטקטורה

```
┌─────────────────────────────────────────────────────────────────┐
│                       Frontend (Jinja2)                         │
│  ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐   │
│  │  Pool Monitor   │ │ Current Ops     │ │ Collection Stats│   │
│  │  (auto-refresh) │ │ (auto-refresh)  │ │ (on-demand)     │   │
│  └────────┬────────┘ └────────┬────────┘ └────────┬────────┘   │
└───────────┼───────────────────┼───────────────────┼─────────────┘
            │                   │                   │
            ▼                   ▼                   ▼
┌─────────────────────────────────────────────────────────────────┐
│                    API Endpoints (aiohttp)                       │
│  GET /api/db/pool    GET /api/db/ops    GET /api/db/collections │
└───────────────────────────────────────────────────────────────────┘
            │                   │                   │
            ▼                   ▼                   ▼
┌─────────────────────────────────────────────────────────────────┐
│                 DatabaseHealthService (Python)                   │
│  get_pool_status()  get_current_ops()  get_collection_stats()   │
└───────────────────────────────────────────────────────────────────┘
            │                   │                   │
            ▼                   ▼                   ▼
┌─────────────────────────────────────────────────────────────────┐
│                       MongoDB Admin Commands                     │
│     serverStatus          currentOp           collStats          │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2. Service Layer - `services/db_health_service.py`

> ⚠️ **חשוב - Async vs Sync:**  
> הפרויקט משתמש ב-**aiohttp** (אסינכרוני) ו-**Motor** לחלק מהפעולות.  
> להלן שתי גרסאות: **Motor (מומלץ)** ו-**PyMongo עם Thread Pool**.

### 2.1 גרסה אסינכרונית (Motor) - מומלץ ✅

```python
"""
Database Health Service - ניטור בריאות MongoDB (Async).

שימוש בפקודות ניהול מובנות: serverStatus, currentOp, collStats.
גרסה אסינכרונית עם Motor - מומלצת לשימוש עם aiohttp.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# Motor - async MongoDB driver
try:
    from motor.motor_asyncio import AsyncIOMotorClient
    MOTOR_AVAILABLE = True
except ImportError:
    MOTOR_AVAILABLE = False
    AsyncIOMotorClient = None  # type: ignore

logger = logging.getLogger(__name__)

# סף לזיהוי slow queries (באלפיות שנייה)
SLOW_QUERY_THRESHOLD_MS = int(os.getenv("DB_HEALTH_SLOW_THRESHOLD_MS", "1000"))


@dataclass
class PoolStatus:
    """מצב Connection Pool."""
    current: int = 0           # חיבורים פעילים כרגע
    available: int = 0         # חיבורים זמינים ב-pool
    total_created: int = 0     # סה"כ חיבורים שנוצרו
    max_pool_size: int = 50    # מקסימום מוגדר
    wait_queue_size: int = 0   # ממתינים לחיבור
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
    operation_type: str      # query, update, insert, command
    namespace: str           # db.collection
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
            result = await self._client.admin.command(
                "currentOp",
                {"$all": True}
            )
            
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
                
                slow_ops.append(SlowOperation(
                    op_id=str(op.get("opid", "")),
                    operation_type=op.get("op", "unknown"),
                    namespace=op.get("ns", "unknown"),
                    running_secs=float(secs_running),
                    query=query if isinstance(query, dict) else {"raw": str(query)},
                    client_ip=op.get("client_s", op.get("client", "")),
                    description=op.get("desc", ""),
                ))

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
                collections = [
                    name for name in await self._db.list_collection_names()
                    if not name.startswith("system.")
                ]

            stats: List[CollectionStat] = []
            
            for coll_name in collections:
                try:
                    # await חובה! - command אסינכרוני
                    result = await self._db.command("collStats", coll_name)
                    
                    stats.append(CollectionStat(
                        name=coll_name,
                        count=int(result.get("count", 0)),
                        size_bytes=int(result.get("size", 0)),
                        storage_size_bytes=int(result.get("storageSize", 0)),
                        index_count=int(result.get("nindexes", 0)),
                        total_index_size_bytes=int(result.get("totalIndexSize", 0)),
                        avg_obj_size_bytes=int(result.get("avgObjSize", 0)),
                    ))
                except Exception as e:
                    logger.warning(f"Failed to get stats for {coll_name}: {e}")
                    continue

            # מיון לפי גודל (הגדול ביותר קודם)
            stats.sort(key=lambda x: x.size_bytes, reverse=True)
            
            return stats

        except Exception as e:
            logger.error(f"Failed to get collection stats: {e}")
            raise RuntimeError(f"collStats failed: {e}") from e

    async def get_health_summary(self) -> Dict[str, Any]:
        """סיכום בריאות כללי לדשבורד.
        
        Returns:
            מילון עם כל המטריקות הקריטיות.
        """
        summary = {
            "timestamp": time.time(),
            "status": "unknown",
            "pool": None,
            "slow_queries_count": 0,
            "collections_count": 0,
            "errors": [],
        }

        # Pool status
        try:
            pool = await self.get_pool_status()
            summary["pool"] = pool.to_dict()
        except Exception as e:
            summary["errors"].append(f"pool: {e}")

        # Slow queries count
        try:
            ops = await self.get_current_operations()
            summary["slow_queries_count"] = len(ops)
        except Exception as e:
            summary["errors"].append(f"ops: {e}")

        # Collections count
        try:
            if self._db:
                coll_names = await self._db.list_collection_names()
                summary["collections_count"] = len([
                    n for n in coll_names
                    if not n.startswith("system.")
                ])
        except Exception as e:
            summary["errors"].append(f"collections: {e}")

        # קביעת סטטוס כללי
        if summary["errors"]:
            summary["status"] = "error"
        elif summary.get("pool", {}).get("status") == "critical":
            summary["status"] = "critical"
        elif summary["slow_queries_count"] > 5:
            summary["status"] = "warning"
        elif summary.get("pool", {}).get("status") == "warning":
            summary["status"] = "warning"
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
```

---

### 2.2 גרסה סינכרונית (PyMongo עם Thread Pool) - אלטרנטיבה

אם אתה רוצה להשתמש ב-`DatabaseManager` הסינכרוני הקיים, עטוף אותו עם `asyncio.to_thread`:

```python
"""
Database Health Service - גרסה סינכרונית עם Thread Pool.

עוטף את PyMongo הסינכרוני ומריץ אותו ב-thread pool
כדי לא לחסום את ה-event loop של aiohttp.
"""
from __future__ import annotations

import asyncio
import logging
from functools import partial
from typing import Any, Dict, List, Optional

# ייבוא ה-dataclasses מהגרסה הקודמת
from .db_health_service import (
    PoolStatus,
    SlowOperation,
    CollectionStat,
    SLOW_QUERY_THRESHOLD_MS,
)

logger = logging.getLogger(__name__)


class SyncDatabaseHealthService:
    """גרסה סינכרונית (PyMongo) - פנימית."""
    
    def __init__(self, db_manager):
        self.db_manager = db_manager

    @property
    def _client(self):
        return getattr(self.db_manager, "client", None)

    @property
    def _db(self):
        return getattr(self.db_manager, "db", None)

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
            
            slow_ops.append(SlowOperation(
                op_id=str(op.get("opid", "")),
                operation_type=op.get("op", "unknown"),
                namespace=op.get("ns", "unknown"),
                running_secs=float(secs_running),
                query=query if isinstance(query, dict) else {"raw": str(query)},
                client_ip=op.get("client_s", op.get("client", "")),
                description=op.get("desc", ""),
            ))

        slow_ops.sort(key=lambda x: x.running_secs, reverse=True)
        return slow_ops

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
                stats.append(CollectionStat(
                    name=coll_name,
                    count=int(result.get("count", 0)),
                    size_bytes=int(result.get("size", 0)),
                    storage_size_bytes=int(result.get("storageSize", 0)),
                    index_count=int(result.get("nindexes", 0)),
                    total_index_size_bytes=int(result.get("totalIndexSize", 0)),
                    avg_obj_size_bytes=int(result.get("avgObjSize", 0)),
                ))
            except Exception as e:
                logger.warning(f"Failed to get stats for {coll_name}: {e}")

        stats.sort(key=lambda x: x.size_bytes, reverse=True)
        return stats


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
        return await asyncio.to_thread(
            self._sync_service.get_current_operations_sync,
            threshold_ms,
            include_system,
        )

    async def get_collection_stats(self, collection_name: Optional[str] = None) -> List[CollectionStat]:
        """שליפת סטטיסטיקות - רץ ב-thread pool."""
        return await asyncio.to_thread(
            self._sync_service.get_collection_stats_sync,
            collection_name,
        )

    async def get_health_summary(self) -> Dict[str, Any]:
        """סיכום בריאות - רץ ב-thread pool."""
        # הרצה מקבילית של כל הבדיקות
        pool_task = asyncio.create_task(self.get_pool_status())
        ops_task = asyncio.create_task(self.get_current_operations())
        
        summary = {
            "timestamp": __import__("time").time(),
            "status": "unknown",
            "pool": None,
            "slow_queries_count": 0,
            "errors": [],
        }

        try:
            pool = await pool_task
            summary["pool"] = pool.to_dict()
        except Exception as e:
            summary["errors"].append(f"pool: {e}")

        try:
            ops = await ops_task
            summary["slow_queries_count"] = len(ops)
        except Exception as e:
            summary["errors"].append(f"ops: {e}")

        # קביעת סטטוס
        if summary["errors"]:
            summary["status"] = "error"
        elif summary.get("pool", {}).get("status") == "critical":
            summary["status"] = "critical"
        elif summary["slow_queries_count"] > 5:
            summary["status"] = "warning"
        elif summary.get("pool", {}).get("status") == "warning":
            summary["status"] = "warning"
        else:
            summary["status"] = "healthy"

        return summary


# Factory function לבחירת הגרסה המתאימה עם הגנה מפני race condition
_health_service_instance = None
_health_service_lock = asyncio.Lock()


async def get_db_health_service():
    """מחזיר את ה-service המתאים לפי הקונפיגורציה.
    
    משתמש ב-asyncio.Lock למניעת race condition בזמן אתחול.
    
    - אם Motor מותקן ו-MONGODB_URL מוגדר: AsyncDatabaseHealthService
    - אחרת: ThreadPoolDatabaseHealthService עם DatabaseManager הקיים
    """
    global _health_service_instance
    
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
            from motor.motor_asyncio import AsyncIOMotorClient
            import os
            if os.getenv("MONGODB_URL"):
                service = AsyncDatabaseHealthService()
                await service.connect()  # אתחול מלא בתוך הנעילה
                _health_service_instance = service
                logger.info("Using AsyncDatabaseHealthService (Motor)")
                return _health_service_instance
        except ImportError:
            pass

        # Fallback ל-PyMongo עם thread pool
        try:
            from database import db_manager
            _health_service_instance = ThreadPoolDatabaseHealthService(db_manager)
            logger.info("Using ThreadPoolDatabaseHealthService (PyMongo)")
            return _health_service_instance
        except Exception as e:
            raise RuntimeError(f"Could not initialize health service: {e}") from e
```

---

## 3. API Endpoints - הוספה ל-`services/webserver.py`

> ⚠️ **שים לב:** כל הקריאות ל-service הן **אסינכרוניות** עם `await`!

```python
# הוסף את ה-imports בראש הקובץ
from services.db_health_service import get_db_health_service

# הוסף את ה-handlers בתוך create_app()

async def db_health_pool_view(request: web.Request) -> web.Response:
    """GET /api/db/pool - מצב Connection Pool."""
    try:
        # await לקבלת ה-service (יכול להיות async init)
        svc = await get_db_health_service()
        # await לקריאה ל-MongoDB (Motor או thread pool)
        pool = await svc.get_pool_status()
        return web.json_response(pool.to_dict())
    except Exception as e:
        logger.error(f"db_health_pool error: {e}")
        return web.json_response(
            {"error": "failed", "message": str(e)},
            status=500
        )


async def db_health_ops_view(request: web.Request) -> web.Response:
    """GET /api/db/ops - פעולות איטיות פעילות."""
    try:
        threshold = int(request.query.get("threshold_ms", "1000"))
        include_system = request.query.get("include_system", "").lower() == "true"
        
        svc = await get_db_health_service()
        # await חובה! - הקריאה ל-MongoDB היא אסינכרונית
        ops = await svc.get_current_operations(
            threshold_ms=threshold,
            include_system=include_system,
        )
        
        return web.json_response({
            "count": len(ops),
            "threshold_ms": threshold,
            "operations": [op.to_dict() for op in ops],
        })
    except Exception as e:
        logger.error(f"db_health_ops error: {e}")
        return web.json_response(
            {"error": "failed", "message": str(e)},
            status=500
        )


async def db_health_collections_view(request: web.Request) -> web.Response:
    """GET /api/db/collections - סטטיסטיקות collections."""
    try:
        collection = request.query.get("collection")
        
        svc = await get_db_health_service()
        # await חובה! - collStats יכול לקחת זמן
        stats = await svc.get_collection_stats(collection_name=collection)
        
        return web.json_response({
            "count": len(stats),
            "collections": [s.to_dict() for s in stats],
        })
    except Exception as e:
        logger.error(f"db_health_collections error: {e}")
        return web.json_response(
            {"error": "failed", "message": str(e)},
            status=500
        )


async def db_health_summary_view(request: web.Request) -> web.Response:
    """GET /api/db/health - סיכום בריאות כללי."""
    try:
        svc = await get_db_health_service()
        # await חובה!
        summary = await svc.get_health_summary()
        return web.json_response(summary)
    except Exception as e:
        logger.error(f"db_health_summary error: {e}")
        return web.json_response(
            {"error": "failed", "message": str(e)},
            status=500
        )


# הוסף את ה-routes בסוף create_app()
app.router.add_get("/api/db/pool", db_health_pool_view)
app.router.add_get("/api/db/ops", db_health_ops_view)
app.router.add_get("/api/db/collections", db_health_collections_view)
app.router.add_get("/api/db/health", db_health_summary_view)
```

### 3.1 אתחול ה-Service ב-App Startup

מומלץ לאתחל את ה-service פעם אחת בעליית השרת:

```python
# בתוך create_app()

async def on_startup(app: web.Application):
    """אתחול שירותים בעליית השרת."""
    try:
        # אתחול מוקדם של DB Health Service
        svc = await get_db_health_service()
        app["db_health_service"] = svc
        logger.info("DB Health Service initialized")
    except Exception as e:
        logger.warning(f"DB Health Service init failed: {e}")

async def on_cleanup(app: web.Application):
    """ניקוי משאבים בכיבוי השרת."""
    svc = app.get("db_health_service")
    if svc and hasattr(svc, "close"):
        await svc.close()

app.on_startup.append(on_startup)
app.on_cleanup.append(on_cleanup)
```

---

## 4. UI Template - `webapp/templates/db_health.html`

```html
{% extends "base.html" %}

{% block title %}Database Health - Code Keeper Bot{% endblock %}

{% block content %}
<h1 class="page-title">🏥 Database Health Dashboard</h1>

<!-- Health Summary Card -->
<div class="health-summary glass-card" id="health-summary">
    <div class="summary-header">
        <div class="status-indicator" data-status="loading">
            <span class="status-dot"></span>
            <span class="status-text">טוען...</span>
        </div>
        <button class="btn btn-secondary btn-icon" onclick="refreshAll()">
            <i class="fas fa-sync"></i>
            רענן הכל
        </button>
    </div>
</div>

<!-- Metrics Grid -->
<div class="metrics-grid" style="display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 1.5rem; margin-top: 2rem;">
    
    <!-- Connection Pool Card -->
    <div class="glass-card metric-card" id="pool-card">
        <div class="card-header">
            <div class="card-title">
                <span class="card-icon">🔌</span>
                <h2>Connection Pool</h2>
            </div>
            <span class="refresh-indicator" data-refresh="5s">
                <i class="fas fa-clock"></i> 5s
            </span>
        </div>
        
        <div class="pool-metrics" id="pool-metrics">
            <div class="metric-row">
                <span class="metric-label">חיבורים פעילים</span>
                <span class="metric-value" id="pool-current">-</span>
            </div>
            <div class="metric-row">
                <span class="metric-label">חיבורים זמינים</span>
                <span class="metric-value" id="pool-available">-</span>
            </div>
            <div class="metric-row">
                <span class="metric-label">ניצולת</span>
                <div class="progress-bar">
                    <div class="progress-fill" id="pool-utilization-bar" style="width: 0%"></div>
                </div>
                <span class="metric-value" id="pool-utilization">0%</span>
            </div>
            <div class="metric-row">
                <span class="metric-label">ממתינים בתור</span>
                <span class="metric-value" id="pool-queue">0</span>
            </div>
            <div class="metric-row">
                <span class="metric-label">סה"כ נוצרו</span>
                <span class="metric-value dim" id="pool-created">-</span>
            </div>
        </div>
    </div>
    
    <!-- Current Operations Card -->
    <div class="glass-card metric-card" id="ops-card">
        <div class="card-header">
            <div class="card-title">
                <span class="card-icon">⏱️</span>
                <h2>Slow Queries</h2>
            </div>
            <span class="refresh-indicator" data-refresh="10s">
                <i class="fas fa-clock"></i> 10s
            </span>
        </div>
        
        <div class="ops-summary" id="ops-summary">
            <div class="ops-count">
                <span class="count-value" id="ops-count">0</span>
                <span class="count-label">פעולות איטיות (>1s)</span>
            </div>
        </div>
        
        <div class="ops-list" id="ops-list">
            <p class="empty-state">אין פעולות איטיות כרגע 🎉</p>
        </div>
    </div>
</div>

<!-- Collections Stats (On-Demand) -->
<div class="glass-card collections-card" id="collections-card" style="margin-top: 2rem;">
    <div class="card-header">
        <div class="card-title">
            <span class="card-icon">📊</span>
            <h2>Collection Stats</h2>
        </div>
        <button class="btn btn-primary btn-icon" id="load-collections-btn" onclick="loadCollections()">
            <i class="fas fa-database"></i>
            טען סטטיסטיקות
        </button>
    </div>
    
    <div class="collections-table-wrapper" id="collections-wrapper" style="display: none;">
        <table class="collections-table">
            <thead>
                <tr>
                    <th>Collection</th>
                    <th>מסמכים</th>
                    <th>גודל (MB)</th>
                    <th>אחסון (MB)</th>
                    <th>אינדקסים</th>
                    <th>גודל אינדקסים (MB)</th>
                </tr>
            </thead>
            <tbody id="collections-tbody">
            </tbody>
        </table>
    </div>
</div>

<style>
.health-summary {
    padding: 1.5rem;
}

.summary-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
}

.status-indicator {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    font-size: 1.25rem;
    font-weight: 600;
}

.status-dot {
    width: 16px;
    height: 16px;
    border-radius: 50%;
    background: #6b7280;
    animation: pulse 2s infinite;
}

.status-indicator[data-status="healthy"] .status-dot {
    background: #22c55e;
}

.status-indicator[data-status="warning"] .status-dot {
    background: #f59e0b;
}

.status-indicator[data-status="critical"] .status-dot {
    background: #ef4444;
}

.status-indicator[data-status="error"] .status-dot {
    background: #ef4444;
}

@keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.5; }
}

.metric-card {
    min-height: 280px;
}

.card-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 1.5rem;
    padding-bottom: 1rem;
    border-bottom: 1px solid rgba(255,255,255,0.08);
}

.card-title {
    display: flex;
    align-items: center;
    gap: 0.75rem;
}

.card-title h2 {
    margin: 0;
    font-size: 1.25rem;
}

.card-icon {
    font-size: 1.5rem;
}

.refresh-indicator {
    font-size: 0.8rem;
    opacity: 0.6;
    display: flex;
    align-items: center;
    gap: 0.3rem;
}

.metric-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 0.75rem 0;
    border-bottom: 1px solid rgba(255,255,255,0.04);
}

.metric-row:last-child {
    border-bottom: none;
}

.metric-label {
    opacity: 0.8;
}

.metric-value {
    font-weight: 600;
    font-size: 1.1rem;
    font-variant-numeric: tabular-nums;
}

.metric-value.dim {
    opacity: 0.6;
    font-size: 0.95rem;
}

.progress-bar {
    flex: 1;
    height: 8px;
    background: rgba(255,255,255,0.1);
    border-radius: 4px;
    margin: 0 1rem;
    overflow: hidden;
}

.progress-fill {
    height: 100%;
    background: linear-gradient(90deg, #22c55e, #84cc16);
    border-radius: 4px;
    transition: width 0.5s ease, background 0.3s ease;
}

.progress-fill.warning {
    background: linear-gradient(90deg, #f59e0b, #eab308);
}

.progress-fill.critical {
    background: linear-gradient(90deg, #ef4444, #dc2626);
}

.ops-summary {
    text-align: center;
    padding: 1.5rem 0;
}

.ops-count .count-value {
    font-size: 3rem;
    font-weight: bold;
    display: block;
    font-variant-numeric: tabular-nums;
}

.ops-count .count-label {
    opacity: 0.7;
    font-size: 0.9rem;
}

.ops-list {
    max-height: 200px;
    overflow-y: auto;
}

.ops-item {
    background: rgba(255,255,255,0.03);
    border-radius: 8px;
    padding: 0.75rem;
    margin-bottom: 0.5rem;
    border-right: 3px solid #6b7280;
}

.ops-item[data-severity="warning"] {
    border-right-color: #f59e0b;
}

.ops-item[data-severity="critical"] {
    border-right-color: #ef4444;
}

.ops-item-header {
    display: flex;
    justify-content: space-between;
    margin-bottom: 0.25rem;
}

.ops-type {
    font-weight: 600;
    text-transform: uppercase;
    font-size: 0.8rem;
}

.ops-time {
    font-variant-numeric: tabular-nums;
    color: #f59e0b;
}

.ops-ns {
    font-size: 0.85rem;
    opacity: 0.7;
    font-family: ui-monospace, monospace;
}

.empty-state {
    text-align: center;
    opacity: 0.6;
    padding: 1rem;
}

.collections-table-wrapper {
    overflow-x: auto;
    margin-top: 1rem;
}

.collections-table {
    width: 100%;
    border-collapse: collapse;
}

.collections-table th,
.collections-table td {
    padding: 0.75rem 1rem;
    text-align: right;
    border-bottom: 1px solid rgba(255,255,255,0.08);
}

.collections-table th {
    font-weight: 600;
    opacity: 0.8;
    font-size: 0.85rem;
    text-transform: uppercase;
}

.collections-table tr:hover {
    background: rgba(255,255,255,0.03);
}

.collections-table td:first-child {
    font-family: ui-monospace, monospace;
    font-weight: 500;
}

/* Rose Pine Dawn overrides */
:root[data-theme="rose-pine-dawn"] .metric-row {
    border-bottom-color: rgba(87,82,121,0.15);
}

:root[data-theme="rose-pine-dawn"] .card-header {
    border-bottom-color: rgba(87,82,121,0.15);
}

:root[data-theme="rose-pine-dawn"] .progress-bar {
    background: rgba(87,82,121,0.15);
}

:root[data-theme="rose-pine-dawn"] .ops-item {
    background: rgba(242,233,225,0.5);
}

:root[data-theme="rose-pine-dawn"] .collections-table th,
:root[data-theme="rose-pine-dawn"] .collections-table td {
    border-bottom-color: rgba(87,82,121,0.15);
}

@media (max-width: 768px) {
    .metrics-grid {
        grid-template-columns: 1fr !important;
    }
    
    .collections-table {
        font-size: 0.85rem;
    }
    
    .collections-table th,
    .collections-table td {
        padding: 0.5rem;
    }
}
</style>

<script>
// רענון אוטומטי
let poolInterval, opsInterval;

document.addEventListener('DOMContentLoaded', () => {
    // טעינה ראשונית
    refreshPool();
    refreshOps();
    refreshSummary();
    
    // רענון אוטומטי
    poolInterval = setInterval(refreshPool, 5000);
    opsInterval = setInterval(refreshOps, 10000);
});

async function refreshAll() {
    await Promise.all([
        refreshSummary(),
        refreshPool(),
        refreshOps(),
    ]);
}

async function refreshSummary() {
    try {
        const resp = await fetch('/api/db/health');
        const data = await resp.json();
        
        const indicator = document.querySelector('.status-indicator');
        indicator.setAttribute('data-status', data.status);
        indicator.querySelector('.status-text').textContent = getStatusText(data.status);
    } catch (e) {
        console.error('refreshSummary error:', e);
    }
}

async function refreshPool() {
    try {
        const resp = await fetch('/api/db/pool');
        const data = await resp.json();
        
        document.getElementById('pool-current').textContent = data.current;
        document.getElementById('pool-available').textContent = data.available;
        document.getElementById('pool-utilization').textContent = data.utilization_pct + '%';
        document.getElementById('pool-queue').textContent = data.wait_queue_size;
        document.getElementById('pool-created').textContent = data.total_created;
        
        const bar = document.getElementById('pool-utilization-bar');
        bar.style.width = data.utilization_pct + '%';
        bar.classList.remove('warning', 'critical');
        if (data.utilization_pct >= 90) {
            bar.classList.add('critical');
        } else if (data.utilization_pct >= 70) {
            bar.classList.add('warning');
        }
    } catch (e) {
        console.error('refreshPool error:', e);
    }
}

// פונקציית escape למניעת XSS
function escapeHtml(str) {
    if (str == null) return '';
    const div = document.createElement('div');
    div.textContent = String(str);
    return div.innerHTML;
}

async function refreshOps() {
    try {
        const resp = await fetch('/api/db/ops');
        const data = await resp.json();
        
        document.getElementById('ops-count').textContent = data.count;
        
        const list = document.getElementById('ops-list');
        if (data.count === 0) {
            list.innerHTML = '<p class="empty-state">אין פעולות איטיות כרגע 🎉</p>';
        } else {
            // שימוש ב-DOM API במקום innerHTML למניעת XSS
            list.innerHTML = '';
            data.operations.forEach(op => {
                const item = document.createElement('div');
                item.className = 'ops-item';
                item.dataset.severity = escapeHtml(op.severity);
                
                const header = document.createElement('div');
                header.className = 'ops-item-header';
                
                const typeSpan = document.createElement('span');
                typeSpan.className = 'ops-type';
                typeSpan.textContent = op.type;  // textContent בטוח מ-XSS
                
                const timeSpan = document.createElement('span');
                timeSpan.className = 'ops-time';
                timeSpan.textContent = `${op.running_secs}s`;
                
                header.appendChild(typeSpan);
                header.appendChild(timeSpan);
                
                const nsDiv = document.createElement('div');
                nsDiv.className = 'ops-ns';
                nsDiv.textContent = op.namespace;  // textContent בטוח מ-XSS
                
                item.appendChild(header);
                item.appendChild(nsDiv);
                list.appendChild(item);
            });
        }
    } catch (e) {
        console.error('refreshOps error:', e);
    }
}

async function loadCollections() {
    const btn = document.getElementById('load-collections-btn');
    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> טוען...';
    btn.disabled = true;
    
    try {
        const resp = await fetch('/api/db/collections');
        const data = await resp.json();
        
        const tbody = document.getElementById('collections-tbody');
        // שימוש ב-DOM API במקום innerHTML למניעת XSS
        tbody.innerHTML = '';
        
        data.collections.forEach(c => {
            const tr = document.createElement('tr');
            
            // יצירת תאים עם textContent (בטוח מ-XSS)
            const cells = [
                c.name,
                c.count.toLocaleString(),
                c.size_mb,
                c.storage_size_mb,
                c.index_count,
                c.total_index_size_mb
            ];
            
            cells.forEach(value => {
                const td = document.createElement('td');
                td.textContent = value;  // textContent בטוח מ-XSS
                tr.appendChild(td);
            });
            
            tbody.appendChild(tr);
        });
        
        document.getElementById('collections-wrapper').style.display = 'block';
        btn.innerHTML = '<i class="fas fa-sync"></i> רענן סטטיסטיקות';
    } catch (e) {
        console.error('loadCollections error:', e);
        btn.innerHTML = '<i class="fas fa-exclamation-triangle"></i> שגיאה';
    } finally {
        btn.disabled = false;
    }
}

function getStatusText(status) {
    const texts = {
        healthy: '✅ תקין',
        warning: '⚠️ אזהרה',
        critical: '🔴 קריטי',
        error: '❌ שגיאה',
        loading: 'טוען...',
        unknown: '❓ לא ידוע',
    };
    return texts[status] || status;
}
</script>
{% endblock %}
```

---

## 5. Route Registration - הוספה ל-Flask/aiohttp Router

### עבור Flask-based webapp (אם קיים)

```python
# webapp/__init__.py או webapp/routes.py

@app.route('/db-health')
@login_required  # הגן על הדף!
def db_health_page():
    """דף דשבורד בריאות מסד הנתונים."""
    return render_template('db_health.html')
```

### עבור aiohttp (services/webserver.py)

```python
# הוסף handler לדף HTML
async def db_health_page_view(request: web.Request) -> web.Response:
    """GET /db-health - דף דשבורד בריאות."""
    # בדיקת הרשאות (לדוגמה: admin token)
    # TODO: הוסף אימות מתאים
    
    # החזרת HTML (בפרודקשן, השתמש ב-aiohttp_jinja2)
    html = """
    <!DOCTYPE html>
    <html>
    <head><title>DB Health</title></head>
    <body>
        <script>window.location = '/webapp/db-health';</script>
    </body>
    </html>
    """
    return web.Response(text=html, content_type="text/html")

# רישום
app.router.add_get("/db-health", db_health_page_view)
```

---

## 6. אבטחה והרשאות

> ⚠️ **חשוב:** הדשבורד חושף מידע רגיש על מסד הנתונים. יש להגן עליו!

### הגנות נדרשות

```python
# דוגמה להגנה על ה-API endpoints

import hmac
import secrets

# 1. Token-based authentication עם הגנה מפני timing attacks
DB_HEALTH_TOKEN = os.getenv("DB_HEALTH_TOKEN", "")


def _constant_time_compare(a: str, b: str) -> bool:
    """השוואה בזמן קבוע למניעת timing attacks.
    
    משתמש ב-hmac.compare_digest שמבצע השוואה בזמן קבוע
    ללא קיצור-דרך על אי-התאמה ראשונה.
    """
    # המר לבייטים כדי להשתמש ב-compare_digest
    try:
        return hmac.compare_digest(
            a.encode('utf-8') if isinstance(a, str) else a,
            b.encode('utf-8') if isinstance(b, str) else b
        )
    except (TypeError, AttributeError):
        return False


@web.middleware
async def db_health_auth_middleware(request: web.Request, handler):
    """Middleware להגנה על endpoints של /api/db/*"""
    if request.path.startswith("/api/db/"):
        if not DB_HEALTH_TOKEN:
            # אם לא מוגדר token, חסום לגמרי
            return web.json_response({"error": "disabled"}, status=403)
        
        auth = request.headers.get("Authorization", "")
        
        # בדיקה שה-header מתחיל ב-Bearer (לא חושפת מידע)
        if not auth.startswith("Bearer "):
            return web.json_response({"error": "unauthorized"}, status=401)
        
        provided_token = auth[7:]  # הסר את "Bearer "
        
        # השוואה בזמן קבוע למניעת timing attacks!
        # secrets.compare_digest או hmac.compare_digest
        if not _constant_time_compare(provided_token, DB_HEALTH_TOKEN):
            return web.json_response({"error": "unauthorized"}, status=401)
    
    return await handler(request)


# 2. IP-based restriction (אופציונלי)
ALLOWED_IPS = {"127.0.0.1", "::1"}  # localhost only

def check_ip_allowed(request: web.Request) -> bool:
    client_ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
    if not client_ip:
        client_ip = request.remote
    return client_ip in ALLOWED_IPS
```

> ⚠️ **למה `hmac.compare_digest`?**  
> השוואה רגילה של מחרוזות (`!=`) עוצרת בתו הראשון שלא מתאים.  
> תוקף יכול למדוד את זמן התגובה ולגלות את ה-token תו-תו.  
> `compare_digest` תמיד לוקחת אותו זמן, לא משנה איפה אי-ההתאמה.

---

## 7. משתני סביבה

| משתנה | ברירת מחדל | תיאור |
|:---|:---:|:---|
| `DB_HEALTH_TOKEN` | (ריק) | Token להגנה על API endpoints |
| `DB_HEALTH_SLOW_THRESHOLD_MS` | `1000` | סף לזיהוי slow queries |
| `DB_HEALTH_POOL_REFRESH_SEC` | `5` | תדירות רענון pool status |
| `DB_HEALTH_OPS_REFRESH_SEC` | `10` | תדירות רענון current ops |

---

## 7.1 תלויות נדרשות

הוסף ל-`requirements.txt`:

```txt
# Async MongoDB driver (מומלץ לשימוש עם aiohttp)
motor>=3.0.0

# לבדיקות אסינכרוניות
pytest-asyncio>=0.21.0
```

> **הערה:** אם אתה מעדיף להשתמש ב-PyMongo הסינכרוני הקיים עם `asyncio.to_thread`,
> אין צורך ב-motor, אבל הביצועים יהיו פחות אופטימליים.

---

## 8. בדיקות יחידה

> ⚠️ **שים לב:** הבדיקות משתמשות ב-`pytest-asyncio` לבדיקת קוד אסינכרוני.

```python
# tests/test_db_health_service.py

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from services.db_health_service import (
    AsyncDatabaseHealthService,
    ThreadPoolDatabaseHealthService,
    PoolStatus,
    SlowOperation,
    CollectionStat,
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
                {"opid": 3, "op": "query", "ns": "local.oplog", "secs_running": 4.0},   # מערכת
            ]
        }
        
        result = await service.get_current_operations(threshold_ms=1000, include_system=False)
        
        assert len(result) == 1
        assert result[0].namespace == "test.users"

    async def test_get_collection_stats_success(self, service):
        """בדיקת שליפת סטטיסטיקות collections."""
        service._db.list_collection_names = AsyncMock(return_value=["users", "logs"])
        service._db.command = AsyncMock(side_effect=[
            {"count": 1000, "size": 1024*1024, "nindexes": 3, "storageSize": 2*1024*1024, "totalIndexSize": 512*1024, "avgObjSize": 512},
            {"count": 5000, "size": 5*1024*1024, "nindexes": 2, "storageSize": 6*1024*1024, "totalIndexSize": 256*1024, "avgObjSize": 256},
        ])
        
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
        import os
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
        assert result.status in ("healthy", "warning", "critical")

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
```

### 8.1 הרצת הבדיקות

```bash
# בדיקות יחידה בלבד
pytest tests/test_db_health_service.py -v

# בדיקות אינטגרציה (דורשות MongoDB)
MONGODB_URL=mongodb://localhost:27017 pytest tests/test_db_health_service.py -v -m integration

# כל הבדיקות
MONGODB_URL=mongodb://localhost:27017 pytest tests/test_db_health_service.py -v
```

---

## 9. אינטגרציה עם Observability

### שליחת מטריקות ל-Prometheus

```python
# metrics.py - הוספת מטריקות

from prometheus_client import Gauge

# Connection Pool metrics
mongo_pool_current = Gauge(
    "mongo_pool_connections_current",
    "Current number of MongoDB connections in use",
)
mongo_pool_available = Gauge(
    "mongo_pool_connections_available",
    "Available MongoDB connections in pool",
)
mongo_pool_utilization = Gauge(
    "mongo_pool_utilization_percent",
    "MongoDB connection pool utilization percentage",
)

# Slow queries metric
mongo_slow_queries_active = Gauge(
    "mongo_slow_queries_active",
    "Number of currently running slow queries (>1s)",
)
```

### עדכון מטריקות אוטומטי

```python
# הוספה ל-db_health_service.py

def update_prometheus_metrics(self):
    """עדכון מטריקות Prometheus."""
    try:
        from metrics import (
            mongo_pool_current,
            mongo_pool_available,
            mongo_pool_utilization,
            mongo_slow_queries_active,
        )
        
        pool = self.get_pool_status()
        mongo_pool_current.set(pool.current)
        mongo_pool_available.set(pool.available)
        mongo_pool_utilization.set(pool.utilization_pct)
        
        ops = self.get_current_operations()
        mongo_slow_queries_active.set(len(ops))
    except Exception as e:
        logger.warning(f"Failed to update Prometheus metrics: {e}")
```

---

## 10. פתרון תקלות

| סימפטום | סיבה אפשרית | פתרון |
|:---|:---|:---|
| `serverStatus` נכשל | חסרות הרשאות admin | וודא שה-user ב-connection string הוא admin |
| `currentOp` ריק תמיד | threshold גבוה מדי | הורד את `DB_HEALTH_SLOW_THRESHOLD_MS` |
| `collStats` איטי | הרבה collections | הגבל לחיצות ידניות בלבד (כפי שמומש) |
| Pool utilization גבוה | עומס או connection leak | בדוק `MONGODB_MAX_POOL_SIZE` ב-`GUIDE_CONNECTION_POOLING.md` |
| Wait queue לא אפס | כל החיבורים תפוסים | הגדל `MONGODB_MAX_POOL_SIZE` או `MONGODB_WAIT_QUEUE_TIMEOUT_MS` |

---

## 11. קישורים רלוונטיים

- [GUIDE_CONNECTION_POOLING.md](./GUIDE_CONNECTION_POOLING.md) - הגדרות Connection Pool
- [MongoDB serverStatus](https://www.mongodb.com/docs/manual/reference/command/serverStatus/)
- [MongoDB currentOp](https://www.mongodb.com/docs/manual/reference/command/currentOp/)
- [MongoDB collStats](https://www.mongodb.com/docs/manual/reference/command/collStats/)
- [database/manager.py](/database/manager.py) - מימוש החיבור הנוכחי

---

## 12. רשימת תיוג למימוש

- [ ] התקן `motor>=3.0.0` (או השתמש ב-PyMongo עם thread pool)
- [ ] צור קובץ `services/db_health_service.py` (גרסה async)
- [ ] הוסף API endpoints ל-`services/webserver.py` עם `await`
- [ ] הוסף אתחול ב-`on_startup` ו-`on_cleanup`
- [ ] צור תבנית `webapp/templates/db_health.html`
- [ ] הגדר `DB_HEALTH_TOKEN` ב-ENV
- [ ] הוסף route ל-webapp (Flask או aiohttp)
- [ ] כתוב בדיקות יחידה (עם `pytest-asyncio`)
- [ ] הוסף מטריקות Prometheus (אופציונלי)
- [ ] עדכן תיעוד API

### סדר מומלץ למימוש

1. **שלב 1 - Backend:**
   ```bash
   pip install motor pytest-asyncio
   ```
   - צור `services/db_health_service.py`
   - הוסף endpoints ל-webserver

2. **שלב 2 - Frontend:**
   - צור `db_health.html`
   - הוסף route

3. **שלב 3 - אבטחה:**
   - הוסף middleware עם token
   - הגדר `DB_HEALTH_TOKEN`

4. **שלב 4 - בדיקות:**
   - כתוב unit tests
   - הרץ integration tests
