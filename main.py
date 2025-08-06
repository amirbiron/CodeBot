#!/usr/bin/env python3
"""
בוט שומר קבצי קוד - Code Keeper Bot
נקודת הכניסה הראשית לבוט
"""

import asyncio
import logging
import signal
import sys
import time
import pymongo
from datetime import datetime, timezone, timedelta
import atexit
import os
import pymongo.errors
from pymongo.errors import DuplicateKeyError

from telegram import Update, ReplyKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (Application, CommandHandler, ContextTypes,
                          MessageHandler, filters, Defaults)

from config import config
from database import CodeSnippet, DatabaseManager, db
from code_processor import code_processor
from bot_handlers import AdvancedBotHandlers  # still used by legacy code
# New import for advanced handler setup helper
from advanced_bot_handlers import setup_advanced_handlers
from conversation_handlers import MAIN_KEYBOARD, get_save_conversation_handler
from activity_reporter import create_reporter

# (Lock mechanism constants removed)

# הגדרת לוגים
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)

reporter = create_reporter(
    mongodb_uri="mongodb+srv://mumin:M43M2TFgLfGvhBwY@muminai.tm6x81b.mongodb.net/?retryWrites=true&w=majority&appName=muminAI",
    service_id="srv-d29d72adbo4c73bcuep0",
    service_name="CodeBot"
)

# =============================================================================
# MONGODB LOCK MANAGEMENT (FINAL, NO-GUESSING VERSION)
# =============================================================================

LOCK_ID = "code_keeper_bot_lock"
LOCK_COLLECTION = "locks"
LOCK_TIMEOUT_MINUTES = 5

def get_lock_collection():
    """
    Gets the lock collection by asking the client for its default database.
    This relies on the DatabaseManager's established connection.
    """
    try:
        # בקש מה-client את מסד הנתונים הדיפולטיבי שהוגדר בחיבור
        default_db = db.client.get_default_database()
        
        if default_db is None:
            logger.critical("Could not determine default database from MongoDB connection!")
            sys.exit(1)
            
        return default_db[LOCK_COLLECTION]
        
    except AttributeError:
        logger.critical("'db.client' object not found or does not have 'get_default_database'. The structure of DatabaseManager might be different.")
        sys.exit(1)
    except Exception as e:
        logger.critical(f"Failed to get default database or collection: {e}", exc_info=True)
        sys.exit(1)

def cleanup_mongo_lock():
    """Runs on script exit to remove the lock document."""
    try:
        lock_collection = get_lock_collection()
        pid = os.getpid()
        result = lock_collection.delete_one({"_id": LOCK_ID, "pid": pid})
        if result.deleted_count > 0:
            logger.info(f"Lock '{LOCK_ID}' released successfully by PID: {pid}.")
    except Exception as e:
        logger.error(f"Error while releasing MongoDB lock: {e}", exc_info=True)

def manage_mongo_lock():
    """ניהול נעילה מתקדם עם מנגנון זיהוי והמתנה"""
    max_retries = 3
    retry_delay = 5  # שניות
    
    for attempt in range(max_retries):
        try:
            from datetime import timezone
            import os
            import time
            
            instance_id = os.getenv("RENDER_INSTANCE_ID", f"local_{os.getpid()}_{int(time.time())}")
            now = datetime.now(timezone.utc)
            
            # בדיקה ראשונה - האם יש נעילה קיימת
            existing_lock = db.db.locks.find_one({"name": "bot_main_lock"})
            
            if existing_lock:
                existing_time = existing_lock.get("timestamp", now)
                existing_instance = existing_lock.get("instance_id", "unknown")
                
                # תיקון timezone אם צריך
                if existing_time.tzinfo is None:
                    existing_time = existing_time.replace(tzinfo=timezone.utc)
                
                time_diff = (now - existing_time).total_seconds()
                
                if time_diff > 180:  # 3 דקות במקום 5
                    logger.warning(f"🧹 נעילה ישנה נמצאה ({time_diff:.0f}s), מוחק...")
                    result = db.db.locks.delete_one({"name": "bot_main_lock"})
                    if result.deleted_count > 0:
                        logger.info("✅ נעילה ישנה נמחקה")
                    else:
                        logger.warning("⚠️ לא הצלחתי למחוק נעילה ישנה")
                else:
                    if attempt < max_retries - 1:
                        logger.warning(f"⏳ תהליך אחר פועל (Instance: {existing_instance}, {time_diff:.0f}s). מנסה שוב בעוד {retry_delay}s...")
                        time.sleep(retry_delay)
                        continue
                    else:
                        logger.error(f"❌ תהליך אחר עדיין פועל אחרי {max_retries} ניסיונות")
                        return False
            
            # ניסיון ליצור נעילה
            try:
                result = db.db.locks.insert_one({
                    "name": "bot_main_lock",
                    "instance_id": instance_id,
                    "timestamp": now,
                    "status": "active",
                    "attempt": attempt + 1
                })
                
                logger.info(f"✅ נעילה נתפסה! Instance: {instance_id} (ניסיון {attempt + 1})")
                
                # פונקציית ניקוי
                def cleanup_lock():
                    try:
                        result = db.db.locks.delete_one({
                            "name": "bot_main_lock", 
                            "instance_id": instance_id
                        })
                        if result.deleted_count > 0:
                            logger.info(f"🧹 נעילה שוחררה. Instance: {instance_id}")
                        else:
                            logger.warning(f"⚠️ לא מצאתי נעילה לשחרור. Instance: {instance_id}")
                    except Exception as e:
                        logger.error(f"שגיאה בשחרור נעילה: {e}")
                
                atexit.register(cleanup_lock)
                return True
                
            except Exception as insert_error:
                if "duplicate key" in str(insert_error).lower() or "E11000" in str(insert_error):
                    if attempt < max_retries - 1:
                        logger.warning(f"🔄 נעילה נתפסה בזמן הניסיון. מנסה שוב בעוד {retry_delay}s...")
                        time.sleep(retry_delay)
                        continue
                    else:
                        logger.error(f"❌ לא הצלחתי לתפוס נעילה אחרי {max_retries} ניסיונות")
                        return False
                else:
                    logger.error(f"שגיאה לא צפויה ביצירת נעילה: {insert_error}")
                    return False
                    
        except Exception as e:
            logger.error(f"שגיאה קריטית בניסיון {attempt + 1}: {e}")
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
                continue
            else:
                return False
    
    logger.error(f"❌ נכשל בכל {max_retries} הניסיונות")
    return False

# =============================================================================

class CodeKeeperBot:
    """המחלקה הראשית של הבוט"""
    
    def __init__(self):
        self.application = Application.builder().token(config.BOT_TOKEN).defaults(Defaults(parse_mode=ParseMode.HTML)).build()
        self.setup_handlers()
        self.advanced_handlers = AdvancedBotHandlers(self.application)
    
    def setup_handlers(self):
        """הגדרת כל ה-handlers של הבוט בסדר הנכון"""

        # --- שלב 1: רישום ה-ConversationHandler בעדיפות ראשונה ---
        # זה יטפל בפקודת /start ובלחיצות על הכפתורים הראשיים.
        conv_handler = get_save_conversation_handler(db)
        self.application.add_handler(conv_handler, group=-1)  # group=-1 נותן עדיפות גבוהה

        # --- שלב 1.5: הוסף CallbackQueryHandler גלובלי לטיפול בכפתורים ---
        from conversation_handlers import handle_callback_query
        from telegram.ext import CallbackQueryHandler
        self.application.add_handler(CallbackQueryHandler(handle_callback_query))

        # --- שלב 2: רישום שאר הפקודות ---
        # הפקודה /start המקורית הופכת להיות חלק מה-conv_handler, אז היא לא כאן.
        self.application.add_handler(CommandHandler("help", self.help_command))
        self.application.add_handler(CommandHandler("save", self.save_command))
        # self.application.add_handler(CommandHandler("list", self.list_command))  # מחוק - מטופל על ידי הכפתור "📚 הצג את כל הקבצים שלי"
        self.application.add_handler(CommandHandler("search", self.search_command))
        self.application.add_handler(CommandHandler("stats", self.stats_command))
        
        # --- שלב 3: רישום המטפל הכללי בסוף ---
        # הוא יפעל רק אם אף אחד מהמטפלים הספציפיים יותר לא תפס את ההודעה.
        self.application.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_text_message)
        )
        
        # --- שלב 4: טיפול בשגיאות ---
        self.application.add_error_handler(self.error_handler)
    
    # start_command הוסר - ConversationHandler מטפל בפקודת /start
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """פקודת עזרה מפורטת"""
        reporter.report_activity(update.effective_user.id)
        response = """
📚 <b>רשימת הפקודות המלאה:</b>

<b>שמירה וניהול:</b>
• <code>/save &lt;filename&gt;</code> - התחלת שמירה של קובץ חדש.
• <code>/list</code> - הצגת כל הקבצים שלך.
• <code>/show &lt;filename&gt;</code> - הצגת קובץ עם הדגשת תחביר וכפתורי פעולה.
• <code>/edit &lt;filename&gt;</code> - עריכת קוד של קובץ קיים.
• <code>/delete &lt;filename&gt;</code> - מחיקת קובץ וכל הגרסאות שלו.

<b>גרסאות וניתוח:</b>
• <code>/versions &lt;filename&gt;</code> - הצגת כל הגרסאות של קובץ.
• <code>/restore &lt;filename&gt; &lt;version&gt;</code> - שחזור גרסה ישנה.
• <code>/analyze &lt;filename&gt;</code> - ניתוח סטטיסטי של קוד.
• <code>/validate &lt;filename&gt;</code> - בדיקת תחביר בסיסית.

<b>שיתוף וארגון:</b>
• <code>/share &lt;filename&gt;</code> - קבלת אפשרויות שיתוף.
• <code>/download &lt;filename&gt;</code> - הורדת הקובץ למחשב שלך.
• <code>/tags &lt;filename&gt; &lt;tag1&gt;,&lt;tag2&gt;</code> - הוספת תגיות לקובץ.
• <code>/search &lt;query&gt;</code> - חיפוש טקסטואלי בקוד שלך.
    
<b>מידע כללי:</b>
• <code>/recent</code> - הצגת קבצים שעודכנו לאחרונה.
• <code>/help</code> - הצגת הודעה זו.
"""
        await update.message.reply_text(response, parse_mode=ParseMode.HTML)
    
    async def save_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """פקודת שמירת קוד"""
        reporter.report_activity(update.effective_user.id)
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
            f"📝 מוכן לשמור את <code>{file_name}</code>\n"
            f"🏷️ תגיות: {', '.join(tags) if tags else 'ללא'}\n\n"
            "אנא שלח את קטע הקוד:",
            parse_mode=ParseMode.HTML
        )
    
    async def list_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """הצגת רשימת הקטעים של המשתמש"""
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
        reporter.report_activity(update.effective_user.id)
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
            results = db.search_code(user_id, "", programming_language=query)
        else:
            # חיפוש חופשי
            results = db.search_code(user_id, query, tags=tags)
        
        if not results:
            await update.message.reply_text(
                f"🔍 לא נמצאו תוצאות עבור: <code>{' '.join(context.args)}</code>",
                parse_mode=ParseMode.HTML
            )
            return
        
        # הצגת תוצאות
        response = f"🔍 **תוצאות חיפוש עבור:** <code>{' '.join(context.args)}</code>\n\n"
        
        for i, file_data in enumerate(results[:10], 1):
            response += f"**{i}. {file_data['file_name']}**\n"
            response += f"🔤 {file_data['programming_language']} | "
            response += f"📅 {file_data['updated_at'].strftime('%d/%m')}\n"
            
            if file_data.get('description'):
                response += f"📝 {file_data['description']}\n"
            
            response += "\n"
        
        if len(results) > 10:
            response += f"\n📄 מוצגות 10 מתוך {len(results)} תוצאות"
        
        await update.message.reply_text(response, parse_mode=ParseMode.HTML)
    
    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """הצגת סטטיסטיקות המשתמש"""
        reporter.report_activity(update.effective_user.id)
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
        
        await update.message.reply_text(response, parse_mode=ParseMode.HTML)
    
    async def handle_text_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """טיפול בהודעות טקסט (קוד פוטנציאלי)"""
        reporter.report_activity(update.effective_user.id)
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
        reporter.report_activity(update.effective_user.id)
        saving_data = context.user_data.pop('saving_file')
        
        if len(code) > config.MAX_CODE_SIZE:
            await update.message.reply_text(
                f"❌ הקוד גדול מדי! מקסימום {config.MAX_CODE_SIZE} תווים."
            )
            return
        
        # זיהוי שפת התכנות באמצעות CodeProcessor
        detected_language = code_processor.detect_language(code, saving_data['file_name'])
        logger.info(f"זוהתה שפה: {detected_language} עבור הקובץ {saving_data['file_name']}")
        
        # יצירת אובייקט קטע קוד
        snippet = CodeSnippet(
            user_id=saving_data['user_id'],
            file_name=saving_data['file_name'],
            code=code,
            programming_language=detected_language,
            tags=saving_data['tags']
        )
        
        # שמירה במסד הנתונים
        if db.save_code_snippet(snippet):
            await update.message.reply_text(
                f"✅ נשמר בהצלחה!\n\n"
                f"📁 **{saving_data['file_name']}**\n"
                f"🔤 שפה: {detected_language}\n"
                f"🏷️ תגיות: {', '.join(saving_data['tags']) if saving_data['tags'] else 'ללא'}\n"
                f"📊 גודל: {len(code)} תווים",
                parse_mode=ParseMode.HTML
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

# ---------------------------------------------------------------------------
# Helper to register the basic command handlers with the Application instance.
# ---------------------------------------------------------------------------


def setup_handlers(application: Application, db_manager):  # noqa: D401
    """Register basic command handlers required for the bot to operate."""

    async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):  # noqa: D401
        reporter.report_activity(update.effective_user.id)
        reply_markup = ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        await update.message.reply_text("👋 שלום! הבוט מוכן לשימוש.", reply_markup=reply_markup)

    async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):  # noqa: D401
        reporter.report_activity(update.effective_user.id)
        await update.message.reply_text("ℹ️ השתמש ב/start כדי להתחיל.")

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
        
        bot = CodeKeeperBot()
        
        logger.info("Bot is starting to poll...")
        bot.application.run_polling(drop_pending_updates=True)
        
    except Exception as e:
        logger.error(f"שגיאה: {e}")
        raise
    finally:
        logger.info("Bot polling stopped. Closing database connection.")
        if 'db' in globals():
            db.close_connection()


# A minimal post_init stub to comply with the PTB builder chain
async def setup_bot_data(application: Application) -> None:  # noqa: D401
    """A post_init function to setup application-wide data."""
    # ניתן להוסיף לוגיקה נוספת כאן בעתיד
    pass

if __name__ == "__main__":
    main()
