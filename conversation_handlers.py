"""
Conversation and menu handlers glue module.

Provides:
- MAIN_KEYBOARD: main reply keyboard layout
- get_save_conversation_handler(db): returns a ConversationHandler for /start and simple flows
- handle_callback_query(update, context): global fallback callback handler for simple "main" and files menu
- handle_batch_button(update, context): entry from main keyboard for batch menu
- EDIT_CODE: state id used when editing large files
- _auto_update_batch_status(application, chat_id, message_id, job_id, user_id): helper to auto-refresh batch status message
"""

import logging
from typing import List

from telegram import (
    Update,
    ReplyKeyboardMarkup,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from telegram.ext import (
    ConversationHandler,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

from database import db
from large_files_handler import large_files_handler
from batch_processor import batch_processor

logger = logging.getLogger(__name__)

# Main reply keyboard used across the app
MAIN_KEYBOARD: List[List[str]] = [
    ["➕ הוסף קוד חדש", "📚 הצג את כל הקבצים שלי"],
    ["📂 קבצים גדולים", "🔧 GitHub"],
    ["⚡ עיבוד Batch"]
]

# Single state used by large files edit flow
EDIT_CODE = 10


def _build_files_menu_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("📚 הצג קבצים גדולים", callback_data="show_large_files")],
        [InlineKeyboardButton("🏠 תפריט ראשי", callback_data="main")],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_save_conversation_handler(_db) -> ConversationHandler:
    """Minimal conversation handler for basic flows and /start."""

    async def start_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        username = update.effective_user.username
        try:
            # save user if DatabaseManager-like is provided (best-effort)
            try:
                db.save_user(user_id, username)
            except Exception:
                pass
            reply_markup = ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
            await update.message.reply_text(
                "👋 שלום! הבוט מוכן לשימוש.\n\n"
                "🔧 לכל תקלה בבוט נא לשלוח הודעה ל-@moominAmir",
                reply_markup=reply_markup,
            )
        except Exception as e:
            logger.error(f"start_entry failed: {e}")
        return ConversationHandler.END

    async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
        text = (update.message.text or "").strip()
        if text == "➕ הוסף קוד חדש":
            await update.message.reply_text(
                "השתמש ב/save <filename> ולאחר מכן שלח את הקוד לשמירה."
            )
            return ConversationHandler.END
        if text == "📚 הצג את כל הקבצים שלי":
            files = db.get_user_files(update.effective_user.id, limit=20)
            if not files:
                await update.message.reply_text(
                    "📂 עדיין לא שמרת קטעי קוד. השתמש ב/save כדי להתחיל!"
                )
                return ConversationHandler.END
            # Simple list of files
            response_lines = ["📋 הקטעים שלך:"]
            for f in files:
                response_lines.append(f"• {f.get('file_name', 'ללא שם')}")
            await update.message.reply_text("\n".join(response_lines))
            return ConversationHandler.END
        if text == "📂 קבצים גדולים":
            # Show large files menu via handler
            try:
                await large_files_handler.show_large_files_menu(update, context, page=1)
            except Exception as e:
                logger.error(f"Failed to show large files: {e}")
            return ConversationHandler.END
        if text == "🔧 GitHub":
            # Redirect to GitHub menu command if available
            try:
                github_handler = context.application.bot_data.get('github_handler')
                if github_handler:
                    await github_handler.github_menu_command(update, context)
                    return ConversationHandler.END
            except Exception:
                pass
            await update.message.reply_text("שלח /github כדי להיכנס לתפריט GitHub")
            return ConversationHandler.END
        if text == "⚡ עיבוד Batch":
            return await handle_batch_button(update, context)
        return ConversationHandler.END

    # Conversation that starts on /start (everything else ends immediately)
    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start_entry)],
        states={},
        fallbacks=[MessageHandler(filters.ALL, text_router)],
        allow_reentry=True,
    )
    return conv


async def handle_batch_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Entry point from main keyboard to show batch help/options."""
    keyboard = [
        [InlineKeyboardButton("📊 מצב עבודות", callback_data="job_status_menu")],
        [InlineKeyboardButton("🔄 רענן אחרון", callback_data="job_status:last")],
        [InlineKeyboardButton("🏠 חזור", callback_data="main")],
    ]
    await update.message.reply_text(
        "⚡ עיבוד Batch\nבחר פעולה:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return ConversationHandler.END


async def _auto_update_batch_status(application, chat_id: int, message_id: int, job_id: str, user_id: int):
    """Periodically refresh a status message for a batch job until completion."""
    try:
        # refresh up to ~60 seconds
        for _ in range(30):
            job = batch_processor.get_job_status(job_id)
            if not job or job.user_id != user_id:
                break
            summary = batch_processor.format_job_summary(job)
            try:
                await application.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=f"📊 <b>סטטוס עבודת Batch</b>\n\n{summary}",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 רענן", callback_data=f"job_status:{job_id}")]])
                )
            except Exception:
                pass
            if job.status in ("completed", "failed"):
                break
            await application._task_queue.sleep(2.0)  # type: ignore[attr-defined]
    except Exception as e:
        logger.warning(f"auto update status failed: {e}")


async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Global fallback callback handler for simple routes not handled elsewhere."""
    query = update.callback_query
    data = query.data if query and query.data else ""
    try:
        # Main menu button brings back the reply keyboard
        if data == "main":
            await query.answer()
            await query.message.reply_text(
                "🏠 תפריט ראשי",
                reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
            )
            return

        # Files menu button (from various places)
        if data == "files":
            await query.answer()
            await query.edit_message_text(
                "📁 תפריט קבצים",
                reply_markup=_build_files_menu_keyboard(),
            )
            return

        # Large files pagination and actions
        if data.startswith("lf_page_") or data == "show_large_files":
            page = 1
            if data.startswith("lf_page_"):
                try:
                    page = int(data.rsplit("_", 1)[-1])
                except Exception:
                    page = 1
            await large_files_handler.show_large_files_menu(update, context, page=page)
            return

        if data.startswith("large_file_"):
            await large_files_handler.handle_file_selection(update, context)
            return
        if data.startswith("lf_view_"):
            await large_files_handler.view_large_file(update, context)
            return
        if data.startswith("lf_download_"):
            await large_files_handler.download_large_file(update, context)
            return
        if data.startswith("lf_delete_"):
            await large_files_handler.delete_large_file_confirm(update, context)
            return
        if data.startswith("lf_confirm_delete_"):
            await large_files_handler.delete_large_file(update, context)
            return
        if data.startswith("lf_info_"):
            await large_files_handler.show_file_info(update, context)
            return
        if data.startswith("lf_edit_"):
            await large_files_handler.edit_large_file(update, context)
            return

        # Job status menu and refresh
        if data == "job_status_menu":
            await query.answer()
            active = [
                job for job in batch_processor.active_jobs.values()
                if job.user_id == update.effective_user.id
            ]
            if not active:
                await query.edit_message_text("📋 אין עבודות פעילות")
                return
            keyboard = []
            for job in active[-10:]:
                keyboard.append([InlineKeyboardButton(
                    f"{job.operation} — {job.status}", callback_data=f"job_status:{job.job_id}")])
            keyboard.append([InlineKeyboardButton("🔙 חזור", callback_data="main")])
            await query.edit_message_text(
                "📋 עבודות פעילות:", reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return

        if data.startswith("job_status:"):
            await query.answer()
            job_id = data.split(":", 1)[1]
            job = batch_processor.get_job_status(job_id)
            if not job or job.user_id != update.effective_user.id:
                await query.edit_message_text("❌ עבודה לא נמצאה")
                return
            summary = batch_processor.format_job_summary(job)
            await query.edit_message_text(
                f"📊 <b>סטטוס עבודת Batch</b>\n\n{summary}",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 רענן", callback_data=f"job_status:{job_id}")]])
            )
            return

    except Exception as e:
        logger.error(f"Error in global callback handler: {e}")
        try:
            await query.edit_message_text("❌ שגיאה בעיבוד הבקשה")
        except Exception:
            pass

