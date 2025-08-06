import logging
import re
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CommandHandler,
    MessageHandler,
    filters,
)
from database import DatabaseManager

# הגדרת לוגר
logger = logging.getLogger(__name__)

# הגדרת שלבי השיחה
GET_CODE, GET_FILENAME, GET_LANGUAGE = range(3)

# כפתורי המקלדת הראשית
MAIN_KEYBOARD = [["➕ הוסף קוד חדש"], ["📚 הצג את כל הקבצים שלי"]]

async def start_save_flow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Starts the conversation to save a new file."""
    await update.message.reply_text(
        "בסדר גמור! שלח לי עכשיו את פיסת הקוד שברצונך לשמור.\n"
        "כדי לבטל את התהליך בכל שלב, פשוט שלח /cancel.",
        reply_markup=ReplyKeyboardRemove(), # מסיר את המקלדת הראשית בזמן התהליך
    )
    return GET_CODE

async def get_code(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Saves the user's code and asks for a filename."""
    context.user_data['code_to_save'] = update.message.text
    await update.message.reply_text(
        "מעולה, הקוד נשמר זמנית. עכשיו, תן לי שם לקובץ (למשל, `my_script.py`)."
    )
    return GET_FILENAME

async def get_filename(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Saves the filename and asks for the programming language."""
    filename = update.message.text.strip()
    # בדיקה בסיסית של שם קובץ תקין
    if not re.match(r'^[\w\.\-]+\.[a-zA-Z0-9]+$', filename):
        await update.message.reply_text(
            "שם הקובץ נראה לא תקין. נסה שוב. הוא צריך להכיל אותיות, מספרים, ונקודה אחת לסיומת."
        )
        return GET_FILENAME # נשארים באותו שלב

    context.user_data['filename_to_save'] = filename
    await update.message.reply_text(
        "שם קובץ מצוין. באיזו שפת תכנות מדובר? (למשל, `python`, `javascript`, `html`)"
    )
    return GET_LANGUAGE

async def get_language_and_save(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Saves the language, saves everything to the database, and ends the conversation."""
    language = update.message.text.strip().lower()
    
    # שליפת המידע שנשמר
    code = context.user_data.get('code_to_save')
    filename = context.user_data.get('filename_to_save')
    user_id = update.message.from_user.id

    # גישה למסד הנתונים מהקונטקסט
    db: DatabaseManager = context.bot_data['db']

    try:
        db.save_file(user_id, filename, code, language)
        await update.message.reply_text(
            f"✅ הקובץ `{filename}` נשמר בהצלחה!",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
        )
    except Exception as e:
        logger.error(f"Failed to save file for user {user_id}: {e}")
        await update.message.reply_text(
            "❌ אופס, משהו השתבש. לא הצלחתי לשמור את הקובץ. נסה שוב מאוחר יותר.",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
        )

    # ניקוי המידע הזמני וסיום השיחה
    context.user_data.clear()
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancels and ends the conversation."""
    await update.message.reply_text(
        "התהליך בוטל. חוזרים לתפריט הראשי.",
        reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
    )
    context.user_data.clear()
    return ConversationHandler.END

def get_save_conversation_handler(db: DatabaseManager) -> ConversationHandler:
    """Creates and returns the ConversationHandler for saving files."""
    return ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^➕ הוסף קוד חדש$"), start_save_flow)],
        states={
            GET_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_code)],
            GET_FILENAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_filename)],
            GET_LANGUAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_language_and_save)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )