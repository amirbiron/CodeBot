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
import os

from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand, BotCommandScopeChat
from telegram.constants import ParseMode
from telegram.ext import (Application, CommandHandler, ContextTypes,
                          MessageHandler, filters, Defaults, ConversationHandler, CallbackQueryHandler,
                          PicklePersistence, InlineQueryHandler)

from config import config
from database import CodeSnippet, DatabaseManager, db
from services import code_service as code_processor
from bot_handlers import AdvancedBotHandlers  # still used by legacy code
from conversation_handlers import MAIN_KEYBOARD, get_save_conversation_handler
from activity_reporter import create_reporter
from github_menu_handler import GitHubMenuHandler
from backup_menu_handler import BackupMenuHandler
from file_manager import backup_manager
from large_files_handler import large_files_handler
from user_stats import user_stats
# from cache_commands import setup_cache_handlers  # disabled
# from enhanced_commands import setup_enhanced_handlers  # disabled
from batch_commands import setup_batch_handlers
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
# התקנת מסנן טשטוש נתונים רגישים
try:
    from utils import install_sensitive_filter
    install_sensitive_filter()
except Exception:
    pass

logger = logging.getLogger(__name__)

# הודעת התחלה מרשימה
logger.info("🚀 מפעיל בוט קוד מתקדם - גרסה פרו!")

# הפחתת רעש בלוגים
logging.getLogger("httpx").setLevel(logging.ERROR)  # רק שגיאות קריטיות
logging.getLogger("telegram.ext.Updater").setLevel(logging.ERROR)
logging.getLogger("telegram.ext.Application").setLevel(logging.WARNING)

# יצירת אובייקט reporter גלובלי
reporter = create_reporter(
    mongodb_uri=(os.getenv('REPORTER_MONGODB_URL') or os.getenv('REPORTER_MONGODB_URI') or config.MONGODB_URL),
    service_id=os.getenv('REPORTER_SERVICE_ID', 'srv-d29d72adbo4c73bcuep0'),
    service_name="CodeBot"
)

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
    Returns the lock collection from the same database the app uses
    via DatabaseManager, avoiding reliance on the URI's default database.
    """
    try:
        # Use the already-selected database from DatabaseManager
        selected_db = db.db
        if selected_db is None:
            logger.critical("DatabaseManager.db is not initialized!")
            sys.exit(1)
        # Optional: small debug to help diagnose DB mismatches
        try:
            logger.debug(f"Using DB for locks: {selected_db.name}")
        except Exception:
            pass
        return selected_db[LOCK_COLLECTION]
    except Exception as e:
        logger.critical(f"Failed to get lock collection from DatabaseManager: {e}", exc_info=True)
        sys.exit(1)

# New: ensure TTL index on expires_at so stale locks get auto-removed

def ensure_lock_indexes() -> None:
    try:
        lock_collection = get_lock_collection()
        # TTL based on the absolute expiration time in the document
        lock_collection.create_index("expires_at", expireAfterSeconds=0, name="lock_expires_ttl")
    except Exception as e:
        # Non-fatal; continue without TTL if index creation fails
        logger.warning(f"Could not ensure TTL index for lock collection: {e}")

def cleanup_mongo_lock():
    """Runs on script exit to remove the lock document."""
    try:
        # If DB client is not available, skip quietly
        try:
            if 'db' in globals() and getattr(db, "client", None) is None:
                logger.debug("Mongo client not available during lock cleanup; skipping.")
                return
        except Exception:
            pass

        lock_collection = get_lock_collection()
        pid = os.getpid()
        result = lock_collection.delete_one({"_id": LOCK_ID, "pid": pid})
        if result.deleted_count > 0:
            logger.info(f"Lock '{LOCK_ID}' released successfully by PID: {pid}.")
    except pymongo.errors.InvalidOperation:
        logger.warning("Mongo client already closed; skipping lock cleanup.")
    except Exception as e:
        logger.error(f"Error while releasing MongoDB lock: {e}", exc_info=True)

def manage_mongo_lock():
    """Acquire a distributed lock in MongoDB to ensure a single bot instance runs."""
    try:
        ensure_lock_indexes()
        lock_collection = get_lock_collection()
        pid = os.getpid()
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(minutes=LOCK_TIMEOUT_MINUTES)

        # Try to create the lock document
        try:
            lock_collection.insert_one({"_id": LOCK_ID, "pid": pid, "expires_at": expires_at})
            logger.info(f"✅ MongoDB lock acquired by PID {pid}")
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
                            return False
                    else:
                        # Infinite wait with periodic log
                        logger.warning("Another bot instance is already running (lock present). Waiting for lock release…")
                        time.sleep(retry_interval_seconds)
                        continue
                # If we reach here without breaking, loop will retry
            
        # Ensure lock is released on exit
        atexit.register(cleanup_mongo_lock)
        return True

    except Exception as e:
        logger.error(f"Failed to acquire MongoDB lock: {e}", exc_info=True)
        # Fail-open to not crash the app, but log loudly
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

        # Maintenance gate: if enabled, short-circuit most interactions
        if config.MAINTENANCE_MODE:
            async def maintenance_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
                try:
                    await (update.callback_query.edit_message_text if getattr(update, 'callback_query', None) else update.message.reply_text)(
                        config.MAINTENANCE_MESSAGE
                    )
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
            # תזמון ניקוי תחזוקה לאחר warmup באמצעות JobQueue (לא דורש event loop רץ עכשיו)
            try:
                warmup_secs = max(1, int(config.MAINTENANCE_AUTO_WARMUP_SECS))
                def _clear_handlers_cb(context: ContextTypes.DEFAULT_TYPE):
                    try:
                        app = self.application
                        if getattr(self, "_maintenance_message_handler", None) is not None:
                            app.remove_handler(self._maintenance_message_handler, group=-100)
                        if getattr(self, "_maintenance_callback_handler", None) is not None:
                            app.remove_handler(self._maintenance_callback_handler, group=-100)
                        logger.warning("MAINTENANCE_MODE auto-warmup window elapsed; resuming normal operation")
                    except Exception:
                        pass
                # Schedule one-time run after warmup
                self.application.job_queue.run_once(lambda ctx: _clear_handlers_cb(ctx), when=warmup_secs)
            except Exception:
                pass
            # ממשיכים לרשום את שאר ה-handlers כדי שיקלטו אוטומטית אחרי ה-warmup

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
        # יצירת BackupMenuHandler ושמירה
        backup_handler = BackupMenuHandler()
        self.application.bot_data['backup_handler'] = backup_handler
        logger.info("✅ BackupMenuHandler instance created and stored in bot_data")
        
        # הוסף פקודת github
        self.application.add_handler(CommandHandler("github", github_handler.github_menu_command))
        # הוסף תפריט גיבוי/שחזור
        async def show_backup_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
            await backup_handler.show_backup_menu(update, context)
        self.application.add_handler(CommandHandler("backup", show_backup_menu))
        self.application.add_handler(CallbackQueryHandler(backup_handler.handle_callback_query, pattern=r'^backup_'))
        
        # הוסף את ה-callbacks של GitHub - חשוב! לפני ה-handler הגלובלי
        self.application.add_handler(
                        CallbackQueryHandler(github_handler.handle_menu_callback, 
                               pattern=r'^(select_repo|upload_file|upload_saved|show_current|set_token|set_folder|close_menu|folder_|repo_|repos_page_|upload_saved_|back_to_menu|repo_manual|noop|analyze_repo|analyze_current_repo|analyze_other_repo|show_suggestions|show_full_analysis|download_analysis_json|back_to_analysis|back_to_analysis_menu|back_to_summary|choose_my_repo|enter_repo_url|suggestion_\d+|github_menu|logout_github|delete_file_menu|delete_repo_menu|confirm_delete_repo|confirm_delete_repo_step1|confirm_delete_file|danger_delete_menu|download_file_menu|browse_open:.*|browse_select_download:.*|browse_select_delete:.*|browse_page:.*|download_zip:.*|multi_toggle|multi_execute|multi_clear|safe_toggle|browse_toggle_select:.*|inline_download_file:.*|notifications_menu|notifications_toggle|notifications_toggle_pr|notifications_toggle_issues|notifications_interval_.*|notifications_check_now|share_folder_link:.*|share_selected_links|pr_menu|create_pr_menu|branches_page_.*|pr_select_head:.*|confirm_create_pr|merge_pr_menu|prs_page_.*|merge_pr:.*|confirm_merge_pr|validate_repo|git_checkpoint|git_checkpoint_doc:.*|git_checkpoint_doc_skip|restore_checkpoint_menu|restore_tags_page_.*|restore_select_tag:.*|restore_branch_from_tag:.*|restore_revert_pr_from_tag:.*|open_pr_from_branch:.*|choose_upload_branch|upload_branches_page_.*|upload_select_branch:.*|choose_upload_folder|upload_select_folder:.*|upload_folder_root|upload_folder_current|upload_folder_custom|upload_folder_create|create_folder|confirm_saved_upload|refresh_saved_checks|github_backup_menu|github_backup_help|github_restore_zip_to_repo|github_restore_zip_setpurge:.*|github_restore_zip_list|github_restore_zip_from_backup:.*|github_repo_restore_backup_setpurge:.*|gh_upload_cat:.*|gh_upload_repo:.*|gh_upload_large:.*|backup_menu|github_create_repo_from_zip|github_new_repo_name|github_set_new_repo_visibility:.*|upload_paste_code)')
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
            if context.user_data.get('waiting_for_repo_url') or \
               context.user_data.get('waiting_for_delete_file_path') or \
               context.user_data.get('waiting_for_download_file_path') or \
               context.user_data.get('waiting_for_new_repo_name') or \
               context.user_data.get('waiting_for_selected_folder') or \
               context.user_data.get('waiting_for_new_folder_path') or \
               context.user_data.get('waiting_for_paste_content') or \
               context.user_data.get('waiting_for_paste_filename'):
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

        # הוספת פקודות batch (עיבוד מרובה קבצים) לפני ההנדלר הגלובלי כדי שיתפוס את התבניות שלו
        setup_batch_handlers(self.application)
        
        # --- רק אחרי כל ה-handlers הספציפיים, הוסף את ה-handler הגלובלי ---
        from conversation_handlers import handle_callback_query
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
        
        # הוספת פקודות cache - disabled
        # setup_cache_handlers(self.application)
        
        # הוספת פקודות משופרות (אוטו-השלמה ותצוגה מקדימה) - disabled
        # setup_enhanced_handlers(self.application)

        # הטרמינל הוסר בסביבת Render (Docker לא זמין)


        # הוספת handlers לכפתורים החדשים במקלדת הראשית
        from conversation_handlers import handle_batch_button
        self.application.add_handler(MessageHandler(
            filters.Regex("^⚡ עיבוד Batch$"), 
            handle_batch_button
        ))
        # כפתור חדש לתפריט גיבוי/שחזור
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
        
        # שחזור ZIP ישירות לריפו בגיטהאב (פריסה והחלפה)
        if context.user_data.get('upload_mode') == 'github_restore_zip_to_repo':
            try:
                document = update.message.document
                user_id = update.effective_user.id
                logger.info(f"GitHub restore-to-repo ZIP received: file_name={document.file_name}, size={document.file_size}")
                await update.message.reply_text("⏳ מוריד קובץ ZIP...")
                file = await context.bot.get_file(document.file_id)
                buf = BytesIO()
                await file.download_to_memory(buf)
                buf.seek(0)
                import zipfile
                if not zipfile.is_zipfile(buf):
                    await update.message.reply_text("❌ הקובץ שהועלה אינו ZIP תקין.")
                    return
                # חלץ את ה-ZIP לזיכרון לרשימת קבצים
                zf = zipfile.ZipFile(buf, 'r')
                # סינון ערכי מערכת של macOS וכד'. נשמור רק קבצים אמיתיים
                all_names = [n for n in zf.namelist() if not n.endswith('/')]
                members = [n for n in all_names if not (n.startswith('__MACOSX/') or n.split('/')[-1].startswith('._'))]
                # זיהוי תיקיית-שורש משותפת (אם כל הקבצים חולקים את אותו הסגמנט העליון)
                top_levels = set()
                for n in zf.namelist():
                    if '/' in n and not n.startswith('__MACOSX/'):
                        top_levels.add(n.split('/', 1)[0])
                common_root = list(top_levels)[0] if len(top_levels) == 1 else None
                logger.info(f"[restore_zip] Detected common_root={common_root!r}, files_in_zip={len(members)}")
                # נקה תיקיית root של GitHub zip רק אם זוהתה תיקיית-שורש משותפת אחת
                def strip_root(path: str) -> str:
                    if common_root and path.startswith(common_root + '/'):
                        return path[len(common_root) + 1:]
                    return path
                files = []
                for name in members:
                    raw = zf.read(name)
                    clean = strip_root(name)
                    if not clean:
                        continue
                    files.append((clean, raw))
                if not files:
                    await update.message.reply_text("❌ לא נמצאו קבצים בתוך ה-ZIP")
                    return
                # העלאה לגיטהאב באמצעות Trees API לעדכון מרובה קבצים
                from github import Github
                from github.InputGitTreeElement import InputGitTreeElement
                github_handler = context.bot_data.get('github_handler')
                session = github_handler.get_user_session(user_id)
                token = github_handler.get_user_token(user_id)
                repo_full = session.get('selected_repo')
                if not (token and repo_full):
                    await update.message.reply_text("❌ אין טוקן או ריפו נבחר")
                    return
                # יעד נעול לבטיחות: אם נקבע בתחילת הזרימה, תמיד נעדיף אותו
                expected_repo_full = context.user_data.get('zip_restore_expected_repo_full')
                repo_full_effective = expected_repo_full or repo_full
                if expected_repo_full and expected_repo_full != repo_full:
                    # דווח על סטייה אבל המשך בבטחה עם היעד הנעול
                    logger.warning(f"[restore_zip] Target mismatch: expected={expected_repo_full}, got={repo_full}. Proceeding with expected (locked) target.")
                    try:
                        await update.message.reply_text(
                            f"⚠️ נמצא פער בין היעד הנוכחי ({repo_full}) ליעד הנעול. נשתמש ביעד הנעול: {expected_repo_full}")
                    except Exception:
                        pass
                # אם לא נשמר יעד צפוי (גרסה ישנה), קבע אותו כעת
                if not expected_repo_full:
                    try:
                        context.user_data['zip_restore_expected_repo_full'] = repo_full
                    except Exception:
                        pass
                g = Github(token)
                # נסיון גישה ליעד הנעול/האפקטיבי עם נפילה בטוחה
                try:
                    repo = g.get_repo(repo_full_effective)
                except Exception as e:
                    logger.exception(f"[restore_zip] Locked target not accessible: {repo_full_effective}: {e}")
                    # נפילה בטוחה: אם אותו בעלים והריפו הנוכחי שונה – נסה את הריפו הנוכחי
                    fallback_used = False
                    if repo_full and repo_full != repo_full_effective:
                        try:
                            expected_owner = (expected_repo_full or repo_full_effective).split('/')[0]
                            current_owner = repo_full.split('/')[0]
                        except Exception:
                            expected_owner = None
                            current_owner = None
                        if expected_owner and current_owner and current_owner == expected_owner:
                            try:
                                await update.message.reply_text(
                                    f"⚠️ היעד הנעול {repo_full_effective} לא נגיש. מנסה להשתמש ביעד הנוכחי {repo_full} (אותו בעלים).")
                            except Exception:
                                pass
                            try:
                                repo = g.get_repo(repo_full)
                                repo_full_effective = repo_full
                                fallback_used = True
                            except Exception as e2:
                                logger.exception(f"[restore_zip] Fallback to current repo failed: {e2}")
                    if 'repo' not in locals():
                        await update.message.reply_text(
                            f"❌ היעד {repo_full_effective} לא נגיש ואין נפילה בטוחה. עצירה. אנא בחרו ריפו מחדש.")
                        raise
                target_branch = repo.default_branch or 'main'
                purge_first = bool(context.user_data.get('github_restore_zip_purge'))
                await update.message.reply_text(
                    ("🧹 מנקה קבצים קיימים...\n" if purge_first else "") +
                    f"📤 מעלה {len(files)} קבצים לריפו {repo_full_effective} (branch: {target_branch})..."
                )
                # בסיס לעץ
                base_ref = repo.get_git_ref(f"heads/{target_branch}")
                base_commit = repo.get_git_commit(base_ref.object.sha)
                base_tree = base_commit.tree
                new_tree_elements = []
                # בנה עצי קלט
                for path, raw in files:
                    # שמור על קידוד נכון: טקסט כ-utf-8, בינארי כ-base64
                    import base64
                    text_exts = ('.md', '.txt', '.json', '.yml', '.yaml', '.xml', '.py', '.js', '.ts', '.tsx', '.css', '.scss', '.html', '.sh', '.gitignore')
                    is_text = path.lower().endswith(text_exts)
                    try:
                        if is_text:
                            text = raw.decode('utf-8')
                            blob = repo.create_git_blob(text, 'utf-8')
                        else:
                            b64 = base64.b64encode(raw).decode('ascii')
                            blob = repo.create_git_blob(b64, 'base64')
                    except Exception:
                        # נפילה לבינארי אם כשל פענוח
                        b64 = base64.b64encode(raw).decode('ascii')
                        blob = repo.create_git_blob(b64, 'base64')
                    elem = InputGitTreeElement(path=path, mode='100644', type='blob', sha=blob.sha)
                    new_tree_elements.append(elem)
                if purge_first:
                    # Soft purge: יצירת עץ חדש ללא בסיס (מוחק קבצים שאינם ב-ZIP)
                    new_tree = repo.create_git_tree(new_tree_elements)
                else:
                    new_tree = repo.create_git_tree(new_tree_elements, base_tree)
                commit_message = f"Restore from ZIP via bot: replace {'with purge' if purge_first else 'update only'}"
                new_commit = repo.create_git_commit(commit_message, new_tree, [base_commit])
                base_ref.edit(new_commit.sha)
                logger.info(f"[restore_zip] Restore commit created: {new_commit.sha}, files_added={len(new_tree_elements)}, purge={purge_first}")
                await update.message.reply_text("✅ השחזור הועלה לריפו בהצלחה")
            except Exception as e:
                logger.exception(f"GitHub restore-to-repo failed: {e}")
                await update.message.reply_text(f"❌ שגיאה בשחזור לריפו: {e}")
                # התראת OOM לאדמין אם מזוהה חריגת זיכרון
                try:
                    msg = str(e)
                    if isinstance(e, MemoryError) or 'Ran out of memory' in msg or 'out of memory' in msg.lower():
                        await notify_admins(context, f"🚨 OOM בשחזור ZIP לריפו: {msg}")
                except Exception:
                    pass
            finally:
                context.user_data['upload_mode'] = None
                context.user_data.pop('github_restore_zip_purge', None)
                try:
                    context.user_data.pop('zip_restore_expected_repo_full', None)
                except Exception:
                    pass
            return
        
        # יצירת ריפו חדש מ‑ZIP (פריסה לתוך ריפו חדש)
        if context.user_data.get('upload_mode') == 'github_create_repo_from_zip':
            try:
                document = update.message.document
                user_id = update.effective_user.id
                logger.info(f"GitHub create-repo-from-zip received: file_name={document.file_name}, size={document.file_size}")
                await update.message.reply_text("⏳ מוריד קובץ ZIP...")
                tg_file = await context.bot.get_file(document.file_id)
                buf = BytesIO()
                await tg_file.download_to_memory(buf)
                buf.seek(0)
                import zipfile, re, os
                if not zipfile.is_zipfile(buf):
                    await update.message.reply_text("❌ הקובץ שהועלה אינו ZIP תקין.")
                    return
                # חלץ שמות ובחר שם בסיס לריפו אם לא הוזן מראש
                with zipfile.ZipFile(buf, 'r') as zf:
                    names_all = zf.namelist()
                    file_names = [n for n in names_all if not n.endswith('/') and not n.startswith('__MACOSX/') and not n.split('/')[-1].startswith('._')]
                    if not file_names:
                        await update.message.reply_text("❌ ה‑ZIP ריק." )
                        return
                    # גלה root משותף אם קיים
                    top_levels = set()
                    for n in names_all:
                        if '/' in n and not n.startswith('__MACOSX/'):
                            top_levels.add(n.split('/', 1)[0])
                    common_root = list(top_levels)[0] if len(top_levels) == 1 else None
                # קבע שם ריפו
                repo_name = context.user_data.get('new_repo_name')
                if not repo_name:
                    base_guess = None
                    if common_root:
                        base_guess = common_root
                    elif document.file_name:
                        base_guess = os.path.splitext(os.path.basename(document.file_name))[0]
                    if not base_guess:
                        base_guess = f"repo-{int(time.time())}"
                    # sanitize
                    repo_name = re.sub(r"\s+", "-", base_guess)
                    repo_name = re.sub(r"[^A-Za-z0-9._-]", "-", repo_name).strip(".-_") or f"repo-{int(time.time())}"
                # התחבר ל‑GitHub וצור ריפו
                github_handler = context.bot_data.get('github_handler')
                token = github_handler.get_user_token(user_id) if github_handler else None
                if not token:
                    await update.message.reply_text("❌ אין טוקן GitHub. שלח /github כדי להתחבר.")
                    return
                await update.message.reply_text(f"📦 יוצר ריפו חדש: <code>{repo_name}</code>", parse_mode=ParseMode.HTML)
                from github import Github
                g = Github(token)
                user = g.get_user()
                repo = user.create_repo(
                    name=repo_name,
                    private=bool(context.user_data.get('new_repo_private', True)),
                    auto_init=False
                )
                repo_full = repo.full_name
                # שמור כריפו נבחר במסד ובסשן
                try:
                    db.save_selected_repo(user_id, repo_full)
                    sess = github_handler.get_user_session(user_id)
                    sess['selected_repo'] = repo_full
                except Exception as e:
                    logger.warning(f"Failed saving selected repo: {e}")
                # כעת פרוס את ה‑ZIP לריפו החדש ב‑commit אחד
                await update.message.reply_text("📤 מעלה את קבצי ה‑ZIP לריפו החדש...")
                # קרא שוב את ה‑ZIP (ה‑buf הוזז קדימה)
                buf.seek(0)
                with zipfile.ZipFile(buf, 'r') as zf:
                    names_all = zf.namelist()
                    members = [n for n in names_all if not n.endswith('/') and not n.startswith('__MACOSX/') and not n.split('/')[-1].startswith('._')]
                    top_levels = set()
                    for n in names_all:
                        if '/' in n and not n.startswith('__MACOSX/'):
                            top_levels.add(n.split('/', 1)[0])
                    common_root = list(top_levels)[0] if len(top_levels) == 1 else None
                    def strip_root(p: str) -> str:
                        if common_root and p.startswith(common_root + '/'): return p[len(common_root)+1:]
                        return p
                    files = []
                    for name in members:
                        data = zf.read(name)
                        clean = strip_root(name)
                        if clean:
                            files.append((clean, data))
                # העלאה: אם הריפו ריק לחלוטין, Git Data API עלול להחזיר 409. במקרה כזה נשתמש ב‑Contents API להעלאה קובץ‑קובץ.
                from github.GithubException import GithubException
                target_branch = (repo.default_branch or 'main')
                base_ref = None
                base_commit = None
                base_tree = None
                try:
                    base_ref = repo.get_git_ref(f"heads/{target_branch}")
                    base_commit = repo.get_git_commit(base_ref.object.sha)
                    base_tree = base_commit.tree
                except GithubException as _e:
                    logger.info(f"No base ref found for new repo (expected for empty repo): {str(_e)}")

                if base_commit is None:
                    # ריפו ריק: נעלה קבצים באמצעות Contents API (commit לכל קובץ)
                    created_count = 0
                    for path, raw in files:
                        try:
                            try:
                                text = raw.decode('utf-8')
                                repo.create_file(path=path, message="Initial import from ZIP via bot", content=text, branch=target_branch)
                            except UnicodeDecodeError:
                                # תוכן בינארי – שלח כ-bytes; PyGithub ידאג לקידוד Base64
                                repo.create_file(path=path, message="Initial import from ZIP via bot (binary)", content=raw, branch=target_branch)
                            created_count += 1
                        except Exception as e_file:
                            logger.warning(f"[create_repo_from_zip] Failed to create file {path}: {e_file}")
                    await update.message.reply_text(
                        f"✅ נוצר ריפו חדש והוזנו {created_count} קבצים\n🔗 <a href=\"https://github.com/{repo_full}\">{repo_full}</a>",
                        parse_mode=ParseMode.HTML
                    )
                    return

                # אחרת: יש commit בסיס – נשתמש ב‑Git Trees API לביצוע commit מרוכז אחד
                from github.InputGitTreeElement import InputGitTreeElement
                import base64
                text_exts = ('.md', '.txt', '.json', '.yml', '.yaml', '.xml', '.py', '.js', '.ts', '.tsx', '.css', '.scss', '.html', '.sh', '.gitignore')
                new_tree_elems = []
                for path, raw in files:
                    try:
                        if path.lower().endswith(text_exts):
                            blob = repo.create_git_blob(raw.decode('utf-8'), 'utf-8')
                        else:
                            blob = repo.create_git_blob(base64.b64encode(raw).decode('ascii'), 'base64')
                    except Exception:
                        blob = repo.create_git_blob(base64.b64encode(raw).decode('ascii'), 'base64')
                    new_tree_elems.append(InputGitTreeElement(path=path, mode='100644', type='blob', sha=blob.sha))
                new_tree = repo.create_git_tree(new_tree_elems, base_tree)
                commit_message = "Initial import from ZIP via bot"
                parents = [base_commit]
                new_commit = repo.create_git_commit(commit_message, new_tree, parents)
                base_ref.edit(new_commit.sha)
                await update.message.reply_text(
                    f"✅ נוצר ריפו חדש והוזנו {len(new_tree_elems)} קבצים\n🔗 <a href=\"https://github.com/{repo_full}\">{repo_full}</a>",
                    parse_mode=ParseMode.HTML
                )
            except Exception as e:
                logger.exception(f"Create new repo from ZIP failed: {e}")
                await update.message.reply_text(f"❌ שגיאה ביצירת ריפו מ‑ZIP: {e}")
                # התראת OOM לאדמין אם מזוהה חריגת זיכרון
                try:
                    msg = str(e)
                    if isinstance(e, MemoryError) or 'Ran out of memory' in msg or 'out of memory' in msg.lower():
                        await notify_admins(context, f"🚨 OOM ביצירת ריפו מ‑ZIP: {msg}")
                except Exception:
                    pass
            finally:
                # נקה דגלי זרימה
                context.user_data['upload_mode'] = None
                for k in ('new_repo_name', 'new_repo_private'):
                    context.user_data.pop(k, None)
            return
        
        # בדוק אם אנחנו במצב העלאה לגיטהאב (תמיכה בשני המשתנים)
        if context.user_data.get('waiting_for_github_upload') or context.user_data.get('upload_mode') == 'github':
            # נהל את ההעלאה ישירות דרך מנהל GitHub כדי לא לאבד את האירוע
            github_handler = context.bot_data.get('github_handler')
            if github_handler:
                await github_handler.handle_file_upload(update, context)
            return
        
        # ייבוא ZIP ראשוני (ללא מחיקה): קבלת ZIP ושמירה כקבצים עם תגית ריפו אם קיימת
        if context.user_data.get('upload_mode') == 'zip_import':
            try:
                document = update.message.document
                user_id = update.effective_user.id
                logger.info(f"ZIP import received: file_name={document.file_name}, mime_type={document.mime_type}, size={document.file_size}")
                await update.message.reply_text("⏳ מוריד קובץ ZIP...")
                file = await context.bot.get_file(document.file_id)
                buf = BytesIO()
                await file.download_to_memory(buf)
                buf.seek(0)
                # שמור זמנית לדיסק
                import tempfile, os, zipfile
                tmp_dir = tempfile.gettempdir()
                safe_name = (document.file_name or 'repo.zip')
                if not safe_name.lower().endswith('.zip'):
                    safe_name += '.zip'
                tmp_path = os.path.join(tmp_dir, safe_name)
                with open(tmp_path, 'wb') as f:
                    f.write(buf.getvalue())
                # בדיקת ZIP תקין
                if not zipfile.is_zipfile(tmp_path):
                    logger.warning(f"Uploaded file is not a valid ZIP: {tmp_path}")
                    await update.message.reply_text("❌ הקובץ שהועלה אינו ZIP תקין.")
                    return
                # נסה לקרוא metadata כדי לצרף תגית repo
                import json
                repo_tag = []
                try:
                    with zipfile.ZipFile(tmp_path, 'r') as zf:
                        md = json.loads(zf.read('metadata.json'))
                        if md.get('repo'):
                            repo_tag = [f"repo:{md['repo']}"]
                except Exception:
                    pass
                # בצע ייבוא ללא מחיקה, עם תגיות אם קיימות
                results = backup_manager.restore_from_backup(user_id=user_id, backup_path=tmp_path, overwrite=True, purge=False, extra_tags=repo_tag)
                restored = results.get('restored_files', 0)
                errors = results.get('errors', [])
                if errors:
                    # הצג תקציר שגיאות כדי לעזור באבחון
                    preview = "\n".join([str(e) for e in errors[:3]])
                    msg = (
                        f"⚠️ הייבוא הושלם חלקית: {restored} קבצים נשמרו\n"
                        f"שגיאות: {len(errors)}\n"
                        f"דוגמאות:\n{preview}"
                    )
                else:
                    msg = f"✅ יובאו {restored} קבצים בהצלחה"
                await update.message.reply_text(msg)
            except Exception as e:
                logger.exception(f"ZIP import failed: {e}")
                await update.message.reply_text(f"❌ שגיאה בייבוא ZIP: {e}")
            finally:
                context.user_data['upload_mode'] = None
            return

        # מצב איסוף קבצים ליצירת ZIP מקומי
        if context.user_data.get('upload_mode') == 'zip_create':
            try:
                document = update.message.document
                user_id = update.effective_user.id
                logger.info(f"ZIP create mode: received file for bundle: {document.file_name} ({document.file_size} bytes)")
                # הורדה לזיכרון
                file = await context.bot.get_file(document.file_id)
                buf = BytesIO()
                await file.download_to_memory(buf)
                raw = buf.getvalue()
                # שמירה לרשימת הפריטים בסשן
                items = context.user_data.get('zip_create_items')
                if items is None:
                    items = []
                    context.user_data['zip_create_items'] = items
                # קביעת שם בטוח
                safe_name = (document.file_name or f"file_{len(items)+1}").strip() or f"file_{len(items)+1}"
                items.append({
                    'filename': safe_name,
                    'bytes': raw,
                })
                await update.message.reply_text(f"✅ נוסף: <code>{html_escape(safe_name)}</code> (סה""כ {len(items)} קבצים)", parse_mode=ParseMode.HTML)
            except Exception as e:
                logger.exception(f"zip_create collect failed: {e}")
                await update.message.reply_text(f"❌ שגיאה בהוספת הקובץ ל‑ZIP: {e}")
            return
        
        await log_user_activity(update, context)
        
        try:
            document = update.message.document
            user_id = update.effective_user.id
            
            # בדיקת גודל הקובץ (עד 20MB)
            if document.file_size > 20 * 1024 * 1024:
                await update.message.reply_text(
                    "❌ הקובץ גדול מדי!\n"
                    "📏 הגודל המקסימלי המותר הוא 20MB"
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
            
            # לוג פרטי הקובץ
            logger.info(f"📄 קובץ נשלח: {document.file_name}, גודל: {document.file_size} bytes")
            
            # קרא את הבייטים
            raw_bytes = file_bytes.read()
            file_size_bytes = len(raw_bytes)
            
            # אם הקובץ הוא ZIP (גם אם הועלה "סתם" במסלול קבצים), נשמור עותק לתיקיית ה-ZIP השמורים
            try:
                import zipfile as _zip
                from io import BytesIO as _BytesIO
                is_zip_hint = ((document.mime_type or '').lower() == 'application/zip') or ((document.file_name or '').lower().endswith('.zip'))
                is_zip_actual = False
                try:
                    is_zip_actual = _zip.is_zipfile(_BytesIO(raw_bytes))
                except Exception:
                    is_zip_actual = False
                if is_zip_hint and is_zip_actual:
                    from file_manager import backup_manager
                    backup_id = f"upload_{user_id}_{int(datetime.now(timezone.utc).timestamp())}"
                    target_path = backup_manager.backup_dir / f"{backup_id}.zip"
                    try:
                        # הוסף metadata.json בסיסי (אם חסר) ושמור בהתאם לאחסון (Mongo/FS)
                        try:
                            # נסה לפתוח את ה-ZIP המקורי כדי לבדוק מטאדטה
                            ztest = _zip.ZipFile(_BytesIO(raw_bytes))
                            try:
                                ztest.getinfo('metadata.json')
                                # כבר קיים metadata.json – נשמור כמו שהוא
                                md_bytes = raw_bytes
                            except KeyError:
                                # הזרקת מטאדטה
                                md = {
                                    "backup_id": backup_id,
                                    "backup_type": "generic_zip",
                                    "user_id": user_id,
                                    "created_at": datetime.now(timezone.utc).isoformat(),
                                    "original_filename": document.file_name,
                                    "source": "uploaded_document"
                                }
                                out_buf = _BytesIO()
                                with _zip.ZipFile(out_buf, 'w', compression=_zip.ZIP_DEFLATED) as zout:
                                    # העתק את התוכן
                                    for name in ztest.namelist():
                                        zout.writestr(name, ztest.read(name))
                                    zout.writestr('metadata.json', json.dumps(md, indent=2))
                                md_bytes = out_buf.getvalue()
                        except Exception:
                            # אם לא מצליחים לקרוא כ-ZIP, נשמור את הבייטים המקוריים
                            md_bytes = raw_bytes

                        # שמירה לפי מצב האחסון
                        try:
                            backup_manager.save_backup_bytes(md_bytes, {"backup_id": backup_id, "backup_type": "generic_zip", "user_id": user_id, "created_at": datetime.now(timezone.utc).isoformat(), "original_filename": document.file_name, "source": "uploaded_document"})
                        except Exception:
                            # נפילה לשמירה לדיסק כניסיון אחרון
                            with open(target_path, 'wb') as fzip:
                                fzip.write(md_bytes)
                        await update.message.reply_text(
                            "✅ קובץ ZIP נשמר בהצלחה לרשימת ה‑ZIP השמורים.\n"
                            "📦 ניתן למצוא אותו תחת: '📚' > '📦 קבצי ZIP' או ב‑Batch/GitHub.")
                        return
                    except Exception as e:
                        logger.warning(f"Failed to persist uploaded ZIP: {e}")
                        # המשך לזרימת קריאת טקסט הרגילה
            except Exception:
                pass

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
        if db.save_code_snippet(snippet):
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
        
        # שחרור נעילה וסגירת חיבור למסד נתונים
        try:
            cleanup_mongo_lock()
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
