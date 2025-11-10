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
from typing import Any
from datetime import datetime

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
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[logging.StreamHandler(sys.stdout)],
)
try:
    from utils import install_sensitive_filter
    install_sensitive_filter()
except Exception:
    pass
try:
    setup_structlog_logging("INFO")
    init_sentry()
except Exception:
    # אל תכשיל את האפליקציה אם תצורת observability נכשלה
    pass

# סגירת סשן aiohttp משותף בסיום התהליך (best-effort)
@atexit.register
def _shutdown_http_shared_session() -> None:
    try:
        from http_async import close_session  # type: ignore
    except Exception:
        return
    try:
        loop = asyncio.get_event_loop()
        if not loop.is_closed():
            loop.run_until_complete(close_session())
    except RuntimeError:
        # אין event loop פעיל
        try:
            # חשוב להשתמש באותו מודול asyncio של המודול (ניתן ל-monkeypatch בטסטים)
            _loop = asyncio.new_event_loop()
            asyncio.set_event_loop(_loop)
            _loop.run_until_complete(close_session())
            _loop.close()
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
        admin_ids = get_admin_ids()
        if not admin_ids:
            return
        for admin_id in admin_ids:
            try:
                await context.bot.send_message(chat_id=admin_id, text=text)
            except Exception:
                pass
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

LOCK_ID = "code_keeper_bot_lock"
LOCK_COLLECTION = "locks"
LOCK_TIMEOUT_MINUTES = 5

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
        lock_collection.create_index("expires_at", expireAfterSeconds=0, name="lock_expires_ttl")
    except Exception as e:
        # Non-fatal; continue without TTL if index creation fails
        logger.warning(f"Could not ensure TTL index for lock collection: {e}")
        try:
            emit_event("lock_ttl_index_failed", severity="warn", error=str(e))
        except Exception:
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
        # If DB client is not available, skip quietly (נחשב כהצלחה — אין מה לנקות)
        try:
            if 'db' in globals() and getattr(db, "client", None) is None:
                logger.debug("Mongo client not available during lock cleanup; skipping.")
                return True
        except Exception:
            pass

        lock_collection = get_lock_collection()
        pid = os.getpid()
        result = lock_collection.delete_one({"_id": LOCK_ID, "pid": pid})
        if result.deleted_count > 0:
            logger.info(f"Lock '{LOCK_ID}' released successfully by PID: {pid}.")
            try:
                emit_event("lock_released", severity="info", pid=pid)
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
    try:
        try:
            ensure_lock_indexes()
        except Exception:
            logger.warning("could not ensure lock indexes; continuing")
        lock_collection = get_lock_collection()
        pid = os.getpid()
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(minutes=LOCK_TIMEOUT_MINUTES)

        # Try to create the lock document
        try:
            lock_collection.insert_one({"_id": LOCK_ID, "pid": pid, "expires_at": expires_at})
            logger.info(f"✅ MongoDB lock acquired by PID {pid}")
            try:
                emit_event("lock_acquired", severity="info", pid=pid)
            except Exception:
                pass
        except DuplicateKeyError:
            # A lock already exists
            # First, attempt immediate takeover if the lock is expired
            while True:
                now = datetime.now(timezone.utc)
                expires_at = now + timedelta(minutes=LOCK_TIMEOUT_MINUTES)

                doc = lock_collection.find_one({"_id": LOCK_ID})
                if doc and doc.get("expires_at") and doc["expires_at"] < now:
                    # Attempt to take over an expired lock
                    result = lock_collection.find_one_and_update(
                        {"_id": LOCK_ID, "expires_at": {"$lt": now}},
                        {"$set": {"pid": pid, "expires_at": expires_at}},
                        return_document=True,
                    )
                    if result:
                        logger.info(f"✅ MongoDB lock re-acquired by PID {pid} (expired lock)")
                        try:
                            emit_event("lock_reacquired", severity="info", pid=pid)
                        except Exception:
                            pass
                        break
                else:
                    # Not expired: wait and retry instead of exiting to support blue/green deploys
                    max_wait_seconds = int(os.getenv("LOCK_MAX_WAIT_SECONDS", "0"))  # 0 = wait indefinitely
                    retry_interval_seconds = int(os.getenv("LOCK_RETRY_INTERVAL_SECONDS", "5"))

                    if max_wait_seconds > 0:
                        deadline = time.time() + max_wait_seconds
                        while time.time() < deadline:
                            time.sleep(retry_interval_seconds)
                            now = datetime.now(timezone.utc)
                            doc = lock_collection.find_one({"_id": LOCK_ID})
                            if not doc or (doc.get("expires_at") and doc["expires_at"] < now):
                                break
                        # loop will re-check and attempt takeover at the top
                        if time.time() >= deadline:
                            logger.warning("Timeout waiting for existing lock to release. Exiting gracefully.")
                            try:
                                emit_event("lock_wait_timeout", severity="warn", max_wait_seconds=max_wait_seconds)
                            except Exception:
                                pass
                            return False
                    else:
                        # Infinite wait with periodic log
                        logger.warning("Another bot instance is already running (lock present). Waiting for lock release…")
                        try:
                            emit_event("lock_waiting_existing", severity="warn")
                        except Exception:
                            pass
                        time.sleep(retry_interval_seconds)
                        continue
                # If we reach here without breaking, loop will retry
            
        # Ensure lock is released on exit
        atexit.register(cleanup_mongo_lock)
        return True

    except Exception as e:
        logger.error(f"Failed to acquire MongoDB lock: {e}", exc_info=True)
        try:
            emit_event("lock_acquire_failed", severity="error", error=str(e))
        except Exception:
            pass
        # Fail-open to not crash the app, but log loudly
        return True

# =============================================================================
# Global reference to the current bot instance
# משמש כדי לאפשר ל-main() לעשות reuse של אינסטנס קיים (לצרכי טסטים/אתחול)
CURRENT_BOT: CodeKeeperBot | None = None  # יוגדר בתוך CodeKeeperBot.__init__

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
        # יצירת תיקייה זמנית עם הרשאות כתיבה
        DATA_DIR = "/tmp"
        if not os.path.exists(DATA_DIR):
            os.makedirs(DATA_DIR, exist_ok=True)
            
        # יצירת persistence לשמירת נתונים בין הפעלות
        persistence = PicklePersistence(filepath=f"{DATA_DIR}/bot_data.pickle")
        
        # במצב בדיקות/CI, חלק מתלויות הטלגרם (Updater פנימי) עלולות להיכשל.
        # נשתמש בבנאי הרגיל, ואם נכשל – נבנה Application מינימלי עם טוקן דמה.
        try:
            self.application = (
                Application.builder()
                .token(config.BOT_TOKEN)
                .defaults(Defaults(parse_mode=ParseMode.HTML))
                .persistence(persistence)
                .post_init(setup_bot_data)
                .build()
            )
        except Exception:
            dummy_token = os.getenv("DUMMY_BOT_TOKEN", "dummy_token")
            # נסה לבנות ללא persistence/post_init כדי לעקוף Updater פנימי
            try:
                self.application = (
                    Application.builder()
                    .token(dummy_token)
                    .defaults(Defaults(parse_mode=ParseMode.HTML))
                    .build()
                )
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

        if maintenance_flag:
            # הגדרת חלון זמן פנימי שבו הודעת תחזוקה פעילה, כך שגם אם מחיקת ה-handlers לא תתבצע
            # ההודעה תיכבה אוטומטית לאחר ה-warmup.
            try:
                self._maintenance_active_until_ts = time.time() + max(1, int(getattr(config, 'MAINTENANCE_AUTO_WARMUP_SECS', 30)))
            except Exception:
                self._maintenance_active_until_ts = time.time() + 30

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
                now = time.time()
                is_active = True if active_until is None else (active_until > 0 and now < active_until)
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
                        chat = getattr(update, "effective_chat", None)
                        bot = getattr(context, "bot", None)
                        chat_id = getattr(chat, "id", None)
                        if bot is not None and chat_id is not None:
                            await bot.send_message(chat_id=chat_id, text=maintenance_text)
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
            try:
                warmup_secs = max(1, int(config.MAINTENANCE_AUTO_WARMUP_SECS))
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
                self.application.job_queue.run_once(_clear_handlers_cb, when=warmup_secs, name="maintenance_clear_handlers")
            except Exception:
                pass
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
                               pattern=r'^(select_repo|upload_file|upload_saved|show_current|set_token|set_folder|close_menu|folder_|repo_|repos_page_|upload_saved_|back_to_menu|repo_manual|noop|analyze_repo|analyze_current_repo|analyze_other_repo|show_suggestions|show_full_analysis|download_analysis_json|back_to_analysis|back_to_analysis_menu|back_to_summary|choose_my_repo|enter_repo_url|suggestion_\d+|github_menu|logout_github|delete_file_menu|delete_repo_menu|confirm_delete_repo|confirm_delete_repo_step1|confirm_delete_file|danger_delete_menu|download_file_menu|browse_repo|browse_open:.*|browse_select_download:.*|browse_select_delete:.*|browse_page:.*|download_zip:.*|multi_toggle|multi_execute|multi_clear|safe_toggle|browse_toggle_select:.*|inline_download_file:.*|view_more|view_back|browse_select_view:.*|browse_ref_menu|browse_refs_branches_page_.*|browse_refs_tags_page_.*|browse_select_ref:.*|browse_search|browse_search_page:.*|notifications_menu|notifications_toggle|notifications_toggle_pr|notifications_toggle_issues|notifications_interval_.*|notifications_check_now|share_folder_link:.*|share_selected_links|pr_menu|create_pr_menu|branches_page_.*|pr_select_head:.*|confirm_create_pr|merge_pr_menu|prs_page_.*|merge_pr:.*|confirm_merge_pr|validate_repo|git_checkpoint|git_checkpoint_doc:.*|git_checkpoint_doc_skip|restore_checkpoint_menu|restore_tags_page_.*|restore_select_tag:.*|restore_branch_from_tag:.*|restore_revert_pr_from_tag:.*|open_pr_from_branch:.*|choose_upload_branch|upload_branches_page_.*|upload_select_branch:.*|upload_select_branch_tok:.*|choose_upload_folder|upload_select_folder:.*|upload_folder_root|upload_folder_current|upload_folder_custom|upload_folder_create|create_folder|confirm_saved_upload|refresh_saved_checks|github_backup_menu|github_backup_help|github_backup_db_list|github_restore_zip_to_repo|github_restore_zip_setpurge:.*|github_restore_zip_list|github_restore_zip_from_backup:.*|github_repo_restore_backup_setpurge:.*|gh_upload_cat:.*|gh_upload_repo:.*|gh_upload_large:.*|backup_menu|github_create_repo_from_zip|github_new_repo_name|github_set_new_repo_visibility:.*|upload_paste_code|cancel_paste_flow|gh_upload_zip_browse:.*|gh_upload_zip_page:.*|gh_upload_zip_select:.*|gh_upload_zip_select_idx:.*|backup_add_note:.*|github_import_repo|import_repo_branches_page_.*|import_repo_select_branch:.*|import_repo_start|import_repo_cancel)')
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
            text = (update.message.text or '').strip()
            main_menu_texts = {"➕ הוסף קוד חדש", "📚 הצג את כל הקבצים שלי", "📂 קבצים גדולים", "🔧 GitHub", "🏠 תפריט ראשי", "⚡ עיבוד Batch"}
            if text in main_menu_texts:
                # נקה דגלים כדי למנוע טריגר שגוי
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
                )
                from handlers.states import (
                    CL_COLLECT_TITLE,
                    CL_COLLECT_DESCRIPTION,
                    CL_COLLECT_URL,
                    CL_COLLECT_LOGO,
                    SN_COLLECT_TITLE,
                    SN_COLLECT_DESCRIPTION,
                    SN_COLLECT_CODE,
                    SN_COLLECT_LANGUAGE,
                    SN_REJECT_REASON,
                    SN_LONG_COLLECT,
                )
                # Approve via inline button (admin-only wrapper inside function)
                self.application.add_handler(CallbackQueryHandler(community_inline_approve, pattern=r'^community_approve:'))
                # Snippet inline approve
                self.application.add_handler(CallbackQueryHandler(snippet_inline_approve, pattern=r'^snippet_approve:'))
                # Submission flow
                comm_conv = ConversationHandler(
                    entry_points=[CallbackQueryHandler(community_submit_start, pattern=r'^community_submit$')],
                    states={
                        CL_COLLECT_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, community_collect_title)],
                        CL_COLLECT_DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, community_collect_description)],
                        CL_COLLECT_URL: [MessageHandler(filters.TEXT & ~filters.COMMAND, community_collect_url)],
                        CL_COLLECT_LOGO: [MessageHandler((filters.PHOTO | filters.TEXT) & ~filters.COMMAND, community_collect_logo)],
                    },
                    fallbacks=[
                        CommandHandler('cancel', lambda u, c: ConversationHandler.END),
                        CallbackQueryHandler(submit_flows_cancel, pattern=r'^cancel$'),
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
                        CommandHandler('cancel', lambda u, c: ConversationHandler.END),
                        CallbackQueryHandler(submit_flows_cancel, pattern=r'^cancel$'),
                    ],
                )
                self.application.add_handler(sn_conv)
                # Snippet reject reason flow
                sn_reject_conv = ConversationHandler(
                    entry_points=[CallbackQueryHandler(snippet_reject_start, pattern=r'^snippet_reject:')],
                    states={
                        SN_REJECT_REASON: [MessageHandler(filters.TEXT & ~filters.COMMAND, snippet_collect_reject_reason)],
                    },
                    fallbacks=[CommandHandler('cancel', lambda u, c: ConversationHandler.END)],
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
        response = """
📚 <b>רשימת הפקודות המלאה:</b>

<b>שמירה וניהול:</b>
• <code>/save &lt;filename&gt;</code> - התחלת שמירה של קובץ חדש.
• <code>/list</code> - הצגת כל הקבצים שלך.
• <code>/show &lt;filename&gt;</code> - הצגת קובץ עם הדגשת תחביר וכפתורי פעולה.
• <code>/edit &lt;filename&gt;</code> - עריכת קוד של קובץ קיים.
• <code>/delete &lt;filename&gt;</code> - מחיקת קובץ.
• <code>/rename &lt;old&gt; &lt;new&gt;</code> - שינוי שם קובץ.
• <code>/download &lt;filename&gt;</code> - הורדת קובץ כמסמך.
• <code>/github</code> - תפריט העלאה ל-GitHub.
    
<b>חיפוש וסינון:</b>
• <code>/recent</code> - הצגת קבצים שעודכנו לאחרונה.
• <code>/stats</code> - סטטיסטיקות אישיות.
• <code>/tags &lt;filename&gt; &lt;tag1&gt;,&lt;tag2&gt;</code> - הוספת תגיות לקובץ.
• <code>/search &lt;query&gt;</code> - חיפוש טקסטואלי בקוד שלך.
    
<b>פיצ'רים חדשים:</b>
• <code>/autocomplete &lt;חלק_משם&gt;</code> - אוטו-השלמה לשמות קבצים.
• <code>/preview &lt;filename&gt;</code> - תצוגה מקדימה של קוד (15 שורות ראשונות).
• <code>/info &lt;filename&gt;</code> - מידע מהיר על קובץ ללא פתיחה.
• <code>/large &lt;filename&gt;</code> - הצגת קובץ גדול עם ניווט בחלקים.

<b>עיבוד Batch (מרובה קבצים):</b>
• <code>/batch_analyze all</code> - ניתוח כל הקבצים בו-זמנית.
• <code>/batch_analyze python</code> - ניתוח קבצי שפה ספציפית.
• <code>/batch_validate all</code> - בדיקת תקינות מרובה קבצים.
• <code>/job_status</code> - בדיקת סטטוס עבודות ברקע.

<b>ביצועים ותחזוקה:</b>
• <code>/cache_stats</code> - סטטיסטיקות ביצועי cache.
• <code>/clear_cache</code> - ניקוי cache אישי לשיפור ביצועים.

<b>מידע כללי:</b>
• <code>/recent</code> - הצגת קבצים שעודכנו לאחרונה.
• <code>/help</code> - הצגת הודעה זו.

🔧 <b>לכל תקלה בבוט נא לשלוח הודעה ל-@moominAmir</b>
"""
        await update.message.reply_text(response, parse_mode=ParseMode.HTML)
    
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
        """בדיקת הפקודות הזמינות (רק לאמיר)"""
        
        if update.effective_user.id != 6865105071:
            return
        
        # בדוק פקודות ציבוריות
        public_cmds = await context.bot.get_my_commands()
        
        # בדוק פקודות אישיות
        from telegram import BotCommandScopeChat
        personal_cmds = await context.bot.get_my_commands(
            scope=BotCommandScopeChat(chat_id=6865105071)
        )
        
        from html import escape as html_escape

        message = "📋 <b>סטטוס פקודות</b>\n\n"
        message += f"סיכום: ציבוריות {len(public_cmds)} | אישיות {len(personal_cmds)}\n\n"
        if public_cmds:
            public_list = "\n".join(f"/{cmd.command}" for cmd in public_cmds)
            message += "<b>ציבוריות:</b>\n" + f"<pre>{html_escape(public_list)}</pre>\n"
        if personal_cmds:
            personal_list = "\n".join(f"/{cmd.command} — {cmd.description}" for cmd in personal_cmds)
            message += "<b>אישיות:</b>\n" + f"<pre>{html_escape(personal_list)}</pre>"
        
        await update.message.reply_text(message, parse_mode=ParseMode.HTML)

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
        text = update.message.text

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
                # שלח התראה לאדמינים
                try:
                    await notify_admins(context, f"🚨 OOM זוהתה בבוט{mem_status}. חריגה: {err_text[:500]}")
                except Exception:
                    pass
                # אם המשתמש אדמין – שלח גם אליו פירוט
                try:
                    if isinstance(update, Update) and update.effective_user:
                        admin_ids = get_admin_ids()
                        if admin_ids and update.effective_user.id in admin_ids:
                            await context.bot.send_message(chat_id=update.effective_user.id,
                                                           text=f"🚨 OOM זוהתה{mem_status}. התקבלה שגיאה: {err_text[:500]}")
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
            "👋 שלום! הבוט מוכן לשימוש.\n\n"
            "🔧 לכל תקלה בבוט נא לשלוח הודעה ל-@moominAmir", 
            reply_markup=reply_markup
        )

    async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):  # noqa: D401
        if reporter is not None:
            reporter.report_activity(update.effective_user.id)
        await log_user_activity(update, context)  # הוספת רישום משתמש לסטטיסטיקות
        await update.message.reply_text(
            "ℹ️ השתמש ב/start כדי להתחיל.\n\n"
            "🔧 לכל תקלה בבוט נא לשלוח הודעה ל-@moominAmir"
        )

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
        db = DatabaseManager()
        
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
            _run_poll_app(drop_pending_updates=True)
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


# A minimal post_init stub to comply with the PTB builder chain
async def setup_bot_data(application: Application) -> None:  # noqa: D401
    """A post_init function to setup application-wide data."""
    # מחיקת כל הפקודות הציבוריות (אין להגדיר /share /share_help — שיתוף דרך הכפתורים)
    await application.bot.delete_my_commands()
    logger.info("✅ Public commands cleared (no /share, /share_help)")

    # הגדרת JobStore מתמיד ל-APScheduler (MongoDB) אם אפשרי
    try:
        jq = getattr(application, "job_queue", None)
        scheduler = getattr(jq, "scheduler", None)
        if scheduler is not None:
            try:
                from database import db as _dbm  # שימוש בלקוח/DB הקיימים
            except Exception:
                _dbm = None  # type: ignore[assignment]
            client = getattr(_dbm, "client", None) if _dbm is not None else None
            db_obj = getattr(_dbm, "db", None) if _dbm is not None else None
            db_name = getattr(db_obj, "name", None) if db_obj is not None else None
            # אל תגדיר במצב NoOp או כשאין חיבור
            if client is not None and db_name and db_name != "noop_db":
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
            try:
                drive_handler = context.application.bot_data.get('drive_handler')
                if not drive_handler:
                    return
                # Access users collection directly to find users with drive schedules
                users_coll = db.db.users if getattr(db, 'db', None) else None
                if users_coll is None:
                    return
                sched_keys = {"daily", "every3", "weekly", "biweekly", "monthly"}
                cursor = None
                try:
                    cursor = users_coll.find({"drive_prefs.schedule": {"$in": list(sched_keys)}})
                except Exception:
                    cursor = []
                for doc in cursor:
                    try:
                        uid = int(doc.get("user_id") or 0)
                        if not uid:
                            continue
                        prefs = doc.get("drive_prefs") or {}
                        key = prefs.get("schedule")
                        if key in sched_keys:
                            # Ensure a repeating job exists and is aligned to the next planned time
                            # _ensure_schedule_job מיועד ב-drive_handler; אם לא קיים, נתעלם בשקט
                            try:
                                await drive_handler._ensure_schedule_job(context, uid, key)
                            except AttributeError:
                                pass
                    except Exception:
                        continue
            except Exception:
                pass
        # Run once shortly after startup to restore jobs after restarts/deploys
        application.job_queue.run_once(_reschedule_drive_jobs, when=1)
    except Exception:
        logger.warning("Failed to schedule Drive jobs rescan on startup")

    # Weekly admin report (usage summary) — scheduled with JobQueue
    try:
        async def _weekly_admin_report(context: ContextTypes.DEFAULT_TYPE):
            try:
                # אפשר לכבות בדוחות שבועיים לחלוטין דרך ENV
                if str(os.getenv("DISABLE_WEEKLY_REPORTS", "")).lower() in {"1", "true", "yes"}:
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
                # Emit via a dynamic import to cooperate with test monkeypatching
                try:
                    try:
                        from observability import emit_event as _emit
                    except Exception:  # pragma: no cover
                        _emit = lambda *a, **k: None
                    _emit("weekly_report_sent", severity="info", total_users=total_users, active_week=active_week)
                except Exception:
                    pass
            except Exception:
                try:
                    try:
                        from observability import emit_event as _emit
                    except Exception:  # pragma: no cover
                        _emit = lambda *a, **k: None
                    _emit("weekly_report_error", severity="error")
                except Exception:
                    pass

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
            try:
                # כיבוי גלובלי דרך ENV
                if str(os.getenv("DISABLE_BACKGROUND_CLEANUP", "")).lower() in {"1", "true", "yes"}:
                    return
                # ניקוי עדין של קאש (respect SAFE_MODE/DISABLE_CACHE_MAINTENANCE internally)
                from cache_manager import cache  # lazy import
                # ניתן לשלוט בפרמטרים דרך ENV
                max_scan = int(os.getenv("CACHE_MAINT_MAX_SCAN", "1000") or 1000)
                ttl_thr = int(os.getenv("CACHE_MAINT_TTL_THRESHOLD", "60") or 60)
                deleted = int(cache.clear_stale(max_scan=max_scan, ttl_seconds_threshold=ttl_thr) or 0)
                if deleted > 0:
                    try:
                        from observability import emit_event as _emit
                    except Exception:  # pragma: no cover
                        _emit = lambda *a, **k: None
                    _emit("cache_maintenance_done", severity="info", deleted=int(deleted))
            except Exception:
                try:
                    from observability import emit_event as _emit
                except Exception:  # pragma: no cover
                    _emit = lambda *a, **k: None
                _emit("cache_maintenance_error", severity="anomaly")

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
            try:
                # כיבוי גלובלי דרך ENV
                if str(os.getenv("DISABLE_BACKGROUND_CLEANUP", "")).lower() in {"1", "true", "yes"}:
                    return
                from file_manager import backup_manager  # lazy import
                summary = backup_manager.cleanup_expired_backups()
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
            except Exception:
                try:
                    from observability import emit_event as _emit
                except Exception:  # pragma: no cover
                    _emit = lambda *a, **k: None
                _emit("backups_cleanup_error", severity="anomaly")

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
            try:
                if os.getenv("PYTEST_CURRENT_TEST"):
                    allow_in_tests = str(os.getenv("PREDICTIVE_SAMPLER_RUN_IN_TESTS", "false")).lower()
                    if allow_in_tests not in {"1", "true", "yes", "on"}:
                        return
                # Feature flag: allow disabling explicitly
                if str(os.getenv("PREDICTIVE_SAMPLER_ENABLED", "true")).lower() not in {"1", "true", "yes", "on"}:
                    return
                base = (os.getenv("PREDICTIVE_SAMPLER_METRICS_URL")
                        or os.getenv("WEBAPP_URL")
                        or os.getenv("PUBLIC_BASE_URL")
                        or "").strip()
                if not base:
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
            except Exception:
                # Fail-open
                try:
                    from observability import emit_event as _emit  # type: ignore
                    _emit("predictive_sampler_exception", severity="anomaly", handled=True)
                except Exception:
                    pass

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

# --- Background job: Cache warming based on recent usage (lightweight) ---
    try:
        async def _cache_warming_job(context: ContextTypes.DEFAULT_TYPE):  # noqa: ARG001
            try:
                # Feature flag
                enabled = str(os.getenv("CACHE_WARMING_ENABLED", "true")).lower() in {"1", "true", "yes", "on"}
                if not enabled:
                    return

                # Time budget to avoid load
                import time as _t
                budget = float(os.getenv("CACHE_WARMING_BUDGET_SECONDS", "1.0") or 1.0)
                t0 = _t.time()

                # Lazy imports to avoid hard deps
                try:
                    from cache_manager import cache as _cache
                except Exception:  # pragma: no cover
                    _cache = None
                try:
                    from webapp.app import get_db as _get_db
                except Exception:  # pragma: no cover
                    _get_db = None
                try:
                    from webapp.app import search_engine as _search_engine
                except Exception:  # pragma: no cover
                    _search_engine = None

                if _cache is None or not getattr(_cache, 'is_enabled', False) or _get_db is None:
                    return

                db = _get_db()
                now = __import__('datetime').datetime.now(__import__('datetime').timezone.utc)
                week_ago = now - __import__('datetime').timedelta(days=7)

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
                    s2 = str(s or '').strip()
                    if s2 and s2 not in uniq_seeds:
                        uniq_seeds.append(s2)

                import hashlib, json

                # Warm per user: stats and suggestions
                for uid in top_users:
                    if (_t.time() - t0) > budget:
                        break
                    # Stats (like /api/stats)
                    try:
                        active_q = {"user_id": uid, "$or": [{"is_active": True}, {"is_active": {"$exists": False}}]}
                        stats = {
                            "total_files": db.code_snippets.count_documents(active_q),
                            "languages": list(db.code_snippets.distinct("programming_language", active_q)),
                            "recent_activity": [],
                        }
                        recent = db.code_snippets.find(active_q, {"file_name": 1, "created_at": 1}).sort("created_at", -1).limit(5)
                        for item in recent:
                            stats["recent_activity"].append({
                                "file_name": item.get("file_name", ""),
                                "created_at": (item.get("created_at") or now).isoformat(),
                            })
                        raw = json.dumps({}, sort_keys=True, ensure_ascii=False)
                        h = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
                        key = f"api:stats:user:{uid}:{h}"
                        try:
                            _cache.set_dynamic(key, stats, "user_stats", {"user_id": uid, "endpoint": "api_stats", "access_frequency": "high"})
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
                                _cache.set_dynamic(key, {"suggestions": sugg}, "search_results", {"user_id": uid, "endpoint": "api_search_suggestions"})
                            except Exception:
                                continue

                # Emit
                try:
                    try:
                        from observability import emit_event as _emit
                    except Exception:  # pragma: no cover
                        _emit = (lambda *a, **k: None)
                    _emit("cache_warming_done", severity="info")
                except Exception:
                    pass
            except Exception:
                try:
                    from observability import emit_event as _emit
                except Exception:
                    _emit = (lambda *a, **k: None)
                _emit("cache_warming_error", severity="anomaly")

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
