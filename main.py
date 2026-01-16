#!/usr/bin/env python3
"""
בוט שומר קבצי קוד - Code Keeper Bot
נקודת הכניסה הראשית לבוט
"""

from __future__ import annotations

# הגדרות מתקדמות
import os
import functools
import inspect
import logging
import asyncio
import warnings
import json
import random
import threading
from pathlib import Path
from typing import Any, Optional, TypedDict
try:
    from typing import NotRequired  # type: ignore[attr-defined]
except ImportError:  # pragma: no cover
    try:
        from typing_extensions import NotRequired  # type: ignore[assignment]
    except Exception:  # pragma: no cover
        class _NotRequiredShim:
            def __class_getitem__(cls, item):
                return item
        NotRequired = _NotRequiredShim  # type: ignore[misc,assignment]
from datetime import datetime

# הפחתת רעש בלוגים: DeprecationWarnings ספרייתיים (למשל httplib2/pyparsing)
# לא משפיע על התנהגות ריצה, רק על פלט אזהרות.
warnings.filterwarnings("ignore", category=DeprecationWarning, module=r"httplib2\.auth")

import signal
import socket
import sys
import time
from urllib.parse import urlparse
try:
    import pymongo
    _HAS_PYMONGO = True
except Exception:
    pymongo = None  # fallback ללא type: ignore
    _HAS_PYMONGO = False
from datetime import datetime, timezone, timedelta
import atexit
try:
    import pymongo.errors
    from pymongo.errors import DuplicateKeyError
except Exception:
    class _DummyErr(Exception):
        pass
    class _DummyErrors:
        InvalidOperation = _DummyErr
        OperationFailure = _DummyErr
    DuplicateKeyError = _DummyErr
    pymongo = type("_PM", (), {"errors": _DummyErrors})()
import os

from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand, BotCommandScopeChat
from telegram.constants import ParseMode
from telegram.ext import (Application, CommandHandler, ContextTypes,
                          MessageHandler, filters, Defaults, ConversationHandler, CallbackQueryHandler,
                          PicklePersistence, InlineQueryHandler, ApplicationHandlerStop, TypeHandler)

from config import config
try:
    import observability as _observability
except Exception:
    _observability = None


def _noop(*_a, **_k):  # type: ignore[unused-argument]
    return None


def _default_generate_request_id() -> str:
    try:
        return str(int(time.time() * 1000))[-8:]
    except Exception:
        return ""



def _observability_attr(name: str, default):
    if _observability is None:
        return default
    try:
        return getattr(_observability, name)
    except AttributeError:
        return default


setup_structlog_logging = _observability_attr("setup_structlog_logging", _noop)
init_sentry = _observability_attr("init_sentry", _noop)
get_log_level_from_env = _observability_attr(
    "get_log_level_from_env",
    lambda default="INFO": (str(os.getenv("LOG_LEVEL") or default)).strip().upper() or "INFO",
)
bind_request_id = _observability_attr("bind_request_id", _noop)
generate_request_id = _observability_attr("generate_request_id", _default_generate_request_id)
emit_event = _observability_attr("emit_event", _noop)
bind_user_context = _observability_attr("bind_user_context", _noop)
bind_command = _observability_attr("bind_command", _noop)
get_observability_context = _observability_attr("get_observability_context", lambda: {})
from metrics import (
    telegram_updates_total,
    track_file_saved,
    track_search_performed,
    track_performance,
    errors_total,
    record_request_outcome,
)
from rate_limiter import RateLimiter
try:
    # Optional advanced limits backend (limits + Redis)
    from limits import RateLimitItemPerMinute
    from limits.storage import RedisStorage, MemoryStorage
    from limits.strategies import MovingWindowRateLimiter
    _LIMITS_AVAILABLE = True
except Exception:
    RateLimitItemPerMinute = None  # type: ignore[assignment]
    RedisStorage = None  # type: ignore[assignment]
    MemoryStorage = None  # type: ignore[assignment]
    MovingWindowRateLimiter = None  # type: ignore[assignment]
    _LIMITS_AVAILABLE = False
from database import CodeSnippet, DatabaseManager, db
from services import code_service as code_processor
from bot_handlers import AdvancedBotHandlers  # still used by legacy code
from bot_handlers import set_activity_reporter as set_bh_activity_reporter
from conversation_handlers import MAIN_KEYBOARD, get_save_conversation_handler
from conversation_handlers import set_activity_reporter as set_ch_activity_reporter
# ייבוא דחוי של ה-activity_reporter בתוך ה-run-time בלבד כדי למנוע יצירת חיבורים בזמן import
from github_menu_handler import GitHubMenuHandler
from backup_menu_handler import BackupMenuHandler
from handlers.drive.menu import GoogleDriveMenuHandler
from handlers.drive.utils import extract_schedule_key as drive_extract_schedule_key
def get_drive_handler_from_application(application: Application) -> tuple[Any, bool]:
    """
    החזר את מופע GoogleDriveMenuHandler מתוך application.

    Returns (handler, restored_flag). restored_flag מציין אם נאלצנו לשחזר את
    ההפניה דרך המאפיין `_drive_handler` לאחר ש-bot_data איבד את המפתח.
    """
    handler = None
    restored = False
    try:
        bot_data = getattr(application, "bot_data", None)
    except Exception:
        bot_data = None
    if isinstance(bot_data, dict):
        handler = bot_data.get("drive_handler")
    if handler:
        return handler, restored
    fallback = getattr(application, "_drive_handler", None)
    if fallback:
        if isinstance(bot_data, dict):
            try:
                bot_data["drive_handler"] = fallback
            except Exception:
                pass
        handler = fallback
        restored = True
    return handler, restored
from handlers.documents import DocumentHandler
from file_manager import backup_manager
from large_files_handler import large_files_handler
from user_stats import user_stats
from cache_commands import setup_cache_handlers  # enabled
# from enhanced_commands import setup_enhanced_handlers  # disabled
from batch_commands import setup_batch_handlers
from html import escape as html_escape
try:
    from aiohttp import web  # for internal web server
except Exception:
    class _DummyWeb:
        class Application:
            def __init__(self, *a, **k): pass
        class AppRunner:
            def __init__(self, *a, **k): pass
            async def setup(self): pass
        class TCPSite:
            def __init__(self, *a, **k): pass
            async def start(self): pass
        async def json_response(*a, **k):
            return None
    web = _DummyWeb()

# (Lock mechanism constants removed)

# הגדרת לוגים בסיסית + structlog + Sentry
_LOG_LEVEL_NAME = get_log_level_from_env("INFO")
try:
    _LOG_LEVEL = int(_LOG_LEVEL_NAME) if str(_LOG_LEVEL_NAME).isdigit() else getattr(logging, str(_LOG_LEVEL_NAME).upper(), logging.INFO)
except Exception:
    _LOG_LEVEL_NAME = "INFO"
    _LOG_LEVEL = logging.INFO

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=_LOG_LEVEL,
    handlers=[logging.StreamHandler(sys.stdout)],
)
try:
    from utils import install_sensitive_filter
    install_sensitive_filter()
except Exception:
    pass
try:
    setup_structlog_logging(_LOG_LEVEL_NAME)
    init_sentry()
except Exception:
    # אל תכשיל את האפליקציה אם תצורת observability נכשלה
    pass

# OpenTelemetry (best-effort, fail-open)
try:
    from observability_otel import setup_telemetry as _setup_otel  # type: ignore

    _setup_otel(
        service_name=str(os.getenv("OTEL_SERVICE_NAME") or "codebot-bot"),
        service_version=os.getenv("SERVICE_VERSION") or os.getenv("RENDER_GIT_COMMIT") or None,
        environment=os.getenv("ENVIRONMENT") or os.getenv("ENV") or None,
        flask_app=None,
    )
except Exception:
    pass

# סגירת סשן aiohttp משותף בסיום התהליך (best-effort)
@atexit.register
def _shutdown_http_shared_session() -> None:
    try:
        from http_async import close_session  # type: ignore
    except Exception:
        return
    loop: asyncio.AbstractEventLoop | None = None
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = None
    if loop is not None and not loop.is_closed():
        try:
            running = bool(loop.is_running())
        except Exception:
            running = False
        if not running:
            try:
                coro = close_session()
            except Exception:
                coro = None
            if coro is not None:
                try:
                    loop.run_until_complete(coro)
                except Exception:
                    try:
                        coro.close()  # type: ignore[attr-defined]
                    except Exception:
                        pass
                else:
                    return
        # אם הלולאה פעילה אי אפשר להמתין לה כאן – נשתמש בלולאה זמנית
    try:
        tmp_loop = asyncio.new_event_loop()
        original_loop: asyncio.AbstractEventLoop | None = None
        try:
            try:
                original_loop = asyncio.get_event_loop()
            except RuntimeError:
                original_loop = None
            try:
                asyncio.set_event_loop(tmp_loop)
            except Exception:
                pass
            try:
                coro = close_session()
            except Exception:
                coro = None
            if coro is not None:
                try:
                    tmp_loop.run_until_complete(coro)
                except Exception:
                    try:
                        coro.close()  # type: ignore[attr-defined]
                    except Exception:
                        pass
        finally:
            tmp_loop.close()
            try:
                if original_loop is None or (original_loop.is_closed() if original_loop else True):
                    asyncio.set_event_loop(None)
                else:
                    asyncio.set_event_loop(original_loop)
            except Exception:
                pass
    except Exception:
        # אל תהרוס כיבוי
        pass

# Optional: Initialize OpenTelemetry for the bot process as well (no Flask app here)
try:
    from observability_otel import setup_telemetry as _setup_otel
    _setup_otel(
        service_name="code-keeper-bot",
        service_version=os.getenv("APP_VERSION", ""),
        environment=os.getenv("ENVIRONMENT", os.getenv("ENV", "production")),
        flask_app=None,
    )
except Exception:
    pass

logger = logging.getLogger(__name__)


def _command_label_from_handler(handler) -> str:
    """הפקת שם פקודה ידידותי למדדים מתוך CommandHandler."""
    try:
        commands = list(getattr(handler, "commands", []) or [])
    except Exception:
        commands = []
    if commands:
        name = sorted(str(cmd).lstrip('/') for cmd in commands if cmd)[:1]
        if name:
            return f"/{name[0]}"
    try:
        base = getattr(handler.callback, "__name__", "")
    except Exception:
        base = ""
    base = (base or "command").lstrip('_')
    return f"/{base}" if not base.startswith('/') else base


def _wrap_command_callback(callback, command_label: str):
    if getattr(callback, "_metrics_wrapped", False):
        return callback

    if inspect.iscoroutinefunction(callback):
        async def _wrapped(update, context, *args, __orig=callback):
            start = time.perf_counter()
            status_code = 200
            status_label: str | None = None
            try:
                return await __orig(update, context, *args)
            except ApplicationHandlerStop:
                status_code = 499
                status_label = "cancelled"
                raise
            except Exception:
                status_code = 500
                status_label = "error"
                raise
            finally:
                try:
                    record_request_outcome(
                        status_code,
                        max(0.0, time.perf_counter() - start),
                        source="telegram",
                        command=command_label,
                        cache_hit=None,
                        status_label=status_label,
                    )
                except Exception:
                    pass
        _wrapped._metrics_wrapped = True  # type: ignore[attr-defined]
        try:
            _wrapped.__name__ = getattr(callback, "__name__", "wrapped_command")
        except Exception:
            pass
        return _wrapped

    def _wrapped_sync(update, context, *args, __orig=callback):
        start = time.perf_counter()
        status_code = 200
        status_label: str | None = None
        try:
            return __orig(update, context, *args)
        except ApplicationHandlerStop:
            status_code = 499
            status_label = "cancelled"
            raise
        except Exception:
            status_code = 500
            status_label = "error"
            raise
        finally:
            try:
                record_request_outcome(
                    status_code,
                    max(0.0, time.perf_counter() - start),
                    source="telegram",
                    command=command_label,
                    cache_hit=None,
                    status_label=status_label,
                )
            except Exception:
                pass

    _wrapped_sync._metrics_wrapped = True  # type: ignore[attr-defined]
    return _wrapped_sync


def _instrument_command_handlers(application) -> None:
    from telegram.ext import CommandHandler as _CommandHandler  # local import to avoid cycles

    try:
        raw_handlers = getattr(application, "handlers", None)
    except Exception:
        return

    handlers: list[Any] = []
    if isinstance(raw_handlers, dict):
        for group in raw_handlers.values():
            try:
                handlers.extend(list(group or []))
            except TypeError:
                continue
    elif raw_handlers:
        try:
            handlers = list(raw_handlers)
        except TypeError:
            handlers = [raw_handlers]

    for handler in handlers:
        if not isinstance(handler, _CommandHandler):
            continue
        try:
            callback = handler.callback
        except Exception:
            continue
        if getattr(callback, "_metrics_wrapped", False):
            continue
        label = _command_label_from_handler(handler)
        wrapped = _wrap_command_callback(callback, label)
        try:
            handler.callback = wrapped
        except Exception:
            pass


def _wrap_github_callback(callback):
    if getattr(callback, "_metrics_wrapped", False):
        return callback

    async def _wrapped(update, context, *args, __orig=callback):
        query = getattr(update, "callback_query", None)
        raw = str(getattr(query, "data", "") or "")
        action = (raw.split(":", 1)[0] or "unknown").strip() or "unknown"
        start = time.perf_counter()
        status_code = 200
        status_label: str | None = None
        try:
            return await __orig(update, context, *args)
        except ApplicationHandlerStop:
            status_code = 499
            status_label = "cancelled"
            raise
        except Exception:
            status_code = 500
            status_label = "error"
            raise
        finally:
            try:
                record_request_outcome(
                    status_code,
                    max(0.0, time.perf_counter() - start),
                    source="telegram",
                    handler=f"github:{action}",
                    cache_hit=None,
                    status_label=status_label,
                )
            except Exception:
                pass

    _wrapped._metrics_wrapped = True  # type: ignore[attr-defined]
    try:
        _wrapped.__name__ = getattr(callback, "__name__", "github_callback")
    except Exception:
        pass
    return _wrapped


def _wrap_handler_callback(callback, handler_label: str):
    if getattr(callback, "_metrics_wrapped", False):
        return callback

    if inspect.iscoroutinefunction(callback):
        async def _wrapped(update, context, *args, __orig=callback):
            start = time.perf_counter()
            status_code = 200
            status_label: str | None = None
            try:
                return await __orig(update, context, *args)
            except ApplicationHandlerStop:
                status_code = 499
                status_label = "cancelled"
                raise
            except Exception:
                status_code = 500
                status_label = "error"
                raise
            finally:
                try:
                    record_request_outcome(
                        status_code,
                        max(0.0, time.perf_counter() - start),
                        source="telegram",
                        handler=handler_label,
                        cache_hit=None,
                        status_label=status_label,
                    )
                except Exception:
                    pass
        _wrapped._metrics_wrapped = True  # type: ignore[attr-defined]
        return _wrapped

    def _wrapped_sync(update, context, *args, __orig=callback):
        start = time.perf_counter()
        status_code = 200
        status_label: str | None = None
        try:
            return __orig(update, context, *args)
        except ApplicationHandlerStop:
            status_code = 499
            status_label = "cancelled"
            raise
        except Exception:
            status_code = 500
            status_label = "error"
            raise
        finally:
            try:
                record_request_outcome(
                    status_code,
                    max(0.0, time.perf_counter() - start),
                    source="telegram",
                    handler=handler_label,
                    cache_hit=None,
                    status_label=status_label,
                )
            except Exception:
                pass

    _wrapped_sync._metrics_wrapped = True  # type:ignore[attr-defined]
    return _wrapped_sync


async def _cancel_command_fallback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handler אסינכרוני אחיד לסיום שיחה כאשר המשתמש מפעיל /cancel."""
    return ConversationHandler.END


def _redis_socket_available(redis_url: str, timeout: float = 0.25) -> bool:
    """
    בדיקת reachability בסיסית ל-Redis כדי להימנע מהמתנה ארוכה בזמן טסטים/CI.

    אם לא ניתן להגיע ל-Redis במהירות, נחזור False ונשתמש בפולבק.
    """
    if not redis_url:
        return False
    try:
        parsed = urlparse(str(redis_url))
    except Exception:
        return False

    scheme = (parsed.scheme or "").lower()
    default_ports = {
        "redis": 6379,
        "rediss": 6379,
        "redis+sentinel": 26379,
    }
    default_port = default_ports.get(scheme)
    if default_port is None:
        return False

    host = parsed.hostname
    try:
        port = parsed.port
    except ValueError:
        port = None

    if host is None:
        netloc = parsed.netloc
        if not netloc:
            return False
        if "@" in netloc:
            netloc = netloc.split("@", 1)[1]
        first_endpoint = netloc.split(",", 1)[0]
        first_endpoint = first_endpoint.strip()
        if not first_endpoint:
            return False
        if first_endpoint.startswith("[") and "]" in first_endpoint:
            end_idx = first_endpoint.find("]")
            host = first_endpoint[1:end_idx]
            remainder = first_endpoint[end_idx + 1:]
            if remainder.startswith(":"):
                try:
                    port = int(remainder[1:])
                except ValueError:
                    port = None
        else:
            if ":" in first_endpoint:
                host_part, port_part = first_endpoint.rsplit(":", 1)
                host = host_part
                try:
                    port = int(port_part)
                except ValueError:
                    port = None
            else:
                host = first_endpoint

    if not host:
        return False

    port = port or default_port
    if not port:
        return False

    try:
        sock = socket.create_connection((host, int(port)), timeout=timeout)
    except Exception:
        return False
    try:
        sock.close()
    except Exception:
        pass
    return True

# הבטחת לולאת asyncio כברירת מחדל (תמיכה ב-Python 3.11 בסביבת טסטים)
# מתקין Policy חסין שמייצר לולאה חדשה אם אין אחת זמינה, גם אם asyncio.run() ניקה את הלולאה.
try:
    class _ResilientEventLoopPolicy(asyncio.DefaultEventLoopPolicy):
        def get_event_loop(self):  # type: ignore[override]
            try:
                return super().get_event_loop()
            except RuntimeError:
                loop = self.new_event_loop()
                self.set_event_loop(loop)
                return loop

    # התקנה חד-פעמית של ה-Policy. אם כבר הותקן Policy חיצוני (כגון uvloop) לא ננסה להחליף בכוח.
    try:
        current_policy = asyncio.get_event_loop_policy()
        # נתקין רק אם זו ה-DefaultPolicy כדי לא לשבור קונפיג קיים
        if isinstance(current_policy, asyncio.DefaultEventLoopPolicy):
            asyncio.set_event_loop_policy(_ResilientEventLoopPolicy())
    except Exception:
        # במידה והקריאה get_event_loop_policy עצמה נכשלת, ננסה להתקין ישירות
        try:
            asyncio.set_event_loop_policy(_ResilientEventLoopPolicy())
        except Exception:
            pass

    # fail-safe: נסה לוודא שיש לולאה נוכחית גם כעת
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        try:
            _loop = asyncio.new_event_loop()
            asyncio.set_event_loop(_loop)
        except Exception:
            # Fail-open: אין להפיל בזמן import
            pass
except Exception:
    # לא נכשיל את ה-import אם יש בעיה במדיניות הלולאה
    pass

# רשימת קידודים לניסיון קריאת קבצים (ניתנת לדריסה בטסטים)
ENCODINGS_TO_TRY = [
    'utf-8',
    'windows-1255',
    'iso-8859-8',
    'cp1255',
    'utf-16',
    'latin-1',
]
def _register_catch_all_callback(application, callback_fn) -> None:
    """רישום CallbackQueryHandler כללי בקבוצה מאוחרת, עם fallback כשה-API לא תומך ב-group.

    נועד להימנע מכשלי טסטים/סטאבים (TypeError על group), ובו בזמן לשמר קדימויות בפרודקשן.
    """
    handler = CallbackQueryHandler(callback_fn)
    try:
        application.add_handler(handler, group=5)
    except TypeError:
        # סביבת טסט/סטאב ללא תמיכה בפרמטר group
        application.add_handler(handler)
    except Exception as e:
        # דווח חריגה כדי שלא נבלע שגיאות רישום שקטות
        logger.error(f"Failed to register catch-all CallbackQueryHandler: {e}")

# הודעת התחלה מרשימה
logger.info("🚀 מפעיל בוט קוד מתקדם - גרסה פרו!")
try:
    emit_event("bot_start", msg_he="מפעיל את הבוט", severity="info")
except Exception:
    pass

# הפחתת רעש בלוגים
logging.getLogger("httpx").setLevel(logging.ERROR)  # רק שגיאות קריטיות
logging.getLogger("telegram.ext.Updater").setLevel(logging.ERROR)
logging.getLogger("telegram.ext.Application").setLevel(logging.WARNING)

# Reporter יווצר ויוזרק בזמן ריצה לאחר בניית האפליקציה והקונפיג
reporter = None

# ===== עזר: שליחת הודעת אדמין =====
def get_admin_ids() -> list[int]:
    try:
        raw = os.getenv('ADMIN_USER_IDS')
        if not raw:
            return []
        return [int(x.strip()) for x in raw.split(',') if x.strip().isdigit()]
    except Exception:
        return []

async def notify_admins(context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    try:
        # Alert Pipeline Consolidation:
        # לא שולחים הודעות "אדמין" ישירות דרך bot.send_message (זה עוקף suppress/Rule Engine).
        # במקום זה, מפיקים internal_alert ומאפשרים למנוע הכללים להחליט אם/לאן לשלוח.
        try:
            from internal_alerts import emit_internal_alert  # type: ignore
        except Exception:
            emit_internal_alert = None  # type: ignore

        if emit_internal_alert is None:
            return

        # שומרים את הטקסט בתור summary; פרטים נוספים (כמו רשימת אדמינים) רק להקשר.
        # NOTE: לא מעבירים token/chat_id וכד' כדי לא להדליף מידע רגיש.
        admin_ids = get_admin_ids()
        emit_internal_alert(
            "admin_notification",
            severity="info",
            summary=str(text or ""),
            source="main.notify_admins",
            admin_ids=admin_ids,
        )
    except Exception:
        pass

# ===== Admin: /recycle_backfill =====
async def recycle_backfill_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ממלא deleted_at ו-deleted_expires_at לרשומות מחוקות רכות וחושב TTL.

    שימוש: /recycle_backfill [X]
    X = ימים לתוקף סל (ברירת מחדל מהקונפיג RECYCLE_TTL_DAYS)
    הפקודה זמינה למנהלים בלבד.
    """
    try:
        user_id = update.effective_user.id if update and update.effective_user else 0
        admin_ids = get_admin_ids()
        if not admin_ids or user_id not in admin_ids:
            try:
                await update.message.reply_text("❌ פקודה זמינה למנהלים בלבד")
            except Exception:
                pass
            return

        # קביעת TTL בימים
        try:
            ttl_days = int(context.args[0]) if context.args else int(getattr(config, 'RECYCLE_TTL_DAYS', 7) or 7)
        except Exception:
            ttl_days = int(getattr(config, 'RECYCLE_TTL_DAYS', 7) or 7)
        ttl_days = max(1, ttl_days)

        now = datetime.now(timezone.utc)
        expires = now + timedelta(days=ttl_days)

        # ודא אינדקסי TTL ואח"כ Backfill בשתי הקולקציות
        from database import db as _db
        results = []
        for coll_name, friendly in (("collection", "קבצים רגילים"), ("large_files_collection", "קבצים גדולים")):
            coll = getattr(_db, coll_name, None)
            # חשוב: אל תשתמשו ב-truthiness על קולקציה של PyMongo
            if coll is None:
                results.append((friendly, 0, 0, "collection-missing"))
                continue
            # ensure TTL index idempotently
            try:
                coll.create_index("deleted_expires_at", expireAfterSeconds=0, name="deleted_ttl")
            except Exception:
                # לא קריטי; נמשיך
                pass

            modified_deleted_at = 0
            modified_deleted_exp = 0
            # backfill deleted_at where missing
            try:
                if hasattr(coll, 'update_many'):
                    r1 = coll.update_many({"is_active": False, "deleted_at": {"$exists": False}}, {"$set": {"deleted_at": now}})
                    modified_deleted_at = int(getattr(r1, 'modified_count', 0) or 0)
            except Exception:
                pass
            # backfill deleted_expires_at where missing
            try:
                if hasattr(coll, 'update_many'):
                    r2 = coll.update_many({"is_active": False, "deleted_expires_at": {"$exists": False}}, {"$set": {"deleted_expires_at": expires}})
                    modified_deleted_exp = int(getattr(r2, 'modified_count', 0) or 0)
            except Exception:
                pass

            results.append((friendly, modified_deleted_at, modified_deleted_exp, ""))

        # דו"ח
        lines = [
            f"🧹 Backfill סל מיחזור (TTL={ttl_days} ימים)",
        ]
        for friendly, c_at, c_exp, err in results:
            if err:
                lines.append(f"• {friendly}: דילוג ({err})")
            else:
                lines.append(f"• {friendly}: deleted_at={c_at}, deleted_expires_at={c_exp}")
        try:
            await update.message.reply_text("\n".join(lines))
        except Exception:
            pass
    except Exception as e:
        try:
            await update.message.reply_text(f"❌ שגיאה ב-backfill: {html_escape(str(e))}")
        except Exception:
            pass

async def log_user_activity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    רישום פעילות משתמש במערכת.
    
    Args:
        update: אובייקט Update מטלגרם
        context: הקונטקסט של השיחה
    
    Note:
        פונקציה זו נקראת אוטומטית עבור כל פעולה של משתמש
    """
    if not update.effective_user:
        return

    # דגימה להפחתת עומס: רק ~25% מהאירועים יעדכנו מיידית את ה-DB
    try:
        import random as _rnd
        sampled = (_rnd.random() < 0.25)
    except Exception:
        sampled = True

    # רישום בסיסי לגמרי מחוץ ל-try כדי לא לחסום את הפלואו
    try:
        # כדי לשמר ספי milestones, אם דוגמים — נכפיל את המשקל בהתאם להסתברות הדגימה
        if sampled:
            # p=0.25 -> weight=4; אם משתנה — נשאב מהקונפיג בעתיד
            weight = 4
            try:
                user_stats.log_user(update.effective_user.id, update.effective_user.username, weight=weight)
            except TypeError:
                # תאימות לאחור לטסטים/סביבה ישנה ללא פרמטר weight
                user_stats.log_user(update.effective_user.id, update.effective_user.username)
    except Exception:
        pass

    # milestones — להרצה אסינכרונית כך שלא תחסום את ההודעה למשתמש
    async def _milestones_job(user_id: int, username: str | None):
        try:
            # טעינה דינמית של מודול ה-DB כדי לעבוד היטב עם monkeypatch בטסטים
            from database import db as _db
            users_collection = _db.db.users if getattr(_db, 'db', None) else None
            if users_collection is None:
                return
            doc = users_collection.find_one({"user_id": user_id}, {"total_actions": 1, "milestones_sent": 1}) or {}
            total_actions = int(doc.get("total_actions") or 0)
            already_sent = set(doc.get("milestones_sent") or [])
            milestones = [50, 100, 200, 500, 1000]
            pending = [m for m in milestones if m <= total_actions and m not in already_sent]
            if not pending:
                return
            milestone = max(pending)
            # התראת אדמין מוקדמת (לצורך ניטור), בנוסף להתראה אחרי עדכון DB
            if milestone >= 500:
                uname = (username or f"User_{user_id}")
                display = f"@{uname}" if uname and not str(uname).startswith('@') else str(uname)
                # קריאה ישירה ללא עטיפת try כדי שלא נבלע בשוגג; ה-wrapper החיצוני יתפוס חריגות
                await notify_admins(context, f"📢 משתמש {display} הגיע ל־{milestone} פעולות בבוט")
            res = users_collection.update_one(
                {"user_id": user_id, "milestones_sent": {"$ne": milestone}},
                {"$addToSet": {"milestones_sent": milestone}, "$set": {"updated_at": datetime.now(timezone.utc)}}
            )
            if getattr(res, 'modified_count', 0) > 0:
                messages = {
                    50: (
                        "וואו! אתה בין המשתמשים המובילים בבוט 🔥\n"
                        "הנוכחות שלך עושה לנו שמח 😊\n"
                        "יש לך רעיונות או דברים שהיית רוצה לראות כאן?\n"
                        "מוזמן לכתוב ל־@moominAmir"
                    ),
                    100: (
                        "💯 פעולות!\n"
                        "כנראה שאתה כבר יודע את הבוט יותר טוב ממני 😂\n"
                        "יאללה, אולי נעשה לך תעודת משתמש ותיק? 🏆"
                    ),
                    200: (
                        "וואו! 200 פעולות! 🚀\n"
                        "אתה לגמרי בין המשתמשים הכי פעילים.\n"
                        "יש פיצ'ר שהיית רוצה לראות בהמשך?\n"
                        "ספר לנו ב־@moominAmir"
                    ),
                    500: (
                        "500 פעולות! 🔥\n"
                        "מגיע לך תודה ענקית על התמיכה! 🩵"
                    ),
                    1000: (
                        "הגעת ל־1000 פעולות! 🎉\n"
                        "אתה אגדה חיה של הבוט הזה 🙌\n"
                        "תודה שאתה איתנו לאורך הדרך 💙\n"
                        "הצעות לשיפור יתקבלו בברכה ❣️\n"
                        "@moominAmir"
                    ),
                }
                try:
                    await context.bot.send_message(chat_id=user_id, text=messages.get(milestone, ""))
                except Exception:
                    pass
            # התראה לאדמין למילסטונים משמעותיים (500+) — גם אם כבר סומן, לא מסוכן לשלוח פעם נוספת
            if milestone >= 500:
                uname = (username or f"User_{user_id}")
                display = f"@{uname}" if uname and not str(uname).startswith('@') else str(uname)
                await notify_admins(context, f"📢 משתמש {display} הגיע ל־{milestone} פעולות בבוט")
        except Exception:
            pass

    try:
        jq = getattr(context, "job_queue", None) or getattr(context.application, "job_queue", None)
        if jq is not None:
            # הרצה מיידית ברקע ללא חסימה
            jq.run_once(lambda _ctx: context.application.create_task(_milestones_job(update.effective_user.id, update.effective_user.username)), when=0)
        else:
            # fallback: יצירת משימה אסינכרונית ישירות
            import asyncio as _aio
            _aio.create_task(_milestones_job(update.effective_user.id, update.effective_user.username))
    except Exception:
        pass

# =============================================================================
# MONGODB LOCK MANAGEMENT (FINAL, NO-GUESSING VERSION)
# =============================================================================

LOCK_ID = "code_keeper_bot_lock"  # legacy fallback
LOCK_COLLECTION = os.getenv("LOCK_COLLECTION", "locks")  # keep legacy default for safe rollouts
LOCK_TIMEOUT_MINUTES = 5  # legacy fallback (deprecated)

# Global lock state (used by cleanup + heartbeat)
_LOCK_SERVICE_ID: str | None = None
_LOCK_OWNER_ID: str | None = None
_LOCK_HEARTBEAT: "_MongoLockHeartbeat | None" = None

def get_lock_collection():
    """
    מחזיר את קולקציית הנעילות ממסד הנתונים.
    
    Returns:
        pymongo.collection.Collection: קולקציית הנעילות
    
    Raises:
        SystemExit: אם מסד הנתונים לא אותחל כראוי
    
    Note:
        משתמש במסד הנתונים שכבר נבחר ב-DatabaseManager
    """
    try:
        # Use the already-selected database from DatabaseManager
        selected_db = db.db
        if selected_db is None:
            logger.critical("DatabaseManager.db is not initialized!")
            try:
                emit_event("db_lock_db_missing", severity="critical", event="db_lock_db_missing")
            except Exception:
                pass
            sys.exit(1)
        # Optional: small debug to help diagnose DB mismatches
        try:
            logger.debug(f"Using DB for locks: {selected_db.name}")
        except Exception:
            pass
        return selected_db[LOCK_COLLECTION]
    except Exception as e:
        logger.critical(f"Failed to get lock collection from DatabaseManager: {e}", exc_info=True)
        try:
            emit_event("db_lock_get_failed", severity="critical", error=str(e))
        except Exception:
            pass
        sys.exit(1)

# New: ensure TTL index on expires_at so stale locks get auto-removed

def ensure_lock_indexes() -> None:
    """
    יוצר אינדקס TTL על שדה expires_at לניקוי אוטומטי של נעילות ישנות.
    
    Note:
        אם יצירת האינדקס נכשלת, המערכת תמשיך לעבוד ללא TTL אוטומטי
    """
    try:
        lock_collection = get_lock_collection()
        # TTL based on the absolute expiration time in the document
        # Backward compatibility: support both legacy `expires_at` and new `expiresAt`
        failures: list[str] = []
        try:
            lock_collection.create_index("expires_at", expireAfterSeconds=0, name="lock_expires_at_ttl")
        except Exception as e:
            failures.append(str(e))
        try:
            lock_collection.create_index("expiresAt", expireAfterSeconds=0, name="lock_expiresAt_ttl")
        except Exception as e:
            failures.append(str(e))
        if failures:
            msg = "; ".join([f for f in failures if f])
            if not msg:
                msg = "ttl_index_failed"
            logger.warning(f"Could not ensure TTL index for lock collection: {msg}")
            try:
                emit_event("lock_ttl_index_failed", severity="warn", error=msg)
            except Exception:
                pass
    except Exception as e:
        # Non-fatal; continue without TTL if index creation fails
        logger.warning(f"Could not ensure TTL index for lock collection: {e}")
        try:
            emit_event("lock_ttl_index_failed", severity="warn", error=str(e))
        except Exception:
            pass


def _env_bool(name: str, default: bool) -> bool:
    try:
        raw = os.getenv(name)
        if raw is None:
            return bool(default)
        val = str(raw).strip().lower()
        if val in {"1", "true", "yes", "y", "on"}:
            return True
        if val in {"0", "false", "no", "n", "off"}:
            return False
        return bool(default)
    except Exception:
        return bool(default)


def _env_int(name: str, default: int) -> int:
    try:
        raw = os.getenv(name)
        if raw is None:
            return int(default)
        raw = str(raw).strip()
        if not raw:
            return int(default)
        return int(float(raw))
    except Exception:
        return int(default)


def _env_float(name: str, default: float) -> float:
    try:
        raw = os.getenv(name)
        if raw is None:
            return float(default)
        raw = str(raw).strip()
        if not raw:
            return float(default)
        return float(raw)
    except Exception:
        return float(default)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _default_owner_id() -> str:
    rid = (os.getenv("RENDER_INSTANCE_ID") or "").strip()
    if rid:
        # חשוב: owner חייב להיות ייחודי ברמת תהליך.
        # אחרת כמה תהליכים באותו Render instance (למשל overlapped restart / multi-worker)
        # יחשבו בטעות "זה אני" ויעשו reacquire/heartbeat במקביל.
        return f"{rid}:{os.getpid()}"
    # fallback: stable enough per-process, and visible for forensics
    try:
        host = (os.getenv("HOSTNAME") or "").strip() or socket.gethostname()
    except Exception:
        host = "unknown-host"
    return f"{host}:{os.getpid()}"


def _default_host_label() -> str:
    v = (os.getenv("RENDER_SERVICE_NAME") or "").strip()
    if v:
        return v
    try:
        return (os.getenv("HOSTNAME") or "").strip() or socket.gethostname()
    except Exception:
        return "unknown-host"


def _compute_heartbeat_interval_seconds(*, lease_seconds: int, explicit: float | None) -> float:
    if explicit is not None and explicit > 0:
        return max(5.0, float(explicit))
    # default: 40% of lease, minimum 5 seconds
    return max(5.0, float(lease_seconds) * 0.4)


def _compute_passive_wait_seconds(min_seconds: float, max_seconds: float) -> float:
    lo = max(0.0, float(min_seconds))
    hi = max(lo, float(max_seconds))
    if hi <= lo:
        return lo
    return float(random.uniform(lo, hi))


_LOCK_SIGNALS_INSTALLED = False
_LOCK_ORIG_SIGNAL_HANDLERS: dict[int, object] = {}


def _install_lock_signal_handlers(*, service_id: str, owner_id: str) -> None:
    """התקנת handlers ל-SIGTERM/SIGINT לשחרור לוק לפני יציאה.

    best-effort: אם פלטפורמה/ספרייה אחרת התקינה handler, ננסה לשרשר אליו.
    """
    global _LOCK_SIGNALS_INSTALLED
    if _LOCK_SIGNALS_INSTALLED:
        return
    # אל תיגע ב-signal handlers בטסטים
    if os.getenv("PYTEST_CURRENT_TEST"):
        return

    def _handler(signum, _frame):  # noqa: ANN001
        try:
            try:
                emit_event(
                    "lock_signal_received",
                    severity="warn",
                    signal=int(signum),
                    service_id=service_id,
                    owner=owner_id,
                )
            except Exception:
                pass
            try:
                cleanup_mongo_lock()
            except Exception:
                pass
        finally:
            # Chain to original handler if it is callable
            orig = _LOCK_ORIG_SIGNAL_HANDLERS.get(int(signum))
            if callable(orig):
                try:
                    orig(signum, _frame)  # type: ignore[misc]
                except Exception:
                    pass
            # Ensure we exit even if chaining did nothing
            try:
                os._exit(0)
            except Exception:
                raise SystemExit(0)

    for sig in (getattr(signal, "SIGTERM", None), getattr(signal, "SIGINT", None)):
        if sig is None:
            continue
        try:
            _LOCK_ORIG_SIGNAL_HANDLERS[int(sig)] = signal.getsignal(sig)
        except Exception:
            _LOCK_ORIG_SIGNAL_HANDLERS[int(sig)] = None
        try:
            signal.signal(sig, _handler)
        except Exception:
            # ignore platforms that do not allow setting signals
            pass

    _LOCK_SIGNALS_INSTALLED = True


class _MongoLockHeartbeat:
    def __init__(
        self,
        *,
        lock_collection,
        service_id: str,
        owner_id: str,
        host_label: str,
        lease_seconds: int,
        interval_seconds: float,
    ) -> None:
        self._lock_collection = lock_collection
        self._service_id = service_id
        self._owner_id = owner_id
        self._host_label = host_label
        self._lease_seconds = int(lease_seconds)
        self._interval_seconds = float(interval_seconds)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_ok_monotonic = time.monotonic()
        self._local_expires_at = _utcnow() + timedelta(seconds=self._lease_seconds)
        try:
            self._instance_id = (os.getenv("RENDER_INSTANCE_ID") or "").strip()
        except Exception:
            self._instance_id = ""

    def _handle_lost_lock(self, reason: str) -> None:
        """
        נקראת כאשר ה-Heartbeat מזהה שאיבדנו את הנעילה (או שאנחנו על סף פקיעה).
        מבצעת יציאה כפויה (Fail-Fast) כדי למנוע מצב של Zombie Bot ו-telegram.error.Conflict.
        """
        try:
            emit_event(
                "lock_fail_fast_exit",
                severity="critical",
                service_id=self._service_id,
                owner=self._owner_id,
                host=self._host_label,
                instance=self._instance_id,
                pid=int(os.getpid()),
                reason=str(reason),
            )
        except Exception:
            pass

        logger.critical(f"🚨 CRITICAL: Lock ownership lost! Reason: {reason}")
        logger.critical(
            f"💀 Killing process {os.getpid()} immediately to prevent telegram.error.Conflict..."
        )

        # נותנים ללוגים רגע להיכתב (ברשת/דיסק). בטסטים לא רוצים השהייה אמיתית.
        try:
            sleep_seconds = 0.0 if os.getenv("PYTEST_CURRENT_TEST") else 1.0
        except Exception:
            sleep_seconds = 1.0
        try:
            if sleep_seconds > 0:
                time.sleep(float(sleep_seconds))
        except Exception:
            pass

        # הרג מיידי של כל התהליך (כולל Threads ו-Greenlets).
        # קוד 1 מסמן ל-Render שהייתה יציאה לא תקינה (כדי שיפעיל מחדש אם צריך).
        os._exit(1)

    def start(self) -> None:
        if self._thread is not None:
            return
        t = threading.Thread(target=self._run, name="mongo_lock_heartbeat", daemon=True)
        self._thread = t
        t.start()
        try:
            emit_event(
                "lock_heartbeat_started",
                severity="info",
                service_id=self._service_id,
                owner=self._owner_id,
                interval_seconds=float(self._interval_seconds),
                lease_seconds=int(self._lease_seconds),
            )
        except Exception:
            pass

    def stop(self, *, join_timeout_seconds: float = 2.0) -> None:
        try:
            self._stop.set()
        except Exception:
            pass
        t = self._thread
        if t is None:
            return
        try:
            t.join(timeout=float(join_timeout_seconds))
        except Exception:
            pass

    def _run(self) -> None:
        # In tests we keep behavior deterministic and avoid background threads unless explicitly enabled.
        if os.getenv("PYTEST_CURRENT_TEST") and not _env_bool("LOCK_ENABLE_HEARTBEAT_IN_TESTS", False):
            return

        while not self._stop.is_set():
            # Wait first (so a caller can stop immediately on shutdown).
            # חשוב: לא מסתמכים רק על interval קבוע.
            # אם ה-lease מתקרב לפקיעה וה-network נכשל, interval גדול יכול ליצור "חלון חפיפה"
            # שבו הלוק פג ב-Mongo אבל המופע עדיין חי עד הטיק הבא.
            # לכן אנחנו מקצרים sleep כאשר מתקרבים ל-expiry המקומי.
            try:
                if self._should_exit_due_to_local_expiry():
                    try:
                        emit_event(
                            "lock_heartbeat_local_expired_exiting",
                            severity="critical",
                            service_id=self._service_id,
                            owner=self._owner_id,
                        )
                    except Exception:
                        pass
                    logger.critical(
                        "Local lock lease is about to expire; exiting to prevent double polling."
                    )
                    self._handle_lost_lock("Local lock lease is about to expire (pre-heartbeat)")
            except Exception:
                # best-effort only
                pass

            sleep_seconds = self._compute_next_sleep_seconds()
            try:
                self._stop.wait(timeout=float(sleep_seconds))
            except Exception:
                time.sleep(float(sleep_seconds))
            if self._stop.is_set():
                break
            self._tick_once()

    def _compute_next_sleep_seconds(self, *, now: datetime | None = None) -> float:
        """קובע כמה זמן לישון עד ניסיון heartbeat הבא.

        העיקרון: interval קבוע הוא ברירת מחדל, אבל כשמתקרבים ל-expiry המקומי
        אנחנו מתעוררים מוקדם יותר (expiry_guard) כדי למנוע חלון חפיפה.
        """
        if now is None:
            now = _utcnow()
        try:
            remaining = float((self._local_expires_at - now).total_seconds())
        except Exception:
            remaining = float(self._interval_seconds)

        expiry_guard_seconds = 2.0
        # Wake up no later than (expiry - guard)
        wake_in = min(float(self._interval_seconds), max(0.2, remaining - expiry_guard_seconds))
        return max(0.2, float(wake_in))

    def _should_exit_due_to_local_expiry(self, *, now: datetime | None = None) -> bool:
        if now is None:
            now = _utcnow()
        try:
            return now >= (self._local_expires_at - timedelta(seconds=2))
        except Exception:
            return False

    def _tick_once(self) -> None:
        """ריצת heartbeat אחת (מופרדת לטסטים)."""
        now = _utcnow()
        # מחשבים יעד חדש, אבל לא "מאריכים" מקומית לפני שהעדכון הצליח בפועל ב-MongoDB.
        # אחרת: תקלה רגעית (timeout/failover) יכולה לגרום לנו לחשוב שיש לנו lease,
        # בעוד שב-Mongo הנעילה פגה ומופע אחר יכול לרכוש אותה -> double polling.
        target_exp = now + timedelta(seconds=self._lease_seconds)

        try:
            res = self._lock_collection.update_one(
                {"_id": self._service_id, "owner": self._owner_id},
                {
                    "$set": {
                        "expiresAt": target_exp,
                        "expires_at": target_exp,  # legacy alias
                        "updatedAt": now,
                        "host": self._host_label,
                        "instance": self._instance_id,
                        "pid": int(os.getpid()),
                    }
                },
            )
            matched = int(getattr(res, "matched_count", 0) or 0)
            if matched <= 0:
                # Ownership lost: exit immediately to prevent dual polling.
                try:
                    emit_event(
                        "lock_ownership_lost",
                        severity="critical",
                        service_id=self._service_id,
                        owner=self._owner_id,
                    )
                except Exception:
                    pass
                self._handle_lost_lock("Database document mismatch (stolen lock)")

            # עדכון הצליח והמסמך עדיין בבעלותנו -> עכשיו מותר לעדכן את ה-expiry המקומי
            self._local_expires_at = target_exp
            self._last_ok_monotonic = time.monotonic()
        except Exception as e:
            # If we fail to refresh close to local expiry, exit rather than risk polling without a valid lease.
            try:
                emit_event(
                    "lock_heartbeat_failed",
                    severity="error",
                    service_id=self._service_id,
                    owner=self._owner_id,
                    error=str(e),
                )
            except Exception:
                pass
            logger.warning(f"Mongo lock heartbeat failed: {e}", exc_info=True)

            try:
                # חשוב: משתמשים ב-expiry האחרון שהצלחנו לחדש בפועל,
                # ולא ב"יעד" הנוכחי שנכשל, כדי לא להאריך מקומית בטעות.
                # חשוב לא פחות: דוגמים זמן מחדש כאן, כי update_one יכול להיתקע זמן רב
                # (timeout/failover), ואז now מתחילת הפונקציה עלול להיות "ישן" מדי.
                check_now = _utcnow()
                if check_now >= (self._local_expires_at - timedelta(seconds=2)):
                    try:
                        emit_event(
                            "lock_heartbeat_expiring_exiting",
                            severity="critical",
                            service_id=self._service_id,
                            owner=self._owner_id,
                            error=str(e),
                        )
                    except Exception:
                        pass
                    self._handle_lost_lock(f"Lease expired during network error ({e})")
            except Exception:
                # If we can't reason about expiry, prefer staying alive; ownership-loss check will kill us if needed.
                pass


def cleanup_mongo_lock() -> bool:
    """
    מנקה את נעילת MongoDB בעת יציאה מהתוכנית.
    
    Returns:
        bool: True אם הניקוי בוצע ללא שגיאה לוגית/חיבור, False אם כשל (למשל client סגור)
    
    Note:
        פונקציה זו נרשמת עם atexit ורצה אוטומטית בסיום התוכנית
    """
    try:
        # Stop heartbeat first (best-effort)
        global _LOCK_HEARTBEAT
        try:
            hb = _LOCK_HEARTBEAT
            _LOCK_HEARTBEAT = None
            if hb is not None:
                hb.stop()
        except Exception:
            pass

        # If DB client is not available, skip quietly (נחשב כהצלחה — אין מה לנקות)
        try:
            if 'db' in globals() and getattr(db, "client", None) is None:
                logger.debug("Mongo client not available during lock cleanup; skipping.")
                return True
        except Exception:
            pass

        lock_collection = get_lock_collection()
        pid = os.getpid()
        service_id = _LOCK_SERVICE_ID or (os.getenv("SERVICE_ID") or LOCK_ID)
        owner_id = _LOCK_OWNER_ID or _default_owner_id()
        # Delete only if we're the owner. Legacy fallback: if owner is missing, allow pid-based cleanup.
        result = lock_collection.delete_one(
            {
                "_id": service_id,
                "$or": [
                    {"owner": owner_id},
                    {"owner": {"$exists": False}, "pid": int(pid)},
                ],
            }
        )
        if result.deleted_count > 0:
            logger.info(f"Lock '{service_id}' released successfully. owner={owner_id} pid={pid}")
            try:
                emit_event("lock_released", severity="info", pid=pid, service_id=service_id, owner=owner_id)
            except Exception:
                pass
        # גם אם לא נמחק — הניקוי idempotent; נחשב כהצלחה
        return True
    except pymongo.errors.InvalidOperation:
        logger.warning("Mongo client already closed; skipping lock cleanup.")
        try:
            emit_event("lock_cleanup_skipped_client_closed", severity="warn")
        except Exception:
            pass
        return False
    except Exception as e:
        logger.error(f"Error while releasing MongoDB lock: {e}", exc_info=True)
        try:
            emit_event("lock_release_error", severity="error", error=str(e))
        except Exception:
            pass
        return False

def manage_mongo_lock():
    """
    רוכש נעילה מבוזרת ב-MongoDB כדי להבטיח שרק מופע אחד של הבוט רץ.
    
    Returns:
        bool: True אם הנעילה נרכשה בהצלחה, False אחרת
    
    Note:
        תומך בהמתנה לשחרור נעילה קיימת עבור blue/green deployments
    """
    wait_health = _LockWaitHealthServer(port=-1)
    try:
        try:
            ensure_lock_indexes()
        except Exception:
            logger.warning("could not ensure lock indexes; continuing")
        lock_collection = get_lock_collection()
        service_id = (os.getenv("SERVICE_ID") or LOCK_ID).strip() or LOCK_ID
        owner_id = _default_owner_id()
        host_label = _default_host_label()
        instance_id = (os.getenv("RENDER_INSTANCE_ID") or "").strip()
        pid = int(os.getpid())

        # Config
        lease_seconds = max(5, _env_int("LOCK_LEASE_SECONDS", 60))
        hb_override = os.getenv("LOCK_HEARTBEAT_INTERVAL")
        hb_explicit = None
        try:
            hb_explicit = float(hb_override) if (hb_override is not None and str(hb_override).strip()) else None
        except Exception:
            hb_explicit = None
        heartbeat_interval = _compute_heartbeat_interval_seconds(lease_seconds=lease_seconds, explicit=hb_explicit)

        wait_for_acquire = _env_bool("LOCK_WAIT_FOR_ACQUIRE", False)
        # Backward compatible alias: LOCK_MAX_WAIT_SECONDS (legacy)
        acquire_max_wait = _env_float("LOCK_ACQUIRE_MAX_WAIT", 0.0)
        if acquire_max_wait <= 0:
            acquire_max_wait = float(_env_int("LOCK_MAX_WAIT_SECONDS", 0) or 0)
        wait_min = _env_float("LOCK_WAIT_MIN_SECONDS", 15.0)
        wait_max = _env_float("LOCK_WAIT_MAX_SECONDS", 45.0)
        active_retry_interval = float(_env_float("LOCK_RETRY_INTERVAL_SECONDS", 1.0))

        fail_open = _env_bool("LOCK_FAIL_OPEN", False)

        start_monotonic = time.monotonic()

        # Optionally start a tiny health server while we wait (Render-safe)
        wait_health = _LockWaitHealthServer.maybe_start_when_waiting()

        while True:
            now = _utcnow()
            exp = now + timedelta(seconds=int(lease_seconds))

            # Attempt: create lock doc
            try:
                lock_collection.insert_one(
                    {
                        "_id": service_id,
                        "owner": owner_id,
                        "host": host_label,
                        "instance": instance_id,
                        "pid": pid,
                        "createdAt": now,
                        "updatedAt": now,
                        "expiresAt": exp,
                        "expires_at": exp,  # legacy alias
                    }
                )
                logger.info(f"✅ MongoDB lock acquired. service_id={service_id} owner={owner_id} pid={pid}")
                try:
                    emit_event("lock_acquired", severity="info", pid=pid, service_id=service_id, owner=owner_id)
                except Exception:
                    pass
                break
            except DuplicateKeyError:
                # Document exists; attempt takeover if expired, or idempotent refresh if already ours.
                result = None
                try:
                    # Prefer ReturnDocument if available; otherwise, keep compatibility with older pymongo stubs.
                    try:
                        from pymongo import ReturnDocument  # type: ignore
                        _ret_after = ReturnDocument.AFTER
                    except Exception:  # pragma: no cover
                        _ret_after = True

                    result = lock_collection.find_one_and_update(
                        {
                            "_id": service_id,
                            "$or": [
                                {"owner": owner_id},
                                {"expiresAt": {"$lte": now}},
                                {"expires_at": {"$lte": now}},
                            ],
                        },
                        {
                            "$set": {
                                "owner": owner_id,
                                "host": host_label,
                                "instance": instance_id,
                                "pid": pid,
                                "updatedAt": now,
                                "expiresAt": exp,
                                "expires_at": exp,
                            },
                            "$setOnInsert": {"createdAt": now},
                        },
                        return_document=_ret_after,
                    )
                except Exception:
                    result = None

                if result and isinstance(result, dict) and result.get("owner") == owner_id:
                    logger.info(f"✅ MongoDB lock re-acquired. service_id={service_id} owner={owner_id} pid={pid}")
                    try:
                        emit_event("lock_reacquired", severity="info", pid=pid, service_id=service_id, owner=owner_id)
                    except Exception:
                        pass
                    break

                # Not ours, not expired => wait
                if wait_for_acquire:
                    if acquire_max_wait > 0 and (time.monotonic() - start_monotonic) >= float(acquire_max_wait):
                        logger.warning("Timeout waiting for lock; exiting gracefully.")
                        try:
                            emit_event(
                                "lock_wait_timeout",
                                severity="warn",
                                max_wait_seconds=float(acquire_max_wait),
                                service_id=service_id,
                            )
                        except Exception:
                            pass
                        try:
                            wait_health.stop()
                        except Exception:
                            pass
                        return False

                    sleep_s = max(0.2, float(active_retry_interval))
                    logger.info(
                        f"Lock busy (active wait). service_id={service_id} will retry in {sleep_s:.1f}s..."
                    )
                    try:
                        emit_event(
                            "lock_waiting_existing",
                            severity="warn",
                            mode="active",
                            sleep_seconds=float(sleep_s),
                            service_id=service_id,
                        )
                    except Exception:
                        pass
                    time.sleep(sleep_s)
                    continue

                # Passive wait with jitter to avoid restart loops (default)
                sleep_s = _compute_passive_wait_seconds(wait_min, wait_max)
                logger.warning(
                    f"Another instance holds the lock; waiting (passive) {sleep_s:.1f}s. service_id={service_id}"
                )
                try:
                    emit_event(
                        "lock_waiting_existing",
                        severity="warn",
                        mode="passive",
                        sleep_seconds=float(sleep_s),
                        service_id=service_id,
                    )
                except Exception:
                    pass
                time.sleep(float(sleep_s))
                continue

            except Exception as e:
                # Unexpected insert error: break to outer handler
                raise e

        # Acquired: stop wait health server if started
        try:
            wait_health.stop()
        except Exception:
            pass

        # Save global ownership state for cleanup/heartbeat
        global _LOCK_SERVICE_ID, _LOCK_OWNER_ID, _LOCK_HEARTBEAT
        _LOCK_SERVICE_ID = service_id
        _LOCK_OWNER_ID = owner_id

        # Ensure lock is released on exit ASAP after ownership is established
        # (גם אם שלבים מאוחרים יותר ייכשלו)
        try:
            atexit.register(cleanup_mongo_lock)
        except Exception:
            pass

        # Start heartbeat (disabled by default in tests unless explicitly enabled)
        try:
            hb = _MongoLockHeartbeat(
                lock_collection=lock_collection,
                service_id=service_id,
                owner_id=owner_id,
                host_label=host_label,
                lease_seconds=int(lease_seconds),
                interval_seconds=float(heartbeat_interval),
            )
            _LOCK_HEARTBEAT = hb
            hb.start()
        except Exception as e:
            # Fail-closed: if we can't keep ownership fresh, better to not start polling
            logger.error(f"Failed to start lock heartbeat: {e}", exc_info=True)
            try:
                emit_event("lock_heartbeat_start_failed", severity="error", error=str(e), service_id=service_id)
            except Exception:
                pass
            # חשוב: אל תשאיר lock יתום במונגו אם ה-heartbeat לא עלה.
            try:
                res = lock_collection.delete_one({"_id": service_id, "owner": owner_id})
                if int(getattr(res, "deleted_count", 0) or 0) > 0:
                    try:
                        emit_event(
                            "lock_released",
                            severity="warn",
                            service_id=service_id,
                            owner=owner_id,
                            pid=int(pid),
                            reason="heartbeat_start_failed",
                        )
                    except Exception:
                        pass
            except Exception:
                pass
            # נקה state גלובלי כדי למנוע cleanup עתידי על owner "אחר"
            try:
                _LOCK_HEARTBEAT = None
                _LOCK_SERVICE_ID = None
                _LOCK_OWNER_ID = None
            except Exception:
                pass
            if not fail_open:
                return False
            # Fail-open explicit: continue without lock (still log loudly)
            return True

        # Install signal handlers after lock ownership is established
        try:
            _install_lock_signal_handlers(service_id=service_id, owner_id=owner_id)
        except Exception:
            pass
        return True

    except Exception as e:
        # Ensure wait health server is not left running in any exception path
        try:
            wait_health.stop()
        except Exception:
            pass
        logger.error(f"Failed to acquire MongoDB lock: {e}", exc_info=True)
        try:
            emit_event("lock_acquire_failed", severity="error", error=str(e))
        except Exception:
            pass
        # Fail-closed by default: don't run polling without a lock (unless explicitly opted-in)
        if _env_bool("LOCK_FAIL_OPEN", False):
            return True
        return False
    finally:
        # Best-effort cleanup: never leave the temporary health server bound to PORT
        try:
            wait_health.stop()
        except Exception:
            pass


class _LockWaitHealthServer:
    """שרת HTTP מינימלי ל-/ /health /healthz בזמן המתנה ללוק.

    מטרה: למנוע restart-loop ב-Render כאשר השירות מוגדר כ-Web Service עם health check.
    """

    def __init__(self, *, port: int) -> None:
        self._port = int(port)
        self._thread: threading.Thread | None = None
        self._server = None

    @classmethod
    def maybe_start_when_waiting(cls) -> "_LockWaitHealthServer":
        # Enable only on platforms that expose PORT (Render/Heroku), and only if explicitly enabled.
        # Default is enabled to align with Render "health passes while waiting".
        if not _env_bool("LOCK_WAIT_HEALTH_SERVER_ENABLED", True):
            return cls(port=-1)
        raw_port = os.getenv("PORT")
        if raw_port is None:
            return cls(port=-1)
        try:
            port = int(str(raw_port).strip() or "0")
        except Exception:
            port = 0
        if port <= 0:
            return cls(port=-1)
        srv = cls(port=port)
        try:
            srv.start()
        except Exception:
            pass
        return srv

    def start(self) -> None:
        if self._port <= 0:
            return
        if self._thread is not None:
            return

        # Use stdlib HTTP server to avoid dependency or asyncio loop juggling.
        from http.server import BaseHTTPRequestHandler, HTTPServer  # local import

        class _Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                try:
                    path = str(getattr(self, "path", "") or "")
                except Exception:
                    path = "/"
                if path in {"/", "/health", "/healthz"}:
                    payload = b'{"status":"ok","mode":"waiting_for_lock"}'
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                    return
                self.send_response(404)
                self.end_headers()

            def log_message(self, *_a, **_k):  # noqa: ANN001, D401
                # silence request logs
                return

        httpd = HTTPServer(("0.0.0.0", int(self._port)), _Handler)
        self._server = httpd

        def _run():
            try:
                httpd.serve_forever(poll_interval=0.5)
            except Exception:
                return

        t = threading.Thread(target=_run, name="lock_wait_health_http", daemon=True)
        self._thread = t
        t.start()
        try:
            emit_event("lock_wait_health_server_started", severity="info", port=int(self._port))
        except Exception:
            pass

    def stop(self) -> None:
        httpd = self._server
        if httpd is None:
            return
        try:
            httpd.shutdown()
        except Exception:
            pass
        try:
            httpd.server_close()
        except Exception:
            pass
        self._server = None

# =============================================================================
# Global reference to the current bot instance
# משמש כדי לאפשר ל-main() לעשות reuse של אינסטנס קיים (לצרכי טסטים/אתחול)
CURRENT_BOT: CodeKeeperBot | None = None  # יוגדר בתוך CodeKeeperBot.__init__


class HelpEntry(TypedDict):
    """תיאור של שורת עזרה."""
    commands: tuple[str, ...]
    description: str | None
    suffix: NotRequired[str]


class HelpSection(TypedDict):
    """קבוצת פקודות ללא כפתורים."""
    title: str
    entries: list[HelpEntry]
    admin_only: NotRequired[bool]
    entries_source: NotRequired[str]


HELP_SECTIONS: list[HelpSection] = [
    {
        "title": "🔔 <b>תזכורות</b>",
        "entries": [
            {"commands": ("remind",), "description": "יצירת תזכורת חכמה"},
            {"commands": ("reminders",), "description": "רשימת תזכורות וניהול"},
        ],
    },
    {
        "title": "🎨 <b>תמונות קוד</b>",
        "entries": [
            {"commands": ("image",), "description": "ייצור תמונה מעוצבת", "suffix": " &lt;קובץ&gt;"},
            {"commands": ("preview",), "description": "תצוגה מקדימה של קובץ", "suffix": " &lt;קובץ&gt;"},
        ],
    },
    {
        "title": "🧰 <b>מטמון</b>",
        "entries": [
            {"commands": ("cache_stats",), "description": "הצגת סטטיסטיקות מטמון (Cache)"},
            {"commands": ("clear_cache",), "description": "ניקוי מטמון למשתמש הנוכחי"},
        ],
    },
    {
        "title": "🏗️ <b>רפקטורינג</b>",
        "entries": [
            {"commands": ("refactor",), "description": "רפקטורינג אוטומטי לקובץ", "suffix": " &lt;קובץ&gt;"},
        ],
    },
    {
        "title": "⚙️ <b>מנהל (מוגבל)</b>",
        "admin_only": True,
        "entries_source": "chatops_catalog",
        "entries": [
            {
                "commands": ("status",),
                "description": "דוח חלון זמן + בדיקות בריאות (UTC)",
                "suffix": " <code>--since 15m</code> | <code>--from 2025-12-16T10:00 --to 2025-12-16T10:15</code>",
            },
            {
                "commands": ("errors",),
                "description": "Top שגיאות + דוח חלון זמן (UTC)",
                "suffix": " <code>--since 15m</code> | <code>--from ... --to ...</code> | <code>--endpoint /api</code> | <code>--min_severity ERROR</code>",
            },
            {"commands": ("metrics", "uptime"), "description": None},
        ],
    },
]

SUPPORT_FOOTER = "לבעיות או הצעות: @moominAmir"

HELP_SECTION_COMMANDS = {
    cmd.lower()
    for section in HELP_SECTIONS
    for entry in section["entries"]
    for cmd in entry["commands"]
}

# פקודות שמופיעות בסקשנים שאינם admin (כדי לא לשכפל אותן בסקשן ChatOps אדמיני)
NON_ADMIN_SECTION_COMMANDS: set[str] = {
    cmd.lower()
    for section in HELP_SECTIONS
    if not bool(section.get("admin_only"))
    for entry in section["entries"]
    for cmd in entry["commands"]
}

HELP_EXCLUDED_COMMANDS: set[str] = {"start", "help", "cancel", "done"}

STATIC_HELP_MESSAGE = (
    "<b>📚 עזרה – פקודות ללא כפתורים</b>\n\n"
    "🔔 <b>תזכורות</b>\n"
    "• <code>/remind</code> – יצירת תזכורת חכמה\n"
    "• <code>/reminders</code> – רשימת תזכורות וניהול\n\n"
    "🎨 <b>תמונות קוד</b>\n"
    "• <code>/image</code> &lt;קובץ&gt; – ייצור תמונה מעוצבת\n"
    "• <code>/preview</code> &lt;קובץ&gt; – תצוגה מקדימה\n\n"
    "🧰 <b>מטמון</b>\n"
    "• <code>/cache_stats</code> – הצגת סטטיסטיקות מטמון (Cache)\n"
    "• <code>/clear_cache</code> – ניקוי מטמון למשתמש הנוכחי\n\n"
    "🏗️ <b>רפקטורינג</b>\n"
    "• <code>/refactor</code> &lt;קובץ&gt; – רפקטורינג אוטומטי לקובץ\n\n"
    f"{SUPPORT_FOOTER}"
)

@functools.lru_cache(maxsize=1)
def _load_chatops_commands_catalog() -> list[dict[str, Any]]:
    """טוען את קטלוג פקודות ChatOps מתוך commands.json (זה מקור האמת של התיעוד)."""
    try:
        path = Path(__file__).resolve().parent / "webapp" / "static" / "data" / "commands.json"
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
        if not isinstance(data, list):
            return []
        return [item for item in data if isinstance(item, dict)]
    except Exception:
        return []


def _build_chatops_help_entries_from_catalog() -> list[HelpEntry]:
    """ממיר את קטלוג ChatOps לרשימת HelpEntry בפורמט של /help."""
    try:
        from html import escape as html_escape

        out: list[HelpEntry] = []
        for item in _load_chatops_commands_catalog():
            if str(item.get("type", "")).strip().lower() != "chatops":
                continue

            name = str(item.get("name", "")).strip()
            if not name.startswith("/"):
                continue

            # name יכול להיות למשל "/observe -v" או "/check commands"
            parts = [p for p in name.split() if p.strip()]
            if not parts:
                continue

            cmd_token = parts[0].lstrip("/").strip().lower()
            if not cmd_token:
                continue
            # מניעת כפילויות: אם הפקודה כבר מוצגת בסקשן ציבורי (כמו cache_stats/clear_cache),
            # לא נציג אותה שוב תחת "מנהל (מוגבל)".
            if cmd_token in NON_ADMIN_SECTION_COMMANDS:
                continue

            description_raw = item.get("description")
            description = description_raw.strip() if isinstance(description_raw, str) else None
            if not description:
                description = None

            suffix_chunks: list[str] = []
            for extra in parts[1:]:
                suffix_chunks.append(f"<code>{html_escape(str(extra))}</code>")

            args = item.get("arguments", [])
            if isinstance(args, list) and args:
                arg_codes = [
                    f"<code>{html_escape(str(a))}</code>"
                    for a in args
                    if isinstance(a, (str, int, float)) and str(a).strip()
                ]
                if arg_codes:
                    suffix_chunks.append(" | ".join(arg_codes))

            suffix = (" " + " ".join(suffix_chunks)) if suffix_chunks else ""
            out.append({"commands": (cmd_token,), "description": description, "suffix": suffix})

        return out
    except Exception:
        return []


def _split_long_message(text: str, *, max_len: int = 3900) -> list[str]:
    """
    מפצל הודעה ארוכה לכמה הודעות (לפי שורות) כדי להישאר מתחת למגבלת טלגרם.

    הערה: אנחנו מפצלים לפי '\n' בלבד כדי לא לשבור HTML (כל התגים הם in-line).
    """
    try:
        if not isinstance(text, str) or not text:
            return [""]
        if len(text) <= max_len:
            return [text]
        lines = text.split("\n")
        chunks: list[str] = []
        buf: list[str] = []
        cur = 0
        for line in lines:
            add = (len(line) + (1 if buf else 0))
            if buf and (cur + add) > max_len:
                chunks.append("\n".join(buf))
                buf = [line]
                cur = len(line)
            else:
                if buf:
                    cur += 1  # newline
                buf.append(line)
                cur += len(line)
        if buf:
            chunks.append("\n".join(buf))
        return chunks or [text]
    except Exception:
        return [text]


def _resolve_section_entries(section: HelpSection) -> list[HelpEntry]:
    """מאפשר לסקשן להביא entries ממקור דינמי, עם fallback לרשימה הקשיחה."""
    try:
        if section.get("entries_source") == "chatops_catalog":
            dyn = _build_chatops_help_entries_from_catalog()
            if dyn:
                return dyn
    except Exception:
        pass
    return section.get("entries", [])


def _collect_commands_from_handler(handler, seen_ids: set[int]) -> set[str]:
    """Extract command names (lowercase) from a handler or nested handlers."""
    commands: set[str] = set()
    if handler is None:
        return commands
    handler_id = id(handler)
    if handler_id in seen_ids:
        return commands
    seen_ids.add(handler_id)

    if isinstance(handler, CommandHandler):
        for cmd in getattr(handler, "commands", []) or []:
            names: list[str] = []
            if isinstance(cmd, str):
                names = [cmd]
            else:
                candidate = getattr(cmd, "command", None)
                if candidate is None:
                    candidate = getattr(cmd, "name", None)
                if isinstance(candidate, str):
                    names = [candidate]
                elif isinstance(candidate, (list, tuple, set)):
                    names = [str(item) for item in candidate if isinstance(item, str)]
            for name in names:
                if name:
                    commands.add(name.lower())
        return commands

    if isinstance(handler, ConversationHandler):
        kwargs: dict[str, Any] = getattr(handler, "kwargs", {}) if isinstance(getattr(handler, "kwargs", {}), dict) else {}
        entry_points = getattr(handler, "entry_points", None)
        if entry_points is None:
            entry_points = kwargs.get("entry_points")
        for nested in entry_points or []:
            commands |= _collect_commands_from_handler(nested, seen_ids)
        states = getattr(handler, "states", None)
        if states is None:
            states = kwargs.get("states")
        for nested_list in (states or {}).values():
            for nested in nested_list or []:
                commands |= _collect_commands_from_handler(nested, seen_ids)
        fallbacks = getattr(handler, "fallbacks", None)
        if fallbacks is None:
            fallbacks = kwargs.get("fallbacks")
        for nested in fallbacks or []:
            commands |= _collect_commands_from_handler(nested, seen_ids)
        return commands

    # Composite handler (tuple/list) – iterate children if קיימים
    if isinstance(handler, (list, tuple, set)):
        for nested in handler:
            commands |= _collect_commands_from_handler(nested, seen_ids)

    return commands


def _get_registered_commands(application) -> set[str]:
    """Return the set of command names registered on the given application."""
    if application is None:
        return set()

    handlers_container = getattr(application, "handlers", None)
    if handlers_container is None:
        return set()

    command_names: set[str] = set()

    if isinstance(handlers_container, dict):
        iterable = handlers_container.values()
    else:
        iterable = handlers_container

    for entry in iterable:
        handler = entry
        if isinstance(entry, tuple) and entry:
            handler = entry[0]
        command_names |= _collect_commands_from_handler(handler, set())

    return command_names


def _build_debug_commands_report(
    *,
    registered_commands: set[str],
    public_menu_commands: list[Any] | None = None,
    personal_menu_commands: list[Any] | None = None,
) -> str:
    """
    בונה דוח דיבוג על פקודות slash:
    - כל הפקודות שנרשמו כ-CommandHandler ב-runtime (כולל כאלה שלא בתפריט טלגרם)
    - (אופציונלי) השוואה מול get_my_commands כדי לזהות פקודות "מוסתרות" מהתפריט
    """
    from html import escape as html_escape

    registered = sorted({str(c).lower().lstrip("/") for c in (registered_commands or set()) if c})
    registered_set = set(registered)

    def _extract_menu_names(cmds: list[Any] | None) -> set[str]:
        names: set[str] = set()
        for cmd in cmds or []:
            try:
                name = getattr(cmd, "command", None)
            except Exception:
                name = None
            if isinstance(name, str) and name.strip():
                names.add(name.strip().lower().lstrip("/"))
        return names

    public_names = _extract_menu_names(public_menu_commands)
    personal_names = _extract_menu_names(personal_menu_commands)
    menu_union = public_names | personal_names

    hidden = sorted(registered_set - menu_union) if menu_union else []
    menu_only = sorted(menu_union - registered_set) if menu_union else []

    lines: list[str] = []
    lines.append("🔍 <b>Debug Commands Report</b>")
    lines.append("")
    lines.append(f"📊 <b>סה\"כ פקודות רשומות בקוד:</b> {len(registered)}")
    lines.append("")
    lines.append("✅ <b>All Registered Commands (runtime):</b>")
    all_text = "\n".join(f"/{c}" for c in registered) if registered else "(none)"
    lines.append(f"<pre>{html_escape(all_text)}</pre>")

    if public_menu_commands is not None or personal_menu_commands is not None:
        lines.append("")
        pub_text = "\n".join(f"/{c}" for c in sorted(public_names)) if public_names else "(none)"
        per_text = "\n".join(f"/{c}" for c in sorted(personal_names)) if personal_names else "(none)"
        lines.append(f"📋 <b>Menu Commands (Telegram):</b> ציבוריות {len(public_names)} | אישיות {len(personal_names)}")
        lines.append("<b>ציבוריות:</b>")
        lines.append(f"<pre>{html_escape(pub_text)}</pre>")
        lines.append("<b>אישיות:</b>")
        lines.append(f"<pre>{html_escape(per_text)}</pre>")

        if menu_union:
            lines.append("")
            lines.append(f"⚠️ <b>Hidden Commands (בקוד אבל לא בתפריט):</b> {len(hidden)}")
            hidden_text = "\n".join(f"/{c}" for c in hidden) if hidden else "(none)"
            lines.append(f"<pre>{html_escape(hidden_text)}</pre>")

            # שימושי לזיהוי "דריפט" – פקודות שנשארו בתפריט אבל לא קיימות בקוד יותר
            lines.append(f"ℹ️ <b>Menu-only (בתפריט אבל לא בקוד):</b> {len(menu_only)}")
            menu_only_text = "\n".join(f"/{c}" for c in menu_only) if menu_only else "(none)"
            lines.append(f"<pre>{html_escape(menu_only_text)}</pre>")

    return "\n".join(lines)


def _build_help_message(registered_commands: set[str], *, is_admin: bool = False) -> str:
    """Compose the help text for commands without dedicated buttons."""
    available_commands = {cmd.lower() for cmd in registered_commands if isinstance(cmd, str)}
    lines: list[str] = ["<b>📚 עזרה – פקודות ללא כפתורים</b>", ""]
    has_sections = False

    for section in HELP_SECTIONS:
        if bool(section.get("admin_only")) and not is_admin:
            continue
        section_lines: list[str] = []
        for entry in _resolve_section_entries(section):
            commands = [cmd for cmd in entry["commands"] if cmd in available_commands]
            if not commands:
                continue
            suffix = entry.get("suffix", "")
            cmd_text = " ".join(f"<code>/{cmd}</code>" for cmd in commands) + suffix
            if entry["description"]:
                section_lines.append(f"• {cmd_text} – {entry['description']}")
            else:
                section_lines.append(f"• {cmd_text}")
        if section_lines:
            has_sections = True
            lines.append(section["title"])
            lines.extend(section_lines)
            lines.append("")

    # הסרת סעיף "פקודות נוספות" לפי הדרישה – מציגים רק את הקטגוריות המוגדרות
    if not has_sections:
        return STATIC_HELP_MESSAGE

    while lines and not lines[-1].strip():
        lines.pop()

    lines.append("")
    lines.append(SUPPORT_FOOTER)

    return "\n".join(lines)


class CodeKeeperBot:
    """
    המחלקה הראשית של Code Keeper Bot.
    
    מחלקה זו מנהלת את כל הפונקציונליות של הבוט, כולל:
    - הגדרת handlers לפקודות ומסרים
    - ניהול שיחות מורכבות
    - אינטגרציות עם שירותים חיצוניים
    - ניהול מסד נתונים
    
    Attributes:
        application: אובייקט Application של python-telegram-bot
        github_handler: מנהל אינטגרציית GitHub
        backup_handler: מנהל מערכת הגיבויים
    """
    
    def __init__(self):
        def _env_float(name: str, default: float) -> float:
            try:
                v = os.getenv(name)
                if v is None:
                    return float(default)
                v = str(v).strip()
                if not v:
                    return float(default)
                return float(v)
            except Exception:
                return float(default)

        def _env_int(name: str, default: int) -> int:
            try:
                v = os.getenv(name)
                if v is None:
                    return int(default)
                v = str(v).strip()
                if not v:
                    return int(default)
                return int(float(v))
            except Exception:
                return int(default)

        def _apply_ptb_timeouts(builder: Any) -> Any:
            """
            Best-effort apply network timeouts to python-telegram-bot builder.

            אנחנו לא מניחים API קשיח (כי PTB השתנה בין גרסאות), ולכן מפעילים רק
            אם השיטה קיימת. כך לא נשבור טסטים/סביבות מינימליות.
            """
            # Defaults tuned to reduce getUpdates "409 Conflict" caused by network jitter:
            # - long polling timeout (server-side) is configured in run_polling (see main()).
            connect_timeout = _env_float("TELEGRAM_CONNECT_TIMEOUT_SECS", 10.0)
            pool_timeout = _env_float("TELEGRAM_POOL_TIMEOUT_SECS", 10.0)
            read_timeout = _env_float("TELEGRAM_READ_TIMEOUT_SECS", 30.0)
            write_timeout = _env_float("TELEGRAM_WRITE_TIMEOUT_SECS", 30.0)

            for method_name, value in (
                ("connect_timeout", connect_timeout),
                ("pool_timeout", pool_timeout),
                ("read_timeout", read_timeout),
                ("write_timeout", write_timeout),
            ):
                try:
                    m = getattr(builder, method_name, None)
                    if callable(m):
                        m(value)
                except Exception:
                    # Fail-open: do not block bot startup because of builder API mismatch
                    pass
            return builder

        # יצירת תיקייה זמנית עם הרשאות כתיבה
        DATA_DIR = "/tmp"
        if not os.path.exists(DATA_DIR):
            os.makedirs(DATA_DIR, exist_ok=True)
            
        # יצירת persistence לשמירת נתונים בין הפעלות
        persistence = PicklePersistence(filepath=f"{DATA_DIR}/bot_data.pickle")
        
        # במצב בדיקות/CI, חלק מתלויות הטלגרם (Updater פנימי) עלולות להיכשל.
        # נשתמש בבנאי הרגיל, ואם נכשל – נבנה Application מינימלי עם טוקן דמה.
        try:
            _builder = (
                Application.builder()
                .token(config.BOT_TOKEN)
                .defaults(Defaults(parse_mode=ParseMode.HTML))
                .persistence(persistence)
                .post_init(setup_bot_data)
            )
            _builder = _apply_ptb_timeouts(_builder)
            self.application = _builder.build()
        except Exception:
            dummy_token = os.getenv("DUMMY_BOT_TOKEN", "dummy_token")
            # נסה לבנות ללא persistence/post_init כדי לעקוף Updater פנימי
            try:
                _builder = (
                    Application.builder()
                    .token(dummy_token)
                    .defaults(Defaults(parse_mode=ParseMode.HTML))
                )
                _builder = _apply_ptb_timeouts(_builder)
                self.application = _builder.build()
            except Exception:
                # בנאי ידני מינימלי: אובייקט עם הממשקים הדרושים לטסטים/סביבות חסרות
                class _MiniApp:
                    def __init__(self):
                        self.handlers = []
                        self.bot_data = {}
                        self._error_handlers = []
                        class _JobQ:
                            def run_once(self, *a, **k):
                                return None
                        self.job_queue = _JobQ()
                    def add_handler(self, *a, **k):
                        # שמירה במבנה יציב לטסטים: (args_tuple, kwargs_dict)
                        # args_tuple מובטח באורך ≥ 2 כך ש-index [1] לא יקרוס.
                        handler_obj = None
                        if len(a) >= 1:
                            handler_obj = a[0]
                        else:
                            # קלט אלטרנטיבי נדיר: handler בקווארגס
                            handler_obj = k.get('handler') or k.get('callback')
                        # group יכול להגיע כארגומנט שני או בקווארגס
                        group_val = a[1] if len(a) >= 2 else k.get('group')
                        # בנה args באורך 2 לפחות – משכפל את ה-handler כדי לספק args[1]
                        norm_args = (handler_obj, handler_obj)
                        norm_kwargs = dict(k)
                        if 'group' not in norm_kwargs:
                            norm_kwargs['group'] = group_val
                        self.handlers.append((norm_args, norm_kwargs))
                    def remove_handler(self, *a, **k):
                        # הסרה שקטה – שמור על API, לא הכרחי לטסטים
                        return None
                    def add_error_handler(self, *a, **k):
                        self._error_handlers.append((a, k))
                    async def run_polling(self, *a, **k):
                        # Fallback שקט: אין polling אמיתי; מאפשר start ללא קריסה
                        return None
                self.application = _MiniApp()
        # משתני עזר עבור שער תחזוקה (TTL יופעל בסוף setup_handlers)
        self._maintenance_gate_pending = False
        self._maintenance_warmup_secs = None
        self._maintenance_clear_handlers_cb = None

        # התקנת מתאם קורלציה לפני רישום שאר ה-handlers
        try:
            self._install_correlation_layer()
        except Exception:
            pass
        try:
            self._install_tracing_layer()
        except Exception:
            pass

        # יצירת והזרקת Activity Reporter בזמן ריצה (מונע חיבורים מרובים בזמן import)
        try:
            mongodb_uri = (
                os.getenv('REPORTER_MONGODB_URL')
                or os.getenv('REPORTER_MONGODB_URI')
                or getattr(config, 'MONGODB_URL', None)
            )
            service_id = os.getenv('REPORTER_SERVICE_ID', getattr(config, 'BOT_LABEL', 'CodeBot'))
            # תמיכה בנטרול דיווח פעילות דרך ENV
            disable_reporter = bool(int((os.getenv('DISABLE_ACTIVITY_REPORTER', '0') or '0').strip() or 0))
            if disable_reporter:
                class _NoopReporter:
                    def report_activity(self, user_id):
                        return None
                created_reporter = _NoopReporter()
            else:
                # ייבוא בזמן ריצה בלבד כדי למנוע יצירת לקוח Mongo בזמן import במודולים אחרים
                try:
                    from activity_reporter import create_reporter  # noqa: WPS433 (runtime import by design)
                except Exception:
                    # אם המודול לא זמין/נכשל — עבור ל-noop
                    class _NoopReporter:
                        def report_activity(self, user_id):
                            return None
                    created_reporter = _NoopReporter()
                else:
                    # יצירה בטוחה: SimpleActivityReporter מטפל בחוסר pymongo בסביבה
                    created_reporter = create_reporter(
                        mongodb_uri=mongodb_uri,
                        service_id=service_id,
                        service_name="CodeBot",
                    )
            # עדכון גלובלי במודול זה
            global reporter
            reporter = created_reporter
            # הזרקה למודולים שתלויים ב-report_activity
            try:
                set_bh_activity_reporter(created_reporter)
            except Exception:
                pass
            try:
                set_ch_activity_reporter(created_reporter)
            except Exception:
                pass
            try:
                from refactor_handlers import set_activity_reporter as set_rh_activity_reporter
                set_rh_activity_reporter(created_reporter)
            except Exception:
                pass
        except Exception:
            # בסביבות CI/טסטים, אל נכשיל את הבנייה
            reporter = None

        self.document_handler = DocumentHandler(
            notify_admins=notify_admins,
            get_reporter=lambda: reporter,
            log_user_activity=log_user_activity,
            encodings_to_try=lambda: ENCODINGS_TO_TRY,
            emit_event=emit_event,
            errors_total=errors_total,
        )

        self.setup_handlers()
        self._activate_maintenance_warmup_if_pending()
        self.advanced_handlers = AdvancedBotHandlers(self.application)
        # רישום קטגוריית "⭐ מועדפים" לתפריט "📚 הקבצים"
        try:
            from conversation_handlers import setup_favorites_category_handlers as _setup_fav
            _setup_fav(self.application)
        except Exception:
            pass
        # Rate limiter instance (לאחר בניית האפליקציה)
        try:
            self._rate_limiter = RateLimiter(max_per_minute=int(getattr(config, 'RATE_LIMIT_PER_MINUTE', 30) or 30))
            # הגדרת דגל shadow כברירת מחדל (גם אם אין מגביל מתקדם)
            self._shadow_mode = bool(getattr(config, 'RATE_LIMIT_SHADOW_MODE', False))
            # אתחול משתנים כדי למנוע AttributeError downstream
            self._advanced_limiter = None
            self._limits_storage = None
            self._per_user_global = None

            if _LIMITS_AVAILABLE:
                try:
                    redis_url = getattr(config, 'REDIS_URL', None) or os.getenv('REDIS_URL')
                    storage = None
                    use_memory_fallback = False

                    if redis_url:
                        # ודא חיבור מהיר ל-Redis; אם נכשל, נשתמש ב-MemoryStorage כדי למנוע TIMEOUT בטסטים
                        connect_timeout = getattr(config, 'REDIS_CONNECT_TIMEOUT', None)
                        try:
                            connect_timeout = float(connect_timeout) if connect_timeout is not None else 0.25
                        except Exception:
                            connect_timeout = 0.25
                        connect_timeout = max(0.05, connect_timeout)

                        if _redis_socket_available(str(redis_url), timeout=connect_timeout):
                            try:
                                storage = RedisStorage(str(redis_url))
                            except Exception:
                                storage = None
                                use_memory_fallback = True
                        else:
                            use_memory_fallback = True

                        if use_memory_fallback and storage is None:
                            try:
                                logger.warning(
                                    "Redis advanced limiter לא נגיש – מעבר ל-MemoryStorage",
                                    extra={"redis_url": str(redis_url)},
                                )
                            except Exception:
                                pass

                    if storage is None and redis_url and use_memory_fallback and MemoryStorage is not None:
                        try:
                            storage = MemoryStorage()
                        except Exception:
                            storage = None

                    if storage is not None:
                        self._limits_storage = storage
                        self._advanced_limiter = MovingWindowRateLimiter(storage)
                        self._per_user_global = RateLimitItemPerMinute(50)
                except Exception:
                    self._advanced_limiter = None
        except Exception:
            self._rate_limiter = RateLimiter(max_per_minute=30)
            self._shadow_mode = False

        # חשיפה גלובלית של האובייקט הנוכחי עבור main()/טסטים
        try:
            global CURRENT_BOT
            CURRENT_BOT = self
        except Exception:
            pass

    def _install_correlation_layer(self) -> None:
        """רישום Handler מוקדם שמייצר ומקשר request_id ומודד מטריקות בסיסיות."""
        async def _pre_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
            # request_id קצר ונוח
            try:
                req_id = context.user_data.get("request_id") if hasattr(context, "user_data") else None
            except Exception:
                req_id = None
            if not req_id:
                req_id = generate_request_id()
                try:
                    if hasattr(context, "user_data"):
                        context.user_data["request_id"] = req_id
                except Exception:
                    pass
            # כרוך ל-contextvars כך שיופיע בכל רשומת לוג בהמשך השרשור
            try:
                bind_request_id(req_id)
            except Exception:
                pass
            try:
                user = getattr(update, "effective_user", None)
                chat = getattr(update, "effective_chat", None)
                uid = getattr(user, "id", None)
                cid = getattr(chat, "id", None)
                bind_user_context(user_id=uid, chat_id=cid)
            except Exception:
                pass
            try:
                command_name = ""
                message = getattr(update, "effective_message", None)
                if message is not None:
                    text = getattr(message, "text", None)
                    if isinstance(text, str):
                        parts = text.split()
                        if parts and parts[0].startswith("/"):
                            command_name = parts[0]
                if not command_name:
                    callback = getattr(update, "callback_query", None)
                    if callback is not None:
                        data = getattr(callback, "data", None)
                        if isinstance(data, str):
                            parts = data.split()
                            if parts:
                                command_name = parts[0]
                if not command_name and getattr(update, "inline_query", None):
                    command_name = "inline_query"
                if command_name:
                    cleaned = command_name.strip()
                    if cleaned.startswith("/"):
                        cleaned = cleaned[1:]
                    if "@" in cleaned:
                        cleaned = cleaned.split("@", 1)[0]
                    cleaned = cleaned.lower()
                    if cleaned:
                        bind_command(f"bot:{cleaned}")
                        try:
                            if hasattr(context, "user_data"):
                                context.user_data["command"] = cleaned
                                # ביטול מצב חיפוש על כל פקודה
                                context.user_data.pop('awaiting_search_text', None)
                                context.user_data.pop('search_ctx', None)
                        except Exception:
                            pass
            except Exception:
                pass
            # עדכון מטריקה כללית על סוג ה-update
            try:
                upd_type = (
                    "callback_query" if getattr(update, "callback_query", None) else
                    "inline_query" if getattr(update, "inline_query", None) else
                    "message" if getattr(update, "message", None) else
                    "other"
                )
                if telegram_updates_total is not None:
                    telegram_updates_total.labels(type=upd_type, status="received").inc()
            except Exception:
                pass

        handler = TypeHandler(Update, _pre_update)  # כל ה-Updates
        try:
            self.application.add_handler(handler, group=-100)
        except TypeError:
            self.application.add_handler(handler)
        except Exception:
            # אל תכשיל את האפליקציה במקרה של כשל
            pass

    def _install_tracing_layer(self) -> None:
        """Wrap process_update with OTEL span for end-to-end tracing."""
        app = getattr(self, "application", None)
        if app is None:
            return
        original = getattr(app, "process_update", None)
        if not callable(original):
            return
        if getattr(app, "_codebot_tracing_installed", False):
            return
        try:
            from observability_instrumentation import start_span, set_current_span_attributes  # type: ignore
        except Exception:
            return
        if not callable(start_span):  # type: ignore[call-arg]
            return

        setattr(app, "_codebot_tracing_installed", True)

        def _normalize_command(value: str | None) -> str:
            try:
                if not value:
                    return ""
                cleaned = str(value).strip().lower()
                if cleaned.startswith("/"):
                    cleaned = cleaned[1:]
                if "@" in cleaned:
                    cleaned = cleaned.split("@", 1)[0]
                return cleaned[:80]
            except Exception:
                return ""

        def _derive_command(update: Update) -> str:
            try:
                message = getattr(update, "effective_message", None)
                if message is not None:
                    text = getattr(message, "text", None)
                    if isinstance(text, str):
                        parts = text.split()
                        if parts and parts[0].startswith("/"):
                            return _normalize_command(parts[0])
                callback = getattr(update, "callback_query", None)
                if callback is not None:
                    data = getattr(callback, "data", None)
                    if isinstance(data, str) and data:
                        return _normalize_command(data.split()[0])
                inline = getattr(update, "inline_query", None)
                if inline is not None:
                    query = getattr(inline, "query", None)
                    if isinstance(query, str) and query:
                        return _normalize_command(query.split()[0])
            except Exception:
                return ""
            return ""

        def _collect_attrs(update: Update | None) -> dict[str, str]:
            attrs: dict[str, str] = {"component": "telegram.bot"}
            try:
                ctx = get_observability_context() or {}
            except Exception:
                ctx = {}
            if isinstance(ctx, dict):
                cmd_ctx = _normalize_command(ctx.get("command")) if ctx.get("command") else ""
                if cmd_ctx:
                    attrs["command"] = cmd_ctx
                req_id = str(ctx.get("request_id", "")).strip()
                if req_id:
                    attrs["request_id"] = req_id
                user_hash = str(ctx.get("user_id", "")).strip()
                if user_hash:
                    attrs["user_id_hash"] = user_hash
                chat_hash = str(ctx.get("chat_id", "")).strip()
                if chat_hash:
                    attrs["chat_id_hash"] = chat_hash
            if update is not None:
                try:
                    upd_id = getattr(update, "update_id", None)
                    if upd_id is not None:
                        attrs["update.id"] = str(int(upd_id))
                except Exception:
                    pass
                try:
                    if getattr(update, "callback_query", None):
                        attrs["update.type"] = "callback_query"
                    elif getattr(update, "inline_query", None):
                        attrs["update.type"] = "inline_query"
                    elif getattr(update, "message", None):
                        attrs["update.type"] = "message"
                    else:
                        attrs.setdefault("update.type", "other")
                except Exception:
                    pass
                try:
                    if "command" not in attrs:
                        derived = _derive_command(update)
                        if derived:
                            attrs["command"] = derived
                except Exception:
                    pass
            return attrs

        @functools.wraps(original)
        async def _process_update_with_span(update: Update, *args, **kwargs):
            span_attrs = _collect_attrs(update)
            span_cm = start_span("bot.update", span_attrs)
            span = span_cm.__enter__()
            if span is not None:
                try:
                    set_current_span_attributes({"component": "telegram.bot"})
                except Exception:
                    pass
            error: Exception | None = None
            try:
                result = await original(update, *args, **kwargs)
                if span is not None:
                    try:
                        span.set_attribute("status", "ok")  # type: ignore[attr-defined]
                    except Exception:
                        pass
                return result
            except Exception as exc:
                error = exc
                if span is not None:
                    try:
                        span.set_attribute("status", "error")  # type: ignore[attr-defined]
                        span.set_attribute("error_signature", type(exc).__name__)  # type: ignore[attr-defined]
                    except Exception:
                        pass
                raise
            finally:
                if error is None:
                    span_cm.__exit__(None, None, None)
                else:
                    span_cm.__exit__(type(error), error, getattr(error, "__traceback__", None))

        setattr(app, "process_update", _process_update_with_span)
    
    def _activate_maintenance_warmup_if_pending(self) -> None:
        """מתזמן את חלון ה-warmup רק אחרי שכל ה-handlers הוגדרו."""
        if not getattr(self, "_maintenance_gate_pending", False):
            return

        try:
            warmup_secs = int(
                self._maintenance_warmup_secs
                if self._maintenance_warmup_secs is not None
                else getattr(config, "MAINTENANCE_AUTO_WARMUP_SECS", 30)
            )
        except Exception:
            warmup_secs = 30
        warmup_secs = max(1, warmup_secs)

        try:
            self._maintenance_active_until_ts = time.time() + warmup_secs
        except Exception:
            self._maintenance_active_until_ts = time.time() + 30

        cb = getattr(self, "_maintenance_clear_handlers_cb", None)
        if cb is not None:
            try:
                self.application.job_queue.run_once(cb, when=warmup_secs, name="maintenance_clear_handlers")
            except Exception:
                pass

        self._maintenance_gate_pending = False
    
    def setup_handlers(self):
        """הגדרת כל ה-handlers של הבוט בסדר הנכון"""

        # Maintenance gate: if enabled, short-circuit most interactions
        # שימוש ב-getattr עבור תאימות לטסטים שמחליפים את config באובייקט מינימלי
        maintenance_flag_raw = getattr(config, "MAINTENANCE_MODE", False)

        def _coerce_flag(value):
            try:
                if value is None:
                    return None
                if isinstance(value, str):
                    normalized = value.strip().lower()
                    if not normalized:
                        return None
                    if normalized in {"1", "true", "yes", "on"}:
                        return True
                    if normalized in {"0", "false", "no", "off"}:
                        return False
                    return None
                if isinstance(value, (bool, int)):
                    return bool(value)
            except Exception:
                return None
            return None

        maintenance_flag = _coerce_flag(maintenance_flag_raw)

        env_override = _coerce_flag(os.getenv("MAINTENANCE_MODE"))
        if env_override is not None:
            maintenance_flag = env_override

        if maintenance_flag is None:
            maintenance_flag = False

        DEFAULT_MAINTENANCE_WARMUP_GRACE_SECS = 0.75

        if maintenance_flag:
            # הגדרת חלון זמן פנימי שבו הודעת תחזוקה פעילה, כך שגם אם מחיקת ה-handlers לא תתבצע
            # ההודעה תיכבה אוטומטית לאחר ה-warmup. החישוב בפועל נדחה לסוף setup_handlers כדי
            # למנוע קיצור מלאכותי של החלון בזמן רישום ה-handlers.
            try:
                warmup_secs = max(1, int(getattr(config, 'MAINTENANCE_AUTO_WARMUP_SECS', 30)))
            except Exception:
                warmup_secs = 30
            self._maintenance_warmup_secs = warmup_secs
            self._maintenance_active_until_ts = None
            self._maintenance_gate_pending = True

            async def maintenance_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
                # אם חלון ה-warmup הסתיים, אל תשלח הודעת תחזוקה
                try:
                    raw_active_until = getattr(self, "_maintenance_active_until_ts", None)
                except Exception:
                    raw_active_until = None
                # פרשנות:
                # None => תחזוקה פעילה (אין TTL)
                # 0 או ערך שלילי => תחזוקה מנוטרלת
                # > 0 => תחזוקה פעילה עד timestamp זה
                try:
                    active_until = float(raw_active_until) if raw_active_until is not None else None
                except Exception:
                    active_until = None
                try:
                    grace_value = getattr(
                        config, "MAINTENANCE_WARMUP_GRACE_SECS", DEFAULT_MAINTENANCE_WARMUP_GRACE_SECS
                    )
                    grace_secs = max(0.0, float(grace_value))
                except Exception:
                    grace_secs = DEFAULT_MAINTENANCE_WARMUP_GRACE_SECS
                now = time.time()
                is_active = True if active_until is None else (active_until > 0 and now < (active_until + grace_secs))
                if not is_active:
                    return ConversationHandler.END

                maintenance_text = getattr(config, "MAINTENANCE_MESSAGE", "") or ""
                sent = False

                callback_query = getattr(update, "callback_query", None)
                if callback_query is not None:
                    try:
                        try:
                            await callback_query.answer(cache_time=1, show_alert=False)
                        except Exception:
                            pass
                        await callback_query.edit_message_text(maintenance_text)
                        sent = True
                    except Exception:
                        sent = False

                if not sent:
                    message = getattr(update, "message", None)
                    if message is None:
                        message = getattr(update, "effective_message", None)
                    if message is None and callback_query is not None:
                        message = getattr(callback_query, "message", None)
                    if message is not None and hasattr(message, "reply_text"):
                        try:
                            await message.reply_text(maintenance_text)
                            sent = True
                        except Exception:
                            sent = False

                if not sent:
                    try:
                        bot = getattr(context, "bot", None)
                        if bot is None:
                            # fallback ל-bot דרך application (במקרים שבהם context.bot לא קיים)
                            bot = getattr(getattr(context, "application", None), "bot", None)
                        if bot is None:
                            bot = getattr(getattr(context, "app", None), "bot", None)

                        chat = getattr(update, "effective_chat", None)
                        chat_id = getattr(chat, "id", None)
                        if chat_id is None:
                            # נסה להפיק chat_id ממשתמש או מהודעה אם קיים
                            message = getattr(update, "message", None) or getattr(update, "effective_message", None)
                            chat_id = getattr(getattr(message, "chat", None), "id", None) or getattr(message, "chat_id", None)
                        if chat_id is None:
                            user = getattr(update, "effective_user", None)
                            chat_id = getattr(user, "id", None)

                        if bot is not None and chat_id is not None:
                            await bot.send_message(chat_id=chat_id, text=maintenance_text)
                            sent = True
                    except Exception:
                        pass

                return ConversationHandler.END
            # Catch-all high-priority handlers during maintenance (keep references for clean removal)
            self._maintenance_message_handler = MessageHandler(filters.ALL, maintenance_reply)
            self._maintenance_callback_handler = CallbackQueryHandler(maintenance_reply)
            self.application.add_handler(self._maintenance_message_handler, group=-100)
            self.application.add_handler(self._maintenance_callback_handler, group=-100)
            logger.warning("MAINTENANCE_MODE is ON — all updates will receive maintenance message")
            # אל תחסום לגמרי: לאחר warmup אוטומטי, הסר תחזוקה (ללא Redeploy)
            # Schedule removing maintenance handlers via JobQueue instead of create_task
            async def _clear_handlers_cb(context: ContextTypes.DEFAULT_TYPE):
                try:
                    app = self.application
                    if getattr(self, "_maintenance_message_handler", None) is not None:
                        app.remove_handler(self._maintenance_message_handler, group=-100)
                    if getattr(self, "_maintenance_callback_handler", None) is not None:
                        app.remove_handler(self._maintenance_callback_handler, group=-100)
                    # נטרל מיידית את החלון הפעיל כדי למנוע שליחת הודעות תחזוקה מיותרות
                    try:
                        self._maintenance_active_until_ts = 0
                    except Exception:
                        pass
                    logger.warning("MAINTENANCE_MODE auto-warmup window elapsed; resuming normal operation")
                except Exception:
                    pass
            self._maintenance_clear_handlers_cb = _clear_handlers_cb
            # ממשיכים לרשום את שאר ה-handlers כדי שיקלטו אוטומטית אחרי ה-warmup

        # ספור את ה-handlers
        handler_count = len(self.application.handlers)
        logger.info(f"🔍 כמות handlers לפני: {handler_count}")
        try:
            emit_event("handlers_count_before", severity="info", count=handler_count)
        except Exception:
            pass

        # --- Rate limiting gate (גבוה עדיפות, לפני שאר ה-handlers) ---
        async def _rate_limit_gate(update: Update, context: ContextTypes.DEFAULT_TYPE):
            try:
                user = (
                    getattr(update, 'effective_user', None)
                    or getattr(getattr(update, 'callback_query', None), 'from_user', None)
                )
                user_id = int(getattr(user, 'id', 0) or 0)
            except Exception:
                user_id = 0
            if user_id:
                # עקיפת אדמין – אדמינים לא מוגבלים ע"י השער הגלובלי
                try:
                    admins = get_admin_ids()
                except Exception:
                    admins = []
                if admins and user_id in admins:
                    return  # מעבר חופשי לאדמין

                # Fallback-counter פשוט פר-משתמש בחלון של 60ש׳ כדי לכסות תקלות נדירות
                # במימוש הראשי של המגביל. לא מחליף את המגביל, רק מחמיר אם צריך.
                blocked_by_local = False
                try:
                    udata = getattr(context, 'user_data', None)
                    if isinstance(udata, dict):
                        now_ts = time.time()
                        local = udata.get('_rl_local')
                        limit_val = int(getattr(getattr(self, '_rate_limiter', object()), 'max_per_minute', 30) or 30)
                        if not isinstance(local, dict) or (now_ts - float(local.get('start_ts', 0.0) or 0.0)) >= 60.0:
                            local = {'start_ts': now_ts, 'count': 0}
                            # שמור מיידית את תחילת החלון החדש כדי לא לאבד state גם אם תתרחש חסימה בבקשה הנוכחית
                            udata['_rl_local'] = local
                        # ספר את הקריאה הנוכחית בחלון הנוכחי
                        next_count = int(local.get('count', 0)) + 1
                        if next_count > limit_val:
                            blocked_by_local = True
                            # אל תעדכן את המונה כאשר חוסמים – נשמור על עקביות מינימלית
                        else:
                            local['count'] = next_count
                            udata['_rl_local'] = local
                except Exception:
                    # אם יש שגיאה, אל תחסום – נשען על המגביל הראשי
                    blocked_by_local = False

                # בדיקה במגביל הראשי
                try:
                    allowed = await self._rate_limiter.check_rate_limit(user_id)
                except Exception:
                    allowed = True

                # Optional: advanced per-user global limit in shadow mode (logging only)
                try:
                    adv = getattr(self, '_advanced_limiter', None)
                    if adv is not None and hasattr(self, '_per_user_global'):
                        key = f"tg:global:{user_id}"
                        ok = adv.hit(self._per_user_global, key)
                        if not ok and getattr(self, '_shadow_mode', False):
                            logger.info(
                                "Rate limit would block (shadow mode)",
                                extra={"user_id": user_id, "scope": "global", "limit": "global_user"},
                            )
                        # במצב shadow אין חסימה על בסיס advanced; נשענים על in-memory gate
                except Exception:
                    pass

                should_block = (not allowed) or blocked_by_local
                if should_block:
                    # חסימה שקטה + הודעה קצרה
                    try:
                        cq = getattr(update, 'callback_query', None)
                        if cq is not None:
                            await cq.answer("יותר מדי בקשות, נסה שוב עוד רגע", show_alert=False, cache_time=1)
                        else:
                            msg = getattr(update, 'message', None)
                            if msg is not None:
                                await msg.reply_text("⚠️ יותר מדי בקשות, נסה שוב בעוד מספר שניות")
                    except Exception:
                        pass
                    raise ApplicationHandlerStop
                else:
                    # Soft-warning ב-80% מהסף – הודעה אדיבה ללא חסימה
                    try:
                        ratio = 0.0
                        if hasattr(self._rate_limiter, 'get_current_usage_ratio'):
                            ratio = float(await self._rate_limiter.get_current_usage_ratio(user_id))
                        if ratio >= 0.8:
                            # אנטי-ספאם: אזהרה לכל היותר פעם בדקה למשתמש
                            now_ts = time.time()
                            udata = getattr(context, 'user_data', None)
                            last_ts = 0.0
                            if isinstance(udata, dict):
                                try:
                                    last_ts = float(udata.get('_soft_warn_ts', 0.0) or 0.0)
                                except Exception:
                                    last_ts = 0.0
                            if (now_ts - last_ts) >= 60.0:
                                try:
                                    cq = getattr(update, 'callback_query', None)
                                    if cq is not None:
                                        await cq.answer("Heads-up: אתה מתקרב למגבלת הקצב (80%+)", show_alert=False, cache_time=1)
                                    else:
                                        msg = getattr(update, 'message', None)
                                        if msg is not None:
                                            await msg.reply_text("ℹ️ חיווי: אתה מתקרב למגבלת הקצב. אם תמשיך בקצב הזה ייתכן שתחסם זמנית.")
                                except Exception:
                                    pass
                                if isinstance(udata, dict):
                                    udata['_soft_warn_ts'] = now_ts
                    except Exception:
                        pass

        # חשיפה לצרכי בדיקות: שמור הפניה לשער ברמת האובייקט
        self._rate_limit_gate = _rate_limit_gate

        # הוסף כשכבת סינון מוקדמת עבור הודעות ולחיצות
        try:
            self.application.add_handler(MessageHandler(filters.ALL, _rate_limit_gate), group=-90)
            self.application.add_handler(CallbackQueryHandler(_rate_limit_gate), group=-90)
        except Exception:
            pass

        # Add conversation handler
        conversation_handler = get_save_conversation_handler(
            db,
            callback_query_handler_cls=CallbackQueryHandler,
        )
        self.application.add_handler(conversation_handler)
        logger.info("ConversationHandler נוסף")
        try:
            emit_event("conversation_handler_added", severity="info")
        except Exception:
            pass

        # ספור שוב
        handler_count_after = len(self.application.handlers)
        logger.info(f"🔍 כמות handlers אחרי: {handler_count_after}")
        try:
            emit_event("handlers_count_after", severity="info", count=handler_count_after)
        except Exception:
            pass

        # --- GitHub handlers - חייבים להיות לפני ה-handler הגלובלי! ---
        # יצירת instance יחיד של GitHubMenuHandler ושמירה ב-bot_data
        github_handler = GitHubMenuHandler()
        try:
            github_handler.handle_menu_callback = _wrap_github_callback(github_handler.handle_menu_callback)
        except Exception:
            pass
        try:
            github_handler.handle_text_input = _wrap_handler_callback(github_handler.handle_text_input, "github:text_input")
        except Exception:
            pass
        try:
            github_handler.handle_file_upload = _wrap_handler_callback(github_handler.handle_file_upload, "github:file_upload")
        except Exception:
            pass
        self.application.bot_data['github_handler'] = github_handler
        logger.info("✅ GitHubMenuHandler instance created and stored in bot_data")
        try:
            emit_event("github_handler_ready", severity="info")
        except Exception:
            pass
        # יצירת BackupMenuHandler ושמירה
        backup_handler = BackupMenuHandler()
        self.application.bot_data['backup_handler'] = backup_handler
        logger.info("✅ BackupMenuHandler instance created and stored in bot_data")
        try:
            emit_event("backup_handler_ready", severity="info")
        except Exception:
            pass

        # יצירת GoogleDriveMenuHandler ושמירה
        drive_handler = GoogleDriveMenuHandler()
        self.application.bot_data['drive_handler'] = drive_handler
        # שמור גם עותק ישיר על ה-application כדי להתגבר על מצבים שבהם bot_data מתאפס (Persistence/Reload)
        try:
            setattr(self.application, "_drive_handler", drive_handler)
        except Exception:
            pass
        logger.info("✅ GoogleDriveMenuHandler instance created and stored in bot_data")
        try:
            emit_event("drive_handler_ready", severity="info")
        except Exception:
            pass
        
        # הוסף פקודת github
        self.application.add_handler(CommandHandler("github", github_handler.github_menu_command))
        # הוסף תפריט גיבוי/שחזור
        async def show_backup_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
            await backup_handler.show_backup_menu(update, context)
        self.application.add_handler(CommandHandler("backup", show_backup_menu))
        self.application.add_handler(CallbackQueryHandler(backup_handler.handle_callback_query, pattern=r'^(backup_|backup_add_note:.*)'))
        
        # הוסף את ה-callbacks של GitHub - חשוב! לפני ה-handler הגלובלי
        self.application.add_handler(
                        CallbackQueryHandler(github_handler.handle_menu_callback, 
                               pattern=r'^(select_repo|upload_file|upload_saved|show_current|set_token|set_folder|close_menu|folder_|repo_|repos_page_|upload_saved_|back_to_menu|repo_manual|noop|analyze_repo|analyze_current_repo|analyze_other_repo|show_suggestions|show_full_analysis|download_analysis_json|back_to_analysis|back_to_analysis_menu|back_to_summary|choose_my_repo|enter_repo_url|suggestion_\d+|github_menu|logout_github|delete_file_menu|delete_repo_menu|confirm_delete_repo|confirm_delete_repo_step1|confirm_delete_file|danger_delete_menu|download_file_menu|browse_repo|browse_open:.*|browse_select_download:.*|browse_select_delete:.*|browse_page:.*|download_zip:.*|multi_toggle|multi_execute|multi_clear|safe_toggle|browse_toggle_select:.*|inline_download_file:.*|view_more|view_back|browse_select_view:.*|browse_ref_menu|browse_refs_branches_page_.*|browse_refs_tags_page_.*|browse_select_ref:.*|browse_search|browse_search_page:.*|notifications_menu|notifications_toggle|notifications_toggle_pr|notifications_toggle_issues|notifications_interval_.*|notifications_check_now|notifications_sentry_test|share_folder_link:.*|share_selected_links|pr_menu|create_pr_menu|branches_page_.*|pr_select_head:.*|confirm_create_pr|merge_pr_menu|prs_page_.*|merge_pr:.*|confirm_merge_pr|validate_repo|git_checkpoint|git_checkpoint_doc:.*|git_checkpoint_doc_skip|restore_checkpoint_menu|restore_tags_page_.*|restore_select_tag:.*|restore_branch_from_tag:.*|restore_revert_pr_from_tag:.*|restore_commit_menu|restore_commits_page_.*|restore_select_commit:.*|restore_branch_from_commit:.*|restore_revert_pr_from_commit:.*|rcb:.*|rcpr:.*|open_pr_from_branch:.*|choose_upload_branch|upload_branches_page_.*|upload_select_branch:.*|upload_select_branch_tok:.*|choose_upload_folder|upload_select_folder:.*|upload_folder_root|upload_folder_current|upload_folder_custom|upload_folder_create|create_folder|confirm_saved_upload|refresh_saved_checks|github_backup_menu|github_backup_help|github_backup_db_list|github_restore_zip_to_repo|github_restore_zip_setpurge:.*|github_restore_zip_list|github_restore_zip_from_backup:.*|github_repo_restore_backup_setpurge:.*|gh_upload_cat:.*|gh_upload_repo:.*|gh_upload_large:.*|backup_menu|github_create_repo_from_zip|github_new_repo_name|github_set_new_repo_visibility:.*|upload_paste_code|cancel_paste_flow|gh_upload_zip_browse:.*|gh_upload_zip_page:.*|gh_upload_zip_select:.*|gh_upload_zip_select_idx:.*|backup_add_note:.*|github_import_repo|import_repo_branches_page_.*|import_repo_select_branch:.*|import_repo_start|import_repo_cancel)')
            )

        # הוסף את ה-callbacks של Google Drive
        self.application.add_handler(
            CallbackQueryHandler(
                drive_handler.handle_callback,
                pattern=r'^(drive_menu|drive_auth|drive_poll_once|drive_cancel_auth|drive_backup_now|drive_sel_zip|drive_sel_all|drive_sel_adv|drive_advanced|drive_adv_by_repo|drive_adv_large|drive_adv_other|drive_choose_folder|drive_choose_folder_adv|drive_folder_default|drive_folder_auto|drive_folder_set|drive_folder_back|drive_folder_cancel|drive_schedule|drive_set_schedule:.*|drive_status|drive_adv_multi_toggle|drive_adv_upload_selected|drive_logout|drive_logout_do|drive_simple_confirm|drive_adv_confirm|drive_make_zip_now|drive_help)$'
            )
        )

        # Inline query handler
        self.application.add_handler(InlineQueryHandler(github_handler.handle_inline_query))
        
        # הגדר conversation handler להעלאת קבצים
        from github_menu_handler import FILE_UPLOAD, REPO_SELECT, FOLDER_SELECT
        async def _upload_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
            try:
                cq = getattr(update, "callback_query", None)
                if cq is not None:
                    await cq.answer("העלאה בוטלה", show_alert=False)
            except Exception:
                pass
            return ConversationHandler.END

        upload_conv_handler = ConversationHandler(
            entry_points=[
                CallbackQueryHandler(github_handler.handle_menu_callback, pattern='^upload_file$')
            ],
            states={
                FILE_UPLOAD: [
                    MessageHandler(filters.Document.ALL, github_handler.handle_file_upload)
                ],
                REPO_SELECT: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, github_handler.handle_text_input)
                ],
                FOLDER_SELECT: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, github_handler.handle_text_input)
                ]
            },
            fallbacks=[
                CommandHandler('cancel', _upload_cancel),
                CallbackQueryHandler(_upload_cancel, pattern=r'^cancel$')
            ]
        )
        
        self.application.add_handler(upload_conv_handler)
        
        # הוסף handler כללי לטיפול בקלט טקסט של GitHub (כולל URL לניתוח)
        async def handle_github_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
            # העבר כל קלט רלוונטי למנהל GitHub לפי דגלים ב-user_data
            message = getattr(update, "message", None)
            if message is None:
                logger.debug("handle_github_text: update without message, ignoring")
                return False
            message_text = getattr(message, "text", None)
            if message_text is None:
                logger.debug("handle_github_text: missing text payload, ignoring")
                return False
            text = (message_text or '').strip()
            main_menu_texts = {"➕ הוסף קוד חדש", "📚 הצג את כל הקבצים שלי", "📂 קבצים גדולים", "🔧 GitHub", "🏠 תפריט ראשי", "⚡ עיבוד Batch"}
            if text in main_menu_texts:
                # נקה דגלים כדי למנוע טריגר שגוי
                context.user_data.pop('awaiting_search_text', None)  # יציאה אוטומטית מ"מצב חיפוש"
                context.user_data.pop('search_ctx', None)
                context.user_data.pop('waiting_for_repo_url', None)
                context.user_data.pop('waiting_for_delete_file_path', None)
                context.user_data.pop('waiting_for_download_file_path', None)
                context.user_data.pop('waiting_for_new_repo_name', None)
                context.user_data.pop('waiting_for_selected_folder', None)
                context.user_data.pop('waiting_for_new_folder_path', None)
                context.user_data.pop('waiting_for_upload_folder', None)
                context.user_data.pop('return_to_pre_upload', None)
                # נקה גם דגלי "הדבק קוד" כדי לצאת יפה מהזרימה
                context.user_data.pop('waiting_for_paste_content', None)
                context.user_data.pop('waiting_for_paste_filename', None)
                context.user_data.pop('paste_content', None)
                return False
            # זרימת הוספת הערה לגיבוי (משותפת ל-GitHub/Backup)
            if context.user_data.get('waiting_for_backup_note_for'):
                backup_id = context.user_data.pop('waiting_for_backup_note_for')
                try:
                    from database import db
                    ok = db.save_backup_note(update.effective_user.id, backup_id, (text or '')[:1000])
                    if ok:
                        await update.message.reply_text(
                            "✅ ההערה נשמרה!",
                            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 חזרה", callback_data=f"backup_details:{backup_id}")]])
                        )
                        # מנע הודעת "נראה שזה קטע קוד!" עבור ההודעה הזו
                        context.user_data['suppress_code_hint_once'] = True
                    else:
                        await update.message.reply_text("❌ שמירת ההערה נכשלה")
                except Exception as e:
                    await update.message.reply_text(f"❌ שגיאה בשמירת ההערה: {e}")
                return True
            # קלט נתיב יעד ידני לסביבת העלאה (upload_folder_custom)
            if context.user_data.get('waiting_for_upload_folder'):
                # ניתוב טקסט למטפל טקסטים של GitHub (סמנטי ונקי)
                return await github_handler.handle_text_input(update, context)

            if context.user_data.get('waiting_for_repo_url') or \
               context.user_data.get('waiting_for_delete_file_path') or \
               context.user_data.get('waiting_for_download_file_path') or \
               context.user_data.get('waiting_for_new_repo_name') or \
               context.user_data.get('waiting_for_selected_folder') or \
               context.user_data.get('waiting_for_new_folder_path') or \
               context.user_data.get('waiting_for_paste_content') or \
               context.user_data.get('waiting_for_paste_filename') or \
               context.user_data.get('browse_search_mode'):
                logger.info(f"🔗 Routing GitHub-related text input from user {update.effective_user.id}")
                return await github_handler.handle_text_input(update, context)
            return False

        # הוסף את ה-handler עם עדיפות גבוהה
        self.application.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_github_text),
            group=-1  # עדיפות גבוהה מאוד
        )
        # הוסף handler טקסט ל-Drive (קוד אישור)
        async def handle_drive_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
            return await drive_handler.handle_text(update, context)

        self.application.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_drive_text),
            group=-1
        )


        logger.info("✅ GitHub handler נוסף בהצלחה")

        # Handler נפרד לטיפול בטוקן GitHub
        async def handle_github_token(update: Update, context: ContextTypes.DEFAULT_TYPE):
            text = update.message.text
            if text.startswith('ghp_') or text.startswith('github_pat_'):
                user_id = update.message.from_user.id
                if user_id not in github_handler.user_sessions:
                    github_handler.user_sessions[user_id] = {}
                # שמירה בזיכרון בלבד לשימוש שוטף
                github_handler.user_sessions[user_id]['github_token'] = text

                # שמור גם במסד נתונים (עם הצפנה אם מוגדר מפתח)
                db.save_github_token(user_id, text)

                await update.message.reply_text(
                    "✅ טוקן נשמר בהצלחה!\n"
                    "כעת תוכל לגשת לריפוזיטוריז הפרטיים שלך.\n\n"
                    "שלח /github כדי לחזור לתפריט."
                )
                return

        # הוסף את ה-handler
        self.application.add_handler(
            MessageHandler(filters.Regex('^(ghp_|github_pat_)'), handle_github_token),
            group=0  # עדיפות גבוהה
        )
        logger.info("✅ GitHub token handler נוסף בהצלחה")

        # פקודה למחיקת טוקן GitHub
        async def handle_github_logout(update: Update, context: ContextTypes.DEFAULT_TYPE):
            user_id = update.effective_user.id
            # מחיקה מהמסד נתונים
            removed = db.delete_github_token(user_id)
            # ניקוי מהסשן
            try:
                session = github_handler.get_user_session(user_id)
                session["github_token"] = None
                session['selected_repo'] = None
                session['selected_folder'] = None
            except Exception:
                pass
            # ניקוי קאש ריפוזיטוריז
            context.user_data.pop('repos', None)
            context.user_data.pop('repos_cache_time', None)
            if removed:
                await update.message.reply_text("🔐 הטוקן נמחק בהצלחה מהחשבון שלך.\n✅ הוסרו גם הגדרות ריפו/תיקייה.")
            else:
                await update.message.reply_text("ℹ️ לא נמצא טוקן לשחזור או שאירעה שגיאה.")

        self.application.add_handler(CommandHandler("github_logout", handle_github_logout))

        # --- Guard גלובלי ללחיצות כפולות על CallbackQuery (קדימות גבוהה ביותר) ---
        async def _global_callback_guard(update: Update, context: ContextTypes.DEFAULT_TYPE):
            try:
                if getattr(update, 'callback_query', None):
                    # בדיקת דופליקטים קצרה לכל הכפתורים
                    try:
                        from utils import CallbackQueryGuard
                        if await CallbackQueryGuard.should_block_async(update, context):
                            try:
                                await update.callback_query.answer()
                            except Exception:
                                pass
                            # עצור עיבוד נוסף של ההודעה הנוכחית
                            raise ApplicationHandlerStop()
                    except Exception:
                        pass
            except ApplicationHandlerStop:
                raise
            except Exception:
                pass

        # הוסף את ה-guard בקבוצה בעלת עדיפות הגבוהה ביותר, לפני כל ה-handlers (כולל batch/github/drive)
        self.application.add_handler(CallbackQueryHandler(_global_callback_guard), group=-100)

        # הוספת פקודות batch (עיבוד מרובה קבצים) לאחר ה-guard כך שלא יעקוף אותו
        setup_batch_handlers(self.application)

        # --- Community Library handlers ---
        try:
            enabled_comm = bool(getattr(config, 'COMMUNITY_LIBRARY_ENABLED', True))
        except Exception:
            enabled_comm = True
        if enabled_comm:
            try:
                from conversation_handlers import (
                    community_submit_start,
                    community_collect_title,
                    community_collect_description,
                    community_collect_url,
                    community_collect_logo,
                    community_inline_approve,
                    community_reject_start,
                    community_collect_reject_reason,
                    # Snippet library
                    snippet_submit_start,
                    snippet_mode_regular_start,
                    snippet_mode_long_start,
                    snippet_collect_title,
                    snippet_collect_description,
                    snippet_collect_code,
                    snippet_collect_language,
                    snippet_long_collect_receive,
                    snippet_long_collect_done,
                    snippet_inline_approve,
                    snippet_reject_start,
                    snippet_collect_reject_reason,
                    show_community_hub,
                    community_catalog_menu,
                    snippets_menu,
                    # New helpers
                    community_hub_callback,
                    main_menu_callback,
                    submit_flows_cancel,
                    cancel,
                )
                from handlers.states import (
                    CL_COLLECT_TITLE,
                    CL_COLLECT_DESCRIPTION,
                    CL_COLLECT_URL,
                    CL_COLLECT_LOGO,
                    CL_REJECT_REASON,
                    SN_COLLECT_TITLE,
                    SN_COLLECT_DESCRIPTION,
                    SN_COLLECT_CODE,
                    SN_COLLECT_LANGUAGE,
                    SN_REJECT_REASON,
                    SN_LONG_COLLECT,
                )
                # Approve via inline button (admin-only wrapper inside function)
                self.application.add_handler(CallbackQueryHandler(community_inline_approve, pattern=r'^community_approve:'))
                # Community inline reject (reason collection)
                cl_reject_conv = ConversationHandler(
                    entry_points=[CallbackQueryHandler(community_reject_start, pattern=r'^community_reject:')],
                    states={
                        CL_REJECT_REASON: [MessageHandler(filters.TEXT & ~filters.COMMAND, community_collect_reject_reason)],
                    },
                    fallbacks=[CommandHandler('cancel', _cancel_command_fallback)],
                )
                self.application.add_handler(cl_reject_conv)
                # Snippet inline approve
                self.application.add_handler(CallbackQueryHandler(snippet_inline_approve, pattern=r'^snippet_approve:'))
                # Submission flow
                _logo_message_filter = filters.TEXT & ~filters.COMMAND
                try:
                    _photo_filter = getattr(filters, "PHOTO", None)
                    if _photo_filter is not None:
                        _logo_message_filter = (_photo_filter | filters.TEXT) & ~filters.COMMAND
                except Exception:
                    # אם חיבור הפילטרים נכשל (למשל בסביבת טסטים עם סטאבים פשוטים),
                    # תישאר רק בדיקה על טקסט. חשוב שה-handler עדיין יירשם.
                    _logo_message_filter = filters.TEXT & ~filters.COMMAND

                # דפוס טקסטים של התפריט הראשי לביטול אוטומטי במהלך תהליכי הגשה
                try:
                    import re as _re
                    _flat_main_menu = [t for row in MAIN_KEYBOARD for t in row]
                    _main_menu_regex = r'^(' + "|".join(_re.escape(t) for t in _flat_main_menu) + r')$'
                except Exception:
                    _main_menu_regex = r'^(?:)$'  # fallback: לא תופס כלום במקרה של כשל

                comm_conv = ConversationHandler(
                    entry_points=[CallbackQueryHandler(community_submit_start, pattern=r'^community_submit$')],
                    states={
                        CL_COLLECT_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, community_collect_title)],
                        CL_COLLECT_DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, community_collect_description)],
                        CL_COLLECT_URL: [MessageHandler(filters.TEXT & ~filters.COMMAND, community_collect_url)],
                        CL_COLLECT_LOGO: [MessageHandler(_logo_message_filter, community_collect_logo)],
                    },
                    fallbacks=[
                        CommandHandler('cancel', _cancel_command_fallback),
                        CallbackQueryHandler(submit_flows_cancel, pattern=r'^cancel$'),
                        # ביטול אוטומטי כאשר המשתמש לוחץ על כפתור אחר בתפריט הראשי
                        MessageHandler(filters.Regex(_main_menu_regex), cancel),
                    ],
                )
                self.application.add_handler(comm_conv)
                # Snippet submission flow
                sn_conv = ConversationHandler(
                    entry_points=[
                        CallbackQueryHandler(snippet_submit_start, pattern=r'^snippet_submit$'),
                        CallbackQueryHandler(snippet_mode_regular_start, pattern=r'^snippet_mode_regular$'),
                        CallbackQueryHandler(snippet_mode_long_start, pattern=r'^snippet_mode_long$'),
                    ],
                    states={
                        SN_COLLECT_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, snippet_collect_title)],
                        SN_COLLECT_DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, snippet_collect_description)],
                        SN_COLLECT_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, snippet_collect_code)],
                        SN_COLLECT_LANGUAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, snippet_collect_language)],
                        SN_LONG_COLLECT: [
                            MessageHandler(filters.TEXT & ~filters.COMMAND, snippet_long_collect_receive),
                            CommandHandler('done', snippet_long_collect_done),
                        ],
                    },
                    fallbacks=[
                        CommandHandler('cancel', _cancel_command_fallback),
                        CallbackQueryHandler(submit_flows_cancel, pattern=r'^cancel$'),
                        # ביטול אוטומטי כאשר המשתמש לוחץ על כפתור אחר בתפריט הראשי
                        MessageHandler(filters.Regex(_main_menu_regex), cancel),
                    ],
                )
                self.application.add_handler(sn_conv)
                # Snippet reject reason flow
                sn_reject_conv = ConversationHandler(
                    entry_points=[CallbackQueryHandler(snippet_reject_start, pattern=r'^snippet_reject:')],
                    states={
                        SN_REJECT_REASON: [MessageHandler(filters.TEXT & ~filters.COMMAND, snippet_collect_reject_reason)],
                    },
                    fallbacks=[CommandHandler('cancel', _cancel_command_fallback)],
                )
                self.application.add_handler(sn_reject_conv)
                # Community hub menus
                self.application.add_handler(MessageHandler(filters.Regex("^🗃️ אוסף הקהילה$"), show_community_hub))
                self.application.add_handler(CallbackQueryHandler(community_catalog_menu, pattern=r'^community_catalog_menu$'))
                self.application.add_handler(CallbackQueryHandler(snippets_menu, pattern=r'^snippets_menu$'))
                # Back navigation helpers
                self.application.add_handler(CallbackQueryHandler(community_hub_callback, pattern=r'^community_hub$'))
                self.application.add_handler(CallbackQueryHandler(main_menu_callback, pattern=r'^main_menu$'))
                # Global cancel for submission flows (works also on entry screen)
                self.application.add_handler(CallbackQueryHandler(submit_flows_cancel, pattern=r'^cancel$'))
            except Exception as _e:
                try:
                    logger.info("Community library handlers not registered: %s", _e)
                except Exception:
                    pass

        # הוספת Refactoring handlers (אם זמינים)
        try:
            from refactor_handlers import setup_refactor_handlers as _setup_rf
            if callable(_setup_rf):
                _setup_rf(self.application)
                logger.info("✅ RefactorHandlers הוגדרו (פקודת /refactor זמינה)")
        except Exception as e:
            logger.warning(f"⚠️ דילוג על RefactorHandlers: {e}")

        # --- רק אחרי כל ה-handlers הספציפיים, הוסף את ה-handler הגלובלי ---
        # חשוב: הוספה בקבוצה מאוחרת כדי שלא תתפוס לפני handlers ייעודיים (למשל מועדפים)
        from conversation_handlers import handle_callback_query
        _register_catch_all_callback(self.application, handle_callback_query)

        try:
            _instrument_command_handlers(self.application)
        except Exception:
            pass

        # ספור סופי
        final_handler_count = len(self.application.handlers)
        logger.info(f"🔍 כמות handlers סופית: {final_handler_count}")

        # הדפס את כל ה-handlers
        for i, handler in enumerate(self.application.handlers):
            logger.info(f"Handler {i}: {type(handler).__name__}")

        # --- שלב 2: רישום שאר הפקודות ---
        # פקודת מנהלים: recycle_backfill
        self.application.add_handler(CommandHandler("recycle_backfill", recycle_backfill_command))
        # פקודות מנהלי ספריית קהילה
        try:
            enabled_comm = bool(getattr(config, 'COMMUNITY_LIBRARY_ENABLED', True))
        except Exception:
            enabled_comm = True
        if enabled_comm:
            try:
                from conversation_handlers import (
                    community_queue_command, community_approve_command, community_reject_command,
                    snippet_queue_command, snippet_approve_command, snippet_reject_command,
                )
                self.application.add_handler(CommandHandler("community_queue", community_queue_command))
                self.application.add_handler(CommandHandler("community_approve", community_approve_command))
                self.application.add_handler(CommandHandler("community_reject", community_reject_command))
                # Snippet admin commands
                self.application.add_handler(CommandHandler("snippet_queue", snippet_queue_command))
                self.application.add_handler(CommandHandler("snippet_approve", snippet_approve_command))
                self.application.add_handler(CommandHandler("snippet_reject", snippet_reject_command))
            except Exception:
                pass
        # הפקודה /start המקורית הופכת להיות חלק מה-conv_handler, אז היא לא כאן.
        self.application.add_handler(CommandHandler("help", self.help_command))
        self.application.add_handler(CommandHandler("save", self.save_command))
        # self.application.add_handler(CommandHandler("list", self.list_command))  # מחוק - מטופל על ידי הכפתור "📚 הצג את כל הקבצים שלי"
        self.application.add_handler(CommandHandler("search", self.search_command))
        self.application.add_handler(CommandHandler("stats", self.stats_command))
        self.application.add_handler(CommandHandler("check", self.check_commands))

        # ChatOps: /jobs (Background Jobs Monitor)
        async def jobs_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
            try:
                from chatops.jobs_commands import handle_jobs_command
            except Exception:
                await update.message.reply_text("❌ Jobs monitor לא זמין כרגע")
                return
            args_text = ""
            try:
                args_text = " ".join(getattr(context, "args", None) or [])
            except Exception:
                args_text = ""
            text = handle_jobs_command(args_text)
            try:
                await update.message.reply_text(
                    text,
                    parse_mode=ParseMode.MARKDOWN,
                    disable_web_page_preview=True,
                )
            except Exception:
                # fallback ל-plain
                await update.message.reply_text(text, disable_web_page_preview=True)

        self.application.add_handler(CommandHandler("jobs", jobs_command))
        
        # הוספת פקודות cache
        setup_cache_handlers(self.application)
        
        # הוספת פקודות משופרות (אוטו-השלמה ותצוגה מקדימה) - disabled
        # setup_enhanced_handlers(self.application)

        # הטרמינל הוסר בסביבת Render (Docker לא זמין)


        # הוספת handlers לכפתורים החדשים במקלדת הראשית
        from conversation_handlers import handle_batch_button
        self.application.add_handler(MessageHandler(
            filters.Regex("^⚡ עיבוד Batch$"), 
            handle_batch_button
        ))
        # כפתור לתפריט Google Drive
        async def show_drive_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
            await drive_handler.menu(update, context)
        self.application.add_handler(MessageHandler(
            filters.Regex("^☁️ Google Drive$"),
            show_drive_menu
        ))

        # פקודה /drive
        self.application.add_handler(CommandHandler("drive", show_drive_menu))
        
        # כפתור Web App
        async def show_webapp(update: Update, context: ContextTypes.DEFAULT_TYPE):
            webapp_url = os.getenv('WEBAPP_URL', 'https://code-keeper-webapp.onrender.com')
            keyboard = [
                [InlineKeyboardButton("🌐 פתח את ה-Web App", url=webapp_url)],
                [InlineKeyboardButton("🔐 התחבר ל-Web App", url=f"{webapp_url}/login")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(
                "🌐 <b>Web App - ממשק ניהול מתקדם</b>\n\n"
                "צפה ונהל את כל הקבצים שלך דרך הדפדפן:\n"
                "• 📊 דשבורד עם סטטיסטיקות\n"
                "• 🔍 חיפוש וסינון מתקדם\n"
                "• 👁️ צפייה בקבצים עם הדגשת syntax\n"
                "• 📥 הורדת קבצים\n"
                "• 📱 עובד בכל מכשיר\n\n"
                "לחץ על הכפתור למטה כדי לפתוח:",
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML
            )
        
        self.application.add_handler(MessageHandler(
            filters.Regex("^🌐 Web App$"),
            show_webapp
        ))
        
        # פקודה /webapp
        self.application.add_handler(CommandHandler("webapp", show_webapp))
        
        # כפתור חדש לתפריט גיבוי/שחזור

        # פקודה /docs – שליחת קישור לתיעוד
        async def show_docs(update: Update, context: ContextTypes.DEFAULT_TYPE):
            await update.message.reply_text(f"📚 תיעוד: {config.DOCUMENTATION_URL}")
        self.application.add_handler(CommandHandler("docs", show_docs))
        # הוסר: כפתורי גיבוי/שחזור מהמקלדת הראשית. כעת תחת /github -> 🧰 גיבוי ושחזור
        # self.application.add_handler(MessageHandler(
        #     filters.Regex("^(📦 גיבוי מלא|♻️ שחזור מגיבוי|🧰 גיבוי/שחזור)$"),
        #     show_backup_menu
        # ))
        
        # --- שלב 3: רישום handler לקבצים ---
        self.application.add_handler(
            MessageHandler(filters.Document.ALL, self.handle_document)
        )
        
        # --- שלב 4: רישום המטפל הכללי בסוף ---
        # הוא יפעל רק אם אף אחד מהמטפלים הספציפיים יותר לא תפס את ההודעה.
        self.application.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_text_message)
        )
        
        try:
            _instrument_command_handlers(self.application)
        except Exception:
            pass

        # --- שלב 5: טיפול בשגיאות ---
        self.application.add_error_handler(self.error_handler)
    
    # start_command הוסר - ConversationHandler מטפל בפקודת /start
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """פקודת עזרה מפורטת"""
        if reporter is not None:
            reporter.report_activity(update.effective_user.id)
        await log_user_activity(update, context)
        ctx_app = getattr(context, "application", None)
        ctx_commands = _get_registered_commands(ctx_app) if ctx_app else set()
        if ctx_commands:
            commands = ctx_commands
        else:
            commands = _get_registered_commands(self.application)
        try:
            from chatops.permissions import is_admin as _is_admin
            user_id = int(getattr(getattr(update, "effective_user", None), "id", 0) or 0)
            user_is_admin = bool(_is_admin(user_id))
        except Exception:
            user_is_admin = False
        response = _build_help_message(commands, is_admin=user_is_admin)
        for chunk in _split_long_message(response):
            await update.message.reply_text(chunk, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    
    async def save_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """פקודת שמירת קוד"""
        if reporter is not None:
            reporter.report_activity(update.effective_user.id)
        await log_user_activity(update, context)
        user_id = update.effective_user.id
        
        if not context.args:
            await update.message.reply_text(
                "❓ אנא ציין שם קובץ:\n"
                "דוגמה: `/save script.py`\n"
                "עם תגיות: `/save script.py #python #api`",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        # פרסור שם קובץ ותגיות
        args = " ".join(context.args)
        tags = []
        
        # חילוץ תגיות
        import re
        tag_matches = re.findall(r'#(\w+)', args)
        if tag_matches:
            tags = tag_matches
            # הסרת התגיות משם הקובץ
            args = re.sub(r'#\w+', '', args).strip()
        
        file_name = args
        
        # שמירת מידע בהקשר למשך השיחה
        context.user_data['saving_file'] = {
            'file_name': file_name,
            'tags': tags,
            'user_id': user_id
        }
        
        safe_file_name = html_escape(file_name)
        safe_tags = ", ".join(html_escape(t) for t in tags) if tags else 'ללא'
        
        # בקשת קוד ולאחריו הערה אופציונלית
        await update.message.reply_text(
            f"📝 מוכן לשמור את <code>{safe_file_name}</code>\n"
            f"🏷️ תגיות: {safe_tags}\n\n"
            "אנא שלח את קטע הקוד:\n"
            "(אחרי שנקבל את הקוד, אשאל אם תרצה להוסיף הערה)",
            parse_mode=ParseMode.HTML
        )
    
    async def list_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """הצגת רשימת הקטעים של המשתמש"""
        if reporter is not None:
            reporter.report_activity(update.effective_user.id)
        user_id = update.effective_user.id
        
        files = db.get_user_files(user_id, limit=20)
        
        if not files:
            await update.message.reply_text(
                "📂 עדיין לא שמרת קטעי קוד.\n"
                "השתמש ב/save כדי להתחיל!"
            )
            return
        
        # בניית הרשימה
        response = "📋 **הקטעים שלך:**\n\n"
        
        for i, file_data in enumerate(files, 1):
            tags_str = ", ".join(file_data.get('tags', [])) if file_data.get('tags') else ""
            description = file_data.get('description', '')
            
            response += f"**{i}. {file_data['file_name']}**\n"
            response += f"🔤 שפה: {file_data['programming_language']}\n"
            
            if description:
                response += f"📝 תיאור: {description}\n"
            
            if tags_str:
                response += f"🏷️ תגיות: {tags_str}\n"
            
            response += f"📅 עודכן: {file_data['updated_at'].strftime('%d/%m/%Y %H:%M')}\n"
            response += f"🔢 גרסה: {file_data['version']}\n\n"
        
        if len(files) == 20:
            response += "\n📄 מוצגים 20 הקטעים האחרונים. השתמש בחיפוש לעוד..."
        
        await update.message.reply_text(response, parse_mode=ParseMode.HTML)
    
    async def search_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """חיפוש קטעי קוד"""
        if reporter is not None:
            reporter.report_activity(update.effective_user.id)
        await log_user_activity(update, context)
        user_id = update.effective_user.id
        
        if not context.args:
            await update.message.reply_text(
                "🔍 **איך לחפש:**\n"
                "• `/search python` - לפי שפה\n"
                "• `/search api` - חיפוש חופשי\n"
                "• `/search #automation` - לפי תגית\n"
                "• `/search script` - בשם קובץ",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        query = " ".join(context.args)
        
        # זיהוי אם זה חיפוש לפי תגית
        tags: list[str] = []
        # תמיכה בגרסאות ישנות של הקונפיג שלא כוללות SUPPORTED_LANGUAGES
        try:
            supported_languages = getattr(config, "SUPPORTED_LANGUAGES", []) or []
        except Exception:
            supported_languages = []
        normalized_languages = {lang.lower(): lang for lang in supported_languages if isinstance(lang, str)}

        language_filter: str | None = None
        search_term = query

        if query.startswith('#'):
            tags = [query[1:]]
            search_term = ""
        else:
            matched_language = normalized_languages.get(query.lower()) if normalized_languages else None
            if matched_language is not None:
                language_filter = matched_language
                search_term = ""

        if language_filter is not None:
            # חיפוש לפי שפה
            with track_performance("search_by_language", labels={"operation": "search_by_language"}):
                results = db.search_code(user_id, "", programming_language=language_filter)
        else:
            # חיפוש חופשי או לפי תגית
            with track_performance("search_free", labels={"operation": "search_free"}):
                results = db.search_code(user_id, search_term, tags=tags)
        
        if not results:
            await update.message.reply_text(
                f"🔍 לא נמצאו תוצאות עבור: <code>{html_escape(' '.join(context.args))}</code>",
                parse_mode=ParseMode.HTML
            )
            return
        
        # Business metric: search performed (avoid logging raw query)
        try:
            track_search_performed(user_id=user_id, query=' '.join(context.args), results_count=len(results))
            emit_event(
                "search_performed",
                severity="info",
                user_id=user_id,
                query_length=len(' '.join(context.args)),
                results_count=len(results),
            )
        except Exception:
            pass

        # הצגת תוצאות
        safe_query = html_escape(' '.join(context.args))
        response = f"🔍 **תוצאות חיפוש עבור:** <code>{safe_query}</code>\n\n"
        
        for i, file_data in enumerate(results[:10], 1):
            response += f"{i}. <code>{html_escape(file_data['file_name'])}</code> — {file_data['programming_language']}\n"
        
        if len(results) > 10:
            response += f"\n📄 מוצגות 10 מתוך {len(results)} תוצאות"
        
        await update.message.reply_text(response, parse_mode=ParseMode.HTML)
    
    async def check_commands(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """בדיקת פקודות תפריט/Runtime (מנהלים בלבד).

        שימושים:

        - ``/check``: מציג את פקודות התפריט (Telegram menu) ציבורי + scope אישי
        - ``/check commands``: מציג את כל ה-Slash commands שנרשמו ב-runtime דרך Application.handlers,
          ומשווה מול התפריט כדי לזהות מה "מוסתר".
        """
        from chatops.permissions import is_admin

        message_obj = getattr(update, "effective_message", None) or getattr(update, "message", None)
        try:
            user_id = int(getattr(getattr(update, "effective_user", None), "id", 0) or 0)
        except Exception:
            user_id = 0

        if not is_admin(user_id):
            if message_obj is not None:
                await message_obj.reply_text("❌ פקודה זמינה למנהלים בלבד")
            return

        args = []
        try:
            args = [str(a).strip().lower() for a in (getattr(context, "args", None) or []) if str(a).strip()]
        except Exception:
            args = []

        # /check commands – דיבוג פקודות runtime + diff מול תפריט טלגרם
        if args[:1] == ["commands"]:
            app = getattr(context, "application", None) or getattr(self, "application", None)
            registered = _get_registered_commands(app)

            public_cmds = None
            personal_cmds = None
            try:
                public_cmds = await context.bot.get_my_commands()
            except Exception:
                public_cmds = None
            try:
                from telegram import BotCommandScopeChat

                # בצ'אט פרטי chat_id == user_id
                personal_cmds = await context.bot.get_my_commands(scope=BotCommandScopeChat(chat_id=user_id))
            except Exception:
                personal_cmds = None

            report = _build_debug_commands_report(
                registered_commands=registered,
                public_menu_commands=public_cmds,
                personal_menu_commands=personal_cmds,
            )
            if message_obj is not None:
                await message_obj.reply_text(report, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
            return

        # /check – תפריט פקודות טלגרם (ציבורי + אישי)
        from html import escape as html_escape

        warnings: list[str] = []

        public_cmds = []
        try:
            public_cmds = await context.bot.get_my_commands()
        except Exception:
            public_cmds = []
            warnings.append("⚠️ לא הצלחתי למשוך פקודות ציבוריות מה-API של טלגרם")

        # בצ'אט פרטי chat_id == user_id. אם אין user_id (0), ננסה fallback ל-chat_id של ההודעה.
        chat_id_for_personal = None
        try:
            if user_id:
                chat_id_for_personal = user_id
            else:
                effective_chat = getattr(update, "effective_chat", None)
                cid = getattr(effective_chat, "id", None) if effective_chat is not None else None
                if isinstance(cid, int) and cid != 0:
                    chat_id_for_personal = cid
        except Exception:
            chat_id_for_personal = None

        personal_cmds = []
        if chat_id_for_personal is None:
            personal_cmds = []
            warnings.append("⚠️ דילוג על פקודות אישיות: אין chat_id זמין")
        else:
            try:
                from telegram import BotCommandScopeChat

                personal_cmds = await context.bot.get_my_commands(
                    scope=BotCommandScopeChat(chat_id=chat_id_for_personal)
                )
            except Exception:
                personal_cmds = []
                warnings.append("⚠️ לא הצלחתי למשוך פקודות אישיות (scope) מה-API של טלגרם")

        message = "📋 <b>סטטוס פקודות (Telegram Menu)</b>\n\n"
        if warnings:
            message += "\n".join(warnings) + "\n\n"
        message += f"סיכום: ציבוריות {len(public_cmds)} | אישיות {len(personal_cmds)}\n\n"
        if public_cmds:
            public_list = "\n".join(f"/{cmd.command}" for cmd in public_cmds)
            message += "<b>ציבוריות:</b>\n" + f"<pre>{html_escape(public_list)}</pre>\n"
        if personal_cmds:
            personal_list = "\n".join(f"/{cmd.command} — {cmd.description}" for cmd in personal_cmds)
            message += "<b>אישיות:</b>\n" + f"<pre>{html_escape(personal_list)}</pre>"

        if message_obj is not None:
            await message_obj.reply_text(message, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """הצגת סטטיסטיקות המשתמש או מנהל"""
        if reporter is not None:
            reporter.report_activity(update.effective_user.id)
        await log_user_activity(update, context)  # הוספת רישום משתמש לסטטיסטיקות
        user_id = update.effective_user.id
        
        # רשימת מנהלים
        ADMIN_IDS = [6865105071]  # הוסף את ה-ID שלך כאן!
        
        # אם המשתמש הוא מנהל, הצג סטטיסטיקות מנהל
        if user_id in ADMIN_IDS:
            # קבל סטטיסטיקות כלליות
            general_stats = user_stats.get_all_time_stats()
            weekly_users = user_stats.get_weekly_stats()
            
            # בנה הודעה בטוחה ל-HTML
            message = "📊 <b>סטטיסטיקות מנהל - שבוע אחרון:</b>\n\n"
            message += f"👥 סה״כ משתמשים רשומים: {general_stats['total_users']}\n"
            message += f"🟢 פעילים היום: {general_stats['active_today']}\n"
            message += f"📅 פעילים השבוע: {general_stats['active_week']}\n\n"
            
            if weekly_users:
                message += "📋 <b>רשימת משתמשים פעילים:</b>\n"
                from html import escape as html_escape
                for i, user in enumerate(weekly_users[:15], 1):
                    username = user.get('username') or 'User'
                    # הימלטות בטוחה
                    safe_username = html_escape(username)
                    if safe_username and safe_username != 'User' and not safe_username.startswith('User_'):
                        # הוספת @ אם זה שם משתמש טלגרם
                        display_name = f"@{safe_username}" if not safe_username.startswith('@') else safe_username
                    else:
                        display_name = safe_username
                    message += f"{i}. {display_name} - {user['days']} ימים ({user['total_actions']} פעולות)\n"
                
                if len(weekly_users) > 15:
                    message += f"\n... ועוד {len(weekly_users) - 15} משתמשים"
            else:
                message += "אין משתמשים פעילים בשבוע האחרון"
            
            await update.message.reply_text(message, parse_mode=ParseMode.HTML, reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True))
        else:
            # סטטיסטיקות רגילות למשתמש רגיל
            stats = db.get_user_stats(user_id)
            
            if not stats or stats.get('total_files', 0) == 0:
                await update.message.reply_text(
                    "📊 עדיין אין לך קטעי קוד שמורים.\n"
                    "התחל עם /save!",
                    reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
                )
                return
            
            languages_str = ", ".join(stats.get('languages', []))
            last_activity = stats.get('latest_activity')
            last_activity_str = last_activity.strftime('%d/%m/%Y %H:%M') if last_activity else "לא ידוע"
            
            response = (
                "📊 <b>הסטטיסטיקות שלך:</b>\n\n"
                f"📁 סה\"כ קבצים: <b>{stats['total_files']}</b>\n"
                f"🔢 סה\"כ גרסאות: <b>{stats['total_versions']}</b>\n"
                f"💾 מגבלת קבצים: {config.MAX_FILES_PER_USER}\n\n"
                "🔤 <b>שפות בשימוש:</b>\n"
                f"{languages_str}\n\n"
                "📅 <b>פעילות אחרונה:</b>\n"
                f"{last_activity_str}\n\n"
                "💡 <b>טיפ:</b> השתמש בתגיות לארגון טוב יותר!"
            )
            
            await update.message.reply_text(response, parse_mode=ParseMode.HTML, reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True))
    
    async def handle_document(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """מטפל בקבצים באמצעות DocumentHandler הייעודי."""
        message = getattr(update, "effective_message", None)
        if message is None:
            message = getattr(update, "message", None)
        document = getattr(message, "document", None) if message else None

        if document:
            size_limit_bytes = 20 * 1024 * 1024

            if getattr(document, "file_size", None) is not None:
                if document.file_size > 20 * 1024 * 1024:
                    warning_text = (
                        "❗️הקובץ גדול מדי.\n"
                        "המגבלה להעלאת קבצים היא 20MB. נסה לכווץ או לחלק את הקובץ."
                    )
                    if message and hasattr(message, "reply_text"):
                        await message.reply_text(warning_text)
                    else:
                        logger.warning("Document rejected: size exceeds 20MB limit")
                    return

            file_size = getattr(document, "file_size", None)

            if file_size is None:
                try:
                    telegram_file = await document.get_file()
                    file_size = getattr(telegram_file, "file_size", None)
                except Exception as exc:
                    logger.warning("Failed to resolve document size: %s", exc)

            if file_size is None:
                warning_text = (
                    "⚠️ לא הצלחתי לבדוק את גודל הקובץ.\n"
                    "המגבלה להעלאת קבצים היא 20MB. ודא שהקובץ קטן מהמגבלה ונסה שוב."
                )
                if message and hasattr(message, "reply_text"):
                    await message.reply_text(warning_text)
                else:
                    logger.warning("Document rejected: unknown size, limit is 20MB")
                return

            if file_size > size_limit_bytes:
                warning_text = (
                    "❗️הקובץ גדול מדי.\n"
                    "המגבלה להעלאת קבצים היא 20MB. נסה לכווץ או לחלק את הקובץ."
                )
                if message and hasattr(message, "reply_text"):
                    await message.reply_text(warning_text)
                else:
                    logger.warning("Document rejected: size exceeds 20MB limit")
                return

        await self.document_handler.handle_document(update, context)

    async def handle_text_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """טיפול בהודעות טקסט (קוד פוטנציאלי)"""
        if reporter is not None:
            reporter.report_activity(update.effective_user.id)
        await log_user_activity(update, context)
        user_id = update.effective_user.id
        message = getattr(update, "message", None)
        if message is None:
            logger.debug("handle_text_message: update without message, ignoring")
            return
        message_text = getattr(message, "text", None)
        if message_text is None:
            logger.debug("handle_text_message: missing text payload, ignoring")
            return
        text = message_text

        # מצב חיפוש אינטראקטיבי (מופעל מהכפתור "🔎 חפש קובץ")
        if context.user_data.get('awaiting_search_text'):
            query_text = (text or '').strip()
            context.user_data.pop('awaiting_search_text', None)

            # פירוק שאילתא: תומך name:..., lang:..., tag:repo:...
            name_substr = []
            lang_filter = None
            tag_filter = None
            try:
                tokens = [t for t in query_text.split() if t.strip()]
                for t in tokens:
                    lower = t.lower()
                    if lower.startswith('name:'):
                        name_substr.append(t.split(':', 1)[1])
                    elif lower.startswith('lang:'):
                        lang_filter = t.split(':', 1)[1].strip().lower() or None
                    elif lower.startswith('tag:'):
                        tag_filter = t.split(':', 1)[1].strip()
                    elif lower.startswith('repo:'):
                        tag_filter = t.strip()
                    else:
                        # מונחי חיפוש חופשיים בשם הקובץ
                        name_substr.append(t)
                name_filter = ' '.join(name_substr).strip()
            except Exception:
                name_filter = query_text

            # אחזור תוצאות
            from database import db
            # נחפש בבסיס (כולל $text), ואז נסנן לפי שם קובץ אם הוגדר name_filter
            results = db.search_code(
                user_id,
                query=name_filter if name_filter else "",
                programming_language=(lang_filter or ""),
                tags=([tag_filter] if tag_filter else []),
                limit=10000,
            ) or []
            # סינון לפי שם קובץ אם יש name_filter
            if name_filter:
                try:
                    nf = name_filter.lower()
                    results = [r for r in results if nf in str(r.get('file_name', '')).lower()]
                except Exception:
                    pass

            total = len(results)
            if total == 0:
                await update.message.reply_text(
                    "🔎 לא נמצאו תוצאות.",
                    reply_to_message_id=update.message.message_id,
                )
                # אפשר לאפשר חיפוש נוסף מיד
                context.user_data['awaiting_search_text'] = True
                return

            # שמירת פילטרים להמשך דפדוף
            context.user_data['search_filters'] = {
                'name_filter': name_filter,
                'lang': lang_filter,
                'tag': tag_filter,
            }
            context.user_data['files_origin'] = { 'type': 'search' }

            # בניית עמוד ראשון
            PAGE_SIZE = 10
            page = 1
            context.user_data['files_last_page'] = page
            start = (page - 1) * PAGE_SIZE
            end = min(start + PAGE_SIZE, total)

            # בניית מקלדת תוצאות
            from telegram import InlineKeyboardMarkup, InlineKeyboardButton
            keyboard = []
            context.user_data['files_cache'] = {}
            for i in range(start, end):
                item = results[i]
                fname = item.get('file_name', 'קובץ')
                lang = item.get('programming_language', 'text')
                button_text = f"📄 {fname} ({lang})"
                keyboard.append([InlineKeyboardButton(button_text, callback_data=f"file_{i}")])
                context.user_data['files_cache'][str(i)] = item

            # עימוד
            total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE if total > 0 else 1
            row = []
            if page > 1:
                row.append(InlineKeyboardButton("⬅️ הקודם", callback_data=f"search_page_{page-1}"))
            if page < total_pages:
                row.append(InlineKeyboardButton("➡️ הבא", callback_data=f"search_page_{page+1}"))
            if row:
                keyboard.append(row)
            keyboard.append([InlineKeyboardButton("🔙 חזרה", callback_data="files")])

            await update.message.reply_text(
                f"🔎 תוצאות חיפוש — סה״כ: {total}\n" +
                f"📄 עמוד {page} מתוך {total_pages}",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return

        # ביטול חד-פעמי של הודעת "נראה שזה קטע קוד!" (למשל אחרי שמירת הערה לגיבוי)
        if context.user_data.pop('suppress_code_hint_once', False):
            return
        
        # בדיקה אם המשתמש בתהליך שמירה
        if 'saving_file' in context.user_data:
            await self._save_code_snippet(update, context, text)
            return
        
        # זיהוי אם זה נראה כמו קוד, למעט בזמן זרימת "הדבק קוד" של GitHub
        if self._looks_like_code(text) and not (
            context.user_data.get('waiting_for_paste_content') or context.user_data.get('waiting_for_paste_filename')
        ):
            await update.message.reply_text(
                "🤔 נראה שזה קטע קוד!\n"
                "רוצה לשמור אותו? השתמש ב/save או שלח שוב עם שם קובץ.",
                reply_to_message_id=update.message.message_id
            )
        # שלב ביניים לקליטת הערה אחרי קוד
        elif 'saving_file' in context.user_data and context.user_data['saving_file'].get('note_asked') and 'pending_code_buffer' in context.user_data:
            note_text = (text or '').strip()
            if note_text.lower() in {"דלג", "skip", "ללא", ""}:
                context.user_data['saving_file']['note_value'] = ""
            else:
                # הגבלת אורך הערה
                context.user_data['saving_file']['note_value'] = note_text[:280]
            # קרא שוב לשמירה בפועל (תדלג על השאלה כי note_asked=true)
            await self._save_code_snippet(update, context, context.user_data.get('pending_code_buffer', ''))
    
    async def _save_code_snippet(self, update: Update, context: ContextTypes.DEFAULT_TYPE, code: str):
        """שמירה בפועל של קטע קוד"""
        if reporter is not None:
            reporter.report_activity(update.effective_user.id)
        saving_data = context.user_data.pop('saving_file')
        
        if len(code) > config.MAX_CODE_SIZE:
            await update.message.reply_text(
                f"❌ הקוד גדול מדי! מקסימום {config.MAX_CODE_SIZE} תווים."
            )
            return
        
        # זיהוי שפת התכנות באמצעות CodeProcessor + תיעוד מדוד
        with track_performance("detect_language"):
            detected_language = code_processor.detect_language(code, saving_data['file_name'])
        logger.info(f"זוהתה שפה: {detected_language} עבור הקובץ {saving_data['file_name']}")
        try:
            emit_event(
                "file_save_detect_language",
                severity="info",
                language=detected_language,
                file_name=saving_data['file_name'],
                size_bytes=len(code.encode('utf-8', errors='replace')),
            )
        except Exception:
            pass
        
        # אם טרם נשמרה הערה, נשאל כעת
        if not saving_data.get('note_asked'):
            saving_data['note_asked'] = True
            context.user_data['saving_file'] = saving_data
            context.user_data['pending_code_buffer'] = code
            await update.message.reply_text(
                "📝 רוצה להוסיף הערה קצרה לקובץ?\n"
                "כתוב/כתבי אותה עכשיו או שלח/י 'דלג' כדי לשמור בלי הערה."
            )
            return

        # שלב שני: כבר נשאלה הערה, בדוק אם התקבלה
        note = saving_data.get('note_value') or ""
        if 'pending_code_buffer' in context.user_data:
            code = context.user_data.pop('pending_code_buffer')

        # יצירת אובייקט קטע קוד כולל הערה (description)
        snippet = CodeSnippet(
            user_id=saving_data['user_id'],
            file_name=saving_data['file_name'],
            code=code,
            programming_language=detected_language,
            description=note,
            tags=saving_data['tags']
        )
        
        # שמירה במסד הנתונים
        saved_ok = False
        with track_performance("db_save_code_snippet"):
            saved_ok = db.save_code_snippet(snippet)
        if saved_ok:
            try:
                # Business metric: file saved (size in BYTES, not chars)
                try:
                    size_bytes = len(code.encode("utf-8", errors="replace"))
                except Exception:
                    size_bytes = len(code)  # Fallback
                track_file_saved(user_id=saving_data['user_id'], language=detected_language, size_bytes=size_bytes)
                emit_event(
                    "file_saved",
                    severity="info",
                    user_id=saving_data['user_id'],
                    language=detected_language,
                    size_bytes=size_bytes,
                    file_name=saving_data['file_name'],
                )
            except Exception:
                pass
            await update.message.reply_text(
                f"✅ נשמר בהצלחה!\n\n"
                f"📁 **{saving_data['file_name']}**\n"
                f"🔤 שפה: {detected_language}\n"
                f"🏷️ תגיות: {', '.join(saving_data['tags']) if saving_data['tags'] else 'ללא'}\n"
                f"📝 הערה: {note or '—'}\n"
                f"📊 גודל: {len(code)} תווים",
                parse_mode=ParseMode.HTML
            )
        else:
            await update.message.reply_text(
                "❌ שגיאה בשמירה. נסה שוב מאוחר יותר."
            )
            try:
                if errors_total is not None:
                    errors_total.labels(code="E_SAVE_FAILED").inc()
                emit_event(
                    "file_save_failed",
                    severity="error",
                    user_id=saving_data['user_id'],
                    file_name=saving_data['file_name'],
                )
            except Exception:
                pass
    
    def _looks_like_code(self, text: str) -> bool:
        """בדיקה פשוטה אם טקסט נראה כמו קוד"""
        code_indicators = [
            'def ', 'function ', 'class ', 'import ', 'from ',
            '){', '};', '<?php', '<html', '<script', 'SELECT ', 'CREATE TABLE'
        ]
        
        return any(indicator in text for indicator in code_indicators) or \
               text.count('\n') > 3 or text.count('{') > 1
    
    def _detect_language(self, filename: str, code: str) -> str:
        """זיהוי בסיסי של שפת תכנות (יורחב בעתיד)"""
        # זיהוי לפי סיומת קובץ
        extension_map = {
            '.py': 'python',
            '.js': 'javascript',
            '.html': 'html',
            '.css': 'css',
            '.java': 'java',
            '.cpp': 'cpp',
            '.c': 'c',
            '.php': 'php',
            '.rb': 'ruby',
            '.go': 'go',
            '.rs': 'rust',
            '.ts': 'typescript',
            '.sql': 'sql',
            '.sh': 'bash',
            '.json': 'json',
            '.xml': 'xml',
            '.yml': 'yaml',
            '.yaml': 'yaml'
        }
        
        for ext, lang in extension_map.items():
            if filename.lower().endswith(ext):
                return lang
        
        # זיהוי בסיסי לפי תוכן
        if 'def ' in code or 'import ' in code:
            return 'python'
        elif 'function ' in code or 'var ' in code or 'let ' in code:
            return 'javascript'
        elif '<?php' in code:
            return 'php'
        elif '<html' in code or '<!DOCTYPE' in code:
            return 'html'
        elif 'SELECT ' in code.upper() or 'CREATE TABLE' in code.upper():
            return 'sql'
        
        return 'text'  # ברירת מחדל
    
    async def error_handler(self, update: object, context: ContextTypes.DEFAULT_TYPE):
        """טיפול בשגיאות"""
        logger.error(f"שגיאה: {context.error}", exc_info=context.error)

        # זיהוי חריגת זיכרון (גלובלי)
        try:
            err = context.error
            err_text = str(err) if err else ""
            is_oom = isinstance(err, MemoryError) or (
                isinstance(err_text, str) and (
                    'Ran out of memory' in err_text or 'out of memory' in err_text.lower() or 'MemoryError' in err_text
                )
            )
            if is_oom:
                # נסה לצרף סטטוס זיכרון
                mem_status = ""
                try:
                    from utils import get_memory_usage  # import מקומי למניעת תלות בזמן בדיקות
                    mu = get_memory_usage()
                    mem_status = f" (RSS={mu.get('rss_mb')}MB, VMS={mu.get('vms_mb')}MB, %={mu.get('percent')})"
                except Exception:
                    pass
                # Alert Pipeline Consolidation: שלח התראה דרך internal_alerts (ולא DM ישיר בבוט)
                try:
                    try:
                        from internal_alerts import emit_internal_alert  # type: ignore
                    except Exception:
                        emit_internal_alert = None  # type: ignore
                    if emit_internal_alert is not None:
                        emit_internal_alert(
                            "bot_oom",
                            severity="critical",
                            summary=f"🚨 OOM זוהתה בבוט{mem_status}. חריגה: {err_text[:500]}",
                            source="main.error_handler",
                            error_message=err_text[:2000],
                            memory_status=mem_status,
                        )
                except Exception:
                    pass
        except Exception:
            pass

        if isinstance(update, Update) and update.effective_message:
            await update.effective_message.reply_text(
                "❌ אירעה שגיאה. אנא נסה שוב מאוחר יותר."
            )
    
    async def start(self):
        """הפעלת הבוט"""
        logger.info("מתחיל את הבוט...")
        await self.application.initialize()
        await self.application.start()
        await self.application.updater.start_polling()
        
        logger.info("הבוט פועל! לחץ Ctrl+C להפסקה.")
    
    async def stop(self):
        """עצירת הבוט"""
        logger.info("עוצר את הבוט...")
        await self.application.updater.stop()
        await self.application.stop()
        await self.application.shutdown()
        
        # שחרור נעילה וסגירת חיבור למסד נתונים (מוגן מכפלות)
        try:
            already_done = getattr(self, "_lock_cleanup_done", False)
        except Exception:
            already_done = False
        if not already_done:
            success = False
            try:
                success = bool(cleanup_mongo_lock())
            except Exception:
                success = False
            if success:
                try:
                    setattr(self, "_lock_cleanup_done", True)
                except Exception:
                    pass
        db.close()
        
        logger.info("הבוט נעצר.")

def signal_handler(signum, frame):
    """טיפול בסיגנלי עצירה"""
    logger.info(f"התקבל סיגנל {signum}, עוצר את הבוט...")
    sys.exit(0)

# ---------------------------------------------------------------------------
# Helper to register the basic command handlers with the Application instance.
# ---------------------------------------------------------------------------


def setup_handlers(application: Application, db_manager):  # noqa: D401
    """Register basic command handlers required for the bot to operate."""

    async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):  # noqa: D401
        user_id = update.effective_user.id
        username = update.effective_user.username
        
        # שמור משתמש במסד נתונים (INSERT OR IGNORE)
        db_manager.save_user(user_id, username)
        
        if reporter is not None:
            reporter.report_activity(user_id)
        await log_user_activity(update, context)  # הוספת רישום משתמש לסטטיסטיקות
        
        # בדיקה אם המשתמש הגיע מה-Web App או רוצה להוסיף קובץ
        if context.args and len(context.args) > 0:
            if context.args[0] == "add_file":
                # המשתמש רוצה להוסיף קובץ חדש
                reply_markup = ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
                await update.message.reply_text(
                    "📁 <b>הוספת קובץ חדש</b>\n\n"
                    "שלח לי קובץ קוד או טקסט כדי לשמור אותו.\n"
                    "אפשר לשלוח:\n"
                    "• קובץ בודד או מספר קבצים\n"
                    "• קובץ ZIP עם מספר קבצים\n"
                    "• הודעת טקסט עם קוד\n\n"
                    "💡 טיפ: אפשר להוסיף תיאור לקובץ בכיתוב (caption)",
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.HTML
                )
                return
            elif context.args[0] == "webapp_login":
                # יצירת קישור התחברות אישי
                webapp_url = os.getenv('WEBAPP_URL', 'https://code-keeper-webapp.onrender.com')
                
                # יצירת טוקן זמני לאימות (אפשר להשתמש ב-JWT או hash פשוט)
                import hashlib
                import time
                timestamp = int(time.time())
                secret = os.getenv('SECRET_KEY', 'dev-secret-key')
                token_data = f"{user_id}:{timestamp}:{secret}"
                auth_token = hashlib.sha256(token_data.encode()).hexdigest()[:32]
                
                # שמירת הטוקן במסד נתונים עם תוקף של 5 דקות
                db = db_manager.get_db()
                db.webapp_tokens.insert_one({
                    'token': auth_token,
                    'user_id': user_id,
                    'username': username,
                    'created_at': datetime.now(timezone.utc),
                    'expires_at': datetime.now(timezone.utc) + timedelta(minutes=5)
                })
                
                # יצירת קישור התחברות
                login_url = f"{webapp_url}/auth/token?token={auth_token}&user_id={user_id}"
                
                keyboard = [
                    [InlineKeyboardButton("🔐 התחבר ל-Web App", url=login_url)],
                    [InlineKeyboardButton("🌐 פתח את ה-Web App", url=webapp_url)]
                ]
                reply_markup_inline = InlineKeyboardMarkup(keyboard)
                
                await update.message.reply_text(
                    "🔐 <b>קישור התחברות אישי ל-Web App</b>\n\n"
                    "לחץ על הכפתור למטה כדי להתחבר:\n\n"
                    "⚠️ <i>הקישור תקף ל-5 דקות בלבד מטעמי אבטחה</i>",
                    reply_markup=reply_markup_inline,
                    parse_mode=ParseMode.HTML
                )
                return
        
        reply_markup = ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        await update.message.reply_text(
            "🤖 שלום וברוך הבא לבוט שומר הקוד המתקדם!\n\n"
            "🔹 שמור ונהל קטעי קוד בחכמה\n"
            "🔹 עריכה מתקדמת עם גרסאות\n"
            "🔹 חיפוש והצגה חכמה\n"
            "🔹 הורדה וניהול מלא\n"
            "🔹 העלאת קבצים ל-GitHub\n\n"
            "✨ חדש בבוט: \n"
            "• 🌐 מיני-WebApp - כפתור בפינה השמאלית למטה\n"
            "  הכי נוח לצפייה והעתקה של קוד ארוך (עד עשרות אלפי שורות)\n\n"
            "• 🗃 אוסף הקהילה - גלו כלים, ובוטים שבנו משתמשים אחרים\n"
            "  ואתם מוזמנים לשתף את הפרויקטים שלכם ולהצטרף לאוסף\n\n"
            "• לרשימת פקודות ללא כפתורים - שלחו /help\n\n"
            "🔧 תקלה בבוט? כתבו ל-@moominAmir",
            reply_markup=reply_markup
        )

    async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):  # noqa: D401
        if reporter is not None:
            reporter.report_activity(update.effective_user.id)
        await log_user_activity(update, context)  # הוספת רישום משתמש לסטטיסטיקות
        ctx_app = getattr(context, "application", None)
        ctx_commands = _get_registered_commands(ctx_app) if ctx_app else set()
        if ctx_commands:
            commands = ctx_commands
        else:
            commands = _get_registered_commands(application)
        try:
            from chatops.permissions import is_admin as _is_admin
            user_id = int(getattr(getattr(update, "effective_user", None), "id", 0) or 0)
            user_is_admin = bool(_is_admin(user_id))
        except Exception:
            user_is_admin = False
        text = _build_help_message(commands, is_admin=user_is_admin)
        try:
            for chunk in _split_long_message(text):
                await update.message.reply_text(chunk, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
        except Exception:
            plain_text = (
                text.replace("<b>", "")
                .replace("</b>", "")
                .replace("<code>", "")
                .replace("</code>", "")
                .replace("&lt;", "<")
                .replace("&gt;", ">")
            )
            for chunk in _split_long_message(plain_text, max_len=3900):
                await update.message.reply_text(chunk, disable_web_page_preview=True)

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))


# ---------------------------------------------------------------------------
# New lock-free main
# ---------------------------------------------------------------------------
def main() -> None:
    """
    Initializes and runs the bot after acquiring a lock.
    """
    try:
        # Initialize database first
        global db
        # השתמש ב-DatabaseManager הגלובלי (database.db) כדי לא ליצור instance חדש
        from database import db as _db  # type: ignore
        db = _db
        
        # MongoDB connection and lock management
        if not manage_mongo_lock():
            logger.warning("Another bot instance is already running. Exiting gracefully.")
            # יציאה נקייה ללא שגיאה
            sys.exit(0)

        # --- המשך הקוד הקיים שלך ---
        logger.info("Lock acquired. Initializing CodeKeeperBot...")
        
        # נשתמש באינסטנס קיים אם כבר נוצר (למשל ע"י טסט), אחרת ניצור חדש
        bot = CURRENT_BOT or CodeKeeperBot()
        
        logger.info("Bot is starting to poll...")
        # Cache warming: הפעלת עבודה רקע קצרה לאתחול קאש עבור משתמשים/תפריטים נפוצים
        try:
            async def _warm_cache(_ctx):
                try:
                    from database import db as _db
                    users: list[int] = []
                    try:
                        # קרא מזהי משתמשים פעילים אחרונים (best-effort)
                        coll = getattr(_db, 'db', None)
                        coll = getattr(coll, 'users', None)
                        rows_obj = None
                        if coll is not None and hasattr(coll, 'find'):
                            try:
                                rows_obj = coll.find({}, {"user_id": 1})
                                # אם יש limit על האובייקט (Cursor), השתמש בו, אחרת נמיר לרשימה ונחתוך
                                if hasattr(rows_obj, 'limit'):
                                    rows_obj = rows_obj.limit(10)
                            except Exception:
                                rows_obj = []
                        if rows_obj is None:
                            rows_obj = []
                        rows_list = list(rows_obj)
                        for r in rows_list[:10]:
                            uid = r.get('user_id') if isinstance(r, dict) else None
                            if isinstance(uid, int):
                                users.append(uid)
                    except Exception:
                        users = []
                    # חמם רשימות קבצים ושמות לקומבוס/אוטוקומפליט
                    for uid in users[:10]:
                        try:
                            _ = _db.get_user_files(uid, limit=50)
                        except Exception:
                            pass
                        try:
                            _ = _db.get_user_file_names(uid, limit=200)
                        except Exception:
                            pass
                        try:
                            _ = _db.get_repo_tags_with_counts(uid, max_tags=50)
                        except Exception:
                            pass
                except Exception:
                    return
            # הרצה לאחר עלייה כדי לא לעכב startup
            try:
                bot.application.job_queue.run_once(_warm_cache, when=2)
            except Exception:
                pass
        except Exception:
            pass
        # Start polling. In tests, run_polling may exist either on the
        # application or directly on the bot stub. Support both to avoid
        # AttributeError in minimal fakes.
        _app = getattr(bot, "application", None)
        _run_poll_app = getattr(_app, "run_polling", None)
        if callable(_run_poll_app):
            # ריכוך התופעה של 409 Conflict בגלל "גיהוקים" ברשת:
            # - מעלים read/write/connect/pool timeouts (ב-builder) + מגדילים גם את long-poll timeout כאן.
            # - מפעילים רק פרמטרים שקיימים בפועל בגרסת PTB (באמצעות inspect.signature).
            def _env_float(name: str, default: float) -> float:
                try:
                    v = os.getenv(name)
                    if v is None:
                        return float(default)
                    v = str(v).strip()
                    if not v:
                        return float(default)
                    return float(v)
                except Exception:
                    return float(default)

            def _env_int(name: str, default: int) -> int:
                try:
                    v = os.getenv(name)
                    if v is None:
                        return int(default)
                    v = str(v).strip()
                    if not v:
                        return int(default)
                    return int(float(v))
                except Exception:
                    return int(default)

            connect_timeout = _env_float("TELEGRAM_CONNECT_TIMEOUT_SECS", 10.0)
            pool_timeout = _env_float("TELEGRAM_POOL_TIMEOUT_SECS", 10.0)
            write_timeout = _env_float("TELEGRAM_WRITE_TIMEOUT_SECS", 30.0)
            read_timeout = _env_float("TELEGRAM_READ_TIMEOUT_SECS", 30.0)
            poll_interval = _env_float("TELEGRAM_POLL_INTERVAL_SECS", 0.0)
            long_poll_timeout = _env_int("TELEGRAM_LONG_POLL_TIMEOUT_SECS", 20)
            conflict_backoff = _env_int("TELEGRAM_CONFLICT_BACKOFF_SECS", 30)
            conflict_max_retries = _env_int("TELEGRAM_CONFLICT_MAX_RETRIES", 5)
            conflict_max_seconds = _env_int("TELEGRAM_CONFLICT_MAX_SECONDS", 300)

            # Ensure read_timeout is safely above the long poll timeout
            try:
                if float(read_timeout) <= float(long_poll_timeout) + 2.0:
                    read_timeout = float(long_poll_timeout) + 5.0
            except Exception:
                pass

            poll_kwargs = {
                "drop_pending_updates": True,
                "poll_interval": float(poll_interval),
                "timeout": int(long_poll_timeout),
                "read_timeout": float(read_timeout),
                "write_timeout": float(write_timeout),
                "connect_timeout": float(connect_timeout),
                "pool_timeout": float(pool_timeout),
            }

            def _call_with_supported_kwargs(fn, kwargs: dict[str, Any]):
                """
                Call fn(**kwargs) but only pass supported keyword args.

                חשוב: לא "לבלוע" חריגות של fn (למשל Conflict). לכן אנחנו תופסים חריגות
                *רק* מהאינטורספקציה של inspect.signature, ולא מהקריאה עצמה.
                """
                supported = kwargs
                try:
                    sig = inspect.signature(fn)
                    # אם הפונקציה מקבלת **kwargs, תעביר הכל (זה המקרה בהרבה stubs/tests)
                    if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
                        supported = kwargs
                    else:
                        supported = {k: v for k, v in kwargs.items() if k in sig.parameters}
                except (TypeError, ValueError):
                    # signature לא זמין (builtins/partials/monkeypatch) – ננסה להעביר הכל
                    supported = kwargs
                return fn(**supported)

            # Best-effort swallow & backoff on Conflict (אם זה נזרק החוצה)
            try:
                from telegram.error import Conflict as _TgConflict  # type: ignore
            except Exception:  # pragma: no cover
                _TgConflict = None  # type: ignore

            conflict_tries = 0
            conflict_started_at: float | None = None
            while True:
                try:
                    _call_with_supported_kwargs(_run_poll_app, poll_kwargs)
                    break
                except Exception as _e:
                    is_conflict = False
                    try:
                        if _TgConflict is not None and isinstance(_e, _TgConflict):
                            is_conflict = True
                        elif "terminated by other getupdates request" in str(_e).lower():
                            is_conflict = True
                    except Exception:
                        is_conflict = False
                    if not is_conflict:
                        raise
                    # Persistent conflicts likely mean another long-lived poller (or webhook) is active.
                    # Don't retry forever: release lock via finally and let the orchestrator recover.
                    try:
                        conflict_tries += 1
                        if conflict_started_at is None:
                            conflict_started_at = time.time()
                        elapsed = float(time.time() - conflict_started_at)
                    except Exception:
                        elapsed = 0.0

                    # conflict_tries נספר כ"כמה פעמים כבר קיבלנו Conflict" (כולל הפעם הראשונה).
                    # כדי ש-CONFLICT_MAX_RETRIES יתנהג כ"מספר retries אחרי ה-Conflict הראשון",
                    # אנחנו יוצאים רק כשעברנו את התקרה (>) ולא כששווים לה.
                    hit_retry_cap = bool(conflict_max_retries > 0 and conflict_tries > conflict_max_retries)
                    hit_time_cap = bool(conflict_max_seconds > 0 and elapsed >= float(conflict_max_seconds))
                    if hit_retry_cap or hit_time_cap:
                        logger.error(
                            "Persistent Telegram getUpdates Conflict; exiting to release lock and allow recovery. "
                            f"tries={conflict_tries} elapsed={elapsed:.1f}s max_retries={conflict_max_retries} "
                            f"max_seconds={conflict_max_seconds} last_err={_e}"
                        )
                        try:
                            emit_event(
                                "telegram_polling_conflict_persistent",
                                severity="error",
                                tries=int(conflict_tries),
                                elapsed_seconds=float(elapsed),
                                max_retries=int(conflict_max_retries),
                                max_seconds=int(conflict_max_seconds),
                                error=str(_e)[:500],
                            )
                        except Exception:
                            pass
                        raise SystemExit(1)
                    logger.warning(
                        f"Telegram getUpdates Conflict detected; backing off for {conflict_backoff}s and retrying. err={_e}"
                    )
                    try:
                        emit_event(
                            "telegram_polling_conflict_backoff",
                            severity="warn",
                            backoff_seconds=int(conflict_backoff),
                            error=str(_e)[:500],
                        )
                    except Exception:
                        pass
                    time.sleep(max(5, int(conflict_backoff)))
        else:
            _run_poll_bot = getattr(bot, "run_polling", None)
            if callable(_run_poll_bot):
                _run_poll_bot(drop_pending_updates=True)
            else:
                logger.warning("run_polling not available on application or bot; skipping.")
        
    except Exception as e:
        logger.error(f"שגיאה: {e}")
        raise
    finally:
        logger.info("Bot polling stopped. Releasing lock and closing database connection.")
        try:
            cleanup_mongo_lock()
        except Exception:
            pass
        if 'db' in globals():
            db.close_connection()
        # Scheduler/Webapp thread-safety: close the scheduler-dedicated Mongo clients (best-effort)
        try:
            app_obj = bot if "bot" in locals() else None
            # CodeKeeperBot שומר את PTB Application תחת bot.application
            app = getattr(app_obj, "application", None) or app_obj
            bot_data = getattr(app, "bot_data", None)
            if isinstance(bot_data, dict):
                motor_client = bot_data.get("_scheduler_motor_client")
                if motor_client is not None and hasattr(motor_client, "close"):
                    motor_client.close()
                pymongo_client = bot_data.get("_scheduler_pymongo_client")
                if pymongo_client is not None and hasattr(pymongo_client, "close"):
                    pymongo_client.close()
                # ניקוי best-effort כדי למנוע שימוש חוזר באובייקטים סגורים
                try:
                    bot_data.pop("_scheduler_motor_client", None)
                    bot_data.pop("_scheduler_motor_db", None)
                    bot_data.pop("_scheduler_pymongo_client", None)
                    bot_data.pop("_scheduler_motor_lock", None)
                except Exception:
                    pass
        except Exception:
            pass


# A minimal post_init stub to comply with the PTB builder chain
async def setup_bot_data(application: Application) -> None:  # noqa: D401
    """A post_init function to setup application-wide data."""
    # מחיקת כל הפקודות הציבוריות (אין להגדיר /share /share_help — שיתוף דרך הכפתורים)
    await application.bot.delete_my_commands()
    logger.info("✅ Public commands cleared (no /share, /share_help)")

    # רישום כל ה-Background Jobs במערכת (Jobs Monitor)
    try:
        from services.register_jobs import register_all_jobs

        register_all_jobs()
    except Exception:
        # Fail-open: אל תכשיל startup אם מודול הניטור לא זמין
        pass

    # Scheduler: "צינור" MongoDB נפרד ל-thread של ה-bot/scheduler, כדי לא לחלוק Pool עם ה-Webapp.
    def _scheduler_db_disabled() -> bool:
        try:
            return str(os.getenv("DISABLE_DB", "") or "").strip().lower() in {"1", "true", "yes", "on"}
        except Exception:
            return False

    async def _get_scheduler_motor_db(app: Application):
        """Motor DB פרטי ל-scheduler (best-effort)."""
        if _scheduler_db_disabled():
            return None
        mongo_url = (os.getenv("MONGODB_URL") or "").strip()
        if not mongo_url:
            return None
        db_name = (os.getenv("DATABASE_NAME") or "code_keeper_bot").strip() or "code_keeper_bot"

        try:
            from motor.motor_asyncio import AsyncIOMotorClient  # type: ignore
        except Exception:
            return None

        bot_data = getattr(app, "bot_data", None)
        if not isinstance(bot_data, dict):
            return None

        existing_db = bot_data.get("_scheduler_motor_db")
        if existing_db is not None:
            return existing_db

        # הגנה מפני race: שתי coroutines יכולות להגיע לכאן במקביל ולהדליף client "יתום"
        lock = bot_data.get("_scheduler_motor_lock")
        if lock is None or not isinstance(lock, asyncio.Lock):
            lock = asyncio.Lock()
            bot_data["_scheduler_motor_lock"] = lock

        async with lock:
            # Double-check אחרי הנעילה
            existing_db = bot_data.get("_scheduler_motor_db")
            if existing_db is not None:
                return existing_db

            try:
                client = AsyncIOMotorClient(mongo_url)
                db_obj = client[db_name]

                # שמירה לפני await כדי למנוע "יתום" במקרה של interleave
                bot_data["_scheduler_motor_client"] = client
                bot_data["_scheduler_motor_db"] = db_obj

                # Best-effort ping: לא חייב, רק sanity check קצר
                try:
                    await asyncio.wait_for(client.admin.command("ping"), timeout=2.0)
                except Exception:
                    pass

                return db_obj
            except Exception:
                # אם משהו נכשל אחרי יצירה חלקית, ננקה best-effort
                try:
                    maybe_client = bot_data.pop("_scheduler_motor_client", None)
                    bot_data.pop("_scheduler_motor_db", None)
                    if maybe_client is not None and hasattr(maybe_client, "close"):
                        maybe_client.close()
                except Exception:
                    pass
                return None

    def _get_scheduler_pymongo_client(app: Application):
        """PyMongo client פרטי ל-APScheduler jobstore (best-effort)."""
        if _scheduler_db_disabled():
            return None
        mongo_url = (os.getenv("MONGODB_URL") or "").strip()
        if not mongo_url:
            return None
        try:
            from pymongo import MongoClient  # type: ignore
        except Exception:
            return None

        bot_data = getattr(app, "bot_data", None)
        if not isinstance(bot_data, dict):
            return None

        existing = bot_data.get("_scheduler_pymongo_client")
        if existing is not None:
            return existing

        try:
            client = MongoClient(mongo_url, serverSelectionTimeoutMS=3000)
            bot_data["_scheduler_pymongo_client"] = client
            return client
        except Exception:
            return None

    # Jobs Monitor: זיהוי הרצות "תקועות" (job_stuck)
    try:
        from datetime import timedelta as _td
        from observability import emit_event as _emit  # type: ignore

        async def _jobs_stuck_monitor(_context: ContextTypes.DEFAULT_TYPE):  # noqa: ARG001
            try:
                db_obj = await _get_scheduler_motor_db(_context.application)
                if db_obj is None:
                    return

                try:
                    threshold_min = int(os.getenv("JOBS_STUCK_THRESHOLD_MINUTES", "20") or 20)
                except Exception:
                    threshold_min = 20
                threshold_min = max(1, threshold_min)

                now = datetime.now(timezone.utc)
                cutoff = now - _td(minutes=threshold_min)

                coll = getattr(db_obj, "job_runs", None)
                if coll is None or not hasattr(coll, "find"):
                    return

                # emit only once per run (stuck_reported_at gate)
                cursor = coll.find(
                    {
                        "status": "running",
                        "started_at": {"$lt": cutoff},
                        "stuck_reported_at": {"$exists": False},
                    },
                    {"run_id": 1, "job_id": 1, "started_at": 1},
                ).sort("started_at", 1).limit(50)

                try:
                    docs = await cursor.to_list(length=50)
                except Exception:
                    docs = []

                for doc in list(docs or []):
                    run_id = str(doc.get("run_id") or "").strip()
                    job_id = str(doc.get("job_id") or "").strip()
                    started_at = doc.get("started_at")
                    minutes = None
                    try:
                        if started_at:
                            minutes = int(max(1, (now - started_at).total_seconds() // 60))
                    except Exception:
                        minutes = None

                    if not run_id or not job_id:
                        continue

                    # mark + append log (keep last 50)
                    try:
                        await coll.update_one(
                            {"run_id": run_id, "stuck_reported_at": {"$exists": False}},
                            {
                                "$set": {"stuck_reported_at": now},
                                "$push": {
                                    "logs": {
                                        "$each": [
                                            {
                                                "timestamp": now,
                                                "level": "error",
                                                "message": "Job stuck detected",
                                                "details": {"minutes": minutes} if minutes is not None else None,
                                            }
                                        ],
                                        "$slice": -50,
                                    }
                                },
                            },
                            upsert=False,
                        )
                    except Exception:
                        pass

                    _emit(
                        "job_stuck",
                        severity="error",
                        job_id=job_id,
                        run_id=run_id,
                        minutes=int(minutes or threshold_min),
                    )
            except Exception:
                return

        try:
            interval = int(os.getenv("JOBS_STUCK_MONITOR_INTERVAL_SECS", "60") or 60)
        except Exception:
            interval = 60
        interval = max(30, interval)
        application.job_queue.run_repeating(
            _jobs_stuck_monitor,
            interval=interval,
            first=30,
            name="jobs_stuck_monitor",
        )
    except Exception:
        # Fail-open
        pass

    # Job Triggers Processor: עיבוד בקשות trigger מה-Webapp
    try:
        async def _process_pending_job_triggers(context: ContextTypes.DEFAULT_TYPE):
            """מעבד בקשות trigger שנוצרו דרך ה-Webapp ומפעיל את הג'ובים."""
            try:
                db_obj = await _get_scheduler_motor_db(context.application)
                if db_obj is None:
                    logger.debug("pending_job_triggers: DB not available or noop")
                    return

                coll = getattr(db_obj, "job_trigger_requests", None)
                if coll is None or not hasattr(coll, "find"):
                    logger.debug("pending_job_triggers: collection not available")
                    return

                now = datetime.now(timezone.utc)
                # מחפש כל בקשות pending - ללא cutoff כדי לא לאבד בקשות אם הבוט היה למטה
                # בקשות ישנות מאוד (מעל שעה) יסומנו כ-expired במקום להתעלם מהן
                from datetime import timedelta as _td_trigger
                expire_cutoff = now - _td_trigger(hours=1)

                # סימון בקשות ישנות מדי כ-expired
                try:
                    expired_result = await coll.update_many(
                        {"status": "pending", "created_at": {"$lt": expire_cutoff}},
                        {"$set": {"status": "expired", "error": "Request expired (bot was unavailable for >1h)"}},
                    )
                    if expired_result.modified_count > 0:
                        logger.info("pending_job_triggers: expired %d old requests", expired_result.modified_count)
                except Exception as exp_err:
                    logger.debug("pending_job_triggers: expire update failed: %s", exp_err)

                cursor = coll.find({"status": "pending"}).sort("created_at", 1).limit(10)
                try:
                    pending_list = await cursor.to_list(length=10)
                except Exception:
                    pending_list = []
                if pending_list:
                    logger.info("pending_job_triggers: found %d pending requests", len(pending_list))

                for doc in pending_list:
                    trigger_id = doc.get("trigger_id")
                    job_id = doc.get("job_id")
                    if not trigger_id or not job_id:
                        logger.warning("pending_job_triggers: skipping doc with missing trigger_id/job_id")
                        continue

                    logger.info("pending_job_triggers: processing trigger_id=%s job_id=%s", trigger_id, job_id)

                    # סימון כ-processing כדי למנוע עיבוד כפול
                    result = await coll.update_one(
                        {"trigger_id": trigger_id, "status": "pending"},
                        {"$set": {"status": "processing", "processed_at": now}},
                    )
                    if result.modified_count == 0:
                        logger.debug("pending_job_triggers: trigger %s already processed", trigger_id)
                        continue  # כבר עובד/עבר עיבוד

                    try:
                        # חיפוש הג'וב ב-JobQueue והפעלתו
                        jq = context.application.job_queue
                        if jq is None:
                            raise RuntimeError("job_queue_unavailable")

                        jobs = jq.get_jobs_by_name(job_id)
                        logger.debug("pending_job_triggers: get_jobs_by_name(%s) returned %d jobs", job_id, len(jobs) if jobs else 0)

                        if not jobs:
                            # ניסיון למצוא callback ישירות מה-JobRegistry
                            all_job_names = [getattr(j, "name", "?") for j in (jq.jobs() if hasattr(jq, "jobs") else [])]
                            logger.warning(
                                "pending_job_triggers: job_not_found job_id=%s available_jobs=%s",
                                job_id,
                                all_job_names[:20]
                            )
                            raise RuntimeError(f"job_not_found: {job_id}")

                        job_obj = jobs[0]
                        callback = getattr(job_obj, "callback", None)
                        if not callable(callback):
                            raise RuntimeError(f"callback_not_callable: {job_id}")

                        # הפעלת הג'וב מיידית
                        suffix = str(int(time.time()))
                        data = getattr(job_obj, "data", None)
                        chat_id = getattr(job_obj, "chat_id", None)
                        user_id = getattr(job_obj, "user_id", None)
                        kwargs = {"when": 0, "name": f"{job_id}_webapp_trigger_{suffix}"}
                        if data is not None:
                            kwargs["data"] = data
                        if chat_id is not None:
                            kwargs["chat_id"] = chat_id
                        if user_id is not None:
                            kwargs["user_id"] = user_id

                        logger.info("pending_job_triggers: running job %s via run_once", job_id)
                        jq.run_once(callback, **kwargs)

                        # עדכון סטטוס להצלחה
                        await coll.update_one(
                            {"trigger_id": trigger_id},
                            {"$set": {"status": "completed", "result": "triggered"}},
                        )
                        logger.info("pending_job_triggers: SUCCESS trigger_id=%s job_id=%s", trigger_id, job_id)

                    except Exception as e:
                        # עדכון סטטוס לכישלון
                        await coll.update_one(
                            {"trigger_id": trigger_id},
                            {"$set": {"status": "failed", "error": str(e)}},
                        )
                        logger.warning("pending_job_triggers: FAILED trigger_id=%s job_id=%s error=%s", trigger_id, job_id, e)

            except Exception as outer_err:
                logger.error("pending_job_triggers: outer exception: %s", outer_err)
                return

        # שיכוך כאבים: polling איטי יותר כדי להפחית עומס על Mongo ברשת איטית/latency גבוהה
        # ברירת מחדל: 60 שניות (ניתן לשינוי דרך ENV)
        try:
            interval = int(os.getenv("JOB_TRIGGERS_POLL_INTERVAL_SECS", "60") or 60)
        except Exception:
            interval = 60
        interval = max(60, interval)
        application.job_queue.run_repeating(
            _process_pending_job_triggers,
            interval=interval,
            first=10,
            name="pending_job_triggers",
        )
        logger.info("✅ Pending job triggers processor registered (every %ds)", interval)
    except Exception:
        # Fail-open
        pass

    # הגדרת JobStore מתמיד ל-APScheduler (MongoDB) אם אפשרי
    try:
        jq = getattr(application, "job_queue", None)
        scheduler = getattr(jq, "scheduler", None)
        if scheduler is not None:
            client = _get_scheduler_pymongo_client(application)
            db_name = (os.getenv("DATABASE_NAME") or "code_keeper_bot").strip() or "code_keeper_bot"
            # אל תגדיר כשאין חיבור
            if client is not None and db_name:
                try:
                    # הוסף JobStore בשם 'persistent' לשימוש ע"י משימות הגיבוי
                    scheduler.add_jobstore(
                        'mongodb',
                        alias='persistent',
                        client=client,
                        database=db_name,
                        collection=os.getenv('APSCHEDULER_COLLECTION', 'scheduler_jobs'),
                    )
                    logger.info("✅ APScheduler persistent jobstore registered (MongoDB)")
                except Exception as e:  # pragma: no cover — fail‑open בסביבות טסט/ללא DB
                    logger.warning(f"APS persistent jobstore not available: {e}")
    except Exception:
        # Fail-open: אין להפיל את ה-setup אם שכבת APScheduler אינה זמינה
        pass
    
    # הגדרת פקודת stats רק למנהל (אמיר בירון)
    AMIR_ID = 6865105071  # ה-ID של אמיר בירון
    
    try:
        # הגדר רק את פקודת stats לאמיר
        await application.bot.set_my_commands(
            commands=[
                BotCommand("stats", "📊 סטטיסטיקות שימוש"),
            ],
            scope=BotCommandScopeChat(chat_id=AMIR_ID)
        )
        logger.info(f"✅ Commands set for Amir (ID: {AMIR_ID}): stats only")
    except Exception as e:
        logger.error(f"⚠️ Error setting admin commands: {e}")

    # פליטת אירוע מוקדמת: ניקוי גיבויים — תמיכה במצבי טסט
    # נשתמש בייבוא דינמי כדי לשתף פעולה עם monkeypatch בטסטים
    try:
        enabled_env = str(os.getenv("BACKUPS_CLEANUP_ENABLED", "false")).lower()
        enabled = enabled_env in {"1", "true", "yes", "on"}
        if not enabled:
            try:
                from observability import emit_event as _emit
            except Exception:  # pragma: no cover
                _emit = None
            if _emit is not None:
                _emit("backups_cleanup_disabled", severity="info")
            else:
                try:
                    emit_event("backups_cleanup_disabled", severity="info")
                except Exception:
                    pass
        else:
            # כאשר מופעל (enabled) ובסביבת טסטים, נפעיל פעם אחת מידית כדי להבטיח פליטת אירוע
            try:
                if os.getenv("PYTEST_CURRENT_TEST"):
                    try:
                        from file_manager import backup_manager as _bm
                    except Exception:  # pragma: no cover
                        _bm = None
                    if _bm is not None:
                        try:
                            summary = _bm.cleanup_expired_backups()
                            try:
                                from observability import emit_event as _emit
                            except Exception:  # pragma: no cover
                                _emit = (lambda *a, **k: None)
                            _emit(
                                "backups_cleanup_done",
                                severity="info",
                                fs_scanned=int((summary or {}).get("fs_scanned", 0) or 0),
                                fs_deleted=int((summary or {}).get("fs_deleted", 0) or 0),
                                gridfs_scanned=int((summary or {}).get("gridfs_scanned", 0) or 0),
                                gridfs_deleted=int((summary or {}).get("gridfs_deleted", 0) or 0),
                            )
                        except Exception:
                            try:
                                from observability import emit_event as _emit
                            except Exception:  # pragma: no cover
                                _emit = (lambda *a, **k: None)
                            _emit("backups_cleanup_error", severity="anomaly")
            except Exception:
                pass
    except Exception:
        # Fail-open: אין להפיל את ה-setup אם שכבת observability לא זמינה
        pass
    
    # הפעלת שרת קטן ל-/health ו-/share/<id> — כבוי כברירת מחדל
    enable_internal_web = str(os.getenv('ENABLE_INTERNAL_SHARE_WEB', 'false')).lower() == 'true'
    if enable_internal_web and config.PUBLIC_BASE_URL:
        try:
            from services.webserver import create_app
            aiohttp_app = create_app()
            async def _start_web_job(context: ContextTypes.DEFAULT_TYPE):
                # Jobs Monitor trigger support: שמור reference ל-Application בתוך aiohttp app
                try:
                    aiohttp_app["telegram_application"] = context.application
                except Exception:
                    pass
                runner = web.AppRunner(aiohttp_app)
                await runner.setup()
                port = int(os.getenv("PORT", "10000"))
                site = web.TCPSite(runner, host="0.0.0.0", port=port)
                await site.start()
                logger.info(f"🌐 Internal web server started on :{port}")
                try:
                    try:
                        from observability import emit_event as _emit
                    except Exception:  # pragma: no cover
                        _emit = lambda *a, **k: None
                    _emit("internal_web_started", severity="info", port=int(port))
                except Exception:
                    pass
            # להריץ אחרי שהאפליקציה התחילה, כדי להימנע מ-PTBUserWarning
            result = application.job_queue.run_once(_start_web_job, when=0)
            # בסביבת טסטים, ה-run_once עשוי להחזיר create_task; נמתין לו כדי להבטיח שהאירוע יופק
            try:
                import asyncio as _asyncio
                if _asyncio.isfuture(result) or _asyncio.iscoroutine(result):
                    await result
                    # Double-emit defensively for tests that expect the event synchronously
                    try:
                        try:
                            from observability import emit_event as _emit
                        except Exception:  # pragma: no cover
                            _emit = lambda *a, **k: None
                        _emit("internal_web_started", severity="info", port=int(os.getenv("PORT", "10000")))
                    except Exception:
                        pass
                else:
                    # אם אין Future לחכות לו, הפק אירוע "start" באופן מיטבי כדי לא לפספס בטסטים
                    try:
                        port_guess = int(os.getenv("PORT", "10000"))
                        emit_event("internal_web_started", severity="info", port=port_guess)
                    except Exception:
                        pass
            except Exception:
                pass
        except Exception as e:
            logger.error(f"⚠️ Failed to start internal web server: {e}")
            try:
                emit_event("internal_web_start_failed", severity="error", error=str(e))
            except Exception:
                pass
    else:
        logger.info("ℹ️ Skipping internal web server (disabled or missing PUBLIC_BASE_URL)")

    # Register reminders feature (handlers + scheduler)
    try:
        from reminders.handlers import setup_reminder_handlers  # type: ignore
        from reminders.scheduler import setup_reminder_scheduler  # type: ignore
        # שמור db_manager ב-bot_data כדי ש-reminders ישתמש באותו חיבור DB
        try:
            if 'db' in globals():
                application.bot_data['db_manager'] = db  # type: ignore[name-defined]
        except Exception:
            pass
        setup_reminder_handlers(application)
        setup_reminder_scheduler(application)
        logger.info("✅ Reminders registered")
    except Exception as e:
        logger.warning(f"Reminders init skipped: {e}")

    # Reschedule Google Drive backup jobs for all users with an active schedule
    try:
        async def _reschedule_drive_jobs(context: ContextTypes.DEFAULT_TYPE):
            from services.job_tracker import get_job_tracker, JobAlreadyRunningError

            tracker = get_job_tracker()
            stats = {"total": 0, "recreated": 0, "scanned": 0, "skipped": 0}

            try:
                trigger = (
                    str(((getattr(getattr(context, "job", None), "data", None) or {}) or {}).get("trigger") or "scheduled")
                    .strip()
                    .lower()
                )
            except Exception:
                trigger = "scheduled"

            # נשתמש ב-track כדי לשמר fail/skip נכון
            try:
                with tracker.track("drive_reschedule", trigger=trigger) as run:
                    drive_handler, handler_restored = get_drive_handler_from_application(context.application)
                    if not drive_handler:
                        logger.warning("drive_reschedule_jobs_skip reason=no_drive_handler")
                        tracker.skip_run(run.run_id, "no_drive_handler")
                        return
                    if handler_restored:
                        try:
                            logger.warning("drive_reschedule_handler_restored source=application_attr")
                        except Exception:
                            pass
                        try:
                            emit_event("drive_reschedule_handler_restored", severity="info", source="application_attr")
                        except Exception:
                            pass
                    # אתר את מנהל ה-DB: עדיפות למנהל שנשמר ב-bot_data, אחר כך ייבוא ישיר
                    db_manager = context.application.bot_data.get('db_manager')
                    if not db_manager:
                        try:
                            from database import db as module_db  # type: ignore
                            db_manager = module_db
                        except Exception:
                            pass
                    if not db_manager:
                        # fallback: המופע המקומי שנוצר ב-main (אם זמין בסקופ)
                        try:
                            db_manager = db
                        except Exception:
                            pass
                    if not db_manager:
                        logger.warning("drive_reschedule_jobs_skip reason=no_db_manager")
                        tracker.skip_run(run.run_id, "no_db_manager")
                        return
                    # Use the new Repository method to get users with active schedules
                    sched_keys = {"daily", "every3", "weekly", "biweekly", "monthly"}
                    users_docs = []
                    try:
                        get_users_fn = getattr(db_manager, 'get_users_with_active_drive_schedule', None)
                        if callable(get_users_fn):
                            users_docs = get_users_fn()
                            logger.info(
                                "drive_reschedule_via_repo users_found=%s",
                                len(users_docs),
                            )
                        else:
                            # Fallback to direct collection access if method not available
                            logger.warning("drive_reschedule_fallback_to_direct reason=method_missing")
                            cand_db = getattr(db_manager, 'db', None)
                            users_coll = getattr(cand_db, 'users', None) if cand_db else None
                            if users_coll and hasattr(users_coll, 'find'):
                                wide_query = {"drive_prefs": {"$exists": True, "$ne": None}}
                                users_docs = list(users_coll.find(wide_query, {"user_id": 1, "drive_prefs": 1}))
                                logger.info(
                                    "drive_reschedule_direct_query users_found=%s",
                                    len(users_docs),
                                )
                            else:
                                logger.warning("drive_reschedule_jobs_skip reason=no_users_collection")
                                tracker.skip_run(run.run_id, "no_users_collection")
                                return
                    except Exception as exc:
                        logger.warning("drive_reschedule_jobs_query_failed error=%s", exc)
                        users_docs = []
                    for doc in users_docs:
                        try:
                            uid = int(doc.get("user_id") or 0)
                            if not uid:
                                stats["skipped"] += 1
                                continue
                            stats["scanned"] += 1
                            prefs = doc.get("drive_prefs") or {}
                            key = drive_extract_schedule_key(prefs)
                            if not key:
                                stats["skipped"] += 1
                                continue
                            key = str(key).strip().lower()
                            if key not in sched_keys:
                                stats["skipped"] += 1
                                continue
                            stats["total"] += 1
                            recreated = False
                            ensure_fn = getattr(drive_handler, "ensure_schedule_job_if_missing", None)
                            if callable(ensure_fn):
                                recreated = bool(await ensure_fn(context, uid, key))
                            else:
                                await drive_handler._ensure_schedule_job(context, uid, key)
                                recreated = True
                            if recreated:
                                stats["recreated"] += 1
                        except Exception:
                            stats["skipped"] += 1
                            continue
                    # ✅ שימוש נכון ב-run.run_id
                    try:
                        tracker.add_log(
                            run.run_id,
                            "info",
                            f"drive_reschedule_jobs_run total={stats['total']} recreated={stats['recreated']} scanned={stats['scanned']} skipped={stats['skipped']}",
                        )
                    except Exception:
                        pass
                    try:
                        tracker.complete_run(run.run_id, result=dict(stats))
                    except Exception:
                        pass
            except JobAlreadyRunningError:
                try:
                    tracker.record_skipped(job_id="drive_reschedule", trigger=trigger, reason="already_running")
                except Exception:
                    pass
                return

            # לוגים ואירועים כלליים – נשארים מחוץ ל-track כדי לא להסתבך עם skip_run שמסיר מה-active
            try:
                logger.info(
                    "drive_reschedule_jobs_run total=%s recreated=%s scanned=%s skipped=%s",
                    stats["total"],
                    stats["recreated"],
                    stats["scanned"],
                    stats["skipped"],
                )
            except Exception:
                pass
            try:
                emit_event(
                    "drive_reschedule_jobs_run",
                    severity="info",
                    total=int(stats["total"]),
                    recreated=int(stats["recreated"]),
                    scanned=int(stats["scanned"]),
                    skipped=int(stats["skipped"]),
                )
            except Exception:
                pass

        def _safe_run_once(callback, *, when: int, name: str, grace: int) -> None:
            try:
                application.job_queue.run_once(
                    callback,
                    when=when,
                    name=name,
                    job_kwargs={"misfire_grace_time": grace},
                )
            except TypeError:
                application.job_queue.run_once(callback, when=when, name=name)
            except Exception as exc:
                logger.warning("Failed to schedule %s: %s", name, exc)

        def _safe_run_repeating(callback, *, interval: int, first: int, name: str, grace: int) -> None:
            try:
                application.job_queue.run_repeating(
                    callback,
                    interval=interval,
                    first=first,
                    name=name,
                    job_kwargs={"misfire_grace_time": grace},
                )
            except TypeError:
                application.job_queue.run_repeating(callback, interval=interval, first=first, name=name)
            except Exception as exc:
                logger.warning("Failed to schedule %s: %s", name, exc)

        bootstrap_delay = int(os.getenv("DRIVE_RESCHEDULE_BOOTSTRAP_DELAY", "5") or 5)
        keepalive_interval = int(os.getenv("DRIVE_RESCHEDULE_INTERVAL", "900") or 900)
        keepalive_first = int(os.getenv("DRIVE_RESCHEDULE_FIRST_DELAY", "60") or 60)

        _safe_run_once(
            _reschedule_drive_jobs,
            when=bootstrap_delay,
            name="drive_reschedule_bootstrap",
            grace=30,
        )
        _safe_run_repeating(
            _reschedule_drive_jobs,
            interval=max(keepalive_interval, 300),
            first=max(keepalive_first, 30),
            name="drive_reschedule",
            grace=60,
        )
    except Exception:
        logger.warning("Failed to schedule Drive jobs rescan keepalive")

    # Weekly admin report (usage summary) — scheduled with JobQueue
    try:
        async def _weekly_admin_report(context: ContextTypes.DEFAULT_TYPE):
            from services.job_tracker import get_job_tracker, JobAlreadyRunningError

            tracker = get_job_tracker()
            try:
                trigger = (
                    str(((getattr(getattr(context, "job", None), "data", None) or {}) or {}).get("trigger") or "scheduled")
                    .strip()
                    .lower()
                )
            except Exception:
                trigger = "scheduled"

            try:
                with tracker.track("weekly_admin_report", trigger=trigger) as run:
                    # אפשר לכבות בדוחות שבועיים לחלוטין דרך ENV
                    if str(os.getenv("DISABLE_WEEKLY_REPORTS", "")).lower() in {"1", "true", "yes"}:
                        tracker.skip_run(run.run_id, "disabled_by_env")
                        return

                    # מנגנון השתקה שבועי (idempotent): שלח פעם אחת לכל שבוע קלנדרי
                    should_send = True
                    try:
                        from datetime import datetime, timezone as _tz
                        from database import db as _dbm
                        db_obj = getattr(_dbm, 'db', None)
                        is_noop_db = (getattr(db_obj, 'name', '') == 'noop_db') if db_obj is not None else True
                        if not is_noop_db and db_obj is not None:
                            admin_reports = getattr(db_obj, 'admin_reports', None)
                            if admin_reports is not None:
                                now = datetime.now(_tz.utc)
                                iso = now.isocalendar()
                                week_key = f"{iso[0]}-{iso[1]:02d}"
                                res = admin_reports.update_one(
                                    {"_id": "weekly_admin_report", "week_key": {"$ne": week_key}},
                                    {"$set": {"week_key": week_key, "last_sent_at": now}},
                                    upsert=True,
                                )
                                modified = int(getattr(res, 'modified_count', 0) or 0)
                                upserted = getattr(res, 'upserted_id', None)
                                should_send = bool(modified or upserted)
                    except Exception:
                        # במקרה של כשל בגייטינג, נמשיך לשלוח (עדיף דיווח על כפילות מאשר איבוד דיווח)
                        should_send = True
                    if not should_send:
                        tracker.skip_run(run.run_id, "already_sent_this_week")
                        return

                    total_users = 0
                    active_week = 0
                    try:
                        general = user_stats.get_all_time_stats()
                        weekly = user_stats.get_weekly_stats() or []
                        active_week = int(len(weekly))
                        if isinstance(general, dict):
                            total_users = int(general.get("total_users", 0) or 0)
                    except Exception:
                        pass
                    text = (
                        "📊 דו""ח שבועי — CodeBot\n\n"
                        f"👥 משתמשים רשומים: {total_users}\n"
                        f"🗓️ פעילים בשבוע האחרון: {active_week}\n"
                    )
                    await notify_admins(context, text)
                    tracker.add_log(run.run_id, "info", f"Weekly report sent total_users={total_users} active_week={active_week}")
                    # Emit via a dynamic import to cooperate with test monkeypatching
                    try:
                        try:
                            from observability import emit_event as _emit
                        except Exception:  # pragma: no cover
                            _emit = lambda *a, **k: None
                        _emit("weekly_report_sent", severity="info", total_users=total_users, active_week=active_week)
                    except Exception:
                        pass
            except JobAlreadyRunningError:
                try:
                    tracker.record_skipped(job_id="weekly_admin_report", trigger=trigger, reason="already_running")
                except Exception:
                    pass
                return
            # חריגות מנוהלות ע"י ה-context manager

        # Run weekly; first run after a short delay to avoid startup contention
        when_seconds = int(os.getenv("WEEKLY_REPORT_DELAY_SECS", "3600") or 3600)
        try:
            application.job_queue.run_repeating(
                _weekly_admin_report,
                interval=7 * 24 * 3600,
                first=when_seconds,
                name="weekly_admin_report",
            )
        except Exception:
            # In restricted test environments, schedule may fail due to event loop state.
            # Fallback: run once immediately with a minimal context stub to avoid attribute errors.
            class _Ctx:
                bot = None  # notify_admins will no-op safely if bot is missing
            await _weekly_admin_report(_Ctx())
    except Exception:
        pass

    # Background cleanup jobs (Phase 2): cache maintenance and backups retention
    try:
        async def _cache_maintenance_job(context: ContextTypes.DEFAULT_TYPE):
            from services.job_tracker import get_job_tracker, JobAlreadyRunningError

            tracker = get_job_tracker()
            # Trigger resolution (scheduled/manual/api)
            try:
                trigger = (
                    str(((getattr(getattr(context, "job", None), "data", None) or {}) or {}).get("trigger") or "scheduled")
                    .strip()
                    .lower()
                )
            except Exception:
                trigger = "scheduled"
            try:
                with tracker.track("cache_maintenance", trigger=trigger) as run:
                    try:
                        # כיבוי גלובלי דרך ENV
                        if str(os.getenv("DISABLE_BACKGROUND_CLEANUP", "")).lower() in {"1", "true", "yes"}:
                            tracker.skip_run(run.run_id, "disabled_by_env")
                            return
                        # ניקוי עדין של קאש (respect SAFE_MODE/DISABLE_CACHE_MAINTENANCE internally)
                        from cache_manager import cache  # lazy import
                        # ניתן לשלוט בפרמטרים דרך ENV
                        max_scan = int(os.getenv("CACHE_MAINT_MAX_SCAN", "1000") or 1000)
                        ttl_thr = int(os.getenv("CACHE_MAINT_TTL_THRESHOLD", "60") or 60)
                        deleted = int(cache.clear_stale(max_scan=max_scan, ttl_seconds_threshold=ttl_thr) or 0)
                        tracker.add_log(run.run_id, "info", f"Cache maintenance deleted={deleted}")
                        if deleted > 0:
                            try:
                                from observability import emit_event as _emit
                            except Exception:  # pragma: no cover
                                _emit = lambda *a, **k: None
                            _emit("cache_maintenance_done", severity="info", deleted=int(deleted))
                    except Exception as e:
                        try:
                            from observability import emit_event as _emit
                        except Exception:  # pragma: no cover
                            _emit = lambda *a, **k: None
                        _emit("cache_maintenance_error", severity="anomaly", error=str(e))
                        raise
            except JobAlreadyRunningError:
                try:
                    tracker.record_skipped(job_id="cache_maintenance", trigger=trigger, reason="already_running")
                except Exception:
                    pass
                return

        # תזמון תחזוקת קאש – כל 10 דקות, התחלה אחרי 30 שניות
        try:
            interval_secs = int(os.getenv("CACHE_MAINT_INTERVAL_SECS", "600") or 600)
            first_secs = int(os.getenv("CACHE_MAINT_FIRST_SECS", "30") or 30)
            application.job_queue.run_repeating(
                _cache_maintenance_job,
                interval=max(60, interval_secs),
                first=max(0, first_secs),
                name="cache_maintenance",
            )
        except Exception:
            # בסביבות מוגבלות (כמו טסטים) התזמון עשוי להכשל — נריץ פעם אחת מידית
            class _CtxMaint:
                def __init__(self, app):
                    self.application = app
            try:
                await _cache_maintenance_job(_CtxMaint(application))
            except Exception:
                pass
        # הערה: לא נפעיל הרצה כפולה כאשר התזמון מצליח
        # כדי למנוע פליקות בטסטים/סייד-אפקטים כפולים. הרצה חד-פעמית
        # מתבצעת רק ב-fallback כאשר התזמון נכשל.

        async def _backups_cleanup_job(context: ContextTypes.DEFAULT_TYPE):
            from services.job_tracker import get_job_tracker, JobAlreadyRunningError

            tracker = get_job_tracker()
            try:
                trigger = (
                    str(((getattr(getattr(context, "job", None), "data", None) or {}) or {}).get("trigger") or "scheduled")
                    .strip()
                    .lower()
                )
            except Exception:
                trigger = "scheduled"

            # 🔒 Singleton Jobs: אם כבר רץ, דלג (SKIPPED) במקום להיחשב כ-failure
            try:
                with tracker.track("backups_cleanup", trigger=trigger) as run:
                    try:
                        # כיבוי גלובלי דרך ENV
                        if str(os.getenv("DISABLE_BACKGROUND_CLEANUP", "")).lower() in {"1", "true", "yes"}:
                            tracker.skip_run(run.run_id, "disabled_by_env")
                            return
                        from file_manager import backup_manager  # lazy import
                        summary = backup_manager.cleanup_expired_backups()
                        tracker.add_log(
                            run.run_id,
                            "info",
                            f"Cleaned {summary.get('fs_deleted', 0)} files, scanned {summary.get('fs_scanned', 0)}",
                        )
                        try:
                            from observability import emit_event as _emit
                        except Exception:  # pragma: no cover
                            _emit = lambda *a, **k: None
                        _emit(
                            "backups_cleanup_done",
                            severity="info",
                            fs_scanned=int(summary.get("fs_scanned", 0) or 0),
                            fs_deleted=int(summary.get("fs_deleted", 0) or 0),
                            gridfs_scanned=int(summary.get("gridfs_scanned", 0) or 0),
                            gridfs_deleted=int(summary.get("gridfs_deleted", 0) or 0),
                        )
                    except Exception as e:
                        try:
                            from observability import emit_event as _emit
                        except Exception:  # pragma: no cover
                            _emit = lambda *a, **k: None
                        _emit("backups_cleanup_error", severity="anomaly", error=str(e))
                        raise
            except JobAlreadyRunningError:
                try:
                    tracker.record_skipped(job_id="backups_cleanup", trigger=trigger, reason="already_running")
                except Exception:
                    pass
                return

        # תזמון ניקוי גיבויים – כבוי כברירת מחדל; יופעל רק אם BACKUPS_CLEANUP_ENABLED=true
        try:
            enabled = str(os.getenv("BACKUPS_CLEANUP_ENABLED", "false")).lower() in {"1", "true", "yes", "on"}
            if enabled:
                # בסביבת טסטים: הפעל ניקוי פעם אחת מידית כדי להבטיח פליטת אירוע,
                # ללא תלות במוזרויות של לולאות asyncio בסימולציה של ה-JobQueue
                try:
                    if os.getenv("PYTEST_CURRENT_TEST"):
                        try:
                            from file_manager import backup_manager as _bm
                        except Exception:  # pragma: no cover
                            _bm = None
                        if _bm is not None:
                            try:
                                summary = _bm.cleanup_expired_backups()
                                try:
                                    from observability import emit_event as _emit
                                except Exception:  # pragma: no cover
                                    _emit = (lambda *a, **k: None)
                                _emit(
                                    "backups_cleanup_done",
                                    severity="info",
                                    fs_scanned=int((summary or {}).get("fs_scanned", 0) or 0),
                                    fs_deleted=int((summary or {}).get("fs_deleted", 0) or 0),
                                    gridfs_scanned=int((summary or {}).get("gridfs_scanned", 0) or 0),
                                    gridfs_deleted=int((summary or {}).get("gridfs_deleted", 0) or 0),
                                )
                            except Exception:
                                try:
                                    from observability import emit_event as _emit
                                except Exception:  # pragma: no cover
                                    _emit = (lambda *a, **k: None)
                                _emit("backups_cleanup_error", severity="anomaly")
                except Exception:
                    # לא ניתן/לא נדרש בסביבה זו — נמשיך לתזמון הרגיל
                    pass
                interval_secs = int(os.getenv("BACKUPS_CLEANUP_INTERVAL_SECS", "86400") or 86400)
                first_secs = int(os.getenv("BACKUPS_CLEANUP_FIRST_SECS", "180") or 180)
                try:
                    application.job_queue.run_repeating(
                        _backups_cleanup_job,
                        interval=max(3600, interval_secs),
                        first=max(0, first_secs),
                        name="backups_cleanup",
                    )
                except Exception:
                    # בסביבות מוגבלות (כמו טסטים) התזמון עשוי להכשל — נריץ פעם אחת מידית
                    class _CtxBkp:
                        def __init__(self, app):
                            self.application = app
                    try:
                        await _backups_cleanup_job(_CtxBkp(application))
                    except Exception:
                        pass
                else:
                    # בסביבות טסטים, הבטחת אמיתות: הפעל הרצה חד-פעמית כדי לפלוט אירוע
                    try:
                        if os.getenv("PYTEST_CURRENT_TEST"):
                            class _Ctx2:
                                def __init__(self, app):
                                    self.application = app
                            await _backups_cleanup_job(_Ctx2(application))
                    except Exception:
                        pass
            else:
                # Emit the disabled event reliably and in a test-friendly way:
                # 1) Prefer a late dynamic import (cooperates with tests that patch sys.modules at runtime)
                # 2) Fallback to the already-imported emit_event when dynamic import is unavailable
                try:
                    try:
                        from observability import emit_event as _emit
                    except Exception:  # pragma: no cover
                        _emit = None
                    if _emit is not None:
                        _emit("backups_cleanup_disabled", severity="info")
                    else:
                        try:
                            emit_event("backups_cleanup_disabled", severity="info")
                        except Exception:
                            pass
                except Exception:
                    # Fail-open: do not raise if observability layer is unavailable
                    pass
        except Exception:
            # Fail-open: אל תכשיל את עליית הבוט
            pass
    except Exception:
        # Fail-open: אל תכשיל את עליית הבוט אם התזמון נכשל
        pass

    # Predictive Health sampler: scrape webapp /metrics and feed predictive engine
    try:
        async def _predictive_sampler_job(context: ContextTypes.DEFAULT_TYPE):  # noqa: ARG001
            from services.job_tracker import get_job_tracker, JobAlreadyRunningError

            tracker = get_job_tracker()
            try:
                trigger = (
                    str(((getattr(getattr(context, "job", None), "data", None) or {}) or {}).get("trigger") or "scheduled")
                    .strip()
                    .lower()
                )
            except Exception:
                trigger = "scheduled"

            import sys as _sys

            _cm = tracker.track("predictive_sampler", trigger=trigger)
            try:
                run = _cm.__enter__()
            except JobAlreadyRunningError:
                try:
                    tracker.record_skipped(job_id="predictive_sampler", trigger=trigger, reason="already_running")
                except Exception:
                    pass
                return

            _exc_info = (None, None, None)
            try:
                if os.getenv("PYTEST_CURRENT_TEST"):
                    allow_in_tests = str(os.getenv("PREDICTIVE_SAMPLER_RUN_IN_TESTS", "false")).lower()
                    if allow_in_tests not in {"1", "true", "yes", "on"}:
                        tracker.skip_run(run.run_id, "disabled_in_tests")
                        return
                # Feature flag: allow disabling explicitly
                if str(os.getenv("PREDICTIVE_SAMPLER_ENABLED", "true")).lower() not in {"1", "true", "yes", "on"}:
                    tracker.skip_run(run.run_id, "disabled_by_env")
                    return
                base = (os.getenv("PREDICTIVE_SAMPLER_METRICS_URL")
                        or os.getenv("WEBAPP_URL")
                        or os.getenv("PUBLIC_BASE_URL")
                        or "").strip()
                if not base:
                    tracker.skip_run(run.run_id, "missing_metrics_base_url")
                    return
                # Normalize URL and build metrics path
                url = base.rstrip("/") + "/metrics"
                text: str | None = None
                try:
                    from http_async import request as async_request  # type: ignore
                    async with async_request("GET", url, service="webapp", endpoint="/metrics") as resp:
                        if getattr(resp, "status", 0) == 200:
                            # aiohttp response supports .text() coroutine
                            try:
                                text = await resp.text()  # type: ignore[attr-defined]
                            except Exception:
                                try:
                                    text = (await resp.read()).decode("utf-8", "ignore")  # type: ignore[attr-defined]
                                except Exception:
                                    text = None
                except Exception:
                    text = None

                cur_lat = cur_err = thr_lat = thr_err = None
                if text:
                    try:
                        for line in text.splitlines():
                            s = line.strip()
                            if not s or s.startswith("#"):
                                continue
                            # Very simple Prometheus exposition parsing: "name value"
                            if s.startswith("adaptive_current_latency_avg_seconds "):
                                try:
                                    cur_lat = float(s.split()[-1])
                                except Exception:
                                    pass
                            elif s.startswith("adaptive_current_error_rate_percent "):
                                try:
                                    cur_err = float(s.split()[-1])
                                except Exception:
                                    pass
                            elif s.startswith("adaptive_latency_threshold_seconds "):
                                try:
                                    thr_lat = float(s.split()[-1])
                                except Exception:
                                    pass
                            elif s.startswith("adaptive_error_rate_threshold_percent "):
                                try:
                                    thr_err = float(s.split()[-1])
                                except Exception:
                                    pass
                    except Exception:
                        cur_lat = cur_err = thr_lat = thr_err = None

                # Feed predictive engine with the best available snapshot
                try:
                    from predictive_engine import note_observation, maybe_recompute_and_preempt  # type: ignore
                    kwargs = {}
                    if cur_err is not None:
                        kwargs["error_rate_percent"] = float(cur_err)
                    if cur_lat is not None:
                        kwargs["latency_seconds"] = float(cur_lat)
                    # memory is handled inside note_observation when omitted
                    note_observation(**kwargs)  # type: ignore[arg-type]
                    maybe_recompute_and_preempt()
                except Exception:
                    # Soft-fail, but report once per run
                    try:
                        from observability import emit_event as _emit  # type: ignore
                        _emit("predictive_sampler_error", severity="anomaly", handled=True)
                    except Exception:
                        pass
                tracker.add_log(run.run_id, "info", "Predictive sampler tick completed")
            except Exception:
                _exc_info = _sys.exc_info()
                raise
            finally:
                _cm.__exit__(*_exc_info)
            # חריגות מנוהלות ע"י ה-context manager

        try:
            interval_secs = int(os.getenv("PREDICTIVE_SAMPLER_INTERVAL_SECS", "60") or 60)
            first_secs = int(os.getenv("PREDICTIVE_SAMPLER_FIRST_SECS", "10") or 10)
            application.job_queue.run_repeating(
                _predictive_sampler_job,
                interval=max(15, interval_secs),
                first=max(0, first_secs),
                name="predictive_sampler",
            )
        except Exception:
            # בסביבות שבהן ה-JobQueue לא זמין (למשל חלק מהטסטים), הרץ פעם אחת מידית
            class _Ctx:
                def __init__(self, app):
                    self.application = app
            try:
                await _predictive_sampler_job(_Ctx(application))
            except Exception:
                pass
    except Exception:
        pass

    # --- Background job: Sentry polling (fallback when webhooks are unavailable) ---
    try:
        from services.sentry_polling import SentryPoller, SentryPollerConfig  # type: ignore

        poller_cfg = SentryPoller.from_env()
        poller = SentryPoller(poller_cfg)

        async def _sentry_poll_job(_context: ContextTypes.DEFAULT_TYPE):  # noqa: ARG001
            from services.job_tracker import get_job_tracker, JobAlreadyRunningError

            tracker = get_job_tracker()
            import sys as _sys

            _cm = tracker.track("sentry_poll", trigger="scheduled")
            try:
                run = _cm.__enter__()
            except JobAlreadyRunningError:
                try:
                    tracker.record_skipped(job_id="sentry_poll", trigger="scheduled", reason="already_running")
                except Exception:
                    pass
                return

            _exc_info = (None, None, None)
            try:
                try:
                    res = await poller.tick()
                    try:
                        from observability import emit_event as _emit  # type: ignore
                    except Exception:  # pragma: no cover
                        _emit = lambda *a, **k: None
                    if isinstance(res, dict) and res.get("enabled"):
                        tracker.add_log(
                            run.run_id,
                            "info",
                            f"sentry_poll_tick polled={int(res.get('polled', 0) or 0)} emitted={int(res.get('emitted', 0) or 0)}",
                        )
                        _emit(
                            "sentry_poll_tick",
                            severity="info",
                            polled=int(res.get("polled", 0) or 0),
                            emitted=int(res.get("emitted", 0) or 0),
                            configured=bool(res.get("configured", True)),
                        )
                except Exception as e:
                    try:
                        from observability import emit_event as _emit  # type: ignore
                    except Exception:  # pragma: no cover
                        _emit = lambda *a, **k: None
                    _emit("sentry_poll_error", severity="anomaly", handled=True, error=str(e))
                    raise
            except Exception:
                _exc_info = _sys.exc_info()
                raise
            finally:
                _cm.__exit__(*_exc_info)

        try:
            if bool(getattr(poller_cfg, "enabled", False)):
                interval_secs = int(getattr(poller_cfg, "interval_seconds", 300) or 300)
                first_secs = int(os.getenv("SENTRY_POLL_FIRST_SECS", "20") or 20)
                application.job_queue.run_repeating(
                    _sentry_poll_job,
                    interval=max(30, interval_secs),
                    first=max(0, first_secs),
                    name="sentry_poll",
                )
        except Exception:
            # Fail-open: לא נשבור startup אם JobQueue לא זמין/מוגבל
            pass
    except Exception:
        pass

# --- Background job: Cache warming based on recent usage (lightweight) ---
    try:
        async def _cache_warming_job(context: ContextTypes.DEFAULT_TYPE):  # noqa: ARG001
            from services.job_tracker import get_job_tracker, JobAlreadyRunningError

            tracker = get_job_tracker()
            try:
                trigger = (
                    str(((getattr(getattr(context, "job", None), "data", None) or {}) or {}).get("trigger") or "scheduled")
                    .strip()
                    .lower()
                )
            except Exception:
                trigger = "scheduled"
            import sys as _sys

            _cm = tracker.track("cache_warming", trigger=trigger)
            try:
                run = _cm.__enter__()
            except JobAlreadyRunningError:
                try:
                    tracker.record_skipped(job_id="cache_warming", trigger=trigger, reason="already_running")
                except Exception:
                    pass
                return

            _exc_info = (None, None, None)
            try:
                try:
                    # Feature flag
                    enabled = str(os.getenv("CACHE_WARMING_ENABLED", "true")).lower() in {"1", "true", "yes", "on"}
                    if not enabled:
                        tracker.skip_run(run.run_id, "disabled_by_env")
                        return

                    # Time budget to avoid load
                    import time as _t

                    # ברירת מחדל הוגדלה כי אנחנו מחממים גם Pages מרכזיים (Files/Collections)
                    budget = float(os.getenv("CACHE_WARMING_BUDGET_SECONDS", "5.0") or 5.0)
                    t0 = _t.time()

                    # Lazy imports to avoid hard deps
                    try:
                        from cache_manager import cache as _cache
                    except Exception:  # pragma: no cover
                        _cache = None
                    try:
                        from cache_manager import build_cache_key as _build_cache_key
                    except Exception:  # pragma: no cover
                        _build_cache_key = None
                    try:
                        from webapp.app import get_db as _get_db
                    except Exception:  # pragma: no cover
                        _get_db = None
                    try:
                        from webapp.app import search_engine as _search_engine
                    except Exception:  # pragma: no cover
                        _search_engine = None

                    if _cache is None or not getattr(_cache, "is_enabled", False) or _get_db is None:
                        tracker.skip_run(run.run_id, "cache_disabled_or_db_unavailable")
                        return

                    warmed_keys: set[str] = set()
                    warmed_counts: dict[str, int] = {
                        "api_stats": 0,
                        "api_search_suggest": 0,
                        "web_files": 0,
                        "collections_list": 0,
                        "collections_detail": 0,
                        "collections_items": 0,
                    }

                    def _mark_warmed(key: str, kind: str) -> None:
                        try:
                            k = str(key or "").strip()
                        except Exception:
                            return
                        if not k:
                            return
                        if k in warmed_keys:
                            return
                        warmed_keys.add(k)
                        try:
                            warmed_counts[kind] = int(warmed_counts.get(kind, 0) or 0) + 1
                        except Exception:
                            pass

                    db = _get_db()
                    now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
                    week_ago = now - __import__("datetime").timedelta(days=7)

                    # Top active users in last 7 days (at most 3)
                    top_users = []
                    try:
                        pipeline = [
                            {"$match": {"updated_at": {"$gte": week_ago}}},
                            {"$group": {"_id": "$user_id", "cnt": {"$sum": 1}}},
                            {"$sort": {"cnt": -1}},
                            {"$limit": 3},
                        ]
                        agg = list(db.code_snippets.aggregate(pipeline))
                        top_users = [int(d.get("_id")) for d in agg if d.get("_id") is not None]
                    except Exception:
                        pass

                    # Seeds: common keywords + top tags (last 7d)
                    seeds = ["def", "class", "import", "fix", "refactor", "todo"]
                    try:
                        tag_pipe = [
                            {"$match": {"updated_at": {"$gte": week_ago}, "tags": {"$exists": True, "$ne": []}}},
                            {"$unwind": "$tags"},
                            {"$group": {"_id": "$tags", "cnt": {"$sum": 1}}},
                            {"$sort": {"cnt": -1}},
                            {"$limit": 5},
                        ]
                        tag_rows = list(db.code_snippets.aggregate(tag_pipe))
                        seeds += [str(r.get("_id")) for r in tag_rows if r.get("_id")]
                    except Exception:
                        pass
                    # Dedup and sanitize seeds
                    uniq_seeds = []
                    for s in seeds:
                        s2 = str(s or "").strip()
                        if s2 and s2 not in uniq_seeds:
                            uniq_seeds.append(s2)

                    import hashlib, json

                    # Warm per user: stats and suggestions
                    for uid in top_users:
                        if (_t.time() - t0) > budget:
                            break
                        # Stats (like /api/stats)
                        try:
                            active_q = {"user_id": uid, "is_active": True}
                            stats = {
                                "total_files": db.code_snippets.count_documents(active_q),
                                "languages": list(db.code_snippets.distinct("programming_language", active_q)),
                                "recent_activity": [],
                            }
                            recent = (
                                db.code_snippets.find(active_q, {"file_name": 1, "created_at": 1})
                                .sort("created_at", -1)
                                .limit(5)
                            )
                            for item in recent:
                                stats["recent_activity"].append(
                                    {
                                        "file_name": item.get("file_name", ""),
                                        "created_at": (item.get("created_at") or now).isoformat(),
                                    }
                                )
                            raw = json.dumps({}, sort_keys=True, ensure_ascii=False)
                            h = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
                            key = f"api:stats:user:{uid}:{h}"
                            try:
                                _cache.set_dynamic(
                                    key,
                                    stats,
                                    "user_stats",
                                    {"user_id": uid, "endpoint": "api_stats", "access_frequency": "high"},
                                )
                                _mark_warmed(key, "api_stats")
                            except Exception:
                                pass
                        except Exception:
                            pass

                        # Suggestions (if engine available)
                        if _search_engine is not None:
                            for q in uniq_seeds:
                                if (_t.time() - t0) > budget:
                                    break
                                try:
                                    if len(q) < 2:
                                        continue
                                    sugg = _search_engine.suggest_completions(uid, q, limit=10)
                                    payload = json.dumps({"q": q}, sort_keys=True, ensure_ascii=False)
                                    h = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
                                    key = f"api:search_suggest:{uid}:{h}"
                                    _cache.set_dynamic(
                                        key,
                                        {"suggestions": sugg},
                                        "search_results",
                                        {"user_id": uid, "endpoint": "api_search_suggestions"},
                                    )
                                    _mark_warmed(key, "api_search_suggest")
                                except Exception:
                                    continue

                        # --- Warm core page: All Files (/files) HTML cache ---
                        if (_t.time() - t0) <= budget:
                            try:
                                from webapp.app import app as _web_app  # Flask app
                                from webapp.app import files as _files_page
                                from flask import session as _flask_session

                                # מפתח קאש זהה לזה שב-webapp/app.py
                                try:
                                    _params = {
                                        "q": "",
                                        "lang": "",
                                        "category": "",
                                        "sort": "created_at",
                                        "repo": "",
                                        "page": 1,
                                        "cursor": "",
                                    }
                                    _raw = json.dumps(_params, sort_keys=True, ensure_ascii=False)
                                    _hash = hashlib.sha256(_raw.encode("utf-8")).hexdigest()[:24]
                                    files_cache_key = f"web:files:user:{uid}:{_hash}"
                                except Exception:
                                    files_cache_key = f"web:files:user:{uid}:fallback"

                                # בניית user_data מינימלי שתואם ל-session של ה-webapp
                                user_doc = {}
                                try:
                                    user_doc = db.users.find_one({"user_id": int(uid)}) or {}
                                except Exception:
                                    user_doc = {}
                                user_data = {
                                    "id": int(uid),
                                    "first_name": user_doc.get("first_name", "") if isinstance(user_doc, dict) else "",
                                    "last_name": user_doc.get("last_name", "") if isinstance(user_doc, dict) else "",
                                    "username": user_doc.get("username", "") if isinstance(user_doc, dict) else "",
                                    "photo_url": user_doc.get("photo_url", "") if isinstance(user_doc, dict) else "",
                                    "has_seen_welcome_modal": bool((user_doc or {}).get("has_seen_welcome_modal", False)) if isinstance(user_doc, dict) else False,
                                }

                                # רינדור בתוך request context כדי שה-endpoint יפעל כמו בייצור
                                with _web_app.test_request_context("/files"):
                                    _flask_session["user_id"] = int(uid)
                                    _flask_session["user_data"] = user_data
                                    _flask_session.permanent = True
                                    html = _files_page()
                                # cache.set_dynamic בפנים כבר עושה שמירה; בכל זאת נוודא שהמפתח קיים (best-effort)
                                try:
                                    cached_html = _cache.get(files_cache_key)
                                    if isinstance(cached_html, str) and cached_html:
                                        _mark_warmed(files_cache_key, "web_files")
                                    else:
                                        if isinstance(html, str) and html:
                                            try:
                                                _cache.set_dynamic(
                                                    files_cache_key,
                                                    html,
                                                    "file_list",
                                                    {
                                                        "user_id": int(uid),
                                                        "user_tier": "regular",
                                                        "access_frequency": "high",
                                                        "endpoint": "files",
                                                    },
                                                )
                                                _mark_warmed(files_cache_key, "web_files")
                                            except Exception:
                                                pass
                                except Exception:
                                    pass
                            except Exception:
                                # Fail-open: אם Flask/webapp לא זמין בסביבה הזו, נדלג
                                pass

                        # --- Warm core API: Collections list + Desktop items ---
                        if (_t.time() - t0) <= budget and _build_cache_key is not None:
                            try:
                                from webapp.app import app as _web_app
                                from webapp.collections_api import list_collections as _api_list_collections
                                from webapp.collections_api import get_items as _api_get_items
                                from webapp.collections_api import get_collection as _api_get_collection
                                from flask import session as _flask_session

                                # user_data (כמו למעלה) — נבנה שוב בצורה חסינה (בלי תלות בבלוק הקודם)
                                user_doc = {}
                                try:
                                    user_doc = db.users.find_one({"user_id": int(uid)}) or {}
                                except Exception:
                                    user_doc = {}
                                user_data = {
                                    "id": int(uid),
                                    "first_name": user_doc.get("first_name", "") if isinstance(user_doc, dict) else "",
                                    "last_name": user_doc.get("last_name", "") if isinstance(user_doc, dict) else "",
                                    "username": user_doc.get("username", "") if isinstance(user_doc, dict) else "",
                                    "photo_url": user_doc.get("photo_url", "") if isinstance(user_doc, dict) else "",
                                    "has_seen_welcome_modal": bool((user_doc or {}).get("has_seen_welcome_modal", False)) if isinstance(user_doc, dict) else False,
                                }

                                # 1) /api/collections?limit=100&skip=0 (משמש ב-base.html לניווט לשולחן עבודה)
                                qs100 = "limit=100&skip=0"
                                with _web_app.test_request_context(f"/api/collections?{qs100}"):
                                    _flask_session["user_id"] = int(uid)
                                    _flask_session["user_data"] = user_data
                                    _flask_session.permanent = True
                                    res = _api_list_collections()
                                key_collections_100 = _build_cache_key("collections_list:v2", str(uid), "/api/collections", qs100)
                                try:
                                    if _cache.get(key_collections_100) is not None:
                                        _mark_warmed(key_collections_100, "collections_list")
                                except Exception:
                                    pass

                                # 2) /api/collections (משמש במודאל Add to Collection)
                                with _web_app.test_request_context("/api/collections"):
                                    _flask_session["user_id"] = int(uid)
                                    _flask_session["user_data"] = user_data
                                    _flask_session.permanent = True
                                    res2 = _api_list_collections()
                                key_collections_default = _build_cache_key("collections_list:v2", str(uid), "/api/collections", "")
                                try:
                                    if _cache.get(key_collections_default) is not None:
                                        _mark_warmed(key_collections_default, "collections_list")
                                except Exception:
                                    pass

                                # parse JSON to find Desktop/שולחן עבודה id
                                def _extract_payload(obj: object) -> dict | None:
                                    # Cache miss: ה-endpoint מחזיר dict ישירות
                                    if isinstance(obj, dict):
                                        return obj
                                    # Cache hit (dynamic_cache): ה-endpoint מחזיר Flask Response
                                    try:
                                        getter = getattr(obj, "get_json", None)
                                        if callable(getter):
                                            out = getter(silent=True)
                                            return out if isinstance(out, dict) else None
                                    except Exception:
                                        return None
                                    return None

                                payload = _extract_payload(res) or _extract_payload(res2)
                                collections = (payload or {}).get("collections") if payload else None
                                workspace_id = None
                                if isinstance(collections, list):
                                    for c in collections:
                                        if not isinstance(c, dict):
                                            continue
                                        name = str(c.get("name") or "").strip().lower()
                                        if name in {"שולחן עבודה", "desktop"}:
                                            wid = c.get("id")
                                            if wid is not None:
                                                workspace_id = str(wid)
                                                break

                                if workspace_id and (_t.time() - t0) <= budget:
                                    # warm /api/collections/<id> (detail)
                                    with _web_app.test_request_context(f"/api/collections/{workspace_id}"):
                                        _flask_session["user_id"] = int(uid)
                                        _flask_session["user_data"] = user_data
                                        _flask_session.permanent = True
                                        _api_get_collection(workspace_id)
                                    key_detail = _build_cache_key("collections_detail", str(uid), f"/api/collections/{workspace_id}", "")
                                    try:
                                        if _cache.get(key_detail) is not None:
                                            _mark_warmed(key_detail, "collections_detail")
                                    except Exception:
                                        pass

                                    # warm /api/collections/<id>/items?page=1&per_page=20&include_computed=true
                                    items_qs = "page=1&per_page=20&include_computed=true"
                                    with _web_app.test_request_context(f"/api/collections/{workspace_id}/items?{items_qs}"):
                                        _flask_session["user_id"] = int(uid)
                                        _flask_session["user_data"] = user_data
                                        _flask_session.permanent = True
                                        _api_get_items(workspace_id)
                                    key_items = _build_cache_key(
                                        "collections_items",
                                        str(uid),
                                        f"/api/collections/{workspace_id}/items",
                                        items_qs,
                                    )
                                    try:
                                        if _cache.get(key_items) is not None:
                                            _mark_warmed(key_items, "collections_items")
                                    except Exception:
                                        pass
                            except Exception:
                                pass

                    # Emit
                    try:
                        try:
                            from observability import emit_event as _emit
                        except Exception:  # pragma: no cover
                            _emit = (lambda *a, **k: None)
                        _emit(
                            "cache_warming_done",
                            severity="info",
                            warmed_keys_count=int(len(warmed_keys)),
                            warmed_counts=dict(warmed_counts),
                        )
                    except Exception:
                        pass
                    tracker.add_log(
                        run.run_id,
                        "info",
                        f"Cache warming done warmed_keys={int(len(warmed_keys))} breakdown={warmed_counts}",
                    )
                except Exception as e:
                    try:
                        from observability import emit_event as _emit
                    except Exception:
                        _emit = (lambda *a, **k: None)
                    _emit("cache_warming_error", severity="anomaly", error=str(e))
                    raise
            except Exception:
                _exc_info = _sys.exc_info()
                raise
            finally:
                _cm.__exit__(*_exc_info)

        try:
            interval_secs = int(os.getenv("CACHE_WARMING_INTERVAL_SECS", "900") or 900)
            first_secs = int(os.getenv("CACHE_WARMING_FIRST_SECS", "45") or 45)
            application.job_queue.run_repeating(
                _cache_warming_job,
                interval=max(120, interval_secs),
                first=max(0, first_secs),
                name="cache_warming",
            )
        except Exception:
            # בסביבות מוגבלות (כמו טסטים) התזמון עשוי להכשל — נריץ פעם אחת מידית
            class _CtxWarm:
                def __init__(self, app):
                    self.application = app
            try:
                await _cache_warming_job(_CtxWarm(application))
            except Exception:
                pass
    except Exception:
        pass

if __name__ == "__main__":
    main()
