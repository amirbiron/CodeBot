"""
Forward incoming Alertmanager alerts to Slack and/or Telegram.

Environment variables used:
- SLACK_WEBHOOK_URL: Incoming webhook URL for Slack (optional)
- ALERT_TELEGRAM_BOT_TOKEN: Bot token for Telegram (optional)
- ALERT_TELEGRAM_CHAT_ID: Chat ID (or channel) to send alerts to (optional)

If none are configured, alerts will still be emitted as structured events.
"""
from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass
from threading import Lock, Timer
from time import monotonic
from typing import Any, Dict, List, Optional

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


_ANOMALY_WINDOW_SECONDS = max(
    0.0,
    float(os.getenv("ALERT_ANOMALY_BATCH_WINDOW_SECONDS", "180") or 180),
)
_ANOMALY_LOCK: Lock = Lock()
_DIGIT_RE = re.compile(r"\d+")


@dataclass
class _AnomalyBatch:
    key: str
    representative_alert: Dict[str, Any]
    count: int
    started_at: float
    window_seconds: float
    timer: Timer


_ANOMALY_BATCHES: Dict[str, _AnomalyBatch] = {}


def _format_alert_text(alert: Dict[str, Any]) -> str:
    labels = alert.get("labels", {}) or {}
    annotations = alert.get("annotations", {}) or {}
    status = str(alert.get("status") or "firing")
    severity = str(labels.get("severity") or labels.get("level") or "info").upper()
    name = labels.get("alertname") or labels.get("name") or "Alert"

    # Short summary/description
    summary = annotations.get("summary") or annotations.get("description") or ""

    # Useful context (allowlist of common labels)
    def _first(keys: List[str]) -> Optional[str]:
        for k in keys:
            v = labels.get(k)
            if v:
                return str(v)
            v = annotations.get(k)
            if v:
                return str(v)
        return None

    service = _first(["service", "app", "application", "job", "component"])
    environment = _first(["env", "environment", "namespace", "cluster"])  # loose mapping
    instance = _first(["instance", "pod", "hostname"])  # k8s or host
    request_id = _first(["request_id", "request-id", "x-request-id", "x_request_id"])  # if present

    generator_url = alert.get("generatorURL") or ""

    parts = [f"[{status.upper()} | {severity}] {name}"]
    if service:
        parts.append(f"service: {service}")
    if environment:
        parts.append(f"env: {environment}")
    if instance:
        parts.append(f"instance: {instance}")
    if summary:
        parts.append(str(summary))
    detail_preview = annotations.get("details_preview") or annotations.get("details")
    if detail_preview:
        parts.append(str(detail_preview))
    if request_id:
        parts.append(f"request_id: {request_id}")

    # Append source URL if exists (Alertmanager/Grafana link)
    if generator_url:
        parts.append(str(generator_url))

    # Best-effort: add Sentry link (issue/events search) when configured
    sentry_link = _build_sentry_link(
        direct_url=_first(["sentry_permalink", "sentry_url", "sentry"]),
        request_id=request_id,
        error_signature=_first(["error_signature", "signature"]),
    )
    if sentry_link:
        parts.append(f"Sentry: {sentry_link}")

    return "\n".join(parts)


def _build_sentry_link(
    direct_url: Optional[str] = None,
    request_id: Optional[str] = None,
    error_signature: Optional[str] = None,
) -> Optional[str]:
    """Build a Sentry UI link.

    Priority:
    1) If a direct permalink is provided – return it.
    2) If request_id is present – build an events/issues query for that request_id.
    3) Else, if error_signature is present – build a query by signature.

    Returns None when Sentry env is not configured.
    """
    try:
        # 1) Direct URL from alert annotations/labels
        if direct_url:
            return str(direct_url)

        # Derive UI base from explicit dashboard URL or DSN + ORG
        dashboard = os.getenv("SENTRY_DASHBOARD_URL") or os.getenv("SENTRY_PROJECT_URL")
        if dashboard:
            base_url = dashboard.rstrip("/")
            # Ensure we point to org scope when given a project URL
            # We'll still append ?query=... which both endpoints accept.
        else:
            dsn = os.getenv("SENTRY_DSN") or ""
            host = None
            if dsn:
                try:
                    from urllib.parse import urlparse
                    parsed = urlparse(dsn)
                    raw_host = parsed.hostname or ""
                except Exception:
                    raw_host = ""
                # Preserve regional subdomain when present, e.g. o123.ingest.eu.sentry.io -> eu.sentry.io
                if ".ingest." in raw_host:
                    try:
                        host = raw_host.split(".ingest.", 1)[1]
                    except Exception:
                        host = None
                elif raw_host.startswith("ingest."):
                    host = raw_host[len("ingest."):]
                elif raw_host == "sentry.io" or raw_host.endswith(".sentry.io"):
                    host = "sentry.io"
                else:
                    host = raw_host or None
            host = host or "sentry.io"
            org = os.getenv("SENTRY_ORG") or os.getenv("SENTRY_ORG_SLUG")
            if not org:
                return None
            base_url = f"https://{host}/organizations/{org}/issues"

        from urllib.parse import quote_plus

        if request_id:
            q = quote_plus(f'request_id:"{request_id}"')
            return f"{base_url}/?query={q}&statsPeriod=24h"
        if error_signature:
            q = quote_plus(f'error_signature:"{error_signature}"')
            return f"{base_url}/?query={q}&statsPeriod=24h"
        return None
    except Exception:
        return None


def _format_duration_label(seconds: float) -> str:
    try:
        seconds = float(seconds)
    except Exception:
        seconds = 60.0
    minutes = max(1, int(math.ceil(seconds / 60.0)))
    return f"{minutes} דקות"


def _format_anomaly_batch_text(alert: Dict[str, Any], count: int, duration_seconds: float) -> str:
    base = _format_alert_text(alert)
    duration = _format_duration_label(duration_seconds)
    return f"{base}\n{count} מופעים ב-{duration}"


def _anomaly_bucket_key(alert: Dict[str, Any]) -> str:
    labels = alert.get("labels", {}) or {}
    annotations = alert.get("annotations", {}) or {}

    def _pick(sources: List[Dict[str, Any]], keys: List[str]) -> str:
        for key in keys:
            for src in sources:
                try:
                    val = src.get(key)
                except Exception:
                    continue
                if val not in (None, ""):
                    return str(val).strip().lower()
        return ""

    alert_name = _pick([labels], ["alertname", "name"]) or "anomaly"
    service = _pick([labels], ["service", "app", "application", "job", "component"])
    environment = _pick([labels], ["env", "environment", "namespace", "cluster"])
    signature = _pick([annotations, labels], ["error_signature", "signature"])
    if not signature:
        summary = _pick([annotations], ["summary", "description"])
        if summary:
            signature = _DIGIT_RE.sub("0", summary.lower())[:80]
    parts = [alert_name]
    if service:
        parts.append(service)
    if environment:
        parts.append(environment)
    if signature:
        parts.append(signature)
    return "|".join(parts)


def _queue_anomaly_alert(alert: Dict[str, Any]) -> bool:
    if _ANOMALY_WINDOW_SECONDS <= 0:
        return False
    key = _anomaly_bucket_key(alert)
    timer: Timer | None = None
    with _ANOMALY_LOCK:
        batch = _ANOMALY_BATCHES.get(key)
        if batch:
            batch.count += 1
            batch.representative_alert = alert
            return True
        timer = Timer(_ANOMALY_WINDOW_SECONDS, _flush_anomaly_batch, args=(key,))
        timer.daemon = True
        _ANOMALY_BATCHES[key] = _AnomalyBatch(
            key=key,
            representative_alert=alert,
            count=1,
            started_at=monotonic(),
            window_seconds=_ANOMALY_WINDOW_SECONDS,
            timer=timer,
        )
    if timer is not None:
        timer.start()
    return True


def _flush_anomaly_batch(key: str) -> None:
    with _ANOMALY_LOCK:
        batch = _ANOMALY_BATCHES.pop(key, None)
    if not batch:
        return
    duration_seconds = max(batch.window_seconds, monotonic() - batch.started_at)
    text = _format_anomaly_batch_text(batch.representative_alert, batch.count, duration_seconds)
    _post_to_telegram(text)


def _reset_anomaly_batches_for_tests() -> None:
    with _ANOMALY_LOCK:
        for batch in _ANOMALY_BATCHES.values():
            try:
                batch.timer.cancel()
            except Exception:
                pass
        _ANOMALY_BATCHES.clear()


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
            severity = str(labels.get("severity") or labels.get("level") or "info")
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
                sev_norm = str(severity or "").strip().lower()
                if sev_norm == "anomaly" and _queue_anomaly_alert(alert):
                    continue
                _post_to_telegram(text)
        except Exception:
            emit_event("alert_forward_error", severity="warn")
