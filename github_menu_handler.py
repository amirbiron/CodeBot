# FIXED: Changed from Markdown to HTML parsing (2025-01-10)
# This fixes Telegram parsing errors with special characters in suggestions

from __future__ import annotations
import asyncio
import json
import logging
import os
import re
import time
import zipfile
from datetime import datetime, timezone
import tempfile
import shutil
from html import escape
from io import BytesIO
from typing import Any, Dict, Optional
import requests

from github import Github, GithubException
from github.InputGitTreeElement import InputGitTreeElement
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQueryResultArticle,
    InputTextMessageContent,
    Update,
)
from telegram.error import BadRequest
import secrets
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
)

from repo_analyzer import RepoAnalyzer
from config import config
from file_manager import backup_manager
from utils import TelegramUtils
try:
    # Optional backoff state
    from services import github_backoff_state  # type: ignore
except Exception:  # pragma: no cover
    github_backoff_state = None  # type: ignore
try:
    from observability import emit_event  # type: ignore
except Exception:  # pragma: no cover
    def emit_event(event: str, severity: str = "info", **fields):  # type: ignore
        return None
try:
    from metrics import track_performance, errors_total  # type: ignore
except Exception:  # pragma: no cover
    from contextlib import contextmanager
    errors_total = None  # type: ignore
    @contextmanager
    def track_performance(*a, **k):  # type: ignore
        yield
try:
    from metrics import track_github_sync  # type: ignore
except Exception:  # pragma: no cover
    def track_github_sync(*a, **k):  # type: ignore
        return None

# הגדרת לוגר
logger = logging.getLogger(__name__)

# מצבי שיחה
REPO_SELECT, FILE_UPLOAD, FOLDER_SELECT = range(3)

# מגבלות קבצים גדולים
MAX_INLINE_FILE_BYTES = 5 * 1024 * 1024  # 5MB לשליחה ישירה בבוט
MAX_ZIP_TOTAL_BYTES = 50 * 1024 * 1024  # 50MB לקובץ ZIP אחד
MAX_ZIP_FILES = 500  # מקסימום קבצים ב-ZIP אחד

# מגבלות ייבוא ריפו (ייבוא תוכן, לא גיבוי)
IMPORT_MAX_FILE_BYTES = 1 * 1024 * 1024  # 1MB לקובץ יחיד
IMPORT_MAX_TOTAL_BYTES = 20 * 1024 * 1024  # 20MB לכל הייבוא
IMPORT_MAX_FILES = 2000  # הגבלה סבירה למספר קבצים
# הרחבת רשימת תיקיות כבדות לדילוג בכל עומק עץ – משפר סריקה/קריאה לאחר חליצה
IMPORT_SKIP_DIRS = {
    ".git", ".github", "__pycache__", "node_modules", "dist", "build",
    "_build", "_static", "_images",  # תבניות שנפוצות תחת docs/
    ".venv", "venv", ".tox"
}

# מגבלות עזר לשליפת תאריכי ענפים למיון
MAX_BRANCH_DATE_FETCH = 120  # אם יש יותר מזה — נוותר על מיון לפי תאריך (למעט ברירת המחדל)

# תצוגת קובץ חלקית
VIEW_LINES_PER_PAGE = 80


def _safe_rmtree_tmp(target_path: str) -> None:
    """מחיקה בטוחה של תיקייה תחת /tmp בלבד, עם סורגי בטיחות.

    יזרוק חריגה אם הנתיב אינו תחת /tmp או שגוי.
    """
    try:
        if not target_path:
            return
        rp_target = os.path.realpath(target_path)
        rp_base = os.path.realpath("/tmp")
        if not rp_target.startswith(rp_base + os.sep):
            raise RuntimeError(f"Refusing to delete non-tmp path: {rp_target}")
        if rp_target in {"/", os.path.expanduser("~"), os.getcwd()}:
            raise RuntimeError(f"Refusing to delete unsafe path: {rp_target}")
        shutil.rmtree(rp_target, ignore_errors=True)
    except Exception:
        # לא מפסיק את הזרימה במקרה של שגיאה בניקוי
        pass


def safe_html_escape(text):
    """Escape text for Telegram HTML; preserves \n/\r/\t and keeps existing HTML entities.

    מרחיב ניקוי תווים בלתי נראים: ZWSP/ZWNJ/ZWJ, BOM/ZWNBSP, ותווי כיווניות LRM/RLM/LRE/RLE/PDF/LRO/RLO/LRI/RLI/FSI/PDI.
    """
    if text is None:
        return ""
    s = escape(str(text))
    # נקה תווים בלתי נראים (Zero-width) + BOM
    s = re.sub(r"[\u200b\u200c\u200d\u2060\ufeff]", "", s)
    # נקה סימוני כיווניות (Cf) נפוצים שגורמים לבלבול בהצגה
    s = re.sub(r"[\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069]", "", s)
    # נקה תווי בקרה אך השאר \n, \r, \t
    s = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]", "", s)
    return s


def format_bytes(num: int) -> str:
    """פורמט נחמד לגודל קובץ"""
    try:
        for unit in ["B", "KB", "MB", "GB"]:
            if num < 1024.0 or unit == "GB":
                return f"{num:.1f} {unit}" if unit != "B" else f"{int(num)} {unit}"
            num /= 1024.0
    except Exception:
        return str(num)
    return str(num)


class GitHubMenuHandler:
    def __init__(self):
        self.user_sessions: Dict[int, Dict[str, Any]] = {}
        self.last_api_call: Dict[int, float] = {}

    def get_user_session(self, user_id: int) -> Dict[str, Any]:
        """מחזיר או יוצר סשן משתמש בזיכרון"""
        if user_id not in self.user_sessions:
            # נסה לטעון ריפו מועדף מהמסד, עם נפילה בטוחה בסביבת בדיקות/CI
            selected_repo = None
            try:
                from database import db  # type: ignore
                try:
                    selected_repo = db.get_selected_repo(user_id)
                except Exception:
                    selected_repo = None
            except Exception:
                selected_repo = None
            self.user_sessions[user_id] = {
                "selected_repo": selected_repo,  # טען מהמסד נתונים
                "selected_folder": None,  # None = root של הריפו
                "github_token": None,
            }
        return self.user_sessions[user_id]

    # --- Date/time helpers ---
    def _to_utc_aware(self, dt: Optional[datetime]) -> Optional[datetime]:
        """Normalize datetime to timezone-aware UTC to avoid comparison errors.

        PyGithub often returns naive UTC datetimes. We must not compare
        naive and aware datetimes, so we coerce to aware UTC.
        """
        if dt is None:
            return None
        try:
            if dt.tzinfo is None:
                return dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            # Fallback: return as-is if unexpected type
            return dt

    async def show_browse_ref_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """תפריט בחירת ref (ענף/תג) עם עימוד וטאבים."""
        query = update.callback_query
        user_id = query.from_user.id
        session = self.get_user_session(user_id)
        token = self.get_user_token(user_id)
        repo_full = session.get("selected_repo")
        if not (token and repo_full):
            await query.edit_message_text("❌ חסר טוקן או ריפו נבחר")
            return
        g = Github(token)
        repo = g.get_repo(repo_full)
        current_ref = context.user_data.get("browse_ref") or (getattr(repo, "default_branch", None) or "main")
        tab = context.user_data.get("browse_ref_tab") or "branches"
        kb = []
        # טאבים
        tabs = [
            InlineKeyboardButton("🌿 ענפים", callback_data="browse_refs_branches_page_0"),
            InlineKeyboardButton("🏷 תגיות", callback_data="browse_refs_tags_page_0"),
        ]
        kb.append(tabs)
        if tab == "branches":
            page = int(context.user_data.get("browse_refs_branches_page", 0))
            try:
                items = list(repo.get_branches())
            except Exception:
                items = []
            page_size = 10
            start = page * page_size
            end = min(start + page_size, len(items))
            for br in items[start:end]:
                label = "✅ " + br.name if br.name == current_ref else br.name
                kb.append([InlineKeyboardButton(label, callback_data=f"browse_select_ref:{br.name}")])
            # עימוד
            nav = []
            if page > 0:
                nav.append(InlineKeyboardButton("⬅️ הקודם", callback_data=f"browse_refs_branches_page_{page-1}"))
            if end < len(items):
                nav.append(InlineKeyboardButton("הבא ➡️", callback_data=f"browse_refs_branches_page_{page+1}"))
            if nav:
                kb.append(nav)
        else:
            page = int(context.user_data.get("browse_refs_tags_page", 0))
            try:
                items = list(repo.get_tags())
            except Exception:
                items = []
            page_size = 10
            start = page * page_size
            end = min(start + page_size, len(items))
            for tg in items[start:end]:
                name = getattr(tg, "name", "")
                label = "✅ " + name if name == current_ref else name
                kb.append([InlineKeyboardButton(label, callback_data=f"browse_select_ref:{name}")])
            nav = []
            if page > 0:
                nav.append(InlineKeyboardButton("⬅️ הקודם", callback_data=f"browse_refs_tags_page_{page-1}"))
            if end < len(items):
                nav.append(InlineKeyboardButton("הבא ➡️", callback_data=f"browse_refs_tags_page_{page+1}"))
            if nav:
                kb.append(nav)
        # תחתית
        kb.append([InlineKeyboardButton("🔙 חזרה", callback_data="github_menu")])
        await query.edit_message_text(
            f"בחר/י ref לדפדוף (נוכחי: <code>{safe_html_escape(current_ref)}</code>)",
            reply_markup=InlineKeyboardMarkup(kb),
            parse_mode="HTML",
        )

    async def show_browse_search_results(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """חיפוש לפי שם קובץ (prefix/contains) עם עימוד ותוצאות לפתיחה."""
        # שימוש ב-Contents API: אין חיפוש שמות ישיר; נשתמש ב-Search API code:in:path/name
        query = update.callback_query if hasattr(update, "callback_query") else None
        user_id = (query.from_user.id if query else update.message.from_user.id)
        session = self.get_user_session(user_id)
        token = self.get_user_token(user_id)
        repo_full = session.get("selected_repo")
        q = (context.user_data.get("browse_search_query") or "").strip()
        page = int(context.user_data.get("browse_search_page", 1))
        if not (token and repo_full and q):
            if query:
                await query.edit_message_text("❌ חסרים נתונים לחיפוש")
            else:
                await update.message.reply_text("❌ חסרים נתונים לחיפוש")
            return
        g = Github(token)
        # הפורמט: repo:owner/name in:path <query>
        try:
            owner, name = repo_full.split("/", 1)
        except ValueError:
            owner, name = repo_full, ""
        # בניית שאילתה: נחפש במחרוזת הנתיב בלבד (in:name לא נתמך ב-code search)
        q_safe = (q or "").replace('"', ' ').strip()
        term = f'"{q_safe}"' if (" " in q_safe) else q_safe
        gh_query = f"repo:{owner}/{name} in:path {term}"
        try:
            # PyGithub מחזיר PaginatedList; נהפוך לרשימה בטוחה עם הגבלה כדי למנוע 403/timeout
            results = list(g.search_code(query=gh_query, order="desc"))
        except BadRequest as br:
            # ננהל את טלגרם "message is not modified" בעדינות
            if "message is not modified" in str(br).lower():
                try:
                    await query.answer("אין שינוי בתוצאה")
                except Exception:
                    pass
                return
            raise
        except Exception as e:
            try:
                if hasattr(update, "callback_query") and update.callback_query:
                    await update.callback_query.answer(f"שגיאה בחיפוש: {str(e)}", show_alert=True)
                else:
                    await update.message.reply_text(f"❌ שגיאה בחיפוש: {str(e)}")
            except Exception:
                pass
            return
        # עימוד ידני
        per_page = 10
        items = results  # כבר רשימה
        if not items:
            msg = f"🔎 אין תוצאות עבור <code>{safe_html_escape(q)}</code> ב-<code>{safe_html_escape(repo_full)}</code>"
            if query:
                await query.edit_message_text(msg, parse_mode="HTML", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 חזרה", callback_data="github_menu")]]))
            else:
                await update.message.reply_text(msg, parse_mode="HTML")
            return
        total = len(items)
        start = (page - 1) * per_page
        end = min(start + per_page, total)
        shown = items[start:end]
        # אפס מיפוי אינדקסים למסך זה (ל-callback קצרים)
        context.user_data["browse_idx_map"] = {}
        # סימון מצב: תצוגת תוצאות חיפוש פעילה (לצורך חזרה אחורה מתצוגת קובץ)
        context.user_data["last_results_were_search"] = True
        kb = []
        for it in shown:
            try:
                path = getattr(it, "path", None) or getattr(it, "name", "")
                if not path:
                    continue
                view_cb = self._mk_cb(context, "browse_select_view", path)
                # כפתור יחיד: "path 👁️" לצפייה בקובץ
                kb.append([
                    InlineKeyboardButton(f"{path} 👁️", callback_data=view_cb)
                ])
            except Exception:
                continue
        nav = []
        total_pages = max(1, (total + per_page - 1) // per_page)
        if page > 1:
            nav.append(InlineKeyboardButton("⬅️ הקודם", callback_data=f"browse_search_page:{page-1}"))
        if page < total_pages:
            nav.append(InlineKeyboardButton("הבא ➡️", callback_data=f"browse_search_page:{page+1}"))
        if nav:
            kb.append(nav)
        kb.append([InlineKeyboardButton("🔙 חזרה", callback_data="github_menu")])
        text = f"🔎 תוצאות חיפוש עבור <code>{safe_html_escape(q)}</code> — מציג {len(shown)} מתוך {total}"
        if query:
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")
        else:
            await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")

    async def check_rate_limit(self, github_client: Github, update_or_query) -> bool:
        """בודק את מגבלת ה-API של GitHub"""
        try:
            rate_limit = github_client.get_rate_limit()
            core_limit = rate_limit.core

            if core_limit.remaining < 10:
                reset_time = core_limit.reset
                minutes_until_reset = max(1, int((reset_time - time.time()) / 60))

                error_message = (
                    f"⏳ חריגה ממגבלת GitHub API\n"
                    f"נותרו רק {core_limit.remaining} בקשות\n"
                    f"המגבלה תתאפס בעוד {minutes_until_reset} דקות\n\n"
                    f"💡 נסה שוב מאוחר יותר"
                )

                # בדוק אם זה callback query או update רגיל
                if hasattr(update_or_query, "answer"):
                    # זה callback query
                    await update_or_query.answer(error_message, show_alert=True)
                else:
                    # זה update רגיל
                    await update_or_query.message.reply_text(error_message)

                return False

            # Respect global backoff switch: if active, warn once and proceed (gate elsewhere)
            try:
                if github_backoff_state is not None and github_backoff_state.get().is_active():
                    msg = "⚠️ Backoff פעיל – ייתכנו השהיות בין קריאות API"
                    if hasattr(update_or_query, "answer"):
                        await update_or_query.answer(msg, show_alert=False)
                    else:
                        await update_or_query.message.reply_text(msg)
            except Exception:
                pass
            return True
        except Exception as e:
            logger.error(f"Error checking rate limit: {e}")
            try:
                emit_event("github_rate_limit_check_error", severity="error", error=str(e))
                if errors_total is not None:
                    errors_total.labels(code="github_rate_limit_check_error").inc()
            except Exception:
                pass
            return True  # במקרה של שגיאה, נמשיך בכל זאת

    async def apply_rate_limit_delay(self, user_id: int):
        """מוסיף השהייה בין בקשות API; מכבד מצב Backoff גלובלי."""
        base_delay = 2.0
        try:
            if github_backoff_state is not None and github_backoff_state.get().is_active():
                # Increase delay under backoff to reduce pressure
                base_delay = 5.0
        except Exception:
            pass
        current_time = time.time()
        last_call = self.last_api_call.get(user_id, 0.0)
        time_since_last = current_time - last_call
        if time_since_last < base_delay:
            await asyncio.sleep(base_delay - time_since_last)
        self.last_api_call[user_id] = time.time()

    def get_user_token(self, user_id: int) -> Optional[str]:
        """מקבל טוקן של משתמש - מהסשן או מהמסד נתונים"""
        session = self.get_user_session(user_id)

        # נסה מהסשן
        token = session.get("github_token")
        if token:
            return token

        # נסה מהמסד נתונים
        from database import db

        token = db.get_github_token(user_id)
        if token:
            # שמור בסשן לשימוש מהיר
            session["github_token"] = token

        return token

    # --- Helpers to keep Telegram callback_data <= 64 bytes ---
    def _mk_cb(self, context: ContextTypes.DEFAULT_TYPE, prefix: str, path: str) -> str:
        """יוצר callback_data בטוח. אם ארוך מדי, משתמש באינדקס זמני במפה ב-context.user_data."""
        safe_path = path or ""
        data = f"{prefix}:{safe_path}"
        try:
            if len(data.encode('utf-8')) <= 64:
                return data
        except Exception:
            if len(data) <= 64:
                return data
        idx_map = context.user_data.get("browse_idx_map")
        if not isinstance(idx_map, dict):
            idx_map = {}
            context.user_data["browse_idx_map"] = idx_map
        idx = str(len(idx_map) + 1)
        idx_map[idx] = safe_path
        return f"{prefix}_i:{idx}"

    def _get_path_from_cb(self, context: ContextTypes.DEFAULT_TYPE, data: str, prefix: str) -> str:
        """שחזור נתיב מתוך callback_data רגיל או ממופה (_i:)."""
        try:
            if data.startswith(prefix + ":"):
                return data.split(":", 1)[1]
            if data.startswith(prefix + "_i:"):
                idx = data.split(":", 1)[1]
                m = context.user_data.get("browse_idx_map") or {}
                return m.get(idx, "")
        except Exception:
            return ""
        return ""

    async def _render_file_view(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """מציג דף תצוגה חלקית של קובץ עם כפתורי 'הצג עוד', 'הורד', 'חזרה'."""
        query = update.callback_query
        user_id = query.from_user.id
        session = self.get_user_session(user_id)
        repo_name = session.get("selected_repo") or "repo"
        path = context.user_data.get("view_file_path") or ""
        data = context.user_data.get("view_file_text") or ""
        page = int(context.user_data.get("view_page_index", 0))
        # חישוב חלוקה לשורות
        lines = data.splitlines()
        total_lines = len(lines)
        start = page * VIEW_LINES_PER_PAGE
        end = min(start + VIEW_LINES_PER_PAGE, total_lines)
        chunk = "\n".join(lines[start:end])
        # טקסט לתצוגה + גודל ושפה מזוהה
        size_bytes = int(context.user_data.get("view_file_size", 0) or 0)
        lang = context.user_data.get("view_detected_language") or "text"
        header = (
            f"📄 תצוגת קובץ\n"
            f"📁 <code>{safe_html_escape(repo_name)}</code>\n"
            f"📄 <code>{safe_html_escape(path)}</code>\n"
            f"🔤 שפה: <code>{safe_html_escape(lang)}</code> | 💾 גודל: <code>{format_bytes(size_bytes)}</code>\n"
            f"שורות {start+1}-{end} מתוך {total_lines}\n\n"
        )
        # בניית מקלדת
        rows = [[InlineKeyboardButton("🔙 חזרה", callback_data="view_back")],
                [InlineKeyboardButton("⬇️ הורד", callback_data=self._mk_cb(context, "browse_select_download", path))]]
        # כפתור שיתוף קישור לקובץ – רק במסך התצוגה (לא ברשימה)
        rows.append([InlineKeyboardButton("🔗 שתף קישור", callback_data=self._mk_cb(context, "share_selected_links_single", path))])
        if end < total_lines:
            rows.append([InlineKeyboardButton("הצג עוד ⤵️", callback_data="view_more")])
        try:
            # הדגשת תחביר קיימת במודול code_processor.highlight_code; נשתמש בה ואז ננקה ל-Telegram
            try:
                from services import code_service as code_processor
                # פורמט שמירת שורות כברירת מחדל
                lower_path = (path or '').lower()
                # אם YAML – נסה צביעה ישירה, אחרת כללי
                if lower_path.endswith('.yml') or lower_path.endswith('.yaml'):
                    try:
                        highlighted_html = code_processor.highlight_code(chunk, 'yaml')
                        body = highlighted_html or f"<pre>{safe_html_escape(chunk)}</pre>"
                    except Exception:
                        body = f"<pre>{safe_html_escape(chunk)}</pre>"
                else:
                    # שמירת שורות בכוח עבור סוגי קבצים רגישים לעיצוב
                    force_pre_exts = ('.md', '.markdown', '.py')
                    if lower_path.endswith(force_pre_exts):
                        body = f"<pre>{safe_html_escape(chunk)}</pre>"
                    else:
                        # נסה היילייט; אם יוצרת בלגן, fallback ל-pre
                        try:
                            highlighted_html = code_processor.highlight_code(chunk, lang)
                            if not highlighted_html or '\n' not in chunk:
                                body = f"<pre>{safe_html_escape(chunk)}</pre>"
                            else:
                                body = highlighted_html
                        except Exception:
                            body = f"<pre>{safe_html_escape(chunk)}</pre>"
            except Exception:
                body = f"<pre>{safe_html_escape(chunk)}</pre>"
            await query.edit_message_text(header + body, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(rows))
        except BadRequest as br:
            if "message is not modified" not in str(br).lower():
                raise

    async def show_import_branch_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """מציג בחירת ענף לייבוא ריפו (עימוד)."""
        query = update.callback_query
        user_id = query.from_user.id
        session = self.get_user_session(user_id)
        token = self.get_user_token(user_id)
        repo_full = session.get("selected_repo") or ""
        if not (token and repo_full):
            await query.edit_message_text("❌ חסר טוקן או ריפו נבחר")
            return
        # הודעת טעינה בזמן שליפת הענפים
        try:
            await TelegramUtils.safe_edit_message_text(query, "⏳ טוען רשימת ענפים…")
        except Exception:
            pass
        g = Github(token)
        try:
            repo = g.get_repo(repo_full)
        except Exception as e:
            try:
                # אין ענף בשלב זה; דווח רק על הריפו
                emit_event("github_import_repo_error", severity="error", error=str(e), repo=repo_full)
            except Exception:
                pass
            await query.edit_message_text(f"❌ שגיאה בטעינת ריפו: {e}")
            return
        try:
            branches = list(repo.get_branches())
            # מיין: main ראשון; אחריו לפי עדכון commit אחרון (חדש→ישן)
            def _branch_sort_key(br):
                try:
                    # commit.last_modified לא קיים תמיד; ניקח commit.commit.author.date
                    return br.commit.commit.author.date
                except Exception:
                    return datetime.min.replace(tzinfo=timezone.utc)
            # רשימת ענפים מלאה
            if len(branches) <= MAX_BRANCH_DATE_FETCH:
                try:
                    branches_sorted = sorted(branches, key=_branch_sort_key, reverse=True)
                except Exception:
                    branches_sorted = branches
            else:
                branches_sorted = branches
            # הוצא main לראש (אם קיים)
            main_idx = next((i for i, b in enumerate(branches_sorted) if (b.name == 'main' or b.name == 'master')), None)
            if main_idx is not None:
                main_br = branches_sorted.pop(main_idx)
                branches_sorted.insert(0, main_br)
            branches = branches_sorted
        except Exception as e:
            await query.edit_message_text(f"❌ שגיאה בשליפת ענפים: {e}")
            return
        page = int(context.user_data.get("import_branches_page", 0))
        page_size = 8
        total_pages = max(1, (len(branches) + page_size - 1) // page_size)
        start = page * page_size
        end = min(start + page_size, len(branches))
        keyboard = []
        # מיפוי אסימונים קצרים לשמות ענפים כדי לעמוד במגבלת 64 בתים של Telegram
        token_map = context.user_data.setdefault("import_branch_token_map", {})
        # תצוגה אחידה: main ראשון (כבר מוקפץ למעלה במיון) ואז כל הענפים – ממוינים מהחדש לישן
        for idx, br in enumerate(branches[start:end]):
            token = f"i{start + idx}"
            token_map[token] = br.name
            label = f"🌿 {br.name}"
            keyboard.append([InlineKeyboardButton(label, callback_data=f"import_repo_select_branch:{token}")])
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton("⬅️ הקודם", callback_data=f"import_repo_branches_page_{page-1}"))
        nav.append(InlineKeyboardButton(f"📄 {page+1}/{total_pages}", callback_data="noop"))
        if page < total_pages - 1:
            nav.append(InlineKeyboardButton("הבא ➡️", callback_data=f"import_repo_branches_page_{page+1}"))
        if nav:
            keyboard.append(nav)
        keyboard.append([InlineKeyboardButton("🔙 חזור", callback_data="github_menu")])
        await query.edit_message_text(
            "⬇️ בחר/י ענף לייבוא קבצים מהריפו:", reply_markup=InlineKeyboardMarkup(keyboard)
        )

    async def _confirm_import_repo(self, update: Update, context: ContextTypes.DEFAULT_TYPE, branch: str):
        """מסך אישור לייבוא עם הסבר קצר כדי למנוע בלבול עם גיבויים."""
        query = update.callback_query
        user_id = query.from_user.id
        session = self.get_user_session(user_id)
        repo_full = session.get("selected_repo") or ""
        text = (
            f"⬇️ ייבוא ריפו מ-GitHub\n\n"
            f"זהו <b>ייבוא קבצים</b> ולא יצירת גיבוי ZIP.\n"
            f"נוריד ZIP רשמי, נחלץ ל-/tmp, נקלט לקבצים במסד עם תגיות:\n"
            f"<code>repo:{repo_full}</code>, <code>source:github</code>\n\n"
            f"נכבד מגבלות גודל/כמות, נדלג על בינאריים ו-<code>.git</code> ותיקיות מיותרות.\n"
            f"ענף: <code>{branch}</code>\n\n"
            f"להמשיך?"
        )
        kb = [
            [InlineKeyboardButton("✅ כן, ייבא", callback_data="import_repo_start")],
            [InlineKeyboardButton("❌ ביטול", callback_data="import_repo_cancel")],
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")

    async def import_repo_from_zip(self, update: Update, context: ContextTypes.DEFAULT_TYPE, repo_full: str, branch: str):
        """מוריד ZIP רשמי של GitHub (zipball) לענף, מחלץ ל-tmp, ומקליט קבצים ל-DB עם תגיות repo/source.

        שמירה: CodeSnippet לקבצים טקסטואליים קטנים (עד IMPORT_MAX_FILE_BYTES) עד סך IMPORT_MAX_TOTAL_BYTES ומקס' IMPORT_MAX_FILES.
        מדלג על בינאריים, קבצי ענק, ותיקיות מיותרות. מנקה tmp בסוף.
        """
        query = update.callback_query
        user_id = query.from_user.id
        token = self.get_user_token(user_id)
        if not token:
            try:
                emit_event("github_import_repo_error", severity="error", error="missing_token", repo=repo_full, branch=branch)
            except Exception:
                pass
            await query.edit_message_text("❌ חסר טוקן GitHub")
            return
        # יצירת לקוח GitHub
        try:
            g = Github(token)
        except Exception as e:
            try:
                emit_event("github_import_repo_error", severity="error", error=str(e), repo=repo_full, branch=branch)
            except Exception:
                pass
            await query.edit_message_text(f"❌ שגיאה בהכנת חיבור ל‑GitHub: {e}")
            return
        try:
            repo = g.get_repo(repo_full)
        except Exception as e:
            await query.edit_message_text(f"❌ שגיאה בטעינת ריפו: {e}")
            return
        await query.edit_message_text("⏳ מוריד ZIP רשמי ומייבא קבצים… זה עשוי לקחת 1–8 דקות")
        import zipfile as _zip
        tmp_dir = None
        zip_path = None
        extracted_dir = None
        saved = 0
        updated = 0
        total_bytes = 0
        skipped = 0
        try:
            # קבלת קישור zipball עבור branch
            try:
                url = repo.get_archive_link("zipball", ref=branch)
            except TypeError:
                # גרסאות PyGithub ישנות לא מקבלות ref; ננסה ללא ref
                url = repo.get_archive_link("zipball")
            resp = requests.get(url, timeout=60)
            resp.raise_for_status()
            # עבודה ב-/tmp בלבד
            tmp_dir = tempfile.mkdtemp(prefix="codebot-gh-import-")
            zip_path = os.path.join(tmp_dir, "repo.zip")
            with open(zip_path, "wb") as f:
                f.write(resp.content)
            # חליצה לתת-תיקייה ייעודית
            extracted_dir = os.path.join(tmp_dir, "repo")
            os.makedirs(extracted_dir, exist_ok=True)
            # מדוד זמן חליצה
            with track_performance("github_zip_extract"):
                with _zip.ZipFile(zip_path, 'r') as zf:
                    zf.extractall(extracted_dir)
            # מצא שורש (github zip מוסיף תיקיית prefix)
            # נבחר תיקייה הראשונה מתחת extracted_dir
            roots = [os.path.join(extracted_dir, d) for d in os.listdir(extracted_dir)]
            root = None
            for p in roots:
                if os.path.isdir(p):
                    root = p
                    break
            if not root:
                await query.edit_message_text("❌ לא נמצאו קבצים לאחר חליצה")
                return
            from database import db
            from utils import detect_language_from_filename
            repo_tag = f"repo:{repo_full}"
            source_tag = "source:github"
            # מעבר על קבצים
            for cur_dir, dirnames, filenames in os.walk(root):
                # סינון תיקיות מיותרות
                dirnames[:] = [d for d in dirnames if d not in IMPORT_SKIP_DIRS]
                for name in filenames:
                    # דלג על קבצי ZIP עצמם או קבצים מוסתרים ענקיים
                    if name.endswith('.zip'):
                        skipped += 1
                        continue
                    file_path = os.path.join(cur_dir, name)
                    rel_path = os.path.relpath(file_path, root)
                    # דלג על נתיבים חשודים
                    if rel_path.startswith('.'):
                        skipped += 1
                        continue
                    try:
                        # קרא כ-bytes ובדוק בינארי/גודל
                        with open(file_path, 'rb') as fh:
                            raw = fh.read(IMPORT_MAX_FILE_BYTES + 1)
                        if len(raw) > IMPORT_MAX_FILE_BYTES:
                            skipped += 1
                            continue
                        # heuristic: אם יש אפס-בייטים רבים → כנראה בינארי
                        if b"\x00" in raw:
                            skipped += 1
                            continue
                        try:
                            text = raw.decode('utf-8')
                        except Exception:
                            try:
                                text = raw.decode('latin-1')
                            except Exception:
                                skipped += 1
                                continue
                        if total_bytes + len(raw) > IMPORT_MAX_TOTAL_BYTES:
                            continue
                        if saved >= IMPORT_MAX_FILES:
                            continue
                        lang = detect_language_from_filename(rel_path)
                        # בדוק אם קיים כבר עבור אותו ריפו (לפי תגית repo:)
                        prev_doc = db.get_latest_version(user_id, rel_path)
                        prev_tags = (prev_doc.get('tags') or []) if isinstance(prev_doc, dict) else []
                        existed_for_repo = any((isinstance(t, str) and t == repo_tag) for t in prev_tags)
                        # מדידת ביצוע עבור שמירה בודדת
                        with track_performance("github_import_save_file"):
                            ok = db.save_file(user_id=user_id, file_name=rel_path, code=text, programming_language=lang, extra_tags=[repo_tag, source_tag])
                        if ok:
                            if existed_for_repo:
                                updated += 1
                            else:
                                saved += 1
                            total_bytes += len(raw)
                        else:
                            skipped += 1
                    except Exception:
                        skipped += 1
            try:
                track_github_sync(user_id=user_id, files_count=saved + updated, success=True)
                emit_event("github_sync", severity="info", user_id=int(user_id), files_count=int(saved + updated), success=True)
            except Exception:
                pass
            await query.edit_message_text(
                f"✅ ייבוא הושלם: {saved} חדשים, {updated} עודכנו, {skipped} דילוגים.\n"
                f"🔖 תיוג: <code>{repo_tag}</code> (ו-<code>{source_tag}</code>)\n\n"
                f"ℹ️ זהו ייבוא תוכן — לא נוצר גיבוי ZIP.\n"
                f"תוכל למצוא את הקבצים ב׳🗂 לפי ריפו׳.",
                parse_mode="HTML",
            )
        except Exception as e:
            try:
                emit_event("github_import_repo_error", severity="error", error=str(e), repo=repo_full, branch=branch)
            except Exception:
                pass
            await query.edit_message_text(f"❌ שגיאה בייבוא: {e}")
        finally:
            # ניקוי בטוח של tmp ושל קובץ ה-ZIP
            try:
                if zip_path and os.path.exists(zip_path):
                    os.remove(zip_path)
            except Exception:
                pass
            _safe_rmtree_tmp(extracted_dir or "")
            _safe_rmtree_tmp(tmp_dir or "")

    async def github_menu_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """מציג תפריט GitHub"""
        user_id = update.effective_user.id

        session = self.get_user_session(user_id)
        token = self.get_user_token(user_id)

        # נקה דגלי זרימת "הדבק קוד" אם היו פעילים, כדי למנוע תקיעה בזרימה
        try:
            context.user_data.pop("waiting_for_paste_content", None)
            context.user_data.pop("waiting_for_paste_filename", None)
            context.user_data.pop("paste_content", None)
        except Exception:
            pass

        # בנה הודעת סטטוס
        status_msg = "<b>🔧 תפריט GitHub</b>\n\n"
        if token:
            status_msg += "🔑 <b>מחובר ל-GitHub</b>\n"
        else:
            status_msg += "🔒 <b>לא מחובר</b>\n"
        if session.get("selected_repo"):
            status_msg += f"📁 ריפו נבחר: <code>{session['selected_repo']}</code>\n"
        if session.get("selected_folder"):
            status_msg += f"📂 תיקיית יעד: <code>{session['selected_folder']}</code>\n"

        keyboard = []

        # כפתור הגדרת טוקן
        if not token:
            keyboard.append(
                [InlineKeyboardButton("🔑 הגדר טוקן GitHub", callback_data="set_token")]
            )

        # כפתור בחירת ריפו - זמין רק עם טוקן
        if token:
            keyboard.append([InlineKeyboardButton("📁 בחר ריפו", callback_data="select_repo")])
            # יצירת ריפו חדש מ-ZIP גם ללא ריפו נבחר
            keyboard.append([InlineKeyboardButton("🆕 צור ריפו חדש מּZIP", callback_data="github_create_repo_from_zip")])

        # כפתורי העלאה - מוצגים רק אם יש ריפו נבחר
        if token and session.get("selected_repo"):
            # העבר את "בחר תיקיית יעד" למעלה, ישירות אחרי "בחר ריפו"
            keyboard.append([InlineKeyboardButton("📂 בחר תיקיית יעד", callback_data="set_folder")])
            # ניווט בריפו
            keyboard.append([InlineKeyboardButton("🗃️ עיין בריפו", callback_data="browse_repo")])
            # כפתור העלאה
            keyboard.append([InlineKeyboardButton("📤 העלה קובץ חדש", callback_data="upload_file")])
            # פעולות נוספות בטוחות
            keyboard.append(
                [InlineKeyboardButton("📥 הורד קובץ מהריפו", callback_data="download_file_menu")]
            )
            # כפתור ייבוא ריפו (ZIP רשמי → ייבוא קבצים ל-DB)
            keyboard.append(
                [InlineKeyboardButton("⬇️ הורד ריפו", callback_data="github_import_repo")]
            )
            # ריכוז פעולות מחיקה בתפריט משנה
            keyboard.append(
                [InlineKeyboardButton("🧨 מחק קובץ/ריפו שלם", callback_data="danger_delete_menu")]
            )
            # התראות חכמות
            keyboard.append(
                [InlineKeyboardButton("🔔 התראות חכמות", callback_data="notifications_menu")]
            )
            # תפריט גיבוי/שחזור מרוכז
            keyboard.append(
                [InlineKeyboardButton("🧰 גיבוי ושחזור", callback_data="github_backup_menu")]
            )

        # כפתור ניתוח ריפו - תמיד מוצג אם יש טוקן
        if token:
            keyboard.append([InlineKeyboardButton("🔍 נתח ריפו", callback_data="analyze_repo")])
            keyboard.append([InlineKeyboardButton("✅ בדוק תקינות ריפו", callback_data="validate_repo")])
            # כפתור יציאה (מחיקת טוקן) כאשר יש טוקן
            keyboard.append(
                [InlineKeyboardButton("🚪 התנתק מגיטהאב", callback_data="logout_github")]
            )

        # כפתור הצגת הגדרות
        keyboard.append(
            [InlineKeyboardButton("📋 הצג הגדרות נוכחיות", callback_data="show_current")]
        )

        # כפתור סגירה
        keyboard.append([InlineKeyboardButton("❌ סגור", callback_data="close_menu")])

        reply_markup = InlineKeyboardMarkup(keyboard)

        if update.callback_query:
            await update.callback_query.edit_message_text(
                status_msg, reply_markup=reply_markup, parse_mode="HTML"
            )
        else:
            await update.message.reply_text(
                status_msg, reply_markup=reply_markup, parse_mode="HTML"
            )
    async def handle_menu_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle menu button clicks"""
        query = update.callback_query
        logger.info(
            f"📱 GitHub handler received callback: {query.data} from user {query.from_user.id}"
        )
        try:
            emit_event(
                "github_callback_received",
                severity="info",
                action=str(getattr(query, "data", "")),
                user_id=int(getattr(getattr(query, "from_user", None), "id", 0) or 0),
            )
        except Exception:
            pass
        await query.answer()

        user_id = query.from_user.id
        session = self.get_user_session(user_id)

        if query.data == "select_repo":
            await self.show_repo_selection(query, context)

        elif query.data == "browse_repo":
            # מצב עיון בריפו עם תצוגת קבצים
            context.user_data["browse_action"] = "view"
            context.user_data["browse_path"] = ""
            context.user_data["browse_page"] = 0
            context.user_data["multi_mode"] = False
            context.user_data["multi_selection"] = []
            await self.show_repo_browser(update, context)

        elif query.data == "upload_file":
            if not session.get("selected_repo"):
                await query.edit_message_text("❌ קודם בחר ריפו!\nשלח /github ובחר 'בחר ריפו'")
            else:
                folder_display = session.get("selected_folder") or "root"
                keyboard = [
                    [InlineKeyboardButton("✍️ הדבק קוד", callback_data="upload_paste_code")],
                    [InlineKeyboardButton("🗂 לפי ריפו", callback_data="gh_upload_cat:repos")],
                    [InlineKeyboardButton("📦 קבצי ZIP", callback_data="gh_upload_cat:zips")],
                    [InlineKeyboardButton("📂 קבצים גדולים", callback_data="gh_upload_cat:large")],
                    [InlineKeyboardButton("📁 שאר הקבצים", callback_data="gh_upload_cat:other")],
                    [InlineKeyboardButton("🔙 חזור", callback_data="github_menu")],
                ]
                await query.edit_message_text(
                    f"📤 <b>העלאת קובץ לריפו</b>\n"
                    f"ריפו: <code>{session['selected_repo']}</code>\n"
                    f"📂 תיקייה: <code>{folder_display}</code>\n\n"
                    f"בחר מקור להעלאה:",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode="HTML",
                )
                return
        elif query.data == "cancel_paste_flow":
            # ביטול מפורש של זרימת "הדבק קוד": נקה דגלים וחזור לתפריט העלאה
            try:
                context.user_data.pop("waiting_for_paste_content", None)
                context.user_data.pop("waiting_for_paste_filename", None)
                context.user_data.pop("paste_content", None)
            except Exception:
                pass
            # נווט חזרה למסך "העלה קובץ חדש"
            # על ידי קריאה עצמית לסעיף upload_file
            if not session.get("selected_repo"):
                await query.edit_message_text("❌ קודם בחר ריפו!\nשלח /github ובחר 'בחר ריפו'")
            else:
                folder_display = session.get("selected_folder") or "root"
                keyboard = [
                    [InlineKeyboardButton("✍️ הדבק קוד", callback_data="upload_paste_code")],
                    [InlineKeyboardButton("🗂 לפי ריפו", callback_data="gh_upload_cat:repos")],
                    [InlineKeyboardButton("📦 קבצי ZIP", callback_data="gh_upload_cat:zips")],
                    [InlineKeyboardButton("📂 קבצים גדולים", callback_data="gh_upload_cat:large")],
                    [InlineKeyboardButton("📁 שאר הקבצים", callback_data="gh_upload_cat:other")],
                    [InlineKeyboardButton("🔙 חזור", callback_data="github_menu")],
                ]
                await query.edit_message_text(
                    f"📤 <b>העלאת קובץ לריפו</b>\n"
                    f"ריפו: <code>{session['selected_repo']}</code>\n"
                    f"📂 תיקייה: <code>{folder_display}</code>\n\n"
                    f"בחר מקור להעלאה:",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode="HTML",
                )
            return
        elif query.data == "upload_paste_code":
            # התחלת זרימת "הדבק קוד"
            # נקה דגלים ישנים
            try:
                context.user_data.pop("waiting_for_paste_content", None)
                context.user_data.pop("waiting_for_paste_filename", None)
                context.user_data.pop("paste_content", None)
            except Exception:
                pass
            context.user_data["waiting_for_paste_content"] = True
            await query.edit_message_text(
                "✍️ שלח/י כאן את הקוד להעלאה כטקסט.\n\n"
                "לאחר מכן אבקש את שם הקובץ (כולל סיומת).",
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("🔙 חזור", callback_data="upload_file"),
                        InlineKeyboardButton("❌ ביטול", callback_data="cancel_paste_flow"),
                    ]
                ]),
            )
            return
        elif query.data == "gh_upload_cat:repos":
            await self.show_upload_repos(update, context)
        elif query.data == "gh_upload_cat:zips":
            # הצג את כל קבצי ה‑ZIP ששמורים בבוט, ללא סינון לפי ריפו
            try:
                context.user_data['zip_back_to'] = 'github_upload'
                context.user_data.pop('github_backup_context_repo', None)
            except Exception:
                pass
            backup_handler = context.bot_data.get('backup_handler')
            if backup_handler is None:
                try:
                    from backup_menu_handler import BackupMenuHandler  # טעינה עצלה למניעת תלות מעגלית
                    backup_handler = BackupMenuHandler()
                    context.bot_data['backup_handler'] = backup_handler
                except Exception as e:
                    await query.edit_message_text(f"❌ רכיב גיבוי לא זמין: {e}")
                    return
            try:
                await backup_handler._show_backups_list(update, context, page=1)
            except Exception as e:
                await query.edit_message_text(f"❌ שגיאה בטעינת קבצי ZIP: {e}")
        elif query.data.startswith("gh_upload_zip_browse:"):
            # עיון בקובץ ZIP שמור ובחירת קובץ מתוכו להעלאה לריפו
            backup_id = query.data.split(":", 1)[1]
            user_id = query.from_user.id
            session = self.get_user_session(user_id)
            token = self.get_user_token(user_id)
            repo_name = session.get("selected_repo")
            if not (token and repo_name):
                await query.edit_message_text("❌ חסרים נתונים (בחר ריפו עם /github)")
                return
            try:
                infos = backup_manager.list_backups(user_id)
                match = next((b for b in infos if getattr(b, 'backup_id', '') == backup_id), None)
                if not match or not match.file_path or not os.path.exists(match.file_path):
                    await query.edit_message_text("❌ הגיבוי לא נמצא בדיסק")
                    return
                # קרא שמות קבצים מתוך ה‑ZIP (ללא תיקיות ו-metadata.json)
                import zipfile as _zip
                names: list[str] = []
                with _zip.ZipFile(match.file_path, 'r') as zf:
                    for n in zf.namelist():
                        if n.endswith('/'):
                            continue
                        if n == 'metadata.json':
                            continue
                        names.append(n)
                if not names:
                    await query.edit_message_text("ℹ️ אין קבצים ב‑ZIP")
                    return
                # עימוד בסיסי
                page = int(context.user_data.get('gh_zip_browse_page', 1))
                PAGE = 10
                total = len(names)
                total_pages = (total + PAGE - 1) // PAGE
                if page < 1:
                    page = 1
                if page > total_pages:
                    page = total_pages
                start = (page - 1) * PAGE
                end = min(start + PAGE, total)
                slice_names = names[start:end]
                # שמירת מיפוי שמות בקאש הסשן כדי להימנע מ-callback ארוך מדי
                try:
                    cache = context.user_data.setdefault('gh_zip_cache', {})
                    cache[backup_id] = {'names': names}
                except Exception:
                    pass
                # בנה כפתורים לבחירת קובץ להעלאה + עימוד + חזרה (לפי אינדקס)
                kb = []
                for idx, n in enumerate(slice_names, start=start):
                    safe_label = n if len(n) <= 64 else (n[:30] + '…' + n[-30:])
                    kb.append([InlineKeyboardButton(safe_label, callback_data=f"gh_upload_zip_select_idx:{backup_id}:{idx}")])
                # עימוד
                nav = []
                if page > 1:
                    nav.append(InlineKeyboardButton("⬅️ הקודם", callback_data=f"gh_upload_zip_page:{backup_id}:{page-1}"))
                if page < total_pages:
                    nav.append(InlineKeyboardButton("הבא ➡️", callback_data=f"gh_upload_zip_page:{backup_id}:{page+1}"))
                if nav:
                    kb.append(nav)
                # חזור לרשימת ה‑ZIPים של העלאה
                kb.append([InlineKeyboardButton("🔙 חזור", callback_data="gh_upload_cat:zips")])
                await query.edit_message_text(
                    f"בחר קובץ מתוך ZIP להעלאה לריפו:\n<code>{backup_id}</code>\nעמוד {page}/{total_pages}",
                    reply_markup=InlineKeyboardMarkup(kb),
                    parse_mode="HTML",
                )
            except Exception as e:
                await query.edit_message_text(f"❌ שגיאה בקריאת ZIP: {e}")
        elif query.data.startswith("gh_upload_zip_page:"):
            # ניווט עמודים בעיון ה‑ZIP
            try:
                _, backup_id, page_str = query.data.split(":", 2)
                context.user_data['gh_zip_browse_page'] = max(1, int(page_str))
                # הביא מחדש את אותו מסך
                await self.handle_menu_callback(update, context)
                # החלף את ה-callback ל-browse כדי להפעיל את העדכון
                update.callback_query.data = f"gh_upload_zip_browse:{backup_id}"
                await self.handle_menu_callback(update, context)
            except Exception:
                await query.answer("שגיאת עימוד", show_alert=True)
        elif query.data.startswith("gh_upload_zip_select_idx:"):
            # בחירת קובץ מתוך ZIP לפי אינדקס כדי לעמוד במגבלת 64 בתים של callback_data
            try:
                _, backup_id, idx_str = query.data.split(":", 2)
                idx = int(idx_str)
            except Exception:
                await query.answer("בקשה לא תקפה", show_alert=True)
                return
            user_id = query.from_user.id
            session = self.get_user_session(user_id)
            token = self.get_user_token(user_id)
            repo_name = session.get("selected_repo")
            if not (token and repo_name):
                await query.edit_message_text("❌ חסרים נתונים (בחר ריפו עם /github)")
                return
            # מצא את הנתיב הפנימי לפי הקאש; אם לא קיים — טען מחדש מה‑ZIP
            inner_path = None
            try:
                cache = context.user_data.get('gh_zip_cache', {})
                names = (cache.get(backup_id) or {}).get('names') or []
                if 0 <= idx < len(names):
                    inner_path = names[idx]
            except Exception:
                inner_path = None
            if not inner_path:
                try:
                    infos = backup_manager.list_backups(user_id)
                    match = next((b for b in infos if getattr(b, 'backup_id', '') == backup_id), None)
                    if not match or not match.file_path or not os.path.exists(match.file_path):
                        await query.edit_message_text("❌ הגיבוי לא נמצא בדיסק")
                        return
                    import zipfile as _zip
                    with _zip.ZipFile(match.file_path, 'r') as zf:
                        all_names = [n for n in zf.namelist() if not n.endswith('/') and n != 'metadata.json']
                    if 0 <= idx < len(all_names):
                        inner_path = all_names[idx]
                    else:
                        await query.edit_message_text("❌ פריט לא קיים ב‑ZIP")
                        return
                except Exception as e:
                    await query.edit_message_text(f"❌ שגיאה בקריאת ZIP: {e}")
                    return
            # המשך זרימת העלאה זהה לבחירה לפי מחרוזת
            try:
                infos = backup_manager.list_backups(user_id)
                match = next((b for b in infos if getattr(b, 'backup_id', '') == backup_id), None)
                if not match or not match.file_path or not os.path.exists(match.file_path):
                    await query.edit_message_text("❌ הגיבוי לא נמצא בדיסק")
                    return
                import zipfile as _zip
                with _zip.ZipFile(match.file_path, 'r') as zf:
                    try:
                        raw = zf.read(inner_path)
                    except Exception:
                        await query.edit_message_text("❌ קובץ לא נמצא בתוך ה‑ZIP")
                        return
                try:
                    content_text = raw.decode('utf-8')
                except Exception:
                    try:
                        content_text = raw.decode('latin-1')
                    except Exception as e:
                        await query.edit_message_text(f"❌ לא ניתן לפענח את הקובץ: {e}")
                        return
                target_folder = (context.user_data.get("upload_target_folder") or session.get("selected_folder") or "").strip("/")
                target_path = f"{target_folder}/{inner_path}" if target_folder else inner_path
                import re as _re
                target_path = _re.sub(r"/+", "/", target_path.strip("/"))
                g = Github(token)
                repo = g.get_repo(repo_name)
                branch = context.user_data.get("upload_target_branch") or repo.default_branch or "main"
                try:
                    existing = repo.get_contents(target_path, ref=branch)
                    result = repo.update_file(
                        path=target_path,
                        message=f"Update {inner_path} via Telegram bot",
                        content=content_text,
                        sha=existing.sha,
                        branch=branch,
                    )
                    await query.edit_message_text(f"✅ הקובץ עודכן בהצלחה ל-<code>{target_path}</code>", parse_mode="HTML")
                except Exception:
                    result = repo.create_file(
                        path=target_path,
                        message=f"Upload {inner_path} via Telegram bot",
                        content=content_text,
                        branch=branch,
                    )
                    await query.edit_message_text(f"✅ הקובץ הועלה בהצלחה ל-<code>{target_path}</code>", parse_mode="HTML")
                kb = [
                    [InlineKeyboardButton("➕ העלה קובץ נוסף מה‑ZIP", callback_data=f"gh_upload_zip_browse:{backup_id}")],
                    [InlineKeyboardButton("🔙 חזור", callback_data="gh_upload_cat:zips")],
                ]
                await query.message.reply_text("🎯 בחר פעולה:", reply_markup=InlineKeyboardMarkup(kb))
            except Exception as e:
                await query.edit_message_text(f"❌ שגיאה בהעלאה: {e}")
        elif query.data.startswith("gh_upload_zip_select:"):
            # בחירת קובץ ספציפי מתוך ZIP להעלאה לריפו
            try:
                _, backup_id, inner_path = query.data.split(":", 2)
            except Exception:
                await query.answer("בקשה לא תקפה", show_alert=True)
                return
            user_id = query.from_user.id
            session = self.get_user_session(user_id)
            token = self.get_user_token(user_id)
            repo_name = session.get("selected_repo")
            if not (token and repo_name):
                await query.edit_message_text("❌ חסרים נתונים (בחר ריפו עם /github)")
                return
            # בדוק את ה‑ZIP והוצא את התוכן של הקובץ
            try:
                infos = backup_manager.list_backups(user_id)
                match = next((b for b in infos if getattr(b, 'backup_id', '') == backup_id), None)
                if not match or not match.file_path or not os.path.exists(match.file_path):
                    await query.edit_message_text("❌ הגיבוי לא נמצא בדיסק")
                    return
                import zipfile as _zip
                with _zip.ZipFile(match.file_path, 'r') as zf:
                    try:
                        raw = zf.read(inner_path)
                    except Exception:
                        await query.edit_message_text("❌ קובץ לא נמצא בתוך ה‑ZIP")
                        return
                # המרת תוכן לטקסט (utf-8 או latin-1)
                try:
                    content_text = raw.decode('utf-8')
                except Exception:
                    try:
                        content_text = raw.decode('latin-1')
                    except Exception as e:
                        await query.edit_message_text(f"❌ לא ניתן לפענח את הקובץ: {e}")
                        return
                # יעד: נתיב התיקייה שנבחרה + שם הקובץ המקורי מה‑ZIP
                target_folder = (context.user_data.get("upload_target_folder") or session.get("selected_folder") or "").strip("/")
                target_path = f"{target_folder}/{inner_path}" if target_folder else inner_path
                # ודא שימוש בנתיב נקי ללא כפילויות '/'
                import re as _re
                target_path = _re.sub(r"/+", "/", target_path.strip("/"))
                # בצע יצירה/עדכון
                g = Github(token)
                repo = g.get_repo(repo_name)
                branch = context.user_data.get("upload_target_branch") or repo.default_branch or "main"
                try:
                    existing = repo.get_contents(target_path, ref=branch)
                    result = repo.update_file(
                        path=target_path,
                        message=f"Update {inner_path} via Telegram bot",
                        content=content_text,
                        sha=existing.sha,
                        branch=branch,
                    )
                    await query.edit_message_text(f"✅ הקובץ עודכן בהצלחה ל-<code>{target_path}</code>", parse_mode="HTML")
                except Exception:
                    result = repo.create_file(
                        path=target_path,
                        message=f"Upload {inner_path} via Telegram bot",
                        content=content_text,
                        branch=branch,
                    )
                    await query.edit_message_text(f"✅ הקובץ הועלה בהצלחה ל-<code>{target_path}</code>", parse_mode="HTML")
                # הצע פעולות המשך: בחר קובץ נוסף מה‑ZIP או חזור
                kb = [
                    [InlineKeyboardButton("➕ העלה קובץ נוסף מה‑ZIP", callback_data=f"gh_upload_zip_browse:{backup_id}")],
                    [InlineKeyboardButton("🔙 חזור", callback_data="gh_upload_cat:zips")],
                ]
                await query.message.reply_text("🎯 בחר פעולה:", reply_markup=InlineKeyboardMarkup(kb))
            except Exception as e:
                await query.edit_message_text(f"❌ שגיאה בהעלאה: {e}")
        elif query.data == "gh_upload_cat:large":
            await self.upload_large_files_menu(update, context)
        elif query.data == "gh_upload_cat:other":
            await self.show_upload_other_files(update, context)

        # --- Create new repository from ZIP ---
        elif query.data == "github_create_repo_from_zip":
            # הכנה לזרימת יצירת ריפו חדש מתוך ZIP
            user_id = query.from_user.id
            session = self.get_user_session(user_id)
            token = self.get_user_token(user_id)
            if not token:
                await query.edit_message_text("❌ אין חיבור ל-GitHub. שלח /github כדי להגדיר טוקן")
                return
            # נקה דגלים ישנים כדי למנוע בלבול בקליטת המסמכים
            context.user_data["waiting_for_github_upload"] = False
            context.user_data["upload_mode"] = "github_create_repo_from_zip"
            # ברירת מחדל: ריפו פרטי
            context.user_data["new_repo_private"] = True
            vis_text = "פרטי" if context.user_data.get("new_repo_private", True) else "ציבורי"
            kb = [
                [InlineKeyboardButton("✍️ הקלד שם ריפו", callback_data="github_new_repo_name")],
                [
                    InlineKeyboardButton(
                        "🔒 פרטי ✅" if context.user_data.get("new_repo_private", True) else "🔒 פרטי",
                        callback_data="github_set_new_repo_visibility:1"
                    ),
                    InlineKeyboardButton(
                        "🌐 ציבורי ✅" if not context.user_data.get("new_repo_private", True) else "🌐 ציבורי",
                        callback_data="github_set_new_repo_visibility:0"
                    ),
                ],
                [InlineKeyboardButton("🔙 חזור", callback_data="github_menu")],
            ]
            help_txt = (
                "🆕 <b>יצירת ריפו חדש מּZIP</b>\n\n"
                "1) ניתן להקליד שם לריפו (ללא רווחים)\n"
                "2) בחר אם הריפו יהיה <b>פרטי</b> או <b>ציבורי</b>\n"
                "3) שלח עכשיו קובץ ZIP עם כל הקבצים\n\n"
                "אם לא תוקלד שם, ננסה לחלץ שם מתיקיית-הבסיס בּZIP או משם הקובץ.\n"
                "ברירת מחדל: <code>repo-&lt;timestamp&gt;</code>\n\n"
                f"נראות נוכחית: <b>{vis_text}</b>\n"
                "לאחר השליחה, ניצור ריפו לפי בחירתך ונפרוס את התוכן ב-commit אחד."
            )
            await query.edit_message_text(help_txt, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))
            return
        elif query.data == "github_new_repo_name":
            # בקשת שם לריפו החדש
            context.user_data["waiting_for_new_repo_name"] = True
            await query.edit_message_text(
                "✏️ הקלד שם לריפו החדש (מותר אותיות, מספרים, נקודות, מקפים וקו תחתון).\nשלח טקסט עכשיו.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 חזור", callback_data="github_create_repo_from_zip")]])
            )
            return
        elif query.data.startswith("github_set_new_repo_visibility:"):
            # בחירת נראות (פרטי/ציבורי) לריפו החדש
            flag = query.data.split(":", 1)[1]
            is_private = flag == "1"
            context.user_data["new_repo_private"] = is_private
            vis_text = "פרטי" if is_private else "ציבורי"
            kb = [
                [InlineKeyboardButton("✍️ הקלד שם ריפו", callback_data="github_new_repo_name")],
                [
                    InlineKeyboardButton(
                        "🔒 פרטי ✅" if is_private else "🔒 פרטי",
                        callback_data="github_set_new_repo_visibility:1"
                    ),
                    InlineKeyboardButton(
                        "🌐 ציבורי ✅" if not is_private else "🌐 ציבורי",
                        callback_data="github_set_new_repo_visibility:0"
                    ),
                ],
                [InlineKeyboardButton("🔙 חזור", callback_data="github_menu")],
            ]
            help_txt = (
                "🆕 <b>יצירת ריפו חדש מּZIP</b>\n\n"
                "1) ניתן להקליד שם לריפו (ללא רווחים)\n"
                "2) בחר אם הריפו יהיה <b>פרטי</b> או <b>ציבורי</b>\n"
                "3) שלח עכשיו קובץ ZIP עם כל הקבצים\n\n"
                "אם לא תוקלד שם, ננסה לחלץ שם מתיקיית-הבסיס בּZIP או משם הקובץ.\n"
                "ברירת מחדל: <code>repo-&lt;timestamp&gt;</code>\n\n"
                f"נראות נוכחית: <b>{vis_text}</b>\n"
                "לאחר השליחה, ניצור ריפו לפי בחירתך ונפרוס את התוכן ב-commit אחד."
            )
            try:
                await query.edit_message_text(help_txt, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))
            except BadRequest as br:
                if "message is not modified" not in str(br).lower():
                    raise
                try:
                    await query.answer("עודכנה הנראות", show_alert=False)
                except Exception:
                    pass
            return
        elif query.data.startswith("gh_upload_repo:"):
            tag = query.data.split(":", 1)[1]
            await self.show_upload_repo_files(update, context, tag)
        elif query.data.startswith("other_files_page_"):
            try:
                p = int(query.data.split("_")[-1])
            except Exception:
                p = 1
            # שמירת עמוד, כדי שלא נקפוץ לעמוד הראשון אחרי פעולה
            context.user_data["other_files_page"] = max(1, p)
            await self.show_upload_other_files(update, context)
        elif query.data.startswith("repo_files_page:"):
            # פורמט: repo_files_page:<repo_tag>:<page>
            try:
                _, repo_tag, page_s = query.data.split(":", 2)
                page = int(page_s)
            except Exception:
                repo_tag, page = None, 1
            if repo_tag:
                # שמור עמוד נוכחי לכל תגית
                d = context.user_data.get("repo_files_page") or {}
                d[repo_tag] = page
                context.user_data["repo_files_page"] = d
                await self.show_upload_repo_files(update, context, repo_tag)
        elif query.data.startswith("gh_upload_large:"):
            file_id = query.data.split(":", 1)[1]
            await self.handle_large_file_upload(update, context, file_id)

        # הוסר: "upload_saved" — הזרימה כלולה ב"העלה קובץ חדש"

        elif query.data.startswith("repos_page_"):
            page = int(query.data.split("_")[2])
            await self.show_repos(update, context, page)

        elif query.data.startswith("upload_saved_"):
            file_id = query.data.split("_")[2]
            # Show pre-upload check screen before actual upload
            context.user_data["pending_saved_file_id"] = file_id
            await self.show_pre_upload_check(update, context)
        elif query.data == "choose_upload_branch":
            # מענה מיידי כדי לשחרר את ה-UI לפני טעינת רשימת ענפים
            try:
                await query.answer("טוען ענפים…", show_alert=False)
            except Exception:
                pass
            await self.show_upload_branch_menu(update, context)
        elif query.data.startswith("upload_branches_page_"):
            try:
                p = int(query.data.split("_")[-1])
            except Exception:
                p = 0
            context.user_data["upload_branches_page"] = max(0, p)
            await self.show_upload_branch_menu(update, context)
        elif query.data.startswith("upload_select_branch_tok:"):
            tok = query.data.split(":", 1)[1]
            br = (context.user_data.get("upload_branch_tokens") or {}).get(tok)
            if not br:
                await query.answer("⚠️ לא נמצא ענף לבחירה", show_alert=True)
            else:
                context.user_data["upload_target_branch"] = br
                await self.show_pre_upload_check(update, context)
        elif query.data == "choose_upload_folder":
            try:
                await query.answer("טוען תיקיות…", show_alert=False)
            except Exception:
                pass
            await self.show_upload_folder_menu(update, context)
        elif query.data.startswith("upload_select_folder:"):
            # בחירת תיקייה מתוך דפדפן הריפו
            folder_path = query.data.split(":", 1)[1]
            # normalize to no leading/trailing slashes
            folder_norm = (folder_path or "").strip("/")
            context.user_data["upload_target_folder"] = folder_norm
            await self.show_pre_upload_check(update, context)
        elif query.data == "upload_folder_root":
            context.user_data["upload_target_folder"] = ""
            await self.show_pre_upload_check(update, context)
        elif query.data == "upload_folder_current":
            context.user_data["upload_target_folder"] = (session.get("selected_folder") or "")
            await self.show_pre_upload_check(update, context)
        elif query.data == "upload_folder_custom":
            try:
                await query.answer("הקלד/י נתיב יעד…", show_alert=False)
            except Exception:
                pass
            await self.ask_upload_folder(update, context)
        elif query.data == "upload_folder_create":
            # פתח זרימת יצירת תיקייה (תואם למסלול בהמשך עבור create_folder)
            context.user_data["waiting_for_new_folder_path"] = True
            # חזרה למסך הבדיקות לאחר היצירה
            context.user_data["return_to_pre_upload"] = True
            keyboard = [[
                InlineKeyboardButton("🔙 חזור", callback_data="create_folder_back"),
                InlineKeyboardButton("❌ ביטול", callback_data="create_folder_cancel")
            ]]
            # שחרר את ה‑UI מיד כדי למנוע תחושת תקיעה
            try:
                await query.answer("הקלד/י נתיב תיקייה…", show_alert=False)
            except Exception:
                pass
            # נסה לערוך את ההודעה, ובמקרה של "message is not modified" עדכן רק את המקלדת, או שלח הודעה חדשה
            try:
                await query.edit_message_text(
                    "➕ יצירת תיקייה חדשה\n\n"
                    "✏️ כתוב נתיב תיקייה חדשה (לדוגמה: src/new/section).\n"
                    "ניצור קובץ ‎.gitkeep‎ בתוך התיקייה כדי ש‑Git ישמור אותה.",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            except BadRequest as br:
                if "message is not modified" in str(br).lower():
                    try:
                        from utils import TelegramUtils as _TU
                        await _TU.safe_edit_message_reply_markup(query, reply_markup=InlineKeyboardMarkup(keyboard))
                    except Exception:
                        # כגיבוי, שלח הודעה חדשה
                        try:
                            await query.message.reply_text(
                                "➕ יצירת תיקייה חדשה\n\n"
                                "✏️ כתוב נתיב תיקייה חדשה (לדוגמה: src/new/section).\n"
                                "ניצור קובץ ‎.gitkeep‎ בתוך התיקייה כדי ש‑Git ישמור אותה.",
                                reply_markup=InlineKeyboardMarkup(keyboard)
                            )
                        except Exception:
                            pass
                else:
                    raise
            return REPO_SELECT
        elif query.data == "confirm_saved_upload":
            file_id = context.user_data.get("pending_saved_file_id")
            if not file_id:
                await query.edit_message_text("❌ לא נמצא קובץ ממתין להעלאה")
            else:
                await self.handle_saved_file_upload(update, context, file_id)
        elif query.data == "refresh_saved_checks":
            await self.show_pre_upload_check(update, context)
        elif query.data == "back_to_menu":
            await self.github_menu_command(update, context)

        elif query.data == "folder_select_done":
            # סיום בחירת תיקייה דרך הדפדפן והצגת מצב
            context.user_data.pop("folder_select_mode", None)
            await self.github_menu_command(update, context)
        elif query.data.startswith("folder_set_session:"):
            folder_path = query.data.split(":", 1)[1]
            session["selected_folder"] = (folder_path or "").strip("/") or None
            await query.answer(f"✅ תיקיית יעד עודכנה ל-{session['selected_folder'] or 'root'}", show_alert=False)
            # יציאה ממסך בחירת תיקייה וחזרה לתפריט הראשי כדי למנוע שגיאת "Message is not modified"
            context.user_data.pop("folder_select_mode", None)
            await self.github_menu_command(update, context)
        elif query.data == "noop":
            await query.answer(cache_time=0)  # לא עושה כלום, רק לכפתור התצוגה

        # --- New: logout GitHub token from menu ---
        elif query.data == "logout_github":
            from database import db

            removed = db.delete_github_token(user_id)
            try:
                session["github_token"] = None
                # נקה גם בחירות קודמות כאשר מתנתקים
                session["selected_repo"] = None
                session["selected_folder"] = None
            except Exception:
                pass
            # נקה קאש ריפוזיטוריז
            context.user_data.pop("repos", None)
            context.user_data.pop("repos_cache_time", None)
            if removed:
                await query.edit_message_text("🔐 התנתקת מ-GitHub והטוקן נמחק.⏳ מרענן תפריט...")
            else:
                await query.edit_message_text("ℹ️ לא נמצא טוקן או שאירעה שגיאה.⏳ מרענן תפריט...")
            # refresh the menu after logout
            await self.github_menu_command(update, context)
            return
        elif query.data == "github_import_repo":
            # פתיחת זרימת ייבוא ריפו (בחירת ענף → ייבוא)
            repo_full = session.get("selected_repo")
            if not repo_full:
                await query.edit_message_text("❌ קודם בחר ריפו!\nשלח /github ובחר 'בחר ריפו'")
                return
            await self.show_import_branch_menu(update, context)
            return
        elif query.data.startswith("import_repo_branches_page_"):
            try:
                p = int(query.data.rsplit("_", 1)[-1])
            except Exception:
                p = 0
            context.user_data["import_branches_page"] = max(0, p)
            await self.show_import_branch_menu(update, context)
            return
        elif query.data.startswith("import_repo_select_branch:"):
            token = query.data.split(":", 1)[1]
            token_map = context.user_data.get("import_branch_token_map", {})
            branch = token_map.get(token, token)
            context.user_data["import_repo_branch"] = branch
            await self._confirm_import_repo(update, context, branch)
            return
        elif query.data == "import_repo_start":
            # התחלת ייבוא בפועל
            repo_full = session.get("selected_repo") or ""
            branch = context.user_data.get("import_repo_branch")
            if not repo_full or not branch:
                await query.edit_message_text("❌ חסרים נתונים ליבוא. בחר ריפו וענף מחדש.")
                return
            await self.import_repo_from_zip(update, context, repo_full, branch)
            return
        elif query.data == "import_repo_cancel":
            await self.github_menu_command(update, context)
            return

        elif query.data == "analyze_repo":
            logger.info(f"🔍 User {query.from_user.id} clicked 'analyze_repo' button")
            await self.show_analyze_repo_menu(update, context)

        elif query.data == "analyze_current_repo":
            # נתח את הריפו הנבחר
            logger.info(f"📊 User {query.from_user.id} analyzing current repo")
            session = self.get_user_session(query.from_user.id)
            repo_url = f"https://github.com/{session['selected_repo']}"
            await self.analyze_repository(update, context, repo_url)

        elif query.data == "back_to_github_menu":
            await self.github_menu_command(update, context)

        elif query.data == "analyze_other_repo":
            logger.info(f"🔄 User {query.from_user.id} wants to analyze another repo")
            await self.analyze_another_repo(update, context)

        elif query.data == "show_suggestions":
            await self.show_improvement_suggestions(update, context)

        elif query.data == "show_full_analysis":
            await self.show_full_analysis(update, context)

        elif query.data == "download_analysis_json":
            await self.download_analysis_json(update, context)

        elif query.data == "github_backup_menu":
            await self.show_github_backup_menu(update, context)
        elif query.data == "github_backup_db_list":
            # מעבר לרשימת "גיבויי DB אחרונים" מתוך תפריט GitHub, עם חזרה ל-GitHub
            try:
                backup_handler = context.bot_data.get('backup_handler')
                if backup_handler is None:
                    from backup_menu_handler import BackupMenuHandler
                    backup_handler = BackupMenuHandler()
                    context.bot_data['backup_handler'] = backup_handler
                # קבע הקשר חזרה ל-GitHub והסר סינון לפי ריפו לרשימה זו
                context.user_data['zip_back_to'] = 'github'
                try:
                    context.user_data.pop('github_backup_context_repo')
                except Exception:
                    pass
                await backup_handler._show_backups_list(update, context, page=1)
            except Exception as e:
                await query.edit_message_text(f"❌ שגיאה בטעינת גיבויים: {e}")

        elif query.data == "github_restore_zip_to_repo":
            # התחלת שחזור ZIP ידני לריפו: הגדר מצב העלאה ובקש בחירת purge
            user_id = query.from_user.id
            session = self.get_user_session(user_id)
            token = self.get_user_token(user_id)
            repo_full = session.get("selected_repo")
            if not (token and repo_full):
                try:
                    await query.edit_message_text("❌ חסר טוקן או ריפו נבחר")
                except BadRequest as br:
                    if "message is not modified" not in str(br).lower():
                        raise
                    try:
                        await query.answer("❌ חסר טוקן או ריפו נבחר", show_alert=True)
                    except Exception:
                        pass
                return
            # ודא שניקינו דגלים ישנים של העלאה רגילה כדי למנוע בלבול
            context.user_data["waiting_for_github_upload"] = False
            context.user_data["upload_mode"] = "github_restore_zip_to_repo"
            # נעל את יעד הריפו הצפוי לשחזור (חגורת בטיחות נגד ריפו אחר)
            try:
                context.user_data["zip_restore_expected_repo_full"] = repo_full
            except Exception:
                # לא קריטי אם נכשלת שמירת סטייט - נאתר בהמשך
                pass
            kb = [
                [InlineKeyboardButton("🧹 מחיקה מלאה לפני העלאה", callback_data="github_restore_zip_setpurge:1")],
                [InlineKeyboardButton("🚫 אל תמחק, רק עדכן", callback_data="github_restore_zip_setpurge:0")],
                [InlineKeyboardButton("❌ ביטול", callback_data="github_backup_menu")],
            ]
            try:
                await query.edit_message_text(
                    "בחר מצב שחזור ZIP לריפו, ואז שלח קובץ ZIP עכשיו:",
                    reply_markup=InlineKeyboardMarkup(kb),
                )
            except BadRequest as br:
                if "message is not modified" not in str(br).lower():
                    await query.message.reply_text(
                        "בחר מצב שחזור ZIP לריפו, ואז שלח קובץ ZIP עכשיו:",
                        reply_markup=InlineKeyboardMarkup(kb),
                    )
                else:
                    try:
                        await query.answer("אין שינוי בתצוגה", show_alert=False)
                    except Exception:
                        pass
        elif query.data.startswith("github_restore_zip_setpurge:"):
            # טיפול בבחירת מצב מחיקה/עדכון לפני העלאה
            purge_flag = query.data.split(":", 1)[1] == "1"
            # ודא שניקינו דגלים ישנים של העלאה רגילה כדי למנוע בלבול
            context.user_data["waiting_for_github_upload"] = False
            context.user_data["upload_mode"] = "github_restore_zip_to_repo"
            context.user_data["github_restore_zip_purge"] = purge_flag
            # השאר את היעד הצפוי אם כבר נקבע קודם
            if not context.user_data.get("zip_restore_expected_repo_full"):
                try:
                    context.user_data["zip_restore_expected_repo_full"] = session.get("selected_repo")
                except Exception:
                    pass
            await query.edit_message_text(
                ("🧹 יבוצע ניקוי לפני העלאה. " if purge_flag else "🔁 ללא מחיקה. ") +
                "שלח עכשיו קובץ ZIP לשחזור לריפו."
            )
            return

        elif query.data == "github_restore_zip_list":
            # הצג רשימת גיבויים (ZIP) של הריפו הנוכחי לצורך שחזור לריפו
            user_id = query.from_user.id
            session = self.get_user_session(user_id)
            repo_full = session.get("selected_repo")
            if not repo_full:
                await query.edit_message_text("❌ קודם בחר ריפו!")
                return
            backups = backup_manager.list_backups(user_id)
            # סנן רק גיבויים עם metadata של אותו ריפו
            backups = [b for b in backups if getattr(b, 'repo', None) == repo_full]
            if not backups:
                await query.edit_message_text(
                    f"ℹ️ אין גיבויי ZIP שמורים עבור הריפו:\n<code>{repo_full}</code>",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 חזור", callback_data="github_backup_menu")]])
                )
                return
            # הצג עד 10 אחרונים
            items = backups[:10]
            lines = [f"בחר גיבוי לשחזור לריפו:\n<code>{repo_full}</code>\n"]
            kb = []
            for b in items:
                lines.append(f"• {b.backup_id} — {b.created_at.strftime('%d/%m/%Y %H:%M')} — {int(b.total_size/1024)}KB")
                kb.append([InlineKeyboardButton("♻️ שחזר גיבוי זה לריפו", callback_data=f"github_restore_zip_from_backup:{b.backup_id}")])
            kb.append([InlineKeyboardButton("🔙 חזור", callback_data="github_backup_menu")])
            await query.edit_message_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")
            return

        elif query.data.startswith("github_restore_zip_from_backup:"):
            # קבל backup_id ואז פתח את תהליך השחזור-לריפו עם קובץ ה-ZIP הזה
            backup_id = query.data.split(":", 1)[1]
            user_id = query.from_user.id
            info_list = backup_manager.list_backups(user_id)
            match = next((b for b in info_list if b.backup_id == backup_id), None)
            if not match or not match.file_path or not os.path.exists(match.file_path):
                await query.edit_message_text("❌ הגיבוי לא נמצא בדיסק")
                return
            # הגדר purge? בקש בחירה
            context.user_data["pending_repo_restore_zip_path"] = match.file_path
            # נעל את יעד הריפו הצפוי עבור השחזור מתוך גיבוי
            try:
                context.user_data["zip_restore_expected_repo_full"] = self.get_user_session(user_id).get("selected_repo")
            except Exception:
                pass
            await query.edit_message_text(
                "האם למחוק קודם את התוכן בריפו לפני העלאה?",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🧹 מחיקה מלאה לפני העלאה", callback_data="github_repo_restore_backup_setpurge:1")],
                    [InlineKeyboardButton("🚫 אל תמחק, רק עדכן", callback_data="github_repo_restore_backup_setpurge:0")],
                    [InlineKeyboardButton("❌ ביטול", callback_data="github_backup_menu")],
                ])
            )
            return
        elif query.data == "github_backup_help":
            help_text = (
                "<b>הסבר על הכפתורים:</b>\n\n"
                "📦 <b>הורד גיבוי ZIP של הריפו</b>: יוצר ומוריד ZIP של כל התוכן (או תיקייה נוכחית), וגם שומר כגיבוי לשימוש עתידי.\n\n"
                "♻️ <b>שחזר ZIP לריפו (פריסה והחלפה)</b>: שלח ZIP מהמחשב, והבוט יפרוס אותו לריפו בקומיט אחד. ניתן לבחור מחיקה מלאה לפני או עדכון בלבד.\n\n"
                "📂 <b>שחזר מגיבוי שמור לריפו</b>: בחר ZIP ששמור בבוט עבור הריפו הזה, והבוט יפרוס אותו לריפו (מחיקה/עדכון לפי בחירה).\n\n"
                "🏷 <b>נקודת שמירה בגיט</b>: יוצר תגית/ענף נקודת שמירה של הריפו הנוכחי כדי שתוכל לחזור אליה.\n\n"
                "↩️ <b>חזרה לנקודת שמירה</b>: פעולות לשחזור מצב מהרפרנס של נקודת שמירה (תגית/ענף) — כולל יצירת ענף/PR לשחזור.\n\n"
                "🗂 <b>גיבויי DB אחרונים</b>: מציג גיבויים של קבצים בבוט עצמו (לא קשור ל‑GitHub).\n\n"
                "♻️ <b>שחזור מגיבוי (ZIP)</b>: שחזור מלא לקבצים בבוט עצמו מקובץ ZIP. מוחק את כל הקבצים בבוט ואז משחזר.\n\n"
                "🔙 <b>חזור</b>: חזרה לתפריט הראשי של GitHub."
            )
            try:
                await query.edit_message_text(help_text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 חזור", callback_data="github_backup_menu")]]))
            except BadRequest as br:
                if "message is not modified" not in str(br).lower():
                    raise
            return

        elif query.data == "backup_menu":
            # האצלת תצוגת תפריט הגיבוי/שחזור של DB ל-BackupMenuHandler
            backup_handler = context.bot_data.get('backup_handler')
            if backup_handler:
                await backup_handler.show_backup_menu(update, context)
            else:
                await query.edit_message_text("❌ רכיב גיבוי לא זמין")

        elif query.data == "back_to_analysis":
            await self.show_full_analysis(update, context)

        elif query.data == "back_to_analysis_menu":
            await self.show_analyze_results_menu(update, context)
        
        elif query.data == "back_to_summary":
            await self.show_analyze_results_menu(update, context)

        elif query.data == "choose_my_repo":
            await self.show_repos(update, context)

        elif query.data == "enter_repo_url":
            await self.request_repo_url(update, context)

        elif query.data.startswith("suggestion_"):
            suggestion_index = int(query.data.split("_")[1])
            await self.show_suggestion_details(update, context, suggestion_index)

        elif query.data == "show_current":
            current_repo = session.get("selected_repo", "לא נבחר")
            current_folder = session.get("selected_folder") or "root"
            has_token = "✅" if self.get_user_token(user_id) else "❌"

            keyboard = [[InlineKeyboardButton("🔙 חזרה לתפריט", callback_data="github_menu")]]
            await query.edit_message_text(
                f"📊 <b>הגדרות נוכחיות:</b>\n\n"
                f"📁 ריפו: <code>{current_repo}</code>\n"
                f"📂 תיקייה: <code>{current_folder}</code>\n"
                f"🔑 טוקן מוגדר: {has_token}\n\n"
                f"💡 טיפ: השתמש ב-'בחר תיקיית יעד' כדי לשנות את מיקום ההעלאה",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )

        elif query.data == "set_token":
            await query.edit_message_text(
                "🔑 שלח לי את הטוקן של GitHub:\n\n"
                "הטוקן יישמר בצורה מאובטחת לחשבון שלך לצורך שימוש עתידי.\n"
                "תוכל להסיר אותו בכל עת עם הפקודה /github_logout.\n\n"
                "💡 טיפ: צור טוקן ב:\n"
                "https://github.com/settings/tokens"
            )
            return REPO_SELECT

        elif query.data == "set_folder":
            # פתח דפדפן ריפו לבחירת תיקיה אמיתית מתוך הריפו
            # סימון מצב בחירת תיקיה עבור session
            context.user_data["folder_select_mode"] = "session"
            # אתחל מצב דפדוף
            current = (session.get("selected_folder") or "").strip("/")
            context.user_data["browse_action"] = "download"
            context.user_data["browse_path"] = current
            context.user_data["browse_page"] = 0
            context.user_data["multi_mode"] = False
            context.user_data["multi_selection"] = []
            # מענה מיידי כדי למנוע תחושת תקיעה
            try:
                await query.answer("טוען דפדפן תיקיות…", show_alert=False)
            except Exception:
                pass
            await self.show_repo_browser(update, context)

        elif query.data.startswith("folder_"):
            folder = query.data.replace("folder_", "")
            if folder == "custom":
                # בקש קלט לתיקייה מותאמת אישית
                context.user_data["waiting_for_selected_folder"] = True
                await query.edit_message_text(
                    "✏️ הקלד שם תיקייה (לדוגמה: src/images)\n"
                    "השאר ריק או הקלד / כדי לבחור root"
                )
                return FOLDER_SELECT
            elif folder == "root":
                session["selected_folder"] = None
                await query.answer("✅ תיקייה עודכנה ל-root", show_alert=False)
                await self.github_menu_command(update, context)
            else:
                session["selected_folder"] = folder.replace("_", "/")
                await query.answer(f"✅ תיקייה עודכנה ל-{session['selected_folder']}", show_alert=False)
                await self.github_menu_command(update, context)

        elif query.data in ("create_folder", "upload_folder_create"):
            # בקש מהמשתמש נתיב תיקייה חדשה ליצירה (ניצור .gitkeep בתוך התיקייה)
            return_to_pre = (query.data == "upload_folder_create")
            context.user_data["waiting_for_new_folder_path"] = True
            context.user_data["return_to_pre_upload"] = return_to_pre
            keyboard = [[InlineKeyboardButton("🔙 חזור", callback_data="create_folder_back"), InlineKeyboardButton("❌ ביטול", callback_data="create_folder_cancel")]]
            await query.edit_message_text(
                "➕ יצירת תיקייה חדשה\n\n"
                "✏️ כתוב נתיב תיקייה חדשה (לדוגמה: src/new/section).\n"
                "ניצור קובץ ‎.gitkeep‎ בתוך התיקייה כדי ש‑Git ישמור אותה.",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return REPO_SELECT

        elif query.data == "create_folder_back":
            # חזרה למסך "תיקיית יעד"
            context.user_data["waiting_for_new_folder_path"] = False
            await self.show_upload_folder_menu(update, context)
            return REPO_SELECT

        elif query.data == "create_folder_cancel":
            # ביטול יצירת תיקייה וחזרה לתפריט GitHub
            context.user_data["waiting_for_new_folder_path"] = False
            context.user_data["return_to_pre_upload"] = False
            await self.github_menu_command(update, context)
            return REPO_SELECT

        elif query.data == "github_menu":
            # חזרה לתפריט הראשי של GitHub
            context.user_data["waiting_for_github_upload"] = False
            context.user_data["in_github_menu"] = False
            context.user_data.pop("folder_select_mode", None)
            # נקה דגל סינון גיבויים לפי ריפו, אם קיים
            # נקה דגלים זמניים של יצירת ריפו חדש
            try:
                context.user_data.pop("waiting_for_new_repo_name", None)
                context.user_data.pop("new_repo_name", None)
                if context.user_data.get("upload_mode") == "github_create_repo_from_zip":
                    context.user_data.pop("upload_mode", None)
                    context.user_data.pop("new_repo_private", None)
            except Exception:
                pass
            try:
                context.user_data.pop("github_backup_context_repo", None)
            except Exception:
                pass
            await self.github_menu_command(update, context)
            return ConversationHandler.END
        
        elif query.data == "git_checkpoint":
            await self.git_checkpoint(update, context)
        
        elif query.data.startswith("git_checkpoint_doc:"):
            parts = query.data.split(":", 2)
            kind = parts[1] if len(parts) > 1 else ""
            name = parts[2] if len(parts) > 2 else ""
            await self.create_checkpoint_doc(update, context, kind, name)
        
        elif query.data == "git_checkpoint_doc_skip":
            kb = [[InlineKeyboardButton("🔙 חזור", callback_data="back_to_menu")]]
            await query.edit_message_text(
                "✅ נקודת שמירה נוצרה. ניתן לחזור לתפריט או להעלות קבצים שמורים.",
                reply_markup=InlineKeyboardMarkup(kb),
            )
        
        elif query.data == "restore_checkpoint_menu":
            await self.show_restore_checkpoint_menu(update, context)
        
        elif query.data.startswith("restore_tags_page_"):
            try:
                p = int(query.data.split("_")[-1])
            except Exception:
                p = 0
            context.user_data["restore_tags_page"] = max(0, p)
            await self.show_restore_checkpoint_menu(update, context)
        
        elif query.data.startswith("restore_select_tag:"):
            tag_name = query.data.split(":", 1)[1]
            await self.show_restore_tag_actions(update, context, tag_name)
        
        elif query.data.startswith("restore_branch_from_tag:"):
            tag_name = query.data.split(":", 1)[1]
            await self.create_branch_from_tag(update, context, tag_name)

        elif query.data.startswith("open_pr_from_branch:"):
            branch_name = query.data.split(":", 1)[1]
            await self.open_pr_from_branch(update, context, branch_name)

        elif query.data.startswith("restore_revert_pr_from_tag:"):
            tag_name = query.data.split(":", 1)[1]
            await self.create_revert_pr_from_tag(update, context, tag_name)

        elif query.data == "close_menu":
            await query.edit_message_text("👋 התפריט נסגר")

        elif query.data.startswith("repo_"):
            if query.data == "repo_manual":
                await query.edit_message_text(
                    "✏️ הקלד שם ריפו בפורמט:\n"
                    "<code>owner/repository</code>\n\n"
                    "לדוגמה: <code>amirbiron/CodeBot</code>",
                    parse_mode="HTML",
                )
                return REPO_SELECT
            else:
                repo_name = query.data.replace("repo_", "")
                session["selected_repo"] = repo_name
                # איפוס תיקיות יעד ישנות בעת בחירת ריפו חדש
                session["selected_folder"] = None
                context.user_data.pop("upload_target_folder", None)
                context.user_data.pop("upload_target_branch", None)

                # נקה סטייטים זמניים של זרם שחזור/גיבוי כדי למנוע נעילה לריפו קודם
                try:
                    context.user_data.pop("zip_restore_expected_repo_full", None)
                    context.user_data.pop("github_restore_zip_purge", None)
                    context.user_data.pop("pending_repo_restore_zip_path", None)
                    context.user_data.pop("upload_mode", None)
                except Exception:
                    pass

                # שמור במסד נתונים
                from database import db

                db.save_selected_repo(user_id, repo_name)

                # הצג את התפריט המלא אחרי בחירת הריפו
                await self.github_menu_command(update, context)
                return

        elif query.data == "danger_delete_menu":
            await self.show_danger_delete_menu(update, context)

        elif query.data == "delete_file_menu":
            await self.show_delete_file_menu(update, context)

        elif query.data == "delete_repo_menu":
            await self.show_delete_repo_menu(update, context)

        elif query.data == "confirm_delete_file":
            await self.confirm_delete_file(update, context)

        elif query.data == "confirm_delete_repo_step1":
            await self.confirm_delete_repo_step1(update, context)

        elif query.data == "confirm_delete_repo":
            await self.confirm_delete_repo(update, context)

        elif query.data == "download_file_menu":
            await self.show_download_file_menu(update, context)

        elif query.data.startswith("browse_open:") or query.data.startswith("browse_open_i:"):
            path = self._get_path_from_cb(context, query.data, "browse_open")
            context.user_data["browse_path"] = path
            context.user_data["browse_page"] = 0
            # מצב מרובה ומחיקה בטוחה לאיפוס
            context.user_data["multi_selection"] = []
            await self.show_repo_browser(update, context)
        elif query.data == "browse_ref_menu":
            await self.show_browse_ref_menu(update, context)
        elif query.data.startswith("browse_refs_branches_page_"):
            try:
                p = int(query.data.rsplit('_', 1)[1])
            except Exception:
                p = 0
            context.user_data["browse_refs_branches_page"] = max(0, p)
            context.user_data["browse_ref_tab"] = "branches"
            await self.show_browse_ref_menu(update, context)
        elif query.data.startswith("browse_refs_tags_page_"):
            try:
                p = int(query.data.rsplit('_', 1)[1])
            except Exception:
                p = 0
            context.user_data["browse_refs_tags_page"] = max(0, p)
            context.user_data["browse_ref_tab"] = "tags"
            await self.show_browse_ref_menu(update, context)
        elif query.data.startswith("browse_select_ref:"):
            # עדכון ref נוכחי והחזרה לדפדפן
            ref = query.data.split(":", 1)[1]
            context.user_data["browse_ref"] = ref
            context.user_data["browse_page"] = 0
            await self.show_repo_browser(update, context)
        elif query.data == "browse_search":
            # בקש מהמשתמש להזין מחרוזת חיפוש לשמות קבצים
            context.user_data["browse_search_mode"] = True
            try:
                await query.answer("הקלד עכשיו את השם לחיפוש (למשל: README)")
            except Exception:
                pass
            try:
                await query.edit_message_text(
                    "🔎 הזן/י מחרוזת לחיפוש בשם קובץ (לדוגמה: README או app.py)",
                )
            except BadRequest as br:
                if "message is not modified" not in str(br).lower():
                    raise
        elif query.data.startswith("browse_search_page:"):
            try:
                page = int(query.data.split(":", 1)[1])
            except Exception:
                page = 1
            context.user_data["browse_search_page"] = max(1, page)
            await self.show_browse_search_results(update, context)
        elif query.data.startswith("browse_select_download:") or query.data.startswith("browse_select_download_i:"):
            path = self._get_path_from_cb(context, query.data, "browse_select_download")
            # שמור על browse_action=download כדי שלא ייחשפו כפתורי מחיקה לאחר ההורדה
            context.user_data.pop("waiting_for_download_file_path", None)
            # אל תאפס את browse_action; נשמור אותו כ-download
            try:
                if context.user_data.get("browse_action") != "download":
                    context.user_data["browse_action"] = "download"
            except Exception:
                context.user_data["browse_action"] = "download"
            # שמור את הנתיב האחרון כדי שהדפדפן יישאר באותו מיקום
            try:
                context.user_data["browse_path"] = context.user_data.get("browse_path") or "/".join((path or "").split("/")[:-1])
            except Exception:
                pass
            # הורדה מיידית
            token = self.get_user_token(user_id)
            repo_name = session.get("selected_repo")
            if not token or not repo_name:
                await query.edit_message_text("❌ חסר טוקן או ריפו נבחר")
                return
            g = Github(token)
            repo = g.get_repo(repo_name)
            contents = repo.get_contents(path)
            # אם הקובץ גדול מדי, שלח קישור להורדה במקום תוכן מלא
            size = getattr(contents, "size", 0) or 0
            if size and size > MAX_INLINE_FILE_BYTES:
                download_url = getattr(contents, "download_url", None)
                if download_url:
                    await query.message.reply_text(
                        f'⚠️ הקובץ גדול ({format_bytes(size)}). להורדה: <a href="{download_url}">קישור ישיר</a>',
                        parse_mode="HTML",
                    )
                else:
                    await query.message.reply_text(
                        f"⚠️ הקובץ גדול ({format_bytes(size)}) ולא ניתן להורידו ישירות כרגע."
                    )
            else:
                data = contents.decoded_content
                base = __import__('os').path
                filename = base.basename(contents.path) or "downloaded_file"
                await query.message.reply_document(document=BytesIO(data), filename=filename)
            # הישאר בדפדפן במצב הורדה בלבד, עדכן מקלדת בלי להחליף טקסט
            await self.show_repo_browser(update, context, only_keyboard=True)
        elif query.data.startswith("browse_select_view:") or query.data.startswith("browse_select_view_i:"):
            # מצב תצוגת קובץ חלקית עם "הצג עוד"
            path = self._get_path_from_cb(context, query.data, "browse_select_view")
            user_id = query.from_user.id
            session = self.get_user_session(user_id)
            token = self.get_user_token(user_id)
            repo_name = session.get("selected_repo")
            if not (token and repo_name):
                await query.edit_message_text("❌ חסרים נתונים (בחר ריפו עם /github)")
                return
            g = Github(token)
            repo = g.get_repo(repo_name)
            # כבדוק ref נוכחי
            try:
                current_ref = (context.user_data.get("browse_ref") or getattr(repo, "default_branch", None) or "main")
            except Exception:
                current_ref = getattr(repo, "default_branch", None) or "main"
            try:
                contents = repo.get_contents(path, ref=current_ref)
                data = contents.decoded_content.decode("utf-8", errors="replace")
                # שמירת נתוני עזר: גודל ושפה מזוהה
                try:
                    from utils import detect_language_from_filename
                    detected_lang = detect_language_from_filename(path)
                except Exception:
                    detected_lang = "text"
                context.user_data["view_file_size"] = int(getattr(contents, "size", 0) or 0)
                context.user_data["view_detected_language"] = detected_lang
            except Exception as e:
                await query.edit_message_text(f"❌ שגיאה בטעינת קובץ: {safe_html_escape(str(e))}", parse_mode="HTML")
                return
            # שימור טקסט בזיכרון קצר (user_data) + אינדקס עמוד
            context.user_data["view_file_path"] = path
            context.user_data["view_file_text"] = data
            context.user_data["view_page_index"] = 0
            await self._render_file_view(update, context)
        elif query.data == "view_more":
            # הצג עוד עמוד; נגן מפני None/מחרוזת
            try:
                current_index = int(context.user_data.get("view_page_index", 0) or 0)
            except Exception:
                current_index = 0
            context.user_data["view_page_index"] = current_index + 1
            await self._render_file_view(update, context)
        elif query.data == "view_back":
            # אם הגענו מתוצאות חיפוש – חזרה לעמוד החיפוש האחרון
            if context.user_data.get("last_results_were_search"):
                try:
                    await self.show_browse_search_results(update, context)
                finally:
                    # ננקה את הדגל רק אחרי שחזרנו למסך החיפוש
                    context.user_data.pop("last_results_were_search", None)
            else:
                # חזרה לעץ הריפו (שומר path)
                context.user_data["browse_action"] = "view"
                if context.user_data.get("browse_page") is None:
                    context.user_data["browse_page"] = 0
                await self.show_repo_browser(update, context)
        elif query.data.startswith("browse_select_delete:") or query.data.startswith("browse_select_delete_i:"):
            path = self._get_path_from_cb(context, query.data, "browse_select_delete")
            # דרוש אישור לפני מחיקה
            context.user_data["pending_delete_file_path"] = path
            keyboard = [
                [InlineKeyboardButton("✅ אישור מחיקה", callback_data="confirm_delete_file")],
                [InlineKeyboardButton("🔙 חזור", callback_data="github_menu")],
            ]
            await query.edit_message_text(
                "האם אתה בטוח שברצונך למחוק את הקובץ הבא?\n\n" f"<code>{path}</code>",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="HTML",
            )
        elif query.data.startswith("download_zip:") or query.data.startswith("download_zip_i:"):
            # הורדת התיקייה הנוכחית כקובץ ZIP
            current_path = self._get_path_from_cb(context, query.data, "download_zip")
            user_id = query.from_user.id
            session = self.get_user_session(user_id)
            token = self.get_user_token(user_id)
            repo_name = session.get("selected_repo")
            if not (token and repo_name):
                await query.edit_message_text("❌ חסרים נתונים")
                return
            try:
                await query.answer(
                    "מוריד תיקייה כ־ZIP, התהליך עשוי להימשך 1–2 דקות.", show_alert=True
                )
                g = Github(token)
                repo = g.get_repo(repo_name)
                # Fast path: הורדת ZIP מלא של הריפו דרך zipball
                if not current_path:
                    try:
                        import zipfile as _zip
                        from datetime import datetime as _dt, timezone as _tz
                        url = repo.get_archive_link("zipball")
                        r = requests.get(url, timeout=60)
                        r.raise_for_status()
                        # בנה ZIP חדש עם metadata.json משולב כדי לאפשר רישום בגיבויים
                        src_buf = BytesIO(r.content)
                        with _zip.ZipFile(src_buf, "r") as zin:
                            # ספר קבצים (דלג על תיקיות)
                            file_names = [n for n in zin.namelist() if not n.endswith("/")]
                            file_count = len(file_names)
                            total_bytes = len(r.content)
                            # צור ZIP חדש עם metadata
                            out_buf = BytesIO()
                            with _zip.ZipFile(out_buf, "w", compression=_zip.ZIP_DEFLATED) as zout:
                                metadata = {
                                    "backup_id": f"backup_{user_id}_{int(_dt.now(_tz.utc).timestamp())}",
                                    "user_id": user_id,
                                    "created_at": _dt.now(_tz.utc).isoformat(),
                                    "backup_type": "github_repo_zip",
                                    "include_versions": False,
                                    "file_count": file_count,
                                    "created_by": "Code Keeper Bot",
                                    "repo": repo.full_name,
                                    "path": current_path or ""
                                }
                                zout.writestr("metadata.json", json.dumps(metadata, indent=2))
                                for name in file_names:
                                    zout.writestr(name, zin.read(name))
                            out_buf.seek(0)
                            # שמור גיבוי (Mongo/FS בהתאם לקונפיג)
                            backup_manager.save_backup_bytes(out_buf.getvalue(), metadata)
                            # שלח למשתמש
                            # השתמש בשם ידידותי: BKP zip <repo> vN - DD/MM/YY
                            try:
                                infos = backup_manager.list_backups(user_id)
                                vcount = len([b for b in infos if getattr(b, 'repo', None) == repo.full_name])
                            except Exception:
                                vcount = 1
                            date_str = _dt.now(_tz.utc).strftime('%d-%m-%y %H.%M')
                            filename = f"BKP zip {repo.name} v{vcount} - {date_str}.zip"
                            out_buf.name = filename
                            caption = f"📦 ריפו מלא — {format_bytes(total_bytes)}.\n💾 נשמר ברשימת הגיבויים."
                            await query.message.reply_document(
                                document=out_buf, filename=filename, caption=caption
                            )
                            # הצג שורת סיכום בסגנון המבוקש ואז בקש תיוג
                            try:
                                backup_id = metadata.get("backup_id")
                                date_str = _dt.now(_tz.utc).strftime('%d/%m/%y %H:%M')
                                try:
                                    # חשב גרסת גיבוי (מספר רצים לאותו ריפו)
                                    infos = backup_manager.list_backups(user_id)
                                    vcount = len([b for b in infos if getattr(b, 'repo', None) == repo.full_name])
                                    v_text = f"(v{vcount}) " if vcount else ""
                                except Exception:
                                    v_text = ""
                                summary_line = f"⬇️ backup zip {repo.name} – {date_str} – {v_text}{format_bytes(total_bytes)}"
                                try:
                                    from database import db as _db
                                    existing_note = _db.get_backup_note(user_id, str(backup_id)) or ""
                                except Exception:
                                    existing_note = ""
                                note_btn_text = "📝 ערוך הערה" if existing_note else "📝 הוסף הערה"
                                kb = [
                                    [InlineKeyboardButton("🏆 מצוין", callback_data=f"backup_rate:{backup_id}:excellent")],
                                    [InlineKeyboardButton("👍 טוב", callback_data=f"backup_rate:{backup_id}:good")],
                                    [InlineKeyboardButton("🤷 סביר", callback_data=f"backup_rate:{backup_id}:ok")],
                                    [InlineKeyboardButton(note_btn_text, callback_data=f"backup_add_note:{backup_id}")],
                                ]
                                msg = await query.message.reply_text(summary_line, reply_markup=InlineKeyboardMarkup(kb))
                                try:
                                    s = context.user_data.setdefault("backup_summaries", {})
                                    s[backup_id] = {"chat_id": msg.chat.id, "message_id": msg.message_id, "text": summary_line}
                                except Exception:
                                    pass
                                # Rating buttons already attached above; no need to call external handler
                            except Exception:
                                pass
                    except Exception as e:
                        logger.error(f"Error fetching repo zipball: {e}")
                        try:
                            emit_event(
                                "github_zipball_fetch_error",
                                severity="error",
                                error=str(e),
                                repo=str(getattr(repo, "full_name", "")),
                            )
                            if errors_total is not None:
                                errors_total.labels(code="github_zipball_fetch_error").inc()
                        except Exception:
                            pass
                        try:
                            await query.edit_message_text(f"❌ שגיאה בהורדת ZIP של הריפו: {e}")
                        except BadRequest as br:
                            if "message is not modified" not in str(br).lower():
                                raise
                    # לאחר יצירת והורדת ה‑ZIP, הצג את רשימת הגיבויים עבור הריפו הנוכחי
                    try:
                        backup_handler = context.bot_data.get('backup_handler')
                        if backup_handler is None:
                            from backup_menu_handler import BackupMenuHandler
                            backup_handler = BackupMenuHandler()
                            context.bot_data['backup_handler'] = backup_handler
                        # הגדר הקשר חזרה לסאב־תפריט GitHub וגבילת הרשימה לריפו הנוכחי
                        try:
                            context.user_data['zip_back_to'] = 'github'
                            context.user_data['github_backup_context_repo'] = repo.full_name
                            context.user_data['backup_highlight_id'] = metadata.get('backup_id')
                        except Exception:
                            pass
                        await backup_handler._show_backups_list(update, context, page=1)
                    except Exception as br:
                        try:
                            await self.show_github_backup_menu(update, context)
                        except BadRequest as br2:
                            if "message is not modified" not in str(br2).lower():
                                raise
                    return

                zip_buffer = BytesIO()
                total_bytes = 0
                total_files = 0
                skipped_large = 0
                with zipfile.ZipFile(zip_buffer, "w", compression=zipfile.ZIP_DEFLATED) as zipf:
                    # קבע שם תיקיית השורש בתוך ה-ZIP
                    zip_root = repo.name if not current_path else current_path.split("/")[-1]

                    async def add_path_to_zip(path: str, rel_prefix: str):
                        # קבל את התוכן עבור הנתיב
                        contents = repo.get_contents(path or "")
                        if not isinstance(contents, list):
                            contents = [contents]
                        for item in contents:
                            if item.type == "dir":
                                await self.apply_rate_limit_delay(user_id)
                                await add_path_to_zip(item.path, f"{rel_prefix}{item.name}/")
                            elif item.type == "file":
                                await self.apply_rate_limit_delay(user_id)
                                file_obj = repo.get_contents(item.path)
                                file_size = getattr(file_obj, "size", 0) or 0
                                nonlocal total_bytes, total_files, skipped_large
                                if file_size > MAX_INLINE_FILE_BYTES:
                                    skipped_large += 1
                                    continue
                                if total_files >= MAX_ZIP_FILES:
                                    continue
                                if total_bytes + file_size > MAX_ZIP_TOTAL_BYTES:
                                    continue
                                data = file_obj.decoded_content
                                arcname = f"{zip_root}/{rel_prefix}{item.name}"
                                zipf.writestr(arcname, data)
                                total_bytes += len(data)
                                total_files += 1

                    await add_path_to_zip(current_path, "")
                # הוסף metadata.json
                metadata = {
                    "backup_id": f"backup_{user_id}_{int(datetime.now(timezone.utc).timestamp())}",
                    "user_id": user_id,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "backup_type": "github_repo_zip",
                    "include_versions": False,
                    "file_count": total_files,
                    "created_by": "Code Keeper Bot",
                    "repo": repo.full_name,
                    "path": current_path or ""
                }
                with zipfile.ZipFile(zip_buffer, 'a', compression=zipfile.ZIP_DEFLATED) as zipf:
                    zipf.writestr("metadata.json", json.dumps(metadata, indent=2))

                zip_buffer.seek(0)
                # שם ידידותי ל-folder/repo
                try:
                    infos = backup_manager.list_backups(user_id)
                    vcount = len([b for b in infos if getattr(b, 'repo', None) == repo.full_name])
                except Exception:
                    vcount = 1
                date_str = datetime.now(timezone.utc).strftime('%d-%m-%y %H.%M')
                name_part = repo.name if not current_path else current_path.split('/')[-1]
                filename = f"BKP zip {name_part} v{vcount} - {date_str}.zip"
                zip_buffer.name = filename
                caption = (
                    f"📦 קובץ ZIP לתיקייה: /{current_path or ''}\n"
                    f"מכיל {total_files} קבצים, {format_bytes(total_bytes)}.\n"
                    f"💾 נשמר ברשימת הגיבויים."
                )
                if skipped_large:
                    caption += f"\n⚠️ דילג על {skipped_large} קבצים גדולים (> {format_bytes(MAX_INLINE_FILE_BYTES)})."
                # שמור גיבוי (Mongo/FS בהתאם לקונפיג)
                try:
                    backup_manager.save_backup_bytes(zip_buffer.getvalue(), metadata)
                except Exception as e:
                    logger.warning(f"Failed to persist GitHub ZIP: {e}")
                    try:
                        emit_event(
                            "github_zip_persist_error",
                            severity="warn",
                            error=str(e),
                            repo=str(getattr(repo, "full_name", "")),
                        )
                    except Exception:
                        pass
                await query.message.reply_document(
                    document=zip_buffer, filename=filename, caption=caption
                )
                # הצג שורת סיכום בסגנון המבוקש ואז בקש תיוג
                try:
                    backup_id = metadata.get("backup_id")
                    date_str = datetime.now(timezone.utc).strftime('%d/%m/%y %H:%M')
                    try:
                        infos = backup_manager.list_backups(user_id)
                        vcount = len([b for b in infos if getattr(b, 'repo', None) == repo.full_name])
                        v_text = f"(v{vcount}) " if vcount else ""
                    except Exception:
                        v_text = ""
                    summary_line = f"⬇️ backup zip {repo.name} – {date_str} – {v_text}{format_bytes(total_bytes)}"
                    try:
                        from database import db as _db
                        existing_note = _db.get_backup_note(user_id, str(backup_id)) or ""
                    except Exception:
                        existing_note = ""
                    note_btn_text = "📝 ערוך הערה" if existing_note else "📝 הוסף הערה"
                    kb = [
                        [InlineKeyboardButton("🏆 מצוין", callback_data=f"backup_rate:{backup_id}:excellent")],
                        [InlineKeyboardButton("👍 טוב", callback_data=f"backup_rate:{backup_id}:good")],
                        [InlineKeyboardButton("🤷 סביר", callback_data=f"backup_rate:{backup_id}:ok")],
                        [InlineKeyboardButton(note_btn_text, callback_data=f"backup_add_note:{backup_id}")],
                    ]
                    msg = await query.message.reply_text(summary_line, reply_markup=InlineKeyboardMarkup(kb))
                    try:
                        s = context.user_data.setdefault("backup_summaries", {})
                        s[backup_id] = {"chat_id": msg.chat.id, "message_id": msg.message_id, "text": summary_line}
                    except Exception:
                        pass
                    # Rating buttons already attached above; no need to call external handler
                except Exception:
                    pass
            except Exception as e:
                logger.error(f"Error creating ZIP: {e}")
                try:
                    emit_event(
                        "github_zip_create_error",
                        severity="error",
                        error=str(e),
                        repo=str(getattr(repo, "full_name", "")),
                    )
                    if errors_total is not None:
                        errors_total.labels(code="github_zip_create_error").inc()
                except Exception:
                    pass
                try:
                    await query.edit_message_text(f"❌ שגיאה בהכנת ZIP: {e}")
                except BadRequest as br:
                    if "message is not modified" not in str(br).lower():
                        raise
                return
            # החזר לדפדפן באותו מקום
            # לאחר יצירת והורדת ה‑ZIP, הצג את רשימת הגיבויים עבור הריפו הנוכחי
            try:
                backup_handler = context.bot_data.get('backup_handler')
                if backup_handler is None:
                    from backup_menu_handler import BackupMenuHandler
                    backup_handler = BackupMenuHandler()
                    context.bot_data['backup_handler'] = backup_handler
                try:
                    context.user_data['zip_back_to'] = 'github'
                    context.user_data['github_backup_context_repo'] = repo.full_name
                    context.user_data['backup_highlight_id'] = metadata.get('backup_id')
                except Exception:
                    pass
                await backup_handler._show_backups_list(update, context, page=1)
            except Exception as br:
                try:
                    await self.show_repo_browser(update, context)
                except BadRequest as br2:
                    if "message is not modified" not in str(br2).lower():
                        raise

        elif query.data.startswith("inline_download_file:"):
            # הורדת קובץ שנבחר דרך אינליין
            path = query.data.split(":", 1)[1]
            user_id = query.from_user.id
            session = self.get_user_session(user_id)
            token = self.get_user_token(user_id)
            repo_name = session.get("selected_repo")
            if not (token and repo_name):
                await query.edit_message_text("❌ חסרים נתונים (בחר ריפו עם /github)")
                return

            # במצב Inline אין query.message ולכן reply_* יקרוס. נערוך את ההודעה המקורית
            # להודעת "+ מתחיל בהורדה" ונשלח את הקובץ בפרטי למשתמש.
            try:
                try:
                    await TelegramUtils.safe_edit_message_text(query, "⬇️ מתחיל בהורדה…")
                except Exception:
                    pass

                g = Github(token)
                repo = g.get_repo(repo_name)
                contents = repo.get_contents(path)
                size = getattr(contents, "size", 0) or 0

                # פונקציות שליחה בהתאם לסוג ההודעה
                async def _send_text(text: str, *, parse_mode: str | None = None):
                    if getattr(query, "message", None) is not None:
                        await query.message.reply_text(text, parse_mode=parse_mode)
                    else:
                        await context.bot.send_message(chat_id=user_id, text=text, parse_mode=parse_mode)

                async def _send_document(buf: BytesIO, filename: str, *, caption: str | None = None):
                    if getattr(query, "message", None) is not None:
                        await query.message.reply_document(document=buf, filename=filename, caption=caption)
                    else:
                        await context.bot.send_document(chat_id=user_id, document=buf, filename=filename, caption=caption)

                if size and size > MAX_INLINE_FILE_BYTES:
                    download_url = getattr(contents, "download_url", None)
                    if download_url:
                        await _send_text(
                            f'⚠️ הקובץ גדול ({format_bytes(size)}). להורדה: <a href="{download_url}">קישור ישיר</a>',
                            parse_mode="HTML",
                        )
                    else:
                        await _send_text(f"⚠️ הקובץ גדול ({format_bytes(size)}) ולא ניתן להורידו ישירות כרגע.")
                else:
                    data = contents.decoded_content
                    filename = os.path.basename(contents.path) or "downloaded_file"
                    await _send_document(BytesIO(data), filename)
            except Exception as e:
                logger.error(f"Inline download error: {e}")
                try:
                    emit_event(
                        "github_inline_download_error",
                        severity="error",
                        error=str(e),
                        repo=str(getattr(repo, "full_name", "")),
                        path=str(path),
                    )
                    if errors_total is not None:
                        errors_total.labels(code="github_inline_download_error").inc()
                except Exception:
                    pass
                try:
                    if getattr(query, "message", None) is not None:
                        await query.message.reply_text(f"❌ שגיאה בהורדה: {e}")
                    else:
                        await context.bot.send_message(chat_id=user_id, text=f"❌ שגיאה בהורדה: {e}")
                except Exception:
                    pass
            return

        elif query.data.startswith("browse_page:"):
            # מעבר עמודים בדפדפן הריפו
            try:
                page_index = int(query.data.split(":", 1)[1])
            except ValueError:
                page_index = 0
            context.user_data["browse_page"] = max(0, page_index)
            await self.show_repo_browser(update, context, only_keyboard=True)

        elif query.data == "multi_toggle":
            # הפעל/בטל מצב בחירה מרובה
            current = context.user_data.get("multi_mode", False)
            context.user_data["multi_mode"] = not current
            if not context.user_data["multi_mode"]:
                context.user_data["multi_selection"] = []
                try:
                    await query.answer("מצב בחירה מרובה בוטל", show_alert=False)
                except Exception:
                    pass
            else:
                try:
                    await query.answer("מצב בחירה מרובה הופעל — סמן קבצים מהרשימה", show_alert=False)
                except Exception:
                    pass
            context.user_data["browse_page"] = 0
            await self.show_repo_browser(update, context, only_keyboard=True)

        elif query.data.startswith("browse_toggle_select:"):
            # הוסף/הסר בחירה של קובץ
            path = query.data.split(":", 1)[1]
            selection = set(context.user_data.get("multi_selection", []))
            if path in selection:
                selection.remove(path)
            else:
                selection.add(path)
            context.user_data["multi_selection"] = list(selection)
            await self.show_repo_browser(update, context, only_keyboard=True)

        elif query.data == "multi_clear":
            # נקה בחירות
            context.user_data["multi_selection"] = []
            await self.show_repo_browser(update, context, only_keyboard=True)

        elif query.data == "safe_toggle":
            # החלף מצב מחיקה בטוחה
            new_state = not context.user_data.get("safe_delete", True)
            context.user_data["safe_delete"] = new_state
            try:
                await query.answer("מחיקה בטוחה " + ("פעילה (PR)" if new_state else "כבויה — מוחק ישירות"), show_alert=False)
            except Exception:
                pass
            await self.show_repo_browser(update, context, only_keyboard=True)
        elif query.data == "multi_execute":
            # בצע פעולה על הבחירה (ZIP בהורדה | מחיקה במצב מחיקה)
            selection = list(dict.fromkeys(context.user_data.get("multi_selection", [])))
            if not selection:
                await query.answer("לא נבחרו קבצים", show_alert=True)
                return
            user_id = query.from_user.id
            session = self.get_user_session(user_id)
            token = self.get_user_token(user_id)
            repo_name = session.get("selected_repo")
            if not (token and repo_name):
                await query.edit_message_text("❌ חסרים נתונים")
                return
            g = Github(token)
            repo = g.get_repo(repo_name)
            action = context.user_data.get("browse_action")
            if action == "download":
                # ארוז את הבחירה ל-ZIP
                try:
                    zip_buffer = BytesIO()
                    total_bytes = 0
                    total_files = 0
                    skipped_large = 0
                    with zipfile.ZipFile(zip_buffer, "w", compression=zipfile.ZIP_DEFLATED) as zipf:
                        for path in selection:
                            await self.apply_rate_limit_delay(user_id)
                            try:
                                file_obj = repo.get_contents(path)
                                if getattr(file_obj, "type", "file") != "file":
                                    continue
                                file_size = getattr(file_obj, "size", 0) or 0
                                if file_size > MAX_INLINE_FILE_BYTES:
                                    skipped_large += 1
                                    continue
                                if total_files >= MAX_ZIP_FILES:
                                    continue
                                if total_bytes + file_size > MAX_ZIP_TOTAL_BYTES:
                                    continue
                                data = file_obj.decoded_content
                                arcname = file_obj.path  # שמור מבנה נתיב
                                zipf.writestr(arcname, data)
                                total_bytes += len(data)
                                total_files += 1
                            except Exception:
                                continue
                    if total_files == 0:
                        await query.answer("אין קבצים מתאימים לאריזה", show_alert=True)
                    else:
                        zip_buffer.seek(0)
                        filename = f"{repo.name}-selected.zip"
                        caption = f"📦 ZIP לקבצים נבחרים — {total_files} קבצים, {format_bytes(total_bytes)}."
                        if skipped_large:
                            caption += f"\n⚠️ דילג על {skipped_large} קבצים גדולים (> {format_bytes(MAX_INLINE_FILE_BYTES)})."
                        await query.message.reply_document(
                            document=zip_buffer, filename=filename, caption=caption
                        )
                except Exception as e:
                    logger.error(f"Multi ZIP error: {e}")
                    try:
                        emit_event(
                            "github_multi_zip_error",
                            severity="error",
                            error=str(e),
                            repo=str(getattr(repo, "full_name", "")),
                            selected_count=int(len(selection) if isinstance(selection, (list, set, tuple)) else 0),
                        )
                        if errors_total is not None:
                            errors_total.labels(code="github_multi_zip_error").inc()
                    except Exception:
                        pass
                    await query.edit_message_text(f"❌ שגיאה באריזת ZIP: {e}")
                    return
                finally:
                    # לאחר פעולה, שמור בדפדפן
                    pass
                # השאר בדפדפן
                await self.show_repo_browser(update, context)
            else:
                # מחיקה של נבחרים
                safe_delete = context.user_data.get("safe_delete", True)
                default_branch = repo.default_branch or "main"
                successes = 0
                failures = 0
                pr_url = None
                if safe_delete:
                    # צור סניף חדש ומחוק בו, ואז פתח PR
                    try:
                        base_ref = repo.get_git_ref(f"heads/{default_branch}")
                        new_branch = f"delete-bot-{int(time.time())}"
                        repo.create_git_ref(ref=f"refs/heads/{new_branch}", sha=base_ref.object.sha)
                        for path in selection:
                            await self.apply_rate_limit_delay(user_id)
                            try:
                                contents = repo.get_contents(path, ref=new_branch)
                                repo.delete_file(
                                    contents.path,
                                    f"Delete via bot: {path}",
                                    contents.sha,
                                    branch=new_branch,
                                )
                                successes += 1
                            except Exception:
                                failures += 1
                        pr = repo.create_pull(
                            title=f"Delete {successes} files via bot",
                            body="Automated deletion",
                            base=default_branch,
                            head=new_branch,
                        )
                        pr_url = pr.html_url
                    except Exception as e:
                        logger.error(f"Safe delete failed: {e}")
                        try:
                            emit_event(
                                "github_safe_delete_error",
                                severity="error",
                                error=str(e),
                                repo=str(getattr(repo, "full_name", "")),
                                branch=str(default_branch),
                            )
                            if errors_total is not None:
                                errors_total.labels(code="github_safe_delete_error").inc()
                        except Exception:
                            pass
                        await query.edit_message_text(f"❌ שגיאה במחיקה בטוחה: {e}")
                        return
                else:
                    # מחיקה ישירה בבראנץ' ברירת המחדל
                    for path in selection:
                        await self.apply_rate_limit_delay(user_id)
                        try:
                            contents = repo.get_contents(path)
                            repo.delete_file(
                                contents.path,
                                f"Delete via bot: {path}",
                                contents.sha,
                                branch=default_branch,
                            )
                            successes += 1
                        except Exception as e:
                            logger.error(f"Delete file failed: {e}")
                            try:
                                emit_event(
                                    "github_delete_file_error",
                                    severity="error",
                                    error=str(e),
                                    repo=str(getattr(repo, "full_name", "")),
                                    path=str(path),
                                )
                                if errors_total is not None:
                                    errors_total.labels(code="github_delete_file_error").inc()
                            except Exception:
                                pass
                            failures += 1
                # סכם והצג
                summary = f"✅ נמחקו {successes} | ❌ נכשלו {failures}"
                if pr_url:
                    summary += f'\n🔗 נפתח PR: <a href="{pr_url}">קישור</a>'
                try:
                    await query.message.reply_text(summary, parse_mode="HTML")
                except Exception:
                    pass
                # אפס מצב מרובה וחזור לתפריט הדפדפן
                context.user_data["multi_mode"] = False
                context.user_data["multi_selection"] = []
                await self.show_repo_browser(update, context)

        elif query.data.startswith("share_folder_link:"):
            # שיתוף קישור לתיקייה
            path = query.data.split(":", 1)[1]
            user_id = query.from_user.id
            session = self.get_user_session(user_id)
            token = self.get_user_token(user_id)
            repo_name = session.get("selected_repo")
            if not (token and repo_name):
                await query.answer("❌ חסרים נתונים", show_alert=True)
                return
            g = Github(token)
            repo = g.get_repo(repo_name)
            branch = repo.default_branch or "main"
            clean_path = (path or "").strip("/")
            url = (
                f"https://github.com/{repo.full_name}/tree/{branch}/{clean_path}"
                if clean_path
                else f"https://github.com/{repo.full_name}/tree/{branch}"
            )
            try:
                await query.message.reply_text(f"🔗 קישור לתיקייה:\n{url}")
            except Exception:
                await query.answer("הקישור נשלח בהודעה חדשה")
            # הישאר בדפדפן
            await self.show_repo_browser(update, context)

        elif query.data == "share_selected_links":
            # שיתוף קישורים לקבצים נבחרים
            selection = list(dict.fromkeys(context.user_data.get("multi_selection", [])))
            if not selection:
                await query.answer("לא נבחרו קבצים", show_alert=True)
                return
            user_id = query.from_user.id
            session = self.get_user_session(user_id)
            token = self.get_user_token(user_id)
            repo_name = session.get("selected_repo")
            if not (token and repo_name):
                await query.answer("❌ חסרים נתונים", show_alert=True)
                return
            g = Github(token)
            repo = g.get_repo(repo_name)
            branch = repo.default_branch or "main"
            lines = []
            for p in selection[:50]:
                # guard: ensure string before strip
                clean = str(p).strip("/")
                url = f"https://github.com/{repo.full_name}/blob/{branch}/{clean}"
                lines.append(f"• {clean}: {url}")
            text = "🔗 קישורים לקבצים נבחרים:\n" + "\n".join(lines)
            try:
                await query.message.reply_text(text)
            except Exception as e:
                logger.error(f"share_selected_links error: {e}")
                try:
                    emit_event(
                        "github_share_selected_links_error",
                        severity="error",
                        error=str(e),
                        repo=str(getattr(repo, "full_name", "")),
                    )
                    if errors_total is not None:
                        errors_total.labels(code="github_share_selected_links_error").inc()
                except Exception:
                    pass
                await query.answer("שגיאה בשיתוף קישורים", show_alert=True)
            # השאר בדפדפן
            await self.show_repo_browser(update, context)

        elif query.data.startswith("share_selected_links_single:"):
            # שיתוף קישור לקובץ יחיד מתצוגה רגילה
            path = query.data.split(":", 1)[1]
            user_id = query.from_user.id
            session = self.get_user_session(user_id)
            token = self.get_user_token(user_id)
            repo_name = session.get("selected_repo")
            if not (token and repo_name):
                await query.answer("❌ חסרים נתונים", show_alert=True)
                return
            g = Github(token)
            repo = g.get_repo(repo_name)
            branch = repo.default_branch or "main"
            clean = str(path).strip("/")
            url = f"https://github.com/{repo.full_name}/blob/{branch}/{clean}"
            try:
                await query.message.reply_text(f"🔗 קישור לקובץ:\n{url}")
            except Exception as e:
                logger.error(f"share_single_link error: {e}")
                try:
                    emit_event(
                        "github_share_single_link_error",
                        severity="error",
                        error=str(e),
                        repo=str(getattr(repo, "full_name", "")),
                        path=str(path),
                    )
                    if errors_total is not None:
                        errors_total.labels(code="github_share_single_link_error").inc()
                except Exception:
                    pass
                await query.answer("שגיאה בשיתוף קישור", show_alert=True)
            await self.show_repo_browser(update, context, only_keyboard=True)

        elif query.data == "notifications_menu":
            await self.show_notifications_menu(update, context)
        elif query.data == "notifications_toggle":
            await self.toggle_notifications(update, context)
        elif query.data == "notifications_toggle_pr":
            await self.toggle_notifications_pr(update, context)
        elif query.data == "notifications_toggle_issues":
            await self.toggle_notifications_issues(update, context)
        elif query.data.startswith("notifications_interval_"):
            await self.set_notifications_interval(update, context)
        elif query.data == "notifications_check_now":
            await self.notifications_check_now(update, context)

        elif query.data == "pr_menu":
            await self.show_pr_menu(update, context)
        elif query.data == "create_pr_menu":
            context.user_data["pr_branches_page"] = 0
            await self.show_create_pr_menu(update, context)
        elif query.data.startswith("branches_page_"):
            try:
                p = int(query.data.split("_")[-1])
            except Exception:
                p = 0
            context.user_data["pr_branches_page"] = max(0, p)
            await self.show_create_pr_menu(update, context)
        elif query.data.startswith("pr_select_head:"):
            head = query.data.split(":", 1)[1]
            context.user_data["pr_head"] = head
            await self.show_confirm_create_pr(update, context)
        elif query.data == "confirm_create_pr":
            await self.confirm_create_pr(update, context)
        elif query.data == "merge_pr_menu":
            context.user_data["pr_list_page"] = 0
            await self.show_merge_pr_menu(update, context)
        elif query.data.startswith("prs_page_"):
            try:
                p = int(query.data.split("_")[-1])
            except Exception:
                p = 0
            context.user_data["pr_list_page"] = max(0, p)
            await self.show_merge_pr_menu(update, context)
        elif query.data.startswith("merge_pr:"):
            pr_number = int(query.data.split(":", 1)[1])
            context.user_data["pr_to_merge"] = pr_number
            await self.show_confirm_merge_pr(update, context)
        elif query.data == "refresh_merge_pr":
            await self.show_confirm_merge_pr(update, context)
        elif query.data == "confirm_merge_pr":
            await self.confirm_merge_pr(update, context)
        elif query.data == "validate_repo":
            status_message = None
            done_event = asyncio.Event()
            progress_task = None
            try:
                status_message = await query.edit_message_text("⏳ בודק תקינות הריפו... 0%")

                async def _progress_updater():
                    percent = 0
                    try:
                        while not done_event.is_set():
                            percent = min(percent + 7, 90)
                            try:
                                await status_message.edit_text(f"⏳ בודק תקינות הריפו... {percent}%")
                            except Exception:
                                pass
                            await asyncio.sleep(1.0)
                    except Exception:
                        pass

                progress_task = asyncio.create_task(_progress_updater())
                import tempfile, zipfile
                token_opt = self.get_user_token(user_id)
                g = Github(login_or_token=(token_opt or ""))
                repo_full = session.get("selected_repo")
                if not repo_full:
                    done_event.set()
                    if progress_task:
                        try:
                            await progress_task
                        except Exception:
                            pass
                    await (status_message.edit_text("❌ קודם בחר ריפו!") if status_message else query.edit_message_text("❌ קודם בחר ריפו!"))
                    return

                def do_validate():
                    repo = g.get_repo(repo_full)
                    url = repo.get_archive_link("zipball")
                    with tempfile.TemporaryDirectory(prefix="repo_val_") as tmp:
                        zip_path = os.path.join(tmp, "repo.zip")
                        r = requests.get(url, timeout=60)
                        r.raise_for_status()
                        with open(zip_path, "wb") as f:
                            f.write(r.content)
                        extract_dir = os.path.join(tmp, "repo")
                        os.makedirs(extract_dir, exist_ok=True)
                        with zipfile.ZipFile(zip_path, "r") as zf:
                            zf.extractall(extract_dir)
                        # GitHub zip יוצר תיקיית-שורש יחידה
                        entries = [os.path.join(extract_dir, d) for d in os.listdir(extract_dir)]
                        root = next((p for p in entries if os.path.isdir(p)), extract_dir)
                        # העתק קבצי קונפיג אם יש
                        try:
                            for name in (".flake8", "pyproject.toml", "mypy.ini", "bandit.yaml"):
                                src = os.path.join(os.getcwd(), name)
                                dst = os.path.join(root, name)
                                if os.path.isfile(src) and not os.path.isfile(dst):
                                    with open(src, "rb") as s, open(dst, "wb") as d:
                                        d.write(s.read())
                        except Exception:
                            pass
                        # הרצת כלים על כל הריפו
                        def _run(cmd, timeout=60):
                            import subprocess
                            try:
                                cp = subprocess.run(cmd, cwd=root, capture_output=True, text=True, timeout=timeout)
                                out = (cp.stdout or "") + (cp.stderr or "")
                                return cp.returncode, out.strip()
                            except subprocess.TimeoutExpired:
                                return 124, "Timeout"
                            except FileNotFoundError:
                                return 127, "Tool not installed"
                            except Exception as e:
                                return 1, str(e)
                        
                        # העדפת כלים מה-venv המקומי אם קיים
                        venv_bin = os.path.join(os.getcwd(), ".venv", "bin")
                        venv_python = os.path.join(venv_bin, "python")
                        
                        def _resolve_tool_candidates(tool_name):
                            candidates = []
                            if os.path.isdir(venv_bin):
                                candidates.append(os.path.join(venv_bin, tool_name))
                            if os.path.isfile(venv_python):
                                candidates.append([venv_python, "-m", tool_name])
                            candidates.append(tool_name)
                            return candidates

                        def _run_any(tool_name, base_args, timeout=60):
                            for candidate in _resolve_tool_candidates(tool_name):
                                cmd = (candidate if isinstance(candidate, list) else [candidate]) + base_args
                                rc, out = _run(cmd, timeout=timeout)
                                # אם הכלי לא נמצא, נסה מועמד הבא
                                if rc == 127:
                                    continue
                                return rc, out
                            return 127, "Tool not installed"
                        results = {}
                        results["flake8"] = _run_any("flake8", ["."])
                        results["mypy"] = _run_any("mypy", ["."])
                        results["bandit"] = _run_any("bandit", ["-q", "-r", "."]) 
                        results["black"] = _run_any("black", ["--check", "."]) 
                        return results, repo_full

                # הריץ ברקע כדי לא לחסום את לולאת האירועים
                results, repo_name_for_msg = await asyncio.to_thread(do_validate)
                done_event.set()
                if progress_task:
                    try:
                        await progress_task
                    except Exception:
                        pass

                # פורמט תוצאות מעוצב
                def status_label(rc):
                    return "OK" if rc == 0 else ("MISSING" if rc == 127 else ("TIMEOUT" if rc == 124 else "FAIL"))

                def status_emoji(rc):
                    return "✅" if rc == 0 else ("⛔" if rc == 127 else ("⏱️" if rc == 124 else "❌"))

                # תרגום סטטוסים לעברית להצגה
                he_label = {"OK": "תקין", "FAIL": "נכשל", "TIMEOUT": "פג זמן", "MISSING": "לא מותקן"}

                counts = {"OK": 0, "FAIL": 0, "TIMEOUT": 0, "MISSING": 0}
                max_tool_len = max((len(t) for t in results.keys()), default=0)
                rows = []
                for tool, (rc, output) in results.items():
                    label = status_label(rc)
                    counts[label] += 1
                    first_line = (output.splitlines() or [""])[0][:120]
                    suffix = f" — {escape(first_line)}" if label != "OK" and first_line else ""
                    rows.append(f"{tool.ljust(max_tool_len)} | {status_emoji(rc)} {he_label.get(label, label)}{suffix}")

                header = f"🧪 בדיקות מתקדמות לריפו <code>{safe_html_escape(repo_name_for_msg)}</code>\n"
                summary = f"סיכום: ✅ {counts['OK']}  ❌ {counts['FAIL']}  ⏱️ {counts['TIMEOUT']}  ⛔ {counts['MISSING']}"
                body = "\n".join(rows)

                # יצירת הצעות ממוקדות
                suggestions: list[str] = []

                # flake8 – הצעה להסרת ייבוא שלא בשימוש
                rc_flake8, out_flake8 = results.get("flake8", (0, ""))
                if rc_flake8 != 0 and out_flake8:
                    import re as _re
                    m = _re.search(r"^(?P<file>[^:\n]+):(?P<line>\d+):\d+:\s*F401\s+'([^']+)'\s+imported but unused", out_flake8, _re.M)
                    if m:
                        file_p = safe_html_escape(m.group("file"))
                        line_p = safe_html_escape(m.group("line"))
                        # לא תמיד אפשר לשלוף את השם בבטחה בטלגרם – משאירים כללי
                        suggestions.append(f"<b>flake8</b>: הסר ייבוא שלא בשימוש בשורה {line_p} בקובץ <code>{file_p}</code>")

                # mypy – הצעה ל-Optional כאשר ברירת מחדל None לסוג לא-Optional
                rc_mypy, out_mypy = results.get("mypy", (0, ""))
                if rc_mypy != 0 and out_mypy:
                    import re as _re
                    m = _re.search(r"Incompatible default for argument \"(?P<arg>[^\"]+)\" \(default has type \"None\", argument has type \"(?P<typ>[^\"]+)\"", out_mypy)
                    if m:
                        arg_p = safe_html_escape(m.group("arg"))
                        typ_p = safe_html_escape(m.group("typ"))
                        suggestions.append(f"<b>mypy</b>: הגדר Optional[{typ_p}] לפרמטר <code>{arg_p}</code> או שנה את ברירת המחדל מ-None")

                # black – הצעה להריץ black על קבצים ספציפיים
                rc_black, out_black = results.get("black", (0, ""))
                if rc_black != 0 and out_black:
                    import re as _re
                    files = _re.findall(r"would reformat\s+(.+)", out_black)
                    if files:
                        raw_path = files[0]
                        # נסה לקצר מסלול זמני של zip לנתיב יחסי בתוך הריפו
                        try:
                            _m = _re.search(r".*/repo/[^/]+/(.+)$", raw_path)
                            short_path = _m.group(1) if _m else raw_path
                        except Exception:
                            short_path = raw_path
                        file1 = safe_html_escape(short_path)
                        suggestions.append(f"<b>black</b>: הרץ black על <code>{file1}</code> או על הפרויקט כולו ליישור פורמט")

                # bandit – הצעות כלליות בהתאם לדפוסים נפוצים
                rc_bandit, out_bandit = results.get("bandit", (0, ""))
                if rc_bandit != 0 and out_bandit:
                    if "eval(" in out_bandit or "B307" in out_bandit:
                        suggestions.append("<b>bandit</b>: החלף שימוש ב-eval בפתרון בטוח יותר (למשל ast.literal_eval)")
                    elif "exec(" in out_bandit or "B102" in out_bandit:
                        suggestions.append("<b>bandit</b>: הימנע מ-exec והשתמש באלטרנטיבות בטוחות")

                message = f"{header}{summary}\n<pre>{body}</pre>"
                if suggestions:
                    # שימור תגיות HTML בתוך ההצעות תוך בריחה של תוכן דינמי נעשה כבר בשלב בניית ההצעות
                    sug_text = "\n".join(f"• {s}" for s in suggestions[:4])
                    message += f"\n\n💡 הצעות ממוקדות:\n{sug_text}"

                # הוסף כפתור חזרה לתפריט GitHub
                kb = [[InlineKeyboardButton("🔙 חזרה לתפריט GitHub", callback_data="github_menu")]]
                await query.edit_message_text(message, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))
            except Exception as e:
                # ודא סגירת עדכון התקדמות גם בשגיאה
                try:
                    done_event.set()
                    if progress_task:
                        try:
                            await progress_task
                        except Exception:
                            pass
                except Exception:
                    pass
                logger.exception("Repo validation failed")
                await query.edit_message_text(f"❌ שגיאה בבדיקת הריפו: {safe_html_escape(e)}", parse_mode="HTML")

    async def show_repo_selection(self, query, context: ContextTypes.DEFAULT_TYPE):
        """Show repository selection menu"""
        await self.show_repos(query.message, context, query=query)

    async def show_repos(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 0, query=None
    ):
        """מציג רשימת ריפוזיטוריז עם pagination"""
        if query:
            user_id = query.from_user.id
        else:
            user_id = update.effective_user.id

        session = self.user_sessions.get(user_id, {})

        if not self.get_user_token(user_id):
            if query:
                await query.answer("❌ נא להגדיר טוקן קודם")
            else:
                await update.reply_text("❌ נא להגדיר טוקן קודם")
            return

        try:
            # בדוק אם יש repos ב-context.user_data ואם הם עדיין תקפים
            cache_time = context.user_data.get("repos_cache_time", 0)
            current_time = time.time()
            cache_age = current_time - cache_time
            cache_max_age = 3600  # שעה אחת

            needs_refresh = "repos" not in context.user_data or cache_age > cache_max_age

            if needs_refresh:
                logger.info(
                    f"[GitHub API] Fetching repos for user {user_id} (cache age: {int(cache_age)}s)"
                )

                # אם אין cache או שהוא ישן, בצע בקשה ל-API

                _tok = self.get_user_token(user_id)
                g = Github(login_or_token=(_tok or ""))

                # בדוק rate limit לפני הבקשה
                rate = g.get_rate_limit()
                logger.info(
                    f"[GitHub API] Rate limit - Remaining: {rate.core.remaining}/{rate.core.limit}"
                )

                if rate.core.remaining < 100:
                    logger.warning(
                        f"[GitHub API] Low on API calls! Only {rate.core.remaining} remaining"
                    )

                if rate.core.remaining < 10:
                    # אם יש cache ישן, השתמש בו במקום לחסום
                    if "repos" in context.user_data:
                        logger.warning(f"[GitHub API] Using stale cache due to rate limit")
                        all_repos = context.user_data["repos"]
                    else:
                        if query:
                            await query.answer(
                                f"⏳ מגבלת API נמוכה! נותרו רק {rate.core.remaining} בקשות",
                                show_alert=True,
                            )
                            return
                else:
                    # הוסף delay בין בקשות
                    await self.apply_rate_limit_delay(user_id)

                    user = g.get_user()
                    logger.info(f"[GitHub API] Getting repos for user: {user.login}")

                    # קבל את כל הריפוזיטוריז - טען רק פעם אחת!
                    context.user_data["repos"] = list(user.get_repos())
                    context.user_data["repos_cache_time"] = current_time
                    logger.info(
                        f"[GitHub API] Loaded {len(context.user_data['repos'])} repos into cache"
                    )
                    all_repos = context.user_data["repos"]
            else:
                logger.info(
                    f"[Cache] Using cached repos for user {user_id} - {len(context.user_data.get('repos', []))} repos (age: {int(cache_age)}s)"
                )
                all_repos = context.user_data["repos"]

            # הגדרות pagination
            repos_per_page = 8
            total_repos = len(all_repos)
            total_pages = (total_repos + repos_per_page - 1) // repos_per_page

            # חשב אינדקסים
            start_idx = page * repos_per_page
            end_idx = min(start_idx + repos_per_page, total_repos)

            # ריפוזיטוריז לעמוד הנוכחי
            page_repos = all_repos[start_idx:end_idx]

            keyboard = []

            # הוסף ריפוזיטוריז
            for repo in page_repos:
                keyboard.append(
                    [
                        InlineKeyboardButton(
                            f"📁 {repo.name}", callback_data=f"repo_{repo.full_name}"
                        )
                    ]
                )

            # כפתורי ניווט
            nav_buttons = []
            if page > 0:
                nav_buttons.append(
                    InlineKeyboardButton("⬅️ הקודם", callback_data=f"repos_page_{page-1}")
                )

            nav_buttons.append(
                InlineKeyboardButton(f"📄 {page+1}/{total_pages}", callback_data="noop")
            )

            if page < total_pages - 1:
                nav_buttons.append(
                    InlineKeyboardButton("➡️ הבא", callback_data=f"repos_page_{page+1}")
                )

            if nav_buttons:
                keyboard.append(nav_buttons)

            # כפתורים נוספים
            keyboard.append(
                [InlineKeyboardButton("✍️ הקלד שם ריפו ידנית", callback_data="repo_manual")]
            )
            keyboard.append([InlineKeyboardButton("🔙 חזור", callback_data="back_to_menu")])

            reply_markup = InlineKeyboardMarkup(keyboard)

            if query:
                await query.edit_message_text(
                    f"בחר ריפוזיטורי (עמוד {page+1} מתוך {total_pages}):", reply_markup=reply_markup
                )
            else:
                try:
                    await update.callback_query.edit_message_text(
                        f"בחר ריפוזיטורי (עמוד {page+1} מתוך {total_pages}):", reply_markup=reply_markup
                    )
                except Exception:
                    await update.message.reply_text(
                        f"בחר ריפוזיטורי (עמוד {page+1} מתוך {total_pages}):",
                        reply_markup=reply_markup,
                    )

        except Exception as e:
            error_msg = str(e)

            # בדוק אם זו שגיאת rate limit
            if "rate limit" in error_msg.lower() or "403" in error_msg:
                error_msg = "⏳ חריגה ממגבלת GitHub API\n" "נסה שוב בעוד כמה דקות"
            else:
                error_msg = f"❌ שגיאה: {error_msg}"

            if query:
                await query.answer(error_msg, show_alert=True)
            else:
                try:
                    await update.callback_query.answer(error_msg, show_alert=True)
                except Exception:
                    await update.message.reply_text(error_msg)
 

    async def show_upload_other_files(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """מציג רק קבצים שאינם מתויגים repo: ואינם קבצים גדולים, עם עימוד ואימוג'י לפי שפה."""
        user_id = update.effective_user.id
        from database import db
        query = update.callback_query
        try:
            # קריאת נתונים
            all_files = db.get_user_files(user_id, limit=1000)
            large_files, _ = db.get_user_large_files(user_id, page=1, per_page=10000)
            large_names = {lf.get('file_name') for lf in large_files if lf.get('file_name')}

            other_files = []
            for f in all_files:
                name = f.get('file_name')
                tags = f.get('tags') or []
                if name and name not in large_names and not any(isinstance(t, str) and t.startswith('repo:') for t in tags):
                    other_files.append(f)

            if not other_files:
                await query.edit_message_text("ℹ️ אין 'שאר קבצים' להצגה (לא מתויגים כריפו ואינם גדולים)")
                return

            # מצב עמוד ובחירה
            try:
                page = int(context.user_data.get("other_files_page", 1))
            except Exception:
                page = 1
            per_page = 20
            total = len(other_files)
            pages = max(1, (total + per_page - 1) // per_page)
            if page > pages:
                page = pages
                context.user_data["other_files_page"] = page
            start = (page - 1) * per_page
            end = start + per_page
            page_items = other_files[start:end]

            # בניית מקלדת לבחירת קובץ יחיד להעלאה
            keyboard = []
            from utils import get_language_emoji, detect_language_from_filename
            for f in page_items:
                fid = str(f.get('_id'))
                name = f.get('file_name', 'ללא שם')
                lang = detect_language_from_filename(name)
                emoji = get_language_emoji(lang)
                keyboard.append([InlineKeyboardButton(f"{emoji} {name}", callback_data=f"upload_saved_{fid}")])

            # ניווט עמודים
            nav = []
            if page > 1:
                nav.append(InlineKeyboardButton("⬅️ הקודם", callback_data=f"other_files_page_{page-1}"))
            if page < pages:
                nav.append(InlineKeyboardButton("➡️ הבא", callback_data=f"other_files_page_{page+1}"))
            if nav:
                keyboard.append(nav)

            keyboard.append([InlineKeyboardButton("🔙 חזור", callback_data="upload_file")])

            await query.edit_message_text(
                f"בחר/י קובץ להעלאה (שאר הקבצים) — עמוד {page}/{pages}:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        except Exception as e:
            await query.edit_message_text(f"❌ שגיאה בטעינת 'שאר הקבצים': {e}")

    async def show_upload_repos(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """מציג תפריט ריפואים לבחירת קבצים שמורים עם תגית repo: להעלאה"""
        user_id = update.effective_user.id
        from database import db
        query = update.callback_query
        try:
            files = db.get_user_files(user_id, limit=1000)
            repo_to_count: dict[str, int] = {}
            for f in files:
                for t in f.get('tags', []) or []:
                    if isinstance(t, str) and t.startswith('repo:'):
                        repo_to_count[t] = repo_to_count.get(t, 0) + 1
            if not repo_to_count:
                await query.edit_message_text("ℹ️ אין קבצים עם תגית ריפו (repo:owner/name)")
                return
            keyboard = []
            for tag, cnt in sorted(repo_to_count.items(), key=lambda x: x[0])[:50]:
                keyboard.append([InlineKeyboardButton(f"{tag} ({cnt})", callback_data=f"gh_upload_repo:{tag}")])
            keyboard.append([InlineKeyboardButton("🔙 חזור", callback_data="upload_file")])
            await query.edit_message_text("בחר/י ריפו (מתוך תגיות הקבצים השמורים):", reply_markup=InlineKeyboardMarkup(keyboard))
        except Exception as e:
            await query.edit_message_text(f"❌ שגיאה בטעינת רשימת ריפואים: {e}")
    async def show_upload_repo_files(self, update: Update, context: ContextTypes.DEFAULT_TYPE,_repo_tag: str):
        """מציג קבצים שמורים תחת תגית ריפו שנבחרה ומאפשר להעלותם עם עימוד"""
        user_id = update.effective_user.id
        from database import db
        query = update.callback_query
        try:
            repo_tag = _repo_tag
            # עימוד: קרא מה-context או התחל בעמוד 1
            try:
                page = int((context.user_data.get("repo_files_page") or {}).get(repo_tag, 1))
            except Exception:
                page = 1
            per_page = 50
            files, total = db.get_user_files_by_repo(user_id, repo_tag, page=page, per_page=per_page)
            if not files:
                await query.edit_message_text("ℹ️ אין קבצים תחת התגית הזו")
                return
            pages = max(1, (total + per_page - 1) // per_page)
            # בניית כפתורים
            keyboard = []
            for f in files:
                fid = str(f.get('_id'))
                name = f.get('file_name', 'ללא שם')
                keyboard.append([InlineKeyboardButton(f"📄 {name}", callback_data=f"upload_saved_{fid}")])
            nav = []
            if page > 1:
                nav.append(InlineKeyboardButton("⬅️ הקודם", callback_data=f"repo_files_page:{repo_tag}:{page-1}"))
            if page < pages:
                nav.append(InlineKeyboardButton("➡️ הבא", callback_data=f"repo_files_page:{repo_tag}:{page+1}"))
            if nav:
                keyboard.append(nav)
            keyboard.append([InlineKeyboardButton("🔙 חזור", callback_data="gh_upload_cat:repos")])
            await query.edit_message_text(
                f"בחר/י קובץ להעלאה מהתגית {repo_tag} (עמוד {page}/{pages}, סך הכל {total}):",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        except Exception as e:
            await query.edit_message_text(f"❌ שגיאה בטעינת קבצים: {e}")

    async def upload_large_files_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """מציג רשימת קבצים גדולים להעלאה לריפו הנבחר"""
        user_id = update.effective_user.id
        from database import db
        query = update.callback_query
        try:
            large_files, total = db.get_user_large_files(user_id, page=1, per_page=50)
            if not large_files:
                await query.edit_message_text("ℹ️ אין קבצים גדולים שמורים")
                return
            keyboard = []
            for lf in large_files:
                fid = str(lf.get('_id'))
                name = lf.get('file_name', 'ללא שם')
                size_kb = (lf.get('file_size', 0) or 0) / 1024
                keyboard.append([InlineKeyboardButton(f"📄 {name} ({size_kb:.0f}KB)", callback_data=f"gh_upload_large:{fid}")])
            keyboard.append([InlineKeyboardButton("🔙 חזור", callback_data="upload_file")])
            await query.edit_message_text("בחר/י קובץ גדול להעלאה:", reply_markup=InlineKeyboardMarkup(keyboard))
        except Exception as e:
            await query.edit_message_text(f"❌ שגיאה בטעינת קבצים גדולים: {e}")

    async def handle_large_file_upload(self, update: Update, context: ContextTypes.DEFAULT_TYPE, file_id: str):
        """מעלה קובץ גדול שנבחר לגיטהאב (עם אותן בדיקות כמו קובץ שמור רגיל)"""
        user_id = update.effective_user.id
        session = self.get_user_session(user_id)
        token = self.get_user_token(user_id)
        query = update.callback_query
        if not (session.get("selected_repo") and token):
            await query.edit_message_text("❌ קודם בחר ריפו/טוקן בגיטהאב")
            return
        # שלוף את תוכן הקובץ הגדול
        from database import db
        from bson import ObjectId
        doc = db.large_files_collection.find_one({"_id": ObjectId(file_id), "user_id": user_id})
        if not doc:
            await query.edit_message_text("❌ קובץ גדול לא נמצא")
            return
        # מאחדים עם זרימת show_pre_upload_check: נשתמש ב-pending_saved_file_id אחרי יצירת מסמך זמני
        try:
            # צור מסמך זמני בקולקשן הרגיל כדי למחזר את מסך הבדיקות
            temp = {
                "user_id": user_id,
                "file_name": doc.get("file_name") or "large_file.txt",
                "content": doc.get("content") or "",
            }
            res = db.collection.insert_one(temp)
            context.user_data["pending_saved_file_id"] = str(res.inserted_id)
            await self.show_pre_upload_check(update, context)
        except Exception as e:
            await query.edit_message_text(f"❌ שגיאה בהכנת קובץ גדול להעלאה: {e}")

    async def handle_saved_file_upload(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, file_id: str
    ):
        """מטפל בהעלאת קובץ שמור ל-GitHub"""
        user_id = update.effective_user.id
        session = self.get_user_session(user_id)

        if not session.get("selected_repo"):
            await update.callback_query.answer("❌ נא לבחור ריפו קודם")
            return

        try:
            from bson import ObjectId

            from database import db

            # קבל את הקובץ מהמסד
            file_data = db.collection.find_one({"_id": ObjectId(file_id), "user_id": user_id})

            if not file_data:
                await update.callback_query.answer("❌ קובץ לא נמצא", show_alert=True)
                return

            await update.callback_query.edit_message_text("⏳ מעלה קובץ ל-GitHub...")
            try:
                emit_event("github_upload_start", user_id=int(user_id), file_id=str(file_id))
            except Exception:
                pass

            # לוג פרטי הקובץ
            logger.info(f"📄 מעלה קובץ שמור: {file_data['file_name']}")

            # קבל את התוכן מהקובץ השמור
            # בדוק כמה אפשרויות לשדה content
            content = (
                file_data.get("content")
                or file_data.get("code")
                or file_data.get("data")
                or file_data.get("file_content", "")
            )

            if not content:
                await update.callback_query.edit_message_text("❌ תוכן הקובץ ריק או לא נמצא")
                return

            # PyGithub מקודד אוטומטית ל-base64, אז רק נוודא שהתוכן הוא string
            if isinstance(content, bytes):
                content = content.decode("utf-8")

            logger.info(f"✅ תוכן מוכן להעלאה, גודל: {len(content)} chars")

            # התחבר ל-GitHub

            token_opt = self.get_user_token(user_id)
            g = Github(token_opt) if token_opt else Github(None)
            token_opt = self.get_user_token(user_id)
            g = Github(token_opt) if token_opt else Github(None)
            token_opt = self.get_user_token(user_id)
            g = Github(token_opt) if token_opt else Github(None)

            # בדוק rate limit לפני הבקשה
            try:
                emit_event("github_rate_limit_check", severity="info")
            except Exception:
                pass
            logger.info(f"[GitHub API] Checking rate limit before uploading file")
            rate = g.get_rate_limit()
            logger.info(
                f"[GitHub API] Rate limit - Remaining: {rate.core.remaining}/{rate.core.limit}"
            )

            if rate.core.remaining < 100:
                logger.warning(
                    f"[GitHub API] Low on API calls! Only {rate.core.remaining} remaining"
                )

            if rate.core.remaining < 10:
                await update.callback_query.answer(
                    f"⏳ מגבלת API נמוכה מדי! נותרו רק {rate.core.remaining} בקשות", show_alert=True
                )
                return

            # הוסף delay בין בקשות
            await self.apply_rate_limit_delay(user_id)

            logger.info(f"[GitHub API] Getting repo: {session['selected_repo']}")
            repo = g.get_repo(session["selected_repo"])

            # Resolve target branch and folder
            branch = context.user_data.get("upload_target_branch") or repo.default_branch or "main"
            folder = context.user_data.get("upload_target_folder") or session.get("selected_folder")
            if folder and folder.strip():
                folder = folder.strip("/")
                file_path = f"{folder}/{file_data['file_name']}"
            else:
                file_path = file_data["file_name"]
            logger.info(f"📁 נתיב יעד: {file_path} (branch: {branch})")

            # נסה להעלות או לעדכן את הקובץ
            # מדידת ביצועים והוספת מטא-מידע על הריפו/הענף
            with track_performance("github_upload_saved_file", labels={"repo": str(session.get("selected_repo", ""))}):
                try:
                    logger.info(f"[GitHub API] Checking if file exists: {file_path} @ {branch}")
                    existing = repo.get_contents(file_path, ref=branch)
                    logger.info(f"[GitHub API] File exists, updating: {file_path}")
                    result = repo.update_file(
                        path=file_path,
                        message=f"Update {file_data['file_name']} via Telegram bot",
                        content=content,  # PyGithub יקודד אוטומטית
                        sha=existing.sha,
                        branch=branch,
                    )
                    action = "עודכן"
                    logger.info(f"✅ קובץ עודכן בהצלחה")
                    try:
                        emit_event(
                            "github_upload_saved_success",
                            severity="info",
                            repo=str(session.get("selected_repo")),
                            branch=str(branch),
                            path=str(file_path),
                            action="update",
                        )
                    except Exception:
                        pass
                except Exception:
                    logger.info(f"[GitHub API] File doesn't exist, creating: {file_path}")
                    result = repo.create_file(
                        path=file_path,
                        message=f"Upload {file_data['file_name']} via Telegram bot",
                        content=content,  # PyGithub יקודד אוטומטית
                        branch=branch,
                    )
                    action = "הועלה"
                    logger.info(f"[GitHub API] File created successfully: {file_path}")
                    try:
                        emit_event(
                            "github_upload_saved_success",
                            severity="info",
                            repo=str(session.get("selected_repo")),
                            branch=str(branch),
                            path=str(file_path),
                            action="create",
                        )
                    except Exception:
                        pass

            raw_url = (
                f"https://raw.githubusercontent.com/{session['selected_repo']}/{branch}/{file_path}"
            )

            await update.callback_query.edit_message_text(
                f"✅ הקובץ {action} בהצלחה!\n\n"
                f"📁 ריפו: <code>{session['selected_repo']}</code>\n"
                f"📂 מיקום: <code>{file_path}</code>\n"
                f"🔗 קישור ישיר:\n{raw_url}\n\n"
                f"שלח /github כדי לחזור לתפריט.",
                parse_mode="HTML",
            )

        except Exception as e:
            logger.error(f"❌ שגיאה בהעלאת קובץ שמור: {str(e)}", exc_info=True)
            try:
                emit_event("github_upload_saved_error", severity="error", error=str(e))
                if errors_total is not None:
                    errors_total.labels(code="github_upload_saved_error").inc()
            except Exception:
                pass

            error_msg = str(e)
            if "rate limit" in error_msg.lower() or "403" in error_msg:
                error_msg = (
                    "⏳ חריגה ממגבלת GitHub API\n"
                    "נסה שוב בעוד כמה דקות\n\n"
                    "💡 טיפ: המתן מספר דקות לפני ניסיון נוסף"
                )
            else:
                error_msg = f"❌ שגיאה בהעלאה:\n{error_msg}\n\nפרטים נוספים נשמרו בלוג."

            await update.callback_query.edit_message_text(error_msg)

    async def handle_file_upload(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle file upload"""
        user_id = update.message.from_user.id
        session = self.get_user_session(user_id)

        # בדוק אם אנחנו במצב העלאה לגיטהאב (תמיכה בשני המשתנים)
        if context.user_data.get("waiting_for_upload_folder"):
            # Capture folder path from user text and return to pre-upload check
            folder_text = (update.message.text or "").strip()
            # normalize: remove leading/trailing slashes
            folder_norm = folder_text.strip("/")
            context.user_data["upload_target_folder"] = folder_norm
            context.user_data["waiting_for_upload_folder"] = False
            await update.message.reply_text("✅ תיקיית יעד עודכנה. חוזר לבדיקות...")
            await self.show_pre_upload_check(update, context)
            return True

        if (
            context.user_data.get("waiting_for_github_upload")
            or context.user_data.get("upload_mode") == "github"
        ):
            # העלאה לגיטהאב
            repo_name = context.user_data.get("target_repo") or session.get("selected_repo")
            if not repo_name:
                await update.message.reply_text("❌ קודם בחר ריפו!\nשלח /github")
                return ConversationHandler.END

            if update.message.document:
                await update.message.reply_text("⏳ מעלה קובץ לגיטהאב...")
                try:
                    emit_event(
                        "github_upload_start",
                        user_id=int(user_id),
                        file_name=str(update.message.document.file_name),
                    )
                except Exception:
                    pass

                try:
                    file = await context.bot.get_file(update.message.document.file_id)
                    file_data = await file.download_as_bytearray()
                    filename = update.message.document.file_name

                    # לוג גודל וסוג הקובץ
                    file_size = len(file_data)
                    logger.info(f"📄 מעלה קובץ: {filename}, גודל: {file_size} bytes")

                    # PyGithub מקודד אוטומטית ל-base64, אז נמיר ל-string אם צריך
                    if isinstance(file_data, (bytes, bytearray)):
                        content = file_data.decode("utf-8")
                    else:
                        content = str(file_data)
                    logger.info(f"✅ תוכן מוכן להעלאה, גודל: {len(content)} chars")

                    token = self.get_user_token(user_id) or os.environ.get("GITHUB_TOKEN")

                    g = Github(login_or_token=(token or ""))

                    # בדוק rate limit לפני הבקשה
                    try:
                        emit_event("github_rate_limit_check", severity="info")
                    except Exception:
                        pass
                    logger.info(f"[GitHub API] Checking rate limit before file upload")
                    rate = g.get_rate_limit()
                    logger.info(
                        f"[GitHub API] Rate limit - Remaining: {rate.core.remaining}/{rate.core.limit}"
                    )

                    if rate.core.remaining < 100:
                        logger.warning(
                            f"[GitHub API] Low on API calls! Only {rate.core.remaining} remaining"
                        )

                    if rate.core.remaining < 10:
                        await update.message.reply_text(
                            f"⏳ מגבלת API נמוכה מדי!\n"
                            f"נותרו רק {rate.core.remaining} בקשות\n"
                            f"נסה שוב מאוחר יותר"
                        )
                        return ConversationHandler.END

                    # הוסף delay בין בקשות
                    await self.apply_rate_limit_delay(user_id)

                    logger.info(f"[GitHub API] Getting repo: {repo_name}")
                    repo = g.get_repo(repo_name)

                    # בניית נתיב הקובץ
                    folder = (
                        context.user_data.get("upload_target_folder")
                        or context.user_data.get("target_folder")
                        or session.get("selected_folder")
                    )
                    if folder and folder.strip() and folder != "root":
                        # הסר / מיותרים
                        folder = folder.strip("/")
                        file_path = f"{folder}/{filename}"
                    else:
                        # העלה ל-root
                        file_path = filename
                    logger.info(f"📁 נתיב יעד: {file_path}")

                    with track_performance("github_upload_direct_file", labels={"repo": str(repo_name)}):
                        try:
                            existing = repo.get_contents(file_path)
                            result = repo.update_file(
                                path=file_path,
                                message=f"Update {filename} via Telegram bot",
                                content=content,  # PyGithub יקודד אוטומטית
                                sha=existing.sha,
                            )
                            action = "עודכן"
                            logger.info(f"✅ קובץ עודכן בהצלחה")
                            try:
                                emit_event(
                                    "github_upload_direct_success",
                                    severity="info",
                                    repo=str(repo_name),
                                    path=str(file_path),
                                    action="update",
                                )
                            except Exception:
                                pass
                        except Exception:
                            result = repo.create_file(
                                path=file_path,
                                message=f"Upload {filename} via Telegram bot",
                                content=content,  # PyGithub יקודד אוטומטית
                            )
                            action = "הועלה"
                            logger.info(f"✅ קובץ נוצר בהצלחה")
                            try:
                                emit_event(
                                    "github_upload_direct_success",
                                    severity="info",
                                    repo=str(repo_name),
                                    path=str(file_path),
                                    action="create",
                                )
                            except Exception:
                                pass

                    raw_url = f"https://raw.githubusercontent.com/{repo_name}/main/{file_path}"

                    await update.message.reply_text(
                        f"✅ הקובץ {action} בהצלחה לגיטהאב!\n\n"
                        f"📁 ריפו: <code>{repo_name}</code>\n"
                        f"📂 מיקום: <code>{file_path}</code>\n"
                        f"🔗 קישור ישיר:\n{raw_url}\n\n"
                        f"שלח /github כדי לחזור לתפריט.",
                        parse_mode="HTML",
                    )

                    # נקה את הסטטוס
                    context.user_data["waiting_for_github_upload"] = False
                    context.user_data["upload_mode"] = None

                except Exception as e:
                    logger.error(f"❌ שגיאה בהעלאה: {str(e)}", exc_info=True)
                    try:
                        emit_event("github_upload_direct_error", severity="error", error=str(e))
                        if errors_total is not None:
                            errors_total.labels(code="github_upload_direct_error").inc()
                    except Exception:
                        pass

                    error_msg = str(e)

                    # בדוק אם זו שגיאת rate limit
                    if "rate limit" in error_msg.lower() or "403" in error_msg:
                        error_msg = (
                            "⏳ חריגה ממגבלת GitHub API\n"
                            "נסה שוב בעוד כמה דקות\n\n"
                            "💡 טיפ: המתן מספר דקות לפני ניסיון נוסף"
                        )
                    else:
                        error_msg = f"❌ שגיאה בהעלאה:\n{error_msg}\n\nפרטים נוספים נשמרו בלוג."

                    await update.message.reply_text(error_msg)
            else:
                await update.message.reply_text("⚠️ שלח קובץ להעלאה")

            return ConversationHandler.END
        else:
            # אם לא במצב העלאה לגיטהאב, תן למטפל הרגיל לטפל בזה
            return ConversationHandler.END

    async def handle_text_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle text input for various states"""
        user_id = update.message.from_user.id
        session = self.get_user_session(user_id)
        text = update.message.text
        logger.info(
            f"📝 GitHub text input handler: user={user_id}, waiting_for_repo={context.user_data.get('waiting_for_repo_url')}"
        )

        # הנתיבים למחיקה/הורדה עוברים דרך דפדפן הכפתורים כעת, לכן אין צורך לטפל כאן

        # הזן/בחר ריפו לניתוח
        if context.user_data.get("waiting_for_repo_url"):
            context.user_data["waiting_for_repo_url"] = False
            await self.analyze_repository(update, context, text)
            return True

        # הזנת שם ריפו חדש לזרימת יצירה מּZIP
        if context.user_data.get("waiting_for_new_repo_name"):
            # נקה את מצב ההמתנה
            context.user_data["waiting_for_new_repo_name"] = False
            name_raw = (text or "").strip()
            # סניטיזציה פשוטה: המרת רווחים למקף ואישור תווים מותרים
            safe = re.sub(r"\s+", "-", name_raw)
            safe = re.sub(r"[^A-Za-z0-9._-]", "-", safe)
            safe = safe.strip(".-_")
            if not safe:
                await update.message.reply_text("❌ שם ריפו לא תקין. נסה שוב עם אותיות/מספרים/.-_ בלבד.")
                context.user_data["waiting_for_new_repo_name"] = True
                return True
            # שמור את השם לבחירת יצירה
            context.user_data["new_repo_name"] = safe
            await update.message.reply_text(
                f"✅ שם הריפו נקבע: <code>{safe}</code>\nשלח עכשיו קובץ ZIP לפריסה.",
                parse_mode="HTML"
            )
            return True

        # זרימת הדבקת קוד: שלב 1 - קבלת תוכן
        if context.user_data.get("waiting_for_paste_content"):
            context.user_data["waiting_for_paste_content"] = False
            code_text = text or ""
            if not code_text.strip():
                context.user_data["waiting_for_paste_content"] = True
                await update.message.reply_text(
                    "⚠️ קיבלתי תוכן ריק. הדבק/י את הקוד שוב.",
                    reply_markup=InlineKeyboardMarkup([
                        [
                            InlineKeyboardButton("🔙 חזור", callback_data="upload_file"),
                            InlineKeyboardButton("❌ ביטול", callback_data="cancel_paste_flow"),
                        ]
                    ])
                )
                return True
            context.user_data["paste_content"] = code_text
            context.user_data["waiting_for_paste_filename"] = True
            await update.message.reply_text(
                "📄 איך לקרוא לקובץ?\nהקלד/י שם כולל סיומת (לדוגמה: app.py או index.ts).",
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("🔙 חזור", callback_data="upload_file"),
                        InlineKeyboardButton("❌ ביטול", callback_data="cancel_paste_flow"),
                    ]
                ])
            )
            return True

        # זרימת הדבקת קוד: שלב 2 - קבלת שם קובץ ופתיחת מסך הבדיקות
        if context.user_data.get("waiting_for_paste_filename"):
            context.user_data["waiting_for_paste_filename"] = False
            raw_name = (text or "").strip()
            # ולידציה בסיסית לשם קובץ
            safe_name = raw_name.replace("\\", "/").split("/")[-1]
            safe_name = re.sub(r"\s+", "_", safe_name)
            safe_name = safe_name.strip()
            if not safe_name or "." not in safe_name:
                context.user_data["waiting_for_paste_filename"] = True
                await update.message.reply_text(
                    "⚠️ שם קובץ לא תקין. ודא שם + סיומת, לדוגמה: main.py",
                    reply_markup=InlineKeyboardMarkup([
                        [
                            InlineKeyboardButton("🔙 חזור", callback_data="upload_file"),
                            InlineKeyboardButton("❌ ביטול", callback_data="cancel_paste_flow"),
                        ]
                    ])
                )
                return True

            if not session.get("selected_repo"):
                await update.message.reply_text("❌ קודם בחר/י ריפו. שלח/י /github")
                return True

            content = context.user_data.get("paste_content") or ""
            try:
                from database import db
                from datetime import datetime
                doc = {
                    "user_id": user_id,
                    "file_name": safe_name,
                    "content": content,
                    "created_at": datetime.utcnow(),
                    "tags": ["pasted"],
                }
                res = db.collection.insert_one(doc)
                context.user_data["pending_saved_file_id"] = str(res.inserted_id)
                # נקה תוכן זמני
                context.user_data.pop("paste_content", None)
                await self.show_pre_upload_check(update, context)
            except Exception as e:
                await update.message.reply_text(f"❌ שגיאה בשמירת הקובץ הזמני: {safe_html_escape(str(e))}", parse_mode="HTML")
            return True

        # חיפוש בשם קובץ מתוך דפדפן הריפו
        if context.user_data.get("browse_search_mode"):
            context.user_data["browse_search_mode"] = False
            query = (text or "").strip()
            if not query:
                await update.message.reply_text("❌ שאילתת חיפוש ריקה. נסה שוב דרך הכפתור.")
                return True
            context.user_data["browse_search_query"] = query
            context.user_data["browse_search_page"] = 1
            await self.show_browse_search_results(update, context)
            return True

        # בחירת תיקייה (מתוך "בחר תיקיית יעד" הכללי)
        if context.user_data.get("waiting_for_selected_folder"):
            context.user_data["waiting_for_selected_folder"] = False
            folder_raw = (text or "").strip()
            # Normalize: allow '/' or empty for root
            if folder_raw in {"", "/"}:
                session["selected_folder"] = None
                await update.message.reply_text("✅ תיקיית יעד עודכנה ל-root")
            else:
                # clean slashes and collapse duplicates
                folder_clean = re.sub(r"/+", "/", folder_raw.strip("/"))
                session["selected_folder"] = folder_clean
                await update.message.reply_text(
                    f"✅ תיקיית יעד עודכנה ל-<code>{safe_html_escape(folder_clean)}</code>",
                    parse_mode="HTML",
                )
            # חזרה לתפריט GitHub
            await self.github_menu_command(update, context)
            return True

        # יצירת תיקייה חדשה (גם מהתפריט וגם מתוך בדיקות לפני העלאה)
        if context.user_data.get("waiting_for_new_folder_path"):
            context.user_data["waiting_for_new_folder_path"] = False
            folder_raw = (text or "").strip()
            if folder_raw in {"", "/"}:
                await update.message.reply_text("❌ יש להזין נתיב תיקייה תקין (לדוגמה: src/new)")
                return True
            folder_clean = re.sub(r"/+", "/", folder_raw.strip("/"))

            # צור קובץ .gitkeep בתיקייה החדשה כדי ליצור אותה בגיט
            token = self.get_user_token(user_id)
            repo_full = session.get("selected_repo")
            if not (token and repo_full):
                await update.message.reply_text("❌ חסר טוקן או ריפו לא נבחר")
                return True
            try:
                g = Github(token)
                repo = g.get_repo(repo_full)
                target_branch = context.user_data.get("upload_target_branch") or getattr(repo, "default_branch", None) or "main"
                file_path = f"{folder_clean}/.gitkeep"
                content = "placeholder to keep directory"
                # נסה ליצור, ואם קיים נעדכן
                try:
                    existing = repo.get_contents(file_path, ref=target_branch)
                    repo.update_file(
                        path=file_path,
                        message=f"Update .gitkeep via bot in {folder_clean}",
                        content=content,
                        sha=existing.sha,
                        branch=target_branch,
                    )
                except Exception:
                    repo.create_file(
                        path=file_path,
                        message=f"Create folder {folder_clean} via bot",
                        content=content,
                        branch=target_branch,
                    )

                # אם נוצר מתוך זרימת ה-pre-upload, עדכן את תיקיית היעד וחזור לבדיקה
                if context.user_data.get("return_to_pre_upload"):
                    context.user_data["return_to_pre_upload"] = False
                    context.user_data["upload_target_folder"] = folder_clean
                    await update.message.reply_text(
                        f"✅ התיקייה נוצרה: <code>{safe_html_escape(folder_clean)}</code>\nחוזר למסך הבדיקות…",
                        parse_mode="HTML",
                    )
                    await self.show_pre_upload_check(update, context)
                else:
                    # אחרת, עדכן גם את התיקייה הנבחרת לשימוש עתידי וחזור לתפריט
                    session["selected_folder"] = folder_clean
                    await update.message.reply_text(
                        f"✅ התיקייה נוצרה ונבחרה: <code>{safe_html_escape(folder_clean)}</code>",
                        parse_mode="HTML",
                    )
                    await self.github_menu_command(update, context)
            except Exception as e:
                logger.error(f"Failed to create folder {folder_clean}: {e}", exc_info=True)
                await update.message.reply_text(
                    f"❌ יצירת תיקייה נכשלה: {safe_html_escape(str(e))}",
                    parse_mode="HTML",
                )
            return True

        # ברירת מחדל: סיים
        return ConversationHandler.END

    async def show_analyze_repo_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """מציג תפריט לניתוח ריפו"""
        logger.info("📋 Starting show_analyze_repo_menu function")
        query = update.callback_query
        user_id = query.from_user.id
        session = self.get_user_session(user_id)
        logger.info(
            f"📊 Session data: selected_repo={session.get('selected_repo')}, has_token={bool(self.get_user_token(user_id))}"
        )

        # בדוק אם יש ריפו נבחר
        if session.get("selected_repo"):
            # אם יש ריפו נבחר, הצע לנתח אותו או לבחור אחר
            keyboard = [
                [
                    InlineKeyboardButton(
                        f"📊 נתח את {session['selected_repo']}",
                        callback_data="analyze_current_repo",
                    )
                ],
                [InlineKeyboardButton("🔍 נתח ריפו אחר", callback_data="analyze_other_repo")],
                [InlineKeyboardButton("🔙 חזור לתפריט", callback_data="github_menu")],
            ]

            await query.edit_message_text(
                "🔍 <b>ניתוח ריפוזיטורי</b>\n\n" "בחר אפשרות:",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="HTML",
            )
        else:
            # אם אין ריפו נבחר, בקש URL
            await self.request_repo_url(update, context)

    async def request_repo_url(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """מבקש URL של ריפו לניתוח"""
        logger.info("📝 Requesting repository URL from user")
        query = update.callback_query if update.callback_query else None

        keyboard = [[InlineKeyboardButton("❌ ביטול", callback_data="github_menu")]]

        message_text = (
            "🔍 <b>ניתוח ריפוזיטורי</b>\n\n"
            "שלח URL של ריפו ציבורי ב-GitHub:\n"
            "לדוגמה: <code>https://github.com/owner/repo</code>\n\n"
            "💡 הריפו חייב להיות ציבורי או שיש לך גישה אליו עם הטוקן"
        )

        if query:
            await query.edit_message_text(
                message_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML"
            )
        else:
            await update.message.reply_text(
                message_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML"
            )

        # סמן שאנחנו מחכים ל-URL
        context.user_data["waiting_for_repo_url"] = True

    async def analyze_another_repo(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """מציג תפריט בחירה לניתוח ריפו אחר"""
        query = update.callback_query
        await query.answer()

        # הצג כפתורים לבחירה
        keyboard = [
            [InlineKeyboardButton("📁 בחר מהריפוזיטורים שלי", callback_data="choose_my_repo")],
            [InlineKeyboardButton("🔗 הכנס URL של ריפו ציבורי", callback_data="enter_repo_url")],
            [InlineKeyboardButton("🔙 חזור", callback_data="back_to_analysis_menu")],
        ]

        await query.edit_message_text(
            "איך תרצה לבחור ריפו לניתוח?", reply_markup=InlineKeyboardMarkup(keyboard)
        )

    async def analyze_repository(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, repo_url: str
    ):
        """מנתח ריפוזיטורי ומציג תוצאות"""
        logger.info(f"🎯 Starting repository analysis for URL: {repo_url}")
        query = update.callback_query if update.callback_query else None
        user_id = update.effective_user.id
        session = self.get_user_session(user_id)
        logger.info(f"👤 User {user_id} analyzing repo: {repo_url}")

        # הצג הודעת המתנה
        status_message = await self._send_or_edit_message(
            update, "🔍 מנתח את הריפו...\nזה עשוי לקחת מספר שניות..."
        )

        try:
            # צור מנתח עם הטוקן
            analyzer = RepoAnalyzer(github_token=self.get_user_token(user_id))

            # נתח את הריפו
            analysis = await analyzer.fetch_and_analyze_repo(repo_url)

            # שמור את הניתוח ב-session
            session["last_analysis"] = analysis
            session["last_analyzed_repo"] = repo_url

            # צור סיכום
            summary = self._create_analysis_summary(analysis)

            # צור כפתורים
            keyboard = [
                [InlineKeyboardButton("🎯 הצג הצעות לשיפור", callback_data="show_suggestions")],
                [InlineKeyboardButton("📥 הורד דוח JSON", callback_data="download_analysis_json")],
                [InlineKeyboardButton("🔍 נתח ריפו אחר", callback_data="analyze_other_repo")],
                [InlineKeyboardButton("🔙 חזור לתפריט", callback_data="github_menu")],
            ]

            # עדכן את ההודעה עם התוצאות
            await status_message.edit_text(
                summary, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML"
            )

        except Exception as e:
            logger.error(f"Error analyzing repository: {e}")
            error_message = f"❌ שגיאה בניתוח הריפו:\n{str(e)}"

            keyboard = [
                [InlineKeyboardButton("🔍 נסה ריפו אחר", callback_data="analyze_other_repo")],
                [InlineKeyboardButton("🔙 חזור לתפריט", callback_data="github_menu")],
            ]

            await status_message.edit_text(
                error_message, reply_markup=InlineKeyboardMarkup(keyboard)
            )
    def _create_analysis_summary(self, analysis: Dict[str, Any]) -> str:
        """יוצר סיכום של הניתוח"""
        # Escape HTML special characters
        repo_name = safe_html_escape(analysis["repo_name"])
        language = (
            safe_html_escape(analysis.get("language", "")) if analysis.get("language") else None
        )

        summary = f"📊 <b>ניתוח הריפו {repo_name}</b>\n\n"

        # סטטוס קבצים בסיסיים
        summary += "<b>קבצים בסיסיים:</b>\n"
        summary += "✅ README\n" if analysis["has_readme"] else "❌ חסר README\n"
        summary += "✅ LICENSE\n" if analysis["has_license"] else "❌ חסר LICENSE\n"
        summary += "✅ .gitignore\n" if analysis["has_gitignore"] else "❌ חסר .gitignore\n"

        # מידע על הפרויקט
        summary += f"\n<b>מידע כללי:</b>\n"
        if language:
            summary += f"🔤 שפה עיקרית: {language}\n"
        summary += f"📁 {analysis['file_count']} קבצי קוד\n"

        # קבצים לפי סוג
        if analysis["files_by_type"]:
            top_types = sorted(analysis["files_by_type"].items(), key=lambda x: x[1], reverse=True)[
                :3
            ]
            for ext, count in top_types:
                ext_escaped = safe_html_escape(ext)
                summary += f"   • {count} קבצי {ext_escaped}\n"

        # תלויות
        if analysis["dependencies"]:
            summary += f"📦 {len(analysis['dependencies'])} תלויות\n"

        # בעיות פוטנציאליות
        if analysis["large_files"]:
            summary += f"⚠️ {len(analysis['large_files'])} קבצים גדולים\n"
        if analysis["long_functions"]:
            summary += f"⚠️ {len(analysis['long_functions'])} פונקציות ארוכות\n"

        # ציון איכות
        quality_score = analysis.get("quality_score", 0)
        if quality_score >= 80:
            emoji = "🌟"
            text = "מצוין"
        elif quality_score >= 60:
            emoji = "✨"
            text = "טוב"
        elif quality_score >= 40:
            emoji = "⭐"
            text = "בינוני"
        else:
            emoji = "💫"
            text = "דורש שיפור"

        summary += f"\n<b>ציון איכות: {emoji} {quality_score}/100 ({text})</b>"

        return summary

    async def show_improvement_suggestions(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """מציג הצעות לשיפור"""
        query = update.callback_query
        await query.answer()

        user_id = query.from_user.id
        session = self.get_user_session(user_id)

        if not session.get("last_analysis"):
            await query.edit_message_text(
                "❌ לא נמצא ניתוח. נתח ריפו קודם.",
                reply_markup=InlineKeyboardMarkup(
                    [
                        [InlineKeyboardButton("🔍 נתח ריפו", callback_data="analyze_repo")],
                        [InlineKeyboardButton("🔙 חזור לתפריט", callback_data="github_menu")],
                    ]
                ),
            )
            return

        # צור הצעות לשיפור
        analyzer = RepoAnalyzer()
        suggestions = analyzer.generate_improvement_suggestions(session["last_analysis"])

        if not suggestions:
            await query.edit_message_text(
                "🎉 מעולה! לא נמצאו הצעות לשיפור משמעותיות.\n" "הפרויקט נראה מצוין!",
                reply_markup=InlineKeyboardMarkup(
                    [
                        [InlineKeyboardButton("🔙 חזור לסיכום", callback_data="back_to_analysis")],
                        [InlineKeyboardButton("🏠 תפריט ראשי", callback_data="github_menu")],
                    ]
                ),
            )
            return

        # שמור הצעות ב-session
        session["suggestions"] = suggestions

        # צור כפתורים להצעות (מקסימום 8 הצעות)
        keyboard = []
        for i, suggestion in enumerate(suggestions[:8]):
            impact_emoji = (
                "🔴"
                if suggestion["impact"] == "high"
                else "🟡" if suggestion["impact"] == "medium" else "🟢"
            )
            button_text = f"{impact_emoji} {suggestion['title']}"
            keyboard.append([InlineKeyboardButton(button_text, callback_data=f"suggestion_{i}")])

        keyboard.append([InlineKeyboardButton("🔙 חזור לסיכום", callback_data="back_to_analysis")])

        # Escape HTML special characters
        repo_name = safe_html_escape(session["last_analysis"]["repo_name"])

        message = f"💡 <b>הצעות לשיפור לריפו {repo_name}</b>\n\n"
        message += f"נמצאו {len(suggestions)} הצעות לשיפור.\n"
        message += "בחר הצעה לפרטים נוספים:\n\n"
        message += "🔴 = השפעה גבוהה | 🟡 = בינונית | 🟢 = נמוכה"

        await query.edit_message_text(
            message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML"
        )

    async def show_suggestion_details(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, suggestion_index: int
    ):
        """מציג פרטי הצעה ספציפית"""
        query = update.callback_query
        await query.answer()

        try:
            user_id = query.from_user.id
            session = self.get_user_session(user_id)

            suggestions = session.get("suggestions", [])
            if suggestion_index >= len(suggestions):
                await query.answer("❌ הצעה לא נמצאה", show_alert=True)
                return

            suggestion = suggestions[suggestion_index]

            # מיפוי השפעה ומאמץ לעברית
            impact_map = {"high": "גבוהה", "medium": "בינונית", "low": "נמוכה"}
            effort_map = {"high": "גבוה", "medium": "בינוני", "low": "נמוך"}

            # Use safe HTML escaping to prevent parsing errors
            title = safe_html_escape(suggestion.get("title", "הצעה"))
            why = safe_html_escape(suggestion.get("why", "לא צוין"))
            how = safe_html_escape(suggestion.get("how", "לא צוין"))
            impact = safe_html_escape(impact_map.get(suggestion.get("impact", "medium"), "בינונית"))
            effort = safe_html_escape(effort_map.get(suggestion.get("effort", "medium"), "בינוני"))

            # בנה הודעה בטוחה
            message = f"<b>{title}</b>\n\n"
            message += f"❓ <b>למה:</b> {why}\n\n"
            message += f"💡 <b>איך:</b> {how}\n\n"
            message += f"📊 <b>השפעה:</b> {impact}\n"
            message += f"⚡ <b>מאמץ:</b> {effort}\n"

            keyboard = []

            # הוסף כפתור למידע נוסף בהתאם לקטגוריה
            suggestion_id = suggestion.get("id", "")
            if suggestion_id == "add_license":
                keyboard.append(
                    [InlineKeyboardButton("📚 מידע על רישיונות", url="https://choosealicense.com/")]
                )
            elif suggestion_id == "add_gitignore":
                keyboard.append(
                    [InlineKeyboardButton("📚 יצירת .gitignore", url="https://gitignore.io/")]
                )
            elif suggestion_id == "add_ci_cd":
                keyboard.append(
                    [
                        InlineKeyboardButton(
                            "📚 GitHub Actions", url="https://docs.github.com/en/actions"
                        )
                    ]
                )

            keyboard.append(
                [InlineKeyboardButton("🔙 חזור להצעות", callback_data="show_suggestions")]
            )

            await query.edit_message_text(
                message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML"
            )

        except Exception as e:
            logger.error(f"Error in show_suggestion_details: {e}")
            # Fallback to simple text without HTML
            try:
                simple_text = f"הצעה #{suggestion_index + 1}\n\n"
                if "suggestion" in locals():
                    simple_text += f"{suggestion.get('title', 'הצעה')}\n\n"
                    simple_text += f"למה: {suggestion.get('why', 'לא צוין')}\n"
                    simple_text += f"איך: {suggestion.get('how', 'לא צוין')}\n"
                else:
                    simple_text += "לא ניתן להציג את פרטי ההצעה"

                await query.edit_message_text(
                    simple_text,
                    reply_markup=InlineKeyboardMarkup(
                        [[InlineKeyboardButton("🔙 חזור", callback_data="show_suggestions")]]
                    ),
                )
            except Exception as fallback_error:
                logger.error(f"Fallback also failed: {fallback_error}")
                await query.answer("❌ שגיאה בהצגת ההצעה", show_alert=True)

    async def show_full_analysis(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """מציג ניתוח מלא"""
        query = update.callback_query
        await query.answer()

        user_id = query.from_user.id
        session = self.get_user_session(user_id)

        analysis = session.get("last_analysis")
        if not analysis:
            await query.answer("❌ לא נמצא ניתוח", show_alert=True)
            return

        # צור דוח מפורט - Escape HTML special characters
        repo_name = safe_html_escape(analysis["repo_name"])
        repo_url = safe_html_escape(analysis["repo_url"])
        description = (
            safe_html_escape(analysis.get("description", ""))
            if analysis.get("description")
            else None
        )
        language = safe_html_escape(analysis.get("language", "לא זוהתה"))

        report = f"📊 <b>דוח מלא - {repo_name}</b>\n\n"

        # מידע בסיסי
        report += "<b>📌 מידע כללי:</b>\n"
        report += f"• URL: {repo_url}\n"
        if description:
            report += f"• תיאור: {description}\n"
        report += f"• שפה: {language}\n"
        report += f"• כוכבים: ⭐ {analysis.get('stars', 0)}\n"
        report += f"• Forks: 🍴 {analysis.get('forks', 0)}\n"

        # קבצים
        report += f"\n<b>📁 קבצים:</b>\n"
        report += f"• סה״כ קבצי קוד: {analysis['file_count']}\n"
        if analysis["files_by_type"]:
            report += "• לפי סוג:\n"
            for ext, count in sorted(
                analysis["files_by_type"].items(), key=lambda x: x[1], reverse=True
            ):
                report += f"  - {ext}: {count}\n"

        # בעיות
        if analysis["large_files"] or analysis["long_functions"]:
            report += f"\n<b>⚠️ בעיות פוטנציאליות:</b>\n"
            if analysis["large_files"]:
                report += f"• {len(analysis['large_files'])} קבצים גדולים (500+ שורות)\n"
            if analysis["long_functions"]:
                report += f"• {len(analysis['long_functions'])} פונקציות ארוכות (50+ שורות)\n"

        # תלויות
        if analysis["dependencies"]:
            report += f"\n<b>📦 תלויות ({len(analysis['dependencies'])}):</b>\n"
            # הצג רק 10 הראשונות
            for dep in analysis["dependencies"][:10]:
                dep_name = safe_html_escape(dep["name"])
                dep_type = safe_html_escape(dep["type"])
                report += f"• {dep_name} ({dep_type})\n"
            if len(analysis["dependencies"]) > 10:
                report += f"• ... ועוד {len(analysis['dependencies']) - 10}\n"

        keyboard = [
            [InlineKeyboardButton("🔙 חזור לסיכום", callback_data="back_to_analysis")],
            [InlineKeyboardButton("🏠 תפריט ראשי", callback_data="github_menu")],
        ]

        # חלק את ההודעה אם היא ארוכה מדי
        if len(report) > 4000:
            report = report[:3900] + "\n\n... (קוצר לצורך תצוגה)"

        await query.edit_message_text(
            report, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML"
        )

    async def download_analysis_json(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """שולח קובץ JSON עם הניתוח המלא"""
        query = update.callback_query
        await query.answer()

        user_id = query.from_user.id
        session = self.get_user_session(user_id)

        analysis = session.get("last_analysis")
        if not analysis:
            await query.answer("❌ לא נמצא ניתוח", show_alert=True)
            return

        # הוסף גם את ההצעות לדוח
        analyzer = RepoAnalyzer()
        suggestions = analyzer.generate_improvement_suggestions(analysis)

        full_report = {
            "analysis": analysis,
            "suggestions": suggestions,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

        # צור קובץ JSON
        json_content = json.dumps(full_report, ensure_ascii=False, indent=2)

        # שלח כקובץ
        import io

        file = io.BytesIO(json_content.encode("utf-8"))
        file.name = f"repo_analysis_{analysis['repo_name']}.json"

        await query.message.reply_document(
            document=file,
            filename=file.name,
            caption=f"📊 דוח ניתוח מלא עבור {analysis['repo_name']}",
        )

        # חזור לתפריט
        await self.show_analyze_results_menu(update, context)

    async def show_analyze_results_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """מציג מחדש את תפריט התוצאות"""
        user_id = update.effective_user.id
        session = self.get_user_session(user_id)

        analysis = session.get("last_analysis")
        if not analysis:
            return

        summary = self._create_analysis_summary(analysis)

        keyboard = [
            [InlineKeyboardButton("🎯 הצג הצעות לשיפור", callback_data="show_suggestions")],
            [InlineKeyboardButton("📥 הורד דוח JSON", callback_data="download_analysis_json")],
            [InlineKeyboardButton("🔍 נתח ריפו אחר", callback_data="analyze_other_repo")],
            [InlineKeyboardButton("🔙 חזור לתפריט", callback_data="github_menu")],
        ]

        if update.callback_query:
            await update.callback_query.edit_message_text(
                summary, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML"
            )
        else:
            await update.message.reply_text(
                summary, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML"
            )

    async def _send_or_edit_message(self, update: Update, text: str, **kwargs):
        """שולח או עורך הודעה בהתאם לסוג ה-update"""
        if update.callback_query:
            return await update.callback_query.edit_message_text(text, **kwargs)
        else:
            return await update.message.reply_text(text, **kwargs)

    async def handle_repo_url_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """מטפל בקלט של URL לניתוח"""
        logger.info(
            f"🔗 Handling repo URL input: waiting={context.user_data.get('waiting_for_repo_url')}"
        )
        if not context.user_data.get("waiting_for_repo_url"):
            return False

        text = update.message.text
        logger.info(f"📌 Received URL: {text}")
        context.user_data["waiting_for_repo_url"] = False

        # בדוק אם זה URL של GitHub
        if "github.com" not in text:
            await update.message.reply_text(
                "❌ נא לשלוח URL תקין של GitHub\n" "לדוגמה: https://github.com/owner/repo",
                reply_markup=InlineKeyboardMarkup(
                    [
                        [InlineKeyboardButton("🔍 נסה שוב", callback_data="analyze_other_repo")],
                        [InlineKeyboardButton("🔙 חזור לתפריט", callback_data="github_menu")],
                    ]
                ),
            )
            return True

        # נתח את הריפו
        await self.analyze_repository(update, context, text)
        return True

    async def show_delete_file_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """מציג תפריט מחיקת קובץ מהריפו (דפדוף בכפתורים)"""
        query = update.callback_query
        session = self.get_user_session(query.from_user.id)
        repo = session.get("selected_repo")
        if not repo:
            await query.edit_message_text("❌ לא נבחר ריפו")
            return
        context.user_data["browse_action"] = "delete"
        context.user_data["browse_path"] = ""
        context.user_data["browse_page"] = 0
        # מצב מרובה ומחיקה בטוחה לאיפוס
        context.user_data["multi_mode"] = False
        context.user_data["multi_selection"] = []
        context.user_data["safe_delete"] = True
        await self.show_repo_browser(update, context)

    async def show_delete_repo_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """מציג תפריט מחיקת ריפו שלם עם אזהרות"""
        query = update.callback_query
        session = self.get_user_session(query.from_user.id)
        repo = session.get("selected_repo")
        if not repo:
            await query.edit_message_text("❌ לא נבחר ריפו")
            return
        keyboard = [
            [
                InlineKeyboardButton(
                    "✅ אני מבין/ה ומאשר/ת מחיקה", callback_data="confirm_delete_repo_step1"
                )
            ],
            [InlineKeyboardButton("🔙 חזור", callback_data="github_menu")],
        ]
        await query.edit_message_text(
            "⚠️ מחיקת ריפו שלם הינה פעולה בלתי הפיכה!\n\n"
            "- יימחקו כל הקבצים, ה-Issues, ה-PRs וה-Settings\n"
            "- לא ניתן לשחזר לאחר המחיקה\n\n"
            f"ריפו למחיקה: <code>{repo}</code>\n\n"
            "אם ברצונך להמשיך, לחץ על האישור ואז תתבקש לאשר שוב.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML",
        )

    async def confirm_delete_file(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """מבצע מחיקת קובץ לאחר אישור"""
        query = update.callback_query
        user_id = query.from_user.id
        session = self.get_user_session(user_id)
        token = self.get_user_token(user_id)
        repo_name = session.get("selected_repo")
        file_path = context.user_data.get("pending_delete_file_path")
        if not (token and repo_name and file_path):
            await query.edit_message_text("❌ נתונים חסרים למחיקה")
            return
        try:
            g = Github(token)
            repo = g.get_repo(repo_name)
            # בדוק אם הקובץ קיים וקבל sha לצורך מחיקה
            contents = repo.get_contents(file_path)
            default_branch = repo.default_branch or "main"
            repo.delete_file(
                contents.path, f"Delete via bot: {file_path}", contents.sha, branch=default_branch
            )
            await query.edit_message_text(
                f"✅ הקובץ נמחק בהצלחה: <code>{file_path}</code>", parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Error deleting file: {e}")
            await query.edit_message_text(f"❌ שגיאה במחיקת קובץ: {e}")
        finally:
            context.user_data.pop("pending_delete_file_path", None)
            await self.github_menu_command(update, context)

    async def confirm_delete_repo_step1(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """מסך אישור סופי לפני מחיקת ריפו, מפנה ללחצן מחיקה סופי"""
        query = update.callback_query
        session = self.get_user_session(query.from_user.id)
        repo = session.get("selected_repo")
        if not repo:
            await query.edit_message_text("❌ לא נבחר ריפו")
            return
        keyboard = [
            [InlineKeyboardButton("🧨 כן, מחק לצמיתות", callback_data="confirm_delete_repo")],
            [InlineKeyboardButton("🔙 ביטול", callback_data="github_menu")],
        ]
        await query.edit_message_text(
            f"⚠️ אישור סופי למחיקת <code>{repo}</code>\n\n"
            "פעולה זו תמחק לצמיתות את הריפו וכל התוכן המשויך אליו.\n"
            "אין דרך לשחזר לאחר מכן.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML",
        )

    async def confirm_delete_repo(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """מבצע מחיקת ריפו שלם לאחר אישור"""
        query = update.callback_query
        user_id = query.from_user.id
        session = self.get_user_session(user_id)
        token = self.get_user_token(user_id)
        repo_name = session.get("selected_repo")
        if not (token and repo_name):
            await query.edit_message_text("❌ נתונים חסרים למחיקה")
            return
        try:
            g = Github(token)
            repo = g.get_repo(repo_name)
            owner = g.get_user()
            # ודא שלמשתמש יש הרשאה למחוק
            if repo.owner.login != owner.login:
                await query.edit_message_text("❌ ניתן למחוק רק ריפו שאתה בעליו")
                return
            repo.delete()
            # נקה קאש ריפוזיטוריז כדי שהרשימה תרוענן ולא תציג פריטים שנמחקו
            context.user_data.pop("repos", None)
            context.user_data.pop("repos_cache_time", None)
            await query.edit_message_text(
                f"✅ הריפו נמחק בהצלחה: <code>{repo_name}</code>", parse_mode="HTML"
            )
            # נקה בחירה לאחר מחיקה
            session["selected_repo"] = None
        except Exception as e:
            logger.error(f"Error deleting repository: {e}")
            await query.edit_message_text(f"❌ שגיאה במחיקת ריפו: {e}")
        finally:
            # לאחר מחיקה, ודא שקאש הרשימות אינו משאיר את הריפו הישן
            context.user_data.pop("repos", None)
            context.user_data.pop("repos_cache_time", None)
            await self.github_menu_command(update, context)

    async def show_danger_delete_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """מציג תפריט מחיקות מסוכן"""
        query = update.callback_query
        session = self.get_user_session(query.from_user.id)
        repo = session.get("selected_repo")
        if not repo:
            await query.edit_message_text("❌ לא נבחר ריפו")
            return
        keyboard = [
            [InlineKeyboardButton("🗑️ מחק קובץ מהריפו", callback_data="delete_file_menu")],
            [InlineKeyboardButton("⚠️ מחק ריפו שלם (מתקדם)", callback_data="delete_repo_menu")],
            [InlineKeyboardButton("🔙 חזור", callback_data="github_menu")],
        ]
        await query.edit_message_text(
            f"🧨 פעולות מחיקה ב-<code>{repo}</code>\n\nבחר פעולה:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML",
        )

    async def show_download_file_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """מציג תפריט הורדת קובץ מהריפו (דפדוף בכפתורים)"""
        query = update.callback_query
        session = self.get_user_session(query.from_user.id)
        repo = session.get("selected_repo")
        if not repo:
            await query.edit_message_text("❌ לא נבחר ריפו")
            return
        # התחל בדפדוף מה-root במצב הורדה בלבד
        context.user_data["browse_action"] = "download"
        context.user_data["browse_path"] = ""
        context.user_data["browse_page"] = 0
        # אפס מצב מחיקה אם הופעל קודם
        context.user_data["multi_mode"] = False
        context.user_data["multi_selection"] = []
        context.user_data["safe_delete"] = True
        await self.show_repo_browser(update, context)
    async def show_repo_browser(self, update: Update, context: ContextTypes.DEFAULT_TYPE, only_keyboard: bool = False):
        """מציג דפדפן ריפו לפי נתיב ושימוש (view/download/delete), כולל breadcrumbs ועימוד."""
        query = update.callback_query
        user_id = query.from_user.id
        session = self.get_user_session(user_id)
        token = self.get_user_token(user_id)
        repo_name = session.get("selected_repo")
        if not (token and repo_name):
            await query.edit_message_text("❌ חסרים נתונים")
            return
        g = Github(token)
        repo = g.get_repo(repo_name)
        path = context.user_data.get("browse_path", "")
        # קביעת ref נוכחי לניווט (ענף/תג)
        try:
            current_ref = context.user_data.get("browse_ref") or (getattr(repo, "default_branch", None) or "main")
        except Exception:
            current_ref = getattr(repo, "default_branch", None) or "main"
        # קבלת תוכן התיקייה
        try:
            contents = repo.get_contents(path or "", ref=current_ref)
        except Exception:
            contents = repo.get_contents(path or "")
        if not isinstance(contents, list):
            # אם זה קובץ יחיד, הפוך לרשימה לצורך תצוגה
            contents = [contents]
        # בניית פריטים (תיקיות קודם, אחר כך קבצים)
        folders = [c for c in contents if c.type == "dir"]
        files = [c for c in contents if c.type == "file"]
        # במצב בחירת תיקייה, לא נציג קבצים כלל
        folder_selecting = bool(context.user_data.get("folder_select_mode"))
        entry_rows = []
        # Breadcrumbs
        crumbs_row = []
        crumbs_row.append(InlineKeyboardButton("🏠 root", callback_data=self._mk_cb(context, "browse_open", "")))
        if path:
            parts = path.split("/")
            accum = []
            for part in parts:
                accum.append(part)
                crumbs_row.append(InlineKeyboardButton(part, callback_data=self._mk_cb(context, "browse_open", '/'.join(accum))))
        if crumbs_row:
            entry_rows.append(crumbs_row)
        # שורת כלים: חיפוש ובחירת ref
        tools_row = [
            InlineKeyboardButton("🔎 חפש בשם קובץ", callback_data="browse_search"),
            InlineKeyboardButton(f"🌿 ref: {current_ref}", callback_data="browse_ref_menu"),
        ]
        entry_rows.append(tools_row)
        for folder in folders:
            # תמיד מציגים פתיחת תיקייה; אין צורך בכפתור "בחר כיעד" (הוסרה דרישתך)
            row = [InlineKeyboardButton(
                f"📂 {folder.name}", callback_data=self._mk_cb(context, "browse_open", folder.path)
            )]
            entry_rows.append(row)
        multi_mode = context.user_data.get("multi_mode", False)
        selection = set(context.user_data.get("multi_selection", []))
        if not folder_selecting:
            for f in files:
                if multi_mode:
                    checked = "☑️" if f.path in selection else "⬜️"
                    entry_rows.append(
                        [
                            InlineKeyboardButton(
                                f"{checked} {f.name}", callback_data=f"browse_toggle_select:{f.path}"
                            )
                        ]
                    )
                else:
                    mode = context.user_data.get("browse_action")
                    if mode == "download":
                        size_val = getattr(f, "size", 0) or 0
                        large_flag = " ⚠️" if size_val and size_val > MAX_INLINE_FILE_BYTES else ""
                        entry_rows.append(
                            [
                                InlineKeyboardButton(
                                    f"⬇️ {f.name}{large_flag}",
                                    callback_data=self._mk_cb(context, "browse_select_download", f.path),
                                )
                            ]
                        )
                    elif mode == "view":
                        # הסר כפתור "שתף קישור" מרשימה; נשאיר רק במסך התצוגה
                        entry_rows.append(
                            [
                                InlineKeyboardButton(
                                    f"👁️ {f.name}", callback_data=self._mk_cb(context, "browse_select_view", f.path)
                                )
                            ]
                        )
                    else:
                        # במצב שאינו download ואינו view — זה מצב delete בלבד
                        entry_rows.append(
                            [
                                InlineKeyboardButton(
                                    f"🗑️ {f.name}", callback_data=self._mk_cb(context, "browse_select_delete", f.path)
                                )
                            ]
                        )
        # ודא דגלים ברירת מחדל כדי למנוע שגיאות בניווט
        if context.user_data.get("browse_page") is None:
            context.user_data["browse_page"] = 0
        if context.user_data.get("multi_mode") is None:
            context.user_data["multi_mode"] = False
        # עימוד
        page_size = 10
        # ודא ששורת הכלים (חיפוש/בחירת ref) תמיד נשמרת בראש כל עמוד
        # נבנה את המטריצה כך שהשורה הראשונה תהיה תמיד הכלים, ולא תיספר לעימוד
        # מצא אינדקס תחילת הפריטים לעימוד אחרי breadcrumbs ושורת כלים
        # breadcrumbs נמצאת ב-entry_rows[0] (אם קיימת), ושורת כלים ב-entry_rows[1]
        start_items_index = 0
        if entry_rows:
            # אם יש breadcrumbs, הם באינדקס 0
            start_items_index = 1
            # אם יש גם שורת כלים, היא באינדקס 1
            if len(entry_rows) > 1 and any(
                isinstance(btn, InlineKeyboardButton) and getattr(btn, 'callback_data', '') == 'browse_search'
                for btn in entry_rows[1]
            ):
                start_items_index = 2
        paginable_rows = entry_rows[start_items_index:]
        total_items = len(paginable_rows)
        total_pages = max(1, (total_items + page_size - 1) // page_size)
        current_page = min(max(0, context.user_data.get("browse_page", 0)), total_pages - 1)
        start_index = current_page * page_size
        end_index = start_index + page_size
        # בנה מקלדת: breadcrumbs (אם קיימת) + שורת כלים + פריטי העמוד
        keyboard = []
        if entry_rows and start_items_index >= 1:
            keyboard.append(entry_rows[0])  # breadcrumbs
        if entry_rows and start_items_index >= 2:
            keyboard.append(entry_rows[1])  # tools row (כולל חיפוש)
        keyboard.extend(paginable_rows[start_index:end_index])
        # ניווט עמודים
        if total_pages > 1:
            nav_row = []
            if current_page > 0:
                nav_row.append(
                    InlineKeyboardButton("⬅️ הקודם", callback_data=f"browse_page:{current_page - 1}")
                )
            nav_row.append(
                InlineKeyboardButton(f"עמוד {current_page + 1}/{total_pages}", callback_data="noop")
            )
            if current_page < total_pages - 1:
                nav_row.append(
                    InlineKeyboardButton("הבא ➡️", callback_data=f"browse_page:{current_page + 1}")
                )
            keyboard.append(nav_row)
        # שורה תחתונה
        bottom = []
        if path:
            # חזרה למעלה
            parent = "/".join(path.split("/")[:-1])
            bottom.append(InlineKeyboardButton("⬆️ למעלה", callback_data=self._mk_cb(context, "browse_open", parent)))
        # כפתור חזרה/סיום לבחירת תיקייה
        if context.user_data.get("folder_select_mode") == "session":
            bottom.append(InlineKeyboardButton("✅ סיום בחירה", callback_data="folder_select_done"))
            bottom.append(InlineKeyboardButton("🔙 ביטול", callback_data="github_menu"))
            # הוסף כפתור יצירת תיקייה חדשה במצב בחירת תיקייה
            keyboard.append([InlineKeyboardButton("➕ צור תיקייה חדשה", callback_data="create_folder")])
        # סדר כפתורים לשורות כדי למנוע צפיפות
        row = []
        if (not folder_selecting) and context.user_data.get("browse_action") == "download":
            row.append(InlineKeyboardButton("📦 הורד תיקייה כ־ZIP", callback_data=self._mk_cb(context, "download_zip", path or "")))
        if len(row) >= 1:
            keyboard.append(row)
        row = []
        if (not folder_selecting) and context.user_data.get("browse_action") == "download":
            row.append(InlineKeyboardButton("🔗 שתף קישור לתיקייה", callback_data=self._mk_cb(context, "share_folder_link", path or "")))
        if not folder_selecting:
            # במצב הורדה לא מציגים כלל כפתורי מחיקה/בחירה מרובה למחיקה
            if context.user_data.get("browse_action") == "download":
                if multi_mode:
                    keyboard.append(row)
                    row = []
                    row.append(InlineKeyboardButton("📦 הורד נבחרים כ־ZIP", callback_data="multi_execute"))
                    row.append(InlineKeyboardButton("🔗 שתף קישורים לנבחרים", callback_data="share_selected_links"))
                    keyboard.append(row)
                    row = [InlineKeyboardButton("♻️ נקה בחירה", callback_data="multi_clear"), InlineKeyboardButton("🚫 בטל מצב מרובה", callback_data="multi_toggle")]
                    keyboard.append(row)
                else:
                    row.append(InlineKeyboardButton("✅ בחר מרובים", callback_data="multi_toggle"))
                    keyboard.append(row)
            else:
                # מצב delete/view – התנהגות קיימת
                if not multi_mode:
                    row.append(InlineKeyboardButton("✅ בחר מרובים", callback_data="multi_toggle"))
                    keyboard.append(row)
                else:
                    keyboard.append(row)
                    row = []
                    safe_label = (
                        "מצב מחיקה בטוח: פעיל" if context.user_data.get("safe_delete", True) else "מצב מחיקה בטוח: כבוי"
                    )
                    row.append(InlineKeyboardButton(safe_label, callback_data="safe_toggle"))
                    keyboard.append(row)
                    row = [InlineKeyboardButton("🗑️ מחק נבחרים", callback_data="multi_execute"), InlineKeyboardButton("🔗 שתף קישורים לנבחרים", callback_data="share_selected_links")]
                    keyboard.append(row)
                    row = [InlineKeyboardButton("♻️ נקה בחירה", callback_data="multi_clear"), InlineKeyboardButton("🚫 בטל מצב מרובה", callback_data="multi_toggle")]
                    keyboard.append(row)
        keyboard.append([InlineKeyboardButton("🔙 חזרה", callback_data="github_menu")])
        if bottom:
            keyboard.append(bottom)
        # טקסט
        _mode = context.user_data.get("browse_action")
        action = "תצוגה" if _mode == "view" else ("הורדה" if _mode == "download" else "מחיקה")
        if only_keyboard:
            try:
                await TelegramUtils.safe_edit_message_reply_markup(query, reply_markup=InlineKeyboardMarkup(keyboard))
                return
            except Exception:
                pass
            if folder_selecting:
                await TelegramUtils.safe_edit_message_text(
                    query,
                    f"📁 דפדוף ריפו: <code>{repo_name}</code>\n"
                    f"🔀 ref: <code>{current_ref}</code>\n"
                    f"📂 נתיב: <code>/{path or ''}</code>\n\n"
                    f"בחר תיקייה יעד או פתח תיקייה (מציג {min(page_size, max(0, total_items - start_index))} מתוך {total_items}):",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode="HTML",
                )
            else:
                await TelegramUtils.safe_edit_message_text(
                    query,
                    f"📁 דפדוף ריפו: <code>{repo_name}</code>\n"
                    f"🔀 ref: <code>{current_ref}</code>\n"
                    f"📂 נתיב: <code>/{path or ''}</code>\n\n"
                    f"בחר קובץ ל{action} או פתח תיקייה (מציג {min(page_size, max(0, total_items - start_index))} מתוך {total_items}):",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode="HTML",
                )
        else:
            if folder_selecting:
                await query.edit_message_text(
                    f"📁 דפדוף ריפו: <code>{repo_name}</code>\n"
                    f"🔀 ref: <code>{current_ref}</code>\n"
                    f"📂 נתיב: <code>/{path or ''}</code>\n\n"
                    f"בחר תיקייה יעד או פתח תיקייה (מציג {min(page_size, max(0, total_items - start_index))} מתוך {total_items}):",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode="HTML",
                )
            else:
                try:
                    await query.edit_message_text(
                        f"📁 דפדוף ריפו: <code>{repo_name}</code>\n"
                        f"🔀 ref: <code>{current_ref}</code>\n"
                        f"📂 נתיב: <code>/{path or ''}</code>\n\n"
                        f"בחר קובץ ל{action} או פתח תיקייה (מציג {min(page_size, max(0, total_items - start_index))} מתוך {total_items}):",
                        reply_markup=InlineKeyboardMarkup(keyboard),
                        parse_mode="HTML",
                    )
                except BadRequest as br:
                    if "message is not modified" not in str(br).lower():
                        raise

    async def handle_inline_query(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Inline mode: חיפוש/ביצוע פעולות ישירות מכל צ'אט"""
        inline_query = update.inline_query
        user_id = inline_query.from_user.id
        session = self.get_user_session(user_id)
        token = self.get_user_token(user_id)
        repo_name = session.get("selected_repo")
        q = (inline_query.query or "").strip()
        results = []
        if not (token and repo_name):
            # בקש מהמשתמש לבחור ריפו
            results.append(
                InlineQueryResultArticle(
                    id=f"help-no-repo",
                    title="בחר/התחבר לריפו לפני שימוש באינליין",
                    description="שלח /github לבחירת ריפו ו/או התחברות",
                    input_message_content=InputTextMessageContent(
                        "🔧 שלח /github לבחירת ריפו ולהתחברות ל-GitHub"
                    ),
                )
            )
            await inline_query.answer(results, cache_time=1, is_personal=True)
            return
        g = Github(token)
        repo = g.get_repo(repo_name)
        # ללא קלט: אל תחזיר תוצאות (מבטל 'פקודות' אינליין מיותרות)
        if not q:
            await inline_query.answer([], cache_time=1, is_personal=True)
            return
        # פרסור פשוט: zip <path> / file <path> או נתיב ישיר
        is_zip = False
        is_file = False
        path = q
        if q.lower().startswith("zip "):
            # מבטלים תמיכת zip באינליין
            await inline_query.answer([], cache_time=1, is_personal=True)
            return
        elif q.lower().startswith("file "):
            is_file = True
            path = q[5:].strip()
        path = path.lstrip("/")
        try:
            contents = repo.get_contents(path)
            # תיקייה
            if isinstance(contents, list):
                # הצג כמה קבצים ראשונים בתיקייה להורדה מהירה (ללא הצעת ZIP)
                shown = 0
                for item in contents:
                    if getattr(item, "type", "") == "file":
                        size_str = format_bytes(getattr(item, "size", 0) or 0)
                        results.append(
                            InlineQueryResultArticle(
                                id=f"file-{item.path}",
                                title=f"⬇️ {item.name} ({size_str})",
                                description=f"/{item.path}",
                                input_message_content=InputTextMessageContent(
                                    f"קובץ: /{item.path}"
                                ),
                                reply_markup=InlineKeyboardMarkup(
                                    [
                                        [
                                            InlineKeyboardButton(
                                        "📩 הורד",
                                                callback_data=f"inline_download_file:{item.path}",
                                            )
                                        ]
                                    ]
                                ),
                            )
                        )
                        shown += 1
                        if shown >= 10:
                            break
            else:
                # קובץ בודד
                size_str = format_bytes(getattr(contents, "size", 0) or 0)
                # נסה להוציא snippet קצר מהתוכן (ללא עלות גבוהה מדי)
                snippet = ""
                try:
                    raw = contents.decoded_content or b""
                    text = raw.decode("utf-8", errors="replace")
                    # קח 3 שורות ראשונות/עד 180 תווים
                    first_lines = "\n".join(text.splitlines()[:3])
                    snippet = first_lines[:180].replace("\n", " ⏎ ")
                except Exception:
                    snippet = ""
                desc = snippet if snippet else f"/{path}"
                results.append(
                    InlineQueryResultArticle(
                        id=f"file-{path}",
                        title=f"⬇️ הורד: {os.path.basename(contents.path)} ({size_str})",
                        description=desc,
                        input_message_content=InputTextMessageContent(f"קובץ: /{path}"),
                        reply_markup=InlineKeyboardMarkup(
                            [
                                [
                                    InlineKeyboardButton(
                                        "📩 הורד", callback_data=f"inline_download_file:{path}"
                                    )
                                ]
                            ]
                        ),
                    )
                )
        except Exception:
            # החזר רק תוצאת קובץ אם נתבקשה מפורשות
            if is_file and path:
                results.append(
                    InlineQueryResultArticle(
                        id=f"file-maybe-{path}",
                        title=f"⬇️ קובץ: /{path}",
                        description="ניסיון הורדה לקובץ (אם קיים)",
                        input_message_content=InputTextMessageContent(f"קובץ: /{path}"),
                        reply_markup=InlineKeyboardMarkup(
                            [
                                [
                                    InlineKeyboardButton(
                                        "📩 הורד", callback_data=f"inline_download_file:{path}"
                                    )
                                ]
                            ]
                        ),
                    )
                )
            else:
                # בלי הודעות עזרה/דמה – נחזיר ריק
                pass
        await inline_query.answer(results[:50], cache_time=1, is_personal=True)

    async def show_notifications_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        user_id = query.from_user.id
        session = self.get_user_session(user_id)
        if not session.get("selected_repo"):
            await query.edit_message_text("❌ בחר ריפו קודם (/github)")
            return
        settings = context.user_data.get("notifications", {})
        enabled = settings.get("enabled", False)
        pr_on = settings.get("pr", True)
        issues_on = settings.get("issues", True)
        interval = settings.get("interval", 300)
        # הצגת מרווח זמן: אם פחות מדקה, הצג בשניות; אחרת בדקות (ללא המילה "תדירות")
        freq_display = f"{interval} שנ׳" if interval < 60 else f"{int(interval/60)} ד׳"
        keyboard = [
            [InlineKeyboardButton("🔙 חזור", callback_data="github_menu")],
            [
                InlineKeyboardButton(
                    "הפעל" if not enabled else "כבה", callback_data="notifications_toggle"
                )
            ],
            [
                InlineKeyboardButton(
                    f"PRs: {'פעיל' if pr_on else 'כבוי'}", callback_data="notifications_toggle_pr"
                )
            ],
            [
                InlineKeyboardButton(
                    f"Issues: {'פעיל' if issues_on else 'כבוי'}",
                    callback_data="notifications_toggle_issues",
                )
            ],
            [
                InlineKeyboardButton("30שנ׳", callback_data="notifications_interval_30"),
                InlineKeyboardButton("2ד׳", callback_data="notifications_interval_120"),
                InlineKeyboardButton("5ד׳", callback_data="notifications_interval_300"),
                InlineKeyboardButton("15ד׳", callback_data="notifications_interval_900"),
            ],
            [InlineKeyboardButton("בדוק עכשיו", callback_data="notifications_check_now")],
        ]
        text = (
            f"🔔 התראות לריפו: <code>{session['selected_repo']}</code>\n"
            f"מצב: {'פעיל' if enabled else 'כבוי'} | ⏱ {freq_display}\n"
            f"התראות = בדיקת PRs/Issues חדשים/שעודכנו ושיגור הודעה אליך."
        )
        try:
            await query.edit_message_text(
                text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML"
            )
        except BadRequest as e:
            # התעלם אם התוכן לא השתנה
            if "Message is not modified" not in str(e):
                raise

    async def toggle_notifications(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        user_id = query.from_user.id
        settings = context.user_data.setdefault(
            "notifications", {"enabled": False, "pr": True, "issues": True, "interval": 300}
        )
        settings["enabled"] = not settings.get("enabled", False)
        # ניהול job
        name = f"notif_{user_id}"
        jq = getattr(context, "job_queue", None) or getattr(context.application, "job_queue", None)
        if jq:
            for job in jq.get_jobs_by_name(name) or []:
                job.schedule_removal()
            if settings["enabled"]:
                jq.run_repeating(
                    self._notifications_job,
                    interval=settings.get("interval", 300),
                    first=5,
                    name=name,
                    data={"user_id": user_id},
                )
        else:
            await query.answer("אזהרה: JobQueue לא זמין — התראות לא ירוצו ברקע", show_alert=True)
        await self.show_notifications_menu(update, context)

    async def toggle_notifications_pr(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        settings = context.user_data.setdefault(
            "notifications", {"enabled": False, "pr": True, "issues": True, "interval": 300}
        )
        settings["pr"] = not settings.get("pr", True)
        await self.show_notifications_menu(update, context)

    async def toggle_notifications_issues(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        settings = context.user_data.setdefault(
            "notifications", {"enabled": False, "pr": True, "issues": True, "interval": 300}
        )
        settings["issues"] = not settings.get("issues", True)
        await self.show_notifications_menu(update, context)

    async def set_notifications_interval(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        user_id = query.from_user.id
        settings = context.user_data.setdefault(
            "notifications", {"enabled": False, "pr": True, "issues": True, "interval": 300}
        )
        try:
            interval = int(query.data.rsplit("_", 1)[1])
        except Exception:
            interval = 300
        settings["interval"] = interval
        # עדכן job אם קיים
        name = f"notif_{user_id}"
        jq = getattr(context, "job_queue", None) or getattr(context.application, "job_queue", None)
        if jq:
            for job in jq.get_jobs_by_name(name) or []:
                job.schedule_removal()
            if settings.get("enabled"):
                jq.run_repeating(
                    self._notifications_job,
                    interval=interval,
                    first=5,
                    name=name,
                    data={"user_id": user_id},
                )
        else:
            await query.answer("אזהרה: JobQueue לא זמין — התראות לא ירוצו ברקע", show_alert=True)
        await self.show_notifications_menu(update, context)

    async def notifications_check_now(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        try:
            await query.answer("בודק עכשיו...", show_alert=False)
        except Exception:
            pass
        await self._notifications_job(context, user_id=query.from_user.id, force=True)
        try:
            await self.show_notifications_menu(update, context)
        except BadRequest as e:
            if "Message is not modified" not in str(e):
                raise

    async def _notifications_job(
        self, context: ContextTypes.DEFAULT_TYPE, user_id: Optional[int] = None, force: bool = False
    ):
        try:
            if user_id is None:
                job = getattr(context, "job", None)
                if job and getattr(job, "data", None):
                    user_id = job.data.get("user_id")
            if not user_id:
                return
            session = self.get_user_session(user_id)
            token = self.get_user_token(user_id)
            repo_name = session.get("selected_repo")
            settings = (
                context.application.user_data.get(user_id, {}).get("notifications")
                if hasattr(context.application, "user_data")
                else None
            )
            if settings is None:
                settings = context.user_data.get("notifications", {})
            if not (token and repo_name):
                return
            if not force and not (settings and settings.get("enabled")):
                return
            g = Github(token)
            repo = g.get_repo(repo_name)
            # נהל זיכרון "נבדק לאחרונה"
            last = session.get("notifications_last", {"pr": None, "issues": None})
            messages = []
            # PRs
            if settings.get("pr", True):
                last_pr_check_time = last.get("pr")
                # If this is the first run (no baseline), set a baseline without sending backlog
                if last_pr_check_time is None:
                    session["notifications_last"] = session.get("notifications_last", {})
                    session["notifications_last"]["pr"] = datetime.now(timezone.utc)
                else:
                    pulls = repo.get_pulls(state="all", sort="updated", direction="desc")
                    for pr in pulls[:10]:
                        updated = self._to_utc_aware(getattr(pr, "updated_at", None))
                        # Normalize baseline too (safety in case it was saved naive somehow)
                        baseline = self._to_utc_aware(last_pr_check_time)
                        # אם אין updated או שאין אפשרות השוואה — עצור כדי למנוע עיבוד יתר של פריטים ישנים
                        if baseline and (updated is None or updated <= baseline):
                            break
                        created = self._to_utc_aware(getattr(pr, "created_at", None))
                        status = (
                            "נפתח"
                            if (pr.state == "open" and created and updated and created == updated)
                            else ("מוזג" if getattr(pr, "merged", False) else ("נסגר" if pr.state == "closed" else "עודכן"))
                        )
                        messages.append(
                            f'🔔 PR {status}: <a href="{pr.html_url}">{safe_html_escape(pr.title)}</a>'
                        )
                    session["notifications_last"] = session.get("notifications_last", {})
                    session["notifications_last"]["pr"] = datetime.now(timezone.utc)
            # Issues
            if settings.get("issues", True):
                last_issues_check_time = last.get("issues")
                if last_issues_check_time is None:
                    session["notifications_last"] = session.get("notifications_last", {})
                    session["notifications_last"]["issues"] = datetime.now(timezone.utc)
                else:
                    issues = repo.get_issues(state="all", sort="updated", direction="desc")
                    count = 0
                    for issue in issues:
                        if issue.pull_request is not None:
                            continue
                        updated = self._to_utc_aware(getattr(issue, "updated_at", None))
                        baseline = self._to_utc_aware(last_issues_check_time)
                        # אם אין updated או שאין אפשרות השוואה — עצור כדי למנוע עיבוד יתר של פריטים ישנים
                        if baseline and (updated is None or updated <= baseline):
                            break
                        created = self._to_utc_aware(getattr(issue, "created_at", None))
                        status = (
                            "נפתח"
                            if (issue.state == "open" and created and updated and created == updated)
                            else ("נסגר" if issue.state == "closed" else "עודכן")
                        )
                        messages.append(
                            f'🔔 Issue {status}: <a href="{issue.html_url}">{safe_html_escape(issue.title)}</a>'
                        )
                        count += 1
                        if count >= 10:
                            break
                    session["notifications_last"] = session.get("notifications_last", {})
                    session["notifications_last"]["issues"] = datetime.now(timezone.utc)
            # שלח הודעה אם יש
            if messages:
                text = "\n".join(messages)
                await context.bot.send_message(
                    chat_id=user_id, text=text, parse_mode="HTML", disable_web_page_preview=True
                )
        except Exception as e:
            logger.error(f"notifications job error: {e}")

    async def show_pr_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        user_id = query.from_user.id
        session = self.get_user_session(user_id)
        if not session.get("selected_repo"):
            await query.edit_message_text("❌ בחר ריפו קודם (/github)")
            return
        keyboard = [
            [InlineKeyboardButton("🆕 צור PR מסניף", callback_data="create_pr_menu")],
            [InlineKeyboardButton("🔀 מזג PR פתוח", callback_data="merge_pr_menu")],
            [InlineKeyboardButton("🔙 חזור", callback_data="github_menu")],
        ]
        await query.edit_message_text(
            f"🔀 פעולות Pull Request עבור <code>{session['selected_repo']}</code>",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML",
        )
    async def show_create_pr_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        user_id = query.from_user.id
        session = self.get_user_session(user_id)
        token = self.get_user_token(user_id)
        repo_name = session.get("selected_repo")
        if not (token and repo_name):
            await query.edit_message_text("❌ חסרים נתונים")
            return
        g = Github(token)
        repo = g.get_repo(repo_name)
        branches = list(repo.get_branches())
        page = context.user_data.get("pr_branches_page", 0)
        page_size = 10
        total_pages = max(1, (len(branches) + page_size - 1) // page_size)
        page = min(max(0, page), total_pages - 1)
        start = page * page_size
        end = start + page_size
        keyboard = []
        for br in branches[start:end]:
            keyboard.append(
                [InlineKeyboardButton(f"🌿 {br.name}", callback_data=f"pr_select_head:{br.name}")]
            )
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton("⬅️ הקודם", callback_data=f"branches_page_{page-1}"))
        nav.append(InlineKeyboardButton(f"עמוד {page+1}/{total_pages}", callback_data="noop"))
        if page < total_pages - 1:
            nav.append(InlineKeyboardButton("הבא ➡️", callback_data=f"branches_page_{page+1}"))
        if nav:
            keyboard.append(nav)
        keyboard.append([InlineKeyboardButton("🔙 חזור", callback_data="pr_menu")])
        await query.edit_message_text(
            f"🆕 צור PR — בחר סניף head (base יהיה ברירת המחדל של הריפו)",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
    async def show_confirm_create_pr(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        user_id = query.from_user.id
        session = self.get_user_session(user_id)
        token = self.get_user_token(user_id)
        repo_name = session.get("selected_repo")
        if not (token and repo_name):
            await query.edit_message_text("❌ חסרים נתונים")
            return
        head = context.user_data.get("pr_head")
        g = Github(token)
        repo = g.get_repo(repo_name)
        base = repo.default_branch or "main"
        txt = (
            f"תיצור PR חדש?\n"
            f"ריפו: <code>{repo_name}</code>\n"
            f"base: <code>{base}</code> ← head: <code>{head}</code>\n\n"
            f"כותרת: <code>PR: {head} → {base}</code>"
        )
        kb = [
            [InlineKeyboardButton("✅ אשר יצירה", callback_data="confirm_create_pr")],
            [InlineKeyboardButton("🔙 חזור", callback_data="create_pr_menu")],
        ]
        await query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")

    async def confirm_create_pr(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        user_id = query.from_user.id
        session = self.get_user_session(user_id)
        token = self.get_user_token(user_id)
        repo_name = session.get("selected_repo")
        if not (token and repo_name):
            await query.edit_message_text("❌ חסרים נתונים")
            return
        head = context.user_data.get("pr_head")
        try:
            g = Github(token)
            repo = g.get_repo(repo_name)
            base = repo.default_branch or "main"
            title = f"PR: {head} → {base} (via bot)"
            body = "נוצר אוטומטית על ידי הבוט"
            pr = repo.create_pull(title=title, body=body, base=base, head=head)
            await query.edit_message_text(
                f'✅ נוצר PR: <a href="{pr.html_url}">{safe_html_escape(pr.title)}</a>',
                parse_mode="HTML",
            )
        except Exception as e:
            await query.edit_message_text(f"❌ שגיאה ביצירת PR: {e}")
            return
        await self.show_pr_menu(update, context)

    async def show_merge_pr_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        user_id = query.from_user.id
        session = self.get_user_session(user_id)
        token = self.get_user_token(user_id)
        repo_name = session.get("selected_repo")
        if not (token and repo_name):
            await query.edit_message_text("❌ חסרים נתונים")
            return
        g = Github(token)
        repo = g.get_repo(repo_name)
        pulls = list(repo.get_pulls(state="open", sort="created", direction="desc"))
        page = context.user_data.get("pr_list_page", 0)
        page_size = 10
        total_pages = max(1, (len(pulls) + page_size - 1) // page_size)
        page = min(max(0, page), total_pages - 1)
        start = page * page_size
        end = start + page_size
        keyboard = []
        for pr in pulls[start:end]:
            title = safe_html_escape(pr.title)
            keyboard.append(
                [
                    InlineKeyboardButton(
                        f"#{pr.number} {title}", callback_data=f"merge_pr:{pr.number}"
                    )
                ]
            )
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton("⬅️ הקודם", callback_data=f"prs_page_{page-1}"))
        nav.append(InlineKeyboardButton(f"עמוד {page+1}/{total_pages}", callback_data="noop"))
        if page < total_pages - 1:
            nav.append(InlineKeyboardButton("הבא ➡️", callback_data=f"prs_page_{page+1}"))
        if nav:
            keyboard.append(nav)
        keyboard.append([InlineKeyboardButton("🔙 חזור", callback_data="pr_menu")])
        await query.edit_message_text(
            f"🔀 בחר PR למיזוג (פתוחים בלבד)", reply_markup=InlineKeyboardMarkup(keyboard)
        )

    async def show_confirm_merge_pr(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        user_id = query.from_user.id
        session = self.get_user_session(user_id)
        token = self.get_user_token(user_id)
        repo_name = session.get("selected_repo")
        pr_number = context.user_data.get("pr_to_merge")
        if not (token and repo_name and pr_number):
            await query.edit_message_text("❌ חסרים נתונים")
            return
        g = Github(token)
        repo = g.get_repo(repo_name)
        pr = repo.get_pull(pr_number)
        try:
            pr.update()
        except Exception:
            pass
        checks = []
        can_merge = True
        try:
            # Try to read permissions from repo API result
            perms = repo.raw_data.get("permissions") if hasattr(repo, "raw_data") else None
            if isinstance(perms, dict):
                push_allowed = bool(perms.get("push"))
            else:
                push_allowed = True
            checks.append(f"הרשאת push: {'כן' if push_allowed else 'לא'}")
            if not push_allowed:
                can_merge = False
        except Exception:
            pass
        mergeable = pr.mergeable
        mergeable_state = getattr(pr, "mergeable_state", None)
        if mergeable is False:
            can_merge = False
        checks.append(f"מצב mergeable: {mergeable_state or ('כן' if mergeable else 'לא ידוע')}")
        try:
            statuses = list(repo.get_commit(pr.head.sha).get_statuses())
            if statuses:
                latest_state = statuses[0].state
                checks.append(f"סטטוסים: {latest_state}")
        except Exception:
            pass
        if getattr(pr, "draft", False):
            checks.append("Draft: כן")
            can_merge = False
        else:
            checks.append("Draft: לא")
        try:
            reviews = list(pr.get_reviews())
            need_changes = any(r.state == 'CHANGES_REQUESTED' for r in reviews)
            if need_changes:
                checks.append("בקשות שינוי פתוחות: כן")
                can_merge = False
        except Exception:
            pass
        txt = (
            f"למזג PR?\n"
            f"#{pr.number}: <b>{safe_html_escape(pr.title)}</b>\n"
            f"{pr.html_url}\n\n"
            f"בדיקות לפני מיזוג:\n" + "\n".join(f"• {c}" for c in checks)
        )
        kb = []
        kb.append([InlineKeyboardButton("🔄 רענן בדיקות", callback_data="refresh_merge_pr")])
        if can_merge:
            kb.append([InlineKeyboardButton("✅ אשר מיזוג", callback_data="confirm_merge_pr")])
        kb.append([InlineKeyboardButton("🔙 חזור", callback_data="merge_pr_menu")])
        await query.edit_message_text(
            txt,
            reply_markup=InlineKeyboardMarkup(kb),
            parse_mode="HTML",
            disable_web_page_preview=True,
        )

    async def confirm_merge_pr(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        user_id = query.from_user.id
        session = self.get_user_session(user_id)
        token = self.get_user_token(user_id)
        repo_name = session.get("selected_repo")
        pr_number = context.user_data.get("pr_to_merge")
        if not (token and repo_name and pr_number):
            await query.edit_message_text("❌ חסרים נתונים")
            return
        try:
            g = Github(token)
            repo = g.get_repo(repo_name)
            pr = repo.get_pull(pr_number)
            result = pr.merge(merge_method="merge")
            if result.merged:
                await query.edit_message_text(
                    f"✅ PR מוזג בהצלחה: <a href=\"{pr.html_url}\">#{pr.number}</a>",
                    parse_mode="HTML",
                )
            else:
                await query.edit_message_text(f"❌ מיזוג נכשל: {result.message}")
        except Exception as e:
            await query.edit_message_text(f"❌ שגיאה במיזוג PR: {e}")
            return
        await self.show_pr_menu(update, context)

    async def git_checkpoint(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        user_id = query.from_user.id
        session = self.get_user_session(user_id)
        repo_full = session.get("selected_repo")
        token = self.get_user_token(user_id)
        if not token or not repo_full:
            await query.edit_message_text("❌ חסר טוקן או ריפו נבחר")
            return
        # Acknowledge the callback early to avoid Telegram timeout spinner
        try:
            await query.answer("יוצר נקודת שמירה...", show_alert=False)
        except Exception:
            pass
        try:
            import datetime
            g = Github(login_or_token=token)
            repo = g.get_repo(repo_full)
            branch_obj = repo.get_branch(repo.default_branch)
            default_branch = branch_obj.name
            sha = branch_obj.commit.sha
            ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d-%H%M%S")
            prefix = (config.GIT_CHECKPOINT_PREFIX or "checkpoint").strip()
            # שמור על תווים חוקיים לשמות refs בסיסיים
            prefix = re.sub(r"[^A-Za-z0-9._/-]+", "-", prefix)
            base_name = f"{prefix}-{ts}"
            tag_name = base_name
            # Create lightweight tag by creating a ref refs/tags/<tag>
            try:
                repo.create_git_ref(ref=f"refs/tags/{tag_name}", sha=sha)
            except GithubException as ge:
                status = getattr(ge, 'status', None)
                # נסה פעם נוספת עם סיומת SHA במקרה של התנגשויות בשם
                if status == 422:
                    try:
                        tag_name = f"{base_name}-{sha[:7]}"
                        repo.create_git_ref(ref=f"refs/tags/{tag_name}", sha=sha)
                    except GithubException as ge2:
                        # fallback ל-branch
                        branch_name = base_name
                        try:
                            repo.create_git_ref(ref=f"refs/heads/{branch_name}", sha=sha)
                        except GithubException as gbe:
                            if getattr(gbe, 'status', None) == 422:
                                branch_name = f"{base_name}-{sha[:7]}"
                                repo.create_git_ref(ref=f"refs/heads/{branch_name}", sha=sha)
                            else:
                                raise ge  # שמור על הודעת השגיאה המקורית של ה-tag
                        # הצלחת גיבוי לענף
                        text = (
                            f"✅ נוצר branch (Fallback): <code>{branch_name}</code> על <code>{default_branch}</code>\n"
                            f"סיבה: tag נחסם (HTTP {status or 'N/A'})\n"
                            f"SHA: <code>{sha[:7]}</code>\n"
                            f"שחזור מהיר: <code>git checkout {branch_name}</code>\n\n"
                            f"רוצה שאיצור עבורך קובץ הוראות לשחזור?"
                        )
                        kb = [
                            [InlineKeyboardButton("📝 צור קובץ הוראות", callback_data=f"git_checkpoint_doc:branch:{branch_name}")],
                            [InlineKeyboardButton("לא תודה", callback_data="git_checkpoint_doc_skip")],
                        ]
                        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")
                        return
                else:
                    # לא 422: עבור ישירות לגיבוי לענף
                    branch_name = base_name
                    try:
                        repo.create_git_ref(ref=f"refs/heads/{branch_name}", sha=sha)
                    except GithubException as gbe:
                        if getattr(gbe, 'status', None) == 422:
                            branch_name = f"{base_name}-{sha[:7]}"
                            repo.create_git_ref(ref=f"refs/heads/{branch_name}", sha=sha)
                        else:
                            raise ge
                    text = (
                        f"✅ נוצר branch (Fallback): <code>{branch_name}</code> על <code>{default_branch}</code>\n"
                        f"סיבה: יצירת tag נכשלה (HTTP {status or 'N/A'})\n"
                        f"SHA: <code>{sha[:7]}</code>\n"
                        f"שחזור מהיר: <code>git checkout {branch_name}</code>\n\n"
                        f"רוצה שאיצור עבורך קובץ הוראות לשחזור?"
                    )
                    kb = [
                        [InlineKeyboardButton("📝 צור קובץ הוראות", callback_data=f"git_checkpoint_doc:branch:{branch_name}")],
                        [InlineKeyboardButton("לא תודה", callback_data="git_checkpoint_doc_skip")],
                    ]
                    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")
                    return
            # הצלחת יצירת tag
            text = (
                f"✅ נוצר tag: <code>{tag_name}</code> על <code>{default_branch}</code>\n"
                f"SHA: <code>{sha[:7]}</code>\n"
                f"שחזור מהיר: <code>git checkout tags/{tag_name}</code>\n\n"
                f"רוצה שאיצור עבורך קובץ הוראות לשחזור?"
            )
            kb = [
                [InlineKeyboardButton("📝 צור קובץ הוראות", callback_data=f"git_checkpoint_doc:tag:{tag_name}")],
                [InlineKeyboardButton("לא תודה", callback_data="git_checkpoint_doc_skip")],
            ]
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")
        except GithubException as e:
            status = getattr(e, 'status', None)
            gh_message = ''
            try:
                gh_message = (e.data or {}).get('message')  # type: ignore[attr-defined]
            except Exception:
                gh_message = str(e)
            help_lines = [
                "בדוק את הרשאות ה-Token שלך:",
                "• לטוקן קלאסי: <b>repo</b> (גישה מלאה) או לכל הפחות <b>public_repo</b> לריפו ציבורי.",
                "• לטוקן מסוג Fine-grained: תחת Repository permissions, תן <b>Contents: Read and write</b> ו-<b>Metadata: Read-only</b> לריפו.",
                "• ודא שיש לך גישת כתיבה לריפו (לא רק לקריאה/פורק).",
                "• בארגונים, ייתכן שנדרש לאשר את האפליקציה/הטוקן בארגון.",
            ]
            extra = ""
            if status in (403, 404):
                extra = "\nייתכן שאין הרשאת כתיבה או שהטוקן מוגבל."
            await query.edit_message_text(
                f"❌ יצירת נקודת שמירה בגיט נכשלה (HTTP {status or 'N/A'}): <b>{safe_html_escape(gh_message)}</b>{extra}\n\n" +
                "\n".join(help_lines),
                parse_mode="HTML",
            )
        except Exception as e:
            logger.error(f"Failed to create git checkpoint: {e}")
            await query.edit_message_text(f"❌ יצירת נקודת שמירה בגיט נכשלה: {safe_html_escape(e)}", parse_mode="HTML")

    async def show_pre_upload_check(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """מציג בדיקות לפני העלאת קובץ שמור (הרשאות/קיום קובץ/ענף/תיקייה)."""
        query = update.callback_query if hasattr(update, "callback_query") else None
        user_id = (query.from_user.id if query else update.effective_user.id)
        session = self.get_user_session(user_id)
        token = self.get_user_token(user_id)
        repo_name = session.get("selected_repo")
        file_id = context.user_data.get("pending_saved_file_id")
        if not (token and repo_name and file_id):
            if query:
                await query.edit_message_text("❌ חסרים נתונים (טוקן/ריפו/קובץ)")
            else:
                await update.message.reply_text("❌ חסרים נתונים (טוקן/ריפו/קובץ)")
            return
        from database import db
        try:
            from bson import ObjectId
            file_data = db.collection.find_one({"_id": ObjectId(file_id), "user_id": user_id})
            if not file_data:
                if query:
                    await query.edit_message_text("❌ קובץ לא נמצא")
                else:
                    await update.message.reply_text("❌ קובץ לא נמצא")
                return
            filename = file_data.get("file_name") or "file"
            # Resolve target folder/branch (overrides take precedence)
            override_folder = (context.user_data.get("upload_target_folder") or "").strip()
            target_folder = override_folder if override_folder != "" else (session.get("selected_folder") or "")
            g = Github(token)
            repo = g.get_repo(repo_name)
            override_branch = context.user_data.get("upload_target_branch")
            default_branch = repo.default_branch or "main"
            target_branch = override_branch or default_branch
            # Build file path
            if target_folder:
                folder_clean = target_folder.strip("/")
                file_path = f"{folder_clean}/{filename}"
            else:
                folder_clean = ""
                file_path = filename
            # Basic repo flags
            archived = getattr(repo, "archived", False)
            perms = repo.raw_data.get("permissions") if hasattr(repo, "raw_data") else None
            push_allowed = True if not isinstance(perms, dict) else bool(perms.get("push"))
            # Check if file exists on target branch
            exists = False
            try:
                repo.get_contents(file_path, ref=target_branch)
                exists = True
            except Exception:
                exists = False
            # Build summary text
            checks = []
            checks.append(f"ענף יעד: {target_branch}")
            checks.append(f"תיקייה: {folder_clean or 'root'}")
            checks.append(f"הרשאת push: {'כן' if push_allowed else 'לא'}")
            checks.append(f"Archived: {'כן' if archived else 'לא'}")
            checks.append(f"הקובץ קיים כבר: {'כן (יעודכן)' if exists else 'לא (ייווצר חדש)'}")
            txt = (
                "בדיקות לפני העלאה:\n"
                f"ריפו: <code>{repo_name}</code>\n"
                f"קובץ: <code>{file_path}</code>\n\n"
                + "\n".join(f"• {c}" for c in checks)
            )
            # Build keyboard
            kb = []
            kb.append([InlineKeyboardButton("🌿 בחר ענף יעד", callback_data="choose_upload_branch")])
            kb.append([InlineKeyboardButton("📂 בחר תיקיית יעד", callback_data="choose_upload_folder")])
            kb.append([InlineKeyboardButton("➕ צור תיקייה חדשה", callback_data="upload_folder_create")])
            kb.append([InlineKeyboardButton("🔄 רענן בדיקות", callback_data="refresh_saved_checks")])
            if push_allowed and not archived:
                kb.append([InlineKeyboardButton("✅ אשר והעלה", callback_data="confirm_saved_upload")])
            kb.append([InlineKeyboardButton("🔙 חזור", callback_data="back_to_menu")])
            if query:
                await query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")
            else:
                await update.message.reply_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")
        except Exception as e:
            msg = f"❌ שגיאה בבדיקות לפני העלאה: {safe_html_escape(str(e))}"
            if query:
                await query.edit_message_text(msg, parse_mode="HTML")
            else:
                await update.message.reply_text(msg, parse_mode="HTML")

    async def confirm_saved_upload(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        # Proceed with the actual upload of the saved file after checks
        file_id = context.user_data.get("pending_saved_file_id")
        if not file_id:
            await update.edit_message_text("❌ לא נמצא קובץ ממתין להעלאה")
        else:
            await self.handle_saved_file_upload(update, context, file_id)

    async def refresh_saved_checks(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.show_pre_upload_check(update, context)

    async def show_upload_branch_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        user_id = query.from_user.id
        session = self.get_user_session(user_id)
        token = self.get_user_token(user_id)
        repo_name = session.get("selected_repo")
        if not (token and repo_name):
            await query.edit_message_text("❌ חסרים נתונים")
            return
        g = Github(token)
        repo = g.get_repo(repo_name)
        branches = list(repo.get_branches())
        page = context.user_data.get("upload_branches_page", 0)
        page_size = 10
        total_pages = max(1, (len(branches) + page_size - 1) // page_size)
        page = min(max(0, page), total_pages - 1)
        start = page * page_size
        end = start + page_size
        keyboard = []
        # מיפוי ענפים ל-token קצר כדי למנוע חיתוך/שגיאות באורך callback
        branch_tokens = context.user_data.get("upload_branch_tokens") or {}
        for br in branches[start:end]:
            br_name = str(getattr(br, "name", "") or "")
            # הפק token קצר ודטרמיניסטי-מספיק לשימוש זמני בתפריט
            try:
                tok = secrets.token_urlsafe(6)
            except Exception:
                tok = "t"
            tok = tok[:24]
            branch_tokens[tok] = br_name
            keyboard.append([InlineKeyboardButton(f"🌿 {br_name}", callback_data=f"upload_select_branch_tok:{tok}")])
        context.user_data["upload_branch_tokens"] = branch_tokens
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton("⬅️ הקודם", callback_data=f"upload_branches_page_{page-1}"))
        nav.append(InlineKeyboardButton(f"עמוד {page+1}/{total_pages}", callback_data="noop"))
        if page < total_pages - 1:
            nav.append(InlineKeyboardButton("הבא ➡️", callback_data=f"upload_branches_page_{page+1}"))
        if nav:
            keyboard.append(nav)
        keyboard.append([InlineKeyboardButton("🔙 חזור", callback_data="refresh_saved_checks")])
        # עריכת ההודעה עם טיפול ב"message is not modified" – במקרה כזה ננסה לעדכן רק את המקלדת
        try:
            await query.edit_message_text("בחר ענף יעד להעלאה:", reply_markup=InlineKeyboardMarkup(keyboard))
        except BadRequest as br:
            if "message is not modified" in str(br).lower():
                try:
                    from utils import TelegramUtils as _TU
                    await _TU.safe_edit_message_reply_markup(query, reply_markup=InlineKeyboardMarkup(keyboard))
                except Exception:
                    pass
            else:
                raise

    async def show_upload_folder_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        user_id = query.from_user.id
        session = self.get_user_session(user_id)
        # הצג את התיקייה הפעילה הנוכחית: עדיפות ל-override זמני מזרימת ההעלאה, אחרת התיקייה שנבחרה במפגש, אחרת root
        current = (context.user_data.get("upload_target_folder") or session.get("selected_folder") or "root")
        kb = [
            [InlineKeyboardButton("📁 root (ראשי)", callback_data="upload_folder_root")],
            [InlineKeyboardButton(f"📂 השתמש בתיקייה שנבחרה: {current}", callback_data="upload_folder_current")],
            [InlineKeyboardButton("✏️ הזן נתיב ידנית", callback_data="upload_folder_custom")],
            [InlineKeyboardButton("➕ צור תיקייה חדשה", callback_data="upload_folder_create")],
            [InlineKeyboardButton("🔙 חזור", callback_data="refresh_saved_checks")],
        ]
        try:
            await query.edit_message_text("בחר תיקיית יעד:", reply_markup=InlineKeyboardMarkup(kb))
        except BadRequest as br:
            if "message is not modified" in str(br).lower():
                try:
                    from utils import TelegramUtils as _TU
                    await _TU.safe_edit_message_reply_markup(query, reply_markup=InlineKeyboardMarkup(kb))
                except Exception:
                    pass
            else:
                raise

    async def ask_upload_folder(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        context.user_data["waiting_for_upload_folder"] = True
        await query.edit_message_text(
            "✏️ הקלד נתיב תיקייה יעד (למשל: src/utils או ריק ל-root).\nשלח טקסט חופשי עכשיו.")

    async def create_checkpoint_doc(self, update: Update, context: ContextTypes.DEFAULT_TYPE, kind: str, name: str):
        """יוצר קובץ הוראות שחזור לנקודת שמירה ושולח ל-flow של העלאה"""
        query = update.callback_query
        user_id = query.from_user.id
        session = self.get_user_session(user_id)
        repo_full = session.get("selected_repo") or ""
        from datetime import datetime
        # בנה תוכן Markdown
        is_tag = (kind == "tag")
        title = "# 🏷️ נקודת שמירה בגיט\n\n"
        what = (f"נוצר tag בשם `{name}`" if is_tag else f"נוצר branch בשם `{name}`")
        repo_line = f"בריפו: `{repo_full}`\n\n" if repo_full else "\n"
        intro = (
            f"{what}.\n{repo_line}"
            "כך ניתן לשחזר לאותה נקודה במחשב המקומי:\n\n"
        )
        if is_tag:
            commands = (
                "1. עדכן תגיות מהריפו:\n\n"
                "```bash\n"
                "git fetch --tags\n"
                "```\n\n"
                "2. מעבר לקריאה בלבד ל-tag (מצב detached):\n\n"
                f"```bash\n"
                f"git checkout tags/{name}\n"
                "```\n\n"
                "3. לחזרה לענף הראשי לאחר מכן:\n\n"
                "```bash\n"
                "git checkout -\n"
                "```\n"
            )
        else:
            commands = (
                "1. עדכן רפרנסים מהריפו:\n\n"
                "```bash\n"
                "git fetch origin\n"
                "```\n\n"
                "2. מעבר לענף שנוצר:\n\n"
                f"```bash\n"
                f"git checkout {name}\n"
                "```\n"
            )
        notes = (
            "\n> הערות:\n"
            "> - נקודת שמירה היא רפרנס ל-commit (tag או branch).\n"
            "> - ניתן למחוק את הקובץ הזה לאחר השחזור.\n"
        )
        content = title + intro + commands + notes
        file_name = f"RESTORE_{name}.md"
        # שמירה במסד והמשך ל-flow של העלאה
        from database import db
        doc = {
            "user_id": user_id,
            "file_name": file_name,
            "content": content,
            "programming_language": "markdown",
            "description": "הוראות שחזור לנקודת שמירה",
            "tags": ["checkpoint", "instructions"],
            "version": 1,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
            "is_active": True,
        }
        try:
            res = db.collection.insert_one(doc)
            context.user_data["pending_saved_file_id"] = str(res.inserted_id)
            # פתח את בדיקות ההעלאה (בחירת ענף/תיקייה ואישור)
            await self.show_pre_upload_check(update, context)
        except Exception as e:
            await query.edit_message_text(f"❌ נכשל ביצירת קובץ הוראות: {safe_html_escape(str(e))}")
    async def show_restore_checkpoint_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """מציג רשימת תגיות נקודות שמירה לבחירה לשחזור"""
        query = update.callback_query
        user_id = query.from_user.id
        session = self.get_user_session(user_id)
        token = self.get_user_token(user_id)
        repo_full = session.get("selected_repo")
        if not (token and repo_full):
            try:
                await query.edit_message_text("❌ חסר טוקן או ריפו נבחר")
            except BadRequest as br:
                if "message is not modified" not in str(br).lower():
                    raise
                try:
                    await query.answer("❌ חסר טוקן או ריפו נבחר", show_alert=True)
                except Exception:
                    pass
            return
        try:
            g = Github(token)
            repo = g.get_repo(repo_full)
            # משוך תגיות (נחתוך לכמות סבירה, למשל 100)
            tags = list(repo.get_tags())[:100]
            prefix = (config.GIT_CHECKPOINT_PREFIX or "checkpoint").strip()
            # שמות חוקיים
            prefix = re.sub(r"[^A-Za-z0-9._/-]+", "-", prefix)
            checkpoint_tags = [t for t in tags if (t.name or "").startswith(prefix + "-")]
            if not checkpoint_tags:
                try:
                    await query.edit_message_text("ℹ️ לא נמצאו תגיות נקודת שמירה בריפו.")
                except BadRequest as br:
                    if "message is not modified" not in str(br).lower():
                        raise
                    try:
                        await query.answer("ℹ️ לא נמצאו תגיות נקודת שמירה", show_alert=False)
                    except Exception:
                        pass
                return
            # עימוד
            page = int(context.user_data.get("restore_tags_page", 0) or 0)
            per_page = 10
            total = len(checkpoint_tags)
            total_pages = max(1, (total + per_page - 1) // per_page)
            page = min(max(0, page), total_pages - 1)
            start = page * per_page
            end = start + per_page
            page_tags = checkpoint_tags[start:end]
            # בנה מקלדת
            keyboard = []
            for t in page_tags:
                keyboard.append([InlineKeyboardButton(f"🏷 {t.name}", callback_data=f"restore_select_tag:{t.name}")])
            nav = []
            if page > 0:
                nav.append(InlineKeyboardButton("⬅️ הקודם", callback_data=f"restore_tags_page_{page-1}"))
            nav.append(InlineKeyboardButton(f"📄 {page+1}/{total_pages}", callback_data="noop"))
            if page < total_pages - 1:
                nav.append(InlineKeyboardButton("➡️ הבא", callback_data=f"restore_tags_page_{page+1}"))
            if nav:
                keyboard.append(nav)
            keyboard.append([InlineKeyboardButton("🔙 חזור", callback_data="github_menu")])
            try:
                await query.edit_message_text(
                    "בחר תגית נקודת שמירה לשחזור:", reply_markup=InlineKeyboardMarkup(keyboard)
                )
            except BadRequest as br:
                if "message is not modified" not in str(br).lower():
                    # פרסום הודעה חדשה כגיבוי
                    await query.message.reply_text(
                        "בחר תגית נקודת שמירה לשחזור:", reply_markup=InlineKeyboardMarkup(keyboard)
                    )
                else:
                    try:
                        await query.answer("אין שינוי בתצוגה", show_alert=False)
                    except Exception:
                        pass
        except Exception as e:
            try:
                await query.edit_message_text(f"❌ שגיאה בטעינת תגיות: {safe_html_escape(str(e))}")
            except BadRequest as br:
                if "message is not modified" not in str(br).lower():
                    raise
                try:
                    await query.answer(f"❌ שגיאה בטעינת תגיות: {safe_html_escape(str(e))}", show_alert=True)
                except Exception:
                    pass

    async def show_restore_tag_actions(self, update: Update, context: ContextTypes.DEFAULT_TYPE, tag_name: str):
        """מציג פעולות אפשריות לשחזור מתגית נתונה"""
        query = update.callback_query
        user_id = query.from_user.id
        session = self.get_user_session(user_id)
        repo_full = session.get("selected_repo")
        if not repo_full:
            await query.edit_message_text("❌ לא נבחר ריפו")
            return
        # הצג אפשרויות: צור קובץ הוראות / צור ענף מהתגית
        text = (
            f"🏷 תגית נבחרה: <code>{tag_name}</code>\n\n"
            f"בחר פעולה לשחזור:" 
        )
        kb = [
            [InlineKeyboardButton("📝 צור קובץ הוראות", callback_data=f"git_checkpoint_doc:tag:{tag_name}")],
            [InlineKeyboardButton("🌿 צור ענף מהתגית", callback_data=f"restore_branch_from_tag:{tag_name}")],
            [InlineKeyboardButton("🔁 צור PR לשחזור (Revert)", callback_data=f"restore_revert_pr_from_tag:{tag_name}")],
            [InlineKeyboardButton("🔙 חזור", callback_data="restore_checkpoint_menu")],
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")
    async def create_branch_from_tag(self, update: Update, context: ContextTypes.DEFAULT_TYPE, tag_name: str):
        """יוצר ענף חדש שמצביע ל-commit של התגית לשחזור נוח"""
        query = update.callback_query
        user_id = query.from_user.id
        session = self.get_user_session(user_id)
        token = self.get_user_token(user_id)
        repo_full = session.get("selected_repo")
        if not (token and repo_full):
            await query.edit_message_text("❌ חסר טוקן או ריפו נבחר")
            return
        try:
            g = Github(token)
            repo = g.get_repo(repo_full)
            sha = None
            # נסה להשיג SHA מה-ref של התגית
            try:
                ref = repo.get_git_ref(f"tags/{tag_name}")
                sha = ref.object.sha
            except GithubException:
                # נפילה חזרה לחיפוש ברשימת תגיות
                for t in repo.get_tags():
                    if t.name == tag_name:
                        sha = t.commit.sha
                        break
            if not sha:
                await query.edit_message_text("❌ לא נמצאה התגית המבוקשת")
                return
            # שם ברירת מחדל לענף שחזור
            base_branch = re.sub(r"[^A-Za-z0-9._/-]+", "-", f"restore-{tag_name}")
            branch_name = base_branch
            # צור את ה-ref, עם ניסיון לשמור על ייחודיות
            try:
                repo.create_git_ref(ref=f"refs/heads/{branch_name}", sha=sha)
            except GithubException as gbe:
                if getattr(gbe, 'status', None) == 422:
                    branch_name = f"{base_branch}-{sha[:7]}"
                    repo.create_git_ref(ref=f"refs/heads/{branch_name}", sha=sha)
                else:
                    raise
            kb = [
                [InlineKeyboardButton("🔀 פתח PR מהענף", callback_data=f"open_pr_from_branch:{branch_name}")],
                [InlineKeyboardButton("🔙 חזור", callback_data="restore_checkpoint_menu")],
            ]
            await query.edit_message_text(
                f"✅ נוצר ענף שחזור: <code>{branch_name}</code> מתוך <code>{tag_name}</code>\n\n"
                f"שחזור מקומי מהיר:\n"
                f"<code>git fetch origin && git checkout {branch_name}</code>",
                reply_markup=InlineKeyboardMarkup(kb),
                parse_mode="HTML",
            )
        except Exception as e:
            # הצג אפשרות להמשיך ליצירת PR לשחזור למרות הכישלון ביצירת ענף
            try:
                kb = [
                    [InlineKeyboardButton("🔁 צור PR לשחזור (Revert)", callback_data=f"restore_revert_pr_from_tag:{tag_name}")],
                    [InlineKeyboardButton("🔙 חזור", callback_data="restore_checkpoint_menu")],
                ]
                await query.edit_message_text(
                    f"❌ שגיאה ביצירת ענף שחזור: {safe_html_escape(str(e))}\n\n"
                    f"תוכל עדיין ליצור PR לשחזור ישירות מהתגית <code>{tag_name}</code>.",
                    reply_markup=InlineKeyboardMarkup(kb),
                    parse_mode="HTML",
                )
            except Exception:
                await query.edit_message_text(f"❌ שגיאה ביצירת ענף שחזור: {safe_html_escape(str(e))}")

    async def open_pr_from_branch(self, update: Update, context: ContextTypes.DEFAULT_TYPE, branch_name: str):
        """פותח Pull Request מהענף שנוצר אל הענף הראשי של הריפו"""
        query = update.callback_query
        user_id = query.from_user.id
        session = self.get_user_session(user_id)
        token = self.get_user_token(user_id)
        repo_full = session.get("selected_repo")
        if not (token and repo_full):
            await query.edit_message_text("❌ חסר טוקן או ריפו נבחר")
            return
        try:
            g = Github(token)
            repo = g.get_repo(repo_full)
            base_branch = repo.default_branch or "main"
            owner_login = repo.owner.login if getattr(repo, "owner", None) else repo_full.split("/")[0]

            # 1) אם כבר קיים PR פתוח מהענף הזה לבסיס – הצג אותו במקום ליצור חדש
            try:
                existing_prs = list(
                    repo.get_pulls(state="open", base=base_branch, head=f"{owner_login}:{branch_name}")
                )
                if existing_prs:
                    pr = existing_prs[0]
                    kb = [[InlineKeyboardButton("🔙 חזור", callback_data="github_menu")]]
                    await query.edit_message_text(
                        f"ℹ️ כבר קיים PR פתוח מהענף <code>{branch_name}</code> ל-<code>{base_branch}</code>: "
                        f"<a href=\"{pr.html_url}\">#{pr.number}</a>",
                        parse_mode="HTML",
                        reply_markup=InlineKeyboardMarkup(kb),
                    )
                    return
            except Exception:
                # נמשיך לנסות ליצור PR אם לא הצלחנו לבדוק קיום
                pass

            # 2) בדוק שיש הבדלים בין HEAD ל-base (אחרת GitHub יחזיר Validation Failed)
            try:
                cmp = repo.compare(base_branch, branch_name)
                if getattr(cmp, "ahead_by", 0) == 0 and getattr(cmp, "behind_by", 0) == 0:
                    kb = [
                        [InlineKeyboardButton("↩️ בחר תגית אחרת", callback_data="restore_checkpoint_menu")],
                        [InlineKeyboardButton("🔙 חזור", callback_data="github_menu")],
                    ]
                    await query.edit_message_text(
                        (
                            "❌ לא ניתן לפתוח PR: אין שינויים בין הענף "
                            f"<code>{branch_name}</code> ל- <code>{base_branch}</code>\n\n"
                            "נסה לבחור תגית אחרת לשחזור, או בצע שינוי/commit בענף לפני פתיחת PR."
                        ),
                        parse_mode="HTML",
                        reply_markup=InlineKeyboardMarkup(kb),
                    )
                    return
            except Exception:
                # אם ההשוואה נכשלה, ננסה בכל זאת ליצור PR – ייתכן שהענף חדש מאוד
                pass

            # 3) צור PR
            title = f"Restore from checkpoint: {branch_name}"
            body = (
                f"Automated PR to restore state from branch `{branch_name}`.\n\n"
                f"Created via Telegram bot."
            )
            pr = repo.create_pull(title=title, body=body, head=branch_name, base=base_branch)
            kb = [[InlineKeyboardButton("🔙 חזור", callback_data="github_menu")]]
            await query.edit_message_text(
                f"✅ נפתח PR: <a href=\"{pr.html_url}\">#{pr.number}</a> ← <code>{base_branch}</code> ← <code>{branch_name}</code>",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(kb),
            )
        except GithubException as ge:
            # פרשנות מפורטת יותר לשגיאות Validation Failed
            message_text = "Validation Failed"
            try:
                data = ge.data or {}
                if isinstance(data, dict):
                    # הודעת על
                    if data.get("message"):
                        message_text = data["message"]
                    # בדוק פירוט שגיאות נפוצות
                    errors = data.get("errors") or []
                    if isinstance(errors, list) and errors:
                        details = []
                        for err in errors:
                            # err יכול להיות dict עם מפתחות code/message
                            code = err.get("code") if isinstance(err, dict) else None
                            msg = err.get("message") if isinstance(err, dict) else None
                            if code == "custom" and msg:
                                details.append(msg)
                            elif msg:
                                details.append(msg)
                        if details:
                            message_text += ": " + "; ".join(details)
            except Exception:
                pass

            # נסה לזהות במפורש "No commits between" או PR קיים ולהציע פתרון
            lower_msg = (message_text or "").lower()
            kb = [[InlineKeyboardButton("🔙 חזור", callback_data="github_menu")]]
            if "no commits between" in lower_msg or "no commits" in lower_msg:
                kb.insert(0, [InlineKeyboardButton("↩️ בחר תגית אחרת", callback_data="restore_checkpoint_menu")])
                await query.edit_message_text(
                    (
                        "❌ שגיאה בפתיחת PR: אין שינויים בין הענפים.\n\n"
                        f"ענף: <code>{branch_name}</code> → בסיס: <code>{base_branch}</code>\n\n"
                        "בחר נקודת שמירה מוקדמת יותר או בצע שינוי/commit בענף ואז נסה שוב."
                    ),
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup(kb),
                )
                return
            if "already exists" in lower_msg or "a pull request already exists" in lower_msg:
                # נסה למצוא את ה-PR הקיים ולהציג קישור
                try:
                    prs = list(repo.get_pulls(state="open", base=base_branch, head=f"{owner_login}:{branch_name}"))
                    if prs:
                        pr = prs[0]
                        await query.edit_message_text(
                            f"ℹ️ כבר קיים PR פתוח: <a href=\"{pr.html_url}\">#{pr.number}</a>",
                            parse_mode="HTML",
                            reply_markup=InlineKeyboardMarkup(kb),
                        )
                        return
                except Exception:
                    pass
            await query.edit_message_text(f"❌ שגיאה בפתיחת PR: {safe_html_escape(message_text)}", parse_mode="HTML")
        except Exception as e:
            await query.edit_message_text(f"❌ שגיאה בפתיחת PR: {safe_html_escape(str(e))}")

    async def create_revert_pr_from_tag(self, update: Update, context: ContextTypes.DEFAULT_TYPE, tag_name: str):
        """יוצר PR שמשחזר את מצב הריפו לתגית ע"י יצירת commit חדש עם עץ התגית על גבי base.
        כך תמיד יהיה diff וה-PR ייפתח בהצלחה.
        """
        query = update.callback_query
        user_id = query.from_user.id
        session = self.get_user_session(user_id)
        token = self.get_user_token(user_id)
        repo_full = session.get("selected_repo")
        if not (token and repo_full):
            await query.edit_message_text("❌ חסר טוקן או ריפו נבחר")
            return
        try:
            g = Github(token)
            repo = g.get_repo(repo_full)
            base_branch = repo.default_branch or "main"

            logger.info("[create_revert_pr_from_tag] repo=%s base=%s tag=%s user=%s", repo_full, base_branch, tag_name, user_id)

            # מצא את ה-SHA של עץ התגית (מתמודד גם עם תגיות מוכללות)
            tag_tree_sha = None
            try:
                ref = repo.get_git_ref(f"tags/{tag_name}")
                ref_obj = getattr(ref, "object", None)
                ref_type = getattr(ref_obj, "type", None)
                ref_sha = getattr(ref_obj, "sha", None)
                logger.info("[create_revert_pr_from_tag] ref_type=%s ref_sha=%s", ref_type, ref_sha)
                if ref_type == "commit" and ref_sha:
                    commit = repo.get_commit(ref_sha)
                    tag_tree_sha = commit.commit.tree.sha
                elif ref_type == "tag" and ref_sha:
                    # תגית מוכללת — נפרק לאובייקט היעד
                    tag_obj = repo.get_git_tag(ref_sha)
                    logger.info("[create_revert_pr_from_tag] annotated tag sha=%s", ref_sha)
                    while getattr(getattr(tag_obj, "object", None), "type", None) == "tag":
                        logger.info("[create_revert_pr_from_tag] peeling nested tag sha=%s", tag_obj.object.sha)
                        tag_obj = repo.get_git_tag(tag_obj.object.sha)
                    target_type = getattr(tag_obj.object, "type", None)
                    target_sha = getattr(tag_obj.object, "sha", None)
                    logger.info("[create_revert_pr_from_tag] tag target_type=%s target_sha=%s", target_type, target_sha)
                    if target_type == "commit" and target_sha:
                        commit = repo.get_commit(target_sha)
                        tag_tree_sha = commit.commit.tree.sha
                    elif target_type == "tree" and target_sha:
                        tag_tree_sha = target_sha
                elif ref_type == "tree" and ref_sha:
                    tag_tree_sha = ref_sha
            except GithubException as ge:
                logger.warning("[create_revert_pr_from_tag] get_git_ref failed: %s", getattr(ge, 'data', None) or str(ge))
                pass

            # נפילה ל-backup: מעבר על get_tags (עובד לרוב על תגיות קלילות)
            if not tag_tree_sha:
                logger.info("[create_revert_pr_from_tag] fallback to repo.get_tags() for %s", tag_name)
                for t in repo.get_tags():
                    if t.name == tag_name:
                        try:
                            commit = repo.get_commit(t.commit.sha)
                            tag_tree_sha = commit.commit.tree.sha
                            logger.info("[create_revert_pr_from_tag] fallback resolved tree=%s via commit=%s", tag_tree_sha, t.commit.sha)
                        except Exception as inner_e:
                            logger.exception("[create_revert_pr_from_tag] fallback resolving tag failed: %s", inner_e)
                        break
            if not tag_tree_sha:
                await query.edit_message_text("❌ לא נמצאה התגית המבוקשת")
                return

            # צור ענף עבודה חדש משם ברור
            safe_branch = re.sub(r"[^A-Za-z0-9._/-]+", "-", f"restore-from-{tag_name}")
            work_branch = safe_branch
            try:
                base_sha = repo.get_branch(base_branch).commit.sha
                logger.info("[create_revert_pr_from_tag] creating work branch=%s from base_sha=%s", work_branch, base_sha)
                repo.create_git_ref(ref=f"refs/heads/{work_branch}", sha=base_sha)
            except GithubException as gbe:
                if getattr(gbe, 'status', None) == 422:
                    work_branch = f"{safe_branch}-{int(time.time())}"
                    base_sha = repo.get_branch(base_branch).commit.sha
                    logger.info("[create_revert_pr_from_tag] branch exists, retry with %s", work_branch)
                    repo.create_git_ref(ref=f"refs/heads/{work_branch}", sha=base_sha)
                else:
                    raise

            # צור commit חדש בעבודה עם tree של התגית והורה מה-base
            base_head = repo.get_branch(base_branch).commit.sha
            parent = repo.get_git_commit(base_head)
            new_tree = repo.get_git_tree(tag_tree_sha)
            new_commit_message = f"Restore repository state from tag {tag_name}"
            logger.info("[create_revert_pr_from_tag] creating git commit on %s with tree=%s parent=%s", work_branch, tag_tree_sha, base_head)
            new_commit = repo.create_git_commit(new_commit_message, new_tree, [parent])
            # עדכן את ה-ref של הענף החדש ל-commit החדש
            repo.get_git_ref(f"heads/{work_branch}").edit(new_commit.sha, force=True)
            logger.info("[create_revert_pr_from_tag] updated ref heads/%s -> %s", work_branch, new_commit.sha)

            # פתח PR
            title = f"Restore to checkpoint: {tag_name}"
            body = (
                f"This PR restores the repository state to tag `{tag_name}` by creating a new commit with the tag's tree on top of `{base_branch}`.\n\n"
                f"Created via Telegram bot."
            )
            pr = repo.create_pull(title=title, body=body, head=work_branch, base=base_branch)
            kb = [[InlineKeyboardButton("🔙 חזור", callback_data="github_menu")]]
            await query.edit_message_text(
                f"✅ נפתח PR: <a href=\"{pr.html_url}\">#{pr.number}</a> ← <code>{base_branch}</code> ← <code>{work_branch}</code>",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(kb),
            )
        except GithubException as ge:
            msg = "Validation Failed"
            details = None
            try:
                data = ge.data or {}
                if isinstance(data, dict) and data.get('message'):
                    msg = data['message']
                details = json.dumps(data, ensure_ascii=False)
            except Exception:
                pass
            logger.error("[create_revert_pr_from_tag] GithubException: %s data=%s", msg, details)
            await query.edit_message_text(f"❌ שגיאה ביצירת PR לשחזור: {safe_html_escape(msg)}")
        except Exception as e:
            logger.exception("[create_revert_pr_from_tag] Unexpected error: %s", e)
            await query.edit_message_text(f"❌ שגיאה ביצירת PR לשחזור: {safe_html_escape(str(e))}")

    async def show_github_backup_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """מציג תפריט גיבוי/שחזור עבור הריפו הנבחר"""
        query = update.callback_query
        user_id = query.from_user.id
        session = self.get_user_session(user_id)
        token = self.get_user_token(user_id)
        repo_full = session.get("selected_repo")
        if not (token and repo_full):
            try:
                await query.edit_message_text("❌ חסר טוקן או ריפו נבחר")
            except BadRequest as br:
                if "message is not modified" not in str(br).lower():
                    raise
                try:
                    await query.answer("❌ חסר טוקן או ריפו נבחר", show_alert=True)
                except Exception:
                    pass
            return
        # כניסה לתפריט גיבוי/שחזור מתחילה זרם חדש – נקה נעילות/סטייטים קודמים
        try:
            context.user_data.pop("zip_restore_expected_repo_full", None)
            context.user_data.pop("github_restore_zip_purge", None)
            context.user_data.pop("pending_repo_restore_zip_path", None)
        except Exception:
            pass
        # סמן הקשר כדי לאפשר סינון גיבויים לפי הריפו הנוכחי
        context.user_data["github_backup_context_repo"] = repo_full
        kb = [
            [InlineKeyboardButton("📦 הורד גיבוי ZIP של הריפו", callback_data="download_zip:")],
            [InlineKeyboardButton("♻️ שחזר ZIP לריפו (פריסה והחלפה)", callback_data="github_restore_zip_to_repo")],
            [InlineKeyboardButton("📂 שחזר מגיבוי שמור לריפו", callback_data="github_restore_zip_list")],
            [InlineKeyboardButton("🏷 נקודת שמירה בגיט", callback_data="git_checkpoint")],
            [InlineKeyboardButton("↩️ חזרה לנקודת שמירה", callback_data="restore_checkpoint_menu")],
            [InlineKeyboardButton("🗂 גיבויי DB אחרונים", callback_data="github_backup_db_list")],
            [InlineKeyboardButton("♻️ שחזור מגיבוי (ZIP)", callback_data="backup_restore_full_start")],
            [InlineKeyboardButton("ℹ️ הסבר על הכפתורים", callback_data="github_backup_help")],
            [InlineKeyboardButton("🔙 חזור", callback_data="github_menu")],
        ]
        try:
            await query.edit_message_text(
                f"🧰 תפריט גיבוי ושחזור לריפו:\n<code>{repo_full}</code>",
                reply_markup=InlineKeyboardMarkup(kb),
                parse_mode="HTML",
            )
        except BadRequest as br:
            if "message is not modified" not in str(br).lower():
                # פרסום הודעה חדשה כגיבוי
                await query.message.reply_text(
                    f"🧰 תפריט גיבוי ושחזור לריפו:\n<code>{repo_full}</code>",
                    reply_markup=InlineKeyboardMarkup(kb),
                    parse_mode="HTML",
                )
            else:
                try:
                    await query.answer("אין שינוי בתצוגה", show_alert=False)
                except Exception:
                    pass
        return

        # Unreachable guard to satisfy linters if parser confuses block ends
        if False and (query and query.data == "github_restore_zip_to_repo"):
            pass
        elif query.data.startswith("github_restore_zip_setpurge:"):
            purge_flag = query.data.split(":", 1)[1] == "1"
            # ודא שניקינו דגלים ישנים של העלאה רגילה כדי למנוע בלבול
            context.user_data["waiting_for_github_upload"] = False
            context.user_data["upload_mode"] = "github_restore_zip_to_repo"
            context.user_data["github_restore_zip_purge"] = purge_flag
            await query.edit_message_text(
                ("🧹 יבוצע ניקוי לפני העלאה. " if purge_flag else "🔁 ללא מחיקה. ") +
                "שלח עכשיו קובץ ZIP לשחזור לריפו."
            )
            return
        elif query.data == "github_restore_zip_list":
            # הצג רשימת גיבויים (ZIP) של הריפו הנוכחי לצורך שחזור לריפו
            user_id = query.from_user.id
            session = self.get_user_session(user_id)
            repo_full = session.get("selected_repo")
            if not repo_full:
                await query.edit_message_text("❌ קודם בחר ריפו!")
                return
            from file_manager import backup_manager
            backups = backup_manager.list_backups(user_id)
            # סנן רק גיבויים עם metadata של אותו ריפו
            backups = [b for b in backups if getattr(b, 'repo', None) == repo_full]
            if not backups:
                await query.edit_message_text(
                    f"ℹ️ אין גיבויי ZIP שמורים עבור הריפו:\n<code>{repo_full}</code>",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 חזור", callback_data="github_backup_menu")]])
                )
                return
            # הצג עד 10 אחרונים
            items = backups[:10]
            lines = [f"בחר גיבוי לשחזור לריפו:\n<code>{repo_full}</code>\n"]
            kb = []
            for b in items:
                lines.append(f"• {b.backup_id} — {b.created_at.strftime('%d/%m/%Y %H:%M')} — {int(b.total_size/1024)}KB")
                kb.append([InlineKeyboardButton("♻️ שחזר גיבוי זה לריפו", callback_data=f"github_restore_zip_from_backup:{b.backup_id}")])
            kb.append([InlineKeyboardButton("🔙 חזור", callback_data="github_backup_menu")])
            await query.edit_message_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")
            return
        elif query.data.startswith("github_restore_zip_from_backup:"):
            # קבל backup_id ואז פתח את תהליך השחזור-לריפו עם קובץ ה-ZIP הזה
            backup_id = query.data.split(":", 1)[1]
            user_id = query.from_user.id
            from file_manager import backup_manager
            info_list = backup_manager.list_backups(user_id)
            match = next((b for b in info_list if b.backup_id == backup_id), None)
            if not match or not match.file_path or not os.path.exists(match.file_path):
                await query.edit_message_text("❌ הגיבוי לא נמצא בדיסק")
                return
            # הגדר purge? בקש בחירה
            context.user_data["pending_repo_restore_zip_path"] = match.file_path
            await query.edit_message_text(
                "האם למחוק קודם את התוכן בריפו לפני העלאה?",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🧹 מחיקה מלאה לפני העלאה", callback_data="github_repo_restore_backup_setpurge:1")],
                    [InlineKeyboardButton("🚫 אל תמחק, רק עדכן", callback_data="github_repo_restore_backup_setpurge:0")],
                    [InlineKeyboardButton("❌ ביטול", callback_data="github_backup_menu")],
                ])
            )
            return
        elif query.data.startswith("github_repo_restore_backup_setpurge:"):
            # בצע את ההעלאה לריפו מתוך קובץ ה-ZIP שמור בדיסק
            purge_flag = query.data.split(":", 1)[1] == "1"
            zip_path = context.user_data.get("pending_repo_restore_zip_path")
            if not zip_path or not os.path.exists(zip_path):
                await query.edit_message_text("❌ קובץ ZIP לא נמצא")
                return
            # הפעל ריסטור לריפו דרך פונקציה חיצונית פשוטה שמתממשקת עם main.handle_document logic
            try:
                await query.edit_message_text("⏳ משחזר לריפו מגיבוי נבחר...")
                # נשתמש בלוגיקה פשוטה: נקרא לפונקציה פנימית שתבצע את אותו זרם של שחזור לריפו
                await self.restore_zip_file_to_repo(update, context, zip_path, purge_flag)
                await query.edit_message_text("✅ השחזור הועלה לריפו בהצלחה")
            except Exception as e:
                await query.edit_message_text(f"❌ שגיאה בשחזור לריפו: {e}")
            finally:
                context.user_data.pop("pending_repo_restore_zip_path", None)
            return

    async def restore_zip_file_to_repo(self, update: Update, context: ContextTypes.DEFAULT_TYPE, zip_path: str, purge_first: bool) -> None:
        """שחזור קבצים מ-ZIP מקומי לריפו הנוכחי באמצעות Trees API (commit אחד)"""
        user_id = update.effective_user.id
        session = self.get_user_session(user_id)
        token = self.get_user_token(user_id)
        repo_full = session.get("selected_repo")
        if not (token and repo_full):
            raise RuntimeError("חסר טוקן או ריפו")
        # חגורת בטיחות: אשר שהיעד תואם את היעד שננעל בתחילת ה-flow
        expected = context.user_data.get("zip_restore_expected_repo_full")
        if expected and expected != repo_full:
            logger.critical(f"[restore_zip_from_backup] Target mismatch: expected={expected}, got={repo_full}. Aborting.")
            raise ValueError(f"Target mismatch: expected {expected}, got {repo_full}")
        if not expected:
            try:
                context.user_data["zip_restore_expected_repo_full"] = repo_full
            except Exception:
                pass
        import zipfile
        if not os.path.exists(zip_path) or not zipfile.is_zipfile(zip_path):
            raise RuntimeError("ZIP לא תקין")
        with zipfile.ZipFile(zip_path, 'r') as zf:
            # סינון קבצי מערכת לא רלוונטיים
            all_names = [n for n in zf.namelist() if not n.endswith('/')]
            members = [n for n in all_names if not (n.startswith('__MACOSX/') or n.split('/')[-1].startswith('._'))]
            # זיהוי תיקיית-שורש משותפת
            top_levels = set()
            for n in zf.namelist():
                if '/' in n and not n.startswith('__MACOSX/'):
                    top_levels.add(n.split('/', 1)[0])
            common_root = list(top_levels)[0] if len(top_levels) == 1 else None
            logger.info(f"[restore_zip_from_backup] Detected common_root={common_root!r}, files_in_zip={len(members)}")
            def strip_root(path: str) -> str:
                if common_root and path.startswith(common_root + '/'):
                    return path[len(common_root) + 1:]
                return path
            files = []
            for name in members:
                raw = zf.read(name)
                clean = strip_root(name)
                if not clean:
                    continue
                files.append((clean, raw))
        g = Github(token)
        repo = g.get_repo(repo_full)
        target_branch = repo.default_branch or 'main'
        base_ref = repo.get_git_ref(f"heads/{target_branch}")
        base_commit = repo.get_git_commit(base_ref.object.sha)
        base_tree = base_commit.tree
        elements = []
        for path, raw in files:
            # כתוב blob מתאים: טקסט כ-utf-8, בינארי כ-base64
            import base64
            is_text = any(path.lower().endswith(ext) for ext in (
                '.md', '.txt', '.json', '.yml', '.yaml', '.xml', '.gitignore', '.py', '.js', '.ts', '.tsx', '.css', '.scss', '.html', '.sh'
            ))
            try:
                if is_text:
                    content = raw.decode('utf-8')
                    blob = repo.create_git_blob(content, 'utf-8')
                else:
                    b64 = base64.b64encode(raw).decode('ascii')
                    blob = repo.create_git_blob(b64, 'base64')
            except Exception:
                b64 = base64.b64encode(raw).decode('ascii')
                blob = repo.create_git_blob(b64, 'base64')
            elements.append(InputGitTreeElement(path=path, mode='100644', type='blob', sha=blob.sha))
        if purge_first:
            # Soft purge: יצירת עץ חדש ללא בסיס (מוחק קבצים שאינם ב-ZIP)
            new_tree = repo.create_git_tree(elements)
        else:
            new_tree = repo.create_git_tree(elements, base_tree)
        commit_message = f"Restore from ZIP via bot: replace {'with purge' if purge_first else 'update only'}"
        new_commit = repo.create_git_commit(commit_message, new_tree, [base_commit])
        base_ref.edit(new_commit.sha)
        logger.info(f"[restore_zip_from_backup] Restore commit created: {new_commit.sha}, files_added={len(elements)}, purge={purge_first}")
        # ניקוי סטייט הגנה אחרי הצלחה
        try:
            context.user_data.pop("zip_restore_expected_repo_full", None)
        except Exception:
            pass