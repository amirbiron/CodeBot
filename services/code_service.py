from typing import Any, Dict, List, Tuple

# Thin wrapper around existing code_processor to allow future swap/refactor
from code_processor import code_processor


def detect_language(code: str, filename: str) -> str:
    return code_processor.detect_language(code, filename)


def validate_code_input(code: str, file_name: str, user_id: int) -> Tuple[bool, str, str]:
    return code_processor.validate_code_input(code, file_name, user_id)


def analyze_code(code: str, language: str) -> Dict[str, Any]:
    return code_processor.analyze_code(code, language)


def extract_functions(code: str, language: str) -> List[Dict[str, Any]]:
    return code_processor.extract_functions(code, language)


def get_code_stats(code: str) -> Dict[str, Any]:
    return code_processor.get_code_stats(code)


def highlight_code(code: str, language: str) -> str:
    return code_processor.highlight_code(code, language)

