"""
File View Handler Module
========================

מודול לניהול תצוגת קבצים וקוד בבוט טלגרם.

מודול זה מספק פונקציונליות ל:
- הצגת קבצי קוד
- עריכת קבצים
- ניהול גרסאות
- ייצוא קבצים
"""

import logging
import os
import re
from io import BytesIO
import inspect
from datetime import datetime, timezone
from typing import List, Optional
import secrets
from html import escape as html_escape
from urllib.parse import quote_plus

from config import config
from utils import TelegramUtils, TextUtils, ValidationUtils


async def _edit_message_text_unified(query, text: str, *, reply_markup=None, parse_mode=None):
    """Edit message text using query.edit_message_text when available, otherwise fallback to TelegramUtils.safe_edit_message_text.

    This keeps tests that stub only one path working and unifies behavior.
    """
    try:
        if hasattr(query, 'edit_message_text') and callable(getattr(query, 'edit_message_text')):
            return await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
        else:
            return await TelegramUtils.safe_edit_message_text(query, text, reply_markup=reply_markup, parse_mode=parse_mode)
    except Exception:
        # last resort — try the other path once
        try:
            return await TelegramUtils.safe_edit_message_text(query, text, reply_markup=reply_markup, parse_mode=parse_mode)
        except Exception:
            return await query.edit_message_text(text)

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes, ConversationHandler

from handlers.states import EDIT_CODE, EDIT_NAME
from services import code_service

logger = logging.getLogger(__name__)

# Injection hook for tests: set to an instance providing the FilesFacade API
FILES_FACADE = None


DEFAULT_WEBAPP_URL = "https://code-keeper-webapp.onrender.com"

def _sanitize_codeblock_language_tag(language: Optional[str]) -> str:
    """מחזיר תג שפה בטוח ל-```lang ב-MarkdownV2 (כדי לקבל תווית שפה + הדגשת תחביר בצד הלקוח)."""
    try:
        lang_tag = str(language or "").strip().lower()
    except Exception:
        lang_tag = ""
    # מיפוי מינימלי לערכים נפוצים/היסטוריים
    alias = {
        "c#": "csharp",
        "cs": "csharp",
        "csharp": "csharp",
        "c++": "cpp",
        "cpp": "cpp",
        "py": "python",
        "python3": "python",
        "js": "javascript",
        "ts": "typescript",
        "sh": "bash",
        "shell": "bash",
    }
    lang_tag = alias.get(lang_tag, lang_tag)
    # Telegram: שמור רק תווים בטוחים; אם יצא ריק — fallback עקבי
    try:
        lang_tag = re.sub(r"[^a-z0-9#+-]+", "", lang_tag)
    except Exception:
        lang_tag = ""
    return lang_tag or "text"

def _sanitize_codeblock_content_for_markdown_v2(code: str) -> str:
    """מונע סגירה מוקדמת של בלוק ``` ב-Telegram ע"י פירוק הרצף ``` בתוך התוכן."""
    try:
        text = str(code or "")
    except Exception:
        return ""
    # אם מופיע ``` בתוך הקוד, הוא יסגור את הבלוק. נשבור את הרצף בעזרת תו Zero‑Width Space.
    # זה שומר קריאות גבוהה ומונע נפילות "אקראיות" ל-HTML.
    try:
        return text.replace("```", "``\u200b`")
    except Exception:
        return text


def _resolve_webapp_base_url() -> Optional[str]:
    """החזרת בסיס ה-URL של ה-WebApp עם סדר עדיפויות ברור."""
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
    """בונה שורת כפתור WebApp עבור מזהה קובץ או fallback לפי שם."""
    base_url = _resolve_webapp_base_url()
    if not base_url:
        return None
    target_url: Optional[str]
    if file_id:
        target_url = f"{base_url}/file/{file_id}"
    elif file_name:
        try:
            query = quote_plus(str(file_name))
        except Exception:
            query = str(file_name)
        target_url = f"{base_url}/files?q={query}#results"
    else:
        target_url = None
    if not target_url:
        return None
    try:
        return [InlineKeyboardButton("🌐 צפייה בWebApp", url=target_url)]
    except TypeError:
        # בסביבות בדיקה ייתכן שהכפתור לא תומך בפרמטר url
        return None


def _get_files_facade():
    """
    מחזיר את ה-FilesFacade עם נפילה חכמה לגרסה שמוזרקת בטסטים.
    קודם ננסה את ה-Composition Root, ואם נכשל/לא זמין ננסה פונקציה גלובלית שמוקפצת בטסטים.
    """
    # עדיפות עליונה: אובייקט מוזרק ישירות (לשימוש בטסטים)
    try:
        injected = globals().get("FILES_FACADE")
        if injected is not None:
            return injected
    except Exception:
        pass
    # עדיפות ראשונה: פונקציה גלובלית שמוקפצת בטסטים (monkeypatch על handlers.file_view.get_files_facade)
    try:
        gf = globals().get("get_files_facade")
        if callable(gf):
            inst = gf()
            if inst:
                return inst
    except Exception:
        pass
    try:
        from src.infrastructure.composition import get_files_facade as _gff  # type: ignore
        facade = _gff()
        if facade:
            return facade
    except Exception:
        pass
    return None


def _get_main_keyboard() -> list:
    """
    מחזיר את פריסת המקלדת הראשית.
    
    Returns:
        list: רשימת כפתורי המקלדת הראשית
    
    Note:
        מחזיר רשימה ריקה במקרה של שגיאה
    """
    try:
        from conversation_handlers import MAIN_KEYBOARD
        return MAIN_KEYBOARD
    except Exception:
        return [[]]


async def _call_service_method(service, method_name, *args, **kwargs):
    """
    קריאה בטוחה לפעולה אסינכרונית/סינכרונית של השירות (לשימוש מול Composition Root).
    """
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


async def handle_file_menu(update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    מציג תפריט פעולות עבור קובץ נבחר.
    
    Args:
        update: אובייקט Update מטלגרם
        context: הקונטקסט של השיחה
    
    Returns:
        int: מצב השיחה החדש
    
    Note:
        מציג אפשרויות כמו הצגה, עריכה, מחיקה ושיתוף
    """
    query = update.callback_query
    await query.answer()
    try:
        file_index = query.data.split('_')[1]
        files_cache = context.user_data.get('files_cache', {})
        file_data = files_cache.get(file_index)
        if not file_data:
            await TelegramUtils.safe_edit_message_text(query, "❌ שגיאה בזיהוי הקובץ החכם")
            return ConversationHandler.END
        file_name = file_data.get('file_name', 'קובץ מיסתורי')
        language = file_data.get('programming_language', 'לא ידועה')
        try:
            file_id_str = str(file_data.get('_id') or '')
        except Exception:
            file_id_str = ''
        # קבע כפתור חזרה בהתאם למקור (מועדפים/רגיל/אחר)
        last_page = context.user_data.get('files_last_page')
        origin = context.user_data.get('files_origin') or {}
        if origin.get('type') == 'by_repo' and origin.get('tag'):
            back_cb = f"by_repo:{origin.get('tag')}"
        elif origin.get('type') == 'favorites':
            back_cb = f"favorites_page_{last_page}" if last_page else "show_favorites"
        elif origin.get('type') == 'regular':
            back_cb = f"files_page_{last_page}" if last_page else "show_regular_files"
        else:
            back_cb = f"back_after_view:{file_name}"

        # הערה: לוגיקת ה־back כבר חושבה למעלה – אין לשכפל כדי לא לדרוס ערך

        webapp_row = _get_webapp_button_row(file_id_str, file_name)
        share_row = list(webapp_row) if webapp_row else []
        share_row.append(InlineKeyboardButton("🔗 שתף קוד", callback_data=f"share_menu_idx:{file_index}"))

        keyboard = [
            [
                InlineKeyboardButton("✏️ ערוך", callback_data=f"edit_code_{file_index}"),
                InlineKeyboardButton("👁️ הצג קוד", callback_data=f"view_{file_index}"),
            ],
            [
                InlineKeyboardButton("📝 ערוך הערה", callback_data=f"edit_note_{file_index}"),
                InlineKeyboardButton("📝 שנה שם", callback_data=f"edit_name_{file_index}"),
            ],
            share_row,
            [
                InlineKeyboardButton("📚 היסטוריה", callback_data=f"versions_{file_index}"),
                InlineKeyboardButton("📥 הורד", callback_data=f"dl_{file_index}"),
            ],
            [
                InlineKeyboardButton("🔄 שכפול", callback_data=f"clone_{file_index}"),
                InlineKeyboardButton("🗑️ מחק", callback_data=f"del_{file_index}"),
            ],
        ]
        last_page = context.user_data.get('files_last_page')
        origin = context.user_data.get('files_origin') or {}
        # קביעה אחידה של יעד כפתור "חזרה" לפי מקור הרשימה
        if origin.get('type') == 'by_repo' and origin.get('tag'):
            back_cb = f"by_repo:{origin.get('tag')}"
        elif origin.get('type') == 'favorites':
            back_cb = f"favorites_page_{last_page}" if last_page else "show_favorites"
        elif origin.get('type') == 'regular':
            back_cb = f"files_page_{last_page}" if last_page else "show_regular_files"
        else:
            # ברירת מחדל: חזרה לתפריט הקבצים, לא לולאה של אותו מסך
            back_cb = f"files_page_{last_page}" if last_page else "files"
        keyboard.append([InlineKeyboardButton("🔙 חזרה לרשימה", callback_data=back_cb)])
        note = file_data.get('description') or ''
        if note:
            try:
                safe_note_md = TextUtils.escape_markdown(note, version=1)
            except Exception:
                safe_note_md = str(note).replace('`', '\\`').replace('*', '\\*').replace('_', '\\_')
            note_line = f"\n📝 הערה: {safe_note_md}\n\n"
        else:
            note_line = "\n📝 הערה: —\n\n"
        # הוסף כפתור מועדפים גם במסך "מרכז בקרה מתקדם"
        try:
            from src.infrastructure.composition import get_files_facade  # type: ignore
            is_fav_now = bool(get_files_facade().is_favorite(update.effective_user.id, file_name))
        except Exception:
            is_fav_now = False
        fav_text = ("💔 הסר ממועדפים" if is_fav_now else "⭐ הוסף למועדפים")
        raw_id = file_id_str
        if raw_id and (len("fav_toggle_id:") + len(raw_id)) <= 60:
            fav_cb = f"fav_toggle_id:{raw_id}"
        else:
            try:
                tok = secrets.token_urlsafe(6)
            except Exception:
                tok = "t"
            short_tok = (tok[:24] if isinstance(tok, str) else "t")
            try:
                tokens_map = context.user_data.get('fav_tokens') or {}
                tokens_map[short_tok] = file_name
                context.user_data['fav_tokens'] = tokens_map
            except Exception:
                pass
            fav_cb = f"fav_toggle_tok:{short_tok}"
        # הוסף שורת מועדפים לפני היסטוריה/הורדה
        keyboard.insert(3, [InlineKeyboardButton(fav_text, callback_data=fav_cb)])
        reply_markup = InlineKeyboardMarkup(keyboard)

        await TelegramUtils.safe_edit_message_text(
            query,
            f"🎯 *מרכז בקרה מתקדם*\n\n"
            f"📄 **קובץ:** `{file_name}`\n"
            f"🧠 **שפה:** {language}{note_line}"
            f"🎮 בחר פעולה מתקדמת:",
            reply_markup=reply_markup,
            parse_mode='Markdown',
        )
    except Exception as e:
        logger.error(f"Error in handle_file_menu: {e}")
        await TelegramUtils.safe_edit_message_text(query, "💥 שגיאה במרכז הבקרה המתקדם")
    return ConversationHandler.END


async def handle_view_file(update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Display file content with actions (edit, history, download)."""
    query = update.callback_query
    await query.answer()
    try:
        file_index = query.data.split('_')[1]
        files_cache = context.user_data.get('files_cache', {})
        file_data = files_cache.get(file_index)
        if not file_data:
            await TelegramUtils.safe_edit_message_text(query, "⚠️ הקובץ נעלם מהמערכת החכמה")
            return ConversationHandler.END
        file_name = file_data.get('file_name', 'קובץ')
        code = file_data.get('code', '')
        language = file_data.get('programming_language', 'text')
        version = file_data.get('version', 1)
        try:
            file_id_str = str(file_data.get('_id') or '')
        except Exception:
            file_id_str = ''

        # טעינת קוד עצלה: אם ברשימות שמרנו רק מטא־דאטה ללא code, שלוף גרסה אחרונה מה-DB
        if not code:
            # נסה קודם דרך שכבת האפליקציה (Composition Root), נפילה ל-DB ישיר לתאימות
            user_id = update.effective_user.id
            loaded = False
            try:
                from src.infrastructure.composition import get_snippet_service  # type: ignore
                svc = get_snippet_service()
                snippet = await _call_service_method(svc, "get_snippet", user_id, file_name)
                if snippet:
                    code = getattr(snippet, "code", "") or ""
                    language = getattr(snippet, "language", language) or language
                    version = getattr(snippet, "version", version) or version
                    loaded = True
            except Exception:
                loaded = False
            if not loaded:
                try:
                    from src.infrastructure.composition import get_files_facade  # type: ignore
                    latest_doc = get_files_facade().get_latest_version(user_id, file_name)
                    if latest_doc:
                        code = latest_doc.get('code', '') or ''
                        language = latest_doc.get('programming_language', language) or language
                        version = latest_doc.get('version', version) or version
                        try:
                            file_id_str = str(latest_doc.get('_id') or file_id_str)
                        except Exception:
                            pass
                        loaded = True
                except Exception:
                    pass
            if loaded:
                # עדכן cache לזיהוי חזרה/המשך "הצג עוד"
                try:
                    files_cache[str(file_index)] = dict(file_data, code=code, programming_language=language, version=version)
                    context.user_data['files_cache'] = files_cache
                except Exception:
                    pass
        # אם השפה שמורה כ-text/ריקה או (markdown עם תוכן שהוא קוד ברור) – נזהה מחדש להצגה דרך מקור אחיד
        try:
            lang_lower = str(language or "").lower()
            file_name_lower = str(file_name or "").lower()
            is_md_name = file_name_lower.endswith((".md", ".markdown", ".mdown", ".mkd", ".mkdn"))
            if (not lang_lower) or lang_lower == "text" or (lang_lower == "markdown" and is_md_name):
                new_lang = code_service.detect_language(code, file_name)
                if new_lang and new_lang != language:
                    language = new_lang
                    # עדכן cache לשימוש בהמשך
                    try:
                        files_cache[str(file_index)] = dict(file_data, programming_language=language)
                        context.user_data['files_cache'] = files_cache
                    except Exception:
                        pass
        except Exception:
            pass
        max_length = 3500
        code_preview = code[:max_length]
        last_page = context.user_data.get('files_last_page')
        origin = context.user_data.get('files_origin') or {}
        # קביעה אחידה של יעד כפתור "חזרה" לפי מקור הרשימה
        if origin.get('type') == 'by_repo' and origin.get('tag'):
            back_cb = f"by_repo:{origin.get('tag')}"
        elif origin.get('type') == 'favorites':
            back_cb = f"favorites_page_{last_page}" if last_page else "show_favorites"
        elif origin.get('type') == 'regular':
            back_cb = f"files_page_{last_page}" if last_page else "show_regular_files"
        else:
            # ברירת מחדל: חזרה לתפריט הקבצים, לא לולאה של אותו מסך
            back_cb = f"files_page_{last_page}" if last_page else "files"
        keyboard = [
            [
                InlineKeyboardButton("✏️ ערוך קוד", callback_data=f"edit_code_{file_index}"),
                InlineKeyboardButton("📝 ערוך שם", callback_data=f"edit_name_{file_index}"),
            ],
            [
                InlineKeyboardButton("📝 ערוך הערה", callback_data=f"edit_note_{file_index}"),
                InlineKeyboardButton("📚 היסטוריה", callback_data=f"versions_{file_index}"),
            ],
            [
                InlineKeyboardButton("📥 הורד", callback_data=f"dl_{file_index}"),
                InlineKeyboardButton("🔄 שכפול", callback_data=f"clone_{file_index}"),
            ],
            [InlineKeyboardButton("🔙 חזרה", callback_data=back_cb)],
        ]
        webapp_row = _get_webapp_button_row(file_id_str or None, file_name)
        share_row = list(webapp_row) if webapp_row else []
        share_row.append(InlineKeyboardButton("🔗 שתף קוד", callback_data=f"share_menu_idx:{file_index}"))
        keyboard.insert(3, share_row)
        # כפתור מועדפים (הוסף/הסר) לפי המצב הנוכחי
        try:
            from src.infrastructure.composition import get_files_facade  # type: ignore
            is_fav_now = bool(get_files_facade().is_favorite(update.effective_user.id, file_name))
        except Exception:
            is_fav_now = False
        fav_text = ("💔 הסר ממועדפים" if is_fav_now else "⭐ הוסף למועדפים")
        # בנה callback בטוח: העדף מזהה מסד אם קיים, אחרת טוקן קצר במיפוי זמני
        raw_id = file_id_str
        if raw_id and (len("fav_toggle_id:") + len(raw_id)) <= 60:
            fav_cb = f"fav_toggle_id:{raw_id}"
        else:
            try:
                tok = secrets.token_urlsafe(6)
            except Exception:
                tok = "t"
            short_tok = (tok[:24] if isinstance(tok, str) else "t")
            try:
                tokens_map = context.user_data.get('fav_tokens') or {}
                tokens_map[short_tok] = file_name
                context.user_data['fav_tokens'] = tokens_map
            except Exception:
                pass
            fav_cb = f"fav_toggle_tok:{short_tok}"
        # הוסף את כפתור המועדפים לפני כפתור החזרה
        keyboard.insert(-1, [InlineKeyboardButton(fav_text, callback_data=fav_cb)])
        # הוספת כפתור "הצג עוד" אם יש עוד תוכן
        note = file_data.get('description') or ''
        note_line = f"\n📝 הערה: {html_escape(note)}\n" if note else "\n📝 הערה: —\n"
        # אחידות: תמיד HTML עם <pre><code>, אך נכבד מגבלת 4096 לאחר escape
        header_html = (
            f"📄 <b>{html_escape(file_name)}</b> ({html_escape(language)}) - גרסה {version}{note_line}\n"
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
        code_preview = code[:preview_raw_limit]
        if preview_raw_limit < len(code):
            next_chunk = code[preview_raw_limit:preview_raw_limit + max_length]
            next_lines = next_chunk.count('\n') or (1 if next_chunk else 0)
            show_more_label = f"הצג עוד {next_lines} שורות ⤵️"
            keyboard.insert(-1, [InlineKeyboardButton(show_more_label, callback_data=f"fv_more:idx:{file_index}:{preview_raw_limit}")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        # ניסיון: MarkdownV2 עם תג שפה בבלוק קוד (כדי לקבל תווית שפה + הדגשת תחביר בצד הלקוח)
        message_text = f"{header_html}<pre><code>{safe_code}</code></pre>"
        parse_mode = 'HTML'
        try:
            file_name_lower = str(file_name or "").lower()
        except Exception:
            file_name_lower = ""
        try:
            language_lower = str(language or "").lower()
        except Exception:
            language_lower = ""
        is_markdown_language = language_lower == 'markdown' or file_name_lower.endswith('.md') or file_name_lower.endswith('.markdown')
        # העדף MarkdownV2 כדי לקבל תווית שפה + הדגשת תחביר בצד הלקוח.
        # חריג: קבצי Markdown נשארים ב-HTML כדי לא לשבור תצוגת Markdown טבעית.
        if not is_markdown_language:
            try:
                safe_file_name_md = TextUtils.escape_markdown(str(file_name), version=2)
                safe_language_md = TextUtils.escape_markdown(str(language), version=2)
                safe_note_md = TextUtils.escape_markdown(str(note), version=2) if note else '—'
                header_md = (
                    f"📄 *{safe_file_name_md}*\n"
                    f"🧠 שפה: {safe_language_md}\n"
                    f"🔢 גרסה: {version}\n"
                    f"📝 הערה: {safe_note_md}\n\n"
                )
                lang_tag = _sanitize_codeblock_language_tag(language)
                code_block_body = _sanitize_codeblock_content_for_markdown_v2(code_preview or "")
                closing_newline = "" if code_block_body.endswith("\n") else "\n"
                markdown_payload = f"{header_md}```{lang_tag}\n{code_block_body}{closing_newline}```"
                if len(markdown_payload) <= 4096:
                    message_text = markdown_payload
                    parse_mode = getattr(ParseMode, "MARKDOWN_V2", "MarkdownV2")
            except Exception:
                # fallback ל-HTML (הקיים) אם MarkdownV2 נכשל מכל סיבה
                pass

        await TelegramUtils.safe_edit_message_text(
            query,
            message_text,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
        )
    except Exception as e:
        logger.error(f"Error in handle_view_file: {e}")
        await TelegramUtils.safe_edit_message_text(query, "❌ שגיאה בהצגת הקוד המתקדם")
    return ConversationHandler.END


async def handle_edit_code(update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    try:
        file_index = query.data.split('_')[2]
        files_cache = context.user_data.get('files_cache', {})
        file_data = files_cache.get(file_index)
        if not file_data:
            await TelegramUtils.safe_edit_message_text(query, "❌ שגיאה בזיהוי הקובץ")
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
            parse_mode='Markdown',
        )
        return EDIT_CODE
    except Exception as e:
        logger.error(f"Error in handle_edit_code: {e}")
        await TelegramUtils.safe_edit_message_text(query, "❌ שגיאה בהתחלת עריכה\n\n🔄 אנא נסה שוב או חזור לתפריט הראשי\n📞 אם הבעיה נמשכת, פנה לתמיכה")
    return ConversationHandler.END


async def receive_new_code(update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if context.user_data.get('editing_note_file'):
        note_text = (update.message.text or '').strip()
        file_name = context.user_data.pop('editing_note_file')
        user_id = update.effective_user.id
        try:
            # שליפת גרסה אחרונה דרך Facade, עדכון הערה דרך save_code_snippet.
            # טרי ולא דרך ``get_latest_version``: הקוד והשפה שנקראים כאן **נכתבים**
            # לגרסה החדשה, והגרסה המקוּשה יכולה להיות מלפני עריכה בוובאפ.
            # קריאה שנכשלה זורקת (ה-facade מבקש ``raise_on_error=True``), והחריגה עולה
            # ל-``except`` שלמטה, שרושם אותה ועונה "שגיאה" — ולא נבלעת ל"הקובץ לא נמצא".
            from src.infrastructure.composition import get_files_facade  # type: ignore
            _facade = get_files_facade()
            doc = _facade.get_latest_version_fresh(user_id, file_name)
            if not doc:
                await update.message.reply_text("❌ הקובץ לא נמצא לעדכון הערה")
                return ConversationHandler.END
            desc = ("" if note_text.lower() == 'מחק' else note_text)[:280]
            ok = False
            try:
                if _facade is not None:
                    ok = bool(_facade.save_code_snippet(
                        user_id=user_id,
                        file_name=file_name,
                        code=doc.get('code', '') or '',
                        programming_language=doc.get('programming_language', 'text') or 'text',
                        description=desc,
                    ))
            except Exception:
                ok = False
            # אין fallback לייבוא DB ישיר; אם ה-facade אינו זמין – ok יישאר False
            if ok:
                await update.message.reply_text(
                    "✅ הערה עודכנה בהצלחה!",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 חזרה", callback_data=f"view_direct_{file_name}")]]),
                )
            else:
                await update.message.reply_text("❌ שגיאה בעדכון ההערה")
        except Exception as e:
            logger.error(f"Error updating note: {e}")
            await update.message.reply_text("❌ שגיאה בעדכון ההערה")
        return ConversationHandler.END

    # שחזור טקסט עם סימוני Markdown שנבלעו ע"י לקוח טלגרם
    try:
        new_code = TelegramUtils.extract_message_text_preserve_markdown(update.message)
    except Exception:
        new_code = update.message.text
    editing_large_file = context.user_data.get('editing_large_file')
    if editing_large_file:
        try:
            user_id = update.effective_user.id
            file_name = editing_large_file['file_name']
            # זיהוי עקבי גם בקבצים גדולים: מקור אחיד דרך code_service
            from services import code_service
            language = code_service.detect_language(new_code, file_name)
            facade = _get_files_facade()
            success = bool(facade and facade.save_large_file(
                user_id=user_id,
                file_name=file_name,
                content=new_code,
                programming_language=language,
                file_size=len(new_code.encode('utf-8')),
                lines_count=len(new_code.split('\n')),
            ))
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
                    parse_mode='Markdown',
                )
                context.user_data.pop('editing_large_file', None)
            else:
                await update.message.reply_text("❌ שגיאה בעדכון הקובץ הגדול")
            return ConversationHandler.END
        except Exception as e:
            logger.error(f"Error updating large file: {e}")
            await update.message.reply_text("❌ שגיאה בעדכון הקובץ")
            return ConversationHandler.END

    file_data = context.user_data.get('editing_file_data')
    if not file_data:
        await update.message.reply_text("❌ שגיאה בנתוני הקובץ")
        return ConversationHandler.END
    try:
        user_id = update.effective_user.id
        file_name = context.user_data.get('editing_file_name') or file_data.get('file_name')
        editing_file_index = context.user_data.get('editing_file_index')
        files_cache = context.user_data.get('files_cache')
        is_valid, cleaned_code, error_message = code_service.validate_code_input(new_code, file_name, user_id)
        if not is_valid:
            await update.message.reply_text(
                f"❌ שגיאה בקלט הקוד:\n{error_message}\n\n"
                f"💡 אנא וודא שהקוד תקין ונסה שוב.",
                reply_markup=ReplyKeyboardMarkup(_get_main_keyboard(), resize_keyboard=True),
            )
            return EDIT_CODE
        detected_language = code_service.detect_language(cleaned_code, file_name)
        facade = _get_files_facade()
        success = bool(facade and facade.save_file(user_id, file_name, cleaned_code, detected_language))
        if success:
            try:
                last_version = get_files_facade().get_latest_version(user_id, file_name)  # type: ignore[name-defined]
            except Exception:
                last_version = None
            version_num = last_version.get('version', 1) if last_version else 1
            try:
                fid = str((last_version or {}).get('_id') or '')
            except Exception:
                fid = ''
            webapp_row = _get_webapp_button_row(fid, file_name)
            keyboard = [
                [
                    InlineKeyboardButton("👁️ הצג קוד מעודכן", callback_data=(f"view_direct_id:{fid}" if fid else f"view_direct_{file_name}")),
                    InlineKeyboardButton("📚 היסטוריה", callback_data=f"versions_file_{file_name}"),
                ],
                [
                    InlineKeyboardButton("📥 הורד", callback_data=f"download_direct_{file_name}"),
                    InlineKeyboardButton("🔙 לרשימה", callback_data="files"),
                ],
            ]
            if webapp_row:
                keyboard.insert(0, webapp_row)
            reply_markup = InlineKeyboardMarkup(keyboard)
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
                parse_mode='Markdown',
            )
        else:
            await update.message.reply_text(
                "❌ שגיאה בעדכון הקוד",
                reply_markup=ReplyKeyboardMarkup(_get_main_keyboard(), resize_keyboard=True),
            )
    except Exception as e:
        logger.error(f"Error updating code: {e}")
        await update.message.reply_text(
            "❌ שגיאה בעדכון הקוד\n\n📝 **פרטים:** פרטי השגיאה לא זמינים\n🔄 אנא נסה שוב או פנה לתמיכה\n🏠 חזרה לתפריט הראשי",
            reply_markup=ReplyKeyboardMarkup(_get_main_keyboard(), resize_keyboard=True),
            parse_mode='Markdown',
        )
    preserved_cache = context.user_data.get('files_cache')
    context.user_data.clear()
    if preserved_cache is not None:
        context.user_data['files_cache'] = preserved_cache
    return ConversationHandler.END


async def handle_edit_name(update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    try:
        file_index = query.data.split('_')[2]
        files_cache = context.user_data.get('files_cache', {})
        file_data = files_cache.get(file_index)
        if not file_data:
            await TelegramUtils.safe_edit_message_text(query, "❌ שגיאה בזיהוי הקובץ")
            return ConversationHandler.END
        context.user_data['editing_file_index'] = file_index
        context.user_data['editing_file_data'] = file_data
        current_name = file_data.get('file_name', 'קובץ')
        await TelegramUtils.safe_edit_message_text(
            query,
            f"📝 *עריכת שם קובץ*\n\n"
            f"📄 **שם נוכחי:** `{current_name}`\n\n"
            f"✏️ שלח שם חדש לקובץ:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 חזרה", callback_data=f"file_{file_index}")]]),
            parse_mode='Markdown',
        )
        return EDIT_NAME
    except Exception as e:
        logger.error(f"Error in handle_edit_name: {e}")
        await TelegramUtils.safe_edit_message_text(query, "❌ שגיאה בהתחלת עריכת שם")
    return ConversationHandler.END


async def handle_edit_note(update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    try:
        file_index = query.data.split('_')[2]
        files_cache = context.user_data.get('files_cache', {})
        file_data = files_cache.get(file_index)
        if not file_data:
            await TelegramUtils.safe_edit_message_text(query, "❌ שגיאה בזיהוי הקובץ")
            return ConversationHandler.END
        file_name = file_data.get('file_name', 'קובץ')
        current_note = file_data.get('description', '') or '—'
        context.user_data['editing_note_file'] = file_name
        await TelegramUtils.safe_edit_message_text(
            query,
            f"📝 *עריכת הערה לקובץ*\n\n"
            f"📄 **שם:** `{file_name}`\n"
            f"🔎 **הערה נוכחית:** {html_escape(current_note)}\n\n"
            f"✏️ שלח/י הערה חדשה (או 'מחק' כדי להסיר)",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 חזרה", callback_data=f"file_{file_index}")]]),
            parse_mode='Markdown',
        )
        return EDIT_CODE
    except Exception as e:
        logger.error(f"Error in handle_edit_note: {e}")
        await TelegramUtils.safe_edit_message_text(query, "❌ שגיאה בהתחלת עריכת הערה")
    return ConversationHandler.END


async def receive_new_name(update, context: ContextTypes.DEFAULT_TYPE) -> int:
    new_name = update.message.text.strip()
    file_data = context.user_data.get('editing_file_data')
    if not file_data:
        await update.message.reply_text("❌ שגיאה בנתוני הקובץ")
        return ConversationHandler.END
    # אפשר גם שמות ללא סיומת (Dockerfile/Makefile) ודוטפיילז (.gitignore)
    if not ValidationUtils.is_valid_filename(new_name):
        await update.message.reply_text(
            "🤔 השם נראה קצת מוזר...\n"
            "💡 נסה שם כמו: `script.py` או `index.html`\n"
            "✅ אותיות, מספרים, נקודות וקווים מותרים!",
        )
        return EDIT_NAME
    try:
        user_id = update.effective_user.id
        old_name = context.user_data.get('editing_file_name') or file_data.get('file_name')
        # דרך ה-FilesFacade מה-Composition Root
        try:
            from src.infrastructure.composition import get_files_facade  # type: ignore
            success = bool(get_files_facade().rename_file(user_id, old_name, new_name))
        except Exception:
            success = False
        if success:
            # חשב fid עבור הכפתור 'הצג קוד' בהעדפת ID אם זמין
            try:
                try:
                    latest_doc = get_files_facade().get_latest_version(user_id, new_name)  # type: ignore[name-defined]
                except Exception:
                    latest_doc = {}
                fid = str(latest_doc.get('_id') or '')
            except Exception:
                fid = ''
            keyboard = [
                [
                    InlineKeyboardButton("👁️ הצג קוד", callback_data=(f"view_direct_id:{fid}" if fid else f"view_direct_{new_name}")),
                    InlineKeyboardButton("📚 היסטוריה", callback_data=f"versions_file_{new_name}"),
                ],
                [
                    InlineKeyboardButton("📥 הורד", callback_data=f"download_direct_{new_name}"),
                    InlineKeyboardButton("🔙 לרשימה", callback_data="files"),
                ],
            ]
            webapp_row = _get_webapp_button_row(fid, new_name)
            if webapp_row:
                keyboard.insert(0, webapp_row)
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(
                f"✅ *שם הקובץ שונה בהצלחה!*\n\n"
                f"📄 **שם ישן:** `{old_name}`\n"
                f"📄 **שם חדש:** `{new_name}`\n"
                f"🎉 **הכל מעודכן במערכת!**",
                reply_markup=reply_markup,
                parse_mode='Markdown',
            )
        else:
            await update.message.reply_text(
                "❌ שגיאה בשינוי השם",
                reply_markup=ReplyKeyboardMarkup(_get_main_keyboard(), resize_keyboard=True),
            )
    except Exception as e:
        logger.error(f"Error renaming file: {e}")
        await update.message.reply_text(
            "❌ שגיאה בשינוי השם",
            reply_markup=ReplyKeyboardMarkup(_get_main_keyboard(), resize_keyboard=True),
        )
    context.user_data.clear()
    return ConversationHandler.END


async def handle_versions_history(update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    try:
        data = query.data
        file_index: Optional[str] = None
        files_cache = context.user_data.get('files_cache', {})
        if data.startswith("versions_file_"):
            file_name = data.replace("versions_file_", "", 1)
        else:
            file_index = data.split('_')[1]
            file_data = files_cache.get(file_index)
            if not file_data:
                await query.edit_message_text("❌ שגיאה בזיהוי הקובץ")
                return ConversationHandler.END
            file_name = file_data.get('file_name')
        user_id = update.effective_user.id
        try:
            from src.infrastructure.composition import get_files_facade  # type: ignore
            versions = get_files_facade().get_all_versions(user_id, file_name)
        except Exception:
            versions = []
        if not versions:
            await query.edit_message_text("📚 אין היסטוריית גרסאות לקובץ זה")
            return ConversationHandler.END
        latest_version_num = versions[0].get('version') if versions and isinstance(versions[0], dict) else None
        history_text = f"📚 *היסטוריית גרסאות - {file_name}*\n\n"
        keyboard: List[List[InlineKeyboardButton]] = []
        for i, version in enumerate(versions[:5]):
            created_at = version.get('created_at', 'לא ידוע')
            version_num = version.get('version', i + 1)
            code_length = len(version.get('code', ''))
            history_text += f"🔹 **גרסה {version_num}**\n"
            history_text += f"   📅 {created_at}\n"
            history_text += f"   📏 {code_length:,} תווים\n\n"
            if latest_version_num is not None and version_num == latest_version_num:
                keyboard.append([
                    InlineKeyboardButton(
                        f"👁 הצג גרסה {version_num}", callback_data=f"view_version_{version_num}_{file_name}"
                    )
                ])
            else:
                keyboard.append([
                    InlineKeyboardButton(
                        f"👁 הצג גרסה {version_num}", callback_data=f"view_version_{version_num}_{file_name}"
                    ),
                    InlineKeyboardButton(
                        f"↩️ שחזר לגרסה {version_num}", callback_data=f"revert_version_{version_num}_{file_name}"
                    ),
                ])
        if file_index is not None:
            keyboard.append([InlineKeyboardButton("🔙 חזרה", callback_data=f"file_{file_index}")])
        else:
            keyboard.append([InlineKeyboardButton("🔙 חזרה", callback_data=f"view_direct_{file_name}")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(history_text, reply_markup=reply_markup, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Error in handle_versions_history: {e}")
        await query.edit_message_text("❌ שגיאה בהצגת היסטוריה")
    return ConversationHandler.END


async def handle_download_file(update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    try:
        data = query.data
        files_cache = context.user_data.get('files_cache', {})
        file_name: Optional[str] = None
        code: str = ''
        if data.startswith('dl_'):
            file_index = data.split('_')[1]
            file_data = files_cache.get(file_index)
            if not file_data:
                await query.edit_message_text("❌ שגיאה בזיהוי הקובץ")
                return ConversationHandler.END
            file_name = file_data.get('file_name', 'file.txt')
            code = file_data.get('code', '')
        elif data.startswith('download_direct_'):
            file_name = data.replace('download_direct_', '', 1)
            if not isinstance(file_name, str):
                await query.edit_message_text("❌ שם קובץ שגוי להורדה")
                return ConversationHandler.END
            user_id = update.effective_user.id
            try:
                from src.infrastructure.composition import get_files_facade  # type: ignore
                latest = get_files_facade().get_latest_version(user_id, file_name)
            except Exception:
                latest = None
            if not latest:
                await query.edit_message_text("❌ לא נמצאה גרסה אחרונה לקובץ")
                return ConversationHandler.END
            code = latest.get('code', '')
        else:
            await query.edit_message_text("❌ בקשת הורדה לא חוקית")
            return ConversationHandler.END
        file_bytes = BytesIO()
        file_bytes.write(code.encode('utf-8'))
        file_bytes.seek(0)
        await query.message.reply_document(
            document=file_bytes,
            filename=file_name,
            caption=f"📥 *הורדת קובץ*\n\n📄 **שם:** `{file_name}`\n📏 **גודל:** {len(code):,} תווים",
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
            parse_mode='Markdown',
        )
    except Exception as e:
        logger.error(f"Error in handle_download_file: {e}")
        await query.edit_message_text("❌ שגיאה בהורדת הקובץ")
    return ConversationHandler.END


async def handle_delete_confirmation(update, context: ContextTypes.DEFAULT_TYPE) -> int:
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
        keyboard = [[
            InlineKeyboardButton("✅ כן, העבר לסל מיחזור", callback_data=f"confirm_del_{file_index}"),
            InlineKeyboardButton("❌ לא, בטל", callback_data=f"file_{file_index}"),
        ]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            f"⚠️ *אישור מחיקה*\n\n"
            f"📄 **קובץ:** `{file_name}`\n\n"
            f"🗑️ האם להעביר את הקובץ לסל המיחזור?\n"
            f"♻️ ניתן לשחזר מתוך סל המיחזור עד פקיעת התוקף",
            reply_markup=reply_markup,
            parse_mode='Markdown',
        )
    except Exception as e:
        logger.error(f"Error in handle_delete_confirmation: {e}")
        await query.edit_message_text("❌ שגיאה באישור מחיקה")
    return ConversationHandler.END


async def handle_delete_file(update, context: ContextTypes.DEFAULT_TYPE) -> int:
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
        try:
            from src.infrastructure.composition import get_files_facade  # type: ignore
            success = bool(get_files_facade().delete_file(user_id, file_name))
        except Exception:
            success = False
        if success:
            keyboard = [[InlineKeyboardButton("🔙 לרשימת קבצים", callback_data="files")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                f"✅ *הקובץ הועבר לסל המיחזור!*\n\n"
                f"📄 **קובץ:** `{file_name}`\n"
                f"♻️ ניתן לשחזר אותו מתפריט '🗑️ סל מיחזור' עד למחיקה אוטומטית",
                reply_markup=reply_markup,
                parse_mode='Markdown',
            )
        else:
            await query.edit_message_text(f"❌ שגיאה במחיקת הקובץ `{file_name}`")
    except Exception as e:
        logger.error(f"Error in handle_delete_file: {e}")
        await query.edit_message_text("❌ שגיאה במחיקת הקובץ")
    return ConversationHandler.END


async def handle_file_info(update, context: ContextTypes.DEFAULT_TYPE) -> int:
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
        keyboard = [[InlineKeyboardButton("🔙 חזרה", callback_data=f"file_{file_index}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(info_text, reply_markup=reply_markup, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Error in handle_file_info: {e}")
        await query.edit_message_text("❌ שגיאה בהצגת מידע")
    return ConversationHandler.END


async def handle_view_direct_file(update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    try:
        data = query.data
        token = data.replace("view_direct_", "", 1)
        user_id = update.effective_user.id
        file_data = None
        file_name = None
        is_large_file = False

        if token.startswith("id:"):
            file_id = token[3:]
            try:
                from src.infrastructure.composition import get_files_facade  # type: ignore
                doc = get_files_facade().get_file_by_id(file_id)
            except Exception:
                doc = None
            if not doc:
                try:
                    from src.infrastructure.composition import get_files_facade  # type: ignore
                    lf = get_files_facade().get_large_file_by_id(file_id)
                except Exception:
                    lf = None
                if lf:
                    is_large_file = True
                    file_name = lf.get('file_name') or 'file'
                    file_data = {
                        'file_name': file_name,
                        'code': lf.get('content', ''),
                        'programming_language': lf.get('programming_language', 'text'),
                        'version': 1,
                        'description': lf.get('description', ''),
                        '_id': lf.get('_id')
                    }
                else:
                    await _edit_message_text_unified(query, "⚠️ הקובץ לא נמצא")
                    return ConversationHandler.END
            else:
                file_name = doc.get('file_name') or 'file'
                file_data = doc
        else:
            file_name = token
            try:
                from src.infrastructure.composition import get_files_facade  # type: ignore
                file_data = get_files_facade().get_latest_version(user_id, file_name)
            except Exception:
                file_data = None
        # תמיכה בקבצים גדולים: אם לא נמצא בקולקציה הרגילה, ננסה large_files
        if not file_data and file_name:
            try:
                from src.infrastructure.composition import get_files_facade  # type: ignore
                lf = get_files_facade().get_large_file(user_id, file_name)
            except Exception:
                lf = None
            if lf:
                is_large_file = True
                file_data = {
                    'file_name': lf.get('file_name', file_name),
                    'code': lf.get('content', ''),
                    'programming_language': lf.get('programming_language', 'text'),
                    'version': 1,
                    'description': lf.get('description', ''),
                    '_id': lf.get('_id')
                }
            else:
                await _edit_message_text_unified(query, "⚠️ הקובץ נעלם מהמערכת החכמה")
                return ConversationHandler.END
        code = file_data.get('code', '')
        language = file_data.get('programming_language', 'text')
        version = file_data.get('version', 1)
        max_length = 3500
        code_preview = code[:max_length]
        # נסה להשיג ObjectId לצורך שיתוף
        try:
            fid = str(file_data.get('_id') or '')
        except Exception:
            fid = ''

        # יעד כפתור "חזרה" לפי מקור הרשימה אם קיים; אחרת חזרה אחרי תצוגה ישירה
        try:
            last_page = context.user_data.get('files_last_page')
            origin = context.user_data.get('files_origin') or {}
            if origin.get('type') == 'by_repo' and origin.get('tag'):
                back_cb = f"by_repo:{origin.get('tag')}"
            elif origin.get('type') == 'favorites':
                back_cb = f"favorites_page_{last_page}" if last_page else "show_favorites"
            elif origin.get('type') == 'regular':
                back_cb = f"files_page_{last_page}" if last_page else "show_regular_files"
            else:
                back_cb = f"back_after_view:{file_name}"
        except Exception:
            back_cb = f"back_after_view:{file_name}"
        keyboard = [
            [
                InlineKeyboardButton("✏️ ערוך קוד", callback_data=f"edit_code_direct_{file_name}"),
                InlineKeyboardButton("📝 ערוך שם", callback_data=f"edit_name_direct_{file_name}"),
            ],
            [
                InlineKeyboardButton("📝 ערוך הערה", callback_data=f"edit_note_direct_{file_name}"),
                InlineKeyboardButton("📚 היסטוריה", callback_data=f"versions_file_{file_name}"),
            ],
            [
                InlineKeyboardButton("📥 הורד", callback_data=f"download_direct_{file_name}"),
                InlineKeyboardButton("🔄 שכפול", callback_data=f"clone_direct_{file_name}"),
            ],
            [
                InlineKeyboardButton("🔗 שתף קוד", callback_data=f"share_menu_id:{fid}") if fid else InlineKeyboardButton("🔗 שתף קוד", callback_data=f"share_menu_id:")
            ],
            [InlineKeyboardButton("🔙 חזרה", callback_data=back_cb)],
        ]
        view_target_id = fid if not is_large_file else None
        webapp_row = _get_webapp_button_row(view_target_id, file_name)
        if webapp_row:
            keyboard.insert(0, webapp_row)
        # כפתור מועדפים (הוסף/הסר) לפי המצב הנוכחי
        try:
            from src.infrastructure.composition import get_files_facade  # type: ignore
            is_fav_now = bool(get_files_facade().is_favorite(update.effective_user.id, file_name))
        except Exception:
            is_fav_now = False
        fav_text = ("💔 הסר ממועדפים" if is_fav_now else "⭐ הוסף למועדפים")
        # בנה callback בטוח: העדף מזהה מסד אם קיים, אחרת טוקן קצר במיפוי זמני
        if fid and (len("fav_toggle_id:") + len(fid)) <= 60:
            fav_cb = f"fav_toggle_id:{fid}"
        else:
            try:
                tok = secrets.token_urlsafe(6)
            except Exception:
                tok = "t"
            short_tok = (tok[:24] if isinstance(tok, str) else "t")
            try:
                tokens_map = context.user_data.get('fav_tokens') or {}
                tokens_map[short_tok] = file_name
                context.user_data['fav_tokens'] = tokens_map
            except Exception:
                pass
            fav_cb = f"fav_toggle_tok:{short_tok}"
        # הוסף את כפתור המועדפים לפני כפתור החזרה
        keyboard.insert(-1, [InlineKeyboardButton(fav_text, callback_data=fav_cb)])
        note = file_data.get('description') or ''
        note_line_html = f"\n📝 הערה: {html_escape(note)}\n\n" if note else "\n📝 הערה: —\n\n"
        large_note_html = "\n<i>זה קובץ גדול</i>\n\n" if is_large_file else ""
        header_html = (
            f"📄 <b>{html_escape(file_name)}</b> ({html_escape(language)}) - גרסה {version}"
            f"{note_line_html}{large_note_html}"
        )
        if not header_html.endswith("\n"):
            header_html += "\n"
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
        code_preview = code[:preview_raw_limit]
        safe_code = html_escape(code_preview)
        if preview_raw_limit < len(code):
            next_chunk = code[preview_raw_limit:preview_raw_limit + max_length]
            next_lines = next_chunk.count('\n') or (1 if next_chunk else 0)
            show_more_label = f"הצג עוד {next_lines} שורות ⤵️"
            keyboard.insert(-1, [InlineKeyboardButton(show_more_label, callback_data=f"fv_more:direct:{file_name}:{preview_raw_limit}")])
        reply_markup = InlineKeyboardMarkup(keyboard)

        html_payload = f"{header_html}<pre><code>{safe_code}</code></pre>"
        message_text = html_payload
        parse_mode = 'HTML'

        try:
            file_name_lower = str(file_name).lower()
        except Exception:
            file_name_lower = ""
        try:
            language_lower = str(language or "").lower()
        except Exception:
            language_lower = ""
        is_markdown_language = language_lower == 'markdown' or file_name_lower.endswith('.md') or file_name_lower.endswith('.markdown')
        # העדף MarkdownV2 כדי לקבל תווית שפה + הדגשת תחביר.
        # חריגים:
        # - קבצים גדולים: עדיף HTML כדי לשמור עקביות בטעינה מדורגת/כפתור "הצג עוד"
        # - קבצי Markdown: עדיף HTML כדי לא לאבד תצוגת Markdown טבעית
        prefer_markdown = (not is_large_file) and (not is_markdown_language)

        if prefer_markdown:
            try:
                # MarkdownV2 מאפשר גם תג שפה לבלוק קוד (שמפעיל תווית שפה + הדגשת תחביר בצד הלקוח)
                safe_file_name_md = TextUtils.escape_markdown(str(file_name), version=2)
                safe_language_md = TextUtils.escape_markdown(str(language), version=2)
                safe_note_md = TextUtils.escape_markdown(str(note), version=2) if note else '—'
                header_md = (
                    f"📄 *{safe_file_name_md}*\n"
                    f"🧠 שפה: {safe_language_md}\n"
                    f"🔢 גרסה: {version}\n"
                    f"📝 הערה: {safe_note_md}\n\n"
                )
                code_block_body = _sanitize_codeblock_content_for_markdown_v2(code_preview or "")
                closing_newline = "" if code_block_body.endswith("\n") else "\n"
                lang_tag = _sanitize_codeblock_language_tag(language)
                markdown_payload = f"{header_md}```{lang_tag}\n{code_block_body}{closing_newline}```"
                if len(markdown_payload) <= 4096:
                    message_text = markdown_payload
                    parse_mode = getattr(ParseMode, "MARKDOWN_V2", "MarkdownV2")
            except Exception as markdown_err:
                logger.debug("Markdown render fallback to HTML: %s", markdown_err)

        await _edit_message_text_unified(
            query,
            message_text,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
        )
    except Exception as e:
        logger.error(f"Error in handle_view_direct_file: {e}")
        await _edit_message_text_unified(query, "❌ שגיאה בהצגת הקוד המתקדם")
    return ConversationHandler.END


async def handle_edit_code_direct(update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    try:
        file_name = query.data.replace("edit_code_direct_", "")
        user_id = update.effective_user.id
        try:
            from src.infrastructure.composition import get_files_facade  # type: ignore
            file_data = get_files_facade().get_latest_version(user_id, file_name)
        except Exception:
            file_data = None
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
            parse_mode='Markdown',
        )
        return EDIT_CODE
    except Exception as e:
        logger.error(f"Error in handle_edit_code_direct: {e}")
        await query.edit_message_text("❌ שגיאה בהתחלת עריכה")
    return ConversationHandler.END


async def handle_edit_name_direct(update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    try:
        file_name = query.data.replace("edit_name_direct_", "")
        user_id = update.effective_user.id
        try:
            from src.infrastructure.composition import get_files_facade  # type: ignore
            file_data = get_files_facade().get_latest_version(user_id, file_name)
        except Exception:
            file_data = None
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
            parse_mode='Markdown',
        )
        return EDIT_NAME
    except Exception as e:
        logger.error(f"Error in handle_edit_name_direct: {e}")
        await query.edit_message_text("❌ שגיאה בהתחלת עריכת שם")
    return ConversationHandler.END


async def handle_edit_note_direct(update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    try:
        file_name = query.data.replace("edit_note_direct_", "")
        user_id = update.effective_user.id
        try:
            from src.infrastructure.composition import get_files_facade  # type: ignore
            file_data = get_files_facade().get_latest_version(user_id, file_name)
        except Exception:
            file_data = None
        if not file_data:
            await query.edit_message_text("❌ לא נמצא הקובץ לעריכת הערה")
            return ConversationHandler.END
        current_note = file_data.get('description', '') or '—'
        context.user_data['editing_note_file'] = file_name
        await query.edit_message_text(
            f"📝 *עריכת הערה לקובץ*\n\n"
            f"📄 **שם:** `{file_name}`\n"
            f"🔎 **הערה נוכחית:** {html_escape(current_note)}\n\n"
            f"✏️ שלח/י הערה חדשה (או שלח/י 'מחק' כדי להסיר).",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 חזרה", callback_data=f"view_direct_{file_name}")]]),
            parse_mode='Markdown',
        )
        return EDIT_CODE
    except Exception as e:
        logger.exception("Error in handle_edit_note_direct: %s", e)
        await query.edit_message_text("❌ שגיאה בעריכת הערה")
    return ConversationHandler.END


def _suggest_clone_name(facade, user_id: int, name: str) -> str:
    """שם פנוי לעותק של ``name``: ``<stem> (copy)<ext>``, ואחריו ``(copy 2)`` עד ``(copy 99)``.

    "פנוי" נשאל את המסד דרך ``get_latest_version_fresh`` ולא את הקאש: השם נבחר כדי לכתוב אליו,
    והקאש אינו שומר ``None`` — שם שנמחק או ששונה בוובאפ היה נשאר "תפוס" עד שהקאש פג. בדיקה
    שנכשלה זורקת (ה-facade מבקש ``raise_on_error=True``), והחריגה עולה לקורא ואינה נחשבת
    "פנוי": שמירה בשם תפוס הייתה נכתבת כגרסה חדשה של הקובץ האחר, ולא כעותק.
    """
    name = str(name)
    dot = name.rfind('.')
    stem, ext = (name[:dot], name[dot:]) if dot > 0 else (name, '')
    candidate = f"{stem} (copy){ext}"
    if not facade.get_latest_version_fresh(user_id, candidate):
        return candidate
    for i in range(2, 100):
        candidate = f"{stem} (copy {i}){ext}"
        if not facade.get_latest_version_fresh(user_id, candidate):
            return candidate
    return f"{stem} (copy {int(datetime.now(timezone.utc).timestamp())}){ext}"


def _clone_fields(source: dict):
    """(קוד, שפה, תיאור, תגיות) שהעותק מקבל — ממסמך המקור שנקרא מהמסד, לא מרשימת הבוט ולא מהקאש."""
    tags = source.get('tags')
    return (
        source.get('code', ''),
        source.get('programming_language', 'text'),
        source.get('description', '') or '',
        list(tags) if isinstance(tags, (list, tuple)) else [],
    )


async def handle_clone(update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    try:
        file_index = query.data.split('_')[1]
        files_cache = context.user_data.get('files_cache', {})
        file_data = files_cache.get(file_index)
        if not file_data:
            await TelegramUtils.safe_edit_message_text(query, "❌ שגיאה בזיהוי הקובץ לשכפול")
            return ConversationHandler.END
        # הרשומה ברשימה מזהה את הקובץ, ותו לא. את התוכן קוראים מהמסד: ``files_cache`` הוא מה
        # שהיה כשהרשימה הוצגה, בלי שום תוקף, ושכפול ממנו העתיק את מה שהרשימה זכרה ולא את
        # הקובץ — וקובץ שכבר נמחק היה נבנה ממנה מחדש.
        original_name = file_data.get('file_name', 'file.txt')
        user_id = update.effective_user.id
        from src.infrastructure.composition import get_files_facade  # type: ignore
        facade = get_files_facade()
        source = facade.get_latest_version_fresh(user_id, original_name)
        if not source:
            await TelegramUtils.safe_edit_message_text(query, "❌ הקובץ לא נמצא לשכפול")
            return ConversationHandler.END
        code, language, description, tags = _clone_fields(source)
        new_name = _suggest_clone_name(facade, user_id, original_name)
        try:
            from src.infrastructure.composition import get_files_facade  # type: ignore
            ok = bool(get_files_facade().save_code_snippet(
                user_id=user_id,
                file_name=new_name,
                code=code,
                programming_language=language,
                description=description,
                tags=tags,
            ))
        except Exception:
            ok = False
        if ok:
            try:
                # רענון חלקי של ה-cache המקומי אם זמין
                if isinstance(files_cache, dict):
                    files_cache[str(file_index)] = dict(file_data, file_name=original_name)
            except Exception:
                pass
            try:
                from src.infrastructure.composition import get_files_facade  # type: ignore
                latest_doc = get_files_facade().get_latest_version(user_id, new_name) or {}
                fid = str(latest_doc.get('_id') or '')
            except Exception:
                fid = ''
            webapp_row = _get_webapp_button_row(fid, new_name)
            keyboard = [
                [
                    InlineKeyboardButton("👁️ הצג קוד", callback_data=(f"view_direct_id:{fid}" if fid else f"view_direct_{new_name}")),
                    InlineKeyboardButton("📚 היסטוריה", callback_data=f"versions_file_{new_name}"),
                ],
                [
                    InlineKeyboardButton("📥 הורד", callback_data=f"download_direct_{new_name}"),
                    InlineKeyboardButton("🔙 לרשימה", callback_data="files"),
                ],
            ]
            if webapp_row:
                keyboard.insert(0, webapp_row)
            reply_markup = InlineKeyboardMarkup(keyboard)
            await TelegramUtils.safe_edit_message_text(
                query,
                f"✅ *הקובץ שוכפל בהצלחה!*\n\n"
                f"📄 **מקור:** `{original_name}`\n"
                f"📄 **עותק חדש:** `{new_name}`",
                reply_markup=reply_markup,
                parse_mode='Markdown',
            )
        else:
            await TelegramUtils.safe_edit_message_text(query, "❌ שגיאה בשכפול הקובץ")
    except Exception as e:
        logger.error(f"Error in handle_clone: {e}")
        await TelegramUtils.safe_edit_message_text(query, "❌ שגיאה בשכפול הקובץ")
    return ConversationHandler.END


async def handle_clone_direct(update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    try:
        file_name = query.data.replace("clone_direct_", "")
        user_id = update.effective_user.id
        # המקור נקרא מהמסד ולא דרך ``get_latest_version`` המקוּשה: מה שנקרא כאן **נכתב**
        # לעותק, והגרסה המקוּשה יכולה להיות מלפני עריכה בוובאפ. קריאה שנכשלה זורקת
        # (ה-facade מבקש ``raise_on_error=True``), והחריגה עולה ל-``except`` שלמטה ונרשמת
        # — ולא נבלעת ל"הקובץ לא נמצא".
        from src.infrastructure.composition import get_files_facade  # type: ignore
        facade = get_files_facade()
        file_data = facade.get_latest_version_fresh(user_id, file_name)
        if not file_data:
            await query.edit_message_text("❌ הקובץ לא נמצא לשכפול")
            return ConversationHandler.END
        code, language, description, tags = _clone_fields(file_data)
        new_name = _suggest_clone_name(facade, user_id, file_name)
        # יצירת snippet לשמירה דרך Facade
        try:
            from src.infrastructure.composition import get_files_facade  # type: ignore
            ok = bool(get_files_facade().save_code_snippet(
                user_id=user_id,
                file_name=new_name,
                code=code,
                programming_language=language,
                description=description,
                tags=tags,
            ))
        except Exception:
            ok = False
        if ok:
            # חשב fid עבור הכפתור 'הצג קוד' בהעדפת ID אם זמין
            try:
                from src.infrastructure.composition import get_files_facade  # type: ignore
                latest_doc = get_files_facade().get_latest_version(user_id, new_name) or {}
                fid = str(latest_doc.get('_id') or '')
            except Exception:
                fid = ''
            webapp_row = _get_webapp_button_row(fid)
            keyboard = [
                [
                    InlineKeyboardButton("👁️ הצג קוד", callback_data=(f"view_direct_id:{fid}" if fid else f"view_direct_{new_name}")),
                    InlineKeyboardButton("📚 היסטוריה", callback_data=f"versions_file_{new_name}"),
                ],
                [
                    InlineKeyboardButton("📥 הורד", callback_data=f"download_direct_{new_name}"),
                    InlineKeyboardButton("🔙 לרשימה", callback_data="files"),
                ],
            ]
            if webapp_row:
                keyboard.insert(0, webapp_row)
            reply_markup = InlineKeyboardMarkup(keyboard)
            text = (
                f"✅ *הקובץ שוכפל בהצלחה!*\n\n"
                f"📄 **מקור:** `{file_name}`\n"
                f"📄 **עותק חדש:** `{new_name}`"
            )
            await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
        else:
            await query.edit_message_text("❌ שגיאה בשכפול הקובץ")
    except Exception as e:
        logger.error(f"Error in handle_clone_direct: {e}")
        await query.edit_message_text("❌ שגיאה בשכפול הקובץ")
    return ConversationHandler.END
