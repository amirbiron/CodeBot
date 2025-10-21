"""
מנהל Cache מתקדם עם Redis
Advanced Cache Manager with Redis
"""

import json
import logging
import os
import time
from functools import wraps
from typing import Any, Dict, List, Optional, Union
try:
    import redis  # type: ignore
except Exception:  # redis אינו חובה – נריץ במצב מושבת אם חסר
    redis = None  # type: ignore[assignment]
import asyncio
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# מטריקות Prometheus (best-effort)
try:  # pragma: no cover
    from prometheus_client import Counter, Histogram
except Exception:  # pragma: no cover
    Counter = Histogram = None  # type: ignore

# Cache metrics (labels kept minimal)
cache_hits_total = (
    Counter("cache_hits_total", "Total cache hits", ["backend"]) if Counter else None
)
cache_misses_total = (
    Counter("cache_misses_total", "Total cache misses", ["backend"]) if Counter else None
)
cache_op_duration_seconds = (
    Histogram(
        "cache_op_duration_seconds",
        "Cache operation duration in seconds",
        ["operation", "backend"],
    )
    if Histogram
    else None
)

class CacheManager:
    """מנהל Cache מתקדם עם Redis"""
    
    def __init__(self):
        self.redis_client = None
        self.is_enabled = False
        self.connect()
    
    def connect(self):
        """התחברות ל-Redis"""
        try:
            if redis is None:
                self.is_enabled = False
                logger.info("חבילת redis לא מותקנת – Cache מושבת")
                return
            # קונפיג דרך pydantic אם זמין, אחרת ENV ישיר – לשמירת תאימות
            try:
                from config import config as _cfg  # type: ignore
            except Exception:
                _cfg = None  # type: ignore

            redis_url = (getattr(_cfg, 'REDIS_URL', None) if _cfg is not None else None) or os.getenv('REDIS_URL')
            if not redis_url or redis_url.strip() == "" or redis_url.startswith("disabled"):
                self.is_enabled = False
                logger.info("Redis אינו מוגדר - Cache מושבת")
                return
            
            # כיבוד timeouts מה-ENV, עם ברירות מחדל שמרניות ב-SAFE_MODE
            safe_mode = str(os.getenv("SAFE_MODE", "")).lower() in ("1", "true", "yes", "y", "on")
            # כבד קונפיג מפורש גם אם הערך 0.0, אל תשתמש ב-or שמבטל 0
            connect_timeout_cfg = (getattr(_cfg, 'REDIS_CONNECT_TIMEOUT', None) if _cfg is not None else None)
            socket_timeout_cfg = (getattr(_cfg, 'REDIS_SOCKET_TIMEOUT', None) if _cfg is not None else None)
            connect_timeout_env = os.getenv("REDIS_CONNECT_TIMEOUT")
            socket_timeout_env = os.getenv("REDIS_SOCKET_TIMEOUT")

            if connect_timeout_cfg is not None:
                socket_connect_timeout = float(connect_timeout_cfg)
            elif connect_timeout_env is not None:
                socket_connect_timeout = float(connect_timeout_env)
            else:
                socket_connect_timeout = float("1" if safe_mode else "5")

            if socket_timeout_cfg is not None:
                socket_timeout = float(socket_timeout_cfg)
            elif socket_timeout_env is not None:
                socket_timeout = float(socket_timeout_env)
            else:
                socket_timeout = float("1" if safe_mode else "5")

            try:
                max_conns_env = (
                    (str(getattr(_cfg, 'REDIS_MAX_CONNECTIONS', '') or '') if _cfg is not None else '')
                    or os.getenv("REDIS_MAX_CONNECTIONS")
                )
                max_connections = int(max_conns_env) if max_conns_env not in (None, "") else int(getattr(_cfg, 'REDIS_MAX_CONNECTIONS', 50) if _cfg is not None else 50)
            except Exception:
                max_connections = int(getattr(_cfg, 'REDIS_MAX_CONNECTIONS', 50) if _cfg is not None else 50)

            self.redis_client = redis.from_url(
                redis_url,
                decode_responses=True,
                socket_connect_timeout=socket_connect_timeout,
                socket_timeout=socket_timeout,
                retry_on_timeout=True,
                health_check_interval=30,
                max_connections=max_connections,
            )
            
            # בדיקת חיבור
            self.redis_client.ping()
            self.is_enabled = True
            
            logger.info("התחברות ל-Redis הצליחה - Cache מופעל")
            
        except Exception as e:
            logger.warning(f"לא ניתן להתחבר ל-Redis: {e} - Cache מושבת")
            self.is_enabled = False
    
    def _make_key(self, prefix: str, *args, **kwargs) -> str:
        """יוצר מפתח cache ייחודי"""
        key_parts = [prefix]
        key_parts.extend(str(arg) for arg in args)
        
        if kwargs:
            sorted_kwargs = sorted(kwargs.items())
            key_parts.extend(f"{k}:{v}" for k, v in sorted_kwargs)
        
        return ":".join(key_parts)
    
    def get(self, key: str) -> Optional[Any]:
        """קבלת ערך מה-cache"""
        if not self.is_enabled:
            return None

        backend = "redis"
        timer_ctx = cache_op_duration_seconds.labels(operation="get", backend=backend).time() if cache_op_duration_seconds else None  # type: ignore
        try:
            value = self.redis_client.get(key)
            if value:
                if cache_hits_total is not None:
                    cache_hits_total.labels(backend=backend).inc()
                return json.loads(value)
            if cache_misses_total is not None:
                cache_misses_total.labels(backend=backend).inc()
        except Exception as e:
            logger.error(f"שגיאה בקריאה מ-cache: {e}")
        finally:
            try:
                if timer_ctx:
                    timer_ctx()  # stop timer
            except Exception:
                pass
        return None
    
    def set(self, key: str, value: Any, expire_seconds: int = 300) -> bool:
        """שמירת ערך ב-cache"""
        if not self.is_enabled:
            return False

        backend = "redis"
        timer_ctx = cache_op_duration_seconds.labels(operation="set", backend=backend).time() if cache_op_duration_seconds else None  # type: ignore
        try:
            serialized = json.dumps(value, default=str, ensure_ascii=False)
            # תמיכה בלקוחות ללא setex: ננסה set(ex=) או set+expire
            client = self.redis_client
            if hasattr(client, 'setex'):
                return bool(client.setex(key, expire_seconds, serialized))
            # חלק מהלקוחות תומכים ב-ex ב-set
            try:
                return bool(client.set(key, serialized, ex=expire_seconds))
            except Exception:
                pass
            # נסה set ואז expire
            ok = bool(client.set(key, serialized))
            try:
                _ = client.expire(key, int(expire_seconds))
            except Exception:
                pass
            return ok
        except Exception as e:
            logger.error(f"שגיאה בכתיבה ל-cache: {e}")
            return False
        finally:
            try:
                if timer_ctx:
                    timer_ctx()
            except Exception:
                pass
    
    def delete(self, key: str) -> bool:
        """מחיקת ערך מה-cache"""
        if not self.is_enabled:
            return False

        backend = "redis"
        timer_ctx = cache_op_duration_seconds.labels(operation="delete", backend=backend).time() if cache_op_duration_seconds else None  # type: ignore
        try:
            return bool(self.redis_client.delete(key))
        except Exception as e:
            logger.error(f"שגיאה במחיקה מ-cache: {e}")
            return False
        finally:
            try:
                if timer_ctx:
                    timer_ctx()
            except Exception:
                pass
    
    def delete_pattern(self, pattern: str) -> int:
        """מחיקת כל המפתחות שמתאימים לתבנית"""
        if not self.is_enabled:
            return 0

        backend = "redis"
        timer_ctx = cache_op_duration_seconds.labels(operation="delete_pattern", backend=backend).time() if cache_op_duration_seconds else None  # type: ignore
        try:
            keys = self.redis_client.keys(pattern)
            if keys:
                return self.redis_client.delete(*keys)
            return 0
        except Exception as e:
            logger.error(f"שגיאה במחיקת תבנית מ-cache: {e}")
            return 0
        finally:
            try:
                if timer_ctx:
                    timer_ctx()
            except Exception:
                pass
    
    def invalidate_user_cache(self, user_id: int):
        """מחיקת כל ה-cache של משתמש ספציפי"""
        # התאמה רחבה יותר למפתחות כפי שהם נוצרים כיום ב-_make_key
        # המפתחות נראים כך: "<prefix>:<func_name>:<self>:<user_id>:..."
        # לכן נמחק לפי prefixes הרלוונטיים ולפי user_id גולמי.
        total_deleted = 0
        try:
            patterns = [
                f"*:user:{user_id}:*",                 # תמיכה לאחור אם יתווסף prefix "user:" בעתיד
                f"user_files:*:{user_id}:*",           # רשימת קבצי משתמש
                f"latest_version:*:{user_id}:*",       # גרסה אחרונה לקובץ
                f"search_code:*:{user_id}:*",          # תוצאות חיפוש למשתמש
                f"user_stats:*:{user_id}",             # סטטיסטיקות משתמש — מסתיים ב-:<user_id>
                f"user_stats:*:{user_id}:*",           # גיבוי: אם יתווספו פרמטרים/סופיות בעתיד
                f"*:{user_id}:*",                      # נפילה לאחור: כל מפתח שמכיל את המזהה
                f"*:{user_id}",                        # נפילה לאחור: מפתחות שמסתיימים במזהה
            ]
            for p in patterns:
                total_deleted += int(self.delete_pattern(p) or 0)
        except Exception as e:
            logger.warning(f"invalidate_user_cache failed for user {user_id}: {e}")
        logger.info(f"נמחקו {total_deleted} ערכי cache עבור משתמש {user_id}")
        return total_deleted

    def clear_all(self) -> int:
        """ניקוי כל המטמון באופן מבוקר.

        - אם Redis מושבת – מחזיר 0.
        - אם Redis פעיל – מוחק את כל המפתחות באמצעות SCAN+DEL (best-effort).
        """
        if not self.is_enabled:
            return 0
        deleted = 0
        try:
            client = self.redis_client
            # תקציב זמן לניקוי כדי לא לחסום worker אם Redis איטי
            budget_seconds = float(os.getenv("CACHE_CLEAR_BUDGET_SECONDS", "2"))
            deadline = time.time() + max(0.0, budget_seconds)
            if hasattr(client, 'scan_iter'):
                for k in client.scan_iter(match='*', count=500):
                    if time.time() > deadline:
                        break
                    try:
                        deleted += int(client.delete(k) or 0)
                    except Exception:
                        pass
                    if time.time() > deadline:
                        break
            else:
                # Fallback: keys + delete
                keys = client.keys('*')
                if keys:
                    deleted = int(client.delete(*keys) or 0)
        except Exception as e:
            logger.warning(f"clear_all failed: {e}")
        logger.info(f"ניקוי cache מלא: {deleted} מפתחות נמחקו")
        return deleted

    def clear_stale(self, max_scan: int = 1000, ttl_seconds_threshold: int = 60) -> int:
        """מחיקת מפתחות שכבר עומדים לפוג ("stale") בצורה עדינה.

        היגיון:
        - אם Redis מושבת – החזר 0.
        - סריקה מדורגת (SCAN) של עד max_scan מפתחות.
        - מחיקה רק למפתחות עם TTL חיובי קטן מ-ttl_seconds_threshold, או TTL שלילי המציין שאינו קיים.
        - לא מוחקים מפתחות ללא TTL (ttl == -1) כדי להימנע מפגיעה בקאש ארוך-חיים.
        """
        if not self.is_enabled:
            return 0

        # דילוג בטוח במצב SAFE_MODE או אם ביקשו לבטל תחזוקת קאש
        if str(os.getenv("SAFE_MODE", "")).lower() in ("1", "true", "yes", "y", "on") or \
           str(os.getenv("DISABLE_CACHE_MAINTENANCE", "")).lower() in ("1", "true", "yes", "y", "on"):
            logger.info("SAFE_MODE/disable flag פעיל — דילוג על clear_stale")
            return 0
        deleted = 0
        scanned = 0
        try:
            client = self.redis_client
            # בדיקת חיות מהירה כדי להיכשל מוקדם
            try:
                _ = client.ping()
            except Exception:
                logger.warning("clear_stale: Redis לא מגיב — דילוג על הניקוי")
                return 0

            # תקציב זמן לניקוי כדי לא לחסום worker אם Redis איטי
            budget_seconds = float(os.getenv("CACHE_CLEAR_BUDGET_SECONDS", "1"))
            deadline = time.time() + max(0.0, budget_seconds)
            # עדיפות ל-scan_iter כדי להימנע מ-blocking
            if hasattr(client, 'scan_iter') and hasattr(client, 'ttl'):
                for k in client.scan_iter(match='*', count=500):
                    if time.time() > deadline:
                        break
                    scanned += 1
                    try:
                        ttl = int(client.ttl(k))
                    except Exception:
                        ttl = -2  # התייחסות כמפתח לא קיים/פג
                    # מחיקה רק אם TTL קצר (<= threshold) או לא קיים (-2)
                    if ttl == -2 or (ttl >= 0 and ttl <= int(ttl_seconds_threshold)):
                        try:
                            deleted += int(client.delete(k) or 0)
                        except Exception:
                            pass
                    # הפסקה כשעברנו את מכסת הסריקות או התקציב
                    if scanned >= int(max_scan) or time.time() > deadline:
                        break
            else:
                # Fallback זהיר: אל תמחק גורף אם אין יכולות TTL/SCAN
                return 0
        except Exception as e:
            logger.warning(f"clear_stale failed: {e}")
        logger.info(f"ניקוי cache עדין (stale): נסרקו {scanned} / נמחקו {deleted}")
        return deleted
    
    def get_stats(self) -> Dict[str, Any]:
        """סטטיסטיקות cache"""
        if not self.is_enabled:
            return {"enabled": False}
            
        try:
            info = self.redis_client.info()
            return {
                "enabled": True,
                "used_memory": info.get('used_memory_human', 'N/A'),
                "connected_clients": info.get('connected_clients', 0),
                "keyspace_hits": info.get('keyspace_hits', 0),
                "keyspace_misses": info.get('keyspace_misses', 0),
                "hit_rate": round(
                    info.get('keyspace_hits', 0) / 
                    max(info.get('keyspace_hits', 0) + info.get('keyspace_misses', 0), 1) * 100, 
                    2
                )
            }
        except Exception as e:
            logger.error(f"שגיאה בקבלת סטטיסטיקות cache: {e}")
            return {"enabled": True, "error": str(e)}

# יצירת instance גלובלי
cache = CacheManager()

def cached(expire_seconds: int = 300, key_prefix: str = "default"):
    """דקורטור לcaching פונקציות"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # יצירת מפתח cache
            cache_key = cache._make_key(key_prefix, func.__name__, *args, **kwargs)
            
            # בדיקה ב-cache
            result = cache.get(cache_key)
            if result is not None:
                logger.debug(f"Cache hit: {cache_key}")
                return result
            
            # הפעלת הפונקציה ושמירה ב-cache
            result = func(*args, **kwargs)
            cache.set(cache_key, result, expire_seconds)
            logger.debug(f"Cache miss, stored: {cache_key}")
            
            return result
        return wrapper
    return decorator

def async_cached(expire_seconds: int = 300, key_prefix: str = "default"):
    """דקורטור לcaching פונקציות async"""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # יצירת מפתח cache
            cache_key = cache._make_key(key_prefix, func.__name__, *args, **kwargs)
            
            # בדיקה ב-cache
            result = cache.get(cache_key)
            if result is not None:
                logger.debug(f"Cache hit: {cache_key}")
                return result
            
            # הפעלת הפונקציה ושמירה ב-cache
            result = await func(*args, **kwargs)
            cache.set(cache_key, result, expire_seconds)
            logger.debug(f"Cache miss, stored: {cache_key}")
            
            return result
        return wrapper
    return decorator