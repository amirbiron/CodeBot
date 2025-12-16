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


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(str(value).strip()))
    except Exception:
        return int(default)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(str(value).strip().replace("%", "").replace("s", ""))
    except Exception:
        return float(default)


def _fmt_minutes(window_seconds: Any) -> str:
    sec = _safe_int(window_seconds, 0)
    if sec <= 0:
        return "—"
    minutes = max(1, int(math.ceil(sec / 60.0)))
    return f"{minutes} minutes"


def _clean_sentry_noise(text: str) -> str:
    """Remove very noisy Sentry/driver fragments for chat notifications."""
    try:
        t = str(text or "")
    except Exception:
        return ""
    # Drop TopologyDescription tail (very long)
    try:
        t = re.sub(r",?\s*Topology Description:\s*<TopologyDescription[\s\S]*$", "", t, flags=re.IGNORECASE)
    except Exception:
        pass
    # Trim excessive whitespace
    try:
        t = re.sub(r"\s+", " ", t).strip()
    except Exception:
        pass
    # Hard cap to avoid huge messages
    if len(t) > 260:
        t = t[:259] + "…"
    return t


def _extract_host_from_text(text: str) -> Optional[str]:
    try:
        m = re.search(r"([\w-]+\.mongodb\.net)", str(text or ""))
        return m.group(1) if m else None
    except Exception:
        return None


def _extract_connect_timeout_ms(text: str) -> Optional[int]:
    try:
        m = re.search(r"connectTimeoutMS:\s*([0-9.]+)ms", str(text or ""), flags=re.IGNORECASE)
        if m:
            return int(float(m.group(1)))
    except Exception:
        return None
    return None


def _parse_avg_threshold_from_summary(summary: str) -> tuple[Optional[float], Optional[float]]:
    """Parse `avg_rt=3.737s (threshold 3.000s)` style summaries."""
    try:
        s = str(summary or "")
    except Exception:
        return None, None
    try:
        m_avg = re.search(r"avg_rt\s*=\s*([0-9.]+)s", s, flags=re.IGNORECASE)
        m_thr = re.search(r"threshold\s*([0-9.]+)s", s, flags=re.IGNORECASE)
        avg = float(m_avg.group(1)) if m_avg else None
        thr = float(m_thr.group(1)) if m_thr else None
        return avg, thr
    except Exception:
        return None, None


def _parse_percent_pair_from_summary(summary: str) -> tuple[Optional[float], Optional[float]]:
    """Parse `...=60.00% > threshold=20.00%` style summaries."""
    try:
        s = str(summary or "")
    except Exception:
        return None, None
    try:
        m_cur = re.search(r"=\s*([0-9.]+)%", s)
        m_thr = re.search(r"threshold\s*=\s*([0-9.]+)%", s, flags=re.IGNORECASE)
        cur = float(m_cur.group(1)) if m_cur else None
        thr = float(m_thr.group(1)) if m_thr else None
        return cur, thr
    except Exception:
        return None, None


def _format_external_service_degraded(
    *,
    service: Optional[str],
    current_percent: Optional[float],
    threshold_percent: Optional[float],
    sample_count: int,
    error_count: int,
    window_seconds: int,
) -> str:
    svc = service or "Unknown"
    cur = f"{current_percent:.0f}%" if current_percent is not None else "—"
    thr = f"{threshold_percent:.0f}%" if threshold_percent is not None else "—"
    window = _fmt_minutes(window_seconds)
    return "\n".join(
        [
            "⚠️ External Service Degraded",
            f"Service: {svc}",
            f"📉 Error Rate: {cur} (Threshold: {thr})",
            "📊 Stats:",
            f"• Errors: {error_count} / {max(0, sample_count)} requests",
            f"• Window: {window}",
            "🛑 Action Required: Check external provider status page.",
        ]
    )


def _parse_slow_endpoints_compact(value: Optional[str]) -> List[Dict[str, Any]]:
    if not value:
        return []
    try:
        raw = str(value)
    except Exception:
        return []
    entries: List[Dict[str, Any]] = []
    for chunk in [c.strip() for c in raw.split(";") if c.strip()]:
        # Format from internal_alerts: "METHOD endpoint: 10.53s (n=1)"
        try:
            m = re.match(
                r"^(?P<method>[A-Z]+)\s+(?P<endpoint>.+?):\s+(?P<sec>[0-9.]+)s\s+\(n=(?P<n>[0-9]+)\)$",
                chunk,
            )
            if not m:
                continue
            entries.append(
                {
                    "method": m.group("method"),
                    "endpoint": m.group("endpoint").strip(),
                    "seconds": float(m.group("sec")),
                    "count": int(m.group("n")),
                }
            )
        except Exception:
            continue
    return entries


def _format_anomaly_alert(
    *,
    avg_rt: Optional[float],
    threshold: Optional[float],
    top_slow_endpoint: Optional[str],
    slow_endpoints_compact: Optional[str],
    active_requests: Optional[str],
    memory_mb: Optional[str],
    recent_errors_5m: Optional[str],
) -> str:
    avg_s = f"{avg_rt:.2f}s" if avg_rt is not None else "—"
    thr_s = f"{threshold:.2f}s" if threshold is not None else "—"

    entries = _parse_slow_endpoints_compact(slow_endpoints_compact)
    main = entries[0] if entries else None
    others = entries[1:4] if len(entries) > 1 else []

    # Fallback: parse "GET index (10.525s)" when compact list is missing
    if main is None and top_slow_endpoint:
        try:
            m = re.match(r"(?P<m>\w+)\s+(?P<ep>[^()]+)\((?P<dur>[0-9.]+)s\)", top_slow_endpoint.strip())
            if m:
                main = {
                    "method": m.group("m").upper(),
                    "endpoint": m.group("ep").strip(),
                    "seconds": float(m.group("dur")),
                    "count": 1,
                }
        except Exception:
            main = None

    health_lines: List[str] = []
    if active_requests is not None:
        health_lines.append(f"• Active Req: {active_requests}")
    if memory_mb is not None:
        try:
            mem = float(str(memory_mb).strip())
            health_lines.append(f"• Memory: {mem:.0f} MB")
        except Exception:
            health_lines.append(f"• Memory: {memory_mb} MB")
    if recent_errors_5m is not None:
        health_lines.append(f"• Errors (5m): {recent_errors_5m}")

    lines = [
        "🐢 System Anomaly Detected",
        f"Avg Response: {avg_s} (Threshold: {thr_s})",
    ]
    if main:
        lines.extend(
            [
                "🐌 Main Bottleneck:",
                f"{main.get('method')} {main.get('endpoint')}",
                f"⏱️ {float(main.get('seconds') or 0.0):.2f}s",
            ]
        )
    if others:
        lines.append("📉 Also Slow in this Window:")
        for item in others:
            try:
                lines.append(f"• {item.get('method')} {item.get('endpoint')}: {float(item.get('seconds') or 0.0):.2f}s")
            except Exception:
                continue
    if health_lines:
        lines.append("📊 Resource Usage:")
        lines.extend(health_lines)
    return "\n".join(lines)


def _format_sentry_issue(
    *,
    short_id: Optional[str],
    summary: str,
    last_seen: Optional[str],
    sentry_link: Optional[str],
) -> str:
    raw = str(summary or "")
    cleaned = _clean_sentry_noise(raw)
    sid = short_id or "—"

    lowered = raw.lower()
    # Heuristics for clearer titles
    if "_operationcancelled" in lowered or "operation cancelled" in lowered:
        title = "🧹 DB Pool Maintenance Warning"
        body = "Background cleanup task failed due to network instability."
        host = _extract_host_from_text(raw)
        if host:
            body += f"\nTarget: {host}"
        text = "\n".join([title, f"Source: Sentry ({sid})", f"Error: Operation Cancelled", body])
    elif "ssl handshake failed" in lowered:
        title = "🔐 SSL Handshake Failed"
        host = _extract_host_from_text(raw) or "Unknown Host"
        timeout_ms = _extract_connect_timeout_ms(raw)
        timeout_line = f"⏱️ Timeout: {timeout_ms}ms ({(timeout_ms/1000.0):.0f}s)" if timeout_ms else "⏱️ Timeout: —"
        text = "\n".join(
            [
                title,
                f"Source: Sentry ({sid})",
                f"Target: {host}",
                timeout_line,
                _clean_sentry_noise(raw),
            ]
        )
    elif ("replicasetnoprimary" in lowered) or ("primary()" in lowered) or ("no replica set members match selector" in lowered):
        title = "🚨 Critical Database Error"
        text = "\n".join(
            [
                title,
                f"Source: Sentry ({sid})",
                "💀 Issue: MongoDB Connection Failed",
                cleaned or "—",
            ]
        )
    else:
        title = "🚨 Sentry Alert"
        text = "\n".join([title, f"Source: Sentry ({sid})", cleaned or "—"])

    if last_seen:
        text += f"\n📅 Last Seen: {last_seen}"
    if sentry_link:
        text += f"\n🔗 Action: {sentry_link}"
    return text


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

    # --- Specialized templates for high-signal alerts ---
    try:
        if str(name or "").strip() == "External Service Degraded":
            cur, thr = _parse_percent_pair_from_summary(str(summary or ""))
            # Prefer explicit annotations from internal_alerts; fallback to details_preview parsing
            cur = _safe_float(_first(["current_percent"])) if _first(["current_percent"]) else cur
            thr = _safe_float(_first(["threshold_percent"])) if _first(["threshold_percent"]) else thr
            sample_count = _safe_int(_first(["sample_count"]), 0)
            error_count = _safe_int(_first(["error_count"]), 0)
            window_seconds = _safe_int(_first(["window_seconds"]), 0)
            msg = _format_external_service_degraded(
                service=service,
                current_percent=cur,
                threshold_percent=thr,
                sample_count=sample_count,
                error_count=error_count,
                window_seconds=window_seconds,
            )
            # Append URLs (Grafana/AM + Sentry) if present
            if generator_url:
                msg += f"\n{generator_url}"
            sentry_link = _build_sentry_link(
                direct_url=_first(["sentry_permalink", "sentry_url", "sentry"]),
                request_id=request_id,
                error_signature=_first(["error_signature", "signature"]),
            )
            if sentry_link:
                msg += f"\nSentry: {sentry_link}"
            return msg

        if str(name or "").strip().lower() == "anomaly_detected":
            avg, thr = _parse_avg_threshold_from_summary(str(summary or ""))
            msg = _format_anomaly_alert(
                avg_rt=avg,
                threshold=thr,
                top_slow_endpoint=_first(["top_slow_endpoint"]),
                slow_endpoints_compact=_first(["slow_endpoints_compact"]),
                active_requests=_first(["active_requests"]),
                memory_mb=_first(["avg_memory_usage_mb"]),
                recent_errors_5m=_first(["recent_errors_5m"]),
            )
            if generator_url:
                msg += f"\n{generator_url}"
            return msg

        # Only treat as a Sentry-origin alert when the alert itself is named as such.
        # Regular alerts may still include a Sentry permalink for convenience.
        if str(name or "").strip().lower().startswith("sentry:"):
            msg = _format_sentry_issue(
                short_id=_first(["sentry_short_id"]) or (str(name).split(":", 1)[-1].strip() if ":" in str(name) else None),
                summary=str(summary or ""),
                last_seen=_first(["sentry_last_seen"]),
                sentry_link=_build_sentry_link(
                    direct_url=_first(["sentry_permalink", "sentry_url", "sentry"]),
                    request_id=request_id,
                    error_signature=_first(["error_signature", "signature"]),
                ),
            )
            return msg
    except Exception:
        # If specialized formatting fails, fall back to generic.
        pass

    parts = [f"🔔 {name} ({severity})"]
    if summary:
        parts.append(str(summary))
    if service:
        parts.append(f"service: {service}")
    if environment:
        parts.append(f"env: {environment}")
    if instance:
        parts.append(f"instance: {instance}")
    if request_id:
        parts.append(f"request_id: {request_id}")
    detail_preview = annotations.get("details_preview") or annotations.get("details")
    if detail_preview:
        parts.append(str(detail_preview))

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
