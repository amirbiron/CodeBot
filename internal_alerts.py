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
    import requests  # type: ignore
except Exception:  # pragma: no cover
    requests = None  # type: ignore

try:  # observability event emission (optional)
    from observability import emit_event  # type: ignore
except Exception:  # pragma: no cover
    def emit_event(event: str, severity: str = "info", **fields):  # type: ignore
        return None

# Optional Prometheus counter for alerts volume (fail-open)
try:  # pragma: no cover - optional at runtime
    from metrics import codebot_alerts_total  # type: ignore
except Exception:  # pragma: no cover
    codebot_alerts_total = None  # type: ignore

# Optional sink forwarder (Slack/Telegram) – used when available
try:
    from alert_forwarder import forward_alerts  # type: ignore
except Exception:  # pragma: no cover
    forward_alerts = None  # type: ignore


_MAX = int(os.getenv("INTERNAL_ALERTS_BUFFER", "200") or 200)
_ALERTS: "deque[Dict[str, Any]]" = deque(maxlen=max(10, _MAX))


def _format_text(name: str, severity: str, summary: str, details: Dict[str, Any]) -> str:
    parts = [f"[{severity.upper()}] {name}"]
    if summary:
        parts.append(str(summary))
    if details:
        # Keep it short, avoid leaking sensitive data
        safe = {k: v for k, v in details.items() if k.lower() not in {"token", "password", "secret", "authorization"}}
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

        # Increment Prometheus counter (labeled by source/severity)
        try:
            if codebot_alerts_total is not None:
                codebot_alerts_total.labels(source="internal", severity=str(severity or "info")).inc()
        except Exception:
            pass

        # Emit structured log/event as well
        emit_event("internal_alert", severity=str(severity), name=str(name), summary=str(summary))

        # Prefer alert_forwarder when available; otherwise Telegram fallback
        try:
            if forward_alerts is not None:
                alert = {
                    "status": "firing",
                    "labels": {"alertname": str(name or "InternalAlert"), "severity": str(severity or "warn")},
                    "annotations": {"summary": str(summary or "")},
                }
                forward_alerts([alert])
            else:
                _send_telegram(_format_text(name, severity, summary, details))
        except Exception:
            # Never break on sinks; try fallback Telegram
            try:
                _send_telegram(_format_text(name, severity, summary, details))
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
