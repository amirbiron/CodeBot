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

```python
"""
Database Health Service - ניטור בריאות MongoDB.

שימוש בפקודות ניהול מובנות: serverStatus, currentOp, collStats.
מותאם ל-DatabaseManager הקיים ב-database/manager.py.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# סף לזיהוי slow queries (באלפיות שנייה)
SLOW_QUERY_THRESHOLD_MS = 1000


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


class DatabaseHealthService:
    """שירות ניטור בריאות MongoDB.
    
    משתמש ב-DatabaseManager הקיים לגישה ל-client.
    
    Usage:
        from database import db_manager
        health_svc = DatabaseHealthService(db_manager)
        pool_status = health_svc.get_pool_status()
    """

    def __init__(self, db_manager):
        """
        Args:
            db_manager: מופע של DatabaseManager מ-database/manager.py
        """
        self.db_manager = db_manager
        self._cached_pool: Optional[PoolStatus] = None
        self._cache_ttl = 2.0  # שניות

    @property
    def _client(self):
        """גישה בטוחה ל-MongoClient."""
        return getattr(self.db_manager, "client", None)

    @property
    def _db(self):
        """גישה בטוחה ל-Database."""
        return getattr(self.db_manager, "db", None)

    def get_pool_status(self) -> PoolStatus:
        """שליפת מצב Connection Pool באמצעות serverStatus.
        
        Returns:
            PoolStatus עם פרטי ה-pool הנוכחיים.
        
        Raises:
            RuntimeError: אם אין חיבור פעיל למסד.
        """
        client = self._client
        if client is None:
            raise RuntimeError("No MongoDB client available")

        try:
            # serverStatus מחזיר מידע מקיף על השרת
            status = client.admin.command("serverStatus")
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

            # מידע נוסף על תור ההמתנה (אם זמין)
            # ב-PyMongo, המידע מגיע מ-topology description
            wait_queue = 0
            try:
                topology = client.topology_description
                for server in topology.server_descriptions().values():
                    # Best-effort: לא תמיד זמין
                    pass
            except Exception:
                pass

            return PoolStatus(
                current=current,
                available=available,
                total_created=total_created,
                max_pool_size=max_pool,
                wait_queue_size=wait_queue,
                utilization_pct=utilization,
            )

        except Exception as e:
            logger.error(f"Failed to get pool status: {e}")
            raise RuntimeError(f"serverStatus failed: {e}") from e

    def get_current_operations(
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
        client = self._client
        if client is None:
            raise RuntimeError("No MongoDB client available")

        try:
            threshold_secs = threshold_ms / 1000.0
            
            # currentOp - הצגת כל הפעולות הפעילות
            result = client.admin.command(
                "currentOp",
                {"$all": True}  # כולל idle connections
            )
            
            slow_ops: List[SlowOperation] = []
            
            for op in result.get("inprog", []):
                # דילוג על פעולות מערכת אם לא התבקש
                if not include_system:
                    ns = op.get("ns", "")
                    if ns.startswith("admin.") or ns.startswith("local.") or ns.startswith("config."):
                        continue
                    # דילוג על פעולות פנימיות
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

    def get_collection_stats(self, collection_name: Optional[str] = None) -> List[CollectionStat]:
        """שליפת סטטיסטיקות collections באמצעות collStats.
        
        Args:
            collection_name: שם collection ספציפי, או None לכל ה-collections.
        
        Returns:
            רשימת CollectionStat ממוינת לפי גודל (הגדול ביותר קודם).
        """
        db = self._db
        if db is None:
            raise RuntimeError("No MongoDB database available")

        try:
            if collection_name:
                collections = [collection_name]
            else:
                # רשימת כל ה-collections (לא כולל system)
                collections = [
                    name for name in db.list_collection_names()
                    if not name.startswith("system.")
                ]

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
                    continue

            # מיון לפי גודל (הגדול ביותר קודם)
            stats.sort(key=lambda x: x.size_bytes, reverse=True)
            
            return stats

        except Exception as e:
            logger.error(f"Failed to get collection stats: {e}")
            raise RuntimeError(f"collStats failed: {e}") from e

    def get_health_summary(self) -> Dict[str, Any]:
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
            pool = self.get_pool_status()
            summary["pool"] = pool.to_dict()
        except Exception as e:
            summary["errors"].append(f"pool: {e}")

        # Slow queries count
        try:
            ops = self.get_current_operations()
            summary["slow_queries_count"] = len(ops)
        except Exception as e:
            summary["errors"].append(f"ops: {e}")

        # Collections count
        try:
            db = self._db
            if db:
                summary["collections_count"] = len([
                    n for n in db.list_collection_names()
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


# Singleton instance לשימוש גלובלי
_health_service: Optional[DatabaseHealthService] = None


def get_db_health_service() -> DatabaseHealthService:
    """מחזיר את ה-singleton של DatabaseHealthService.
    
    Usage:
        from services.db_health_service import get_db_health_service
        svc = get_db_health_service()
        pool = svc.get_pool_status()
    """
    global _health_service
    if _health_service is None:
        from database import db_manager
        _health_service = DatabaseHealthService(db_manager)
    return _health_service
```

---

## 3. API Endpoints - הוספה ל-`services/webserver.py`

```python
# הוסף את ה-imports בראש הקובץ
from services.db_health_service import get_db_health_service

# הוסף את ה-handlers בתוך create_app()

async def db_health_pool_view(request: web.Request) -> web.Response:
    """GET /api/db/pool - מצב Connection Pool."""
    try:
        svc = get_db_health_service()
        pool = svc.get_pool_status()
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
        
        svc = get_db_health_service()
        ops = svc.get_current_operations(
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
        
        svc = get_db_health_service()
        stats = svc.get_collection_stats(collection_name=collection)
        
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
        svc = get_db_health_service()
        summary = svc.get_health_summary()
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

async function refreshOps() {
    try {
        const resp = await fetch('/api/db/ops');
        const data = await resp.json();
        
        document.getElementById('ops-count').textContent = data.count;
        
        const list = document.getElementById('ops-list');
        if (data.count === 0) {
            list.innerHTML = '<p class="empty-state">אין פעולות איטיות כרגע 🎉</p>';
        } else {
            list.innerHTML = data.operations.map(op => `
                <div class="ops-item" data-severity="${op.severity}">
                    <div class="ops-item-header">
                        <span class="ops-type">${op.type}</span>
                        <span class="ops-time">${op.running_secs}s</span>
                    </div>
                    <div class="ops-ns">${op.namespace}</div>
                </div>
            `).join('');
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
        tbody.innerHTML = data.collections.map(c => `
            <tr>
                <td>${c.name}</td>
                <td>${c.count.toLocaleString()}</td>
                <td>${c.size_mb}</td>
                <td>${c.storage_size_mb}</td>
                <td>${c.index_count}</td>
                <td>${c.total_index_size_mb}</td>
            </tr>
        `).join('');
        
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

# 1. Token-based authentication
DB_HEALTH_TOKEN = os.getenv("DB_HEALTH_TOKEN", "")

@web.middleware
async def db_health_auth_middleware(request: web.Request, handler):
    """Middleware להגנה על endpoints של /api/db/*"""
    if request.path.startswith("/api/db/"):
        if not DB_HEALTH_TOKEN:
            # אם לא מוגדר token, חסום לגמרי
            return web.json_response({"error": "disabled"}, status=403)
        
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer ") or auth[7:] != DB_HEALTH_TOKEN:
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

---

## 7. משתני סביבה

| משתנה | ברירת מחדל | תיאור |
|:---|:---:|:---|
| `DB_HEALTH_TOKEN` | (ריק) | Token להגנה על API endpoints |
| `DB_HEALTH_SLOW_THRESHOLD_MS` | `1000` | סף לזיהוי slow queries |
| `DB_HEALTH_POOL_REFRESH_SEC` | `5` | תדירות רענון pool status |
| `DB_HEALTH_OPS_REFRESH_SEC` | `10` | תדירות רענון current ops |

---

## 8. בדיקות יחידה

```python
# tests/test_db_health_service.py

import pytest
from unittest.mock import MagicMock, patch
from services.db_health_service import DatabaseHealthService, PoolStatus


class TestDatabaseHealthService:
    """בדיקות יחידה ל-DatabaseHealthService."""

    @pytest.fixture
    def mock_db_manager(self):
        """Mock של DatabaseManager."""
        manager = MagicMock()
        manager.client = MagicMock()
        manager.db = MagicMock()
        return manager

    @pytest.fixture
    def service(self, mock_db_manager):
        return DatabaseHealthService(mock_db_manager)

    def test_get_pool_status_success(self, service, mock_db_manager):
        """בדיקת שליפת מצב pool תקינה."""
        mock_db_manager.client.admin.command.return_value = {
            "connections": {
                "current": 10,
                "available": 40,
                "totalCreated": 150,
            }
        }
        
        result = service.get_pool_status()
        
        assert result.current == 10
        assert result.available == 40
        assert result.total_created == 150
        assert result.utilization_pct == 20.0  # 10/50 * 100

    def test_get_pool_status_no_client(self, mock_db_manager):
        """בדיקת שגיאה כשאין client."""
        mock_db_manager.client = None
        service = DatabaseHealthService(mock_db_manager)
        
        with pytest.raises(RuntimeError, match="No MongoDB client"):
            service.get_pool_status()

    def test_get_current_operations_filters_by_threshold(self, service, mock_db_manager):
        """בדיקת סינון לפי סף זמן."""
        mock_db_manager.client.admin.command.return_value = {
            "inprog": [
                {"opid": 1, "op": "query", "ns": "test.users", "secs_running": 2.5},
                {"opid": 2, "op": "query", "ns": "test.logs", "secs_running": 0.5},
                {"opid": 3, "op": "update", "ns": "test.data", "secs_running": 5.0},
            ]
        }
        
        result = service.get_current_operations(threshold_ms=1000)
        
        assert len(result) == 2
        assert result[0].running_secs == 5.0  # ממוין לפי זמן
        assert result[1].running_secs == 2.5

    def test_get_collection_stats_success(self, service, mock_db_manager):
        """בדיקת שליפת סטטיסטיקות collections."""
        mock_db_manager.db.list_collection_names.return_value = ["users", "logs"]
        mock_db_manager.db.command.side_effect = [
            {"count": 1000, "size": 1024*1024, "nindexes": 3, "storageSize": 2*1024*1024, "totalIndexSize": 512*1024, "avgObjSize": 512},
            {"count": 5000, "size": 5*1024*1024, "nindexes": 2, "storageSize": 6*1024*1024, "totalIndexSize": 256*1024, "avgObjSize": 256},
        ]
        
        result = service.get_collection_stats()
        
        assert len(result) == 2
        assert result[0].name == "logs"  # ממוין לפי גודל
        assert result[0].count == 5000


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

- [ ] צור קובץ `services/db_health_service.py`
- [ ] הוסף API endpoints ל-`services/webserver.py`
- [ ] צור תבנית `webapp/templates/db_health.html`
- [ ] הגדר `DB_HEALTH_TOKEN` ב-ENV
- [ ] הוסף route ל-webapp (Flask או aiohttp)
- [ ] כתוב בדיקות יחידה
- [ ] הוסף מטריקות Prometheus (אופציונלי)
- [ ] עדכן תיעוד API
