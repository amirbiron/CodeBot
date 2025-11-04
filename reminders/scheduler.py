from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from telegram.ext import Application

from .database import RemindersDB
from .models import ReminderConfig

logger = logging.getLogger(__name__)


class ReminderScheduler:
    def __init__(self, application: Application, db: RemindersDB):
        self.application = application
        self.db = db
        self.job_queue = application.job_queue
        self.is_running = False

    async def start(self):
        if self.is_running:
            return
        self.is_running = True
        try:
            await self._load_existing_reminders()
            # Check recurring hourly
            self.job_queue.run_repeating(self._check_recurring_reminders, interval=3600, first=10, name="recurring_reminders_check")
        except Exception as e:
            logger.error(f"Scheduler start error: {e}")

    async def stop(self):
        self.is_running = False
        for job in self.job_queue.jobs():
            try:
                if job.name and job.name.startswith("reminder_"):
                    job.schedule_removal()
            except Exception:
                continue

    async def _load_existing_reminders(self):
        try:
            due_reminders = self.db.get_pending_reminders(batch_size=1000)
            for reminder in due_reminders:
                await self.schedule_reminder(reminder)

            upcoming = getattr(self.db, "get_future_reminders", None)
            if callable(upcoming):
                for reminder in upcoming(batch_size=2000):
                    await self.schedule_reminder(reminder)
        except Exception as e:
            logger.error(f"Load reminders error: {e}")

    async def schedule_reminder(self, reminder: dict) -> bool:
        try:
            rid = reminder.get("reminder_id")
            when = reminder.get("remind_at")
            user_id = int(reminder.get("user_id"))
            if not when or when <= datetime.now(timezone.utc):
                await self._send_reminder(reminder)
                return True
            name = f"reminder_{rid}"
            # cancel existing
            for job in self.job_queue.get_jobs_by_name(name):
                job.schedule_removal()
            self.job_queue.run_once(self._send_reminder_job, when=when, name=name, data=reminder, chat_id=user_id, user_id=user_id)
            return True
        except Exception as e:
            logger.error(f"Schedule error: {e}")
            return False

    async def _send_reminder_job(self, context):
        reminder = context.job.data
        await self._send_reminder(reminder)

    async def _send_reminder(self, reminder: dict):
        try:
            user_id = int(reminder.get("user_id"))
            message = self._format_message(reminder)
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup
            kb = [
                [InlineKeyboardButton("✅ בוצע", callback_data=f"rem_complete_{reminder['reminder_id']}"), InlineKeyboardButton("⏰ דחה", callback_data=f"rem_snooze_{reminder['reminder_id']}")],
                [InlineKeyboardButton("🗑️ מחק", callback_data=f"rem_delete_{reminder['reminder_id']}")],
            ]
            await self.application.bot.send_message(chat_id=user_id, text=message, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))
            # Mark as sent (keep status pending for user interaction)
            self.db.mark_reminder_sent(str(reminder.get("reminder_id")), success=True)
        except Exception as e:
            logger.error(f"Send reminder error: {e}")
            self.db.mark_reminder_sent(str(reminder.get("reminder_id")), success=False, error=str(e))

    def _format_message(self, reminder: dict) -> str:
        title = str(reminder.get("title", ""))
        description = str(reminder.get("description", ""))
        msg = "⏰ **תזכורת!**\n\n" + f"📌 {title}\n"
        if description:
            msg += f"\n{description}\n"
        return msg

    async def _check_recurring_reminders(self, context):  # pragma: no cover - simple delegation
        try:
            self.db.handle_recurring_reminders()
        except Exception as e:
            logger.error(f"Recurring reminders check failed: {e}")


def setup_reminder_scheduler(application: Application):
    db = RemindersDB(application.bot_data.get("db_manager")) if getattr(application, "bot_data", None) else RemindersDB()
    scheduler = ReminderScheduler(application, db)
    application.bot_data["reminder_scheduler"] = scheduler
    application.job_queue.run_once(lambda context: context.application.create_task(scheduler.start()), when=1)
    return scheduler
