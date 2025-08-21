import os
import logging
import threading
from datetime import datetime
from flask import Flask
from typing import Dict, Any
import re
from io import BytesIO

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, BotCommand
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, ConversationHandler, filters
)
from telegram.constants import ParseMode
from telegram.error import Conflict, NetworkError, Forbidden, TimedOut

from database.database_manager import Database
from activity_reporter import create_reporter

# Activity Reporter setup (keep after variable loading)
reporter = create_reporter(
    mongodb_uri="mongodb+srv://mumin:M43M2TFgLfGvhBwY@muminai.tm6x81b.mongodb.net/?retryWrites=true&w=majority&appName=muminAI",
    service_id="srv-d1t3lijuibrs738s0af0",
    service_name="SaveMe"
)

# Helper function to escape markdown
def escape_markdown(text: str) -> str:
    """Helper function to escape telegram markdown characters."""
    escape_chars = r'\_*[]()~`>#+-=|{}.!'
    return re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', text)

# Heuristic language detection for code snippets
def detect_code_language(text: str) -> str | None:
    try:
        sample = text.strip()
        first_line = sample.splitlines()[0] if sample else ""
        if re.match(r'^#!/bin/(bash|sh)', sample):
            return 'bash'
        if '<?php' in sample:
            return 'php'
        if re.search(r'</?[a-zA-Z][\w:-]*\b', sample) and '<' in sample and '>' in sample:
            return 'html'
        if re.search(r'^\s*\{', sample) and re.search(r'"[^"]+"\s*:', sample):
            return 'json'
        if re.search(r'^(FROM|RUN|CMD|COPY|ENTRYPOINT|ENV|ARG|WORKDIR|EXPOSE)\b', sample, re.IGNORECASE | re.MULTILINE):
            return 'dockerfile'
        if re.search(r'^\s*\[.+\]\s*$', sample, re.MULTILINE) and re.search(r'=', sample):
            return 'ini'
        if re.search(r'^[\s\-\w]+:\s+.+$', sample, re.MULTILINE) and not re.search(r';\s*$', sample, re.MULTILINE):
            return 'yaml'
        if re.search(r'\bpackage\s+main\b', sample) or re.search(r'\bfunc\s+\w+\s*\(', sample):
            return 'go'
        if re.search(r'\bfn\s+\w+\s*\(|println!\s*\(', sample):
            return 'rust'
        if re.search(r'\busing\s+System\b|\bnamespace\b|public\s+class\b', sample):
            return 'csharp'
        if re.search(r'\bpublic\s+class\b|System\.out\.println', sample):
            return 'java'
        if re.search(r'\bSELECT\b|\bINSERT\b|\bUPDATE\b|\bDELETE\b|\bCREATE\b|\bTABLE\b', sample, re.IGNORECASE):
            return 'sql'
        if re.search(r'\b(def|class)\s+\w+|from\s+\w+\s+import|import\s+\w+', sample) and not re.search(r';\s*$', first_line):
            return 'python'
        if re.search(r'\b(const|let|var|function)\b|=>|console\.log|import\s+.*\s+from\s+', sample):
            return 'javascript'
        return None
    except Exception:
        return None

# Helper to format text content to preserve code/Markdown rendering in Telegram
def format_text_content_for_telegram(text: str):
    """Return (formatted_text, parse_mode) for Telegram so code/Markdown is preserved.

    - If content already includes triple backticks, send as-is with Markdown parse mode.
    - If content looks like Markdown (headings, lists, emphasis, links), send as-is with Markdown parse mode.
    - If content looks like code, wrap in triple backticks (with language when detected) and send with Markdown parse mode.
    - Otherwise, send as plain text (no parse mode).
    """
    try:
        if '```' in text:
            return text, ParseMode.MARKDOWN

        # Detect Markdown-like content (should be rendered, not shown as code)
        markdown_patterns = [
            r'(^|\n)#{1,6}\s',                 # headings
            r'(^|\n)(?:\- |\* |\d+\. |> )', # lists / blockquote
            r'\*\*[^\n]+\*\*',              # bold
            r'__[^\n]+__',                      # bold (alt)
            r'(?<!\*)\*[^\n]+\*(?!\*)',     # italic
            r'_(?:[^\n_]|_[^\n])+_',          # italic (alt)
            r'\[[^\]]+\]\([^\)]+\)',       # links [text](url)
        ]
        if any(re.search(p, text, re.MULTILINE) for p in markdown_patterns):
            return text, ParseMode.MARKDOWN

        # Detect code-like content (should be fenced)
        code_patterns = [
            r'(^|\n)\s{4,}',  # indented code blocks
            r'\b(def|class|import|from|const|let|var|function|public|private|return|if|else|for|while|try|catch)\b',
            r'[{};=<>\[\]]',   # common code punctuation
        ]
        if any(re.search(pattern, text) for pattern in code_patterns):
            lang = detect_code_language(text) or ''
            fence = f"```{lang}\n{text}\n```"
            return fence, ParseMode.MARKDOWN

        return text, None
    except Exception:
        return text, None

# --- Flask App for Render Health Check ---
flask_app = Flask('')
@flask_app.route('/')
def health_check():
    return "Bot is alive!", 200

def run_flask():
    port = int(os.environ.get('PORT', 8080))
    flask_app.run(host='0.0.0.0', port=port)

# --- Bot Configuration ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Conversation States
SELECTING_ACTION, AWAIT_CONTENT, AWAIT_CATEGORY, AWAIT_SUBJECT, AWAIT_SUBJECT_EDIT, AWAIT_NOTE, AWAIT_EDIT, AWAIT_SEARCH, AWAIT_MD_TEXT, AWAIT_MULTIPART = range(10)

# --- Error Handler ---
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    error = context.error
    logger.error("Exception while handling an update:", exc_info=error)
    # Add specific error handling if needed

class SaveMeBot:
    def __init__(self):
        db_path = os.environ.get('DATABASE_PATH', 'save_me_bot.db')
        self.db = Database(db_path=db_path)

    # --- Activity Reporting Helper ---
    def _report(self, update: Update):
        reporter.report_activity(update.effective_user.id)

    # --- Main Menu and State Entrypoints ---
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        self._report(update)
        username = update.effective_user.first_name
        welcome_text = f"שלום {username}! 👋\nברוך הבא לבוט 'שמור לי'.\nבחר פעולה מהתפריט:"
        keyboard = [
            [KeyboardButton("➕ הוסף תוכן")],
            [KeyboardButton("📝 המרה ל-Markdown")],
            [KeyboardButton("🧩 איסוף טקסט רב-הודעות")],
            [KeyboardButton("🔍 חיפוש"), KeyboardButton("📚 הצג קטגוריות")],
            [KeyboardButton("⚙️ הגדרות")]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        chat_id = update.effective_chat.id
        await context.bot.send_message(chat_id=chat_id, text=welcome_text, reply_markup=reply_markup)
        return SELECTING_ACTION

    async def ask_for_content(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        self._report(update)
        await update.message.reply_text("שלח לי את התוכן לשמירה:")
        return AWAIT_CONTENT

    async def start_multipart(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        self._report(update)
        context.user_data['multipart_buffer'] = []
        keyboard = [[InlineKeyboardButton("✔️ סיום", callback_data="multipart_end")],
                    [InlineKeyboardButton("✖️ ביטול", callback_data="multipart_cancel")]]
        await update.message.reply_text("מצב איסוף הופעל. שלח כמה הודעות טקסט שתרצה, ואז לחץ '✔️ סיום'", reply_markup=InlineKeyboardMarkup(keyboard))
        return AWAIT_MULTIPART

    async def multipart_router(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        self._report(update)
        query = update.callback_query
        if query:
            await query.answer()
            if query.data == 'multipart_end':
                parts = context.user_data.get('multipart_buffer', [])
                text = "\n".join(parts).strip()
                context.user_data.pop('multipart_buffer', None)
                await query.edit_message_text("קיבלתי. שמור כעת כפריט רגיל.")
                if not text:
                    await context.bot.send_message(chat_id=update.effective_chat.id, text="לא התקבל טקסט.")
                    return await self.start(update, context)
                # Continue to category selection as text item
                context.user_data['new_item'] = {'type': 'text', 'content': text}
                categories = self.db.get_user_categories(update.effective_user.id)
                keyboard = [[InlineKeyboardButton(c, callback_data=f"cat_{c}")] for c in categories]
                keyboard.append([InlineKeyboardButton("🆕 קטגוריה חדשה", callback_data="cat_new")])
                await context.bot.send_message(chat_id=update.effective_chat.id, text="בחר קטגוריה:", reply_markup=InlineKeyboardMarkup(keyboard))
                return AWAIT_CATEGORY
            if query.data == 'multipart_cancel':
                context.user_data.pop('multipart_buffer', None)
                await query.edit_message_text("בוטל.")
                return await self.start(update, context)
        else:
            # receive a part
            if update.message and update.message.text:
                buf = context.user_data.get('multipart_buffer', [])
                buf.append(update.message.text)
                context.user_data['multipart_buffer'] = buf
                await update.message.reply_text(f"נוסף קטע. כרגע {len(buf)} קטעים. לחץ '✔️ סיום' כשאתה מוכן.")
                return AWAIT_MULTIPART
 
    async def upload_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        self._report(update)
        text = (
            "איך להעלות תוכן:\n\n"
            "1) קובץ מצורף: שלח כ-document/photo/video לפי הצורך.\n"
            "2) טקסט ארוך: לחץ על 'התחל איסוף טקסט' ושלח כמה הודעות, ואז סיים.\n"
        )
        keyboard = [[InlineKeyboardButton("התחל איסוף טקסט", callback_data="upload_start_multipart")],
                    [InlineKeyboardButton("סגור", callback_data="upload_close")]]
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
        return SELECTING_ACTION

    async def upload_router(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        self._report(update)
        query = update.callback_query
        if not query:
            return SELECTING_ACTION
        await query.answer()
        if query.data == 'upload_start_multipart':
            # Start multipart collection via callback
            context.user_data['multipart_buffer'] = []
            kb = [[InlineKeyboardButton("✔️ סיום", callback_data="multipart_end")],
                  [InlineKeyboardButton("✖️ ביטול", callback_data="multipart_cancel")]]
            await context.bot.send_message(chat_id=update.effective_chat.id, text="מצב איסוף הופעל. שלח הודעות טקסט ואז לחץ '✔️ סיום'", reply_markup=InlineKeyboardMarkup(kb))
            return AWAIT_MULTIPART
        if query.data == 'upload_close':
            try:
                await query.edit_message_text("נסגר.")
            except Exception:
                pass
            return SELECTING_ACTION
        return SELECTING_ACTION

    async def ask_for_search_query(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        self._report(update)
        await update.message.reply_text("מה לחפש?")
        return AWAIT_SEARCH

    # New: Ask for text to convert to Markdown
    async def ask_for_md_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        self._report(update)
        await update.message.reply_text("שלח את הטקסט להמרה לקובץ Markdown (.md):")
        return AWAIT_MD_TEXT

    # New: Convert received text to .md and send back
    async def convert_text_to_md_and_send(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        self._report(update)
        text = (update.message.text or '').strip()
        if not text:
            await update.message.reply_text("לא התקבל טקסט. שלח טקסט רגיל להמרה.")
            return AWAIT_MD_TEXT

        # Show the content (rendered/escaped) instead of sending a file
        preview_text, parse_mode = format_text_content_for_telegram(text)
        if parse_mode:
            await update.message.reply_text(preview_text, parse_mode=parse_mode)
        else:
            await update.message.reply_text(preview_text)

        # Additionally send as a .md file so the user can open with a Markdown viewer
        try:
            md_bytes = BytesIO(text.encode('utf-8'))
            md_bytes.name = f"note-{datetime.now().strftime('%Y%m%d-%H%M%S')}.md"
            await update.message.reply_document(document=md_bytes, filename=md_bytes.name, caption="קובץ Markdown")
        except Exception:
            # Ignore file send failures; preview already sent
            pass

        # Prepare save flow like a regular save (user chooses category and subject)
        context.user_data['new_item'] = {'type': 'text', 'content': text}

        categories = self.db.get_user_categories(update.effective_user.id)
        keyboard = [[InlineKeyboardButton(c, callback_data=f"cat_{c}")] for c in categories]
        keyboard.append([InlineKeyboardButton("🆕 קטגוריה חדשה", callback_data="cat_new")])
        await update.message.reply_text("בחר קטגוריה:", reply_markup=InlineKeyboardMarkup(keyboard))
        return AWAIT_CATEGORY

    # --- Display Logic ---
    async def show_item_with_actions(self, update_or_query, context: ContextTypes.DEFAULT_TYPE, item_id: int):
        item = self.db.get_item(item_id)
        if not item:
            if hasattr(update_or_query, 'edit_message_text'):
                await update_or_query.edit_message_text("הפריט נמחק.")
            return

        # --- הודעת ניהול (מטא-דאטה וכפתורים) ---
        category = escape_markdown(item['category'])
        subject = escape_markdown(item['subject'])
        note = escape_markdown(item.get('note', ''))

        metadata_text = f"📁 **קטגוריה:** {category}\n📝 **נושא:** {subject}"
        if note:
            metadata_text += f"\n\n🗒️ **הערה:** {note}"

        pin_text = "📌 בטל קיבוע" if item.get('is_pinned') else "📌 קבע"
        note_text = "✏️ ערוך הערה" if item.get('note') else "📝 הוסף הערה"
        keyboard = [
            [InlineKeyboardButton(pin_text, callback_data=f"pin_{item_id}")],
            [InlineKeyboardButton("✏️ ערוך נושא", callback_data=f"editsubject_{item_id}")],
            [InlineKeyboardButton("✏️ ערוך תוכן", callback_data=f"edit_{item_id}")],
            [InlineKeyboardButton(note_text, callback_data=f"note_{item_id}")],
            [InlineKeyboardButton("🗑️ מחק", callback_data=f"delete_{item_id}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        chat_id = update_or_query.message.chat.id
        if hasattr(update_or_query, 'edit_message_text'):
            await update_or_query.edit_message_text(metadata_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        else:
            await context.bot.send_message(chat_id=chat_id, text=metadata_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

        content_type = item.get('content_type')
        if content_type == 'text' or (content_type == 'document' and (item.get('file_name', '').endswith('.md')) and (item.get('content') is not None and item.get('content') != '')):
            text_to_send, parse_mode = format_text_content_for_telegram(item.get('content', ''))
            if parse_mode:
                await context.bot.send_message(chat_id=chat_id, text=text_to_send, parse_mode=parse_mode)
            else:
                await context.bot.send_message(chat_id=chat_id, text=text_to_send)
        elif content_type and item.get('file_id'):
            send_map = {'photo': context.bot.send_photo, 'document': context.bot.send_document, 'video': context.bot.send_video, 'voice': context.bot.send_voice}
            if content_type in send_map:
                await send_map[content_type](chat_id=chat_id, **{content_type: item['file_id'], 'caption': item.get('caption', '')})

    # --- All other class methods from your bot logic go here ---
    # (show_categories, handle_search, receive_content, receive_category, save_note, etc.)
    async def show_categories(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        self._report(update)
        categories = self.db.get_user_categories(update.effective_user.id)
        if not categories:
            await update.message.reply_text("אין קטגוריות עדיין.")
            return
        keyboard = [[InlineKeyboardButton(f"{cat} ({self.db.get_category_count(update.effective_user.id, cat)})", callback_data=f"showcat_{cat}")] for cat in categories]
        await update.message.reply_text("בחר קטגוריה להצגה:", reply_markup=InlineKeyboardMarkup(keyboard))

    async def handle_search_query(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        self._report(update)
        query = update.message.text.strip()
        results = self.db.search_items(update.effective_user.id, query)
        if not results:
            await update.message.reply_text("לא נמצאו תוצאות.")
        else:
            keyboard = [[InlineKeyboardButton(f"{item['category']} | {item['subject']}", callback_data=f"showitem_{item['id']}")] for item in results[:10]]
            await update.message.reply_text(f"נמצאו {len(results)} תוצאות:", reply_markup=InlineKeyboardMarkup(keyboard))
        return await self.start(update, context) # Return to main menu

    async def receive_content(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        self._report(update)
        message = update.message

        content_data = {}
        if message.text: content_data.update({'type': 'text', 'content': message.text})
        elif message.photo: content_data.update({'type': 'photo', 'file_id': message.photo[-1].file_id, 'caption': message.caption or ""})
        elif message.document: content_data.update({'type': 'document', 'file_id': message.document.file_id, 'file_name': message.document.file_name, 'caption': message.caption or ""})
        else:
            await update.message.reply_text("סוג תוכן לא נתמך.")
            return await self.start(update, context)

        context.user_data['new_item'] = content_data

        categories = self.db.get_user_categories(update.effective_user.id)
        keyboard = [[InlineKeyboardButton(c, callback_data=f"cat_{c}")] for c in categories]
        keyboard.append([InlineKeyboardButton("🆕 קטגוריה חדשה", callback_data="cat_new")])
        await update.message.reply_text("בחר קטגוריה:", reply_markup=InlineKeyboardMarkup(keyboard))
        return AWAIT_CATEGORY

    async def receive_category(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        self._report(update)
        query = update.callback_query
        category_name = ""
        if query:
            await query.answer()
            if query.data == 'cat_new':
                await query.edit_message_text("הקלד שם לקטגוריה החדשה:")
                return AWAIT_CATEGORY
            category_name = query.data.replace('cat_', '')
            await query.edit_message_text(f"קטגוריה: {category_name}\n\nכעת, הקלד נושא:")
        else:
            category_name = update.message.text.strip()
            await update.message.reply_text(f"קטגוריה: {category_name}\n\nכעת, הקלד נושא:")

        context.user_data['new_item']['category'] = category_name
        return AWAIT_SUBJECT

    async def receive_subject_and_save(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        self._report(update)
        context.user_data['new_item']['subject'] = update.message.text.strip()
        item_data = context.user_data['new_item']
        
        # Call the save_item function with all required parameters
        item_id = self.db.save_item(
            user_id=update.effective_user.id,
            category=item_data.get('category'),
            subject=item_data.get('subject'),
            content_type=item_data.get('type'),
            content=item_data.get('content', ''),
            file_id=item_data.get('file_id', ''),
            file_name=item_data.get('file_name', ''),
            caption=item_data.get('caption', '')
        )
        
        await update.message.reply_text("✅ נשמר בהצלחה!")
        await self.show_item_with_actions(update, context, item_id)
        
        # Clean up user_data and return to the main menu
        del context.user_data['new_item']
        return await self.start(update, context)

    async def save_note(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        self._report(update)
        item_id = context.user_data.get('action_item_id')
        if not item_id: return await self.start(update, context)
        self.db.update_note(item_id, update.message.text)
        await update.message.reply_text("✅ ההערה עודכנה.")
        await self.show_item_with_actions(update, context, item_id)
        del context.user_data['action_item_id']
        return await self.start(update, context)

    async def item_action_router(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        self._report(update)
        query = update.callback_query; await query.answer()
        action, item_id_str = query.data.split('_', 1)
        item_id = int(item_id_str)

        if action in ['showitem', 'pin', 'delete']:
            if action == 'pin': self.db.toggle_pin(item_id)
            if action == 'delete': self.db.delete_item(item_id); await query.edit_message_text("✅ הפריט נמחק."); return SELECTING_ACTION
            await self.show_item_with_actions(query, context, item_id)
            return SELECTING_ACTION

        context.user_data['action_item_id'] = item_id
        if action == 'note': await query.edit_message_text("הקלד את ההערה:"); return AWAIT_NOTE
        elif action == 'edit': await query.edit_message_text("שלח את התוכן החדש:"); return AWAIT_EDIT
        elif action == 'editsubject': await query.edit_message_text("הקלד את הנושא החדש:"); return AWAIT_SUBJECT_EDIT

        return SELECTING_ACTION

    async def save_edited_subject(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        self._report(update)
        item_id = context.user_data.get('action_item_id')
        if not item_id:
            return await self.start(update, context)
        new_subject = update.message.text.strip()
        self.db.update_subject(item_id, new_subject)
        await update.message.reply_text("✅ הנושא עודכן.")
        await self.show_item_with_actions(update, context, item_id)
        del context.user_data['action_item_id']
        return await self.start(update, context)

    async def show_category_items(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        self._report(update)
        query = update.callback_query; await query.answer()
        category = query.data.replace('showcat_', '')
        items = self.db.get_category_items(update.effective_user.id, category)
        if not items:
            await query.edit_message_text("אין פריטים בקטגוריה זו.")
            return
        keyboard = [[InlineKeyboardButton(f"{'📌 ' if item['is_pinned'] else ''}{item['subject']}", callback_data=f"showitem_{item['id']}")] for item in items]
        await query.edit_message_text(f"📁 פריטים בקטגוריית {category}:", reply_markup=InlineKeyboardMarkup(keyboard))

    async def show_settings(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        self._report(update)
        await update.message.reply_text("אזור הגדרות (בבנייה).")

    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        self._report(update)
        await update.message.reply_text("הפעולה בוטלה.")
        return await self.start(update, context)

def main() -> None:
    token = os.environ.get('BOT_TOKEN')
    if not token: logger.error("FATAL: BOT_TOKEN is not set."); return

    flask_thread = threading.Thread(target=run_flask)
    flask_thread.start()

    bot = SaveMeBot()
    application = Application.builder().token(token).build()
    application.add_error_handler(error_handler)

    # Bot commands setup skipped to keep main() synchronous

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', bot.start), CommandHandler('tomd', bot.ask_for_md_text), CommandHandler('upload', bot.upload_help)],
        states={
                         SELECTING_ACTION: [
                 MessageHandler(filters.TEXT & filters.Regex('^➕ הוסף תוכן$'), bot.ask_for_content),
                 MessageHandler(filters.TEXT & filters.Regex('^📝 המרה ל-Markdown$'), bot.ask_for_md_text),
                 MessageHandler(filters.TEXT & filters.Regex('^🧩 איסוף טקסט רב-הודעות$'), bot.start_multipart),
                 MessageHandler(filters.TEXT & filters.Regex('^🔍 חיפוש$'), bot.ask_for_search_query),
                 MessageHandler(filters.TEXT & filters.Regex('^📚 הצג קטגוריות$'), bot.show_categories),
                 MessageHandler(filters.TEXT & filters.Regex('^⚙️ הגדרות$'), bot.show_settings),
                 CallbackQueryHandler(bot.show_category_items, pattern="^showcat_"),
                 CallbackQueryHandler(bot.upload_router, pattern="^(upload_start_multipart|upload_close)$"),
                 CallbackQueryHandler(bot.item_action_router, pattern="^(showitem_|pin_|delete_|note_|edit_|editsubject_)")
             ],
             AWAIT_CONTENT: [MessageHandler(filters.ALL & ~filters.COMMAND, bot.receive_content)],
             AWAIT_CATEGORY: [CallbackQueryHandler(bot.receive_category, pattern="^cat_"), MessageHandler(filters.TEXT & ~filters.COMMAND, bot.receive_category)],
             AWAIT_SUBJECT: [MessageHandler(filters.TEXT & ~filters.COMMAND, bot.receive_subject_and_save)],
             AWAIT_SEARCH: [MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_search_query)],
             AWAIT_NOTE: [MessageHandler(filters.TEXT & ~filters.COMMAND, bot.save_note)],
             AWAIT_EDIT: [MessageHandler(filters.ALL & ~filters.COMMAND, lambda u,c: c.bot.send_message(u.effective_chat.id, "Edit not implemented yet"))], # Placeholder
             AWAIT_SUBJECT_EDIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, bot.save_edited_subject)],
             AWAIT_MD_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, bot.convert_text_to_md_and_send)],
             AWAIT_MULTIPART: [
                 CallbackQueryHandler(bot.multipart_router, pattern='^(multipart_end|multipart_cancel)$'),
                 MessageHandler(filters.TEXT & ~filters.COMMAND, bot.multipart_router)
             ]
         },
        fallbacks=[CommandHandler('cancel', bot.cancel)],
        allow_reentry=True
    )

    application.add_handler(conv_handler)

    logger.info("Bot is starting to poll...")
    application.run_polling()

if __name__ == '__main__':
    main()
