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
import random
import hashlib

import structlog

try:  # Optional OpenTelemetry
    from opentelemetry.trace import get_current_span  # type: ignore
except Exception:  # pragma: no cover
    get_current_span = None  # type: ignore

SCHEMA_VERSION = "1.0"


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
    if severity in {"error", "critical"}:
        logger.error(**fields)
    elif severity in {"warn", "warning"}:
        logger.warning(**fields)
    else:
        logger.info(**fields)


def init_sentry() -> None:
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
    except Exception:
        return
