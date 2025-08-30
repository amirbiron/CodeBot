"""
מנהל Cache מתקדם עם Redis
Advanced Cache Manager with Redis
"""

import json
import logging
import os
from functools import wraps
from typing import Any, Dict, List, Optional, Union
import redis
import asyncio
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

class CacheManager:
    """מנהל Cache מתקדם עם Redis"""
    
    def __init__(self):
        self.redis_client = None
        self.is_enabled = False
        self.connect()
    
    def connect(self):
        """התחברות ל-Redis"""
        try:
            redis_url = os.getenv('REDIS_URL')
            if not redis_url or redis_url.strip() == "" or redis_url.startswith("disabled"):
                self.is_enabled = False
                logger.info("Redis אינו מוגדר - Cache מושבת")
                return
            
            self.redis_client = redis.from_url(
                redis_url,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5,
                retry_on_timeout=True,
                health_check_interval=30
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
            
        try:
            value = self.redis_client.get(key)
            if value:
                return json.loads(value)
        except Exception as e:
            logger.error(f"שגיאה בקריאה מ-cache: {e}")
        
        return None
    
    def set(self, key: str, value: Any, expire_seconds: int = 300) -> bool:
        """שמירת ערך ב-cache"""
        if not self.is_enabled:
            return False
            
        try:
            serialized = json.dumps(value, default=str, ensure_ascii=False)
            return self.redis_client.setex(key, expire_seconds, serialized)
        except Exception as e:
            logger.error(f"שגיאה בכתיבה ל-cache: {e}")
            return False
    
    def delete(self, key: str) -> bool:
        """מחיקת ערך מה-cache"""
        if not self.is_enabled:
            return False
            
        try:
            return bool(self.redis_client.delete(key))
        except Exception as e:
            logger.error(f"שגיאה במחיקה מ-cache: {e}")
            return False
    
    def delete_pattern(self, pattern: str) -> int:
        """מחיקת כל המפתחות שמתאימים לתבנית"""
        if not self.is_enabled:
            return 0
            
        try:
            keys = self.redis_client.keys(pattern)
            if keys:
                return self.redis_client.delete(*keys)
            return 0
        except Exception as e:
            logger.error(f"שגיאה במחיקת תבנית מ-cache: {e}")
            return 0
    
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
                f"*:{user_id}:*",                      # נפילה לאחור: כל מפתח שמכיל את המזהה
            ]
            for p in patterns:
                total_deleted += int(self.delete_pattern(p) or 0)
        except Exception as e:
            logger.warning(f"invalidate_user_cache failed for user {user_id}: {e}")
        logger.info(f"נמחקו {total_deleted} ערכי cache עבור משתמש {user_id}")
        return total_deleted
    
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