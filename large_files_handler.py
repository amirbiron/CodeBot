"""
טיפול בקבצים גדולים עם ממשק כפתורים מתקדם
Large Files Handler with Advanced Button Interface
"""

import logging
from io import BytesIO
from typing import Dict, List, Optional, Tuple

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputFile, Update
from telegram.ext import ContextTypes

from database import LargeFile, db
from utils import detect_language_from_filename, get_language_emoji

logger = logging.getLogger(__name__)


class LargeFilesHandler:
    """מנהל קבצים גדולים עם ממשק מתקדם"""

    def __init__(self):
        self.files_per_page = 8
        self.preview_max_chars = 3500

    async def show_large_files_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 1) -> None:
        """מציג תפריט קבצים גדולים עם ניווט בין עמודים"""
        user_id = update.effective_user.id

        # קבלת קבצים לעמוד הנוכחי
        files, total_count = db.get_user_large_files(user_id, page, self.files_per_page)

        if not files and page == 1:
            # אין קבצים בכלל
            keyboard = [[InlineKeyboardButton("🏠 תפריט ראשי", callback_data="main")]]
            reply_markup = InlineKeyboardMarkup(keyboard)

            text = (
                "📂 **אין לך קבצים גדולים שמורים**\n\n"
                "💡 **איך לשמור קבצים גדולים?**\n"
                "• שלח קובץ טקסט/קוד לבוט\n"
                "• הבוט ישמור אותו אוטומטית\n"
                "• תמיכה עד 10MB!"
            )

            if hasattr(update, "callback_query") and update.callback_query:
                await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
            else:
                await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")
            return

        # חישוב מספר עמודים
        total_pages = (total_count + self.files_per_page - 1) // self.files_per_page

        # יצירת כפתורים לקבצים
        keyboard = []
        for i, file in enumerate(files):
            file_name = file.get("file_name", "קובץ ללא שם")
            language = file.get("programming_language", "text")
            file_size = file.get("file_size", 0)

            # שמירת מידע על הקובץ בקאש
            file_index = f"lf_{page}_{i}"
            if "large_files_cache" not in context.user_data:
                context.user_data["large_files_cache"] = {}
            context.user_data["large_files_cache"][file_index] = file

            # יצירת כפתור עם אימוג'י ומידע
            emoji = get_language_emoji(language)
            size_kb = file_size / 1024
            button_text = f"{emoji} {file_name} ({size_kb:.1f}KB)"

            keyboard.append([InlineKeyboardButton(button_text, callback_data=f"large_file_{file_index}")])

        # כפתורי ניווט
        nav_buttons = []
        if page > 1:
            nav_buttons.append(InlineKeyboardButton("⬅️ הקודם", callback_data=f"lf_page_{page-1}"))

        nav_buttons.append(InlineKeyboardButton(f"📄 {page}/{total_pages}", callback_data="noop"))

        if page < total_pages:
            nav_buttons.append(InlineKeyboardButton("➡️ הבא", callback_data=f"lf_page_{page+1}"))

        if nav_buttons:
            keyboard.append(nav_buttons)

        # כפתורים נוספים
        keyboard.extend(
            [
                [InlineKeyboardButton("🔄 רענן", callback_data=f"lf_page_{page}")],
                [InlineKeyboardButton("🏠 תפריט ראשי", callback_data="main")],
            ]
        )

        reply_markup = InlineKeyboardMarkup(keyboard)

        # טקסט כותרת
        text = (
            f"📚 **הקבצים הגדולים שלך**\n"
            f'📊 סה"כ: {total_count} קבצים\n'
            f"📄 עמוד {page} מתוך {total_pages}\n\n"
            "✨ לחץ על קובץ לצפייה וניהול:"
        )

        if hasattr(update, "callback_query") and update.callback_query:
            await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
        else:
            await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")

    async def handle_file_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """טיפול בבחירת קובץ גדול"""
        query = update.callback_query
        await query.answer()

        # קבלת מידע על הקובץ
        file_index = query.data.replace("large_file_", "")
        large_files_cache = context.user_data.get("large_files_cache", {})
        file_data = large_files_cache.get(file_index)

        if not file_data:
            await query.edit_message_text("❌ שגיאה בזיהוי הקובץ")
            return

        file_name = file_data.get("file_name", "קובץ ללא שם")
        language = file_data.get("programming_language", "text")
        file_size = file_data.get("file_size", 0)
        lines_count = file_data.get("lines_count", 0)
        created_at = file_data.get("created_at", "לא ידוע")

        # כפתורי פעולות
        keyboard = [
            [
                InlineKeyboardButton("👁️ צפה בקובץ", callback_data=f"lf_view_{file_index}"),
                InlineKeyboardButton("📥 הורד", callback_data=f"lf_download_{file_index}"),
            ],
            [
                InlineKeyboardButton("📝 ערוך", callback_data=f"lf_edit_{file_index}"),
                InlineKeyboardButton("🗑️ מחק", callback_data=f"lf_delete_{file_index}"),
            ],
            [InlineKeyboardButton("📊 מידע מפורט", callback_data=f"lf_info_{file_index}")],
            [InlineKeyboardButton("🔙 חזרה לרשימה", callback_data="show_large_files")],
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)

        # הכנת טקסט עם מידע על הקובץ
        emoji = get_language_emoji(language)
        size_kb = file_size / 1024

        text = (
            f"📄 **{file_name}**\n\n"
            f"{emoji} **שפה:** {language}\n"
            f"💾 **גודל:** {size_kb:.1f}KB ({file_size:,} בתים)\n"
            f"📏 **שורות:** {lines_count:,}\n"
            f"📅 **נוצר:** {created_at}\n\n"
            "🎯 בחר פעולה:"
        )

        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")

    async def view_large_file(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """הצגת קובץ גדול - תצוגה מקדימה או שליחה כקובץ"""
        query = update.callback_query
        await query.answer()

        # קבלת מידע על הקובץ
        file_index = query.data.replace("lf_view_", "")
        large_files_cache = context.user_data.get("large_files_cache", {})
        file_data = large_files_cache.get(file_index)

        if not file_data:
            await query.edit_message_text("❌ שגיאה בזיהוי הקובץ")
            return

        file_name = file_data.get("file_name", "קובץ ללא שם")
        content = file_data.get("content", "")
        language = file_data.get("programming_language", "text")

        # בדיקה אם הקובץ קטן מספיק להצגה בצ'אט
        if len(content) <= self.preview_max_chars:
            # הצגה ישירה בצ'אט
            formatted_content = f"```{language}\n{content}\n```"

            keyboard = [[InlineKeyboardButton("🔙 חזרה", callback_data=f"large_file_{file_index}")]]
            reply_markup = InlineKeyboardMarkup(keyboard)

            try:
                await query.edit_message_text(
                    f"📄 **{file_name}**\n\n{formatted_content}", reply_markup=reply_markup, parse_mode="Markdown"
                )
            except Exception as e:
                # אם יש בעיה עם Markdown, ננסה בלי
                await query.edit_message_text(f"📄 {file_name}\n\n{content}", reply_markup=reply_markup)
        else:
            # הקובץ גדול מדי - נציג תצוגה מקדימה ונשלח כקובץ
            preview = content[: self.preview_max_chars] + "\n\n... [המשך הקובץ נשלח כקובץ מצורף]"
            formatted_preview = f"```{language}\n{preview}\n```"

            keyboard = [[InlineKeyboardButton("🔙 חזרה", callback_data=f"large_file_{file_index}")]]
            reply_markup = InlineKeyboardMarkup(keyboard)

            # שליחת תצוגה מקדימה
            try:
                await query.edit_message_text(
                    f"📄 **{file_name}** (תצוגה מקדימה)\n\n{formatted_preview}",
                    reply_markup=reply_markup,
                    parse_mode="Markdown",
                )
            except:
                await query.edit_message_text(f"📄 {file_name} (תצוגה מקדימה)\n\n{preview}", reply_markup=reply_markup)

            # שליחת הקובץ המלא
            file_bytes = BytesIO(content.encode("utf-8"))
            file_bytes.name = file_name

            await query.message.reply_document(
                document=file_bytes, caption=f"📄 הקובץ המלא: **{file_name}**", parse_mode="Markdown"
            )

    async def download_large_file(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """הורדת קובץ גדול"""
        query = update.callback_query
        await query.answer("📥 מכין את הקובץ להורדה...")

        # קבלת מידע על הקובץ
        file_index = query.data.replace("lf_download_", "")
        large_files_cache = context.user_data.get("large_files_cache", {})
        file_data = large_files_cache.get(file_index)

        if not file_data:
            await query.edit_message_text("❌ שגיאה בזיהוי הקובץ")
            return

        file_name = file_data.get("file_name", "קובץ ללא שם")
        content = file_data.get("content", "")
        language = file_data.get("programming_language", "text")

        # יצירת קובץ להורדה
        file_bytes = BytesIO(content.encode("utf-8"))
        file_bytes.name = file_name

        # שליחת הקובץ
        await query.message.reply_document(
            document=file_bytes,
            caption=f"📥 **{file_name}**\n🔤 שפה: {language}\n💾 גודל: {len(content):,} תווים",
            parse_mode="Markdown",
        )

        # חזרה לתפריט הקובץ
        await self.handle_file_selection(update, context)

    async def delete_large_file_confirm(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """אישור מחיקת קובץ גדול"""
        query = update.callback_query
        await query.answer()

        file_index = query.data.replace("lf_delete_", "")
        large_files_cache = context.user_data.get("large_files_cache", {})
        file_data = large_files_cache.get(file_index)

        if not file_data:
            await query.edit_message_text("❌ שגיאה בזיהוי הקובץ")
            return

        file_name = file_data.get("file_name", "קובץ ללא שם")

        keyboard = [
            [
                InlineKeyboardButton("✅ כן, מחק", callback_data=f"lf_confirm_delete_{file_index}"),
                InlineKeyboardButton("❌ ביטול", callback_data=f"large_file_{file_index}"),
            ]
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(
            f"⚠️ **אזהרה**\n\n"
            f"האם אתה בטוח שברצונך למחוק את הקובץ:\n"
            f"📄 `{file_name}`?\n\n"
            f"⚡ הפעולה לא ניתנת לביטול!",
            reply_markup=reply_markup,
            parse_mode="Markdown",
        )

    async def delete_large_file(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """מחיקת קובץ גדול"""
        query = update.callback_query
        await query.answer()

        file_index = query.data.replace("lf_confirm_delete_", "")
        large_files_cache = context.user_data.get("large_files_cache", {})
        file_data = large_files_cache.get(file_index)

        if not file_data:
            await query.edit_message_text("❌ שגיאה בזיהוי הקובץ")
            return

        user_id = update.effective_user.id
        file_name = file_data.get("file_name", "קובץ ללא שם")

        # מחיקת הקובץ
        success = db.delete_large_file(user_id, file_name)

        if success:
            # ניקוי הקאש
            if file_index in large_files_cache:
                del large_files_cache[file_index]

            keyboard = [[InlineKeyboardButton("🔙 חזרה לרשימה", callback_data="show_large_files")]]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await query.edit_message_text(
                f"✅ **הקובץ נמחק בהצלחה!**\n\n" f"📄 קובץ שנמחק: `{file_name}`",
                reply_markup=reply_markup,
                parse_mode="Markdown",
            )
        else:
            await query.edit_message_text("❌ שגיאה במחיקת הקובץ")

    async def show_file_info(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """הצגת מידע מפורט על קובץ גדול"""
        query = update.callback_query
        await query.answer()

        file_index = query.data.replace("lf_info_", "")
        large_files_cache = context.user_data.get("large_files_cache", {})
        file_data = large_files_cache.get(file_index)

        if not file_data:
            await query.edit_message_text("❌ שגיאה בזיהוי הקובץ")
            return

        file_name = file_data.get("file_name", "קובץ ללא שם")
        content = file_data.get("content", "")
        language = file_data.get("programming_language", "text")
        file_size = file_data.get("file_size", 0)
        lines_count = file_data.get("lines_count", 0)
        created_at = file_data.get("created_at", "לא ידוע")
        updated_at = file_data.get("updated_at", "לא ידוע")
        tags = file_data.get("tags", [])

        # חישוב סטטיסטיקות נוספות
        words_count = len(content.split())
        avg_line_length = len(content) // lines_count if lines_count > 0 else 0

        # הכנת טקסט מידע
        emoji = get_language_emoji(language)
        size_kb = file_size / 1024
        size_mb = size_kb / 1024

        text = (
            f"📊 **מידע מפורט על הקובץ**\n\n"
            f"📄 **שם:** `{file_name}`\n"
            f"{emoji} **שפה:** {language}\n"
            f"💾 **גודל:** {size_kb:.1f}KB ({size_mb:.2f}MB)\n"
            f"📏 **שורות:** {lines_count:,}\n"
            f"📝 **מילים:** {words_count:,}\n"
            f"🔤 **תווים:** {len(content):,}\n"
            f"📐 **אורך שורה ממוצע:** {avg_line_length} תווים\n"
            f"📅 **נוצר:** {created_at}\n"
            f"🔄 **עודכן:** {updated_at}\n"
        )

        if tags:
            text += f"🏷️ **תגיות:** {', '.join(tags)}\n"

        keyboard = [[InlineKeyboardButton("🔙 חזרה", callback_data=f"large_file_{file_index}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")

    async def edit_large_file(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """התחלת תהליך עריכת קובץ גדול"""
        query = update.callback_query
        await query.answer()

        file_index = query.data.replace("lf_edit_", "")
        large_files_cache = context.user_data.get("large_files_cache", {})
        file_data = large_files_cache.get(file_index)

        if not file_data:
            await query.edit_message_text("❌ שגיאה בזיהוי הקובץ")
            return

        file_name = file_data.get("file_name", "קובץ ללא שם")

        # שמירת מידע על הקובץ לעריכה
        context.user_data["editing_large_file"] = {
            "file_index": file_index,
            "file_name": file_name,
            "file_data": file_data,
        }

        keyboard = [[InlineKeyboardButton("❌ ביטול", callback_data=f"large_file_{file_index}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(
            f"✏️ **עריכת קובץ גדול**\n\n"
            f"📄 קובץ: `{file_name}`\n\n"
            f"⚠️ **שים לב:** עקב גודל הקובץ, העריכה תחליף את כל התוכן.\n"
            f"📝 שלח את התוכן החדש המלא של הקובץ:",
            reply_markup=reply_markup,
            parse_mode="Markdown",
        )

        # החזרת מצב שיחה לעריכה
        from conversation_handlers import EDIT_CODE

        return EDIT_CODE


# יצירת instance גלובלי
large_files_handler = LargeFilesHandler()
