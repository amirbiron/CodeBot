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

# הגדרת שלבי השיחה - הסר את GET_LANGUAGE
GET_CODE, GET_FILENAME = range(2)

# כפתורי המקלדת הראשית
MAIN_KEYBOARD = [["➕ הוסף קוד חדש"], ["📚 הצג את כל הקבצים שלי"]]

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """טיפול בפקודת /start - מציג את התפריט הראשי"""
    user_name = update.effective_user.first_name
    welcome_text = (
        f"🤖 שלום {user_name}! ברוך הבא לבוט שומר הקוד!\n\n"
        "🔹 שמור קטעי קוד בקלות\n"
        "🔹 חפש והצג את הקבצים שלך\n"
        "🔹 נהל את הקודים שלך במקום אחד\n\n"
        "בחר פעולה מהכפתורים למטה:"
    )
    
    keyboard = ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
    await update.message.reply_text(welcome_text, reply_markup=keyboard)
    return ConversationHandler.END

async def show_all_files(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """מציג את כל הקבצים השמורים של המשתמש"""
    user_id = update.effective_user.id
    db: DatabaseManager = context.bot_data['db']
    
    try:
        files = db.get_user_files(user_id)
        
        if not files:
            await update.message.reply_text(
                "📂 אין לך קבצים שמורים עדיין.\n"
                "לחץ על '➕ הוסף קוד חדש' כדי להתחיל!",
                reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
            )
        else:
            files_list = "\n".join([f"📄 {file['filename']}" for file in files])
            await update.message.reply_text(
                f"📚 הקבצים השמורים שלך ({len(files)} קבצים):\n\n{files_list}",
                reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
            )
            
    except Exception as e:
        logger.error(f"Failed to get files for user {user_id}: {e}")
        await update.message.reply_text(
            "❌ שגיאה בהצגת הקבצים. נסה שוב מאוחר יותר.",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )
    
    return ConversationHandler.END

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
    """שמירת שם הקובץ וזיהוי אוטומטי של שפת התכנות"""
    filename = update.message.text.strip()
    
    # בדיקה בסיסית של שם קובץ תקין
    if not re.match(r'^[\w\.\-]+\.[a-zA-Z0-9]+$', filename):
        await update.message.reply_text(
            "שם הקובץ נראה לא תקין. נסה שוב. הוא צריך להכיל אותיות, מספרים, ונקודה אחת לסיומת."
        )
        return GET_FILENAME # נשארים באותו שלב

    # שמירת שם הקובץ
    context.user_data['filename_to_save'] = filename
    
    # זיהוי אוטומטי של השפה
    code = context.user_data.get('code_to_save')
    
    # ייבוא מעבד הקוד לזיהוי השפה
    from code_processor import code_processor
    detected_language = code_processor.detect_language(code, filename)
    
    # שמירה ישירה במסד הנתונים
    user_id = update.message.from_user.id
    db: DatabaseManager = context.bot_data['db']

    try:
        db.save_file(user_id, filename, code, detected_language)
        await update.message.reply_text(
            f"✅ הקובץ `{filename}` נשמר בהצלחה!\n"
            f"🔍 זוהתה שפת תכנות: **{detected_language}**",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
            parse_mode='Markdown'
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
        entry_points=[
            CommandHandler("start", start_command),
            MessageHandler(filters.Regex("^➕ הוסף קוד חדש$"), start_save_flow),
            MessageHandler(filters.Regex("^📚 הצג את כל הקבצים שלי$"), show_all_files),
        ],
        states={
            GET_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_code)],
            GET_FILENAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_filename)],
            # הסרנו את GET_LANGUAGE כי הזיהוי אוטומטי
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )