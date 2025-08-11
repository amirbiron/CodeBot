# FIXED: Changed from Markdown to HTML parsing (2025-01-10)
# This fixes Telegram parsing errors with special characters in suggestions

import asyncio
import json
import logging
import os
import re
import time
import zipfile
from datetime import datetime
from html import escape
from io import BytesIO
from typing import Any, Dict, Optional

from github import Github
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQueryResultArticle,
    InputFile,
    InputTextMessageContent,
    Update,
)
from telegram.error import BadRequest
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from repo_analyzer import RepoAnalyzer

# הגדרת לוגר
logger = logging.getLogger(__name__)

# מצבי שיחה
REPO_SELECT, FILE_UPLOAD, FOLDER_SELECT = range(3)

# מגבלות קבצים גדולים
MAX_INLINE_FILE_BYTES = 5 * 1024 * 1024  # 5MB לשליחה ישירה בבוט
MAX_ZIP_TOTAL_BYTES = 50 * 1024 * 1024  # 50MB לקובץ ZIP אחד
MAX_ZIP_FILES = 500  # מקסימום קבצים ב-ZIP אחד


def safe_html_escape(text):
    """Safely escape text for HTML parsing in Telegram"""
    if not text:
        return ""

    # Convert to string and escape HTML
    text = str(text)
    text = escape(text)

    # Remove any problematic characters that might break HTML parsing
    # Replace common problematic patterns
    text = text.replace("&lt;", "(")
    text = text.replace("&gt;", ")")
    text = text.replace("&amp;", "&")

    # Remove any zero-width characters and control characters
    text = re.sub(r"[\u200b\u200c\u200d\ufeff]", "", text)
    text = re.sub(r"[\x00-\x1f\x7f-\x9f]", "", text)

    # Ensure no unclosed tags by removing < and > that weren't escaped
    text = text.replace("<", "(").replace(">", ")")

    return text.strip()


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
            # נסה לטעון ריפו מועדף מהמסד
            from database import db

            selected_repo = db.get_selected_repo(user_id)
            self.user_sessions[user_id] = {
                "selected_repo": selected_repo,  # טען מהמסד נתונים
                "selected_folder": None,  # None = root של הריפו
                "github_token": None,
            }
        return self.user_sessions[user_id]

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

            return True
        except Exception as e:
            logger.error(f"Error checking rate limit: {e}")
            return True  # במקרה של שגיאה, נמשיך בכל זאת

    async def apply_rate_limit_delay(self, user_id: int):
        """מוסיף השהייה בין בקשות API"""
        current_time = time.time()
        last_call = self.last_api_call.get(user_id, 0)

        # אם עברו פחות מ-2 שניות מהבקשה האחרונה, נחכה
        time_since_last = current_time - last_call
        if time_since_last < 2:
            await asyncio.sleep(2 - time_since_last)

        self.last_api_call[user_id] = time.time()

    def get_user_token(self, user_id: int) -> str:
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

    async def github_menu_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """מציג תפריט GitHub"""
        user_id = update.effective_user.id

        session = self.get_user_session(user_id)
        token = self.get_user_token(user_id)

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

        # כפתורי העלאה - מוצגים רק אם יש ריפו נבחר
        if token and session.get("selected_repo"):
            keyboard.append(
                [InlineKeyboardButton("📚 העלה מהקבצים השמורים", callback_data="upload_saved")]
            )
            keyboard.append([InlineKeyboardButton("📂 בחר תיקיית יעד", callback_data="set_folder")])
            # פעולות נוספות בטוחות
            keyboard.append(
                [InlineKeyboardButton("📥 הורד קובץ מהריפו", callback_data="download_file_menu")]
            )
            # ריכוז פעולות מחיקה בתפריט משנה
            keyboard.append(
                [InlineKeyboardButton("🧨 מחק קובץ/ריפו שלם", callback_data="danger_delete_menu")]
            )
            # התראות חכמות
            keyboard.append(
                [InlineKeyboardButton("🔔 התראות חכמות", callback_data="notifications_menu")]
            )
            # נקודת שמירה בגיט (Tag על HEAD)
            keyboard.append(
                [InlineKeyboardButton("🏷 נקודת שמירה בגיט", callback_data="git_checkpoint")]
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
        await query.answer()

        user_id = query.from_user.id
        session = self.get_user_session(user_id)

        if query.data == "select_repo":
            await self.show_repo_selection(query, context)

        elif query.data == "upload_file":
            if not session.get("selected_repo"):
                await query.edit_message_text("❌ קודם בחר ריפו!\nשלח /github ובחר 'בחר ריפו'")
            else:
                folder_display = session.get("selected_folder") or "root"

                # הוסף כפתור למנהל קבצים
                keyboard = [
                    [
                        InlineKeyboardButton(
                            "📂 פתח מנהל קבצים", switch_inline_query_current_chat=""
                        )
                    ],
                    [InlineKeyboardButton("❌ ביטול", callback_data="github_menu")],
                ]

                await query.edit_message_text(
                    f"📤 <b>העלאת קובץ לריפו:</b>\n"
                    f"<code>{session['selected_repo']}</code>\n"
                    f"📂 תיקייה: <code>{folder_display}</code>\n\n"
                    f"שלח קובץ או לחץ לפתיחת מנהל קבצים:",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode="HTML",
                )

                # סמן שאנחנו במצב העלאה לגיטהאב
                context.user_data["waiting_for_github_upload"] = True
                context.user_data["upload_mode"] = "github"  # הוסף גם את המשתנה החדש
                context.user_data["target_repo"] = session["selected_repo"]
                context.user_data["target_folder"] = session.get("selected_folder", "")
                context.user_data["in_github_menu"] = True
                return FILE_UPLOAD

        elif query.data == "upload_saved":
            await self.upload_saved_files(update, context)

        elif query.data.startswith("repos_page_"):
            page = int(query.data.split("_")[2])
            await self.show_repos(update, context, page)

        elif query.data.startswith("upload_saved_"):
            file_id = query.data.split("_")[2]
            await self.handle_saved_file_upload(update, context, file_id)

        elif query.data == "back_to_menu":
            await self.github_menu_command(update, context)

        elif query.data == "noop":
            await query.answer()  # לא עושה כלום, רק לכפתור התצוגה

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

        elif query.data == "back_to_analysis":
            await self.show_analyze_results_menu(update, context)

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

            await query.edit_message_text(
                f"📊 <b>הגדרות נוכחיות:</b>\n\n"
                f"📁 ריפו: <code>{current_repo}</code>\n"
                f"📂 תיקייה: <code>{current_folder}</code>\n"
                f"🔑 טוקן מוגדר: {has_token}\n\n"
                f"💡 טיפ: השתמש ב-'בחר תיקיית יעד' כדי לשנות את מיקום ההעלאה",
                parse_mode="HTML",
            )

            # חזרה מיידית לתפריט
            await self.github_menu_command(update, context)

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
            keyboard = [
                [InlineKeyboardButton("📁 root (ראשי)", callback_data="folder_root")],
                [InlineKeyboardButton("📂 src", callback_data="folder_src")],
                [InlineKeyboardButton("📂 docs", callback_data="folder_docs")],
                [InlineKeyboardButton("📂 assets", callback_data="folder_assets")],
                [InlineKeyboardButton("📂 images", callback_data="folder_images")],
                [InlineKeyboardButton("✏️ אחר (הקלד ידנית)", callback_data="folder_custom")],
                [InlineKeyboardButton("🔙 חזור לתפריט", callback_data="github_menu")],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await query.edit_message_text("📂 בחר תיקיית יעד:", reply_markup=reply_markup)

        elif query.data.startswith("folder_"):
            folder = query.data.replace("folder_", "")
            if folder == "custom":
                await query.edit_message_text(
                    "✏️ הקלד שם תיקייה:\n" "(השאר ריק או הקלד / להעלאה ל-root)"
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

        elif query.data == "github_menu":
            # חזרה לתפריט הראשי של GitHub
            await query.answer()
            context.user_data["waiting_for_github_upload"] = False
            context.user_data["upload_mode"] = None  # נקה גם את המשתנה החדש
            context.user_data["in_github_menu"] = False
            await self.github_menu_command(update, context)
            return ConversationHandler.END
        
        elif query.data == "git_checkpoint":
            # יצירת tag על HEAD של הריפו הנבחר
            session = self.get_user_session(query.from_user.id)
            repo_full = session.get("selected_repo")
            token = self.get_user_token(query.from_user.id)
            if not token or not repo_full:
                await query.edit_message_text("❌ חסר טוקן או ריפו נבחר")
                return
            try:
                import datetime
                g = Github(login_or_token=token)
                repo = g.get_repo(repo_full)
                ref = repo.get_git_ref("heads/" + repo.get_branch(repo.default_branch).name)
                sha = ref.object.sha
                ts = datetime.datetime.utcnow().strftime("%Y%m%d-%H%M%S")
                tag_name = f"checkpoint-{ts}"
                # Create lightweight tag by creating a ref refs/tags/<tag>
                repo.create_git_ref(ref=f"refs/tags/{tag_name}", sha=sha)
                await query.edit_message_text(
                    f"✅ נוצר tag: <code>{tag_name}</code> על HEAD\nSHA: <code>{sha[:7]}</code>",
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.error(f"Failed to create git checkpoint: {e}")
                await query.edit_message_text("❌ יצירת נקודת שמירה בגיט נכשלה")

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

        elif query.data == "confirm_delete_repo":
            await self.confirm_delete_repo(update, context)

        elif query.data == "download_file_menu":
            await self.show_download_file_menu(update, context)

        elif query.data.startswith("browse_open:"):
            context.user_data["browse_path"] = query.data.split(":", 1)[1]
            context.user_data["browse_page"] = 0
            # מצב מרובה ומחיקה בטוחה לאיפוס
            context.user_data["multi_selection"] = []
            await self.show_repo_browser(update, context)
        elif query.data.startswith("browse_select_download:"):
            path = query.data.split(":", 1)[1]
            context.user_data.pop("waiting_for_download_file_path", None)
            context.user_data.pop("browse_action", None)
            context.user_data.pop("browse_path", None)
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
            await self.github_menu_command(update, context)
        elif query.data.startswith("browse_select_delete:"):
            path = query.data.split(":", 1)[1]
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

        elif query.data.startswith("download_zip:"):
            # הורדת התיקייה הנוכחית כקובץ ZIP
            current_path = query.data.split(":", 1)[1]
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

                zip_buffer.seek(0)
                filename = (
                    f"{repo.name}{'-' + current_path.replace('/', '_') if current_path else ''}.zip"
                )
                zip_buffer.name = filename
                caption = (
                    f"📦 קובץ ZIP לתיקייה: /{current_path or ''}\n"
                    f"מכיל {total_files} קבצים, {format_bytes(total_bytes)}."
                )
                if skipped_large:
                    caption += f"\n⚠️ דילג על {skipped_large} קבצים גדולים (> {format_bytes(MAX_INLINE_FILE_BYTES)})."
                await query.message.reply_document(
                    document=zip_buffer, filename=filename, caption=caption
                )
            except Exception as e:
                logger.error(f"Error creating ZIP: {e}")
                await query.edit_message_text(f"❌ שגיאה בהכנת ZIP: {e}")
                return
            # החזר לדפדפן באותו מקום
            await self.show_repo_browser(update, context)

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
            try:
                g = Github(token)
                repo = g.get_repo(repo_name)
                contents = repo.get_contents(path)
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
                    filename = os.path.basename(contents.path) or "downloaded_file"
                    await query.message.reply_document(document=BytesIO(data), filename=filename)
            except Exception as e:
                logger.error(f"Inline download error: {e}")
                await query.message.reply_text(f"❌ שגיאה בהורדה: {e}")
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
            context.user_data["safe_delete"] = not context.user_data.get("safe_delete", True)
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
                clean = p.strip("/")
                url = f"https://github.com/{repo.full_name}/blob/{branch}/{clean}"
                lines.append(f"• {clean}: {url}")
            text = "🔗 קישורים לקבצים נבחרים:\n" + "\n".join(lines)
            try:
                await query.message.reply_text(text)
            except Exception as e:
                logger.error(f"share_selected_links error: {e}")
                await query.answer("שגיאה בשיתוף קישורים", show_alert=True)
            # השאר בדפדפן
            await self.show_repo_browser(update, context)

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
        elif query.data == "confirm_merge_pr":
            await self.confirm_merge_pr(update, context)

        elif query.data == "validate_repo":
            try:
                await query.edit_message_text("⏳ מוריד את הריפו ובודק תקינות...")
                import tempfile, requests, zipfile
                g = Github(self.get_user_token(user_id))
                repo_full = session.get("selected_repo")
                if not repo_full:
                    await query.edit_message_text("❌ קודם בחר ריפו!")
                    return
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
                    results = {}
                    results["flake8"] = _run(["flake8", "."])
                    results["mypy"] = _run(["mypy", "."])
                    results["bandit"] = _run(["bandit", "-q", "-r", "."])
                    results["black"] = _run(["black", "--check", "."])
                # פורמט תוצאות
                def label(rc):
                    return "OK" if rc == 0 else ("MISSING" if rc == 127 else ("TIMEOUT" if rc == 124 else "FAIL"))
                lines = [f"🧪 בדיקות מתקדמות לריפו <code>{repo_full}</code>:"]
                for tool, (rc, output) in results.items():
                    first = (output.splitlines() or [""])[0][:120]
                    suffix = f" — {escape(first)}" if label(rc) != "OK" and first else ""
                    lines.append(f"• {tool}: <b>{label(rc)}</b>{suffix}")
                await query.edit_message_text("\n".join(lines), parse_mode="HTML")
            except Exception as e:
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

                g = Github(self.get_user_token(user_id))

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
                await update.callback_query.edit_message_text(
                    f"בחר ריפוזיטורי (עמוד {page+1} מתוך {total_pages}):", reply_markup=reply_markup
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
                await update.callback_query.answer(error_msg, show_alert=True)

    async def upload_saved_files(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """מציג רשימת קבצים שמורים להעלאה"""
        user_id = update.effective_user.id
        session = self.user_sessions.get(user_id, {})

        if not session.get("selected_repo"):
            await update.callback_query.answer("❌ נא לבחור ריפו קודם")
            return

        try:
            # כאן תצטרך להתחבר למסד הנתונים שלך
            # לדוגמה:
            from database import db

            files = db.get_user_files(user_id)

            if not files:
                await update.callback_query.answer("❌ אין לך קבצים שמורים", show_alert=True)
                return

            keyboard = []
            for file in files[:10]:  # מציג עד 10 קבצים
                keyboard.append(
                    [
                        InlineKeyboardButton(
                            f"📄 {file['file_name']}", callback_data=f"upload_saved_{file['_id']}"
                        )
                    ]
                )

            keyboard.append([InlineKeyboardButton("🔙 חזור", callback_data="back_to_menu")])

            reply_markup = InlineKeyboardMarkup(keyboard)

            await update.callback_query.edit_message_text(
                "בחר קובץ להעלאה:", reply_markup=reply_markup
            )

        except Exception as e:
            await update.callback_query.answer(f"❌ שגיאה: {str(e)}", show_alert=True)

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

            g = Github(self.get_user_token(user_id))

            # בדוק rate limit לפני הבקשה
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

            # הגדר נתיב הקובץ
            folder = session.get("selected_folder")
            if folder and folder.strip():
                # הסר / מיותרים
                folder = folder.strip("/")
                file_path = f"{folder}/{file_data['file_name']}"
            else:
                # העלה ל-root
                file_path = file_data["file_name"]
            logger.info(f"📁 נתיב יעד: {file_path}")

            # נסה להעלות או לעדכן את הקובץ
            try:
                logger.info(f"[GitHub API] Checking if file exists: {file_path}")
                existing = repo.get_contents(file_path)
                logger.info(f"[GitHub API] File exists, updating: {file_path}")
                result = repo.update_file(
                    path=file_path,
                    message=f"Update {file_data['file_name']} via Telegram bot",
                    content=content,  # PyGithub יקודד אוטומטית
                    sha=existing.sha,
                )
                action = "עודכן"
                logger.info(f"✅ קובץ עודכן בהצלחה")
            except:
                logger.info(f"[GitHub API] File doesn't exist, creating: {file_path}")
                result = repo.create_file(
                    path=file_path,
                    message=f"Upload {file_data['file_name']} via Telegram bot",
                    content=content,  # PyGithub יקודד אוטומטית
                )
                action = "הועלה"
                logger.info(f"[GitHub API] File created successfully: {file_path}")

            raw_url = (
                f"https://raw.githubusercontent.com/{session['selected_repo']}/main/{file_path}"
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

            await update.callback_query.edit_message_text(error_msg)

    async def handle_file_upload(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle file upload"""
        user_id = update.message.from_user.id
        session = self.get_user_session(user_id)

        # בדוק אם אנחנו במצב העלאה לגיטהאב (תמיכה בשני המשתנים)
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

                    g = Github(token)

                    # בדוק rate limit לפני הבקשה
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
                    folder = context.user_data.get("target_folder") or session.get(
                        "selected_folder"
                    )
                    if folder and folder.strip() and folder != "root":
                        # הסר / מיותרים
                        folder = folder.strip("/")
                        file_path = f"{folder}/{filename}"
                    else:
                        # העלה ל-root
                        file_path = filename
                    logger.info(f"📁 נתיב יעד: {file_path}")

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
                    except:
                        result = repo.create_file(
                            path=file_path,
                            message=f"Upload {filename} via Telegram bot",
                            content=content,  # PyGithub יקודד אוטומטית
                        )
                        action = "הועלה"
                        logger.info(f"✅ קובץ נוצר בהצלחה")

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
                [InlineKeyboardButton("📋 פרטים מלאים", callback_data="show_full_analysis")],
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
            "generated_at": datetime.now().isoformat(),
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
            [InlineKeyboardButton("📋 פרטים מלאים", callback_data="show_full_analysis")],
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
            await query.edit_message_text(
                f"✅ הריפו נמחק בהצלחה: <code>{repo_name}</code>", parse_mode="HTML"
            )
            # נקה בחירה לאחר מחיקה
            session["selected_repo"] = None
        except Exception as e:
            logger.error(f"Error deleting repository: {e}")
            await query.edit_message_text(f"❌ שגיאה במחיקת ריפו: {e}")
        finally:
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
        # התחל בדפדוף מה-root
        context.user_data["browse_action"] = "download"
        context.user_data["browse_path"] = ""
        context.user_data["browse_page"] = 0
        context.user_data["multi_mode"] = False
        context.user_data["multi_selection"] = []
        await self.show_repo_browser(update, context)

    async def show_repo_browser(self, update: Update, context: ContextTypes.DEFAULT_TYPE, only_keyboard: bool = False):
        """מציג דפדפן ריפו לפי נתיב ושימוש (download/delete)"""
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
        # קבלת תוכן התיקייה
        contents = repo.get_contents(path or "")
        if not isinstance(contents, list):
            # אם זה קובץ יחיד, הפוך לרשימה לצורך תצוגה
            contents = [contents]
        # בניית פריטים (תיקיות קודם, אחר כך קבצים)
        folders = [c for c in contents if c.type == "dir"]
        files = [c for c in contents if c.type == "file"]
        entry_rows = []
        # Breadcrumbs
        crumbs_row = []
        crumbs_row.append(InlineKeyboardButton("🏠 root", callback_data="browse_open:"))
        if path:
            parts = path.split("/")
            accum = []
            for part in parts:
                accum.append(part)
                crumbs_row.append(
                    InlineKeyboardButton(part, callback_data=f"browse_open:{'/'.join(accum)}")
                )
        if crumbs_row:
            entry_rows.append(crumbs_row)
        for folder in folders:
            entry_rows.append(
                [
                    InlineKeyboardButton(
                        f"📂 {folder.name}", callback_data=f"browse_open:{folder.path}"
                    )
                ]
            )
        multi_mode = context.user_data.get("multi_mode", False)
        selection = set(context.user_data.get("multi_selection", []))
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
                if context.user_data.get("browse_action") == "download":
                    size_val = getattr(f, "size", 0) or 0
                    large_flag = " ⚠️" if size_val and size_val > MAX_INLINE_FILE_BYTES else ""
                    entry_rows.append(
                        [
                            InlineKeyboardButton(
                                f"⬇️ {f.name}{large_flag}",
                                callback_data=f"browse_select_download:{f.path}",
                            )
                        ]
                    )
                else:
                    entry_rows.append(
                        [
                            InlineKeyboardButton(
                                f"🗑️ {f.name}", callback_data=f"browse_select_delete:{f.path}"
                            )
                        ]
                    )
        # עימוד
        page_size = 10
        total_items = len(entry_rows)
        total_pages = max(1, (total_items + page_size - 1) // page_size)
        current_page = min(max(0, context.user_data.get("browse_page", 0)), total_pages - 1)
        start_index = current_page * page_size
        end_index = start_index + page_size
        keyboard = entry_rows[start_index:end_index]
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
            bottom.append(InlineKeyboardButton("⬆️ למעלה", callback_data=f"browse_open:{parent}"))
        # סדר כפתורים לשורות כדי למנוע צפיפות
        row = []
        if context.user_data.get("browse_action") == "download":
            row.append(
                InlineKeyboardButton(
                    "📦 הורד תיקייה כ־ZIP", callback_data=f"download_zip:{path or ''}"
                )
            )
        if len(row) >= 1:
            keyboard.append(row)
        row = []
        if context.user_data.get("browse_action") == "download":
            row.append(
                InlineKeyboardButton(
                    "🔗 שתף קישור לתיקייה", callback_data=f"share_folder_link:{path or ''}"
                )
            )
        if not multi_mode:
            row.append(InlineKeyboardButton("✅ בחר מרובים", callback_data="multi_toggle"))
            keyboard.append(row)
        else:
            keyboard.append(row)
            row = []
            if context.user_data.get("browse_action") == "download":
                row.append(
                    InlineKeyboardButton("📦 הורד נבחרים כ־ZIP", callback_data="multi_execute")
                )
                row.append(
                    InlineKeyboardButton(
                        "🔗 שתף קישורים לנבחרים", callback_data="share_selected_links"
                    )
                )
                keyboard.append(row)
            else:
                safe_label = (
                    "מצב מחיקה בטוח: פעיל"
                    if context.user_data.get("safe_delete", True)
                    else "מצב מחיקה בטוח: כבוי"
                )
                row.append(InlineKeyboardButton(safe_label, callback_data="safe_toggle"))
                keyboard.append(row)
                row = [
                    InlineKeyboardButton("🗑️ מחק נבחרים", callback_data="multi_execute"),
                    InlineKeyboardButton(
                        "🔗 שתף קישורים לנבחרים", callback_data="share_selected_links"
                    ),
                ]
                keyboard.append(row)
            row = [
                InlineKeyboardButton("♻️ נקה בחירה", callback_data="multi_clear"),
                InlineKeyboardButton("🚫 בטל מצב מרובה", callback_data="multi_toggle"),
            ]
            keyboard.append(row)
        keyboard.append([InlineKeyboardButton("🔙 חזרה", callback_data="github_menu")])
        if bottom:
            keyboard.append(bottom)
        # טקסט
        action = "הורדה" if context.user_data.get("browse_action") == "download" else "מחיקה"
        if only_keyboard:
            try:
                await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))
            except Exception:
                await query.edit_message_text(
                    f"📁 דפדוף ריפו: <code>{repo_name}</code>\n"
                    f"📂 נתיב: <code>/{path or ''}</code>\n\n"
                    f"בחר קובץ ל{action} או פתח תיקייה (מציג {min(page_size, max(0, total_items - start_index))} מתוך {total_items}):",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode="HTML",
                )
        else:
            await query.edit_message_text(
                f"📁 דפדוף ריפו: <code>{repo_name}</code>\n"
                f"📂 נתיב: <code>/{path or ''}</code>\n\n"
                f"בחר קובץ ל{action} או פתח תיקייה (מציג {min(page_size, max(0, total_items - start_index))} מתוך {total_items}):",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="HTML",
            )

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
        # ללא קלט: הצג עזרה קצרה
        if not q:
            results = [
                InlineQueryResultArticle(
                    id="help-1",
                    title="zip <path> — הורד תיקייה כ־ZIP",
                    description="לדוגמה: zip src/components",
                    input_message_content=InputTextMessageContent("בחר תיקייה להורדה כ־ZIP"),
                    reply_markup=InlineKeyboardMarkup(
                        [[InlineKeyboardButton("פתח /github", callback_data="github_menu")]]
                    ),
                ),
                InlineQueryResultArticle(
                    id="help-2",
                    title="file <path> — הורד קובץ בודד",
                    description="לדוגמה: file README.md או src/app.py",
                    input_message_content=InputTextMessageContent("בחר קובץ להורדה"),
                    reply_markup=InlineKeyboardMarkup(
                        [[InlineKeyboardButton("פתח /github", callback_data="github_menu")]]
                    ),
                ),
                InlineQueryResultArticle(
                    id="help-3",
                    title=f"ריפו נוכחי: {repo_name}",
                    description="הקלד נתיב מלא לרשימה/קובץ",
                    input_message_content=InputTextMessageContent(f"ריפו: {repo_name}"),
                ),
            ]
            await inline_query.answer(results, cache_time=1, is_personal=True)
            return
        # פרסור פשוט: zip <path> / file <path> או נתיב ישיר
        is_zip = False
        is_file = False
        path = q
        if q.lower().startswith("zip "):
            is_zip = True
            path = q[4:].strip()
        elif q.lower().startswith("file "):
            is_file = True
            path = q[5:].strip()
        path = path.lstrip("/")
        try:
            contents = repo.get_contents(path)
            # תיקייה
            if isinstance(contents, list):
                # תוצאה ל־ZIP
                results.append(
                    InlineQueryResultArticle(
                        id=f"zip-{path or 'root'}",
                        title=f"📦 ZIP לתיקייה: /{path or ''}",
                        description=f"{repo_name} — אריזת תיקייה והורדה",
                        input_message_content=InputTextMessageContent(
                            f"ZIP לתיקייה: /{path or ''}"
                        ),
                        reply_markup=InlineKeyboardMarkup(
                            [
                                [
                                    InlineKeyboardButton(
                                        "📦 הורד ZIP", callback_data=f"download_zip:{path}"
                                    )
                                ]
                            ]
                        ),
                    )
                )
                # הצג כמה קבצים ראשונים בתיקייה להורדה מהירה
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
                                                "⬇️ הורד",
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
                results.append(
                    InlineQueryResultArticle(
                        id=f"file-{path}",
                        title=f"⬇️ הורד: {os.path.basename(contents.path)} ({size_str})",
                        description=f"/{path}",
                        input_message_content=InputTextMessageContent(f"קובץ: /{path}"),
                        reply_markup=InlineKeyboardMarkup(
                            [
                                [
                                    InlineKeyboardButton(
                                        "⬇️ הורד", callback_data=f"inline_download_file:{path}"
                                    )
                                ]
                            ]
                        ),
                    )
                )
        except Exception:
            # אם לצורך zip/file מפורש, החזר כפתור גם אם לא קיים (ייתכן נתיב שגוי)
            if is_zip and path:
                results.append(
                    InlineQueryResultArticle(
                        id=f"zip-maybe-{path}",
                        title=f"📦 ZIP: /{path}",
                        description="ניסיון אריזה לתיקייה (אם קיימת)",
                        input_message_content=InputTextMessageContent(f"ZIP לתיקייה: /{path}"),
                        reply_markup=InlineKeyboardMarkup(
                            [
                                [
                                    InlineKeyboardButton(
                                        "📦 הורד ZIP", callback_data=f"download_zip:{path}"
                                    )
                                ]
                            ]
                        ),
                    )
                )
            elif is_file and path:
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
                                        "⬇️ הורד", callback_data=f"inline_download_file:{path}"
                                    )
                                ]
                            ]
                        ),
                    )
                )
            else:
                results.append(
                    InlineQueryResultArticle(
                        id="not-found",
                        title="לא נמצאה התאמה",
                        description="הקלד: zip <path> או file <path> או נתיב מלא",
                        input_message_content=InputTextMessageContent("לא נמצאה התאמה לשאילתה"),
                    )
                )
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
                InlineKeyboardButton("תדירות: 2ד׳", callback_data="notifications_interval_120"),
                InlineKeyboardButton("5ד׳", callback_data="notifications_interval_300"),
                InlineKeyboardButton("15ד׳", callback_data="notifications_interval_900"),
            ],
            [InlineKeyboardButton("בדוק עכשיו", callback_data="notifications_check_now")],
        ]
        text = (
            f"🔔 התראות לריפו: <code>{session['selected_repo']}</code>\n"
            f"מצב: {'פעיל' if enabled else 'כבוי'} | תדירות: {int(interval/60)} ד׳\n"
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
                    session["notifications_last"]["pr"] = datetime.utcnow()
                else:
                    pulls = repo.get_pulls(state="all", sort="updated", direction="desc")
                    for pr in pulls[:10]:
                        updated = pr.updated_at
                        if updated <= last_pr_check_time:
                            break
                        status = (
                            "נפתח"
                            if pr.state == "open" and pr.created_at == pr.updated_at
                            else ("מוזג" if pr.merged else ("נסגר" if pr.state == "closed" else "עודכן"))
                        )
                        messages.append(
                            f'🔔 PR {status}: <a href="{pr.html_url}">{safe_html_escape(pr.title)}</a>'
                        )
                    session["notifications_last"] = session.get("notifications_last", {})
                    session["notifications_last"]["pr"] = datetime.utcnow()
            # Issues
            if settings.get("issues", True):
                last_issues_check_time = last.get("issues")
                if last_issues_check_time is None:
                    session["notifications_last"] = session.get("notifications_last", {})
                    session["notifications_last"]["issues"] = datetime.utcnow()
                else:
                    issues = repo.get_issues(state="all", sort="updated", direction="desc")
                    count = 0
                    for issue in issues:
                        if issue.pull_request is not None:
                            continue
                        updated = issue.updated_at
                        if updated <= last_issues_check_time:
                            break
                        status = (
                            "נפתח"
                            if issue.state == "open" and issue.created_at == issue.updated_at
                            else ("נסגר" if issue.state == "closed" else "עודכן")
                        )
                        messages.append(
                            f'🔔 Issue {status}: <a href="{issue.html_url}">{safe_html_escape(issue.title)}</a>'
                        )
                        count += 1
                        if count >= 10:
                            break
                    session["notifications_last"] = session.get("notifications_last", {})
                    session["notifications_last"]["issues"] = datetime.utcnow()
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
        txt = f"למזג PR?\n" f"#{pr.number}: <b>{safe_html_escape(pr.title)}</b>\n" f"{pr.html_url}"
        kb = [
            [InlineKeyboardButton("✅ אשר מיזוג", callback_data="confirm_merge_pr")],
            [InlineKeyboardButton("🔙 חזור", callback_data="merge_pr_menu")],
        ]
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
                    f'✅ PR מוזג בהצלחה: <a href="{pr.html_url}">#{pr.number}</a>',
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
        try:
            import datetime
            g = Github(login_or_token=token)
            repo = g.get_repo(repo_full)
            ref = repo.get_git_ref("heads/" + repo.get_branch(repo.default_branch).name)
            sha = ref.object.sha
            ts = datetime.datetime.utcnow().strftime("%Y%m%d-%H%M%S")
            tag_name = f"checkpoint-{ts}"
            tag_message = f"Checkpoint created by bot at {ts}Z"
            # Create lightweight tag by creating a ref refs/tags/<tag>
            repo.create_git_ref(ref=f"refs/tags/{tag_name}", sha=sha)
            await query.edit_message_text(
                f"✅ נוצר tag: <code>{tag_name}</code> על HEAD\nSHA: <code>{sha[:7]}</code>",
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Failed to create git checkpoint: {e}")
            await query.edit_message_text("❌ יצירת נקודת שמירה בגיט נכשלה")
