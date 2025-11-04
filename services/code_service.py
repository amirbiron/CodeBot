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

from typing import Any, Dict, List, Tuple, Optional
from utils import normalize_code

try:
    from observability_instrumentation import traced, set_current_span_attributes
except Exception:  # pragma: no cover
    def traced(*_a, **_k):  # type: ignore
        def _inner(f):
            return f
        return _inner

    def set_current_span_attributes(*_a, **_k):  # type: ignore
        return None

# Thin wrapper around existing code_processor to allow future swap/refactor
# We keep a loose type here to avoid importing heavy optional deps during type checking/runtime.
try:
    from code_processor import code_processor as _cp
    code_processor: Optional[Any] = _cp
except Exception:  # optional deps (e.g., cairosvg) might be missing locally
    code_processor = None


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
    זיהוי שפת תכנות עבור קוד ושם קובץ נתונים.
    
    Args:
        code: קוד המקור לניתוח
        filename: שם הקובץ (כולל סיומת)
    
    Returns:
        str: שם שפת התכנות שזוהתה
    
    Example:
        >>> detect_language("print('Hello')", "test.py")
        'python'
    """
    if code_processor is not None:
        return code_processor.detect_language(code, filename)
    return _fallback_detect_language(code, filename)


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
        set_current_span_attributes({
            "code.length": int(len(code or "")),
            "file_name": str(file_name or ""),
        })
    except Exception:
        pass
    if code_processor is None:
        # Minimal fallback: normalize only
        return True, normalize_code(code), ""
    ok, cleaned, msg = code_processor.validate_code_input(code, file_name, user_id)
    # לאחר שהוולידטור מריץ sanitize + normalize (עם טיפול מיוחד ל-Markdown),
    # אין לבצע נרמול חוזר שעלול לקצץ רווחי סוף שורה במסמכי Markdown.
    # אם בפועל נדרש נרמול נוסף בעתיד, יש להעביר דגלים תואמים לסוג הקובץ.
    try:
        set_current_span_attributes({"validation.ok": bool(ok)})
    except Exception:
        pass
    return ok, cleaned, msg


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

