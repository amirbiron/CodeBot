import asyncio
import os
import sys
import math
from typing import Dict, List, Optional
import pytest
import pytest_asyncio

# Ensure project root is on sys.path so `import utils` works in tests
PROJECT_ROOT = os.path.dirname(__file__)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("performance")
    group.addoption(
        "--perf-heavy-percentile",
        action="store",
        default=os.getenv("PERF_HEAVY_PERCENTILE", "90"),
        help="אחוזון לסימון heavy אוטומטי (ברירת מחדל: 90)",
    )


def _compute_percentile(values: List[float], percentile: float) -> Optional[float]:
    if not values:
        return None
    xs = sorted(values)
    p = max(0.0, min(100.0, float(percentile)))
    # Nearest-rank method
    rank = int(math.ceil((p / 100.0) * len(xs)))
    idx = max(0, min(rank - 1, len(xs) - 1))
    return xs[idx]


def pytest_configure(config: pytest.Config) -> None:
    # Accumulate per-test durations for performance tests
    config._perf_times = {}  # type: ignore[attr-defined]


def pytest_collection_modifyitems(config: pytest.Config, items: List[pytest.Item]) -> None:
    """Auto-mark heavy tests by dynamic percentile and optionally skip heavies.

    - מסמן כ-heavy טסטי performance שחצו את סף האחוזון (מתוך ריצה קודמת).
    - אם ONLY_LIGHT_PERF=1 → מדלג על heavy.
    """
    cache: Dict[str, float] = config.cache.get("perf/last_durations", {}) or {}  # type: ignore[attr-defined]
    try:
        heavy_percentile = float(config.getoption("--perf-heavy-percentile"))
    except Exception:
        heavy_percentile = 90.0

    threshold: Optional[float] = None
    if cache:
        threshold = _compute_percentile(list(cache.values()), heavy_percentile)

    # Log measured threshold (or absence)
    if threshold is not None:
        print(f"Heavy threshold auto-calculated: {threshold:.3f}s (P{int(heavy_percentile)})")
    else:
        print("Heavy threshold auto-calculated: N/A (insufficient data)")

    # Add heavy mark based on last run durations
    if threshold is not None:
        for item in items:
            if "performance" in item.keywords:
                last = cache.get(item.nodeid)
                if last is not None and last >= threshold:
                    item.add_marker(pytest.mark.heavy)

    # Optionally skip heavies when ONLY_LIGHT_PERF is set
    only_light = os.getenv("ONLY_LIGHT_PERF") in ("1", "true", "True")
    if only_light:
        skip_heavy = pytest.mark.skip(reason="ONLY_LIGHT_PERF set; skipping heavy performance tests")
        for item in items:
            if "performance" in item.keywords and "heavy" in item.keywords:
                item.add_marker(skip_heavy)

def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo) -> None:  # type: ignore[override]
    if call.when == "call" and "performance" in item.keywords:
        # call.duration is not guaranteed; compute from start/stop
        duration = getattr(call, "stop", None)
        if duration is not None:
            duration = call.stop - call.start  # type: ignore[operator]
            # store
            store: Dict[str, float] = item.config._perf_times  # type: ignore[attr-defined]
            store[item.nodeid] = float(duration)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:  # type: ignore[override]
    store: Dict[str, float] = getattr(session.config, "_perf_times", {})  # type: ignore[attr-defined]
    session.config.cache.set("perf/last_durations", store)  # type: ignore[attr-defined]


@pytest.fixture(autouse=True)
def _reset_cache_manager_stub_before_test() -> None:
    """מבטל Stub שדלף למודול cache_manager בין טסטים.

    ישנם טסטים שממקפים את `sys.modules['cache_manager']` ל-`types.SimpleNamespace`.
    אם מסיבה כלשהי ה-Stubbing לא שוחזר, נוודא לפני כל טסט שהייבוא הבא
    יחזיר את המודול האמיתי ע"י הסרת ה-Stub מה-`sys.modules`.
    """
    import sys
    from types import SimpleNamespace

    cm = sys.modules.get('cache_manager')
    if isinstance(cm, SimpleNamespace):
        sys.modules.pop('cache_manager', None)


@pytest.fixture(autouse=True)
def _ensure_legacy_event_loop_for_sync_tests(request: pytest.FixtureRequest) -> None:
    """משחזר את ההתנהגות הישנה של pytest-asyncio עבור טסטים סינכרוניים.

    בגרסאות החדשות (asyncio_mode=auto) כבר לא נוצר לולאה כברירת מחדל,
    אבל יש לנו עדיין טסטים סינכרוניים שקוראים ל-asyncio.get_event_loop().
    נחזיר לולאה זמנית רק עבור טסטים שלא מסומנים כ-@pytest.mark.asyncio.
    """
    if request.node.get_closest_marker("asyncio"):
        yield
        return

    created_loop: Optional[asyncio.AbstractEventLoop] = None
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = None

    if loop is None or loop.is_closed():
        created_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(created_loop)

    try:
        yield
    finally:
        if created_loop is not None:
            asyncio.set_event_loop(None)
            try:
                created_loop.close()
            finally:
                pass


@pytest.fixture(scope="session", autouse=True)
def _close_http_async_session_after_session() -> None:
    """סוגר את סשן aiohttp הגלובלי בסיום הרצת הטסטים."""

    yield

    try:
        from http_async import close_session  # type: ignore
    except Exception:
        return

    import asyncio

    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = None

    if loop is not None and not loop.is_closed():
        try:
            running = bool(loop.is_running())
        except Exception:
            running = False
        if not running:
            try:
                coro = close_session()
            except Exception:
                coro = None
            if coro is not None:
                try:
                    loop.run_until_complete(coro)
                except Exception:
                    try:
                        coro.close()  # type: ignore[attr-defined]
                    except Exception:
                        pass
                else:
                    return

    try:
        new_loop = asyncio.new_event_loop()
        original_loop = None
        try:
            try:
                original_loop = asyncio.get_event_loop()
            except RuntimeError:
                original_loop = None
            try:
                asyncio.set_event_loop(new_loop)
            except Exception:
                pass
            try:
                coro = close_session()
            except Exception:
                coro = None
            if coro is not None:
                try:
                    new_loop.run_until_complete(coro)
                except Exception:
                    try:
                        coro.close()  # type: ignore[attr-defined]
                    except Exception:
                        pass
        finally:
            new_loop.close()
            try:
                if original_loop is None or (original_loop.is_closed() if original_loop else True):
                    asyncio.set_event_loop(None)
                else:
                    asyncio.set_event_loop(original_loop)
            except Exception:
                pass
    except Exception:
        pass


@pytest_asyncio.fixture(autouse=True)
async def _reset_http_async_session_between_tests(request=None) -> None:
    """סוגר את הסשן הגלובלי של http_async לפני ואחרי כל טסט אסינכרוני."""
    try:
        from http_async import close_session  # type: ignore
    except Exception:
        close_session = None  # type: ignore
    is_async_test = True
    if request is not None:
        try:
            is_async_test = request.node.get_closest_marker("asyncio") is not None
        except Exception:
            is_async_test = True
    if not is_async_test or close_session is None:
        yield
        return
    try:
        await close_session()
    except Exception:
        pass
    yield
    try:
        await close_session()
    except Exception:
        pass
