import logging
import os
import tempfile
from io import BytesIO
from typing import Any, Dict

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import ContextTypes

from file_manager import backup_manager

logger = logging.getLogger(__name__)

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
			await self._start_full_restore(update, context)
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
					caption=f"✅ גיבוי נוצר בהצלחה\nקבצים: {info.file_count} | גודל: {info.total_size} bytes"
				)
			await self.show_backup_menu(update, context)
		except Exception as e:
			logger.error(f"Failed sending backup: {e}")
			await query.edit_message_text("❌ שגיאה בשליחת קובץ הגיבוי")
	
	async def _start_full_restore(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
		query = update.callback_query
		await query.answer()
		# סמן שאנחנו ממתינים לקובץ ZIP לשחזור
		context.user_data['upload_mode'] = 'backup_restore'
		await query.edit_message_text(
			"📥 שלח עכשיו קובץ ZIP של גיבוי שהתקבל מהבוט כדי לבצע שחזור מלא.\n"
			"⚠️ בקבצים קיימים, תתבצע דריסה."
		)
	
	async def _delegate_git_checkpoint(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
		query = update.callback_query
		await query.answer()
		github_handler = context.bot_data.get('github_handler')
		if not github_handler:
			await query.edit_message_text("❌ רכיב GitHub לא זמין")
			return
		# העבר ל-handler של GitHub
		await github_handler.git_checkpoint(update, context)
	
	async def _delegate_git_restore_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
		query = update.callback_query
		await query.answer()
		github_handler = context.bot_data.get('github_handler')
		if not github_handler:
			await query.edit_message_text("❌ רכיב GitHub לא זמין")
			return
		await github_handler.show_restore_checkpoint_menu(update, context)