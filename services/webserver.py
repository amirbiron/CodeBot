import logging
import os
from typing import Optional

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
    )
except Exception:  # pragma: no cover
    metrics_endpoint_bytes = lambda: b""  # type: ignore
    metrics_content_type = lambda: "text/plain; charset=utf-8"  # type: ignore
    def record_request_outcome(status_code: int, duration_seconds: float) -> None:  # type: ignore
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

logger = logging.getLogger(__name__)


def create_app() -> web.Application:
    # הוסף middleware שמייצר ומקשר request_id לכל בקשה נכנסת
    @web.middleware
    async def _request_id_mw(request: web.Request, handler):
        req_id = generate_request_id() or ""
        start = time.perf_counter()
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
        response = await handler(request)
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
            record_request_outcome(status, duration)
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
            # Emit a structured event that tests can monkeypatch easily while
            # still honoring dynamic replacement of observability.emit_event
            try:
                import sys as _sys
                chosen_emit = None
                obs = _sys.modules.get("observability")
                if obs is not None:
                    cand = getattr(obs, "emit_event", None)
                    if callable(cand):
                        chosen_emit = cand
                if chosen_emit is None:
                    chosen_emit = emit_event  # type: ignore
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
    app.router.add_get("/incidents", incidents_get_view)
    app.router.add_get("/share/{share_id}", share_view)

    return app


def run(host: str = "0.0.0.0", port: int = 10000) -> None:
    app = create_app()
    web.run_app(app, host=host, port=port)

