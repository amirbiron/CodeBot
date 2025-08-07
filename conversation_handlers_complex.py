import asyncio
import logging
import re
from datetime import datetime
from io import BytesIO

import telegram.error
from telegram import (InlineKeyboardButton, InlineKeyboardMarkup,
                      ReplyKeyboardMarkup, ReplyKeyboardRemove, Update)
from telegram.ext import (CallbackQueryHandler, CommandHandler, ContextTypes,
                          ConversationHandler, MessageHandler, filters)

from activity_reporter import create_reporter
from database import DatabaseManager

# הגדרת לוגר
logger = logging.getLogger(__name__)

# הגדרת שלבי השיחה - פשוט
GET_CODE, GET_FILENAME, EDIT_CODE, EDIT_NAME = range(4)

# כפתורי המקלדת הראשית
MAIN_KEYBOARD = [["➕ הוסף קוד חדש"], ["📚 הצג את כל הקבצים שלי"]]

reporter = create_reporter()


def get_file_emoji(language):
    """פונקציה להחזרת אמוג'י בהתאם לשפת התכנות"""
    emoji_map = {
        "python": "🐍",
        "javascript": "🟨",
        "java": "☕",
        "c": "🔧",
        "cpp": "🔧",
        "c++": "🔧",
        "html": "🌐",
        "css": "🎨",
        "sql": "🗄️",
        "php": "🐘",
        "ruby": "💎",
        "go": "🐹",
        "rust": "🦀",
        "swift": "🍎",
        "kotlin": "🟣",
        "typescript": "🔷",
        "bash": "🐚",
        "shell": "🐚",
        "json": "📄",
        "xml": "📄",
        "yaml": "📄",
        "yml": "📄",
        "markdown": "📝",
        "md": "📝",
        "txt": "📄",
        "text": "📄",
    }
    return emoji_map.get(language.lower(), "📄")


async def handle_duplicate_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """פונקציה לטיפול בקריאות כפולות"""
    query = update.callback_query
    await query.answer()

    # לוגיקה לטיפול בקבצים כפולים
    # כאן ניתן להוסיף לוגיקה ספציפית לטיפול בקבצים עם שמות זהים
    logger.info(f"Handle duplicate callback called by user {update.effective_user.id}")

    return ConversationHandler.END


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


async def handle_file_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """מציג תפריט אפשרויות לקובץ ספציפי"""
    query = update.callback_query
    await query.answer()

    try:
        # קבלת האינדקס מה-callback_data
        file_index = query.data.split("_")[1]

        # קבלת המידע מה-cache
        files_cache = context.user_data.get("files_cache", {})
        file_data = files_cache.get(file_index)

        if not file_data:
            await query.edit_message_text("❌ שגיאה בזיהוי הקובץ")
            return ConversationHandler.END

        file_name = file_data.get("file_name", "קובץ ללא שם")

        # יצירת כפתורי פעולה עם callback_data קצר
        keyboard = [
            [
                InlineKeyboardButton("👁️ הצג קוד", callback_data=f"view_{file_index}"),
                InlineKeyboardButton("📥 הורד", callback_data=f"dl_{file_index}"),
            ],
            [
                InlineKeyboardButton("🗑️ מחק", callback_data=f"del_{file_index}"),
                InlineKeyboardButton("📊 מידע", callback_data=f"info_{file_index}"),
            ],
            [InlineKeyboardButton("🔙 חזרה לרשימה", callback_data="files")],
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(
            f"📄 *{file_name}*\n\n" "בחר פעולה:",
            reply_markup=reply_markup,
            parse_mode="Markdown",
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
        file_index = query.data.split("_")[1]

        # קבלת המידע מה-cache
        files_cache = context.user_data.get("files_cache", {})
        file_data = files_cache.get(file_index)

        if not file_data:
            await query.edit_message_text("⚠️ הקובץ לא נמצא")
            return ConversationHandler.END

        file_name = file_data.get("file_name", "קובץ")
        code = file_data.get("code", "")
        language = file_data.get("programming_language", "text")
        version = file_data.get("version", 1)

        # חיתוך הקוד אם הוא ארוך מדי
        max_length = 3500
        if len(code) > max_length:
            code_preview = (
                code[:max_length] + "\n\n... [קוד חתוך - השתמש בהורדה לקובץ המלא]"
            )
        else:
            code_preview = code

        # כפתורים מורחבים עם עריכה
        keyboard = [
            [
                InlineKeyboardButton(
                    "✏️ ערוך קוד", callback_data=f"edit_code_{file_index}"
                ),
                InlineKeyboardButton(
                    "📝 ערוך שם", callback_data=f"edit_name_{file_index}"
                ),
            ],
            [
                InlineKeyboardButton(
                    "📚 היסטוריה", callback_data=f"versions_{file_index}"
                ),
                InlineKeyboardButton("📥 הורד", callback_data=f"dl_{file_index}"),
            ],
            [InlineKeyboardButton("🔙 חזרה", callback_data=f"file_{file_index}")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(
            f"📄 *{file_name}* ({language}) - גרסה {version}\n\n"
            f"```{language}\n{code_preview}\n```",
            reply_markup=reply_markup,
            parse_mode="Markdown",
        )

    except Exception as e:
        logger.error(f"Error in handle_view_file: {e}")
        await query.edit_message_text("❌ שגיאה בהצגת הקובץ")

    reporter.report_activity(update.effective_user.id)
    return ConversationHandler.END


async def handle_edit_code(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """התחלת עריכת קוד - תומך בגישה ישירה וגישה דרך cache"""
    logger.info(f"=== handle_edit_code התחיל - User ID: {update.effective_user.id}")

    query = update.callback_query
    await query.answer()

    logger.info(f"callback_data: {query.data}")

    try:
        # זיהוי סוג הקריאה
        if query.data.startswith("edit_code_direct_"):
            file_name = query.data.replace("edit_code_direct_", "")
            user_id = query.from_user.id

            logger.info(f"עריכה ישירה: {file_name}")

            # קבלה מהמסד
            from database import db

            file_data = db.get_latest_version(user_id, file_name)

            if not file_data:
                logger.error(f"קובץ לא נמצא במסד: {file_name}")
                await query.edit_message_text("⚠️ הקובץ לא נמצא")
                return ConversationHandler.END

            logger.info(f"קובץ נמצא: {file_data.get('file_name', 'N/A')}")

        else:  # edit_code_X - גישה דרך cache
            file_index = query.data.split("_")[2]
            logger.info(f"עריכה דרך cache: index {file_index}")

            files_cache = context.user_data.get("files_cache", {})
            file_data = files_cache.get(file_index)

            if not file_data:
                logger.error(f"קובץ לא נמצא ב-cache: index {file_index}")
                await query.edit_message_text("⚠️ הקובץ לא נמצא")
                return ConversationHandler.END

            file_name = file_data.get("file_name", "קובץ")
            logger.info(f"קובץ נמצא ב-cache: {file_name}")

        # שמירת המידע לעריכה
        context.user_data["editing_file"] = {
            "file_data": file_data,
            "edit_type": "code",
            "file_name": file_name,
        }

        logger.info(f"מידע נשמר ל-context: {file_name}")

        # כפתור ביטול במקום פקודה
        keyboard = [[InlineKeyboardButton("❌ ביטול", callback_data="cancel_edit")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(
            f"✏️ *עריכת קוד - {file_name}*\n\n" "📝 שלח את הקוד החדש:",
            reply_markup=reply_markup,
            parse_mode="Markdown",
        )

        logger.info("הודעת עריכה נשלחה, מחזיר EDIT_CODE")
        return EDIT_CODE

    except Exception as e:
        logger.error(f"שגיאה ב-handle_edit_code: {e}", exc_info=True)
        await query.edit_message_text("❌ שגיאה בתחילת עריכה")

    return ConversationHandler.END


async def handle_edit_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """התחלת עריכת שם קובץ"""
    query = update.callback_query
    await query.answer()

    try:
        # זיהוי סוג הקריאה
        if query.data.startswith("edit_name_direct_"):
            file_name = query.data.replace("edit_name_direct_", "")
            user_id = query.from_user.id

            # קבלה מהמסד
            from database import db

            file_data = db.get_latest_version(user_id, file_name)

            if not file_data:
                await query.edit_message_text("⚠️ הקובץ לא נמצא")
                return ConversationHandler.END

        else:  # edit_name_X - גישה דרך cache
            file_index = query.data.split("_")[2]
            files_cache = context.user_data.get("files_cache", {})
            file_data = files_cache.get(file_index)

            if not file_data:
                await query.edit_message_text("⚠️ הקובץ לא נמצא")
                return ConversationHandler.END

            file_name = file_data.get("file_name", "קובץ")

        # שמירת המידע לעריכה
        context.user_data["editing_file"] = {
            "file_data": file_data,
            "edit_type": "name",
            "file_name": file_name,
        }

        # כפתור ביטול
        keyboard = [[InlineKeyboardButton("❌ ביטול", callback_data="cancel_edit")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(
            f"📝 *עריכת שם קובץ*\n\n"
            f"שם נוכחי: `{file_name}`\n\n"
            "📝 שלח את השם החדש:",
            reply_markup=reply_markup,
            parse_mode="Markdown",
        )

        return EDIT_NAME

    except Exception as e:
        logger.error(f"Error in handle_edit_name: {e}")
        await query.edit_message_text("❌ שגיאה בתחילת עריכה")

    return ConversationHandler.END


async def handle_cancel_edit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """ביטול עריכה"""
    query = update.callback_query
    await query.answer()

    editing_info = context.user_data.get("editing_file", {})
    file_name = editing_info.get("file_name", "קובץ")

    # ניקוי
    context.user_data.clear()

    await query.edit_message_text(
        f"❌ עריכת `{file_name}` בוטלה.", parse_mode="Markdown"
    )

    # חזרה לתפריט הראשי
    await asyncio.sleep(1)
    await query.message.reply_text(
        "בחר פעולה:",
        reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
    )

    return ConversationHandler.END


async def receive_new_code(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """קבלת קוד חדש לעריכה"""
    print(f"🔥🔥🔥 receive_new_code נקרא! User: {update.effective_user.id}")
    logger.critical(f"🔥🔥🔥 receive_new_code נקרא! User: {update.effective_user.id}")
    logger.info(f"=== receive_new_code התחיל - User ID: {update.effective_user.id}")

    new_code = update.message.text
    editing_info = context.user_data.get("editing_file", {})

    logger.info(f"קוד חדש התקבל, אורך: {len(new_code)} תווים")
    logger.info(f"editing_info: {editing_info}")

    file_data = editing_info.get("file_data", {})
    file_name = editing_info.get("file_name") or file_data.get("file_name", "קובץ")
    old_code = file_data.get("code", "")
    user_id = update.effective_user.id

    logger.info(f"שם קובץ: {file_name}, משתמש: {user_id}")

    # תגובה מיידית שהקוד התקבל
    try:
        processing_msg = await update.message.reply_text(
            "⏳ מעבד ושומר את הקוד החדש..."
        )
        logger.info("הודעת עיבוד נשלחה")
    except Exception as e:
        logger.error(f"שגיאה בשליחת הודעת עיבוד: {e}")
        processing_msg = None

    try:
        logger.info("מתחיל תהליך שמירה...")

        # יצירת גרסה חדשה במסד הנתונים
        from database import db
        from file_manager import VersionManager

        logger.info("ייבואים הושלמו")

        version_manager = VersionManager()
        logger.info("VersionManager נוצר")

        # זיהוי שפה מחדש
        from code_processor import code_processor

        logger.info("מזהה שפת תכנות...")

        detected_language = code_processor.detect_language(new_code, file_name)
        logger.info(f"שפה זוהתה: {detected_language}")

        # שמירת הגרסה החדשה
        logger.info("שומר קובץ במסד הנתונים...")
        success = db.save_file(user_id, file_name, new_code, detected_language)
        logger.info(f"תוצאת שמירה: {success}")

        if success:
            logger.info("שמירה הצליחה, מחשב שינויים...")

            # חישוב שינויים
            try:
                changes_summary = version_manager._generate_changes_summary(
                    old_code, new_code
                )
                logger.info(f"סיכום שינויים: {changes_summary}")
            except Exception as summary_error:
                logger.error(f"שגיאה בחישוב שינויים: {summary_error}")
                changes_summary = "שינויים זוהו"

            # כפתורים מלאים אחרי שמירה
            keyboard = [
                [
                    InlineKeyboardButton(
                        "👁️ הצג קוד מעודכן", callback_data=f"view_updated_{file_name}"
                    ),
                    InlineKeyboardButton(
                        "✏️ ערוך שוב", callback_data=f"edit_code_direct_{file_name}"
                    ),
                ],
                [
                    InlineKeyboardButton(
                        "📚 גרסאות קודמות", callback_data=f"versions_file_{file_name}"
                    ),
                    InlineKeyboardButton(
                        "📝 ערוך שם", callback_data=f"edit_name_direct_{file_name}"
                    ),
                ],
                [
                    InlineKeyboardButton(
                        "📥 הורד", callback_data=f"download_direct_{file_name}"
                    ),
                    InlineKeyboardButton(
                        "🗑️ מחק קובץ", callback_data=f"delete_direct_{file_name}"
                    ),
                ],
                [InlineKeyboardButton("🔙 לרשימת קבצים", callback_data="files")],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            logger.info("כפתורים נוצרו")

            # מחיקת הודעת העיבוד
            if processing_msg:
                try:
                    await processing_msg.delete()
                    logger.info("הודעת עיבוד נמחקה")
                except Exception as del_error:
                    logger.error(f"שגיאה במחיקת הודעת עיבוד: {del_error}")

            # שליחת הודעת הצלחה
            logger.info("שולח הודעת הצלחה...")
            success_msg = await update.message.reply_text(
                f"✅ *הקוד עודכן בהצלחה!*\n\n"
                f"📄 קובץ: `{file_name}`\n"
                f"🔍 שפה: {detected_language}\n"
                f"📊 שינויים: {changes_summary}\n\n"
                f"💾 הגרסה הקודמת נשמרה אוטומטית",
                reply_markup=reply_markup,
                parse_mode="Markdown",
            )
            logger.info(f"הודעת הצלחה נשלחה, ID: {success_msg.message_id}")

        else:
            logger.error("שמירה נכשלה!")

            # מחיקת הודעת העיבוד
            if processing_msg:
                try:
                    await processing_msg.delete()
                except:
                    pass

            await update.message.reply_text(
                "❌ שגיאה בשמירת הקוד החדש. נסה שוב.",
                reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
            )
            logger.info("הודעת כישלון נשלחה")

    except Exception as e:
        logger.error(f"שגיאה קריטית ב-receive_new_code: {e}", exc_info=True)

        # מחיקת הודעת העיבוד
        if processing_msg:
            try:
                await processing_msg.delete()
            except:
                pass

        # הודעת שגיאה עם כפתורי חזרה
        keyboard = [
            [InlineKeyboardButton("🔙 לרשימת קבצים", callback_data="files")],
            [InlineKeyboardButton("🏠 תפריט ראשי", callback_data="main")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            f"❌ שגיאה בעדכון הקוד:\n`{str(e)[:100]}...`\n\nנסה שוב מאוחר יותר",
            reply_markup=reply_markup,
            parse_mode="Markdown",
        )
        logger.info("הודעת שגיאה עם כפתורים נשלחה")

    # ניקוי
    logger.info("מנקה context.user_data...")
    context.user_data.clear()
    logger.info("=== receive_new_code הסתיים")
    return ConversationHandler.END


async def receive_new_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """קבלת שם חדש לקובץ"""
    new_name = update.message.text.strip()
    editing_info = context.user_data.get("editing_file", {})
    file_data = editing_info.get("file_data", {})

    # תמיכה בשני מצבים: index-based ו-file name-based
    old_name = editing_info.get("file_name") or file_data.get("file_name", "קובץ")
    user_id = update.effective_user.id

    # בדיקת תקינות שם
    if not re.match(r"^[\w\.\-]+\.[a-zA-Z0-9]+$", new_name):
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
                f"❌ קובץ בשם `{new_name}` כבר קיים.\n" "בחר שם אחר.",
                parse_mode="Markdown",
            )
            return EDIT_NAME

        # עדכון שם הקובץ במסד הנתונים
        # כאן צריך לעדכן את כל הגרסאות של הקובץ
        result = db.collection.update_many(
            {"user_id": user_id, "file_name": old_name, "is_active": True},
            {"$set": {"file_name": new_name, "updated_at": datetime.now()}},
        )

        if result.modified_count > 0:
            keyboard = [
                [
                    InlineKeyboardButton(
                        "👁️ הצג קובץ", callback_data=f"view_updated_{new_name}"
                    )
                ],
                [InlineKeyboardButton("🔙 לרשימת קבצים", callback_data="files")],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await update.message.reply_text(
                f"✅ *שם הקובץ עודכן בהצלחה!*\n\n"
                f"📄 שם ישן: `{old_name}`\n"
                f"📄 שם חדש: `{new_name}`\n\n"
                f"💾 כל הגרסאות עודכנו",
                reply_markup=reply_markup,
                parse_mode="Markdown",
            )
        else:
            await update.message.reply_text("❌ לא הצלחתי לעדכן את השם")

    except Exception as e:
        logger.error(f"Error updating file name: {e}")
        await update.message.reply_text("❌ שגיאה בעדכון השם")

    # ניקוי
    context.user_data.clear()
    return ConversationHandler.END


async def handle_versions_history(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """הצגת היסטוריית גרסאות"""
    query = update.callback_query
    await query.answer()

    try:
        if query.data.startswith("versions_"):
            file_index = query.data.split("_")[1]

            files_cache = context.user_data.get("files_cache", {})
            file_data = files_cache.get(file_index)

            if not file_data:
                await query.edit_message_text("⚠️ הקובץ לא נמצא")
                return ConversationHandler.END

            file_name = file_data.get("file_name", "קובץ")

        elif query.data.startswith("versions_file_"):
            file_name = query.data.replace("versions_file_", "")

        else:
            await query.edit_message_text("❌ נתונים לא תקינים")
            return ConversationHandler.END

        user_id = query.from_user.id

        # קבלת כל הגרסאות
        from database import db

        versions = db.get_all_versions(user_id, file_name)

        if not versions or len(versions) == 0:
            # אין גרסאות - הצג הודעה ידידותית עם כפתורים
            keyboard = [
                [
                    InlineKeyboardButton(
                        "👁️ הצג קובץ", callback_data=f"view_updated_{file_name}"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "✏️ ערוך קוד", callback_data=f"edit_code_direct_{file_name}"
                    ),
                    InlineKeyboardButton(
                        "📝 ערוך שם", callback_data=f"edit_name_direct_{file_name}"
                    ),
                ],
                [InlineKeyboardButton("🔙 לרשימת קבצים", callback_data="files")],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await query.edit_message_text(
                f"📚 *היסטוריית גרסאות - {file_name}*\n\n"
                f"📄 זהו קובץ חדש - יש רק גרסה אחת (נוכחית)\n\n"
                f"💡 גרסאות נוספות ייווצרו כאשר תערוך את הקובץ",
                reply_markup=reply_markup,
                parse_mode="Markdown",
            )
            return ConversationHandler.END

        # יצירת רשימת גרסאות
        versions_text = f"📚 *היסטוריית גרסאות - {file_name}*\n\n"

        for i, version in enumerate(versions[:10]):  # מגביל ל-10 גרסאות אחרונות
            version_num = version.get("version", i + 1)
            created_at = version.get("created_at", "לא ידוע")

            if isinstance(created_at, str):
                date_str = created_at[:19]
            else:
                date_str = str(created_at)[:19] if created_at else "לא ידוע"

            current_marker = " 🟢 *נוכחי*" if i == 0 else ""
            versions_text += f"📄 **גרסה {version_num}**{current_marker}\n"
            versions_text += f"🕐 {date_str}\n"

            if i < len(versions) - 1:
                versions_text += "➖➖➖\n"

        if len(versions) > 10:
            versions_text += f"\n... ועוד {len(versions) - 10} גרסאות ישנות"

        # כפתורים
        keyboard = [
            [
                InlineKeyboardButton(
                    "👁️ הצג קובץ נוכחי", callback_data=f"view_updated_{file_name}"
                )
            ],
            [
                InlineKeyboardButton(
                    "✏️ ערוך קוד", callback_data=f"edit_code_direct_{file_name}"
                ),
                InlineKeyboardButton(
                    "📝 ערוך שם", callback_data=f"edit_name_direct_{file_name}"
                ),
            ],
            [InlineKeyboardButton("🔙 לרשימת קבצים", callback_data="files")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(
            versions_text, reply_markup=reply_markup, parse_mode="Markdown"
        )

    except Exception as e:
        logger.error(f"Error in handle_versions_history: {e}")

        # שגיאה - תמיד נציג כפתורים כדי לא לקלקל את הממשק
        keyboard = [
            [
                InlineKeyboardButton(
                    "👁️ הצג קובץ",
                    callback_data=f"view_updated_{file_name if 'file_name' in locals() else 'unknown'}",
                )
            ],
            [InlineKeyboardButton("🔙 לרשימת קבצים", callback_data="files")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(
            "❌ שגיאה בהצגת היסטוריה\n\n" "נסה שוב או חזור לרשימת הקבצים",
            reply_markup=reply_markup,
        )

    return ConversationHandler.END


async def handle_view_updated_file(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """הצגת קובץ מעודכן אחרי עריכה"""
    query = update.callback_query
    await query.answer()

    try:
        # חילוץ שם הקובץ מה-callback_data
        file_name = query.data.replace("view_updated_", "")
        user_id = query.from_user.id

        # קבלת הקובץ מהמסד
        from database import db

        file_data = db.get_latest_version(user_id, file_name)

        if not file_data:
            # הקובץ לא נמצא - תמיד נציג כפתורים כדי לא לקלקל
            keyboard = [
                [InlineKeyboardButton("📚 רשימת קבצים", callback_data="files")],
                [InlineKeyboardButton("➕ הוסף קוד חדש", callback_data="add_new_code")],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await query.edit_message_text(
                f"⚠️ הקובץ `{file_name}` לא נמצא\n\n" "ייתכן שנמחק או שונה שמו",
                reply_markup=reply_markup,
                parse_mode="Markdown",
            )
            return ConversationHandler.END

        code = file_data.get("code", "")
        language = file_data.get("programming_language", "text")
        version = file_data.get("version", 1)

        # חיתוך הקוד אם נדרש
        max_length = 3500
        if len(code) > max_length:
            code_preview = (
                code[:max_length] + "\n\n... [קוד חתוך - השתמש בהורדה לקובץ המלא]"
            )
        else:
            code_preview = code

        # כפתורים מלאים - תמיד
        keyboard = [
            [
                InlineKeyboardButton(
                    "✏️ ערוך קוד", callback_data=f"edit_code_direct_{file_name}"
                ),
                InlineKeyboardButton(
                    "📝 ערוך שם", callback_data=f"edit_name_direct_{file_name}"
                ),
            ],
            [
                InlineKeyboardButton(
                    "📚 היסטוריה", callback_data=f"versions_file_{file_name}"
                ),
                InlineKeyboardButton(
                    "📥 הורד", callback_data=f"download_direct_{file_name}"
                ),
            ],
            [
                InlineKeyboardButton(
                    "🗑️ מחק", callback_data=f"delete_direct_{file_name}"
                ),
                InlineKeyboardButton("🔙 לרשימת קבצים", callback_data="files"),
            ],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(
            f"📄 *{file_name}* ({language}) - גרסה {version}\n\n"
            f"```{language}\n{code_preview}\n```",
            reply_markup=reply_markup,
            parse_mode="Markdown",
        )

    except Exception as e:
        logger.error(f"Error in handle_view_updated_file: {e}")

        # גם בשגיאה - תמיד כפתורים
        keyboard = [
            [InlineKeyboardButton("📚 רשימת קבצים", callback_data="files")],
            [
                InlineKeyboardButton(
                    "🔄 נסה שוב",
                    callback_data=f"view_updated_{file_name if 'file_name' in locals() else 'unknown'}",
                )
            ],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(
            "❌ שגיאה בהצגת הקובץ\n\n" "נסה שוב או חזור לרשימת הקבצים",
            reply_markup=reply_markup,
        )

    return ConversationHandler.END


async def handle_compare_versions(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
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

        latest_code = latest.get("code", "")
        previous_code = previous.get("code", "")

        # חישוב הבדלים בסיסי
        latest_lines = len(latest_code.split("\n"))
        previous_lines = len(previous_code.split("\n"))
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
            [
                InlineKeyboardButton(
                    "🔙 חזרה להיסטוריה", callback_data=f"versions_file_{file_name}"
                )
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(
            diff_text, reply_markup=reply_markup, parse_mode="Markdown"
        )

    except Exception as e:
        logger.error(f"Error in handle_compare_versions: {e}")
        await query.edit_message_text("❌ שגיאה בהשוואת גרסאות")

    return ConversationHandler.END


async def handle_edit_code_file(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
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
        context.user_data["editing_file"] = {
            "file_name": file_name,
            "file_data": file_data,
            "edit_type": "code",
        }

        await query.edit_message_text(
            f"✏️ *עריכת קוד - {file_name}*\n\n"
            "שלח את הקוד החדש.\n"
            "לביטול שלח `/cancel`",
            parse_mode="Markdown",
        )

        return EDIT_CODE

    except Exception as e:
        logger.error(f"Error in handle_edit_code_file: {e}")
        await query.edit_message_text("❌ שגיאה בתחילת עריכה")

    return ConversationHandler.END


async def handle_edit_name_file(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
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
        context.user_data["editing_file"] = {
            "file_name": file_name,
            "file_data": file_data,
            "edit_type": "name",
        }

        await query.edit_message_text(
            f"📝 *עריכת שם קובץ*\n\n"
            f"שם נוכחי: `{file_name}`\n\n"
            "שלח את השם החדש.\n"
            "לביטול שלח `/cancel`",
            parse_mode="Markdown",
        )

        return EDIT_NAME

    except Exception as e:
        logger.error(f"Error in handle_edit_name_file: {e}")
        await query.edit_message_text("❌ שגיאה בתחילת עריכה")

    return ConversationHandler.END


async def handle_download_file_by_name(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
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

        code_content = file_data.get("code", "")

        # יצירת קובץ בזיכרון
        file_in_memory = BytesIO(code_content.encode("utf-8"))

        # שליחת הקובץ
        await context.bot.send_document(
            chat_id=query.message.chat_id,
            document=file_in_memory,
            filename=file_name,
            caption=f"📥 הקובץ '{file_name}' מוכן להורדה!",
        )

        await query.answer("✅ הקובץ נשלח!")

    except Exception as e:
        logger.error(f"Error in handle_download_file_by_name: {e}")
        await query.answer("❌ שגיאה בהורדת הקובץ", show_alert=True)

    return ConversationHandler.END


async def handle_callback_query(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """טיפול בכל הכפתורים האינטראקטיביים"""
    query = update.callback_query

    try:
        data = query.data

        if data.startswith("file_") and not data.startswith("files"):
            return await handle_file_menu(update, context)
        elif data.startswith("view_"):
            if data.startswith("view_updated_"):
                return await handle_view_updated_file(update, context)
            else:
                return await handle_view_file(update, context)
        elif data.startswith("edit_code_"):
            return await handle_edit_code(update, context)
        elif data.startswith("edit_name_"):
            return await handle_edit_name(update, context)
        elif data.startswith("versions_"):
            return await handle_versions_history(update, context)
        elif data.startswith("dl_") or data.startswith("download_direct_"):
            return await handle_download_file(update, context)
        elif data.startswith("del_") or data.startswith("delete_direct_"):
            return await handle_delete_confirmation(update, context)
        elif data.startswith("confirm_del_"):
            return await handle_delete_file(update, context)
        elif data.startswith("info_"):
            return await handle_file_info(update, context)
        elif data == "cancel_edit":
            return await handle_cancel_edit(update, context)
        elif data == "files":
            return await show_all_files_callback(update, context)
        elif data == "add_new_code":
            await query.edit_message_text("בחר פעולה:")
            await query.message.reply_text(
                "➕ לחץ על 'הוסף קוד חדש' כדי להתחיל",
                reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
            )
        elif data == "main":
            await query.edit_message_text("חוזר לתפריט הראשי:")
            await query.message.reply_text(
                "בחר פעולה:",
                reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
            )

    except telegram.error.BadRequest as e:
        if "Message is not modified" not in str(e):
            raise
    except Exception as e:
        logger.error(f"Error in handle_callback_query: {e}")

    reporter.report_activity(update.effective_user.id)
    return ConversationHandler.END


async def handle_download_file(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """הורדת קובץ - תומך בגישה ישירה וגישה דרך cache"""
    query = update.callback_query
    await query.answer()

    try:
        # זיהוי סוג הקריאה
        if query.data.startswith("download_direct_"):
            file_name = query.data.replace("download_direct_", "")
            user_id = query.from_user.id

            # קבלה מהמסד
            from database import db

            file_data = db.get_latest_version(user_id, file_name)

            if not file_data:
                await query.answer("⚠️ הקובץ לא נמצא", show_alert=True)
                return ConversationHandler.END

            code_content = file_data.get("code", "")

        else:  # dl_X - גישה דרך cache
            file_index = query.data.split("_")[1]
            files_cache = context.user_data.get("files_cache", {})
            file_data = files_cache.get(file_index)

            if not file_data:
                await query.answer("⚠️ הקובץ לא נמצא", show_alert=True)
                return ConversationHandler.END

            file_name = file_data.get("file_name", "file.txt")
            code_content = file_data.get("code", "")

        # יצירת קובץ בזיכרון
        file_in_memory = BytesIO(code_content.encode("utf-8"))

        # שליחת הקובץ
        await context.bot.send_document(
            chat_id=query.message.chat_id,
            document=file_in_memory,
            filename=file_name,
            caption=f"📥 הקובץ '{file_name}' מוכן להורדה!",
        )

        await query.answer("✅ הקובץ נשלח!")

    except Exception as e:
        logger.error(f"Error in handle_download_file: {e}")
        await query.answer("❌ שגיאה בהורדת הקובץ", show_alert=True)

    return ConversationHandler.END


async def handle_delete_confirmation(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """מציג אישור מחיקה - תומך בגישה ישירה וגישה דרך cache"""
    query = update.callback_query
    await query.answer()

    try:
        # זיהוי סוג הקריאה
        if query.data.startswith("delete_direct_"):
            file_name = query.data.replace("delete_direct_", "")
            user_id = query.from_user.id

            # בדיקה שהקובץ קיים
            from database import db

            file_data = db.get_latest_version(user_id, file_name)

            if not file_data:
                await query.edit_message_text("⚠️ הקובץ לא נמצא")
                return ConversationHandler.END

            # כפתורי אישור לגישה ישירה
            keyboard = [
                [
                    InlineKeyboardButton(
                        "🗑️ כן, מחק", callback_data=f"confirm_del_direct_{file_name}"
                    ),
                    InlineKeyboardButton(
                        "❌ לא, בטל", callback_data=f"view_updated_{file_name}"
                    ),
                ]
            ]

        else:  # del_X - גישה דרך cache
            file_index = query.data.split("_")[1]
            files_cache = context.user_data.get("files_cache", {})
            file_data = files_cache.get(file_index)

            if not file_data:
                await query.edit_message_text("⚠️ הקובץ לא נמצא")
                return ConversationHandler.END

            file_name = file_data.get("file_name", "קובץ ללא שם")

            # כפתורי אישור לגישה דרך cache
            keyboard = [
                [
                    InlineKeyboardButton(
                        "🗑️ כן, מחק", callback_data=f"confirm_del_{file_index}"
                    ),
                    InlineKeyboardButton(
                        "❌ לא, בטל", callback_data=f"file_{file_index}"
                    ),
                ]
            ]

        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(
            f"⚠️ *אישור מחיקה*\n\n"
            f"האם אתה בטוח שברצונך למחוק את הקובץ:\n"
            f"📄 `{file_name}`\n\n"
            f"⚠️ פעולה זו לא ניתנת לביטול!",
            reply_markup=reply_markup,
            parse_mode="Markdown",
        )

    except Exception as e:
        logger.error(f"Error in handle_delete_confirmation: {e}")
        await query.edit_message_text("❌ שגיאה בהצגת אישור המחיקה")

    return ConversationHandler.END


async def handle_delete_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """מחיקת קובץ אחרי אישור - תומך בגישה ישירה וגישה דרך cache"""
    query = update.callback_query
    await query.answer()

    try:
        # זיהוי סוג הקריאה
        if query.data.startswith("confirm_del_direct_"):
            file_name = query.data.replace("confirm_del_direct_", "")
            user_id = query.from_user.id

        else:  # confirm_del_X - גישה דרך cache
            file_index = query.data.split("_")[2]  # confirm_del_X
            files_cache = context.user_data.get("files_cache", {})
            file_data = files_cache.get(file_index)

            if not file_data:
                await query.edit_message_text("⚠️ הקובץ לא נמצא")
                return ConversationHandler.END

            file_name = file_data.get("file_name", "קובץ ללא שם")
            user_id = query.from_user.id

        # מחיקה מהמסד
        from database import db

        success = db.delete_file(user_id, file_name)

        if success:
            # הסרה מהcache אם זו גישה דרך cache
            if not query.data.startswith("confirm_del_direct_"):
                file_index = query.data.split("_")[2]
                if file_index in context.user_data.get("files_cache", {}):
                    del context.user_data["files_cache"][file_index]

            await query.edit_message_text(
                f"✅ הקובץ `{file_name}` נמחק בהצלחה!", parse_mode="Markdown"
            )

            # חזרה לרשימת הקבצים אחרי 2 שניות
            await asyncio.sleep(2)
            return await show_all_files_callback(update, context)
        else:
            await query.edit_message_text(f"❌ שגיאה במחיקת הקובץ `{file_name}`")

    except Exception as e:
        logger.error(f"Error in handle_delete_file: {e}")
        await query.edit_message_text("❌ שגיאה במחיקת הקובץ")

    return ConversationHandler.END


async def handle_file_info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """מציג מידע על הקובץ"""
    query = update.callback_query
    await query.answer()

    try:
        file_index = query.data.split("_")[1]

        files_cache = context.user_data.get("files_cache", {})
        file_data = files_cache.get(file_index)

        if not file_data:
            await query.edit_message_text("⚠️ הקובץ לא נמצא")
            return ConversationHandler.END

        file_name = file_data.get("file_name", "קובץ ללא שם")
        language = file_data.get("programming_language", "לא זוהתה")
        code = file_data.get("code", "")
        created_at = file_data.get("created_at", "לא ידוע")
        updated_at = file_data.get("updated_at", "לא ידוע")
        version = file_data.get("version", 1)

        # חישוב סטטיסטיקות
        lines = len(code.split("\n"))
        chars = len(code)
        words = len(code.split())

        # פורמט תאריכים
        if isinstance(created_at, str):
            created_str = created_at[:19] if len(created_at) > 19 else created_at
        else:
            created_str = str(created_at)[:19] if created_at else "לא ידוע"

        if isinstance(updated_at, str):
            updated_str = updated_at[:19] if len(updated_at) > 19 else updated_at
        else:
            updated_str = str(updated_at)[:19] if updated_at else "לא ידוע"

        # כפתור חזרה
        keyboard = [
            [InlineKeyboardButton("🔙 חזרה", callback_data=f"file_{file_index}")]
        ]
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
            info_text, reply_markup=reply_markup, parse_mode="Markdown"
        )

    except Exception as e:
        logger.error(f"Error in handle_file_info: {e}")
        await query.edit_message_text("❌ שגיאה בהצגת מידע הקובץ")

    reporter.report_activity(update.effective_user.id)
    return ConversationHandler.END


async def show_all_files_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
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
                file_name = file.get("file_name", "קובץ ללא שם")
                language = file.get("programming_language", "text")

                # עדכון cache
                if "files_cache" not in context.user_data:
                    context.user_data["files_cache"] = {}
                context.user_data["files_cache"][str(i)] = file

                emoji = get_file_emoji(language)
                button_text = f"{emoji} {file_name}"

                keyboard.append(
                    [InlineKeyboardButton(button_text, callback_data=f"file_{i}")]
                )

                if i >= 9:
                    break

            keyboard.append(
                [InlineKeyboardButton("🔙 תפריט ראשי", callback_data="main")]
            )

            files_count_text = (
                f"({len(files)} קבצים)"
                if len(files) <= 10
                else f"({len(files)} קבצים - מציג 10 ראשונים)"
            )
            text = f"📚 *הקבצים השמורים שלך* {files_count_text}\n\nלחץ על קובץ כדי לראות אפשרויות:"

        reply_markup = InlineKeyboardMarkup(keyboard)

        if query:
            await query.edit_message_text(
                text, reply_markup=reply_markup, parse_mode="Markdown"
            )
        else:
            # במקרה של קריאה רגילה (לא callback)
            await update.message.reply_text(
                text, reply_markup=reply_markup, parse_mode="Markdown"
            )

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
    """ביטול התהליך הנוכחי"""
    context.user_data.clear()

    await update.message.reply_text(
        "❌ התהליך בוטל.",
        reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
    )
    return ConversationHandler.END


def get_save_conversation_handler(db: DatabaseManager) -> ConversationHandler:
    """Creates and returns the ConversationHandler for saving files."""
    logger.info("יוצר ConversationHandler...")

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
                CallbackQueryHandler(handle_duplicate_callback),
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
            CallbackQueryHandler(handle_cancel_edit, pattern="^cancel_edit$"),
        ],
        allow_reentry=True,
        per_message=False,
    )
