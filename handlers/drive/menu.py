from typing import Any, Dict, Optional
import os
import asyncio

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
try:
    from telegram.error import BadRequest
except Exception:  # pragma: no cover
    BadRequest = Exception  # type: ignore[assignment]
from telegram.ext import ContextTypes

from services import google_drive_service as gdrive
from config import config
from file_manager import backup_manager
from database import db


class GoogleDriveMenuHandler:
    def __init__(self):
        self.sessions: Dict[int, Dict[str, Any]] = {}

    def _session(self, user_id: int) -> Dict[str, Any]:
        if user_id not in self.sessions:
            self.sessions[user_id] = {}
        return self.sessions[user_id]

    def _is_uploading(self, user_id: int) -> bool:
        return bool(self._session(user_id).get("uploading"))

    def _begin_upload(self, user_id: int) -> bool:
        sess = self._session(user_id)
        if sess.get("uploading"):
            return False
        sess["uploading"] = True
        return True

    def _end_upload(self, user_id: int) -> None:
        try:
            self._session(user_id)["uploading"] = False
        except Exception:
            pass

    async def menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        # Feature flag: allow fallback to old behavior if disabled
        if not config.DRIVE_MENU_V2:
            query = update.callback_query if update.callback_query else None
            if query:
                await query.answer()
                await query.edit_message_text("התכונה כבויה כרגע (DRIVE_MENU_V2=false)")
            else:
                await update.message.reply_text("התכונה כבויה כרגע (DRIVE_MENU_V2=false)")
            return
        query = update.callback_query if update.callback_query else None
        if query:
            await query.answer()
            send = query.edit_message_text
        else:
            send = update.message.reply_text

        user_id = update.effective_user.id
        tokens = db.get_drive_tokens(user_id)

        # נחשיב "מחובר" אם יש טוקנים שמורים; בדיקת שירות בפועל תעשה לפני העלאה
        # זה מונע מצב מבלבל שבו מוצג "לא מחובר" מיד אחרי התחברות מוצלחת
        service_ready = bool(tokens)
        if not service_ready:
            kb = [[InlineKeyboardButton("🔐 התחבר ל‑Drive", callback_data="drive_auth")]]
            await send("Google Drive\n\nלא מחובר. התחבר כדי לגבות לקבצי Drive.", reply_markup=InlineKeyboardMarkup(kb))
            return

        # Connected -> show main backup selection directly per requested flow
        await self._render_simple_selection(update, context, header_prefix="Google Drive — מחובר\n")

    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        user_id = query.from_user.id
        data = query.data
        await query.answer()

        if data == "drive_menu":
            await self.menu(update, context)
            return
        # Backward compatibility: map old callback to new one
        if data == "drive_advanced":
            data = "drive_sel_adv"
        if data == "drive_auth":
            __import__('logging').getLogger(__name__).warning(f"Drive: start auth by user {user_id}")
            try:
                flow = gdrive.start_device_authorization(user_id)
            except Exception as e:
                # הצג שגיאה ידידותית כאשר קונפיגורציית OAuth חסרה/שגויה או כשיש בעיית רשת
                kb = [[InlineKeyboardButton("🔙 חזרה", callback_data="drive_menu")]]
                await query.edit_message_text(
                    f"❌ לא ניתן להתחבר ל‑Drive.\n{e}\n\nבדוק שהוגדר GOOGLE_CLIENT_ID (ו‑GOOGLE_CLIENT_SECRET אם נדרש) ושההרשאות תקינות.",
                    reply_markup=InlineKeyboardMarkup(kb)
                )
                return
            sess = self._session(user_id)
            sess["device_code"] = flow.get("device_code")
            sess["interval"] = max(3, int(flow.get("interval", 5)))
            sess["auth_expires_at"] = int(__import__('time').time()) + int(flow.get("expires_in", 1800))
            # schedule polling job
            jobs = context.bot_data.setdefault("drive_auth_jobs", {})
            # cancel old if exists
            old = jobs.get(user_id)
            if old:
                try:
                    old.schedule_removal()
                except Exception:
                    pass
            async def _poll_once(ctx: ContextTypes.DEFAULT_TYPE):
                try:
                    uid = ctx.job.data.get("user_id")
                    chat_id = ctx.job.data.get("chat_id")
                    message_id = ctx.job.data.get("message_id")
                    s = self._session(uid)
                    dc = s.get("device_code")
                    if not dc:
                        return
                    # Expiry guard: stop polling and notify
                    import time as _t
                    exp = s.get("auth_expires_at") or 0
                    if exp and _t.time() > exp:
                        try:
                            ctx.job.schedule_removal()
                        except Exception:
                            pass
                        ctx.bot_data.setdefault("drive_auth_jobs", {}).pop(uid, None)
                        s.pop("device_code", None)
                        try:
                            await ctx.bot.edit_message_text(
                                chat_id=chat_id,
                                message_id=message_id,
                                text="⌛ פג תוקף בקשת ההתחברות. לחץ שוב על \"התחבר ל‑Drive\".",
                                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔐 התחבר ל‑Drive", callback_data="drive_auth")]])
                            )
                        except Exception:
                            pass
                        return
                    tokens = gdrive.poll_device_token(dc)
                    # None => עדיין ממתינים; dict עם error => לא לשמור, להמתין
                    if not tokens or (isinstance(tokens, dict) and tokens.get("error")):
                        return
                    # הצלחה: שמירה והודעה
                    gdrive.save_tokens(uid, tokens)  # type: ignore[arg-type]
                    try:
                        ctx.job.schedule_removal()
                    except Exception:
                        pass
                    jobs.pop(uid, None)
                    s.pop("device_code", None)
                    try:
                        await ctx.bot.edit_message_text(
                            chat_id=chat_id,
                            message_id=message_id,
                            text="✅ חיבור ל‑Drive הושלם!"
                        )
                    except Exception:
                        pass
                except Exception:
                    pass
            try:
                job = context.application.job_queue.run_repeating(
                    _poll_once,
                    interval=sess["interval"],
                    first=5,
                    name=f"drive_auth_{user_id}",
                    data={"user_id": user_id, "chat_id": query.message.chat_id, "message_id": query.message.message_id}
                )
                jobs[user_id] = job
            except Exception:
                pass
            # show instruction with buttons
            # enable manual code paste fallback
            context.user_data["waiting_for_drive_code"] = True
            text = (
                "🔐 התחברות ל‑Google Drive\n\n"
                f"גש לכתובת: {flow.get('verification_url')}\n"
                f"קוד: <code>{flow.get('user_code')}</code>\n\n"
                "ℹ️ טיפ: לחצו על הקוד כדי להעתיק אותו ללוח, ואז לחצו על הקישור והדביקו את הקוד בדפדפן.\n\n"
                "לאחר האישור, לחץ על ׳🔄 בדוק חיבור׳ או המתן לאימות אוטומטי."
            )
            kb = [
                [InlineKeyboardButton("🔄 בדוק חיבור", callback_data="drive_poll_once")],
                [InlineKeyboardButton("❌ בטל", callback_data="drive_cancel_auth")],
            ]
            await query.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))
            return
        if data == "drive_poll_once":
            __import__('logging').getLogger(__name__).debug(f"Drive: manual poll token by user {user_id}")
            sess = self._session(user_id)
            dc = sess.get("device_code")
            if not dc:
                await query.answer("אין בקשת התחברות פעילה", show_alert=True)
                return
            try:
                tokens = gdrive.poll_device_token(dc)
            except Exception:
                tokens = None
            if not tokens:
                # Visible feedback in message
                text = (
                    "🔐 התחברות ל‑Google Drive\n\n"
                    "⌛ עדיין ממתינים לאישור בדפדפן…\n\n"
                    "ℹ️ טיפ: לחצו על הקוד שהוצג בהודעה הקודמת כדי להעתיק, פתחו את הקישור והדביקו את הקוד בדפדפן.\n\n"
                    "לאחר האישור, לחץ על ׳🔄 בדוק חיבור׳ או המתן לאימות אוטומטי."
                )
                kb = [
                    [InlineKeyboardButton("🔄 בדוק חיבור", callback_data="drive_poll_once")],
                    [InlineKeyboardButton("❌ בטל", callback_data="drive_cancel_auth")],
                ]
                await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))
                return
            if isinstance(tokens, dict) and tokens.get("error"):
                err = tokens.get("error")
                desc = tokens.get("error_description") or "בקשה נדחתה. נא לאשר בדפדפן ולנסות שוב."
                kb = [
                    [InlineKeyboardButton("🔄 בדוק חיבור", callback_data="drive_poll_once")],
                    [InlineKeyboardButton("❌ בטל", callback_data="drive_cancel_auth")],
                ]
                await query.edit_message_text(f"❌ שגיאה: {err}\n{desc}", reply_markup=InlineKeyboardMarkup(kb))
                return
            gdrive.save_tokens(user_id, tokens)
            # cancel background job if exists
            jobs = context.bot_data.setdefault("drive_auth_jobs", {})
            job = jobs.pop(user_id, None)
            if job:
                try:
                    job.schedule_removal()
                except Exception:
                    pass
            __import__('logging').getLogger(__name__).warning(f"Drive: auth completed for user {user_id}")
            await query.edit_message_text("✅ חיבור ל‑Drive הושלם!")
            await self.menu(update, context)
            return
        if data == "drive_cancel_auth":
            sess = self._session(user_id)
            sess.pop("device_code", None)
            jobs = context.bot_data.setdefault("drive_auth_jobs", {})
            job = jobs.pop(user_id, None)
            if job:
                try:
                    job.schedule_removal()
                except Exception:
                    pass
            await query.edit_message_text("ביטלת את ההתחברות ל‑Drive.")
            return
        if data == "drive_backup_now":
            await self._render_simple_selection(update, context)
            return
        if data == "drive_sel_zip":
            # בחר קטגוריית ZIP בלבד (ללא העלאה מיידית); ההעלאה תתבצע רק בלחיצה על "אישור"
            # הצג הודעה אם אין ZIPים שמורים כדי שהמשתמש ידע מה יקרה באישור
            try:
                existing = backup_manager.list_backups(user_id) or []
                saved_zips = [b for b in existing if str(getattr(b, 'file_path', '')).endswith('.zip')]
            except Exception:
                saved_zips = []
            sess = self._session(user_id)
            if sess.get("selected_category") == "zip":
                await query.answer("כבר נבחר 'קבצי ZIP'", show_alert=False)
                return
            sess["selected_category"] = "zip"
            prefix = "ℹ️ לא נמצאו קבצי ZIP שמורים בבוט. באישור לא יועלה דבר.\n\n" if not saved_zips else "✅ נבחר: קבצי ZIP\n\n"
            await self._render_simple_selection(update, context, header_prefix=prefix)
            return
        if data == "drive_sel_all":
            # בחר קטגוריית "הכל" (ללא העלאה מיידית); ההעלאה תתבצע רק בלחיצה על "אישור"
            sess = self._session(user_id)
            if sess.get("selected_category") == "all":
                await query.answer("כבר נבחר 'הכל'", show_alert=False)
                return
            sess["selected_category"] = "all"
            await self._render_simple_selection(update, context, header_prefix="✅ נבחר: הכל\n\n")
            return
        if data == "drive_sel_adv":
            await self._render_advanced_menu(update, context)
            return
        if data in {"drive_adv_by_repo", "drive_adv_large", "drive_adv_other"}:
            # Ensure Drive service ready
            if gdrive.get_drive_service(user_id) is None:
                kb = [
                    [InlineKeyboardButton("🔐 התחבר ל‑Drive", callback_data="drive_auth")],
                    [InlineKeyboardButton("🔙 חזרה", callback_data="drive_sel_adv")],
                ]
                await query.edit_message_text("❌ לא ניתן לגשת ל‑Drive כרגע. נסה להתחבר מחדש או לבדוק הרשאות.", reply_markup=InlineKeyboardMarkup(kb))
                return
            category = {
                "drive_adv_by_repo": "by_repo",
                "drive_adv_large": "large",
                "drive_adv_other": "other",
            }[data]
            sess = self._session(user_id)
            if sess.get("adv_multi"):
                selected = sess.setdefault("adv_selected", set())
                selected.add(category)
                await self._render_advanced_menu(update, context, header_prefix="✅ נוסף לבחירה. ניתן לבחור עוד אפשרויות או להעלות.\n\n")
            else:
                # Immediate upload per category with better empty-state handling
                if category == "by_repo":
                    grouped = gdrive.create_repo_grouped_zip_bytes(user_id)
                    if not grouped:
                        await query.edit_message_text("ℹ️ לא נמצאו קבצים מקוטלגים לפי ריפו להעלאה.")
                        return
                    ok_any = False
                    for repo_name, suggested, data_bytes in grouped:
                        friendly = gdrive.compute_friendly_name(user_id, "by_repo", repo_name, content_sample=data_bytes[:1024])
                        sub_path = gdrive.compute_subpath("by_repo", repo_name)
                        fid = gdrive.upload_bytes(user_id, friendly, data_bytes, sub_path=sub_path)
                        ok_any = ok_any or bool(fid)
                    if ok_any:
                        await query.edit_message_text("✅ הועלו גיבויי ריפו לפי תיקיות")
                    else:
                        kb = [
                            [InlineKeyboardButton("🔐 התחבר ל‑Drive", callback_data="drive_auth")],
                            [InlineKeyboardButton("🔙 חזרה", callback_data="drive_sel_adv")],
                        ]
                        await query.edit_message_text("❌ כשל בהעלאה. נסה להתחבר מחדש או לבדוק הרשאות.", reply_markup=InlineKeyboardMarkup(kb))
                else:
                    # Pre-check category has files
                    try:
                        from database import db as _db
                        has_any = False
                        if category == "large":
                            large_files, _ = _db.get_user_large_files(user_id, page=1, per_page=1)
                            has_any = bool(large_files)
                        elif category == "other":
                            files = _db.get_user_files(user_id, limit=1) or []
                            # other = not repo tagged
                            for d in files:
                                tags = d.get('tags') or []
                                if not any((t or '').startswith('repo:') for t in tags):
                                    has_any = True
                                    break
                    except Exception:
                        has_any = True
                    if not has_any:
                        label_map = {"large": "קבצים גדולים", "other": "שאר קבצים"}
                        await query.edit_message_text(f"ℹ️ אין פריטים זמינים בקטגוריה: {label_map.get(category, category)}.")
                        return
                    fn, data_bytes = gdrive.create_full_backup_zip_bytes(user_id, category=category)
                    from config import config as _cfg
                    friendly = gdrive.compute_friendly_name(user_id, category, getattr(_cfg, 'BOT_LABEL', 'CodeBot') or 'CodeBot', content_sample=data_bytes[:1024])
                    sub_path = gdrive.compute_subpath(category)
                    fid = gdrive.upload_bytes(user_id, friendly, data_bytes, sub_path=sub_path)
                    if fid:
                        await query.edit_message_text("✅ גיבוי הועלה ל‑Drive")
                    else:
                        kb = [
                            [InlineKeyboardButton("🔐 התחבר ל‑Drive", callback_data="drive_auth")],
                            [InlineKeyboardButton("🔙 חזרה", callback_data="drive_sel_adv")],
                        ]
                        await query.edit_message_text("❌ כשל בהעלאה. נסה להתחבר מחדש או לבדוק הרשאות.", reply_markup=InlineKeyboardMarkup(kb))
            return
        if data == "drive_adv_multi_toggle":
            sess = self._session(user_id)
            sess["adv_multi"] = not bool(sess.get("adv_multi", False))
            multi_on = bool(sess.get("adv_multi", False))
            kb = [
                [InlineKeyboardButton("לפי ריפו", callback_data="drive_adv_by_repo")],
                [InlineKeyboardButton("קבצים גדולים", callback_data="drive_adv_large")],
                [InlineKeyboardButton("שאר קבצים", callback_data="drive_adv_other")],
                [InlineKeyboardButton(("✅ אפשרות מרובה" if multi_on else "⬜ אפשרות מרובה"), callback_data="drive_adv_multi_toggle")],
                [InlineKeyboardButton("⬆️ העלה נבחרים", callback_data="drive_adv_upload_selected")],
                [InlineKeyboardButton("🔙 חזרה", callback_data="drive_backup_now")],
            ]
            await query.edit_message_text("בחר קטגוריה מתקדמת:", reply_markup=InlineKeyboardMarkup(kb))
            return
        if data == "drive_adv_upload_selected":
            sess = self._session(user_id)
            cats = list(sess.get("adv_selected", set()) or [])
            if not cats:
                await query.answer("לא נבחרו אפשרויות", show_alert=True)
                return
            uploaded_any = False
            for c in cats:
                if c == "by_repo":
                    grouped = gdrive.create_repo_grouped_zip_bytes(user_id)
                    for repo_name, suggested, data_bytes in grouped:
                        friendly = gdrive.compute_friendly_name(user_id, "by_repo", repo_name, content_sample=data_bytes[:1024])
                        sub_path = gdrive.compute_subpath("by_repo", repo_name)
                        fid = gdrive.upload_bytes(user_id, friendly, data_bytes, sub_path=sub_path)
                        uploaded_any = uploaded_any or bool(fid)
                else:
                    fn, data_bytes = gdrive.create_full_backup_zip_bytes(user_id, category=c)
                    from config import config as _cfg
                    friendly = gdrive.compute_friendly_name(user_id, c, getattr(_cfg, 'BOT_LABEL', 'CodeBot') or 'CodeBot', content_sample=data_bytes[:1024])
                    sub_path = gdrive.compute_subpath(c)
                    fid = gdrive.upload_bytes(user_id, friendly, data_bytes, sub_path=sub_path)
                    uploaded_any = uploaded_any or bool(fid)
            sess["adv_selected"] = set()
            if uploaded_any:
                await query.edit_message_text("✅ הועלו הגיבויים שנבחרו")
            else:
                kb = [
                    [InlineKeyboardButton("🔐 התחבר ל‑Drive", callback_data="drive_auth")],
                    [InlineKeyboardButton("🔙 חזרה", callback_data="drive_sel_adv")],
                ]
                await query.edit_message_text("❌ כשל בהעלאה. נסה להתחבר מחדש או לבדוק הרשאות.", reply_markup=InlineKeyboardMarkup(kb))
            return
        if data == "drive_choose_folder":
            # Remember current simple menu context
            self._session(user_id)["last_menu"] = "simple"
            await self._render_choose_folder_simple(update, context)
            return
        if data == "drive_choose_folder_adv":
            # Advanced folder selection includes automatic arrangement explanation
            self._session(user_id)["last_menu"] = "adv"
            explain = (
                "סידור תיקיות אוטומטי: הבוט יסדר בתוך 'גיבויי_קודלי' לפי קטגוריות ותאריכים,\n"
                "וב'לפי ריפו' גם תת‑תיקיות לפי שם הריפו."
            )
            kb = [
                [InlineKeyboardButton("🤖 סידור תיקיות אוטומטי (כמו בבוט)", callback_data="drive_folder_auto")],
                [InlineKeyboardButton("📂 גיבויי_קודלי (ברירת מחדל)", callback_data="drive_folder_default")],
                [InlineKeyboardButton("✏️ הגדר נתיב מותאם (שלח טקסט)", callback_data="drive_folder_set")],
                [InlineKeyboardButton("🔙 חזרה", callback_data="drive_sel_adv")],
            ]
            await query.edit_message_text(f"בחר תיקיית יעד:\n\n{explain}", reply_markup=InlineKeyboardMarkup(kb))
            return
        if data == "drive_folder_default":
            fid = gdrive.get_or_create_default_folder(user_id)
            # Update session label
            sess = self._session(user_id)
            sess["target_folder_label"] = "גיבויי_קודלי"
            sess["target_folder_auto"] = False
            # Return to proper menu depending on origin (אל תציג כשל גם אם לא הצלחנו ליצור בפועל כרגע)
            await self._render_after_folder_selection(update, context, success=True)
            return
        if data == "drive_folder_auto":
            # Auto-arrangement: keep default folder but mark label as automatic
            fid = gdrive.get_or_create_default_folder(user_id)
            sess = self._session(user_id)
            sess["target_folder_label"] = "אוטומטי"
            sess["target_folder_auto"] = True
            await self._render_after_folder_selection(update, context, success=bool(fid))
            return
        if data == "drive_folder_set":
            context.user_data["waiting_for_drive_folder_path"] = True
            kb = [
                [InlineKeyboardButton("🔙 חזרה", callback_data="drive_folder_back")],
                [InlineKeyboardButton("❌ ביטול", callback_data="drive_folder_cancel")],
            ]
            await query.edit_message_text(
                "שלח נתיב תיקייה (למשל: Project/Backups/Code) — ניצור אם לא קיים",
                reply_markup=InlineKeyboardMarkup(kb)
            )
            return
        if data == "drive_folder_back":
            # חזרה למסך בחירת תיקיית יעד לפי הקשר אחרון
            context.user_data.pop("waiting_for_drive_folder_path", None)
            last = self._session(user_id).get("last_menu")
            if last == "adv":
                await self._render_choose_folder_adv(update, context)
            else:
                await self._render_choose_folder_simple(update, context)
            return
        if data == "drive_folder_cancel":
            # ביטול מצב הזנת נתיב וחזרה לתפריט לפי הקשר
            context.user_data.pop("waiting_for_drive_folder_path", None)
            last = self._session(user_id).get("last_menu")
            if last == "adv":
                await self._render_advanced_menu(update, context)
            else:
                await self._render_simple_selection(update, context)
            return
        if data == "drive_schedule":
            current = (db.get_drive_prefs(user_id) or {}).get("schedule")
            def label(key: str, text: str) -> str:
                return ("✅ " + text) if current == key else text
            back_cb = "drive_sel_adv" if self._session(user_id).get("last_menu") == "adv" else "drive_backup_now"
            kb = [
                [InlineKeyboardButton(label("daily", "כל יום"), callback_data="drive_set_schedule:daily")],
                [InlineKeyboardButton(label("every3", "כל 3 ימים"), callback_data="drive_set_schedule:every3")],
                [InlineKeyboardButton(label("weekly", "כל שבוע"), callback_data="drive_set_schedule:weekly")],
                [InlineKeyboardButton(label("biweekly", "פעם בשבועיים"), callback_data="drive_set_schedule:biweekly")],
                [InlineKeyboardButton(label("monthly", "פעם בחודש"), callback_data="drive_set_schedule:monthly")],
                [InlineKeyboardButton("⛔ בטל תזמון", callback_data="drive_set_schedule:off")],
                [InlineKeyboardButton("🔙 חזרה", callback_data=back_cb)],
            ]
            await query.edit_message_text("בחר תדירות גיבוי אוטומטי:", reply_markup=InlineKeyboardMarkup(kb))
            return
        if data.startswith("drive_set_schedule:"):
            key = data.split(":", 1)[1]
            # Save preference
            if key == "off":
                db.save_drive_prefs(user_id, {"schedule": None})
                # cancel job if exists
                jobs = context.bot_data.setdefault("drive_schedule_jobs", {})
                job = jobs.pop(user_id, None)
                if job:
                    try:
                        job.schedule_removal()
                    except Exception:
                        pass
                await query.edit_message_text("⛔ תזמון בוטל")
                return
            db.save_drive_prefs(user_id, {"schedule": key})
            # schedule job
            interval_map = {
                "daily": 24 * 3600,
                "every3": 3 * 24 * 3600,
                "weekly": 7 * 24 * 3600,
                "biweekly": 14 * 24 * 3600,
                "monthly": 30 * 24 * 3600,
            }
            seconds = interval_map.get(key, 24 * 3600)

            async def _scheduled_backup_cb(ctx: ContextTypes.DEFAULT_TYPE):
                try:
                    uid = ctx.job.data["user_id"]
                    ok = gdrive.perform_scheduled_backup(uid)
                    if ok:
                        await ctx.bot.send_message(chat_id=uid, text="☁️ גיבוי אוטומטי ל‑Drive הושלם בהצלחה")
                except Exception:
                    pass

            try:
                jobs = context.bot_data.setdefault("drive_schedule_jobs", {})
                # cancel existing
                old = jobs.get(user_id)
                if old:
                    try:
                        old.schedule_removal()
                    except Exception:
                        pass
                job = context.application.job_queue.run_repeating(
                    _scheduled_backup_cb, interval=seconds, first=10, name=f"drive_{user_id}", data={"user_id": user_id}
                )
                jobs[user_id] = job
            except Exception:
                pass
            # Re-render menu to reflect updated schedule label
            if self._session(user_id).get("last_menu") == "adv":
                await self._render_advanced_menu(update, context, header_prefix="✅ תזמון נשמר\n\n")
            else:
                await self._render_simple_selection(update, context, header_prefix="✅ תזמון נשמר\n\n")
            return
        if data == "drive_logout":
            # Ask for confirmation before logging out
            kb = [
                [InlineKeyboardButton("✅ התנתק", callback_data="drive_logout_do")],
                [InlineKeyboardButton("❌ בטל", callback_data="drive_backup_now")],
            ]
            await query.edit_message_text("האם להתנתק מ‑Google Drive?", reply_markup=InlineKeyboardMarkup(kb))
            return
        if data == "drive_logout_do":
            __import__('logging').getLogger(__name__).warning(f"Drive: logout by user {user_id}")
            ok = db.delete_drive_tokens(user_id)
            await query.edit_message_text("🚪נותקת מ‑Google Drive" if ok else "❌ לא בוצעה התנתקות")
            return
        if data == "drive_simple_confirm":
            # בצע את הפעולה שנבחרה רק עכשיו
            sess = self._session(user_id)
            selected = sess.get("selected_category")
            if not selected:
                await query.answer("לא נבחר מה לגבות", show_alert=True)
                return
            # בדיקת שירות רק בשלב ביצוע
            if gdrive.get_drive_service(user_id) is None:
                kb = [
                    [InlineKeyboardButton("🔐 התחבר ל‑Drive", callback_data="drive_auth")],
                    [InlineKeyboardButton("🔙 חזרה", callback_data="drive_backup_now")],
                ]
                await query.edit_message_text("❌ לא ניתן לגשת ל‑Drive כרגע. נסה להתחבר מחדש או לבדוק הרשאות.", reply_markup=InlineKeyboardMarkup(kb))
                return
            if selected == "zip":
                try:
                    existing = backup_manager.list_backups(user_id) or []
                    saved_zips = [b for b in existing if str(getattr(b, 'file_path', '')).endswith('.zip')]
                except Exception:
                    saved_zips = []
                if not saved_zips:
                    kb = [
                        [InlineKeyboardButton("📦 צור ZIP שמור בבוט", callback_data="drive_make_zip_now")],
                        [InlineKeyboardButton("🔙 חזרה", callback_data="drive_backup_now")],
                    ]
                    await query.edit_message_text("ℹ️ לא נמצאו קבצי ZIP שמורים בבוט. אפשר ליצור עכשיו ZIP שמור בבוט או לבחור 🧰 הכל.", reply_markup=InlineKeyboardMarkup(kb))
                    return
                # פידבק מיידי לפני פעולת העלאה שעלולה לקחת זמן
                try:
                    await query.edit_message_text("⏳ מעלה קבצי ZIP ל‑Drive…")
                except Exception:
                    pass
                # הרצת ההעלאה בת׳רד נפרד כדי לא לחסום את הלולאה האסינכרונית
                count, ids = await asyncio.to_thread(gdrive.upload_all_saved_zip_backups, user_id)
                if count <= 0:
                    kb = [[InlineKeyboardButton("🔙 חזרה", callback_data="drive_backup_now")]]
                    await query.edit_message_text("❌ ההעלאה נכשלה או לא הועלו קבצים. נסה שוב מאוחר יותר.", reply_markup=InlineKeyboardMarkup(kb))
                    return
                sess["zip_done"] = True
                sess["last_upload"] = "zip"
                await self._render_simple_selection(update, context, header_prefix=f"✅ הועלו {count} גיבויי ZIP ל‑Drive\n\n")
                return
            if selected == "all":
                # פידבק מיידי לפני יצירת ZIP מלא והעלאה
                try:
                    await query.edit_message_text("⏳ מכין גיבוי מלא ומעלה ל‑Drive…")
                except Exception:
                    pass
                from config import config as _cfg
                # יצירת ZIP והרצה בת׳רד נפרד
                fn, data_bytes = await asyncio.to_thread(gdrive.create_full_backup_zip_bytes, user_id, "all")
                friendly = gdrive.compute_friendly_name(user_id, "all", getattr(_cfg, 'BOT_LABEL', 'CodeBot') or 'CodeBot', content_sample=data_bytes[:1024])
                sub_path = gdrive.compute_subpath("all")
                # העלאה בת׳רד נפרד
                fid = await asyncio.to_thread(gdrive.upload_bytes, user_id, friendly, data_bytes, None, sub_path)
                if fid:
                    sess["all_done"] = True
                    sess["last_upload"] = "all"
                    await self._render_simple_selection(update, context, header_prefix="✅ גיבוי מלא הועלה ל‑Drive\n\n")
                else:
                    kb = [
                        [InlineKeyboardButton("🔐 התחבר ל‑Drive", callback_data="drive_auth")],
                        [InlineKeyboardButton("🔙 חזרה", callback_data="drive_backup_now")],
                    ]
                    await query.edit_message_text("❌ כשל בהעלאה. נסה להתחבר מחדש או לבדוק הרשאות.", reply_markup=InlineKeyboardMarkup(kb))
                return
        if data == "drive_adv_confirm":
            await self._render_adv_summary(update, context)
            return
        if data == "drive_make_zip_now":
            # צור גיבוי מלא ושמור אותו בבוט (לא בדרייב), כדי שיהיו ZIPים זמינים להעלאה
            from services import backup_service as _backup_service
            await query.edit_message_text("⏳ יוצר ZIP שמור בבוט…")
            try:
                # נשתמש בשירות הגיבוי המקומי ליצירת ZIP ושמירה
                fn, data_bytes = gdrive.create_full_backup_zip_bytes(user_id, category="all")
                ok = _backup_service.save_backup_bytes(data_bytes, {"backup_id": os.path.splitext(fn)[0], "user_id": user_id, "backup_type": "manual"})
                if ok:
                    await query.edit_message_text("✅ נוצר ZIP שמור בבוט. עכשיו ניתן לבחור שוב '📦 קבצי ZIP' להעלאה ל‑Drive.")
                else:
                    await query.edit_message_text("❌ יצירת ה‑ZIP נכשלה. נסה שוב מאוחר יותר.")
            except Exception:
                await query.edit_message_text("❌ יצירת ה‑ZIP נכשלה. נסה שוב מאוחר יותר.")
            return

    async def handle_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
        text = (update.message.text or "").strip()
        if context.user_data.get("waiting_for_drive_code"):
            # User pasted one-time code; exchange by polling device flow once
            context.user_data["waiting_for_drive_code"] = False
            sess = self._session(update.effective_user.id)
            device_code = sess.get("device_code")
            if not device_code:
                await update.message.reply_text("❌ פג תוקף הבקשה. נסה שוב.")
                return True
            tokens = gdrive.poll_device_token(device_code)
            if not tokens:
                await update.message.reply_text("⌛ עדיין ממתינים לאישור. אשר בדפדפן ונסה שוב לשלוח את הקוד.")
                context.user_data["waiting_for_drive_code"] = True
                return True
            saved = gdrive.save_tokens(update.effective_user.id, tokens)
            if saved:
                await update.message.reply_text("✅ חיבור ל‑Drive הושלם! שלח /drive כדי להתחיל לגבות.")
            else:
                await update.message.reply_text("❌ לא ניתן לשמור את החיבור.")
            return True
        if context.user_data.get("waiting_for_drive_folder_path"):
            context.user_data["waiting_for_drive_folder_path"] = False
            path = text
            fid = gdrive.ensure_path(update.effective_user.id, path)
            if fid:
                # Save label for buttons
                sess = self._session(update.effective_user.id)
                sess["target_folder_label"] = path
                sess["target_folder_auto"] = False
                await update.message.reply_text("✅ תיקיית יעד עודכנה בהצלחה")
            else:
                await update.message.reply_text("❌ לא ניתן להגדיר את התיקייה. ודא בהרשאות Drive.")
            return True
        return False


    # ===== Helpers =====
    def _schedule_button_label(self, user_id: int) -> str:
        prefs = db.get_drive_prefs(user_id) or {}
        key = prefs.get("schedule")
        mapping = {
            "daily": "🕑 כל יום",
            "every3": "🕑 כל 3 ימים",
            "weekly": "🕑 פעם בשבוע",
            "biweekly": "🕑 פעם בשבועיים",
            "monthly": "🕑 פעם בחודש",
        }
        return mapping.get(key) or "🗓 זמני גיבוי"

    def _compose_selection_header(self, user_id: int) -> str:
        sess = self._session(user_id)
        # Prefer showing current selection (UI state) over last executed upload
        selected = sess.get("selected_category")
        last_upload = sess.get("last_upload")
        category = selected or last_upload
        if category == "zip":
            typ = "קבצי ZIP"
        elif category == "all":
            typ = "הכל"
        elif isinstance(category, str) and category in {"by_repo", "large", "other"}:
            typ = {"by_repo": "לפי ריפו", "large": "קבצים גדולים", "other": "שאר קבצים"}[category]
        else:
            typ = "—"
        folder = sess.get("target_folder_label") or "ברירת מחדל (גיבויי_קודלי)"
        sched = self._schedule_button_label(user_id)
        sched_text = sched.replace("🕑 ", "") if sched != "🗓 זמני גיבוי" else "לא נקבע"
        return f"סוג: {typ}\nתיקייה: {folder}\nתזמון: {sched_text}\n"

    def _folder_button_label(self, user_id: int) -> str:
        sess = self._session(user_id)
        label = sess.get("target_folder_label")
        if label:
            return f"📂 תיקיית יעד: {label}"
        return "📂 בחר תיקיית יעד"

    async def _render_simple_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE, header_prefix: str = ""):
        query = update.callback_query if update.callback_query else None
        if query:
            send = query.edit_message_text
        else:
            send = update.message.reply_text
        user_id = update.effective_user.id
        sess = self._session(user_id)
        zip_label = "📦 קבצי ZIP" + (" ✅️" if sess.get("zip_done") else "")
        all_label = "🧰 הכל" + (" ✅️" if sess.get("all_done") else "")
        folder_label = self._folder_button_label(user_id)
        schedule_label = self._schedule_button_label(user_id)
        sess["last_menu"] = "simple"
        kb = [
            [InlineKeyboardButton(zip_label, callback_data="drive_sel_zip")],
            [InlineKeyboardButton(all_label, callback_data="drive_sel_all")],
            [InlineKeyboardButton(folder_label, callback_data="drive_choose_folder")],
            [InlineKeyboardButton(schedule_label, callback_data="drive_schedule")],
            [InlineKeyboardButton("✅ אישור", callback_data="drive_simple_confirm")],
            [InlineKeyboardButton("⚙️ מתקדם", callback_data="drive_sel_adv")],
            [InlineKeyboardButton("🚪 התנתק", callback_data="drive_logout")],
        ]
        header = header_prefix + self._compose_selection_header(user_id)
        await send(header + "בחר מה לגבות:", reply_markup=InlineKeyboardMarkup(kb))

    async def _render_after_folder_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE, success: bool):
        query = update.callback_query
        user_id = query.from_user.id
        # Determine where to go back based on last context (advanced vs simple)
        last = self._session(user_id).get("last_menu")
        prefix = "✅ תיקיית יעד עודכנה\n\n" if success else "❌ כשל בקביעת תיקייה\n\n"
        if last == "adv":
            await self._render_advanced_menu(update, context, header_prefix=prefix)
        else:
            await self._render_simple_selection(update, context, header_prefix=prefix)

    async def _render_advanced_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE, header_prefix: str = ""):
        query = update.callback_query
        user_id = query.from_user.id
        sess = self._session(user_id)
        sess["last_menu"] = "adv"
        multi_on = bool(sess.get("adv_multi", False))
        folder_label = self._folder_button_label(user_id)
        schedule_label = self._schedule_button_label(user_id)
        kb = [
            [InlineKeyboardButton("לפי ריפו", callback_data="drive_adv_by_repo")],
            [InlineKeyboardButton("קבצים גדולים", callback_data="drive_adv_large")],
            [InlineKeyboardButton("שאר קבצים", callback_data="drive_adv_other")],
            [InlineKeyboardButton(("✅ בחירה מרובה" if multi_on else "⬜ בחירה מרובה"), callback_data="drive_adv_multi_toggle")],
            [InlineKeyboardButton("📂 בחר תיקיית יעד", callback_data="drive_choose_folder_adv")],
            [InlineKeyboardButton(schedule_label, callback_data="drive_schedule")],
            [InlineKeyboardButton("✅ אישור", callback_data="drive_adv_confirm")],
            [InlineKeyboardButton("🔙 חזרה", callback_data="drive_backup_now")],
            [InlineKeyboardButton("🚪 התנתק", callback_data="drive_logout")],
        ]
        header = header_prefix + self._compose_selection_header(user_id)
        await query.edit_message_text(header + "בחר קטגוריה מתקדמת:", reply_markup=InlineKeyboardMarkup(kb))

    async def _render_simple_summary(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        user_id = query.from_user.id
        sess = self._session(user_id)
        last_upload = sess.get("last_upload") or "—"
        folder = sess.get("target_folder_label") or "ברירת מחדל (גיבויי_קודלי)"
        schedule = self._schedule_button_label(user_id).replace("🕑 ", "")
        txt = (
            "סיכום הגדרות:\n"
            f"• סוג גיבוי אחרון: {('קבצי ZIP' if last_upload=='zip' else ('הכל' if last_upload=='all' else '—'))}\n"
            f"• תיקיית יעד: {folder}\n"
            f"• תזמון: {schedule if schedule != '🗓 זמני גיבוי' else 'לא נקבע'}\n"
        )
        kb = [[InlineKeyboardButton("🔙 חזרה", callback_data="drive_backup_now")]]
        await query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb))

    async def _render_choose_folder_simple(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        explain = (
            "סידור תיקיות אוטומטי: הבוט יסדר בתוך 'גיבויי_קודלי' לפי קטגוריות ותאריכים,\n"
            "וב'לפי ריפו' גם תת‑תיקיות לפי שם הריפו."
        )
        kb = [
            [InlineKeyboardButton("🤖 סידור תיקיות אוטומטי (כמו בבוט)", callback_data="drive_folder_auto")],
            [InlineKeyboardButton("📂 גיבויי_קודלי (ברירת מחדל)", callback_data="drive_folder_default")],
            [InlineKeyboardButton("✏️ הגדר נתיב מותאם (שלח טקסט)", callback_data="drive_folder_set")],
            [InlineKeyboardButton("🔙 חזרה", callback_data="drive_backup_now")],
        ]
        await query.edit_message_text(f"בחר תיקיית יעד:\n\n{explain}", reply_markup=InlineKeyboardMarkup(kb))

    async def _render_choose_folder_adv(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        explain = (
            "סידור תיקיות אוטומטי: הבוט יסדר בתוך 'גיבויי_קודלי' לפי קטגוריות ותאריכים,\n"
            "וב'לפי ריפו' גם תת‑תיקיות לפי שם הריפו."
        )
        kb = [
            [InlineKeyboardButton("🤖 סידור תיקיות אוטומטי (כמו בבוט)", callback_data="drive_folder_auto")],
            [InlineKeyboardButton("📂 גיבויי_קודלי (ברירת מחדל)", callback_data="drive_folder_default")],
            [InlineKeyboardButton("✏️ הגדר נתיב מותאם (שלח טקסט)", callback_data="drive_folder_set")],
            [InlineKeyboardButton("🔙 חזרה", callback_data="drive_sel_adv")],
        ]
        await query.edit_message_text(f"בחר תיקיית יעד:\n\n{explain}", reply_markup=InlineKeyboardMarkup(kb))

    async def _render_adv_summary(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        user_id = query.from_user.id
        sess = self._session(user_id)
        cats = list(sess.get("adv_selected", set()) or [])
        cats_map = {"by_repo": "לפי ריפו", "large": "קבצים גדולים", "other": "שאר קבצים"}
        cats_txt = ", ".join(cats_map.get(c, c) for c in cats) if cats else "—"
        folder = sess.get("target_folder_label") or "ברירת מחדל (גיבויי_קודלי)"
        schedule = self._schedule_button_label(user_id).replace("🕑 ", "")
        txt = (
            "סיכום מתקדם:\n"
            f"• קטגוריות: {cats_txt}\n"
            f"• תיקיית יעד: {folder}\n"
            f"• תזמון: {schedule if schedule != '🗓 זמני גיבוי' else 'לא נקבע'}\n"
        )
        kb = [[InlineKeyboardButton("🔙 חזרה", callback_data="drive_sel_adv")]]
        await query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb))
