import logging
import os
import tempfile
from io import BytesIO
from typing import Any, Dict
from datetime import datetime, timezone
try:
	from zoneinfo import ZoneInfo  # Python 3.9+
	_IL_TZ = ZoneInfo("Asia/Jerusalem")
except Exception:
	_IL_TZ = None

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
		if isinstance(dt, datetime):
			# Assume UTC when tzinfo is missing
			if dt.tzinfo is None:
				dt = dt.replace(tzinfo=timezone.utc)
			try:
				from zoneinfo import ZoneInfo
				dt = dt.astimezone(ZoneInfo("Asia/Jerusalem"))
			except Exception:
				# Fallback: keep UTC if zoneinfo not available
				pass
			return dt.strftime('%d/%m/%Y %H:%M')
		return str(dt)
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