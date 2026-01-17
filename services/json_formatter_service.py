"""
JSON Formatter Service
======================
שירות לעיצוב, אימות ותיקון JSON.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class JsonValidationResult:
    """תוצאת אימות JSON."""

    is_valid: bool
    error_message: Optional[str] = None
    error_line: Optional[int] = None
    error_column: Optional[int] = None


@dataclass
class JsonStats:
    """סטטיסטיקות JSON."""

    total_keys: int
    max_depth: int
    total_values: int
    string_count: int
    number_count: int
    boolean_count: int
    null_count: int
    array_count: int
    object_count: int


class JsonFormatterService:
    """שירות לעיצוב ועיבוד JSON."""

    def __init__(self) -> None:
        self.default_indent = 2

    def format_json(self, json_string: str, indent: int = 2, sort_keys: bool = False) -> str:
        """
        עיצוב JSON עם הזחה.

        Args:
            json_string: מחרוזת JSON לעיצוב
            indent: מספר רווחים להזחה (ברירת מחדל: 2)
            sort_keys: האם למיין מפתחות אלפבתית

        Returns:
            JSON מעוצב

        Raises:
            json.JSONDecodeError: אם ה-JSON לא תקין
        """
        parsed = json.loads(json_string)
        return json.dumps(parsed, indent=indent, sort_keys=sort_keys, ensure_ascii=False)

    def minify_json(self, json_string: str) -> str:
        """
        דחיסת JSON להסרת רווחים מיותרים.

        Args:
            json_string: מחרוזת JSON לדחיסה

        Returns:
            JSON דחוס בשורה אחת
        """
        parsed = json.loads(json_string)
        return json.dumps(parsed, separators=(",", ":"), ensure_ascii=False)

    def validate_json(self, json_string: str) -> JsonValidationResult:
        """
        אימות תקינות JSON.

        Args:
            json_string: מחרוזת JSON לאימות

        Returns:
            תוצאת האימות עם פרטי שגיאה אם יש
        """
        try:
            json.loads(json_string)
            return JsonValidationResult(is_valid=True)
        except json.JSONDecodeError as e:
            return JsonValidationResult(
                is_valid=False,
                error_message=e.msg,
                error_line=e.lineno,
                error_column=e.colno,
            )

    def get_json_stats(self, json_string: str) -> JsonStats:
        """
        חישוב סטטיסטיקות על מבנה ה-JSON.

        Args:
            json_string: מחרוזת JSON לניתוח

        Returns:
            סטטיסטיקות המבנה
        """
        parsed = json.loads(json_string)
        stats = {
            "total_keys": 0,
            "max_depth": 0,
            "total_values": 0,
            "string_count": 0,
            "number_count": 0,
            "boolean_count": 0,
            "null_count": 0,
            "array_count": 0,
            "object_count": 0,
        }

        def analyze(obj: Any, depth: int = 0) -> None:
            stats["max_depth"] = max(stats["max_depth"], depth)

            if isinstance(obj, dict):
                stats["object_count"] += 1
                stats["total_keys"] += len(obj)
                for value in obj.values():
                    analyze(value, depth + 1)
            elif isinstance(obj, list):
                stats["array_count"] += 1
                for item in obj:
                    analyze(item, depth + 1)
            else:
                stats["total_values"] += 1
                if isinstance(obj, str):
                    stats["string_count"] += 1
                elif isinstance(obj, bool):
                    stats["boolean_count"] += 1
                elif isinstance(obj, (int, float)):
                    stats["number_count"] += 1
                elif obj is None:
                    stats["null_count"] += 1

        analyze(parsed)
        return JsonStats(**stats)

    def fix_common_errors(self, json_string: str) -> tuple[str, list[str]]:
        """
        ניסיון לתקן שגיאות נפוצות ב-JSON.

        Args:
            json_string: מחרוזת JSON עם שגיאות אפשריות

        Returns:
            tuple של (JSON מתוקן, רשימת תיקונים שבוצעו)
        """
        fixes: list[str] = []
        fixed = json_string

        # תיקון פסיקים מיותרים בסוף arrays/objects
        trailing_comma = re.compile(r",(\s*[\]\}])")
        if trailing_comma.search(fixed):
            fixed = trailing_comma.sub(r"\1", fixed)
            fixes.append("הוסרו פסיקים מיותרים")

        # תיקון מירכאות בודדות למירכאות כפולות
        if "'" in fixed:
            # זהירות: רק אם זה נראה כמו JSON עם מירכאות בודדות
            try:
                json.loads(fixed)
            except json.JSONDecodeError:
                fixed = fixed.replace("'", '"')
                fixes.append("הומרו מירכאות בודדות לכפולות")

        # תיקון undefined/NaN/Infinity
        replacements = [
            (r"\bundefined\b", "null", "הומר undefined ל-null"),
            (r"\bNaN\b", "null", "הומר NaN ל-null"),
            (r"\bInfinity\b", "null", "הומר Infinity ל-null"),
        ]
        for pattern, replacement, message in replacements:
            if re.search(pattern, fixed):
                fixed = re.sub(pattern, replacement, fixed)
                fixes.append(message)

        return fixed, fixes


_service_instance: Optional[JsonFormatterService] = None


def get_json_formatter_service() -> JsonFormatterService:
    """קבלת instance יחיד של השירות."""
    global _service_instance
    if _service_instance is None:
        _service_instance = JsonFormatterService()
    return _service_instance

