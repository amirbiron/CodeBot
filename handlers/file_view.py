import logging
import re
from io import BytesIO
from datetime import datetime, timezone
from typing import List, Optional
from html import escape as html_escape

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes, ConversationHandler

from handlers.states import EDIT_CODE, EDIT_NAME

logger = logging.getLogger(__name__)


def _get_main_keyboard():
    try:
        from conversation_handlers import MAIN_KEYBOARD
        return MAIN_KEYBOARD
    except Exception:
        return [[]]


async def handle_file_menu(update, context: ContextTypes.DEFAULT_TYPE) -> int:
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
        keyboard = [
            [
                InlineKeyboardButton("👁️ הצג קוד", callback_data=f"view_{file_index}"),
                InlineKeyboardButton("✏️ ערוך", callback_data=f"edit_code_{file_index}"),
            ],
            [
                InlineKeyboardButton("📝 שנה שם", callback_data=f"edit_name_{file_index}"),
                InlineKeyboardButton("📝 ערוך הערה", callback_data=f"edit_note_{file_index}"),
            ],
            [
                InlineKeyboardButton("📚 היסטוריה", callback_data=f"versions_{file_index}"),
                InlineKeyboardButton("📥 הורד", callback_data=f"dl_{file_index}"),
            ],
            [
                InlineKeyboardButton("🔄 שכפול", callback_data=f"clone_{file_index}"),
                InlineKeyboardButton("🗑️ מחק", callback_data=f"del_{file_index}"),
            ],
        ]
        last_page = context.user_data.get('files_last_page')
        origin = context.user_data.get('files_origin') or {}
        if origin.get('type') == 'by_repo' and origin.get('tag'):
            back_cb = f"by_repo:{origin.get('tag')}"
        elif origin.get('type') == 'regular':
            back_cb = f"files_page_{last_page}" if last_page else "show_regular_files"
        else:
            back_cb = f"files_page_{last_page}" if last_page else "files"
        keyboard.append([InlineKeyboardButton("🔙 חזרה לרשימה", callback_data=back_cb)])
        reply_markup = InlineKeyboardMarkup(keyboard)
        note = file_data.get('description') or ''
        note_line = f"\n📝 הערה: {html_escape(note)}\n\n" if note else "\n📝 הערה: —\n\n"
        await query.edit_message_text(
            f"🎯 *מרכז בקרה מתקדם*\n\n"
            f"📄 **קובץ:** `{file_name}`\n"
            f"🧠 **שפה:** {language}{note_line}"
            f"🎮 בחר פעולה מתקדמת:",
            reply_markup=reply_markup,
            parse_mode='Markdown',
        )
    except Exception as e:
        logger.error(f"Error in handle_file_menu: {e}")
        await query.edit_message_text("💥 שגיאה במרכז הבקרה המתקדם")
    return ConversationHandler.END


async def handle_view_file(update, context: ContextTypes.DEFAULT_TYPE) -> int:
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
        max_length = 3500
        code_preview = code[:max_length] + "\n\n... [📱 הצג המשך - השתמש בהורדה לקובץ המלא]" if len(code) > max_length else code
        last_page = context.user_data.get('files_last_page')
        origin = context.user_data.get('files_origin') or {}
        if origin.get('type') == 'by_repo' and origin.get('tag'):
            back_cb = f"by_repo:{origin.get('tag')}"
        elif origin.get('type') == 'regular':
            back_cb = f"files_page_{last_page}" if last_page else "show_regular_files"
        else:
            back_cb = f"files_page_{last_page}" if last_page else f"file_{file_index}"
        keyboard = [
            [
                InlineKeyboardButton("✏️ ערוך קוד", callback_data=f"edit_code_{file_index}"),
                InlineKeyboardButton("📝 ערוך שם", callback_data=f"edit_name_{file_index}"),
            ],
            [
                InlineKeyboardButton("📝 ערוך הערה", callback_data=f"edit_note_{file_index}"),
                InlineKeyboardButton("📚 היסטוריה", callback_data=f"versions_{file_index}"),
            ],
            [
                InlineKeyboardButton("📥 הורד", callback_data=f"dl_{file_index}"),
                InlineKeyboardButton("🔄 שכפול", callback_data=f"clone_{file_index}"),
            ],
            [InlineKeyboardButton("🔙 חזרה", callback_data=back_cb)],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        note = file_data.get('description') or ''
        note_line = f"\n📝 הערה: {html_escape(note)}\n" if note else "\n📝 הערה: —\n"
        await query.edit_message_text(
            f"📄 *{file_name}* ({language}) - גרסה {version}{note_line}\n"
            f"```{language}\n{code_preview}\n```",
            reply_markup=reply_markup,
            parse_mode='Markdown',
        )
    except Exception as e:
        logger.error(f"Error in handle_view_file: {e}")
        await query.edit_message_text("❌ שגיאה בהצגת הקוד המתקדם")
    return ConversationHandler.END


async def handle_edit_code(update, context: ContextTypes.DEFAULT_TYPE) -> int:
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
            f"📝 שלח את הקוד החדש והמעודכן:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 חזרה", callback_data=f"file_{file_index}")]]),
            parse_mode='Markdown',
        )
        return EDIT_CODE
    except Exception as e:
        logger.error(f"Error in handle_edit_code: {e}")
        await query.edit_message_text("❌ שגיאה בהתחלת עריכה\n\n🔄 אנא נסה שוב או חזור לתפריט הראשי\n📞 אם הבעיה נמשכת, פנה לתמיכה")
    return ConversationHandler.END


async def receive_new_code(update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if context.user_data.get('editing_note_file'):
        note_text = (update.message.text or '').strip()
        file_name = context.user_data.pop('editing_note_file')
        user_id = update.effective_user.id
        try:
            from database import db, CodeSnippet
            doc = db.get_latest_version(user_id, file_name)
            if not doc:
                await update.message.reply_text("❌ הקובץ לא נמצא לעדכון הערה")
                return ConversationHandler.END
            snippet = CodeSnippet(
                user_id=user_id,
                file_name=file_name,
                code=doc.get('code', ''),
                programming_language=doc.get('programming_language', 'text'),
                description=("" if note_text.lower() == 'מחק' else note_text)[:280],
            )
            ok = db.save_code_snippet(snippet)
            if ok:
                await update.message.reply_text(
                    "✅ הערה עודכנה בהצלחה!",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 חזרה", callback_data=f"view_direct_{file_name}")]]),
                )
            else:
                await update.message.reply_text("❌ שגיאה בעדכון ההערה")
        except Exception as e:
            logger.error(f"Error updating note: {e}")
            await update.message.reply_text("❌ שגיאה בעדכון ההערה")
        return ConversationHandler.END

    new_code = update.message.text
    editing_large_file = context.user_data.get('editing_large_file')
    if editing_large_file:
        try:
            user_id = update.effective_user.id
            file_name = editing_large_file['file_name']
            from utils import detect_language_from_filename
            language = detect_language_from_filename(file_name)
            from database import LargeFile, db
            updated_file = LargeFile(
                user_id=user_id,
                file_name=file_name,
                content=new_code,
                programming_language=language,
                file_size=len(new_code.encode('utf-8')),
                lines_count=len(new_code.split('\n')),
            )
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
                    parse_mode='Markdown',
                )
                context.user_data.pop('editing_large_file', None)
            else:
                await update.message.reply_text("❌ שגיאה בעדכון הקובץ הגדול")
            return ConversationHandler.END
        except Exception as e:
            logger.error(f"Error updating large file: {e}")
            await update.message.reply_text("❌ שגיאה בעדכון הקובץ")
            return ConversationHandler.END

    file_data = context.user_data.get('editing_file_data')
    if not file_data:
        await update.message.reply_text("❌ שגיאה בנתוני הקובץ")
        return ConversationHandler.END
    try:
        user_id = update.effective_user.id
        file_name = context.user_data.get('editing_file_name') or file_data.get('file_name')
        editing_file_index = context.user_data.get('editing_file_index')
        files_cache = context.user_data.get('files_cache')
        from code_processor import code_processor
        is_valid, cleaned_code, error_message = code_processor.validate_code_input(new_code, file_name, user_id)
        if not is_valid:
            await update.message.reply_text(
                f"❌ שגיאה בקלט הקוד:\n{error_message}\n\n"
                f"💡 אנא וודא שהקוד תקין ונסה שוב.",
                reply_markup=ReplyKeyboardMarkup(_get_main_keyboard(), resize_keyboard=True),
            )
            return EDIT_CODE
        detected_language = code_processor.detect_language(cleaned_code, file_name)
        from database import db
        success = db.save_file(user_id, file_name, cleaned_code, detected_language)
        if success:
            keyboard = [
                [
                    InlineKeyboardButton("👁️ הצג קוד מעודכן", callback_data=f"view_direct_{file_name}"),
                    InlineKeyboardButton("📚 היסטוריה", callback_data=f"versions_file_{file_name}"),
                ],
                [
                    InlineKeyboardButton("📥 הורד", callback_data=f"download_direct_{file_name}"),
                    InlineKeyboardButton("🔙 לרשימה", callback_data="files"),
                ],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            updated_file = db.get_latest_version(user_id, file_name)
            version_num = updated_file.get('version', 1) if updated_file else 1
            try:
                if files_cache is not None and editing_file_index is not None and str(editing_file_index) in files_cache:
                    entry = files_cache[str(editing_file_index)]
                    entry['code'] = cleaned_code
                    entry['programming_language'] = detected_language
                    entry['version'] = version_num
                    entry['updated_at'] = datetime.now(timezone.utc)
            except Exception as e:
                logger.warning(f"Failed to refresh files_cache after edit: {e}")
            await update.message.reply_text(
                f"✅ *הקובץ עודכן בהצלחה!*\n\n"
                f"📄 **קובץ:** `{file_name}`\n"
                f"🧠 **שפה:** {detected_language}\n"
                f"📝 **גרסה:** {version_num} (עודכן מהגרסה הקודמת)\n"
                f"💾 **הקובץ הקיים עודכן עם השינויים החדשים!**",
                reply_markup=reply_markup,
                parse_mode='Markdown',
            )
        else:
            await update.message.reply_text(
                "❌ שגיאה בעדכון הקוד",
                reply_markup=ReplyKeyboardMarkup(_get_main_keyboard(), resize_keyboard=True),
            )
    except Exception as e:
        logger.error(f"Error updating code: {e}")
        await update.message.reply_text(
            "❌ שגיאה בעדכון הקוד\n\n📝 **פרטים:** פרטי השגיאה לא זמינים\n🔄 אנא נסה שוב או פנה לתמיכה\n🏠 חזרה לתפריט הראשי",
            reply_markup=ReplyKeyboardMarkup(_get_main_keyboard(), resize_keyboard=True),
            parse_mode='Markdown',
        )
    preserved_cache = context.user_data.get('files_cache')
    context.user_data.clear()
    if preserved_cache is not None:
        context.user_data['files_cache'] = preserved_cache
    return ConversationHandler.END


async def handle_edit_name(update, context: ContextTypes.DEFAULT_TYPE) -> int:
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
            f"✏️ שלח שם חדש לקובץ:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 חזרה", callback_data=f"file_{file_index}")]]),
            parse_mode='Markdown',
        )
        return EDIT_NAME
    except Exception as e:
        logger.error(f"Error in handle_edit_name: {e}")
        await query.edit_message_text("❌ שגיאה בהתחלת עריכת שם")
    return ConversationHandler.END


async def handle_edit_note(update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    try:
        file_index = query.data.split('_')[2]
        files_cache = context.user_data.get('files_cache', {})
        file_data = files_cache.get(file_index)
        if not file_data:
            await query.edit_message_text("❌ שגיאה בזיהוי הקובץ")
            return ConversationHandler.END
        file_name = file_data.get('file_name', 'קובץ')
        current_note = file_data.get('description', '') or '—'
        context.user_data['editing_note_file'] = file_name
        await query.edit_message_text(
            f"📝 *עריכת הערה לקובץ*\n\n"
            f"📄 **שם:** `{file_name}`\n"
            f"🔎 **הערה נוכחית:** {html_escape(current_note)}\n\n"
            f"✏️ שלח/י הערה חדשה (או 'מחק' כדי להסיר)",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 חזרה", callback_data=f"file_{file_index}")]]),
            parse_mode='Markdown',
        )
        return EDIT_CODE
    except Exception as e:
        logger.error(f"Error in handle_edit_note: {e}")
        await query.edit_message_text("❌ שגיאה בהתחלת עריכת הערה")
    return ConversationHandler.END


async def receive_new_name(update, context: ContextTypes.DEFAULT_TYPE) -> int:
    new_name = update.message.text.strip()
    file_data = context.user_data.get('editing_file_data')
    if not file_data:
        await update.message.reply_text("❌ שגיאה בנתוני הקובץ")
        return ConversationHandler.END
    if not re.match(r'^[\w\.\-\_]+\.[a-zA-Z0-9]+$', new_name):
        await update.message.reply_text(
            "🤔 השם נראה קצת מוזר...\n"
            "💡 נסה שם כמו: `script.py` או `index.html`\n"
            "✅ אותיות, מספרים, נקודות וקווים מותרים!",
        )
        return EDIT_NAME
    try:
        user_id = update.effective_user.id
        old_name = context.user_data.get('editing_file_name') or file_data.get('file_name')
        from database import db
        success = db.rename_file(user_id, old_name, new_name)
        if success:
            keyboard = [
                [
                    InlineKeyboardButton("👁️ הצג קוד", callback_data=f"view_direct_{new_name}"),
                    InlineKeyboardButton("📚 היסטוריה", callback_data=f"versions_file_{new_name}"),
                ],
                [
                    InlineKeyboardButton("📥 הורד", callback_data=f"download_direct_{new_name}"),
                    InlineKeyboardButton("🔙 לרשימה", callback_data="files"),
                ],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(
                f"✅ *שם הקובץ שונה בהצלחה!*\n\n"
                f"📄 **שם ישן:** `{old_name}`\n"
                f"📄 **שם חדש:** `{new_name}`\n"
                f"🎉 **הכל מעודכן במערכת!**",
                reply_markup=reply_markup,
                parse_mode='Markdown',
            )
        else:
            await update.message.reply_text(
                "❌ שגיאה בשינוי השם",
                reply_markup=ReplyKeyboardMarkup(_get_main_keyboard(), resize_keyboard=True),
            )
    except Exception as e:
        logger.error(f"Error renaming file: {e}")
        await update.message.reply_text(
            "❌ שגיאה בשינוי השם",
            reply_markup=ReplyKeyboardMarkup(_get_main_keyboard(), resize_keyboard=True),
        )
    context.user_data.clear()
    return ConversationHandler.END


async def handle_versions_history(update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    try:
        data = query.data
        file_index: Optional[str] = None
        files_cache = context.user_data.get('files_cache', {})
        if data.startswith("versions_file_"):
            file_name = data.replace("versions_file_", "", 1)
        else:
            file_index = data.split('_')[1]
            file_data = files_cache.get(file_index)
            if not file_data:
                await query.edit_message_text("❌ שגיאה בזיהוי הקובץ")
                return ConversationHandler.END
            file_name = file_data.get('file_name')
        user_id = update.effective_user.id
        from database import db
        versions = db.get_all_versions(user_id, file_name)
        if not versions:
            await query.edit_message_text("📚 אין היסטוריית גרסאות לקובץ זה")
            return ConversationHandler.END
        latest_version_num = versions[0].get('version') if versions and isinstance(versions[0], dict) else None
        history_text = f"📚 *היסטוריית גרסאות - {file_name}*\n\n"
        keyboard: List[List[InlineKeyboardButton]] = []
        for i, version in enumerate(versions[:5]):
            created_at = version.get('created_at', 'לא ידוע')
            version_num = version.get('version', i + 1)
            code_length = len(version.get('code', ''))
            history_text += f"🔹 **גרסה {version_num}**\n"
            history_text += f"   📅 {created_at}\n"
            history_text += f"   📏 {code_length:,} תווים\n\n"
            if latest_version_num is not None and version_num == latest_version_num:
                keyboard.append([
                    InlineKeyboardButton(
                        f"👁 הצג גרסה {version_num}", callback_data=f"view_version_{version_num}_{file_name}"
                    )
                ])
            else:
                keyboard.append([
                    InlineKeyboardButton(
                        f"👁 הצג גרסה {version_num}", callback_data=f"view_version_{version_num}_{file_name}"
                    ),
                    InlineKeyboardButton(
                        f"↩️ שחזר לגרסה {version_num}", callback_data=f"revert_version_{version_num}_{file_name}"
                    ),
                ])
        if file_index is not None:
            keyboard.append([InlineKeyboardButton("🔙 חזרה", callback_data=f"file_{file_index}")])
        else:
            keyboard.append([InlineKeyboardButton("🔙 חזרה", callback_data=f"view_direct_{file_name}")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(history_text, reply_markup=reply_markup, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Error in handle_versions_history: {e}")
        await query.edit_message_text("❌ שגיאה בהצגת היסטוריה")
    return ConversationHandler.END


async def handle_download_file(update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    try:
        data = query.data
        files_cache = context.user_data.get('files_cache', {})
        file_name: Optional[str] = None
        code: str = ''
        if data.startswith('dl_'):
            file_index = data.split('_')[1]
            file_data = files_cache.get(file_index)
            if not file_data:
                await query.edit_message_text("❌ שגיאה בזיהוי הקובץ")
                return ConversationHandler.END
            file_name = file_data.get('file_name', 'file.txt')
            code = file_data.get('code', '')
        elif data.startswith('download_direct_'):
            file_name = data.replace('download_direct_', '', 1)
            from database import db
            user_id = update.effective_user.id
            latest = db.get_latest_version(user_id, file_name)
            if not latest:
                await query.edit_message_text("❌ לא נמצאה גרסה אחרונה לקובץ")
                return ConversationHandler.END
            code = latest.get('code', '')
        else:
            await query.edit_message_text("❌ בקשת הורדה לא חוקית")
            return ConversationHandler.END
        file_bytes = BytesIO()
        file_bytes.write(code.encode('utf-8'))
        file_bytes.seek(0)
        await query.message.reply_document(
            document=file_bytes,
            filename=file_name,
            caption=f"📥 *הורדת קובץ*\n\n📄 **שם:** `{file_name}`\n📏 **גודל:** {len(code):,} תווים",
        )
        keyboard = []
        if data.startswith('dl_'):
            file_index = data.split('_')[1]
            keyboard.append([InlineKeyboardButton("🔙 חזרה", callback_data=f"file_{file_index}")])
        else:
            keyboard.append([InlineKeyboardButton("🔙 חזרה", callback_data=f"view_direct_{file_name}")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            f"✅ *הקובץ הורד בהצלחה!*\n\n"
            f"📄 **שם:** `{file_name}`",
            reply_markup=reply_markup,
            parse_mode='Markdown',
        )
    except Exception as e:
        logger.error(f"Error in handle_download_file: {e}")
        await query.edit_message_text("❌ שגיאה בהורדת הקובץ")
    return ConversationHandler.END


async def handle_delete_confirmation(update, context: ContextTypes.DEFAULT_TYPE) -> int:
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
        keyboard = [[
            InlineKeyboardButton("✅ כן, מחק", callback_data=f"confirm_del_{file_index}"),
            InlineKeyboardButton("❌ לא, בטל", callback_data=f"file_{file_index}"),
        ]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            f"⚠️ *אישור מחיקה*\n\n"
            f"📄 **קובץ:** `{file_name}`\n\n"
            f"🗑️ האם אתה בטוח שברצונך למחוק את הקובץ?\n"
            f"⚠️ **פעולה זו לא ניתנת לביטול!**",
            reply_markup=reply_markup,
            parse_mode='Markdown',
        )
    except Exception as e:
        logger.error(f"Error in handle_delete_confirmation: {e}")
        await query.edit_message_text("❌ שגיאה באישור מחיקה")
    return ConversationHandler.END


async def handle_delete_file(update, context: ContextTypes.DEFAULT_TYPE) -> int:
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
            keyboard = [[InlineKeyboardButton("🔙 לרשימת קבצים", callback_data="files")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                f"✅ *הקובץ נמחק בהצלחה!*\n\n"
                f"📄 **קובץ שנמחק:** `{file_name}`\n"
                f"🗑️ **הקובץ הוסר לחלוטין מהמערכת**",
                reply_markup=reply_markup,
                parse_mode='Markdown',
            )
        else:
            await query.edit_message_text(f"❌ שגיאה במחיקת הקובץ `{file_name}`")
    except Exception as e:
        logger.error(f"Error in handle_delete_file: {e}")
        await query.edit_message_text("❌ שגיאה במחיקת הקובץ")
    return ConversationHandler.END


async def handle_file_info(update, context: ContextTypes.DEFAULT_TYPE) -> int:
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
        keyboard = [[InlineKeyboardButton("🔙 חזרה", callback_data=f"file_{file_index}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(info_text, reply_markup=reply_markup, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Error in handle_file_info: {e}")
        await query.edit_message_text("❌ שגיאה בהצגת מידע")
    return ConversationHandler.END


async def handle_view_direct_file(update, context: ContextTypes.DEFAULT_TYPE) -> int:
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
        max_length = 3500
        code_preview = code[:max_length] + "\n\n... [📱 הצג המשך - השתמש בהורדה לקובץ המלא]" if len(code) > max_length else code
        keyboard = [
            [
                InlineKeyboardButton("✏️ ערוך קוד", callback_data=f"edit_code_direct_{file_name}"),
                InlineKeyboardButton("📝 ערוך שם", callback_data=f"edit_name_direct_{file_name}"),
            ],
            [
                InlineKeyboardButton("📝 ערוך הערה", callback_data=f"edit_note_direct_{file_name}"),
                InlineKeyboardButton("📚 היסטוריה", callback_data=f"versions_file_{file_name}"),
            ],
            [
                InlineKeyboardButton("📥 הורד", callback_data=f"download_direct_{file_name}"),
                InlineKeyboardButton("🔄 שכפול", callback_data=f"clone_direct_{file_name}"),
            ],
            [InlineKeyboardButton("🔙 לרשימה", callback_data="files")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        note = file_data.get('description') or ''
        note_line = f"\n📝 הערה: {html_escape(note)}\n\n" if note else "\n📝 הערה: —\n\n"
        await query.edit_message_text(
            f"📄 *{file_name}* ({language}) - גרסה {version}{note_line}"
            f"```{language}\n{code_preview}\n```",
            reply_markup=reply_markup,
            parse_mode='Markdown',
        )
    except Exception as e:
        logger.error(f"Error in handle_view_direct_file: {e}")
        await query.edit_message_text("❌ שגיאה בהצגת הקוד המתקדם")
    return ConversationHandler.END


async def handle_edit_code_direct(update, context: ContextTypes.DEFAULT_TYPE) -> int:
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
            f"📝 שלח את הקוד החדש והמעודכן:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 חזרה", callback_data=f"view_direct_{file_name}")]]),
            parse_mode='Markdown',
        )
        return EDIT_CODE
    except Exception as e:
        logger.error(f"Error in handle_edit_code_direct: {e}")
        await query.edit_message_text("❌ שגיאה בהתחלת עריכה")
    return ConversationHandler.END


async def handle_edit_name_direct(update, context: ContextTypes.DEFAULT_TYPE) -> int:
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
            f"✏️ שלח שם חדש לקובץ:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 חזרה", callback_data=f"view_direct_{file_name}")]]),
            parse_mode='Markdown',
        )
        return EDIT_NAME
    except Exception as e:
        logger.error(f"Error in handle_edit_name_direct: {e}")
        await query.edit_message_text("❌ שגיאה בהתחלת עריכת שם")
    return ConversationHandler.END


async def handle_edit_note_direct(update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    try:
        file_name = query.data.replace("edit_note_direct_", "")
        user_id = update.effective_user.id
        from database import db
        file_data = db.get_latest_version(user_id, file_name)
        if not file_data:
            await query.edit_message_text("❌ לא נמצא הקובץ לעריכת הערה")
            return ConversationHandler.END
        current_note = file_data.get('description', '') or '—'
        context.user_data['editing_note_file'] = file_name
        await query.edit_message_text(
            f"📝 *עריכת הערה לקובץ*\n\n"
            f"📄 **שם:** `{file_name}`\n"
            f"🔎 **הערה נוכחית:** {html_escape(current_note)}\n\n"
            f"✏️ שלח/י הערה חדשה (או שלח/י 'מחק' כדי להסיר).",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 חזרה", callback_data=f"view_direct_{file_name}")]]),
            parse_mode='Markdown',
        )
        return EDIT_CODE
    except Exception as e:
        logger.exception("Error in handle_edit_note_direct: %s", e)
        await query.edit_message_text("❌ שגיאה בעריכת הערה")
    return ConversationHandler.END

