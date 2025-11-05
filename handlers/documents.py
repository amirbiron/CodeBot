"""Handlers עבור מסמכים וקבצים הנשלחים לבוט."""

from __future__ import annotations

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
from typing import Awaitable, Callable, List, Optional, Protocol, Sequence

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from database import CodeSnippet, LargeFile, db
from file_manager import backup_manager
from html import escape as html_escape


logger = logging.getLogger(__name__)


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
        encodings_to_try: Sequence[str],
        emit_event: Callable[..., object] | None,
        errors_total: Optional[_MetricProto],
    ) -> None:
        self._notify_admins = notify_admins
        self._get_reporter = get_reporter
        self._log_user_activity = log_user_activity
        self._encodings_to_try = tuple(encodings_to_try)
        self._emit_event = emit_event
        self._errors_total = errors_total

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
            await file.download_to_memory(buf)
            buf.seek(0)
            if not zipfile.is_zipfile(buf):
                await update.message.reply_text("❌ הקובץ שהועלה אינו ZIP תקין.")
                return
            zf = zipfile.ZipFile(buf, "r")
            all_names = [n for n in zf.namelist() if not n.endswith("/")]
            members = [n for n in all_names if not (n.startswith("__MACOSX/") or n.split("/")[-1].startswith("._"))]
            top_levels = set()
            for name in zf.namelist():
                if "/" in name and not name.startswith("__MACOSX/"):
                    top_levels.add(name.split("/", 1)[0])
            common_root = list(top_levels)[0] if len(top_levels) == 1 else None

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
            with zipfile.ZipFile(buf, "r") as zf:
                names_all = zf.namelist()
                file_names = [
                    n
                    for n in names_all
                    if not n.endswith("/")
                    and not n.startswith("__MACOSX/")
                    and not n.split("/")[-1].startswith("._")
                ]
                if not file_names:
                    await update.message.reply_text("❌ ה‑ZIP ריק.")
                    return
                top_levels = set()
                for name in names_all:
                    if "/" in name and not name.startswith("__MACOSX/"):
                        top_levels.add(name.split("/", 1)[0])
                common_root = list(top_levels)[0] if len(top_levels) == 1 else None

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
            from github import Github

            g = Github(token)
            user = g.get_user()
            repo = user.create_repo(
                name=repo_name,
                private=bool(context.user_data.get("new_repo_private", True)),
                auto_init=False,
            )
            repo_full = repo.full_name
            try:
                db.save_selected_repo(user_id, repo_full)
                sess = github_handler.get_user_session(user_id)
                sess["selected_repo"] = repo_full
            except Exception as err:
                logger.warning("Failed saving selected repo: %s", err)

            await update.message.reply_text("📤 מעלה את קבצי ה‑ZIP לריפו החדש...")
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
                top_levels = set()
                for name in names_all:
                    if "/" in name and not name.startswith("__MACOSX/"):
                        top_levels.add(name.split("/", 1)[0])
                common_root = list(top_levels)[0] if len(top_levels) == 1 else None

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
                logger.info("No base ref found for new repo (expected for empty repo): %s", exc)

            if base_commit is None:
                created_count = 0
                for path, raw in files:
                    try:
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
                    except Exception as err:
                        logger.warning("[create_repo_from_zip] Failed to create file %s: %s", path, err)
                await update.message.reply_text(
                    f"✅ נוצר ריפו חדש והוזנו {created_count} קבצים\n🔗 <a href=\"https://github.com/{repo_full}\">{repo_full}</a>",
                    parse_mode=ParseMode.HTML,
                )
                return

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
            await update.message.reply_text(
                f"✅ נוצר ריפו חדש והוזנו {len(new_tree_elems)} קבצים\n🔗 <a href=\"https://github.com/{repo_full}\">{repo_full}</a>",
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
            file = await context.bot.get_file(document.file_id)
            buf = BytesIO()
            await file.download_to_memory(buf)
            raw = buf.getvalue()
            items = context.user_data.get("zip_create_items")
            if items is None:
                items = []
                context.user_data["zip_create_items"] = items
            safe_name = (document.file_name or f"file_{len(items)+1}").strip() or f"file_{len(items)+1}"
            items.append({"filename": safe_name, "bytes": raw})
            await update.message.reply_text(
                f"✅ נוסף: <code>{html_escape(safe_name)}</code> (סה""כ {len(items)} קבצים)",
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

            await self._maybe_store_zip_copy(update, context, document, raw_bytes)

            content, detected_encoding = self._decode_bytes(raw_bytes)
            if content is None:
                logger.error("❌ לא ניתן לקרוא את הקובץ באף קידוד: %s", self._encodings_to_try)
                if self._emit_event is not None:
                    try:
                        self._emit_event(
                            "file_read_unreadable",
                            severity="error",
                            attempted_encodings=",".join(self._encodings_to_try),
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
                    + f"📝 ניסיתי את הקידודים: {', '.join(self._encodings_to_try)}\n"
                    + "💡 אנא ודא שזהו קובץ טקסט/קוד ולא קובץ בינארי"
                )
                return

            file_name = document.file_name or "untitled.txt"
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
        for encoding in self._encodings_to_try:
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
    ) -> None:
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
                return

            backup_id = f"upload_{update.effective_user.id}_{int(datetime.now(timezone.utc).timestamp())}"
            target_path = backup_manager.backup_dir / f"{backup_id}.zip"
            try:
                try:
                    ztest = zipfile.ZipFile(BytesIO(raw_bytes))
                    try:
                        ztest.getinfo("metadata.json")
                        md_bytes = raw_bytes
                    except KeyError:
                        md = {
                            "backup_id": backup_id,
                            "backup_type": "generic_zip",
                            "user_id": update.effective_user.id,
                            "created_at": datetime.now(timezone.utc).isoformat(),
                            "original_filename": document.file_name,
                            "source": "uploaded_document",
                        }
                        out_buf = BytesIO()
                        with zipfile.ZipFile(out_buf, "w", compression=zipfile.ZIP_DEFLATED) as zout:
                            for name in ztest.namelist():
                                zout.writestr(name, ztest.read(name))
                            zout.writestr("metadata.json", json.dumps(md, indent=2))
                        md_bytes = out_buf.getvalue()
                except Exception:
                    md_bytes = raw_bytes

                try:
                    backup_manager.save_backup_bytes(
                        md_bytes,
                        {
                            "backup_id": backup_id,
                            "backup_type": "generic_zip",
                            "user_id": update.effective_user.id,
                            "created_at": datetime.now(timezone.utc).isoformat(),
                            "original_filename": document.file_name,
                            "source": "uploaded_document",
                        },
                    )
                except Exception:
                    with open(target_path, "wb") as fzip:
                        fzip.write(md_bytes)
                await update.message.reply_text(
                    "✅ קובץ ZIP נשמר בהצלחה לרשימת ה‑ZIP השמורים.\n"
                    "📦 ניתן למצוא אותו תחת: '📚' > '📦 קבצי ZIP' או ב‑Batch/GitHub."
                )
            except Exception as err:
                logger.warning("Failed to persist uploaded ZIP: %s", err)
        except Exception:
            pass

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
        large_file = LargeFile(
            user_id=user_id,
            file_name=file_name,
            content=content,
            programming_language=language,
            file_size=len(content.encode("utf-8")),
            lines_count=len(content.split("\n")),
        )
        success = db.save_large_file(large_file)
        if self._emit_event is not None:
            try:
                self._emit_event(
                    "file_saved",
                    severity="info",
                    user_id=int(user_id),
                    language=str(language),
                    size_bytes=int(len(content.encode("utf-8"))),
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
            from bson import ObjectId  # noqa: F401  # נדרש לצורך יצירת ObjectId ב-db.get_large_file
            saved_large = db.get_large_file(user_id, file_name) or {}
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
        lines_count = len(content.split("\n"))
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
        snippet = CodeSnippet(
            user_id=user_id,
            file_name=file_name,
            code=content,
            programming_language=language,
        )
        success = db.save_code_snippet(snippet)
        if self._emit_event is not None:
            try:
                self._emit_event(
                    "file_saved",
                    severity="info",
                    user_id=int(user_id),
                    language=str(language),
                    size_bytes=int(len(content.encode("utf-8"))),
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
            saved_doc = db.get_latest_version(user_id, file_name) or {}
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

