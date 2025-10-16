"""
Internal alerts system for CodeBot (post-MVP).

- Stores recent alerts in-memory for ChatOps consumption
- Forwards alerts to sinks via alert_forwarder (Slack/Telegram)
- Emits structured events via observability.emit_event

Environment variables used by sinks are handled by alert_forwarder.
This module is intentionally dependency-light and fail-open.
"""
from __future__ import annotations

from collections import deque
from typing import Any, Dict, List

try:  # sink forwarder (optional in tests)
    from alert_forwarder import forward_alerts  # type: ignore
except Exception:  # pragma: no cover
    def forward_alerts(_alerts: List[Dict[str, Any]]) -> None:  # type: ignore
        return None

try:  # observability event emission (optional)
    from observability import emit_event  # type: ignore
except Exception:  # pragma: no cover
    def emit_event(event: str, severity: str = "info", **fields):  # type: ignore
        return None


_RECENT_ALERTS: "deque[Dict[str, str]]" = deque(maxlen=200)


def emit_internal_alert(name: str, severity: str, summary: str) -> None:
    """Emit an internal alert and forward to external sinks.

    - name: short machine name (e.g., "anomaly_detected")
    - severity: info|warn|error|critical|anomaly (mapped to warn by sinks if unknown)
    - summary: human readable description
    """
    try:
        alert = {
            "status": "firing",
            "labels": {"alertname": str(name or "InternalAlert"), "severity": str(severity or "warn")},
            "annotations": {"summary": str(summary or "")},
        }
        # Keep in memory for ChatOps
        _RECENT_ALERTS.append(
            {
                "name": str(name or "InternalAlert"),
                "severity": str(severity or "warn"),
                "summary": str(summary or ""),
            }
        )
        # Emit a structured event (for logs/ELK/Sentry breadcrumbs)
        try:
            emit_event("internal_alert", severity="warn" if str(severity).lower() == "anomaly" else str(severity), name=name, summary=summary)
        except Exception:
            pass
        # Forward to sinks (Slack/Telegram)
        try:
            forward_alerts([alert])
        except Exception:
            pass
    except Exception:
        # Fail-open
        return


def get_recent_alerts(limit: int = 5) -> List[Dict[str, str]]:
    try:
        if limit <= 0:
            return []
        return list(_RECENT_ALERTS)[-limit:]
    except Exception:
        return []

"""
Internal alert system for CodeBot: in-memory queue and Telegram delivery.

Environment variables:
- ALERT_TELEGRAM_BOT_TOKEN: Bot token used for internal alert notifications (optional)
- ALERT_TELEGRAM_CHAT_ID: Chat/channel ID to send notifications to (optional)
- INTERNAL_ALERTS_BUFFER: Max number of alerts to keep in-memory (default: 200)

This module is intentionally lightweight and fail-open. It should never raise.
"""
from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
from typing import Any, Dict, List
import os

try:  # runtime optional
    import requests  # type: ignore
except Exception:  # pragma: no cover
    requests = None  # type: ignore

try:
    from observability import emit_event  # type: ignore
except Exception:  # pragma: no cover
    def emit_event(event: str, severity: str = "info", **fields):  # type: ignore
        return None


_MAX = int(os.getenv("INTERNAL_ALERTS_BUFFER", "200") or 200)
_ALERTS: "deque[Dict[str, Any]]" = deque(maxlen=max(10, _MAX))


def _format_text(name: str, severity: str, summary: str, details: Dict[str, Any]) -> str:
    parts = [f"[{severity.upper()}] {name}"]
    if summary:
        parts.append(str(summary))
    if details:
        # Keep it short, avoid leaking sensitive data
        safe = {k: v for k, v in details.items() if k.lower() not in {"token", "password", "secret"}}
        if safe:
            parts.append("details=" + ", ".join(f"{k}={v}" for k, v in list(safe.items())[:6]))
    return "\n".join(parts)


def _send_telegram(text: str) -> None:
    token = os.getenv("ALERT_TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("ALERT_TELEGRAM_CHAT_ID")
    if not token or not chat_id or requests is None:
        return
    try:
        api = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {"chat_id": chat_id, "text": text}
        requests.post(api, json=payload, timeout=5)
    except Exception:
        # Don't raise
        pass


def emit_internal_alert(name: str, severity: str = "info", summary: str = "", **details: Any) -> None:
    """Emit an internal alert: store in-memory, send to Telegram, and log event.

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
        # Try to deliver to Telegram
        _send_telegram(_format_text(name, severity, summary, details))
    except Exception:
        return


def get_recent_alerts(limit: int = 5) -> List[Dict[str, Any]]:
    try:
        if limit <= 0:
            return []
        return list(_ALERTS)[-limit:]
    except Exception:
        return []
