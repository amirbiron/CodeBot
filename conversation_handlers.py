import logging
import re

from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove, Update
from telegram.ext import (CallbackQueryHandler, CommandHandler, ContextTypes,
                          ConversationHandler, MessageHandler, filters)

from activity_reporter import create_reporter
from database import DatabaseManager

# הגדרת לוגר
logger = logging.getLogger(__name__)

# הגדרת שלבי השיחה - פשוט
GET_CODE, GET_FILENAME = range(2)

# כפתורי המקלדת הראשית
MAIN_KEYBOARD = [["➕ הוסף קוד חדש"], ["📚 הצג את כל הקבצים שלי"]]

reporter = create_reporter()


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """טיפול בפקודת /start - מציג את התפריט הראשי"""
    user_name = update.effective_user.first_name
    welcome_text = (
        f"🤖 שלום {user_name}! ברוך הבא לבוט שומר הקוד!\n\n"
        "🔹 שמור קטעי קוד בקלות\n"
        "🔹 הצג את הקבצים שלך\n\n"
        "בחר פעולה:"
    )

    keyboard = ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
    await update.message.reply_text(welcome_text, reply_markup=keyboard)
    reporter.report_activity(update.effective_user.id)
    return ConversationHandler.END


async def show_all_files(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """מציג את כל הקבצים השמורים של המשתמש"""
    user_id = update.effective_user.id
    from database import db

    try:
        files = db.get_user_files(user_id)

        if not files:
            await update.message.reply_text(
                "📂 אין לך קבצים שמורים עדיין.\n"
                "לחץ על '➕ הוסף קוד חדש' כדי להתחיל!",
                reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
            )
        else:
            response = "📚 הקבצים השמורים שלך:\n\n"
            for i, file in enumerate(files[:10], 1):  # מגביל ל-10 קבצים
                file_name = file.get("file_name", "קובץ ללא שם")
                language = file.get("programming_language", "text")
                response += f"{i}. {file_name} ({language})\n"

            if len(files) > 10:
                response += f"\n... ועוד {len(files) - 10} קבצים"

            await update.message.reply_text(
                response,
                reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
            )

    except Exception as e:
        logger.error(f"Failed to get files for user {user_id}: {e}")
        await update.message.reply_text(
            "❌ שגיאה בהצגת הקבצים. נסה שוב מאוחר יותר.",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
        )

    reporter.report_activity(update.effective_user.id)
    return ConversationHandler.END


async def start_save_flow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """התחלת תהליך שמירת קוד"""
    await update.message.reply_text(
        "שלח לי את קטע הקוד שברצונך לשמור.\n" "כדי לבטל - שלח /cancel",
        reply_markup=ReplyKeyboardRemove(),
    )
    reporter.report_activity(update.effective_user.id)
    return GET_CODE


async def get_code(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """שמירת הקוד וביקש שם קובץ"""
    context.user_data["code_to_save"] = update.message.text
    await update.message.reply_text(
        "✅ הקוד נקלט! עכשיו תן לי שם לקובץ (למשל: my_script.py)"
    )
    reporter.report_activity(update.effective_user.id)
    return GET_FILENAME


async def get_filename(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """שמירת שם הקובץ וסיום התהליך"""
    filename = update.message.text.strip()
    user_id = update.message.from_user.id

    # בדיקה בסיסית של שם קובץ
    if not re.match(r"^[\w\.\-]+\.[a-zA-Z0-9]+$", filename):
        await update.message.reply_text(
            "שם הקובץ נראה לא תקין. נסה שוב (צריך להכיל נקודה לסיומת)."
        )
        return GET_FILENAME

    code = context.user_data.get("code_to_save")

    try:
        # זיהוי אוטומטי של השפה
        from code_processor import code_processor

        detected_language = code_processor.detect_language(code, filename)

        # שמירה במסד הנתונים
        from database import db

        success = db.save_file(user_id, filename, code, detected_language)

        if success:
            await update.message.reply_text(
                f"✅ הקובץ '{filename}' נשמר בהצלחה!\n"
                f"🔍 זוהתה שפת תכנות: {detected_language}",
                reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
            )
        else:
            await update.message.reply_text(
                "❌ אופס, משהו השתבש. נסה שוב מאוחר יותר.",
                reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
            )

    except Exception as e:
        logger.error(f"Failed to save file for user {user_id}: {e}")
        await update.message.reply_text(
            "❌ אופס, משהו השתבש. נסה שוב מאוחר יותר.",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
        )

    # ניקוי ונסיום
    context.user_data.clear()
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """ביטול התהליך הנוכחי"""
    context.user_data.clear()

    await update.message.reply_text(
        "❌ התהליך בוטל.",
        reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
    )
    return ConversationHandler.END


async def handle_callback_query(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """טיפול בסיסי בכפתורים"""
    query = update.callback_query
    await query.answer()

    if query.data == "main":
        await query.edit_message_text("חוזר לתפריט הראשי:")
        await query.message.reply_text(
            "בחר פעולה:",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
        )

    reporter.report_activity(update.effective_user.id)
    return ConversationHandler.END


def get_save_conversation_handler(db: DatabaseManager) -> ConversationHandler:
    """יצירת ConversationHandler פשוט"""
    logger.info("יוצר ConversationHandler פשוט...")

    return ConversationHandler(
        entry_points=[
            CommandHandler("start", start_command),
            MessageHandler(filters.Regex("^➕ הוסף קוד חדש$"), start_save_flow),
            MessageHandler(filters.Regex("^📚 הצג את כל הקבצים שלי$"), show_all_files),
        ],
        states={
            GET_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_code)],
            GET_FILENAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_filename)
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
        ],
        allow_reentry=True,
        per_message=False,
    )
