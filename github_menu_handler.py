import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackQueryHandler, ConversationHandler, MessageHandler, filters, CommandHandler
from github import Github
from typing import Dict, Any
import base64
import logging

# הגדרת לוגר
logger = logging.getLogger(__name__)

# מצבי שיחה
REPO_SELECT, FILE_UPLOAD, FOLDER_SELECT = range(3)

class GitHubMenuHandler:
    def __init__(self):
        self.user_sessions: Dict[int, Dict[str, Any]] = {}
        
    def get_user_session(self, user_id: int) -> Dict[str, Any]:
        """Get or create user session"""
        if user_id not in self.user_sessions:
            self.user_sessions[user_id] = {
                'selected_repo': None,
                'selected_folder': None,  # None = root של הריפו
                'github_token': None
            }
        return self.user_sessions[user_id]
    
    async def github_menu_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """מציג תפריט GitHub"""
        user_id = update.effective_user.id
        
        if user_id not in self.user_sessions:
            self.user_sessions[user_id] = {}
        
        session = self.user_sessions[user_id]
        
        # בנה הודעת סטטוס
        status_msg = "🔧 *GitHub Integration Menu*\n\n"
        
        if 'github_token' in session:
            status_msg += "✅ טוקן מוגדר\n"
        else:
            status_msg += "❌ טוקן לא מוגדר\n"
        
        if 'selected_repo' in session:
            status_msg += f"📁 ריפו: `{session['selected_repo']}`\n"
            folder_display = session.get('selected_folder') or 'root'
            status_msg += f"📂 תיקייה: `{folder_display}`\n"
        else:
            status_msg += "❌ ריפו לא נבחר\n"
        
        keyboard = []
        
        # כפתור הגדרת טוקן
        if 'github_token' not in session:
            keyboard.append([InlineKeyboardButton("🔑 הגדר טוקן GitHub", callback_data="set_token")])
        
        # כפתור בחירת ריפו
        keyboard.append([InlineKeyboardButton("📁 בחר ריפו", callback_data="select_repo")])
        
        # כפתורי העלאה - מוצגים רק אם יש ריפו נבחר
        if 'selected_repo' in session:
            keyboard.append([
                InlineKeyboardButton("📤 העלה קובץ חדש", callback_data="upload_file")
            ])
            keyboard.append([
                InlineKeyboardButton("📚 העלה מהקבצים השמורים", callback_data="upload_saved")
            ])
            keyboard.append([
                InlineKeyboardButton("📂 בחר תיקיית יעד", callback_data="set_folder")
            ])
        
        # כפתור הצגת הגדרות
        keyboard.append([InlineKeyboardButton("📋 הצג הגדרות נוכחיות", callback_data="show_current")])
        
        # כפתור סגירה
        keyboard.append([InlineKeyboardButton("❌ סגור", callback_data="close_menu")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if update.callback_query:
            await update.callback_query.edit_message_text(
                status_msg, 
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(
                status_msg, 
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
    
    async def handle_menu_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle menu button clicks"""
        query = update.callback_query
        await query.answer()
        
        user_id = query.from_user.id
        session = self.get_user_session(user_id)
        
        if query.data == 'select_repo':
            await self.show_repo_selection(query, context)
            
        elif query.data == 'upload_file':
            if not session.get('selected_repo'):
                await query.edit_message_text(
                    "❌ קודם בחר ריפו!\nשלח /github ובחר 'בחר ריפו'"
                )
            else:
                folder_display = session.get('selected_folder') or 'root'
                await query.edit_message_text(
                    f"📤 *העלאת קובץ לריפו:*\n"
                    f"`{session['selected_repo']}`\n"
                    f"📂 תיקייה: `{folder_display}`\n\n"
                    f"שלח לי קובץ להעלאה:",
                    parse_mode='Markdown'
                )
                return FILE_UPLOAD
        
        elif query.data == "upload_saved":
            await self.upload_saved_files(update, context)
            
        elif query.data.startswith("repos_page_"):
            page = int(query.data.split("_")[2])
            await self.show_repos(update, context, page)
            
        elif query.data.startswith("upload_saved_"):
            file_id = query.data.split("_")[2]
            await self.handle_saved_file_upload(update, context, file_id)
            
        elif query.data == "back_to_menu":
            await self.github_menu_command(update, context)
            
        elif query.data == "noop":
            await query.answer()  # לא עושה כלום, רק לכפתור התצוגה
                
        elif query.data == 'show_current':
            current_repo = session.get('selected_repo', 'לא נבחר')
            current_folder = session.get('selected_folder') or 'root'
            has_token = "✅" if session.get('github_token') else "❌"
            
            await query.edit_message_text(
                f"📊 *הגדרות נוכחיות:*\n\n"
                f"📁 ריפו: `{current_repo}`\n"
                f"📂 תיקייה: `{current_folder}`\n"
                f"🔑 טוקן מוגדר: {has_token}\n\n"
                f"💡 טיפ: השתמש ב-'בחר תיקיית יעד' כדי לשנות את מיקום ההעלאה",
                parse_mode='Markdown'
            )
            
        elif query.data == 'set_token':
            await query.edit_message_text(
                "🔑 שלח לי את הטוקן של GitHub:\n"
                "(הטוקן יישמר רק לסשן הנוכחי)\n\n"
                "💡 טיפ: צור טוקן ב:\n"
                "https://github.com/settings/tokens"
            )
            return REPO_SELECT
            
        elif query.data == 'set_folder':
            keyboard = [
                [InlineKeyboardButton("📁 root (ראשי)", callback_data='folder_root')],
                [InlineKeyboardButton("📂 src", callback_data='folder_src')],
                [InlineKeyboardButton("📂 docs", callback_data='folder_docs')],
                [InlineKeyboardButton("📂 assets", callback_data='folder_assets')],
                [InlineKeyboardButton("📂 images", callback_data='folder_images')],
                [InlineKeyboardButton("✏️ אחר (הקלד ידנית)", callback_data='folder_custom')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                "📂 בחר תיקיית יעד:",
                reply_markup=reply_markup
            )
            
        elif query.data.startswith('folder_'):
            folder = query.data.replace('folder_', '')
            if folder == 'custom':
                await query.edit_message_text(
                    "✏️ הקלד שם תיקייה:\n"
                    "(השאר ריק או הקלד / להעלאה ל-root)"
                )
                return FOLDER_SELECT
            elif folder == 'root':
                session['selected_folder'] = None
                await query.edit_message_text("✅ תיקייה עודכנה ל: `root` (ראשי)", parse_mode='Markdown')
            else:
                session['selected_folder'] = folder.replace('_', '/')
                await query.edit_message_text(f"✅ תיקייה עודכנה ל: `{session['selected_folder']}`", parse_mode='Markdown')
                
        elif query.data == 'close_menu':
            await query.edit_message_text("👋 התפריט נסגר")
            
        elif query.data.startswith('repo_'):
            if query.data == 'repo_manual':
                await query.edit_message_text(
                    "✏️ הקלד שם ריפו בפורמט:\n"
                    "`owner/repository`\n\n"
                    "לדוגמה: `amirbiron/CodeBot`",
                    parse_mode='Markdown'
                )
                return REPO_SELECT
            else:
                repo_name = query.data.replace('repo_', '')
                session['selected_repo'] = repo_name
                await query.edit_message_text(
                    f"✅ ריפו נבחר: `{repo_name}`\n\n"
                    f"כעת תוכל להעלות קבצים!",
                    parse_mode='Markdown'
                )
    
    async def show_repo_selection(self, query, context: ContextTypes.DEFAULT_TYPE):
        """Show repository selection menu"""
        await self.show_repos(query.message, context, query=query)
    
    async def show_repos(self, update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 0, query=None):
        """מציג רשימת ריפוזיטוריז עם pagination"""
        if query:
            user_id = query.from_user.id
        else:
            user_id = update.effective_user.id
            
        session = self.user_sessions.get(user_id, {})
        
        if 'github_token' not in session:
            if query:
                await query.answer("❌ נא להגדיר טוקן קודם")
            else:
                await update.reply_text("❌ נא להגדיר טוקן קודם")
            return
        
        try:
            from github import Github
            g = Github(session['github_token'])
            user = g.get_user()
            
            # קבל את כל הריפוזיטוריז
            all_repos = list(user.get_repos())
            
            # הגדרות pagination
            repos_per_page = 8
            total_repos = len(all_repos)
            total_pages = (total_repos + repos_per_page - 1) // repos_per_page
            
            # חשב אינדקסים
            start_idx = page * repos_per_page
            end_idx = min(start_idx + repos_per_page, total_repos)
            
            # ריפוזיטוריז לעמוד הנוכחי
            page_repos = all_repos[start_idx:end_idx]
            
            keyboard = []
            
            # הוסף ריפוזיטוריז
            for repo in page_repos:
                keyboard.append([
                    InlineKeyboardButton(
                        f"📁 {repo.name}", 
                        callback_data=f"repo_{repo.full_name}"
                    )
                ])
            
            # כפתורי ניווט
            nav_buttons = []
            if page > 0:
                nav_buttons.append(
                    InlineKeyboardButton("⬅️ הקודם", callback_data=f"repos_page_{page-1}")
                )
            
            nav_buttons.append(
                InlineKeyboardButton(f"📄 {page+1}/{total_pages}", callback_data="noop")
            )
            
            if page < total_pages - 1:
                nav_buttons.append(
                    InlineKeyboardButton("➡️ הבא", callback_data=f"repos_page_{page+1}")
                )
            
            if nav_buttons:
                keyboard.append(nav_buttons)
            
            # כפתורים נוספים
            keyboard.append([InlineKeyboardButton("✍️ הקלד שם ריפו ידנית", callback_data="repo_manual")])
            keyboard.append([InlineKeyboardButton("🔙 חזור", callback_data="back_to_menu")])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            if query:
                await query.edit_message_text(
                    f"בחר ריפוזיטורי (עמוד {page+1} מתוך {total_pages}):",
                    reply_markup=reply_markup
                )
            else:
                await update.callback_query.edit_message_text(
                    f"בחר ריפוזיטורי (עמוד {page+1} מתוך {total_pages}):",
                    reply_markup=reply_markup
                )
            
        except Exception as e:
            if query:
                await query.answer(f"❌ שגיאה: {str(e)}", show_alert=True)
            else:
                await update.callback_query.answer(f"❌ שגיאה: {str(e)}", show_alert=True)
    
    async def upload_saved_files(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """מציג רשימת קבצים שמורים להעלאה"""
        user_id = update.effective_user.id
        session = self.user_sessions.get(user_id, {})
        
        if 'selected_repo' not in session:
            await update.callback_query.answer("❌ נא לבחור ריפו קודם")
            return
        
        try:
            # כאן תצטרך להתחבר למסד הנתונים שלך
            # לדוגמה:
            from database import db
            files = db.get_user_files(user_id)
            
            if not files:
                await update.callback_query.answer("❌ אין לך קבצים שמורים", show_alert=True)
                return
            
            keyboard = []
            for file in files[:10]:  # מציג עד 10 קבצים
                keyboard.append([
                    InlineKeyboardButton(
                        f"📄 {file['file_name']}", 
                        callback_data=f"upload_saved_{file['_id']}"
                    )
                ])
            
            keyboard.append([InlineKeyboardButton("🔙 חזור", callback_data="back_to_menu")])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.callback_query.edit_message_text(
                "בחר קובץ להעלאה:",
                reply_markup=reply_markup
            )
            
        except Exception as e:
            await update.callback_query.answer(f"❌ שגיאה: {str(e)}", show_alert=True)
    
    async def handle_saved_file_upload(self, update: Update, context: ContextTypes.DEFAULT_TYPE, file_id: str):
        """מטפל בהעלאת קובץ שמור ל-GitHub"""
        user_id = update.effective_user.id
        session = self.user_sessions.get(user_id, {})
        
        if 'selected_repo' not in session:
            await update.callback_query.answer("❌ נא לבחור ריפו קודם")
            return
        
        try:
            from database import db
            from bson import ObjectId
            
            # קבל את הקובץ מהמסד
            file_data = db.collection.find_one({
                "_id": ObjectId(file_id),
                "user_id": user_id
            })
            
            if not file_data:
                await update.callback_query.answer("❌ קובץ לא נמצא", show_alert=True)
                return
            
            await update.callback_query.edit_message_text("⏳ מעלה קובץ ל-GitHub...")
            
            # לוג פרטי הקובץ
            logger.info(f"📄 מעלה קובץ שמור: {file_data['file_name']}")
            
            # קודד את התוכן ל-base64
            content = file_data['content']
            if isinstance(content, str):
                # אם התוכן כבר מחרוזת, קודד אותו
                encoded_content = base64.b64encode(content.encode('utf-8')).decode('utf-8')
            else:
                # אם התוכן בינארי
                encoded_content = base64.b64encode(content).decode('utf-8')
            
            logger.info(f"✅ קודד ל-base64, גודל מקודד: {len(encoded_content)} chars")
            
            # התחבר ל-GitHub
            from github import Github
            g = Github(session['github_token'])
            repo = g.get_repo(session['selected_repo'])
            
            # הגדר נתיב הקובץ
            folder = session.get('selected_folder')
            if folder and folder.strip():
                # הסר / מיותרים
                folder = folder.strip('/')
                file_path = f"{folder}/{file_data['file_name']}"
            else:
                # העלה ל-root
                file_path = file_data['file_name']
            logger.info(f"📁 נתיב יעד: {file_path}")
            
            # נסה להעלות או לעדכן את הקובץ
            try:
                existing = repo.get_contents(file_path)
                result = repo.update_file(
                    path=file_path,
                    message=f"Update {file_data['file_name']} via Telegram bot",
                    content=encoded_content,  # שימוש בתוכן מקודד
                    sha=existing.sha
                )
                action = "עודכן"
                logger.info(f"✅ קובץ עודכן בהצלחה")
            except:
                result = repo.create_file(
                    path=file_path,
                    message=f"Upload {file_data['file_name']} via Telegram bot",
                    content=encoded_content  # שימוש בתוכן מקודד
                )
                action = "הועלה"
                logger.info(f"✅ קובץ נוצר בהצלחה")
            
            raw_url = f"https://raw.githubusercontent.com/{session['selected_repo']}/main/{file_path}"
            
            await update.callback_query.edit_message_text(
                f"✅ הקובץ {action} בהצלחה!\n\n"
                f"📁 ריפו: `{session['selected_repo']}`\n"
                f"📂 מיקום: `{file_path}`\n"
                f"🔗 קישור ישיר:\n{raw_url}",
                parse_mode='Markdown'
            )
            
        except Exception as e:
            logger.error(f"❌ שגיאה בהעלאת קובץ שמור: {str(e)}", exc_info=True)
            await update.callback_query.edit_message_text(
                f"❌ שגיאה בהעלאה:\n{str(e)}\n\n"
                f"פרטים נוספים נשמרו בלוג."
            )
    
    async def handle_file_upload(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle file upload"""
        user_id = update.message.from_user.id
        session = self.get_user_session(user_id)
        
        if not session.get('selected_repo'):
            await update.message.reply_text(
                "❌ קודם בחר ריפו!\nשלח /github"
            )
            return ConversationHandler.END
        
        if update.message.document:
            await update.message.reply_text("⏳ מעלה קובץ...")
            
            try:
                file = await context.bot.get_file(update.message.document.file_id)
                file_data = await file.download_as_bytearray()
                filename = update.message.document.file_name
                
                # לוג גודל וסוג הקובץ
                file_size = len(file_data)
                logger.info(f"📄 מעלה קובץ: {filename}, גודל: {file_size} bytes")
                
                # קודד ל-base64
                encoded_content = base64.b64encode(file_data).decode('utf-8')
                logger.info(f"✅ קודד ל-base64, גודל מקודד: {len(encoded_content)} chars")
                
                token = session.get('github_token') or os.environ.get('GITHUB_TOKEN')
                
                g = Github(token)
                repo = g.get_repo(session['selected_repo'])
                
                # בניית נתיב הקובץ
                folder = session.get('selected_folder')
                if folder and folder.strip():
                    # הסר / מיותרים
                    folder = folder.strip('/')
                    file_path = f"{folder}/{filename}"
                else:
                    # העלה ל-root
                    file_path = filename
                logger.info(f"📁 נתיב יעד: {file_path}")
                
                try:
                    existing = repo.get_contents(file_path)
                    result = repo.update_file(
                        path=file_path,
                        message=f"Update {filename} via Telegram bot",
                        content=encoded_content,  # שימוש בתוכן מקודד
                        sha=existing.sha
                    )
                    action = "עודכן"
                    logger.info(f"✅ קובץ עודכן בהצלחה")
                except:
                    result = repo.create_file(
                        path=file_path,
                        message=f"Upload {filename} via Telegram bot",
                        content=encoded_content  # שימוש בתוכן מקודד
                    )
                    action = "הועלה"
                    logger.info(f"✅ קובץ נוצר בהצלחה")
                
                raw_url = f"https://raw.githubusercontent.com/{session['selected_repo']}/main/{file_path}"
                
                await update.message.reply_text(
                    f"✅ הקובץ {action} בהצלחה!\n\n"
                    f"📁 ריפו: `{session['selected_repo']}`\n"
                    f"📂 מיקום: `{file_path}`\n"
                    f"🔗 קישור ישיר:\n{raw_url}",
                    parse_mode='Markdown'
                )
                
            except Exception as e:
                logger.error(f"❌ שגיאה בהעלאה: {str(e)}", exc_info=True)
                await update.message.reply_text(
                    f"❌ שגיאה בהעלאה:\n{str(e)}\n\n"
                    f"פרטים נוספים נשמרו בלוג."
                )
        else:
            await update.message.reply_text("⚠️ שלח קובץ להעלאה")
        
        return ConversationHandler.END
    
    async def handle_text_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle text input for various states"""
        user_id = update.message.from_user.id
        session = self.get_user_session(user_id)
        text = update.message.text
        
        if text.startswith('ghp_') or text.startswith('github_pat_'):
            session['github_token'] = text
            await update.message.reply_text(
                "✅ טוקן נשמר בהצלחה!\n"
                "כעת תוכל לגשת לריפוזיטוריז הפרטיים שלך."
            )
            return ConversationHandler.END
        
        elif '/' in text:
            session['selected_repo'] = text
            await update.message.reply_text(
                f"✅ ריפו הוגדר: `{text}`",
                parse_mode='Markdown'
            )
            return ConversationHandler.END
        
        else:
            # טיפול בהגדרת תיקייה
            if text.strip() in ['/', '']:
                session['selected_folder'] = None
                await update.message.reply_text(
                    "✅ תיקייה הוגדרה: `root` (ראשי)",
                    parse_mode='Markdown'
                )
            else:
                # הסר / מיותרים
                folder = text.strip().strip('/')
                session['selected_folder'] = folder
                await update.message.reply_text(
                    f"✅ תיקייה הוגדרה: `{folder}`",
                    parse_mode='Markdown'
                )
            return ConversationHandler.END