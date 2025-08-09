import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackQueryHandler, ConversationHandler, MessageHandler, filters, CommandHandler
from github import Github
from typing import Dict, Any

# מצבי שיחה
REPO_SELECT, FILE_UPLOAD, FOLDER_SELECT = range(3)

class GitHubMenuHandler:
    def __init__(self):
        self.user_sessions: Dict[int, Dict[str, Any]] = {}
        
    def get_user_session(self, user_id: int) -> Dict[str, Any]:
        """Get or create user session"""
        if user_id not in self.user_sessions:
            self.user_sessions[user_id] = {
                'repo': None,
                'folder': 'uploads',
                'github_token': None
            }
        return self.user_sessions[user_id]
    
    async def github_menu_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show main GitHub menu"""
        keyboard = [
            [InlineKeyboardButton("📁 בחר ריפו", callback_data='select_repo')],
            [InlineKeyboardButton("📤 העלה קובץ", callback_data='upload_file')],
            [InlineKeyboardButton("📋 הצג ריפו נוכחי", callback_data='show_current')],
            [InlineKeyboardButton("🔑 הגדר טוקן GitHub", callback_data='set_token')],
            [InlineKeyboardButton("📂 שנה תיקיית יעד", callback_data='set_folder')],
            [InlineKeyboardButton("❌ סגור", callback_data='close_menu')]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "🔧 *תפריט GitHub*\n"
            "בחר פעולה:",
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
            if not session.get('repo'):
                await query.edit_message_text(
                    "❌ קודם בחר ריפו!\nשלח /github ובחר 'בחר ריפו'"
                )
            else:
                await query.edit_message_text(
                    f"📤 *העלאת קובץ לריפו:*\n"
                    f"`{session['repo']}`\n"
                    f"📂 תיקייה: `{session['folder']}`\n\n"
                    f"שלח לי קובץ להעלאה:",
                    parse_mode='Markdown'
                )
                return FILE_UPLOAD
                
        elif query.data == 'show_current':
            current_repo = session.get('repo', 'לא נבחר')
            current_folder = session.get('folder', 'uploads')
            has_token = "✅" if session.get('github_token') else "❌"
            
            await query.edit_message_text(
                f"📊 *הגדרות נוכחיות:*\n\n"
                f"📁 ריפו: `{current_repo}`\n"
                f"📂 תיקייה: `{current_folder}`\n"
                f"🔑 טוקן מוגדר: {has_token}",
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
                [InlineKeyboardButton("uploads", callback_data='folder_uploads')],
                [InlineKeyboardButton("assets", callback_data='folder_assets')],
                [InlineKeyboardButton("assets/images", callback_data='folder_assets_images')],
                [InlineKeyboardButton("docs", callback_data='folder_docs')],
                [InlineKeyboardButton("אחר (הקלד ידנית)", callback_data='folder_custom')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                "📂 בחר תיקיית יעד:",
                reply_markup=reply_markup
            )
            
        elif query.data.startswith('folder_'):
            folder = query.data.replace('folder_', '')
            if folder == 'custom':
                await query.edit_message_text("הקלד שם תיקייה:")
                return FOLDER_SELECT
            else:
                session['folder'] = folder.replace('_', '/')
                await query.edit_message_text(f"✅ תיקייה עודכנה ל: `{session['folder']}`", parse_mode='Markdown')
                
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
                session['repo'] = repo_name
                await query.edit_message_text(
                    f"✅ ריפו נבחר: `{repo_name}`\n\n"
                    f"כעת תוכל להעלות קבצים!",
                    parse_mode='Markdown'
                )
    
    async def show_repo_selection(self, query, context: ContextTypes.DEFAULT_TYPE):
        """Show repository selection menu"""
        user_id = query.from_user.id
        session = self.get_user_session(user_id)
        
        token = session.get('github_token') or os.environ.get('GITHUB_TOKEN')
        
        if not token:
            await query.edit_message_text(
                "❌ לא נמצא טוקן GitHub!\n"
                "שלח /github ובחר 'הגדר טוקן'"
            )
            return
        
        try:
            g = Github(token)
            user = g.get_user()
            
            repos = list(user.get_repos())[:10]
            
            keyboard = []
            for repo in repos:
                keyboard.append([
                    InlineKeyboardButton(
                        f"📁 {repo.full_name}",
                        callback_data=f'repo_{repo.full_name}'
                    )
                ])
            
            keyboard.append([
                InlineKeyboardButton("✏️ הקלד ריפו ידנית", callback_data='repo_manual')
            ])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                "📁 בחר ריפו מהרשימה:",
                reply_markup=reply_markup
            )
            
        except Exception as e:
            await query.edit_message_text(
                f"❌ שגיאה בטעינת ריפוזיטוריז:\n{str(e)}"
            )
    
    async def handle_file_upload(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle file upload"""
        user_id = update.message.from_user.id
        session = self.get_user_session(user_id)
        
        if not session.get('repo'):
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
                
                token = session.get('github_token') or os.environ.get('GITHUB_TOKEN')
                
                g = Github(token)
                repo = g.get_repo(session['repo'])
                
                file_path = f"{session['folder']}/{filename}"
                
                try:
                    existing = repo.get_contents(file_path)
                    result = repo.update_file(
                        path=file_path,
                        message=f"Update {filename} via Telegram bot",
                        content=file_data,
                        sha=existing.sha
                    )
                    action = "עודכן"
                except:
                    result = repo.create_file(
                        path=file_path,
                        message=f"Upload {filename} via Telegram bot",
                        content=file_data
                    )
                    action = "הועלה"
                
                raw_url = f"https://raw.githubusercontent.com/{session['repo']}/main/{file_path}"
                
                await update.message.reply_text(
                    f"✅ הקובץ {action} בהצלחה!\n\n"
                    f"📁 ריפו: `{session['repo']}`\n"
                    f"📂 מיקום: `{file_path}`\n"
                    f"🔗 קישור ישיר:\n{raw_url}",
                    parse_mode='Markdown'
                )
                
            except Exception as e:
                await update.message.reply_text(
                    f"❌ שגיאה בהעלאה:\n{str(e)}"
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
            session['repo'] = text
            await update.message.reply_text(
                f"✅ ריפו הוגדר: `{text}`",
                parse_mode='Markdown'
            )
            return ConversationHandler.END
        
        else:
            session['folder'] = text
            await update.message.reply_text(
                f"✅ תיקייה הוגדרה: `{text}`",
                parse_mode='Markdown'
            )
            return ConversationHandler.END