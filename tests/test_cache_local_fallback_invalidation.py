"""ביטול קאש חייב לחול גם על הפולבק המקומי בזיכרון.

הרקע: כש-Redis אינו זמין הדקורטור ``cached`` כותב לפולבק מקומי, אבל כל
פונקציות ה-invalidation עברו דרך ``delete_pattern`` שיצא מיד ב-``return 0``
כשהקאש כבוי. התוצאה הייתה קאש שאי אפשר לבטל: ערך ישן שרד עד שה-TTL פג,
גם אחרי כתיבה מוצלחת.

זה שבר את גרסאות הקבצים: ``save_code_snippet`` גזר את מספר הגרסה הבאה
מערך מקוּש, וכך כמה גרסאות קיבלו את אותו מספר.
"""

import cache_manager
import pytest
from cache_manager import cache, cached


@pytest.fixture(autouse=True)
def clean_local_cache():
    cache_manager._local_cache_store.clear()
    yield
    cache_manager._local_cache_store.clear()


def _counting_fn():
    """פונקציה מקוּשה שמחזירה ערך חדש בכל קריאה אמיתית."""
    state = {"n": 0}

    @cached(expire_seconds=180, key_prefix="latest_version")
    def fn(user_id, file_name):
        state["n"] += 1
        return {"version": state["n"], "file_name": file_name}

    return fn


def test_local_fallback_is_populated_when_redis_is_down():
    """תנאי מוקדם: בלי Redis הערך אכן נשמר מקומית."""
    assert not cache.is_enabled, "הבדיקה מיועדת למצב שבו Redis אינו זמין"
    fn = _counting_fn()
    assert fn(7, "demo.md")["version"] == 1
    assert len(cache_manager._local_cache_store) == 1
    # בלי ביטול — הערך אכן נדבק, וזה מה שהופך את ה-invalidation לחובה
    assert fn(7, "demo.md")["version"] == 1


def test_invalidate_user_cache_clears_local_fallback():
    fn = _counting_fn()
    assert fn(7, "demo.md")["version"] == 1

    removed = cache.invalidate_user_cache(7)
    assert removed >= 1, "ביטול הקאש לא דיווח על מחיקה כלשהי"
    assert not cache_manager._local_cache_store, "הפולבק המקומי נשאר מזוהם"

    # הקריאה הבאה חייבת להגיע למקור ולא לקאש
    assert fn(7, "demo.md")["version"] == 2


def test_invalidate_file_related_clears_local_fallback():
    fn = _counting_fn()
    fn(7, "demo.md")

    cache.invalidate_file_related(file_id="demo.md", user_id=7)
    assert not cache_manager._local_cache_store
    assert fn(7, "demo.md")["version"] == 2


def test_invalidation_keeps_other_users_entries():
    """הביטול ממוקד: משתמש אחר לא אמור לאבד את הקאש שלו."""
    fn = _counting_fn()
    fn(7, "demo.md")
    fn(8, "demo.md")
    assert len(cache_manager._local_cache_store) == 2

    cache.invalidate_user_cache(7)
    assert len(cache_manager._local_cache_store) == 1, "נמחקו ערכים של משתמש אחר"


def test_clear_all_empties_local_fallback():
    fn = _counting_fn()
    fn(7, "demo.md")
    fn(8, "other.md")

    removed = cache.clear_all()
    assert removed >= 2
    assert not cache_manager._local_cache_store


def test_delete_pattern_matches_local_keys():
    """delete_pattern הוא הצוואר שכל ביטול עובר דרכו."""
    fn = _counting_fn()
    fn(7, "demo.md")

    assert cache.delete_pattern("nothing_matches:*") == 0
    assert len(cache_manager._local_cache_store) == 1

    assert cache.delete_pattern("latest_version:*") >= 1
    assert not cache_manager._local_cache_store


def test_clear_stale_reports_local_cleanup():
    """כשאין Redis, clear_stale עדיין מנקה פגי-תוקף — והמספר צריך לשקף את זה."""
    import time

    fn = _counting_fn()
    fn(7, "demo.md")
    # מזייפים פקיעה כדי שהניקוי ימצא מה למחוק
    for key in list(cache_manager._local_cache_store):
        _, payload = cache_manager._local_cache_store[key]
        cache_manager._local_cache_store[key] = (time.time() - 1, payload)

    removed = cache.clear_stale()
    assert removed >= 1, "clear_stale דיווח 0 למרות שניקה מקומית"
    assert not cache_manager._local_cache_store


def test_cleanup_local_cache_returns_removed_count():
    import time

    fn = _counting_fn()
    fn(7, "a.md")
    fn(8, "b.md")
    for key in list(cache_manager._local_cache_store):
        _, payload = cache_manager._local_cache_store[key]
        cache_manager._local_cache_store[key] = (time.time() - 1, payload)

    assert cache_manager._cleanup_local_cache(force=True) == 2
