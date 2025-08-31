from typing import Any, Dict, List, Tuple

# Thin wrapper around existing code_processor to allow future swap/refactor
try:
    from code_processor import code_processor  # type: ignore
except Exception:  # optional deps (e.g., cairosvg) might be missing locally
    code_processor = None  # type: ignore[assignment]


def _fallback_detect_language(code: str, filename: str) -> str:
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
    """Detect programming language for given code and filename."""
    if code_processor is not None:
        return code_processor.detect_language(code, filename)
    return _fallback_detect_language(code, filename)


def validate_code_input(code: str, file_name: str, user_id: int) -> Tuple[bool, str, str]:
    """Validate and sanitize code input. Returns (is_valid, cleaned_code, error_message)."""
    if code_processor is None:
        # Minimal fallback: accept as-is
        return True, code, ""
    return code_processor.validate_code_input(code, file_name, user_id)


def analyze_code(code: str, language: str) -> Dict[str, Any]:
    """Run analysis on code snippet for the given language."""
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
