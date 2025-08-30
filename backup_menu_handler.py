import logging
import os
import tempfile
from io import BytesIO
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

def _build_download_button_text(info) -> str:
	"""יוצר טקסט תמציתי לכפתור ההורדה הכולל שם עיקרי + תאריך/גודל.
	מוגבל לאורך בטוח עבור טלגרם (~64 תווים) תוך הבטחת הצגת התאריך."""
	MAX_LEN = 64
	base = "backup zip"
	# שם עיקרי
	if getattr(info, 'backup_type', '') == 'github_repo_zip' and getattr(info, 'repo', None):
		primary = _repo_only(str(info.repo))
	else:
		primary = "full"
	date_part = _format_date(getattr(info, 'created_at', ''))
	size_part = _format_bytes(getattr(info, 'total_size', 0))

	def build(base_text: str, prim: str, include_size: bool = True) -> str:
		if include_size:
			return f"⬇️ {base_text} {prim} — {date_part} — {size_part}"
		return f"⬇️ {base_text} {prim} — {date_part}"

	# התחלה עם תצורה מלאה
	prim_use = _truncate_middle(primary, 32)
	text = build(base, prim_use, include_size=True)
	if len(text) <= MAX_LEN:
		return text
	# 1) קצר עוד את השם העיקרי
	for limit in (28, 24, 20, 16, 12, 8):
		prim_use = _truncate_middle(primary, limit)
		text = build(base, prim_use, include_size=True)
		if len(text) <= MAX_LEN:
			return text
	# 2) השמט את הגודל כדי לשמר את התאריך
	text = build(base, prim_use, include_size=False)
	if len(text) <= MAX_LEN:
		return text
	# 3) קצר את הקידומת ל-"zip"
	short_base = "zip"
	text = build(short_base, prim_use, include_size=False)
	if len(text) <= MAX_LEN:
		return text
	# 4) נסה לקצר עוד את השם עם הקידומת הקצרה
	for limit in (10, 8, 6, 4):
		prim_use = _truncate_middle(primary, limit)
		text = build(short_base, prim_use, include_size=False)
		if len(text) <= MAX_LEN:
			return text
	# 5) נפילה סופית: הצג רק תאריך עם קידומת קצרה
	return f"⬇️ {short_base} — {date_part}"

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
			await self._download_by_id(update, context, backup_id)
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
				# נסה לערוך את הודעת הסיכום אם שמרנו אותה בסשן
				try:
					summary_cache = context.user_data.get("backup_summaries", {})
					meta = summary_cache.get(b_id)
					if meta:
						chat_id = meta.get("chat_id")
						message_id = meta.get("message_id")
						base_text = meta.get("text") or ""
						await context.bot.edit_message_text(
							chat_id=chat_id,
							message_id=message_id,
							text=f"{base_text}\n{rating_value} / 👍 טוב / 🤷 סביר"
						)
				except Exception:
					pass
				try:
					await query.edit_message_text(f"נשמר הדירוג: {rating_value}")
				except Exception:
					await query.answer("נשמר הדירוג", show_alert=False)
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
			for b in backups:
				repo_name = getattr(b, 'repo', None)
				if not repo_name:
					continue
				repo_to_sorted.setdefault(repo_name, []).append(b)
			for repo_name, arr in repo_to_sorted.items():
				arr.sort(key=lambda x: getattr(x, 'created_at', None))
				for idx, b in enumerate(arr, start=1):
					id_to_version[getattr(b, 'backup_id', '')] = idx
		except Exception:
			id_to_version = {}
		lines = [f"📦 קבצי ZIP שמורים — סה\"כ: {total}\n📄 עמוד {page} מתוך {total_pages}\n"]
		keyboard = []
		for info in items:
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
			second_line = f"  ↳ גודל: {_format_bytes(getattr(info, 'total_size', 0))} | קבצים: {files_txt} | גרסה: v{vnum}"
			if rating:
				second_line += f" {rating}"
			lines.append(second_line)
			row = []
			# הצג כפתור שחזור רק עבור גיבויים מסוג DB (לא ל-GitHub ZIP)
			if btype not in {"github_repo_zip"}:
				row.append(InlineKeyboardButton("♻️ שחזר", callback_data=f"backup_restore_id:{info.backup_id}"))
			# כפתור הורדה תמיד זמין עם טקסט תמציתי
			row.append(InlineKeyboardButton(_build_download_button_text(info), callback_data=f"backup_download_id:{info.backup_id}"))
			keyboard.append(row)
		# עימוד: הקודם/הבא
		nav = []
		row = build_pagination_row(page, total, PAGE_SIZE, "backup_page_")
		if row:
			nav.extend(row)
		if nav:
			keyboard.append(nav)
		# פעולות נוספות - כפתור חזרה דינמי
		if zip_back_to == 'files':
			back_cb = 'files'
		elif zip_back_to == 'github_upload':
			back_cb = 'upload_file'
		elif current_repo is not None or zip_back_to == 'github':
			back_cb = 'github_backup_menu'
		else:
			back_cb = 'backup_menu'
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