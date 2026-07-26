"""SkillMenuHandler — תפריט הסקילים בבוט (סוג קובץ נפרד לגמרי מגיבויים).

מבנה מפושט של BackupMenuHandler: רשימה + פעולות (הורדה/מחיקה/תיוג/הערה) על סקיל בודד,
בלי לוגיקת repo/versioning/github שסקילים אינם צריכים.

- שכבת האחסון היא SkillManager (GridFS "skills", שמירה byte-for-byte, בלי retention/restore).
- תיוג והערות נשמרים דרך אותו facade גנרי של הגיבויים (מפתח: user_id + id) — skill_id ייחודי
  ולכן אין התנגשות עם backup_id.
"""

import asyncio
import logging
from io import BytesIO
from typing import Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import ContextTypes

from file_manager import skill_manager
from handlers.pagination import build_pagination_row
# שימוש חוזר בעזרי תצוגה טהורים מ-BackupMenuHandler (בלי שכפול קוד)
from backup_menu_handler import (
    _format_bytes,
    _format_date,
    _truncate_middle,
    _rating_to_emoji,
    _get_files_facade,
)
from utils import TelegramUtils

logger = logging.getLogger(__name__)


def _collect_ratings(user_id: int, skill_ids: list) -> dict:
    """אוסף דירוגים עבור רשימת skill_ids בקריאה אחת (מיועד להרצה ב-thread)."""
    facade = _get_files_facade()
    out: dict = {}
    if facade is None:
        return out
    for sid in skill_ids:
        try:
            out[sid] = (facade.get_backup_rating(user_id, sid) or "")
        except Exception:
            out[sid] = ""
    return out

_RATING_MAP = {
    "excellent": "🏆 מצוין",
    "good": "👍 טוב",
    "ok": "🤷 סביר",
}

PAGE_SIZE = 10


class SkillMenuHandler:
    """תפריט סקילים — רשימה ופעולות על סקיל בודד (הורדה/מחיקה/תיוג/הערה)."""

    async def _get_skills(self, user_id: int):
        # I/O של GridFS — מריצים ב-thread כדי לא לחסום את לולאת האירועים
        return await asyncio.to_thread(skill_manager.list_skills, user_id)

    async def _find_skill(self, user_id: int, skill_id: str):
        skills = await self._get_skills(user_id)
        return next((s for s in skills if s.skill_id == skill_id), None)

    async def _show_skills_list(self, update: Update, context: ContextTypes.DEFAULT_TYPE,
                                page: Optional[int] = None):
        query = update.callback_query
        user_id = query.from_user.id
        await query.answer()
        skills = await self._get_skills(user_id)
        if not skills:
            keyboard = [[InlineKeyboardButton("🔙 חזור", callback_data="files")]]
            await TelegramUtils.safe_edit_message_text(
                query,
                "ℹ️ אין סקילים שמורים.\n"
                "כדי לשמור סקיל: שלח/י קובץ ZIP ובחר/י '📝 סקיל'.",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
            return

        total = len(skills)
        if page is None:
            try:
                page = int(context.user_data.get("skill_list_page", 1) or 1)
            except Exception:
                page = 1
        if page < 1:
            page = 1
        total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE if total > 0 else 1
        if page > total_pages:
            page = total_pages
        context.user_data["skill_list_page"] = page
        start = (page - 1) * PAGE_SIZE
        items = skills[start:min(start + PAGE_SIZE, total)]

        # איסוף דירוגים לפריטי העמוד בקריאה אחת ב-thread (לא חוסם את ה-event loop)
        ratings = await asyncio.to_thread(_collect_ratings, user_id, [s.skill_id for s in items])

        lines = [f"📝 סקילים שמורים — סה\"כ: {total}\n📄 עמוד {page} מתוך {total_pages}\n"]
        keyboard = []
        for info in items:
            name = info.original_name or info.skill_id
            rating = ratings.get(info.skill_id, "")
            emoji = _rating_to_emoji(rating)
            lines.append(f"• {name} — {_format_date(info.created_at)}")
            second = f"  ↳ גודל: {_format_bytes(info.total_size)} | קבצים: {info.file_count}"
            if emoji:
                second += f" | {emoji}"
            lines.append(second)
            btn = f"📝 {_truncate_middle(name, 28)} - {_format_date(info.created_at)}"
            if emoji:
                btn = f"{emoji} {btn}"
            keyboard.append([InlineKeyboardButton(btn[:64], callback_data=f"skill_details:{info.skill_id}")])

        nav = build_pagination_row(page, total, PAGE_SIZE, "skill_page_")
        if nav:
            keyboard.append(nav)
        keyboard.append([InlineKeyboardButton("🔙 חזור", callback_data="files")])
        await TelegramUtils.safe_edit_message_text(
            query, "\n".join(lines), reply_markup=InlineKeyboardMarkup(keyboard)
        )

    async def _show_skill_details(self, update: Update, context: ContextTypes.DEFAULT_TYPE, skill_id: str):
        query = update.callback_query
        await query.answer()
        user_id = query.from_user.id
        match = await self._find_skill(user_id, skill_id)
        if not match:
            await TelegramUtils.safe_edit_message_text(query, "❌ הסקיל לא נמצא")
            return
        try:
            facade = _get_files_facade()
            rating = (facade.get_backup_rating(user_id, skill_id) if facade is not None else "") or ""
        except Exception:
            rating = ""
        try:
            facade = _get_files_facade()
            note_text = (facade.get_backup_note(user_id, skill_id) if facade is not None else "") or ""
        except Exception:
            note_text = ""
        lines = [
            f"📝 סקיל: {match.original_name or skill_id}",
            f"📅 נוצר: {_format_date(match.created_at)}",
            f"📁 קבצים: {match.file_count}",
            f"📏 גודל: {_format_bytes(match.total_size)}",
        ]
        if rating:
            lines.append(f"🏷 תיוג: {rating}")
        if note_text:
            lines.append(f"📝 הערה: {note_text}")
        kb = [
            [InlineKeyboardButton("⬇️ הורדה", callback_data=f"skill_download_id:{skill_id}")],
            [InlineKeyboardButton("🗑 מחק", callback_data=f"skill_delete_one_confirm:{skill_id}")],
            [InlineKeyboardButton("🏷 ערוך תיוג", callback_data=f"skill_rate_menu:{skill_id}")],
            [InlineKeyboardButton("📝 ערוך הערה" if note_text else "📝 הוסף הערה",
                                  callback_data=f"skill_add_note:{skill_id}")],
            [InlineKeyboardButton("🔙 חזור לרשימה", callback_data="skill_list")],
        ]
        await TelegramUtils.safe_edit_message_text(
            query, "\n".join(lines), reply_markup=InlineKeyboardMarkup(kb)
        )

    async def _download_by_id(self, update: Update, context: ContextTypes.DEFAULT_TYPE, skill_id: str):
        query = update.callback_query
        user_id = query.from_user.id
        await query.answer()
        # ה-bytes נמשכים ישירות מ-GridFS (אין עותק מקומי כמו בגיבויים) — byte-for-byte
        raw = await asyncio.to_thread(skill_manager.get_skill_bytes, user_id, skill_id)
        if raw is None:
            await TelegramUtils.safe_edit_message_text(query, "❌ הסקיל לא נמצא")
            return
        # רק לאחר שיש bytes — סריקה נוספת לשם המקורי (חוסך סריקת GridFS כפולה בכל לחיצה)
        match = await self._find_skill(user_id, skill_id)
        try:
            filename = (match.original_name if match else None) or f"{skill_id}.zip"
            await query.message.reply_document(
                document=InputFile(BytesIO(raw), filename=filename),
                caption=f"📝 {filename} — {_format_bytes(len(raw))}",
            )
            try:
                await self._show_skills_list(update, context)
            except Exception as e:
                if "message is not modified" not in str(e).lower():
                    raise
        except Exception:
            logger.exception("שליחת סקיל נכשלה")
            await TelegramUtils.safe_edit_message_text(query, "❌ שגיאה בשליחת הסקיל")

    async def send_rating_prompt(self, update: Update, context: ContextTypes.DEFAULT_TYPE, skill_id: str):
        """שולח הודעת תיוג עם 3 כפתורים עבור סקיל מסוים."""
        try:
            keyboard = [
                [InlineKeyboardButton("🏆 מצוין", callback_data=f"skill_rate:{skill_id}:excellent")],
                [InlineKeyboardButton("👍 טוב", callback_data=f"skill_rate:{skill_id}:good")],
                [InlineKeyboardButton("🤷 סביר", callback_data=f"skill_rate:{skill_id}:ok")],
            ]
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="תיוג:",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
        except Exception:
            pass

    async def _ask_skill_note(self, update: Update, context: ContextTypes.DEFAULT_TYPE, skill_id: str):
        """מבקש מהמשתמש להזין הערה לסקיל; הטקסט נתפס ב-main.handle_text_message."""
        query = update.callback_query
        await query.answer()
        user_id = query.from_user.id
        try:
            facade = _get_files_facade()
            existing = (facade.get_backup_note(user_id, skill_id) if facade is not None else "") or ""
        except Exception:
            existing = ""
        try:
            context.user_data['waiting_for_skill_note_for'] = skill_id
            prompt = "✏️ הקלד/י הערה לסקיל (עד 1000 תווים).\nשלח/י טקסט עכשיו.\n\n"
            if existing:
                prompt += f"הערה נוכחית: {existing}\n"
            await TelegramUtils.safe_edit_message_text(
                query,
                prompt,
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("🔙 חזרה", callback_data=f"skill_details:{skill_id}")]]
                ),
            )
        except Exception:
            logger.exception("פתיחת עריכת הערה נכשלה")
            await TelegramUtils.safe_edit_message_text(query, "❌ שגיאה בפתיחת עריכת הערה")

    async def handle_callback_query(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """מרכז ניתוב לכל כפתורי הסקילים (prefix: skill_)."""
        query = update.callback_query
        user_id = query.from_user.id
        data = query.data or ""

        if data == "skill_list":
            await self._show_skills_list(update, context)
        elif data.startswith("skill_page_"):
            try:
                page = int(data.split("_")[-1])
            except Exception:
                page = 1
            await self._show_skills_list(update, context, page=page)
        elif data.startswith("skill_details:"):
            await self._show_skill_details(update, context, data.split(":", 1)[1])
        elif data.startswith("skill_download_id:"):
            await self._download_by_id(update, context, data.split(":", 1)[1])
        elif data.startswith("skill_rate_menu:"):
            await self.send_rating_prompt(update, context, data.split(":", 1)[1])
        elif data.startswith("skill_add_note:"):
            await self._ask_skill_note(update, context, data.split(":", 1)[1])
        elif data.startswith("skill_delete_one_confirm:"):
            skill_id = data.split(":", 1)[1]
            kb = [
                [InlineKeyboardButton("✅ אישור מחיקה", callback_data=f"skill_delete_one_execute:{skill_id}")],
                [InlineKeyboardButton("🔙 ביטול", callback_data=f"skill_details:{skill_id}")],
            ]
            await TelegramUtils.safe_edit_message_text(
                query, "האם למחוק לצמיתות את הסקיל?", reply_markup=InlineKeyboardMarkup(kb)
            )
        elif data.startswith("skill_delete_one_execute:"):
            skill_id = data.split(":", 1)[1]
            try:
                res = await asyncio.to_thread(skill_manager.delete_skills, user_id, [skill_id])
                # ניקוי תיוג נלווה (best-effort) — אותו מנגנון גנרי של הגיבויים
                try:
                    facade = _get_files_facade()
                    if facade is not None:
                        facade.delete_backup_ratings(user_id, [skill_id])
                except Exception:
                    pass
                if res.get("deleted", 0):
                    await TelegramUtils.safe_edit_message_text(query, "✅ הסקיל נמחק")
                    await self._show_skills_list(update, context)
                else:
                    await TelegramUtils.safe_edit_message_text(query, "❌ המחיקה נכשלה")
            except Exception:
                logger.exception("מחיקת סקיל נכשלה")
                await TelegramUtils.safe_edit_message_text(query, "❌ שגיאה במחיקה")
        elif data.startswith("skill_rate:"):
            # פורמט: skill_rate:<skill_id>:<rating_key>
            try:
                _, s_id, rating_key = data.split(":", 2)
            except Exception:
                await query.answer("בקשה לא תקפה", show_alert=True)
                return
            rating_value = _RATING_MAP.get(rating_key, rating_key)
            try:
                facade = _get_files_facade()
                ok = bool(facade.save_backup_rating(user_id, s_id, rating_value)) if facade is not None else False
                if ok:
                    await TelegramUtils.safe_edit_message_text(
                        query,
                        f"✅ התיוג נשמר: {rating_value}",
                        reply_markup=InlineKeyboardMarkup(
                            [[InlineKeyboardButton("🔙 לפרטי הסקיל", callback_data=f"skill_details:{s_id}")]]
                        ),
                    )
                else:
                    await query.answer("שמירת התיוג נכשלה", show_alert=True)
            except Exception:
                await query.answer("שגיאה בשמירת התיוג", show_alert=True)
