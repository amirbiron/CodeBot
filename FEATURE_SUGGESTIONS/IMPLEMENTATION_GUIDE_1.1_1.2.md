# 📘 מדריך מימוש - עיצוב קוד אוטומטי ו-Linting מתקדם

> מדריך מפורט למימוש הצעות 1.1 ו-1.2 מתוך FEATURE_SUGGESTIONS2.md

---

## 📋 תוכן עניינים

1. [סקירה כללית](#סקירה-כללית)
2. [פיצ'ר 1.1 - עיצוב קוד אוטומטי](#פיצר-11---עיצוב-קוד-אוטומטי)
3. [פיצ'ר 1.2 - Linting מתקדם](#פיצר-12---linting-מתקדם)
4. [אינטגרציה עם המערכת הקיימת](#אינטגרציה-עם-המערכת-הקיימת)
5. [בדיקות ואבטחה](#בדיקות-ואבטחה)
6. [תכנית פריסה](#תכנית-פריסה)

---

## 🎯 סקירה כללית

### מטרות המימוש
- **פיצ'ר 1.1**: מתן יכולת עיצוב אוטומטי של קוד לפי תקנים מקובלים (Black, Prettier, autopep8, gofmt)
- **פיצ'ר 1.2**: בדיקת איכות קוד עמוקה עם זיהוי בעיות, באגים ו-code smells

### יתרונות למשתמש
- ✅ חיסכון זמן בעריכה ידנית
- ✅ קוד עקבי ונקי
- ✅ עמידה בתקני צוות
- ✅ זיהוי מוקדם של באגים ובעיות סגנון

### אומדן זמן פיתוח
- **פיצ'ר 1.1**: 1-2 שבועות (מורכבות בינונית)
- **פיצ'ר 1.2**: 1-2 שבועות (מורכבות בינונית)
- **סה"כ עם אינטגרציה**: 3-4 שבועות

---

## 🎨 פיצ'ר 1.1 - עיצוב קוד אוטומטי

### 1.1.1 דרישות טכניות

#### תלויות Python נדרשות
```python
# requirements.txt
black>=23.0.0           # Python formatter
autopep8>=2.0.0        # Python PEP8 formatter
yapf>=0.40.0           # Google's Python formatter
```

#### כלים חיצוניים (דרך subprocess)
```bash
# JavaScript/TypeScript
npm install -g prettier

# Go
go install golang.org/x/tools/cmd/gofmt@latest
```

### 1.1.2 ארכיטקטורה מוצעת

#### מבנה תיקיות
```
handlers/
├── code_formatting/
│   ├── __init__.py
│   ├── formatter_base.py      # Base class לכל formatters
│   ├── python_formatter.py    # Python-specific
│   ├── javascript_formatter.py # JS/TS-specific
│   ├── go_formatter.py        # Go-specific
│   └── formatter_factory.py   # Factory pattern
```

#### דיאגרמת זרימה
```
משתמש שולח קובץ
    ↓
זיהוי שפת תכנות (לפי סיומת)
    ↓
בחירת Formatter מתאים
    ↓
עיצוב הקוד
    ↓
השוואה לפני/אחרי
    ↓
אופציות שמירה למשתמש
```

### 1.1.3 מימוש - Base Formatter

```python
# handlers/code_formatting/formatter_base.py
from abc import ABC, abstractmethod
from typing import Dict, Optional, Tuple
from dataclasses import dataclass
import difflib

@dataclass
class FormattingResult:
    """תוצאת עיצוב קוד"""
    success: bool
    original_code: str
    formatted_code: str
    lines_changed: int
    error_message: Optional[str] = None
    
    def get_diff(self) -> str:
        """מחזיר diff מפורט"""
        diff = difflib.unified_diff(
            self.original_code.splitlines(keepends=True),
            self.formatted_code.splitlines(keepends=True),
            fromfile='לפני',
            tofile='אחרי',
            lineterm=''
        )
        return '\n'.join(diff)


class CodeFormatter(ABC):
    """Base class לכל formatters"""
    
    @abstractmethod
    def format(self, code: str, options: Dict = None) -> FormattingResult:
        """מעצב קוד ומחזיר תוצאה"""
        pass
    
    @abstractmethod
    def is_available(self) -> bool:
        """בודק אם ה-formatter זמין במערכת"""
        pass
    
    @abstractmethod
    def get_supported_extensions(self) -> list:
        """מחזיר רשימת סיומות נתמכות"""
        pass
    
    def count_changes(self, original: str, formatted: str) -> int:
        """סופר מספר שורות ששונו"""
        original_lines = original.splitlines()
        formatted_lines = formatted.splitlines()
        
        changes = 0
        for orig, fmt in zip(original_lines, formatted_lines):
            if orig != fmt:
                changes += 1
        
        # הוספה/מחיקה של שורות
        changes += abs(len(original_lines) - len(formatted_lines))
        
        return changes
```

### 1.1.4 מימוש - Python Formatter

```python
# handlers/code_formatting/python_formatter.py
import subprocess
import tempfile
import os
from pathlib import Path
from typing import Dict, Optional

from .formatter_base import CodeFormatter, FormattingResult


class PythonFormatter(CodeFormatter):
    """Formatter לקוד Python"""
    
    SUPPORTED_TOOLS = {
        'black': {
            'command': 'black',
            'args': ['--quiet', '-'],
            'default_line_length': 88
        },
        'autopep8': {
            'command': 'autopep8',
            'args': ['-'],
            'default_line_length': 79
        },
        'yapf': {
            'command': 'yapf',
            'args': [],
            'default_line_length': 80
        }
    }
    
    def __init__(self, tool: str = 'black'):
        if tool not in self.SUPPORTED_TOOLS:
            raise ValueError(f"כלי לא נתמך: {tool}")
        self.tool = tool
        self.tool_config = self.SUPPORTED_TOOLS[tool]
    
    def format(self, code: str, options: Dict = None) -> FormattingResult:
        """מעצב קוד Python"""
        options = options or {}
        
        try:
            # בניית פקודה
            cmd = [self.tool_config['command']] + self.tool_config['args']
            
            # הוספת line-length אם נדרש
            if 'line_length' in options:
                if self.tool == 'black':
                    cmd.extend(['--line-length', str(options['line_length'])])
                elif self.tool == 'autopep8':
                    cmd.extend(['--max-line-length', str(options['line_length'])])
            
            # הרצת הכלי
            result = subprocess.run(
                cmd,
                input=code,
                text=True,
                capture_output=True,
                timeout=30
            )
            
            if result.returncode != 0:
                return FormattingResult(
                    success=False,
                    original_code=code,
                    formatted_code=code,
                    lines_changed=0,
                    error_message=result.stderr
                )
            
            formatted_code = result.stdout
            lines_changed = self.count_changes(code, formatted_code)
            
            return FormattingResult(
                success=True,
                original_code=code,
                formatted_code=formatted_code,
                lines_changed=lines_changed
            )
            
        except subprocess.TimeoutExpired:
            return FormattingResult(
                success=False,
                original_code=code,
                formatted_code=code,
                lines_changed=0,
                error_message="תם הזמן לעיצוב הקוד"
            )
        except Exception as e:
            return FormattingResult(
                success=False,
                original_code=code,
                formatted_code=code,
                lines_changed=0,
                error_message=str(e)
            )
    
    def is_available(self) -> bool:
        """בודק אם הכלי זמין"""
        try:
            subprocess.run(
                [self.tool_config['command'], '--version'],
                capture_output=True,
                timeout=5
            )
            return True
        except:
            return False
    
    def get_supported_extensions(self) -> list:
        return ['.py', '.pyw']
```

### 1.1.5 מימוש - Formatter Factory

```python
# handlers/code_formatting/formatter_factory.py
from pathlib import Path
from typing import Optional

from .formatter_base import CodeFormatter
from .python_formatter import PythonFormatter
# from .javascript_formatter import JavaScriptFormatter
# from .go_formatter import GoFormatter


class FormatterFactory:
    """Factory ליצירת formatters לפי סוג קובץ"""
    
    EXTENSION_MAP = {
        '.py': ('python', PythonFormatter),
        '.pyw': ('python', PythonFormatter),
        # '.js': ('javascript', JavaScriptFormatter),
        # '.jsx': ('javascript', JavaScriptFormatter),
        # '.ts': ('javascript', JavaScriptFormatter),
        # '.tsx': ('javascript', JavaScriptFormatter),
        # '.go': ('go', GoFormatter),
    }
    
    @classmethod
    def get_formatter(cls, file_path: str, tool: Optional[str] = None) -> Optional[CodeFormatter]:
        """מחזיר formatter מתאים לפי סוג קובץ"""
        ext = Path(file_path).suffix.lower()
        
        if ext not in cls.EXTENSION_MAP:
            return None
        
        language, formatter_class = cls.EXTENSION_MAP[ext]
        
        # אם לא צוין כלי, משתמש בברירת המחדל
        if tool:
            return formatter_class(tool=tool)
        else:
            return formatter_class()
    
    @classmethod
    def get_supported_extensions(cls) -> list:
        """מחזיר רשימת כל הסיומות הנתמכות"""
        return list(cls.EXTENSION_MAP.keys())
```

### 1.1.6 אינטגרציה עם Telegram Bot

```python
# handlers/code_formatting/telegram_handler.py
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from telegram.constants import ParseMode

from .formatter_factory import FormatterFactory
from database.repository import CodeRepository

# States
WAITING_FILE, WAITING_ACTION = range(2)


async def format_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """נקודת כניסה לפקודת /format"""
    await update.message.reply_text(
        "🎨 *עיצוב קוד אוטומטי*\n\n"
        "שלח לי קובץ קוד ואעצב אותו בשבילך!\n\n"
        "סוגי קבצים נתמכים:\n"
        "• Python (.py)\n"
        "• JavaScript/TypeScript (.js, .ts)\n"
        "• Go (.go)\n\n"
        "או שלח /cancel לביטול",
        parse_mode=ParseMode.MARKDOWN
    )
    return WAITING_FILE


async def handle_file_for_formatting(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """מטפל בקובץ שנשלח לעיצוב"""
    # קבלת הקובץ
    if update.message.document:
        file = await update.message.document.get_file()
        file_name = update.message.document.file_name
    elif update.message.text:
        # אם שלח טקסט, נניח שזה קוד
        await update.message.reply_text("❌ אנא שלח קובץ, לא טקסט")
        return WAITING_FILE
    else:
        await update.message.reply_text("❌ פורמט לא נתמך")
        return WAITING_FILE
    
    # הורדת הקובץ
    content = await file.download_as_bytearray()
    code = content.decode('utf-8')
    
    # בחירת formatter
    formatter = FormatterFactory.get_formatter(file_name)
    
    if not formatter:
        await update.message.reply_text(
            f"❌ סוג קובץ לא נתמך: {file_name}\n"
            f"סוגים נתמכים: {', '.join(FormatterFactory.get_supported_extensions())}"
        )
        return WAITING_FILE
    
    # בדיקה שהכלי זמין
    if not formatter.is_available():
        await update.message.reply_text(
            "❌ כלי העיצוב אינו זמין כרגע. אנא נסה מאוחר יותר"
        )
        return ConversationHandler.END
    
    # עיצוב הקוד
    await update.message.reply_text("🎨 מעצב את הקוד...")
    result = formatter.format(code)
    
    if not result.success:
        await update.message.reply_text(
            f"❌ שגיאה בעיצוב:\n`{result.error_message}`",
            parse_mode=ParseMode.MARKDOWN
        )
        return ConversationHandler.END
    
    # שמירה בהקשר
    context.user_data['format_result'] = result
    context.user_data['original_filename'] = file_name
    
    # הצגת תוצאה
    message = (
        f"✅ *הקוד עוצב בהצלחה!*\n\n"
        f"📊 *סטטיסטיקות:*\n"
        f"• קובץ: `{file_name}`\n"
        f"• שורות ששונו: {result.lines_changed}\n"
        f"• גודל לפני: {len(result.original_code)} תווים\n"
        f"• גודל אחרי: {len(result.formatted_code)} תווים\n\n"
    )
    
    # כפתורי פעולה
    keyboard = [
        [
            InlineKeyboardButton("💾 שמור גרסה חדשה", callback_data="format_save_new"),
            InlineKeyboardButton("📝 החלף את המקור", callback_data="format_replace")
        ],
        [
            InlineKeyboardButton("👀 הצג diff", callback_data="format_show_diff"),
            InlineKeyboardButton("❌ בטל", callback_data="format_cancel")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        message,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup
    )
    
    return WAITING_ACTION


async def handle_format_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """מטפל בפעולה שנבחרה"""
    query = update.callback_query
    await query.answer()
    
    action = query.data
    result = context.user_data.get('format_result')
    filename = context.user_data.get('original_filename')
    
    if action == "format_save_new":
        # שמירה כקובץ חדש
        new_filename = f"formatted_{filename}"
        # כאן תוכל לשמור ב-DB או להעלות ל-GitHub
        await query.message.reply_document(
            document=result.formatted_code.encode('utf-8'),
            filename=new_filename,
            caption=f"✅ קובץ מעוצב: {new_filename}"
        )
        
    elif action == "format_replace":
        # החלפת הקובץ המקורי
        # כאן צריך לממש החלפה ב-GitHub או במערכת קבצים
        await query.message.reply_text(
            "✅ הקובץ המקורי הוחלף בגרסה המעוצבת"
        )
        
    elif action == "format_show_diff":
        # הצגת diff
        diff = result.get_diff()
        if len(diff) > 4000:
            diff = diff[:4000] + "\n... (קוצר)"
        await query.message.reply_text(
            f"```diff\n{diff}\n```",
            parse_mode=ParseMode.MARKDOWN
        )
        return WAITING_ACTION  # חזרה לאפשרויות
        
    elif action == "format_cancel":
        await query.message.reply_text("❌ פעולה בוטלה")
    
    # ניקוי
    context.user_data.pop('format_result', None)
    context.user_data.pop('original_filename', None)
    
    return ConversationHandler.END


# הגדרת ה-ConversationHandler
format_handler = ConversationHandler(
    entry_points=[CommandHandler('format', format_command)],
    states={
        WAITING_FILE: [
            MessageHandler(filters.Document.ALL, handle_file_for_formatting)
        ],
        WAITING_ACTION: [
            CallbackQueryHandler(handle_format_action, pattern='^format_')
        ]
    },
    fallbacks=[CommandHandler('cancel', lambda u, c: ConversationHandler.END)]
)
```

---

## ✨ פיצ'ר 1.2 - Linting מתקדם

### 1.2.1 דרישות טכניות

#### תלויות Python
```python
# requirements.txt
pylint>=3.0.0          # Python linter
flake8>=6.0.0          # Style guide checker
mypy>=1.0.0            # Type checker
radon>=6.0.0           # Complexity analyzer
bandit>=1.7.0          # Security checker
```

#### כלים חיצוניים
```bash
# JavaScript/TypeScript
npm install -g eslint
npm install -g tslint

# Go
go install golang.org/x/lint/golint@latest
```

### 1.2.2 ארכיטקטורה

#### מבנה תיקיות
```
handlers/
├── code_linting/
│   ├── __init__.py
│   ├── linter_base.py         # Base class
│   ├── python_linter.py       # Python linters
│   ├── javascript_linter.py   # JS/TS linters
│   ├── security_checker.py    # בדיקות אבטחה
│   └── linter_factory.py      # Factory
```

### 1.2.3 מימוש - Base Linter

```python
# handlers/code_linting/linter_base.py
from abc import ABC, abstractmethod
from typing import List, Dict, Optional
from dataclasses import dataclass
from enum import Enum


class IssueSeverity(Enum):
    """רמת חומרה של בעיה"""
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"
    STYLE = "style"


@dataclass
class LintIssue:
    """בעיה שנמצאה ב-lint"""
    line: int
    column: int
    severity: IssueSeverity
    code: str  # קוד הבעיה (למשל E501)
    message: str
    rule: str  # שם הכלל שהופר
    suggestion: Optional[str] = None  # הצעה לתיקון


@dataclass
class LintResult:
    """תוצאת lint"""
    success: bool
    file_path: str
    issues: List[LintIssue]
    score: float  # 0-10
    total_lines: int
    errors_count: int = 0
    warnings_count: int = 0
    info_count: int = 0
    style_count: int = 0
    
    def __post_init__(self):
        """חישוב סטטיסטיקות"""
        for issue in self.issues:
            if issue.severity == IssueSeverity.ERROR:
                self.errors_count += 1
            elif issue.severity == IssueSeverity.WARNING:
                self.warnings_count += 1
            elif issue.severity == IssueSeverity.INFO:
                self.info_count += 1
            elif issue.severity == IssueSeverity.STYLE:
                self.style_count += 1
    
    def get_summary(self) -> str:
        """מחזיר סיכום טקסטואלי"""
        emoji_map = {
            'errors': '🔴',
            'warnings': '🟡',
            'info': '💙',
            'style': '🎨'
        }
        
        summary = f"📊 *ציון כללי:* {self.score:.1f}/10\n"
        summary += f"📝 *סך שורות:* {self.total_lines}\n\n"
        
        if self.errors_count:
            summary += f"{emoji_map['errors']} *שגיאות:* {self.errors_count}\n"
        if self.warnings_count:
            summary += f"{emoji_map['warnings']} *אזהרות:* {self.warnings_count}\n"
        if self.info_count:
            summary += f"{emoji_map['info']} *מידע:* {self.info_count}\n"
        if self.style_count:
            summary += f"{emoji_map['style']} *סגנון:* {self.style_count}\n"
        
        return summary


class CodeLinter(ABC):
    """Base class לכל linters"""
    
    @abstractmethod
    def lint(self, code: str, file_path: str) -> LintResult:
        """מבצע lint על הקוד"""
        pass
    
    @abstractmethod
    def is_available(self) -> bool:
        """בודק זמינות"""
        pass
    
    @abstractmethod
    def get_supported_extensions(self) -> list:
        """מחזיר סיומות נתמכות"""
        pass
    
    def calculate_score(self, issues: List[LintIssue], total_lines: int) -> float:
        """מחשב ציון איכות (0-10)"""
        if total_lines == 0:
            return 10.0
        
        # משקלים לכל סוג בעיה
        weights = {
            IssueSeverity.ERROR: -1.0,
            IssueSeverity.WARNING: -0.3,
            IssueSeverity.INFO: -0.1,
            IssueSeverity.STYLE: -0.05
        }
        
        penalty = sum(weights.get(issue.severity, 0) for issue in issues)
        
        # נרמול לפי מספר שורות
        normalized_penalty = (penalty / total_lines) * 100
        
        score = max(0, min(10, 10 + normalized_penalty))
        return round(score, 1)
```

### 1.2.4 מימוש - Python Linter

```python
# handlers/code_linting/python_linter.py
import subprocess
import tempfile
import json
import re
from pathlib import Path
from typing import List

from .linter_base import CodeLinter, LintResult, LintIssue, IssueSeverity


class PythonLinter(CodeLinter):
    """Linter לקוד Python"""
    
    def __init__(self, tool: str = 'pylint'):
        self.tool = tool
        self.tool_configs = {
            'pylint': self._run_pylint,
            'flake8': self._run_flake8,
            'mypy': self._run_mypy
        }
    
    def lint(self, code: str, file_path: str) -> LintResult:
        """מבצע lint"""
        if self.tool not in self.tool_configs:
            raise ValueError(f"כלי לא נתמך: {self.tool}")
        
        # יצירת קובץ זמני
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(code)
            temp_path = f.name
        
        try:
            # הרצת הכלי
            issues = self.tool_configs[self.tool](temp_path, code)
            
            # חישוב ציון
            total_lines = len(code.splitlines())
            score = self.calculate_score(issues, total_lines)
            
            return LintResult(
                success=True,
                file_path=file_path,
                issues=issues,
                score=score,
                total_lines=total_lines
            )
        finally:
            Path(temp_path).unlink(missing_ok=True)
    
    def _run_pylint(self, file_path: str, code: str) -> List[LintIssue]:
        """הרצת pylint"""
        try:
            result = subprocess.run(
                ['pylint', '--output-format=json', file_path],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            issues = []
            if result.stdout:
                data = json.loads(result.stdout)
                for item in data:
                    severity = self._map_pylint_severity(item.get('type', 'info'))
                    issues.append(LintIssue(
                        line=item.get('line', 0),
                        column=item.get('column', 0),
                        severity=severity,
                        code=item.get('message-id', ''),
                        message=item.get('message', ''),
                        rule=item.get('symbol', '')
                    ))
            
            return issues
        except Exception as e:
            return []
    
    def _run_flake8(self, file_path: str, code: str) -> List[LintIssue]:
        """הרצת flake8"""
        try:
            result = subprocess.run(
                ['flake8', '--format=%(row)d:%(col)d: %(code)s %(text)s', file_path],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            issues = []
            for line in result.stdout.splitlines():
                match = re.match(r'(\d+):(\d+): ([A-Z]\d+) (.+)', line)
                if match:
                    line_num, col, code, message = match.groups()
                    severity = self._map_flake8_severity(code[0])
                    issues.append(LintIssue(
                        line=int(line_num),
                        column=int(col),
                        severity=severity,
                        code=code,
                        message=message,
                        rule=code
                    ))
            
            return issues
        except Exception:
            return []
    
    def _run_mypy(self, file_path: str, code: str) -> List[LintIssue]:
        """הרצת mypy"""
        try:
            result = subprocess.run(
                ['mypy', '--show-column-numbers', file_path],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            issues = []
            for line in result.stdout.splitlines():
                # פורמט: file.py:10:5: error: message
                match = re.match(r'.+:(\d+):(\d+): (error|warning|note): (.+)', line)
                if match:
                    line_num, col, severity_str, message = match.groups()
                    severity = IssueSeverity.ERROR if severity_str == 'error' else IssueSeverity.WARNING
                    issues.append(LintIssue(
                        line=int(line_num),
                        column=int(col),
                        severity=severity,
                        code='type-check',
                        message=message,
                        rule='mypy'
                    ))
            
            return issues
        except Exception:
            return []
    
    def _map_pylint_severity(self, pylint_type: str) -> IssueSeverity:
        """מיפוי סוגי pylint לרמות חומרה"""
        mapping = {
            'error': IssueSeverity.ERROR,
            'warning': IssueSeverity.WARNING,
            'convention': IssueSeverity.STYLE,
            'refactor': IssueSeverity.INFO
        }
        return mapping.get(pylint_type.lower(), IssueSeverity.INFO)
    
    def _map_flake8_severity(self, code_prefix: str) -> IssueSeverity:
        """מיפוי קודי flake8"""
        if code_prefix == 'E':  # Errors
            return IssueSeverity.ERROR
        elif code_prefix == 'W':  # Warnings
            return IssueSeverity.WARNING
        else:
            return IssueSeverity.STYLE
    
    def is_available(self) -> bool:
        """בדיקת זמינות"""
        try:
            subprocess.run(
                [self.tool, '--version'],
                capture_output=True,
                timeout=5
            )
            return True
        except:
            return False
    
    def get_supported_extensions(self) -> list:
        return ['.py', '.pyw']
```

### 1.2.5 אינטגרציה עם Telegram Bot

```python
# handlers/code_linting/telegram_handler.py
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from telegram.constants import ParseMode

from .linter_factory import LinterFactory
from .linter_base import IssueSeverity

WAITING_FILE_LINT, WAITING_LINT_ACTION = range(2)


async def lint_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """פקודת /lint"""
    await update.message.reply_text(
        "🔍 *בדיקת איכות קוד*\n\n"
        "שלח לי קובץ קוד ואבדוק את האיכות!\n\n"
        "אני בודק:\n"
        "• 🔴 שגיאות תחביר ולוגיקה\n"
        "• 🟡 אזהרות וcode smells\n"
        "• 💙 הצעות שיפור\n"
        "• 🎨 בעיות סגנון\n\n"
        "סוגי קבצים: Python, JavaScript, Go\n"
        "או /cancel לביטול",
        parse_mode=ParseMode.MARKDOWN
    )
    return WAITING_FILE_LINT


async def handle_file_for_linting(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """קבלת קובץ ל-lint"""
    if not update.message.document:
        await update.message.reply_text("❌ אנא שלח קובץ")
        return WAITING_FILE_LINT
    
    # הורדת קובץ
    file = await update.message.document.get_file()
    file_name = update.message.document.file_name
    content = await file.download_as_bytearray()
    code = content.decode('utf-8')
    
    # בחירת linter
    linter = LinterFactory.get_linter(file_name)
    
    if not linter:
        await update.message.reply_text(
            f"❌ סוג קובץ לא נתמך: {file_name}"
        )
        return WAITING_FILE_LINT
    
    if not linter.is_available():
        await update.message.reply_text(
            "❌ כלי הבדיקה אינו זמין כרגע"
        )
        return ConversationHandler.END
    
    # הרצת lint
    await update.message.reply_text("🔍 בודק את הקוד...")
    result = linter.lint(code, file_name)
    
    # שמירה בהקשר
    context.user_data['lint_result'] = result
    
    # הכנת הודעה
    summary = result.get_summary()
    
    # פירוט בעיות (עד 10 הראשונות)
    issues_text = ""
    for idx, issue in enumerate(result.issues[:10], 1):
        emoji = {
            IssueSeverity.ERROR: '🔴',
            IssueSeverity.WARNING: '🟡',
            IssueSeverity.INFO: '💙',
            IssueSeverity.STYLE: '🎨'
        }.get(issue.severity, '•')
        
        issues_text += (
            f"\n{emoji} שורה {issue.line}: {issue.message[:50]}"
            + ("..." if len(issue.message) > 50 else "")
        )
    
    if len(result.issues) > 10:
        issues_text += f"\n\n... ועוד {len(result.issues) - 10} בעיות"
    
    message = (
        f"✅ *בדיקה הושלמה!*\n\n"
        f"{summary}\n"
        f"{issues_text if issues_text else '✨ לא נמצאו בעיות!'}"
    )
    
    # כפתורי פעולה
    keyboard = []
    if result.issues:
        keyboard.append([
            InlineKeyboardButton("🔧 תקן אוטומטית", callback_data="lint_auto_fix"),
            InlineKeyboardButton("📄 דוח מלא", callback_data="lint_full_report")
        ])
    keyboard.append([
        InlineKeyboardButton("❌ סגור", callback_data="lint_close")
    ])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        message,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup
    )
    
    return WAITING_LINT_ACTION


async def handle_lint_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """טיפול בפעולה שנבחרה"""
    query = update.callback_query
    await query.answer()
    
    action = query.data
    result = context.user_data.get('lint_result')
    
    if action == "lint_auto_fix":
        # תיקון אוטומטי (אם יש תמיכה)
        await query.message.reply_text(
            "🔧 תיקון אוטומטי יתווסף בגרסה הבאה"
        )
    
    elif action == "lint_full_report":
        # דוח מלא
        report = f"📄 *דוח מלא - {result.file_path}*\n\n"
        
        # קיבוץ לפי חומרה
        by_severity = {}
        for issue in result.issues:
            if issue.severity not in by_severity:
                by_severity[issue.severity] = []
            by_severity[issue.severity].append(issue)
        
        for severity in [IssueSeverity.ERROR, IssueSeverity.WARNING, IssueSeverity.INFO, IssueSeverity.STYLE]:
            if severity in by_severity:
                emoji = {
                    IssueSeverity.ERROR: '🔴',
                    IssueSeverity.WARNING: '🟡',
                    IssueSeverity.INFO: '💙',
                    IssueSeverity.STYLE: '🎨'
                }[severity]
                
                report += f"\n{emoji} *{severity.value.title()}:*\n"
                for issue in by_severity[severity][:5]:  # 5 לכל סוג
                    report += f"• שורה {issue.line}: {issue.message}\n"
        
        await query.message.reply_text(report, parse_mode=ParseMode.MARKDOWN)
    
    elif action == "lint_close":
        await query.message.delete()
    
    context.user_data.pop('lint_result', None)
    return ConversationHandler.END


# ConversationHandler
lint_handler = ConversationHandler(
    entry_points=[CommandHandler('lint', lint_command)],
    states={
        WAITING_FILE_LINT: [
            MessageHandler(filters.Document.ALL, handle_file_for_linting)
        ],
        WAITING_LINT_ACTION: [
            CallbackQueryHandler(handle_lint_action, pattern='^lint_')
        ]
    },
    fallbacks=[CommandHandler('cancel', lambda u, c: ConversationHandler.END)]
)
```

---

## 🔗 אינטגרציה עם המערכת הקיימת

### 4.1 רישום ה-Handlers ב-main.py

```python
# main.py
from handlers.code_formatting.telegram_handler import format_handler
from handlers.code_linting.telegram_handler import lint_handler

def main():
    application = Application.builder().token(BOT_TOKEN).build()
    
    # ... handlers קיימים ...
    
    # הוספת handlers חדשים
    application.add_handler(format_handler)
    application.add_handler(lint_handler)
    
    # ... המשך ...
```

### 4.2 הוספת תפריטים

```python
# bot_handlers.py או קובץ תפריטים ייעודי
async def code_tools_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """תפריט כלי קוד"""
    keyboard = [
        [
            InlineKeyboardButton("🎨 עיצוב קוד", callback_data="tool_format"),
            InlineKeyboardButton("🔍 בדיקת איכות", callback_data="tool_lint")
        ],
        [
            InlineKeyboardButton("📊 ניתוח מורכבות", callback_data="tool_complexity"),
            InlineKeyboardButton("🔐 בדיקת אבטחה", callback_data="tool_security")
        ],
        [InlineKeyboardButton("↩️ חזור", callback_data="main_menu")]
    ]
    
    await update.message.reply_text(
        "🛠️ *כלי עיבוד קוד*\n\nבחר כלי:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )
```

### 4.3 שמירת תוצאות ב-Database

```python
# database/models.py
from sqlalchemy import Column, Integer, String, Float, JSON, DateTime
from datetime import datetime

class CodeAnalysis(Base):
    """טבלה לשמירת תוצאות ניתוח קוד"""
    __tablename__ = 'code_analyses'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=False)
    file_name = Column(String, nullable=False)
    analysis_type = Column(String)  # 'format' או 'lint'
    score = Column(Float)
    issues_count = Column(Integer)
    result_data = Column(JSON)  # תוצאה מלאה ב-JSON
    created_at = Column(DateTime, default=datetime.utcnow)


# database/repository.py
class CodeAnalysisRepository:
    """ניהול ניתוחי קוד"""
    
    @staticmethod
    async def save_analysis(
        user_id: int,
        file_name: str,
        analysis_type: str,
        score: float,
        issues_count: int,
        result_data: dict
    ):
        """שמירת תוצאת ניתוח"""
        session = get_session()
        analysis = CodeAnalysis(
            user_id=user_id,
            file_name=file_name,
            analysis_type=analysis_type,
            score=score,
            issues_count=issues_count,
            result_data=result_data
        )
        session.add(analysis)
        session.commit()
        return analysis.id
    
    @staticmethod
    async def get_user_analyses(user_id: int, limit: int = 10):
        """קבלת היסטוריית ניתוחים של משתמש"""
        session = get_session()
        return session.query(CodeAnalysis)\
            .filter_by(user_id=user_id)\
            .order_by(CodeAnalysis.created_at.desc())\
            .limit(limit)\
            .all()
```

---

## 🧪 בדיקות ואבטחה

### 5.1 Unit Tests

```python
# tests/test_formatters.py
import pytest
from handlers.code_formatting.python_formatter import PythonFormatter

def test_python_formatter_basic():
    """בדיקת עיצוב בסיסי"""
    formatter = PythonFormatter(tool='black')
    
    messy_code = """
def hello(  name,age  ):
    print( "hi "+name )
"""
    
    result = formatter.format(messy_code)
    
    assert result.success
    assert result.lines_changed > 0
    assert 'def hello(name, age):' in result.formatted_code


def test_python_formatter_with_options():
    """בדיקת אופציות"""
    formatter = PythonFormatter(tool='black')
    
    code = "x = 1"
    result = formatter.format(code, {'line_length': 80})
    
    assert result.success


# tests/test_linters.py
import pytest
from handlers.code_linting.python_linter import PythonLinter

def test_python_linter_finds_issues():
    """בדיקה שה-linter מוצא בעיות"""
    linter = PythonLinter(tool='flake8')
    
    bad_code = """
import sys
def bad_function():
    x=1+2
    unused_var = 5
"""
    
    result = linter.lint(bad_code, 'test.py')
    
    assert result.success
    assert len(result.issues) > 0
    assert result.score < 10  # יש בעיות


def test_python_linter_clean_code():
    """בדיקת קוד נקי"""
    linter = PythonLinter(tool='flake8')
    
    clean_code = """
def hello(name: str) -> None:
    print(f"Hello, {name}")
"""
    
    result = linter.lint(clean_code, 'test.py')
    
    assert result.success
    assert len(result.issues) == 0
    assert result.score == 10.0
```

### 5.2 בדיקות אבטחה

```python
# handlers/code_formatting/security.py
import re
from typing import List

class CodeSecurityChecker:
    """בדיקות אבטחה בסיסיות"""
    
    DANGEROUS_PATTERNS = [
        (r'eval\s*\(', 'שימוש מסוכן ב-eval()'),
        (r'exec\s*\(', 'שימוש מסוכן ב-exec()'),
        (r'__import__\s*\(', 'import דינמי'),
        (r'subprocess\..*shell=True', 'shell injection risk'),
        (r'os\.system\s*\(', 'שימוש מסוכן ב-os.system()'),
    ]
    
    @classmethod
    def check_code_safety(cls, code: str) -> List[str]:
        """בודק בעיות אבטחה בקוד"""
        warnings = []
        
        for pattern, message in cls.DANGEROUS_PATTERNS:
            if re.search(pattern, code):
                warnings.append(f"⚠️ {message}")
        
        return warnings


# שימוש ב-formatter handler
async def handle_file_for_formatting(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... קוד קיים ...
    
    # בדיקת אבטחה
    security_warnings = CodeSecurityChecker.check_code_safety(code)
    if security_warnings:
        warning_text = "\n".join(security_warnings)
        await update.message.reply_text(
            f"⚠️ *אזהרות אבטחה:*\n{warning_text}\n\nהאם להמשיך?",
            parse_mode=ParseMode.MARKDOWN
        )
    
    # ... המשך עיצוב ...
```

### 5.3 הגבלות משאבים

```python
# handlers/code_formatting/resource_limits.py
import resource
import signal
from contextlib import contextmanager

class ResourceLimits:
    """הגבלת משאבים לפעולות מסוכנות"""
    
    MAX_FILE_SIZE = 1024 * 1024  # 1MB
    MAX_EXECUTION_TIME = 30  # שניות
    MAX_MEMORY = 100 * 1024 * 1024  # 100MB
    
    @staticmethod
    def timeout_handler(signum, frame):
        raise TimeoutError("פעולה ארכה מדי")
    
    @classmethod
    @contextmanager
    def limited_execution(cls):
        """הקשר עם הגבלות"""
        # הגבלת זמן
        signal.signal(signal.SIGALRM, cls.timeout_handler)
        signal.alarm(cls.MAX_EXECUTION_TIME)
        
        # הגבלת זיכרון (Linux only)
        try:
            resource.setrlimit(
                resource.RLIMIT_AS,
                (cls.MAX_MEMORY, cls.MAX_MEMORY)
            )
        except:
            pass
        
        try:
            yield
        finally:
            signal.alarm(0)  # ביטול timeout
    
    @classmethod
    def check_file_size(cls, content: bytes) -> bool:
        """בדיקת גודל קובץ"""
        return len(content) <= cls.MAX_FILE_SIZE


# שימוש
async def handle_file_for_formatting(update: Update, context: ContextTypes.DEFAULT_TYPE):
    content = await file.download_as_bytearray()
    
    if not ResourceLimits.check_file_size(content):
        await update.message.reply_text("❌ קובץ גדול מדי (מקסימום 1MB)")
        return
    
    try:
        with ResourceLimits.limited_execution():
            result = formatter.format(code)
    except TimeoutError:
        await update.message.reply_text("❌ הפעולה ארכה מדי")
        return
```

---

## 📅 תכנית פריסה

### שלב 1: פיתוח (שבועות 1-2)
- [x] תכנון ארכיטקטורה
- [ ] מימוש Base Classes
- [ ] מימוש Python Formatter
- [ ] מימוש Python Linter
- [ ] בדיקות יחידה

### שלב 2: אינטגרציה (שבוע 3)
- [ ] אינטגרציה עם Telegram Bot
- [ ] הוספת תפריטים
- [ ] אינטגרציה עם Database
- [ ] בדיקות אינטגרציה

### שלב 3: הרחבה (שבוע 4)
- [ ] תמיכה ב-JavaScript/TypeScript
- [ ] תמיכה ב-Go
- [ ] בדיקות אבטחה
- [ ] אופטימיזציה

### שלב 4: פריסה (שבוע 5)
- [ ] בדיקות E2E
- [ ] תיעוד משתמש
- [ ] פריסה לסביבת ייצור
- [ ] מעקב ומוניטורינג

---

## 📊 מטריקות הצלחה

### KPIs
- [ ] **שימוש**: 50+ פעולות עיצוב ביום
- [ ] **שביעות רצון**: 80%+ דירוג חיובי
- [ ] **ביצועים**: <5 שניות לעיצוב קובץ ממוצע
- [ ] **אמינות**: 99% הצלחה בפעולות

### מעקב
```python
# services/analytics.py
class CodeToolsAnalytics:
    """מעקב אחר שימוש בכלים"""
    
    @staticmethod
    async def track_format_usage(user_id: int, file_type: str, success: bool):
        # שמירה ב-DB או analytics service
        pass
    
    @staticmethod
    async def track_lint_usage(user_id: int, score: float):
        pass
    
    @staticmethod
    async def get_usage_stats(days: int = 30):
        """סטטיסטיקות שימוש"""
        return {
            'total_formats': 1234,
            'total_lints': 567,
            'avg_score': 8.2,
            'top_languages': ['python', 'javascript']
        }
```

---

## 🚀 הרחבות עתידיות

### גרסה 2.0
- [ ] תיקון אוטומטי של בעיות lint
- [ ] המלצות AI לשיפור קוד
- [ ] תמיכה בשפות נוספות (Rust, Ruby, PHP)
- [ ] אינטגרציה עם CI/CD

### גרסה 3.0
- [ ] Real-time formatting בעריכה
- [ ] Code review אוטומטי
- [ ] תבניות קוד מותאמות אישית
- [ ] למידה מהרגלי המשתמש

---

## 📝 סיכום

מסמך זה מספק מדריך מקיף למימוש פיצ'רים 1.1 ו-1.2:

✅ **הושלם**:
- ארכיטקטורה מפורטת
- קוד לדוגמה מלא
- אינטגרציה עם הבוט
- בדיקות אבטחה
- תכנית פריסה

🔧 **לביצוע**:
1. התקנת תלויות
2. מימוש הקוד לפי הדוגמאות
3. בדיקות יסודיות
4. פריסה מדורגת

📞 **צור קשר**:
לשאלות או הבהרות נוספות, פנה לצוות הפיתוח.

---

**נוצר ב**: 2025-10-08  
**גרסה**: 1.0  
**מחבר**: CodeBot Team

**בהצלחה עם המימוש! 🚀**
