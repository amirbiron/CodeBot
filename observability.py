"""
Structured logging, correlation IDs, and optional Sentry initialization.

- structlog configuration with JSON/console rendering
- request_id binding via contextvars
- optional OpenTelemetry trace_id/span_id injection
- sensitive data redaction
- Sentry init (if SENTRY_DSN provided)
"""
from __future__ import annotations

import logging
import os
import uuid
from typing import Any, Dict
import time
from fnmatch import fnmatch
import threading
import random
import hashlib

import structlog
from collections import deque
from datetime import datetime

try:  # Optional OpenTelemetry
    from opentelemetry.trace import get_current_span  # type: ignore
except Exception:  # pragma: no cover
    get_current_span = None  # type: ignore

SCHEMA_VERSION = "1.0"

# Custom log level for anomalies
ANOMALY_LEVEL_NUM = 35  # between WARNING(30) and ERROR(40)
if not hasattr(logging, "ANOMALY"):
    logging.addLevelName(ANOMALY_LEVEL_NUM, "ANOMALY")

# Guard to avoid double Sentry initialization in multi-import scenarios
_SENTRY_INIT_DONE = False


def _add_otel_ids(logger, method, event_dict: Dict[str, Any]):
    try:
        if get_current_span is None:
            return event_dict
        span = get_current_span()
        ctx = span.get_span_context() if span else None
        if ctx and getattr(ctx, "is_valid", False):
            event_dict["trace_id"] = f"{ctx.trace_id:032x}"
            event_dict["span_id"] = f"{ctx.span_id:016x}"
    except Exception:
        return event_dict
    return event_dict


def _redact_sensitive(logger, method, event_dict: Dict[str, Any]):
    try:
        sensitive_keys = {"token", "password", "secret", "authorization", "cookie", "set-cookie"}
        for key in list(event_dict.keys()):
            try:
                if any(s in key.lower() for s in sensitive_keys):
                    event_dict[key] = "[REDACTED]"
            except Exception:
                continue
    except Exception:
        return event_dict
    return event_dict


def _add_schema_version(logger, method, event_dict: Dict[str, Any]):
    event_dict.setdefault("schema_version", SCHEMA_VERSION)
    return event_dict


def _choose_renderer():
    debug = str(os.getenv("DEBUG", "")).lower() in {"1", "true", "yes"}
    fmt = (os.getenv("LOG_FORMAT") or "").lower().strip()
    if debug or fmt == "console":
        return structlog.dev.ConsoleRenderer()
    return structlog.processors.JSONRenderer()


def _maybe_sample_info(logger, method, event_dict: Dict[str, Any]):
    """Drop a fraction of info-level logs based on sampling.

    - Controlled via env LOG_INFO_SAMPLE_RATE (float 0..1, default 1.0)
    - Always keep warn/error (sampling applies to info only)
    - Always keep events in allowlist (comma-separated names in LOG_INFO_SAMPLE_ALLOWLIST)
    - Sampling decision is stable per-request by hashing request_id when present
    """
    try:
        level = (event_dict.get("level") or "").lower()
        if level != "info":
            return event_dict

        # Allowlist of events that should never be sampled
        raw_allow = (os.getenv("LOG_INFO_SAMPLE_ALLOWLIST") or "").strip()
        allowlist = {x.strip() for x in raw_allow.split(",") if x.strip()} or {
            # sensible defaults
            "business_metric",
            "performance",
            "github_sync",
        }
        ev = str(event_dict.get("event") or "")
        if ev in allowlist:
            return event_dict

        try:
            rate = float(os.getenv("LOG_INFO_SAMPLE_RATE", "1.0"))
        except Exception:
            rate = 1.0
        if rate >= 0.999:  # keep all
            return event_dict
        if rate <= 0.0:
            raise structlog.DropEvent

        # Stable per-request sampling using request_id when present
        req_id = str(event_dict.get("request_id") or "")
        if req_id:
            digest = hashlib.sha1(req_id.encode("utf-8")).digest()
            # Convert first 4 bytes to number in [0,1)
            val = int.from_bytes(digest[:4], "big") / float(2**32)
        else:
            val = random.random()
        if val <= rate:
            return event_dict
        raise structlog.DropEvent
    except structlog.DropEvent:
        raise
    except Exception:
        # Fail-open on sampling errors
        return event_dict


def setup_structlog_logging(min_level: str | int = "INFO") -> None:
    level = logging.getLevelName(min_level) if isinstance(min_level, str) else int(min_level)

    if not logging.getLogger().handlers:
        logging.basicConfig(level=level, handlers=[logging.StreamHandler()])
    else:
        logging.getLogger().setLevel(level)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            _add_otel_ids,
            _redact_sensitive,
            _add_schema_version,
            structlog.processors.add_log_level,
            _maybe_sample_info,
            structlog.processors.TimeStamper(fmt="iso"),
            _choose_renderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=False,
    )


def generate_request_id() -> str:
    return str(uuid.uuid4())[:8]


def bind_request_id(request_id: str) -> None:
    try:
        structlog.contextvars.bind_contextvars(request_id=request_id)
    except Exception:
        pass


def emit_event(event: str, severity: str = "info", **fields: Any) -> None:
    logger = structlog.get_logger()
    fields.setdefault("event", event)
    # Keep a lightweight in-memory buffer of recent errors for ChatOps /errors fallback
    try:
        if severity in {"error", "critical"}:
            _RECENT_ERRORS.append({
                "ts": datetime.utcnow().isoformat(),
                "event": str(event),
                "error_code": str(fields.get("error_code") or ""),
                "error": str(fields.get("error") or fields.get("message") or ""),
                "operation": str(fields.get("operation") or ""),
            })
    except Exception:
        pass
    if severity in {"error", "critical"}:
        # best-effort: alert per single error (rate-limited via env)
        try:
            _maybe_alert_single_error(event, fields)
        except Exception:
            pass
        logger.error(**fields)
    elif severity in {"warn", "warning"}:
        logger.warning(**fields)
    elif severity == "anomaly":
        # Structlog does not expose custom levels directly; enrich and log as warning with level hint
        fields["level"] = "ANOMALY"
        logger.warning(**fields)
    else:
        logger.info(**fields)


def init_sentry() -> None:
    global _SENTRY_INIT_DONE
    if _SENTRY_INIT_DONE:
        return
    dsn = os.getenv("SENTRY_DSN")
    if not dsn:
        return
    try:
        import sentry_sdk  # type: ignore
        from sentry_sdk.integrations.logging import LoggingIntegration  # type: ignore

        def _before_send(event, hint):  # type: ignore[no-redef]
            try:
                extra = event.get("extra", {})
                for k in list(extra.keys()):
                    if any(s in k.lower() for s in ("token", "password", "secret", "cookie", "authorization")):
                        extra[k] = "[REDACTED]"
                event["extra"] = extra
            except Exception:
                pass
            return event

        sentry_sdk.init(
            dsn=dsn,
            environment=os.getenv("ENVIRONMENT", os.getenv("ENV", "production")),
            traces_sample_rate=float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.1")),
            profiles_sample_rate=float(os.getenv("SENTRY_PROFILES_SAMPLE_RATE", "0.1")),
            integrations=[LoggingIntegration(level=logging.INFO, event_level=logging.ERROR)],
            before_send=_before_send,
        )
        _SENTRY_INIT_DONE = True
    except Exception:
        return


# --- Simple in-memory errors buffer for ChatOps (/errors) ---
_RECENT_ERRORS: "deque[Dict[str, Any]]" = deque(maxlen=int(os.getenv("RECENT_ERRORS_BUFFER", "200")))


def get_recent_errors(limit: int = 10) -> list[Dict[str, Any]]:
    """Return the most recent error events recorded via emit_event.

    This is a best-effort, in-memory buffer intended for environments without Sentry.
    """
    try:
        if limit <= 0:
            return []
        return list(_RECENT_ERRORS)[-limit:]
    except Exception:
        return []


def emit_anomaly(name: str, **fields: Any) -> None:
    """Utility to emit an ANOMALY-level event consistently across services."""
    try:
        fields = dict(fields or {})
        fields.setdefault("event", str(name))
        emit_event(str(name), severity="anomaly", **fields)
    except Exception:
        return


# --- Optional: alert on each individual error (rate-limited) ---
# Controlled by env ALERT_EACH_ERROR={1|true|yes} and ALERT_EACH_ERROR_COOLDOWN_SECONDS (default 120)
_SINGLE_ERROR_ALERT_LAST_TS: Dict[str, float] = {}
# Re-entrancy guard to avoid recursive loops via internal alert logging/forwarders
_IN_SINGLE_ERROR_ALERT: bool = False
_SINGLE_ERROR_ALERT_LOCK = threading.Lock()


def _cleanup_single_error_keys(now: float, cooldown: int) -> None:
    """Evict stale keys and cap the map size to prevent memory growth.

    - TTL: ALERT_EACH_ERROR_TTL_SECONDS (default: max(cooldown*10, 3600))
    - Max keys: ALERT_EACH_ERROR_MAX_KEYS (default: 1000)
    """
    try:
        try:
            ttl_env = os.getenv("ALERT_EACH_ERROR_TTL_SECONDS")
            if ttl_env:
                ttl = max(0, int(ttl_env))
            else:
                ttl = max(3600, int(cooldown) * 10)
        except Exception:
            ttl = max(3600, int(cooldown or 0) * 10)

        try:
            max_keys = int(os.getenv("ALERT_EACH_ERROR_MAX_KEYS", "1000"))
        except Exception:
            max_keys = 1000

        # TTL eviction
        if ttl > 0 and _SINGLE_ERROR_ALERT_LAST_TS:
            stale_keys = [k for k, ts in list(_SINGLE_ERROR_ALERT_LAST_TS.items()) if (now - float(ts or 0.0)) > ttl]
            for k in stale_keys:
                _SINGLE_ERROR_ALERT_LAST_TS.pop(k, None)

        # Size cap eviction (remove oldest by timestamp)
        while max_keys > 0 and len(_SINGLE_ERROR_ALERT_LAST_TS) > max_keys:
            oldest_key = None
            oldest_ts = None
            for k, ts in _SINGLE_ERROR_ALERT_LAST_TS.items():
                fts = float(ts or 0.0)
                if oldest_ts is None or fts < oldest_ts:
                    oldest_ts = fts
                    oldest_key = k
            if oldest_key is None:
                break
            _SINGLE_ERROR_ALERT_LAST_TS.pop(oldest_key, None)
    except Exception:
        # Best-effort cleanup
        return


def _maybe_alert_single_error(event: str, fields: Dict[str, Any]) -> None:
    try:
        global _IN_SINGLE_ERROR_ALERT
        if _IN_SINGLE_ERROR_ALERT:
            return
        enabled = str(os.getenv("ALERT_EACH_ERROR", "")).lower() in {"1", "true", "yes", "on"}
        if not enabled:
            return

        try:
            cooldown = int(os.getenv("ALERT_EACH_ERROR_COOLDOWN_SECONDS", "120"))
        except Exception:
            cooldown = 120

        # Optional include/exclude filters (comma-separated; supports * wildcard and substring)
        def _parse_patterns(key: str) -> list[str]:
            raw = (os.getenv(key) or "").strip()
            return [p.strip() for p in raw.split(",") if p.strip()]

        include_patterns = _parse_patterns("ALERT_EACH_ERROR_INCLUDE")
        exclude_patterns = _parse_patterns("ALERT_EACH_ERROR_EXCLUDE")

        # Ignore our own fallback marker to prevent recursive loops
        ev_name = str(fields.get("event") or event or "").strip()
        # Ignore our own system/internal events to prevent re-triggering
        if ev_name.lower() in {"single_error_alert_fallback", "internal_alert", "alert_received"}:
            return

        # Build a stable key to rate-limit similar errors
        name = ev_name or "error"
        err_code = str(fields.get("error_code") or "")
        operation = str(fields.get("operation") or "")
        key = "|".join([name, err_code, operation])

        def _matches_any(values: list[str], patterns: list[str]) -> bool:
            if not patterns:
                return False
            for v in values:
                lv = v.lower()
                for pat in patterns:
                    lp = pat.lower()
                    if fnmatch(lv, lp) or (lp in lv):
                        return True
            return False

        # Exclude takes precedence
        if _matches_any([name, err_code, operation], exclude_patterns):
            return
        # If include provided, require a match
        if include_patterns and not _matches_any([name, err_code, operation], include_patterns):
            return

        now = time.time()
        with _SINGLE_ERROR_ALERT_LOCK:
            last = float(_SINGLE_ERROR_ALERT_LAST_TS.get(key, 0.0) or 0.0)
            if (now - last) < max(0, cooldown):
                return
            _SINGLE_ERROR_ALERT_LAST_TS[key] = now
            _cleanup_single_error_keys(now, cooldown)

        # Keep summary privacy-friendly (avoid full exception text)
        rid = str(fields.get("request_id") or "")
        parts = [f"error_code={err_code or 'n/a'}", f"operation={operation or 'n/a'}"]
        if rid:
            parts.append(f"request_id={rid}")
        summary = ", ".join(parts)

        # Defer import to avoid import cycles and make this best-effort
        _IN_SINGLE_ERROR_ALERT = True
        try:
            from internal_alerts import emit_internal_alert  # type: ignore
            # Use non-error severity for the internal log event to avoid re-entry paths,
            # the sink forwarding still occurs for non-critical severities.
            emit_internal_alert(name=name, severity="warn", summary=summary)
        except Exception:
            # As a fallback, log directly without re-entering emit_event to avoid recursion
            try:
                structlog.get_logger().warning(event="single_error_alert_fallback", name=name, summary=summary)
            except Exception:
                pass
        finally:
            _IN_SINGLE_ERROR_ALERT = False
    except Exception:
        return
