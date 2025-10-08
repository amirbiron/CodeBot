"""
Handlers לפקודות Refactoring בבוט Telegram
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
)

from refactoring_engine import (
    refactoring_engine,
    RefactorType,
    RefactorProposal,
)
from activity_reporter import create_reporter
from config import config
from utils import TelegramUtils

logger = logging.getLogger(__name__)

# Reporter לפעילות
reporter = create_reporter(
    mongodb_uri=config.MONGODB_URL,
    service_id=config.BOT_LABEL,
    service_name="CodeBot",
)


class RefactorHandlers:
    """מחלקה לניהול כל ה-handlers של Refactoring"""

    def __init__(self, application):
        self.application = application
        self.pending_proposals = {}  # {user_id: RefactorProposal}
        self.setup_handlers()

    def setup_handlers(self) -> None:
        self.application.add_handler(CommandHandler("refactor", self.refactor_command))
        self.application.add_handler(
            CallbackQueryHandler(self.handle_refactor_type_callback, pattern=r'^refactor_type:')
        )
        self.application.add_handler(
            CallbackQueryHandler(self.handle_proposal_callback, pattern=r'^refactor_action:')
        )

    async def refactor_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        פקודה: /refactor <type> <filename>

        או: /refactor <filename> (מציג תפריט בחירה)
        """
        user_id = update.effective_user.id if update and update.effective_user else 0
        try:
            reporter.report_activity(user_id)
        except Exception:
            pass

        if not context.args:
            await update.message.reply_text(
                "🏗️ *רפקטורינג אוטומטי*\n\n"
                "שימוש: `/refactor <filename>`\n\n"
                "דוגמה:\n"
                "`/refactor large_module.py`\n\n"
                "הבוט יציע אפשרויות רפקטורינג מתאימות",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        filename = " ".join(context.args)

        # טעינת קובץ מה-DB
        try:
            from database import db  # import דינמי לתמיכה בטסטים עם monkeypatch
            # תמיכה לאחור: get_code_by_name אם קיים, אחרת get_file
            if hasattr(db, 'get_code_by_name'):
                snippet = db.get_code_by_name(user_id, filename)
            else:
                snippet = db.get_file(user_id, filename)
        except Exception:
            snippet = None

        if not snippet:
            await update.message.reply_text(
                f"❌ לא נמצא קובץ בשם `{filename}`\n\n"
                "השתמש ב-`/list` לראות את הקבצים שלך",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        code = snippet.get('code') or ''
        await self._show_refactor_type_menu(update, filename, code)

    async def _show_refactor_type_menu(self, update: Update, filename: str, code: str):
        keyboard = [
            [
                InlineKeyboardButton(
                    "📦 פיצול קובץ גדול",
                    callback_data=f"refactor_type:split_functions:{filename}",
                ),
            ],
            [
                InlineKeyboardButton(
                    "🔧 חילוץ פונקציות",
                    callback_data=f"refactor_type:extract_functions:{filename}",
                ),
            ],
            [
                InlineKeyboardButton(
                    "🎨 המרה למחלקות",
                    callback_data=f"refactor_type:convert_to_classes:{filename}",
                ),
            ],
            [
                InlineKeyboardButton(
                    "🔀 מיזוג קוד דומה",
                    callback_data=f"refactor_type:merge_similar:{filename}",
                ),
            ],
            [
                InlineKeyboardButton(
                    "💉 Dependency Injection",
                    callback_data=f"refactor_type:dependency_injection:{filename}",
                ),
            ],
            [
                InlineKeyboardButton("❌ ביטול", callback_data="refactor_type:cancel"),
            ],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        lines_count = len(code.splitlines())
        msg = (
            f"🏗️ *רפקטורינג עבור:* `{filename}`\n\n"
            f"📏 גודל: {len(code)} תווים\n"
            f"📝 שורות: {lines_count}\n\n"
            "בחר סוג רפקטורינג:"
        )
        await update.message.reply_text(msg, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

    async def handle_refactor_type_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        user_id = update.effective_user.id if update and update.effective_user else 0
        parts = (query.data or '').split(':')
        if len(parts) < 2:
            return
        action = parts[1]
        if action == "cancel":
            await TelegramUtils.safe_edit_message_text(query, "❌ בוטל")
            return
        refactor_type_str = action
        filename = ':'.join(parts[2:])
        try:
            from database import db  # dynamic import for tests
            if hasattr(db, 'get_code_by_name'):
                snippet = db.get_code_by_name(user_id, filename)
            else:
                snippet = db.get_file(user_id, filename)
        except Exception:
            snippet = None
        if not snippet:
            await TelegramUtils.safe_edit_message_text(query, "❌ הקובץ לא נמצא")
            return
        code = snippet.get('code') or ''
        await TelegramUtils.safe_edit_message_text(
            query,
            "🏗️ מנתח קוד ומכין הצעת רפקטורינג...\n"
            "⏳ זה יכול לקחת כמה שניות"
        )
        try:
            refactor_type = RefactorType(refactor_type_str)
        except ValueError:
            await TelegramUtils.safe_edit_message_text(query, f"❌ סוג רפקטורינג לא חוקי: {refactor_type_str}")
            return
        result = refactoring_engine.propose_refactoring(code=code, filename=filename, refactor_type=refactor_type)
        if not result.success or not result.proposal:
            error_msg = result.error or "שגיאה לא ידועה"
            await TelegramUtils.safe_edit_message_text(query, f"❌ {error_msg}")
            return
        self.pending_proposals[user_id] = result.proposal
        # לוג פעילות משתמש (מקטין רעש סטטיסטיקות קיימות)
        try:
            from user_stats import user_stats
            user_stats.log_user(user_id)
        except Exception:
            pass
        await self._display_proposal(query, result.proposal, result.validation_passed)

    async def _display_proposal(self, query, proposal: RefactorProposal, validation_passed: bool):
        msg = "🏗️ *הצעת רפקטורינג*\n\n"
        msg += proposal.description
        msg += "\n\n"
        msg += "*📋 סיכום שינויים:*\n"
        for change in proposal.changes_summary:
            msg += f"{change}\n"
        msg += "\n"
        if proposal.warnings:
            msg += "*⚠️ אזהרות:*\n"
            for warning in proposal.warnings:
                msg += f"{warning}\n"
            msg += "\n"
        if validation_passed:
            msg += "✅ *הקבצים החדשים עברו בדיקת תקינות*\n"
        else:
            msg += "⚠️ *יש בעיות בדיקת תקינות - בדוק לפני אישור*\n"
        msg += f"\n_מספר קבצים חדשים: {len(proposal.new_files)}_"
        keyboard = [
            [InlineKeyboardButton("✅ אשר ושמור", callback_data="refactor_action:approve")],
            [
                InlineKeyboardButton("📄 תצוגה מקדימה", callback_data="refactor_action:preview"),
                InlineKeyboardButton("📝 ערוך הצעה", callback_data="refactor_action:edit"),
            ],
            [InlineKeyboardButton("❌ בטל", callback_data="refactor_action:cancel")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await TelegramUtils.safe_edit_message_text(query, msg, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

    async def handle_proposal_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        user_id = update.effective_user.id if update and update.effective_user else 0
        if user_id not in self.pending_proposals:
            await TelegramUtils.safe_edit_message_text(query, "❌ לא נמצאה הצעה ממתינה")
            return
        proposal = self.pending_proposals[user_id]
        action = (query.data or '').split(':')[1]
        if action == "cancel":
            del self.pending_proposals[user_id]
            await TelegramUtils.safe_edit_message_text(query, "❌ הרפקטורינג בוטל")
            return
        if action == "preview":
            await self._send_preview(query, proposal)
            return
        if action == "edit":
            await query.answer("📝 עריכה ידנית טרם מיושמת - אשר או בטל", show_alert=True)
            return
        if action == "approve":
            await self._approve_and_save(query, user_id, proposal)
            del self.pending_proposals[user_id]
            # לוג פעילות משתמש
            try:
                from user_stats import user_stats
                user_stats.log_user(user_id)
            except Exception:
                pass
            return

    async def _send_preview(self, query, proposal: RefactorProposal):
        await query.answer("📄 שולח תצוגה מקדימה...")
        for filename, content in proposal.new_files.items():
            preview_content = content
            if len(content) > 3000:
                preview_content = content[:3000] + "\n\n... (קוד נוסף לא מוצג) ..."
            msg = f"📄 *{filename}*\n\n```python\n{preview_content}\n```"
            try:
                await query.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
            except Exception:
                await query.message.reply_text(f"📄 {filename}\n\n{preview_content}")

    async def _approve_and_save(self, query, user_id: int, proposal: RefactorProposal):
        await TelegramUtils.safe_edit_message_text(query, "💾 שומר קבצים חדשים...")
        saved_count = 0
        errors = []
        try:
            from database import db
        except Exception:
            db = None  # type: ignore
        for filename, content in proposal.new_files.items():
            try:
                if db is not None:
                    if hasattr(db, 'save_code'):
                        db.save_code(
                            user_id=user_id,
                            filename=filename,
                            code=content,
                            language="python",
                            tags=[f"refactored_{proposal.refactor_type.value}"],
                        )
                    else:
                        db.save_file(
                            user_id=user_id,
                            file_name=filename,
                            code=content,
                            programming_language="python",
                            extra_tags=[f"refactored_{proposal.refactor_type.value}"],
                        )
                saved_count += 1
            except Exception as e:
                logger.error(f"שגיאה בשמירת {filename}: {e}")
                errors.append(f"❌ {filename}: {str(e)}")
        self._save_refactor_metadata(user_id, proposal)
        msg = f"✅ *רפקטורינג הושלם!*\n\n"
        msg += f"📦 נשמרו {saved_count} קבצים חדשים\n"
        if errors:
            msg += f"\n⚠️ *שגיאות:*\n"
            for error in errors:
                msg += f"{error}\n"
        msg += f"\n_השתמש ב-`/list` לראות את הקבצים החדשים_"
        await TelegramUtils.safe_edit_message_text(query, msg, parse_mode=ParseMode.MARKDOWN)

    def _save_refactor_metadata(self, user_id: int, proposal: RefactorProposal) -> None:
        try:
            from database import db
            db.collection('refactorings').insert_one({
                'user_id': user_id,
                'timestamp': datetime.now(timezone.utc),
                'refactor_type': proposal.refactor_type.value,
                'original_file': proposal.original_file,
                'new_files': list(proposal.new_files.keys()),
                'changes_summary': proposal.changes_summary,
            })
        except Exception as e:
            logger.error(f"שגיאה בשמירת מטא-דאטה: {e}")


def setup_refactor_handlers(application):
    """פונקציה להגדרת כל ה-handlers"""
    return RefactorHandlers(application)

