import logging
import os
import tempfile
from io import BytesIO
from typing import Any, Dict

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import ContextTypes

from file_manager import backup_manager

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

def _build_download_button_text(info) -> str:
	"""יוצר טקסט תמציתי לכפתור ההורדה הכולל שם עיקרי + תאריך/גודל.
	מוגבל לאורך בטוח עבור טלגרם (~64 תווים) תוך הבטחת הצגת התאריך."""
	MAX_LEN = 64
	base = "backup zip"
	# שם עיקרי
	if getattr(info, 'backup_type', '') == 'github_repo_zip' and getattr(info, 'repo', None):
		primary = str(info.repo)
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
		else:
			await query.answer("לא נתמך", show_alert=True)
	
	async def _create_full_backup(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
		query = update.callback_query
		user_id = query.from_user.id
		await query.edit_message_text("⏳ יוצר גיבוי מלא...")
		info = await backup_manager.create_backup(user_id=user_id, backup_type="manual", include_versions=True)
		if not info or not info.file_path or not os.path.exists(info.file_path):
			await query.edit_message_text("❌ יצירת הגיבוי נכשלה")
			return
		try:
			with open(info.file_path, 'rb') as f:
				await query.message.reply_document(
					document=InputFile(f, filename=os.path.basename(info.file_path)),
					caption=f"✅ גיבוי נוצר בהצלחה\nקבצים: {info.file_count} | גודל: {_format_bytes(info.total_size)}"
				)
			await self.show_backup_menu(update, context)
		except Exception as e:
			logger.error(f"Failed sending backup: {e}")
			await query.edit_message_text("❌ שגיאה בשליחת קובץ הגיבוי")
	
	async def _start_full_restore(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
		# נשמר לשם תאימות אם יקראו בפועל, מפנה לרשימת גיבויים
		await self._show_backups_list(update, context)
	
	# הוסרה תמיכה בהעלאת ZIP ישירה מהתפריט כדי למנוע מחיקה גורפת בטעות
	
	async def _show_backups_list(self, update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 1):
		query = update.callback_query
		user_id = query.from_user.id
		await query.answer()
		backups = backup_manager.list_backups(user_id)
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
		lines = [f"📦 קבצי ZIP שמורים — סה""כ: {total}\n📄 עמוד {page} מתוך {total_pages}\n"]
		keyboard = []
		for info in items:
			btype = getattr(info, 'backup_type', 'unknown')
			repo_name = getattr(info, 'repo', None)
			if repo_name:
				line = (
					f"• {repo_name} — {info.created_at.strftime('%d/%m/%Y %H:%M')} — "
					f"{_format_bytes(info.total_size)} — {info.file_count} קבצים — סוג: {btype} — ID: {info.backup_id}"
				)
			else:
				line = (
					f"• {info.backup_id} — {info.created_at.strftime('%d/%m/%Y %H:%M')} — "
					f"{_format_bytes(info.total_size)} — {info.file_count} קבצים — סוג: {btype}"
				)
			lines.append(line)
			row = []
			# הצג כפתור שחזור רק עבור גיבויים מסוג DB (לא ל-GitHub ZIP)
			if btype not in {"github_repo_zip"}:
				row.append(InlineKeyboardButton("♻️ שחזר", callback_data=f"backup_restore_id:{info.backup_id}"))
			# כפתור הורדה תמיד זמין עם טקסט תמציתי
			row.append(InlineKeyboardButton(_build_download_button_text(info), callback_data=f"backup_download_id:{info.backup_id}"))
			keyboard.append(row)
		# עימוד: הקודם/הבא
		pagination = []
		if page > 1:
			pagination.append(InlineKeyboardButton("⬅️ הקודם", callback_data=f"backup_page_{page-1}"))
		if page < total_pages:
			pagination.append(InlineKeyboardButton("➡️ הבא", callback_data=f"backup_page_{page+1}"))
		if pagination:
			keyboard.append(pagination)
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