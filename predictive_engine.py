"""
Predictive Health Engine (Observability v6)

- Maintains sliding window for metrics: error_rate_percent, latency_seconds, memory_usage_percent
- Computes simple linear regression trend per metric
- If forecast crosses adaptive threshold within horizon (default 15 minutes), logs a predictive incident
- Predictive incidents are appended to data/predictions_log.json (JSONL)
- Optionally triggers preemptive actions (cache clear, GC, controlled restart) and logs PREDICTIVE_ACTION_TRIGGERED

This module is intentionally best-effort and fail-open. It should never raise.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Deque, Dict, List, Optional, Tuple
from collections import deque
from datetime import datetime, timezone
import json
import os
import time
import math

# Optional psutil for memory
try:  # pragma: no cover - optional
    import psutil  # type: ignore
except Exception:  # pragma: no cover
    psutil = None  # type: ignore

# Lazy event emitter (avoid hard import at module import time)
try:
    from observability import emit_event  # type: ignore
except Exception:  # pragma: no cover
    def emit_event(event: str, severity: str = "info", **fields):  # type: ignore
        return None

# Prometheus counters are optional
try:  # pragma: no cover - metrics optional in some environments
    from metrics import business_events_total  # noqa: F401
    from metrics import errors_total  # noqa: F401
    from metrics import Counter  # type: ignore
except Exception:  # pragma: no cover
    Counter = None  # type: ignore

try:  # expose counters if prometheus_client available via metrics module
    from metrics import (  # type: ignore
        predicted_incidents_total as _predicted_ctr,
        actual_incidents_total as _actual_ctr,
    )
except Exception:
    _predicted_ctr = None  # type: ignore
    _actual_ctr = None  # type: ignore

# Optional cache manager for preemptive actions
try:
    from cache_manager import cache as _cache  # type: ignore
except Exception:  # pragma: no cover
    _cache = None  # type: ignore

_DATA_DIR = os.path.join("data")
_PREDICTIONS_FILE = os.path.join(_DATA_DIR, "predictions_log.json")

# Sliding windows store up to 4 hours to give more context but filter by horizon
_MAX_WINDOW_SEC = 4 * 60 * 60
_RECOMPUTE_MIN_INTERVAL_SEC = 60  # avoid excessive recomputation
_DEFAULT_HORIZON_SEC = int(os.getenv("PREDICTIVE_HORIZON_SECONDS", str(15 * 60)) or 900)
_MEMORY_THRESHOLD_PCT = float(os.getenv("MEMORY_USAGE_THRESHOLD_PERCENT", "85") or 85.0)

# In-memory buffers: (ts_seconds, value)
_values_error_rate: Deque[Tuple[float, float]] = deque(maxlen=240)  # roughly 1/min for 4h
_values_latency: Deque[Tuple[float, float]] = deque(maxlen=240)
_values_memory: Deque[Tuple[float, float]] = deque(maxlen=240)

_last_recompute_ts: float = 0.0


@dataclass
class Trend:
    metric: str
    slope_per_minute: float
    intercept: float
    current_value: float
    threshold: float
    predicted_cross_ts: Optional[float]


def _ensure_dirs() -> None:
    try:
        os.makedirs(_DATA_DIR, exist_ok=True)
    except Exception:
        pass


def _now() -> float:
    return time.time()


def _linear_regression(points: List[Tuple[float, float]]) -> Tuple[float, float]:
    """Return (slope_per_minute, intercept) over time expressed in minutes.

    points: list of (ts_seconds, value)
    """
    try:
        if not points:
            return 0.0, 0.0
        if len(points) == 1:
            return 0.0, float(points[0][1])
        # Convert to minutes relative to first point to improve conditioning
        t0 = float(points[0][0])
        xs = [((p[0] - t0) / 60.0) for p in points]
        ys = [float(p[1]) for p in points]
        n = float(len(xs))
        sum_x = sum(xs)
        sum_y = sum(ys)
        sum_xx = sum(x * x for x in xs)
        sum_xy = sum(x * y for x, y in zip(xs, ys))
        denom = (n * sum_xx - sum_x * sum_x)
        if denom == 0.0:
            return 0.0, ys[-1]
        slope = (n * sum_xy - sum_x * sum_y) / denom
        # intercept with respect to minute-axis origin at t0
        intercept = (sum_y - slope * sum_x) / n
        # Convert intercept back to absolute time origin: y = slope*(t_minute - 0) + intercept
        return float(slope), float(intercept)
    except Exception:
        return 0.0, 0.0


def _evict_old(points: Deque[Tuple[float, float]], min_ts: float) -> None:
    try:
        while points and points[0][0] < min_ts:
            points.popleft()
    except Exception:
        return


def _get_thresholds() -> Dict[str, float]:
    """Fetch adaptive thresholds for error_rate_percent and latency_seconds.

    Returns zeros when unavailable (treated as disabled).
    """
    try:
        from alert_manager import get_thresholds_snapshot  # type: ignore
        snap = get_thresholds_snapshot() or {}
        return {
            "error_rate_percent": float(snap.get("error_rate_percent", {}).get("threshold", 0.0) or 0.0),
            "latency_seconds": float(snap.get("latency_seconds", {}).get("threshold", 0.0) or 0.0),
        }
    except Exception:
        return {"error_rate_percent": 0.0, "latency_seconds": 0.0}


def _get_current_values() -> Tuple[float, float, float]:
    """Return (error_rate_percent, latency_seconds, memory_usage_percent)."""
    err = lat = mem = 0.0
    try:
        from alert_manager import (  # type: ignore
            get_current_error_rate_percent,
            get_current_avg_latency_seconds,
        )
        err = float(get_current_error_rate_percent(window_sec=5 * 60))
        lat = float(get_current_avg_latency_seconds(window_sec=5 * 60))
    except Exception:
        err, lat = 0.0, 0.0
    try:
        if psutil is not None:
            mem = float(psutil.virtual_memory().percent)
        else:
            mem = 0.0
    except Exception:
        mem = 0.0
    return err, lat, mem


def note_observation(
    *,
    error_rate_percent: Optional[float] = None,
    latency_seconds: Optional[float] = None,
    memory_usage_percent: Optional[float] = None,
    ts: Optional[float] = None,
) -> None:
    """Record a single observation into sliding windows.

    Values default to current snapshot from alert_manager/psutil.
    """
    try:
        t = float(ts if ts is not None else _now())
        if error_rate_percent is None or latency_seconds is None or memory_usage_percent is None:
            cur_err, cur_lat, cur_mem = _get_current_values()
            error_rate_percent = cur_err if error_rate_percent is None else error_rate_percent
            latency_seconds = cur_lat if latency_seconds is None else latency_seconds
            memory_usage_percent = cur_mem if memory_usage_percent is None else memory_usage_percent
        _values_error_rate.append((t, float(error_rate_percent)))
        _values_latency.append((t, float(latency_seconds)))
        _values_memory.append((t, float(memory_usage_percent)))
        # Evict old
        min_ts = t - _MAX_WINDOW_SEC
        _evict_old(_values_error_rate, min_ts)
        _evict_old(_values_latency, min_ts)
        _evict_old(_values_memory, min_ts)
    except Exception:
        return


def _predict_cross(
    metric: str,
    points: Deque[Tuple[float, float]],
    current_value: float,
    threshold: float,
    now_ts: float,
    horizon_sec: int,
) -> Trend:
    try:
        pts = list(points)
        slope_min, intercept = _linear_regression(pts)
        predicted_ts: Optional[float] = None
        # If we've already crossed the threshold, treat as "now"
        if threshold > 0.0 and current_value >= threshold:
            predicted_ts = now_ts
        # Otherwise, only rising trends matter for preemptive actions
        elif slope_min > 0.0 and threshold > 0.0:
            # Solve for y = slope*(minutes_since_t0) + intercept crosses threshold within horizon
            # Compute minutes from t0 to crossing
            minutes_since_t0_to_cross = (threshold - intercept) / slope_min if slope_min != 0.0 else float("inf")
            # Convert to absolute timestamp
            t0 = float(pts[0][0]) if pts else now_ts
            predicted = t0 + (minutes_since_t0_to_cross * 60.0)
            if predicted >= now_ts and (predicted - now_ts) <= float(horizon_sec):
                predicted_ts = predicted
        return Trend(
            metric=metric,
            slope_per_minute=float(slope_min),
            intercept=float(intercept),
            current_value=float(current_value),
            threshold=float(threshold),
            predicted_cross_ts=predicted_ts,
        )
    except Exception:
        return Trend(metric=metric, slope_per_minute=0.0, intercept=0.0, current_value=0.0, threshold=float(threshold or 0.0), predicted_cross_ts=None)


def evaluate_predictions(now_ts: Optional[float] = None, horizon_seconds: Optional[int] = None) -> List[Trend]:
    """Compute predictions for all metrics. Returns list of Trend objects."""
    t = float(now_ts if now_ts is not None else _now())
    horizon = int(horizon_seconds if horizon_seconds is not None else _DEFAULT_HORIZON_SEC)
    try:
        thrs = _get_thresholds()
        err_thr = float(thrs.get("error_rate_percent", 0.0) or 0.0)
        lat_thr = float(thrs.get("latency_seconds", 0.0) or 0.0)
        # Current values from the tails of buffers to avoid double-fetches
        cur_err = float(_values_error_rate[-1][1]) if _values_error_rate else 0.0
        cur_lat = float(_values_latency[-1][1]) if _values_latency else 0.0
        cur_mem = float(_values_memory[-1][1]) if _values_memory else 0.0

        out: List[Trend] = []
        out.append(_predict_cross("error_rate_percent", _values_error_rate, cur_err, err_thr, t, horizon))
        out.append(_predict_cross("latency_seconds", _values_latency, cur_lat, lat_thr, t, horizon))
        out.append(_predict_cross("memory_usage_percent", _values_memory, cur_mem, _MEMORY_THRESHOLD_PCT, t, horizon))
        return out
    except Exception:
        return []


def _append_prediction_record(record: Dict[str, Any]) -> None:
    try:
        _ensure_dirs()
        line = json.dumps(record, ensure_ascii=False)
        with open(_PREDICTIONS_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        return


def _log_prediction(trend: Trend) -> None:
    try:
        rec = {
            "prediction_id": _safe_uuid(),
            "ts": datetime.now(timezone.utc).isoformat(),
            "metric": trend.metric,
            "current_value": trend.current_value,
            "threshold": trend.threshold,
            "slope_per_minute": trend.slope_per_minute,
            "predicted_cross_ts": datetime.fromtimestamp(trend.predicted_cross_ts, timezone.utc).isoformat() if trend.predicted_cross_ts else None,
            "horizon_seconds": _DEFAULT_HORIZON_SEC,
        }
        _append_prediction_record(rec)
        try:
            emit_event("PREDICTIVE_INCIDENT_DETECTED", severity="warn", metric=trend.metric)
        except Exception:
            pass
        try:
            if _predicted_ctr is not None:
                _predicted_ctr.labels(metric=str(trend.metric)).inc()  # type: ignore[attr-defined]
        except Exception:
            pass
    except Exception:
        return


def _safe_uuid() -> str:
    try:
        import uuid
        return str(uuid.uuid4())
    except Exception:
        return ""


def maybe_recompute_and_preempt(now_ts: Optional[float] = None) -> List[Trend]:
    """Throttled evaluation. If any metric predicted to breach within horizon, trigger preemptive actions.

    Returns the trends (for observability/tests).
    """
    global _last_recompute_ts
    t = float(now_ts if now_ts is not None else _now())
    try:
        if (t - _last_recompute_ts) < _RECOMPUTE_MIN_INTERVAL_SEC:
            # Throttled: avoid side effects and also skip heavy computations.
            # Return empty and let the next interval do work once.
            return []
        _last_recompute_ts = t
        trends = evaluate_predictions(now_ts=t)
        for tr in trends:
            if tr.predicted_cross_ts is None:
                continue
            _log_prediction(tr)
            _trigger_preemptive_action(tr)
        # Advance the recompute timestamp after performing side effects to prevent duplicates
        _last_recompute_ts = t
        return trends
    except Exception:
        return []


def _trigger_preemptive_action(tr: Trend) -> None:
    try:
        action = None
        if tr.metric == "latency_seconds":
            # Clear stale cache (fallback to clear_all when unknown)
            try:
                # Prefer clear_stale when available
                if _cache is not None and hasattr(_cache, "clear_stale"):
                    deleted = int(_cache.clear_stale() or 0)
                elif _cache is not None and hasattr(_cache, "clear_all"):
                    deleted = int(_cache.clear_all() or 0)  # type: ignore[attr-defined]
                else:
                    deleted = 0
            except Exception:
                deleted = 0
            action = f"cache_clear({deleted})"
        elif tr.metric == "memory_usage_percent":
            try:
                import gc
                gc.collect()
            except Exception:
                pass
            action = "gc.collect()"
        elif tr.metric == "error_rate_percent":
            # Controlled restart of a single worker (log-only in dev)
            action = "restart_worker:1"
            try:
                emit_event("service_restart_attempt", severity="warn", service="worker-1", reason="predictive")
            except Exception:
                pass
        emit_event("PREDICTIVE_ACTION_TRIGGERED", severity="warn", metric=tr.metric, action=action or "none")
    except Exception:
        return


def get_recent_predictions(limit: int = 5) -> List[Dict[str, Any]]:
    try:
        if limit <= 0:
            return []
        if not os.path.exists(_PREDICTIONS_FILE):
            return []
        items: List[Dict[str, Any]] = []
        with open(_PREDICTIONS_FILE, "r", encoding="utf-8") as f:
            for line in f:
                t = (line or "").strip()
                if not t:
                    continue
                try:
                    items.append(json.loads(t))
                except Exception:
                    continue
        return items[-limit:]
    except Exception:
        return []


def get_trend_snapshot() -> Dict[str, Dict[str, Any]]:
    """Return a snapshot with direction and slope for UI (/predict).

    Keys are metrics; values include direction emoji and slope.
    """
    try:
        trends = evaluate_predictions()
        out: Dict[str, Dict[str, Any]] = {}
        for tr in trends:
            if tr.slope_per_minute > 1e-6:
                direction = "🔴"  # rising
            elif tr.slope_per_minute < -1e-6:
                direction = "🟢"  # decreasing
            else:
                direction = "⚪"  # flat
            out[tr.metric] = {
                "direction": direction,
                "slope_per_minute": round(tr.slope_per_minute, 6),
                "current_value": round(tr.current_value, 6),
                "threshold": round(tr.threshold, 6),
                "predicted_cross_at": tr.predicted_cross_ts,
            }
        return out
    except Exception:
        return {}
