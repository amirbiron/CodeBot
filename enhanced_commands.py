"""
פקודות משופרות עם אוטו-השלמה ותצוגה מקדימה
Enhanced Commands with Autocomplete and Preview
"""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler, CallbackQueryHandler
from telegram.constants import ParseMode
from database import db
from autocomplete_manager import autocomplete
from code_preview import code_preview
from html import escape as html_escape

logger = logging.getLogger(__name__)

async def autocomplete_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """פקודת אוטו-השלמה לשמות קבצים"""
    user_id = update.effective_user.id
    
    if not context.args:
        await update.message.reply_text(
            "🔍 <b>אוטו-השלמה לשמות קבצים</b>\n\n"
            "שימוש: <code>/autocomplete &lt;תחילת_שם&gt;</code>\n\n"
            "דוגמה: <code>/autocomplete scr</code>\n"
            "יציע: script.py, scraper.js, screen.css",
            parse_mode=ParseMode.HTML
        )
        return
    
    partial_name = " ".join(context.args)
    suggestions = autocomplete.suggest_filenames(user_id, partial_name, limit=8)
    
    if not suggestions:
        await update.message.reply_text(
            f"🔍 לא נמצאו קבצים המתחילים ב-'{html_escape(partial_name)}'\n\n"
            "💡 נסה עם פחות תווים או שם אחר",
            parse_mode=ParseMode.HTML
        )
        return
    
    # יצירת כפתורים לכל הצעה
    keyboard = []
    for suggestion in suggestions:
        filename = suggestion['filename']
        score = suggestion['score']
        
        keyboard.append([
            InlineKeyboardButton(
                f"📄 {filename} ({score}%)",
                callback_data=f"show_file:{filename}"
            )
        ])
    
    # כפתור לביטול
    keyboard.append([
        InlineKeyboardButton("❌ ביטול", callback_data="cancel_autocomplete")
    ])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"🔍 <b>הצעות לשם '{html_escape(partial_name)}':</b>\n\n"
        "לחץ על קובץ לתצוגה מקדימה:",
        parse_mode=ParseMode.HTML,
        reply_markup=reply_markup
    )

async def preview_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """פקודת תצוגה מקדימה של קוד"""
    user_id = update.effective_user.id
    
    if not context.args:
        # הצגת רשימת קבצים אחרונים לבחירה
        recent_files = autocomplete.get_recent_files(user_id, limit=5)
        
        if not recent_files:
            await update.message.reply_text(
                "📂 אין קבצים זמינים לתצוגה מקדימה\n\n"
                "💡 שימוש: <code>/preview &lt;שם_קובץ&gt;</code>",
                parse_mode=ParseMode.HTML
            )
            return
        
        # יצירת כפתורים לקבצים אחרונים
        keyboard = []
        for filename in recent_files:
            keyboard.append([
                InlineKeyboardButton(
                    f"👁️ {filename}",
                    callback_data=f"preview_file:{filename}"
                )
            ])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "👁️ <b>תצוגה מקדימה - קבצים אחרונים:</b>\n\n"
            "בחר קובץ לתצוגה מקדימה:",
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup
        )
        return
    
    file_name = " ".join(context.args)
    await _show_file_preview(update, user_id, file_name)

async def quick_info_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """פקודת מידע מהיר על קובץ"""
    user_id = update.effective_user.id
    
    if not context.args:
        await update.message.reply_text(
            "ℹ️ <b>מידע מהיר על קובץ</b>\n\n"
            "שימוש: <code>/info &lt;שם_קובץ&gt;</code>\n\n"
            "דוגמה: <code>/info script.py</code>",
            parse_mode=ParseMode.HTML
        )
        return
    
    file_name = " ".join(context.args)
    file_data = db.get_latest_version(user_id, file_name)
    
    if not file_data:
        # הצעת אוטו-השלמה אם הקובץ לא נמצא
        suggestions = autocomplete.suggest_filenames(user_id, file_name, limit=3)
        
        if suggestions:
            suggestion_text = "\n".join([f"• {s['display']}" for s in suggestions])
            await update.message.reply_text(
                f"❌ קובץ '{html_escape(file_name)}' לא נמצא\n\n"
                f"🔍 <b>האם התכוונת ל:</b>\n{suggestion_text}",
                parse_mode=ParseMode.HTML
            )
        else:
            await update.message.reply_text(
                f"❌ קובץ '{html_escape(file_name)}' לא נמצא",
                parse_mode=ParseMode.HTML
            )
        return
    
    # יצירת מידע מהיר
    info_text = code_preview.create_quick_info(file_data)
    
    # כפתורי פעולה
    keyboard = [
        [
            InlineKeyboardButton("👁️ תצוגה מקדימה", callback_data=f"preview_file:{file_name}"),
            InlineKeyboardButton("📖 הצג מלא", callback_data=f"show_file:{file_name}")
        ],
        [
            InlineKeyboardButton("✏️ ערוך", callback_data=f"edit_file:{file_name}"),
            InlineKeyboardButton("📥 הורד", callback_data=f"download_file:{file_name}")
        ]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        info_text,
        parse_mode=ParseMode.HTML,
        reply_markup=reply_markup
    )

async def _show_file_preview(update, user_id: int, file_name: str):
    """הצגת תצוגה מקדימה של קובץ"""
    try:
        file_data = db.get_latest_version(user_id, file_name)
        
        if not file_data:
            await update.message.reply_text(
                f"❌ קובץ '{html_escape(file_name)}' לא נמצא",
                parse_mode=ParseMode.HTML
            )
            return
        
        # יצירת תצוגה מקדימה
        preview_info = code_preview.create_preview(
            file_data['code'],
            file_name,
            file_data['programming_language']
        )
        
        # פורמט ההודעה
        message = code_preview.format_preview_message(file_name, preview_info)
        
        # כפתורי פעולה
        keyboard = [
            [
                InlineKeyboardButton("📖 הצג קובץ מלא", callback_data=f"show_file:{file_name}"),
                InlineKeyboardButton("✏️ ערוך", callback_data=f"edit_file:{file_name}")
            ],
            [
                InlineKeyboardButton("📥 הורד", callback_data=f"download_file:{file_name}"),
                InlineKeyboardButton("ℹ️ מידע מפורט", callback_data=f"info_file:{file_name}")
            ]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            message,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup
        )
        
    except Exception as e:
        logger.error(f"שגיאה בהצגת תצוגה מקדימה: {e}")
        await update.message.reply_text("❌ שגיאה בטעינת תצוגה מקדימה")

async def handle_enhanced_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """טיפול בcallbacks של הפיצ'רים המשופרים"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    data = query.data
    
    try:
        if data.startswith("preview_file:"):
            file_name = data[13:]  # הסרת "preview_file:"
            await _show_file_preview(query, user_id, file_name)
            
        elif data.startswith("show_file:"):
            file_name = data[10:]  # הסרת "show_file:"
            # קריאה לפונקציה קיימת להצגת קובץ מלא
            from bot_handlers import AdvancedBotHandlers
            # כאן נצטרך לקרוא לפונקציה המתאימה
            
        elif data.startswith("info_file:"):
            file_name = data[10:]  # הסרת "info_file:"
            file_data = db.get_latest_version(user_id, file_name)
            
            if file_data:
                info_text = code_preview.create_quick_info(file_data)
                await query.edit_message_text(
                    info_text,
                    parse_mode=ParseMode.HTML
                )
            else:
                await query.edit_message_text("❌ קובץ לא נמצא")
                
        elif data == "cancel_autocomplete":
            await query.edit_message_text("❌ פעולה בוטלה")
            
    except Exception as e:
        logger.error(f"שגיאה בטיפול ב-callback משופר: {e}")
        await query.edit_message_text("❌ שגיאה בעיבוד הבקשה")

def setup_enhanced_handlers(application):
    """הוספת handlers לפיצ'רים המשופרים"""
    application.add_handler(CommandHandler("autocomplete", autocomplete_command))
    application.add_handler(CommandHandler("preview", preview_command))
    application.add_handler(CommandHandler("info", quick_info_command))
    
    # הוספת callback handler (יש לוודא שזה לא מתנגש עם handlers קיימים)
    application.add_handler(CallbackQueryHandler(
        handle_enhanced_callbacks,
        pattern="^(preview_file:|show_file:|info_file:|cancel_autocomplete)"
    ))
    
    logger.info("Enhanced handlers הוגדרו בהצלחה")