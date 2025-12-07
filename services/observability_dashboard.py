from __future__ import annotations

import hashlib
import json
import logging
import os
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

from monitoring import alerts_storage, metrics_storage, incident_story_storage  # type: ignore
from services.observability_http import SecurityError, fetch_graph_securely

try:  # Best-effort fallback for slow endpoint summaries
    from metrics import get_top_slow_endpoints  # type: ignore
except Exception:  # pragma: no cover
    def get_top_slow_endpoints(limit: int = 5, window_seconds: Optional[int] = None):  # type: ignore
        return []


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

_HTTP_FETCH_TIMEOUT = 10

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

_ALERT_GRAPH_SOURCES_PATH = Path(os.getenv("ALERT_GRAPH_SOURCES_PATH", "config/alert_graph_sources.json"))
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


def _http_get_json(
    url_template: str,
    *,
    timeout: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
    allowed_hosts: Optional[List[str]] = None,
    allow_redirects: bool = False,
    **url_params,
) -> Any:
    """
    Securely fetch JSON payloads for Visual Context graphs or external metrics.

    Uses fetch_graph_securely to protect against SSRF/DNS rebinding, enforces an
    optional host allowlist, and decodes the response as UTF-8 JSON.
    """

    fetch_timeout = timeout or _HTTP_FETCH_TIMEOUT
    try:
        url = url_template.format(**url_params)
    except KeyError as exc:
        missing = exc.args[0]
        raise ValueError(f"Missing template parameter: {missing}") from exc

    parsed = urlparse(url)
    scheme = (parsed.scheme or "").lower()
    host = (parsed.hostname or "").lower()
    if scheme not in {"http", "https"}:
        raise SecurityError("visual_context_invalid_scheme")

    if allowed_hosts is not None:
        normalized_hosts = {str(h).strip().lower() for h in allowed_hosts if h}
        if not normalized_hosts:
            raise SecurityError("visual_context_empty_allowlist")
        if host not in normalized_hosts:
            raise SecurityError(f"visual_context_disallowed_host:{host}")

    try:
        raw_bytes = fetch_graph_securely(
            url,
            timeout=fetch_timeout,
            allow_redirects=allow_redirects,
            headers=headers,
        )
    except SecurityError as exc:
        raise SecurityError(f"visual_context_fetch_blocked: {exc}") from exc
    except Exception as exc:  # pragma: no cover - unexpected transport issues
        raise RuntimeError(f"visual_context_fetch_failed: {exc}") from exc

    try:
        text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("Invalid UTF-8 payload from visual context endpoint") from exc

    try:
        return json.loads(text or "{}")
    except json.JSONDecodeError as exc:
        raise ValueError("Invalid JSON payload from visual context endpoint") from exc


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
        expanded["id"] = _hash_identifier(f"{expanded.get('label')}-{expanded.get('type')}-{alert_type}-{severity}")
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
    default_range = (definition or {}).get("default_range") or _TIMEFRAME_DEFAULTS.get(category or "", "2h")
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
        ts_dt = None
        if isinstance(ts, datetime):
            if ts.tzinfo is None:
                ts_dt = ts.replace(tzinfo=timezone.utc)
            else:
                try:
                    ts_dt = ts.astimezone(timezone.utc)
                except Exception:
                    ts_dt = ts
        else:
            ts_dt = _parse_iso_dt(str(ts)) if ts else None
        ts_value = ts_dt.isoformat() if ts_dt else (ts if isinstance(ts, str) else None)
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
                "timestamp": ts_value,
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

    alert_uids = [alert.get("alert_uid") for alert in alerts if alert.get("alert_uid")]
    if alert_uids:
        story_map = incident_story_storage.get_stories_by_alert_uids(alert_uids)
        for alert in alerts:
            uid = alert.get("alert_uid")
            if not uid:
                continue
            story = story_map.get(uid)
            if not story:
                continue
            alert["story"] = {
                "story_id": story.get("story_id"),
                "updated_at": story.get("updated_at"),
                "summary": (story.get("what_we_saw") or {}).get("description"),
            }

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
        for rec in (_internal_alerts.get_recent_alerts(limit=200) or []):  # type: ignore[attr-defined]
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
        "anomalies_not_related_to_deployment_percent": round(
            _percent(anomalies_outside, anomaly_total), 1
        )
        if anomaly_total
        else 0.0,
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
        logger.warning("external_metric_missing_allowlist", extra={"metric": safe_metric, "url": url})
        return []
    if host not in allowed_hosts:
        logger.warning("external_metric_blocked_host", extra={"metric": safe_metric, "host": host})
        return []
    try:
        payload = _http_get_json(
            url,
            headers=headers,
            timeout=timeout,
            allowed_hosts=allowed_hosts,
        )
    except Exception as exc:
        logger.warning("external_metric_fetch_failed", extra={"metric": safe_metric, "url": url, "error": str(exc)})
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


def _minutes_from_label(label: Optional[str]) -> Optional[int]:
    if not label:
        return None
    text = str(label).strip().lower()
    if not text:
        return None
    if text.endswith("m"):
        try:
            return max(5, int(text[:-1]))
        except Exception:
            return None
    if text.endswith("h"):
        try:
            return max(5, int(text[:-1]) * 60)
        except Exception:
            return None
    if text.endswith("d"):
        try:
            return max(5, int(text[:-1]) * 1440)
        except Exception:
            return None
    try:
        return max(5, int(text))
    except Exception:
        return None


def _pick_granularity_seconds_from_minutes(total_minutes: int) -> int:
    if total_minutes <= 30:
        return 60
    if total_minutes <= 120:
        return 300
    if total_minutes <= 360:
        return 900
    if total_minutes <= 720:
        return 1800
    if total_minutes <= 1440:
        return 3600
    if total_minutes <= 4320:
        return 10800
    return 21600


def _window_around_timestamp(ts: datetime, *, minutes: int) -> Tuple[datetime, datetime]:
    minutes = max(10, minutes)
    half_delta = timedelta(minutes=minutes / 2.0)
    start_dt = ts - half_delta
    end_dt = ts + half_delta
    return start_dt, end_dt


def _collect_story_actions(alert_uid: str) -> List[Dict[str, Any]]:
    actions: List[Dict[str, Any]] = []
    if not alert_uid:
        return actions
    for action in _iter_quick_fix_actions():
        if str(action.get("alert_uid") or "") != alert_uid:
            continue
        actions.append(
            {
                "label": action.get("action_label") or action.get("summary") or "Quick Fix",
                "summary": action.get("summary") or "",
                "timestamp": action.get("timestamp"),
                "alert_type": action.get("alert_type"),
            }
        )
    return actions


def _build_story_description(alert: Dict[str, Any]) -> str:
    parts: List[str] = []
    name = alert.get("name") or alert.get("alert_type") or "Alert"
    severity = str(alert.get("severity") or "").upper()
    summary = alert.get("summary") or ""
    if severity:
        parts.append(f"[{severity}]")
    parts.append(str(name))
    if summary:
        parts.append(f"— {summary}")
    metadata = alert.get("metadata") if isinstance(alert.get("metadata"), dict) else {}
    endpoint = metadata.get("endpoint") or alert.get("endpoint")
    if endpoint:
        parts.append(f"(endpoint: {endpoint})")
    return " ".join(part for part in parts if part)


def _build_graph_snapshot(
    graph_meta: Optional[Dict[str, Any]],
    *,
    start_dt: Optional[datetime],
    end_dt: Optional[datetime],
) -> Optional[Dict[str, Any]]:
    if not graph_meta:
        return None
    metric = graph_meta.get("metric")
    if not metric:
        return None
    label = graph_meta.get("label") or metric
    unit = graph_meta.get("unit")
    total_minutes = 60
    if start_dt and end_dt:
        total_minutes = max(5, int((end_dt - start_dt).total_seconds() / 60.0))
    granularity_seconds = _pick_granularity_seconds_from_minutes(total_minutes)
    try:
        payload = fetch_timeseries(
            start_dt=start_dt,
            end_dt=end_dt,
            granularity_seconds=granularity_seconds,
            metric=metric,
        )
    except Exception:
        payload = {}
    series = payload.get("data") if isinstance(payload, dict) else []
    if not isinstance(series, list):
        series = []
    trimmed = series[:250]
    return {
        "metric": metric,
        "label": label,
        "unit": unit,
        "series": trimmed,
        "granularity_seconds": granularity_seconds,
        "range_minutes": total_minutes,
        "meta": {
            "default_range": graph_meta.get("default_range"),
            "category": graph_meta.get("category"),
        },
    }


def _logs_from_actions(actions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    logs: List[Dict[str, Any]] = []
    for action in actions:
        logs.append(
            {
                "source": "chatops",
                "timestamp": action.get("timestamp"),
                "content": action.get("summary") or action.get("label"),
            }
        )
    return logs


def _is_within_window(ts: datetime, start_dt: Optional[datetime], end_dt: Optional[datetime]) -> bool:
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
    story_count = 0

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

    stories = incident_story_storage.list_stories(
        start_dt=start_dt,
        end_dt=end_dt,
        limit=limit // 2,
    )
    for story in stories:
        ts = (story.get("time_window") or {}).get("start") or story.get("alert_timestamp")
        ts_dt = _parse_iso_dt(ts)
        if ts_dt is None or not _is_within_window(ts_dt, start_dt, end_dt):
            continue
        story_count += 1
        events.append(
            {
                "id": story.get("story_id"),
                "timestamp": ts,
                "type": "story",
                "severity": "info",
                "title": story.get("alert_name") or "Incident Story",
                "summary": (story.get("what_we_saw") or {}).get("description") or "",
                "link": f"/admin/observability?{urlencode({'story_id': story.get('story_id'), 'focus_ts': ts})}",
                "metadata": {
                    "alert_uid": story.get("alert_uid"),
                    "story_id": story.get("story_id"),
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
            "stories": story_count,
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


def _normalize_iso_timestamp(value: Optional[str]) -> Optional[str]:
    dt = _parse_iso_dt(value)
    if dt is None:
        return None
    return dt.isoformat()


def _format_window_label(start_dt: Optional[datetime], end_dt: Optional[datetime]) -> str:
    if not start_dt or not end_dt:
        return ""
    start_txt = start_dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%MZ")
    end_txt = end_dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%MZ")
    return f"{start_txt} → {end_txt}"


def _invalidate_alert_cache() -> None:
    with _CACHE_LOCK:
        if "alerts" in _CACHE:
            _CACHE.pop("alerts", None)


def build_story_template(
    alert_snapshot: Dict[str, Any],
    *,
    timerange_label: Optional[str] = None,
) -> Dict[str, Any]:
    if not isinstance(alert_snapshot, dict):
        raise ValueError("invalid_alert")
    alert = dict(alert_snapshot)
    alert_uid = alert.get("alert_uid") or _build_alert_uid(alert)
    alert["alert_uid"] = alert_uid
    alert_ts = _parse_iso_dt(alert.get("timestamp")) or datetime.now(timezone.utc)
    minutes = (
        _minutes_from_label(timerange_label)
        or _minutes_from_label((alert.get("graph") or {}).get("default_range"))
        or int((alert.get("graph") or {}).get("default_minutes") or 60)
    )
    start_dt, end_dt = _window_around_timestamp(alert_ts, minutes=minutes or 60)
    graph_snapshot = _build_graph_snapshot(alert.get("graph"), start_dt=start_dt, end_dt=end_dt)
    auto_actions = _collect_story_actions(alert_uid)
    logs = _logs_from_actions(auto_actions)
    template = {
        "alert_uid": alert_uid,
        "alert_name": alert.get("name") or alert.get("alert_type") or "Alert",
        "alert_timestamp": alert_ts.isoformat(),
        "summary": alert.get("summary"),
        "severity": alert.get("severity"),
        "metadata": alert.get("metadata") or {},
        "time_window": {
            "start": start_dt.isoformat(),
            "end": end_dt.isoformat(),
            "label": _format_window_label(start_dt, end_dt),
        },
        "what_we_saw": {
            "description": _build_story_description(alert),
            "graph_snapshot": graph_snapshot,
        },
        "what_we_did": {
            "auto_actions": auto_actions,
            "manual_notes": "",
        },
        "logs": logs,
        "insights": "",
    }
    return template


def save_incident_story(story_payload: Dict[str, Any], *, user_id: Optional[int]) -> Dict[str, Any]:
    if not isinstance(story_payload, dict):
        raise ValueError("invalid_story")
    alert_uid = str(story_payload.get("alert_uid") or "").strip()
    if not alert_uid:
        raise ValueError("missing_alert_uid")
    time_window = story_payload.get("time_window") or {}
    start_iso = _normalize_iso_timestamp(time_window.get("start"))
    end_iso = _normalize_iso_timestamp(time_window.get("end"))
    if not start_iso or not end_iso:
        raise ValueError("missing_time_window")
    start_dt = _parse_iso_dt(start_iso)
    end_dt = _parse_iso_dt(end_iso)
    what_we_saw = story_payload.get("what_we_saw") or {}
    description = str(what_we_saw.get("description") or "").strip()
    if not description:
        raise ValueError("missing_description")
    graph_snapshot = what_we_saw.get("graph_snapshot")
    what_we_did = story_payload.get("what_we_did") or {}
    auto_actions = what_we_did.get("auto_actions") or []
    if not isinstance(auto_actions, list):
        auto_actions = []
    manual_notes = str(what_we_did.get("manual_notes") or "").strip()
    logs = story_payload.get("logs") or []
    if not isinstance(logs, list):
        logs = []
    insights = str(story_payload.get("insights") or "").strip()
    alert_name = story_payload.get("alert_name") or story_payload.get("title") or "Alert"
    doc = {
        "story_id": story_payload.get("story_id"),
        "alert_uid": alert_uid,
        "alert_name": alert_name,
        "alert_timestamp": story_payload.get("alert_timestamp") or start_iso,
        "time_window": {
            "start": start_iso,
            "end": end_iso,
            "label": time_window.get("label") or _format_window_label(start_dt, end_dt),
        },
        "what_we_saw": {
            "description": description,
            "graph_snapshot": graph_snapshot,
        },
        "what_we_did": {
            "auto_actions": auto_actions,
            "manual_notes": manual_notes,
        },
        "logs": logs,
        "insights": insights,
        "metadata": story_payload.get("metadata") or {},
        "summary": story_payload.get("summary") or "",
        "severity": story_payload.get("severity"),
        "author_hash": _hash_identifier(user_id),
    }
    stored = incident_story_storage.save_story(doc)
    _invalidate_alert_cache()
    return stored


def fetch_story(story_id: str) -> Optional[Dict[str, Any]]:
    if not story_id:
        return None
    return incident_story_storage.get_story(story_id)


def export_story_markdown(story_id: str) -> Optional[str]:
    story = fetch_story(story_id)
    if not story:
        return None
    return _render_story_markdown(story)


def _render_story_markdown(story: Dict[str, Any]) -> str:
    lines: List[str] = []
    title = story.get("alert_name") or story.get("alert_uid") or "Incident Story"
    lines.append(f"# Incident Story – {title}")
    lines.append("")
    lines.append(f"- Alert UID: `{story.get('alert_uid')}`")
    lines.append(f"- Time Window: {((story.get('time_window') or {}).get('label')) or ''}")
    lines.append(f"- Severity: {story.get('severity') or 'n/a'}")
    lines.append(f"- Summary: {story.get('summary') or ''}")
    lines.append("")
    lines.append("## 👀 מה ראינו")
    lines.append(story.get("what_we_saw", {}).get("description") or "")
    graph_snapshot = (story.get("what_we_saw") or {}).get("graph_snapshot") or {}
    series = graph_snapshot.get("series") or []
    if series:
        lines.append("")
        lines.append("**Graph Snapshot:**")
        sample = series[:10]
        lines.append("")
        lines.append("| Timestamp | Value |")
        lines.append("| --- | --- |")
        for point in sample:
            lines.append(f"| {point.get('timestamp')} | {point.get('value') or point.get('avg_duration') or point.get('count')} |")
        if len(series) > len(sample):
            lines.append(f"| … | ({len(series) - len(sample)} more points) |")
    lines.append("")
    lines.append("## 🛠️ מה עשינו")
    auto_actions = (story.get("what_we_did") or {}).get("auto_actions") or []
    manual_notes = (story.get("what_we_did") or {}).get("manual_notes")
    if auto_actions:
        for action in auto_actions:
            label = action.get("label") or "Action"
            ts = action.get("timestamp") or ""
            lines.append(f"- {label} ({ts})")
    if manual_notes:
        lines.append("")
        lines.append(manual_notes)
    lines.append("")
    logs = story.get("logs") or []
    if logs:
        lines.append("## 💻 לוגים / פקודות")
        for log in logs:
            source = log.get("source") or "log"
            content = log.get("content") or ""
            lines.append(f"- **{source}:** {content}")
        lines.append("")
    insights = story.get("insights")
    if insights:
        lines.append("## 💡 תובנות")
        lines.append(insights)
    return "\n".join(lines).strip() + "\n"
