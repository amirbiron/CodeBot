from __future__ import annotations

import hashlib
import ipaddress
import json
import logging
import os
import socket
import threading
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlencode, urlparse

try:
    import internal_alerts as _internal_alerts  # type: ignore
except Exception:  # pragma: no cover
    _internal_alerts = None  # type: ignore

from monitoring import alerts_storage, metrics_storage  # type: ignore

try:  # Best-effort fallback for slow endpoint summaries
    from metrics import get_top_slow_endpoints  # type: ignore
except Exception:  # pragma: no cover

    def get_top_slow_endpoints(limit: int = 5, window_seconds: Optional[int] = None):  # type: ignore
        return []


def is_public_ip(ip_addr: str) -> bool:
    """
    Check if the given IP address is public (not private/loopback/link-local).

    Returns True if the IP is public and safe to contact.
    Returns False if the IP is in a private range and should be blocked.
    """
    try:
        ip = ipaddress.ip_address(ip_addr)
    except ValueError:
        # Invalid IP address
        return False

    # Check if IP is in any private/restricted range
    # This includes:
    # - Loopback: 127.0.0.0/8, ::1/128
    # - Private: 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, fc00::/7
    # - Link-local: 169.254.0.0/16, fe80::/10
    # - Multicast and other reserved ranges
    if ip.is_loopback:
        return False
    if ip.is_private:
        return False
    if ip.is_link_local:
        return False
    if ip.is_multicast:
        return False
    if ip.is_reserved:
        return False
    if ip.is_unspecified:
        return False

    return True


_CACHE: Dict[str, Dict[Any, Tuple[float, Any]]] = {}
_CACHE_LOCK = threading.Lock()
_ALERTS_CACHE_TTL = 120.0
_AGG_CACHE_TTL = 150.0
_TS_CACHE_TTL = 150.0

_QUICK_FIX_PATH = Path(os.getenv("ALERT_QUICK_FIX_PATH", "config/alert_quick_fixes.json"))
_QUICK_FIX_CACHE: Dict[str, Any] = {}
_QUICK_FIX_MTIME: float = 0.0
_QUICK_FIX_ACTIONS: deque[Dict[str, Any]] = deque(maxlen=200)

logger = logging.getLogger(__name__)

_RANGE_TO_MINUTES = {
    "15m": 15,
    "30m": 30,
    "1h": 60,
    "2h": 120,
    "3h": 180,
    "4h": 240,
    "6h": 360,
    "24h": 1440,
    "48h": 2880,
    "7d": 10080,
}

_TIMEFRAME_DEFAULTS = {
    "spike": "30m",
    "degradation": "2h",
    "trend": "48h",
    "pattern": "7d",
}

_METRIC_DEFINITIONS: Dict[str, Dict[str, Any]] = {
    "error_rate_percent": {
        "label": "שיעור שגיאות (%)",
        "unit": "%",
        "source": "request_error_rate",
        "category": "degradation",
        "default_range": "2h",
    },
    "latency_seconds": {
        "label": "זמן תגובה (ש׳׳)",
        "unit": "sec",
        "source": "request_latency",
        "category": "spike",
        "default_range": "1h",
    },
    "memory_usage_percent": {
        "label": "ניצול זיכרון (%)",
        "unit": "%",
        "source": "predictive",
        "category": "trend",
        "default_range": "6h",
    },
    "cpu_usage_percent": {
        "label": "ניצול CPU (%)",
        "unit": "%",
        "source": "predictive",
        "category": "spike",
        "default_range": "30m",
    },
    "disk_usage_percent": {
        "label": "ניצול דיסק (%)",
        "unit": "%",
        "source": "predictive",
        "category": "trend",
        "default_range": "48h",
    },
    "requests_per_minute": {
        "label": "בקשות לדקה",
        "unit": "rpm",
        "source": "request_volume",
        "category": "pattern",
        "default_range": "3h",
    },
}

_METRIC_ALIASES = {
    "error_rate": "error_rate_percent",
    "error_rate_percent": "error_rate_percent",
    "errors": "error_rate_percent",
    "latency": "latency_seconds",
    "latency_seconds": "latency_seconds",
    "response_time": "latency_seconds",
    "memory": "memory_usage_percent",
    "memory_percent": "memory_usage_percent",
    "memory_usage": "memory_usage_percent",
    "cpu": "cpu_usage_percent",
    "cpu_percent": "cpu_usage_percent",
    "disk": "disk_usage_percent",
    "disk_usage": "disk_usage_percent",
    "disk_percent": "disk_usage_percent",
    "traffic": "requests_per_minute",
    "qps": "requests_per_minute",
    "rpm": "requests_per_minute",
}

_ALERT_GRAPH_RULES: List[Dict[str, Any]] = [
    {
        "metric": "cpu_usage_percent",
        "category": "spike",
        "keywords": ("cpu", "burst", "timeout", "spike"),
        "type_matches": ("cpu_spike", "api_timeout"),
    },
    {
        "metric": "latency_seconds",
        "category": "degradation",
        "keywords": ("latency", "slow response", "p95", "timeout"),
        "type_matches": ("slow_response", "api_latency"),
    },
    {
        "metric": "error_rate_percent",
        "category": "degradation",
        "keywords": ("error rate", "errors", "5xx"),
        "type_matches": ("high_error_rate", "error_spike"),
    },
    {
        "metric": "memory_usage_percent",
        "category": "trend",
        "keywords": ("memory", "leak", "heap"),
        "type_matches": ("memory_leak",),
    },
    {
        "metric": "disk_usage_percent",
        "category": "trend",
        "keywords": ("disk", "storage", "capacity"),
        "type_matches": ("disk_full", "disk_usage"),
    },
    {
        "metric": "requests_per_minute",
        "category": "pattern",
        "keywords": ("traffic", "surge", "throughput", "qps"),
        "type_matches": ("traffic_surge",),
    },
]

_ALERT_GRAPH_SOURCES_PATH = Path(
    os.getenv("ALERT_GRAPH_SOURCES_PATH", "config/alert_graph_sources.json")
)
_GRAPH_SOURCES_CACHE: Dict[str, Any] = {}
_GRAPH_SOURCES_MTIME: float = 0.0
_EXTERNAL_ALLOWED_METRICS: set[str] = set()


def _cache_get(kind: str, key: Any, ttl: float) -> Any:
    now = time.time()
    with _CACHE_LOCK:
        bucket = _CACHE.get(kind, {})
        entry = bucket.get(key)
        if not entry:
            return None
        ts, value = entry
        if (now - ts) < ttl:
            return value
    return None


def _cache_set(kind: str, key: Any, value: Any) -> None:
    with _CACHE_LOCK:
        bucket = _CACHE.setdefault(kind, {})
        bucket[key] = (time.time(), value)


def _hash_identifier(raw: Any) -> str:
    try:
        text = str(raw or "").strip()
    except Exception:
        text = ""
    if not text:
        return ""
    try:
        digest = hashlib.sha256(text.encode("utf-8", "ignore")).hexdigest()
    except Exception:
        return ""
    return digest[:12]


def _load_quick_fix_config() -> Dict[str, Any]:
    global _QUICK_FIX_CACHE, _QUICK_FIX_MTIME
    path = _QUICK_FIX_PATH
    try:
        stat = path.stat()
    except FileNotFoundError:
        _QUICK_FIX_CACHE = {}
        _QUICK_FIX_MTIME = 0.0
        return {}
    except Exception:
        return _QUICK_FIX_CACHE

    if stat.st_mtime <= _QUICK_FIX_MTIME and _QUICK_FIX_CACHE:
        return _QUICK_FIX_CACHE

    try:
        text = path.read_text(encoding="utf-8")
        data = json.loads(text or "{}")
        if isinstance(data, dict):
            _QUICK_FIX_CACHE = data
        else:
            _QUICK_FIX_CACHE = {}
    except Exception:
        _QUICK_FIX_CACHE = {}
    _QUICK_FIX_MTIME = stat.st_mtime
    return _QUICK_FIX_CACHE


def _expand_quick_fix_action(cfg: Dict[str, Any], alert: Dict[str, Any]) -> Dict[str, Any]:
    timestamp = str(alert.get("timestamp") or "")
    alert_type = str(alert.get("alert_type") or "")
    severity = str(alert.get("severity") or "")
    replacements = {
        "{{timestamp}}": timestamp,
        "{{alert_type}}": alert_type,
        "{{severity}}": severity,
    }
    expanded: Dict[str, Any] = {}
    for key, value in cfg.items():
        if isinstance(value, str):
            new_val = value
            for token, replacement in replacements.items():
                new_val = new_val.replace(token, replacement)
            expanded[key] = new_val
        else:
            expanded[key] = value
    if not expanded.get("id"):
        expanded["id"] = _hash_identifier(
            f"{expanded.get('label')}-{expanded.get('type')}-{alert_type}-{severity}"
        )
    return expanded


def _collect_quick_fix_actions(alert: Dict[str, Any]) -> List[Dict[str, Any]]:
    config = _load_quick_fix_config() or {}
    actions: List[Dict[str, Any]] = []
    seen: set[str] = set()

    def _extend(entries: Any) -> None:
        if not entries:
            return
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            expanded = _expand_quick_fix_action(entry, alert)
            act_id = str(expanded.get("id") or "")
            if act_id in seen:
                continue
            seen.add(act_id)
            actions.append(expanded)

    alert_type = str(alert.get("alert_type") or "").lower()
    by_type = config.get("by_alert_type") or {}
    if alert_type and alert_type in by_type:
        _extend(by_type.get(alert_type))

    severity = str(alert.get("severity") or "").lower()
    by_severity = config.get("by_severity") or {}
    if severity and severity in by_severity:
        _extend(by_severity.get(severity))

    _extend(config.get("fallback"))
    return actions


def get_quick_fix_actions(alert: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return applicable quick-fix actions for a given alert."""
    try:
        return _collect_quick_fix_actions(alert)
    except Exception:
        return []


def _load_graph_sources_config() -> Dict[str, Any]:
    global _GRAPH_SOURCES_CACHE, _GRAPH_SOURCES_MTIME, _EXTERNAL_ALLOWED_METRICS
    path = _ALERT_GRAPH_SOURCES_PATH
    if not path:
        return _GRAPH_SOURCES_CACHE
    try:
        stat = path.stat()
    except FileNotFoundError:
        _GRAPH_SOURCES_CACHE = {}
        _GRAPH_SOURCES_MTIME = 0.0
        return _GRAPH_SOURCES_CACHE
    except Exception:
        return _GRAPH_SOURCES_CACHE
    if stat.st_mtime <= _GRAPH_SOURCES_MTIME and _GRAPH_SOURCES_CACHE:
        return _GRAPH_SOURCES_CACHE
    try:
        text = path.read_text(encoding="utf-8")
        data = json.loads(text or "{}")
    except Exception:
        _GRAPH_SOURCES_CACHE = {}
        _GRAPH_SOURCES_MTIME = stat.st_mtime
        return _GRAPH_SOURCES_CACHE
    sources = data.get("sources") if isinstance(data, dict) else {}
    if isinstance(sources, dict):
        normalized: Dict[str, Any] = {}
        for key, value in sources.items():
            if not isinstance(value, dict):
                continue
            norm_key = str(key).lower()
            normalized[norm_key] = value
        _GRAPH_SOURCES_CACHE = normalized
        _EXTERNAL_ALLOWED_METRICS = set(normalized.keys())
    else:
        _GRAPH_SOURCES_CACHE = {}
        _EXTERNAL_ALLOWED_METRICS = set()
    _GRAPH_SOURCES_MTIME = stat.st_mtime
    return _GRAPH_SOURCES_CACHE


def _get_external_metric_sources() -> Dict[str, Any]:
    return _load_graph_sources_config()


def _normalize_metric_name(metric: Optional[str]) -> Optional[str]:
    if not metric:
        return None
    key = str(metric).strip().lower()
    if not key:
        return None
    return _METRIC_ALIASES.get(key, key)


def _get_metric_definition(metric: Optional[str]) -> Optional[Dict[str, Any]]:
    if not metric:
        return None
    key = _normalize_metric_name(metric)
    if not key:
        return None
    base = _METRIC_DEFINITIONS.get(key)
    if base:
        definition = dict(base)
        definition["metric"] = key
        return definition
    external = _get_external_metric_sources().get(key)
    if external:
        category = str(external.get("category") or "degradation").strip().lower() or "degradation"
        default_range = external.get("default_range") or _TIMEFRAME_DEFAULTS.get(category, "2h")
        allowed_hosts = external.get("allowed_hosts")
        if isinstance(allowed_hosts, str):
            allowed_hosts = [allowed_hosts]
        if isinstance(allowed_hosts, list):
            normalized_hosts = []
            for host in allowed_hosts:
                if not host:
                    continue
                normalized_hosts.append(str(host).strip().lower())
            allowed_hosts = normalized_hosts
        else:
            allowed_hosts = None
        definition = {
            "metric": key,
            "label": external.get("label") or key,
            "unit": external.get("unit") or "",
            "category": category,
            "default_range": default_range,
            "source": "external",
            "external_config": external,
            "allowed_hosts": allowed_hosts,
        }
        return definition
    return None


def _minutes_for_range(label: Optional[str]) -> int:
    if not label:
        return _RANGE_TO_MINUTES.get("2h", 120)
    return _RANGE_TO_MINUTES.get(str(label), _RANGE_TO_MINUTES.get("2h", 120))


def _alert_metric_from_metadata(alert: Dict[str, Any]) -> Optional[str]:
    metadata = alert.get("metadata")
    if not isinstance(metadata, dict):
        return None
    for key in ("metric", "metric_name", "graph_metric", "graph_metric_name"):
        value = metadata.get(key)
        normalized = _normalize_metric_name(value)
        if normalized:
            return normalized
    return None


def _match_graph_rule(alert: Dict[str, Any]) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    name = str(alert.get("name") or "").lower()
    alert_type = str(alert.get("alert_type") or "").lower()
    summary = str(alert.get("summary") or "").lower()
    haystack = " ".join(filter(None, [name, alert_type, summary]))
    for rule in _ALERT_GRAPH_RULES:
        metric = rule.get("metric")
        if not metric:
            continue
        keywords = rule.get("keywords") or ()
        type_matches = tuple(str(t).lower() for t in (rule.get("type_matches") or ()))
        matched = False
        if alert_type and type_matches:
            if alert_type in type_matches or any(alert_type.startswith(t) for t in type_matches):
                matched = True
        if not matched and keywords:
            for kw in keywords:
                if kw and str(kw).lower() in haystack:
                    matched = True
                    break
        if matched:
            return _normalize_metric_name(metric), rule.get("category"), f"rule:{metric}"
    return None, None, None


def _describe_alert_graph(alert: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    metric = _alert_metric_from_metadata(alert)
    reason = "metadata" if metric else None
    category = None
    if not metric:
        metric, category, reason = _match_graph_rule(alert)
    if not metric:
        return None
    definition = _get_metric_definition(metric)
    category = (definition or {}).get("category") or category
    default_range = (definition or {}).get("default_range") or _TIMEFRAME_DEFAULTS.get(
        category or "", "2h"
    )
    minutes = _minutes_for_range(default_range)
    return {
        "metric": (definition or {}).get("metric") or metric,
        "label": (definition or {}).get("label") or metric or "metric",
        "unit": (definition or {}).get("unit") or "",
        "category": category,
        "default_range": default_range,
        "default_minutes": minutes,
        "source": (definition or {}).get("source"),
        "available": bool(definition),
        "reason": reason or ("rule" if metric else "unknown"),
    }


def _build_alert_uid(alert: Dict[str, Any]) -> str:
    parts = [
        str(alert.get("timestamp") or ""),
        str(alert.get("name") or ""),
        str(alert.get("summary") or ""),
        str(alert.get("alert_type") or ""),
    ]
    raw = "|".join(parts)
    return _hash_identifier(raw or "|".join(parts))


def _parse_iso_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _matches_filters(
    rec: Dict[str, Any],
    *,
    start_dt: Optional[datetime],
    end_dt: Optional[datetime],
    severity: Optional[str],
    alert_type: Optional[str],
    endpoint: Optional[str],
    search: Optional[str],
) -> bool:
    ts = _parse_iso_dt(rec.get("timestamp"))
    if start_dt and (ts is None or ts < start_dt):
        return False
    if end_dt and (ts is None or ts > end_dt):
        return False
    if severity:
        if str(rec.get("severity") or "").lower() != severity.lower():
            return False
    if alert_type:
        if str(rec.get("alert_type") or "").lower() != alert_type.lower():
            return False
    if endpoint:
        if str(rec.get("endpoint") or "") != endpoint:
            return False
    if search:
        needle = search.lower()
        haystack = " ".join(
            str(part or "").lower()
            for part in [
                rec.get("name"),
                rec.get("summary"),
                rec.get("metadata"),
            ]
        )
        if needle not in haystack:
            return False
    return True


def _fallback_alerts(
    *,
    start_dt: Optional[datetime],
    end_dt: Optional[datetime],
    severity: Optional[str],
    alert_type: Optional[str],
    endpoint: Optional[str],
    search: Optional[str],
    page: int,
    per_page: int,
) -> Tuple[List[Dict[str, Any]], int]:
    if _internal_alerts is None:
        return [], 0
    try:
        raw = _internal_alerts.get_recent_alerts(limit=400)  # type: ignore[attr-defined]
    except Exception:
        raw = []
    normalized: List[Dict[str, Any]] = []
    for item in reversed(raw):
        ts = item.get("ts")
        severity_value = str(item.get("severity") or "").lower()
        metadata = item.get("details") if isinstance(item.get("details"), dict) else {}
        endpoint_hint = (
            metadata.get("endpoint")
            or metadata.get("path")
            or metadata.get("route")
            or metadata.get("url")
        )
        alert_type_value = str(metadata.get("alert_type") or item.get("name") or "").lower() or None
        normalized.append(
            {
                "timestamp": ts,
                "name": item.get("name"),
                "severity": severity_value,
                "summary": item.get("summary"),
                "metadata": metadata or {},
                "duration_seconds": metadata.get("duration_seconds"),
                "alert_type": alert_type_value,
                "endpoint": endpoint_hint,
                "source": "buffer",
                "silenced": False,
            }
        )
    filtered = [
        rec
        for rec in sorted(normalized, key=lambda r: r.get("timestamp") or "", reverse=True)
        if _matches_filters(
            rec,
            start_dt=start_dt,
            end_dt=end_dt,
            severity=severity,
            alert_type=alert_type,
            endpoint=endpoint,
            search=search,
        )
    ]
    total = len(filtered)
    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    return filtered[start_idx:end_idx], total


def fetch_alerts(
    *,
    start_dt: Optional[datetime],
    end_dt: Optional[datetime],
    severity: Optional[str],
    alert_type: Optional[str],
    endpoint: Optional[str],
    search: Optional[str],
    page: int,
    per_page: int,
) -> Dict[str, Any]:
    cache_key = (
        start_dt.isoformat() if start_dt else None,
        end_dt.isoformat() if end_dt else None,
        (severity or "").lower(),
        (alert_type or "").lower(),
        endpoint or "",
        search or "",
        page,
        per_page,
    )
    cached = _cache_get("alerts", cache_key, _ALERTS_CACHE_TTL)
    if cached is not None:
        return cached

    alerts, total = alerts_storage.fetch_alerts(
        start_dt=start_dt,
        end_dt=end_dt,
        severity=severity,
        alert_type=alert_type,
        endpoint=endpoint,
        search=search,
        page=page,
        per_page=per_page,
    )
    if not alerts:
        alerts, total = _fallback_alerts(
            start_dt=start_dt,
            end_dt=end_dt,
            severity=severity,
            alert_type=alert_type,
            endpoint=endpoint,
            search=search,
            page=page,
            per_page=per_page,
        )

    for alert in alerts:
        try:
            uid = _build_alert_uid(alert)
        except Exception:
            uid = _hash_identifier(alert)
        alert["alert_uid"] = uid
        alert["quick_fixes"] = get_quick_fix_actions(alert)
        graph = _describe_alert_graph(alert)
        if graph:
            alert["graph"] = graph

    payload = {
        "alerts": alerts,
        "total": total,
        "page": page,
        "per_page": per_page,
    }
    _cache_set("alerts", cache_key, payload)
    return payload


def _fallback_summary() -> Dict[str, int]:
    if _internal_alerts is None:
        return {"total": 0, "critical": 0, "anomaly": 0, "deployment": 0}
    try:
        data = _internal_alerts.get_recent_alerts(limit=400)  # type: ignore[attr-defined]
    except Exception:
        data = []
    summary = {"total": 0, "critical": 0, "anomaly": 0, "deployment": 0}
    for entry in data:
        severity = str(entry.get("severity") or "").lower()
        name = str(entry.get("name") or "").lower()
        summary["total"] += 1
        if severity == "critical":
            summary["critical"] += 1
        if severity == "anomaly":
            summary["anomaly"] += 1
        if name == "deployment_event":
            summary["deployment"] += 1
    return summary


def _fallback_top_endpoints(limit: int = 5) -> List[Dict[str, Any]]:
    rows = get_top_slow_endpoints(limit=limit, window_seconds=3600)
    result: List[Dict[str, Any]] = []
    for row in rows:
        result.append(
            {
                "endpoint": row.get("endpoint") or row.get("method"),
                "method": row.get("method"),
                "count": row.get("count"),
                "avg_duration": row.get("avg_duration"),
                "max_duration": row.get("max_duration"),
            }
        )
    return result


def _build_windows(
    deployments: List[datetime],
    *,
    window_minutes: int = 30,
) -> List[Tuple[datetime, datetime]]:
    delta = timedelta(minutes=window_minutes)
    return [(ts, ts + delta) for ts in deployments]


def _percent(part: int, whole: int) -> float:
    if whole <= 0:
        return 0.0
    return (float(part) / float(whole)) * 100.0


def fetch_aggregations(
    *,
    start_dt: Optional[datetime],
    end_dt: Optional[datetime],
    slow_endpoints_limit: int = 5,
) -> Dict[str, Any]:
    cache_key = (
        start_dt.isoformat() if start_dt else None,
        end_dt.isoformat() if end_dt else None,
        slow_endpoints_limit,
    )
    cached = _cache_get("aggregations", cache_key, _AGG_CACHE_TTL)
    if cached is not None:
        return cached

    summary = alerts_storage.aggregate_alert_summary(start_dt=start_dt, end_dt=end_dt)
    if not any(summary.values()):
        summary = _fallback_summary()

    top_endpoints = metrics_storage.aggregate_top_endpoints(
        start_dt=start_dt,
        end_dt=end_dt,
        limit=slow_endpoints_limit,
    )
    if not top_endpoints:
        top_endpoints = _fallback_top_endpoints(limit=slow_endpoints_limit)

    deployments = alerts_storage.fetch_alert_timestamps(
        start_dt=start_dt,
        end_dt=end_dt,
        alert_type="deployment_event",
        limit=50,
    )
    if not deployments and _internal_alerts is not None:
        fallback_deployments = [
            _parse_iso_dt(rec.get("ts"))
            for rec in (_internal_alerts.get_recent_alerts(limit=200) or [])  # type: ignore[attr-defined]
            if str(rec.get("name") or "").lower() == "deployment_event"
        ]
        deployments = [ts for ts in fallback_deployments if ts is not None]

    windows = _build_windows(deployments)
    window_averages: List[float] = []
    for start, finish in windows:
        avg = metrics_storage.average_request_duration(start_dt=start, end_dt=finish)
        if avg is not None:
            window_averages.append(avg)
    avg_spike = sum(window_averages) / len(window_averages) if window_averages else 0.0

    anomalies = alerts_storage.fetch_alert_timestamps(
        start_dt=start_dt,
        end_dt=end_dt,
        severity="anomaly",
        limit=500,
    )
    anomaly_total = len(anomalies)
    if not anomalies and _internal_alerts is not None:
        anomaly_total = 0
        anomalies = []
        for rec in _internal_alerts.get_recent_alerts(limit=200) or []:  # type: ignore[attr-defined]
            ts = _parse_iso_dt(rec.get("ts"))
            if ts is None:
                continue
            if start_dt and ts < start_dt:
                continue
            if end_dt and ts > end_dt:
                continue
            if str(rec.get("severity") or "").lower() == "anomaly":
                anomalies.append(ts)
        anomaly_total = len(anomalies)

    def _is_in_window(ts: datetime) -> bool:
        for start, finish in windows:
            if start <= ts <= finish:
                return True
        return False

    anomalies_outside = 0
    if windows and anomalies:
        for ts in anomalies:
            if not _is_in_window(ts):
                anomalies_outside += 1
    elif anomalies:
        anomalies_outside = len(anomalies)

    correlation = {
        "avg_spike_during_deployment": round(avg_spike, 3) if avg_spike else 0.0,
        "anomalies_not_related_to_deployment_percent": (
            round(_percent(anomalies_outside, anomaly_total), 1) if anomaly_total else 0.0
        ),
    }

    payload = {
        "summary": summary,
        "top_slow_endpoints": top_endpoints,
        "deployment_correlation": correlation,
    }
    _cache_set("aggregations", cache_key, payload)
    return payload


def _fallback_alert_timeseries(
    *,
    start_dt: Optional[datetime],
    end_dt: Optional[datetime],
    granularity_seconds: int,
) -> List[Dict[str, Any]]:
    if _internal_alerts is None:
        return []
    try:
        raw = _internal_alerts.get_recent_alerts(limit=400)  # type: ignore[attr-defined]
    except Exception:
        return []
    bucket = max(60, granularity_seconds)
    counts: Dict[int, Dict[str, int]] = {}
    for rec in raw:
        ts = _parse_iso_dt(rec.get("ts"))
        if ts is None:
            continue
        if start_dt and ts < start_dt:
            continue
        if end_dt and ts > end_dt:
            continue
        bucket_key = int(ts.timestamp() // bucket) * bucket
        bucket_row = counts.setdefault(
            bucket_key,
            {"critical": 0, "anomaly": 0, "warning": 0, "info": 0, "total": 0},
        )
        severity = str(rec.get("severity") or "info").lower()
        if severity.startswith("crit"):
            severity = "critical"
        elif severity.startswith("anom"):
            severity = "anomaly"
        elif severity.startswith("warn"):
            severity = "warning"
        else:
            severity = "info"
        bucket_row[severity] += 1
        bucket_row["total"] += 1
    result: List[Dict[str, Any]] = []
    for bucket_key in sorted(counts.keys()):
        ts_iso = datetime.fromtimestamp(bucket_key, tz=timezone.utc).isoformat()
        row = dict(counts[bucket_key])
        row["timestamp"] = ts_iso
        result.append(row)
    return result


def _predictive_metric_series(
    metric: str,
    *,
    start_dt: Optional[datetime],
    end_dt: Optional[datetime],
    granularity_seconds: int,
) -> List[Dict[str, Any]]:
    start_ts = start_dt.timestamp() if start_dt else None
    end_ts = end_dt.timestamp() if end_dt else None
    try:
        from predictive_engine import get_observations  # type: ignore
    except Exception:
        return []
    try:
        rows = get_observations(metric, start_ts=start_ts, end_ts=end_ts)
    except ValueError:
        return []
    except Exception:
        logger.debug("predictive_metric_series_failed", exc_info=True)
        return []
    if not rows:
        return []
    bucket = max(60, int(granularity_seconds or 60))
    buckets: Dict[int, List[float]] = {}
    for ts, value in rows:
        if start_ts is not None and ts < start_ts:
            continue
        if end_ts is not None and ts > end_ts:
            continue
        key = int(ts // bucket) * bucket
        buckets.setdefault(key, []).append(float(value))
    data: List[Dict[str, Any]] = []
    for key in sorted(buckets.keys()):
        bucket_values = buckets[key]
        if not bucket_values:
            continue
        avg_value = sum(bucket_values) / float(len(bucket_values))
        ts_iso = datetime.fromtimestamp(key, tz=timezone.utc).isoformat()
        data.append({"timestamp": ts_iso, "value": avg_value})
    return data


def _http_get_json(
    url: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    timeout: float = 5.0,
    allowed_hosts: Optional[List[str]] = None,
) -> Any:
    response_text = None
    request_fn = None
    allowed_hosts = [str(h).strip().lower() for h in (allowed_hosts or []) if h]
    if not allowed_hosts:
        raise RuntimeError("allowed_hosts_required")
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    scheme = (parsed.scheme or "").lower()
    if scheme not in {"http", "https"} or host not in allowed_hosts:
        raise RuntimeError("http_host_not_allowed")

    # SSRF Protection: Resolve hostname to IP and verify it's not in private ranges
    try:
        # Resolve the hostname to IP addresses
        addr_info = socket.getaddrinfo(host, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
        if not addr_info:
            raise RuntimeError("hostname_resolution_failed")

        # Check all resolved IPs - all must be public
        for family, socktype, proto, canonname, sockaddr in addr_info:
            ip_addr = str(sockaddr[0])  # First element is the IP address
            if not is_public_ip(ip_addr):
                logger.warning(
                    "ssrf_blocked_private_ip", extra={"host": host, "ip": ip_addr, "url": url}
                )
                raise RuntimeError("private_ip_blocked")
    except socket.gaierror as exc:
        logger.warning(
            "hostname_resolution_failed", extra={"host": host, "url": url, "error": str(exc)}
        )
        raise RuntimeError("hostname_resolution_failed") from exc
    except RuntimeError:
        # Re-raise our own RuntimeError exceptions (private_ip_blocked, etc.)
        raise
    except Exception as exc:
        logger.warning("ip_validation_failed", extra={"host": host, "url": url, "error": str(exc)})
        raise RuntimeError("ip_validation_failed") from exc

    try:
        from http_sync import request as http_request  # type: ignore

        request_fn = http_request
    except Exception:
        request_fn = None
    if request_fn is not None:
        resp = request_fn("GET", url, headers=headers or {}, timeout=timeout)
        try:
            raise_fn = getattr(resp, "raise_for_status", None)
            if callable(raise_fn):
                raise_fn()
            else:
                status_code = getattr(resp, "status_code", None)
                if status_code is not None and int(status_code) >= 400:
                    raise RuntimeError(f"http_error_status_{status_code}")
        except Exception:
            raise
        response_text = getattr(resp, "text", None)
        if response_text is None:
            try:
                response_text = resp.content.decode("utf-8")  # type: ignore[attr-defined]
            except Exception:
                response_text = None
    else:
        try:
            import requests  # type: ignore
        except Exception as exc:  # pragma: no cover
            raise RuntimeError("http_client_unavailable") from exc
        resp = requests.get(url, headers=headers, timeout=timeout)  # type: ignore[attr-defined]
        resp.raise_for_status()
        response_text = resp.text
    return json.loads(response_text or "null")


def _fetch_external_metric_series(
    metric: str,
    definition: Dict[str, Any],
    *,
    start_dt: Optional[datetime],
    end_dt: Optional[datetime],
    granularity_seconds: int,
) -> List[Dict[str, Any]]:
    import re

    if definition.get("source") != "external":
        raise ValueError("unsupported_external_metric")
    if metric not in _EXTERNAL_ALLOWED_METRICS:
        logger.warning("external_metric_not_allowlisted", extra={"metric": metric})
        raise ValueError("invalid_metric")
    # Only allow safe metric names for template substitution
    safe_metric = metric
    if not re.fullmatch(r"[A-Za-z0-9_-]+", safe_metric):
        logger.warning("external_metric_invalid_name", extra={"metric": safe_metric})
        raise ValueError("invalid_metric_name")
    config = definition.get("external_config") or {}
    template = config.get("graph_url_template")
    if not template:
        raise ValueError("missing_graph_url_template")
    replacements = {
        "{{metric_name}}": safe_metric,
        "{{start_time}}": start_dt.isoformat() if start_dt else "",
        "{{end_time}}": end_dt.isoformat() if end_dt else "",
        "{{granularity_seconds}}": str(granularity_seconds),
        "{{start_ts_ms}}": str(int(start_dt.timestamp() * 1000)) if start_dt else "",
        "{{end_ts_ms}}": str(int(end_dt.timestamp() * 1000)) if end_dt else "",
    }
    url = template
    for token, value in replacements.items():
        url = url.replace(token, value)
    headers = config.get("headers") if isinstance(config.get("headers"), dict) else None
    timeout = float(config.get("timeout", 5.0) or 5.0)
    parsed = urlparse(url)
    scheme = (parsed.scheme or "").lower()
    host = (parsed.hostname or "").lower()
    if scheme not in {"http", "https"} or not host:
        logger.warning("external_metric_invalid_url", extra={"metric": safe_metric, "url": url})
        return []
    allowed_hosts = definition.get("allowed_hosts") or []
    if not allowed_hosts:
        logger.warning(
            "external_metric_missing_allowlist", extra={"metric": safe_metric, "url": url}
        )
        return []
    if host not in allowed_hosts:
        logger.warning("external_metric_blocked_host", extra={"metric": safe_metric, "host": host})
        return []
    try:
        payload = _http_get_json(url, headers=headers, timeout=timeout, allowed_hosts=allowed_hosts)
    except Exception as exc:
        logger.warning(
            "external_metric_fetch_failed",
            extra={"metric": safe_metric, "url": url, "error": str(exc)},
        )
        return []
    data_block = payload.get("data") if isinstance(payload, dict) else payload
    if not isinstance(data_block, list):
        return []
    rows: List[Dict[str, Any]] = []
    value_key = config.get("value_key") or "value"
    ts_key = config.get("timestamp_key") or "timestamp"
    for item in data_block:
        if not isinstance(item, dict):
            continue
        ts = item.get(ts_key)
        value = item.get(value_key)
        if ts is None or value is None:
            continue
        try:
            value_num = float(value)
        except Exception:
            logger.warning(
                "external_metric_invalid_value",
                extra={"metric": metric, "value": value, "timestamp": ts},
            )
            continue
        rows.append({"timestamp": str(ts), "value": value_num})
    return rows


def fetch_timeseries(
    *,
    start_dt: Optional[datetime],
    end_dt: Optional[datetime],
    granularity_seconds: int,
    metric: str,
) -> Dict[str, Any]:
    cache_key = (
        start_dt.isoformat() if start_dt else None,
        end_dt.isoformat() if end_dt else None,
        granularity_seconds,
        metric,
    )
    cached = _cache_get("timeseries", cache_key, _TS_CACHE_TTL)
    if cached is not None:
        return cached

    requested_metric = (metric or "alerts_count") or "alerts_count"
    metric_key = str(requested_metric).strip().lower() or "alerts_count"
    normalized_metric = _normalize_metric_name(metric_key) or metric_key
    data: List[Dict[str, Any]] = []

    if normalized_metric == "alerts_count":
        buckets = alerts_storage.aggregate_alert_timeseries(
            start_dt=start_dt,
            end_dt=end_dt,
            granularity_seconds=granularity_seconds,
        )
        if not buckets:
            buckets = _fallback_alert_timeseries(
                start_dt=start_dt,
                end_dt=end_dt,
                granularity_seconds=granularity_seconds,
            )
        for entry in buckets:
            data.append(
                {
                    "timestamp": entry.get("timestamp"),
                    "critical": entry.get("critical", 0),
                    "anomaly": entry.get("anomaly", 0),
                    "warning": entry.get("warning", 0),
                    "info": entry.get("info", 0),
                    "total": entry.get("total", 0),
                }
            )
    elif normalized_metric in {"response_time", "latency_seconds"}:
        buckets = metrics_storage.aggregate_request_timeseries(
            start_dt=start_dt,
            end_dt=end_dt,
            granularity_seconds=granularity_seconds,
        )
        for entry in buckets:
            data.append(
                {
                    "timestamp": entry.get("timestamp"),
                    "avg_duration": entry.get("avg_duration"),
                    "max_duration": entry.get("max_duration"),
                    "count": entry.get("count", 0),
                }
            )
    elif normalized_metric in {"error_rate", "error_rate_percent"}:
        buckets = metrics_storage.aggregate_request_timeseries(
            start_dt=start_dt,
            end_dt=end_dt,
            granularity_seconds=granularity_seconds,
        )
        for entry in buckets:
            count = entry.get("count", 0)
            errors = entry.get("error_count", 0)
            data.append(
                {
                    "timestamp": entry.get("timestamp"),
                    "error_rate": _percent(int(errors), int(count)),
                    "count": count,
                    "errors": errors,
                }
            )
    elif normalized_metric in {"memory_usage_percent", "cpu_usage_percent", "disk_usage_percent"}:
        data = _predictive_metric_series(
            normalized_metric,
            start_dt=start_dt,
            end_dt=end_dt,
            granularity_seconds=granularity_seconds,
        )
    elif normalized_metric == "requests_per_minute":
        buckets = metrics_storage.aggregate_request_timeseries(
            start_dt=start_dt,
            end_dt=end_dt,
            granularity_seconds=granularity_seconds,
        )
        minutes = max(1.0, float(granularity_seconds or 60) / 60.0)
        for entry in buckets:
            count_val = int(entry.get("count", 0) or 0)
            rpm = float(count_val) / minutes
            data.append(
                {
                    "timestamp": entry.get("timestamp"),
                    "requests_per_minute": rpm,
                    "count": count_val,
                }
            )
    else:
        definition = _get_metric_definition(normalized_metric)
        if definition and definition.get("source") == "external":
            data = _fetch_external_metric_series(
                normalized_metric,
                definition,
                start_dt=start_dt,
                end_dt=end_dt,
                granularity_seconds=granularity_seconds,
            )
        else:
            raise ValueError("invalid_metric")

    payload_metric = metric_key if metric else normalized_metric
    payload = {"metric": payload_metric, "data": data}
    _cache_set("timeseries", cache_key, payload)
    return payload


def _build_focus_link(timestamp: Optional[str], *, anchor: str = "history") -> str:
    base = "/admin/observability"
    if timestamp:
        query = urlencode({"focus_ts": timestamp})
        base = f"{base}?{query}"
    if anchor:
        return f"{base}#{anchor}"
    return base


def _is_within_window(
    ts: datetime, start_dt: Optional[datetime], end_dt: Optional[datetime]
) -> bool:
    if start_dt and ts < start_dt:
        return False
    if end_dt and ts > end_dt:
        return False
    return True


def record_quick_fix_action(
    *,
    action_id: str,
    action_label: str,
    alert_snapshot: Dict[str, Any],
    user_id: Optional[int],
) -> None:
    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "action_id": str(action_id or ""),
        "action_label": str(action_label or ""),
        "alert_uid": str(alert_snapshot.get("alert_uid") or _build_alert_uid(alert_snapshot)),
        "alert_type": str(alert_snapshot.get("alert_type") or ""),
        "alert_severity": str(alert_snapshot.get("severity") or ""),
        "alert_timestamp": str(alert_snapshot.get("timestamp") or ""),
        "summary": str(alert_snapshot.get("summary") or ""),
        "user_hash": _hash_identifier(user_id),
    }
    _QUICK_FIX_ACTIONS.append(event)
    try:
        from observability import emit_event  # type: ignore

        emit_event(
            "quick_fix_invoked",
            severity="info",
            action_id=event["action_id"],
            alert_type=event["alert_type"],
            alert_uid=event["alert_uid"],
            handled=True,
        )
    except Exception:
        pass


def _iter_quick_fix_actions() -> List[Dict[str, Any]]:
    return list(_QUICK_FIX_ACTIONS)


def fetch_incident_replay(
    *,
    start_dt: Optional[datetime],
    end_dt: Optional[datetime],
    limit: int = 200,
) -> Dict[str, Any]:
    try:
        per_page = max(10, min(500, int(limit or 200)))
    except Exception:
        per_page = 200

    alerts, _ = alerts_storage.fetch_alerts(
        start_dt=start_dt,
        end_dt=end_dt,
        severity=None,
        alert_type=None,
        endpoint=None,
        search=None,
        page=1,
        per_page=per_page,
    )

    events: List[Dict[str, Any]] = []
    alert_count = 0
    deployment_count = 0
    chatops_count = 0

    for alert in alerts:
        ts = alert.get("timestamp")
        ts_dt = _parse_iso_dt(ts)
        if ts and ts_dt is None:
            # Skip malformed timestamps
            continue
        if ts_dt is not None and not _is_within_window(ts_dt, start_dt, end_dt):
            continue
        event_type = "alert"
        if str(alert.get("alert_type") or "").lower() == "deployment_event":
            event_type = "deployment"
            deployment_count += 1
        else:
            alert_count += 1
        uid = alert.get("alert_uid") or _build_alert_uid(alert)
        events.append(
            {
                "id": uid,
                "timestamp": ts,
                "type": event_type,
                "severity": alert.get("severity"),
                "title": alert.get("name") or "Alert",
                "summary": alert.get("summary") or "",
                "link": _build_focus_link(ts, anchor="history"),
                "metadata": {
                    "endpoint": alert.get("endpoint"),
                    "alert_type": alert.get("alert_type"),
                    "source": alert.get("source"),
                },
            }
        )

    for action in _iter_quick_fix_actions():
        ts = action.get("timestamp")
        ts_dt = _parse_iso_dt(ts)
        if ts_dt is None or not _is_within_window(ts_dt, start_dt, end_dt):
            continue
        chatops_count += 1
        events.append(
            {
                "id": f"{action.get('action_id')}-{action.get('alert_uid')}",
                "timestamp": ts,
                "type": "chatops",
                "severity": "info",
                "title": action.get("action_label") or "Quick Fix",
                "summary": action.get("summary") or "",
                "link": _build_focus_link(action.get("alert_timestamp") or ts, anchor="history"),
                "metadata": {
                    "alert_uid": action.get("alert_uid"),
                    "alert_type": action.get("alert_type"),
                },
            }
        )

    events.sort(key=lambda e: e.get("timestamp") or "")
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window": {
            "start": start_dt.isoformat() if start_dt else None,
            "end": end_dt.isoformat() if end_dt else None,
        },
        "counts": {
            "alerts": alert_count,
            "deployments": deployment_count,
            "chatops": chatops_count,
        },
        "events": events,
    }
    return payload


def build_dashboard_snapshot(
    *,
    start_dt: Optional[datetime],
    end_dt: Optional[datetime],
    timerange_label: str,
    alerts_limit: int = 120,
) -> Dict[str, Any]:
    summary = fetch_aggregations(start_dt=start_dt, end_dt=end_dt, slow_endpoints_limit=10)
    alerts_payload = fetch_alerts(
        start_dt=start_dt,
        end_dt=end_dt,
        severity=None,
        alert_type=None,
        endpoint=None,
        search=None,
        page=1,
        per_page=max(25, min(200, alerts_limit)),
    )
    alerts_data = alerts_payload.get("alerts", [])

    alerts_timeseries = fetch_timeseries(
        start_dt=start_dt,
        end_dt=end_dt,
        granularity_seconds=3600,
        metric="alerts_count",
    )
    response_timeseries = fetch_timeseries(
        start_dt=start_dt,
        end_dt=end_dt,
        granularity_seconds=3600,
        metric="response_time",
    )
    error_rate_timeseries = fetch_timeseries(
        start_dt=start_dt,
        end_dt=end_dt,
        granularity_seconds=3600,
        metric="error_rate",
    )

    config_version = (_load_quick_fix_config() or {}).get("version")
    snapshot = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "timerange": timerange_label,
        "window": {
            "start": start_dt.isoformat() if start_dt else None,
            "end": end_dt.isoformat() if end_dt else None,
        },
        "summary": summary.get("summary"),
        "top_slow_endpoints": summary.get("top_slow_endpoints"),
        "deployment_correlation": summary.get("deployment_correlation"),
        "timeseries": {
            "alerts_count": alerts_timeseries.get("data"),
            "response_time": response_timeseries.get("data"),
            "error_rate": error_rate_timeseries.get("data"),
        },
        "alerts": alerts_data,
        "meta": {
            "alerts_total": alerts_payload.get("total"),
            "per_page": alerts_payload.get("per_page"),
            "quick_fix_config_version": config_version,
        },
    }
    return snapshot
