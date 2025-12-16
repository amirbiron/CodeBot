from __future__ import annotations

import copy
import hashlib
import json
import logging
import os
import re
import threading
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlencode, urlparse

import requests
try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    yaml = None  # type: ignore

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
try:
    _AI_EXPLAIN_CACHE_TTL = float(os.getenv("OBS_AI_EXPLAIN_CACHE_TTL", "600"))
except ValueError:  # pragma: no cover - env misconfig fallback
    _AI_EXPLAIN_CACHE_TTL = 600.0

_AI_EXPLAIN_URL = os.getenv("OBS_AI_EXPLAIN_URL") or os.getenv("AI_EXPLAIN_URL") or ""
_AI_EXPLAIN_TOKEN = os.getenv("OBS_AI_EXPLAIN_TOKEN") or os.getenv("AI_EXPLAIN_TOKEN") or ""
try:
    _AI_EXPLAIN_TIMEOUT = float(os.getenv("OBS_AI_EXPLAIN_TIMEOUT", "12"))
except ValueError:  # pragma: no cover - env misconfig fallback
    _AI_EXPLAIN_TIMEOUT = 12.0

_MAX_AI_METADATA_ITEMS = 25
_MAX_AI_METADATA_CHILD_ITEMS = 5
_MAX_AI_METADATA_STRING = 512
_MAX_AI_LOG_LINES = 40
_MAX_AI_TEXT_CHARS = 4000
_MAX_MASK_INPUT = 20000

_HEX_TOKEN_RE = re.compile(r"\b[0-9a-f]{16,}\b", re.IGNORECASE)
_LONG_DIGIT_RE = re.compile(r"\b\d{8,}\b")
_SECRET_RE = re.compile(r"(?i)(token|secret|password|api[_-]?key)\s*[:=]\s*([^\s,;]+)")
_EMAIL_LOCAL_CHARS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._%+-")
_EMAIL_DOMAIN_CHARS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-")

_QUICK_FIX_PATH = Path(os.getenv("ALERT_QUICK_FIX_PATH", "config/alert_quick_fixes.json"))
_QUICK_FIX_CACHE: Dict[str, Any] = {}
_QUICK_FIX_MTIME: float = 0.0
_QUICK_FIX_ACTIONS: deque[Dict[str, Any]] = deque(maxlen=200)

_RUNBOOK_PATH = Path(os.getenv("OBSERVABILITY_RUNBOOK_PATH", "config/observability_runbooks.yml"))
_RUNBOOK_CACHE: Dict[str, Any] = {}
_RUNBOOK_ALIAS_MAP: Dict[str, str] = {}
_RUNBOOK_MTIME: float = 0.0
try:
    _RUNBOOK_STATE_TTL = float(os.getenv("OBS_RUNBOOK_STATE_TTL", "14400"))
except ValueError:  # pragma: no cover - env misconfig fallback
    _RUNBOOK_STATE_TTL = 14400.0
try:
    _RUNBOOK_EVENT_CACHE_TTL = float(os.getenv("OBS_RUNBOOK_EVENT_TTL", "900"))
except ValueError:  # pragma: no cover - env misconfig fallback
    _RUNBOOK_EVENT_CACHE_TTL = 900.0
_RUNBOOK_STATE: Dict[str, Dict[str, Any]] = {}
_RUNBOOK_EVENT_CACHE: Dict[str, Tuple[float, Dict[str, Any]]] = {}
_RUNBOOK_STATE_LOCK = threading.Lock()

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


def _cache_dt_key(dt: Optional[datetime], *, bucket_seconds: int = 60) -> Optional[str]:
    """מייצר מפתח זמן יציב לקאש.

    הרבה מהקריאות מגיעות עם end_dt="עכשיו", ולכן שימוש ב-isoformat מלא יוצר miss
    על כל בקשה ומבטל את הקאש לחלוטין. כאן אנחנו "מיישרים" את הזמן לבאקט (דקה כברירת מחדל)
    רק עבור *מפתח הקאש* — לא משנים את start_dt/end_dt שנשלחים לשכבות האחסון.
    """
    if dt is None:
        return None
    try:
        aware = _ensure_utc_aware(dt)
        # יישור דטרמיניסטי לבאקט (למשל 60 שניות)
        bucket = max(1, int(bucket_seconds))
        epoch = int(aware.timestamp())
        snapped = (epoch // bucket) * bucket
        return datetime.fromtimestamp(snapped, tz=timezone.utc).isoformat()
    except Exception:
        try:
            return dt.isoformat()
        except Exception:
            return None


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


def _slugify(value: str, fallback: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "_", (value or "").lower()).strip("_")
    return text or fallback


def _normalize_alert_type(value: Optional[str]) -> str:
    try:
        text = str(value or "").strip().lower()
    except Exception:
        return ""
    if not text:
        return ""
    # Normalize common variants so alert types match runbook aliases:
    # - "No replica set members" -> "no_replica_set_members"
    # - "SSL handshake failed"   -> "ssl_handshake_failed"
    # - "_OperationCancelled"    -> "operationcancelled"
    text = re.sub(r"[\s\-]+", "_", text)
    text = text.strip("_")
    text = re.sub(r"[^a-z0-9_\.]+", "", text)
    text = re.sub(r"_+", "_", text)
    return text


def _fallback_runbook_definition() -> Dict[str, Any]:
    """
    Fallback runbook shown when runbook YAML isn't available/parseable.

    This prevents the UI from showing "אין Runbook" in environments where the
    YAML dependency/config wasn't shipped correctly, and still gives operators
    safe, actionable next steps.
    """
    return {
        "id": "generic_incident_flow",
        "title": "פלייבוק כללי להתראות",
        "description": "Fallback בסיסי כשאין Runbook ייעודי/כשקובץ ה-Runbooks לא נטען.",
        "category": "fallback",
        "steps": [
            {
                "id": "open_replay",
                "title": "פתח Incident Replay סביב האירוע",
                "description": "בדוק אם יש דיפלוימנט/התראות נוספות סביב אותה שעה.",
                "action": {
                    "label": "⏪ Incident Replay",
                    "type": "link",
                    "href": "/admin/observability/replay?timerange=3h&focus_ts={{timestamp}}",
                    "safety": "safe",
                },
            },
            {
                "id": "run_errors",
                "title": "משוך /errors",
                "description": "פקודה מהירה שמציפה שגיאות אחרונות (fallback כשאין תמונה מלאה).",
                "action": {
                    "label": "🚨 /errors",
                    "type": "copy",
                    "payload": "/errors",
                    "safety": "safe",
                },
            },
        ],
    }


def _normalize_runbook_config(raw: Any) -> Tuple[Dict[str, Any], Dict[str, str], Optional[str], Optional[int]]:
    definitions: Dict[str, Any] = {}
    aliases: Dict[str, str] = {}
    default_key: Optional[str] = None
    version: Optional[int] = None

    if isinstance(raw, dict):
        version = raw.get("version")
        runbooks_block = raw.get("runbooks") if isinstance(raw.get("runbooks"), dict) else raw
    else:
        runbooks_block = {}

    for key, value in runbooks_block.items():
        if key in {"version", "runbooks", "default"}:
            continue
        if not isinstance(value, dict):
            continue
        slug = _slugify(str(value.get("id") or key), f"rb_{len(definitions)+1}")
        runbook = {
            "id": slug,
            "title": value.get("title") or str(key).replace("_", " ").title(),
            "description": value.get("description") or "",
            "category": value.get("category") or "",
            "steps": [],
        }
        steps = value.get("steps")
        if isinstance(steps, list):
            normalized_steps: List[Dict[str, Any]] = []
            for idx, step in enumerate(steps):
                if not isinstance(step, dict):
                    continue
                step_title = step.get("title") or f"Step {idx + 1}"
                step_id = _slugify(str(step.get("id") or step_title), f"step_{idx + 1}")
                normalized_steps.append(
                    {
                        "id": step_id,
                        "title": step_title,
                        "description": step.get("description") or "",
                        "action": copy.deepcopy(step.get("action")) if isinstance(step.get("action"), dict) else None,
                    }
                )
            runbook["steps"] = normalized_steps
        definitions[slug] = runbook

        aliases[_normalize_alert_type(key)] = slug
        for alias in value.get("aliases") or []:
            aliases[_normalize_alert_type(alias)] = slug
        if str(value.get("default")).lower() in {"1", "true", "yes"}:
            default_key = slug

    cfg_default = raw.get("default") if isinstance(raw, dict) else None
    if not default_key and isinstance(cfg_default, str):
        candidate = _normalize_alert_type(cfg_default)
        mapped = aliases.get(candidate) or candidate
        if mapped in definitions:
            default_key = mapped

    return definitions, aliases, default_key, version


def _load_runbook_config() -> Dict[str, Any]:
    global _RUNBOOK_CACHE, _RUNBOOK_ALIAS_MAP, _RUNBOOK_MTIME
    path = _RUNBOOK_PATH
    try:
        stat = path.stat()
    except FileNotFoundError:
        _RUNBOOK_CACHE = {}
        _RUNBOOK_ALIAS_MAP = {}
        _RUNBOOK_MTIME = 0.0
        return {}
    except Exception:
        return _RUNBOOK_CACHE

    if stat.st_mtime <= _RUNBOOK_MTIME and _RUNBOOK_CACHE:
        return _RUNBOOK_CACHE

    if yaml is None:  # pragma: no cover - optional dependency missing
        logger.warning("observability_runbook_yaml_missing")
        _RUNBOOK_CACHE = {}
        _RUNBOOK_ALIAS_MAP = {}
        _RUNBOOK_MTIME = stat.st_mtime
        return _RUNBOOK_CACHE

    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        logger.warning("observability_runbook_parse_failed")
        data = {}

    definitions, aliases, default_key, version = _normalize_runbook_config(data)
    _RUNBOOK_CACHE = {
        "definitions": definitions,
        "default": default_key,
        "version": version,
    }
    _RUNBOOK_ALIAS_MAP = aliases
    _RUNBOOK_MTIME = stat.st_mtime
    return _RUNBOOK_CACHE


def _resolve_runbook_key(alert_type: Optional[str], *, allow_default: bool = True) -> Optional[str]:
    config = _load_runbook_config()
    definitions = config.get("definitions") or {}
    if not definitions:
        return None
    normalized = _normalize_alert_type(alert_type)
    alias = _RUNBOOK_ALIAS_MAP.get(normalized)
    if alias and alias in definitions:
        return alias
    if normalized and normalized in definitions:
        return normalized
    if allow_default:
        default_key = config.get("default")
        if default_key and default_key in definitions:
            return default_key
    return None


def _resolve_runbook_entry(alert_type: Optional[str]) -> Optional[Dict[str, Any]]:
    slug = _resolve_runbook_key(alert_type, allow_default=True)
    if not slug:
        return None
    config = _load_runbook_config()
    definition = (config.get("definitions") or {}).get(slug)
    if not definition:
        return None
    return copy.deepcopy(definition)


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


def _expand_runbook_steps(
    runbook: Dict[str, Any],
    alert: Dict[str, Any],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    steps_payload: List[Dict[str, Any]] = []
    actions: List[Dict[str, Any]] = []
    steps = runbook.get("steps") or []
    alert_uid = alert.get("alert_uid") or _build_alert_uid(alert)
    alert["alert_uid"] = alert_uid

    for step in steps:
        if not isinstance(step, dict):
            continue
        step_id = step.get("id") or _slugify(step.get("title") or "", f"step_{len(steps_payload)+1}")
        action_cfg = step.get("action")
        expanded_action = None
        if isinstance(action_cfg, dict):
            cfg = dict(action_cfg)
            if not cfg.get("id"):
                cfg["id"] = f"{runbook.get('id', 'runbook')}-{step_id}"
            expanded_action = _expand_quick_fix_action(cfg, alert)
            if step.get("description") and not expanded_action.get("description"):
                expanded_action["description"] = step.get("description")
            actions.append(expanded_action)
        steps_payload.append(
            {
                "id": step_id,
                "title": step.get("title") or step_id,
                "description": step.get("description") or "",
                "action": expanded_action,
            }
        )
    return steps_payload, actions


def _runbook_quick_fix_actions(alert: Dict[str, Any]) -> List[Dict[str, Any]]:
    runbook = _resolve_runbook_entry(alert.get("alert_type"))
    if not runbook:
        return []
    _, actions = _expand_runbook_steps(runbook, alert)
    return actions


def get_quick_fix_actions(alert: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return applicable quick-fix actions for a given alert."""
    try:
        actions = _runbook_quick_fix_actions(alert)
        if actions:
            return actions
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
    alert_type = str(alert.get("alert_type") or "").strip().lower()
    metric = _alert_metric_from_metadata(alert)
    reason = "metadata" if metric else None
    category = None
    # Sentry issues אינם קשורים בהכרח למדדים הפנימיים (latency/error_rate וכו'),
    # ולעיתים התאמה היוריסטית לפי מילות מפתח ("errors") יוצרת גרף "ריק" ומבלבל.
    # אם בעתיד נרצה גרף עבור Sentry – נוסיף metric מפורש במטא־דאטה או מקור חיצוני.
    if not metric and alert_type == "sentry_issue":
        return None
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


def _ensure_utc_aware(dt: datetime) -> datetime:
    """
    Normalize datetimes for safe comparisons.

    We treat offset-naive datetimes as UTC (common for DB-stored timestamps).
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


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
        return _ensure_utc_aware(dt)
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
        # Metric pollution guard (fallback path): אל תערבב drills בנתונים "אמיתיים"
        try:
            if bool(metadata.get("is_drill")):
                continue
        except Exception:
            pass
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
        _cache_dt_key(start_dt, bucket_seconds=60),
        _cache_dt_key(end_dt, bucket_seconds=60),
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
        try:
            details = entry.get("details") if isinstance(entry, dict) else None
            if isinstance(details, dict) and bool(details.get("is_drill")):
                continue
        except Exception:
            pass
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
    # Ensure consistent datetime semantics across sources (DB timestamps are often naive UTC).
    start_dt = _ensure_utc_aware(start_dt) if start_dt else None
    end_dt = _ensure_utc_aware(end_dt) if end_dt else None

    cache_key = (
        _cache_dt_key(start_dt, bucket_seconds=60),
        _cache_dt_key(end_dt, bucket_seconds=60),
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
    deployments = [_ensure_utc_aware(ts) for ts in deployments]
    if not deployments and _internal_alerts is not None:
        fallback_deployments = [
            _parse_iso_dt(rec.get("ts"))
            for rec in (_internal_alerts.get_recent_alerts(limit=200) or [])  # type: ignore[attr-defined]
            if str(rec.get("name") or "").lower() == "deployment_event"
        ]
        deployments = [_ensure_utc_aware(ts) for ts in fallback_deployments if ts is not None]

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
    anomalies = [_ensure_utc_aware(ts) for ts in anomalies]
    anomaly_total = len(anomalies)
    if not anomalies and _internal_alerts is not None:
        anomaly_total = 0
        anomalies = []
        for rec in (_internal_alerts.get_recent_alerts(limit=200) or []):  # type: ignore[attr-defined]
            ts = _parse_iso_dt(rec.get("ts"))
            if ts is None:
                continue
            ts = _ensure_utc_aware(ts)
            if start_dt and ts < start_dt:
                continue
            if end_dt and ts > end_dt:
                continue
            if str(rec.get("severity") or "").lower() == "anomaly":
                anomalies.append(ts)
        anomaly_total = len(anomalies)

    def _is_in_window(ts: datetime) -> bool:
        ts = _ensure_utc_aware(ts)
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
        try:
            details = rec.get("details") if isinstance(rec, dict) else None
            if isinstance(details, dict) and bool(details.get("is_drill")):
                continue
        except Exception:
            pass
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
    # קאש יציב: align לפי גרנולריות כדי שלא נקבל miss על כל "עכשיו"
    bucket = max(60, int(granularity_seconds or 60))
    cache_key = (
        _cache_dt_key(start_dt, bucket_seconds=bucket),
        _cache_dt_key(end_dt, bucket_seconds=bucket),
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


def _mask_text(value: Any) -> str:
    original = str(value or "")
    if not original:
        return ""
    suffix = ""
    text = original
    if len(text) > _MAX_MASK_INPUT:
        text = text[:_MAX_MASK_INPUT]
        suffix = "…"

    def _replace_secret(match: re.Match[str]) -> str:
        key = match.group(1)
        return f"{key}=<redacted>"

    masked = _SECRET_RE.sub(_replace_secret, text)
    masked = _mask_email_like(masked)
    masked = _HEX_TOKEN_RE.sub("<token>", masked)
    masked = _LONG_DIGIT_RE.sub("<id>", masked)
    return masked + suffix


def _mask_email_like(text: str) -> str:
    if "@" not in text:
        return text
    parts: List[str] = []
    idx = 0
    length = len(text)
    while idx < length:
        at_pos = text.find("@", idx)
        if at_pos == -1:
            parts.append(text[idx:])
            break
        local_start = at_pos - 1
        while local_start >= idx and text[local_start] in _EMAIL_LOCAL_CHARS:
            local_start -= 1
        local_start += 1
        domain_end = at_pos + 1
        dot_seen = False
        while domain_end < length and text[domain_end] in _EMAIL_DOMAIN_CHARS:
            if text[domain_end] == ".":
                dot_seen = True
            domain_end += 1
        has_local = local_start < at_pos
        has_domain = domain_end > at_pos + 1
        if has_local and has_domain and dot_seen:
            parts.append(text[idx:local_start])
            parts.append("[email]")
            idx = domain_end
        else:
            parts.append(text[idx:domain_end])
            idx = domain_end
    return "".join(parts)


def _truncate_text(text: str, limit: int) -> str:
    if limit <= 0 or len(text) <= limit:
        return text
    head = max(32, limit // 2)
    tail = max(32, limit - head - 1)
    if tail <= 0:
        return text[:limit]
    return f"{text[:head]}…{text[-tail:]}"


def _mask_value(value: Any, depth: int = 0) -> Any:
    if depth > 3:
        return "…"
    if isinstance(value, dict):
        sanitized: Dict[str, Any] = {}
        for idx, (key, val) in enumerate(value.items()):
            if idx >= _MAX_AI_METADATA_CHILD_ITEMS:
                break
            sanitized[str(key)] = _mask_value(val, depth + 1)
        return sanitized
    if isinstance(value, list):
        out: List[Any] = []
        for item in value[:_MAX_AI_METADATA_CHILD_ITEMS]:
            out.append(_mask_value(item, depth + 1))
        return out
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    truncated = _truncate_text(_mask_text(value), _MAX_AI_METADATA_STRING if depth else _MAX_AI_TEXT_CHARS)
    return truncated.strip()


def _sanitize_metadata(metadata: Any) -> Dict[str, Any]:
    if not isinstance(metadata, dict):
        return {}
    sanitized: Dict[str, Any] = {}
    for idx, (key, value) in enumerate(metadata.items()):
        if idx >= _MAX_AI_METADATA_ITEMS:
            break
        sanitized[str(key)] = _mask_value(value)
    return sanitized


def _flatten_log_value(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (int, float)):
        return [str(value)]
    if isinstance(value, list):
        lines: List[str] = []
        for item in value:
            lines.extend(_flatten_log_value(item))
        return lines
    if isinstance(value, dict):
        lines: List[str] = []
        for key, val in list(value.items())[:_MAX_AI_METADATA_CHILD_ITEMS]:
            if isinstance(val, (dict, list)):
                lines.append(f"{key}: {json.dumps(val, ensure_ascii=False)[:160]}")
            else:
                lines.append(f"{key}: {val}")
        return lines
    return [str(value)]


def _collect_log_lines(metadata: Any) -> List[str]:
    if not isinstance(metadata, dict):
        return []
    lines: List[str] = []
    candidate_keys = (
        "logs",
        "recent_logs",
        "log_excerpt",
        "log_lines",
        "messages",
        "errors",
        "events",
        "samples",
    )
    for key in candidate_keys:
        value = metadata.get(key)
        if not value:
            continue
        lines.extend(_flatten_log_value(value))
    return lines


def _slice_log_lines(lines: List[str]) -> List[str]:
    if not lines:
        return []
    sanitized: List[str] = []
    for line in lines:
        clean = _mask_text(line).strip()
        if not clean:
            continue
        sanitized.append(_truncate_text(clean, 320))
    if len(sanitized) <= _MAX_AI_LOG_LINES:
        return sanitized
    remaining = max(1, _MAX_AI_LOG_LINES - 1)
    head = remaining // 2
    tail = remaining - head
    return sanitized[:head] + ["…"] + sanitized[-tail:]


def _summarize_quick_fixes(alert: Dict[str, Any]) -> List[Dict[str, Any]]:
    fixes_summary: List[Dict[str, Any]] = []
    quick_fixes = alert.get("quick_fixes")
    if not isinstance(quick_fixes, list):
        return fixes_summary
    for fix in quick_fixes[:3]:
        if not isinstance(fix, dict):
            continue
        fixes_summary.append(
            {
                "label": _truncate_text(_mask_text(fix.get("label") or "פעולה"), 160),
                "type": fix.get("type"),
                "safety": fix.get("safety"),
            }
        )
    return fixes_summary


def _summarize_graph_meta(graph_meta: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(graph_meta, dict):
        return None
    summary = {
        "metric": graph_meta.get("metric"),
        "label": graph_meta.get("label"),
        "unit": graph_meta.get("unit"),
        "default_range": graph_meta.get("default_range"),
        "default_minutes": graph_meta.get("default_minutes"),
    }
    if not summary["metric"] and not summary["label"]:
        return None
    return summary


def _build_ai_context(alert: Dict[str, Any]) -> Dict[str, Any]:
    metadata = alert.get("metadata") if isinstance(alert.get("metadata"), dict) else {}
    sanitized_metadata = _sanitize_metadata(metadata)
    log_lines = _collect_log_lines(metadata)
    log_excerpt = "\n".join(_slice_log_lines(log_lines))
    alert_uid = alert.get("alert_uid")
    auto_actions = _collect_story_actions(alert_uid or "")
    safe_actions: List[Dict[str, Any]] = []
    for action in auto_actions[:4]:
        safe_actions.append(
            {
                "label": _truncate_text(_mask_text(action.get("label")), 160),
                "summary": _truncate_text(_mask_text(action.get("summary")), 200),
                "timestamp": action.get("timestamp"),
            }
        )
    context = {
        "alert_uid": alert_uid,
        "alert_name": alert.get("name") or alert.get("alert_type") or "Alert",
        "severity": alert.get("severity"),
        "summary": alert.get("summary"),
        "timestamp": alert.get("timestamp"),
        "endpoint": alert.get("endpoint") or sanitized_metadata.get("endpoint"),
        "metadata": sanitized_metadata,
        "log_excerpt": log_excerpt,
        "auto_actions": safe_actions,
        "quick_fixes": _summarize_quick_fixes(alert),
        "graph": _summarize_graph_meta(alert.get("graph")),
    }
    return context


def _ensure_list_of_strings(value: Any) -> List[str]:
    if isinstance(value, str):
        value = value.strip()
        return [value] if value else []
    if isinstance(value, (int, float)):
        return [str(value)]
    if isinstance(value, list):
        out: List[str] = []
        for item in value:
            text = str(item).strip()
            if text:
                out.append(text)
        return out
    return []


def _fallback_root_cause(alert: Dict[str, Any], context: Dict[str, Any]) -> str:
    severity = str(alert.get("severity") or "").upper() or "INFO"
    name = context.get("alert_name") or "התראה"
    summary = context.get("summary") or alert.get("summary") or ""
    endpoint = context.get("endpoint")
    parts = [f"התראה ברמת {severity} בשם {name}"]
    if endpoint:
        parts.append(f"בנקודת הקצה {endpoint}")
    if summary:
        parts.append(f"— {summary}")
    return " ".join(part for part in parts if part).strip()


def _fallback_actions(alert: Dict[str, Any], context: Dict[str, Any]) -> List[str]:
    actions: List[str] = []
    endpoint = context.get("endpoint")
    severity = str(alert.get("severity") or "").lower()
    if endpoint:
        actions.append(f"בדוק לוגים ומדדי עומס עבור {endpoint} סביב זמן ההתראה.")
    if severity == "critical":
        actions.append("אם התרחש דיפלוימנט סמוך, שקול ביצוע rollback או ביטול הפיצ׳ר האחרון.")
    if context.get("auto_actions"):
        for action in context["auto_actions"][:2]:
            label = action.get("label") or action.get("summary")
            if label:
                actions.append(f"בחן את תוצאת פעולת ה-ChatOps: {label}.")
    if context.get("quick_fixes"):
        actions.append("הרץ Quick Fix רלוונטי רק לאחר אימות הנתונים והערכת הסיכון.")
    if not actions:
        actions.append("נתח את נתוני המטה והגרפים כדי לאמת האם מדובר באירוע אמיתי או רעש בלבד.")
    if len(actions) < 2:
        actions.append("עדכן את צוות ה-SRE בממצאים והוסף סיכום ל-Incident Story בעת הצורך.")
    return actions[:4]


def _fallback_signals(context: Dict[str, Any]) -> List[str]:
    signals: List[str] = []
    severity = context.get("severity")
    if severity:
        signals.append(f"חומרה: {severity}")
    metadata = context.get("metadata") or {}
    for key in ("endpoint", "error_code", "host", "deployment_id"):
        value = metadata.get(key)
        if value:
            signals.append(f"{key}: {value}")
    graph = context.get("graph")
    if graph:
        label = graph.get("label") or graph.get("metric")
        default_range = graph.get("default_range") or "1h"
        if label:
            signals.append(f"גרף זמין: {label} ({default_range})")
    log_excerpt = context.get("log_excerpt")
    if log_excerpt:
        first_line = log_excerpt.splitlines()[0]
        if first_line:
            signals.append(f"מדגמי לוגים: {first_line}")
    deduped: List[str] = []
    seen: set[str] = set()
    for sig in signals:
        text = str(sig).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        deduped.append(text)
    if not deduped:
        deduped.append("לא זוהו אותות חריגים נוספים מעבר לנתונים שסופקו.")
    return deduped[:4]


def _normalize_ai_payload(
    raw_payload: Dict[str, Any],
    alert: Dict[str, Any],
    context: Dict[str, Any],
    *,
    provider: str,
) -> Dict[str, Any]:
    generated_at = datetime.now(timezone.utc)
    root = raw_payload.get("root_cause") or raw_payload.get("rootCause") or ""
    actions = raw_payload.get("actions") or raw_payload.get("recommendations") or []
    signals = raw_payload.get("signals") or raw_payload.get("notable_signals") or []
    root_text = _truncate_text(_mask_text(root), _MAX_AI_TEXT_CHARS).strip()
    if not root_text:
        root_text = _fallback_root_cause(alert, context)
    actions_list = _ensure_list_of_strings(actions) or _fallback_actions(alert, context)
    signals_list = _ensure_list_of_strings(signals) or _fallback_signals(context)
    explanation = {
        "alert_uid": context.get("alert_uid"),
        "alert_name": context.get("alert_name"),
        "severity": context.get("severity"),
        "root_cause": root_text,
        "actions": [_truncate_text(_mask_text(item), 400) for item in actions_list],
        "signals": [_truncate_text(_mask_text(item), 300) for item in signals_list],
        "provider": provider,
        "generated_at": generated_at.isoformat(),
        "cached": False,
    }
    ttl_seconds = int(_AI_EXPLAIN_CACHE_TTL) if _AI_EXPLAIN_CACHE_TTL > 0 else 0
    if ttl_seconds:
        explanation["cache_expires_at"] = (generated_at + timedelta(seconds=ttl_seconds)).isoformat()
    return explanation


def _heuristic_ai_payload(alert: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    fallback = {
        "root_cause": _fallback_root_cause(alert, context),
        "actions": _fallback_actions(alert, context),
        "signals": _fallback_signals(context),
    }
    return _normalize_ai_payload(fallback, alert, context, provider="heuristic")


def _call_ai_provider(context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Invoke the externally configured AI endpoint.

    Expected contract (so whoever מגדיר את השירות יודע מה להחזיר):

    Request:
        POST ${OBS_AI_EXPLAIN_URL}
        Authorization: Bearer ${OBS_AI_EXPLAIN_TOKEN}  (רשות בלבד, אם הוגדר)
        Content-Type: application/json

        {
            "context": { ... }  # כל נתוני ההתראה אחרי Masking (ראה _build_ai_context)
            "expected_sections": ["root_cause", "actions", "signals"]
        }

    Response (דוגמה):
        {
            "root_cause": "ה־error_rate קפץ אחרי דיפלוימנט 12:05",
            "actions": [
                "בצע rollback ל־service@1.4.2",
                "בדוק את לוגי auth-service על request_id=abc"
            ],
            "signals": [
                "error_rate 12% מול ממוצע 1%",
                "deployment_id deploy-2025-12-07-12-00"
            ],
            "provider": "gpt-4o-mini",
            "generated_at": "2025-12-07T09:32:11Z",
            "cached": false
        }

    כל שדה אופציונלי למעט שלושת המקטעים: root_cause, actions, signals.
    """
    if not _AI_EXPLAIN_URL:
        return None
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "CodeBot/ObservabilityDashboard",
    }
    if _AI_EXPLAIN_TOKEN:
        headers["Authorization"] = f"Bearer {_AI_EXPLAIN_TOKEN}"
    payload = {
        "context": context,
        "expected_sections": ["root_cause", "actions", "signals"],
    }
    try:
        response = requests.post(
            _AI_EXPLAIN_URL,
            json=payload,
            headers=headers,
            timeout=_AI_EXPLAIN_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
        if isinstance(data, dict):
            return data
    except Exception as exc:  # pragma: no cover - network issues
        logger.warning("observability_ai_request_failed", exc_info=True, extra={"error": str(exc)})
    return None


def explain_alert_with_ai(alert_snapshot: Dict[str, Any], *, force_refresh: bool = False) -> Dict[str, Any]:
    if not isinstance(alert_snapshot, dict):
        raise ValueError("invalid_alert_snapshot")
    alert = dict(alert_snapshot)
    alert_uid = alert.get("alert_uid") or _build_alert_uid(alert)
    if not alert_uid:
        raise ValueError("missing_alert_uid")
    alert["alert_uid"] = alert_uid

    if not force_refresh and _AI_EXPLAIN_CACHE_TTL > 0:
        cached = _cache_get("ai_explain", alert_uid, _AI_EXPLAIN_CACHE_TTL)
        if cached:
            payload = copy.deepcopy(cached)
            payload["cached"] = True
            return payload

    context = _build_ai_context(alert)
    raw_response = _call_ai_provider(context)
    if raw_response:
        explanation = _normalize_ai_payload(raw_response, alert, context, provider="ai_service")
    else:
        explanation = _heuristic_ai_payload(alert, context)

    if _AI_EXPLAIN_CACHE_TTL > 0:
        cached_copy = copy.deepcopy(explanation)
        cached_copy["cached"] = False
        _cache_set("ai_explain", alert_uid, cached_copy)

    explanation["cached"] = False
    return explanation


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


def _seed_replay_event_cache(events: List[Dict[str, Any]]) -> None:
    if not events:
        return
    now = time.time()
    with _CACHE_LOCK:
        for event in events:
            event_id = str(event.get("id") or "")
            if not event_id:
                continue
            metadata = copy.deepcopy(event.get("metadata") or {})
            _RUNBOOK_EVENT_CACHE[event_id] = (
                now,
                {
                    "id": event_id,
                    "alert_uid": event_id,
                    "type": event.get("type"),
                    "title": event.get("title"),
                    "summary": event.get("summary"),
                    "timestamp": event.get("timestamp"),
                    "severity": event.get("severity"),
                    "alert_type": metadata.get("alert_type") or event.get("type"),
                    "metadata": metadata,
                    "link": event.get("link"),
                },
            )


def _lookup_replay_event(event_id: str) -> Optional[Dict[str, Any]]:
    key = str(event_id or "").strip()
    if not key:
        return None
    now = time.time()
    with _CACHE_LOCK:
        entry = _RUNBOOK_EVENT_CACHE.get(key)
        if not entry:
            return None
        ts, data = entry
        if (now - ts) > _RUNBOOK_EVENT_CACHE_TTL:
            _RUNBOOK_EVENT_CACHE.pop(key, None)
            return None
        return copy.deepcopy(data)


def _get_runbook_state(alert_uid: str) -> Dict[str, Any]:
    uid = str(alert_uid or "").strip()
    default_state = {"completed": set(), "updated_at": None, "user_hash": None, "ts": 0.0}
    if not uid:
        return default_state
    now = time.time()
    with _RUNBOOK_STATE_LOCK:
        entry = _RUNBOOK_STATE.get(uid)
        if entry and (now - entry.get("ts", 0.0)) > _RUNBOOK_STATE_TTL:
            _RUNBOOK_STATE.pop(uid, None)
            entry = None
        if not entry:
            return default_state
        completed = set(entry.get("completed") or set())
        return {
            "completed": completed,
            "updated_at": entry.get("updated_at"),
            "user_hash": entry.get("user_hash"),
            "ts": entry.get("ts", now),
        }


def _set_runbook_step_state(
    alert_uid: str,
    step_id: str,
    completed: bool,
    user_id: Optional[int],
) -> Dict[str, Any]:
    uid = str(alert_uid or "").strip()
    if not uid:
        raise ValueError("missing_alert_uid")
    step = str(step_id or "").strip()
    if not step:
        raise ValueError("missing_step_id")
    now = time.time()
    with _RUNBOOK_STATE_LOCK:
        state = _RUNBOOK_STATE.get(uid)
        if state and (now - state.get("ts", 0.0)) > _RUNBOOK_STATE_TTL:
            state = None
            _RUNBOOK_STATE.pop(uid, None)
        completed_steps: set[str] = set(state.get("completed") or set()) if state else set()
        if completed:
            completed_steps.add(step)
        else:
            completed_steps.discard(step)
        entry = {
            "completed": completed_steps,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "user_hash": _hash_identifier(user_id),
            "ts": time.time(),
        }
        _RUNBOOK_STATE[uid] = entry
        return {
            "completed": set(entry["completed"]),
            "updated_at": entry["updated_at"],
            "user_hash": entry["user_hash"],
            "ts": entry["ts"],
        }


def _build_runbook_snapshot(
    alert_snapshot: Dict[str, Any],
    *,
    runbook: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    definition = copy.deepcopy(runbook) if runbook else _resolve_runbook_entry(alert_snapshot.get("alert_type"))
    if not definition:
        # If the runbook config isn't available (e.g. YAML missing), don't fail the UI.
        definition = _fallback_runbook_definition()
    steps, actions = _expand_runbook_steps(definition, alert_snapshot)
    state = _get_runbook_state(alert_snapshot.get("alert_uid") or _build_alert_uid(alert_snapshot))
    completed_ids = set(state.get("completed") or set())
    completed_count = 0
    for step in steps:
        step_id = step.get("id")
        is_completed = bool(step_id and step_id in completed_ids)
        step["completed"] = is_completed
        if step.get("action"):
            step["action"] = copy.deepcopy(step["action"])
        if is_completed:
            completed_count += 1
    total_steps = len(steps)
    progress = {
        "completed": completed_count,
        "total": total_steps,
        "percent": (completed_count / total_steps * 100.0) if total_steps else 0.0,
    }
    status = {
        "completed_steps": sorted(completed_ids),
        "updated_at": state.get("updated_at"),
        "updated_by": state.get("user_hash"),
    }
    return {
        "runbook": {
            "id": definition.get("id"),
            "title": definition.get("title"),
            "description": definition.get("description") or "",
            "steps": steps,
            "progress": progress,
        },
        "actions": actions,
        "status": status,
    }


def _build_event_context(
    event_id: str,
    fallback_metadata: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    context = _lookup_replay_event(event_id)
    if context:
        return context
    if fallback_metadata is None:
        return None
    normalized_type = _normalize_alert_type(
        fallback_metadata.get("alert_type") or fallback_metadata.get("type")
    )
    if not normalized_type:
        raise ValueError("missing_alert_type")
    metadata = copy.deepcopy(fallback_metadata.get("metadata") or {})
    metadata.setdefault("alert_type", normalized_type)
    endpoint_hint = fallback_metadata.get("endpoint")
    if endpoint_hint and "endpoint" not in metadata:
        metadata["endpoint"] = endpoint_hint
    source_hint = fallback_metadata.get("source")
    if source_hint and "source" not in metadata:
        metadata["source"] = source_hint
    return {
        "id": str(event_id),
        "alert_uid": str(event_id),
        "type": fallback_metadata.get("type") or "alert",
        "title": fallback_metadata.get("title") or fallback_metadata.get("summary") or "Alert",
        "summary": fallback_metadata.get("summary") or "",
        "timestamp": fallback_metadata.get("timestamp"),
        "severity": fallback_metadata.get("severity") or "info",
        "alert_type": normalized_type,
        "metadata": metadata,
        "link": fallback_metadata.get("link"),
    }


def fetch_runbook_for_event(
    *,
    event_id: str,
    fallback_metadata: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    key = str(event_id or "").strip()
    if not key:
        raise ValueError("missing_event_id")
    context = _build_event_context(key, fallback_metadata)
    if context is None:
        return None
    alert_snapshot = {
        "alert_uid": context.get("alert_uid"),
        "name": context.get("title"),
        "summary": context.get("summary"),
        "severity": context.get("severity"),
        "timestamp": context.get("timestamp"),
        "alert_type": context.get("alert_type"),
        "metadata": context.get("metadata") or {},
    }
    snapshot = _build_runbook_snapshot(alert_snapshot)
    payload = {
        "event": context,
        "runbook": None,
        "actions": [],
        "status": {
            "completed_steps": [],
            "updated_at": None,
            "updated_by": None,
        },
    }
    if snapshot:
        payload["runbook"] = snapshot["runbook"]
        payload["actions"] = snapshot["actions"]
        payload["status"] = snapshot["status"]
    return payload


def update_runbook_step_status(
    *,
    event_id: str,
    step_id: str,
    completed: bool,
    user_id: Optional[int],
    fallback_metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    key = str(event_id or "").strip()
    if not key:
        raise ValueError("missing_event_id")
    step = str(step_id or "").strip()
    if not step:
        raise ValueError("missing_step_id")
    context = _build_event_context(key, fallback_metadata)
    if context is None:
        raise ValueError("unknown_event")
    alert_snapshot = {
        "alert_uid": context.get("alert_uid"),
        "name": context.get("title"),
        "summary": context.get("summary"),
        "severity": context.get("severity"),
        "timestamp": context.get("timestamp"),
        "alert_type": context.get("alert_type"),
        "metadata": context.get("metadata") or {},
    }
    runbook = _resolve_runbook_entry(alert_snapshot.get("alert_type"))
    if not runbook:
        raise ValueError("runbook_missing")
    valid_step_ids = {step_def.get("id") for step_def in runbook.get("steps") or []}
    if step not in valid_step_ids:
        raise ValueError("invalid_step")
    _set_runbook_step_state(alert_snapshot.get("alert_uid"), step, completed, user_id)
    snapshot = _build_runbook_snapshot(alert_snapshot, runbook=runbook)
    if not snapshot:
        raise ValueError("runbook_missing")
    return {
        "event": context,
        "runbook": snapshot["runbook"],
        "actions": snapshot["actions"],
        "status": snapshot["status"],
    }


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
        metadata = {
            "endpoint": alert.get("endpoint"),
            "alert_type": alert.get("alert_type"),
            "source": alert.get("source"),
            "has_runbook": bool(_resolve_runbook_key(alert.get("alert_type"), allow_default=False)),
        }
        events.append(
            {
                "id": uid,
                "timestamp": ts,
                "type": event_type,
                "severity": alert.get("severity"),
                "title": alert.get("name") or "Alert",
                "summary": alert.get("summary") or "",
                "link": _build_focus_link(ts, anchor="history"),
                "metadata": metadata,
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
    _seed_replay_event_cache(events)
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


def build_coverage_report(
    *,
    start_dt: Optional[datetime],
    end_dt: Optional[datetime],
    min_count: int = 1,
) -> Dict[str, Any]:
    """Build a coverage report between active alert_types and config (runbooks/quick fixes).

    Definitions:
    - Missing runbook: active alert_type that doesn't match a specific runbook key/alias
      (default runbook does NOT count as coverage).
    - Missing quick fix: active alert_type that HAS a specific runbook but has no per-alert actions
      (no actions in runbook steps AND no by_alert_type actions in alert_quick_fixes.json).
    - Orphan runbook: runbook key + aliases that don't match any active alert_type in the window.
      (default runbook is excluded from the orphan list).
    - Orphan quick fix: by_alert_type entries in alert_quick_fixes.json that don't match any
      active alert_type in the window.
    """
    now = datetime.now(timezone.utc)
    generated_at = now.isoformat()

    # 1) Catalog alert types (source of truth, all-time)
    catalog_rows: List[Dict[str, Any]] = []
    try:
        catalog_rows = alerts_storage.fetch_alert_type_catalog(
            min_total_count=min_count,
            limit=50_000,
        )
    except Exception:
        catalog_rows = []

    # Best-effort fallback when catalog is unavailable: fall back to in-memory alerts in the requested window.
    # Note: this fallback is NOT persistent, but avoids returning an empty report in minimal setups.
    if not catalog_rows:
        catalog_rows = _fallback_aggregate_alert_types(start_dt=start_dt, end_dt=end_dt, min_count=min_count)

    catalog_types: set[str] = set()
    for row in catalog_rows:
        try:
            key = _normalize_alert_type(row.get("alert_type"))
            if key:
                catalog_types.add(key)
        except Exception:
            continue

    # 2) Load configs
    runbook_cfg = _load_runbook_config() or {}
    runbook_definitions = runbook_cfg.get("definitions") or {}
    default_runbook_key = runbook_cfg.get("default")

    quick_cfg = _load_quick_fix_config() or {}
    quick_by_type = quick_cfg.get("by_alert_type") if isinstance(quick_cfg.get("by_alert_type"), dict) else {}
    if not isinstance(quick_by_type, dict):
        quick_by_type = {}

    # 3) Missing runbooks / quick fixes (catalog-based)
    missing_runbooks: List[Dict[str, Any]] = []
    missing_quick_fixes: List[Dict[str, Any]] = []

    for row in catalog_rows:
        alert_type = _normalize_alert_type(row.get("alert_type"))
        if not alert_type:
            continue

        count = int(row.get("count") or 0)
        last_seen_dt = row.get("last_seen_dt")
        last_seen_ts = last_seen_dt.isoformat() if isinstance(last_seen_dt, datetime) else None
        sample_title = str(row.get("sample_title") or "").strip() or str(row.get("sample_name") or "").strip()

        # Runbook coverage: default does not count
        runbook_key = _resolve_runbook_key(alert_type, allow_default=False)
        if runbook_key and default_runbook_key and runbook_key == default_runbook_key:
            runbook_key = None

        if not runbook_key:
            missing_runbooks.append(
                {
                    "alert_type": alert_type,
                    "count": count,
                    "last_seen_ts": last_seen_ts,
                    "sample_title": sample_title,
                }
            )
            continue

        # Quick-fix coverage (per-alert only)
        has_quick_fix = False

        try:
            rb = runbook_definitions.get(runbook_key) if isinstance(runbook_definitions, dict) else None
            steps = (rb or {}).get("steps") if isinstance(rb, dict) else None
            if isinstance(steps, list):
                for step in steps:
                    if not isinstance(step, dict):
                        continue
                    action = step.get("action")
                    if isinstance(action, dict) and action:
                        has_quick_fix = True
                        break
        except Exception:
            pass

        if not has_quick_fix:
            try:
                by_type_actions = quick_by_type.get(alert_type)
                if isinstance(by_type_actions, list) and len(by_type_actions) > 0:
                    has_quick_fix = True
            except Exception:
                pass

        if not has_quick_fix:
            missing_quick_fixes.append(
                {
                    "alert_type": alert_type,
                    "count": count,
                    "last_seen_ts": last_seen_ts,
                    "sample_title": sample_title,
                }
            )

    missing_runbooks.sort(key=lambda r: (-int(r.get("count") or 0), str(r.get("alert_type") or "")))
    missing_quick_fixes.sort(key=lambda r: (-int(r.get("count") or 0), str(r.get("alert_type") or "")))

    # 4) Orphans
    orphan_runbooks = _find_orphan_runbooks(
        active_types=catalog_types,
        default_runbook_key=default_runbook_key,
    )
    orphan_quick_fixes: List[Dict[str, Any]] = []
    try:
        for key in sorted({str(k).strip().lower() for k in quick_by_type.keys() if k}):
            if key and key not in catalog_types:
                orphan_quick_fixes.append({"alert_type": key})
    except Exception:
        orphan_quick_fixes = []

    return {
        "missing_runbooks": missing_runbooks,
        "missing_quick_fixes": missing_quick_fixes,
        "orphan_runbooks": orphan_runbooks,
        "orphan_quick_fixes": orphan_quick_fixes,
        "meta": {
            # Keep window for context/links, but the report itself is catalog-based by default.
            "window_start": start_dt.isoformat() if start_dt else None,
            "window_end": end_dt.isoformat() if end_dt else None,
            "generated_at": generated_at,
            "mode": "catalog",
            "catalog_total": len(catalog_rows),
        },
    }


def _fallback_aggregate_alert_types(
    *,
    start_dt: Optional[datetime],
    end_dt: Optional[datetime],
    min_count: int,
) -> List[Dict[str, Any]]:
    if _internal_alerts is None:
        return []
    try:
        raw = _internal_alerts.get_recent_alerts(limit=600)  # type: ignore[attr-defined]
    except Exception:
        return []
    if not isinstance(raw, list):
        return []

    counts: Dict[str, int] = {}
    last_seen: Dict[str, datetime] = {}
    sample_title: Dict[str, str] = {}

    for rec in raw:
        if not isinstance(rec, dict):
            continue
        ts_dt = _parse_iso_dt(rec.get("ts") or rec.get("timestamp"))
        if ts_dt is None:
            continue
        if not _is_within_window(ts_dt, start_dt, end_dt):
            continue
        details = rec.get("details") if isinstance(rec.get("details"), dict) else rec.get("metadata")
        if isinstance(details, dict) and bool(details.get("is_drill")):
            continue
        a_type = _normalize_alert_type(details.get("alert_type") if isinstance(details, dict) else rec.get("alert_type"))
        if not a_type:
            a_type = _normalize_alert_type(rec.get("name"))
        if not a_type:
            continue
        counts[a_type] = counts.get(a_type, 0) + 1
        if a_type not in last_seen or ts_dt > last_seen[a_type]:
            last_seen[a_type] = ts_dt
            sample_title[a_type] = str(rec.get("summary") or rec.get("title") or rec.get("name") or "").strip()

    out: List[Dict[str, Any]] = []
    for a_type, cnt in counts.items():
        if cnt < max(1, int(min_count or 1)):
            continue
        out.append(
            {
                "alert_type": a_type,
                "count": cnt,
                "last_seen_dt": last_seen.get(a_type),
                "sample_title": sample_title.get(a_type, ""),
                "sample_name": a_type,
            }
        )
    out.sort(key=lambda r: (-int(r.get("count") or 0), str(r.get("alert_type") or "")))
    return out


def _find_orphan_runbooks(
    *,
    active_types: set[str],
    default_runbook_key: Optional[str],
) -> List[Dict[str, Any]]:
    if yaml is None:  # pragma: no cover - optional dependency missing
        return []
    path = _RUNBOOK_PATH
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return []
    if not isinstance(raw, dict):
        return []
    runbooks_block = raw.get("runbooks") if isinstance(raw.get("runbooks"), dict) else raw
    if not isinstance(runbooks_block, dict):
        return []

    cfg_default = str(raw.get("default") or "").strip().lower()
    out: List[Dict[str, Any]] = []
    for key, value in runbooks_block.items():
        if key in {"version", "runbooks", "default"}:
            continue
        if not isinstance(value, dict):
            continue
        runbook_key = str(key or "").strip().lower()
        if not runbook_key:
            continue
        is_default = False
        try:
            if cfg_default and cfg_default == runbook_key:
                is_default = True
        except Exception:
            pass
        try:
            if str(value.get("default")).lower() in {"1", "true", "yes"}:
                is_default = True
        except Exception:
            pass
        if default_runbook_key and runbook_key == str(default_runbook_key).lower():
            is_default = True
        if is_default:
            continue

        aliases_raw = value.get("aliases") or []
        aliases: List[str] = []
        if isinstance(aliases_raw, list):
            for item in aliases_raw:
                if not isinstance(item, str):
                    continue
                alias = item.strip().lower()
                if alias:
                    aliases.append(alias)
        aliases = sorted(set(aliases))

        matches_active = runbook_key in active_types or any(a in active_types for a in aliases)
        if not matches_active:
            out.append({"runbook_key": runbook_key, "aliases": aliases})

    out.sort(key=lambda r: str(r.get("runbook_key") or ""))
    return out


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
    return render_story_markdown_inline(story)


def render_story_markdown_inline(story: Dict[str, Any]) -> str:
    """
    מייצר טקסט Markdown עבור סיפור אירוע קיים או טיוטה זמנית.

    הפונקציה אחראית רק להרכבת התוכן, ללא שליפת הנתונים מהמסד – ולכן ניתן
    לעשות בה שימוש גם עבור סיפורים שטרם נשמרו.
    """
    if not isinstance(story, dict):
        raise ValueError("invalid_story_payload")
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
