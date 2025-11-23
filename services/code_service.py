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
    זיהוי שפת תכנות עבור קוד ושם קובץ נתונים, עם עדיפויות חכמות:
    - שמות מיוחדים ללא סיומת (Dockerfile/Makefile/Taskfile/.*ignore/.env)
    - זיהוי shebang (#!/usr/bin/env bash|python, #!/bin/sh וכו')
    - העדפת אותות תוכן עבור סיומות גנריות (.md/.txt/ללא סיומת)
    - נפילה חכמה למעבד ברירת מחדל ולמיפוי סיומות
    """
    # נסה דטקטור דומייני מאוחד לקבלת עקביות בין כל הזרימות (שמירה/עריכה/תצוגה)
    try:
        from src.domain.services.language_detector import LanguageDetector  # type: ignore
        return LanguageDetector().detect_language(code, filename)
    except Exception:
        pass
    fname = (filename or "").strip()
    code = code or ""
    fname_lower = fname.lower()
    ext = Path(fname_lower).suffix  # '' when no extension

    # 1) שמות מיוחדים ללא סיומת
    special_names_map = {
        "dockerfile": "dockerfile",
        "makefile": "makefile",
        "taskfile": "yaml",  # Taskfile (go-task) הוא YAML
    }
    base = Path(fname_lower).name
    if base in special_names_map:
        return special_names_map[base]
    if base in {".gitignore"}:
        return "gitignore"
    if base in {".dockerignore"}:
        return "dockerignore"
    if base in {".env"}:
        return "env"

    # 2) Shebang detection (גם env-variations)
    try:
        first_line = (code.splitlines()[0] if code else "").strip().lower()
    except Exception:
        first_line = ""
    if first_line.startswith("#!"):
        if "bash" in first_line or first_line.endswith("/sh") or " env sh" in first_line or " env bash" in first_line:
            return "bash"
        if "python" in first_line:
            return "python"

    # 3) נשתמש במעבד השפות אם זמין
    detected = None
    if code_processor is not None:
        try:
            detected = _normalize_detected_language(
                code_processor.detect_language(code, filename)
            )
        except Exception:
            detected = None

    # 4) העדפת תוכן עבור סיומות גנריות
    generic_md_exts = {".md", ".markdown", ".mdown", ".mkd", ".mkdn"}
    generic_text_exts = {".txt", ""}

    def looks_like_markdown(text: str) -> bool:
        content = text or ""
        # התעלם מ-shebang בתחילת הטקסט
        if content.startswith("#!"):
            nl = content.find("\n")
            content = "" if nl == -1 else content[nl + 1 :]
        if re.search(r"(^|\n)\s{0,3}#[^#]", content):
            return True
        if re.search(r"(^|\n)\s{0,2}[-*+]\s+\S", content):
            return True
        if re.search(r"\[.+?\]\(.+?\)", content):
            return True
        if "```" in content:
            return True
        return False

    def strong_python_signal(text: str) -> bool:
        if re.search(r"^#!.*\bpython(\d+(?:\.\d+)*)?\b", text, flags=re.IGNORECASE | re.MULTILINE):
            return True
        signals = 0
        if re.search(r"^\s*def\s+\w+\s*\(", text, flags=re.MULTILINE):
            signals += 1
        if re.search(r"^\s*class\s+\w+\s*\(?", text, flags=re.MULTILINE):
            signals += 1
        if re.search(r"^\s*import\s+\w+", text, flags=re.MULTILINE):
            signals += 1
        if "__name__" in text and "__main__" in text:
            signals += 1
        if re.search(r":\s*(#.*)?\n\s{4,}\S", text, flags=re.MULTILINE):
            signals += 1
        return signals >= 2

    # Markdown: תעדוף Python אם יש אותות חזקים וללא סמני Markdown בולטים
    if ext in generic_md_exts:
        if strong_python_signal(code) and not looks_like_markdown(code):
            return "python"
        # אם המעבד מצא שפה שאינה markdown (למשל python) — קבל אותה; אחרת markdown
        if detected and detected != "text":
            return detected
        return "markdown"

    # טקסט/ללא סיומת: אם המעבד מצא שפה — קבל; אחרת בדיקה ידנית ליAML
    if ext in generic_text_exts:
        if detected and detected != "text":
            return detected
        # Taskfile/קבצי YAML ללא סיומת
        if re.search(r"(?m)^\s*\w+\s*:", code) or re.search(r"(?m)^\s*-\s+\S", code):
            return "yaml"
        # מיפוי לפי שם קובץ (למשל .env)
        mapped = _detect_from_filename(fname)
        if mapped and mapped != "text":
            return mapped
        return "text"

    # 5) אם המעבד מצא תוצאה — החזר אותה
    if detected:
        return detected

    # 6) נפילה חכמה למיפוי לפי שם קובץ/סיומת
    mapped = _detect_from_filename(fname)
    if mapped and mapped != "text":
        return mapped

    # 7) Fallback אחרון
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

