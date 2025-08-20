import logging
import re
import asyncio
from io import BytesIO
from datetime import datetime, timezone
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
import telegram.error
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)
from database import DatabaseManager
from activity_reporter import create_reporter
from utils import get_language_emoji as get_file_emoji
from user_stats import user_stats
from typing import List, Optional
from html import escape as html_escape

def _truncate_middle(text: str, max_len: int) -> str:
    """מקצר מחרוזת באמצע עם אליפסיס אם חורגת מאורך נתון."""
    if max_len <= 0:
        return ''
    if len(text) <= max_len:
        return text
    if max_len <= 1:
        return text[:max_len]
    keep = max_len - 1
    front = keep // 2
    back = keep - front
    return text[:front] + '…' + text[-back:]

def _repo_label_from_tag(tag: str) -> str:
    """מחלץ שם ריפו מתגית בסגנון repo:owner/name"""
    try:
        return tag.split(':', 1)[1] if tag.startswith('repo:') else tag
    except Exception:
        return tag

def _repo_only_from_tag(tag: str) -> str:
    """מחזיר רק את שם ה-repo ללא owner מתוך תגית repo:owner/name"""
    label = _repo_label_from_tag(tag)
    try:
        return label.split('/', 1)[1] if '/' in label else label
    except Exception:
        return label

def _build_repo_button_text(tag: str, count: int) -> str:
    """בונה תווית כפתור קומפקטית לריפו, מציג רק את שם ה-repo בלי owner."""
    MAX_LEN = 64
    label = _repo_only_from_tag(tag)
    label_short = _truncate_middle(label, MAX_LEN)
    return label_short

# הגדרת לוגר
logger = logging.getLogger(__name__)

# הגדרת שלבי השיחה
GET_CODE, GET_FILENAME, EDIT_CODE, EDIT_NAME = range(4)

# קבועי עימוד
FILES_PAGE_SIZE = 10

# כפתורי המקלדת הראשית
MAIN_KEYBOARD = [
    ["➕ הוסף קוד חדש"],
    ["📚 הצג את כל הקבצים שלי", "📂 קבצים גדולים"],
    ["⚡ עיבוד Batch", "🔧 GitHub"],
    ["📥 ייבוא ZIP מריפו", "🗂 לפי ריפו"],
    ["ℹ️ הסבר על הבוט"]
]

reporter = create_reporter(
    mongodb_uri="mongodb+srv://mumin:M43M2TFgLfGvhBwY@muminai.tm6x81b.mongodb.net/?retryWrites=true&w=majority&appName=muminAI",
    service_id="srv-d29d72adbo4c73bcuep0",
    service_name="CodeBot"
)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """טיפול בפקודת /start - מציג את התפריט הראשי"""
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name
    username = update.effective_user.username
    
    # שמור משתמש במסד נתונים (INSERT OR IGNORE)
    from database import db
    db.save_user(user_id, username)
    # רישום פעילות למעקב סטטיסטיקות ב-MongoDB
    user_stats.log_user(user_id, username)
    
    safe_user_name = html_escape(user_name) if user_name else ""
    
    welcome_text = (
        f"🤖 שלום {safe_user_name}! ברוך הבא לבוט שומר הקוד המתקדם!\n\n"
        "🔹 שמור ונהל קטעי קוד בחכמה\n"
        "🔹 עריכה מתקדמת עם גרסאות\n"
        "🔹 חיפוש והצגה חכמה\n"
        "🔹 הורדה וניהול מלא\n"
        "🔹 העלאת קבצים ל-GitHub\n"
        "🔹 ניתוח ריפו\n\n"
        "בחר פעולה מהתפריט למטה 👇\n\n"
        "🔧 לכל תקלה בבוט נא לשלוח הודעה ל-@moominAmir"
    )
    
    keyboard = ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
    await update.message.reply_text(welcome_text, reply_markup=keyboard)
    reporter.report_activity(user_id)
    return ConversationHandler.END

HELP_PAGES = [
    (
        "🤖 <b>ברוכים הבאים לבוט ניהול קוד!</b>\n\n"
        "בוט חכם לניהול, גיבוי וארגון קבצי קוד.\n"
        "עובד מצוין עם GitHub ותומך בכל שפות התכנות.\n\n"
        "➕ <b>הוסף קוד</b> - פשוט שלחו קוד והבוט ישמור\n"
        "📚 <b>הצג קבצים</b> - כל הקבצים שלכם מאורגנים\n"
        "⚡ <b>עיבוד Batch</b> - ניתוח אוטומטי של פרויקטים\n"
        "🔧 <b>GitHub</b> - סנכרון וגיבוי אוטומטי\n\n"
        "דפדפו לעמודים הבאים להסבר מפורט ⬅️"
    ),
    (
        "⚡ <b>עיבוד Batch - הכי חשוב להבין!</b>\n\n"
        "מאפשר לבצע פעולות על <u>עשרות קבצים בבת אחת</u>.\n\n"
        "<b>איך זה עובד?</b>\n"
        "1️⃣ בוחרים קבוצת קבצים (לפי ריפו/ZIP/גדולים/אחר)\n"
        "2️⃣ בוחרים פעולה:\n\n"
        "📊 <b>ניתוח (Analyze)</b> - מה מקבלים?\n"
        "• בדיקת איכות קוד (ציון 0-100)\n"
        "• זיהוי בעיות אבטחה\n"
        "• מציאת קוד כפול\n"
        "• המלצות לשיפור\n"
        "• סטטיסטיקות: שורות, פונקציות, מורכבות\n\n"
        "✅ <b>בדיקת תקינות (Validate)</b> - מה בודק?\n"
        "• שגיאות תחביר\n"
        "• ייבואים חסרים\n"
        "• משתנים לא מוגדרים\n"
        "• בעיות לוגיות\n\n"
        "<b>דוגמה:</b> יש לכם פרויקט React? הפעילו ניתוח על כל הקבצים ותקבלו דוח מלא!"
    ),
    (
        "🔧 <b>אינטגרציית GitHub - מדריך מלא</b>\n\n"
        "<b>התחלה מהירה:</b>\n"
        "1️⃣ לחצו על 🔧 GitHub\n"
        "2️⃣ הגדירו טוקן (מסבירים איך)\n"
        "3️⃣ בחרו ריפו\n"
        "4️⃣ מוכנים!\n\n"
        "<b>מה אפשר לעשות?</b>\n\n"
        "📤 <b>העלאת קבצים</b> - 2 דרכים:\n"
        "• קובץ חדש - שלחו קוד והוא יעלה ישר לריפו\n"
        "• מהשמורים - בחרו קבצים שכבר יש בבוט\n\n"
        "🧰 <b>גיבוי ושחזור</b> - החכם ביותר!\n"
        "• יוצר ZIP של כל הריפו\n"
        "• שומר בבוט עם תאריך\n"
        "• אפשר לשחזר בכל רגע\n"
        "• מושלם לפני שינויים גדולים!\n\n"
        "🔔 <b>התראות חכמות</b>\n"
        "• מקבלים הודעה על כל commit חדש\n"
        "• מעקב אחר pull requests\n"
        "• התראות על issues"
    ),
    (
        "📥 <b>ייבוא ZIP מריפו - למה זה טוב?</b>\n\n"
        "תכונה מיוחדת לייבוא פרויקטים שלמים!\n\n"
        "<b>איך משתמשים?</b>\n"
        "1. הורידו ZIP מגיטהאב (Code → Download ZIP)\n"
        "2. לחצו על 📥 ייבוא ZIP\n"
        "3. שלחו את הקובץ\n\n"
        "<b>מה קורה?</b>\n"
        "• הבוט פורס את כל הקבצים\n"
        "• מתייג אוטומטית עם שם הריפו\n"
        "• שומר מבנה תיקיות\n"
        "• מאפשר עיבוד Batch על כולם!\n\n"
        "🗂 <b>לפי ריפו - ארגון חכם</b>\n"
        "• כל הקבצים מתויגים repo:owner/name\n"
        "• קל למצוא קבצים לפי פרויקט\n"
        "• אפשר לייצא חזרה כ-ZIP\n\n"
        "<b>טיפ:</b> יש לכם כמה פרויקטים? ייבאו אותם כ-ZIP והבוט יארגן הכל!"
    ),
    (
        "📂 <b>קבצים גדולים - טיפול מיוחד</b>\n\n"
        "קבצים מעל 500 שורות מקבלים טיפול VIP:\n\n"
        "• <b>טעינה חכמה</b> - לא טוען הכל לזיכרון\n"
        "• <b>צפייה בחלקים</b> - 100 שורות בכל פעם\n"
        "• <b>חיפוש מהיר</b> - מוצא מה שצריך בלי לטעון הכל\n"
        "• <b>הורדה ישירה</b> - מקבלים כקובץ מיד\n\n"
        "<b>מתי זה שימושי?</b>\n"
        "• קבצי JSON גדולים\n"
        "• לוגים ארוכים\n"
        "• קבצי נתונים\n"
        "• קוד שנוצר אוטומטית"
    ),
    (
        "📚 <b>תפריט הקבצים - מה יש שם?</b>\n\n"
        "לחיצה על 📚 פותחת 4 אפשרויות:\n\n"
        "🗂 <b>לפי ריפו</b> - קבצים מאורגנים לפי פרויקט\n"
        "📦 <b>קבצי ZIP</b> - כל הגיבויים והארכיונים\n"
        "📂 <b>גדולים</b> - קבצים מעל 500 שורות\n"
        "📁 <b>שאר</b> - כל השאר\n\n"
        "<b>לכל קובץ יש תפריט עם:</b>\n"
        "👁️ הצג | ✏️ ערוך | 📝 שנה שם\n"
        "📚 היסטוריה | 📥 הורד | 🗑️ מחק\n\n"
        "<b>טיפ:</b> הקבצים מוצגים 10 בעמוד עם ניווט נוח"
    ),
    (
        "🔍 <b>ניתוח ובדיקת ריפו</b>\n\n"
        "שתי פעולות חזקות בתפריט GitHub:\n\n"
        "🔍 <b>נתח ריפו - מקבלים דוח מלא:</b>\n"
        "• כמה קבצים מכל סוג\n"
        "• סה״כ שורות קוד\n"
        "• גודל הריפו\n"
        "• קבצים בעייתיים\n"
        "• המלצות לשיפור\n\n"
        "✅ <b>בדוק תקינות - בדיקה עמוקה:</b>\n"
        "• סורק את כל הקבצים\n"
        "• מוצא שגיאות תחביר\n"
        "• בודק תלויות\n"
        "• מזהה קבצים שבורים\n"
        "• נותן ציון כללי לריפו\n\n"
        "<b>מתי להשתמש?</b>\n"
        "• לפני מיזוג branch\n"
        "• אחרי שינויים גדולים\n"
        "• בדיקה תקופתית לפרויקט"
    ),
    (
        "💡 <b>טיפים מתקדמים למשתמשי פרו</b>\n\n"
        "🏷️ <b>תגיות חכמות:</b>\n"
        "• הוסיפו #frontend #backend לארגון\n"
        "• תגית repo: נוספת אוטומטית\n"
        "• חיפוש לפי תגיות בעתיד\n\n"
        "🔄 <b>וורקפלואו מומלץ:</b>\n"
        "1. ייבאו פרויקט כ-ZIP\n"
        "2. הפעילו ניתוח Batch\n"
        "3. תקנו בעיות\n"
        "4. העלו חזרה לגיטהאב\n\n"
        "⚠️ <b>מגבלות:</b>\n"
        "• קבצים עד 50MB\n"
        "• 1000 קבצים למשתמש\n"
        "• עיבוד Batch: עד 100 קבצים\n\n"
        "<b>יש שאלות?</b> הבוט די אינטואיטיבי,\n"
        "פשוט נסו את הכפתורים! 🚀"
    ),
]

async def show_help_page(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 1) -> int:
    """מציג עמוד עזרה עם כפתורי ניווט"""
    total_pages = len(HELP_PAGES)
    page = max(1, min(page, total_pages))
    text = HELP_PAGES[page - 1]
    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton("⬅️ הקודם", callback_data=f"help_page:{page-1}"))
    nav.append(InlineKeyboardButton(f"עמוד {page}/{total_pages}", callback_data="noop"))
    if page < total_pages:
        nav.append(InlineKeyboardButton("➡️ הבא", callback_data=f"help_page:{page+1}"))
    keyboard = [nav, [InlineKeyboardButton("🏠 חזרה לתפריט", callback_data="main")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    if hasattr(update, 'callback_query') and update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
    return ConversationHandler.END

async def start_repo_zip_import(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """מצב ייבוא ZIP של ריפו: מבקש לשלוח ZIP ומכין את ה-upload_mode."""
    context.user_data.pop('waiting_for_github_upload', None)
    context.user_data['upload_mode'] = 'zip_import'
    cancel_markup = InlineKeyboardMarkup([[InlineKeyboardButton("❌ ביטול", callback_data="cancel")]])
    await update.message.reply_text(
        "📥 שלח/י עכשיו קובץ ZIP של הריפו (העלאה ראשונית).\n"
        "🔖 אצמיד תגית repo:owner/name (אם קיימת ב-metadata). לא מתבצעת מחיקה.",
        reply_markup=cancel_markup
    )
    reporter.report_activity(update.effective_user.id)
    return ConversationHandler.END

async def show_by_repo_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """מציג תפריט קבוצות לפי תגיות ריפו ומאפשר בחירה."""
    from database import db
    user_id = update.effective_user.id
    files = db.get_user_files(user_id, limit=500)
    # ריכוז תגיות ריפו
    repo_to_count = {}
    for f in files:
        for t in f.get('tags', []) or []:
            if t.startswith('repo:'):
                repo_to_count[t] = repo_to_count.get(t, 0) + 1
    if not repo_to_count:
        await update.message.reply_text("ℹ️ אין קבצים עם תגית ריפו.")
        return ConversationHandler.END
    # בניית מקלדת
    keyboard = []
    for tag, cnt in sorted(repo_to_count.items(), key=lambda x: x[0])[:20]:
        keyboard.append([InlineKeyboardButton(f"{tag} ({cnt})", callback_data=f"by_repo:{tag}")])
    keyboard.append([InlineKeyboardButton("🔙 חזור", callback_data="files")])
    await update.message.reply_text(
        "בחר/י ריפו להצגת קבצים:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ConversationHandler.END

async def show_by_repo_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """גרסת callback להצגת תפריט ריפו (עריכת ההודעה הנוכחית)."""
    from database import db
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    files = db.get_user_files(user_id, limit=500)
    repo_to_count = {}
    for f in files:
        for t in f.get('tags', []) or []:
            if t.startswith('repo:'):
                repo_to_count[t] = repo_to_count.get(t, 0) + 1
    if not repo_to_count:
        await query.edit_message_text("ℹ️ אין קבצים עם תגית ריפו.")
        return ConversationHandler.END
    keyboard = []
    for tag, cnt in sorted(repo_to_count.items(), key=lambda x: x[0])[:20]:
        keyboard.append([InlineKeyboardButton(f"{tag} ({cnt})", callback_data=f"by_repo:{tag}")])
    keyboard.append([InlineKeyboardButton("🔙 חזור", callback_data="files")])
    await query.edit_message_text(
        "בחר/י ריפו להצגת קבצים:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ConversationHandler.END
async def show_all_files(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """מציג את כל הקבצים השמורים עם ממשק אינטראקטיבי מתקדם"""
    user_id = update.effective_user.id
    # רישום פעילות למעקב סטטיסטיקות ב-MongoDB
    user_stats.log_user(user_id, update.effective_user.username)
    from database import db
    # הקשר: חזרה מתצוגת ZIP תחזור ל"📚" ותבטל סינון לפי ריפו
    try:
        context.user_data['zip_back_to'] = 'files'
        context.user_data.pop('github_backup_context_repo', None)
    except Exception:
        pass
    
    try:
        # סנן קבצים השייכים לקטגוריות אחרות:
        # - קבצים גדולים אינם מוחזרים כאן ממילא
        # - קבצי ZIP אינם חלק ממסד הקבצים
        # - קבצים עם תגית repo: יוצגו תחת "לפי ריפו" ולכן יוחרגו כאן
        all_files = db.get_user_files(user_id)
        files = [f for f in all_files if not any((t or '').startswith('repo:') for t in (f.get('tags') or []))]
        
        # מסך בחירה: 4 כפתורים
        keyboard = [
            [InlineKeyboardButton("🗂 לפי ריפו", callback_data="by_repo_menu")],
            [InlineKeyboardButton("📦 קבצי ZIP", callback_data="backup_list")],
            [InlineKeyboardButton("📂 קבצים גדולים", callback_data="show_large_files")],
            [InlineKeyboardButton("📁 שאר הקבצים", callback_data="show_regular_files")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "בחר/י דרך להצגת הקבצים:",
            reply_markup=reply_markup
        )
    except Exception as e:
        logger.error(f"שגיאה בהצגת כל הקבצים: {e}")
        await update.message.reply_text(
            "❌ אירעה שגיאה בעת ניסיון לשלוף את הקבצים שלך. נסה שוב מאוחר יותר.",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )
    
    reporter.report_activity(user_id)
    return ConversationHandler.END

async def show_large_files_direct(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """הצגת קבצים גדולים ישירות מהתפריט הראשי"""
    # נקה דגלים ישנים של GitHub כדי למנוע בלבול בקלט
    context.user_data.pop('waiting_for_delete_file_path', None)
    context.user_data.pop('waiting_for_download_file_path', None)
    # רישום פעילות למעקב סטטיסטיקות ב-MongoDB
    user_stats.log_user(update.effective_user.id, update.effective_user.username)
    from large_files_handler import large_files_handler
    await large_files_handler.show_large_files_menu(update, context)
    return ConversationHandler.END

async def show_github_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """הצגת תפריט GitHub"""
    # שימוש ב-instance הגלובלי במקום ליצור חדש
    if 'github_handler' not in context.bot_data:
        from github_menu_handler import GitHubMenuHandler
        context.bot_data['github_handler'] = GitHubMenuHandler()
    
    # רישום פעילות למעקב סטטיסטיקות ב-MongoDB
    user_stats.log_user(update.effective_user.id, update.effective_user.username)
    
    github_handler = context.bot_data['github_handler']
    await github_handler.github_menu_command(update, context)
    reporter.report_activity(update.effective_user.id)
    return ConversationHandler.END


async def show_all_files_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """גרסת callback של show_all_files - מציגה תפריט בחירה בין סוגי קבצים"""
    query = update.callback_query
    await query.answer()
    
    try:
        # הקשר: חזרה מתצוגת ZIP תחזור ל"📚" ותבטל סינון לפי ריפו
        try:
            context.user_data['zip_back_to'] = 'files'
            context.user_data.pop('github_backup_context_repo', None)
        except Exception:
            pass
        keyboard = [
            [InlineKeyboardButton("🗂 לפי ריפו", callback_data="by_repo_menu")],
            [InlineKeyboardButton("📦 קבצי ZIP", callback_data="backup_list")],
            [InlineKeyboardButton("📂 קבצים גדולים", callback_data="show_large_files")],
            [InlineKeyboardButton("📁 שאר הקבצים", callback_data="show_regular_files")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            "בחר/י דרך להצגת הקבצים:",
            reply_markup=reply_markup
        )
        reporter.report_activity(update.effective_user.id)
    except Exception as e:
        logger.error(f"Error in show_all_files_callback: {e}")
        await query.edit_message_text("❌ שגיאה בטעינת התפריט")
    
    return ConversationHandler.END

async def show_regular_files_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """הצגת קבצים רגילים בלבד"""
    query = update.callback_query
    await query.answer()
    
    # Instead of creating a fake update, adapt show_all_files logic for callback queries
    user_id = update.effective_user.id
    from database import db
    
    try:
        all_files = db.get_user_files(user_id)
        files = [f for f in all_files if not any((t or '').startswith('repo:') for t in (f.get('tags') or []))]
        
        if not files:
            await query.edit_message_text(
                "📂 אין לך קבצים שמורים עדיין.\n"
                "✨ לחץ על '➕ הוסף קוד חדש' כדי להתחיל יצירה!"
            )
            # כפתור חזרה לתת־התפריט של הקבצים
            keyboard = [[InlineKeyboardButton("🔙 חזור", callback_data="files")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.message.reply_text(
                "🎮 בחר פעולה:",
                reply_markup=reply_markup
            )
        else:
            # עימוד והצגת דף ראשון
            total_files = len(files)
            total_pages = (total_files + FILES_PAGE_SIZE - 1) // FILES_PAGE_SIZE if total_files > 0 else 1
            page = 1
            start_index = (page - 1) * FILES_PAGE_SIZE
            end_index = min(start_index + FILES_PAGE_SIZE, total_files)

            keyboard = []
            context.user_data['files_cache'] = {}
            for i in range(start_index, end_index):
                file = files[i]
                file_name = file.get('file_name', 'קובץ ללא שם')
                language = file.get('programming_language', 'text')
                context.user_data['files_cache'][str(i)] = file
                emoji = get_file_emoji(language)
                button_text = f"{emoji} {file_name}"
                keyboard.append([InlineKeyboardButton(button_text, callback_data=f"file_{i}")])

            # שורת עימוד
            pagination_row = []
            if page > 1:
                pagination_row.append(InlineKeyboardButton("⬅️ הקודם", callback_data=f"files_page_{page-1}"))
            if page < total_pages:
                pagination_row.append(InlineKeyboardButton("➡️ הבא", callback_data=f"files_page_{page+1}"))
            if pagination_row:
                keyboard.append(pagination_row)

            # כפתור חזרה
            keyboard.append([InlineKeyboardButton("🔙 חזור", callback_data="files")])

            reply_markup = InlineKeyboardMarkup(keyboard)

            header_text = (
                f"📚 <b>הקבצים השמורים שלך</b> — סה״כ: {total_files}\n"
                f"📄 עמוד {page} מתוך {total_pages}\n\n"
                "✨ לחץ על קובץ לחוויה מלאה של עריכה וניהול:"
            )

            await query.edit_message_text(
                header_text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML
            )
            
        reporter.report_activity(user_id)
        
    except Exception as e:
        logger.error(f"Error in show_regular_files_callback: {e}")
        await query.edit_message_text("❌ שגיאה בטעינת הקבצים")
    
    return ConversationHandler.END

async def show_regular_files_page_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """מעבר בין עמודים בתצוגת 'הקבצים השמורים שלך'"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    from database import db
    try:
        # קרא את כל הקבצים כדי לחשב עימוד
        files = db.get_user_files(user_id)
        if not files:
            # אם אין קבצים, הצג הודעה וכפתור חזרה לתת־התפריט של הקבצים
            await query.edit_message_text(
                "📂 אין לך קבצים שמורים עדיין.\n"
                "✨ לחץ על '➕ הוסף קוד חדש' כדי להתחיל יצירה!"
            )
            reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 חזור", callback_data="files")]])
            await query.message.reply_text("🎮 בחר פעולה:", reply_markup=reply_markup)
            return ConversationHandler.END

        # ניתוח מספר העמוד המבוקש
        data = query.data
        try:
            page = int(data.split("_")[-1])
        except Exception:
            page = 1
        if page < 1:
            page = 1

        total_files = len(files)
        total_pages = (total_files + FILES_PAGE_SIZE - 1) // FILES_PAGE_SIZE if total_files > 0 else 1
        if page > total_pages:
            page = total_pages

        start_index = (page - 1) * FILES_PAGE_SIZE
        end_index = min(start_index + FILES_PAGE_SIZE, total_files)

        # בנה מקלדת לדף המבוקש
        keyboard = []
        context.user_data['files_cache'] = {}
        for i in range(start_index, end_index):
            file = files[i]
            file_name = file.get('file_name', 'קובץ ללא שם')
            language = file.get('programming_language', 'text')
            context.user_data['files_cache'][str(i)] = file
            emoji = get_file_emoji(language)
            button_text = f"{emoji} {file_name}"
            keyboard.append([InlineKeyboardButton(button_text, callback_data=f"file_{i}")])

        # שורת עימוד
        pagination_row = []
        if page > 1:
            pagination_row.append(InlineKeyboardButton("⬅️ הקודם", callback_data=f"files_page_{page-1}"))
        if page < total_pages:
            pagination_row.append(InlineKeyboardButton("➡️ הבא", callback_data=f"files_page_{page+1}"))
        if pagination_row:
            keyboard.append(pagination_row)

        # כפתור חזרה
        keyboard.append([InlineKeyboardButton("🔙 חזור", callback_data="files")])

        reply_markup = InlineKeyboardMarkup(keyboard)

        header_text = (
            f"📚 <b>הקבצים השמורים שלך</b> — סה״כ: {total_files}\n"
            f"📄 עמוד {page} מתוך {total_pages}\n\n"
            "✨ לחץ על קובץ לחוויה מלאה של עריכה וניהול:"
        )

        await query.edit_message_text(
            header_text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logger.error(f"Error in show_regular_files_page_callback: {e}")
        await query.edit_message_text("❌ שגיאה בטעינת עמוד הקבצים")
    return ConversationHandler.END

async def start_save_flow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """התחלת תהליך שמירה מתקדם"""
    cancel_markup = InlineKeyboardMarkup([[InlineKeyboardButton("❌ ביטול", callback_data="cancel")]])
    await update.message.reply_text(
        "✨ *מצוין!* בואו נצור קוד חדש!\n\n"
        "📝 שלח לי את קטע הקוד המבריק שלך.\n"
        "💡 אני אזהה את השפה אוטומטית ואארגן הכל!",
        reply_markup=cancel_markup,
        parse_mode='Markdown'
    )
    reporter.report_activity(update.effective_user.id)
    return GET_CODE

async def get_code(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """קבלת הקוד עם אנליזה מתקדמת"""
    code = update.message.text
    context.user_data['code_to_save'] = code
    
    # אנליזה מהירה של הקוד
    lines = len(code.split('\n'))
    chars = len(code)
    words = len(code.split())
    
    await update.message.reply_text(
        f"✅ *קוד מתקדם התקבל בהצלחה!*\n\n"
        f"📊 **סטטיסטיקות מהירות:**\n"
        f"• 📏 שורות: {lines:,}\n"
        f"• 🔤 תווים: {chars:,}\n"
        f"• 📝 מילים: {words:,}\n\n"
        f"💭 עכשיו תן לי שם קובץ חכם (למשל: `my_amazing_script.py`)\n"
        f"🧠 השם יעזור לי לזהות את השפה ולארגן הכל מושלם!",
        parse_mode='Markdown'
    )
    return GET_FILENAME

async def get_filename(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """שמירת שם הקובץ עם בדיקות מתקדמות"""
    filename = update.message.text.strip()
    user_id = update.message.from_user.id
    
    # בדיקה מתקדמת של שם קובץ
    if not re.match(r'^[\w\.\-\_]+\.[a-zA-Z0-9]+$', filename):
        await update.message.reply_text(
            "🤔 השם נראה קצת מוזר...\n"
            "💡 נסה שם כמו: `script.py` או `index.html`\n"
            "✅ אותיות, מספרים, נקודות וקווים מותרים!"
        )
        return GET_FILENAME

    # בדיקת כפילות מתקדמת
    from database import db
    existing_file = db.get_latest_version(user_id, filename)
    
    if existing_file:
        keyboard = [
            [InlineKeyboardButton("🔄 החלף את הקובץ הקיים", callback_data=f"replace_{filename}")],
            [InlineKeyboardButton("✏️ שנה שם קובץ", callback_data="rename_file")],
            [InlineKeyboardButton("🚫 בטל ושמור במקום אחר", callback_data="cancel_save")]
        ]
        
        context.user_data['pending_filename'] = filename
        
        await update.message.reply_text(
            f"⚠️ *אופס!* הקובץ `{filename}` כבר קיים במערכת!\n\n"
            f"🤔 מה תרצה לעשות?",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
        return GET_FILENAME

    # שמירה מתקדמת
    return await save_file_final(update, context, filename, user_id)

async def save_file_final(update, context, filename, user_id):
    """שמירה סופית של הקובץ"""
    context.user_data['filename_to_save'] = filename
    code = context.user_data.get('code_to_save')
    
    try:
        # זיהוי שפה חכם
        from code_processor import code_processor
        detected_language = code_processor.detect_language(code, filename)
        
        # שמירה במסד נתונים
        from database import db
        success = db.save_file(user_id, filename, code, detected_language)
        
        if success:
            # כפתורים מתקדמים למיד אחרי שמירה
            keyboard = [
                [
                    InlineKeyboardButton("👁️ הצג קוד", callback_data=f"view_direct_{filename}"),
                    InlineKeyboardButton("✏️ ערוך", callback_data=f"edit_code_direct_{filename}")
                ],
                [
                    InlineKeyboardButton("📝 שנה שם", callback_data=f"edit_name_direct_{filename}"),
                    InlineKeyboardButton("📚 היסטוריה", callback_data=f"versions_file_{filename}")
                ],
                [
                    InlineKeyboardButton("📥 הורד", callback_data=f"download_direct_{filename}"),
                    InlineKeyboardButton("🗑️ מחק", callback_data=f"delete_direct_{filename}")
                ],
                [
                    InlineKeyboardButton("📊 מידע מתקדם", callback_data=f"info_direct_{filename}"),
                    InlineKeyboardButton("🔙 לרשימה", callback_data="files")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                f"🎉 *קובץ נשמר בהצלחה מרשימה!*\n\n"
                f"📄 **שם:** `{filename}`\n"
                f"🧠 **שפה זוהתה:** {detected_language}\n"
                f"⚡ **מוכן לעבודה מתקדמת!**\n\n"
                f"🎮 בחר פעולה מהכפתורים החכמים:",
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(
                "💥 אופס! קרתה שגיאה טכנית.\n"
                "🔧 המערכת מתקדמת - ננסה שוב מאוחר יותר!",
                reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
            )
        
    except Exception as e:
        logger.error(f"Failed to save file for user {user_id}: {e}")
        await update.message.reply_text(
            "🤖 המערכת החכמה שלנו נתקלה בבעיה זמנית.\n"
            "⚡ ננסה שוב בקרוב!",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )

    context.user_data.clear()
    return ConversationHandler.END

async def handle_duplicate_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """טיפול בכפתורי הכפילות"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    if data.startswith("replace_"):
        filename = data.replace("replace_", "")
        user_id = update.effective_user.id
        return await save_file_final(query, context, filename, user_id)
    elif data == "rename_file":
        await query.edit_message_text(
            "✏️ *שנה שם קובץ*\n\n"
            "📝 שלח שם קובץ חדש:",
            parse_mode='Markdown'
        )
        return GET_FILENAME
    elif data == "cancel_save":
        context.user_data.clear()
        await query.edit_message_text("🚫 השמירה בוטלה!")
        await query.message.reply_text(
            "🏠 חוזרים לתפריט הראשי:",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )
        return ConversationHandler.END
    
    return GET_FILENAME

async def handle_file_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """תפריט קובץ מתקדם עם אפשרויות רבות"""
    query = update.callback_query
    await query.answer()
    
    try:
        file_index = query.data.split('_')[1]
        files_cache = context.user_data.get('files_cache', {})
        file_data = files_cache.get(file_index)
        
        if not file_data:
            await query.edit_message_text("❌ שגיאה בזיהוי הקובץ החכם")
            return ConversationHandler.END
        
        file_name = file_data.get('file_name', 'קובץ מיסתורי')
        language = file_data.get('programming_language', 'לא ידועה')
        
        # כפתורים מתקדמים מלאים
        keyboard = [
            [
                InlineKeyboardButton("👁️ הצג קוד", callback_data=f"view_{file_index}"),
                InlineKeyboardButton("✏️ ערוך", callback_data=f"edit_code_{file_index}")
            ],
            [
                InlineKeyboardButton("📝 שנה שם", callback_data=f"edit_name_{file_index}"),
                InlineKeyboardButton("📚 היסטוריה", callback_data=f"versions_{file_index}")
            ],
            [
                InlineKeyboardButton("📥 הורד", callback_data=f"dl_{file_index}"),
                InlineKeyboardButton("📊 מידע", callback_data=f"info_{file_index}")
            ],
            [
                InlineKeyboardButton("🔄 שכפול", callback_data=f"clone_{file_index}"),
                InlineKeyboardButton("🗑️ מחק", callback_data=f"del_{file_index}")
            ],
            [InlineKeyboardButton("🔙 חזרה לרשימה", callback_data="files")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"🎯 *מרכז בקרה מתקדם*\n\n"
            f"📄 **קובץ:** `{file_name}`\n"
            f"🧠 **שפה:** {language}\n\n"
            f"🎮 בחר פעולה מתקדמת:",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        
    except Exception as e:
        logger.error(f"Error in handle_file_menu: {e}")
        await query.edit_message_text("💥 שגיאה במרכז הבקרה המתקדם")
    
    return ConversationHandler.END

async def handle_view_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """הצגת קוד עם אפשרויות מתקדמות"""
    query = update.callback_query
    await query.answer()
    
    try:
        file_index = query.data.split('_')[1]
        files_cache = context.user_data.get('files_cache', {})
        file_data = files_cache.get(file_index)
        
        if not file_data:
            await query.edit_message_text("⚠️ הקובץ נעלם מהמערכת החכמה")
            return ConversationHandler.END
        
        file_name = file_data.get('file_name', 'קובץ')
        code = file_data.get('code', '')
        language = file_data.get('programming_language', 'text')
        version = file_data.get('version', 1)
        
        # חיתוך חכם של הקוד
        max_length = 3500
        if len(code) > max_length:
            code_preview = code[:max_length] + "\n\n... [📱 הצג המשך - השתמש בהורדה לקובץ המלא]"
        else:
            code_preview = code
        
        # כפתורים מתקדמים לעריכה
        keyboard = [
            [
                InlineKeyboardButton("✏️ ערוך קוד", callback_data=f"edit_code_{file_index}"),
                InlineKeyboardButton("📝 ערוך שם", callback_data=f"edit_name_{file_index}")
            ],
            [
                InlineKeyboardButton("📚 היסטוריה", callback_data=f"versions_{file_index}"),
                InlineKeyboardButton("📥 הורד", callback_data=f"dl_{file_index}")
            ],
            [
                InlineKeyboardButton("🔄 שכפול", callback_data=f"clone_{file_index}"),
                InlineKeyboardButton("📊 מידע מלא", callback_data=f"info_{file_index}")
            ],
            [InlineKeyboardButton("🔙 חזרה", callback_data=f"file_{file_index}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"📄 *{file_name}* ({language}) - גרסה {version}\n\n"
            f"```{language}\n{code_preview}\n```",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        
    except Exception as e:
        logger.error(f"Error in handle_view_file: {e}")
        await query.edit_message_text("❌ שגיאה בהצגת הקוד המתקדם")
    
    return ConversationHandler.END

async def handle_edit_code(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """התחלת עריכת קוד"""
    query = update.callback_query
    await query.answer()
    
    try:
        file_index = query.data.split('_')[2]
        files_cache = context.user_data.get('files_cache', {})
        file_data = files_cache.get(file_index)
        
        if not file_data:
            await query.edit_message_text("❌ שגיאה בזיהוי הקובץ")
            return ConversationHandler.END
        
        context.user_data['editing_file_index'] = file_index
        context.user_data['editing_file_data'] = file_data
        
        file_name = file_data.get('file_name', 'קובץ')
        
        await query.edit_message_text(
            f"✏️ *עריכת קוד מתקדמת*\n\n"
            f"📄 **קובץ:** `{file_name}`\n\n"
            f"📝 שלח את הקוד החדש והמעודכן:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 חזרה", callback_data=f"file_{file_index}")]]),
            parse_mode='Markdown'
        )
        
        return EDIT_CODE
        
    except Exception as e:
        # לוגים מפורטים לשגיאות עריכה
        logger.error(f"Error in handle_edit_code: {e}")
        logger.error(f"User ID: {update.effective_user.id}")
        logger.error(f"Query data: {query.data if query else 'No query'}")
        
        # רישום בלוגר הייעודי
        try:
            from code_processor import code_processor
            code_processor.code_logger.error(f"שגיאה בהתחלת עריכת קוד עבור משתמש {update.effective_user.id}: {str(e)}")
        except:
            pass
        
        await query.edit_message_text(
            "❌ שגיאה בהתחלת עריכה\n\n"
            "🔄 אנא נסה שוב או חזור לתפריט הראשי\n"
            "📞 אם הבעיה נמשכת, פנה לתמיכה"
        )
    
    return ConversationHandler.END

async def receive_new_code(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """קבלת הקוד החדש לעריכה"""
    new_code = update.message.text
    
    # בדיקה אם מדובר בעריכת קובץ גדול
    editing_large_file = context.user_data.get('editing_large_file')
    if editing_large_file:
        try:
            user_id = update.effective_user.id
            file_name = editing_large_file['file_name']
            file_data = editing_large_file['file_data']
            
            from utils import detect_language_from_filename
            language = detect_language_from_filename(file_name)
            
            # יצירת קובץ גדול חדש עם התוכן המעודכן
            from database import LargeFile
            updated_file = LargeFile(
                user_id=user_id,
                file_name=file_name,
                content=new_code,
                programming_language=language,
                file_size=len(new_code.encode('utf-8')),
                lines_count=len(new_code.split('\n'))
            )
            
            from database import db
            success = db.save_large_file(updated_file)
            
            if success:
                from utils import get_language_emoji
                emoji = get_language_emoji(language)
                
                keyboard = [[InlineKeyboardButton("📚 חזרה לקבצים גדולים", callback_data="show_large_files")]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                lines_count = len(new_code.split('\n'))
                await update.message.reply_text(
                    f"✅ **הקובץ הגדול עודכן בהצלחה!**\n\n"
                    f"📄 **קובץ:** `{file_name}`\n"
                    f"{emoji} **שפה:** {language}\n"
                    f"💾 **גודל חדש:** {len(new_code):,} תווים\n"
                    f"📏 **שורות:** {lines_count:,}",
                    reply_markup=reply_markup,
                    parse_mode='Markdown'
                )
                
                # ניקוי נתוני העריכה
                context.user_data.pop('editing_large_file', None)
            else:
                await update.message.reply_text("❌ שגיאה בעדכון הקובץ הגדול")
            
            return ConversationHandler.END
            
        except Exception as e:
            logger.error(f"Error updating large file: {e}")
            await update.message.reply_text("❌ שגיאה בעדכון הקובץ")
            return ConversationHandler.END
    
    # המשך הטיפול הרגיל בקבצים רגילים
    file_data = context.user_data.get('editing_file_data')
    
    if not file_data:
        await update.message.reply_text("❌ שגיאה בנתוני הקובץ")
        return ConversationHandler.END
    
    try:
        user_id = update.effective_user.id
        # תמיכה במקרים ישירים ומקרי cache
        file_name = context.user_data.get('editing_file_name') or file_data.get('file_name')
        editing_file_index = context.user_data.get('editing_file_index')
        files_cache = context.user_data.get('files_cache')
        
        from code_processor import code_processor
        
        # אימות וסניטציה של הקוד הנכנס
        is_valid, cleaned_code, error_message = code_processor.validate_code_input(new_code, file_name, user_id)
        
        if not is_valid:
            await update.message.reply_text(
                f"❌ שגיאה בקלט הקוד:\n{error_message}\n\n"
                f"💡 אנא וודא שהקוד תקין ונסה שוב.",
                reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
            )
            return EDIT_CODE  # חזרה למצב עריכה
        
        # זיהוי שפה עם הקוד המנוקה
        detected_language = code_processor.detect_language(cleaned_code, file_name)
        
        from database import db
        success = db.save_file(user_id, file_name, cleaned_code, detected_language)
        
        if success:
            keyboard = [
                [
                    InlineKeyboardButton("👁️ הצג קוד מעודכן", callback_data=f"view_direct_{file_name}"),
                    InlineKeyboardButton("📚 היסטוריה", callback_data=f"versions_file_{file_name}")
                ],
                [
                    InlineKeyboardButton("📥 הורד", callback_data=f"download_direct_{file_name}"),
                    InlineKeyboardButton("🔙 לרשימה", callback_data="files")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            # Get the new version number to display
            from database import db
            updated_file = db.get_latest_version(user_id, file_name)
            version_num = updated_file.get('version', 1) if updated_file else 1
            
            # רענון קאש של הקבצים אם קיים אינדקס רלוונטי
            try:
                if files_cache is not None and editing_file_index is not None and str(editing_file_index) in files_cache:
                    entry = files_cache[str(editing_file_index)]
                    entry['code'] = cleaned_code
                    entry['programming_language'] = detected_language
                    entry['version'] = version_num
                    entry['updated_at'] = datetime.now(timezone.utc)
            except Exception as e:
                logger.warning(f"Failed to refresh files_cache after edit: {e}")
            
            await update.message.reply_text(
                f"✅ *הקובץ עודכן בהצלחה!*\n\n"
                f"📄 **קובץ:** `{file_name}`\n"
                f"🧠 **שפה:** {detected_language}\n"
                f"📝 **גרסה:** {version_num} (עודכן מהגרסה הקודמת)\n"
                f"💾 **הקובץ הקיים עודכן עם השינויים החדשים!**",
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(
                "❌ שגיאה בעדכון הקוד",
                reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
            )
    
    except Exception as e:
        # לוגים מפורטים לאיתור בעיות
        logger.error(f"Error updating code: {e}")
        logger.error(f"User ID: {update.effective_user.id}")
        logger.error(f"Original code length: {len(new_code) if new_code else 0}")
        logger.error(f"File name: {file_name if 'file_name' in locals() else 'Unknown'}")
        
        # רישום בלוגר הייעודי לקוד
        try:
            from code_processor import code_processor
            code_processor.code_logger.error(f"שגיאה בעדכון קוד עבור משתמש {update.effective_user.id}: {str(e)}")
        except:
            pass
        
        # הודעת שגיאה מפורטת למשתמש
        error_details = "פרטי השגיאה לא זמינים"
        if "validation" in str(e).lower():
            error_details = "שגיאה באימות הקוד"
        elif "database" in str(e).lower():
            error_details = "שגיאה בשמירת הקוד במסד הנתונים"
        elif "language" in str(e).lower():
            error_details = "שגיאה בזיהוי שפת התכנות"
        
        await update.message.reply_text(
            f"❌ שגיאה בעדכון הקוד\n\n"
            f"📝 **פרטים:** {error_details}\n"
            f"🔄 אנא נסה שוב או פנה לתמיכה\n"
            f"🏠 חזרה לתפריט הראשי",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
            parse_mode='Markdown'
        )
    
    # נקה את מצב העריכה אך שמור קאש של קבצים אם קיים
    preserved_cache = context.user_data.get('files_cache')
    context.user_data.clear()
    if preserved_cache is not None:
        context.user_data['files_cache'] = preserved_cache
    return ConversationHandler.END

async def handle_edit_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """התחלת עריכת שם קובץ"""
    query = update.callback_query
    await query.answer()
    
    try:
        file_index = query.data.split('_')[2]
        files_cache = context.user_data.get('files_cache', {})
        file_data = files_cache.get(file_index)
        
        if not file_data:
            await query.edit_message_text("❌ שגיאה בזיהוי הקובץ")
            return ConversationHandler.END
        
        context.user_data['editing_file_index'] = file_index
        context.user_data['editing_file_data'] = file_data
        
        current_name = file_data.get('file_name', 'קובץ')
        
        await query.edit_message_text(
            f"📝 *עריכת שם קובץ*\n\n"
            f"📄 **שם נוכחי:** `{current_name}`\n\n"
            f"✏️ שלח שם חדש לקובץ:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 חזרה", callback_data=f"file_{file_index}")]]),
            parse_mode='Markdown'
        )
        
        return EDIT_NAME
        
    except Exception as e:
        logger.error(f"Error in handle_edit_name: {e}")
        await query.edit_message_text("❌ שגיאה בהתחלת עריכת שם")
    
    return ConversationHandler.END

async def receive_new_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """קבלת השם החדש לקובץ"""
    new_name = update.message.text.strip()
    file_data = context.user_data.get('editing_file_data')
    
    if not file_data:
        await update.message.reply_text("❌ שגיאה בנתוני הקובץ")
        return ConversationHandler.END
    
    # בדיקת תקינות שם
    if not re.match(r'^[\w\.\-\_]+\.[a-zA-Z0-9]+$', new_name):
        await update.message.reply_text(
            "🤔 השם נראה קצת מוזר...\n"
            "💡 נסה שם כמו: `script.py` או `index.html`\n"
            "✅ אותיות, מספרים, נקודות וקווים מותרים!"
        )
        return EDIT_NAME
    
    try:
        user_id = update.effective_user.id
        # תמיכה במקרים ישירים ומקרי cache
        old_name = context.user_data.get('editing_file_name') or file_data.get('file_name')
        
        from database import db
        success = db.rename_file(user_id, old_name, new_name)
        
        if success:
            keyboard = [
                [
                    InlineKeyboardButton("👁️ הצג קוד", callback_data=f"view_direct_{new_name}"),
                    InlineKeyboardButton("📚 היסטוריה", callback_data=f"versions_file_{new_name}")
                ],
                [
                    InlineKeyboardButton("📥 הורד", callback_data=f"download_direct_{new_name}"),
                    InlineKeyboardButton("🔙 לרשימה", callback_data="files")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                f"✅ *שם הקובץ שונה בהצלחה!*\n\n"
                f"📄 **שם ישן:** `{old_name}`\n"
                f"📄 **שם חדש:** `{new_name}`\n"
                f"🎉 **הכל מעודכן במערכת!**",
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(
                "❌ שגיאה בשינוי השם",
                reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
            )
    
    except Exception as e:
        logger.error(f"Error renaming file: {e}")
        await update.message.reply_text(
            "❌ שגיאה בשינוי השם",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )
    
    context.user_data.clear()
    return ConversationHandler.END

async def handle_versions_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """הצגת היסטוריית גרסאות"""
    query = update.callback_query
    await query.answer()
    
    try:
        data = query.data
        file_index: Optional[str] = None
        files_cache = context.user_data.get('files_cache', {})
        
        if data.startswith("versions_file_"):
            # מצב של שם קובץ ישיר
            file_name = data.replace("versions_file_", "", 1)
        else:
            # מצב של אינדקס מרשימת הקבצים
            file_index = data.split('_')[1]
            file_data = files_cache.get(file_index)
            
            if not file_data:
                await query.edit_message_text("❌ שגיאה בזיהוי הקובץ")
                return ConversationHandler.END
            
            file_name = file_data.get('file_name')
        
        user_id = update.effective_user.id
        from database import db
        versions = db.get_all_versions(user_id, file_name)
        
        if not versions:
            await query.edit_message_text("📚 אין היסטוריית גרסאות לקובץ זה")
            return ConversationHandler.END
        
        # הנח שהרשימה ממוינת כך שהגרסה העדכנית ראשונה
        latest_version_num = versions[0].get('version') if versions and isinstance(versions[0], dict) else None
        
        history_text = f"📚 *היסטוריית גרסאות - {file_name}*\n\n"
        
        keyboard: List[List[InlineKeyboardButton]] = []
        
        for i, version in enumerate(versions[:5]):  # מציג עד 5 גרסאות
            created_at = version.get('created_at', 'לא ידוע')
            version_num = version.get('version', i+1)
            code_length = len(version.get('code', ''))
            
            history_text += f"🔹 **גרסה {version_num}**\n"
            history_text += f"   📅 {created_at}\n"
            history_text += f"   📏 {code_length:,} תווים\n\n"
            
            # כפתורים לפעולות על כל גרסה
            if latest_version_num is not None and version_num == latest_version_num:
                # אל תציג כפתור שחזור עבור הגרסה הנוכחית
                keyboard.append([
                    InlineKeyboardButton(
                        f"👁 הצג גרסה {version_num}",
                        callback_data=f"view_version_{version_num}_{file_name}"
                    )
                ])
            else:
                keyboard.append([
                    InlineKeyboardButton(
                        f"👁 הצג גרסה {version_num}",
                        callback_data=f"view_version_{version_num}_{file_name}"
                    ),
                    InlineKeyboardButton(
                        f"↩️ שחזר לגרסה {version_num}",
                        callback_data=f"revert_version_{version_num}_{file_name}"
                    )
                ])
        
        # כפתור חזרה מתאים לפי מקור הקריאה
        if file_index is not None:
            keyboard.append([InlineKeyboardButton("🔙 חזרה", callback_data=f"file_{file_index}")])
        else:
            keyboard.append([InlineKeyboardButton("🔙 חזרה", callback_data=f"view_direct_{file_name}")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            history_text,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        
    except Exception as e:
        logger.error(f"Error in handle_versions_history: {e}")
        await query.edit_message_text("❌ שגיאה בהצגת היסטוריה")
    
    return ConversationHandler.END

async def handle_download_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """הורדת קובץ"""
    query = update.callback_query
    await query.answer()
    
    try:
        data = query.data
        files_cache = context.user_data.get('files_cache', {})
        file_name: Optional[str] = None
        code: str = ''
        
        if data.startswith('dl_'):
            # מצב אינדקס
            file_index = data.split('_')[1]
            file_data = files_cache.get(file_index)
            
            if not file_data:
                await query.edit_message_text("❌ שגיאה בזיהוי הקובץ")
                return ConversationHandler.END
            
            file_name = file_data.get('file_name', 'file.txt')
            code = file_data.get('code', '')
        elif data.startswith('download_direct_'):
            # מצב שם ישיר
            file_name = data.replace('download_direct_', '', 1)
            from database import db
            user_id = update.effective_user.id
            latest = db.get_latest_version(user_id, file_name)
            if not latest:
                await query.edit_message_text("❌ לא נמצאה גרסה אחרונה לקובץ")
                return ConversationHandler.END
            code = latest.get('code', '')
        else:
            await query.edit_message_text("❌ בקשת הורדה לא חוקית")
            return ConversationHandler.END
        
        # יצירת קובץ להורדה
        file_bytes = BytesIO()
        file_bytes.write(code.encode('utf-8'))
        file_bytes.seek(0)
        
        await query.message.reply_document(
            document=file_bytes,
            filename=file_name,
            caption=f"📥 *הורדת קובץ*\n\n📄 **שם:** `{file_name}`\n📏 **גודל:** {len(code):,} תווים"
        )
        
        keyboard = []
        if data.startswith('dl_'):
            file_index = data.split('_')[1]
            keyboard.append([InlineKeyboardButton("🔙 חזרה", callback_data=f"file_{file_index}")])
        else:
            keyboard.append([InlineKeyboardButton("🔙 חזרה", callback_data=f"view_direct_{file_name}")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"✅ *הקובץ הורד בהצלחה!*\n\n"
            f"📄 **שם:** `{file_name}`",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        
    except Exception as e:
        logger.error(f"Error in handle_download_file: {e}")
        await query.edit_message_text("❌ שגיאה בהורדת הקובץ")
    
    return ConversationHandler.END

async def handle_delete_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """אישור מחיקת קובץ"""
    query = update.callback_query
    await query.answer()
    
    try:
        file_index = query.data.split('_')[1]
        files_cache = context.user_data.get('files_cache', {})
        file_data = files_cache.get(file_index)
        
        if not file_data:
            await query.edit_message_text("❌ שגיאה בזיהוי הקובץ")
            return ConversationHandler.END
        
        file_name = file_data.get('file_name', 'קובץ')
        
        keyboard = [
            [
                InlineKeyboardButton("✅ כן, מחק", callback_data=f"confirm_del_{file_index}"),
                InlineKeyboardButton("❌ לא, בטל", callback_data=f"file_{file_index}")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"⚠️ *אישור מחיקה*\n\n"
            f"📄 **קובץ:** `{file_name}`\n\n"
            f"🗑️ האם אתה בטוח שברצונך למחוק את הקובץ?\n"
            f"⚠️ **פעולה זו לא ניתנת לביטול!**",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        
    except Exception as e:
        logger.error(f"Error in handle_delete_confirmation: {e}")
        await query.edit_message_text("❌ שגיאה באישור מחיקה")
    
    return ConversationHandler.END

async def handle_delete_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """מחיקת קובץ סופית"""
    query = update.callback_query
    await query.answer()
    
    try:
        file_index = query.data.split('_')[2]
        files_cache = context.user_data.get('files_cache', {})
        file_data = files_cache.get(file_index)
        
        if not file_data:
            await query.edit_message_text("❌ שגיאה בזיהוי הקובץ")
            return ConversationHandler.END
        
        user_id = update.effective_user.id
        file_name = file_data.get('file_name')
        
        from database import db
        success = db.delete_file(user_id, file_name)
        
        if success:
            keyboard = [
                [InlineKeyboardButton("🔙 לרשימת קבצים", callback_data="files")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                f"✅ *הקובץ נמחק בהצלחה!*\n\n"
                f"📄 **קובץ שנמחק:** `{file_name}`\n"
                f"🗑️ **הקובץ הוסר לחלוטין מהמערכת**",
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
        else:
            await query.edit_message_text(
                f"❌ שגיאה במחיקת הקובץ `{file_name}`"
            )
        
    except Exception as e:
        logger.error(f"Error in handle_delete_file: {e}")
        await query.edit_message_text("❌ שגיאה במחיקת הקובץ")
    
    return ConversationHandler.END

async def handle_file_info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """הצגת מידע מפורט על קובץ"""
    query = update.callback_query
    await query.answer()
    
    try:
        file_index = query.data.split('_')[1]
        files_cache = context.user_data.get('files_cache', {})
        file_data = files_cache.get(file_index)
        
        if not file_data:
            await query.edit_message_text("❌ שגיאה בזיהוי הקובץ")
            return ConversationHandler.END
        
        file_name = file_data.get('file_name', 'קובץ')
        code = file_data.get('code', '')
        language = file_data.get('programming_language', 'לא ידועה')
        created_at = file_data.get('created_at', 'לא ידוע')
        version = file_data.get('version', 1)
        
        # חישוב סטטיסטיקות
        lines = len(code.split('\n'))
        chars = len(code)
        words = len(code.split())
        
        info_text = (
            f"📊 *מידע מפורט על הקובץ*\n\n"
            f"📄 **שם:** `{file_name}`\n"
            f"🧠 **שפת תכנות:** {language}\n"
            f"📅 **נוצר:** {created_at}\n"
            f"🔢 **גרסה:** {version}\n\n"
            f"📊 **סטטיסטיקות:**\n"
            f"• 📏 שורות: {lines:,}\n"
            f"• 🔤 תווים: {chars:,}\n"
            f"• 📝 מילים: {words:,}\n"
        )
        
        keyboard = [
            [InlineKeyboardButton("🔙 חזרה", callback_data=f"file_{file_index}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            info_text,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        
    except Exception as e:
        logger.error(f"Error in handle_file_info: {e}")
        await query.edit_message_text("❌ שגיאה בהצגת מידע")
    
    return ConversationHandler.END

async def handle_view_direct_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """הצגת קובץ באמצעות שם קובץ ישיר"""
    query = update.callback_query
    await query.answer()
    
    try:
        file_name = query.data.replace("view_direct_", "")
        user_id = update.effective_user.id
        
        from database import db
        file_data = db.get_latest_version(user_id, file_name)
        
        if not file_data:
            await query.edit_message_text("⚠️ הקובץ נעלם מהמערכת החכמה")
            return ConversationHandler.END
        
        code = file_data.get('code', '')
        language = file_data.get('programming_language', 'text')
        version = file_data.get('version', 1)
        
        # חיתוך חכם של הקוד
        max_length = 3500
        if len(code) > max_length:
            code_preview = code[:max_length] + "\n\n... [📱 הצג המשך - השתמש בהורדה לקובץ המלא]"
        else:
            code_preview = code
        
        # כפתורים מתקדמים לעריכה
        keyboard = [
            [
                InlineKeyboardButton("✏️ ערוך קוד", callback_data=f"edit_code_direct_{file_name}"),
                InlineKeyboardButton("📝 ערוך שם", callback_data=f"edit_name_direct_{file_name}")
            ],
            [
                InlineKeyboardButton("📚 היסטוריה", callback_data=f"versions_file_{file_name}"),
                InlineKeyboardButton("📥 הורד", callback_data=f"download_direct_{file_name}")
            ],
            [
                InlineKeyboardButton("🔄 שכפול", callback_data=f"clone_direct_{file_name}"),
                InlineKeyboardButton("📊 מידע מלא", callback_data=f"info_direct_{file_name}")
            ],
            [InlineKeyboardButton("🔙 לרשימה", callback_data="files")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"📄 *{file_name}* ({language}) - גרסה {version}\n\n"
            f"```{language}\n{code_preview}\n```",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        
    except Exception as e:
        logger.error(f"Error in handle_view_direct_file: {e}")
        await query.edit_message_text("❌ שגיאה בהצגת הקוד המתקדם")
    
    return ConversationHandler.END

async def handle_edit_code_direct(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """התחלת עריכת קוד באמצעות שם קובץ ישיר"""
    query = update.callback_query
    await query.answer()
    
    try:
        file_name = query.data.replace("edit_code_direct_", "")
        user_id = update.effective_user.id
        
        from database import db
        file_data = db.get_latest_version(user_id, file_name)
        
        if not file_data:
            await query.edit_message_text("❌ שגיאה בזיהוי הקובץ")
            return ConversationHandler.END
        
        context.user_data['editing_file_data'] = file_data
        context.user_data['editing_file_name'] = file_name
        
        await query.edit_message_text(
            f"✏️ *עריכת קוד מתקדמת*\n\n"
            f"📄 **קובץ:** `{file_name}`\n\n"
            f"📝 שלח את הקוד החדש והמעודכן:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 חזרה", callback_data=f"view_direct_{file_name}")]]),
            parse_mode='Markdown'
        )
        
        return EDIT_CODE
        
    except Exception as e:
        logger.error(f"Error in handle_edit_code_direct: {e}")
        await query.edit_message_text("❌ שגיאה בהתחלת עריכה")
    
    return ConversationHandler.END

async def handle_edit_name_direct(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """התחלת עריכת שם קובץ באמצעות שם קובץ ישיר"""
    query = update.callback_query
    await query.answer()
    
    try:
        file_name = query.data.replace("edit_name_direct_", "")
        user_id = update.effective_user.id
        
        from database import db
        file_data = db.get_latest_version(user_id, file_name)
        
        if not file_data:
            await query.edit_message_text("❌ שגיאה בזיהוי הקובץ")
            return ConversationHandler.END
        
        context.user_data['editing_file_data'] = file_data
        context.user_data['editing_file_name'] = file_name
        
        await query.edit_message_text(
            f"📝 *עריכת שם קובץ*\n\n"
            f"📄 **שם נוכחי:** `{file_name}`\n\n"
            f"✏️ שלח שם חדש לקובץ:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 חזרה", callback_data=f"view_direct_{file_name}")]]),
            parse_mode='Markdown'
        )
        
        return EDIT_NAME
        
    except Exception as e:
        logger.error(f"Error in handle_edit_name_direct: {e}")
        await query.edit_message_text("❌ שגיאה בהתחלת עריכת שם")
    
    return ConversationHandler.END

async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """מרכז בקרה מתקדם לכל הכפתורים"""
    query = update.callback_query
    
    try:
        data = query.data
        
        if data.startswith("file_") and not data.startswith("files"):
            return await handle_file_menu(update, context)
        elif data.startswith("view_"):
            if data.startswith("view_direct_"):
                return await handle_view_direct_file(update, context)
            elif data.startswith("view_version_"):
                return await handle_view_version(update, context)
            else:
                return await handle_view_file(update, context)
        elif data.startswith("edit_code_"):
            if data.startswith("edit_code_direct_"):
                return await handle_edit_code_direct(update, context)
            else:
                return await handle_edit_code(update, context)
        elif data.startswith("edit_name_"):
            if data.startswith("edit_name_direct_"):
                return await handle_edit_name_direct(update, context)
            else:
                return await handle_edit_name(update, context)
        elif data.startswith("revert_version_"):
            return await handle_revert_version(update, context)
        elif data.startswith("versions_"):
            return await handle_versions_history(update, context)
        elif data.startswith("dl_") or data.startswith("download_"):
            return await handle_download_file(update, context)
        elif data.startswith("del_") or data.startswith("delete_"):
            return await handle_delete_confirmation(update, context)
        elif data.startswith("confirm_del_"):
            return await handle_delete_file(update, context)
        elif data.startswith("info_"):
            return await handle_file_info(update, context)
        elif data == "files" or data == "refresh_files":
            return await show_all_files_callback(update, context)
        elif data == "by_repo_menu":
            return await show_by_repo_menu_callback(update, context)
        elif data.startswith("files_page_"):
            return await show_regular_files_page_callback(update, context)
        elif data == "main" or data == "main_menu":
            await query.edit_message_text("🏠 חוזר לבית החכם:")
            await query.message.reply_text(
                "🎮 בחר פעולה מתקדמת:",
                reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
            )
            return ConversationHandler.END
        elif data == "cancel":
            # ביטול כללי דרך כפתור
            context.user_data.clear()
            await query.edit_message_text("🚫 התהליך בוטל בהצלחה!")
            await query.message.reply_text(
                "🎮 בחר פעולה מתקדמת:",
                reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
            )
            return ConversationHandler.END
        elif data.startswith("replace_") or data == "rename_file" or data == "cancel_save":
            return await handle_duplicate_callback(update, context)
        
        # טיפול בקבצים גדולים
        elif data == "show_regular_files":
            return await show_regular_files_callback(update, context)
        elif data == "show_large_files":
            from large_files_handler import large_files_handler
            await large_files_handler.show_large_files_menu(update, context)
        elif data.startswith("lf_page_"):
            from large_files_handler import large_files_handler
            page = int(data.replace("lf_page_", ""))
            await large_files_handler.show_large_files_menu(update, context, page)
        elif data.startswith("large_file_"):
            from large_files_handler import large_files_handler
            await large_files_handler.handle_file_selection(update, context)
        elif data.startswith("lf_view_"):
            from large_files_handler import large_files_handler
            await large_files_handler.view_large_file(update, context)
        elif data.startswith("lf_download_"):
            from large_files_handler import large_files_handler
            await large_files_handler.download_large_file(update, context)
        elif data.startswith("lf_edit_"):
            from large_files_handler import large_files_handler
            return await large_files_handler.edit_large_file(update, context)
        elif data.startswith("lf_delete_"):
            from large_files_handler import large_files_handler
            await large_files_handler.delete_large_file_confirm(update, context)
        elif data.startswith("lf_confirm_delete_"):
            from large_files_handler import large_files_handler
            await large_files_handler.delete_large_file(update, context)
        elif data.startswith("lf_info_"):
            from large_files_handler import large_files_handler
            await large_files_handler.show_file_info(update, context)
        elif data in ("batch_analyze_all", "batch_analyze_python", "batch_analyze_javascript", "batch_analyze_java", "batch_analyze_cpp"):
            from database import db
            from batch_processor import batch_processor
            user_id = update.effective_user.id
            language_map = {
                "batch_analyze_python": "python",
                "batch_analyze_javascript": "javascript",
                "batch_analyze_java": "java",
                "batch_analyze_cpp": "cpp",
            }
            if data == "batch_analyze_all":
                all_files = db.get_user_files(user_id, limit=1000)
                files = [f['file_name'] for f in all_files]
            else:
                language = language_map[data]
                all_files = db.get_user_files(user_id, limit=1000)
                files = [f['file_name'] for f in all_files if f.get('programming_language', '').lower() == language]
            if not files:
                await query.answer("❌ לא נמצאו קבצים", show_alert=True)
                return ConversationHandler.END
            job_id = await batch_processor.analyze_files_batch(user_id, files)
            keyboard = [[InlineKeyboardButton("📊 בדוק סטטוס", callback_data=f"job_status:{job_id}")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            sent = await query.message.reply_text(
                f"⚡ <b>ניתוח Batch התחיל!</b>\n\n📁 מנתח {len(files)} קבצים\n🆔 Job ID: <code>{job_id}</code>",
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup
            )
            asyncio.create_task(_auto_update_batch_status(context.application, sent.chat_id, sent.message_id, job_id, user_id))
        elif data == "batch_validate_all":
            from database import db
            from batch_processor import batch_processor
            user_id = update.effective_user.id
            all_files = db.get_user_files(user_id, limit=1000)
            files = [f['file_name'] for f in all_files]
            if not files:
                await query.answer("❌ לא נמצאו קבצים", show_alert=True)
                return ConversationHandler.END
            job_id = await batch_processor.validate_files_batch(user_id, files)
            keyboard = [[InlineKeyboardButton("📊 בדוק סטטוס", callback_data=f"job_status:{job_id}")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            sent = await query.message.reply_text(
                f"✅ <b>בדיקת תקינות Batch התחילה!</b>\n\n📁 בודק {len(files)} קבצים\n🆔 Job ID: <code>{job_id}</code>",
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup
            )
            # Auto refresh
            asyncio.create_task(_auto_update_batch_status(context.application, sent.chat_id, sent.message_id, job_id, user_id))
        elif data == "show_jobs":
            from batch_processor import batch_processor
            active_jobs = [job for job in batch_processor.active_jobs.values() if job.user_id == update.effective_user.id]
            if not active_jobs:
                await query.answer("אין עבודות פעילות", show_alert=True)
                return ConversationHandler.END
            keyboard = []
            for job in active_jobs[-5:]:
                keyboard.append([InlineKeyboardButton(f"{job.operation} - {job.status}", callback_data=f"job_status:{job.job_id}")])
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.message.reply_text(
                f"📋 <b>עבודות Batch פעילות ({len(active_jobs)}):</b>",
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup
            )
        elif data == "noop":
            # כפתור שלא עושה כלום (לתצוגה בלבד)
            await query.answer()
        elif data == "back_to_repo_menu":
            return await show_by_repo_menu_callback(update, context)
        elif data.startswith("help_page:"):
            try:
                p = int(data.split(":")[1])
            except Exception:
                p = 1
            return await show_help_page(update, context, page=p)
        # --- Batch category routing ---
        elif data == "batch_menu":
            return await show_batch_menu(update, context)
        elif data == "batch_cat:repos":
            return await show_batch_repos_menu(update, context)
        elif data == "batch_cat:zips":
            context.user_data['batch_target'] = { 'type': 'zips' }
            return await show_batch_files_menu(update, context, page=1)
        elif data == "batch_cat:large":
            context.user_data['batch_target'] = { 'type': 'large' }
            return await show_batch_files_menu(update, context, page=1)
        elif data == "batch_cat:other":
            context.user_data['batch_target'] = { 'type': 'other' }
            return await show_batch_files_menu(update, context, page=1)
        elif data.startswith("batch_repo:"):
            tag = data.split(":", 1)[1]
            context.user_data['batch_target'] = { 'type': 'repo', 'tag': tag }
            return await show_batch_files_menu(update, context, page=1)
        elif data.startswith("batch_files_page_"):
            try:
                p = int(data.split("_")[-1])
            except Exception:
                p = 1
            return await show_batch_files_menu(update, context, page=p)
        elif data.startswith("batch_file:"):
            # בחירת קובץ יחיד
            gi = int(data.split(":", 1)[1])
            items = context.user_data.get('batch_items') or []
            if 0 <= gi < len(items):
                context.user_data['batch_selected_files'] = [items[gi]]
                return await show_batch_actions_menu(update, context)
            else:
                await query.answer("קובץ לא קיים", show_alert=True)
                return ConversationHandler.END
        elif data == "batch_select_all":
            items = context.user_data.get('batch_items') or []
            if not items:
                await query.answer("אין קבצים לבחור", show_alert=True)
                return ConversationHandler.END
            context.user_data['batch_selected_files'] = list(items)
            return await show_batch_actions_menu(update, context)
        elif data == "batch_back_to_files":
            return await show_batch_files_menu(update, context, page=1)
        elif data.startswith("batch_action:"):
            action = data.split(":", 1)[1]
            return await execute_batch_on_current_selection(update, context, action)
        elif data.startswith("by_repo:"):
            # הצגת קבצים לפי תגית ריפו
            tag = data.split(":", 1)[1]
            from database import db
            user_id = update.effective_user.id
            files = db.search_code(user_id, query="", tags=[tag], limit=200)
            if not files:
                await query.edit_message_text("ℹ️ אין קבצים עבור התגית הזו.")
                return ConversationHandler.END
            keyboard = []
            for i, f in enumerate(files[:20]):
                name = f.get('file_name', 'ללא שם')
                keyboard.append([InlineKeyboardButton(name, callback_data=f"file_{i}")])
                # שמור קאש קל להצגה
                context.user_data.setdefault('files_cache', {})[str(i)] = f
            keyboard.append([InlineKeyboardButton("🔙 חזור", callback_data="back_to_repo_menu")])
            keyboard.append([InlineKeyboardButton("🏠 תפריט ראשי", callback_data="main")])
            await query.edit_message_text(
                f"📂 קבצים עם {tag}:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        
    except telegram.error.BadRequest as e:
        if "Message is not modified" not in str(e):
            raise
    except Exception as e:
        logger.error(f"Error in smart callback handler: {e}")
    
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """ביטול מתקדם"""
    context.user_data.clear()
    
    await update.message.reply_text(
        "🚫 התהליך בוטל בהצלחה!\n"
        "🏠 חוזרים לבית החכם שלנו.",
        reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
    )
    return ConversationHandler.END

def get_save_conversation_handler(db: DatabaseManager) -> ConversationHandler:
    """יוצר ConversationHandler מתקדם וחכם"""
    logger.info("יוצר מערכת שיחה מתקדמת...")
    
    return ConversationHandler(
        entry_points=[
            CommandHandler("start", start_command),
            MessageHandler(filters.Regex("^➕ הוסף קוד חדש$"), start_save_flow),
            MessageHandler(filters.Regex("^📚 הצג את כל הקבצים שלי$"), show_all_files),
            MessageHandler(filters.Regex("^📂 קבצים גדולים$"), show_large_files_direct),
            MessageHandler(filters.Regex("^🔧 GitHub$"), show_github_menu),
            MessageHandler(filters.Regex("^📥 ייבוא ZIP מריפו$"), start_repo_zip_import),
            MessageHandler(filters.Regex("^🗂 לפי ריפו$"), show_by_repo_menu),
            MessageHandler(filters.Regex("^ℹ️ הסבר על הבוט$"), lambda u, c: show_help_page(u, c, page=1)),
            
            # כניסה לעריכת קוד/שם גם דרך כפתורי callback כדי שמצב השיחה ייקבע כראוי
            CallbackQueryHandler(handle_callback_query, pattern=r'^(edit_code_|edit_name_|lf_edit_)')
        ],
        states={
            GET_CODE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_code)
            ],
            GET_FILENAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_filename),
                CallbackQueryHandler(handle_duplicate_callback)
            ],
            EDIT_CODE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_new_code)
            ],
            EDIT_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_new_name)
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            CallbackQueryHandler(handle_callback_query)
        ],
        allow_reentry=True,
        per_message=False
    )

async def handle_view_version(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """הצגת קוד של גרסה מסוימת"""
    query = update.callback_query
    await query.answer()
    
    try:
        data = query.data  # פורמט צפוי: view_version_{version}_{file_name}
        remainder = data.replace('view_version_', '', 1)
        sep_index = remainder.find('_')
        if sep_index == -1:
            await query.edit_message_text("❌ נתוני גרסה שגויים")
            return ConversationHandler.END
        version_str = remainder[:sep_index]
        file_name = remainder[sep_index+1:]
        version_num = int(version_str)
        
        user_id = update.effective_user.id
        from database import db
        version_doc = db.get_version(user_id, file_name, version_num)
        if not version_doc:
            await query.edit_message_text("❌ הגרסה המבוקשת לא נמצאה")
            return ConversationHandler.END
        
        # בדיקה אם זו הגרסה הנוכחית
        latest_doc = db.get_latest_version(user_id, file_name)
        latest_version_num = latest_doc.get('version') if latest_doc else None
        is_current = latest_version_num == version_num
        
        code = version_doc.get('code', '')
        language = version_doc.get('programming_language', 'text')
        
        # קיצור תצוגה אם ארוך מדי
        max_length = 3500
        if len(code) > max_length:
            code_preview = code[:max_length] + "\n\n... [הקובץ קוצר, להמשך מלא הורד את הקובץ]"
        else:
            code_preview = code
        
        if is_current:
            keyboard = [
                [
                    InlineKeyboardButton("📚 היסטוריה", callback_data=f"versions_file_{file_name}")
                ],
                [InlineKeyboardButton("🔙 חזרה", callback_data=f"view_direct_{file_name}")]
            ]
        else:
            keyboard = [
                [
                    InlineKeyboardButton("↩️ שחזר לגרסה זו", callback_data=f"revert_version_{version_num}_{file_name}"),
                    InlineKeyboardButton("📚 היסטוריה", callback_data=f"versions_file_{file_name}")
                ],
                [InlineKeyboardButton("🔙 חזרה", callback_data=f"view_direct_{file_name}")]
            ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"📄 *{file_name}* ({language}) - גרסה {version_num}\n\n"
            f"```{language}\n{code_preview}\n```",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        
    except Exception as e:
        logger.error(f"Error in handle_view_version: {e}")
        await query.edit_message_text("❌ שגיאה בהצגת גרסה")
    
    return ConversationHandler.END

async def handle_revert_version(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """שחזור הקובץ לגרסה מסוימת על ידי יצירת גרסה חדשה עם תוכן ישן"""
    query = update.callback_query
    await query.answer()
    
    try:
        data = query.data  # פורמט צפוי: revert_version_{version}_{file_name}
        remainder = data.replace('revert_version_', '', 1)
        sep_index = remainder.find('_')
        if sep_index == -1:
            await query.edit_message_text("❌ נתוני שחזור שגויים")
            return ConversationHandler.END
        version_str = remainder[:sep_index]
        file_name = remainder[sep_index+1:]
        version_num = int(version_str)
        
        user_id = update.effective_user.id
        from database import db
        version_doc = db.get_version(user_id, file_name, version_num)
        if not version_doc:
            await query.edit_message_text("❌ הגרסה לשחזור לא נמצאה")
            return ConversationHandler.END
        
        code = version_doc.get('code', '')
        language = version_doc.get('programming_language', 'text')
        
        success = db.save_file(user_id, file_name, code, language)
        if not success:
            await query.edit_message_text("❌ שגיאה בשחזור הגרסה")
            return ConversationHandler.END
        
        latest = db.get_latest_version(user_id, file_name)
        latest_ver = latest.get('version', version_num) if latest else version_num
        
        keyboard = [
            [
                InlineKeyboardButton("👁️ הצג קוד מעודכן", callback_data=f"view_direct_{file_name}"),
                InlineKeyboardButton("📚 היסטוריה", callback_data=f"versions_file_{file_name}")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"✅ *שוחזר בהצלחה לגרסה {version_num}!*\n\n"
            f"📄 **קובץ:** `{file_name}`\n"
            f"📝 **גרסה נוכחית:** {latest_ver}",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        
    except Exception as e:
        logger.error(f"Error in handle_revert_version: {e}")
        await query.edit_message_text("❌ שגיאה בשחזור גרסה")
    
    return ConversationHandler.END

async def handle_preview_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """טיפול בכפתור 'תצוגה מקדימה'"""
    user_id = update.effective_user.id
    
    # הצגת קבצים אחרונים לתצוגה מקדימה
    from autocomplete_manager import autocomplete
    recent_files = autocomplete.get_recent_files(user_id, limit=8)
    
    if not recent_files:
        await update.message.reply_text(
            "📂 אין קבצים זמינים לתצוגה מקדימה\n\n"
            "💡 צור קבצים חדשים כדי להשתמש בפיצ'ר זה",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
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
    
    # כפתור חזרה
    keyboard.append([
        InlineKeyboardButton("🏠 תפריט ראשי", callback_data="main_menu")
    ])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "👁️ <b>תצוגה מקדימה מהירה</b>\n\n"
        "בחר קובץ לתצוגה מקדימה (15 שורות ראשונות):",
        parse_mode=ParseMode.HTML,
        reply_markup=reply_markup
    )

async def handle_autocomplete_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """טיפול בכפתור 'אוטו-השלמה'"""
    await update.message.reply_text(
        "🔍 <b>אוטו-השלמה חכמה</b>\n\n"
        "השתמש בפקודה: <code>/autocomplete &lt;תחילת_שם&gt;</code>\n\n"
        "דוגמאות:\n"
        "• <code>/autocomplete scr</code> - יציע script.py, scraper.js\n"
        "• <code>/autocomplete api</code> - יציע api.py, api_client.js\n"
        "• <code>/autocomplete test</code> - יציע test_utils.py, testing.js\n\n"
        "💡 <b>טיפ:</b> ככל שתכתוב יותר תווים, ההצעות יהיו מדויקות יותר!",
        parse_mode=ParseMode.HTML,
        reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
    )

async def handle_batch_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """טיפול בכפתור 'עיבוד Batch' - מציג תפריט בחירת קטגוריה"""
    await show_batch_menu(update, context)

async def show_batch_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """תפריט בחירת קטגוריה עבור עיבוד Batch"""
    query = update.callback_query if update.callback_query else None
    if query:
        await query.answer()
        send = query.edit_message_text
    else:
        send = update.message.reply_text
    keyboard = [
        [InlineKeyboardButton("🗂 לפי ריפו", callback_data="batch_cat:repos")],
        [InlineKeyboardButton("📦 קבצי ZIP", callback_data="batch_cat:zips")],
        [InlineKeyboardButton("📂 קבצים גדולים", callback_data="batch_cat:large")],
        [InlineKeyboardButton("📁 שאר הקבצים", callback_data="batch_cat:other")],
        [InlineKeyboardButton("📋 סטטוס עבודות", callback_data="show_jobs")],
        [InlineKeyboardButton("🔙 חזור", callback_data="main")],
    ]
    await send(
        "⚡ <b>עיבוד Batch</b>\n\nבחר/י קבוצת קבצים לעיבוד:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.HTML
    )
    return ConversationHandler.END

async def show_batch_repos_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """תפריט בחירת ריפו לעיבוד Batch"""
    from database import db
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    files = db.get_user_files(user_id, limit=1000)
    repo_to_count = {}
    for f in files:
        for t in f.get('tags', []) or []:
            if t.startswith('repo:'):
                repo_to_count[t] = repo_to_count.get(t, 0) + 1
    if not repo_to_count:
        await query.edit_message_text("ℹ️ אין קבצים עם תגיות ריפו.")
        return ConversationHandler.END
    # מיין לפי תווית מוצגת (repo בלבד) לשיפור קריאות
    sorted_items = sorted(repo_to_count.items(), key=lambda x: _repo_only_from_tag(x[0]).lower())[:50]
    keyboard = []
    lines = ["🗂 בחר/י ריפו לעיבוד:", ""]
    for tag, cnt in sorted_items:
        # תווית מלאה לרשימה
        lines.append(f"• {_repo_label_from_tag(tag)} ({cnt})")
        # כפתור עם שם מקוצר בלבד
        btn_text = _build_repo_button_text(tag, cnt)
        keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"batch_repo:{tag}")])
    keyboard.append([InlineKeyboardButton("🔙 חזור", callback_data="batch_menu")])
    await query.edit_message_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ConversationHandler.END

async def show_batch_files_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 1) -> int:
    """מציג רשימת קבצים בהתאם לקטגוריה שנבחרה לבחירה (הכל או בודד)"""
    from database import db
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    target = context.user_data.get('batch_target') or {}
    t = target.get('type')
    items: List[str] = []
    try:
        if t == 'repo':
            tag = target.get('tag')
            files_docs = db.search_code(user_id, query="", tags=[tag], limit=2000)
            items = [f.get('file_name') for f in files_docs if f.get('file_name')]
        elif t == 'zips':
            # הצג את כל הקבצים הרגילים
            files_docs = db.get_user_files(user_id, limit=1000)
            items = [f.get('file_name') for f in files_docs if f.get('file_name')]
        elif t == 'large':
            large_files, _ = db.get_user_large_files(user_id, page=1, per_page=10000)
            items = [f.get('file_name') for f in large_files if f.get('file_name')]
        elif t == 'other':
            files_docs = db.get_user_files(user_id, limit=1000)
            files_docs = [f for f in files_docs if not any((tg or '').startswith('repo:') for tg in (f.get('tags') or []))]
            items = [f.get('file_name') for f in files_docs if f.get('file_name')]
        else:
            files_docs = db.get_user_files(user_id, limit=1000)
            items = [f.get('file_name') for f in files_docs if f.get('file_name')]

        if not items:
            await query.edit_message_text("❌ לא נמצאו קבצים לקטגוריה שנבחרה")
            return ConversationHandler.END

        # שמור רשימה בזיכרון זמני כדי לאפשר בחירה זריזה
        context.user_data['batch_items'] = items

        # עימוד
        PAGE_SIZE = 10
        total = len(items)
        total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
        if page < 1:
            page = 1
        if page > total_pages:
            page = total_pages
        start = (page - 1) * PAGE_SIZE
        end = min(start + PAGE_SIZE, total)

        keyboard = []
        for idx, name in enumerate(items[start:end], start=start):
            keyboard.append([InlineKeyboardButton(f"📄 {name}", callback_data=f"batch_file:{idx}")])

        # ניווט
        nav = []
        if page > 1:
            nav.append(InlineKeyboardButton("⬅️ הקודם", callback_data=f"batch_files_page_{page-1}"))
        if page < total_pages:
            nav.append(InlineKeyboardButton("➡️ הבא", callback_data=f"batch_files_page_{page+1}"))
        if nav:
            keyboard.append(nav)

        # פעולות
        keyboard.append([InlineKeyboardButton("✅ בחר הכל", callback_data="batch_select_all")])
        keyboard.append([InlineKeyboardButton("🔙 חזור", callback_data="batch_menu")])

        await query.edit_message_text(
            f"בחר/י קובץ לניתוח/בדיקה, או לחץ על 'בחר הכל' כדי לעבד את כל הקבצים ({total}).",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except Exception as e:
        logger.error(f"Error in show_batch_files_menu: {e}")
        await query.edit_message_text("❌ שגיאה בטעינת רשימת קבצים ל-Batch")
    return ConversationHandler.END

async def show_batch_actions_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """תפריט פעולות לאחר בחירת קטגוריה/ריפו"""
    query = update.callback_query
    await query.answer()
    selected = context.user_data.get('batch_selected_files') or []
    count = len(selected)
    keyboard = [
        [InlineKeyboardButton("📊 ניתוח (Analyze)", callback_data="batch_action:analyze")],
        [InlineKeyboardButton("✅ בדיקת תקינות (Validate)", callback_data="batch_action:validate")],
        [InlineKeyboardButton("🔙 חזור לבחירת קבצים", callback_data="batch_back_to_files")],
        [InlineKeyboardButton("🏁 חזרה לתפריט Batch", callback_data="batch_menu")],
    ]
    await query.edit_message_text(
        f"בחר/י פעולה שתתבצע על הקבצים הנבחרים:\n\n" + (f"נבחרו: <b>{count}</b> קבצים" if count else "לא נבחרו קבצים — ניתן לבחור הכל או קובץ בודד"),
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.HTML
    )
    return ConversationHandler.END

async def execute_batch_on_current_selection(update: Update, context: ContextTypes.DEFAULT_TYPE, action: str) -> int:
    """מבצע את פעולת ה-Batch על קבוצת היעד שנבחרה"""
    from database import db
    from batch_processor import batch_processor
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    target = context.user_data.get('batch_target') or {}
    files: List[str] = []
    try:
        # אם יש בחירה מפורשת של קבצים, השתמש בה
        explicit = context.user_data.get('batch_selected_files')
        if explicit:
            files = [f for f in explicit if f]
        else:
            t = target.get('type')
            if t == 'repo':
                tag = target.get('tag')
                items = db.search_code(user_id, query="", tags=[tag], limit=2000)
                files = [f.get('file_name') for f in items if f.get('file_name')]
            elif t == 'zips':
                # ZIPs אינם קבצי קוד; כבר בשלב הבחירה הוצגו הקבצים הרגילים
                items = db.get_user_files(user_id)
                files = [f.get('file_name') for f in items if f.get('file_name')]
            elif t == 'large':
                # שלוף רק קבצים גדולים
                large_files, _ = db.get_user_large_files(user_id, page=1, per_page=10000)
                files = [f.get('file_name') for f in large_files if f.get('file_name')]
            elif t == 'other':
                # קבצים רגילים שאין להם תגית repo:
                items = db.get_user_files(user_id)
                items = [f for f in items if not any((t or '').startswith('repo:') for t in (f.get('tags') or []))]
                files = [f.get('file_name') for f in items if f.get('file_name')]
            else:
                # ברירת מחדל: כל הקבצים רגילים
                items = db.get_user_files(user_id)
                files = [f.get('file_name') for f in items if f.get('file_name')]

        if not files:
            await query.edit_message_text("❌ לא נמצאו קבצים בקבוצה שנבחרה")
            return ConversationHandler.END

        if action == 'analyze':
            job_id = await batch_processor.analyze_files_batch(user_id, files)
            title = "⚡ ניתוח Batch התחיל!"
        else:
            job_id = await batch_processor.validate_files_batch(user_id, files)
            title = "✅ בדיקת תקינות Batch התחילה!"

        keyboard = [[InlineKeyboardButton("📊 בדוק סטטוס", callback_data=f"job_status:{job_id}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            f"{title}\n\n📁 קבצים: {len(files)}\n🆔 Job ID: <code>{job_id}</code>",
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup
        )
    except Exception as e:
        logger.error(f"Error executing batch: {e}")
        await query.edit_message_text("❌ שגיאה בהפעלת Batch")
    return ConversationHandler.END

async def _auto_update_batch_status(application, chat_id: int, message_id: int, job_id: str, user_id: int):
    from batch_processor import batch_processor
    from telegram.constants import ParseMode
    try:
        for _ in range(150):  # עד ~5 דקות, כל 2 שניות
            job = batch_processor.get_job_status(job_id)
            if not job or job.user_id != user_id:
                return
            summary = batch_processor.format_job_summary(job)
            keyboard = []
            if job.status == "completed":
                keyboard.append([InlineKeyboardButton("📋 הצג תוצאות", callback_data=f"job_results:{job_id}")])
                await application.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=f"📊 <b>סטטוס עבודת Batch</b>\n\n🆔 <code>{job_id}</code>\n🔧 <b>פעולה:</b> {job.operation}\n\n{summary}",
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                return
            else:
                await application.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=f"📊 <b>סטטוס עבודת Batch</b>\n\n🆔 <code>{job_id}</code>\n🔧 <b>פעולה:</b> {job.operation}\n\n{summary}",
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 רענן", callback_data=f"job_status:{job_id}")]])
                )
            await asyncio.sleep(2)
    except Exception:
        return