"""ביטול הקאש במיגרציה מדווח **מה שנמדד**, לא היעדר חריגה.

הרקע (K11 ו-``return-value-failure-unchecked`` §4): ``invalidate_user_cache``
עוטף את כל גופו ב-``except Exception`` ומחזיר ``int``. הוא אינו זורק, ולכן
‏``try/except`` סביבו הוא ``except`` שלא ירוץ לעולם — וספירת "הקריאה חזרה"
אינה ספירה של מפתחות שנמחקו. הגרסה הקודמת בדיוק עשתה את זה, ואז העמוד
דיווח לאדמין "קאש בוטל עבור X משתמשים".

הבדיקות כאן אינן נוגעות במונגו: היחידה הנבדקת היא פונקציה טהורה מעל
אובייקט הקאש, ולכן הקריאה הישירה **היא** הממשק (``TESTING-PATTERNS`` T1,
סעיף ה-false-positives).
"""

from __future__ import annotations

import pytest

from services import created_at_migration as mig


class _CountingCache:
    """קאש מדומה שמחזיר מספר ידוע — ומתעד את מי שנקרא עבורו.

    מדמה את **החוזה** של ``CacheManager``: לא זורק לעולם, ומסמן את
    התוצאה בערך ההחזרה בלבד.
    """

    def __init__(self, per_user: int = 3, is_enabled: bool = True):
        self.per_user = per_user
        self.is_enabled = is_enabled
        self.calls: list[int] = []

    def invalidate_user_cache(self, user_id: int) -> int:
        self.calls.append(user_id)
        return self.per_user


@pytest.fixture
def use_cache(monkeypatch):
    """מזריק קאש מדומה למודול ``cache_manager`` שהשירות מייבא ממנו."""

    def _install(cache_obj):
        import cache_manager

        monkeypatch.setattr(cache_manager, "cache", cache_obj, raising=False)
        return cache_obj

    return _install


def test_report_counts_keys_actually_deleted(use_cache):
    """המספר בדו"ח הוא סכום ערכי ההחזרה, לא מספר הקריאות שלא נפלו."""
    cache = use_cache(_CountingCache(per_user=3))

    report = mig._invalidate_users([11, 22])

    assert cache.calls == [11, 22]
    assert report["users"] == 2
    assert report["keys_deleted"] == 6, "נספרו קריאות במקום מפתחות"
    assert report["backend"] is True


def test_zero_keys_is_not_reported_as_failure(use_cache):
    """קאש קר מחזיר 0 — וזה מצב תקין, לא כשל.

    לפי K11 הקובע הוא החוזה של הפונקציה: מפתח קיים רק אם מישהו שלף
    קודם את רשימת הקבצים. סימון 0 ככשל היה מציף אזהרה על כל מיגרציה
    שרצה על משתמש שלא נכנס לאתר.
    """
    use_cache(_CountingCache(per_user=0))

    report = mig._invalidate_users([11])

    assert report["keys_deleted"] == 0
    assert report["backend"] is True
    assert "error" not in report


def test_missing_redis_is_surfaced_even_though_the_call_succeeds(use_cache):
    """בלי Redis הניקוי חל רק על התהליך הזה — וזה חייב להגיע לאדמין.

    זה ההבדל שהמימוש הקודם לא ידע לעשות: גם "קאש קר" וגם "אין backend"
    נראו כמו הצלחה שקטה.
    """
    use_cache(_CountingCache(per_user=1, is_enabled=False))

    report = mig._invalidate_users([11])

    assert report["backend"] is False
    assert report["keys_deleted"] == 1


def test_unimportable_cache_module_is_reported(monkeypatch):
    """כשל ייבוא חוזר בשדה ``error`` ולא נבלע."""
    import builtins

    real_import = builtins.__import__

    def _boom(name, *args, **kwargs):
        if name == "cache_manager":
            raise ImportError("no cache backend in this deployment")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _boom)

    report = mig._invalidate_users([11])

    assert report["error"] == "no cache backend in this deployment"
    assert report["backend"] is False
    assert report["keys_deleted"] == 0
