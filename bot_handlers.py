"""
פקודות מתקדמות לבוט שומר קבצי קוד
Advanced Bot Handlers for Code Keeper Bot
"""

import asyncio
import io
import logging
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from telegram import (InlineKeyboardButton, InlineKeyboardMarkup, InputFile,
                      Update)
from telegram.constants import ParseMode
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes

from code_processor import code_processor
from config import config
from database import CodeSnippet, db

logger = logging.getLogger(__name__)

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
        self.application.add_handler(CommandHandler("rename", self.rename_command))
        self.application.add_handler(CommandHandler("copy", self.copy_command))
        
        # פקודות גרסאות
        self.application.add_handler(CommandHandler("versions", self.versions_command))
        self.application.add_handler(CommandHandler("restore", self.restore_command))
        self.application.add_handler(CommandHandler("diff", self.diff_command))
        
        # פקודות שיתוף
        self.application.add_handler(CommandHandler("share", self.share_command))
        self.application.add_handler(CommandHandler("export", self.export_command))
        self.application.add_handler(CommandHandler("download", self.download_command))
        
        # פקודות ניתוח
        self.application.add_handler(CommandHandler("analyze", self.analyze_command))
        self.application.add_handler(CommandHandler("validate", self.validate_command))
        self.application.add_handler(CommandHandler("minify", self.minify_command))
        
        # פקודות ארגון
        self.application.add_handler(CommandHandler("tags", self.tags_command))
        self.application.add_handler(CommandHandler("languages", self.languages_command))
        self.application.add_handler(CommandHandler("recent", self.recent_command))
        
        # Callback handlers לכפתורים
        self.application.add_handler(CallbackQueryHandler(self.handle_callback_query))
    
    async def show_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """הצגת קטע קוד עם הדגשת תחביר"""
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
        
        # יצירת כפתורי פעולה
        keyboard = [
            [
                InlineKeyboardButton("🎨 הדגשה צבעונית", callback_data=f"highlight_{file_name}"),
                InlineKeyboardButton("📊 ניתוח", callback_data=f"analyze_{file_name}")
            ],
            [
                InlineKeyboardButton("✏️ עריכה", callback_data=f"edit_{file_name}"),
                InlineKeyboardButton("🌐 שיתוף", callback_data=f"share_{file_name}")
            ],
            [
                InlineKeyboardButton("📋 העתקה", callback_data=f"copy_{file_name}"),
                InlineKeyboardButton("📥 הורדה", callback_data=f"download_{file_name}")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # הכנת המידע
        code = file_data['code']
        tags_str = ", ".join(file_data.get('tags', [])) if file_data.get('tags') else "ללא"
        
        response = f"""
📄 **{file_name}**

🔤 **שפה:** {file_data['programming_language']}
🏷️ **תגיות:** {tags_str}
📅 **עודכן:** {file_data['updated_at'].strftime('%d/%m/%Y %H:%M')}
🔢 **גרסה:** {file_data['version']}
📏 **גודל:** {len(code)} תווים

**קוד:**
```{file_data['programming_language']}
{code[:1000]}{'...' if len(code) > 1000 else ''}
```
        """
        
        if file_data.get('description'):
            response = response.replace("**קוד:**", f"📝 **תיאור:** {file_data['description']}\n\n**קוד:**")
        
        await update.message.reply_text(
            response,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup
        )
    
    async def edit_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """עריכת קטע קוד קיים"""
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
        validation = code_processor.validate_syntax(file_data['code'], file_data['programming_language'])
        
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
        """שיתוף קטע קוד ב-Gist או Pastebin"""
        user_id = update.effective_user.id
        
        if not context.args:
            await update.message.reply_text(
                "🌐 אנא ציין שם קובץ לשיתוף:\n"
                "דוגמה: `/share script.py`",
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
        
        # כפתורי אפשרויות שיתוף
        keyboard = [
            [
                InlineKeyboardButton("🐙 GitHub Gist", callback_data=f"share_gist_{file_name}"),
                InlineKeyboardButton("📋 Pastebin", callback_data=f"share_pastebin_{file_name}")
            ],
            [
                InlineKeyboardButton("📱 קישור פנימי", callback_data=f"share_internal_{file_name}"),
                InlineKeyboardButton("❌ ביטול", callback_data="cancel_share")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"🌐 **שיתוף קובץ:** `{file_name}`\n\n"
            f"🔤 שפה: {file_data['programming_language']}\n"
            f"📏 גודל: {len(file_data['code'])} תווים\n\n"
            f"בחר אופן שיתוף:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup
        )
    
    async def download_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """הורדת קובץ"""
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
        user_id = update.effective_user.id
        
        # כמה ימים אחורה לחפש
        days_back = 7
        if context.args and context.args[0].isdigit():
            days_back = int(context.args[0])
        
        # חיפוש קבצים אחרונים
        since_date = datetime.now() - timedelta(days=days_back)
        
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
            days_ago = (datetime.now() - file_data['updated_at']).days
            time_str = f"היום" if days_ago == 0 else f"לפני {days_ago} ימים"
            
            response += f"📄 **{file_data['file_name']}**\n"
            response += f"   🔤 {file_data['programming_language']} | 📅 {time_str}\n\n"
        
        if len(recent_files) > 15:
            response += f"📄 ועוד {len(recent_files) - 15} קבצים..."
        
        await update.message.reply_text(response, parse_mode=ParseMode.MARKDOWN)
    
    async def handle_callback_query(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """טיפול בלחיצות על כפתורים"""
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
            
            elif data.startswith("highlight_"):
                file_name = data.replace("highlight_", "")
                await self._send_highlighted_code(query, user_id, file_name)
            
            elif data.startswith("share_gist_"):
                file_name = data.replace("share_gist_", "")
                await self._share_to_gist(query, user_id, file_name)
            
            elif data.startswith("download_"):
                file_name = data.replace("download_", "")
                await self._download_file(query, user_id, file_name)
            
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
            # כאן יהיה הקוד לשיתוף ב-Gist (יתווסף בintegrations.py)
            gist_url = "https://gist.github.com/example"  # placeholder
            
            await query.edit_message_text(
                f"🐙 **שותף ב-GitHub Gist!**\n\n"
                f"📄 קובץ: `{file_name}`\n"
                f"🔗 קישור: {gist_url}",
                parse_mode=ParseMode.MARKDOWN
            )
            
        except Exception as e:
            logger.error(f"שגיאה בשיתוף Gist: {e}")
            await query.edit_message_text("❌ שגיאה בשיתוף. נסה שוב מאוחר יותר.")

# פקודות נוספות ייוצרו בהמשך...
