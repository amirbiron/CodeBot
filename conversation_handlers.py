import logging
import re
import asyncio
from io import BytesIO
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup
import telegram.error
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)
from database import DatabaseManager
from activity_reporter import create_reporter

# הגדרת לוגר
logger = logging.getLogger(__name__)

# הגדרת שלבי השיחה - הסר את GET_LANGUAGE
GET_CODE, GET_FILENAME, EDIT_CODE, EDIT_NAME, EDIT_CONFIRM = range(5)

# כפתורי המקלדת הראשית
MAIN_KEYBOARD = [["➕ הוסף קוד חדש"], ["📚 הצג את כל הקבצים שלי"]]

reporter = create_reporter(
    mongodb_uri="mongodb+srv://mumin:M43M2TFgLfGvhBwY@muminai.tm6x81b.mongodb.net/?retryWrites=true&w=majority&appName=muminAI",
    service_id="srv-d29d72adbo4c73bcuep0",
    service_name="CodeBot"
)

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
    reporter.report_activity(update.effective_user.id)
    return ConversationHandler.END

async def show_all_files(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """מציג את כל הקבצים השמורים של המשתמש עם כפתורים אינטראקטיביים"""
    user_id = update.effective_user.id
    from database import db
    
    try:
        files = db.get_user_files(user_id)
        
        if not files:
            await update.message.reply_text(
                "📂 אין לך קבצים שמורים עדיין.\n"
                "לחץ על '➕ הוסף קוד חדש' כדי להתחיל!",
                reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
            )
        else:
            # יצירת כפתורים עבור כל קובץ
            keyboard = []
            
            for i, file in enumerate(files):
                file_name = file.get('file_name', 'קובץ ללא שם')
                language = file.get('programming_language', 'text')
                
                # שימוש באינדקס במקום file_id כדי לחסוך מקום
                # שמירת המידע ב-context לשימוש מאוחר יותר
                if 'files_cache' not in context.user_data:
                    context.user_data['files_cache'] = {}
                context.user_data['files_cache'][str(i)] = file
                
                # כפתור לכל קובץ עם אמוג'י לפי סוג הקובץ
                emoji = get_file_emoji(language)
                button_text = f"{emoji} {file_name}"
                
                # callback_data קצר יותר - רק האינדקס
                keyboard.append([InlineKeyboardButton(
                    button_text, 
                    callback_data=f"file_{i}"
                )])
                
                # הגבלה ל-10 קבצים בפעם אחת
                if i >= 9:
                    break
            
            # הוספת כפתור חזרה
            keyboard.append([InlineKeyboardButton("🔙 תפריט ראשי", callback_data="main")])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            files_count_text = f"({len(files)} קבצים)" if len(files) <= 10 else f"({len(files)} קבצים - מציג 10 ראשונים)"
            
            await update.message.reply_text(
                f"📚 *הקבצים השמורים שלך* {files_count_text}\n\n"
                "לחץ על קובץ כדי לראות אפשרויות:",
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            
    except Exception as e:
        logger.error(f"Failed to get files for user {user_id}: {e}")
        await update.message.reply_text(
            "❌ שגיאה בהצגת הקבצים. נסה שוב מאוחר יותר.",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )
    
    reporter.report_activity(update.effective_user.id)
    return ConversationHandler.END

def get_file_emoji(language: str) -> str:
    """מחזיר אמוג'י מתאים לסוג הקובץ"""
    emoji_map = {
        'python': '🐍',
        'javascript': '📜',
        'html': '🌐',
        'css': '🎨',
        'java': '☕',
        'cpp': '⚙️',
        'c': '🔧',
        'php': '🐘',
        'sql': '🗄️',
        'json': '📋',
        'yaml': '📝',
        'markdown': '📖',
        'bash': '💻',
        'text': '📄'
    }
    return emoji_map.get(language.lower(), '📄')

async def start_save_flow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Starts the conversation to save a new file."""
    await update.message.reply_text(
        "בסדר גמור! שלח לי עכשיו את פיסת הקוד שברצונך לשמור.\n"
        "כדי לבטל את התהליך בכל שלב, פשוט שלח /cancel.",
        reply_markup=ReplyKeyboardRemove(), # מסיר את המקלדת הראשית בזמן התהליך
    )
    reporter.report_activity(update.effective_user.id)
    return GET_CODE

async def get_code(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Saves the user's code and asks for a filename."""
    context.user_data['code_to_save'] = update.message.text
    await update.message.reply_text(
        "✅ הקוד נקלט בהצלחה! עכשיו תן לי שם לקובץ (למשל: `my_script.py`).\n\n"
        "💡 שם הקובץ יעזור לי לזהות את שפת התכנות אוטומטית!"
    )
    reporter.report_activity(update.effective_user.id)
    return GET_FILENAME

async def get_filename(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """שמירת שם הקובץ, בדיקת כפילויות וזיהוי אוטומטי של שפת התכנות"""
    filename = update.message.text.strip()
    user_id = update.message.from_user.id
    
    # בדיקה בסיסית של שם קובץ תקין
    if not re.match(r'^[\w\.\-]+\.[a-zA-Z0-9]+$', filename):
        await update.message.reply_text(
            "שם הקובץ נראה לא תקין. נסה שוב. הוא צריך להכיל אותיות, מספרים, ונקודה אחת לסיומת."
        )
        return GET_FILENAME # נשארים באותו שלב

    # בדיקת כפילות - האם הקובץ כבר קיים
    from database import db
    existing_file = db.get_latest_version(user_id, filename)
    
    if existing_file:
        await update.message.reply_text(
            f"⚠️ הקובץ `{filename}` כבר קיים!\n\n"
            "בחר פעולה:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 החלף את הקובץ הקיים", callback_data=f"replace_{filename}")],
                [InlineKeyboardButton("📝 שנה שם קובץ", callback_data="rename_file")],
                [InlineKeyboardButton("❌ בטל", callback_data="cancel_save")]
            ])
        )
        return GET_FILENAME  # נשאר באותו שלב לטיפול בתשובה

    # שמירת שם הקובץ
    context.user_data['filename_to_save'] = filename
    
    # זיהוי אוטומטי של השפה
    code = context.user_data.get('code_to_save')
    
    try:
        # ייבוא מעבד הקוד לזיהוי השפה
        from code_processor import code_processor
        detected_language = code_processor.detect_language(code, filename)
        
        # שמירה במסד הנתונים
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

async def handle_duplicate_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """טיפול בלחיצות על כפתורי כפילות"""
    query = update.callback_query
    await query.answer()
    
    try:
        if query.data.startswith("replace_"):
            filename = query.data.replace("replace_", "")
            context.user_data['filename_to_save'] = filename
            
            # החלפת הקובץ הקיים
            user_id = query.from_user.id
            code = context.user_data.get('code_to_save')
            
            from code_processor import code_processor
            from database import db
            
            detected_language = code_processor.detect_language(code, filename)
            db.save_file(user_id, filename, code, detected_language)
            
            await query.edit_message_text(
                f"✅ הקובץ `{filename}` הוחלף בהצלחה!\n"
                f"🔍 זוהתה שפת תכנות: **{detected_language}**",
                parse_mode='Markdown'
            )
            
            # חזרה לתפריט הראשי
            await query.message.reply_text(
                "בחר פעולה:",
                reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
            )
            
        elif query.data == "rename_file":
            await query.edit_message_text(
                "💭 הזן שם קובץ חדש:"
            )
            return GET_FILENAME  # חזרה לשלב קבלת שם קובץ
            
        elif query.data == "cancel_save":
            await query.edit_message_text(
                "❌ השמירה בוטלה."
            )
            await query.message.reply_text(
                "חוזרים לתפריט הראשי:",
                reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
            )
            
        context.user_data.clear()
        return ConversationHandler.END
        
    except telegram.error.BadRequest as e:
        if "Message is not modified" in str(e):
            pass  # התעלם מהשגיאה הזו
        else:
            raise
    reporter.report_activity(update.effective_user.id)
    return ConversationHandler.END

async def handle_file_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """מציג תפריט אפשרויות לקובץ ספציפי"""
    query = update.callback_query
    await query.answer()
    
    try:
        # קבלת האינדקס מה-callback_data
        file_index = query.data.split('_')[1]
        
        # קבלת המידע מה-cache
        files_cache = context.user_data.get('files_cache', {})
        file_data = files_cache.get(file_index)
        
        if not file_data:
            await query.edit_message_text("❌ שגיאה בזיהוי הקובץ")
            return ConversationHandler.END
        
        file_name = file_data.get('file_name', 'קובץ ללא שם')
        
        # יצירת כפתורי פעולה עם callback_data קצר
        keyboard = [
            [
                InlineKeyboardButton("👁️ הצג קוד", callback_data=f"view_{file_index}"),
                InlineKeyboardButton("📥 הורד", callback_data=f"dl_{file_index}")
            ],
            [
                InlineKeyboardButton("🗑️ מחק", callback_data=f"del_{file_index}"),
                InlineKeyboardButton("📊 מידע", callback_data=f"info_{file_index}")
            ],
            [InlineKeyboardButton("🔙 חזרה לרשימה", callback_data="files")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"📄 *{file_name}*\n\n"
            "בחר פעולה:",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        
    except Exception as e:
        logger.error(f"Error in handle_file_menu: {e}")
        await query.edit_message_text("❌ שגיאה בטעינת תפריט הקובץ")
    
    reporter.report_activity(update.effective_user.id)
    return ConversationHandler.END

async def handle_view_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """מציג את תוכן הקובץ עם אפשרויות עריכה"""
    query = update.callback_query
    await query.answer()
    
    try:
        file_index = query.data.split('_')[1]
        
        # קבלת המידע מה-cache
        files_cache = context.user_data.get('files_cache', {})
        file_data = files_cache.get(file_index)
        
        if not file_data:
            await query.edit_message_text("⚠️ הקובץ לא נמצא")
            return ConversationHandler.END
        
        file_name = file_data.get('file_name', 'קובץ')
        code = file_data.get('code', '')
        language = file_data.get('programming_language', 'text')
        version = file_data.get('version', 1)
        
        # חיתוך הקוד אם הוא ארוך מדי
        max_length = 3500
        if len(code) > max_length:
            code_preview = code[:max_length] + "\n\n... [קוד חתוך - השתמש בהורדה לקובץ המלא]"
        else:
            code_preview = code
        
        # כפתורים מורחבים עם עריכה
        keyboard = [
            [
                InlineKeyboardButton("✏️ ערוך קוד", callback_data=f"edit_code_{file_index}"),
                InlineKeyboardButton("📝 ערוך שם", callback_data=f"edit_name_{file_index}")
            ],
            [
                InlineKeyboardButton("📚 היסטוריה", callback_data=f"versions_{file_index}"),
                InlineKeyboardButton("📥 הורד", callback_data=f"dl_{file_index}")
            ],
            [InlineKeyboardButton("🔙 חזרה", callback_data=f"file_{file_index}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"📄 *{file_name}* ({language}) - גרסה {version}\n\n"
            f"```{language}\n{code_preview}\n```",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        
    except Exception as e:
        logger.error(f"Error in handle_view_file: {e}")
        await query.edit_message_text("❌ שגיאה בהצגת הקובץ")
    
    reporter.report_activity(update.effective_user.id)
    return ConversationHandler.END

async def handle_edit_code(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """התחלת עריכת קוד"""
    query = update.callback_query
    await query.answer()
    
    try:
        file_index = query.data.split('_')[2]  # edit_code_X
        
        files_cache = context.user_data.get('files_cache', {})
        file_data = files_cache.get(file_index)
        
        if not file_data:
            await query.edit_message_text("⚠️ הקובץ לא נמצא")
            return ConversationHandler.END
        
        file_name = file_data.get('file_name', 'קובץ')
        
        # שמירת המידע לעריכה
        context.user_data['editing_file'] = {
            'file_index': file_index,
            'file_data': file_data,
            'edit_type': 'code'
        }
        
        await query.edit_message_text(
            f"✏️ *עריכת קוד - {file_name}*\n\n"
            "שלח את הקוד החדש.\n"
            "לביטול שלח `/cancel`",
            parse_mode='Markdown'
        )
        
        return EDIT_CODE
        
    except Exception as e:
        logger.error(f"Error in handle_edit_code: {e}")
        await query.edit_message_text("❌ שגיאה בתחילת עריכה")
    
    return ConversationHandler.END

async def handle_edit_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """התחלת עריכת שם קובץ"""
    query = update.callback_query
    await query.answer()
    
    try:
        file_index = query.data.split('_')[2]  # edit_name_X
        
        files_cache = context.user_data.get('files_cache', {})
        file_data = files_cache.get(file_index)
        
        if not file_data:
            await query.edit_message_text("⚠️ הקובץ לא נמצא")
            return ConversationHandler.END
        
        current_name = file_data.get('file_name', 'קובץ')
        
        # שמירת המידע לעריכה
        context.user_data['editing_file'] = {
            'file_index': file_index,
            'file_data': file_data,
            'edit_type': 'name'
        }
        
        await query.edit_message_text(
            f"📝 *עריכת שם קובץ*\n\n"
            f"שם נוכחי: `{current_name}`\n\n"
            "שלח את השם החדש.\n"
            "לביטול שלח `/cancel`",
            parse_mode='Markdown'
        )
        
        return EDIT_NAME
        
    except Exception as e:
        logger.error(f"Error in handle_edit_name: {e}")
        await query.edit_message_text("❌ שגיאה בתחילת עריכה")
    
    return ConversationHandler.END

async def receive_new_code(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """קבלת קוד חדש לעריכה"""
    new_code = update.message.text
    editing_info = context.user_data.get('editing_file', {})
    file_data = editing_info.get('file_data', {})
    
    # תמיכה בשני מצבים: index-based ו-file name-based
    file_name = editing_info.get('file_name') or file_data.get('file_name', 'קובץ')
    old_code = file_data.get('code', '')
    user_id = update.effective_user.id
    
    try:
        # יצירת גרסה חדשה במסד הנתונים
        from file_manager import VersionManager
        from database import db
        
        version_manager = VersionManager()
        
        # זיהוי שפה מחדש
        from code_processor import code_processor
        detected_language = code_processor.detect_language(new_code, file_name)
        
        # שמירת הגרסה החדשה (זה ישמור גם את הגרסה הקודמת)
        success = db.save_file(user_id, file_name, new_code, detected_language)
        
        if success:
            # חישוב שינויים
            changes_summary = version_manager._generate_changes_summary(old_code, new_code)
            
            keyboard = [
                [InlineKeyboardButton("👁️ הצג גרסה חדשה", callback_data=f"view_updated_{file_name}")],
                [InlineKeyboardButton("📚 היסטוריית גרסאות", callback_data=f"versions_file_{file_name}")],
                [InlineKeyboardButton("🔙 לרשימת קבצים", callback_data="files")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                f"✅ *הקוד עודכן בהצלחה!*\n\n"
                f"📄 קובץ: `{file_name}`\n"
                f"🔍 שפה: {detected_language}\n"
                f"📊 שינויים: {changes_summary}\n\n"
                f"💾 הגרסה הקודמת נשמרה אוטומטית",
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(
                "❌ שגיאה בשמירת הקוד החדש. נסה שוב.",
                reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
            )
    
    except Exception as e:
        logger.error(f"Error updating code: {e}")
        await update.message.reply_text(
            "❌ שגיאה בעדכון הקוד.",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )
    
    # ניקוי
    context.user_data.clear()
    return ConversationHandler.END

async def receive_new_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """קבלת שם חדש לקובץ"""
    new_name = update.message.text.strip()
    editing_info = context.user_data.get('editing_file', {})
    file_data = editing_info.get('file_data', {})
    
    # תמיכה בשני מצבים: index-based ו-file name-based
    old_name = editing_info.get('file_name') or file_data.get('file_name', 'קובץ')
    user_id = update.effective_user.id
    
    # בדיקת תקינות שם
    if not re.match(r'^[\w\.\-]+\.[a-zA-Z0-9]+$', new_name):
        await update.message.reply_text(
            "❌ שם קובץ לא תקין. השתמש באותיות, מספרים ונקודה אחת לסיומת."
        )
        return EDIT_NAME
    
    try:
        from database import db
        
        # בדיקה אם השם החדש כבר קיים (למשתמש הזה)
        existing = db.get_latest_version(user_id, new_name)
        if existing and new_name != old_name:
            await update.message.reply_text(
                f"❌ קובץ בשם `{new_name}` כבר קיים.\n"
                "בחר שם אחר.",
                parse_mode='Markdown'
            )
            return EDIT_NAME
        
        # עדכון שם הקובץ במסד הנתונים
        # כאן צריך לעדכן את כל הגרסאות של הקובץ
        result = db.collection.update_many(
            {"user_id": user_id, "file_name": old_name, "is_active": True},
            {"$set": {"file_name": new_name, "updated_at": datetime.now()}}
        )
        
        if result.modified_count > 0:
            keyboard = [
                [InlineKeyboardButton("👁️ הצג קובץ", callback_data=f"view_updated_{new_name}")],
                [InlineKeyboardButton("🔙 לרשימת קבצים", callback_data="files")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                f"✅ *שם הקובץ עודכן בהצלחה!*\n\n"
                f"📄 שם ישן: `{old_name}`\n"
                f"📄 שם חדש: `{new_name}`\n\n"
                f"💾 כל הגרסאות עודכנו",
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text("❌ לא הצלחתי לעדכן את השם")
    
    except Exception as e:
        logger.error(f"Error updating file name: {e}")
        await update.message.reply_text("❌ שגיאה בעדכון השם")
    
    # ניקוי
    context.user_data.clear()
    return ConversationHandler.END

async def handle_versions_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """הצגת היסטוריית גרסאות"""
    query = update.callback_query
    await query.answer()
    
    try:
        if query.data.startswith("versions_"):
            file_index = query.data.split('_')[1]
            
            files_cache = context.user_data.get('files_cache', {})
            file_data = files_cache.get(file_index)
            
            if not file_data:
                await query.edit_message_text("⚠️ הקובץ לא נמצא")
                return ConversationHandler.END
                
            file_name = file_data.get('file_name', 'קובץ')
        
        elif query.data.startswith("versions_file_"):
            file_name = query.data.replace("versions_file_", "")
        
        else:
            await query.edit_message_text("❌ נתונים לא תקינים")
            return ConversationHandler.END
        
        user_id = query.from_user.id
        
        # קבלת כל הגרסאות
        from database import db
        versions = db.get_all_versions(user_id, file_name)
        
        if not versions:
            await query.edit_message_text(f"❌ לא נמצאו גרסאות עבור `{file_name}`")
            return ConversationHandler.END
        
        # יצירת רשימת גרסאות
        versions_text = f"📚 *היסטוריית גרסאות - {file_name}*\n\n"
        
        for i, version in enumerate(versions[:10]):  # מגביל ל-10 גרסאות אחרונות
            version_num = version.get('version', i+1)
            created_at = version.get('created_at', 'לא ידוע')
            
            if isinstance(created_at, str):
                date_str = created_at[:19]
            else:
                date_str = str(created_at)[:19] if created_at else 'לא ידוע'
            
            current_marker = " 🟢 *נוכחי*" if i == 0 else ""
            versions_text += f"📄 **גרסה {version_num}**{current_marker}\n"
            versions_text += f"🕐 {date_str}\n"
            
            if i < len(versions) - 1:
                versions_text += "➖➖➖\n"
        
        if len(versions) > 10:
            versions_text += f"\n... ועוד {len(versions) - 10} גרסאות ישנות"
        
        # כפתורים
        keyboard = [
            [InlineKeyboardButton("🔄 השווה גרסאות", callback_data=f"compare_{file_name}")],
            [InlineKeyboardButton("🔙 חזרה לקובץ", callback_data=f"view_updated_{file_name}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            versions_text,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        
    except Exception as e:
        logger.error(f"Error in handle_versions_history: {e}")
        await query.edit_message_text("❌ שגיאה בהצגת היסטוריה")
    
    return ConversationHandler.END

async def handle_view_updated_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """הצגת קובץ מעודכן לפי שם"""
    query = update.callback_query
    await query.answer()
    
    try:
        file_name = query.data.replace("view_updated_", "")
        user_id = query.from_user.id
        
        from database import db
        file_data = db.get_latest_version(user_id, file_name)
        
        if not file_data:
            await query.edit_message_text(f"⚠️ הקובץ {file_name} לא נמצא")
            return ConversationHandler.END
        
        code = file_data.get('code', '')
        language = file_data.get('programming_language', 'text')
        version = file_data.get('version', 1)
        
        # חיתוך הקוד אם הוא ארוך מדי
        max_length = 3500
        if len(code) > max_length:
            code_preview = code[:max_length] + "\n\n... [קוד חתוך - השתמש בהורדה לקובץ המלא]"
        else:
            code_preview = code
        
        # כפתורים
        keyboard = [
            [
                InlineKeyboardButton("✏️ ערוך קוד", callback_data=f"edit_code_file_{file_name}"),
                InlineKeyboardButton("📝 ערוך שם", callback_data=f"edit_name_file_{file_name}")
            ],
            [
                InlineKeyboardButton("📚 היסטוריה", callback_data=f"versions_file_{file_name}"),
                InlineKeyboardButton("📥 הורד", callback_data=f"dl_file_{file_name}")
            ],
            [InlineKeyboardButton("🔙 לרשימת קבצים", callback_data="files")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"📄 *{file_name}* ({language}) - גרסה {version}\n\n"
            f"```{language}\n{code_preview}\n```",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        
    except Exception as e:
        logger.error(f"Error in handle_view_updated_file: {e}")
        await query.edit_message_text("❌ שגיאה בהצגת הקובץ")
    
    return ConversationHandler.END

async def handle_compare_versions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """השוואת גרסאות (פונקציונליות בסיסית)"""
    query = update.callback_query
    await query.answer()
    
    try:
        file_name = query.data.replace("compare_", "")
        user_id = query.from_user.id
        
        from database import db
        versions = db.get_all_versions(user_id, file_name)
        
        if len(versions) < 2:
            await query.edit_message_text(
                f"❌ אין מספיק גרסאות להשוואה עבור {file_name}"
            )
            return ConversationHandler.END
        
        # השוואה בין שתי הגרסאות האחרונות
        latest = versions[0]
        previous = versions[1]
        
        latest_code = latest.get('code', '')
        previous_code = previous.get('code', '')
        
        # חישוב הבדלים בסיסי
        latest_lines = len(latest_code.split('\n'))
        previous_lines = len(previous_code.split('\n'))
        lines_diff = latest_lines - previous_lines
        
        chars_diff = len(latest_code) - len(previous_code)
        
        diff_text = f"📊 *השוואת גרסאות - {file_name}*\n\n"
        diff_text += f"🆕 גרסה {latest.get('version', 'N/A')} (נוכחית)\n"
        diff_text += f"🕐 {str(latest.get('created_at', ''))[:19]}\n\n"
        diff_text += f"📋 גרסה {previous.get('version', 'N/A')} (קודמת)\n"
        diff_text += f"🕐 {str(previous.get('created_at', ''))[:19]}\n\n"
        diff_text += f"📈 **הבדלים:**\n"
        diff_text += f"• שורות: {lines_diff:+d}\n"
        diff_text += f"• תווים: {chars_diff:+d}\n"
        
        keyboard = [
            [InlineKeyboardButton("🔙 חזרה להיסטוריה", callback_data=f"versions_file_{file_name}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            diff_text,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        
    except Exception as e:
        logger.error(f"Error in handle_compare_versions: {e}")
        await query.edit_message_text("❌ שגיאה בהשוואת גרסאות")
    
    return ConversationHandler.END

async def handle_edit_code_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """התחלת עריכת קוד לפי שם קובץ"""
    query = update.callback_query
    await query.answer()
    
    try:
        file_name = query.data.replace("edit_code_file_", "")
        user_id = query.from_user.id
        
        from database import db
        file_data = db.get_latest_version(user_id, file_name)
        
        if not file_data:
            await query.edit_message_text(f"⚠️ הקובץ {file_name} לא נמצא")
            return ConversationHandler.END
        
        # שמירת המידע לעריכה
        context.user_data['editing_file'] = {
            'file_name': file_name,
            'file_data': file_data,
            'edit_type': 'code'
        }
        
        await query.edit_message_text(
            f"✏️ *עריכת קוד - {file_name}*\n\n"
            "שלח את הקוד החדש.\n"
            "לביטול שלח `/cancel`",
            parse_mode='Markdown'
        )
        
        return EDIT_CODE
        
    except Exception as e:
        logger.error(f"Error in handle_edit_code_file: {e}")
        await query.edit_message_text("❌ שגיאה בתחילת עריכה")
    
    return ConversationHandler.END

async def handle_edit_name_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """התחלת עריכת שם קובץ לפי שם קובץ"""
    query = update.callback_query
    await query.answer()
    
    try:
        file_name = query.data.replace("edit_name_file_", "")
        user_id = query.from_user.id
        
        from database import db
        file_data = db.get_latest_version(user_id, file_name)
        
        if not file_data:
            await query.edit_message_text(f"⚠️ הקובץ {file_name} לא נמצא")
            return ConversationHandler.END
        
        # שמירת המידע לעריכה
        context.user_data['editing_file'] = {
            'file_name': file_name,
            'file_data': file_data,
            'edit_type': 'name'
        }
        
        await query.edit_message_text(
            f"📝 *עריכת שם קובץ*\n\n"
            f"שם נוכחי: `{file_name}`\n\n"
            "שלח את השם החדש.\n"
            "לביטול שלח `/cancel`",
            parse_mode='Markdown'
        )
        
        return EDIT_NAME
        
    except Exception as e:
        logger.error(f"Error in handle_edit_name_file: {e}")
        await query.edit_message_text("❌ שגיאה בתחילת עריכה")
    
    return ConversationHandler.END

async def handle_download_file_by_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """הורדת קובץ לפי שם"""
    query = update.callback_query
    await query.answer()
    
    try:
        file_name = query.data.replace("dl_file_", "")
        user_id = query.from_user.id
        
        from database import db
        file_data = db.get_latest_version(user_id, file_name)
        
        if not file_data:
            await query.edit_message_text(f"⚠️ הקובץ {file_name} לא נמצא")
            return ConversationHandler.END
        
        code_content = file_data.get('code', '')
        
        # יצירת קובץ בזיכרון
        file_in_memory = BytesIO(code_content.encode('utf-8'))
        
        # שליחת הקובץ
        await context.bot.send_document(
            chat_id=query.message.chat_id,
            document=file_in_memory,
            filename=file_name,
            caption=f"📥 הקובץ '{file_name}' מוכן להורדה!"
        )
        
        await query.answer("✅ הקובץ נשלח!")
        
    except Exception as e:
        logger.error(f"Error in handle_download_file_by_name: {e}")
        await query.answer("❌ שגיאה בהורדת הקובץ", show_alert=True)
    
    return ConversationHandler.END

async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """טיפול בכל הכפתורים האינטראקטיביים"""
    query = update.callback_query
    
    try:
        data = query.data
        
        if data.startswith("file_") and not data.startswith("files"):
            return await handle_file_menu(update, context)
        elif data.startswith("view_"):
            return await handle_view_file(update, context)
        elif data.startswith("edit_code_"):
            return await handle_edit_code(update, context)
        elif data.startswith("edit_name_"):
            return await handle_edit_name(update, context)
        elif data.startswith("versions_"):
            return await handle_versions_history(update, context)
        elif data.startswith("view_updated_"):
            return await handle_view_updated_file(update, context)
        elif data.startswith("compare_"):
            return await handle_compare_versions(update, context)
        elif data.startswith("edit_code_file_"):
            return await handle_edit_code_file(update, context)
        elif data.startswith("edit_name_file_"):
            return await handle_edit_name_file(update, context)
        elif data.startswith("dl_file_"):
            return await handle_download_file_by_name(update, context)
        elif data.startswith("dl_"):
            return await handle_download_file(update, context)
        elif data.startswith("del_"):
            return await handle_delete_confirmation(update, context)
        elif data.startswith("confirm_del_"):
            return await handle_delete_file(update, context)
        elif data.startswith("info_"):
            return await handle_file_info(update, context)
        elif data == "files":
            return await show_all_files_callback(update, context)
        elif data == "main":
            await query.edit_message_text("חוזר לתפריט הראשי:")
            await query.message.reply_text(
                "בחר פעולה:",
                reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
            )
        
    except telegram.error.BadRequest as e:
        if "Message is not modified" not in str(e):
            raise
    except Exception as e:
        logger.error(f"Error in handle_callback_query: {e}")
    
    reporter.report_activity(update.effective_user.id)
    return ConversationHandler.END

async def handle_download_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """הורדת קובץ"""
    query = update.callback_query
    await query.answer()
    
    try:
        file_index = query.data.split('_')[1]
        
        files_cache = context.user_data.get('files_cache', {})
        file_data = files_cache.get(file_index)
        
        if not file_data:
            await query.edit_message_text("⚠️ הקובץ לא נמצא")
            return ConversationHandler.END
        
        file_name = file_data.get('file_name', 'file.txt')
        code_content = file_data.get('code', '')
        
        # יצירת קובץ בזיכרון
        file_in_memory = BytesIO(code_content.encode('utf-8'))
        
        # שליחת הקובץ
        await context.bot.send_document(
            chat_id=query.message.chat_id,
            document=file_in_memory,
            filename=file_name,
            caption=f"📥 הקובץ '{file_name}' מוכן להורדה!"
        )
        
        await query.answer("✅ הקובץ נשלח!")
        
    except Exception as e:
        logger.error(f"Error in handle_download_file: {e}")
        await query.answer("❌ שגיאה בהורדת הקובץ", show_alert=True)
    
    reporter.report_activity(update.effective_user.id)
    return ConversationHandler.END

async def handle_delete_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """מציג אישור מחיקה"""
    query = update.callback_query
    await query.answer()
    
    try:
        file_index = query.data.split('_')[1]
        
        files_cache = context.user_data.get('files_cache', {})
        file_data = files_cache.get(file_index)
        
        if not file_data:
            await query.edit_message_text("⚠️ הקובץ לא נמצא")
            return ConversationHandler.END
        
        file_name = file_data.get('file_name', 'קובץ ללא שם')
        
        # כפתורי אישור
        keyboard = [
            [
                InlineKeyboardButton("🗑️ כן, מחק", callback_data=f"confirm_del_{file_index}"),
                InlineKeyboardButton("❌ לא, בטל", callback_data=f"file_{file_index}")
            ]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"⚠️ *אישור מחיקה*\n\n"
            f"האם אתה בטוח שברצונך למחוק את הקובץ:\n"
            f"📄 `{file_name}`\n\n"
            f"⚠️ פעולה זו לא ניתנת לביטול!",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        
    except Exception as e:
        logger.error(f"Error in handle_delete_confirmation: {e}")
        await query.edit_message_text("❌ שגיאה בהצגת אישור המחיקה")
    
    reporter.report_activity(update.effective_user.id)
    return ConversationHandler.END

async def handle_delete_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """מחיקת קובץ אחרי אישור"""
    query = update.callback_query
    await query.answer()
    
    try:
        file_index = query.data.split('_')[2]  # confirm_del_X
        
        files_cache = context.user_data.get('files_cache', {})
        file_data = files_cache.get(file_index)
        
        if not file_data:
            await query.edit_message_text("⚠️ הקובץ לא נמצא")
            return ConversationHandler.END
        
        file_name = file_data.get('file_name', 'קובץ ללא שם')
        user_id = query.from_user.id
        
        # מחיקה מהמסד
        from database import db
        success = db.delete_file(user_id, file_name)
        
        if success:
            # הסרה מהcache
            if file_index in context.user_data.get('files_cache', {}):
                del context.user_data['files_cache'][file_index]
            
            await query.edit_message_text(
                f"✅ הקובץ `{file_name}` נמחק בהצלחה!",
                parse_mode='Markdown'
            )
            
            # חזרה לרשימת הקבצים אחרי 2 שניות
            await asyncio.sleep(2)
            return await show_all_files_callback(update, context)
        else:
            await query.edit_message_text(f"❌ שגיאה במחיקת הקובץ `{file_name}`")
        
    except Exception as e:
        logger.error(f"Error in handle_delete_file: {e}")
        await query.edit_message_text("❌ שגיאה במחיקת הקובץ")
    
    reporter.report_activity(update.effective_user.id)
    return ConversationHandler.END

async def handle_file_info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """מציג מידע על הקובץ"""
    query = update.callback_query
    await query.answer()
    
    try:
        file_index = query.data.split('_')[1]
        
        files_cache = context.user_data.get('files_cache', {})
        file_data = files_cache.get(file_index)
        
        if not file_data:
            await query.edit_message_text("⚠️ הקובץ לא נמצא")
            return ConversationHandler.END
        
        file_name = file_data.get('file_name', 'קובץ ללא שם')
        language = file_data.get('programming_language', 'לא זוהתה')
        code = file_data.get('code', '')
        created_at = file_data.get('created_at', 'לא ידוע')
        updated_at = file_data.get('updated_at', 'לא ידוע')
        version = file_data.get('version', 1)
        
        # חישוב סטטיסטיקות
        lines = len(code.split('\n'))
        chars = len(code)
        words = len(code.split())
        
        # פורמט תאריכים
        if isinstance(created_at, str):
            created_str = created_at[:19] if len(created_at) > 19 else created_at
        else:
            created_str = str(created_at)[:19] if created_at else 'לא ידוע'
            
        if isinstance(updated_at, str):
            updated_str = updated_at[:19] if len(updated_at) > 19 else updated_at
        else:
            updated_str = str(updated_at)[:19] if updated_at else 'לא ידוע'
        
        # כפתור חזרה
        keyboard = [[InlineKeyboardButton("🔙 חזרה", callback_data=f"file_{file_index}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        info_text = (
            f"📊 *מידע על הקובץ*\n\n"
            f"📄 **שם קובץ:** `{file_name}`\n"
            f"🔍 **שפה:** {language}\n"
            f"📝 **גרסה:** {version}\n\n"
            f"📈 **סטטיסטיקות:**\n"
            f"• שורות: {lines:,}\n"
            f"• תווים: {chars:,}\n"
            f"• מילים: {words:,}\n\n"
            f"🕐 **נוצר:** {created_str}\n"
            f"🕐 **עודכן:** {updated_str}"
        )
        
        await query.edit_message_text(
            info_text,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        
    except Exception as e:
        logger.error(f"Error in handle_file_info: {e}")
        await query.edit_message_text("❌ שגיאה בהצגת מידע הקובץ")
    
    reporter.report_activity(update.effective_user.id)
    return ConversationHandler.END

async def show_all_files_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """גרסת callback של show_all_files"""
    query = update.callback_query
    if query:
        await query.answer()
    
    user_id = update.effective_user.id
    from database import db
    
    try:
        files = db.get_user_files(user_id)
        
        if not files:
            text = "📂 אין לך קבצים שמורים עדיין.\nלחץ על '➕ הוסף קוד חדש' כדי להתחיל!"
            keyboard = [[InlineKeyboardButton("🔙 תפריט ראשי", callback_data="main")]]
        else:
            # יצירת כפתורים עבור כל קובץ
            keyboard = []
            
            for i, file in enumerate(files):
                file_name = file.get('file_name', 'קובץ ללא שם')
                language = file.get('programming_language', 'text')
                
                # עדכון cache
                if 'files_cache' not in context.user_data:
                    context.user_data['files_cache'] = {}
                context.user_data['files_cache'][str(i)] = file
                
                emoji = get_file_emoji(language)
                button_text = f"{emoji} {file_name}"
                
                keyboard.append([InlineKeyboardButton(
                    button_text, 
                    callback_data=f"file_{i}"
                )])
                
                if i >= 9:
                    break
            
            keyboard.append([InlineKeyboardButton("🔙 תפריט ראשי", callback_data="main")])
            
            files_count_text = f"({len(files)} קבצים)" if len(files) <= 10 else f"({len(files)} קבצים - מציג 10 ראשונים)"
            text = f"📚 *הקבצים השמורים שלך* {files_count_text}\n\nלחץ על קובץ כדי לראות אפשרויות:"
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if query:
            await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
        else:
            # במקרה של קריאה רגילה (לא callback)
            await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')
            
    except Exception as e:
        logger.error(f"Failed to get files for user {user_id}: {e}")
        error_text = "❌ שגיאה בהצגת הקבצים. נסה שוב מאוחר יותר."
        
        if query:
            await query.edit_message_text(error_text)
        else:
            await update.message.reply_text(error_text)
    
    reporter.report_activity(update.effective_user.id)
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancels and ends the conversation."""
    await update.message.reply_text(
        "התהליך בוטל. חוזרים לתפריט הראשי.",
        reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
    )
    context.user_data.clear()
    reporter.report_activity(update.effective_user.id)
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
            GET_FILENAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_filename),
                CallbackQueryHandler(handle_duplicate_callback)
            ],
            EDIT_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_new_code)],
            EDIT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_new_name)],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            CallbackQueryHandler(handle_callback_query)  # הוסף את זה!
        ],
        # הוסף allow_reentry=True כדי לאפשר חזרה לשיחה
        allow_reentry=True,
        per_message=False
    )