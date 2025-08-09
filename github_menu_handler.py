import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackQueryHandler, ConversationHandler, MessageHandler, filters, CommandHandler
from github import Github
from typing import Dict, Any
import logging
import time
import asyncio
import json
from repo_analyzer import RepoAnalyzer
from datetime import datetime

# הגדרת לוגר
logger = logging.getLogger(__name__)

# מצבי שיחה
REPO_SELECT, FILE_UPLOAD, FOLDER_SELECT = range(3)

class GitHubMenuHandler:
    def __init__(self):
        self.user_sessions: Dict[int, Dict[str, Any]] = {}
        self.last_api_call = {}  # מעקב אחר זמן הבקשה האחרונה לכל משתמש
        
    def get_user_session(self, user_id: int) -> Dict[str, Any]:
        """Get or create user session"""
        if user_id not in self.user_sessions:
            self.user_sessions[user_id] = {
                'selected_repo': None,
                'selected_folder': None,  # None = root של הריפו
                'github_token': None
            }
        return self.user_sessions[user_id]
    
    async def check_rate_limit(self, github_client: Github, update_or_query) -> bool:
        """בודק את מגבלת ה-API של GitHub"""
        try:
            rate_limit = github_client.get_rate_limit()
            core_limit = rate_limit.core
            
            if core_limit.remaining < 10:
                reset_time = core_limit.reset
                minutes_until_reset = max(1, int((reset_time - time.time()) / 60))
                
                error_message = (
                    f"⏳ חריגה ממגבלת GitHub API\n"
                    f"נותרו רק {core_limit.remaining} בקשות\n"
                    f"המגבלה תתאפס בעוד {minutes_until_reset} דקות\n\n"
                    f"💡 נסה שוב מאוחר יותר"
                )
                
                # בדוק אם זה callback query או update רגיל
                if hasattr(update_or_query, 'answer'):
                    # זה callback query
                    await update_or_query.answer(error_message, show_alert=True)
                else:
                    # זה update רגיל
                    await update_or_query.message.reply_text(error_message)
                
                return False
            
            return True
        except Exception as e:
            logger.error(f"Error checking rate limit: {e}")
            return True  # במקרה של שגיאה, נמשיך בכל זאת
    
    async def apply_rate_limit_delay(self, user_id: int):
        """מוסיף השהייה בין בקשות API"""
        current_time = time.time()
        last_call = self.last_api_call.get(user_id, 0)
        
        # אם עברו פחות מ-2 שניות מהבקשה האחרונה, נחכה
        time_since_last = current_time - last_call
        if time_since_last < 2:
            await asyncio.sleep(2 - time_since_last)
        
        self.last_api_call[user_id] = time.time()
    
    async def github_menu_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """מציג תפריט GitHub"""
        user_id = update.effective_user.id
        
        if user_id not in self.user_sessions:
            self.user_sessions[user_id] = {}
        
        session = self.user_sessions[user_id]
        
        # בדיקת טוקן
        token = session.get('github_token')
        logger.info(f"[GitHub] Token exists: {bool(token)}")
        if token:
            logger.info(f"[GitHub] Token length: {len(token)}")
        
        # בנה הודעת סטטוס
        status_msg = "🔧 *GitHub Integration Menu*\n\n"
        
        if session.get('github_token'):
            status_msg += "✅ טוקן מוגדר\n"
        else:
            status_msg += "❌ טוקן לא מוגדר\n"
        
        if session.get('selected_repo'):
            status_msg += f"📁 ריפו: `{session['selected_repo']}`\n"
            folder_display = session.get('selected_folder') or 'root'
            status_msg += f"📂 תיקייה: `{folder_display}`\n"
        else:
            status_msg += "❌ ריפו לא נבחר\n"
        
        keyboard = []
        
        # כפתור הגדרת טוקן
        if not session.get('github_token'):
            keyboard.append([InlineKeyboardButton("🔑 הגדר טוקן GitHub", callback_data="set_token")])
        
        # כפתור בחירת ריפו
        keyboard.append([InlineKeyboardButton("📁 בחר ריפו", callback_data="select_repo")])
        
        # כפתורי העלאה - מוצגים רק אם יש ריפו נבחר
        if session.get('selected_repo'):
            keyboard.append([
                InlineKeyboardButton("📚 העלה מהקבצים השמורים", callback_data="upload_saved")
            ])
            keyboard.append([
                InlineKeyboardButton("📂 בחר תיקיית יעד", callback_data="set_folder")
            ])
        
        # כפתור ניתוח ריפו - תמיד מוצג אם יש טוקן
        if session.get('github_token'):
            keyboard.append([InlineKeyboardButton("🔍 נתח ריפו", callback_data="analyze_repo")])
        
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
                
                # הוסף כפתור למנהל קבצים
                keyboard = [
                    [InlineKeyboardButton("📂 פתח מנהל קבצים", switch_inline_query_current_chat="")],
                    [InlineKeyboardButton("❌ ביטול", callback_data="github_menu")]
                ]
                
                await query.edit_message_text(
                    f"📤 *העלאת קובץ לריפו:*\n"
                    f"`{session['selected_repo']}`\n"
                    f"📂 תיקייה: `{folder_display}`\n\n"
                    f"שלח קובץ או לחץ לפתיחת מנהל קבצים:",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode='Markdown'
                )
                
                # סמן שאנחנו במצב העלאה לגיטהאב
                context.user_data['waiting_for_github_upload'] = True
                context.user_data['upload_mode'] = 'github'  # הוסף גם את המשתנה החדש
                context.user_data['target_repo'] = session['selected_repo']
                context.user_data['target_folder'] = session.get('selected_folder', '')
                context.user_data['in_github_menu'] = True
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
                
        elif query.data == 'analyze_repo':
            await self.show_analyze_repo_menu(update, context)
        
        elif query.data == 'analyze_current_repo':
            # נתח את הריפו הנבחר
            session = self.get_user_session(query.from_user.id)
            repo_url = f"https://github.com/{session['selected_repo']}"
            await self.analyze_repository(update, context, repo_url)
        
        elif query.data == 'analyze_other_repo':
            await self.request_repo_url(update, context)
        
        elif query.data == 'show_suggestions':
            await self.show_improvement_suggestions(update, context)
        
        elif query.data == 'show_full_analysis':
            await self.show_full_analysis(update, context)
        
        elif query.data == 'download_analysis_json':
            await self.download_analysis_json(update, context)
        
        elif query.data == 'back_to_analysis':
            await self.show_analyze_results_menu(update, context)
        
        elif query.data.startswith('suggestion_'):
            suggestion_index = int(query.data.split('_')[1])
            await self.show_suggestion_details(update, context, suggestion_index)
            
        elif query.data == 'show_current':
            current_repo = session.get('selected_repo', 'לא נבחר')
            current_folder = session.get('selected_folder') or 'root'
            has_token = "✅" if session.get('github_token') else "❌"
            
            await query.edit_message_text(
                f"📊 *הגדרות נוכחיות:*\n\n"
                f"📁 ריפו: `{current_repo}`\n"
                f"📂 תיקייה: `{current_folder}`\n"
                f"🔑 טוקן מוגדר: {has_token}\n\n"
                f"💡 טיפ: השתמש ב-'בחר תיקיית יעד' כדי לשנות את מיקום ההעלאה\n\n"
                f"⏳ חוזר לתפריט בעוד מספר שניות...",
                parse_mode='Markdown'
            )
            
            # המתן 3 שניות ואז הצג את התפריט
            await asyncio.sleep(3)
            await self.github_menu_command(update, context)
            
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
                [InlineKeyboardButton("✏️ אחר (הקלד ידנית)", callback_data='folder_custom')],
                [InlineKeyboardButton("🔙 חזור לתפריט", callback_data='github_menu')]
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
                await query.edit_message_text(
                    "✅ תיקייה עודכנה ל: `root` (ראשי)\n\n⏳ חוזר לתפריט...", 
                    parse_mode='Markdown'
                )
                # המתן שנייה ואז הצג את התפריט
                await asyncio.sleep(1.5)
                await self.github_menu_command(update, context)
            else:
                session['selected_folder'] = folder.replace('_', '/')
                await query.edit_message_text(
                    f"✅ תיקייה עודכנה ל: `{session['selected_folder']}`\n\n⏳ חוזר לתפריט...", 
                    parse_mode='Markdown'
                )
                # המתן שנייה ואז הצג את התפריט
                await asyncio.sleep(1.5)
                await self.github_menu_command(update, context)
                
        elif query.data == 'github_menu':
            # חזרה לתפריט הראשי של GitHub
            await query.answer()
            context.user_data['waiting_for_github_upload'] = False
            context.user_data['upload_mode'] = None  # נקה גם את המשתנה החדש
            context.user_data['in_github_menu'] = False
            await self.github_menu_command(update, context)
            return ConversationHandler.END
            
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
                
                # הצג את התפריט המלא אחרי בחירת הריפו
                await self.github_menu_command(update, context)
                return
    
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
        
        if not session.get('github_token'):
            if query:
                await query.answer("❌ נא להגדיר טוקן קודם")
            else:
                await update.reply_text("❌ נא להגדיר טוקן קודם")
            return
        
        try:
            # בדוק אם יש repos ב-context.user_data ואם הם עדיין תקפים
            cache_time = context.user_data.get('repos_cache_time', 0)
            current_time = time.time()
            cache_age = current_time - cache_time
            cache_max_age = 3600  # שעה אחת
            
            needs_refresh = (
                'repos' not in context.user_data or 
                cache_age > cache_max_age
            )
            
            if needs_refresh:
                logger.info(f"[GitHub API] Fetching repos for user {user_id} (cache age: {int(cache_age)}s)")
                
                # אם אין cache או שהוא ישן, בצע בקשה ל-API
                from github import Github
                g = Github(session['github_token'])
                
                # בדוק rate limit לפני הבקשה
                rate = g.get_rate_limit()
                logger.info(f"[GitHub API] Rate limit - Remaining: {rate.core.remaining}/{rate.core.limit}")
                
                if rate.core.remaining < 100:
                    logger.warning(f"[GitHub API] Low on API calls! Only {rate.core.remaining} remaining")
                
                if rate.core.remaining < 10:
                    # אם יש cache ישן, השתמש בו במקום לחסום
                    if 'repos' in context.user_data:
                        logger.warning(f"[GitHub API] Using stale cache due to rate limit")
                        all_repos = context.user_data['repos']
                    else:
                        if query:
                            await query.answer(
                                f"⏳ מגבלת API נמוכה! נותרו רק {rate.core.remaining} בקשות",
                                show_alert=True
                            )
                            return
                else:
                    # הוסף delay בין בקשות
                    await self.apply_rate_limit_delay(user_id)
                    
                    user = g.get_user()
                    logger.info(f"[GitHub API] Getting repos for user: {user.login}")
                    
                    # קבל את כל הריפוזיטוריז - טען רק פעם אחת!
                    context.user_data['repos'] = list(user.get_repos())
                    context.user_data['repos_cache_time'] = current_time
                    logger.info(f"[GitHub API] Loaded {len(context.user_data['repos'])} repos into cache")
                    all_repos = context.user_data['repos']
            else:
                logger.info(f"[Cache] Using cached repos for user {user_id} - {len(context.user_data.get('repos', []))} repos (age: {int(cache_age)}s)")
                all_repos = context.user_data['repos']
            
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
            error_msg = str(e)
            
            # בדוק אם זו שגיאת rate limit
            if "rate limit" in error_msg.lower() or "403" in error_msg:
                error_msg = (
                    "⏳ חריגה ממגבלת GitHub API\n"
                    "נסה שוב בעוד כמה דקות"
                )
            else:
                error_msg = f"❌ שגיאה: {error_msg}"
            
            if query:
                await query.answer(error_msg, show_alert=True)
            else:
                await update.callback_query.answer(error_msg, show_alert=True)
    
    async def upload_saved_files(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """מציג רשימת קבצים שמורים להעלאה"""
        user_id = update.effective_user.id
        session = self.user_sessions.get(user_id, {})
        
        if not session.get('selected_repo'):
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
        
        if not session.get('selected_repo'):
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
            
            # קבל את התוכן מהקובץ השמור
            # בדוק כמה אפשרויות לשדה content
            content = file_data.get('content') or \
                     file_data.get('code') or \
                     file_data.get('data') or \
                     file_data.get('file_content', '')
            
            if not content:
                await update.callback_query.edit_message_text("❌ תוכן הקובץ ריק או לא נמצא")
                return
                
            # PyGithub מקודד אוטומטית ל-base64, אז רק נוודא שהתוכן הוא string
            if isinstance(content, bytes):
                content = content.decode('utf-8')
            
            logger.info(f"✅ תוכן מוכן להעלאה, גודל: {len(content)} chars")
            
            # התחבר ל-GitHub
            from github import Github
            g = Github(session['github_token'])
            
            # בדוק rate limit לפני הבקשה
            logger.info(f"[GitHub API] Checking rate limit before uploading file")
            rate = g.get_rate_limit()
            logger.info(f"[GitHub API] Rate limit - Remaining: {rate.core.remaining}/{rate.core.limit}")
            
            if rate.core.remaining < 100:
                logger.warning(f"[GitHub API] Low on API calls! Only {rate.core.remaining} remaining")
            
            if rate.core.remaining < 10:
                await update.callback_query.answer(
                    f"⏳ מגבלת API נמוכה מדי! נותרו רק {rate.core.remaining} בקשות",
                    show_alert=True
                )
                return
            
            # הוסף delay בין בקשות
            await self.apply_rate_limit_delay(user_id)
            
            logger.info(f"[GitHub API] Getting repo: {session['selected_repo']}")
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
                logger.info(f"[GitHub API] Checking if file exists: {file_path}")
                existing = repo.get_contents(file_path)
                logger.info(f"[GitHub API] File exists, updating: {file_path}")
                result = repo.update_file(
                    path=file_path,
                    message=f"Update {file_data['file_name']} via Telegram bot",
                    content=content,  # PyGithub יקודד אוטומטית
                    sha=existing.sha
                )
                action = "עודכן"
                logger.info(f"✅ קובץ עודכן בהצלחה")
            except:
                logger.info(f"[GitHub API] File doesn't exist, creating: {file_path}")
                result = repo.create_file(
                    path=file_path,
                    message=f"Upload {file_data['file_name']} via Telegram bot",
                    content=content  # PyGithub יקודד אוטומטית
                )
                action = "הועלה"
                logger.info(f"[GitHub API] File created successfully: {file_path}")
            
            raw_url = f"https://raw.githubusercontent.com/{session['selected_repo']}/main/{file_path}"
            
            await update.callback_query.edit_message_text(
                f"✅ הקובץ {action} בהצלחה!\n\n"
                f"📁 ריפו: `{session['selected_repo']}`\n"
                f"📂 מיקום: `{file_path}`\n"
                f"🔗 קישור ישיר:\n{raw_url}\n\n"
                f"שלח /github כדי לחזור לתפריט.",
                parse_mode='Markdown'
            )
            
        except Exception as e:
            logger.error(f"❌ שגיאה בהעלאת קובץ שמור: {str(e)}", exc_info=True)
            
            error_msg = str(e)
            
            # בדוק אם זו שגיאת rate limit
            if "rate limit" in error_msg.lower() or "403" in error_msg:
                error_msg = (
                    "⏳ חריגה ממגבלת GitHub API\n"
                    "נסה שוב בעוד כמה דקות\n\n"
                    "💡 טיפ: המתן מספר דקות לפני ניסיון נוסף"
                )
            else:
                error_msg = f"❌ שגיאה בהעלאה:\n{error_msg}\n\nפרטים נוספים נשמרו בלוג."
            
            await update.callback_query.edit_message_text(error_msg)
    
    async def handle_file_upload(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle file upload"""
        user_id = update.message.from_user.id
        session = self.get_user_session(user_id)
        
        # בדוק אם אנחנו במצב העלאה לגיטהאב (תמיכה בשני המשתנים)
        if context.user_data.get('waiting_for_github_upload') or context.user_data.get('upload_mode') == 'github':
            # העלאה לגיטהאב
            repo_name = context.user_data.get('target_repo') or session.get('selected_repo')
            if not repo_name:
                await update.message.reply_text(
                    "❌ קודם בחר ריפו!\nשלח /github"
                )
                return ConversationHandler.END
            
            if update.message.document:
                await update.message.reply_text("⏳ מעלה קובץ לגיטהאב...")
                
                try:
                    file = await context.bot.get_file(update.message.document.file_id)
                    file_data = await file.download_as_bytearray()
                    filename = update.message.document.file_name
                    
                    # לוג גודל וסוג הקובץ
                    file_size = len(file_data)
                    logger.info(f"📄 מעלה קובץ: {filename}, גודל: {file_size} bytes")
                    
                    # PyGithub מקודד אוטומטית ל-base64, אז נמיר ל-string אם צריך
                    if isinstance(file_data, (bytes, bytearray)):
                        content = file_data.decode('utf-8')
                    else:
                        content = str(file_data)
                    logger.info(f"✅ תוכן מוכן להעלאה, גודל: {len(content)} chars")
                    
                    token = session.get('github_token') or os.environ.get('GITHUB_TOKEN')
                    
                    g = Github(token)
                    
                    # בדוק rate limit לפני הבקשה
                    logger.info(f"[GitHub API] Checking rate limit before file upload")
                    rate = g.get_rate_limit()
                    logger.info(f"[GitHub API] Rate limit - Remaining: {rate.core.remaining}/{rate.core.limit}")
                    
                    if rate.core.remaining < 100:
                        logger.warning(f"[GitHub API] Low on API calls! Only {rate.core.remaining} remaining")
                    
                    if rate.core.remaining < 10:
                        await update.message.reply_text(
                            f"⏳ מגבלת API נמוכה מדי!\n"
                            f"נותרו רק {rate.core.remaining} בקשות\n"
                            f"נסה שוב מאוחר יותר"
                        )
                        return ConversationHandler.END
                    
                    # הוסף delay בין בקשות
                    await self.apply_rate_limit_delay(user_id)
                    
                    logger.info(f"[GitHub API] Getting repo: {repo_name}")
                    repo = g.get_repo(repo_name)
                    
                    # בניית נתיב הקובץ
                    folder = context.user_data.get('target_folder') or session.get('selected_folder')
                    if folder and folder.strip() and folder != 'root':
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
                            content=content,  # PyGithub יקודד אוטומטית
                            sha=existing.sha
                        )
                        action = "עודכן"
                        logger.info(f"✅ קובץ עודכן בהצלחה")
                    except:
                        result = repo.create_file(
                            path=file_path,
                            message=f"Upload {filename} via Telegram bot",
                            content=content  # PyGithub יקודד אוטומטית
                        )
                        action = "הועלה"
                        logger.info(f"✅ קובץ נוצר בהצלחה")
                    
                    raw_url = f"https://raw.githubusercontent.com/{repo_name}/main/{file_path}"
                    
                    await update.message.reply_text(
                        f"✅ הקובץ {action} בהצלחה לגיטהאב!\n\n"
                        f"📁 ריפו: `{repo_name}`\n"
                        f"📂 מיקום: `{file_path}`\n"
                        f"🔗 קישור ישיר:\n{raw_url}\n\n"
                        f"שלח /github כדי לחזור לתפריט.",
                        parse_mode='Markdown'
                    )
                    
                    # נקה את הסטטוס
                    context.user_data['waiting_for_github_upload'] = False
                    context.user_data['upload_mode'] = None
                    
                except Exception as e:
                    logger.error(f"❌ שגיאה בהעלאה: {str(e)}", exc_info=True)
                    
                    error_msg = str(e)
                    
                    # בדוק אם זו שגיאת rate limit
                    if "rate limit" in error_msg.lower() or "403" in error_msg:
                        error_msg = (
                            "⏳ חריגה ממגבלת GitHub API\n"
                            "נסה שוב בעוד כמה דקות\n\n"
                            "💡 טיפ: המתן מספר דקות לפני ניסיון נוסף"
                        )
                    else:
                        error_msg = f"❌ שגיאה בהעלאה:\n{error_msg}\n\nפרטים נוספים נשמרו בלוג."
                    
                    await update.message.reply_text(error_msg)
            else:
                await update.message.reply_text("⚠️ שלח קובץ להעלאה")
            
            return ConversationHandler.END
        else:
            # אם לא במצב העלאה לגיטהאב, תן למטפל הרגיל לטפל בזה
            return ConversationHandler.END
    
    async def handle_text_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle text input for various states"""
        user_id = update.message.from_user.id
        session = self.get_user_session(user_id)
        text = update.message.text
        
        # בדוק אם מחכים ל-URL לניתוח
        if context.user_data.get('waiting_for_repo_url'):
            handled = await self.handle_repo_url_input(update, context)
            if handled:
                return ConversationHandler.END
        
        if text.startswith('ghp_') or text.startswith('github_pat_'):
            session['github_token'] = text
            
            # נקה את repos מ-context.user_data כשמשנים טוקן
            if 'repos' in context.user_data:
                del context.user_data['repos']
            if 'repos_cache_time' in context.user_data:
                del context.user_data['repos_cache_time']
            logger.info(f"[GitHub] Cleared repos cache for user {user_id} after token change")
            
            await update.message.reply_text(
                "✅ טוקן נשמר בהצלחה!\n"
                "כעת תוכל לגשת לריפוזיטוריז הפרטיים שלך."
            )
            return ConversationHandler.END
        
        elif '/' in text:
            session['selected_repo'] = text
            
            # הצג את התפריט המלא אחרי הגדרת הריפו
            await self.github_menu_command(update, context)
            return ConversationHandler.END
        
        else:
            # טיפול בהגדרת תיקייה
            if text.strip() in ['/', '']:
                session['selected_folder'] = None
                await update.message.reply_text(
                    "✅ תיקייה הוגדרה: `root` (ראשי)\n\n⏳ חוזר לתפריט...",
                    parse_mode='Markdown'
                )
            else:
                # הסר / מיותרים
                folder = text.strip().strip('/')
                session['selected_folder'] = folder
                await update.message.reply_text(
                    f"✅ תיקייה הוגדרה: `{folder}`\n\n⏳ חוזר לתפריט...",
                    parse_mode='Markdown'
                )
            
            # המתן שנייה ואז הצג את התפריט
            await asyncio.sleep(1.5)
            await self.github_menu_command(update, context)
            return ConversationHandler.END

    async def show_analyze_repo_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """מציג תפריט לניתוח ריפו"""
        query = update.callback_query
        user_id = query.from_user.id
        session = self.get_user_session(user_id)
        
        # בדוק אם יש ריפו נבחר
        if session.get('selected_repo'):
            # אם יש ריפו נבחר, הצע לנתח אותו או לבחור אחר
            keyboard = [
                [InlineKeyboardButton(f"📊 נתח את {session['selected_repo']}", callback_data="analyze_current_repo")],
                [InlineKeyboardButton("🔍 נתח ריפו אחר", callback_data="analyze_other_repo")],
                [InlineKeyboardButton("🔙 חזור לתפריט", callback_data="github_menu")]
            ]
            
            await query.edit_message_text(
                "🔍 *ניתוח ריפוזיטורי*\n\n"
                "בחר אפשרות:",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
        else:
            # אם אין ריפו נבחר, בקש URL
            await self.request_repo_url(update, context)
    
    async def request_repo_url(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """מבקש URL של ריפו לניתוח"""
        query = update.callback_query if update.callback_query else None
        
        keyboard = [
            [InlineKeyboardButton("❌ ביטול", callback_data="github_menu")]
        ]
        
        message_text = (
            "🔍 *ניתוח ריפוזיטורי*\n\n"
            "שלח URL של ריפו ציבורי ב-GitHub:\n"
            "לדוגמה: `https://github.com/owner/repo`\n\n"
            "💡 הריפו חייב להיות ציבורי או שיש לך גישה אליו עם הטוקן"
        )
        
        if query:
            await query.edit_message_text(
                message_text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(
                message_text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
        
        # סמן שאנחנו מחכים ל-URL
        context.user_data['waiting_for_repo_url'] = True
    
    async def analyze_repository(self, update: Update, context: ContextTypes.DEFAULT_TYPE, repo_url: str):
        """מנתח ריפוזיטורי ומציג תוצאות"""
        query = update.callback_query if update.callback_query else None
        user_id = update.effective_user.id
        session = self.get_user_session(user_id)
        
        # הצג הודעת המתנה
        status_message = await self._send_or_edit_message(
            update, 
            "🔍 מנתח את הריפו...\nזה עשוי לקחת מספר שניות..."
        )
        
        try:
            # צור מנתח עם הטוקן
            analyzer = RepoAnalyzer(github_token=session.get('github_token'))
            
            # נתח את הריפו
            analysis = await analyzer.fetch_and_analyze_repo(repo_url)
            
            # שמור את הניתוח ב-session
            session['last_analysis'] = analysis
            session['last_analyzed_repo'] = repo_url
            
            # צור סיכום
            summary = self._create_analysis_summary(analysis)
            
            # צור כפתורים
            keyboard = [
                [InlineKeyboardButton("🎯 הצג הצעות לשיפור", callback_data="show_suggestions")],
                [InlineKeyboardButton("📋 פרטים מלאים", callback_data="show_full_analysis")],
                [InlineKeyboardButton("📥 הורד דוח JSON", callback_data="download_analysis_json")],
                [InlineKeyboardButton("🔍 נתח ריפו אחר", callback_data="analyze_other_repo")],
                [InlineKeyboardButton("🔙 חזור לתפריט", callback_data="github_menu")]
            ]
            
            # עדכן את ההודעה עם התוצאות
            await status_message.edit_text(
                summary,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
            
        except Exception as e:
            logger.error(f"Error analyzing repository: {e}")
            error_message = f"❌ שגיאה בניתוח הריפו:\n{str(e)}"
            
            keyboard = [
                [InlineKeyboardButton("🔍 נסה ריפו אחר", callback_data="analyze_other_repo")],
                [InlineKeyboardButton("🔙 חזור לתפריט", callback_data="github_menu")]
            ]
            
            await status_message.edit_text(
                error_message,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
    
    def _create_analysis_summary(self, analysis: Dict[str, Any]) -> str:
        """יוצר סיכום של הניתוח"""
        summary = f"📊 *ניתוח הריפו {analysis['repo_name']}*\n\n"
        
        # סטטוס קבצים בסיסיים
        summary += "*קבצים בסיסיים:*\n"
        summary += "✅ README\n" if analysis['has_readme'] else "❌ חסר README\n"
        summary += "✅ LICENSE\n" if analysis['has_license'] else "❌ חסר LICENSE\n"
        summary += "✅ .gitignore\n" if analysis['has_gitignore'] else "❌ חסר .gitignore\n"
        
        # מידע על הפרויקט
        summary += f"\n*מידע כללי:*\n"
        if analysis.get('language'):
            summary += f"🔤 שפה עיקרית: {analysis['language']}\n"
        summary += f"📁 {analysis['file_count']} קבצי קוד\n"
        
        # קבצים לפי סוג
        if analysis['files_by_type']:
            top_types = sorted(analysis['files_by_type'].items(), key=lambda x: x[1], reverse=True)[:3]
            for ext, count in top_types:
                summary += f"   • {count} קבצי {ext}\n"
        
        # תלויות
        if analysis['dependencies']:
            summary += f"📦 {len(analysis['dependencies'])} תלויות\n"
        
        # בעיות פוטנציאליות
        if analysis['large_files']:
            summary += f"⚠️ {len(analysis['large_files'])} קבצים גדולים\n"
        if analysis['long_functions']:
            summary += f"⚠️ {len(analysis['long_functions'])} פונקציות ארוכות\n"
        
        # ציון איכות
        quality_score = analysis.get('quality_score', 0)
        if quality_score >= 80:
            emoji = "🌟"
            text = "מצוין"
        elif quality_score >= 60:
            emoji = "✨"
            text = "טוב"
        elif quality_score >= 40:
            emoji = "⭐"
            text = "בינוני"
        else:
            emoji = "💫"
            text = "דורש שיפור"
        
        summary += f"\n*ציון איכות: {emoji} {quality_score}/100 ({text})*"
        
        return summary
    
    async def show_improvement_suggestions(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """מציג הצעות לשיפור"""
        query = update.callback_query
        await query.answer()
        
        user_id = query.from_user.id
        session = self.get_user_session(user_id)
        
        if not session.get('last_analysis'):
            await query.edit_message_text(
                "❌ לא נמצא ניתוח. נתח ריפו קודם.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔍 נתח ריפו", callback_data="analyze_repo")],
                    [InlineKeyboardButton("🔙 חזור לתפריט", callback_data="github_menu")]
                ])
            )
            return
        
        # צור הצעות לשיפור
        analyzer = RepoAnalyzer()
        suggestions = analyzer.generate_improvement_suggestions(session['last_analysis'])
        
        if not suggestions:
            await query.edit_message_text(
                "🎉 מעולה! לא נמצאו הצעות לשיפור משמעותיות.\n"
                "הפרויקט נראה מצוין!",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 חזור לסיכום", callback_data="back_to_analysis")],
                    [InlineKeyboardButton("🏠 תפריט ראשי", callback_data="github_menu")]
                ])
            )
            return
        
        # שמור הצעות ב-session
        session['suggestions'] = suggestions
        
        # צור כפתורים להצעות (מקסימום 8 הצעות)
        keyboard = []
        for i, suggestion in enumerate(suggestions[:8]):
            impact_emoji = "🔴" if suggestion['impact'] == 'high' else "🟡" if suggestion['impact'] == 'medium' else "🟢"
            button_text = f"{impact_emoji} {suggestion['title']}"
            keyboard.append([InlineKeyboardButton(button_text, callback_data=f"suggestion_{i}")])
        
        keyboard.append([InlineKeyboardButton("🔙 חזור לסיכום", callback_data="back_to_analysis")])
        
        message = f"💡 *הצעות לשיפור לריפו {session['last_analysis']['repo_name']}*\n\n"
        message += f"נמצאו {len(suggestions)} הצעות לשיפור.\n"
        message += "בחר הצעה לפרטים נוספים:\n\n"
        message += "🔴 = השפעה גבוהה | 🟡 = בינונית | 🟢 = נמוכה"
        
        await query.edit_message_text(
            message,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
    
    async def show_suggestion_details(self, update: Update, context: ContextTypes.DEFAULT_TYPE, suggestion_index: int):
        """מציג פרטי הצעה ספציפית"""
        query = update.callback_query
        await query.answer()
        
        user_id = query.from_user.id
        session = self.get_user_session(user_id)
        
        suggestions = session.get('suggestions', [])
        if suggestion_index >= len(suggestions):
            await query.answer("❌ הצעה לא נמצאה", show_alert=True)
            return
        
        suggestion = suggestions[suggestion_index]
        
        # מיפוי השפעה ומאמץ לעברית
        impact_map = {'high': 'גבוהה', 'medium': 'בינונית', 'low': 'נמוכה'}
        effort_map = {'high': 'גבוה', 'medium': 'בינוני', 'low': 'נמוך'}
        
        message = f"*{suggestion['title']}*\n\n"
        message += f"❓ *למה:* {suggestion['why']}\n\n"
        message += f"💡 *איך:* {suggestion['how']}\n\n"
        message += f"📊 *השפעה:* {impact_map.get(suggestion['impact'], suggestion['impact'])}\n"
        message += f"⚡ *מאמץ:* {effort_map.get(suggestion['effort'], suggestion['effort'])}\n"
        
        keyboard = []
        
        # הוסף כפתור למידע נוסף בהתאם לקטגוריה
        if suggestion['id'] == 'add_license':
            keyboard.append([InlineKeyboardButton("📚 מידע על רישיונות", url="https://choosealicense.com/")])
        elif suggestion['id'] == 'add_gitignore':
            keyboard.append([InlineKeyboardButton("📚 יצירת .gitignore", url="https://gitignore.io/")])
        elif suggestion['id'] == 'add_ci_cd':
            keyboard.append([InlineKeyboardButton("📚 GitHub Actions", url="https://docs.github.com/en/actions")])
        
        keyboard.append([InlineKeyboardButton("🔙 חזור להצעות", callback_data="show_suggestions")])
        
        await query.edit_message_text(
            message,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
    
    async def show_full_analysis(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """מציג ניתוח מלא"""
        query = update.callback_query
        await query.answer()
        
        user_id = query.from_user.id
        session = self.get_user_session(user_id)
        
        analysis = session.get('last_analysis')
        if not analysis:
            await query.answer("❌ לא נמצא ניתוח", show_alert=True)
            return
        
        # צור דוח מפורט
        report = f"📊 *דוח מלא - {analysis['repo_name']}*\n\n"
        
        # מידע בסיסי
        report += "*📌 מידע כללי:*\n"
        report += f"• URL: {analysis['repo_url']}\n"
        if analysis.get('description'):
            report += f"• תיאור: {analysis['description']}\n"
        report += f"• שפה: {analysis.get('language', 'לא זוהתה')}\n"
        report += f"• כוכבים: ⭐ {analysis.get('stars', 0)}\n"
        report += f"• Forks: 🍴 {analysis.get('forks', 0)}\n"
        
        # קבצים
        report += f"\n*📁 קבצים:*\n"
        report += f"• סה״כ קבצי קוד: {analysis['file_count']}\n"
        if analysis['files_by_type']:
            report += "• לפי סוג:\n"
            for ext, count in sorted(analysis['files_by_type'].items(), key=lambda x: x[1], reverse=True):
                report += f"  - {ext}: {count}\n"
        
        # בעיות
        if analysis['large_files'] or analysis['long_functions']:
            report += f"\n*⚠️ בעיות פוטנציאליות:*\n"
            if analysis['large_files']:
                report += f"• {len(analysis['large_files'])} קבצים גדולים (500+ שורות)\n"
            if analysis['long_functions']:
                report += f"• {len(analysis['long_functions'])} פונקציות ארוכות (50+ שורות)\n"
        
        # תלויות
        if analysis['dependencies']:
            report += f"\n*📦 תלויות ({len(analysis['dependencies'])}):*\n"
            # הצג רק 10 הראשונות
            for dep in analysis['dependencies'][:10]:
                report += f"• {dep['name']} ({dep['type']})\n"
            if len(analysis['dependencies']) > 10:
                report += f"• ... ועוד {len(analysis['dependencies']) - 10}\n"
        
        keyboard = [
            [InlineKeyboardButton("🔙 חזור לסיכום", callback_data="back_to_analysis")],
            [InlineKeyboardButton("🏠 תפריט ראשי", callback_data="github_menu")]
        ]
        
        # חלק את ההודעה אם היא ארוכה מדי
        if len(report) > 4000:
            report = report[:3900] + "\n\n... (קוצר לצורך תצוגה)"
        
        await query.edit_message_text(
            report,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
    
    async def download_analysis_json(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """שולח קובץ JSON עם הניתוח המלא"""
        query = update.callback_query
        await query.answer()
        
        user_id = query.from_user.id
        session = self.get_user_session(user_id)
        
        analysis = session.get('last_analysis')
        if not analysis:
            await query.answer("❌ לא נמצא ניתוח", show_alert=True)
            return
        
        # הוסף גם את ההצעות לדוח
        analyzer = RepoAnalyzer()
        suggestions = analyzer.generate_improvement_suggestions(analysis)
        
        full_report = {
            'analysis': analysis,
            'suggestions': suggestions,
            'generated_at': datetime.now().isoformat()
        }
        
        # צור קובץ JSON
        json_content = json.dumps(full_report, ensure_ascii=False, indent=2)
        
        # שלח כקובץ
        import io
        file = io.BytesIO(json_content.encode('utf-8'))
        file.name = f"repo_analysis_{analysis['repo_name']}.json"
        
        await query.message.reply_document(
            document=file,
            filename=file.name,
            caption=f"📊 דוח ניתוח מלא עבור {analysis['repo_name']}"
        )
        
        # חזור לתפריט
        await self.show_analyze_results_menu(update, context)
    
    async def show_analyze_results_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """מציג מחדש את תפריט התוצאות"""
        user_id = update.effective_user.id
        session = self.get_user_session(user_id)
        
        analysis = session.get('last_analysis')
        if not analysis:
            return
        
        summary = self._create_analysis_summary(analysis)
        
        keyboard = [
            [InlineKeyboardButton("🎯 הצג הצעות לשיפור", callback_data="show_suggestions")],
            [InlineKeyboardButton("📋 פרטים מלאים", callback_data="show_full_analysis")],
            [InlineKeyboardButton("📥 הורד דוח JSON", callback_data="download_analysis_json")],
            [InlineKeyboardButton("🔍 נתח ריפו אחר", callback_data="analyze_other_repo")],
            [InlineKeyboardButton("🔙 חזור לתפריט", callback_data="github_menu")]
        ]
        
        if update.callback_query:
            await update.callback_query.edit_message_text(
                summary,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(
                summary,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
    
    async def _send_or_edit_message(self, update: Update, text: str, **kwargs):
        """שולח או עורך הודעה בהתאם לסוג ה-update"""
        if update.callback_query:
            return await update.callback_query.edit_message_text(text, **kwargs)
        else:
            return await update.message.reply_text(text, **kwargs)
    
    async def handle_repo_url_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """מטפל בקלט של URL לניתוח"""
        if not context.user_data.get('waiting_for_repo_url'):
            return False
        
        text = update.message.text
        context.user_data['waiting_for_repo_url'] = False
        
        # בדוק אם זה URL של GitHub
        if 'github.com' not in text:
            await update.message.reply_text(
                "❌ נא לשלוח URL תקין של GitHub\n"
                "לדוגמה: https://github.com/owner/repo",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔍 נסה שוב", callback_data="analyze_other_repo")],
                    [InlineKeyboardButton("🔙 חזור לתפריט", callback_data="github_menu")]
                ])
            )
            return True
        
        # נתח את הריפו
        await self.analyze_repository(update, context, text)
        return True
