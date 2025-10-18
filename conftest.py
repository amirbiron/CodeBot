import os
import sys
import math
from typing import Dict, List, Optional
import pytest

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

