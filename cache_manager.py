"""
מנהל Cache מתקדם עם Redis
Advanced Cache Manager with Redis
"""

import json
import logging
import os
import time
from functools import wraps
from typing import Any, Dict, List, Optional, Union, Callable, TypeVar, ParamSpec, Coroutine, cast, Tuple
import random
try:
    import redis
except Exception:  # redis אינו חובה – נריץ במצב מושבת אם חסר
    redis = None
import asyncio
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# מטריקות Prometheus (best-effort) — רישום חסין כפילויות
try:  # pragma: no cover
    from prometheus_client import Counter, Histogram, REGISTRY
except Exception:  # pragma: no cover
    Counter = Histogram = REGISTRY = None


def _ensure_metric(name: str, create_fn):
    """יוצר או מחזיר מטריקה קיימת באותו שם מ-REGISTRY.

    המטרה: למנוע ValueError על רישום כפול כאשר המודול נטען מחדש (importlib.reload).
    """
    # אם prometheus_client לא זמין, נחזיר None כדי שהקוד יקצר דרך best-effort
    if REGISTRY is None:
        try:
            return create_fn()  # ייתכן שמחזיר None ממילא
        except Exception:
            return None

    try:
        # שימוש ב-API פנימי אך יציב יחסית כדי לאתר קולקטור קיים
        existing = getattr(REGISTRY, "_names_to_collectors", {}).get(name)
        if existing is not None:
            return existing
    except Exception:
        # נפילה שקטה — ננסה ליצור ונחזור אם תתרחש כפילות
        pass

    try:
        return create_fn()
    except Exception:
        # במקרה של ValueError: Duplicated timeseries... נחפש ונחזיר את הקיים
        try:
            return getattr(REGISTRY, "_names_to_collectors", {}).get(name)
        except Exception:
            return None


# Cache metrics (labels kept minimal) — נרשמות באופן אידמפוטנטי
cache_hits_total = _ensure_metric(
    "cache_hits_total", lambda: Counter("cache_hits_total", "Total cache hits", ["backend"]) if Counter else None
)
cache_misses_total = _ensure_metric(
    "cache_misses_total", lambda: Counter("cache_misses_total", "Total cache misses", ["backend"]) if Counter else None
)
cache_op_duration_seconds = _ensure_metric(
    "cache_op_duration_seconds",
    lambda: Histogram(
        "cache_op_duration_seconds",
        "Cache operation duration in seconds",
        ["operation", "backend"],
    ) if Histogram else None,
)


# ===================== Dynamic TTL utilities =====================
class DynamicTTL:
    """ניהול TTL דינמי לפי סוג תוכן וקונטקסט.

    הערכים כאן מייצגים TTL בסיסי בשניות עבור סוגי תוכן שכיחים.
    """

    BASE_TTL: Dict[str, int] = {
        "user_stats": 300,         # 5 דקות
        "file_content": 3600,      # שעה
        "file_list": 60,           # דקה
        "markdown_render": 1800,   # 30 דקות
        "search_results": 180,     # 3 דקות
        "public_stats": 600,       # 10 דקות
        "bookmarks": 120,          # 2 דקות
        "tags": 300,               # 5 דקות
        "settings": 60,            # דקה
        # Collections (My Collections) – TTL מומלץ לפי המדריך
        "collections_list": 60,
        "collections_detail": 30,
        "collections_items": 30,
    }

    @classmethod
    def calculate_ttl(cls, content_type: str, context: Dict[str, Any] | None = None) -> int:
        """חשב TTL בסיסי מוכוון קונטקסט.

        מבטיח גבולות בטוחים: מינימום 30 שניות, מקסימום 7200 (שעתיים).
        """
        ctx: Dict[str, Any] = context or {}
        base_ttl: int = int(cls.BASE_TTL.get(content_type, 300))

        # התאמות לפי קונטקסט
        if bool(ctx.get("is_favorite")):
            base_ttl = int(base_ttl * 1.5)

        try:
            last_mod_hours = float(ctx.get("last_modified_hours_ago", 24))
        except Exception:
            last_mod_hours = 24.0
        if last_mod_hours < 1.0:
            base_ttl = int(base_ttl * 0.5)

        if str(ctx.get("access_frequency", "low")).lower() == "high":
            base_ttl = int(base_ttl * 2)

        if str(ctx.get("user_tier", "regular")).lower() == "premium":
            # משתמשי פרימיום יעדיפו עדכונים מהירים
            base_ttl = int(base_ttl * 0.7)

        return max(30, min(base_ttl, 7200))


class ActivityBasedTTL:
    """התאמת TTL לפי שעות פעילות (best-effort)."""

    @staticmethod
    def _now_hour() -> int:
        try:
            from datetime import datetime
            return int(datetime.now().hour)
        except Exception:
            return 12

    @classmethod
    def get_activity_multiplier(cls) -> float:
        hour = cls._now_hour()
        if 9 <= hour < 18:      # שעות שיא – קצר יותר
            return 0.7
        if 18 <= hour < 23:     # ערב – בינוני
            return 1.0
        return 1.5               # לילה – ארוך יותר

    @classmethod
    def adjust_ttl(cls, base_ttl: int) -> int:
        try:
            mult = float(cls.get_activity_multiplier())
        except Exception:
            mult = 1.0
        # הוסף jitter קטן למניעת thundering herd
        ttl = int(max(1, base_ttl) * mult)
        jitter = int(max(1, ttl // 10))  # עד ±10%
        try:
            ttl = ttl + random.randint(-jitter, jitter)
        except Exception:
            pass
        return max(30, min(int(ttl), 7200))


def build_cache_key(*parts: Any) -> str:
    """בניית מפתח cache יעיל ומובנה מהחלקים הנתונים.

    - מסנן חלקים ריקים
    - ממיר לתווים בטוחים (רווחים/סלאשים)
    - מגביל אורך ומוסיף hash קצר במידת הצורך
    """
    from hashlib import sha256

    clean_parts: List[str] = [str(p) for p in parts if p not in (None, "")]
    key: str = ":".join(clean_parts)
    key = key.replace(" ", "_").replace("/", "-")
    if len(key) > 200:
        key_hash = sha256(key.encode("utf-8")).hexdigest()[:8]
        key = f"{key[:150]}:{key_hash}"
    return key

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
                from config import config as _cfg
            except Exception:
                _cfg = None

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
        timer_ctx = cache_op_duration_seconds.labels(operation="get", backend=backend).time() if cache_op_duration_seconds else None
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
        timer_ctx = cache_op_duration_seconds.labels(operation="set", backend=backend).time() if cache_op_duration_seconds else None
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

    # ===================== Dynamic TTL helpers =====================
    def set_dynamic(
        self,
        key: str,
        value: Any,
        content_type: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """שמירה ב-cache עם TTL דינמי ותיעוד מינימלי במטריקות/לוגים."""
        # חישוב TTL דינמי וביצוע התאמות פעילות + jitter
        base_ttl = DynamicTTL.calculate_ttl(content_type, context or {})
        adjusted_ttl = ActivityBasedTTL.adjust_ttl(base_ttl)
        try:
            logger.debug(
                "cache_set_dynamic",
                extra={
                    "key": str(key)[:120],
                    "ttl": int(adjusted_ttl),
                    "content_type": str(content_type),
                },
            )
        except Exception:
            pass
        return self.set(key, value, int(adjusted_ttl))

    def get_with_refresh(
        self,
        key: str,
        refresh_func: Callable[[], Any],
        *,
        content_type: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """קריאה מ-cache; אם חסר – מחשב, שומר דינמית ומחזיר."""
        cached_value = self.get(key)
        if cached_value is not None:
            return cached_value
        fresh_value = refresh_func()
        if fresh_value is not None:
            try:
                self.set_dynamic(key, fresh_value, content_type, context)
            except Exception:
                # Fail-open: אם שמירה נכשלה לא נשבור זרימה
                pass
        return fresh_value

    def delete(self, key: str) -> bool:
        """מחיקת ערך מה-cache"""
        if not self.is_enabled:
            return False

        backend = "redis"
        timer_ctx = cache_op_duration_seconds.labels(operation="delete", backend=backend).time() if cache_op_duration_seconds else None
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
        timer_ctx = cache_op_duration_seconds.labels(operation="delete_pattern", backend=backend).time() if cache_op_duration_seconds else None
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

    def invalidate_user_cache(self, user_id: int) -> int:
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

    # ===================== Invalidation helpers (tag/pattern-based) =====================
    def invalidate_file_related(self, file_id: str, user_id: Optional[Union[int, str]] = None) -> int:
        """ביטול קאש לפי קובץ: תוכן/רינדור/רשימות.

        דפוסים נפוצים מעוגנים לאחור בהתאם למפתחות הקיימים בקוד.
        """
        if not self.is_enabled:
            return 0
        total = 0
        try:
            patterns = [
                f"file_content:{file_id}*",
                f"markdown_render:{file_id}*",
                f"md_render:{file_id}*",
            ]
            if user_id is not None:
                uid = str(user_id)
                patterns.extend([
                    f"web:files:user:{uid}:*",
                    f"user_files:*:{uid}:*",
                    f"latest_version:*:{uid}:*",
                ])
            for p in patterns:
                total += int(self.delete_pattern(p) or 0)
        except Exception as e:
            logger.warning(f"invalidate_file_related failed: {e}")
        return total

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


# ===================== Flask dynamic cache decorator =====================
P = ParamSpec("P")
R = TypeVar("R")


def dynamic_cache(content_type: str, key_prefix: Optional[str] = None) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """דקורטור ל-caching דינמי ל-Flask endpoints.

    - בונה מפתח קאש יציב הכולל משתמש/נתיב/פרמטרים
    - שומר רק טיפוסים serializable; עבור Response עם JSON שומר את ה-data בלבד
    - Fail-open: לעולם לא מפיל endpoint על בעיות קאש
    """
    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        @wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            try:
                # ייבוא מאוחר כדי להימנע מתלות פלצ'ית בזמן import מודולרי/טסטים
                try:
                    from flask import request, session, jsonify
                except Exception:  # pragma: no cover
                    request = None
                    session = {}
                    def jsonify(x):
                        return x

                # זיהוי משתמש וקונטקסט בסיסי
                uid = None
                try:
                    uid = session.get('user_id') if hasattr(session, 'get') else None
                except Exception:
                    uid = None
                try:
                    user_tier = (session.get('user_tier') or 'regular') if hasattr(session, 'get') else 'regular'
                except Exception:
                    user_tier = 'regular'

                # מפתח קאש: prefix/שם פונקציה + user + path + query
                prefix = key_prefix if key_prefix else getattr(func, "__name__", "endpoint")
                req_path = getattr(request, 'path', '') if request is not None else ''
                try:
                    q = request.query_string.decode(errors='ignore') if request is not None else ''
                except Exception:
                    q = ''
                cache_key = build_cache_key(prefix, str(uid or 'anonymous'), req_path, q)

                # ניסיון שליפה מהקאש
                cached_value = cache.get(cache_key)
                if cached_value is not None:
                    if isinstance(cached_value, dict):
                        return cast(R, jsonify(cached_value))
                    return cast(R, cached_value)

                # חישוב התוצאה
                result = func(*args, **kwargs)

                # אם זו תגובת Flask עם JSON — שמור רק את ה-data
                try:
                    if hasattr(result, 'get_json'):
                        data = result.get_json(silent=True)
                        if data is not None:
                            cache.set_dynamic(cache_key, data, content_type, {
                                'user_id': uid,
                                'user_tier': user_tier,
                                'endpoint': getattr(func, '__name__', ''),
                            })
                            return result
                except Exception:
                    pass

                # שמירה של טיפוסים serializable נפוצים
                if isinstance(result, (dict, list, str, int, float, bool)):
                    try:
                        cache.set_dynamic(cache_key, result, content_type, {
                            'user_id': uid,
                            'user_tier': user_tier,
                            'endpoint': getattr(func, '__name__', ''),
                        })
                    except Exception:
                        pass

                return result
            except Exception:
                # Fail-open על כל תקלה במנגנון הקאש
                return func(*args, **kwargs)

        return wrapper

    return decorator

# יצירת instance גלובלי
cache = CacheManager()

# Fallback in-process cache store (used when Redis disabled or on failures)
_local_cache_store: Dict[str, Tuple[float, Any]] = {}

def cached(expire_seconds: int = 300, key_prefix: str = "default"):
    """דקורטור לcaching פונקציות"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # יצירת מפתח cache
            cache_key = cache._make_key(key_prefix, func.__name__, *args, **kwargs)
            
            # בדיקה ב-cache (Redis/remote)
            result = cache.get(cache_key)
            if result is not None:
                logger.debug(f"Cache hit: {cache_key}")
                return result

            # בדיקת Fallback בזיכרון מקומי
            try:
                entry = _local_cache_store.get(cache_key)
                if entry is not None:
                    expires_at, local_value = entry
                    if float(expires_at) > time.time():
                        logger.debug(f"Local cache hit: {cache_key}")
                        return local_value
            except Exception:
                # לא חוסם זרימה במקרה של שגיאה בפולבק
                pass
            
            # הפעלת הפונקציה ושמירה ב-cache
            result = func(*args, **kwargs)
            wrote_remote = False
            try:
                wrote_remote = bool(cache.set(cache_key, result, expire_seconds))
            except Exception:
                wrote_remote = False

            # אם נכשל כתיבה לרימוט — שמור בזיכרון מקומי עם TTL
            if not wrote_remote:
                try:
                    _local_cache_store[cache_key] = (time.time() + float(expire_seconds), result)
                except Exception:
                    pass
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
            
            # בדיקה ב-cache (Redis/remote)
            result = cache.get(cache_key)
            if result is not None:
                logger.debug(f"Cache hit: {cache_key}")
                return result

            # בדיקת Fallback בזיכרון מקומי
            try:
                entry = _local_cache_store.get(cache_key)
                if entry is not None:
                    expires_at, local_value = entry
                    if float(expires_at) > time.time():
                        logger.debug(f"Local cache hit: {cache_key}")
                        return local_value
            except Exception:
                pass
            
            # הפעלת הפונקציה ושמירה ב-cache
            result = await func(*args, **kwargs)
            wrote_remote = False
            try:
                wrote_remote = bool(cache.set(cache_key, result, expire_seconds))
            except Exception:
                wrote_remote = False

            if not wrote_remote:
                try:
                    _local_cache_store[cache_key] = (time.time() + float(expire_seconds), result)
                except Exception:
                    pass
            logger.debug(f"Cache miss, stored: {cache_key}")
            
            return result
        return wrapper
    return decorator