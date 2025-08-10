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
from utils import get_language_emoji as get_file_emoji
from user_stats import user_stats

# הגדרת לוגר
logger = logging.getLogger(__name__)

# הגדרת שלבי השיחה
GET_CODE, GET_FILENAME, EDIT_CODE, EDIT_NAME = range(4)

# כפתורי המקלדת הראשית
MAIN_KEYBOARD = [["➕ הוסף קוד חדש"], ["📚 הצג את כל הקבצים שלי"], ["📂 קבצים גדולים"], ["🔧 GitHub"]]

reporter = create_reporter(
    mongodb_uri="mongodb+srv://mumin:M43M2TFgLfGvhBwY@muminai.tm6x81b.mongodb.net/?retryWrites=true&w=majority&appName=muminAI",
    service_id="srv-d29d72adbo4c73bcuep0",
    service_name="CodeBot"
)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """טיפול בפקודת /start - מציג את התפריט הראשי"""
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name
    username = update.effective_user.username
    
    # שמור משתמש במסד נתונים (INSERT OR IGNORE)
    from database import db
    db.save_user(user_id, username)
    # רישום פעילות למעקב סטטיסטיקות ב-MongoDB
    user_stats.log_user(user_id, username)
    
    welcome_text = (
        f"🤖 שלום {user_name}! ברוך הבא לבוט שומר הקוד המתקדם!\n\n"
        "🔹 שמור ונהל קטעי קוד בחכמה\n"
        "🔹 עריכה מתקדמת עם גרסאות (בפיתוח)\n"
        "🔹 חיפוש והצגה חכמה\n"
        "🔹 הורדה וניהול מלא\n"
        "🔹 העלאת קבצים ל-GitHub\n\n"
        "בחר פעולה מהתפריט למטה 👇\n\n"
        "🔧 לכל תקלה בבוט נא לשלוח הודעה ל-@moominAmir"
    )
    
    keyboard = ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
    await update.message.reply_text(welcome_text, reply_markup=keyboard)
    reporter.report_activity(user_id)
    return ConversationHandler.END

async def show_all_files(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """מציג את כל הקבצים השמורים עם ממשק אינטראקטיבי מתקדם"""
    user_id = update.effective_user.id
    # רישום פעילות למעקב סטטיסטיקות ב-MongoDB
    user_stats.log_user(user_id, update.effective_user.username)
    from database import db
    
    try:
        files = db.get_user_files(user_id)
        
        if not files:
            await update.message.reply_text(
                "📂 אין לך קבצים שמורים עדיין.\n"
                "✨ לחץ על '➕ הוסף קוד חדש' כדי להתחיל יצירה!",
                reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
            )
        else:
            # יצירת כפתורים מתקדמים עבור כל קובץ
            keyboard = []
            
            for i, file in enumerate(files):
                file_name = file.get('file_name', 'קובץ ללא שם')
                language = file.get('programming_language', 'text')
                
                # שמירת המידע ב-context למידע מהיר
                if 'files_cache' not in context.user_data:
                    context.user_data['files_cache'] = {}
                context.user_data['files_cache'][str(i)] = file
                
                # כפתור מעוצב עם אמוג'י חכם
                emoji = get_file_emoji(language)
                button_text = f"{emoji} {file_name}"
                
                keyboard.append([InlineKeyboardButton(
                    button_text, 
                    callback_data=f"file_{i}"
                )])
                
                if i >= 9:  # הגבלה אסתטית
                    break
            
            # כפתורי ניווט מתקדמים
            nav_buttons = [
                [InlineKeyboardButton("🔄 רענן רשימה", callback_data="refresh_files")],
                [InlineKeyboardButton("🏠 תפריט ראשי", callback_data="main")]
            ]
            keyboard.extend(nav_buttons)
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            files_count_text = f"({len(files)} קבצים)" if len(files) <= 10 else f"({len(files)} קבצים - מציג 10 הטובים ביותר)"
            
            await update.message.reply_text(
                f"📚 *המרכז הדיגיטלי שלך* {files_count_text}\n\n"
                "✨ לחץ על קובץ לחוויה מלאה של עריכה וניהול:",
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            
    except Exception as e:
        logger.error(f"Failed to get files for user {user_id}: {e}")
        await update.message.reply_text(
            "❌ שגיאה זמנית בטעינת הקבצים. הטכנולוגיה מתקדמת - ננסה שוב!",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )
    
    reporter.report_activity(user_id)
    return ConversationHandler.END

async def show_large_files_direct(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """הצגת קבצים גדולים ישירות מהתפריט הראשי"""
    # רישום פעילות למעקב סטטיסטיקות ב-MongoDB
    user_stats.log_user(update.effective_user.id, update.effective_user.username)
    from large_files_handler import large_files_handler
    await large_files_handler.show_large_files_menu(update, context)
    reporter.report_activity(update.effective_user.id)
    return ConversationHandler.END

async def show_github_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """הצגת תפריט GitHub"""
    # שימוש ב-instance הגלובלי במקום ליצור חדש
    if 'github_handler' not in context.bot_data:
        from github_menu_handler import GitHubMenuHandler
        context.bot_data['github_handler'] = GitHubMenuHandler()
    
    # רישום פעילות למעקב סטטיסטיקות ב-MongoDB
    user_stats.log_user(update.effective_user.id, update.effective_user.username)
    
    github_handler = context.bot_data['github_handler']
    await github_handler.github_menu_command(update, context)
    reporter.report_activity(update.effective_user.id)
    return ConversationHandler.END

async def show_all_files_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """גרסת callback של show_all_files - מציגה תפריט בחירה בין סוגי קבצים"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    from database import db
    
    try:
        # קבלת מידע על קבצים
        regular_files = db.get_user_files(user_id)
        large_files, large_count = db.get_user_large_files(user_id, page=1, per_page=100)
        
        # יצירת תפריט בחירה
        keyboard = []
        
        if regular_files:
            keyboard.append([InlineKeyboardButton(
                f"📁 קבצים רגילים ({len(regular_files)})",
                callback_data="show_regular_files"
            )])
        
        if large_files:
            keyboard.append([InlineKeyboardButton(
                f"📚 קבצים גדולים ({large_count})",
                callback_data="show_large_files"
            )])
        
        if not regular_files and not large_files:
            await query.edit_message_text(
                "📂 אין לך קבצים שמורים עדיין.\n"
                "✨ שלח קובץ או השתמש ב-'➕ הוסף קוד חדש' כדי להתחיל!"
            )
            # Add main menu keyboard
            keyboard = [
                [InlineKeyboardButton("🏠 תפריט ראשי", callback_data="main")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.message.reply_text(
                "🎮 בחר פעולה:",
                reply_markup=reply_markup
            )
        else:
            # הוספת כפתור תפריט ראשי
            keyboard.append([InlineKeyboardButton("🏠 תפריט ראשי", callback_data="main")])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            total_files = len(regular_files) + large_count
            
            text = (
                f"📚 **הקבצים שלך** (סה\"כ: {total_files})\n\n"
                "🎯 בחר קטגוריה:"
            )
            
            await query.edit_message_text(
                text,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
        
        reporter.report_activity(user_id)
        
    except Exception as e:
        logger.error(f"Error in show_all_files_callback: {e}")
        await query.edit_message_text("❌ שגיאה בטעינת הקבצים")
    
    return ConversationHandler.END

async def show_regular_files_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """הצגת קבצים רגילים בלבד"""
    query = update.callback_query
    await query.answer()
    
    # Instead of creating a fake update, adapt show_all_files logic for callback queries
    user_id = update.effective_user.id
    from database import db
    
    try:
        files = db.get_user_files(user_id)
        
        if not files:
            await query.edit_message_text(
                "📂 אין לך קבצים שמורים עדיין.\n"
                "✨ לחץ על '➕ הוסף קוד חדש' כדי להתחיל יצירה!"
            )
            # Add main menu keyboard
            keyboard = [
                [InlineKeyboardButton("🏠 תפריט ראשי", callback_data="main")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.message.reply_text(
                "🎮 בחר פעולה:",
                reply_markup=reply_markup
            )
        else:
            # יצירת כפתורים מתקדמים עבור כל קובץ
            keyboard = []
            
            for i, file in enumerate(files):
                file_name = file.get('file_name', 'קובץ ללא שם')
                language = file.get('programming_language', 'text')
                
                # שמירת המידע ב-context למידע מהיר
                if 'files_cache' not in context.user_data:
                    context.user_data['files_cache'] = {}
                context.user_data['files_cache'][str(i)] = file
                
                # כפתור מעוצב עם אמוג'י חכם
                emoji = get_file_emoji(language)
                button_text = f"{emoji} {file_name}"
                
                keyboard.append([InlineKeyboardButton(
                    button_text, 
                    callback_data=f"file_{i}"
                )])
                
                if i >= 9:  # הגבלה אסתטית
                    break
            
            # כפתורי ניווט מתקדמים
            nav_buttons = [
                [InlineKeyboardButton("🔄 רענן רשימה", callback_data="refresh_files")],
                [InlineKeyboardButton("🏠 תפריט ראשי", callback_data="main")]
            ]
            keyboard.extend(nav_buttons)
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            files_count_text = f"({len(files)} קבצים)" if len(files) <= 10 else f"({len(files)} קבצים - מציג 10 הטובים ביותר)"
            
            header_text = (
                f"📚 **הקבצים השמורים שלך** {files_count_text}\n\n"
                "✨ לחץ על קובץ לחוויה מלאה של עריכה וניהול:"
            )
            
            await query.edit_message_text(
                header_text,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            
        reporter.report_activity(user_id)
        
    except Exception as e:
        logger.error(f"Error in show_regular_files_callback: {e}")
        await query.edit_message_text("❌ שגיאה בטעינת הקבצים")
    
    return ConversationHandler.END

async def start_save_flow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """התחלת תהליך שמירה מתקדם"""
    await update.message.reply_text(
        "✨ *מצוין!* בואו נצור קוד חדש!\n\n"
        "📝 שלח לי את קטע הקוד המבריק שלך.\n"
        "💡 אני אזהה את השפה אוטומטית ואארגן הכל!\n\n"
        "🚫 לביטול בכל שלב: `/cancel`",
        reply_markup=ReplyKeyboardRemove(),
        parse_mode='Markdown'
    )
    reporter.report_activity(update.effective_user.id)
    return GET_CODE

async def get_code(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """קבלת הקוד עם אנליזה מתקדמת"""
    code = update.message.text
    context.user_data['code_to_save'] = code
    
    # אנליזה מהירה של הקוד
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
        parse_mode='Markdown'
    )
    return GET_FILENAME

async def get_filename(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """שמירת שם הקובץ עם בדיקות מתקדמות"""
    filename = update.message.text.strip()
    user_id = update.message.from_user.id
    
    # בדיקה מתקדמת של שם קובץ
    if not re.match(r'^[\w\.\-\_]+\.[a-zA-Z0-9]+$', filename):
        await update.message.reply_text(
            "🤔 השם נראה קצת מוזר...\n"
            "💡 נסה שם כמו: `script.py` או `index.html`\n"
            "✅ אותיות, מספרים, נקודות וקווים מותרים!"
        )
        return GET_FILENAME

    # בדיקת כפילות מתקדמת
    from database import db
    existing_file = db.get_latest_version(user_id, filename)
    
    if existing_file:
        keyboard = [
            [InlineKeyboardButton("🔄 החלף את הקובץ הקיים", callback_data=f"replace_{filename}")],
            [InlineKeyboardButton("✏️ שנה שם קובץ", callback_data="rename_file")],
            [InlineKeyboardButton("🚫 בטל ושמור במקום אחר", callback_data="cancel_save")]
        ]
        
        context.user_data['pending_filename'] = filename
        
        await update.message.reply_text(
            f"⚠️ *אופס!* הקובץ `{filename}` כבר קיים במערכת!\n\n"
            f"🤔 מה תרצה לעשות?",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
        return GET_FILENAME

    # שמירה מתקדמת
    return await save_file_final(update, context, filename, user_id)

async def save_file_final(update, context, filename, user_id):
    """שמירה סופית של הקובץ"""
    context.user_data['filename_to_save'] = filename
    code = context.user_data.get('code_to_save')
    
    try:
        # זיהוי שפה חכם
        from code_processor import code_processor
        detected_language = code_processor.detect_language(code, filename)
        
        # שמירה במסד נתונים
        from database import db
        success = db.save_file(user_id, filename, code, detected_language)
        
        if success:
            # כפתורים מתקדמים למיד אחרי שמירה
            keyboard = [
                [
                    InlineKeyboardButton("👁️ הצג קוד", callback_data=f"view_direct_{filename}"),
                    InlineKeyboardButton("✏️ ערוך", callback_data=f"edit_code_direct_{filename}")
                ],
                [
                    InlineKeyboardButton("📝 שנה שם", callback_data=f"edit_name_direct_{filename}"),
                    InlineKeyboardButton("📚 היסטוריה", callback_data=f"versions_file_{filename}")
                ],
                [
                    InlineKeyboardButton("📥 הורד", callback_data=f"download_direct_{filename}"),
                    InlineKeyboardButton("🗑️ מחק", callback_data=f"delete_direct_{filename}")
                ],
                [
                    InlineKeyboardButton("📊 מידע מתקדם", callback_data=f"info_direct_{filename}"),
                    InlineKeyboardButton("🔙 לרשימה", callback_data="files")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                f"🎉 *קובץ נשמר בהצלחה מרשימה!*\n\n"
                f"📄 **שם:** `{filename}`\n"
                f"🧠 **שפה זוהתה:** {detected_language}\n"
                f"⚡ **מוכן לעבודה מתקדמת!**\n\n"
                f"🎮 בחר פעולה מהכפתורים החכמים:",
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(
                "💥 אופס! קרתה שגיאה טכנית.\n"
                "🔧 המערכת מתקדמת - ננסה שוב מאוחר יותר!",
                reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
            )
        
    except Exception as e:
        logger.error(f"Failed to save file for user {user_id}: {e}")
        await update.message.reply_text(
            "🤖 המערכת החכמה שלנו נתקלה בבעיה זמנית.\n"
            "⚡ ננסה שוב בקרוב!",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )

    context.user_data.clear()
    return ConversationHandler.END

async def handle_duplicate_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """טיפול בכפתורי הכפילות"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    if data.startswith("replace_"):
        filename = data.replace("replace_", "")
        user_id = update.effective_user.id
        return await save_file_final(query, context, filename, user_id)
    elif data == "rename_file":
        await query.edit_message_text(
            "✏️ *שנה שם קובץ*\n\n"
            "📝 שלח שם קובץ חדש:",
            parse_mode='Markdown'
        )
        return GET_FILENAME
    elif data == "cancel_save":
        context.user_data.clear()
        await query.edit_message_text("🚫 השמירה בוטלה!")
        await query.message.reply_text(
            "🏠 חוזרים לתפריט הראשי:",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )
        return ConversationHandler.END
    
    return GET_FILENAME

async def handle_file_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """תפריט קובץ מתקדם עם אפשרויות רבות"""
    query = update.callback_query
    await query.answer()
    
    try:
        file_index = query.data.split('_')[1]
        files_cache = context.user_data.get('files_cache', {})
        file_data = files_cache.get(file_index)
        
        if not file_data:
            await query.edit_message_text("❌ שגיאה בזיהוי הקובץ החכם")
            return ConversationHandler.END
        
        file_name = file_data.get('file_name', 'קובץ מיסתורי')
        language = file_data.get('programming_language', 'לא ידועה')
        
        # כפתורים מתקדמים מלאים
        keyboard = [
            [
                InlineKeyboardButton("👁️ הצג קוד", callback_data=f"view_{file_index}"),
                InlineKeyboardButton("✏️ ערוך", callback_data=f"edit_code_{file_index}")
            ],
            [
                InlineKeyboardButton("📝 שנה שם", callback_data=f"edit_name_{file_index}"),
                InlineKeyboardButton("📚 היסטוריה", callback_data=f"versions_{file_index}")
            ],
            [
                InlineKeyboardButton("📥 הורד", callback_data=f"dl_{file_index}"),
                InlineKeyboardButton("📊 מידע", callback_data=f"info_{file_index}")
            ],
            [
                InlineKeyboardButton("🔄 שכפול", callback_data=f"clone_{file_index}"),
                InlineKeyboardButton("🗑️ מחק", callback_data=f"del_{file_index}")
            ],
            [InlineKeyboardButton("🔙 חזרה לרשימה", callback_data="files")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"🎯 *מרכז בקרה מתקדם*\n\n"
            f"📄 **קובץ:** `{file_name}`\n"
            f"🧠 **שפה:** {language}\n\n"
            f"🎮 בחר פעולה מתקדמת:",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        
    except Exception as e:
        logger.error(f"Error in handle_file_menu: {e}")
        await query.edit_message_text("💥 שגיאה במרכז הבקרה המתקדם")
    
    return ConversationHandler.END

async def handle_view_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """הצגת קוד עם אפשרויות מתקדמות"""
    query = update.callback_query
    await query.answer()
    
    try:
        file_index = query.data.split('_')[1]
        files_cache = context.user_data.get('files_cache', {})
        file_data = files_cache.get(file_index)
        
        if not file_data:
            await query.edit_message_text("⚠️ הקובץ נעלם מהמערכת החכמה")
            return ConversationHandler.END
        
        file_name = file_data.get('file_name', 'קובץ')
        code = file_data.get('code', '')
        language = file_data.get('programming_language', 'text')
        version = file_data.get('version', 1)
        
        # חיתוך חכם של הקוד
        max_length = 3500
        if len(code) > max_length:
            code_preview = code[:max_length] + "\n\n... [📱 הצג המשך - השתמש בהורדה לקובץ המלא]"
        else:
            code_preview = code
        
        # כפתורים מתקדמים לעריכה
        keyboard = [
            [
                InlineKeyboardButton("✏️ ערוך קוד", callback_data=f"edit_code_{file_index}"),
                InlineKeyboardButton("📝 ערוך שם", callback_data=f"edit_name_{file_index}")
            ],
            [
                InlineKeyboardButton("📚 היסטוריה", callback_data=f"versions_{file_index}"),
                InlineKeyboardButton("📥 הורד", callback_data=f"dl_{file_index}")
            ],
            [
                InlineKeyboardButton("🔄 שכפול", callback_data=f"clone_{file_index}"),
                InlineKeyboardButton("📊 מידע מלא", callback_data=f"info_{file_index}")
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
        await query.edit_message_text("❌ שגיאה בהצגת הקוד המתקדם")
    
    return ConversationHandler.END

async def handle_edit_code(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """התחלת עריכת קוד"""
    query = update.callback_query
    await query.answer()
    
    try:
        file_index = query.data.split('_')[2]
        files_cache = context.user_data.get('files_cache', {})
        file_data = files_cache.get(file_index)
        
        if not file_data:
            await query.edit_message_text("❌ שגיאה בזיהוי הקובץ")
            return ConversationHandler.END
        
        context.user_data['editing_file_index'] = file_index
        context.user_data['editing_file_data'] = file_data
        
        file_name = file_data.get('file_name', 'קובץ')
        
        await query.edit_message_text(
            f"✏️ *עריכת קוד מתקדמת*\n\n"
            f"📄 **קובץ:** `{file_name}`\n\n"
            f"📝 שלח את הקוד החדש והמעודכן:\n"
            f"🚫 לביטול: `/cancel`",
            parse_mode='Markdown'
        )
        
        return EDIT_CODE
        
    except Exception as e:
        # לוגים מפורטים לשגיאות עריכה
        logger.error(f"Error in handle_edit_code: {e}")
        logger.error(f"User ID: {update.effective_user.id}")
        logger.error(f"Query data: {query.data if query else 'No query'}")
        
        # רישום בלוגר הייעודי
        try:
            from code_processor import code_processor
            code_processor.code_logger.error(f"שגיאה בהתחלת עריכת קוד עבור משתמש {update.effective_user.id}: {str(e)}")
        except:
            pass
        
        await query.edit_message_text(
            "❌ שגיאה בהתחלת עריכה\n\n"
            "🔄 אנא נסה שוב או חזור לתפריט הראשי\n"
            "📞 אם הבעיה נמשכת, פנה לתמיכה"
        )
    
    return ConversationHandler.END

async def receive_new_code(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """קבלת הקוד החדש לעריכה"""
    new_code = update.message.text
    
    # בדיקה אם מדובר בעריכת קובץ גדול
    editing_large_file = context.user_data.get('editing_large_file')
    if editing_large_file:
        try:
            user_id = update.effective_user.id
            file_name = editing_large_file['file_name']
            file_data = editing_large_file['file_data']
            
            from utils import detect_language_from_filename
            language = detect_language_from_filename(file_name)
            
            # יצירת קובץ גדול חדש עם התוכן המעודכן
            from database import LargeFile
            updated_file = LargeFile(
                user_id=user_id,
                file_name=file_name,
                content=new_code,
                programming_language=language,
                file_size=len(new_code.encode('utf-8')),
                lines_count=len(new_code.split('\n'))
            )
            
            from database import db
            success = db.save_large_file(updated_file)
            
            if success:
                from utils import get_language_emoji
                emoji = get_language_emoji(language)
                
                keyboard = [[InlineKeyboardButton("📚 חזרה לקבצים גדולים", callback_data="show_large_files")]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                lines_count = len(new_code.split('\n'))
                await update.message.reply_text(
                    f"✅ **הקובץ הגדול עודכן בהצלחה!**\n\n"
                    f"📄 **קובץ:** `{file_name}`\n"
                    f"{emoji} **שפה:** {language}\n"
                    f"💾 **גודל חדש:** {len(new_code):,} תווים\n"
                    f"📏 **שורות:** {lines_count:,}",
                    reply_markup=reply_markup,
                    parse_mode='Markdown'
                )
                
                # ניקוי נתוני העריכה
                context.user_data.pop('editing_large_file', None)
            else:
                await update.message.reply_text("❌ שגיאה בעדכון הקובץ הגדול")
            
            return ConversationHandler.END
            
        except Exception as e:
            logger.error(f"Error updating large file: {e}")
            await update.message.reply_text("❌ שגיאה בעדכון הקובץ")
            return ConversationHandler.END
    
    # המשך הטיפול הרגיל בקבצים רגילים
    file_data = context.user_data.get('editing_file_data')
    
    if not file_data:
        await update.message.reply_text("❌ שגיאה בנתוני הקובץ")
        return ConversationHandler.END
    
    try:
        user_id = update.effective_user.id
        # תמיכה במקרים ישירים ומקרי cache
        file_name = context.user_data.get('editing_file_name') or file_data.get('file_name')
        editing_file_index = context.user_data.get('editing_file_index')
        files_cache = context.user_data.get('files_cache')
        
        from code_processor import code_processor
        
        # אימות וסניטציה של הקוד הנכנס
        is_valid, cleaned_code, error_message = code_processor.validate_code_input(new_code, file_name, user_id)
        
        if not is_valid:
            await update.message.reply_text(
                f"❌ שגיאה בקלט הקוד:\n{error_message}\n\n"
                f"💡 אנא וודא שהקוד תקין ונסה שוב.\n"
                f"🚫 לביטול: `/cancel`",
                reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
            )
            return EDIT_CODE  # חזרה למצב עריכה
        
        # זיהוי שפה עם הקוד המנוקה
        detected_language = code_processor.detect_language(cleaned_code, file_name)
        
        from database import db
        success = db.save_file(user_id, file_name, cleaned_code, detected_language)
        
        if success:
            keyboard = [
                [
                    InlineKeyboardButton("👁️ הצג קוד מעודכן", callback_data=f"view_direct_{file_name}"),
                    InlineKeyboardButton("📚 היסטוריה", callback_data=f"versions_file_{file_name}")
                ],
                [
                    InlineKeyboardButton("📥 הורד", callback_data=f"download_direct_{file_name}"),
                    InlineKeyboardButton("🔙 לרשימה", callback_data="files")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            # Get the new version number to display
            from database import db
            updated_file = db.get_latest_version(user_id, file_name)
            version_num = updated_file.get('version', 1) if updated_file else 1
            
            # רענון קאש של הקבצים אם קיים אינדקס רלוונטי
            try:
                if files_cache is not None and editing_file_index is not None and str(editing_file_index) in files_cache:
                    entry = files_cache[str(editing_file_index)]
                    entry['code'] = cleaned_code
                    entry['programming_language'] = detected_language
                    entry['version'] = version_num
                    entry['updated_at'] = datetime.now()
            except Exception as e:
                logger.warning(f"Failed to refresh files_cache after edit: {e}")
            
            await update.message.reply_text(
                f"✅ *הקובץ עודכן בהצלחה!*\n\n"
                f"📄 **קובץ:** `{file_name}`\n"
                f"🧠 **שפה:** {detected_language}\n"
                f"📝 **גרסה:** {version_num} (עודכן מהגרסה הקודמת)\n"
                f"💾 **הקובץ הקיים עודכן עם השינויים החדשים!**",
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(
                "❌ שגיאה בעדכון הקוד",
                reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
            )
    
    except Exception as e:
        # לוגים מפורטים לאיתור בעיות
        logger.error(f"Error updating code: {e}")
        logger.error(f"User ID: {update.effective_user.id}")
        logger.error(f"Original code length: {len(new_code) if new_code else 0}")
        logger.error(f"File name: {file_name if 'file_name' in locals() else 'Unknown'}")
        
        # רישום בלוגר הייעודי לקוד
        try:
            from code_processor import code_processor
            code_processor.code_logger.error(f"שגיאה בעדכון קוד עבור משתמש {update.effective_user.id}: {str(e)}")
        except:
            pass
        
        # הודעת שגיאה מפורטת למשתמש
        error_details = "פרטי השגיאה לא זמינים"
        if "validation" in str(e).lower():
            error_details = "שגיאה באימות הקוד"
        elif "database" in str(e).lower():
            error_details = "שגיאה בשמירת הקוד במסד הנתונים"
        elif "language" in str(e).lower():
            error_details = "שגיאה בזיהוי שפת התכנות"
        
        await update.message.reply_text(
            f"❌ שגיאה בעדכון הקוד\n\n"
            f"📝 **פרטים:** {error_details}\n"
            f"🔄 אנא נסה שוב או פנה לתמיכה\n"
            f"🏠 חזרה לתפריט הראשי",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
            parse_mode='Markdown'
        )
    
    # נקה את מצב העריכה אך שמור קאש של קבצים אם קיים
    preserved_cache = context.user_data.get('files_cache')
    context.user_data.clear()
    if preserved_cache is not None:
        context.user_data['files_cache'] = preserved_cache
    return ConversationHandler.END

async def handle_edit_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """התחלת עריכת שם קובץ"""
    query = update.callback_query
    await query.answer()
    
    try:
        file_index = query.data.split('_')[2]
        files_cache = context.user_data.get('files_cache', {})
        file_data = files_cache.get(file_index)
        
        if not file_data:
            await query.edit_message_text("❌ שגיאה בזיהוי הקובץ")
            return ConversationHandler.END
        
        context.user_data['editing_file_index'] = file_index
        context.user_data['editing_file_data'] = file_data
        
        current_name = file_data.get('file_name', 'קובץ')
        
        await query.edit_message_text(
            f"📝 *עריכת שם קובץ*\n\n"
            f"📄 **שם נוכחי:** `{current_name}`\n\n"
            f"✏️ שלח שם חדש לקובץ:\n"
            f"🚫 לביטול: `/cancel`",
            parse_mode='Markdown'
        )
        
        return EDIT_NAME
        
    except Exception as e:
        logger.error(f"Error in handle_edit_name: {e}")
        await query.edit_message_text("❌ שגיאה בהתחלת עריכת שם")
    
    return ConversationHandler.END

async def receive_new_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """קבלת השם החדש לקובץ"""
    new_name = update.message.text.strip()
    file_data = context.user_data.get('editing_file_data')
    
    if not file_data:
        await update.message.reply_text("❌ שגיאה בנתוני הקובץ")
        return ConversationHandler.END
    
    # בדיקת תקינות שם
    if not re.match(r'^[\w\.\-\_]+\.[a-zA-Z0-9]+$', new_name):
        await update.message.reply_text(
            "🤔 השם נראה קצת מוזר...\n"
            "💡 נסה שם כמו: `script.py` או `index.html`\n"
            "✅ אותיות, מספרים, נקודות וקווים מותרים!"
        )
        return EDIT_NAME
    
    try:
        user_id = update.effective_user.id
        # תמיכה במקרים ישירים ומקרי cache
        old_name = context.user_data.get('editing_file_name') or file_data.get('file_name')
        
        from database import db
        success = db.rename_file(user_id, old_name, new_name)
        
        if success:
            keyboard = [
                [
                    InlineKeyboardButton("👁️ הצג קוד", callback_data=f"view_direct_{new_name}"),
                    InlineKeyboardButton("📚 היסטוריה", callback_data=f"versions_file_{new_name}")
                ],
                [
                    InlineKeyboardButton("📥 הורד", callback_data=f"download_direct_{new_name}"),
                    InlineKeyboardButton("🔙 לרשימה", callback_data="files")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                f"✅ *שם הקובץ שונה בהצלחה!*\n\n"
                f"📄 **שם ישן:** `{old_name}`\n"
                f"📄 **שם חדש:** `{new_name}`\n"
                f"🎉 **הכל מעודכן במערכת!**",
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(
                "❌ שגיאה בשינוי השם",
                reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
            )
    
    except Exception as e:
        logger.error(f"Error renaming file: {e}")
        await update.message.reply_text(
            "❌ שגיאה בשינוי השם",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )
    
    context.user_data.clear()
    return ConversationHandler.END

async def handle_versions_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """הצגת היסטוריית גרסאות"""
    query = update.callback_query
    await query.answer()
    
    try:
        file_index = query.data.split('_')[1]
        files_cache = context.user_data.get('files_cache', {})
        file_data = files_cache.get(file_index)
        
        if not file_data:
            await query.edit_message_text("❌ שגיאה בזיהוי הקובץ")
            return ConversationHandler.END
        
        user_id = update.effective_user.id
        file_name = file_data.get('file_name')
        
        from database import db
        versions = db.get_all_versions(user_id, file_name)
        
        if not versions:
            await query.edit_message_text("📚 אין היסטוריית גרסאות לקובץ זה")
            return ConversationHandler.END
        
        history_text = f"📚 *היסטוריית גרסאות - {file_name}*\n\n"
        
        for i, version in enumerate(versions[:5]):  # מציג עד 5 גרסאות
            created_at = version.get('created_at', 'לא ידוע')
            version_num = version.get('version', i+1)
            code_length = len(version.get('code', ''))
            
            history_text += f"🔹 **גרסה {version_num}**\n"
            history_text += f"   📅 {created_at}\n"
            history_text += f"   📏 {code_length:,} תווים\n\n"
        
        keyboard = [
            [InlineKeyboardButton("🔙 חזרה", callback_data=f"file_{file_index}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            history_text,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        
    except Exception as e:
        logger.error(f"Error in handle_versions_history: {e}")
        await query.edit_message_text("❌ שגיאה בהצגת היסטוריה")
    
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
            await query.edit_message_text("❌ שגיאה בזיהוי הקובץ")
            return ConversationHandler.END
        
        file_name = file_data.get('file_name', 'file.txt')
        code = file_data.get('code', '')
        
        # יצירת קובץ להורדה
        file_bytes = BytesIO()
        file_bytes.write(code.encode('utf-8'))
        file_bytes.seek(0)
        
        await query.message.reply_document(
            document=file_bytes,
            filename=file_name,
            caption=f"📥 *הורדת קובץ*\n\n📄 **שם:** `{file_name}`\n📏 **גודל:** {len(code):,} תווים"
        )
        
        keyboard = [
            [InlineKeyboardButton("🔙 חזרה", callback_data=f"file_{file_index}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"✅ *הקובץ הורד בהצלחה!*\n\n"
            f"📄 **שם:** `{file_name}`",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        
    except Exception as e:
        logger.error(f"Error in handle_download_file: {e}")
        await query.edit_message_text("❌ שגיאה בהורדת הקובץ")
    
    return ConversationHandler.END

async def handle_delete_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """אישור מחיקת קובץ"""
    query = update.callback_query
    await query.answer()
    
    try:
        file_index = query.data.split('_')[1]
        files_cache = context.user_data.get('files_cache', {})
        file_data = files_cache.get(file_index)
        
        if not file_data:
            await query.edit_message_text("❌ שגיאה בזיהוי הקובץ")
            return ConversationHandler.END
        
        file_name = file_data.get('file_name', 'קובץ')
        
        keyboard = [
            [
                InlineKeyboardButton("✅ כן, מחק", callback_data=f"confirm_del_{file_index}"),
                InlineKeyboardButton("❌ לא, בטל", callback_data=f"file_{file_index}")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"⚠️ *אישור מחיקה*\n\n"
            f"📄 **קובץ:** `{file_name}`\n\n"
            f"🗑️ האם אתה בטוח שברצונך למחוק את הקובץ?\n"
            f"⚠️ **פעולה זו לא ניתנת לביטול!**",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        
    except Exception as e:
        logger.error(f"Error in handle_delete_confirmation: {e}")
        await query.edit_message_text("❌ שגיאה באישור מחיקה")
    
    return ConversationHandler.END

async def handle_delete_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """מחיקת קובץ סופית"""
    query = update.callback_query
    await query.answer()
    
    try:
        file_index = query.data.split('_')[2]
        files_cache = context.user_data.get('files_cache', {})
        file_data = files_cache.get(file_index)
        
        if not file_data:
            await query.edit_message_text("❌ שגיאה בזיהוי הקובץ")
            return ConversationHandler.END
        
        user_id = update.effective_user.id
        file_name = file_data.get('file_name')
        
        from database import db
        success = db.delete_file(user_id, file_name)
        
        if success:
            keyboard = [
                [InlineKeyboardButton("🔙 לרשימת קבצים", callback_data="files")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                f"✅ *הקובץ נמחק בהצלחה!*\n\n"
                f"📄 **קובץ שנמחק:** `{file_name}`\n"
                f"🗑️ **הקובץ הוסר לחלוטין מהמערכת**",
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
        else:
            await query.edit_message_text(
                f"❌ שגיאה במחיקת הקובץ `{file_name}`"
            )
        
    except Exception as e:
        logger.error(f"Error in handle_delete_file: {e}")
        await query.edit_message_text("❌ שגיאה במחיקת הקובץ")
    
    return ConversationHandler.END

async def handle_file_info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """הצגת מידע מפורט על קובץ"""
    query = update.callback_query
    await query.answer()
    
    try:
        file_index = query.data.split('_')[1]
        files_cache = context.user_data.get('files_cache', {})
        file_data = files_cache.get(file_index)
        
        if not file_data:
            await query.edit_message_text("❌ שגיאה בזיהוי הקובץ")
            return ConversationHandler.END
        
        file_name = file_data.get('file_name', 'קובץ')
        code = file_data.get('code', '')
        language = file_data.get('programming_language', 'לא ידועה')
        created_at = file_data.get('created_at', 'לא ידוע')
        version = file_data.get('version', 1)
        
        # חישוב סטטיסטיקות
        lines = len(code.split('\n'))
        chars = len(code)
        words = len(code.split())
        
        info_text = (
            f"📊 *מידע מפורט על הקובץ*\n\n"
            f"📄 **שם:** `{file_name}`\n"
            f"🧠 **שפת תכנות:** {language}\n"
            f"📅 **נוצר:** {created_at}\n"
            f"🔢 **גרסה:** {version}\n\n"
            f"📊 **סטטיסטיקות:**\n"
            f"• 📏 שורות: {lines:,}\n"
            f"• 🔤 תווים: {chars:,}\n"
            f"• 📝 מילים: {words:,}\n"
        )
        
        keyboard = [
            [InlineKeyboardButton("🔙 חזרה", callback_data=f"file_{file_index}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            info_text,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        
    except Exception as e:
        logger.error(f"Error in handle_file_info: {e}")
        await query.edit_message_text("❌ שגיאה בהצגת מידע")
    
    return ConversationHandler.END

async def handle_view_direct_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """הצגת קובץ באמצעות שם קובץ ישיר"""
    query = update.callback_query
    await query.answer()
    
    try:
        file_name = query.data.replace("view_direct_", "")
        user_id = update.effective_user.id
        
        from database import db
        file_data = db.get_latest_version(user_id, file_name)
        
        if not file_data:
            await query.edit_message_text("⚠️ הקובץ נעלם מהמערכת החכמה")
            return ConversationHandler.END
        
        code = file_data.get('code', '')
        language = file_data.get('programming_language', 'text')
        version = file_data.get('version', 1)
        
        # חיתוך חכם של הקוד
        max_length = 3500
        if len(code) > max_length:
            code_preview = code[:max_length] + "\n\n... [📱 הצג המשך - השתמש בהורדה לקובץ המלא]"
        else:
            code_preview = code
        
        # כפתורים מתקדמים לעריכה
        keyboard = [
            [
                InlineKeyboardButton("✏️ ערוך קוד", callback_data=f"edit_code_direct_{file_name}"),
                InlineKeyboardButton("📝 ערוך שם", callback_data=f"edit_name_direct_{file_name}")
            ],
            [
                InlineKeyboardButton("📚 היסטוריה", callback_data=f"versions_file_{file_name}"),
                InlineKeyboardButton("📥 הורד", callback_data=f"download_direct_{file_name}")
            ],
            [
                InlineKeyboardButton("🔄 שכפול", callback_data=f"clone_direct_{file_name}"),
                InlineKeyboardButton("📊 מידע מלא", callback_data=f"info_direct_{file_name}")
            ],
            [InlineKeyboardButton("🔙 לרשימה", callback_data="files")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"📄 *{file_name}* ({language}) - גרסה {version}\n\n"
            f"```{language}\n{code_preview}\n```",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        
    except Exception as e:
        logger.error(f"Error in handle_view_direct_file: {e}")
        await query.edit_message_text("❌ שגיאה בהצגת הקוד המתקדם")
    
    return ConversationHandler.END

async def handle_edit_code_direct(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """התחלת עריכת קוד באמצעות שם קובץ ישיר"""
    query = update.callback_query
    await query.answer()
    
    try:
        file_name = query.data.replace("edit_code_direct_", "")
        user_id = update.effective_user.id
        
        from database import db
        file_data = db.get_latest_version(user_id, file_name)
        
        if not file_data:
            await query.edit_message_text("❌ שגיאה בזיהוי הקובץ")
            return ConversationHandler.END
        
        context.user_data['editing_file_data'] = file_data
        context.user_data['editing_file_name'] = file_name
        
        await query.edit_message_text(
            f"✏️ *עריכת קוד מתקדמת*\n\n"
            f"📄 **קובץ:** `{file_name}`\n\n"
            f"📝 שלח את הקוד החדש והמעודכן:\n"
            f"🚫 לביטול: `/cancel`",
            parse_mode='Markdown'
        )
        
        return EDIT_CODE
        
    except Exception as e:
        logger.error(f"Error in handle_edit_code_direct: {e}")
        await query.edit_message_text("❌ שגיאה בהתחלת עריכה")
    
    return ConversationHandler.END

async def handle_edit_name_direct(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """התחלת עריכת שם קובץ באמצעות שם קובץ ישיר"""
    query = update.callback_query
    await query.answer()
    
    try:
        file_name = query.data.replace("edit_name_direct_", "")
        user_id = update.effective_user.id
        
        from database import db
        file_data = db.get_latest_version(user_id, file_name)
        
        if not file_data:
            await query.edit_message_text("❌ שגיאה בזיהוי הקובץ")
            return ConversationHandler.END
        
        context.user_data['editing_file_data'] = file_data
        context.user_data['editing_file_name'] = file_name
        
        await query.edit_message_text(
            f"📝 *עריכת שם קובץ*\n\n"
            f"📄 **שם נוכחי:** `{file_name}`\n\n"
            f"✏️ שלח שם חדש לקובץ:\n"
            f"🚫 לביטול: `/cancel`",
            parse_mode='Markdown'
        )
        
        return EDIT_NAME
        
    except Exception as e:
        logger.error(f"Error in handle_edit_name_direct: {e}")
        await query.edit_message_text("❌ שגיאה בהתחלת עריכת שם")
    
    return ConversationHandler.END

async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """מרכז בקרה מתקדם לכל הכפתורים"""
    query = update.callback_query
    
    try:
        data = query.data
        
        if data.startswith("file_") and not data.startswith("files"):
            return await handle_file_menu(update, context)
        elif data.startswith("view_"):
            if data.startswith("view_direct_"):
                return await handle_view_direct_file(update, context)
            else:
                return await handle_view_file(update, context)
        elif data.startswith("edit_code_"):
            if data.startswith("edit_code_direct_"):
                return await handle_edit_code_direct(update, context)
            else:
                return await handle_edit_code(update, context)
        elif data.startswith("edit_name_"):
            if data.startswith("edit_name_direct_"):
                return await handle_edit_name_direct(update, context)
            else:
                return await handle_edit_name(update, context)
        elif data.startswith("versions_"):
            return await handle_versions_history(update, context)
        elif data.startswith("dl_") or data.startswith("download_"):
            return await handle_download_file(update, context)
        elif data.startswith("del_") or data.startswith("delete_"):
            return await handle_delete_confirmation(update, context)
        elif data.startswith("confirm_del_"):
            return await handle_delete_file(update, context)
        elif data.startswith("info_"):
            return await handle_file_info(update, context)
        elif data == "files" or data == "refresh_files":
            return await show_all_files_callback(update, context)
        elif data == "main":
            await query.edit_message_text("🏠 חוזר לבית החכם:")
            await query.message.reply_text(
                "🎮 בחר פעולה מתקדמת:",
                reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
            )
        elif data.startswith("replace_") or data == "rename_file" or data == "cancel_save":
            return await handle_duplicate_callback(update, context)
        
        # טיפול בקבצים גדולים
        elif data == "show_regular_files":
            return await show_regular_files_callback(update, context)
        elif data == "show_large_files":
            from large_files_handler import large_files_handler
            await large_files_handler.show_large_files_menu(update, context)
        elif data.startswith("lf_page_"):
            from large_files_handler import large_files_handler
            page = int(data.replace("lf_page_", ""))
            await large_files_handler.show_large_files_menu(update, context, page)
        elif data.startswith("large_file_"):
            from large_files_handler import large_files_handler
            await large_files_handler.handle_file_selection(update, context)
        elif data.startswith("lf_view_"):
            from large_files_handler import large_files_handler
            await large_files_handler.view_large_file(update, context)
        elif data.startswith("lf_download_"):
            from large_files_handler import large_files_handler
            await large_files_handler.download_large_file(update, context)
        elif data.startswith("lf_edit_"):
            from large_files_handler import large_files_handler
            return await large_files_handler.edit_large_file(update, context)
        elif data.startswith("lf_delete_"):
            from large_files_handler import large_files_handler
            await large_files_handler.delete_large_file_confirm(update, context)
        elif data.startswith("lf_confirm_delete_"):
            from large_files_handler import large_files_handler
            await large_files_handler.delete_large_file(update, context)
        elif data.startswith("lf_info_"):
            from large_files_handler import large_files_handler
            await large_files_handler.show_file_info(update, context)
        elif data == "noop":
            # כפתור שלא עושה כלום (לתצוגה בלבד)
            await query.answer()
        
    except telegram.error.BadRequest as e:
        if "Message is not modified" not in str(e):
            raise
    except Exception as e:
        logger.error(f"Error in smart callback handler: {e}")
    
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """ביטול מתקדם"""
    context.user_data.clear()
    
    await update.message.reply_text(
        "🚫 התהליך בוטל בהצלחה!\n"
        "🏠 חוזרים לבית החכם שלנו.",
        reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
    )
    return ConversationHandler.END

def get_save_conversation_handler(db: DatabaseManager) -> ConversationHandler:
    """יוצר ConversationHandler מתקדם וחכם"""
    logger.info("יוצר מערכת שיחה מתקדמת...")
    
    return ConversationHandler(
        entry_points=[
            CommandHandler("start", start_command),
            MessageHandler(filters.Regex("^➕ הוסף קוד חדש$"), start_save_flow),
            MessageHandler(filters.Regex("^📚 הצג את כל הקבצים שלי$"), show_all_files),
            MessageHandler(filters.Regex("^📂 קבצים גדולים$"), show_large_files_direct),
            MessageHandler(filters.Regex("^🔧 GitHub$"), show_github_menu),
            # כניסה לעריכת קוד/שם גם דרך כפתורי callback כדי שמצב השיחה ייקבע כראוי
            CallbackQueryHandler(handle_callback_query, pattern=r'^(edit_code_|edit_name_|lf_edit_)')
        ],
        states={
            GET_CODE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_code)
            ],
            GET_FILENAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_filename),
                CallbackQueryHandler(handle_duplicate_callback)
            ],
            EDIT_CODE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_new_code)
            ],
            EDIT_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_new_name)
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            CallbackQueryHandler(handle_callback_query)
        ],
        allow_reentry=True,
        per_message=False
    )