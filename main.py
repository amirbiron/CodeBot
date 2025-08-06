#!/usr/bin/env python3
"""
בוט שומר קבצי קוד - Code Keeper Bot
נקודת הכניסה הראשית לבוט
"""

import asyncio
import logging
import signal
import sys
from datetime import datetime

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (Application, CommandHandler, ContextTypes,
                          MessageHandler, filters)

from config import config
from database import CodeSnippet, db

# הגדרת לוגים
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)

class CodeKeeperBot:
    """המחלקה הראשית של הבוט"""
    
    def __init__(self):
        self.application = Application.builder().token(config.BOT_TOKEN).build()
        self.setup_handlers()
    
    def setup_handlers(self):
        """הגדרת כל ה-handlers של הבוט"""
        
        # פקודות עיקריות
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("help", self.help_command))
        self.application.add_handler(CommandHandler("save", self.save_command))
        self.application.add_handler(CommandHandler("list", self.list_command))
        self.application.add_handler(CommandHandler("search", self.search_command))
        self.application.add_handler(CommandHandler("stats", self.stats_command))
        
        # הודעות טקסט (לזיהוי קוד אוטומטי)
        self.application.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_text_message)
        )
        
        # טיפול בשגיאות
        self.application.add_error_handler(self.error_handler)
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """פקודת התחלה"""
        user = update.effective_user
        welcome_text = f"""
👋 שלום {user.first_name}!

🤖 אני בוט שומר קבצי קוד - הפתרון המושלם לשמירה וניהול קטעי הקוד שלך!

✨ מה אני יכול לעשות:
• 💾 שמירת קטעי קוד עם זיהוי שפה אוטומטי
• 🏷️ תיוג ותיאור קטעים
• 🔍 חיפוש מתקדם לפי שפה, תגיות או תוכן
• 📝 ניהול גרסאות לכל קטע קוד
• 📊 הדגשת תחביר צבעונית
• 🌐 שיתוף קטעים ב-Gist/Pastebin

📋 פקודות זמינות:
/save - שמירת קטע קוד
/list - צפייה בכל הקטעים שלך
/search - חיפוש קטעי קוד
/stats - סטטיסטיקות האחסון שלך
/help - עזרה מפורטת

🚀 התחל בשליחת קטע קוד או השתמש ב/save!
        """
        
        await update.message.reply_text(
            welcome_text,
            parse_mode=ParseMode.MARKDOWN_V2
        )
        
        logger.info(f"משתמש חדש התחיל: {user.id} ({user.username})")
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """פקודת עזרה מפורטת"""
        help_text = """
📖 **מדריך שימוש מפורט**

**שמירת קוד:**
• `/save שם_קובץ` - לאחר מכן שלח את הקוד
• שלח קוד ישירות - אזהה אוטומטי ואציע שמירה
• הוסף תגיות: `/save script.py #python #api #automation`

**חיפוש וצפייה:**
• `/list` - כל הקטעים שלך
• `/search מילת_חיפוש` - חיפוש חופשי
• `/search python` - לפי שפת תכנות
• `/search #api` - לפי תגית

**פקודות נוספות:**
• `/stats` - סטטיסטיקות האחסון שלך
• `/version שם_קובץ` - כל הגרסאות
• `/delete שם_קובץ` - מחיקת קובץ
• `/share שם_קובץ` - שיתוף ב-Gist

**טיפים:**
🔸 השתמש בשמות קבצים ברורים
🔸 הוסף תיאור לכל קטע קוד
🔸 השתמש בתגיות למיון טוב יותר
🔸 הבוט תומך ב-20+ שפות תכנות

💡 אם אתה לא בטוח בשפה, שלח את הקוד ואני אזהה אוטומטי!
        """
        
        await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)
    
    async def save_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """פקודת שמירת קוד"""
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
        
        await update.message.reply_text(
            f"📝 מוכן לשמור את `{file_name}`\n"
            f"🏷️ תגיות: {', '.join(tags) if tags else 'ללא'}\n\n"
            "אנא שלח את קטע הקוד:",
            parse_mode=ParseMode.MARKDOWN
        )
    
    async def list_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """הצגת רשימת הקטעים של המשתמש"""
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
            response += f"🔤 שפה: {file_data['language']}\n"
            
            if description:
                response += f"📝 תיאור: {description}\n"
            
            if tags_str:
                response += f"🏷️ תגיות: {tags_str}\n"
            
            response += f"📅 עודכן: {file_data['updated_at'].strftime('%d/%m/%Y %H:%M')}\n"
            response += f"🔢 גרסה: {file_data['version']}\n\n"
        
        if len(files) == 20:
            response += "\n📄 מוצגים 20 הקטעים האחרונים. השתמש בחיפוש לעוד..."
        
        await update.message.reply_text(response, parse_mode=ParseMode.MARKDOWN)
    
    async def search_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """חיפוש קטעי קוד"""
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
        tags = []
        if query.startswith('#'):
            tags = [query[1:]]
            query = ""
        elif query in config.SUPPORTED_LANGUAGES:
            # חיפוש לפי שפה
            results = db.search_code(user_id, "", language=query)
        else:
            # חיפוש חופשי
            results = db.search_code(user_id, query, tags=tags)
        
        if not results:
            await update.message.reply_text(
                f"🔍 לא נמצאו תוצאות עבור: `{' '.join(context.args)}`",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        # הצגת תוצאות
        response = f"🔍 **תוצאות חיפוש עבור:** `{' '.join(context.args)}`\n\n"
        
        for i, file_data in enumerate(results[:10], 1):
            response += f"**{i}. {file_data['file_name']}**\n"
            response += f"🔤 {file_data['language']} | "
            response += f"📅 {file_data['updated_at'].strftime('%d/%m')}\n"
            
            if file_data.get('description'):
                response += f"📝 {file_data['description']}\n"
            
            response += "\n"
        
        if len(results) > 10:
            response += f"\n📄 מוצגות 10 מתוך {len(results)} תוצאות"
        
        await update.message.reply_text(response, parse_mode=ParseMode.MARKDOWN)
    
    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """הצגת סטטיסטיקות המשתמש"""
        user_id = update.effective_user.id
        
        stats = db.get_user_stats(user_id)
        
        if not stats or stats.get('total_files', 0) == 0:
            await update.message.reply_text(
                "📊 עדיין אין לך קטעי קוד שמורים.\n"
                "התחל עם /save!"
            )
            return
        
        languages_str = ", ".join(stats.get('languages', []))
        last_activity = stats.get('latest_activity')
        last_activity_str = last_activity.strftime('%d/%m/%Y %H:%M') if last_activity else "לא ידוע"
        
        response = f"""
📊 **הסטטיסטיקות שלך:**

📁 סה"כ קבצים: **{stats['total_files']}**
🔢 סה"כ גרסאות: **{stats['total_versions']}**
💾 מגבלת קבצים: {config.MAX_FILES_PER_USER}

🔤 **שפות בשימוש:**
{languages_str}

📅 **פעילות אחרונה:**
{last_activity_str}

💡 **טיפ:** השתמש בתגיות לארגון טוב יותר!
        """
        
        await update.message.reply_text(response, parse_mode=ParseMode.MARKDOWN)
    
    async def handle_text_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """טיפול בהודעות טקסט (קוד פוטנציאלי)"""
        user_id = update.effective_user.id
        text = update.message.text
        
        # בדיקה אם המשתמש בתהליך שמירה
        if 'saving_file' in context.user_data:
            await self._save_code_snippet(update, context, text)
            return
        
        # זיהוי אם זה נראה כמו קוד
        if self._looks_like_code(text):
            await update.message.reply_text(
                "🤔 נראה שזה קטע קוד!\n"
                "רוצה לשמור אותו? השתמש ב/save או שלח שוב עם שם קובץ.",
                reply_to_message_id=update.message.message_id
            )
    
    async def _save_code_snippet(self, update: Update, context: ContextTypes.DEFAULT_TYPE, code: str):
        """שמירה בפועל של קטע קוד"""
        saving_data = context.user_data.pop('saving_file')
        
        if len(code) > config.MAX_CODE_SIZE:
            await update.message.reply_text(
                f"❌ הקוד גדול מדי! מקסימום {config.MAX_CODE_SIZE} תווים."
            )
            return
        
        # זיהוי שפת התכנות (זה ייעשה בcode_processor.py בעתיד)
        language = self._detect_language(saving_data['file_name'], code)
        
        # יצירת אובייקט קטע קוד
        snippet = CodeSnippet(
            user_id=saving_data['user_id'],
            file_name=saving_data['file_name'],
            code=code,
            language=language,
            tags=saving_data['tags']
        )
        
        # שמירה במסד הנתונים
        if db.save_code_snippet(snippet):
            await update.message.reply_text(
                f"✅ נשמר בהצלחה!\n\n"
                f"📁 **{saving_data['file_name']}**\n"
                f"🔤 שפה: {language}\n"
                f"🏷️ תגיות: {', '.join(saving_data['tags']) if saving_data['tags'] else 'ללא'}\n"
                f"📊 גודל: {len(code)} תווים",
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await update.message.reply_text(
                "❌ שגיאה בשמירה. נסה שוב מאוחר יותר."
            )
    
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
        
        # סגירת חיבור למסד נתונים
        db.close()
        
        logger.info("הבוט נעצר.")

def signal_handler(signum, frame):
    """טיפול בסיגנלי עצירה"""
    logger.info(f"התקבל סיגנל {signum}, עוצר את הבוט...")
    sys.exit(0)

async def main():
    """הפונקציה הראשית"""
    try:
        # הגדרת טיפול בסיגנלים
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        # יצירת והפעלת הבוט
        bot = CodeKeeperBot()
        await bot.start()
        
        # המתנה אינסופית
        while True:
            await asyncio.sleep(1)
            
    except KeyboardInterrupt:
        logger.info("עצירה על ידי המשתמש")
    except Exception as e:
        logger.error(f"שגיאה קריטית: {e}")
    finally:
        if 'bot' in locals():
            await bot.stop()

if __name__ == "__main__":
    asyncio.run(main())
