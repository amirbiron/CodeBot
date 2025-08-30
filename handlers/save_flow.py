import re
import logging
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler

from handlers.states import GET_CODE, GET_FILENAME, GET_NOTE
from services import code_service

logger = logging.getLogger(__name__)


async def start_save_flow(update, context: ContextTypes.DEFAULT_TYPE) -> int:
    cancel_markup = InlineKeyboardMarkup([[InlineKeyboardButton("❌ ביטול", callback_data="cancel")]])
    await update.message.reply_text(
        "✨ *מצוין!* בואו נצור קוד חדש!\n\n"
        "📝 שלח לי את קטע הקוד המבריק שלך.\n"
        "💡 אני אזהה את השפה אוטומטית ואארגן הכל!",
        reply_markup=cancel_markup,
        parse_mode='Markdown',
    )
    return GET_CODE


async def get_code(update, context: ContextTypes.DEFAULT_TYPE) -> int:
    code = update.message.text
    context.user_data['code_to_save'] = code
    lines = len(code.split('\n'))
    chars = len(code)
    words = len(code.split())
    await update.message.reply_text(
        f"✅ *קוד מתקדם התקבל בהצלחה!*\n\n"
        f"📊 **סטטיסטיקות מהירות:**\n"
        f"• 📏 שורות: {lines:,}\n"
        f"• 🔤 תווים: {chars:,}\n"
        f"• 📝 מילים: {words:,}\n\n"
        f"💭 עכשיו תן לי שם קובץ חכם (למשל: `my_amazing_script.py`)\n"
        f"🧠 השם יעזור לי לזהות את השפה ולארגן הכל מושלם!",
        parse_mode='Markdown',
    )
    return GET_FILENAME


async def get_filename(update, context: ContextTypes.DEFAULT_TYPE) -> int:
    filename = update.message.text.strip()
    user_id = update.message.from_user.id
    if not re.match(r'^[\w\.\-\_]+\.[a-zA-Z0-9]+$', filename):
        await update.message.reply_text(
            "🤔 השם נראה קצת מוזר...\n"
            "💡 נסה שם כמו: `script.py` או `index.html`\n"
            "✅ אותיות, מספרים, נקודות וקווים מותרים!"
        )
        return GET_FILENAME
    from database import db
    existing_file = db.get_latest_version(user_id, filename)
    if existing_file:
        keyboard = [
            [InlineKeyboardButton("🔄 החלף את הקובץ הקיים", callback_data=f"replace_{filename}")],
            [InlineKeyboardButton("✏️ שנה שם קובץ", callback_data="rename_file")],
            [InlineKeyboardButton("🚫 בטל ושמור במקום אחר", callback_data="cancel_save")],
        ]
        context.user_data['pending_filename'] = filename
        await update.message.reply_text(
            f"⚠️ *אופס!* הקובץ `{filename}` כבר קיים במערכת!\n\n"
            f"🤔 מה תרצה לעשות?",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown',
        )
        return GET_FILENAME
    context.user_data['pending_filename'] = filename
    await update.message.reply_text(
        "📝 רוצה להוסיף הערה קצרה לקובץ?\n"
        "כתוב/כתבי אותה עכשיו או שלח/י 'דלג' כדי לשמור בלי הערה."
    )
    return GET_NOTE


async def get_note(update, context: ContextTypes.DEFAULT_TYPE) -> int:
    note_text = (update.message.text or '').strip()
    if note_text.lower() in {"דלג", "skip", "ללא"}:
        context.user_data['note_to_save'] = ""
    else:
        context.user_data['note_to_save'] = note_text[:280]
    filename = context.user_data.get('pending_filename') or context.user_data.get('filename_to_save')
    user_id = update.message.from_user.id
    return await save_file_final(update, context, filename, user_id)


async def save_file_final(update, context, filename, user_id):
    context.user_data['filename_to_save'] = filename
    code = context.user_data.get('code_to_save')
    try:
        detected_language = code_service.detect_language(code, filename)
        from database import db, CodeSnippet
        note = (context.user_data.get('note_to_save') or '').strip()
        snippet = CodeSnippet(
            user_id=user_id,
            file_name=filename,
            code=code,
            programming_language=detected_language,
            description=note,
        )
        success = db.save_code_snippet(snippet)
        if success:
            keyboard = [
                [
                    InlineKeyboardButton("👁️ הצג קוד", callback_data=f"view_direct_{filename}"),
                    InlineKeyboardButton("✏️ ערוך", callback_data=f"edit_code_direct_{filename}"),
                ],
                [
                    InlineKeyboardButton("📝 שנה שם", callback_data=f"edit_name_direct_{filename}"),
                    InlineKeyboardButton("📚 היסטוריה", callback_data=f"versions_file_{filename}"),
                ],
                [
                    InlineKeyboardButton("📥 הורד", callback_data=f"download_direct_{filename}"),
                    InlineKeyboardButton("🗑️ מחק", callback_data=f"delete_direct_{filename}"),
                ],
                [
                    InlineKeyboardButton("📊 מידע מתקדם", callback_data=f"info_direct_{filename}"),
                    InlineKeyboardButton("🔙 לרשימה", callback_data="files"),
                ],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            note_display = note if note else '—'
            await update.message.reply_text(
                f"🎉 *קובץ נשמר בהצלחה!*\n\n"
                f"📄 **שם:** `{filename}`\n"
                f"🧠 **שפה זוהתה:** {detected_language}\n"
                f"📝 **הערה:** {note_display}\n\n"
                f"🎮 בחר פעולה מהכפתורים החכמים:",
                reply_markup=reply_markup,
                parse_mode='Markdown',
            )
        else:
            await update.message.reply_text(
                "💥 אופס! קרתה שגיאה טכנית.\n"
                "🔧 המערכת מתקדמת - ננסה שוב מאוחר יותר!",
                reply_markup=ReplyKeyboardMarkup([[]], resize_keyboard=True),
            )
    except Exception as e:
        logger.error(f"Failed to save file for user {user_id}: {e}")
        await update.message.reply_text(
            "🤖 המערכת החכמה שלנו נתקלה בבעיה זמנית.\n"
            "⚡ ננסה שוב בקרוב!",
            reply_markup=ReplyKeyboardMarkup([[]], resize_keyboard=True),
        )
    context.user_data.clear()
    return ConversationHandler.END

