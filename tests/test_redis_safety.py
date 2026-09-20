"""בדיקות ל-timeouts של Redis ולמסלולי ה-SAFE_MODE של הקאש.

שני הטסטים הראשונים כאן נכתבו פעם מול ``CacheManager`` עם ``importlib.reload``,
והם היו **תלויי סדר**: התוצאה נקבעה לפי איזה מודול ``config`` הספיק להיכנס
ל-``sys.modules`` לפני כן — האמיתי שבשורש, או ``tests/config.py`` שמאפיל עליו
בזמן pytest. לבד הם עברו, בריצה המלאה הם נפלו על ``3.0 != 2.0``.

היום ההכרעה עצמה היא פונקציה טהורה ב-``runtime_settings``, והבדיקות קוראות
לה ישירות עם קלטים. אין ``reload``, אין ``os.environ`` גלובלי, ואין תלות
במה שכבר נטען בתהליך.
"""

import importlib
import types

import pytest

from runtime_settings import (
    DEFAULT_REDIS_CONNECT_TIMEOUT,
    DEFAULT_REDIS_SOCKET_TIMEOUT,
    SAFE_MODE_REDIS_TIMEOUT,
    redis_timeouts,
    resolve_redis_timeouts,
    safe_mode_enabled,
)


def _fake_cfg(**fields):
    """אובייקט קונפיג מזויף — כמו ``config`` האמיתי, רק בלי pydantic."""
    return types.SimpleNamespace(**fields)


# ===================== הפונקציה הטהורה =====================


def test_explicit_values_win_over_every_default():
    assert resolve_redis_timeouts(2.0, 3.0, safe_mode=False) == (2.0, 3.0)


def test_explicit_values_win_also_in_safe_mode():
    """ערך שהוגדר במפורש מנצח גם כש-SAFE_MODE דולק."""
    assert resolve_redis_timeouts(7.0, 8.0, safe_mode=True) == (7.0, 8.0)


def test_zero_is_an_explicit_value_and_not_a_missing_one():
    """``0`` הוא ערך לגיטימי, ולא "לא הוגדר" — הכלל הזה היה בקוד מאז ומתמיד."""
    assert resolve_redis_timeouts(0.0, 0.0, safe_mode=True) == (0.0, 0.0)


def test_safe_mode_gives_one_second_to_both():
    assert resolve_redis_timeouts(None, None, safe_mode=True) == (
        SAFE_MODE_REDIS_TIMEOUT,
        SAFE_MODE_REDIS_TIMEOUT,
    )
    assert (SAFE_MODE_REDIS_TIMEOUT, SAFE_MODE_REDIS_TIMEOUT) == (1.0, 1.0)


def test_defaults_without_safe_mode_are_three_and_five():
    assert resolve_redis_timeouts(None, None, safe_mode=False) == (
        DEFAULT_REDIS_CONNECT_TIMEOUT,
        DEFAULT_REDIS_SOCKET_TIMEOUT,
    )
    assert (DEFAULT_REDIS_CONNECT_TIMEOUT, DEFAULT_REDIS_SOCKET_TIMEOUT) == (3.0, 5.0)


def test_one_side_explicit_the_other_default():
    assert resolve_redis_timeouts(2.0, None, safe_mode=False) == (2.0, 5.0)
    assert resolve_redis_timeouts(None, 2.0, safe_mode=True) == (1.0, 2.0)


# ===================== נקודת הכניסה: קונפיג + ENV =====================


def test_env_timeouts_are_honored_when_config_has_none():
    """זה מה שהטסט הישן ניסה לבדוק — עכשיו בלי תלות ב-sys.modules."""
    cfg = _fake_cfg(REDIS_CONNECT_TIMEOUT=None, REDIS_SOCKET_TIMEOUT=None)
    env = {"REDIS_CONNECT_TIMEOUT": "2", "REDIS_SOCKET_TIMEOUT": "3"}
    assert redis_timeouts(cfg, env) == (2.0, 3.0)


def test_env_timeouts_are_honored_when_there_is_no_config_at_all():
    """בטסטים ``config`` מוחלף במודול דמה שאין בו את השדות האלה."""
    env = {"REDIS_CONNECT_TIMEOUT": "2", "REDIS_SOCKET_TIMEOUT": "3"}
    assert redis_timeouts(_fake_cfg(), env) == (2.0, 3.0)
    assert redis_timeouts(None, env) == (2.0, 3.0)


def test_config_value_wins_over_env():
    """הקונפיג כבר קרא את ה-ENV בעצמו, ולכן הוא הערך הקובע כשהוא קיים."""
    cfg = _fake_cfg(REDIS_CONNECT_TIMEOUT=2.0, REDIS_SOCKET_TIMEOUT=3.0)
    env = {"REDIS_CONNECT_TIMEOUT": "9", "REDIS_SOCKET_TIMEOUT": "9"}
    assert redis_timeouts(cfg, env) == (2.0, 3.0)


def test_safe_mode_is_one_second_even_when_the_config_object_is_loaded():
    """הרגרסיה עצמה.

    קודם השדות בקונפיג נשאו ברירת מחדל שנקבעה בזמן import ולעולם לא הייתה
    ``None``, ולכן ``SAFE_MODE`` קיבל בפועל 3 ו-5. היום השדה ריק כשאיש לא
    הגדיר אותו, ו-SAFE_MODE מקבל את השנייה שהובטחה בתיעוד.
    """
    cfg = _fake_cfg(REDIS_CONNECT_TIMEOUT=None, REDIS_SOCKET_TIMEOUT=None)
    assert redis_timeouts(cfg, {"SAFE_MODE": "1"}) == (1.0, 1.0)


def test_blank_env_value_means_unset_and_not_zero():
    cfg = _fake_cfg(REDIS_CONNECT_TIMEOUT=None, REDIS_SOCKET_TIMEOUT=None)
    env = {"REDIS_CONNECT_TIMEOUT": "", "REDIS_SOCKET_TIMEOUT": "   "}
    assert redis_timeouts(cfg, env) == (3.0, 5.0)


@pytest.mark.parametrize("bad", ["abc", "-1", "nan", "inf", True, object()])
def test_unusable_value_falls_back_to_the_default_and_does_not_kill_the_cache(bad):
    """ערך פגום לא מפיל את החיבור — קודם הוא היה מכבה את הקאש כולו."""
    cfg = _fake_cfg(REDIS_CONNECT_TIMEOUT=bad, REDIS_SOCKET_TIMEOUT=bad)
    assert redis_timeouts(cfg, {}) == (3.0, 5.0)


# ===================== קריאת הדגל SAFE_MODE =====================


@pytest.mark.parametrize("raw", ["1", "true", "TRUE", "yes", "y", "on", " on "])
def test_safe_mode_truthy_values(raw):
    assert safe_mode_enabled({"SAFE_MODE": raw}) is True


@pytest.mark.parametrize("raw", ["0", "false", "no", "off", "", "   ", "maybe"])
def test_safe_mode_falsy_values(raw):
    assert safe_mode_enabled({"SAFE_MODE": raw}) is False


def test_safe_mode_missing_or_not_a_string():
    assert safe_mode_enabled({}) is False
    assert safe_mode_enabled({"SAFE_MODE": 1}) is False


# ===================== החיווט: מה באמת מגיע ל-redis =====================


def test_cache_manager_passes_the_resolved_timeouts_to_redis(monkeypatch):
    """הפונקציה הטהורה לבדה אינה מוכיחה שהערך שלה מגיע ל-``redis.from_url``.

    לכן כאן מחליפים את ההכרעה בערך ידוע ובודקים שהוא זה שנמסר ללקוח —
    בלי ``reload`` ובלי להישען על ה-ENV של התהליך.
    """
    captured = {}

    class _FakeClient:
        def ping(self):
            return True

    def _from_url(url, **kwargs):  # noqa: ARG001
        captured["kwargs"] = dict(kwargs)
        return _FakeClient()

    cm = importlib.import_module("cache_manager")
    monkeypatch.setattr(cm, "redis", types.SimpleNamespace(from_url=_from_url))
    monkeypatch.setattr(cm, "redis_timeouts", lambda cfg=None: (2.0, 3.0))
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")

    mgr = cm.CacheManager()

    assert mgr.is_enabled is True
    assert captured["kwargs"]["socket_connect_timeout"] == 2.0
    assert captured["kwargs"]["socket_timeout"] == 3.0


def test_clear_stale_skips_in_safe_mode(monkeypatch):
    import cache_manager as cm
    importlib.reload(cm)

    monkeypatch.setenv('SAFE_MODE', '1')

    mgr = cm.CacheManager()
    mgr.is_enabled = True

    class _NoPingClient:
        def ping(self):  # should not be called under SAFE_MODE
            raise AssertionError("ping should not be called in SAFE_MODE")

    mgr.redis_client = _NoPingClient()

    assert mgr.clear_stale() == 0


def test_clear_stale_returns_quickly_when_ping_fails(monkeypatch):
    import cache_manager as cm
    importlib.reload(cm)

    monkeypatch.setenv('SAFE_MODE', '0')

    mgr = cm.CacheManager()
    mgr.is_enabled = True

    class _FailPingClient:
        def ping(self):
            raise RuntimeError("redis down")

    mgr.redis_client = _FailPingClient()

    assert mgr.clear_stale() == 0


def test_clear_stale_budget_limits_work(monkeypatch):
    import cache_manager as cm
    importlib.reload(cm)

    monkeypatch.setenv('SAFE_MODE', '0')
    monkeypatch.setenv('CACHE_CLEAR_BUDGET_SECONDS', '0.000001')

    mgr = cm.CacheManager()
    mgr.is_enabled = True

    class _Client:
        def ping(self):
            return True
        def scan_iter(self, match='*', count=500):  # noqa: ARG002
            for i in range(1000):
                yield f"k{i}"
        def ttl(self, key):  # noqa: ARG002
            return -2  # treat as expired to trigger delete
        def delete(self, key):  # noqa: ARG002
            return 1

    mgr.redis_client = _Client()

    n = mgr.clear_stale(max_scan=1000)
    # Should stop early due to budget; definitely less than full 1000
    assert 0 <= n <= 10


def test_predictive_engine_safe_mode_skip(monkeypatch):
    import predictive_engine as pe
    importlib.reload(pe)

    # Enable SAFE_MODE
    monkeypatch.setenv('SAFE_MODE', '1')

    # Capture emitted events
    events = []
    def _emit(event, severity="info", **fields):  # noqa: ARG001
        events.append(event)
    monkeypatch.setattr(pe, 'emit_event', _emit)

    # Make cache explode if called (it shouldn't)
    class _Boom:
        def clear_stale(self):
            raise AssertionError("clear_stale should not be called in SAFE_MODE")
    monkeypatch.setattr(pe, '_cache', _Boom())

    tr = pe.Trend(metric="latency_seconds", slope_per_minute=1.0, intercept=0.0, current_value=1.0, threshold=0.5, predicted_cross_ts=123.0)

    pe._trigger_preemptive_action(tr)

    assert "PREDICTIVE_ACTION_SKIPPED" in events
