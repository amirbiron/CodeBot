"""
Forward incoming Alertmanager alerts to Slack and/or Telegram.

Environment variables used:
- SLACK_WEBHOOK_URL: Incoming webhook URL for Slack (optional)
- ALERT_TELEGRAM_BOT_TOKEN: Bot token for Telegram (optional)
- ALERT_TELEGRAM_CHAT_ID: Chat ID (or channel) to send alerts to (optional)

If none are configured, alerts will still be emitted as structured events.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List

# Graceful degradation for HTTP client: prefer pooled http_sync, fallback to requests
try:  # pragma: no cover
    from http_sync import request as _pooled_request  # type: ignore
except Exception:  # pragma: no cover
    _pooled_request = None  # type: ignore
try:  # pragma: no cover
    import requests as _requests  # type: ignore
except Exception:  # pragma: no cover
    _requests = None  # type: ignore

try:
    from observability import emit_event  # type: ignore
except Exception:  # pragma: no cover
    def emit_event(event: str, severity: str = "info", **fields):  # type: ignore
        return None


def _format_alert_text(alert: Dict[str, Any]) -> str:
    labels = alert.get("labels", {}) or {}
    annotations = alert.get("annotations", {}) or {}
    status = str(alert.get("status") or "firing")
    severity = str(labels.get("severity") or labels.get("level") or "info").upper()
    name = labels.get("alertname") or labels.get("name") or "Alert"
    summary = annotations.get("summary") or annotations.get("description") or ""
    generator_url = alert.get("generatorURL") or ""
    parts = [f"[{status.upper()} | {severity}] {name}"]
    if summary:
        parts.append(str(summary))
    if generator_url:
        parts.append(str(generator_url))
    return "\n".join(parts)


def _post_to_slack(text: str) -> None:
    url = os.getenv("SLACK_WEBHOOK_URL")
    if not url:
        return
    try:
        if _pooled_request is not None:
            _pooled_request('POST', url, json={"text": text}, timeout=5)
        elif _requests is not None:
            _requests.post(url, json={"text": text}, timeout=5)
        else:
            raise RuntimeError("no http client available")
    except Exception:
        emit_event("alert_forward_slack_error", severity="warn")


def _post_to_telegram(text: str) -> None:
    token = os.getenv("ALERT_TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("ALERT_TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return
    try:
        api = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {"chat_id": chat_id, "text": text}
        if _pooled_request is not None:
            _pooled_request('POST', api, json=payload, timeout=5)
        elif _requests is not None:
            _requests.post(api, json=payload, timeout=5)
        else:
            raise RuntimeError("no http client available")
    except Exception:
        emit_event("alert_forward_telegram_error", severity="warn")


def forward_alerts(alerts: List[Dict[str, Any]]) -> None:
    """Forward a list of Alertmanager alerts to configured sinks and log them."""
    if not isinstance(alerts, list):
        return
    for alert in alerts:
        try:
            text = _format_alert_text(alert)
            labels = alert.get("labels", {}) or {}
            severity = labels.get("severity") or labels.get("level") or "info"
            # Emit the base receipt event consistently as anomaly to reflect detection,
            # while preserving the original label in a separate field for observability.
            mapped_severity = "anomaly"
            emit_event(
                "alert_received",
                severity=mapped_severity,
                alertname=str(labels.get("alertname") or labels.get("name") or ""),
                severity_label=str(severity),
                status=str(alert.get("status") or ""),
                handled=False,
            )
            _post_to_slack(text)
            _post_to_telegram(text)
        except Exception:
            emit_event("alert_forward_error", severity="warn")
