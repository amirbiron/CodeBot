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

# Graceful degradation for HTTP client: prefer pooled http_sync for retries/backoff,
# fallback to plain requests when pooler is unavailable.
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


def _use_plain_requests() -> bool:
    """Return True when we should prefer plain requests over the pooled client.

    Resolution order:
    1) REQUESTS_FORCE_PLAIN=1|true|yes -> True
    2) REQUESTS_FORCE_POOLED=1|true|yes -> False
    3) If running under pytest and `_pooled_request` appears monkeypatched
       (function __module__ != 'http_sync') -> use pooled (False)
    4) If running under pytest and `_pooled_request` is the default from http_sync -> True
    5) Otherwise (normal runtime): if pooled exists -> False else -> True
    """
    try:
        force_plain = (os.getenv("REQUESTS_FORCE_PLAIN", "") or "").strip().lower() in {"1", "true", "yes"}
        if force_plain:
            return True
        force_pooled = (os.getenv("REQUESTS_FORCE_POOLED", "") or "").strip().lower() in {"1", "true", "yes"}
        if force_pooled:
            return False

        pooled_exists = _pooled_request is not None
        under_pytest = "PYTEST_CURRENT_TEST" in os.environ

        if under_pytest:
            if pooled_exists and getattr(_pooled_request, "__module__", "") != "http_sync":
                # Test explicitly monkeypatched pooled transport; honor it
                return False
            # Default under pytest: use plain requests so tests can monkeypatch requests.post
            return True

        # Normal runtime: prefer pooled when available
        return not pooled_exists
    except Exception:
        # Fail-open to plain requests
        return True


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
        # Prefer pooled client for retry/backoff in production, but use plain
        # requests during tests or when explicitly requested.
        if not _use_plain_requests() and _pooled_request is not None:
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
        # Prefer pooled client for retry/backoff in production, but use plain
        # requests during tests or when explicitly requested.
        if not _use_plain_requests() and _pooled_request is not None:
            _pooled_request('POST', api, json=payload, timeout=5)
        elif _requests is not None:
            _requests.post(api, json=payload, timeout=5)
        else:
            raise RuntimeError("no http client available")
    except Exception:
        emit_event("alert_forward_telegram_error", severity="warn")


def forward_alerts(alerts: List[Dict[str, Any]]) -> None:
    """Forward a list of Alertmanager alerts to configured sinks, respecting silences (best-effort)."""
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
            # Silence enforcement (pattern on name). Fail-open on errors.
            try:
                from monitoring.silences import is_silenced  # type: ignore
                name = str(labels.get("alertname") or labels.get("name") or "")
                sev_norm = str(severity or "").lower() or None
                silenced, silence_info = is_silenced(name=name, severity=sev_norm)
            except Exception:
                silenced, silence_info = False, None
            if silenced:
                try:
                    emit_event(
                        "alert_silenced",
                        severity="info",
                        name=str(labels.get("alertname") or labels.get("name") or ""),
                        silence_id=str((silence_info or {}).get("_id") or ""),
                        until=str((silence_info or {}).get("until_ts") or ""),
                    )
                except Exception:
                    pass
                # Do not send to sinks
                continue
            _post_to_slack(text)
            _post_to_telegram(text)
        except Exception:
            emit_event("alert_forward_error", severity="warn")
