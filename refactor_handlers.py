"""
Handlers לפקודות Refactoring בבוט Telegram
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pathlib import Path
import unicodedata
import os

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
from typing import Protocol

# הזרקת reporter בזמן ריצה כדי להימנע מיצירה בזמן import
class _ReporterProto(Protocol):
    def report_activity(self, user_id: int) -> None: ...

class _NoopReporter:
    def report_activity(self, user_id: int) -> None:
        return None

reporter: _ReporterProto = _NoopReporter()

def set_activity_reporter(new_reporter: _ReporterProto) -> None:
    global reporter
    reporter = new_reporter or _NoopReporter()
from config import config
from utils import TelegramUtils

logger = logging.getLogger(__name__)

# reporter יוגדר ב-main בזמן ריצה דרך set_activity_reporter

# ---- DB access via composition facade --------------------------------------
def _get_files_facade_or_none():
    """Best-effort access to FilesFacade without importing `database` in handlers."""
    try:
        from src.infrastructure.composition import get_files_facade  # type: ignore
        return get_files_facade()
    except Exception:
        return None


def _call_files_api(method_name: str, *args, **kwargs):
    """
    Invoke FilesFacade method by name (no legacy DB fallback).
    """
    facade = _get_files_facade_or_none()
    if facade is not None:
        method = getattr(facade, method_name, None)
        if callable(method):
            try:
                return method(*args, **kwargs)
            except Exception:
                return None
    return None


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

        # Normalize filename input: trim, strip quotes/backticks/smart-quotes and remove zero-width/dir marks
        raw = " ".join(context.args)
        def _normalize_filename_input(s: str) -> str:
            s = s.strip()
            # Remove surrounding common quotes (ASCII + smart quotes)
            quotes = ['`', '"', "'", '“', '”', '‘', '’']
            if len(s) >= 2 and s[0] in quotes and s[-1] in quotes:
                s = s[1:-1]
            # Remove zero-width and formatting marks (category Cf)
            s = ''.join(ch for ch in s if unicodedata.category(ch) != 'Cf')
            # Replace non-breaking space with regular space and trim again
            s = s.replace('\u00A0', ' ').strip()
            return s
        filename = _normalize_filename_input(raw)

        # טעינת קובץ דרך הפסאדה (ללא import של database בתוך handlers)
        snippet = _call_files_api("get_latest_version", user_id, filename)
        if not snippet:
            snippet = _call_files_api("get_large_file", user_id, filename)

        # Fallback: השוואה בלתי-תלויה-רישיות + התאמת basename (עוזר במקרי נתיב מלא)
        if not snippet:
            # חשוב: לאחר רפקטור ה-Repository מחזיר ברירת מחדל רשימות ללא code/content כדי לשפר ביצועים.
            # לכן כאן משתמשים ברשימה רק כדי למצוא שם קובץ מתאים, ואז מבצעים Full Fetch ממוקד לקובץ הבודד.
            try:
                files = _call_files_api("get_user_files", user_id, limit=200) or []
            except Exception:
                files = []
            # צירוף קבצים גדולים לרשימה להשוואה בשם
            try:
                large_files, _ = _call_files_api("get_user_large_files", user_id, page=1, per_page=200) or ([], 0)
                # נסמן שמדובר בקובץ גדול כדי שנוכל לבצע full fetch נכון בהמשך
                marked_large: list[dict] = []
                try:
                    for lf in list(large_files or []):
                        if isinstance(lf, dict):
                            tmp = dict(lf)
                            tmp["_is_large_file"] = True
                            marked_large.append(tmp)
                except Exception:
                    marked_large = list(large_files or [])
                files = list(files or []) + marked_large
            except Exception:
                pass
            def _norm_for_match(s: str) -> str:
                try:
                    s = s or ""
                    # strip quotes/backticks/smart quotes if wrapped
                    q = ['`', '"', "'", '“', '”', '‘', '’']
                    if len(s) >= 2 and s[0] in q and s[-1] in q:
                        s = s[1:-1]
                    # remove zero-width and formatting marks
                    s = ''.join(ch for ch in s if unicodedata.category(ch) != 'Cf')
                    s = s.replace('\u00A0', ' ').strip()
                    return s.lower()
                except Exception:
                    return (s or '').strip().lower()
            try:
                target_lower = _norm_for_match(filename)
                base_lower = _norm_for_match(Path(filename).name)
            except Exception:
                target_lower = _norm_for_match(filename)
                base_lower = target_lower
            best: Optional[dict] = None
            for f in files or []:
                try:
                    name = str(f.get('file_name') or '')
                    if not name:
                        continue
                    nl = _norm_for_match(name)
                    nbase = _norm_for_match(Path(name).name)
                    if nl == target_lower or nbase == base_lower:
                        best = f
                        break
                except Exception:
                    continue
            if best is not None:
                # Full fetch ממוקד לפי שם הקובץ שנמצא
                try:
                    best_name = str(best.get("file_name") or "")
                except Exception:
                    best_name = ""
                if best_name:
                    try:
                        if bool(best.get("_is_large_file")):
                            snippet = _call_files_api("get_large_file", user_id, best_name)
                        else:
                            snippet = _call_files_api("get_latest_version", user_id, best_name)
                        if not snippet:
                            snippet = _call_files_api("get_large_file", user_id, best_name)
                    except Exception:
                        snippet = best
                else:
                    snippet = best

        if not snippet:
            await update.message.reply_text(
                f"❌ לא נמצא קובץ בשם `{filename}`\n\n"
                "השתמש ב-`/list` לראות את הקבצים שלך",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        # תמיכה גם במסמכי LargeFile שבהם התוכן תחת המפתח 'content'
        code = (snippet.get('code') if isinstance(snippet, dict) else None) or (snippet.get('content') if isinstance(snippet, dict) else None) or ''
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
        snippet = _call_files_api("get_latest_version", user_id, filename)
        if not snippet:
            snippet = _call_files_api("get_large_file", user_id, filename)
        if not snippet:
            await TelegramUtils.safe_edit_message_text(query, "❌ הקובץ לא נמצא")
            return
        code = (snippet.get('code') if isinstance(snippet, dict) else None) or (snippet.get('content') if isinstance(snippet, dict) else None) or ''
        await TelegramUtils.safe_edit_message_text(query, "🏗️ מנתח קוד ומכין הצעת רפקטורינג...\n⏳ זה יכול לקחת כמה שניות")
        try:
            refactor_type = RefactorType(refactor_type_str)
        except ValueError:
            await TelegramUtils.safe_edit_message_text(query, f"❌ סוג רפקטורינג לא חוקי: {refactor_type_str}")
            return
        # הפעלה לפי-בקשה: שכבות רק לקריאה הנוכחית (ללא שינוי ENV גלובלי)
        layered = True if refactor_type == RefactorType.SPLIT_FUNCTIONS else None
        result = refactoring_engine.propose_refactoring(
            code=code,
            filename=filename,
            refactor_type=refactor_type,
            layered_mode=layered,
        )
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
            [
                InlineKeyboardButton("✅ אשר ושמור", callback_data="refactor_action:approve"),
                InlineKeyboardButton("🐙 ייצוא ל-Gist", callback_data="refactor_action:export_gist"),
            ],
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
        if action == "export_gist":
            await self._export_gist(query, user_id, proposal)
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

    async def _export_gist(self, query, user_id: int, proposal: RefactorProposal) -> None:
        files_map = proposal.new_files or {}
        if not files_map:
            await query.message.reply_text("❌ אין קבצים לייצוא בהצעה הנוכחית.")
            return
        # ה-Gist נוצר תחת חשבון ה-GitHub של המשתמש, לא של המערכת.
        # הקריאה ניגשת ל-DB ולרשת ולכן רצה בת'רד נפרד.
        user_gist = None
        gist_error = "❌ ייצוא ל-Gist לא זמין כרגע."
        try:
            from integrations import resolve_gist_for_user

            user_gist, gist_error = await asyncio.to_thread(resolve_gist_for_user, user_id)
        except Exception:
            logger.exception("failed to resolve gist integration for user")
        if user_gist is None:
            await query.message.reply_text(gist_error)
            return
        description = (
            f"פיצול {proposal.original_file} ({len(files_map)} קבצים חדשים)"
            if proposal.refactor_type == RefactorType.SPLIT_FUNCTIONS
            else f"רפקטורינג {proposal.refactor_type.value} עבור {proposal.original_file}"
        )
        try:
            result = await asyncio.to_thread(
                user_gist.create_gist_multi,
                files_map=files_map,
                description=description,
                public=True,
            )
        except Exception as e:
            logger.error(f"שגיאה ביצירת Gist לרפקטורינג {proposal.original_file}: {e}", exc_info=True)
            result = None
        if not result or not result.get("url"):
            await query.message.reply_text("❌ יצירת Gist נכשלה. נסה שוב מאוחר יותר.")
            return
        logger.info(
            "המשתמש %s ייצא את הרפקטורינג %s ל-Gist בהצלחה: %s",
            user_id,
            proposal.original_file,
            result.get("url"),
        )
        await query.message.reply_text(
            "🐙 *הקבצים יוצאו ל-Gist!*\n\n"
            f"📄 {len(files_map)} קבצים חדשים\n"
            f"🔗 {result['url']}",
            parse_mode=ParseMode.MARKDOWN,
        )

    async def _approve_and_save(self, query, user_id: int, proposal: RefactorProposal):
        await TelegramUtils.safe_edit_message_text(query, "💾 שומר קבצים חדשים...")
        saved_count = 0
        errors = []
        tag = f"refactored_{proposal.refactor_type.value}"
        for filename, content in proposal.new_files.items():
            try:
                ok = bool(
                    _call_files_api(
                        "save_file",
                        user_id,
                        filename,
                        content,
                        "python",
                        extra_tags=[tag],
                    )
                )
                if ok:
                    saved_count += 1
                else:
                    errors.append(f"❌ {filename}: שמירה נכשלה")
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
            ok = bool(
                _call_files_api(
                "insert_refactor_metadata",
                {
                    "user_id": user_id,
                    "timestamp": datetime.now(timezone.utc),
                    "refactor_type": proposal.refactor_type.value,
                    "original_file": proposal.original_file,
                    "new_files": list((proposal.new_files or {}).keys()),
                    "changes_summary": list(proposal.changes_summary or []),
                },
                )
            )
            if not ok:
                # חשוב: הפסאדה מחזירה False על כשלי DB, ו-_call_files_api יכול לבלוע חריגות.
                logger.error("שמירת מטא-דאטה לרפקטורינג נכשלה (הפסאדה החזירה False/None)")
        except Exception as e:
            logger.error(f"שגיאה בשמירת מטא-דאטה: {e}")


def setup_refactor_handlers(application):
    """פונקציה להגדרת כל ה-handlers"""
    return RefactorHandlers(application)

