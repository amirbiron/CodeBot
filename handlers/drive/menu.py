from typing import Any, Dict, Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from services import google_drive_service as gdrive
from database import db


class GoogleDriveMenuHandler:
    def __init__(self):
        self.sessions: Dict[int, Dict[str, Any]] = {}

    def _session(self, user_id: int) -> Dict[str, Any]:
        if user_id not in self.sessions:
            self.sessions[user_id] = {}
        return self.sessions[user_id]

    async def menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query if update.callback_query else None
        if query:
            await query.answer()
            send = query.edit_message_text
        else:
            send = update.message.reply_text

        user_id = update.effective_user.id
        tokens = db.get_drive_tokens(user_id)

        if not tokens:
            kb = [[InlineKeyboardButton("🔐 התחבר ל‑Drive", callback_data="drive_auth")]]
            await send("Google Drive\n\nלא מחובר. התחבר כדי לגבות לקבצי Drive.", reply_markup=InlineKeyboardMarkup(kb))
            return

        # Connected menu
        kb = [
            [InlineKeyboardButton("📤 גבה עכשיו", callback_data="drive_backup_now")],
            [InlineKeyboardButton("🗂 בחר תיקיית יעד", callback_data="drive_choose_folder")],
            [InlineKeyboardButton("🗓 זמני גיבוי", callback_data="drive_schedule")],
            [InlineKeyboardButton("⚙️ מתקדם", callback_data="drive_sel_adv")],
            [InlineKeyboardButton("🚪 התנתק", callback_data="drive_logout")],
        ]
        await send("Google Drive — מחובר\nבחר פעולה:", reply_markup=InlineKeyboardMarkup(kb))

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
            flow = gdrive.start_device_authorization(user_id)
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
                    uid = user_id
                    s = self._session(uid)
                    dc = s.get("device_code")
                    if not dc:
                        return
                    tokens = gdrive.poll_device_token(dc)
                    if tokens:
                        gdrive.save_tokens(uid, tokens)
                        # cancel job and notify
                        try:
                            j = ctx.job
                            j.schedule_removal()
                        except Exception:
                            pass
                        jobs.pop(uid, None)
                        s.pop("device_code", None)
                        try:
                            await query.edit_message_text("✅ חיבור ל‑Drive הושלם!")
                        except Exception:
                            pass
                except Exception:
                    pass
            try:
                job = context.application.job_queue.run_repeating(_poll_once, interval=sess["interval"], first=5, name=f"drive_auth_{user_id}")
                jobs[user_id] = job
            except Exception:
                pass
            # show instruction with buttons
            text = (
                "🔐 התחברות ל‑Google Drive\n\n"
                f"גש לכתובת: {flow.get('verification_url')}\n"
                f"קוד: <code>{flow.get('user_code')}</code>\n\n"
                "לאחר האישור, לחץ על ׳🔄 בדוק חיבור׳ או המתן לאימות אוטומטי."
            )
            kb = [
                [InlineKeyboardButton("🔄 בדוק חיבור", callback_data="drive_poll_once")],
                [InlineKeyboardButton("❌ בטל", callback_data="drive_cancel_auth")],
            ]
            await query.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))
            return
        if data == "drive_poll_once":
            sess = self._session(user_id)
            dc = sess.get("device_code")
            if not dc:
                await query.answer("אין בקשת התחברות פעילה", show_alert=True)
                return
            tokens = gdrive.poll_device_token(dc)
            if not tokens:
                await query.answer("עדיין ממתינים לאישור…", show_alert=False)
                return
            if isinstance(tokens, dict) and tokens.get("error"):
                # Show descriptive error to the user and keep polling active
                err = tokens.get("error")
                desc = tokens.get("error_description") or "בקשה נדחתה. נא לאשר בדפדפן ולנסות שוב."
                await query.answer(f"שגיאה: {err}\n{desc}"[:190], show_alert=True)
                return
            gdrive.save_tokens(user_id, tokens)
            tokens = gdrive.poll_device_token(dc)
            if not tokens:
                await query.answer("עדיין ממתינים לאישור…", show_alert=False)
                return
            if isinstance(tokens, dict) and tokens.get("error"):
                err = tokens.get("error")
                desc = tokens.get("error_description") or "בקשה נדחתה. נא לאשר בדפדפן ולנסות שוב."
                await query.answer(f"שגיאה: {err}\n{desc}"[:190], show_alert=True)
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
            # Show selection: ZIP, הכל, מתקדם
            kb = [
                [InlineKeyboardButton("📦 קבצי ZIP", callback_data="drive_sel_zip")],
                [InlineKeyboardButton("🧰 הכל", callback_data="drive_sel_all")],
                [InlineKeyboardButton("⚙️ מתקדם", callback_data="drive_sel_adv")],
                [InlineKeyboardButton("🔙 חזרה", callback_data="drive_menu")],
            ]
            await query.edit_message_text("בחר מה לגבות:", reply_markup=InlineKeyboardMarkup(kb))
            return
        if data == "drive_sel_zip":
            # Upload existing ZIP backups
            count, ids = gdrive.upload_all_saved_zip_backups(user_id)
            await query.edit_message_text(f"✅ הועלו {count} גיבויים ל‑Drive")
            return
        if data == "drive_sel_all":
            fn, data_bytes = gdrive.create_full_backup_zip_bytes(user_id, category="all")
            fid = gdrive.upload_bytes(user_id, fn, data_bytes)
            await query.edit_message_text("✅ גיבוי מלא הועלה ל‑Drive" if fid else "❌ כשל בהעלאה")
            return
        if data == "drive_sel_adv":
            multi_on = bool(self._session(user_id).get("adv_multi", False))
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
        if data in {"drive_adv_by_repo", "drive_adv_large", "drive_adv_other"}:
            category = {
                "drive_adv_by_repo": "by_repo",
                "drive_adv_large": "large",
                "drive_adv_other": "other",
            }[data]
            sess = self._session(user_id)
            if sess.get("adv_multi"):
                selected = sess.setdefault("adv_selected", set())
                selected.add(category)
                await query.edit_message_text("✅ נוסף לבחירה. ניתן לבחור עוד אפשרויות או להעלות.")
            else:
                fn, data_bytes = gdrive.create_full_backup_zip_bytes(user_id, category=category)
                fid = gdrive.upload_bytes(user_id, fn, data_bytes)
                await query.edit_message_text("✅ גיבוי הועלה ל‑Drive" if fid else "❌ כשל בהעלאה")
            return
        if data == "drive_adv_multi_toggle":
            sess = self._session(user_id)
            sess["adv_multi"] = not bool(sess.get("adv_multi", False))
            await self.handle_callback(update, context)
            return
        if data == "drive_adv_upload_selected":
            sess = self._session(user_id)
            cats = list(sess.get("adv_selected", set()) or [])
            if not cats:
                await query.answer("לא נבחרו אפשרויות", show_alert=True)
                return
            uploaded_any = False
            for c in cats:
                fn, data_bytes = gdrive.create_full_backup_zip_bytes(user_id, category=c)
                fid = gdrive.upload_bytes(user_id, fn, data_bytes)
                uploaded_any = uploaded_any or bool(fid)
            sess["adv_selected"] = set()
            await query.edit_message_text("✅ הועלו הגיבויים שנבחרו" if uploaded_any else "❌ כשל בהעלאה")
            return
        if data == "drive_choose_folder":
            kb = [
                [InlineKeyboardButton("📁 ברירת מחדל (CodeKeeper Backups)", callback_data="drive_folder_default")],
                [InlineKeyboardButton("✏️ הגדר נתיב מותאם (שלח טקסט)", callback_data="drive_folder_set")],
                [InlineKeyboardButton("🔙 חזרה", callback_data="drive_menu")],
            ]
            await query.edit_message_text("בחר דרך לקביעת תיקיית יעד:", reply_markup=InlineKeyboardMarkup(kb))
            return
        if data == "drive_folder_default":
            fid = gdrive.get_or_create_default_folder(user_id)
            await query.edit_message_text("📁 נקבעה תיקיית יעד ברירת מחדל: CodeKeeper Backups" if fid else "❌ כשל בקביעת תיקייה")
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
            # חזרה למסך בחירת תיקיית יעד
            context.user_data.pop("waiting_for_drive_folder_path", None)
            kb = [
                [InlineKeyboardButton("📁 ברירת מחדל (CodeKeeper Backups)", callback_data="drive_folder_default")],
                [InlineKeyboardButton("✏️ הגדר נתיב מותאם (שלח טקסט)", callback_data="drive_folder_set")],
                [InlineKeyboardButton("🔙 חזרה", callback_data="drive_menu")],
            ]
            await query.edit_message_text("בחר דרך לקביעת תיקיית יעד:", reply_markup=InlineKeyboardMarkup(kb))
            return
        if data == "drive_folder_cancel":
            # ביטול מצב הזנת נתיב וחזרה לתפריט דרייב
            context.user_data.pop("waiting_for_drive_folder_path", None)
            await self.menu(update, context)
            return
        if data == "drive_schedule":
            current = (db.get_drive_prefs(user_id) or {}).get("schedule")
            def label(key: str, text: str) -> str:
                return ("✅ " + text) if current == key else text
            kb = [
                [InlineKeyboardButton(label("daily", "כל יום"), callback_data="drive_set_schedule:daily")],
                [InlineKeyboardButton(label("every3", "כל 3 ימים"), callback_data="drive_set_schedule:every3")],
                [InlineKeyboardButton(label("weekly", "כל שבוע"), callback_data="drive_set_schedule:weekly")],
                [InlineKeyboardButton(label("biweekly", "פעם בשבועיים"), callback_data="drive_set_schedule:biweekly")],
                [InlineKeyboardButton(label("monthly", "פעם בחודש"), callback_data="drive_set_schedule:monthly")],
                [InlineKeyboardButton("⛔ בטל תזמון", callback_data="drive_set_schedule:off")],
                [InlineKeyboardButton("🔙 חזרה", callback_data="drive_menu")],
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
            await query.edit_message_text("✅ תזמון נשמר")
            return
        if data == "drive_logout":
            ok = db.delete_drive_tokens(user_id)
            await query.edit_message_text("🚪נותקת מ‑Google Drive" if ok else "❌ לא בוצעה התנתקות")
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
                await update.message.reply_text("✅ תיקיית יעד עודכנה בהצלחה")
            else:
                await update.message.reply_text("❌ לא ניתן להגדיר את התיקייה. ודא בהרשאות Drive.")
            return True
        return False

