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
import math
import time
import mimetypes
import uuid
import inspect
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from functools import wraps, lru_cache
from types import SimpleNamespace
from typing import Optional, Dict, Any, List, Tuple, Set
from concurrent.futures import ThreadPoolExecutor, Future

from flask import Flask, Blueprint, render_template, jsonify, request, session, redirect, url_for, send_file, abort, Response, g, flash, make_response, send_from_directory
import threading
import atexit
import time as _time
from werkzeug.http import http_date, parse_date
from werkzeug.utils import secure_filename
from urllib.parse import urlparse, urlunparse, quote as url_quote
from werkzeug.exceptions import HTTPException
from flask_compress import Compress
from pymongo import MongoClient, DESCENDING, ASCENDING
from pymongo.errors import PyMongoError
from pygments import highlight
from pygments.lexers import TextLexer, get_lexer_by_name, guess_lexer
from pygments.util import ClassNotFound
from pygments.formatters import HtmlFormatter
from pygments.styles import get_style_by_name
from bs4 import BeautifulSoup
from markdown import Markdown
from bson import ObjectId
from bson.binary import Binary
from bson.errors import InvalidId
from datetime import timedelta
import re
import sys
from pathlib import Path
import secrets
import yaml
import threading
import base64
import contextvars
import traceback
import asyncio


# Cache עבור בדיקות persistent login
_persistent_login_cache = {}
_persistent_login_cache_lock = threading.Lock()


def _check_persistent_login_cached(user_id: str) -> bool:
    """בדיקת persistent login עם cache של 60 שניות"""
    now = time.time()
    token = request.cookies.get(REMEMBER_COOKIE_NAME)
    if not token:
        return False

    # cache key כולל גם את ה-token (חלק ממנו) כדי להימנע מזיהום בין מכשירים
    cache_key = f"persistent_{user_id}_{token[:16]}"

    # בדיקת Cache (בנעילה כדי למנוע race / dict-size-change)
    with _persistent_login_cache_lock:
        if cache_key in _persistent_login_cache:
            cached_value, expires_at = _persistent_login_cache[cache_key]
            if expires_at > now:
                return cached_value

    # Cache miss - בדיקה מול DB
    has_persistent = False
    try:
        db = get_db()
        doc = db.remember_tokens.find_one({'token': token, 'user_id': user_id})
        if doc:
            exp = doc.get('expires_at')
            if isinstance(exp, datetime):
                if exp.tzinfo is None:
                    exp = exp.replace(tzinfo=timezone.utc)
                has_persistent = exp > datetime.now(timezone.utc)
            else:
                try:
                    dt = datetime.fromisoformat(str(exp))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    has_persistent = dt > datetime.now(timezone.utc)
                except Exception:
                    has_persistent = False
    except Exception:
        has_persistent = False

    # שמירה ב-cache
    with _persistent_login_cache_lock:
        _persistent_login_cache[cache_key] = (has_persistent, now + 60)

        # ניקוי cache ישן (בטוח)
        if len(_persistent_login_cache) > 1000:
            keys_to_remove = [k for k, v in list(_persistent_login_cache.items()) if v[1] < now]
            for k in keys_to_remove:
                _persistent_login_cache.pop(k, None)

    return has_persistent


# --- Logging: honor LOG_LEVEL for the WebApp process ---
def _env_log_level_name(default: str = "INFO") -> str:
    raw = os.getenv("LOG_LEVEL")
    value = (str(raw or "")).strip()
    if not value:
        return str(default or "INFO").strip().upper() or "INFO"
    upper = value.upper()
    if upper == "WARN":
        return "WARNING"
    if upper == "FATAL":
        return "CRITICAL"
    if upper.isdigit():
        return upper
    if upper in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        return upper
    return str(default or "INFO").strip().upper() or "INFO"


_WEBAPP_LOG_LEVEL_NAME = _env_log_level_name("INFO")
try:
    _WEBAPP_LOG_LEVEL = int(_WEBAPP_LOG_LEVEL_NAME) if _WEBAPP_LOG_LEVEL_NAME.isdigit() else getattr(logging, _WEBAPP_LOG_LEVEL_NAME, logging.INFO)
except Exception:
    _WEBAPP_LOG_LEVEL_NAME = "INFO"
    _WEBAPP_LOG_LEVEL = logging.INFO

_root_logger = logging.getLogger()
if not _root_logger.handlers:
    logging.basicConfig(
        level=_WEBAPP_LOG_LEVEL,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
else:
    _root_logger.setLevel(_WEBAPP_LOG_LEVEL)


# הוספת נתיב ה-root של הפרויקט ל-PYTHONPATH כדי לאפשר import ל-"database" כשהסקריפט רץ מתוך webapp/
ROOT_DIR = str(Path(__file__).resolve().parents[1])
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

# After ROOT_DIR is in sys.path, we can safely import project modules.
# Best-effort: keep redaction + structlog level in sync with LOG_LEVEL.
try:
    from utils import install_sensitive_filter  # noqa: E402
    install_sensitive_filter()
except Exception:
    pass
try:
    from observability import setup_structlog_logging as _setup_structlog_logging  # noqa: E402
    _setup_structlog_logging(_WEBAPP_LOG_LEVEL_NAME)
except Exception:
    pass

# מייבא לאחר הוספת ROOT_DIR ל-PYTHONPATH כדי למנוע כשל ייבוא בדיפלוי
from http_sync import request as http_request  # noqa: E402

# נרמול טקסט/קוד לפני שמירה (הסרת תווים נסתרים, כיווניות, אחידות שורות)
from utils import normalize_code, TimeUtils, detect_language_from_filename  # noqa: E402
from user_stats import user_stats  # noqa: E402
from webapp.activity_tracker import log_user_event  # noqa: E402
from webapp.config_radar import build_config_radar_snapshot  # noqa: E402
from services import observability_dashboard as observability_service  # noqa: E402
from services.diff_service import get_diff_service, DiffMode  # noqa: E402
from services.db_health_service import (  # noqa: E402
    SyncDatabaseHealthService,
    InvalidCollectionNameError,
    CollectionAccessDeniedError,
    MAX_SKIP,
)
from services.git_mirror_service import get_mirror_service  # noqa: E402
from services.styled_export_service import (  # noqa: E402
    get_export_theme,
    list_export_presets,
    markdown_to_html,
    render_styled_html,
)
from services.theme_parser_service import parse_vscode_theme, validate_theme_json  # noqa: E402


# --- Observability: הרצת פעולות כבדות בת׳רד (תואם Flask sync) ---
_OBSERVABILITY_THREADPOOL = ThreadPoolExecutor(
    max_workers=max(2, min(16, int(os.getenv('OBSERVABILITY_THREADPOOL_WORKERS') or 6))),
    thread_name_prefix='observability',
)


def _run_observability_blocking(func, *args, **kwargs):
    """מריץ פונקציה כבדה בת׳רד ומחזיר תוצאה (ללא async/await)."""
    return _OBSERVABILITY_THREADPOOL.submit(func, *args, **kwargs).result()

# קונפיגורציה מרכזית (Pydantic Settings)
try:  # שמירה על יציבות גם בסביבות דוקס/CI
    from config import config as cfg
except Exception:  # pragma: no cover
    cfg = None

# --- Smart Projection (Performance) ---
# ברירת מחדל למסכי רשימות: אל תמשוך שדות "כבדים" מה-DB.
# חשוב: מסכי צפייה/עריכה של קובץ בודד עדיין מושכים מסמך מלא.
try:  # prefer the canonical list projection from repository layer
    from database.repository import HEAVY_FIELDS_EXCLUDE_PROJECTION as _HEAVY_FIELDS_EXCLUDE_PROJECTION  # type: ignore
except Exception:  # pragma: no cover - fallback for minimal environments
    _HEAVY_FIELDS_EXCLUDE_PROJECTION = {"code": 0, "content": 0, "raw_content": 0}

LIST_EXCLUDE_HEAVY_PROJECTION: Dict[str, int] = dict(_HEAVY_FIELDS_EXCLUDE_PROJECTION)

DEFAULT_LANGUAGE_CHOICES = [
    "python",
    "javascript",
    "typescript",
    "html",
    "css",
    "sql",
    "json",
    "markdown",
    "xml",
    "shell",
    "bash",
    "go",
    "java",
    "yaml",
    "csharp",
]


def _load_supported_languages_from_config() -> List[str]:
    try:
        configured = list((cfg.SUPPORTED_LANGUAGES if cfg else []) or [])
        if configured:
            return configured
    except Exception:
        pass
    return list(DEFAULT_LANGUAGE_CHOICES)


def _build_language_choices(user_langs: Optional[List[str]] = None) -> List[str]:
    """איחוד שפות: נתונים קיימים של המשתמש + ברירת מחדל מהקונפיג."""
    dedup: Dict[str, str] = {}

    def _add_languages(candidates: List[str]) -> None:
        for lang in candidates or []:
            if not lang:
                continue
            lang_str = str(lang).strip()
            if not lang_str:
                continue
            if lang_str.lower() == "text":
                continue
            key = lang_str.lower()
            dedup.setdefault(key, lang_str)

    _add_languages(user_langs or [])
    _add_languages(_load_supported_languages_from_config())

    return [dedup[key] for key in sorted(dedup.keys())]


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


@app.get("/favicon.ico")
def favicon():
    """favicon ברירת מחדל (לכל האתר). דפים ספציפיים יכולים להגדיר icon אחר ב-HTML."""
    return send_from_directory(app.static_folder, "favicon.ico", mimetype="image/x-icon", max_age=31536000)


# OpenTelemetry (best-effort, fail-open)
try:
    from observability_otel import setup_telemetry as _setup_otel  # type: ignore

    _setup_otel(
        service_name=str(os.getenv("OTEL_SERVICE_NAME") or "codebot-webapp"),
        service_version=os.getenv("SERVICE_VERSION") or os.getenv("RENDER_GIT_COMMIT") or None,
        environment=os.getenv("ENVIRONMENT") or os.getenv("ENV") or None,
        flask_app=app,
    )
except Exception:
    pass
# לוגר מודולרי לשימוש פנימי
logger = logging.getLogger(__name__)

# Jobs Monitor: רישום Jobs מוכרים ל-UI/API (fail-open)
try:
    from services.register_jobs import register_all_jobs  # noqa: E402

    register_all_jobs()
except Exception:
    pass

# --- Background warmup: heavy observability reports (fire & forget) ---
_OBS_WARMUP_THREAD: Optional[threading.Thread] = None
_OBS_WARMUP_LOCK = threading.Lock()
_OBS_WARMUP_STOP_EVENT = threading.Event()


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return float(default)
    try:
        return float(str(raw).strip())
    except Exception:
        return float(default)


def _parse_timerange_seconds(raw: str | None, default_seconds: int) -> int:
    """Parse '24h'/'7d'/'30d' style duration to seconds (best-effort)."""
    if not raw:
        return int(default_seconds)
    text = str(raw).strip().lower()
    if not text:
        return int(default_seconds)
    try:
        if text.endswith("ms"):
            value = float(text[:-2])
            seconds = max(0.001, value / 1000.0)
        elif text.endswith("s"):
            seconds = float(text[:-1])
        elif text.endswith("m"):
            seconds = float(text[:-1]) * 60.0
        elif text.endswith("h"):
            seconds = float(text[:-1]) * 3600.0
        elif text.endswith("d"):
            seconds = float(text[:-1]) * 86400.0
        else:
            seconds = float(text)
    except Exception:
        return int(default_seconds)
    return max(1, int(seconds))


def _observability_warmup_ranges() -> List[str]:
    raw = os.getenv("OBSERVABILITY_WARMUP_RANGES", "24h,7d,30d")
    parts = [p.strip() for p in str(raw or "").split(",")]
    ranges = [p for p in parts if p]
    return ranges or ["24h", "7d", "30d"]


def _should_autostart_observability_warmup() -> bool:
    # Feature flag
    if not _env_bool("OBSERVABILITY_WARMUP_ENABLED", True):
        return False

    # Avoid noisy side-effects in unit tests unless explicitly forced
    if os.getenv("PYTEST_CURRENT_TEST") and not _env_bool("OBSERVABILITY_WARMUP_AUTOSTART", False):
        return False

    # Flask dev reloader imports modules twice; start only in the "real" (child) process.
    #
    # Werkzeug sets WERKZEUG_RUN_MAIN="true" only in the child process that serves requests.
    # The parent reloader process typically has it *unset* (None), which looks identical to many
    # production setups (gunicorn/uwsgi) where it's also unset.
    #
    # לכן אנחנו מזהים "סביבת reloader" לפי דגלים של flask-run/debug, ורק אז דורשים WERKZEUG_RUN_MAIN="true".
    wrm = os.getenv("WERKZEUG_RUN_MAIN")
    if wrm not in (None, ""):
        # When explicitly present, only allow the child ("true"/"1").
        if str(wrm).strip().lower() not in {"true", "1"}:
            return False
    else:
        # If it is unset, allow in production, but block in the reloader parent process.
        flask_run_from_cli = str(os.getenv("FLASK_RUN_FROM_CLI") or "").strip().lower() in {"true", "1"}
        flask_debug = str(os.getenv("FLASK_DEBUG") or "").strip().lower() in {"true", "1"}
        flask_env = str(os.getenv("FLASK_ENV") or "").strip().lower()
        likely_reloader_parent = flask_run_from_cli or flask_debug or (flask_env == "development")
        if likely_reloader_parent:
            return False

    return True


def _run_observability_warmup(stop_event: threading.Event) -> None:
    """Warm up the heavy observability aggregations cache and DB RAM."""
    delay_seconds = max(0.0, _env_float("OBSERVABILITY_WARMUP_DELAY_SECONDS", 5.0))
    budget_seconds = max(0.0, _env_float("OBSERVABILITY_WARMUP_BUDGET_SECONDS", 20.0))
    slow_endpoints_limit = max(1, min(20, int(_env_float("OBSERVABILITY_WARMUP_SLOW_LIMIT", 5.0))))

    # Delay: allow the server to start accepting requests first.
    if delay_seconds > 0:
        stop_event.wait(delay_seconds)
    if stop_event.is_set():
        return

    logger.info("🔥 Starting Background Cache Warmup...")

    t0 = _time.monotonic()
    try:
        for range_val in _observability_warmup_ranges():
            if budget_seconds and (_time.monotonic() - t0) > budget_seconds:
                logger.info("⏱️ Warmup budget exceeded; stopping early")
                break
            if stop_event.is_set():
                break

            logger.info("⏳ Warming up report: %s...", range_val)
            now = datetime.now(timezone.utc)
            seconds = _parse_timerange_seconds(range_val, default_seconds=24 * 3600)
            start_dt = now - timedelta(seconds=seconds)

            # Direct service call (no HTTP) to populate internal cache and DB RAM.
            observability_service.fetch_aggregations(
                start_dt=start_dt,
                end_dt=now,
                slow_endpoints_limit=slow_endpoints_limit,
            )

        logger.info("✅ Background Cache Warmup Completed!")
    except Exception as e:
        # Fail-open: warmup is best-effort and should never crash the process.
        logger.warning("⚠️ Warmup failed (non-critical): %s", e, exc_info=True)


def start_background_observability_warmup() -> None:
    """Start warmup thread once (non-blocking)."""
    global _OBS_WARMUP_THREAD
    if not _should_autostart_observability_warmup():
        return
    try:
        with _OBS_WARMUP_LOCK:
            if _OBS_WARMUP_THREAD is not None and _OBS_WARMUP_THREAD.is_alive():
                return
            _OBS_WARMUP_STOP_EVENT.clear()
            _OBS_WARMUP_THREAD = threading.Thread(
                target=_run_observability_warmup,
                args=(_OBS_WARMUP_STOP_EVENT,),
                name="observability_warmup",
                daemon=True,
            )
            _OBS_WARMUP_THREAD.start()
    except Exception:
        # Fail-open: never block startup due to warmup scheduling.
        return


def _stop_background_observability_warmup() -> None:
    try:
        _OBS_WARMUP_STOP_EVENT.set()
    except Exception:
        return


atexit.register(_stop_background_observability_warmup)
# זמני (חירום): ביטול Warmup בזמן startup כדי לשחרר עומס DB.
# כדי להפעיל מחדש בלי שינוי קוד: DISABLE_STARTUP_WARMUP=false
if str(os.getenv("DISABLE_STARTUP_WARMUP", "true")).lower() not in {"1", "true", "yes", "on"}:
    start_background_observability_warmup()


# --- Observability: Alert Tags indexes warmup (best-effort) ---
def start_background_alert_tags_indexes() -> None:
    """מנסה להבטיח אינדקסים ל-alert_tags ברקע (לא חוסם את השרת)."""
    # אל תרוץ ב-CI/Docs (לפי אותו כלל גלובלי)
    if str(os.getenv("DISABLE_DB", "")).lower() in {"1", "true", "yes"}:
        return
    if str(os.getenv("SPHINX_MOCK_IMPORTS", "")).lower() in {"1", "true", "yes"}:
        return
    try:
        from monitoring import alert_tags_storage  # type: ignore
    except Exception:
        return
    try:
        t = threading.Thread(target=alert_tags_storage.ensure_indexes, daemon=True, name="alert_tags_indexes")
        t.start()
    except Exception:
        return


start_background_alert_tags_indexes()

# --- Startup metrics instrumentation (נרשם רק בזמן עלייה) ---
_STARTUP_METRICS_MS: Dict[str, float] = {}
_STARTUP_METRICS_LOCK = threading.Lock()
_STARTUP_METRICS_LOGGED = False


def _record_startup_metric(name: str, duration_seconds: float | None, *, accumulate: bool = False) -> None:
    """שומר מדידה (במילי-שניות) עבור שלב העלייה – ללא תקורה בזמן ריצה."""
    if duration_seconds is None:
        return
    try:
        duration_ms = max(0.0, float(duration_seconds) * 1000.0)
    except Exception:
        return
    updated_value: float | None = None
    try:
        with _STARTUP_METRICS_LOCK:
            if accumulate:
                updated_value = duration_ms + _STARTUP_METRICS_MS.get(name, 0.0)
                _STARTUP_METRICS_MS[name] = updated_value
            else:
                existing = _STARTUP_METRICS_MS.get(name)
                if existing is None or duration_ms > existing:
                    _STARTUP_METRICS_MS[name] = duration_ms
                    updated_value = duration_ms
                else:
                    updated_value = existing
    except Exception:
        return
    try:
        record_startup_stage_metric(name, updated_value)
    except Exception:
        pass


def _emit_startup_metrics_log(total_ms: float | None = None) -> None:
    """מדפיס לוג מובנה בסיום העלייה בפורמט שניתן לניתוח."""
    global _STARTUP_METRICS_LOGGED
    with _STARTUP_METRICS_LOCK:
        if _STARTUP_METRICS_LOGGED:
            return
        _STARTUP_METRICS_LOGGED = True
        metrics_snapshot = dict(_STARTUP_METRICS_MS)
    try:
        templates_ms = metrics_snapshot.get('templates')
        mongo_ms = metrics_snapshot.get('mongo') or metrics_snapshot.get('mongo_ping')
        indexes_ms = (
            metrics_snapshot.get('indexes_recent', 0.0) +
            metrics_snapshot.get('indexes_code', 0.0) +
            metrics_snapshot.get('indexes_announcements', 0.0)
        )
        ordered_parts: list[str] = []
        for label, value in (
            ('mongo', mongo_ms),
            ('templates', templates_ms),
            ('indexes', indexes_ms),
        ):
            if value and value > 0.0:
                ordered_parts.append(f"{label}={int(round(value))}ms")
        if total_ms is None:
            try:
                total_ms = max(0.0, (_time.perf_counter() - get_boot_monotonic()) * 1000.0)
            except Exception:
                total_ms = 0.0
        ordered_parts.append(f"total={int(round(total_ms or 0.0))}ms")
        try:
            record_startup_total_metric(total_ms)
        except Exception:
            pass
        logger.info("[startup-metrics] %s", " ".join(ordered_parts))
    except Exception:
        pass

# --- Static asset version (for cache-busting of PWA manifest/icons) ---
_MANIFEST_PATH = (Path(__file__).parent / 'static' / 'manifest.json')
_STATIC_VERSION_SOURCE = "init"

def _compute_static_version() -> str:
    """Return a short version string to bust caches for static assets.

    Preference order:
    1) ASSET_VERSION env (exported by start_webapp.sh)
    2) APP_VERSION env (explicit override)
    3) VCS commit env (Render/Heroku/etc.)
    4) SHA1(first 8) of manifest.json contents
    5) Hourly rolling timestamp
    """
    global _STATIC_VERSION_SOURCE
    version_candidates = [
        ("ASSET_VERSION", os.getenv("ASSET_VERSION")),
        ("APP_VERSION", os.getenv("APP_VERSION")),
        ("RENDER_GIT_COMMIT", os.getenv("RENDER_GIT_COMMIT")),
        ("SOURCE_VERSION", os.getenv("SOURCE_VERSION")),
        ("GIT_COMMIT", os.getenv("GIT_COMMIT")),
        ("HEROKU_SLUG_COMMIT", os.getenv("HEROKU_SLUG_COMMIT")),
    ]
    for source_name, value in version_candidates:
        if value:
            _STATIC_VERSION_SOURCE = source_name.lower()
            return str(value)[:8]  # קיצור כדי לשמור על מחרוזת קצרה ויציבה
    try:
        p = _MANIFEST_PATH
        if p.is_file():
            h = hashlib.sha1(p.read_bytes()).hexdigest()  # nosec - not for security
            _STATIC_VERSION_SOURCE = "manifest_sha"
            return h[:8]
    except Exception:
        pass
    try:
        _STATIC_VERSION_SOURCE = "hourly_timestamp"
        return str(int(_time.time() // 3600))
    except Exception:
        _STATIC_VERSION_SOURCE = "default_dev"
        return "dev"

_STATIC_VERSION = _compute_static_version()
try:
    logger.info("[static-version] using=%s source=%s", _STATIC_VERSION, _STATIC_VERSION_SOURCE)
except Exception:
    pass

def _env_int(name: str, default: int) -> int:
    try:
        raw = os.getenv(name)
        if raw is None or raw.strip() == '':
            return default
        value = int(raw)
        if value <= 0:
            return default
        return value
    except Exception:
        return default

MARKDOWN_IMAGE_LIMIT = _env_int('MARKDOWN_IMAGE_LIMIT', 6)
MARKDOWN_IMAGE_MAX_BYTES = _env_int('MARKDOWN_IMAGE_MAX_BYTES', 2 * 1024 * 1024)
ALLOWED_MARKDOWN_IMAGE_TYPES = {'image/png', 'image/jpeg', 'image/webp', 'image/gif'}

# מזהי המדריכים המשותפים לזרימת ה-Onboarding בווב
# הערכים ההיסטוריים נשמרים כאליאסים כדי שקישורים ישנים ימשיכו לעבוד – בפועל נטען את המדריך
# המעודכן מקובץ USER_GUIDE.md בכל בקשה.
WELCOME_GUIDE_PRIMARY_SHARE_ID = "welcome"
WELCOME_GUIDE_SECONDARY_SHARE_ID = "welcome-quickstart"
WELCOME_GUIDE_SHARE_ALIASES = {
    WELCOME_GUIDE_PRIMARY_SHARE_ID,
    WELCOME_GUIDE_SECONDARY_SHARE_ID,
    "JjvpJFTXZO0oHtoC",
    "sdVOAx6hUGsH4Anr",
}
USER_GUIDE_PATH = Path(__file__).parent / 'USER_GUIDE.md'
WELCOME_GUIDE_FILE_NAME = "CodeKeeper-WebApp-Guide-v2.md"
WELCOME_GUIDE_DESCRIPTION = "מדריך משתמש מעודכן ל-Code Keeper WebApp (גרסה 2.0)"

# Weekly Tip feature flag (env/config override)
def _to_bool(val, default: bool = True) -> bool:
    try:
        if isinstance(val, bool):
            return val
        s = str(val).strip().lower()
        if s in ("0", "false", "no", "off", "none", ""):  # treat empty as false only if explicitly provided
            return False
        if s in ("1", "true", "yes", "on"):  # common truthy strings
            return True
        return default
    except Exception:
        return default

_WEEKLY_TIP_ENABLED_RAW = _cfg_or_env('WEEKLY_TIP_ENABLED', default='true')
WEEKLY_TIP_ENABLED = _to_bool(_WEEKLY_TIP_ENABLED_RAW, default=True)

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
            job_started = _time.perf_counter()
            # Preload Pygments lexers/formatters (import and simple use)
            try:
                from pygments.lexers import get_lexer_by_name as _g
                _t0 = _time.perf_counter()
                for _name in ("python", "javascript", "bash", "json"):
                    try:
                        _ = _g(_name)
                    except Exception:
                        pass
                duration = max(0.0, float(_time.perf_counter() - _t0))
                try:
                    record_dependency_init("pygments_lexers", duration)
                except Exception:
                    pass
                try:
                    _record_startup_metric('lexers', duration)
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
                duration = max(0.0, float(_time.perf_counter() - _t1))
                try:
                    record_dependency_init("jinja_precompile", duration)
                except Exception:
                    pass
                try:
                    _record_startup_metric('templates', duration)
                except Exception:
                    pass
            except Exception:
                pass
            # Optionally attempt DB ping + init in background (best-effort)
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
                        _ = get_db()
                    except Exception:
                        pass
                duration = max(0.0, float(_time.perf_counter() - _t0))
                try:
                    record_dependency_init("mongodb_ping", duration)
                except Exception:
                    pass
                try:
                    _record_startup_metric('mongo_ping', duration)
                except Exception:
                    pass
            except Exception:
                pass
            # Signal startup completion at the end of preload sequence
            total_ms = max(0.0, float((_time.perf_counter() - job_started) * 1000.0))
            try:
                mark_startup_complete()
            finally:
                try:
                    _emit_startup_metrics_log(total_ms=total_ms)
                except Exception:
                    pass
        _thr.Thread(target=_job, name="preload-assets", daemon=True).start()
    except Exception:
        # Never block on preload failures
        try:
            mark_startup_complete()
        finally:
            try:
                _emit_startup_metrics_log()
            except Exception:
                pass

# --- API blueprints registration ---
try:
    from webapp.bookmarks_api import bookmarks_bp  # noqa: E402
    app.register_blueprint(bookmarks_bp)
except Exception:
    # אם יש כשל בייבוא (למשל בזמן דוקס/CI בלי תלותים), אל תפיל את השרת
    pass

# GitHub Webhooks (Repo Sync Engine) - לפי המדריך
try:
    from webapp.routes.webhooks import webhooks_bp  # noqa: E402
    app.register_blueprint(webhooks_bp)
except Exception:
    # אל תפיל את השרת אם ה-Blueprint אינו זמין (למשל בסביבת דוקס/CI)
    pass

# Repo Browser UI/API (Repo Sync Engine) - לפי המדריך
try:
    from webapp.routes.repo_browser import repo_bp  # noqa: E402
    app.register_blueprint(repo_bp)
except Exception:
    # אל תפיל את השרת אם ה-Blueprint אינו זמין (למשל בסביבת דוקס/CI)
    pass

# Themes API (Presets/Import/Export) - לפי המדריך
try:
    from webapp.themes_api import themes_bp  # noqa: E402
    app.register_blueprint(themes_bp)
except Exception:
    # אל תפיל את השרת אם ה-Blueprint אינו זמין (למשל בסביבת דוקס/CI)
    pass

# Sticky Notes API (Markdown inline notes)
try:
    from webapp.sticky_notes_api import sticky_notes_bp, kickoff_index_warmup  # noqa: E402
    app.register_blueprint(sticky_notes_bp)
    # זמני (חירום): ביטול Warmup בזמן startup כדי לשחרר עומס DB.
    # כדי להפעיל מחדש בלי שינוי קוד: DISABLE_STARTUP_WARMUP=false
    if str(os.getenv("DISABLE_STARTUP_WARMUP", "true")).lower() not in {"1", "true", "yes", "on"}:
        try:
            kickoff_index_warmup()
        except Exception:
            pass
except Exception:
    # אל תפיל את היישום אם ה-Blueprint אינו זמין (למשל בסביבת דוקס/CI)
    pass

# Web Push API (public key + subscribe/unsubscribe)
try:
    from webapp.push_api import push_bp, start_sender_if_enabled  # noqa: E402
    app.register_blueprint(push_bp)
    # הפעלת שולח פושים ברקע (רק אם מאופשר בקונפיג)
    try:
        start_sender_if_enabled()
    except Exception:
        pass
except Exception:
    # סביבת דוקס/CI ללא תלויות לא צריכה להיכשל על ייבוא זה
    pass

# Code Tools API (format/lint/fix)
try:
    from webapp.code_tools_api import code_tools_bp  # noqa: E402
    app.register_blueprint(code_tools_bp)
except Exception as e:
    try:
        logger.warning(f"Failed to register code_tools_bp: {e}")
    except Exception:
        pass

# JSON Formatter API (format/minify/validate/fix)
try:
    from webapp.json_formatter_api import json_formatter_bp  # noqa: E402
    app.register_blueprint(json_formatter_bp)
except Exception as e:
    try:
        logger.warning(f"Failed to register json_formatter_bp: {e}")
    except Exception:
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
        try:
            from webapp.workspace_api import workspace_bp  # noqa: E402
            app.register_blueprint(workspace_bp, url_prefix="/api/workspace")
        except Exception as _workspace_err:
            try:
                logger.info("workspace_api blueprint not registered: %s", _workspace_err)
            except Exception:
                pass
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

# Visual Rules API (Visual Rule Engine)
try:
    from webapp.rules_api import rules_bp  # noqa: E402
    app.register_blueprint(rules_bp, url_prefix="/api/rules")
except Exception as _e:
    # אל תפיל את היישום אם ה-Blueprint אינו זמין (למשל בסביבת דוקס/CI)
    try:
        logger.info("rules_api blueprint not registered: %s", _e)
    except Exception:
        pass

# --- Metrics helpers (import guarded to avoid hard deps in docs/CI) ---
try:
    from metrics import (
        record_request_outcome,
        record_http_request,
        record_request_queue_delay,
        get_boot_monotonic,
        mark_startup_complete,
        note_first_request_latency,
        record_dependency_init,
        get_avg_response_time_seconds,
        update_health_gauges,
        record_startup_stage_metric,
        record_startup_total_metric,
        note_request_started,
        note_request_finished,
        note_deployment_started,
        note_deployment_shutdown,
     )
    _METRICS_AVAILABLE = True
except Exception:  # pragma: no cover
    _METRICS_AVAILABLE = False
    def record_request_outcome(status_code: int, duration_seconds: float, **_kwargs) -> None:
        return None
    def record_http_request(method: str, endpoint: str, status_code: int, duration_seconds: float) -> None:
        return None
    def record_request_queue_delay(method: str, endpoint: str | None, delay_seconds: float, **_kwargs) -> None:
        return None
    def get_boot_monotonic() -> float:
        return 0.0
    def mark_startup_complete() -> None:
        return None
    def note_first_request_latency(_d: float | None = None) -> None:
        return None
    def record_dependency_init(_name: str, _dur: float) -> None:
        return None
    def get_avg_response_time_seconds() -> float:
        return 0.0
    def update_health_gauges(**_kwargs) -> None:
        return None
    def record_startup_stage_metric(_stage: str, _duration_ms: float | None) -> None:
        return None
    def record_startup_total_metric(_duration_ms: float | None) -> None:
        return None
    def note_request_started() -> None:
        return None
    def note_request_finished() -> None:
        return None
    def note_deployment_started(_summary: str = "Service starting up") -> None:
        return None
    def note_deployment_shutdown(_summary: str = "Service shutting down") -> None:
        return None

# Trigger preload only after metrics helpers are available
_preload_heavy_assets_async()

try:
    note_deployment_started("webapp service starting up")
except Exception:
    pass

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
    impersonation_sessions_total = _ensure_metric(
        'admin_impersonation_sessions_total',
        lambda: Counter(
            'admin_impersonation_sessions_total',
            'Total admin impersonation sessions started',
            ['admin_id']
        )
    )
    impersonation_duration_seconds = _ensure_metric(
        'admin_impersonation_duration_seconds',
        lambda: Histogram(
            'admin_impersonation_duration_seconds',
            'Duration of admin impersonation sessions',
            buckets=[60, 300, 600, 1800, 3600]
        )
    )
else:
    search_counter = _MetricNoop()
    search_duration = _MetricNoop()
    search_results_count = _MetricNoop()
    search_cache_hits = _MetricNoop()
    search_cache_misses = _MetricNoop()
    active_indexes_gauge = _MetricNoop()
    impersonation_sessions_total = _MetricNoop()
    impersonation_duration_seconds = _MetricNoop()

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

_RATE_LIMIT_EXEMPT_USER_IDS = {6865105071}  # החרגה לפיתוח (לא מוגבל בכלל)

def _is_rate_limit_exempt_user() -> bool:
    """האם המשתמש הנוכחי מוחרג מכל ה-rate limits (אדמין או allowlist)."""
    try:
        uid_raw = session.get("user_id")
        uid = int(uid_raw) if uid_raw is not None else None
    except Exception:
        uid = None
    if uid is None:
        return False
    if uid in _RATE_LIMIT_EXEMPT_USER_IDS:
        return True
    try:
        return bool(is_admin(int(uid)))
    except Exception:
        return False

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

        # ==========================================================
        # Rate limit exemptions (dev/admin)
        # ==========================================================
        # מטרת ההחרגה: לאפשר פיתוח שוטף בלי להיחסם ע"י Rate Limiting
        # ולהחריג אדמינים מכל Endpoint.
        @limiter.request_filter
        def _rate_limit_exempt_filter() -> bool:
            return _is_rate_limit_exempt_user()
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

# עמוד הקובץ מציג שהות של 30 יום בסל המחזור (issue #1937)
WEBAPP_SINGLE_DELETE_TTL_DAYS = 30
FILE_HISTORY_MAX_VERSIONS = 25

# הגדרת חיבור קבוע (Remember Me)
try:
    PERSISTENT_LOGIN_DAYS = max(30, int(os.getenv('PERSISTENT_LOGIN_DAYS', '180')))
except Exception:
    PERSISTENT_LOGIN_DAYS = 180
REMEMBER_COOKIE_NAME = 'remember_me'

# --- Admin Impersonation ---
IMPERSONATION_SESSION_KEY = 'admin_impersonation_active'
IMPERSONATION_ORIGINAL_ADMIN_KEY = 'admin_impersonation_original_user_id'

 

# חיבור ל-MongoDB
client = None
db = None

# Cache לנתוני healthz (מדידת אינדקסים) כדי לעמוד בדרישת 300ms
_HEALTHZ_INDEX_CACHE_TTL_SECONDS = 60
_HEALTHZ_INDEX_CACHE: Dict[str, Any] = {'ts': 0.0, 'count': 0}
_HEALTHZ_INDEX_CACHE_LOCK = threading.Lock()
_HEALTHZ_CRITICAL_COLLECTIONS: Tuple[str, ...] = (
    'code_snippets',
    'recent_opens',
    'collections',
    'users',
)


def _sample_critical_index_count(db_ref) -> tuple[int, float]:
    """מודד מספר אינדקסים בסיסי עבור אוספים קריטיים (עם cache קצר)."""
    if db_ref is None:
        return (0, 0.0)
    now_ts = time.time()
    with _HEALTHZ_INDEX_CACHE_LOCK:
        cached_ts = float(_HEALTHZ_INDEX_CACHE.get('ts') or 0.0)
        if (now_ts - cached_ts) < _HEALTHZ_INDEX_CACHE_TTL_SECONDS:
            return (int(_HEALTHZ_INDEX_CACHE.get('count') or 0), 0.0)
    start = _time.perf_counter()
    total_indexes = 0
    for coll_name in _HEALTHZ_CRITICAL_COLLECTIONS:
        try:
            info = db_ref[coll_name].index_information()
            total_indexes += len(info or {})
        except Exception:
            continue
    duration = max(0.0, float(_time.perf_counter() - start))
    with _HEALTHZ_INDEX_CACHE_LOCK:
        _HEALTHZ_INDEX_CACHE['ts'] = now_ts
        _HEALTHZ_INDEX_CACHE['count'] = total_indexes
    return (total_indexes, duration)


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
    theme_scope = _normalize_theme_scope(request.cookies.get('ui_theme_scope'))
    cookie_theme = ''
    use_cookie_theme = False
    theme_raw = ''
    try:
        cookie_theme = (request.cookies.get('ui_theme') or '').strip().lower()
        theme_raw, theme_scope, use_cookie_theme, _ = _resolve_theme_raw_token(
            user_id,
            user_doc=user_doc,
        )
    except Exception:
        theme_raw = theme

    theme_type, theme_id, theme = _parse_theme_token(theme_raw)

    # Shared Theme (ui_prefs.theme = "shared:<slug>")
    shared_theme = None
    if theme_type == "shared":
        if theme_id and db_ref is not None:
            try:
                doc = db_ref.shared_themes.find_one({"_id": theme_id, "is_active": True})
                if isinstance(doc, dict) and doc.get("_id"):
                    colors = doc.get("colors", {})
                    if not isinstance(colors, dict):
                        colors = {}
                    syntax_css = doc.get("syntax_css", "")
                    if not isinstance(syntax_css, str):
                        syntax_css = ""
                    syntax_colors = doc.get("syntax_colors", {})
                    if not isinstance(syntax_colors, dict):
                        syntax_colors = {}
                    shared_theme = {
                        "id": doc.get("_id"),
                        "name": doc.get("name"),
                        "description": doc.get("description", ""),
                        "colors": colors,
                        "syntax_css": syntax_css,
                        "syntax_colors": syntax_colors,
                        "is_featured": bool(doc.get("is_featured", False)),
                    }
                else:
                    theme = "classic"
                    theme_type = "builtin"
            except Exception:
                theme = "classic"
                theme_type = "builtin"
                shared_theme = None
        else:
            theme = "classic"
            theme_type = "builtin"
            shared_theme = None

    # ערכת נושא מותאמת (אם קיימת) — מועברת לתבניות כדי לאפשר injection ב-base.html
    # תומך גם במבנה חדש (custom_themes[]) וגם בישן (custom_theme).
    custom_theme = None
    custom_theme_id = ""

    # =====================================================
    # ADMIN IMPERSONATION - חישוב בזמן אמת
    # =====================================================

    # 1. שליפת האמת האבסולוטית (לא תלויה ב-Impersonation)
    actual_is_admin = False
    actual_is_premium = False
    try:
        if user_id:
            actual_is_admin = bool(is_admin(int(user_id)))
            actual_is_premium = bool(is_premium(int(user_id)))
    except Exception:
        pass

    # 2. בדיקת מצב Impersonation עם Fail-Safe
    #    - ?force_admin=1 → עקיפה לשעת חירום
    #    - דגל פעיל + המשתמש אדמין באמת → מצב פעיל
    force_admin_override = request.args.get('force_admin') == '1'
    impersonation_flag = session.get(IMPERSONATION_SESSION_KEY, False)

    if force_admin_override:
        # 🆘 מנגנון מילוט: האדמין הוסיף ?force_admin=1 ל-URL
        user_is_impersonating = False
    else:
        # מצב Impersonation פעיל רק אם:
        # א. הדגל פעיל בסשן
        # ב. המשתמש אכן אדמין (הגנה מפני מניפולציה)
        user_is_impersonating = bool(impersonation_flag and actual_is_admin)

    # 3. חישוב הסטטוס האפקטיבי לתצוגה
    #    - אם מתחזים → לא אדמין, לא פרימיום (רואים כמשתמש רגיל)
    #    - אחרת → הסטטוס האמיתי
    if user_is_impersonating:
        effective_is_admin = False
        effective_is_premium = False
    else:
        effective_is_admin = actual_is_admin
        effective_is_premium = actual_is_premium

    # 4. user_is_admin משמש את ה-UI (מקבל את הערך האפקטיבי)
    user_is_admin = effective_is_admin
    def _normalize_custom_theme_doc(doc: dict, *, force_active: bool = False) -> dict:
        tdoc = dict(doc or {})
        if not isinstance(tdoc.get('variables'), dict):
            tdoc = {**tdoc, 'variables': {}}
        if not isinstance(tdoc.get('syntax_css', ''), str):
            tdoc = {**tdoc, 'syntax_css': ''}
        if not isinstance(tdoc.get('syntax_colors'), dict):
            tdoc = {**tdoc, 'syntax_colors': {}}
        if force_active:
            tdoc = {**tdoc, 'is_active': True}
        return tdoc

    try:
        if user_id and user_doc:
            themes = user_doc.get('custom_themes')
            # בחירה לפי מזהה (כשנבחר custom:<id> במכשיר הנוכחי)
            if theme_type == "custom" and theme_id and isinstance(themes, list):
                for tdoc in themes:
                    if not isinstance(tdoc, dict):
                        continue
                    t_id = str(tdoc.get('id') or '').strip()
                    if t_id and t_id == str(theme_id).strip():
                        custom_theme = _normalize_custom_theme_doc(tdoc, force_active=True)
                        custom_theme_id = t_id
                        break

            # מבנה חדש (מערך) – עדיפות
            if not custom_theme and isinstance(themes, list) and themes:
                for tdoc in themes:
                    if isinstance(tdoc, dict) and tdoc.get('is_active'):
                        custom_theme = _normalize_custom_theme_doc(tdoc)
                        custom_theme_id = str(tdoc.get('id') or '').strip()
                        break

            # Fallback למבנה ישן (אובייקט בודד)
            if not custom_theme:
                ct = user_doc.get('custom_theme')
                if isinstance(ct, dict) and ct:
                    custom_theme = _normalize_custom_theme_doc(ct, force_active=(theme_type == "custom"))
                    ct_id = str(ct.get('id') or '').strip()
                    if ct_id:
                        custom_theme_id = ct_id
    except Exception:
        custom_theme = None
        custom_theme_id = ""

    # Safety: אל תאפשר theme=custom בלי custom_theme פעיל.
    try:
        ct_active = bool(custom_theme and isinstance(custom_theme, dict) and custom_theme.get('is_active'))
    except Exception:
        ct_active = False
    if theme == 'custom' and not ct_active:
        theme = 'classic'
        theme_type = "builtin"

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

    # Onboarding flags (persisted in DB under ui_prefs.onboarding.*)
    ui_prefs = (user_doc.get('ui_prefs') or {}) if isinstance(user_doc, dict) else {}
    ui_theme_pref_set = False
    try:
        ui_theme_pref_set = bool((ui_prefs.get('theme') or '').strip())
    except Exception:
        ui_theme_pref_set = False
    if not ui_theme_pref_set and theme_scope == THEME_SCOPE_DEVICE:
        try:
            ui_theme_pref_set = bool((cookie_theme or '').strip())
        except Exception:
            ui_theme_pref_set = False

    onboarding = ui_prefs.get('onboarding') if isinstance(ui_prefs, dict) else None
    if not isinstance(onboarding, dict):
        onboarding = {}

    onboarding_walkthrough_v1_seen = False
    onboarding_theme_wizard_seen = False
    try:
        onboarding_walkthrough_v1_seen = bool(onboarding.get('walkthrough_v1_seen', False))
    except Exception:
        onboarding_walkthrough_v1_seen = False
    try:
        onboarding_theme_wizard_seen = bool(onboarding.get('theme_wizard_seen', False))
    except Exception:
        onboarding_theme_wizard_seen = False

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

    # Bust static cache optionally per-request (for debugging/force-refresh)
    try:
        no_cache_param = (request.args.get('no_cache') or request.args.get('nc') or '').strip().lower()
        force_bust = no_cache_param in ('1', 'true', 'yes')
    except Exception:
        force_bust = False

    try:
        static_ver = _STATIC_VERSION + ('.' + str(int(_time.time())) if force_bust else '')
    except Exception:
        static_ver = _STATIC_VERSION

    ui_theme_custom_id = custom_theme_id if theme == "custom" else ""

    return {
        'bot_username': BOT_USERNAME_CLEAN,
        'ui_font_scale': font_scale,
        'ui_theme': theme,
        'ui_theme_scope': theme_scope,
        'ui_theme_custom_id': ui_theme_custom_id,
        'custom_theme': custom_theme,
        'shared_theme': shared_theme,
        # הרשאות (אפקטיביות - לשימוש ה-UI)
        'user_is_admin': user_is_admin,
        'user_is_premium': effective_is_premium,
        
        # --- Admin Impersonation ---
        'user_is_impersonating': user_is_impersonating,
        'actual_is_admin': actual_is_admin,
        'can_impersonate': actual_is_admin,
        # Feature flags
        'announcement_enabled': WEEKLY_TIP_ENABLED,
        'weekly_tip_enabled': WEEKLY_TIP_ENABLED,
        # גרסה סטטית לצירוף לסטטיקה (cache-busting)
        'static_version': static_ver,
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
        # Onboarding (server persisted)
        'ui_theme_pref_set': ui_theme_pref_set,
        'onboarding_walkthrough_v1_seen': onboarding_walkthrough_v1_seen,
        'onboarding_theme_wizard_seen': onboarding_theme_wizard_seen,
    }

    
# --- Theme helpers (single source of truth) ---
ALLOWED_UI_THEMES = {
    'classic',
    'ocean',
    'high-contrast',
    'dark',
    'dim',
    'rose-pine-dawn',
    'nebula',
    'custom',
}

THEME_SCOPE_GLOBAL = "global"
THEME_SCOPE_DEVICE = "device"
_THEME_SCOPE_VALUES = {THEME_SCOPE_GLOBAL, THEME_SCOPE_DEVICE}
_THEME_ID_SAFE_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,63}$")


def _normalize_theme_scope(value: Optional[str]) -> str:
    v = str(value or "").strip().lower()
    return v if v in _THEME_SCOPE_VALUES else THEME_SCOPE_GLOBAL


def _parse_theme_token(raw: Optional[str]) -> tuple[str, str, str]:
    """מפרק ערכת נושא: (type, id, theme_attr)."""
    val = str(raw or "").strip()
    if not val:
        return "builtin", "", "classic"
    low = val.lower()
    if low.startswith("shared:"):
        theme_id = low.split(":", 1)[1].strip()
        if theme_id and _THEME_ID_SAFE_RE.fullmatch(theme_id):
            return "shared", theme_id, f"shared:{theme_id}"
        return "builtin", "", "classic"
    if low.startswith("custom:"):
        theme_id = low.split(":", 1)[1].strip()
        if theme_id and _THEME_ID_SAFE_RE.fullmatch(theme_id):
            return "custom", theme_id, "custom"
        return "builtin", "", "classic"
    if low == "custom":
        return "custom", "", "custom"
    if low in ALLOWED_UI_THEMES:
        return "builtin", low, low
    return "builtin", "", "classic"


def _resolve_theme_raw_token(
    user_id: Optional[int],
    *,
    user_doc: Optional[Dict[str, Any]] = None,
    projection: Optional[Dict[str, int]] = None,
) -> Tuple[str, str, bool, Optional[Dict[str, Any]]]:
    """מחזיר theme_raw לפי cookie/DB, כולל scope ומסמך משתמש (אם נשלף)."""
    theme_scope = _normalize_theme_scope(request.cookies.get('ui_theme_scope'))
    cookie_theme = (request.cookies.get('ui_theme') or '').strip().lower()
    use_cookie_theme = bool(cookie_theme) and theme_scope == THEME_SCOPE_DEVICE
    theme_raw = cookie_theme or ''

    if user_id and not use_cookie_theme:
        if user_doc is None:
            try:
                db_ref = get_db()
                if projection is None:
                    projection = {'ui_prefs.theme': 1}
                elif 'ui_prefs.theme' not in projection:
                    projection = dict(projection)
                    projection['ui_prefs.theme'] = 1
                user_doc = db_ref.users.find_one(
                    {'user_id': int(user_id)},
                    projection,
                ) or {}
            except Exception:
                user_doc = None
        if isinstance(user_doc, dict):
            pref = ((user_doc.get('ui_prefs') or {}).get('theme') or '').strip().lower()
            if pref:
                theme_raw = pref

    if not theme_raw:
        theme_raw = 'classic'
    return theme_raw, theme_scope, use_cookie_theme, user_doc


# NOTE:
# כל הלוגיקה של Themes API (כולל validation + activate) הועברה ל-`webapp/themes_api.py`
# כדי למנוע פיצול בין `app.py` לבין Blueprint ייעודי.
#


def get_custom_theme(user_id) -> Optional[Dict[str, Any]]:
    """
    טען את הערכה המותאמת הפעילה של המשתמש.
    תומך גם במבנה הישן (custom_theme) וגם בחדש (custom_themes[]).
    """
    if not user_id:
        return None
    try:
        db_ref = get_db()
        user_doc = db_ref.users.find_one(
            {"user_id": user_id},
            {"custom_theme": 1, "custom_themes": 1},
        )
        if not user_doc:
            return None

        # מבנה חדש (מערך) – עדיפות
        themes = user_doc.get("custom_themes")
        if isinstance(themes, list) and themes:
            for theme in themes:
                if isinstance(theme, dict) and theme.get("is_active"):
                    if not isinstance(theme.get("variables"), dict):
                        theme = {**theme, "variables": {}}
                    if not isinstance(theme.get("syntax_css", ""), str):
                        theme = {**theme, "syntax_css": ""}
                    if not isinstance(theme.get("syntax_colors"), dict):
                        theme = {**theme, "syntax_colors": {}}
                    return theme

        # Fallback למבנה ישן (אובייקט בודד)
        old_theme = user_doc.get("custom_theme")
        if isinstance(old_theme, dict) and old_theme.get("is_active"):
            if not isinstance(old_theme.get("variables"), dict):
                old_theme = {**old_theme, "variables": {}}
            if not isinstance(old_theme.get("syntax_css", ""), str):
                old_theme = {**old_theme, "syntax_css": ""}
            if not isinstance(old_theme.get("syntax_colors"), dict):
                old_theme = {**old_theme, "syntax_colors": {}}
            return old_theme

        return None
    except Exception as e:
        logger.warning("get_custom_theme failed: %s", e)
        return None

def get_current_theme() -> str:
    """קובע את ערכת הנושא הנוכחית לפי cookie ו/או העדפות משתמש (DB).
    נופל חזרה ל-classic אם הערך לא חוקי.
    """
    t = 'classic'
    try:
        uid = session.get('user_id')
        theme_raw, _, _, _ = _resolve_theme_raw_token(uid)
        if theme_raw:
            t = theme_raw
    except Exception:
        pass
    _, _, theme_attr = _parse_theme_token(t)
    if theme_attr not in ALLOWED_UI_THEMES:
        theme_attr = 'classic'
    return theme_attr

@lru_cache(maxsize=32)
def _style_exists(style: str) -> bool:
    """בודק אם style של Pygments זמין בהתקנה הנוכחית."""
    if not style:
        return False
    try:
        get_style_by_name(style)
        return True
    except ClassNotFound:
        return False

@lru_cache(maxsize=32)
def get_pygments_style(theme_name: str) -> str:
    """מיפוי ערכת נושא ל־Pygments style עם נפילה חכמה ל-default.

    הערה: במצב כהה נעדיף ערכות כהות זמינות כדי למנוע טקסט כהה על רקע כהה
    במקרה שבו ערכות כמו github-dark אינן מותקנות בסביבת הריצה.
    """
    theme = (theme_name or '').strip().lower()
    preferred = 'github'
    # custom themes נחשבים כהים כברירת מחדל (רוב הערכות המיובאות הן כהות)
    if theme in ('dark', 'dim', 'nebula', 'custom'):
        preferred = 'github-dark'
    elif theme == 'high-contrast':
        preferred = 'monokai'

    for candidate in (preferred, 'monokai', 'friendly', 'default'):
        if candidate == 'default' or _style_exists(candidate):
            return candidate

    return 'default'


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
                    duration = max(0.0, float(_time.perf_counter() - _t0))
                    db = client[DATABASE_NAME]
                    try:
                        record_dependency_init("mongodb", duration)
                    except Exception:
                        pass
                    try:
                        _record_startup_metric('mongo', duration)
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
    # אינדקסים לבאנרי הכרזות (Announcements)
    try:
        ensure_announcements_indexes()
    except Exception:
        pass
    # אינדקסים למשתמשים (Themes)
    try:
        ensure_users_indexes()
    except Exception:
        pass
    # אינדקסים לערכות ציבוריות (Shared Themes)
    try:
        ensure_shared_themes_indexes()
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
    _start = _time.perf_counter()
    _did_work = False
    try:
        # השתמש ב-db גלובלי אם כבר מאותחל; אל תקרא get_db() כדי להימנע מ-deadlock בזמן אתחול
        _db = db if db is not None else None
        if _db is None:
            return
        _did_work = True
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
    finally:
        if _did_work:
            try:
                _record_startup_metric('indexes_recent', max(0.0, float(_time.perf_counter() - _start)), accumulate=True)
            except Exception:
                pass


# --- Ensure indexes for announcements once per process ---
_announcements_indexes_ready = False

def ensure_announcements_indexes() -> None:
    """יוצר אינדקסים לאוסף announcements פעם אחת בתהליך.

    אינדקסים:
    - (is_active, updated_at)
    - created_at desc
    """
    global _announcements_indexes_ready
    if _announcements_indexes_ready:
        return
    _start = _time.perf_counter()
    _did_work = False
    try:
        _db = db if db is not None else None
        if _db is None:
            return
        _did_work = True
        coll = _db.announcements
        try:
            from pymongo import ASCENDING, DESCENDING
            coll.create_index([('is_active', ASCENDING), ('updated_at', DESCENDING)], name='active_updated_idx', background=True)
            coll.create_index([('created_at', DESCENDING)], name='created_desc_idx', background=True)
        except Exception:
            pass
        _announcements_indexes_ready = True
    except Exception:
        pass
    finally:
        if _did_work:
            try:
                _record_startup_metric('indexes_announcements', max(0.0, float(_time.perf_counter() - _start)), accumulate=True)
            except Exception:
                pass


# --- Ensure indexes for users (themes) once per process ---
_users_indexes_ready = False


def ensure_users_indexes() -> None:
    """יוצר אינדקסים לאוסף users עבור Themes פעם אחת בתהליך.

    אינדקסים:
    - (user_id, custom_themes.is_active)
    - (user_id, custom_themes.id)
    """
    global _users_indexes_ready
    if _users_indexes_ready:
        return
    _start = _time.perf_counter()
    _did_work = False
    try:
        _db = db if db is not None else None
        if _db is None:
            return
        _did_work = True
        coll = _db.users
        try:
            from pymongo import ASCENDING

            coll.create_index(
                [('user_id', ASCENDING), ('custom_themes.is_active', ASCENDING)],
                name='user_custom_themes_active',
                background=True,
            )
            coll.create_index(
                [('user_id', ASCENDING), ('custom_themes.id', ASCENDING)],
                name='user_custom_themes_id',
                background=True,
            )
        except Exception:
            pass
        _users_indexes_ready = True
    except Exception:
        pass
    finally:
        if _did_work:
            try:
                _record_startup_metric('indexes_users', max(0.0, float(_time.perf_counter() - _start)), accumulate=True)
            except Exception:
                pass


# --- Ensure indexes for shared_themes once per process ---
_shared_themes_indexes_ready = False


def ensure_shared_themes_indexes() -> None:
    """יוצר אינדקסים לאוסף shared_themes פעם אחת בתהליך.

    אינדקסים:
    - (is_active)
    - (created_at DESC)
    - (created_by)
    """
    global _shared_themes_indexes_ready
    if _shared_themes_indexes_ready:
        return
    _start = _time.perf_counter()
    _did_work = False
    try:
        _db = db if db is not None else None
        if _db is None:
            return
        _did_work = True
        coll = _db.shared_themes
        try:
            from pymongo import ASCENDING, DESCENDING

            coll.create_index(
                [("is_active", ASCENDING)],
                name="shared_themes_is_active_idx",
                background=True,
            )
            coll.create_index(
                [("created_at", DESCENDING)],
                name="shared_themes_created_at_desc_idx",
                background=True,
            )
            coll.create_index(
                [("created_by", ASCENDING)],
                name="shared_themes_created_by_idx",
                background=True,
            )
        except Exception:
            pass
        _shared_themes_indexes_ready = True
    except Exception:
        pass
    finally:
        if _did_work:
            try:
                _record_startup_metric(
                    "indexes_shared_themes",
                    max(0.0, float(_time.perf_counter() - _start)),
                    accumulate=True,
                )
            except Exception:
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


def _get_theme_etag_key(user_id: Optional[int]) -> str:
    """מפתח קצר שמייצג את ערכת הנושא הנוכחית (כולל שינויי גרסה)."""
    theme_raw = 'classic'
    user_doc = None
    try:
        theme_raw, _, _, user_doc = _resolve_theme_raw_token(
            user_id,
            projection={'ui_prefs.theme': 1, 'custom_themes': 1, 'custom_theme': 1},
        )
    except Exception:
        theme_raw = 'classic'
        user_doc = None

    theme_type, theme_id, theme_attr = _parse_theme_token(theme_raw)
    base = theme_attr if theme_attr in ALLOWED_UI_THEMES else 'classic'
    if theme_type == 'shared' and theme_id:
        base = f"shared:{theme_id}"
    elif theme_type == 'custom' and theme_id:
        base = f"custom:{theme_id}"
    elif theme_type == 'custom':
        base = 'custom'

    version_parts = []
    if theme_type == 'custom':
        updated_at = None
        theme_ident = ''
        if user_id and user_doc is None:
            try:
                db_ref = get_db()
                user_doc = db_ref.users.find_one(
                    {'user_id': int(user_id)},
                    {'custom_themes': 1, 'custom_theme': 1},
                ) or {}
            except Exception:
                user_doc = None
        found_custom = False
        if isinstance(user_doc, dict):
            themes = user_doc.get('custom_themes')
            if theme_id and isinstance(themes, list):
                for tdoc in themes:
                    if isinstance(tdoc, dict) and str(tdoc.get('id') or '').strip() == theme_id:
                        updated_at = tdoc.get('updated_at')
                        found_custom = True
                        break
            if updated_at is None and isinstance(themes, list):
                for tdoc in themes:
                    if isinstance(tdoc, dict) and tdoc.get('is_active'):
                        updated_at = tdoc.get('updated_at')
                        if not theme_id:
                            theme_ident = str(tdoc.get('id') or '').strip()
                        found_custom = True
                        break
            if updated_at is None:
                ct = user_doc.get('custom_theme')
                if isinstance(ct, dict) and (ct.get('is_active') or theme_id):
                    updated_at = ct.get('updated_at')
                    if not theme_id:
                        theme_ident = str(ct.get('id') or '').strip()
                    found_custom = True
        if not found_custom:
            base = 'classic'
        if theme_ident:
            version_parts.append(theme_ident)
        if updated_at:
            try:
                updated_str = _safe_dt_from_doc(updated_at).isoformat()
            except Exception:
                updated_str = str(updated_at)
            if updated_str:
                version_parts.append(updated_str)
    elif theme_type == 'shared' and theme_id:
        try:
            db_ref = get_db()
            doc = db_ref.shared_themes.find_one(
                {'_id': theme_id, 'is_active': True},
                {'updated_at': 1},
            ) or {}
            if not doc:
                base = 'classic'
            else:
                updated_at = doc.get('updated_at')
                if updated_at:
                    updated_str = _safe_dt_from_doc(updated_at).isoformat()
                    if updated_str:
                        version_parts.append(updated_str)
        except Exception:
            base = 'classic'

    if version_parts:
        return f"{base}|{'|'.join(version_parts)}"
    return base


def _compute_file_etag(doc: Dict[str, Any], *, variant: str = '') -> str:
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
    raw_code = (doc.get('code') or doc.get('content') or '')
    file_name = (doc.get('file_name') or '')
    version = str(doc.get('version') or '')
    # Hash a compact JSON string of identifying fields + content digest
    try:
        payload_data = {
            'u': updated_str,
            'n': file_name,
            'v': version,
            'sha': hashlib.sha256(raw_code.encode('utf-8')).hexdigest(),
        }
        if variant:
            payload_data['var'] = variant
        payload = json.dumps(payload_data, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
        tag = hashlib.sha256(payload.encode('utf-8')).hexdigest()[:16]
        return f'W/"{tag}"'
    except Exception:
        # Fallback: time-based weak tag
        return f'W/"{int(time.time())}"'


def _get_user_any_file_by_id(db_ref, user_id: int, file_id: str) -> Tuple[Optional[Dict[str, Any]], str]:
    """שליפת קובץ לפי ObjectId ממסמך רגיל או large_files, עם וידוא בעלות משתמש.

    מחזיר (doc, kind) כאשר kind הוא "regular" או "large" או "" אם לא נמצא.
    """
    if not file_id:
        return None, ""
    try:
        obj_id = ObjectId(file_id)
    except (InvalidId, TypeError):
        return None, ""
    try:
        doc = db_ref.code_snippets.find_one({'_id': obj_id, 'user_id': user_id})
        if isinstance(doc, dict):
            return doc, "regular"
    except Exception:
        pass
    try:
        large_coll = getattr(db_ref, 'large_files', None)
        if large_coll is None:
            return None, ""
        doc = large_coll.find_one({
            '_id': obj_id,
            'user_id': user_id,
            'is_active': {'$ne': False},
        })
        if isinstance(doc, dict):
            return doc, "large"
    except Exception:
        pass
    return None, ""


_SOURCE_URL_SCHEMES = {'http', 'https'}


def _normalize_source_url_value(raw: str) -> Tuple[Optional[str], Optional[str]]:
    """מאמת ומנרמל קישור מקור של משתמש (http/https בלבד)."""
    value = (raw or '').strip()
    if not value:
        return None, None

    candidate = value
    if candidate.startswith('//'):
        candidate = f'https:{candidate}'
    elif '://' not in candidate:
        candidate = f'https://{candidate}'

    if any(ch.isspace() for ch in candidate):
        return None, 'קישור למקור לא יכול להכיל רווחים'

    try:
        parsed = urlparse(candidate)
    except Exception:
        return None, 'קישור למקור אינו תקין'

    scheme = (parsed.scheme or '').lower()
    if scheme not in _SOURCE_URL_SCHEMES:
        return None, 'ניתן להזין רק קישורי http או https'

    netloc = (parsed.netloc or '').strip()
    if not netloc or ' ' in netloc:
        return None, 'שם המארח בקישור אינו תקין'

    cleaned = urlunparse((
        scheme,
        netloc,
        parsed.path or '',
        parsed.params or '',
        parsed.query or '',
        parsed.fragment or '',
    ))
    return cleaned, None


def _extract_source_hostname(url: str) -> str:
    """מחזיר שם מארח לתצוגה בלחצן הקישור."""
    if not url:
        return ''
    try:
        parsed = urlparse(url)
    except Exception:
        return ''
    host = (parsed.netloc or '').strip()
    if not host:
        return ''
    host = host.split('@')[-1]
    if ':' in host:
        host = host.split(':', 1)[0]
    return host


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
    _start = _time.perf_counter()
    _did_work = False
    try:
        # השתמש ב-db גלובלי אם כבר מאותחל; אל תקרא get_db() כדי להימנע מ-deadlock בזמן אתחול
        _db = db if db is not None else None
        if _db is None:
            return
        _did_work = True
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
            # אינדקסים לשדות מטא חדשים (מסייעים לפילטרים/מיונים עתידיים כמו min_size/max_size)
            try:
                coll.create_index([('user_id', ASCENDING), ('file_size', ASCENDING)], name='user_file_size', background=True)
            except Exception:
                pass
            try:
                coll.create_index([('user_id', ASCENDING), ('lines_count', ASCENDING)], name='user_lines_count', background=True)
            except Exception:
                pass
            # אינדקסים לתמיכה ב-"גרסה אחרונה לכל file_name" (פייפליינים עם sort+group)
            try:
                coll.create_index(
                    [('user_id', ASCENDING), ('file_name', ASCENDING), ('version', DESCENDING)],
                    name='user_file_version_desc',
                    background=True,
                )
            except Exception:
                pass
            # אינדקסים למיונים נפוצים במסכי רשימות
            try:
                coll.create_index([('user_id', ASCENDING), ('updated_at', DESCENDING)], name='user_updated_at', background=True)
            except Exception:
                pass
            try:
                coll.create_index(
                    [('user_id', ASCENDING), ('is_favorite', ASCENDING), ('favorited_at', DESCENDING)],
                    name='user_favorite_favorited_at',
                    background=True,
                )
            except Exception:
                pass
            try:
                coll.create_index(
                    [('user_id', ASCENDING), ('is_pinned', ASCENDING), ('pin_order', ASCENDING), ('pinned_at', DESCENDING)],
                    name='user_pinned_pin_order',
                    background=True,
                )
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
    finally:
        if _did_work:
            try:
                _record_startup_metric('indexes_code', max(0.0, float(_time.perf_counter() - _start)), accumulate=True)
            except Exception:
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


@lru_cache(maxsize=1)
def _load_user_guide_markdown() -> Optional[Tuple[str, datetime]]:
    """טוען את קובץ המדריך המקומי ומחזיר את התוכן והזמן האחרון שבו עודכן."""
    try:
        content = USER_GUIDE_PATH.read_text(encoding='utf-8')
    except FileNotFoundError:
        try:
            logger.warning("USER_GUIDE markdown file missing", extra={'path': str(USER_GUIDE_PATH)})
        except Exception:
            pass
        return None
    except Exception:
        try:
            logger.exception("Failed reading USER_GUIDE markdown", extra={'path': str(USER_GUIDE_PATH)})
        except Exception:
            pass
        return None
    try:
        updated_at = datetime.fromtimestamp(USER_GUIDE_PATH.stat().st_mtime, timezone.utc)
    except Exception:
        updated_at = datetime.now(timezone.utc)
    return content, updated_at


def _get_builtin_share_doc(share_id: str) -> Optional[Dict[str, Any]]:
    """בניית מסמך שיתוף מובנה מהמדריך המקומי (למזהי welcome)."""
    if not share_id or share_id not in WELCOME_GUIDE_SHARE_ALIASES:
        return None
    loaded = _load_user_guide_markdown()
    if not loaded:
        return None
    code, updated_at = loaded
    return {
        'share_id': share_id,
        'file_name': WELCOME_GUIDE_FILE_NAME,
        'code': code,
        'language': 'markdown',
        'description': WELCOME_GUIDE_DESCRIPTION,
        'created_at': updated_at,
        'updated_at': updated_at,
        'views': 0,
        'is_builtin': True,
    }


def get_internal_share(share_id: str, *, include_code: bool = True) -> Optional[Dict[str, Any]]:
    """שליפת שיתוף פנימי מה-DB (internal_shares) עם בדיקת תוקף.

    - include_code=False: מיועד לתצוגה מקדימה (preview) כדי לא למשוך תוכן מלא.
    - include_code=True: מיועד להורדה/שמירה, כשבאמת חייבים את התוכן המלא.
    """
    builtin_doc = _get_builtin_share_doc(share_id)
    if builtin_doc:
        if not include_code:
            # תצוגה מקדימה: אל תדחוף קוד מלא לזיכרון אם לא צריך.
            try:
                code = str(builtin_doc.get('code') or '')
                builtin_doc = dict(builtin_doc)
                builtin_doc['snippet_preview'] = code[:2000]
                builtin_doc['file_size'] = int(len(code.encode('utf-8', errors='ignore'))) if code else 0
                builtin_doc['lines_count'] = int(len(code.splitlines())) if code else 0
                builtin_doc.pop('code', None)
                builtin_doc['mode'] = builtin_doc.get('mode') or 'preview'
            except Exception:
                pass
        return builtin_doc
    try:
        db = get_db()
        coll = db.internal_shares
        projection = None
        if not include_code:
            # Preview: אל תחזיר את שדה code אם הוא קיים (יכול להיות כבד מאוד).
            projection = {"code": 0}
        try:
            doc = coll.find_one({"share_id": share_id}, projection=projection)
        except TypeError:
            # תאימות לסטאבים/מימושים ללא projection=
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
    try:
        is_async = asyncio.iscoroutinefunction(f)  # type: ignore[attr-defined]
    except Exception:
        is_async = False

    if is_async:
        @wraps(f)
        async def decorated_function(*args, **kwargs):
            if 'user_id' not in session:
                try:
                    wants_json = (
                        (request.path or '').startswith('/api/') or
                        ('application/json' in (request.headers.get('Accept') or ''))
                    )
                except Exception:
                    wants_json = False
                if wants_json:
                    return jsonify({'error': 'נדרש להתחבר'}), 401
                next_url = request.full_path if request.query_string else request.path
                return redirect(url_for('login', next=next_url))
            return await f(*args, **kwargs)
        return decorated_function

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


def get_current_user_id() -> Optional[int]:
    """פונקציה תואמת-מדריך להחזרת מזהה משתמש נוכחי (או None אם לא מחובר)."""
    try:
        uid = session.get('user_id')
        if uid is None:
            return None
        return int(uid)
    except Exception:
        return None


# --- Compare API - API להשוואת קבצים (לפי המדריך) ---
compare_bp = Blueprint('compare', __name__, url_prefix='/api/compare')


@compare_bp.route('/versions/<file_id>', methods=['GET'])
def compare_versions(file_id: str):
    """
    השוואה בין גרסאות של קובץ.

    Query params:
        - left: מספר גרסה שמאלית (ברירת מחדל: גרסה אחרונה - 1)
        - right: מספר גרסה ימנית (ברירת מחדל: גרסה אחרונה)

    Returns:
        JSON עם תוצאת ההשוואה
    """
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 401

    from database import db as _db
    db = _db

    # קבלת הקובץ לפי ID
    file_doc = db.get_file_by_id(file_id)
    if not file_doc:
        return jsonify({"error": "File not found"}), 404

    if file_doc.get("user_id") != user_id:
        return jsonify({"error": "Forbidden"}), 403

    file_name = file_doc.get("file_name")
    current_version = file_doc.get("version", 1)

    # קבלת פרמטרים
    version_left = request.args.get('left', type=int, default=max(1, current_version - 1))
    version_right = request.args.get('right', type=int, default=current_version)

    # חישוב ההשוואה
    diff_service = get_diff_service(db)
    result = diff_service.compare_versions(user_id, file_name, version_left, version_right)

    if not result:
        return jsonify({"error": "Could not compare versions"}), 400

    return jsonify(result.to_dict())


@compare_bp.route('/files', methods=['POST'])
def compare_files():
    """
    השוואה בין שני קבצים שונים.

    Body (JSON):
        - left_file_id: מזהה קובץ שמאלי
        - right_file_id: מזהה קובץ ימני

    Returns:
        JSON עם תוצאת ההשוואה
    """
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json() or {}
    left_id = data.get('left_file_id')
    right_id = data.get('right_file_id')

    if not left_id or not right_id:
        return jsonify({"error": "Missing file IDs"}), 400

    from database import db as _db
    db = _db

    diff_service = get_diff_service(db)
    result = diff_service.compare_files(user_id, left_id, right_id)

    if not result:
        return jsonify({"error": "Could not compare files"}), 400

    return jsonify(result.to_dict())


@compare_bp.route('/diff', methods=['POST'])
def compare_raw():
    """
    השוואה בין שני טקסטים גולמיים.

    Body (JSON):
        - left_content: תוכן שמאלי
        - right_content: תוכן ימני

    Returns:
        JSON עם תוצאת ההשוואה
    """
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json() or {}
    left_content = data.get('left_content', '')
    right_content = data.get('right_content', '')

    diff_service = get_diff_service()
    result = diff_service.compute_diff(left_content, right_content)

    return jsonify(result.to_dict())


app.register_blueprint(compare_bp)

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
            'has_seen_welcome_modal': bool(user.get('has_seen_welcome_modal', False)),
            'is_admin': is_admin(user_id),
            'is_premium': is_premium(user_id),
        }
        session.permanent = True
    except Exception:
        # אל תכשיל בקשות בגלל כשל חיבור/פרסר
        pass


# --- Queue delay (request queueing) instrumentation ---
_QUEUE_DELAY_HEADERS = ("X-Queue-Start", "X-Request-Start")
_QUEUE_DELAY_EPOCH_RE = re.compile(r"(-?\d+(?:\.\d+)?)")


def _queue_delay_warn_threshold_ms() -> int:
    try:
        return max(0, int(float(os.getenv("QUEUE_DELAY_WARN_MS", "500") or 500)))
    except Exception:
        return 500


def _parse_request_start_to_epoch_seconds(raw: str | None) -> float | None:
    """Parse ingress timestamp headers into epoch seconds (best-effort)."""
    try:
        text = str(raw or "").strip()
    except Exception:
        return None
    if not text:
        return None
    if text.lower().startswith("t="):
        text = text.split("=", 1)[1].strip()
    m = _QUEUE_DELAY_EPOCH_RE.search(text)
    if not m:
        return None
    token = m.group(1)
    if not token:
        return None
    if "." in token:
        try:
            value = float(token)
        except Exception:
            return None
        return value if value > 0 else None
    try:
        value_int = int(token)
    except Exception:
        return None
    if value_int <= 0:
        return None
    digits = len(token.lstrip("+-"))
    if digits <= 10:
        return float(value_int)
    if digits <= 13:
        return float(value_int) / 1_000.0
    if digits <= 16:
        return float(value_int) / 1_000_000.0
    return float(value_int) / 1_000_000_000.0


def _compute_queue_delay_ms(headers, *, now_epoch_seconds: float) -> tuple[int, str | None]:
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


@app.before_request
def _correlation_bind():
    """Bind a short request_id to structlog context and store for response header."""
    try:
        # Queue delay must be captured as early as possible (before business logic).
        try:
            now_epoch = float(time.time())
            q_ms, q_src = _compute_queue_delay_ms(request.headers, now_epoch_seconds=now_epoch)
            setattr(g, "_queue_delay_ms", int(q_ms))
            setattr(g, "_queue_delay_source", q_src)
            _bind_queue_delay_context(int(q_ms), q_src)
        except Exception:
            setattr(g, "_queue_delay_ms", 0)
            setattr(g, "_queue_delay_source", None)

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
        note_request_started()
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
            path_label = getattr(request, "path", "")
            method_label = getattr(request, "method", "GET")
            handler_label = endpoint or path_label
            cache_flag = getattr(g, "_otel_cache_hit", None)
            record_request_outcome(
                status,
                dur,
                source="webapp",
                handler=handler_label,
                method=method_label,
                path=path_label,
                cache_hit=cache_flag,
            )
            # חשוב: /triage משתמש ב-alert_manager. בפועל ייתכן שהמודול metrics (או ה-bridge שלו)
            # לא מזין את alert_manager בסביבה מסוימת, ולכן כאן אנחנו מדווחים תמיד (best-effort).
            # כדי למנוע רעש, אנחנו עדיין מסננים נתיבים סטטיים/בריאות כאשר הבקשה "ok".
            try:
                from alert_manager import note_request as _am_note_request  # type: ignore

                # דילוג על רעש (סטטי/בריאות) רק כשהבקשה "ok". שגיאות עדיין נרשמות.
                try:
                    p = str(path_label or "")
                except Exception:
                    p = ""
                is_static = p.startswith("/static/")
                silent_paths = {"/metrics", "/health", "/healthz", "/favicon.ico"}
                is_silent_ok = (p in silent_paths) and int(status) < 400
                if (not is_static) or int(status) >= 400:
                    if not is_silent_ok:
                        ctx: Dict[str, Any] = {
                            "path": p,
                            "method": str(method_label or ""),
                        }
                        try:
                            if endpoint:
                                ctx["endpoint"] = str(endpoint)
                        except Exception:
                            pass
                        try:
                            rid = getattr(request, "_req_id", None)
                            if rid:
                                ctx["request_id"] = str(rid)
                        except Exception:
                            pass
                        try:
                            q_ms = int(getattr(g, "_queue_delay_ms", 0) or 0)
                        except Exception:
                            q_ms = 0
                        if q_ms > 0:
                            ctx["queue_delay_ms"] = int(q_ms)
                        ctx = {k: v for k, v in (ctx or {}).items() if v not in (None, "", {})}
                        _am_note_request(int(status), float(dur), source="internal", context=(ctx or None))
            except Exception:
                pass
            try:
                method = getattr(request, "method", "GET")
                record_http_request(method, endpoint, status, dur, path=path_label)
            except Exception:
                pass
            # Queue delay instrumentation (best-effort)
            try:
                q_ms = int(getattr(g, "_queue_delay_ms", 0) or 0)
            except Exception:
                q_ms = 0
            try:
                q_src = getattr(g, "_queue_delay_source", None)
            except Exception:
                q_src = None
            try:
                record_request_queue_delay(method_label, endpoint, float(q_ms) / 1000.0)
            except Exception:
                pass
            try:
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
                    rid = getattr(request, "_req_id", "") or ""
                    access_fields: Dict[str, Any] = {
                        "request_id": str(rid),
                        "method": method_label,
                        "path": path_label,
                        "handler": handler_label,
                        "status_code": int(status),
                        "duration_ms": int(float(dur) * 1000),
                        "queue_delay": int(q_ms),
                    }
                    if q_src:
                        access_fields["queue_delay_source"] = str(q_src)
                    emit_event("access_logs", severity="info", **access_fields)
            except Exception:
                pass
            try:
                threshold = _queue_delay_warn_threshold_ms()
                if threshold > 0 and int(q_ms) >= int(threshold):
                    warn_fields: Dict[str, Any] = {
                        "request_id": str(getattr(request, "_req_id", "") or ""),
                        "queue_delay": int(q_ms),
                        "threshold_ms": int(threshold),
                        "method": method_label,
                        "path": path_label,
                        "handler": handler_label,
                    }
                    if q_src:
                        warn_fields["queue_delay_source"] = str(q_src)
                    emit_event("queue_delay_high", severity="warning", **warn_fields)
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
def _impersonation_action_event(resp):
    try:
        method = str(getattr(request, "method", "") or "").upper()
        if method in ("GET", "HEAD", "OPTIONS"):
            return resp
        if not is_impersonating_safe():
            return resp
        endpoint = getattr(request, "endpoint", None) or getattr(request, "path", "") or "unknown"
        target_id = None
        try:
            view_args = getattr(request, "view_args", None) or {}
            for key in ("file_id", "id", "snippet_id", "collection_id", "share_id"):
                if key in view_args:
                    target_id = view_args.get(key)
                    break
        except Exception:
            target_id = None
        emit_event(
            "action_performed_while_impersonating",
            severity="info",
            user_id=session.get("user_id"),
            action=endpoint,
            target_id=target_id,
        )
    except Exception:
        pass
    return resp


@app.teardown_request
def _metrics_teardown(_exc):
    try:
        note_request_finished()
    except Exception:
        pass


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
                    "worker-src 'self' blob:; "
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


@app.after_request
def _disable_html_cache(resp):
    """Force browsers to revalidate HTML responses unless ETag is present."""
    try:
        content_type = resp.headers.get('Content-Type', '')
        if isinstance(content_type, str) and 'text/html' in content_type:
            # Respect explicit cache directives set by endpoints.
            if 'Cache-Control' in resp.headers:
                return resp
            # Allow ETag-based revalidation for pages that set validators.
            if 'ETag' in resp.headers:
                resp.headers['Cache-Control'] = 'private, max-age=0, must-revalidate'
                return resp
            resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
            resp.headers['Pragma'] = 'no-cache'
            resp.headers['Expires'] = '0'
    except Exception:
        # Never fail the response if header manipulation crashes
        pass
    return resp


# --- Service Worker: served at root scope (/sw.js) ---
@app.route('/sw.js')
def service_worker_js():
    try:
        from pathlib import Path
        p = (Path(__file__).parent / 'static' / 'sw.js')
        if not p.is_file():
            return Response('/* no service worker */', mimetype='application/javascript')
        content = p.read_text(encoding='utf-8')
        resp = Response(content)
        try:
            resp.headers['Content-Type'] = 'application/javascript; charset=utf-8'
            # Service Worker MUST update quickly; avoid any caching.
            resp.headers['Cache-Control'] = 'no-store, max-age=0, must-revalidate'
            resp.headers['Pragma'] = 'no-cache'
            resp.headers['Expires'] = '0'
            # Ensure root scope is allowed even if served from /sw.js
            resp.headers['Service-Worker-Allowed'] = '/'
        except Exception:
            pass
        return resp
    except Exception:
        return Response('// sw error', mimetype='application/javascript')

# === Alertmanager Webhook endpoint (optional integration) ===
# מאפשר להפנות התראות מ-Alertmanager ישירות לבוט/טלגרם דרך alert_forwarder
@app.route('/alertmanager/webhook', methods=['POST'])
def alertmanager_webhook():
    try:
        # --- DEBUG START ---
        # חשוב: לא מדפיסים סודות ללוגים. אנחנו משחירים ערכים רגישים.
        import os
        import secrets as _secrets
        import logging
        logger = logging.getLogger(__name__)

        def _mask_secret(value: object) -> str:
            try:
                s = ('' if value is None else str(value)).strip()
                if not s:
                    return '<empty>'
                if len(s) <= 4:
                    return '*' * len(s)
                return f"{s[:2]}{'*' * (len(s) - 4)}{s[-2:]}"
            except Exception:
                return '<unavailable>'

        # שליפת נתונים לדיבוג
        # (ב-Flask אין request.query; משתמשים ב-request.args)
        req_secret = (
            request.args.get("secret")
            or request.args.get("token")
            or request.headers.get("X-Alertmanager-Token")
        )
        env_secret = os.getenv("ALERTMANAGER_WEBHOOK_SECRET")
        client_ip = (
            (request.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
            or (request.remote_addr or "")
        )

        logger.warning(f"🚨 DEBUG WEBHOOK: Client IP={client_ip}")
        logger.warning(f"🚨 DEBUG WEBHOOK: Received Secret={_mask_secret(req_secret)}")
        logger.warning(f"🚨 DEBUG WEBHOOK: Expected Secret={_mask_secret(env_secret)}")
        logger.warning(
            f"🚨 DEBUG WEBHOOK: IP allowlist configured={bool(os.getenv('ALERTMANAGER_IP_ALLOWLIST'))}"
        )
        # --- DEBUG END ---

        # --- Basic authentication/guard ---
        env_secret = (os.getenv('ALERTMANAGER_WEBHOOK_SECRET') or '').strip()

        def secrets_match(req: object, env: object) -> bool:
            """Compare webhook secrets in constant-time (best effort)."""
            return _secrets.compare_digest(
                ('' if req is None else str(req)).strip(),
                ('' if env is None else str(env)).strip(),
            )

        # --- תחילת התיקון ---
        # ביטלנו את בדיקת ה-IP כי היא חוסמת סתם. סומכים רק על הסיסמה.
        # allow_ips = {... from ALERTMANAGER_IP_ALLOWLIST ...}
        # if allow_ips and not is_ip_allowed(...):
        #     return 403
        # --- סוף התיקון ---

        # מוודאים שרק בדיקת הסיסמה נשארת (אם מוגדרת סיסמה ב-ENV)
        if env_secret and not secrets_match(req_secret, env_secret):
            logger.warning("🚨 DEBUG WEBHOOK: Wrong secret for /alertmanager/webhook")
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
    """
    דקורטור לבדיקת הרשאות אדמין.
    
    - חוסם גישה במצב Impersonation (למעט Fail-Safe)
    - מאפשר עקיפה דרך ?force_admin=1
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        
        # בדיקה אם המשתמש הוא אדמין (הסטטוס האמיתי)
        try:
            uid = int(session['user_id'])
        except Exception:
            abort(403)
            
        if not is_admin(uid):
            abort(403)
        
        # 🆘 Fail-Safe: עקיפה דרך URL
        force_admin = request.args.get('force_admin') == '1'
        
        # במצב Impersonation - חסום גישה לעמודי אדמין (אלא אם Fail-Safe)
        if is_impersonating_safe() and not force_admin:
            flash('מצב צפייה כמשתמש פעיל - אין גישה לעמודי אדמין. לעקיפה: הוסף ?force_admin=1', 'warning')
            return redirect(url_for('dashboard'))
        
        return f(*args, **kwargs)
    return decorated_function

def premium_or_admin_required(f):
    """דקורטור לבדיקת הרשאות Premium או אדמין"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))

        try:
            uid = int(session['user_id'])
        except Exception:
            abort(403)

        if not (is_admin(uid) or is_premium(uid)):
            abort(403)

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


# --- Admin Impersonation Functions ---

def is_impersonating_raw() -> bool:
    """
    בודק אם הדגל הגולמי של Impersonation פעיל בסשן.
    
    ⚠️ לא לשימוש ישיר ב-UI! השתמש ב-is_impersonating_safe() שכולל Fail-Safe.
    """
    return bool(session.get(IMPERSONATION_SESSION_KEY, False))


def is_impersonating_safe() -> bool:
    """
    בודק אם מצב Impersonation פעיל, עם מנגנון מילוט (Fail-Safe).
    
    - אם ?force_admin=1 ב-URL → תמיד מחזיר False (עקיפה לשעת חירום)
    - אם הדגל פעיל אבל המשתמש לא אדמין באמת → מחזיר False (הגנה)
    - אחרת → מחזיר את מצב הדגל
    """
    # 🆘 Fail-Safe: עקיפה דרך URL לשעת חירום
    if request.args.get('force_admin') == '1':
        return False
    
    # בדיקה שהדגל פעיל
    if not is_impersonating_raw():
        return False
    
    # הגנה: וידוא שהמשתמש אכן אדמין (מונע מניפולציה בסשן)
    user_id = session.get('user_id')
    if user_id is None:
        return False
    
    try:
        if not is_admin(int(user_id)):
            # משתמש לא-אדמין עם דגל Impersonation? משהו לא בסדר - נקה
            session.pop(IMPERSONATION_SESSION_KEY, None)
            return False
    except Exception:
        return False
    
    return True


def can_impersonate() -> bool:
    """בודק אם המשתמש הנוכחי יכול להפעיל מצב Impersonation (רק אדמינים)."""
    user_id = session.get('user_id')
    if user_id is None:
        return False
    
    try:
        # בודק את הסטטוס האמיתי (לא האפקטיבי!)
        return is_admin(int(user_id))
    except Exception:
        return False


def start_impersonation() -> bool:
    """
    מפעיל מצב Impersonation. מחזיר True אם הצליח.
    
    ⚠️ חשוב: לא נוגעים ב-session['user_data']!
    כל הלוגיקה מחושבת בזמן אמת ב-Context Processor.
    """
    if not can_impersonate():
        return False
    
    user_id = session.get('user_id')
    
    # שומרים רק את הדגל - לא משנים user_data!
    session[IMPERSONATION_SESSION_KEY] = True
    session[IMPERSONATION_ORIGINAL_ADMIN_KEY] = user_id
    session['impersonation_started_at'] = time.time()
    
    return True


def stop_impersonation() -> bool:
    """
    מפסיק מצב Impersonation ומחזיר לסטטוס רגיל.
    
    ⚠️ חשוב: לא נוגעים ב-session['user_data']!
    """
    if not is_impersonating_raw():
        return False
    
    # ניקוי דגלי Impersonation בלבד
    session.pop(IMPERSONATION_SESSION_KEY, None)
    session.pop(IMPERSONATION_ORIGINAL_ADMIN_KEY, None)
    session.pop('impersonation_started_at', None)
    
    return True


def _parse_iso_arg(name: str) -> Optional[datetime]:
    raw = request.args.get(name)
    if not raw:
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        if text.endswith('Z'):
            text = text[:-1] + '+00:00'
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        raise ValueError(f"invalid_{name}")


def _parse_duration_to_seconds(raw: Optional[str], default_seconds: int, *, allow_none: bool = False) -> int:
    if not raw:
        return default_seconds
    text = str(raw).strip().lower()
    if not text:
        return default_seconds
    try:
        if text.endswith('ms'):
            value = float(text[:-2])
            seconds = max(0.001, value / 1000.0)
        elif text.endswith('s'):
            seconds = float(text[:-1])
        elif text.endswith('m'):
            seconds = float(text[:-1]) * 60.0
        elif text.endswith('h'):
            seconds = float(text[:-1]) * 3600.0
        elif text.endswith('d'):
            seconds = float(text[:-1]) * 86400.0
        else:
            seconds = float(text)
    except Exception:
        if allow_none:
            return default_seconds
        raise ValueError("invalid_duration")
    return max(1, int(seconds))


def _resolve_time_window(default_hours: int = 24) -> Tuple[Optional[datetime], Optional[datetime]]:
    start_dt = _parse_iso_arg('start_time')
    end_dt = _parse_iso_arg('end_time')
    timerange = str(request.args.get('timerange') or request.args.get('range') or '').strip().lower()

    if start_dt and end_dt:
        if end_dt < start_dt:
            raise ValueError("invalid_timerange")
        return start_dt, end_dt

    now = datetime.now(timezone.utc)
    if timerange:
        if timerange == 'custom':
            if not (start_dt and end_dt):
                raise ValueError("custom_range_requires_start_and_end")
            if end_dt < start_dt:
                raise ValueError("invalid_timerange")
            return start_dt, end_dt
        duration_seconds = _parse_duration_to_seconds(timerange, default_hours * 3600)
        return now - timedelta(seconds=duration_seconds), now

    duration_seconds = default_hours * 3600
    return now - timedelta(seconds=duration_seconds), now


def _parse_pagination() -> Tuple[int, int]:
    try:
        page = max(1, int(request.args.get('page', 1)))
    except Exception:
        page = 1
    try:
        per_page = int(request.args.get('per_page', 50))
    except Exception:
        per_page = 50
    per_page = max(1, min(200, per_page))
    return page, per_page


def _log_webapp_user_activity() -> bool:
    """Best-effort logging של שימוש ב-WebApp לצורכי סטטיסטיקות. מחזיר True אם נרשמה פעילות."""
    try:
        user_id = session.get('user_id')
    except Exception:
        user_id = None
    if not user_id:
        return False
    username = None
    try:
        user_data = session.get('user_data') or {}
        if isinstance(user_data, dict):
            username = user_data.get('username')
    except Exception:
        username = None

    try:
        logged = log_user_event(int(user_id), username=username)
        return bool(logged)
    except Exception:
        return False


@app.route('/admin/impersonate/start', methods=['POST'])
@login_required
def admin_impersonate_start():
    """הפעלת מצב צפייה כמשתמש רגיל (Impersonation)."""
    if not can_impersonate():
        return jsonify({'ok': False, 'error': 'לא מורשה'}), 403
    
    if start_impersonation():
        emit_event(
            'admin_impersonation_started',
            severity='info',
            user_id=session.get('user_id'),
        )
        try:
            impersonation_sessions_total.labels(admin_id=str(session.get('user_id'))).inc()
        except Exception:
            pass
        # 🔄 Cache-Control: מונע בעיות Cache בדפדפן
        resp = make_response(jsonify({'ok': True, 'message': 'מצב צפייה כמשתמש הופעל'}))
        resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        resp.headers['Pragma'] = 'no-cache'
        resp.headers['Expires'] = '0'
        return resp
    
    return jsonify({'ok': False, 'error': 'לא ניתן להפעיל מצב צפייה'}), 400


@app.route('/admin/impersonate/stop', methods=['POST'])
@login_required
def admin_impersonate_stop():
    """כיבוי מצב צפייה כמשתמש רגיל."""
    started_at = session.get('impersonation_started_at')
    if stop_impersonation():
        elapsed_time = None
        try:
            if started_at:
                elapsed_time = max(0.0, float(time.time() - float(started_at)))
        except Exception:
            elapsed_time = None
        emit_event(
            'admin_impersonation_stopped',
            severity='info',
            user_id=session.get('user_id'),
            duration_seconds=elapsed_time,
        )
        try:
            if elapsed_time is not None:
                impersonation_duration_seconds.observe(float(elapsed_time))
        except Exception:
            pass
        # 🔄 Cache-Control
        resp = make_response(jsonify({'ok': True, 'message': 'מצב צפייה כמשתמש הופסק'}))
        resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        resp.headers['Pragma'] = 'no-cache'
        resp.headers['Expires'] = '0'
        return resp
    
    return jsonify({'ok': False, 'error': 'לא במצב צפייה'}), 400


@app.route('/admin/impersonate/status', methods=['GET'])
@login_required
def admin_impersonate_status():
    """מחזיר סטטוס מצב ה-Impersonation הנוכחי."""
    actual_admin = can_impersonate()
    currently_impersonating = is_impersonating_safe()
    
    return jsonify({
        'ok': True,
        'is_impersonating': currently_impersonating,
        'can_impersonate': actual_admin,
        'actual_is_admin': actual_admin,
        # effective = actual אם לא מתחזים, אחרת False
        'effective_admin': False if currently_impersonating else actual_admin,
    })


@app.route('/db-health')
def db_health_page():
    """דף דשבורד בריאות מסד הנתונים (Admin בלבד)."""
    try:
        user_id = session.get('user_id')
    except Exception:
        user_id = None

    # דרישת המוצר: ללא הרשאה מתאימה => 403 (גם אם לא מחובר)
    try:
        uid_int = int(user_id) if user_id is not None else None
    except Exception:
        uid_int = None
    if not uid_int or not is_admin(uid_int):
        abort(403)

    token = str(os.getenv("DB_HEALTH_TOKEN", "") or "").strip()
    if not token:
        abort(403)

    return render_template('db_health.html', db_health_token=token)


@app.route('/admin/db-health')
def admin_db_health_page():
    """Alias תאימות לנתיב אדמין: מפנה ל-/db-health."""
    # שמור את אותה התנהגות הרשאות (403) כמו הדף בפועל
    return db_health_page()


# --- Query Performance Profiler (Admin UI + API) ---
def _profiler_token() -> str:
    return str(os.getenv("PROFILER_AUTH_TOKEN", "") or "").strip()


def _profiler_allowed_ips() -> List[str]:
    raw = str(os.getenv("PROFILER_ALLOWED_IPS", "") or "").strip()
    if not raw:
        return []
    return [ip.strip() for ip in raw.split(",") if ip.strip()]


def _profiler_is_authorized() -> bool:
    """אימות X-Profiler-Token + allowlist IP (best-effort).

    - אם token מוגדר: חייבים לספק X-Profiler-Token תואם
    - allowlist IP (אופציונלי): אם מוגדר, חייבים להיות בתוך הרשימה
    - בנוסף: מאפשר אדמין מחובר (session) גם אם token לא הוגדר
    """
    # Admin override (משאיר UI נוח לסביבה פנימית)
    try:
        uid = session.get("user_id")
        if uid is not None and is_admin(int(uid)):
            # עדיין נכבד allowlist IP אם מוגדר
            allowed_ips = _profiler_allowed_ips()
            if allowed_ips:
                client_ip = request.remote_addr or ""
                return client_ip in allowed_ips
            return True
    except Exception:
        pass

    token = _profiler_token()
    if token:
        provided = str(request.headers.get("X-Profiler-Token", "") or "").strip()
        try:
            if not hmac.compare_digest(provided, token):
                return False
        except Exception:
            return False

    allowed_ips = _profiler_allowed_ips()
    if allowed_ips:
        client_ip = request.remote_addr or ""
        if client_ip not in allowed_ips:
            return False

    # אם אין token ואין allowlist — נדרוש אדמין (למנוע דליפה בסביבה פתוחה)
    try:
        uid = session.get("user_id")
        return bool(uid is not None and is_admin(int(uid)))
    except Exception:
        return False


_WEBAPP_PROFILER_SERVICE = None
_WEBAPP_PROFILER_RATE_LIMITER = None


def _get_webapp_profiler_service():
    """מחזיר service יציב ל-WebApp (Flask)."""
    global _WEBAPP_PROFILER_SERVICE
    if _WEBAPP_PROFILER_SERVICE is not None:
        return _WEBAPP_PROFILER_SERVICE

    _db = get_db()
    _client = globals().get("client")

    class _ManagerLike:
        client = _client
        db = _db

    try:
        from services.query_profiler_service import PersistentQueryProfilerService  # type: ignore
    except Exception as e:
        raise RuntimeError(f"QueryProfilerService unavailable: {e}") from e

    try:
        # שיכוך כאבים: ברירת מחדל גבוהה יותר כדי להימנע מרעש/עומס בלוגים
        threshold_ms = int(float(os.getenv("PROFILER_SLOW_THRESHOLD_MS", "1000") or 1000))
    except Exception:
        threshold_ms = 1000

    _WEBAPP_PROFILER_SERVICE = PersistentQueryProfilerService(_ManagerLike(), slow_threshold_ms=threshold_ms)
    return _WEBAPP_PROFILER_SERVICE


def _get_webapp_profiler_rate_limiter():
    global _WEBAPP_PROFILER_RATE_LIMITER
    if _WEBAPP_PROFILER_RATE_LIMITER is not None:
        return _WEBAPP_PROFILER_RATE_LIMITER
    try:
        from services.query_profiler_service import RateLimiter  # type: ignore
    except Exception:
        return None
    try:
        limit = int(float(os.getenv("PROFILER_RATE_LIMIT", "60") or 60))
    except Exception:
        limit = 60
    _WEBAPP_PROFILER_RATE_LIMITER = RateLimiter(requests_per_minute=limit)
    return _WEBAPP_PROFILER_RATE_LIMITER


def _profiler_rate_limit_ok() -> bool:
    limiter = _get_webapp_profiler_rate_limiter()
    if limiter is None:
        return True
    # אדמין/משתמש מוחרג: אין מגבלת קצב בכלל
    if _is_rate_limit_exempt_user():
        return True
    try:
        client_id = str(request.headers.get("X-Profiler-Client") or request.remote_addr or "unknown")
        return limiter.is_allowed(client_id)
    except Exception:
        return True


def _run_awaitable_blocking(awaitable, *, thread_label: str) -> Any:
    """הרצה בטוחה של awaitable בסביבה סינכרונית (Flask/WSGI).

    - אם יש event loop פעיל ב-thread הנוכחי: מריצים ב-thread נקי עם לולאה חדשה.
    - אחרת: מריצים לולאה חדשה באותו thread.
    """

    def _get_native_thread_class():
        try:
            from gevent import monkey as gevent_monkey  # type: ignore
        except Exception:
            return threading.Thread
        try:
            return gevent_monkey.get_original("threading", "Thread")
        except Exception:
            start_fn = None
            for module_name in ("thread", "_thread"):
                try:
                    start_fn = gevent_monkey.get_original(module_name, "start_new_thread")
                    break
                except Exception:
                    continue
            if start_fn is None:
                return threading.Thread

            class _NativeThread:
                def __init__(self, *, target=None, name=None, daemon=None, args=None, kwargs=None):
                    self._target = target
                    self._args = tuple(args or ())
                    self._kwargs = dict(kwargs or {})
                    self.name = name or "native_thread"
                    # start_new_thread לא תומך ב-daemon; נשמר לשקיפות בלבד.
                    self.daemon = bool(daemon) if daemon is not None else False

                def start(self):
                    def _runner():
                        # ננסה להצמיד שם לת׳רד (best-effort).
                        try:
                            threading.current_thread().name = self.name
                        except Exception:
                            pass
                        if self._target is not None:
                            self._target(*self._args, **self._kwargs)

                    start_fn(_runner, ())

            return _NativeThread

    def _is_running_loop_error(exc: BaseException) -> bool:
        msg = str(exc).lower()
        return (
            "event loop is already running" in msg
            or "cannot run the event loop while another loop is running" in msg
            or "asyncio.run() cannot be called from a running event loop" in msg
        )

    async def _runner():
        return await awaitable

    def _run_in_new_loop():
        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None
        run_in_clean_context = False
        if running_loop is not None:
            loop_thread_id = getattr(running_loop, "_thread_id", None)
            if loop_thread_id is None or loop_thread_id != threading.get_ident():
                # Loop context leaked from a different thread (gevent/contextvars).
                # Run in a clean context to avoid false "loop already running".
                run_in_clean_context = True
                running_loop = None
            elif running_loop.is_running():
                raise RuntimeError("event loop is already running")

        def _run_in_new_loop_inner():
            prev_loop = None
            loop = None
            try:
                try:
                    prev_loop = asyncio.get_event_loop()
                except RuntimeError:
                    prev_loop = None
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                return loop.run_until_complete(_runner())
            finally:
                if loop is not None:
                    try:
                        loop.close()
                    finally:
                        try:
                            if prev_loop is None or prev_loop.is_closed():
                                asyncio.set_event_loop(None)
                            else:
                                asyncio.set_event_loop(prev_loop)
                        except Exception:
                            pass

        if run_in_clean_context:
            return contextvars.Context().run(_run_in_new_loop_inner)
        return _run_in_new_loop_inner()

    def _run_in_fresh_thread():
        future: Future = Future()

        def _target():
            try:
                future.set_result(_run_in_new_loop())
            except BaseException as exc:
                future.set_exception(exc)

        native_thread = _get_native_thread_class()
        thread = native_thread(target=_target, name=f"{thread_label}_loop", daemon=True)
        thread.start()
        return future.result()

    def _run_in_threadpool():
        return _OBSERVABILITY_THREADPOOL.submit(_run_in_new_loop).result()

    def _run_in_threadpool_with_fallback():
        try:
            return _run_in_threadpool()
        except RuntimeError as exc:
            if _is_running_loop_error(exc):
                return _run_in_fresh_thread()
            raise

    # תחת gevent/asyncio: אם יש event loop פעיל, נברח ל-thread "נקי".
    try:
        running_loop = asyncio.get_running_loop()
    except RuntimeError:
        running_loop = None
    if running_loop is not None:
        loop_thread_id = getattr(running_loop, "_thread_id", None)
        if loop_thread_id is not None and loop_thread_id == threading.get_ident():
            return _run_in_threadpool_with_fallback()

    # אין event loop פעיל ב-thread הנוכחי => מותר להריץ לולאה חדשה כאן.
    try:
        return _run_in_new_loop()
    except RuntimeError as exc:
        if _is_running_loop_error(exc):
            return _run_in_threadpool_with_fallback()
        raise


def _run_profiler(awaitable):
    """הרצת קורוטינה בצורה תואמת Flask תחת WSGI."""
    return _run_awaitable_blocking(awaitable, thread_label="profiler")


@app.route("/admin/profiler")
@admin_required
def admin_profiler_page():
    """דשבורד Query Performance Profiler (Admin בלבד)."""
    # token אופציונלי: אם מוגדר, נשתמש בו בבקשות JS כדי להגן על ה-API
    return render_template("profiler_dashboard.html", profiler_token=_profiler_token())


def _serialize_slow_query(q) -> Dict[str, Any]:
    return {
        "query_id": q.query_id,
        "collection": q.collection,
        "operation": q.operation,
        "query_shape": q.query_shape,
        "execution_time_ms": q.execution_time_ms,
        "timestamp": q.timestamp.isoformat() if getattr(q, "timestamp", None) else None,
    }


def _serialize_stage(stage) -> Dict[str, Any]:
    return {
        "stage": stage.stage.value,
        "index_name": stage.index_name,
        "direction": stage.direction,
        "filter_condition": stage.filter_condition,
        "input_stage": _serialize_stage(stage.input_stage) if stage.input_stage else None,
        "children": [_serialize_stage(c) for c in stage.children],
    }


def _serialize_explain_plan(plan) -> Dict[str, Any]:
    return {
        "query_id": plan.query_id,
        "collection": plan.collection,
        "query_shape": plan.query_shape,
        "winning_plan": _serialize_stage(plan.winning_plan),
        "rejected_plans": [_serialize_stage(p) for p in plan.rejected_plans],
        "stats": {
            "execution_time_ms": plan.stats.execution_time_ms,
            "docs_examined": plan.stats.docs_examined,
            "docs_returned": plan.stats.docs_returned,
            "keys_examined": plan.stats.keys_examined,
            "index_used": plan.stats.index_used,
            "is_covered_query": plan.stats.is_covered_query,
            "efficiency_ratio": round(plan.stats.efficiency_ratio, 4),
        }
        if plan.stats
        else None,
        "timestamp": plan.timestamp.isoformat(),
    }


def _serialize_aggregation_explain(plan) -> Dict[str, Any]:
    return {
        "query_id": plan.query_id,
        "collection": plan.collection,
        "pipeline_shape": plan.pipeline_shape,
        "stages": [
            {
                "stage_name": s.stage_name,
                "execution_time_ms": s.execution_time_ms,
                "docs_examined": s.docs_examined,
                "n_returned": s.n_returned,
                "uses_disk": s.uses_disk,
                "memory_usage_bytes": s.memory_usage_bytes,
                "index_used": s.index_used,
                "lookup_collection": s.lookup_collection,
                "lookup_strategy": s.lookup_strategy,
            }
            for s in plan.stages
        ],
        "total_execution_time_ms": plan.total_execution_time_ms,
        "timestamp": plan.timestamp.isoformat(),
    }


def _serialize_recommendation(rec) -> Dict[str, Any]:
    return {
        "id": rec.id,
        "title": rec.title,
        "description": rec.description,
        "severity": rec.severity.value,
        "category": rec.category,
        "suggested_action": rec.suggested_action,
        "estimated_improvement": rec.estimated_improvement,
        "code_example": rec.code_example,
        "documentation_link": rec.documentation_link,
    }


@app.route("/api/profiler/slow-queries", methods=["GET"])
def api_profiler_slow_queries():
    if not _profiler_is_authorized():
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
    if not _profiler_rate_limit_ok():
        return jsonify({"status": "error", "message": "rate_limited"}), 429
    try:
        limit = int(request.args.get("limit", "50"))
    except Exception:
        limit = 50
    collection = request.args.get("collection")
    min_time = request.args.get("min_time")
    hours = request.args.get("hours")
    since = None
    if hours:
        try:
            since = datetime.utcnow() - timedelta(hours=int(hours))
        except Exception:
            since = None
    try:
        svc = _get_webapp_profiler_service()
        queries = _run_profiler(
            svc.get_slow_queries(
                limit=limit,
                collection_filter=collection,
                min_execution_time_ms=float(min_time) if min_time else None,
                since=since,
            )
        )
        return jsonify({"status": "success", "data": [_serialize_slow_query(q) for q in queries], "count": len(queries)})
    except Exception:
        logger.exception("api_profiler_slow_queries_failed")
        return jsonify({"status": "error", "message": "internal_error"}), 500


@app.route("/api/profiler/summary", methods=["GET"])
def api_profiler_summary():
    if not _profiler_is_authorized():
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
    if not _profiler_rate_limit_ok():
        return jsonify({"status": "error", "message": "rate_limited"}), 429
    try:
        svc = _get_webapp_profiler_service()
        summary = _run_profiler(svc.get_summary_async())
        return jsonify({"status": "success", "data": summary})
    except Exception:
        logger.exception("api_profiler_summary_failed")
        return jsonify({"status": "error", "message": "internal_error"}), 500


@app.route("/api/profiler/explain", methods=["POST"])
def api_profiler_explain():
    if not _profiler_is_authorized():
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
    if not _profiler_rate_limit_ok():
        return jsonify({"status": "error", "message": "rate_limited"}), 429
    try:
        body = request.get_json(force=True, silent=False) or {}
    except Exception:
        return jsonify({"status": "error", "message": "invalid_json"}), 400
    collection = body.get("collection")
    query = body.get("query", {}) or {}
    pipeline = body.get("pipeline")
    verbosity = body.get("verbosity", "queryPlanner")
    if not collection:
        return jsonify({"status": "error", "message": "collection is required"}), 400
    try:
        svc = _get_webapp_profiler_service()
        if isinstance(pipeline, list):
            explain = _run_profiler(svc.get_aggregation_explain(collection=collection, pipeline=pipeline, verbosity=verbosity))
            return jsonify({"status": "success", "data": _serialize_aggregation_explain(explain)})
        explain = _run_profiler(svc.get_explain_plan(collection=collection, query=query, verbosity=verbosity))
        return jsonify({"status": "success", "data": _serialize_explain_plan(explain)})
    except ValueError as e:
        if "broken array normalization" in str(e):
            return jsonify({
                "status": "error",
                "message": "השאילתה מכילה נרמול שבור מגרסה ישנה. יש להשתמש בשאילתה המקורית או להקליט מחדש.",
                "error_code": "BROKEN_QUERY_SHAPE"
            }), 400
        logger.exception("api_profiler_explain_failed")
        return jsonify({"status": "error", "message": "internal_error"}), 500
    except Exception:
        logger.exception("api_profiler_explain_failed")
        return jsonify({"status": "error", "message": "internal_error"}), 500


@app.route("/api/profiler/recommendations", methods=["POST"])
def api_profiler_recommendations():
    if not _profiler_is_authorized():
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
    if not _profiler_rate_limit_ok():
        return jsonify({"status": "error", "message": "rate_limited"}), 429
    try:
        body = request.get_json(force=True, silent=False) or {}
    except Exception:
        return jsonify({"status": "error", "message": "invalid_json"}), 400
    collection = body.get("collection")
    query = body.get("query", {}) or {}
    pipeline = body.get("pipeline")
    verbosity = body.get("verbosity", "queryPlanner")
    if not collection:
        return jsonify({"status": "error", "message": "collection is required"}), 400
    try:
        svc = _get_webapp_profiler_service()
        if isinstance(pipeline, list):
            explain = _run_profiler(svc.get_aggregation_explain(collection=collection, pipeline=pipeline, verbosity=verbosity))
            recommendations = _run_profiler(svc.analyze_aggregation_and_recommend(explain))
            return jsonify(
                {
                    "status": "success",
                    "data": {
                        "aggregation_explain": _serialize_aggregation_explain(explain),
                        "recommendations": [_serialize_recommendation(r) for r in recommendations],
                    },
                }
            )
        explain = _run_profiler(svc.get_explain_plan(collection=collection, query=query, verbosity=verbosity))
        recommendations = _run_profiler(svc.generate_recommendations(explain))
        return jsonify(
            {
                "status": "success",
                "data": {
                    "explain": _serialize_explain_plan(explain),
                    "recommendations": [_serialize_recommendation(r) for r in recommendations],
                },
            }
        )
    except ValueError as e:
        if "broken array normalization" in str(e):
            return jsonify({
                "status": "error",
                "message": "השאילתה מכילה נרמול שבור מגרסה ישנה. יש להשתמש בשאילתה המקורית או להקליט מחדש.",
                "error_code": "BROKEN_QUERY_SHAPE"
            }), 400
        logger.exception("api_profiler_recommendations_failed")
        return jsonify({"status": "error", "message": "internal_error"}), 500
    except Exception:
        logger.exception("api_profiler_recommendations_failed")
        return jsonify({"status": "error", "message": "internal_error"}), 500


@app.route("/api/profiler/analyze", methods=["POST"])
def api_profiler_analyze():
    """Alias 1:1 למדריך: POST /api/profiler/analyze -> recommendations."""
    return api_profiler_recommendations()


@app.route("/api/profiler/collection/<name>/stats", methods=["GET"])
def api_profiler_collection_stats(name: str):
    if not _profiler_is_authorized():
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
    if not _profiler_rate_limit_ok():
        return jsonify({"status": "error", "message": "rate_limited"}), 429
    try:
        svc = _get_webapp_profiler_service()
        stats = _run_profiler(svc.get_collection_stats(name))
        return jsonify({"status": "success", "data": stats})
    except Exception:
        logger.exception("api_profiler_collection_stats_failed")
        return jsonify({"status": "error", "message": "internal_error"}), 500


def _db_health_token() -> str:
    return str(os.getenv("DB_HEALTH_TOKEN", "") or "").strip()


def _db_health_is_authorized() -> bool:
    """אימות Bearer token עבור /api/db/* (הגנה על מידע רגיש)."""
    token = _db_health_token()
    if not token:
        return False
    auth = str(request.headers.get("Authorization", "") or "")
    if not auth.startswith("Bearer "):
        # fallback: admin session (webapp)
        try:
            uid = session.get("user_id")
            if uid is not None and is_admin(int(uid)) and not is_impersonating_safe():
                return True
        except Exception:
            pass
        return False
    provided = auth[7:].strip()
    try:
        return hmac.compare_digest(provided, token)
    except Exception:
        return False


def _maintenance_cleanup_is_authorized() -> bool:
    """אימות token עבור Endpoint תחזוקה.

    מאפשר token גם ב-query string (?token=...) כדי לתמוך בהרצה מדפדפן/טאבלט
    ללא יכולת לשלוח Headers מותאמים אישית.

    חשוב: אנחנו לא מרחיבים את ההתנהגות הזו ל-/api/db/* כדי לא להחליש אבטחה שם.
    """
    token = _db_health_token()
    if not token:
        return False

    auth = str(request.headers.get("Authorization", "") or "")
    provided = ""
    if auth.startswith("Bearer "):
        provided = auth[7:].strip()
    else:
        try:
            provided = str(request.args.get("token") or "").strip()
        except Exception:
            provided = ""

    if not provided:
        return False
    try:
        return hmac.compare_digest(provided, token)
    except Exception:
        return False


_WEBAPP_DB_HEALTH_SERVICE = None
_DB_HEALTH_ASYNC_LOOP = None
_DB_HEALTH_ASYNC_LOOP_THREAD = None
_DB_HEALTH_ASYNC_LOOP_READY = threading.Event()
_DB_HEALTH_ASYNC_LOOP_LOCK = threading.Lock()

# Throttling ל-collStats (Per-process). מגן על DB מפני הרצות תכופות.
_DB_HEALTH_COLLECTIONS_LAST_REQUEST_MONO: Optional[float] = None
_DB_HEALTH_COLLECTIONS_COOLDOWN_LOCK = threading.Lock()


def _get_db_health_native_thread_class():
    try:
        from gevent import monkey as gevent_monkey  # type: ignore
    except Exception:
        return threading.Thread
    try:
        return gevent_monkey.get_original("threading", "Thread")
    except Exception:
        start_fn = None
        for module_name in ("thread", "_thread"):
            try:
                start_fn = gevent_monkey.get_original(module_name, "start_new_thread")
                break
            except Exception:
                continue
        if start_fn is None:
            return threading.Thread

        class _NativeThread:
            def __init__(self, *, target=None, name=None, daemon=None, args=None, kwargs=None):
                self._target = target
                self._args = tuple(args or ())
                self._kwargs = dict(kwargs or {})
                self.name = name or "native_thread"
                self.daemon = bool(daemon) if daemon is not None else False
                self._start_called = threading.Event()
                self._started = threading.Event()
                self._finished = threading.Event()

            def start(self):
                def _runner():
                    try:
                        threading.current_thread().name = self.name
                    except Exception:
                        pass
                    self._started.set()
                    try:
                        if self._target is not None:
                            self._target(*self._args, **self._kwargs)
                    finally:
                        self._finished.set()

                start_fn(_runner, ())
                self._start_called.set()

            def is_alive(self) -> bool:
                return self._start_called.is_set() and not self._finished.is_set()

        return _NativeThread


def _ensure_db_health_async_loop():
    global _DB_HEALTH_ASYNC_LOOP, _DB_HEALTH_ASYNC_LOOP_THREAD
    loop = _DB_HEALTH_ASYNC_LOOP
    if loop is not None and not loop.is_closed() and loop.is_running():
        return loop
    with _DB_HEALTH_ASYNC_LOOP_LOCK:
        loop = _DB_HEALTH_ASYNC_LOOP
        if loop is not None and not loop.is_closed():
            if loop.is_running():
                return loop
            thread = _DB_HEALTH_ASYNC_LOOP_THREAD
            if thread is not None and thread.is_alive():
                _DB_HEALTH_ASYNC_LOOP_READY.wait(timeout=0.25)
                if loop.is_running():
                    return loop
            try:
                loop.close()
            except Exception:
                logger.warning("db_health_loop_close_failed", exc_info=True)
        _DB_HEALTH_ASYNC_LOOP_READY.clear()
        loop = asyncio.new_event_loop()

        def _run_loop():
            asyncio.set_event_loop(loop)
            loop.call_soon(_DB_HEALTH_ASYNC_LOOP_READY.set)
            loop.run_forever()

        native_thread = _get_db_health_native_thread_class()
        thread = native_thread(target=_run_loop, name="db_health_async_loop", daemon=True)
        try:
            thread.start()
        except Exception:
            try:
                loop.close()
            except Exception:
                logger.warning("db_health_loop_close_failed", exc_info=True)
            raise
        _DB_HEALTH_ASYNC_LOOP = loop
        _DB_HEALTH_ASYNC_LOOP_THREAD = thread
        return loop


def _run_db_health(awaitable):
    """הרצת קורוטינה בצורה תואמת Flask תחת WSGI.

    אם מתקבל awaitable – נריץ אותו בלולאה ייעודית ברקע.
    """
    if inspect.isawaitable(awaitable):
        try:
            loop = _ensure_db_health_async_loop()
        except Exception:
            logger.exception("db_health_async_loop_failed")
            return _run_awaitable_blocking(awaitable, thread_label="db_health")
        try:
            async def _await_wrapper(item):
                return await item
            return asyncio.run_coroutine_threadsafe(_await_wrapper(awaitable), loop).result()
        except Exception:
            logger.exception("db_health_async_loop_failed")
            raise
    return awaitable


def _get_webapp_db_health_service():
    """מחזיר service יציב ל-WebApp (Flask).

    הערה: ב-Flask תחת WSGI, שימוש ב-Motor יכול להישבר בגלל event loop שונה בין בקשות.
    לכן אנחנו משתמשים בגרסה סינכרונית כדי להימנע מ-asyncio ב-WSGI.
    """
    global _WEBAPP_DB_HEALTH_SERVICE
    current_service = _WEBAPP_DB_HEALTH_SERVICE
    if current_service is not None:
        if isinstance(current_service, SyncDatabaseHealthService):
            # בדוק שה-service עדיין תקף (ה-client לא None)
            try:
                if current_service._client is not None:
                    return current_service
                # אם ה-client הוא None, נאתחל מחדש
                logger.warning("db_health_service_client_is_none, reinitializing")
            except Exception:
                pass  # אם יש שגיאה, נאתחל מחדש
        # Avoid closing a new instance created by another thread.
        if current_service is _WEBAPP_DB_HEALTH_SERVICE:
            _WEBAPP_DB_HEALTH_SERVICE = None
            close_fn = getattr(current_service, "close", None)
            if callable(close_fn):
                try:
                    close_result = close_fn()
                    if inspect.isawaitable(close_result):
                        _run_awaitable_blocking(close_result, thread_label="db_health_close")
                except Exception:
                    logger.warning("db_health_service_close_failed", exc_info=True)

    # ודא שה-client/db של ה-WebApp מאותחל
    _db = get_db()
    _client = globals().get("client")

    # שימוש ב-instance attributes במקום class attributes לאמינות
    class _ManagerLike:
        def __init__(self, mongo_client, mongo_db):
            self.client = mongo_client
            self.db = mongo_db

    if _client is None:
        logger.error("db_health_service: client is None after get_db()")

    _WEBAPP_DB_HEALTH_SERVICE = SyncDatabaseHealthService(_ManagerLike(_client, _db))
    return _WEBAPP_DB_HEALTH_SERVICE


@app.route('/api/db/pool', methods=['GET'])
def api_db_pool():
    """GET /api/db/pool - מצב Connection Pool."""
    if not _db_health_token():
        return jsonify({"error": "disabled"}), 403
    if not _db_health_is_authorized():
        return jsonify({"error": "unauthorized"}), 401
    try:
        svc = _get_webapp_db_health_service()
        pool = _run_db_health(svc.get_pool_status())
        return jsonify(pool.to_dict())
    except Exception as e:
        logger.exception("api_db_pool_failed")
        return jsonify({"error": "failed", "message": "internal_error"}), 500


@app.route('/api/db/ops', methods=['GET'])
def api_db_ops():
    """GET /api/db/ops - פעולות איטיות פעילות."""
    if not _db_health_token():
        return jsonify({"error": "disabled"}), 403
    if not _db_health_is_authorized():
        return jsonify({"error": "unauthorized"}), 401
    try:
        threshold = int(request.args.get("threshold_ms", "1000"))
    except Exception:
        threshold = 1000
    include_system = str(request.args.get("include_system", "")).lower() == "true"
    try:
        svc = _get_webapp_db_health_service()
        ops = _run_db_health(svc.get_current_operations(threshold_ms=threshold, include_system=include_system))
        return jsonify(
            {
                "count": len(ops),
                "threshold_ms": threshold,
                "operations": [op.to_dict() for op in ops],
            }
        )
    except Exception as e:
        logger.exception("api_db_ops_failed")
        return jsonify({"error": "failed", "message": "internal_error"}), 500


@app.route('/api/db/collections', methods=['GET'])
def api_db_collections():
    """GET /api/db/collections - סטטיסטיקות collections."""
    if not _db_health_token():
        return jsonify({"error": "disabled"}), 403
    if not _db_health_is_authorized():
        return jsonify({"error": "unauthorized"}), 401

    # Cooldown: הגנה על collStats (כבד) מפני הרצות תכופות.
    try:
        cooldown_sec = int(os.getenv("DB_HEALTH_COLLECTIONS_COOLDOWN_SEC", "30"))
    except Exception:
        cooldown_sec = 30
    cooldown_sec = max(0, cooldown_sec)

    start_mono = time.monotonic()
    if cooldown_sec > 0:
        # אדמין/משתמש מוחרג: לא נחסום עם cooldown בזמן פיתוח/תחזוקה
        if _is_rate_limit_exempt_user():
            cooldown_sec = 0

        global _DB_HEALTH_COLLECTIONS_LAST_REQUEST_MONO
        with _DB_HEALTH_COLLECTIONS_COOLDOWN_LOCK:
            last = _DB_HEALTH_COLLECTIONS_LAST_REQUEST_MONO
            if last is not None:
                elapsed = start_mono - float(last)
                if elapsed < cooldown_sec:
                    remaining = max(0.0, float(cooldown_sec) - elapsed)
                    retry_after_sec = max(1, int(math.ceil(remaining)))
                    logger.info(
                        "api_db_collections_rate_limited",
                        extra={
                            "retry_after_sec": retry_after_sec,
                            "cooldown_sec": cooldown_sec,
                        },
                    )
                    resp = jsonify({"error": "rate_limited", "retry_after_sec": retry_after_sec})
                    resp.status_code = 429
                    resp.headers["Retry-After"] = str(retry_after_sec)
                    return resp

            # Mark-as-started כדי למנוע הרצות מקביליות (per-process).
            _DB_HEALTH_COLLECTIONS_LAST_REQUEST_MONO = start_mono

    collection = request.args.get("collection")
    try:
        svc = _get_webapp_db_health_service()
        stats = _run_db_health(svc.get_collection_stats(collection_name=collection))
        duration_ms = int((time.monotonic() - start_mono) * 1000)
        logger.info(
            "api_db_collections_loaded",
            extra={
                "duration_ms": duration_ms,
                "count": len(stats),
                "collection": collection or "",
            },
        )
        return jsonify({"count": len(stats), "collections": [s.to_dict() for s in stats]})
    except Exception as e:
        logger.exception("api_db_collections_failed")
        return jsonify({"error": "failed", "message": "internal_error"}), 500


@app.route('/api/db/<collection>/documents', methods=['GET'])
def api_db_collection_documents(collection: str):
    """GET /api/db/{collection}/documents - שליפת מסמכים מ-collection."""
    if not _db_health_token():
        return jsonify({"error": "disabled"}), 403
    if not _db_health_is_authorized():
        return jsonify({"error": "unauthorized"}), 401

    # פרסור פרמטרים עם ברירות מחדל
    try:
        skip = int(request.args.get("skip", "0"))
        limit = int(request.args.get("limit", "20"))
    except Exception:
        return jsonify({"error": "invalid_params", "message": "skip and limit must be integers"}), 400

    if skip < 0 or limit < 1:
        return jsonify({"error": "invalid_params", "message": "skip >= 0, limit >= 1"}), 400
    if skip > MAX_SKIP:
        return jsonify({"error": "invalid_params", "message": f"skip cannot exceed {MAX_SKIP}"}), 400

    def _clean_filter_value(value: Any, max_len: int = 120) -> str:
        if value is None:
            return ""
        try:
            text = str(value).strip()
        except Exception:
            return ""
        if not text:
            return ""
        return text[:max_len]

    filters: Dict[str, Any] = {}
    user_id_raw = _clean_filter_value(request.args.get("userId") or request.args.get("user_id"), 40)
    status_raw = _clean_filter_value(request.args.get("status"), 40)
    file_id_raw = _clean_filter_value(request.args.get("fileId") or request.args.get("file_id"), 120)

    if user_id_raw:
        try:
            filters["user_id"] = int(user_id_raw)
        except Exception:
            filters["user_id"] = user_id_raw
    if status_raw:
        filters["status"] = status_raw
    if file_id_raw:
        filters["file_id"] = file_id_raw

    try:
        svc = _get_webapp_db_health_service()
        result = _run_db_health(
            svc.get_documents(
                collection_name=collection,
                skip=skip,
                limit=limit,
                filters=filters or None,
            )
        )
        return jsonify(result)
    except InvalidCollectionNameError as e:
        return jsonify({"error": "invalid_collection_name", "message": str(e)}), 400
    except CollectionAccessDeniedError as e:
        return jsonify({"error": "access_denied", "message": str(e)}), 403
    except Exception:
        logger.exception("api_db_collection_documents_failed")
        return jsonify({"error": "failed", "message": "internal_error"}), 500


@app.route('/api/db/health', methods=['GET'])
def api_db_health():
    """GET /api/db/health - סיכום בריאות כללי."""
    if not _db_health_token():
        return jsonify({"error": "disabled"}), 403
    if not _db_health_is_authorized():
        return jsonify({"error": "unauthorized"}), 401
    try:
        svc = _get_webapp_db_health_service()
        summary = _run_db_health(svc.get_health_summary())
        return jsonify(summary)
    except Exception as e:
        logger.exception("api_db_health_failed")
        return jsonify({"error": "failed", "message": "internal_error"}), 500


@app.route("/api/debug/maintenance_cleanup", methods=["GET"])
def api_debug_maintenance_cleanup():
    """GET /api/debug/maintenance_cleanup

    Endpoint תחזוקה קבוע:
    - מחיקה מלאה של slow_queries_log + service_metrics
    - הגדרת TTL:
      - slow_queries_log.timestamp => 7 ימים (604800)
      - service_metrics.ts => 24 שעות (86400)
      - service_metrics.timestamp => 24 שעות (86400) (תאימות לאחור/best-effort)
    - ניקוי אינדקסים ב-code_snippets להשארת מינימום קריטי

    הרשאות:
    - דורש DB_HEALTH_TOKEN
    - מאפשר Bearer header, או query param (?token=...) רק ב-endpoint הזה.
    """
    if not _db_health_token():
        return jsonify({"error": "disabled"}), 403
    if not _maintenance_cleanup_is_authorized():
        return jsonify({"error": "unauthorized"}), 401

    preview = str(request.args.get("preview") or "").lower() in {"1", "true", "yes", "on"}

    def _ensure_ttl_index(coll: Any, *, field: str, expire_seconds: int, index_name: str) -> dict:
        info_before: dict = {}
        try:
            info_before = coll.index_information() or {}
        except Exception:
            info_before = {}

        existing_meta = info_before.get(index_name) if isinstance(info_before, dict) else None
        if isinstance(existing_meta, dict):
            try:
                existing_expire = existing_meta.get("expireAfterSeconds")
                existing_key = existing_meta.get("key")
                if existing_expire == int(expire_seconds) and existing_key == [(field, 1)]:
                    return {
                        "name": index_name,
                        "field": field,
                        "expireAfterSeconds": int(expire_seconds),
                        "status": "exists",
                    }
            except Exception:
                pass

        # drop conflicting index with same name (best-effort)
        if not preview:
            try:
                coll.drop_index(index_name)
            except Exception:
                pass

        try:
            created_name = None
            if not preview:
                created_name = coll.create_index(
                    [(field, 1)],
                    name=index_name,
                    expireAfterSeconds=int(expire_seconds),
                    background=True,
                )
            return {
                "name": str(created_name or index_name),
                "field": field,
                "expireAfterSeconds": int(expire_seconds),
                "status": "planned" if preview else "created",
            }
        except Exception as e:
            return {
                "name": index_name,
                "field": field,
                "expireAfterSeconds": int(expire_seconds),
                "status": "error",
                "error": str(e),
            }

    def _should_keep_code_snippets_index(index_name: str, meta: Any) -> bool:
        if index_name in {"_id_", "search_text_idx", "unique_file_name", "user_id", "user_updated_at"}:
            return True
        if not isinstance(meta, dict):
            return False
        key = meta.get("key")
        # single-field user_id index (name can vary: user_id_1, user_id_idx, etc.)
        if key in ([("user_id", 1)], [("user_id", -1)]):
            return True
        # default UI sort index: (user_id, updated_at desc)
        if key in (
            [("user_id", 1), ("updated_at", -1)],
            [("updated_at", -1), ("user_id", 1)],
            [("user_id", -1), ("updated_at", -1)],
            [("updated_at", -1), ("user_id", -1)],
        ):
            return True
        # unique (user_id, file_name)
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

    try:
        db = get_db()

        # Purge logs
        deleted_slow = 0
        deleted_metrics = 0
        if not preview:
            slow_res = db.slow_queries_log.delete_many({})
            metrics_res = db.service_metrics.delete_many({})
            deleted_slow = int(getattr(slow_res, "deleted_count", 0) or 0)
            deleted_metrics = int(getattr(metrics_res, "deleted_count", 0) or 0)

        # Explicitly drop legacy TTL index that may conflict (IndexOptionsConflict)
        service_metrics_pre_drop: dict[str, Any]
        if preview:
            service_metrics_pre_drop = {"planned_drop": ["metrics_ttl"]}
        else:
            dropped_pre: list[str] = []
            try:
                db.service_metrics.drop_index("metrics_ttl")
                dropped_pre.append("metrics_ttl")
            except Exception:
                pass
            service_metrics_pre_drop = {"dropped": dropped_pre}

        # TTL indexes
        ttl_results = {
            "slow_queries_log": _ensure_ttl_index(
                db.slow_queries_log,
                field="timestamp",
                expire_seconds=604800,
                index_name="ttl_cleanup",
            ),
            "service_metrics_ts": _ensure_ttl_index(
                db.service_metrics,
                field="ts",
                expire_seconds=86400,
                index_name="ttl_cleanup_ts",
            ),
            "service_metrics_timestamp": _ensure_ttl_index(
                db.service_metrics,
                field="timestamp",
                expire_seconds=86400,
                index_name="ttl_cleanup",
            ),
        }
        ttl_results["service_metrics_pre_drop"] = service_metrics_pre_drop

        # code_snippets indexes cleanup
        code_snippets = db.code_snippets
        try:
            idx_info = code_snippets.index_information() or {}
        except Exception:
            idx_info = {}

        indexes_before = sorted([str(k) for k in (idx_info or {}).keys()])
        indexes_before_details: dict[str, dict] = {}
        for k, meta in (idx_info or {}).items():
            if not isinstance(meta, dict):
                continue
            name = str(k)
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

        for name, meta in sorted((idx_info or {}).items(), key=lambda kv: str(kv[0])):
            idx_name = str(name)
            if _should_keep_code_snippets_index(idx_name, meta):
                kept.append(idx_name)
                continue
            try:
                if preview:
                    dropped.append(idx_name)  # planned
                else:
                    code_snippets.drop_index(idx_name)
                    dropped.append(idx_name)
            except Exception as e:
                drop_errors[idx_name] = str(e)

        # Ensure critical UI sort index exists (user_id + updated_at desc)
        ensured: dict[str, Any] = {"name": "user_updated_at", "key": [("user_id", 1), ("updated_at", -1)]}
        if preview:
            ensured["status"] = "planned"
        else:
            try:
                code_snippets.create_index(
                    [("user_id", 1), ("updated_at", -1)],
                    name="user_updated_at",
                    background=True,
                )
                ensured["status"] = "created_or_exists"
            except Exception as e:
                ensured["status"] = "error"
                ensured["error"] = str(e)

        try:
            idx_info_after = code_snippets.index_information() or {}
        except Exception:
            idx_info_after = {}
        indexes_after = sorted([str(k) for k in (idx_info_after or {}).keys()])

        return jsonify(
            {
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
                    "ensured": ensured,
                },
            }
        )
    except Exception:
        logger.exception("api_debug_maintenance_cleanup_failed")
        return jsonify({"ok": False, "error": "failed", "message": "internal_error"}), 500


@app.route('/admin/stats')
@admin_required
def admin_stats_page():
    """מסך אדמין להצגת פעילות משתמשים במערכת."""
    fallback_summary = {'total_users': 0, 'active_today': 0, 'active_week': 0}
    try:
        summary_raw = user_stats.get_all_time_stats() or {}
        summary = {
            'total_users': int(summary_raw.get('total_users') or 0),
            'active_today': int(summary_raw.get('active_today') or 0),
            'active_week': int(summary_raw.get('active_week') or 0),
        }
        weekly_users = user_stats.get_weekly_stats() or []
        weekly_limit = 100
        displayed_users = weekly_users[:weekly_limit]
        total_actions = sum(int(u.get('total_actions') or 0) for u in displayed_users)
        return render_template(
            'admin_stats.html',
            summary=summary,
            weekly_users=displayed_users,
            weekly_limit=weekly_limit,
            total_actions=total_actions,
            generated_at=datetime.now(timezone.utc).strftime('%d/%m/%Y %H:%M'),
        )
    except Exception:
        logger.exception("Error in admin stats page")
        return render_template(
            'admin_stats.html',
            summary=fallback_summary,
            weekly_users=[],
            weekly_limit=0,
            total_actions=0,
            error="אירעה שגיאה בטעינת הנתונים. נסה שוב מאוחר יותר.",
            generated_at=datetime.now(timezone.utc).strftime('%d/%m/%Y %H:%M'),
        ), 500


@app.route('/admin/observability')
@admin_required
def admin_observability_page():
    """מסך Observability Dashboard המציג התראות, גרפים ואגרגציות."""
    return render_template(
        'admin_observability.html',
        default_range='24h',
        default_page=1,
    )


@app.route('/admin/rules')
@admin_required
def admin_rules_page():
    """מסך אדמין למנוע כללים ויזואלי (Visual Rule Engine)."""
    return render_template('admin_rules.html')


@app.route('/admin/config-inspector')
@admin_required
def admin_config_inspector_page():
    """דף Config Inspector לאדמינים: סקירה של משתני סביבה וקונפיגורציה."""
    from services.config_inspector_service import ConfigStatus, get_config_service

    # קבלת פרמטרים לסינון
    category = request.args.get("category", "")
    status = request.args.get("status", "")

    # המרת סטטוס לאנום
    status_filter = None
    if status:
        try:
            status_filter = ConfigStatus(status)
        except ValueError:
            status_filter = None

    # קבלת הנתונים מהשירות
    service = get_config_service()
    overview = service.get_config_overview(
        category_filter=category or None,
        status_filter=status_filter,
    )
    category_summary = service.get_category_summary()
    missing_required = service.validate_required()

    return render_template(
        "admin_config_inspector.html",
        overview=overview,
        category_summary=category_summary,
        missing_required=missing_required,
        selected_category=category,
        selected_status=status,
        statuses=[s.value for s in ConfigStatus],
    )


@app.route('/admin/cache-inspector')
def admin_cache_inspector_page():
    """
    דף Cache Inspector לאדמינים.
    מציג סקירה של Redis cache עם אפשרויות חיפוש ומחיקה.
    """
    # דרישת המוצר: ללא הרשאה מתאימה => 403 (גם אם לא מחובר)
    if not _require_admin_user():
        abort(403)

    from services.cache_inspector_service import (
        get_cache_inspector_service,
        CacheKeyStatus,
    )

    # קבלת פרמטרים
    pattern = request.args.get("pattern", "*")
    limit_str = request.args.get("limit", "100")

    try:
        limit = min(int(limit_str), 500)
    except ValueError:
        limit = 100

    # קבלת הנתונים מהשירות
    service = get_cache_inspector_service()
    overview = service.get_overview(pattern=pattern, limit=limit)
    prefixes = service.get_key_prefixes()

    # רינדור התבנית
    return render_template(
        "admin_cache_inspector.html",
        overview=overview,
        prefixes=prefixes,
        selected_pattern=pattern,
        selected_limit=limit,
        statuses=[s.value for s in CacheKeyStatus],
    )


@app.route('/admin/cache-inspector/delete', methods=['POST'])
def admin_cache_delete_handler():
    """
    API למחיקת מפתח/תבנית מה-cache.
    """
    # בדיקת הרשאות אדמין
    if not _require_admin_user():
        return jsonify({"error": "Admin access required"}), 403

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Invalid JSON"}), 400

    key = data.get("key")
    pattern = data.get("pattern")

    from services.cache_inspector_service import get_cache_inspector_service

    service = get_cache_inspector_service()

    if key:
        # מחיקת מפתח בודד
        success = service.delete_key(str(key))
        return jsonify(
            {
                "success": bool(success),
                "message": f"Key '{key}' deleted" if success else "Delete failed",
            }
        )

    if pattern:
        # מחיקת תבנית
        pattern_str = str(pattern)
        if pattern_str in ("*", "**"):
            return jsonify(
                {
                    "error": "Cannot delete all keys. Use Clear All button.",
                }
            ), 400

        deleted = service.delete_pattern(pattern_str)
        return jsonify(
            {
                "success": True,
                "deleted_count": int(deleted),
                "message": f"{deleted} keys deleted",
            }
        )

    return jsonify({"error": "No key or pattern provided"}), 400


@app.route('/admin/cache-inspector/clear-all', methods=['POST'])
def admin_cache_clear_all_handler():
    """
    API לניקוי כל ה-cache (דורש אישור).
    """
    # בדיקת הרשאות אדמין
    if not _require_admin_user():
        return jsonify({"error": "Admin access required"}), 403

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Invalid JSON"}), 400

    confirm = data.get("confirm", False)
    if not confirm:
        return jsonify(
            {
                "error": "Confirmation required",
                "message": "Send confirm: true to clear all cache",
            }
        ), 400

    from services.cache_inspector_service import get_cache_inspector_service

    service = get_cache_inspector_service()
    deleted = service.clear_all(confirm=True)

    return jsonify(
        {
            "success": True,
            "deleted_count": int(deleted),
            "message": f"Cache cleared: {deleted} keys deleted",
        }
    )


@app.route('/admin/cache-inspector/key/<path:key>')
def admin_cache_key_details_handler(key: str):
    """
    API לקבלת פרטים מלאים על מפתח.
    """
    # בדיקת הרשאות אדמין
    if not _require_admin_user():
        return jsonify({"error": "Admin access required"}), 403

    if not key:
        return jsonify({"error": "Key required"}), 400

    from services.cache_inspector_service import get_cache_inspector_service

    service = get_cache_inspector_service()
    details = service.get_key_details(key)

    if details is None:
        return jsonify({"error": "Key not found"}), 404

    return jsonify(details)


@app.route('/api/cache/stats')
def api_cache_stats_handler():
    """
    API לסטטיסטיקות cache (ציבורי למוניטורינג).
    """
    # רמת הגנה: רק סטטיסטיקות כלליות, ללא מפתחות
    from services.cache_inspector_service import get_cache_inspector_service

    service = get_cache_inspector_service()
    stats = service.get_cache_stats()

    return jsonify(
        {
            "enabled": bool(stats.enabled),
            "used_memory": stats.used_memory,
            "hit_rate": stats.hit_rate,
            "total_keys": int(stats.total_keys),
            "connected_clients": int(stats.connected_clients),
            "uptime_seconds": int(stats.uptime_seconds),
        }
    )


@app.route('/admin/drills')
@admin_required
def admin_drills_page():
    """מסך Drill Mode להרצת תרגולים והיסטוריה."""
    return render_template('admin_drills.html')


# --- Background Jobs Monitor UI + API ---
@app.route('/jobs/monitor')
@admin_required
def jobs_monitor_page():
    """מסך ניטור Jobs שרצים ברקע."""
    # העברת token לצורך קריאות API מאומתות
    token = os.getenv("DB_HEALTH_TOKEN", "")
    return render_template('jobs_monitor.html', db_health_token=token)


def _job_run_doc_to_dict(doc: Dict[str, Any], include_logs: bool = False) -> Dict[str, Any]:
    logs = []
    if include_logs:
        for log in (doc.get("logs") or [])[:]:
            try:
                ts = log.get("timestamp")
                ts_s = ts.isoformat() if ts else None
            except Exception:
                ts_s = None
            logs.append(
                {
                    "timestamp": ts_s,
                    "level": log.get("level"),
                    "message": log.get("message"),
                }
            )

    started_at = doc.get("started_at")
    ended_at = doc.get("ended_at")
    try:
        started_s = started_at.isoformat() if started_at else None
    except Exception:
        started_s = None
    try:
        ended_s = ended_at.isoformat() if ended_at else None
    except Exception:
        ended_s = None

    duration_seconds = None
    try:
        if started_at and ended_at:
            duration_seconds = float((ended_at - started_at).total_seconds())
    except Exception:
        duration_seconds = None

    out = {
        "run_id": doc.get("run_id"),
        "job_id": doc.get("job_id"),
        "started_at": started_s,
        "ended_at": ended_s,
        "status": doc.get("status"),
        "progress": int(doc.get("progress") or 0),
        "total_items": int(doc.get("total_items") or 0),
        "processed_items": int(doc.get("processed_items") or 0),
        "error_message": doc.get("error_message"),
        "trigger": doc.get("trigger"),
        "user_id": doc.get("user_id"),
        "duration_seconds": duration_seconds,
    }
    if include_logs:
        out["logs"] = logs
    return out


_BOT_JOBS_API_BASE_CACHE: Dict[str, Any] = {"base": "", "checked_at": 0.0}


def _probe_bot_jobs_api_base(base_url: str) -> bool:
    """בדיקה מהירה האם Bot Jobs API נגיש (best-effort)."""
    base = str(base_url or "").strip()
    if not base:
        return False
    base = base.rstrip("/")
    for path in ("/healthz", "/health"):
        try:
            resp = http_request("GET", base + path, timeout=1.5)
            status = int(getattr(resp, "status_code", 0) or 0)
            if status in (200, 204):
                return True
        except Exception:
            continue
    return False


def _get_bot_jobs_api_base_url() -> str:
    """מחזיר base URL ל-Bot Jobs API כדי לאפשר Trigger/סטטוס נכון (עם cache קצר)."""
    try:
        now = float(time.time())
    except Exception:
        now = 0.0

    # Cache קצר כדי להימנע מ-probe בכל בקשה
    try:
        if (now - float(_BOT_JOBS_API_BASE_CACHE.get("checked_at") or 0.0)) < 10.0:
            return str(_BOT_JOBS_API_BASE_CACHE.get("base") or "").strip()
    except Exception:
        pass

    # אם הוגדר מפורשות – השתמש בו גם בלי probe.
    configured = ""
    for key in ("BOT_JOBS_API_BASE_URL", "BOT_API_BASE_URL"):
        v = (os.getenv(key) or "").strip()
        if v:
            configured = v.rstrip("/")
            break
    if configured:
        chosen = configured
    else:
        # בלי BOT_JOBS_API_BASE_URL מפורש לא ננסה "לנחש" (זה יכול להוביל לקריאה לעצמנו).
        chosen = ""

    try:
        _BOT_JOBS_API_BASE_CACHE["base"] = chosen
        _BOT_JOBS_API_BASE_CACHE["checked_at"] = now
    except Exception:
        pass

    return chosen


def _bot_jobs_api_headers() -> Dict[str, str] | None:
    token = (os.getenv("DB_HEALTH_TOKEN") or "").strip()
    if not token:
        return None
    return {"Authorization": f"Bearer {token}"}


def _bot_jobs_api_is_explicitly_configured() -> bool:
    return bool((os.getenv("BOT_JOBS_API_BASE_URL") or os.getenv("BOT_API_BASE_URL") or "").strip())


def _fetch_bot_jobs_enabled_map(bot_api_base: str) -> Dict[str, bool]:
    """מנסה למשוך /api/jobs מה-bot כדי לקבל enabled אמיתי (כולל ENV של הבוט)."""
    base = str(bot_api_base or "").strip().rstrip("/")
    if not base:
        return {}
    url = base + "/api/jobs"
    try:
        resp = http_request("GET", url, timeout=2, headers=_bot_jobs_api_headers())
        status = int(getattr(resp, "status_code", 0) or 0)
        if status < 200 or status >= 300:
            return {}
        try:
            payload = resp.json()
        except Exception:
            return {}
        jobs = payload.get("jobs") if isinstance(payload, dict) else None
        if not isinstance(jobs, list):
            return {}
        out: Dict[str, bool] = {}
        for j in jobs:
            if not isinstance(j, dict):
                continue
            jid = str(j.get("job_id") or "").strip()
            if not jid:
                continue
            out[jid] = bool(j.get("enabled"))
        return out
    except Exception:
        return {}


@app.route('/api/jobs', methods=['GET'])
@admin_required
def api_jobs_list():
    """GET /api/jobs - רשימת כל ה-jobs"""
    from services.job_registry import JobRegistry

    registry = JobRegistry()
    bot_api_base = _get_bot_jobs_api_base_url()
    # חשוב: כדי למנוע recursion deadlock, לא נבצע HTTP call אם ה-base לא הוגדר מפורשות.
    bot_enabled_map = (
        _fetch_bot_jobs_enabled_map(bot_api_base)
        if (bot_api_base and _bot_jobs_api_is_explicitly_configured())
        else {}
    )
    jobs_by_id = {}
    for job in registry.list_all():
        enabled_local = registry.is_enabled(job.job_id)
        enabled = bool(bot_enabled_map.get(job.job_id, enabled_local))
        # can_trigger: מאפשר הפעלה ידנית אם יש callback מוגדר
        can_trigger = bool(job.callback_name)
        jobs_by_id[job.job_id] = {
            "job_id": job.job_id,
            "name": job.name,
            "description": job.description,
            "category": job.category.value,
            "type": job.job_type.value,
            "interval_seconds": job.interval_seconds,
            "enabled": enabled,
            "can_trigger": can_trigger,
            "env_toggle": job.env_toggle,
        }

    def _dynamic_job_stub(jid: str) -> dict:
        # Default: show in UI but disable trigger (we can't guarantee it exists in JobQueue)
        cat = "other"
        typ = "on_demand"
        name = jid
        desc = "Job דינמי (נוצר מהרצה/פעולת משתמש)"
        if jid.startswith("drive_"):
            cat = "sync"
            typ = "repeating"
            name = "גיבוי Drive (דינמי)"
            desc = "גיבוי Drive מתוזמן עבור משתמש"
        elif jid.startswith("reminder_"):
            cat = "other"
            typ = "once"
            name = "תזכורת (דינמי)"
            desc = "שליחת תזכורת בודדת"
        elif jid.startswith("batch_"):
            cat = "batch"
            typ = "on_demand"
            name = "Batch (דינמי)"
            desc = "עיבוד Batch עבור משתמש"
        return {
            "job_id": jid,
            "name": name,
            "description": desc,
            "category": cat,
            "type": typ,
            "interval_seconds": None,
            "enabled": True,
            "can_trigger": False,
            "env_toggle": None,
        }

    # Merge in jobs discovered from DB (so the monitor shows user actions too)
    try:
        from datetime import datetime, timezone, timedelta

        db = get_db()
        since = datetime.now(timezone.utc) - timedelta(days=7)
        pipeline = [
            {"$match": {"started_at": {"$gte": since}}},
            {"$group": {"_id": "$job_id", "last_started_at": {"$max": "$started_at"}}},
            {"$sort": {"last_started_at": -1}},
            {"$limit": 300},
        ]
        for row in db.job_runs.aggregate(pipeline):
            jid = row.get("_id")
            if isinstance(jid, str) and jid and jid not in jobs_by_id:
                jobs_by_id[jid] = _dynamic_job_stub(jid)
    except Exception:
        pass

    return jsonify({"jobs": list(jobs_by_id.values())})


@app.route('/api/jobs/active', methods=['GET'])
@admin_required
def api_jobs_active():
    """GET /api/jobs/active - הרצות פעילות והרצות אחרונות"""
    from datetime import timedelta

    try:
        db = get_db()
        now = datetime.now(timezone.utc)
        five_minutes_ago = now - timedelta(minutes=5)

        # הרצות שעדיין רצות כרגע
        running_cursor = db.job_runs.find({"status": "running"}).sort("started_at", DESCENDING).limit(20)
        running_runs = [_job_run_doc_to_dict(doc) for doc in (running_cursor or [])]

        # הרצות שהסתיימו ב-5 דקות האחרונות (completed/failed/skipped)
        recent_cursor = db.job_runs.find({
            "status": {"$in": ["completed", "failed", "skipped"]},
            "ended_at": {"$gte": five_minutes_ago}
        }).sort("ended_at", DESCENDING).limit(30)
        recent_runs = [_job_run_doc_to_dict(doc) for doc in (recent_cursor or [])]

        return jsonify({
            "active_runs": running_runs,
            "recent_runs": recent_runs,
        })
    except Exception:
        logger.exception("api_jobs_active_failed")
        return jsonify({"active_runs": [], "recent_runs": []})


@app.route('/api/jobs/<job_id>', methods=['GET'])
@admin_required
def api_job_detail(job_id: str):
    """GET /api/jobs/{job_id} - פרטי job ספציפי"""
    from services.job_registry import JobRegistry

    registry = JobRegistry()
    bot_api_base = _get_bot_jobs_api_base_url()
    bot_enabled_map = (
        _fetch_bot_jobs_enabled_map(bot_api_base)
        if (bot_api_base and _bot_jobs_api_is_explicitly_configured())
        else {}
    )
    job = registry.get(job_id)
    if not job:
        # Allow showing dynamic jobs that exist only in DB history.
        job_payload = {
            "job_id": job_id,
            "name": job_id,
            "description": "Job דינמי (נוצר מהרצה/פעולת משתמש)",
            "category": ("sync" if job_id.startswith("drive_") else ("batch" if job_id.startswith("batch_") else "other")),
            "type": ("repeating" if job_id.startswith("drive_") else ("once" if job_id.startswith("reminder_") else "on_demand")),
            "interval_seconds": None,
            "enabled": True,
            "can_trigger": False,
            "source_file": "",
        }
    else:
        enabled_local = registry.is_enabled(job.job_id)
        enabled = bool(bot_enabled_map.get(job.job_id, enabled_local))
        # can_trigger: מאפשר הפעלה ידנית אם יש callback מוגדר
        can_trigger = bool(job.callback_name)
        job_payload = {
            "job_id": job.job_id,
            "name": job.name,
            "description": job.description,
            "category": job.category.value,
            "type": job.job_type.value,
            "interval_seconds": job.interval_seconds,
            "enabled": enabled,
            "can_trigger": can_trigger,
            "source_file": job.source_file,
        }

    try:
        db = get_db()
        active = list(
            db.job_runs.find({"job_id": job_id, "status": "running"}).sort("started_at", DESCENDING).limit(20)
        )
        history = list(
            db.job_runs.find({"job_id": job_id}).sort("started_at", DESCENDING).limit(20)
        )
    except Exception:
        active = []
        history = []

    return jsonify(
        {
            "job": job_payload,
            "active_runs": [_job_run_doc_to_dict(d) for d in active],
            "history": [_job_run_doc_to_dict(d) for d in history],
        }
    )


@app.route('/api/jobs/runs/<run_id>', methods=['GET'])
@admin_required
def api_job_run_detail(run_id: str):
    """GET /api/jobs/runs/{run_id} - פרטי הרצה"""
    try:
        db = get_db()
        doc = db.job_runs.find_one({"run_id": run_id})
    except Exception:
        doc = None
    if not doc:
        return jsonify({"error": "Run not found"}), 404
    return jsonify({"run": _job_run_doc_to_dict(doc, include_logs=True)})


@app.route('/api/jobs/<job_id>/trigger', methods=['POST'])
@admin_required
def api_job_trigger(job_id: str):
    """POST /api/jobs/{job_id}/trigger - הפעלה ידנית"""
    from services.job_registry import JobRegistry

    registry = JobRegistry()
    job = registry.get(job_id)
    if not job:
        logging.warning("api_job_trigger: job_not_found job_id=%s", job_id)
        return jsonify({"error": "Job not found"}), 404

    # אסטרטגיה 1: ניסיון להפעיל דרך Bot API (אם מוגדר)
    bot_api_base = _get_bot_jobs_api_base_url()
    logging.info(
        "api_job_trigger: job_id=%s bot_api_base=%s explicitly_configured=%s",
        job_id,
        bot_api_base or "(none)",
        _bot_jobs_api_is_explicitly_configured(),
    )

    if bot_api_base:
        url = bot_api_base.rstrip("/") + f"/api/jobs/{job_id}/trigger"
        logging.info("api_job_trigger: trying Bot API url=%s", url)
        try:
            headers = _bot_jobs_api_headers()
            resp = http_request(
                "POST",
                url,
                service="bot",
                endpoint="/api/jobs/{job_id}/trigger",
                headers=headers,
                timeout=5,
            )
            status = int(getattr(resp, "status_code", 0) or 0)
            logging.info("api_job_trigger: Bot API response status=%s", status)
            if 200 <= status < 300:
                try:
                    payload = resp.json()
                except Exception:
                    payload = {"message": (resp.text or "").strip(), "job_id": job_id}
                return jsonify(payload), status
            # אם Bot API החזיר שגיאה, ננסה את האסטרטגיה הבאה
            logging.warning("api_job_trigger: Bot API returned error status=%s, falling back", status)
        except Exception as bot_err:
            logging.warning("api_job_trigger: Bot API failed error=%s, falling back to DB", bot_err)

    # אסטרטגיה 2: יצירת בקשת trigger בדאטאבייס שהבוט יעבד
    logging.info("api_job_trigger: using DB fallback for job_id=%s", job_id)
    try:
        trigger_id = _create_pending_job_trigger(job_id, job.name)
        if trigger_id:
            logging.info("api_job_trigger: created pending trigger trigger_id=%s job_id=%s", trigger_id, job_id)
            return jsonify({
                "message": f"בקשת הפעלה נוצרה עבור {job.name}",
                "job_id": job_id,
                "trigger_id": trigger_id,
                "status": "pending",
                "note": "הבוט יעבד את הבקשה בהקדם (תוך דקה לכל היותר)",
            }), 202  # Accepted
        else:
            logging.error("api_job_trigger: _create_pending_job_trigger returned None")
    except Exception:
        logging.exception("Failed to create pending trigger for job %s", job_id)

    return jsonify({
        "error": "trigger_unavailable",
        "message": "לא ניתן להפעיל את הג'וב כרגע. ודא שהבוט פעיל.",
    }), 503


def _create_pending_job_trigger(job_id: str, job_name: str) -> Optional[str]:
    """יצירת בקשת trigger בדאטאבייס לעיבוד על ידי הבוט."""
    try:
        db = get_db()
        trigger_id = str(uuid.uuid4())[:12]
        now = datetime.now(timezone.utc)
        doc = {
            "trigger_id": trigger_id,
            "job_id": job_id,
            "job_name": job_name,
            "status": "pending",
            "created_at": now,
            "processed_at": None,
            "result": None,
            "error": None,
        }
        db.job_trigger_requests.insert_one(doc)
        logging.info("Created pending job trigger: %s for job %s", trigger_id, job_id)
        return trigger_id
    except Exception as e:
        logging.exception("Failed to create pending job trigger: %s", e)
        return None


@app.route('/api/jobs/triggers/pending', methods=['GET'])
@admin_required
def api_pending_triggers():
    """GET /api/jobs/triggers/pending - בקשות trigger ממתינות"""
    try:
        db = get_db()
        cursor = db.job_trigger_requests.find(
            {"status": "pending"}
        ).sort("created_at", DESCENDING).limit(50)
        triggers = []
        for doc in cursor:
            triggers.append({
                "trigger_id": doc.get("trigger_id"),
                "job_id": doc.get("job_id"),
                "job_name": doc.get("job_name"),
                "status": doc.get("status"),
                "created_at": doc.get("created_at").isoformat() if doc.get("created_at") else None,
            })
        return jsonify({"pending_triggers": triggers})
    except Exception:
        return jsonify({"pending_triggers": []})


@app.route('/admin/observability/replay')
@admin_required
def admin_observability_replay_page():
    """ציר זמן Incident Replay עם אפשרות לשיתוף טווח זמן."""
    timerange = request.args.get('timerange') or request.args.get('range') or '3h'
    start_arg = request.args.get('start') or request.args.get('start_time')
    end_arg = request.args.get('end') or request.args.get('end_time')
    focus_ts = request.args.get('focus_ts')
    return render_template(
        'observability_replay.html',
        default_range=timerange,
        initial_start=start_arg,
        initial_end=end_arg,
        initial_focus=focus_ts,
    )


# --- Snippet library admin UI ---
try:
    from services import snippet_library_service as _snip_service  # type: ignore
except Exception:
    _snip_service = None  # type: ignore


def _get_snippets_collection_and_repo():
    """מאחזר את אוסף הסניפטים ואת ה-Repository לשימוש בכלי האדמין."""
    try:
        from database import db as _db
    except Exception:
        return None, None
    coll = getattr(_db, 'snippets_collection', None)
    if coll is None:
        coll = getattr(getattr(_db, 'db', None), 'snippets', None)
    repo = None
    try:
        repo = _db._get_repo()
    except Exception:
        repo = None
    return coll, repo


def _collect_snippets_stats(coll):
    """החזרת נתוני מצב בסיסיים עבור דף האדמין."""
    stats = {"approved": 0, "pending": 0, "total": 0}
    if coll is None:
        return stats
    try:
        stats["approved"] = int(coll.count_documents({"status": "approved"}))
    except Exception:
        stats["approved"] = 0
    try:
        stats["pending"] = int(coll.count_documents({"status": "pending"}))
    except Exception:
        stats["pending"] = 0
    try:
        stats["total"] = int(coll.count_documents({}))
    except Exception:
        stats["total"] = stats["approved"]
    return stats


def _build_snippet_export_payload(coll, *, include_pending: bool = False) -> List[Dict[str, Any]]:
    """בונה רשימת אובייקטים לייצוא JSON מתוך אוסף Mongo."""
    if coll is None:
        return []
    query: Dict[str, Any] = {}
    if include_pending:
        query["status"] = {"$in": ["approved", "pending"]}
    else:
        query["status"] = "approved"
    try:
        cursor = coll.find(
            query,
            {
                "title": 1,
                "description": 1,
                "language": 1,
                "status": 1,
            },
        )
    except Exception:
        return []
    try:
        rows = list(cursor)
    except Exception:
        rows = []

    def _norm(value: Any, *, limit: int | None = None) -> str:
        try:
            text = str(value or "").strip()
        except Exception:
            text = ""
        if limit and len(text) > limit:
            text = text[:limit]
        return text

    payload: List[Dict[str, Any]] = []
    for doc in rows:
        item = {
            "id": str(doc.get("_id")) if doc.get("_id") is not None else "",
            "title": _norm(doc.get("title"), limit=180),
            "language": _norm(doc.get("language"), limit=40),
            "description": _norm(doc.get("description"), limit=1000),
            "status": _norm(doc.get("status"), limit=20) or "approved",
        }
        payload.append(item)
    payload.sort(key=lambda it: (it.get("language", ""), it.get("title", "")))
    return payload


def _sanitize_snippet_field(value: Any, *, limit: int | None = None) -> str:
    """נירמול טקסטי זהה לזה של שירות הסניפטים (Fallback במקרה שאין)."""
    if _snip_service is not None and hasattr(_snip_service, "_sanitize_text"):
        try:
            return _snip_service._sanitize_text(value, limit or 180)  # type: ignore[attr-defined]
        except Exception:
            pass
    try:
        text = str(value or "").strip()
    except Exception:
        text = ""
    if limit and len(text) > limit:
        text = text[:limit]
    return text


def _apply_snippet_json_import(
    coll,
    repo,
    payload: List[Any],
    *,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """מיישם עדכוני JSON (בעיקר כותרות) ומחזיר סיכום תרצה."""
    errors_list: List[str] = []
    summary: Dict[str, Any] = {
        "total": len(payload),
        "updated": 0,
        "skipped": 0,
        "errors": errors_list,
        "dry_run": dry_run,
    }
    if coll is None or not payload:
        return summary

    normalizer = None
    if repo is not None:
        normalizer = getattr(repo, "_normalize_snippet_identifier", None)

    def _normalize_id(raw_id: Any):
        candidate = str(raw_id or "").strip()
        if not candidate:
            return None
        if callable(normalizer):
            try:
                normalized = normalizer(candidate)
                if normalized is not None:
                    return normalized
            except Exception:
                pass
        try:
            return ObjectId(candidate)
        except Exception:
            return None

    max_errors = 20

    for idx, entry in enumerate(payload):
        if not isinstance(entry, dict):
            summary["skipped"] += 1
            if len(errors_list) < max_errors:
                errors_list.append(f"#{idx + 1}: האיבר אינו אובייקט JSON")
            continue
        raw_id = entry.get("id") or entry.get("_id")
        if not raw_id:
            summary["skipped"] += 1
            if len(errors_list) < max_errors:
                errors_list.append(f"#{idx + 1}: חסר שדה 'id'")
            continue
        normalized_id = _normalize_id(raw_id)
        if normalized_id is None:
            summary["skipped"] += 1
            if len(errors_list) < max_errors:
                errors_list.append(f"#{idx + 1}: מזהה לא תקין ({raw_id})")
            continue

        updates: Dict[str, Any] = {}
        if "title" in entry:
            updates["title"] = _sanitize_snippet_field(entry.get("title"), limit=180)
        if "description" in entry:
            updates["description"] = _sanitize_snippet_field(entry.get("description"), limit=1000)
        if "language" in entry:
            updates["language"] = _sanitize_snippet_field(entry.get("language"), limit=40)
        if "code" in entry:
            try:
                updates["code"] = str(entry.get("code") or "")
            except Exception:
                updates["code"] = ""

        if not updates:
            summary["skipped"] += 1
            continue

        if dry_run:
            summary["updated"] += 1
            continue

        try:
            result = coll.update_one({'_id': normalized_id}, {'$set': updates})
        except Exception as exc:
            summary["skipped"] += 1
            if len(errors_list) < max_errors:
                errors_list.append(f"#{idx + 1}: שגיאת DB ({exc})")
            continue

        modified = int(getattr(result, "modified_count", 0) or 0)
        matched = int(getattr(result, "matched_count", 0) or 0)
        if modified or matched:
            summary["updated"] += 1
        else:
            summary["skipped"] += 1
            if len(errors_list) < max_errors:
                errors_list.append(f"#{idx + 1}: לא נמצא סניפט עם המזהה {raw_id}")

    return summary


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
                        # BYPASS: שליחה ישירה לטלגרם ללא מנוע כללים
                        # סיבה: הודעת מוצר למשתמש (BOT_TOKEN, chat_id=user_id) ולא "התראת מערכת" שמנוהלת ע"י Rule Engine
                        # TODO: לשקול בעתיד שכבת Notification Service מאוחדת (user_notifications) אם ירצו ניהול כללי/השקטה גם להודעות מוצר
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
                                    from telegram_api import parse_telegram_json_from_response, require_telegram_ok

                                    resp = _http_request('POST', api, json=payload, timeout=5)
                                    body = parse_telegram_json_from_response(resp, url=api)
                                    require_telegram_ok(body, url=api)
                                else:  # pragma: no cover
                                    import requests as _requests  # type: ignore
                                    from telegram_api import parse_telegram_json_from_response, require_telegram_ok

                                    resp = _requests.post(api, json=payload, timeout=5)
                                    body = parse_telegram_json_from_response(resp, url=api)
                                    require_telegram_ok(body, url=api)
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
                        # BYPASS: שליחה ישירה לטלגרם ללא מנוע כללים
                        # סיבה: הודעת מוצר למשתמש (BOT_TOKEN, chat_id=user_id) ולא "התראת מערכת" שמנוהלת ע"י Rule Engine
                        # TODO: לשקול בעתיד שכבת Notification Service מאוחדת (user_notifications) אם ירצו ניהול כללי/השקטה גם להודעות מוצר
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
                                    from telegram_api import parse_telegram_json_from_response, require_telegram_ok

                                    resp = _http_request('POST', api, json=payload, timeout=5)
                                    body = parse_telegram_json_from_response(resp, url=api)
                                    require_telegram_ok(body, url=api)
                                else:  # pragma: no cover
                                    import requests as _requests  # type: ignore
                                    from telegram_api import parse_telegram_json_from_response, require_telegram_ok

                                    resp = _requests.post(api, json=payload, timeout=5)
                                    body = parse_telegram_json_from_response(resp, url=api)
                                    require_telegram_ok(body, url=api)
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
                                from telegram_api import parse_telegram_json_from_response, require_telegram_ok

                                resp = _http_request('POST', api, json=payload, timeout=5)
                                body = parse_telegram_json_from_response(resp, url=api)
                                require_telegram_ok(body, url=api)
                            else:  # pragma: no cover
                                import requests as _requests  # type: ignore
                                from telegram_api import parse_telegram_json_from_response, require_telegram_ok

                                resp = _requests.post(api, json=payload, timeout=5)
                                body = parse_telegram_json_from_response(resp, url=api)
                                require_telegram_ok(body, url=api)
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
                                from telegram_api import parse_telegram_json_from_response, require_telegram_ok

                                resp = _http_request('POST', api, json=payload, timeout=5)
                                body = parse_telegram_json_from_response(resp, url=api)
                                require_telegram_ok(body, url=api)
                            else:  # pragma: no cover
                                import requests as _requests  # type: ignore
                                from telegram_api import parse_telegram_json_from_response, require_telegram_ok

                                resp = _requests.post(api, json=payload, timeout=5)
                                body = parse_telegram_json_from_response(resp, url=api)
                                require_telegram_ok(body, url=api)
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


# --- Admin: Import multiple snippets from Markdown (UI) ---
@app.route('/admin/snippets/import', methods=['GET', 'POST'])
@admin_required
def admin_snippets_import():
    """Admin UI to import multiple snippets from a pasted Markdown document or a URL (incl. GitHub/Gist).

    On POST:
      - If source_url provided and content empty: fetch content from URL (best-effort, supports GitHub/Gist raw).
      - Parse markdown into (title, description, code, language) tuples.
      - If dry_run: render preview with counts without persisting.
      - Else: persist each snippet via repository and auto-approve by default.
    """
    from flask import request
    import re as _re
    import dataclasses as _dc
    import textwrap as _textwrap
    from typing import List as _List, Optional as _Optional, Tuple as _Tuple

    # Lazy imports to avoid top-level deps
    try:
        from urllib.parse import urlparse as _urlparse
        from urllib.request import Request as _Request, urlopen as _urlopen
    except Exception:  # pragma: no cover
        _urlparse = None  # type: ignore
        _Request = None  # type: ignore
        _urlopen = None  # type: ignore

    @_dc.dataclass
    class _ParsedSnippet:
        title: str
        description: str
        code: str
        language: str

    _FENCE_START_RE = _re.compile(r"^```([a-zA-Z0-9_+-]*)\s*$")
    _FENCE_END_RE = _re.compile(r"^```\s*$")

    def _strip_leading_decorations(text: str) -> str:
        t = text or ""
        while t and (t[0] in ('✅', '•', '*', '-', '–', '—', ' ', '\t')):
            t = t[1:].lstrip(' \t')
        return t

    def _match_header(line: str) -> _Optional[str]:
        """Match markdown header ##..#### without heavy regex to avoid ReDoS."""
        if not line:
            return None
        # Up to 3 leading spaces
        s = line
        lead = 0
        while lead < len(s) and lead < 3 and s[lead] == ' ':
            lead += 1
        s = s[lead:]
        # Count '#'
        i = 0
        while i < len(s) and s[i] == '#':
            i += 1
        if 2 <= i <= 4 and i < len(s) and s[i].isspace():
            title = s[i:].strip()
            return _strip_leading_decorations(title)
        return None

    def _extract_why(line: str) -> _Optional[str]:
        if not line:
            return None
        s = line.lstrip()
        prefix = "**למה זה שימושי:**"
        if s.startswith(prefix):
            return s[len(prefix):].strip()
        return None

    def _guess_language(value: str, fallback: str = "text") -> str:
        value = (value or "").strip().lower()
        if not value:
            return fallback
        mapping = {
            "py": "python",
            "js": "javascript",
            "ts": "typescript",
            "sh": "bash",
            "shell": "bash",
            "yml": "yaml",
            "md": "markdown",
            "golang": "go",
            "html5": "html",
            "css3": "css",
        }
        return mapping.get(value, value)

    def _maybe_to_raw_url(url: str) -> str:
        """Accept only GitHub file/blobs and Gist URLs and strictly parse."""
        try:
            parsed = _urlparse(url) if _urlparse else None
        except Exception:
            return ""
        if not parsed or not (parsed.scheme and parsed.netloc and parsed.path):
            return ""
        host = parsed.netloc.lower()
        path = parsed.path or ""
        if host == "github.com" and "/blob/" in path:
            parts = path.strip("/").split("/")
            if len(parts) >= 5:
                owner, repo, _blob, branch = parts[:4]
                rest_segments = parts[4:]
                # Allow dots in names (file extensions), forbid empty/"."/".." segments
                safe_re = r"^[A-Za-z0-9._\-]+$"
                if (
                    _re.match(safe_re, owner)
                    and _re.match(safe_re, repo)
                    and _re.match(safe_re, branch)
                    and all((_re.match(safe_re, p) and p not in ("", ".", "..")) for p in rest_segments)
                ):
                    tail = "/".join(rest_segments)
                    return f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{tail}"
                else:
                    return ""
        if host == "gist.github.com":
            parts = path.strip("/").split("/")
            if len(parts) >= 2:
                user, gist_id = parts[:2]
                safe_re = r"^[A-Za-z0-9._\-]+$"
                if _re.match(safe_re, user) and _re.match(safe_re, gist_id):
                    return f"https://gist.githubusercontent.com/{user}/{gist_id}/raw"
                else:
                    return ""
        return ""

    def _is_allowed_url(url: str) -> bool:
        """Allow only hardcoded raw GitHub/Gist hosts with HTTPS."""
        try:
            parsed = _urlparse(url) if _urlparse else None
        except Exception:
            return False
        if not parsed or not (parsed.scheme and parsed.netloc):
            return False
        scheme = parsed.scheme.lower()
        host = parsed.netloc.lower()
        if scheme != "https":
            return False
        # Disallow any URL containing '@', port other than 443, or fragments/queries
        if "@" in host or (":" in host and not host.endswith(":443")):
            return False
        if parsed.query or parsed.fragment:
            return False
        return host in {"raw.githubusercontent.com", "gist.githubusercontent.com"}

    def _fetch_url(url: str, timeout: int = 20) -> str:
        if _Request is None or _urlopen is None:
            raise RuntimeError("URL fetching is unavailable on this server")
        req = _Request(url, headers={"User-Agent": "CodeBot/WebApp-Importer"})
        with _urlopen(req, timeout=timeout) as resp:  # type: ignore[arg-type]
            data = resp.read()
            return data.decode("utf-8", errors="replace")

    def _parse_markdown(md: str) -> _List[_ParsedSnippet]:
        lines = (md or "").splitlines()
        results: _List[_ParsedSnippet] = []
        current_title: _Optional[str] = None
        current_description: _Optional[str] = None
        i = 0
        while i < len(lines):
            line = lines[i]
            # Header lines (##..#### Title)
            hdr = _match_header(line)
            if hdr is not None:
                current_title = hdr
                current_description = None
                i += 1
                continue
            # Why line ("**למה זה שימושי:** ...")
            why = _extract_why(line)
            if why is not None:
                current_description = why
                i += 1
                continue
            m_fence = _FENCE_START_RE.match(line)
            if m_fence:
                lang = _guess_language(m_fence.group(1) or "text")
                code_lines: _List[str] = []
                i += 1
                while i < len(lines):
                    if _FENCE_END_RE.match(lines[i]):
                        break
                    code_lines.append(lines[i])
                    i += 1
                if i < len(lines) and _FENCE_END_RE.match(lines[i]):
                    i += 1
                title = (current_title or "סניפט ללא כותרת").strip()
                description = (current_description or "מתוך מסמך מיובא").strip()
                description = description.replace("\n", " ").strip()
                if len(description) > 160:
                    description = description[:157].rstrip() + "..."
                code_text = "\n".join(code_lines).rstrip("\n")
                if len(code_text) > 150_000:
                    code_text = code_text[:150_000] + "\n# ... trimmed ..."
                results.append(_ParsedSnippet(title=title, description=description, code=code_text, language=lang))
                continue
            i += 1
        return results

    def _persist(snippets: _List[_ParsedSnippet], *, auto_approve: bool, dry_run: bool) -> _Tuple[int, int, int]:
        from database import db as _db
        def _exists_title_ci(title: str) -> bool:
            try:
                coll = getattr(_db, 'snippets_collection', None)
                if coll is None:
                    return False
                q = {"title": {"$regex": f"^{_re.escape(title)}$", "$options": "i"}}
                doc = coll.find_one(q)
                return bool(doc)
            except Exception:
                return False
        created = approved = skipped = 0
        for snip in snippets:
            if _exists_title_ci(snip.title):
                skipped += 1
                continue
            if dry_run:
                created += 1
                if auto_approve:
                    approved += 1
                continue
            try:
                res = _db._get_repo().create_snippet_proposal(
                    title=snip.title,
                    description=snip.description,
                    code=snip.code,
                    language=snip.language,
                    user_id=int(session.get('user_id') or 0),
                    username=(session.get('user_data') or {}).get('username') if isinstance(session.get('user_data'), dict) else None,
                )
                if res:
                    created += 1
                    if auto_approve:
                        ok = _db._get_repo().approve_snippet(res, int(session.get('user_id') or 0))
                        if ok:
                            approved += 1
                else:
                    skipped += 1
            except Exception:
                skipped += 1
        return created, approved, skipped

    if request.method == 'GET':
        return render_template('admin_snippets_import.html', result=None)

    # POST
    source_url = (request.form.get('source_url') or '').strip()
    content = request.form.get('content') or ''
    # HTML checkbox: when unchecked the key is absent -> should be False
    auto_approve = str(request.form.get('auto_approve') or '').lower() in {'on', '1', 'true', 'yes'}
    dry_run = (request.form.get('dry_run') or '') == 'on'

    text = content
    if not text and source_url:
        maybe_raw_url = _maybe_to_raw_url(source_url)
        if not maybe_raw_url or not _is_allowed_url(maybe_raw_url):
            err = "ניתן לייבא רק מ‑GitHub/Gist באמצעות מזהה חוקי (לא URL שרירותי)"
            return render_template('admin_snippets_import.html', error=err, result=None, source_url=source_url, content=content, auto_approve=auto_approve, dry_run=dry_run)
        try:
            text = _fetch_url(maybe_raw_url)
        except Exception as e:
            err = f"שגיאה בטעינת ה‑URL: {e}"
            return render_template('admin_snippets_import.html', error=err, result=None, source_url=source_url, content=content, auto_approve=auto_approve, dry_run=dry_run)

    if not text.strip():
        return render_template('admin_snippets_import.html', error="לא התקבל תוכן או URL", result=None, source_url=source_url, content=content, auto_approve=auto_approve, dry_run=dry_run)

    snippets = _parse_markdown(text)
    if not snippets:
        return render_template('admin_snippets_import.html', error="לא נמצאו סניפטים במסמך", result=None, source_url=source_url, content=content, auto_approve=auto_approve, dry_run=dry_run)

    created, approved, skipped = _persist(snippets, auto_approve=auto_approve, dry_run=dry_run)
    summary = {
        'parsed': len(snippets),
        'created': created,
        'approved': approved,
        'skipped': skipped,
        'auto_approve': auto_approve,
        'dry_run': dry_run,
        'titles': [s.title for s in snippets],
    }
    return render_template('admin_snippets_import.html', result=summary, error=None, source_url=source_url, content=content, auto_approve=auto_approve, dry_run=dry_run)


@app.route('/admin/snippets/translate', methods=['GET', 'POST'])
@admin_required
def admin_snippets_translate():
    coll, repo = _get_snippets_collection_and_repo()
    builtin_count = len(getattr(_snip_service, "BUILTIN_SNIPPETS", [])) if _snip_service is not None else 0
    stats = _collect_snippets_stats(coll)
    error = None
    import_result = None
    default_dry_run = True
    if request.method == 'POST':
        default_dry_run = bool(request.form.get('dry_run'))
        uploaded = request.files.get('json_file')
        if coll is None:
            error = "אוסף הסניפטים אינו זמין כרגע (יתכן ששרת ה-DB לא מחובר)."
        elif uploaded is None or not uploaded.filename:
            error = "נא לבחור קובץ JSON לייבוא."
        else:
            raw_bytes = uploaded.read()
            max_size = 5_000_000  # ~5MB
            if not raw_bytes:
                error = "הקובץ שנבחר ריק."
            elif len(raw_bytes) > max_size:
                error = "קובץ גדול מדי (עד 5MB). נסו לפצל או להסיר שדות מיותרים."
            else:
                try:
                    payload = json.loads(raw_bytes.decode('utf-8'))
                except Exception as exc:
                    error = f"JSON לא תקין: {exc}"
                else:
                    if not isinstance(payload, list):
                        error = "הקובץ חייב להכיל מערך של אובייקטים (list)."
                    else:
                        dry_run = bool(request.form.get('dry_run'))
                        import_result = _apply_snippet_json_import(coll, repo, payload, dry_run=dry_run)
                        default_dry_run = dry_run
    return render_template(
        'admin_snippets_translate.html',
        stats=stats,
        builtin_count=builtin_count,
        error=error,
        import_result=import_result,
        default_dry_run=default_dry_run,
    )


@app.route('/admin/snippets/export-json')
@admin_required
def admin_snippets_export_json():
    coll, _ = _get_snippets_collection_and_repo()
    include_pending = request.args.get('include_pending') == '1'
    payload = _build_snippet_export_payload(coll, include_pending=include_pending)
    body = json.dumps(payload, ensure_ascii=False, indent=2)
    file_name = f"snippets-export-{datetime.now(timezone.utc).strftime('%Y%m%d')}.json"
    response = Response(body, mimetype='application/json; charset=utf-8')
    response.headers['Content-Disposition'] = f'attachment; filename="{file_name}"'
    return response


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


# --- Announcements: Admin UI + Public API ---
def _normalize_announcement_link(raw: str) -> str:
    try:
        v = (raw or "").strip()
        if not v:
            return ""
        # קישור פנימי מותר: מתחיל ב-
        if v.startswith('/'):
            return v
        # קישור חיצוני: https בלבד
        if v.lower().startswith('https://'):
            return v
        return ""
    except Exception:
        return ""

def _announcement_doc_to_json(doc: Dict[str, Any]) -> Dict[str, Any]:
    return {
        'id': str(doc.get('_id')),
        'text': str(doc.get('text') or ''),
        'link': (doc.get('link') or None) if str(doc.get('link') or '').strip() else None,
    }


def _normalize_announcement_paths(raw: str) -> list[str]:
    """מקבל מחרוזת עם פסיקים/שורות ומחזיר רשימת נתיבים תקינים שיתאימו ע"פ כללים פשוטים.

    כללים:
    - חייב להתחיל ב-'/'
    - רווחים ייגזרו
    - תו '*' מותר בסוף התבנית (prefix match), למשל: '/files*'
    - תווים אחרים יישמרו כפי שהם (ללא Regex)
    """
    try:
        parts = []
        for token in str(raw or '').replace('\n', ',').replace('\r', ',').split(','):
            s = (token or '').strip()
            if not s:
                continue
            if not s.startswith('/'):
                continue
            parts.append(s)
        # הסר כפילויות תוך שמירה על סדר
        seen = set()
        uniq = []
        for p in parts:
            if p in seen:
                continue
            seen.add(p)
            uniq.append(p)
        return uniq
    except Exception:
        return []


def _runtime_env_segment() -> str:
    """ממפה ENV לקטגוריה לוגית: 'prod' או 'dev'."""
    try:
        name = (os.getenv('ENVIRONMENT') or os.getenv('ENV') or 'production').strip().lower()
        if name in {'dev', 'development', 'local'}:
            return 'dev'
        return 'prod'
    except Exception:
        return 'prod'


def _path_matches(pattern: str, current_path: str) -> bool:
    try:
        pat = str(pattern or '').strip()
        path = str(current_path or '/').strip()
        if not pat.startswith('/'):
            return False
        if pat.endswith('*'):
            prefix = pat[:-1]
            return path.startswith(prefix)
        return path == pat
    except Exception:
        return False


def _announcement_matches_context(doc: Dict[str, Any], current_path: str) -> bool:
    """בודק התאמת הכרזה לנתיב ולסביבה. ברירת מחדל: רק /login ו-/files."""
    try:
        # התאמת סביבה
        env_rule = str(doc.get('env') or 'all').strip().lower()
        env_seg = _runtime_env_segment()
        if env_rule not in {'all', 'prod', 'dev'}:
            env_rule = 'all'
        if env_rule != 'all' and env_rule != env_seg:
            return False

        # התאמת נתיב
        paths: list[str] = list(doc.get('paths') or [])
        # אם אין כלל paths — ברירת מחדל רק לעמודים הראשיים
        default_paths = ['/login', '/files']
        rules = paths if len(paths) > 0 else default_paths
        for pat in rules:
            if _path_matches(str(pat), current_path):
                return True
        return False
    except Exception:
        return False


@app.route('/api/v1/announcements/active', methods=['GET'])
def api_active_announcement():
    # אנדפוינט מחזיר את ההכרזה הפעילה או null; עם debug=1 לאדמין מוחזר הסבר מפורט
    try:
        _db = get_db()
    except Exception:
        return jsonify(None)
    try:
        current_path = (request.args.get('path') or request.path or '/').strip()
        debug_flag = str((request.args.get('debug') or '').strip().lower()) in {'1', 'true', 'yes'}
        try:
            uid = int(session.get('user_id') or 0)
        except Exception:
            uid = 0
        admin_view = bool(uid and is_admin(uid) and debug_flag)

        doc = _db.announcements.find_one({'is_active': True}, sort=[('updated_at', DESCENDING)])
        if not doc:
            resp = jsonify(None)
            if admin_view:
                try:
                    resp.headers['X-Announcement-Reason'] = 'no_active_doc'
                    resp.headers['X-Announcement-Path'] = str(current_path)
                    resp.headers['X-Announcement-Env-Seg'] = _runtime_env_segment()
                except Exception:
                    pass
            return resp, 200

        matches = _announcement_matches_context(doc, current_path)
        if not matches:
            resp = jsonify(None)
            if admin_view:
                try:
                    resp.headers['X-Announcement-Reason'] = 'context_mismatch'
                    resp.headers['X-Announcement-Env-Rule'] = str(doc.get('env') or 'all')
                    resp.headers['X-Announcement-Env-Seg'] = _runtime_env_segment()
                    resp.headers['X-Announcement-Paths'] = ','.join(list(doc.get('paths') or []))
                    resp.headers['X-Announcement-Path'] = str(current_path)
                except Exception:
                    pass
            return resp, 200

        payload = _announcement_doc_to_json(doc)
        resp = jsonify(payload)
        if admin_view:
            try:
                resp.headers['X-Announcement-Reason'] = 'ok'
                resp.headers['X-Announcement-Env-Rule'] = str(doc.get('env') or 'all')
                resp.headers['X-Announcement-Env-Seg'] = _runtime_env_segment()
                resp.headers['X-Announcement-Paths'] = ','.join(list(doc.get('paths') or []))
                resp.headers['X-Announcement-Path'] = str(current_path)
                resp.headers['X-Announcement-Id'] = payload.get('id', '')
            except Exception:
                pass
        return resp, 200
    except Exception:
        return jsonify(None)


@app.route('/admin/announcements', methods=['GET'])
@admin_required
def admin_announcements_index():
    items: list[dict] = []
    try:
        _db = get_db()
        cur = _db.announcements.find({}, sort=[('created_at', DESCENDING)])
        for d in cur:
            try:
                items.append({
                    '_id': str(d.get('_id')),
                    'text': str(d.get('text') or ''),
                    'link': str(d.get('link') or ''),
                    'is_active': bool(d.get('is_active', False)),
                    'paths': list(d.get('paths') or []),
                    'env': str(d.get('env') or 'all'),
                    'created_at': d.get('created_at'),
                    'updated_at': d.get('updated_at'),
                })
            except Exception:
                pass
    except Exception:
        items = []
    return render_template('admin_announcements.html', items=items)


@app.route('/admin/announcements/new', methods=['GET', 'POST'])
@admin_required
def admin_announcements_new():
    if request.method == 'GET':
        return render_template('admin_announcements.html', create_mode=True, items=None)
    # POST: create
    text = (request.form.get('text') or '').strip()
    link = _normalize_announcement_link(request.form.get('link') or '')
    paths_raw = request.form.get('paths') or ''
    paths = _normalize_announcement_paths(paths_raw)
    env_rule = (request.form.get('env') or 'all').strip().lower()
    env_rule = env_rule if env_rule in {'all', 'prod', 'dev'} else 'all'
    is_active = str(request.form.get('is_active') or '').lower() in {'on', '1', 'true', 'yes'}
    if not text:
        return render_template('admin_announcements.html', create_mode=True, error='חובה להזין טקסט להכרזה', form={'text': text, 'link': link, 'is_active': is_active})
    try:
        _db = get_db()
    except Exception:
        return render_template('admin_announcements.html', create_mode=True, error='שגיאת מסד נתונים')
    now = datetime.now(timezone.utc)
    try:
        if is_active:
            try:
                _db.announcements.update_many({'is_active': True}, {'$set': {'is_active': False, 'updated_at': now}})
            except Exception:
                pass
        doc = {
            'text': text[:280],
            'link': link,
            'is_active': bool(is_active),
            'created_at': now,
            'updated_at': now,
            'paths': paths,
            'env': env_rule,
        }
        _db.announcements.insert_one(doc)
    except Exception:
        return render_template('admin_announcements.html', create_mode=True, error='שמירת ההכרזה נכשלה')
    return redirect(url_for('admin_announcements_index'))


@app.route('/admin/announcements/edit', methods=['GET', 'POST'])
@admin_required
def admin_announcements_edit():
    try:
        _db = get_db()
    except Exception:
        return redirect(url_for('admin_announcements_index'))
    item_id = (request.args.get('id') or request.form.get('id') or '').strip()
    from bson import ObjectId  # type: ignore
    if request.method == 'POST':
        text = (request.form.get('text') or '').strip()
        link = _normalize_announcement_link(request.form.get('link') or '')
        paths_raw = request.form.get('paths') or ''
        paths = _normalize_announcement_paths(paths_raw)
        env_rule = (request.form.get('env') or 'all').strip().lower()
        env_rule = env_rule if env_rule in {'all', 'prod', 'dev'} else 'all'
        is_active = str(request.form.get('is_active') or '').lower() in {'on', '1', 'true', 'yes'}
        if not text:
            return render_template('admin_announcements.html', edit_mode=True, error='חובה להזין טקסט', item_id=item_id)
        now = datetime.now(timezone.utc)
        try:
            if is_active:
                try:
                    _db.announcements.update_many({'is_active': True, '_id': {'$ne': ObjectId(item_id)}}, {'$set': {'is_active': False, 'updated_at': now}})
                except Exception:
                    pass
            _db.announcements.update_one(
                {'_id': ObjectId(item_id)},
                {'$set': {
                    'text': text[:280],
                    'link': link,
                    'is_active': bool(is_active),
                    'updated_at': now,
                    'paths': paths,
                    'env': env_rule,
                }}
            )
        except Exception:
            return render_template('admin_announcements.html', edit_mode=True, error='עדכון נכשל', item_id=item_id)
        return redirect(url_for('admin_announcements_index'))
    # GET: load existing
    try:
        doc = _db.announcements.find_one({'_id': ObjectId(item_id)})
        if not isinstance(doc, dict):
            return redirect(url_for('admin_announcements_index'))
        item = {
            '_id': str(doc.get('_id')),
            'text': str(doc.get('text') or ''),
            'link': str(doc.get('link') or ''),
            'is_active': bool(doc.get('is_active', False)),
            'paths': ', '.join([str(p) for p in (doc.get('paths') or [])]) if isinstance(doc.get('paths'), (list, tuple)) else '',
            'env': str(doc.get('env') or 'all'),
        }
        return render_template('admin_announcements.html', edit_mode=True, item=item)
    except Exception:
        return redirect(url_for('admin_announcements_index'))


@app.route('/admin/announcements/delete', methods=['POST'])
@admin_required
def admin_announcements_delete():
    try:
        _db = get_db()
    except Exception:
        return redirect(url_for('admin_announcements_index'))
    item_id = (request.args.get('id') or request.form.get('id') or '').strip()
    try:
        from bson import ObjectId  # type: ignore
        _db.announcements.delete_one({'_id': ObjectId(item_id)})
    except Exception:
        pass
    return redirect(url_for('admin_announcements_index'))


@app.route('/admin/announcements/activate')
@admin_required
def admin_announcements_activate():
    try:
        _db = get_db()
    except Exception:
        return redirect(url_for('admin_announcements_index'))
    item_id = (request.args.get('id') or '').strip()
    if not item_id:
        return redirect(url_for('admin_announcements_index'))
    now = datetime.now(timezone.utc)
    try:
        from bson import ObjectId  # type: ignore
        _db.announcements.update_many({'is_active': True}, {'$set': {'is_active': False, 'updated_at': now}})
        _db.announcements.update_one({'_id': ObjectId(item_id)}, {'$set': {'is_active': True, 'updated_at': now}})
    except Exception:
        pass
    return redirect(url_for('admin_announcements_index'))


@app.route('/admin/force-index-creation')
@admin_required
def force_index_creation():
    """
    Endpoint לבדיקת/יצירת אינדקס active_recent_fixed על code_snippets.
    אם האינדקס כבר קיים - מחזיר את המצב הנוכחי.
    שם עקבי עם database/manager.py.
    """
    import json
    from bson import json_util
    
    results = {}
    try:
        from pymongo import IndexModel, ASCENDING, DESCENDING

        db = get_db()
        collection = db.code_snippets

        # בדיקה אם האינדקס כבר קיים
        existing_indexes = list(collection.list_indexes())
        index_names = [idx.get("name") for idx in existing_indexes]
        
        # שם עקבי עם manager.py
        target_index_name = "active_recent_fixed"
        old_index_name = "active_recent_idx"
        
        # מחיקת האינדקס הישן אם קיים
        if old_index_name in index_names:
            try:
                collection.drop_index(old_index_name)
                results['dropped_old'] = f"✅ Dropped old index '{old_index_name}'"
            except Exception:
                pass
        
        if target_index_name in index_names:
            # האינדקס כבר קיים - זה טוב!
            results['status'] = f"✅ Index '{target_index_name}' already exists!"
            results['message'] = (
                "האינדקס כבר קיים ועובד. "
                "הבעיה היא לא האינדקס - הבעיה היא דפוס השאילתות עם $or. "
                "לך ל-/admin/fix-is-active?action=migrate כדי לתקן את הנתונים."
            )
        else:
            # ניסיון ליצור את האינדקס
            model = IndexModel(
                [("is_active", ASCENDING), ("created_at", DESCENDING)],
                name=target_index_name,
                background=True
            )
            try:
                collection.create_indexes([model])
                results['status'] = f"✅ Index '{target_index_name}' created successfully!"
            except Exception as create_err:
                err_str = str(create_err)
                if "IndexOptionsConflict" in err_str or "already exists" in err_str.lower():
                    results['status'] = f"✅ Index already exists (different name)"
                    results['message'] = "האינדקס כבר קיים. הבעיה היא בדפוס השאילתות, לא באינדקס."
                else:
                    raise create_err

        # החזרת רשימת האינדקסים
        results['indexes'] = json.loads(json_util.dumps(list(collection.list_indexes())))
        results['next_step'] = "הרץ /admin/fix-is-active?action=migrate כדי לתקן את הנתונים"

        return jsonify(results)

    except Exception as e:
        logger.exception("force_index_creation_failed")
        return jsonify({"error": str(e), "status": "failed"}), 500


@app.route('/admin/create-job-trigger-index')
@admin_required
def create_job_trigger_index():
    """
    יצירת אינדקס על job_trigger_requests.status
    למניעת COLLSCAN בזמן polling.
    """
    import json
    from bson import json_util

    results = {}
    try:
        from pymongo import IndexModel, ASCENDING

        db = get_db()
        collection = db.job_trigger_requests

        # בדיקה אם האינדקס כבר קיים
        existing_indexes = list(collection.list_indexes())
        index_names = [idx.get("name") for idx in existing_indexes]

        target_index_name = "status_idx"

        if target_index_name in index_names:
            results['status'] = f"✅ Index '{target_index_name}' already exists!"
            results['message'] = "האינדקס כבר קיים - הבעיה אמורה להיפתר."
        else:
            # יצירת האינדקס
            model = IndexModel(
                [("status", ASCENDING)],
                name=target_index_name,
                background=True
            )
            try:
                collection.create_indexes([model])
                results['status'] = f"✅ Index '{target_index_name}' created successfully!"
                results['message'] = "האינדקס נוצר - ה-COLLSCAN אמור להיעלם."
            except Exception as create_err:
                err_str = str(create_err)
                if "IndexOptionsConflict" in err_str or "already exists" in err_str.lower():
                    results['status'] = f"✅ Index already exists (different name)"
                else:
                    raise create_err

        # החזרת רשימת האינדקסים
        results['indexes'] = json.loads(json_util.dumps(list(collection.list_indexes())))

        return jsonify(results)

    except Exception as e:
        logger.exception("create_job_trigger_index_failed")
        return jsonify({"error": str(e), "status": "failed"}), 500


@app.route('/admin/create-global-search-index')
@admin_required
def create_global_search_index():
    """
    יצירת אינדקס TEXT לחיפוש גלובלי על code_snippets.
    מאפשר להפעיל בנייה יזומה ולבדוק אם יש פעולת Index Build פעילה.
    """
    import json
    from bson import json_util

    results = {}
    try:
        from pymongo import IndexModel, TEXT

        db = get_db()
        collection = db.code_snippets

        target_index_name = "search_text_idx"

        # שליחת פקודת יצירה (idempotent בפועל; אם כבר קיים - לא אמור להזיק)
        model = IndexModel(
            [("file_name", TEXT), ("description", TEXT), ("tags", TEXT), ("code", TEXT)],
            name=target_index_name,
            background=True,
        )
        try:
            collection.create_indexes([model])
            results["status"] = f"✅ Command Sent for {target_index_name}"
        except Exception as create_err:
            err_str = str(create_err or "")
            err_l = err_str.lower()
            code = getattr(create_err, "code", None)
            is_conflict = bool(
                code in {85, 86}
                or "indexoptionsconflict" in err_l
                or "indexkeyspecsconflict" in err_l
                or "already exists" in err_l
            )
            if is_conflict:
                results["status"] = f"✅ Index '{target_index_name}' already exists (or equivalent)"
                results["message"] = err_str
            else:
                raise

        # רשימת אינדקסים עדכנית
        results["indexes"] = json.loads(json_util.dumps(list(collection.list_indexes())))

        # בדיקת פעולות בניית אינדקסים פעילות (best-effort; תלוי הרשאות/Atlas tier)
        building_ops = []
        building_error = None
        try:
            current_ops = db.command({"currentOp": 1, "command.createIndexes": {"$exists": True}})
            for op in current_ops.get("inprog", []) or []:
                cmd = op.get("command") or {}
                if cmd.get("createIndexes") == "code_snippets":
                    building_ops.append(op)
        except Exception as e:
            # fallback תואם Shared Tier
            try:
                ops = db.command({"currentOp": 1, "active": True})
                for op in ops.get("inprog", []) or []:
                    cmd = op.get("command") or {}
                    msg = op.get("msg", "")
                    # ב-fallback נספור רק אם זו בניית אינדקס של code_snippets (ולא כל "Index Build" כללי)
                    if cmd.get("createIndexes") == "code_snippets" or ("Index Build" in (msg or "") and "code_snippets" in (msg or "")):
                        building_ops.append(op)
            except Exception as e2:
                building_error = f"{e} | {e2}"

        results["building_ops"] = {
            "active_count": len(building_ops),
            "status": "✅ אין בנייה פעילה" if not building_ops else f"⏳ {len(building_ops)} פעולות בנייה פעילות",
            "operations": json.loads(json_util.dumps(building_ops)) if building_ops else [],
        }
        if building_error:
            results["building_ops"]["error"] = building_error

        return jsonify(results)

    except Exception as e:
        logger.exception("create_global_search_index_failed")
        return jsonify({"error": str(e), "status": "failed"}), 500


@app.route('/admin/verify-indexes')
@admin_required
def verify_indexes():
    """
    סקריפט אימות אינדקסים מקיף.
    בודק:
    1. פעולות בניית אינדקסים פעילות (currentOp)
    2. אינדקסים בקולקשן users (לבדיקת user_id)
    3. אינדקסים בקולקשן note_reminders
    4. אינדקסים בקולקציות קריטיות נוספות
    """
    import json
    from bson import json_util

    results = {
        "current_index_builds": {},
        "users_indexes": {},
        "note_reminders_indexes": {},
        "job_trigger_requests_indexes": {},
        "code_snippets_indexes": {},
        "summary": {}
    }

    try:
        db = get_db()

        # 1. בדיקת פעולות בניית אינדקסים פעילות
        try:
            current_ops = db.command({
                "currentOp": 1,
                "command.createIndexes": {"$exists": True}
            })
            in_progress = current_ops.get("inprog", [])
            results["current_index_builds"] = {
                "active_count": len(in_progress),
                "status": "✅ אין פעולות בנייה פעילות" if not in_progress else f"⏳ {len(in_progress)} פעולות בנייה פעילות",
                "operations": json.loads(json_util.dumps(in_progress)) if in_progress else []
            }
        except Exception as e:
            results["current_index_builds"] = {"error": str(e)}

        # 2. אינדקסים בקולקשן users
        try:
            users_indexes = list(db.users.list_indexes())
            has_user_id_idx = any(
                "user_id" in str(idx.get("key", {})) 
                for idx in users_indexes
            )
            results["users_indexes"] = {
                "count": len(users_indexes),
                "has_user_id_index": has_user_id_idx,
                "status": "✅ קיים אינדקס על user_id" if has_user_id_idx else "⚠️ חסר אינדקס על user_id!",
                "indexes": json.loads(json_util.dumps(users_indexes))
            }
        except Exception as e:
            results["users_indexes"] = {"error": str(e)}

        # 3. אינדקסים בקולקשן note_reminders
        try:
            reminders_indexes = list(db.note_reminders.list_indexes())
            results["note_reminders_indexes"] = {
                "count": len(reminders_indexes),
                "status": f"✅ {len(reminders_indexes)} אינדקסים קיימים",
                "indexes": json.loads(json_util.dumps(reminders_indexes))
            }
        except Exception as e:
            results["note_reminders_indexes"] = {"error": str(e)}

        # 4. אינדקסים בקולקשן job_trigger_requests
        try:
            job_indexes = list(db.job_trigger_requests.list_indexes())
            has_status_idx = any(
                "status" in str(idx.get("key", {})) 
                for idx in job_indexes
            )
            results["job_trigger_requests_indexes"] = {
                "count": len(job_indexes),
                "has_status_index": has_status_idx,
                "status": "✅ קיים אינדקס על status" if has_status_idx else "⚠️ חסר אינדקס על status!",
                "indexes": json.loads(json_util.dumps(job_indexes))
            }
        except Exception as e:
            results["job_trigger_requests_indexes"] = {"error": str(e)}

        # 5. אינדקסים בקולקשן code_snippets
        try:
            snippets_indexes = list(db.code_snippets.list_indexes())
            has_active_idx = any(
                "is_active" in str(idx.get("key", {})) and "created_at" in str(idx.get("key", {}))
                for idx in snippets_indexes
            )
            results["code_snippets_indexes"] = {
                "count": len(snippets_indexes),
                "has_is_active_created_at_index": has_active_idx,
                "status": "✅ קיים אינדקס מורכב על is_active + created_at" if has_active_idx else "⚠️ חסר אינדקס מורכב!",
                "indexes": json.loads(json_util.dumps(snippets_indexes))
            }
        except Exception as e:
            results["code_snippets_indexes"] = {"error": str(e)}

        # סיכום
        warnings = []
        if not results.get("users_indexes", {}).get("has_user_id_index"):
            warnings.append("חסר אינדקס על users.user_id")
        if not results.get("job_trigger_requests_indexes", {}).get("has_status_index"):
            warnings.append("חסר אינדקס על job_trigger_requests.status")
        if not results.get("code_snippets_indexes", {}).get("has_is_active_created_at_index"):
            warnings.append("חסר אינדקס מורכב על code_snippets")
        
        results["summary"] = {
            "all_critical_indexes_present": len(warnings) == 0,
            "warnings": warnings if warnings else ["✅ כל האינדקסים הקריטיים קיימים!"],
            "builds_in_progress": results.get("current_index_builds", {}).get("active_count", 0)
        }

        return jsonify(results)

    except Exception as e:
        logger.exception("verify_indexes_failed")
        return jsonify({"error": str(e), "status": "failed"}), 500


@app.route('/admin/create-users-index')
@admin_required
def create_users_index():
    """
    יצירת אינדקס על users.user_id
    למניעת COLLSCAN בזמן update לפי user_id.
    """
    import json
    from bson import json_util

    results = {}
    try:
        from pymongo import IndexModel, ASCENDING

        db = get_db()
        collection = db.users

        # בדיקה אם האינדקס כבר קיים
        existing_indexes = list(collection.list_indexes())
        
        # בדיקה אם יש אינדקס על user_id
        has_user_id_idx = any(
            idx.get("key", {}).get("user_id") is not None
            for idx in existing_indexes
        )

        if has_user_id_idx:
            results['status'] = "✅ Index on 'user_id' already exists!"
            results['message'] = "האינדקס כבר קיים - אין צורך ליצור חדש."
        else:
            # יצירת האינדקס
            model = IndexModel(
                [("user_id", ASCENDING)],
                name="user_id_idx",
                background=True
            )
            try:
                collection.create_indexes([model])
                results['status'] = "✅ Index 'user_id_idx' created successfully!"
                results['message'] = "האינדקס נוצר - ה-COLLSCAN על users אמור להיעלם."
            except Exception as create_err:
                err_str = str(create_err)
                if "IndexOptionsConflict" in err_str or "already exists" in err_str.lower():
                    results['status'] = "✅ Index already exists (different name)"
                else:
                    raise create_err

        # החזרת רשימת האינדקסים
        results['indexes'] = json.loads(json_util.dumps(list(collection.list_indexes())))

        return jsonify(results)

    except Exception as e:
        logger.exception("create_users_index_failed")
        return jsonify({"error": str(e), "status": "failed"}), 500


@app.route('/admin/fix-is-active')
@admin_required
def fix_is_active():
    """
    🚨 CRITICAL: תיקון הבעיה האמיתית של Slow Queries!
    
    הבעיה (היסטורית): השאילתות השתמשו ב-$or/exists לצורך תאימות לאחור,
    וזה מנע שימוש יעיל באינדקסים.
    
    הפתרון:
    1. מיגרציה: הוספת is_active: true לכל המסמכים שחסר להם השדה
    2. לאחר מכן: השאילתות יוכלו להשתמש בפילטר ישיר {is_active: true}
    
    פרמטרים (query string):
    - action=status: רק בדיקת סטטוס (ברירת מחדל)
    - action=migrate: הרצת המיגרציה (מוגבל לבאטש בכל קריאה)
    - batch_size=N: גודל באטש (ברירת מחדל: 5000, מקסימום: 10000)
    """
    import json
    from bson import json_util
    
    results = {}
    action = request.args.get('action', 'status')
    
    try:
        batch_size = min(10000, max(100, int(request.args.get('batch_size', 5000))))
    except (ValueError, TypeError):
        batch_size = 5000
    
    try:
        db = get_db()
        
        # בדיקת שתי הקולקציות
        collections_to_check = ['code_snippets', 'large_files']
        
        for coll_name in collections_to_check:
            collection = db[coll_name]
            
            # ספירת מסמכים לפני המיגרציה
            missing_count_before = collection.count_documents({"is_active": {"$exists": False}})
            total_count = collection.count_documents({})
            
            results[coll_name] = {
                "total_documents": total_count,
                "missing_before_migration": missing_count_before,
            }
            
            if action == 'migrate' and missing_count_before > 0:
                # מיגרציה עם באטצ'ינג אמיתי:
                # MongoDB update_many לא תומך ב-limit, אז נשתמש ב-find + update עם $in
                from bson import ObjectId
                
                # שליפת IDs של מסמכים שחסר להם is_active (מוגבל לבאטש)
                docs_to_update = list(collection.find(
                    {"is_active": {"$exists": False}},
                    {"_id": 1},
                ).limit(batch_size))
                
                ids_to_update = [doc["_id"] for doc in docs_to_update]
                
                if ids_to_update:
                    # עדכון רק המסמכים שנבחרו
                    result = collection.update_many(
                        {"_id": {"$in": ids_to_update}},
                        {"$set": {"is_active": True}},
                    )
                    results[coll_name]["migrated_count"] = result.modified_count
                else:
                    results[coll_name]["migrated_count"] = 0
                
                results[coll_name]["action"] = "migrate"
                results[coll_name]["batch_size_used"] = batch_size
            else:
                results[coll_name]["migrated_count"] = 0
                results[coll_name]["action"] = "status_only"
            
            # ספירה מחודשת אחרי המיגרציה (לדיוק בסיכום)
            missing_count_after = collection.count_documents({"is_active": {"$exists": False}})
            has_is_active_count = collection.count_documents({"is_active": {"$exists": True}})
            
            results[coll_name]["missing_after_migration"] = missing_count_after
            results[coll_name]["with_is_active"] = has_is_active_count
            results[coll_name]["percentage_fixed"] = round((has_is_active_count / total_count * 100) if total_count > 0 else 100, 2)
        
        # סיכום כללי - משתמש בספירות אחרי המיגרציה
        total_missing_after = sum(r.get("missing_after_migration", 0) for r in results.values() if isinstance(r, dict))
        total_migrated = sum(r.get("migrated_count", 0) for r in results.values() if isinstance(r, dict))
        
        results["summary"] = {
            "total_missing_after_migration": total_missing_after,
            "total_migrated_this_call": total_migrated,
            "ready_for_optimized_queries": total_missing_after == 0,
            "batch_size": batch_size,
            "next_step": (
                "✅ כל המסמכים מכילים is_active - אפשר לעדכן את השאילתות לפילטר ישיר!"
                if total_missing_after == 0
                else f"⚠️ עדיין יש {total_missing_after} מסמכים ללא is_active. הרץ ?action=migrate שוב."
            ),
        }
        
        if action == 'migrate':
            results["summary"]["action_taken"] = "migrate"
            if total_missing_after > 0:
                results["summary"]["recommendation"] = (
                    f"המשך להריץ ?action=migrate עד שכל המסמכים יתוקנו. "
                    f"תיקנתי {total_migrated} מסמכים בקריאה זו, נותרו {total_missing_after}."
                )
        
        return jsonify(results)
        
    except Exception as e:
        logger.exception("fix_is_active_failed")
        return jsonify({"error": str(e), "status": "failed"}), 500


@app.route('/admin/diagnose-slow-queries')
@admin_required
def diagnose_slow_queries():
    """
    אבחון מפורט של בעיית השאילתות האיטיות.
    מציג:
    1. מצב האינדקסים
    2. כמה מסמכים חסר להם is_active
    3. דוגמת explain על שאילתה טיפוסית
    """
    import json
    from bson import json_util
    
    results = {"diagnosis": {}, "indexes": {}, "explain_test": {}}
    
    try:
        db = get_db()
        collection = db.code_snippets
        
        # 1. מצב האינדקסים
        indexes = list(collection.list_indexes())
        results["indexes"] = {
            "count": len(indexes),
            "list": json.loads(json_util.dumps(indexes)),
        }
        
        # 2. בדיקת מסמכים חסרי is_active
        missing_is_active = collection.count_documents({"is_active": {"$exists": False}})
        total = collection.count_documents({})
        results["diagnosis"]["missing_is_active"] = missing_is_active
        results["diagnosis"]["total_documents"] = total
        results["diagnosis"]["percentage_with_is_active"] = round(((total - missing_is_active) / total * 100) if total > 0 else 100, 2)
        
        # 3. בדיקת explain על שאילתה טיפוסית
        # לאחר המיגרציה: משתמשים בפילטר פשוט וידידותי לאינדקסים
        slow_query = {"is_active": True}
        
        # explain באמצעות db.command (תואם PyMongo 4.x)
        try:
            explain_slow = db.command(
                "explain",
                {"find": "code_snippets", "filter": slow_query},
                verbosity="queryPlanner"
            )
            winning_plan = explain_slow.get("queryPlanner", {}).get("winningPlan", {})
            slow_result = {
                "query": str(slow_query),
                "winning_plan_stage": winning_plan.get("stage", "UNKNOWN"),
                "index_used": winning_plan.get("indexName"),
                "full_explain": json.loads(json_util.dumps(winning_plan)),
            }
            # שמירה על מפתח חדש + תאימות לאחור (כדי לא לשבור מי שעוקב אחרי ה-json)
            results["explain_test"]["slow_query_direct"] = slow_result
            results["explain_test"]["slow_query_with_or"] = slow_result
        except Exception as e:
            err_obj = {"error": str(e)}
            results["explain_test"]["slow_query_direct"] = err_obj
            results["explain_test"]["slow_query_with_or"] = err_obj
        
        # explain על שאילתה מהירה (פילטר ישיר)
        fast_query = {"is_active": True}
        try:
            explain_fast = db.command(
                "explain",
                {"find": "code_snippets", "filter": fast_query},
                verbosity="queryPlanner"
            )
            winning_plan = explain_fast.get("queryPlanner", {}).get("winningPlan", {})
            results["explain_test"]["fast_query_direct"] = {
                "query": str(fast_query),
                "winning_plan_stage": winning_plan.get("stage", "UNKNOWN"),
                "index_used": winning_plan.get("indexName"),
                "full_explain": json.loads(json_util.dumps(winning_plan)),
            }
        except Exception as e:
            results["explain_test"]["fast_query_direct"] = {"error": str(e)}
        
        # 4. המלצות
        results["recommendations"] = []
        
        if missing_is_active > 0:
            results["recommendations"].append({
                "priority": "CRITICAL",
                "issue": f"יש {missing_is_active} מסמכים ללא שדה is_active",
                "solution": "הרץ /admin/fix-is-active?action=migrate כדי להוסיף is_active לכל המסמכים",
            })
        
        try:
            if results["explain_test"].get("slow_query_direct", {}).get("winning_plan_stage") == "COLLSCAN":
                results["recommendations"].append({
                    "priority": "HIGH",
                    "issue": "נמצא COLLSCAN ב-explain (אין שימוש באינדקס)",
                    "solution": "ודא שהשאילתה משתמשת בפילטרים שמובילים את האינדקס (למשל user_id+is_active) ושקיים אינדקס מתאים",
                })
        except Exception:
            pass
        
        if missing_is_active == 0:
            results["recommendations"].append({
                "priority": "INFO",
                "status": "✅ כל המסמכים מכילים is_active!",
                "next_step": "עכשיו צריך לעדכן את הקוד להשתמש בפילטר ישיר במקום $or",
            })
        
        return jsonify(results)
        
    except Exception as e:
        logger.exception("diagnose_slow_queries_failed")
        return jsonify({"error": str(e), "status": "failed"}), 500


@app.route('/admin/fix-all-now')
@admin_required
def fix_all_now():
    """
    🚀 תיקון חד-פעמי מלא:
    1. תיקון כל המסמכים החסרים (is_active)
    2. מחיקת האינדקס ההפוך
    3. יצירת האינדקס הנכון
    """
    import json
    from bson import json_util
    
    results = {"steps": []}
    
    try:
        from pymongo import IndexModel, ASCENDING, DESCENDING
        
        db = get_db()
        
        # === שלב 1: תיקון המסמכים החסרים ===
        for coll_name in ['code_snippets', 'large_files']:
            collection = db[coll_name]
            missing_before = collection.count_documents({"is_active": {"$exists": False}})
            
            if missing_before > 0:
                result = collection.update_many(
                    {"is_active": {"$exists": False}},
                    {"$set": {"is_active": True}},
                )
                results["steps"].append({
                    "action": f"fix_missing_is_active_{coll_name}",
                    "status": "✅ success",
                    "documents_fixed": result.modified_count,
                })
            else:
                results["steps"].append({
                    "action": f"fix_missing_is_active_{coll_name}",
                    "status": "✅ already clean",
                    "documents_fixed": 0,
                })
        
        # === שלב 2: מחיקת אינדקסים ישנים/מתנגשים ===
        collection = db.code_snippets
        old_index_names = ["active_recent_idx", "active_recent_v2"]  # שמות ישנים למחיקה
        
        for old_index_name in old_index_names:
            try:
                collection.drop_index(old_index_name)
                results["steps"].append({
                    "action": "drop_old_index",
                    "index_name": old_index_name,
                    "status": "✅ dropped",
                })
            except Exception as e:
                err_str = str(e).lower()
                if "not found" in err_str or "doesn't exist" in err_str:
                    pass  # לא קיים, זה בסדר
                else:
                    results["steps"].append({
                        "action": "drop_old_index",
                        "index_name": old_index_name,
                        "status": f"❌ error: {str(e)}",
                    })
        
        # === שלב 3: יצירת האינדקס הנכון ===
        new_index_name = "active_recent_fixed"
        collection = db.code_snippets
        
        # מחיקת האינדקס הישן אם קיים (יכול להיות בסדר הלא נכון)
        try:
            collection.drop_index(new_index_name)
            results["steps"].append({
                "action": "drop_old_fixed_index",
                "index_name": new_index_name,
                "status": "✅ dropped old version",
            })
        except Exception:
            pass  # לא קיים, זה בסדר
        
        try:
            # ⚠️ חשוב: שימוש ב-create_index עם רשימת tuples (לא dict!) כדי לשמור על הסדר
            # is_active חייב להיות ראשון!
            collection.create_index(
                [("is_active", 1), ("created_at", -1)],
                name=new_index_name,
                background=True
            )
            results["steps"].append({
                "action": "create_correct_index",
                "index_name": new_index_name,
                "key_order": [("is_active", 1), ("created_at", -1)],
                "status": "✅ created with correct order",
            })
        except Exception as e:
            err_str = str(e)
            if "already exists" in err_str.lower() or "IndexOptionsConflict" in err_str:
                results["steps"].append({
                    "action": "create_correct_index",
                    "index_name": new_index_name,
                    "status": "✅ already exists",
                })
            else:
                results["steps"].append({
                    "action": "create_correct_index",
                    "index_name": new_index_name,
                    "status": f"❌ error: {str(e)}",
                })
        
        # === סיכום ===
        # בדיקה סופית - בודק את שתי הקולקציות
        missing_code_snippets = db.code_snippets.count_documents({"is_active": {"$exists": False}})
        missing_large_files = db.large_files.count_documents({"is_active": {"$exists": False}})
        total_missing_after = missing_code_snippets + missing_large_files
        
        indexes_after = list(db.code_snippets.list_indexes())
        
        # מציאת האינדקס החדש
        new_index_info = None
        for idx in indexes_after:
            if idx.get("name") == new_index_name:
                new_index_info = idx
                break
        
        results["final_status"] = {
            "missing_is_active_code_snippets": missing_code_snippets,
            "missing_is_active_large_files": missing_large_files,
            "total_missing_is_active": total_missing_after,
            "new_index_exists": new_index_info is not None,
            "new_index_key_order": dict(new_index_info.get("key", {})) if new_index_info else None,
            "success": total_missing_after == 0 and new_index_info is not None,
        }
        
        if results["final_status"]["success"]:
            results["message"] = "🎉 הכל תוקן! האינדקס בסדר הנכון והנתונים מלאים."
        else:
            results["message"] = "⚠️ חלק מהתיקונים לא הצליחו. בדוק את הפרטים."
        
        return jsonify(results)
        
    except Exception as e:
        logger.exception("fix_all_now_failed")
        return jsonify({"error": str(e), "status": "failed"}), 500


@app.route('/admin/resolve-naming-conflicts')
@admin_required
def resolve_naming_conflicts():
    """
    🛠️ תיקון אינדקסים לפי הדרישות החדשות:
    
    1. code_snippets: מחיקת אינדקס מתנגש ויצירת user_file_version_desc
       {file_name: 1, user_id: 1, version: -1}
    2. job_trigger_requests: מחיקת status_idx ויצירת אינדקס משולב
       {status: 1, created_at: -1}
    3. scheduler_jobs: יצירת אינדקס על next_run_time
       {next_run_time: 1}
    4. code_snippets: וידוא active_recent_fixed בסדר הנכון
       {is_active: 1, created_at: -1}
    """
    import json
    from bson import json_util
    
    results = {"steps": [], "collections_fixed": []}
    
    try:
        from pymongo import IndexModel, ASCENDING, DESCENDING
        
        db = get_db()
        
        # === 1. code_snippets: user_file_version_desc ===
        collection = db.code_snippets
        target_name = "user_file_version_desc"
        
        # שלב 1: מחיקה מפורשת של האינדקס הקיים (גם אם יש לו את אותו השם אבל סדר שונה)
        try:
            collection.drop_index(target_name)
            results["steps"].append({
                "action": "drop_existing_index",
                "collection": "code_snippets",
                "index_name": target_name,
                "status": "✅ dropped (was in wrong order: user_id, file_name, version)"
            })
        except Exception as e:
            err = str(e)
            if "not found" in err.lower() or "ns not found" in err.lower():
                results["steps"].append({
                    "action": "drop_existing_index",
                    "collection": "code_snippets",
                    "index_name": target_name,
                    "status": "ℹ️ index did not exist, proceeding to create"
                })
            else:
                results["steps"].append({
                    "action": "drop_existing_index",
                    "collection": "code_snippets",
                    "index_name": target_name,
                    "status": f"⚠️ drop error (may not exist): {err}"
                })
        
        # שלב 2: יצירת האינדקס בסדר הנכון - file_name ראשון!
        # הסדר הנכון שה-Manager מצפה לו: file_name, user_id, version
        try:
            collection.create_index(
                [("file_name", ASCENDING), ("user_id", ASCENDING), ("version", DESCENDING)],
                name=target_name,
                background=True
            )
            results["steps"].append({
                "action": "create_index",
                "collection": "code_snippets",
                "index_name": target_name,
                "key_order": {"file_name": 1, "user_id": 1, "version": -1},
                "expected_order": "file_name → user_id → version (CORRECT)",
                "status": "✅ created with correct order"
            })
            results["collections_fixed"].append("code_snippets:user_file_version_desc")
        except Exception as e:
            err = str(e)
            results["steps"].append({
                "action": "create_index",
                "collection": "code_snippets",
                "index_name": target_name,
                "status": f"❌ error: {err}"
            })
        
        # === 2. job_trigger_requests: מחיקת status_idx ויצירת אינדקס משולב ===
        try:
            jtr_collection = db.job_trigger_requests
            
            # מחיקת האינדקס הישן
            try:
                jtr_collection.drop_index("status_idx")
                results["steps"].append({
                    "action": "drop_index",
                    "collection": "job_trigger_requests",
                    "index_name": "status_idx",
                    "status": "✅ dropped"
                })
            except Exception as e:
                err = str(e).lower()
                if "not found" in err or "doesn't exist" in err:
                    results["steps"].append({
                        "action": "drop_index",
                        "collection": "job_trigger_requests",
                        "index_name": "status_idx",
                        "status": "⚠️ not found (already dropped?)"
                    })
                else:
                    results["steps"].append({
                        "action": "drop_index",
                        "collection": "job_trigger_requests",
                        "index_name": "status_idx",
                        "status": f"❌ error: {str(e)}"
                    })
            
            # יצירת האינדקס המשולב החדש
            new_jtr_index = "status_created_idx"
            try:
                jtr_collection.create_index(
                    [("status", ASCENDING), ("created_at", DESCENDING)],
                    name=new_jtr_index,
                    background=True
                )
                results["steps"].append({
                    "action": "create_index",
                    "collection": "job_trigger_requests",
                    "index_name": new_jtr_index,
                    "key_order": {"status": 1, "created_at": -1},
                    "status": "✅ created"
                })
                results["collections_fixed"].append("job_trigger_requests:status_created_idx")
            except Exception as e:
                err = str(e)
                if "already exists" in err.lower() or "IndexOptionsConflict" in err:
                    results["steps"].append({
                        "action": "create_index",
                        "collection": "job_trigger_requests",
                        "index_name": new_jtr_index,
                        "status": "✅ already exists"
                    })
                else:
                    results["steps"].append({
                        "action": "create_index",
                        "collection": "job_trigger_requests",
                        "index_name": new_jtr_index,
                        "status": f"❌ error: {err}"
                    })
        except Exception as e:
            results["steps"].append({
                "action": "job_trigger_requests_setup",
                "status": f"❌ collection error: {str(e)}"
            })
        
        # === 3. scheduler_jobs: אינדקס על next_run_time ===
        try:
            sched_collection = db.scheduler_jobs
            sched_index_name = "next_run_time_idx"
            
            try:
                sched_collection.create_index(
                    [("next_run_time", ASCENDING)],
                    name=sched_index_name,
                    background=True
                )
                results["steps"].append({
                    "action": "create_index",
                    "collection": "scheduler_jobs",
                    "index_name": sched_index_name,
                    "key_order": {"next_run_time": 1},
                    "status": "✅ created"
                })
                results["collections_fixed"].append("scheduler_jobs:next_run_time_idx")
            except Exception as e:
                err = str(e)
                if "already exists" in err.lower() or "IndexOptionsConflict" in err:
                    results["steps"].append({
                        "action": "create_index",
                        "collection": "scheduler_jobs",
                        "index_name": sched_index_name,
                        "status": "✅ already exists"
                    })
                else:
                    results["steps"].append({
                        "action": "create_index",
                        "collection": "scheduler_jobs",
                        "index_name": sched_index_name,
                        "status": f"❌ error: {err}"
                    })
        except Exception as e:
            results["steps"].append({
                "action": "scheduler_jobs_setup",
                "status": f"❌ collection error: {str(e)}"
            })
        
        # === 4. code_snippets: וידוא active_recent_fixed ===
        collection = db.code_snippets
        active_idx_name = "active_recent_fixed"
        
        # מחיקה אם קיים (כדי ליצור מחדש בסדר הנכון)
        try:
            collection.drop_index(active_idx_name)
            results["steps"].append({
                "action": "drop_for_recreate",
                "collection": "code_snippets",
                "index_name": active_idx_name,
                "status": "✅ dropped for recreation"
            })
        except Exception:
            pass  # לא קיים, זה בסדר
        
        try:
            # is_active חייב להיות ראשון!
            collection.create_index(
                [("is_active", ASCENDING), ("created_at", DESCENDING)],
                name=active_idx_name,
                background=True
            )
            results["steps"].append({
                "action": "create_index",
                "collection": "code_snippets",
                "index_name": active_idx_name,
                "key_order": {"is_active": 1, "created_at": -1},
                "status": "✅ created with correct order"
            })
            results["collections_fixed"].append("code_snippets:active_recent_fixed")
        except Exception as e:
            err = str(e)
            results["steps"].append({
                "action": "create_index",
                "collection": "code_snippets",
                "index_name": active_idx_name,
                "status": f"❌ error: {err}"
            })
        
        # === סיכום: רשימת אינדקסים עדכנית ===
        results["current_indexes"] = {}
        
        for coll_name in ["code_snippets", "job_trigger_requests", "scheduler_jobs"]:
            try:
                coll = db[coll_name]
                indexes = list(coll.list_indexes())
                results["current_indexes"][coll_name] = json.loads(json_util.dumps(indexes))
            except Exception as e:
                results["current_indexes"][coll_name] = {"error": str(e)}
        
        results["message"] = f"✅ תיקון הסתיים. {len(results['collections_fixed'])} אינדקסים נוצרו/עודכנו."
        results["success"] = len([s for s in results["steps"] if "✅" in s.get("status", "")]) > 0
        
        return jsonify(results)
        
    except Exception as e:
        logger.exception("resolve_naming_conflicts_failed")
        return jsonify({"error": str(e), "status": "failed"}), 500


@app.route('/admin/check-op')
@admin_required
def check_mongo_ops():
    """
    🔍 בדיקת פעולות MongoDB שרצות כרגע (כמו בניית אינדקסים).
    
    מחזיר מידע על:
    - פעולות בניית אינדקסים (Index Builds)
    - זמן ריצה של כל פעולה
    
    📝 הערה: גרסה תואמת ל-Atlas Shared Tier (ללא $all).
    """
    try:
        db = get_db()
        
        # פקודה בסיסית שעובדת ב-Atlas Shared Tier
        ops = db.command({"currentOp": 1, "active": True})
        
        in_progress = []
        for op in ops.get('inprog', []):
            # טיפול בטוח ב-command למניעת TypeError/AttributeError
            # (command יכול להיות None, לא רק missing)
            command = op.get('command') or {}
            msg = op.get('msg', '')
            
            # זיהוי בניית אינדקסים או פקודות רלוונטיות
            is_index = "createIndexes" in command or "Index Build" in msg
            
            if is_index or msg:
                in_progress.append({
                    "msg": msg or "Processing...",
                    "collection": command.get("createIndexes") or "N/A",
                    "progress": op.get('progress', {}),
                    "secs_running": op.get('secs_running'),
                    "opid": op.get('opid')
                })
        
        return jsonify({
            "status": "success",
            "active_index_builds": in_progress,
            "raw_ops_count": len(ops.get('inprog', []))
        })
    except Exception as e:
        logger.exception("check_mongo_ops_failed")
        return jsonify({
            "status": "error", 
            "message": f"Atlas/Auth Error: {str(e)}"
        }), 500


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

    # בניית ביטוי חיפוש:
    # - אם המשתמש ביקש REGEX: נשמור על $regex (ללא $text)
    # - אחרת: נעדיף $text (מהיר יותר וידידותי לאינדקסים) + נשתמש ב-regexFind רק לצורך snippet/highlight
    pattern = query if is_regex else re.escape(query)

    match_stage: Dict[str, Any] = {
        'user_id': user_id,
        'is_active': True,
    }
    if is_regex:
        match_stage['code'] = {
            '$regex': pattern,
            '$options': 'i',  # חיפוש לא רגיש לאותיות גדולות/קטנות
        }
    else:
        match_stage['$text'] = {'$search': query}

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

    # חשוב: בחיפוש רוצים להחזיר snippet קצר ולא למשוך את כל `code` לפייתון.
    # נחלץ match ראשון + snippet ב-DB (best-effort). אם פונקציות אגרגציה חסרות,
    # ניפול ל-fallback הישן (כבד יותר) כדי לשמור פונקציונליות.
    pipeline = [
        {'$match': match_stage},
        {'$sort': {'file_name': 1, 'version': -1}},
        {'$group': {'_id': '$file_name', 'latest': {'$first': '$$ROOT'}}},
        {'$replaceRoot': {'newRoot': '$latest'}},
        # חישוב match ראשון + snippet סביבו (בערך 200 תווים סביב נקודת התאמה)
        {'$addFields': {
            '_m': {'$regexFind': {'input': '$code', 'regex': pattern, 'options': 'i'}},
        }},
        {'$addFields': {
            '_has_code_match': {'$gt': [{'$strLenBytes': {'$ifNull': ['$_m.match', '']}}, 0]},
            '_match_idx': {'$ifNull': ['$_m.idx', 0]},
            '_match_len': {'$strLenBytes': {'$ifNull': ['$_m.match', '']}},
        }},
        {'$addFields': {
            # אם אין התאמה בקוד (למשל התאמה הייתה בשם קובץ/תיאור/תגיות דרך $text),
            # נציג Preview בסיסי מתחילת הקוד כדי לא ליצור highlight שבור/מטעה.
            '_snippet_start': {
                '$cond': {
                    'if': '$_has_code_match',
                    'then': {'$max': [0, {'$subtract': ['$_match_idx', 50]}]},
                    'else': 0,
                }
            },
        }},
        {'$addFields': {
            'snippet_preview': {'$substrBytes': ['$code', '$_snippet_start', 200]},
            # מטא-דאטה קל (למסמכים חדשים נשמר כבר; למסמכים ישנים מחשבים בריצה)
            'file_size': {'$ifNull': ['$file_size', {'$strLenBytes': '$code'}]},
            'lines_count': {'$ifNull': ['$lines_count', {'$size': {'$split': ['$code', '\n']}}]},
            # highlight range יחיד (יחסי ל-snippet) עבור התאמה הראשונה, רק אם באמת נמצאה התאמה בקוד
            'highlight_ranges': {
                '$cond': {
                    'if': '$_has_code_match',
                    'then': [[
                        {'$max': [0, {'$subtract': ['$_match_idx', '$_snippet_start']}]},
                        {'$max': [0, {'$add': [{'$subtract': ['$_match_idx', '$_snippet_start']}, '$_match_len']}]},
                    ]],
                    'else': [],
                }
            },
        }},
        {'$project': {
            # אל תחזיר code מלא בחיפוש fallback
            'code': 0,
            # שדות עזר פנימיים
            '_m': 0,
            '_has_code_match': 0,
            '_match_idx': 0,
            '_match_len': 0,
            '_snippet_start': 0,
        }},
        {'$sort': {'updated_at': -1}},
        {'$limit': total_limit},
    ]

    try:
        docs = list(db.code_snippets.aggregate(pipeline, allowDiskUse=True))
        from types import SimpleNamespace
        results: list = []
        for doc in docs:
            if not isinstance(doc, dict):
                continue
            # score גס ב-fallback: אין לנו חישוב מושלם בלי לקרוא את כל התוכן
            score = 1.0
            try:
                score = float(doc.get('relevance_score') or 1.0)
            except Exception:
                score = 1.0
            results.append(SimpleNamespace(
                file_name=str(doc.get('file_name') or ''),
                programming_language=str(doc.get('programming_language') or ''),
                tags=list(doc.get('tags') or []),
                created_at=doc.get('created_at') or datetime.now(timezone.utc),
                updated_at=doc.get('updated_at') or datetime.now(timezone.utc),
                version=int(doc.get('version') or 1),
                relevance_score=float(score),
                matches=[],
                snippet_preview=str(doc.get('snippet_preview') or ''),
                highlight_ranges=list(doc.get('highlight_ranges') or []),
                file_size=int(doc.get('file_size') or 0),
                lines_count=int(doc.get('lines_count') or 0),
            ))
        return results
    except Exception:
        # אם $text נכשל (למשל אין אינדקס טקסט), ננסה fallback ל-$regex על code בלבד
        # כדי לשמור על התנהגות חיפוש בסיסית.
        try:
            if (not is_regex) and isinstance(match_stage, dict) and ('$text' in match_stage):
                match_stage2 = dict(match_stage)
                match_stage2.pop('$text', None)
                match_stage2['code'] = {'$regex': pattern, '$options': 'i'}
                pipeline2 = list(pipeline)
                pipeline2[0] = {'$match': match_stage2}
                docs2 = list(db.code_snippets.aggregate(pipeline2, allowDiskUse=True))
                from types import SimpleNamespace
                results2: list = []
                for doc in docs2:
                    if not isinstance(doc, dict):
                        continue
                    score = 1.0
                    try:
                        score = float(doc.get('relevance_score') or 1.0)
                    except Exception:
                        score = 1.0
                    results2.append(SimpleNamespace(
                        file_name=str(doc.get('file_name') or ''),
                        programming_language=str(doc.get('programming_language') or ''),
                        tags=list(doc.get('tags') or []),
                        created_at=doc.get('created_at') or datetime.now(timezone.utc),
                        updated_at=doc.get('updated_at') or datetime.now(timezone.utc),
                        version=int(doc.get('version') or 1),
                        relevance_score=float(score),
                        matches=[],
                        snippet_preview=str(doc.get('snippet_preview') or ''),
                        highlight_ranges=list(doc.get('highlight_ranges') or []),
                        file_size=int(doc.get('file_size') or 0),
                        lines_count=int(doc.get('lines_count') or 0),
                    ))
                return results2
        except Exception:
            pass

        # fallback אחרון: שמירה על פונקציונליות גם אם Mongo לא תומך ב-$regexFind וכו'.
        try:
            old_pipeline = [
                {'$match': match_stage},
                {'$sort': {'file_name': 1, 'version': -1}},
                {'$group': {'_id': '$file_name', 'latest': {'$first': '$$ROOT'}}},
                {'$replaceRoot': {'newRoot': '$latest'}},
                {'$sort': {'updated_at': -1}},
                {'$limit': total_limit},
            ]
            docs = list(db.code_snippets.aggregate(old_pipeline, allowDiskUse=True))
        except Exception:
            return []
        from types import SimpleNamespace
        results: list = []
        # קומפילציה להדגשה ליטרלית בלבד (לא מחזירים את כל הקוד ללקוח)
        try:
            comp = re.compile(re.escape(query), re.IGNORECASE | re.MULTILINE)
        except Exception:
            comp = None
        for doc in docs:
            if not isinstance(doc, dict):
                continue
            code_text = str(doc.get('code') or '')
            snippet = ''
            highlight_ranges = []
            if comp is not None:
                m = comp.search(code_text)
                if m:
                    start = max(0, m.start() - 50)
                    end = min(len(code_text), m.end() + 50)
                    snippet = code_text[start:end]
                    highlight_ranges = [(m.start() - start, m.end() - start)]
            results.append(SimpleNamespace(
                file_name=str(doc.get('file_name') or ''),
                programming_language=str(doc.get('programming_language') or ''),
                tags=list(doc.get('tags') or []),
                created_at=doc.get('created_at') or datetime.now(timezone.utc),
                updated_at=doc.get('updated_at') or datetime.now(timezone.utc),
                version=int(doc.get('version') or 1),
                relevance_score=1.0,
                matches=[],
                snippet_preview=snippet,
                highlight_ranges=highlight_ranges,
                file_size=int(doc.get('file_size') or 0),
                lines_count=int(doc.get('lines_count') or 0),
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

        # Resolve DB ids for links + מטא-דאטה (best-effort; don't fail search if DB unavailable)
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

        def _resolve_doc_meta(fn: str) -> Dict[str, Any]:
            """החזרת {_id, file_size, lines_count} עבור הקובץ (גרסה אחרונה פעילה)."""
            if db is None:
                return {}
            try:
                return dict(db.code_snippets.find_one(
                    {
                        'user_id': user_id,
                        'file_name': fn,
                        'is_active': {'$ne': False},
                    },
                    {
                        '_id': 1,
                        'file_size': 1,
                        'lines_count': 1,
                    },
                    sort=[('version', DESCENDING), ('updated_at', DESCENDING), ('_id', DESCENDING)],
                ) or {})
            except Exception:
                return {}

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
                        _resolve_doc_meta(fn)
                    ))(_safe_getattr(r, 'file_name', '')),
                    'file_name': _safe_getattr(r, 'file_name', ''),
                    'language': _safe_getattr(r, 'programming_language', ''),
                    'tags': _safe_getattr(r, 'tags', []) or [],
                    'score': round(float(_safe_getattr(r, 'relevance_score', 0.0) or 0.0), 2),
                    'snippet': (_safe_getattr(r, 'snippet_preview', '') or '')[:200],
                    'highlights': _safe_getattr(r, 'highlight_ranges', []) or [],
                    'matches': (_safe_getattr(r, 'matches', []) or [])[:5],
                    'updated_at': safe_iso((_safe_getattr(r, 'updated_at', datetime.now(timezone.utc)) or datetime.now(timezone.utc)), field='updated_at'),
                    # עקביות: לא מחזירים `code` או `content`. מחזירים מטא בלבד.
                    # נעדיף שדות שמגיעים מה-result (במנוע/ב-fallback) ואם חסר – ניקח מה-DB.
                    'file_size': int(_safe_getattr(r, 'file_size', 0) or 0),
                    'lines_count': int(_safe_getattr(r, 'lines_count', 0) or 0),
                    # תאימות לאחור: `size` נשאר, אבל עכשיו הוא size-bytes ולא אורך תוכן שנשלף.
                    'size': int(_safe_getattr(r, 'file_size', 0) or 0),
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
    """בדיקת עומק מהירה (תחת 300ms) עבור Load Balancer וניטור חיצוני."""
    start = _time.perf_counter()
    payload: Dict[str, Any] = {
        "status": "ok",
        "mongo": "unknown",
        "indexes": 0,
        "latency_ms": 0.0,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "static_version": _STATIC_VERSION,
        "static_version_source": _STATIC_VERSION_SOURCE,
    }
    errors: List[str] = []
    latency_breakdown: Dict[str, float] = {}
    avg_rt_ms = 0.0
    mongo_latency_ms: float | None = None

    # זמן תגובה ממוצע של שכבת ה-Web (EWMA) – מסייע לזהות רגרסיה כללית
    try:
        avg_rt_ms = max(0.0, float(get_avg_response_time_seconds()) * 1000.0)
        if avg_rt_ms > 0.0:
            latency_breakdown["app_avg"] = round(avg_rt_ms, 2)
    except Exception:
        pass

    db_ref = db if db is not None else None
    if not MONGODB_URL:
        payload["status"] = "error"
        payload["mongo"] = "missing"
        errors.append("mongo_url_missing")
    else:
        if db_ref is None:
            try:
                db_ref = get_db()
            except Exception:
                db_ref = None
                payload["mongo"] = "error"
                errors.append("mongo_init_failed")
        if db_ref is not None:
            # פינג קצר למסד הנתונים
            try:
                ping_start = _time.perf_counter()
                db_ref.command('ping')
                mongo_latency_ms = max(0.0, float(_time.perf_counter() - ping_start) * 1000.0)
                latency_breakdown["mongo_ping"] = round(mongo_latency_ms, 2)
                payload["mongo"] = "connected"
            except Exception:
                payload["mongo"] = "error"
                errors.append("mongo_ping_failed")
            # ספירת אינדקסים קריטיים (עם cache קצר כדי לשמור על SLA של 300ms)
            try:
                indexes_count, indexes_duration = _sample_critical_index_count(db_ref)
                payload["indexes"] = int(indexes_count)
                if indexes_duration > 0.0:
                    latency_breakdown["indexes_scan"] = round(indexes_duration * 1000.0, 2)
            except Exception:
                payload["indexes"] = 0
                errors.append("index_sample_failed")

    payload["latency_ms"] = round(max(0.0, float((_time.perf_counter() - start) * 1000.0)), 2)
    if latency_breakdown:
        payload["latency_breakdown_ms"] = latency_breakdown
    if errors:
        payload["errors"] = errors
        if payload["status"] == "ok":
            payload["status"] = "error"
    status_code = 200 if payload["status"] == "ok" else 503
    try:
        ping_value = mongo_latency_ms if payload.get("mongo") == "connected" else None
        update_health_gauges(
            mongo_connected=payload.get("mongo") == "connected",
            ping_ms=ping_value,
            indexes_total=payload.get("indexes"),
            latency_ewma_ms=avg_rt_ms,
        )
    except Exception:
        pass
    return jsonify(payload), status_code


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

def get_language_icon(language: Optional[str]) -> str:
    """מחזיר אייקון עבור שפת תכנות/קטגוריה"""
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
        'env': '🔐',
        'dotenv': '🔐',
        'gitignore': '🚫',
        'dockerignore': '🚫',
        'text': '📄',
    }
    normalized = (language or '').strip().lower()
    return icons.get(normalized, '📄')


def resolve_file_language(language: Optional[str], file_name: str = "") -> str:
    """מחליט על שפה לתצוגה לפי שדה השפה והסיומת בפועל"""
    lang = (language or '').strip().lower()
    if (not lang or lang == 'text') and file_name:
        try:
            detected = detect_language_from_filename(file_name)
        except Exception:
            detected = ''
        lang = (detected or '').strip().lower()
    return lang or 'text'


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

# מסנן Jinja לתאימות למדריכים/תבניות: alias ל-datetime_display
@app.template_filter('format_datetime')
def jinja_format_datetime(value) -> str:
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

@app.route('/', methods=['HEAD'])
@_limiter_exempt()
def index_head():
    """בדיקת דופק קלה ל-HEAD / בלי IO/Template.

    חשוב: Flask ממפה HEAD אוטומטית ל-GET ולכן בלי מסלול ייעודי היינו מריצים
    את `index()` (כולל קריאת uptime חיצונית) גם עבור בדיקות דופק/Health.
    """
    return Response(status=200)


@app.route('/', methods=['GET'])
@_limiter_exempt()
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
        'has_seen_welcome_modal': bool((user_doc or {}).get('has_seen_welcome_modal', False)),
        'is_admin': is_admin(user_id),
        'is_premium': is_premium(user_id),
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
            'has_seen_welcome_modal': bool(user.get('has_seen_welcome_modal', False)),
            'is_admin': is_admin(user_id_int),
            'is_premium': is_premium(user_id_int),
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


_TIMELINE_GROUP_META: Dict[str, Dict[str, str]] = {
    'files': {'title': 'קבצים', 'icon': '📁', 'accent': 'timeline-accent-code'},
    'push': {'title': 'התראות פוש', 'icon': '📣', 'accent': 'timeline-accent-push'},
}
_TIMELINE_LIMITS = {'files': 12, 'push': 8}
_MIN_DT = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _normalize_dt(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except Exception:
            return None
    return None


def _format_relative(dt: Optional[datetime]) -> str:
    if not isinstance(dt, datetime):
        return "לא ידוע"
    try:
        return TimeUtils.format_relative_time(dt)
    except Exception:
        try:
            return dt.strftime('%d/%m/%Y %H:%M')
        except Exception:
            return "לא ידוע"


def _format_calendar_hint(dt: Optional[datetime]) -> str:
    if not isinstance(dt, datetime):
        return ""
    try:
        localized = dt.astimezone(timezone.utc)
    except Exception:
        localized = dt
    return localized.strftime('%d/%m %H:%M')


def _finalize_events(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    finalized: List[Dict[str, Any]] = []
    for ev in items:
        cleaned = dict(ev)
        cleaned.pop('_dt', None)
        finalized.append(cleaned)
    return finalized


def _summarize_group(title: str, total_count: int, recent_count: int) -> str:
    if total_count <= 0:
        return f"אין פעילות {title.lower()} עדיין"
    if recent_count > 0:
        return f"{recent_count} פעולות {title.lower()} השבוע"
    return f"{total_count} פעולות אחרונות"


def _extract_note_preview(note_content: str, limit: int = 80) -> str:
    text = (note_content or "").strip()
    if not text:
        return "פתק ללא תוכן"
    preview = text.splitlines()[0].strip()
    if len(preview) > limit:
        return preview[:limit - 1].rstrip() + "…"
    return preview


def _lookup_notes_map(db, user_id: int, note_ids: List[Any]) -> Dict[str, Dict[str, Any]]:
    note_ids_clean = [str(n) for n in (note_ids or []) if str(n).strip()]
    if not note_ids_clean:
        return {}
    object_ids: List[Any] = []
    plain_ids: List[str] = []
    for note_id in note_ids_clean:
        try:
            object_ids.append(ObjectId(note_id))
        except Exception:
            plain_ids.append(note_id)
    projection = {'content': 1, 'file_id': 1, 'updated_at': 1, 'color': 1}
    results: Dict[str, Dict[str, Any]] = {}
    try:
        if object_ids:
            cursor = db.sticky_notes.find({'_id': {'$in': object_ids}, 'user_id': int(user_id)}, projection)
            for doc in cursor or []:
                results[str(doc.get('_id'))] = doc
    except Exception:
        pass
    try:
        if plain_ids:
            cursor = db.sticky_notes.find({'_id': {'$in': plain_ids}, 'user_id': int(user_id)}, projection)
            for doc in cursor or []:
                results[str(doc.get('_id'))] = doc
    except Exception:
        pass
    return results


def _lookup_files_map(db, file_ids: List[Any]) -> Dict[str, str]:
    unique_ids = []
    seen = set()
    for fid in file_ids or []:
        if not fid:
            continue
        val = str(fid)
        if val in seen:
            continue
        seen.add(val)
        unique_ids.append(val)
    object_ids: List[Any] = []
    for fid in unique_ids:
        try:
            object_ids.append(ObjectId(fid))
        except Exception:
            continue
    if not object_ids:
        return {}
    try:
        cursor = db.code_snippets.find({'_id': {'$in': object_ids}}, {'file_name': 1})
    except Exception:
        return {}
    files: Dict[str, str] = {}
    try:
        for doc in cursor or []:
            files[str(doc.get('_id'))] = doc.get('file_name') or 'ללא שם'
    except Exception:
        return {}
    return files


def _build_timeline_event(
    group: str,
    *,
    title: str,
    subtitle: str,
    dt: Any,
    icon: str,
    badge: Optional[str] = None,
    badge_variant: Optional[str] = None,
    href: Optional[str] = None,
    status: Optional[str] = None,
    meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    normalized_dt = _normalize_dt(dt)
    return {
        '_dt': normalized_dt,
        'group': group,
        'icon': icon,
        'title': title,
        'subtitle': subtitle or '',
        'badge': badge,
        'badge_variant': badge_variant,
        'href': href,
        'status': status,
        'meta': meta or {},
        'timestamp': normalized_dt.isoformat() if normalized_dt else None,
        'relative_time': _format_relative(normalized_dt),
        'accent': _TIMELINE_GROUP_META.get(group, {}).get('accent', ''),
    }


def _build_activity_timeline(db, user_id: int, active_query: Optional[Dict[str, Any]] = None, *, now: Optional[datetime] = None) -> Dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    recent_cutoff = now - timedelta(days=7)
    events: Dict[str, List[Dict[str, Any]]] = {k: [] for k in _TIMELINE_GROUP_META}
    errors: List[str] = []
    files_recent_total = 0

    # Files activity
    try:
        file_query = active_query or {
            'user_id': user_id,
            'is_active': True,
        }
        # טווח 7 ימים: הכפתור "טען עוד" אמור להרחיב עד שבוע אחורה בלבד.
        # נשתמש ב-$or כדי לכסות מקרים שבהם updated_at חסר/None ונשענים על created_at.
        file_query_recent = dict(file_query) if isinstance(file_query, dict) else {'user_id': user_id, 'is_active': True}
        file_query_recent['$or'] = [
            {'updated_at': {'$gte': recent_cutoff}},
            {'updated_at': {'$exists': False}, 'created_at': {'$gte': recent_cutoff}},
            {'updated_at': None, 'created_at': {'$gte': recent_cutoff}},
        ]
        try:
            files_recent_total = int(db.code_snippets.count_documents(file_query_recent))
        except Exception:
            files_recent_total = 0

        cursor = db.code_snippets.find(
            file_query_recent,
            {'file_name': 1, 'programming_language': 1, 'updated_at': 1, 'created_at': 1, 'version': 1, 'description': 1},
        ).sort('updated_at', DESCENDING).limit(_TIMELINE_LIMITS['files'])
    except Exception:
        cursor = []
        errors.append('files')
    for doc in cursor or []:
        dt = doc.get('updated_at') or doc.get('created_at')
        version = doc.get('version') or 1
        is_new = version == 1
        action = "נוצר" if is_new else "עודכן"
        file_name = doc.get('file_name') or "ללא שם"
        language = resolve_file_language(doc.get('programming_language'), file_name)
        title = f"{action} {file_name}"
        details: List[str] = []
        if doc.get('programming_language'):
            details.append(doc['programming_language'])
        elif language and language != 'text':
            details.append(language)
        if version:
            details.append(f"גרסה {version}")
        description = (doc.get('description') or "").strip()
        subtitle = description if description else (" · ".join(details) if details else "ללא פרטים נוספים")
        href = f"/file/{doc.get('_id')}"
        file_badge = doc.get('programming_language') or (language if language and language != 'text' else None)
        events['files'].append(
            _build_timeline_event(
                'files',
                title=title,
                subtitle=subtitle,
                dt=dt,
                icon=get_language_icon(language),
                badge=file_badge,
                badge_variant='code',
                href=href,
                meta={'details': " · ".join(details)},
            )
        )

    # Push/reminder events
    push_docs: List[Dict[str, Any]] = []
    try:
        cursor = db.note_reminders.find(
            {'user_id': user_id},
            {'note_id': 1, 'status': 1, 'remind_at': 1, 'updated_at': 1, 'ack_at': 1, 'last_push_success_at': 1},
        ).sort('updated_at', DESCENDING).limit(_TIMELINE_LIMITS['push'])
        push_docs = list(cursor or [])
    except Exception:
        errors.append('push')
    note_ids = [doc.get('note_id') for doc in push_docs if doc.get('note_id')]
    notes_map = _lookup_notes_map(db, user_id, note_ids)
    for doc in push_docs:
        note_id = str(doc.get('note_id', ''))
        note_doc = notes_map.get(note_id)
        note_preview = _extract_note_preview(note_doc.get('content', '')) if note_doc else "פתק ללא שם"
        remind_at = _normalize_dt(doc.get('remind_at'))
        last_push = _normalize_dt(doc.get('last_push_success_at'))
        ack_at = _normalize_dt(doc.get('ack_at'))
        status = str(doc.get('status') or 'pending').lower()
        if ack_at:
            badge, variant = "נסגר", "success"
            subtitle = "התזכורת טופלה"
            dt = ack_at
        elif last_push and (not remind_at or last_push >= remind_at):
            badge, variant = "נשלח", "success"
            subtitle = "התראה נשלחה"
            dt = last_push
        elif status == 'snoozed':
            badge, variant = "מושהה", "warning"
            subtitle = "נדחה על ידי המשתמש"
            dt = remind_at or doc.get('updated_at')
        elif remind_at and remind_at > now:
            badge, variant = "מתוכנן", "info"
            subtitle = f"תוזמן ל-{_format_calendar_hint(remind_at)}"
            dt = remind_at
        else:
            badge, variant = "ממתין", "warning"
            subtitle = "בהמתנה למשלוח"
            dt = remind_at or doc.get('updated_at')

        href = None
        file_id = note_doc.get('file_id') if note_doc else None
        if file_id:
            href = f"/file/{file_id}"

        events['push'].append(
            _build_timeline_event(
                'push',
                title=f"תזכורת לפתק {note_preview}",
                subtitle=subtitle,
                dt=dt,
                icon='📣',
                badge=badge,
                badge_variant=variant,
                href=href,
                status=status,
            )
        )

    # Sort groups and build summaries
    feed: List[Dict[str, Any]] = []
    filters: List[Dict[str, Any]] = [{'id': 'all', 'label': 'הכול', 'count': 0}]
    groups_payload: List[Dict[str, Any]] = []
    for group_id, meta in _TIMELINE_GROUP_META.items():
        sorted_items = sorted(events[group_id], key=lambda ev: ev.get('_dt') or _MIN_DT, reverse=True)
        events[group_id] = sorted_items
        feed.extend(sorted_items)
        recent_count = sum(1 for ev in sorted_items if isinstance(ev.get('_dt'), datetime) and ev['_dt'] >= recent_cutoff)
        group_payload: Dict[str, Any] = {
            'id': group_id,
            'title': meta['title'],
            'icon': meta['icon'],
            'summary': _summarize_group(meta['title'], len(sorted_items), recent_count),
            'events': _finalize_events(sorted_items),
        }
        if group_id == 'files':
            shown = len(sorted_items)
            total = max(0, int(files_recent_total or 0))
            group_payload['total_recent'] = total
            group_payload['shown'] = shown
            group_payload['has_more'] = bool(total > shown)
        groups_payload.append(group_payload)
        filters.append({'id': group_id, 'label': meta['title'], 'count': len(sorted_items)})

    feed_sorted = sorted(feed, key=lambda ev: ev.get('_dt') or _MIN_DT, reverse=True)
    filters[0]['count'] = len(feed_sorted)

    return {
        'groups': groups_payload,
        'feed': _finalize_events(feed_sorted[:30]),
        'filters': filters,
        'compact_limit': 5,
        'has_events': any(events[group] for group in events),
        'updated_at': now.isoformat(),
        'errors': errors,
    }


def _build_files_need_attention(
    db,
    user_id: int,
    max_items: int = 10,
    stale_days: int = 60,
    dismissed_ids: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    בונה נתונים עבור ווידג'ט "קבצים שדורשים טיפול".
    
    Args:
        db: חיבור למסד הנתונים
        user_id: מזהה המשתמש
        max_items: מקסימום פריטים להצגה בכל קבוצה
        stale_days: מספר ימים לאחריהם קובץ נחשב "לא עודכן זמן רב"
        dismissed_ids: רשימת מזהים שהמשתמש דחה (להסתרה זמנית)
    
    Returns:
        מילון עם נתוני הווידג'ט
    """
    from datetime import datetime, timezone, timedelta
    from database.repository import HEAVY_FIELDS_EXCLUDE_PROJECTION
    
    dismissed_ids = dismissed_ids or []
    dismissed_oids = []
    for did in dismissed_ids:
        try:
            dismissed_oids.append(ObjectId(did))
        except Exception:
            pass
    
    missing_metadata: List[Dict[str, Any]] = []
    stale_files: List[Dict[str, Any]] = []
    result: Dict[str, Any] = {
        'missing_metadata': missing_metadata,
        'stale_files': stale_files,
        'total_missing': 0,
        'total_stale': 0,
        'shown_missing': 0,
        'shown_stale': 0,
        'has_items': False,
        'settings': {
            'stale_days': stale_days,
            'max_items': max_items
        }
    }
    
    # === בסיס שאילתה משותף ===
    base_query: Dict[str, Any] = {
        'user_id': user_id,
        'is_active': True
    }
    
    # === Projection קל (בלי code/content) ===
    # משתמשים בהחרגת שדות כבדים בלבד כדי להימנע מערבוב inclusion/exclusion
    projection = dict(HEAVY_FIELDS_EXCLUDE_PROJECTION)

    def _latest_files_pipeline(match_extra: Optional[Dict[str, Any]], sort_after: Dict[str, int]) -> List[Dict[str, Any]]:
        pipeline: List[Dict[str, Any]] = [
            {'$match': base_query},
            {'$sort': {'file_name': 1, 'version': -1}},
            {'$group': {'_id': '$file_name', 'latest': {'$first': '$$ROOT'}}},
            {'$replaceRoot': {'newRoot': '$latest'}},
        ]
        if dismissed_oids:
            pipeline.append({'$match': {'_id': {'$nin': dismissed_oids}}})
        if match_extra:
            pipeline.append({'$match': match_extra})
        pipeline.append({'$sort': sort_after})
        pipeline.append({'$project': projection})
        return pipeline

    def _count_latest(match_extra: Optional[Dict[str, Any]]) -> int:
        pipeline: List[Dict[str, Any]] = [
            {'$match': base_query},
            {'$sort': {'file_name': 1, 'version': -1}},
            {'$group': {'_id': '$file_name', 'latest': {'$first': '$$ROOT'}}},
            {'$replaceRoot': {'newRoot': '$latest'}},
        ]
        if dismissed_oids:
            pipeline.append({'$match': {'_id': {'$nin': dismissed_oids}}})
        if match_extra:
            pipeline.append({'$match': match_extra})
        pipeline.append({'$count': 'count'})
        try:
            docs = list(db.code_snippets.aggregate(pipeline, allowDiskUse=True))
            if docs and isinstance(docs[0], dict):
                return int(docs[0].get('count') or 0)
        except Exception:
            return 0
        return 0
    
    # =====================================================
    # קבוצה 1: קבצים חסרי תיאור או תגיות
    # =====================================================
    # תנאי: description ריק/חסר או tags ריק/חסר
    missing_query = dict(base_query)
    missing_query['$or'] = [
        # תיאור חסר או ריק
        {'description': {'$exists': False}},
        {'description': None},
        {'description': ''},
        # תגיות חסרות או ריקות
        {'tags': {'$exists': False}},
        {'tags': None},
        {'tags': []},
    ]
    
    # ספירה כוללת (רק הגרסה האחרונה לכל קובץ)
    result['total_missing'] = _count_latest(missing_query)
    
    # שליפה מוגבלת (רק הגרסה האחרונה לכל קובץ)
    missing_pipeline = _latest_files_pipeline(missing_query, {'updated_at': -1})
    missing_docs = list(db.code_snippets.aggregate(
        missing_pipeline + [{'$limit': max_items}],
        allowDiskUse=True
    ))
    
    result['shown_missing'] = len(missing_docs)
    
    for doc in missing_docs:
        reasons = []
        desc = (doc.get('description') or '').strip()
        tags = doc.get('tags') or []
        
        if not desc:
            reasons.append('חסר תיאור')
        if not tags:
            reasons.append('חסרות תגיות')
        
        missing_metadata.append({
            'id': str(doc['_id']),
            'file_name': doc.get('file_name', ''),
            'language': doc.get('programming_language', 'text'),
            'icon': get_language_icon(doc.get('programming_language', '')),
            'description': desc[:100],
            'tags': tags[:5],  # לתצוגה ברשימה בלבד
            'tags_full': tags,  # כל התגיות - לשימוש ב-quick edit
            'tags_count': len(tags),
            'updated_at': doc.get('updated_at'),
            'reasons': reasons,
            'reason_text': ' + '.join(reasons) if reasons else 'חסר מידע'
        })
    
    # =====================================================
    # קבוצה 2: קבצים שלא עודכנו זמן רב
    # =====================================================
    # תנאי מפתח: רק קבצים עם מטא-דאטה תקין!
    # קובץ נחשב "stale" רק אם:
    #   - updated_at ישן
    #   - description קיים ולא ריק
    #   - tags קיים ויש בו לפחות איבר אחד
    
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=stale_days)
    
    stale_query = dict(base_query)
    stale_query['updated_at'] = {'$lt': cutoff_date}
    
    # החרגה מפורשת של קבצים חסרי מטא-דאטה
    # שימוש ב-$and כדי לוודא שגם description וגם tags תקינים
    stale_query['$and'] = [
        # description קיים ולא ריק
        {'description': {'$exists': True}},
        {'description': {'$ne': None}},
        {'description': {'$ne': ''}},
        # tags קיים ויש לפחות איבר אחד (pattern מומלץ למונגו)
        {'tags.0': {'$exists': True}}
    ]
    
    # ספירה כוללת (רק הגרסה האחרונה לכל קובץ)
    result['total_stale'] = _count_latest(stale_query)
    
    # שליפה מוגבלת - הישנים קודם (רק הגרסה האחרונה לכל קובץ)
    stale_pipeline = _latest_files_pipeline(stale_query, {'updated_at': 1})
    stale_docs = list(db.code_snippets.aggregate(
        stale_pipeline + [{'$limit': max_items}],
        allowDiskUse=True
    ))
    
    result['shown_stale'] = len(stale_docs)
    
    for doc in stale_docs:
        updated = doc.get('updated_at')
        days_ago = 0
        if updated:
            try:
                delta = datetime.now(timezone.utc) - updated
                days_ago = delta.days
            except Exception:
                days_ago = stale_days
        
        stale_files.append({
            'id': str(doc['_id']),
            'file_name': doc.get('file_name', ''),
            'language': doc.get('programming_language', 'text'),
            'icon': get_language_icon(doc.get('programming_language', '')),
            'description': (doc.get('description') or '')[:100],
            'tags': (doc.get('tags') or [])[:5],
            'updated_at': updated,
            'days_ago': days_ago,
            'reason_text': f'לא עודכן {days_ago} ימים'
        })
    
    result['has_items'] = bool(result['missing_metadata'] or result['stale_files'])
    
    return result


def _get_active_dismissals(db, user_id: int) -> List[str]:
    """
    שולף את רשימת ה-file_ids שהמשתמש דחה ועדיין לא פגו.
    
    Returns:
        רשימת מזהי קבצים (כ-strings)
    """
    from datetime import datetime, timezone
    
    now = datetime.now(timezone.utc)
    
    try:
        # שליפת כל הדחיות שעדיין בתוקף (כולל דחיות "לתמיד")
        dismissals = db.attention_dismissals.find(
            {
                'user_id': user_id,
                '$or': [
                    {'forever': True},
                    {'expires_at': {'$gt': now}}
                ]
            },
            {'file_id': 1}
        )
        
        return [str(d['file_id']) for d in dismissals if d.get('file_id')]
    except Exception as e:
        logger.warning(f"Failed to get dismissals for user {user_id}: {e}")
        return []


def _build_push_card(db, user_id: int, *, now: Optional[datetime] = None) -> Dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    push_enabled = (os.getenv('PUSH_NOTIFICATIONS_ENABLED', 'true').strip().lower() in {'1', 'true', 'yes', 'on'})
    variants = [user_id, str(user_id)]

    try:
        subs_count = db.push_subscriptions.count_documents({'user_id': {'$in': variants}})
    except Exception:
        subs_count = 0

    last_subscribed = None
    if subs_count:
        try:
            cur = db.push_subscriptions.find({'user_id': {'$in': variants}}, {'updated_at': 1}).sort('updated_at', DESCENDING).limit(1)
            docs = list(cur or [])
            if docs:
                last_subscribed = _normalize_dt(docs[0].get('updated_at'))
        except Exception:
            last_subscribed = None

    try:
        pending_count = db.note_reminders.count_documents({'user_id': user_id, 'status': {'$in': ['pending', 'snoozed']}})
    except Exception:
        pending_count = 0

    last_push_doc = None
    try:
        cur = db.note_reminders.find(
            {'user_id': user_id, 'last_push_success_at': {'$ne': None}},
            {'note_id': 1, 'last_push_success_at': 1}
        ).sort('last_push_success_at', DESCENDING).limit(1)
        docs = list(cur or [])
        if docs:
            last_push_doc = docs[0]
    except Exception:
        last_push_doc = None

    next_reminder_doc = None
    try:
        cur = db.note_reminders.find(
            {'user_id': user_id, 'status': {'$in': ['pending', 'snoozed']}, 'remind_at': {'$gte': now}},
            {'note_id': 1, 'remind_at': 1}
        ).sort('remind_at', 1).limit(1)
        docs = list(cur or [])
        if docs:
            next_reminder_doc = docs[0]
    except Exception:
        next_reminder_doc = None

    note_ids = []
    if last_push_doc and last_push_doc.get('note_id'):
        note_ids.append(last_push_doc['note_id'])
    if next_reminder_doc and next_reminder_doc.get('note_id'):
        note_ids.append(next_reminder_doc['note_id'])
    notes_map = _lookup_notes_map(db, user_id, note_ids)

    status_variant = 'success'
    if not push_enabled:
        status_text = "התראות הושבתו ברמת המערכת"
        status_variant = 'danger'
    elif subs_count <= 0:
        status_text = "עוד לא הופעל בדפדפן הזה"
        status_variant = 'warning'
    elif subs_count == 1:
        status_text = "מופעל בדפדפן אחד"
    else:
        status_text = f"מופעל ב-{subs_count} דפדפנים"

    def _note_summary(doc, *, prefer_future: bool = False):
        if not doc:
            return None
        note = notes_map.get(str(doc.get('note_id')))
        if not note:
            return None
        remind_dt = _normalize_dt(doc.get('remind_at'))
        push_dt = _normalize_dt(doc.get('last_push_success_at'))
        if prefer_future:
            timestamp = remind_dt or push_dt
            if remind_dt and remind_dt >= now:
                relative = _format_relative(remind_dt)
            elif remind_dt:
                relative = "ממתין לשליחה"
            else:
                relative = "לא ידוע"
        else:
            timestamp = push_dt or remind_dt
            relative = _format_relative(timestamp) if timestamp else "לא ידוע"
        return {
            'title': _extract_note_preview(note.get('content', '')),
            'relative_time': relative,
            'timestamp': timestamp.isoformat() if timestamp else None,
        }

    last_push = None
    if last_push_doc:
        last_push = _note_summary(last_push_doc)
    next_reminder = None
    if next_reminder_doc:
        next_reminder = _note_summary(next_reminder_doc, prefer_future=True)

    return {
        'feature_enabled': push_enabled,
        'subscriptions': subs_count,
        'status_text': status_text,
        'status_variant': status_variant,
        'last_subscription': _format_relative(last_subscribed) if last_subscribed else None,
        'pending_count': pending_count,
        'last_push': last_push,
        'next_reminder': next_reminder,
        'cta_href': '/settings#push',
        'cta_label': 'נהל התראות',
    }


def _build_notes_snapshot(db, user_id: int, limit: int = 10) -> Dict[str, Any]:
    try:
        total_notes = db.sticky_notes.count_documents({'user_id': user_id})
    except Exception:
        total_notes = 0
    try:
        cursor = db.sticky_notes.find({'user_id': user_id}).sort('updated_at', DESCENDING).limit(limit)
        note_docs = list(cursor or [])
    except Exception:
        note_docs = []

    file_ids = [note.get('file_id') for note in note_docs if note.get('file_id')]
    files_map = _lookup_files_map(db, file_ids)
    notes_payload: List[Dict[str, Any]] = []
    for note in note_docs:
        dt = _normalize_dt(note.get('updated_at'))
        file_id = note.get('file_id')
        file_name = files_map.get(str(file_id), 'ללא קובץ') if file_id else 'ללא קובץ'
        notes_payload.append({
            'id': str(note.get('_id')),
            'title': _extract_note_preview(note.get('content', '')),
            'file_name': file_name,
            'file_url': f"/file/{file_id}" if file_id else None,
            'color': note.get('color'),
            'timestamp': dt.isoformat() if dt else None,
            'relative_time': _format_relative(dt),
        })

    return {
        'notes': notes_payload,
        'total': total_notes,
        'has_notes': bool(notes_payload),
    }


# נתיב לקובץ whats_new
_WHATS_NEW_PATH = Path(__file__).parent.parent / 'config' / 'whats_new.yaml'

# Cache לטעינת whats_new עם TTL
_whats_new_cache: Dict[str, Any] = {}
_whats_new_cache_time: float = 0
_whats_new_cache_lock = threading.Lock()
_WHATS_NEW_CACHE_TTL = 300  # 5 דקות


def _load_whats_new_cached() -> List[Dict[str, Any]]:
    """טוען את כל הפיצ'רים מקובץ YAML (עם cache)"""
    global _whats_new_cache, _whats_new_cache_time
    
    now = time.time()
    
    # בדיקת cache (בנעילה)
    with _whats_new_cache_lock:
        if _whats_new_cache and (now - _whats_new_cache_time) < _WHATS_NEW_CACHE_TTL:
            return _whats_new_cache.get('features', [])
    
    try:
        if not _WHATS_NEW_PATH.exists():
            return []
        
        with open(_WHATS_NEW_PATH, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
        
        features = data.get('features', []) if data else []
        
        # עיבוד הנתונים
        processed_features = []
        for feat in features:
            if not isinstance(feat, dict):
                continue
            
            title = feat.get('title', '')
            if not title:
                continue
            
            # עיבוד תאריך
            date_str = feat.get('date', '')
            relative_time = ''
            feat_date = None
            if date_str:
                try:
                    feat_date = datetime.strptime(str(date_str), '%Y-%m-%d').replace(tzinfo=timezone.utc)
                    relative_time = _format_relative(feat_date)
                except (ValueError, TypeError):
                    relative_time = str(date_str)
            
            processed_features.append({
                'title': title,
                'description': feat.get('description', ''),
                'icon': feat.get('icon', '✨'),
                'date': date_str,
                'date_obj': feat_date,
                'relative_time': relative_time,
                'link': feat.get('link'),
                'badge': feat.get('badge'),
            })
        
        # שמירה ב-cache (בנעילה)
        with _whats_new_cache_lock:
            _whats_new_cache = {'features': processed_features}
            _whats_new_cache_time = now
        
        return processed_features
        
    except Exception as e:
        logger.warning(f"Failed to load whats_new.yaml: {e}")
        return []


def _load_whats_new(limit: int = 5, offset: int = 0, max_days: int = 180) -> Dict[str, Any]:
    """טוען פיצ'רים חדשים עם תמיכה ב-pagination והגבלת ימים"""
    all_features = _load_whats_new_cached()
    
    # סינון לפי תאריך (רק פיצ'רים מהימים האחרונים)
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=max_days)
    filtered_features = []
    for feat in all_features:
        feat_date = feat.get('date_obj')
        # אם אין תאריך או התאריך בטווח - כולל
        if feat_date is None or feat_date >= cutoff_date:
            # הסר את date_obj מהתוצאה (לא צריך ב-template)
            clean_feat = {k: v for k, v in feat.items() if k != 'date_obj'}
            filtered_features.append(clean_feat)
    
    total = len(filtered_features)
    features_slice = filtered_features[offset:offset + limit]
    next_offset = offset + len(features_slice)
    remaining = max(0, total - next_offset)
    
    return {
        'features': features_slice,
        'has_features': bool(features_slice),
        'total': total,
        'offset': offset,
        'next_offset': next_offset,
        'remaining': remaining,
        'has_more': remaining > 0,
    }


@app.route('/dashboard')
@login_required
def dashboard():
    """דשבורד עם סטטיסטיקות"""
    try:
        db = get_db()
        user_id = session['user_id']

        # בדיקה אם המשתמש אדמין (סטטוס אפקטיבי)
        actual_is_admin = False
        try:
            actual_is_admin = bool(is_admin(int(user_id)))
        except Exception:
            actual_is_admin = False
        if is_impersonating_safe():
            user_is_admin = False
        else:
            user_is_admin = actual_is_admin
        
        # שליפת סטטיסטיקות - רק קבצים פעילים
        active_query = {
            'user_id': user_id,
            'is_active': True
        }
        total_files = db.code_snippets.count_documents(active_query)
        
        # חישוב נפח כולל
        pipeline = [
            {'$match': {
                'user_id': user_id,
                'is_active': True
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
                'is_active': True
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
                'is_active': True
            },
            {'file_name': 1, 'programming_language': 1, 'created_at': 1}
        ).sort('created_at', DESCENDING).limit(5))
        
        # עיבוד הנתונים לתצוגה
        for file in recent_files:
            file['_id'] = str(file['_id'])
            language = resolve_file_language(file.get('programming_language'), file.get('file_name', ''))
            file['language'] = language
            file['icon'] = get_language_icon(language)
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

        # 📌 קבצים נעוצים לדשבורד
        pinned_files = []
        max_pinned = 8
        try:
            from database.manager import get_pinned_files as _get_pinned_files, MAX_PINNED_FILES
            pin_manager = SimpleNamespace(collection=db.code_snippets)
            pinned_files = _get_pinned_files(pin_manager, user_id)
            max_pinned = MAX_PINNED_FILES
        except Exception:
            pinned_files = []
        pinned_data = []
        for p in pinned_files:
            pinned_data.append({
                "id": str(p.get("_id", "")),
                "file_name": p.get("file_name", ""),
                "language": p.get("programming_language", ""),
                "icon": get_language_icon(p.get("programming_language", "")),
                "tags": (p.get("tags") or [])[:3],
                "description": (p.get("description", "") or "")[:50],
                "lines": p.get("lines_count", 0)
            })

        # ========== חדש: קבצים מהקומיט האחרון (אדמין בלבד) ==========
        last_commit = None
        if user_is_admin:
            try:
                repo_name = os.getenv("REPO_NAME", "CodeBot")
                git_service = get_mirror_service()

                if git_service.mirror_exists(repo_name):
                    last_commit = git_service.get_last_commit_info(repo_name)

                    # הוספת מידע נוסף מה-DB
                    if last_commit:
                        metadata = db.repo_metadata.find_one({"repo_name": repo_name})
                        if metadata:
                            last_commit["sync_time"] = metadata.get("last_sync_time")
                            last_commit["sync_status"] = metadata.get("sync_status", "unknown")
                        try:
                            raw_date = str(last_commit.get("date") or "").strip()
                        except Exception:
                            raw_date = ""
                        if raw_date:
                            local_dt = None
                            try:
                                normalized = raw_date.replace("Z", "+00:00")
                                parsed = datetime.fromisoformat(normalized)
                                if parsed.tzinfo is None:
                                    parsed = parsed.replace(tzinfo=timezone.utc)
                                local_dt = parsed.astimezone(ZoneInfo("Asia/Jerusalem"))
                            except Exception:
                                local_dt = None
                            if local_dt is not None:
                                last_commit["date_israel"] = local_dt
                                last_commit["date_israel_str"] = local_dt.strftime("%d/%m/%Y %H:%M")
            except Exception as e:
                logger.warning(f"Failed to get last commit info: {e}")
                last_commit = None
        # ================================================================
        
        activity_timeline = _build_activity_timeline(db, user_id, active_query)
        push_card = _build_push_card(db, user_id)
        notes_snapshot = _build_notes_snapshot(db, user_id)
        whats_new = _load_whats_new(limit=5)
        
        # === ווידג'ט: קבצים שדורשים טיפול ===
        # שליפת דחיות פעילות
        dismissed_ids = _get_active_dismissals(db, user_id)
        
        # בניית נתוני הווידג'ט
        files_need_attention = _build_files_need_attention(
            db,
            user_id,
            max_items=10,
            stale_days=60,  # ניתן לקרוא מהעדפות המשתמש בעתיד
            dismissed_ids=dismissed_ids
        )

        return render_template('dashboard.html', 
                             user=session['user_data'],
                             stats=stats,
                             activity_timeline=activity_timeline,
                             push_card=push_card,
                             notes_snapshot=notes_snapshot,
                             whats_new=whats_new,
                             files_need_attention=files_need_attention,
                             bot_username=BOT_USERNAME_CLEAN,
                             pinned_files=pinned_data,
                             max_pinned=max_pinned,
                             # חדש:
                             user_is_admin=user_is_admin,
                             last_commit=last_commit)
                             
    except Exception as e:
        logger.exception("Error in dashboard")
        import traceback
        traceback.print_exc()
        # נסה להציג דשבורד ריק במקרה של שגיאה
        fallback_timeline = {
            'groups': [],
            'feed': [],
            'filters': [{'id': 'all', 'label': 'הכול', 'count': 0}],
            'compact_limit': 5,
            'has_events': False,
            'updated_at': datetime.now(timezone.utc).isoformat()
        }
        fallback_card = {'feature_enabled': False, 'subscriptions': 0, 'status_text': "לא זמין", 'status_variant': 'danger', 'pending_count': 0, 'last_push': None, 'next_reminder': None, 'cta_href': '/settings#push', 'cta_label': 'נהל התראות'}
        fallback_notes = {'notes': [], 'total': 0, 'has_notes': False}
        fallback_attention = {
            'missing_metadata': [],
            'stale_files': [],
            'total_missing': 0,
            'total_stale': 0,
            'shown_missing': 0,
            'shown_stale': 0,
            'has_items': False,
            'settings': {
                'stale_days': 60,
                'max_items': 10
            }
        }

        return render_template('dashboard.html', 
                             user=session.get('user_data', {}),
                             stats={
                                 'total_files': 0,
                                 'total_size': '0 B',
                                 'top_languages': [],
                                 'recent_files': []
                             },
                             pinned_files=[],
                             max_pinned=8,
                             activity_timeline=fallback_timeline,
                             push_card=fallback_card,
                             notes_snapshot=fallback_notes,
                             whats_new={'features': [], 'has_features': False, 'total': 0},
                             files_need_attention=fallback_attention,
                             error="אירעה שגיאה בטעינת הנתונים. אנא נסה שוב.",
                             bot_username=BOT_USERNAME_CLEAN,
                             user_is_admin=False,
                             last_commit=None)

@app.route('/files')
@app.route('/files', endpoint='files_page')
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
    # ברירת מחדל: חדש ביותר (ולא "ישן ביותר") — עבור "כל הקבצים", "קבצים גדולים", "שאר הקבצים"
    raw_sort = (request.args.get('sort') or '').strip()
    sort_by = raw_sort or '-created_at'
    repo_name = request.args.get('repo', '').strip()
    page = int(request.args.get('page', 1))
    cursor_token = (request.args.get('cursor') or '').strip()
    per_page = 20

    # --- Smart Projection helpers ---
    # מסמכים חדשים יכולים להכיל file_size/lines_count (נשמרים בזמן שמירה).
    # למסמכים ישנים: נחשב ב-DB (בלי להחזיר את `code`) באמצעות $strLenBytes/$split.
    _mongo_file_size_from_code = {
        '$cond': {
            'if': {'$and': [
                {'$ne': ['$code', None]},
                {'$eq': [{'$type': '$code'}, 'string']},
            ]},
            'then': {'$strLenBytes': '$code'},
            'else': 0,
        }
    }
    _mongo_lines_count_from_code = {
        '$cond': {
            'if': {'$and': [
                {'$ne': ['$code', None]},
                {'$eq': [{'$type': '$code'}, 'string']},
            ]},
            # הערה: $split שומר תאימות טובה מספיק למסך רשימה (לא מושלם לעומת splitlines()).
            'then': {'$size': {'$split': ['$code', '\n']}},
            'else': 0,
        }
    }
    _mongo_add_size_lines_stage = {
        '$addFields': {
            'file_size': {'$ifNull': ['$file_size', _mongo_file_size_from_code]},
            'lines_count': {'$ifNull': ['$lines_count', _mongo_lines_count_from_code]},
        }
    }

    # החלת ברירות מחדל למיון לפני בניית מפתח הקאש
    try:
        # קטגוריית "נפתחו לאחרונה": לפי זמן פתיחה אחרון אם לא סופק מיון במפורש
        if (category_filter or '').strip().lower() == 'recent' and not raw_sort:
            sort_by = '-last_opened_at'
    except Exception:
        pass
    try:
        # קטגוריית "מועדפים": לפי זמן הוספה למועדפים (חדש -> ישן) אם לא סופק מיון במפורש
        if (category_filter or '').strip().lower() == 'favorites' and not raw_sort:
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
    
    # בניית שאילתה - לאחר המיגרציה: משתמשים בפילטר ישיר ויעיל לאינדקסים
    query = {
        'user_id': user_id,
        '$and': [{'is_active': True}],
    }

    # אם $text לא זמין (למשל אינדקס עדיין בבנייה / לא קיים), נרצה fallback בטוח ל-$regex
    # כדי למנוע קריסה של הדף.
    def _with_regex_fallback(curr_query: Dict[str, Any]) -> Dict[str, Any]:
        try:
            if not search_query:
                return curr_query
            if not isinstance(curr_query, dict):
                return curr_query
            if '$text' not in curr_query:
                return curr_query

            q2: Dict[str, Any] = dict(curr_query)
            q2.pop('$text', None)

            and_list = list(q2.get('$and') or [])

            # חיפוש ליטרלי (לא Regex גולמי) למניעת דפוסים מסוכנים
            needle = str(search_query).strip()
            if not needle:
                q2['$and'] = and_list
                return q2
            esc = re.escape(needle)

            and_list.append({
                '$or': [
                    {'file_name': {'$regex': esc, '$options': 'i'}},
                    {'description': {'$regex': esc, '$options': 'i'}},
                    # Large files משתמשים בשדה content; ב-code_snippets זה פשוט לא ישפיע
                    {'content': {'$regex': esc, '$options': 'i'}},
                    # תאימות: tags יכולים להיות list; זהו fallback "טוב מספיק"
                    {'tags': {'$in': [needle.lower()]}},
                ]
            })
            q2['$and'] = and_list
            return q2
        except Exception:
            return curr_query
    
    if search_query:
        # חיפוש טקסטואלי ב-UI: נעדיף $text במקום $regex כדי לאפשר שימוש באינדקס טקסט
        query['$text'] = {'$search': search_query}
    
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
                    'is_active': True,
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
                        'is_active': True,
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
            # קבצים גדולים: יישור להגדרת הבוט — משתמשים באוסף large_files (לא לפי 100KB ב-code_snippets)
            large_coll = getattr(db, 'large_files', None)
            if large_coll is not None:
                sort_dir = -1 if sort_by.startswith('-') else 1
                sort_field_local = sort_by.lstrip('-') or 'created_at'
                try:
                    total_count = int(large_coll.count_documents(query) or 0)
                except Exception:
                    # fallback אם $text נכשל (למשל אינדקס לא קיים/בבנייה)
                    try:
                        query = _with_regex_fallback(query)
                        total_count = int(large_coll.count_documents(query) or 0)
                    except Exception:
                        total_count = 0
                try:
                    cursor = large_coll.find(query, LIST_EXCLUDE_HEAVY_PROJECTION)
                    cursor = cursor.sort(sort_field_local, sort_dir)
                    cursor = cursor.skip((page - 1) * per_page).limit(per_page)
                    files_cursor = cursor
                except Exception:
                    try:
                        query = _with_regex_fallback(query)
                        cursor = large_coll.find(query, LIST_EXCLUDE_HEAVY_PROJECTION)
                        cursor = cursor.sort(sort_field_local, sort_dir)
                        cursor = cursor.skip((page - 1) * per_page).limit(per_page)
                        files_cursor = cursor
                    except Exception:
                        files_cursor = []
            else:
                # fallback היסטורי: סינון לפי 100KB מתוך code_snippets
                pipeline = [
                    {'$match': query},
                    _mongo_add_size_lines_stage,
                    {'$match': {'file_size': {'$gte': 102400}}}  # 100KB
                ]
                files_cursor = db.code_snippets.aggregate(pipeline + [
                    {'$project': LIST_EXCLUDE_HEAVY_PROJECTION},
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
            _mongo_add_size_lines_stage,
            {'$match': {'file_size': {'$gt': 0}}},
            {'$group': {'_id': '$file_name'}},
            {'$count': 'total'}
        ]
        try:
            count_result = list(db.code_snippets.aggregate(count_pipeline))
        except Exception:
            query = _with_regex_fallback(query)
            count_pipeline[0] = {'$match': query}
            try:
                count_result = list(db.code_snippets.aggregate(count_pipeline))
            except Exception:
                count_result = []
        total_count = count_result[0]['total'] if count_result else 0
    elif category_filter == 'other':
        # ספירת קבצים ייחודיים לפי שם קובץ לאחר סינון (תוכן >0), עם עקביות ל-query הכללי
        count_pipeline = [
            {'$match': query},
            _mongo_add_size_lines_stage,
            {'$match': {'file_size': {'$gt': 0}}},
            {'$group': {'_id': '$file_name'}},
            {'$count': 'total'}
        ]
        try:
            count_result = list(db.code_snippets.aggregate(count_pipeline))
        except Exception:
            query = _with_regex_fallback(query)
            count_pipeline[0] = {'$match': query}
            try:
                count_result = list(db.code_snippets.aggregate(count_pipeline))
            except Exception:
                count_result = []
        total_count = count_result[0]['total'] if count_result else 0
    elif category_filter != 'large':
        try:
            total_count = db.code_snippets.count_documents(query)
        except Exception:
            query = _with_regex_fallback(query)
            try:
                total_count = db.code_snippets.count_documents(query)
            except Exception:
                total_count = 0
    
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
                    'is_active': True,
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
            '$and': [{'is_active': True}],
        }
        # לשמור עקביות עם החיפוש/מסננים הכלליים
        if search_query:
            recent_query['$text'] = {'$search': search_query}
        if language_filter:
            recent_query['programming_language'] = language_filter
        # צמצום לשמות שנפתחו לאחרונה
        recent_query['file_name'] = {'$in': file_names or ['__none__']}

        # אגרגציה: גרסה אחרונה לכל שם קובץ + פלטר לתוכן לא ריק
        sort_field_local = sort_by.lstrip('-') if sort_by else 'last_opened_at'
        sort_dir = -1 if (sort_by or '').startswith('-') else 1

        pipeline = [
            {'$match': recent_query},
            # חשוב: סינון "לא ריק" חייב להתבצע לפני group כדי לבחור את הגרסה האחרונה *הלא-ריקה*
            # ולא לפסול קובץ רק בגלל שהגרסה האחרונה ריקה.
            _mongo_add_size_lines_stage,
            {'$match': {'file_size': {'$gt': 0}}},
            {'$sort': {'file_name': 1, 'version': -1}},
            {'$group': {'_id': '$file_name', 'latest': {'$first': '$$ROOT'}}},
            {'$replaceRoot': {'newRoot': '$latest'}},
            {'$project': LIST_EXCLUDE_HEAVY_PROJECTION},
        ]

        # מיון: אם מיון לפי last_opened_at – נטפל בפייתון; אחרת נמיין ב-DB
        if sort_field_local in {'file_name', 'created_at', 'updated_at'}:
            pipeline.append({'$sort': {sort_field_local: sort_dir}})

        try:
            latest_items = list(db.code_snippets.aggregate(pipeline))
        except Exception:
            # fallback אם $text נכשל
            try:
                recent_query_fallback = _with_regex_fallback(recent_query)
                pipeline[0] = {'$match': recent_query_fallback}
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
            lang_display = resolve_file_language(latest.get('programming_language'), fname)
            try:
                size_bytes = int(latest.get('file_size') or 0)
            except Exception:
                size_bytes = 0
            try:
                lines_count = int(latest.get('lines_count') or 0)
            except Exception:
                lines_count = 0
            files_list.append({
                'id': str(latest.get('_id')),
                'file_name': fname,
                'language': lang_display,
                'icon': get_language_icon(lang_display),
                'description': latest.get('description', ''),
                'tags': latest.get('tags', []),
                'size': format_file_size(size_bytes),
                'lines': lines_count,
                'created_at': format_datetime_display(latest.get('created_at')),
                'updated_at': format_datetime_display(latest.get('updated_at')),
                'last_opened_at': format_datetime_display(recent_map.get(fname)),
            })

        # רשימת שפות לפילטר - רק מקבצים פעילים
        languages = db.code_snippets.distinct(
            'programming_language',
            {
                'user_id': user_id,
                'is_active': True,
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
            # חשוב: סינון "לא ריק" חייב להתבצע לפני group כדי לבחור את הגרסה האחרונה *הלא-ריקה*.
            # אחרת, אם הגרסה האחרונה ריקה נקבל mismatch בין total_count לבין הרשימה בפועל.
            _mongo_add_size_lines_stage,
            {'$match': {'file_size': {'$gt': 0}}},
            {'$sort': {'file_name': 1, 'version': -1}},
            {'$group': {'_id': '$file_name', 'latest': {'$first': '$$ROOT'}}},
            {'$replaceRoot': {'newRoot': '$latest'}},
            {'$project': LIST_EXCLUDE_HEAVY_PROJECTION},
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
        # קטגוריות רגילות (ללא recent/large/other): עימוד לפי מסמכים,
        # אבל עם Smart Projection כדי לא להחזיר `code` למסך רשימה.
        files_cursor = db.code_snippets.aggregate([
            {'$match': query},
            _mongo_add_size_lines_stage,
            {'$project': LIST_EXCLUDE_HEAVY_PROJECTION},
            {'$sort': {sort_field: sort_order}},
            {'$skip': (page - 1) * per_page},
            {'$limit': per_page},
        ])
    elif category_filter == 'other':
        # "שאר קבצים": בעלי תוכן (>0 בתים), מציגים גרסה אחרונה לכל file_name; עקבי עם ה-query הכללי
        sort_dir = -1 if sort_by.startswith('-') else 1
        sort_field_local = sort_by.lstrip('-')
        base_pipeline = [
            {'$match': query},
            _mongo_add_size_lines_stage,
            {'$match': {'file_size': {'$gt': 0}}},
        ]
        pipeline = base_pipeline + [
            {'$sort': {'file_name': 1, 'version': -1}},
            {'$group': {'_id': '$file_name', 'latest': {'$first': '$$ROOT'}}},
            {'$replaceRoot': {'newRoot': '$latest'}},
            {'$project': LIST_EXCLUDE_HEAVY_PROJECTION},
            {'$sort': {sort_field_local: sort_dir}},
            {'$skip': (page - 1) * per_page},
            {'$limit': per_page},
        ]
        files_cursor = db.code_snippets.aggregate(pipeline)
    
    files_list = []
    for file in files_cursor:
        fname = file.get('file_name') or ''
        lang_display = resolve_file_language(file.get('programming_language'), fname)
        try:
            size_bytes = int(file.get('file_size') or 0)
        except Exception:
            size_bytes = 0
        try:
            lines_count = int(file.get('lines_count') or 0)
        except Exception:
            lines_count = 0
        files_list.append({
            'id': str(file['_id']),
            'file_name': fname,
            'language': lang_display,
            'icon': get_language_icon(lang_display),
            'description': file.get('description', ''),
            'tags': file.get('tags', []),
            'size': format_file_size(size_bytes),
            'lines': lines_count,
            'created_at': format_datetime_display(file.get('created_at')),
            'updated_at': format_datetime_display(file.get('updated_at'))
        })
    
    # רשימת שפות לפילטר - רק מקבצים פעילים
    if category_filter == 'large' and getattr(db, 'large_files', None) is not None:
        try:
            large_coll = getattr(db, 'large_files', None)
            languages = large_coll.distinct(
                'programming_language',
                {
                    'user_id': user_id,
                    'is_active': True,
                }
            ) if large_coll is not None else []
        except Exception:
            languages = []
    else:
        languages = db.code_snippets.distinct(
            'programming_language',
            {
                'user_id': user_id,
                'is_active': True,
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


@app.route('/trash')
@login_required
@traced("files.recycle_bin_page")
def trash_page():
    """דף סל מחזור בווב-אפ (קבצים עם is_active=False)."""
    db = get_db()
    user_id = session['user_id']

    try:
        page = int(request.args.get('page', 1))
    except Exception:
        page = 1
    page = max(1, page)
    per_page = 20

    match = {'user_id': user_id, 'is_active': False}

    reg_docs: list[dict] = []
    try:
        reg_docs = list(db.code_snippets.find(
            match,
            {
                'file_name': 1,
                'programming_language': 1,
                'deleted_at': 1,
                'deleted_expires_at': 1,
                'updated_at': 1,
                'created_at': 1,
                'version': 1,
            },
        ))
    except Exception:
        reg_docs = []

    large_docs: list[dict] = []
    large_coll = getattr(db, 'large_files', None)
    if large_coll is not None:
        try:
            large_docs = list(large_coll.find(
                match,
                {
                    'file_name': 1,
                    'programming_language': 1,
                    'deleted_at': 1,
                    'deleted_expires_at': 1,
                    'updated_at': 1,
                    'created_at': 1,
                },
            ))
        except Exception:
            large_docs = []

    combined: list[dict] = []
    for d in reg_docs:
        if isinstance(d, dict):
            d['_is_large'] = False
            combined.append(d)
    for d in large_docs:
        if isinstance(d, dict):
            d['_is_large'] = True
            combined.append(d)

    def _sort_key(doc: dict):
        dt = doc.get('deleted_at') or doc.get('updated_at') or doc.get('created_at')
        if isinstance(dt, datetime):
            return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)
        return datetime.min.replace(tzinfo=timezone.utc)

    combined.sort(key=_sort_key, reverse=True)

    total_count = len(combined)
    total_pages = (total_count + per_page - 1) // per_page if total_count > 0 else 1
    page = max(1, min(page, total_pages))
    start = (page - 1) * per_page
    end = start + per_page
    page_docs = combined[start:end]

    items: list[dict] = []
    for doc in page_docs:
        fname = str(doc.get('file_name') or '')
        lang_display = resolve_file_language(doc.get('programming_language'), fname)
        is_large = bool(doc.get('_is_large', False))
        items.append({
            'id': str(doc.get('_id') or ''),
            'file_name': fname,
            'language': lang_display,
            'icon': get_language_icon(lang_display),
            'deleted_at': format_datetime_display(doc.get('deleted_at')),
            'expires_at': format_datetime_display(doc.get('deleted_expires_at')),
            'version': (doc.get('version') if not is_large else None),
            'kind': ('גדול' if is_large else 'רגיל'),
        })

    return render_template(
        'trash.html',
        user=session['user_data'],
        items=items,
        total_count=total_count,
        page=page,
        total_pages=total_pages,
        has_prev=page > 1,
        has_next=page < total_pages,
        recycle_ttl_days=RECYCLE_TTL_DAYS_DEFAULT,
    )

@app.route('/file/<file_id>')
@login_required
def view_file(file_id):
    """צפייה בקובץ בודד"""
    db = get_db()
    user_id = session['user_id']

    # הרשאות UI (לכפתורים/מודאלים) - Premium/Admin
    actual_is_admin = False
    actual_is_premium = False
    try:
        uid_int = int(user_id)
        actual_is_admin = bool(is_admin(uid_int))
        actual_is_premium = bool(is_premium(uid_int))
    except Exception:
        actual_is_admin = False
        actual_is_premium = False
    if is_impersonating_safe():
        user_is_admin = False
        user_is_premium = False
    else:
        user_is_admin = actual_is_admin
        user_is_premium = actual_is_premium
    
    try:
        file, kind = _get_user_any_file_by_id(db, user_id, file_id)
    except Exception as e:
        logger.exception("DB error fetching file", extra={"file_id": file_id, "user_id": user_id, "error": str(e)})
        abort(500)
    
    if not file:
        abort(404)
    is_large = (kind == "large")

    skip_activity = False
    try:
        skip_activity = bool(session.pop('_skip_view_activity_once', False))
    except Exception:
        skip_activity = False
    if not skip_activity:
        _log_webapp_user_activity()

    clear_edit_draft_for_id = ''
    try:
        clear_edit_draft_for_id = str(session.pop(_EDIT_CLEAR_DRAFT_SESSION_KEY, '') or '')
    except Exception:
        clear_edit_draft_for_id = ''

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
    theme_key = _get_theme_etag_key(user_id)
    etag = _compute_file_etag(file, variant=theme_key)
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
    code = (file.get('code') or file.get('content') or '')
    language = resolve_file_language(file.get('programming_language'), file.get('file_name', ''))
    
    # הגבלת גודל תצוגה - 1MB
    MAX_DISPLAY_SIZE = 1024 * 1024  # 1MB
    if len(code.encode('utf-8')) > MAX_DISPLAY_SIZE:
        html = render_template('view_file.html',
                             user=session['user_data'],
                             user_is_admin=user_is_admin,
                             is_premium=user_is_premium,
                             clear_edit_draft_for_id=clear_edit_draft_for_id,
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
                                 'version': (file.get('version', 1) if not is_large else None),
                                 'is_large': is_large,
                                 'can_pin': False,
                                 'is_pinned': bool(file.get('is_pinned', False)),
                                 'source_url': file.get('source_url') or '',
                                 'source_url_host': _extract_source_hostname(file.get('source_url')),
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
                             user_is_admin=user_is_admin,
                             is_premium=user_is_premium,
                             clear_edit_draft_for_id=clear_edit_draft_for_id,
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
                                 'version': (file.get('version', 1) if not is_large else None),
                                 'is_large': is_large,
                                 'can_pin': False,
                                 'is_pinned': bool(file.get('is_pinned', False)),
                                 'source_url': file.get('source_url') or '',
                                 'source_url_host': _extract_source_hostname(file.get('source_url')),
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
    
    _theme = get_current_theme()
    style_name = get_pygments_style(_theme)
    formatter = HtmlFormatter(
        style=style_name,
        linenos=True,
        cssclass='source',
        lineanchors='line',
        anchorlinenos=True
    )
    try:
        highlighted_code = highlight(code, lexer, formatter)
        css = formatter.get_style_defs('.source')
        # אם מסיבה כלשהי אין טקסט נראה – נרים חריגה כדי להפעיל נפילת noclasses
        import re as _re
        text_only = _re.sub(r'<[^>]+>', '', highlighted_code or '').strip()
        if not text_only:
            raise ValueError('empty highlighted rendering')
    except Exception:
        formatter = HtmlFormatter(
            noclasses=True,
            linenos=True,
            cssclass='source',
            lineanchors='line',
            anchorlinenos=True
        )
        highlighted_code = highlight(code, lexer, formatter)
        css = ''
    
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
        'version': (file.get('version', 1) if not is_large else None),
        'is_large': is_large,
        'can_pin': not is_large,
        'is_favorite': bool(file.get('is_favorite', False)),
        'is_pinned': bool(file.get('is_pinned', False)),
        'source_url': file.get('source_url') or '',
        'source_url_host': _extract_source_hostname(file.get('source_url')),
    }
    if not is_large:
        markdown_images = []
        try:
            cursor = db.markdown_images.find(
                {'snippet_id': file['_id'], 'user_id': user_id}
            ).sort('order', ASCENDING)
            for img in cursor:
                markdown_images.append({
                    'id': str(img.get('_id')),
                    'file_name': img.get('file_name') or 'image',
                    'size': format_file_size(int(img.get('size') or 0)),
                    'content_type': img.get('content_type') or '',
                    'url': url_for('get_markdown_image', file_id=file_id, image_id=str(img.get('_id')))
                })
        except Exception:
            markdown_images = []
        if markdown_images:
            file_data['markdown_images'] = markdown_images
    
    html = render_template('view_file.html',
                         user=session['user_data'],
                         user_is_admin=user_is_admin,
                         is_premium=user_is_premium,
                         clear_edit_draft_for_id=clear_edit_draft_for_id,
                         file=file_data,
                         highlighted_code=highlighted_code,
                         syntax_css=css,
                         raw_code=code)
    resp = Response(html, mimetype='text/html; charset=utf-8')
    resp.headers['ETag'] = etag
    resp.headers['Last-Modified'] = last_modified_str
    return resp


@app.route('/compare/<file_id>')
@login_required
def compare_versions_page(file_id: str):
    """דף השוואת גרסאות של קובץ."""
    user_id = get_current_user_id()

    from database import db as _db
    db = _db

    file_doc = db.get_file_by_id(file_id)
    if not file_doc or file_doc.get("user_id") != user_id:
        abort(404)

    # קבלת כל הגרסאות
    all_versions = db.get_all_versions(user_id, file_doc.get("file_name"))

    return render_template(
        'compare.html',
        file=file_doc,
        versions=all_versions,
        current_version=file_doc.get("version", 1),
    )


@app.route('/compare')
@login_required
def compare_files_page():
    """דף השוואת קבצים שונים."""
    user_id = get_current_user_id()

    left_id = request.args.get('left')
    right_id = request.args.get('right')

    from database import db as _db
    db = _db

    # קבלת רשימת הקבצים לבחירה
    user_files = db.get_user_files(
        user_id,
        limit=100,
        projection={
            "_id": 1,
            "file_name": 1,
            "programming_language": 1,
            "updated_at": 1,
            "file_size": 1,
            "lines_count": 1,
        },
    )

    # חישוב שפות מובילות לסינון מהיר (Top 5)
    lang_counts: Dict[str, int] = {}
    files: List[Dict[str, Any]] = []
    for f in (user_files or []):
        try:
            lang = f.get("programming_language") or "other"
        except Exception:
            lang = "other"
        try:
            lang_counts[lang] = lang_counts.get(lang, 0) + 1
        except Exception:
            pass

        # התאמה מינימלית כדי ש-{{ files | tojson }} יעבוד גם עם ObjectId/Datetime
        ff: Dict[str, Any] = dict(f or {})
        try:
            ff["_id"] = str(ff.get("_id", ""))
        except Exception:
            ff["_id"] = str(getattr(f, "_id", "") or "")
        updated_at = ff.get("updated_at")
        try:
            if hasattr(updated_at, "isoformat"):
                ff["updated_at"] = updated_at.isoformat()
            elif updated_at is None:
                ff["updated_at"] = ""
            else:
                ff["updated_at"] = str(updated_at)
        except Exception:
            ff["updated_at"] = str(updated_at) if updated_at is not None else ""
        files.append(ff)

    top_languages = sorted(lang_counts.keys(), key=lambda x: -lang_counts[x])[:5]

    return render_template(
        'compare_files.html',
        files=files,
        selected_left=left_id,
        selected_right=right_id,
        top_languages=top_languages,
    )


@app.route('/compare/paste')
@login_required
def compare_paste_page():
    """דף השוואת קוד בהדבקה - ללא צורך בקבצים שמורים."""
    return render_template('compare_paste.html')


@app.route('/tools/code')
@login_required
def code_tools_page():
    """דף ייעודי לכלי קוד (Playground) עם Diff מקצועי."""
    return render_template('code_tools.html')


@app.route('/tools/json')
@login_required
def json_formatter_page():
    """דף JSON Formatter."""
    return render_template('json_formatter.html')


@app.route('/file/<file_id>/images/<image_id>')
@login_required
def get_markdown_image(file_id, image_id):
    db = get_db()
    user_id = session['user_id']
    try:
        snippet_id = ObjectId(file_id)
        image_obj_id = ObjectId(image_id)
    except (InvalidId, TypeError):
        abort(404)

    try:
        image_doc = db.markdown_images.find_one({
            '_id': image_obj_id,
            'snippet_id': snippet_id,
            'user_id': user_id,
        })
    except PyMongoError:
        image_doc = None

    if not image_doc:
        abort(404)

    data = image_doc.get('data')
    if data is None:
        abort(404)

    try:
        payload = bytes(data)
    except Exception:
        abort(404)

    content_type = image_doc.get('content_type') or 'application/octet-stream'
    resp = Response(payload, mimetype=content_type)
    resp.headers['Cache-Control'] = 'private, max-age=86400'
    filename = image_doc.get('file_name') or 'image'
    try:
        resp.headers['Content-Disposition'] = f'inline; filename="{filename}"'
    except Exception:
        pass
    return resp


def _get_user_file_by_id(db_ref, user_id: int, file_id: str) -> Optional[Dict[str, Any]]:
    """שליפת קובץ לפי ObjectId תוך וידוא בעלות משתמש."""
    if not file_id:
        return None
    try:
        obj_id = ObjectId(file_id)
    except (InvalidId, TypeError):
        return None
    try:
        return db_ref.code_snippets.find_one({'_id': obj_id, 'user_id': user_id})
    except Exception:
        return None

_LIVE_PREVIEW_MAX_BYTES = 200 * 1024  # 200KB כדי למנוע תקיעות ברינדור
_LIVE_PREVIEW_ALLOWED_SCHEMES = {"http", "https", "mailto", "tel"}
_LIVE_PREVIEW_ALLOWED_DATA_PREFIXES = ("data:image/",)
_LIVE_PREVIEW_BASE_ALLOWED_TAGS = {
    "p",
    "strong",
    "em",
    "ul",
    "ol",
    "li",
    "pre",
    "code",
    "blockquote",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "table",
    "thead",
    "tbody",
    "tfoot",
    "tr",
    "td",
    "th",
    "hr",
    "br",
    "span",
    "div",
    "img",
    "a",
    "kbd",
    "mark",
    "del",
    "ins",
    "code",
}
_LIVE_PREVIEW_HTML_ALLOWED_TAGS = _LIVE_PREVIEW_BASE_ALLOWED_TAGS.union(
    {
        "section",
        "article",
        "header",
        "footer",
        "nav",
        "main",
        "figure",
        "figcaption",
        "video",
        "audio",
        "source",
        "canvas",
        "svg",
        "path",
        "circle",
        "g",
        "small",
        "sup",
        "sub",
        "label",
        "input",
        "textarea",
        "button",
        "select",
        "option",
        "form",
        "fieldset",
        "legend",
        "details",
        "summary",
        "dl",
        "dt",
        "dd",
        "style",
    }
)
_LIVE_PREVIEW_GLOBAL_ATTRS = {
    "class",
    "id",
    "dir",
    "lang",
    "title",
    "role",
    "tabindex",
    "aria-label",
    "aria-hidden",
    "aria-expanded",
    "aria-controls",
    "aria-describedby",
    "aria-live",
}
_LIVE_PREVIEW_ELEMENT_ATTRS = {
    "a": {"href", "target", "rel"},
    "img": {"src", "alt", "title", "width", "height", "loading"},
    "code": {"class"},
    "pre": {"class"},
    "table": {"class"},
    "td": {"colspan", "rowspan"},
    "th": {"colspan", "rowspan", "scope"},
    "video": {"controls", "autoplay", "loop", "muted", "poster"},
    "audio": {"controls", "autoplay", "loop", "muted"},
    "source": {"src", "type"},
    "button": {"type", "disabled"},
    "input": {"type", "name", "value", "placeholder", "checked", "disabled"},
    "textarea": {"name", "rows", "cols", "placeholder", "disabled"},
    "select": {"name", "multiple", "size", "disabled"},
    "option": {"value", "selected", "disabled"},
    "form": {"method", "action"},
}
_LIVE_PREVIEW_BLOCKED_TAGS = {"script", "iframe", "embed", "object", "base", "link"}
_LIVE_PREVIEW_URL_ATTRS = {
    "href": False,
    "src": True,
    "poster": True,
    "action": False,
}
_PYGMENTS_PREVIEW_FORMATTER = HtmlFormatter(style="friendly", cssclass="codehilite", wrapcode=True)
_PYGMENTS_PREVIEW_CSS = _PYGMENTS_PREVIEW_FORMATTER.get_style_defs(".codehilite")


def _is_safe_preview_url(value: str, *, allow_data_uri: bool) -> bool:
    val = (value or "").strip()
    if not val:
        return False
    lowered = val.lower()
    if lowered.startswith("javascript:"):
        return False
    if lowered.startswith("//"):
        return False
    if lowered.startswith("data:"):
        if not allow_data_uri:
            return False
        return any(lowered.startswith(prefix) for prefix in _LIVE_PREVIEW_ALLOWED_DATA_PREFIXES)
    if lowered.startswith(("#", "./", "../")):
        return True
    if lowered.startswith("/"):
        return True
    parsed = urlparse(val)
    if parsed.scheme:
        return parsed.scheme.lower() in _LIVE_PREVIEW_ALLOWED_SCHEMES
    return True


def _sanitize_preview_html(
    raw_html: str,
    *,
    profile: str,
) -> str:
    """
    Sanitizes HTML שמוחזר לתצוגה חיה.

    profile:
        - "markdown": מכלול תגיות בסיסי, ללא style.
        - "html": מאפשר תגיות מבניות ו-attribs נוספים.
        - "code": זהה ל-markdown אך אוכף div/span עם class.
    """
    if not raw_html:
        return ""
    allowed_tags = _LIVE_PREVIEW_BASE_ALLOWED_TAGS if profile in {"markdown", "code"} else _LIVE_PREVIEW_HTML_ALLOWED_TAGS
    allow_inline_styles = profile == "html"
    soup = BeautifulSoup(raw_html, "html.parser")
    for blocked in _LIVE_PREVIEW_BLOCKED_TAGS:
        for element in soup.find_all(blocked):
            element.decompose()
    for tag in soup.find_all(True):
        name = (tag.name or "").lower()
        if name not in allowed_tags:
            tag.unwrap()
            continue
        cleaned_attrs: Dict[str, Any] = {}
        tag_attrs = dict(tag.attrs or {})
        allowed_for_tag = _LIVE_PREVIEW_ELEMENT_ATTRS.get(name, set())
        for attr_name, attr_value in tag_attrs.items():
            attr_lower = attr_name.lower()
            if attr_lower.startswith("on"):
                continue
            if attr_lower == "style" and not allow_inline_styles:
                continue
            if attr_lower not in allowed_for_tag and attr_lower not in _LIVE_PREVIEW_GLOBAL_ATTRS:
                if attr_lower.startswith("aria-") or attr_lower.startswith("data-"):
                    pass
                elif not (allow_inline_styles and attr_lower == "style"):
                    continue
            value = attr_value
            if isinstance(value, list):
                value = value[0]
            value_str = str(value)
            if attr_lower in _LIVE_PREVIEW_URL_ATTRS:
                allow_data = _LIVE_PREVIEW_URL_ATTRS[attr_lower]
                if not _is_safe_preview_url(value_str, allow_data_uri=allow_data):
                    continue
            cleaned_attrs[attr_lower] = value_str
        tag.attrs = cleaned_attrs
    return soup.decode()


def _render_markdown_preview(text: str) -> Tuple[str, str]:
    md = Markdown(
        extensions=[
            "extra",
            "codehilite",
            "tables",
            "sane_lists",
            "toc",
            "admonition",
        ],
        output_format="html5",
    )
    try:
        md.preprocessors.deregister("html_block")
    except Exception:
        pass
    try:
        md.inlinePatterns.deregister("html")
    except Exception:
        try:
            md.inlinePatterns.deregister("inlinehtml")
        except Exception:
            pass
    rendered = md.convert(text or "")
    sanitized = _sanitize_preview_html(rendered, profile="markdown")
    return sanitized, _PYGMENTS_PREVIEW_CSS


def _render_code_preview(text: str, language: str) -> Tuple[str, str]:
    code = text or ""
    lexer = None
    try:
        if language:
            lexer = get_lexer_by_name(language, stripall=False)
    except ClassNotFound:
        lexer = None
    if lexer is None:
        try:
            lexer = guess_lexer(code)
        except Exception:
            lexer = TextLexer()
    highlighted = highlight(code, lexer, _PYGMENTS_PREVIEW_FORMATTER)
    sanitized = _sanitize_preview_html(highlighted, profile="code")
    return sanitized, _PYGMENTS_PREVIEW_CSS


def _render_html_preview(text: str) -> str:
    return _sanitize_preview_html(text or "", profile="html")


def _resolve_preview_mode(language: str, mode_hint: str) -> str:
    normalized_hint = (mode_hint or "").strip().lower()
    if normalized_hint in {"markdown", "html", "code"}:
        return normalized_hint
    if language in {"markdown", "md"}:
        return "markdown"
    if language in {"html", "htm"}:
        return "html"
    return "code"


def _normalize_preview_language(language: Optional[str], file_name: Optional[str]) -> str:
    lang = (language or "").strip().lower()
    if not lang or lang == "text":
        try:
            detected = detect_language_from_filename(file_name or "")
        except Exception:
            detected = None
        if detected:
            lang = detected.lower()
    return lang or "text"


@app.route('/api/preview/live', methods=['POST'])
@login_required
@traced("preview.live")
def api_live_preview():
    """
    רינדור לייב של תוכן העורך עבור מצב Split View.

    התגובה מחזירה HTML מסונן + מידע עזר (CSS ל-Pygments וכו').
    """
    start = time.perf_counter()
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        payload = {}
    content = payload.get('content')
    if not isinstance(content, str):
        return jsonify({'ok': False, 'error': 'missing_content'}), 400
    normalized_content = content.replace('\r\n', '\n')
    if not normalized_content.strip():
        return jsonify({'ok': False, 'error': 'empty_content'}), 400
    try:
        payload_size = len(normalized_content.encode('utf-8'))
    except Exception:
        payload_size = len(normalized_content)
    if payload_size > _LIVE_PREVIEW_MAX_BYTES:
        return jsonify({'ok': False, 'error': 'content_too_large', 'limit': _LIVE_PREVIEW_MAX_BYTES}), 413
    language = _normalize_preview_language(payload.get('language'), payload.get('file_name'))
    resolved_mode = _resolve_preview_mode(language, payload.get('mode'))
    html = ''
    css_bundle: List[str] = []
    presentation = 'fragment'
    try:
        if resolved_mode == 'markdown':
            html, css = _render_markdown_preview(normalized_content)
            if css:
                css_bundle.append(css)
        elif resolved_mode == 'html':
            html = _render_html_preview(normalized_content)
            presentation = 'iframe'
        else:
            html, css = _render_code_preview(normalized_content, language)
            if css:
                css_bundle.append(css)
    except Exception as exc:
        try:
            logger.exception("live_preview_render_failed", extra={'mode': resolved_mode, 'error': str(exc)})
        except Exception:
            pass
        return jsonify({'ok': False, 'error': 'render_failed'}), 500
    duration_ms = int((time.perf_counter() - start) * 1000)
    meta: Dict[str, Any] = {
        'language': language,
        'mode': resolved_mode,
        'bytes': payload_size,
        'characters': len(normalized_content),
        'duration_ms': duration_ms,
    }
    if css_bundle:
        meta['styles'] = css_bundle
    return jsonify({
        'ok': True,
        'mode': resolved_mode,
        'presentation': presentation,
        'html': html,
        'meta': meta,
    })


@app.route('/api/file/<file_id>/preview')
@login_required
@traced("file.preview")
def file_preview(file_id):
    """מחזיר preview (עד 20 שורות ראשונות) של קובץ קוד כ-HTML מודגש.

    שימושי להצגה מהירה בתוך כרטיס בעמוד הקבצים, ללא ניווט לעמוד מלא.
    """
    db = get_db()
    user_id = session['user_id']

    # שליפת הקובץ למשתמש הנוכחי (רגיל או large_files)
    try:
        file, kind = _get_user_any_file_by_id(db, user_id, file_id)
    except Exception as e:
        logger.exception("DB error fetching file preview", extra={
            "file_id": file_id,
            "user_id": user_id,
            "error": str(e),
        })
        return jsonify({'ok': False, 'error': 'Database error'}), 500

    if not file:
        return jsonify({'ok': False, 'error': 'File not found'}), 404

    code = (file.get('code') or file.get('content') or '') or ''
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

    _theme = get_current_theme()
    style_name = get_pygments_style(_theme)
    formatter = HtmlFormatter(
        style=style_name,
        linenos=False,
        cssclass='preview-highlight',
        nowrap=False,
    )
    try:
        highlighted_html = highlight(preview_code, lexer, formatter)
        css = formatter.get_style_defs('.preview-highlight')
        import re as _re
        text_only = _re.sub(r'<[^>]+>', '', highlighted_html or '').strip()
        if not text_only:
            raise ValueError('empty highlighted preview')
    except Exception:
        formatter = HtmlFormatter(
            noclasses=True,
            linenos=False,
            cssclass='preview-highlight',
            nowrap=False,
        )
        highlighted_html = highlight(preview_code, lexer, formatter)
        css = ''

    return jsonify({
        'ok': True,
        'highlighted_html': highlighted_html,
        'syntax_css': css,
        'total_lines': total_lines,
        'preview_lines': preview_lines,
        'language': language,
        'has_more': total_lines > preview_lines,
    })


@app.route('/api/file/<file_id>/quick-update', methods=['POST'])
@login_required
def api_file_quick_update(file_id):
    """
    עדכון מהיר של תיאור ו/או תגיות לקובץ.
    Body: { "description": "...", "tags": ["tag1", "tag2"] }
    
    הערה: עדכון מוצלח גם מעדכן את updated_at, מה שיגרום לקובץ
    לצאת מרשימת "לא עודכן זמן רב" (וזו התנהגות רצויה).
    """
    try:
        user_id = session['user_id']
        db = get_db()
        
        try:
            oid = ObjectId(file_id)
        except Exception:
            return jsonify({'ok': False, 'error': 'מזהה לא תקין'}), 400
        
        # וידוא בעלות
        doc = db.code_snippets.find_one({
            '_id': oid,
            'user_id': user_id,
            'is_active': True
        }, {'_id': 1})
        
        if not doc:
            return jsonify({'ok': False, 'error': 'הקובץ לא נמצא'}), 404
        
        data = request.get_json() or {}
        updates = {'updated_at': datetime.now(timezone.utc)}
        
        if 'description' in data:
            desc = (data.get('description') or '').strip()[:500]
            updates['description'] = desc
        
        if 'tags' in data:
            raw_tags = data.get('tags') or []
            if isinstance(raw_tags, str):
                # תמיכה בקלט comma-separated
                raw_tags = [t.strip() for t in raw_tags.split(',') if t.strip()]
            # ניקוי ונורמליזציה
            clean_tags = []
            for t in raw_tags[:20]:  # מקסימום 20 תגיות
                tag = str(t).strip().lower()[:50]
                if tag and tag not in clean_tags:
                    clean_tags.append(tag)
            updates['tags'] = clean_tags
        
        if len(updates) <= 1:  # רק updated_at
            return jsonify({'ok': False, 'error': 'לא סופקו שדות לעדכון'}), 400
        
        db.code_snippets.update_one({'_id': oid}, {'$set': updates})
        
        # Invalidate cache
        try:
            cache.invalidate_file_related(file_id, user_id)
        except Exception:
            pass
        
        return jsonify({
            'ok': True,
            'updated_fields': list(updates.keys())
        })
        
    except Exception as e:
        logger.exception(f"Error in quick update: {e}")
        return jsonify({'ok': False, 'error': 'שגיאה בעדכון'}), 500


@app.route('/api/file/<file_id>/dismiss-attention', methods=['POST'])
@login_required
def api_file_dismiss_attention(file_id):
    """
    דוחה קובץ מרשימת "דורש טיפול" (הסתרה זמנית).
    Body: { "days": 30 } - מספר ימים להסתרה (ברירת מחדל: 30)
    
    אפשרויות מומלצות: 7, 30, 90 ימים.
    """
    try:
        user_id = session['user_id']
        db = get_db()
        
        try:
            oid = ObjectId(file_id)
        except Exception:
            return jsonify({'ok': False, 'error': 'מזהה לא תקין'}), 400
        
        # וידוא בעלות
        doc = db.code_snippets.find_one({
            '_id': oid,
            'user_id': user_id,
            'is_active': True
        }, {'_id': 1})
        
        if not doc:
            return jsonify({'ok': False, 'error': 'הקובץ לא נמצא'}), 404
        
        data = request.get_json() or {}
        is_forever = bool(data.get('forever'))
        now = datetime.now(timezone.utc)
        
        if is_forever:
            update = {
                '$set': {
                    'dismissed_at': now,
                    'forever': True
                },
                '$unset': {
                    'expires_at': '',
                    'days': ''
                }
            }
        else:
            days = min(max(int(data.get('days', 30)), 1), 365)  # 1-365 ימים
            expires_at = now + timedelta(days=days)
            update = {
                '$set': {
                    'dismissed_at': now,
                    'expires_at': expires_at,
                    'days': days,
                    'forever': False
                }
            }
        
        # שמירה ב-collection ייעודי
        db.attention_dismissals.update_one(
            {'user_id': user_id, 'file_id': oid},
            update,
            upsert=True
        )
        
        payload = {'ok': True, 'forever': is_forever}
        if not is_forever:
            payload.update({
                'dismissed_until': expires_at.isoformat(),
                'days': days
            })
        return jsonify(payload)
        
    except Exception as e:
        logger.exception(f"Error in dismiss attention: {e}")
        return jsonify({'ok': False, 'error': 'שגיאה בדחייה'}), 500


@app.route('/api/file/<file_id>/history', methods=['GET'])
@login_required
def api_file_history(file_id):
    """היסטוריית גרסאות עבור קובץ ספציפי."""
    db = get_db()
    user_id = session['user_id']
    file_doc = _get_user_file_by_id(db, user_id, file_id)
    if not file_doc:
        return jsonify({'ok': False, 'error': 'קובץ לא נמצא'}), 404

    file_name = (file_doc.get('file_name') or '').strip()
    if not file_name:
        return jsonify({'ok': False, 'error': 'שם קובץ חסר'}), 400

    try:
        docs = list(db.code_snippets.find(
            {
                'user_id': user_id,
                'file_name': file_name,
'is_active': True,
            },
            {
                '_id': 1,
                'version': 1,
                'created_at': 1,
                'updated_at': 1,
                'description': 1,
                'file_size': 1,
                'lines_count': 1,
            },
            sort=[('version', DESCENDING)],
        ).limit(FILE_HISTORY_MAX_VERSIONS))
    except Exception:
        return jsonify({'ok': False, 'error': 'שגיאה בטעינת היסטוריה'}), 500

    versions: List[Dict[str, Any]] = []
    latest_version = 0
    if docs:
        try:
            latest_version = int(docs[0].get('version') or 0)
        except Exception:
            latest_version = 0
    for doc in docs:
        version_number = int(doc.get('version') or 0)
        try:
            size_bytes = int(doc.get('file_size') or 0)
        except Exception:
            size_bytes = 0
        try:
            line_count = int(doc.get('lines_count') or 0)
        except Exception:
            line_count = 0
        versions.append({
            'id': str(doc.get('_id')),
            'version': version_number,
            'is_current': version_number == latest_version,
            'created_at': format_datetime_display(doc.get('created_at')),
            'updated_at': format_datetime_display(doc.get('updated_at')),
            'iso_created': safe_iso(doc.get('created_at'), 'created_at'),
            'iso_updated': safe_iso(doc.get('updated_at'), 'updated_at'),
            'line_count': line_count,
            'size': format_file_size(size_bytes),
            'file_size': size_bytes,
            'lines_count': line_count,
            'description': (doc.get('description') or '').strip(),
        })

    return jsonify({
        'ok': True,
        'file_name': file_name,
        'versions': versions,
        'latest_version': latest_version,
    })


@app.route('/api/file/<file_id>/restore', methods=['POST'])
@login_required
def api_restore_file_version(file_id):
    """שחזור גרסה: מוסיף גרסה חדשה המבוססת על גרסה קודמת."""
    db = get_db()
    user_id = session['user_id']
    payload = request.get_json(silent=True) or {}
    try:
        version_num = int(payload.get('version') or 0)
    except Exception:
        version_num = 0
    if version_num < 1:
        return jsonify({'ok': False, 'error': 'מספר גרסה לא חוקי'}), 400

    file_doc = _get_user_file_by_id(db, user_id, file_id)
    if not file_doc:
        return jsonify({'ok': False, 'error': 'קובץ לא נמצא'}), 404

    file_name = (file_doc.get('file_name') or '').strip()
    if not file_name:
        return jsonify({'ok': False, 'error': 'שם קובץ חסר'}), 400

    try:
        version_doc = db.code_snippets.find_one({
            'user_id': user_id,
            'file_name': file_name,
            'version': version_num,
        })
    except Exception:
        version_doc = None
    if not version_doc:
        return jsonify({'ok': False, 'error': 'הגרסה לא נמצאה'}), 404

    try:
        latest_doc = db.code_snippets.find_one(
            {
                'user_id': user_id,
                'file_name': file_name,
'is_active': True,
            },
            sort=[('version', DESCENDING)],
        )
    except Exception:
        latest_doc = None

    latest_version = int((latest_doc or {}).get('version') or 0)
    next_version = latest_version + 1

    code_value = version_doc.get('code') or ''
    if not isinstance(code_value, str):
        code_value = str(code_value or '')

    language = (
        version_doc.get('programming_language')
        or (latest_doc or {}).get('programming_language')
        or file_doc.get('programming_language')
        or 'text'
    )
    description = version_doc.get('description')
    if description is None:
        description = (latest_doc or {}).get('description') or file_doc.get('description') or ''

    tags = version_doc.get('tags')
    if not isinstance(tags, list):
        try:
            tags = list(tags or [])
        except Exception:
            tags = []
    if not tags:
        try:
            tags = list((latest_doc or {}).get('tags') or [])
        except Exception:
            tags = []

    now = datetime.now(timezone.utc)
    new_doc: Dict[str, Any] = {
        'user_id': user_id,
        'file_name': file_name,
        'code': code_value,
        'programming_language': language,
        'description': description,
        'tags': tags,
        'version': next_version,
        'created_at': now,
        'updated_at': now,
        'is_active': True,
        'is_favorite': bool((latest_doc or {}).get('is_favorite', file_doc.get('is_favorite', False))),
        'favorited_at': (latest_doc or {}).get('favorited_at'),
    }
    source_url = version_doc.get('source_url') or file_doc.get('source_url')
    if source_url:
        new_doc['source_url'] = source_url

    try:
        res = db.code_snippets.insert_one(new_doc)
    except Exception:
        return jsonify({'ok': False, 'error': 'שמירת הגרסה נכשלה'}), 500

    inserted_id = str(getattr(res, 'inserted_id', '') or '')
    try:
        cache.invalidate_user_cache(int(user_id))
        cache.invalidate_file_related(file_id=file_name, user_id=user_id)
    except Exception:
        pass

    try:
        _log_webapp_user_activity()
        session['_skip_view_activity_once'] = True
    except Exception:
        pass

    return jsonify({
        'ok': True,
        'file_id': inserted_id,
        'version': next_version,
    })


@app.route('/api/file/<file_id>/trash', methods=['POST'])
@login_required
def api_file_move_to_trash(file_id):
    """העברה רכה לסל המיחזור מתוך עמוד הקובץ."""
    db = get_db()
    user_id = session['user_id']
    file_doc = _get_user_file_by_id(db, user_id, file_id)
    if not file_doc:
        return jsonify({'ok': False, 'error': 'קובץ לא נמצא'}), 404

    file_name = (file_doc.get('file_name') or '').strip()
    if not file_name:
        return jsonify({'ok': False, 'error': 'שם קובץ חסר'}), 400

    if not bool(file_doc.get('is_active', True)):
        return jsonify({'ok': False, 'error': 'הקובץ כבר הועבר לסל'}), 409

    now = datetime.now(timezone.utc)
    ttl_days = WEBAPP_SINGLE_DELETE_TTL_DAYS
    expires_at = now + timedelta(days=ttl_days)

    try:
        res = db.code_snippets.update_many(
            {
                'user_id': user_id,
                'file_name': file_name,
'is_active': True,
            },
            {'$set': {
                'is_active': False,
                'updated_at': now,
                'deleted_at': now,
                'deleted_expires_at': expires_at,
            }},
        )
    except Exception:
        return jsonify({'ok': False, 'error': 'שגיאה בהעברה לסל'}), 500

    modified_count = int(getattr(res, 'modified_count', 0) or 0)
    if not modified_count:
        return jsonify({'ok': False, 'error': 'לא נמצאה גרסה פעילה'}), 409

    try:
        cache.invalidate_user_cache(int(user_id))
        cache.delete_pattern(f"collections_*:{int(user_id)}:*")
    except Exception:
        pass
    try:
        _log_webapp_user_activity()
    except Exception:
        pass

    message = f'הקובץ הועבר לסל המיחזור ל-{ttl_days} ימים'
    return jsonify({'ok': True, 'message': message, 'affected': modified_count})


@app.route('/api/trash/<file_id>/restore', methods=['POST'])
@login_required
@traced("files.recycle_bin_restore")
def api_recycle_bin_restore(file_id: str):
    """שחזור פריט מסל המחזור לפי מזהה מסמך (קוד רגיל או קובץ גדול)."""
    db = get_db()
    user_id = session['user_id']
    try:
        oid = ObjectId(file_id)
    except Exception:
        return jsonify({'ok': False, 'error': 'Invalid file id'}), 400

    now = datetime.now(timezone.utc)
    modified = 0

    try:
        res = db.code_snippets.update_many(
            {'_id': oid, 'user_id': user_id, 'is_active': False},
            {'$set': {'is_active': True, 'updated_at': now},
             '$unset': {'deleted_at': '', 'deleted_expires_at': ''}},
        )
        modified += int(getattr(res, 'modified_count', 0) or 0)
    except Exception:
        pass

    if modified == 0:
        large_coll = getattr(db, 'large_files', None)
        if large_coll is not None:
            try:
                res2 = large_coll.update_many(
                    {'_id': oid, 'user_id': user_id, 'is_active': False},
                    {'$set': {'is_active': True, 'updated_at': now},
                     '$unset': {'deleted_at': '', 'deleted_expires_at': ''}},
                )
                modified += int(getattr(res2, 'modified_count', 0) or 0)
            except Exception:
                pass

    if modified == 0:
        return jsonify({'ok': False, 'error': 'not_found'}), 404

    try:
        cache.invalidate_user_cache(int(user_id))
        cache.delete_pattern(f"collections_*:{int(user_id)}:*")
    except Exception:
        pass

    return jsonify({'ok': True, 'restored': modified})


@app.route('/api/trash/<file_id>/purge', methods=['POST'])
@login_required
@traced("files.recycle_bin_purge")
def api_recycle_bin_purge(file_id: str):
    """מחיקה סופית מפריט בסל המחזור לפי מזהה מסמך."""
    db = get_db()
    user_id = session['user_id']
    try:
        oid = ObjectId(file_id)
    except Exception:
        return jsonify({'ok': False, 'error': 'Invalid file id'}), 400

    deleted = 0
    try:
        res = db.code_snippets.delete_many({'_id': oid, 'user_id': user_id, 'is_active': False})
        deleted += int(getattr(res, 'deleted_count', 0) or 0)
    except Exception:
        pass

    if deleted == 0:
        large_coll = getattr(db, 'large_files', None)
        if large_coll is not None:
            try:
                res2 = large_coll.delete_many({'_id': oid, 'user_id': user_id, 'is_active': False})
                deleted += int(getattr(res2, 'deleted_count', 0) or 0)
            except Exception:
                pass

    if deleted == 0:
        return jsonify({'ok': False, 'error': 'not_found'}), 404

    try:
        cache.invalidate_user_cache(int(user_id))
        cache.delete_pattern(f"collections_*:{int(user_id)}:*")
    except Exception:
        pass

    return jsonify({'ok': True, 'deleted': deleted})

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
        raw_cursor = db.recent_opens.find(
            {'user_id': user_id},
            {
                'last_opened_file_id': 1,
                'file_name': 1,
                'language': 1,
                'last_opened_at': 1,
            },
        ) \
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
'is_active': True
                        }
                        file_doc = db.code_snippets.find_one(
                            q,
                            {
                                'file_name': 1,
                                'programming_language': 1,
                                'file_size': 1,
                                'lines_count': 1,
                            },
                        )
                    except Exception:
                        file_doc = None

                # fallback: אם אין מסמך לפי מזהה – נסה לפי שם הקובץ העדכני
                if file_doc is None and file_name_hint:
                    try:
                        file_doc = db.code_snippets.find_one(
                            {
                                'user_id': user_id,
                                'file_name': file_name_hint,
'is_active': True
                            },
                            {
                                'file_name': 1,
                                'programming_language': 1,
                                'file_size': 1,
                                'lines_count': 1,
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

                # שים לב: לא מושכים `code` רק כדי לחשב גודל — זה כבד מאוד על DB.
                # אם `file_size` לא קיים (מסמכים ישנים) נחזיר 0; זה עדיף על האטה/תקיעות.
                try:
                    size_bytes = int(file_doc.get('file_size') or 0)
                except Exception:
                    size_bytes = 0
                try:
                    lines_count = int(file_doc.get('lines_count') or 0)
                except Exception:
                    lines_count = 0
                lang = (file_doc.get('programming_language') or rdoc.get('language') or 'text')

                results.append({
                    'id': sid,
                    'filename': str(file_doc.get('file_name') or file_name_hint or ''),
                    'language': str(lang).lower(),
                    'size': size_bytes,
                    'file_size': size_bytes,
                    'lines_count': lines_count,
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
'is_active': True,
                },
                sort=[('version', DESCENDING), ('updated_at', DESCENDING), ('_id', DESCENDING)],
            )
        except Exception:
            doc = None

        if not doc:
            trashed_doc = None
            try:
                trashed_doc = db.code_snippets.find_one(
                    {
                        'user_id': user_id,
                        'file_name': name,
                        '$or': [
                            {'is_active': False},
                            {'deleted_at': {'$exists': True}},
                            {'deleted_expires_at': {'$exists': True}},
                        ],
                    },
                    sort=[('version', DESCENDING), ('updated_at', DESCENDING), ('_id', DESCENDING)],
                )
            except Exception:
                trashed_doc = None

            if trashed_doc:
                return jsonify({
                    'ok': False,
                    'error': 'in_recycle_bin',
                    'file_name': trashed_doc.get('file_name'),
                    'deleted_at': safe_iso(trashed_doc.get('deleted_at'), 'deleted_at'),
                    'recycle_expires_at': safe_iso(trashed_doc.get('deleted_expires_at'), 'deleted_expires_at'),
                })
            return jsonify({'ok': False, 'error': 'not_found'})

        lang = (doc.get('programming_language') or 'text').lower()
        return jsonify({'ok': True, 'id': str(doc.get('_id')), 'file_name': doc.get('file_name'), 'language': lang})
    except Exception as e:
        try:
            logger.error('api_resolve_file_by_name failed: %s', e)
        except Exception:
            pass
        return jsonify({'ok': False, 'error': 'internal_error'}), 500


def _sync_collection_items_after_web_rename(db, user_id: int, old_name: str, new_name: str) -> None:
    """Ensure My Collections reflect renamed files when שינוי שם נעשה מהווב."""
    if not old_name or not new_name or old_name == new_name:
        return
    coll = getattr(db, 'collection_items', None)
    if coll is None:
        return
    try:
        coll.update_many(
            {"user_id": int(user_id), "file_name": str(old_name)},
            {"$set": {"file_name": str(new_name), "updated_at": datetime.now(timezone.utc)}},
        )
    except Exception as exc:  # pragma: no cover - best effort
        try:
            logger.warning(
                "collections rename sync failed",
                extra={"user_id": user_id, "old_name": old_name, "new_name": new_name, "error": str(exc)},
            )
        except Exception:
            pass
        return
    try:
        cache.invalidate_user_cache(int(user_id))
    except Exception:
        pass
    try:
        cache.delete_pattern(f"collections_*:{int(user_id)}:*")
    except Exception:
        pass

@app.route('/edit/<file_id>', methods=['GET', 'POST'])
@login_required
def edit_file_page(file_id):
    """עריכת קובץ קיים: טופס עריכה ושמירת גרסה חדשה."""
    db = get_db()
    user_id = session['user_id']
    try:
        file, kind = _get_user_any_file_by_id(db, user_id, file_id)
    except Exception as e:
        logger.exception("DB error fetching file for edit", extra={"file_id": file_id, "user_id": user_id, "error": str(e)})
        abort(500)
    if not file:
        abort(404)
    is_large = (kind == "large")

    original_file_name = str(file.get('file_name') or '')
    error = None
    success = None

    # --- Large files: עדכון במקום (ללא "גרסאות") ---
    if request.method == 'POST' and is_large:
        try:
            file_name = (request.form.get('file_name') or '').strip()
            content = request.form.get('code') or ''
            content = normalize_code(content)
            language = (request.form.get('language') or '').strip() or (file.get('programming_language') or 'text')
            description = (request.form.get('description') or '').strip()
            raw_tags = (request.form.get('tags') or '').strip()
            tags = [t.strip() for t in re.split(r'[,#\n]+', raw_tags) if t.strip()] if raw_tags else list(file.get('tags') or [])

            raw_source_url = (request.form.get('source_url') or '').strip()
            source_url_state = (request.form.get('source_url_touched') or '').strip().lower()
            source_url_was_edited = source_url_state == 'edited'

            if not file_name:
                error = 'יש להזין שם קובץ'
            if not content and not error:
                error = 'יש להזין תוכן קוד'

            update_doc: Dict[str, Any] = {}
            if not error and source_url_was_edited:
                if raw_source_url:
                    clean_source_url, source_url_err = _normalize_source_url_value(raw_source_url)
                    if source_url_err:
                        error = source_url_err
                    else:
                        update_doc['source_url'] = clean_source_url or ''
                else:
                    update_doc['source_url'] = ''

            if not error:
                now = datetime.now(timezone.utc)
                update_doc.update({
                    'file_name': file_name,
                    'content': content,
                    'programming_language': language,
                    'description': description,
                    'tags': tags,
                    'file_size': len(content.encode('utf-8')),
                    'lines_count': len(content.split('\n')),
                    'updated_at': now,
                })
                large_coll = getattr(db, 'large_files', None)
                if large_coll is None:
                    error = "לא ניתן לערוך קבצים גדולים בסביבה זו (large_files לא זמין)."
                else:
                    res = large_coll.update_one(
                        {'_id': ObjectId(file_id), 'user_id': user_id, 'is_active': {'$ne': False}},
                        {'$set': update_doc},
                    )
                    acknowledged = bool(getattr(res, "acknowledged", False))
                    matched = int(getattr(res, "matched_count", 0) or 0)
                    modified = int(getattr(res, "modified_count", 0) or 0)
                    if not acknowledged:
                        error = "❌ השמירה נכשלה (DB לא אישר את העדכון)."
                    elif matched <= 0:
                        # לדוגמה: הקובץ הועבר לסל/סומן כלא-פעיל בזמן שהמשתמש ערך
                        error = "⚠️ הקובץ כבר לא זמין לעריכה (ייתכן שנמחק/הועבר לסל). רענן את הדף ונסה שוב."
                    else:
                        try:
                            _sync_collection_items_after_web_rename(db, user_id, original_file_name, file_name)
                        except Exception:
                            pass
                        try:
                            cache.invalidate_user_cache(int(user_id))
                        except Exception:
                            pass
                        success = "✅ נשמר" if modified > 0 else "✅ נשמר (ללא שינוי)"
                        try:
                            refreshed = large_coll.find_one(
                                {'_id': ObjectId(file_id), 'user_id': user_id, 'is_active': {'$ne': False}}
                            )
                            if isinstance(refreshed, dict):
                                file = refreshed
                        except Exception:
                            pass
        except Exception as exc:
            logger.exception("Error saving large file", extra={"file_id": file_id, "user_id": user_id, "error": str(exc)})
            error = "אירעה שגיאה בשמירה"

    if request.method == 'POST' and not is_large:
        try:
            file_name = (request.form.get('file_name') or '').strip()
            code = request.form.get('code') or ''
            # נרמול התוכן כדי להסיר תווים נסתרים וליישר פורמט עוד לפני שמירה
            code = normalize_code(code)
            language = (request.form.get('language') or '').strip() or (file.get('programming_language') or 'text')
            description = (request.form.get('description') or '').strip()
            raw_tags = (request.form.get('tags') or '').strip()
            tags = [t.strip() for t in re.split(r'[,#\n]+', raw_tags) if t.strip()] if raw_tags else list(file.get('tags') or [])
            raw_source_url = request.form.get('source_url') or ''
            source_url_value = raw_source_url.strip()
            source_url_state = (request.form.get('source_url_touched') or '').strip().lower()
            source_url_was_edited = source_url_state == 'edited'
            clean_source_url = None
            source_url_removed = False
            markdown_image_payloads: List[Dict[str, Any]] = []
            deleted_image_obj_ids: List[ObjectId] = []
            try:
                deleted_raw = (request.form.get('deleted_images') or '').strip()
            except Exception:
                deleted_raw = ''
            if deleted_raw:
                deleted_ids: List[str] = []
                try:
                    parsed = json.loads(deleted_raw)
                    if isinstance(parsed, list):
                        deleted_ids = [str(x) for x in parsed if str(x).strip()]
                except Exception:
                    # fallback: "a,b,c" / "a b c"
                    try:
                        deleted_ids = [p.strip() for p in re.split(r'[,\s]+', deleted_raw) if p.strip()]
                    except Exception:
                        deleted_ids = []
                for raw_id in deleted_ids:
                    try:
                        deleted_image_obj_ids.append(ObjectId(raw_id))
                    except Exception:
                        continue
            if source_url_value:
                clean_source_url, source_url_err = _normalize_source_url_value(source_url_value)
                if source_url_err:
                    error = source_url_err
                elif clean_source_url:
                    source_url_value = clean_source_url
            elif source_url_was_edited:
                source_url_removed = True
            if source_url_was_edited:
                file['source_url'] = source_url_value

            if not file_name and not error:
                error = 'יש להזין שם קובץ'
            if not code and not error:
                error = 'יש להזין תוכן קוד'
            if not error:
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
'is_active': True
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

                # תמונות ל-Markdown (כמו במסך יצירה): נשמרות כ-attachments לפי גרסה
                # חשוב: ה-Frontend מאפשר לצרף תמונות גם כשנבחרה שפת Markdown ב-Dropdown,
                # גם אם שם הקובץ לא מסתיים ב-.md/.markdown. כדי למנוע איבוד מידע, נאסוף תמונות גם לפי השפה.
                is_md_extension = isinstance(file_name, str) and file_name.lower().endswith(('.md', '.markdown'))
                try:
                    lang_value = str(language or request.form.get('language') or '').strip().lower()
                except Exception:
                    lang_value = ''
                is_md_language = lang_value in ('markdown', 'md')
                should_collect_images = is_md_extension or is_md_language
                if not error and should_collect_images:
                    # נשאיל תמונות קיימות מהגרסה הנוכחית (אלא אם המשתמש סימן למחיקה)
                    carry_payloads: List[Dict[str, Any]] = []
                    try:
                        query: Dict[str, Any] = {'snippet_id': file.get('_id'), 'user_id': user_id}
                        if deleted_image_obj_ids:
                            query['_id'] = {'$nin': deleted_image_obj_ids}
                        cursor = db.markdown_images.find(query).sort('order', 1)
                        for doc in cursor:
                            data = doc.get('data')
                            if data is None:
                                continue
                            try:
                                raw = bytes(data)
                            except Exception:
                                raw = b''
                            if not raw:
                                continue
                            carry_payloads.append({
                                'filename': doc.get('file_name') or 'image',
                                'content_type': (doc.get('content_type') or 'application/octet-stream'),
                                'size': int(doc.get('size') or len(raw)),
                                'data': raw,
                            })
                    except Exception:
                        carry_payloads = []

                    try:
                        incoming_images = request.files.getlist('md_images')
                    except Exception:
                        incoming_images = []
                    valid_images = [img for img in incoming_images if getattr(img, 'filename', '').strip()]
                    # מגבלת כמות: קיימות (שלא נמחקו) + חדשות
                    if (carry_payloads or valid_images) and (len(carry_payloads) + len(valid_images)) > MARKDOWN_IMAGE_LIMIT:
                        error = f'ניתן לצרף עד {MARKDOWN_IMAGE_LIMIT} תמונות'
                    if not error:
                        markdown_image_payloads.extend(carry_payloads)
                        for img in valid_images:
                            if error:
                                break
                            try:
                                data = img.read()
                            except Exception:
                                data = b''
                            if not data:
                                continue
                            if len(data) > MARKDOWN_IMAGE_MAX_BYTES:
                                max_mb = max(1, MARKDOWN_IMAGE_MAX_BYTES // (1024 * 1024))
                                error = f'כל תמונה מוגבלת ל-{max_mb}MB'
                                break
                            safe_name = secure_filename(img.filename or '') or f'image_{len(markdown_image_payloads) + 1}.png'
                            content_type = (img.mimetype or '').lower()
                            if content_type not in ALLOWED_MARKDOWN_IMAGE_TYPES:
                                guessed_type = mimetypes.guess_type(safe_name)[0] or ''
                                content_type = guessed_type.lower() if guessed_type else content_type
                            if content_type not in ALLOWED_MARKDOWN_IMAGE_TYPES:
                                error = 'ניתן להעלות רק תמונות PNG, JPG, WEBP או GIF'
                                break
                            markdown_image_payloads.append({
                                'filename': safe_name,
                                'content_type': content_type,
                                'size': len(data),
                                'data': data,
                            })
                        if error:
                            markdown_image_payloads = []

                # אם ולידציית תמונות (או כל ולידציה אחרת) קבעה error – לא נשמור גרסה חדשה
                if not error:
                    now = datetime.now(timezone.utc)
                    pinned_info = None
                    pinned_source_name = None
                    try:
                        if bool(file.get('is_pinned', False)):
                            pinned_info = file
                            pinned_source_name = file.get('file_name') or original_file_name or file_name
                        else:
                            candidate_name = original_file_name or file.get('file_name') or file_name
                            if candidate_name:
                                try:
                                    pinned_info = db.code_snippets.find_one(
                                        {
                                            'user_id': user_id,
                                            'file_name': candidate_name,
                                            'is_active': True,
                                            'is_pinned': True,
                                        },
                                        sort=[('version', -1)],
                                    )
                                except TypeError:
                                    pinned_info = db.code_snippets.find_one({
                                        'user_id': user_id,
                                        'file_name': candidate_name,
                                        'is_active': True,
                                        'is_pinned': True,
                                    })
                                if pinned_info:
                                    pinned_source_name = pinned_info.get('file_name') or candidate_name
                    except Exception:
                        pinned_info = None
                        pinned_source_name = None
                    if pinned_info is None:
                        try:
                            same_name = True
                            if original_file_name and file_name and original_file_name != file_name:
                                same_name = False
                            if same_name and bool((prev or {}).get('is_pinned', False)):
                                pinned_info = prev
                                pinned_source_name = (prev or {}).get('file_name') or original_file_name or file_name
                        except Exception:
                            pinned_info = None
                            pinned_source_name = None

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
                    if pinned_info:
                        new_doc['is_pinned'] = True
                        try:
                            pinned_at = pinned_info.get('pinned_at')
                        except Exception:
                            pinned_at = None
                        new_doc['pinned_at'] = pinned_at if pinned_at is not None else now
                        try:
                            new_doc['pin_order'] = int(pinned_info.get('pin_order', 0) or 0)
                        except Exception:
                            new_doc['pin_order'] = 0
                    prev_source = None
                    try:
                        prev_source = (prev or file or {}).get('source_url')
                    except Exception:
                        prev_source = None
                    if clean_source_url:
                        new_doc['source_url'] = clean_source_url
                    elif not source_url_removed and prev_source:
                        new_doc['source_url'] = prev_source
                    try:
                        res = db.code_snippets.insert_one(new_doc)
                        if res and getattr(res, 'inserted_id', None):
                            if new_doc.get('is_pinned'):
                                unpin_errors: List[Dict[str, Any]] = []
                                try:
                                    unpin_query = {
                                        'user_id': user_id,
                                        'file_name': file_name,
                                        'is_pinned': True,
                                        'is_active': True,
                                        '_id': {'$ne': res.inserted_id},
                                    }
                                    db.code_snippets.update_many(
                                        unpin_query,
                                        {'$set': {
                                            'is_pinned': False,
                                            'pinned_at': None,
                                            'pin_order': 0,
                                            'updated_at': now,
                                        }},
                                    )
                                except Exception as exc:
                                    unpin_errors.append({"scope": "same_name", "error": str(exc)})
                                if pinned_source_name and pinned_source_name != file_name:
                                    try:
                                        db.code_snippets.update_many(
                                            {
                                                'user_id': user_id,
                                                'file_name': pinned_source_name,
                                                'is_pinned': True,
                                                'is_active': True,
                                                '_id': {'$ne': res.inserted_id},
                                            },
                                            {'$set': {
                                                'is_pinned': False,
                                                'pinned_at': None,
                                                'pin_order': 0,
                                                'updated_at': now,
                                            }},
                                        )
                                    except Exception as exc:
                                        unpin_errors.append({"scope": "old_name", "error": str(exc)})
                                if unpin_errors:
                                    try:
                                        emit_event(
                                            "edit_file_unpin_failed",
                                            severity="warning",
                                            user_id=int(user_id),
                                            file_id=str(res.inserted_id),
                                            file_name=str(file_name),
                                            pinned_source_name=str(pinned_source_name or ""),
                                            errors=unpin_errors,
                                        )
                                    except Exception:
                                        pass
                                    try:
                                        logger.warning(
                                            "Failed to unpin previous pinned docs after edit",
                                            extra={
                                                "user_id": int(user_id),
                                                "file_id": str(res.inserted_id),
                                                "file_name": str(file_name),
                                                "pinned_source_name": str(pinned_source_name or ""),
                                                "errors": unpin_errors,
                                            },
                                        )
                                    except Exception:
                                        pass
                            try:
                                # איפוס טיוטת עריכה מקומית רק לאחר שמירה מוצלחת (redirect ל-view)
                                session[_EDIT_CLEAR_DRAFT_SESSION_KEY] = str(file_id)
                            except Exception:
                                pass
                            if markdown_image_payloads:
                                try:
                                    _save_markdown_images(db, user_id, res.inserted_id, markdown_image_payloads)
                                except Exception:
                                    pass
                            if original_file_name and original_file_name != file_name:
                                _sync_collection_items_after_web_rename(db, user_id, original_file_name, file_name)
                            if _log_webapp_user_activity():
                                session['_skip_view_activity_once'] = True
                            return redirect(url_for('view_file', file_id=str(res.inserted_id)))
                        error = 'שמירת הקובץ נכשלה'
                    except Exception as _e:
                        error = f'שמירת הקובץ נכשלה: {_e}'
        except Exception as e:
            error = f'שגיאה בעריכה: {e}'

    # טופס עריכה (GET או POST עם שגיאה)
    try:
        user_langs = db.code_snippets.distinct('programming_language', {'user_id': user_id}) if db is not None else []
    except Exception:
        user_langs = []
    languages = _build_language_choices(user_langs)

    # המרה לנתונים לתבנית
    code_value = file.get('code') or file.get('content') or ''
    file_data = {
        'id': str(file.get('_id')),
        'file_name': file.get('file_name') or '',
        'language': file.get('programming_language') or 'text',
        'description': file.get('description') or '',
        'tags': file.get('tags') or [],
        'version': (file.get('version', 1) if not is_large else None),
        'is_large': bool(is_large),
        'source_url': file.get('source_url') or '',
    }

    # תמונות Markdown לגרסה הנוכחית (לצורך תצוגה/מחיקה ב-edit) — רק לקבצים רגילים
    existing_images: List[Dict[str, Any]] = []
    if not is_large:
        try:
            cursor = db.markdown_images.find(
                {'snippet_id': file.get('_id'), 'user_id': user_id}
            ).sort('order', 1)
            for img in cursor:
                existing_images.append({
                    'id': str(img.get('_id')),
                    'url': url_for('get_markdown_image', file_id=file_id, image_id=str(img.get('_id'))),
                    'name': img.get('file_name') or 'image',
                })
        except Exception:
            existing_images = []

    return render_template('edit_file.html',
                         user=session['user_data'],
                         file=file_data,
                         code_value=code_value,
                         languages=languages,
                         existing_images=existing_images,
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
        file, _kind = _get_user_any_file_by_id(db, user_id, file_id)
    except Exception as e:
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
    body = (file.get('code') or file.get('content') or '')
    file_content = BytesIO(str(body).encode('utf-8'))
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
        file, _kind = _get_user_any_file_by_id(db, user_id, file_id)
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
        file, _kind = _get_user_any_file_by_id(db, user_id, file_id)
    except Exception:
        abort(404)
    if not file:
        abort(404)

    code = (file.get('code') or file.get('content') or '')
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
        file, _kind = _get_user_any_file_by_id(db, user_id, file_id)
    except Exception:
        abort(404)
    if not file:
        abort(404)

    file_name = (file.get('file_name') or '').strip()
    language = (file.get('programming_language') or '').strip().lower()
    # אם סומן כ-text אך הסיומת .md – התייחס אליו כ-markdown
    if (not language or language == 'text') and file_name.lower().endswith('.md'):
        language = 'markdown'
    code = (file.get('code') or file.get('content') or '')

    # כיבוי קאש יזום לפי פרמטר no_cache/nc
    try:
        _no_cache_param = (request.args.get('no_cache') or request.args.get('nc') or '').strip().lower()
        force_no_cache = _no_cache_param in ('1', 'true', 'yes')
    except Exception:
        force_no_cache = False

    # --- HTTP cache validators (ETag / Last-Modified) ---
    theme_key = _get_theme_etag_key(user_id)
    etag = _compute_file_etag(file, variant=theme_key)
    last_modified_dt = _safe_dt_from_doc(file.get('updated_at') or file.get('created_at'))
    last_modified_str = http_date(last_modified_dt)
    inm = request.headers.get('If-None-Match')
    if not force_no_cache and inm and inm == etag:
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
        if not force_no_cache and ims_dt is not None and last_modified_dt.replace(microsecond=0) <= ims_dt:
            resp = Response(status=304)
            resp.headers['ETag'] = etag
            resp.headers['Last-Modified'] = last_modified_str
            return resp

    # --- Cache: תוצר ה-HTML של תצוגת Markdown (תבנית) ---
    should_cache = getattr(cache, 'is_enabled', False)
    md_cache_key = None
    if should_cache and not force_no_cache:
        try:
            # בתצוגה זו התוכן מגיע כתוכן גולמי ומעובד בצד לקוח; ה-HTML תלוי רק בפרמטרים הללו
            _params = {
                'file_name': file_name,
                'lang': 'markdown',
                'theme': theme_key,
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
            try:
                fallback_hash = hashlib.sha256(str(theme_key).encode('utf-8')).hexdigest()[:12]
            except Exception:
                fallback_hash = "theme"
            md_cache_key = f"web:md_preview:user:{user_id}:{file_id}:{fallback_hash}:fallback"

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
    # בדיקת הרשאת אדמין כדי לאפשר פיצ'רים ייעודיים בצד לקוח (ללא שינוי תוכן)
    actual_is_admin = False
    try:
        actual_is_admin = bool(is_admin(int(user_id)))
    except Exception:
        actual_is_admin = False
    if is_impersonating_safe():
        user_is_admin = False
    else:
        user_is_admin = actual_is_admin

    html = render_template(
        'md_preview.html',
        user=session.get('user_data', {}),
        file=file_data,
        md_code=code,
        bot_username=BOT_USERNAME_CLEAN,
        can_save_shared=False,
        is_admin=user_is_admin,
    )
    # אפשרות לעקיפת קאש לדף הזה לפי פרמטר no_cache/nc — לאחר הרנדר אך לפני אחסון בקאש
    if force_no_cache:
        resp = Response(html, mimetype='text/html; charset=utf-8')
        resp.headers['ETag'] = etag
        resp.headers['Last-Modified'] = last_modified_str
        resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate'
        resp.headers['Pragma'] = 'no-cache'
        return resp

    if should_cache and md_cache_key and not force_no_cache:
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


@app.route('/read/<path:filename>')
@login_required
def reader_mode(filename):
    """Reader mode for markdown files by file name."""
    db = get_db()
    user_id = session['user_id']
    name = (filename or '').strip()
    if not name:
        abort(404)

    try:
        doc = db.code_snippets.find_one(
            {
                'user_id': user_id,
                'file_name': name,
                'is_active': True,
            },
            sort=[('version', DESCENDING), ('updated_at', DESCENDING), ('_id', DESCENDING)],
        )
    except Exception as e:
        logger.exception("DB error fetching file for reader mode", extra={
            "file_name": name,
            "user_id": user_id,
            "error": str(e),
        })
        abort(500)

    if not doc:
        abort(404)

    theme_key = _get_theme_etag_key(user_id)
    etag = _compute_file_etag(doc, variant=theme_key)
    last_modified_dt = _safe_dt_from_doc(doc.get('updated_at') or doc.get('created_at'))
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

    file_name = (doc.get('file_name') or 'README.md').strip() or 'README.md'
    language = (doc.get('programming_language') or '').strip().lower()
    if (not language or language == 'text') and file_name.lower().endswith('.md'):
        language = 'markdown'
    is_markdown = language == 'markdown' or file_name.lower().endswith(('.md', '.markdown'))
    if not is_markdown:
        return redirect(url_for('view_file', file_id=str(doc.get('_id'))))

    code = (doc.get('code') or doc.get('content') or '')
    rendered_html, pygments_css = _render_markdown_preview(code)
    back_url = url_for('md_preview', file_id=str(doc.get('_id')))

    html = render_template(
        'reader_mode.html',
        title=file_name,
        subtitle=None,
        content=rendered_html,
        pygments_css=pygments_css,
        back_url=back_url,
    )
    resp = Response(html, mimetype='text/html; charset=utf-8')
    resp.headers['ETag'] = etag
    resp.headers['Last-Modified'] = last_modified_str
    return resp


# ============================================
# Styled HTML Export Routes
# ============================================


@app.route('/export/styled/<file_id>', methods=['GET', 'POST'])
@login_required
@premium_or_admin_required
@traced("export.styled_html")
def export_styled_html(file_id):
    """
    ייצוא קובץ Markdown כ-HTML מעוצב להורדה.

    GET Query params:
        theme: מזהה ערכת הנושא (default: tech-guide-dark)
        preview: אם '1', מחזיר HTML לתצוגה מקדימה במקום להורדה

    POST Form data:
        vscode_json: תוכן JSON של ערכת VS Code (לייבוא ישיר)
        preview: אם '1', מחזיר HTML לתצוגה מקדימה
    """
    db = get_db()
    user_id = session['user_id']

    # שליפת הקובץ
    try:
        file, _kind = _get_user_any_file_by_id(db, user_id, file_id)
    except Exception as e:
        logger.exception("DB error fetching file for export", extra={"file_id": file_id, "user_id": user_id, "error": str(e)})
        abort(500)

    if not file:
        abort(404)

    # וידוא שזה קובץ Markdown
    language = (file.get('programming_language') or '').lower()
    file_name = file.get('file_name') or ''  # טיפול גם ב-None וגם בחסר
    is_markdown = language == 'markdown' or file_name.lower().endswith(('.md', '.markdown'))

    if not is_markdown:
        flash('ייצוא HTML מעוצב זמין רק לקבצי Markdown', 'warning')
        return redirect(url_for('view_file', file_id=file_id))

    # שליפת ערכת הנושא - תלוי ב-Method
    if request.method == 'POST':
        # POST: ערכת VS Code מה-Form Data
        vscode_json = request.form.get('vscode_json')
        if vscode_json:
            theme = get_export_theme('vscode-import', vscode_json=vscode_json)
        else:
            theme = get_export_theme('tech-guide-dark')
    else:
        # GET: ערכה מה-Query String
        theme_id = request.args.get('theme', 'tech-guide-dark')

        # שליפת ערכות המשתמש (אם בחר ערכה אישית)
        user_data = db.users.find_one({"user_id": int(user_id)}, {"custom_themes": 1})
        user_themes = user_data.get("custom_themes", []) if user_data else []

        theme = get_export_theme(theme_id, user_themes=user_themes)

    # המרת Markdown ל-HTML
    raw_content = file.get('code') or file.get('content') or ''

    # בדיקה אם המשתמש רוצה TOC
    include_toc = request.args.get('toc') == '1' or request.form.get('toc') == '1'
    html_content, toc_html = markdown_to_html(raw_content, include_toc=include_toc)

    # רינדור HTML מלא
    # שימוש ב-or כדי לטפל גם במקרה ש-file_name קיים אבל הוא None
    # הסרת סיומות case-insensitive עם regex
    raw_title = file.get('file_name') or 'Untitled'
    title = re.sub(r'\.(md|markdown)$', '', raw_title, flags=re.IGNORECASE)
    rendered_html = render_styled_html(
        content_html=html_content,
        title=title,
        theme=theme,
        toc_html=toc_html,
    )

    # תצוגה מקדימה או הורדה
    # תומך גם ב-GET query param וגם ב-POST form field
    is_preview = (
        request.args.get('preview') == '1' or
        request.form.get('preview') == '1'
    )

    if is_preview:
        # לתצוגה מקדימה - מחזירים HTML ישיר
        return rendered_html

    # הורדה - מחזירים כקובץ להורדה
    response = make_response(rendered_html)
    response.headers['Content-Type'] = 'text/html; charset=utf-8'

    # 🔒 סניטציה של שם הקובץ - רווח בודד במקום כל whitespace, ללא newlines
    safe_filename = re.sub(r'[^\w \-.]', '', title)  # רווח בודד, לא \s
    safe_filename = safe_filename.strip()[:50] or 'document'
    response.headers['Content-Disposition'] = f'attachment; filename="{safe_filename}.html"'

    return response


@app.route('/api/export/themes')
@login_required
@premium_or_admin_required
def api_export_themes():
    """
    מחזיר רשימת ערכות נושא זמינות לייצוא.

    Returns:
        JSON עם:
        - presets: ערכות מוכנות מראש
        - user_themes: ערכות המשתמש
    """
    db = get_db()
    user_id = session['user_id']

    # Presets
    presets = list_export_presets()

    # ערכות המשתמש
    user_data = db.users.find_one({"user_id": int(user_id)}, {"custom_themes": 1})
    user_themes: list[dict] = []

    if user_data and user_data.get("custom_themes"):
        for theme in user_data["custom_themes"]:
            if not isinstance(theme, dict):
                continue
            user_themes.append({
                "id": theme.get("id"),
                "name": theme.get("name", "My Theme"),
                "description": theme.get("description", ""),
                "category": "custom",
            })

    return jsonify({
        "ok": True,
        "presets": presets,
        "user_themes": user_themes,
    })


@app.route('/api/export/parse-vscode', methods=['POST'])
@login_required
@premium_or_admin_required
def api_parse_vscode_theme():
    """
    מפרסר JSON של ערכת VS Code ומחזיר CSS Variables.

    Body (JSON):
        json_content: תוכן הקובץ JSON

    Returns:
        JSON עם name, variables, syntax_css
    """
    data = request.get_json()
    if not data or not data.get('json_content'):
        return jsonify({"ok": False, "error": "Missing json_content"}), 400

    json_content = data['json_content']

    # וולידציה
    is_valid, error_msg = validate_theme_json(json_content)
    if not is_valid:
        return jsonify({"ok": False, "error": error_msg}), 400

    # פרסור
    try:
        parsed = parse_vscode_theme(json_content)
        return jsonify({
            "ok": True,
            "name": parsed.get("name", "VS Code Theme"),
            "type": parsed.get("type", "dark"),
            "variables": parsed.get("variables", {}),
            "syntax_css": parsed.get("syntax_css", ""),
        })
    except Exception as e:
        logger.exception("Failed to parse VS Code theme")
        return jsonify({"ok": False, "error": "Failed to parse VS Code theme"}), 400


@app.route('/api/export/styled/<file_id>/share', methods=['POST'])
@login_required
@premium_or_admin_required
@traced("export.styled_share")
def api_create_styled_share(file_id):
    """
    יוצר קישור שיתוף ציבורי ל-HTML מעוצב.

    Body (JSON):
        theme: מזהה ערכת הנושא (default: tech-guide-dark)
        vscode_json: תוכן JSON של ערכת VS Code (אופציונלי)

    Returns:
        JSON עם share_url, token, expires_at
    """
    try:
        db = get_db()
        user_id = session['user_id']

        # בדיקת קובץ
        try:
            file, _kind = _get_user_any_file_by_id(db, user_id, file_id)
        except Exception as e:
            logger.exception("DB error fetching file for styled share", extra={"file_id": file_id, "user_id": user_id, "error": str(e)})
            return jsonify({'ok': False, 'error': 'שגיאה בשרת'}), 500

        if not file:
            return jsonify({'ok': False, 'error': 'קובץ לא נמצא'}), 404

        # וידוא שזה קובץ Markdown
        language = (file.get('programming_language') or '').lower()
        file_name = file.get('file_name') or ''
        is_markdown = language == 'markdown' or file_name.lower().endswith(('.md', '.markdown'))

        if not is_markdown:
            return jsonify({'ok': False, 'error': 'ייצוא HTML מעוצב זמין רק לקבצי Markdown'}), 400

        # פרסור הבקשה
        data = request.get_json(silent=True) or {}
        theme_id = data.get('theme', 'tech-guide-dark')
        vscode_json = data.get('vscode_json')
        is_permanent = bool(data.get('permanent', False))

        # יצירת ה-styled HTML
        markdown_content = file.get('code', '')
        try:
            if vscode_json:
                theme = get_export_theme('vscode-import', vscode_json=vscode_json)
            else:
                # בדיקה אם זו ערכה אישית של המשתמש
                user_data = db.users.find_one({"user_id": int(user_id)}, {"custom_themes": 1})
                user_themes = (user_data.get("custom_themes") or []) if user_data else []
                user_theme = next((t for t in user_themes if t.get("id") == theme_id), None)

                if user_theme:
                    theme = get_export_theme(theme_id, user_theme=user_theme)
                else:
                    theme = get_export_theme(theme_id)

            # המרת Markdown ל-HTML
            html_content, toc_html = markdown_to_html(markdown_content, include_toc=False)

            # יצירת כותרת מהשם (הסרת סיומת)
            raw_title = file_name or 'Untitled'
            title = re.sub(r'\.(md|markdown)$', '', raw_title, flags=re.IGNORECASE)

            # רינדור HTML מלא
            styled_html = render_styled_html(
                content_html=html_content,
                title=title,
                theme=theme,
                toc_html=toc_html,
            )
        except Exception as e:
            logger.exception("Failed to render styled HTML for share", extra={"file_id": file_id, "theme_id": theme_id})
            return jsonify({'ok': False, 'error': 'שגיאה ביצירת HTML מעוצב'}), 500

        # יצירת token ושמירה ב-DB
        token = secrets.token_urlsafe(32)
        now = datetime.now(timezone.utc)
        expires_at = None if is_permanent else now + timedelta(days=PUBLIC_SHARE_TTL_DAYS)

        db.styled_shares.insert_one({
            'token': token,
            'source_file_id': ObjectId(file_id),
            'user_id': int(user_id),
            'file_name': file_name,
            'theme_id': theme_id,
            'styled_html': styled_html,
            'created_at': now,
            'expires_at': expires_at,
            'is_permanent': is_permanent,
            'view_count': 0,
        })

        base_url = (WEBAPP_URL or request.host_url.rstrip('/')).rstrip('/')
        share_url = f"{base_url}/shared/styled/{token}"

        return jsonify({
            'ok': True,
            'share_url': share_url,
            'token': token,
            'expires_at': expires_at.isoformat() if expires_at else None,
            'is_permanent': is_permanent,
        })
    except Exception as e:
        logger.exception("Failed to create styled share", extra={"file_id": file_id})
        return jsonify({'ok': False, 'error': 'שגיאה לא צפויה'}), 500


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

        # מצב שיתוף:
        # - preview: תצוגה מקדימה בלבד (לא שומרים/לא מושכים code מלא)
        # - download: מיועד להורדה/גיבוי (שומרים תוכן מלא)
        share_mode = 'download' if share_type in {'download', 'full', 'raw'} else 'preview'

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

        doc: Dict[str, Any] = {
            'share_id': share_id,
            'created_at': now,
            'views': 0,
            'is_permanent': permanent_flag,
            'mode': share_mode,
            'source_file_id': ObjectId(file_id),
            'source_user_id': int(user_id),
        }
        if share_mode == 'preview':
            # אל תביא code מלא לפייתון. חתוך snippet + מטא-דאטה ב-DB.
            try:
                agg = list(db.code_snippets.aggregate([
                    {'$match': {'_id': ObjectId(file_id), 'user_id': user_id}},
                    {'$addFields': {
                        'file_size': {'$ifNull': ['$file_size', {'$strLenBytes': '$code'}]},
                        'lines_count': {'$ifNull': ['$lines_count', {'$size': {'$split': ['$code', '\n']}}]},
                        'snippet_preview': {'$substrBytes': ['$code', 0, 2000]},
                    }},
                    {'$project': {
                        'file_name': 1,
                        'programming_language': 1,
                        'description': 1,
                        'file_size': 1,
                        'lines_count': 1,
                        'snippet_preview': 1,
                    }},
                    {'$limit': 1},
                ]))
                meta = agg[0] if agg and isinstance(agg[0], dict) else {}
            except Exception:
                meta = {}
            if not meta:
                return jsonify({'ok': False, 'error': 'קובץ לא נמצא'}), 404
            doc.update({
                'file_name': meta.get('file_name') or 'snippet.txt',
                'language': (meta.get('programming_language') or 'text'),
                'description': meta.get('description') or '',
                'file_size': int(meta.get('file_size') or 0),
                'lines_count': int(meta.get('lines_count') or 0),
                'snippet_preview': str(meta.get('snippet_preview') or ''),
            })
        else:
            # download/full: חייבים תוכן מלא
            code = file.get('code') or ''
            if not isinstance(code, str):
                code = str(code or '')
            try:
                size_bytes = int(file.get('file_size') or len(code.encode('utf-8', errors='ignore')))
            except Exception:
                size_bytes = 0
            try:
                lines_count = int(file.get('lines_count') or len(code.splitlines()))
            except Exception:
                lines_count = 0
            doc.update({
                'file_name': file.get('file_name') or 'snippet.txt',
                'code': code,
                'language': (file.get('programming_language') or 'text'),
                'description': file.get('description') or '',
                'file_size': size_bytes,
                'lines_count': lines_count,
                'snippet_preview': code[:2000],
            })
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

        # שמירה דורשת תוכן מלא (לא preview)
        # חשוב: לא להעביר kwargs כאן כדי לא לשבור טסטים שעושים monkeypatch לפונקציה.
        share_doc = get_internal_share(share_id)
        if not share_doc:
            return jsonify({'ok': False, 'error': 'השיתוף לא נמצא'}), 404

        raw_code = share_doc.get('code', '')
        if not raw_code:
            return jsonify({'ok': False, 'error': 'השיתוף אינו כולל תוכן מלא'}), 400
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
'is_active': True
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

        _log_webapp_user_activity()

        return jsonify({'ok': True, 'file_id': inserted_id, 'file_name': safe_name, 'version': version})
    except Exception:
        return jsonify({'ok': False, 'error': 'שגיאה לא צפויה'}), 500


_UPLOAD_CLEAR_DRAFT_SESSION_KEY = 'upload_should_clear_draft'
_EDIT_CLEAR_DRAFT_SESSION_KEY = 'edit_should_clear_draft_for_file_id'


def _save_markdown_images(db, user_id, snippet_id, images_payload):
    if not images_payload:
        return
    docs = []
    now = datetime.now(timezone.utc)
    for idx, payload in enumerate(images_payload):
        data = payload.get('data')
        if not data:
            continue
        docs.append({
            'user_id': user_id,
            'snippet_id': snippet_id,
            'file_name': payload.get('filename'),
            'content_type': payload.get('content_type') or 'application/octet-stream',
            'size': payload.get('size') or len(data),
            'order': idx,
            'created_at': now,
            'data': Binary(data),
        })
    if not docs:
        return
    try:
        db.markdown_images.insert_many(docs)
    except Exception as exc:
        logger.exception("Failed to save markdown images", extra={
            'snippet_id': str(snippet_id),
            'user_id': user_id,
            'error': str(exc),
        })


@app.route('/upload/from-repo')
@login_required
def upload_from_repo():
    """פתיחת עמוד העלאה עם תוכן קובץ מהריפו - לעריכה מהירה או העתקת קטעים."""
    from services.git_mirror_service import get_mirror_service
    
    file_path = request.args.get('path', '').strip()
    if not file_path:
        return redirect(url_for('upload_file_web'))
    
    # קריאת הקובץ מהריפו
    git_service = get_mirror_service()
    content = git_service.get_file_content('CodeBot', file_path)
    
    if content is None:
        flash('הקובץ לא נמצא בריפו', 'error')
        return redirect(url_for('upload_file_web'))
    
    # זיהוי שפה לפי סיומת
    ext = file_path.split('.')[-1].lower() if '.' in file_path else 'text'
    lang_map = {
        'py': 'python', 'js': 'javascript', 'ts': 'typescript',
        'html': 'html', 'css': 'css', 'json': 'json',
        'md': 'markdown', 'yml': 'yaml', 'yaml': 'yaml',
        'sh': 'shell', 'sql': 'sql'
    }
    language = lang_map.get(ext, 'text')
    
    # שם הקובץ מהנתיב
    file_name = file_path.split('/')[-1]
    
    # שליפת שפות קיימות
    db = get_db()
    user_id = session['user_id']
    try:
        raw_languages = db.code_snippets.distinct('programming_language', {'user_id': user_id}) if db is not None else []
    except Exception:
        raw_languages = []
    languages = _build_language_choices(raw_languages)
    
    return render_template(
        'upload.html',
        bot_username=BOT_USERNAME_CLEAN,
        user=session['user_data'],
        languages=languages,
        error=None,
        success=None,
        file_name_value=file_name,
        language_value=language,
        description_value=f'מקור: {file_path}',
        tags_value='',
        code_value=content,
        source_url_value=f'https://github.com/amirbiron/CodeBot/blob/main/{url_quote(file_path, safe="/")}',
        clear_local_draft=True,
        from_repo=True,  # flag להראות שזה מגיע מהריפו
    )


@app.route('/upload', methods=['GET', 'POST'])
@login_required
@traced("files.upload_web")
def upload_file_web():
    """העלאת קובץ חדש דרך הווב-אפליקציה."""
    db = get_db()
    user_id = session['user_id']
    error = None
    success = None
    should_clear_local_draft = bool(session.pop(_UPLOAD_CLEAR_DRAFT_SESSION_KEY, False))
    # החזקת ערכי טופס לשחזור במקרה של שגיאה ולרינדור ראשוני
    file_name_value = ''
    language_value = 'text'
    description_value = ''
    tags_value = ''
    code_value = ''
    source_url_value = ''
    if request.method == 'POST':
        try:
            file_name = (request.form.get('file_name') or '').strip()
            code = request.form.get('code') or ''
            language = (request.form.get('language') or '').strip() or 'text'
            description = (request.form.get('description') or '').strip()
            raw_tags = (request.form.get('tags') or '').strip()
            tags = [t.strip() for t in re.split(r'[,#\n]+', raw_tags) if t.strip()] if raw_tags else []
            raw_source_url = request.form.get('source_url') or ''
            source_url_value = raw_source_url.strip()
            source_url_state = (request.form.get('source_url_touched') or '').strip().lower()
            source_url_was_edited = source_url_state == 'edited'
            clean_source_url = None
            source_url_removed = False
            markdown_image_payloads: List[Dict[str, Any]] = []
            if source_url_value:
                clean_source_url, source_url_err = _normalize_source_url_value(source_url_value)
                if source_url_err:
                    error = source_url_err
                elif clean_source_url:
                    source_url_value = clean_source_url
            elif source_url_was_edited:
                source_url_removed = True

            # שמור את הערכים שהוזנו לצורך שחזור בטופס
            file_name_value = file_name
            language_value = language or 'text'
            description_value = description
            tags_value = raw_tags
            code_value = code

            # אם הועלה קובץ — נקרא ממנו ונשתמש בשמו אם אין שם קובץ בשדה
            try:
                uploaded = request.files.get('code_file')
            except Exception:
                uploaded = None
            had_upload_too_large = False
            if uploaded and hasattr(uploaded, 'filename') and uploaded.filename:
                # הגבלת גודל בסיסית (עד ~2MB)
                data = uploaded.read()
                max_bytes = 2 * 1024 * 1024
                if data and len(data) > max_bytes:
                    # שמור תצוגה מקוצרת כדי לא לאבד לגמרי את התוכן, אבל הצג שגיאה
                    had_upload_too_large = True
                    error = 'קובץ גדול מדי (עד 2MB)'
                    preview = data[: min(len(data), 256 * 1024)]  # תצוגה עד 256KB
                    try:
                        code_preview = preview.decode('utf-8', errors='replace')
                    except Exception:
                        try:
                            code_preview = preview.decode('latin-1', errors='replace')
                        except Exception:
                            code_preview = ''
                    code_value = code_preview
                    if not file_name:
                        file_name = uploaded.filename or ''
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
            if not had_upload_too_large:
                code_value = code  # עדכן גם את ערך השחזור לאחר נרמול, אלא אם קובץ היה גדול מדי

            if not file_name and not error:
                error = 'יש להזין שם קובץ'
            if not code and not error:
                error = 'יש להזין תוכן קוד'
            if not error:
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
                # חשוב: ה-Frontend מאפשר לצרף תמונות כששפת הטופס היא Markdown, גם אם הסיומת אינה .md.
                # כדי למנוע איבוד מידע, נאסוף תמונות גם לפי השפה שנשלחה בטופס.
                is_md_extension = isinstance(file_name, str) and file_name.lower().endswith(('.md', '.markdown'))
                try:
                    lang_value = str(language or request.form.get('language') or '').strip().lower()
                except Exception:
                    lang_value = ''
                is_md_language = lang_value in ('markdown', 'md')
                should_collect_images = is_md_extension or is_md_language
                if not error and should_collect_images:
                    try:
                        incoming_images = request.files.getlist('md_images')
                    except Exception:
                        incoming_images = []
                    valid_images = [img for img in incoming_images if getattr(img, 'filename', '').strip()]
                    if valid_images:
                        if len(valid_images) > MARKDOWN_IMAGE_LIMIT:
                            error = f'ניתן לצרף עד {MARKDOWN_IMAGE_LIMIT} תמונות'
                        else:
                            for img in valid_images:
                                if error:
                                    break
                                try:
                                    data = img.read()
                                except Exception:
                                    data = b''
                                if not data:
                                    continue
                                if len(data) > MARKDOWN_IMAGE_MAX_BYTES:
                                    max_mb = max(1, MARKDOWN_IMAGE_MAX_BYTES // (1024 * 1024))
                                    error = f'כל תמונה מוגבלת ל-{max_mb}MB'
                                    break
                                safe_name = secure_filename(img.filename or '') or f'image_{len(markdown_image_payloads) + 1}.png'
                                content_type = (img.mimetype or '').lower()
                                if content_type not in ALLOWED_MARKDOWN_IMAGE_TYPES:
                                    guessed_type = mimetypes.guess_type(safe_name)[0] or ''
                                    content_type = guessed_type.lower() if guessed_type else content_type
                                if content_type not in ALLOWED_MARKDOWN_IMAGE_TYPES:
                                    error = 'ניתן להעלות רק תמונות PNG, JPG, WEBP או GIF'
                                    break
                                markdown_image_payloads.append({
                                    'filename': safe_name,
                                    'content_type': content_type,
                                    'size': len(data),
                                    'data': data,
                                })
                            if error:
                                markdown_image_payloads = []
                if not error:
                    try:
                        # קבע גרסה חדשה על בסיס האחרונה הפעילה
                        prev = db.code_snippets.find_one(
                            {
                                'user_id': user_id,
                                'file_name': file_name,
'is_active': True
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
                    if clean_source_url:
                        doc['source_url'] = clean_source_url
                    elif not source_url_removed:
                        prev_source = (prev or {}).get('source_url')
                        if prev_source:
                            doc['source_url'] = prev_source
                    try:
                        res = db.code_snippets.insert_one(doc)
                    except Exception as _e:
                        res = None
                    if res and getattr(res, 'inserted_id', None):
                        if markdown_image_payloads:
                            try:
                                _save_markdown_images(db, user_id, res.inserted_id, markdown_image_payloads)
                            except Exception:
                                pass
                        session[_UPLOAD_CLEAR_DRAFT_SESSION_KEY] = True
                        if _log_webapp_user_activity():
                            session['_skip_view_activity_once'] = True
                        return redirect(url_for('view_file', file_id=str(res.inserted_id)))
                    error = 'שמירת הקובץ נכשלה'
        except Exception as e:
            error = f'שגיאה בהעלאה: {e}'
    # שליפת שפות קיימות + השלמה לברירת מחדל
    try:
        raw_languages = db.code_snippets.distinct('programming_language', {'user_id': user_id}) if db is not None else []
    except Exception:
        raw_languages = []
    languages = _build_language_choices(raw_languages)
    return render_template(
        'upload.html',
        bot_username=BOT_USERNAME_CLEAN,
        user=session['user_data'],
        languages=languages,
        error=error,
        success=success,
        # ערכי טופס לשחזור
        file_name_value=file_name_value,
        language_value=language_value,
        description_value=description_value,
        tags_value=tags_value,
        code_value=code_value,
        source_url_value=source_url_value,
        clear_local_draft=should_clear_local_draft,
    )

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
            'is_active': True
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


@app.route('/api/pin/toggle/<file_id>', methods=['POST'])
@login_required
def api_toggle_pin(file_id):
    """
    API לנעיצה/ביטול נעיצה של קובץ

    Returns:
        JSON: {ok: bool, is_pinned: bool, error?: str, count: int}
    """
    try:
        db = get_db()
        user_id = session['user_id']

        # מצא את הקובץ לפי ID
        try:
            snippet = db.code_snippets.find_one({'_id': ObjectId(file_id), 'user_id': user_id})
        except Exception:
            snippet = None
        if not snippet:
            return jsonify({"ok": False, "error": "הקובץ לא נמצא"}), 404

        file_name = snippet.get("file_name")
        if not file_name:
            return jsonify({"ok": False, "error": "שם קובץ חסר"}), 400

        from database.manager import toggle_pin as _toggle_pin, get_pinned_count as _get_pinned_count
        pin_manager = SimpleNamespace(collection=db.code_snippets)
        result = _toggle_pin(pin_manager, user_id, file_name)

        if not result.get("success"):
            # אל תחזיר פרטי שגיאה פנימיים ללקוח (אבל שמור הודעות עסקיות)
            raw_error = result.get("error", "") or ""
            if raw_error.startswith("ניתן לנעוץ עד"):
                client_error = raw_error
            else:
                client_error = "שגיאה בעת עדכון סטטוס נעיצה"
            return jsonify({
                "ok": False,
                "error": client_error
            }), 400

        return jsonify({
            "ok": True,
            "is_pinned": result.get("is_pinned", False),
            "count": _get_pinned_count(pin_manager, user_id)
        })

    except Exception as e:
        # Log full exception details on the server, but return a generic message to the client
        # הודעת שגיאה כללית בלבד ללקוח
        logger.exception("Error in api_toggle_pin")
        return jsonify({"ok": False, "error": "שגיאה פנימית בשרת"}), 500


@app.route('/api/pinned', methods=['GET'])
@login_required
def api_get_pinned_files():
    """
    API לקבלת רשימת קבצים נעוצים

    Returns:
        JSON: {ok: bool, files: list, count: int}
    """
    try:
        db = get_db()
        user_id = session['user_id']
        from database.manager import get_pinned_files as _get_pinned_files
        pin_manager = SimpleNamespace(collection=db.code_snippets)
        pinned = _get_pinned_files(pin_manager, user_id)

        # הכנת נתונים לתצוגה
        files = []
        for p in pinned:
            files.append({
                "id": str(p.get("_id", "")),
                "file_name": p.get("file_name", ""),
                "language": p.get("programming_language", ""),
                "icon": get_language_icon(p.get("programming_language", "")),
                "tags": (p.get("tags") or [])[:3],
                "description": (p.get("description", "") or "")[:50],
                "pinned_at": p.get("pinned_at"),
                "updated_at": p.get("updated_at"),
                "size": format_file_size(p.get("file_size", 0)),
                "lines": p.get("lines_count", 0)
            })

        return jsonify({
            "ok": True,
            "files": files,
            "count": len(files)
        })

    except Exception as e:
        logger.error(f"Error in api_get_pinned_files: {e}")
        return jsonify({"ok": False, "error": "אירעה שגיאה בעת טעינת הקבצים הנעוצים"}), 500


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
            'is_active': True
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
            'is_active': True
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
            'is_active': True
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

        # שליפת הקבצים השייכים למשתמש בלבד (רגילים + קבצים גדולים)
        docs_by_id: Dict[ObjectId, Dict[str, Any]] = {}
        found_ids: set[ObjectId] = set()

        cursor = db.code_snippets.find({
            '_id': {'$in': object_ids},
            'user_id': user_id,
            'is_active': True
        }, {'_id': 1, 'file_name': 1, 'code': 1})
        for doc in cursor:
            if isinstance(doc, dict) and doc.get('_id') is not None:
                docs_by_id[doc['_id']] = doc
                found_ids.add(doc['_id'])

        remaining_ids = [oid for oid in object_ids if oid not in found_ids]
        large_coll = getattr(db, 'large_files', None)
        if remaining_ids and large_coll is not None:
            cursor = large_coll.find({
                '_id': {'$in': remaining_ids},
                'user_id': user_id,
                'is_active': True
            }, {'_id': 1, 'file_name': 1, 'content': 1})
            for doc in cursor:
                if isinstance(doc, dict) and doc.get('_id') is not None:
                    docs_by_id.setdefault(doc['_id'], doc)

        from io import BytesIO
        import zipfile

        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
            for oid in object_ids:
                doc = docs_by_id.get(oid)
                if not doc:
                    continue
                filename = (doc.get('file_name') or f"file_{str(doc.get('_id'))}.txt").strip() or f"file_{str(doc.get('_id'))}.txt"
                try:
                    # מניעת שמות תיקיה מסוכנים
                    filename = filename.replace('..', '_').replace('/', '_').replace('\\', '_')
                except Exception:
                    filename = f"file_{str(doc.get('_id'))}.txt"
                content = doc.get('code')
                if content is None:
                    content = doc.get('content')
                if isinstance(content, bytes):
                    try:
                        content = content.decode('utf-8', errors='ignore')
                    except Exception:
                        content = ''
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
                'is_active': True
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
'is_active': True
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


@app.route('/api/dashboard/last-commit-files', methods=['GET'])
@login_required
def api_dashboard_last_commit_files():
    """API: טעינת 'טען עוד' לקבצי הקומיט האחרון (Admin only)."""
    user_id = session.get("user_id")
    try:
        if user_id is None or not is_admin(int(user_id)):
            return jsonify({"ok": False, "error": "admin_only"}), 403
    except Exception:
        return jsonify({"ok": False, "error": "admin_only"}), 403

    sha = (request.args.get("sha") or "").strip()
    raw_offset = request.args.get("offset", "0")
    raw_limit = request.args.get("limit", "50")
    try:
        offset = int(raw_offset)
    except Exception:
        offset = 0
    try:
        limit = int(raw_limit)
    except Exception:
        limit = 50

    offset = max(0, offset)
    limit = max(1, min(200, limit))

    db = get_db()
    repo_name = os.getenv("REPO_NAME", "CodeBot")
    git_service = get_mirror_service()

    if not git_service.mirror_exists(repo_name):
        return jsonify({"ok": False, "error": "mirror_not_found"}), 404

    try:
        last_commit = git_service.get_last_commit_info(repo_name, ref=sha or "HEAD", offset=offset, max_files=limit)
        if not last_commit:
            return jsonify({"ok": False, "error": "commit_not_found"}), 404

        # אפשר להחזיר גם sync_time/סטטוס אם נרצה בעתיד, כרגע מספיק קבצים + total
        return jsonify(
            {
                "ok": True,
                "sha": last_commit.get("sha"),
                "files": last_commit.get("files") or [],
                "total_files": int(last_commit.get("total_files") or 0),
                "truncated": bool(last_commit.get("truncated")),
                "offset": offset,
            }
        )
    except Exception as e:
        logger.warning(f"Failed to load last commit files: {e}")
        return jsonify({"ok": False, "error": "load_failed"}), 500


@app.route('/api/dashboard/activity/files', methods=['GET'])
@login_required
def api_dashboard_activity_files():
    """API: טען עוד 12 אירועי קבצים לפיד אחרון (עד 7 ימים אחורה)."""
    user_id = session.get("user_id")
    try:
        user_id_int = int(user_id) if user_id is not None else None
    except Exception:
        user_id_int = None
    if not user_id_int:
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    raw_offset = request.args.get("offset", "0")
    raw_limit = request.args.get("limit", "12")
    try:
        offset = int(raw_offset)
    except Exception:
        offset = 0
    try:
        limit = int(raw_limit)
    except Exception:
        limit = 12

    offset = max(0, offset)
    limit = max(1, min(50, limit))

    now = datetime.now(timezone.utc)
    recent_cutoff = now - timedelta(days=7)

    db = get_db()
    base_query = {
        'user_id': user_id_int,
        'is_active': True,
    }
    recent_query: Dict[str, Any] = dict(base_query)
    recent_query['$or'] = [
        {'updated_at': {'$gte': recent_cutoff}},
        {'updated_at': {'$exists': False}, 'created_at': {'$gte': recent_cutoff}},
        {'updated_at': None, 'created_at': {'$gte': recent_cutoff}},
    ]

    try:
        total_recent = int(db.code_snippets.count_documents(recent_query))
    except Exception:
        total_recent = 0

    try:
        cursor = (
            db.code_snippets.find(
                recent_query,
                {'file_name': 1, 'programming_language': 1, 'updated_at': 1, 'created_at': 1, 'version': 1, 'description': 1},
            )
            .sort('updated_at', DESCENDING)
            .skip(offset)
            .limit(limit)
        )
        docs = list(cursor or [])
    except Exception as e:
        logger.warning(f"Failed to fetch timeline files: {e}")
        return jsonify({"ok": False, "error": "load_failed"}), 500

    items: List[Dict[str, Any]] = []
    for doc in docs:
        dt = doc.get('updated_at') or doc.get('created_at')
        version = doc.get('version') or 1
        is_new = version == 1
        action = "נוצר" if is_new else "עודכן"
        file_name = doc.get('file_name') or "ללא שם"
        language = resolve_file_language(doc.get('programming_language'), file_name)
        title = f"{action} {file_name}"
        details: List[str] = []
        if doc.get('programming_language'):
            details.append(doc['programming_language'])
        elif language and language != 'text':
            details.append(language)
        if version:
            details.append(f"גרסה {version}")
        description = (doc.get('description') or "").strip()
        subtitle = description if description else (" · ".join(details) if details else "ללא פרטים נוספים")
        href = f"/file/{doc.get('_id')}"
        file_badge = doc.get('programming_language') or (language if language and language != 'text' else None)
        items.append(
            _build_timeline_event(
                'files',
                title=title,
                subtitle=subtitle,
                dt=dt,
                icon=get_language_icon(language),
                badge=file_badge,
                badge_variant='code',
                href=href,
                meta={'details': " · ".join(details)},
            )
        )

    # שמירה על אחידות פורמט מול הדשבורד
    finalized = _finalize_events(sorted(items, key=lambda ev: ev.get('_dt') or _MIN_DT, reverse=True))
    next_offset = offset + len(finalized)
    remaining = max(0, total_recent - next_offset)

    return jsonify(
        {
            "ok": True,
            "events": finalized,
            "total_recent": total_recent,
            "offset": offset,
            "next_offset": next_offset,
            "remaining": remaining,
            "has_more": bool(remaining > 0),
        }
    )


@app.route('/api/dashboard/whats-new', methods=['GET'])
@login_required
def api_dashboard_whats_new():
    """API: טען עוד פיצ'רים חדשים (pagination)."""
    try:
        offset = max(0, int(request.args.get('offset', 0)))
        limit = min(10, max(1, int(request.args.get('limit', 5))))
        max_days = min(180, max(7, int(request.args.get('max_days', 30))))
    except (ValueError, TypeError):
        offset = 0
        limit = 5
        max_days = 30

    data = _load_whats_new(limit=limit, offset=offset, max_days=max_days)
    
    return jsonify({
        "ok": True,
        "features": data['features'],
        "total": data['total'],
        "offset": data['offset'],
        "next_offset": data['next_offset'],
        "remaining": data['remaining'],
        "has_more": data['has_more'],
    })


@app.route('/api/stats/logs', methods=['GET'])
@login_required
def api_stats_logs():
    """API לוגים קצר (לטובת Observability/UI) – מחזיר רשומות מצומצמות ובטוחות."""
    if not _require_admin_user():
        return jsonify({'ok': False, 'error': 'admin_only'}), 403
    try:
        try:
            limit = int(request.args.get('limit') or 120)
        except Exception:
            limit = 120
        limit = max(1, min(500, limit))

        def _fetch() -> List[Dict[str, Any]]:
            rows: List[Dict[str, Any]] = []
            try:
                import internal_alerts as _ia  # type: ignore
            except Exception:
                _ia = None  # type: ignore
            if _ia is None or not hasattr(_ia, 'get_recent_alerts'):
                return rows
            try:
                raw = _ia.get_recent_alerts(limit=max(20, limit))  # type: ignore[attr-defined]
            except Exception:
                raw = []
            mask = getattr(observability_service, "_mask_text", None)
            for rec in (raw or [])[:limit]:
                if not isinstance(rec, dict):
                    continue
                ts = rec.get('timestamp') or rec.get('ts') or rec.get('time') or rec.get('created_at')
                severity = rec.get('severity') or rec.get('level') or rec.get('status') or 'info'
                message = rec.get('message') or rec.get('summary') or rec.get('event') or rec.get('name') or ''
                source = rec.get('source') or rec.get('service') or rec.get('component') or ''
                try:
                    msg_text = str(message or '')
                except Exception:
                    msg_text = ''
                if callable(mask):
                    try:
                        msg_text = str(mask(msg_text) or '')
                    except Exception:
                        pass
                msg_text = (msg_text[:500] + '…') if len(msg_text) > 500 else msg_text
                rows.append({
                    'timestamp': ts,
                    'severity': str(severity or 'info'),
                    'message': msg_text,
                    'source': str(source or ''),
                })
            return rows

        logs = _run_observability_blocking(_fetch)
        return jsonify({'ok': True, 'logs': logs, 'count': len(logs)})
    except Exception:
        logger.exception("api_stats_logs_failed")
        return jsonify({'ok': False, 'error': 'internal_error'}), 500

@app.route('/theme-preview')
def theme_preview():
    """תצוגה מקדימה של ערכות נושא מוצעות"""
    return render_template('theme_preview.html', static_version=_STATIC_VERSION)

@app.route('/font-preview')
@login_required
def font_preview():
    """תצוגה מקדימה והשוואת פונטים לקוד (Fira Code vs JetBrains Mono)"""
    return render_template('font_preview.html', static_version=_STATIC_VERSION)

@app.route('/settings')
@login_required
def settings():
    """דף הגדרות - אופטימלי עם תמיכה בsessions ישנים"""
    user_id = session['user_id']
    user_data = session.get('user_data') or {}
    if not isinstance(user_data, dict):
        user_data = {}
    session['user_data'] = user_data

    # ✅ Fallback ל-DB אם אין ב-session (sessions ישנים)
    user_is_admin = user_data.get('is_admin')
    if user_is_admin is None:
        user_is_admin = is_admin(user_id)
        user_data['is_admin'] = user_is_admin
        session.modified = True

    user_is_premium = user_data.get('is_premium')
    if user_is_premium is None:
        user_is_premium = is_premium(user_id)
        user_data['is_premium'] = user_is_premium
        session.modified = True

    if is_impersonating_safe():
        effective_is_admin = False
        effective_is_premium = False
    else:
        effective_is_admin = bool(user_is_admin)
        effective_is_premium = bool(user_is_premium)

    # ✅ בדיקת persistent token עם cache
    has_persistent = _check_persistent_login_cached(user_id)

    # דגל פוש
    push_enabled = os.getenv('PUSH_NOTIFICATIONS_ENABLED', 'true').strip().lower() in {'1', 'true', 'yes', 'on'}

    return render_template(
        'settings.html',
        user=user_data,
        is_admin=effective_is_admin,
        is_premium=effective_is_premium,
        persistent_login_enabled=has_persistent,
        persistent_days=PERSISTENT_LOGIN_DAYS,
        push_enabled=push_enabled
    )


@app.route('/settings/push-debug')
@login_required
def settings_push_debug():
    """עמוד דיבוג פשוט ל-Web Push (למי שאין DevTools)."""
    user_id = session.get('user_id')
    user_data = session.get('user_data') or {}
    if not isinstance(user_data, dict):
        user_data = {}
    try:
        if not is_admin(user_id):
            return redirect('/settings#push')
    except Exception:
        return redirect('/settings#push')

    push_enabled = os.getenv('PUSH_NOTIFICATIONS_ENABLED', 'true').strip().lower() in {'1', 'true', 'yes', 'on'}

    # Server config signals (do not expose secrets)
    vapid_public = (os.getenv("VAPID_PUBLIC_KEY") or "").strip()
    vapid_private = (os.getenv("VAPID_PRIVATE_KEY") or "").strip()
    remote_enabled_env = (os.getenv("PUSH_REMOTE_DELIVERY_ENABLED") or "").strip()
    remote_url = (os.getenv("PUSH_DELIVERY_URL") or "").strip()
    remote_token_set = bool((os.getenv("PUSH_DELIVERY_TOKEN") or "").strip())

    # Runtime package versions (helps diagnose dependency/caching issues)
    def _dist_version(*names: str) -> str:
        try:
            from importlib import metadata  # py3.8+

            for n in names:
                try:
                    v = metadata.version(n)
                    if v:
                        return str(v)
                except metadata.PackageNotFoundError:
                    continue
                except Exception:
                    continue
        except Exception:
            pass
        return "unknown"

    py_vapid_version = _dist_version("py-vapid", "py_vapid")
    pywebpush_version = _dist_version("pywebpush")
    cryptography_version = _dist_version("cryptography")

    subs_count = None
    subs_error = ""
    try:
        db = get_db()
        # Match the same user_id handling used by push_api (int/str variants).
        variants: set = set()
        try:
            variants.add(user_id)
        except Exception:
            pass
        try:
            variants.add(int(user_id))  # type: ignore[arg-type]
        except Exception:
            pass
        try:
            variants.add(str(user_id or ""))
        except Exception:
            pass
        variants_list = [v for v in variants if v not in (None, "")]
        if not variants_list:
            variants_list = [user_id]
        subs_count = int(db.push_subscriptions.count_documents({"user_id": {"$in": variants_list}}))
    except Exception as e:
        subs_error = str(e)

    ua = ""
    try:
        ua = str(request.headers.get("User-Agent") or "")
    except Exception:
        ua = ""

    actual_is_admin = bool(user_data.get('is_admin', False))
    actual_is_premium = bool(user_data.get('is_premium', False))
    if is_impersonating_safe():
        effective_is_admin = False
        effective_is_premium = False
    else:
        effective_is_admin = actual_is_admin
        effective_is_premium = actual_is_premium

    return render_template(
        'settings_push_debug.html',
        user=user_data,
        is_admin=effective_is_admin,
        is_premium=effective_is_premium,
        push_enabled=push_enabled,
        vapid_public_set=bool(vapid_public),
        vapid_private_set=bool(vapid_private),
        remote_enabled_env=remote_enabled_env,
        remote_url=remote_url,
        remote_token_set=remote_token_set,
        py_vapid_version=py_vapid_version,
        pywebpush_version=pywebpush_version,
        cryptography_version=cryptography_version,
        subs_count=subs_count,
        subs_error=subs_error,
        user_agent=ua,
        static_version=_STATIC_VERSION,
    )


@app.route('/settings/push-test', methods=['POST'])
@login_required
def settings_push_test():
    """POST שמחזיר JSON של /api/push/test (ללא DevTools)."""
    try:
        # Reuse the existing API handler to keep behavior consistent.
        from webapp.push_api import test_push as _test_push  # type: ignore
        resp = _test_push()
        # resp can be (response, status) in some paths, normalize.
        if isinstance(resp, tuple) and len(resp) >= 1:
            return resp
        return resp
    except Exception:
        # Do not leak traceback; return simple JSON
        return jsonify({"ok": False, "error": "internal_error"}), 500


@app.route('/settings/theme-builder')
@login_required
def theme_builder():
    """דף בונה ערכת נושא מותאמת אישית (זמין לכל משתמש מחובר)."""
    user_id = session['user_id']
    actual_is_admin = False
    actual_is_premium = False
    try:
        uid_int = int(user_id)
        actual_is_admin = bool(is_admin(uid_int))
        actual_is_premium = bool(is_premium(uid_int))
    except Exception:
        actual_is_admin = False
        actual_is_premium = False
    if is_impersonating_safe():
        user_is_admin = False
        user_is_premium = False
    else:
        user_is_admin = actual_is_admin
        user_is_premium = actual_is_premium

    return render_template(
        'settings/theme_builder.html',
        user=session.get('user_data', {}),
        is_admin=user_is_admin,
        is_premium=user_is_premium,
        saved_theme=None,
    )


@app.route('/settings/theme-gallery')
@login_required
def theme_gallery():
    """דף ייעודי: גלריית Presets + ייבוא ערכות (VS Code/JSON)."""
    user_id = session['user_id']
    actual_is_admin = False
    actual_is_premium = False
    try:
        uid_int = int(user_id)
        actual_is_admin = bool(is_admin(uid_int))
        actual_is_premium = bool(is_premium(uid_int))
    except Exception:
        actual_is_admin = False
        actual_is_premium = False
    if is_impersonating_safe():
        user_is_admin = False
        user_is_premium = False
    else:
        user_is_admin = actual_is_admin
        user_is_premium = actual_is_premium
    return render_template(
        'settings/theme_gallery.html',
        user=session.get('user_data', {}),
        is_admin=user_is_admin,
        is_premium=user_is_premium,
    )

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
                'is_active': True
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
    - theme: אחד מ-{"classic","ocean","high-contrast","dark","dim","rose-pine-dawn","nebula","custom"} (אופציונלי)
    - editor: "simple" | "codemirror" (אופציונלי)
    - work_state: אובייקט עם מצב עבודה נוכחי (last_url, scroll_y, timestamp)
    - onboarding: אובייקט flags (walkthrough_v1_seen, theme_wizard_seen)
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
        theme_scope_cookie_value: Optional[str] = None
        theme_scope: Optional[str] = None

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
        if 'theme_scope' in payload:
            theme_scope = _normalize_theme_scope(payload.get('theme_scope'))
            theme_scope_cookie_value = (
                THEME_SCOPE_DEVICE if theme_scope == THEME_SCOPE_DEVICE else THEME_SCOPE_GLOBAL
            )

        if 'theme' in payload:
            theme = (payload.get('theme') or '').strip().lower()
            # 'custom' זמין לכל משתמש מחובר, רק אם קיימת ערכה פעילה ב-DB.
            if theme == 'custom':
                try:
                    ct = get_custom_theme(user_id)
                    if not (isinstance(ct, dict) and ct.get('is_active')):
                        return jsonify({'ok': False, 'error': 'custom_theme_not_active'}), 400
                except Exception:
                    return jsonify({'ok': False, 'error': 'custom_theme_not_active'}), 400

            if theme in ALLOWED_UI_THEMES:
                resolved_scope = (
                    THEME_SCOPE_DEVICE if theme_scope == THEME_SCOPE_DEVICE else THEME_SCOPE_GLOBAL
                )
                if resolved_scope != THEME_SCOPE_DEVICE:
                    update_fields['ui_prefs.theme'] = theme
                resp_payload['theme'] = theme
                theme_cookie_value = theme
                theme_scope_cookie_value = resolved_scope

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

        # Onboarding flags (persisted; boolean only)
        if 'onboarding' in payload:
            try:
                ob = payload.get('onboarding') or {}
                if not isinstance(ob, dict):
                    return jsonify({'ok': False, 'error': 'onboarding must be an object'}), 400

                onboarding_resp: Dict[str, Any] = {}
                if 'walkthrough_v1_seen' in ob:
                    v = ob.get('walkthrough_v1_seen')
                    if not isinstance(v, bool):
                        return jsonify({'ok': False, 'error': 'onboarding.walkthrough_v1_seen must be boolean'}), 400
                    update_fields['ui_prefs.onboarding.walkthrough_v1_seen'] = v
                    onboarding_resp['walkthrough_v1_seen'] = v

                if 'theme_wizard_seen' in ob:
                    v = ob.get('theme_wizard_seen')
                    if not isinstance(v, bool):
                        return jsonify({'ok': False, 'error': 'onboarding.theme_wizard_seen must be boolean'}), 400
                    update_fields['ui_prefs.onboarding.theme_wizard_seen'] = v
                    onboarding_resp['theme_wizard_seen'] = v

                if onboarding_resp:
                    resp_payload['onboarding'] = onboarding_resp
            except Exception:
                return jsonify({'ok': False, 'error': 'invalid_onboarding'}), 400

        needs_db_update = len(update_fields) > 1  # יותר מ-updated_at
        needs_cookie_update = any(
            v is not None
            for v in (font_scale_cookie_value, theme_cookie_value, theme_scope_cookie_value)
        )

        # אם לא התקבל אף שדה עדכני ואין צורך בקוקיז – אין מה לעדכן
        if not needs_db_update and not needs_cookie_update:
            return jsonify({'ok': True})

        if needs_db_update:
            db.users.update_one(
                {'user_id': user_id},
                {'$set': update_fields, '$setOnInsert': {'created_at': datetime.now(timezone.utc)}},
                upsert=True,
            )

        # עדכון קוקיז רק עבור שדות שסופקו
        resp = jsonify(resp_payload)
        try:
            # CodeQL hardening: לא מאפשרים ערכי Cookie עם תווי שליטה/תווים אסורים
            if font_scale_cookie_value is not None:
                # ערך צפוי אחרי format: "0.85".."1.60"
                if not re.fullmatch(r"[0-9]\.[0-9]{2}", str(font_scale_cookie_value)):
                    font_scale_cookie_value = None
            if theme_cookie_value is not None:
                # ערכים מתוך ALLOWED_UI_THEMES בלבד, אבל נחזק גם כאן כדי ש-CodeQL יזהה ולידציה
                if not re.fullmatch(r"[a-z0-9-]{1,32}", str(theme_cookie_value)):
                    theme_cookie_value = None
            if theme_scope_cookie_value is not None:
                if theme_scope_cookie_value not in _THEME_SCOPE_VALUES:
                    theme_scope_cookie_value = None

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
            if theme_scope_cookie_value is not None:
                scope_value = THEME_SCOPE_DEVICE if theme_scope_cookie_value == THEME_SCOPE_DEVICE else THEME_SCOPE_GLOBAL
                resp.set_cookie(
                    'ui_theme_scope',
                    scope_value,
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


#
# NOTE:
# ה-API של Themes הועבר במלואו ל-`webapp/themes_api.py` (Blueprint),
# כדי לא להשאיר לוגיקה מפוצלת בתוך `app.py`.
#


@app.route('/api/config/radar', methods=['GET'])
@login_required
def api_config_radar():
    """מאחד את קבצי הקונפיגורציה הקריטיים למסך Config Radar."""
    user_id = session.get('user_id')
    try:
        user_id_int = int(user_id) if user_id is not None else None
    except Exception:
        user_id_int = None
    if not user_id_int or not is_admin(user_id_int):
        return jsonify({'ok': False, 'error': 'admin_only'}), 403
    try:
        snapshot = build_config_radar_snapshot()
        return jsonify(snapshot)
    except Exception:
        logger.exception("config_radar_snapshot_failed")
        return jsonify({'ok': False, 'error': 'internal_error'}), 500


def _require_admin_user() -> Optional[int]:
    user_id = session.get('user_id')
    try:
        user_id_int = int(user_id) if user_id is not None else None
    except Exception:
        user_id_int = None
    if not user_id_int or not is_admin(user_id_int):
        return None
    return user_id_int


@app.route('/api/observability/drills/scenarios', methods=['GET'])
@login_required
def api_observability_drills_scenarios():
    if not _require_admin_user():
        return jsonify({'ok': False, 'error': 'admin_only'}), 403
    try:
        from services import drill_service  # type: ignore

        return jsonify({'ok': True, 'scenarios': drill_service.list_scenarios()})
    except Exception:
        logger.exception("drills_list_scenarios_failed")
        return jsonify({'ok': False, 'error': 'internal_error'}), 500


@app.route('/api/observability/drills/run', methods=['POST'])
@login_required
def api_observability_drills_run():
    user_id = _require_admin_user()
    if not user_id:
        return jsonify({'ok': False, 'error': 'admin_only'}), 403
    payload = request.get_json(silent=True) or {}
    scenario_id = str(payload.get('scenario_id') or '').strip()
    if not scenario_id:
        return jsonify({'ok': False, 'error': 'missing_scenario_id'}), 400
    try:
        from services import drill_service  # type: ignore

        result = drill_service.run_drill_scenario(scenario_id, requested_by=str(user_id))
        return jsonify(
            {
                'ok': True,
                'drill_id': result.drill_id,
                'scenario_id': result.scenario_id,
                'alert': result.alert,
                'pipeline': result.pipeline,
                'telegram_sent': bool(result.telegram_sent),
            }
        )
    except Exception as exc:
        # Map known errors to clearer codes
        try:
            from services.drill_service import DrillDisabledError, DrillScenarioNotFoundError  # type: ignore

            if isinstance(exc, DrillDisabledError):
                return jsonify({'ok': False, 'error': 'drill_disabled'}), 503
            if isinstance(exc, DrillScenarioNotFoundError):
                return jsonify({'ok': False, 'error': 'unknown_scenario'}), 400
        except Exception:
            pass
        logger.exception("drills_run_failed")
        return jsonify({'ok': False, 'error': 'internal_error'}), 500


@app.route('/api/observability/drills/history', methods=['GET'])
@login_required
def api_observability_drills_history():
    if not _require_admin_user():
        return jsonify({'ok': False, 'error': 'admin_only'}), 403
    try:
        try:
            limit = int(request.args.get('limit', 25))
        except Exception:
            limit = 25
        limit = max(1, min(200, limit))
        from monitoring.drills_storage import list_drills  # type: ignore

        drills = list_drills(limit=limit) or []
        return jsonify({'ok': True, 'drills': drills, 'total': len(drills)})
    except Exception:
        logger.exception("drills_history_failed")
        return jsonify({'ok': False, 'error': 'internal_error'}), 500


@app.route('/api/observability/drills/history/<drill_id>', methods=['GET'])
@login_required
def api_observability_drills_history_details(drill_id: str):
    if not _require_admin_user():
        return jsonify({'ok': False, 'error': 'admin_only'}), 403
    key = str(drill_id or '').strip()
    if not key:
        return jsonify({'ok': False, 'error': 'missing_drill_id'}), 400
    try:
        from monitoring.drills_storage import get_drill  # type: ignore

        doc = get_drill(key)
        if not doc:
            return jsonify({'ok': False, 'error': 'not_found'}), 404
        return jsonify({'ok': True, 'drill': doc})
    except Exception:
        logger.exception("drills_history_details_failed")
        return jsonify({'ok': False, 'error': 'internal_error'}), 500


@app.route('/api/observability/alerts', methods=['GET'])
@login_required
def api_observability_alerts():
    if not _require_admin_user():
        return jsonify({'ok': False, 'error': 'admin_only'}), 403
    try:
        # Support no_cache parameter to force fresh data (bypass cache)
        no_cache_param = (request.args.get('no_cache') or request.args.get('nc') or '').strip().lower()
        if no_cache_param in ('1', 'true', 'yes'):
            # Invalidate alerts cache before fetching
            observability_service._invalidate_alert_cache()

        start_dt, end_dt = _resolve_time_window(default_hours=24)
        page, per_page = _parse_pagination()
        severity = request.args.get('severity') or None
        if severity and severity.lower() in {'all', 'any'}:
            severity = None
        alert_type = request.args.get('alert_type') or None
        if alert_type and alert_type.lower() in {'all', 'any'}:
            alert_type = None
        endpoint = request.args.get('endpoint') or None
        search = request.args.get('search') or request.args.get('q') or None
        data = _run_observability_blocking(
            observability_service.fetch_alerts,
            start_dt=start_dt,
            end_dt=end_dt,
            severity=severity,
            alert_type=alert_type,
            endpoint=endpoint,
            search=search,
            page=page,
            per_page=per_page,
        )
        data['ok'] = True
        return jsonify(data)
    except ValueError as exc:
        logger.warning("observability_alerts_bad_request: %s", exc)
        return jsonify({'ok': False, 'error': 'bad_request'}), 400
    except Exception:
        logger.exception("observability_alerts_failed")
        return jsonify({'ok': False, 'error': 'internal_error'}), 500


# ==========================================
# Alert Tags Routes
# ==========================================


@app.route('/api/observability/alerts/<alert_uid>/tags', methods=['GET'])
@login_required
def api_get_alert_tags(alert_uid: str):
    """שליפת תגיות להתראה."""
    if not _require_admin_user():
        return jsonify({'ok': False, 'error': 'admin_only'}), 403
    result = observability_service.get_alert_tags(alert_uid)
    status = 200 if result.get("ok") else 400
    return jsonify(result), status


@app.route('/api/observability/alerts/<alert_uid>/tags', methods=['POST'])
@login_required
def api_set_alert_tags(alert_uid: str):
    """עדכון כל התגיות להתראה."""
    user_id = _require_admin_user()
    if not user_id:
        return jsonify({'ok': False, 'error': 'admin_only'}), 403
    data = request.get_json(silent=True) or {}
    result = observability_service.set_alert_tags(
        alert_uid=alert_uid,
        alert_timestamp=data.get("alert_timestamp", ""),
        tags=data.get("tags"),
        user_id=user_id,
    )
    status = 200 if result.get("ok") else 400
    return jsonify(result), status


@app.route('/api/observability/alerts/<alert_uid>/tags/add', methods=['POST'])
@login_required
def api_add_alert_tag(alert_uid: str):
    """הוספת תגית בודדת."""
    user_id = _require_admin_user()
    if not user_id:
        return jsonify({'ok': False, 'error': 'admin_only'}), 403
    data = request.get_json(silent=True) or {}
    result = observability_service.add_alert_tag(
        alert_uid=alert_uid,
        alert_timestamp=data.get("alert_timestamp", ""),
        tag=data.get("tag", ""),
        user_id=user_id,
    )
    status = 200 if result.get("ok") else 400
    return jsonify(result), status


@app.route('/api/observability/alerts/<alert_uid>/tags/<tag>', methods=['DELETE'])
@login_required
def api_remove_alert_tag(alert_uid: str, tag: str):
    """הסרת תגית."""
    if not _require_admin_user():
        return jsonify({'ok': False, 'error': 'admin_only'}), 403
    result = observability_service.remove_alert_tag(alert_uid=alert_uid, tag=tag)
    status = 200 if result.get("ok") else 400
    return jsonify(result), status


@app.route('/api/observability/tags/suggest', methods=['GET'])
@login_required
def api_suggest_tags():
    """הצעות תגיות (Autocomplete)."""
    if not _require_admin_user():
        return jsonify({'ok': False, 'error': 'admin_only'}), 403
    prefix = request.args.get("q", "")
    try:
        limit = int(request.args.get("limit", 20))
    except Exception:
        limit = 20
    limit = max(1, min(50, limit))
    result = observability_service.suggest_tags(prefix, limit)
    return jsonify(result)


@app.route('/api/observability/tags/popular', methods=['GET'])
@login_required
def api_popular_tags():
    """תגיות פופולריות."""
    if not _require_admin_user():
        return jsonify({'ok': False, 'error': 'admin_only'}), 403
    try:
        limit = int(request.args.get("limit", 50))
    except Exception:
        limit = 50
    limit = max(1, min(100, limit))
    result = observability_service.get_popular_tags(limit)
    return jsonify(result)


@app.route('/api/observability/alerts/global-tags', methods=['POST'])
@login_required
def api_set_global_alert_tags():
    """שמירת תגיות גלובליות לסוג התראה."""
    user_id = _require_admin_user()
    if not user_id:
        return jsonify({'ok': False, 'error': 'admin_only'}), 403
    data = request.get_json(silent=True) or {}
    # DEBUG: Log incoming request data
    logger.info(
        "🔍 api_set_global_alert_tags - data=%r, alert_name=%r, tags=%r (type=%s)",
        data, data.get("alert_name"), data.get("tags"), type(data.get("tags")).__name__
    )
    result = observability_service.set_global_alert_tags(
        alert_name=data.get("alert_name", ""),
        tags=data.get("tags"),
        user_id=user_id,
    )
    logger.info("🔍 api_set_global_alert_tags - result=%r", result)
    status = 200 if result.get("ok") else 400
    return jsonify(result), status


@app.route('/api/observability/alerts/signature-tags', methods=['POST'])
@login_required
def api_set_signature_alert_tags():
    """שמירת תגיות לפי חתימת שגיאה (לתיוג שגיאה ספציפית שחוזרת)."""
    user_id = _require_admin_user()
    if not user_id:
        return jsonify({'ok': False, 'error': 'admin_only'}), 403
    data = request.get_json(silent=True) or {}
    logger.info(
        "🔍 api_set_signature_alert_tags - data=%r, error_signature=%r, tags=%r (type=%s)",
        data, data.get("error_signature"), data.get("tags"), type(data.get("tags")).__name__
    )
    result = observability_service.set_signature_alert_tags(
        error_signature=data.get("error_signature", ""),
        tags=data.get("tags"),
        user_id=user_id,
    )
    logger.info("🔍 api_set_signature_alert_tags - result=%r", result)
    status = 200 if result.get("ok") else 400
    return jsonify(result), status


@app.route('/api/observability/tags/debug', methods=['GET'])
@login_required
def api_debug_tags():
    """Debug endpoint to see stored global tags, signature tags, and alert names."""
    if not _require_admin_user():
        return jsonify({'ok': False, 'error': 'admin_only'}), 403
    try:
        from monitoring import alert_tags_storage
        coll = alert_tags_storage._get_collection()
        if coll is None:
            return jsonify({'ok': False, 'error': 'db_not_available'})

        # Get all global tags (documents with alert_type_name)
        global_tags = list(coll.find(
            {"alert_type_name": {"$exists": True}},
            {"_id": 0, "alert_type_name": 1, "tags": 1}
        ).limit(50))

        # Get all signature tags (documents with error_signature)
        signature_tags = list(coll.find(
            {"error_signature": {"$exists": True}},
            {"_id": 0, "error_signature": 1, "tags": 1}
        ).limit(50))

        # Get all instance tags (documents with alert_uid)
        instance_tags = list(coll.find(
            {"alert_uid": {"$exists": True}},
            {"_id": 0, "alert_uid": 1, "tags": 1}
        ).limit(50))

        # Get sample alert_types from recent alerts
        # fetch_alerts requires start_dt and end_dt, doesn't support limit
        from monitoring import alerts_storage
        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(days=1)
        all_recent_alerts, _ = alerts_storage.fetch_alerts(
            start_dt=start_time,
            end_dt=end_time,
        )
        recent_alerts = all_recent_alerts[:20]
        alert_types_in_alerts = list(set(
            a.get("alert_type") or a.get("name") or "unknown"
            for a in recent_alerts
        ))

        return jsonify({
            'ok': True,
            'global_tags': global_tags,
            'signature_tags': signature_tags,
            'instance_tags': instance_tags,
            'alert_types_in_alerts': alert_types_in_alerts[:10],
        })
    except Exception as e:
        logger.exception("debug_tags_failed")
        return jsonify({'ok': False, 'error': 'internal_error'}), 500


@app.route('/api/observability/alerts-by-type', methods=['GET'])
@login_required
def api_observability_alerts_by_type():
    """Return specific alerts for a given alert_type (e.g., sentry_issue)."""
    if not _require_admin_user():
        return jsonify({'ok': False, 'error': 'admin_only'}), 403

    alert_type = request.args.get('alert_type', '').strip().lower()
    if not alert_type:
        return jsonify({'ok': False, 'error': 'missing_alert_type'}), 400

    try:
        limit = int(request.args.get('limit') or 100)
    except Exception:
        limit = 100
    limit = max(1, min(500, limit))

    try:
        from monitoring import alerts_storage

        rows = alerts_storage.fetch_alerts_by_type(
            alert_type=alert_type,
            limit=limit,
            include_details=True,
        )

        # Build Sentry links for alerts without permalink
        from alert_forwarder import _build_sentry_link

        for row in rows:
            if not row.get('sentry_permalink'):
                row['sentry_link'] = _build_sentry_link(
                    direct_url=None,
                    request_id=None,
                    error_signature=row.get('error_signature'),
                )
            else:
                row['sentry_link'] = row.get('sentry_permalink')

            # Format timestamp
            ts_dt = row.get('ts_dt')
            if ts_dt:
                try:
                    row['ts_iso'] = ts_dt.isoformat()
                except Exception:
                    pass
            # Ensure JSON-safe payload
            row.pop('ts_dt', None)

        return jsonify(
            {
                'ok': True,
                'alert_type': alert_type,
                'count': len(rows),
                'alerts': rows,
            }
        )
    except Exception:
        logger.exception("alerts_by_type_failed")
        return jsonify({'ok': False, 'error': 'internal_error'}), 500


@app.route('/api/observability/coverage', methods=['GET'])
@login_required
def api_observability_coverage():
    if not _require_admin_user():
        return jsonify({'ok': False, 'error': 'admin_only'}), 403
    try:
        start_dt, end_dt = _resolve_time_window(default_hours=24)
        try:
            min_count = int(request.args.get('min_count') or 1)
        except Exception:
            min_count = 1
        min_count = max(1, min(10_000, min_count))
        payload = _run_observability_blocking(
            observability_service.build_coverage_report,
            start_dt=start_dt,
            end_dt=end_dt,
            min_count=min_count,
        )
        payload['ok'] = True
        return jsonify(payload)
    except ValueError as exc:
        logger.warning("observability_coverage_bad_request: %s", exc)
        return jsonify({'ok': False, 'error': 'bad_request'}), 400
    except Exception:
        logger.exception("observability_coverage_failed")
        return jsonify({'ok': False, 'error': 'internal_error'}), 500


@app.route('/api/observability/aggregations', methods=['GET'])
@login_required
def api_observability_aggregations():
    if not _require_admin_user():
        return jsonify({'ok': False, 'error': 'admin_only'}), 403
    try:
        start_dt, end_dt = _resolve_time_window(default_hours=24)
        try:
            limit = int(request.args.get('limit', 5))
        except Exception:
            limit = 5
        limit = max(1, min(20, limit))
        payload = _run_observability_blocking(
            observability_service.fetch_aggregations,
            start_dt=start_dt,
            end_dt=end_dt,
            slow_endpoints_limit=limit,
        )
        payload['ok'] = True
        return jsonify(payload)
    except ValueError:
        logger.exception("observability_aggregations_bad_request")
        return jsonify({'ok': False, 'error': 'bad_request'}), 400
    except Exception:
        logger.exception("observability_aggregations_failed")
        return jsonify({'ok': False, 'error': 'internal_error'}), 500


@app.route('/api/observability/timeseries', methods=['GET'])
@login_required
def api_observability_timeseries():
    if not _require_admin_user():
        return jsonify({'ok': False, 'error': 'admin_only'}), 403
    try:
        start_dt, end_dt = _resolve_time_window(default_hours=7 * 24)
        granularity_arg = request.args.get('granularity') or '1h'
        granularity_seconds = _parse_duration_to_seconds(granularity_arg, default_seconds=3600)
        metric = request.args.get('metric') or 'alerts_count'
        payload = _run_observability_blocking(
            observability_service.fetch_timeseries,
            start_dt=start_dt,
            end_dt=end_dt,
            granularity_seconds=granularity_seconds,
            metric=metric,
        )
        payload['ok'] = True
        payload['granularity_seconds'] = granularity_seconds
        return jsonify(payload)
    except ValueError as exc:
        logger.warning("observability_timeseries_bad_request: %s", exc)
        return jsonify({'ok': False, 'error': 'invalid_request'}), 400
    except Exception:
        logger.exception("observability_timeseries_failed")
        return jsonify({'ok': False, 'error': 'internal_error'}), 500


@app.route('/api/observability/export', methods=['GET'])
@login_required
def api_observability_export():
    user_id = _require_admin_user()
    if not user_id:
        return jsonify({'ok': False, 'error': 'admin_only'}), 403
    try:
        start_dt, end_dt = _resolve_time_window(default_hours=24)
        timerange = request.args.get('timerange') or request.args.get('range') or '24h'
        try:
            alerts_limit = int(request.args.get('alerts_limit') or request.args.get('per_page', 120))
        except Exception:
            alerts_limit = 120
        snapshot = _run_observability_blocking(
            observability_service.build_dashboard_snapshot,
            start_dt=start_dt,
            end_dt=end_dt,
            timerange_label=timerange,
            alerts_limit=alerts_limit,
        )
        snapshot['ok'] = True
        return jsonify(snapshot)
    except ValueError as exc:
        logger.warning("observability_export_bad_request: %s", exc)
        return jsonify({'ok': False, 'error': 'bad_request'}), 400
    except Exception:
        logger.exception("observability_export_failed")
        return jsonify({'ok': False, 'error': 'internal_error'}), 500


@app.route('/api/observability/replay', methods=['GET'])
@login_required
def api_observability_replay():
    if not _require_admin_user():
        return jsonify({'ok': False, 'error': 'admin_only'}), 403
    try:
        start_dt, end_dt = _resolve_time_window(default_hours=6)
        try:
            limit = int(request.args.get('limit', 200))
        except Exception:
            limit = 200
        payload = _run_observability_blocking(
            observability_service.fetch_incident_replay,
            start_dt=start_dt,
            end_dt=end_dt,
            limit=limit,
        )
        payload['ok'] = True
        return jsonify(payload)
    except ValueError as exc:
        logger.warning("observability_replay_bad_request: %s", exc)
        return jsonify({'ok': False, 'error': 'bad_request'}), 400
    except Exception:
        logger.exception("observability_replay_failed")
        return jsonify({'ok': False, 'error': 'internal_error'}), 500


@app.route('/api/observability/runbook/<event_id>', methods=['GET'])
@login_required
def api_observability_runbook(event_id: str):
    if not _require_admin_user():
        return jsonify({'ok': False, 'error': 'admin_only'}), 403
    ui_context = request.args.get('ui') or request.args.get('context')
    fallback = {
        'alert_type': request.args.get('alert_type'),
        'type': request.args.get('type'),
        'severity': request.args.get('severity'),
        'summary': request.args.get('summary'),
        'title': request.args.get('title'),
        'timestamp': request.args.get('timestamp'),
        'endpoint': request.args.get('endpoint'),
        'source': request.args.get('source'),
        'link': request.args.get('link'),
    }
    metadata = {key: value for key, value in fallback.items() if value}
    if metadata:
        metadata['metadata'] = {
            'alert_type': metadata.get('alert_type'),
            'endpoint': metadata.get('endpoint'),
            'source': metadata.get('source'),
        }
    try:
        payload = _run_observability_blocking(
            observability_service.fetch_runbook_for_event,
            event_id=event_id,
            fallback_metadata=metadata or None,
            ui_context=ui_context,
        )
    except ValueError as exc:
        logger.info("observability_runbook_invalid_request: event_id=%s error=%s", event_id, exc)
        return jsonify({'ok': False, 'error': 'bad_request', 'message': 'Invalid request'}), 400
    except Exception:
        logger.exception("observability_runbook_fetch_failed")
        return jsonify({'ok': False, 'error': 'internal_error'}), 500
    if payload is None:
        return jsonify({'ok': True, 'event': None, 'runbook': None, 'actions': [], 'status': {}})
    payload['ok'] = True
    return jsonify(payload)


@app.route('/api/observability/runbook/<event_id>/status', methods=['POST'])
@login_required
def api_observability_runbook_status(event_id: str):
    user_id = _require_admin_user()
    if not user_id:
        return jsonify({'ok': False, 'error': 'admin_only'}), 403
    payload = request.get_json(silent=True) or {}
    ui_context = payload.get('ui') or payload.get('context')
    step_id = str(payload.get('step_id') or '').strip()
    if not step_id:
        return jsonify({'ok': False, 'error': 'missing_step_id'}), 400
    completed = bool(payload.get('completed'))
    fallback_event = payload.get('event')
    fallback_metadata = fallback_event if isinstance(fallback_event, dict) else None
    try:
        snapshot = _run_observability_blocking(
            observability_service.update_runbook_step_status,
            event_id=event_id,
            step_id=step_id,
            completed=completed,
            user_id=user_id,
            fallback_metadata=fallback_metadata,
            ui_context=ui_context,
        )
    except ValueError as exc:
        logger.warning("observability_runbook_status_invalid_request: event_id=%s error=%s", event_id, exc)
        return jsonify({'ok': False, 'error': 'bad_request', 'message': 'Invalid request'}), 400
    except Exception:
        logger.exception("observability_runbook_status_failed")
        return jsonify({'ok': False, 'error': 'internal_error'}), 500
    snapshot['ok'] = True
    return jsonify(snapshot)


@app.route('/api/observability/quickfix/track', methods=['POST'])
@login_required
def api_observability_quickfix_track():
    user_id = _require_admin_user()
    if not user_id:
        return jsonify({'ok': False, 'error': 'admin_only'}), 403
    payload = request.get_json(silent=True) or {}
    action_id = str(payload.get('action_id') or '').strip()
    action_label = str(payload.get('action_label') or '').strip()
    alert_snapshot = payload.get('alert') or {}
    if not action_id or not isinstance(alert_snapshot, dict):
        return jsonify({'ok': False, 'error': 'missing_fields'}), 400
    try:
        observability_service.record_quick_fix_action(
            action_id=action_id,
            action_label=action_label or action_id,
            alert_snapshot=alert_snapshot,
            user_id=user_id,
        )
    except Exception:
        logger.exception("observability_quickfix_track_failed")
        return jsonify({'ok': False, 'error': 'internal_error'}), 500
    return jsonify({'ok': True})


@app.route('/api/observability/alerts/ai_explain', methods=['POST'])
@login_required
def api_observability_alert_ai_explain():
    if not _require_admin_user():
        return jsonify({'ok': False, 'error': 'admin_only'}), 403
    payload = request.get_json(silent=True) or {}
    alert_snapshot = payload.get('alert')
    force_refresh = bool(payload.get('force') or payload.get('refresh'))
    if not isinstance(alert_snapshot, dict):
        return jsonify({'ok': False, 'error': 'missing_alert'}), 400
    try:
        explanation = _run_observability_blocking(
            observability_service.explain_alert_with_ai,
            alert_snapshot,
            force_refresh=force_refresh,
        )
        return jsonify({'ok': True, 'explanation': explanation})
    except ValueError as exc:
        logger.warning("observability_ai_explain_bad_request", extra={'error': str(exc)})
        return jsonify({
            'ok': False,
            'error': 'bad_request',
            'message': 'Invalid request data',
        }), 400
    except Exception:
        logger.exception("observability_ai_explain_failed")
        return jsonify({
            'ok': False,
            'error': 'internal_error',
            'message': 'הפקת הסבר נכשלה, נסה שוב מאוחר יותר',
        }), 500


@app.route('/api/observability/story/template', methods=['POST'])
@login_required
def api_observability_story_template():
    if not _require_admin_user():
        return jsonify({'ok': False, 'error': 'admin_only'}), 403
    payload = request.get_json(silent=True) or {}
    alert_snapshot = payload.get('alert')
    if not isinstance(alert_snapshot, dict):
        return jsonify({'ok': False, 'error': 'missing_alert'}), 400
    timerange = payload.get('timerange')
    try:
        template = _run_observability_blocking(
            observability_service.build_story_template,
            alert_snapshot=alert_snapshot,
            timerange_label=timerange,
        )
        return jsonify({'ok': True, 'story': template})
    except ValueError:
        return jsonify({'ok': False, 'error': 'bad_request'}), 400
    except Exception:
        logger.exception("observability_story_template_failed")
        return jsonify({'ok': False, 'error': 'internal_error'}), 500


@app.route('/api/observability/stories', methods=['POST'])
@login_required
def api_observability_story_save():
    user_id = _require_admin_user()
    if not user_id:
        return jsonify({'ok': False, 'error': 'admin_only'}), 403
    payload = request.get_json(silent=True) or {}
    story_payload = payload.get('story') if isinstance(payload.get('story'), dict) else payload
    if not isinstance(story_payload, dict):
        return jsonify({'ok': False, 'error': 'missing_story'}), 400
    try:
        stored = _run_observability_blocking(observability_service.save_incident_story, story_payload, user_id=user_id)
        return jsonify({'ok': True, 'story': stored})
    except ValueError as exc:
        logger.exception("observability_story_save_bad_request: %s", exc)
        return jsonify({'ok': False, 'error': 'bad_request'}), 400
    except Exception:
        logger.exception("observability_story_save_failed")
        return jsonify({'ok': False, 'error': 'internal_error'}), 500


@app.route('/api/observability/stories/<story_id>', methods=['GET'])
@login_required
def api_observability_story_get(story_id: str):
    if not _require_admin_user():
        return jsonify({'ok': False, 'error': 'admin_only'}), 403
    story = _run_observability_blocking(observability_service.fetch_story, story_id)
    if not story:
        return jsonify({'ok': False, 'error': 'not_found'}), 404
    return jsonify({'ok': True, 'story': story})


@app.route('/api/observability/stories/<story_id>/export', methods=['GET'])
@login_required
def api_observability_story_export(story_id: str):
    if not _require_admin_user():
        return jsonify({'ok': False, 'error': 'admin_only'}), 403
    export_format = (request.args.get('format') or 'markdown').lower()
    if export_format not in {'md', 'markdown'}:
        return jsonify({'ok': False, 'error': 'unsupported_format'}), 400
    try:
        markdown = _run_observability_blocking(observability_service.export_story_markdown, story_id)
    except Exception:
        logger.exception("observability_story_export_failed")
        return jsonify({'ok': False, 'error': 'internal_error'}), 500
    if markdown is None:
        return jsonify({'ok': False, 'error': 'not_found'}), 404
    safe_story_id = "".join(ch for ch in story_id if ch.isalnum() or ch in {'-', '_', '.'})
    if not safe_story_id:
        safe_story_id = "story"
    filename = f"incident_story_{safe_story_id}.md"
    resp = Response(markdown, mimetype='text/markdown')
    resp.headers['Content-Disposition'] = f'attachment; filename=\"{filename}\"'
    return resp


def _persist_story_markdown_file(
    *,
    user_id: int,
    file_name: str,
    markdown: str,
    alert_name: Optional[str] = None,
    alert_uid: Optional[str] = None,
    story_id: Optional[str] = None,
    extra_tags: Optional[List[str]] = None,
) -> Dict[str, Any]:
    if not isinstance(user_id, int) or user_id <= 0:
        raise ValueError("invalid_user")
    safe_name = (file_name or "").strip()
    if not safe_name:
        raise ValueError("missing_file_name")
    if len(safe_name) > 255:
        raise ValueError("file_name_too_long")
    if any(ch in safe_name for ch in {'/', '\\', '\n', '\r'}):
        raise ValueError("invalid_file_name")
    if not safe_name.lower().endswith('.md'):
        safe_name = f"{safe_name}.md"
    normalized_markdown = normalize_code(markdown or "")
    if not normalized_markdown:
        raise ValueError("empty_markdown")
    db_ref = get_db()
    if db_ref is None:
        raise RuntimeError("db_unavailable")
    try:
        prev = db_ref.code_snippets.find_one(
            {
                'user_id': user_id,
                'file_name': safe_name,
'is_active': True,
            },
            sort=[('version', -1)],
        )
    except Exception:
        prev = None
    version = int((prev or {}).get('version', 0) or 0) + 1
    now = datetime.now(timezone.utc)
    description = (alert_name or '').strip() or 'Incident Story'
    tag_sources: List[str] = ['incident-story']
    if extra_tags:
        tag_sources.extend(extra_tags)
    dedup_tags: List[str] = []
    seen_tags: set[str] = set()
    for tag in tag_sources:
        if not tag:
            continue
        text = str(tag).strip()
        if not text:
            continue
        key = text.lower()
        if key in seen_tags:
            continue
        seen_tags.add(key)
        dedup_tags.append(text)
    doc: Dict[str, Any] = {
        'user_id': user_id,
        'file_name': safe_name,
        'code': normalized_markdown,
        'programming_language': 'markdown',
        'description': description[:400],
        'tags': dedup_tags,
        'version': version,
        'created_at': now,
        'updated_at': now,
        'is_active': True,
    }
    story_context: Dict[str, Any] = {}
    if alert_uid:
        story_context['alert_uid'] = alert_uid
    if story_id:
        story_context['story_id'] = story_id
    if story_context:
        doc['story_context'] = story_context
    try:
        res = db_ref.code_snippets.insert_one(doc)
    except Exception as exc:
        logger.exception(
            "story_markdown_file_insert_failed",
            extra={'user_id': user_id, 'file_name': safe_name, 'error': str(exc)},
        )
        raise
    inserted_id = getattr(res, 'inserted_id', None)
    if not inserted_id:
        raise RuntimeError("file_insert_failed")
    try:
        cache.invalidate_user_cache(user_id)
    except Exception:
        pass
    try:
        cache.invalidate_file_related(file_id=safe_name, user_id=user_id)
    except Exception:
        pass
    return {
        'file_id': str(inserted_id),
        'file_name': safe_name,
        'version': version,
    }


@app.route('/api/observability/stories/save_markdown', methods=['POST'])
@login_required
def api_observability_story_save_markdown_file():
    user_id = _require_admin_user()
    if not user_id:
        return jsonify({'ok': False, 'error': 'admin_only'}), 403
    payload = request.get_json(silent=True) or {}
    story_payload = payload.get('story') if isinstance(payload.get('story'), dict) else payload.get('story_payload')
    file_name = (payload.get('file_name') or '').strip()
    if not file_name or not isinstance(story_payload, dict):
        return jsonify({'ok': False, 'error': 'missing_fields'}), 400
    try:
        markdown = _run_observability_blocking(observability_service.render_story_markdown_inline, story_payload)
        tags = []
        severity = (story_payload.get('severity') or '').strip()
        if severity:
            tags.append(f"severity:{severity}")
        alert_uid = story_payload.get('alert_uid')
        if alert_uid:
            tags.append(f"alert:{alert_uid}")
        result = _run_observability_blocking(
            _persist_story_markdown_file,
            user_id=user_id,
            file_name=file_name,
            markdown=markdown,
            alert_name=story_payload.get('alert_name') or story_payload.get('alert_uid'),
            alert_uid=alert_uid,
            story_id=story_payload.get('story_id'),
            extra_tags=tags,
        )
        file_id = result.get('file_id')
        view_url = url_for('view_file', file_id=file_id) if file_id else None
        md_preview_url = url_for('md_preview', file_id=file_id) if file_id else None
        payload = {'ok': True, **result}
        if view_url:
            payload['view_url'] = view_url
        if md_preview_url:
            payload['md_preview_url'] = md_preview_url
        return jsonify(payload)
    except ValueError as exc:
        logger.warning("story_markdown_save_bad_request", extra={'error': str(exc)})
        return jsonify({'ok': False, 'error': 'bad_request'}), 400
    except Exception:
        logger.exception("story_markdown_save_failed")
        return jsonify({'ok': False, 'error': 'internal_error'}), 500


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
                {
                    '$set': {'ui_prefs.editor': editor_type, 'updated_at': datetime.now(timezone.utc)},
                    '$setOnInsert': {'created_at': datetime.now(timezone.utc)},
                },
                upsert=True,
            )
        except Exception:
            # לא מפילים את הבקשה במקרה של DB בעייתי – נשמור לפחות בסשן
            pass

        return jsonify({'ok': True, 'editor_type': editor_type})
    except Exception:
        return jsonify({'ok': False, 'error': 'שגיאה לא צפויה'}), 500


@app.route('/api/settings/attention', methods=['PUT'])
@login_required
def api_update_attention_settings():
    """עדכון הגדרות ווידג'ט 'קבצים שדורשים טיפול'"""
    user_id = session['user_id']
    data = request.get_json() or {}
    
    allowed_fields = {
        'enabled', 'stale_days', 'max_items_per_group',
        'show_missing_description', 'show_missing_tags', 'show_stale_files'
    }
    
    updates = {}
    for field in allowed_fields:
        if field in data:
            value = data[field]
            if field == 'stale_days':
                value = min(max(int(value), 7), 365)
            elif field == 'max_items_per_group':
                value = min(max(int(value), 3), 50)
            elif field in ('enabled', 'show_missing_description', 'show_missing_tags', 'show_stale_files'):
                value = bool(value)
            updates[f'attention_settings.{field}'] = value
    
    if updates:
        db = get_db()
        db.user_preferences.update_one(
            {'user_id': user_id},
            {'$set': updates},
            upsert=True
        )
    
    return jsonify({'ok': True})

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
        # קאש ל-5–10 דקות (באמצעות cache_manager; Redis אם זמין, אחרת פולבק בזיכרון).
        # זה endpoint ציבורי שמרונדר הרבה ואין סיבה להפעיל aggregation כבד בכל ריענון.
        cache_key = "api:public_stats:v1"
        try:
            cached = cache.get(cache_key)
            if isinstance(cached, dict) and cached.get("ok") is True:
                payload = dict(cached)
                payload["cached"] = True
                return jsonify(payload)
        except Exception:
            pass

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

        payload = {
            "ok": True,
            "total_users": total_users,
            "active_users_24h": active_users_24h,
            "total_snippets": total_snippets,
            "timestamp": now_utc.isoformat(),
            "cached": False,
        }
        try:
            # Dynamic TTL: public_stats ברירת מחדל 10 דקות (עם התאמות פעילות)
            cache.set_dynamic(cache_key, payload, "public_stats", {"endpoint": "api_public_stats"})
        except Exception:
            pass
        return jsonify(payload)
    except Exception as e:
        return jsonify({
            "ok": False,
            "total_users": 0,
            "active_users_24h": 0,
            "total_snippets": 0,
        }), 200

# --- Auth status & user info ---

# Cache עבור העדפות משתמש
_user_prefs_cache = {}


def _get_user_prefs_cached(user_id) -> dict:
    """מחזיר העדפות UI עם cache של 60 שניות"""
    import time

    now = time.time()
    try:
        uid_int = int(user_id)
    except Exception:
        return {}

    cache_key = f"prefs_{uid_int}"

    # בדיקת cache
    if cache_key in _user_prefs_cache:
        cached_prefs, expires_at = _user_prefs_cache[cache_key]
        if expires_at > now:
            return cached_prefs

    # Cache miss - טען מDB
    prefs = {}
    try:
        _db = get_db()
        # Mongo הוא type-strict: user_id נשמר כאינט, לכן חייבים לשאול עם int
        u = _db.users.find_one({'user_id': uid_int}) or {}
        prefs = u.get('ui_prefs') or {}
    except Exception:
        prefs = {}

    # שמור בcache
    _user_prefs_cache[cache_key] = (prefs, now + 60)

    # ניקוי cache ישן
    if len(_user_prefs_cache) > 1000:
        keys_to_remove = [k for k, v in _user_prefs_cache.items() if v[1] < now]
        for k in keys_to_remove:
            _user_prefs_cache.pop(k, None)

    return prefs


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
        raw_user_data = session.get('user_data')
        user_data = raw_user_data if isinstance(raw_user_data, dict) else {}
        # אם ה-session לא הכיל dict, נוודא שמעתה הוא כן (כדי שהכתיבה תתמיד)
        if raw_user_data is None or not isinstance(raw_user_data, dict):
            user_data = {}
            session['user_data'] = user_data

        uid = session['user_id']
        try:
            uid_int = int(uid)
        except Exception:
            uid_int = None

        # ✅ Cache ל-ui_prefs (60 שניות)
        prefs = _get_user_prefs_cached(uid_int) if uid_int is not None else {}

        # ✅ roles מתוך session עם fallback (תומך sessions ישנים)
        user_is_admin = user_data.get('is_admin')
        if user_is_admin is None:
            user_is_admin = bool(is_admin(uid_int)) if uid_int is not None else False
            user_data['is_admin'] = user_is_admin
            session.modified = True

        user_is_premium = user_data.get('is_premium')
        if user_is_premium is None:
            user_is_premium = bool(is_premium(uid_int)) if uid_int is not None else False
            user_data['is_premium'] = user_is_premium
            session.modified = True

        actual_is_admin = bool(user_is_admin)
        actual_is_premium = bool(user_is_premium)
        if is_impersonating_safe():
            effective_is_admin = False
            effective_is_premium = False
        else:
            effective_is_admin = actual_is_admin
            effective_is_premium = actual_is_premium

        role_flags = {
            'is_admin': bool(effective_is_admin),
            'is_premium': bool(effective_is_premium),
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
    # תצוגה מקדימה: אל תמשוך code מלא אלא אם באמת צריך
    doc = get_internal_share(share_id, include_code=False)
    if not doc:
        return render_template('404.html'), 404

    # תצוגה ציבורית: ברירת מחדל היא snippet (או code מלא אם זה שיתוף ישן/מלא)
    code = doc.get('snippet_preview') or doc.get('code') or ''
    file_name = doc.get('file_name', 'snippet.txt')
    language = resolve_file_language(doc.get('language'), file_name)
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
    _theme = get_current_theme()
    formatter = HtmlFormatter(style=get_pygments_style(_theme), linenos=True, cssclass='source', lineanchors='line', anchorlinenos=True)
    highlighted_code = highlight(code, lexer, formatter)
    css = formatter.get_style_defs('.source')

    # מטא-דאטה: נעדיף מהמסמך (preview), אחרת נחשב מה-snippet (best-effort)
    try:
        size_bytes = int(doc.get('file_size') or 0)
    except Exception:
        size_bytes = 0
    try:
        lines_count = int(doc.get('lines_count') or 0)
    except Exception:
        lines_count = 0
    if size_bytes <= 0:
        try:
            size_bytes = len(str(code).encode('utf-8', errors='ignore'))
        except Exception:
            size_bytes = 0
    if lines_count <= 0:
        try:
            lines_count = len(str(code).splitlines())
        except Exception:
            lines_count = 0
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
        'size': format_file_size(size_bytes),
        'lines': lines_count,
        'created_at': created_at_str,
        'updated_at': created_at_str,
        'version': 1,
        'can_pin': False,
    }
    return render_template('view_file.html', file=file_data, highlighted_code=highlighted_code, syntax_css=css)


@app.route('/read/share/<share_id>')
def public_reader_mode(share_id):
    """Reader mode for public shared markdown files."""
    doc = get_internal_share(share_id, include_code=True)
    if not doc:
        return render_template('404.html'), 404

    code = doc.get('snippet_preview') or doc.get('code') or ''
    file_name = str(doc.get('file_name') or 'snippet.md').strip() or 'snippet.md'
    language = resolve_file_language(doc.get('language'), file_name)
    is_markdown = (language == 'markdown') or (file_name.lower().endswith(('.md', '.markdown')))
    if not is_markdown:
        return redirect(url_for('public_share', share_id=share_id))

    rendered_html, pygments_css = _render_markdown_preview(code)
    back_url = url_for('public_share', share_id=share_id, view='md')
    subtitle = doc.get('description') or None

    html = render_template(
        'reader_mode.html',
        title=file_name or 'README.md',
        subtitle=subtitle,
        content=rendered_html,
        pygments_css=pygments_css,
        back_url=back_url,
    )
    resp = Response(html, mimetype='text/html; charset=utf-8')
    resp.headers['Cache-Control'] = 'no-store'
    return resp


@app.route('/share/<share_id>/download')
def public_share_download(share_id: str):
    """הורדה ציבורית של שיתוף פנימי (רק לשיתופי download/full)."""
    doc = get_internal_share(share_id, include_code=True)
    if not doc:
        return render_template('404.html'), 404
    if str(doc.get('mode') or '').lower() != 'download':
        return render_template('404.html'), 404
    code = doc.get('code') or ''
    if not isinstance(code, str) or not code:
        return render_template('404.html'), 404
    file_name = str(doc.get('file_name') or 'shared.txt').strip() or 'shared.txt'
    safe = file_name.replace('..', '_').replace('/', '_').replace('\\', '_')
    from io import BytesIO
    buf = BytesIO(code.encode('utf-8', errors='ignore'))
    buf.seek(0)
    resp = send_file(buf, mimetype='text/plain; charset=utf-8', as_attachment=True, download_name=safe)
    resp.headers['Cache-Control'] = 'no-store'
    return resp

# --- Public styled HTML share route (tokens created via /api/export/styled/<file_id>/share) ---
@app.route('/shared/styled/<token>')
def public_shared_styled(token: str):
    """עמוד שיתוף ציבורי ל-HTML מעוצב לפי token מ-collection styled_shares.

    מחזיר את ה-HTML המעוצב ישירות. אם פג תוקף, מחזיר 404.
    """
    try:
        db = get_db()
        doc = db.styled_shares.find_one({'token': token})
    except Exception:
        doc = None

    if not doc:
        return render_template('404.html'), 404

    # בדיקת תוקף - קישורים קבועים לא פגים
    is_permanent = doc.get('is_permanent', False)
    exp = doc.get('expires_at')
    expired = False

    if not is_permanent:
        try:
            now = datetime.now(timezone.utc)
            if exp is None:
                expired = True
            elif isinstance(exp, datetime):
                expired = exp <= now
            else:
                expired = True
        except Exception:
            expired = True

    if expired:
        return render_template('404.html'), 404

    # עדכון מונה צפיות
    try:
        db.styled_shares.update_one(
            {'token': token},
            {'$inc': {'view_count': 1}}
        )
    except Exception:
        pass  # לא קריטי

    # החזרת ה-HTML המעוצב
    styled_html = doc.get('styled_html', '')
    if not styled_html:
        return render_template('404.html'), 404

    response = make_response(styled_html)
    response.headers['Content-Type'] = 'text/html; charset=utf-8'
    response.headers['Cache-Control'] = 'public, max-age=3600'  # cache לשעה
    # CSP restrictive - מונע הרצת סקריפטים בתוכן משתמש
    response.headers['Content-Security-Policy'] = "script-src 'none'"
    return response


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
    # תצוגת רשימה: לא צריך להחזיר code מלא (כבד מאוד)
    try:
        cursor = db.code_snippets.find(
            {'_id': {'$in': file_ids}},
            {
                'file_name': 1,
                'programming_language': 1,
                'file_size': 1,
                'lines_count': 1,
            },
        )
        files = list(cursor)
    except Exception:
        # fallback למימושים ללא projection=
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
        file_name = (f.get('file_name') or 'snippet.txt')
        language = resolve_file_language(f.get('programming_language'), file_name)
        try:
            size_bytes = int(f.get('file_size') or 0)
        except Exception:
            size_bytes = 0
        try:
            lines = int(f.get('lines_count') or 0)
        except Exception:
            lines = 0
        # fallback למסמכים ישנים בלבד (עדיף על משיכת קוד יזומה)
        if size_bytes <= 0:
            size_bytes = 0
        view_items.append({
            'id': str(f.get('_id')),
            'file_name': file_name,
            'language': language,
            'icon': get_language_icon(language),
            'size': format_file_size(size_bytes),
            'lines': lines,
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
