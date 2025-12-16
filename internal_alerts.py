"""
Internal alerts system for CodeBot (post-MVP).

- Stores recent alerts in-memory for ChatOps consumption
- Emits structured events via observability.emit_event
- Optionally forwards alerts to sinks via alert_forwarder (Slack/Telegram)
  or directly to Telegram if alert_forwarder is unavailable.

Environment variables used by the Telegram fallback:
- ALERT_TELEGRAM_BOT_TOKEN
- ALERT_TELEGRAM_CHAT_ID

This module is intentionally lightweight and fail-open. It should never raise.
"""
from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
from typing import Any, Dict, List
import os

try:
    from prometheus_client import Counter, REGISTRY
except Exception:  # pragma: no cover
    Counter = REGISTRY = None  # type: ignore

try:  # runtime optional
    from http_sync import request  # type: ignore
except Exception:  # pragma: no cover
    request = None  # type: ignore

try:  # observability event emission (optional)
    from observability import emit_event  # type: ignore
except Exception:  # pragma: no cover
    def emit_event(event: str, severity: str = "info", **fields):  # type: ignore
        return None

# Optional sink forwarder (Slack/Telegram) – used when available
try:
    from alert_forwarder import forward_alerts  # type: ignore
except Exception:  # pragma: no cover
    forward_alerts = None  # type: ignore


_MAX = int(os.getenv("INTERNAL_ALERTS_BUFFER", "200") or 200)
_ALERTS: "deque[Dict[str, Any]]" = deque(maxlen=max(10, _MAX))


def _get_prom_counter(name: str, documentation: str, labelnames: List[str]):
    if Counter is None:
        return None
    if REGISTRY is not None:
        try:
            existing = getattr(REGISTRY, "_names_to_collectors", {}).get(name)
        except Exception:
            existing = None
        if existing is not None:
            return existing
    try:
        return Counter(name, documentation, labelnames)
    except ValueError:
        if REGISTRY is not None:
            try:
                return getattr(REGISTRY, "_names_to_collectors", {}).get(name)
            except Exception:
                return None
        return None


internal_alerts_total = _get_prom_counter(
    "internal_alerts_total",
    "Total internal alerts emitted",
    ["name", "severity"],
)

_SENSITIVE_DETAIL_KEYS = {"token", "password", "secret", "authorization", "auth"}
_PROMOTED_DETAIL_KEYS = {
    "service",
    "component",
    "app",
    "application",
    "env",
    "environment",
    "namespace",
    "cluster",
    "request_id",
    "request-id",
    "x-request-id",
    "x_request_id",
    "instance",
    "pod",
    "hostname",
    "host",
}
_SENTRY_META_KEYS = {"sentry", "sentry_url", "sentry-permalink", "sentry_permalink"}


def _coerce_str(value: Any) -> str:
    try:
        return str(value)
    except Exception:
        return ""


def _first_detail(details: Dict[str, Any], keys) -> Any:
    for key in keys:
        try:
            if key in details:
                val = details.get(key)
                if val not in (None, ""):
                    return _coerce_str(val)
        except Exception:
            continue
    return None


def _details_preview(details: Dict[str, Any]) -> str | None:
    if not isinstance(details, dict):
        return None
    safe_items: List[str] = []
    def _short(val: Any, *, limit: int = 180) -> str:
        try:
            text = _coerce_str(val)
        except Exception:
            text = ""
        if len(text) > limit:
            return text[: max(0, limit - 1)] + "…"
        return text

    def _compact_labels(val: Any) -> str | None:
        if not isinstance(val, dict):
            return None
        # Keep only high-signal fields used by anomaly alerts
        keys = ("top_slow_endpoint", "active_requests", "recent_errors_5m", "avg_memory_usage_mb")
        parts: List[str] = []
        for k in keys:
            try:
                v = val.get(k)
            except Exception:
                v = None
            if v in (None, ""):
                continue
            parts.append(f"{k}={_short(v, limit=80)}")
        if parts:
            return ", ".join(parts)
        return None

    def _compact_slow_endpoints(val: Any) -> str | None:
        if not isinstance(val, list) or not val:
            return None
        parts: List[str] = []
        for item in val[:4]:
            if not isinstance(item, dict):
                continue
            try:
                method = str(item.get("method") or "GET").upper()
                endpoint = str(item.get("endpoint") or "unknown")
                count = int(item.get("count") or 0)
                avg = float(item.get("avg_duration") or 0.0)
                # Prefer avg (more stable), keep max only when it's the same (common in single sample)
                parts.append(f"{method} {endpoint}: {avg:.2f}s (n={max(1, count)})")
            except Exception:
                continue
        if parts:
            return "; ".join(parts)
        return None

    for key, value in details.items():
        try:
            lk = str(key).lower()
        except Exception:
            continue
        if lk in _SENSITIVE_DETAIL_KEYS or lk in _PROMOTED_DETAIL_KEYS or lk in _SENTRY_META_KEYS:
            continue
        # Special compaction for noisy structured fields
        if lk == "labels":
            compact = _compact_labels(value)
            if compact:
                safe_items.append(compact)
                if len(safe_items) >= 6:
                    break
                continue
        if lk == "slow_endpoints":
            compact = _compact_slow_endpoints(value)
            if compact:
                safe_items.append(f"slow_endpoints={compact}")
                if len(safe_items) >= 6:
                    break
                continue
        safe_items.append(f"{key}={_coerce_str(value)}")
        if len(safe_items) >= 6:
            break
    if safe_items:
        return ", ".join(safe_items)
    return None


def _build_forward_payload(name: str, severity: str, summary: str, details: Dict[str, Any]) -> Dict[str, Any]:
    alert = {
        "status": "firing",
        "labels": {"alertname": str(name or "InternalAlert"), "severity": str(severity or "warn")},
        "annotations": {"summary": str(summary or "")},
    }
    if not isinstance(details, dict) or not details:
        return alert

    service = _first_detail(details, ("service", "component", "app", "application"))
    environment = _first_detail(details, ("env", "environment", "namespace", "cluster"))
    instance = _first_detail(details, ("instance", "pod", "hostname", "host"))
    request_id = _first_detail(details, ("request_id", "request-id", "x-request-id", "x_request_id"))

    if service:
        alert["labels"]["service"] = service
    if environment:
        alert["labels"]["env"] = environment
    if instance:
        alert["labels"]["instance"] = instance
    if request_id:
        alert["labels"]["request_id"] = request_id

    generator_url = _first_detail(details, ("generator_url", "grafana_url", "dashboard_url"))
    if generator_url:
        alert["generatorURL"] = generator_url

    sentry_direct = _first_detail(details, ("sentry_permalink", "sentry-permalink", "sentry_url", "sentry"))
    if sentry_direct:
        alert["annotations"]["sentry_permalink"] = sentry_direct
    error_signature = _first_detail(details, ("error_signature", "signature"))
    if error_signature:
        alert["annotations"]["error_signature"] = error_signature

    # Promote a small allowlist of numeric/meta fields into annotations for better formatting downstream.
    # Keep values as strings to match Alertmanager annotations behavior.
    try:
        promote_keys = (
            # Generic metric fields (alert_manager / internal)
            "current_percent",
            "threshold_percent",
            "sample_count",
            "error_count",
            "window_seconds",
            "current_seconds",
            "threshold_seconds",
            "source",
            "metric",
            "graph_metric",
            # Sentry meta (webhook/poll)
            "sentry_short_id",
            "sentry_issue_id",
            "sentry_last_seen",
            "sentry_first_seen",
            "project",
            "level",
            "action",
        )
        for k in promote_keys:
            if k not in details:
                continue
            try:
                v = details.get(k)
            except Exception:
                v = None
            if v in (None, ""):
                continue
            alert["annotations"][k] = _coerce_str(v)
    except Exception:
        pass

    # Anomaly formatting helpers: flatten nested labels + compact slow endpoints list.
    try:
        if str(name or "").strip().lower() == "anomaly_detected":
            raw_labels = details.get("labels") if isinstance(details, dict) else None
            if isinstance(raw_labels, dict):
                for k in ("top_slow_endpoint", "active_requests", "recent_errors_5m", "avg_memory_usage_mb"):
                    try:
                        v = raw_labels.get(k)
                    except Exception:
                        v = None
                    if v in (None, ""):
                        continue
                    alert["annotations"][k] = _coerce_str(v)
            raw_slow = details.get("slow_endpoints") if isinstance(details, dict) else None
            if isinstance(raw_slow, list) and raw_slow:
                compact_parts: List[str] = []
                for item in raw_slow[:6]:
                    if not isinstance(item, dict):
                        continue
                    try:
                        method = str(item.get("method") or "GET").upper()
                        endpoint = str(item.get("endpoint") or "unknown")
                        count = int(item.get("count") or 0)
                        avg = float(item.get("avg_duration") or 0.0)
                        compact_parts.append(f"{method} {endpoint}: {avg:.2f}s (n={max(1, count)})")
                    except Exception:
                        continue
                if compact_parts:
                    alert["annotations"]["slow_endpoints_compact"] = "; ".join(compact_parts)
    except Exception:
        pass

    preview = _details_preview(details)
    if preview:
        alert["annotations"]["details_preview"] = preview

    return alert


def _severity_rank(value: str | None) -> int:
    try:
        v = (value or "").strip().lower()
        if v in {"critical", "fatal", "crit"}:
            return 4
        if v in {"error", "err", "errors"}:
            return 3
        if v in {"warning", "warn"}:
            return 2
        if v in {"info", "notice", "anomaly"}:
            return 1
        if v in {"debug", "trace"}:
            return 0
    except Exception:
        return 1
    return 1


def _min_direct_telegram_rank() -> int:
    raw = os.getenv("ALERT_TELEGRAM_MIN_SEVERITY", "info")
    return _severity_rank(raw)


def _should_send_direct_telegram(severity: str) -> bool:
    try:
        return _severity_rank(severity) >= _min_direct_telegram_rank()
    except Exception:
        return True


def _format_text(name: str, severity: str, summary: str, details: Dict[str, Any]) -> str:
    parts = [f"[{severity.upper()}] {name}"]
    if summary:
        parts.append(str(summary))
    if details:
        # Keep it short, avoid leaking sensitive data
        safe = {k: v for k, v in details.items() if k.lower() not in {"token", "password", "secret", "authorization"}}
        if safe:
            parts.append("details=" + ", ".join(f"{k}={v}" for k, v in list(safe.items())[:6]))

    # Add Sentry Link if configured
    sentry_url = os.getenv("SENTRY_DASHBOARD_URL")
    sentry_org = os.getenv("SENTRY_ORG")
    if sentry_url:
        parts.append(f"\n[פתח ב-Sentry]({sentry_url})")
    elif sentry_org and os.getenv("SENTRY_DSN"):
        # Construct search link
        import urllib.parse
        query = urllib.parse.quote(f"is:unresolved {name}")
        link = f"https://{sentry_org}.sentry.io/issues/?query={query}"
        parts.append(f"\n[פתח ב-Sentry]({link})")

    return "\n".join(parts)


def _send_telegram(text: str, severity: str = "info") -> None:
    if not _should_send_direct_telegram(severity):
        return
    token = os.getenv("ALERT_TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("ALERT_TELEGRAM_CHAT_ID")
    if not token or not chat_id or request is None:
        return
    try:
        api = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {"chat_id": chat_id, "text": text}
        request('POST', api, json=payload, timeout=5)
    except Exception:
        # Don't raise
        pass


def emit_internal_alert(name: str, severity: str = "info", summary: str = "", **details: Any) -> None:
    """Emit an internal alert: store in-memory, forward to sinks, and log.

    severity: "info" | "warn" | "error" | "critical" | "anomaly"
    """
    try:
        def _is_drill(d: Any) -> bool:
            if not isinstance(d, dict):
                return False
            try:
                if bool(d.get("is_drill")):
                    return True
            except Exception:
                pass
            try:
                meta = d.get("metadata")
                if isinstance(meta, dict) and bool(meta.get("is_drill")):
                    return True
            except Exception:
                pass
            return False

        rec = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "name": str(name),
            "severity": str(severity),
            "summary": str(summary),
        }
        if details:
            rec["details"] = {k: (str(v) if not isinstance(v, (int, float, bool)) else v) for k, v in details.items()}
        _ALERTS.append(rec)
        is_drill = _is_drill(details)
        if internal_alerts_total is not None:
            try:
                internal_alerts_total.labels(str(name or "InternalAlert"), str(severity or "info")).inc()
            except Exception:
                pass

        # Emit structured log/event as well
        # חשוב: אל תשלח את חומרת ההתראה כ-severity של emit_event,
        # אחרת observability.emit_event יתעד זאת כ-error/critical ב-Sentry וייצור Issues "internal_alert".
        # במקום זה, משדרים תמיד כאנומליה (לצורך תיעוד/דאשבורד) ושומרים את החומרה המקורית בשדה נפרד.
        emit_event(
            "internal_alert",
            severity="anomaly",
            alert_severity=str(severity),
            name=str(name),
            summary=str(summary),
            is_drill=bool(is_drill),
            handled=True if is_drill else None,
        )

        # Note: Do not persist here to avoid double counting with alert_manager.

        # For critical alerts – use alert_manager for Telegram + Grafana annotations with dispatch log
        if str(severity).lower() == "critical":
            # Safety switch: תרגול לא יוצא לסינקים קריטיים (טלגרם/גרפנה/אוטומציות)
            if is_drill:
                try:
                    from monitoring.alerts_storage import record_alert  # type: ignore
                    record_alert(
                        alert_id=None,
                        name=str(name),
                        severity="critical",
                        summary=str(summary),
                        source="internal_alerts",
                        details=details if isinstance(details, dict) else None,
                    )
                except Exception:
                    pass
                return
            try:
                from alert_manager import forward_critical_alert  # type: ignore
                forward_critical_alert(name=str(name), summary=str(summary), **(details or {}))
            except Exception:
                # Fallback to Telegram only
                try:
                    _send_telegram(_format_text(name, severity, summary, details), severity=str(severity))
                except Exception:
                    pass
                # Best-effort: persist critical alert when fallback path used
                try:
                    from monitoring.alerts_storage import record_alert  # type: ignore
                    record_alert(
                        alert_id=None,
                        name=str(name),
                        severity="critical",
                        summary=str(summary),
                        source="internal_alerts",
                        details=details if isinstance(details, dict) else None,
                    )
                except Exception:
                    pass
        else:
            # Prefer alert_forwarder when available; otherwise Telegram fallback
            # Safety switch: תרגול לא יוצא לסינקים
            if is_drill:
                try:
                    from monitoring.alerts_storage import record_alert  # type: ignore
                    record_alert(
                        alert_id=None,
                        name=str(name),
                        severity=str(severity),
                        summary=str(summary),
                        source="internal_alerts",
                        details=details if isinstance(details, dict) else None,
                    )
                except Exception:
                    pass
                return
            try:
                if forward_alerts is not None:
                    alert = _build_forward_payload(name, severity, summary, details)
                    forward_alerts([alert])
                else:
                    _send_telegram(_format_text(name, severity, summary, details), severity=str(severity))
            except Exception:
                # Never break on sinks; try fallback Telegram
                try:
                    _send_telegram(_format_text(name, severity, summary, details), severity=str(severity))
                except Exception:
                    pass
            # Best-effort: persist non-critical alert (single write)
            try:
                from monitoring.alerts_storage import record_alert  # type: ignore
                record_alert(
                    alert_id=None,
                    name=str(name),
                    severity=str(severity),
                    summary=str(summary),
                    source="internal_alerts",
                    details=details if isinstance(details, dict) else None,
                )
            except Exception:
                pass
    except Exception:
        return


def get_recent_alerts(limit: int = 5) -> List[Dict[str, Any]]:
    try:
        if limit <= 0:
            return []
        return list(_ALERTS)[-limit:]
    except Exception:
        return []
