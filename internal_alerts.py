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
    for key, value in details.items():
        try:
            lk = str(key).lower()
        except Exception:
            continue
        if lk in _SENSITIVE_DETAIL_KEYS or lk in _PROMOTED_DETAIL_KEYS or lk in _SENTRY_META_KEYS:
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
        rec = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "name": str(name),
            "severity": str(severity),
            "summary": str(summary),
        }
        if details:
            rec["details"] = {k: (str(v) if not isinstance(v, (int, float, bool)) else v) for k, v in details.items()}
        _ALERTS.append(rec)

        # Emit structured log/event as well
        emit_event("internal_alert", severity=str(severity), name=str(name), summary=str(summary))

        # Note: Do not persist here to avoid double counting with alert_manager.

        # For critical alerts – use alert_manager for Telegram + Grafana annotations with dispatch log
        if str(severity).lower() == "critical":
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
                    record_alert(alert_id=None, name=str(name), severity="critical", summary=str(summary), source="internal_alerts")
                except Exception:
                    pass
        else:
            # Prefer alert_forwarder when available; otherwise Telegram fallback
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
                record_alert(alert_id=None, name=str(name), severity=str(severity), summary=str(summary), source="internal_alerts")
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
