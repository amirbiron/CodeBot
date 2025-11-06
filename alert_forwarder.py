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


def _format_alert_text(alert: Dict[str, Any]) -> str:
    labels = alert.get("labels", {}) or {}
    annotations = alert.get("annotations", {}) or {}
    status = str(alert.get("status") or "firing")
    severity = str(labels.get("severity") or labels.get("level") or "info").upper()
    name = labels.get("alertname") or labels.get("name") or "Alert"
    component = labels.get("component") or ""
    summary = annotations.get("summary") or annotations.get("description") or ""
    generator_url = alert.get("generatorURL") or ""
    parts = [f"[{status.upper()} | {severity}] {name}"]
    if component:
        parts.append(f"component: {component}")
    if summary:
        parts.append(str(summary))
    if generator_url:
        parts.append(str(generator_url))
    return "\n".join(parts)


def _is_monkeypatched_pooled() -> bool:
    """Detect if _pooled_request was monkeypatched by tests.

    If _pooled_request is a callable and is not the original http_sync.request,
    we consider it monkeypatched and prefer using it.
    """
    try:
        from http_sync import request as _original  # type: ignore
    except Exception:  # pragma: no cover
        _original = None  # type: ignore
    try:
        return callable(_pooled_request) and (_pooled_request is not _original)
    except Exception:
        return False


def _use_pooled_http() -> bool:
    """Whether to prefer pooled HTTP client over requests.

    - Explicit opt-in via ALERTS_USE_POOLED_HTTP (1/true/yes/on)
    - Or when tests monkeypatch _pooled_request to a stub
    """
    val = str(os.getenv("ALERTS_USE_POOLED_HTTP", "")).strip().lower()
    if val in {"1", "true", "yes", "on"}:
        return True
    return _is_monkeypatched_pooled()


def _post_to_slack(text: str) -> None:
    url = os.getenv("SLACK_WEBHOOK_URL")
    if not url:
        return
    try:
        prefer_pooled = _use_pooled_http()
        if prefer_pooled and _pooled_request is not None:
            _pooled_request('POST', url, json={"text": text}, timeout=5)
        elif _requests is not None:
            _requests.post(url, json={"text": text}, timeout=5)
        elif _pooled_request is not None:
            _pooled_request('POST', url, json={"text": text}, timeout=5)
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
        prefer_pooled = _use_pooled_http()
        if prefer_pooled and _pooled_request is not None:
            _pooled_request('POST', api, json=payload, timeout=5)
        elif _requests is not None:
            _requests.post(api, json=payload, timeout=5)
        elif _pooled_request is not None:
            _pooled_request('POST', api, json=payload, timeout=5)
        else:
            raise RuntimeError("no http client available")
    except Exception:
        emit_event("alert_forward_telegram_error", severity="warn")


def _severity_rank(value: str | None) -> int:
    try:
        v = (value or "").strip().lower()
        if v in {"critical", "fatal", "crit"}:
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


def _min_telegram_severity_rank() -> int:
    # Default: send all severities unless explicitly raised via env
    raw = os.getenv("ALERT_TELEGRAM_MIN_SEVERITY", "info")
    return _severity_rank(raw)


def forward_alerts(alerts: List[Dict[str, Any]]) -> None:
    """Forward a list of Alertmanager alerts to configured sinks, respecting silences (best-effort)."""
    if not isinstance(alerts, list):
        return
    min_tg_rank = _min_telegram_severity_rank()
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
            # Send to Telegram only if severity >= configured minimum
            if _severity_rank(severity) >= min_tg_rank:
                _post_to_telegram(text)
        except Exception:
            emit_event("alert_forward_error", severity="warn")
