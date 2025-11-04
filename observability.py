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
from typing import Any, Dict, Mapping, Optional
import time
from fnmatch import fnmatch
import threading
import random
import hashlib

import structlog
from collections import deque
from datetime import datetime, timezone

try:  # Optional during lightweight environments
    from monitoring.error_signatures import ErrorSignatures, SignatureMatch  # type: ignore
except Exception:  # pragma: no cover
    ErrorSignatures = None  # type: ignore
    SignatureMatch = None  # type: ignore
try:  # Optional OpenTelemetry
    from opentelemetry.trace import get_current_span  # type: ignore
except Exception:  # pragma: no cover
    get_current_span = None  # type: ignore

SCHEMA_VERSION = "1.0"

LOGGER = logging.getLogger(__name__)

# Custom log level for anomalies
ANOMALY_LEVEL_NUM = 35  # between WARNING(30) and ERROR(40)
if not hasattr(logging, "ANOMALY"):
    logging.addLevelName(ANOMALY_LEVEL_NUM, "ANOMALY")

# Guard to avoid double Sentry initialization in multi-import scenarios
_SENTRY_INIT_DONE = False
# Track the DSN used for initialization to allow re-init if DSN changes during tests/runtime
_SENTRY_DSN_USED: str | None = None

_ERROR_SIGNATURES_CACHE: Optional["ErrorSignatures"] = None
_ERROR_SIGNATURES_LOCK = threading.Lock()


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


def _env_true(key: str) -> bool:
    try:
        return str(os.getenv(key, "")).strip().lower() in {"1", "true", "yes", "on"}
    except Exception:
        return False


def _set_sentry_tag(name: str, value: str) -> None:
    if not value:
        return
    try:
        import sentry_sdk  # type: ignore

        sentry_sdk.set_tag(str(name), str(value))  # type: ignore[attr-defined]
    except Exception:
        return


def _hash_identifier(raw: Any) -> str:
    try:
        if raw is None:
            return ""
        text = str(raw).strip()
    except Exception:
        text = ""
    if not text:
        return ""
    try:
        digest = hashlib.sha256(text.encode("utf-8", "ignore")).hexdigest()
    except Exception:
        return ""
    return digest[:16]


def _sanitize_command_identifier(command: Any | None) -> str:
    try:
        raw = "" if command is None else str(command).strip()
    except Exception:
        raw = ""
    if not raw:
        return ""
    sanitized = raw.replace("\n", " ").split()[0]
    if sanitized.startswith("/"):
        sanitized = sanitized[1:]
    if "@" in sanitized:
        sanitized = sanitized.split("@", 1)[0]
    sanitized = sanitized.lower()
    if len(sanitized) > 80:
        sanitized = sanitized[:80]
    return sanitized


def get_observability_context() -> Dict[str, str]:
    try:
        ctx = structlog.contextvars.get_contextvars()
    except Exception:
        return {}
    if not isinstance(ctx, dict):
        return {}
    result: Dict[str, str] = {}
    for key in ("request_id", "command", "user_id", "chat_id"):
        try:
            val = ctx.get(key)
        except Exception:
            val = None
        if val:
            result[str(key)] = str(val)
    return result


def get_request_id(default: str = "") -> str:
    try:
        rid = get_observability_context().get("request_id", "")
    except Exception:
        rid = ""
    return str(rid or default)


def bind_command(command: str | None) -> None:
    sanitized = _sanitize_command_identifier(command)
    if not sanitized:
        return
    try:
        structlog.contextvars.bind_contextvars(command=sanitized)
    except Exception:
        pass
    _set_sentry_tag("command", sanitized)


def bind_user_context(*, user_id: Any | None = None, chat_id: Any | None = None) -> None:
    to_bind: Dict[str, str] = {}
    user_hash = _hash_identifier(user_id)
    if user_hash:
        to_bind["user_id"] = user_hash
        _set_sentry_tag("user_id", user_hash)
    chat_hash = _hash_identifier(chat_id)
    if chat_hash:
        to_bind["chat_id"] = chat_hash
        _set_sentry_tag("chat_id", chat_hash)
    if to_bind:
        try:
            structlog.contextvars.bind_contextvars(**to_bind)
        except Exception:
            pass


def _trace_headers() -> Dict[str, str]:
    try:
        from opentelemetry.propagate import inject  # type: ignore
    except Exception:
        return {}
    carrier: Dict[str, str] = {}
    try:
        inject(carrier)  # type: ignore[call-overload]
    except TypeError:
        try:
            inject(lambda c, k, v: carrier.__setitem__(str(k), str(v)))  # type: ignore[arg-type]
        except Exception:
            return {}
    except Exception:
        return {}
    normalized: Dict[str, str] = {}
    for key, value in carrier.items():
        if not key or not value:
            continue
        normalized[str(key)] = str(value)
    return normalized


def prepare_outgoing_headers(headers: Mapping[str, Any] | None = None) -> Dict[str, str]:
    prepared: Dict[str, str] = {}
    existing_lower: set[str] = set()
    if headers:
        for key, value in headers.items():
            if key is None or value is None:
                continue
            try:
                skey = str(key)
                svalue = str(value)
            except Exception:
                continue
            prepared[skey] = svalue
            existing_lower.add(skey.lower())

    rid = get_request_id("")
    if rid and "x-request-id" not in existing_lower:
        prepared["X-Request-ID"] = rid
        existing_lower.add("x-request-id")

    for key, value in _trace_headers().items():
        lower = key.lower()
        if lower in existing_lower:
            continue
        prepared[key] = value
        existing_lower.add(lower)

    return prepared


def _get_error_signatures() -> Optional["ErrorSignatures"]:
    if ErrorSignatures is None:  # pragma: no cover - optional dependency
        return None
    global _ERROR_SIGNATURES_CACHE
    cache = _ERROR_SIGNATURES_CACHE
    if cache is not None:
        return cache
    with _ERROR_SIGNATURES_LOCK:
        cache = _ERROR_SIGNATURES_CACHE
        if cache is not None:
            return cache
        path = os.getenv("ERROR_SIGNATURES_PATH", "config/error_signatures.yml")
        try:
            cache = ErrorSignatures(path)  # type: ignore[call-arg]
        except Exception:
            cache = None
        _ERROR_SIGNATURES_CACHE = cache
        return cache


def _classify_error_context(fields: Dict[str, Any], fallback: str = "") -> Optional["SignatureMatch"]:
    signatures = _get_error_signatures()
    if signatures is None:
        return None

    candidates: list[str] = []
    seen: set[str] = set()

    def _extend(value: Any) -> None:
        if value is None:
            return
        if isinstance(value, (list, tuple, set)):
            for item in value:
                _extend(item)
            return
        try:
            text = str(value)
        except Exception:
            return
        text = text.strip()
        if not text:
            return
        if text not in seen:
            seen.add(text)
            candidates.append(text)

    if fallback:
        _extend(fallback)

    for key in ("error", "message", "detail", "description", "operation", "event", "status", "response_text"):
        _extend(fields.get(key))

    combined = " | ".join(candidates[:4]) if candidates else ""
    probe_lines = [combined] if combined else []
    probe_lines.extend(candidates)

    for text in probe_lines:
        if not text:
            continue
        try:
            match = signatures.match(text)
        except Exception:
            continue
        if match:
            return match
    return None


def classify_error(fields: Mapping[str, Any] | None = None, fallback: str = "") -> Optional["SignatureMatch"]:
    try:
        payload = dict(fields or {})
    except Exception:
        payload = {}
    try:
        return _classify_error_context(payload, fallback)
    except Exception:
        return None


# Lazy singleton for the log aggregator to avoid repeated construction
_LOG_AGG_SINGLETON = None  # type: ignore[var-annotated]
_LOG_AGG_SHADOW = False


def _mirror_to_log_aggregator(logger, method, event_dict: Dict[str, Any]):
    """Mirror warning/error/anomaly logs into the in-process aggregator.

    Fail-open: never raises; ignores internal/system events to avoid loops.
    Controlled via ENV:
      - LOG_AGGREGATOR_ENABLED={1|true|yes|on}
      - LOG_AGGREGATOR_SHADOW={1|true|yes|on}
      - ERROR_SIGNATURES_PATH, ALERTS_GROUPING_CONFIG
    """
    try:
        if not _env_true("LOG_AGGREGATOR_ENABLED"):
            return event_dict

        level = str(event_dict.get("level") or "").upper()
        if level not in {"WARNING", "ERROR", "CRITICAL", "ANOMALY"}:
            return event_dict

        ev_name = str(event_dict.get("event") or "").strip().lower()
        # Avoid recursion/loops by skipping our own internal/system events
        if ev_name in {"internal_alert", "alert_received", "single_error_alert_fallback", "log_aggregator_shadow_emit"}:
            return event_dict

        parts = [
            str(event_dict.get("event") or ""),
            str(event_dict.get("error") or event_dict.get("message") or ""),
            str(event_dict.get("status_code") or ""),
            str(event_dict.get("route") or ""),
        ]
        line = " ".join(p for p in parts if p).strip()
        if not line:
            return event_dict

        # Lazy create singleton with current ENV configuration
        global _LOG_AGG_SINGLETON, _LOG_AGG_SHADOW
        if _LOG_AGG_SINGLETON is None:
            sig_path = os.getenv("ERROR_SIGNATURES_PATH", "config/error_signatures.yml")
            grp_path = os.getenv("ALERTS_GROUPING_CONFIG", "config/alerts.yml")
            shadow = _env_true("LOG_AGGREGATOR_SHADOW")
            try:
                from monitoring.log_analyzer import LogEventAggregator  # type: ignore
                _LOG_AGG_SINGLETON = LogEventAggregator(
                    signatures_path=str(sig_path),
                    alerts_config_path=str(grp_path),
                    shadow=bool(shadow),
                )
                _LOG_AGG_SHADOW = bool(shadow)
            except Exception:
                # If aggregator unavailable, skip
                return event_dict
        else:
            # If SHADOW env toggled after creation, don't recreate here (tests may reset process)
            pass

        try:
            _LOG_AGG_SINGLETON.analyze_line(line)  # type: ignore[attr-defined]
        except Exception:
            # Never break logging on aggregator errors
            return event_dict
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
            _mirror_to_log_aggregator,
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
    _set_sentry_tag("request_id", request_id)


def emit_event(event: str, severity: str = "info", **fields: Any) -> None:
    logger = structlog.get_logger()
    fields.setdefault("event", event)

    if severity in {"error", "critical"}:
        ctx = get_observability_context()
        request_id = str(fields.get("request_id") or ctx.get("request_id") or "").strip()
        if request_id and "request_id" not in fields:
            fields["request_id"] = request_id

        command_tag = _sanitize_command_identifier(fields.get("command")) or str(ctx.get("command") or "")
        user_tag = _hash_identifier(fields.get("user_id")) or str(ctx.get("user_id") or "")
        chat_tag = _hash_identifier(fields.get("chat_id")) or str(ctx.get("chat_id") or "")
        message_text = str(fields.get("error") or fields.get("message") or event)

        classification = _classify_error_context(fields, message_text)
        if classification is not None:
            category = str(getattr(classification, "category", "") or "").strip()
            signature_id = str(getattr(classification, "signature_id", "") or "").strip()
            summary = str(getattr(classification, "summary", "") or "").strip()
            severity_hint = str(getattr(classification, "severity", "") or "").strip()
            policy_hint = str(getattr(classification, "policy", "") or "").strip()
            metadata = getattr(classification, "metadata", {}) or {}

            if category and "error_category" not in fields:
                fields["error_category"] = category
            if signature_id and "error_signature" not in fields:
                fields["error_signature"] = signature_id
            if summary and "error_summary" not in fields:
                fields["error_summary"] = summary
            if policy_hint and "error_policy" not in fields:
                fields["error_policy"] = policy_hint
            if severity_hint and "error_severity_hint" not in fields:
                fields["error_severity_hint"] = severity_hint
            if metadata and "error_metadata" not in fields:
                safe_meta = {str(k): str(v) for k, v in metadata.items() if v is not None}
                if safe_meta:
                    fields["error_metadata"] = safe_meta
            if category:
                _set_sentry_tag("error_category", category)
            if signature_id:
                _set_sentry_tag("error_signature", signature_id)

        # Keep a lightweight in-memory buffer of recent errors for ChatOps /errors fallback
        try:
            _RECENT_ERRORS.append({
                "ts": datetime.now(timezone.utc).isoformat(),
                "event": str(event),
                "error_code": str(fields.get("error_code") or ""),
                "error": str(fields.get("error") or fields.get("message") or ""),
                "operation": str(fields.get("operation") or ""),
                "error_category": str(fields.get("error_category") or ""),
                "error_signature": str(fields.get("error_signature") or ""),
                "error_policy": str(fields.get("error_policy") or ""),
            })
        except Exception:
            pass

        # best-effort: alert per single error (rate-limited via env)
        try:
            _maybe_alert_single_error(event, fields)
        except Exception:
            pass
        # גשר ישיר ל-Sentry: שליחת הודעה עם תג request_id אם קיים,
        # כדי להבטיח אירוע גם כאשר ה-LoggingIntegration לא קולט structlog
        try:
            import sentry_sdk  # type: ignore

            with sentry_sdk.push_scope() as scope:  # type: ignore[attr-defined]
                for key, value in (
                    ("request_id", request_id),
                    ("command", command_tag),
                    ("user_id", user_tag),
                    ("chat_id", chat_tag),
                ):
                    value_str = str(value).strip()
                    if not value_str:
                        continue
                    try:
                        scope.set_tag(key, value_str)  # type: ignore[attr-defined]
                    except Exception:
                        pass
                sentry_sdk.capture_message(message_text, level="error")  # type: ignore[attr-defined]
        except Exception:
            # Fail-open אם sentry לא זמין
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
    global _SENTRY_INIT_DONE, _SENTRY_DSN_USED
    # Prefer explicit ENV, but fall back to config.SENTRY_DSN when available.
    # This aligns bot/background processes with the webapp which already reads from config.
    dsn = os.getenv("SENTRY_DSN")
    if not dsn:
        try:
            from config import config as _cfg  # type: ignore
            dsn = _cfg.SENTRY_DSN or None  # type: ignore[attr-defined]
        except Exception:
            dsn = None
    if not dsn:
        LOGGER.warning("sentry init skipped: missing DSN", extra={"event": "sentry_init_skipped", "reason": "missing_dsn"})
        return
    # If already initialized with the same DSN, skip. If DSN differs (e.g., in tests), allow re-init.
    if _SENTRY_INIT_DONE and (_SENTRY_DSN_USED == dsn):
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
                # אם request_id קיים ב-extra/contexts – קבע כתג לתשאול קל ב-Sentry
                rid = None
                try:
                    rid = extra.get("request_id") or (event.get("contexts", {}).get("request", {}).get("request_id") if isinstance(event.get("contexts"), dict) else None)
                except Exception:
                    rid = None
                if rid:
                    tags = event.get("tags") or {}
                    tags.setdefault("request_id", str(rid))
                    event["tags"] = tags
            except Exception:
                pass
            return event

        # Resolve environment consistently with fallback to config if ENV/ENVIRONMENT not set
        env_val = os.getenv("ENVIRONMENT") or os.getenv("ENV")
        if not env_val:
            try:
                from config import config as _cfg  # type: ignore
                env_val = getattr(_cfg, "ENVIRONMENT", "production")  # type: ignore[attr-defined]
            except Exception:
                env_val = "production"

        sentry_sdk.init(
            dsn=dsn,
            environment=str(env_val or "production"),
            traces_sample_rate=float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.1")),
            profiles_sample_rate=float(os.getenv("SENTRY_PROFILES_SAMPLE_RATE", "0.1")),
            integrations=[LoggingIntegration(level=logging.INFO, event_level=logging.ERROR)],
            before_send=_before_send,
        )
        _SENTRY_INIT_DONE = True
        _SENTRY_DSN_USED = dsn
    except Exception as exc:
        LOGGER.exception(
            "sentry init failed",
            extra={"event": "sentry_init_failed", "error": str(exc)},
        )
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
            # Emit the internal alert as an error to reflect the source severity.
            # Re-entry is prevented by the _IN_SINGLE_ERROR_ALERT guard above.
            emit_internal_alert(name=name, severity="error", summary=summary)
        except Exception:
            # As a fallback, log directly without re-entering emit_event to avoid recursion
            try:
                # Log fallback as anomaly to reflect auto-handled path
                structlog.get_logger().warning(event="single_error_alert_fallback", level="ANOMALY", name=name, summary=summary)
            except Exception:
                pass
        finally:
            _IN_SINGLE_ERROR_ALERT = False
    except Exception:
        return
