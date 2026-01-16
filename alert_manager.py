"""
Adaptive alert manager for Smart Observability v4.

- Maintains rolling 3h window of request samples (status, latency)
- Recomputes adaptive thresholds every 5 minutes based on mean + 3*sigma
- Emits critical alerts when current 5m stats breach adaptive thresholds
- Sends critical alerts to Telegram and Grafana annotations and logs dispatches

Environment variables used (optional; fail-open if missing):

- ALERT_TELEGRAM_BOT_TOKEN, ALERT_TELEGRAM_CHAT_ID
- GRAFANA_URL (e.g. https://grafana.example.com)
- GRAFANA_API_TOKEN (Bearer token)
- ALERT_COOLDOWN_SEC (override global cooldown between alerts)
- ALERT_THRESHOLD_SCALE / ALERT_ERROR_THRESHOLD_SCALE / ALERT_LATENCY_THRESHOLD_SCALE
  (multiply adaptive thresholds to widen the "normal" band)
- ALERT_MIN_SAMPLE_COUNT / ALERT_ERROR_MIN_SAMPLE_COUNT / ALERT_LATENCY_MIN_SAMPLE_COUNT
  (require a minimum number of samples in the evaluation window before alerting)
"""
from __future__ import annotations

from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Tuple, Optional
import asyncio
import math
import os
import threading
import time
import uuid

try:
    from http_sync import request  # type: ignore
except Exception:  # pragma: no cover
    request = None  # type: ignore

try:  # structured events (optional)
    from observability import emit_event  # type: ignore
except Exception:  # pragma: no cover
    def emit_event(event: str, severity: str = "info", **fields):  # type: ignore
        return None


# --- Configuration helpers ---
def _parse_float_env(name: str, default: float) -> float:
    try:
        raw = os.getenv(name)
        if raw is None or not str(raw).strip():
            return float(default)
        return float(raw)
    except Exception:
        return float(default)


def _parse_int_env(name: str, default: int) -> int:
    try:
        raw = os.getenv(name)
        if raw is None or not str(raw).strip():
            return int(default)
        return int(float(raw))
    except Exception:
        return int(default)


def _get_positive_float(name: str, default: float) -> float:
    val = _parse_float_env(name, default)
    return val if val > 0 else float(default)


def _get_non_negative_int(name: str, default: int) -> int:
    val = _parse_int_env(name, default)
    return val if val >= 0 else int(default)


# --- Startup warmup gate (avoid noisy internal alerts during deploy/cold start) ---
# בזמן warmup אנחנו חוסמים את ה-monitor הפנימי לחלוטין כדי למנוע רעשי דיפלוי.
_DEFAULT_STARTUP_GRACE_PERIOD_SECONDS = 1200  # 20 minutes
_STARTUP_GRACE_PERIOD_SECONDS = _get_non_negative_int(
    "ALERT_STARTUP_GRACE_PERIOD_SECONDS",
    _DEFAULT_STARTUP_GRACE_PERIOD_SECONDS,
)
_START_TIME = time.time()


# --- In-memory state ---
_WINDOW_SEC = 3 * 60 * 60  # 3 hours
_RECOMPUTE_EVERY_SEC = 5 * 60  # 5 minutes
_COOLDOWN_SEC = 5 * 60  # minimum gap between alerts of same type

_COOLDOWN_SEC = _get_non_negative_int("ALERT_COOLDOWN_SEC", _COOLDOWN_SEC)

_DEFAULT_THRESHOLD_SCALE = _get_positive_float("ALERT_THRESHOLD_SCALE", 1.0)
_THRESHOLD_SCALES = {
    "error_rate_percent": _get_positive_float("ALERT_ERROR_THRESHOLD_SCALE", _DEFAULT_THRESHOLD_SCALE),
    "latency_seconds": _get_positive_float("ALERT_LATENCY_THRESHOLD_SCALE", _DEFAULT_THRESHOLD_SCALE),
}

# Optional minimum floors to prevent zero/near-zero thresholds causing noise bursts
_MIN_ERR_RATE_FLOOR = max(0.0, _parse_float_env("ALERT_MIN_ERROR_RATE_PERCENT", 5.0))
_MIN_LATENCY_FLOOR = max(0.0, _parse_float_env("ALERT_MIN_LATENCY_SECONDS", 1.0))

_DEFAULT_MIN_SAMPLE_COUNT = _get_non_negative_int("ALERT_MIN_SAMPLE_COUNT", 15)
_ERROR_MIN_SAMPLE_COUNT = _get_non_negative_int("ALERT_ERROR_MIN_SAMPLE_COUNT", _DEFAULT_MIN_SAMPLE_COUNT)
_LATENCY_MIN_SAMPLE_COUNT = _get_non_negative_int("ALERT_LATENCY_MIN_SAMPLE_COUNT", _DEFAULT_MIN_SAMPLE_COUNT)
_MIN_SAMPLE_REQUIREMENTS = {
    "error_rate_percent": _ERROR_MIN_SAMPLE_COUNT,
    "latency_seconds": _LATENCY_MIN_SAMPLE_COUNT,
}
_EXTERNAL_WARNING_THRESHOLD = max(0.0, _parse_float_env("ALERT_EXTERNAL_ERROR_RATE_THRESHOLD", 20.0))
_EXTERNAL_WARNING_MIN_SAMPLE_COUNT = max(1, _get_non_negative_int("ALERT_EXTERNAL_MIN_SAMPLE_COUNT", 5))

_Sample = Tuple[float, bool, float, str]
_samples: Deque[_Sample] = deque(maxlen=200_000)  # (ts, is_error, latency_s, source)
_error_contexts: Deque[Tuple[float, Dict[str, Any]]] = deque(maxlen=5_000)
_ERROR_CONTEXT_WINDOW_SEC = 5 * 60
_REQUEST_CONTEXTS: Deque[Tuple[float, Dict[str, Any]]] = deque(maxlen=20_000)
_REQUEST_CONTEXT_WINDOW_SEC = max(60, int(os.getenv("REQUEST_CONTEXT_WINDOW_SECONDS", "900") or 900))
_last_recompute_ts: float = 0.0

# Guard for lazy state initialization (avoid races under concurrent calls).
_MONGO_SERVERSTATUS_STATE_LOCK = threading.Lock()


@dataclass
class _MetricThreshold:
    mean: float = 0.0
    std: float = 0.0
    threshold: float = 0.0  # mean + 3*sigma
    updated_at_ts: float = 0.0


_thresholds = {
    "error_rate_percent": _MetricThreshold(),
    "latency_seconds": _MetricThreshold(),
}

_last_alert_ts: Dict[str, float] = defaultdict(float)


# Log of dispatches for audit/observability v4
_DISPATCH_LOG_MAX = int(os.getenv("ALERT_DISPATCH_LOG_MAX", "500") or 500)
_dispatch_log: Deque[Dict[str, Any]] = deque(maxlen=max(50, _DISPATCH_LOG_MAX))


def reset_state_for_tests() -> None:
    """Clear in-memory buffers (for unit tests).

    Not intended for production use.
    """
    _samples.clear()
    # Make sure unit tests are not blocked by startup warmup.
    global _START_TIME
    try:
        _START_TIME = time.time() - float(_STARTUP_GRACE_PERIOD_SECONDS or 0) - 1.0
    except Exception:
        _START_TIME = time.time() - 3600.0
    global _last_recompute_ts
    _last_recompute_ts = 0.0
    for k in list(_thresholds.keys()):
        _thresholds[k] = _MetricThreshold()
    _dispatch_log.clear()
    _last_alert_ts.clear()
    _error_contexts.clear()
    _REQUEST_CONTEXTS.clear()


def _now() -> float:
    return time.time()


def _normalize_sample_source(source: Optional[str]) -> str:
    try:
        text = str(source or "").strip().lower()
    except Exception:
        text = ""
    if text.startswith("external"):
        return "external"
    return "internal"


def note_request(
    status_code: int,
    duration_seconds: float,
    ts: Optional[float] = None,
    *,
    context: Optional[Dict[str, Any]] = None,
    source: Optional[str] = None,
) -> None:
    """Record a single request sample into the 3h rolling window.

    ts: optional epoch seconds (for tests). Defaults to current time.
    """
    try:
        t = float(ts if ts is not None else _now())
        is_error = int(status_code) >= 500
        normalized_source = _normalize_sample_source(source)
        _samples.append((t, bool(is_error), max(0.0, float(duration_seconds)), normalized_source))
        if is_error and context:
            _record_error_context(t, context)
        if context:
            _record_request_context(t, duration_seconds, normalized_source, context)
        _evict_older_than(t - _WINDOW_SEC)
        _recompute_if_due(t)
    except Exception:
        return


def _record_request_context(
    ts: float,
    duration_seconds: float,
    source: str,
    context: Dict[str, Any],
) -> None:
    """Keep a small rolling buffer of request contexts for quick-fix enrichment.

    This is intentionally best-effort and keeps only a minimal subset of keys to
    avoid memory bloat and accidental PII retention.
    """
    try:
        # Only keep contexts that can help explain slowness/root cause.
        queue_delay_ms = None
        for key in ("queue_delay_ms", "queue_delay", "queue_time_ms", "queue_ms"):
            try:
                raw = context.get(key)
            except Exception:
                raw = None
            if raw in (None, ""):
                continue
            try:
                queue_delay_ms = int(float(raw))
            except Exception:
                queue_delay_ms = None
            if queue_delay_ms is not None:
                queue_delay_ms = max(0, queue_delay_ms)
                break
        duration_ms = int(max(0.0, float(duration_seconds)) * 1000.0)
        kept: Dict[str, Any] = {
            "source": str(source or ""),
            "duration_ms": duration_ms,
        }
        if queue_delay_ms is not None:
            kept["queue_delay_ms"] = int(queue_delay_ms)
        # Minimal routing context (no message text)
        for key in ("path", "endpoint", "route", "method", "handler", "command", "component", "request_id"):
            try:
                val = context.get(key)
            except Exception:
                val = None
            if val in (None, ""):
                continue
            try:
                kept[key] = str(val)[:256]
            except Exception:
                continue
        _REQUEST_CONTEXTS.append((float(ts), kept))
        cutoff = float(ts) - float(_REQUEST_CONTEXT_WINDOW_SEC)
        while _REQUEST_CONTEXTS and _REQUEST_CONTEXTS[0][0] < cutoff:
            _REQUEST_CONTEXTS.popleft()
    except Exception:
        return


def _evict_older_than(min_ts: float) -> None:
    try:
        while _samples and _samples[0][0] < min_ts:
            _samples.popleft()
    except Exception:
        return


def _recompute_if_due(now_ts: Optional[float] = None) -> None:
    global _last_recompute_ts
    t = float(now_ts if now_ts is not None else _now())
    if (t - _last_recompute_ts) < _RECOMPUTE_EVERY_SEC:
        return
    _last_recompute_ts = t
    try:
        _recompute_thresholds(t)
    except Exception:
        return


def _recompute_thresholds(now_ts: float) -> None:
    # Build per-minute buckets for last 3 hours
    start_ts = now_ts - _WINDOW_SEC
    per_minute: Dict[int, Dict[str, float]] = defaultdict(lambda: {"count": 0.0, "errors": 0.0, "lat_sum": 0.0})
    for ts, is_err, lat, sample_source in list(_samples):
        if ts < start_ts:
            continue
        if sample_source != "internal":
            continue
        minute = int(ts // 60)
        b = per_minute[minute]
        b["count"] += 1.0
        b["errors"] += 1.0 if is_err else 0.0
        b["lat_sum"] += float(lat)

    # If no data, keep thresholds at zero
    if not per_minute:
        for k in _thresholds:
            _thresholds[k] = _MetricThreshold(updated_at_ts=now_ts)
        _update_gauges(None, None, None, None)
        return

    # Compute per-minute error rate (%) and avg latency (s)
    err_rates: List[float] = []
    avg_lats: List[float] = []
    for _, b in sorted(per_minute.items()):
        c = b["count"]
        if c <= 0:
            continue
        err_pct = (b["errors"] / c) * 100.0
        err_rates.append(err_pct)
        avg_lats.append(b["lat_sum"] / c)

    def _mean_std(values: List[float]) -> Tuple[float, float]:
        if not values:
            return 0.0, 0.0
        mean = sum(values) / float(len(values))
        if len(values) == 1:
            return mean, 0.0
        var = sum((v - mean) ** 2 for v in values) / float(len(values))
        return mean, math.sqrt(var)

    err_mean, err_std = _mean_std(err_rates)
    lat_mean, lat_std = _mean_std(avg_lats)

    err_thr = max(0.0, err_mean + 3.0 * err_std) * _THRESHOLD_SCALES["error_rate_percent"]
    lat_thr = max(0.0, lat_mean + 3.0 * lat_std) * _THRESHOLD_SCALES["latency_seconds"]
    # Apply safety floors (configurable via env)
    err_thr = max(err_thr, _MIN_ERR_RATE_FLOOR)
    lat_thr = max(lat_thr, _MIN_LATENCY_FLOOR)

    _thresholds["error_rate_percent"] = _MetricThreshold(
        mean=err_mean, std=err_std, threshold=err_thr, updated_at_ts=now_ts
    )
    _thresholds["latency_seconds"] = _MetricThreshold(
        mean=lat_mean, std=lat_std, threshold=lat_thr, updated_at_ts=now_ts
    )

    # Update Prometheus gauges (best-effort, lazy import to avoid cycles)
    try:
        # שמור עקביות: ספים מחושבים רק על דגימות פנימיות, ולכן גם ה-"current" gauges
        # צריכים לשקף את אותו מקור (ולא לכלול תקלות חיצוניות/Circuit Breaker).
        cur_err = get_current_error_rate_percent(window_sec=5 * 60, source="internal")
        cur_lat = get_current_avg_latency_seconds(window_sec=5 * 60, source="internal")
        _update_gauges(err_thr, lat_thr, cur_err, cur_lat)
    except Exception:
        _update_gauges(err_thr, lat_thr, None, None)


def _update_gauges(
    err_thr_pct: Optional[float],
    lat_thr_sec: Optional[float],
    cur_err_pct: Optional[float],
    cur_lat_sec: Optional[float],
) -> None:
    try:
        from metrics import set_adaptive_observability_gauges  # type: ignore
        set_adaptive_observability_gauges(
            error_rate_threshold_percent=err_thr_pct,
            latency_threshold_seconds=lat_thr_sec,
            current_error_rate_percent=cur_err_pct,
            current_latency_avg_seconds=cur_lat_sec,
        )
    except Exception:
        return


def _update_external_error_rate_gauge(value: Optional[float]) -> None:
    try:
        from metrics import set_external_error_rate_percent  # type: ignore
        set_external_error_rate_percent(value)
    except Exception:
        return


def _collect_recent_samples(window_sec: int, source_filter: Optional[str] = None) -> Tuple[int, int, float]:
    try:
        now_ts = _now()
        start = now_ts - max(1, int(window_sec))
        total = 0
        errors = 0
        sum_lat = 0.0
        target_source = None
        if source_filter:
            lowered = str(source_filter).strip().lower()
            if lowered in {"internal", "external"}:
                target_source = lowered
        for ts, is_err, lat, sample_source in reversed(_samples):
            if ts < start:
                break
            if target_source is not None and sample_source != target_source:
                continue
            total += 1
            if is_err:
                errors += 1
            sum_lat += float(lat)
        return total, errors, sum_lat
    except Exception:
        return 0, 0, 0.0


def _sanitize_error_context(context: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not isinstance(context, dict):
        return None
    allowed_keys = ("command", "handler", "path", "method", "request_id", "user_id", "source", "component")
    sanitized: Dict[str, str] = {}
    for key in allowed_keys:
        try:
            value = context.get(key)
        except Exception:
            continue
        if value in (None, ""):
            continue
        try:
            text = str(value).strip()
        except Exception:
            continue
        if not text:
            continue
        limit = 64 if key in {"request_id", "user_id"} else 200
        sanitized[key] = text[:limit]
    return sanitized or None


def _record_error_context(ts: float, context: Optional[Dict[str, Any]]) -> None:
    sanitized = _sanitize_error_context(context)
    if not sanitized:
        return
    try:
        _error_contexts.append((ts, sanitized))
    except Exception:
        pass


def _recent_error_contexts(now_ts: float, window_sec: int = _ERROR_CONTEXT_WINDOW_SEC) -> List[Dict[str, Any]]:
    cutoff = now_ts - max(1, int(window_sec))
    while _error_contexts and _error_contexts[0][0] < cutoff:
        try:
            _error_contexts.popleft()
        except Exception:
            break
    return [ctx for _, ctx in list(_error_contexts)]


def _queue_delay_stats(now_ts: float, *, window_sec: int = 300, source: Optional[str] = None) -> Dict[str, Any]:
    """Compute best-effort queue-delay stats from recent request contexts."""
    try:
        window = max(1, int(window_sec))
    except Exception:
        window = 300
    cutoff = float(now_ts) - float(window)
    target_source = None
    if source:
        try:
            s = str(source).strip().lower()
        except Exception:
            s = ""
        if s in {"internal", "external"}:
            target_source = s

    # Evict old entries (best-effort)
    try:
        while _REQUEST_CONTEXTS and _REQUEST_CONTEXTS[0][0] < cutoff:
            _REQUEST_CONTEXTS.popleft()
    except Exception:
        pass

    values: List[int] = []
    try:
        for ts, ctx in list(_REQUEST_CONTEXTS):
            if ts < cutoff:
                continue
            if not isinstance(ctx, dict):
                continue
            if target_source is not None:
                try:
                    if str(ctx.get("source") or "").strip().lower() != target_source:
                        continue
                except Exception:
                    continue
            q = ctx.get("queue_delay_ms")
            if q in (None, ""):
                continue
            try:
                values.append(max(0, int(float(q))))
            except Exception:
                continue
    except Exception:
        return {}

    if not values:
        return {}
    values.sort()
    n = len(values)
    avg = int(round(sum(values) / float(n)))
    # P95 via "nearest-rank" (avoid underestimating for small samples).
    # Example: n=10 -> ceil(0.95*10)-1 = 9 (max element), not 8.
    try:
        p95_idx = int(math.ceil(0.95 * float(n))) - 1
    except Exception:
        p95_idx = n - 1
    p95_idx = max(0, min(n - 1, int(p95_idx)))
    p95 = int(values[p95_idx])
    mx = int(values[-1])
    return {
        "queue_delay_ms_avg": avg,
        "queue_delay_ms_p95": p95,
        "queue_delay_ms_max": mx,
        "queue_delay_samples": int(n),
    }


def _system_resource_snapshot() -> Dict[str, Any]:
    """Best-effort resource snapshot (CPU/RAM + in-flight requests)."""
    out: Dict[str, Any] = {}
    try:
        import psutil  # type: ignore

        try:
            out["cpu_percent"] = float(psutil.cpu_percent(interval=None))
        except Exception:
            pass
        try:
            vm = psutil.virtual_memory()
            out["memory_percent"] = float(getattr(vm, "percent", 0.0) or 0.0)
        except Exception:
            pass
    except Exception:
        pass

    # Active requests + RSS are tracked in metrics (best-effort, avoid hard dependency)
    try:
        from metrics import get_active_requests_count, get_current_memory_usage  # type: ignore

        try:
            out["active_requests"] = int(get_active_requests_count())
        except Exception:
            pass
        try:
            out["memory_mb"] = round(float(get_current_memory_usage()), 2)
        except Exception:
            pass
    except Exception:
        pass
    return {k: v for k, v in out.items() if v not in (None, "")}


def _mongo_connections_snapshot() -> Dict[str, Any]:
    """Best-effort MongoDB connections snapshot.

    NOTE: This is *not* PyMongo client-side pool utilization; it's server-reported
    connections.current/available which is still a useful pressure signal.
    """
    # חשוב: פונקציה זו נקראת מנתיבי בקשה (דרך metrics.record_request_outcome -> check_and_emit_alerts),
    # ולכן אסור לה לבצע IO חוסם. אנחנו מחזירים Cache ומרעננים ברקע (best-effort).
    out: Dict[str, Any] = {}
    try:
        from database import db as db_manager  # type: ignore
    except Exception:
        return {}
    try:
        client = getattr(db_manager, "client", None)
    except Exception:
        client = None
    if client is None:
        return {}

    # --- cache + refresh scheduling ---
    # Module-level cache to avoid blocking the main thread / event loop.
    # We keep the state on the function object to minimize global clutter and preserve backwards compatibility.
    state = getattr(_mongo_connections_snapshot, "_state", None)
    if state is None:
        # Avoid creating multiple independent state dicts under concurrency.
        with _MONGO_SERVERSTATUS_STATE_LOCK:
            state = getattr(_mongo_connections_snapshot, "_state", None)
            if state is None:
                state = {
                    "lock": threading.Lock(),
                    "ts": 0.0,
                    "data": {},
                    "inflight": False,
                }
                setattr(_mongo_connections_snapshot, "_state", state)

    def _refresh_interval_seconds() -> float:
        # Default 5s to match guides. Allow tuning via env.
        try:
            return max(1.0, float(os.getenv("MONGO_SERVERSTATUS_REFRESH_SEC", "5") or "5"))
        except Exception:
            return 5.0

    def _parse_status(status_obj: Any) -> Dict[str, Any]:
        try:
            connections = status_obj.get("connections") if isinstance(status_obj, dict) else None
        except Exception:
            connections = None
        if not isinstance(connections, dict):
            return {}
        current = connections.get("current")
        available = connections.get("available")
        try:
            cur_i = int(current)
            avail_i = int(available)
        except Exception:
            return {}
        total = max(0, cur_i) + max(0, avail_i)
        util = (float(max(0, cur_i)) / float(total) * 100.0) if total > 0 else 0.0
        return {
            "db_connections_current": int(max(0, cur_i)),
            "db_connections_available": int(max(0, avail_i)),
            "db_pool_utilization_pct": round(util, 1),
        }

    def _set_cache(data: Dict[str, Any]) -> None:
        try:
            with state["lock"]:
                state["data"] = dict(data or {})
                state["ts"] = float(time.time())
        except Exception:
            return

    def _mark_inflight(val: bool) -> None:
        try:
            with state["lock"]:
                state["inflight"] = bool(val)
        except Exception:
            return

    def _should_refresh(now_ts: float) -> bool:
        try:
            with state["lock"]:
                last_ts = float(state.get("ts") or 0.0)
                inflight = bool(state.get("inflight"))
        except Exception:
            last_ts = 0.0
            inflight = False
        age = max(0.0, float(now_ts - last_ts))
        return (not inflight) and (age >= _refresh_interval_seconds())

    def _schedule_refresh() -> None:
        # Atomically check + mark inflight under the same lock to prevent TOCTOU races
        # that can trigger multiple concurrent refreshes.
        now_ts = time.time()
        try:
            with state["lock"]:
                last_ts = float(state.get("ts") or 0.0)
                inflight = bool(state.get("inflight"))
                age = max(0.0, float(now_ts - last_ts))
                if inflight or age < _refresh_interval_seconds():
                    return
                state["inflight"] = True
        except Exception:
            return

        # Try async Motor first (if admin.command is awaitable), otherwise offload sync PyMongo to executor/thread.
        try:
            cmd = getattr(getattr(client, "admin", None), "command", None)
        except Exception:
            cmd = None

        def _finalize() -> None:
            _mark_inflight(False)

        # Async path (Motor-like)
        try:
            if callable(cmd):
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    loop = None
                if loop is not None:
                    try:
                        maybe_coro = cmd("serverStatus")  # type: ignore[misc]
                    except Exception:
                        maybe_coro = None
                    if maybe_coro is not None and asyncio.iscoroutine(maybe_coro):
                        try:
                            task = loop.create_task(maybe_coro)
                        except Exception:
                            # Prevent "coroutine was never awaited" warnings when task creation fails
                            # (e.g. loop is closing).
                            try:
                                maybe_coro.close()  # type: ignore[attr-defined]
                            except Exception:
                                pass
                            raise
                        def _done_cb(fut: "asyncio.Future[Any]") -> None:  # type: ignore[name-defined]
                            try:
                                res = fut.result()
                                _set_cache(_parse_status(res))
                            except Exception:
                                pass
                            finally:
                                _finalize()
                        task.add_done_callback(_done_cb)
                        return
        except Exception:
            # If anything fails here, fall back to sync executor below.
            pass

        # Sync path (PyMongo-like): run in executor if loop exists, otherwise spawn a daemon thread.
        def _job_sync() -> None:
            try:
                status_obj = client.admin.command("serverStatus")  # type: ignore[attr-defined]
                _set_cache(_parse_status(status_obj))
            except Exception:
                pass
            finally:
                _finalize()

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is not None:
            try:
                loop.run_in_executor(None, _job_sync)
                return
            except Exception:
                pass
        try:
            threading.Thread(target=_job_sync, name="mongo-serverstatus-refresh", daemon=True).start()
        except Exception:
            # If we can't even spawn a thread, just mark done and move on.
            _finalize()

    # Kick a refresh if stale, but always return cached snapshot immediately.
    try:
        _schedule_refresh()
    except Exception:
        pass
    try:
        with state["lock"]:
            cached = dict(state.get("data") or {})
    except Exception:
        cached = {}
    return cached


def _derive_feature_from_command(command: Optional[str]) -> Optional[str]:
    if not command:
        return None
    try:
        text = str(command).strip()
    except Exception:
        return None
    if not text:
        return None
    if ":" in text:
        candidate = text.split(":")[-1]
    else:
        candidate = text
    candidate = candidate.strip()
    return candidate or None


def _format_error_rate_meta_summary(
    label: Optional[str],
    current_pct: float,
    threshold_pct: float,
    request_id: Optional[str],
) -> str:
    parts: List[str] = []
    if label:
        parts.append(label)
    parts.append(f"error_rate {current_pct:.2f}% > {max(threshold_pct, 0.0):.2f}%")
    if request_id:
        short = request_id[:8]
        parts.append(f"request {short}")
    return " · ".join(parts)


def _build_high_error_rate_meta(
    current_pct: float,
    threshold_pct: float,
    sample_count: int,
    now_ts: float,
    window_sec: int,
    preferred_source: Optional[str] = None,
) -> Dict[str, Any]:
    contexts = _recent_error_contexts(now_ts, window_sec)
    normalized_pref = (preferred_source or "").strip().lower() or None
    if normalized_pref:
        filtered = [ctx for ctx in contexts if (ctx.get("source") or "internal").lower() == normalized_pref]
        if filtered:
            contexts = filtered
    meta: Dict[str, Any] = {
        "alert_type": "high_error_rate",
        "metric": "error_rate_percent",
        "metric_name": "error_rate_percent",
        "graph_metric": "error_rate_percent",
        "error_rate_percent": round(current_pct, 4),
        "threshold_percent": round(threshold_pct, 4),
        "sample_count": int(sample_count),
        "window_seconds": int(window_sec),
        "recent_error_context_count": len(contexts),
    }
    dominant_label = None
    if contexts:
        commands = [ctx.get("command") for ctx in contexts if ctx.get("command")]
        dominant_command = None
        if commands:
            counts = Counter(commands)
            dominant_command = counts.most_common(1)[0][0]
            if dominant_command:
                meta["command"] = dominant_command
                feature = _derive_feature_from_command(dominant_command)
                if feature:
                    meta["feature"] = feature
                    dominant_label = feature
                else:
                    dominant_label = dominant_command
        latest = contexts[-1]
        endpoint = latest.get("path") or latest.get("handler")
        if endpoint:
            meta["endpoint"] = endpoint
            if dominant_label is None:
                dominant_label = endpoint
        method = latest.get("method")
        if method:
            meta["method"] = method
        source = latest.get("source")
        if source and "source" not in meta:
            meta["source"] = source
        component = latest.get("component")
        if component:
            meta["component"] = component
        request_id = latest.get("request_id")
        if request_id:
            meta["request_id"] = request_id
        user_id = latest.get("user_id")
        if user_id:
            meta["user_id"] = user_id
    else:
        request_id = None

    if "request_id" not in meta:
        request_id = None
    else:
        request_id = str(meta["request_id"])
    label = dominant_label or "high_error_rate"
    meta["meta_summary"] = _format_error_rate_meta_summary(label, current_pct, threshold_pct, request_id)
    return meta


def _enrich_alert_details(key: str, details: Dict[str, Any], now_ts: float) -> Dict[str, Any]:
    if str(key) == "latency_seconds":
        enriched = dict(details or {})
        # Normalize alert_type so dashboards/runbooks can match reliably.
        enriched.setdefault("alert_type", "slow_response")
        # Provide a consistent duration_ms signal for quick-fix decisioning.
        if "duration_ms" not in enriched:
            try:
                cur = float(enriched.get("current_seconds") or 0.0)
                if cur > 0:
                    enriched["duration_ms"] = int(round(cur * 1000.0))
            except Exception:
                pass
        # Best-effort queue-delay stats from recent request contexts.
        try:
            window_sec = int(enriched.get("window_seconds") or 300)
        except Exception:
            window_sec = 300
        try:
            enriched.update(_queue_delay_stats(now_ts, window_sec=window_sec, source=enriched.get("source")))
        except Exception:
            pass
        # Best-effort resource snapshot (cpu/mem + active_requests).
        try:
            enriched.update(_system_resource_snapshot())
        except Exception:
            pass
        # Best-effort DB "pool" pressure snapshot (connections utilization).
        try:
            enriched.update(_mongo_connections_snapshot())
        except Exception:
            pass
        return enriched

    if str(key) != "error_rate_percent":
        return details
    try:
        current_pct = float(details.get("current_percent") or details.get("error_rate_percent") or 0.0)
    except Exception:
        current_pct = 0.0
    try:
        threshold_pct = float(details.get("threshold_percent") or _thresholds.get("error_rate_percent", _MetricThreshold()).threshold or 0.0)
    except Exception:
        threshold_pct = 0.0
    try:
        sample_count = int(details.get("sample_count") or 0)
    except Exception:
        sample_count = 0
    try:
        window_sec = int(details.get("window_seconds") or _ERROR_CONTEXT_WINDOW_SEC)
    except Exception:
        window_sec = _ERROR_CONTEXT_WINDOW_SEC
    preferred_source = None
    try:
        src = details.get("source")
        if src:
            preferred_source = str(src).strip().lower() or None
    except Exception:
        preferred_source = None
    meta = _build_high_error_rate_meta(
        current_pct,
        threshold_pct,
        sample_count,
        now_ts,
        window_sec,
        preferred_source=preferred_source,
    )
    existing_source = details.get("source")
    details.update(meta)
    if existing_source is not None:
        details["source"] = existing_source
    return details


def get_current_error_rate_percent(window_sec: int = 300, *, source: Optional[str] = None) -> float:
    """Return error rate percent for the last window (default 5 minutes)."""
    try:
        total, errors, _ = _collect_recent_samples(window_sec, source_filter=source)
        if total <= 0:
            return 0.0
        return (float(errors) / float(total)) * 100.0
    except Exception:
        return 0.0


def get_current_avg_latency_seconds(window_sec: int = 300, *, source: Optional[str] = None) -> float:
    """Return average latency in seconds for the last window (default 5 minutes)."""
    try:
        total, _errors, sum_lat = _collect_recent_samples(window_sec, source_filter=source)
        if total <= 0:
            return 0.0
        return float(sum_lat) / float(total)
    except Exception:
        return 0.0


def get_request_stats_between(
    start_dt: datetime,
    end_dt: datetime,
    *,
    source: Optional[str] = None,
    percentiles: Tuple[int, ...] = (50, 95, 99),
) -> Dict[str, float]:
    """Best-effort request stats for an arbitrary time window מתוך ה-buffer בזיכרון.

    מחזיר:
    - total (int as float)
    - errors (int as float)
    - p50/p95/p99 (seconds) אם יש דגימות

    הערה: היסטוריה זמינה רק עד ~3 שעות (WINDOW_SEC).
    """
    try:
        # Normalize inputs to UTC timestamps
        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=timezone.utc)
        else:
            start_dt = start_dt.astimezone(timezone.utc)
        if end_dt.tzinfo is None:
            end_dt = end_dt.replace(tzinfo=timezone.utc)
        else:
            end_dt = end_dt.astimezone(timezone.utc)
    except Exception:
        start_dt = start_dt.replace(tzinfo=timezone.utc)
        end_dt = end_dt.replace(tzinfo=timezone.utc)

    start_ts = float(start_dt.timestamp())
    end_ts = float(end_dt.timestamp())
    if end_ts <= start_ts:
        return {"total": 0.0, "errors": 0.0}

    src_norm = _normalize_sample_source(source) if source else None
    total = 0
    errors = 0
    lats: List[float] = []
    try:
        for ts, is_err, lat, sample_source in list(_samples):
            if ts < start_ts or ts > end_ts:
                continue
            if src_norm and sample_source != src_norm:
                continue
            total += 1
            if is_err:
                errors += 1
            try:
                lats.append(float(lat))
            except Exception:
                continue
    except Exception:
        return {"total": float(total), "errors": float(errors)}

    out: Dict[str, float] = {"total": float(total), "errors": float(errors)}
    if not lats:
        return out
    lats.sort()

    def _nearest_rank(p: int) -> float:
        n = len(lats)
        if n <= 0:
            return 0.0
        try:
            k = int(math.ceil((float(p) / 100.0) * float(n))) - 1
        except Exception:
            k = 0
        k = max(0, min(n - 1, k))
        return float(lats[k])

    try:
        pcts = tuple(int(p) for p in (percentiles or (50, 95, 99)))
    except Exception:
        pcts = (50, 95, 99)
    for p in pcts:
        if 0 < int(p) < 100:
            out[f"p{int(p)}"] = _nearest_rank(int(p))
    return out


def bump_threshold(kind: str, factor: float = 1.2) -> None:
    """Multiply the current adaptive threshold by a factor and refresh gauges (best-effort)."""
    try:
        thr = _thresholds.get(kind)
        if not thr:
            return
        current = float(thr.threshold or 0.0)
        if current <= 0.0:
            return
        thr.threshold = current * float(factor)
        thr.updated_at_ts = _now()
        try:
            cur_err = get_current_error_rate_percent(window_sec=5 * 60, source="internal")
            cur_lat = get_current_avg_latency_seconds(window_sec=5 * 60, source="internal")
        except Exception:
            cur_err = None
            cur_lat = None
        if kind == "error_rate_percent":
            _update_gauges(thr.threshold, None, cur_err, cur_lat)
        elif kind == "latency_seconds":
            _update_gauges(None, thr.threshold, cur_err, cur_lat)
    except Exception:
        return


def get_thresholds_snapshot() -> Dict[str, Dict[str, float]]:
    """Return the latest thresholds for external consumers/tests."""
    out: Dict[str, Dict[str, float]] = {}
    try:
        for k, v in _thresholds.items():
            out[k] = {
                "mean": float(v.mean or 0.0),
                "std": float(v.std or 0.0),
                "threshold": float(v.threshold or 0.0),
                "updated_at_ts": float(v.updated_at_ts or 0.0),
            }
    except Exception:
        pass
    return out


def _should_fire(kind: str, value: float, sample_count: Optional[int] = None) -> bool:
    thr = _thresholds.get(kind)
    if not thr:
        return False
    if sample_count is not None:
        try:
            min_required = int(_MIN_SAMPLE_REQUIREMENTS.get(kind, 0))
        except Exception:
            min_required = 0
        if sample_count < max(0, min_required):
            return False
    return value > max(0.0, float(thr.threshold or 0.0))


def _emit_warning_once(key: str, name: str, summary: str, details: Dict[str, Any], now_ts: float) -> None:
    try:
        details = dict(details or {})
    except Exception:
        details = {}
    last = _last_alert_ts.get(key, 0.0)
    if (now_ts - last) < _COOLDOWN_SEC:
        return
    _last_alert_ts[key] = now_ts
    try:
        from internal_alerts import emit_internal_alert  # type: ignore
        emit_internal_alert(name=name, severity="warning", summary=summary, **details)
    except Exception:
        try:
            emit_event("external_warning", severity="warning", name=name, summary=summary, **details)
        except Exception:
            pass


def check_and_emit_alerts(now_ts: Optional[float] = None) -> None:
    """Evaluate current stats vs adaptive thresholds and emit critical alerts when breached.

    Cooldowns ensure we do not spam more than once per 5 minutes per alert type.
    """
    try:
        uptime = time.time() - float(_START_TIME or 0.0)
        if float(_STARTUP_GRACE_PERIOD_SECONDS or 0) > 0 and uptime < float(_STARTUP_GRACE_PERIOD_SECONDS):
            return
    except Exception:
        # Fail-open: if anything goes wrong, do not block alerting.
        pass
    t = float(now_ts if now_ts is not None else _now())
    try:
        _recompute_if_due(t)

        window_sec = 5 * 60
        internal_total, internal_errors, internal_latency_sum = _collect_recent_samples(window_sec, source_filter="internal")
        external_total, external_errors, _ = _collect_recent_samples(window_sec, source_filter="external")

        # Error rate (internal only)
        cur_err_pct = (float(internal_errors) / float(internal_total) * 100.0) if internal_total > 0 else 0.0
        try:
            err_threshold = float(_thresholds.get("error_rate_percent", _MetricThreshold()).threshold or 0.0)
        except Exception:
            err_threshold = 0.0
        if internal_total > 0 and _should_fire("error_rate_percent", cur_err_pct, internal_total):
            details = {
                "current_percent": round(cur_err_pct, 4),
                "sample_count": int(internal_total),
                "error_count": int(internal_errors),
                "threshold_percent": round(err_threshold, 4),
                "window_seconds": int(window_sec),
                "metric": "error_rate_percent",
                "graph_metric": "error_rate_percent",
                "source": "internal",
            }
            if external_total:
                details["external_sample_count"] = int(external_total)
                details["external_error_count"] = int(external_errors)
            _emit_critical_once(
                key="error_rate_percent",
                name="High Error Rate",
                summary=f"error_rate={cur_err_pct:.2f}% > threshold={_thresholds['error_rate_percent'].threshold:.2f}%",
                details=details,
                now_ts=t,
            )

        # Latency
        cur_lat = (float(internal_latency_sum) / float(internal_total)) if internal_total > 0 else 0.0
        if internal_total > 0 and _should_fire("latency_seconds", cur_lat, internal_total):
            _emit_critical_once(
                key="latency_seconds",
                name="High Latency",
                summary=f"avg_latency={cur_lat:.3f}s > threshold={_thresholds['latency_seconds'].threshold:.3f}s",
                details={
                    "current_seconds": round(cur_lat, 4),
                    "sample_count": int(internal_total),
                    "window_seconds": int(window_sec),
                    "source": "internal",
                },
                now_ts=t,
            )

        # External tracking (warning only)
        external_err_pct = (float(external_errors) / float(external_total) * 100.0) if external_total > 0 else 0.0
        _update_external_error_rate_gauge(external_err_pct if external_total > 0 else 0.0)
        if (
            external_total >= _EXTERNAL_WARNING_MIN_SAMPLE_COUNT
            and external_err_pct >= _EXTERNAL_WARNING_THRESHOLD
        ):
            warning_details = {
                "current_percent": round(external_err_pct, 4),
                "sample_count": int(external_total),
                "error_count": int(external_errors),
                "window_seconds": int(window_sec),
                "threshold_percent": round(_EXTERNAL_WARNING_THRESHOLD, 4),
                "source": "external",
            }
            # Best-effort: derive "which service" from recent external error contexts.
            # This relies on metrics.record_request_outcome(...) feeding alert_manager.note_request(...)
            # with a context that includes component/command/path. If unavailable, we keep it empty.
            try:
                contexts = _recent_error_contexts(t, window_sec)
                ext = [c for c in (contexts or []) if str(c.get("source") or "").lower().startswith("external")]
                if ext:
                    def _most_common(key: str) -> Optional[str]:
                        vals = [str(c.get(key)).strip() for c in ext if c.get(key)]
                        if not vals:
                            return None
                        return Counter(vals).most_common(1)[0][0]
                    # Prefer component → command → path/handler
                    service_label = (
                        _most_common("component")
                        or _most_common("command")
                        or _most_common("path")
                        or _most_common("handler")
                    )
                    if service_label:
                        warning_details["service"] = service_label
            except Exception:
                pass
            _emit_warning_once(
                key="external_error_rate_percent",
                name="External Service Degraded",
                summary=f"external_error_rate={external_err_pct:.2f}% > threshold={_EXTERNAL_WARNING_THRESHOLD:.2f}%",
                details=warning_details,
                now_ts=t,
            )
    except Exception:
        return


def _emit_critical_once(key: str, name: str, summary: str, details: Dict[str, Any], now_ts: float) -> None:
    try:
        details = dict(details or {})
    except Exception:
        details = {}
    try:
        details = _enrich_alert_details(key, details, now_ts)
    except Exception:
        pass
    last = _last_alert_ts.get(key, 0.0)
    if (now_ts - last) < _COOLDOWN_SEC:
        return
    _last_alert_ts[key] = now_ts
    # Auto-remediation & incident logging (best-effort)
    # Safety switch: אל תפעיל remediation על Drill
    is_drill = False
    try:
        is_drill = bool(details.get("is_drill")) or bool((details.get("metadata") or {}).get("is_drill"))
    except Exception:
        is_drill = False
    if is_drill:
        try:
            emit_event(
                "drill_remediation_skipped",
                severity="anomaly",
                handled=True,
                name=str(name),
                metric=str(key),
            )
        except Exception:
            pass
    else:
        try:
            from remediation_manager import handle_critical_incident  # type: ignore
            try:
                if key == "error_rate_percent":
                    current_val = float(details.get("current_percent", 0.0) or 0.0)
                elif key == "latency_seconds":
                    current_val = float(details.get("current_seconds", 0.0) or 0.0)
                else:
                    current_val = 0.0
            except Exception:
                current_val = 0.0
            try:
                thr_val = float(_thresholds.get(key, _MetricThreshold()).threshold or 0.0)
            except Exception:
                thr_val = 0.0
            handle_critical_incident(name=name, metric=key, value=current_val, threshold=thr_val, details=details)
        except Exception:
            pass
    try:
        from internal_alerts import emit_internal_alert  # type: ignore
    except Exception:
        emit_internal_alert = None  # type: ignore

    try:
        if emit_internal_alert is not None:
            # internal_alerts will forward critical alerts via alert_manager.forward_critical_alert
            # to avoid duplicate dispatches, do not call _notify_critical_external when this path is taken
            emit_internal_alert(name=name, severity="critical", summary=summary, **details)
        else:
            # Fallback: ensure external delivery directly
            _notify_critical_external(name=name, summary=summary, details=details)
    except Exception:
        # Still attempt external sinks for visibility
        try:
            _notify_critical_external(name=name, summary=summary, details=details)
        except Exception:
            pass


def forward_critical_alert(name: str, summary: str, **details: Any) -> None:
    """Public API: forward a critical alert to sinks and log dispatches."""
    _notify_critical_external(name=name, summary=summary, details=details)


def _notify_critical_external(name: str, summary: str, details: Dict[str, Any]) -> None:
    """Send critical alert to sinks with silence enforcement and log dispatches.

    Enforcement:
    - If a matching active silence exists (pattern on name, optional severity), do not send to sinks
      but still record the alert in DB with silenced=true for transparency.
    """
    # Safety switch: Drill לא יוצא לסינקים, אבל כן נשמר ב-DB לצורך צפייה ב-Observability.
    try:
        is_drill = bool(details.get("is_drill")) or bool((details.get("metadata") or {}).get("is_drill"))
    except Exception:
        is_drill = False
    if is_drill:
        try:
            from monitoring.alerts_storage import record_alert  # type: ignore

            record_alert(
                alert_id=str(uuid.uuid4()),
                name=str(name),
                severity="critical",
                summary=str(summary),
                source="drill",
                silenced=True,
                details=details if isinstance(details, dict) else None,
            )
        except Exception:
            pass
        try:
            emit_event(
                "drill_critical_blocked",
                severity="anomaly",
                handled=True,
                name=str(name),
            )
        except Exception:
            pass
        return

    alert_id = str(uuid.uuid4())
    text = _format_text(name=name, severity="CRITICAL", summary=summary, details=details)
    # Silences check (best-effort)
    silenced = False
    silence_info: Optional[Dict[str, Any]] = None
    try:
        from monitoring.silences import is_silenced  # type: ignore
        silenced, silence_info = is_silenced(name=name, severity="critical")
    except Exception:
        silenced, silence_info = False, None

    # Persist to MongoDB (best-effort) for unified counts across services; include silenced flag
    try:
        from monitoring.alerts_storage import record_alert  # type: ignore
        record_alert(
            alert_id=alert_id,
            name=str(name),
            severity="critical",
            summary=str(summary),
            source="alert_manager",
            silenced=bool(silenced),
            details=details if isinstance(details, dict) else None,
        )
    except Exception:
        pass

    if silenced:
        # Emit observability event that alert was silenced (best-effort)
        try:
            emit_event(
                "alert_silenced",
                severity="info",
                alert_id=alert_id,
                name=name,
                silence_id=str((silence_info or {}).get("_id") or ""),
                until=str((silence_info or {}).get("until_ts") or ""),
            )
        except Exception:
            pass
    else:
        # Telegram
        _dispatch("telegram", alert_id, _send_telegram, text)
        # Grafana annotation
        _dispatch("grafana", alert_id, _send_grafana_annotation, name, summary)
    try:
        emit_event(
            "critical_alert_dispatched",
            severity="anomaly",
            alert_id=alert_id,
            name=name,
            handled=(not silenced),
        )
    except Exception:
        pass


def _dispatch(sink: str, alert_id: str, fn, *args) -> None:  # type: ignore[no-untyped-def]
    ts = datetime.now(timezone.utc).isoformat()
    ok = False
    try:
        fn(*args)
        ok = True
    except Exception:
        ok = False
    finally:
        _dispatch_log.append({"ts": ts, "alert_id": alert_id, "sink": sink, "ok": bool(ok)})


def _format_text(name: str, severity: str, summary: str, details: Dict[str, Any]) -> str:
    parts = [f"[{severity}] {name}"]
    if summary:
        parts.append(str(summary).strip())

    # Short allowlist of useful context
    def _get(d: Dict[str, Any], key: str) -> Optional[str]:
        try:
            v = d.get(key)
            return str(v) if v is not None and v != "" else None
        except Exception:
            return None

    service = _get(details, "service") or _get(details, "component")
    environment = _get(details, "env") or _get(details, "environment")
    request_id = _get(details, "request_id") or _get(details, "request-id") or _get(details, "x-request-id")

    if service:
        parts.append(f"service: {service}")
    if environment:
        parts.append(f"env: {environment}")
    if request_id:
        parts.append(f"request_id: {request_id}")

    # Append short sanitized details preview (without fields we already promoted)
    if details:
        sensitive = {"token", "password", "secret", "authorization"}
        promoted = {"service", "component", "env", "environment", "request_id", "request-id", "x-request-id"}
        sentry_meta = {"sentry", "sentry_url", "sentry-permalink", "sentry_permalink"}
        def _is_allowed(k: str) -> bool:
            lk = k.lower()
            return lk not in sensitive and lk not in promoted and lk not in sentry_meta

        safe_items = [(k, v) for k, v in details.items() if _is_allowed(str(k))]
        if safe_items:
            parts.append(
                ", ".join(f"{k}={v}" for k, v in safe_items[:6])
            )

    # Best-effort Sentry link (permalink or derived from request_id)
    sentry_direct = _get(details, "sentry_permalink") or _get(details, "sentry_url") or _get(details, "sentry")
    link = _build_sentry_link(direct_url=sentry_direct, request_id=request_id, error_signature=_get(details, "error_signature"))
    if link:
        parts.append(f"Sentry: {link}")

    # Best-effort: include Quick Fix suggestion (derived from runbooks + dynamic rules).
    try:
        from services.observability_dashboard import get_quick_fix_actions  # type: ignore

        snapshot = {
            "name": str(name or ""),
            "severity": str(severity or "").lower(),
            "summary": str(summary or ""),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "alert_type": str(details.get("alert_type") or ""),
            "metadata": details if isinstance(details, dict) else {},
        }
        actions = get_quick_fix_actions(snapshot, ui_context="bot_alert")
        if actions:
            top = actions[0] if isinstance(actions[0], dict) else None
            if top:
                label = str(top.get("label") or "").strip()
                hint = ""
                if str(top.get("type") or "").lower() == "copy" and top.get("payload"):
                    hint = f" → {top.get('payload')}"
                elif top.get("href"):
                    hint = f" → {top.get('href')}"
                if label:
                    parts.append(f"Quick Fix: {label}{hint}")
    except Exception:
        pass

    return "\n".join([p for p in parts if p])


def _build_sentry_link(
    direct_url: Optional[str] = None,
    request_id: Optional[str] = None,
    error_signature: Optional[str] = None,
) -> Optional[str]:
    try:
        if direct_url:
            return str(direct_url)
        dashboard = os.getenv("SENTRY_DASHBOARD_URL") or os.getenv("SENTRY_PROJECT_URL")
        if dashboard:
            base_url = dashboard.rstrip("/")
        else:
            dsn = os.getenv("SENTRY_DSN") or ""
            host = None
            if dsn:
                try:
                    from urllib.parse import urlparse
                    parsed = urlparse(dsn)
                    raw_host = parsed.hostname or ""
                except Exception:
                    raw_host = ""
                # Preserve region when present: o123.ingest.eu.sentry.io -> eu.sentry.io
                if ".ingest." in raw_host:
                    try:
                        host = raw_host.split(".ingest.", 1)[1]
                    except Exception:
                        host = None
                elif raw_host.startswith("ingest."):
                    host = raw_host[len("ingest."):]
                elif raw_host == "sentry.io" or raw_host.endswith(".sentry.io"):
                    host = "sentry.io"
                else:
                    host = raw_host or None
            host = host or "sentry.io"
            org = os.getenv("SENTRY_ORG") or os.getenv("SENTRY_ORG_SLUG")
            if not org:
                return None
            base_url = f"https://{host}/organizations/{org}/issues"
        from urllib.parse import quote_plus
        if request_id:
            q = quote_plus(f'request_id:"{request_id}"')
            return f"{base_url}/?query={q}&statsPeriod=24h"
        if error_signature:
            q = quote_plus(f'error_signature:"{error_signature}"')
            return f"{base_url}/?query={q}&statsPeriod=24h"
        return None
    except Exception:
        return None


def _send_telegram(text: str) -> None:
    token = os.getenv("ALERT_TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("ALERT_TELEGRAM_CHAT_ID")
    if not token or not chat_id or request is None:
        return
    api = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        from telegram_api import parse_telegram_json_from_response, require_telegram_ok

        resp = request('POST', api, json={"chat_id": chat_id, "text": text}, timeout=5)
        body = parse_telegram_json_from_response(resp, url=api)
        require_telegram_ok(body, url=api)
    except Exception as e:
        # do not raise
        try:
            from telegram_api import TelegramAPIError

            if isinstance(e, TelegramAPIError):
                emit_event(
                    "telegram_api_error",
                    severity="warn",
                    handled=True,
                    context="alert_manager.sendMessage",
                    error_code=getattr(e, "error_code", None),
                    description=getattr(e, "description", None),
                )
        except Exception:
            pass
        pass


def _send_grafana_annotation(name: str, summary: str) -> None:
    base = os.getenv("GRAFANA_URL")
    token = os.getenv("GRAFANA_API_TOKEN")
    if not base or not token or request is None:
        return
    url = base.rstrip("/") + "/api/annotations"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {
        "time": int(_now() * 1000),
        "tags": ["codebot", "alert", "critical"],
        "text": f"{name}: {summary}",
    }
    try:
        request('POST', url, json=payload, headers=headers, timeout=5)
    except Exception:
        # swallow errors
        pass


def get_dispatch_log(limit: int = 50) -> List[Dict[str, Any]]:
    try:
        if limit <= 0:
            return []
        return list(_dispatch_log)[-limit:]
    except Exception:
        return []
