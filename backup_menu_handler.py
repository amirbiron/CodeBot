import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional
import zipfile
from types import SimpleNamespace

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import ContextTypes

from services import backup_service as backup_manager
from handlers.pagination import build_pagination_row
from i18n.strings_he import BTN_BACKUP_ZIPS

logger = logging.getLogger(__name__)

def _get_files_facade():
    """Lazy facade accessor to avoid import-order issues in tests."""
    try:
        from src.infrastructure.composition import get_files_facade  # type: ignore
        return get_files_facade()
    except Exception:
        return None

# Structured logging and performance instrumentation (fail-open in tests)
try:
    from observability import emit_event  # type: ignore
except Exception:  # pragma: no cover
    def emit_event(event: str, severity: str = "info", **fields: Any) -> None:  # type: ignore
        return None

try:
    from metrics import track_performance  # type: ignore
except Exception:  # pragma: no cover
    from contextlib import contextmanager

    @contextmanager
    def track_performance(_operation: str, labels: Optional[Dict[str, str]] = None):  # type: ignore
        yield

# עזר לפורמט גודל

def _format_bytes(num: int) -> str:
    try:
        for unit in ["B", "KB", "MB", "GB"]:
            if num < 1024.0 or unit == "GB":
                return f"{num:.1f} {unit}" if unit != "B" else f"{int(num)} {unit}"
            num /= 1024.0
    except Exception:
        return str(num)
    return str(num)

# עזרי תצוגה לשמות/תאריכים בכפתורים
def _format_date(dt) -> str:
    try:
        return dt.strftime('%d/%m/%y %H:%M')
    except Exception:
        return str(dt)

def _truncate_middle(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    if max_len <= 1:
        return text[:max_len]
    keep = max_len - 1
    front = keep // 2
    back = keep - front
    return text[:front] + '…' + text[-back:]

# עזר: מחזיר רק את שם הריפו ללא ה-owner (owner/repo → repo)
def _repo_only(repo_full: str) -> str:
    try:
        if not repo_full:
            return ""
        repo_full = str(repo_full)
        return repo_full.split('/', 1)[1] if '/' in repo_full else repo_full
    except Exception:
        return str(repo_full)

def _rating_to_emoji(rating: str) -> str:
    """המרת מחרוזת דירוג (למשל "🏆 מצוין") לאימוג'י בלבד ("🏆")."""
    try:
        if not isinstance(rating, str):
            return ""
        r = rating.strip()
        if not r:
            return ""
        if "🏆" in r:
            return "🏆"
        if "👍" in r:
            return "👍"
        if "🤷" in r:
            return "🤷"
        # אם כבר אימוג'י בלבד הועבר
        if r in {"🏆", "👍", "🤷"}:
            return r
        # ברירת מחדל: בלי טקסט
        return ""
    except Exception:
        return ""
def _build_download_button_text(info, force_hide_size: bool = False, vnum: int = None, rating: str = "") -> str:
    """יוצר טקסט תמציתי לכפתור ההורדה הכולל שם עיקרי + תאריך/גודל.
    מוגבל לאורך בטוח עבור טלגרם (~64 תווים) תוך הבטחת הצגת התאריך."""
    MAX_LEN = 64
    # שם עיקרי
    if getattr(info, 'backup_type', '') == 'github_repo_zip' and getattr(info, 'repo', None):
        primary = _repo_only(str(info.repo))
    else:
        # עבור ZIP כללי/ידני, הצג את ה-backup_id כשם עיקרי במקום "full"
        primary = getattr(info, 'backup_id', 'full')
    date_part = _format_date(getattr(info, 'created_at', ''))

    def build_button_text(prim: str, version_text: str = "", rating_text: str = "") -> str:
        # פורמט סופי: BKP zip <name> vN <rating?> - <date>
        parts = ["BKP", "zip", prim]
        if version_text:
            parts.append(version_text)
        if rating_text:
            parts.append(rating_text)
        left = " ".join([p for p in parts if p])
        return f"{left} - {date_part}"

    # אם יש צורך להסתיר את הגודל (למשל במצב מחיקה), בנה טקסט ללא הגודל
    version_text = f"v{vnum}" if vnum else ""
    rating_text = _rating_to_emoji(rating)
    if force_hide_size:
        prim_use = _truncate_middle(primary, 24)
        text = build_button_text(prim_use, version_text, rating_text)
        if len(text) <= MAX_LEN:
            return text
        for limit in (20, 16, 12, 10, 8, 6, 4):
            prim_use = _truncate_middle(primary, limit)
            text = build_button_text(prim_use, version_text, rating_text)
            if len(text) <= MAX_LEN:
                return text
        # נפילה: בלי דירוג
        text = build_button_text(prim_use, version_text, "")
        if len(text) <= MAX_LEN:
            return text
        # נפילה סופית: שם מקוצר מאוד
        return build_button_text(_truncate_middle(primary, 3), version_text, "")

    # גרסת מיזוג: בטל מסלול כפול ישן של force_hide_size ללא גרסה

    # התחלה עם תצורה מלאה ללא גודל, עם גרסה ודירוג
    prim_use = _truncate_middle(primary, 28)
    text = build_button_text(prim_use, version_text, rating_text)
    if len(text) <= MAX_LEN:
        return text
    # 1) קצר עוד את השם העיקרי
    for limit in (24, 20, 16, 12, 10, 8):
        prim_use = _truncate_middle(primary, limit)
        text = build_button_text(prim_use, version_text, rating_text)
        if len(text) <= MAX_LEN:
            return text
    # 2) נסה ללא דירוג
    text = build_button_text(prim_use, version_text, "")
    if len(text) <= MAX_LEN:
        return text
    # 3) נפילה סופית: שם קצר מאוד עם גרסה
    return build_button_text(_truncate_middle(primary, 4), version_text, "")

class BackupMenuHandler:
    """תפריט גיבוי ושחזור מלא + נקודות שמירה בגיט"""
    def __init__(self):
        self.user_sessions: Dict[int, Dict[str, Any]] = {}
    
    def _get_session(self, user_id: int) -> Dict[str, Any]:
        if user_id not in self.user_sessions:
            self.user_sessions[user_id] = {}
        return self.user_sessions[user_id]
    
    def _get_cached_backup(self, context: ContextTypes.DEFAULT_TYPE, user_id: int, backup_id: str) -> Optional[SimpleNamespace]:
        try:
            cache = context.user_data.get("_recent_backups", {})
        except Exception:
            return None
        data = cache.get(backup_id)
        if not data:
            return None
        # ייתכן שהקובץ המקומי עדיין לא נוצר (בייחוד כשהאחסון הוא GridFS והעותק המקומי נשלף לפי דרישה).
        # אל תכשיל תצוגת פרטי הגיבוי — נוודא קיום קובץ רק בעת הורדה בפועל.
        file_path = data.get("file_path") or ""
        created_at_raw = data.get("created_at")
        created_at_dt: datetime
        if isinstance(created_at_raw, datetime):
            created_at_dt = created_at_raw if created_at_raw.tzinfo else created_at_raw.replace(tzinfo=timezone.utc)
        elif isinstance(created_at_raw, str):
            try:
                created_at_dt = datetime.fromisoformat(created_at_raw)
                if created_at_dt.tzinfo is None:
                    created_at_dt = created_at_dt.replace(tzinfo=timezone.utc)
            except Exception:
                created_at_dt = datetime.now(timezone.utc)
        else:
            created_at_dt = datetime.now(timezone.utc)
        try:
            total_size = int(data.get("total_size") or 0)
        except Exception:
            total_size = 0
        try:
            file_count = int(data.get("file_count") or 0)
        except Exception:
            file_count = 0
        return SimpleNamespace(
            backup_id=backup_id,
            user_id=user_id,
            created_at=created_at_dt,
            file_count=file_count,
            total_size=total_size,
            backup_type=data.get("backup_type", "github_repo_zip"),
            status="completed",
            file_path=file_path,
            repo=data.get("repo"),
            path=data.get("path"),
            metadata=data,
        )

    def _merge_cached_backups(self, context: ContextTypes.DEFAULT_TYPE, user_id: int, backups: list[Any]) -> list[Any]:
        try:
            cache = context.user_data.get("_recent_backups", {})
        except Exception:
            cache = {}
        if not cache:
            return backups
        existing_ids = {getattr(b, "backup_id", "") for b in backups}
        extras: list[Any] = []
        if isinstance(cache, dict):
            for bid in list(cache.keys()):
                if bid in existing_ids:
                    cache.pop(bid, None)
                    continue
                cached = self._get_cached_backup(context, user_id, bid)
                if cached:
                    extras.append(cached)
        if extras:
            backups.extend(extras)
            try:
                backups.sort(key=lambda b: getattr(b, "created_at", datetime.now(timezone.utc)), reverse=True)
            except Exception:
                pass
        return backups

    def _forget_cached_backup(self, context: ContextTypes.DEFAULT_TYPE, backup_id: str) -> None:
        try:
            cache = context.user_data.get("_recent_backups", {})
            if isinstance(cache, dict):
                cache.pop(backup_id, None)
        except Exception:
            pass

    async def show_backup_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query if update.callback_query else None
        if query:
            await query.answer()
            message = query.edit_message_text
        else:
            message = update.message.reply_text
        
        keyboard = [
            [InlineKeyboardButton("📦 צור גיבוי מלא", callback_data="backup_create_full")],
            [InlineKeyboardButton("♻️ שחזור מגיבוי (ZIP)", callback_data="backup_restore_full_start")],
            [InlineKeyboardButton("🗂 גיבויים אחרונים", callback_data="backup_list")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        try:
            user_id = (update.callback_query.from_user.id if update.callback_query else update.effective_user.id)
            emit_event("backup_menu_opened", severity="info", user_id=int(user_id))
        except Exception:
            pass
        await message("בחר פעולה מתפריט הגיבוי/שחזור:", reply_markup=reply_markup)
    
    # docs:backup-callback-dispatch:start — הקטע מוטמע בתיעוד (docs/conversation-handlers.rst); אל תסיר את הסימון
    async def handle_callback_query(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        user_id = query.from_user.id
        data = query.data
        
        if data == "backup_create_full":
            await self._create_full_backup(update, context)
        elif data == "backup_restore_full_start":
            await self._show_backups_list(update, context)
        elif data == "backup_list":
            # הצג את הרשימה בעמוד האחרון שבו היינו (אם נשמר), אחרת עמוד 1
            await self._show_backups_list(update, context)
        elif data.startswith("backup_add_note:"):
            backup_id = data.split(":", 1)[1]
            await self._ask_backup_note(update, context, backup_id)
        elif data.startswith("backup_page_"):
            try:
                page = int(data.split("_")[-1])
            except Exception:
                page = 1
            await self._show_backups_list(update, context, page=page)
        elif data.startswith("backup_restore_id:"):
            backup_id = data.split(":", 1)[1]
            await self._restore_by_id(update, context, backup_id)
        elif data.startswith("backup_download_id:"):
            backup_id = data.split(":", 1)[1]
            # הורדה בפועל של קובץ הגיבוי לפי מזהה
            await self._download_by_id(update, context, backup_id)
        elif data.startswith("backup_details:"):
            backup_id = data.split(":", 1)[1]
            await self._show_backup_details(update, context, backup_id)
    # docs:backup-callback-dispatch:end
        elif data.startswith("backup_rate_menu:"):
            # פתיחת מסך תיוג עם 3 כפתורים (🏆 / 👍 / 🤷)
            backup_id = data.split(":", 1)[1]
            await self.send_rating_prompt(update, context, backup_id)
        elif data.startswith("backup_delete_one_confirm:"):
            backup_id = data.split(":", 1)[1]
            kb = [
                [InlineKeyboardButton("✅ אישור מחיקה", callback_data=f"backup_delete_one_execute:{backup_id}")],
                [InlineKeyboardButton("🔙 ביטול", callback_data=f"backup_details:{backup_id}")],
            ]
            txt = f"האם למחוק לצמיתות את הגיבוי:\n{backup_id}?"
            await update.callback_query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb))
        elif data.startswith("backup_delete_one_execute:"):
            backup_id = data.split(":", 1)[1]
            try:
                res = backup_manager.delete_backups(user_id, [backup_id])
                try:
                    facade = _get_files_facade()
                    if facade is not None:
                        facade.delete_backup_ratings(user_id, [backup_id])
                except Exception:
                    pass
                deleted = res.get("deleted", 0)
                if deleted:
                    await update.callback_query.edit_message_text("✅ הגיבוי נמחק")
                    self._forget_cached_backup(context, backup_id)
                    await self._show_backups_list(update, context)
                else:
                    await update.callback_query.edit_message_text("❌ המחיקה נכשלה")
                try:
                    emit_event("backup_delete_one", severity="info" if deleted else "warn", user_id=int(user_id), backup_id=str(backup_id), deleted=int(deleted))
                except Exception:
                    pass
            except Exception as e:
                await update.callback_query.edit_message_text(f"❌ שגיאה במחיקה: {e}")
                try:
                    emit_event("backup_delete_one_error", severity="error", user_id=int(user_id), backup_id=str(backup_id), error=str(e))
                except Exception:
                    pass
        elif data == "backup_delete_mode_on":
            context.user_data["backup_delete_mode"] = True
            context.user_data["backup_delete_selected"] = set()
            await self._show_backups_list(update, context)
        elif data == "backup_delete_mode_off":
            context.user_data.pop("backup_delete_mode", None)
            context.user_data.pop("backup_delete_selected", None)
            await self._show_backups_list(update, context)
        elif data.startswith("backup_toggle_del:"):
            bid = data.split(":", 1)[1]
            sel = context.user_data.setdefault("backup_delete_selected", set())
            if bid in sel:
                sel.remove(bid)
            else:
                sel.add(bid)
            await self._show_backups_list(update, context)
        elif data == "backup_delete_confirm":
            sel = list(context.user_data.get("backup_delete_selected", set()) or [])
            if not sel:
                await query.answer("לא נבחרו פריטים", show_alert=True)
                return
            # הצג מסך אימות סופי
            txt = "אישור מחיקה\nהאם אתה בטוח שברצונך למחוק את:"\
                + "\n" + "\n".join(sel[:15]) + ("\n…" if len(sel) > 15 else "")
            kb = [
                [InlineKeyboardButton("✅ אישור מחיקה", callback_data="backup_delete_execute")],
                [InlineKeyboardButton("🔙 ביטול", callback_data="backup_delete_mode_off")],
            ]
            await query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb))
        elif data == "backup_delete_execute":
            sel = list(context.user_data.get("backup_delete_selected", set()) or [])
            if not sel:
                await query.edit_message_text("לא נבחרו פריטים למחיקה")
                return
            # מחיקה בפועל
            try:
                res = backup_manager.delete_backups(user_id, sel)
                try:
                    # נקה דירוגים
                    facade = _get_files_facade()
                    if facade is not None:
                        facade.delete_backup_ratings(user_id, sel)
                except Exception:
                    pass
                deleted = res.get("deleted", 0)
                errs = res.get("errors", [])
                msg = f"✅ נמחקו {deleted} גיבויים"
                if errs:
                    msg += f"\n⚠️ כשלים: {len(errs)}"
                await query.edit_message_text(msg)
                # נקה מצב מחיקה ורענן רשימה
                context.user_data.pop("backup_delete_mode", None)
                context.user_data.pop("backup_delete_selected", None)
                for bid in sel:
                    self._forget_cached_backup(context, bid)
                try:
                    await self._show_backups_list(update, context)
                except Exception:
                    pass
            except Exception as e:
                await query.edit_message_text(f"❌ שגיאה במחיקה: {e}")
        elif data.startswith("backup_rate:"):
            # פורמט: backup_rate:<backup_id>:<rating_key>
            try:
                _, b_id, rating_key = data.split(":", 2)
            except Exception:
                await query.answer("בקשה לא תקפה", show_alert=True)
                return
            # שמור דירוג
            rating_map = {
                "excellent": "🏆 מצוין",
                "good": "👍 טוב",
                "ok": "🤷 סביר",
            }
            rating_value = rating_map.get(rating_key, rating_key)
            try:
                facade = _get_files_facade()
                ok = True
                if facade is None:
                    ok = False
                else:
                    ok = bool(facade.save_backup_rating(user_id, b_id, rating_value))
                if not ok:
                    await query.answer("שמירת דירוג נכשלה", show_alert=True)
                    return
                # רענון UX: אם נכנסו דרך תצוגת פרטים, הצג אותה שוב; אחרת רענן רשימה
                try:
                    await self._show_backup_details(update, context, b_id)
                except Exception:
                    await self._show_backups_list(update, context)
            except Exception as e:
                await query.answer(f"שמירת דירוג נכשלה: {e}", show_alert=True)
            return
        else:
            await query.answer("לא נתמך", show_alert=True)
    
    async def _create_full_backup(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        user_id = query.from_user.id
        await query.edit_message_text("⏳ יוצר גיבוי מלא...")
        # יצירת גיבוי מלא (מייצא את כל הקבצים ממונגו לזיפ ושומר ב-GridFS/דיסק)
        try:
            try:
                emit_event("backup_create_full_start", severity="info", user_id=int(user_id))
            except Exception:
                pass
            from io import BytesIO
            import json
            facade = _get_files_facade()
            if facade is None:
                raise RuntimeError("DB unavailable")
            # אסוף את הקבצים של המשתמש (כולל code) — נדרש כדי לכתוב את ה-ZIP.
            # הערה: ברירת המחדל ב-Repository לרשימות עשויה להחזיר ללא שדות כבדים; לכן מבקשים code במפורש.
            try:
                files = facade.get_user_files(
                    user_id,
                    limit=1000,
                    projection={"_id": 1, "file_name": 1, "code": 1},
                ) or []
            except TypeError:
                # תאימות ל-stubs ישנים שלא תומכים ב-projection
                files = facade.get_user_files(user_id, limit=1000) or []
            backup_id = f"backup_{user_id}_{int(__import__('time').time())}"
            buf = BytesIO()
            try:
                with track_performance("backup_create_full_zip"):
                    # High compression to shrink backup size
                    with zipfile.ZipFile(buf, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
                        # כתיבת תוכן הקבצים
                        for doc in files:
                            name = doc.get('file_name') or f"file_{doc.get('_id')}"
                            code = doc.get('code') or ''
                            zf.writestr(name, code)
                        # מטאדטה
                        metadata = {
                            "backup_id": backup_id,
                            "user_id": user_id,
                            "created_at": __import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat(),
                            "backup_type": "manual",
                            "include_versions": True,
                            "file_count": len(files)
                        }
                        zf.writestr('metadata.json', json.dumps(metadata, indent=2))

                # הקפאה ל-bytes פעם אחת בלבד (מונע דליפות של file handles דרך InputFile(BytesIO))
                zip_bytes = buf.getvalue()

                # שמור בהתאם למצב האחסון
                with track_performance("backup_save_bytes"):
                    backup_manager.save_backup_bytes(zip_bytes, metadata)

                # שלח קובץ למשתמש (bytes במקום stream כדי למנוע unraisable/ResourceWarnings)
                await query.message.reply_document(
                    document=InputFile(zip_bytes, filename=f"{backup_id}.zip"),
                    caption=f"✅ גיבוי נוצר בהצלחה\nקבצים: {len(files)} | גודל: {_format_bytes(len(zip_bytes))}"
                )
            finally:
                try:
                    buf.close()
                except Exception:
                    pass
            try:
                emit_event(
                    "backup_create_full_success",
                    severity="info",
                    user_id=int(user_id),
                    backup_id=str(backup_id),
                    files_count=int(len(files)),
                    size_bytes=int(len(zip_bytes)),
                )
            except Exception:
                pass
            await self.show_backup_menu(update, context)
        except Exception as e:
            logger.error(f"Failed creating/sending backup: {e}")
            try:
                # ספירת שגיאות + קוד יציב
                try:
                    from metrics import errors_total  # type: ignore
                    if errors_total is not None:
                        errors_total.labels(code="E_BACKUP_CREATE").inc()
                except Exception:
                    pass
                emit_event("backup_create_full_error", severity="error", user_id=int(user_id), error_code="E_BACKUP_CREATE", error=str(e))
            except Exception:
                pass
            await query.edit_message_text("❌ יצירת הגיבוי נכשלה")
    
    async def _start_full_restore(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        # נשמר לשם תאימות אם יקראו בפועל, מפנה לרשימת גיבויים
        await self._show_backups_list(update, context)
    
    # הוסרה תמיכה בהעלאת ZIP ישירה מהתפריט כדי למנוע מחיקה גורפת בטעות
    
    async def _show_backups_list(self, update: Update, context: ContextTypes.DEFAULT_TYPE, page: Optional[int] = None):
        query = update.callback_query
        user_id = query.from_user.id
        await query.answer()
        highlight_id = context.user_data.pop("backup_highlight_id", None)
        with track_performance("backup_list_backups"):
            backups = backup_manager.list_backups(user_id)
        # מציגים אך ורק קבצי ZIP השייכים למשתמש הנוכחי (סינון נעשה בשכבת השירות)
        # יעד חזרה דינמי לפי מקור הכניסה ("📚" או GitHub)
        zip_back_to = context.user_data.get('zip_back_to')
        # אם מגיעים מתפריט "📚" או מזרימת "העלה קובץ חדש → קבצי ZIP" (github_upload), אל תסנן לפי ריפו
        current_repo = None if zip_back_to in {'files', 'github_upload'} else context.user_data.get('github_backup_context_repo')
        if current_repo:
            filtered = []
            for b in backups:
                try:
                    if getattr(b, 'repo', None) == current_repo:
                        filtered.append(b)
                except Exception:
                    continue
            # תמיד החל סינון לפי ריפו; אם יוצא ריק, יוצג מסר "אין גיבויים לריפו הזה"
            backups = filtered
        backups = self._merge_cached_backups(context, user_id, backups)
        if not backups:
            # קבע יעד חזרה: ל"📚" אם זה המקור, אחרת לתפריט הגיבוי של GitHub אם יש הקשר, אחרת לתפריט הגיבוי הכללי
            if zip_back_to == 'files':
                back_cb = 'files'
            elif zip_back_to == 'github_upload':
                back_cb = 'upload_file'
            elif current_repo is not None or zip_back_to == 'github':
                back_cb = 'github_backup_menu'
            else:
                back_cb = 'backup_menu'
            keyboard = [[InlineKeyboardButton("🔙 חזור", callback_data=back_cb)]]
            msg = "ℹ️ לא נמצאו גיבויים שמורים."
            if current_repo:
                msg = f"ℹ️ לא נמצאו גיבויים עבור הריפו:\n<code>{current_repo}</code>"
            try:
                emit_event("backup_list_empty", severity="info", user_id=int(user_id), repo=str(current_repo or ""), source=str(zip_back_to or ""))
            except Exception:
                pass
            await query.edit_message_text(
                msg,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return
        
        # עימוד תוצאות
        try:
            from config import config as _cfg  # type: ignore
            PAGE_SIZE = int(getattr(_cfg, 'UI_PAGE_SIZE', 10)) if hasattr(_cfg, 'UI_PAGE_SIZE') else 10
        except Exception:
            PAGE_SIZE = 10
        total = len(backups)
        # ברירת מחדל: שמור עמוד אחרון שסיירנו בו אם לא סופק
        try:
            if page is None:
                page = int(context.user_data.get("backup_list_page", 1) or 1)
        except Exception:
            page = 1
        if page < 1:
            page = 1
        total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE if total > 0 else 1
        if page > total_pages:
            page = total_pages
        # שמור את העמוד הנוכחי כדי לשמרו בין פעולות (מחיקה מרובה, סימון, הורדה וכו')
        try:
            context.user_data["backup_list_page"] = page
        except Exception:
            pass
        start = (page - 1) * PAGE_SIZE
        end = min(start + PAGE_SIZE, total)
        items = backups[start:end]
        # חשב גרסאות (vN) לכל ריפו לפי סדר כרונולוגי (הכי ישן = v1)
        repo_to_sorted: Dict[str, list] = {}
        id_to_version: Dict[str, int] = {}
        try:
            from datetime import datetime
            def _key(v: Any) -> float:
                dt = getattr(v, 'created_at', None)
                if isinstance(dt, datetime):
                    return dt.timestamp()
                return 0.0
            for b in backups:
                repo_name = getattr(b, 'repo', None)
                if not repo_name:
                    continue
                repo_to_sorted.setdefault(repo_name, []).append(b)
            for repo_name, arr in repo_to_sorted.items():
                arr.sort(key=_key)
                for idx, b in enumerate(arr, start=1):
                    id_to_version[getattr(b, 'backup_id', '')] = idx
        except Exception:
            id_to_version = {}
        lines = [f"{BTN_BACKUP_ZIPS} שמורים — סה\"כ: {total}\n📄 עמוד {page} מתוך {total_pages}\n"]
        keyboard = []
        delete_mode = bool(context.user_data.get("backup_delete_mode"))
        selected = set(context.user_data.get("backup_delete_selected", set()))
        for info in items:
            highlight = (getattr(info, 'backup_id', '') == highlight_id)
            btype = getattr(info, 'backup_type', 'unknown')
            repo_name = getattr(info, 'repo', None)
            # שורת כותרת לפריט
            if repo_name:
                repo_display = _repo_only(repo_name)
                first_line = f"• {repo_display} — {_format_date(getattr(info, 'created_at', ''))}"
            else:
                # עבור ZIP כללי, הצג שם ידידותי בסגנון הכפתורים
                first_line = f"• BKP zip {getattr(info, 'backup_id', '').replace('backup_', '')} — {_format_date(getattr(info, 'created_at', ''))}"
            lines.append(first_line)
            # שורה שנייה עם גודל | קבצים | גרסה (+דירוג אם קיים)
            try:
                facade = _get_files_facade()
                rating = (facade.get_backup_rating(user_id, info.backup_id) if facade is not None else "") or ""
            except Exception:
                rating = ""
            vnum = id_to_version.get(getattr(info, 'backup_id', ''), 1)
            files_cnt = getattr(info, 'file_count', 0) or 0
            files_txt = f"{files_cnt:,}"
            if delete_mode:
                mark = "✅" if info.backup_id in selected else "⬜️"
                second_line = f"  ↳ {mark} | קבצים: {files_txt} | גרסה: v{vnum}"
            else:
                second_line = f"  ↳ גודל: {_format_bytes(getattr(info, 'total_size', 0))} | קבצים: {files_txt} | גרסה: v{vnum}"
            lines.append(second_line)
            row = []
            if delete_mode:
                mark = "✅" if info.backup_id in selected else "⬜️"
                row.append(InlineKeyboardButton(f"{mark} בחר למחיקה", callback_data=f"backup_toggle_del:{info.backup_id}"))
                # הצג גם כפתור הורדה אך בלי גודל על הכפתור עצמו
                btn_text = _build_download_button_text(info, force_hide_size=True, vnum=vnum, rating=rating)
                if highlight:
                    btn_text = f"✔️ {btn_text}"
                row.append(InlineKeyboardButton(btn_text, callback_data=f"backup_download_id:{info.backup_id}"))
            else:
                # הצג שם מלא של ה‑ZIP על הכפתור לפי התבנית
                # טקסט כפתור בסגנון "BKP zip <name> vN <emoji?> - <date>"
                btn_text = _build_download_button_text(info, force_hide_size=False, vnum=vnum, rating=rating)
                if highlight:
                    btn_text = f"✔️ {btn_text}"
                # במצב העלאה לריפו (GitHub → העלאת קובץ → קבצי ZIP): לחיצה תפתח דפדוף בתוך ה‑ZIP
                if zip_back_to == 'github_upload':
                    row.append(InlineKeyboardButton(btn_text, callback_data=f"gh_upload_zip_browse:{info.backup_id}"))
                else:
                    # ברירת מחדל: מעבר למסך פרטים עם פעולות
                    row.append(InlineKeyboardButton(btn_text, callback_data=f"backup_details:{info.backup_id}"))
            keyboard.append(row)
        # עימוד: הקודם/הבא
        nav = []
        row = build_pagination_row(page, total, PAGE_SIZE, "backup_page_")
        if row:
            nav.extend(row)
        if nav:
            keyboard.append(nav)
        # פעולות נוספות - כפתור חזרה דינמי + מצב מחיקה
        if zip_back_to == 'files':
            back_cb = 'files'
        elif zip_back_to == 'github_upload':
            back_cb = 'upload_file'
        elif current_repo is not None or zip_back_to == 'github':
            back_cb = 'github_backup_menu'
        else:
            back_cb = 'backup_menu'
        controls_row = []
        if delete_mode:
            controls_row.append(InlineKeyboardButton("🗑 אשר ומחק", callback_data="backup_delete_confirm"))
            controls_row.append(InlineKeyboardButton("❌ צא ממצב מחיקה", callback_data="backup_delete_mode_off"))
        else:
            controls_row.append(InlineKeyboardButton("🗑 מחיקה מרובה", callback_data="backup_delete_mode_on"))
        keyboard.append(controls_row)
        keyboard.append([InlineKeyboardButton("🔙 חזור", callback_data=back_cb)])
        await query.edit_message_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(keyboard))
        try:
            emit_event("backup_list_shown", severity="info", user_id=int(user_id), total=int(total), page=int(page))
        except Exception:
            pass

    async def send_rating_prompt(self, update: Update, context: ContextTypes.DEFAULT_TYPE, backup_id: str):
        """שולח הודעת תיוג עם 3 כפתורים עבור גיבוי מסוים."""
        try:
            keyboard = [
                [InlineKeyboardButton("🏆 מצוין", callback_data=f"backup_rate:{backup_id}:excellent")],
                [InlineKeyboardButton("👍 טוב", callback_data=f"backup_rate:{backup_id}:good")],
                [InlineKeyboardButton("🤷 סביר", callback_data=f"backup_rate:{backup_id}:ok")],
            ]
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="תיוג:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        except Exception:
            pass

    async def _show_backup_details(self, update: Update, context: ContextTypes.DEFAULT_TYPE, backup_id: str):
        """מציג תצוגת פרטים עבור גיבוי בודד עם פעולות: הורדה, מחיקה, עריכת תיוג"""
        query = update.callback_query
        await query.answer()
        user_id = query.from_user.id
        info_list = backup_manager.list_backups(user_id)
        match = next((b for b in info_list if b.backup_id == backup_id), None)
        if not match:
            match = self._get_cached_backup(context, user_id, backup_id)
        if not match:
            await query.edit_message_text("❌ הגיבוי לא נמצא")
            return
        # שלוף דירוג נוכחי אם קיים
        try:
            facade = _get_files_facade()
            rating = (facade.get_backup_rating(user_id, backup_id) if facade is not None else "") or ""
        except Exception:
            rating = ""
        # שלוף הערה אם קיימת
        try:
            facade = _get_files_facade()
            note_text = (facade.get_backup_note(user_id, backup_id) if facade is not None else "") or ""
        except Exception:
            note_text = ""
        when = _format_date(getattr(match, 'created_at', ''))
        size_txt = _format_bytes(getattr(match, 'total_size', 0))
        files_cnt = getattr(match, 'file_count', 0) or 0
        repo_name = getattr(match, 'repo', '') or '-'
        lines = [
            f"📦 גיבוי: {backup_id}",
            f"📅 נוצר: {when}",
            f"📁 קבצים: {files_cnt}",
            f"📏 גודל: {size_txt}",
            f"🔖 ריפו: {repo_name}",
        ]
        if rating:
            lines.append(f"🏷 תיוג: {rating}")
        if note_text:
            lines.append(f"📝 הערה: {note_text}")
        kb = [
            [InlineKeyboardButton("⬇️ הורדה", callback_data=f"backup_download_id:{backup_id}")],
            [InlineKeyboardButton("🗑 מחק", callback_data=f"backup_delete_one_confirm:{backup_id}")],
            [InlineKeyboardButton("🏷 ערוך תיוג", callback_data=f"backup_rate_menu:{backup_id}")],
            [InlineKeyboardButton("📝 ערוך הערה" if note_text else "📝 הוסף הערה", callback_data=f"backup_add_note:{backup_id}")],
            [InlineKeyboardButton("🔙 חזור לרשימה", callback_data="backup_list")],
        ]
        await query.edit_message_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(kb))

    async def _ask_backup_note(self, update: Update, context: ContextTypes.DEFAULT_TYPE, backup_id: str):
        """מבקש מהמשתמש להזין הערה לגיבוי ובסיום שומר אותה במסד"""
        query = update.callback_query
        await query.answer()
        user_id = query.from_user.id
        # שלוף הערה קיימת אם יש
        try:
            facade = _get_files_facade()
            existing = (facade.get_backup_note(user_id, backup_id) if facade is not None else "") or ""
        except Exception:
            existing = ""
        try:
            context.user_data['waiting_for_backup_note_for'] = backup_id
            prompt = "✏️ הקלד/י הערה לגיבוי (עד 1000 תווים).\nשלח/י טקסט עכשיו.\n\n"
            if existing:
                prompt += f"הערה נוכחית: {existing}\n"
            await query.edit_message_text(prompt, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 חזרה", callback_data=f"backup_details:{backup_id}")]]))
        except Exception as e:
            await query.edit_message_text(f"❌ שגיאה בפתיחת עריכת הערה: {e}")

    
    async def _restore_by_id(self, update: Update, context: ContextTypes.DEFAULT_TYPE, backup_id: str):
        query = update.callback_query
        user_id = query.from_user.id
        await query.edit_message_text("⏳ משחזר מגיבוי נבחר...")
        # מצא את קובץ הגיבוי
        info_list = backup_manager.list_backups(user_id)
        match = next((b for b in info_list if b.backup_id == backup_id), None)
        if not match:
            match = self._get_cached_backup(context, user_id, backup_id)
        if not match or not match.file_path or not os.path.exists(match.file_path):
            await query.edit_message_text("❌ הגיבוי לא נמצא בדיסק")
            return
        try:
            with track_performance("backup_restore_full"):
                results = backup_manager.restore_from_backup(user_id=user_id, backup_path=match.file_path, overwrite=True, purge=True)
            restored = results.get('restored_files', 0)
            errors = results.get('errors', [])
            msg = f"✅ שוחזרו {restored} קבצים בהצלחה מגיבוי {backup_id}"
            if errors:
                msg += f"\n⚠️ שגיאות: {len(errors)}"
            await query.edit_message_text(msg)
        except Exception as e:
            await query.edit_message_text(f"❌ שגיאה בשחזור: {e}")
    
    async def _download_by_id(self, update: Update, context: ContextTypes.DEFAULT_TYPE, backup_id: str):
        query = update.callback_query
        user_id = query.from_user.id
        await query.answer()
        info_list = backup_manager.list_backups(user_id)
        match = next((b for b in info_list if b.backup_id == backup_id), None)
        if not match:
            match = self._get_cached_backup(context, user_id, backup_id)
        if not match or not match.file_path or not os.path.exists(match.file_path):
            await query.edit_message_text("❌ הגיבוי לא נמצא בדיסק")
            return
        try:
            # בנה שם קובץ ידידותי בעת שליחה — ללא תווי "/" בשם
            friendly = None
            try:
                repo_name = getattr(match, 'repo', None)
                created_at = getattr(match, 'created_at', None)
                date_str = _format_date(created_at)
                # המרה לפורמט בטוח לשם קובץ (ללא "/")
                date_str = date_str.replace('/', '-').replace(':', '.')
                # הוסף אימוג'י דירוג אם קיים
                try:
                    facade = _get_files_facade()
                    rating = (facade.get_backup_rating(user_id, backup_id) if facade is not None else "") or ""
                except Exception:
                    rating = ""
                emoji = rating.split()[0] if isinstance(rating, str) and rating else ""
                if repo_name:
                    # גרסת vN לפי מיקום ברשימת אותו ריפו
                    infos = backup_manager.list_backups(user_id)
                    vcount = len([b for b in infos if getattr(b, 'repo', None) == repo_name])
                    name_part = _repo_only(repo_name)
                    friendly = f"BKP zip {name_part} v{vcount}{(' ' + emoji) if emoji else ''} - {date_str}.zip"
                else:
                    friendly = f"BKP zip {backup_id.replace('backup_', '')}{(' ' + emoji) if emoji else ''} - {date_str}.zip"
            except Exception:
                friendly = None
            with track_performance("backup_download_zip_bytes"):
                with open(match.file_path, 'rb') as f:
                    await query.message.reply_document(
                        document=InputFile(f, filename=(friendly or os.path.basename(match.file_path))),
                        caption=f"📦 {backup_id} — {_format_bytes(os.path.getsize(match.file_path))}"
                    )
            # השאר בתצוגת רשימה — רענן את הרשימה
            try:
                await self._show_backups_list(update, context)
            except Exception as e:
                # התמודד עם מקרה של Message is not modified
                msg = str(e).lower()
                if "message is not modified" not in msg:
                    raise
        except Exception as e:
            await query.edit_message_text(f"❌ שגיאה בשליחת קובץ הגיבוי: {e}")