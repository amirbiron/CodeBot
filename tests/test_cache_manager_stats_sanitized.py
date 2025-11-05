import types

from cache_manager import CacheManager


class _FailingRedis:
    def info(self):  # pragma: no cover - behavior under test is in CacheManager
        raise RuntimeError("boom")


def test_get_stats_sanitizes_exception_message():
    cm = CacheManager()
    # נכריח מצב 'מופעל' ונחליף לקוח Redis לכזה שזורק חריגה ב-info()
    cm.is_enabled = True
    cm.redis_client = _FailingRedis()

    stats = cm.get_stats()

    assert stats.get("enabled") is True
    assert stats.get("error") == "unavailable"
