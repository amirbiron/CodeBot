"""
פקודות מתקדמות לבוט שומר קבצי קוד
Advanced Bot Handlers for Code Keeper Bot
"""

import asyncio
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
from config import config
from database import CodeSnippet, db
from conversation_handlers import MAIN_KEYBOARD
# Reporter מוזרק בזמן ריצה כדי למנוע יצירה בזמן import
class _NoopReporter:
    def report_activity(self, user_id):
        return None

reporter = _NoopReporter()

def set_activity_reporter(new_reporter):
    global reporter
    reporter = new_reporter or _NoopReporter()
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
            db_ok = await check_db_connection()

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
                if aiohttp is not None and os.getenv("GITHUB_TOKEN"):
                    timeout = aiohttp.ClientTimeout(total=10)
                    connector = aiohttp.TCPConnector(limit=50)
                    async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
                        async with session.get("https://api.github.com/rate_limit", headers={"Authorization": f"token {os.getenv('GITHUB_TOKEN')}"}) as resp:
                            data = await resp.json()
                            remaining = int(data.get("resources", {}).get("core", {}).get("remaining", 0))
                            limit = int(data.get("resources", {}).get("core", {}).get("limit", 0))
                            used_pct = (100 - int(remaining * 100 / max(limit, 1))) if limit else 0
                            gh_status = f"{remaining}/{limit} ({used_pct}% used)"
            except Exception:
                gh_status = "error"

            def _emoji(ok: bool) -> str:
                return "🟢" if ok else "🔴"

            text = (
                f"📋 Status\n"
                f"DB: {_emoji(db_ok)}\n"
                f"Redis: {_emoji(redis_ok)}\n"
                f"GitHub: {gh_status}\n"
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
                    host = (parsed.hostname or '').replace('ingest.', '') if parsed.hostname else None
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
        """/observe – סיכום חי מתוך /metrics ו-/alerts (24h/5m)"""
        try:
            # הרשאות: אדמינים בלבד
            try:
                user_id = int(getattr(update.effective_user, 'id', 0) or 0)
            except Exception:
                user_id = 0
            if not self._is_admin(user_id):
                await update.message.reply_text("❌ פקודה זמינה למנהלים בלבד")
                return

            # Uptime
            try:
                from metrics import get_uptime_percentage  # type: ignore
                uptime = float(get_uptime_percentage())
            except Exception:
                uptime = 100.0

            # Error rate & Active users & alerts via internal helpers and endpoints
            try:
                # Prefer internal metrics helpers when available
                from alert_manager import get_current_error_rate_percent  # type: ignore
                error_rate = float(get_current_error_rate_percent(window_sec=5 * 60))
            except Exception:
                error_rate = 0.0

            # Active users gauge – best-effort via Prometheus isn't available directly here;
            # we maintain a rough number in memory in metrics via note_active_user, not per 24h.
            # For ChatOps, provide a conservative placeholder if not available.
            active_users = 0
            try:
                # Attempt to import the in-memory set if exposed (best-effort)
                from metrics import codebot_active_users_total  # type: ignore
                if codebot_active_users_total is not None:
                    # Prometheus Gauge does not expose value portably; leave 0 if unavailable
                    active_users = 0
            except Exception:
                active_users = 0

            # Alerts count (24h) using internal_alerts buffer (approx, not persisted)
            alerts_24h = 0
            critical_24h = 0
            try:
                from internal_alerts import get_recent_alerts  # type: ignore
                items = get_recent_alerts(limit=200) or []
                # Filter by timestamp (ISO) last 24h
                now = datetime.now(timezone.utc)
                day_ago = now.timestamp() - 24 * 3600
                for a in items:
                    try:
                        ts = a.get('ts')
                        t = datetime.fromisoformat(str(ts)).timestamp() if ts else 0.0
                    except Exception:
                        t = 0.0
                    if t >= day_ago:
                        alerts_24h += 1
                        if str(a.get('severity', '')).lower() == 'critical':
                            critical_24h += 1
            except Exception:
                alerts_24h = 0
                critical_24h = 0

            text = (
                "🔍 Observability Overview\n"
                f"Uptime: {uptime:.2f}%\n"
                f"Error Rate: {error_rate:.2f}%\n"
                f"Active Users: {active_users}\n"
                f"Alerts (24h): {alerts_24h} ({critical_24h} critical)"
            )
            await update.message.reply_text(text)
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
                from predictive_engine import evaluate_predictions  # type: ignore
            except Exception:
                await update.message.reply_text("ℹ️ מנוע חיזוי אינו זמין בסביבה זו")
                return
            horizon = 3 * 60 * 60  # 3h
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
        """/errors – 10 השגיאות האחרונות. מקור ראשי: Sentry; Fallback: זיכרון מקומי."""
        try:
            # הרשאות: אדמינים בלבד
            try:
                user_id = int(getattr(update.effective_user, 'id', 0) or 0)
            except Exception:
                user_id = 0
            if not self._is_admin(user_id):
                await update.message.reply_text("❌ פקודה זמינה למנהלים בלבד")
                return

            lines: list[str] = []
            used_fallback = False

            # 1) Sentry-first (best-effort)
            try:
                import integrations_sentry as _sentry  # type: ignore
                if getattr(_sentry, "is_configured", None) and _sentry.is_configured():
                    issues = await _sentry.get_recent_issues(limit=10)
                    if issues:
                        for i, it in enumerate(issues, 1):
                            sid = str(it.get("shortId") or it.get("id") or "-")
                            title = str(it.get("title") or "")
                            lines.append(f"{i}. [{sid}] {title}")
            except Exception:
                # ignore and try fallback
                pass

            # 2) Fallback – recent errors buffer from observability
            if not lines:
                try:
                    from observability import get_recent_errors  # type: ignore
                    recent = get_recent_errors(limit=10) or []
                    if recent:
                        for i, er in enumerate(recent, 1):
                            code = er.get("error_code") or "-"
                            msg = er.get("error") or er.get("event") or ""
                            lines.append(f"{i}. [{code}] {msg}")
                    else:
                        used_fallback = True
                except Exception:
                    used_fallback = True

            if used_fallback and not lines:
                lines.append("(אין נתוני שגיאות זמינים בסביבה זו)")
            await update.message.reply_text("\n".join(["🧰 שגיאות אחרונות:"] + lines))
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
                summary_lines.append(f"דוח מלא: {share_url}")

            # קישורי Grafana (2 ראשונים)
            try:
                links = list(result.get("grafana_links") or [])
                if links:
                    glines = ", ".join(f"[{l.get('name')}]({l.get('url')})" for l in links[:2])
                    summary_lines.append(f"Grafana: {glines}")
            except Exception:
                pass

            await update.message.reply_text("\n".join(summary_lines), parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            await update.message.reply_text(f"❌ שגיאה ב-/triage: {html.escape(str(e))}")

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
            if aiohttp is None or not os.getenv("GITHUB_TOKEN"):
                await update.message.reply_text("ℹ️ אין GITHUB_TOKEN או aiohttp – מידע לא זמין")
                return
            timeout = aiohttp.ClientTimeout(total=10)
            connector = aiohttp.TCPConnector(limit=50)
            async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
                async with session.get("https://api.github.com/rate_limit", headers={"Authorization": f"token {os.getenv('GITHUB_TOKEN')}"}) as resp:
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
        """בודק אם המשתמש הוא אדמין לפי ENV ADMIN_USER_IDS (או מודול permissions אם קיים)."""
        try:
            if callable(_perm_is_admin):
                return bool(_perm_is_admin(int(user_id)))
        except Exception:
            pass
        try:
            raw = os.getenv('ADMIN_USER_IDS', '')
            ids = [int(x.strip()) for x in raw.split(',') if x.strip().isdigit()]
            return int(user_id) in ids
        except Exception:
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
            
            # ועוד callback handlers...

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
