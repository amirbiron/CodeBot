import asyncio
import atexit
import logging
import os
import secrets
from dataclasses import dataclass
import hashlib
import hmac
import re
from typing import Any, Dict, Optional, Tuple

# Configure structured logging and Sentry as early as possible,
# and install sensitive data redaction on log handlers before Sentry hooks logging.
try:
    from observability import setup_structlog_logging, init_sentry, get_log_level_from_env  # type: ignore
    setup_structlog_logging(get_log_level_from_env("INFO"))
    try:
        from utils import install_sensitive_filter  # type: ignore
        install_sensitive_filter()
    except Exception as e:
        # תיעוד חריגה במקום pass בלבד – זרימה אוטומטית מטופלת כאנומליה
        try:
            from observability import emit_event  # type: ignore
            emit_event(
                "install_sensitive_filter_failed",
                severity="anomaly",
                operation="startup",
                handled=True,
                error=str(e),
            )
        except Exception:
            logging.getLogger(__name__).warning(
                "install_sensitive_filter_failed", extra={"operation": "startup", "handled": True}
            )
    init_sentry()
except Exception as e:
    # Fail-open: אל תחסום עלייה – אך רשום אזהרה במקום pass
    logging.getLogger(__name__).warning(
        "observability_init_failed", extra={"operation": "startup", "handled": True, "error": str(e)}
    )

from aiohttp import web
import json
import time
from services.db_health_service import get_db_health_service
try:
    # Correlation for web requests
    from observability import generate_request_id, bind_request_id  # type: ignore
except Exception:  # pragma: no cover
    def generate_request_id():  # type: ignore
        return ""
    def bind_request_id(_rid: str) -> None:  # type: ignore
        return None
try:
    from metrics import (
        metrics_endpoint_bytes,
        metrics_content_type,
        record_request_outcome,
        record_request_queue_delay,
        note_request_started,
        note_request_finished,
        note_deployment_started,
        note_deployment_shutdown,
    )
except Exception:  # pragma: no cover
    metrics_endpoint_bytes = lambda: b""  # type: ignore
    metrics_content_type = lambda: "text/plain; charset=utf-8"  # type: ignore
    def record_request_outcome(status_code: int, duration_seconds: float, **_kwargs) -> None:  # type: ignore
        return None
    def record_request_queue_delay(method: str, endpoint: str | None, delay_seconds: float, **_kwargs) -> None:  # type: ignore
        return None
    def note_request_started() -> None:  # type: ignore
        return None
    def note_request_finished() -> None:  # type: ignore
        return None
    def note_deployment_started(_summary: str = "Service starting up") -> None:  # type: ignore
        return None
    def note_deployment_shutdown(_summary: str = "Service shutting down") -> None:  # type: ignore
        return None
from html import escape as html_escape

# הערה: לא נייבא את code_sharing כ-reference קבוע כדי לאפשר monkeypatch דינמי בטסטים.
# במקום זאת נפתור את ה-service בזמן ריצה בתוך ה-handler.

# Optional structured logging/event emission and error counter (fail-open)
try:  # type: ignore
    from observability import emit_event  # type: ignore
except Exception:  # pragma: no cover
    def emit_event(event: str, severity: str = "info", **fields):  # type: ignore
        return None
try:
    from metrics import errors_total  # type: ignore
except Exception:  # pragma: no cover
    errors_total = None  # type: ignore

try:
    _AI_REQUEST_TIMEOUT = max(5.0, min(20.0, float(os.getenv("OBS_AI_EXPLAIN_TIMEOUT", "10"))))
except ValueError:
    _AI_REQUEST_TIMEOUT = 10.0
_AI_ROUTE_TOKEN = os.getenv("OBS_AI_EXPLAIN_TOKEN") or os.getenv("AI_EXPLAIN_TOKEN") or ""

logger = logging.getLogger(__name__)

# --- DB Health auth (Token-based) ---
DB_HEALTH_TOKEN = os.getenv("DB_HEALTH_TOKEN", "")


def _constant_time_compare(a: str, b: str) -> bool:
    """השוואה בזמן קבוע למניעת timing attacks.

    משתמש ב-hmac.compare_digest שמבצע השוואה בזמן קבוע
    ללא קיצור-דרך על אי-התאמה ראשונה.
    """
    try:
        return hmac.compare_digest(
            a.encode("utf-8") if isinstance(a, str) else a,
            b.encode("utf-8") if isinstance(b, str) else b,
        )
    except (TypeError, AttributeError):
        return False


@web.middleware
async def db_health_auth_middleware(request: web.Request, handler):
    """Middleware להגנה על endpoints רגישים (DB + Jobs Monitor)."""
    if (
        request.path.startswith("/api/db/")
        or request.path.startswith("/api/jobs")
        or request.path.startswith("/api/debug/")
    ):
        if not DB_HEALTH_TOKEN:
            # אם לא מוגדר token, חסום לגמרי
            return web.json_response({"error": "disabled"}, status=403)

        auth = request.headers.get("Authorization", "") or ""

        # עדיפות ל-header; fallback ל-query param (?token=...) רק ל-endpoint תחזוקה,
        # כדי לא להחליש את מצב האבטחה של /api/db/* ו-/api/jobs/*
        provided_token = ""
        if auth.startswith("Bearer "):
            provided_token = auth[7:]  # הסר את "Bearer "
        else:
            allow_query_token = request.path == "/api/debug/maintenance_cleanup"
            if allow_query_token:
                try:
                    provided_token = str(request.query.get("token") or "")
                except Exception:
                    provided_token = ""

        if not provided_token:
            return web.json_response({"error": "unauthorized"}, status=401)

        # השוואה בזמן קבוע למניעת timing attacks!
        # secrets.compare_digest או hmac.compare_digest
        if not _constant_time_compare(provided_token, DB_HEALTH_TOKEN):
            return web.json_response({"error": "unauthorized"}, status=401)

    return await handler(request)


# AI explain service is optional in minimal envs.
# IMPORTANT: Tests monkeypatch `services.webserver.ai_explain_service`, so keep the attribute always present.
try:  # type: ignore
    from services import ai_explain_service as ai_explain_service  # type: ignore
except Exception:  # pragma: no cover
    class _AiExplainServiceStub:
        class AiExplainError(RuntimeError):
            pass

        async def generate_ai_explanation(self, *_a, **_k):  # type: ignore[no-untyped-def]
            raise self.AiExplainError("service_unavailable")

    ai_explain_service = _AiExplainServiceStub()  # type: ignore

# --- Queue delay (request queueing) instrumentation ---
_QUEUE_DELAY_HEADERS = ("X-Queue-Start", "X-Request-Start")
_QUEUE_DELAY_EVENT_NAME = "access_logs"
_QUEUE_DELAY_EPOCH_RE = re.compile(r"(-?\d+(?:\.\d+)?)")


def _queue_delay_warn_threshold_ms() -> int:
    try:
        return max(0, int(float(os.getenv("QUEUE_DELAY_WARN_MS", "500") or 500)))
    except Exception:
        return 500


def _parse_request_start_to_epoch_seconds(raw: str | None) -> float | None:
    """Parse request start header into epoch seconds (best-effort).

    Supported shapes:
    - "t=1700000000.123"  (seconds, float)
    - "1700000000"        (seconds, int)
    - "1700000000123"     (milliseconds)
    - "1700000000123456"  (microseconds)
    - "1700000000123456789" (nanoseconds)
    """
    try:
        text = str(raw or "").strip()
    except Exception:
        return None
    if not text:
        return None

    # Common prefix: "t=..."
    if text.lower().startswith("t="):
        text = text.split("=", 1)[1].strip()

    m = _QUEUE_DELAY_EPOCH_RE.search(text)
    if not m:
        return None
    token = m.group(1)
    if not token:
        return None

    # Float token => treat as seconds (e.g., "1700000000.123")
    if "." in token:
        try:
            value = float(token)
        except Exception:
            return None
        return value if value > 0 else None

    # Integer token => infer unit from digit length
    try:
        value_int = int(token)
    except Exception:
        return None
    if value_int <= 0:
        return None

    digits = len(token.lstrip("+-"))
    # epoch seconds ~ 10 digits, ms ~ 13, us ~ 16, ns ~ 19
    if digits <= 10:
        return float(value_int)
    if digits <= 13:
        return float(value_int) / 1_000.0
    if digits <= 16:
        return float(value_int) / 1_000_000.0
    return float(value_int) / 1_000_000_000.0


def _compute_queue_delay_ms(headers: Any, *, now_epoch_seconds: float) -> Tuple[int, str | None]:
    """Return (queue_delay_ms, source_header) with fail-open behavior."""
    for header_name in _QUEUE_DELAY_HEADERS:
        try:
            raw = headers.get(header_name)
        except Exception:
            raw = None
        if not raw:
            continue
        ts = _parse_request_start_to_epoch_seconds(raw)
        if ts is None:
            continue
        try:
            delay_ms = int(round(max(0.0, float(now_epoch_seconds - float(ts)) * 1000.0)))
        except Exception:
            delay_ms = 0
        return delay_ms, header_name
    return 0, None


def _bind_queue_delay_context(queue_delay_ms: int, source_header: str | None) -> None:
    """Bind queue delay to structlog contextvars (best-effort)."""
    try:
        import structlog  # type: ignore

        payload: Dict[str, Any] = {"queue_delay": int(queue_delay_ms)}
        if source_header:
            payload["queue_delay_source"] = str(source_header)
        structlog.contextvars.bind_contextvars(**payload)
    except Exception:
        return


# --- Sentry webhook: in-memory de-dup to avoid bursts ---
_SENTRY_DEDUP: dict[str, float] = {}


def _sentry_dedup_window_seconds() -> int:
    try:
        return max(0, int(float(os.getenv("SENTRY_WEBHOOK_DEDUP_WINDOW_SECONDS", "300") or 300)))
    except Exception:
        return 300


def _sentry_secret() -> str:
    # Prefer explicit Sentry webhook secret; fallback to generic webhook secret if set.
    return str(os.getenv("SENTRY_WEBHOOK_SECRET") or os.getenv("WEBHOOK_SECRET") or "").strip()


def _sha256_hmac_hex(secret: str, msg: bytes) -> str:
    try:
        return hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()
    except Exception:
        return ""


def _constant_time_equals(a: str, b: str) -> bool:
    try:
        return hmac.compare_digest(str(a or ""), str(b or ""))
    except Exception:
        return False


def _verify_sentry_webhook(request: web.Request, body: bytes) -> bool:
    """Best-effort verification for Sentry webhook calls.

    Supported modes:
    - HMAC signature headers (preferred when provided by Sentry)
    - Bearer token / query param token fallback (for setups where headers are not configurable)
    """
    secret = _sentry_secret()
    if not secret:
        # Explicit opt-in: if no secret configured, allow (fail-open).
        return True

    # 1) Token fallback: Authorization: Bearer <secret> or ?token=<secret>
    try:
        auth = str(request.headers.get("Authorization") or "").strip()
        if auth.lower().startswith("bearer "):
            token = auth.split(" ", 1)[1].strip()
            if token and _constant_time_equals(token, secret):
                return True
    except Exception:
        pass
    try:
        token = str(request.query.get("token") or "").strip()
        if token and _constant_time_equals(token, secret):
            return True
    except Exception:
        pass

    # 2) HMAC signature headers (Sentry varies between integrations)
    # Common headers:
    # - X-Sentry-Hook-Signature / X-Sentry-Signature
    # - X-Sentry-Hook-Timestamp / X-Sentry-Timestamp
    try:
        sig = (
            request.headers.get("X-Sentry-Hook-Signature")
            or request.headers.get("X-Sentry-Signature")
            or request.headers.get("Sentry-Hook-Signature")
            or request.headers.get("Sentry-Signature")
            or ""
        )
        sig = str(sig or "").strip()
    except Exception:
        sig = ""
    try:
        ts = (
            request.headers.get("X-Sentry-Hook-Timestamp")
            or request.headers.get("X-Sentry-Timestamp")
            or request.headers.get("Sentry-Hook-Timestamp")
            or request.headers.get("Sentry-Timestamp")
            or ""
        )
        ts = str(ts or "").strip()
    except Exception:
        ts = ""

    if not sig:
        return False

    # Accept both common signing shapes:
    # - HMAC(secret, body)
    # - HMAC(secret, f"{timestamp}.{body}")
    try:
        candidate_a = _sha256_hmac_hex(secret, body)
        if candidate_a and _constant_time_equals(candidate_a, sig):
            return True
    except Exception:
        pass
    if ts:
        try:
            candidate_b = _sha256_hmac_hex(secret, ts.encode("utf-8") + b"." + body)
            if candidate_b and _constant_time_equals(candidate_b, sig):
                return True
        except Exception:
            pass
    return False


@dataclass
class _SentryAlert:
    name: str
    summary: str
    severity: str
    dedup_key: str
    details: Dict[str, Any]


def _map_sentry_level_to_severity(level: str | None) -> str:
    v = str(level or "").strip().lower()
    if v in {"fatal", "critical"}:
        return "critical"
    if v in {"error", "err"}:
        return "error"
    if v in {"warning", "warn"}:
        return "warning"
    if v in {"info"}:
        return "info"
    # Unknown -> keep it visible but not noisy
    return "warning"


def _truncate(text: str, limit: int) -> str:
    try:
        s = str(text or "").strip()
    except Exception:
        s = ""
    if limit and len(s) > limit:
        return s[: max(0, limit - 1)] + "…"
    return s


def _extract_sentry_alert(payload: Any) -> _SentryAlert | None:
    if not isinstance(payload, dict) or not payload:
        return None

    action = str(payload.get("action") or payload.get("trigger") or payload.get("status") or "").strip().lower()
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    issue = (
        data.get("issue") if isinstance(data.get("issue"), dict)
        else (payload.get("issue") if isinstance(payload.get("issue"), dict) else {})
    )
    event = (
        data.get("event") if isinstance(data.get("event"), dict)
        else (payload.get("event") if isinstance(payload.get("event"), dict) else {})
    )
    project = (
        data.get("project") if isinstance(data.get("project"), dict)
        else (payload.get("project") if isinstance(payload.get("project"), dict) else {})
    )

    title = (
        payload.get("title")
        or issue.get("title")
        or event.get("title")
        or event.get("message")
        or payload.get("message")
        or ""
    )
    title_s = _truncate(str(title), 220)

    issue_id = str(issue.get("id") or payload.get("issue_id") or "").strip()
    short_id = str(issue.get("shortId") or issue.get("short_id") or payload.get("shortId") or payload.get("short_id") or "").strip()
    permalink = str(
        issue.get("permalink")
        or payload.get("permalink")
        or event.get("permalink")
        or payload.get("url")
        or ""
    ).strip()
    project_slug = str(project.get("slug") or payload.get("project_slug") or payload.get("project") or "").strip()
    level = str(event.get("level") or payload.get("level") or payload.get("level_name") or "").strip().lower() or None
    severity = _map_sentry_level_to_severity(level)

    # Drop resolved notifications by default (still record as info if they come through).
    if action in {"resolved", "resolved_issue", "issue_resolved"}:
        severity = "info"

    # Heuristic: some Sentry issues are background/maintenance noise (e.g. pymongo pool housekeeping).
    # Downgrade them to warning so they don't look like user-facing errors in Telegram/Observability.
    try:
        lowered_title = str(title_s or "").lower()
        # NOTE: do not override "resolved" notifications; they should remain informational,
        # otherwise we emit new warning-level alerts and create new dedup keys.
        if (
            severity != "info"
            and ("_operationcancelled" in lowered_title or "operation cancelled" in lowered_title)
        ):
            severity = "warning"
    except Exception:
        pass

    # Stable identifiers for dedup
    primary_id = issue_id or short_id or str(event.get("id") or event.get("event_id") or "").strip()
    dedup_key = "|".join([x for x in [primary_id, project_slug, severity, action] if x])
    if not dedup_key:
        # Worst-case fallback: title bucket
        dedup_key = f"title:{title_s[:80]}"

    display_id = short_id or (issue_id[:8] if issue_id else "issue")
    name = _truncate(f"Sentry: {display_id}", 128)

    # Important: order matters for UI display. Put alert_type and Sentry IDs first.
    details: Dict[str, Any] = {
        "alert_type": "sentry_issue",
        "sentry_issue_id": issue_id or None,
        "sentry_short_id": short_id or None,
        "sentry_permalink": permalink or None,
        "sentry_event_id": str(event.get("id") or event.get("event_id") or "").strip() or None,
        "project": project_slug or None,
        "level": level or None,
        "action": action or None,
        "logger": str(event.get("logger") or payload.get("logger") or "").strip() or None,
        "culprit": str(issue.get("culprit") or event.get("culprit") or "").strip() or None,
        "environment": str(event.get("environment") or payload.get("environment") or "").strip() or None,
    }
    # Remove None values to keep storage clean
    details = {k: v for k, v in details.items() if v not in (None, "")}

    summary = title_s or "Sentry alert"
    return _SentryAlert(name=name, summary=summary, severity=severity, dedup_key=dedup_key, details=details)


def _should_emit_sentry_alert(dedup_key: str) -> bool:
    window = _sentry_dedup_window_seconds()
    if window <= 0:
        return True
    now = time.time()
    # Lazy cleanup of old entries (best-effort)
    try:
        cutoff = now - float(window)
        for k, ts in list(_SENTRY_DEDUP.items()):
            if ts < cutoff:
                _SENTRY_DEDUP.pop(k, None)
    except Exception:
        pass
    last = _SENTRY_DEDUP.get(dedup_key)
    if last is not None and (now - float(last)) < float(window):
        return False
    _SENTRY_DEDUP[dedup_key] = now
    return True


def create_app() -> web.Application:
    # הוסף middleware שמייצר ומקשר request_id לכל בקשה נכנסת
    @web.middleware
    async def _request_id_mw(request: web.Request, handler):
        req_id = generate_request_id() or ""
        start = time.perf_counter()
        wall_now = time.time()
        handler_name = getattr(handler, "__name__", None) or handler.__class__.__name__
        queue_delay_ms, queue_delay_source = _compute_queue_delay_ms(
            request.headers, now_epoch_seconds=float(wall_now)
        )
        _bind_queue_delay_context(queue_delay_ms, queue_delay_source)
        try:
            note_request_started()
        except Exception:
            pass
        try:
            bind_request_id(req_id)
        except Exception as e:
            try:
                emit_event(
                    "bind_request_id_failed",
                    severity="anomaly",
                    operation="request_id_middleware",
                    handled=True,
                    request_id=req_id,
                    error=str(e),
                )
            except Exception:
                logging.getLogger(__name__).warning(
                    "bind_request_id_failed", extra={"operation": "request_id_middleware", "handled": True}
                )
        # המשך עיבוד
        try:
            response = await handler(request)
        finally:
            try:
                note_request_finished()
            except Exception:
                pass
        try:
            if hasattr(response, "headers") and req_id:
                response.headers["X-Request-ID"] = req_id
        except Exception as e:
            try:
                emit_event(
                    "set_request_id_header_failed",
                    severity="anomaly",
                    operation="request_id_middleware",
                    handled=True,
                    request_id=req_id,
                    error=str(e),
                )
            except Exception:
                logging.getLogger(__name__).warning(
                    "set_request_id_header_failed", extra={"operation": "request_id_middleware", "handled": True}
                )
        # Update unified request metrics (best-effort)
        try:
            duration = max(0.0, float(time.perf_counter() - start))
            status = int(getattr(response, "status", 0) or 0)
            route_name = None
            try:
                route = getattr(request.match_info, "route", None)
                route_name = getattr(route, "name", None)
            except Exception:
                route_name = None
            path_label = getattr(request, "path", "")
            method_label = getattr(request, "method", "GET")
            handler_label = route_name or handler_name or path_label
            record_request_outcome(
                status,
                duration,
                source="aiohttp",
                handler=handler_label,
                path=path_label,
                method=method_label,
                cache_hit=None,
            )
            try:
                record_request_queue_delay(
                    method_label,
                    route_name or handler_name or path_label,
                    float(queue_delay_ms) / 1000.0,
                )
            except Exception:
                pass
            # Structured access log (best-effort)
            try:
                access_fields: Dict[str, Any] = {
                    "request_id": req_id,
                    "method": method_label,
                    "path": path_label,
                    "handler": handler_label,
                    "status_code": status,
                    "duration_ms": int(duration * 1000),
                    "queue_delay": int(queue_delay_ms),
                }
                if queue_delay_source:
                    access_fields["queue_delay_source"] = str(queue_delay_source)
                # Silence noisy monitoring endpoints when request is "ok".
                # - For health/metrics: skip only successes (<400) but keep 4xx/5xx.
                # - For favicon: also skip 404/4xx noise, keep 5xx.
                # - For root availability probes: skip HEAD / when "ok" (<400), but keep 4xx/5xx.
                silent_paths = {"/metrics", "/health", "/healthz", "/favicon.ico"}
                is_silent_path = path_label in silent_paths
                is_root_check = (path_label == "/" and str(method_label).upper() == "HEAD")
                should_silence = False
                if is_silent_path or is_root_check:
                    ok_threshold = 500 if path_label == "/favicon.ico" else 400
                    should_silence = int(status) < int(ok_threshold)
                if not should_silence:
                    emit_event(_QUEUE_DELAY_EVENT_NAME, severity="info", **access_fields)
            except Exception:
                pass
            # Warning when queue delay is suspiciously high
            try:
                threshold = _queue_delay_warn_threshold_ms()
                if threshold > 0 and int(queue_delay_ms) >= int(threshold):
                    warn_fields: Dict[str, Any] = {
                        "request_id": req_id,
                        "queue_delay": int(queue_delay_ms),
                        "threshold_ms": int(threshold),
                        "method": method_label,
                        "path": path_label,
                        "handler": handler_label,
                    }
                    if queue_delay_source:
                        warn_fields["queue_delay_source"] = str(queue_delay_source)
                    emit_event("queue_delay_high", severity="warning", **warn_fields)
            except Exception:
                pass
        except Exception as e:
            try:
                emit_event(
                    "record_request_outcome_failed",
                    severity="anomaly",
                    operation="request_metrics",
                    handled=True,
                    request_id=req_id,
                    error=str(e),
                )
            except Exception:
                logging.getLogger(__name__).warning(
                    "record_request_outcome_failed", extra={"operation": "request_metrics", "handled": True}
                )
        return response

    app = web.Application(middlewares=[_request_id_mw, db_health_auth_middleware])

    # --- Query Performance Profiler routes (best-effort) ---
    try:
        profiler_enabled = str(os.getenv("PROFILER_ENABLED", "true") or "").strip().lower() in {"1", "true", "yes", "y", "on"}
    except Exception:
        profiler_enabled = True
    if profiler_enabled:
        try:
            from database import db_manager  # type: ignore
            from services.query_profiler_service import PersistentQueryProfilerService  # type: ignore
            from handlers.profiler_handler import setup_profiler_routes  # type: ignore

            try:
                threshold_ms = int(float(os.getenv("PROFILER_SLOW_THRESHOLD_MS", "100") or 100))
            except Exception:
                threshold_ms = 100
            profiler_service = PersistentQueryProfilerService(db_manager, slow_threshold_ms=threshold_ms)
            app["profiler_service"] = profiler_service
            setup_profiler_routes(app, profiler_service)
        except Exception as e:
            try:
                emit_event(
                    "profiler_routes_init_failed",
                    severity="warn",
                    handled=True,
                    error=str(e),
                )
            except Exception:
                pass

    async def on_startup(app: web.Application):
        """אתחול שירותים בעליית השרת."""
        try:
            # אתחול מוקדם של DB Health Service
            svc = await get_db_health_service()
            app["db_health_service"] = svc
            logger.info("DB Health Service initialized")
        except Exception as e:
            logger.warning(f"DB Health Service init failed: {e}")

    async def on_cleanup(app: web.Application):
        """ניקוי משאבים בכיבוי השרת."""
        svc = app.get("db_health_service")
        if svc and hasattr(svc, "close"):
            await svc.close()

    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)

    async def health(request: web.Request) -> web.Response:
        return web.json_response({"status": "ok"})

    async def metrics_view(request: web.Request) -> web.Response:
        try:
            payload = metrics_endpoint_bytes()
            return web.Response(body=payload, headers={"Content-Type": metrics_content_type()})
        except Exception as e:
            logger.error(f"metrics_view error: {e}")
            # העדף emit_event שהוחלף במודול זה (monkeypatch), ואם לא – פתור דינמית את observability.emit_event
            try:
                chosen_emit = emit_event  # type: ignore
                try:
                    import sys as _sys
                    obs = _sys.modules.get("observability")
                    obs_emit = getattr(obs, "emit_event", None) if obs is not None else None
                except Exception:
                    obs_emit = None
                # אם emit_event במודול הזה אינו מגיע מ-observability (סימן ל-monkeypatch) – העדף אותו
                # אחרת, אפשר להשתמש ב-observability.emit_event בזמן ריצה כדי לכבד monkeypatch שבוצע לאחר import
                if not callable(chosen_emit) or getattr(chosen_emit, "__module__", "") == "observability":
                    if callable(obs_emit):
                        chosen_emit = obs_emit  # type: ignore
                chosen_emit(
                    "metrics_view_error",
                    severity="error",
                    error_code="E_METRICS_VIEW",
                    error=str(e),
                )  # type: ignore
            except Exception:
                pass
            try:
                if errors_total is not None:
                    errors_total.labels(code="E_METRICS_VIEW").inc()
            except Exception:
                pass
            return web.Response(status=500, text="metrics error")

    async def alerts_view(request: web.Request) -> web.Response:
        """Alertmanager webhook endpoint: forwards alerts and logs them.

        Expected payload schema: {"alerts": [...]} or a single alert object.
        """
        try:
            raw = await request.text()
            data = json.loads(raw) if raw else {}
        except Exception as e:
            try:
                # פנה ל-emit_event שהוחדר למודול זה (מאפשר monkeypatch בטסטים)
                emit_event("alerts_parse_error", severity="warn", error_code="E_ALERTS_PARSE", error=str(e))  # type: ignore
            except Exception:
                pass
            try:
                if errors_total is not None:
                    errors_total.labels(code="E_ALERTS_PARSE").inc()
            except Exception:
                pass
            return web.Response(status=400, text="invalid json")

        # Normalize to list of alerts
        alerts = []
        if isinstance(data, dict) and "alerts" in data and isinstance(data["alerts"], list):
            alerts = data["alerts"]
        elif isinstance(data, dict) and data:
            alerts = [data]

        # Forward via helper (Slack/Telegram) and emit events
        try:
            # Log only a lightweight counter at info level here; per-alert severities
            # are handled inside alert_forwarder.forward_alerts.
            emit_event("alert_received", severity="info", count=int(len(alerts)))
        except Exception:
            pass
        try:
            from alert_forwarder import forward_alerts  # type: ignore
            forward_alerts(alerts)
        except Exception as e:
            # Soft-fail; דווח כאנומליה מטופלת
            try:
                emit_event(
                    "alerts_forward_failed",
                    severity="anomaly",
                    operation="alerts_forward",
                    handled=True,
                    error=str(e),
                )
            except Exception:
                logging.getLogger(__name__).warning(
                    "alerts_forward_failed", extra={"operation": "alerts_forward", "handled": True}
                )

        return web.json_response({"status": "ok", "forwarded": len(alerts)})

    async def alerts_get_view(request: web.Request) -> web.Response:
        """Return recent internal alerts as JSON for ChatOps and dashboards.

        Query params:
        - limit: int (default 20)
        """
        try:
            limit = int(request.query.get("limit", "20"))
        except Exception:
            limit = 20
        try:
            from internal_alerts import get_recent_alerts  # type: ignore
            items = get_recent_alerts(limit=max(1, min(200, limit))) or []
        except Exception:
            items = []
        return web.json_response({"alerts": items})

    async def sentry_webhook_view(request: web.Request) -> web.Response:
        """Sentry webhook endpoint: converts Sentry alerts into internal alerts.

        - Emits internal_alerts.emit_internal_alert(...) so Telegram forwarding works.
        - Persists to Mongo via monitoring.alerts_storage through internal_alerts (best-effort).
        """
        try:
            body = await request.read()
        except Exception:
            body = b""

        if not _verify_sentry_webhook(request, body):
            try:
                emit_event("sentry_webhook_unauthorized", severity="warn", handled=True)  # type: ignore
            except Exception:
                pass
            return web.json_response({"ok": False, "error": "unauthorized"}, status=401)

        try:
            raw_text = body.decode("utf-8", errors="replace") if body else ""
            payload = json.loads(raw_text) if raw_text else {}
        except Exception as e:
            try:
                emit_event(
                    "sentry_webhook_parse_error",
                    severity="warn",
                    handled=True,
                    error=str(e),
                )  # type: ignore
            except Exception:
                pass
            return web.json_response({"ok": False, "error": "invalid_json"}, status=400)

        alert = _extract_sentry_alert(payload)
        if alert is None:
            try:
                emit_event("sentry_webhook_ignored", severity="info", handled=True, reason="empty_payload")  # type: ignore
            except Exception:
                pass
            return web.json_response({"ok": True, "ignored": True})

        should_emit = _should_emit_sentry_alert(alert.dedup_key)
        try:
            emit_event(
                "sentry_webhook_received",
                severity="info",
                handled=True,
                dedup=not should_emit,
                sentry_short_id=str(alert.details.get("sentry_short_id") or ""),
                project=str(alert.details.get("project") or ""),
                level=str(alert.details.get("level") or ""),
                action=str(alert.details.get("action") or ""),
            )  # type: ignore
        except Exception:
            pass

        if should_emit:
            try:
                from internal_alerts import emit_internal_alert  # type: ignore

                emit_internal_alert(
                    name=alert.name,
                    severity=str(alert.severity),
                    summary=str(alert.summary),
                    **(alert.details or {}),
                )
            except Exception as e:
                try:
                    emit_event(
                        "sentry_webhook_emit_failed",
                        severity="anomaly",
                        handled=True,
                        error=str(e),
                    )  # type: ignore
                except Exception:
                    pass
                return web.json_response({"ok": False, "error": "emit_failed"}, status=500)

        return web.json_response({"ok": True, "deduped": (not should_emit)})

    async def incidents_get_view(request: web.Request) -> web.Response:
        """Return incident history as JSON.

        Query params:
        - limit: int (default 20)
        """
        try:
            limit = int(request.query.get("limit", "20"))
        except Exception:
            limit = 20
        try:
            from remediation_manager import get_incidents  # type: ignore
            items = get_incidents(limit=max(1, min(200, limit))) or []
        except Exception:
            items = []
        return web.json_response({"incidents": items})

    async def ai_explain_view(request: web.Request) -> web.Response:
        start = time.perf_counter()
        req_id = request.headers.get("X-Request-ID") or ""

        if _AI_ROUTE_TOKEN:
            auth_header = request.headers.get("Authorization", "").strip()
            expected_header = f"Bearer {_AI_ROUTE_TOKEN}"
            try:
                valid_token = secrets.compare_digest(auth_header, expected_header)
            except Exception:
                valid_token = False
            if not valid_token:
                return web.json_response(
                    {
                        "error": "unauthorized",
                        "message": "missing or invalid bearer token",
                    },
                    status=401,
                )
        try:
            payload = await request.json()
        except json.JSONDecodeError:
            return web.json_response({"error": "bad_request", "message": "invalid json"}, status=400)
        except Exception:
            return web.json_response({"error": "bad_request", "message": "invalid body"}, status=400)

        context = payload.get("context")
        expected_sections = payload.get("expected_sections")
        if not isinstance(context, dict):
            return web.json_response(
                {"error": "invalid_context", "message": "context must be an object"},
                status=400,
            )
        if expected_sections is not None and not isinstance(expected_sections, list):
            expected_sections = None

        alert_uid = str(context.get("alert_uid") or "")
        try:
            explanation = await asyncio.wait_for(
                ai_explain_service.generate_ai_explanation(
                    context,
                    expected_sections=expected_sections,
                    request_id=req_id,
                ),
                timeout=_AI_REQUEST_TIMEOUT,
            )
        except asyncio.TimeoutError:
            duration = time.perf_counter() - start
            try:
                emit_event(
                    "ai_explain_request_failure",
                    severity="error",
                    alert_uid=alert_uid,
                    duration_ms=int(duration * 1000),
                    error_code="handler_timeout",
                    handled=True,
                )
            except Exception:
                pass
            return web.json_response(
                {
                    "error": "timeout",
                    "message": "פניית ה-AI חרגה מחלון הזמן",
                },
                status=504,
            )
        except ai_explain_service.AiExplainError as exc:
            duration = time.perf_counter() - start
            error_code = str(exc) or "provider_error"
            if error_code == "invalid_context":
                status = 400
                message = "מבנה ההקשר אינו תקין"
            elif error_code == "anthropic_api_key_missing":
                status = 503
                message = "השירות לא הוגדר (חסר מפתח Anthropic)"
            elif error_code in {"service_unavailable", "ai_explain_service_unavailable"}:
                status = 503
                message = "שירות ההסבר אינו זמין"
            else:
                status = 502
                message = "ספק ה-AI לא הצליח להחזיר תשובה"
            try:
                emit_event(
                    "ai_explain_request_failure",
                    severity="error",
                    alert_uid=alert_uid,
                    duration_ms=int(duration * 1000),
                    error_code=error_code,
                    handled=status < 500,
                )
            except Exception:
                pass
            return web.json_response({"error": error_code, "message": message}, status=status)
        except Exception as exc:
            duration = time.perf_counter() - start
            try:
                emit_event(
                    "ai_explain_request_failure",
                    severity="error",
                    alert_uid=alert_uid,
                    duration_ms=int(duration * 1000),
                    error=str(exc),
                    handled=False,
                )
            except Exception:
                pass
            logger.exception("ai_explain_handler_failed")
            return web.json_response(
                {"error": "internal_error", "message": "שגיאה בשירות ההסבר"},
                status=500,
            )

        duration = time.perf_counter() - start
        try:
            emit_event(
                "ai_explain_request_success",
                severity="info",
                alert_uid=alert_uid,
                duration_ms=int(duration * 1000),
                provider=explanation.get("provider"),
            )
        except Exception:
            pass
        return web.json_response(explanation)

    async def share_view(request: web.Request) -> web.Response:
        share_id = request.match_info.get("share_id", "")
        try:
            # 해결 תלויות בזמן ריצה כדי לאפשר monkeypatch ב-tests:
            try:
                import importlib
                integ = importlib.import_module("integrations")
                _code_sharing = getattr(integ, "code_sharing")
            except Exception:
                from integrations import code_sharing as _code_sharing  # type: ignore
            data = _code_sharing.get_internal_share(share_id)
        except Exception as e:
            logger.error(f"share_view error: {e}")
            try:
                # דווח אירוע מובנה על שגיאה בהצגת שיתוף
                # הערה: משתמש ב-emit_event של המודול כדי לאפשר monkeypatch בטסטים
                emit_event("share_view_error", severity="error", error_code="E_SHARE_VIEW", share_id=str(share_id), error=str(e))
            except Exception:
                pass
            try:
                if errors_total is not None:
                    errors_total.labels(code="E_SHARE_VIEW").inc()
            except Exception:
                pass
            data = None
        if not data:
            # החזר 404 וגם דווח אירוע מובנה לצורכי ניטור
            try:
                # הערה: משתמש ב-emit_event של המודול כדי לאפשר monkeypatch בטסטים
                emit_event("share_view_not_found", severity="warn", share_id=str(share_id))
            except Exception:
                pass
            return web.Response(status=404, text="Share not found or expired")

        # החזר HTML פשוט לצפייה נוחה
        code = data.get("code", "")
        file_name = data.get("file_name", "snippet.txt")
        language = data.get("language", "text")
        try:
            emit_event("share_view_success", severity="info", share_id=str(share_id), file_name=str(file_name), language=str(language))
        except Exception:
            pass
        html = f"""
<!DOCTYPE html>
<html lang="he">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Share: {file_name}</title>
  <style>
    body {{ font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace; margin: 24px; }}
    pre {{ white-space: pre-wrap; word-wrap: break-word; background: #0d1117; color: #c9d1d9; padding: 16px; border-radius: 8px; overflow: auto; }}
    h1 {{ font-size: 18px; }}
    .meta {{ color: #57606a; margin-bottom: 8px; }}
    a {{ color: #58a6ff; }}
  </style>
  </head>
  <body>
    <h1>📄 {file_name}</h1>
    <div class="meta">שפה: {language}</div>
    <pre>{html_escape(code)}</pre>
  </body>
</html>
"""
        return web.Response(text=html, content_type="text/html")

    async def db_health_pool_view(request: web.Request) -> web.Response:
        """GET /api/db/pool - מצב Connection Pool."""
        try:
            # await לקבלת ה-service (יכול להיות async init)
            svc = await get_db_health_service()
            # await לקריאה ל-MongoDB (Motor או thread pool)
            pool = await svc.get_pool_status()
            return web.json_response(pool.to_dict())
        except Exception as e:
            logger.error(f"db_health_pool error: {e}")
            return web.json_response({"error": "failed", "message": "internal_error"}, status=500)

    async def db_health_ops_view(request: web.Request) -> web.Response:
        """GET /api/db/ops - פעולות איטיות פעילות."""
        try:
            threshold = int(request.query.get("threshold_ms", "1000"))
            include_system = request.query.get("include_system", "").lower() == "true"

            svc = await get_db_health_service()
            # await חובה! - הקריאה ל-MongoDB היא אסינכרונית
            ops = await svc.get_current_operations(
                threshold_ms=threshold,
                include_system=include_system,
            )

            return web.json_response(
                {
                    "count": len(ops),
                    "threshold_ms": threshold,
                    "operations": [op.to_dict() for op in ops],
                }
            )
        except Exception as e:
            logger.error(f"db_health_ops error: {e}")
            return web.json_response({"error": "failed", "message": "internal_error"}, status=500)

    async def db_health_collections_view(request: web.Request) -> web.Response:
        """GET /api/db/collections - סטטיסטיקות collections."""
        try:
            collection = request.query.get("collection")

            svc = await get_db_health_service()
            # await חובה! - collStats יכול לקחת זמן
            stats = await svc.get_collection_stats(collection_name=collection)

            return web.json_response(
                {
                    "count": len(stats),
                    "collections": [s.to_dict() for s in stats],
                }
            )
        except Exception as e:
            logger.error(f"db_health_collections error: {e}")
            return web.json_response({"error": "failed", "message": "internal_error"}, status=500)

    async def db_health_summary_view(request: web.Request) -> web.Response:
        """GET /api/db/health - סיכום בריאות כללי."""
        try:
            svc = await get_db_health_service()
            # await חובה!
            summary = await svc.get_health_summary()
            return web.json_response(summary)
        except Exception as e:
            logger.error(f"db_health_summary error: {e}")
            return web.json_response({"error": "failed", "message": "internal_error"}, status=500)

    async def maintenance_cleanup_view(request: web.Request) -> web.Response:
        """GET /api/debug/maintenance_cleanup

        Endpoint תחזוקה חד-פעמי (DB):
        - איפוס קולקציות לוגים: slow_queries_log, service_metrics
        - יצירת TTL לקולקציות לוגים (מחיקה אוטומטית בעתיד)
        - ניקוי אינדקסים ב-code_snippets: השארה של אינדקסים קריטיים בלבד.

        ⚠️ מוגן ע"י db_health_auth_middleware (Bearer token).
        """
        from services.db_provider import get_db

        def _run_cleanup() -> dict:
            preview = str(request.query.get("preview", "") or "").lower() in {"1", "true", "yes", "on"}
            db = get_db()

            # --- collections to purge ---
            try:
                slow_queries_coll = db.slow_queries_log
            except Exception:
                slow_queries_coll = None
            try:
                service_metrics_coll = db.service_metrics
            except Exception:
                service_metrics_coll = None
            try:
                code_snippets_coll = db.code_snippets
            except Exception:
                code_snippets_coll = None

            # Detect fail-open/noop db
            if not getattr(slow_queries_coll, "delete_many", None) or not getattr(service_metrics_coll, "delete_many", None):
                raise RuntimeError("db_unavailable_or_no_delete_many")
            if not getattr(code_snippets_coll, "index_information", None) or not getattr(code_snippets_coll, "drop_index", None):
                raise RuntimeError("db_unavailable_or_no_index_management")

            deleted_slow = 0
            deleted_metrics = 0
            if not preview:
                slow_res = slow_queries_coll.delete_many({})
                metrics_res = service_metrics_coll.delete_many({})
                deleted_slow = int(getattr(slow_res, "deleted_count", 0) or 0)
                deleted_metrics = int(getattr(metrics_res, "deleted_count", 0) or 0)

            # --- TTL indexes (permanent cleanup) ---
            def _ensure_ttl_index(coll: Any, *, field: str, expire_seconds: int, index_name: str) -> dict:
                """Ensure TTL index exists with requested expireAfterSeconds (best-effort)."""
                info_before = {}
                try:
                    info_before = coll.index_information() or {}
                except Exception:
                    info_before = {}

                existing_meta = info_before.get(index_name) if isinstance(info_before, dict) else None
                if isinstance(existing_meta, dict):
                    try:
                        existing_expire = existing_meta.get("expireAfterSeconds")
                        existing_key = existing_meta.get("key")
                        if (
                            existing_expire == int(expire_seconds)
                            and existing_key == [(field, 1)]
                        ):
                            return {
                                "name": index_name,
                                "field": field,
                                "expireAfterSeconds": int(expire_seconds),
                                "status": "exists",
                            }
                    except Exception:
                        pass

                # Try drop conflicting TTL index with the same name
                if not preview:
                    try:
                        coll.drop_index(index_name)
                    except Exception:
                        pass

                created_name = None
                if not preview:
                    try:
                        created_name = coll.create_index(
                            [(field, 1)],
                            name=index_name,
                            expireAfterSeconds=int(expire_seconds),
                            background=True,
                        )
                    except Exception as e:
                        # Best-effort: report error and continue
                        return {
                            "name": index_name,
                            "field": field,
                            "expireAfterSeconds": int(expire_seconds),
                            "status": "error",
                            "error": str(e),
                        }

                return {
                    "name": str(created_name or index_name),
                    "field": field,
                    "expireAfterSeconds": int(expire_seconds),
                    "status": "planned" if preview else "created",
                }

            ttl_results: dict[str, Any] = {
                "slow_queries_log": _ensure_ttl_index(
                    slow_queries_coll,
                    field="timestamp",
                    expire_seconds=604800,  # 7 days
                    index_name="ttl_cleanup",
                ),
                # service_metrics uses "ts" in code, but we'll also create a "timestamp" TTL for safety/backward-compat
                "service_metrics_ts": _ensure_ttl_index(
                    service_metrics_coll,
                    field="ts",
                    expire_seconds=86400,  # 24 hours
                    index_name="ttl_cleanup_ts",
                ),
                "service_metrics_timestamp": _ensure_ttl_index(
                    service_metrics_coll,
                    field="timestamp",
                    expire_seconds=86400,  # 24 hours
                    index_name="ttl_cleanup",
                ),
            }

            # --- index cleanup (code_snippets) ---
            try:
                idx_info = code_snippets_coll.index_information() or {}
            except Exception:
                idx_info = {}

            indexes_before = sorted([str(k) for k in idx_info.keys()])
            indexes_before_details: dict[str, dict] = {}
            for k, meta in (idx_info or {}).items():
                if not isinstance(meta, dict):
                    continue
                name = str(k)
                # keep response compact but useful for review (especially text indexes)
                indexes_before_details[name] = {
                    "key": meta.get("key"),
                    "unique": bool(meta.get("unique")) if "unique" in meta else False,
                    "expireAfterSeconds": meta.get("expireAfterSeconds"),
                    "weights": meta.get("weights"),
                    "default_language": meta.get("default_language"),
                }

            dropped: list[str] = []
            kept: list[str] = []
            drop_errors: dict[str, str] = {}

            def _should_keep_code_snippets_index(index_name: str, meta: Any) -> bool:
                # Keep by explicit name
                if index_name in {"_id_", "search_text_idx", "unique_file_name", "user_id"}:
                    return True
                if not isinstance(meta, dict):
                    return False
                key = meta.get("key")
                # Keep single-field user_id index (name may be user_id_1 / user_id_idx etc.)
                if key in ([("user_id", 1)], [("user_id", -1)]):
                    return True
                # Keep a unique index enforcing unique file name per user (compound user_id + file_name)
                try:
                    if bool(meta.get("unique")) and key in (
                        [("user_id", 1), ("file_name", 1)],
                        [("file_name", 1), ("user_id", 1)],
                        [("user_id", 1), ("file_name", -1)],
                        [("file_name", -1), ("user_id", 1)],
                        [("user_id", -1), ("file_name", 1)],
                        [("file_name", 1), ("user_id", -1)],
                        [("user_id", -1), ("file_name", -1)],
                        [("file_name", -1), ("user_id", -1)],
                    ):
                        return True
                except Exception:
                    pass
                return False

            for name in sorted(idx_info.keys()):
                idx_name = str(name)
                meta = idx_info.get(name)
                if _should_keep_code_snippets_index(idx_name, meta):
                    kept.append(idx_name)
                    continue
                try:
                    if preview:
                        dropped.append(idx_name)  # planned
                    else:
                        code_snippets_coll.drop_index(idx_name)
                        dropped.append(idx_name)
                except Exception as e:
                    # Best-effort: אם אינדקס לא קיים/לא ניתן למחיקה, נשמור שגיאה ונתקדם.
                    drop_errors[idx_name] = str(e)

            try:
                idx_info_after = code_snippets_coll.index_information() or {}
            except Exception:
                idx_info_after = {}
            indexes_after = sorted([str(k) for k in idx_info_after.keys()])

            return {
                "ok": True,
                "preview": preview,
                "deleted_documents": {
                    "slow_queries_log": deleted_slow,
                    "service_metrics": deleted_metrics,
                    "total": deleted_slow + deleted_metrics,
                },
                "ttl": ttl_results,
                "indexes": {
                    "collection": "code_snippets",
                    "before": indexes_before,
                    "before_details": indexes_before_details,
                    "after": indexes_after,
                    "dropped": dropped,
                    "kept": kept,
                    "drop_errors": drop_errors,
                },
            }

        try:
            result = await asyncio.to_thread(_run_cleanup)
            try:
                emit_event(
                    "maintenance_cleanup_done",
                    severity="info",
                    deleted_total=int((result.get("deleted_documents") or {}).get("total") or 0),
                    dropped_indexes_count=int(len(((result.get("indexes") or {}).get("dropped")) or [])),
                )
            except Exception:
                pass
            return web.json_response(result)
        except Exception as e:
            logger.exception("maintenance_cleanup_failed")
            try:
                emit_event("maintenance_cleanup_failed", severity="error", handled=True, error=str(e))
            except Exception:
                pass
            return web.json_response({"ok": False, "error": "failed", "message": "internal_error"}, status=500)

    app.router.add_get("/health", health)
    # Always expose /healthz alias for platform probes
    try:
        app.router.add_get("/healthz", health)
    except Exception as e:
        # Ignore if already registered – אך תעד כאנומליה מטופלת
        try:
            emit_event(
                "healthz_route_register_failed",
                severity="anomaly",
                operation="startup",
                handled=True,
                error=str(e),
            )
        except Exception:
            logging.getLogger(__name__).warning(
                "healthz_route_register_failed", extra={"operation": "startup", "handled": True}
            )
    app.router.add_get("/metrics", metrics_view)
    app.router.add_post("/alerts", alerts_view)
    app.router.add_get("/alerts", alerts_get_view)
    app.router.add_post("/webhooks/sentry", sentry_webhook_view)
    app.router.add_get("/incidents", incidents_get_view)
    app.router.add_post("/api/ai/explain", ai_explain_view)
    app.router.add_get("/share/{share_id}", share_view)
    app.router.add_get("/api/debug/maintenance_cleanup", maintenance_cleanup_view)
    app.router.add_get("/api/db/pool", db_health_pool_view)
    app.router.add_get("/api/db/ops", db_health_ops_view)
    app.router.add_get("/api/db/collections", db_health_collections_view)
    app.router.add_get("/api/db/health", db_health_summary_view)

    # Jobs Monitor routes
    try:
        register_jobs_routes(app)
    except Exception:
        pass

    return app


async def get_jobs_list(request: web.Request) -> web.Response:
    """GET /api/jobs - רשימת כל ה-jobs"""
    from services.job_registry import JobRegistry

    registry = JobRegistry()
    jobs = []

    for job in registry.list_all():
        is_enabled = registry.is_enabled(job.job_id)
        jobs.append(
            {
                "job_id": job.job_id,
                "name": job.name,
                "description": job.description,
                "category": job.category.value,
                "type": job.job_type.value,
                "interval_seconds": job.interval_seconds,
                "enabled": is_enabled,
                "env_toggle": job.env_toggle,
                # can_trigger: מאפשר הפעלה ידנית אם יש callback מוגדר
                "can_trigger": bool(job.callback_name),
            }
        )

    return web.json_response({"jobs": jobs})


async def get_job_detail(request: web.Request) -> web.Response:
    """GET /api/jobs/{job_id} - פרטי job ספציפי"""
    from services.job_registry import JobRegistry
    from services.job_tracker import get_job_tracker

    job_id = request.match_info.get("job_id")
    registry = JobRegistry()
    tracker = get_job_tracker()

    job = registry.get(job_id)
    if not job:
        return web.json_response({"error": "Job not found"}, status=404)

    history = tracker.get_job_history(job_id, limit=20)
    active = [r for r in tracker.get_active_runs() if r.job_id == job_id]

    return web.json_response(
        {
            "job": {
                "job_id": job.job_id,
                "name": job.name,
                "description": job.description,
                "category": job.category.value,
                "type": job.job_type.value,
                "interval_seconds": job.interval_seconds,
                "enabled": registry.is_enabled(job.job_id),
                "source_file": job.source_file,
            },
            "active_runs": [_run_to_dict(r) for r in active],
            "history": [_run_to_dict(r) for r in history],
        }
    )


async def get_run_detail(request: web.Request) -> web.Response:
    """GET /api/jobs/runs/{run_id} - פרטי הרצה"""
    from services.job_tracker import get_job_tracker

    run_id = request.match_info.get("run_id")
    tracker = get_job_tracker()

    run = tracker.get_run(run_id)
    if not run:
        return web.json_response({"error": "Run not found"}, status=404)

    return web.json_response({"run": _run_to_dict(run, include_logs=True)})


async def get_active_runs(request: web.Request) -> web.Response:
    """GET /api/jobs/active - הרצות פעילות"""
    from services.job_tracker import get_job_tracker

    tracker = get_job_tracker()
    runs = tracker.get_active_runs()

    return web.json_response({"active_runs": [_run_to_dict(r) for r in runs]})


async def trigger_job(request: web.Request) -> web.Response:
    """POST /api/jobs/{job_id}/trigger - הפעלה ידנית"""
    from services.job_registry import JobRegistry

    job_id = request.match_info.get("job_id")
    registry = JobRegistry()

    job = registry.get(job_id)
    if not job:
        return web.json_response({"error": "Job not found"}, status=404)

    # Trigger via Telegram JobQueue (same process as bot)
    tg_app = None
    try:
        tg_app = request.app.get("telegram_application")
    except Exception:
        tg_app = None
    if tg_app is None:
        return web.json_response({"error": "job_queue_unavailable"}, status=503)

    jq = getattr(tg_app, "job_queue", None)
    if jq is None or not hasattr(jq, "get_jobs_by_name"):
        return web.json_response({"error": "job_queue_unavailable"}, status=503)

    try:
        jobs = jq.get_jobs_by_name(job_id)
    except Exception:
        jobs = []
    if not jobs:
        return web.json_response({"error": "job_not_scheduled"}, status=404)

    job_obj = jobs[0]
    callback = getattr(job_obj, "callback", None)
    if not callable(callback):
        return web.json_response({"error": "job_callback_unavailable"}, status=500)

    # Schedule immediate one-off run
    try:
        suffix = str(int(time.time()))
    except Exception:
        suffix = "now"
    try:
        data = getattr(job_obj, "data", None)
        chat_id = getattr(job_obj, "chat_id", None)
        user_id = getattr(job_obj, "user_id", None)
        kwargs = {"when": 0, "name": f"{job_id}_manual_{suffix}"}
        if data is not None:
            kwargs["data"] = data
        if chat_id is not None:
            kwargs["chat_id"] = chat_id
        if user_id is not None:
            kwargs["user_id"] = user_id
        jq.run_once(callback, **kwargs)
    except Exception:
        try:
            # Fallback for older signatures
            jq.run_once(callback, when=0)
        except Exception:
            logger.exception("jobs_trigger_failed job_id=%s", job_id)
            return web.json_response(
                {"error": "trigger_failed", "message": "Failed to trigger job"},
                status=500,
            )

    return web.json_response({"message": f"Job {job_id} triggered", "job_id": job_id})


def _run_to_dict(run, include_logs: bool = False) -> dict:
    """המרת JobRun ל-dict"""
    d = {
        "run_id": run.run_id,
        "job_id": run.job_id,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "ended_at": run.ended_at.isoformat() if run.ended_at else None,
        "status": run.status.value,
        "progress": run.progress,
        "total_items": run.total_items,
        "processed_items": run.processed_items,
        "error_message": run.error_message,
        "trigger": run.trigger,
        "user_id": run.user_id,
        "duration_seconds": (
            (run.ended_at - run.started_at).total_seconds()
            if run.ended_at and run.started_at
            else None
        ),
    }
    if include_logs:
        d["logs"] = [
            {
                "timestamp": log.timestamp.isoformat(),
                "level": log.level,
                "message": log.message,
            }
            for log in run.logs
        ]
    return d


def register_jobs_routes(app: web.Application):
    """רישום routes של Jobs"""
    app.router.add_get("/api/jobs", get_jobs_list)
    app.router.add_get("/api/jobs/active", get_active_runs)
    app.router.add_get("/api/jobs/{job_id}", get_job_detail)
    app.router.add_get("/api/jobs/runs/{run_id}", get_run_detail)
    app.router.add_post("/api/jobs/{job_id}/trigger", trigger_job)


def run(host: str = "0.0.0.0", port: int = 10000) -> None:
    try:
        note_deployment_started("aiohttp service starting up")
    except Exception:
        pass
    app = create_app()
    web.run_app(app, host=host, port=port)


if __name__ == "__main__":  # pragma: no cover - used by Render/CLI entrypoint
    host = os.getenv("WEB_HOST") or os.getenv("HOST") or "0.0.0.0"
    port_env = os.getenv("PORT") or os.getenv("WEB_PORT") or "10000"
    try:
        port = int(port_env)
    except (TypeError, ValueError):
        port = 10000
    run(host=host, port=port)

