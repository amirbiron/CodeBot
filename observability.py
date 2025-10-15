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
    if severity == "error":
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
