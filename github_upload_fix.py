# ============================================
# תיקון העלאה ישירה מהמכשיר לגיטהאב
# ============================================

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand, BotCommandScopeChat
from telegram.ext import ContextTypes, Application
from github import Github, GithubException
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

# ============================================
# פונקציה מתוקנת לבקשת העלאת קובץ
# ============================================

async def github_upload_new_file(update, context):
    """בקשה להעלאת קובץ חדש לגיטהאב"""
    query = update.callback_query
    await query.answer()
    
    repo_name = context.user_data.get('selected_repo', 'amirbiron/CodeBot')
    folder = context.user_data.get('github_folder', 'root')
    
    # סמן במפורש שאנחנו במצב העלאה לגיטהאב
    context.user_data['waiting_for'] = 'github_upload'
    context.user_data['upload_mode'] = 'github'
    context.user_data['target_repo'] = repo_name
    context.user_data['target_folder'] = folder
    
    # הודעה עם הוראות ברורות
    message = (
        f"📤 **העלאת קובץ לגיטהאב**\n\n"
        f"🔗 ריפו: `{repo_name}`\n"
        f"📂 תיקייה: `{folder}`\n\n"
        f"**כדי להעלות קובץ מהמכשיר:**\n"
        f"1️⃣ לחץ על 📎 (הסיכה) בשורת ההודעה\n"
        f"2️⃣ בחר 'Document' או 'File'\n"
        f"3️⃣ בחר את הקובץ מהמכשיר\n"
        f"4️⃣ שלח אותו\n\n"
        f"⏳ ממתין לקובץ..."
    )
    
    keyboard = [
        [InlineKeyboardButton("📱 בחר מקבצים שמורים", callback_data="select_from_saved")],
        [InlineKeyboardButton("❌ ביטול", callback_data="github_menu")]
    ]
    
    await query.edit_message_text(
        message,
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ============================================
# פונקציה מתוקנת לטיפול בקובץ שהתקבל
# ============================================

async def handle_document_fixed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """טיפול בקובץ שהתקבל"""
    
    # דיבאג
    logger.info(f"DEBUG: upload_mode = {context.user_data.get('upload_mode')}")
    logger.info(f"DEBUG: Document received: {update.message.document.file_name}")
    
    # בדוק אם אנחנו במצב העלאה לגיטהאב
    if context.user_data.get('upload_mode') == 'github':
        # הצג הודעת עיבוד
        processing_msg = await update.message.reply_text("⏳ מעבד את הקובץ...")
        
        try:
            # העלה לגיטהאב
            await upload_to_github_fixed(update, context, processing_msg)
        except Exception as e:
            await processing_msg.edit_text(f"❌ שגיאה: {str(e)}")
        finally:
            # נקה את מצב ההעלאה
            context.user_data['upload_mode'] = None
    else:
        # העבר לטיפול הרגיל
        return None  # תן ל-handler הבא לטפל

# ============================================
# פונקציה מתוקנת להעלאה לגיטהאב
# ============================================

async def upload_to_github_fixed(update, context, status_message):
    """העלאה מתוקנת לגיטהאב"""
    
    # קבל את פרטי הקובץ
    document = update.message.document
    if not document:
        await status_message.edit_text("❌ לא התקבל קובץ תקין")
        return
    
    file_name = document.file_name
    await status_message.edit_text(f"📥 מוריד את {file_name}...")
    
    # הורד את הקובץ
    file = await document.get_file()
    file_bytes = await file.download_as_bytearray()
    
    # קבל פרטי יעד
    repo_name = context.user_data.get('target_repo', 'amirbiron/CodeBot')
    folder = context.user_data.get('target_folder', '')
    
    # בנה נתיב מלא
    if folder and folder != 'root' and folder != '':
        file_path = f"{folder}/{file_name}"
    else:
        file_path = file_name
    
    # דיבאג
    logger.info(f"DEBUG: Repo = {repo_name}, Path = {file_path}")
    
    await status_message.edit_text(f"🔄 מתחבר לגיטהאב...")
    
    # קבל טוקן
    github_token = context.user_data.get('github_token')
    if not github_token:
        # נסה מהסשן של GitHub handler
        if hasattr(context.bot_data, 'github_handler'):
            user_session = context.bot_data.github_handler.get_user_session(update.effective_user.id)
            github_token = user_session.get('github_token')
    
    if not github_token:
        await status_message.edit_text(
            "❌ אין חיבור לגיטהאב.\n"
            "השתמש ב-/github להתחברות או הגדר טוקן."
        )
        return
    
    logger.info(f"DEBUG: Token exists = {bool(github_token)}")
    
    try:
        # התחבר
        g = Github(github_token)
        user = g.get_user()
        
        await status_message.edit_text(f"📦 ניגש לריפו {repo_name}...")
        
        # קבל את הריפו
        repo = g.get_repo(repo_name)
        
        await status_message.edit_text(f"📤 מעלה את {file_name}...")
        
        # נסה להעלות/לעדכן
        try:
            # בדוק אם הקובץ כבר קיים
            existing_file = repo.get_contents(file_path)
            
            # עדכן קובץ קיים
            result = repo.update_file(
                path=file_path,
                message=f"Update {file_name} via Telegram bot",
                content=file_bytes,
                sha=existing_file.sha
            )
            action = "עודכן"
            
        except:
            # צור קובץ חדש
            result = repo.create_file(
                path=file_path,
                message=f"Upload {file_name} via Telegram bot",
                content=file_bytes
            )
            action = "הועלה"
        
        # הצלחה! צור לינק
        commit_sha = result['commit'].sha[:7]
        file_url = f"https://github.com/{repo_name}/blob/main/{file_path}"
        
        success_message = (
            f"✅ **הקובץ {action} בהצלחה!**\n\n"
            f"📄 קובץ: `{file_name}`\n"
            f"📁 נתיב: `{file_path}`\n"
            f"🔗 ריפו: `{repo_name}`\n"
            f"🔖 Commit: `{commit_sha}`\n"
        )
        
        keyboard = [
            [InlineKeyboardButton("👁 צפה בקובץ", url=file_url)],
            [InlineKeyboardButton("📤 העלה עוד", callback_data="github_upload_new")],
            [InlineKeyboardButton("🔙 חזרה לתפריט", callback_data="github_menu")]
        ]
        
        await status_message.edit_text(
            success_message,
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
    except GithubException as e:
        error_msg = f"❌ שגיאת GitHub:\n`{str(e)}`\n\n"
        
        if "404" in str(e):
            error_msg += "• הריפו לא נמצא או אין הרשאות\n"
        elif "401" in str(e):
            error_msg += "• בעיית אימות - בדוק את הטוקן\n"
        elif "403" in str(e):
            error_msg += "• אין הרשאות כתיבה לריפו\n"
        
        await status_message.edit_text(error_msg, parse_mode='Markdown')
        
    except Exception as e:
        await status_message.edit_text(
            f"❌ שגיאה כללית:\n`{str(e)}`",
            parse_mode='Markdown'
        )

# ============================================
# הגדרת פקודות מינימליות - רק stats למנהל
# ============================================

async def setup_minimal_commands(application: Application) -> None:
    """מחיקת כל הפקודות והשארת רק stats למנהל"""
    
    # 1. מחק את כל הפקודות לכל המשתמשים
    await application.bot.delete_my_commands()
    print("✅ All public commands removed")
    
    # 2. הגדר רק stats למנהל (אמיר בירון)
    AMIR_ID = 6865105071  # ה-ID של אמיר בירון
    
    try:
        # הגדר את פקודת stats רק לאמיר
        await application.bot.set_my_commands(
            commands=[
                BotCommand("stats", "📊 סטטיסטיקות שימוש")
            ],
            scope=BotCommandScopeChat(chat_id=AMIR_ID)
        )
        print(f"✅ Stats command set for Amir (ID: {AMIR_ID})")
        
    except Exception as e:
        print(f"⚠️ Error setting admin commands: {e}")

# ============================================
# פונקציית stats מעודכנת עם בדיקת הרשאות
# ============================================

async def stats_command_secured(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """הצג סטטיסטיקות - רק לאמיר בירון"""
    
    user_id = update.effective_user.id
    username = update.effective_user.username
    
    # רק אמיר יכול להשתמש
    AMIR_ID = 6865105071
    
    if user_id != AMIR_ID:
        await update.message.reply_text(
            "⛔ הפקודה הזו זמינה רק למנהל המערכת."
        )
        logger.warning(f"❌ Unauthorized stats attempt by @{username} (ID: {user_id})")
        return
    
    # כאן תצטרך להעתיק את הקוד הקיים של stats
    logger.info(f"✅ Stats shown to Amir")
    # ... המשך הקוד של הסטטיסטיקות

# ============================================
# פונקציה לבדיקת הפקודות (אופציונלי)
# ============================================

async def check_commands(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """בדיקת הפקודות הזמינות (רק לאמיר)"""
    
    if update.effective_user.id != 6865105071:
        return
    
    # בדוק פקודות ציבוריות
    public_cmds = await context.bot.get_my_commands()
    
    # בדוק פקודות אישיות
    personal_cmds = await context.bot.get_my_commands(
        scope=BotCommandScopeChat(chat_id=6865105071)
    )
    
    message = "📋 **סטטוס פקודות:**\n\n"
    message += f"**ציבוריות:** {len(public_cmds)} פקודות\n"
    
    if public_cmds:
        for cmd in public_cmds:
            message += f"  • /{cmd.command}\n"
    
    message += f"\n**אישיות לך:** {len(personal_cmds)} פקודות\n"
    
    if personal_cmds:
        for cmd in personal_cmds:
            message += f"  • /{cmd.command} - {cmd.description}\n"
    
    await update.message.reply_text(message, parse_mode='Markdown')