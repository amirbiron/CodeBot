import logging
import os
from typing import Any, Dict

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import ContextTypes

from services import backup_service as backup_manager
from database import db
from handlers.pagination import build_pagination_row

logger = logging.getLogger(__name__)

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
		await message("בחר פעולה מתפריט הגיבוי/שחזור:", reply_markup=reply_markup)
	
	async def handle_callback_query(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
		query = update.callback_query
		user_id = query.from_user.id
		data = query.data
		
		if data == "backup_create_full":
			await self._create_full_backup(update, context)
		elif data == "backup_restore_full_start":
			await self._show_backups_list(update, context)
		elif data == "backup_list":
			await self._show_backups_list(update, context, page=1)
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
					from database import db as _db
					_db.delete_backup_ratings(user_id, [backup_id])
				except Exception:
					pass
				deleted = res.get("deleted", 0)
				if deleted:
					await update.callback_query.edit_message_text("✅ הגיבוי נמחק")
					await self._show_backups_list(update, context)
				else:
					await update.callback_query.edit_message_text("❌ המחיקה נכשלה")
			except Exception as e:
				await update.callback_query.edit_message_text(f"❌ שגיאה במחיקה: {e}")
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
			txt = "האם אתה בטוח שברצונך למחוק את:"\
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
					from database import db as _db
					_db.delete_backup_ratings(user_id, sel)
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
				db.save_backup_rating(user_id, b_id, rating_value)
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
			from io import BytesIO
			import zipfile, json
			from database import db
			# אסוף את הקבצים של המשתמש
			files = db.get_user_files(user_id, limit=10000) or []
			backup_id = f"backup_{user_id}_{int(__import__('time').time())}"
			buf = BytesIO()
			with zipfile.ZipFile(buf, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
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
			buf.seek(0)
			# שמור בהתאם למצב האחסון
			backup_manager.save_backup_bytes(buf.getvalue(), metadata)
			# שלח קובץ למשתמש
			buf.seek(0)
			await query.message.reply_document(
				document=InputFile(buf, filename=f"{backup_id}.zip"),
				caption=f"✅ גיבוי נוצר בהצלחה\nקבצים: {len(files)} | גודל: {_format_bytes(len(buf.getvalue()))}"
			)
			await self.show_backup_menu(update, context)
		except Exception as e:
			logger.error(f"Failed creating/sending backup: {e}")
			await query.edit_message_text("❌ יצירת הגיבוי נכשלה")
	
	async def _start_full_restore(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
		# נשמר לשם תאימות אם יקראו בפועל, מפנה לרשימת גיבויים
		await self._show_backups_list(update, context)
	
	# הוסרה תמיכה בהעלאת ZIP ישירה מהתפריט כדי למנוע מחיקה גורפת בטעות
	
	async def _show_backups_list(self, update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 1):
		query = update.callback_query
		user_id = query.from_user.id
		await query.answer()
		highlight_id = context.user_data.pop("backup_highlight_id", None)
		backups = backup_manager.list_backups(user_id)
		# ודא שתמיד מוצגים כל קבצי ה‑ZIP ללא סינון לפי משתמש
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
			backups = filtered
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
			await query.edit_message_text(
				msg,
				reply_markup=InlineKeyboardMarkup(keyboard)
			)
			return
		
		# עימוד תוצאות
		PAGE_SIZE = 10
		total = len(backups)
		if page < 1:
			page = 1
		total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE if total > 0 else 1
		if page > total_pages:
			page = total_pages
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
		lines = [f"📦 קבצי ZIP שמורים — סה\"כ: {total}\n📄 עמוד {page} מתוך {total_pages}\n"]
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
				first_line = f"• {getattr(info, 'backup_id', '')} — {_format_date(getattr(info, 'created_at', ''))}"
			lines.append(first_line)
			# שורה שנייה עם גודל | קבצים | גרסה (+דירוג אם קיים)
			try:
				rating = db.get_backup_rating(user_id, info.backup_id) or ""
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
			await query.edit_message_text("❌ הגיבוי לא נמצא")
			return
		# שלוף דירוג נוכחי אם קיים
		try:
			rating = db.get_backup_rating(user_id, backup_id) or ""
		except Exception:
			rating = ""
		# שלוף הערה אם קיימת
		try:
			note_text = db.get_backup_note(user_id, backup_id) or ""
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
			[InlineKeyboardButton("📝 הוסף הערה", callback_data=f"backup_add_note:{backup_id}")],
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
			from database import db
			existing = db.get_backup_note(user_id, backup_id) or ""
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
		if not match or not match.file_path or not os.path.exists(match.file_path):
			await query.edit_message_text("❌ הגיבוי לא נמצא בדיסק")
			return
		try:
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
		if not match or not match.file_path or not os.path.exists(match.file_path):
			await query.edit_message_text("❌ הגיבוי לא נמצא בדיסק")
			return
		try:
			with open(match.file_path, 'rb') as f:
				await query.message.reply_document(
					document=InputFile(f, filename=os.path.basename(match.file_path)),
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