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

from typing import Any, Dict, List, Tuple
from utils import normalize_code

# Thin wrapper around existing code_processor to allow future swap/refactor
try:
    from code_processor import code_processor  # type: ignore
except Exception:  # optional deps (e.g., cairosvg) might be missing locally
    code_processor = None  # type: ignore[assignment]


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
    if code_processor is None:
        # Minimal fallback: normalize only
        return True, normalize_code(code), ""
    ok, cleaned, msg = code_processor.validate_code_input(code, file_name, user_id)
    # Ensure normalization on the cleaned result (idempotent)
    try:
        cleaned = normalize_code(cleaned)
    except Exception:
        pass
    return ok, cleaned, msg


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
    if code_processor is None:
        return {"language": language, "length": len(code)}
    return code_processor.analyze_code(code, language)


def extract_functions(code: str, language: str) -> List[Dict[str, Any]]:
    """Extract function definitions from code."""
    if code_processor is None:
        return []
    return code_processor.extract_functions(code, language)


def get_code_stats(code: str) -> Dict[str, Any]:
    """Compute simple statistics for a code snippet."""
    if code_processor is None:
        return {"length": len(code)}
    return code_processor.get_code_stats(code)


def highlight_code(code: str, language: str) -> str:
    """Return syntax highlighted representation for code."""
    if code_processor is None:
        return code
    return code_processor.highlight_code(code, language)

