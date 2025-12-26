# 📘 מדריך מימוש - עיצוב קוד אוטומטי ו-Linting ל-WebApp

> **מתי להשתמש:** בעת מימוש פיצ'רי עיצוב קוד ובדיקת איכות ב-WebApp  
> **קבצים רלוונטיים:** `services/code_formatter_service.py`, `webapp/code_tools_api.py`, `webapp/templates/code_tools.html`, `webapp/static/js/code-tools.js`  
> **מבוסס על:** [IMPLEMENTATION_GUIDE_1.1_1.2.md](https://github.com/amirbiron/CodeBot/blob/9a2a6f806a7c80cd48d5048dccc911d23f164ba2/FEATURE_SUGGESTIONS/IMPLEMENTATION_GUIDE_1.1_1.2.md)

---

## 🔄 התאמות מהמדריך המקורי

המדריך המקורי תוכנן ל-Telegram Bot. מסמך זה מתאים אותו ל-**WebApp** עם:
- Flask Blueprint API במקום Telegram handlers
- ממשק HTML/JS עם CodeMirror במקום הודעות טלגרם
- אינטגרציה עם מערכת הקבצים הקיימת ב-webapp

### 📊 סטטוס הקוד הקיים

| רכיב | סטטוס | הערות |
|------|--------|--------|
| `code_processor.py` | ✅ קיים | זיהוי שפות, הדגשת תחביר, ניתוח בסיסי |
| `services/code_service.py` | ✅ קיים | wrapper ל-code_processor |
| Black formatter | ✅ מותקן | `requirements/development.txt` |
| flake8 linter | ✅ מותקן | `requirements/development.txt` |
| isort | ✅ מותקן | `requirements/development.txt` |
| CodeMirror | ✅ קיים | `webapp/static_build/` |

---

## 📋 תוכן עניינים

1. [סקירה כללית](#סקירה-כללית)
2. [ארכיטקטורה](#ארכיטקטורה)
3. [Backend Service](#backend-service)
4. [API Endpoints](#api-endpoints)
5. [WebApp UI](#webapp-ui)
6. [אינטגרציה עם עורך הקבצים](#אינטגרציה-עם-עורך-הקבצים)
7. [בדיקות](#בדיקות)
8. [משימות עדיפות](#משימות-עדיפות)

---

## 🎯 סקירה כללית

### מטרות המימוש
- **פיצ'ר 1.1 - עיצוב קוד**: Black, isort, autopep8
- **פיצ'ר 1.2 - Linting**: flake8, pylint (אופציונלי), בדיקת תחביר
- **פיצ'ר 1.2.6 - תיקון אוטומטי**: 3 רמות (בטוח, זהיר, אגרסיבי)

### יתרונות למשתמש
- ✅ עיצוב קוד בלחיצה אחת בזמן עריכה
- ✅ זיהוי בעיות לפני שמירה
- ✅ הצגת diff לפני ואחרי
- ✅ תיקון אוטומטי עם שליטה מלאה

### קהל יעד
- משתמשי ה-WebApp שעורכים קוד Python בעורך הקבצים
- מי שרוצה לשמור על קוד נקי ועקבי

---

## 🏗️ ארכיטקטורה

### תרשים רכיבים

```
┌─────────────────────────────────────────────────────────────────┐
│                        Frontend (Browser)                        │
├─────────────────────────────────────────────────────────────────┤
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐  │
│  │  CodeMirror │  │  Diff View  │  │  Controls & Actions     │  │
│  │   Editor    │  │  Component  │  │  (Format/Lint/Fix)      │  │
│  └──────┬──────┘  └──────┬──────┘  └───────────┬─────────────┘  │
│         └────────────────┼─────────────────────┘                 │
│                          │                                       │
│                   ┌──────▼──────┐                                │
│                   │ CodeTools   │                                │
│                   │   Module    │                                │
│                   └──────┬──────┘                                │
└──────────────────────────┼──────────────────────────────────────┘
                           │ HTTP/JSON
                           ▼
┌──────────────────────────────────────────────────────────────────┐
│                        Backend (Flask)                           │
├──────────────────────────────────────────────────────────────────┤
│  ┌─────────────────────┐      ┌──────────────────────────────┐  │
│  │ code_tools_api      │ ──── │  CodeFormatterService        │  │
│  │ (Blueprint)         │      │  - format_code()             │  │
│  │                     │      │  - lint_code()               │  │
│  │ POST /api/code/     │      │  - auto_fix()                │  │
│  │     format          │      │  - get_diff()                │  │
│  │     lint            │      └──────────────────────────────┘  │
│  │     fix             │                                        │
│  │     diff            │      ┌──────────────────────────────┐  │
│  └─────────────────────┘      │  code_processor (קיים)       │  │
│                               │  - detect_language()         │  │
│                               │  - validate_syntax()         │  │
│                               │  - analyze_code()            │  │
│                               └──────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
```

### זרימת נתונים

1. **משתמש לוחץ "עיצוב"** → CodeMirror Editor
2. **בקשת API** → `/api/code/format`
3. **Service מריץ Black/isort** → תוצאה
4. **תצוגת Diff** → אישור משתמש
5. **עדכון Editor** → קוד מעוצב

---

## 🐍 Backend Service

### קובץ: `services/code_formatter_service.py`

```python
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
            fromfile='לפני',
            tofile='אחרי',
            lineterm=''
        )
        return '\n'.join(diff)
    
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
        'python': {
            'formatters': ['black', 'isort', 'autopep8'],
            'linters': ['flake8'],
            'extensions': ['.py', '.pyw']
        }
    }
    
    # בעיות שניתן לתקן אוטומטית
    FIXABLE_CODES = {
        # Whitespace
        'W291', 'W292', 'W293', 'W391',
        # Imports
        'E401', 'F401', 'I001',
        # Line length (זהיר)
        'E501',
        # Indentation
        'E101', 'E111', 'E117',
    }
    
    def __init__(self):
        self._check_tools_availability()
    
    def _check_tools_availability(self) -> Dict[str, bool]:
        """בודק אילו כלים זמינים במערכת."""
        tools = {}
        for tool in ['black', 'isort', 'flake8', 'autopep8']:
            try:
                result = subprocess.run(
                    [tool, '--version'],
                    capture_output=True,
                    timeout=5
                )
                tools[tool] = result.returncode == 0
            except (subprocess.SubprocessError, FileNotFoundError):
                tools[tool] = False
        self._available_tools = tools
        return tools
    
    def is_tool_available(self, tool: str) -> bool:
        """בודק אם כלי ספציפי זמין."""
        if not hasattr(self, '_available_tools'):
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
        
        if len(code.encode('utf-8')) > self.MAX_FILE_SIZE:
            return False, f"הקובץ גדול מדי (מקסימום {self.MAX_FILE_SIZE // 1024}KB)"
        
        try:
            code.encode('utf-8')
        except UnicodeEncodeError:
            return False, "קידוד תווים לא תקין"
        
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
        options: Optional[Dict[str, Any]] = None
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
                error_message=error
            )
        
        # בדיקת זמינות כלי
        if not self.is_tool_available(tool):
            return FormattingResult(
                success=False,
                original_code=code,
                formatted_code=code,
                error_message=f"הכלי {tool} אינו מותקן"
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
                    error_message=f"כלי לא נתמך: {tool}"
                )
            
            lines_changed = self._count_changes(code, formatted)
            
            return FormattingResult(
                success=True,
                original_code=code,
                formatted_code=formatted,
                lines_changed=lines_changed,
                tool_used=tool
            )
            
        except subprocess.TimeoutExpired:
            return FormattingResult(
                success=False,
                original_code=code,
                formatted_code=code,
                error_message="תם הזמן לעיצוב הקוד"
            )
        except Exception as e:
            logger.error(f"Error formatting code with {tool}: {e}")
            return FormattingResult(
                success=False,
                original_code=code,
                formatted_code=code,
                error_message=str(e)
            )
    
    def _get_clean_env(self) -> Dict[str, str]:
        """
        מחזיר סביבה נקייה להרצת כלים חיצוניים.
        מונע קריאת קונפיגים גלובליים שיכולים לשבש תוצאות.
        """
        env = os.environ.copy()
        env['PYTHONIOENCODING'] = 'utf-8'  # פלט תמיד UTF-8
        return env
    
    def _decode_output(self, output: bytes) -> str:
        """מפענח פלט עם טיפול בתווים בעייתיים."""
        return output.decode('utf-8', errors='replace')
    
    def _run_black(self, code: str, options: Dict) -> str:
        """מריץ Black formatter."""
        cmd = ['black', '-', '--quiet']
        
        if 'line_length' in options:
            cmd.extend(['--line-length', str(options['line_length'])])
        
        result = subprocess.run(
            cmd,
            input=code.encode('utf-8'),
            capture_output=True,
            timeout=self.TIMEOUT_SECONDS,
            env=self._get_clean_env()
        )
        
        if result.returncode != 0:
            raise RuntimeError(self._decode_output(result.stderr))
        
        return self._decode_output(result.stdout)
    
    def _run_isort(self, code: str, options: Dict) -> str:
        """מריץ isort למיון imports."""
        cmd = ['isort', '-']
        
        if 'line_length' in options:
            cmd.extend(['--line-length', str(options['line_length'])])
        
        # Black compatibility mode - קריטי למניעת התנגשויות!
        cmd.extend(['--profile', 'black'])
        
        env = self._get_clean_env()
        
        result = subprocess.run(
            cmd,
            input=code.encode('utf-8'),
            capture_output=True,
            timeout=self.TIMEOUT_SECONDS,
            env=env
        )
        
        return self._decode_output(result.stdout)
    
    def _run_autopep8(self, code: str, options: Dict) -> str:
        """מריץ autopep8."""
        cmd = ['autopep8', '-']
        
        if 'line_length' in options:
            cmd.extend(['--max-line-length', str(options['line_length'])])
        
        # רמת אגרסיביות
        aggression = options.get('aggression', 1)
        for _ in range(aggression):
            cmd.append('-a')
        
        result = subprocess.run(
            cmd,
            input=code.encode('utf-8'),
            capture_output=True,
            timeout=self.TIMEOUT_SECONDS,
            env=self._get_clean_env()
        )
        
        return self._decode_output(result.stdout)
    
    # ==================== Linting ====================
    
    def lint_code(
        self,
        code: str,
        language: str = "python",
        filename: str = "code.py"
    ) -> LintResult:
        """
        מריץ בדיקת lint על הקוד.
        
        Args:
            code: קוד לבדיקה
            language: שפת התכנות
            filename: שם קובץ (לקונטקסט)
        
        Returns:
            LintResult עם רשימת הבעיות
        """
        is_valid, error = self.validate_input(code, language)
        if not is_valid:
            return LintResult(
                success=False,
                error_message=error
            )
        
        if not self.is_tool_available('flake8'):
            return LintResult(
                success=False,
                error_message="flake8 אינו מותקן"
            )
        
        try:
            issues = self._run_flake8(code)
            score = self._calculate_score(code, issues)
            
            return LintResult(
                success=True,
                issues=issues,
                score=score
            )
            
        except Exception as e:
            logger.error(f"Error linting code: {e}")
            return LintResult(
                success=False,
                error_message=str(e)
            )
    
    def _run_flake8(self, code: str) -> List[LintIssue]:
        """מריץ flake8 ומחזיר רשימת בעיות."""
        # כותב לקובץ זמני כי flake8 עובד טוב יותר עם קבצים
        # הערה: ב-Windows יש לפעמים בעיות הרשאה - ב-Linux/Docker עובד חלק
        with tempfile.NamedTemporaryFile(
            mode='wb',  # binary mode לשליטה בקידוד
            suffix='.py',
            delete=False
        ) as f:
            f.write(code.encode('utf-8'))
            temp_path = f.name
        
        try:
            result = subprocess.run(
                [
                    'flake8',
                    '--format=%(row)d:%(col)d:%(code)s:%(text)s',
                    '--isolated',  # התעלם מקונפיגים גלובליים
                    temp_path
                ],
                capture_output=True,
                timeout=self.TIMEOUT_SECONDS,
                env=self._get_clean_env()
            )
            
            stdout = self._decode_output(result.stdout)
            
            issues = []
            for line in stdout.strip().split('\n'):
                if not line:
                    continue
                
                try:
                    parts = line.split(':', 3)
                    if len(parts) >= 4:
                        row, col, code, message = parts
                        issues.append(LintIssue(
                            line=int(row),
                            column=int(col),
                            code=code,
                            message=message,
                            severity=self._get_severity(code),
                            fixable=code in self.FIXABLE_CODES
                        ))
                except (ValueError, IndexError):
                    continue
            
            return issues
            
        finally:
            Path(temp_path).unlink(missing_ok=True)
    
    def _get_severity(self, code: str) -> str:
        """מחזיר חומרת הבעיה לפי קוד."""
        if code.startswith('E9') or code.startswith('F'):
            return "error"
        if code.startswith('E'):
            return "warning"
        if code.startswith('W'):
            return "warning"
        return "info"
    
    def _calculate_score(self, code: str, issues: List[LintIssue]) -> float:
        """
        מחשב ציון איכות 0-10.
        מבוסס על מספר הבעיות ביחס לגודל הקוד.
        """
        if not issues:
            return 10.0
        
        lines = len(code.split('\n'))
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
    
    def auto_fix(
        self,
        code: str,
        level: str = "safe",
        language: str = "python"
    ) -> AutoFixResult:
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
                level=level
            )
        
        fixes_applied = []
        current_code = code
        
        try:
            # שלב 1: autopep8 לתיקונים בסיסיים (כל הרמות)
            if self.is_tool_available('autopep8'):
                aggression = {'safe': 0, 'cautious': 1, 'aggressive': 2}.get(level, 0)
                result = self.format_code(
                    current_code,
                    tool='autopep8',
                    options={'aggression': aggression}
                )
                if result.success and result.has_changes():
                    current_code = result.formatted_code
                    fixes_applied.append(f"autopep8 (אגרסיביות {aggression})")
            
            # שלב 2: isort למיון imports (cautious+)
            if level in ('cautious', 'aggressive') and self.is_tool_available('isort'):
                result = self.format_code(current_code, tool='isort')
                if result.success and result.has_changes():
                    current_code = result.formatted_code
                    fixes_applied.append("isort (מיון imports)")
            
            # שלב 3: Black לעיצוב מלא (aggressive)
            if level == 'aggressive' and self.is_tool_available('black'):
                result = self.format_code(current_code, tool='black')
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
                    level=level
                )
            
            # בדיקת בעיות שנותרו
            lint_result = self.lint_code(current_code, language)
            
            return AutoFixResult(
                success=True,
                original_code=code,
                fixed_code=current_code,
                fixes_applied=fixes_applied,
                issues_remaining=lint_result.issues if lint_result.success else [],
                level=level
            )
            
        except Exception as e:
            logger.error(f"Error in auto_fix: {e}")
            return AutoFixResult(
                success=False,
                original_code=code,
                fixed_code=code,
                error_message=str(e),
                level=level
            )
    
    # ==================== Utilities ====================
    
    def _count_changes(self, original: str, formatted: str) -> int:
        """סופר מספר שורות ששונו."""
        diff = difflib.ndiff(original.splitlines(), formatted.splitlines())
        return sum(1 for line in diff if line.startswith(('+ ', '- ')))
    
    def get_diff(self, original: str, formatted: str) -> str:
        """מחזיר diff מפורמט."""
        diff = difflib.unified_diff(
            original.splitlines(keepends=True),
            formatted.splitlines(keepends=True),
            fromfile='לפני',
            tofile='אחרי'
        )
        return ''.join(diff)
    
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
```

---

## 🌐 API Endpoints

### קובץ: `webapp/code_tools_api.py`

```python
"""
Code Tools API Blueprint
========================
נקודות קצה לעיצוב קוד, linting ותיקון אוטומטי.
"""

from flask import Blueprint, request, jsonify
from services.code_formatter_service import get_code_formatter_service
import json

code_tools_bp = Blueprint('code_tools', __name__, url_prefix='/api/code')


@code_tools_bp.route('/format', methods=['POST'])
def format_code():
    """
    עיצוב קוד.

    Request Body:
        {
            "code": "<source code>",
            "language": "python",        // אופציונלי
            "tool": "black",             // black | isort | autopep8
            "options": {                 // אופציונלי
                "line_length": 88
            }
        }

    Response:
        {
            "success": true,
            "formatted_code": "...",
            "diff": "...",
            "lines_changed": 5,
            "has_changes": true,
            "tool_used": "black"
        }
    """
    data = request.get_json()
    if not data or 'code' not in data:
        return jsonify({'success': False, 'error': 'חסר קוד'}), 400

    service = get_code_formatter_service()

    result = service.format_code(
        code=data['code'],
        language=data.get('language', 'python'),
        tool=data.get('tool', 'black'),
        options=data.get('options', {})
    )

    return jsonify({
        'success': result.success,
        'formatted_code': result.formatted_code,
        'diff': result.get_diff() if result.success else None,
        'lines_changed': result.lines_changed,
        'has_changes': result.has_changes(),
        'tool_used': result.tool_used,
        'error': result.error_message
    })


@code_tools_bp.route('/lint', methods=['POST'])
def lint_code():
    """
    בדיקת איכות קוד.

    Request Body:
        {
            "code": "<source code>",
            "language": "python",
            "filename": "example.py"     // אופציונלי
        }

    Response:
        {
            "success": true,
            "score": 8.5,
            "issues": [
                {
                    "line": 10,
                    "column": 5,
                    "code": "E501",
                    "message": "line too long",
                    "severity": "warning",
                    "fixable": true
                }
            ],
            "has_errors": false,
            "fixable_count": 3
        }
    """
    data = request.get_json()
    if not data or 'code' not in data:
        return jsonify({'success': False, 'error': 'חסר קוד'}), 400

    service = get_code_formatter_service()

    result = service.lint_code(
        code=data['code'],
        language=data.get('language', 'python'),
        filename=data.get('filename', 'code.py')
    )

    issues = [
        {
            'line': i.line,
            'column': i.column,
            'code': i.code,
            'message': i.message,
            'severity': i.severity,
            'fixable': i.fixable
        }
        for i in result.issues
    ]

    return jsonify({
        'success': result.success,
        'score': result.score,
        'issues': issues,
        'has_errors': result.has_errors,
        'fixable_count': result.fixable_count,
        'error': result.error_message
    })


@code_tools_bp.route('/fix', methods=['POST'])
def auto_fix_code():
    """
    תיקון אוטומטי של בעיות.

    Request Body:
        {
            "code": "<source code>",
            "level": "safe",             // safe | cautious | aggressive
            "language": "python"
        }

    Response:
        {
            "success": true,
            "fixed_code": "...",
            "diff": "...",
            "fixes_applied": ["autopep8", "isort"],
            "issues_remaining": [...],
            "level": "safe"
        }
    """
    data = request.get_json()
    if not data or 'code' not in data:
        return jsonify({'success': False, 'error': 'חסר קוד'}), 400

    service = get_code_formatter_service()

    result = service.auto_fix(
        code=data['code'],
        level=data.get('level', 'safe'),
        language=data.get('language', 'python')
    )

    diff = service.get_diff(result.original_code, result.fixed_code) if result.success else None

    issues_remaining = [
        {
            'line': i.line,
            'column': i.column,
            'code': i.code,
            'message': i.message,
            'severity': i.severity
        }
        for i in result.issues_remaining
    ]

    return jsonify({
        'success': result.success,
        'fixed_code': result.fixed_code,
        'diff': diff,
        'fixes_applied': result.fixes_applied,
        'issues_remaining': issues_remaining,
        'level': result.level,
        'error': result.error_message
    })


@code_tools_bp.route('/tools', methods=['GET'])
def get_available_tools():
    """
    קבלת רשימת כלים זמינים.

    Response:
        {
            "tools": {
                "black": true,
                "isort": true,
                "flake8": true,
                "autopep8": false
            }
        }
    """
    service = get_code_formatter_service()
    return jsonify({
        'tools': service.get_available_tools()
    })


@code_tools_bp.route('/diff', methods=['POST'])
def get_diff():
    """
    השוואת שני קטעי קוד.

    Request Body:
        {
            "original": "<original code>",
            "modified": "<modified code>"
        }

    Response:
        {
            "diff": "...",
            "lines_changed": 5
        }
    """
    data = request.get_json()
    if not data or 'original' not in data or 'modified' not in data:
        return jsonify({'success': False, 'error': 'חסר קוד מקור או יעד'}), 400

    service = get_code_formatter_service()

    diff = service.get_diff(data['original'], data['modified'])
    lines_changed = service._count_changes(data['original'], data['modified'])

    return jsonify({
        'success': True,
        'diff': diff,
        'lines_changed': lines_changed
    })
```

### רישום ה-Blueprint

הוסף ל-`webapp/app.py`:

```python
try:
    from webapp.code_tools_api import code_tools_bp
    app.register_blueprint(code_tools_bp)
except Exception as e:
    logger.warning(f"Failed to register code_tools_bp: {e}")
```

---

## 🎨 WebApp UI

### אפשרות 1: Toolbar בעורך הקבצים

הוסף כפתורים ל-`edit_file.html`:

```html
<!-- הוסף ל-split-toolbar -->
<div class="code-tools-group" data-show-for-language="python">
    <button type="button"
            class="btn btn-sm btn-outline"
            id="btn-format-code"
            title="עיצוב קוד (Ctrl+Shift+F)">
        <i class="fas fa-magic"></i>
        עיצוב
    </button>
    <button type="button"
            class="btn btn-sm btn-outline"
            id="btn-lint-code"
            title="בדיקת איכות (Ctrl+Shift+L)">
        <i class="fas fa-check-circle"></i>
        Lint
    </button>
    <div class="dropdown">
        <button type="button"
                class="btn btn-sm btn-outline dropdown-toggle"
                id="btn-auto-fix">
            <i class="fas fa-wrench"></i>
            תיקון
        </button>
        <div class="dropdown-menu">
            <button class="dropdown-item" data-level="safe">
                🛡️ בטוח (whitespace)
            </button>
            <button class="dropdown-item" data-level="cautious">
                ⚠️ זהיר (+imports)
            </button>
            <button class="dropdown-item" data-level="aggressive">
                🔥 אגרסיבי (מלא)
            </button>
        </div>
    </div>
</div>
```

### אפשרות 2: דף ייעודי לכלי קוד

צור `webapp/templates/code_tools.html`:

```html
{% extends "base.html" %}

{% block title %}כלי קוד - Code Keeper Bot{% endblock %}

{% block extra_css %}
<link rel="stylesheet" href="{{ url_for('static', filename='css/code-tools.css') }}?v={{ static_version }}">
{% endblock %}

{% block content %}
<div class="code-tools-container">
    <!-- Header -->
    <div class="tools-header">
        <h1>
            <span class="icon">🛠️</span>
            כלי קוד
        </h1>
        <p class="subtitle">עיצוב, בדיקת איכות ותיקון אוטומטי</p>
    </div>

    <!-- Toolbar -->
    <div class="tools-toolbar glass-card">
        <div class="toolbar-group primary-actions">
            <button id="btn-format" class="btn btn-primary" title="עיצוב (Ctrl+Shift+F)">
                <span class="btn-icon">✨</span>
                עיצוב
            </button>
            <button id="btn-lint" class="btn btn-info" title="בדיקת איכות">
                <span class="btn-icon">🔍</span>
                Lint
            </button>
            <div class="dropdown">
                <button id="btn-fix" class="btn btn-warning dropdown-toggle">
                    <span class="btn-icon">🔧</span>
                    תיקון
                </button>
                <div class="dropdown-menu">
                    <button class="dropdown-item" data-level="safe">
                        🛡️ בטוח
                        <small>whitespace בלבד</small>
                    </button>
                    <button class="dropdown-item" data-level="cautious">
                        ⚠️ זהיר
                        <small>+ מיון imports</small>
                    </button>
                    <button class="dropdown-item" data-level="aggressive">
                        🔥 אגרסיבי
                        <small>עיצוב מלא</small>
                    </button>
                </div>
            </div>
        </div>

        <div class="toolbar-group options">
            <select id="format-tool" class="form-select form-select-sm">
                <option value="black">Black</option>
                <option value="autopep8">autopep8</option>
            </select>
            <label class="option-label">
                <input type="number" id="line-length" value="88" min="40" max="200">
                <span>אורך שורה</span>
            </label>
        </div>
    </div>

    <!-- Main Content -->
    <div class="tools-content">
        <!-- Input Panel -->
        <div class="input-panel glass-card">
            <div class="panel-header">
                <span class="panel-title">קוד מקור</span>
                <select id="language-select" class="form-select form-select-sm">
                    <option value="python">Python</option>
                </select>
            </div>
            <div class="panel-body">
                <div id="input-editor"></div>
            </div>
            <div class="panel-footer">
                <span id="input-stats"></span>
            </div>
        </div>

        <!-- Output Panel -->
        <div class="output-panel glass-card">
            <div class="panel-header">
                <span class="panel-title">תוצאה</span>
                <div class="view-toggle">
                    <button class="view-btn active" data-view="code">קוד</button>
                    <button class="view-btn" data-view="diff">Diff</button>
                    <button class="view-btn" data-view="issues">בעיות</button>
                </div>
            </div>
            <div class="panel-body">
                <div id="code-view" class="view-content active">
                    <div id="output-editor"></div>
                </div>
                <div id="diff-view" class="view-content">
                    <pre id="diff-content"></pre>
                </div>
                <div id="issues-view" class="view-content">
                    <div id="issues-list"></div>
                </div>
            </div>
            <div class="panel-footer">
                <div id="lint-score"></div>
                <button id="btn-apply" class="btn btn-sm btn-success" disabled>
                    החל שינויים
                </button>
            </div>
        </div>
    </div>

    <!-- Status Bar -->
    <div id="status-bar" class="status-bar glass-card hidden">
        <span class="status-icon"></span>
        <span class="status-message"></span>
    </div>
</div>
{% endblock %}

{% block extra_js %}
<script src="{{ url_for('static', filename='js/code-tools.js') }}?v={{ static_version }}"></script>
{% endblock %}
```

---

## 🔗 אינטגרציה עם עורך הקבצים

### הוספה ל-`webapp/static/js/file-form.js`

```javascript
/**
 * Code Tools Integration
 * ======================
 * אינטגרציה של כלי עיצוב/lint עם עורך הקבצים הקיים.
 */

const CodeToolsIntegration = {
    
    /**
     * אתחול - נקרא מתוך FileFormManager
     */
    init(editorInstance, languageSelect) {
        this.editor = editorInstance;
        this.languageSelect = languageSelect;
        this.bindEvents();
        this.updateToolsVisibility();
    },
    
    /**
     * קישור אירועים
     */
    bindEvents() {
        // כפתורי Toolbar
        document.getElementById('btn-format-code')?.addEventListener('click', () => this.formatCode());
        document.getElementById('btn-lint-code')?.addEventListener('click', () => this.lintCode());
        
        // תפריט תיקון
        document.querySelectorAll('[data-level]').forEach(btn => {
            btn.addEventListener('click', () => this.autoFix(btn.dataset.level));
        });
        
        // קיצורי מקלדת
        document.addEventListener('keydown', (e) => {
            if ((e.ctrlKey || e.metaKey) && e.shiftKey) {
                if (e.key === 'F') {
                    e.preventDefault();
                    this.formatCode();
                } else if (e.key === 'L') {
                    e.preventDefault();
                    this.lintCode();
                }
            }
        });
        
        // עדכון כשמשתנה השפה
        this.languageSelect?.addEventListener('change', () => this.updateToolsVisibility());
    },
    
    /**
     * הצגת/הסתרת כלים לפי שפה
     */
    updateToolsVisibility() {
        const language = this.languageSelect?.value || 'text';
        const toolsGroup = document.querySelector('.code-tools-group');
        
        if (toolsGroup) {
            // כרגע תומכים רק ב-Python
            toolsGroup.style.display = language === 'python' ? 'flex' : 'none';
        }
    },
    
    /**
     * קבלת קוד מה-editor
     */
    getCode() {
        if (this.editor && typeof this.editor.getValue === 'function') {
            return this.editor.getValue();
        }
        return document.getElementById('codeTextarea')?.value || '';
    },
    
    /**
     * עדכון קוד ב-editor
     */
    setCode(code) {
        if (this.editor && typeof this.editor.setValue === 'function') {
            this.editor.setValue(code);
        } else {
            const textarea = document.getElementById('codeTextarea');
            if (textarea) textarea.value = code;
        }
    },
    
    /**
     * עיצוב קוד
     */
    async formatCode() {
        const code = this.getCode();
        if (!code.trim()) {
            this.showStatus('אין קוד לעיצוב', 'warning');
            return;
        }
        
        this.showStatus('מעצב...', 'loading');
        
        try {
            const response = await fetch('/api/code/format', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    code,
                    tool: 'black',
                    language: 'python'
                })
            });
            
            const result = await response.json();
            
            if (result.success) {
                if (result.has_changes) {
                    // הצג diff ובקש אישור
                    const confirmed = await this.showDiffConfirmation(
                        code,
                        result.formatted_code,
                        result.lines_changed
                    );
                    
                    if (confirmed) {
                        this.setCode(result.formatted_code);
                        this.showStatus(`עוצב בהצלחה (${result.lines_changed} שורות)`, 'success');
                    }
                } else {
                    this.showStatus('הקוד כבר מעוצב', 'info');
                }
            } else {
                this.showStatus(result.error || 'שגיאה בעיצוב', 'error');
            }
        } catch (error) {
            this.showStatus('שגיאה בתקשורת', 'error');
            console.error('Format error:', error);
        }
    },
    
    /**
     * בדיקת lint
     */
    async lintCode() {
        const code = this.getCode();
        if (!code.trim()) {
            this.showStatus('אין קוד לבדיקה', 'warning');
            return;
        }
        
        this.showStatus('בודק...', 'loading');
        
        try {
            const response = await fetch('/api/code/lint', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ code, language: 'python' })
            });
            
            const result = await response.json();
            
            if (result.success) {
                this.showLintResults(result);
            } else {
                this.showStatus(result.error || 'שגיאה בבדיקה', 'error');
            }
        } catch (error) {
            this.showStatus('שגיאה בתקשורת', 'error');
            console.error('Lint error:', error);
        }
    },
    
    /**
     * תיקון אוטומטי
     */
    async autoFix(level) {
        const code = this.getCode();
        if (!code.trim()) {
            this.showStatus('אין קוד לתיקון', 'warning');
            return;
        }
        
        this.showStatus('מתקן...', 'loading');
        
        try {
            const response = await fetch('/api/code/fix', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ code, level, language: 'python' })
            });
            
            const result = await response.json();
            
            if (result.success) {
                if (result.fixes_applied.length > 0) {
                    const confirmed = await this.showDiffConfirmation(
                        code,
                        result.fixed_code,
                        result.fixes_applied.length,
                        result.fixes_applied
                    );
                    
                    if (confirmed) {
                        this.setCode(result.fixed_code);
                        this.showStatus(
                            `תוקן: ${result.fixes_applied.join(', ')}`,
                            'success'
                        );
                    }
                } else {
                    this.showStatus('אין תיקונים נדרשים', 'info');
                }
            } else {
                this.showStatus(result.error || 'שגיאה בתיקון', 'error');
            }
        } catch (error) {
            this.showStatus('שגיאה בתקשורת', 'error');
            console.error('Fix error:', error);
        }
    },
    
    /**
     * הצגת תוצאות lint
     */
    showLintResults(result) {
        const { score, issues, fixable_count } = result;
        
        // יצירת modal או panel לתוצאות
        let html = `
            <div class="lint-results">
                <div class="lint-score ${score >= 8 ? 'good' : score >= 5 ? 'medium' : 'bad'}">
                    <span class="score-value">${score}</span>
                    <span class="score-max">/10</span>
                </div>
        `;
        
        if (issues.length === 0) {
            html += '<p class="no-issues">✅ לא נמצאו בעיות!</p>';
        } else {
            html += `
                <div class="issues-summary">
                    ${issues.length} בעיות נמצאו
                    ${fixable_count > 0 ? `(${fixable_count} ניתנות לתיקון אוטומטי)` : ''}
                </div>
                <ul class="issues-list">
            `;
            
            for (const issue of issues.slice(0, 10)) {
                html += `
                    <li class="issue-item ${issue.severity}">
                        <span class="issue-location">שורה ${issue.line}</span>
                        <span class="issue-code">${issue.code}</span>
                        <span class="issue-message">${issue.message}</span>
                        ${issue.fixable ? '<span class="issue-fixable">🔧</span>' : ''}
                    </li>
                `;
            }
            
            if (issues.length > 10) {
                html += `<li class="more-issues">...ועוד ${issues.length - 10} בעיות</li>`;
            }
            
            html += '</ul>';
        }
        
        html += '</div>';
        
        // הצג ב-modal או toast
        this.showModal('תוצאות Lint', html, fixable_count > 0 ? [
            { text: 'תקן אוטומטית', action: () => this.autoFix('safe'), primary: true },
            { text: 'סגור', action: 'close' }
        ] : [{ text: 'סגור', action: 'close' }]);
    },
    
    /**
     * הצגת diff לאישור
     */
    async showDiffConfirmation(original, modified, changesCount, fixesList = null) {
        return new Promise((resolve) => {
            // חישוב diff
            const diffLines = this.computeDiff(original, modified);
            
            let html = `
                <div class="diff-preview">
                    <div class="diff-stats">
                        ${changesCount} שינויים
                        ${fixesList ? `<br><small>${fixesList.join(', ')}</small>` : ''}
                    </div>
                    <pre class="diff-content">${this.escapeHtml(diffLines)}</pre>
                </div>
            `;
            
            this.showModal('אישור שינויים', html, [
                { text: 'החל', action: () => resolve(true), primary: true },
                { text: 'ביטול', action: () => resolve(false) }
            ]);
        });
    },
    
    /**
     * חישוב diff
     * 
     * הערה: לגרסת Production מומלץ להשתמש בספריות מקצועיות:
     * - diff-match-patch של Google (קל ומהיר)
     * - merge-view של CodeMirror (כבר קיים בפרויקט!)
     * 
     * דוגמה עם CodeMirror MergeView:
     * ```javascript
     * import { MergeView } from '@codemirror/merge';
     * const view = new MergeView({
     *     a: { doc: original },
     *     b: { doc: modified },
     *     parent: container
     * });
     * ```
     */
    computeDiff(original, modified) {
        // גרסה בסיסית - לגרסה 2.0 החלף בספרייה מקצועית
        const origLines = original.split('\n');
        const modLines = modified.split('\n');
        let diff = '';
        
        const maxLines = Math.max(origLines.length, modLines.length);
        for (let i = 0; i < Math.min(maxLines, 50); i++) {
            const orig = origLines[i] || '';
            const mod = modLines[i] || '';
            
            if (orig !== mod) {
                if (orig) diff += `- ${orig}\n`;
                if (mod) diff += `+ ${mod}\n`;
            }
        }
        
        if (maxLines > 50) {
            diff += `\n... (${maxLines - 50} שורות נוספות)`;
        }
        
        return diff || '(אין שינויים)';
    },
    
    /**
     * הצגת הודעת סטטוס
     */
    showStatus(message, type) {
        // שימוש במנגנון Toast הקיים
        if (window.showToast) {
            window.showToast(message, type);
        } else {
            console.log(`[${type}] ${message}`);
        }
    },
    
    /**
     * הצגת modal
     */
    showModal(title, content, buttons) {
        // שימוש במנגנון modal קיים או יצירת אחד פשוט
        const modal = document.createElement('div');
        modal.className = 'code-tools-modal';
        modal.innerHTML = `
            <div class="modal-backdrop"></div>
            <div class="modal-content">
                <div class="modal-header">
                    <h3>${title}</h3>
                    <button class="modal-close">&times;</button>
                </div>
                <div class="modal-body">${content}</div>
                <div class="modal-footer">
                    ${buttons.map(b => `
                        <button class="btn ${b.primary ? 'btn-primary' : 'btn-outline'}"
                                data-action="${b.action === 'close' ? 'close' : 'custom'}">
                            ${b.text}
                        </button>
                    `).join('')}
                </div>
            </div>
        `;
        
        document.body.appendChild(modal);
        
        // Bind events
        modal.querySelector('.modal-close').onclick = () => modal.remove();
        modal.querySelector('.modal-backdrop').onclick = () => modal.remove();
        
        buttons.forEach((btn, i) => {
            const btnEl = modal.querySelectorAll('.modal-footer button')[i];
            if (btnEl && typeof btn.action === 'function') {
                btnEl.onclick = () => {
                    btn.action();
                    modal.remove();
                };
            } else if (btnEl) {
                btnEl.onclick = () => modal.remove();
            }
        });
    },
    
    /**
     * Escape HTML
     */
    escapeHtml(str) {
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }
};

// Export
window.CodeToolsIntegration = CodeToolsIntegration;
```

---

## 🧪 בדיקות

### קובץ: `tests/test_code_formatter_service.py`

```python
"""
Tests for Code Formatter Service
================================
"""

import pytest
from services.code_formatter_service import (
    CodeFormatterService,
    FormattingResult,
    LintResult,
    AutoFixResult,
    get_code_formatter_service
)


@pytest.fixture
def service():
    return CodeFormatterService()


class TestValidation:
    """בדיקות ולידציה."""
    
    def test_validate_empty_code(self, service):
        is_valid, error = service.validate_input("")
        assert is_valid is False
        assert "ריק" in error
    
    def test_validate_large_file(self, service):
        large_code = "x = 1\n" * 100000
        is_valid, error = service.validate_input(large_code)
        assert is_valid is False
        assert "גדול" in error
    
    def test_validate_syntax_error(self, service):
        bad_code = "def foo(\n    pass"
        is_valid, error = service.validate_input(bad_code, "python")
        assert is_valid is False
        assert "תחביר" in error
    
    def test_validate_good_code(self, service):
        good_code = "def foo():\n    pass"
        is_valid, error = service.validate_input(good_code, "python")
        assert is_valid is True
        assert error is None


class TestFormatting:
    """בדיקות עיצוב."""
    
    @pytest.mark.skipif(
        not CodeFormatterService().is_tool_available('black'),
        reason="Black not available"
    )
    def test_format_with_black(self, service):
        messy_code = "x=1+2"
        result = service.format_code(messy_code, tool='black')
        
        assert result.success
        assert "x = 1 + 2" in result.formatted_code
    
    @pytest.mark.skipif(
        not CodeFormatterService().is_tool_available('isort'),
        reason="isort not available"
    )
    def test_format_imports_with_isort(self, service):
        code = "import sys\nimport os"
        result = service.format_code(code, tool='isort')
        
        assert result.success
        # isort ממיין אלפבתית
        assert result.formatted_code.index('os') < result.formatted_code.index('sys')
    
    def test_format_unavailable_tool(self, service):
        result = service.format_code("x=1", tool='nonexistent')
        assert result.success is False
        assert "לא נתמך" in result.error_message


class TestLinting:
    """בדיקות lint."""
    
    @pytest.mark.skipif(
        not CodeFormatterService().is_tool_available('flake8'),
        reason="flake8 not available"
    )
    def test_lint_clean_code(self, service):
        clean_code = '''def hello():
    """Say hello."""
    print("Hello")
'''
        result = service.lint_code(clean_code)
        
        assert result.success
        assert result.score >= 8.0
    
    @pytest.mark.skipif(
        not CodeFormatterService().is_tool_available('flake8'),
        reason="flake8 not available"
    )
    def test_lint_bad_code(self, service):
        bad_code = "x=1+2;y=3"  # Multiple issues
        result = service.lint_code(bad_code)
        
        assert result.success
        assert len(result.issues) > 0
    
    def test_lint_score_calculation(self, service):
        # מוק את _run_flake8 כדי לבדוק חישוב
        from services.code_formatter_service import LintIssue
        
        issues = [
            LintIssue(1, 1, "E501", "line too long", "warning", True),
            LintIssue(2, 1, "W291", "trailing whitespace", "warning", True),
        ]
        
        score = service._calculate_score("x = 1\ny = 2\nz = 3", issues)
        assert 0 <= score <= 10


class TestAutoFix:
    """בדיקות תיקון אוטומטי."""
    
    @pytest.mark.skipif(
        not CodeFormatterService().is_tool_available('autopep8'),
        reason="autopep8 not available"
    )
    def test_auto_fix_safe(self, service):
        code_with_whitespace = "x = 1   \ny = 2"  # Trailing whitespace
        result = service.auto_fix(code_with_whitespace, level='safe')
        
        assert result.success
        assert "   " not in result.fixed_code
    
    def test_auto_fix_preserves_syntax(self, service):
        code = "def foo():\n    return 1"
        result = service.auto_fix(code, level='aggressive')
        
        if result.success:
            # וודא שהקוד עדיין תקין
            import ast
            ast.parse(result.fixed_code)


class TestDiff:
    """בדיקות diff."""
    
    def test_get_diff(self, service):
        original = "x = 1"
        modified = "x = 2"
        
        diff = service.get_diff(original, modified)
        
        assert "-x = 1" in diff
        assert "+x = 2" in diff
    
    def test_count_changes(self, service):
        original = "a\nb\nc"
        modified = "a\nB\nc"
        
        count = service._count_changes(original, modified)
        assert count == 2  # One removal, one addition


class TestServiceSingleton:
    """בדיקות singleton."""
    
    def test_singleton(self):
        service1 = get_code_formatter_service()
        service2 = get_code_formatter_service()
        
        assert service1 is service2
```

---

## 📋 משימות עדיפות

### P0 - חובה לפני השקה

- [ ] מימוש `CodeFormatterService` עם Black, flake8
- [ ] יצירת API endpoints ורישום Blueprint
- [ ] אינטגרציה בסיסית עם עורך הקבצים
- [ ] בדיקות יחידה ל-Service

### P1 - חשוב

- [ ] תמיכה ב-isort ו-autopep8
- [ ] UI לתוצאות lint עם הדגשת שורות
- [ ] הצגת diff לפני אישור שינויים
- [ ] קיצורי מקלדת (Ctrl+Shift+F)

### P2 - שיפורים

- [ ] דף ייעודי `/tools/code` לעבודה עם קוד
- [ ] שמירת הגדרות (line_length, tool) ב-localStorage
- [ ] היסטוריית עיצובים
- [ ] תמיכה בשפות נוספות (JavaScript, TypeScript)

### P3 - עתידי

- [ ] אינטגרציה עם pylint
- [ ] המלצות AI לשיפור קוד
- [ ] תצוגת Live lint בזמן כתיבה
- [ ] החלפת flake8 ב-**ruff** (מהיר פי 100!)
- [ ] Background Tasks עם Celery לקבצים גדולים

---

## 🚀 שיפורים לגרסה 2.0

### 1. החלפת Linter ב-Ruff

[Ruff](https://github.com/astral-sh/ruff) הוא linter חדש וMEGA מהיר (פי 10-100 מ-flake8):

```python
# הארכיטקטורה המודולרית מאפשרת החלפה פשוטה:
def _run_ruff(self, code: str) -> List[LintIssue]:
    result = subprocess.run(
        ['ruff', 'check', '--format=json', '-'],
        input=code.encode('utf-8'),
        capture_output=True,
        timeout=self.TIMEOUT_SECONDS,
        env=self._get_clean_env()
    )
    # Ruff מחזיר JSON ישירות - קל יותר לפרסר
    import json
    data = json.loads(self._decode_output(result.stdout))
    return [LintIssue(...) for item in data]
```

### 2. Background Tasks עם Celery

לקבצים גדולים ועומס גבוה:

```python
# tasks.py
from celery import Celery
app = Celery('code_tools', broker='redis://localhost:6379/0')

@app.task
def format_code_async(code: str, tool: str, options: dict):
    service = get_code_formatter_service()
    return service.format_code(code, tool=tool, options=options)

# API
@code_tools_bp.route('/format', methods=['POST'])
def format_code():
    task = format_code_async.delay(code, tool, options)
    return jsonify({'task_id': task.id})

@code_tools_bp.route('/format/<task_id>', methods=['GET'])
def get_format_result(task_id):
    task = format_code_async.AsyncResult(task_id)
    if task.ready():
        return jsonify({'status': 'done', 'result': task.result})
    return jsonify({'status': 'pending'})
```

### 3. תצוגת Diff מקצועית

השתמש ב-CodeMirror MergeView שכבר קיים בפרויקט:

```javascript
// webapp/static/js/diff-view.js
import { MergeView } from '@codemirror/merge';
import { python } from '@codemirror/lang-python';

function showProfessionalDiff(original, modified, container) {
    return new MergeView({
        a: { doc: original, extensions: [python()] },
        b: { doc: modified, extensions: [python()] },
        parent: container,
        highlightChanges: true,
        gutter: true
    });
}
```

---

## ⚠️ נקודות חשובות

### 1. תלות בסביבת Production

הכלים (`black`, `flake8`, `isort`) מותקנים רק ב-`development.txt`.  
**לשימוש ב-production**, הוסף ל-`requirements/production.txt`:

```txt
black>=25.0.0
flake8>=7.0.0
isort>=6.0.0
autopep8>=2.0.0
```

### 2. בדיקת תחביר אחרי תיקון

**קריטי**: תמיד לבדוק `ast.parse()` אחרי תיקון אוטומטי!  
תיקונים אגרסיביים יכולים לשבור קוד.

### 3. מקרי קצה מסוכנים

| מקרה | סיכון | פתרון |
|------|-------|-------|
| שורה עם string ארוך | Black עלול לשבור | הגבלת אורך שורה |
| קוד עם type hints מורכבים | isort עלול להזיז | בדיקת תחביר אחרי |
| קוד עם `# noqa` | autopep8 עלול להתעלם | שמירת הערות |

### 4. ביצועים ו-Blocking (קריטי!)

הפעלת `subprocess.run` בתוך Request של Flask היא פעולה **חוסמת (Blocking)**.  
אם הקוד כבד או שהשרת עמוס, ה-Worker ייתקע עד ה-Timeout.

**גרסה 1.0 (MVP):**
- הגבל גודל קובץ ל-500KB
- Timeout של **5-10 שניות** (לא 30!)
- הרץ עם Gunicorn ומספיק Workers:
  ```bash
  gunicorn -w 4 -b 0.0.0.0:5000 webapp.app:app
  ```

**גרסה 2.0 (Production Scale):**
- העבר עיבוד ל-Background Task (Celery / Redis Queue)
- ה-Client יעשה Polling לתוצאה
- דוגמה:
  ```python
  # POST /api/code/format → מחזיר task_id
  # GET /api/code/format/{task_id} → מחזיר status/result
  ```

### 5. אבטחה (Security)

**קבצים זמניים:**
- השתמש ב-`tempfile.NamedTemporaryFile(delete=True)`
- ⚠️ **Windows**: לפעמים יש בעיות הרשאה לפתוח קובץ שוב כשהוא פתוח
- ✅ **Linux/Docker**: עובד חלק

**סביבה נקייה לכלים:**
```python
# מומלץ: מניעת קריאת קונפיגים גלובליים
env = os.environ.copy()
env['PYTHONIOENCODING'] = 'utf-8'  # פלט תמיד UTF-8
result = subprocess.run(..., env=env)
```

### 6. טיפול בקידוד (Encoding)

כשמריצים `subprocess.run`, תווים מוזרים בפלט יכולים לקרוס את ה-Service:

```python
# במקום:
result = subprocess.run(..., text=True)

# עדיף:
result = subprocess.run(..., capture_output=True)
stdout = result.stdout.decode('utf-8', errors='replace')
stderr = result.stderr.decode('utf-8', errors='replace')
```

---

## 🔗 קישורים רלוונטיים

- [מדריך המקור (Telegram)](https://github.com/amirbiron/CodeBot/blob/9a2a6f806a7c80cd48d5048dccc911d23f164ba2/FEATURE_SUGGESTIONS/IMPLEMENTATION_GUIDE_1.1_1.2.md)
- [JSON Formatter Guide](./JSON_FORMATTER_IMPLEMENTATION_GUIDE.md) - מדריך דומה
- [CodeBot Documentation](https://amirbiron.github.io/CodeBot/)
- [Black Documentation](https://black.readthedocs.io/)
- [flake8 Documentation](https://flake8.pycqa.org/)

---

**נוצר ב**: 2025-12-26  
**עודכן**: 2025-12-26 (v1.1 - שיפורי Production Readiness)  
**מבוסס על**: IMPLEMENTATION_GUIDE_1.1_1.2.md (2025-10-08)  
**מותאם ל**: WebApp (Flask)

---

## 📝 היסטוריית גרסאות

### v1.1 (2025-12-26) - Production Readiness
- ✅ הוספת `_get_clean_env()` עם PYTHONIOENCODING
- ✅ טיפול נכון ב-encoding עם `errors='replace'`
- ✅ שינוי Timeout מ-30 ל-10 שניות
- ✅ הוספת `--isolated` ל-flake8
- ✅ הערות על Blocking ו-Gunicorn workers
- ✅ המלצות לגרסה 2.0 (Celery, Ruff, MergeView)
- ✅ סעיף אבטחה מורחב

### v1.0 (2025-12-26) - Initial WebApp Adaptation
- התאמה מלאה מ-Telegram ל-WebApp
- Flask Blueprint API
- JavaScript integration

---

## 📝 סיכום שינויים מהמדריך המקורי

| נושא | מקור (Telegram) | יעד (WebApp) |
|------|-----------------|--------------|
| ממשק | Telegram Handlers | Flask Blueprint API |
| UI | הודעות + Inline Keyboard | HTML/CSS + CodeMirror |
| State | Telegram Context | JavaScript State |
| אינטראקציה | פקודות /format, /lint | כפתורים + קיצורי מקלדת |
| תצוגת Diff | הודעת טקסט | Modal עם syntax highlight |

**הפיצ'רים זהים**, רק הממשק שונה!
