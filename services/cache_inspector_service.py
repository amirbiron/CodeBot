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

    ACTIVE = "Active"  # מפתח פעיל עם TTL
    PERSISTENT = "Persistent"  # מפתח ללא TTL (לא יפוג)
    EXPIRING_SOON = "Expiring"  # יפוג תוך דקה
    EXPIRED = "Expired"  # פג תוקף (לא קיים)


@dataclass
class CacheEntry:
    """ערך cache בודד עם מטא-דאטה."""

    key: str
    value_preview: str  # תצוגה מקדימה מקוצרת
    ttl_seconds: int  # -1 = persistent, -2 = not exists
    size_bytes: int  # גודל משוער
    status: CacheKeyStatus
    value_type: str  # סוג הערך (string, dict, list, etc.)
    created_hint: str = ""  # רמז לזמן יצירה (אם זמין)


@dataclass
class CacheStats:
    """סטטיסטיקות כלליות של ה-cache."""

    enabled: bool
    used_memory: str  # e.g., "1.5M"
    used_memory_bytes: int
    connected_clients: int
    keyspace_hits: int
    keyspace_misses: int
    hit_rate: float  # אחוז hit rate
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
                preview = preview[: self.VALUE_PREVIEW_LENGTH] + "..."

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
            hits = info.get("keyspace_hits", 0)
            misses = info.get("keyspace_misses", 0)
            total_ops = hits + misses
            hit_rate = round((hits / total_ops * 100) if total_ops > 0 else 0, 2)

            return CacheStats(
                enabled=True,
                used_memory=info.get("used_memory_human", "N/A"),
                used_memory_bytes=info.get("used_memory", 0),
                connected_clients=info.get("connected_clients", 0),
                keyspace_hits=hits,
                keyspace_misses=misses,
                hit_rate=hit_rate,
                total_keys=total_keys,
                evicted_keys=info.get("evicted_keys", 0),
                uptime_seconds=info.get("uptime_in_seconds", 0),
                redis_version=info.get("redis_version", "N/A"),
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

                    entries.append(
                        CacheEntry(
                            key=key,
                            value_preview=preview,
                            ttl_seconds=ttl,
                            size_bytes=size,
                            status=status,
                            value_type=value_type,
                        )
                    )

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

