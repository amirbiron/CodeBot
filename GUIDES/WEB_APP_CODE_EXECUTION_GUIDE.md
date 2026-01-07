# מדריך מימוש הרצת קוד בווב אפ

> **מטרה:** הוספת יכולת להריץ קוד Python בצורה בטוחה מתוך ממשק ה-Webapp  
> **דרישות קדם:** שירות Code Tools קיים (`code_tools_api.py`), Docker בסביבת Production

---

## סקירה כללית

### מה הפיצ'ר עושה?

Code Execution מאפשר למשתמשים להריץ קטעי קוד Python ישירות מהדפדפן ולראות את הפלט:

| פונקציונליות | תיאור |
|--------------|-------|
| **הרצת קוד** | ביצוע קוד Python בסביבה מבודדת |
| **פלט בזמן אמת** | הצגת stdout/stderr |
| **הגבלות אבטחה** | Sandbox עם timeout ומגבלות משאבים |
| **היסטוריה** | שמירת הרצות אחרונות (אופציונלי) |

### למה זה שימושי?

- **למידה**: לבדוק snippets מספריית הקוד
- **דיבאג**: לבדוק קטעי קוד לפני שמירה
- **Playground**: סביבת ניסויים מהירה
- **Code Tools**: משלים את הפיצ'ר הקיים של עיצוב ו-lint

### סיכוני אבטחה ⚠️

הרצת קוד משתמש בשרת היא **פעולה מסוכנת**. המדריך כולל שכבות הגנה:

1. **Docker Sandbox** – הרצה בקונטיינר מבודד
2. **Timeout** – מגבלת זמן ריצה (5-30 שניות)
3. **Resource Limits** – הגבלת CPU/Memory
4. **Network Isolation** – ללא גישה לרשת
5. **Read-only Filesystem** – אין אפשרות לכתוב לדיסק
6. **Admin Only** – ברירת מחדל: רק אדמינים (אפשר להרחיב)

---

## ארכיטקטורה

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Browser (Webapp)                             │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │  code_tools.html / view_file.html / edit_file.html          │    │
│  │  ┌─────────────────┐  ┌───────────────────────────────────┐ │    │
│  │  │  קוד מקור       │  │  ▶ Run   📋 Copy   ✨ Format      │ │    │
│  │  │  (CodeMirror)   │  └───────────────────────────────────┘ │    │
│  │  │                 │                                        │    │
│  │  │  print("Hello") │  ┌───────────────────────────────────┐ │    │
│  │  │                 │  │  Output:                          │ │    │
│  │  │                 │  │  Hello                            │ │    │
│  │  └─────────────────┘  └───────────────────────────────────┘ │    │
│  └─────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼ POST /api/code/run
┌─────────────────────────────────────────────────────────────────────┐
│                      Flask Blueprint (code_tools_api.py)             │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │ @code_tools_bp.route("/run", methods=["POST"])              │    │
│  │   ├─ בדיקת הרשאות (Admin / Feature Flag)                    │    │
│  │   ├─ Validation (גודל, תווים אסורים)                        │    │
│  │   └─ קריאה ל-CodeExecutionService                          │    │
│  └─────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    CodeExecutionService                              │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │ execute(code, timeout, memory_limit)                        │    │
│  │   ├─ Pre-flight checks (blocked keywords)                   │    │
│  │   ├─ Docker run (isolated container)                        │    │
│  │   └─ Return stdout/stderr/exit_code                         │    │
│  └─────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    Docker Sandbox Container                          │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │ python:3.11-slim (read-only, no network, resource limits)   │    │
│  │   └─ python -c "<user_code>"                                │    │
│  └─────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 1. Service Layer – `CodeExecutionService`

### קובץ: `services/code_execution_service.py`

```python
"""
Code Execution Service
======================
שירות להרצת קוד Python בסביבה מבודדת (Docker Sandbox).

⚠️ אזהרת אבטחה: שירות זה מאפשר הרצת קוד שרירותי.
   יש להפעיל רק עם הגנות מתאימות (Docker, Resource Limits, Admin-only).
"""

from __future__ import annotations

import logging
import subprocess
import tempfile
import time
import os
import re
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class ExecutionResult:
    """תוצאת הרצת קוד."""
    
    success: bool
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    execution_time_ms: int = 0
    error_message: Optional[str] = None
    truncated: bool = False  # האם הפלט קוצץ
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "exit_code": self.exit_code,
            "execution_time_ms": self.execution_time_ms,
            "error_message": self.error_message,
            "truncated": self.truncated,
        }


class CodeExecutionService:
    """
    שירות להרצת קוד Python בסביבה מבודדת.
    
    אסטרטגיות הרצה:
    1. Docker (מומלץ לפרודקשן) - בידוד מלא
    2. subprocess (לפיתוח בלבד) - פחות בטוח
    
    שימוש:
        service = CodeExecutionService()
        result = service.execute("print('Hello')")
        print(result.stdout)  # Hello
    """
    
    # ============== הגדרות ברירת מחדל ==============
    
    # Timeout בשניות
    DEFAULT_TIMEOUT: int = 5
    MAX_TIMEOUT: int = 30
    
    # הגבלות משאבים
    MAX_MEMORY_MB: int = 128
    MAX_OUTPUT_BYTES: int = 100 * 1024  # 100KB
    MAX_CODE_LENGTH: int = 50 * 1024     # 50KB
    
    # Docker image להרצה
    DOCKER_IMAGE: str = "python:3.11-slim"
    
    # מילות מפתח חסומות (אבטחה בסיסית - לא מספיקה לבד!)
    BLOCKED_KEYWORDS: tuple[str, ...] = (
        "import os",
        "import subprocess",
        "import sys",
        "__import__",
        "eval(",
        "exec(",
        "compile(",
        "open(",
        "file(",
        "input(",
        "raw_input(",
        "getattr(",
        "setattr(",
        "delattr(",
        "globals(",
        "locals(",
        "vars(",
        "dir(",
        "__builtins__",
        "__class__",
        "__bases__",
        "__subclasses__",
        "__mro__",
        "__code__",
        "breakpoint(",
        "exit(",
        "quit(",
    )
    
    # מודולים מותרים (whitelist לסביבות פחות מגבילות)
    ALLOWED_IMPORTS: tuple[str, ...] = (
        "math",
        "random",
        "datetime",
        "json",
        "re",
        "collections",
        "itertools",
        "functools",
        "operator",
        "string",
        "textwrap",
        "typing",
        "dataclasses",
        "enum",
        "decimal",
        "fractions",
        "statistics",
        "copy",
        "pprint",
        "bisect",
        "heapq",
        "array",
    )
    
    def __init__(self, use_docker: bool = True):
        """
        אתחול השירות.
        
        Args:
            use_docker: האם להשתמש ב-Docker (מומלץ).
                        False רק לסביבת פיתוח מקומית!
        """
        self._use_docker = use_docker
        self._docker_available = self._check_docker()
        
        if use_docker and not self._docker_available:
            logger.warning(
                "Docker not available, falling back to subprocess. "
                "This is UNSAFE for production!"
            )
    
    def _check_docker(self) -> bool:
        """בדיקה האם Docker זמין."""
        try:
            result = subprocess.run(
                ["docker", "version"],
                capture_output=True,
                timeout=5,
            )
            return result.returncode == 0
        except (subprocess.SubprocessError, FileNotFoundError):
            return False
    
    def is_docker_available(self) -> bool:
        """האם Docker זמין להרצה."""
        return self._docker_available
    
    # ============== Validation ==============
    
    def validate_code(self, code: str) -> tuple[bool, Optional[str]]:
        """
        בדיקת תקינות קוד לפני הרצה.
        
        Returns:
            (is_valid, error_message)
        """
        if not code or not code.strip():
            return False, "הקוד ריק"
        
        # בדיקת אורך
        if len(code) > self.MAX_CODE_LENGTH:
            return False, f"הקוד ארוך מדי (מקסימום {self.MAX_CODE_LENGTH // 1024}KB)"
        
        # בדיקת קידוד
        try:
            code.encode("utf-8")
        except UnicodeEncodeError:
            return False, "קידוד תווים לא תקין"
        
        # בדיקת מילות מפתח חסומות
        code_lower = code.lower()
        for keyword in self.BLOCKED_KEYWORDS:
            if keyword.lower() in code_lower:
                return False, f"הקוד מכיל פעולה לא מורשית: {keyword}"
        
        return True, None
    
    def _sanitize_output(self, output: str) -> str:
        """ניקוי וקיצוץ פלט."""
        if not output:
            return ""
        
        # המרה ל-UTF-8 בטוח
        try:
            output = output.encode("utf-8", errors="replace").decode("utf-8")
        except Exception:
            output = str(output)
        
        # קיצוץ אם ארוך מדי
        if len(output) > self.MAX_OUTPUT_BYTES:
            output = output[:self.MAX_OUTPUT_BYTES] + "\n... (הפלט קוצץ)"
        
        return output
    
    # ============== Execution ==============
    
    def execute(
        self,
        code: str,
        timeout: int = DEFAULT_TIMEOUT,
        memory_limit_mb: int = MAX_MEMORY_MB,
    ) -> ExecutionResult:
        """
        הרצת קוד Python.
        
        Args:
            code: קוד Python להרצה
            timeout: מגבלת זמן בשניות
            memory_limit_mb: מגבלת זיכרון ב-MB
        
        Returns:
            ExecutionResult עם stdout/stderr/exit_code
        """
        # Validation
        is_valid, error = self.validate_code(code)
        if not is_valid:
            return ExecutionResult(
                success=False,
                error_message=error,
            )
        
        # אכיפת מגבלות
        timeout = min(max(1, timeout), self.MAX_TIMEOUT)
        memory_limit_mb = min(max(32, memory_limit_mb), self.MAX_MEMORY_MB)
        
        start_time = time.monotonic()
        
        try:
            if self._use_docker and self._docker_available:
                result = self._execute_docker(code, timeout, memory_limit_mb)
            else:
                result = self._execute_subprocess(code, timeout)
            
            result.execution_time_ms = int((time.monotonic() - start_time) * 1000)
            return result
            
        except subprocess.TimeoutExpired:
            return ExecutionResult(
                success=False,
                error_message=f"תם הזמן להרצה ({timeout} שניות)",
                execution_time_ms=timeout * 1000,
            )
        except Exception as e:
            logger.error(f"Code execution error: {e}", exc_info=True)
            return ExecutionResult(
                success=False,
                error_message=f"שגיאה בהרצה: {str(e)}",
            )
    
    def _execute_docker(
        self,
        code: str,
        timeout: int,
        memory_limit_mb: int,
    ) -> ExecutionResult:
        """הרצה בתוך Docker container."""
        
        # פקודת Docker עם הגנות מלאות
        docker_cmd = [
            "docker", "run",
            "--rm",                              # מחיקה אוטומטית
            "--network", "none",                 # ללא רשת
            "--read-only",                       # קריאה בלבד
            f"--memory={memory_limit_mb}m",      # הגבלת זיכרון
            "--memory-swap", f"{memory_limit_mb}m",  # ללא swap
            "--cpus=0.5",                        # חצי CPU
            "--pids-limit=50",                   # הגבלת processes
            "--security-opt=no-new-privileges",  # ללא העלאת הרשאות
            "--cap-drop=ALL",                    # הסרת capabilities
            "--user", "nobody",                  # משתמש מוגבל
            self.DOCKER_IMAGE,
            "python", "-c", code,
        ]
        
        result = subprocess.run(
            docker_cmd,
            capture_output=True,
            timeout=timeout + 2,  # קצת יותר מ-timeout פנימי
        )
        
        stdout = self._sanitize_output(result.stdout.decode("utf-8", errors="replace"))
        stderr = self._sanitize_output(result.stderr.decode("utf-8", errors="replace"))
        
        truncated = (
            len(result.stdout) > self.MAX_OUTPUT_BYTES or
            len(result.stderr) > self.MAX_OUTPUT_BYTES
        )
        
        return ExecutionResult(
            success=result.returncode == 0,
            stdout=stdout,
            stderr=stderr,
            exit_code=result.returncode,
            truncated=truncated,
        )
    
    def _execute_subprocess(
        self,
        code: str,
        timeout: int,
    ) -> ExecutionResult:
        """
        הרצה ב-subprocess (לפיתוח בלבד!).
        
        ⚠️ אזהרה: שיטה זו פחות בטוחה מ-Docker.
        """
        logger.warning("Executing code via subprocess - UNSAFE for production!")
        
        result = subprocess.run(
            ["python", "-c", code],
            capture_output=True,
            timeout=timeout,
            env={
                "PATH": "/usr/bin:/bin",
                "PYTHONDONTWRITEBYTECODE": "1",
            },
        )
        
        stdout = self._sanitize_output(result.stdout.decode("utf-8", errors="replace"))
        stderr = self._sanitize_output(result.stderr.decode("utf-8", errors="replace"))
        
        return ExecutionResult(
            success=result.returncode == 0,
            stdout=stdout,
            stderr=stderr,
            exit_code=result.returncode,
        )
    
    # ============== Helper Methods ==============
    
    def get_allowed_imports(self) -> List[str]:
        """רשימת imports מותרים."""
        return list(self.ALLOWED_IMPORTS)
    
    def get_limits(self) -> Dict[str, Any]:
        """מגבלות הרצה נוכחיות."""
        return {
            "max_timeout_seconds": self.MAX_TIMEOUT,
            "max_memory_mb": self.MAX_MEMORY_MB,
            "max_code_length_bytes": self.MAX_CODE_LENGTH,
            "max_output_bytes": self.MAX_OUTPUT_BYTES,
            "docker_available": self._docker_available,
        }


# ============== Singleton ==============

_service_instance: Optional[CodeExecutionService] = None


def get_code_execution_service() -> CodeExecutionService:
    """קבלת instance יחיד של השירות."""
    global _service_instance
    if _service_instance is None:
        # בפרודקשן: Docker=True, בפיתוח: לפי ENV
        use_docker = os.getenv("CODE_EXEC_USE_DOCKER", "true").lower() == "true"
        _service_instance = CodeExecutionService(use_docker=use_docker)
    return _service_instance
```

---

## 2. API Routes – הרחבת `code_tools_api.py`

### הוספה לקובץ: `webapp/code_tools_api.py`

```python
# הוספה ל-imports בראש הקובץ:
from services.code_execution_service import (
    get_code_execution_service,
    ExecutionResult,
)

# ============================================================
# Code Execution Endpoint
# ============================================================

# Feature flag - ברירת מחדל: מכובה
FEATURE_CODE_EXECUTION = os.getenv("FEATURE_CODE_EXECUTION", "false").lower() == "true"


def _is_code_execution_allowed(user_id: int) -> bool:
    """
    בדיקה האם הרצת קוד מותרת למשתמש.
    
    ברירת מחדל: Admin בלבד.
    ניתן להרחיב ל-whitelist או לכולם (לא מומלץ).
    """
    if not FEATURE_CODE_EXECUTION:
        return False
    return _is_admin(user_id)


@code_tools_bp.route("/run", methods=["POST"])
def run_code():
    """
    הרצת קוד Python בסביבה מבודדת.

    Request Body:
        {
            "code": "<python code>",
            "timeout": 5,           // אופציונלי, 1-30 שניות
            "memory_limit_mb": 128  // אופציונלי, 32-128 MB
        }

    Response (Success):
        {
            "success": true,
            "stdout": "Hello World\\n",
            "stderr": "",
            "exit_code": 0,
            "execution_time_ms": 45,
            "truncated": false
        }

    Response (Error):
        {
            "success": false,
            "error": "הקוד מכיל פעולה לא מורשית: import os",
            "stdout": "",
            "stderr": "",
            "exit_code": -1
        }
    """
    # בדיקת Feature Flag
    if not FEATURE_CODE_EXECUTION:
        return jsonify({
            "success": False,
            "error": "הרצת קוד מושבתת בשרת זה",
        }), 403
    
    # בדיקת הרשאות
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"success": False, "error": "נדרש להתחבר"}), 401
    
    try:
        uid_int = int(user_id)
    except Exception:
        return jsonify({"success": False, "error": "משתמש לא תקין"}), 401
    
    if not _is_code_execution_allowed(uid_int):
        return jsonify({
            "success": False,
            "error": "אין הרשאה להריץ קוד",
        }), 403
    
    # פרסור הבקשה
    data = request.get_json()
    if not data or "code" not in data:
        return jsonify({"success": False, "error": "חסר קוד"}), 400
    
    code = data.get("code", "")
    timeout = data.get("timeout", 5)
    memory_limit_mb = data.get("memory_limit_mb", 128)
    
    # Validation של פרמטרים
    try:
        timeout = min(max(1, int(timeout)), 30)
        memory_limit_mb = min(max(32, int(memory_limit_mb)), 128)
    except (ValueError, TypeError):
        timeout = 5
        memory_limit_mb = 128
    
    # הרצה
    service = get_code_execution_service()
    result = service.execute(
        code=code,
        timeout=timeout,
        memory_limit_mb=memory_limit_mb,
    )
    
    # לוג (ללא הקוד עצמו - אבטחה)
    try:
        from logging import getLogger
        logger = getLogger(__name__)
        logger.info(
            "Code execution: user=%s success=%s exit=%s time=%dms",
            uid_int,
            result.success,
            result.exit_code,
            result.execution_time_ms,
        )
    except Exception:
        pass
    
    return jsonify({
        "success": result.success,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "exit_code": result.exit_code,
        "execution_time_ms": result.execution_time_ms,
        "truncated": result.truncated,
        "error": result.error_message,
    })


@code_tools_bp.route("/run/limits", methods=["GET"])
def get_run_limits():
    """
    קבלת מגבלות הרצה.

    Response:
        {
            "enabled": true,
            "limits": {
                "max_timeout_seconds": 30,
                "max_memory_mb": 128,
                "max_code_length_bytes": 51200,
                "max_output_bytes": 102400,
                "docker_available": true
            },
            "allowed_imports": ["math", "random", ...]
        }
    """
    service = get_code_execution_service()
    
    return jsonify({
        "enabled": FEATURE_CODE_EXECUTION,
        "limits": service.get_limits(),
        "allowed_imports": service.get_allowed_imports(),
    })
```

---

## 3. Frontend – הוספה ל-`code-tools-page.js`

### עדכון: `webapp/static/js/code-tools-page.js`

הוסף את הקוד הבא **בתוך פונקציית `init()`**, אחרי האתחולים הקיימים:

```javascript
// ============================================================
// Code Execution (Run Button)
// ============================================================

const btnRun = document.getElementById('btn-run');
const outputConsole = document.getElementById('run-output');

// בדיקה האם הרצת קוד מופעלת
async function checkExecutionEnabled() {
  try {
    const resp = await fetch('/api/code/run/limits');
    const data = await resp.json();
    
    if (data && data.enabled && btnRun) {
      btnRun.style.display = 'inline-flex';
      btnRun.title = `Timeout: ${data.limits?.max_timeout_seconds || 30}s`;
    }
    
    return data;
  } catch (e) {
    console.log('Code execution not available');
    return null;
  }
}

async function runCode() {
  const code = getDoc(inputEditor);
  if (!code.trim()) {
    showStatus('אין קוד להרצה', 'warning');
    return;
  }

  showStatus('מריץ...', 'loading');
  
  // הצגת פאנל פלט
  setViewMode('output');
  if (outputConsole) {
    outputConsole.innerHTML = '<div class="console-loading">⏳ מריץ קוד...</div>';
  }

  try {
    const result = await postJson('/api/code/run', {
      code,
      timeout: 10,
      memory_limit_mb: 128,
    });

    if (outputConsole) {
      let html = '';
      
      // Stdout
      if (result.stdout) {
        html += `<div class="console-stdout">${escapeHtml(result.stdout)}</div>`;
      }
      
      // Stderr
      if (result.stderr) {
        html += `<div class="console-stderr">${escapeHtml(result.stderr)}</div>`;
      }
      
      // Error message
      if (result.error && !result.success) {
        html += `<div class="console-error">❌ ${escapeHtml(result.error)}</div>`;
      }
      
      // Empty output
      if (!html) {
        html = '<div class="console-info">הקוד רץ בהצלחה (ללא פלט)</div>';
      }
      
      // Metadata
      html += `<div class="console-meta">
        Exit: ${result.exit_code} · Time: ${result.execution_time_ms}ms
        ${result.truncated ? ' · ⚠️ הפלט קוצץ' : ''}
      </div>`;
      
      outputConsole.innerHTML = html;
    }

    if (result.success) {
      showStatus(`הרצה הסתיימה (${result.execution_time_ms}ms)`, 'success');
    } else {
      showStatus(result.error || 'שגיאה בהרצה', 'error');
    }
    
  } catch (e) {
    if (outputConsole) {
      outputConsole.innerHTML = `<div class="console-error">❌ ${escapeHtml(e.message)}</div>`;
    }
    showStatus(e.message || 'שגיאה בהרצה', 'error');
  }
}

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

// Event listeners
btnRun?.addEventListener('click', runCode);

// Keyboard shortcut: Ctrl+Enter to run
document.addEventListener('keydown', (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
    e.preventDefault();
    runCode();
  }
});

// בדיקת זמינות בטעינה
checkExecutionEnabled();
```

---

## 4. HTML Updates – הוספת כפתור Run

### עדכון: `webapp/templates/code_tools.html`

הוסף כפתור Run לתוך ה-toolbar:

```html
<!-- בתוך .toolbar-group.primary-actions, אחרי btn-lint -->
<button id="btn-run" class="btn btn-success" style="display:none;" title="הרץ (Ctrl+Enter)">
  ▶️ הרץ
</button>
```

הוסף tab חדש ל-view toggle:

```html
<!-- בתוך .view-toggle -->
<button class="view-btn" data-view="output">פלט</button>
```

הוסף את ה-output view בתוך panel-body:

```html
<!-- בתוך .panel-body של output-panel, אחרי issues-view -->
<div id="output-view" class="view-content">
  <div id="run-output" class="run-console"></div>
</div>
```

---

## 5. CSS – סגנונות לפלט

### הוספה לקובץ: `webapp/static/css/code-tools.css`

```css
/* ============================================================
   Code Execution Output Console
   ============================================================ */

.run-console {
  padding: 1rem;
  font-family: var(--font-mono, 'JetBrains Mono', 'Fira Code', monospace);
  font-size: 0.9rem;
  line-height: 1.5;
  min-height: 200px;
  direction: ltr;
  text-align: left;
}

.console-loading {
  color: var(--text-muted, rgba(255, 255, 255, 0.6));
  text-align: center;
  padding: 2rem;
}

.console-stdout {
  white-space: pre-wrap;
  word-break: break-word;
  color: var(--text-primary, #ffffff);
  margin-bottom: 0.5rem;
}

.console-stderr {
  white-space: pre-wrap;
  word-break: break-word;
  color: #ff8a8a;
  margin-bottom: 0.5rem;
  padding: 0.5rem;
  background: rgba(255, 99, 132, 0.1);
  border-radius: 6px;
  border-left: 3px solid #ff6384;
}

.console-error {
  color: #ff6384;
  padding: 0.75rem;
  background: rgba(255, 99, 132, 0.12);
  border-radius: 8px;
  margin-top: 0.5rem;
}

.console-info {
  color: var(--text-muted, rgba(255, 255, 255, 0.6));
  text-align: center;
  padding: 1rem;
}

.console-meta {
  margin-top: 1rem;
  padding-top: 0.75rem;
  border-top: 1px solid rgba(255, 255, 255, 0.1);
  font-size: 0.8rem;
  color: var(--text-muted, rgba(255, 255, 255, 0.5));
}

/* Success button style */
.code-tools-container .btn.btn-success,
.code-tools-group .btn.btn-success {
  background: linear-gradient(135deg, #10b981, #059669);
  border: none;
  color: #ffffff;
}

.code-tools-container .btn.btn-success:hover,
.code-tools-group .btn.btn-success:hover {
  background: linear-gradient(135deg, #059669, #047857);
  box-shadow: 0 4px 12px rgba(16, 185, 129, 0.3);
}

/* Running state */
.code-tools-container .btn.btn-success.running,
.code-tools-group .btn.btn-success.running {
  opacity: 0.7;
  pointer-events: none;
}
```

---

## 6. Environment Variables

### הוספה ל-`.env` או `docker-compose.yml`:

```bash
# Code Execution Feature
FEATURE_CODE_EXECUTION=true      # הפעלת הפיצ'ר (false by default)
CODE_EXEC_USE_DOCKER=true        # שימוש ב-Docker (מומלץ)
CODE_EXEC_MAX_TIMEOUT=30         # timeout מקסימלי בשניות
CODE_EXEC_MAX_MEMORY_MB=128      # זיכרון מקסימלי
```

---

## 7. Docker Setup

### וידוא Docker Image

לפני השימוש, יש לוודא שה-image קיים:

```bash
docker pull python:3.11-slim
```

### הרשאות Docker (Linux)

אם ה-webapp רץ כ-non-root, יש להוסיף את המשתמש לקבוצת docker:

```bash
sudo usermod -aG docker www-data
```

או להריץ עם Docker socket mount ב-docker-compose:

```yaml
# docker-compose.yml
code-keeper-bot:
  volumes:
    - /var/run/docker.sock:/var/run/docker.sock:ro
```

---

## 8. אבטחה ✅

### שכבות הגנה

| שכבה | מה עושה | איפה |
|------|---------|------|
| **Feature Flag** | מכבה את הפיצ'ר כברירת מחדל | `FEATURE_CODE_EXECUTION` |
| **Auth** | רק משתמשים מחוברים | `session.get("user_id")` |
| **Admin Check** | רק אדמינים (ברירת מחדל) | `_is_code_execution_allowed()` |
| **Keyword Blocking** | חסימת פקודות מסוכנות | `BLOCKED_KEYWORDS` |
| **Code Length** | הגבלת אורך קוד | 50KB |
| **Docker Sandbox** | בידוד מלא | `--network none`, `--read-only` |
| **Resource Limits** | הגבלת CPU/Memory | `--memory`, `--cpus` |
| **Timeout** | מניעת infinite loops | 5-30 שניות |
| **Output Limit** | מניעת memory bomb | 100KB |
| **No Privileges** | הרצה כ-nobody | `--user nobody`, `--cap-drop=ALL` |

### מה **לא** לעשות

❌ אל תפעיל את הפיצ'ר ללא Docker בפרודקשן  
❌ אל תאפשר הרצה לכל המשתמשים ללא שיקול  
❌ אל תעלה את ה-timeout מעל 30 שניות  
❌ אל תאפשר גישה לרשת מתוך הקונטיינר  
❌ אל תשמור קוד משתמשים ללא הצפנה  

### הרחבת הרשאות (זהירות!)

אם רוצים לאפשר לכל המשתמשים:

```python
def _is_code_execution_allowed(user_id: int) -> bool:
    if not FEATURE_CODE_EXECUTION:
        return False
    
    # אפשרות 1: לכל משתמש מחובר
    return True
    
    # אפשרות 2: Whitelist
    allowed_users = os.getenv("CODE_EXEC_ALLOWED_USERS", "").split(",")
    return str(user_id) in allowed_users
```

---

## 9. בדיקות (Tests)

### קובץ: `tests/test_code_execution_service.py`

```python
"""Unit tests for CodeExecutionService."""

from unittest.mock import MagicMock, patch
import pytest

from services.code_execution_service import (
    CodeExecutionService,
    ExecutionResult,
    get_code_execution_service,
)


class TestCodeExecutionService:
    """Test suite for CodeExecutionService."""

    def setup_method(self):
        """Setup test instance (no Docker)."""
        self.service = CodeExecutionService(use_docker=False)

    def test_validate_empty_code(self):
        """Empty code should fail validation."""
        is_valid, error = self.service.validate_code("")
        assert is_valid is False
        assert "ריק" in error

    def test_validate_blocked_keywords(self):
        """Blocked keywords should fail validation."""
        dangerous_codes = [
            "import os",
            "import subprocess",
            "__import__('os')",
            "eval('code')",
            "exec('code')",
            "open('file.txt')",
        ]
        
        for code in dangerous_codes:
            is_valid, error = self.service.validate_code(code)
            assert is_valid is False, f"Should block: {code}"
            assert "לא מורשית" in error

    def test_validate_safe_code(self):
        """Safe code should pass validation."""
        safe_codes = [
            "print('hello')",
            "x = 1 + 2",
            "import math\nprint(math.pi)",
            "for i in range(10): print(i)",
        ]
        
        for code in safe_codes:
            is_valid, error = self.service.validate_code(code)
            assert is_valid is True, f"Should allow: {code}"
            assert error is None

    def test_validate_code_too_long(self):
        """Code exceeding max length should fail."""
        long_code = "x = 1\n" * 100000
        is_valid, error = self.service.validate_code(long_code)
        assert is_valid is False
        assert "ארוך" in error

    @patch('subprocess.run')
    def test_execute_simple_code(self, mock_run):
        """Test simple code execution."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=b"Hello World\n",
            stderr=b"",
        )
        
        result = self.service.execute("print('Hello World')")
        
        assert result.success is True
        assert "Hello World" in result.stdout
        assert result.exit_code == 0

    @patch('subprocess.run')
    def test_execute_with_error(self, mock_run):
        """Test code that raises an error."""
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout=b"",
            stderr=b"NameError: name 'x' is not defined\n",
        )
        
        result = self.service.execute("print(x)")
        
        assert result.success is False
        assert "NameError" in result.stderr
        assert result.exit_code == 1

    @patch('subprocess.run')
    def test_execute_timeout(self, mock_run):
        """Test timeout handling."""
        from subprocess import TimeoutExpired
        mock_run.side_effect = TimeoutExpired(cmd="python", timeout=5)
        
        result = self.service.execute("while True: pass")
        
        assert result.success is False
        assert "תם הזמן" in result.error_message

    def test_sanitize_output_truncation(self):
        """Long output should be truncated."""
        long_output = "x" * 200000
        sanitized = self.service._sanitize_output(long_output)
        
        assert len(sanitized) <= self.service.MAX_OUTPUT_BYTES + 50
        assert "קוצץ" in sanitized

    def test_get_limits(self):
        """Test limits getter."""
        limits = self.service.get_limits()
        
        assert "max_timeout_seconds" in limits
        assert "max_memory_mb" in limits
        assert "docker_available" in limits

    def test_get_allowed_imports(self):
        """Test allowed imports list."""
        imports = self.service.get_allowed_imports()
        
        assert "math" in imports
        assert "random" in imports
        assert "os" not in imports


class TestDockerExecution:
    """Tests for Docker-based execution (integration)."""

    @pytest.fixture
    def docker_service(self):
        """Service with Docker enabled."""
        service = CodeExecutionService(use_docker=True)
        if not service.is_docker_available():
            pytest.skip("Docker not available")
        return service

    def test_docker_simple_execution(self, docker_service):
        """Test actual Docker execution."""
        result = docker_service.execute("print('Docker works!')")
        
        assert result.success is True
        assert "Docker works!" in result.stdout

    def test_docker_network_blocked(self, docker_service):
        """Network should be blocked in Docker."""
        result = docker_service.execute("""
import socket
try:
    socket.create_connection(("google.com", 80), timeout=1)
    print("NETWORK WORKS - BAD!")
except:
    print("Network blocked - Good!")
""")
        
        assert "blocked" in result.stdout.lower() or result.exit_code != 0

    def test_docker_filesystem_readonly(self, docker_service):
        """Filesystem should be read-only."""
        result = docker_service.execute("""
try:
    with open('/tmp/test.txt', 'w') as f:
        f.write('test')
    print("WRITE WORKS - BAD!")
except:
    print("Write blocked - Good!")
""")
        
        # בדיקה שכתיבה נכשלה או הפלט מציין חסימה
        assert "blocked" in result.stdout.lower() or "error" in result.stderr.lower()


class TestAPIEndpoint:
    """Tests for the /api/code/run endpoint."""

    @pytest.fixture
    def client(self, app):
        """Flask test client."""
        return app.test_client()

    def test_run_requires_auth(self, client):
        """Endpoint should require authentication."""
        response = client.post(
            '/api/code/run',
            json={"code": "print(1)"},
        )
        assert response.status_code in (401, 403)

    def test_run_requires_code(self, client, admin_session):
        """Endpoint should require code parameter."""
        response = client.post(
            '/api/code/run',
            json={},
        )
        assert response.status_code == 400
```

### הרצת הבדיקות

```bash
# Unit tests only (no Docker)
pytest tests/test_code_execution_service.py -v -k "not Docker"

# Full tests (requires Docker)
pytest tests/test_code_execution_service.py -v
```

---

## 10. צ'קליסט למימוש

- [ ] יצירת `services/code_execution_service.py`
- [ ] הוספת endpoints ל-`webapp/code_tools_api.py`
- [ ] עדכון `webapp/static/js/code-tools-page.js`
- [ ] עדכון `webapp/templates/code_tools.html`
- [ ] הוספת CSS ל-`webapp/static/css/code-tools.css`
- [ ] הגדרת ENV: `FEATURE_CODE_EXECUTION=true`
- [ ] וידוא Docker image: `python:3.11-slim`
- [ ] כתיבת בדיקות
- [ ] Review אבטחה
- [ ] בדיקה בסביבת פיתוח
- [ ] Deploy לסביבת staging
- [ ] תיעוד למשתמשים

---

## 11. תוצאה צפויה

לאחר המימוש, דף Code Tools יציג:

```
┌─────────────────────────────────────────────────────────────────────┐
│ 🛠️ כלי קוד                                                          │
│ Playground לעיצוב, בדיקת איכות והרצת קוד (Python)                   │
├─────────────────────────────────────────────────────────────────────┤
│ [✨ עיצוב] [🔍 Lint] [🔧 תיקון ▼] [▶️ הרץ]     [Black ▼] [88] שורה │
├─────────────────────────────────────────────────────────────────────┤
│                           │                                         │
│  קוד מקור                 │  תוצאה         [קוד] [Diff] [בעיות] [פלט]│
│  ─────────────────────    │  ───────────────────────────────────────│
│  │                     │  │                                        │
│  │ def greet(name):    │  │  Output:                               │
│  │     print(f"Hi {n.. │  │  ─────────────────────────────────     │
│  │                     │  │  Hi Alice                              │
│  │ greet("Alice")      │  │  Hi Bob                                │
│  │                     │  │                                        │
│  │                     │  │  Exit: 0 · Time: 45ms                  │
│  │                     │  │                                        │
│  └─────────────────────┘  └────────────────────────────────────────┘
│  Python · 4 שורות · 0KB                                             │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 12. הרחבות עתידיות

### תמיכה בשפות נוספות

```python
# בתוך CodeExecutionService

LANGUAGE_IMAGES = {
    "python": "python:3.11-slim",
    "node": "node:20-slim",
    "ruby": "ruby:3.2-slim",
    "go": "golang:1.21-alpine",
}

def execute(self, code: str, language: str = "python", ...):
    image = self.LANGUAGE_IMAGES.get(language, "python:3.11-slim")
    # ...
```

### היסטוריית הרצות

```python
# שמירה ב-MongoDB
async def save_execution(
    user_id: int,
    code_hash: str,
    result: ExecutionResult,
):
    await db.code_executions.insert_one({
        "user_id": user_id,
        "code_hash": code_hash,  # לא שומרים את הקוד עצמו
        "success": result.success,
        "exit_code": result.exit_code,
        "execution_time_ms": result.execution_time_ms,
        "timestamp": datetime.utcnow(),
    })
```

### WebSocket לפלט בזמן אמת

```python
# עבור קוד ארוך עם הרבה prints
# websocket שמזרים stdout בזמן אמת
```

---

## 13. שאלות נפוצות

### ש: למה צריך Docker?

בלי Docker, קוד זדוני יכול:
- לקרוא/לכתוב קבצים בשרת
- לגשת לרשת הפנימית
- לצרוך את כל המשאבים
- להריץ פקודות מערכת

Docker מבודד את הקוד לקונטיינר זמני ללא גישה.

### ש: מה קורה אם אין Docker?

השירות יעבור ל-subprocess fallback, אבל **זה לא בטוח**!
- מתאים רק לפיתוח מקומי
- לא להפעיל בפרודקשן
- יהיה לוג אזהרה

### ש: איך מוסיפים ספריות Python?

יש שתי אפשרויות:

1. **Whitelist imports** - הוספה ל-`ALLOWED_IMPORTS`
2. **Custom image** - יצירת Dockerfile עם הספריות:

```dockerfile
FROM python:3.11-slim
RUN pip install numpy pandas matplotlib
```

### ש: האם אפשר להריץ קוד אסינכרוני?

כרגע לא. הקוד רץ כ-`python -c "..."` שלא תומך ב-await ברמה העליונה.

אפשר להוסיף תמיכה:

```python
import asyncio
asyncio.run(main())
```

### ש: מה לגבי Rate Limiting?

מומלץ להוסיף הגבלה על מספר הרצות:

```python
from flask_limiter import Limiter

limiter = Limiter(app, key_func=get_user_id)

@code_tools_bp.route("/run", methods=["POST"])
@limiter.limit("10 per minute")
def run_code():
    ...
```

---

## 14. מקורות נוספים

- [Docker Security Best Practices](https://docs.docker.com/engine/security/)
- [Python Sandbox Techniques](https://wiki.python.org/moin/SandboxedPython)
- [Code Tools API הקיים](/workspace/webapp/code_tools_api.py)
- [Code Formatter Service](/workspace/services/code_formatter_service.py)
- [Cache Inspector Guide](/workspace/GUIDES/CACHE_INSPECTOR_IMPLEMENTATION_GUIDE.md) - מדריך מימוש דומה
