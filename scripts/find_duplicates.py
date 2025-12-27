#!/usr/bin/env python3
"""
סקריפט לאיתור כפילויות קוד בריפו.

🔒 סקריפט לקריאה בלבד - לא מבצע שום עריכה או מחיקה של קוד!

שיפורים לעומת הגרסה המקורית:
- סינון תיקיות מדויק יותר עם Path.parts
- תמיכה בפונקציות אסינכרוניות (AsyncFunctionDef)
- נרמול AST מתקדם: החלפת מזהים והסרת docstrings
- טיפול בטוח ב-lineno/end_lineno
- SHA256 במקום MD5

שימוש:
    python scripts/find_duplicates.py
    python scripts/find_duplicates.py --min-lines 6
    python scripts/find_duplicates.py --output json
"""

from __future__ import annotations

import argparse
import ast
import copy
import hashlib
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ============================================================================
# הגדרות
# ============================================================================

PROJECT_ROOT = Path(__file__).parent.parent  # תיקיית הפרויקט

# תיקיות לסריקה (רק תיקיות שבאמת מכילות קוד של הפרויקט)
DIRS_TO_INCLUDE = {
    "services",
    "handlers",
    "webapp",
    "database",
    "src",
    "chatops",
    "monitoring",
    "reminders",
    "i18n",
    "tools",
}

# תיקיות להתעלמות מוחלטת
DIRS_TO_EXCLUDE = {
    "tests",
    "node_modules",
    "__pycache__",
    ".git",
    "venv",
    ".venv",
    "docs",
}

# מינימום שורות לפונקציה (פחות מזה = נתעלם)
DEFAULT_MIN_LINES = 4


# ============================================================================
# מבני נתונים
# ============================================================================


@dataclass
class FunctionLocation:
    """מיקום של פונקציה בקוד."""

    file: str
    name: str
    start_line: int
    end_line: int
    is_async: bool = False

    @property
    def lines_range(self) -> str:
        return f"{self.start_line}-{self.end_line}"

    @property
    def line_count(self) -> int:
        return self.end_line - self.start_line + 1


@dataclass
class DuplicateGroup:
    """קבוצת פונקציות כפולות."""

    hash_prefix: str
    locations: list[FunctionLocation] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.locations)


# ============================================================================
# נרמול AST מתקדם
# ============================================================================


class ASTNormalizer(ast.NodeTransformer):
    """
    מנרמל עץ AST כדי להשוות מבנים לוגיים.

    מה שהוא עושה:
    - מחליף את כל שמות המשתנים ל-_v0, _v1, _v2...
    - מסיר docstrings
    - מסיר מידע מיקום (lineno, col_offset וכו')
    """

    def __init__(self) -> None:
        self.var_counter = 0
        self.var_map: dict[str, str] = {}

    def _get_normalized_name(self, original: str) -> str:
        """מחזיר שם מנורמל למשתנה."""
        if original not in self.var_map:
            self.var_map[original] = f"_v{self.var_counter}"
            self.var_counter += 1
        return self.var_map[original]

    def visit_Name(self, node: ast.Name) -> ast.Name:
        """מחליף שמות משתנים לשמות גנריים."""
        node.id = self._get_normalized_name(node.id)
        self.generic_visit(node)
        return node

    def visit_arg(self, node: ast.arg) -> ast.arg:
        """מחליף שמות פרמטרים."""
        node.arg = self._get_normalized_name(node.arg)
        self.generic_visit(node)
        return node

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.FunctionDef:
        """מטפל בפונקציה - מסיר docstring ומנרמל שם."""
        node.name = "_func"
        node.body = self._remove_docstring(node.body)
        self.generic_visit(node)
        return node

    def visit_AsyncFunctionDef(
        self, node: ast.AsyncFunctionDef
    ) -> ast.AsyncFunctionDef:
        """מטפל בפונקציה אסינכרונית - מסיר docstring ומנרמל שם."""
        node.name = "_func"
        node.body = self._remove_docstring(node.body)
        self.generic_visit(node)
        return node

    def _remove_docstring(self, body: list[ast.stmt]) -> list[ast.stmt]:
        """מסיר docstring מגוף הפונקציה."""
        if not body:
            return body

        first_stmt = body[0]
        if isinstance(first_stmt, ast.Expr) and isinstance(
            first_stmt.value, ast.Constant
        ):
            if isinstance(first_stmt.value.value, str):
                return body[1:]
        return body


def normalize_ast_node(node: ast.AST) -> str:
    """
    מנרמל צומת AST ומחזיר מחרוזת להשוואה.

    מחזיר את הייצוג המנורמל של הפונקציה - ללא שמות משתנים,
    ללא docstrings, רק המבנה הלוגי.
    """
    # יוצרים עותק עמוק כדי לא לשנות את המקור
    node_copy = copy.deepcopy(node)

    # מנרמלים את העץ
    normalizer = ASTNormalizer()
    normalized = normalizer.visit(node_copy)

    # ממירים ל-dump ללא מידע מיקום
    return ast.dump(normalized, include_attributes=False)


def get_function_hash(normalized_code: str) -> str:
    """מחשב hash של הקוד המנורמל עם SHA256."""
    return hashlib.sha256(normalized_code.encode("utf-8")).hexdigest()


# ============================================================================
# סריקת הפרויקט
# ============================================================================


def should_scan_file(filepath: Path) -> bool:
    """בודק אם הקובץ צריך להיסרק."""
    if not filepath.suffix == ".py":
        return False

    # בודקים שהקובץ נמצא באחת התיקיות הרצויות
    parts = set(filepath.parts)

    # אם יש תיקייה שצריך להתעלם ממנה - דילוג
    if parts & DIRS_TO_EXCLUDE:
        return False

    # בודקים אם הקובץ נמצא באחת התיקיות שאנחנו רוצים
    return bool(parts & DIRS_TO_INCLUDE)


def get_line_info(node: ast.AST) -> tuple[int, int]:
    """
    מחזיר מידע שורות בטוח עבור צומת AST.

    מטפל במקרים שבהם lineno או end_lineno לא קיימים.
    """
    start = getattr(node, "lineno", 0)
    end = getattr(node, "end_lineno", start)
    return start, end


def extract_functions(
    filepath: Path, min_lines: int
) -> list[tuple[ast.AST, FunctionLocation]]:
    """מחלץ את כל הפונקציות מקובץ."""
    functions: list[tuple[ast.AST, FunctionLocation]] = []

    try:
        content = filepath.read_text(encoding="utf-8")
        tree = ast.parse(content)
    except (SyntaxError, UnicodeDecodeError) as e:
        print(f"⚠️  דילגתי על {filepath}: {e}")
        return functions

    for node in ast.walk(tree):
        is_async = isinstance(node, ast.AsyncFunctionDef)
        is_sync = isinstance(node, ast.FunctionDef)

        if not (is_async or is_sync):
            continue

        start_line, end_line = get_line_info(node)

        # בדיקת מינימום שורות
        line_count = end_line - start_line + 1
        if line_count < min_lines:
            continue

        location = FunctionLocation(
            file=str(filepath.relative_to(PROJECT_ROOT)),
            name=node.name,  # type: ignore
            start_line=start_line,
            end_line=end_line,
            is_async=is_async,
        )

        functions.append((node, location))

    return functions


def scan_project(min_lines: int = DEFAULT_MIN_LINES) -> dict[str, list[FunctionLocation]]:
    """
    סורק את הפרויקט ומחזיר מפה של hash לרשימת מיקומים.

    ⚠️ פונקציה לקריאה בלבד - לא משנה שום קובץ!
    """
    duplicates: dict[str, list[FunctionLocation]] = {}

    print(f"🚀 מתחיל סריקה בתיקיות: {', '.join(sorted(DIRS_TO_INCLUDE))}...")
    print(f"   מתעלם מפונקציות קצרות מ-{min_lines} שורות")
    print()

    files_scanned = 0
    functions_found = 0

    for py_file in PROJECT_ROOT.rglob("*.py"):
        if not should_scan_file(py_file):
            continue

        files_scanned += 1
        functions = extract_functions(py_file, min_lines)

        for node, location in functions:
            functions_found += 1

            # נרמול ו-hash
            normalized = normalize_ast_node(node)
            func_hash = get_function_hash(normalized)

            if func_hash not in duplicates:
                duplicates[func_hash] = []
            duplicates[func_hash].append(location)

    print(f"📁 נסרקו {files_scanned} קבצים")
    print(f"🔍 נמצאו {functions_found} פונקציות")

    return duplicates


# ============================================================================
# הצגת תוצאות
# ============================================================================


def print_report(duplicates: dict[str, list[FunctionLocation]]) -> int:
    """מדפיס דוח כפילויות. מחזיר את מספר הכפילויות שנמצאו."""
    print("\n" + "=" * 60)
    print("📊 תוצאות הסריקה")
    print("=" * 60)

    found = 0
    total_duplicate_instances = 0

    # מיון לפי מספר הכפילויות (הכי הרבה קודם)
    sorted_items = sorted(
        ((h, locs) for h, locs in duplicates.items() if len(locs) > 1),
        key=lambda x: len(x[1]),
        reverse=True,
    )

    for func_hash, locations in sorted_items:
        found += 1
        total_duplicate_instances += len(locations)

        # בדיקה אם יש פונקציות async בקבוצה
        has_async = any(loc.is_async for loc in locations)
        async_marker = " 🔄" if has_async else ""

        print(f"\n🔴 כפילות #{found} (Hash: {func_hash[:8]}...){async_marker}")
        print(f"   נמצאו {len(locations)} מופעים:")

        for loc in locations:
            async_tag = "[async] " if loc.is_async else ""
            print(
                f"   • {loc.file}: {async_tag}{loc.name}() "
                f"(שורות {loc.lines_range}, {loc.line_count} שורות)"
            )

    print("\n" + "=" * 60)

    if found == 0:
        print("✅ הקוד נקי! לא נמצאו כפילויות.")
    else:
        print(f"⚠️  סה\"כ נמצאו {found} קבוצות של קוד משוכפל")
        print(f"   ({total_duplicate_instances} מופעים כפולים)")

    print("=" * 60)

    return found


def output_json(duplicates: dict[str, list[FunctionLocation]]) -> None:
    """מדפיס את התוצאות בפורמט JSON."""
    result: dict[str, Any] = {
        "summary": {
            "duplicate_groups": 0,
            "total_duplicates": 0,
        },
        "duplicates": [],
    }

    for func_hash, locations in duplicates.items():
        if len(locations) <= 1:
            continue

        result["summary"]["duplicate_groups"] += 1
        result["summary"]["total_duplicates"] += len(locations)

        group = {
            "hash": func_hash[:16],
            "count": len(locations),
            "locations": [
                {
                    "file": loc.file,
                    "function": loc.name,
                    "start_line": loc.start_line,
                    "end_line": loc.end_line,
                    "is_async": loc.is_async,
                }
                for loc in locations
            ],
        }
        result["duplicates"].append(group)

    # מיון לפי מספר כפילויות
    result["duplicates"].sort(key=lambda x: x["count"], reverse=True)

    print(json.dumps(result, ensure_ascii=False, indent=2))


# ============================================================================
# נקודת כניסה
# ============================================================================


def main() -> int:
    """נקודת כניסה ראשית."""
    parser = argparse.ArgumentParser(
        description="סקריפט לאיתור כפילויות קוד (קריאה בלבד)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
דוגמאות שימוש:
  python scripts/find_duplicates.py                    # סריקה רגילה
  python scripts/find_duplicates.py --min-lines 6     # רק פונקציות ארוכות יותר
  python scripts/find_duplicates.py --output json     # פלט JSON
        """,
    )

    parser.add_argument(
        "--min-lines",
        type=int,
        default=DEFAULT_MIN_LINES,
        help=f"מינימום שורות לפונקציה (ברירת מחדל: {DEFAULT_MIN_LINES})",
    )

    parser.add_argument(
        "--output",
        choices=["text", "json"],
        default="text",
        help="פורמט הפלט (ברירת מחדל: text)",
    )

    args = parser.parse_args()

    # סריקה
    duplicates = scan_project(min_lines=args.min_lines)

    # הצגת תוצאות
    if args.output == "json":
        output_json(duplicates)
        return 0
    else:
        found = print_report(duplicates)
        return 1 if found > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
