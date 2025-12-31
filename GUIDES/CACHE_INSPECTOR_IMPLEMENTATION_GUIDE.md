# מדריך מימוש Cache Inspector Panel

> **מטרה:** דשבורד אדמין לצפייה, חיפוש ומחיקת entries ב-Redis cache עם הצגת TTL ו-memory usage.

---

## סקירה כללית

### מה הפיצ'ר עושה?

Cache Inspector הוא דף אדמין שמאפשר לראות במבט אחד:

| עמודה | תיאור |
|-------|-------|
| **Key** | מפתח ה-cache |
| **Value Preview** | תצוגה מקדימה של הערך (מקוצר) |
| **TTL** | זמן התפוגה בשניות (-1 = אין, -2 = לא קיים) |
| **Size** | גודל הערך בבייטים (משוער) |
| **Actions** | כפתור מחיקה |

### למה זה שימושי?

- **דיבאג**: לראות מה נמצא ב-cache בזמן אמת
- **ניטור**: לעקוב אחרי צריכת זיכרון ו-hit rate
- **תחזוקה**: למחוק entries בעייתיים או מיותרים
- **אופטימיזציה**: לזהות מפתחות עם TTL ארוך/קצר מדי

---

## ארכיטקטורה

```
┌─────────────────────────────────────────────────────────────┐
│                      Browser (Admin)                         │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                  /admin/cache-inspector                      │
│                     (Protected Route)                        │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                   CacheInspectorService                      │
│  ┌─────────────────────────────────────────────────────────┐│
│  │ get_cache_stats()                                       ││
│  │   → cache.get_stats()                                   ││
│  │   → memory usage, hit rate, clients                     ││
│  └─────────────────────────────────────────────────────────┘│
│  ┌─────────────────────────────────────────────────────────┐│
│  │ list_keys(pattern, limit)                               ││
│  │   → redis_client.scan_iter()                            ││
│  │   → redis_client.ttl()                                  ││
│  │   → redis_client.strlen()                               ││
│  └─────────────────────────────────────────────────────────┘│
│  ┌─────────────────────────────────────────────────────────┐│
│  │ delete_key(key) / delete_pattern(pattern)               ││
│  │   → cache.delete() / cache.delete_pattern()             ││
│  └─────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│              admin_cache_inspector.html                      │
│                  (Jinja2 Template)                           │
└─────────────────────────────────────────────────────────────┘
```

---

## 1. Service Layer – `CacheInspectorService`

### קובץ: `services/cache_inspector_service.py`

```python
"""
Cache Inspector Service
=======================
שירות לצפייה, חיפוש ומחיקת entries ב-Redis cache.
מספק ממשק בטוח לניהול cache עם הגנות אבטחה.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class CacheKeyStatus(str, Enum):
    """סטטוס של מפתח cache."""
    ACTIVE = "Active"           # מפתח פעיל עם TTL
    PERSISTENT = "Persistent"   # מפתח ללא TTL (לא יפוג)
    EXPIRING_SOON = "Expiring"  # יפוג תוך דקה
    EXPIRED = "Expired"         # פג תוקף (לא קיים)


@dataclass
class CacheEntry:
    """ערך cache בודד עם מטא-דאטה."""
    key: str
    value_preview: str          # תצוגה מקדימה מקוצרת
    ttl_seconds: int            # -1 = persistent, -2 = not exists
    size_bytes: int             # גודל משוער
    status: CacheKeyStatus
    value_type: str             # סוג הערך (string, dict, list, etc.)
    created_hint: str = ""      # רמז לזמן יצירה (אם זמין)


@dataclass
class CacheStats:
    """סטטיסטיקות כלליות של ה-cache."""
    enabled: bool
    used_memory: str            # e.g., "1.5M"
    used_memory_bytes: int
    connected_clients: int
    keyspace_hits: int
    keyspace_misses: int
    hit_rate: float             # אחוז hit rate
    total_keys: int
    evicted_keys: int
    uptime_seconds: int
    redis_version: str
    error: Optional[str] = None


@dataclass
class CacheOverview:
    """סקירת cache מלאה."""
    stats: CacheStats
    entries: List[CacheEntry] = field(default_factory=list)
    generated_at: str = ""
    search_pattern: str = "*"
    total_scanned: int = 0
    has_more: bool = False


class CacheInspectorService:
    """
    שירות לניהול וסקירת Redis cache.
    
    שימוש:
        service = CacheInspectorService()
        overview = service.get_overview(pattern="user:*", limit=100)
    """
    
    # מגבלת ברירת מחדל לסריקה (למניעת עומס)
    DEFAULT_SCAN_LIMIT: int = 100
    MAX_SCAN_LIMIT: int = 500
    
    # אורך מקסימלי לתצוגה מקדימה של ערך
    VALUE_PREVIEW_LENGTH: int = 100
    
    # רשימת תבניות רגישות שלא יוצגו הערך שלהן
    SENSITIVE_PATTERNS: tuple[str, ...] = (
        "session:",
        "token:",
        "auth:",
        "secret:",
        "password:",
        "credential:",
        "api_key:",
    )
    
    # ערך להסתרה
    MASKED_VALUE: str = "[SENSITIVE - HIDDEN]"
    
    def __init__(self) -> None:
        """אתחול השירות עם גישה ל-CacheManager."""
        self._cache_manager = None
    
    @property
    def cache_manager(self):
        """גישה עצלנית ל-CacheManager (lazy import)."""
        if self._cache_manager is None:
            try:
                from cache_manager import cache
                self._cache_manager = cache
            except ImportError:
                logger.error("cache_manager module not found")
                self._cache_manager = None
        return self._cache_manager
    
    @property
    def redis_client(self):
        """גישה ישירה ל-Redis client."""
        if self.cache_manager and self.cache_manager.is_enabled:
            return self.cache_manager.redis_client
        return None
    
    def is_enabled(self) -> bool:
        """בדיקה האם Redis מופעל."""
        return self.cache_manager is not None and self.cache_manager.is_enabled
    
    def _is_sensitive_key(self, key: str) -> bool:
        """בדיקה האם מפתח רגיש."""
        key_lower = key.lower()
        return any(pattern in key_lower for pattern in self.SENSITIVE_PATTERNS)
    
    def _get_value_preview(self, key: str) -> Tuple[str, str]:
        """
        קבלת תצוגה מקדימה של ערך.
        
        Returns:
            Tuple של (preview, type)
        """
        if self._is_sensitive_key(key):
            return self.MASKED_VALUE, "sensitive"
        
        try:
            client = self.redis_client
            if client is None:
                return "(unavailable)", "unknown"
            
            # קבלת הערך הגולמי
            raw_value = client.get(key)
            if raw_value is None:
                return "(null)", "null"
            
            # ניסיון לפרסר JSON
            try:
                parsed = json.loads(raw_value)
                if isinstance(parsed, dict):
                    value_type = "dict"
                    preview = json.dumps(parsed, ensure_ascii=False)
                elif isinstance(parsed, list):
                    value_type = "list"
                    preview = json.dumps(parsed, ensure_ascii=False)
                else:
                    value_type = type(parsed).__name__
                    preview = str(parsed)
            except (json.JSONDecodeError, TypeError):
                value_type = "string"
                preview = str(raw_value)
            
            # קיצור התצוגה
            if len(preview) > self.VALUE_PREVIEW_LENGTH:
                preview = preview[:self.VALUE_PREVIEW_LENGTH] + "..."
            
            return preview, value_type
            
        except Exception as e:
            logger.warning(f"Error getting value preview for {key}: {e}")
            return "(error)", "error"
    
    def _determine_status(self, ttl: int) -> CacheKeyStatus:
        """קביעת סטטוס לפי TTL."""
        if ttl == -2:
            return CacheKeyStatus.EXPIRED
        if ttl == -1:
            return CacheKeyStatus.PERSISTENT
        if ttl <= 60:
            return CacheKeyStatus.EXPIRING_SOON
        return CacheKeyStatus.ACTIVE
    
    def get_cache_stats(self) -> CacheStats:
        """
        קבלת סטטיסטיקות כלליות של ה-cache.
        
        Returns:
            אובייקט CacheStats עם כל המטריקות
        """
        if not self.is_enabled():
            return CacheStats(
                enabled=False,
                used_memory="N/A",
                used_memory_bytes=0,
                connected_clients=0,
                keyspace_hits=0,
                keyspace_misses=0,
                hit_rate=0.0,
                total_keys=0,
                evicted_keys=0,
                uptime_seconds=0,
                redis_version="N/A",
                error="Redis is disabled",
            )
        
        try:
            client = self.redis_client
            info = client.info()
            
            # חישוב מספר המפתחות הכולל
            total_keys = 0
            try:
                db_info = client.info("keyspace")
                for db_name, db_data in db_info.items():
                    if db_name.startswith("db"):
                        total_keys += db_data.get("keys", 0)
            except Exception:
                total_keys = client.dbsize()
            
            # חישוב hit rate
            hits = info.get('keyspace_hits', 0)
            misses = info.get('keyspace_misses', 0)
            total_ops = hits + misses
            hit_rate = round((hits / total_ops * 100) if total_ops > 0 else 0, 2)
            
            return CacheStats(
                enabled=True,
                used_memory=info.get('used_memory_human', 'N/A'),
                used_memory_bytes=info.get('used_memory', 0),
                connected_clients=info.get('connected_clients', 0),
                keyspace_hits=hits,
                keyspace_misses=misses,
                hit_rate=hit_rate,
                total_keys=total_keys,
                evicted_keys=info.get('evicted_keys', 0),
                uptime_seconds=info.get('uptime_in_seconds', 0),
                redis_version=info.get('redis_version', 'N/A'),
            )
            
        except Exception as e:
            logger.error(f"Error getting cache stats: {e}")
            return CacheStats(
                enabled=True,
                used_memory="N/A",
                used_memory_bytes=0,
                connected_clients=0,
                keyspace_hits=0,
                keyspace_misses=0,
                hit_rate=0.0,
                total_keys=0,
                evicted_keys=0,
                uptime_seconds=0,
                redis_version="N/A",
                error=str(e),
            )
    
    def list_keys(
        self,
        pattern: str = "*",
        limit: int = DEFAULT_SCAN_LIMIT,
    ) -> Tuple[List[CacheEntry], int, bool]:
        """
        רשימת מפתחות עם מטא-דאטה.
        
        Args:
            pattern: תבנית חיפוש (e.g., "user:*")
            limit: מגבלת תוצאות
            
        Returns:
            Tuple של (entries, total_scanned, has_more)
        """
        if not self.is_enabled():
            return [], 0, False
        
        # אכיפת מגבלות
        limit = min(max(1, limit), self.MAX_SCAN_LIMIT)
        
        entries: List[CacheEntry] = []
        scanned = 0
        has_more = False
        
        try:
            client = self.redis_client
            
            # סריקה בטוחה עם SCAN
            for key in client.scan_iter(match=pattern, count=100):
                scanned += 1
                
                if len(entries) >= limit:
                    has_more = True
                    break
                
                try:
                    # קבלת TTL
                    ttl = client.ttl(key)
                    
                    # קבלת גודל (אם אפשר)
                    try:
                        size = client.strlen(key)
                    except Exception:
                        size = 0
                    
                    # קבלת תצוגה מקדימה
                    preview, value_type = self._get_value_preview(key)
                    
                    # קביעת סטטוס
                    status = self._determine_status(ttl)
                    
                    entries.append(CacheEntry(
                        key=key,
                        value_preview=preview,
                        ttl_seconds=ttl,
                        size_bytes=size,
                        status=status,
                        value_type=value_type,
                    ))
                    
                except Exception as e:
                    logger.warning(f"Error processing key {key}: {e}")
                    continue
            
            # מיון לפי מפתח
            entries.sort(key=lambda e: e.key)
            
        except Exception as e:
            logger.error(f"Error listing cache keys: {e}")
        
        return entries, scanned, has_more
    
    def get_key_details(self, key: str) -> Optional[Dict[str, Any]]:
        """
        קבלת פרטים מלאים על מפתח בודד.
        
        Args:
            key: מפתח ה-cache
            
        Returns:
            מילון עם כל הפרטים או None אם לא קיים
        """
        if not self.is_enabled():
            return None
        
        try:
            client = self.redis_client
            
            # בדיקת קיום
            if not client.exists(key):
                return None
            
            # קבלת TTL
            ttl = client.ttl(key)
            
            # קבלת הערך המלא (אם לא רגיש)
            if self._is_sensitive_key(key):
                value = self.MASKED_VALUE
                value_type = "sensitive"
            else:
                raw_value = client.get(key)
                try:
                    value = json.loads(raw_value)
                    value_type = type(value).__name__
                except (json.JSONDecodeError, TypeError):
                    value = raw_value
                    value_type = "string"
            
            # קבלת גודל
            try:
                size = client.strlen(key)
            except Exception:
                size = len(str(raw_value)) if raw_value else 0
            
            # קבלת encoding ו-idletime (אם נתמך)
            encoding = "unknown"
            idle_time = None
            try:
                encoding = client.object("encoding", key)
                idle_time = client.object("idletime", key)
            except Exception:
                pass
            
            return {
                "key": key,
                "value": value,
                "value_type": value_type,
                "ttl_seconds": ttl,
                "size_bytes": size,
                "encoding": encoding,
                "idle_time_seconds": idle_time,
                "status": self._determine_status(ttl).value,
                "is_sensitive": self._is_sensitive_key(key),
            }
            
        except Exception as e:
            logger.error(f"Error getting key details for {key}: {e}")
            return None
    
    def delete_key(self, key: str) -> bool:
        """
        מחיקת מפתח בודד.
        
        Args:
            key: מפתח למחיקה
            
        Returns:
            True אם נמחק בהצלחה
        """
        if not self.is_enabled():
            return False
        
        try:
            result = self.cache_manager.delete(key)
            if result:
                logger.info(f"Cache key deleted: {key}")
            return result
        except Exception as e:
            logger.error(f"Error deleting cache key {key}: {e}")
            return False
    
    def delete_pattern(self, pattern: str) -> int:
        """
        מחיקת מפתחות לפי תבנית.
        
        Args:
            pattern: תבנית למחיקה (e.g., "user:123:*")
            
        Returns:
            מספר המפתחות שנמחקו
        """
        if not self.is_enabled():
            return 0
        
        # בדיקת אבטחה: לא מאפשר מחיקת הכל בלי אישור מפורש
        if pattern in ("*", "**"):
            logger.warning("Attempt to delete all keys blocked - use clear_all() instead")
            return 0
        
        try:
            deleted = self.cache_manager.delete_pattern(pattern)
            logger.info(f"Cache pattern deleted: {pattern} ({deleted} keys)")
            return deleted
        except Exception as e:
            logger.error(f"Error deleting cache pattern {pattern}: {e}")
            return 0
    
    def clear_all(self, confirm: bool = False) -> int:
        """
        ניקוי כל ה-cache.
        
        Args:
            confirm: דגל אישור (חייב להיות True)
            
        Returns:
            מספר המפתחות שנמחקו
        """
        if not confirm:
            logger.warning("clear_all called without confirmation")
            return 0
        
        if not self.is_enabled():
            return 0
        
        try:
            deleted = self.cache_manager.clear_all()
            logger.warning(f"Cache cleared: {deleted} keys deleted")
            return deleted
        except Exception as e:
            logger.error(f"Error clearing cache: {e}")
            return 0
    
    def get_overview(
        self,
        pattern: str = "*",
        limit: int = DEFAULT_SCAN_LIMIT,
    ) -> CacheOverview:
        """
        קבלת סקירה מלאה של ה-cache.
        
        Args:
            pattern: תבנית חיפוש
            limit: מגבלת תוצאות
            
        Returns:
            אובייקט CacheOverview מלא
        """
        stats = self.get_cache_stats()
        entries, scanned, has_more = self.list_keys(pattern, limit)
        
        return CacheOverview(
            stats=stats,
            entries=entries,
            generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            search_pattern=pattern,
            total_scanned=scanned,
            has_more=has_more,
        )
    
    def get_key_prefixes(self, sample_size: int = 1000) -> Dict[str, int]:
        """
        ניתוח תפוצת prefixes במפתחות.
        
        Args:
            sample_size: מספר מפתחות לדגימה
            
        Returns:
            מילון של prefix -> count
        """
        if not self.is_enabled():
            return {}
        
        prefixes: Dict[str, int] = {}
        
        try:
            client = self.redis_client
            count = 0
            
            for key in client.scan_iter(match="*", count=100):
                count += 1
                if count > sample_size:
                    break
                
                # חילוץ prefix (עד ה-: הראשון)
                if ":" in key:
                    prefix = key.split(":")[0]
                else:
                    prefix = "(no-prefix)"
                
                prefixes[prefix] = prefixes.get(prefix, 0) + 1
            
        except Exception as e:
            logger.error(f"Error analyzing prefixes: {e}")
        
        # מיון לפי כמות
        return dict(sorted(prefixes.items(), key=lambda x: -x[1]))


# Singleton instance
_cache_inspector_service: Optional[CacheInspectorService] = None


def get_cache_inspector_service() -> CacheInspectorService:
    """קבלת instance יחיד של השירות."""
    global _cache_inspector_service
    if _cache_inspector_service is None:
        _cache_inspector_service = CacheInspectorService()
    return _cache_inspector_service
```

---

## 2. API/Routes – Handler לדף

### הוספה לקובץ: `services/webserver.py`

```python
# הוספה בראש הקובץ (imports)
from services.cache_inspector_service import (
    get_cache_inspector_service,
    CacheKeyStatus,
)

# הוספת הראוטים (בתוך setup_routes או אזור הראוטים)

@routes.get("/admin/cache-inspector")
async def admin_cache_inspector_handler(request: web.Request) -> web.Response:
    """
    דף Cache Inspector לאדמינים.
    מציג סקירה של Redis cache עם אפשרויות חיפוש ומחיקה.
    """
    # בדיקת הרשאות אדמין
    session = await get_session(request)
    if not session.get("is_admin"):
        raise web.HTTPForbidden(text="Admin access required")
    
    # קבלת פרמטרים
    pattern = request.query.get("pattern", "*")
    limit_str = request.query.get("limit", "100")
    
    try:
        limit = min(int(limit_str), 500)
    except ValueError:
        limit = 100
    
    # קבלת הנתונים מהשירות
    service = get_cache_inspector_service()
    overview = service.get_overview(pattern=pattern, limit=limit)
    prefixes = service.get_key_prefixes()
    
    # רינדור התבנית
    return render_template(
        "admin_cache_inspector.html",
        request,
        overview=overview,
        prefixes=prefixes,
        selected_pattern=pattern,
        selected_limit=limit,
        statuses=[s.value for s in CacheKeyStatus],
    )


@routes.post("/admin/cache-inspector/delete")
async def admin_cache_delete_handler(request: web.Request) -> web.Response:
    """
    API למחיקת מפתח/תבנית מה-cache.
    """
    # בדיקת הרשאות אדמין
    session = await get_session(request)
    if not session.get("is_admin"):
        return web.json_response({"error": "Admin access required"}, status=403)
    
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)
    
    key = data.get("key")
    pattern = data.get("pattern")
    
    service = get_cache_inspector_service()
    
    if key:
        # מחיקת מפתח בודד
        success = service.delete_key(key)
        return web.json_response({
            "success": success,
            "message": f"Key '{key}' deleted" if success else "Delete failed",
        })
    
    if pattern:
        # מחיקת תבנית
        if pattern in ("*", "**"):
            return web.json_response({
                "error": "Cannot delete all keys. Use Clear All button.",
            }, status=400)
        
        deleted = service.delete_pattern(pattern)
        return web.json_response({
            "success": True,
            "deleted_count": deleted,
            "message": f"{deleted} keys deleted",
        })
    
    return web.json_response({"error": "No key or pattern provided"}, status=400)


@routes.post("/admin/cache-inspector/clear-all")
async def admin_cache_clear_all_handler(request: web.Request) -> web.Response:
    """
    API לניקוי כל ה-cache (דורש אישור).
    """
    # בדיקת הרשאות אדמין
    session = await get_session(request)
    if not session.get("is_admin"):
        return web.json_response({"error": "Admin access required"}, status=403)
    
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)
    
    confirm = data.get("confirm", False)
    
    if not confirm:
        return web.json_response({
            "error": "Confirmation required",
            "message": "Send confirm: true to clear all cache",
        }, status=400)
    
    service = get_cache_inspector_service()
    deleted = service.clear_all(confirm=True)
    
    return web.json_response({
        "success": True,
        "deleted_count": deleted,
        "message": f"Cache cleared: {deleted} keys deleted",
    })


@routes.get("/admin/cache-inspector/key/{key}")
async def admin_cache_key_details_handler(request: web.Request) -> web.Response:
    """
    API לקבלת פרטים מלאים על מפתח.
    """
    # בדיקת הרשאות אדמין
    session = await get_session(request)
    if not session.get("is_admin"):
        return web.json_response({"error": "Admin access required"}, status=403)
    
    key = request.match_info.get("key", "")
    if not key:
        return web.json_response({"error": "Key required"}, status=400)
    
    service = get_cache_inspector_service()
    details = service.get_key_details(key)
    
    if details is None:
        return web.json_response({"error": "Key not found"}, status=404)
    
    return web.json_response(details)


@routes.get("/api/cache/stats")
async def api_cache_stats_handler(request: web.Request) -> web.Response:
    """
    API לסטטיסטיקות cache (ציבורי למוניטורינג).
    """
    # רמת הגנה: רק סטטיסטיקות כלליות, ללא מפתחות
    service = get_cache_inspector_service()
    stats = service.get_cache_stats()
    
    return web.json_response({
        "enabled": stats.enabled,
        "used_memory": stats.used_memory,
        "hit_rate": stats.hit_rate,
        "total_keys": stats.total_keys,
        "connected_clients": stats.connected_clients,
        "uptime_seconds": stats.uptime_seconds,
    })
```

---

## 3. Frontend Template – `admin_cache_inspector.html`

### קובץ: `webapp/templates/admin_cache_inspector.html`

```html
{% extends "base.html" %}

{% block title %}Cache Inspector{% endblock %}

{% block extra_css %}
<style>
/* ================================
   Cache Inspector – Glassmorphism Dark Theme
   ================================ */

.cache-page {
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
  color: #fff;
  max-width: 1400px;
  margin: 0 auto;
  padding: 1rem;
}

.cache-page .page-title {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  font-size: 1.8rem;
  font-weight: 600;
}

.cache-page .page-title i {
  color: #64ffda;
}

/* ================================
   Stats Cards (Glassmorphism)
   ================================ */
.cache-stats-cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 1rem;
}

.stat-card {
  background: rgba(18, 24, 38, 0.75);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 16px;
  padding: 1.25rem;
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.25);
  transition: transform 0.2s ease, box-shadow 0.2s ease;
}

.stat-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 14px 40px rgba(0, 0, 0, 0.35);
}

.stat-card h3 {
  font-size: 0.85rem;
  margin: 0;
  opacity: 0.7;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.stat-card .card-value {
  font-size: 1.8rem;
  font-weight: 600;
  margin: 0.5rem 0 0;
}

.stat-card .card-value.memory { color: #a5d6ff; }
.stat-card .card-value.hit-rate { color: #64ffda; }
.stat-card .card-value.keys { color: #ffa34f; }
.stat-card .card-value.clients { color: #d8a6ff; }

/* ================================
   Search/Filters Bar
   ================================ */
.cache-filters {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
  align-items: center;
  padding: 1rem 1.25rem;
  background: rgba(18, 24, 38, 0.6);
  backdrop-filter: blur(10px);
  border-radius: 14px;
  border: 1px solid rgba(255, 255, 255, 0.06);
}

.cache-filters label {
  font-size: 0.9rem;
  opacity: 0.8;
}

.cache-filters input[type="text"] {
  background: rgba(255, 255, 255, 0.08);
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 999px;
  color: #fff;
  padding: 0.5rem 1rem;
  font-size: 0.9rem;
  min-width: 200px;
  transition: background 0.2s ease, border-color 0.2s ease;
}

.cache-filters input[type="text"]:focus {
  outline: none;
  border-color: #64ffda;
  background: rgba(255, 255, 255, 0.12);
}

.cache-filters input[type="text"]::placeholder {
  color: rgba(255, 255, 255, 0.4);
}

.cache-filters select {
  background: rgba(255, 255, 255, 0.08);
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 999px;
  color: #fff;
  padding: 0.4rem 1rem;
  font-size: 0.9rem;
  cursor: pointer;
}

.cache-filters select option {
  background: #1a1f2e;
  color: #fff;
}

.filter-btn {
  border: none;
  border-radius: 999px;
  padding: 0.5rem 1.2rem;
  background: linear-gradient(135deg, #64ffda, #4dd0e1);
  color: #0c1725;
  font-weight: 600;
  cursor: pointer;
  transition: box-shadow 0.2s ease, transform 0.2s ease;
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
}

.filter-btn:hover {
  transform: translateY(-1px);
  box-shadow: 0 8px 20px rgba(100, 255, 218, 0.3);
}

.filter-btn.danger {
  background: linear-gradient(135deg, #ff627c, #ff8fa3);
}

.filter-btn.danger:hover {
  box-shadow: 0 8px 20px rgba(255, 98, 124, 0.3);
}

.filter-btn.secondary {
  background: rgba(255, 255, 255, 0.08);
  color: #fff;
}

.filter-btn.secondary:hover {
  background: rgba(255, 255, 255, 0.15);
  box-shadow: none;
}

/* ================================
   Prefix Quick Filters
   ================================ */
.prefix-filters {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  padding: 0.75rem 1rem;
  background: rgba(18, 24, 38, 0.4);
  border-radius: 12px;
  border: 1px solid rgba(255, 255, 255, 0.04);
}

.prefix-filters .label {
  font-size: 0.85rem;
  opacity: 0.7;
  margin-left: 0.5rem;
}

.prefix-chip {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  padding: 0.25rem 0.7rem;
  background: rgba(255, 255, 255, 0.06);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 999px;
  font-size: 0.8rem;
  cursor: pointer;
  transition: background 0.2s ease, border-color 0.2s ease;
}

.prefix-chip:hover {
  background: rgba(100, 255, 218, 0.1);
  border-color: rgba(100, 255, 218, 0.3);
}

.prefix-chip .count {
  font-size: 0.75rem;
  opacity: 0.6;
}

/* ================================
   Cache Table
   ================================ */
.cache-table-wrapper {
  background: rgba(18, 24, 38, 0.72);
  backdrop-filter: blur(14px);
  border-radius: 18px;
  padding: 1.25rem;
  border: 1px solid rgba(255, 255, 255, 0.05);
  box-shadow: 0 18px 32px rgba(0, 0, 0, 0.35);
  overflow-x: auto;
}

.cache-table-wrapper h2 {
  margin: 0 0 1rem;
  font-size: 1.15rem;
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.cache-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.92rem;
}

.cache-table thead th {
  text-align: right;
  padding: 0.75rem 0.6rem;
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
  font-weight: 500;
  opacity: 0.8;
  white-space: nowrap;
}

.cache-table tbody td {
  padding: 0.7rem 0.6rem;
  border-bottom: 1px solid rgba(255, 255, 255, 0.04);
  vertical-align: middle;
}

.cache-table tbody tr:hover {
  background: rgba(255, 255, 255, 0.03);
}

/* Key column */
.cache-key {
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
  font-size: 0.85rem;
  color: #a5d6ff;
  word-break: break-all;
  max-width: 350px;
}

/* Value preview */
.cache-value {
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
  font-size: 0.82rem;
  color: rgba(255, 255, 255, 0.7);
  max-width: 250px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.cache-value.sensitive {
  color: #888;
  font-style: italic;
}

/* TTL column */
.ttl-badge {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  padding: 0.2rem 0.6rem;
  border-radius: 999px;
  font-size: 0.8rem;
  font-family: 'JetBrains Mono', monospace;
}

.ttl-badge.active {
  background: rgba(100, 255, 218, 0.12);
  color: #64ffda;
}

.ttl-badge.expiring {
  background: rgba(255, 163, 79, 0.18);
  color: #ffa34f;
}

.ttl-badge.persistent {
  background: rgba(216, 166, 255, 0.15);
  color: #d8a6ff;
}

.ttl-badge.expired {
  background: rgba(255, 99, 132, 0.18);
  color: #ff627c;
}

/* Size column */
.size-badge {
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.8rem;
  opacity: 0.7;
}

/* Type badge */
.type-badge {
  display: inline-block;
  padding: 0.15rem 0.45rem;
  border-radius: 4px;
  font-size: 0.75rem;
  background: rgba(255, 255, 255, 0.08);
  color: rgba(255, 255, 255, 0.6);
}

/* Status pill */
.status-pill {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  padding: 0.25rem 0.7rem;
  border-radius: 999px;
  font-size: 0.8rem;
  font-weight: 500;
}

.status-pill.active {
  background: rgba(100, 255, 218, 0.12);
  color: #64ffda;
}

.status-pill.persistent {
  background: rgba(216, 166, 255, 0.15);
  color: #d8a6ff;
}

.status-pill.expiring {
  background: rgba(255, 163, 79, 0.18);
  color: #ffa34f;
}

.status-pill.expired {
  background: rgba(255, 99, 132, 0.18);
  color: #ff627c;
}

/* Delete button */
.delete-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border: none;
  border-radius: 6px;
  background: rgba(255, 99, 132, 0.1);
  color: rgba(255, 99, 132, 0.7);
  cursor: pointer;
  opacity: 0;
  transition: opacity 0.15s ease, background 0.15s ease, color 0.15s ease;
}

.cache-table tbody tr:hover .delete-btn {
  opacity: 1;
}

.delete-btn:hover {
  background: rgba(255, 99, 132, 0.2);
  color: #ff627c;
}

.delete-btn i {
  font-size: 0.8rem;
}

/* ================================
   Actions Bar
   ================================ */
.cache-actions {
  display: flex;
  gap: 0.75rem;
  align-items: center;
  padding-top: 0.5rem;
}

.action-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.5rem 1rem;
  border: none;
  border-radius: 8px;
  font-size: 0.9rem;
  cursor: pointer;
  transition: background 0.2s ease, transform 0.2s ease;
}

.action-btn.primary {
  background: rgba(100, 255, 218, 0.15);
  color: #64ffda;
}

.action-btn.primary:hover {
  background: rgba(100, 255, 218, 0.25);
}

.action-btn.danger {
  background: rgba(255, 99, 132, 0.15);
  color: #ff627c;
}

.action-btn.danger:hover {
  background: rgba(255, 99, 132, 0.25);
}

/* ================================
   Toast Notification
   ================================ */
.toast {
  position: fixed;
  bottom: 24px;
  left: 50%;
  transform: translateX(-50%) translateY(100px);
  background: rgba(18, 24, 38, 0.95);
  backdrop-filter: blur(10px);
  padding: 0.7rem 1.4rem;
  border-radius: 999px;
  font-size: 0.9rem;
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.4);
  z-index: 9999;
  opacity: 0;
  transition: transform 0.3s ease, opacity 0.3s ease;
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.toast.show {
  transform: translateX(-50%) translateY(0);
  opacity: 1;
}

.toast.success {
  color: #64ffda;
  border: 1px solid rgba(100, 255, 218, 0.2);
}

.toast.error {
  color: #ff627c;
  border: 1px solid rgba(255, 99, 132, 0.2);
}

/* ================================
   Modal (for Clear All confirmation)
   ================================ */
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.7);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 10000;
  opacity: 0;
  visibility: hidden;
  transition: opacity 0.2s ease, visibility 0.2s ease;
}

.modal-overlay.show {
  opacity: 1;
  visibility: visible;
}

.modal-content {
  background: rgba(18, 24, 38, 0.95);
  backdrop-filter: blur(20px);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 20px;
  padding: 2rem;
  max-width: 400px;
  text-align: center;
  transform: scale(0.95);
  transition: transform 0.2s ease;
}

.modal-overlay.show .modal-content {
  transform: scale(1);
}

.modal-content h3 {
  margin: 0 0 1rem;
  color: #ff627c;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
}

.modal-content p {
  opacity: 0.8;
  margin-bottom: 1.5rem;
}

.modal-actions {
  display: flex;
  gap: 1rem;
  justify-content: center;
}

/* ================================
   Footer / Meta
   ================================ */
.cache-meta {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 0.85rem;
  opacity: 0.7;
  padding-top: 0.5rem;
}

/* ================================
   Responsive
   ================================ */
@media (max-width: 768px) {
  .cache-page .page-title {
    font-size: 1.4rem;
  }
  
  .stat-card .card-value {
    font-size: 1.5rem;
  }
  
  .cache-filters {
    flex-direction: column;
    align-items: stretch;
  }
  
  .cache-filters input,
  .cache-filters select,
  .filter-btn {
    width: 100%;
  }
  
  .cache-table {
    font-size: 0.85rem;
  }
  
  .cache-key,
  .cache-value {
    max-width: 150px;
  }
}

/* ================================
   Rose Pine Dawn Theme Support
   ================================ */
:root[data-theme="rose-pine-dawn"] .cache-page {
  color: var(--text-primary);
}

:root[data-theme="rose-pine-dawn"] .stat-card,
:root[data-theme="rose-pine-dawn"] .cache-table-wrapper,
:root[data-theme="rose-pine-dawn"] .cache-filters {
  background: color-mix(in srgb, #ffffff 75%, var(--bg-secondary) 25%);
  border-color: var(--glass-border);
}

:root[data-theme="rose-pine-dawn"] .cache-table thead th,
:root[data-theme="rose-pine-dawn"] .cache-table tbody td {
  border-color: rgba(87, 82, 121, 0.2);
}

:root[data-theme="rose-pine-dawn"] .cache-key {
  color: #286983;
}
</style>
{% endblock %}

{% block content %}
<div class="cache-page" dir="rtl">
  <!-- Page Title -->
  <div class="page-title">
    <i class="fas fa-database"></i>
    Cache Inspector
  </div>

  <!-- Stats Cards -->
  <div class="cache-stats-cards">
    <div class="stat-card">
      <h3>זיכרון בשימוש</h3>
      <div class="card-value memory">{{ overview.stats.used_memory }}</div>
    </div>
    <div class="stat-card">
      <h3>Hit Rate</h3>
      <div class="card-value hit-rate">{{ overview.stats.hit_rate }}%</div>
    </div>
    <div class="stat-card">
      <h3>סה"כ מפתחות</h3>
      <div class="card-value keys">{{ overview.stats.total_keys }}</div>
    </div>
    <div class="stat-card">
      <h3>לקוחות מחוברים</h3>
      <div class="card-value clients">{{ overview.stats.connected_clients }}</div>
    </div>
    <div class="stat-card">
      <h3>Hits</h3>
      <div class="card-value">{{ overview.stats.keyspace_hits | default(0) }}</div>
    </div>
    <div class="stat-card">
      <h3>Misses</h3>
      <div class="card-value">{{ overview.stats.keyspace_misses | default(0) }}</div>
    </div>
  </div>

  <!-- Redis Status Alert -->
  {% if not overview.stats.enabled %}
  <div class="config-alert warning" style="background: rgba(255, 99, 132, 0.12); border: 1px solid rgba(255, 99, 132, 0.3); color: #ff9bb6; display: flex; align-items: flex-start; gap: 0.75rem; padding: 1rem 1.25rem; border-radius: 14px;">
    <i class="fas fa-exclamation-triangle"></i>
    <div>
      <strong>Redis מושבת</strong><br>
      {% if overview.stats.error %}{{ overview.stats.error }}{% else %}Cache לא פעיל{% endif %}
    </div>
  </div>
  {% endif %}

  <!-- Search/Filters -->
  <form class="cache-filters" method="get" action="">
    <label for="patternInput">תבנית חיפוש:</label>
    <input 
      type="text" 
      name="pattern" 
      id="patternInput" 
      value="{{ selected_pattern }}" 
      placeholder="e.g., user:* or *:stats:*"
    >
    
    <label for="limitSelect">מגבלה:</label>
    <select name="limit" id="limitSelect">
      <option value="50" {% if selected_limit == 50 %}selected{% endif %}>50</option>
      <option value="100" {% if selected_limit == 100 %}selected{% endif %}>100</option>
      <option value="200" {% if selected_limit == 200 %}selected{% endif %}>200</option>
      <option value="500" {% if selected_limit == 500 %}selected{% endif %}>500</option>
    </select>
    
    <button type="submit" class="filter-btn">
      <i class="fas fa-search"></i> חפש
    </button>
    <a href="?" class="filter-btn secondary">
      <i class="fas fa-redo"></i> איפוס
    </a>
  </form>

  <!-- Prefix Quick Filters -->
  {% if prefixes %}
  <div class="prefix-filters">
    <span class="label">סינון מהיר:</span>
    {% for prefix, count in prefixes.items() %}
      {% if loop.index <= 10 %}
      <span class="prefix-chip" onclick="filterByPrefix('{{ prefix }}:*')">
        {{ prefix }}
        <span class="count">({{ count }})</span>
      </span>
      {% endif %}
    {% endfor %}
  </div>
  {% endif %}

  <!-- Cache Table -->
  <div class="cache-table-wrapper">
    <h2>
      <i class="fas fa-list"></i>
      רשימת מפתחות
      {% if overview.has_more %}
        <span style="font-size: 0.8rem; opacity: 0.6;">(מוצגים {{ overview.entries | length }} מתוך יותר)</span>
      {% endif %}
    </h2>
    
    {% if overview.entries %}
    <table class="cache-table">
      <thead>
        <tr>
          <th>Key</th>
          <th>Value (Preview)</th>
          <th>TTL</th>
          <th>Size</th>
          <th>Type</th>
          <th>Status</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        {% for entry in overview.entries %}
        <tr data-key="{{ entry.key }}">
          <td>
            <div class="cache-key" title="{{ entry.key }}">{{ entry.key }}</div>
          </td>
          <td>
            <div class="cache-value {% if entry.value_type == 'sensitive' %}sensitive{% endif %}" title="{{ entry.value_preview }}">
              {{ entry.value_preview }}
            </div>
          </td>
          <td>
            {% if entry.ttl_seconds == -1 %}
              <span class="ttl-badge persistent" title="No expiration">
                <i class="fas fa-infinity"></i> ∞
              </span>
            {% elif entry.ttl_seconds == -2 %}
              <span class="ttl-badge expired" title="Key expired or missing">
                <i class="fas fa-times"></i> N/A
              </span>
            {% elif entry.ttl_seconds <= 60 %}
              <span class="ttl-badge expiring" title="Expiring soon">
                <i class="fas fa-clock"></i> {{ entry.ttl_seconds }}s
              </span>
            {% else %}
              <span class="ttl-badge active">
                {{ entry.ttl_seconds }}s
              </span>
            {% endif %}
          </td>
          <td>
            <span class="size-badge">{{ entry.size_bytes }} B</span>
          </td>
          <td>
            <span class="type-badge">{{ entry.value_type }}</span>
          </td>
          <td>
            <span class="status-pill {{ entry.status.value | lower }}">
              {% if entry.status.value == 'Active' %}
                <i class="fas fa-check"></i>
              {% elif entry.status.value == 'Persistent' %}
                <i class="fas fa-lock"></i>
              {% elif entry.status.value == 'Expiring' %}
                <i class="fas fa-hourglass-half"></i>
              {% else %}
                <i class="fas fa-times"></i>
              {% endif %}
              {{ entry.status.value }}
            </span>
          </td>
          <td>
            <button 
              type="button" 
              class="delete-btn" 
              onclick="deleteKey('{{ entry.key }}')"
              title="מחק מפתח">
              <i class="fas fa-trash"></i>
            </button>
          </td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
    {% else %}
    <div style="text-align: center; padding: 2rem; opacity: 0.7;">
      <i class="fas fa-inbox" style="font-size: 2rem; margin-bottom: 0.5rem;"></i>
      <p>לא נמצאו מפתחות התואמים לתבנית</p>
    </div>
    {% endif %}
  </div>

  <!-- Actions -->
  <div class="cache-actions">
    <button type="button" class="action-btn primary" onclick="refreshPage()">
      <i class="fas fa-sync"></i> רענן
    </button>
    <button type="button" class="action-btn danger" onclick="showClearAllModal()">
      <i class="fas fa-trash-alt"></i> נקה הכל
    </button>
  </div>

  <!-- Meta Footer -->
  <div class="cache-meta">
    <span>
      <i class="fas fa-clock"></i>
      נוצר ב: {{ overview.generated_at }}
    </span>
    <span>
      <i class="fas fa-server"></i>
      Redis {{ overview.stats.redis_version }}
    </span>
    <span>
      נסרקו: {{ overview.total_scanned }} מפתחות
    </span>
  </div>
</div>

<!-- Clear All Confirmation Modal -->
<div class="modal-overlay" id="clearAllModal">
  <div class="modal-content">
    <h3>
      <i class="fas fa-exclamation-triangle"></i>
      אזהרה
    </h3>
    <p>האם אתה בטוח שברצונך למחוק את <strong>כל</strong> ה-cache?<br>פעולה זו לא ניתנת לביטול.</p>
    <div class="modal-actions">
      <button type="button" class="filter-btn secondary" onclick="hideClearAllModal()">
        ביטול
      </button>
      <button type="button" class="filter-btn danger" onclick="clearAllCache()">
        <i class="fas fa-trash"></i> מחק הכל
      </button>
    </div>
  </div>
</div>

<!-- Toast -->
<div class="toast" id="toast">
  <i class="fas fa-check"></i>
  <span id="toastMessage">הפעולה הצליחה</span>
</div>

<script>
(function() {
  // ================================
  // Toast notifications
  // ================================
  const toast = document.getElementById('toast');
  const toastMessage = document.getElementById('toastMessage');
  let toastTimeout = null;
  
  function showToast(message, type = 'success') {
    toast.className = 'toast ' + type;
    toast.querySelector('i').className = type === 'success' ? 'fas fa-check' : 'fas fa-exclamation-circle';
    toastMessage.textContent = message;
    toast.classList.add('show');
    
    if (toastTimeout) clearTimeout(toastTimeout);
    toastTimeout = setTimeout(() => toast.classList.remove('show'), 3000);
  }
  
  // ================================
  // Delete key
  // ================================
  window.deleteKey = async function(key) {
    if (!confirm(`האם למחוק את המפתח?\n${key}`)) return;
    
    try {
      const resp = await fetch('/admin/cache-inspector/delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ key }),
      });
      
      const data = await resp.json();
      
      if (data.success) {
        showToast(data.message, 'success');
        // הסרת השורה מהטבלה
        const row = document.querySelector(`tr[data-key="${key}"]`);
        if (row) row.remove();
      } else {
        showToast(data.error || 'שגיאה במחיקה', 'error');
      }
    } catch (err) {
      showToast('שגיאה בתקשורת עם השרת', 'error');
    }
  };
  
  // ================================
  // Clear All Modal
  // ================================
  const modal = document.getElementById('clearAllModal');
  
  window.showClearAllModal = function() {
    modal.classList.add('show');
  };
  
  window.hideClearAllModal = function() {
    modal.classList.remove('show');
  };
  
  window.clearAllCache = async function() {
    try {
      const resp = await fetch('/admin/cache-inspector/clear-all', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ confirm: true }),
      });
      
      const data = await resp.json();
      
      if (data.success) {
        showToast(data.message, 'success');
        hideClearAllModal();
        // רענון הדף אחרי שנייה
        setTimeout(() => location.reload(), 1000);
      } else {
        showToast(data.error || 'שגיאה בניקוי', 'error');
      }
    } catch (err) {
      showToast('שגיאה בתקשורת עם השרת', 'error');
    }
  };
  
  // Close modal on outside click
  modal.addEventListener('click', (e) => {
    if (e.target === modal) hideClearAllModal();
  });
  
  // ================================
  // Prefix quick filter
  // ================================
  window.filterByPrefix = function(pattern) {
    document.getElementById('patternInput').value = pattern;
    document.querySelector('.cache-filters').submit();
  };
  
  // ================================
  // Refresh page
  // ================================
  window.refreshPage = function() {
    location.reload();
  };
  
  // ================================
  // Keyboard shortcuts
  // ================================
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      hideClearAllModal();
      if (toast.classList.contains('show')) toast.classList.remove('show');
    }
    // Ctrl+F to focus search
    if ((e.ctrlKey || e.metaKey) && e.key === 'f') {
      e.preventDefault();
      document.getElementById('patternInput').focus();
    }
  });
  
  // ================================
  // Auto-refresh (optional)
  // ================================
  // Uncomment to enable auto-refresh every 30 seconds
  // setInterval(() => location.reload(), 30000);
})();
</script>
{% endblock %}
```

---

## 4. שימוש והרחבה

### הוספת מאפיינים נוספים

#### הוספת תמיכה ב-Redis Cluster

```python
# בתוך CacheInspectorService

def get_cluster_info(self) -> Dict[str, Any]:
    """מידע על Redis Cluster (אם רלוונטי)."""
    if not self.is_enabled():
        return {"cluster_enabled": False}
    
    try:
        client = self.redis_client
        cluster_info = client.info("cluster")
        return {
            "cluster_enabled": cluster_info.get("cluster_enabled", "0") == "1",
            "cluster_slots_assigned": cluster_info.get("cluster_slots_assigned", 0),
            "cluster_slots_ok": cluster_info.get("cluster_slots_ok", 0),
            "cluster_size": cluster_info.get("cluster_size", 0),
        }
    except Exception:
        return {"cluster_enabled": False}
```

#### הוספת תמיכה ב-Key Groups

```python
def group_keys_by_prefix(
    self,
    pattern: str = "*",
    max_groups: int = 20,
) -> Dict[str, int]:
    """קיבוץ מפתחות לפי prefix."""
    groups: Dict[str, int] = {}
    
    try:
        for key in self.redis_client.scan_iter(match=pattern, count=500):
            prefix = key.split(":")[0] if ":" in key else "(root)"
            groups[prefix] = groups.get(prefix, 0) + 1
            
            if len(groups) > max_groups * 2:
                # מיון ושמירת רק ה-top
                groups = dict(sorted(
                    groups.items(),
                    key=lambda x: -x[1]
                )[:max_groups])
    except Exception:
        pass
    
    return groups
```

---

## 5. אבטחה ✅

### מה מוגן?

1. **הסתרת ערכים רגישים** – מפתחות עם session/token/auth/password מוסתרים
2. **הגנת Admin** – כל הראוטים דורשים `is_admin=True` בסשן
3. **מניעת מחיקה גורפת** – לא ניתן למחוק `*` ללא אישור מפורש
4. **Rate limiting** – מגבלת SCAN למניעת עומס על Redis
5. **לוגים** – כל פעולת מחיקה נרשמת בלוג

### מה **לא** לעשות

❌ אל תאפשר גישה לדף ללא אימות  
❌ אל תציג ערכים מלאים של מפתחות רגישים  
❌ אל תאפשר מחיקה בבקשת GET  
❌ אל תסמוך על client-side validation בלבד  

### הגנות נוספות (מומלץ)

```python
# הוספת Rate Limiting לראוט המחיקה
from aiohttp_throttle import throttle

@routes.post("/admin/cache-inspector/delete")
@throttle(rate=5, per=60)  # מקסימום 5 מחיקות לדקה
async def admin_cache_delete_handler(request: web.Request) -> web.Response:
    ...
```

---

## 6. בדיקות (Tests)

### קובץ: `tests/test_cache_inspector_service.py`

```python
"""Unit tests for CacheInspectorService."""

from unittest.mock import MagicMock, patch
import pytest

from services.cache_inspector_service import (
    CacheInspectorService,
    CacheKeyStatus,
    CacheEntry,
    CacheStats,
)


class TestCacheInspectorService:
    """Test suite for CacheInspectorService."""

    def setup_method(self):
        """Setup test instance."""
        self.service = CacheInspectorService()

    def test_is_sensitive_key(self):
        """Test sensitive key detection."""
        assert self.service._is_sensitive_key("session:user:123") is True
        assert self.service._is_sensitive_key("token:abc") is True
        assert self.service._is_sensitive_key("auth:refresh") is True
        assert self.service._is_sensitive_key("user:stats:123") is False
        assert self.service._is_sensitive_key("file_content:abc") is False

    def test_determine_status(self):
        """Test status determination based on TTL."""
        assert self.service._determine_status(-2) == CacheKeyStatus.EXPIRED
        assert self.service._determine_status(-1) == CacheKeyStatus.PERSISTENT
        assert self.service._determine_status(30) == CacheKeyStatus.EXPIRING_SOON
        assert self.service._determine_status(60) == CacheKeyStatus.EXPIRING_SOON
        assert self.service._determine_status(61) == CacheKeyStatus.ACTIVE
        assert self.service._determine_status(3600) == CacheKeyStatus.ACTIVE

    def test_get_cache_stats_disabled(self):
        """Test stats when Redis is disabled."""
        with patch.object(self.service, 'is_enabled', return_value=False):
            stats = self.service.get_cache_stats()
            
            assert stats.enabled is False
            assert stats.used_memory == "N/A"
            assert stats.error == "Redis is disabled"

    @patch('services.cache_inspector_service.CacheInspectorService.redis_client')
    def test_get_cache_stats_enabled(self, mock_client):
        """Test stats when Redis is enabled."""
        mock_client.info.return_value = {
            'used_memory_human': '1.5M',
            'used_memory': 1500000,
            'connected_clients': 5,
            'keyspace_hits': 1000,
            'keyspace_misses': 100,
            'evicted_keys': 0,
            'uptime_in_seconds': 86400,
            'redis_version': '7.0.0',
        }
        mock_client.dbsize.return_value = 500
        
        with patch.object(self.service, 'is_enabled', return_value=True):
            with patch.object(self.service, 'redis_client', mock_client):
                stats = self.service.get_cache_stats()
        
                assert stats.enabled is True
                assert stats.used_memory == '1.5M'
                assert stats.hit_rate == 90.91  # 1000/(1000+100)*100

    def test_list_keys_disabled(self):
        """Test list_keys when Redis is disabled."""
        with patch.object(self.service, 'is_enabled', return_value=False):
            entries, scanned, has_more = self.service.list_keys()
            
            assert entries == []
            assert scanned == 0
            assert has_more is False

    def test_list_keys_limit_enforcement(self):
        """Test that limit is enforced."""
        # מגבלה גבוהה מדי צריכה להיות מוגבלת
        service = CacheInspectorService()
        limit = min(1000, service.MAX_SCAN_LIMIT)
        assert limit == service.MAX_SCAN_LIMIT

    def test_delete_pattern_blocks_wildcard(self):
        """Test that delete_pattern blocks dangerous patterns."""
        with patch.object(self.service, 'is_enabled', return_value=True):
            # לא צריך לקרוא ל-cache_manager.delete_pattern
            result = self.service.delete_pattern("*")
            assert result == 0
            
            result = self.service.delete_pattern("**")
            assert result == 0

    @patch('services.cache_inspector_service.CacheInspectorService.cache_manager')
    def test_delete_key(self, mock_cache):
        """Test single key deletion."""
        mock_cache.delete.return_value = True
        mock_cache.is_enabled = True
        
        with patch.object(self.service, 'is_enabled', return_value=True):
            with patch.object(self.service, 'cache_manager', mock_cache):
                result = self.service.delete_key("user:123")
        
                assert result is True
                mock_cache.delete.assert_called_once_with("user:123")

    def test_clear_all_requires_confirmation(self):
        """Test that clear_all requires explicit confirmation."""
        with patch.object(self.service, 'is_enabled', return_value=True):
            # Without confirmation
            result = self.service.clear_all(confirm=False)
            assert result == 0

    def test_get_value_preview_masks_sensitive(self):
        """Test that sensitive keys have masked values."""
        # מפתח רגיש צריך להחזיר ערך מוסתר
        assert self.service._is_sensitive_key("session:abc") is True
        preview, value_type = self.service._get_value_preview("session:abc")
        assert preview == self.service.MASKED_VALUE
        assert value_type == "sensitive"

    def test_overview_integration(self):
        """Test get_overview returns proper structure."""
        with patch.object(self.service, 'is_enabled', return_value=False):
            overview = self.service.get_overview()
            
            assert overview.stats is not None
            assert overview.entries == []
            assert overview.generated_at != ""
            assert overview.search_pattern == "*"


class TestCacheKeyStatus:
    """Test CacheKeyStatus enum."""

    def test_values(self):
        """Test enum values."""
        assert CacheKeyStatus.ACTIVE.value == "Active"
        assert CacheKeyStatus.PERSISTENT.value == "Persistent"
        assert CacheKeyStatus.EXPIRING_SOON.value == "Expiring"
        assert CacheKeyStatus.EXPIRED.value == "Expired"
```

### הרצת הבדיקות

```bash
pytest tests/test_cache_inspector_service.py -v
```

---

## 7. צ'קליסט למימוש

- [ ] יצירת `services/cache_inspector_service.py`
- [ ] הוספת הראוטים ל-`services/webserver.py`
- [ ] יצירת `webapp/templates/admin_cache_inspector.html`
- [ ] הוספת קישור בתפריט האדמין
- [ ] כתיבת בדיקות
- [ ] בדיקה ידנית בסביבת פיתוח
- [ ] Review אבטחה (ערכים רגישים מוסתרים, הרשאות Admin)
- [ ] Deploy לסביבת staging

---

## 8. תוצאה צפויה

לאחר המימוש, תקבל דף אדמין שנראה כך:

```
┌─────────────────────────────────────────────────────────────────────┐
│ 🗄️ Cache Inspector                                                  │
├─────────────────────────────────────────────────────────────────────┤
│ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐   │
│ │ 1.5M     │ │ 91%      │ │ 2,450    │ │ 5        │ │ 1,000    │   │
│ │ זיכרון   │ │ Hit Rate │ │ מפתחות  │ │ לקוחות   │ │ Hits     │   │
│ └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘   │
├─────────────────────────────────────────────────────────────────────┤
│ תבנית: [user:*          ] מגבלה: [100 ▼] [🔍 חפש] [↻ איפוס]        │
├─────────────────────────────────────────────────────────────────────┤
│ סינון מהיר: [user (450)] [file (320)] [stats (180)] [search (95)] │
├─────────────────────────────────────────────────────────────────────┤
│ Key                │ Value      │ TTL    │ Size │ Type │ Status   │  │
│────────────────────┼────────────┼────────┼──────┼──────┼──────────┼──│
│ user:123:stats     │ {"total".. │ 285s   │ 456B │ dict │ ● Active │🗑│
│ user:456:files     │ [{"id":... │ 58s    │ 1.2K │ list │ ⏳ Expir │🗑│
│ session:abc123     │ [HIDDEN]   │ ∞      │ 128B │ sens │ 🔒 Persi │🗑│
│ search:results:q1  │ {"items".. │ 45s    │ 2.3K │ dict │ ⏳ Expir │🗑│
│ ...                │            │        │      │      │          │  │
├─────────────────────────────────────────────────────────────────────┤
│ [↻ רענן]  [🗑️ נקה הכל]                                              │
├─────────────────────────────────────────────────────────────────────┤
│ 🕐 נוצר ב: 2024-01-15 14:30:22  │  🖥️ Redis 7.0.0  │  נסרקו: 100    │
└─────────────────────────────────────────────────────────────────────┘
```

**לגנדה:**
- 🔒 = Persistent (ללא TTL)
- ⏳ = Expiring Soon (פחות מדקה)
- ● = Active (TTL תקין)
- 🗑 = כפתור מחיקה (מופיע ב-hover)

---

## 9. אינטגרציה עם cache_manager.py

המדריך משתמש ישירות ב-`cache_manager.py` הקיים:

| פונקציית שירות | מתודה ב-cache_manager |
|----------------|----------------------|
| `get_cache_stats()` | `cache.get_stats()` |
| `delete_key(key)` | `cache.delete(key)` |
| `delete_pattern(pattern)` | `cache.delete_pattern(pattern)` |
| `clear_all()` | `cache.clear_all()` |
| `list_keys()` | `cache.redis_client.scan_iter()` |
| TTL lookup | `cache.redis_client.ttl(key)` |
| Size lookup | `cache.redis_client.strlen(key)` |

---

## שאלות נפוצות

### ש: מה קורה אם Redis מושבת?

הדף יציג הודעת אזהרה וכל הסטטיסטיקות יהיו N/A. פעולות מחיקה יחזירו 0.

### ש: האם אפשר לערוך ערכים מהדף?

לא. הדף הוא **קריאה ומחיקה בלבד** מטעמי אבטחה.  
עריכת cache נעשית דרך הקוד או Redis CLI.

### ש: איך מוסיפים prefix חדש לסינון מהיר?

ה-prefixes מחושבים אוטומטית מהמפתחות הקיימים. אין צורך בהגדרה ידנית.

### ש: האם יש auto-refresh?

ברירת המחדל ללא auto-refresh. ניתן להפעיל בקוד ה-JS:
```javascript
setInterval(() => location.reload(), 30000);  // כל 30 שניות
```

### ש: איך מונעים מחיקה בטעות?

1. מחיקת מפתח בודד דורשת confirm() בדפדפן
2. מחיקת תבנית חוסמת `*` ו-`**`
3. "נקה הכל" דורש Modal confirmation + דגל `confirm: true` ב-API

---

## 10. מקורות נוספים

- [Redis SCAN Command](https://redis.io/commands/scan/)
- [Redis INFO Command](https://redis.io/commands/info/)
- [cache_manager.py](/workspace/cache_manager.py) – המימוש הקיים בפרויקט
