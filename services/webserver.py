import asyncio
import atexit
import logging
import os
import secrets
from dataclasses import dataclass
import hashlib
import hmac
from typing import Any, Dict, Optional

# Configure structured logging and Sentry as early as possible,
# and install sensitive data redaction on log handlers before Sentry hooks logging.
try:
    from observability import setup_structlog_logging, init_sentry  # type: ignore
    setup_structlog_logging("INFO")
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
    def note_request_started() -> None:  # type: ignore
        return None
    def note_request_finished() -> None:  # type: ignore
        return None
    def note_deployment_started(_summary: str = "Service starting up") -> None:  # type: ignore
        return None
    def note_deployment_shutdown(_summary: str = "Service shutting down") -> None:  # type: ignore
        return None
from html import escape as html_escape
from services import ai_explain_service

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

    # Stable identifiers for dedup
    primary_id = issue_id or short_id or str(event.get("id") or event.get("event_id") or "").strip()
    dedup_key = "|".join([x for x in [primary_id, project_slug, severity, action] if x])
    if not dedup_key:
        # Worst-case fallback: title bucket
        dedup_key = f"title:{title_s[:80]}"

    display_id = short_id or (issue_id[:8] if issue_id else "issue")
    name = _truncate(f"Sentry: {display_id}", 128)

    details: Dict[str, Any] = {
        "alert_type": "sentry_issue",
        "action": action or None,
        "project": project_slug or None,
        "level": level or None,
        "sentry_issue_id": issue_id or None,
        "sentry_short_id": short_id or None,
        "sentry_permalink": permalink or None,
        "sentry_event_id": str(event.get("id") or event.get("event_id") or "").strip() or None,
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
        handler_name = getattr(handler, "__name__", None) or handler.__class__.__name__
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

    app = web.Application(middlewares=[_request_id_mw])

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

    return app


def run(host: str = "0.0.0.0", port: int = 10000) -> None:
    try:
        note_deployment_started("aiohttp service starting up")
        atexit.register(lambda: note_deployment_shutdown("aiohttp service shutting down"))
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

