"""
פקודות מתקדמות לבוט שומר קבצי קוד
Advanced Bot Handlers for Code Keeper Bot
"""

import asyncio
import io
import logging
import re
import html
import secrets
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
from activity_reporter import create_reporter

logger = logging.getLogger(__name__)

reporter = create_reporter(
    mongodb_uri="mongodb+srv://mumin:M43M2TFgLfGvhBwY@muminai.tm6x81b.mongodb.net/?retryWrites=true&w=majority&appName=muminAI",
    service_id="srv-d29d72adbo4c73bcuep0",
    service_name="CodeBot"
)

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
        
        # Callback handlers לכפתורים
        # Handler כללי (תאימות לאחור)
        # הוסף Guard גלובלי קודם בקדימות גבוהה כדי למנוע לחיצות כפולות
        async def _guard(update: Update, context: ContextTypes.DEFAULT_TYPE):
            try:
                if getattr(update, 'callback_query', None):
                    try:
                        from utils import CallbackQueryGuard
                        if CallbackQueryGuard.should_block(update, context):
                            try:
                                await update.callback_query.answer("עובד…", show_alert=False)
                            except Exception:
                                pass
                            raise ApplicationHandlerStop()
                    except Exception:
                        pass
            except ApplicationHandlerStop:
                raise
            except Exception:
                pass

        self.application.add_handler(CallbackQueryHandler(_guard), group=-10)
        self.application.add_handler(CallbackQueryHandler(self.handle_callback_query))
        # Handler ממוקד עם קדימות גבוהה לכפתורי /share
        try:
            share_pattern = r'^(share_gist_|share_pastebin_|share_internal_|share_gist_multi:|share_internal_multi:|cancel_share)'
            self.application.add_handler(CallbackQueryHandler(self.handle_callback_query, pattern=share_pattern), group=-5)
        except Exception:
            pass
    
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
        
        # קבל את הקוד המקורי (הפונקציה highlight_code תחזיר אותו כפי שהוא)
        original_code = code_processor.highlight_code(
            file_data['code'],
            file_data['programming_language'],
            'html'
        )

        # בצע הימלטות לתוכן הקוד כדי למנוע שגיאות
        escaped_code = html.escape(original_code)

        # עטוף את הקוד הנקי בתגיות <pre><code> שטלגרם תומך בהן
        response_text = f"""<b>File:</b> <code>{html.escape(file_data['file_name'])}</code>
<b>Language:</b> {file_data['programming_language']}

<pre><code>{escaped_code}</code></pre>
"""
        
        # --- מבנה הכפתורים החדש והנקי ---
        file_id = str(file_data.get('_id', file_name))
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
            ]
        ]
        reply_markup = InlineKeyboardMarkup(buttons)
        # ---------------------------------
        
        await update.message.reply_text(response_text, parse_mode='HTML', reply_markup=reply_markup)
    
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
        all_files = db.get_user_files(user_id, limit=1000)
        all_names = [f['file_name'] for f in all_files]

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
        
        files = db.get_user_files(user_id, limit=1000)
        
        if not files:
            await update.message.reply_text("🏷️ עדיין אין לך קבצים עם תגיות.")
            return
        
        # איסוף כל התגיות
        all_tags = {}
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
        
        response = f"📅 **קבצים מ-{days_back} הימים האחרונים:**\n\n"
        
        for file_data in recent_files[:15]:  # מקסימום 15 קבצים
            dt_now = datetime.now(timezone.utc) if file_data['updated_at'].tzinfo else datetime.now()
            days_ago = (dt_now - file_data['updated_at']).days
            time_str = f"היום" if days_ago == 0 else f"לפני {days_ago} ימים"
            
            response += f"📄 **{file_data['file_name']}**\n"
            response += f"   🔤 {file_data['programming_language']} | 📅 {time_str}\n\n"
        
        if len(recent_files) > 15:
            response += f"📄 ועוד {len(recent_files) - 15} קבצים..."
        
        await update.message.reply_text(response, parse_mode=ParseMode.MARKDOWN)
    
    async def handle_callback_query(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """טיפול בלחיצות על כפתורים"""
        reporter.report_activity(update.effective_user.id)
        query = update.callback_query
        await query.answer()
        
        data = query.data
        user_id = query.from_user.id
        
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
            file_data['programming_language'], 
            'html'
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
