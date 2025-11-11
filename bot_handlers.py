"""
פקודות מתקדמות לבוט שומר קבצי קוד
Advanced Bot Handlers for Code Keeper Bot
"""

import asyncio
import hashlib
import os
import io
import logging
import re
import html
import secrets
import telegram.error
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from telegram import (InlineKeyboardButton, InlineKeyboardMarkup, InputFile,
                      Update, ReplyKeyboardMarkup)
from telegram.constants import ParseMode
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes
from telegram.ext import ApplicationHandlerStop

from services import code_service as code_processor
from services.image_generator import CodeImageGenerator
from rate_limiter import RateLimiter
from config import config
from database import CodeSnippet, db
from conversation_handlers import MAIN_KEYBOARD
from pathlib import Path
try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover
    yaml = None  # type: ignore
# Reporter מוזרק בזמן ריצה כדי למנוע יצירה בזמן import
class _NoopReporter:
    def report_activity(self, user_id):
        return None

reporter = _NoopReporter()

def set_activity_reporter(new_reporter):
    global reporter
    reporter = new_reporter or _NoopReporter()
    
# Rate limiter לפיצ'ר יצירת תמונות (10 פעולות בדקה למשתמש)
image_rate_limiter = RateLimiter(max_per_minute=10)

# טעינת קונפיגורציית תמונות (אופציונלי)
def _load_image_config() -> dict:
    try:
        cfg_path = Path(__file__).parent / 'config' / 'image_settings.yaml'
        if yaml is None or not cfg_path.exists():
            return {}
        data = yaml.safe_load(cfg_path.read_text(encoding='utf-8')) or {}
        return dict(data.get('image_generation') or {})
    except Exception:
        return {}

IMAGE_CONFIG = _load_image_config()
import json
try:
    import aiohttp  # for GitHub rate limit check
except Exception:  # pragma: no cover
    aiohttp = None  # type: ignore

# ChatOps helpers: sensitive command throttling and permissions integration
try:
    from chatops.ratelimit import limit_sensitive  # type: ignore
except Exception:  # pragma: no cover
    def limit_sensitive(_name: str):  # type: ignore
        def _decorator(fn):
            return fn
        return _decorator

try:
    from chatops.permissions import (
        admin_required,
        chat_allowlist_required,
        is_admin as _perm_is_admin,
    )  # type: ignore
except Exception:  # pragma: no cover
    _perm_is_admin = None  # type: ignore
    def admin_required(fn):  # type: ignore
        return fn
    def chat_allowlist_required(fn):  # type: ignore
        return fn

logger = logging.getLogger(__name__)

import os as _os

class AdvancedBotHandlers:
    """פקודות מתקדמות של הבוט"""
    
    def __init__(self, application):
        self.application = application
        self.setup_advanced_handlers()
    
    def setup_advanced_handlers(self):
        """הגדרת handlers מתקדמים"""
        
        # פקודות ניהול קבצים
        self.application.add_handler(CommandHandler("show", self.show_command))
        self.application.add_handler(CommandHandler("edit", self.edit_command))
        self.application.add_handler(CommandHandler("delete", self.delete_command))
        # self.application.add_handler(CommandHandler("rename", self.rename_command))
        # self.application.add_handler(CommandHandler("copy", self.copy_command))
        # מועדפים
        self.application.add_handler(CommandHandler("favorite", self.favorite_command))
        self.application.add_handler(CommandHandler("fav", self.favorite_command))  # קיצור דרך
        self.application.add_handler(CommandHandler("favorites", self.favorites_command))
        
        # פקודות גרסאות
        self.application.add_handler(CommandHandler("versions", self.versions_command))
        # self.application.add_handler(CommandHandler("restore", self.restore_command))
        # self.application.add_handler(CommandHandler("diff", self.diff_command))
        
        # פקודות שיתוף
        self.application.add_handler(CommandHandler("share", self.share_command))
        self.application.add_handler(CommandHandler("share_help", self.share_help_command))
        # self.application.add_handler(CommandHandler("export", self.export_command))
        self.application.add_handler(CommandHandler("download", self.download_command))
        # יצירת תמונות מקוד – רישום עמיד: כל פקודה נרשמת בנפרד
        for _cmd, _fn in (
            ("image", self.image_command),
            ("preview", self.preview_command),
            ("image_all", self.image_all_command),
        ):
            try:
                self.application.add_handler(CommandHandler(_cmd, _fn))
            except Exception as e:
                # אל תעצור רישום פקודות אחרות; דווח והמשך
                try:
                    logger.error(f"Failed to register /{_cmd}: {e}")
                except Exception:
                    pass
        
        # פקודות ניתוח
        self.application.add_handler(CommandHandler("analyze", self.analyze_command))
        self.application.add_handler(CommandHandler("validate", self.validate_command))
        # self.application.add_handler(CommandHandler("minify", self.minify_command))
        
        # פקודות ארגון
        self.application.add_handler(CommandHandler("tags", self.tags_command))
        # self.application.add_handler(CommandHandler("languages", self.languages_command))
        self.application.add_handler(CommandHandler("recent", self.recent_command))
        self.application.add_handler(CommandHandler("info", self.info_command))
        self.application.add_handler(CommandHandler("broadcast", self.broadcast_command))
        # פקודת DM למנהלים – שליחת הודעה פרטית עם שימור רווחים (HTML <pre>)
        self.application.add_handler(CommandHandler("dm", self.dm_command))
        # חיפוש
        self.application.add_handler(CommandHandler("search", self.search_command))
        # ChatOps MVP + Stage 2 commands
        self.application.add_handler(CommandHandler(
            "status",
            chat_allowlist_required(admin_required(self.status_command))
        ))
        # Alias for detailed health check via chat (same as /status for now)
        self.application.add_handler(CommandHandler(
            "health",
            chat_allowlist_required(admin_required(self.status_command))
        ))
        self.application.add_handler(CommandHandler(
            "observe",
            chat_allowlist_required(admin_required(self.observe_command))
        ))
        self.application.add_handler(CommandHandler(
            "triage",
            chat_allowlist_required(admin_required(limit_sensitive("triage")(self.triage_command)))
        ))
        # מערכת: מידע ומדדים
        self.application.add_handler(CommandHandler(
            "system_info",
            chat_allowlist_required(admin_required(self.system_info_command))
        ))
        self.application.add_handler(CommandHandler(
            "metrics",
            chat_allowlist_required(admin_required(self.metrics_command))
        ))
        # Observability v6 – Predictive Health
        self.application.add_handler(CommandHandler("predict", self.predict_command))
        # Observability v7 – Prediction accuracy
        self.application.add_handler(CommandHandler("accuracy", self.accuracy_command))
        # פקודת מנהל להצגת קישור ל-Sentry
        self.application.add_handler(CommandHandler(
            "sen",
            chat_allowlist_required(admin_required(self.sentry_command))
        ))
        self.application.add_handler(CommandHandler(
            "errors",
            chat_allowlist_required(admin_required(limit_sensitive("errors")(self.errors_command)))
        ))
        self.application.add_handler(CommandHandler(
            "rate_limit",
            chat_allowlist_required(admin_required(limit_sensitive("rate_limit")(self.rate_limit_command)))
        ))
        # GitHub Backoff controls (admins)
        self.application.add_handler(CommandHandler(
            "enable_backoff",
            chat_allowlist_required(admin_required(limit_sensitive("enable_backoff")(self.enable_backoff_command)))
        ))
        self.application.add_handler(CommandHandler(
            "disable_backoff",
            chat_allowlist_required(admin_required(limit_sensitive("disable_backoff")(self.disable_backoff_command)))
        ))
        self.application.add_handler(CommandHandler(
            "uptime",
            chat_allowlist_required(admin_required(self.uptime_command))
        ))
        self.application.add_handler(CommandHandler(
            "alerts",
            chat_allowlist_required(admin_required(self.alerts_command))
        ))
        # Observability v5 – incident memory
        self.application.add_handler(CommandHandler(
            "incidents",
            chat_allowlist_required(admin_required(self.incidents_command))
        ))

        # ChatOps – Silences management
        self.application.add_handler(CommandHandler(
            "silence",
            chat_allowlist_required(admin_required(limit_sensitive("silence")(self.silence_command)))
        ))
        self.application.add_handler(CommandHandler(
            "unsilence",
            chat_allowlist_required(admin_required(limit_sensitive("unsilence")(self.unsilence_command)))
        ))
        self.application.add_handler(CommandHandler(
            "silences",
            chat_allowlist_required(admin_required(self.silences_command))
        ))
        
        # Callback handlers לכפתורים
        # Guard הגלובלי התשתיתי מתווסף ב-main.py; כאן נשאר רק ה-handler הכללי
        # חשוב: הוספה בקבוצה מאוחרת, כדי לתת עדיפות ל-handlers ספציפיים (למשל מועדפים)
        try:
            self.application.add_handler(CallbackQueryHandler(self.handle_callback_query), group=5)
        except TypeError:
            # סביבת בדיקות עם add_handler ללא פרמטר group
            self.application.add_handler(CallbackQueryHandler(self.handle_callback_query))
        # Handler מוקדם וממוקד לטוגל מועדפים כדי להבטיח קליטה מיידית
        toggle_pattern = r'^(fav_toggle_id:|fav_toggle_tok:)'
        toggle_handler = CallbackQueryHandler(self.handle_callback_query, pattern=toggle_pattern)
        try:
            self.application.add_handler(toggle_handler, group=-5)
        except TypeError:
            self.application.add_handler(toggle_handler)
        except Exception as e:
            logger.error(f"Failed to register favorites toggle CallbackQueryHandler: {e}")
        # Handler ממוקד עם קדימות גבוהה לכפתורי /share
        share_pattern = r'^(share_gist_|share_pastebin_|share_internal_|share_gist_multi:|share_internal_multi:|cancel_share)'
        share_handler = CallbackQueryHandler(self.handle_callback_query, pattern=share_pattern)
        try:
            self.application.add_handler(share_handler, group=-5)
        except TypeError:
            # סביבת בדיקות/סטאב שבה add_handler לא תומך בפרמטר group
            self.application.add_handler(share_handler)
        except Exception as e:
            # אל תבלע חריגות שקטות – דווח ללוג כדי לא לשבור את כפתורי השיתוף
            logger.error(f"Failed to register share CallbackQueryHandler: {e}")
    
    def _get_image_settings(self, context: ContextTypes.DEFAULT_TYPE, file_name: str) -> Dict[str, Any]:
        try:
            settings_map = context.user_data.setdefault('img_settings', {})
            return dict(settings_map.get(file_name) or {})
        except Exception:
            return {}

    def _set_image_setting(self, context: ContextTypes.DEFAULT_TYPE, file_name: str, key: str, value: Any) -> None:
        try:
            settings_map = context.user_data.setdefault('img_settings', {})
            entry = dict(settings_map.get(file_name) or {})
            entry[key] = value
            settings_map[file_name] = entry
        except Exception:
            pass

    # --- Image callbacks tokenization helpers (to stay under Telegram's 64B limit) ---
    def _get_or_create_image_token(self, context: ContextTypes.DEFAULT_TYPE, file_name: str) -> str:
        """Return a short stable token for a file name, storing mapping in user_data.
        We avoid leaking long names into callback_data which has a 64 bytes limit.
        """
        try:
            tokens = context.user_data.setdefault('img_name_by_tok', {})
            reverse = context.user_data.setdefault('img_tok_by_name', {})
            tok = reverse.get(file_name)
            if tok:
                return tok
            # Generate 8-hex token; prefix with 'tok:' when used in callback
            tok = secrets.token_hex(4)
            # Ensure uniqueness
            while tok in tokens:
                tok = secrets.token_hex(4)
            tokens[tok] = file_name
            reverse[file_name] = tok
            return tok
        except Exception:
            # Fallback – if something goes wrong, return sanitized short name tail
            return (file_name or 'file')[-40:]

    def _resolve_image_target(self, context: ContextTypes.DEFAULT_TYPE, suffix: str) -> str:
        """Resolve a callback suffix back to the original file name.
        Supports either a raw file name or a token prefixed with 'tok:'.
        """
        try:
            if suffix.startswith('tok:'):
                token = suffix.split(':', 1)[1]
            else:
                token = suffix
            # Try token lookup first
            name = (context.user_data.get('img_name_by_tok') or {}).get(token)
            if name:
                return str(name)
            # Not a known token – assume it's a direct file name
            return suffix
        except Exception:
            return suffix

    def _make_safe_suffix(self, context: ContextTypes.DEFAULT_TYPE, action_prefix: str, file_name: str) -> str:
        """Return a safe suffix for callback_data for given action.
        If the combined callback would exceed 64 bytes, return a 'tok:<token>' suffix.
        """
        try:
            cb = f"{action_prefix}{file_name}"
            if len(cb.encode('utf-8')) <= 64:
                return file_name
            tok = self._get_or_create_image_token(context, file_name)
            return f"tok:{tok}"
        except Exception:
            return file_name

    async def show_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """הצגת קטע קוד עם הדגשת תחביר"""
        reporter.report_activity(update.effective_user.id)
        user_id = update.effective_user.id
        
        if not context.args:
            await update.message.reply_text(
                "📄 אנא ציין שם קובץ:\n"
                "דוגמה: `/show script.py`",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        file_name = " ".join(context.args)
        file_data = db.get_latest_version(user_id, file_name)
        
        if not file_data:
            await update.message.reply_text(
                f"❌ קובץ `{file_name}` לא נמצא.",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        # קבל את הקוד המקורי בבטחה; ודא שתמיד יש מחרוזת קוד
        code_raw = str((file_data.get('code') or ""))
        language = str((file_data.get('programming_language') or ""))
        try:
            # highlight_code עשוי להחזיר מחרוזת ריקה במקרי קצה — ניפול חזרה לקוד המקורי
            original_code = code_processor.highlight_code(code_raw, language)
        except Exception:
            original_code = code_raw
        if not isinstance(original_code, str) or original_code == "":
            original_code = code_raw
        
        # בצע הימלטות לתוכן הקוד כדי למנוע שגיאות
        escaped_code = html.escape(original_code)
        language_html = html.escape(language)

        # עטוף את הקוד הנקי בתגיות <pre><code> שטלגרם תומך בהן
        response_text = f"""<b>File:</b> <code>{html.escape(str(file_data.get('file_name', file_name)))}</code>
<b>Language:</b> {language_html}

<pre><code>{escaped_code}</code></pre>
"""
        
        # --- מבנה הכפתורים החדש והנקי ---
        file_id = str(file_data.get('_id', file_name))
        # כפתור מועדפים בהתאם למצב הנוכחי
        try:
            is_fav_now = bool(db.is_favorite(user_id, file_name))
        except Exception:
            is_fav_now = False
        fav_text = ("💔 הסר ממועדפים" if is_fav_now else "⭐ הוסף למועדפים")
        # הקפדה על מגבלת 64 בתים ב-callback_data + הימנעות מתווים בעייתיים
        # העדפה ל-ID אם קיים; אחרת טוקן קצר עם מיפוי ב-user_data
        has_id = True
        try:
            _raw_id = file_data.get('_id')
            if _raw_id is None:
                has_id = False
            else:
                file_id_str = str(_raw_id)
        except Exception:
            has_id = False
            file_id_str = ""
        if has_id and (len("fav_toggle_id:") + len(file_id_str)) <= 60:
            fav_cb = f"fav_toggle_id:{file_id_str}"
        else:
            try:
                token = secrets.token_urlsafe(6)
            except Exception:
                token = "t"  # fallback קצר
            # קיצור טוקן לשימוש ב-callback_data ושמירת המיפוי תחת המפתח המקוצר
            short_tok = (token[:24] if isinstance(token, str) else "t")
            try:
                tokens_map = context.user_data.get('fav_tokens') or {}
                tokens_map[short_tok] = file_name
                context.user_data['fav_tokens'] = tokens_map
            except Exception:
                pass
            fav_cb = f"fav_toggle_tok:{short_tok}"

        buttons = [
            [
                InlineKeyboardButton("🗑️ מחיקה", callback_data=f"delete_{file_id}"),
                InlineKeyboardButton("✏️ עריכה", callback_data=f"edit_{file_id}")
            ],
            [
                InlineKeyboardButton("📝 ערוך הערה", callback_data=f"edit_note_{file_id}"),
                InlineKeyboardButton("💾 הורדה", callback_data=f"download_{file_id}")
            ],
            [
                InlineKeyboardButton("🌐 שיתוף", callback_data=f"share_{file_id}")
            ],
            [
                InlineKeyboardButton(fav_text, callback_data=fav_cb)
            ]
        ]
        reply_markup = InlineKeyboardMarkup(buttons)
        # ---------------------------------
        
        await update.message.reply_text(response_text, parse_mode='HTML', reply_markup=reply_markup)

    async def favorite_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """הוספה/הסרה של קובץ מהמועדפים: /favorite <file_name>"""
        reporter.report_activity(update.effective_user.id)
        user_id = update.effective_user.id
        if not context.args:
            await update.message.reply_text(
                "🔖 <b>הוספה/הסרה ממועדפים</b>\n\n"
                "שימוש: <code>/favorite &lt;file_name&gt;</code>\n\n"
                "דוגמה:\n"
                "<code>/favorite config.py</code>\n\n"
                "או שלח <code>/favorites</code> לצפייה בכל המועדפים",
                parse_mode=ParseMode.HTML
            )
            return
        file_name = " ".join(context.args)
        snippet = db.get_latest_version(user_id, file_name)
        if not snippet:
            await update.message.reply_text(
                f"❌ הקובץ <code>{html.escape(file_name)}</code> לא נמצא.\n"
                "שלח <code>/list</code> לרשימת הקבצים שלך.",
                parse_mode=ParseMode.HTML
            )
            return
        new_state = db.toggle_favorite(user_id, file_name)
        # אם המתודה מחזירה None, זו שגיאה
        if new_state is None:
            await update.message.reply_text("❌ שגיאה בעדכון מועדפים. נסה שוב מאוחר יותר.")
            return
        language = snippet.get('programming_language', '') or ''
        emoji = ''
        try:
            from utils import get_language_emoji
            emoji = get_language_emoji(language)
        except Exception:
            emoji = ''
        if new_state:
            msg = (
                f"⭐ <b>נוסף למועדפים!</b>\n\n"
                f"📁 קובץ: <code>{html.escape(file_name)}</code>\n"
                f"{emoji} שפה: {html.escape(language or 'לא ידוע')}\n\n"
                f"💡 גש במהירות עם <code>/favorites</code>"
            )
        else:
            msg = (
                f"💔 <b>הוסר מהמועדפים</b>\n\n"
                f"📁 קובץ: <code>{html.escape(file_name)}</code>\n\n"
                f"ניתן להוסיף שוב מאוחר יותר."
            )
        # כפתורים מהירים
        keyboard = [
            [
                InlineKeyboardButton("📋 הצג קובץ", callback_data=f"view_direct_{file_name}"),
                InlineKeyboardButton("⭐ כל המועדפים", callback_data="favorites_list"),
            ]
        ]
        await update.message.reply_text(msg, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(keyboard))

    async def favorites_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """רשימת המועדפים של המשתמש: /favorites"""
        reporter.report_activity(update.effective_user.id)
        user_id = update.effective_user.id
        favorites = db.get_favorites(user_id, limit=50)
        if not favorites:
            await update.message.reply_text(
                "💭 אין לך מועדפים כרגע.\n"
                "✨ הוסף מועדף ראשון עם <code>/favorite &lt;שם&gt;</code>",
                parse_mode=ParseMode.HTML
            )
            return
        lines = ["⭐ <b>המועדפים שלך</b>"]
        from utils import TimeUtils, get_language_emoji
        for idx, fav in enumerate(favorites[:10], 1):
            fname = fav.get('file_name', '')
            lang = fav.get('programming_language', '')
            rel = ''
            try:
                fa = fav.get('favorited_at') or fav.get('updated_at') or fav.get('created_at')
                if fa:
                    rel = TimeUtils.format_relative_time(fa)
            except Exception:
                rel = ''
            emoji = get_language_emoji(lang)
            line = f"{idx}. {emoji} <code>{html.escape(str(fname))}</code>"
            if rel:
                line += f" • {rel}"
            lines.append(line)
        if len(favorites) > 10:
            lines.append(f"\n➕ ועוד {len(favorites) - 10} קבצים...")
        message = "\n".join(lines)
        # כפתורי קיצור לקבצים (עד 5 ראשונים)
        buttons: list[list[InlineKeyboardButton]] = []
        for fav in favorites[:5]:
            fname = fav.get('file_name', '')
            try:
                latest = db.get_latest_version(user_id, fname) or {}
                fid = str(latest.get('_id') or '')
            except Exception:
                fid = ''
            if fid:
                cb = f"view_direct_id:{fid}"
            else:
                safe_name = (fname[:45] + '...') if len(fname) > 48 else fname
                cb = f"view_direct_{safe_name}"
            buttons.append([InlineKeyboardButton(f"📄 {fname[:20]}", callback_data=cb)])
        # פעולות כלליות
        actions_row = [
            InlineKeyboardButton("📥 ייצוא JSON", callback_data="export_favorites"),
            InlineKeyboardButton("📊 סטטיסטיקה", callback_data="favorites_stats"),
        ]
        if buttons:
            buttons.append(actions_row)
        else:
            buttons = [actions_row]
        # שליחת הודעה ארוכה בצורה בטוחה (פיצול למספר הודעות אם צריך)
        await self._send_long_message(
            update.message,
            message,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(buttons),
        )

        # אם יש יותר מ-10 מועדפים, שלח את השאר כהודעות נוספות — מפוצלות בבטחה
        if len(favorites) > 10:
            rest_lines: List[str] = []
            from utils import get_language_emoji as _gle
            for idx, fav in enumerate(favorites[10:], 11):
                fname = fav.get('file_name', '')
                lang = fav.get('programming_language', '')
                rest_lines.append(f"{idx}. {_gle(lang)} <code>{html.escape(str(fname))}</code>")
            rest_text = "\n".join(rest_lines)
            if rest_text:
                await self._send_long_message(
                    update.message,
                    rest_text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=None,
                )
    
    async def edit_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """עריכת קטע קוד קיים"""
        reporter.report_activity(update.effective_user.id)
        user_id = update.effective_user.id
        
        if not context.args:
            await update.message.reply_text(
                "✏️ אנא ציין שם קובץ לעריכה:\n"
                "דוגמה: `/edit script.py`",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        file_name = " ".join(context.args)
        file_data = db.get_latest_version(user_id, file_name)
        
        if not file_data:
            await update.message.reply_text(
                f"❌ קובץ `{file_name}` לא נמצא.",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        # שמירת מידע לעריכה
        context.user_data['editing_file'] = {
            'file_name': file_name,
            'user_id': user_id,
            'original_data': file_data
        }
        
        await update.message.reply_text(
            f"✏️ **עריכת קובץ:** `{file_name}`\n\n"
            f"**קוד נוכחי:**\n"
            f"```{file_data['programming_language']}\n{file_data['code']}\n```\n\n"
            "🔄 אנא שלח את הקוד החדש:",
            parse_mode=ParseMode.MARKDOWN
        )
    
    async def delete_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """מחיקת קטע קוד"""
        reporter.report_activity(update.effective_user.id)
        user_id = update.effective_user.id
        
        if not context.args:
            await update.message.reply_text(
                "🗑️ אנא ציין שם קובץ למחיקה:\n"
                "דוגמה: `/delete script.py`",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        file_name = " ".join(context.args)
        file_data = db.get_latest_version(user_id, file_name)
        
        if not file_data:
            await update.message.reply_text(
                f"❌ קובץ `{file_name}` לא נמצא.",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        # כפתורי אישור
        keyboard = [
            [
                InlineKeyboardButton("✅ כן, מחק", callback_data=f"confirm_delete_{file_name}"),
                InlineKeyboardButton("❌ ביטול", callback_data="cancel_delete")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"🗑️ **אישור מחיקה**\n\n"
            f"האם אתה בטוח שברצונך למחוק את `{file_name}`?\n"
            f"פעולה זו תמחק את כל הגרסאות של הקובץ ולא ניתן לבטל אותה!",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup
        )
    
    async def versions_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """הצגת כל גרסאות הקובץ"""
        reporter.report_activity(update.effective_user.id)
        user_id = update.effective_user.id
        
        if not context.args:
            await update.message.reply_text(
                "🔢 אנא ציין שם קובץ:\n"
                "דוגמה: `/versions script.py`",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        file_name = " ".join(context.args)
        versions = db.get_all_versions(user_id, file_name)
        
        if not versions:
            await update.message.reply_text(
                f"❌ קובץ `{file_name}` לא נמצא.",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        response = f"🔢 **גרסאות עבור:** `{file_name}`\n\n"
        
        for version_data in versions:
            is_latest = version_data == versions[0]
            status = "🟢 נוכחית" if is_latest else "🔵 ישנה"
            
            response += f"**גרסה {version_data['version']}** {status}\n"
            response += f"📅 {version_data['updated_at'].strftime('%d/%m/%Y %H:%M')}\n"
            response += f"📏 {len(version_data['code'])} תווים\n"
            
            if version_data.get('description'):
                response += f"📝 {version_data['description']}\n"
            
            response += "\n"
        
        # כפתורי פעולה
        keyboard = []
        for version_data in versions[:5]:  # מקסימום 5 גרסאות בכפתורים
            keyboard.append([
                InlineKeyboardButton(
                    f"📄 גרסה {version_data['version']}",
                    callback_data=f"show_version_{file_name}_{version_data['version']}"
                ),
                InlineKeyboardButton(
                    f"🔄 שחזר",
                    callback_data=f"restore_version_{file_name}_{version_data['version']}"
                )
            ])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            response,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup
        )
    
    async def analyze_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """ניתוח מתקדם של קטע קוד"""
        reporter.report_activity(update.effective_user.id)
        user_id = update.effective_user.id
        
        if not context.args:
            await update.message.reply_text(
                "📊 אנא ציין שם קובץ לניתוח:\n"
                "דוגמה: `/analyze script.py`",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        file_name = " ".join(context.args)
        file_data = db.get_latest_version(user_id, file_name)
        
        if not file_data:
            await update.message.reply_text(
                f"❌ קובץ `{file_name}` לא נמצא.",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        code = file_data['code']
        language = file_data['programming_language']
        
        # ניתוח הקוד
        stats = code_processor.get_code_stats(code)
        functions = code_processor.extract_functions(code, language)
        
        response = f"""
📊 **ניתוח קוד עבור:** `{file_name}`

📏 **מדדי גודל:**
• סה"כ שורות: {stats['total_lines']}
• שורות קוד: {stats['code_lines']}
• שורות הערות: {stats['comment_lines']}
• שורות ריקות: {stats['blank_lines']}

📝 **מדדי תוכן:**
• תווים: {stats['characters']}
• מילים: {stats['words']}
• תווים ללא רווחים: {stats['characters_no_spaces']}

🔧 **מבנה קוד:**
• פונקציות: {stats['functions']}
• מחלקות: {stats['classes']}
• ניקוד מורכבות: {stats['complexity_score']}

📖 **קריאות:**
• ניקוד קריאות: {stats.get('readability_score', 'לא זמין')}
        """
        
        if functions:
            response += f"\n🔧 **פונקציות שנמצאו:**\n"
            for func in functions[:10]:  # מקסימום 10 פונקציות
                response += f"• `{func['name']}()` (שורה {func['line']})\n"
            
            if len(functions) > 10:
                response += f"• ועוד {len(functions) - 10} פונקציות...\n"
        
        # הצעות לשיפור
        suggestions = []
        
        if stats['comment_lines'] / stats['total_lines'] < 0.1:
            suggestions.append("💡 הוסף יותר הערות לקוד")
        
        if stats['functions'] == 0 and stats['total_lines'] > 20:
            suggestions.append("💡 שקול לחלק את הקוד לפונקציות")
        
        if stats['complexity_score'] > stats['total_lines']:
            suggestions.append("💡 הקוד מורכב - שקול פישוט")
        
        if suggestions:
            response += f"\n💡 **הצעות לשיפור:**\n"
            for suggestion in suggestions:
                response += f"• {suggestion}\n"
        
        await update.message.reply_text(response, parse_mode=ParseMode.MARKDOWN)

    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/status – בדיקות בריאות בסיסיות: DB, Redis, GitHub API"""
        try:
            # הרשאות: אדמינים בלבד
            try:
                user_id = int(getattr(update.effective_user, 'id', 0) or 0)
            except Exception:
                user_id = 0
            if not self._is_admin(user_id):
                await update.message.reply_text("❌ פקודה זמינה למנהלים בלבד")
                return
            # DB status - בדיקת פינג אמיתית ל-MongoDB
            # הערה: ניגש לפונקציה דרך המודול כדי לאפשר monkeypatch יציב בטסטים
            try:
                import importlib
                _bh = importlib.import_module(__name__)
                _checker = getattr(_bh, 'check_db_connection', check_db_connection)
            except Exception:
                _checker = check_db_connection
            db_ok = await _checker()

            # Redis status
            redis_ok = False
            try:
                from cache_manager import cache as _cache
                redis_ok = bool(getattr(_cache, 'is_enabled', False))
            except Exception:
                redis_ok = False

            # GitHub API rate limit (optional)
            gh_status = "unknown"
            try:
                if os.getenv("GITHUB_TOKEN"):
                    from http_async import request as async_request
                    async with async_request(
                        "GET",
                        "https://api.github.com/rate_limit",
                        headers={"Authorization": f"token {os.getenv('GITHUB_TOKEN')}"},
                        service="github",
                        endpoint="rate_limit",
                    ) as resp:
                        data = await resp.json()
                        remaining = int(data.get("resources", {}).get("core", {}).get("remaining", 0))
                        limit = int(data.get("resources", {}).get("core", {}).get("limit", 0))
                        used_pct = (100 - int(remaining * 100 / max(limit, 1))) if limit else 0
                        gh_status = f"{remaining}/{limit} ({used_pct}% used)"
            except Exception:
                gh_status = "error"

            def _emoji(ok: bool) -> str:
                return "🟢" if ok else "🔴"

            # Sentry status (DSN/API) – לא חושפים סודות
            sentry_dsn_set = bool(os.getenv("SENTRY_DSN"))
            sentry_api_ready = bool(os.getenv("SENTRY_AUTH_TOKEN") and (os.getenv("SENTRY_ORG") or os.getenv("SENTRY_ORG_SLUG")))

            # OTEL exporter – best-effort: קיים endpoint ידוע או מודול otel זמין בסביבה
            otel_ready = False
            try:
                otel_ready = bool(
                    os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
                    or os.getenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT")
                    or os.getenv("OTEL_EXPORTER_OTLP_METRICS_ENDPOINT")
                )
                if not otel_ready:
                    import importlib
                    _ = importlib.import_module("opentelemetry")  # type: ignore
                    otel_ready = True
            except Exception:
                otel_ready = False

            text = (
                f"📋 Status\n"
                f"DB: {_emoji(db_ok)}\n"
                f"Redis: {_emoji(redis_ok)}\n"
                f"GitHub: {gh_status}\n"
                f"Sentry DSN: {_emoji(bool(sentry_dsn_set))}\n"
                f"Sentry API: {_emoji(bool(sentry_api_ready))}\n"
                f"OTEL Exporter: {_emoji(bool(otel_ready))}\n"
            )
            await update.message.reply_text(text)
        except Exception as e:
            await update.message.reply_text(f"❌ שגיאה ב-/status: {html.escape(str(e))}")

    async def sentry_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/sen – מחזיר קישור ל-Sentry (מנהלים בלבד)"""
        try:
            try:
                user_id = int(getattr(update.effective_user, 'id', 0) or 0)
            except Exception:
                user_id = 0
            if not self._is_admin(user_id):
                await update.message.reply_text("❌ פקודה זמינה למנהלים בלבד")
                return

            # עדיפות ל-ENV ישיר של קישור דאשבורד
            dashboard = os.getenv("SENTRY_DASHBOARD_URL") or os.getenv("SENTRY_PROJECT_URL")
            dsn = os.getenv("SENTRY_DSN") or ""
            url = None
            if dashboard:
                url = dashboard
            else:
                # ננסה לגזור דומיין מה-DSN (ללא זליגת סודות)
                host = None
                try:
                    from urllib.parse import urlparse
                    parsed = urlparse(dsn)
                    raw_host = parsed.hostname or ''
                    # Sentry SaaS DSN hosts look like o123.ingest.sentry.io or ingest.sentry.io
                    # ללינק UI נרצה https://sentry.io/...
                    if raw_host == 'sentry.io' or raw_host.endswith('.sentry.io'):
                        host = 'sentry.io'
                    elif raw_host.startswith('ingest.'):
                        host = raw_host[len('ingest.'):]
                    else:
                        host = raw_host or None
                except Exception:
                    host = None
                org = os.getenv("SENTRY_ORG") or os.getenv("SENTRY_ORG_SLUG")
                if host and org:
                    url = f"https://{host}/organizations/{org}/issues/"
                elif host:
                    url = f"https://{host}/"

            if not url:
                await update.message.reply_text("ℹ️ Sentry לא מוגדר בסביבה זו.")
                return
            safe_url = html.escape(url)
            await update.message.reply_text(f"🔗 Sentry: {safe_url}", parse_mode=ParseMode.HTML)
        except Exception as e:
            await update.message.reply_text(f"❌ שגיאה ב-/sen: {html.escape(str(e))}")

    async def uptime_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/uptime – אחוז זמינות כולל לפי metrics"""
        try:
            # הרשאות: אדמינים בלבד
            try:
                user_id = int(getattr(update.effective_user, 'id', 0) or 0)
            except Exception:
                user_id = 0
            if not self._is_admin(user_id):
                await update.message.reply_text("❌ פקודה זמינה למנהלים בלבד")
                return
            try:
                from metrics import get_uptime_percentage  # type: ignore
                uptime = float(get_uptime_percentage())
            except Exception:
                uptime = 100.0
            await update.message.reply_text(f"⏱️ Uptime: {uptime:.2f}%")
        except Exception as e:
            await update.message.reply_text(f"❌ שגיאה ב-/uptime: {html.escape(str(e))}")

    async def observe_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/observe – סיכום חי; /observe -v/ -vv – תצוגה מפורטת עם מקורות"""
        try:
            # הרשאות: אדמינים בלבד
            try:
                user_id = int(getattr(update.effective_user, 'id', 0) or 0)
            except Exception:
                user_id = 0
            if not self._is_admin(user_id):
                await update.message.reply_text("❌ פקודה זמינה למנהלים בלבד")
                return

            args = list(getattr(context, 'args', []) or [])
            verbose_level = 0
            if any(str(a).strip().lower() == "-vv" for a in args):
                verbose_level = 2
            elif any(str(a).strip().lower() in {"-v", "--verbose"} for a in args):
                verbose_level = 1

            # פרמטרים אופציונליים: source=db|memory|all, window=5m|1h|24h
            source = "all"
            window = "24h"
            for a in args:
                s = str(a).strip().lower()
                if s.startswith("source="):
                    v = s.split("=", 1)[1].strip()
                    if v in {"db", "memory", "all"}:
                        source = v
                if s.startswith("window="):
                    v = s.split("=", 1)[1].strip()
                    if v in {"5m", "1h", "24h"}:
                        window = v

            # אם לא מצב מפורט – השאר התנהגות קיימת ללא שינוי
            if verbose_level == 0 and not any(t.startswith("source=") or t.startswith("window=") for t in args):
                # Uptime
                try:
                    from metrics import get_uptime_percentage  # type: ignore
                    uptime = float(get_uptime_percentage())
                except Exception:
                    uptime = 100.0

                # Error rate
                try:
                    from alert_manager import get_current_error_rate_percent  # type: ignore
                    error_rate = float(get_current_error_rate_percent(window_sec=5 * 60))
                except Exception:
                    error_rate = 0.0

                # Active users – כרגע placeholder
                active_users = 0
                try:
                    from metrics import codebot_active_users_total  # type: ignore
                    if codebot_active_users_total is not None:
                        active_users = 0
                except Exception:
                    active_users = 0

                # Alerts count (24h) עם fallback
                alerts_24h = 0
                critical_24h = 0
                used_db = False
                try:
                    from monitoring.alerts_storage import count_alerts_last_hours  # type: ignore
                    total_db, critical_db = count_alerts_last_hours(hours=24)
                    if (total_db or critical_db):
                        alerts_24h = int(total_db)
                        critical_24h = int(critical_db)
                        used_db = True
                except Exception:
                    used_db = False

                if not used_db:
                    internal_total = 0
                    internal_critical = 0
                    try:
                        from internal_alerts import get_recent_alerts  # type: ignore
                        items = get_recent_alerts(limit=400) or []
                        now = datetime.now(timezone.utc)
                        day_ago = now.timestamp() - 24 * 3600
                        for a in items:
                            try:
                                ts = a.get('ts')
                                t = datetime.fromisoformat(str(ts)).timestamp() if ts else 0.0
                            except Exception:
                                t = 0.0
                            if t >= day_ago:
                                internal_total += 1
                                if str(a.get('severity', '')).lower() == 'critical':
                                    internal_critical += 1
                    except Exception:
                        internal_total = 0
                        internal_critical = 0

                    dispatch_critical = 0
                    try:
                        from alert_manager import get_dispatch_log  # type: ignore
                        ditems = get_dispatch_log(limit=500) or []
                        now = datetime.now(timezone.utc)
                        day_ago = now.timestamp() - 24 * 3600
                        seen_ids = set()
                        for di in ditems:
                            try:
                                ts = di.get('ts')
                                t = datetime.fromisoformat(str(ts)).timestamp() if ts else 0.0
                            except Exception:
                                t = 0.0
                            if t >= day_ago:
                                aid = str(di.get('alert_id') or '').strip()
                                if aid:
                                    seen_ids.add(aid)
                        dispatch_critical = len(seen_ids)
                    except Exception:
                        dispatch_critical = 0

                    if internal_total > 0:
                        alerts_24h = internal_total
                        critical_24h = max(internal_critical, dispatch_critical)
                    else:
                        alerts_24h = dispatch_critical
                        critical_24h = dispatch_critical

                text = (
                    "🔍 Observability Overview\n"
                    f"Uptime: {uptime:.2f}%\n"
                    f"Error Rate: {error_rate:.2f}%\n"
                    f"Active Users: {active_users}\n"
                    f"Alerts (24h): {alerts_24h} ({critical_24h} critical)"
                )
                # חשוב: לבטל HTML parsing כדי למנוע כשלים על תווים/מזהים לא-מותרים
                await update.message.reply_text(text, parse_mode=None)
                return

            # ---- מצב מפורט (-v / -vv) ----
            # Uptime
            try:
                from metrics import get_uptime_percentage  # type: ignore
                uptime = float(get_uptime_percentage())
            except Exception:
                uptime = 100.0

            # Current metrics + thresholds (memory)
            try:
                from alert_manager import (
                    get_current_error_rate_percent,  # type: ignore
                    get_current_avg_latency_seconds,  # type: ignore
                    get_thresholds_snapshot,  # type: ignore
                )
                cur_err = float(get_current_error_rate_percent(window_sec=5 * 60))
                cur_lat = float(get_current_avg_latency_seconds(window_sec=5 * 60))
                thr = get_thresholds_snapshot() or {}
                err_thr = float(thr.get("error_rate_percent", {}).get("threshold", 0.0) or 0.0)
                lat_thr = float(thr.get("latency_seconds", {}).get("threshold", 0.0) or 0.0)
            except Exception:
                cur_err = 0.0
                cur_lat = 0.0
                err_thr = 0.0
                lat_thr = 0.0

            # חלון זמן לספירת התראות
            from datetime import timedelta
            now_dt = datetime.now(timezone.utc)
            if window == "5m":
                window_seconds = 5 * 60
                since_dt = now_dt - timedelta(seconds=window_seconds)
                window_label = "5m"
            elif window == "1h":
                window_seconds = 60 * 60
                since_dt = now_dt - timedelta(seconds=window_seconds)
                window_label = "1h"
            else:
                window_seconds = 24 * 3600
                since_dt = now_dt - timedelta(seconds=window_seconds)
                window_label = "24h"

            # Alerts – DB
            db_total = db_critical = None
            db_ok = False
            if source in {"db", "all"}:
                try:
                    from monitoring.alerts_storage import count_alerts_since  # type: ignore
                    db_total, db_critical = count_alerts_since(since_dt)
                    db_ok = True
                except Exception:
                    db_ok = False

            # Alerts – Memory (internal buffer) and dispatch de-dup check
            mem_total = mem_critical = None
            disp_unique_critical = None
            if source in {"memory", "all"}:
                try:
                    from internal_alerts import get_recent_alerts  # type: ignore
                    items = get_recent_alerts(limit=500) or []
                except Exception:
                    items = []
                try:
                    # בחר בסיס זמן יציב: מקס' ה-ts מהזיכרון (אם קיים), אחרת now
                    base_ts = None
                    try:
                        for a in items:
                            ts = a.get('ts')
                            if ts:
                                t = datetime.fromisoformat(str(ts)).timestamp()
                                base_ts = max(base_ts or t, t)
                    except Exception:
                        base_ts = None
                    if base_ts is None:
                        base_ts = since_dt.timestamp()
                    min_ts = float(base_ts) - float(window_seconds)
                    t_total = 0
                    t_critical = 0
                    for a in items:
                        try:
                            ts = a.get('ts')
                            t = datetime.fromisoformat(str(ts)).timestamp() if ts else 0.0
                        except Exception:
                            t = 0.0
                        if t >= min_ts:
                            t_total += 1
                            if str(a.get('severity', '')).lower() == 'critical':
                                t_critical += 1
                    mem_total = t_total
                    mem_critical = t_critical
                except Exception:
                    mem_total = mem_critical = 0

                # Unique critical IDs from dispatch log
                try:
                    from alert_manager import get_dispatch_log  # type: ignore
                    ditems = get_dispatch_log(limit=500) or []
                    # סמוך לבסיס הזמן שנקבע לזיכרון כדי לשמר עקביות עם חלון הזמן בפועל
                    if 'base_ts' in locals() and base_ts is not None:
                        min_ts = float(base_ts) - float(window_seconds)
                    else:
                        min_ts = since_dt.timestamp()
                    seen = set()
                    for di in ditems:
                        try:
                            ts = di.get('ts')
                            t = datetime.fromisoformat(str(ts)).timestamp() if ts else 0.0
                        except Exception:
                            t = 0.0
                        if t >= min_ts:
                            aid = str(di.get('alert_id') or '').strip()
                            if aid:
                                seen.add(aid)
                    disp_unique_critical = len(seen)
                except Exception:
                    disp_unique_critical = 0

            # Cooling snapshot & sinks health (best-effort)
            cooldown_lines: list[str] = []
            try:
                from alert_manager import get_cooldown_snapshot  # type: ignore
            except Exception:
                get_cooldown_snapshot = None  # type: ignore
            if get_cooldown_snapshot is not None:  # type: ignore[truthy-bool]
                try:
                    snap = get_cooldown_snapshot() or {}
                    for key in ("error_rate_percent", "latency_seconds"):
                        info = snap.get(key) or {}
                        active = bool(info.get("cooldown_active"))
                        left = info.get("seconds_left")
                        if active and left is not None:
                            cooldown_lines.append(f"{key}: active (~{int(left)}s left)")
                        else:
                            cooldown_lines.append(f"{key}: idle")
                except Exception:
                    cooldown_lines = []

            # Sinks health from dispatch log
            sinks_lines: list[str] = []
            try:
                from alert_manager import get_dispatch_log  # type: ignore
                ditems = get_dispatch_log(limit=100) or []
                per_sink: dict[str, dict[str, int]] = {}
                for di in ditems:
                    sink = str(di.get('sink') or 'unknown')
                    ok = bool(di.get('ok'))
                    s = per_sink.setdefault(sink, {"ok": 0, "fail": 0})
                    if ok:
                        s["ok"] += 1
                    else:
                        s["fail"] += 1
                for sink, agg in per_sink.items():
                    total = max(1, int(agg.get("ok", 0) + agg.get("fail", 0)))
                    okc = int(agg.get("ok", 0))
                    sinks_lines.append(f"{sink}: {okc}/{total} ok")
            except Exception:
                sinks_lines = []

            # בניית הודעה
            lines: list[str] = []
            lines.append("🔍 Observability – verbose")
            lines.append(f"Uptime: {uptime:.2f}% (source: memory)")
            lines.append(
                f"Error Rate (5m): curr={cur_err:.2f}% | thr={err_thr:.2f}% (source: memory)"
            )
            lines.append(
                f"Latency (5m): curr={cur_lat:.3f}s | thr={lat_thr:.3f}s (source: memory)"
            )

            # Alerts sections
            if source in {"db", "all"}:
                if db_ok and db_total is not None and db_critical is not None:
                    lines.append(f"Alerts (DB, window={window_label}): total={int(db_total)} | critical={int(db_critical)}")
                else:
                    lines.append(f"Alerts (DB, window={window_label}): unavailable (fallback to memory)")
            if source in {"memory", "all"}:
                if mem_total is not None and mem_critical is not None:
                    extra = f"; unique_critical_ids={disp_unique_critical}" if disp_unique_critical is not None else ""
                    lines.append(
                        f"Alerts (Memory, window={window_label}): total={int(mem_total)} | critical={int(mem_critical)}{extra}"
                    )
                else:
                    lines.append(f"Alerts (Memory, window={window_label}): n/a")

            # Recent errors (limited)
            try:
                from observability import get_recent_errors  # type: ignore
                recent = get_recent_errors(limit=5) or []
            except Exception:
                recent = []
            if recent:
                lines.append("Recent Errors (memory, N≤5):")
                for r in recent[-5:]:
                    try:
                        code = str(r.get("error_code") or r.get("code") or "-")
                        ev = str(r.get("event") or "error")
                        ts = str(r.get("ts") or "")
                        lines.append(f"- [{code}] {ev} — {ts}")
                    except Exception:
                        continue

            # Cooling & Health
            if cooldown_lines:
                lines.append("Cooling:")
                lines.extend(["- " + x for x in cooldown_lines])
            if sinks_lines:
                lines.append("Sinks:")
                lines.extend(["- " + x for x in sinks_lines])

            # -vv: רשימת מזהי התראות אחרונות מה-DB (N=10)
            if verbose_level >= 2 and source in {"db", "all"}:
                try:
                    if db_ok:
                        from monitoring.alerts_storage import list_recent_alert_ids  # type: ignore
                        ids = list_recent_alert_ids(limit=10) or []
                    else:
                        ids = []
                except Exception:
                    ids = []
                if ids:
                    lines.append("Recent Alert IDs (DB, N≤10):")
                    for i in (ids[:10]):
                        lines.append(f"- {i}")

            # גבול אורך: חתוך אם ארוך מדי
            text = "\n".join(lines)
            if len(text) > 3500:
                text = text[:3400] + "\n… (truncated)"
            # חשוב: לבטל HTML parsing כדי למנוע כשלים על תווים/מזהים לא-מותרים (למשל IDs עם '<')
            await update.message.reply_text(text, parse_mode=None)
        except Exception as e:
            await update.message.reply_text(f"❌ שגיאה ב-/observe: {html.escape(str(e))}")

    async def alerts_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/alerts – הצג 5 ההתראות האחרונות מהמערכת הפנימית"""
        try:
            # הרשאות: אדמינים בלבד
            try:
                user_id = int(getattr(update.effective_user, 'id', 0) or 0)
            except Exception:
                user_id = 0
            if not self._is_admin(user_id):
                await update.message.reply_text("❌ פקודה זמינה למנהלים בלבד")
                return
            try:
                from internal_alerts import get_recent_alerts  # type: ignore
                items = get_recent_alerts(limit=5) or []
            except Exception:
                items = []
            if not items:
                await update.message.reply_text("ℹ️ אין התראות אחרונות")
                return
            lines = ["🚨 התראות אחרונות:"]
            for i, a in enumerate(items, 1):
                name = str(a.get('name') or 'alert')
                sev = str(a.get('severity') or 'info').upper()
                summary = str(a.get('summary') or '')
                lines.append(f"{i}. [{sev}] {name} – {summary}")
            await update.message.reply_text("\n".join(lines))
        except Exception as e:
            await update.message.reply_text(f"❌ שגיאה ב-/alerts: {html.escape(str(e))}")

    async def incidents_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/incidents – 5 התקלות האחרונות (שם, זמן, טיפול)"""
        try:
            try:
                user_id = int(getattr(update.effective_user, 'id', 0) or 0)
            except Exception:
                user_id = 0
            if not self._is_admin(user_id):
                await update.message.reply_text("❌ פקודה זמינה למנהלים בלבד")
                return
            try:
                from remediation_manager import get_incidents  # type: ignore
                items = get_incidents(limit=5) or []
            except Exception:
                items = []
            lines = ["🧠 תקלות אחרונות:"]
            if not items:
                lines.append("(אין תקלות מתועדות)")
            for i, it in enumerate((items[-5:] if items else []), 1):
                name = str(it.get('name') or 'incident')
                ts = str(it.get('ts') or '')
                action = str(it.get('response_action') or '-')
                lines.append(f"{i}. {name} — {ts} — action: {action}")
            # הרחבה: תחזיות פעילות (Observability v6)
            try:
                from predictive_engine import get_recent_predictions  # type: ignore
                preds = get_recent_predictions(limit=3) or []
            except Exception:
                preds = []
            lines.append("\n🔮 תחזיות פעילות:")
            if not preds:
                lines.append("(אין תחזיות פעילות)")
            else:
                for j, p in enumerate(preds[-3:], 1):
                    metric = str(p.get('metric') or '-')
                    when = str(p.get('predicted_cross_ts') or p.get('predicted_cross_at') or '-')
                    lines.append(f"{j}. {metric} → {when}")
            await update.message.reply_text("\n".join(lines))
        except Exception as e:
            await update.message.reply_text(f"❌ שגיאה ב-/incidents: {html.escape(str(e))}")

    async def predict_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/predict – תחזית תקלות ל-3 שעות הקרובות עם חיווי מגמות."""
        try:
            # הרשאות: אדמינים בלבד
            try:
                user_id = int(getattr(update.effective_user, 'id', 0) or 0)
            except Exception:
                user_id = 0
            if not self._is_admin(user_id):
                await update.message.reply_text("❌ פקודה זמינה למנהלים בלבד")
                return
            try:
                from predictive_engine import evaluate_predictions, note_observation  # type: ignore
            except Exception:
                await update.message.reply_text("ℹ️ מנוע חיזוי אינו זמין בסביבה זו")
                return
            horizon = 3 * 60 * 60  # 3h
            # Ensure we have a fresh observation snapshot before evaluating
            try:
                note_observation()
            except Exception:
                pass
            trends = evaluate_predictions(horizon_seconds=horizon) or []
            if not trends:
                await update.message.reply_text("🔮 אין נתונים מספיקים לחיזוי כרגע")
                return
            def _dir_emoji(slope: float) -> str:
                try:
                    if slope > 1e-6:
                        return "🔴"  # עליה
                    if slope < -1e-6:
                        return "🟢"  # ירידה
                    return "⚪"      # יציב
                except Exception:
                    return "⚪"
            lines: list[str] = ["🔮 Predictive Health – 3h"]
            for tr in trends:
                try:
                    metric = getattr(tr, 'metric', '-')
                    slope = float(getattr(tr, 'slope_per_minute', 0.0) or 0.0)
                    current = float(getattr(tr, 'current_value', 0.0) or 0.0)
                    thr = float(getattr(tr, 'threshold', 0.0) or 0.0)
                    cross_ts = getattr(tr, 'predicted_cross_ts', None)
                    emoji = _dir_emoji(slope)
                    base = f"{emoji} {metric}: curr={current:.3f} thr={thr:.3f} slope/min={slope:.4f}"
                    if cross_ts:
                        try:
                            from datetime import datetime, timezone
                            dt = datetime.fromtimestamp(float(cross_ts), timezone.utc)
                            when = dt.strftime('%H:%M UTC')
                            base += f" → חצייה צפויה ב-{when}"
                        except Exception:
                            base += " → חצייה צפויה"
                    lines.append(base)
                except Exception:
                    continue
            await update.message.reply_text("\n".join(lines))
        except Exception as e:
            await update.message.reply_text(f"❌ שגיאה ב-/predict: {html.escape(str(e))}")

    async def silence_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/silence <name|pattern> <duration> [reason...] [severity=<level>] [--force]

        Examples:
        /silence "High Latency" 2h reason=maintenance
        /silence High.* 30m severity=critical
        """
        try:
            # Admins only handled by decorator; parse args
            args = list(getattr(context, "args", []) or [])
            # (no additional args parsing here)
            if len(args) < 2:
                await update.message.reply_text("ℹ️ שימוש: /silence <name|pattern> <duration> [reason...] [severity=<level>] [--force]")
                return
            pattern = str(args[0])
            duration_str = str(args[1])
            reason_tokens = list(args[2:])
            force = any(t.strip().lower() == "--force" for t in reason_tokens)
            reason_tokens = [t for t in reason_tokens if t.strip().lower() != "--force"]
            severity = None
            # extract severity=xxx token if present
            new_tokens = []
            for t in reason_tokens:
                if t.lower().startswith("severity="):
                    severity = t.split("=", 1)[1].strip() or None
                else:
                    new_tokens.append(t)
            reason_tokens = new_tokens
            reason = " ".join(reason_tokens).strip()

            # duration parse & bounds
            try:
                from monitoring.silences import parse_duration_to_seconds  # type: ignore
                max_days_env = int(_os.getenv("SILENCE_MAX_DAYS", "7") or 7)
                dur_sec = parse_duration_to_seconds(duration_str, max_days=max_days_env)  # type: ignore[arg-type]
            except Exception:
                # Fallback lightweight parser (supports Ns/Nm/Nh/Nd)
                try:
                    import re as _re
                    try:
                        max_days_env = int(_os.getenv("SILENCE_MAX_DAYS", "7") or 7)
                    except Exception:
                        max_days_env = 7
                    m = _re.fullmatch(r"\s*(\d+)\s*([smhd])\s*", str(duration_str).strip().lower())
                    if not m:
                        dur_sec = None
                    else:
                        n = int(m.group(1))
                        unit = m.group(2)
                        if unit == "s":
                            seconds = n
                        elif unit == "m":
                            seconds = n * 60
                        elif unit == "h":
                            seconds = n * 3600
                        else:
                            seconds = n * 86400
                        max_seconds = max(1, int(max_days_env)) * 86400
                        if seconds <= 0:
                            dur_sec = None
                        else:
                            dur_sec = min(seconds, max_seconds)
                except Exception:
                    dur_sec = None
            if not dur_sec:
                await update.message.reply_text("❌ משך זמן לא תקין. השתמש ב-5m/1h/2d וכד'.")
                return

            try:
                user_id = int(getattr(update.effective_user, 'id', 0) or 0)
            except Exception:
                user_id = 0

            # Prevent dangerous patterns unless force
            if not force:
                dangerous = {".*", "^.*$", "(?s).*", ".+", "^.+$"}
                if pattern.strip() in dangerous:
                    await update.message.reply_text("⛔ תבנית מסוכנת. הוסף --force אם אתה בטוח.")
                    return

            # Dynamically resolve monitoring.silences to respect test monkeypatching
            import sys as _sys, importlib as _il  # type: ignore
            sil = _sys.modules.get('monitoring.silences') or _il.import_module('monitoring.silences')  # type: ignore
            doc = sil.create_silence(pattern=pattern, duration_seconds=int(dur_sec), created_by=user_id, reason=reason, severity=severity, force=bool(force))
            if not doc:
                await update.message.reply_text("❌ יצירת השתקה נכשלה (בדוק מגבלות/תבנית/DB)")
                return
            sid = str(doc.get("_id") or "")
            until = str(doc.get("until_ts") or "")
            await update.message.reply_text(f"✅ הושתק: id={sid}\nפג ב- {until}")
        except Exception as e:
            await update.message.reply_text(f"❌ שגיאה ב-/silence: {html.escape(str(e))}")

    async def unsilence_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/unsilence <id|pattern> – disable active silence(s)."""
        try:
            args = list(getattr(context, "args", []) or [])
            if not args:
                await update.message.reply_text("ℹ️ שימוש: /unsilence <id|pattern>")
                return
            target = " ".join(args).strip()
            import sys as _sys, importlib as _il  # type: ignore
            sil = _sys.modules.get('monitoring.silences') or _il.import_module('monitoring.silences')  # type: ignore
            # Heuristic: id is 32-hex (uuid hex); else treat as pattern
            import re as _re
            if _re.fullmatch(r"[0-9a-fA-F]{32}", target):
                ok = sil.unsilence_by_id(target)
                await update.message.reply_text("✅ בוטלה השתקה" if ok else "ℹ️ לא נמצאה/עודכנה השתקה")
                return
            else:
                n = sil.unsilence_by_pattern(target)
                await update.message.reply_text(f"✅ בוטלו {n} השתקות" if n > 0 else "ℹ️ לא נמצאו השתקות פעילות לתבנית")
        except Exception as e:
            await update.message.reply_text(f"❌ שגיאה ב-/unsilence: {html.escape(str(e))}")

    async def silences_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/silences – list active silences."""
        try:
            import sys as _sys, importlib as _il  # type: ignore
            sil = _sys.modules.get('monitoring.silences') or _il.import_module('monitoring.silences')  # type: ignore
            items = sil.list_active_silences(limit=50) or []
            if not items:
                await update.message.reply_text("ℹ️ אין השתקות פעילות")
                return
            lines = ["🔕 השתקות פעילות:"]
            for it in items:
                sid = str(it.get("_id") or "")
                patt = str(it.get("pattern") or "")
                sev = str(it.get("severity") or "") or "-"
                until = str(it.get("until_ts") or "")
                reason = str(it.get("reason") or "")
                lines.append(f"• {sid} | pattern={patt} | severity={sev} | until={until} | reason={reason}")
            await update.message.reply_text("\n".join(lines))
        except Exception as e:
            await update.message.reply_text(f"❌ שגיאה ב-/silences: {html.escape(str(e))}")

    async def accuracy_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/accuracy — דיוק חיזוי נוכחי וסטטיסטיקת מניעה."""
        try:
            # הרשאות: אדמינים בלבד
            try:
                user_id = int(getattr(update.effective_user, 'id', 0) or 0)
            except Exception:
                user_id = 0
            if not self._is_admin(user_id):
                await update.message.reply_text("❌ פקודה זמינה למנהלים בלבד")
                return

            # שליפת דיוק חיזוי מ-gauge אם קיים
            accuracy = None
            prevented_total = 0
            try:
                from metrics import prediction_accuracy_percent, prevented_incidents_total  # type: ignore
                if prediction_accuracy_percent is not None:
                    # Gauges in prometheus_client expose _value.get()
                    accuracy = float(getattr(getattr(prediction_accuracy_percent, "_value", None), "get", lambda: 0.0)())
                if prevented_incidents_total is not None:
                    # Sum across all labels if possible
                    # prometheus_client stores counters in _metrics dict keyed by label tuples
                    metrics_map = getattr(prevented_incidents_total, "_metrics", {}) or {}
                    for _labels, sample in getattr(metrics_map, "items", lambda: [])():
                        try:
                            prevented_total += int(getattr(getattr(sample, "_value", None), "get", lambda: 0)())
                        except Exception:
                            continue
            except Exception:
                pass

            # גיבוי: חישוב זריז מתוך predictive_engine (אם gauge לא קיים)
            if accuracy is None:
                try:
                    from predictive_engine import get_recent_predictions  # type: ignore
                    preds = get_recent_predictions(limit=200) or []
                    accuracy = 100.0 if preds else 0.0
                except Exception:
                    accuracy = 0.0

            msg = (
                f"📊 Prediction Accuracy: {accuracy:.2f}%\n"
                f"🛡️ Prevented Incidents (est.): {prevented_total}"
            )
            await update.message.reply_text(msg)
        except Exception as e:
            await update.message.reply_text(f"❌ שגיאה ב-/accuracy: {html.escape(str(e))}")

    async def errors_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/errors – Top signatures (5/30/120m) + Sentry links; supports '/errors examples <signature>'"""
        try:
            # הרשאות: אדמינים בלבד
            try:
                user_id = int(getattr(update.effective_user, 'id', 0) or 0)
            except Exception:
                user_id = 0
            if not self._is_admin(user_id):
                await update.message.reply_text("❌ פקודה זמינה למנהלים בלבד")
                return

            args = list(getattr(context, "args", []) or [])
            # Optional filters: service=..., endpoint=...
            svc_filter = None
            ep_filter = None
            try:
                for tok in args:
                    t = str(tok or "").strip()
                    if "=" not in t:
                        continue
                    k, v = t.split("=", 1)
                    key = (k or "").strip().lower()
                    val = (v or "").strip()
                    if key == "service" and val:
                        svc_filter = val
                    elif key == "endpoint" and val:
                        ep_filter = val
            except Exception:
                svc_filter = svc_filter or None
                ep_filter = ep_filter or None

            # Helper: build Sentry query link for a given error_signature
            def _sentry_query_link(signature: str) -> Optional[str]:
                try:
                    # Best-effort derive UI base from DSN
                    dsn = os.getenv("SENTRY_DSN") or ""
                    host = None
                    if dsn:
                        try:
                            from urllib.parse import urlparse
                            parsed = urlparse(dsn)
                            raw_host = parsed.hostname or ''
                        except Exception:
                            raw_host = ''
                        if raw_host == 'sentry.io' or raw_host.endswith('.sentry.io'):
                            host = 'sentry.io'
                        elif raw_host.startswith('ingest.'):
                            host = raw_host[len('ingest.'):]
                        else:
                            host = raw_host or None
                    host = host or 'sentry.io'
                    org = os.getenv("SENTRY_ORG") or os.getenv("SENTRY_ORG_SLUG")
                    if not org:
                        return None
                    from urllib.parse import quote_plus
                    q = quote_plus(f'error_signature:"{signature}"')
                    return f"https://{host}/organizations/{org}/issues/?query={q}&statsPeriod=24h"
                except Exception:
                    return None

            # Sub-command: examples for a given signature
            if args and args[0].lower() in {"example", "examples"}:
                signature = " ".join(args[1:]).strip()
                if not signature:
                    await update.message.reply_text("ℹ️ שימוש: /errors examples <error_signature>")
                    return
                try:
                    from observability import get_recent_errors  # type: ignore
                    examples = []
                    for er in (get_recent_errors(limit=200) or []):
                        sig = str(er.get("error_signature") or er.get("event") or "")
                        if sig == signature:
                            ts = str(er.get("ts") or er.get("timestamp") or "")
                            msg = str(er.get("error") or er.get("event") or "")
                            examples.append(f"• {ts} – {msg}")
                            if len(examples) >= 5:
                                break
                    if not examples:
                        await update.message.reply_text("(אין דוגמאות זמינות לחתימה זו)")
                        return
                    link = _sentry_query_link(signature)
                    header = f"🔎 דוגמאות לשגיאות עבור החתימה: {signature}"
                    if link:
                        header += f"\nSentry: {link}"
                    await update.message.reply_text("\n".join([header] + examples))
                    return
                except Exception:
                    await update.message.reply_text("(כשל באיסוף דוגמאות)")
                    return

            lines: list[str] = []
            kb_rows: list[list[InlineKeyboardButton]] = []

            # 1) Sentry-first (best-effort): recent unresolved issues
            try:
                import integrations_sentry as _sentry  # type: ignore
                if getattr(_sentry, "is_configured", None) and _sentry.is_configured():
                    issues = await _sentry.get_recent_issues(limit=10)
                    if issues:
                        lines.append("Sentry – issues אחרונים:")
                        for i, it in enumerate(issues, 1):
                            sid = str(it.get("shortId") or it.get("id") or "-")
                            title = str(it.get("title") or "")
                            perma = str(it.get("permalink") or "")
                            suffix = f" – {perma}" if perma else ""
                            lines.append(f"{i}. [{sid}] {title}{suffix}")
            except Exception:
                # ignore and continue
                pass

            # 2) Local Top signatures from recent errors buffer, across windows
            try:
                from observability import get_recent_errors  # type: ignore
                from datetime import datetime, timezone, timedelta

                def _parse_ts(ts: str) -> Optional[datetime]:
                    try:
                        return datetime.fromisoformat(str(ts).replace('Z', '+00:00'))
                    except Exception:
                        return None

                # Windows default or single-window from args like '30m' (search any token)
                wins: list[int]
                _win_tok = None
                try:
                    for t in args:
                        tl = str(t or "").lower().strip()
                        if tl.endswith('m') and tl[:-1].isdigit():
                            _win_tok = tl
                            break
                except Exception:
                    _win_tok = None
                if _win_tok is not None:
                    mins = max(1, int(_win_tok[:-1]))
                    wins = [mins]
                else:
                    wins = [5, 30, 120]

                recent = get_recent_errors(limit=200) or []
                now = datetime.now(timezone.utc)

                # נשמור מועמדים לכפתורים מתוך חלון היעד (ברירת מחדל: 30m או החלון היחיד שבחר המשתמש)
                target_window = wins[0] if len(wins) == 1 else 30
                selected_sigs: list[str] = []

                for w in wins:
                    start = now - timedelta(minutes=int(w))
                    grouped: dict[str, dict[str, Any]] = {}
                    for er in recent:
                        # Apply optional filters (substring match, case-insensitive)
                        try:
                            if svc_filter:
                                svc = str(er.get("service") or "")
                                if svc_filter.lower() not in svc.lower():
                                    continue
                            if ep_filter:
                                ep = str(er.get("endpoint") or "")
                                if ep_filter.lower() not in ep.lower():
                                    continue
                        except Exception:
                            # On parsing errors, skip filtering for this record
                            pass
                        ts_raw = er.get("ts") or er.get("timestamp") or ""
                        ts_parsed = _parse_ts(ts_raw)
                        error_ts: datetime = ts_parsed if ts_parsed is not None else now
                        try:
                            if error_ts.tzinfo is None:
                                error_ts = error_ts.replace(tzinfo=timezone.utc)
                            else:
                                error_ts = error_ts.astimezone(timezone.utc)
                        except Exception:
                            error_ts = now
                        if error_ts < start:
                            continue
                        signature = str(er.get("error_signature") or er.get("event") or "unknown")
                        bucket = grouped.setdefault(signature, {
                            "count": 0,
                            "sample": "",
                            "category": str(er.get("error_category") or ""),
                            "policy": str(er.get("error_policy") or ""),
                            "code": str(er.get("error_code") or "-"),
                        })
                        bucket["count"] += 1
                        if not bucket["sample"]:
                            bucket["sample"] = str(er.get("error") or er.get("event") or "")
                        if not bucket["category"]:
                            bucket["category"] = str(er.get("error_category") or "")
                        if not bucket["policy"]:
                            bucket["policy"] = str(er.get("error_policy") or "")
                        if bucket.get("code") in {"", "-"} and er.get("error_code"):
                            bucket["code"] = str(er.get("error_code") or "-")

                    lines.append("")
                    lines.append(f"⏱️ Top {w}m:")
                    if not grouped:
                        lines.append("(אין נתונים בחלון זה)")
                        continue

                    sorted_groups = sorted(grouped.items(), key=lambda item: item[1]["count"], reverse=True)
                    for i, (sig, info) in enumerate(sorted_groups[:10], 1):
                        category = info.get("category") or "-"
                        label_parts = [category]
                        if sig and sig != "unknown":
                            label_parts.append(sig)
                        label = "|".join(label_parts)
                        count = int(info.get("count", 0) or 0)
                        sample = str(info.get("sample") or "-")
                        code = str(info.get("code") or "-")
                        line = f"{i}. [{label}] {count}× {sample}"
                        policy = str(info.get("policy") or "").strip()
                        if policy and policy not in {"escalate", "default"}:
                            line += f" — policy={policy}"
                        if code and code != "-":
                            line += f" (code={code})"
                        link = _sentry_query_link(sig) if sig and sig != "unknown" else None
                        if link:
                            line += f" — Sentry: {link}"
                        line += f" — דוגמאות: /errors examples {sig}"
                        lines.append(line)

                    # בחירת מועמדים לכפתורים
                    if (w == target_window) or (not selected_sigs and w == wins[-1]):
                        selected_sigs = [sig for sig, _info in sorted_groups[:5] if sig and sig != "unknown"]

                # בניית מקלדת אינליין: לכל חתימה כפתור דוגמאות + כפתור Sentry (URL)
                if selected_sigs:
                    try:
                        tokens_map = context.user_data.get('errors_sig_tokens') or {}
                        for sig in selected_sigs:
                            tok = hashlib.sha1(sig.encode('utf-8', 'ignore')).hexdigest()[:16]
                            tokens_map[tok] = sig
                            label = f"📄 דוגמאות – {sig[:18]}"
                            row = [InlineKeyboardButton(label, callback_data=f"err_ex:{tok}")]
                            link = _sentry_query_link(sig)
                            if link:
                                row.append(InlineKeyboardButton("🔎 Sentry", url=link))
                            kb_rows.append(row)
                        context.user_data['errors_sig_tokens'] = tokens_map
                    except Exception:
                        kb_rows = []
            except Exception:
                pass

            if not lines:
                lines.append("(אין נתוני שגיאות זמינים בסביבה זו)")
            await update.message.reply_text(
                "\n".join(["🧰 שגיאות אחרונות:"] + lines),
                reply_markup=(InlineKeyboardMarkup(kb_rows) if kb_rows else None)
            )
        except Exception as e:
            await update.message.reply_text(f"❌ שגיאה ב-/errors: {html.escape(str(e))}")

    async def triage_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/triage <request_id|query> – דוח חקירה קצר + קישור ל-HTML"""
        try:
            # הרשאות: אדמינים בלבד
            try:
                user_id = int(getattr(update.effective_user, 'id', 0) or 0)
            except Exception:
                user_id = 0
            if not self._is_admin(user_id):
                await update.message.reply_text("❌ פקודה זמינה למנהלים בלבד")
                return

            args = context.args or []
            query = " ".join(args).strip()
            if not query:
                await update.message.reply_text("ℹ️ שימוש: /triage <request_id או שאילתא>")
                return

            # איסוף נתונים דרך שירות ה-investigation (Sentry-first, best-effort)
            result: dict = {}
            try:
                from services import investigation_service as inv  # type: ignore
                result = await inv.triage(query, limit=20)
            except Exception:
                result = {"query": query, "timeline": [], "summary_text": ""}

            summary_lines: list[str] = ["🔎 Triage", f"Query: {html.escape(query)}"]
            text_summary = str(result.get("summary_text") or "").strip()
            if text_summary:
                summary_lines.append(text_summary)

            # שיתוף דוח HTML מלא כ-share פנימי
            share_url = None
            try:
                from integrations import code_sharing  # type: ignore
                html_doc = str(result.get("summary_html") or "")
                share = await code_sharing.share_code(
                    "internal", f"triage-{query}.html", html_doc, "html", description="Triage report"
                )
                if isinstance(share, dict):
                    share_url = share.get("url")
            except Exception:
                share_url = None
            if share_url:
                # חלק מלקוחות מרחפים על '_' בהודעות טקסט רגילות. שימוש ב‑Markdown עם קישור מעוגן מונע עיוות מזהה השיתוף.
                summary_lines.append(f"דוח מלא: [לחיצה כאן]({share_url})")
            else:
                # גם בסביבת טסטים ללא אינטגרציית שיתוף חייב להיות אזכור ברור לדוח המלא.
                summary_lines.append("דוח מלא: לא נוצר קישור אוטומטי (סביבת בדיקות)")

            # קישורי Sentry (2 ראשונים) + Grafana (2 ראשונים)
            try:
                slinks = list(result.get("sentry_links") or [])
                if slinks:
                    sl = ", ".join(f"[{l.get('name')}]({l.get('url')})" for l in slinks[:2])
                    summary_lines.append(f"Sentry: {sl}")
                glinks = list(result.get("grafana_links") or [])
                if glinks:
                    gl = ", ".join(f"[{l.get('name')}]({l.get('url')})" for l in glinks[:2])
                    summary_lines.append(f"Grafana: {gl}")
            except Exception:
                pass

            await update.message.reply_text("\n".join(summary_lines), parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            await update.message.reply_text(f"❌ שגיאה ב-/triage: {html.escape(str(e))}")

    async def system_info_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/system_info – תקציר מצב המערכת (CPU/Mem/Uptime/Env) – אדמינים בלבד"""
        try:
            # הרשאות: אדמינים בלבד
            try:
                user_id = int(getattr(update.effective_user, 'id', 0) or 0)
            except Exception:
                user_id = 0
            if not self._is_admin(user_id):
                await update.message.reply_text("❌ פקודה זמינה למנהלים בלבד")
                return

            import sys, platform
            # Uptime – השתמש בפונקציה ייעודית מ-metrics
            try:
                from metrics import get_process_uptime_seconds  # type: ignore
                uptime_sec = float(get_process_uptime_seconds())
            except Exception:
                uptime_sec = 0.0

            def _format_duration(seconds: float) -> str:
                try:
                    s = int(max(0, seconds))
                    d, rem = divmod(s, 86400)
                    h, rem = divmod(rem, 3600)
                    m, _ = divmod(rem, 60)
                    parts = []
                    if d:
                        parts.append(f"{d}d")
                    if h or d:
                        parts.append(f"{h}h")
                    parts.append(f"{m}m")
                    return " ".join(parts)
                except Exception:
                    return f"{seconds:.0f}s"

            # CPU/load
            cpu_count = os.cpu_count() or 1
            try:
                la1, la5, la15 = os.getloadavg()
                load_part = f"load {la1:.2f}/{la5:.2f}/{la15:.2f} (CPUs={cpu_count})"
            except Exception:
                load_part = f"CPUs={cpu_count}"

            # Memory RSS (best-effort)
            def _fmt_bytes(n: int) -> str:
                try:
                    units = ['B','KB','MB','GB','TB']
                    val = float(n)
                    i = 0
                    while val >= 1024 and i < len(units)-1:
                        val /= 1024.0
                        i += 1
                    return f"{val:.1f} {units[i]}"
                except Exception:
                    return str(n)

            mem_part = "unknown"
            try:
                try:
                    import psutil  # type: ignore
                except Exception:
                    psutil = None  # type: ignore
                if psutil is not None:
                    p = psutil.Process(os.getpid())
                    mem_part = _fmt_bytes(int(getattr(p.memory_info(), 'rss', 0)))
                else:
                    import resource  # type: ignore
                    rss_kb = int(getattr(resource.getrusage(resource.RUSAGE_SELF), 'ru_maxrss', 0))
                    mem_part = _fmt_bytes(rss_kb * 1024)
            except Exception:
                mem_part = "unknown"

            # סטטוס Sentry (ללא חשיפת סודות)
            sentry_dsn_set = bool(os.getenv("SENTRY_DSN"))
            sentry_api_ready = bool(os.getenv("SENTRY_AUTH_TOKEN") and (os.getenv("SENTRY_ORG") or os.getenv("SENTRY_ORG_SLUG")))

            env_name = os.getenv("ENVIRONMENT") or os.getenv("ENV") or "production"
            app_ver = os.getenv("APP_VERSION") or getattr(config, 'APP_VERSION', '') or ''

            lines = [
                "🖥️ System Info",
                f"• Python: {html.escape(sys.version.split(' ')[0])} ({html.escape(platform.system())} {html.escape(platform.release())})",
                f"• Uptime: {_format_duration(uptime_sec)}",
                f"• CPU: {load_part}",
                f"• Memory RSS: {mem_part}",
                f"• Env: {html.escape(env_name)} | Version: {html.escape(str(app_ver))}",
                f"• Sentry DSN: {'configured' if sentry_dsn_set else 'not set'}",
                f"• Sentry API (token+org): {'configured' if sentry_api_ready else 'not set'}",
            ]
            await update.message.reply_text("\n".join(lines))
        except Exception as e:
            await update.message.reply_text(f"❌ שגיאה ב-/system_info: {html.escape(str(e))}")

    async def metrics_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/metrics – סיכום קצר + קובץ metrics מלא (Prometheus) – אדמינים בלבד"""
        try:
            try:
                user_id = int(getattr(update.effective_user, 'id', 0) or 0)
            except Exception:
                user_id = 0
            if not self._is_admin(user_id):
                await update.message.reply_text("❌ פקודה זמינה למנהלים בלבד")
                return

            from metrics import metrics_endpoint_bytes, get_uptime_percentage  # type: ignore
            payload: bytes
            try:
                payload = metrics_endpoint_bytes() or b""
            except Exception:
                payload = b""

            try:
                uptime_pct = float(get_uptime_percentage())
                summary = f"📈 Metrics: uptime≈{uptime_pct:.2f}%"
            except Exception:
                summary = "📈 Metrics: uptime≈N/A"
            if payload:
                try:
                    fname = f"metrics_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.txt"
                    bio = io.BytesIO(payload)
                    bio.seek(0)
                    await update.message.reply_document(InputFile(bio, filename=fname), caption=summary)
                    return
                except Exception:
                    try:
                        text_preview = payload.decode('utf-8', errors='ignore')[:3500]
                    except Exception:
                        text_preview = "(metrics unavailable)"
                    await update.message.reply_text(summary + "\n\n" + text_preview)
                    return
            else:
                await update.message.reply_text(summary + "\n(metrics unavailable)")
        except Exception as e:
            await update.message.reply_text(f"❌ שגיאה ב-/metrics: {html.escape(str(e))}")

    async def rate_limit_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/rate_limit – מצב מגבלת GitHub עם התראה אם שימוש >80%"""
        try:
            # הרשאות: אדמינים בלבד
            try:
                user_id = int(getattr(update.effective_user, 'id', 0) or 0)
            except Exception:
                user_id = 0
            if not self._is_admin(user_id):
                await update.message.reply_text("❌ פקודה זמינה למנהלים בלבד")
                return
            if not os.getenv("GITHUB_TOKEN"):
                await update.message.reply_text("ℹ️ אין GITHUB_TOKEN – מידע לא זמין")
                return
            from http_async import request as async_request
            async with async_request(
                "GET",
                "https://api.github.com/rate_limit",
                headers={"Authorization": f"token {os.getenv('GITHUB_TOKEN')}"},
                service="github",
                endpoint="rate_limit",
            ) as resp:
                data = await resp.json()
            core = data.get("resources", {}).get("core", {})
            remaining = int(core.get("remaining", 0))
            limit = int(core.get("limit", 0))
            used_pct = (100 - int(remaining * 100 / max(limit, 1))) if limit else 0
            bar = self._progress_bar(used_pct)
            msg = (
                f"📈 GitHub Rate Limit\n"
                f"Remaining: {remaining}/{limit}\n"
                f"Usage: {bar}\n"
            )
            # אזהרה גם כאשר הנתונים לא זמינים (limit==0), וגם מעל 80%
            if used_pct >= 80 or limit == 0:
                msg += "\n⚠️ מתקרבים למגבלה! שקול לצמצם קריאות או להפעיל backoff"
            await update.message.reply_text(msg)
        except Exception as e:
            await update.message.reply_text(f"❌ שגיאה ב-/rate_limit: {html.escape(str(e))}")

    async def enable_backoff_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/enable_backoff – הפעלת Backoff גלובלי (מנהלים בלבד)"""
        try:
            try:
                user_id = int(getattr(update.effective_user, 'id', 0) or 0)
            except Exception:
                user_id = 0
            if not self._is_admin(user_id):
                await update.message.reply_text("❌ פקודה זמינה למנהלים בלבד")
                return
            ttl_min = None
            if context.args:
                try:
                    ttl_min = int(context.args[0])
                except Exception:
                    ttl_min = None
            reason = "manual"
            try:
                from services import github_backoff_state as _state
                if _state is None:
                    await update.message.reply_text("ℹ️ Backoff לא זמין בסביבה זו")
                    return
                info = _state.enable(reason=reason, ttl_minutes=ttl_min)
                ttl_text = f", יפוג בעוד {ttl_min} דק'" if ttl_min else ""
                await update.message.reply_text(f"🟡 הופעל Backoff GitHub (סיבה: {info.reason}{ttl_text})")
            except Exception as e:
                await update.message.reply_text(f"❌ שגיאה בהפעלת Backoff: {html.escape(str(e))}")
        except Exception as e:
            await update.message.reply_text(f"❌ שגיאה ב-/enable_backoff: {html.escape(str(e))}")

    async def disable_backoff_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/disable_backoff – כיבוי Backoff גלובלי (מנהלים בלבד)"""
        try:
            try:
                user_id = int(getattr(update.effective_user, 'id', 0) or 0)
            except Exception:
                user_id = 0
            if not self._is_admin(user_id):
                await update.message.reply_text("❌ פקודה זמינה למנהלים בלבד")
                return
            try:
                from services import github_backoff_state as _state
                if _state is None:
                    await update.message.reply_text("ℹ️ Backoff לא זמין בסביבה זו")
                    return
                info = _state.disable(reason="manual")
                await update.message.reply_text("🟢 Backoff כובה")
            except Exception as e:
                await update.message.reply_text(f"❌ שגיאה בכיבוי Backoff: {html.escape(str(e))}")
        except Exception as e:
            await update.message.reply_text(f"❌ שגיאה ב-/disable_backoff: {html.escape(str(e))}")

    def _progress_bar(self, percentage: int, width: int = 20) -> str:
        try:
            filled = int(width * max(0, min(100, int(percentage))) / 100)
            bar = "█" * filled + "░" * (width - filled)
            color = "🟢" if percentage < 60 else "🟡" if percentage < 80 else "🔴"
            return f"{color} [{bar}] {percentage}%"
        except Exception:
            return f"{percentage}%"
    
    async def validate_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """בדיקת תחביר של קוד"""
        reporter.report_activity(update.effective_user.id)
        user_id = update.effective_user.id
        
        if not context.args:
            await update.message.reply_text(
                "✅ אנא ציין שם קובץ לבדיקה:\n"
                "דוגמה: `/validate script.py`",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        file_name = " ".join(context.args)
        file_data = db.get_latest_version(user_id, file_name)
        
        if not file_data:
            await update.message.reply_text(
                f"❌ קובץ `{file_name}` לא נמצא.",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        # בדיקת תחביר
        from code_processor import CodeProcessor
        validation = CodeProcessor().validate_syntax(file_data['code'], file_data['programming_language'])
        
        if validation['is_valid']:
            response = f"✅ **תחביר תקין עבור:** `{file_name}`\n\n"
            response += f"🎉 הקוד עובר את כל בדיקות התחביר!"
        else:
            response = f"❌ **שגיאות תחביר עבור:** `{file_name}`\n\n"
            
            for error in validation['errors']:
                response += f"🚨 **שגיאה בשורה {error['line']}:**\n"
                response += f"   {error['message']}\n\n"
        
        # אזהרות
        if validation['warnings']:
            response += f"⚠️ **אזהרות:**\n"
            for warning in validation['warnings']:
                response += f"• שורה {warning['line']}: {warning['message']}\n"
        
        # הצעות
        if validation['suggestions']:
            response += f"\n💡 **הצעות לשיפור:**\n"
            for suggestion in validation['suggestions']:
                response += f"• {suggestion['message']}\n"
        
        await update.message.reply_text(response, parse_mode=ParseMode.MARKDOWN)
    
    async def share_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """שיתוף קטע(י) קוד ב-Gist/Pastebin/קישור פנימי. תומך בשם יחיד או שמות מרובים."""
        reporter.report_activity(update.effective_user.id)
        user_id = update.effective_user.id
        
        if not context.args:
            await update.message.reply_text(
                "🌐 אנא ציין שם קובץ או כמה שמות, מופרדים ברווח:\n"
                "דוגמאות:\n"
                "• `/share script.py`\n"
                "• `/share app.py utils.py README.md`",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        # תמיכה בשמות מרובים + wildcards (כמו *.py)
        requested_names: List[str] = context.args
        # ניקוי כפילויות, שימור סדר
        seen: set = set()
        file_names: List[str] = []
        for name in requested_names:
            if name not in seen:
                seen.add(name)
                file_names.append(name)

        # שליפת פרטי הקבצים (תומך ב-wildcards)
        found_files: List[Dict[str, Any]] = []
        missing: List[str] = []
        # נקבל את רשימת הקבצים של המשתמש למסנן wildcards בזיכרון
        all_files = db.get_user_files(user_id, limit=500, projection={"file_name": 1})
        all_names = [f['file_name'] for f in all_files if f.get('file_name')]

        def _expand_pattern(pattern: str) -> List[str]:
            # תמיכה בסיסית ב-* בלבד (תחילת/סוף/אמצע)
            if '*' not in pattern:
                return [pattern]
            # ממפה ל-regex פשוט
            import re as _re
            expr = '^' + _re.escape(pattern).replace('\\*', '.*') + '$'
            rx = _re.compile(expr)
            return [n for n in all_names if rx.match(n)]

        expanded_names: List[str] = []
        for name in file_names:
            expanded = _expand_pattern(name)
            expanded_names.extend(expanded)

        # ניפוי כפילויות ושמירת סדר
        seen2 = set()
        final_names: List[str] = []
        for n in expanded_names:
            if n not in seen2:
                seen2.add(n)
                final_names.append(n)

        for fname in final_names:
            data = db.get_latest_version(user_id, fname)
            if data:
                found_files.append(data)
            else:
                missing.append(fname)

        if not found_files:
            await update.message.reply_text(
                "❌ לא נמצאו קבצים לשיתוף.",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        # קידוד מזהה הקשר לשיתוף מרובה קבצים
        if len(found_files) == 1:
            single = found_files[0]
            file_name = single['file_name']
            keyboard = [
                [
                    InlineKeyboardButton("🐙 GitHub Gist", callback_data=f"share_gist_{file_name}"),
                    InlineKeyboardButton("📋 Pastebin", callback_data=f"share_pastebin_{file_name}")
                ]
            ]
            if config.PUBLIC_BASE_URL:
                keyboard.append([
                    InlineKeyboardButton("📱 קישור פנימי", callback_data=f"share_internal_{file_name}"),
                    InlineKeyboardButton("❌ ביטול", callback_data="cancel_share")
                ])
            else:
                keyboard.append([
                    InlineKeyboardButton("❌ ביטול", callback_data="cancel_share")
                ])
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(
                f"🌐 **שיתוף קובץ:** `{file_name}`\n\n"
                f"🔤 שפה: {single['programming_language']}\n"
                f"📏 גודל: {len(single['code'])} תווים\n\n"
                f"בחר אופן שיתוף:",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=reply_markup
            )
        else:
            # רישום מזהה ייחודי לרשימת הקבצים אצל המשתמש
            share_id = secrets.token_urlsafe(8)
            if 'multi_share' not in context.user_data:
                context.user_data['multi_share'] = {}
            # נשמור מיפוי share_id -> רשימת שמות קבצים
            context.user_data['multi_share'][share_id] = [f['file_name'] for f in found_files]

            files_list_preview = "\n".join([f"• `{f['file_name']}` ({len(f['code'])} תווים)" for f in found_files[:10]])
            more = "" if len(found_files) <= 10 else f"\n(ועוד {len(found_files)-10} קבצים...)"

            keyboard = [
                [
                    InlineKeyboardButton("🐙 GitHub Gist (מרובה)", callback_data=f"share_gist_multi:{share_id}")
                ]
            ]
            if config.PUBLIC_BASE_URL:
                keyboard.append([
                    InlineKeyboardButton("📱 קישור פנימי (מרובה)", callback_data=f"share_internal_multi:{share_id}"),
                    InlineKeyboardButton("❌ ביטול", callback_data="cancel_share")
                ])
            else:
                keyboard.append([
                    InlineKeyboardButton("❌ ביטול", callback_data="cancel_share")
                ])
            reply_markup = InlineKeyboardMarkup(keyboard)

            await update.message.reply_text(
                f"🌐 **שיתוף מספר קבצים ({len(found_files)}):**\n\n"
                f"{files_list_preview}{more}\n\n"
                f"בחר אופן שיתוף:",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=reply_markup
            )

    async def share_help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """הסבר קצר על פקודת /share"""
        reporter.report_activity(update.effective_user.id)
        if config.PUBLIC_BASE_URL:
            help_text = (
                "# 📤 פקודת /share – שיתוף קבצים בקלות\n\n"
                "## מה זה עושה?\n"
                "פקודת `/share` מאפשרת לך לשתף קבצים מהבוט באופן מהיר ונוח. הבוט יוצר עבורך קישורי שיתוף אוטומטיים לקבצים שאתה בוחר.\n\n"
                "## איך להשתמש?\n\n"
                "### דוגמאות פשוטות:\n"
                "- **קובץ יחיד:** `/share script.py`\n"
                "- **מספר קבצים:** `/share app.py utils.py README.md`\n"
                "- **עם כוכביות (wildcards):** `/share *.py` או `/share main.*`\n\n"
                "### ⚠️ חשוב לזכור:\n"
                "שמות הקבצים הם **case sensitive** - כלומר, צריך להקפיד על אותיות קטנות וגדולות בדיוק כמו שהן מופיעות בשם הקובץ המקורי.\n"
                "- **אם יש כמה קבצים עם אותו שם בבוט – ישותף האחרון שנשמר.**\n\n"
                "## איזה סוגי קישורים אפשר לקבל?\n\n"
                "### 🐙 GitHub Gist\n"
                "- **מתאים לכל סוג קובץ ומספר קבצים**\n"
                "- קישור יציב ואמין\n"
                "- כדי להשתמש יש להגדיר `GITHUB_TOKEN`\n\n"
                "### 📋 Pastebin\n"
                "- **רק לקובץ יחיד (מרובה קבצים לא נתמך)**\n"
                "- מהיר ופשוט לשימוש\n"
                "- כדי להשתמש יש להגדיר `PASTEBIN_API_KEY`\n\n"
                "### 📱 קישור פנימי\n"
                "- **זמין בסביבה זו**\n"
                "- קישור זמני (בתוקף כשבוע בערך)\n"
                "- עובד עם כל סוג וכמות קבצים\n\n"
            )
        else:
            help_text = (
                "# 📤 פקודת /share – שיתוף קבצים בקלות\n\n"
                "## מה זה עושה?\n"
                "פקודת `/share` מאפשרת לך לשתף קבצים מהבוט באופן מהיר ונוח. הבוט יוצר עבורך קישורי שיתוף אוטומטיים לקבצים שאתה בוחר.\n\n"
                "## איך להשתמש?\n\n"
                "### דוגמאות פשוטות:\n"
                "- **קובץ יחיד:** `/share script.py`\n"
                "- **מספר קבצים:** `/share app.py utils.py README.md`\n"
                "- **עם כוכביות (wildcards):** `/share *.py` או `/share main.*`\n\n"
                "### ⚠️ חשוב לזכור:\n"
                "שמות הקבצים הם **case sensitive** - כלומר, צריך להקפיד על אותיות קטנות וגדולות בדיוק כמו שהן מופיעות בשם הקובץ המקורי.\n"
                "- **אם יש כמה קבצים עם אותו שם בבוט – ישותף האחרון שנשמר.**\n\n"
                "## איזה סוגי קישורים אפשר לקבל?\n\n"
                "### 🐙 GitHub Gist\n"
                "- **מתאים לכל סוג קובץ ומספר קבצים**\n"
                "- קישור יציב ואמין\n"
                "- כדי להשתמש יש להגדיר `GITHUB_TOKEN`\n\n"
                "### 📋 Pastebin\n"
                "- **רק לקובץ יחיד (מרובה קבצים לא נתמך)**\n"
                "- מהיר ופשוט לשימוש\n"
                "- כדי להשתמש יש להגדיר `PASTEBIN_API_KEY`\n\n"
                "(קישור פנימי אינו זמין בסביבה זו)\n\n"
            )
        await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)
    
    async def download_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """הורדת קובץ"""
        reporter.report_activity(update.effective_user.id)
        user_id = update.effective_user.id
        
        if not context.args:
            await update.message.reply_text(
                "📥 אנא ציין שם קובץ להורדה:\n"
                "דוגמה: `/download script.py`",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        file_name = " ".join(context.args)
        file_data = db.get_latest_version(user_id, file_name)
        
        if not file_data:
            await update.message.reply_text(
                f"❌ קובץ `{file_name}` לא נמצא.",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        # יצירת קובץ להורדה
        file_content = file_data['code'].encode('utf-8')
        file_obj = io.BytesIO(file_content)
        file_obj.name = file_name
        
        # שליחת הקובץ
        await update.message.reply_document(
            document=InputFile(file_obj, filename=file_name),
            caption=f"📥 **הורדת קובץ:** `{file_name}`\n"
                   f"🔤 שפה: {file_data['programming_language']}\n"
                   f"📅 עודכן: {file_data['updated_at'].strftime('%d/%m/%Y %H:%M')}",
            parse_mode=ParseMode.MARKDOWN
        )
    
    async def tags_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """הצגת כל התגיות של המשתמש"""
        reporter.report_activity(update.effective_user.id)
        user_id = update.effective_user.id
        
        files = db.get_user_files(user_id, limit=500, projection={"file_name": 1, "tags": 1})
        
        if not files:
            await update.message.reply_text("🏷️ עדיין אין לך קבצים עם תגיות.")
            return
        
        # איסוף כל התגיות
        all_tags: dict[str, int] = {}
        for file_data in files:
            for tag in file_data.get('tags', []):
                if tag in all_tags:
                    all_tags[tag] += 1
                else:
                    all_tags[tag] = 1
        
        if not all_tags:
            await update.message.reply_text("🏷️ עדיין אין לך קבצים עם תגיות.")
            return
        
        # מיון לפי תדירות
        sorted_tags = sorted(all_tags.items(), key=lambda x: x[1], reverse=True)
        
        response = "🏷️ **התגיות שלך:**\n\n"
        
        for tag, count in sorted_tags[:20]:  # מקסימום 20 תגיות
            response += f"• `#{tag}` ({count} קבצים)\n"
        
        if len(sorted_tags) > 20:
            response += f"\n📄 ועוד {len(sorted_tags) - 20} תגיות..."
        
        await update.message.reply_text(response, parse_mode=ParseMode.MARKDOWN)
    
    async def recent_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """הצגת הקבצים שעודכנו לאחרונה"""
        reporter.report_activity(update.effective_user.id)
        user_id = update.effective_user.id
        
        # כמה ימים אחורה לחפש
        days_back = 7
        if context.args and context.args[0].isdigit():
            days_back = int(context.args[0])
        
        # חיפוש קבצים אחרונים
        since_date = datetime.now(timezone.utc) - timedelta(days=days_back)
        
        files = db.get_user_files(user_id, limit=50)
        recent_files = [
            f for f in files 
            if f['updated_at'] >= since_date
        ]
        
        if not recent_files:
            await update.message.reply_text(
                f"📅 לא נמצאו קבצים שעודכנו ב-{days_back} הימים האחרונים."
            )
            return
        
        response = f"📅 <b>קבצים מ-{days_back} הימים האחרונים:</b>\n\n"
        
        for file_data in recent_files[:15]:  # מקסימום 15 קבצים
            dt_now = datetime.now(timezone.utc) if file_data['updated_at'].tzinfo else datetime.now()
            days_ago = (dt_now - file_data['updated_at']).days
            time_str = f"היום" if days_ago == 0 else f"לפני {days_ago} ימים"
            safe_name = html.escape(str(file_data.get('file_name', '')))
            safe_lang = html.escape(str(file_data.get('programming_language', 'unknown')))
            response += f"📄 <code>{safe_name}</code>\n"
            response += f"   🔤 {safe_lang} | 📅 {time_str}\n\n"
        
        if len(recent_files) > 15:
            response += f"📄 ועוד {len(recent_files) - 15} קבצים..."
        
        await update.message.reply_text(response, parse_mode=ParseMode.HTML)

    async def info_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """מידע מהיר על קובץ ללא פתיחה"""
        reporter.report_activity(update.effective_user.id)
        user_id = update.effective_user.id
        
        if not context.args:
            await update.message.reply_text(
                "ℹ️ אנא ציין שם קובץ:\n"
                "דוגמה: <code>/info script.py</code>",
                parse_mode=ParseMode.HTML
            )
            return
        
        file_name = " ".join(context.args)
        file_data = db.get_latest_version(user_id, file_name)
        if not file_data:
            await update.message.reply_text(
                f"❌ קובץ <code>{html.escape(file_name)}</code> לא נמצא.",
                parse_mode=ParseMode.HTML
            )
            return
        
        safe_name = html.escape(str(file_data.get('file_name', file_name)))
        safe_lang = html.escape(str(file_data.get('programming_language', 'unknown')))
        size_chars = len(file_data.get('code', '') or '')
        updated_at = file_data.get('updated_at')
        try:
            updated_str = updated_at.strftime('%d/%m/%Y %H:%M') if updated_at else '-'
        except Exception:
            updated_str = str(updated_at) if updated_at else '-'
        tags = file_data.get('tags') or []
        tags_str = ", ".join(f"#{html.escape(str(t))}" for t in tags) if tags else "-"
        
        message = (
            "ℹ️ <b>מידע על קובץ</b>\n\n"
            f"📄 <b>שם:</b> <code>{safe_name}</code>\n"
            f"🔤 <b>שפה:</b> {safe_lang}\n"
            f"📏 <b>גודל:</b> {size_chars} תווים\n"
            f"📅 <b>עודכן:</b> {html.escape(updated_str)}\n"
            f"🏷️ <b>תגיות:</b> {tags_str}"
        )
        await update.message.reply_text(message, parse_mode=ParseMode.HTML)

    async def search_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """חיפוש קטעי קוד לפי טקסט/שפה/תגיות — מימוש מינימלי ובטוח לסוגים"""
        reporter.report_activity(update.effective_user.id)
        # קלט בטוח — לא מניחים כלום על context.args
        args = list(context.args or [])
        if not args:
            await update.message.reply_text(
                "🔍 שימוש: /search <query>\n\n"
                "דוגמאות:\n"
                "• /search python — סינון לפי שפה\n"
                "• /search #utils — לפי תגית\n"
                "• /search api — חיפוש חופשי בשם/בתוכן",
                parse_mode=ParseMode.MARKDOWN,
            )
            return
        # פענוח מינימלי של פרמטרים ללא תלות במסד/שירותים
        query_tokens = []
        tags = []
        languages = []
        for token in args:
            t = str(token or "").strip()
            if not t:
                continue
            if t.startswith('#') and len(t) > 1:
                tags.append(t[1:])
            elif t.lower() in {"python","javascript","typescript","java","html","css","json","yaml","markdown","bash","text"}:
                languages.append(t.lower())
            else:
                query_tokens.append(t)
        # תשובה מינימלית; ההיגיון המלא של חיפוש נמצא ב-main/handlers אחרים
        msg = ["🔍 חיפוש התחלתי (תצוגת הדגמה):\n"]
        if languages:
            msg.append(f"• שפות: {', '.join(languages)}")
        if tags:
            msg.append(f"• תגיות: {', '.join('#'+x for x in tags)}")
        if query_tokens:
            msg.append(f"• טקסט: {' '.join(query_tokens)}")
        await update.message.reply_text("\n".join(msg) or "🔍 חיפוש", parse_mode=ParseMode.MARKDOWN)

    def _is_admin(self, user_id: int) -> bool:
        """בודק אם המשתמש הוא אדמין לפי allowlist מפורש; נופל חזרה למודול permissions ללא מצב allow-all."""
        # שלב ראשון: allowlist מפורש מה-ENV (בעל קדימות)
        try:
            raw = os.getenv('ADMIN_USER_IDS', '')
            ids = [int(x.strip()) for x in raw.split(',') if x.strip().isdigit()]
        except Exception:
            ids = []

        if ids:
            try:
                return int(user_id) in ids
            except Exception:
                return False

        # אם אין allowlist מפורש, אל תסמוך על override גורף של CHATOPS_ALLOW_ALL_IF_NO_ADMINS
        allow_all_override = str(os.getenv("CHATOPS_ALLOW_ALL_IF_NO_ADMINS", "")).strip().lower()
        if allow_all_override in {"1", "true", "yes", "on"}:
            return False

        #Fallback זהיר למודול permissions אם זמין (למשל עבור מקורות אחרים של הרשאות)
        try:
            if callable(_perm_is_admin):
                return bool(_perm_is_admin(int(user_id)))
        except Exception:
            return False

        return False

    async def broadcast_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """שידור הודעה לכל המשתמשים עם הגבלת קצב, RetryAfter וסיכום תוצאות."""
        user_id = update.effective_user.id
        if not self._is_admin(user_id):
            await update.message.reply_text("❌ פקודה זמינה רק למנהלים")
            return
        
        # ההודעה לשידור
        message_text = " ".join(context.args or []).strip()
        if not message_text:
            await update.message.reply_text(
                "📢 שימוש: /broadcast <message>\n"
                "שלח את ההודעה שתשודר לכל המשתמשים."
            )
            return
        
        # שליפת נמענים מ-Mongo
        if not hasattr(db, 'db') or db.db is None or not hasattr(db.db, 'users'):
            await update.message.reply_text("❌ לא ניתן לטעון רשימת משתמשים מהמסד.")
            return
        try:
            coll = db.db.users
            cursor = coll.find({"user_id": {"$exists": True}, "blocked": {"$ne": True}}, {"user_id": 1})
            recipients: List[int] = []
            for doc in cursor:
                try:
                    uid = int(doc.get("user_id") or 0)
                    if uid:
                        recipients.append(uid)
                except Exception:
                    continue
        except Exception as e:
            logger.error(f"טעינת נמענים נכשלה: {e}")
            await update.message.reply_text("❌ שגיאה בטעינת רשימת נמענים")
            return
        
        if not recipients:
            await update.message.reply_text("ℹ️ אין נמענים לשידור.")
            return
        
        # תוכן בטוח ל-HTML
        safe_text = html.escape(message_text)
        
        success_count = 0
        fail_count = 0
        removed_ids: List[int] = []
        delay_seconds = 0.1  # ~10 הודעות בשנייה

        for rid in recipients:
            sent_ok = False
            attempts = 0
            while attempts < 3 and not sent_ok:
                try:
                    await context.bot.send_message(chat_id=rid, text=safe_text, parse_mode=ParseMode.HTML)
                    success_count += 1
                    sent_ok = True
                except telegram.error.RetryAfter as e:
                    attempts += 1
                    await asyncio.sleep(float(getattr(e, 'retry_after', 1.0)) + 0.5)
                    # ננסה שוב בלולאה
                except telegram.error.Forbidden:
                    fail_count += 1
                    removed_ids.append(rid)
                    break
                except telegram.error.BadRequest as e:
                    fail_count += 1
                    if 'chat not found' in str(e).lower() or 'not found' in str(e).lower():
                        removed_ids.append(rid)
                    break
                except Exception as e:
                    logger.warning(f"שידור לנמען {rid} נכשל: {e}")
                    fail_count += 1
                    break
            if not sent_ok and attempts >= 3:
                fail_count += 1
            await asyncio.sleep(delay_seconds)
        
        removed_count = 0
        if removed_ids:
            try:
                coll.update_many({"user_id": {"$in": removed_ids}}, {"$set": {"blocked": True}})
                removed_count = len(removed_ids)
            except Exception:
                pass
        
        summary = (
            "📢 סיכום שידור\n\n"
            f"👥 נמענים: {len(recipients)}\n"
            f"✅ הצלחות: {success_count}\n"
            f"❌ כשלים: {fail_count}\n"
            f"🧹 סומנו כחסומים/לא זמינים: {removed_count}"
        )
        await update.message.reply_text(summary)

    async def dm_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """שליחת הודעה פרטית למשתמש יחיד (למנהלים בלבד).

        שימוש:
        /dm <user_id|@username> <message...>

        ההודעה נשלחת ב-HTML עם עטיפת <pre> כדי לשמר רווחים ושורות.
        """
        caller_id = update.effective_user.id
        if not self._is_admin(caller_id):
            await update.message.reply_text("❌ פקודה זמינה רק למנהלים")
            return

        raw = (getattr(update.message, 'text', None) or '').strip()
        # תמיכה ב-/dm@BotUserName
        m = re.match(r"^/dm(?:@\S+)?\s+(\S+)\s+([\s\S]+)$", raw)
        if not m:
            await update.message.reply_text(
                "📬 שימוש: /dm <user_id|@username> <message>\nדוגמה: /dm 123456 היי! קיבלת פרימיום 💎"
            )
            return

        recipient_token = m.group(1).strip()
        message_text = m.group(2)

        # Resolve recipient
        target_id: Optional[int] = None
        if recipient_token.lstrip("-").isdigit():
            try:
                target_id = int(recipient_token)
            except Exception:
                target_id = None
        else:
            # username: strip leading @ and query DB
            uname = recipient_token[1:] if recipient_token.startswith('@') else recipient_token
            try:
                if hasattr(db, 'db') and db.db is not None and hasattr(db.db, 'users'):
                    # נסה התאמה מדויקת ואז lowercase
                    doc = db.db.users.find_one({"username": uname}) or db.db.users.find_one({"username": uname.lower()})
                    if doc and doc.get('user_id'):
                        target_id = int(doc['user_id'])
            except Exception:
                target_id = None

        if not target_id:
            await update.message.reply_text("❌ נמענ/ת לא נמצא/ה. ספק/י user_id תקין או @username קיים.")
            return

        # HTML-safe with preserved whitespace/newlines
        safe = "<pre>" + html.escape(message_text) + "</pre>"

        try:
            await context.bot.send_message(
                chat_id=target_id,
                text=safe,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
            await update.message.reply_text(f"✅ ההודעה נשלחה ל-{target_id} ({len(message_text)} תווים)")
        except telegram.error.RetryAfter as e:
            # המתן ונסה שוב פעם אחת
            try:
                await asyncio.sleep(float(getattr(e, 'retry_after', 1.0)) + 0.5)
                await context.bot.send_message(
                    chat_id=target_id,
                    text=safe,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                )
                await update.message.reply_text(f"✅ ההודעה נשלחה ל-{target_id} לאחר המתנה (Rate Limit)")
            except Exception as e2:
                await update.message.reply_text(f"❌ שליחה נכשלה לאחר המתנה: {type(e2).__name__}")
        except telegram.error.Forbidden:
            # ייתכן שהמשתמש חסם את הבוט – נסמן ב-DB
            try:
                if hasattr(db, 'db') and db.db is not None and hasattr(db.db, 'users'):
                    db.db.users.update_one({"user_id": target_id}, {"$set": {"blocked": True}})
            except Exception:
                pass
            await update.message.reply_text("⚠️ לא ניתן לשלוח (המשתמש חסם את הבוט או בוטק). סומן כ-blocked.")
        except Exception as e:
            await update.message.reply_text(f"❌ שגיאה בשליחה: {type(e).__name__}")
    
    async def handle_callback_query(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """טיפול בלחיצות על כפתורים"""
        reporter.report_activity(update.effective_user.id)
        query = update.callback_query
        await query.answer()
        
        data = query.data
        try:
            user_obj = getattr(query, 'from_user', None) or getattr(update, 'effective_user', None)
            user_id = int(getattr(user_obj, 'id', 0) or 0)
        except Exception:
            user_id = 0
        
        try:
            if data.startswith("confirm_delete_"):
                file_name = data.replace("confirm_delete_", "")
                
                if db.delete_file(user_id, file_name):
                    await query.edit_message_text(
                        f"✅ הקובץ `{file_name}` נמחק בהצלחה!",
                        parse_mode=ParseMode.MARKDOWN
                    )
                else:
                    await query.edit_message_text("❌ שגיאה במחיקת הקובץ.")
            
            elif data == "cancel_delete":
                await query.edit_message_text("❌ מחיקה בוטלה.")
            
            elif data == "cancel_share":
                # ביטול תיבת השיתוף (יחיד/מרובה)
                await query.edit_message_text("❌ השיתוף בוטל.")
                try:
                    # ניקוי הקשר מרובה אם נשמר
                    ms = context.user_data.get('multi_share')
                    if isinstance(ms, dict) and not ms:
                        context.user_data.pop('multi_share', None)
                except Exception:
                    pass
            
            elif data.startswith("highlight_"):
                file_name = data.replace("highlight_", "")
                await self._send_highlighted_code(query, user_id, file_name)
            
            elif data.startswith("share_gist_multi:"):
                share_id = data.split(":", 1)[1]
                await self._share_to_gist_multi(query, context, user_id, share_id)
            
            elif data.startswith("share_gist_"):
                file_name = data.replace("share_gist_", "")
                await self._share_to_gist(query, user_id, file_name)
            
            elif data.startswith("share_pastebin_"):
                file_name = data.replace("share_pastebin_", "")
                await self._share_to_pastebin(query, user_id, file_name)
            
            elif data.startswith("share_internal_"):
                file_name = data.replace("share_internal_", "")
                await self._share_internal(query, user_id, file_name)

            # הסרנו noop/‏share_noop — אין צורך עוד

            elif data.startswith("share_internal_multi:"):
                share_id = data.split(":", 1)[1]
                await self._share_internal_multi(query, context, user_id, share_id)
            
            elif data.startswith("download_"):
                file_name = data.replace("download_", "")
                await self._send_file_download(query, user_id, file_name)
            
            # --- Image generation callbacks ---
            elif data.startswith("regenerate_image_"):
                _suffix = data.replace("regenerate_image_", "")
                file_name = self._resolve_image_target(context, _suffix)
                # Rate limit for expensive regeneration
                try:
                    allowed = await image_rate_limiter.check_rate_limit(user_id)
                except Exception:
                    allowed = True
                if not allowed:
                    await query.answer("⏱️ יותר מדי בקשות. אנא נסה שוב בעוד דקה.", show_alert=True)
                    return
                doc = db.get_latest_version(user_id, file_name)
                if not doc or not doc.get('code'):
                    await query.edit_message_text(f"❌ קובץ `{html.escape(file_name)}` לא נמצא או ריק.", parse_mode=ParseMode.MARKDOWN)
                    return
                settings = self._get_image_settings(context, file_name)
                style = str(settings.get('style') or IMAGE_CONFIG.get('default_style') or 'monokai')
                theme = str(settings.get('theme') or IMAGE_CONFIG.get('default_theme') or 'dark')
                width = int(settings.get('width') or IMAGE_CONFIG.get('default_width') or 1200)
                gen = CodeImageGenerator(style=style, theme=theme)
                try:
                    img = gen.generate_image(code=str(doc['code']), language=str(doc.get('programming_language') or 'text'), filename=file_name, max_width=width)
                finally:
                    try:
                        gen.cleanup()  # type: ignore[attr-defined]
                    except Exception:
                        pass
                bio = io.BytesIO(img)
                bio.name = f"{file_name}.png"
                # צרף מקלדת עדכנית גם להודעת ה-reply החדשה
                regen_suffix = self._make_safe_suffix(context, "regenerate_image_", file_name)
                edit_suffix = self._make_safe_suffix(context, "edit_image_settings_", file_name)
                save_suffix = self._make_safe_suffix(context, "save_to_drive_", file_name)
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 יצור מחדש", callback_data=f"regenerate_image_{regen_suffix}"),
                     InlineKeyboardButton("📝 ערוך הגדרות", callback_data=f"edit_image_settings_{edit_suffix}")],
                    [InlineKeyboardButton("💾 שמור ב-Drive", callback_data=f"save_to_drive_{save_suffix}")]
                ])
                await query.message.reply_photo(
                    photo=InputFile(bio, filename=bio.name),
                    caption=f"🔄 נוצר מחדש: <code>{html.escape(file_name)}</code>",
                    parse_mode=ParseMode.HTML,
                    reply_markup=kb,
                )

            elif data.startswith("edit_image_settings_"):
                _suffix = data.replace("edit_image_settings_", "")
                file_name = self._resolve_image_target(context, _suffix)
                # בנה מקלדת לבחירת תמה ורוחב – ודא ש-callbacks קצרים
                theme_suffix = self._make_safe_suffix(context, "img_set_theme:", file_name)
                width_suffix = self._make_safe_suffix(context, "img_set_width:", file_name)
                # הוסף הפרדה ':' רק כאשר משתמשים ב-suffix (יתמוך גם ב-tok:<...>)
                def _mk_theme_cb(val: str) -> str:
                    return f"img_set_theme:{val}:{theme_suffix}"
                def _mk_width_cb(val: int) -> str:
                    return f"img_set_width:{val}:{width_suffix}"
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("🎨 Dark", callback_data=_mk_theme_cb("dark")),
                     InlineKeyboardButton("🌤️ Light", callback_data=_mk_theme_cb("light"))],
                    [InlineKeyboardButton("🐙 GitHub", callback_data=_mk_theme_cb("github")),
                     InlineKeyboardButton("🎯 Monokai", callback_data=_mk_theme_cb("monokai"))],
                    [InlineKeyboardButton("⬅️ 800px", callback_data=_mk_width_cb(800)),
                     InlineKeyboardButton("➡️ 1400px", callback_data=_mk_width_cb(1400))],
                    [InlineKeyboardButton("✅ סגור", callback_data="cancel_share")]
                ])
                await query.edit_message_text("🛠️ עריכת הגדרות תמונה – בחר תמה/רוחב ואז לחץ 'יצור מחדש'", reply_markup=kb)

            elif data.startswith("img_set_theme:"):
                try:
                    _, theme, suffix = data.split(":", 2)
                except ValueError:
                    await query.answer("⚠️ נתונים שגויים", show_alert=False)
                    return
                file_name = self._resolve_image_target(context, suffix)
                self._set_image_setting(context, file_name, 'theme', theme)
                await query.answer("🎨 עודכן!", show_alert=False)

            elif data.startswith("img_set_width:"):
                try:
                    _, width_s, suffix = data.split(":", 2)
                    width = int(width_s)
                except Exception:
                    await query.answer("⚠️ רוחב לא תקין", show_alert=False)
                    return
                file_name = self._resolve_image_target(context, suffix)
                self._set_image_setting(context, file_name, 'width', width)
                await query.answer("📏 עודכן!", show_alert=False)

            elif data.startswith("save_to_drive_"):
                _suffix = data.replace("save_to_drive_", "")
                file_name = self._resolve_image_target(context, _suffix)
                # Rate limit for potentially heavy generation+upload
                try:
                    allowed = await image_rate_limiter.check_rate_limit(user_id)
                except Exception:
                    allowed = True
                if not allowed:
                    await query.answer("⏱️ יותר מדי בקשות. אנא נסה שוב בעוד דקה.", show_alert=True)
                    return
                doc = db.get_latest_version(user_id, file_name)
                if not doc or not doc.get('code'):
                    await query.edit_message_text(f"❌ קובץ `{html.escape(file_name)}` לא נמצא או ריק.", parse_mode=ParseMode.MARKDOWN)
                    return
                settings = self._get_image_settings(context, file_name)
                style = str(settings.get('style') or IMAGE_CONFIG.get('default_style') or 'monokai')
                theme = str(settings.get('theme') or IMAGE_CONFIG.get('default_theme') or 'dark')
                width = int(settings.get('width') or IMAGE_CONFIG.get('default_width') or 1200)
                gen = CodeImageGenerator(style=style, theme=theme)
                try:
                    img = gen.generate_image(code=str(doc['code']), language=str(doc.get('programming_language') or 'text'), filename=file_name, max_width=width)
                finally:
                    try:
                        gen.cleanup()  # type: ignore[attr-defined]
                    except Exception:
                        pass
                # העלאה ל-Drive
                try:
                    from services.google_drive_service import upload_bytes  # type: ignore
                    fid = upload_bytes(user_id, filename=f"{file_name}.png", data=img, sub_path="code_images")
                except Exception:
                    fid = None
                if fid:
                    await query.edit_message_text(f"✅ נשמר ל-Drive (id: <code>{html.escape(str(fid))}</code>)", parse_mode=ParseMode.HTML)
                else:
                    await query.edit_message_text("⚠️ שמירה ל-Drive לא הצליחה (בדוק הרשאות/חיבור)")

            # ועוד callback handlers...

            # --- ChatOps: /errors inline examples ---
            elif data.startswith("err_ex:"):
                try:
                    # הרשאות: אדמינים בלבד
                    if not self._is_admin(user_id):
                        await query.message.reply_text("❌ פקודה זמינה למנהלים בלבד")
                        return
                except Exception:
                    pass
                token = data.split(":", 1)[1]
                try:
                    sig = (context.user_data.get('errors_sig_tokens') or {}).get(token)
                except Exception:
                    sig = None
                if not sig:
                    await query.answer("כפתור פג תוקף", show_alert=False)
                    return
                # אסוף עד 5 דוגמאות מהבאפר המקומי
                try:
                    from observability import get_recent_errors  # type: ignore
                    examples = []
                    for er in (get_recent_errors(limit=200) or []):
                        if str(er.get("error_signature") or er.get("event") or "") == sig:
                            ts = str(er.get("ts") or er.get("timestamp") or "")
                            msg = str(er.get("error") or er.get("event") or "")
                            examples.append(f"• {ts} – {msg}")
                            if len(examples) >= 5:
                                break
                    header = f"🔎 דוגמאות לשגיאות עבור החתימה: {sig}"
                    # קישור Sentry (אם זמין)
                    try:
                        from urllib.parse import quote_plus
                        dsn = os.getenv("SENTRY_DSN") or ""
                        host = None
                        if dsn:
                            from urllib.parse import urlparse
                            parsed = urlparse(dsn)
                            raw_host = parsed.hostname or ''
                            if raw_host == 'sentry.io' or raw_host.endswith('.sentry.io'):
                                host = 'sentry.io'
                            elif raw_host.startswith('ingest.'):
                                host = raw_host[len('ingest.'):]
                            else:
                                host = raw_host or None
                        host = host or 'sentry.io'
                        org = os.getenv("SENTRY_ORG") or os.getenv("SENTRY_ORG_SLUG")
                        if org:
                            q = quote_plus(f'error_signature:"{sig}"')
                            link = f"https://{host}/organizations/{org}/issues/?query={q}&statsPeriod=24h"
                            header += f"\nSentry: {link}"
                    except Exception:
                        pass
                    if not examples:
                        await query.message.reply_text(header + "\n(אין דוגמאות זמינות לחתימה זו)")
                    else:
                        await query.message.reply_text("\n".join([header] + examples))
                except Exception:
                    await query.message.reply_text("(כשל באיסוף דוגמאות)")
                    return

            # --- Favorites callbacks ---
            elif data == "favorites_list":
                favs = db.get_favorites(user_id, limit=50)
                if not favs:
                    await query.edit_message_text("💭 אין לך מועדפים כרגע.")
                    return
                from utils import get_language_emoji
                lines = ["⭐ <b>המועדפים שלך</b>\n"]
                for idx, fav in enumerate(favs[:10], 1):
                    fname = fav.get('file_name', '')
                    lang = fav.get('programming_language', '')
                    lines.append(f"{idx}. {get_language_emoji(lang)} <code>{html.escape(str(fname))}</code>")
                if len(favs) > 10:
                    lines.append(f"\n➕ ועוד {len(favs) - 10} קבצים...")
                await query.edit_message_text("\n".join(lines), parse_mode=ParseMode.HTML)

            elif data == "export_favorites":
                favs = db.get_favorites(user_id, limit=200)
                export_data = {
                    "exported_at": datetime.now(timezone.utc).isoformat(),
                    "user_id": user_id,
                    "total_favorites": len(favs),
                    "favorites": favs,
                }
                raw = json.dumps(export_data, ensure_ascii=False, indent=2)
                bio = io.BytesIO(raw.encode('utf-8'))
                bio.name = "favorites.json"
                # שליחה עם BytesIO כפרמטר ראשון כדי לאפשר לטסטים לחלץ את התוכן
                await query.message.reply_document(bio, filename="favorites.json", caption="📥 ייצוא מועדפים (JSON)")
                await query.edit_message_text("✅ קובץ ייצוא נשלח")

            elif data == "favorites_stats":
                favs = db.get_favorites(user_id, limit=500)
                if not favs:
                    await query.edit_message_text("💭 אין סטטיסטיקות - אין מועדפים")
                    return
                langs: Dict[str, int] = {}
                all_tags: List[str] = []
                for f in favs:
                    lang = (f.get('programming_language') or 'unknown')
                    langs[lang] = langs.get(lang, 0) + 1
                    try:
                        for t in (f.get('tags') or []):
                            if isinstance(t, str):
                                all_tags.append(t)
                    except Exception:
                        pass
                popular_lang = max(langs.items(), key=lambda x: x[1]) if langs else ("אין", 0)
                from collections import Counter
                top_tags = Counter(all_tags).most_common(3)
                text = (
                    "📊 <b>סטטיסטיקות מועדפים</b>\n\n"
                    f"⭐ סך המועדפים: {len(favs)}\n\n"
                    f"🔤 שפה פופולרית:\n   {popular_lang[0]} ({popular_lang[1]})\n"
                )
                if top_tags:
                    text += "\n🏷️ תגיות פופולריות:\n" + "\n".join([f"   #{t} ({c})" for t, c in top_tags])
                await query.edit_message_text(text, parse_mode=ParseMode.HTML)

            elif data.startswith("fav_toggle_id:"):
                fid = data.split(":", 1)[1]
                try:
                    doc = db.get_file_by_id(fid)
                except Exception:
                    doc = None
                if not doc:
                    await query.answer("⚠️ הקובץ לא נמצא", show_alert=False)
                    return
                fname = doc.get('file_name')
                state = db.toggle_favorite(user_id, fname)
                await query.answer("⭐ נוסף למועדפים!" if state else "💔 הוסר מהמועדפים", show_alert=False)
                # אם אנחנו במסך בקרה/פעולות, הצג הודעת סטטוס מעל הכפתורים ושמור את המקלדת
                try:
                    # שלוף פרטים להצגה
                    latest = db.get_latest_version(user_id, fname) or {}
                    lang = latest.get('programming_language') or 'text'
                    note = latest.get('description') or '—'
                    notice = ("⭐️ הקוד נשמר במועדפים" if state else "💔 הקוד הוסר מהמועדפים")
                    from html import escape as _e
                    new_text = (
                        f"{notice}\n\n"
                        f"📄 קובץ: <code>{_e(str(fname))}</code>\n"
                        f"🧠 שפה: {_e(str(lang))}\n"
                        f"📝 הערה: {_e(str(note))}\n\n"
                        f"🎮 בחר פעולה מתקדמת:"
                    )
                    # בנה מקלדת מעודכנת עם תווית כפתור מועדפים הנכונה
                    try:
                        is_fav_now = bool(db.is_favorite(user_id, fname))
                    except Exception:
                        is_fav_now = state
                    fav_label = "💔 הסר ממועדפים" if is_fav_now else "⭐ הוסף למועדפים"
                    # נעדיף שימוש ב-id אם זמין
                    fav_cb = f"fav_toggle_id:{fid}" if fid else f"fav_toggle_tok:{fname}"
                    from telegram import InlineKeyboardButton as _IKB, InlineKeyboardMarkup as _IKM
                    updated_kb = _IKM([[ _IKB(fav_label, callback_data=fav_cb) ]])
                    await query.edit_message_text(new_text, parse_mode=ParseMode.HTML, reply_markup=updated_kb)
                except Exception:
                    pass

            elif data.startswith("fav_toggle_tok:"):
                token = data.split(":", 1)[1]
                try:
                    fname = (context.user_data.get('fav_tokens') or {}).get(token)
                except Exception:
                    fname = None
                if not fname:
                    await query.answer("⚠️ לא נמצא קובץ לפעולה", show_alert=True)
                    return
                state = db.toggle_favorite(user_id, fname)
                await query.answer("⭐ נוסף למועדפים!" if state else "💔 הוסר מהמועדפים", show_alert=False)
                try:
                    latest = db.get_latest_version(user_id, fname) or {}
                    lang = latest.get('programming_language') or 'text'
                    note = latest.get('description') or '—'
                    notice = ("⭐️ הקוד נשמר במועדפים" if state else "💔 הקוד הוסר מהמועדפים")
                    from html import escape as _e
                    new_text = (
                        f"{notice}\n\n"
                        f"📄 קובץ: <code>{_e(str(fname))}</code>\n"
                        f"🧠 שפה: {_e(str(lang))}\n"
                        f"📝 הערה: {_e(str(note))}\n\n"
                        f"🎮 בחר פעולה מתקדמת:"
                    )
                    try:
                        is_fav_now = bool(db.is_favorite(user_id, fname))
                    except Exception:
                        is_fav_now = state
                    fav_label = "💔 הסר ממועדפים" if is_fav_now else "⭐ הוסף למועדפים"
                    fav_cb = f"fav_toggle_tok:{token}"
                    from telegram import InlineKeyboardButton as _IKB, InlineKeyboardMarkup as _IKM
                    updated_kb = _IKM([[ _IKB(fav_label, callback_data=fav_cb) ]])
                    await query.edit_message_text(new_text, parse_mode=ParseMode.HTML, reply_markup=updated_kb)
                except Exception:
                    pass
            
        except Exception as e:
            logger.error(f"שגיאה ב-callback: {e}")
            await query.edit_message_text("❌ אירעה שגיאה. נסה שוב.")
    
    async def _send_highlighted_code(self, query, user_id: int, file_name: str):
        """שליחת קוד עם הדגשת תחביר"""
        file_data = db.get_latest_version(user_id, file_name)
        
        if not file_data:
            await query.edit_message_text(f"❌ קובץ `{file_name}` לא נמצא.")
            return
        
        # יצירת קוד מודגש
        highlighted = code_processor.highlight_code(
            file_data['code'], 
            file_data['programming_language']
        )
        
        # שליחה כקובץ HTML אם הקוד ארוך
        if len(file_data['code']) > 500:
            html_content = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="utf-8">
                <title>{file_name}</title>
                <style>body {{ font-family: monospace; }}</style>
            </head>
            <body>
                {highlighted}
            </body>
            </html>
            """
            
            html_file = io.BytesIO(html_content.encode('utf-8'))
            html_file.name = f"{file_name}.html"
            
            await query.message.reply_document(
                document=InputFile(html_file, filename=f"{file_name}.html"),
                caption=f"🎨 קוד מודגש עבור `{file_name}`"
            )
        else:
            # שליחה כהודעה
            await query.edit_message_text(
                f"🎨 **קוד מודגש עבור:** `{file_name}`\n\n"
                f"```{file_data['programming_language']}\n{file_data['code']}\n```",
                parse_mode=ParseMode.MARKDOWN
            )

    async def _send_long_message(self, msg_target, text: str, parse_mode: Optional[str] = None, reply_markup: Optional[InlineKeyboardMarkup] = None) -> None:
        """שליחת טקסט ארוך במספר הודעות, מפוצל לפי אורך בטוח לטלגרם.

        מגבלת אורך הודעת טלגרם היא סביב 4096 תווים. נשתמש במרווח בטחון.
        """
        try:
            MAX_LEN = 3500
            remaining = text or ""
            if len(remaining) <= MAX_LEN:
                await msg_target.reply_text(remaining, parse_mode=parse_mode, reply_markup=reply_markup)
                return
            # פיצול לפי שורות כדי לשמור על פירוק טבעי
            lines = (remaining.split("\n") if remaining else [])
            buf: list[str] = []
            curr = 0
            for line in lines:
                # +1 עבור ה"\n" שיתווסף בהמשך
                line_len = len(line) + (1 if buf else 0)
                if curr + line_len > MAX_LEN:
                    chunk = "\n".join(buf)
                    await msg_target.reply_text(chunk, parse_mode=parse_mode)
                    buf = [line]
                    curr = len(line)
                else:
                    buf.append(line)
                    curr += line_len
            if buf:
                chunk = "\n".join(buf)
                await msg_target.reply_text(chunk, parse_mode=parse_mode, reply_markup=reply_markup)
        except Exception:
            # במקרה חריג, שלח את הכל בהודעה אחת (עלול לחרוג אם ארוך מדי)
            await msg_target.reply_text(text or "", parse_mode=parse_mode, reply_markup=reply_markup)
    
    async def _share_to_gist(self, query, user_id: int, file_name: str):
        """שיתוף ב-GitHub Gist"""
        
        if not config.GITHUB_TOKEN:
            await query.edit_message_text(
                "❌ שיתוף ב-Gist לא זמין - לא הוגדר טוקן GitHub."
            )
            return
        
        file_data = db.get_latest_version(user_id, file_name)
        
        if not file_data:
            await query.edit_message_text(f"❌ קובץ `{file_name}` לא נמצא.")
            return
        
        try:
            from integrations import code_sharing
            description = f"שיתוף אוטומטי דרך CodeBot — {file_name}"
            result = await code_sharing.share_code(
                service="gist",
                file_name=file_name,
                code=file_data["code"],
                language=file_data["programming_language"],
                description=description,
                public=True
            )
            if not result or not result.get("url"):
                await query.edit_message_text("❌ יצירת Gist נכשלה. ודא שטוקן GitHub תקין והרשאות מתאימות.")
                return
            await query.edit_message_text(
                f"🐙 **שותף ב-GitHub Gist!**\n\n"
                f"📄 קובץ: `{file_name}`\n"
                f"🔗 קישור: {result['url']}",
                parse_mode=ParseMode.MARKDOWN
            )
            
        except Exception as e:
            logger.error(f"שגיאה בשיתוף Gist: {e}")
            await query.edit_message_text("❌ שגיאה בשיתוף. נסה שוב מאוחר יותר.")

    async def _share_to_pastebin(self, query, user_id: int, file_name: str):
        """שיתוף ב-Pastebin"""
        from integrations import code_sharing
        file_data = db.get_latest_version(user_id, file_name)
        if not file_data:
            await query.edit_message_text(f"❌ קובץ `{file_name}` לא נמצא.")
            return
        try:
            result = await code_sharing.share_code(
                service="pastebin",
                file_name=file_name,
                code=file_data["code"],
                language=file_data["programming_language"],
                private=True,
                expire="1M"
            )
            if not result or not result.get("url"):
                await query.edit_message_text("❌ יצירת Pastebin נכשלה. בדוק מפתח API.")
                return
            await query.edit_message_text(
                f"📋 **שותף ב-Pastebin!**\n\n"
                f"📄 קובץ: `{file_name}`\n"
                f"🔗 קישור: {result['url']}",
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception as e:
            logger.error(f"שגיאה בשיתוף Pastebin: {e}")
            await query.edit_message_text("❌ שגיאה בשיתוף. נסה שוב מאוחר יותר.")

    async def _share_internal(self, query, user_id: int, file_name: str):
        """יצירת קישור שיתוף פנימי"""
        from integrations import code_sharing
        file_data = db.get_latest_version(user_id, file_name)
        if not file_data:
            await query.edit_message_text(f"❌ קובץ `{file_name}` לא נמצא.")
            return
        try:
            result = await code_sharing.share_code(
                service="internal",
                file_name=file_name,
                code=file_data["code"],
                language=file_data["programming_language"],
                description=f"שיתוף פנימי של {file_name}"
            )
            if not result or not result.get("url"):
                await query.edit_message_text("❌ יצירת קישור פנימי נכשלה.")
                return
            if not config.PUBLIC_BASE_URL:
                await query.edit_message_text(
                    "ℹ️ קישור פנימי אינו זמין כרגע (לא הוגדר PUBLIC_BASE_URL).\n"
                    "באפשרותך להשתמש ב-Gist/Pastebin במקום.")
                return
            # ניסוח תוקף קריא
            expires_iso = result.get('expires_at', '')
            expiry_line = f"⏳ תוקף: {expires_iso}"
            try:
                dt = datetime.fromisoformat(expires_iso)
                now = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.now()
                delta = dt - now
                total_seconds = int(delta.total_seconds())
                if total_seconds > 0:
                    days = total_seconds // 86400
                    hours = (total_seconds % 86400) // 3600
                    if days > 0:
                        rel = f"בעוד ~{days} ימים" + (f" ו-{hours} שעות" if hours > 0 else "")
                    elif hours > 0:
                        rel = f"בעוד ~{hours} שעות"
                    else:
                        minutes = (total_seconds % 3600) // 60
                        rel = f"בעוד ~{minutes} דקות"
                else:
                    rel = "פג"
                date_str = dt.strftime("%d/%m/%Y %H:%M")
                expiry_line = f"⏳ תוקף: {date_str} ({rel})"
            except Exception:
                pass
            safe_file = html.escape(file_name)
            safe_url = html.escape(result['url'])
            safe_expiry = html.escape(expiry_line)
            await query.edit_message_text(
                f"📱 <b>נוצר קישור פנימי!</b>\n\n"
                f"📄 קובץ: <code>{safe_file}</code>\n"
                f"🔗 קישור: <a href=\"{safe_url}\">{safe_url}</a>\n"
                f"{safe_expiry}",
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            logger.error(f"שגיאה ביצירת קישור פנימי: {e}")
            await query.edit_message_text("❌ שגיאה בשיתוף. נסה שוב מאוחר יותר.")

    async def _share_to_gist_multi(self, query, context: ContextTypes.DEFAULT_TYPE, user_id: int, share_id: str):
        """שיתוף מספר קבצים לגיסט אחד"""
        from integrations import gist_integration
        files_map: Dict[str, str] = {}
        names: List[str] = (context.user_data.get('multi_share', {}).get(share_id) or [])
        if not names:
            await query.edit_message_text("❌ לא נמצאה רשימת קבצים עבור השיתוף.")
            return
        for fname in names:
            data = db.get_latest_version(user_id, fname)
            if data:
                files_map[data['file_name']] = data['code']
        if not files_map:
            await query.edit_message_text("❌ לא נמצאו קבצים פעילים לשיתוף.")
            return
        if not config.GITHUB_TOKEN:
            await query.edit_message_text("❌ שיתוף ב-Gist לא זמין - אין GITHUB_TOKEN.")
            return
        try:
            description = f"שיתוף מרובה קבצים ({len(files_map)}) דרך {config.BOT_LABEL}"
            result = gist_integration.create_gist_multi(files_map=files_map, description=description, public=True)
            if not result or not result.get("url"):
                await query.edit_message_text("❌ יצירת Gist מרובה קבצים נכשלה.")
                return
            await query.edit_message_text(
                f"🐙 **שותף ב-GitHub Gist (מרובה קבצים)!**\n\n"
                f"📄 קבצים: {len(files_map)}\n"
                f"🔗 קישור: {result['url']}",
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception as e:
            logger.error(f"שגיאה בשיתוף גיסט מרובה: {e}")
            await query.edit_message_text("❌ שגיאה בשיתוף. נסה שוב מאוחר יותר.")
        finally:
            try:
                context.user_data.get('multi_share', {}).pop(share_id, None)
            except Exception:
                pass

    async def _share_internal_multi(self, query, context: ContextTypes.DEFAULT_TYPE, user_id: int, share_id: str):
        """יצירת קישור פנימי למספר קבצים — מאחד לקובץ טקסט אחד"""
        from integrations import code_sharing
        names: List[str] = (context.user_data.get('multi_share', {}).get(share_id) or [])
        if not names:
            await query.edit_message_text("❌ לא נמצאה רשימת קבצים עבור השיתוף.")
            return
        # נאחד לקובץ טקסט אחד קצר עם מפרידים
        bundle_parts: List[str] = []
        lang_hint = None
        for fname in names:
            data = db.get_latest_version(user_id, fname)
            if data:
                lang_hint = lang_hint or data['programming_language']
                bundle_parts.append(f"// ==== {data['file_name']} ====\n{data['code']}\n")
        if not bundle_parts:
            await query.edit_message_text("❌ לא נמצאו קבצים לשיתוף פנימי.")
            return
        combined_code = "\n".join(bundle_parts)
        try:
            result = await code_sharing.share_code(
                service="internal",
                file_name=f"bundle-{share_id}.txt",
                code=combined_code,
                language=lang_hint or "text",
                description=f"שיתוף פנימי מרובה קבצים ({len(names)})"
            )
            if not result or not result.get("url"):
                await query.edit_message_text("❌ יצירת קישור פנימי נכשלה.")
                return
            if not config.PUBLIC_BASE_URL:
                await query.edit_message_text(
                    "ℹ️ קישור פנימי אינו זמין כרגע (לא הוגדר PUBLIC_BASE_URL).\n"
                    "באפשרותך להשתמש ב-Gist במרובה קבצים.")
                return
            # ניסוח תוקף קריא
            expires_iso = result.get('expires_at', '')
            expiry_line = f"⏳ תוקף: {expires_iso}"
            try:
                dt = datetime.fromisoformat(expires_iso)
                now = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.now()
                delta = dt - now
                total_seconds = int(delta.total_seconds())
                if total_seconds > 0:
                    days = total_seconds // 86400
                    hours = (total_seconds % 86400) // 3600
                    if days > 0:
                        rel = f"בעוד ~{days} ימים" + (f" ו-{hours} שעות" if hours > 0 else "")
                    elif hours > 0:
                        rel = f"בעוד ~{hours} שעות"
                    else:
                        minutes = (total_seconds % 3600) // 60
                        rel = f"בעוד ~{minutes} דקות"
                else:
                    rel = "פג"
                date_str = dt.strftime("%d/%m/%Y %H:%M")
                expiry_line = f"⏳ תוקף: {date_str} ({rel})"
            except Exception:
                pass
            safe_url = html.escape(result['url'])
            safe_expiry = html.escape(expiry_line)
            await query.edit_message_text(
                f"📱 <b>נוצר קישור פנימי (מרובה קבצים)!</b>\n\n"
                f"📄 קבצים: {len(names)}\n"
                f"🔗 קישור: <a href=\"{safe_url}\">{safe_url}</a>\n"
                f"{safe_expiry}",
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            logger.error(f"שגיאה בקישור פנימי מרובה: {e}")
            await query.edit_message_text("❌ שגיאה בשיתוף. נסה שוב מאוחר יותר.")
        finally:
            try:
                context.user_data.get('multi_share', {}).pop(share_id, None)
            except Exception:
                pass

    async def _send_file_download(self, query, user_id: int, file_name: str):
        file_data = db.get_latest_version(user_id, file_name)
        if not file_data:
            await query.edit_message_text(f"❌ קובץ `{file_name}` לא נמצא.")
            return
        await query.message.reply_document(document=InputFile(io.BytesIO(file_data['code'].encode('utf-8')), filename=f"{file_name}"))

    # --- Image generation commands ---------------------------------------
    async def image_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """יצירת תמונת PNG מהקוד עבור קובץ נתון."""
        reporter.report_activity(update.effective_user.id)
        user_id = update.effective_user.id

        # שימוש בסיסי והסבר קצר
        if not context.args:
            await update.message.reply_text(
                "🖼️ <b>יצירת תמונת קוד</b>\n"
                "שימוש: <code>/image &lt;file_name&gt;</code>",
                parse_mode=ParseMode.HTML,
            )
            return

        # Rate limiting
        try:
            allowed = await image_rate_limiter.check_rate_limit(user_id)
        except Exception:
            allowed = True  # אל תשבור את הזרימה במקרה חריג
        if not allowed:
            await update.message.reply_text("⏱️ יותר מדי בקשות. אנא נסה שוב בעוד דקה.")
            return

        file_name = " ".join(context.args)
        file_data = db.get_latest_version(user_id, file_name)
        if not file_data:
            safe = html.escape(file_name)
            await update.message.reply_text(f"❌ קובץ <code>{safe}</code> לא נמצא.", parse_mode=ParseMode.HTML)
            return

        code = str(file_data.get('code') or '')
        language = str(file_data.get('programming_language') or 'text')
        if not code:
            await update.message.reply_text("❌ הקובץ ריק.")
            return

        try:
            # העדפות מתצורה/הקשר
            settings = self._get_image_settings(context, file_name)
            style = str(settings.get('style') or IMAGE_CONFIG.get('default_style') or 'monokai')
            theme = str(settings.get('theme') or IMAGE_CONFIG.get('default_theme') or 'dark')
            width = int(settings.get('width') or IMAGE_CONFIG.get('default_width') or 1200)

            generator = CodeImageGenerator(style=style, theme=theme)
            try:
                image_bytes = generator.generate_image(code=code, language=language, filename=file_name, max_width=width)
            finally:
                try:
                    generator.cleanup()  # type: ignore[attr-defined]
                except Exception:
                    pass

            bio = io.BytesIO(image_bytes)
            bio.name = f"{file_name}.png"
            safe_name = html.escape(file_name)
            safe_lang = html.escape(language)
            # כפתורים מתקדמים – ודא עמידה במגבלת 64 בתים של טלגרם
            regen_suffix = self._make_safe_suffix(context, "regenerate_image_", file_name)
            edit_suffix = self._make_safe_suffix(context, "edit_image_settings_", file_name)
            save_suffix = self._make_safe_suffix(context, "save_to_drive_", file_name)
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 יצור מחדש", callback_data=f"regenerate_image_{regen_suffix}"),
                 InlineKeyboardButton("📝 ערוך הגדרות", callback_data=f"edit_image_settings_{edit_suffix}")],
                [InlineKeyboardButton("💾 שמור ב-Drive", callback_data=f"save_to_drive_{save_suffix}")]
            ])
            await update.message.reply_photo(
                photo=InputFile(bio, filename=f"{file_name}.png"),
                caption=(
                    f"🖼️ <b>תמונת קוד:</b> <code>{safe_name}</code>\n"
                    f"🔤 שפה: {safe_lang} | 🎨 תמה: {html.escape(theme)} | 🧩 סגנון: {html.escape(style)}"
                ),
                parse_mode=ParseMode.HTML,
                reply_markup=kb,
            )
        except ImportError as e:
            await update.message.reply_text(
                f"❌ שגיאה: חסרות ספריות נדרשות.\n<code>{html.escape(str(e))}</code>",
                parse_mode=ParseMode.HTML,
            )
        except Exception as e:
            logger.error(f"Error generating image: {e}", exc_info=True)
            await update.message.reply_text(
                f"❌ שגיאה ביצירת תמונה: <code>{html.escape(str(e))}</code>",
                parse_mode=ParseMode.HTML,
            )

    async def preview_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """תצוגה מקדימה (עד 50 שורות, רוחב 800px)."""
        reporter.report_activity(update.effective_user.id)
        user_id = update.effective_user.id

        if not context.args:
            await update.message.reply_text(
                "👁️ <b>תצוגה מקדימה</b>\n"
                "שימוש: <code>/preview &lt;file_name&gt;</code>",
                parse_mode=ParseMode.HTML,
            )
            return

        # Rate limit עדין גם כאן
        try:
            allowed = await image_rate_limiter.check_rate_limit(user_id)
        except Exception:
            allowed = True
        if not allowed:
            await update.message.reply_text("⏱️ יותר מדי בקשות. אנא נסה שוב בעוד דקה.")
            return

        file_name = " ".join(context.args)
        file_data = db.get_latest_version(user_id, file_name)
        if not file_data:
            safe = html.escape(file_name)
            await update.message.reply_text(f"❌ קובץ <code>{safe}</code> לא נמצא.", parse_mode=ParseMode.HTML)
            return

        code = str(file_data.get('code') or '')
        language = str(file_data.get('programming_language') or 'text')
        lines = code.splitlines()
        max_preview_lines = int(((IMAGE_CONFIG.get('preview') or {}).get('max_lines')) or 50)
        if len(lines) > max_preview_lines:
            code = "\n".join(lines[:max_preview_lines]) + "\n..."

        try:
            style = str(IMAGE_CONFIG.get('default_style') or 'monokai')
            theme = str(IMAGE_CONFIG.get('default_theme') or 'dark')
            prev_w = int(((IMAGE_CONFIG.get('preview') or {}).get('width')) or 800)
            generator = CodeImageGenerator(style=style, theme=theme)
            try:
                image_bytes = generator.generate_image(code=code, language=language, filename=file_name, max_width=prev_w, max_height=1500)
            finally:
                try:
                    generator.cleanup()  # type: ignore[attr-defined]
                except Exception:
                    pass
            bio = io.BytesIO(image_bytes)
            bio.name = f"preview_{file_name}.png"
            safe_name = html.escape(file_name)
            await update.message.reply_photo(
                photo=InputFile(bio, filename=bio.name),
                caption=f"👁️ תצוגה מקדימה: <code>{safe_name}</code>",
                parse_mode=ParseMode.HTML,
            )
        except Exception as e:
            logger.error(f"Preview error: {e}")
            await update.message.reply_text(f"❌ שגיאה: <code>{html.escape(str(e))}</code>", parse_mode=ParseMode.HTML)

    async def image_all_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """יצירת תמונות לכל הקבצים של המשתמש (עד 20)."""
        reporter.report_activity(update.effective_user.id)
        user_id = update.effective_user.id

        # בדיקה רכה של Rate limit
        try:
            allowed = await image_rate_limiter.check_rate_limit(user_id)
        except Exception:
            allowed = True
        if not allowed:
            await update.message.reply_text("⏱️ יותר מדי בקשות. אנא נסה שוב בעוד דקה.")
            return

        files = db.get_user_files(user_id, limit=20)
        if not files:
            await update.message.reply_text("❌ לא נמצאו קבצים.")
            return

        status = await update.message.reply_text(f"🎨 יוצר {len(files)} תמונות...\n0/{len(files)} הושלמו")
        done = 0
        generator = CodeImageGenerator(style='monokai', theme='dark')
        for f in files:
            try:
                fname = f.get('file_name') or f.get('file_name'.encode(), 'unknown')
                data = db.get_latest_version(user_id, fname)
                if not data or not data.get('code'):
                    continue
                img_bytes = generator.generate_image(
                    code=str(data['code']),
                    language=str(data.get('programming_language') or 'text'),
                    filename=fname,
                )
                bio = io.BytesIO(img_bytes)
                bio.name = f"{fname}.png"
                await update.message.reply_photo(photo=InputFile(bio, filename=bio.name), parse_mode=ParseMode.HTML)
                done += 1
                if done % 5 == 0:
                    try:
                        await status.edit_text(f"🎨 יוצר {len(files)} תמונות...\n{done}/{len(files)} הושלמו")
                    except Exception:
                        pass
            except Exception as e:
                logger.error(f"Error processing {f.get('file_name')}: {e}")
                continue
        try:
            generator.cleanup()  # type: ignore[attr-defined]
        except Exception:
            pass
        await status.edit_text(f"✅ הושלם! נוצרו {done}/{len(files)} תמונות.")

# פקודות נוספות ייוצרו בהמשך...


async def check_db_connection() -> bool:
    """בדיקת חיבור אמיתית ל-MongoDB באמצעות פקודת ping.

    לוגיקה:
    - טוען URI מה-ENV (MONGODB_URL/REPORTER_MONGODB_URL/REPORTER_MONGODB_URI)
    - מנסה תחילה Motor (אסינכרוני) עם await
    - נפילה ל-PyMongo (סינכרוני) אם Motor לא זמין
    - מחזיר True רק אם ping הצליח בפועל
    """
    try:
        mongodb_uri = (
            os.getenv('REPORTER_MONGODB_URL')
            or os.getenv('REPORTER_MONGODB_URI')
            or os.getenv('MONGODB_URL')
            or ""
        )
        if not mongodb_uri:
            logger.debug("MongoDB URI missing (MONGODB_URL not configured)")
            return False

        # Motor (עדיף אסינכרוני)
        try:
            import motor.motor_asyncio as _motor  # type: ignore
            client = _motor.AsyncIOMotorClient(mongodb_uri, serverSelectionTimeoutMS=3000)
            try:
                await client.admin.command('ping')
                return True
            finally:
                try:
                    client.close()
                except Exception:
                    pass
        except Exception as motor_err:
            logger.debug(f"Motor ping failed; falling back to PyMongo: {motor_err}")

        # PyMongo (סינכרוני)
        try:
            from pymongo import MongoClient  # type: ignore
            client2 = MongoClient(mongodb_uri, serverSelectionTimeoutMS=3000)
            try:
                client2.admin.command('ping')
                return True
            finally:
                try:
                    client2.close()
                except Exception:
                    pass
        except Exception as pym_err:
            logger.debug(f"PyMongo ping failed: {pym_err}")
            return False
    except Exception as e:
        logger.debug(f"Unexpected error during DB check: {e}")
        return False
