"""
טיפול בקבצים גדולים עם ממשק כפתורים מתקדם
Large Files Handler with Advanced Button Interface
"""

import logging
from io import BytesIO
from typing import Dict, List, Optional, Tuple

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputFile,
    Update
)
from telegram.ext import ContextTypes

from src.infrastructure.composition import get_files_facade
from utils import get_language_emoji, TextUtils

logger = logging.getLogger(__name__)

class LargeFilesHandler:
    """מנהל קבצים גדולים עם ממשק מתקדם"""
    
    def __init__(self):
        self.files_per_page = 8
        self.preview_max_chars = 3500

    def _facade(self):
        """גישה בטוחה ל-FilesFacade (ללא תלות ישירה ב-database מתוך handlers)."""
        try:
            return get_files_facade()
        except Exception:
            return None

    def _fetch_full_large_file_content(self, user_id: int, file_data: Dict) -> Tuple[str, str]:
        """
        מחזיר (content, language) ע"י שליפה מפורשת מה-DB כאשר הרשימה נטענה עם Smart Projection
        (כלומר ללא השדה content).

        חשוב: יש כאן בדיקת בעלות מינימלית כאשר השליפה נעשית לפי _id.
        """
        file_name = file_data.get("file_name") or ""
        language = (file_data.get("programming_language") or "text") if isinstance(file_data, dict) else "text"
        content = file_data.get("content") if isinstance(file_data, dict) else ""
        if isinstance(content, str) and content:
            return content, str(language or "text")

        full_doc: Optional[Dict] = None
        facade = self._facade()
        if facade is None:
            raise RuntimeError("FilesFacade unavailable")

        file_id = file_data.get("_id") if isinstance(file_data, dict) else None
        if file_id:
            try:
                doc, is_large = facade.get_user_document_by_id(user_id=user_id, file_id=str(file_id))
                if is_large and isinstance(doc, dict):
                    full_doc = doc
            except Exception:
                logger.error("שליפת מסמך קובץ גדול לפי id נכשלה", exc_info=True)
                raise

        if not full_doc:
            try:
                if file_name:
                    full_doc = facade.get_large_file(user_id, str(file_name))
            except Exception:
                logger.error("שליפת קובץ גדול לפי שם נכשלה", exc_info=True)
                raise

        if isinstance(full_doc, dict):
            new_content = full_doc.get("content") or ""
            new_lang = full_doc.get("programming_language") or language or "text"
            try:
                # רענון הקאש כדי למנוע "ניסיון שני עובד" ולהפוך את זה לדטרמיניסטי
                file_data["content"] = new_content
                if new_lang:
                    file_data["programming_language"] = new_lang
            except Exception:
                pass
            return str(new_content or ""), str(new_lang or "text")

        return "", str(language or "text")
    
    async def show_large_files_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 1) -> None:
        """מציג תפריט קבצים גדולים עם ניווט בין עמודים"""
        user_id = update.effective_user.id
        
        # קבלת קבצים לעמוד הנוכחי
        facade = self._facade()
        if facade is None:
            logger.error("FilesFacade unavailable while listing large files")
            keyboard = [[InlineKeyboardButton("🔙 חזור", callback_data="files")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            text = "❌ לא ניתן לטעון כרגע את רשימת הקבצים הגדולים (בעיה במסד הנתונים)."
            if hasattr(update, 'callback_query') and update.callback_query:
                await update.callback_query.edit_message_text(text, reply_markup=reply_markup)
            else:
                await update.message.reply_text(text, reply_markup=reply_markup)
            return
        try:
            files, total_count = facade.get_user_large_files(user_id, page=page, per_page=self.files_per_page)
        except Exception:
            logger.error("טעינת רשימת קבצים גדולים נכשלה (שגיאת DB)", exc_info=True)
            keyboard = [[InlineKeyboardButton("🔙 חזור", callback_data="files")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            text = "❌ שגיאה במסד הנתונים בעת טעינת הרשימה. נסו שוב עוד רגע."
            if hasattr(update, 'callback_query') and update.callback_query:
                await update.callback_query.edit_message_text(text, reply_markup=reply_markup)
            else:
                await update.message.reply_text(text, reply_markup=reply_markup)
            return
        
        if not files and page == 1:
            # אין קבצים בכלל
            keyboard = [[InlineKeyboardButton("🔙 חזור", callback_data="files")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            text = (
                "📂 **אין לך קבצים גדולים שמורים**\n\n"
                "💡 **איך לשמור קבצים גדולים?**\n"
                "• שלח קובץ טקסט לבוט\n"
                "• הבוט ישמור אותו אוטומטית\n"
                "• תמיכה עד 20MB!"
            )
            
            if hasattr(update, 'callback_query') and update.callback_query:
                await update.callback_query.edit_message_text(
                    text, reply_markup=reply_markup, parse_mode='Markdown'
                )
            else:
                await update.message.reply_text(
                    text, reply_markup=reply_markup, parse_mode='Markdown'
                )
            return
        
        # חישוב מספר עמודים
        total_pages = (total_count + self.files_per_page - 1) // self.files_per_page
        
        # יצירת כפתורים לקבצים
        keyboard = []
        for i, file in enumerate(files):
            file_name = file.get('file_name', 'קובץ ללא שם')
            language = file.get('programming_language', 'text')
            file_size = file.get('file_size', 0)
            
            # שמירת מידע על הקובץ בקאש
            file_index = f"lf_{page}_{i}"
            if 'large_files_cache' not in context.user_data:
                context.user_data['large_files_cache'] = {}
            context.user_data['large_files_cache'][file_index] = file
            
            # יצירת כפתור עם אימוג'י ומידע
            emoji = get_language_emoji(language)
            size_kb = file_size / 1024
            button_text = f"{emoji} {file_name} ({size_kb:.1f}KB)"
            
            # הוסף גם כפתור "שתף קוד" לתפריט מהרשימה (ObjectId מצוי במסמך)
            row = [InlineKeyboardButton(
                button_text,
                callback_data=f"large_file_{file_index}"
            )]
            keyboard.append(row)
        
        # כפתורי ניווט
        nav_buttons = []
        if page > 1:
            nav_buttons.append(InlineKeyboardButton("⬅️ הקודם", callback_data=f"lf_page_{page-1}"))
        
        if total_pages > 1:
            nav_buttons.append(InlineKeyboardButton(f"📄 {page}/{total_pages}", callback_data="noop"))
        
        if page < total_pages:
            nav_buttons.append(InlineKeyboardButton("➡️ הבא", callback_data=f"lf_page_{page+1}"))
        
        if nav_buttons:
            keyboard.append(nav_buttons)
        
        # כפתורים נוספים
        keyboard.extend([
            [InlineKeyboardButton("🔄 רענן", callback_data=f"lf_page_{page}")],
            [InlineKeyboardButton("🔙 חזור", callback_data="files")]
        ])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # טקסט כותרת
        text = (
            f"📚 **הקבצים הגדולים שלך**\n"
            f"📊 סה\"כ: {total_count} קבצים\n"
            f"📄 עמוד {page} מתוך {total_pages}\n\n"
            "✨ לחץ על קובץ לצפייה וניהול:"
        )
        
        if hasattr(update, 'callback_query') and update.callback_query:
            await update.callback_query.edit_message_text(
                text, reply_markup=reply_markup, parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(
                text, reply_markup=reply_markup, parse_mode='Markdown'
            )
    
    async def handle_file_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """טיפול בבחירת קובץ גדול"""
        query = update.callback_query
        await query.answer()
        
        # קבלת מידע על הקובץ
        file_index = query.data.replace("large_file_", "")
        large_files_cache = context.user_data.get('large_files_cache', {})
        file_data = large_files_cache.get(file_index)
        
        if not file_data:
            await query.edit_message_text("❌ שגיאה בזיהוי הקובץ")
            return
        
        file_name = file_data.get('file_name', 'קובץ ללא שם')
        language = file_data.get('programming_language', 'text')
        file_size = file_data.get('file_size', 0)
        lines_count = file_data.get('lines_count', 0)
        created_at = file_data.get('created_at', 'לא ידוע')
        
        # כפתורי פעולות
        keyboard = [
            [
                InlineKeyboardButton("👁️ צפה בקובץ", callback_data=f"lf_view_{file_index}"),
                InlineKeyboardButton("📥 הורד", callback_data=f"lf_download_{file_index}")
            ],
            [
                InlineKeyboardButton("📝 ערוך", callback_data=f"lf_edit_{file_index}"),
                InlineKeyboardButton("🗑️ מחק", callback_data=f"lf_delete_{file_index}")
            ],
            [
                InlineKeyboardButton("📊 מידע מפורט", callback_data=f"lf_info_{file_index}")
            ],
            [
                InlineKeyboardButton("🔗 שתף קוד", callback_data=f"share_menu_id:{str(file_data.get('_id') or '')}")
            ],
            [
                InlineKeyboardButton("🔙 חזרה לרשימה", callback_data="show_large_files")
            ]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # הכנת טקסט עם מידע על הקובץ
        emoji = get_language_emoji(language)
        size_kb = file_size / 1024
        
        # בריחה בטוחה לשם קובץ בתוך Markdown: נשתמש ב-code span כדי לנטרל תווים בעייתיים
        safe_file_name = str(file_name).replace('`', '\\`')
        text = (
            f"📄 `{safe_file_name}`\n\n"
            f"{emoji} **שפה:** {language}\n"
            f"💾 **גודל:** {size_kb:.1f}KB ({file_size:,} בתים)\n"
            f"📏 **שורות:** {lines_count:,}\n"
            f"📅 **נוצר:** {created_at}\n\n"
            "🎯 בחר פעולה:"
        )
        
        await query.edit_message_text(
            text,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    
    async def view_large_file(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """הצגת קובץ גדול - תצוגה מקדימה או שליחה כקובץ"""
        query = update.callback_query
        await query.answer()
        
        # קבלת מידע על הקובץ
        file_index = query.data.replace("lf_view_", "")
        large_files_cache = context.user_data.get('large_files_cache', {})
        file_data = large_files_cache.get(file_index)
        
        if not file_data:
            await query.edit_message_text("❌ שגיאה בזיהוי הקובץ")
            return
        
        user_id = update.effective_user.id
        file_name = file_data.get('file_name', 'קובץ ללא שם')
        try:
            content, language = self._fetch_full_large_file_content(user_id, file_data)
        except Exception:
            logger.error("שליפת תוכן קובץ גדול נכשלה (שגיאת DB)", exc_info=True)
            keyboard = [[InlineKeyboardButton("🔙 חזרה", callback_data=f"large_file_{file_index}")]]
            await query.edit_message_text(
                "❌ שגיאה במסד הנתונים בעת שליפת תוכן הקובץ. נסו שוב עוד רגע.",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
            return

        if not (isinstance(content, str) and content):
            keyboard = [[InlineKeyboardButton("🔙 חזרה", callback_data=f"large_file_{file_index}")]]
            await query.edit_message_text(
                "❌ לא הצלחתי לשלוף את תוכן הקובץ (התוכן ריק או חסר).",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
            return
        
        # בדיקה אם הקובץ קטן מספיק להצגה בצ'אט
        if len(content) <= self.preview_max_chars:
            # הצגה ישירה עם Markdown ובלוק קוד; נבריח backticks כדי למנוע שבירה
            safe_content = str(content).replace('```', '\\`\\`\\`')
            formatted_content = f"```{language}\n{safe_content}\n```"
            keyboard = [[InlineKeyboardButton("🔙 חזרה", callback_data=f"large_file_{file_index}")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            # בריחת שם הקובץ ל-Markdown כדי למנוע BadRequest על _ [] וכד'.
            try:
                safe_file_name = TextUtils.escape_markdown(file_name, version=1)
            except Exception:
                safe_file_name = str(file_name).replace('`', '\\`')
            # נסה Markdown; אם נכשל, שלח ללא parse_mode
            try:
                await query.edit_message_text(
                    f"📄 **{safe_file_name}**\n\n{formatted_content}",
                    reply_markup=reply_markup,
                    parse_mode='Markdown'
                )
            except Exception:
                await query.edit_message_text(
                    f"📄 {file_name}\n\n{content}",
                    reply_markup=reply_markup
                )
        else:
            # הקובץ גדול מדי - נציג תצוגה מקדימה ונשלח כקובץ
            preview = content[:self.preview_max_chars] + "\n\n... [המשך הקובץ נשלח כקובץ מצורף]"
            keyboard = [[InlineKeyboardButton("🔙 חזרה", callback_data=f"large_file_{file_index}")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            # שליחת תצוגה מקדימה עם Markdown ובלוק קוד; נבריח backticks
            safe_preview = str(preview).replace('```', '\\`\\`\\`')
            formatted_preview = f"```{language}\n{safe_preview}\n```"
            try:
                safe_file_name = TextUtils.escape_markdown(file_name, version=1)
            except Exception:
                safe_file_name = str(file_name).replace('`', '\\`')
            try:
                await query.edit_message_text(
                    f"📄 **{safe_file_name}** (תצוגה מקדימה)\n\n{formatted_preview}",
                    reply_markup=reply_markup,
                    parse_mode='Markdown'
                )
            except Exception:
                await query.edit_message_text(
                    f"📄 {file_name} (תצוגה מקדימה)\n\n{preview}",
                    reply_markup=reply_markup
                )
            
            # שליחת הקובץ המלא
            file_bytes = BytesIO()
            file_bytes.write(content.encode("utf-8"))
            file_bytes.seek(0)
            
            # בכיתוב של המסמך, נבריח שם קובץ ונמנע Markdown
            await query.message.reply_document(
                document=file_bytes,
                filename=file_name,
                caption=f"📄 הקובץ המלא: {file_name}",
            )
    
    async def download_large_file(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """הורדת קובץ גדול"""
        query = update.callback_query
        await query.answer("📥 מכין את הקובץ להורדה...")
        
        # קבלת מידע על הקובץ
        file_index = query.data.replace("lf_download_", "")
        large_files_cache = context.user_data.get('large_files_cache', {})
        file_data = large_files_cache.get(file_index)
        
        if not file_data:
            await query.edit_message_text("❌ שגיאה בזיהוי הקובץ")
            return
        
        user_id = update.effective_user.id
        file_name = file_data.get('file_name', 'קובץ ללא שם')
        try:
            content, language = self._fetch_full_large_file_content(user_id, file_data)
        except Exception:
            logger.error("הכנת הורדה לקובץ גדול נכשלה (שגיאת DB)", exc_info=True)
            keyboard = [[InlineKeyboardButton("🔙 חזרה", callback_data=f"large_file_{file_index}")]]
            await query.edit_message_text(
                "❌ שגיאה במסד הנתונים בעת הכנת ההורדה. נסו שוב עוד רגע.",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
            return

        if not (isinstance(content, str) and content):
            keyboard = [[InlineKeyboardButton("🔙 חזרה", callback_data=f"large_file_{file_index}")]]
            await query.edit_message_text(
                "❌ לא הצלחתי להכין הורדה כי התוכן ריק/חסר.",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
            return
        
        # יצירת קובץ להורדה
        file_bytes = BytesIO()
        file_bytes.write(content.encode("utf-8"))
        file_bytes.seek(0)
        
        # שליחת הקובץ
        await query.message.reply_document(
            document=file_bytes,
            filename=file_name,
            caption=f"📥 {file_name}\n🔤 שפה: {language}\n💾 גודל: {len(content):,} תווים",
        )
        
        # חזרה לתפריט הקובץ
        await self.handle_file_selection(update, context)
    
    async def delete_large_file_confirm(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """אישור מחיקת קובץ גדול"""
        query = update.callback_query
        await query.answer()
        
        file_index = query.data.replace("lf_delete_", "")
        large_files_cache = context.user_data.get('large_files_cache', {})
        file_data = large_files_cache.get(file_index)
        
        if not file_data:
            await query.edit_message_text("❌ שגיאה בזיהוי הקובץ")
            return
        
        file_name = file_data.get('file_name', 'קובץ ללא שם')
        
        keyboard = [
            [
                InlineKeyboardButton("✅ כן, העבר לסל מיחזור", callback_data=f"lf_confirm_delete_{file_index}"),
                InlineKeyboardButton("❌ ביטול", callback_data=f"large_file_{file_index}")
            ]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"⚠️ **אזהרה**\n\n"
            f"האם להעביר את הקובץ לסל המיחזור:\n"
            f"📄 `{file_name}`?\n\n"
            f"♻️ ניתן לשחזר מתוך סל המיחזור עד פקיעת התוקף",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    
    async def delete_large_file(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """מחיקת קובץ גדול"""
        query = update.callback_query
        await query.answer()
        
        file_index = query.data.replace("lf_confirm_delete_", "")
        large_files_cache = context.user_data.get('large_files_cache', {})
        file_data = large_files_cache.get(file_index)
        
        if not file_data:
            await query.edit_message_text("❌ שגיאה בזיהוי הקובץ")
            return
        
        user_id = update.effective_user.id
        file_name = file_data.get('file_name', 'קובץ ללא שם')
        
        # מחיקת הקובץ
        facade = self._facade()
        if facade is None:
            await query.edit_message_text("❌ לא ניתן למחוק כרגע — אין חיבור למסד הנתונים.")
            return
        try:
            success = bool(facade.delete_large_file(user_id, file_name))
        except Exception:
            logger.error("מחיקת קובץ גדול נכשלה (שגיאת DB)", exc_info=True)
            await query.edit_message_text("❌ שגיאה במסד הנתונים בעת מחיקת הקובץ. נסו שוב עוד רגע.")
            return
        
        if success:
            # ניקוי הקאש
            if file_index in large_files_cache:
                del large_files_cache[file_index]
            
            # בדוק אם נשארו קבצים פעילים
            remaining_total = 0
            try:
                _remaining_files, remaining_total = facade.get_user_large_files(user_id, page=1, per_page=1)
            except Exception:
                # לא נכשיל את ה-flow על בדיקה "קוסמטית" של האם נשארו קבצים; נרשום לוג ונפול חזרה.
                logger.error("בדיקת קבצים גדולים שנותרו נכשלה (שגיאת DB)", exc_info=True)
            if remaining_total > 0:
                keyboard = [[InlineKeyboardButton("🔙 חזרה לרשימה", callback_data="show_large_files")]]
            else:
                keyboard = [[InlineKeyboardButton("🔙 חזור", callback_data="files")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                f"✅ **הקובץ הועבר לסל המיחזור!**\n\n"
                f"📄 קובץ: `{file_name}`\n"
                f"♻️ ניתן לשחזר אותו מתפריט '🗑️ סל מיחזור' עד למחיקה אוטומטית",
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
        else:
            await query.edit_message_text("❌ שגיאה במחיקת הקובץ")
    
    async def show_file_info(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """הצגת מידע מפורט על קובץ גדול"""
        query = update.callback_query
        await query.answer()
        
        file_index = query.data.replace("lf_info_", "")
        large_files_cache = context.user_data.get('large_files_cache', {})
        file_data = large_files_cache.get(file_index)
        
        if not file_data:
            await query.edit_message_text("❌ שגיאה בזיהוי הקובץ")
            return
        
        file_name = file_data.get('file_name', 'קובץ ללא שם')
        content = file_data.get('content', '')
        language = file_data.get('programming_language', 'text')
        file_size = file_data.get('file_size', 0)
        lines_count = file_data.get('lines_count', 0)
        created_at = file_data.get('created_at', 'לא ידוע')
        updated_at = file_data.get('updated_at', 'לא ידוע')
        tags = file_data.get('tags', [])
        
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
        
        await query.edit_message_text(
            text,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    
    async def edit_large_file(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """התחלת תהליך עריכת קובץ גדול"""
        query = update.callback_query
        await query.answer()
        
        file_index = query.data.replace("lf_edit_", "")
        large_files_cache = context.user_data.get('large_files_cache', {})
        file_data = large_files_cache.get(file_index)
        
        if not file_data:
            await query.edit_message_text("❌ שגיאה בזיהוי הקובץ")
            from conversation_handlers import EDIT_CODE
            return int(EDIT_CODE)
        
        file_name = file_data.get('file_name', 'קובץ ללא שם')
        
        # שמירת מידע על הקובץ לעריכה
        context.user_data['editing_large_file'] = {
            'file_index': file_index,
            'file_name': file_name,
            'file_data': file_data
        }
        
        keyboard = [[InlineKeyboardButton("❌ ביטול", callback_data=f"large_file_{file_index}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"✏️ **עריכת קובץ גדול**\n\n"
            f"📄 קובץ: `{file_name}`\n\n"
            f"⚠️ **שים לב:** עקב גודל הקובץ, העריכה תחליף את כל התוכן.\n"
            f"📝 שלח את התוכן החדש המלא של הקובץ:",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        
        # החזרת מצב שיחה לעריכה
        from conversation_handlers import EDIT_CODE
        return int(EDIT_CODE)

# יצירת instance גלובלי
large_files_handler = LargeFilesHandler()