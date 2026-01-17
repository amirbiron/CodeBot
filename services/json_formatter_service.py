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
        except TypeError as e:
            return JsonValidationResult(is_valid=False, error_message=str(e))

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

        # אם ה-JSON כבר תקין — לא נוגעים בו בכלל (מונע "תיקון" שמקלקל תוכן)
        try:
            def _reject_constants(_val: str) -> None:
                raise ValueError("invalid_json_constant")

            # חשוב: Python json מאפשר NaN/Infinity כברירת מחדל.
            # כאן אנחנו מתייחסים אליהם כ"לא תקין" כדי ש-Magic Fix לא יחזיר -Infinity/-NaN כערכים.
            json.loads(fixed, parse_constant=_reject_constants)
            return fixed, fixes
        except (json.JSONDecodeError, TypeError, ValueError):
            pass

        def _partition_by_quoted_strings(text: str) -> tuple[list[tuple[bool, str]], bool]:
            """
            מחלק את הטקסט למקטעים: (is_quoted_string, segment).
            מזהה מחרוזות שמתחילות ב- ' או " ומכבד escape עם backslash.
            """
            parts: list[tuple[bool, str]] = []
            start = 0
            i = 0
            in_quote: Optional[str] = None
            while i < len(text):
                ch = text[i]
                if in_quote is not None:
                    if ch == "\\":
                        i += 2
                        continue
                    if ch == in_quote:
                        i += 1
                        parts.append((True, text[start:i]))
                        start = i
                        in_quote = None
                        continue
                    i += 1
                    continue

                # not in quote
                if ch in ('"', "'"):
                    if start < i:
                        parts.append((False, text[start:i]))
                    in_quote = ch
                    start = i
                    i += 1
                    continue
                i += 1

            if start < len(text):
                parts.append(((in_quote is not None), text[start:]))
            return parts, (in_quote is not None)

        def _sub_outside_strings(text: str, pattern: re.Pattern[str], repl: str) -> tuple[str, bool]:
            parts, unbalanced = _partition_by_quoted_strings(text)
            if unbalanced:
                # אם יש מחרוזת לא סגורה, עדיף לא להריץ תיקונים Regex שעלולים לשבור תוכן.
                return text, False
            changed = False
            out_parts: list[str] = []
            for is_str, seg in parts:
                if is_str:
                    out_parts.append(seg)
                    continue
                new_seg, n = pattern.subn(repl, seg)
                if n:
                    changed = True
                out_parts.append(new_seg)
            return "".join(out_parts), changed

        # תיקון פסיקים מיותרים בסוף arrays/objects
        trailing_comma = re.compile(r",(\s*[\]\}])")
        fixed2, changed = _sub_outside_strings(fixed, trailing_comma, r"\1")
        if changed:
            fixed = fixed2
            fixes.append("הוסרו פסיקים מיותרים")

        def _escape_for_double_quotes(text: str) -> str:
            # JSON לא תומך ב-\' (זה escape לא חוקי), ולכן אם הגיע מ-string בסגנון single-quote,
            # נסיר backslash רק מהדפוס \' ונשאיר escapes אחרים.
            s = text.replace("\\'", "'")
            # אם יש " לא מאויש ב-backslash, צריך לאייש כדי שיהיה JSON תקין
            s = re.sub(r'(?<!\\)"', r'\\"', s)
            return s

        def _fix_single_quoted_keys_and_values(raw: str) -> tuple[str, bool]:
            """
            ניסיון "זהיר" להמיר מירכאות בודדות לכפולות *רק* במקומות שמזוהים בבירור:
            - מפתחות באובייקט: {'key': ...}  -> {"key": ...}
            - ערכי מחרוזת:     : 'value'     -> : "value"
            לא נוגעים בטקסט שבתוך מחרוזות קיימות במירכאות כפולות (כדי לא לשבור apostrophes).
            """
            changed = False
            out = raw

            # מפתחות: start או אחרי '{' / ',' עם רווחים
            key_pat = re.compile(r"(?P<prefix>(?:^|[{,]\s*))'(?P<key>(?:[^'\\]|\\.)*)'\s*:")

            def _key_sub(m: re.Match[str]) -> str:
                nonlocal changed
                changed = True
                prefix = m.group("prefix")
                key = _escape_for_double_quotes(m.group("key"))
                return f'{prefix}"{key}":'

            out = key_pat.sub(_key_sub, out)

            # ערכי מחרוזת: אחרי ':' ואז '...'(עד delimiter), בלי לנחש מבנים מורכבים
            val_pat = re.compile(
                r":\s*'(?P<val>(?:[^'\\]|\\.)*)'(?P<suffix>(?=\s*[,}\]]|\s*$))"
            )

            def _val_sub(m: re.Match[str]) -> str:
                nonlocal changed
                changed = True
                val = _escape_for_double_quotes(m.group("val"))
                return f': "{val}"'

            out = val_pat.sub(_val_sub, out)
            return out, changed

        # תיקון מירכאות בודדות למירכאות כפולות (זהיר, בלי replace גורף)
        if "'" in fixed:
            try:
                json.loads(fixed)
            except json.JSONDecodeError:
                fixed2, changed = _fix_single_quoted_keys_and_values(fixed)
                if changed and fixed2 != fixed:
                    fixed = fixed2
                    fixes.append("הומרו מירכאות בודדות לכפולות")

        # תיקון undefined/NaN/Infinity (זהיר: מחליף רק כערכים, לא בתוך מחרוזות)
        token_pat = re.compile(
            r"(?P<prefix>(?:^|[{\[,]\s*|:\s*))(?P<token>undefined|[+-]?NaN|[+-]?Infinity)(?P<suffix>(?=\s*[,}\]]|\s*$))"
        )

        def _token_sub(m: re.Match[str]) -> str:
            token = m.group("token")
            if token == "undefined":
                fixes.append("הומר undefined ל-null")
            elif "NaN" in token:
                fixes.append("הומר NaN ל-null")
            else:
                fixes.append("הומר Infinity ל-null")
            return f"{m.group('prefix')}null"

        parts, unbalanced = _partition_by_quoted_strings(fixed)
        if not unbalanced:
            changed = False
            out_parts2: list[str] = []
            for is_str, seg in parts:
                if is_str:
                    out_parts2.append(seg)
                    continue
                new_seg, n = token_pat.subn(_token_sub, seg)
                if n:
                    changed = True
                out_parts2.append(new_seg)
            if changed:
                fixed = "".join(out_parts2)

        return fixed, fixes


_service_instance: Optional[JsonFormatterService] = None


def get_json_formatter_service() -> JsonFormatterService:
    """קבלת instance יחיד של השירות."""
    global _service_instance
    if _service_instance is None:
        _service_instance = JsonFormatterService()
    return _service_instance

