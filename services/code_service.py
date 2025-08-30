from typing import Any, Dict, List, Tuple

# Thin wrapper around existing code_processor to allow future swap/refactor
from code_processor import code_processor


def detect_language(code: str, filename: str) -> str:
    """Detect programming language for given code and filename."""
    return code_processor.detect_language(code, filename)


def validate_code_input(code: str, file_name: str, user_id: int) -> Tuple[bool, str, str]:
    """Validate and sanitize code input. Returns (is_valid, cleaned_code, error_message)."""
    return code_processor.validate_code_input(code, file_name, user_id)


def analyze_code(code: str, language: str) -> Dict[str, Any]:
    """Run analysis on code snippet for the given language."""
    return code_processor.analyze_code(code, language)


def extract_functions(code: str, language: str) -> List[Dict[str, Any]]:
    """Extract function definitions from code."""
    return code_processor.extract_functions(code, language)


def get_code_stats(code: str) -> Dict[str, Any]:
    """Compute simple statistics for a code snippet."""
    return code_processor.get_code_stats(code)


def highlight_code(code: str, language: str) -> str:
    """Return syntax highlighted representation for code."""
    return code_processor.highlight_code(code, language)

