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
from utils import normalize_code
from utils import detect_language_from_filename as _detect_from_filename

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
        # Minimal fallback: normalize only
        ok = True
        cleaned = normalize_code(code)
        msg = ""
    else:
        ok, cleaned, msg = code_processor.validate_code_input(code, file_name, user_id)
    # לאחר שהוולידטור מריץ sanitize + normalize (עם טיפול מיוחד ל-Markdown),
    # אין לבצע נרמול חוזר שעלול לקצץ רווחי סוף שורה במסמכי Markdown.
    # אם בפועל נדרש נרמול נוסף בעתיד, יש להעביר דגלים תואמים לסוג הקובץ.
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

