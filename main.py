#!/usr/bin/env python3
"""
בוט שומר קבצי קוד - Code Keeper Bot
נקודת הכניסה הראשית לבוט - גרסה פשוטה
"""

import logging
import sys

from telegram.ext import Application
from telegram.constants import ParseMode

from config import config
from database import DatabaseManager, db
from conversation_handlers import get_save_conversation_handler
from activity_reporter import create_reporter

# הגדרת לוגים פשוטה
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)

# יצירת reporter פשוט
reporter = create_reporter()

class SimpleCodeKeeperBot:
    """גרסה פשוטה של בוט שומר הקוד"""
    
    def __init__(self):
        self.application = Application.builder().token(config.BOT_TOKEN).build()
        self.setup_handlers()
    
    def setup_handlers(self):
        """הגדרת handlers בסיסיים"""
        # הוספת conversation handler לשמירת קבצים
        conversation_handler = get_save_conversation_handler(db)
        self.application.add_handler(conversation_handler)
        
        # הוספת CallbackQueryHandler לטיפול בכפתורים
        from conversation_handlers import handle_callback_query
        from telegram.ext import CallbackQueryHandler
        self.application.add_handler(CallbackQueryHandler(handle_callback_query))
        
        # פקודות בסיסיות
        from telegram.ext import CommandHandler
        self.application.add_handler(CommandHandler("help", self.help_command))
        
        # טיפול בשגיאות
        self.application.add_error_handler(self.error_handler)
        
        logger.info("✅ Bot handlers setup completed")
    
    async def help_command(self, update, context):
        """פקודת עזרה פשוטה"""
        reporter.report_activity(update.effective_user.id)
        await update.message.reply_text(
            "🤖 ברוך הבא לבוט שומר הקוד!\n\n"
            "השתמש ב/start כדי להתחיל\n"
            "או לחץ על הכפתורים למטה לפעולות מהירות"
        )
    
    async def error_handler(self, update, context):
        """טיפול בשגיאות פשוט"""
        logger.error(f"Error occurred: {context.error}")
        if update and update.effective_message:
            await update.effective_message.reply_text(
                "❌ אירעה שגיאה. אנא נסה שוב."
            )


def main():
    """הפעלת הבוט - גרסה פשוטה"""
    try:
        # אתחול מסד נתונים
        global db
        db = DatabaseManager()
        logger.info("✅ Database connected")
        
        # יצירת הבוט
        bot = SimpleCodeKeeperBot()
        logger.info("✅ Bot created")
        
        # הפעלת הבוט
        logger.info("🚀 Starting bot...")
        bot.application.run_polling(drop_pending_updates=True)
        
    except Exception as e:
        logger.error(f"Error starting bot: {e}")
        raise
    finally:
        if 'db' in globals():
            db.close_connection()
        logger.info("Bot stopped")


if __name__ == "__main__":
    main()
