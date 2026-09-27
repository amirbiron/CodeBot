"""
Code Service Module
===================

שירות עיבוד וניתוח קוד עבור Code Keeper Bot.

מודול זה מספק wrapper לפונקציונליות עיבוד קוד, כולל:
- זיהוי שפות תכנות
- הדגשת תחביר
- ניתוח קוד
- חיפוש בקוד
"""

from typing import Any, Dict, List, Tuple, Optional, Callable, TypeVar
import re
from pathlib import Path
from utils import detect_language_from_filename as _detect_from_filename

# ייבוא רגיל ולא אופציונלי: מסלול שממשיך לשמור בלי הניקוי כשהייבוא נכשל היה
# חוזר בשקט להתנהגות אחרת. המודול טהור, בלי I/O.
from src.domain.services.code_normalizer import PasteCleanup
from src.domain.services.code_normalizer import clean_pasted_code as _clean_pasted_code
from src.domain.services.code_normalizer import is_markdown_filename

try:
    from observability_instrumentation import traced, set_current_span_attributes
except Exception:  # pragma: no cover
    _F = TypeVar("_F", bound=Callable[..., Any])

    def traced(*_a: Any, **_k: Any) -> Callable[[_F], _F]:
        def _inner(func: _F) -> _F:
            return func
        return _inner

    def set_current_span_attributes(*_a: Any, **_k: Any) -> None:
        return None

# Thin wrapper around existing code_processor to allow future swap/refactor
# We keep a loose type here to avoid importing heavy optional deps during type checking/runtime.
try:
    from code_processor import code_processor as _cp
    code_processor: Optional[Any] = _cp
except Exception:  # optional deps (e.g., cairosvg) might be missing locally
    code_processor = None


def _normalize_detected_language(label: Optional[str]) -> Optional[str]:
    """
    מנרמל תוצאות זיהוי משירותים חיצוניים למונחים אחידים בתוך המערכת.
    """
    if not label:
        return None
    normalized = label.strip().lower()
    alias_map = {
        "text only": "text",
        "plain text": "text",
        "plaintext": "text",
        "md": "markdown",
        "gfm": "markdown",
        "github flavored markdown": "markdown",
        "github-flavored markdown": "markdown",
    }
    normalized = alias_map.get(normalized, normalized)
    if not normalized or normalized in {"unknown"}:
        return None
    return normalized


def _fallback_detect_language(code: str, filename: str) -> str:
    """
    זיהוי שפת תכנות לפי סיומת קובץ (fallback).
    
    Args:
        code: קוד המקור
        filename: שם הקובץ
    
    Returns:
        str: שם שפת התכנות שזוהתה
    
    Note:
        פונקציה זו משמשת כ-fallback כאשר code_processor לא זמין
    """
    ext = (filename or "").lower()
    mapping = {
        ".py": "python",
        ".js": "javascript",
        ".jsx": "javascript",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".java": "java",
        ".cpp": "cpp",
        ".cc": "cpp",
        ".cxx": "cpp",
        ".c": "c",
        ".cs": "csharp",
        ".go": "go",
        ".rs": "rust",
        ".rb": "ruby",
        ".php": "php",
        ".swift": "swift",
        ".sh": "bash",
        ".bash": "bash",
        ".sql": "sql",
        ".html": "html",
        ".htm": "html",
        ".css": "css",
        ".json": "json",
        ".yaml": "yaml",
        ".yml": "yaml",
        ".xml": "xml",
        ".md": "markdown",
        "dockerfile": "dockerfile",
        ".toml": "toml",
        ".ini": "ini",
        ".txt": "text",
    }
    for k, v in mapping.items():
        if ext.endswith(k) or ext == k:
            return v
    return "text"


def detect_language(code: str, filename: str) -> str:
    """
    מקור אמת לזיהוי שפה: דטקטור דומייני.
    נשמרים fallback-ים ישנים לתאימות, אך החלטה סופית מגיעה מהדומיין כאשר אפשר.
    """
    # Fast-path special filenames before any heavy detection
    try:
        name = (filename or "").strip()
        name_lower = name.lower()
        base = Path(name_lower).name
        # Taskfile (with or without extension)
        if base.startswith("taskfile"):
            return "yaml"
        # Dotenv variants: .env, .env.local, .env.production, etc.
        if base == ".env" or base.startswith(".env."):
            return "env"
    except Exception:
        pass
    # 1) Domain detector (source of truth)
    try:
        from src.domain.services.language_detector import LanguageDetector
        return LanguageDetector().detect_language(code, filename)
    except Exception:
        pass
    # 2) Filename-only mapping (legacy utils)
    fname = (filename or "").strip()
    mapped = _detect_from_filename(fname)
    if mapped and mapped != "text":
        return mapped
    # 3) Old processor fallback (best-effort)
    if code_processor is not None:
        try:
            detected = _normalize_detected_language(code_processor.detect_language(code, filename))
            if detected:
                return detected
        except Exception:
            pass
    # 4) Final minimal fallback
    return _fallback_detect_language(code or "", filename or "")


@traced("code.validate_input")
def validate_code_input(code: str, file_name: str, user_id: int) -> Tuple[bool, str, str]:
    """
    בודק ומנקה קלט קוד.
    
    Args:
        code: קוד המקור לבדיקה
        file_name: שם הקובץ
        user_id: מזהה המשתמש
    
    Returns:
        Tuple[bool, str, str]: (is_valid, cleaned_code, error_message)
            - is_valid: האם הקוד תקין
            - cleaned_code: הקוד המנוקה
            - error_message: הודעת שגיאה (אם יש)
    """
    try:
        code_length = int(len(code or ""))
    except TypeError:
        code_length = 0
    try:
        set_current_span_attributes({
            "code.length": code_length,
            "file_name": str(file_name or ""),
        })
    except Exception:
        pass
    if code_processor is None:
        # בלי המאמת (תלות אופציונלית חסרה בזמן ייבוא) אין בדיקות — הקוד חוזר כמו שהוא.
        ok = True
        cleaned = code
        msg = ""
    else:
        ok, cleaned, msg = code_processor.validate_code_input(code, file_name, user_id)
    # המאמת אינו מנקה: הניקוי של קוד מודבק הוא ``clean_pasted_code`` שלמטה,
    # וה-handler מריץ אותו פעם אחת לפני האימות.
    try:
        try:
            cleaned_length = int(len(cleaned or ""))
        except TypeError:
            cleaned_length = 0
        span_attrs = {
            "validation.ok": bool(ok),
            "status": "ok" if ok else "error",
            "cleaned.length": cleaned_length,
            "code.length.original": code_length,
        }
        if file_name:
            span_attrs["file_name"] = str(file_name)
        if msg:
            span_attrs["error.message"] = str(msg)
        set_current_span_attributes(span_attrs)
    except Exception:
        pass
    return ok, cleaned, msg


def clean_pasted_code(code: Optional[str], file_name: Optional[str]) -> PasteCleanup:
    """הניקוי המינימלי לקוד שמודבק בבוט — הדלת של ה-handlers אליו.

    ה-handlers אינם מייבאים את שכבת הדומיין
    (``tests/unit/architecture/test_layer_boundaries.py``), ולכן הם עוברים כאן.
    מה מנוקה ומה לא — ב-docstring של
    :func:`src.domain.services.code_normalizer.clean_pasted_code`; כאן רק נקבע
    אם הקובץ הוא Markdown, לפי השם (:func:`is_markdown_filename`).

    כל זרימה בבוט קוראת לזה פעם אחת, ממש לפני השמירה, כשגם הקוד וגם השם
    ידועים. ``None`` הוא טקסט ריק: ``context.user_data`` יכול לאבד את הקוד בין
    שלבי השיחה, והזרימות תמיד שמרו אז מחרוזת ריקה.
    """
    return _clean_pasted_code(code if code is not None else "", is_markdown=is_markdown_filename(file_name))


#: כמה מספרי שורות האזהרה מונה לפני "ועוד N שורות". הרשימה המלאה אינה
#: הולכת לאיבוד — היא במסמך עצמו; זה רק מה שנכנס להודעה בטלגרם.
_NOTICE_MAX_LISTED_LINES = 10


def _join_hebrew(items: List[str]) -> str:
    """מחבר רשימה כמו בעברית: א, ב וג. לפני ספרה או אות לטינית ה-ו' באה עם מקף."""
    if len(items) <= 1:
        return "".join(items)
    last = items[-1]
    conj = "ו" if "א" <= last[:1] <= "ת" else "ו-"
    return ", ".join(items[:-1]) + " " + conj + last


def _count_phrase(count: int, one: str, many: str) -> str:
    return one if count == 1 else many.format(n=count)


def format_cleanup_notice(cleanup: PasteCleanup) -> str:
    """השורות שהבוט מוסיף להודעת ההצלחה: מה נוקה, ואזהרה על תווי כיווניות.

    מחרוזת ריקה כשאין מה לומר. בלי השורה הזו הניקוי היה קורה בשקט, וזה בדיוק
    מה שהוחלף כאן. הטקסט אינו מכיל אף תו מבין ``_*`[]<>&``: הוא נכנס להודעות
    עם ``parse_mode`` של Markdown וגם של HTML, ותו כזה היה משנה את העיצוב או
    מפיל את השליחה ב-``BadRequest``.
    """
    lines: List[str] = []
    cleaned = _cleaned_items(cleanup)
    if cleaned:
        lines.append("🧹 ניקיתי מהקוד: " + _join_hebrew(cleaned))
    if cleanup.bidi_control_lines:
        lines.append(
            "⚠️ " + _where_lines(cleanup.bidi_control_lines) + " יש תווים שמשנים את סדר התצוגה. "
            "הם לא נראים, ויכולים לגרום לקוד להיראות אחרת ממה שהוא עושה. לא נגעתי בהם."
        )
    return "\n".join(lines)


def _cleaned_items(cleanup: PasteCleanup) -> List[str]:
    """הפריטים של שורת "ניקיתי מהקוד", לפי הסדר שבו הניקוי רץ."""
    counted = (
        (cleanup.crlf, "סוף שורה אחד של Windows", "{n} סופי שורה של Windows"),
        (cleanup.lone_cr, "סוף שורה אחד של Mac הישן", "{n} סופי שורה של Mac הישן"),
        (int(cleanup.bom), "סימן BOM בתחילת הטקסט", "סימן BOM בתחילת הטקסט"),
        (
            cleanup.special_spaces,
            "רווח מיוחד אחד (כמו NBSP) שהפך לרווח רגיל",
            "{n} רווחים מיוחדים (כמו NBSP) שהפכו לרווח רגיל",
        ),
        (cleanup.zwsp, "ZWSP אחד", "{n} תווי ZWSP"),
        (cleanup.trailing_whitespace_lines, "רווחים בסוף שורה אחת", "רווחים בסוף {n} שורות"),
    )
    return [_count_phrase(count, one, many) for count, one, many in counted if count]


def _where_lines(numbers: Tuple[int, ...]) -> str:
    """איפה התווים: "בשורה 4", "בשורות 4 ו-9", או "בשורות 1, 2, ... ועוד 3 שורות"."""
    listed = [str(n) for n in numbers[:_NOTICE_MAX_LISTED_LINES]]
    rest = len(numbers) - len(listed)
    if rest:
        return "בשורות " + ", ".join(listed) + " " + _count_phrase(rest, "ועוד שורה אחת", "ועוד {n} שורות")
    if len(listed) == 1:
        return "בשורה " + listed[0]
    return "בשורות " + _join_hebrew(listed)


@traced("code.analyze")
def analyze_code(code: str, language: str) -> Dict[str, Any]:
    """
    מבצע ניתוח על קטע קוד עבור שפה נתונה.
    
    Args:
        code: קוד המקור לניתוח
        language: שפת התכנות
    
    Returns:
        Dict[str, Any]: מילון עם תוצאות הניתוח, כולל:
            - lines: מספר שורות
            - complexity: מורכבות הקוד
            - metrics: מטריקות נוספות
    """
    try:
        set_current_span_attributes({
            "language": str(language or ""),
            "code.length": int(len(code or "")),
        })
    except Exception:
        pass
    if code_processor is None:
        return {"language": language, "length": len(code)}
    return code_processor.analyze_code(code, language)


@traced("code.extract_functions")
def extract_functions(code: str, language: str) -> List[Dict[str, Any]]:
    """Extract function definitions from code."""
    try:
        set_current_span_attributes({
            "language": str(language or ""),
            "code.length": int(len(code or "")),
        })
    except Exception:
        pass
    if code_processor is None:
        return []
    return code_processor.extract_functions(code, language)


@traced("code.stats")
def get_code_stats(code: str) -> Dict[str, Any]:
    """Compute simple statistics for a code snippet."""
    try:
        set_current_span_attributes({"code.length": int(len(code or ""))})
    except Exception:
        pass
    if code_processor is None:
        return {"length": len(code)}
    return code_processor.get_code_stats(code)


@traced("code.highlight")
def highlight_code(code: str, language: str) -> str:
    """Return syntax highlighted representation for code."""
    try:
        set_current_span_attributes({
            "language": str(language or ""),
            "code.length": int(len(code or "")),
        })
    except Exception:
        pass
    if code_processor is None:
        return code
    return code_processor.highlight_code(code, language)

