import re
import os
import logging
import inspect
from io import BytesIO
from typing import Optional
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler

from handlers.states import GET_CODE, GET_FILENAME, GET_NOTE, WAIT_ADD_CODE_MODE, LONG_COLLECT
from services import code_service
from utils import TextUtils
from utils import ValidationUtils
from utils import TelegramUtils
from utils import normalize_code  # נרמול קלט כדי להסיר תווים נסתרים מוקדם

logger = logging.getLogger(__name__)

def _get_files_facade_or_none():
    """Best-effort access to FilesFacade without importing legacy DB."""
    try:
        from src.infrastructure.composition import get_files_facade  # type: ignore
        return get_files_facade()
    except Exception:
        return None
# Observability (fail-open): unify error/event reporting
try:  # type: ignore
    from observability import emit_event  # type: ignore
except Exception:  # pragma: no cover
    def emit_event(event: str, severity: str = "info", **fields):  # type: ignore
        return None
try:  # type: ignore
    from internal_alerts import emit_internal_alert  # type: ignore
except Exception:  # pragma: no cover
    def emit_internal_alert(name: str, severity: str = "info", summary: str = "", **details):  # type: ignore
        return None

# הגדרות מצב איסוף
LONG_COLLECT_MAX_BYTES = 300 * 1024  # 300KB
LONG_COLLECT_TIMEOUT_SECONDS = 15 * 60  # 15 דקות
_SAVE_FLOW_STATE_KEYS = [
    'filename_to_save',
    'code_to_save',
    'note_to_save',
    'pending_filename',
    'long_collect_parts',
    'long_collect_active',
    'long_collect_locked',
    'long_collect_job',
]


def _should_use_new_save_flow() -> bool:
    """קריאה בטוחה לדגל המסלול החדש."""
    try:
        return str(os.getenv("USE_NEW_SAVE_FLOW", "")).lower() in {"1", "true", "yes"}
    except Exception:
        return False


def _safe_construct(target, *preferred_args):
    """ניסיון אתחול גמיש עבור מחלקות שמוחלפות במוקים פשוטים בטסטים."""
    if target is None:
        return None
    if not callable(target):
        return target
    try:
        return target(*preferred_args)
    except TypeError:
        try:
            return target()
        except Exception:
            return None
    except Exception:
        return None


def _build_layered_snippet_service():
    """יוצר מופע שירות למסלול החדש דרך Composition Root אחד."""
    try:
        from src.infrastructure.composition import get_snippet_service  # type: ignore
        return get_snippet_service()
    except Exception:
        return None


async def _call_service_method(service, method_name, *args, **kwargs):
    """קריאה בטוחה לפעולה אסינכרונית/סינכרונית של השירות."""
    if not service:
        return None
    method = getattr(service, method_name, None)
    if not callable(method):
        return None
    try:
        result = method(*args, **kwargs)
        if inspect.isawaitable(result):
            return await result
        return result
    except Exception:
        return None


def _cleanup_save_flow_state(context: ContextTypes.DEFAULT_TYPE) -> None:
    for k in _SAVE_FLOW_STATE_KEYS:
        try:
            context.user_data.pop(k, None)
        except Exception:
            continue


async def _send_save_success(update, context, filename, detected_language, note, fid):
    note = note or ''
    note_btn_text = "📝 ערוך הערה" if note else "📝 הוסף הערה"
    keyboard = [
        [
            InlineKeyboardButton("👁️ הצג קוד", callback_data=f"view_direct_id:{fid}" if fid else f"view_direct_{filename}"),
            InlineKeyboardButton("✏️ ערוך", callback_data=f"edit_code_direct_{filename}"),
        ],
        [
            InlineKeyboardButton("📝 שנה שם", callback_data=f"edit_name_direct_{filename}"),
            InlineKeyboardButton(note_btn_text, callback_data=f"edit_note_direct_{filename}"),
        ],
        [
            InlineKeyboardButton("📚 היסטוריה", callback_data=f"versions_file_{filename}"),
            InlineKeyboardButton("📥 הורד", callback_data=f"download_direct_{filename}"),
        ],
        [
            InlineKeyboardButton("🗑️ מחק", callback_data=f"delete_direct_{filename}"),
        ],
        [
            InlineKeyboardButton("🔗 שתף קוד", callback_data=f"share_menu_id:{fid}") if fid else InlineKeyboardButton("🔗 שתף קוד", callback_data="share_menu_id:"),
        ],
        [
            InlineKeyboardButton("🔙 לרשימה", callback_data="files"),
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    note_display = TextUtils.escape_markdown(note, version=1) if note else '—'
    await update.message.reply_text(
        f"🎉 *קובץ נשמר בהצלחה!*\n\n"
        f"📄 **שם:** `{filename}`\n"
        f"🧠 **שפה זוהתה:** {detected_language}\n"
        f"📝 **הערה:** {note_display}\n\n"
        f"🎮 בחר פעולה מהכפתורים החכמים:",
        reply_markup=reply_markup,
        parse_mode='Markdown',
    )
    try:
        import time as _time
        now_epoch = int(_time.time())
        context.user_data['last_save_success'] = {
            'file_name': filename,
            'language': detected_language,
            'note': note,
            'file_id': fid,
            'saved_at_epoch': now_epoch,
        }
        # שמור גם מפתח ישיר לנוחות בדיקות/שימוש עתידי
        context.user_data['last_save_success_ts'] = now_epoch
    except Exception:
        pass


async def _save_via_layered_flow(update, context, filename, user_id, code, note):
    service = _build_layered_snippet_service()
    if not service:
        return False
    try:
        from src.application.dto.create_snippet_dto import CreateSnippetDTO  # type: ignore
    except Exception:
        return False
    dto_kwargs = {
        'user_id': user_id,
        'filename': filename,
        'code': code,
    }
    if note:
        dto_kwargs['note'] = note
    dto = None
    try:
        dto = CreateSnippetDTO(**dto_kwargs)
    except TypeError:
        try:
            dto = CreateSnippetDTO(user_id, filename, code, note or None)  # type: ignore[arg-type]
        except Exception:
            return False
    except Exception:
        return False
    saved = await _call_service_method(service, "create_snippet", dto)
    if not saved:
        return False
    fid = ''
    # נסיון 1: FilesFacade (אם זמין)
    facade = _get_files_facade_or_none()
    if facade is not None:
        try:
            saved_doc = facade.get_latest_version(user_id, filename) or {}
        except Exception:
            saved_doc = {}
        try:
            fid = str(saved_doc.get('_id') or '')
        except Exception:
            fid = ''
    detected_language = getattr(saved, "language", None) or getattr(saved, "detected_language", None) or ""
    # חיזוק: אם קיבלנו 'text' או שלא נקבעה שפה, ננסה זיהוי מהשירות הוותיק (סיומת גוברת כמו .md)
    try:
        ext_lower = str(filename or '').lower()
    except Exception:
        ext_lower = ''
    if not detected_language or detected_language == 'text' or (ext_lower.endswith(('.md', '.markdown', '.mdown', '.mkd', '.mkdn')) and detected_language != 'markdown'):
        try:
            detected_language = code_service.detect_language(code, filename)
        except Exception:
            detected_language = "text"
    await _send_save_success(update, context, filename, detected_language, note or '', fid)
    _cleanup_save_flow_state(context)
    return True


def _get_total_bytes(parts: list[str]) -> int:
    try:
        return sum(len(p.encode('utf-8', errors='ignore')) for p in parts)
    except Exception:
        return 0


def _sanitize_part(text: str) -> str:
    # הסר אליפסות יוניקוד '…' מכל חלק
    try:
        return (text or '').replace('…', '')
    except Exception:
        return text or ''


def _detect_secrets(text: str) -> list[str]:
    """זיהוי גס של סודות כדי להתריע למשתמש לפני שיתוף/שמירה."""
    patterns = [
        r"ghp_[A-Za-z0-9]{36,}",
        r"github_pat_[A-Za-z0-9_]{30,}",
        r"AIza[0-9A-Za-z\-_]{35}",  # Google API
        r"sk_(live|test)_[0-9A-Za-z]{20,}",  # Stripe
        r"xox[abprs]-[0-9A-Za-z\-]{10,}",  # Slack
        r"AWS_ACCESS_KEY_ID\s*=\s*[A-Z0-9]{16,20}",
        r"AWS_SECRET_ACCESS_KEY\s*=\s*[A-Za-z0-9/+=]{30,}",
        r"-----BEGIN (RSA |EC |)PRIVATE KEY-----",
        r"(?i)(api|secret|token|key)[\s:=\"]{1,20}[A-Za-z0-9_\-]{16,}"
    ]
    matches = []
    try:
        for pat in patterns:
            if re.search(pat, text or ''):
                matches.append(pat)
    except Exception:
        pass
    return matches


def _cancel_long_collect_timeout(context: ContextTypes.DEFAULT_TYPE) -> None:
    job = context.user_data.pop('long_collect_job', None)
    try:
        if job:
            job.schedule_removal()
    except Exception:
        pass


def _schedule_long_collect_timeout(update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """קבע/רענן טיימאאוט ללא פעילות.

    שימוש במזהה Job קבוע (per-user) ו-replace_existing כדי למנוע כפילויות בלוגים של APScheduler.
    """
    try:
        jid = f"long_collect_timeout:{update.effective_user.id}"
        job = context.job_queue.run_once(
            long_collect_timeout_job,
            when=LONG_COLLECT_TIMEOUT_SECONDS,
            data={
                'chat_id': update.effective_chat.id if getattr(update, 'effective_chat', None) else update.callback_query.message.chat_id,
                'user_id': update.effective_user.id,
            },
            name=jid,
            job_kwargs={
                'id': jid,
                'replace_existing': True,
            }
        )
        context.user_data['long_collect_job'] = job
    except Exception as e:
        try:
            emit_event(
                "long_collect_schedule_timeout_failed",
                severity="anomaly",
                operation="save_flow.schedule_timeout",
                handled=True,
                user_id=getattr(getattr(update, 'effective_user', None), 'id', None),
                error=str(e),
            )
        except Exception:
            pass
        logger.warning(f"Failed scheduling timeout: {e}")


async def long_collect_timeout_job(context: ContextTypes.DEFAULT_TYPE):
    """קריאת טיימאאוט: מסכם ומתקדם לפי חלקים שנאספו."""
    try:
        data = context.job.data or {}
        chat_id = data.get('chat_id')
        user_id = data.get('user_id')
        # שליפת נתוני המשתמש
        parts = context.user_data.get('long_collect_parts') or []
        if not parts:
            await context.bot.send_message(
                chat_id=chat_id,
                text="⏳ מצב איסוף הסתיים אוטומטית לאחר 15 דקות ללא פעילות.\nלא נאספו חלקים, ולכן המצב נסגר."
            )
            context.user_data.pop('long_collect_active', None)
            _cancel_long_collect_timeout(context)
            return
        # סמן נעילה כדי למנוע הוספה נוספת
        context.user_data['long_collect_locked'] = True
        total_bytes = _get_total_bytes(parts)
        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                f"⏳ מצב איסוף נסגר לאחר חוסר פעילות.\n"
                f'✅ נאספו {len(parts)} חלקים (סה"כ ~{total_bytes // 1024}KB).\n'
                f"שלח/י /done לאיחוד לקובץ אחד או /cancel לביטול."
            )
        )
        # נשארים בסטייט, אך נעולים להוספה נוספת עד /done או /cancel
    except Exception as e:
        try:
            emit_event(
                "long_collect_timeout_job_failed",
                severity="anomaly",
                operation="save_flow.timeout_job",
                handled=True,
                error=str(e),
            )
        except Exception:
            pass
        logger.warning(f"Timeout job failed: {e}")

async def start_save_flow(update, context: ContextTypes.DEFAULT_TYPE) -> int:
    cancel_markup = InlineKeyboardMarkup([[InlineKeyboardButton("❌ ביטול", callback_data="cancel")]])
    # תמיכה גם בקריאה מתוך callback וגם מתוך הודעת טקסט
    target_msg = getattr(update, "message", None)
    if target_msg is None and getattr(update, "callback_query", None) is not None:
        target_msg = update.callback_query.message
    await target_msg.reply_text(
        "✨ *מצוין!* בואו נצור קוד חדש!\n\n"
        "📝 שלח לי את קטע הקוד המבריק שלך.\n"
        "💡 אני אזהה את השפה אוטומטית ואארגן הכל!",
        reply_markup=cancel_markup,
        parse_mode='Markdown',
    )
    return GET_CODE


async def start_add_code_menu(update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """תפריט בחירת מצב הוספת קוד: רגיל או איסוף ארוך"""
    keyboard = [
        [InlineKeyboardButton("🧩 קוד רגיל", callback_data="add_code_regular")],
        [InlineKeyboardButton("✍️ איסוף קוד ארוך", callback_data="add_code_long")],
        [InlineKeyboardButton("❌ ביטול", callback_data="cancel")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "איך תרצו להוסיף קוד?",
        reply_markup=reply_markup
    )
    return WAIT_ADD_CODE_MODE


async def start_long_collect(update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """כניסה למצב איסוף קוד ארוך"""
    # איפוס/אתחול רשימת החלקים
    context.user_data['long_collect_parts'] = []
    context.user_data['long_collect_active'] = True
    context.user_data['long_collect_locked'] = False
    await update.callback_query.answer()
    await update.callback_query.message.reply_text(
        "נכנסתי למצב איסוף קוד ✍️\n"
        "שלח/י את חלקי הקוד בהודעות נפרדות.\n"
        "כשתסיים/י, שלח/י /done כדי לאחד את הכל לקובץ אחד.\n"
        "אפשר גם /cancel לביטול."
    )
    _schedule_long_collect_timeout(update, context)
    return LONG_COLLECT


async def long_collect_receive(update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """קבלת חלק קוד נוסף במצב איסוף"""
    # אם מצב נעול בעקבות טיימאאוט, למנוע הוספה
    if context.user_data.get('long_collect_locked'):
        await update.message.reply_text("מצב האיסוף נעול לאחר חוסר פעילות. שלח/י /done או /cancel.")
        return LONG_COLLECT

    # התעלמות מתכנים שאינם טקסט או מסמכי טקסט
    if update.message.document:
        doc = update.message.document
        mime = (doc.mime_type or '').lower()
        if mime.startswith('text/') or doc.file_name.endswith(('.txt', '.md', '.py', '.js', '.ts', '.json', '.yml', '.yaml', '.java', '.kt', '.go', '.rs', '.c', '.cpp', '.h', '.cs', '.rb', '.php', '.swift', '.sql', '.sh', '.bat', '.ps1')):
            # הורדה כטקסט
            file = await doc.get_file()
            bio = BytesIO()
            await file.download_to_memory(out=bio)
            text = bio.getvalue().decode('utf-8', errors='ignore')
        else:
            await update.message.reply_text("📎 קיבלתי קובץ שאינו טקסט. שלח/י מסמך טקסט או הדבק/י את הקוד כהודעת טקסט.")
            return LONG_COLLECT
    elif update.message.text:
        # קלט טקסט גולמי בדיוק כפי שנשלח ע"י המשתמש, ללא הזרקת Markdown
        text = update.message.text or ''
    else:
        await update.message.reply_text("🖼️ התקבלה הודעה שאינה טקסט. שלח/י קוד כהודעת טקסט או קובץ טקסט.")
        return LONG_COLLECT

    text = _sanitize_part(text)
    # נרמול מוקדם: הסרת תווים נסתרים/כיווניות ואיחוד שורות
    try:
        text = normalize_code(text)
    except Exception:
        pass
    parts = context.user_data.get('long_collect_parts')
    if parts is None:
        parts = []
        context.user_data['long_collect_parts'] = parts
    # הוסף את החלק כפי שהוא
    parts.append(text)
    total_bytes = _get_total_bytes(parts)
    if total_bytes > LONG_COLLECT_MAX_BYTES:
        # גלול אחורה את התוספת האחרונה
        parts.pop()
        await update.message.reply_text(
            f"❗ חרגת מתקרת הגודל ({LONG_COLLECT_MAX_BYTES // 1024}KB). החלק האחרון לא נשמר.\n"
            f"נוכחי: ~{total_bytes // 1024}KB (כולל נסיון החלק האחרון)."
        )
        return LONG_COLLECT

    # רמיזת אבטחה בסיסית
    try:
        if _detect_secrets(text):
            await update.message.reply_text("⚠️ שים/שימי לב: נראה שההודעה מכילה מפתח/סוד. ודא/י שלא לשתף מידע רגיש.")
    except Exception:
        pass

    # עדכון ספירת חלקים
    await update.message.reply_text(f"נשמר ✔️ (סה״כ {len(parts)} חלקים)")
    _schedule_long_collect_timeout(update, context)
    # הישאר במצב האיסוף
    return LONG_COLLECT


async def long_collect_done(update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """סיום איסוף, איחוד ושילוב לזרימת שמירה רגילה"""
    parts = context.user_data.get('long_collect_parts') or []
    if not parts:
        await update.message.reply_text(
            "לא התקבלו חלקים עדיין. שלח/י קוד, או /cancel לביטול."
        )
        return LONG_COLLECT
    code_text = "\n".join(parts)
    # נרמול כלל הטקסט המאוחד (אידמפוטנטי)
    try:
        code_text = normalize_code(code_text)
    except Exception:
        pass
    context.user_data['code_to_save'] = code_text
    # אזהרת סודות באיחוד הכולל
    try:
        if _detect_secrets(code_text):
            await update.message.reply_text("⚠️ אזהרה: בטקסט המאוחד נמצאו מפתחות/סודות פוטנציאליים. ודא/י שאין חשיפת מידע רגיש.")
    except Exception:
        pass
    context.user_data.pop('long_collect_active', None)
    context.user_data.pop('long_collect_locked', None)
    _cancel_long_collect_timeout(context)
    # הצג הודעת סיכום והמשך לבקשת שם קובץ
    lines = len(code_text.split('\n'))
    chars = len(code_text)
    words = len(code_text.split())
    await update.message.reply_text(
        "📝 כל החלקים אוחדו בהצלחה.\n"
        "הנה הקובץ המלא.\n\n"
        f"📊 **סטטיסטיקות מהירות:**\n"
        f"• 📏 שורות: {lines:,}\n"
        f"• 🔤 תווים: {chars:,}\n"
        f"• 📝 מילים: {words:,}\n\n"
        f"💭 עכשיו תן לי שם קובץ חכם (למשל: `my_amazing_script.py`)\n"
        f"🧠 השם יעזור לי לזהות את השפה ולארגן הכל מושלם!",
        parse_mode='Markdown',
    )
    return GET_FILENAME


async def get_code(update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # קלט טקסט גולמי כפי שנשלח ע"י המשתמש, ללא המרה ל-Markdown
    code = update.message.text or ''
    # נרמול מוקדם כדי למנוע תווים נסתרים כבר בשלב האיסוף
    try:
        code = normalize_code(code)
    except Exception:
        pass
    context.user_data['code_to_save'] = code
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
        parse_mode='Markdown',
    )
    return GET_FILENAME


async def get_filename(update, context: ContextTypes.DEFAULT_TYPE) -> int:
    filename = update.message.text.strip()
    user_id = update.message.from_user.id
    # קבלה של שמות ללא סיומת (Dockerfile/Makefile/Procfile), נקודתיים (.gitignore), וגם name.ext רגיל
    if not ValidationUtils.is_valid_filename(filename):
        await update.message.reply_text(
            "🤔 השם נראה קצת מוזר...\n"
            "💡 נסה שם כמו: `script.py` או `index.html`\n"
            "✅ אותיות, מספרים, נקודות וקווים מותרים!"
        )
        return GET_FILENAME
    # בדיקת קיום קובץ קודם: נסה מסלול חדש אם מופעל בדגל סביבה, אחרת DB ישיר
    existing_file = None
    use_new = _should_use_new_save_flow()
    if use_new:
        service = _build_layered_snippet_service()
        existing_entity = await _call_service_method(service, "get_snippet", user_id, filename)
        if existing_entity is not None:
            existing_file = existing_entity
        if existing_file is None:
            facade = _get_files_facade_or_none()
            if facade is not None:
                try:
                    existing_doc = facade.get_latest_version(user_id, filename)
                    existing_file = bool(existing_doc)
                except Exception:
                    existing_file = None
    else:
        facade = _get_files_facade_or_none()
        if facade is not None:
            try:
                existing_file = facade.get_latest_version(user_id, filename)
            except Exception:
                existing_file = None
    if existing_file:
        keyboard = [
            [InlineKeyboardButton("🔄 החלף את הקובץ הקיים", callback_data=f"replace_{filename}")],
            [InlineKeyboardButton("✏️ שנה שם קובץ", callback_data="rename_file")],
            [InlineKeyboardButton("🚫 בטל ושמור במקום אחר", callback_data="cancel_save")],
        ]
        context.user_data['pending_filename'] = filename
        await update.message.reply_text(
            f"⚠️ *אופס!* הקובץ `{filename}` כבר קיים במערכת!\n\n"
            f"🤔 מה תרצה לעשות?",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown',
        )
        return GET_FILENAME
    context.user_data['pending_filename'] = filename
    await update.message.reply_text(
        "📝 רוצה להוסיף הערה קצרה לקובץ?\n"
        "כתוב/כתבי אותה עכשיו או שלח/י 'דלג' כדי לשמור בלי הערה."
    )
    return GET_NOTE


async def get_note(update, context: ContextTypes.DEFAULT_TYPE) -> int:
    note_text = (update.message.text or '').strip()
    if note_text.lower() in {"דלג", "skip", "ללא"}:
        context.user_data['note_to_save'] = ""
    else:
        context.user_data['note_to_save'] = note_text[:280]
    filename = context.user_data.get('pending_filename') or context.user_data.get('filename_to_save')
    user_id = update.message.from_user.id
    return await save_file_final(update, context, filename, user_id)


async def save_file_final(update, context, filename, user_id):
    context.user_data['filename_to_save'] = filename
    code = context.user_data.get('code_to_save')
    # מחסום נגד "גרסת רפאים": אם אין תוכן לשמירה ובוצעה זה עתה שמירה מוצלחת לאותו שם קובץ – דלג
    try:
        import time as _time
        last = context.user_data.get('last_save_success') or {}
        last_name = str(last.get('file_name') or '')
        last_ts = int(context.user_data.get('last_save_success_ts') or last.get('saved_at_epoch') or 0)
        code_empty = not code or not str(code).strip()
        if code_empty and last_name == str(filename) and (_time.time() - last_ts) <= 15:
            try:
                emit_event(
                    "save_flow_skip_empty_duplicate",
                    severity="info",
                    operation="save_flow.guard",
                    user_id=int(user_id),
                    file_name=str(filename),
                )
            except Exception:
                pass
            # אל תנקה את last_save_success כדי לשמר עקבות; כן ננקה סטייט של ה-save flow
            _cleanup_save_flow_state(context)
            return ConversationHandler.END
    except Exception:
        # במקרה של כשל בבדיקה – נמשיך כרגיל
        pass
    # הבטחת נרמול לפני שמירה (אידמפוטנטי)
    try:
        code = normalize_code(code)
    except Exception:
        pass
    note = (context.user_data.get('note_to_save') or '').strip()
    # נסה מסלול חדש (ארכיטקטורה שכבתית) כאשר מופעל בדגל סביבה
    use_new = _should_use_new_save_flow()
    if use_new:
        try:
            layered_saved = await _save_via_layered_flow(update, context, filename, user_id, code, note)
            if layered_saved:
                return ConversationHandler.END
        except Exception:
            # אם המסלול החדש נכשל, ניפול חזרה למסלול הישן בהמשך
            pass
    try:
        detected_language = code_service.detect_language(code, filename)
        try:
            from src.infrastructure.composition import get_files_facade  # type: ignore
            facade = get_files_facade()
        except Exception:
            facade = None
        success = False
        last_exc: Optional[BaseException] = None
        if facade is not None:
            try:
                success = bool(
                    facade.save_code_snippet(
                        user_id=int(user_id),
                        file_name=str(filename),
                        code=str(code or ""),
                        programming_language=str(detected_language or "text"),
                        description=str(note or ""),
                        tags=None,
                    )
                )
            except Exception as exc:
                success = False
                last_exc = last_exc or exc
        if not success and last_exc is not None:
            raise last_exc
        if success:
            try:
                saved_doc = (facade.get_latest_version(user_id, filename) if facade is not None else None) or {}
                fid = str(saved_doc.get('_id') or '')
            except Exception:
                fid = ''
            await _send_save_success(update, context, filename, detected_language, note or '', fid)
            _cleanup_save_flow_state(context)
            return ConversationHandler.END
        else:
            await update.message.reply_text(
                "💥 אופס! קרתה שגיאה טכנית.\n"
                "🔧 המערכת מתקדמת - ננסה שוב מאוחר יותר!",
                reply_markup=ReplyKeyboardMarkup([[]], resize_keyboard=True),
            )
    except Exception as e:
        try:
            emit_event(
                "save_file_failed",
                severity="anomaly",
                operation="save_flow.save_file_final",
                handled=True,
                user_id=int(user_id),
                file_name=str(filename),
                error=str(e),
            )
            emit_internal_alert(
                name="save_file_failed",
                severity="anomaly",
                summary=f"user_id={user_id}, file_name={filename}",
            )
        except Exception:
            pass
        logger.error(f"Failed to save file for user {user_id}: {e}")
        await update.message.reply_text(
            "🤖 המערכת החכמה שלנו נתקלה בבעיה זמנית.\n"
            "⚡ ננסה שוב בקרוב!",
            reply_markup=ReplyKeyboardMarkup([[]], resize_keyboard=True),
        )
    _cleanup_save_flow_state(context)
    return ConversationHandler.END

