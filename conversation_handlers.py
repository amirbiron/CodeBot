import logging
import os
import re
import asyncio
from io import BytesIO
from datetime import datetime, timezone, timedelta
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
from file_manager import backup_manager
# Reporter מוזרק בזמן ריצה כדי להימנע מפתיחת חיבור בעת import
class _NoopReporter:
    def report_activity(self, user_id):
        return None

reporter = _NoopReporter()

def set_activity_reporter(new_reporter):
    global reporter
    reporter = new_reporter or _NoopReporter()
from utils import get_language_emoji as get_file_emoji
from user_stats import user_stats
from typing import List, Optional, Dict, cast
from html import escape as html_escape
from utils import TelegramUtils, TextUtils
from services import code_service
from i18n.strings_he import MAIN_MENU as MAIN_KEYBOARD
from handlers.pagination import build_pagination_row
from config import config
from urllib.parse import quote_plus

DEFAULT_WEBAPP_URL = "https://code-keeper-webapp.onrender.com"


def _resolve_webapp_base_url() -> Optional[str]:
    candidates = []
    try:
        candidates.append(getattr(config, "WEBAPP_URL", None))
    except Exception:
        candidates.append(None)
    try:
        candidates.append(os.getenv("WEBAPP_URL"))
    except Exception:
        candidates.append(None)
    try:
        candidates.append(getattr(config, "PUBLIC_BASE_URL", None))
    except Exception:
        candidates.append(None)
    candidates.append(DEFAULT_WEBAPP_URL)

    for candidate in candidates:
        if not candidate:
            continue
        base = str(candidate).strip()
        if base:
            return base.rstrip('/')
    return None


def _get_webapp_button_row(file_id: Optional[str], file_name: Optional[str] = None) -> Optional[List[InlineKeyboardButton]]:
    base_url = _resolve_webapp_base_url()
    if not base_url:
        return None
    if file_id:
        target = f"{base_url}/file/{file_id}"
    elif file_name:
        try:
            query = quote_plus(str(file_name))
        except Exception:
            query = str(file_name)
        target = f"{base_url}/files?q={query}#results"
    else:
        target = None
    if not target:
        return None
    try:
        return [InlineKeyboardButton("🌐 צפייה בWebApp", url=target)]
    except TypeError:
        # בסביבות בדיקה ייתכן ש-InlineKeyboardButton אינו תומך בפרמטר url
        return None

async def _safe_edit_message_text(query, text: str, reply_markup=None, parse_mode=None) -> None:
    """עורך הודעה בבטיחות: מתעלם משגיאת 'Message is not modified'."""
    try:
        if parse_mode is None:
            await query.edit_message_text(text=text, reply_markup=reply_markup)
        else:
            await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode=parse_mode)
    except telegram.error.BadRequest as e:
        if "message is not modified" in str(e).lower():
            return
        raise

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

def _format_bytes(num: int) -> str:
    """פורמט נוח לקריאת גדלים"""
    try:
        for unit in ["B", "KB", "MB", "GB"]:
            if num < 1024.0 or unit == "GB":
                return f"{num:.1f} {unit}" if unit != "B" else f"{int(num)} {unit}"
            num /= 1024.0
    except Exception:
        return str(num)
    return str(num)

# הגדרת לוגר
logger = logging.getLogger(__name__)

# הגדרת שלבי השיחה (מועברים למודול משותף)
from handlers.states import GET_CODE, GET_FILENAME, GET_NOTE, EDIT_CODE, EDIT_NAME, WAIT_ADD_CODE_MODE, LONG_COLLECT

# קבועי עימוד
try:
    FILES_PAGE_SIZE = int(getattr(config, 'UI_PAGE_SIZE', 10))
except Exception:
    FILES_PAGE_SIZE = 10

# כפתורי המקלדת הראשית
MAIN_KEYBOARD = [
    ["🗜️ יצירת ZIP", "➕ הוסף קוד חדש"],
    ["📚 הצג את כל הקבצים שלי", "🔧 GitHub"],
    ["⚡ עיבוד Batch", "📥 ייבוא ZIP מריפו"],
    ["☁️ Google Drive", "ℹ️ הסבר על הבוט"]
]

# ה-reporters יוגדרו ב-main בזמן ריצה

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle /start and show the main menu."""
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name
    username = update.effective_user.username
    from database import db
    db.save_user(user_id, username)
    user_stats.log_user(user_id, username)
    # אם המשתמש הגיע עם פרמטר webapp_login — צור ושלח קישור התחברות אישי ל-Web App
    try:
        if context.args and len(context.args) > 0 and str(context.args[0]).strip().lower() == "webapp_login":
            import hashlib, time
            webapp_url = (config.WEBAPP_URL or 'https://code-keeper-webapp.onrender.com')
            timestamp = int(time.time())
            secret = os.getenv('SECRET_KEY', 'dev-secret-key')
            token_data = f"{user_id}:{timestamp}:{secret}"
            auth_token = hashlib.sha256(token_data.encode()).hexdigest()[:32]
            # שמירת הטוקן ב-DB (תוקף 5 דקות)
            try:
                mongo_db = getattr(db, 'db', None)
                if mongo_db is not None:
                    mongo_db.webapp_tokens.insert_one({
                        'token': auth_token,
                        'user_id': user_id,
                        'username': username,
                        'created_at': datetime.now(timezone.utc),
                        'expires_at': datetime.now(timezone.utc) + timedelta(minutes=5),
                    })
            except Exception:
                pass
            login_url = f"{webapp_url}/auth/token?token={auth_token}&user_id={user_id}"
            # יבוא מקומי כדי לאפשר לסטאבים של הטלגרם להיטען גם אם המודול נטען מוקדם יותר בטסטים
            from telegram import InlineKeyboardButton as _IKB, InlineKeyboardMarkup as _IKM
            reply_markup = _IKM([
                [_IKB("🔐 התחבר ל-Web App", url=login_url)],
                [_IKB("🌐 פתח את ה-Web App", url=webapp_url)],
            ])
            await update.message.reply_text(
                "🔐 <b>קישור התחברות אישי ל-Web App</b>\n\n"
                "לחץ על הכפתור למטה כדי להתחבר:\n\n"
                "⚠️ <i>הקישור תקף ל-5 דקות בלבד מטעמי אבטחה</i>",
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML,
            )
            try:
                reporter.report_activity(user_id)
            except Exception:
                pass
            return ConversationHandler.END
    except Exception:
        # אם משהו נכשל ביצירת קישור — נמשיך לזרימת ברירת המחדל
        pass
    safe_user_name = html_escape(user_name) if user_name else ""
    from i18n.strings_he import MESSAGES
    welcome_text = MESSAGES["welcome"].format(name=safe_user_name)
    keyboard = ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
    await update.message.reply_text(welcome_text, reply_markup=keyboard)
    try:
        reporter.report_activity(user_id)
    except Exception:
        pass
    return ConversationHandler.END

HELP_PAGES = [
    (
        "🤖 <b>ברוכים הבאים לבוט ניהול קוד!</b>\n\n"
        "בוט חכם לניהול, גיבוי וארגון קבצי קוד.\n"
        "עובד מצוין עם GitHub ותומך בכל שפות התכנות.\n\n"
        "➕ <b>הוסף קוד</b> - פשוט שלחו קוד והבוט ישמור\n"
        "📚 <b>הצג קבצים</b> - כל הקבצים שלכם מאורגנים\n"
        "⚡ <b>עיבוד Batch</b> - ניתוח אוטומטי של פרויקטים\n"
        "🔧 <b>GitHub</b> - סנכרון וגיבוי אוטומטי\n"
        "🌐 <b>Web App</b> - ממשק דפדפן מתקדם\n\n"
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
        "לחיצה על 📚 פותחת אפשרויות ניהול:\n\n"
        "🔎 <b>חפש קובץ</b> — חיפוש לפי שם/שפה/תגית:\n"
        "• שם: הקלד/י חלק משם הקובץ (למשל: <code>main</code> או <code>utils.py</code>)\n"
        "• שפה: הוסף/י <code>lang:python</code> / <code>lang:js</code> / ...\n"
        "• תגית: הוסף/י <code>tag:repo:owner/name</code> (לפי פרויקט)\n"
        "• שילוב: לדוגמה <code>name:util lang:python</code> או <code>lang:ts tag:repo:org/proj</code>\n\n"
        "🗂 <b>לפי ריפו</b> — קבצים מאורגנים לפי פרויקט\n"
        "📂 <b>קבצים גדולים</b> — תצוגה מדורגת לקבצים ארוכים\n"
        "📁 <b>שאר הקבצים</b> — כל השאר\n"
        "📦 <b>קבצי ZIP</b> — גיבויים/ארכיונים\n\n"
        "<b>לכל קובץ יש תפריט עם:</b>\n"
        "👁️ הצג | ✏️ ערוך | 📝 שנה שם\n"
        "📚 היסטוריה | 📥 הורד | 🗑️ העבר לסל\n\n"
        "<b>טיפ:</b> יש עימוד (10 לעמוד) וגם 'הצג עוד/פחות' בתצוגת קוד"
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
    (
        "🌐 <b>Web App - ממשק ניהול מתקדם!</b>\n\n"
        "גישה לכל הקבצים שלכם דרך הדפדפן!\n\n"
        "<b>מה יש ב-Web App?</b>\n\n"
        "📊 <b>דשבורד אישי</b>\n"
        "• סטטיסטיקות מלאות על הקבצים\n"
        "• גרפים ותרשימים\n"
        "• פעילות אחרונה\n"
        "• שפות פופולריות\n\n"
        "🔍 <b>חיפוש מתקדם</b>\n"
        "• חיפוש לפי שם, תיאור או תגית\n"
        "• סינון לפי שפת תכנות\n"
        "• מיון לפי תאריך, גודל או שם\n\n"
        "👁️ <b>צפייה בקבצים</b>\n"
        "• הדגשת syntax צבעונית\n"
        "• מספרי שורות\n"
        "• העתקה בלחיצה\n"
        "• הורדה ישירה\n\n"
        "<b>איך מתחברים?</b>\n"
        "1. לחצו על 🌐 Web App בתפריט\n"
        "2. התחברו עם Telegram\n"
        "3. זהו! כל הקבצים שלכם זמינים\n\n"
        "🔗 כתובת: code-keeper-webapp.onrender.com"
    ),
    (
        "🚀 <b>חדש ב-WebApp: מערכת סימניות חכמות</b>\n\n"
        "🏷 סימון שורות בקוד + הוספת הערות אישיות.\n\n"
        "<b>איך זה עובד?</b>\n"
        "• לחיצה על מספר שורה → מוסיפה סימנייה אדומה קטנה\n"
        "• לחיצה חוזרת → מסירה אותה\n"
        "• לחיצה על אייקון 🔖 בצד ימין → מציגה את כל הסימניות + ההערות שלך\n\n"
        "<b>קיצורי מקלדת</b>\n"
        "• Ctrl / Cmd + B – הוסף/הסר סימנייה\n"
        "• Ctrl / Cmd + Shift + B – פתח/סגור פאנל סימניות\n"
        "• Escape – סגור את הפאנל\n\n"
        "<b>פעולות עכבר</b>\n"
        "• לחיצה על מספר שורה – הוסף/הסר סימנייה\n"
        "• Shift + Click – הוסף או ערוך הערה\n"
        "• Ctrl / Cmd + Click – מחק סימנייה\n\n"
        "<b>מגבלות</b>\n"
        "• עד 50 סימניות לקובץ\n"
        "• עד 500 למשתמש\n"
        "• עד 500 תווים לכל הערה\n\n"
        "🌐 מופיע אוטומטית בעמוד צפייה בקובץ (view_file.html) ודורש משתמש מחובר."
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

# --- רישום handlers לקטגוריית מועדפים ---
def setup_favorites_category_handlers(application):
    # הוספה בקבוצת עדיפות גבוהה לפני ה-catch-all הכללי, עם fallback כאשר group לא נתמך
    try:
        application.add_handler(CallbackQueryHandler(show_favorites_callback, pattern=r'^show_favorites$'), group=-5)
    except TypeError:
        application.add_handler(CallbackQueryHandler(show_favorites_callback, pattern=r'^show_favorites$'))
    try:
        application.add_handler(CallbackQueryHandler(show_favorites_page_callback, pattern=r'^favorites_page_\d+$'), group=-5)
    except TypeError:
        application.add_handler(CallbackQueryHandler(show_favorites_page_callback, pattern=r'^favorites_page_\d+$'))

# --- Redirect file view/edit handlers to split module implementations ---
from handlers.file_view import (
    handle_file_menu as handle_file_menu,
    handle_view_file as handle_view_file,
    handle_edit_code as handle_edit_code,
    receive_new_code as receive_new_code,
    handle_edit_name as handle_edit_name,
    handle_edit_note as handle_edit_note,
    receive_new_name as receive_new_name,
    handle_versions_history as handle_versions_history,
    handle_download_file as handle_download_file,
    handle_delete_confirmation as handle_delete_confirmation,
    handle_delete_file as handle_delete_file,
    handle_file_info as handle_file_info,
    handle_view_direct_file as handle_view_direct_file,
    handle_edit_code_direct as handle_edit_code_direct,
    handle_edit_name_direct as handle_edit_name_direct,
    handle_edit_note_direct as handle_edit_note_direct,
    handle_clone as handle_clone,
    handle_clone_direct as handle_clone_direct,
)

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
    try:
        reporter.report_activity(update.effective_user.id)
    except Exception:
        pass
    return ConversationHandler.END

async def start_zip_create_flow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """מתחיל מצב יצירת ZIP: המשתמש שולח כמה קבצים ואז לוחץ 'סיום'."""
    # אתחול מצב האיסוף
    context.user_data['upload_mode'] = 'zip_create'
    context.user_data['zip_create_items'] = []
    # כפתורי פעולה
    keyboard = [
        [InlineKeyboardButton("✅ סיום", callback_data="zip_create_finish")],
        [InlineKeyboardButton("❌ ביטול", callback_data="zip_create_cancel")]
    ]
    await update.message.reply_text(
        "🗜️ מצב יצירת ZIP הופעל.\n"
        "שלח/י עכשיו את כל הקבצים שברצונך לכלול.\n"
        "כשתסיים/י, לחצ/י 'סיום' וניצור עבורך ZIP מוכן.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    try:
        reporter.report_activity(update.effective_user.id)
    except Exception:
        pass
    return ConversationHandler.END

async def show_by_repo_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """מציג תפריט קבוצות לפי תגיות ריפו ומאפשר בחירה."""
    from database import db
    user_id = update.effective_user.id
    # שימוש באגרגציה מהירה ב-DB כדי לקבל תגיות ריפו עם ספירה
    tags_with_counts = db.get_repo_tags_with_counts(user_id, max_tags=20)
    if not tags_with_counts:
        await update.message.reply_text("ℹ️ אין קבצים עם תגית ריפו.")
        return ConversationHandler.END
    # בניית מקלדת
    keyboard = []
    for row in tags_with_counts:
        try:
            tag = row.get("tag") if isinstance(row, dict) else None
            cnt = int(row.get("count") or 0) if isinstance(row, dict) else 0
        except Exception:
            tag, cnt = None, 0
        if not tag:
            continue
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
    # שימוש באגרגציה מהירה ב-DB כדי לקבל תגיות ריפו עם ספירה
    tags_with_counts = db.get_repo_tags_with_counts(user_id, max_tags=20)
    if not tags_with_counts:
        await TelegramUtils.safe_edit_message_text(query, "ℹ️ אין קבצים עם תגית ריפו.")
        return ConversationHandler.END
    keyboard = []
    for row in tags_with_counts:
        try:
            tag = row.get("tag") if isinstance(row, dict) else None
            cnt = int(row.get("count") or 0) if isinstance(row, dict) else 0
        except Exception:
            tag, cnt = None, 0
        if not tag:
            continue
        keyboard.append([InlineKeyboardButton(f"{tag} ({cnt})", callback_data=f"by_repo:{tag}")])
    keyboard.append([InlineKeyboardButton("🔙 חזור", callback_data="files")])
    await TelegramUtils.safe_edit_message_text(
        query,
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
        # מסך בחירה: כפתורי ניווט ראשיים
        keyboard = [
            [InlineKeyboardButton("🔎 חפש קובץ", callback_data="search_files")],
            [InlineKeyboardButton("🗂 לפי ריפו", callback_data="by_repo_menu")],
            [InlineKeyboardButton("📦 קבצי ZIP", callback_data="backup_list")],
            [InlineKeyboardButton("📂 קבצים גדולים", callback_data="show_large_files")],
            [InlineKeyboardButton("📁 שאר הקבצים", callback_data="show_regular_files")],
            [InlineKeyboardButton("⭐ מועדפים", callback_data="show_favorites")],
            [InlineKeyboardButton("🗑️ סל מיחזור", callback_data="recycle_bin")],
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
    
    try:
        reporter.report_activity(user_id)
    except Exception:
        pass
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
        from handlers.github.menu import GitHubMenuHandler
        context.bot_data['github_handler'] = GitHubMenuHandler()
    
    # רישום פעילות למעקב סטטיסטיקות ב-MongoDB
    user_stats.log_user(update.effective_user.id, update.effective_user.username)
    
    github_handler = context.bot_data['github_handler']
    await github_handler.github_menu_command(update, context)
    try:
        reporter.report_activity(update.effective_user.id)
    except Exception:
        pass
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
            [InlineKeyboardButton("⭐ מועדפים", callback_data="show_favorites")],
            [InlineKeyboardButton("🗑️ סל מיחזור", callback_data="recycle_bin")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await TelegramUtils.safe_edit_message_text(
            query,
            "בחר/י דרך להצגת הקבצים:",
            reply_markup=reply_markup
        )
        try:
            reporter.report_activity(update.effective_user.id)
        except Exception:
            pass
    except Exception as e:
        # אל תרשום ERROR אם זו רק הודעה שלא השתנתה
        msg = str(e)
        if "message is not modified" not in msg.lower():
            logger.error(f"Error in show_all_files_callback: {e}")
        await TelegramUtils.safe_edit_message_text(query, "❌ שגיאה בטעינת התפריט")
    
    return ConversationHandler.END

async def show_regular_files_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """הצגת קבצים רגילים בלבד"""
    query = update.callback_query
    await query.answer()
    
    # Instead of creating a fake update, adapt show_all_files logic for callback queries
    user_id = update.effective_user.id
    from database import db
    
    try:
        # עימוד אמיתי בצד ה-DB + ללא החזרת תוכן קוד
        files, total_files = db.get_regular_files_paginated(user_id, page=1, per_page=FILES_PAGE_SIZE)
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
            total_pages = (total_files + FILES_PAGE_SIZE - 1) // FILES_PAGE_SIZE if total_files > 0 else 1
            page = 1
            context.user_data['files_last_page'] = page
            context.user_data['files_origin'] = { 'type': 'regular' }
            # אתחול מצב מחיקה מרובה
            context.user_data['rf_multi_delete'] = False
            context.user_data['rf_selected_ids'] = []

            keyboard = []
            context.user_data['files_cache'] = {}
            start_index = 0
            for offset, file in enumerate(files):
                i = start_index + offset
                file_name = file.get('file_name', 'קובץ ללא שם')
                language = file.get('programming_language', 'text')
                context.user_data['files_cache'][str(i)] = file
                emoji = get_file_emoji(language)
                # ⭐ חיווי מועדף — רק אם השם לא ארוך מדי כדי לא לפגוע בקריאות
                try:
                    from database import db as _db
                    is_fav = bool(_db.is_favorite(user_id, file_name))
                except Exception:
                    is_fav = False
                star = "⭐ " if is_fav and len(str(file_name) or "") <= 35 else ""
                button_text = f"{star}{emoji} {file_name}"
                # כפתור כניסה בלבד (ללא כפתור מועדפים ברשימה)
                keyboard.append([InlineKeyboardButton(button_text, callback_data=f"file_{i}")])

            pagination_row = build_pagination_row(page, total_files, FILES_PAGE_SIZE, "files_page_")
            if pagination_row:
                keyboard.append(pagination_row)

            # כפתור העברה מרובה לסל
            keyboard.append([InlineKeyboardButton("🗑️ העברה מרובה לסל", callback_data="rf_multi_start")])
            keyboard.append([InlineKeyboardButton("🔙 חזור", callback_data="files")])
            reply_markup = InlineKeyboardMarkup(keyboard)

            header_text = (
                f"📚 <b>הקבצים השמורים שלך</b> — סה״כ: {total_files}\n"
                f"📄 עמוד {page} מתוך {total_pages}\n\n"
                "✨ לחץ על קובץ לחוויה מלאה של עריכה וניהול:"
            )

            try:
                await query.edit_message_text(
                    header_text,
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.HTML
                )
            except telegram.error.BadRequest as br:
                if "message is not modified" not in str(br).lower():
                    raise
            
        try:
            reporter.report_activity(user_id)
        except Exception:
            pass
        
    except Exception as e:
        logger.error(f"Error in show_regular_files_callback: {e}")
        await query.edit_message_text("❌ שגיאה בטעינת הקבצים")
    
    return ConversationHandler.END

async def show_favorites_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """הצגת מועדפים (רשימת קבצים מסומנים is_favorite=True) עם עימוד קל בצד הבוט.
    משתמש ב-db.get_favorites ומחלק לעמודים בגודל FILES_PAGE_SIZE.
    """
    query = update.callback_query
    try:
        await query.answer("טוען מועדפים…", show_alert=False)
    except Exception:
        pass
    user_id = update.effective_user.id
    from database import db
    try:
        favs = db.get_favorites(user_id, limit=1000) or []
        if not favs:
            await query.edit_message_text(
                "💭 אין לך מועדפים כרגע.\nהוסף בעזרת /favorite &lt;שם&gt; או דרך כפתור ⭐ במסכי הקובץ",
                parse_mode=ParseMode.HTML
            )
            keyboard = [[InlineKeyboardButton("🔙 חזור", callback_data="files")]]
            await query.message.reply_text("🎮 בחר פעולה:", reply_markup=InlineKeyboardMarkup(keyboard))
            return ConversationHandler.END
        # עמוד ראשון
        page = 1
        total_files = len(favs)
        total_pages = (total_files + FILES_PAGE_SIZE - 1) // FILES_PAGE_SIZE
        context.user_data['files_last_page'] = page
        context.user_data['files_origin'] = { 'type': 'favorites' }
        context.user_data['files_cache'] = {}
        start = 0
        end = min(FILES_PAGE_SIZE, total_files)
        keyboard = []
        for i, file in enumerate(favs[start:end], start):
            context.user_data['files_cache'][str(i)] = file
            name = file.get('file_name', 'file')
            lang = file.get('programming_language', 'text')
            emoji = get_file_emoji(lang)
            # כפתור כניסה + כפתור מועדפים ישיר
            try:
                fid = str(file.get('_id') or '')
            except Exception:
                fid = ''
            if fid:
                fav_cb = f"fav_toggle_id:{fid}"
            else:
                fav_cb = f"fav_toggle_tok:{i}"
                tokens_map = context.user_data.get('fav_tokens') or {}
                tokens_map[str(i)] = name
                context.user_data['fav_tokens'] = tokens_map
            # קבע תווית מדויקת לפי המסד (בטוח יותר מהשדה במסמך שמוחזר מהרשימה)
            try:
                from database import db as _db
                is_fav = bool(_db.is_favorite(user_id, name))
            except Exception:
                is_fav = True  # בהקשר 'מועדפים' נניח שזה מועדף
            fav_label = "💔 הסר ממועדפים" if is_fav else "⭐ הוסף למועדפים"
            keyboard.append([
                InlineKeyboardButton(f"{emoji} {name}", callback_data=f"file_{i}"),
                InlineKeyboardButton(fav_label, callback_data=fav_cb)
            ])
        from handlers.pagination import build_pagination_row
        pagination_row = build_pagination_row(page, total_files, FILES_PAGE_SIZE, "favorites_page_")
        if pagination_row:
            keyboard.append(pagination_row)
        # כפתור חזרה לתת־תפריט הקבצים
        keyboard.append([InlineKeyboardButton("🔙 חזור", callback_data="files")])
        header = (
            f"⭐ <b>המועדפים שלך</b> — סה״כ: {total_files}\n"
            f"📄 עמוד {page} מתוך {total_pages}\n\n"
            "✨ לחץ על קובץ להצגה מלאה:"
        )
        try:
            await query.edit_message_text(header, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)
        except telegram.error.BadRequest as br:
            if "message is not modified" in str(br).lower():
                try:
                    from utils import TelegramUtils as _TU
                    await _TU.safe_edit_message_reply_markup(query, reply_markup=InlineKeyboardMarkup(keyboard))
                except Exception:
                    pass
            else:
                raise
    except Exception as e:
        logger.error(f"Error in show_favorites_callback: {e}")
        await query.edit_message_text("❌ שגיאה בטעינת מועדפים")
    return ConversationHandler.END

async def show_favorites_page_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    from database import db
    try:
        favs = db.get_favorites(user_id, limit=1000) or []
        total_files = len(favs)
        if total_files == 0:
            await query.edit_message_text("💭 אין מועדפים להצגה")
            await query.message.reply_text("🎮 בחר פעולה:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 חזור", callback_data="files")]]))
            return ConversationHandler.END
        data = query.data
        try:
            page = int(str(data).split("_")[-1])
        except Exception:
            page = int(context.user_data.get('files_last_page') or 1)
        page = max(1, page)
        total_pages = (total_files + FILES_PAGE_SIZE - 1) // FILES_PAGE_SIZE
        page = min(page, total_pages)
        context.user_data['files_last_page'] = page
        context.user_data['files_origin'] = { 'type': 'favorites' }
        context.user_data['files_cache'] = {}
        start = (page - 1) * FILES_PAGE_SIZE
        end = min(start + FILES_PAGE_SIZE, total_files)
        keyboard = []
        for i, file in enumerate(favs[start:end], start):
            context.user_data['files_cache'][str(i)] = file
            name = file.get('file_name', 'file')
            lang = file.get('programming_language', 'text')
            emoji = get_file_emoji(lang)
            keyboard.append([InlineKeyboardButton(f"{emoji} {name}", callback_data=f"file_{i}")])
        from handlers.pagination import build_pagination_row
        pagination_row = build_pagination_row(page, total_files, FILES_PAGE_SIZE, "favorites_page_")
        if pagination_row:
            keyboard.append(pagination_row)
        keyboard.append([InlineKeyboardButton("🔙 חזור", callback_data="files")])
        header = (
            f"⭐ <b>המועדפים שלך</b> — סה״כ: {total_files}\n"
            f"📄 עמוד {page} מתוך {total_pages}\n\n"
            "✨ לחץ על קובץ להצגה מלאה:"
        )
        await query.edit_message_text(header, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.error(f"Error in show_favorites_page_callback: {e}")
        await query.edit_message_text("❌ שגיאה בטעינת עמוד מועדפים")
    return ConversationHandler.END

async def show_regular_files_page_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """מעבר בין עמודים בתצוגת 'הקבצים השמורים שלך'"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    from database import db
    try:
        # שלוף דף ספציפי מה-DB ללא תוכן קוד (ה-DB כבר מהדק עמוד חוקי במידת הצורך)
        data = query.data
        try:
            requested_page = int(data.split("_")[-1])
        except Exception:
            requested_page = context.user_data.get('files_last_page') or 1
        requested_page = max(1, requested_page)
        files, total_files = db.get_regular_files_paginated(user_id, page=requested_page, per_page=FILES_PAGE_SIZE)
        if total_files == 0:
            # אם אין קבצים, הצג הודעה וכפתור חזרה לתת־התפריט של הקבצים
            await query.edit_message_text(
                "📂 אין לך קבצים שמורים עדיין.\n"
                "✨ לחץ על '➕ הוסף קוד חדש' כדי להתחיל יצירה!"
            )
            reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 חזור", callback_data="files")]])
            await query.message.reply_text("🎮 בחר פעולה:", reply_markup=reply_markup)
            return ConversationHandler.END

        # חישוב מספר העמודים והידוק 'page_used' לעמוד חוקי, תואם לפריטים שחזרו מה-DB
        total_pages = (total_files + FILES_PAGE_SIZE - 1) // FILES_PAGE_SIZE if total_files > 0 else 1
        page_used = min(max(1, requested_page), total_pages)
        context.user_data['files_last_page'] = page_used
        context.user_data['files_origin'] = { 'type': 'regular' }

        # בנה מקלדת לדף המבוקש
        keyboard = []
        multi_on = bool(context.user_data.get('rf_multi_delete'))
        selected_ids = set(context.user_data.get('rf_selected_ids') or [])
        context.user_data['files_cache'] = {}
        start_index = (page_used - 1) * FILES_PAGE_SIZE
        for offset, file in enumerate(files):
            i = start_index + offset
            file_name = file.get('file_name', 'קובץ ללא שם')
            language = file.get('programming_language', 'text')
            emoji = get_file_emoji(language)
            if multi_on:
                file_id = str(file.get('_id') or '')
                checked = "☑️" if file_id in selected_ids else "⬜️"
                button_text = f"{checked} {file_name}"
                keyboard.append([InlineKeyboardButton(button_text, callback_data=f"rf_toggle:{page_used}:{file_id}")])
            else:
                context.user_data['files_cache'][str(i)] = file
                try:
                    from database import db as _db
                    is_fav = bool(_db.is_favorite(user_id, file_name))
                except Exception:
                    is_fav = False
                star = "⭐ " if is_fav and len(str(file_name) or "") <= 35 else ""
                button_text = f"{star}{emoji} {file_name}"
                keyboard.append([InlineKeyboardButton(button_text, callback_data=f"file_{i}")])

        pagination_row = build_pagination_row(page_used, total_files, FILES_PAGE_SIZE, "files_page_")
        if pagination_row:
            keyboard.append(pagination_row)

        if multi_on:
            count_sel = len(selected_ids)
            # כפתורי העברה/ביטול במצב מחיקה מרובה
            keyboard.append([InlineKeyboardButton(f"🗑️ העבר נבחרים לסל ({count_sel})", callback_data="rf_delete_confirm")])
            keyboard.append([InlineKeyboardButton("❌ בטל העברה מרובה", callback_data="rf_multi_cancel")])
            keyboard.append([InlineKeyboardButton("🔙 חזור", callback_data="files")])
        else:
            # כפתור העברה מרובה לסל במצב רגיל
            keyboard.append([InlineKeyboardButton("🗑️ העברה מרובה לסל", callback_data="rf_multi_start")])
            keyboard.append([InlineKeyboardButton("🔙 חזור", callback_data="files")])
        reply_markup = InlineKeyboardMarkup(keyboard)

        header_text = (
            f"📚 <b>הקבצים השמורים שלך</b> — סה״כ: {total_files}\n"
            f"📄 עמוד {page_used} מתוך {total_pages}\n\n"
            "✨ לחץ על קובץ לחוויה מלאה של עריכה וניהול:"
        )

        try:
            await query.edit_message_text(
                header_text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML
            )
        except telegram.error.BadRequest as br:
            if "message is not modified" not in str(br).lower():
                raise
    except Exception as e:
        logger.error(f"Error in show_regular_files_page_callback: {e}")
        await query.edit_message_text("❌ שגיאה בטעינת עמוד הקבצים")
    return ConversationHandler.END

from handlers.save_flow import start_save_flow as start_save_flow
from handlers.save_flow import start_add_code_menu as start_add_code_menu
from handlers.save_flow import start_long_collect as start_long_collect
from handlers.save_flow import long_collect_receive as long_collect_receive
from handlers.save_flow import long_collect_done as long_collect_done

from handlers.save_flow import get_code as get_code

from handlers.save_flow import get_filename as get_filename

from handlers.save_flow import get_note as get_note

from handlers.save_flow import save_file_final as save_file_final

# --- Recycle bin paging constants ---
try:
    RECYCLE_PAGE_SIZE = int(getattr(config, 'UI_PAGE_SIZE', 10))
except Exception:
    RECYCLE_PAGE_SIZE = 10

async def show_recycle_bin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    try:
        await TelegramUtils.safe_answer(query)
    except Exception:
        pass
    try:
        user_id = update.effective_user.id
        data = query.data or "recycle_page_1"
        try:
            page = int(str(data).split("_")[-1]) if str(data).startswith("recycle_page_") else 1
        except Exception:
            page = 1
        from database import db
        page = max(1, page)
        items, total = db._get_repo().list_deleted_files(user_id, page=page, per_page=RECYCLE_PAGE_SIZE)
        total_pages = (total + RECYCLE_PAGE_SIZE - 1) // RECYCLE_PAGE_SIZE if total > 0 else 1
        keyboard = []
        for it in items:
            fid = str(it.get('_id') or '')
            name = it.get('file_name', 'file')
            keyboard.append([
                InlineKeyboardButton(f"♻️ שחזר: {name}", callback_data=f"recycle_restore:{fid}"),
                InlineKeyboardButton("🧨 מחיקה סופית", callback_data=f"recycle_purge:{fid}")
            ])
        nav = []
        if page > 1:
            nav.append(InlineKeyboardButton("⬅️ הקודם", callback_data=f"recycle_page_{page-1}"))
        if page < total_pages:
            nav.append(InlineKeyboardButton("➡️ הבא", callback_data=f"recycle_page_{page+1}"))
        if nav:
            keyboard.append(nav)
        keyboard.append([InlineKeyboardButton("🔙 חזור", callback_data="files")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        header = (
            f"🗑️ <b>סל מיחזור</b> — {total} פריטים\n"
            f"📄 עמוד {page} מתוך {total_pages}"
        )
        await TelegramUtils.safe_edit_message_text(query, header, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.error(f"show_recycle_bin failed: {e}")
        await TelegramUtils.safe_edit_message_text(query, "❌ שגיאה בטעינת סל המיחזור")
    return ConversationHandler.END

async def recycle_restore(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    try:
        await TelegramUtils.safe_answer(query)
    except Exception:
        pass
    try:
        user_id = update.effective_user.id
        fid = (query.data or '').split(':', 1)[-1]
        if not fid:
            await TelegramUtils.safe_answer(query, "בקשה לא תקפה", show_alert=True)
            return ConversationHandler.END
        from database import db
        ok = db._get_repo().restore_file_by_id(user_id, fid)
        if ok:
            await TelegramUtils.safe_answer(query, "♻️ שוחזר", show_alert=False)
        else:
            await TelegramUtils.safe_answer(query, "❌ שגיאת שחזור", show_alert=True)
        return await show_recycle_bin(update, context)
    except Exception as e:
        logger.error(f"recycle_restore failed: {e}")
        await TelegramUtils.safe_edit_message_text(query, "❌ שגיאה בשחזור")
    return ConversationHandler.END

async def recycle_purge(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    try:
        await TelegramUtils.safe_answer(query)
    except Exception:
        pass
    try:
        user_id = update.effective_user.id
        fid = (query.data or '').split(':', 1)[-1]
        if not fid:
            await TelegramUtils.safe_answer(query, "בקשה לא תקפה", show_alert=True)
            return ConversationHandler.END
        from database import db
        ok = db._get_repo().purge_file_by_id(user_id, fid)
        if ok:
            await TelegramUtils.safe_answer(query, "🧨 נמחק לצמיתות", show_alert=False)
        else:
            await TelegramUtils.safe_answer(query, "❌ שגיאת מחיקה סופית", show_alert=True)
        return await show_recycle_bin(update, context)
    except Exception as e:
        logger.error(f"recycle_purge failed: {e}")
        await TelegramUtils.safe_edit_message_text(query, "❌ שגיאה במחיקה סופית")
    return ConversationHandler.END
async def share_single_by_id(update: Update, context: ContextTypes.DEFAULT_TYPE, service: str, file_id: str) -> int:
    """שיתוף קובץ יחיד לפי ObjectId בשירות מבוקש (gist/pastebin)."""
    query = update.callback_query
    await query.answer()
    try:
        from database import db
        from bson import ObjectId
        user_id = update.effective_user.id
        # ודא שהקובץ שייך למשתמש
        doc = db.collection.find_one({"_id": ObjectId(file_id), "user_id": user_id})
        # אם לא נמצא בקולקשן הרגיל, נסה בקבצים גדולים
        is_large = False
        if not doc:
            doc = db.large_files_collection.find_one({"_id": ObjectId(file_id), "user_id": user_id})
            if doc:
                is_large = True
        if not doc:
            # במקום להציג שגיאה שגויה ואז הצלחה, נציג התראה קצרה בלבד ונפסיק
            await query.answer("קובץ לא נמצא", show_alert=False)
            return ConversationHandler.END
        file_name = doc.get('file_name') or 'file.txt'
        code = doc.get('code') or doc.get('content') or doc.get('data') or ''
        language = doc.get('programming_language') or 'text'
        if not code:
            await query.edit_message_text("❌ תוכן הקובץ ריק או חסר")
            return ConversationHandler.END
        from integrations import code_sharing
        if service == 'gist':
            if not config.GITHUB_TOKEN:
                await query.edit_message_text("❌ Gist לא זמין (חסר GITHUB_TOKEN)")
                return ConversationHandler.END
            result = await code_sharing.share_code('gist', file_name, code, language, description=f"שיתוף דרך CodeBot — {file_name}")
            if not result or not result.get('url'):
                await query.edit_message_text("❌ יצירת Gist נכשלה")
                return ConversationHandler.END
            await query.edit_message_text(
                f"🐙 **שותף ב-GitHub Gist!**\n\n📄 `{file_name}`\n🔗 {result['url']}",
                parse_mode=ParseMode.MARKDOWN
            )
        elif service == 'pastebin':
            result = await code_sharing.share_code('pastebin', file_name, code, language, private=True, expire='1M')
            if not result or not result.get('url'):
                await query.edit_message_text("❌ יצירת Pastebin נכשלה")
                return ConversationHandler.END
            await query.edit_message_text(
                f"📋 **שותף ב-Pastebin!**\n\n📄 `{file_name}`\n🔗 {result['url']}",
                parse_mode=ParseMode.MARKDOWN
            )
    except Exception as e:
        logger.error(f"Error in share_single_by_id: {e}")
        await query.edit_message_text("❌ שגיאה בשיתוף הקובץ")
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
        try:
            file_id_str = str(file_data.get('_id') or '')
        except Exception:
            file_id_str = ''
        
        # כפתורים מתקדמים מלאים
        keyboard = [
            [
                InlineKeyboardButton("👁️ הצג קוד", callback_data=f"view_{file_index}"),
                InlineKeyboardButton("✏️ ערוך", callback_data=f"edit_code_{file_index}")
            ],
            [
                InlineKeyboardButton("📝 שנה שם", callback_data=f"edit_name_{file_index}"),
                InlineKeyboardButton("📝 ערוך הערה", callback_data=f"edit_note_{file_index}")
            ],
            [
                InlineKeyboardButton("📚 היסטוריה", callback_data=f"versions_{file_index}"),
                InlineKeyboardButton("📥 הורד", callback_data=f"dl_{file_index}")
            ],
            [
                InlineKeyboardButton("🔗 שתף קוד", callback_data=f"share_menu_idx:{file_index}")
            ],
            [
                InlineKeyboardButton("🔄 שכפול", callback_data=f"clone_{file_index}"),
                InlineKeyboardButton("🗑️ מחק", callback_data=f"del_{file_index}")
            ]
        ]
        webapp_row = _get_webapp_button_row(file_id_str, file_name)
        if webapp_row:
            keyboard.insert(1, webapp_row)

        # כפתור חזרה בהתאם למקור הרשימה (שאר הקבצים/לפי ריפו)
        last_page = context.user_data.get('files_last_page')
        origin = context.user_data.get('files_origin') or {}
        if origin.get('type') == 'by_repo' and origin.get('tag'):
            back_cb = f"by_repo:{origin.get('tag')}"
        elif origin.get('type') == 'regular':
            back_cb = f"files_page_{last_page}" if last_page else "show_regular_files"
        else:
            back_cb = f"files_page_{last_page}" if last_page else "files"
        keyboard.append([InlineKeyboardButton("🔙 חזרה לרשימה", callback_data=back_cb)])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # הוסף הצגת הערה אם קיימת
        note = file_data.get('description') or ''
        if note:
            try:
                safe_note_md = TextUtils.escape_markdown(note, version=1)
            except Exception:
                safe_note_md = str(note).replace('`', '\\`').replace('*', '\\*').replace('_', '\\_')
            note_line = f"\n📝 הערה: {safe_note_md}\n\n"
        else:
            note_line = "\n📝 הערה: —\n\n"
        await TelegramUtils.safe_edit_message_text(
            query,
            f"🎯 *מרכז בקרה מתקדם*\n\n"
            f"📄 **קובץ:** `{file_name}`\n"
            f"🧠 **שפה:** {language}{note_line}"
            f"🎮 בחר פעולה מתקדמת:",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        
    except Exception as e:
        logger.error(f"Error in handle_file_menu: {e}")
        await query.edit_message_text("💥 שגיאה במרכז הבקרה המתקדם")
    
    return ConversationHandler.END

async def handle_view_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """מפנה למימוש המרכזי ב-handlers.file_view כדי לאפשר 'הצג עוד/פחות'."""
    import handlers.file_view as file_view_handlers
    return await file_view_handlers.handle_view_file(update, context)

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
        
        await TelegramUtils.safe_edit_message_text(
            query,
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
        except Exception as log_err:
            logger.debug(f"Failed to log to code_logger: {log_err}")
        
        await query.edit_message_text(
            "❌ שגיאה בהתחלת עריכה\n\n"
            "🔄 אנא נסה שוב או חזור לתפריט הראשי\n"
            "📞 אם הבעיה נמשכת, פנה לתמיכה"
        )
    
    return ConversationHandler.END

async def receive_new_code(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """קבלת הקוד החדש לעריכה"""
    # אם אנו במצב עריכת הערה (description), ננתב לפונקציה יעודית
    if context.user_data.get('editing_note_file'):
        note_text = (update.message.text or '').strip()
        file_name = context.user_data.pop('editing_note_file')
        user_id = update.effective_user.id
        try:
            from database import db
            # שלוף את המסמך האחרון ועדכן תיאור
            doc = db.get_latest_version(user_id, file_name)
            if not doc:
                await update.message.reply_text("❌ הקובץ לא נמצא לעדכון הערה")
                return ConversationHandler.END
            # צור גרסה חדשה עם אותו קוד ושם, עדכון שדה description
            from database import CodeSnippet
            snippet = CodeSnippet(
                user_id=user_id,
                file_name=file_name,
                code=doc.get('code', ''),
                programming_language=doc.get('programming_language', 'text'),
                description=("" if note_text.lower() == 'מחק' else note_text)[:280]
            )
            ok = db.save_code_snippet(snippet)
            if ok:
                await update.message.reply_text(
                    "✅ הערה עודכנה בהצלחה!",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 חזרה", callback_data=f"view_direct_{file_name}")]])
                )
            else:
                await update.message.reply_text("❌ שגיאה בעדכון ההערה")
        except Exception as e:
            logger.error(f"Error updating note: {e}")
            await update.message.reply_text("❌ שגיאה בעדכון ההערה")
        return ConversationHandler.END

    # שחזור טקסט עם סימוני Markdown שנבלעו (אם יש), בהתאם למדיניות השימור
    try:
        new_code = TelegramUtils.extract_message_text_preserve_markdown(update.message)
    except Exception:
        new_code = update.message.text or ''
    
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
            last_version = db.get_latest_version(user_id, file_name)
            version_num = last_version.get('version', 1) if last_version else 1
            try:
                fid = str((last_version or {}).get('_id') or '')
            except Exception:
                fid = ''
            webapp_row = _get_webapp_button_row(fid, file_name)
            keyboard = [
                [
                    InlineKeyboardButton("👁️ הצג קוד מעודכן", callback_data=(f"view_direct_id:{fid}" if fid else f"view_direct_{file_name}")),
                    InlineKeyboardButton("📚 היסטוריה", callback_data=f"versions_file_{file_name}")
                ],
                [
                    InlineKeyboardButton("📥 הורד", callback_data=f"download_direct_{file_name}"),
                    InlineKeyboardButton("🔙 לרשימה", callback_data="files")
                ]
            ]
            if webapp_row:
                keyboard.insert(0, webapp_row)
            reply_markup = InlineKeyboardMarkup(keyboard)
            
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
        except Exception as log_err:
            logger.debug(f"Failed to log to code_logger: {log_err}")
        
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

async def handle_edit_note(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """התחלת עריכת הערה (description) מתצוגת רשימה עם אינדקס"""
    query = update.callback_query
    await query.answer()
    try:
        file_index = query.data.split('_')[2]
        files_cache = context.user_data.get('files_cache', {})
        file_data = files_cache.get(file_index)
        if not file_data:
            await query.edit_message_text("❌ שגיאה בזיהוי הקובץ")
            return ConversationHandler.END
        file_name = file_data.get('file_name', 'קובץ')
        current_note = file_data.get('description', '') or '—'
        # הגדר דגל כדי ש-receive_new_code יעדכן הערה
        context.user_data['editing_note_file'] = file_name
        try:
            safe_current_note = TextUtils.escape_markdown(current_note, version=1)
        except Exception:
            safe_current_note = str(current_note).replace('`', '\\`').replace('*', '\\*').replace('_', '\\_')
        await query.edit_message_text(
            f"📝 *עריכת הערה לקובץ*\n\n"
            f"📄 **שם:** `{file_name}`\n"
            f"🔎 **הערה נוכחית:** {safe_current_note}\n\n"
            f"✏️ שלח/י הערה חדשה (או 'מחק' כדי להסיר)",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 חזרה", callback_data=f"file_{file_index}")]]),
            parse_mode='Markdown'
        )
        return EDIT_CODE
    except Exception as e:
        logger.error(f"Error in handle_edit_note: {e}")
        await query.edit_message_text("❌ שגיאה בהתחלת עריכת הערה")
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
            try:
                latest_doc = db.get_latest_version(user_id, new_name) or {}
                fid = str(latest_doc.get('_id') or '')
            except Exception:
                fid = ''
            webapp_row = _get_webapp_button_row(fid, new_name)
            keyboard = [
                [
                    InlineKeyboardButton("👁️ הצג קוד", callback_data=(f"view_direct_id:{fid}" if fid else f"view_direct_{new_name}")),
                    InlineKeyboardButton("📚 היסטוריה", callback_data=f"versions_file_{new_name}")
                ],
                [
                    InlineKeyboardButton("📥 הורד", callback_data=f"download_direct_{new_name}"),
                    InlineKeyboardButton("🔙 לרשימה", callback_data="files")
                ]
            ]
            if webapp_row:
                keyboard.insert(0, webapp_row)
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
    # שימוש במענה בטוח כדי להתעלם מ-"Query is too old" כשגורם חיצוני מעכב את הטיפול
    await TelegramUtils.safe_answer(query)
    
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
                InlineKeyboardButton("✅ כן, העבר לסל", callback_data=f"confirm_del_{file_index}"),
                InlineKeyboardButton("❌ לא, בטל", callback_data=f"file_{file_index}")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        try:
            _ttl_raw = getattr(config, 'RECYCLE_TTL_DAYS', 7)
            _ttl_days = max(1, int(_ttl_raw))
        except Exception:
            _ttl_days = 7
        await query.edit_message_text(
            f"⚠️ *אישור העברה לסל*\n\n"
            f"📄 **קובץ:** `{file_name}`\n\n"
            f"🗑️ הקובץ יועבר לסל המיחזור. ניתן לשחזר עד {_ttl_days} ימים לפני מחיקה אוטומטית.",
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
            
            try:
                _ttl_raw = getattr(config, 'RECYCLE_TTL_DAYS', 7)
                _ttl_days = max(1, int(_ttl_raw))
            except Exception:
                _ttl_days = 7
            await query.edit_message_text(
                f"✅ *הקובץ הועבר לסל המיחזור!*\n\n"
                f"📄 **קובץ:** `{file_name}`\n"
                f"♻️ ניתן לשחזר מסל המיחזור עד {_ttl_days} ימים.",
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

    

    

    

    

async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """מרכז בקרה מתקדם לכל הכפתורים"""
    query = update.callback_query
    # ה-guard הגלובלי מטופל ב-main.py; אין צורך בבקרת busy כאן

    # מנגנון מונע-כפל ברמת update אחד: אותו callback יכול להיתפס גם ע"י ה-ConversationHandler
    # וגם ע"י ה-catch-all הגלובלי (בקבוצה מאוחרת). כדי למנוע שליחה כפולה של הודעות,
    # נסמן את מזהה ה-update כטופל כבר, ונצא מיד אם הוא נתקל שוב.
    try:
        uid = getattr(update, 'update_id', None)
        # החל מנגנון הכפילות רק כאשר יש update_id תקין (לא None)
        if uid is not None:
            last_handled_uid = context.user_data.get('_last_callback_update_id')
            if last_handled_uid == uid:
                return ConversationHandler.END
            context.user_data['_last_callback_update_id'] = uid
    except Exception:
        # לא לחסום את הזרימה במקרה של חוסר מפתח/טסטים
        pass

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
        elif data.startswith("edit_note_"):
            if data.startswith("edit_note_direct_"):
                return await handle_edit_note_direct(update, context)
            else:
                return await handle_edit_note(update, context)
        elif data.startswith("revert_version_"):
            return await handle_revert_version(update, context)
        elif data.startswith("versions_"):
            return await handle_versions_history(update, context)
        elif data.startswith("dl_") or data.startswith("download_"):
            return await handle_download_file(update, context)
        elif data.startswith("fv_more:"):
            # טעינת עוד טקסט לתצוגת קוד (lazy-load) — תומך גם ב-index וגם ב-direct
            parts = data.split(":")
            # פורמטים נתמכים: fv_more:idx:{index}:{offset} | fv_more:direct:{file_name}:{offset}
            if len(parts) < 4:
                return ConversationHandler.END
            mode = parts[1]
            try:
                chunk_offset = int(parts[3])
            except Exception:
                chunk_offset = 0
            max_length = 3500
            header_text = ""
            code_to_show = ""
            language = "text"
            file_name = "קובץ"
            reply_markup = None
            if mode == "idx":
                file_index = parts[2]
                files_cache = context.user_data.get('files_cache', {})
                file_data = files_cache.get(file_index) or {}
                code = file_data.get('code', '')
                file_name = file_data.get('file_name', 'קובץ')
                language = file_data.get('programming_language', 'text')
                # חישוב קטע הבא
                next_end = min(len(code), chunk_offset + max_length)
                # הגבלת אורך הודעה ל-4096 תווים כולל כותרת ותגיות HTML בסיסיות
                header_len = len(f"📄 <b>{html_escape(file_name)}</b> ({html_escape(language)})\n\n")
                tags_len = len("<pre><code>") + len("</code></pre>")
                safe_code_limit = max(1000, 4096 - header_len - tags_len - 10)
                if next_end <= safe_code_limit:
                    code_to_show = code[:next_end]
                else:
                    # הצג חלון הזזה שמסתיים ב-next_end, עם קידומת אליפסיס
                    prefix = "…\n"
                    available = max(0, safe_code_limit - len(prefix))
                    start_index = max(0, next_end - available)
                    code_to_show = (prefix if start_index > 0 else "") + code[start_index:next_end]
                # בניית מקלדת עם כפתור "הצג עוד" הבא אם יש
                keyboard = []
                # שחזור כפתורי פעולה עיקריים
                keyboard.append([InlineKeyboardButton("✏️ ערוך קוד", callback_data=f"edit_code_{file_index}"), InlineKeyboardButton("📝 ערוך שם", callback_data=f"edit_name_{file_index}")])
                keyboard.append([InlineKeyboardButton("📝 ערוך הערה", callback_data=f"edit_note_{file_index}"), InlineKeyboardButton("📚 היסטוריה", callback_data=f"versions_{file_index}")])
                keyboard.append([InlineKeyboardButton("📥 הורד", callback_data=f"dl_{file_index}"), InlineKeyboardButton("🔄 שכפול", callback_data=f"clone_{file_index}")])
                last_page = context.user_data.get('files_last_page')
                origin = context.user_data.get('files_origin') or {}
                if origin.get('type') == 'by_repo' and origin.get('tag'):
                    back_cb = f"by_repo:{origin.get('tag')}"
                elif origin.get('type') == 'regular':
                    back_cb = f"files_page_{last_page}" if last_page else "show_regular_files"
                else:
                    back_cb = f"files_page_{last_page}" if last_page else f"file_{file_index}"
                if next_end < len(code):
                    next_chunk = code[next_end:next_end + max_length]
                    next_lines = next_chunk.count('\n') or (1 if next_chunk else 0)
                    keyboard.insert(-1, [InlineKeyboardButton(f"הצג עוד {next_lines} שורות ⤵️", callback_data=f"fv_more:idx:{file_index}:{next_end}")])
                if next_end > max_length:
                    prev_chunk = code[max(max_length, next_end - max_length):next_end]
                    prev_lines = prev_chunk.count('\n') or (1 if prev_chunk else 0)
                    keyboard.insert(-1, [InlineKeyboardButton(f"הצג פחות {prev_lines} שורות ⤴️", callback_data=f"fv_less:idx:{file_index}:{next_end}")])
                keyboard.append([InlineKeyboardButton("🔙 חזרה", callback_data=back_cb)])
                reply_markup = InlineKeyboardMarkup(keyboard)
            elif mode == "direct":
                file_name = parts[2]
                user_id = update.effective_user.id
                from database import db
                doc = db.get_latest_version(user_id, file_name)
                is_large_file = False
                if not doc:
                    # נסה large_file
                    doc = db.get_large_file(user_id, file_name) or {}
                    is_large_file = bool(doc)
                    code = doc.get('content', '')
                else:
                    code = doc.get('code', '')
                language = (doc.get('programming_language') if isinstance(doc, dict) else 'text') or 'text'
                next_end = min(len(code), chunk_offset + max_length)
                # הגבלת אורך הודעה ל-4096 תווים כולל כותרת ותגיות HTML
                header_len = len(f"📄 <b>{html_escape(file_name)}</b> ({html_escape(language)})\n\n")
                tags_len = len("<pre><code>") + len("</code></pre>")
                safe_code_limit = max(1000, 4096 - header_len - tags_len - 10)
                if next_end <= safe_code_limit:
                    code_to_show = code[:next_end]
                else:
                    prefix = "…\n"
                    available = max(0, safe_code_limit - len(prefix))
                    start_index = max(0, next_end - available)
                    code_to_show = (prefix if start_index > 0 else "") + code[start_index:next_end]
                # כפתורים לתצוגה ישירה
                keyboard = []
                keyboard.append([InlineKeyboardButton("✏️ ערוך קוד", callback_data=f"edit_code_direct_{file_name}"), InlineKeyboardButton("📝 ערוך שם", callback_data=f"edit_name_direct_{file_name}")])
                keyboard.append([InlineKeyboardButton("📝 ערוך הערה", callback_data=f"edit_note_direct_{file_name}"), InlineKeyboardButton("📚 היסטוריה", callback_data=f"versions_file_{file_name}")])
                keyboard.append([InlineKeyboardButton("📥 הורד", callback_data=f"download_direct_{file_name}"), InlineKeyboardButton("🔄 שכפול", callback_data=f"clone_direct_{file_name}")])
                try:
                    fid = str(doc.get('_id') or '') if isinstance(doc, dict) else ''
                except Exception:
                    fid = ''
                keyboard.append([InlineKeyboardButton("🔗 שתף קוד", callback_data=f"share_menu_id:{fid}") if fid else InlineKeyboardButton("🔗 שתף קוד", callback_data=f"share_menu_id:")])
                keyboard.append([InlineKeyboardButton("🔙 חזרה", callback_data=f"back_after_view:{file_name}")])
                if next_end < len(code):
                    next_chunk = code[next_end:next_end + max_length]
                    next_lines = next_chunk.count('\n') or (1 if next_chunk else 0)
                    keyboard.insert(-2, [InlineKeyboardButton(f"הצג עוד {next_lines} שורות ⤵️", callback_data=f"fv_more:direct:{file_name}:{next_end}")])
                if next_end > max_length:
                    prev_chunk = code[max(max_length, next_end - max_length):next_end]
                    prev_lines = prev_chunk.count('\n') or (1 if prev_chunk else 0)
                    keyboard.insert(-2, [InlineKeyboardButton(f"הצג פחות {prev_lines} שורות ⤴️", callback_data=f"fv_less:direct:{file_name}:{next_end}")])
                reply_markup = InlineKeyboardMarkup(keyboard)
            # רינדור מחדש עם קטע ארוך יותר — HTML אחיד, ואינדיקציה לקובץ גדול במצב direct
            note = ''
            large_note_html = ''
            if mode == 'idx':
                try:
                    note = (file_data.get('description') or '') if isinstance(file_data, dict) else ''
                except Exception:
                    note = ''
            else:
                try:
                    note = (doc.get('description') or '') if isinstance(doc, dict) else ''
                except Exception:
                    note = ''
                try:
                    if 'is_large_file' in locals() and is_large_file:
                        large_note_html = "\n<i>זה קובץ גדול</i>\n"
                except Exception:
                    pass
            note_line = f"\n📝 הערה: {html_escape(note)}\n" if note else "\n"
            safe_code_html = html_escape(code_to_show)
            try:
                await query.edit_message_text(
                    f"📄 <b>{html_escape(file_name)}</b> ({html_escape(language)}){note_line}{large_note_html}\n" +
                    f"<pre><code>{safe_code_html}</code></pre>",
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.HTML
                )
            except telegram.error.BadRequest as br:
                if "message is not modified" not in str(br).lower():
                    raise
        elif data.startswith("fv_less:"):
            # צמצום התצוגה לאחור — מציג פחות שורות
            parts = data.split(":")
            if len(parts) < 4:
                return ConversationHandler.END
            mode = parts[1]
            try:
                current_end = int(parts[3])
            except Exception:
                current_end = 0
            max_length = 3500
            prev_end = max(max_length, current_end - max_length)
            code_to_show = ""
            language = "text"
            file_name = "קובץ"
            reply_markup = None
            if mode == "idx":
                file_index = parts[2]
                files_cache = context.user_data.get('files_cache', {})
                file_data = files_cache.get(file_index) or {}
                code = file_data.get('code', '')
                file_name = file_data.get('file_name', 'קובץ')
                language = file_data.get('programming_language', 'text')
                # הגבלת אורך הודעה ל-4096 תווים כולל כותרת ותגיות HTML
                header_len = len(f"📄 <b>{html_escape(file_name)}</b> ({html_escape(language)})\n\n")
                tags_len = len("<pre><code>") + len("</code></pre>")
                safe_code_limit = max(1000, 4096 - header_len - tags_len - 10)
                if prev_end <= safe_code_limit:
                    code_to_show = code[:prev_end]
                else:
                    prefix = "…\n"
                    available = max(0, safe_code_limit - len(prefix))
                    start_index = max(0, prev_end - available)
                    code_to_show = (prefix if start_index > 0 else "") + code[start_index:prev_end]
                keyboard = []
                keyboard.append([InlineKeyboardButton("✏️ ערוך קוד", callback_data=f"edit_code_{file_index}"), InlineKeyboardButton("📝 ערוך שם", callback_data=f"edit_name_{file_index}")])
                keyboard.append([InlineKeyboardButton("📝 ערוך הערה", callback_data=f"edit_note_{file_index}"), InlineKeyboardButton("📚 היסטוריה", callback_data=f"versions_{file_index}")])
                keyboard.append([InlineKeyboardButton("📥 הורד", callback_data=f"dl_{file_index}"), InlineKeyboardButton("🔄 שכפול", callback_data=f"clone_{file_index}")])
                last_page = context.user_data.get('files_last_page')
                origin = context.user_data.get('files_origin') or {}
                if origin.get('type') == 'by_repo' and origin.get('tag'):
                    back_cb = f"by_repo:{origin.get('tag')}"
                elif origin.get('type') == 'regular':
                    back_cb = f"files_page_{last_page}" if last_page else "show_regular_files"
                else:
                    back_cb = f"files_page_{last_page}" if last_page else f"file_{file_index}"
                # כפתורי עוד/פחות בהתאם לשוליים
                if prev_end < len(code):
                    next_chunk = code[prev_end:prev_end + max_length]
                    next_lines = next_chunk.count('\n') or (1 if next_chunk else 0)
                    keyboard.insert(-1, [InlineKeyboardButton(f"הצג עוד {next_lines} שורות ⤵️", callback_data=f"fv_more:idx:{file_index}:{prev_end}")])
                if prev_end > max_length:
                    prev_chunk2 = code[max(max_length, prev_end - max_length):prev_end]
                    prev_lines2 = prev_chunk2.count('\n') or (1 if prev_chunk2 else 0)
                    keyboard.insert(-1, [InlineKeyboardButton(f"הצג פחות {prev_lines2} שורות ⤴️", callback_data=f"fv_less:idx:{file_index}:{prev_end}")])
                keyboard.append([InlineKeyboardButton("🔙 חזרה", callback_data=back_cb)])
                reply_markup = InlineKeyboardMarkup(keyboard)
            elif mode == "direct":
                file_name = parts[2]
                user_id = update.effective_user.id
                from database import db
                doc = db.get_latest_version(user_id, file_name)
                is_large_file = False
                if not doc:
                    doc = db.get_large_file(user_id, file_name) or {}
                    is_large_file = bool(doc)
                    code = doc.get('content', '')
                else:
                    code = doc.get('code', '')
                language = (doc.get('programming_language') if isinstance(doc, dict) else 'text') or 'text'
                # הגבלת אורך הודעה ל-4096 תווים כולל כותרת ותגיות HTML
                header_len = len(f"📄 <b>{html_escape(file_name)}</b> ({html_escape(language)})\n\n")
                tags_len = len("<pre><code>") + len("</code></pre>")
                safe_code_limit = max(1000, 4096 - header_len - tags_len - 10)
                if prev_end <= safe_code_limit:
                    code_to_show = code[:prev_end]
                else:
                    prefix = "…\n"
                    available = max(0, safe_code_limit - len(prefix))
                    start_index = max(0, prev_end - available)
                    code_to_show = (prefix if start_index > 0 else "") + code[start_index:prev_end]
                keyboard = []
                keyboard.append([InlineKeyboardButton("✏️ ערוך קוד", callback_data=f"edit_code_direct_{file_name}"), InlineKeyboardButton("📝 ערוך שם", callback_data=f"edit_name_direct_{file_name}")])
                keyboard.append([InlineKeyboardButton("📝 ערוך הערה", callback_data=f"edit_note_direct_{file_name}"), InlineKeyboardButton("📚 היסטוריה", callback_data=f"versions_file_{file_name}")])
                keyboard.append([InlineKeyboardButton("📥 הורד", callback_data=f"download_direct_{file_name}"), InlineKeyboardButton("🔄 שכפול", callback_data=f"clone_direct_{file_name}")])
                try:
                    fid = str(doc.get('_id') or '') if isinstance(doc, dict) else ''
                except Exception:
                    fid = ''
                keyboard.append([InlineKeyboardButton("🔗 שתף קוד", callback_data=f"share_menu_id:{fid}") if fid else InlineKeyboardButton("🔗 שתף קוד", callback_data=f"share_menu_id:")])
                if prev_end < len(code):
                    next_chunk = code[prev_end:prev_end + max_length]
                    next_lines = next_chunk.count('\n') or (1 if next_chunk else 0)
                    keyboard.insert(-1, [InlineKeyboardButton(f"הצג עוד {next_lines} שורות ⤵️", callback_data=f"fv_more:direct:{file_name}:{prev_end}")])
                if prev_end > max_length:
                    prev_chunk2 = code[max(max_length, prev_end - max_length):prev_end]
                    prev_lines2 = prev_chunk2.count('\n') or (1 if prev_chunk2 else 0)
                    keyboard.insert(-1, [InlineKeyboardButton(f"הצג פחות {prev_lines2} שורות ⤴️", callback_data=f"fv_less:direct:{file_name}:{prev_end}")])
                keyboard.append([InlineKeyboardButton("🔙 חזרה", callback_data=f"back_after_view:{file_name}")])
                reply_markup = InlineKeyboardMarkup(keyboard)
            # רינדור מחדש עם קטע קצר יותר — HTML אחיד, ואינדיקציה לקובץ גדול במצב direct
            note = ''
            large_note_html = ''
            if mode == 'idx':
                try:
                    note = (file_data.get('description') or '') if isinstance(file_data, dict) else ''
                except Exception:
                    note = ''
            else:
                try:
                    note = (doc.get('description') or '') if isinstance(doc, dict) else ''
                except Exception:
                    note = ''
                try:
                    if 'is_large_file' in locals() and is_large_file:
                        large_note_html = "\n<i>זה קובץ גדול</i>\n"
                except Exception:
                    pass
            note_line = f"\n📝 הערה: {html_escape(note)}\n" if note else "\n"
            safe_code_html = html_escape(code_to_show)
            try:
                await query.edit_message_text(
                    f"📄 <b>{html_escape(file_name)}</b> ({html_escape(language)}){note_line}{large_note_html}\n" +
                    f"<pre><code>{safe_code_html}</code></pre>",
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.HTML
                )
            except telegram.error.BadRequest as br:
                if "message is not modified" not in str(br).lower():
                    raise
        elif data.startswith("clone_"):
            if data.startswith("clone_direct_"):
                return await handle_clone_direct(update, context)
            else:
                return await handle_clone(update, context)
        elif data.startswith("back_after_view:"):
            # חזרה למסך ההצלחה לאחר צפייה בקוד שנשמר זה עתה
            try:
                file_name = data.split(":", 1)[1]
            except Exception:
                file_name = ''
            saved = context.user_data.get('last_save_success') or {}
            fallback_to_db = not bool(saved)
            # ננסה לעדכן מהמסד אם חסר
            if fallback_to_db:
                try:
                    from database import db
                    doc = db.get_latest_version(update.effective_user.id, file_name)
                    saved = {
                        'file_name': file_name or (doc.get('file_name') if doc else ''),
                        'language': (doc.get('programming_language') if doc else 'text'),
                        'note': (doc.get('description') if doc else ''),
                        'file_id': str(doc.get('_id') or '') if doc else ''
                    }
                except Exception:
                    saved = {'file_name': file_name, 'language': 'text', 'note': '', 'file_id': ''}
            # בנה מקלדת כמו בהודעת ההצלחה לאחר שמירה
            fname = saved.get('file_name') or file_name or 'file.txt'
            lang = saved.get('language') or 'text'
            note = saved.get('note') or ''
            fid = saved.get('file_id') or ''
            view_fid = fid if not fallback_to_db else ''
            note_btn_text = "📝 ערוך הערה" if note else "📝 הוסף הערה"
            keyboard = [
                [
                    InlineKeyboardButton("👁️ הצג קוד", callback_data=(f"view_direct_id:{view_fid}" if view_fid else f"view_direct_{fname}")),
                    InlineKeyboardButton("✏️ ערוך", callback_data=f"edit_code_direct_{fname}")
                ],
                [
                    InlineKeyboardButton("📝 שנה שם", callback_data=f"edit_name_direct_{fname}"),
                    InlineKeyboardButton(note_btn_text, callback_data=f"edit_note_direct_{fname}")
                ],
                [
                    InlineKeyboardButton("📚 היסטוריה", callback_data=f"versions_file_{fname}"),
                    InlineKeyboardButton("📥 הורד", callback_data=f"download_direct_{fname}")
                ],
                [
                    InlineKeyboardButton("🗑️ מחק", callback_data=f"delete_direct_{fname}")
                ],
                [
                    InlineKeyboardButton("🔗 שתף קוד", callback_data=f"share_menu_id:{fid}") if fid else InlineKeyboardButton("🔗 שתף קוד", callback_data=f"share_menu_id:")
                ],
                [
                    InlineKeyboardButton("🔙 לרשימה", callback_data="files")
                ]
            ]
            webapp_row = _get_webapp_button_row(fid, fname)
            if webapp_row:
                keyboard.insert(1, webapp_row)
            reply_markup = InlineKeyboardMarkup(keyboard)
            note_display = note if note else '—'
            try:
                await query.edit_message_text(
                    f"🎉 *קובץ נשמר בהצלחה!*\n\n"
                    f"📄 **שם:** `{fname}`\n"
                    f"🧠 **שפה זוהתה:** {lang}\n"
                    f"📝 **הערה:** {note_display}\n\n"
                    f"🎮 בחר פעולה מהכפתורים החכמים:",
                    reply_markup=reply_markup,
                    parse_mode='Markdown'
                )
            except Exception:
                await query.edit_message_text("🎉 קובץ נשמר בהצלחה!", reply_markup=reply_markup)
            return ConversationHandler.END
        elif data.startswith("share_menu_id:"):
            # תפריט שיתוף לפי ObjectId
            fid = data.split(":", 1)[1]
            kb = [
                [
                    InlineKeyboardButton("🐙 GitHub Gist", callback_data=f"share_gist_id:{fid}"),
                    InlineKeyboardButton("📋 Pastebin", callback_data=f"share_pastebin_id:{fid}")
                ],
                [InlineKeyboardButton("❌ ביטול", callback_data="cancel_share")]
            ]
            await TelegramUtils.safe_edit_message_reply_markup(query, reply_markup=InlineKeyboardMarkup(kb))
            return ConversationHandler.END
        elif data.startswith("share_gist_id:"):
            fid = data.split(":", 1)[1]
            return await share_single_by_id(update, context, service="gist", file_id=fid)
        elif data.startswith("share_pastebin_id:"):
            fid = data.split(":", 1)[1]
            return await share_single_by_id(update, context, service="pastebin", file_id=fid)
        elif data.startswith("share_menu_idx:"):
            # תפריט שתף לפי אינדקס קובץ מה-cache
            idx = data.split(":", 1)[1]
            files_cache = context.user_data.get('files_cache', {})
            file_data = files_cache.get(idx)
            if not file_data:
                await query.answer("קובץ לא נמצא", show_alert=True)
                return ConversationHandler.END
            fid = str(file_data.get('_id') or '')
            if not fid:
                await query.answer("קובץ לא תקין", show_alert=True)
                return ConversationHandler.END
            kb = [
                [
                    InlineKeyboardButton("🐙 GitHub Gist", callback_data=f"share_gist_id:{fid}"),
                    InlineKeyboardButton("📋 Pastebin", callback_data=f"share_pastebin_id:{fid}")
                ],
                [InlineKeyboardButton("❌ ביטול", callback_data="cancel_share")]
            ]
            await TelegramUtils.safe_edit_message_reply_markup(query, reply_markup=InlineKeyboardMarkup(kb))
            return ConversationHandler.END
        elif data.startswith("del_") or data.startswith("delete_"):
            return await handle_delete_confirmation(update, context)
        elif data.startswith("confirm_del_"):
            return await handle_delete_file(update, context)
        elif data.startswith("info_"):
            return await handle_file_info(update, context)
        elif data == "files" or data == "refresh_files":
            return await show_all_files_callback(update, context)
        elif data == "recycle_bin":
            return await show_recycle_bin(update, context)
        elif data.startswith("recycle_page_"):
            return await show_recycle_bin(update, context)
        elif data.startswith("recycle_restore:"):
            return await recycle_restore(update, context)
        elif data.startswith("recycle_purge:"):
            return await recycle_purge(update, context)
        elif data == "by_repo_menu":
            return await show_by_repo_menu_callback(update, context)
        elif data == "add_code_regular":
            # מעבר לזרימת "קוד רגיל" הקיימת - נשלח הודעה חדשה כמו start_save_flow
            await query.answer()
            # הסתרת תת-התפריט כדי למנוע בלבול
            try:
                await query.edit_message_text("✨ מצב הוספת קוד רגיל")
            except Exception:
                pass
            return await start_save_flow(update, context)
        elif data == "add_code_long":
            # כניסה למצב איסוף קוד ארוך
            return await start_long_collect(update, context)
        elif data.startswith("files_page_"):
            return await show_regular_files_page_callback(update, context)
        elif data == "rf_multi_start":
            # כניסה למצב מחיקה מרובה
            context.user_data['rf_multi_delete'] = True
            context.user_data.setdefault('rf_selected_ids', [])
            return await show_regular_files_page_callback(update, context)
        elif data == "rf_multi_cancel":
            # יציאה ממצב מחיקה מרובה
            context.user_data['rf_multi_delete'] = False
            context.user_data['rf_selected_ids'] = []
            return await show_regular_files_page_callback(update, context)
        elif data.startswith("rf_toggle:"):
            # פורמט: rf_toggle:<page>:<file_id>
            parts = data.split(":", 2)
            try:
                page = int(parts[1])
            except Exception:
                page = context.user_data.get('files_last_page') or 1
            file_id = parts[2] if len(parts) > 2 else ''
            selected = set(context.user_data.get('rf_selected_ids') or [])
            if file_id in selected:
                selected.remove(file_id)
            else:
                if file_id:
                    selected.add(file_id)
            context.user_data['rf_selected_ids'] = list(selected)
            context.user_data['rf_multi_delete'] = True
            context.user_data['files_last_page'] = page
            return await show_regular_files_page_callback(update, context)
        elif data == "rf_delete_confirm":
            # הודעת אימות ראשונה למחיקה מרובה
            user_id = update.effective_user.id
            selected_ids: List[str] = list(context.user_data.get('rf_selected_ids') or [])
            count_sel = len(selected_ids)
            if count_sel == 0:
                await query.answer("לא נבחרו קבצים", show_alert=True)
                return ConversationHandler.END
            last_page = context.user_data.get('files_last_page') or 1
            try:
                _ttl_raw = getattr(config, 'RECYCLE_TTL_DAYS', 7)
                _ttl_days = max(1, int(_ttl_raw))
            except Exception:
                _ttl_days = 7
            warn = (
                f"⚠️ עומד/ת להעביר <b>{count_sel}</b> קבצים לסל המיחזור.\n"
                f"הקבצים יהיו ניתנים לשחזור עד {_ttl_days} ימים, ולאחר מכן יימחקו אוטומטית.\n"
                "אין שום פעולה מול GitHub, ולא נמחקים קבצי ZIP/גדולים.\n\n"
                "אם זה בטעות, חזור/י אחורה."
            )
            kb = [
                [InlineKeyboardButton("✅ אני מאשר/ת", callback_data="rf_delete_double_confirm")],
                [InlineKeyboardButton("🔙 חזרה", callback_data=f"files_page_{last_page}")],
            ]
            await query.edit_message_text(warn, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML)
        elif data == "rf_delete_double_confirm":
            # אישור שני
            last_page = context.user_data.get('files_last_page') or 1
            try:
                _ttl_raw = getattr(config, 'RECYCLE_TTL_DAYS', 7)
                _ttl_days = max(1, int(_ttl_raw))
            except Exception:
                _ttl_days = 7
            text2 = (
                "🧨 אישור סופי להעברה לסל\n"
                f"הקבצים יועברו לסל המיחזור ויישארו לשחזור עד {_ttl_days} ימים.\n"
                "אין שום פעולה מול GitHub, ולא נמחקים קבצי ZIP/גדולים.\n"
            )
            kb = [
                [InlineKeyboardButton("🧨 כן, העבר לסל", callback_data="rf_delete_do")],
                [InlineKeyboardButton("🔙 בטל", callback_data=f"files_page_{last_page}")],
            ]
            await query.edit_message_text(text2, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML)
        elif data == "rf_delete_do":
            # מחיקה בפועל לפי מזהי קבצים
            from database import db
            user_id = update.effective_user.id
            selected_ids: List[str] = list(context.user_data.get('rf_selected_ids') or [])
            deleted = 0
            for fid in selected_ids:
                try:
                    res = db.delete_file_by_id(fid)
                    if res:
                        deleted += 1
                except Exception:
                    continue
            # רענון רשימת הקבצים ושחזור מצב רגיל (דף עדכני) ישירות מה-DB
            try:
                last_page = context.user_data.get('files_last_page') or 1
                files, total_files = db.get_regular_files_paginated(user_id, page=last_page, per_page=FILES_PAGE_SIZE)
            except Exception:
                files, total_files = [], 0
            context.user_data['rf_selected_ids'] = []
            context.user_data['rf_multi_delete'] = False
            # עדכן עמוד אחרון בהתאם לסה"כ אחרי מחיקה
            total_pages = (total_files + FILES_PAGE_SIZE - 1) // FILES_PAGE_SIZE if total_files > 0 else 1
            last_page = context.user_data.get('files_last_page') or 1
            if last_page > total_pages:
                last_page = total_pages or 1
            context.user_data['files_last_page'] = last_page
            try:
                _ttl_raw = getattr(config, 'RECYCLE_TTL_DAYS', 7)
                _ttl_days = max(1, int(_ttl_raw))
            except Exception:
                _ttl_days = 7
            msg = (
                f"✅ הועברו לסל {deleted} קבצים.\n"
                f"♻️ ניתן לשחזר מסל המיחזור עד {_ttl_days} ימים."
            )
            kb = [
                [InlineKeyboardButton("🔙 חזור לשאר הקבצים", callback_data=f"files_page_{last_page}")],
                [InlineKeyboardButton("🏠 תפריט ראשי", callback_data="main")],
            ]
            await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb))
            return ConversationHandler.END
        elif data == "main" or data == "main_menu":
            await query.edit_message_text("🏠 חוזר לבית החכם:")
            await query.message.reply_text(
                "🎮 בחר פעולה מתקדמת:",
                reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
            )
            return ConversationHandler.END
        elif data == "cancel":
            # ביטול כללי דרך כפתור
            # ביטול טיימאאוט אם קיים
            try:
                job = context.user_data.get('long_collect_job')
                if job:
                    job.schedule_removal()
            except Exception:
                pass
            context.user_data.clear()
            await query.edit_message_text("🚫 התהליך בוטל בהצלחה!")
            await query.message.reply_text(
                "🎮 בחר פעולה מתקדמת:",
                reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
            )
            return ConversationHandler.END
        elif data == "zip_create_cancel":
            # ביטול מצב יצירת ZIP בלבד
            context.user_data.pop('upload_mode', None)
            context.user_data.pop('zip_create_items', None)
            await query.edit_message_text("🚫 יצירת ה‑ZIP בוטלה.")
            await query.message.reply_text(
                "🎮 בחר פעולה מתקדמת:",
                reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
            )
            return ConversationHandler.END
        elif data == "zip_create_finish":
            # בניית ZIP מהקבצים שנאספו ושליחה למשתמש
            try:
                items = context.user_data.get('zip_create_items') or []
                if not items:
                    await query.edit_message_text("ℹ️ לא נאספו קבצים. שלח/י קבצים ואז נסה שוב.")
                    return ConversationHandler.END
                from io import BytesIO as _BytesIO
                import zipfile as _zip
                buf = _BytesIO()
                with _zip.ZipFile(buf, 'w', compression=_zip.ZIP_DEFLATED) as z:
                    for it in items:
                        # it: {"filename": str, "bytes": bytes}
                        try:
                            z.writestr(it.get('filename') or 'file', it.get('bytes') or b'')
                        except Exception:
                            pass
                buf.seek(0)
                safe_name = f"my-files-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.zip"
                await query.message.reply_document(document=buf, filename=safe_name)
                await query.edit_message_text(f"✅ נוצר ZIP עם {len(items)} קבצים ונשלח אליך.")
            except Exception as e:
                logger.exception(f"zip_create_finish failed: {e}")
                await query.edit_message_text(f"❌ שגיאה ביצירת ה‑ZIP: {e}")
            finally:
                context.user_data.pop('upload_mode', None)
                context.user_data.pop('zip_create_items', None)
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
                # משוך רק שמות קבצים בהקרנה קלה כדי לחסוך בזיכרון
                all_files = db.get_user_files(user_id, limit=500, projection={"file_name": 1})
                files = [f['file_name'] for f in all_files if f.get('file_name')]
            else:
                language = language_map[data]
                all_files = db.get_user_files(user_id, limit=500, projection={"file_name": 1, "programming_language": 1})
                files = [f['file_name'] for f in all_files if str(f.get('programming_language', '')).lower() == language and f.get('file_name')]
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
            all_files = db.get_user_files(user_id, limit=500, projection={"file_name": 1})
            files = [f['file_name'] for f in all_files if f.get('file_name')]
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
            return await show_batch_zips_menu(update, context, page=1)
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
        elif data.startswith("batch_zip_page_"):
            try:
                p = int(data.split("_")[-1])
            except Exception:
                p = 1
            return await show_batch_zips_menu(update, context, page=p)
        elif data.startswith("batch_zip_download_id:"):
            backup_id = data.split(":", 1)[1]
            try:
                info_list = backup_manager.list_backups(update.effective_user.id)
                match = next((b for b in info_list if b.backup_id == backup_id), None)
                if not match or not match.file_path or not os.path.exists(match.file_path):
                    await query.answer("❌ הגיבוי לא נמצא בדיסק", show_alert=True)
                else:
                    with open(match.file_path, 'rb') as fh:
                        await query.message.reply_document(
                            document=fh,
                            filename=os.path.basename(match.file_path),
                            caption=f"📦 {backup_id} — {_format_bytes(os.path.getsize(match.file_path))}"
                        )
                return ConversationHandler.END
            except Exception:
                await query.answer("❌ שגיאה בהורדה", show_alert=True)
                return ConversationHandler.END
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
            # הצגת קבצים לפי תגית ריפו + אפשרות מחיקה מרוכזת, עם עימוד
            tag = data.split(":", 1)[1]
            context.user_data['files_origin'] = { 'type': 'by_repo', 'tag': tag }
            from database import db
            user_id = update.effective_user.id
            files, total = db.get_user_files_by_repo(user_id, tag, page=1, per_page=FILES_PAGE_SIZE)
            if not files:
                await query.edit_message_text("ℹ️ אין קבצים עבור התגית הזו.")
                return ConversationHandler.END
            # נשמור את מספר העמוד הנוכחי עבור ניווט חזרה
            context.user_data['files_last_page'] = 1
            keyboard = []
            context.user_data['files_cache'] = {}
            start_index = 0
            for offset, f in enumerate(files):
                i = start_index + offset
                name = f.get('file_name', 'ללא שם')
                language = f.get('programming_language', 'text')
                emoji = get_file_emoji(language)
                button_text = f"{emoji} {name}"
                keyboard.append([InlineKeyboardButton(button_text, callback_data=f"file_{i}")])
                context.user_data['files_cache'][str(i)] = f
            # שורת עימוד
            pagination_row = build_pagination_row(1, total, FILES_PAGE_SIZE, f"by_repo_page:{tag}:")
            if pagination_row:
                keyboard.append(pagination_row)
            # פעולת העברה לריפו הנוכחי לסל המיחזור
            keyboard.append([InlineKeyboardButton("🗑️ העבר את כל הריפו לסל", callback_data=f"byrepo_delete_confirm:{tag}")])
            keyboard.append([InlineKeyboardButton("🔙 חזור", callback_data="back_to_repo_menu")])
            keyboard.append([InlineKeyboardButton("🏠 תפריט ראשי", callback_data="main")])
            await query.edit_message_text(
                f"📂 קבצים עם {tag}:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        elif data == "search_files":
            # מעבר למצב חיפוש: בקשת שאילתא מהמשתמש
            context.user_data['search_ctx'] = {'mode': 'all_files'}
            kb = [[InlineKeyboardButton("🔙 חזרה", callback_data="files")]]
            await query.edit_message_text(
                "🔎 *חיפוש קבצים*\n\n"
                "הקלד/י אחת מהאפשרויות:\n"
                "• שם קובץ או חלק ממנו (לדוגמה: main.py או main)\n"
                "• תגית עם קידומת repo:owner/name\n"
                "• שפה (לדוגמה: python, js)\n"
                "או שילוב: name:util lang:python tag:repo:me/project",
                reply_markup=InlineKeyboardMarkup(kb),
                parse_mode=ParseMode.MARKDOWN
            )
            # סמן שמחכים לטקסט חיפוש
            context.user_data['awaiting_search_text'] = True
        elif data.startswith("byrepo_delete_confirm:"):
            # שלב אישור ראשון למחיקת כל הקבצים תחת תגית ריפו
            tag = data.split(":", 1)[1]
            from database import db
            user_id = update.effective_user.id
            files = db.search_code(user_id, query="", tags=[tag] if tag else [], limit=10000) or []
            total = len(files)
            try:
                _ttl_raw = getattr(config, 'RECYCLE_TTL_DAYS', 7)
                _ttl_days = max(1, int(_ttl_raw))
            except Exception:
                _ttl_days = 7
            warn_text = (
                f"⚠️ עומד/ת להעביר <b>{total}</b> קבצים של <code>{tag}</code> לסל המיחזור.\n"
                f"הקבצים יהיו ניתנים לשחזור עד {_ttl_days} ימים, ולאחר מכן יימחקו אוטומטית.\n"
                "אין שום פעולה מול GitHub, ולא נמחקים קבצי ZIP/גדולים.\n\n"
                "אם זה בטעות, חזור/י אחורה."
            )
            kb = [
                [InlineKeyboardButton("✅ אני מאשר/ת", callback_data=f"byrepo_delete_double_confirm:{tag}")],
                [InlineKeyboardButton("🔙 חזרה", callback_data=f"by_repo:{tag}")],
            ]
            await query.edit_message_text(warn_text, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML)
        elif data.startswith("byrepo_delete_double_confirm:"):
            # שלב אישור שני
            tag = data.split(":", 1)[1]
            try:
                _ttl_raw = getattr(config, 'RECYCLE_TTL_DAYS', 7)
                _ttl_days = max(1, int(_ttl_raw))
            except Exception:
                _ttl_days = 7
            text2 = (
                "🧨 אישור סופי להעברה לסל\n"
                f"כל הקבצים תחת <code>{tag}</code> יועברו לסל המיחזור ויישארו לשחזור עד {_ttl_days} ימים.\n"
                "אין שום פעולה מול GitHub, ולא נמחקים קבצי ZIP/גדולים.\n"
            )
            kb = [
                [InlineKeyboardButton("🧨 כן, העבר לסל", callback_data=f"byrepo_delete_do:{tag}")],
                [InlineKeyboardButton("🔙 בטל", callback_data=f"by_repo:{tag}")],
            ]
            await query.edit_message_text(text2, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML)
        elif data.startswith("by_repo_page:"):
            # עימוד קבצים לפי תגית ריפו: תבנית callback "by_repo_page:{tag}:{page}"
            parts = data.split(":")
            # צורה אפשרית: ["by_repo_page", "repo", "me/app", "2"] או ["by_repo_page","repo:me/app","2"]
            if len(parts) < 3:
                return ConversationHandler.END
            try:
                page = int(parts[-1])
            except Exception:
                page = 1
            # התגית היא כל מה שבין prefix לבין העמוד האחרון
            tag = ":".join(parts[1:-1]) or ""
            if page < 1:
                page = 1
            context.user_data['files_origin'] = { 'type': 'by_repo', 'tag': tag }
            context.user_data['files_last_page'] = page
            from database import db
            user_id = update.effective_user.id
            files, total = db.get_user_files_by_repo(user_id, tag, page=page, per_page=FILES_PAGE_SIZE)
            keyboard = []
            context.user_data['files_cache'] = {}
            start_index = (page - 1) * FILES_PAGE_SIZE
            for offset, f in enumerate(files):
                i = start_index + offset
                name = f.get('file_name', 'ללא שם')
                language = f.get('programming_language', 'text')
                emoji = get_file_emoji(language)
                button_text = f"{emoji} {name}"
                keyboard.append([InlineKeyboardButton(button_text, callback_data=f"file_{i}")])
                context.user_data['files_cache'][str(i)] = f
            pagination_row = build_pagination_row(page, total, FILES_PAGE_SIZE, f"by_repo_page:{tag}:")
            if pagination_row:
                keyboard.append(pagination_row)
            keyboard.append([InlineKeyboardButton("🗑️ העבר את כל הריפו לסל", callback_data=f"byrepo_delete_confirm:{tag}")])
            keyboard.append([InlineKeyboardButton("🔙 חזור", callback_data="back_to_repo_menu")])
            keyboard.append([InlineKeyboardButton("🏠 תפריט ראשי", callback_data="main")])
            try:
                await query.edit_message_text(
                    f"📂 קבצים עם {tag}:",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            except telegram.error.BadRequest as br:
                if "message is not modified" not in str(br).lower():
                    raise
        elif data.startswith("search_page_"):
            # עימוד תוצאות חיפוש שהוזנו בטקסט
            try:
                page = int(data.split("_")[-1])
            except Exception:
                page = 1
            PAGE_SIZE = 10
            filters = context.user_data.get('search_filters') or {}
            name_filter = filters.get('name_filter') or ""
            lang = filters.get('lang')
            tag = filters.get('tag')
            from database import db
            results = db.search_code(
                update.effective_user.id,
                query=name_filter,
                programming_language=(lang or ""),
                tags=([tag] if tag else []),
                limit=10000,
            ) or []
            # סינון נוסף לפי שם אם צריך
            if name_filter:
                try:
                    nf = name_filter.lower()
                    results = [r for r in results if nf in str(r.get('file_name', '')).lower()]
                except Exception:
                    pass
            total = len(results)
            total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE if total > 0 else 1
            if page < 1:
                page = 1
            if page > total_pages:
                page = total_pages
            start = (page - 1) * PAGE_SIZE
            end = min(start + PAGE_SIZE, total)
            keyboard = []
            context.user_data['files_cache'] = {}
            for i in range(start, end):
                item = results[i]
                fname = item.get('file_name', 'קובץ')
                lang_v = item.get('programming_language', 'text')
                button_text = f"📄 {fname} ({lang_v})"
                keyboard.append([InlineKeyboardButton(button_text, callback_data=f"file_{i}")])
                context.user_data['files_cache'][str(i)] = item
            row = []
            if page > 1:
                row.append(InlineKeyboardButton("⬅️ הקודם", callback_data=f"search_page_{page-1}"))
            if page < total_pages:
                row.append(InlineKeyboardButton("➡️ הבא", callback_data=f"search_page_{page+1}"))
            if row:
                keyboard.append(row)
            keyboard.append([InlineKeyboardButton("🔙 חזרה", callback_data="files")])
            await query.edit_message_text(
                f"🔎 תוצאות חיפוש — סה״כ: {total}\n" +
                f"📄 עמוד {page} מתוך {total_pages}",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        elif data.startswith("byrepo_delete_do:"):
            # ביצוע מחיקה בפועל: מחיקה לפי שם קובץ של כל הקבצים תחת התג הנבחר
            tag = data.split(":", 1)[1]
            from database import db
            user_id = update.effective_user.id
            files = db.search_code(user_id, query="", tags=[tag] if tag else [], limit=10000) or []
            total = len(files)
            deleted = 0
            # הודעת התקדמות ראשונית + אימוג׳י קבוע
            try:
                spinner_emoji = "⏳"
                percent = 0
                progress_text = (
                    f"{spinner_emoji} מוחק קבצים… 0/{total} (0%)\n"
                    "זה עלול להימשך עד דקה."
                )
                await query.edit_message_text(progress_text)
            except Exception:
                pass

            # מחיקה עם עדכוני התקדמות מתונים (Rate-limit ידידותי)
            try:
                import time as _time
                last_edit_ts = 0.0
            except Exception:
                last_edit_ts = 0.0
            for idx, f in enumerate(files, start=1):
                name = f.get('file_name')
                if not name:
                    continue
                try:
                    if db.delete_file(user_id, name):
                        deleted += 1
                except Exception:
                    continue
                # עדכון התקדמות כל ~0.8 שניות או כל 25 קבצים
                now_ts = 0.0
                try:
                    now_ts = _time.time()
                except Exception:
                    pass
                should_update = False
                if idx % 25 == 0:
                    should_update = True
                if last_edit_ts == 0.0 or (now_ts and (now_ts - last_edit_ts) >= 0.8):
                    should_update = True
                if should_update:
                    try:
                        percent = int((deleted / total) * 100) if total > 0 else 100
                        progress_text = (
                            f"{spinner_emoji} מוחק קבצים… {deleted}/{total} ({percent}%)\n"
                            "זה עלול להימשך עד דקה."
                        )
                        await query.edit_message_text(progress_text)
                        last_edit_ts = now_ts or last_edit_ts
                    except Exception:
                        pass
            try:
                _ttl_raw = getattr(config, 'RECYCLE_TTL_DAYS', 7)
                _ttl_days = max(1, int(_ttl_raw))
            except Exception:
                _ttl_days = 7
            msg = (
                f"✅ הועברו לסל {deleted} קבצים תחת <code>{tag}</code>.\n"
                f"♻️ ניתן לשחזר מסל המיחזור עד {_ttl_days} ימים."
            )
            kb = [
                [InlineKeyboardButton("🔙 חזור לתפריט ריפו", callback_data="by_repo_menu")],
                [InlineKeyboardButton("🏠 תפריט ראשי", callback_data="main")],
            ]
            await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML)
        elif data.startswith("batch_zip_page_"):
            try:
                p = int(data.split("_")[-1])
            except Exception:
                p = 1
            return await show_batch_zips_menu(update, context, page=p)
        elif data.startswith("batch_zip_use_for_batch:"):
            # בחירה ב-ZIP לצורך עיבוד Batch: מעבר לבחירת קבצים/"בחר הכל"
            zid = data.split(":", 1)[1]
            try:
                context.user_data['batch_selected_zip_id'] = zid
            except Exception:
                pass
            context.user_data['batch_target'] = { 'type': 'zips' }
            return await show_batch_files_menu(update, context, page=1)
        
    except telegram.error.BadRequest as e:
        if "Message is not modified" not in str(e):
            raise
    except Exception as e:
        logger.error(f"Error in smart callback handler: {e}")
    finally:
        # שחרור ה-guard בזמן יציאה
        try:
            context.user_data.pop("_cb_busy_until", None)
        except Exception:
            pass
    
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """ביטול מתקדם"""
    # ביטול טיימאאוט אם קיים וניקוי מצב איסוף
    try:
        job = context.user_data.get('long_collect_job')
        if job:
            job.schedule_removal()
    except Exception:
        pass
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
            MessageHandler(filters.Regex("^➕ הוסף קוד חדש$"), start_add_code_menu),
            MessageHandler(filters.Regex("^📚 הצג את כל הקבצים שלי$"), show_all_files),
            MessageHandler(filters.Regex("^📂 קבצים גדולים$"), show_large_files_direct),
            MessageHandler(filters.Regex("^🔧 GitHub$"), show_github_menu),
            MessageHandler(filters.Regex("^📥 ייבוא ZIP מריפו$"), start_repo_zip_import),
            MessageHandler(filters.Regex("^🗜️ יצירת ZIP$"), start_zip_create_flow),
            MessageHandler(filters.Regex("^🗂 לפי ריפו$"), show_by_repo_menu),
            MessageHandler(filters.Regex("^ℹ️ הסבר על הבוט$"), lambda u, c: show_help_page(u, c, page=1)),
            
            # כניסה לעריכת קוד/שם/הערה גם דרך כפתורי callback כדי שמצב השיחה ייקבע כראוי
            CallbackQueryHandler(handle_callback_query, pattern=r'^(edit_code_|edit_name_|edit_note_|edit_note_direct_|lf_edit_)')
        ],
        states={
            WAIT_ADD_CODE_MODE: [
                CallbackQueryHandler(handle_callback_query)
            ],
            GET_CODE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_code)
            ],
            GET_FILENAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_filename),
                CallbackQueryHandler(handle_duplicate_callback)
            ],
            GET_NOTE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_note)
            ],
            LONG_COLLECT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, long_collect_receive),
                CommandHandler("done", long_collect_done),
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
        
        # קיצור תצוגה אם ארוך מדי — נכבד מגבלת 4096 לאחר escape ל-HTML
        max_length = 3500
        code_preview = code[:max_length]
        
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
        
        header_html = (
            f"📄 <b>{html_escape(file_name)}</b> ({html_escape(language)}) - גרסה {version_num}\n\n"
        )
        html_wrapper_overhead = len("<pre><code>") + len("</code></pre>")
        fudge = 10
        available_for_code = 4096 - len(header_html) - html_wrapper_overhead - fudge
        if available_for_code < 100:
            available_for_code = 100
        preview_raw_limit = min(max_length, len(code))
        safe_code = html_escape(code[:preview_raw_limit])
        if len(safe_code) > available_for_code and preview_raw_limit > 0:
            try:
                factor = max(1.0, len(safe_code) / max(1, preview_raw_limit))
                preview_raw_limit = max(0, int(available_for_code / factor))
            except Exception:
                preview_raw_limit = max(0, preview_raw_limit - (len(safe_code) - available_for_code))
            safe_code = html_escape(code[:preview_raw_limit])
            while len(safe_code) > available_for_code and preview_raw_limit > 0:
                step = max(50, len(safe_code) - available_for_code)
                preview_raw_limit = max(0, preview_raw_limit - step)
                safe_code = html_escape(code[:preview_raw_limit])
        await query.edit_message_text(
            f"{header_html}<pre><code>{safe_code}</code></pre>",
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML
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
        
        try:
            fid = str((latest or {}).get('_id') or '')
        except Exception:
            fid = ''
        webapp_row = _get_webapp_button_row(fid, file_name)
        keyboard = [
            [
                InlineKeyboardButton("👁️ הצג קוד מעודכן", callback_data=(f"view_direct_id:{fid}" if fid else f"view_direct_{file_name}")),
                InlineKeyboardButton("📚 היסטוריה", callback_data=f"versions_file_{file_name}")
            ]
        ]
        if webapp_row:
            keyboard.insert(0, webapp_row)
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
    files = db.get_user_files(user_id, limit=500, projection={"file_name": 1, "tags": 1})
    repo_to_count: Dict[str, int] = {}
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
            files_docs = db.search_code(user_id, query="", tags=[tag] if tag else [], limit=2000)
            items = [cast(str, f['file_name']) for f in files_docs if f.get('file_name')]
        elif t == 'zips':
            # הצג את כל הקבצים הרגילים
            files_docs = db.get_user_files(user_id, limit=500, projection={"file_name": 1})
            items = [cast(str, f['file_name']) for f in files_docs if f.get('file_name')]
        elif t == 'large':
            large_files, _ = db.get_user_large_files(user_id, page=1, per_page=10000)
            items = [cast(str, f['file_name']) for f in large_files if f.get('file_name')]
        elif t == 'other':
            files_docs = db.get_user_files(user_id, limit=500, projection={"file_name": 1, "tags": 1})
            files_docs = [f for f in files_docs if not any((tg or '').startswith('repo:') for tg in (f.get('tags') or []))]
            items = [cast(str, f['file_name']) for f in files_docs if f.get('file_name')]
        else:
            files_docs = db.get_user_files(user_id, limit=500, projection={"file_name": 1})
            items = [cast(str, f['file_name']) for f in files_docs if f.get('file_name')]

        if not items:
            await TelegramUtils.safe_edit_message_text(query, "❌ לא נמצאו קבצים לקטגוריה שנבחרה")
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
        row = build_pagination_row(page, total, PAGE_SIZE, "batch_files_page_")
        if row:
            nav.extend(row)
        if nav:
            keyboard.append(nav)

        # פעולות
        keyboard.append([InlineKeyboardButton("✅ בחר הכל", callback_data="batch_select_all")])
        keyboard.append([InlineKeyboardButton("🔙 חזור", callback_data="batch_menu")])

        await TelegramUtils.safe_edit_message_text(
            query,
            f"בחר/י קובץ לניתוח/בדיקה, או לחץ על 'בחר הכל' כדי לעבד את כל הקבצים ({total}).",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except Exception as e:
        logger.error(f"Error in show_batch_files_menu: {e}")
        await TelegramUtils.safe_edit_message_text(query, "❌ שגיאה בטעינת רשימת קבצים ל-Batch")
    return ConversationHandler.END

async def show_batch_zips_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 1) -> int:
    """מציג רשימת קבצי ZIP שמורים (גיבויים/ארכיונים) עבור Batch"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    try:
        backups = backup_manager.list_backups(user_id)
        # מציג את כל קבצי ה‑ZIP השמורים בבוט
        if not backups:
            keyboard = [[InlineKeyboardButton("🔙 חזור", callback_data="batch_menu")]]
            await query.edit_message_text(
                "ℹ️ לא נמצאו קבצי ZIP שמורים.",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return ConversationHandler.END

        PAGE_SIZE = 10
        total = len(backups)
        total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
        if page < 1:
            page = 1
        if page > total_pages:
            page = total_pages
        start = (page - 1) * PAGE_SIZE
        end = min(start + PAGE_SIZE, total)
        items = backups[start:end]

        lines = [f"📦 קבצי ZIP שמורים — סה""כ: {total}\n📄 עמוד {page} מתוך {total_pages}\n"]
        keyboard = []
        # חישוב גרסאות vN לפי ריפו
        repo_to_sorted: Dict[str, list] = {}
        id_to_version = {}
        try:
            from datetime import datetime as _dt
            def _key(v):
                dt = getattr(v, 'created_at', None)
                return dt.timestamp() if hasattr(dt, 'timestamp') else 0.0
            for b in backups:
                r = getattr(b, 'repo', None)
                if not r:
                    continue
                repo_to_sorted.setdefault(r, []).append(b)
            for r, arr in repo_to_sorted.items():
                arr.sort(key=_key)
                for idx, b in enumerate(arr, start=1):
                    id_to_version[getattr(b, 'backup_id', '')] = idx
        except Exception:
            id_to_version = {}

        for info in items:
            when = info.created_at.strftime('%d/%m/%Y %H:%M') if getattr(info, 'created_at', None) else ''
            # קבע primary: שם ריפו ללא owner עבור github_repo_zip אחרת backup_id
            if getattr(info, 'backup_type', '') == 'github_repo_zip' and getattr(info, 'repo', None):
                try:
                    primary = info.repo.split('/', 1)[1] if '/' in info.repo else info.repo
                except Exception:
                    primary = str(getattr(info, 'repo', ''))
            else:
                primary = getattr(info, 'backup_id', 'full')
            vnum = id_to_version.get(getattr(info, 'backup_id', ''), None)
            vtxt = f" v{vnum}" if vnum else ""
            # שלוף דירוג אם קיים
            try:
                from database import db
                rating = db.get_backup_rating(user_id, info.backup_id) or ""
            except Exception:
                rating = ""
            emoji = ""
            if "🏆" in rating:
                emoji = " 🏆"
            elif "👍" in rating:
                emoji = " 👍"
            elif "🤷" in rating:
                emoji = " 🤷"
            btn_text = f"BKP zip {primary}{vtxt}{emoji} - {when}"
            # שורת מידע
            size_text = _format_bytes(getattr(info, 'total_size', 0))
            count_text = getattr(info, 'file_count', 0)
            lines.append(f"• {btn_text} — {size_text} — {count_text} קבצים")
            keyboard.append([
                InlineKeyboardButton(btn_text if len(btn_text) <= 64 else btn_text[:60] + '…', callback_data=f"batch_zip_use_for_batch:{info.backup_id}")
            ])

        nav = []
        if page > 1:
            nav.append(InlineKeyboardButton("⬅️ הקודם", callback_data=f"batch_zip_page_{page-1}"))
        if page < total_pages:
            nav.append(InlineKeyboardButton("➡️ הבא", callback_data=f"batch_zip_page_{page+1}"))
        if nav:
            keyboard.append(nav)

        keyboard.append([InlineKeyboardButton("🔙 חזור", callback_data="batch_menu")])
        await query.edit_message_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception:
        await query.edit_message_text("❌ שגיאה בטעינת רשימת ZIPs")
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
                items = db.search_code(user_id, query="", tags=[tag] if tag else [], limit=2000)
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