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
"""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Tuple, Optional
import math
import os
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


# --- In-memory state ---
_WINDOW_SEC = 3 * 60 * 60  # 3 hours
_RECOMPUTE_EVERY_SEC = 5 * 60  # 5 minutes
_COOLDOWN_SEC = 5 * 60  # minimum gap between alerts of same type

_samples: Deque[Tuple[float, bool, float]] = deque(maxlen=200_000)  # (ts, is_error, latency_s)
_last_recompute_ts: float = 0.0


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
    global _last_recompute_ts
    _last_recompute_ts = 0.0
    for k in list(_thresholds.keys()):
        _thresholds[k] = _MetricThreshold()
    _dispatch_log.clear()
    _last_alert_ts.clear()


def _now() -> float:
    return time.time()


def note_request(status_code: int, duration_seconds: float, ts: Optional[float] = None) -> None:
    """Record a single request sample into the 3h rolling window.

    ts: optional epoch seconds (for tests). Defaults to current time.
    """
    try:
        t = float(ts if ts is not None else _now())
        is_error = int(status_code) >= 500
        _samples.append((t, bool(is_error), max(0.0, float(duration_seconds))))
        _evict_older_than(t - _WINDOW_SEC)
        _recompute_if_due(t)
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
    for ts, is_err, lat in list(_samples):
        if ts < start_ts:
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

    err_thr = max(0.0, err_mean + 3.0 * err_std)
    lat_thr = max(0.0, lat_mean + 3.0 * lat_std)

    _thresholds["error_rate_percent"] = _MetricThreshold(
        mean=err_mean, std=err_std, threshold=err_thr, updated_at_ts=now_ts
    )
    _thresholds["latency_seconds"] = _MetricThreshold(
        mean=lat_mean, std=lat_std, threshold=lat_thr, updated_at_ts=now_ts
    )

    # Update Prometheus gauges (best-effort, lazy import to avoid cycles)
    try:
        cur_err = get_current_error_rate_percent(window_sec=5 * 60)
        cur_lat = get_current_avg_latency_seconds(window_sec=5 * 60)
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


def get_current_error_rate_percent(window_sec: int = 300) -> float:
    """Return error rate percent for the last window (default 5 minutes)."""
    try:
        now_ts = _now()
        start = now_ts - max(1, int(window_sec))
        total = 0.0
        errors = 0.0
        for ts, is_err, _lat in reversed(_samples):
            if ts < start:
                break
            total += 1.0
            if is_err:
                errors += 1.0
        if total <= 0.0:
            return 0.0
        return (errors / total) * 100.0
    except Exception:
        return 0.0


def get_current_avg_latency_seconds(window_sec: int = 300) -> float:
    """Return average latency in seconds for the last window (default 5 minutes)."""
    try:
        now_ts = _now()
        start = now_ts - max(1, int(window_sec))
        total = 0.0
        sum_lat = 0.0
        for ts, _is_err, lat in reversed(_samples):
            if ts < start:
                break
            total += 1.0
            sum_lat += float(lat)
        if total <= 0.0:
            return 0.0
        return sum_lat / total
    except Exception:
        return 0.0


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
            cur_err = get_current_error_rate_percent(window_sec=5 * 60)
            cur_lat = get_current_avg_latency_seconds(window_sec=5 * 60)
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


def _should_fire(kind: str, value: float) -> bool:
    thr = _thresholds.get(kind)
    if not thr:
        return False
    return value > max(0.0, float(thr.threshold or 0.0))


def check_and_emit_alerts(now_ts: Optional[float] = None) -> None:
    """Evaluate current stats vs adaptive thresholds and emit critical alerts when breached.

    Cooldowns ensure we do not spam more than once per 5 minutes per alert type.
    """
    t = float(now_ts if now_ts is not None else _now())
    try:
        _recompute_if_due(t)

        # Error rate
        cur_err_pct = get_current_error_rate_percent(window_sec=5 * 60)
        if _should_fire("error_rate_percent", cur_err_pct):
            _emit_critical_once(
                key="error_rate_percent",
                name="High Error Rate",
                summary=f"error_rate={cur_err_pct:.2f}% > threshold={_thresholds['error_rate_percent'].threshold:.2f}%",
                details={"current_percent": round(cur_err_pct, 4)},
                now_ts=t,
            )

        # Latency
        cur_lat = get_current_avg_latency_seconds(window_sec=5 * 60)
        if _should_fire("latency_seconds", cur_lat):
            _emit_critical_once(
                key="latency_seconds",
                name="High Latency",
                summary=f"avg_latency={cur_lat:.3f}s > threshold={_thresholds['latency_seconds'].threshold:.3f}s",
                details={"current_seconds": round(cur_lat, 4)},
                now_ts=t,
            )
    except Exception:
        return


def _emit_critical_once(key: str, name: str, summary: str, details: Dict[str, Any], now_ts: float) -> None:
    last = _last_alert_ts.get(key, 0.0)
    if (now_ts - last) < _COOLDOWN_SEC:
        return
    _last_alert_ts[key] = now_ts
    # Auto-remediation & incident logging (best-effort)
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
        record_alert(alert_id=alert_id, name=str(name), severity="critical", summary=str(summary), source="alert_manager", silenced=bool(silenced))
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
    parts = [f"[{severity}] {name}", str(summary or "").strip()]
    if details:
        safe = {k: v for k, v in details.items() if k.lower() not in {"token", "password", "secret", "authorization"}}
        if safe:
            parts.append(", ".join(f"{k}={v}" for k, v in list(safe.items())[:6]))
    return "\n".join([p for p in parts if p])


def _send_telegram(text: str) -> None:
    token = os.getenv("ALERT_TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("ALERT_TELEGRAM_CHAT_ID")
    if not token or not chat_id or request is None:
        return
    api = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        request('POST', api, json={"chat_id": chat_id, "text": text}, timeout=5)
    except Exception:
        # do not raise
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
