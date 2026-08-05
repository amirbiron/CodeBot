"""Handlers עבור מסמכים וקבצים הנשלחים לבוט."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import tempfile
import time
import zipfile
from datetime import datetime, timezone
from io import BytesIO
from typing import Any, Awaitable, Callable, Iterable, List, Optional, Protocol, Sequence

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import ContextTypes

# שימוש ב-FilesFacade דרך Composition Root כדי להימנע מתלות ישירה ב-DB
from typing import Optional as _Optional  # local alias to avoid collision
from file_manager import backup_manager
from html import escape as html_escape


logger = logging.getLogger(__name__)

# לוג חד-פעמי לתהליך כשטלגרם דוחה את האימוג'י המותאם (תנאי פרימיום/ID לא תקף)
_custom_emoji_warned = False

# מגבלות ייבוא ZIP — הגנה מפני "פצצת ZIP" (דקומפרסיה מתפוצצת) בעת בניית ריפו מקובץ.
# הבדיקות נעשות מול הגודל הלא-דחוס (ZipInfo.file_size) לפני קריאת התוכן לזיכרון.
MAX_IMPORT_ZIP_MEMBERS = 2000  # מספר קבצים מקסימלי בארכיון לייבוא
MAX_IMPORT_FILE_UNCOMPRESSED_BYTES = 50 * 1024 * 1024  # 50MB לקובץ בודד (לא דחוס)
MAX_IMPORT_TOTAL_UNCOMPRESSED_BYTES = 500 * 1024 * 1024  # 500MB סך הכל (לא דחוס)


def detect_zip_common_root(names: Iterable[str]) -> Optional[str]:
    """
    מזהה תיקיית שורש משותפת בארכיון, או ``None`` אם אין כזו.

    תיקיית שורש קיימת רק אם *כל* הרשומות נמצאות תחתיה. אם יש ולו קובץ אחד
    בשורש הארכיון, אין שורש משותף — אחרת ZIP כמו ``README.md`` + ``src/main.py``
    היה מזוהה בטעות עם שורש ``src``, ו-``src/main.py`` היה נחתך ל-``main.py``.
    """
    top_levels = set()
    has_root_level_file = False
    for name in names:
        if not name or name.startswith("__MACOSX/"):
            continue
        if "/" in name:
            top_levels.add(name.split("/", 1)[0])
        else:
            has_root_level_file = True
    if has_root_level_file or len(top_levels) != 1:
        return None
    return next(iter(top_levels))


def normalize_repo_folder(folder: str) -> str:
    """
    מנרמל נתיב של תיקיית יעד בריפו ומחזיר אותו בלי לוכסנים בקצוות.

    מחזיר מחרוזת ריקה עבור שורש הריפו. זורק ``ValueError`` אם הנתיב מנסה
    לצאת מהריפו (``..``), אם הוא נתיב מוחלט, או אם הוא מכיל תווים אסורים.
    """
    raw = (folder or "").strip().replace("\\", "/")
    if not raw:
        return ""
    # נתיב בריפו הוא תמיד יחסי לשורש שלו, ולכן "/docs" ו-"docs" זהים.
    # מנרמלים במקום לדחות, כי זו טעות הקלדה נפוצה ולא ניסיון לברוח מהריפו.
    raw = raw.lstrip("/")
    if not raw:
        return ""
    # "C:/..." הוא כמעט תמיד הדבקה של נתיב מהמחשב, ולא כוונה אמיתית
    if re.match(r"^[A-Za-z]:", raw):
        raise ValueError("נתיב היעד חייב להיות יחסי לריפו (לא נתיב מהמחשב).")

    parts: List[str] = []
    for part in raw.split("/"):
        if not part or part == ".":
            continue
        if part == "..":
            raise ValueError("נתיב היעד לא יכול להכיל '..'.")
        if "\x00" in part:
            raise ValueError("נתיב היעד מכיל תווים לא חוקיים.")
        parts.append(part)
    return "/".join(parts)


def sanitize_zip_member_path(path: str) -> Optional[str]:
    """
    מנקה נתיב של קובץ מתוך ZIP ומחזיר אותו, או ``None`` אם יש לדלג עליו.

    זו ההגנה מפני Zip-Slip: ארכיון יכול להכיל נתיב כמו ``../../secrets``,
    ובלעדיה הוא היה נכתב מחוץ לתיקיית היעד שהמשתמש בחר.
    """
    if not path:
        return None
    candidate = path.replace("\\", "/").strip()
    if not candidate or candidate.endswith("/"):
        return None
    # נתיב מוחלט בתוך ארכיון אינו מסוכן כאן (היעד הוא git tree, לא דיסק),
    # ולכן מנרמלים אותו במקום להשמיט את הקובץ בשקט.
    candidate = candidate.lstrip("/")
    if not candidate or re.match(r"^[A-Za-z]:", candidate):
        return None

    parts: List[str] = []
    for part in candidate.split("/"):
        if not part or part == ".":
            continue
        if part == "..":
            return None
        if "\x00" in part:
            return None
        parts.append(part)
    if not parts:
        return None
    return "/".join(parts)


class _ReporterProto(Protocol):
    """Protocol for activity reporter."""
    def report_activity(self, user_id: int) -> None: ...


class _MetricProto(Protocol):
    """Protocol for Prometheus Counter metric."""
    def labels(self, **labelkwargs) -> _MetricProto: ...
    def inc(self, amount: float = 1) -> None: ...


class DocumentHandler:
    """אחראי על טיפול בכל המסלולים של קבצים שמגיעים לבוט."""

    def __init__(
        self,
        notify_admins: Callable[[ContextTypes.DEFAULT_TYPE, str], Awaitable[None]],
        get_reporter: Callable[[], Optional[_ReporterProto]],
        log_user_activity: Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[None]],
        encodings_to_try: Sequence[str] | Callable[[], Sequence[str]],
        emit_event: Callable[..., object] | None,
        errors_total: Optional[_MetricProto],
    ) -> None:
        self._notify_admins = notify_admins
        self._get_reporter = get_reporter
        self._log_user_activity = log_user_activity
        self._encodings_provider: Callable[[], Sequence[str]] | None = (
            encodings_to_try if callable(encodings_to_try) else None
        )
        if callable(encodings_to_try):
            try:
                initial_encodings: Sequence[str] = encodings_to_try()
            except Exception as exc:
                logger.debug("Dynamic encoding provider failed during init: %s", exc)
                initial_encodings = ()
        else:
            initial_encodings = encodings_to_try

        self._encodings_to_try = self._normalize_encodings(initial_encodings)
        if not self._encodings_to_try:
            # מנע מצב שבו אין קידודים בכלל
            self._encodings_to_try = ("utf-8",)
        self._last_encodings_attempted = self._encodings_to_try
        self._emit_event = emit_event
        self._errors_total = errors_total
        self._files_facade: Optional[Any] = None
        self._files_facade_initialized = False

    @staticmethod
    def _normalize_encodings(values: Sequence[str] | Iterable[str]) -> tuple[str, ...]:
        cleaned: list[str] = []
        for value in values:
            if not value:
                continue
            try:
                text = str(value).strip()
            except Exception:
                continue
            if not text:
                continue
            cleaned.append(text)
        return tuple(cleaned)

    def _current_encodings(self) -> tuple[str, ...]:
        provider = self._encodings_provider
        if provider is not None:
            try:
                resolved = self._normalize_encodings(provider())
            except Exception as exc:
                logger.debug("Dynamic encoding provider failed: %s", exc)
            else:
                if resolved:
                    self._encodings_to_try = resolved
                    return resolved
        return self._encodings_to_try

    def _resolve_files_facade(self) -> Optional[Any]:
        if self._files_facade_initialized:
            return self._files_facade
        self._files_facade_initialized = True
        try:
            from src.infrastructure.composition import get_files_facade  # type: ignore
        except Exception as exc:
            logger.debug("Files facade unavailable: %s", exc)
            self._files_facade = None
            return None
        try:
            self._files_facade = get_files_facade()
        except Exception as exc:
            logger.warning("Failed to initialize files facade: %s", exc)
            self._files_facade = None
        return self._files_facade

    def _save_code_snippet(
        self,
        *,
        user_id: int,
        file_name: str,
        language: str,
        content: str,
        description: str = "",
        tags: Optional[List[str]] = None,
    ) -> bool:
        if self._save_code_snippet_via_facade(
            user_id=user_id,
            file_name=file_name,
            language=language,
            content=content,
            description=description,
            tags=tags,
        ):
            return True
        return False

    def _save_code_snippet_via_facade(
        self,
        *,
        user_id: int,
        file_name: str,
        language: str,
        content: str,
        description: str = "",
        tags: Optional[List[str]] = None,
    ) -> bool:
        facade = self._resolve_files_facade()
        if facade is None:
            return False
        try:
            return bool(
                facade.save_code_snippet(  # type: ignore[attr-defined]
                    user_id=user_id,
                    file_name=file_name,
                    code=content,
                    programming_language=language,
                    description=description,
                    tags=tags,
                )
            )
        except Exception as exc:
            logger.warning("FilesFacade save_code_snippet failed: %s", exc)
            return False

    def _save_large_file(
        self,
        *,
        user_id: int,
        file_name: str,
        language: str,
        content: str,
        file_size: int,
        lines_count: int,
    ) -> bool:
        if self._save_large_file_via_facade(
            user_id=user_id,
            file_name=file_name,
            language=language,
            content=content,
            file_size=file_size,
            lines_count=lines_count,
        ):
            return True
        return False

    def _save_large_file_via_facade(
        self,
        *,
        user_id: int,
        file_name: str,
        language: str,
        content: str,
        file_size: int,
        lines_count: int,
    ) -> bool:
        facade = self._resolve_files_facade()
        if facade is None:
            return False
        try:
            return bool(
                facade.save_large_file(  # type: ignore[attr-defined]
                    user_id=user_id,
                    file_name=file_name,
                    content=content,
                    programming_language=language,
                    file_size=file_size,
                    lines_count=lines_count,
                )
            )
        except Exception as exc:
            logger.warning("FilesFacade save_large_file failed: %s", exc)
            return False

    def _get_latest_version_entry(self, user_id: int, file_name: str) -> Optional[dict]:
        return self._get_latest_version_via_facade(user_id, file_name)

    def _get_large_file_entry(self, user_id: int, file_name: str) -> Optional[dict]:
        return self._get_large_file_via_facade(user_id, file_name)

    def _get_latest_version_via_facade(self, user_id: int, file_name: str) -> Optional[dict]:
        facade = self._resolve_files_facade()
        if facade is None:
            return None
        try:
            doc = facade.get_latest_version(user_id, file_name)  # type: ignore[attr-defined]
            return doc or None
        except Exception:
            return None

    def _get_large_file_via_facade(self, user_id: int, file_name: str) -> Optional[dict]:
        facade = self._resolve_files_facade()
        if facade is None:
            return None
        try:
            doc = facade.get_large_file(user_id, file_name)  # type: ignore[attr-defined]
            return doc or None
        except Exception:
            return None

    def _save_selected_repo(self, user_id: int, repo_full: str) -> bool:
        return self._save_selected_repo_via_facade(user_id, repo_full)

    def _save_selected_repo_via_facade(self, user_id: int, repo_full: str) -> bool:
        facade = self._resolve_files_facade()
        if facade is None:
            return False
        try:
            logger.debug("Trying to save selected repo via FilesFacade for %s", repo_full)
            return bool(facade.save_selected_repo(user_id, repo_full))  # type: ignore[attr-defined]
        except Exception as exc:
            logger.warning("FilesFacade save_selected_repo failed: %s", exc)
            return False

    async def handle_document(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """נתיב ראשי לטיפול בקובץ שנשלח."""

        logger.info("DEBUG: upload_mode = %s", context.user_data.get("upload_mode"))
        logger.info("DEBUG: waiting_for_github_upload = %s", context.user_data.get("waiting_for_github_upload"))

        upload_mode = context.user_data.get("upload_mode")

        if upload_mode == "github_restore_zip_to_repo":
            await self._handle_github_restore_zip_to_repo(update, context)
            return

        if upload_mode == "github_create_repo_from_zip":
            await self._handle_github_create_repo_from_zip(update, context)
            return

        if upload_mode == "github_zip_to_folder":
            await self._handle_github_zip_to_folder(update, context)
            return

        if context.user_data.get("waiting_for_github_upload") or upload_mode == "github":
            await self._handle_github_direct_upload(update, context)
            return

        if upload_mode == "zip_import":
            await self._handle_zip_import(update, context)
            return

        if upload_mode == "zip_create":
            await self._handle_zip_create(update, context)
            return

        await self._log_user_activity(update, context)
        await self._handle_textual_file(update, context)

    async def _handle_github_restore_zip_to_repo(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        try:
            document = update.message.document
            user_id = update.effective_user.id
            logger.info(
                "GitHub restore-to-repo ZIP received: file_name=%s, size=%s",
                document.file_name,
                document.file_size,
            )
            await update.message.reply_text("⏳ מוריד קובץ ZIP...")
            file = await context.bot.get_file(document.file_id)
            buf = BytesIO()
            try:
                await file.download_to_memory(buf)
                buf.seek(0)
                if not zipfile.is_zipfile(buf):
                    await update.message.reply_text("❌ הקובץ שהועלה אינו ZIP תקין.")
                    return

                # חשוב: סגירה דטרמיניסטית של ה-ZIP כדי להימנע מ-Unraisable Exception בזמן GC
                with zipfile.ZipFile(buf, "r") as zf:
                    all_names = [n for n in zf.namelist() if not n.endswith("/")]
                    members = [
                        n
                        for n in all_names
                        if not (n.startswith("__MACOSX/") or n.split("/")[-1].startswith("._"))
                    ]
                    common_root = detect_zip_common_root(zf.namelist())

                    def strip_root(path: str) -> str:
                        if common_root and path.startswith(common_root + "/"):
                            return path[len(common_root) + 1 :]
                        return path

                    files: List[tuple[str, bytes]] = []
                    for name in members:
                        raw = zf.read(name)
                        clean = strip_root(name)
                        if clean:
                            files.append((clean, raw))
                if not files:
                    await update.message.reply_text("❌ לא נמצאו קבצים בתוך ה-ZIP")
                    return
            finally:
                try:
                    buf.close()
                except Exception:
                    pass

            from github import Github
            from github.InputGitTreeElement import InputGitTreeElement

            github_handler = context.bot_data.get("github_handler")
            session = github_handler.get_user_session(user_id)
            token = github_handler.get_user_token(user_id)
            repo_full = session.get("selected_repo")
            if not (token and repo_full):
                await update.message.reply_text("❌ אין טוקן או ריפו נבחר")
                return

            expected_repo_full = context.user_data.get("zip_restore_expected_repo_full")
            repo_full_effective = expected_repo_full or repo_full
            if expected_repo_full and expected_repo_full != repo_full:
                logger.warning(
                    "[restore_zip] Target mismatch: expected=%s, got=%s. Proceeding with expected (locked) target.",
                    expected_repo_full,
                    repo_full,
                )
                try:
                    await update.message.reply_text(
                        f"⚠️ נמצא פער בין היעד הנוכחי ({repo_full}) ליעד הנעול. נשתמש ביעד הנעול: {expected_repo_full}"
                    )
                except Exception:
                    pass
            if not expected_repo_full:
                try:
                    context.user_data["zip_restore_expected_repo_full"] = repo_full
                except Exception:
                    pass

            g = Github(token)
            try:
                repo = g.get_repo(repo_full_effective)
            except Exception as err:
                logger.exception("[restore_zip] Locked target not accessible: %s", err)
                fallback_used = False
                if repo_full and repo_full != repo_full_effective:
                    try:
                        expected_owner = (expected_repo_full or repo_full_effective).split("/")[0]
                        current_owner = repo_full.split("/")[0]
                    except Exception:
                        expected_owner = None
                        current_owner = None
                    if expected_owner and current_owner and current_owner == expected_owner:
                        try:
                            await update.message.reply_text(
                                f"⚠️ היעד הנעול {repo_full_effective} לא נגיש. מנסה להשתמש ביעד הנוכחי {repo_full} (אותו בעלים)."
                            )
                        except Exception:
                            pass
                        try:
                            repo = g.get_repo(repo_full)
                            repo_full_effective = repo_full
                            fallback_used = True
                        except Exception as err2:
                            logger.exception("[restore_zip] Fallback to current repo failed: %s", err2)
                if "repo" not in locals():
                    await update.message.reply_text(
                        f"❌ היעד {repo_full_effective} לא נגיש ואין נפילה בטוחה. עצירה. אנא בחרו ריפו מחדש."
                    )
                    raise
            target_branch = repo.default_branch or "main"
            purge_first = bool(context.user_data.get("github_restore_zip_purge"))
            await update.message.reply_text(
                ("🧹 מנקה קבצים קיימים...\n" if purge_first else "")
                + f"📤 מעלה {len(files)} קבצים לריפו {repo_full_effective} (branch: {target_branch})..."
            )
            base_ref = repo.get_git_ref(f"heads/{target_branch}")
            base_commit = repo.get_git_commit(base_ref.object.sha)
            base_tree = base_commit.tree
            new_tree_elements: List[InputGitTreeElement] = []
            text_exts = (
                ".md",
                ".txt",
                ".json",
                ".yml",
                ".yaml",
                ".xml",
                ".py",
                ".js",
                ".ts",
                ".tsx",
                ".css",
                ".scss",
                ".html",
                ".sh",
                ".gitignore",
            )
            for path, raw in files:
                is_text = path.lower().endswith(text_exts)
                try:
                    if is_text:
                        text = raw.decode("utf-8")
                        blob = repo.create_git_blob(text, "utf-8")
                    else:
                        b64 = base64.b64encode(raw).decode("ascii")
                        blob = repo.create_git_blob(b64, "base64")
                except Exception:
                    b64 = base64.b64encode(raw).decode("ascii")
                    blob = repo.create_git_blob(b64, "base64")
                elem = InputGitTreeElement(path=path, mode="100644", type="blob", sha=blob.sha)
                new_tree_elements.append(elem)
            if purge_first:
                new_tree = repo.create_git_tree(new_tree_elements)
            else:
                new_tree = repo.create_git_tree(new_tree_elements, base_tree)
            commit_message = "Restore from ZIP via bot: replace " + ("with purge" if purge_first else "update only")
            new_commit = repo.create_git_commit(commit_message, new_tree, [base_commit])
            base_ref.edit(new_commit.sha)
            logger.info(
                "[restore_zip] Restore commit created: %s, files_added=%s, purge=%s",
                new_commit.sha,
                len(new_tree_elements),
                purge_first,
            )
            await update.message.reply_text("✅ השחזור הועלה לריפו בהצלחה")
        except Exception as err:
            logger.exception("GitHub restore-to-repo failed: %s", err)
            await update.message.reply_text(f"❌ שגיאה בשחזור לריפו: {err}")
            await self._maybe_alert_oom(context, err, "בשחזור ZIP לריפו")
        finally:
            context.user_data["upload_mode"] = None
            context.user_data.pop("github_restore_zip_purge", None)
            context.user_data.pop("zip_restore_expected_repo_full", None)

    def _parse_zip_for_import(self, buf: BytesIO):
        """מפרסר את ה-ZIP ומחזיר ``(files, common_root, member_count)``.

        פונקציה חוסמת (CPU/זיכרון) שנועדה לרוץ ב-``asyncio.to_thread`` בלבד — אין
        לגעת בלולאת האירועים. ``files`` היא רשימת ``(path נקי, bytes)`` לאחר הסרת
        תיקיית שורש משותפת. ``member_count`` הוא מספר הקבצים ב-ZIP (לפני ניקוי).
        """
        buf.seek(0)
        with zipfile.ZipFile(buf, "r") as zf:
            names_all = zf.namelist()
            members = [
                n
                for n in names_all
                if not n.endswith("/")
                and not n.startswith("__MACOSX/")
                and not n.split("/")[-1].startswith("._")
            ]
            # הגנה מפני "פצצת ZIP": אכיפת מגבלות (מספר קבצים + גודל לא-דחוס) לפני
            # קריאת התוכן לזיכרון, כדי שארכיון זדוני לא ימוטט את התהליך.
            if len(members) > MAX_IMPORT_ZIP_MEMBERS:
                raise ValueError(
                    f"הארכיון מכיל יותר מדי קבצים ({len(members)} > {MAX_IMPORT_ZIP_MEMBERS})."
                )
            total_uncompressed = 0
            for name in members:
                try:
                    entry_size = int(zf.getinfo(name).file_size)
                except Exception:
                    entry_size = 0
                if entry_size > MAX_IMPORT_FILE_UNCOMPRESSED_BYTES:
                    raise ValueError(f"קובץ בארכיון גדול מדי (לא דחוס): {name}")
                total_uncompressed += entry_size
                if total_uncompressed > MAX_IMPORT_TOTAL_UNCOMPRESSED_BYTES:
                    raise ValueError("סך התוכן הלא-דחוס בארכיון חורג מהמגבלה המותרת.")
            common_root = detect_zip_common_root(names_all)

            def strip_root(path: str) -> str:
                if common_root and path.startswith(common_root + "/"):
                    return path[len(common_root) + 1 :]
                return path

            files = []
            for name in members:
                data = zf.read(name)
                clean = strip_root(name)
                if clean:
                    files.append((clean, data))
        return files, common_root, len(members)

    def _gh_create_repo(self, token: str, repo_name: str, private: bool):
        """יוצר ריפו חדש ב-GitHub. פונקציה חוסמת (רשת) ל-``asyncio.to_thread``."""
        from github import Github

        g = Github(token)
        user = g.get_user()
        return user.create_repo(name=repo_name, private=private, auto_init=False)

    def _gh_upload_files(self, repo, files) -> int:
        """מעלה את הקבצים לריפו החדש ומחזיר את מספר הקבצים שהוזנו.

        פונקציה חוסמת (N קריאות רשת) שנועדה לרוץ ב-``asyncio.to_thread`` בלבד.
        משמרת את ההתנהגות המקורית: לריפו ריק (ללא base commit) יוצרים כל קובץ דרך
        Contents API; לריפו עם היסטוריה בונים blobs+tree+commit.
        """
        from github.GithubException import GithubException

        target_branch = repo.default_branch or "main"
        base_ref = None
        base_commit = None
        base_tree = None
        try:
            base_ref = repo.get_git_ref(f"heads/{target_branch}")
            base_commit = repo.get_git_commit(base_ref.object.sha)
            base_tree = base_commit.tree
        except GithubException as exc:
            # ריפו חדש וריק מחזיר 404/409 מ-get_git_ref — זה המצב הצפוי. כל סטטוס
            # אחר (הרשאות/רייט-לימיט/שגיאת שרת) הוא כשל אמיתי שאין לבלוע בשקט.
            status = getattr(exc, "status", None)
            if status is not None and status not in (404, 409):
                raise
            logger.info("No base ref found for new repo (expected for empty repo): %s", exc)

        if base_commit is None:
            created_count = 0
            for path, raw in files:
                # כשל API ביצירת קובץ מתפשט (ולא נבלע) כדי שלא נדווח על ייבוא מוצלח
                # בעוד שחלק מהקבצים נכשלו; טיפול ה-UTF-8 מול בינארי נשמר.
                try:
                    text = raw.decode("utf-8")
                    repo.create_file(
                        path=path,
                        message="Initial import from ZIP via bot",
                        content=text,
                        branch=target_branch,
                    )
                except UnicodeDecodeError:
                    repo.create_file(
                        path=path,
                        message="Initial import from ZIP via bot (binary)",
                        content=raw,
                        branch=target_branch,
                    )
                created_count += 1
            return created_count

        from github.InputGitTreeElement import InputGitTreeElement

        text_exts = (
            ".md",
            ".txt",
            ".json",
            ".yml",
            ".yaml",
            ".xml",
            ".py",
            ".js",
            ".ts",
            ".tsx",
            ".css",
            ".scss",
            ".html",
            ".sh",
            ".gitignore",
        )
        new_tree_elems: List[InputGitTreeElement] = []
        for path, raw in files:
            try:
                if path.lower().endswith(text_exts):
                    blob = repo.create_git_blob(raw.decode("utf-8"), "utf-8")
                else:
                    blob = repo.create_git_blob(base64.b64encode(raw).decode("ascii"), "base64")
            except Exception:
                blob = repo.create_git_blob(base64.b64encode(raw).decode("ascii"), "base64")
            new_tree_elems.append(InputGitTreeElement(path=path, mode="100644", type="blob", sha=blob.sha))
        new_tree = repo.create_git_tree(new_tree_elems, base_tree)
        commit_message = "Initial import from ZIP via bot"
        parents = [base_commit]
        new_commit = repo.create_git_commit(commit_message, new_tree, parents)
        base_ref.edit(new_commit.sha)
        return len(new_tree_elems)

    async def _handle_github_create_repo_from_zip(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        try:
            document = update.message.document
            user_id = update.effective_user.id
            logger.info(
                "GitHub create-repo-from-zip received: file_name=%s, size=%s",
                document.file_name,
                document.file_size,
            )
            await update.message.reply_text("⏳ מוריד קובץ ZIP...")
            tg_file = await context.bot.get_file(document.file_id)
            buf = BytesIO()
            await tg_file.download_to_memory(buf)
            buf.seek(0)
            if not zipfile.is_zipfile(buf):
                await update.message.reply_text("❌ הקובץ שהועלה אינו ZIP תקין.")
                return
            # פרסור ה-ZIP (CPU/זיכרון כבד) מחוץ ל-event loop כדי לא לחסום אותו
            files, common_root, member_count = await asyncio.to_thread(
                self._parse_zip_for_import, buf
            )
            if not member_count:
                await update.message.reply_text("❌ ה‑ZIP ריק.")
                return

            repo_name = context.user_data.get("new_repo_name")
            if not repo_name:
                base_guess = None
                if common_root:
                    base_guess = common_root
                elif document.file_name:
                    base_guess = os.path.splitext(os.path.basename(document.file_name))[0]
                if not base_guess:
                    base_guess = f"repo-{int(time.time())}"
                repo_name = re.sub(r"\s+", "-", base_guess)
                repo_name = re.sub(r"[^A-Za-z0-9._-]", "-", repo_name).strip(".-_") or f"repo-{int(time.time())}"

            github_handler = context.bot_data.get("github_handler")
            token = github_handler.get_user_token(user_id) if github_handler else None
            if not token:
                await update.message.reply_text("❌ אין טוקן GitHub. שלח /github כדי להתחבר.")
                return
            await update.message.reply_text(
                f"📦 יוצר ריפו חדש: <code>{repo_name}</code>", parse_mode=ParseMode.HTML
            )
            # יצירת הריפו ב-GitHub (רשת) מחוץ ל-event loop
            repo = await asyncio.to_thread(
                self._gh_create_repo,
                token,
                repo_name,
                bool(context.user_data.get("new_repo_private", True)),
            )
            repo_full = repo.full_name
            # עדכן סשן בזיכרון תמיד (הריפו נוצר בגיטהאב בפועל),
            # ובצע ניקוי מצבים תלויים כמו _apply_repo_selection
            try:
                sess = github_handler.get_user_session(user_id)
                sess["selected_repo"] = repo_full
                sess["selected_folder"] = None
            except Exception as err:
                logger.warning("Failed updating github session after repo creation: %s", err)
            # נקה מצבים ישנים ב-context כדי שפעולות הבאות ישתמשו בריפו החדש
            for _key in (
                "upload_target_folder", "upload_target_branch",
                "waiting_for_manual_repo", "zip_restore_expected_repo_full",
                "github_restore_zip_purge", "pending_repo_restore_zip_path",
                "repos", "repos_cache_time",
            ):
                context.user_data.pop(_key, None)
            # שמור למסד נתונים (ריפו + איפוס תיקיית יעד)
            # _save_selected_repo בולע exceptions ומחזיר False בכישלון,
            # לכן בודקים את ערך ההחזרה ולא מסתמכים על try/except
            if self._save_selected_repo(user_id, repo_full):
                try:
                    facade = self._resolve_files_facade()
                    if facade is not None and hasattr(facade, "save_selected_folder"):
                        facade.save_selected_folder(user_id, None)
                except Exception as err:
                    logger.warning("Failed saving selected folder to DB: %s", err)
            else:
                logger.warning("Failed saving selected repo to DB for user %s", user_id)

            await update.message.reply_text("📤 מעלה את קבצי ה‑ZIP לריפו החדש...")
            # העלאת הקבצים ל-GitHub (N קריאות רשת) מחוץ ל-event loop כדי לא לחסום אותו
            created_count = await asyncio.to_thread(self._gh_upload_files, repo, files)
            await update.message.reply_text(
                f"✅ נוצר ריפו חדש והוזנו {created_count} קבצים\n🔗 <a href=\"https://github.com/{repo_full}\">{repo_full}</a>",
                parse_mode=ParseMode.HTML,
            )
        except Exception as err:
            logger.exception("Create new repo from ZIP failed: %s", err)
            await update.message.reply_text(f"❌ שגיאה ביצירת ריפו מ‑ZIP: {err}")
            await self._maybe_alert_oom(context, err, "ביצירת ריפו מ‑ZIP")
        finally:
            context.user_data["upload_mode"] = None
            for key in ("new_repo_name", "new_repo_private"):
                context.user_data.pop(key, None)

    def _gh_upload_files_to_folder(self, repo, files, prefix: str) -> int:
        """
        פורס קבצים לתוך תיקייה בריפו קיים, בקומיט אחד.

        פונקציה חוסמת (רשת) שנועדה לרוץ ב-``asyncio.to_thread`` בלבד.
        הקבצים נוספים על גבי העץ הקיים, ולכן שאר הריפו אינו מושפע: קובץ
        קיים באותו נתיב מוחלף, וכל השאר נשאר כמו שהוא.
        """
        from github.InputGitTreeElement import InputGitTreeElement

        target_branch = repo.default_branch or "main"
        base_ref = repo.get_git_ref(f"heads/{target_branch}")
        base_commit = repo.get_git_commit(base_ref.object.sha)
        base_tree = base_commit.tree

        text_exts = (
            ".md", ".txt", ".json", ".yml", ".yaml", ".xml", ".py", ".js",
            ".ts", ".tsx", ".css", ".scss", ".html", ".sh", ".gitignore",
        )

        elements: List[Any] = []
        for path, raw in files:
            full_path = f"{prefix}/{path}" if prefix else path
            is_text = full_path.lower().endswith(text_exts)
            try:
                if is_text:
                    blob = repo.create_git_blob(raw.decode("utf-8"), "utf-8")
                else:
                    blob = repo.create_git_blob(
                        base64.b64encode(raw).decode("ascii"), "base64"
                    )
            except Exception:
                blob = repo.create_git_blob(
                    base64.b64encode(raw).decode("ascii"), "base64"
                )
            elements.append(
                InputGitTreeElement(path=full_path, mode="100644", type="blob", sha=blob.sha)
            )

        # base_tree תמיד מועבר: הפריסה מוסיפה על הקיים ולא מחליפה את הריפו
        new_tree = repo.create_git_tree(elements, base_tree)
        commit_message = f"Deploy ZIP contents to {prefix or 'root'} via bot"
        new_commit = repo.create_git_commit(commit_message, new_tree, [base_commit])
        base_ref.edit(new_commit.sha)
        logger.info(
            "[zip_to_folder] Commit created: %s, files=%s, prefix=%s",
            new_commit.sha, len(elements), prefix,
        )
        return len(elements)

    async def _handle_github_zip_to_folder(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """פורס את תוכן ה-ZIP לתוך תיקייה שנבחרה בריפו קיים."""
        try:
            document = update.message.document
            user_id = update.effective_user.id

            # היעד נקבע מראש בתפריט ונשמר, כדי שלא ישתנה בין הבחירה לשליחת הקובץ
            try:
                prefix = normalize_repo_folder(
                    context.user_data.get("zip_to_folder_target") or ""
                )
            except ValueError as err:
                await update.message.reply_text(f"❌ נתיב היעד אינו תקין: {err}")
                return
            if not prefix:
                await update.message.reply_text(
                    "❌ לא נבחרה תיקיית יעד. חזור לתפריט ובחר תיקייה."
                )
                return

            github_handler = context.bot_data.get("github_handler")
            session = github_handler.get_user_session(user_id) if github_handler else {}
            token = github_handler.get_user_token(user_id) if github_handler else None
            # היעד הנעול מנצח, כדי שהחלפת ריפו באמצע לא תשלח קבצים למקום אחר
            repo_full = context.user_data.get("zip_to_folder_repo") or session.get("selected_repo")
            if not (token and repo_full):
                await update.message.reply_text("❌ אין טוקן או ריפו נבחר")
                return

            logger.info(
                "GitHub zip-to-folder received: file_name=%s, size=%s, repo=%s, folder=%s",
                document.file_name, document.file_size, repo_full, prefix,
            )

            await update.message.reply_text("⏳ מוריד קובץ ZIP...")
            tg_file = await context.bot.get_file(document.file_id)
            buf = BytesIO()
            try:
                await tg_file.download_to_memory(buf)
                buf.seek(0)
                if not zipfile.is_zipfile(buf):
                    await update.message.reply_text("❌ הקובץ שהועלה אינו ZIP תקין.")
                    return
                # פרסור כבד מחוץ ל-event loop; כולל מגבלות נגד "פצצת ZIP"
                files, _common_root, member_count = await asyncio.to_thread(
                    self._parse_zip_for_import, buf
                )
            finally:
                try:
                    buf.close()
                except Exception:
                    pass

            if not member_count or not files:
                await update.message.reply_text("❌ לא נמצאו קבצים בתוך ה-ZIP")
                return

            # הגנת Zip-Slip: נתיב שמנסה לצאת מהתיקייה מדולג ולא נכתב לריפו
            safe_files: List[tuple[str, bytes]] = []
            skipped: List[str] = []
            for path, raw in files:
                clean = sanitize_zip_member_path(path)
                if clean is None:
                    skipped.append(path)
                    continue
                safe_files.append((clean, raw))

            if skipped:
                logger.warning(
                    "[zip_to_folder] Skipped %s unsafe path(s), first: %s",
                    len(skipped), skipped[:3],
                )
            if not safe_files:
                await update.message.reply_text(
                    "❌ כל הנתיבים ב-ZIP נדחו מטעמי בטיחות (נתיבים מוחלטים או '..')."
                )
                return

            g_repo = await asyncio.to_thread(self._gh_get_repo, token, repo_full)
            notice = ""
            if skipped:
                notice = f"\n⚠️ דולגו {len(skipped)} נתיבים לא בטוחים (מכילים '..' או נתיב מוחלט)."
            await update.message.reply_text(
                f"📤 מעלה {len(safe_files)} קבצים אל <code>{html_escape(repo_full)}/{html_escape(prefix)}</code>...{notice}",
                parse_mode=ParseMode.HTML,
            )

            count = await asyncio.to_thread(
                self._gh_upload_files_to_folder, g_repo, safe_files, prefix
            )

            folder_url = f"https://github.com/{repo_full}/tree/{g_repo.default_branch or 'main'}/{prefix}"
            await update.message.reply_text(
                f"✅ נפרסו {count} קבצים לתיקייה\n"
                f"🔗 <a href=\"{html_escape(folder_url)}\">{html_escape(repo_full)}/{html_escape(prefix)}</a>",
                parse_mode=ParseMode.HTML,
            )
        except Exception as err:
            logger.exception("ZIP to folder failed: %s", err)
            await update.message.reply_text(f"❌ שגיאה בפריסת ZIP לתיקייה: {err}")
            await self._maybe_alert_oom(context, err, "בפריסת ZIP לתיקייה")
        finally:
            context.user_data["upload_mode"] = None
            for key in ("zip_to_folder_target", "zip_to_folder_repo"):
                context.user_data.pop(key, None)

    def _gh_get_repo(self, token: str, repo_full: str):
        """מחזיר אובייקט ריפו. פונקציה חוסמת (רשת) ל-``asyncio.to_thread``."""
        from github import Github

        return Github(token).get_repo(repo_full)

    async def _handle_github_direct_upload(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        github_handler = context.bot_data.get("github_handler")
        if github_handler:
            await github_handler.handle_file_upload(update, context)

    async def _handle_zip_import(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        try:
            document = update.message.document
            user_id = update.effective_user.id
            logger.info(
                "ZIP import received: file_name=%s, mime_type=%s, size=%s",
                document.file_name,
                document.mime_type,
                document.file_size,
            )
            await update.message.reply_text("⏳ מוריד קובץ ZIP...")
            file = await context.bot.get_file(document.file_id)
            buf = BytesIO()
            await file.download_to_memory(buf)
            buf.seek(0)
            tmp_dir = tempfile.gettempdir()
            safe_name = (document.file_name or "repo.zip")
            if not safe_name.lower().endswith(".zip"):
                safe_name += ".zip"
            tmp_path = os.path.join(tmp_dir, safe_name)
            with open(tmp_path, "wb") as fh:
                fh.write(buf.getvalue())
            if not zipfile.is_zipfile(tmp_path):
                logger.warning("Uploaded file is not a valid ZIP: %s", tmp_path)
                await update.message.reply_text("❌ הקובץ שהועלה אינו ZIP תקין.")
                return

            repo_tag: List[str] = []
            try:
                with zipfile.ZipFile(tmp_path, "r") as zf:
                    md = json.loads(zf.read("metadata.json"))
                    if md.get("repo"):
                        repo_tag = [f"repo:{md['repo']}"]
            except Exception:
                repo_tag = []

            if not repo_tag:
                try:
                    def _parse_repo_full_from_label(label: str) -> str:
                        if not isinstance(label, str) or not label:
                            return ""
                        base = label.strip().strip("/").strip()
                        base = re.sub(r"\.zip$", "", base, flags=re.IGNORECASE)
                        parts = base.split("-") if "-" in base else [base]
                        if len(parts) < 2:
                            return ""
                        owner = parts[0]
                        tail = parts[1:]
                        while tail:
                            last = tail[-1]
                            is_sha = bool(re.fullmatch(r"[0-9a-fA-F]{7,40}", last))
                            is_branch_hint = last.lower() in {"main", "master", "develop", "dev", "release"}
                            if is_sha or is_branch_hint:
                                tail = tail[:-1]
                            else:
                                break
                        if not tail:
                            return ""
                        repo_name = "-".join(tail)
                        if not owner or not repo_name:
                            return ""
                        return f"{owner}/{repo_name}"

                    guessed_full = ""
                    with zipfile.ZipFile(tmp_path, "r") as zf:
                        all_names = zf.namelist()
                        top_levels = {
                            n.split("/", 1)[0]
                            for n in all_names
                            if "/" in n and not n.startswith("__MACOSX/")
                        }
                        common_root = list(top_levels)[0] if len(top_levels) == 1 else None
                    if common_root:
                        guessed_full = _parse_repo_full_from_label(common_root)
                    if not guessed_full and safe_name:
                        name_wo_ext = os.path.splitext(os.path.basename(safe_name))[0]
                        guessed_full = _parse_repo_full_from_label(name_wo_ext)
                    if guessed_full:
                        repo_tag = [f"repo:{guessed_full}"]
                except Exception:
                    repo_tag = []

            results = backup_manager.restore_from_backup(
                user_id=user_id,
                backup_path=tmp_path,
                overwrite=True,
                purge=False,
                extra_tags=repo_tag,
            )
            restored = results.get("restored_files", 0)
            errors = results.get("errors", [])
            if errors:
                preview = "\n".join([str(err) for err in errors[:3]])
                msg = (
                    f"⚠️ הייבוא הושלם חלקית: {restored} קבצים נשמרו\n"
                    f"שגיאות: {len(errors)}\n"
                    f"דוגמאות:\n{preview}"
                )
            else:
                msg = f"✅ יובאו {restored} קבצים בהצלחה"
            await update.message.reply_text(msg)
        except Exception as err:
            logger.exception("ZIP import failed: %s", err)
            await update.message.reply_text(f"❌ שגיאה בייבוא ZIP: {err}")
        finally:
            context.user_data["upload_mode"] = None

    async def _handle_zip_create(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        try:
            document = update.message.document
            user_id = update.effective_user.id
            logger.info(
                "ZIP create mode: received file for bundle: %s (%s bytes)",
                document.file_name,
                document.file_size,
            )
            items = context.user_data.get("zip_create_items")
            if items is None:
                items = []
                context.user_data["zip_create_items"] = items
            # אכיפת מגבלות מוקדמת — לפני ההורדה לזיכרון (הגנה מ-DoS/זיכרון): מספר קבצים + גודל מוצהר
            from utils import ZIP_CREATE_MAX_FILES, ZIP_CREATE_MAX_TOTAL_BYTES
            limit_mb = ZIP_CREATE_MAX_TOTAL_BYTES // (1024 * 1024)
            if len(items) >= ZIP_CREATE_MAX_FILES:
                await update.message.reply_text(
                    f"⚠️ הגעת למקסימום {ZIP_CREATE_MAX_FILES} קבצים ל-ZIP. לחצ/י 'סיום' כדי ליצור."
                )
                return
            current_total = sum(len(it.get("bytes") or b"") for it in items)
            incoming_size = int(getattr(document, "file_size", 0) or 0)
            if current_total + incoming_size > ZIP_CREATE_MAX_TOTAL_BYTES:
                await update.message.reply_text(
                    f"⚠️ הקובץ לא נוסף — חריגה מהמגבלה של {limit_mb}MB לכלל ה-ZIP."
                )
                return
            # הורדה רק לאחר שהמגבלות המוקדמות עברו
            file = await context.bot.get_file(document.file_id)
            buf = BytesIO()
            await file.download_to_memory(buf)
            raw = buf.getvalue()
            # אימות סופי לפי הגודל בפועל (למקרה של פער מול file_size המוצהר)
            if current_total + len(raw) > ZIP_CREATE_MAX_TOTAL_BYTES:
                await update.message.reply_text(
                    f"⚠️ הקובץ לא נוסף — חריגה מהמגבלה של {limit_mb}MB לכלל ה-ZIP."
                )
                return
            safe_name = (document.file_name or f"file_{len(items)+1}").strip() or f"file_{len(items)+1}"
            items.append({"filename": safe_name, "bytes": raw})
            await update.message.reply_text(
                f'✅ נוסף: <code>{html_escape(safe_name)}</code> (סה"כ {len(items)} קבצים)',
                parse_mode=ParseMode.HTML,
            )
        except Exception as err:
            logger.exception("zip_create collect failed: %s", err)
            await update.message.reply_text(f"❌ שגיאה בהוספת הקובץ ל‑ZIP: {err}")

    async def _handle_textual_file(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        try:
            document = update.message.document
            user_id = update.effective_user.id
            if document.file_size > 20 * 1024 * 1024:
                await update.message.reply_text(
                    "❌ הקובץ גדול מדי!\n📏 הגודל המקסימלי המותר הוא 20MB"
                )
                return

            await update.message.reply_text("⏳ מוריד את הקובץ...")
            file = await context.bot.get_file(document.file_id)
            file_bytes = BytesIO()
            await file.download_to_memory(file_bytes)
            file_bytes.seek(0)
            raw_bytes = file_bytes.read()

            handled_zip = await self._maybe_store_zip_copy(update, context, document, raw_bytes)
            if handled_zip:
                return

            content, detected_encoding = self._decode_bytes(raw_bytes)
            if content is None:
                attempted = getattr(self, "_last_encodings_attempted", self._current_encodings())
                attempted_display = [str(enc) for enc in attempted if enc]
                logger.error("❌ לא ניתן לקרוא את הקובץ באף קידוד: %s", attempted_display)
                if self._emit_event is not None:
                    try:
                        self._emit_event(
                            "file_read_unreadable",
                            severity="error",
                            attempted_encodings=",".join(attempted_display),
                        )
                    except Exception:
                        pass
                if self._errors_total is not None:
                    try:
                        self._errors_total.labels(code="E_FILE_UNREADABLE").inc()
                    except Exception:
                        pass
                await update.message.reply_text(
                    "❌ לא ניתן לקרוא את הקובץ!\n"
                    + f"📝 ניסיתי את הקידודים: {', '.join(attempted_display)}\n"
                    + "💡 אנא ודא שזהו קובץ טקסט/קוד ולא קובץ בינארי"
                )
                return

            file_name = document.file_name or "untitled.txt"
            # זיהוי שפה חייב לקבל גם את התוכן (למשל block.md עם קוד Python מובהק)
            try:
                from services import code_service  # type: ignore
                language = code_service.detect_language(content or "", file_name)
            except Exception:
                from utils import detect_language_from_filename
                language = detect_language_from_filename(file_name)
            if len(content) > 4096:
                await self._store_large_file(update, context, user_id, file_name, language, content, detected_encoding)
            else:
                await self._store_regular_file(update, context, user_id, file_name, language, content, detected_encoding)

            reporter = self._get_reporter()
            if reporter is not None:
                try:
                    reporter.report_activity(user_id)
                except Exception:
                    pass
        except Exception as err:
            logger.error("שגיאה בטיפול בקובץ: %s", err)
            if self._emit_event is not None:
                try:
                    self._emit_event("file_process_error", severity="error", error=str(err))
                except Exception:
                    pass
            if self._errors_total is not None:
                try:
                    self._errors_total.labels(code="E_FILE_PROCESS").inc()
                except Exception:
                    pass
            await update.message.reply_text("❌ שגיאה בעיבוד הקובץ")

    def _decode_bytes(self, raw_bytes: bytes) -> tuple[Optional[str], Optional[str]]:
        encodings = self._current_encodings()
        self._last_encodings_attempted = encodings

        for encoding in encodings:
            try:
                content = raw_bytes.decode(encoding)
            except UnicodeDecodeError:
                continue
            else:
                logger.info("✅ הקובץ נקרא בהצלחה בקידוד: %s", encoding)
                if self._emit_event is not None:
                    try:
                        self._emit_event("file_read_success", severity="info", encoding=str(encoding))
                    except Exception:
                        pass
                return content, encoding
        return None, None

    async def _maybe_store_zip_copy(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        document,
        raw_bytes: bytes,
    ) -> bool:
        try:
            is_zip_hint = ((document.mime_type or "").lower() == "application/zip") or (
                (document.file_name or "").lower().endswith(".zip")
            )
            is_zip_actual = False
            try:
                is_zip_actual = zipfile.is_zipfile(BytesIO(raw_bytes))
            except Exception:
                is_zip_actual = False
            if not (is_zip_hint and is_zip_actual):
                return False

            # ZIP זוהה — במקום שמירה אוטומטית לגיבוי, בקש מהמשתמש לבחור יעד: סקיל או גיבוי.
            # ה-bytes נשמרים כמו שהם בקובץ זמני; הבחירה בפועל מתבצעת ב-callback (בחירה מפורשת בלבד).
            from utils import (
                stash_pending_zip_bytes,
                cleanup_pending_zip,
                cleanup_stale_pending_zips,
                tg_emoji,
                PENDING_ZIP_TTL_SECONDS,
            )
            from config import config
            import uuid as _uuid

            original_name = document.file_name or "upload.zip"

            # ניקוי עצל: קבצים ממתינים ישנים (שלא נבחרו) — גם על הדיסק וגם ב-user_data.
            # הסריקה סינכרונית (glob+stat) — רצה ב-thread כדי לא לחסום את לולאת האירועים.
            try:
                await asyncio.to_thread(cleanup_stale_pending_zips)
            except Exception:
                pass
            pending = context.user_data.setdefault("pending_zip", {})
            try:
                now_ts = int(datetime.now(timezone.utc).timestamp())
                stale_tokens = [
                    t for t, m in pending.items()
                    if now_ts - int((m or {}).get("ts", 0)) > PENDING_ZIP_TTL_SECONDS
                ]
                for _old in stale_tokens:
                    cleanup_pending_zip((pending.get(_old) or {}).get("path", ""))
                    pending.pop(_old, None)
                # הגבלת מספר ה-ZIP הממתינים למשתמש — הסרת הישנים ביותר מעבר לקיבולת
                MAX_PENDING = 5
                if len(pending) >= MAX_PENDING:
                    oldest = sorted(pending.items(), key=lambda kv: int((kv[1] or {}).get("ts", 0)))
                    for _old, _meta in oldest[: len(pending) - MAX_PENDING + 1]:
                        cleanup_pending_zip((_meta or {}).get("path", ""))
                        pending.pop(_old, None)
            except Exception:
                pass

            token = _uuid.uuid4().hex
            try:
                # כתיבה לדיסק — ב-thread כדי לא לחסום את לולאת האירועים
                path = await asyncio.to_thread(stash_pending_zip_bytes, raw_bytes, token)
            except Exception as err:
                logger.warning("Failed to stash pending ZIP: %s", err)
                return False
            pending[token] = {
                "path": path,
                "original_name": original_name,
                "size": len(raw_bytes),
                "ts": int(datetime.now(timezone.utc).timestamp()),
            }

            # כפתורים: אימוג'י רגיל בלבד — inline keyboard לא תומך ב-custom emoji entities
            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("🧩 סקיל", callback_data=f"zip_route_skill:{token}"),
                    InlineKeyboardButton("📦 גיבוי", callback_data=f"zip_route_backup:{token}"),
                ]
            ])

            def _zip_prompt_text(icon: str) -> str:
                return (
                    f"{icon} קיבלתי קובץ ZIP: <code>{html_escape(original_name)}</code>\n"
                    "איפה לשמור אותו?\n\n"
                    "🧩 <b>בקטגוריית סקילים</b> — קטגוריה מיוחדת לשמירת סקילים בפורמט ZIP\n"
                    "📦 <b>בקטגוריית גיבויים</b> — קטגוריה לשמירת Repo's מגיטהאב בפורמט ZIP "
                    "(אפשר אחר כך לשחזר מהזיפ את כל הריפו בגיטהאב דרך הבוט - בלחיצה)"
                )

            try:
                # אייקון ZIP מותאם (טלגרם פרימיום) — ה-ID מגיע מ-ENV בלבד; בלי ID נופלים ל-📁
                custom_icon = tg_emoji(getattr(config, "CUSTOM_EMOJI_ZIP_ID", None), "📁")
                try:
                    await update.message.reply_text(
                        _zip_prompt_text(custom_icon),
                        reply_markup=keyboard,
                        parse_mode=ParseMode.HTML,
                    )
                except BadRequest:
                    # טלגרם דחתה את ההודעה — אם זה בגלל האימוג'י המותאם (תנאי פרימיום/ID
                    # שנמחק), שולחים שוב עם האימוג'י הרגיל: המשתמש חייב לקבל את ההודעה.
                    if custom_icon == "📁":
                        raise  # אין אימוג'י מותאם בהודעה — הכשל ממקור אחר, אין טעם בניסיון זהה
                    await update.message.reply_text(
                        _zip_prompt_text("📁"),
                        reply_markup=keyboard,
                        parse_mode=ParseMode.HTML,
                    )
                    # מסמנים ומלוגגים רק אחרי שה-fallback עבר — זו ההוכחה שהבעיה הייתה
                    # האימוג'י (BadRequest ממקור אחר היה מפיל גם את השליחה הזו ומתגלגל הלאה)
                    global _custom_emoji_warned
                    if not _custom_emoji_warned:
                        _custom_emoji_warned = True
                        logger.warning("האימוג'י המותאם (CUSTOM_EMOJI_ZIP_ID) נדחה ע\"י טלגרם — נופלים לאימוג'י רגיל")
            except Exception:
                # בלי כפתורים אין דרך לממש את הבחירה — מנקים את הרשומה והקובץ שנוצרו עבור ה-ZIP הזה
                cleanup_pending_zip(path)
                pending.pop(token, None)
                raise
            return True
        except Exception:
            pass
        return False

    async def _store_large_file(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        user_id: int,
        file_name: str,
        language: str,
        content: str,
        detected_encoding: Optional[str],
    ) -> None:
        size_bytes = len(content.encode("utf-8"))
        lines_count = len(content.split("\n"))
        success = self._save_large_file(
            user_id=user_id,
            file_name=file_name,
            language=language,
            content=content,
            file_size=size_bytes,
            lines_count=lines_count,
        )
        if self._emit_event is not None:
            try:
                self._emit_event(
                    "file_saved",
                    severity="info",
                    user_id=int(user_id),
                    language=str(language),
                    size_bytes=int(size_bytes),
                    large=True,
                )
            except Exception:
                pass
        if not success:
            await update.message.reply_text("❌ שגיאה בשמירת הקובץ")
            return

        from utils import get_language_emoji

        emoji = get_language_emoji(language)
        try:
            saved_large = self._get_large_file_entry(user_id, file_name) or {}
            fid = str(saved_large.get("_id") or "")
        except Exception:
            fid = ""
        keyboard = [
            [
                InlineKeyboardButton(
                    "👁️ הצג קוד",
                    callback_data=f"view_direct_id:{fid}" if fid else f"view_direct_{file_name}",
                ),
                InlineKeyboardButton("📚 הצג קבצים גדולים", callback_data="show_large_files"),
            ],
            [
                InlineKeyboardButton(
                    "🔗 שתף קוד",
                    callback_data=f"share_menu_id:{fid}" if fid else "share_menu_id:",
                )
            ],
            [InlineKeyboardButton("🏠 תפריט ראשי", callback_data="main")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "✅ **הקובץ נשמר בהצלחה!**\n\n"
            + f"📄 **שם:** `{file_name}`\n"
            + f"{emoji} **שפה:** {language}\n"
            + f"🔤 **קידוד:** {detected_encoding}\n"
            + f"💾 **גודל:** {len(content):,} תווים\n"
            + f"📏 **שורות:** {lines_count:,}\n\n"
            + "🎮 בחר פעולה מהכפתורים החכמים:",
            reply_markup=reply_markup,
            parse_mode="Markdown",
        )
        try:
            context.user_data["last_save_success"] = {
                "file_name": file_name,
                "language": language,
                "note": "",
                "file_id": fid,
            }
        except Exception:
            pass

    async def _store_regular_file(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        user_id: int,
        file_name: str,
        language: str,
        content: str,
        detected_encoding: Optional[str],
    ) -> None:
        size_bytes = len(content.encode("utf-8"))
        success = self._save_code_snippet(
            user_id=user_id,
            file_name=file_name,
            language=language,
            content=content,
        )
        if self._emit_event is not None:
            try:
                self._emit_event(
                    "file_saved",
                    severity="info",
                    user_id=int(user_id),
                    language=str(language),
                    size_bytes=int(size_bytes),
                    large=False,
                )
            except Exception:
                pass
        if not success:
            await update.message.reply_text("❌ שגיאה בשמירת הקובץ")
            return

        from utils import get_language_emoji

        emoji = get_language_emoji(language)
        try:
            saved_doc = self._get_latest_version_entry(user_id, file_name) or {}
            fid = str(saved_doc.get("_id") or "")
        except Exception:
            fid = ""
        keyboard = [
            [
                InlineKeyboardButton(
                    "👁️ הצג קוד",
                    callback_data=f"view_direct_id:{fid}" if fid else f"view_direct_{file_name}",
                ),
                InlineKeyboardButton(
                    "✏️ ערוך",
                    callback_data=f"edit_code_direct_{file_name}",
                ),
            ],
            [
                InlineKeyboardButton(
                    "📥 הורד",
                    callback_data=f"download_direct_{file_name}",
                ),
                InlineKeyboardButton(
                    "📚 היסטוריה",
                    callback_data=f"versions_file_{file_name}",
                ),
            ],
            [
                InlineKeyboardButton(
                    "🔗 שתף קוד",
                    callback_data=f"share_menu_id:{fid}" if fid else "share_menu_id:",
                )
            ],
            [InlineKeyboardButton("📚 הצג את כל הקבצים", callback_data="files")],
            [InlineKeyboardButton("🏠 תפריט ראשי", callback_data="main")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "✅ **הקובץ נשמר בהצלחה!**\n\n"
            + f"📄 **שם:** `{file_name}`\n"
            + f"{emoji} **שפה:** {language}\n"
            + f"🔤 **קידוד:** {detected_encoding}\n"
            + f"💾 **גודל:** {len(content)} תווים\n\n"
            + "🎮 בחר פעולה מהכפתורים החכמים:",
            reply_markup=reply_markup,
            parse_mode="Markdown",
        )
        try:
            context.user_data["last_save_success"] = {
                "file_name": file_name,
                "language": language,
                "note": "",
                "file_id": fid,
            }
        except Exception:
            pass

    async def _maybe_alert_oom(self, context: ContextTypes.DEFAULT_TYPE, err: Exception, suffix: str) -> None:
        try:
            msg = str(err)
            if isinstance(err, MemoryError) or "Ran out of memory" in msg or "out of memory" in msg.lower():
                try:
                    notifier = self._notify_admins
                    if notifier is not None:
                        await notifier(context, f"🚨 OOM {suffix}: {msg}")
                except Exception:
                    pass
        except Exception:
            pass

