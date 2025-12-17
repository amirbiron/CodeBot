"""
Global Settings Service - הגדרות מערכת גלובליות הנשמרות ב-MongoDB.

מאפשר שליטה בזמן אמת על הגדרות מערכת ללא צורך באתחול השרת.
"""

import logging
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Default values for global settings
DEFAULTS: Dict[str, Any] = {
    'ENABLE_ANIMATIONS': True,  # מתג חירום לאנימציות
}

# In-memory cache for settings (with TTL)
_cache: Dict[str, Any] = {}
_cache_ts: float = 0.0
_CACHE_TTL_SECONDS: float = 30.0  # רענון מהמסד כל 30 שניות


def _get_settings_collection():
    """מחזיר את ה-collection של הגדרות המערכת."""
    try:
        from database.manager import get_db
        db = get_db()
        if db is None:
            return None
        return db.global_settings
    except Exception as e:
        logger.warning(f"Failed to get global_settings collection: {e}")
        return None


def _load_from_db() -> Dict[str, Any]:
    """טוען את כל ההגדרות מהמסד."""
    global _cache, _cache_ts
    
    try:
        collection = _get_settings_collection()
        if collection is None:
            return dict(DEFAULTS)
        
        # כל ההגדרות נשמרות כמסמך יחיד עם _id='global'
        doc = collection.find_one({'_id': 'global'})
        if doc:
            # מיזוג עם defaults (במקרה שיש הגדרות חדשות שעדיין לא במסד)
            settings = dict(DEFAULTS)
            settings.update({k: v for k, v in doc.items() if k != '_id'})
            _cache = settings
            _cache_ts = time.time()
            return settings
        else:
            # אין מסמך - יצירת מסמך ראשוני
            try:
                collection.insert_one({'_id': 'global', **DEFAULTS})
            except Exception:
                pass  # אולי כבר קיים (race condition)
            _cache = dict(DEFAULTS)
            _cache_ts = time.time()
            return _cache
    except Exception as e:
        logger.error(f"Error loading global settings: {e}")
        return dict(DEFAULTS)


def _get_cached_settings() -> Dict[str, Any]:
    """מחזיר הגדרות מה-cache או טוען מהמסד אם ה-cache פג."""
    global _cache, _cache_ts
    
    now = time.time()
    if not _cache or (now - _cache_ts) > _CACHE_TTL_SECONDS:
        return _load_from_db()
    return _cache


def get(key: str, default: Any = None) -> Any:
    """
    מחזיר ערך הגדרה גלובלית.
    
    Args:
        key: שם ההגדרה
        default: ערך ברירת מחדל אם לא קיים
        
    Returns:
        ערך ההגדרה
    """
    settings = _get_cached_settings()
    if key in settings:
        return settings[key]
    return default if default is not None else DEFAULTS.get(key)


def get_all() -> Dict[str, Any]:
    """מחזיר את כל ההגדרות הגלובליות."""
    return dict(_get_cached_settings())


def set(key: str, value: Any) -> bool:
    """
    שומר ערך הגדרה גלובלית.
    
    Args:
        key: שם ההגדרה
        value: הערך לשמירה
        
    Returns:
        True אם השמירה הצליחה
    """
    global _cache, _cache_ts
    
    try:
        collection = _get_settings_collection()
        if collection is None:
            logger.error("Cannot save setting: no database connection")
            return False
        
        # עדכון במסד
        result = collection.update_one(
            {'_id': 'global'},
            {'$set': {key: value}},
            upsert=True
        )
        
        # עדכון ה-cache
        if _cache:
            _cache[key] = value
        _cache_ts = time.time()
        
        logger.info(f"Global setting updated: {key}={value}")
        return True
        
    except Exception as e:
        logger.error(f"Error saving global setting {key}: {e}")
        return False


def set_many(settings: Dict[str, Any]) -> bool:
    """
    שומר מספר הגדרות בבת אחת.
    
    Args:
        settings: מילון של הגדרות
        
    Returns:
        True אם השמירה הצליחה
    """
    global _cache, _cache_ts
    
    try:
        collection = _get_settings_collection()
        if collection is None:
            return False
        
        result = collection.update_one(
            {'_id': 'global'},
            {'$set': settings},
            upsert=True
        )
        
        # עדכון ה-cache
        if _cache:
            _cache.update(settings)
        _cache_ts = time.time()
        
        logger.info(f"Global settings updated: {list(settings.keys())}")
        return True
        
    except Exception as e:
        logger.error(f"Error saving global settings: {e}")
        return False


def invalidate_cache():
    """מנקה את ה-cache ומכריח טעינה מחדש מהמסד."""
    global _cache, _cache_ts
    _cache = {}
    _cache_ts = 0.0


# Convenience functions for specific settings

def is_animations_enabled() -> bool:
    """בודק אם האנימציות מופעלות ברמת המערכת."""
    return bool(get('ENABLE_ANIMATIONS', True))


def set_animations_enabled(enabled: bool) -> bool:
    """מפעיל או מכבה את האנימציות ברמת המערכת."""
    return set('ENABLE_ANIMATIONS', bool(enabled))
