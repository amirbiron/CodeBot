#!/usr/bin/env python3
"""
בוט שומר קבצי קוד - Code Keeper Bot
נקודת הכניסה הראשית לבוט
"""

# הגדרות מתקדמות
import os
import logging
import asyncio
from datetime import datetime
from io import BytesIO

import signal
import sys
import time
import pymongo
from datetime import datetime, timezone, timedelta
import atexit
import pymongo.errors
from pymongo.errors import DuplicateKeyError

from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand, BotCommandScopeChat
from telegram.constants import ParseMode
from telegram.ext import (Application, CommandHandler, ContextTypes,
                          MessageHandler, filters, Defaults, ConversationHandler, CallbackQueryHandler,
                          PicklePersistence, InlineQueryHandler)

from config import config
from database import CodeSnippet, DatabaseManager, db
from code_processor import code_processor
from bot_handlers import AdvancedBotHandlers  # still used by legacy code
# New import for advanced handler setup helper
from advanced_bot_handlers import setup_advanced_handlers
from conversation_handlers import MAIN_KEYBOARD, get_save_conversation_handler
from activity_reporter import create_reporter
from github_menu_handler import GitHubMenuHandler
from large_files_handler import large_files_handler
from user_stats import user_stats
from cache_commands import setup_cache_handlers
from html import escape as html_escape

# (Lock mechanism constants removed)

# הגדרת לוגר מתקדם
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)

# הודעת התחלה מרשימה
logger.info("🚀 מפעיל בוט קוד מתקדם - גרסה פרו!")

# הפחתת רעש בלוגים
logging.getLogger("httpx").setLevel(logging.ERROR)  # רק שגיאות קריטיות
logging.getLogger("telegram.ext.Updater").setLevel(logging.ERROR)
logging.getLogger("telegram.ext.Application").setLevel(logging.WARNING)

# יצירת אובייקט reporter גלובלי
reporter = create_reporter(
    mongodb_uri=os.getenv('REPORTER_MONGODB_URI', config.MONGODB_URL),
    service_id=os.getenv('REPORTER_SERVICE_ID', 'srv-d29d72adbo4c73bcuep0'),
    service_name="CodeBot"
)

async def log_user_activity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """רישום פעילות משתמש"""
    if update.effective_user:
        user_stats.log_user(
            update.effective_user.id,
            update.effective_user.username
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
    """מושבת זמנית"""
    logger.info("🚫 מנגנון נעילה מושבת")
    return True

# =============================================================================

class CodeKeeperBot:
    """המחלקה הראשית של הבוט"""
    
    def __init__(self):
        # יצירת תיקייה זמנית עם הרשאות כתיבה
        DATA_DIR = "/tmp"
        if not os.path.exists(DATA_DIR):
            os.makedirs(DATA_DIR, exist_ok=True)
            
        # יצירת persistence לשמירת נתונים בין הפעלות
        persistence = PicklePersistence(filepath=f"{DATA_DIR}/bot_data.pickle")
        
        self.application = (
            Application.builder()
            .token(config.BOT_TOKEN)
            .defaults(Defaults(parse_mode=ParseMode.HTML))
            .persistence(persistence)
            .post_init(setup_bot_data)
            .build()
        )
        self.setup_handlers()
        self.advanced_handlers = AdvancedBotHandlers(self.application)
    
    def setup_handlers(self):
        """הגדרת כל ה-handlers של הבוט בסדר הנכון"""

        # ספור את ה-handlers
        handler_count = len(self.application.handlers)
        logger.info(f"🔍 כמות handlers לפני: {handler_count}")

        # Add conversation handler
        conversation_handler = get_save_conversation_handler(db)
        self.application.add_handler(conversation_handler)
        logger.info("ConversationHandler נוסף")

        # ספור שוב
        handler_count_after = len(self.application.handlers)
        logger.info(f"🔍 כמות handlers אחרי: {handler_count_after}")

        # --- GitHub handlers - חייבים להיות לפני ה-handler הגלובלי! ---
        # יצירת instance יחיד של GitHubMenuHandler ושמירה ב-bot_data
        github_handler = GitHubMenuHandler()
        self.application.bot_data['github_handler'] = github_handler
        logger.info("✅ GitHubMenuHandler instance created and stored in bot_data")
        
        # הוסף פקודת github
        self.application.add_handler(CommandHandler("github", github_handler.github_menu_command))
        
        # הוסף את ה-callbacks של GitHub - חשוב! לפני ה-handler הגלובלי
        self.application.add_handler(
            CallbackQueryHandler(github_handler.handle_menu_callback, 
                               pattern=r'^(select_repo|upload_file|upload_saved|show_current|set_token|set_folder|close_menu|folder_|repo_|repos_page_|upload_saved_|back_to_menu|repo_manual|noop|analyze_repo|analyze_current_repo|analyze_other_repo|show_suggestions|show_full_analysis|download_analysis_json|back_to_analysis|back_to_analysis_menu|back_to_summary|choose_my_repo|enter_repo_url|suggestion_\d+|github_menu|logout_github|delete_file_menu|delete_repo_menu|confirm_delete_repo|confirm_delete_repo_step1|confirm_delete_file|danger_delete_menu|download_file_menu|browse_open:.*|browse_select_download:.*|browse_select_delete:.*|browse_page:.*|download_zip:.*|multi_toggle|multi_execute|multi_clear|safe_toggle|browse_toggle_select:.*|inline_download_file:.*|notifications_menu|notifications_toggle|notifications_toggle_pr|notifications_toggle_issues|notifications_interval_.*|notifications_check_now|share_folder_link:.*|share_selected_links|pr_menu|create_pr_menu|branches_page_.*|pr_select_head:.*|confirm_create_pr|merge_pr_menu|prs_page_.*|merge_pr:.*|confirm_merge_pr)')
        )

        # Inline query handler
        self.application.add_handler(InlineQueryHandler(github_handler.handle_inline_query))
        
        # הגדר conversation handler להעלאת קבצים
        from github_menu_handler import FILE_UPLOAD, REPO_SELECT, FOLDER_SELECT
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
            fallbacks=[CommandHandler('cancel', lambda u, c: ConversationHandler.END)]
        )
        
        self.application.add_handler(upload_conv_handler)
        
        # הוסף handler כללי לטיפול בקלט טקסט של GitHub (כולל URL לניתוח)
        async def handle_github_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
            # העבר כל קלט רלוונטי למנהל GitHub לפי דגלים ב-user_data
            text = (update.message.text or '').strip()
            main_menu_texts = {"➕ הוסף קוד חדש", "📚 הצג את כל הקבצים שלי", "📂 קבצים גדולים", "🔧 GitHub"}
            if text in main_menu_texts:
                # נקה דגלים כדי למנוע טריגר שגוי
                context.user_data.pop('waiting_for_repo_url', None)
                context.user_data.pop('waiting_for_delete_file_path', None)
                context.user_data.pop('waiting_for_download_file_path', None)
                return False
            if context.user_data.get('waiting_for_repo_url') or \
               context.user_data.get('waiting_for_delete_file_path') or \
               context.user_data.get('waiting_for_download_file_path'):
                logger.info(f"🔗 Routing GitHub-related text input from user {update.effective_user.id}")
                return await github_handler.handle_text_input(update, context)
            return False
        
        # הוסף את ה-handler עם עדיפות גבוהה
        self.application.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_github_text),
            group=-1  # עדיפות גבוהה מאוד
        )
        
        logger.info("✅ GitHub handler נוסף בהצלחה")
        
        # Handler נפרד לטיפול בטוקן GitHub
        async def handle_github_token(update: Update, context: ContextTypes.DEFAULT_TYPE):
            text = update.message.text
            if text.startswith('ghp_') or text.startswith('github_pat_'):
                user_id = update.message.from_user.id
                if user_id not in github_handler.user_sessions:
                    github_handler.user_sessions[user_id] = {}
                github_handler.user_sessions[user_id]['github_token'] = text
                
                # שמור גם במסד נתונים
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

        # --- רק אחרי כל ה-handlers של GitHub, הוסף את ה-handler הגלובלי ---
        # הוסף CallbackQueryHandler גלובלי לטיפול בכפתורים
        from conversation_handlers import handle_callback_query
        # CallbackQueryHandler כבר מיובא בתחילת הקובץ!
        self.application.add_handler(CallbackQueryHandler(handle_callback_query))
        logger.info("CallbackQueryHandler גלובלי נוסף")

        # ספור סופי
        final_handler_count = len(self.application.handlers)
        logger.info(f"🔍 כמות handlers סופית: {final_handler_count}")

        # הדפס את כל ה-handlers
        for i, handler in enumerate(self.application.handlers):
            logger.info(f"Handler {i}: {type(handler).__name__}")

        # --- שלב 2: רישום שאר הפקודות ---
        # הפקודה /start המקורית הופכת להיות חלק מה-conv_handler, אז היא לא כאן.
        self.application.add_handler(CommandHandler("help", self.help_command))
        self.application.add_handler(CommandHandler("save", self.save_command))
        # self.application.add_handler(CommandHandler("list", self.list_command))  # מחוק - מטופל על ידי הכפתור "📚 הצג את כל הקבצים שלי"
        self.application.add_handler(CommandHandler("search", self.search_command))
        self.application.add_handler(CommandHandler("stats", self.stats_command))
        self.application.add_handler(CommandHandler("check", self.check_commands))
        
        # הוספת פקודות cache
        setup_cache_handlers(self.application)
        
        # --- שלב 3: רישום handler לקבצים ---
        self.application.add_handler(
            MessageHandler(filters.Document.ALL, self.handle_document)
        )
        
        # --- שלב 4: רישום המטפל הכללי בסוף ---
        # הוא יפעל רק אם אף אחד מהמטפלים הספציפיים יותר לא תפס את ההודעה.
        self.application.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_text_message)
        )
        
        # --- שלב 5: טיפול בשגיאות ---
        self.application.add_error_handler(self.error_handler)
    
    # start_command הוסר - ConversationHandler מטפל בפקודת /start
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """פקודת עזרה מפורטת"""
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
        
        await update.message.reply_text(
            f"📝 מוכן לשמור את <code>{safe_file_name}</code>\n"
            f"🏷️ תגיות: {safe_tags}\n\n"
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
                f"🔍 לא נמצאו תוצאות עבור: <code>{html_escape(' '.join(context.args))}</code>",
                parse_mode=ParseMode.HTML
            )
            return
        
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
        
        message = "📋 **סטטוס פקודות:**\n\n"
        message += f"**ציבוריות:** {len(public_cmds)} פקודות\n"
        
        if public_cmds:
            for cmd in public_cmds:
                message += f"  • /{cmd.command}\n"
        
        message += f"\n**אישיות לך:** {len(personal_cmds)} פקודות\n"
        
        if personal_cmds:
            for cmd in personal_cmds:
                message += f"  • /{cmd.command} - {cmd.description}\n"
        
        await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)

    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """הצגת סטטיסטיקות המשתמש או מנהל"""
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
        """טיפול בקבצים שנשלחים לבוט"""
        
        # דיבאג
        logger.info(f"DEBUG: upload_mode = {context.user_data.get('upload_mode')}")
        logger.info(f"DEBUG: waiting_for_github_upload = {context.user_data.get('waiting_for_github_upload')}")
        
        # בדוק אם אנחנו במצב העלאה לגיטהאב (תמיכה בשני המשתנים)
        if context.user_data.get('waiting_for_github_upload') or context.user_data.get('upload_mode') == 'github':
            # תן ל-GitHub handler לטפל בזה
            return
        
        await log_user_activity(update, context)
        
        try:
            document = update.message.document
            user_id = update.effective_user.id
            
            # בדיקת גודל הקובץ (עד 10MB)
            if document.file_size > 10 * 1024 * 1024:
                await update.message.reply_text(
                    "❌ הקובץ גדול מדי!\n"
                    "📏 הגודל המקסימלי המותר הוא 10MB"
                )
                return
            
            # הורדת הקובץ
            await update.message.reply_text("⏳ מוריד את הקובץ...")
            file = await context.bot.get_file(document.file_id)
            
            # קריאת התוכן
            file_bytes = BytesIO()
            await file.download_to_memory(file_bytes)
            file_bytes.seek(0)
            
            # ניסיון לקרוא את הקובץ בקידודים שונים
            content = None
            detected_encoding = None
            encodings_to_try = ['utf-8', 'windows-1255', 'iso-8859-8', 'cp1255', 'utf-16', 'latin-1']
            
            # קרא את הבייטים
            raw_bytes = file_bytes.read()
            file_size_bytes = len(raw_bytes)
            
            # לוג פרטי הקובץ
            logger.info(f"📄 קובץ נשלח: {document.file_name}, גודל: {file_size_bytes} bytes")
            
            # נסה קידודים שונים
            for encoding in encodings_to_try:
                try:
                    content = raw_bytes.decode(encoding)
                    detected_encoding = encoding
                    logger.info(f"✅ הקובץ נקרא בהצלחה בקידוד: {encoding}")
                    break
                except UnicodeDecodeError:
                    continue
            
            if content is None:
                logger.error(f"❌ לא ניתן לקרוא את הקובץ באף קידוד: {encodings_to_try}")
                await update.message.reply_text(
                    "❌ לא ניתן לקרוא את הקובץ!\n"
                    f"📝 ניסיתי את הקידודים: {', '.join(encodings_to_try)}\n"
                    "💡 אנא ודא שזהו קובץ טקסט/קוד ולא קובץ בינארי"
                )
                return
            
            # זיהוי שפת תכנות
            file_name = document.file_name or "untitled.txt"
            from utils import detect_language_from_filename
            language = detect_language_from_filename(file_name)
            
            # בדיקה אם הקובץ גדול (מעל 4096 תווים)
            if len(content) > 4096:
                # שמירה כקובץ גדול
                from database import LargeFile
                large_file = LargeFile(
                    user_id=user_id,
                    file_name=file_name,
                    content=content,
                    programming_language=language,
                    file_size=len(content.encode('utf-8')),
                    lines_count=len(content.split('\n'))
                )
                
                success = db.save_large_file(large_file)
                
                if success:
                    from utils import get_language_emoji
                    emoji = get_language_emoji(language)
                    
                    keyboard = [
                        [InlineKeyboardButton("📚 הצג קבצים גדולים", callback_data="show_large_files")],
                        [InlineKeyboardButton("🏠 תפריט ראשי", callback_data="main")]
                    ]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    
                    lines_count = len(content.split('\n'))
                    await update.message.reply_text(
                        f"✅ **הקובץ נשמר בהצלחה!**\n\n"
                        f"📄 **שם:** `{file_name}`\n"
                        f"{emoji} **שפה:** {language}\n"
                        f"🔤 **קידוד:** {detected_encoding}\n"
                        f"💾 **גודל:** {len(content):,} תווים\n"
                        f"📏 **שורות:** {lines_count:,}\n\n"
                        "💡 הקובץ נשמר במערכת הקבצים הגדולים",
                        reply_markup=reply_markup,
                        parse_mode='Markdown'
                    )
                else:
                    await update.message.reply_text("❌ שגיאה בשמירת הקובץ")
            else:
                # שמירה כקובץ רגיל
                from database import CodeSnippet
                snippet = CodeSnippet(
                    user_id=user_id,
                    file_name=file_name,
                    code=content,
                    programming_language=language
                )
                
                success = db.save_code_snippet(snippet)
                
                if success:
                    from utils import get_language_emoji
                    emoji = get_language_emoji(language)
                    
                    keyboard = [
                        [InlineKeyboardButton("📚 הצג את כל הקבצים", callback_data="files")],
                        [InlineKeyboardButton("🏠 תפריט ראשי", callback_data="main")]
                    ]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    
                    await update.message.reply_text(
                        f"✅ **הקובץ נשמר בהצלחה!**\n\n"
                        f"📄 **שם:** `{file_name}`\n"
                        f"{emoji} **שפה:** {language}\n"
                        f"🔤 **קידוד:** {detected_encoding}\n"
                        f"💾 **גודל:** {len(content)} תווים\n",
                        reply_markup=reply_markup,
                        parse_mode='Markdown'
                    )
                else:
                    await update.message.reply_text("❌ שגיאה בשמירת הקובץ")
            
            reporter.report_activity(user_id)
            
        except Exception as e:
            logger.error(f"שגיאה בטיפול בקובץ: {e}")
            await update.message.reply_text("❌ שגיאה בעיבוד הקובץ")
    
    async def handle_text_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """טיפול בהודעות טקסט (קוד פוטנציאלי)"""
        reporter.report_activity(update.effective_user.id)
        await log_user_activity(update, context)
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
        user_id = update.effective_user.id
        username = update.effective_user.username
        
        # שמור משתמש במסד נתונים (INSERT OR IGNORE)
        db_manager.save_user(user_id, username)
        
        reporter.report_activity(user_id)
        await log_user_activity(update, context)  # הוספת רישום משתמש לסטטיסטיקות
        reply_markup = ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        await update.message.reply_text(
            "👋 שלום! הבוט מוכן לשימוש.\n\n"
            "🔧 לכל תקלה בבוט נא לשלוח הודעה ל-@moominAmir", 
            reply_markup=reply_markup
        )

    async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):  # noqa: D401
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
    # מחיקת כל הפקודות הציבוריות
    await application.bot.delete_my_commands()
    logger.info("✅ All public commands removed")
    
    # הגדרת פקודת stats רק למנהל (אמיר בירון)
    AMIR_ID = 6865105071  # ה-ID של אמיר בירון
    
    try:
        # הגדר את פקודת stats רק לאמיר
        await application.bot.set_my_commands(
            commands=[
                BotCommand("stats", "📊 סטטיסטיקות שימוש")
            ],
            scope=BotCommandScopeChat(chat_id=AMIR_ID)
        )
        logger.info(f"✅ Stats command set for Amir (ID: {AMIR_ID})")
        
    except Exception as e:
        logger.error(f"⚠️ Error setting admin commands: {e}")

if __name__ == "__main__":
    main()
