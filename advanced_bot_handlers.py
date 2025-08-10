# advanced_bot_handlers.py
import logging
from io import BytesIO

from telegram import InputFile, Update
from telegram.ext import Application, CallbackQueryHandler, ContextTypes

from activity_reporter import create_reporter

logger = logging.getLogger(__name__)

reporter = create_reporter(
    mongodb_uri="mongodb+srv://mumin:M43M2TFgLfGvhBwY@muminai.tm6x81b.mongodb.net/?retryWrites=true&w=majority&appName=muminAI",
    service_id="srv-d29d72adbo4c73bcuep0",
    service_name="CodeBot",
)


class AdvancedBotHandlers:
    def __init__(self, db):
        # Save reference to the database manager that is injected from the caller
        self.db = db

    async def _delete_file(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Handles the 'Delete' button. Deletes the file from the DB and updates the message.
        """
        reporter.report_activity(update.effective_user.id)
        query = update.callback_query
        await query.answer()

        try:
            file_id = query.data.split("_")[1]
            # נניח שקיימת פונקציה כזו במנהל מסד הנתונים שלך
            deleted_count = self.db.delete_file_by_id(file_id)  # type: ignore[attr-defined]

            if deleted_count > 0:
                await query.edit_message_text(text="✅ הקובץ נמחק בהצלחה.")
            else:
                await query.edit_message_text(text="⚠️ לא נמצא קובץ למחיקה. ייתכן שכבר נמחק.")
        except Exception as e:
            logger.error(f"Error in _delete_file: {e}")
            await query.edit_message_text("❌ אירעה שגיאה בעת ניסיון המחיקה.")

    async def _download_file(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Handles the 'Download' button. Sends the code as a text file.
        """
        reporter.report_activity(update.effective_user.id)
        query = update.callback_query
        await query.answer()

        try:
            file_id = query.data.split("_")[1]
            file_data = self.db.get_file_by_id(file_id)  # type: ignore[attr-defined]

            if not file_data:
                await query.edit_message_text("⚠️ הקובץ לא נמצא.")
                return

            file_name = file_data.get("file_name", "file.txt")
            code_content = file_data.get("code", "")

            file_in_memory = BytesIO(code_content.encode("utf-8"))

            await context.bot.send_document(
                chat_id=query.message.chat_id,
                document=InputFile(file_in_memory, filename=file_name),
                caption=f"הקובץ '{file_name}' מוכן להורדה.",
            )
        except Exception as e:
            logger.error(f"Error in _download_file: {e}")
            await query.message.reply_text("❌ אירעה שגיאה בעת הכנת הקובץ להורדה.")

    async def _share_file(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Handles the 'Share' button. Currently a placeholder.
        """
        reporter.report_activity(update.effective_user.id)
        query = update.callback_query
        # מציג התראה קופצת למשתמש
        await query.answer("פיצ'ר השיתוף עדיין בפיתוח!", show_alert=True)


def setup_advanced_handlers(application: Application, db):
    """Register the new callback query handlers for Advanced actions."""
    handlers = AdvancedBotHandlers(db)

    # הוספת המטפלים החדשים
    application.add_handler(CallbackQueryHandler(handlers._delete_file, pattern="^delete_"))
    application.add_handler(CallbackQueryHandler(handlers._download_file, pattern="^download_"))
    application.add_handler(CallbackQueryHandler(handlers._share_file, pattern="^share_"))

    # Here you can keep registering other existing handlers if needed
