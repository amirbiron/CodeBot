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
			await self._show_backups_list(update, context)
		elif data.startswith("backup_restore_id:"):
			backup_id = data.split(":", 1)[1]
			await self._restore_by_id(update, context, backup_id)
		elif data.startswith("backup_download_id:"):
			backup_id = data.split(":", 1)[1]
			await self._download_by_id(update, context, backup_id)
		elif data == "backup_upload_zip":
			await self._start_full_restore_upload(update, context)
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
	
	async def _start_full_restore_upload(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
		query = update.callback_query
		await query.answer()
		# סמן שאנחנו ממתינים לקובץ ZIP לשחזור
		context.user_data['upload_mode'] = 'backup_restore'
		await query.edit_message_text(
			"📥 שלח עכשיו קובץ ZIP של גיבוי שהתקבל מהבוט כדי לבצע שחזור מלא.\n"
			"⚠️ פעולה זו תמחק את הקבצים הקיימים ותשחזר מהגיבוי."
		)
	
	async def _show_backups_list(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
		query = update.callback_query
		user_id = query.from_user.id
		await query.answer()
		backups = backup_manager.list_backups(user_id)
		if not backups:
			keyboard = [
				[InlineKeyboardButton("⬆️ העלה ZIP לשחזור", callback_data="backup_upload_zip")],
				[InlineKeyboardButton("🔙 חזור", callback_data="backup_menu")],
			]
			await query.edit_message_text(
				"ℹ️ לא נמצאו גיבויים שמורים. ניתן להעלות ZIP לשחזור או לחזור.",
				reply_markup=InlineKeyboardMarkup(keyboard)
			)
			return
		
		# הצג עד 10 אחרונים
		items = backups[:10]
		lines = ["בחר גיבוי לשחזור או להורדה:\n"]
		keyboard = []
		for info in items:
			line = f"• {info.backup_id} — {info.created_at.strftime('%d/%m/%Y %H:%M')} — {_format_bytes(info.total_size)} — {info.file_count} קבצים"
			lines.append(line)
			keyboard.append([
				InlineKeyboardButton("♻️ שחזר", callback_data=f"backup_restore_id:{info.backup_id}"),
				InlineKeyboardButton("⬇️ הורד", callback_data=f"backup_download_id:{info.backup_id}"),
			])
		# פעולות נוספות
		keyboard.append([InlineKeyboardButton("⬆️ העלה ZIP לשחזור", callback_data="backup_upload_zip")])
		keyboard.append([InlineKeyboardButton("🔙 חזור", callback_data="backup_menu")])
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
			# השאר בתצוגת רשימה
			await self._show_backups_list(update, context)
		except Exception as e:
			await query.edit_message_text(f"❌ שגיאה בשליחת קובץ הגיבוי: {e}")