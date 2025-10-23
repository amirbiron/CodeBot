from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

from .models import Reminder, ReminderConfig, ReminderStatus
from .database import RemindersDB
from .validators import ReminderValidator
from .utils import parse_time

logger = logging.getLogger(__name__)

REMINDER_TITLE, REMINDER_TIME, REMINDER_DESCRIPTION = range(3)


class ReminderHandlers:
    def __init__(self, db: RemindersDB, validator: ReminderValidator):
        self.db = db
        self.validator = validator

    def _ensure_user_data(self, context: ContextTypes.DEFAULT_TYPE) -> dict:
        """Ensure context.user_data exists and is a dict.

        In production, PTB provides user_data. In lightweight tests or stubs,
        context may be a SimpleNamespace without this attribute.
        """
        try:
            ud = getattr(context, "user_data")
        except Exception:
            ud = None
        if not isinstance(ud, dict):
            setattr(context, "user_data", {})
            return context.user_data  # type: ignore[attr-defined]
        return ud

    async def remind_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        # Limit per user
        count = self.db.get_user_reminders_count(user_id)
        if count >= ReminderConfig.max_reminders_per_user:
            await update.message.reply_text(
                f"❌ הגעת למגבלה של {ReminderConfig.max_reminders_per_user} תזכורות."
            )
            return ConversationHandler.END

        args = context.args
        if args:
            return await self._quick_reminder(update, context, args)

        await update.message.reply_text(
            "📝 **יצירת תזכורת חדשה**\n\nמה הכותרת של התזכורת?\n(לביטול: /cancel)",
            parse_mode=ParseMode.MARKDOWN,
        )
        return REMINDER_TITLE

    async def _quick_reminder(self, update: Update, context: ContextTypes.DEFAULT_TYPE, args: list):
        try:
            text = " ".join(args)
            title_match = re.search(r'"([^"]+)"', text)
            if not title_match:
                await update.message.reply_text(
                    "❌ פורמט שגוי. דוגמה:\n`/remind \"לתקן באג\" tomorrow 10:00`",
                    parse_mode=ParseMode.MARKDOWN,
                )
                return ConversationHandler.END
            title = title_match.group(1)
            time_text = text[title_match.end() :].strip()
            remind_time = parse_time(time_text, self._get_user_timezone(update.effective_user.id))
            if not remind_time:
                await update.message.reply_text(
                    "❌ לא הצלחתי להבין את הזמן.\nדוגמות: tomorrow 10:00, בעוד שעה, 2024-12-25 15:30"
                )
                return ConversationHandler.END
            reminder = Reminder(
                reminder_id=str(uuid.uuid4()),
                user_id=update.effective_user.id,
                title=title,
                remind_at=remind_time.astimezone(timezone.utc),
                user_timezone=self._get_user_timezone(update.effective_user.id),
            )
            success, result = self.db.create_reminder(reminder)
            if success:
                job_name = f"reminder_{reminder.reminder_id}"
                context.job_queue.run_once(
                    self._send_reminder_notification,
                    when=reminder.remind_at,
                    name=job_name,
                    data=reminder.to_dict(),
                    chat_id=update.effective_chat.id,
                    user_id=update.effective_user.id,
                )
                await update.message.reply_text(
                    f"✅ **תזכורת נוצרה!**\n\n📌 {title}\n⏰ {remind_time.strftime('%d/%m/%Y %H:%M')}\n\n💡 /reminders לרשימה",
                    parse_mode=ParseMode.MARKDOWN,
                )
            else:
                await update.message.reply_text(f"❌ {result}")
        except Exception as e:
            logger.error(f"Quick reminder error: {e}")
            await update.message.reply_text("❌ שגיאה ביצירת תזכורת")
        return ConversationHandler.END

    async def receive_title(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        title = (update.message.text or "").strip()
        if len(title) > ReminderConfig.max_title_length or not self.validator.validate_text(title):
            await update.message.reply_text("❌ כותרת לא תקינה, נסה שוב:")
            return REMINDER_TITLE
        self._ensure_user_data(context)["reminder_title"] = title
        keyboard = [
            [InlineKeyboardButton("בעוד שעה", callback_data="time_1h")],
            [InlineKeyboardButton("מחר בבוקר (09:00)", callback_data="time_tomorrow_9")],
            [InlineKeyboardButton("מחר בערב (18:00)", callback_data="time_tomorrow_18")],
            [InlineKeyboardButton("בעוד שבוע", callback_data="time_week")],
            [InlineKeyboardButton("זמן מותאם אישית", callback_data="time_custom")],
        ]
        await update.message.reply_text(
            f"📌 **{title}**\n\nמתי להזכיר לך?",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN,
        )
        return REMINDER_TIME

    async def receive_time(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        # Support both inline button selection (callback_query) and free text message for custom time
        user_tz = self._get_user_timezone(update.effective_user.id)
        now = datetime.now(ZoneInfo(user_tz))

        if update.callback_query:
            query = update.callback_query
            await query.answer()
            data = query.data or ""
            if data == "time_1h":
                remind_time = now + timedelta(hours=1)
            elif data == "time_tomorrow_9":
                remind_time = (now + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
            elif data == "time_tomorrow_18":
                remind_time = (now + timedelta(days=1)).replace(hour=18, minute=0, second=0, microsecond=0)
            elif data == "time_week":
                remind_time = now + timedelta(weeks=1)
            elif data == "time_custom":
                await query.edit_message_text(
                    "⏰ הקלד זמן מותאם אישית (e.g. 15:30 / tomorrow 10:00 / 2025-12-25 14:00 / בעוד 3 שעות)"
                )
                return REMINDER_TIME
            else:
                return REMINDER_TIME
        else:
            # Free-text custom time input
            text = (update.message.text or "").strip()
            remind_time = parse_time(text, user_tz)
            if not remind_time:
                await update.message.reply_text(
                    "❌ לא הבנתי את הזמן. נסה שוב:\n(או /cancel לביטול)"
                )
                return REMINDER_TIME

        self._ensure_user_data(context)["reminder_time"] = remind_time.astimezone(timezone.utc)
        keyboard = [
            [InlineKeyboardButton("ללא תיאור", callback_data="desc_skip")],
            [InlineKeyboardButton("הוסף תיאור", callback_data="desc_add")],
        ]
        msg_text = f"📌 **{context.user_data['reminder_title']}**\n⏰ {remind_time.strftime('%d/%m/%Y %H:%M')}\n\nלהוסיף תיאור?"
        if update.callback_query:
            await update.callback_query.edit_message_text(
                msg_text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.MARKDOWN,
            )
        else:
            await update.message.reply_text(
                msg_text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.MARKDOWN,
            )
        return REMINDER_DESCRIPTION

    async def receive_description(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        description = ""
        if update.callback_query:
            await update.callback_query.answer()
            if update.callback_query.data == "desc_add":
                await update.callback_query.edit_message_text("📝 הקלד תיאור לתזכורת (או /skip)")
                return REMINDER_DESCRIPTION
        else:
            text = (update.message.text or "").strip()
            if text and text != "/skip":
                if len(text) > ReminderConfig.max_description_length or not self.validator.validate_text(text):
                    await update.message.reply_text("❌ תיאור לא תקין. נסה שוב או /skip:")
                    return REMINDER_DESCRIPTION
                description = text

        reminder = Reminder(
            reminder_id=str(uuid.uuid4()),
            user_id=update.effective_user.id,
            title=self._ensure_user_data(context).get("reminder_title", ""),
            description=description,
            remind_at=self._ensure_user_data(context).get("reminder_time"),
            user_timezone=self._get_user_timezone(update.effective_user.id),
        )
        ok, result = self.db.create_reminder(reminder)
        if ok:
            job_name = f"reminder_{reminder.reminder_id}"
            context.job_queue.run_once(
                self._send_reminder_notification,
                when=reminder.remind_at,
                name=job_name,
                data=reminder.to_dict(),
                chat_id=update.effective_chat.id if update.effective_chat else update.callback_query.message.chat_id,  # type: ignore[attr-defined]
                user_id=update.effective_user.id,
            )
            msg = (
                "✅ **תזכורת נוצרה בהצלחה!**\n\n"
                f"📌 {reminder.title}\n"
                f"⏰ {reminder.remind_at.astimezone(ZoneInfo(self._get_user_timezone(update.effective_user.id))).strftime('%d/%m/%Y %H:%M')}\n\n"
                "💡 /reminders לרשימה"
            )
            if update.callback_query:
                await update.callback_query.edit_message_text(msg, parse_mode=ParseMode.MARKDOWN)
            else:
                await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
        else:
            err = f"❌ {result}"
            if update.callback_query:
                await update.callback_query.edit_message_text(err)
            else:
                await update.message.reply_text(err)
        try:
            ud = getattr(context, "user_data")
            if isinstance(ud, dict):
                ud.clear()
        except Exception:
            pass
        return ConversationHandler.END

    async def reminders_list(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        page = int(context.args[0]) if context.args else 1
        per_page = 10
        reminders = self.db.get_user_reminders(user_id, status=ReminderStatus.PENDING.value, limit=per_page, skip=(page - 1) * per_page)
        if not reminders:
            await update.message.reply_text("📭 אין לך תזכורות ממתינות.\n\n💡 /remind ליצירת תזכורת")
            return
        message = "📋 **התזכורות שלך:**\n\n"
        for i, rem in enumerate(reminders, 1):
            title = str(rem.get("title", ""))
            t = rem.get("remind_at")
            try:
                if isinstance(t, datetime):
                    t_local = t.astimezone(ZoneInfo(self._get_user_timezone(user_id)))
                    ts = t_local.strftime("%d/%m %H:%M")
                else:
                    ts = str(t)
            except Exception:
                ts = str(t)
            message += f"{i}. **{title}**\n   ⏳ {ts}\n\n"
        keyboard = [
            [InlineKeyboardButton("➕ תזכורת חדשה", callback_data="rem_new")]
        ]
        await update.message.reply_text(message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)

    async def reminder_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        data = query.data
        user_id = update.effective_user.id
        if data.startswith("rem_complete_"):
            rid = data.replace("rem_complete_", "")
            if self.db.complete_reminder(user_id, rid):
                await query.edit_message_text("✅ התזכורת הושלמה!")
                for job in context.job_queue.get_jobs_by_name(f"reminder_{rid}"):
                    job.schedule_removal()
            else:
                await query.answer("❌ שגיאה", show_alert=True)
        elif data.startswith("rem_snooze_"):
            rid = data.replace("rem_snooze_", "")
            kb = [
                [InlineKeyboardButton("15 דקות", callback_data=f"snooze_{rid}_15")],
                [InlineKeyboardButton("שעה", callback_data=f"snooze_{rid}_60")],
                [InlineKeyboardButton("3 שעות", callback_data=f"snooze_{rid}_180")],
                [InlineKeyboardButton("מחר", callback_data=f"snooze_{rid}_1440")],
            ]
            await query.edit_message_text("⏰ לכמה זמן לדחות?", reply_markup=InlineKeyboardMarkup(kb))
        elif data.startswith("snooze_"):
            _, rid, minutes = data.split("_")
            if self.db.snooze_reminder(user_id, rid, int(minutes)):
                # reschedule
                new_time = datetime.now(timezone.utc) + timedelta(minutes=int(minutes))
                for job in context.job_queue.get_jobs_by_name(f"reminder_{rid}"):
                    job.schedule_removal()
                doc = self.db.reminders_collection.find_one({"reminder_id": rid})
                if doc:
                    context.job_queue.run_once(
                        self._send_reminder_notification,
                        when=new_time,
                        name=f"reminder_{rid}",
                        data=doc,
                        chat_id=query.message.chat_id,
                        user_id=user_id,
                    )
                await query.edit_message_text(f"⏰ התזכורת נדחתה ב-{minutes} דקות", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📋 לרשימה", callback_data="rem_list")]]))
            else:
                await query.answer("❌ שגיאה בדחייה", show_alert=True)
        elif data.startswith("rem_delete_"):
            rid = data.replace("rem_delete_", "")
            kb = [[InlineKeyboardButton("✅ כן, מחק", callback_data=f"confirm_del_{rid}"), InlineKeyboardButton("❌ ביטול", callback_data="rem_list")]]
            await query.edit_message_text("⚠️ למחוק את התזכורת?", reply_markup=InlineKeyboardMarkup(kb))
        elif data.startswith("confirm_del_"):
            rid = data.replace("confirm_del_", "")
            if self.db.delete_reminder(user_id, rid):
                for job in context.job_queue.get_jobs_by_name(f"reminder_{rid}"):
                    job.schedule_removal()
                await query.edit_message_text("🗑️ התזכורת נמחקה")
            else:
                await query.answer("❌ שגיאה במחיקה", show_alert=True)
        elif data == "rem_list":
            # reload list
            fake_update = Update(update.update_id, message=None, callback_query=query)
            # Not ideal; simply prompt user to use /reminders
            await query.edit_message_text("📋 השתמש ב-/reminders כדי לראות את הרשימה")

    async def _send_reminder_notification(self, context: ContextTypes.DEFAULT_TYPE):
        job = context.job
        data = job.data
        chat_id = job.chat_id
        try:
            title = str(data.get("title", ""))
            description = str(data.get("description", ""))
            rid = str(data.get("reminder_id"))
            message = "⏰ **תזכורת!**\n\n" + f"📌 {title}\n"
            if description:
                message += f"\n{description}\n"
            kb = [
                [InlineKeyboardButton("✅ בוצע", callback_data=f"rem_complete_{rid}"), InlineKeyboardButton("⏰ דחה", callback_data=f"rem_snooze_{rid}")],
                [InlineKeyboardButton("🗑️ מחק", callback_data=f"rem_delete_{rid}")],
            ]
            await context.bot.send_message(chat_id=chat_id, text=message, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(kb))
            self.db.mark_reminder_sent(rid, success=True)
        except Exception as e:
            logger.error(f"Reminder send error: {e}")
            rid = str((data or {}).get("reminder_id"))
            self.db.mark_reminder_sent(rid, success=False, error=str(e))

    def _get_user_timezone(self, user_id: int) -> str:
        return "Asia/Jerusalem"


def setup_reminder_handlers(application):
    db = RemindersDB(application.bot_data.get("db_manager")) if getattr(application, "bot_data", None) else RemindersDB()
    validator = ReminderValidator()
    handlers = ReminderHandlers(db, validator)

    async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
        return ConversationHandler.END

    conv = ConversationHandler(
        entry_points=[CommandHandler("remind", handlers.remind_command)],
        states={
            REMINDER_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.receive_title)],
            REMINDER_TIME: [CallbackQueryHandler(handlers.receive_time, pattern=r"^time_"), MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.receive_time)],
            REMINDER_DESCRIPTION: [CallbackQueryHandler(handlers.receive_description, pattern=r"^desc_"), MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.receive_description)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    # Ensure conversation handlers run before generic text handlers registered elsewhere
    application.add_handler(conv, group=-1)
    application.add_handler(CommandHandler("reminders", handlers.reminders_list))
    application.add_handler(CallbackQueryHandler(handlers.reminder_callback, pattern=r"^(rem_|snooze_|confirm_del_)"))
