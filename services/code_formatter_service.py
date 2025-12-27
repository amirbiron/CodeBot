"""
Code Formatter & Linting Service
================================
שירות לעיצוב קוד, בדיקת איכות ותיקון אוטומטי.

מבוסס על הכלים הקיימים בפרויקט:
- Black (עיצוב Python)
- flake8 (linting)
- isort (מיון imports)
"""

import subprocess
import tempfile
import difflib
import ast
import os
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


@dataclass
class FormattingResult:
    """תוצאת עיצוב קוד."""

    success: bool
    original_code: str
    formatted_code: str
    lines_changed: int = 0
    error_message: Optional[str] = None
    tool_used: str = ""

    def get_diff(self) -> str:
        """מחזיר diff מפורט בין המקור לתוצאה."""
        diff = difflib.unified_diff(
            self.original_code.splitlines(keepends=True),
            self.formatted_code.splitlines(keepends=True),
            fromfile="לפני",
            tofile="אחרי",
            lineterm="",
        )
        return "\n".join(diff)

    def has_changes(self) -> bool:
        """בודק אם יש שינויים."""
        return self.original_code != self.formatted_code


@dataclass
class LintIssue:
    """בעיה שזוהתה ע"י linter."""

    line: int
    column: int
    code: str  # E501, W293, etc.
    message: str
    severity: str = "warning"  # error, warning, info
    fixable: bool = False


@dataclass
class LintResult:
    """תוצאת בדיקת lint."""

    success: bool
    issues: List[LintIssue] = field(default_factory=list)
    score: float = 10.0  # 0-10
    error_message: Optional[str] = None

    @property
    def has_errors(self) -> bool:
        return any(i.severity == "error" for i in self.issues)

    @property
    def fixable_count(self) -> int:
        return sum(1 for i in self.issues if i.fixable)


@dataclass
class AutoFixResult:
    """תוצאת תיקון אוטומטי."""

    success: bool
    original_code: str
    fixed_code: str
    fixes_applied: List[str] = field(default_factory=list)
    issues_remaining: List[LintIssue] = field(default_factory=list)
    error_message: Optional[str] = None
    level: str = "safe"  # safe, cautious, aggressive


class CodeFormatterService:
    """
    שירות מרכזי לעיצוב קוד ובדיקת איכות.

    תומך בשפות:
    - Python (Black, isort, flake8, autopep8)
    - בעתיד: JavaScript, TypeScript, Go

    הערות ביצועים:
    - הפעלת subprocess היא Blocking - הרץ עם מספיק Gunicorn workers
    - לגרסה 2.0: שקול העברה ל-Background Tasks (Celery)
    """

    # הגבלות
    MAX_FILE_SIZE = 500 * 1024  # 500KB
    TIMEOUT_SECONDS = 10  # קצר יותר למניעת blocking ארוך

    # כלים תומכים לפי שפה
    SUPPORTED_LANGUAGES = {
        "python": {
            "formatters": ["black", "isort", "autopep8"],
            "linters": ["flake8"],
            "extensions": [".py", ".pyw"],
        }
    }

    # בעיות שניתן לתקן אוטומטית
    FIXABLE_CODES = {
        # Whitespace
        "W291",
        "W292",
        "W293",
        "W391",
        # Imports
        "E401",
        "F401",
        "I001",
        # Line length (זהיר)
        "E501",
        # Indentation
        "E101",
        "E111",
        "E117",
    }

    def __init__(self):
        self._check_tools_availability()

    def _check_tools_availability(self) -> Dict[str, bool]:
        """בודק אילו כלים זמינים במערכת."""
        tools = {}
        for tool in ["black", "isort", "flake8", "autopep8", "autoflake"]:
            try:
                result = subprocess.run(
                    [tool, "--version"],
                    capture_output=True,
                    timeout=5,
                )
                tools[tool] = result.returncode == 0
            except (subprocess.SubprocessError, FileNotFoundError):
                tools[tool] = False
        self._available_tools = tools
        return tools

    def is_tool_available(self, tool: str) -> bool:
        """בודק אם כלי ספציפי זמין."""
        if not hasattr(self, "_available_tools"):
            self._check_tools_availability()
        return self._available_tools.get(tool, False)

    # ==================== Validation ====================

    def validate_input(self, code: str, language: str = "python") -> tuple[bool, Optional[str]]:
        """
        מאמת שהקוד תקין לעיבוד.

        Returns:
            (is_valid, error_message)
        """
        if not code or not code.strip():
            return False, "הקוד ריק"

        # בדיקת Encoding לפני בדיקת גודל (כדי לא לזרוק UnicodeEncodeError החוצה)
        try:
            encoded_code = code.encode("utf-8")
        except UnicodeEncodeError:
            return False, "קידוד תווים לא תקין"

        if len(encoded_code) > self.MAX_FILE_SIZE:
            return False, f"הקובץ גדול מדי (מקסימום {self.MAX_FILE_SIZE // 1024}KB)"

        # בדיקת תחביר Python
        if language == "python":
            try:
                ast.parse(code)
            except SyntaxError as e:
                return False, f"שגיאת תחביר בשורה {e.lineno}: {e.msg}"

        return True, None

    # ==================== Formatting ====================

    def format_code(
        self,
        code: str,
        language: str = "python",
        tool: str = "black",
        options: Optional[Dict[str, Any]] = None,
    ) -> FormattingResult:
        """
        מעצב קוד לפי הכלי המבוקש.

        Args:
            code: קוד המקור
            language: שפת התכנות
            tool: כלי העיצוב (black, isort, autopep8)
            options: אפשרויות נוספות (line_length, etc.)

        Returns:
            FormattingResult עם הקוד המעוצב
        """
        options = options or {}

        # בדיקת תקינות
        is_valid, error = self.validate_input(code, language)
        if not is_valid:
            return FormattingResult(
                success=False,
                original_code=code,
                formatted_code=code,
                error_message=error,
            )

        # בדיקת זמינות כלי
        if not self.is_tool_available(tool):
            return FormattingResult(
                success=False,
                original_code=code,
                formatted_code=code,
                error_message=f"הכלי {tool} אינו מותקן",
            )

        try:
            if tool == "black":
                formatted = self._run_black(code, options)
            elif tool == "isort":
                formatted = self._run_isort(code, options)
            elif tool == "autopep8":
                formatted = self._run_autopep8(code, options)
            else:
                return FormattingResult(
                    success=False,
                    original_code=code,
                    formatted_code=code,
                    error_message=f"כלי לא נתמך: {tool}",
                )

            lines_changed = self._count_changes(code, formatted)

            return FormattingResult(
                success=True,
                original_code=code,
                formatted_code=formatted,
                lines_changed=lines_changed,
                tool_used=tool,
            )

        except subprocess.TimeoutExpired:
            return FormattingResult(
                success=False,
                original_code=code,
                formatted_code=code,
                error_message="תם הזמן לעיצוב הקוד",
            )
        except Exception as e:
            logger.error(f"Error formatting code with {tool}: {e}")
            return FormattingResult(
                success=False,
                original_code=code,
                formatted_code=code,
                error_message=str(e),
            )

    def _get_clean_env(self) -> Dict[str, str]:
        """
        מחזיר סביבה נקייה להרצת כלים חיצוניים.
        מונע קריאת קונפיגים גלובליים שיכולים לשבש תוצאות.
        """
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"  # פלט תמיד UTF-8
        return env

    def _decode_output(self, output: bytes) -> str:
        """מפענח פלט עם טיפול בתווים בעייתיים."""
        return output.decode("utf-8", errors="replace")

    def _run_black(self, code: str, options: Dict) -> str:
        """מריץ Black formatter."""
        cmd = ["black", "-", "--quiet"]

        if "line_length" in options:
            cmd.extend(["--line-length", str(options["line_length"])])

        result = subprocess.run(
            cmd,
            input=code.encode("utf-8"),
            capture_output=True,
            timeout=self.TIMEOUT_SECONDS,
            env=self._get_clean_env(),
        )

        if result.returncode != 0:
            raise RuntimeError(self._decode_output(result.stderr))

        return self._decode_output(result.stdout)

    def _run_isort(self, code: str, options: Dict) -> str:
        """מריץ isort למיון imports."""
        cmd = ["isort", "-"]

        if "line_length" in options:
            cmd.extend(["--line-length", str(options["line_length"])])

        # Black compatibility mode - קריטי למניעת התנגשויות!
        cmd.extend(["--profile", "black"])

        env = self._get_clean_env()

        result = subprocess.run(
            cmd,
            input=code.encode("utf-8"),
            capture_output=True,
            timeout=self.TIMEOUT_SECONDS,
            env=env,
        )

        if result.returncode != 0:
            err = self._decode_output(result.stderr) or self._decode_output(result.stdout)
            raise RuntimeError(f"isort failed: {err}")

        return self._decode_output(result.stdout)

    def _run_autopep8(self, code: str, options: Dict) -> str:
        """מריץ autopep8."""
        cmd = ["autopep8", "-"]

        if "line_length" in options:
            cmd.extend(["--max-line-length", str(options["line_length"])])

        # רמת אגרסיביות
        aggression = options.get("aggression", 1)
        for _ in range(aggression):
            cmd.append("-a")

        result = subprocess.run(
            cmd,
            input=code.encode("utf-8"),
            capture_output=True,
            timeout=self.TIMEOUT_SECONDS,
            env=self._get_clean_env(),
        )

        if result.returncode != 0:
            err = self._decode_output(result.stderr) or self._decode_output(result.stdout)
            raise RuntimeError(f"autopep8 failed: {err}")

        return self._decode_output(result.stdout)

    def _run_autoflake(self, code: str, options: Dict) -> str:
        """
        מריץ autoflake להסרת imports ומשתנים לא בשימוש.

        Deep cleaning - מסיר קוד מת:
        - imports לא בשימוש
        - משתנים לא בשימוש
        - מפתחות כפולים במילונים
        """
        cmd = [
            "autoflake",
            "--remove-all-unused-imports",  # הסרת כל ה-imports שלא בשימוש
            "--remove-unused-variables",  # הסרת משתנים לא בשימוש
            "--remove-duplicate-keys",  # הסרת מפתחות כפולים במילונים
            "--ignore-init-module-imports",  # הגנה על __init__.py
            "-",  # קריאה מ-stdin
        ]

        result = subprocess.run(
            cmd,
            input=code.encode("utf-8"),
            capture_output=True,
            timeout=self.TIMEOUT_SECONDS,
            env=self._get_clean_env(),
        )

        if result.returncode != 0:
            err = self._decode_output(result.stderr) or self._decode_output(result.stdout)
            raise RuntimeError(f"autoflake failed: {err}")

        return self._decode_output(result.stdout)

    # ==================== Linting ====================

    def lint_code(self, code: str, language: str = "python", filename: str = "code.py") -> LintResult:
        """
        מריץ בדיקת lint על הקוד.

        Args:
            code: קוד לבדיקה
            language: שפת התכנות
            filename: שם קובץ (לקונטקסט)

        Returns:
            LintResult עם רשימת הבעיות
        """
        # בדיקת קוד ריק / גדול מדי
        if not code or not code.strip():
            return LintResult(success=False, error_message="הקוד ריק")
        
        try:
            encoded_code = code.encode("utf-8")
        except UnicodeEncodeError:
            return LintResult(success=False, error_message="קידוד תווים לא תקין")
        
        if len(encoded_code) > self.MAX_FILE_SIZE:
            return LintResult(success=False, error_message=f"הקובץ גדול מדי (מקסימום {self.MAX_FILE_SIZE // 1024}KB)")
        
        # בדיקת syntax - אם יש שגיאה, נחזיר אותה כ-issue ולא כ-error
        syntax_issues = []
        if language == "python":
            try:
                ast.parse(code)
            except SyntaxError as e:
                syntax_issues.append(LintIssue(
                    line=e.lineno or 1,
                    column=e.offset or 0,
                    code="E999",
                    message=f"שגיאת תחביר: {e.msg}",
                    severity="error",
                    fixable=False,
                ))

        # אם יש שגיאות syntax, נחזיר אותן (flake8 לא יעבוד על קוד שבור)
        if syntax_issues:
            score = self._calculate_score(code, syntax_issues)
            return LintResult(
                success=True,
                issues=syntax_issues,
                score=score,
            )
        
        if not self.is_tool_available("flake8"):
            return LintResult(
                success=False,
                error_message="flake8 אינו מותקן",
            )

        try:
            issues = self._run_flake8(code)
            score = self._calculate_score(code, issues)

            return LintResult(
                success=True,
                issues=issues,
                score=score,
            )

        except Exception as e:
            logger.error(f"Error linting code: {e}")
            return LintResult(
                success=False,
                error_message=str(e),
            )

    def _run_flake8(self, code: str) -> List[LintIssue]:
        """מריץ flake8 ומחזיר רשימת בעיות."""
        # כותב לקובץ זמני כי flake8 עובד טוב יותר עם קבצים
        # הערה: ב-Windows יש לפעמים בעיות הרשאה - ב-Linux/Docker עובד חלק
        with tempfile.NamedTemporaryFile(
            mode="wb",  # binary mode לשליטה בקידוד
            suffix=".py",
            delete=False,
        ) as f:
            f.write(code.encode("utf-8"))
            temp_path = f.name

        try:
            result = subprocess.run(
                [
                    "flake8",
                    "--format=%(row)d:%(col)d:%(code)s:%(text)s",
                    "--isolated",  # התעלם מקונפיגים גלובליים
                    temp_path,
                ],
                capture_output=True,
                timeout=self.TIMEOUT_SECONDS,
                env=self._get_clean_env(),
            )

            stdout = self._decode_output(result.stdout)

            issues = []
            for line in stdout.strip().split("\n"):
                if not line:
                    continue

                try:
                    parts = line.split(":", 3)
                    if len(parts) >= 4:
                        row, col, code, message = parts
                        issues.append(
                            LintIssue(
                                line=int(row),
                                column=int(col),
                                code=code,
                                message=message,
                                severity=self._get_severity(code),
                                fixable=code in self.FIXABLE_CODES,
                            )
                        )
                except (ValueError, IndexError):
                    continue

            return issues

        finally:
            Path(temp_path).unlink(missing_ok=True)

    def _get_severity(self, code: str) -> str:
        """מחזיר חומרת הבעיה לפי קוד."""
        if code.startswith("E9") or code.startswith("F"):
            return "error"
        if code.startswith("E"):
            return "warning"
        if code.startswith("W"):
            return "warning"
        return "info"

    def _calculate_score(self, code: str, issues: List[LintIssue]) -> float:
        """
        מחשב ציון איכות 0-10.
        מבוסס על מספר הבעיות ביחס לגודל הקוד.
        """
        if not issues:
            return 10.0

        lines = len(code.split("\n"))
        if lines == 0:
            return 10.0

        # ניקוד: מתחילים מ-10, מפחיתים לפי בעיות
        error_penalty = sum(1 for i in issues if i.severity == "error") * 1.0
        warning_penalty = sum(1 for i in issues if i.severity == "warning") * 0.5
        info_penalty = sum(1 for i in issues if i.severity == "info") * 0.1

        total_penalty = error_penalty + warning_penalty + info_penalty

        # מנרמל לפי גודל הקוד
        normalized_penalty = total_penalty / (lines / 10)

        score = max(0.0, 10.0 - normalized_penalty)
        return round(score, 1)

    # ==================== Auto-Fix ====================

    def auto_fix(self, code: str, level: str = "safe", language: str = "python") -> AutoFixResult:
        """
        תיקון אוטומטי של בעיות lint.

        רמות תיקון:
        - safe: רק whitespace ובעיות בטוחות
        - cautious: + מיון imports
        - aggressive: + שבירת שורות ארוכות

        Args:
            code: קוד לתיקון
            level: רמת התיקון
            language: שפת התכנות

        Returns:
            AutoFixResult עם הקוד המתוקן
        """
        is_valid, error = self.validate_input(code, language)
        if not is_valid:
            return AutoFixResult(
                success=False,
                original_code=code,
                fixed_code=code,
                error_message=error,
                level=level,
            )

        fixes_applied = []
        current_code = code

        try:
            # שלב 1: autopep8 לתיקונים בסיסיים (כל הרמות)
            if self.is_tool_available("autopep8"):
                aggression = {"safe": 0, "cautious": 1, "aggressive": 2}.get(level, 0)
                result = self.format_code(
                    current_code,
                    tool="autopep8",
                    options={"aggression": aggression},
                )
                if result.success and result.has_changes():
                    current_code = result.formatted_code
                    fixes_applied.append(f"autopep8 (אגרסיביות {aggression})")

            # שלב 2: autoflake - הסרת קוד מת (cautious+)
            # חשוב: חייב להיות לפני isort כי autoflake מסיר imports שלא בשימוש!
            if level in ("cautious", "aggressive") and self.is_tool_available("autoflake"):
                try:
                    cleaned_code = self._run_autoflake(current_code, {})
                    if cleaned_code != current_code:
                        current_code = cleaned_code
                        fixes_applied.append("autoflake (הסרת imports ומשתנים לא בשימוש)")
                except Exception as e:
                    logger.warning(f"autoflake failed, continuing: {e}")

            # שלב 3: isort למיון imports (cautious+)
            if level in ("cautious", "aggressive") and self.is_tool_available("isort"):
                result = self.format_code(current_code, tool="isort")
                if result.success and result.has_changes():
                    current_code = result.formatted_code
                    fixes_applied.append("isort (מיון imports)")

            # שלב 4: Black לעיצוב מלא (aggressive)
            if level == "aggressive" and self.is_tool_available("black"):
                result = self.format_code(current_code, tool="black")
                if result.success and result.has_changes():
                    current_code = result.formatted_code
                    fixes_applied.append("Black (עיצוב מלא)")

            # בדיקת תחביר אחרי התיקון
            try:
                ast.parse(current_code)
            except SyntaxError as e:
                return AutoFixResult(
                    success=False,
                    original_code=code,
                    fixed_code=code,
                    error_message=f"התיקון יצר שגיאת תחביר: {e.msg}",
                    level=level,
                )

            # בדיקת בעיות שנותרו
            lint_result = self.lint_code(current_code, language)

            return AutoFixResult(
                success=True,
                original_code=code,
                fixed_code=current_code,
                fixes_applied=fixes_applied,
                issues_remaining=lint_result.issues if lint_result.success else [],
                level=level,
            )

        except Exception as e:
            logger.error(f"Error in auto_fix: {e}")
            return AutoFixResult(
                success=False,
                original_code=code,
                fixed_code=code,
                error_message=str(e),
                level=level,
            )

    # ==================== Utilities ====================

    def _count_changes(self, original: str, formatted: str) -> int:
        """סופר מספר שורות ששונו."""
        diff = difflib.ndiff(original.splitlines(), formatted.splitlines())
        return sum(1 for line in diff if line.startswith(("+ ", "- ")))

    def get_diff(self, original: str, formatted: str) -> str:
        """מחזיר diff מפורמט."""
        diff = difflib.unified_diff(
            original.splitlines(keepends=True),
            formatted.splitlines(keepends=True),
            fromfile="לפני",
            tofile="אחרי",
        )
        return "".join(diff)

    def get_available_tools(self) -> Dict[str, bool]:
        """מחזיר רשימת כלים זמינים."""
        return self._check_tools_availability()


# Singleton
_service_instance: Optional[CodeFormatterService] = None


def get_code_formatter_service() -> CodeFormatterService:
    """קבלת instance יחיד של השירות."""
    global _service_instance
    if _service_instance is None:
        _service_instance = CodeFormatterService()
    return _service_instance

