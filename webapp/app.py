#!/usr/bin/env python3
"""
Code Keeper Bot - Web Application
אפליקציית ווב לניהול וצפייה בקטעי קוד
"""

import os
import logging
import hashlib
import hmac
import json
import time
from datetime import datetime, timezone
from functools import wraps
from typing import Optional, Dict, Any, List

from flask import Flask, render_template, jsonify, request, session, redirect, url_for, send_file, abort, Response, g
import threading
import atexit
import time as _time
from werkzeug.http import http_date, parse_date
from werkzeug.exceptions import HTTPException
from flask_compress import Compress
from pymongo import MongoClient, DESCENDING
from pymongo.errors import PyMongoError
from pygments import highlight
from pygments.lexers import get_lexer_by_name, guess_lexer
from pygments.util import ClassNotFound
from pygments.formatters import HtmlFormatter
from bson import ObjectId
from bson.errors import InvalidId
from datetime import timedelta
import re
import sys
from pathlib import Path
import secrets
import threading
import base64
import traceback


# הוספת נתיב ה-root של הפרויקט ל-PYTHONPATH כדי לאפשר import ל-"database" כשהסקריפט רץ מתוך webapp/
ROOT_DIR = str(Path(__file__).resolve().parents[1])
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

# מייבא לאחר הוספת ROOT_DIR ל-PYTHONPATH כדי למנוע כשל ייבוא בדיפלוי
from http_sync import request as http_request  # noqa: E402

# נרמול טקסט/קוד לפני שמירה (הסרת תווים נסתרים, כיווניות, אחידות שורות)
from utils import normalize_code  # noqa: E402

# קונפיגורציה מרכזית (Pydantic Settings)
try:  # שמירה על יציבות גם בסביבות דוקס/CI
    from config import config as cfg
except Exception:  # pragma: no cover
    cfg = None


def _cfg_or_env(attr: str, default: Any = None, *, env_name: str | None = None) -> Any:
    """משיג ערך מהקונפיג או מהסביבה, כולל תמיכה ב-Stubs פשוטים בטסטים."""
    env_key = env_name or attr
    value = None
    if cfg is not None:
        value = getattr(cfg, attr, None)
    if value in (None, '') and env_key:
        env_val = os.getenv(env_key)
        if env_val not in (None, ''):
            value = env_val
    if value in (None, ''):
        value = default
    return value

# Search engine & types
try:
    from search_engine import search_engine, SearchType, SearchFilter, SortOrder
except Exception:
    search_engine = None
    class _Missing:
        pass
    SearchType = _Missing
    SearchFilter = _Missing
    SortOrder = _Missing

# Structured logging (optional and safe-noop fallbacks)
try:
    from observability import (
        emit_event,
        bind_request_id,
        generate_request_id,
        bind_user_context,
        bind_command,
        get_observability_context,
    )
except Exception:  # pragma: no cover
    def emit_event(event: str, severity: str = "info", **fields):
        return None
    def bind_request_id(request_id: str) -> None:
        return None
    def generate_request_id() -> str:
        try:
            return str(int(time.time() * 1000))[-8:]
        except Exception:
            return ""
    def bind_user_context(*_a, **_k):
        return None
    def bind_command(_identifier: str | None = None) -> None:
        return None
    def get_observability_context() -> Dict[str, Any]:
        return {}

# Alertmanager forwarding (optional)
try:
    from alert_forwarder import forward_alerts as _forward_alerts
except Exception:  # pragma: no cover
    def _forward_alerts(_alerts):
        return None

# Optional monitoring & resilience
try:
    from prometheus_client import Counter, Histogram, Gauge, generate_latest, REGISTRY
except Exception:
    Counter = Histogram = Gauge = generate_latest = REGISTRY = None
try:
    from tenacity import retry, stop_after_attempt, wait_exponential
except Exception:
    retry = stop_after_attempt = wait_exponential = None
try:
    import sentry_sdk
    from sentry_sdk.integrations.flask import FlaskIntegration
    _SENTRY_AVAILABLE = True
except Exception:
    _SENTRY_AVAILABLE = False
# Cache (Redis) – שימוש במנהל הקאש המרכזי של הפרויקט
try:
    from cache_manager import cache  # noqa: E402
except Exception:
    from typing import Any, Optional, Dict, Union
    class _NoCache:
        is_enabled: bool = False
        def get(self, key: str) -> None:  # pragma: no cover - fallback only
            return None
        def set(self, key: str, value: Any, expire_seconds: int = 60) -> bool:  # pragma: no cover - fallback only
            return False
        def set_dynamic(self, key: str, value: Any, content_type: str, context: Optional[Dict[str, Any]] = None) -> bool:  # pragma: no cover - fallback only
            return False
        def delete(self, key: str) -> bool:  # pragma: no cover - fallback only
            return False
        def delete_pattern(self, pattern: str) -> int:  # pragma: no cover - fallback only
            return 0
        def invalidate_user_cache(self, user_id: int) -> int:  # pragma: no cover - fallback only
            return 0
        def clear_all(self) -> int:  # pragma: no cover - fallback only
            return 0
        def invalidate_file_related(self, file_id: str, user_id: Optional[Union[int, str]] = None) -> int:  # pragma: no cover - fallback only
            return 0
        def clear_stale(self, max_scan: int = 1000, ttl_seconds_threshold: int = 60) -> int:  # pragma: no cover - fallback only
            return 0
        def get_stats(self) -> Dict[str, Any]:  # pragma: no cover - fallback only
            return {"enabled": False}
    cache = _NoCache()

# יצירת האפליקציה
app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')
app.permanent_session_lifetime = timedelta(days=30)  # סשן נשמר ל-30 יום
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 31536000  # שנה לסטטיקה
app.config['COMPRESS_ALGORITHM'] = ['br', 'gzip']
app.config['COMPRESS_LEVEL'] = 6
app.config['COMPRESS_BR_LEVEL'] = 5
Compress(app)
# לוגר מודולרי לשימוש פנימי
logger = logging.getLogger(__name__)

# --- Static asset version (for cache-busting of PWA manifest/icons) ---
_MANIFEST_PATH = (Path(__file__).parent / 'static' / 'manifest.json')

def _compute_static_version() -> str:
    """Return a short version string to bust caches for static assets.

    Preference order:
    1) ASSET_VERSION env
    2) APP_VERSION env
    3) SHA1(first 8) of manifest.json contents
    4) Hourly rolling timestamp
    """
    v = os.getenv("ASSET_VERSION") or os.getenv("APP_VERSION")
    if v:
        return str(v)
    try:
        p = _MANIFEST_PATH
        if p.is_file():
            h = hashlib.sha1(p.read_bytes()).hexdigest()  # nosec - not for security
            return h[:8]
    except Exception:
        pass
    try:
        return str(int(_time.time() // 3600))
    except Exception:
        return "dev"

_STATIC_VERSION = _compute_static_version()

# מזהי המדריכים המשותפים לזרימת ה-Onboarding בווב
WELCOME_GUIDE_PRIMARY_SHARE_ID = "JjvpJFTXZO0oHtoC"
WELCOME_GUIDE_SECONDARY_SHARE_ID = "sdVOAx6hUGsH4Anr"

# Guards for first-request and DB init race conditions
_FIRST_REQUEST_LOCK = threading.Lock()
_FIRST_REQUEST_RECORDED = False


def _build_request_span_attrs() -> Dict[str, str]:
    attrs: Dict[str, str] = {"component": "flask.webapp"}
    try:
        method = getattr(request, "method", "")
        if method:
            attrs["http.method"] = str(method).upper()
    except Exception:
        pass
    try:
        endpoint = getattr(request, "endpoint", "") or ""
        if endpoint:
            attrs["endpoint"] = endpoint
    except Exception:
        pass
    try:
        path = getattr(request, "path", "") or ""
        if path:
            attrs["http.target"] = path
    except Exception:
        pass
    try:
        rid = getattr(request, "_req_id", None)
        if not rid:
            rid = request.headers.get("X-Request-ID")
        if rid:
            attrs["request_id"] = str(rid)
    except Exception:
        pass
    try:
        ctx = get_observability_context() or {}
        if isinstance(ctx, dict):
            if ctx.get("command"):
                attrs["command"] = str(ctx["command"])
            if ctx.get("user_id"):
                attrs["user_id_hash"] = str(ctx["user_id"])
            if ctx.get("chat_id"):
                attrs["chat_id_hash"] = str(ctx["chat_id"])
    except Exception:
        pass
    return {k: v for k, v in attrs.items() if v not in ("", None)}


@app.before_request
def _otel_start_request_span():
    try:
        attrs = _build_request_span_attrs()
        span_cm = start_span("web.request", attrs)
    except Exception:
        setattr(g, "_otel_span_cm", None)
        setattr(g, "_otel_span", None)
        setattr(g, "_otel_response_status", None)
        setattr(g, "_otel_cache_hit", None)
        return
    span = span_cm.__enter__()
    setattr(g, "_otel_span_cm", span_cm)
    setattr(g, "_otel_span", span)
    setattr(g, "_otel_response_status", None)
    setattr(g, "_otel_cache_hit", None)
    if span is not None:
        try:
            set_current_span_attributes({"component": "flask.webapp"})
        except Exception:
            pass
# --- OpenTelemetry (optional, fail-open) ---
try:
    from observability_otel import setup_telemetry as _setup_otel
    _setup_otel(
        service_name="code-keeper-webapp",
        service_version=os.getenv("APP_VERSION", ""),
        environment=os.getenv("ENVIRONMENT", os.getenv("ENV", "production")),
        flask_app=app,
    )
except Exception:
    pass

# Manual tracing decorator (fail-open)
try:
    from observability_instrumentation import traced, start_span, set_current_span_attributes
except Exception:  # pragma: no cover
    def traced(*_a, **_k):
        def _inner(f):
            return f
        return _inner

    class _NoSpan:
        def __enter__(self):  # pragma: no cover
            return None

        def __exit__(self, *_exc):  # pragma: no cover
            return False

    def start_span(*_a, **_k):  # type: ignore
        return _NoSpan()

    def set_current_span_attributes(*_a, **_k):  # type: ignore
        return None
# --- Correlation ID across services (request_id) ---
try:
    from observability import generate_request_id as _gen_rid, bind_request_id as _bind_rid
except Exception:
    def _gen_rid():
        return ""
    def _bind_rid(_rid: str) -> None:
        return None

# --- Lightweight preload of heavy dependencies/templates (non-blocking) ---
def _preload_heavy_assets_async() -> None:
    """Preload non-critical assets to reduce first-hit latency.

    Runs in a background thread to avoid blocking app import.
    """
    try:
        import threading as _thr
        def _job():
            # Preload Pygments lexers/formatters (import and simple use)
            try:
                from pygments.lexers import get_lexer_by_name as _g
                _t0 = _time.perf_counter()
                for _name in ("python", "javascript", "bash", "json"):
                    try:
                        _ = _g(_name)
                    except Exception:
                        pass
                try:
                    record_dependency_init("pygments_lexers", max(0.0, float(_time.perf_counter() - _t0)))
                except Exception:
                    pass
            except Exception:
                pass
            # Warm up Jinja by preloading hot templates (compile without request context)
            try:
                _t1 = _time.perf_counter()
                with app.app_context():
                    # Preload a few hot templates (best-effort)
                    for _tpl in ("files.html", "view_file.html", "dashboard.html", "md_preview.html", "login.html"):
                        try:
                            _ = app.jinja_env.get_template(_tpl)
                        except Exception:
                            pass
                try:
                    record_dependency_init("jinja_precompile", max(0.0, float(_time.perf_counter() - _t1)))
                except Exception:
                    pass
            except Exception:
                pass
            # Optionally attempt DB ping in background (best-effort)
            try:
                _t0 = _time.perf_counter()
                # Use a short‑lived client to avoid mutating the global shared client
                if MONGODB_URL:
                    _tmp_client = MongoClient(
                        MONGODB_URL,
                        serverSelectionTimeoutMS=2000,
                        tz_aware=True,
                        tzinfo=timezone.utc,
                    )
                    try:
                        # Best‑effort ping; ignore failures silently
                        _ = _tmp_client.admin.command('ping')
                    except Exception:
                        pass
                    finally:
                        try:
                            _tmp_client.close()
                        except Exception:
                            pass
                try:
                    record_dependency_init("mongodb_ping", max(0.0, float(_time.perf_counter() - _t0)))
                except Exception:
                    pass
            except Exception:
                pass
            # Signal startup completion at the end of preload sequence
            try:
                mark_startup_complete()
            except Exception:
                pass
        _thr.Thread(target=_job, name="preload-assets", daemon=True).start()
    except Exception:
        # Never block on preload failures
        try:
            mark_startup_complete()
        except Exception:
            pass

# --- API blueprints registration ---
try:
    from webapp.bookmarks_api import bookmarks_bp  # noqa: E402
    app.register_blueprint(bookmarks_bp)
except Exception:
    # אם יש כשל בייבוא (למשל בזמן דוקס/CI בלי תלותים), אל תפיל את השרת
    pass

# Sticky Notes API (Markdown inline notes)
try:
    from webapp.sticky_notes_api import sticky_notes_bp  # noqa: E402
    app.register_blueprint(sticky_notes_bp)
except Exception:
    # אל תפיל את היישום אם ה-Blueprint אינו זמין (למשל בסביבת דוקס/CI)
    pass

# זיהוי הרצה תחת pytest בזמן import (גם בזמן איסוף טסטים)
_IS_PYTEST = bool(os.getenv("PYTEST_CURRENT_TEST")) or ("pytest" in sys.modules) or os.getenv("PYTEST") == "1" or os.getenv("PYTEST_RUNNING") == "1"

# Collections (My Collections) API
try:
    from config import config as _cfg
except Exception:
    _cfg = None

try:
    # קביעת זמינות הפיצ'ר: ברירת מחדל True, אלא אם הקונפיג מכבה במפורש.
    enabled = True if _cfg is None else bool(getattr(_cfg, 'FEATURE_MY_COLLECTIONS', True))
    # ב-PyTest – נכפה enable כדי להבטיח רישום ה-Blueprint גם אם config חסר/מכובה
    if _IS_PYTEST:
        enabled = True

    if enabled:
        from webapp.collections_api import collections_bp  # noqa: E402
        # רישום יחיד וקנוני של ה-API בנתיב /api/collections
        app.register_blueprint(collections_bp, url_prefix="/api/collections")
        # רישום דפי UI (server-rendered) הטעונים למסלול /collections
        try:
            from webapp.collections_ui import collections_ui  # noqa: E402
            app.register_blueprint(collections_ui)
        except Exception as _e:
            try:
                logger.info("collections_ui blueprint not registered: %s", _e)
            except Exception:
                pass
except Exception as e:
    # בפרודקשן – לא נרשום Blueprint דיאגנוסטי, רק נרשום ללוג
    try:
        logger.error("Failed to register collections blueprint: %s", e, exc_info=True)
    except Exception:
        pass
    if _IS_PYTEST:
        # ב-PyTest – אם הייבוא נכשל, נרשום Blueprint דיאגנוסטי שמחזיר 503 במקום 404
        try:
            from flask import Blueprint  # ייבוא לוקלי כדי לא לזהם טופ-לבל

            diagnostic_bp = Blueprint('collections_diagnostic', __name__)

            # נתיבים לוכדים לכל ה-API תחת /api/collections
            @diagnostic_bp.route('', defaults={'_path': ''}, methods=['GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'OPTIONS'])
            @diagnostic_bp.route('/<path:_path>', methods=['GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'OPTIONS'])
            def _collections_unavailable(_path: str = ""):
                # שימוש ב-jsonify שכבר יובא בטופ-לבל
                return jsonify({
                    'ok': False,
                    'error': 'collections_api_unavailable',
                    'diagnostic': True
                }), 503

            app.register_blueprint(diagnostic_bp, url_prefix="/api/collections")
            try:
                logger.info("Registered diagnostic collections blueprint for pytest")
            except Exception:
                pass
        except Exception:
            # אם גם הרישום הדיאגנוסטי נכשל – נכשיל את הטסט כדי לא להסתיר תקלה אמיתית
            raise

# Community Library API/UI (feature-flagged)
try:
    _enabled_comm = True if _cfg is None else bool(getattr(_cfg, 'COMMUNITY_LIBRARY_ENABLED', True))
    if _IS_PYTEST:
        _enabled_comm = True
    if _enabled_comm:
        try:
            from webapp.community_library_api import community_lib_bp  # type: ignore  # noqa: E402
            app.register_blueprint(community_lib_bp)
        except Exception as _e:
            try:
                logger.info("community_library_api not registered: %s", _e)
            except Exception:
                pass
        try:
            from webapp.community_library_ui import community_library_ui  # type: ignore  # noqa: E402
            app.register_blueprint(community_library_ui)
        except Exception as _e:
            try:
                logger.info("community_library_ui not registered: %s", _e)
            except Exception:
                pass
        # Snippet Library API/UI
        try:
            from webapp.snippet_library_api import snippets_bp  # type: ignore  # noqa: E402
            app.register_blueprint(snippets_bp)
        except Exception as _e:
            try:
                logger.info("snippets_api not registered: %s", _e)
            except Exception:
                pass
        try:
            # UI blueprint may be optional; register if available
            from webapp.snippet_library_ui import snippet_library_ui  # type: ignore  # noqa: E402
            app.register_blueprint(snippet_library_ui)
        except Exception as _e:
            try:
                logger.info("snippet_library_ui not registered: %s", _e)
            except Exception:
                pass
except Exception:
    pass

# --- Metrics helpers (import guarded to avoid hard deps in docs/CI) ---
try:
    from metrics import (
        record_request_outcome,
        record_http_request,
        get_boot_monotonic,
        mark_startup_complete,
        note_first_request_latency,
        record_dependency_init,
     )
except Exception:  # pragma: no cover
    def record_request_outcome(status_code: int, duration_seconds: float, **_kwargs) -> None:
        return None
    def record_http_request(method: str, endpoint: str, status_code: int, duration_seconds: float) -> None:
        return None
    def get_boot_monotonic() -> float:
        return 0.0
    def mark_startup_complete() -> None:
        return None
    def note_first_request_latency(_d: float | None = None) -> None:
        return None
    def record_dependency_init(_name: str, _dur: float) -> None:
        return None

# Trigger preload only after metrics helpers are available
_preload_heavy_assets_async()

# --- Search: metrics, limiter (lightweight, optional) ---
def _no_op(*args, **kwargs):
    return None

try:
    from flask_limiter import Limiter
    from flask_limiter.util import get_remote_address
    _LIMITER_AVAILABLE = True
except Exception:
    Limiter = None
    # fall back to a simple remote address accessor if limiter not installed
    get_remote_address = lambda: request.remote_addr if request else ""
    _LIMITER_AVAILABLE = False

# Prometheus metrics (idempotent registration)
def _get_existing_metric(name: str):
    try:
        if REGISTRY is not None and hasattr(REGISTRY, '_names_to_collectors'):
            return REGISTRY._names_to_collectors.get(name)
    except Exception:
        return None
    return None
class _MetricNoop:
    def labels(self, *a, **k): return self
    def inc(self, *a, **k): return None
    def observe(self, *a, **k): return None
    def set(self, *a, **k): return None
def _ensure_metric(name: str, create_fn):
    existing = _get_existing_metric(name)
    if existing:
        return existing
    try:
        return create_fn()
    except Exception:
        existing = _get_existing_metric(name)
        if existing:
            return existing
        return _MetricNoop()

if Counter and Histogram and Gauge:
    search_counter = _ensure_metric('search_requests_total', lambda: Counter('search_requests_total', 'Total number of search requests', ['search_type', 'status']))
    search_duration = _ensure_metric('search_duration_seconds', lambda: Histogram('search_duration_seconds', 'Search request duration in seconds'))
    search_results_count = _ensure_metric('search_results_count', lambda: Histogram('search_results_count', 'Number of results returned'))
    search_cache_hits = _ensure_metric('search_cache_hits_total', lambda: Counter('search_cache_hits_total', 'Total number of cache hits'))
    search_cache_misses = _ensure_metric('search_cache_misses_total', lambda: Counter('search_cache_misses_total', 'Total number of cache misses'))
    active_indexes_gauge = _ensure_metric('search_active_indexes', lambda: Gauge('search_active_indexes', 'Number of active search indexes'))
else:
    search_counter = _MetricNoop()
    search_duration = _MetricNoop()
    search_results_count = _MetricNoop()
    search_cache_hits = _MetricNoop()
    search_cache_misses = _MetricNoop()
    active_indexes_gauge = _MetricNoop()

# Optional Sentry init (non-fatal if missing)
try:
    if _SENTRY_AVAILABLE and getattr(__import__('config'), 'config').SENTRY_DSN:
        # Install sensitive data redaction on all handlers before Sentry hooks logging
        try:
            from utils import install_sensitive_filter
            install_sensitive_filter()
        except Exception:
            pass
        sentry_sdk.init(
            dsn=getattr(__import__('config'), 'config').SENTRY_DSN,
            integrations=[FlaskIntegration()],
            traces_sample_rate=0.05,
            environment=getattr(__import__('config'), 'config').ENVIRONMENT,
        )
except Exception:
    pass

"""Rate limiting backend setup

Preference order:
1) Redis via REDIS_URL (TLS supported by driver) when available
2) In-memory fallback (per-process; acceptable for local/dev and tests)
3) Disabled if flask_limiter is unavailable
"""
def _client_rate_key():
    """Rate-limit key: prefer user_id; else leftmost X-Forwarded-For; else remote_addr.

    זה מצמצם false-positives בפלטפורמות Proxy (למשל Render/Cloudflare) ומונע הגבלת
    משתמשים שונים תחת אותו IP פנימי.
    """
    try:
        if 'user_id' in session:
            return str(session.get('user_id'))
        # Try the leftmost IP from X-Forwarded-For
        try:
            xff = (request.headers.get('X-Forwarded-For') or '').split(',')
            for raw in xff:
                ip = (raw or '').strip()
                if ip:
                    return ip
        except Exception:
            pass
        return get_remote_address()
    except Exception:
        try:
            return request.remote_addr or ""
        except Exception:
            return ""

if _LIMITER_AVAILABLE:
    try:
        # Resolve storage URI: prefer Redis when configured
        _storage_uri = "memory://"
        try:
            from config import config as _cfg
        except Exception:
            _cfg = None
        if _cfg is not None and getattr(_cfg, 'REDIS_URL', None):
            _storage_uri = str(getattr(_cfg, 'REDIS_URL'))
        elif os.getenv('REDIS_URL'):
            _storage_uri = os.getenv('REDIS_URL') or "memory://"

        limiter = Limiter(
            app=app,
            key_func=_client_rate_key,
            default_limits=["200 per day", "50 per hour"],
            storage_uri=_storage_uri,
            strategy=(getattr(_cfg, 'RATE_LIMIT_STRATEGY', 'moving-window') if _cfg else 'moving-window'),
            swallow_errors=True,  # don't crash the app if backend unavailable
        )
    except Exception:
        limiter = None
else:
    limiter = None

# הגדרות
MONGODB_URL = _cfg_or_env('MONGODB_URL')
DATABASE_NAME = _cfg_or_env('DATABASE_NAME', default='code_keeper_bot')
BOT_TOKEN = _cfg_or_env('BOT_TOKEN')
WEBAPP_URL = _cfg_or_env('WEBAPP_URL', default='https://code-keeper-webapp.onrender.com')
PUBLIC_BASE_URL = _cfg_or_env('PUBLIC_BASE_URL', default='')
_DOCS_URL_RAW = _cfg_or_env('DOCUMENTATION_URL', default='https://amirbiron.github.io/CodeBot/')
DOCUMENTATION_URL = (_DOCS_URL_RAW.rstrip('/') + '/') if _DOCS_URL_RAW else 'https://amirbiron.github.io/CodeBot/'

BOT_USERNAME = os.getenv('BOT_USERNAME', 'my_code_keeper_bot')
BOT_USERNAME_CLEAN = (BOT_USERNAME or '').lstrip('@')
_ttl_env = os.getenv('PUBLIC_SHARE_TTL_DAYS', '7')
FA_SRI_HASH = (os.getenv('FA_SRI_HASH') or '').strip()

# --- Cache TTLs (seconds) for heavy endpoints/pages ---
def _int_env(name: str, default: int, lo: int = 30, hi: int = 180) -> int:
    try:
        val = int(os.getenv(name, str(default)))
        return max(lo, min(hi, val))
    except Exception:
        return default

FILES_PAGE_CACHE_TTL = _int_env('FILES_PAGE_CACHE_TTL', 90, lo=30, hi=180)
MD_PREVIEW_CACHE_TTL = _int_env('MD_PREVIEW_CACHE_TTL', 120, lo=60, hi=180)
API_STATS_CACHE_TTL = _int_env('API_STATS_CACHE_TTL', 120, lo=60, hi=180)

# --- External uptime monitoring (Option 2 from issue #730) ---
# Provider options: 'betteruptime' (Better Stack), 'uptimerobot', 'statuscake', 'pingdom'
UPTIME_PROVIDER = (os.getenv('UPTIME_PROVIDER') or '').strip().lower()  # e.g., 'betteruptime'
UPTIME_API_KEY = os.getenv('UPTIME_API_KEY', '')
UPTIME_MONITOR_ID = os.getenv('UPTIME_MONITOR_ID', '')
# Public status page URL (if you have one externally)
UPTIME_STATUS_URL = os.getenv('UPTIME_STATUS_URL', '')
# Optional widget (Better Uptime / Better Stack announcement widget)
UPTIME_WIDGET_SCRIPT_URL = os.getenv('UPTIME_WIDGET_SCRIPT_URL', 'https://uptime.betterstack.com/widgets/announcement.js')
UPTIME_WIDGET_ID = os.getenv('UPTIME_WIDGET_ID', '')  # the widget data-id
# Cache TTL (seconds) for external uptime API calls
try:
    UPTIME_CACHE_TTL_SECONDS = max(30, int(os.getenv('UPTIME_CACHE_TTL_SECONDS', '120')))
except Exception:
    UPTIME_CACHE_TTL_SECONDS = 120
try:
    PUBLIC_SHARE_TTL_DAYS = max(1, int(_ttl_env))
except Exception:
    PUBLIC_SHARE_TTL_DAYS = 7

# ברירת מחדל לימי שהות בסל מחזור עבור מחיקה רכה בווב
try:
    RECYCLE_TTL_DAYS_DEFAULT = max(1, int(os.getenv('RECYCLE_TTL_DAYS', '7') or '7'))
except Exception:
    RECYCLE_TTL_DAYS_DEFAULT = 7

# הגדרת חיבור קבוע (Remember Me)
try:
    PERSISTENT_LOGIN_DAYS = max(30, int(os.getenv('PERSISTENT_LOGIN_DAYS', '180')))
except Exception:
    PERSISTENT_LOGIN_DAYS = 180
REMEMBER_COOKIE_NAME = 'remember_me'

 

# חיבור ל-MongoDB
client = None
db = None
@app.context_processor
def inject_globals():
    """הזרקת משתנים גלובליים לכל התבניות"""
    user_id = session.get('user_id')
    user_doc: Dict[str, Any] = {}
    db_ref = None
    if user_id:
        try:
            db_ref = get_db()
            user_doc = db_ref.users.find_one({'user_id': user_id}) or {}
        except Exception:
            user_doc = {}

    # קביעת גודל גופן מהעדפות משתמש/קוקי
    font_scale = 1.0
    try:
        cookie_val = request.cookies.get('ui_font_scale')
        if cookie_val:
            try:
                v = float(cookie_val)
                if 0.85 <= v <= 1.6:
                    font_scale = v
            except Exception:
                pass
        if user_id and user_doc:
            try:
                v = float(((user_doc.get('ui_prefs') or {}).get('font_scale')) or font_scale)
                if 0.85 <= v <= 1.6:
                    font_scale = v
            except Exception:
                pass
    except Exception:
        pass

    # ערכת נושא
    theme = 'classic'
    try:
        cookie_theme = (request.cookies.get('ui_theme') or '').strip().lower()
        if cookie_theme:
            theme = cookie_theme
        if user_id and user_doc:
            try:
                t = ((user_doc.get('ui_prefs') or {}).get('theme') or '').strip().lower()
                if t:
                    theme = t
            except Exception:
                pass
    except Exception:
        pass
    if theme not in {'classic','ocean','forest','high-contrast'}:
        theme = 'classic'

    show_welcome_modal = False
    if user_id:
        # אם אין user_doc (למשל כשל זמני ב-DB) נ fallback לסשן כדי לא לחסום משתמשים חדשים
        if user_doc:
            show_welcome_modal = not bool(user_doc.get('has_seen_welcome_modal'))
        else:
            try:
                show_welcome_modal = not bool(session.get('user_data', {}).get('has_seen_welcome_modal', False))
            except Exception:
                show_welcome_modal = False

    # SRI map (optional): only set if provided via env to avoid mismatches
    sri_map = {}
    try:
        if FA_SRI_HASH:
            sri_map['fa'] = FA_SRI_HASH
    except Exception:
        sri_map = {}

    try:
        primary_guide_url = url_for('public_share', share_id=WELCOME_GUIDE_PRIMARY_SHARE_ID, view='md')
        secondary_guide_url = url_for('public_share', share_id=WELCOME_GUIDE_SECONDARY_SHARE_ID, view='md')
    except Exception:
        primary_guide_url = f"/share/{WELCOME_GUIDE_PRIMARY_SHARE_ID}?view=md"
        secondary_guide_url = f"/share/{WELCOME_GUIDE_SECONDARY_SHARE_ID}?view=md"

    return {
        'bot_username': BOT_USERNAME_CLEAN,
        'ui_font_scale': font_scale,
        'ui_theme': theme,
        # גרסה סטטית לצירוף לסטטיקה (cache-busting)
        'static_version': _STATIC_VERSION,
        # קישור לתיעוד (לשימוש בתבניות)
        'documentation_url': DOCUMENTATION_URL,
        # External uptime config for templates (non-sensitive only)
        'uptime_provider': UPTIME_PROVIDER,
        'uptime_status_url': UPTIME_STATUS_URL,
        'uptime_widget_script_url': UPTIME_WIDGET_SCRIPT_URL,
        'uptime_widget_id': UPTIME_WIDGET_ID,
        # SRI hashes for CDN assets (optional; provided via env)
        'cdn_sri': sri_map if sri_map else None,
        # Welcome modal config
        'show_welcome_modal': show_welcome_modal,
        'welcome_primary_guide_url': primary_guide_url,
        'welcome_secondary_guide_url': secondary_guide_url,
    }

 


def get_db():
    """מחזיר חיבור למסד הנתונים"""
    global client, db
    # Proper double-checked locking: perform initialization under the lock
    if client is None:
        _db_lock = globals().setdefault("_DB_INIT_LOCK", threading.Lock())
        with _db_lock:
            if client is None:
                if not MONGODB_URL:
                    raise Exception("MONGODB_URL is not configured")
                try:
                    # החזר אובייקטי זמן tz-aware כדי למנוע השוואות naive/aware
                    _t0 = _time.perf_counter()
                    client = MongoClient(
                        MONGODB_URL,
                        serverSelectionTimeoutMS=5000,
                        tz_aware=True,
                        tzinfo=timezone.utc,
                    )
                    # בדיקת חיבור
                    client.server_info()
                    db = client[DATABASE_NAME]
                    try:
                        record_dependency_init("mongodb", max(0.0, float(_time.perf_counter() - _t0)))
                    except Exception:
                        pass
                except Exception:
                    logger.exception("Failed to connect to MongoDB")
                    raise
    # מחוץ לנעילה: הבטח אינדקסים פעם אחת, ללא קריאה חוזרת ל-get_db
    try:
        ensure_recent_opens_indexes()
    except Exception:
        pass
    try:
        ensure_code_snippets_indexes()
    except Exception:
        pass
    return db


# --- Graceful MongoClient shutdown on process exit ---
def _close_mongo_client_on_exit() -> None:
    try:
        global client
        if client is not None:
            try:
                client.close()
            except Exception:
                pass
            finally:
                client = None
    except Exception:
        pass

atexit.register(_close_mongo_client_on_exit)

# --- Ensure indexes for recent_opens once per process ---
_recent_opens_indexes_ready = False

def ensure_recent_opens_indexes() -> None:
    """יוצר אינדקסים נחוצים לאוסף recent_opens פעם אחת בתהליך."""
    global _recent_opens_indexes_ready
    if _recent_opens_indexes_ready:
        return
    try:
        # השתמש ב-db גלובלי אם כבר מאותחל; אל תקרא get_db() כדי להימנע מ-deadlock בזמן אתחול
        _db = db if db is not None else None
        if _db is None:
            return
        coll = _db.recent_opens
        try:
            from pymongo import ASCENDING, DESCENDING
            coll.create_index([('user_id', ASCENDING), ('file_name', ASCENDING)], name='user_file_unique', unique=True)
            coll.create_index([('user_id', ASCENDING), ('last_opened_at', DESCENDING)], name='user_last_opened_idx')
        except Exception:
            # גם אם יצירת אינדקס נכשלה, לא נכשיל את היישום
            pass
        _recent_opens_indexes_ready = True
    except Exception:
        # אין להפיל את השרת במקרה של בעיית DB בתחילת חיים
        pass


# --- HTTP caching helpers (ETag / Last-Modified) ---
def _safe_dt_from_doc(value) -> datetime:
    """Normalize a datetime-like value from Mongo into tz-aware datetime (UTC)."""
    try:
        if isinstance(value, datetime):
            dt = value
        elif value is not None:
            # ISO string or other repr
            dt = datetime.fromisoformat(str(value))
        else:
            dt = datetime.now(timezone.utc)
    except Exception:
        dt = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _compute_file_etag(doc: Dict[str, Any]) -> str:
    """Compute a weak ETag for a file document based on updated_at and raw content.

    We intentionally include only fields that impact the rendered output to keep
    the validator stable but sensitive to relevant changes.
    """
    try:
        updated_at = doc.get('updated_at')
        if isinstance(updated_at, datetime):
            updated_str = updated_at.isoformat()
        elif updated_at is not None:
            updated_str = str(updated_at)
        else:
            updated_str = ''
    except Exception:
        updated_str = ''
    raw_code = (doc.get('code') or '')
    file_name = (doc.get('file_name') or '')
    version = str(doc.get('version') or '')
    # Hash a compact JSON string of identifying fields + content digest
    try:
        payload = json.dumps({
            'u': updated_str,
            'n': file_name,
            'v': version,
            'sha': hashlib.sha256(raw_code.encode('utf-8')).hexdigest(),
        }, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
        tag = hashlib.sha256(payload.encode('utf-8')).hexdigest()[:16]
        return f'W/"{tag}"'
    except Exception:
        # Fallback: time-based weak tag
        return f'W/"{int(time.time())}"'


# --- Ensure indexes for code_snippets once per process ---
_code_snippets_indexes_ready = False

def ensure_code_snippets_indexes() -> None:
    """יוצר אינדקסים קריטיים עבור אוסף code_snippets פעם אחת בתהליך.

    אינדקסים:
    - (user_id, created_at)
    - (user_id, programming_language)
    - (user_id, tags)
    - (user_id, is_favorite)
    - Text index על (file_name, description, tags) – אם אין כבר.
    """
    global _code_snippets_indexes_ready
    if _code_snippets_indexes_ready:
        return
    try:
        # השתמש ב-db גלובלי אם כבר מאותחל; אל תקרא get_db() כדי להימנע מ-deadlock בזמן אתחול
        _db = db if db is not None else None
        if _db is None:
            return
        coll = _db.code_snippets
        try:
            from pymongo import ASCENDING, DESCENDING
            # זוגות פשוטים
            try:
                coll.create_index([('user_id', ASCENDING), ('created_at', DESCENDING)], name='user_created_at', background=True)
            except Exception:
                pass
            try:
                coll.create_index([('user_id', ASCENDING), ('programming_language', ASCENDING)], name='user_lang', background=True)
            except Exception:
                pass
            try:
                coll.create_index([('user_id', ASCENDING), ('tags', ASCENDING)], name='user_tags', background=True)
            except Exception:
                pass
            try:
                coll.create_index([('user_id', ASCENDING), ('is_favorite', ASCENDING)], name='user_favorite', background=True)
            except Exception:
                pass

            # Text index – רק אם לא קיים כבר אינדקס מסוג text
            try:
                has_text = False
                try:
                    for ix in coll.list_indexes():
                        for k, spec in ix.to_dict().get('key', {}).items():
                            if str(spec).lower() == 'text':
                                has_text = True
                                break
                        if has_text:
                            break
                except Exception:
                    # Fallback ל-index_information()
                    try:
                        for _name, info in (coll.index_information() or {}).items():
                            key = info.get('key') or []
                            for pair in key:
                                if isinstance(pair, (list, tuple)) and len(pair) >= 2 and str(pair[1]).lower() == 'text':
                                    has_text = True
                                    break
                            if has_text:
                                break
                    except Exception:
                        has_text = False
                if not has_text:
                    coll.create_index([
                        ('file_name', 'text'),
                        ('description', 'text'),
                        ('tags', 'text'),
                    ], name='text_file_desc_tags', background=True)
            except Exception:
                pass
        except Exception:
            # אם pymongo לא נטען/סביבת Docs – לא נכשיל
            pass
        _code_snippets_indexes_ready = True
    except Exception:
        # אין להפיל את האפליקציה במקרה של בעיית DB בתחילת חיים
        pass

# (הוסר שימוש ב-before_first_request; ראה הקריאה בתוך get_db למניעת שגיאה בפלאסק 3)


# --- Cursor encoding helpers for pagination ---
def _encode_cursor(created_at: datetime, oid: ObjectId) -> str:
    try:
        dt = created_at if isinstance(created_at, datetime) else _safe_dt_from_doc(created_at)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        ts = int(dt.timestamp())
    except Exception:
        ts = int(time.time())
    try:
        raw = json.dumps({'t': ts, 'id': str(oid)}, separators=(',', ':'), sort_keys=True).encode('utf-8')
        return base64.urlsafe_b64encode(raw).rstrip(b'=').decode('ascii')
    except Exception:
        return ''


def _decode_cursor(cursor: str) -> tuple[datetime | None, ObjectId | None]:
    if not cursor:
        return (None, None)
    try:
        padding = '=' * (-len(cursor) % 4)
        data = base64.urlsafe_b64decode((cursor + padding).encode('ascii'))
        obj = json.loads(data.decode('utf-8'))
        ts = int(obj.get('t'))
        oid_str = str(obj.get('id') or '')
        last_dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        last_oid = ObjectId(oid_str) if oid_str else None
        return (last_dt, last_oid)
    except Exception:
        return (None, None)

# --- Simple in-process cache for external uptime calls ---
_uptime_cache_lock = threading.Lock()
_uptime_cache: Dict[str, Any] = {
    'data': None,
    'provider': None,
    'fetched_at': 0.0,
}

def _get_uptime_cached() -> Optional[Dict[str, Any]]:
    now_ts = time.time()
    with _uptime_cache_lock:
        data = _uptime_cache.get('data')
        ts = float(_uptime_cache.get('fetched_at') or 0)
        if data and (now_ts - ts) < UPTIME_CACHE_TTL_SECONDS:
            return data
    return None

def _set_uptime_cache(payload: Dict[str, Any]) -> None:
    with _uptime_cache_lock:
        _uptime_cache['data'] = payload
        _uptime_cache['provider'] = UPTIME_PROVIDER
        _uptime_cache['fetched_at'] = time.time()

def _fetch_uptime_from_betteruptime() -> Optional[Dict[str, Any]]:
    if not (UPTIME_API_KEY and UPTIME_MONITOR_ID):
        return None
    try:
        # SLA endpoint per issue suggestion
        url = f'https://uptime.betterstack.com/api/v2/monitors/{UPTIME_MONITOR_ID}/sla'
        headers = {'Authorization': f'Bearer {UPTIME_API_KEY}'}
        resp = http_request('GET', url, headers=headers, timeout=8)
        if resp.status_code != 200:
            return None
        body = resp.json() if resp.content else {}
        # Normalize output
        availability = None
        try:
            availability = float(((body or {}).get('data') or {}).get('availability') or 0)
        except Exception:
            availability = None
        result = {
            'provider': 'betteruptime',
            'uptime_percentage': round(availability, 2) if isinstance(availability, (int, float)) else None,
            'raw': body,
            'status_url': UPTIME_STATUS_URL or None,
        }
        return result
    except Exception:
        return None

def _fetch_uptime_from_uptimerobot() -> Optional[Dict[str, Any]]:
    """Fetch uptime from UptimeRobot.

    Notes:
    - UptimeRobot v2 מחזיר שדה custom_uptime_ratios (לא ranges) כשמבקשים יחסי זמינות
      עבור X ימים אחרונים. ערך '1' משמע 24 שעות אחרונות.
    - נתמוך גם ב-custom_uptime_ranges אם יוחזר (תאימות עתידית/ישנה).
    """
    if not UPTIME_API_KEY:
        return None
    try:
        url = 'https://api.uptimerobot.com/v2/getMonitors'
        payload = {
            'api_key': UPTIME_API_KEY,
            # יחס זמינות ל-1 יום (24 שעות)
            'custom_uptime_ratios': '1',
            'format': 'json',
        }
        # אם זה לא מפתח monitor‑specific (שמתחיל ב-'m'), ונמסר מזהה monitor – נשלח אותו
        try:
            api_key_is_monitor_specific = str(UPTIME_API_KEY).strip().lower().startswith('m')
        except Exception:
            api_key_is_monitor_specific = False
        if UPTIME_MONITOR_ID and not api_key_is_monitor_specific:
            payload['monitors'] = UPTIME_MONITOR_ID
        # שמירה על זמן תגובה קצר בעמוד הבית – timeout אגרסיבי כדי לא לחסום את ה-WSGI
        resp = http_request('POST', url, data=payload, timeout=3)
        if resp.status_code != 200:
            return None
        body = resp.json() if resp.content else {}
        monitors = (body or {}).get('monitors') or []
        uptime_percentage = None
        if (body or {}).get('stat') == 'fail':
            return None
        if monitors:
            # נסה את כל הוריאציות הידועות
            val = (
                monitors[0].get('custom_uptime_ratio') or
                monitors[0].get('custom_uptime_ratios') or
                monitors[0].get('custom_uptime_range') or
                monitors[0].get('custom_uptime_ranges')
            )
            try:
                if isinstance(val, str):
                    # custom_uptime_ratios יכול להיות "99.99" או "99.99-..." – ניקח את הראשון
                    first = val.split('-')[0].strip()
                    uptime_percentage = round(float(first), 2)
                elif isinstance(val, (int, float)):
                    uptime_percentage = round(float(val), 2)
            except Exception:
                uptime_percentage = None
        return {
            'provider': 'uptimerobot',
            'uptime_percentage': uptime_percentage,
            'raw': body,
            'status_url': UPTIME_STATUS_URL or None,
        }
    except Exception:
        return None

def fetch_external_uptime() -> Optional[Dict[str, Any]]:
    """Fetch uptime according to configured provider with basic caching."""
    # Return from cache if fresh
    cached = _get_uptime_cached()
    if cached is not None:
        return cached
    result: Optional[Dict[str, Any]] = None
    provider = (UPTIME_PROVIDER or '').strip().lower()
    if provider == 'betteruptime':
        result = _fetch_uptime_from_betteruptime()
    elif provider == 'uptimerobot':
        result = _fetch_uptime_from_uptimerobot()
    elif provider in {'statuscake', 'pingdom'}:
        # Not implemented: fall back to None to avoid errors
        result = None
    if result is not None:
        _set_uptime_cache(result)
    return result

def get_internal_share(share_id: str) -> Optional[Dict[str, Any]]:
    """שליפת שיתוף פנימי מה-DB (internal_shares) עם בדיקת תוקף."""
    try:
        db = get_db()
        coll = db.internal_shares
        doc = coll.find_one({"share_id": share_id})
        if not doc:
            return None
        # TTL אמור לטפל במחיקה, אבל אם עדיין לא נמחק — נבדוק תוקף ידנית באופן חסין tz
        exp = doc.get("expires_at")
        if isinstance(exp, datetime):
            exp_aware = exp if exp.tzinfo is not None else exp.replace(tzinfo=timezone.utc)
            now_utc = datetime.now(timezone.utc)
            if exp_aware < now_utc:
                return None
        elif isinstance(exp, str):
            try:
                exp_dt = datetime.fromisoformat(exp)
                exp_aware = exp_dt if exp_dt.tzinfo is not None else exp_dt.replace(tzinfo=timezone.utc)
                if exp_aware < datetime.now(timezone.utc):
                    return None
            except Exception:
                pass
        try:
            coll.update_one({"_id": doc["_id"]}, {"$inc": {"views": 1}})
        except Exception:
            pass
        return doc
    except Exception as e:
        logger.exception("Error fetching internal share")
        return None

# Telegram Login Widget Verification
def verify_telegram_auth(auth_data: Dict[str, Any]) -> bool:
    """מאמת את הנתונים מ-Telegram Login Widget"""
    check_hash = auth_data.get('hash')
    if not check_hash:
        return False
    
    # יצירת data-check-string
    data_items = []
    for key, value in sorted(auth_data.items()):
        if key != 'hash':
            data_items.append(f"{key}={value}")
    
    data_check_string = '\n'.join(data_items)
    
    # חישוב hash
    secret_key = hashlib.sha256(BOT_TOKEN.encode()).digest()
    calculated_hash = hmac.new(
        secret_key,
        data_check_string.encode(),
        hashlib.sha256
    ).hexdigest()
    
    # בדיקת תוקף
    if calculated_hash != check_hash:
        return False
    
    # בדיקת זמן (עד שעה מהחתימה)
    auth_date = int(auth_data.get('auth_date', 0))
    if (time.time() - auth_date) > 3600:
        return False
    
    return True

def login_required(f):
    """דקורטור לבדיקת התחברות"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            # אם זו בקשת API או שהלקוח מצפה ל-JSON – נחזיר 401 JSON כדי שה-frontend יפנה ל-/login
            try:
                wants_json = (
                    (request.path or '').startswith('/api/') or
                    ('application/json' in (request.headers.get('Accept') or ''))
                )
            except Exception:
                wants_json = False
            if wants_json:
                return jsonify({'error': 'נדרש להתחבר'}), 401
            # אחרת: הפניה רגילה לעמוד ההתחברות, עם next לחזרה
            next_url = request.full_path if request.query_string else request.path
            return redirect(url_for('login', next=next_url))
        return f(*args, **kwargs)
    return decorated_function

# before_request: אם אין סשן אבל יש cookie "remember_me" תקף — נבצע התחברות שקופה
@app.before_request
def try_persistent_login():
    try:
        if 'user_id' in session:
            return
        token = request.cookies.get(REMEMBER_COOKIE_NAME)
        if not token:
            return
        db = get_db()
        doc = db.remember_tokens.find_one({
            'token': token
        })
        if not doc:
            return
        # בדיקת תוקף
        exp = doc.get('expires_at')
        now = datetime.now(timezone.utc)
        if isinstance(exp, datetime):
            if exp < now:
                return
        else:
            try:
                if datetime.fromisoformat(str(exp)) < now:
                    return
            except Exception:
                return
        # שחזור סשן בסיסי
        user_id = int(doc.get('user_id'))
        user = db.users.find_one({'user_id': user_id}) or {}
        session['user_id'] = user_id
        session['user_data'] = {
            'id': user_id,
            'first_name': user.get('first_name', ''),
            'last_name': user.get('last_name', ''),
            'username': user.get('username', ''),
            'photo_url': '',
            'has_seen_welcome_modal': bool(user.get('has_seen_welcome_modal', False))
        }
        session.permanent = True
    except Exception:
        # אל תכשיל בקשות בגלל כשל חיבור/פרסר
        pass


@app.before_request
def _correlation_bind():
    """Bind a short request_id to structlog context and store for response header."""
    try:
        try:
            incoming = str(request.headers.get("X-Request-ID", "")).strip()
        except Exception:
            incoming = ""
        rid = incoming or (_gen_rid() or "")
        if rid:
            try:
                _bind_rid(rid)
            except Exception:
                pass
            try:
                # attach to request for after_request header
                setattr(request, "_req_id", rid)
            except Exception:
                pass
            try:
                set_current_span_attributes({"request_id": rid})
            except Exception:
                pass
        try:
            uid = session.get("user_id") if "user_id" in session else None
        except Exception:
            uid = None
        try:
            bind_user_context(user_id=uid)
        except Exception:
            pass
        try:
            ctx = get_observability_context() or {}
        except Exception:
            ctx = {}
        try:
            updates: Dict[str, Any] = {}
            if isinstance(ctx, dict):
                if ctx.get("user_id"):
                    updates["user_id_hash"] = ctx["user_id"]
                if ctx.get("chat_id"):
                    updates["chat_id_hash"] = ctx["chat_id"]
            if updates:
                set_current_span_attributes(updates)
        except Exception:
            pass
        try:
            method = getattr(request, "method", "") or ""
            endpoint = getattr(request, "endpoint", "") or ""
            path_hint = getattr(request, "path", "") or ""
            identifier = endpoint or path_hint
            if identifier:
                cmd = f"webapp:{method.upper()}:{identifier}" if method else f"webapp:{identifier}"
                bind_command(cmd)
                try:
                    set_current_span_attributes({"command": cmd})
                except Exception:
                    pass
        except Exception:
            pass
    except Exception:
        pass


@app.after_request
def _add_request_id_header(resp):
    try:
        rid = getattr(request, "_req_id", "")
        if rid:
            resp.headers["X-Request-ID"] = rid
    except Exception:
        pass
    return resp


@app.before_request
def _metrics_start_timer():  # minimal, best-effort
    try:
        request._metrics_start = _time.perf_counter( )
        setattr(g, "_otel_cache_hit", None)
    except Exception:
        pass


@app.after_request
def _metrics_after(resp):
    try:
        start = float(getattr(request, "_metrics_start", 0.0) or 0.0)
        if start:
            dur = max(0.0, float(_time.perf_counter() - start))
            status = int(getattr(resp, "status_code", 0) or 0)
            endpoint = getattr(request, "endpoint", None)
            handler_label = endpoint or getattr(request, "path", "")
            cache_flag = getattr(g, "_otel_cache_hit", None)
            record_request_outcome(
                status,
                dur,
                source="webapp",
                handler=handler_label,
                cache_hit=cache_flag,
            )
            try:
                method = getattr(request, "method", "GET")
                record_http_request(method, endpoint, status, dur)
            except Exception:
                pass
            # מדידת זמן "בקשה ראשונה" מול זמן אתחול התהליך
            try:
                global _FIRST_REQUEST_RECORDED
                if not _FIRST_REQUEST_RECORDED:
                    with _FIRST_REQUEST_LOCK:
                        if not _FIRST_REQUEST_RECORDED:
                            note_first_request_latency()
                            _FIRST_REQUEST_RECORDED = True
            except Exception:
                pass
    except Exception:
        pass
    return resp


@app.after_request
def _otel_record_response(resp):
    try:
        setattr(g, "_otel_response_status", int(getattr(resp, "status_code", 0) or 0))
    except Exception:
        setattr(g, "_otel_response_status", None)
    span = getattr(g, "_otel_span", None)
    if span is not None:
        try:
            span.set_attribute("http.status_code", int(getattr(resp, "status_code", 0) or 0))  # type: ignore[attr-defined]
        except Exception:
            pass
        try:
            cache_hit_flag = getattr(g, "_otel_cache_hit", None)
            if cache_hit_flag is not None:
                span.set_attribute("cache_hit", bool(cache_hit_flag))  # type: ignore[attr-defined]
        except Exception:
            pass
        try:
            code = int(getattr(resp, "status_code", 0) or 0)
            span.set_attribute("status", "error" if code >= 500 else "ok")  # type: ignore[attr-defined]
        except Exception:
            pass
    return resp


@app.teardown_request
def _otel_teardown_request(exc):
    span_cm = getattr(g, "_otel_span_cm", None)
    if span_cm is None:
        return
    span = getattr(g, "_otel_span", None)
    if span is not None and exc is not None:
        try:
            span.set_attribute("status", "error")  # type: ignore[attr-defined]
            span.set_attribute("error_signature", type(exc).__name__)  # type: ignore[attr-defined]
        except Exception:
            pass
    status_code = getattr(g, "_otel_response_status", None)
    if span is not None and status_code is not None:
        try:
            span.set_attribute("http.status_code", int(status_code))  # type: ignore[attr-defined]
        except Exception:
            pass
    cache_hit_flag = getattr(g, "_otel_cache_hit", None)
    if span is not None and cache_hit_flag is not None:
        try:
            span.set_attribute("cache_hit", bool(cache_hit_flag))  # type: ignore[attr-defined]
        except Exception:
            pass
    if exc is None:
        span_cm.__exit__(None, None, None)
    else:
        span_cm.__exit__(type(exc), exc, getattr(exc, "__traceback__", None))
    setattr(g, "_otel_span_cm", None)
    setattr(g, "_otel_span", None)
    setattr(g, "_otel_response_status", None)
    setattr(g, "_otel_cache_hit", None)


# --- Slow request logging (server-side) ---
@app.after_request
def _log_slow_request(resp):
    try:
        start = float(getattr(request, "_metrics_start", 0.0) or 0.0)
        if not start:
            return resp
        dur_ms = ( _time.perf_counter() - start ) * 1000.0
        try:
            slow_ms = float(os.getenv("SLOW_MS", "0") or 0)
        except Exception:
            slow_ms = 0.0
        if slow_ms and dur_ms > slow_ms:
            try:
                logger.warning(
                    "slow_request",
                    extra={
                        "path": getattr(request, "path", "") or "",
                        "method": getattr(request, "method", "GET"),
                        "status": int(getattr(resp, "status_code", 0) or 0),
                        "ms": round(dur_ms, 1),
                    },
                )
            except Exception:
                pass
    except Exception:
        pass
    return resp

# --- Default CSP for HTML pages (allows CodeMirror ESM + workers) ---
@app.after_request
def _add_default_csp(resp):
    """Set a safe, permissive-enough CSP for HTML pages by default.

    - Allows dynamic ESM imports from common CDNs used by the webapp
    - Allows blob: for workers required by some CodeMirror features
    - Keeps frame-ancestors restricted to self

    Note: Route-specific responses that already set CSP (e.g. raw HTML preview)
    remain authoritative; we only add this header if it's missing.
    """
    try:
        if 'Content-Security-Policy' not in resp.headers:
            content_type = resp.headers.get('Content-Type', '')
            if isinstance(content_type, str) and 'text/html' in content_type:
                resp.headers['Content-Security-Policy'] = (
                    "default-src 'self'; "
                    "base-uri 'self'; "
                    "frame-ancestors 'self'; "
                    # Scripts: allow our origin, inline (for small in-page helpers), blob workers, and ESM from CDNs
                    "script-src 'self' 'unsafe-inline' blob: https://cdn.jsdelivr.net https://unpkg.com https://esm.sh https://telegram.org; "
                    # Workers used by some CM6 language/tooling integrations
                    "worker-src blob:; "
                    # Styles: local + inline + Google Fonts CSS + Font Awesome from cdnjs
                    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdnjs.cloudflare.com https://cdn.jsdelivr.net; "
                    # Fonts: local + Google Fonts + Font Awesome webfonts + data: (icons)
                    "font-src 'self' https://fonts.gstatic.com https://cdnjs.cloudflare.com data:; "
                    # Images: local + data/blob (thumbnails, inline previews)
                    "img-src 'self' data: blob: https://telegram.org; "
                    # XHR/fetch for ESM modules and assets
                    "connect-src 'self' https://cdn.jsdelivr.net https://unpkg.com https://esm.sh https://oauth.telegram.org https://telegram.org; "
                    # Frames: allow Telegram OAuth widget iframes
                    "frame-src 'self' https://oauth.telegram.org https://telegram.org;"
                )
    except Exception:
        # Never break responses due to header set failures
        pass
    return resp


# === Alertmanager Webhook endpoint (optional integration) ===
# מאפשר להפנות התראות מ-Alertmanager ישירות לבוט/טלגרם דרך alert_forwarder
@app.route('/alertmanager/webhook', methods=['POST'])
def alertmanager_webhook():
    try:
        # --- Basic authentication/guard ---
        secret = os.getenv('ALERTMANAGER_WEBHOOK_SECRET', '').strip()
        allow_ips = {ip.strip() for ip in (os.getenv('ALERTMANAGER_IP_ALLOWLIST') or '').split(',') if ip.strip()}

        def _client_ip() -> str:
            try:
                xff = (request.headers.get('X-Forwarded-For') or '').split(',')[0].strip()
                return xff or (request.remote_addr or '')
            except Exception:
                return request.remote_addr or ''

        ok_secret = True
        ok_ip = True
        # If a secret is configured, require matching header or query token
        if secret:
            token = request.headers.get('X-Alertmanager-Token') or request.args.get('token') or ''
            ok_secret = (token.strip() == secret)
        # If an IP allow-list is configured, require client IP in the list
        if allow_ips:
            ok_ip = (_client_ip() in allow_ips)

        # Enforce guards when configured
        if (secret and not ok_secret) or (allow_ips and not ok_ip):
            return jsonify({"status": "forbidden"}), 403

        payload = request.get_json(silent=True) or {}
        alerts = payload.get('alerts') or []
        if isinstance(alerts, list) and alerts:
            try:
                _forward_alerts(alerts)
            except Exception:
                pass
            return jsonify({"status": "ok", "forwarded": len(alerts)}), 200
        return jsonify({"status": "no_alerts"}), 200
    except Exception:
        return jsonify({"status": "error"}), 200

def admin_required(f):
    """דקורטור לבדיקת הרשאות אדמין"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        
        # בדיקה אם המשתמש הוא אדמין
        admin_ids_env = os.getenv('ADMIN_USER_IDS', '')
        admin_ids_list = admin_ids_env.split(',') if admin_ids_env else []
        admin_ids = [int(x.strip()) for x in admin_ids_list if x.strip().isdigit()]
        
        if session['user_id'] not in admin_ids:
            abort(403)  # Forbidden
        
        return f(*args, **kwargs)
    return decorated_function

def is_admin(user_id: int) -> bool:
    """בודק אם משתמש הוא אדמין"""
    admin_ids_env = os.getenv('ADMIN_USER_IDS', '')
    admin_ids_list = admin_ids_env.split(',') if admin_ids_env else []
    admin_ids = [int(x.strip()) for x in admin_ids_list if x.strip().isdigit()]
    return user_id in admin_ids

def is_premium(user_id: int) -> bool:
    """בודק אם משתמש הוא פרימיום לפי ENV PREMIUM_USER_IDS"""
    try:
        premium_ids_env = os.getenv('PREMIUM_USER_IDS', '')
        premium_ids_list = premium_ids_env.split(',') if premium_ids_env else []
        premium_ids = [int(x.strip()) for x in premium_ids_list if x.strip().isdigit()]
        return user_id in premium_ids
    except Exception:
        return False


# --- Snippet library admin UI ---
try:
    from services import snippet_library_service as _snip_service  # type: ignore
except Exception:
    _snip_service = None  # type: ignore


@app.route('/admin/snippets/pending')
@admin_required
def admin_snippets_pending():
    items = []
    try:
        if _snip_service is not None:
            items = _snip_service.list_pending_snippets(limit=200, skip=0)
    except Exception:
        items = []
    return render_template('admin_snippets_pending.html', items=items)


@app.route('/admin/snippets/approve')
@admin_required
def admin_snippet_approve():
    item_id = request.args.get('id') or ''
    try:
        if _snip_service is not None and item_id:
            # שלוף user_id לפני שינוי הסטטוס כדי למנוע החטאות לאחר עדכון
            pre_uid = 0
            doc = None
            try:
                from database import db as _db
                coll = getattr(_db, 'snippets_collection', None)
                if coll is None:
                    coll = getattr(_db.db, 'snippets')
                normalized_id = _db._get_repo()._normalize_snippet_identifier(item_id)
                doc = coll.find_one({'_id': normalized_id}) if (normalized_id is not None and coll is not None) else None
                pre_uid = int((doc or {}).get('user_id') or 0)
            except Exception:
                pre_uid = 0

            ok = _snip_service.approve_snippet(item_id, int(session.get('user_id')))
            # שליחת הודעה ידידותית למגיש הסניפט (כמו בבוט)
            if ok:
                uid = pre_uid
                if uid <= 0:
                    # fallback: נסה לאחר עדכון אם לא הצלחנו קודם
                    try:
                        from database import db as _db
                        coll = getattr(_db, 'snippets_collection', None)
                        if coll is None:
                            coll = getattr(_db.db, 'snippets')
                        normalized_id = _db._get_repo()._normalize_snippet_identifier(item_id)
                        post_doc = coll.find_one({'_id': normalized_id}) if (normalized_id is not None and coll is not None) else None
                        uid = int((post_doc or {}).get('user_id') or 0)
                    except Exception:
                        uid = 0
                if uid > 0:
                    try:
                        # base URL להצגה למשתמש
                        base = (PUBLIC_BASE_URL or WEBAPP_URL or request.host_url or '').rstrip('/')
                        text = (
                            "🎉 איזה כיף! הסניפט שלך אושר והתווסף לספריית הסניפטים.\n"
                            f"אפשר לצפות כאן: {base}/snippets"
                        )
                        # שלח דרך Telegram Bot API
                        import os as _os
                        bot_token = _os.getenv('BOT_TOKEN', '')
                        if bot_token:
                            try:
                                try:
                                    from http_sync import request as _http_request  # type: ignore
                                except Exception:  # pragma: no cover
                                    _http_request = None  # type: ignore
                                api = f"https://api.telegram.org/bot{bot_token}/sendMessage"
                                payload = {"chat_id": uid, "text": text}
                                if _http_request is not None:
                                    _http_request('POST', api, json=payload, timeout=5)
                                else:  # pragma: no cover
                                    import requests as _requests  # type: ignore
                                    _requests.post(api, json=payload, timeout=5)
                            except Exception:
                                pass
                    except Exception:
                        pass
    except Exception:
        pass
    return redirect(url_for('admin_snippets_pending'))


@app.route('/admin/snippets/reject')
@admin_required
def admin_snippet_reject():
    item_id = request.args.get('id') or ''
    reason = request.args.get('reason') or ''
    try:
        if _snip_service is not None and item_id:
            # שלוף user_id לפני שינוי הסטטוס כדי להבטיח שיודיעו למגיש הנכון
            pre_uid = 0
            try:
                from database import db as _db
                coll = getattr(_db, 'snippets_collection', None)
                if coll is None:
                    coll = getattr(_db.db, 'snippets')
                normalized_id = _db._get_repo()._normalize_snippet_identifier(item_id)
                pre_doc = coll.find_one({'_id': normalized_id}) if (normalized_id is not None and coll is not None) else None
                pre_uid = int((pre_doc or {}).get('user_id') or 0)
            except Exception:
                pre_uid = 0

            ok = _snip_service.reject_snippet(item_id, int(session.get('user_id')), reason)
            # שליחת הודעה ידידותית למגיש הסניפט (כמו בבוט)
            if ok:
                uid = pre_uid
                if uid <= 0:
                    try:
                        from database import db as _db
                        coll = getattr(_db, 'snippets_collection', None)
                        if coll is None:
                            coll = getattr(_db.db, 'snippets')
                        normalized_id = _db._get_repo()._normalize_snippet_identifier(item_id)
                        post_doc = coll.find_one({'_id': normalized_id}) if (normalized_id is not None and coll is not None) else None
                        uid = int((post_doc or {}).get('user_id') or 0)
                    except Exception:
                        uid = 0
                if uid > 0:
                    try:
                        text = (
                            "🙂 תודה על ההגשה! כרגע ההצעה לא אושרה.\n"
                            f"סיבה: {reason or '—'}\n"
                            "נשמח לשינויים קטנים ולהגשה מחדש."
                        )
                        import os as _os
                        bot_token = _os.getenv('BOT_TOKEN', '')
                        if bot_token:
                            try:
                                try:
                                    from http_sync import request as _http_request  # type: ignore
                                except Exception:  # pragma: no cover
                                    _http_request = None  # type: ignore
                                api = f"https://api.telegram.org/bot{bot_token}/sendMessage"
                                payload = {"chat_id": uid, "text": text}
                                if _http_request is not None:
                                    _http_request('POST', api, json=payload, timeout=5)
                                else:  # pragma: no cover
                                    import requests as _requests  # type: ignore
                                    _requests.post(api, json=payload, timeout=5)
                            except Exception:
                                pass
                    except Exception:
                        pass
    except Exception:
        pass
    return redirect(url_for('admin_snippets_pending'))


@app.route('/admin/snippets/view')
@admin_required
def admin_snippet_view():
    item_id = request.args.get('id') or ''
    doc = None
    try:
        if _snip_service is not None and item_id:
            # גישה ישירה לקולקציה כדי להביא את גוף הקוד המלא
            from database import db as _db
            coll = getattr(_db, 'snippets_collection', None)
            if coll is None:
                coll = getattr(_db.db, 'snippets')
            # שימוש בנרמול מזהה דרך ה-Repository
            normalized_id = _db._get_repo()._normalize_snippet_identifier(item_id)
            if normalized_id is not None and coll is not None:
                raw = coll.find_one({'_id': normalized_id})
                if isinstance(raw, dict):
                    doc = {
                        'title': raw.get('title', ''),
                        'description': raw.get('description', ''),
                        'language': raw.get('language', 'text'),
                        'username': raw.get('username', ''),
                        'code': raw.get('code', ''),
                        'status': raw.get('status', ''),
                        'submitted_at': raw.get('submitted_at'),
                        'approved_at': raw.get('approved_at'),
                    }
    except Exception:
        doc = None
    return render_template('admin_snippet_view.html', item=doc, item_id=item_id)


@app.route('/admin/snippets/delete', methods=['POST'])
@admin_required
def admin_snippet_delete():
    item_id = request.args.get('id') or request.form.get('id') or ''
    try:
        from database import db as _db
        coll = getattr(_db, 'snippets_collection', None)
        if coll is None:
            coll = getattr(_db.db, 'snippets')
        normalized_id = _db._get_repo()._normalize_snippet_identifier(item_id)
        if normalized_id is not None and coll is not None:
            coll.delete_one({'_id': normalized_id})
    except Exception:
        pass
    return redirect(url_for('admin_snippets_pending'))


# --- Community Library: Pending management (Admin) ---
@app.route('/admin/community/pending')
@admin_required
def admin_community_pending():
    items = []
    try:
        from services import community_library_service as _cl_service  # type: ignore
    except Exception:
        _cl_service = None  # type: ignore
    try:
        if _cl_service is not None:
            items = _cl_service.list_pending(limit=200, skip=0)
    except Exception:
        items = []
    return render_template('admin_community_pending.html', items=items)


@app.route('/admin/community/approve')
@admin_required
def admin_community_approve():
    item_id = request.args.get('id') or ''
    try:
        from services import community_library_service as _cl_service  # type: ignore
    except Exception:
        _cl_service = None  # type: ignore
    try:
        if _cl_service is not None and item_id:
            # שליפת מזהה משתמש קודם לאישור (לצורך הודעה)
            pre_uid = 0
            try:
                from database import db as _db
                coll = getattr(_db, 'community_library_collection', None)
                if coll is None:
                    coll = getattr(_db.db, 'community_library_items')
                try:
                    from services.community_library_service import ObjectId as _CLObjectId  # type: ignore
                except Exception:
                    _CLObjectId = None  # type: ignore
                q = {'_id': (_CLObjectId(item_id) if _CLObjectId is not None else item_id)}
                doc = coll.find_one(q) if coll is not None else None
                pre_uid = int((doc or {}).get('user_id') or 0)
            except Exception:
                pre_uid = 0

            _cl_service.approve_item(item_id, int(session.get('user_id')))

            # שליחת הודעת Telegram ידידותית למגיש/ה (best-effort)
            try:
                uid = pre_uid
                if uid <= 0:
                    from database import db as _db
                    coll = getattr(_db, 'community_library_collection', None)
                    if coll is None:
                        coll = getattr(_db.db, 'community_library_items')
                    try:
                        from services.community_library_service import ObjectId as _CLObjectId  # type: ignore
                    except Exception:
                        _CLObjectId = None  # type: ignore
                    q = {'_id': (_CLObjectId(item_id) if _CLObjectId is not None else item_id)}
                    post_doc = coll.find_one(q) if coll is not None else None
                    uid = int((post_doc or {}).get('user_id') or 0)
                if uid > 0:
                    base = (PUBLIC_BASE_URL or WEBAPP_URL or request.host_url or '').rstrip('/')
                    text = (
                        "🎉 איזה כיף! הבקשה שלך אושרה ונוספה לאוסף הקהילה.\n"
                        f"אפשר לצפות כאן: {base}/community-library"
                    )
                    bot_token = os.getenv('BOT_TOKEN', '')
                    if bot_token:
                        try:
                            try:
                                from http_sync import request as _http_request  # type: ignore
                            except Exception:  # pragma: no cover
                                _http_request = None  # type: ignore
                            api = f"https://api.telegram.org/bot{bot_token}/sendMessage"
                            payload = {"chat_id": uid, "text": text}
                            if _http_request is not None:
                                _http_request('POST', api, json=payload, timeout=5)
                            else:  # pragma: no cover
                                import requests as _requests  # type: ignore
                                _requests.post(api, json=payload, timeout=5)
                        except Exception:
                            pass
            except Exception:
                pass
    except Exception:
        pass
    return redirect(url_for('admin_community_pending'))


@app.route('/admin/community/reject')
@admin_required
def admin_community_reject():
    item_id = request.args.get('id') or ''
    reason = request.args.get('reason') or ''
    try:
        from services import community_library_service as _cl_service  # type: ignore
    except Exception:
        _cl_service = None  # type: ignore
    try:
        if _cl_service is not None and item_id:
            pre_uid = 0
            try:
                from database import db as _db
                coll = getattr(_db, 'community_library_collection', None)
                if coll is None:
                    coll = getattr(_db.db, 'community_library_items')
                try:
                    from services.community_library_service import ObjectId as _CLObjectId  # type: ignore
                except Exception:
                    _CLObjectId = None  # type: ignore
                q = {'_id': (_CLObjectId(item_id) if _CLObjectId is not None else item_id)}
                doc = coll.find_one(q) if coll is not None else None
                pre_uid = int((doc or {}).get('user_id') or 0)
            except Exception:
                pre_uid = 0

            _cl_service.reject_item(item_id, int(session.get('user_id')), reason)

            # הודעת דחייה בטלגרם (best‑effort)
            try:
                uid = pre_uid
                if uid <= 0:
                    from database import db as _db
                    coll = getattr(_db, 'community_library_collection', None)
                    if coll is None:
                        coll = getattr(_db.db, 'community_library_items')
                    try:
                        from services.community_library_service import ObjectId as _CLObjectId  # type: ignore
                    except Exception:
                        _CLObjectId = None  # type: ignore
                    q = {'_id': (_CLObjectId(item_id) if _CLObjectId is not None else item_id)}
                    post_doc = coll.find_one(q) if coll is not None else None
                    uid = int((post_doc or {}).get('user_id') or 0)
                if uid > 0:
                    text = (
                        "🙂 תודה על ההגשה! כרגע הבקשה לא אושרה.\n"
                        f"סיבה: {reason or '—'}\n"
                        "נשמח לשינויים קטנים ולהגשה מחדש."
                    )
                    bot_token = os.getenv('BOT_TOKEN', '')
                    if bot_token:
                        try:
                            try:
                                from http_sync import request as _http_request  # type: ignore
                            except Exception:  # pragma: no cover
                                _http_request = None  # type: ignore
                            api = f"https://api.telegram.org/bot{bot_token}/sendMessage"
                            payload = {"chat_id": uid, "text": text}
                            if _http_request is not None:
                                _http_request('POST', api, json=payload, timeout=5)
                            else:  # pragma: no cover
                                import requests as _requests  # type: ignore
                                _requests.post(api, json=payload, timeout=5)
                        except Exception:
                            pass
            except Exception:
                pass
    except Exception:
        pass
    return redirect(url_for('admin_community_pending'))

@app.route('/admin/snippets/edit', methods=['GET', 'POST'])
@admin_required
def admin_snippet_edit():
    item_id = request.args.get('id') or request.form.get('id') or ''
    from database import db as _db
    coll = getattr(_db, 'snippets_collection', None)
    if coll is None:
        coll = getattr(_db.db, 'snippets')
    normalized_id = _db._get_repo()._normalize_snippet_identifier(item_id) if item_id else None
    if request.method == 'POST' and normalized_id is not None and coll is not None:
        try:
            upd = {
                'title': request.form.get('title') or '',
                'description': request.form.get('description') or '',
                'language': request.form.get('language') or 'text',
                'code': request.form.get('code') or '',
            }
            coll.update_one({'_id': normalized_id}, {'$set': upd})
            return redirect(url_for('admin_snippet_view', id=item_id))
        except Exception:
            pass
    # GET: load current
    doc = None
    try:
        if normalized_id is not None and coll is not None:
            raw = coll.find_one({'_id': normalized_id})
            if isinstance(raw, dict):
                doc = {
                    'title': raw.get('title', ''),
                    'description': raw.get('description', ''),
                    'language': raw.get('language', 'text'),
                    'code': raw.get('code', ''),
                }
    except Exception:
        doc = None
    return render_template('admin_snippet_edit.html', item=doc, item_id=item_id)


# --- Community library admin: minimal Edit/Delete ---
@app.route('/admin/community/delete', methods=['POST'])
@admin_required
def admin_community_delete():
    item_id = request.args.get('id') or request.form.get('id') or ''
    try:
        from bson import ObjectId  # type: ignore
    except Exception:
        ObjectId = None  # type: ignore
    try:
        from database import db as _db
        coll = getattr(_db, 'community_library_collection', None)
        if coll is None:
            coll = getattr(_db.db, 'community_library_items')
        if coll is not None and item_id:
            q = {'_id': ObjectId(item_id)} if ObjectId is not None else {'_id': item_id}
            coll.delete_one(q)
    except Exception:
        pass
    return redirect(url_for('community_library_page'))


@app.route('/admin/community/edit', methods=['GET', 'POST'])
@admin_required
def admin_community_edit():
    from flask import request
    try:
        from bson import ObjectId  # type: ignore
    except Exception:
        ObjectId = None  # type: ignore
    item_id = request.args.get('id') or request.form.get('id') or ''
    from database import db as _db
    coll = getattr(_db, 'community_library_collection', None)
    if coll is None:
        coll = getattr(_db.db, 'community_library_items')
    if request.method == 'POST' and coll is not None and item_id:
        try:
            q = {'_id': ObjectId(item_id)} if ObjectId is not None else {'_id': item_id}
            upd = {
                'title': request.form.get('title') or '',
                'description': request.form.get('description') or '',
                'url': request.form.get('url') or '',
            }
            coll.update_one(q, {'$set': upd})
            return redirect(url_for('community_library_page'))
        except Exception:
            pass
    # GET: load current
    doc = None
    try:
        if coll is not None and item_id:
            q = {'_id': ObjectId(item_id)} if ObjectId is not None else {'_id': item_id}
            raw = coll.find_one(q)
            if isinstance(raw, dict):
                doc = {
                    'title': raw.get('title', ''),
                    'description': raw.get('description', ''),
                    'url': raw.get('url', ''),
                }
    except Exception:
        doc = None
    return render_template('admin_community_edit.html', item=doc, item_id=item_id)
# ===== Global Content Search API =====
def _search_limiter_decorator(rule: str):
    """Wrap limiter.limit if available; return no-op otherwise."""
    if limiter is None:
        def _wrap(fn):
            return fn
        return _wrap
    try:
        return limiter.limit(rule)
    except Exception:
        def _wrap(fn):
            return fn
        return _wrap

def _limiter_exempt():
    """Return limiter.exempt if available; else identity decorator.

    מאפשר להחריג endpoints כמו /metrics ו-/health(z) ממגבלות הקצב.
    """
    if limiter is None:
        def _wrap(fn):
            return fn
        return _wrap
    try:
        return limiter.exempt
    except Exception:
        def _wrap(fn):
            return fn
        return _wrap

@app.errorhandler(429)
def _ratelimit_handler(e):
    try:
        # Metrics + structured log (best-effort, never break response)
        try:
            from metrics import rate_limit_blocked
        except Exception:
            rate_limit_blocked = None
        try:
            emit_event(
                "rate_limit_blocked",
                severity="warning",
                path=str(getattr(request, 'path', '')),
                remote=str(getattr(request, 'remote_addr', '')),
            )
        except Exception:
            pass
        try:
            if rate_limit_blocked is not None:
                # scope: נתיב, limit: לא ידוע ברמת handler – נסמן "route"
                scope = str(getattr(request, 'path', '') or 'route')
                rate_limit_blocked.labels(source="webapp", scope=scope, limit="route").inc()
        except Exception:
            pass
        payload = {
            "error": "rate_limit_exceeded",
            "message": "יותר מדי בקשות. אנא נסה שוב מאוחר יותר.",
            "retry_after": getattr(e, 'description', None),
        }
        return jsonify(payload), 429
    except Exception:
        return jsonify({"error": "rate_limit_exceeded"}), 429


def _safe_retry(*dargs, **dkwargs):
    """Wrap tenacity.retry if available, else identity decorator."""
    if retry is None or stop_after_attempt is None or wait_exponential is None:
        def _wrap(fn):
            return fn
        return _wrap
    return retry(*dargs, **dkwargs)


def _get_search_index_count() -> int:
    try:
        if search_engine and hasattr(search_engine, 'indexes'):
            return len(getattr(search_engine, 'indexes'))
    except Exception:
        pass
    return 0


# In-memory cache for search responses (bounded by TTL externally via redis cache_manager in future)
_memory_search_cache: dict[str, dict[str, dict]] = {}

def _cache_get(uid: int, key: str):
    try:
        bucket = _memory_search_cache.get(str(uid))
        if isinstance(bucket, dict):
            entry = bucket.get(key)
            if isinstance(entry, dict):
                ts = float(entry.get('ts') or 0)
                # TTL: 5 minutes
                if (time.time() - ts) > 300:
                    try:
                        del bucket[key]
                    except Exception:
                        pass
                    return None
                return entry.get('results')
    except Exception:
        return None
    return None


def _cache_set(uid: int, key: str, value: dict):
    try:
        bucket = _memory_search_cache.setdefault(str(uid), {})
        if isinstance(bucket, dict):
            bucket[key] = {'results': value, 'ts': time.time()}
    except Exception:
        pass


@_safe_retry(
    stop=stop_after_attempt(3) if stop_after_attempt else None,
    wait=wait_exponential(multiplier=1, min=1, max=8) if wait_exponential else None,
)
def _safe_search(user_id: int, query: str, **kwargs):
    """Wrapper לביצוע חיפוש באופן עמיד לתקלות.

    אם מנוע החיפוש המלא אינו זמין (למשל ייבוא נכשל בגלל ENV חסרים),
    נשתמש ב-Fallback פשוט שמבצע חיפוש substring ב-DB ישירות.
    """
    # ניסיון להשתמש במנוע המלא אם זמין
    engine_results = None
    if search_engine:
        try:
            engine_results = search_engine.search(user_id, query, **kwargs)
            # אם המנוע החזיר תוצאות – נחזיר אותן. אם החזיר ריק, ננסה נפילה לאחור ל-DB.
            if isinstance(engine_results, list) and len(engine_results) > 0:
                return engine_results
        except Exception:
            # ניפול ל-fallback הבסיסי במקרה של תקלה
            engine_results = None

    # Fallback: חיפוש בסיסי ב-MongoDB על תוכן הקבצים (code)
    try:
        db = get_db()
    except Exception:
        return []

    # הגבלת תוצאות כוללת (כמו באסטרטגיית total_limit)
    try:
        total_limit = int(kwargs.get('limit') or 50)
    except Exception:
        total_limit = 50

    # החלטה האם לבצע Regex גולמי או חיפוש מחרוזת רגיל (ברירת מחדל: רגיל)
    st = kwargs.get('search_type')
    try:
        is_regex = (getattr(st, 'name', '') == 'REGEX') or (str(st).lower() == 'regex')
    except Exception:
        is_regex = False

    # בניית ביטוי החיפוש ל-$regex (רגיש/לא רגיש)
    pattern = query if is_regex else re.escape(query)

    # בניית match בסיסי
    match_stage = {
        'user_id': user_id,
        '$or': [
            {'is_active': True},
            {'is_active': {'$exists': False}},
        ],
        'code': {
            '$regex': pattern,
            '$options': 'i',  # חיפוש לא רגיש לאותיות גדולות/קטנות
        },
    }

    # ניסיון להחיל מסננים בסיסיים אם הועברו
    filters = kwargs.get('filters')
    try:
        if filters:
            langs = list(getattr(filters, 'languages', []) or [])
            if langs:
                match_stage['programming_language'] = {'$in': langs}
            tags = list(getattr(filters, 'tags', []) or [])
            if tags:
                match_stage['tags'] = {'$in': tags}
    except Exception:
        pass

    pipeline = [
        {'$match': match_stage},
        {'$sort': {'file_name': 1, 'version': -1}},
        {'$group': {'_id': '$file_name', 'latest': {'$first': '$$ROOT'}}},
        {'$replaceRoot': {'newRoot': '$latest'}},
        {'$sort': {'updated_at': -1}},
        {'$limit': total_limit},
    ]

    try:
        docs = list(db.code_snippets.aggregate(pipeline, allowDiskUse=True))
    except Exception:
        return []

    # החזרת מבנה תוצאות הדומה למנוע המלא
    from types import SimpleNamespace
    results: list = []
    # קומפילציה ל-highlight תואם Unicode בצורה בטוחה: תמיד escap‎e לקלט משתמש
    # (גם במצב regex) כדי למנוע החדרת תבניות רגקס. ההדגשה היא ליטרלית בלבד.
    try:
        comp = re.compile(re.escape(query), re.IGNORECASE | re.MULTILINE)
    except Exception:
        comp = None

    for doc in docs:
        code_text = str(doc.get('code') or '')

        # יצירת snippet ו-highlight מדויקים לפי span של regex (Unicode-safe)
        snippet = ''
        highlight_ranges = []
        match_start = -1
        match_end = -1
        if comp is not None:
            m = comp.search(code_text)
            if m:
                match_start, match_end = m.start(), m.end()
                start = max(0, match_start - 50)
                end = min(len(code_text), match_end + 50)
                snippet = code_text[start:end]
                rel_start = match_start - start
                rel_end = match_end - start
                highlight_ranges = [(rel_start, rel_end)]

        # ניקוד פשוט לפי שכיחות ביחס לאורך המסמך (סופרים הופעות ע"י regex)
        try:
            occurrences = sum(1 for _ in comp.finditer(code_text)) if comp is not None else 0
        except Exception:
            occurrences = 1 if match_start >= 0 else 0
        denom = max(1, len(code_text))
        score = min((occurrences or (1 if match_start >= 0 else 0)) / (denom / 1000.0), 10.0)

        # בניית אובייקט תוצאה עם תכונות כפי שמצופה downstream
        results.append(SimpleNamespace(
            file_name=str(doc.get('file_name') or ''),
            content=code_text,
            programming_language=str(doc.get('programming_language') or ''),
            tags=list(doc.get('tags') or []),
            created_at=doc.get('created_at') or datetime.now(timezone.utc),
            updated_at=doc.get('updated_at') or datetime.now(timezone.utc),
            version=int(doc.get('version') or 1),
            relevance_score=float(score),
            matches=[],
            snippet_preview=snippet,
            highlight_ranges=highlight_ranges,
        ))

    return results


@app.route('/api/search/global', methods=['POST'])
@login_required
@_search_limiter_decorator("30 per minute")
@traced("search.global")
def api_search_global():
    """חיפוש גלובלי בתוכן כל הקבצים של המשתמש."""
    start_time = time.time()
    user_id = session['user_id']
    try:
        setattr(g, "_otel_cache_hit", False)
    except Exception:
        pass
    try:
        # Soft-warning ב-80% מניצול ההגבלה (למיטב היכולת; תלוי במימוש limiter)
        try:
            if limiter is not None and hasattr(limiter, 'current_limit'):
                # Flask-Limiter 3.x אינו מספק API יציב לשאילת ניצול; נסתפק באירוע/מטריקה בזמן תגובה 429.
                pass
            else:
                # אין מידע על ניצול ברמת Flask; נשאיר לשכבת הבוט.
                pass
        except Exception:
            pass
        # בקשות חיפוש מזוהות ע"י request_id לתחקור קל יותר
        try:
            request_id = generate_request_id()
            bind_request_id(request_id)
        except Exception:
            request_id = ""

        payload = request.get_json(silent=True) or {}
        query = (payload.get('query') or '').strip()
        if not query:
            try:
                search_counter.labels(search_type='invalid', status='error').inc()
            except Exception:
                pass
            return jsonify({'error': 'נא להזין טקסט לחיפוש'}), 400
        if len(query) > 500:
            try:
                search_counter.labels(search_type='invalid', status='error').inc()
            except Exception:
                pass
            return jsonify({'error': 'השאילתה ארוכה מדי (מקסימום 500 תווים)'}), 400

        search_type_str = (payload.get('search_type') or 'content').strip().lower()
        enums_ok = bool(search_engine) and hasattr(SearchType, 'CONTENT') and hasattr(SortOrder, 'RELEVANCE')
        if enums_ok:
            try:
                st_map = {
                    'content': SearchType.CONTENT,
                    'regex': SearchType.REGEX,
                    'fuzzy': SearchType.FUZZY,
                    'function': SearchType.FUNCTION,
                    'text': SearchType.TEXT,
                }
                search_type = st_map.get(search_type_str, SearchType.CONTENT)
            except Exception:
                # Fallback בטוח במידה ויש Enum אך קרתה שגיאה במיפוי
                search_type = getattr(SearchType, 'CONTENT', None)
        else:
            # כאשר מנוע החיפוש/Enums לא זמינים — אל ניגע ב-Enums כדי שלא ייזרק AttributeError
            search_type = None

        # Filters
        filter_data = payload.get('filters') or {}
        try:
            filters = SearchFilter(
                languages=list(filter_data.get('languages') or []),
                tags=list(filter_data.get('tags') or []),
                date_from=filter_data.get('date_from'),
                date_to=filter_data.get('date_to'),
                min_size=filter_data.get('min_size'),
                max_size=filter_data.get('max_size'),
                has_functions=filter_data.get('has_functions'),
                has_classes=filter_data.get('has_classes'),
                file_pattern=filter_data.get('file_pattern'),
            )
        except Exception:
            filters = None

        # Regex validation if relevant
        if search_type_str == 'regex':
            # סינון בסיסי למניעת ReDoS על דפוסים מסוכנים
            def _is_regex_safe(p: str) -> bool:
                try:
                    # אורך מרבי
                    if len(p) > 200:
                        return False
                    # מניעת כוכב כפול על תחומים רחבים (.*.*)
                    if re.search(r"\.(\*)[^\n]*\.(\*)", p):
                        return False
                    # מניעת כמתים מקוננים (דפוסים ידועים לקטסטרופה)
                    if re.search(r"\([^)]{0,64}[+*]{1,2}\)\s*[+*]{1,2}", p):
                        return False
                    # כמתים מספריים גדולים
                    for m in re.finditer(r"\{\s*(\d{2,})\s*(?:,\s*(\d+)\s*)?\}", p):
                        lo = int(m.group(1) or 0)
                        hi = int(m.group(2)) if m.group(2) else lo
                        if lo > 100 or hi > 200:
                            return False
                    # קומפילציה בסיסית בלבד
                    re.compile(p)
                    return True
                except Exception:
                    return False
            if not _is_regex_safe(query):
                try:
                    search_counter.labels(search_type='regex', status='invalid_pattern').inc()
                except Exception:
                    pass
                return jsonify({'error': 'ביטוי רגולרי לא מאושר'}), 400

        # Sorting
        sort_str = (payload.get('sort') or 'relevance').strip().lower()
        if enums_ok:
            try:
                so_map = {
                    'relevance': SortOrder.RELEVANCE,
                    'date_desc': SortOrder.DATE_DESC,
                    'date_asc': SortOrder.DATE_ASC,
                    'name_asc': SortOrder.NAME_ASC,
                    'name_desc': SortOrder.NAME_DESC,
                    'size_desc': SortOrder.SIZE_DESC,
                    'size_asc': SortOrder.SIZE_ASC,
                }
                sort_order = so_map.get(sort_str, SortOrder.RELEVANCE)
            except Exception:
                sort_order = getattr(SortOrder, 'RELEVANCE', None)
        else:
            sort_order = None

        # Pagination
        try:
            page = max(1, int(payload.get('page') or 1))
        except Exception:
            page = 1
        try:
            limit = min(100, max(1, int(payload.get('limit') or 20)))
        except Exception:
            limit = 20

        # Redis-backed dynamic cache key
        should_cache = getattr(cache, 'is_enabled', False)
        cache_key = None
        if should_cache:
            try:
                cache_payload = json.dumps({'q': query, 't': search_type_str, 'f': filter_data, 's': sort_str, 'p': page, 'l': limit}, sort_keys=True, ensure_ascii=False).encode('utf-8')
                key_hash = hashlib.sha256(cache_payload).hexdigest()[:24]
                cache_key = f"api:search:{user_id}:{key_hash}"
                cached = cache.get(cache_key)
                if isinstance(cached, dict) and cached:
                    try:
                        search_cache_hits.inc()
                        search_counter.labels(search_type=search_type_str, status='cache_hit').inc()
                    except Exception:
                        pass
                    try:
                        setattr(g, "_otel_cache_hit", True)
                    except Exception:
                        pass
                    return jsonify(dict(cached, cached=True))
            except Exception:
                cache_key = None

        try:
            search_cache_misses.inc()
        except Exception:
            pass

        # Execute search
        total_limit = min(1000, limit * page)
        # אל ניגש ל-Enums כשאינם זמינים — במצב כזה _safe_search יחזיר [] ממילא
        results = _safe_search(
            user_id=user_id,
            query=query,
            search_type=(search_type if enums_ok else None),
            filters=filters,
            sort_order=(sort_order if enums_ok else None),
            limit=total_limit,
        )

        # לוג אינפורמטיבי על החיפוש שבוצע (ללא הדלפת תוכן השאילתה)
        try:
            emit_event(
                "search_request",
                severity="info",
                request_id=request_id,
                user_id=int(user_id),
                query_length=int(len(query)),
                search_type=str(search_type_str),
                sort=str(sort_str),
                page=int(page),
                limit=int(limit),
                total_limit=int(total_limit),
                used_engine=bool(enums_ok),
            )
        except Exception:
            pass

        # Metrics
        try:
            search_results_count.observe(len(results) if isinstance(results, list) else 0)
            active_indexes_gauge.set(_get_search_index_count())
        except Exception:
            pass

        # Slice for page
        start_idx = (page - 1) * limit
        end_idx = start_idx + limit
        page_results = results[start_idx:end_idx] if isinstance(results, list) else []

        # Build response
        def _safe_getattr(obj, name, default=None):
            try:
                return getattr(obj, name, default)
            except Exception:
                return default

        # Resolve DB ids for links (best-effort; don't fail search if DB unavailable)
        try:
            db = get_db()
        except Exception:
            db = None
        # Log politely when DB is unavailable, but continue gracefully
        try:
            if db is None:
                emit_event(
                    "search_db_unavailable",
                    severity="warning",
                    request_id=request_id if 'request_id' in locals() else "",
                    user_id=int(user_id),
                )
        except Exception:
            pass

        resp = {
            'success': True,
            'query': query,
            'total_results': len(results) if isinstance(results, list) else 0,
            'page': page,
            'per_page': limit,
            'search_time': round(time.time() - start_time, 3),
            'cached': False,
            'results': [
                {
                    'file_id': (lambda fn: (lambda doc: (str(doc.get('_id')) if isinstance(doc, dict) and doc.get('_id') else hashlib.sha256(f"{user_id}:{fn}".encode('utf-8')).hexdigest()))(
                        (db.code_snippets.find_one({'user_id': user_id, 'file_name': fn}, sort=[('version', -1)]) if db is not None else None)
                    ))(_safe_getattr(r, 'file_name', '')),
                    'file_name': _safe_getattr(r, 'file_name', ''),
                    'language': _safe_getattr(r, 'programming_language', ''),
                    'tags': _safe_getattr(r, 'tags', []) or [],
                    'score': round(float(_safe_getattr(r, 'relevance_score', 0.0) or 0.0), 2),
                    'snippet': (_safe_getattr(r, 'snippet_preview', '') or '')[:200],
                    'highlights': _safe_getattr(r, 'highlight_ranges', []) or [],
                    'matches': (_safe_getattr(r, 'matches', []) or [])[:5],
                    'updated_at': safe_iso((_safe_getattr(r, 'updated_at', datetime.now(timezone.utc)) or datetime.now(timezone.utc)), field='updated_at'),
                    'size': len(_safe_getattr(r, 'content', '') or ''),
                }
                for r in page_results
            ],
        }

        # Cache set (redis dynamic if available; else skip)
        try:
            if cache_key:
                cache.set_dynamic(
                    cache_key,
                    resp,
                    "search_results",
                    {
                        "user_id": user_id,
                        "user_tier": session.get("user_tier", "regular"),
                        "access_frequency": "high" if len(query) <= 16 else "low",
                        "endpoint": "api_search_global",
                    },
                )
        except Exception:
            pass
        try:
            search_counter.labels(search_type=search_type_str, status='success').inc()
        except Exception:
            pass

        # לוג סיכום
        try:
            emit_event(
                "search_response",
                severity="info",
                request_id=request_id,
                user_id=int(user_id),
                results_count=int(resp.get('total_results', 0)),
                page_results=int(len(resp.get('results') or [])),
                duration_ms=int(round((time.time() - start_time) * 1000)),
                cache_hit=False,
            )
        except Exception:
            pass
        return jsonify(resp)

    except Exception as e:
        # לוג שגיאה מובנה עבור תחקור
        try:
            emit_event(
                "search_error",
                severity="error",
                request_id=request_id if 'request_id' in locals() else "",
                user_id=int(user_id),
                error=str(e),
            )
        except Exception:
            pass
        try:
            search_counter.labels(search_type='unknown', status='error').inc()
        except Exception:
            pass
        try:
            if _SENTRY_AVAILABLE:
                sentry_sdk.capture_exception(e)
        except Exception:
            pass
        # אל נחשוף פרטי חריגה חוצה
        return jsonify({'error': 'אירעה שגיאה בחיפוש'}), 500
    finally:
        try:
            search_duration.observe(time.time() - start_time)
        except Exception:
            pass


@app.route('/api/search/suggestions', methods=['GET'])
@login_required
@traced("search.suggestions")
def api_search_suggestions():
    """הצעות השלמה אוטומטיות לחיפוש על בסיס אינדקס המנוע."""
    try:
        q = (request.args.get('q') or '').strip()
        if len(q) < 2 or not search_engine:
            return jsonify({'suggestions': []})

        # Try dynamic cache (fast path)
        uid = session['user_id']
        key = None
        try:
            if getattr(cache, 'is_enabled', False):
                payload = json.dumps({'q': q}, sort_keys=True, ensure_ascii=False)
                h = hashlib.sha256(payload.encode('utf-8')).hexdigest()[:16]
                key = f"api:search_suggest:{uid}:{h}"
                cached = cache.get(key)
                if isinstance(cached, dict) and 'suggestions' in cached:
                    return jsonify(cached)
        except Exception:
            key = None

        suggestions = search_engine.suggest_completions(uid, q, limit=10)
        resp = {'suggestions': suggestions}
        try:
            if key:
                cache.set_dynamic(key, resp, 'search_results', {'user_id': uid, 'endpoint': 'api_search_suggestions'})
        except Exception:
            pass
        return jsonify(resp)
    except Exception:
        return jsonify({'suggestions': []})


@app.route('/metrics')
@_limiter_exempt()
def metrics_endpoint():
    """Prometheus metrics endpoint (unified across services)."""
    try:
        from metrics import metrics_endpoint_bytes, metrics_content_type
    except Exception:
        def metrics_endpoint_bytes():
            return b"metrics disabled"
        def metrics_content_type():
            return "text/plain; charset=utf-8"
    try:
        # Update local gauges that depend on app state (best-effort)
        try:
            if 'active_indexes_gauge' in globals():
                active_indexes_gauge.set(_get_search_index_count())
        except Exception:
            pass
        payload = metrics_endpoint_bytes()
        return Response(payload, mimetype=metrics_content_type())
    except Exception:
        return Response("metrics unavailable", mimetype='text/plain', status=503)


@app.route('/healthz')
@_limiter_exempt()
def healthz():
    """Simple liveness probe for platforms expecting /healthz."""
    try:
        # Light check: ensure app context and (optional) DB client object exist
        _ = app.name  # noqa: F841
        return jsonify({"status": "ok"}), 200
    except Exception:
        return jsonify({"status": "error"}), 503


@app.route('/api/search/health')
def api_search_health():
    """בדיקת תקינות פשוטה של מנוע החיפוש (ללא גישה לנתוני משתמש)."""
    try:
        _ = _get_search_index_count()
        return jsonify({'status': 'ok', 'indexes': _}), 200
    except Exception:
        return jsonify({'status': 'error'}), 503


def format_file_size(size_bytes: float | int) -> str:
    """מעצב גודל קובץ לתצוגה ידידותית"""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} TB"

def is_binary_file(content: str | bytes, filename: str = "") -> bool:
    """בודק אם קובץ הוא בינארי"""
    # רשימת סיומות בינאריות
    binary_extensions = {
        '.exe', '.dll', '.so', '.dylib', '.bin', '.dat',
        '.pdf', '.doc', '.docx', '.xls', '.xlsx',
        '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.ico',
        '.mp3', '.mp4', '.avi', '.mov', '.wav',
        '.zip', '.rar', '.7z', '.tar', '.gz',
        '.pyc', '.pyo', '.class', '.o', '.a'
    }
    
    # בדיקה לפי סיומת
    if filename:
        ext = os.path.splitext(filename.lower())[1]
        if ext in binary_extensions:
            return True
    
    # בדיקה לפי תוכן
    if content:
        try:
            # נסיון לקרוא כ-UTF-8
            if isinstance(content, bytes):
                content.decode('utf-8')
            # בדיקת תווים בינאריים
            null_count = content.count('\0') if isinstance(content, str) else content.count(b'\0')
            if null_count > 0:
                return True
        except UnicodeDecodeError:
            return True
    
    return False

def get_language_icon(language: str) -> str:
    """מחזיר אייקון עבור שפת תכנות"""
    icons = {
        'python': '🐍',
        'javascript': '📜',
        'typescript': '📘',
        'java': '☕',
        'cpp': '⚙️',
        'c': '🔧',
        'csharp': '🎯',
        'go': '🐹',
        'rust': '🦀',
        'ruby': '💎',
        'php': '🐘',
        'swift': '🦉',
        'kotlin': '🎨',
        'html': '🌐',
        'css': '🎨',
        'sql': '🗄️',
        'bash': '🖥️',
        'shell': '🐚',
        'dockerfile': '🐳',
        'yaml': '📋',
        'json': '📊',
        'xml': '📄',
        'markdown': '📝',
    }
    return icons.get(language.lower(), '📄')

# המרה בטוחה למחרוזת ISO8601; לא מפילה על טיפוס שגוי
def safe_iso(value, field: str = "") -> str:
    if isinstance(value, str):
        return value  # כבר בפורמט טקסטואלי
    try:
        return value.isoformat( )
    except Exception:
        try:
            # אזהרה תחקורית – לא מפילה את הזרימה
            logger.warning(
                "Non-datetime value in isoformat field=%s type=%s",
                field,
                type(value).__name__,
            )
        except Exception:
            pass
        try:
            return str(value)
        except Exception:
            return ""

# עיצוב תאריך בטוח לתצוגה ללא נפילה לברירת מחדל של עכשיו
def format_datetime_display(value) -> str:
    try:
        if isinstance(value, datetime):
            dt = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
            return dt.strftime('%d/%m/%Y %H:%M')
        if isinstance(value, str) and value:
            try:
                dtp = datetime.fromisoformat(value)
                dtp = dtp if dtp.tzinfo is not None else dtp.replace(tzinfo=timezone.utc)
                return dtp.strftime('%d/%m/%Y %H:%M')
            except Exception:
                return ''
        return ''
    except Exception:
        return ''

# מסנן Jinja להצגת שעה:דקות (HH:MM) בלבד
@app.template_filter('hhmm')
def format_time_hhmm(value) -> str:
    try:
        if isinstance(value, datetime):
            dt = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
            return dt.strftime('%H:%M')
        if isinstance(value, str) and value:
            try:
                dtp = datetime.fromisoformat(value)
                dtp = dtp if dtp.tzinfo is not None else dtp.replace(tzinfo=timezone.utc)
                return dtp.strftime('%H:%M')
            except Exception:
                return ''
        return ''
    except Exception:
        return ''

# מסנן Jinja להצגת תאריך כולל (DD/MM/YYYY HH:MM)
@app.template_filter('datetime_display')
def jinja_datetime_display(value) -> str:
    return format_datetime_display(value)

# מסנן Jinja חכם: אם היום – מציג HH:MM, אחרת DD/MM HH:MM
@app.template_filter('day_hhmm')
def format_day_hhmm(value) -> str:
    try:
        if isinstance(value, datetime):
            dt = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
        elif isinstance(value, str) and value:
            try:
                dt = datetime.fromisoformat(value)
                dt = dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)
            except Exception:
                return ''
        else:
            return ''

        now = datetime.now(timezone.utc)
        if dt.date() == now.date():
            return dt.strftime('%H:%M')
        return dt.strftime('%d/%m %H:%M')
    except Exception:
        return ''
# Routes

@app.route('/')
def index():
    """דף הבית"""
    # Try resolve external uptime (non-blocking semantics: short timeout + cache inside helper)
    uptime_summary: Optional[Dict[str, Any]] = None
    try:
        uptime_summary = fetch_external_uptime()
    except Exception:
        uptime_summary = None
    return render_template(
        'index.html',
        bot_username=BOT_USERNAME_CLEAN,
        logged_in=('user_id' in session),
        user=session.get('user_data', {}),
        uptime=uptime_summary,
    )

@app.route('/login')
def login():
    """דף התחברות"""
    return render_template('login.html', bot_username=BOT_USERNAME_CLEAN)

@app.route('/auth/telegram', methods=['GET', 'POST'])
def telegram_auth():
    """טיפול באימות Telegram"""
    auth_data = dict(request.args) if request.method == 'GET' else request.get_json()
    
    if not verify_telegram_auth(auth_data):
        return jsonify({'error': 'Invalid authentication'}), 401
    
    # שמירת נתוני המשתמש בסשן
    user_id = int(auth_data['id'])
    user_doc: Dict[str, Any] = {}
    try:
        db = get_db()
    except Exception:
        db = None
    now_utc = datetime.now(timezone.utc)
    if db is not None:
        try:
            user_doc = db.users.find_one({'user_id': user_id}) or {}
        except Exception:
            user_doc = {}
        try:
            db.users.update_one(
                {'user_id': user_id},
                {
                    '$set': {
                        'user_id': user_id,
                        'first_name': auth_data.get('first_name', ''),
                        'last_name': auth_data.get('last_name', ''),
                        'username': auth_data.get('username', ''),
                        'photo_url': auth_data.get('photo_url', ''),
                        'updated_at': now_utc,
                    },
                    '$setOnInsert': {
                        'created_at': now_utc,
                        'has_seen_welcome_modal': False,
                    },
                },
                upsert=True,
            )
        except Exception:
            pass
        try:
            from database.collections_manager import CollectionsManager
            CollectionsManager(db).ensure_default_collections(user_id)
        except Exception:
            pass
    session['user_id'] = user_id
    session['user_data'] = {
        'id': user_id,
        'first_name': auth_data.get('first_name', ''),
        'last_name': auth_data.get('last_name', ''),
        'username': auth_data.get('username', ''),
        'photo_url': auth_data.get('photo_url', ''),
        'has_seen_welcome_modal': bool((user_doc or {}).get('has_seen_welcome_modal', False))
    }
    
    # הפוך את הסשן לקבוע לכל המשתמשים (30 יום)
    session.permanent = True
    
    # אפשר להוסיף כאן הגדרות נוספות לאדמינים בעתיד
    
    return redirect(url_for('dashboard'))

@app.route('/auth/token')
def token_auth():
    """טיפול באימות עם טוקן מהבוט"""
    token = request.args.get('token')
    user_id = request.args.get('user_id')
    
    if not token or not user_id:
        return render_template('404.html'), 404
    
    try:
        db = get_db()
        # חיפוש הטוקן במסד נתונים
        token_doc = db.webapp_tokens.find_one({
            'token': token,
            'user_id': int(user_id)
        })
        
        if not token_doc:
            return render_template('login.html', 
                                 bot_username=BOT_USERNAME_CLEAN,
                                 error="קישור ההתחברות לא תקף או פג תוקפו")
        
        # בדיקת תוקף
        if token_doc['expires_at'] < datetime.now(timezone.utc):
            # מחיקת טוקן שפג תוקפו
            db.webapp_tokens.delete_one({'_id': token_doc['_id']})
            return render_template('login.html', 
                                 bot_username=BOT_USERNAME_CLEAN,
                                 error="קישור ההתחברות פג תוקף. אנא בקש קישור חדש מהבוט.")
        
        # מחיקת הטוקן לאחר שימוש (חד פעמי)
        db.webapp_tokens.delete_one({'_id': token_doc['_id']})
        
        # שליפת פרטי המשתמש
        now_utc = datetime.now(timezone.utc)
        user = db.users.find_one({'user_id': int(user_id)}) or {}
        try:
            db.users.update_one(
                {'user_id': int(user_id)},
                {
                    '$set': {
                        'user_id': int(user_id),
                        'first_name': user.get('first_name') or token_doc.get('first_name', ''),
                        'last_name': user.get('last_name') or token_doc.get('last_name', ''),
                        'username': token_doc.get('username', user.get('username', '')),
                        'photo_url': user.get('photo_url', ''),
                        'updated_at': now_utc,
                    },
                    '$setOnInsert': {
                        'created_at': now_utc,
                        'has_seen_welcome_modal': False,
                    },
                },
                upsert=True,
            )
        except Exception:
            pass
        try:
            from database.collections_manager import CollectionsManager
            CollectionsManager(db).ensure_default_collections(int(user_id))
        except Exception:
            pass
        
        # שמירת נתוני המשתמש בסשן
        user_id_int = int(user_id)
        session['user_id'] = user_id_int
        session['user_data'] = {
            'id': user_id_int,
            'first_name': user.get('first_name', token_doc.get('first_name', '')),
            'last_name': user.get('last_name', token_doc.get('last_name', '')),
            'username': token_doc.get('username', ''),
            'photo_url': user.get('photo_url', ''),
            'has_seen_welcome_modal': bool(user.get('has_seen_welcome_modal', False))
        }
        
        # הפוך את הסשן לקבוע לכל המשתמשים (30 יום)
        session.permanent = True
        
        # אפשר להוסיף כאן הגדרות נוספות לאדמינים בעתיד
        
        return redirect(url_for('dashboard'))
        
    except Exception as e:
        logger.exception("Error in token auth")
        return render_template('login.html', 
                             bot_username=BOT_USERNAME_CLEAN,
                             error="שגיאה בהתחברות. אנא נסה שנית.")

@app.route('/logout')
def logout():
    """התנתקות"""
    try:
        token = request.cookies.get(REMEMBER_COOKIE_NAME)
        if token:
            try:
                db = get_db()
                db.remember_tokens.delete_one({'token': token})
            except Exception:
                pass
    except Exception:
        pass
    resp = redirect(url_for('index'))
    try:
        resp.delete_cookie(REMEMBER_COOKIE_NAME)
    except Exception:
        pass
    session.clear()
    return resp

@app.route('/dashboard')
@login_required
def dashboard():
    """דשבורד עם סטטיסטיקות"""
    try:
        db = get_db()
        user_id = session['user_id']
        
        # שליפת סטטיסטיקות - רק קבצים פעילים
        active_query = {
            'user_id': user_id,
            '$or': [
                {'is_active': True},
                {'is_active': {'$exists': False}}
            ]
        }
        total_files = db.code_snippets.count_documents(active_query)
        
        # חישוב נפח כולל
        pipeline = [
            {'$match': {
                'user_id': user_id,
                '$or': [
                    {'is_active': True},
                    {'is_active': {'$exists': False}}
                ]
            }},
            {'$project': {
                'code_size': {
                    '$cond': {
                        'if': {'$and': [
                            {'$ne': ['$code', None]},
                            {'$eq': [{'$type': '$code'}, 'string']}
                        ]},
                        'then': {'$strLenBytes': '$code'},
                        'else': 0
                    }
                }
            }},
            {'$group': {
                '_id': None,
                'total_size': {'$sum': '$code_size'}
            }}
        ]
        size_result = list(db.code_snippets.aggregate(pipeline))
        total_size = size_result[0]['total_size'] if size_result else 0
        
        # שפות פופולריות
        languages_pipeline = [
            {'$match': {
                'user_id': user_id,
                '$or': [
                    {'is_active': True},
                    {'is_active': {'$exists': False}}
                ]
            }},
            {'$group': {
                '_id': '$programming_language',
                'count': {'$sum': 1}
            }},
            {'$sort': {'count': -1}},
            {'$limit': 5}
        ]
        top_languages = list(db.code_snippets.aggregate(languages_pipeline))
        
        # פעילות אחרונה
        recent_files = list(db.code_snippets.find(
            {
                'user_id': user_id,
                '$or': [
                    {'is_active': True},
                    {'is_active': {'$exists': False}}
                ]
            },
            {'file_name': 1, 'programming_language': 1, 'created_at': 1}
        ).sort('created_at', DESCENDING).limit(5))
        
        # עיבוד הנתונים לתצוגה
        for file in recent_files:
            file['_id'] = str(file['_id'])
            file['icon'] = get_language_icon(file.get('programming_language', ''))
            if 'created_at' in file:
                file['created_at_formatted'] = file['created_at'].strftime('%d/%m/%Y %H:%M')
        
        stats = {
            'total_files': total_files,
            'total_size': format_file_size(total_size),
            'top_languages': [
                {
                    'name': lang['_id'] or 'לא מוגדר',
                    'count': lang['count'],
                    'icon': get_language_icon(lang['_id'] or '')
                }
                for lang in top_languages
            ],
            'recent_files': recent_files
        }
        
        return render_template('dashboard.html', 
                             user=session['user_data'],
                             stats=stats,
                             bot_username=BOT_USERNAME_CLEAN)
                             
    except Exception as e:
        logger.exception("Error in dashboard")
        import traceback
        traceback.print_exc()
        # נסה להציג דשבורד ריק במקרה של שגיאה
        return render_template('dashboard.html', 
                             user=session.get('user_data', {}),
                             stats={
                                 'total_files': 0,
                                 'total_size': '0 B',
                                 'top_languages': [],
                                 'recent_files': []
                             },
                             error="אירעה שגיאה בטעינת הנתונים. אנא נסה שוב.",
                             bot_username=BOT_USERNAME_CLEAN)

@app.route('/files')
@login_required
@traced("files.list")
def files():
    """רשימת כל הקבצים של המשתמש"""
    db = get_db()
    user_id = session['user_id']
    # --- Cache: בדיקת HTML שמור לפי משתמש ופרמטרים ---
    should_cache = getattr(cache, 'is_enabled', False)
    
    # פרמטרים לחיפוש ומיון
    search_query = request.args.get('q', '')
    language_filter = request.args.get('lang', '')
    category_filter = request.args.get('category', '')
    sort_by = request.args.get('sort', 'created_at')
    repo_name = request.args.get('repo', '').strip()
    page = int(request.args.get('page', 1))
    cursor_token = (request.args.get('cursor') or '').strip()
    per_page = 20

    # החלת ברירות מחדל למיון לפני בניית מפתח הקאש
    try:
        # קטגוריית "נפתחו לאחרונה": לפי זמן פתיחה אחרון אם לא סופק מיון במפורש
        if (category_filter or '').strip().lower() == 'recent' and not (request.args.get('sort') or '').strip():
            sort_by = '-last_opened_at'
    except Exception:
        pass
    try:
        # קטגוריית "מועדפים": לפי זמן הוספה למועדפים (חדש -> ישן) אם לא סופק מיון במפורש
        if (category_filter or '').strip().lower() == 'favorites' and not (request.args.get('sort') or '').strip():
            sort_by = '-favorited_at'
    except Exception:
        pass
    # הכנת מפתח Cache ייחודי לפרמטרים
    try:
        _params = {
            'q': search_query,
            'lang': language_filter,
            'category': category_filter,
            'sort': sort_by,
            'repo': repo_name,
            'page': page,
            'cursor': (cursor_token[:32] if cursor_token else ''),
        }
        _raw = json.dumps(_params, sort_keys=True, ensure_ascii=False)
        _hash = hashlib.sha256(_raw.encode('utf-8')).hexdigest()[:24]
        files_cache_key = f"web:files:user:{user_id}:{_hash}"
    except Exception:
        files_cache_key = f"web:files:user:{user_id}:fallback"

    if should_cache:
        try:
            cached_html = cache.get(files_cache_key)
            if isinstance(cached_html, str) and cached_html:
                return cached_html
        except Exception:
            pass
    # הערה: ברירות המחדל למיון עבור recent/favorites כבר הוחלו לפני בניית מפתח הקאש
    
    # בניית שאילתה - כולל סינון קבצים פעילים בלבד
    query = {
        'user_id': user_id,
        '$and': [
            {
                '$or': [
                    {'is_active': True},
                    {'is_active': {'$exists': False}}  # תמיכה בקבצים ישנים ללא השדה
                ]
            }
        ]
    }
    
    if search_query:
        query['$and'].append(
            {'$or': [
                {'file_name': {'$regex': search_query, '$options': 'i'}},
                {'description': {'$regex': search_query, '$options': 'i'}},
                {'tags': {'$in': [search_query.lower()]}}
            ]}
        )
    
    if language_filter:
        query['programming_language'] = language_filter
    
    # סינון לפי קטגוריה
    if category_filter:
        if category_filter == 'repo':
            # תצוגת "לפי ריפו":
            # אם נבחר ריפו ספציפי -> מסנן לקבצים של אותו ריפו; אחרת -> נציג רשימת ריפואים ונחזור מיד
            if repo_name:
                query['$and'].append({'tags': f'repo:{repo_name}'})
            else:
                # הפקה של רשימת ריפואים מתוך תגיות שמתחילות ב- repo:
                # חשוב: לא מושפעת מחיפוש/שפה כדי להציג את כל הריפואים של המשתמש
                base_active_query = {
                    'user_id': user_id,
                    '$or': [
                        {'is_active': True},
                        {'is_active': {'$exists': False}}
                    ]
                }
                # מיישר ללוגיקה של הבוט: קבוצה לפי file_name (הגרסה האחרונה בלבד), ואז חילוץ תגית repo: אחת
                repo_pipeline = [
                    {'$match': base_active_query},
                    {'$sort': {'file_name': 1, 'version': -1}},
                    {'$group': {'_id': '$file_name', 'latest': {'$first': '$$ROOT'}}},
                    {'$replaceRoot': {'newRoot': '$latest'}},
                    {'$match': {'tags': {'$elemMatch': {'$regex': r'^repo:', '$options': 'i'}}}},
                    {'$project': {
                        'repo_tag': {
                            '$arrayElemAt': [
                                {
                                    '$filter': {
                                        'input': '$tags',
                                        'as': 't',
                                        'cond': {'$regexMatch': {'input': '$$t', 'regex': '^repo:', 'options': 'i'}}
                                    }
                                },
                                -1
                            ]
                        }
                    }},
                    {'$group': {'_id': '$repo_tag', 'count': {'$sum': 1}}},
                    {'$sort': {'_id': 1}},
                ]
                repos_raw = list(db.code_snippets.aggregate(repo_pipeline))
                repos_list = []
                for r in repos_raw:
                    try:
                        repo_full = str(r.get('_id') or '')
                        # strip leading 'repo:' if present
                        name = repo_full.split(':', 1)[1] if ':' in repo_full else repo_full
                        repos_list.append({'name': name, 'count': int(r.get('count') or 0)})
                    except Exception:
                        continue
                # רשימת שפות לפילטר - רק מקבצים פעילים
                languages = db.code_snippets.distinct(
                    'programming_language',
                    {
                        'user_id': user_id,
                        '$or': [
                            {'is_active': True},
                            {'is_active': {'$exists': False}}
                        ]
                    }
                )
                languages = sorted([lang for lang in languages if lang]) if languages else []
                html = render_template('files.html',
                                     user=session['user_data'],
                                     files=[],
                                     repos=repos_list,
                                     total_count=len(repos_list),
                                     languages=languages,
                                     search_query=search_query,
                                     language_filter=language_filter,
                                     category_filter=category_filter,
                                     selected_repo='',
                                     sort_by=sort_by,
                                     page=1,
                                     total_pages=1,
                                     has_prev=False,
                                     has_next=False,
                                     bot_username=BOT_USERNAME_CLEAN)
                if should_cache:
                    try:
                        cache.set_dynamic(
                            files_cache_key,
                            html,
                            "file_list",
                            {
                                "user_id": user_id,
                                "user_tier": session.get("user_tier", "regular"),
                                "access_frequency": "high",
                                "endpoint": "files",
                            },
                        )
                    except Exception:
                        try:
                            cache.set(files_cache_key, html, FILES_PAGE_CACHE_TTL)
                        except Exception:
                            pass
                return html
        elif category_filter == 'zip':
            # הוסר מה‑UI; נשיב מיד לרשימת קבצים רגילה כדי למנוע שימוש ב‑Mongo לאחסון גיבויים
            return redirect(url_for('files'))
        elif category_filter == 'large':
            # קבצים גדולים (מעל 100KB)
            # נצטרך להוסיף שדה size אם אין
            pipeline = [
                {'$match': query},
                {'$addFields': {
                    'code_size': {
                        '$cond': {
                            'if': {'$and': [
                                {'$ne': ['$code', None]},
                                {'$eq': [{'$type': '$code'}, 'string']}
                            ]},
                            'then': {'$strLenBytes': '$code'},
                            'else': 0
                        }
                    }
                }},
                {'$match': {'code_size': {'$gte': 102400}}}  # 100KB
            ]
            # נשתמש ב-aggregation במקום find רגיל
            files_cursor = db.code_snippets.aggregate(pipeline + [
                {'$sort': {sort_by.lstrip('-'): -1 if sort_by.startswith('-') else 1}},
                {'$skip': (page - 1) * per_page},
                {'$limit': per_page}
            ])
            count_result = list(db.code_snippets.aggregate(pipeline + [{'$count': 'total'}]))
            total_count = count_result[0]['total'] if count_result else 0
        elif category_filter == 'favorites':
            # קטגוריית "מועדפים" – השתמש בשדה is_favorite
            query['$and'].append({'is_favorite': True})
        elif category_filter == 'other':
            # שאר הקבצים (לא מסומנים כריפו/גיטהאב, לא ZIP)
            query['$and'].append({
                '$nor': [
                    {'tags': 'source:github'},
                    {'tags': {'$elemMatch': {'$regex': r'^repo:', '$options': 'i'}}}
                ]
            })
            query['$and'].append({'file_name': {'$not': {'$regex': r'\.zip$', '$options': 'i'}}})
            query['$and'].append({'is_archive': {'$ne': True}})
        elif category_filter == 'recent':
            # תצוגת "נפתחו לאחרונה" – נשתמש באוסף recent_opens
            # נחזיר מוקדם תבנית שמחכה ל-files_list שנבנה מטבלת recent_opens
            pass
    
    # ספירת סך הכל (אם לא חושב כבר)
    if not category_filter:
        # "כל הקבצים": ספירה distinct לפי שם קובץ לאחר סינון (תוכן >0)
        count_pipeline = [
            {'$match': query},
            {'$addFields': {
                'code_size': {
                    '$cond': {
                        'if': {'$and': [
                            {'$ne': ['$code', None]},
                            {'$eq': [{'$type': '$code'}, 'string']}
                        ]},
                        'then': {'$strLenBytes': '$code'},
                        'else': 0
                    }
                }
            }},
            {'$match': {'code_size': {'$gt': 0}}},
            {'$group': {'_id': '$file_name'}},
            {'$count': 'total'}
        ]
        count_result = list(db.code_snippets.aggregate(count_pipeline))
        total_count = count_result[0]['total'] if count_result else 0
    elif category_filter == 'other':
        # ספירת קבצים ייחודיים לפי שם קובץ לאחר סינון (תוכן >0), עם עקביות ל-query הכללי
        count_pipeline = [
            {'$match': query},
            {'$addFields': {
                'code_size': {
                    '$cond': {
                        'if': {'$and': [
                            {'$ne': ['$code', None]},
                            {'$eq': [{'$type': '$code'}, 'string']}
                        ]},
                        'then': {'$strLenBytes': '$code'},
                        'else': 0
                    }
                }
            }},
            {'$match': {'code_size': {'$gt': 0}}},
            {'$group': {'_id': '$file_name'}},
            {'$count': 'total'}
        ]
        count_result = list(db.code_snippets.aggregate(count_pipeline))
        total_count = count_result[0]['total'] if count_result else 0
    elif category_filter != 'large':
        total_count = db.code_snippets.count_documents(query)
    
    # שליפת הקבצים
    sort_order = DESCENDING if sort_by.startswith('-') else 1
    sort_field = sort_by.lstrip('-')
    
    # קטגוריה מיוחדת: recent
    if category_filter == 'recent':
        # שליפת שמות קבצים אחרונים לפי user_id והזמן האחרון שנפתחו
        try:
            recent_docs = list(db.recent_opens.find({'user_id': user_id}, {'file_name': 1, 'last_opened_at': 1, '_id': 0}))
        except Exception:
            recent_docs = []

        if not recent_docs:
            # אין קבצים שנפתחו לאחרונה
            languages = db.code_snippets.distinct(
                'programming_language',
                {
                    'user_id': user_id,
                    '$or': [
                        {'is_active': True},
                        {'is_active': {'$exists': False}}
                    ]
                }
            )
            languages = sorted([lang for lang in languages if lang]) if languages else []
            html = render_template('files.html',
                                 user=session['user_data'],
                                 files=[],
                                 total_count=0,
                                 languages=languages,
                                 search_query=search_query,
                                 language_filter=language_filter,
                                 category_filter=category_filter,
                                 sort_by=sort_by,
                                 page=page,
                                 total_pages=1,
                                 has_prev=False,
                                 has_next=False,
                                 bot_username=BOT_USERNAME_CLEAN)
            if should_cache:
                try:
                    cache.set_dynamic(
                        files_cache_key,
                        html,
                        "file_list",
                        {
                            "user_id": user_id,
                            "user_tier": session.get("user_tier", "regular"),
                            "access_frequency": "high",
                            "endpoint": "files",
                        },
                    )
                except Exception:
                    try:
                        cache.set(files_cache_key, html, FILES_PAGE_CACHE_TTL)
                    except Exception:
                        pass
            return html

        # מיפוי שם->זמן פתיחה אחרון ומערך שמות
        recent_map = {}
        file_names = []
        for r in recent_docs:
            fname = (r.get('file_name') or '').strip()
            if not fname:
                continue
            file_names.append(fname)
            recent_map[fname] = r.get('last_opened_at')

        # בניית שאילתה עם כל המסננים שכבר חושבו + סינון לשמות שנפתחו לאחרונה
        recent_query = {
            'user_id': user_id,
            '$and': [{
                '$or': [
                    {'is_active': True},
                    {'is_active': {'$exists': False}}
                ]
            }]
        }
        # לשמור עקביות עם החיפוש/מסננים הכלליים
        if search_query:
            recent_query['$and'].append({'$or': [
                {'file_name': {'$regex': search_query, '$options': 'i'}},
                {'description': {'$regex': search_query, '$options': 'i'}},
                {'tags': {'$in': [search_query.lower()]}}
            ]})
        if language_filter:
            recent_query['programming_language'] = language_filter
        # צמצום לשמות שנפתחו לאחרונה
        recent_query['file_name'] = {'$in': file_names or ['__none__']}

        # אגרגציה: גרסה אחרונה לכל שם קובץ + פלטר לתוכן לא ריק
        sort_field_local = sort_by.lstrip('-') if sort_by else 'last_opened_at'
        sort_dir = -1 if (sort_by or '').startswith('-') else 1

        pipeline = [
            {'$match': recent_query},
            {'$addFields': {
                'code_size': {
                    '$cond': {
                        'if': {'$and': [
                            {'$ne': ['$code', None]},
                            {'$eq': [{'$type': '$code'}, 'string']}
                        ]},
                        'then': {'$strLenBytes': '$code'},
                        'else': 0
                    }
                }
            }},
            {'$match': {'code_size': {'$gt': 0}}},
            {'$sort': {'file_name': 1, 'version': -1}},
            {'$group': {'_id': '$file_name', 'latest': {'$first': '$$ROOT'}}},
            {'$replaceRoot': {'newRoot': '$latest'}},
        ]

        # מיון: אם מיון לפי last_opened_at – נטפל בפייתון; אחרת נמיין ב-DB
        if sort_field_local in {'file_name', 'created_at', 'updated_at'}:
            pipeline.append({'$sort': {sort_field_local: sort_dir}})

        try:
            latest_items = list(db.code_snippets.aggregate(pipeline))
        except Exception:
            latest_items = []

        # מיון לפי זמן פתיחה אחרון (במידה ונדרש)
        if sort_field_local not in {'file_name', 'created_at', 'updated_at'}:
            # treat as last_opened_at
            latest_items.sort(key=lambda d: (recent_map.get(d.get('file_name') or ''), (d.get('file_name') or '')), reverse=(sort_dir == -1))

        # פג'ינציה
        total_count = len(latest_items)
        total_pages = (total_count + per_page - 1) // per_page if total_count > 0 else 1
        page = max(1, min(page, total_pages))
        start = (page - 1) * per_page
        end = start + per_page
        page_items = latest_items[start:end]

        # המרה לפורמט תבנית
        files_list = []
        for latest in page_items:
            fname = latest.get('file_name') or ''
            code_str = latest.get('code') or ''
            lang_raw = (latest.get('programming_language') or '').lower() or 'text'
            lang_display = 'markdown' if (lang_raw in {'', 'text'} and fname.lower().endswith('.md')) else lang_raw
            files_list.append({
                'id': str(latest.get('_id')),
                'file_name': fname,
                'language': lang_display,
                'icon': get_language_icon(lang_display),
                'description': latest.get('description', ''),
                'tags': latest.get('tags', []),
                'size': format_file_size(len(code_str.encode('utf-8'))),
                'lines': len(code_str.splitlines()),
                'created_at': format_datetime_display(latest.get('created_at')),
                'updated_at': format_datetime_display(latest.get('updated_at')),
                'last_opened_at': format_datetime_display(recent_map.get(fname)),
            })

        # רשימת שפות לפילטר - רק מקבצים פעילים
        languages = db.code_snippets.distinct(
            'programming_language',
            {
                'user_id': user_id,
                '$or': [
                    {'is_active': True},
                    {'is_active': {'$exists': False}}
                ]
            }
        )
        languages = sorted([lang for lang in languages if lang]) if languages else []

        return render_template('files.html',
                             user=session['user_data'],
                             files=files_list,
                             total_count=total_count,
                             languages=languages,
                             search_query=search_query,
                             language_filter=language_filter,
                             category_filter=category_filter,
                             sort_by=sort_by,
                             page=page,
                             total_pages=total_pages,
                             has_prev=page > 1,
                             has_next=page < total_pages,
                             bot_username=BOT_USERNAME_CLEAN)

    # שימוש בסיסי: במצב ברירת מחדל אין פג'ינציית cursor
    use_cursor = False

    # אם לא עשינו aggregation כבר (בקטגוריות large/other) — עבור all נשתמש גם באגרגציה
    if not category_filter:
        sort_dir = -1 if sort_by.startswith('-') else 1
        sort_field_local = sort_by.lstrip('-')
        # בסיס הפייפליין: גרסה אחרונה לכל file_name ותוכן לא ריק
        base_pipeline = [
            {'$match': query},
            {'$addFields': {
                'code_size': {
                    '$cond': {
                        'if': {'$and': [
                            {'$ne': ['$code', None]},
                            {'$eq': [{'$type': '$code'}, 'string']}
                        ]},
                        'then': {'$strLenBytes': '$code'},
                        'else': 0
                    }
                }
            }},
            {'$match': {'code_size': {'$gt': 0}}},
            {'$sort': {'file_name': 1, 'version': -1}},
            {'$group': {'_id': '$file_name', 'latest': {'$first': '$$ROOT'}}},
            {'$replaceRoot': {'newRoot': '$latest'}},
        ]
        next_cursor_token = None
        use_cursor = (sort_field_local == 'created_at')
        if use_cursor:
            last_dt, last_oid = _decode_cursor(cursor_token)
            pipeline = list(base_pipeline)
            if last_dt is not None and last_oid is not None:
                if sort_dir == -1:
                    # דפדוף קדימה (חדש->ישן): הביא ישנים יותר מ-anchor
                    pipeline.append({'$match': {
                        '$or': [
                            {'created_at': {'$lt': last_dt}},
                            {'$and': [
                                {'created_at': {'$eq': last_dt}},
                                {'_id': {'$lt': last_oid}},
                            ]}
                        ]
                    }})
                else:
                    # דפדוף קדימה (ישן->חדש)
                    pipeline.append({'$match': {
                        '$or': [
                            {'created_at': {'$gt': last_dt}},
                            {'$and': [
                                {'created_at': {'$eq': last_dt}},
                                {'_id': {'$gt': last_oid}},
                            ]}
                        ]
                    }})
            # מיון יציב + חיתוך ל-page+1 כדי לזהות אם יש עוד
            pipeline.append({'$sort': {'created_at': sort_dir, '_id': sort_dir}})
            pipeline.append({'$limit': per_page + 1})
            docs = list(db.code_snippets.aggregate(pipeline))
            if len(docs) > per_page:
                anchor = docs[per_page - 1]
                try:
                    next_cursor_token = _encode_cursor(anchor.get('created_at') or datetime.now(timezone.utc), anchor.get('_id'))
                except Exception:
                    next_cursor_token = None
                docs = docs[:per_page]
            files_cursor = docs
        else:
            pipeline = list(base_pipeline)
            pipeline.append({'$sort': {sort_field_local: sort_dir}})
            pipeline.append({'$skip': (page - 1) * per_page})
            pipeline.append({'$limit': per_page})
            files_cursor = db.code_snippets.aggregate(pipeline)
    elif category_filter not in ('large', 'other'):
        files_cursor = db.code_snippets.find(query).sort(sort_field, sort_order).skip((page - 1) * per_page).limit(per_page)
    elif category_filter == 'other':
        # "שאר קבצים": בעלי תוכן (>0 בתים), מציגים גרסה אחרונה לכל file_name; עקבי עם ה-query הכללי
        sort_dir = -1 if sort_by.startswith('-') else 1
        sort_field_local = sort_by.lstrip('-')
        base_pipeline = [
            {'$match': query},
            {'$addFields': {
                'code_size': {
                    '$cond': {
                        'if': {'$and': [
                            {'$ne': ['$code', None]},
                            {'$eq': [{'$type': '$code'}, 'string']}
                        ]},
                        'then': {'$strLenBytes': '$code'},
                        'else': 0
                    }
                }
            }},
            {'$match': {'code_size': {'$gt': 0}}},
        ]
        pipeline = base_pipeline + [
            {'$sort': {'file_name': 1, 'version': -1}},
            {'$group': {'_id': '$file_name', 'latest': {'$first': '$$ROOT'}}},
            {'$replaceRoot': {'newRoot': '$latest'}},
            {'$sort': {sort_field_local: sort_dir}},
            {'$skip': (page - 1) * per_page},
            {'$limit': per_page},
        ]
        files_cursor = db.code_snippets.aggregate(pipeline)
    
    files_list = []
    for file in files_cursor:
        code_str = file.get('code') or ''
        fname = file.get('file_name') or ''
        lang_raw = (file.get('programming_language') or '').lower() or 'text'
        # Fallback: אם שמור כ-text אבל הסיומת היא .md – נתייג כ-markdown לתצוגה
        lang_display = 'markdown' if (lang_raw in {'', 'text'} and fname.lower().endswith('.md')) else lang_raw
        files_list.append({
            'id': str(file['_id']),
            'file_name': fname,
            'language': lang_display,
            'icon': get_language_icon(lang_display),
            'description': file.get('description', ''),
            'tags': file.get('tags', []),
            'size': format_file_size(len(code_str.encode('utf-8'))),
            'lines': len(code_str.splitlines()),
            'created_at': format_datetime_display(file.get('created_at')),
            'updated_at': format_datetime_display(file.get('updated_at'))
        })
    
    # רשימת שפות לפילטר - רק מקבצים פעילים
    languages = db.code_snippets.distinct(
        'programming_language',
        {
            'user_id': user_id,
            '$or': [
                {'is_active': True},
                {'is_active': {'$exists': False}}
            ]
        }
    )
    # סינון None וערכים ריקים ומיון
    languages = sorted([lang for lang in languages if lang]) if languages else []
    
    # חישוב עמודים
    total_pages = (total_count + per_page - 1) // per_page
    
    # שמירה על הקשר ריפו שנבחר (אם קיים) כדי לא לשבור עימוד/מסננים
    selected_repo_value = repo_name if (category_filter == 'repo' and repo_name) else ''

    html = render_template('files.html',
                         user=session['user_data'],
                         files=files_list,
                         total_count=total_count,
                         languages=languages,
                         search_query=search_query,
                         language_filter=language_filter,
                         category_filter=category_filter,
                         sort_by=sort_by,
                         page=page,
                         total_pages=total_pages,
                         has_prev=page > 1,
                         has_next=page < total_pages,
                         cursor_mode=use_cursor,
                         next_cursor=(next_cursor_token if 'next_cursor_token' in locals() else None),
                         selected_repo=selected_repo_value,
                         bot_username=BOT_USERNAME_CLEAN)
    if should_cache:
        try:
            cache.set(files_cache_key, html, FILES_PAGE_CACHE_TTL)
        except Exception:
            pass
    return html

@app.route('/file/<file_id>')
@login_required
def view_file(file_id):
    """צפייה בקובץ בודד"""
    db = get_db()
    user_id = session['user_id']
    
    try:
        file = db.code_snippets.find_one({
            '_id': ObjectId(file_id),
            'user_id': user_id
        })
    except (InvalidId, TypeError):
        abort(404)
    except PyMongoError as e:
        logger.exception("DB error fetching file", extra={"file_id": file_id, "user_id": user_id, "error": str(e)})
        abort(500)
    
    if not file:
        abort(404)
    # עדכון רשימת "נפתחו לאחרונה" (MRU) עבור המשתמש הנוכחי — לפני בדיקות Cache
    try:
        ensure_recent_opens_indexes()
        coll = db.recent_opens
        now = datetime.now(timezone.utc)
        coll.update_one(
            {'user_id': user_id, 'file_name': file.get('file_name')},
            {'$set': {
                'user_id': user_id,
                'file_name': file.get('file_name'),
                'last_opened_at': now,
                'last_opened_file_id': file.get('_id'),
                'language': (file.get('programming_language') or 'text'),
                'updated_at': now,
            }, '$setOnInsert': {'created_at': now}},
            upsert=True
        )
    except Exception:
        # אין לכשיל את הדף אם אין DB או אם יש כשל אינדקס/עדכון
        pass
    # HTTP cache validators (ETag / Last-Modified)
    etag = _compute_file_etag(file)
    last_modified_dt = _safe_dt_from_doc(file.get('updated_at') or file.get('created_at'))
    last_modified_str = http_date(last_modified_dt)
    inm = request.headers.get('If-None-Match')
    if inm and inm == etag:
        resp = Response(status=304)
        resp.headers['ETag'] = etag
        resp.headers['Last-Modified'] = last_modified_str
        return resp
    ims = request.headers.get('If-Modified-Since')
    if ims:
        try:
            ims_dt = parse_date(ims)
        except Exception:
            ims_dt = None
        if ims_dt is not None and last_modified_dt.replace(microsecond=0) <= ims_dt:
            resp = Response(status=304)
            resp.headers['ETag'] = etag
            resp.headers['Last-Modified'] = last_modified_str
            return resp


    # הדגשת syntax
    code = file.get('code', '')
    language = (file.get('programming_language') or 'text').lower()
    # תקן תיוג: אם נשמר כ-text אך הסיומת .md – תייג כ-markdown לתצוגה וכפתור 🌐
    try:
        if (not language or language == 'text') and str(file.get('file_name') or '').lower().endswith('.md'):
            language = 'markdown'
    except Exception:
        pass
    
    # הגבלת גודל תצוגה - 1MB
    MAX_DISPLAY_SIZE = 1024 * 1024  # 1MB
    if len(code.encode('utf-8')) > MAX_DISPLAY_SIZE:
        html = render_template('view_file.html',
                             user=session['user_data'],
                             file={
                                 'id': str(file['_id']),
                                 'file_name': file['file_name'],
                                 'language': language,
                                 'icon': get_language_icon(language),
                                 'description': file.get('description', ''),
                                 'tags': file.get('tags', []),
                                 'size': format_file_size(len(code.encode('utf-8'))),
                                 'lines': len(code.splitlines()),
                                 'created_at': format_datetime_display(file.get('created_at')),
                                 'updated_at': format_datetime_display(file.get('updated_at')),
                                 'version': file.get('version', 1)
                             },
                             highlighted_code='<div class="alert alert-info" style="text-align: center; padding: 3rem;"><i class="fas fa-file-alt" style="font-size: 3rem; margin-bottom: 1rem;"></i><br>הקובץ גדול מדי לתצוגה (' + format_file_size(len(code.encode('utf-8'))) + ')<br><br>ניתן להוריד את הקובץ לצפייה מקומית</div>',
                             syntax_css='')
        resp = Response(html, mimetype='text/html; charset=utf-8')
        resp.headers['ETag'] = etag
        resp.headers['Last-Modified'] = last_modified_str
        return resp
    
    # בדיקה אם הקובץ בינארי
    if is_binary_file(code, file.get('file_name', '')):
        html = render_template('view_file.html',
                             user=session['user_data'],
                             file={
                                 'id': str(file['_id']),
                                 'file_name': file['file_name'],
                                 'language': 'binary',
                                 'icon': '🔒',
                                 'description': 'קובץ בינארי - לא ניתן להציג',
                                 'tags': file.get('tags', []),
                                 'size': format_file_size(len(code.encode('utf-8')) if code else 0),
                                 'lines': 0,
                                 'created_at': format_datetime_display(file.get('created_at')),
                                 'updated_at': format_datetime_display(file.get('updated_at')),
                                 'version': file.get('version', 1)
                             },
                             highlighted_code='<div class="alert alert-warning" style="text-align: center; padding: 3rem;"><i class="fas fa-lock" style="font-size: 3rem; margin-bottom: 1rem;"></i><br>קובץ בינארי - לא ניתן להציג את התוכן<br><br>ניתן להוריד את הקובץ בלבד</div>',
                             syntax_css='')
        resp = Response(html, mimetype='text/html; charset=utf-8')
        resp.headers['ETag'] = etag
        resp.headers['Last-Modified'] = last_modified_str
        return resp
    
    try:
        lexer = get_lexer_by_name(language, stripall=True)
    except ClassNotFound:
        try:
            lexer = guess_lexer(code)
        except ClassNotFound:
            lexer = get_lexer_by_name('text')
    
    formatter = HtmlFormatter(
        style='github-dark',
        linenos=True,
        cssclass='source',
        lineanchors='line',
        anchorlinenos=True
    )
    
    highlighted_code = highlight(code, lexer, formatter)
    css = formatter.get_style_defs('.source')
    
    file_data = {
        'id': str(file['_id']),
        'file_name': file['file_name'],
        'language': language,
        'icon': get_language_icon(language),
        'description': file.get('description', ''),
        'tags': file.get('tags', []),
        'size': format_file_size(len(code.encode('utf-8'))),
        'lines': len(code.splitlines()),
        'created_at': format_datetime_display(file.get('created_at')),
        'updated_at': format_datetime_display(file.get('updated_at')),
        'version': file.get('version', 1),
        'is_favorite': bool(file.get('is_favorite', False)),
    }
    
    html = render_template('view_file.html',
                         user=session['user_data'],
                         file=file_data,
                         highlighted_code=highlighted_code,
                         syntax_css=css,
                         raw_code=code)
    resp = Response(html, mimetype='text/html; charset=utf-8')
    resp.headers['ETag'] = etag
    resp.headers['Last-Modified'] = last_modified_str
    return resp


@app.route('/api/file/<file_id>/preview')
@login_required
@traced("file.preview")
def file_preview(file_id):
    """מחזיר preview (עד 20 שורות ראשונות) של קובץ קוד כ-HTML מודגש.

    שימושי להצגה מהירה בתוך כרטיס בעמוד הקבצים, ללא ניווט לעמוד מלא.
    """
    db = get_db()
    user_id = session['user_id']

    # שליפת הקובץ למשתמש הנוכחי
    try:
        file = db.code_snippets.find_one({
            '_id': ObjectId(file_id),
            'user_id': user_id,
        })
    except (InvalidId, TypeError):
        return jsonify({'ok': False, 'error': 'Invalid file ID'}), 400
    except PyMongoError as e:
        logger.exception("DB error fetching file preview", extra={
            "file_id": file_id,
            "user_id": user_id,
            "error": str(e),
        })
        return jsonify({'ok': False, 'error': 'Database error'}), 500

    if not file:
        return jsonify({'ok': False, 'error': 'File not found'}), 404

    code = file.get('code', '') or ''
    language = (file.get('programming_language') or 'text').lower()

    if not code.strip():
        return jsonify({'ok': False, 'error': 'File is empty'}), 400

    # אם נשמר כ-text אבל הסיומת .md – תייג כ-markdown לתצוגה נכונה
    try:
        if (not language or language == 'text') and str(file.get('file_name') or '').lower().endswith('.md'):
            language = 'markdown'
    except Exception:
        pass

    # הגבלת גודל עבור preview כדי להגן על הלקוח (נמדד בבייטים)
    MAX_PREVIEW_SIZE = 100 * 1024  # 100KB
    try:
        size_bytes = len(code.encode('utf-8', errors='replace'))
    except Exception:
        # הגנה קיצונית: אם אירעה תקלה חריגה, נ fallback לאורך התווים
        size_bytes = len(code)
    if size_bytes > MAX_PREVIEW_SIZE:
        return jsonify({'ok': False, 'error': 'File too large for preview', 'size': size_bytes}), 413

    # מניעת תצוגת קבצים בינאריים
    if is_binary_file(code, file.get('file_name', '')):
        return jsonify({'ok': False, 'error': 'Binary file cannot be previewed'}), 400

    # בניית קטע התצוגה – 20 שורות ראשונות
    lines = code.split('\n')
    total_lines = len(lines)
    preview_lines = min(20, total_lines)
    preview_code = '\n'.join(lines[:preview_lines])

    # הדגשת תחביר
    try:
        lexer = get_lexer_by_name(language, stripall=True)
    except ClassNotFound:
        try:
            lexer = guess_lexer(preview_code)
        except ClassNotFound:
            lexer = get_lexer_by_name('text')

    formatter = HtmlFormatter(
        style='github-dark',
        linenos=False,
        cssclass='preview-highlight',
        nowrap=False,
    )
    highlighted_html = highlight(preview_code, lexer, formatter)
    css = formatter.get_style_defs('.preview-highlight')

    return jsonify({
        'ok': True,
        'highlighted_html': highlighted_html,
        'syntax_css': css,
        'total_lines': total_lines,
        'preview_lines': preview_lines,
        'language': language,
        'has_more': total_lines > preview_lines,
    })

@app.route('/api/files/recent')
@login_required
def api_recent_files():
    """מחזיר רשימת קבצים שנפתחו לאחרונה עבור המשתמש הנוכחי בלבד.

    מדלג על רשומות חסרות או לא תקפות (ללא מזהה קובץ, או קובץ שלא קיים/לא פעיל),
    ומחזיר לכל היותר 10 פריטים תקינים בפורמט:
    [{id, filename, language, size, accessed_at}]
    """
    try:
        db = get_db()
        user_id = session['user_id']
        ensure_recent_opens_indexes()

        # שלוף יותר מ-10 כדי לפצות על דילוג פריטים לא תקינים
        raw_cursor = db.recent_opens.find({'user_id': user_id}) \
            .sort('last_opened_at', DESCENDING) \
            .limit(30)

        results = []
        seen_ids = set()
        for rdoc in raw_cursor:
            if len(results) >= 10:
                break
            try:
                last_file_id = rdoc.get('last_opened_file_id')
                file_name_hint = (rdoc.get('file_name') or '').strip()

                file_doc = None
                # נסה לפי מזהה אחרון
                if last_file_id:
                    try:
                        q = {
                            '_id': last_file_id,
                            'user_id': user_id,
                            '$or': [
                                {'is_active': True},
                                {'is_active': {'$exists': False}}
                            ]
                        }
                        file_doc = db.code_snippets.find_one(q)
                    except Exception:
                        file_doc = None

                # fallback: אם אין מסמך לפי מזהה – נסה לפי שם הקובץ העדכני
                if file_doc is None and file_name_hint:
                    try:
                        file_doc = db.code_snippets.find_one(
                            {
                                'user_id': user_id,
                                'file_name': file_name_hint,
                                '$or': [
                                    {'is_active': True},
                                    {'is_active': {'$exists': False}}
                                ]
                            },
                            sort=[('version', DESCENDING), ('updated_at', DESCENDING), ('_id', DESCENDING)]
                        )
                    except Exception:
                        file_doc = None

                # אם עדיין אין קובץ תקין – דלג (מונע לינקים שבורים)
                if not file_doc or not file_doc.get('_id'):
                    continue

                fid = file_doc.get('_id')
                # הימנע מכפילויות באותו id
                sid = str(fid)
                if sid in seen_ids:
                    continue
                seen_ids.add(sid)

                code_str = (file_doc.get('code') or '') if isinstance(file_doc.get('code'), str) else ''
                size_bytes = len(code_str.encode('utf-8')) if code_str else 0
                lang = (file_doc.get('programming_language') or rdoc.get('language') or 'text')

                results.append({
                    'id': sid,
                    'filename': str(file_doc.get('file_name') or file_name_hint or ''),
                    'language': str(lang).lower(),
                    'size': size_bytes,
                    'accessed_at': (rdoc.get('last_opened_at') or datetime.now(timezone.utc)).isoformat(),
                })
            except Exception:
                # שמור עמידות – דלג על מסמך בעייתי
                continue

        return jsonify(results)
    except Exception as e:
        try:
            logger.exception("Error fetching recent files", extra={"error": str(e)})
        except Exception:
            pass
        return jsonify({'error': 'Failed to fetch recent files'}), 500

@app.route('/api/files/resolve')
@login_required
def api_resolve_file_by_name():
    """Resolve latest active file id by exact file_name for current user.

    Returns JSON: {ok: bool, id?: str, language?: str, file_name?: str}
    """
    try:
        db = get_db()
        user_id = session['user_id']
        name = (request.args.get('name') or '').strip()
        if not name:
            return jsonify({'ok': False, 'error': 'missing name'}), 400

        try:
            # Prefer the latest version for this user and file name
            doc = db.code_snippets.find_one(
                {
                    'user_id': user_id,
                    'file_name': name,
                    '$or': [
                        {'is_active': True},
                        {'is_active': {'$exists': False}},
                    ],
                },
                sort=[('version', DESCENDING), ('updated_at', DESCENDING), ('_id', DESCENDING)],
            )
        except Exception:
            doc = None

        if not doc:
            return jsonify({'ok': False, 'error': 'not_found'})

        lang = (doc.get('programming_language') or 'text').lower()
        return jsonify({'ok': True, 'id': str(doc.get('_id')), 'file_name': doc.get('file_name'), 'language': lang})
    except Exception as e:
        try:
            logger.error('api_resolve_file_by_name failed: %s', e)
        except Exception:
            pass
        return jsonify({'ok': False, 'error': 'internal_error'}), 500

@app.route('/edit/<file_id>', methods=['GET', 'POST'])
@login_required
def edit_file_page(file_id):
    """עריכת קובץ קיים: טופס עריכה ושמירת גרסה חדשה."""
    db = get_db()
    user_id = session['user_id']
    try:
        file = db.code_snippets.find_one({'_id': ObjectId(file_id), 'user_id': user_id})
    except Exception:
        file = None
    if not file:
        abort(404)

    error = None
    success = None

    if request.method == 'POST':
        try:
            file_name = (request.form.get('file_name') or '').strip()
            code = request.form.get('code') or ''
            # נרמול התוכן כדי להסיר תווים נסתרים וליישר פורמט עוד לפני שמירה
            code = normalize_code(code)
            language = (request.form.get('language') or '').strip() or (file.get('programming_language') or 'text')
            description = (request.form.get('description') or '').strip()
            raw_tags = (request.form.get('tags') or '').strip()
            tags = [t.strip() for t in re.split(r'[,#\n]+', raw_tags) if t.strip()] if raw_tags else list(file.get('tags') or [])

            if not file_name:
                error = 'יש להזין שם קובץ'
            elif not code:
                error = 'יש להזין תוכן קוד'
            else:
                # זיהוי שפה בסיסי אם לא סופק
                if not language or language == 'text':
                    try:
                        from utils import detect_language_from_filename as _dl
                        language = _dl(file_name) or 'text'
                    except Exception:
                        language = 'text'

                # נסיון ניחוש שפה לפי תוכן כאשר נותר text
                if language == 'text' and code:
                    try:
                        lex = None
                        try:
                            lex = guess_lexer(code)
                        except Exception:
                            lex = None
                        if lex is not None:
                            lex_name = (getattr(lex, 'name', '') or '').lower()
                            aliases = [a.lower() for a in getattr(lex, 'aliases', []) or []]
                            cand = lex_name or (aliases[0] if aliases else '')
                            def _normalize_lang(name: str) -> str:
                                n = name.lower()
                                if 'python' in n or n in {'py'}:
                                    return 'python'
                                if n in {'javascript', 'js', 'node', 'nodejs'} or 'javascript' in n:
                                    return 'javascript'
                                if n in {'typescript', 'ts'}:
                                    return 'typescript'
                                if n in {'c++', 'cpp', 'cxx'}:
                                    return 'cpp'
                                if n == 'c':
                                    return 'c'
                                if n in {'c#', 'csharp'}:
                                    return 'csharp'
                                if n in {'go', 'golang'}:
                                    return 'go'
                                if n in {'rust', 'rs'}:
                                    return 'rust'
                                if 'java' in n:
                                    return 'java'
                                if 'kotlin' in n:
                                    return 'kotlin'
                                if n in {'ruby', 'rb'}:
                                    return 'ruby'
                                if n in {'php'}:
                                    return 'php'
                                if n in {'swift'}:
                                    return 'swift'
                                if n in {'html', 'htm'}:
                                    return 'html'
                                if n in {'css', 'scss', 'sass', 'less'}:
                                    return 'css'
                                if n in {'bash', 'sh', 'shell', 'zsh'}:
                                    return 'bash'
                                if n in {'sql'}:
                                    return 'sql'
                                if n in {'yaml', 'yml'}:
                                    return 'yaml'
                                if n in {'json'}:
                                    return 'json'
                                if n in {'xml'}:
                                    return 'xml'
                                if 'markdown' in n or n in {'md'}:
                                    return 'markdown'
                                return 'text'
                            guessed = _normalize_lang(cand)
                            if guessed != 'text':
                                language = guessed
                    except Exception:
                        pass

                # חיזוק מיפוי: אם הסיומת .md והשפה עדיין לא זוהתה כ-markdown – תיוג כ-markdown
                try:
                    if isinstance(file_name, str) and file_name.lower().endswith('.md') and (not language or language.lower() == 'text'):
                        language = 'markdown'
                except Exception:
                    pass

                # עדכון שם קובץ לפי השפה (אם אין סיומת או .txt)
                try:
                    lang_to_ext = {
                        'python': 'py',
                        'javascript': 'js',
                        'typescript': 'ts',
                        'java': 'java',
                        'cpp': 'cpp',
                        'c': 'c',
                        'csharp': 'cs',
                        'go': 'go',
                        'rust': 'rs',
                        'ruby': 'rb',
                        'php': 'php',
                        'swift': 'swift',
                        'kotlin': 'kt',
                        'html': 'html',
                        'css': 'css',
                        'sql': 'sql',
                        'bash': 'sh',
                        'shell': 'sh',
                        'yaml': 'yaml',
                        'json': 'json',
                        'xml': 'xml',
                        'markdown': 'md',
                        'scss': 'scss',
                        'sass': 'sass',
                        'less': 'less',
                    }
                    lang_key = (language or 'text').lower()
                    target_ext = lang_to_ext.get(lang_key)
                    if target_ext:
                        base, curr_ext = os.path.splitext(file_name or '')
                        curr_ext_lower = curr_ext.lower()
                        wanted_dot_ext = f'.{target_ext}'
                        if base:
                            if curr_ext_lower == '':
                                file_name = f"{base}{wanted_dot_ext}"
                            elif curr_ext_lower in {'.txt', '.text'} and curr_ext_lower != wanted_dot_ext:
                                file_name = f"{base}{wanted_dot_ext}"
                except Exception:
                    pass

                # קבע גרסה חדשה על סמך שם הקובץ לאחר העדכון
                try:
                    prev = db.code_snippets.find_one(
                        {
                            'user_id': user_id,
                            'file_name': file_name,
                            '$or': [
                                {'is_active': True},
                                {'is_active': {'$exists': False}}
                            ]
                        },
                        sort=[('version', -1)]
                    )
                except Exception:
                    prev = None
                version = int((prev or {}).get('version', 0) or 0) + 1
                if not description:
                    try:
                        description = (prev or file or {}).get('description') or ''
                    except Exception:
                        description = ''
                if not tags:
                    try:
                        tags = list((prev or file or {}).get('tags') or [])
                    except Exception:
                        tags = []

                now = datetime.now(timezone.utc)
                new_doc = {
                    'user_id': user_id,
                    'file_name': file_name,
                    'code': code,
                    'programming_language': language,
                    'description': description,
                    'tags': tags,
                    'version': version,
                    'created_at': now,
                    'updated_at': now,
                    'is_active': True,
                }
                try:
                    res = db.code_snippets.insert_one(new_doc)
                    if res and getattr(res, 'inserted_id', None):
                        return redirect(url_for('view_file', file_id=str(res.inserted_id)))
                    error = 'שמירת הקובץ נכשלה'
                except Exception as _e:
                    error = f'שמירת הקובץ נכשלה: {_e}'
        except Exception as e:
            error = f'שגיאה בעריכה: {e}'

    # טופס עריכה (GET או POST עם שגיאה)
    try:
        languages = db.code_snippets.distinct('programming_language', {'user_id': user_id}) if db is not None else []
        languages = sorted([l for l in languages if l]) if languages else []
    except Exception:
        languages = []

    # המרה לנתונים לתבנית
    code_value = file.get('code') or ''
    file_data = {
        'id': str(file.get('_id')),
        'file_name': file.get('file_name') or '',
        'language': file.get('programming_language') or 'text',
        'description': file.get('description') or '',
        'tags': file.get('tags') or [],
        'version': file.get('version', 1),
    }

    return render_template('edit_file.html',
                         user=session['user_data'],
                         file=file_data,
                         code_value=code_value,
                         languages=languages,
                         error=error,
                         success=success,
                         bot_username=BOT_USERNAME_CLEAN)

@app.route('/download/<file_id>')
@login_required
@traced("files.download")
def download_file(file_id):
    """הורדת קובץ"""
    db = get_db()
    user_id = session['user_id']
    
    try:
        file = db.code_snippets.find_one({
            '_id': ObjectId(file_id),
            'user_id': user_id
        })
    except (InvalidId, TypeError):
        abort(404)
    except PyMongoError as e:
        logger.exception("DB error fetching file for download", extra={"file_id": file_id, "user_id": user_id, "error": str(e)})
        abort(500)
    
    if not file:
        abort(404)
    
    # קביעת סיומת קובץ
    language = file.get('programming_language', 'txt')
    extensions = {
        'python': 'py',
        'javascript': 'js',
        'typescript': 'ts',
        'java': 'java',
        'cpp': 'cpp',
        'c': 'c',
        'csharp': 'cs',
        'go': 'go',
        'rust': 'rs',
        'ruby': 'rb',
        'php': 'php',
        'swift': 'swift',
        'kotlin': 'kt',
        'html': 'html',
        'css': 'css',
        'sql': 'sql',
        'bash': 'sh',
        'shell': 'sh',
        'dockerfile': 'dockerfile',
        'yaml': 'yaml',
        'json': 'json',
        'xml': 'xml',
        'markdown': 'md'
    }
    
    ext = extensions.get(language.lower(), 'txt')
    filename = file['file_name']
    if not filename.endswith(f'.{ext}'):
        filename = f"{filename}.{ext}"
    
    # יצירת קובץ זמני והחזרתו
    from io import BytesIO
    file_content = BytesIO(file['code'].encode('utf-8'))
    file_content.seek(0)
    
    return send_file(
        file_content,
        as_attachment=True,
        download_name=filename,
        mimetype='text/plain'
    )

@app.route('/html/<file_id>')
@login_required
def html_preview(file_id):
    """תצוגת דפדפן לקובץ HTML בתוך iframe עם sandbox."""
    db = get_db()
    user_id = session['user_id']
    try:
        file = db.code_snippets.find_one({
            '_id': ObjectId(file_id),
            'user_id': user_id
        })
    except Exception:
        abort(404)
    if not file:
        abort(404)

    language = (file.get('programming_language') or '').lower()
    file_name = file.get('file_name') or 'index.html'
    # מציגים תצוגת דפדפן רק לקבצי HTML
    if language != 'html' and not (isinstance(file_name, str) and file_name.lower().endswith(('.html', '.htm'))):
        return redirect(url_for('view_file', file_id=file_id))

    file_data = {
        'id': str(file.get('_id')),
        'file_name': file_name,
        'language': language or 'html',
    }
    return render_template('html_preview.html', user=session.get('user_data', {}), file=file_data, bot_username=BOT_USERNAME_CLEAN)

@app.route('/raw_html/<file_id>')
@login_required
def raw_html(file_id):
    """מחזיר את ה-HTML הגולמי להצגה בתוך ה-iframe (אותו דומיין)."""
    db = get_db()
    user_id = session['user_id']
    try:
        file = db.code_snippets.find_one({
            '_id': ObjectId(file_id),
            'user_id': user_id
        })
    except Exception:
        abort(404)
    if not file:
        abort(404)

    code = file.get('code') or ''
    # קביעת מצב הרצה: ברירת מחדל ללא סקריפטים
    allow = (request.args.get('allow') or request.args.get('mode') or '').strip().lower()
    scripts_enabled = allow in {'1', 'true', 'yes', 'scripts', 'js'}
    if scripts_enabled:
        csp = \
            "sandbox allow-scripts; " \
            "default-src 'none'; " \
            "base-uri 'none'; " \
            "form-action 'none'; " \
            "connect-src 'none'; " \
            "img-src data:; " \
            "style-src 'unsafe-inline'; " \
            "font-src data:; " \
            "object-src 'none'; " \
            "frame-ancestors 'self'; " \
            "script-src 'unsafe-inline'"
        # שים לב: גם במצב זה ה-iframe נשאר בסנדבוקס ללא allow-forms/allow-popups/allow-same-origin
    else:
        csp = \
            "sandbox; " \
            "default-src 'none'; " \
            "base-uri 'none'; " \
            "form-action 'none'; " \
            "connect-src 'none'; " \
            "img-src data:; " \
            "style-src 'unsafe-inline'; " \
            "font-src data:; " \
            "object-src 'none'; " \
            "frame-ancestors 'self'; " \
            "script-src 'none'"

    resp = Response(code, mimetype='text/html; charset=utf-8')
    resp.headers['Content-Security-Policy'] = csp
    resp.headers['X-Content-Type-Options'] = 'nosniff'
    resp.headers['Referrer-Policy'] = 'no-referrer'
    resp.headers['Cache-Control'] = 'no-store'
    return resp

@app.route('/md/<file_id>')
@login_required
def md_preview(file_id):
    """תצוגת Markdown מעוצבת ועשירה, עם הרחבות GFM/KaTeX/Mermaid.

    מציג קבצי Markdown (.md) בדפדפן ברינדור עשיר. לא מבצע הרצת סקריפטים מהתוכן.
    הרינדור עצמו מתבצע בצד הלקוח באמצעות ספריות CDN (markdown-it + plugins),
    ומופעלות תוספות ביצועים כגון טעינה עצלה לתמונות ו-render מדורג למסמכים ארוכים.
    """
    db = get_db()
    user_id = session['user_id']
    try:
        file = db.code_snippets.find_one({
            '_id': ObjectId(file_id),
            'user_id': user_id
        })
    except Exception:
        abort(404)
    if not file:
        abort(404)

    file_name = (file.get('file_name') or '').strip()
    language = (file.get('programming_language') or '').strip().lower()
    # אם סומן כ-text אך הסיומת .md – התייחס אליו כ-markdown
    if (not language or language == 'text') and file_name.lower().endswith('.md'):
        language = 'markdown'
    code = file.get('code') or ''

    # --- HTTP cache validators (ETag / Last-Modified) ---
    etag = _compute_file_etag(file)
    last_modified_dt = _safe_dt_from_doc(file.get('updated_at') or file.get('created_at'))
    last_modified_str = http_date(last_modified_dt)
    inm = request.headers.get('If-None-Match')
    if inm and inm == etag:
        resp = Response(status=304)
        resp.headers['ETag'] = etag
        resp.headers['Last-Modified'] = last_modified_str
        return resp
    ims = request.headers.get('If-Modified-Since')
    if ims:
        try:
            ims_dt = parse_date(ims)
        except Exception:
            ims_dt = None
        if ims_dt is not None and last_modified_dt.replace(microsecond=0) <= ims_dt:
            resp = Response(status=304)
            resp.headers['ETag'] = etag
            resp.headers['Last-Modified'] = last_modified_str
            return resp

    # --- Cache: תוצר ה-HTML של תצוגת Markdown (תבנית) ---
    should_cache = getattr(cache, 'is_enabled', False)
    md_cache_key = None
    if should_cache:
        try:
            # בתצוגה זו התוכן מגיע כתוכן גולמי ומעובד בצד לקוח; ה-HTML תלוי רק בפרמטרים הללו
            _params = {
                'file_name': file_name,
                'lang': 'markdown',
            }
            _raw = json.dumps(_params, sort_keys=True, ensure_ascii=False)
            _hash = hashlib.sha256(_raw.encode('utf-8')).hexdigest()[:24]
            md_cache_key = f"web:md_preview:user:{user_id}:{file_id}:{_hash}"
            cached_html = cache.get(md_cache_key)
            if isinstance(cached_html, str) and cached_html:
                resp = Response(cached_html, mimetype='text/html; charset=utf-8')
                resp.headers['ETag'] = etag
                resp.headers['Last-Modified'] = last_modified_str
                return resp
        except Exception:
            md_cache_key = f"web:md_preview:user:{user_id}:{file_id}:fallback"

    # הצג תצוגת Markdown רק אם זה אכן Markdown
    is_md = language == 'markdown' or file_name.lower().endswith('.md')
    if not is_md:
        return redirect(url_for('view_file', file_id=file_id))

    file_data = {
        'id': str(file.get('_id')),
        'file_name': file_name or 'README.md',
        'language': 'markdown',
    }
    # העבר את התוכן ללקוח בתור JSON כדי למנוע בעיות escaping
    html = render_template(
        'md_preview.html',
        user=session.get('user_data', {}),
        file=file_data,
        md_code=code,
        bot_username=BOT_USERNAME_CLEAN,
        can_save_shared=False,
    )
    if should_cache and md_cache_key:
        try:
            cache.set_dynamic(
                md_cache_key,
                html,
                "markdown_render",
                {
                    "user_id": user_id,
                    "user_tier": session.get("user_tier", "regular"),
                    "last_modified_hours_ago": max(0.0, (datetime.now(timezone.utc) - (file.get('updated_at') or last_modified_dt)).total_seconds() / 3600.0) if file else 24,
                    "endpoint": "md_preview",
                },
            )
        except Exception:
            try:
                cache.set(md_cache_key, html, MD_PREVIEW_CACHE_TTL)
            except Exception:
                pass
    resp = Response(html, mimetype='text/html; charset=utf-8')
    resp.headers['ETag'] = etag
    resp.headers['Last-Modified'] = last_modified_str
    return resp

@app.route('/api/share/<file_id>', methods=['POST'])
@login_required
@traced("share.create_single")
def create_public_share(file_id):
    """יוצר קישור ציבורי לשיתוף הקובץ ומחזיר את ה-URL."""
    try:
        db = get_db()
        user_id = session['user_id']

        try:
            file = db.code_snippets.find_one({
                '_id': ObjectId(file_id),
                'user_id': user_id
            })
        except Exception:
            return jsonify({'ok': False, 'error': 'קובץ לא נמצא'}), 404

        if not file:
            return jsonify({'ok': False, 'error': 'קובץ לא נמצא'}), 404

        payload = {}
        try:
            payload = request.get_json(silent=True) or {}
        except Exception:
            payload = {}

        share_type = ''
        try:
            share_type = str(payload.get('type') or payload.get('mode') or payload.get('variant') or request.args.get('type') or request.args.get('variant') or request.args.get('mode') or '').strip().lower()
        except Exception:
            share_type = ''

        permanent_flag = False
        if share_type in {'permanent', 'forever'}:
            permanent_flag = True
        elif isinstance(payload.get('permanent'), bool):
            permanent_flag = payload.get('permanent')
        elif isinstance(payload.get('permanent'), str):
            try:
                permanent_flag = payload.get('permanent').strip().lower() in {'1', 'true', 'yes'}
            except Exception:
                permanent_flag = False
        elif request.args.get('permanent') is not None:
            try:
                permanent_flag = str(request.args.get('permanent')).strip().lower() in {'1', 'true', 'yes'}
            except Exception:
                permanent_flag = False

        share_id = secrets.token_urlsafe(12)
        now = datetime.now(timezone.utc)
        expires_at = None if permanent_flag else now + timedelta(days=PUBLIC_SHARE_TTL_DAYS)

        doc = {
            'share_id': share_id,
            'file_name': file.get('file_name') or 'snippet.txt',
            'code': file.get('code') or '',
            'language': (file.get('programming_language') or 'text'),
            'description': file.get('description') or '',
            'created_at': now,
            'views': 0,
            'is_permanent': permanent_flag,
        }
        if not permanent_flag and expires_at is not None:
            doc['expires_at'] = expires_at

        coll = db.internal_shares
        # ניסיון ליצור אינדקסים רלוונטיים (בטוח לקרוא מספר פעמים)
        try:
            from pymongo import ASCENDING, DESCENDING
            coll.create_index([('share_id', ASCENDING)], name='share_id_unique', unique=True)
            coll.create_index([('created_at', DESCENDING)], name='created_at_desc')
            coll.create_index([('expires_at', ASCENDING)], name='expires_ttl', expireAfterSeconds=0)
        except Exception:
            pass

        try:
            coll.insert_one(doc)
        except Exception:
            return jsonify({'ok': False, 'error': 'שגיאה בשמירה'}), 500

        # בסיס ליצירת URL ציבורי: קודם PUBLIC_BASE_URL, אחר כך WEBAPP_URL, ולבסוף host_url מהבקשה
        base = (PUBLIC_BASE_URL or WEBAPP_URL or request.host_url or '').rstrip('/')
        share_url = f"{base}/share/{share_id}" if base else f"/share/{share_id}"

        response_payload = {
            'ok': True,
            'url': share_url,
            'share_id': share_id,
            'is_permanent': permanent_flag,
        }
        if expires_at is not None:
            response_payload['expires_at'] = expires_at.isoformat()

        return jsonify(response_payload)
    except Exception:
        return jsonify({'ok': False, 'error': 'שגיאה לא צפויה'}), 500


@app.route('/api/shared/save', methods=['POST'])
@login_required
def api_save_shared_file():
    try:
        payload = request.get_json(silent=True) or {}
        share_id = str(payload.get('share_id') or '').strip()
        if not share_id:
            return jsonify({'ok': False, 'error': 'share_id נדרש'}), 400

        share_doc = get_internal_share(share_id)
        if not share_doc:
            return jsonify({'ok': False, 'error': 'השיתוף לא נמצא'}), 404

        raw_code = share_doc.get('code', '')
        code = normalize_code(raw_code if isinstance(raw_code, str) else str(raw_code or ''))

        requested_name = str(payload.get('file_name') or share_doc.get('file_name') or '').strip()
        if not requested_name:
            requested_name = 'מדריך WebApp'
        safe_name = requested_name
        name_path = Path(safe_name)
        if not name_path.suffix:
            safe_name = f"{safe_name}.md"
        elif name_path.suffix.lower() not in {'.md', '.markdown'}:
            safe_name = f"{name_path.stem}.md"

        language = (share_doc.get('language') or 'markdown').lower()
        if not language or language == 'text':
            language = 'markdown'

        user_id = session['user_id']
        db = get_db()
        now_utc = datetime.now(timezone.utc)

        try:
            prev = db.code_snippets.find_one(
                {
                    'user_id': user_id,
                    'file_name': safe_name,
                    '$or': [
                        {'is_active': True},
                        {'is_active': {'$exists': False}}
                    ]
                },
                sort=[('version', -1)],
            )
        except Exception:
            prev = None

        version = int((prev or {}).get('version', 0) or 0) + 1
        description = share_doc.get('description') or (prev or {}).get('description') or ''
        try:
            tags = list((prev or {}).get('tags') or [])
        except Exception:
            tags = []

        snippet_doc = {
            'user_id': user_id,
            'file_name': safe_name,
            'code': code,
            'programming_language': language,
            'description': description,
            'tags': tags,
            'version': version,
            'created_at': now_utc,
            'updated_at': now_utc,
            'is_active': True,
        }

        try:
            res = db.code_snippets.insert_one(snippet_doc)
        except Exception as exc:
            logger.exception("Failed to save shared guide", extra={'share_id': share_id, 'user_id': user_id, 'error': str(exc)})
            return jsonify({'ok': False, 'error': 'שמירת המדריך נכשלה'}), 500

        inserted_id = str(getattr(res, 'inserted_id', '') or '')

        try:
            cache.invalidate_user_cache(user_id)
            cache.invalidate_file_related(file_id=safe_name, user_id=user_id)
        except Exception:
            pass

        return jsonify({'ok': True, 'file_id': inserted_id, 'file_name': safe_name, 'version': version})
    except Exception:
        return jsonify({'ok': False, 'error': 'שגיאה לא צפויה'}), 500


@app.route('/upload', methods=['GET', 'POST'])
@login_required
@traced("files.upload_web")
def upload_file_web():
    """העלאת קובץ חדש דרך הווב-אפליקציה."""
    db = get_db()
    user_id = session['user_id']
    error = None
    success = None
    if request.method == 'POST':
        try:
            file_name = (request.form.get('file_name') or '').strip()
            code = request.form.get('code') or ''
            language = (request.form.get('language') or '').strip() or 'text'
            description = (request.form.get('description') or '').strip()
            raw_tags = (request.form.get('tags') or '').strip()
            tags = [t.strip() for t in re.split(r'[,#\n]+', raw_tags) if t.strip()] if raw_tags else []

            # אם הועלה קובץ — נקרא ממנו ונשתמש בשמו אם אין שם קובץ בשדה
            try:
                uploaded = request.files.get('code_file')
            except Exception:
                uploaded = None
            if uploaded and hasattr(uploaded, 'filename') and uploaded.filename:
                # הגבלת גודל בסיסית (עד ~2MB)
                data = uploaded.read()
                if data and len(data) > 2 * 1024 * 1024:
                    error = 'קובץ גדול מדי (עד 2MB)'
                else:
                    try:
                        code = data.decode('utf-8')
                    except Exception:
                        try:
                            code = data.decode('latin-1')
                        except Exception:
                            code = ''
                    if not file_name:
                        file_name = uploaded.filename or ''

            # נרמול התוכן (בין אם הגיע מהטופס או מקובץ שהועלה)
            code = normalize_code(code)

            if not file_name:
                error = 'יש להזין שם קובץ'
            elif not code:
                error = 'יש להזין תוכן קוד'
            else:
                # זיהוי שפה בסיסי אם לא סופק
                if not language or language == 'text':
                    try:
                        from utils import detect_language_from_filename as _dl
                        language = _dl(file_name) or 'text'
                    except Exception:
                        language = 'text'

                # אם עדיין לא זוהתה שפה (או הוגדרה כ-text) ננסה לנחש לפי התוכן
                if language == 'text' and code:
                    try:
                        lex = None
                        try:
                            lex = guess_lexer(code)
                        except Exception:
                            lex = None
                        if lex is not None:
                            lex_name = (getattr(lex, 'name', '') or '').lower()
                            aliases = [a.lower() for a in getattr(lex, 'aliases', []) or []]
                            cand = lex_name or (aliases[0] if aliases else '')
                            # מיפוי שמות/כינויים של Pygments לשפה פנימית
                            def _normalize_lang(name: str) -> str:
                                n = name.lower()
                                if 'python' in n or n in {'py'}:
                                    return 'python'
                                if n in {'javascript', 'js', 'node', 'nodejs'} or 'javascript' in n:
                                    return 'javascript'
                                if n in {'typescript', 'ts'}:
                                    return 'typescript'
                                if n in {'c++', 'cpp', 'cxx'}:
                                    return 'cpp'
                                if n == 'c':
                                    return 'c'
                                if n in {'c#', 'csharp'}:
                                    return 'csharp'
                                if n in {'go', 'golang'}:
                                    return 'go'
                                if n in {'rust', 'rs'}:
                                    return 'rust'
                                if 'java' in n:
                                    return 'java'
                                if 'kotlin' in n:
                                    return 'kotlin'
                                if n in {'ruby', 'rb'}:
                                    return 'ruby'
                                if n in {'php'}:
                                    return 'php'
                                if n in {'swift'}:
                                    return 'swift'
                                if n in {'html', 'htm'}:
                                    return 'html'
                                if n in {'css', 'scss', 'sass', 'less'}:
                                    # נעדיף css כשלא ברור
                                    return 'css'
                                if n in {'bash', 'sh', 'shell', 'zsh'}:
                                    return 'bash'
                                if n in {'sql'}:
                                    return 'sql'
                                if n in {'yaml', 'yml'}:
                                    return 'yaml'
                                if n in {'json'}:
                                    return 'json'
                                if n in {'xml'}:
                                    return 'xml'
                                if 'markdown' in n or n in {'md'}:
                                    return 'markdown'
                                return 'text'
                            guessed = _normalize_lang(cand)
                            if guessed != 'text':
                                language = guessed
                    except Exception:
                        pass

                # חיזוק מיפוי: אם הסיומת .md והשפה עדיין לא זוהתה כ-markdown – תיוג כ-markdown
                try:
                    if isinstance(file_name, str) and file_name.lower().endswith('.md') and (not language or language.lower() == 'text'):
                        language = 'markdown'
                except Exception:
                    pass

                # עדכון שם קובץ כך שיתאם את השפה (סיומת מתאימה)
                try:
                    lang_to_ext = {
                        'python': 'py',
                        'javascript': 'js',
                        'typescript': 'ts',
                        'java': 'java',
                        'cpp': 'cpp',
                        'c': 'c',
                        'csharp': 'cs',
                        'go': 'go',
                        'rust': 'rs',
                        'ruby': 'rb',
                        'php': 'php',
                        'swift': 'swift',
                        'kotlin': 'kt',
                        'html': 'html',
                        'css': 'css',
                        'sql': 'sql',
                        'bash': 'sh',
                        'shell': 'sh',
                        'yaml': 'yaml',
                        'json': 'json',
                        'xml': 'xml',
                        'markdown': 'md',
                        'scss': 'scss',
                        'sass': 'sass',
                        'less': 'less',
                        # שפות נוספות יישארו ללא שינוי
                    }
                    lang_key = (language or 'text').lower()
                    target_ext = lang_to_ext.get(lang_key)
                    if target_ext:
                        base, curr_ext = os.path.splitext(file_name or '')
                        curr_ext_lower = curr_ext.lower()
                        wanted_dot_ext = f'.{target_ext}'
                        if not base:
                            # שם ריק – לא נשנה כאן
                            pass
                        elif curr_ext_lower == '':
                            file_name = f"{base}{wanted_dot_ext}"
                        elif curr_ext_lower in {'.txt', '.text'} and curr_ext_lower != wanted_dot_ext:
                            file_name = f"{base}{wanted_dot_ext}"
                        # אם קיימת סיומת לא-טקסט ואחרת – נשאיר כפי שהיא כדי לכבד את שם הקובץ שהוזן
                except Exception:
                    pass
                # שמירה ישירה במסד (להימנע מתלות ב-BOT_TOKEN של שכבת הבוט)
                try:
                    # קבע גרסה חדשה על בסיס האחרונה הפעילה
                    prev = db.code_snippets.find_one(
                        {
                            'user_id': user_id,
                            'file_name': file_name,
                            '$or': [
                                {'is_active': True},
                                {'is_active': {'$exists': False}}
                            ]
                        },
                        sort=[('version', -1)]
                    )
                except Exception:
                    prev = None
                version = int((prev or {}).get('version', 0) or 0) + 1
                if not description:
                    try:
                        description = (prev or {}).get('description') or ''
                    except Exception:
                        description = ''
                prev_tags = []
                try:
                    prev_tags = list((prev or {}).get('tags') or [])
                except Exception:
                    prev_tags = []
                # אל תוסיף תגיות repo:* כברירת מחדל בעת העלאה חדשה; שמור רק תגיות רגילות אם המשתמש לא הקליד
                safe_prev_tags = [t for t in prev_tags if not (isinstance(t, str) and t.strip().lower().startswith('repo:'))]
                final_tags = tags if tags else safe_prev_tags

                now = datetime.now(timezone.utc)
                doc = {
                    'user_id': user_id,
                    'file_name': file_name,
                    'code': code,
                    'programming_language': language,
                    'description': description,
                    'tags': final_tags,
                    'version': version,
                    'created_at': now,
                    'updated_at': now,
                    'is_active': True,
                }
                try:
                    res = db.code_snippets.insert_one(doc)
                except Exception as _e:
                    res = None
                if res and getattr(res, 'inserted_id', None):
                    return redirect(url_for('view_file', file_id=str(res.inserted_id)))
                error = 'שמירת הקובץ נכשלה'
        except Exception as e:
            error = f'שגיאה בהעלאה: {e}'
    # שליפת שפות קיימות להצעה
    languages = db.code_snippets.distinct('programming_language', {'user_id': user_id}) if db is not None else []
    languages = sorted([l for l in languages if l]) if languages else []
    return render_template('upload.html', bot_username=BOT_USERNAME_CLEAN, user=session['user_data'], languages=languages, error=error, success=success)

@app.route('/api/favorite/toggle/<file_id>', methods=['POST'])
@login_required
def api_toggle_favorite(file_id):
    """טוגל מועדפים עבור קובץ: מעדכן את המסמך הפעיל העדכני לפי file_name למשתמש."""
    try:
        db = get_db()
        user_id = session['user_id']
        try:
            src = db.code_snippets.find_one({'_id': ObjectId(file_id), 'user_id': user_id})
        except Exception:
            src = None
        if not src:
            return jsonify({'ok': False, 'error': 'קובץ לא נמצא'}), 404

        file_name = src.get('file_name')
        if not file_name:
            return jsonify({'ok': False, 'error': 'שם קובץ חסר'}), 400

        current = bool(src.get('is_favorite', False))
        new_state = not current
        now = datetime.now(timezone.utc)

        # עדכן את הגרסאות הפעילות האחרונות עבור אותו שם קובץ
        q = {
            'user_id': user_id,
            'file_name': file_name,
            '$or': [
                {'is_active': True},
                {'is_active': {'$exists': False}}
            ]
        }
        try:
            db.code_snippets.update_many(q, {
                '$set': {
                    'is_favorite': new_state,
                    'favorited_at': (now if new_state else None),
                    'updated_at': now,
                }
            })
        except Exception:
            return jsonify({'ok': False, 'error': 'לא ניתן לעדכן מועדפים'}), 500

        return jsonify({'ok': True, 'state': new_state})
    except Exception:
        return jsonify({'ok': False, 'error': 'שגיאה לא צפויה'}), 500

@app.route('/api/files/bulk-favorite', methods=['POST'])
@login_required
@traced("files.bulk_favorite")
def api_files_bulk_favorite():
    """הוספת is_favorite=True לקבוצת קבצים של המשתמש."""
    try:
        data = request.get_json(silent=True) or {}
        file_ids = list(data.get('file_ids') or [])
        if not file_ids:
            return jsonify({'success': False, 'error': 'No files selected'}), 400
        if len(file_ids) > 100:
            return jsonify({'success': False, 'error': 'Too many files (max 100)'}), 400

        try:
            object_ids = [ObjectId(fid) for fid in file_ids]
        except Exception:
            return jsonify({'success': False, 'error': 'Invalid file id'}), 400

        db = get_db()
        user_id = session['user_id']
        now = datetime.now(timezone.utc)

        q = {
            '_id': {'$in': object_ids},
            'user_id': user_id,
            '$or': [
                {'is_active': True},
                {'is_active': {'$exists': False}}
            ]
        }
        res = db.code_snippets.update_many(q, {
            '$set': {
                'is_favorite': True,
                'favorited_at': now,
                'updated_at': now,
            }
        })
        return jsonify({'success': True, 'updated': int(getattr(res, 'modified_count', 0))})
    except Exception:
        return jsonify({'success': False, 'error': 'שגיאה לא צפויה'}), 500

@app.route('/api/files/bulk-unfavorite', methods=['POST'])
@login_required
@traced("files.bulk_unfavorite")
def api_files_bulk_unfavorite():
    """ביטול is_favorite לקבוצת קבצים של המשתמש."""
    try:
        data = request.get_json(silent=True) or {}
        file_ids = list(data.get('file_ids') or [])
        if not file_ids:
            return jsonify({'success': False, 'error': 'No files selected'}), 400
        if len(file_ids) > 100:
            return jsonify({'success': False, 'error': 'Too many files (max 100)'}), 400

        try:
            object_ids = [ObjectId(fid) for fid in file_ids]
        except Exception:
            return jsonify({'success': False, 'error': 'Invalid file id'}), 400

        db = get_db()
        user_id = session['user_id']
        now = datetime.now(timezone.utc)

        q = {
            '_id': {'$in': object_ids},
            'user_id': user_id,
            '$or': [
                {'is_active': True},
                {'is_active': {'$exists': False}}
            ]
        }
        res = db.code_snippets.update_many(q, {
            '$set': {
                'is_favorite': False,
                'favorited_at': None,
                'updated_at': now,
            }
        })
        return jsonify({'success': True, 'updated': int(getattr(res, 'modified_count', 0))})
    except Exception:
        return jsonify({'success': False, 'error': 'שגיאה לא צפויה'}), 500

@app.route('/api/files/bulk-tag', methods=['POST'])
@login_required
@traced("files.bulk_tag")
def api_files_bulk_tag():
    """הוספת תגיות לקבוצת קבצים של המשתמש ללא כפילויות."""
    try:
        data = request.get_json(silent=True) or {}
        file_ids = list(data.get('file_ids') or [])
        tags = list(data.get('tags') or [])
        if not file_ids:
            return jsonify({'success': False, 'error': 'No files selected'}), 400
        if len(file_ids) > 100:
            return jsonify({'success': False, 'error': 'Too many files (max 100)'}), 400
        # נרמול תגיות – מחרוזות לא ריקות בלבד
        safe_tags = []
        for t in tags:
            try:
                s = str(t).strip()
            except Exception:
                s = ''
            if s:
                safe_tags.append(s)
        # הסר כפילויות תוך שמירה על סדר יחסי
        seen = set()
        norm_tags = [x for x in safe_tags if not (x in seen or seen.add(x))]
        if not norm_tags:
            return jsonify({'success': False, 'error': 'No tags provided'}), 400

        try:
            object_ids = [ObjectId(fid) for fid in file_ids]
        except Exception:
            return jsonify({'success': False, 'error': 'Invalid file id'}), 400

        db = get_db()
        user_id = session['user_id']
        now = datetime.now(timezone.utc)

        q = {
            '_id': {'$in': object_ids},
            'user_id': user_id,
            '$or': [
                {'is_active': True},
                {'is_active': {'$exists': False}}
            ]
        }
        res = db.code_snippets.update_many(q, {
            '$addToSet': {'tags': {'$each': norm_tags}},
            '$set': {'updated_at': now}
        })
        return jsonify({'success': True, 'updated': int(getattr(res, 'modified_count', 0))})
    except Exception:
        return jsonify({'success': False, 'error': 'שגיאה לא צפויה'}), 500

@app.route('/api/files/create-zip', methods=['POST'])
@login_required
@traced("files.create_zip")
def api_files_create_zip():
    """יצירת קובץ ZIP עם קבצים נבחרים של המשתמש."""
    try:
        data = request.get_json(silent=True) or {}
        file_ids = list(data.get('file_ids') or [])
        if not file_ids:
            return jsonify({'success': False, 'error': 'No files selected'}), 400
        if len(file_ids) > 100:
            return jsonify({'success': False, 'error': 'Too many files (max 100)'}), 400

        try:
            object_ids = [ObjectId(fid) for fid in file_ids]
        except Exception:
            return jsonify({'success': False, 'error': 'Invalid file id'}), 400

        db = get_db()
        user_id = session['user_id']

        # שליפת הקבצים השייכים למשתמש בלבד
        cursor = db.code_snippets.find({
            '_id': {'$in': object_ids},
            'user_id': user_id,
            '$or': [
                {'is_active': True},
                {'is_active': {'$exists': False}}
            ]
        })

        from io import BytesIO
        import zipfile

        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
            for doc in cursor:
                filename = (doc.get('file_name') or f"file_{str(doc.get('_id'))}.txt").strip() or f"file_{str(doc.get('_id'))}.txt"
                # ודא שם ייחודי אם יש כפילויות
                try:
                    # מניעת שמות תיקיה מסוכנים
                    filename = filename.replace('..', '_').replace('/', '_').replace('\\', '_')
                except Exception:
                    filename = f"file_{str(doc.get('_id'))}.txt"
                content = doc.get('code')
                if not isinstance(content, str):
                    content = ''
                zf.writestr(filename, content)

        zip_buffer.seek(0)
        ts = int(time.time())
        return send_file(zip_buffer, mimetype='application/zip', as_attachment=True, download_name=f'code_files_{ts}.zip')
    except Exception:
        return jsonify({'success': False, 'error': 'שגיאה לא צפויה'}), 500

@app.route('/api/files/create-share-link', methods=['POST'])
@login_required
@traced("share.create_multi")
def api_files_create_share_link():
    """יוצר קישור שיתוף ציבורי לקבצים נבחרים ומחזיר URL."""
    try:
        data = request.get_json(silent=True) or {}
        file_ids = list(data.get('file_ids') or [])
        if not file_ids:
            return jsonify({'success': False, 'error': 'No files selected'}), 400
        if len(file_ids) > 100:
            return jsonify({'success': False, 'error': 'Too many files (max 100)'}), 400

        try:
            object_ids = [ObjectId(fid) for fid in file_ids]
        except Exception:
            return jsonify({'success': False, 'error': 'Invalid file id'}), 400

        db = get_db()
        user_id = session['user_id']

        # אימות שהקבצים שייכים למשתמש
        owned_count = db.code_snippets.count_documents({
            '_id': {'$in': object_ids},
            'user_id': user_id
        })
        if owned_count != len(object_ids):
            return jsonify({'success': False, 'error': 'Some files not found'}), 404

        token = secrets.token_urlsafe(32)
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(days=PUBLIC_SHARE_TTL_DAYS)

        db.share_links.insert_one({
            'token': token,
            'file_ids': object_ids,
            'user_id': user_id,
            'created_at': now,
            'expires_at': expires_at,
            'view_count': 0,
        })

        base_url = (WEBAPP_URL or request.host_url.rstrip('/')).rstrip('/')
        share_url = f"{base_url}/shared/{token}"
        return jsonify({'success': True, 'share_url': share_url, 'expires_at': expires_at.isoformat(), 'token': token})
    except Exception:
        return jsonify({'success': False, 'error': 'שגיאה לא צפויה'}), 500

@app.route('/api/files/bulk-delete', methods=['POST'])
@login_required
@traced("files.bulk_delete")
def api_files_bulk_delete():
    """מחיקה רכה (soft delete) לקבוצת קבצים – מסמן is_active=False עם תוקף שחזור.

    קלט JSON:
    - file_ids: List[str]
    - ttl_days: Optional[int] – אם לא סופק, יילקח מ־RECYCLE_TTL_DAYS (ברירת מחדל 7)
    """
    try:
        data = request.get_json(silent=True) or {}
        file_ids = list(data.get('file_ids') or [])
        # ברירת מחדל מ-ENV (RECYCLE_TTL_DAYS); אם התקבל ערך לא חוקי – השתמש בברירת המחדל
        raw_ttl = data.get('ttl_days')
        if raw_ttl is None or str(raw_ttl).strip() == '':
            ttl_days = RECYCLE_TTL_DAYS_DEFAULT
        else:
            try:
                ttl_days = int(raw_ttl)
            except Exception:
                ttl_days = RECYCLE_TTL_DAYS_DEFAULT
        if ttl_days < 1:
            ttl_days = RECYCLE_TTL_DAYS_DEFAULT
        if ttl_days > 30:
            ttl_days = 30

        if not file_ids:
            return jsonify({'success': False, 'error': 'No files selected'}), 400
        # המרה ל-ObjectId והסרת כפילויות לשמירה על לוגיקה עקבית בספירה/אימות
        try:
            object_ids = [ObjectId(fid) for fid in file_ids]
        except Exception:
            return jsonify({'success': False, 'error': 'Invalid file id'}), 400
        # שמור סדר אך הסר כפילויות
        unique_object_ids = list(dict.fromkeys(object_ids))
        if len(unique_object_ids) > 100:
            return jsonify({'success': False, 'error': 'Too many files (max 100)'}), 400

        db = get_db()
        user_id = session['user_id']
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(days=ttl_days)

        # אימות בעלות ואיסוף סטטוס is_active לכל קובץ; תוצאה אחת לכל ID ייחודי
        docs = list(db.code_snippets.find(
            {'_id': {'$in': unique_object_ids}, 'user_id': user_id},
            {'_id': 1, 'is_active': 1}
        ))
        found_ids = {doc['_id'] for doc in docs}
        if len(found_ids) != len(unique_object_ids):
            return jsonify({'success': False, 'error': 'Some files not found'}), 404
        # קבצים פעילים למחיקה (מוגדר כ-True או לא קיים)
        active_ids = [doc['_id'] for doc in docs if bool(doc.get('is_active', True))]
        skipped_already_deleted = len(unique_object_ids) - len(active_ids)

        modified_count = 0
        if active_ids:
            q = {
                '_id': {'$in': active_ids},
                'user_id': user_id,
                '$or': [
                    {'is_active': True},
                    {'is_active': {'$exists': False}}
                ]
            }
            res = db.code_snippets.update_many(q, {
                '$set': {
                    'is_active': False,
                    'deleted_at': now,
                    'deleted_expires_at': expires_at,
                    'updated_at': now,
                }
            })
            modified_count = int(getattr(res, 'modified_count', 0))
        return jsonify({
            'success': True,
            'deleted': modified_count,
            'skipped_already_deleted': skipped_already_deleted,
            'requested': len(unique_object_ids),
            'message': f'הקבצים הועברו לסל המחזור ל-{ttl_days} ימים'
        })
    except Exception:
        return jsonify({'success': False, 'error': 'שגיאה לא צפויה'}), 500

@app.route('/api/stats')
@login_required
def api_stats():
    """API לקבלת סטטיסטיקות"""
    db = get_db()
    user_id = session['user_id']

    # --- Cache: JSON סטטיסטיקות לפי משתמש ופרמטרים ---
    should_cache = getattr(cache, 'is_enabled', False)
    try:
        _params = {
            # לעתיד: אם יתווספו פילטרים לסטטיסטיקות ב-query string
        }
        _raw = json.dumps(_params, sort_keys=True, ensure_ascii=False)
        _hash = hashlib.sha256(_raw.encode('utf-8')).hexdigest()[:16]
        stats_cache_key = f"api:stats:user:{user_id}:{_hash}"
    except Exception:
        stats_cache_key = f"api:stats:user:{user_id}:v1"

    if should_cache:
        try:
            cached_json = cache.get(stats_cache_key)
            if isinstance(cached_json, dict) and cached_json:
                # ETag בסיסי לפי hash של גוף ה‑JSON השמור בקאש
                try:
                    etag = 'W/"' + hashlib.sha256(json.dumps(cached_json, sort_keys=True, ensure_ascii=False).encode('utf-8')).hexdigest()[:16] + '"'
                    inm = request.headers.get('If-None-Match')
                    if inm and inm == etag:
                        return Response(status=304)
                    resp = jsonify(cached_json)
                    resp.headers['ETag'] = etag
                    return resp
                except Exception:
                    return jsonify(cached_json)
        except Exception:
            pass
    
    active_query = {
        'user_id': user_id,
        '$or': [
            {'is_active': True},
            {'is_active': {'$exists': False}}
        ]
    }
    
    stats = {
        'total_files': db.code_snippets.count_documents(active_query),
        'languages': list(db.code_snippets.distinct('programming_language', active_query)),
        'recent_activity': []
    }
    
    recent = db.code_snippets.find(
        active_query,
        {'file_name': 1, 'created_at': 1}
    ).sort('created_at', DESCENDING).limit(10)
    
    for item in recent:
        stats['recent_activity'].append({
            'file_name': item['file_name'],
            'created_at': item.get('created_at', datetime.now()).isoformat()
        })
    
    if should_cache:
        try:
            cache.set_dynamic(
                stats_cache_key,
                stats,
                "user_stats",
                {
                    "user_id": user_id,
                    "user_tier": session.get("user_tier", "regular"),
                    "endpoint": "api_stats",
                    "access_frequency": "high",
                },
            )
        except Exception:
            try:
                cache.set(stats_cache_key, stats, API_STATS_CACHE_TTL)
            except Exception:
                pass
    # הוספת ETag לתגובה גם כאשר לא שוחזר מהקאש
    try:
        etag = 'W/"' + hashlib.sha256(json.dumps(stats, sort_keys=True, ensure_ascii=False).encode('utf-8')).hexdigest()[:16] + '"'
        inm = request.headers.get('If-None-Match')
        if inm and inm == etag:
            return Response(status=304)
        resp = jsonify(stats)
        resp.headers['ETag'] = etag
        return resp
    except Exception:
        return jsonify(stats)

@app.route('/settings')
@login_required
def settings():
    """דף הגדרות"""
    user_id = session['user_id']
    
    # בדיקה אם המשתמש הוא אדמין
    user_is_admin = is_admin(user_id)
    # בדיקה אם המשתמש הוא פרימיום
    user_is_premium = is_premium(user_id)

    # בדיקה האם יש חיבור קבוע פעיל
    has_persistent = False
    try:
        db = get_db()
        token = request.cookies.get(REMEMBER_COOKIE_NAME)
        if token:
            doc = db.remember_tokens.find_one({'token': token, 'user_id': user_id})
            if doc:
                exp = doc.get('expires_at')
                if isinstance(exp, datetime):
                    has_persistent = exp > datetime.now(timezone.utc)
                else:
                    try:
                        has_persistent = datetime.fromisoformat(str(exp)) > datetime.now(timezone.utc)
                    except Exception:
                        has_persistent = False
    except Exception:
        has_persistent = False

    return render_template('settings.html',
                         user=session['user_data'],
                         is_admin=user_is_admin,
                         is_premium=user_is_premium,
                         persistent_login_enabled=has_persistent,
                         persistent_days=PERSISTENT_LOGIN_DAYS)

@app.route('/health')
@_limiter_exempt()
def health():
    """בדיקת תקינות"""
    health_data = {
        'status': 'checking',
        'message': 'Web app is running!',
        'version': '2.0.0',
        'database': 'unknown',
        'config': {},
        'timestamp': datetime.now(timezone.utc).isoformat()
    }
    
    # בדיקת משתני סביבה
    health_data['config'] = {
        'MONGODB_URL': 'configured' if MONGODB_URL else 'missing',
        'BOT_TOKEN': 'configured' if BOT_TOKEN else 'missing',
        'BOT_USERNAME': BOT_USERNAME or 'missing',
        'DATABASE_NAME': DATABASE_NAME,
        'WEBAPP_URL': WEBAPP_URL
    }
    
    # בדיקת חיבור למסד נתונים
    try:
        if not MONGODB_URL:
            health_data['database'] = 'not configured'
            health_data['status'] = 'unhealthy'
            health_data['error'] = 'MONGODB_URL is not configured'
        else:
            db = get_db()
            db.command('ping')
            health_data['database'] = 'connected'
            health_data['status'] = 'healthy'
    except Exception as e:
        health_data['database'] = 'error'
        health_data['status'] = 'unhealthy'
        # אל נחשוף פירוט חריגה
        health_data['error'] = 'unhealthy'
    
    return jsonify(health_data)


@app.route('/api/cache/stats', methods=['GET'])
@login_required
def api_cache_stats():
    """החזרת סטטיסטיקות Redis/Cache למטרות ניטור (מאובטח למשתמש מחובר)."""
    try:
        stats = cache.get_stats()
        return jsonify(stats)
    except Exception:
        return jsonify({"enabled": False, "error": "unavailable"}), 200


@app.route('/api/cache/warm', methods=['POST'])
@login_required
def api_cache_warm():
    """חימום קאש בסיסי למשתמש הנוכחי: סטטיסטיקות + הצעות חיפוש.

    קלט אופציונלי (JSON):
      {
        "suggestions": ["def", "class", ...],
        "limit": 10
      }
    """
    try:
        user_id = session['user_id']
        payload = request.get_json(silent=True) or {}
        seeds = payload.get('suggestions') or ["def", "class", "import", "todo", "fix", "bug"]
        limit = int(payload.get('limit') or 10)

        # 1) Warm stats (reuse logic from /api/stats, but simplified)
        try:
            db = get_db()
            active_query = {
                'user_id': user_id,
                '$or': [
                    {'is_active': True},
                    {'is_active': {'$exists': False}}
                ]
            }
            stats = {
                'total_files': db.code_snippets.count_documents(active_query),
                'languages': list(db.code_snippets.distinct('programming_language', active_query)),
                'recent_activity': []
            }
            recent = db.code_snippets.find(active_query, {'file_name': 1, 'created_at': 1}).sort('created_at', DESCENDING).limit(10)
            for item in recent:
                stats['recent_activity'].append({
                    'file_name': item.get('file_name', ''),
                    'created_at': (item.get('created_at') or datetime.now()).isoformat()
                })
            # cache key same as /api/stats
            _raw = json.dumps({}, sort_keys=True, ensure_ascii=False)
            _hash = hashlib.sha256(_raw.encode('utf-8')).hexdigest()[:16]
            stats_cache_key = f"api:stats:user:{user_id}:{_hash}"
            try:
                cache.set_dynamic(
                    stats_cache_key,
                    stats,
                    "user_stats",
                    {
                        "user_id": user_id,
                        "user_tier": session.get("user_tier", "regular"),
                        "endpoint": "api_stats",
                        "access_frequency": "high",
                    },
                )
            except Exception:
                pass
        except Exception:
            pass

        # 2) Warm search suggestions for short seeds
        try:
            if search_engine and isinstance(seeds, list):
                for q in seeds:
                    try:
                        q_str = str(q or '').strip()
                        if len(q_str) < 2:
                            continue
                        sugg = search_engine.suggest_completions(user_id, q_str, limit=min(20, max(1, int(limit))))
                        payload = json.dumps({'q': q_str}, sort_keys=True, ensure_ascii=False)
                        h = hashlib.sha256(payload.encode('utf-8')).hexdigest()[:16]
                        key = f"api:search_suggest:{user_id}:{h}"
                        cache.set_dynamic(key, {'suggestions': sugg}, 'search_results', {'user_id': user_id, 'endpoint': 'api_search_suggestions'})
                    except Exception:
                        continue
        except Exception:
            pass

        return jsonify({"ok": True})
    except Exception:
        return jsonify({"ok": False}), 500

# API: הפעלת/ביטול חיבור קבוע
@app.route('/api/persistent_login', methods=['POST'])
@login_required
def api_persistent_login():
    try:
        db = get_db()
        user_id = session['user_id']
        payload = request.get_json(silent=True) or {}
        enable = bool(payload.get('enable'))

        resp = jsonify({'ok': True, 'enabled': enable})

        if enable:
            # צור טוקן ושמור ב-DB
            token = secrets.token_urlsafe(32)
            now = datetime.now(timezone.utc)
            expires_at = now + timedelta(days=PERSISTENT_LOGIN_DAYS)
            try:
                db.remember_tokens.create_index('token', unique=True)
                db.remember_tokens.create_index('expires_at', expireAfterSeconds=0)
            except Exception:
                pass
            db.remember_tokens.update_one(
                {'user_id': user_id},
                {'$set': {'user_id': user_id, 'token': token, 'updated_at': now, 'expires_at': expires_at}, '$setOnInsert': {'created_at': now}},
                upsert=True
            )
            resp.set_cookie(
                REMEMBER_COOKIE_NAME,
                token,
                max_age=PERSISTENT_LOGIN_DAYS * 24 * 3600,
                secure=True,
                httponly=True,
                samesite='Lax'
            )
        else:
            # נטרל: מחיקת טוקן וקוקי
            try:
                token = request.cookies.get(REMEMBER_COOKIE_NAME)
                if token:
                    db.remember_tokens.delete_one({'user_id': user_id, 'token': token})
            except Exception:
                pass
            resp.delete_cookie(REMEMBER_COOKIE_NAME)

        return resp
    except Exception:
        return jsonify({'ok': False, 'error': 'שגיאה לא צפויה'}), 500

@app.route('/api/ui_prefs', methods=['POST'])
@_limiter_exempt()
@login_required
def api_ui_prefs():
    """שמירת העדפות UI: תומך בעדכונים חלקיים (font_scale/theme/editor/work_state).

    קלט JSON נתמך:
    - font_scale: float בין 0.85 ל-1.6 (אופציונלי)
    - theme: אחד מ-{"classic","ocean","forest","high-contrast"} (אופציונלי)
    - editor: "simple" | "codemirror" (אופציונלי)
    - work_state: אובייקט עם מצב עבודה נוכחי (last_url, scroll_y, timestamp)
    """
    try:
        payload = request.get_json(silent=True) or {}

        db = get_db()
        user_id = session['user_id']
        now_utc = datetime.now(timezone.utc)

        update_fields: Dict[str, Any] = {'updated_at': now_utc}
        resp_payload: Dict[str, Any] = {'ok': True}
        # נשמור ערכים בטוחים בלבד עבור קובצי cookie
        font_scale_cookie_value: Optional[str] = None
        theme_cookie_value: Optional[str] = None

        # עדכון גודל גופן במידת הצורך
        if 'font_scale' in payload:
            try:
                font_scale = float(payload.get('font_scale'))
                if font_scale < 0.85:
                    font_scale = 0.85
                if font_scale > 1.6:
                    font_scale = 1.6
                update_fields['ui_prefs.font_scale'] = font_scale
                resp_payload['font_scale'] = font_scale
                font_scale_cookie_value = f"{font_scale:.2f}"
            except Exception:
                return jsonify({'ok': False, 'error': 'font_scale must be a number'}), 400

        # עדכון ערכת צבעים במידת הצורך
        if 'theme' in payload:
            theme = (payload.get('theme') or '').strip().lower()
            if theme in {'classic', 'ocean', 'forest', 'high-contrast'}:
                update_fields['ui_prefs.theme'] = theme
                resp_payload['theme'] = theme
                theme_cookie_value = theme

        # עדכון סוג העורך במידת הצורך (שיקוף גם ל-session)
        if 'editor' in payload:
            editor_type = (payload.get('editor') or '').strip().lower()
            if editor_type in {'simple', 'codemirror'}:
                update_fields['ui_prefs.editor'] = editor_type
                session['preferred_editor'] = editor_type
                resp_payload['editor'] = editor_type

        # עדכון work_state (שחזור מצב עבודה חוצה סשנים)
        if 'work_state' in payload:
            try:
                ws = payload.get('work_state') or {}
                safe_ws: Dict[str, Any] = {}
                lu = str(ws.get('last_url') or '').strip()
                if lu.startswith('/') and len(lu) <= 512:
                    safe_ws['last_url'] = lu
                try:
                    sy = float(ws.get('scroll_y'))
                    if sy < 0:
                        sy = 0.0
                    if sy > 10_000_000:
                        sy = 10_000_000.0
                    safe_ws['scroll_y'] = int(sy)
                except Exception:
                    pass
                ts = str(ws.get('timestamp') or '').strip()
                if ts:
                    safe_ws['timestamp'] = ts[:64]
                if safe_ws:
                    update_fields['ui_prefs.work_state'] = safe_ws
                    resp_payload['work_state'] = safe_ws
            except Exception:
                pass

        # אם לא התקבל אף שדה עדכני – אין מה לעדכן
        if len(update_fields) == 1:  # רק updated_at
            return jsonify({'ok': True})

        db.users.update_one({'user_id': user_id}, {'$set': update_fields}, upsert=True)

        # עדכון קוקיז רק עבור שדות שסופקו
        resp = jsonify(resp_payload)
        try:
            if font_scale_cookie_value is not None:
                resp.set_cookie(
                    'ui_font_scale',
                    font_scale_cookie_value,
                    max_age=365*24*3600,
                    samesite='Lax',
                    secure=True,
                    httponly=True,
                )
            if theme_cookie_value is not None:
                resp.set_cookie(
                    'ui_theme',
                    theme_cookie_value,
                    max_age=365*24*3600,
                    samesite='Lax',
                    secure=True,
                    httponly=True,
                )
        except Exception:
            pass
        return resp
    except Exception:
        return jsonify({'ok': False, 'error': 'שגיאה לא צפויה'}), 500


@app.route('/api/welcome/ack', methods=['POST'])
@login_required
def api_welcome_ack():
    try:
        db = get_db()
        user_id = session['user_id']
        now_utc = datetime.now(timezone.utc)
        db.users.update_one(
            {'user_id': user_id},
            {'$set': {'has_seen_welcome_modal': True, 'updated_at': now_utc}, '$setOnInsert': {'created_at': now_utc}},
            upsert=True,
        )
        try:
            user_data = dict(session.get('user_data') or {})
            user_data['has_seen_welcome_modal'] = True
            session['user_data'] = user_data
            session.modified = True
        except Exception:
            pass
        return jsonify({'ok': True})
    except Exception:
        return jsonify({'ok': False, 'error': 'שגיאה לא צפויה'}), 500


# --- User preferences (generic) ---
@app.route('/api/user/preferences', methods=['POST'])
@login_required
def update_user_preferences():
    """עדכון העדפות משתמש כלליות (כעת: סוג עורך).

    מבנה קלט צפוי (JSON): { "editor_type": "simple" | "codemirror" }
    """
    try:
        payload = request.get_json(silent=True) or {}
        editor_type = (payload.get('editor_type') or '').strip().lower()
        if editor_type not in {'simple', 'codemirror'}:
            return jsonify({'ok': False, 'error': 'Invalid editor type'}), 400

        # עדכון session כדי להשפיע מיידית ב-render
        session['preferred_editor'] = editor_type

        # שמירה ב-DB תחת ui_prefs.editor לשימור חוצה דיפלוימנטים
        try:
            from datetime import datetime, timezone
            db = get_db()
            user_id = session['user_id']
            db.users.update_one(
                {'user_id': user_id},
                {'$set': {'ui_prefs.editor': editor_type, 'updated_at': datetime.now(timezone.utc)}},
                upsert=True,
            )
        except Exception:
            # לא מפילים את הבקשה במקרה של DB בעייתי – נשמור לפחות בסשן
            pass

        return jsonify({'ok': True, 'editor_type': editor_type})
    except Exception:
        return jsonify({'ok': False, 'error': 'שגיאה לא צפויה'}), 500

# --- Public statistics for landing/mini web app ---
@app.route('/api/public_stats')
@_limiter_exempt()
def api_public_stats():
    """סטטיסטיקות גלובליות להצגה בעמוד הבית/מיני-ווב ללא התחברות.

    מחזיר:
    - total_users: סה"כ משתמשים שנוצרו אי פעם
    - active_users_24h: משתמשים שהיו פעילים ב-24 השעות האחרונות (updated_at)
    - total_snippets: סה"כ קטעי קוד ייחודיים שנשמרו אי פעם (distinct לפי user_id+file_name) כאשר התוכן לא ריק — כולל כאלה שנמחקו (is_active=false)
    """
    try:
        db = get_db()
        now_utc = datetime.now(timezone.utc)
        last_24h = now_utc - timedelta(hours=24)

        # Users
        try:
            total_users = int(db.users.count_documents({}))
        except Exception:
            total_users = 0
        try:
            active_users_24h = int(db.users.count_documents({"updated_at": {"$gte": last_24h}}))
        except Exception:
            active_users_24h = 0

        # Total distinct snippets (user_id+file_name), with non-empty code, including deleted (soft-deleted)
        try:
            pipeline = [
                {"$match": {"code": {"$type": "string"}}},
                {"$addFields": {
                    "code_size": {
                        "$cond": {
                            "if": {"$eq": [{"$type": "$code"}, "string"]},
                            "then": {"$strLenBytes": "$code"},
                            "else": 0,
                        }
                    }
                }},
                {"$match": {"code_size": {"$gt": 0}}},
                {"$group": {"_id": {"user_id": "$user_id", "file_name": "$file_name"}}},
                {"$count": "count"},
            ]
            res = list(db.code_snippets.aggregate(pipeline, allowDiskUse=True))
            total_snippets = int(res[0]["count"]) if res else 0
        except Exception:
            total_snippets = 0

        return jsonify({
            "ok": True,
            "total_users": total_users,
            "active_users_24h": active_users_24h,
            "total_snippets": total_snippets,
            "timestamp": now_utc.isoformat(),
        })
    except Exception as e:
        return jsonify({
            "ok": False,
            "total_users": 0,
            "active_users_24h": 0,
            "total_snippets": 0,
        }), 200

# --- Auth status & user info ---
@app.route('/api/me')
def api_me():
    """סטטוס התחברות ופרטי משתמש בסיסיים לצורך סוכנים/קליינט.

    לא זורק 401 כדי לאפשר בדיקה פשוטה; מחזיר ok=false אם לא מחובר.
    """
    try:
        is_auth = 'user_id' in session
        if not is_auth:
            return jsonify({
                'ok': False,
                'authenticated': False
            })
        user_data = session.get('user_data') or {}
        # שליפת העדפות בסיסיות מה‑DB (best-effort, ללא כשל)
        prefs = {}
        try:
            _db = get_db()
            u = _db.users.find_one({'user_id': session['user_id']}) or {}
            prefs = (u.get('ui_prefs') or {})
        except Exception:
            prefs = {}
        uid = session['user_id']
        role_flags = {
            'is_admin': is_admin(uid),
            'is_premium': is_premium(uid),
        }
        # קביעת תפקיד עיקרי ותווית ידידותית
        if role_flags['is_admin']:
            role = 'admin'
            role_label = 'משתמש אדמין'
        elif role_flags['is_premium']:
            role = 'premium'
            role_label = 'משתמש פרימיום 💎'
        else:
            role = 'regular'
            role_label = 'משתמש רגיל'

        return jsonify({
            'ok': True,
            'authenticated': True,
            'user': {
                'user_id': uid,
                'username': user_data.get('username'),
                'first_name': user_data.get('first_name'),
                'last_name': user_data.get('last_name'),
            },
            'role': role,
            'role_label': role_label,
            'roles': role_flags,
            'ui_prefs': {
                'font_scale': prefs.get('font_scale'),
                'theme': prefs.get('theme'),
                'editor': prefs.get('editor'),
                'work_state': prefs.get('work_state'),
            }
        })
    except Exception:
        return jsonify({'ok': False, 'error': 'שגיאה לא צפויה'}), 500

# --- External uptime public endpoint ---
@app.route('/api/uptime')
def api_uptime():
    """נתוני זמינות חיצוניים (ללא סודות)."""
    try:
        summary = fetch_external_uptime()
        if not summary:
            return jsonify({'ok': False, 'error': 'uptime_unavailable'}), 503
        safe = {
            'ok': True,
            'provider': summary.get('provider') or UPTIME_PROVIDER or None,
            'uptime_percentage': summary.get('uptime_percentage'),
            'status_url': summary.get('status_url') or (UPTIME_STATUS_URL or None),
        }
        return jsonify(safe)
    except Exception:
        return jsonify({'ok': False, 'error': 'שגיאה לא צפויה'}), 500

# --- Public share route ---
@app.route('/share/<share_id>')
def public_share(share_id):
    """הצגת שיתוף פנימי בצורה ציבורית ללא התחברות.

    תומך בפרמטר view=md כדי להציג קבצי Markdown בעמוד התצוגה הייעודי (עם כפתורי שיתוף).
    """
    doc = get_internal_share(share_id)
    if not doc:
        return render_template('404.html'), 404

    code = doc.get('code', '')
    language = (doc.get('language', 'text') or 'text').lower()
    file_name = doc.get('file_name', 'snippet.txt')
    description = doc.get('description', '')

    can_save_shared = bool(session.get('user_id'))
    user_context = session.get('user_data', {}) if can_save_shared else {}

    # אם view=md והמסמך Markdown – נרנדר את עמוד md_preview עם דגל is_public
    try:
        view = (request.args.get('view') or '').strip().lower()
    except Exception:
        view = ''
    is_markdown = (language == 'markdown') or (isinstance(file_name, str) and file_name.lower().endswith('.md'))
    if view == 'md' and is_markdown:
        file_data = {
            'id': share_id,
            'file_name': file_name or 'README.md',
            'language': 'markdown',
        }
        return render_template(
            'md_preview.html',
            user=user_context,
            file=file_data,
            md_code=code,
            bot_username=BOT_USERNAME_CLEAN,
            is_public=True,
            can_save_shared=can_save_shared,
        )

    # ברירת מחדל: תצוגת קוד (כמו קודם)
    try:
        lexer = get_lexer_by_name(language, stripall=True)
    except Exception:
        try:
            lexer = guess_lexer(code)
        except Exception:
            from pygments.lexers import TextLexer
            lexer = TextLexer()
    formatter = HtmlFormatter(style='github-dark', linenos=True, cssclass='source', lineanchors='line', anchorlinenos=True)
    highlighted_code = highlight(code, lexer, formatter)
    css = formatter.get_style_defs('.source')

    size = len(code.encode('utf-8'))
    lines = len(code.split('\n'))
    created_at = doc.get('created_at')
    if isinstance(created_at, datetime):
        created_at_str = created_at.strftime('%d/%m/%Y %H:%M')
    else:
        try:
            created_at_str = datetime.fromisoformat(created_at).strftime('%d/%m/%Y %H:%M') if created_at else ''
        except Exception:
            created_at_str = ''

    file_data = {
        'id': share_id,
        'file_name': file_name,
        'language': language,
        'icon': get_language_icon(language),
        'description': description,
        'tags': [],
        'size': format_file_size(size),
        'lines': lines,
        'created_at': created_at_str,
        'updated_at': created_at_str,
        'version': 1,
    }
    return render_template('view_file.html', file=file_data, highlighted_code=highlighted_code, syntax_css=css)

# --- Public multiple-files share route (tokens created via /api/files/create-share-link) ---
@app.route('/shared/<token>')
def public_shared_files(token: str):
    """עמוד שיתוף ציבורי לקבצים מרובים לפי token מ-collection share_links.

    תומך בהצגת רשימה עם קישורי הורדה/צפייה לכל קובץ. אם פג תוקף, מחזיר 404.
    """
    try:
        db = get_db()
        doc = db.share_links.find_one({'token': token})
    except Exception:
        doc = None
    if not doc:
        return render_template('404.html'), 404

    # תוקף
    exp = doc.get('expires_at')
    try:
        now = datetime.now(timezone.utc)
        if isinstance(exp, datetime):
            expired = exp <= now
        else:
            expired = True
    except Exception:
        expired = True
    if expired:
        return render_template('404.html'), 404

    # שליפת קבצים
    file_ids = [oid for oid in (doc.get('file_ids') or []) if isinstance(oid, ObjectId)]
    if not file_ids:
        return render_template('404.html'), 404
    try:
        cursor = db.code_snippets.find({'_id': {'$in': file_ids}})
        files = list(cursor)
    except Exception:
        files = []
    if not files:
        return render_template('404.html'), 404

    # בניית רשימת פריטים לתצוגה
    view_items = []
    for f in files:
        code = f.get('code', '')
        language = (f.get('programming_language') or 'text').lower()
        file_name = (f.get('file_name') or 'snippet.txt')
        size = len((code or '').encode('utf-8'))
        lines = len((code or '').split('\n'))
        view_items.append({
            'id': str(f.get('_id')),
            'file_name': file_name,
            'language': language,
            'icon': get_language_icon(language),
            'size': format_file_size(size),
            'lines': lines,
            'code': code,
        })

    # תבנית בסיסית של רשימת קבצים ששותפו
    # שימוש ב-template קיים אם יש – אחרת נציג רשימה פשוטה דרך view_file עבור פריט בודד אינו מתאים כאן
    # לכן נשתמש ב-html פשוט בתוך אותו טמפלט בסיס
    # רנדר טמפלט ייעודי כדי למנוע עמוד ריק ולתת פריסה אחידה
    return render_template('shared_files.html', items=view_items)

# Error handlers
@app.errorhandler(404)
def not_found(e):
    return render_template('404.html'), 404

@app.errorhandler(500)
def server_error(e):
    logger.exception("Server error")
    return render_template('500.html'), 500

@app.errorhandler(Exception)
def handle_exception(e):
    """טיפול בכל שגיאה אחרת"""
    if isinstance(e, HTTPException):
        return e
    logger.exception("Unhandled exception")
    import traceback
    traceback.print_exc()
    return render_template('500.html'), 500

# --- OpenAPI/Swagger/Redoc documentation endpoints ---
OPENAPI_SPEC_PATH = Path(ROOT_DIR) / 'docs' / 'openapi.yaml'

@app.route('/openapi.yaml')
def openapi_yaml():
    try:
        return send_file(OPENAPI_SPEC_PATH, mimetype='application/yaml')
    except Exception:
        return jsonify({'ok': False, 'error': 'unavailable'}), 500

@app.route('/docs')
def swagger_docs():
    html = """
<!doctype html>
<html>
  <head>
    <meta charset="utf-8"/>
    <title>API Docs</title>
    <link rel="stylesheet" href="https://unpkg.com/swagger-ui-dist@5/swagger-ui.css">
    <style>body { margin:0; } #swagger-ui { max-width: 100%; }</style>
  </head>
  <body>
    <div id="swagger-ui"></div>
    <script src="https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
    <script>
      window.onload = () => {
        window.ui = SwaggerUIBundle({ url: '/openapi.yaml', dom_id: '#swagger-ui' });
      };
    </script>
  </body>
  <script>/* Avoid CSP issues in simple dev setup */</script>
  </html>
"""
    return Response(html, mimetype='text/html')

@app.route('/redoc')
def redoc_docs():
    html = """
<!doctype html>
<html>
  <head>
    <meta charset="utf-8"/>
    <title>ReDoc</title>
    <style>body { margin:0; padding: 0; }</style>
    <script src="https://cdn.jsdelivr.net/npm/redoc@next/bundles/redoc.standalone.js"></script>
  </head>
  <body>
    <redoc spec-url='/openapi.yaml'></redoc>
    <script>
      try { Redoc.init('/openapi.yaml'); } catch (e) {}
    </script>
  </body>
</html>
"""
    return Response(html, mimetype='text/html')

# בדיקת קונפיגורציה בהפעלה
def check_configuration():
    """בדיקת משתני סביבה נדרשים"""
    required_vars = {
        'MONGODB_URL': MONGODB_URL,
        'BOT_TOKEN': BOT_TOKEN,
        'BOT_USERNAME': BOT_USERNAME
    }
    
    missing = []
    for var_name, var_value in required_vars.items():
        if not var_value:
            missing.append(var_name)
            logger.warning("Environment variable is not configured: %s", var_name, extra={"var_name": var_name})
    
    if missing:
        logger.warning("Missing required environment variables: %s", ", ".join(missing), extra={"missing": missing})
        logger.warning("Please configure them in Render Dashboard or .env file")
    
    # בדיקת חיבור ל-MongoDB
    if MONGODB_URL:
        try:
            test_client = MongoClient(MONGODB_URL, serverSelectionTimeoutMS=5000)
            test_client.server_info()
            logger.info("MongoDB connection successful")
            test_client.close()
        except Exception as e:
            logger.warning("MongoDB connection failed", exc_info=e)
    
    return len(missing) == 0

if __name__ == '__main__':
    logger.info("Starting Code Keeper Web App...")
    logger.info("BOT_USERNAME: %s", BOT_USERNAME)
    logger.info("DATABASE_NAME: %s", DATABASE_NAME)
    logger.info("WEBAPP_URL: %s", WEBAPP_URL)
    
    if check_configuration():
        logger.info("Configuration check passed")
    else:
        logger.warning("Configuration issues detected")
    
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=os.getenv('DEBUG', 'false').lower() == 'true')