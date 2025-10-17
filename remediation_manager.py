"""
Auto-remediation manager for critical incidents.

- Persists incidents to data/incidents_log.json (append-only JSON lines)
- Triggers remediation actions based on incident type
- Adds Grafana annotations for visibility (best-effort)
- Implements simple 15-minute recurrence detection and adaptive threshold bump hook

Environment variables (optional):
- GRAFANA_URL, GRAFANA_API_TOKEN for annotations

Notes:
- File I/O is constrained under data/ per workspace safety rules
- All operations are best-effort; never raise from public APIs
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional, List
import hashlib
import json
import os
import threading
import uuid

try:  # optional dependency
    import requests  # type: ignore
except Exception:  # pragma: no cover
    requests = None  # type: ignore

def _emit_event(event: str, severity: str = "info", **fields) -> None:
    """Dynamic event emitter to honor test-time monkeypatching.

    Imports observability at call-time so stubs in sys.modules are respected.
    """
    try:
        from importlib import import_module
        obs = import_module('observability')
        fn = getattr(obs, 'emit_event', None)
        if callable(fn):
            fn(event, severity=severity, **fields)
    except Exception:
        return

# Optional cache manager for remediation
try:
    from cache_manager import cache as _cache  # type: ignore
except Exception:  # pragma: no cover
    _cache = None  # type: ignore

# Optional DB reconnection
try:
    from database.manager import DatabaseManager  # type: ignore
except Exception:  # pragma: no cover
    DatabaseManager = None  # type: ignore


_LOCK = threading.Lock()
_DATA_DIR = os.path.join("data")
_INCIDENTS_FILE = os.path.join(_DATA_DIR, "incidents_log.json")
_FIFTEEN_MIN = 15 * 60


def _ensure_dirs() -> None:
    try:
        os.makedirs(_DATA_DIR, exist_ok=True)
    except Exception:
        pass


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash_incident_key(name: str, metric: str, details: Dict[str, Any]) -> str:
    # Recurrence grouping should ignore volatile details like current values
    # to ensure the same incident type groups together across occurrences.
    base = json.dumps({
        "name": name,
        "metric": metric,
    }, sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(base.encode("utf-8")).hexdigest()[:12]


def _write_incident(record: Dict[str, Any]) -> None:
    try:
        _ensure_dirs()
        line = json.dumps(record, ensure_ascii=False)
        # Append-only JSONL for simplicity and robustness
        with _LOCK:
            with open(_INCIDENTS_FILE, "a", encoding="utf-8") as f:
                f.write(line + "\n")
    except Exception:
        pass


def _read_incidents(limit: Optional[int] = None) -> List[Dict[str, Any]]:
    try:
        with _LOCK:
            if not os.path.exists(_INCIDENTS_FILE):
                return []
            items: List[Dict[str, Any]] = []
            with open(_INCIDENTS_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    t = (line or "").strip()
                    if not t:
                        continue
                    try:
                        items.append(json.loads(t))
                    except Exception:
                        continue
        return items[-limit:] if (limit and limit > 0) else items
    except Exception:
        return []


def _grafana_annotate(text: str) -> None:
    base = os.getenv("GRAFANA_URL")
    token = os.getenv("GRAFANA_API_TOKEN")
    if not base or not token or requests is None:
        return
    try:
        url = base.rstrip("/") + "/api/annotations"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        payload = {"time": int(datetime.now(timezone.utc).timestamp() * 1000), "tags": ["codebot", "incident"], "text": text}
        requests.post(url, json=payload, headers=headers, timeout=5)
    except Exception:
        pass


def _restart_service(name: str) -> bool:
    # Placeholder: in this project we don't manage processes; emit event only
    try:
        _emit_event("service_restart_attempt", severity="warn", service=str(name))
        return True
    except Exception:
        return False


def _clear_internal_cache() -> bool:
    try:
        if _cache is not None:
            if hasattr(_cache, "clear_all"):
                try:
                    _cache.clear_all()  # type: ignore[attr-defined]
                except Exception:
                    pass
            else:
                try:
                    _cache.delete_pattern("*")  # type: ignore[call-arg]
                except Exception:
                    pass
        _emit_event("cache_clear_attempt", severity="warn")
        return True
    except Exception:
        return False


def _reconnect_mongodb() -> bool:
    try:
        if DatabaseManager is not None:
            # Create a new ephemeral manager to force a new connection
            mgr = DatabaseManager()
            # Touch db attribute to initialize
            _ = getattr(mgr, "db", None)
        _emit_event("mongodb_reconnect_attempt", severity="warn")
        return True
    except Exception:
        return False


def _detect_recurring(kind_key: str, now_ts: float) -> bool:
    try:
        items = _read_incidents(limit=200)
        cutoff = now_ts - _FIFTEEN_MIN
        for rec in reversed(items):
            if rec.get("kind_key") == kind_key:
                try:
                    ts = rec.get("ts") or rec.get("timestamp")
                    t = datetime.fromisoformat(str(ts)).timestamp()
                except Exception:
                    continue
                if t >= cutoff:
                    return True
                if t < cutoff:
                    return False
        return False
    except Exception:
        return False


def _bump_adaptive_thresholds(metric: str, factor: float = 1.2) -> None:
    try:
        # Defer to alert_manager thresholds if available
        from alert_manager import get_thresholds_snapshot  # type: ignore
        from metrics import set_adaptive_observability_gauges  # type: ignore
        snap = get_thresholds_snapshot() or {}
        err_thr = float(snap.get("error_rate_percent", {}).get("threshold", 0.0) or 0.0)
        lat_thr = float(snap.get("latency_seconds", {}).get("threshold", 0.0) or 0.0)
        if metric == "error_rate_percent" and err_thr > 0.0:
            err_thr *= float(factor)
        if metric == "latency_seconds" and lat_thr > 0.0:
            lat_thr *= float(factor)
        set_adaptive_observability_gauges(
            error_rate_threshold_percent=err_thr if err_thr > 0.0 else None,
            latency_threshold_seconds=lat_thr if lat_thr > 0.0 else None,
        )
    except Exception:
        return


def handle_critical_incident(name: str, metric: str, value: float, threshold: float, details: Optional[Dict[str, Any]] = None) -> str:
    """Main entrypoint: log incident, attempt remediation, annotate Grafana, and return incident_id.

    name examples: "High Error Rate", "High Latency", "DB Connection Errors"
    metric examples: "error_rate_percent", "latency_seconds", "db_connection_errors"
    """
    try:
        now = datetime.now(timezone.utc)
        now_ts = now.timestamp()
        incident_id = str(uuid.uuid4())
        kind_key = _hash_incident_key(str(name), str(metric), details or {})
        recurring = _detect_recurring(kind_key, now_ts)

        action = "none"
        name_l = (name or "").lower()
        metric_l = (metric or "").lower()
        if "error rate" in name_l or metric_l == "error_rate_percent":
            action = "restart_service:webapp"
            _restart_service("webapp")
        elif "latency" in name_l or metric_l == "latency_seconds":
            action = "clear_cache"
            _clear_internal_cache()
        elif "db" in name_l or "mongo" in name_l or metric_l == "db_connection_errors":
            action = "reconnect_mongodb"
            _reconnect_mongodb()

        record: Dict[str, Any] = {
            "incident_id": incident_id,
            "ts": now.isoformat(),
            "severity": "critical",
            "name": str(name),
            "metric": str(metric),
            "value": float(value),
            "threshold": float(threshold),
            "response_action": action,
            "recurring_issue": bool(recurring),
            "kind_key": kind_key,
        }

        _write_incident(record)
        _emit_event("AUTO_REMEDIATION_EXECUTED", severity="error", incident_id=incident_id, name=str(name))

        try:
            _grafana_annotate(f"{name} — action={action} recurring={recurring}")
        except Exception:
            pass

        if recurring:
            # Capture pre-bump snapshot to avoid double-bump when exporting gauges
            before_err = before_lat = None
            try:
                from alert_manager import get_thresholds_snapshot  # type: ignore
                snap_before = get_thresholds_snapshot() or {}
                before_err = float(snap_before.get("error_rate_percent", {}).get("threshold", 0.0) or 0.0)
                before_lat = float(snap_before.get("latency_seconds", {}).get("threshold", 0.0) or 0.0)
            except Exception:
                before_err = before_lat = None

            # Bump internal thresholds by 1.2x
            try:
                from alert_manager import bump_threshold  # type: ignore
                bump_threshold(kind=str(metric), factor=1.2)
            except Exception:
                pass

            # Export gauges that reflect exactly one bump (no double multiplication)
            try:
                from metrics import set_adaptive_observability_gauges  # type: ignore
                if str(metric) == "error_rate_percent":
                    base = before_err if (before_err and before_err > 0.0) else float(threshold)
                    new_val = (base * 1.2) if base and base > 0.0 else None
                    set_adaptive_observability_gauges(error_rate_threshold_percent=new_val)
                elif str(metric) == "latency_seconds":
                    base = before_lat if (before_lat and before_lat > 0.0) else float(threshold)
                    new_val = (base * 1.2) if base and base > 0.0 else None
                    set_adaptive_observability_gauges(latency_threshold_seconds=new_val)
            except Exception:
                pass

        return incident_id
    except Exception:
        return ""


def get_incidents(limit: int = 50) -> List[Dict[str, Any]]:
    return _read_incidents(limit=max(1, min(500, int(limit))))
