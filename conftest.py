import asyncio
import inspect
import os
import sys
import math
from pathlib import Path
from typing import AsyncIterator, Dict, List, Optional
import pytest
import pytest_asyncio

# -----------------------------------------------------------------------------
# Telegram module isolation (safe)
# -----------------------------------------------------------------------------
#
# חלק מהטסטים מבצעים stubbing ידני ל-`sys.modules['telegram']` בלי להשתמש ב-monkeypatch,
# ולפעמים זה stubbing *חלקי* (למשל בלי `InputFile`). אחרי שטסט כזה רץ, טסטים אחרים
# שמייבאים `bot_handlers` נופלים כבר בזמן import על:
# `ImportError: cannot import name 'InputFile' from 'telegram'`.
#
# מצד שני, אסור לנו למחוק/לטעון מחדש את telegram.ext בצורה אגרסיבית, כי זה עלול ליצור
# שתי גרסאות שונות של אותן מחלקות (BaseHandler/ApplicationHandlerStop) ולהוביל ל-TypeError.
#
# הפתרון: נשמור reference לסטאבים הקנוניים שמגיעים מ-`tests/_telegram_stubs.py`
# (שכבר נטענים ב-`tests/conftest.py`), ונשחזר אותם *רק* אם מזהים ש-telegram נהיה "שבור".
_CANONICAL_TELEGRAM_MODULES: Dict[str, object] = {}


def _ensure_canonical_telegram_modules_loaded() -> None:
    if _CANONICAL_TELEGRAM_MODULES:
        return
    try:
        import tests._telegram_stubs  # noqa: F401
    except Exception:
        return
    for key in (
        "telegram",
        "telegram.constants",
        "telegram.error",
        "telegram.ext",
        "telegram.ext._application",
    ):
        mod = sys.modules.get(key)
        if mod is not None:
            _CANONICAL_TELEGRAM_MODULES[key] = mod


def _telegram_is_broken() -> bool:
    tg = sys.modules.get("telegram")
    if tg is None:
        return True
    return not hasattr(tg, "InputFile")


def _restore_canonical_telegram_modules() -> None:
    if not _CANONICAL_TELEGRAM_MODULES:
        return
    for key, mod in _CANONICAL_TELEGRAM_MODULES.items():
        sys.modules[key] = mod  # type: ignore[assignment]


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

    ui_group = parser.getgroup("ui_validation")
    ui_group.addoption(
        "--run-ui-validation",
        action="store_true",
        default=False,
        help=(
            "מריץ את בדיקות ה-UI תחת tests/ui_validation/. "
            "ברירת מחדל: מדלג עליהן כדי לא לחסום Unit Tests רגילים."
        ),
    )


def _is_ui_validation_test_path(path_str: str) -> bool:
    s = path_str.replace("\\", "/")
    return "tests/ui_validation/tests/" in s or s.endswith("tests/ui_validation/tests")


def _ui_validation_enabled(config: pytest.Config) -> bool:
    # הפעלה מפורשת
    if bool(config.getoption("--run-ui-validation")):
        return True
    if os.getenv("UI_TEST_RUN", "").lower() in ("1", "true", "yes"):
        return True

    # הפעלה דרך נתיב CLI (הדרך המומלצת): pytest ... tests/ui_validation/
    args = [str(a).replace("\\", "/") for a in (getattr(config, "args", None) or [])]
    return any(a.startswith("tests/ui_validation") or "/tests/ui_validation" in a for a in args)


def pytest_ignore_collect(collection_path: Path, config: pytest.Config) -> bool:
    """מדלג על בדיקות UI validation כברירת מחדל.

    הסיבה: ה-Unit Tests ב-CI רצים בלי בחירת markers (pytest -v),
    ובדיקות UI דורשות סביבת Playwright/URL ולעיתים גם browser install.

    כדי להריץ את הסוויטה:
    - Smoke: pytest -m smoke -n 4 tests/ui_validation/
    - Full: pytest -m "ui_full and not flaky" -n 4 tests/ui_validation/
    - או עם הדגל: pytest --run-ui-validation tests/ui_validation/
    """
    path_str = str(collection_path)
    if not _is_ui_validation_test_path(path_str):
        return False

    return not _ui_validation_enabled(config)


def _compute_percentile(values: List[float], percentile: float) -> Optional[float]:
    if not values:
        return None
    xs = sorted(values)
    p = max(0.0, min(100.0, float(percentile)))
    # Nearest-rank method
    rank = int(math.ceil((p / 100.0) * len(xs)))
    idx = max(0, min(rank - 1, len(xs) - 1))
    return xs[idx]


def _ensure_real_telegram_package_loaded() -> None:
    """וודא שב-process הנוכחי `telegram` הוא package אמיתי (python-telegram-bot).

    זה חשוב במיוחד ל-xdist: אזהרות שנשלחות מה-workers עלולות להתבסס על
    מחלקות/מודולים כמו `telegram.warnings`, וה-master חייב להיות מסוגל לייבא אותם.
    """
    # ⚠️ חשוב ל-Isolation:
    # בעבר ניקינו כאן stubs של telegram מתוך sys.modules כדי "להחזיר" PTB אמיתי.
    # בפועל זה יוצר מצב מסוכן שבו חלק מהקוד נטען מול telegram.ext ישן וחלק מול חדש,
    # ואז מתקבלות שגיאות כמו:
    # - TypeError: handler is not an instance of BaseHandler
    # - ApplicationHandlerStop שלא נתפס ב-pytest.raises (כי זו מחלקה אחרת)
    #
    # לכן אנחנו *לא* מוחקים/מטעינים מחדש telegram במהלך הרצת הטסטים.
    # אם צריך PTB אמיתי, יש להריץ את הסוויטה בלי ה-stubs (tests/_telegram_stubs.py).
    return


def pytest_configure(config: pytest.Config) -> None:
    # Accumulate per-test durations for performance tests
    config._perf_times = {}  # type: ignore[attr-defined]
    _ensure_real_telegram_package_loaded()
    _ensure_canonical_telegram_modules_loaded()


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

    # UI validation tests: לא חוסמים Unit Tests כברירת מחדל
    if not _ui_validation_enabled(config):
        skip_ui = pytest.mark.skip(
            reason="UI validation disabled by default (run with tests/ui_validation/ or --run-ui-validation)"
        )
        for item in items:
            nodeid = str(getattr(item, "nodeid", "")).replace("\\", "/")
            if nodeid.startswith("tests/ui_validation/tests/"):
                item.add_marker(skip_ui)

    # הפיקסצ'ר שמנקה את http_async רלוונטי רק לטסטים אסינכרוניים
    for item in items:
        try:
            has_asyncio_marker = item.get_closest_marker("asyncio") is not None
        except Exception:
            has_asyncio_marker = False
        is_coroutine_test = False
        try:
            obj = getattr(item, "obj", None)
            is_coroutine_test = bool(obj and inspect.iscoroutinefunction(obj))
        except Exception:
            is_coroutine_test = False
        if has_asyncio_marker or is_coroutine_test:
            item.add_marker(pytest.mark.usefixtures("_reset_http_async_session_between_tests"))

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
def _reset_cache_manager_state_between_tests(_reset_cache_manager_stub_before_test) -> None:
    """מאפס מצב גלובלי של cache_manager בין טסטים.

    בהרצה מקבילית (xdist) כל worker מריץ תת-סט אחר של טסטים, ולכן "דליפות" מצב
    (למשל cache.is_enabled=True עם redis_client=None) הופכות לפלייקיות.
    אנחנו מאפסים לברירת מחדל בטוחה לפני/אחרי כל טסט.
    """
    try:
        import cache_manager as cm  # type: ignore

        try:
            cm.cache.is_enabled = False
            cm.cache.redis_client = None
        except Exception:
            pass

        try:
            lock = getattr(cm, "_local_cache_lock", None)
            store = getattr(cm, "_local_cache_store", None)
            if store is not None:
                if lock is not None:
                    with lock:
                        store.clear()
                else:
                    store.clear()
            try:
                setattr(cm, "_local_cache_last_cleanup_ts", None)
            except Exception:
                pass
        except Exception:
            pass
    except Exception:
        pass

    yield

    # ניקוי נוסף אחרי הטסט כדי למנוע דליפות לשאר הטסטים באותו worker
    try:
        import cache_manager as cm  # type: ignore
        try:
            cm.cache.is_enabled = False
            cm.cache.redis_client = None
        except Exception:
            pass
        try:
            lock = getattr(cm, "_local_cache_lock", None)
            store = getattr(cm, "_local_cache_store", None)
            if store is not None:
                if lock is not None:
                    with lock:
                        store.clear()
                else:
                    store.clear()
        except Exception:
            pass
    except Exception:
        pass


@pytest.fixture(autouse=True)
def _reset_telegram_modules_between_tests() -> None:
    """מנקה stubs שדלפו ל-telegram בין טסטים.

    יש טסטים שמסטבבים את `telegram` כדי לאפשר import בסביבות בלי PTB.
    בהרצה עם xdist, דליפה כזו יכולה להפיל טסטים שעושים import/reload ל-main.
    """
    _ensure_canonical_telegram_modules_loaded()
    if _telegram_is_broken():
        _restore_canonical_telegram_modules()
    yield
    # ניקוי אחרי הטסט — רק אם מישהו השאיר סטאב שבור
    if _telegram_is_broken():
        _restore_canonical_telegram_modules()


@pytest.fixture(autouse=True)
def _reset_alerts_storage_stub_before_test() -> None:
    """מבטל Stub שדלף ל-`monitoring.alerts_storage` בין טסטים.

    חלק מהטסטים מציבים שם `types.SimpleNamespace` בתוך `sys.modules`.
    בהרצה מקבילית זה יכול לדלוף ולהשפיע על טסטים אחרים שמצפים למודול אמיתי.
    """
    import sys
    from types import SimpleNamespace

    def _clean() -> None:
        mod = sys.modules.get("monitoring.alerts_storage")
        if isinstance(mod, SimpleNamespace):
            sys.modules.pop("monitoring.alerts_storage", None)

    # ניקוי לפני הטסט (אם דלף מטסט קודם באותו worker)
    _clean()
    yield
    # ניקוי אחרי הטסט (כדי למנוע דליפה לטסט הבא באותו worker)
    _clean()


@pytest.fixture(autouse=True)
def _reset_database_package_stub_between_tests() -> None:
    """מנקה Stub שדלף ל-`database` (package) בין טסטים.

    יש טסטים שמזריקים `sys.modules['database']` כמודול דמה.
    אם זה דולף, importlib.reload על תתי-מודולים ייכשל כי `database` כבר לא package.
    """
    import sys
    import types

    def _purge_if_not_package() -> None:
        mod = sys.modules.get("database")
        if mod is None:
            return
        # package אמיתי אמור להכיל __path__
        if isinstance(mod, types.ModuleType) and hasattr(mod, "__path__"):
            return
        for name in list(sys.modules.keys()):
            if name == "database" or name.startswith("database."):
                sys.modules.pop(name, None)

    _purge_if_not_package()
    yield
    _purge_if_not_package()


@pytest.fixture(autouse=True)
def _ensure_http_async_session_closed_for_sync_tests() -> None:
    """סוגר את סשן http_async גם בטסטים סינכרוניים שמשתמשים ב-asyncio.run."""
    try:
        from http_async import close_session  # type: ignore
    except Exception:
        yield
        return

    yield

    try:
        # אם יש לולאה רצה כרגע - כנראה שזה טסט אסינכרוני והפיקסצ'ר הייעודי יטפל
        asyncio.get_running_loop()
        return
    except RuntimeError:
        pass

    try:
        asyncio.run(close_session())
    except RuntimeError:
        # במקרה שקיים לולאה ברקע אך אינה רצה, נקים לולאה זמנית
        loop = asyncio.new_event_loop()
        original_loop: Optional[asyncio.AbstractEventLoop] = None
        try:
            try:
                original_loop = asyncio.get_event_loop()
            except RuntimeError:
                original_loop = None
            try:
                asyncio.set_event_loop(loop)
            except Exception:
                pass
            try:
                loop.run_until_complete(close_session())
            except Exception:
                raise
        finally:
            loop.close()
            try:
                if original_loop is None or (original_loop.is_closed() if original_loop else True):
                    asyncio.set_event_loop(None)
                else:
                    asyncio.set_event_loop(original_loop)
            except Exception:
                pass
    except Exception:
        pass


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


@pytest_asyncio.fixture
async def _reset_http_async_session_between_tests(
    request: Optional[pytest.FixtureRequest] = None,
) -> AsyncIterator[None]:
    """סוגר את הסשן הגלובלי של http_async לפני ואחרי כל טסט אסינכרוני."""
    try:
        from http_async import close_session  # type: ignore
    except Exception:
        close_session = None  # type: ignore

    is_async_test = True
    if request is not None:
        try:
            marker = request.node.get_closest_marker("asyncio")
        except Exception:
            marker = None
        if marker is not None:
            is_async_test = True
        else:
            func = getattr(request.node, "function", None)
            is_async_test = bool(func and inspect.iscoroutinefunction(func))
        # אם לא הצלחנו לקבוע – נניח שזה טסט אסינכרוני כדי להישאר בצד הבטוח
        if request is not None and marker is None and not is_async_test:
            try:
                call_obj = getattr(request.node, "obj", None)
                if call_obj and inspect.iscoroutinefunction(call_obj):
                    is_async_test = True
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
