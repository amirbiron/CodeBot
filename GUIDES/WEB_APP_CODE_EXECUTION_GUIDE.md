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
| **פלט אחרי סיום** | הצגת stdout/stderr לאחר סיום ההרצה |
| **הגבלות אבטחה** | Sandbox עם timeout ומגבלות משאבים |
| **היסטוריה** | שמירת הרצות אחרונות (אופציונלי) |

> **הערה:** כרגע זו קריאה סינכרונית שמחזירה פלט בסוף. לפלט בזמן אמת (streaming) ראו סעיף 12 – הרחבות עתידיות (SSE/WebSocket).

### למה זה שימושי?

- **למידה**: לבדוק snippets מספריית הקוד
- **דיבאג**: לבדוק קטעי קוד לפני שמירה
- **Playground**: סביבת ניסויים מהירה
- **Code Tools**: משלים את הפיצ'ר הקיים של עיצוב ו-lint

### הגנות Admin קיימות (חשוב!)

הדף `/tools/code` ו-API `/api/code/*` **כבר מוגנים** בפרויקט:
- הדף מוגן עם `@admin_required` ב-`webapp/app.py`
- כל ה-API מוגן עם `@code_tools_bp.before_request` ב-`webapp/code_tools_api.py`

**לכן:** אין צורך לשכפל בדיקות Admin בכל endpoint חדש. מספיק להוסיף Feature Flag + הלוגיקה עצמה.

### סיכוני אבטחה ⚠️

הרצת קוד משתמש בשרת היא **פעולה מסוכנת**. המדריך כולל שכבות הגנה:

1. **Docker Sandbox** – הרצה בקונטיינר מבודד (חובה בפרודקשן)
2. **Fail-Closed** – אם Docker לא זמין בפרודקשן, מסרבים להריץ (לא fallback)
3. **Timeout** – מגבלת זמן ריצה (5-30 שניות)
4. **Resource Limits** – הגבלת CPU/Memory/PIDs
5. **Network Isolation** – ללא גישה לרשת
6. **Read-only + tmpfs** – אין כתיבה לדיסק, רק ל-/tmp מוגבל
7. **Admin Only** – ברירת מחדל: רק אדמינים (כבר קיים ברמת ה-Blueprint)

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

קונפיגורציה דרך ENV:
    CODE_EXEC_USE_DOCKER=true       # חובה בפרודקשן
    CODE_EXEC_ALLOW_FALLBACK=false  # false = fail-closed בפרודקשן
    CODE_EXEC_MAX_TIMEOUT=30        # מקסימום timeout בשניות
    CODE_EXEC_MAX_MEMORY_MB=128     # מקסימום זיכרון
    CODE_EXEC_DOCKER_IMAGE=python:3.11-slim
"""

from __future__ import annotations

import logging
import subprocess
import tempfile
import time
import os
import uuid
from dataclasses import dataclass
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)


def _get_env_int(key: str, default: int) -> int:
    """קריאת ENV כ-int עם ברירת מחדל."""
    val = os.environ.get(key)
    if val is None:
        return default
    try:
        return int(val)
    except ValueError:
        return default


def _get_env_bool(key: str, default: bool) -> bool:
    """קריאת ENV כ-bool עם ברירת מחדל."""
    val = os.environ.get(key)
    if val is None:
        return default
    return val.lower() in ("true", "1", "yes", "on")


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
    used_docker: bool = False  # האם רץ ב-Docker
    
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
    2. subprocess (לפיתוח בלבד) - רק אם ALLOW_FALLBACK=true
    
    שימוש:
        service = CodeExecutionService()
        result = service.execute("print('Hello')")
        print(result.stdout)  # Hello
    """
    
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
    
    # Label לזיהוי קונטיינרים להרצת קוד (ל-cleanup)
    CONTAINER_LABEL: str = "code_exec=1"
    
    def __init__(self):
        """
        אתחול השירות.
        קונפיגורציה נקראת מ-ENV בזמן __init__ (לא global)
        כדי לאפשר monkeypatch בטסטים.
        """
        self._use_docker = _get_env_bool("CODE_EXEC_USE_DOCKER", True)
        self._allow_fallback = _get_env_bool("CODE_EXEC_ALLOW_FALLBACK", False)
        self._max_timeout = _get_env_int("CODE_EXEC_MAX_TIMEOUT", 30)
        self._max_memory_mb = _get_env_int("CODE_EXEC_MAX_MEMORY_MB", 128)
        self._max_output_bytes = _get_env_int("CODE_EXEC_MAX_OUTPUT_BYTES", 100 * 1024)
        self._max_code_length = _get_env_int("CODE_EXEC_MAX_CODE_LENGTH", 50 * 1024)
        self._docker_image = os.environ.get("CODE_EXEC_DOCKER_IMAGE", "python:3.11-slim")
        
        self._docker_available = self._check_docker()
        
        # לוג קונפיגורציה בעלייה
        logger.info(
            "CodeExecutionService initialized: docker=%s, available=%s, fallback=%s",
            self._use_docker,
            self._docker_available,
            self._allow_fallback,
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
    
    def can_execute(self) -> tuple[bool, Optional[str]]:
        """
        בדיקה האם אפשר להריץ קוד כרגע.
        
        לוגיקה חיובית (Whitelist):
        1. Docker מוגדר וזמין? → OK
        2. Fallback מותר? → OK
        3. אחרת → שגיאה
        
        Returns:
            (can_execute, error_message)
        """
        # 1. האם Docker מוגדר וזמין?
        if self._use_docker and self._docker_available:
            return True, None
        
        # 2. אם לא, האם מותר Fallback?
        if self._allow_fallback:
            return True, None
        
        # 3. אף אחד מהם לא מתקיים - שגיאה
        if self._use_docker and not self._docker_available:
            return False, "Docker מוגדר אך אינו זמין בשרת"
        
        # Docker כבוי מפורשות ו-Fallback אסור
        return False, "הרצת קוד מושבתת (Docker כבוי ו-Fallback אסור)"
    
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
        if len(code) > self._max_code_length:
            return False, f"הקוד ארוך מדי (מקסימום {self._max_code_length // 1024}KB)"
        
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
    
    def _sanitize_output(self, output: str) -> tuple[str, bool]:
        """
        ניקוי וקיצוץ פלט.
        
        Returns:
            (sanitized_output, was_truncated)
        """
        if not output:
            return "", False
        
        # המרה ל-UTF-8 בטוח
        try:
            output = output.encode("utf-8", errors="replace").decode("utf-8")
        except Exception:
            output = str(output)
        
        # קיצוץ אם ארוך מדי
        truncated = len(output) > self._max_output_bytes
        if truncated:
            output = output[:self._max_output_bytes] + "\n... (הפלט קוצץ)"
        
        return output, truncated
    
    # ============== Execution ==============
    
    def execute(
        self,
        code: str,
        timeout: int = 5,
        memory_limit_mb: int = 128,
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
        # בדיקת זמינות (fail-closed)
        can_exec, exec_error = self.can_execute()
        if not can_exec:
            return ExecutionResult(
                success=False,
                error_message=exec_error,
            )
        
        # Validation
        is_valid, error = self.validate_code(code)
        if not is_valid:
            return ExecutionResult(
                success=False,
                error_message=error,
            )
        
        # אכיפת מגבלות
        timeout = min(max(1, timeout), self._max_timeout)
        memory_limit_mb = min(max(32, memory_limit_mb), self._max_memory_mb)
        
        start_time = time.monotonic()
        use_docker = self._use_docker and self._docker_available
        
        try:
            if use_docker:
                result = self._execute_docker(code, timeout, memory_limit_mb)
            elif self._allow_fallback:
                # Fallback ל-subprocess רק אם הוגדר במפורש
                result = self._execute_subprocess(code, timeout)
            else:
                # Fail-closed: Docker לא זמין ו-fallback חסום
                # הערה: can_execute() אמור לתפוס את זה קודם,
                # אבל זו הגנה לעומק (defense in depth)
                logger.error(
                    "Code execution blocked: docker=%s, available=%s, fallback=%s",
                    self._use_docker, self._docker_available, self._allow_fallback
                )
                return ExecutionResult(
                    success=False,
                    error_message="תצורת שרת שגויה: הרצה ללא Docker חסומה",
                )
            
            result.execution_time_ms = int((time.monotonic() - start_time) * 1000)
            result.used_docker = use_docker
            
            # לוג (ללא קוד וללא פלט - רק מטא-דאטה)
            logger.info(
                "Code execution: docker=%s exit=%s time=%dms truncated=%s",
                use_docker,
                result.exit_code,
                result.execution_time_ms,
                result.truncated,
            )
            
            return result
            
        except subprocess.TimeoutExpired:
            logger.warning("Code execution timeout: %ds", timeout)
            return ExecutionResult(
                success=False,
                error_message=f"תם הזמן להרצה ({timeout} שניות)",
                execution_time_ms=timeout * 1000,
                used_docker=use_docker,
            )
        except Exception as e:
            # לא מלוגגים את e המלא כי עלול להכיל קוד
            logger.error("Code execution error: %s", type(e).__name__)
            return ExecutionResult(
                success=False,
                error_message=f"שגיאה בהרצה: {type(e).__name__}",
            )
    
    def _execute_docker(
        self,
        code: str,
        timeout: int,
        memory_limit_mb: int,
    ) -> ExecutionResult:
        """
        הרצה בתוך Docker container עם הגנות מלאות.
        
        הגנות Docker:
        - --rm: מחיקה אוטומטית
        - --network none: ללא רשת
        - --read-only: filesystem רק קריאה
        - --tmpfs /tmp: /tmp זמני לכתיבה (עם noexec)
        - --memory/--cpus/--pids-limit: הגבלת משאבים
        - --security-opt no-new-privileges: ללא העלאת הרשאות
        - --cap-drop=ALL: הסרת כל ה-capabilities
        - --ipc=none: בידוד IPC
        - --name + --label: לזיהוי וניקוי ב-timeout
        
        הגנות משאבים (בזמן אמת):
        - RAM: tempfile במקום capture_output
        - Disk: ניטור גודל קבצים בלולאה עם Popen
        - Time: timeout עם kill
        """
        container_name = f"code-exec-{uuid.uuid4().hex[:12]}"
        
        docker_cmd = [
            "docker", "run",
            "--rm",
            f"--name={container_name}",
            f"--label={self.CONTAINER_LABEL}",
            "--network=none",
            "--read-only",
            "--tmpfs=/tmp:rw,noexec,nosuid,size=10m",
            f"--memory={memory_limit_mb}m",
            f"--memory-swap={memory_limit_mb}m",
            "--cpus=0.5",
            "--pids-limit=50",
            "--ipc=none",
            "--security-opt=no-new-privileges",
            "--cap-drop=ALL",
            "--user=nobody",
            self._docker_image,
            "python", "-c", code,
        ]
        
        # Popen + Polling לניטור בזמן אמת (מונע Disk Exhaustion)
        with tempfile.TemporaryFile() as stdout_f, tempfile.TemporaryFile() as stderr_f:
            start_time = time.monotonic()
            
            # 1. הפעלת התהליך (Non-blocking)
            process = subprocess.Popen(
                docker_cmd,
                stdout=stdout_f,
                stderr=stderr_f,
            )
            
            exit_code = None
            output_truncated = False
            error_msg = None
            
            # 2. לולאת ניטור (Polling)
            while True:
                # בדיקת סטטוס - האם התהליך סיים?
                exit_code = process.poll()
                if exit_code is not None:
                    break
                
                # בדיקת Timeout
                elapsed = time.monotonic() - start_time
                if elapsed > timeout + 2:
                    process.kill()
                    process.wait()  # חיכוי לסגירה נקייה
                    self._cleanup_container(container_name)
                    error_msg = f"תם הזמן להרצה ({timeout} שניות)"
                    break
                
                # בדיקת גודל קבצים (Disk Quota Protection)
                # os.fstat נותן את הגודל האמיתי מה-OS
                try:
                    out_size = os.fstat(stdout_f.fileno()).st_size
                    err_size = os.fstat(stderr_f.fileno()).st_size
                except OSError:
                    out_size = err_size = 0
                
                if out_size > self._max_output_bytes or err_size > self._max_output_bytes:
                    process.kill()
                    process.wait()
                    self._cleanup_container(container_name)
                    output_truncated = True
                    logger.warning(
                        "Output limit exceeded: stdout=%d stderr=%d max=%d",
                        out_size, err_size, self._max_output_bytes
                    )
                    break
                
                # המתנה קצרה למניעת עומס CPU
                time.sleep(0.05)
            
            # 3. קריאת הפלט שנצבר (עד המקסימום)
            stdout_f.seek(0)
            stderr_f.seek(0)
            
            read_limit = self._max_output_bytes + 100
            stdout_str = stdout_f.read(read_limit).decode("utf-8", errors="replace")
            stderr_str = stderr_f.read(read_limit).decode("utf-8", errors="replace")
        
        # Sanitization סופי
        stdout, out_trunc = self._sanitize_output(stdout_str)
        stderr, err_trunc = self._sanitize_output(stderr_str)
        
        return ExecutionResult(
            success=(exit_code == 0) and (error_msg is None),
            stdout=stdout,
            stderr=stderr,
            exit_code=exit_code if exit_code is not None else -1,
            truncated=output_truncated or out_trunc or err_trunc,
            error_message=error_msg,
        )
    
    def _cleanup_container(self, container_name: str) -> None:
        """ניקוי קונטיינר יתום (best-effort)."""
        try:
            subprocess.run(
                ["docker", "rm", "-f", container_name],
                capture_output=True,
                timeout=5,
            )
            logger.info("Cleaned up container: %s", container_name)
        except Exception:
            # best-effort, לא קריטי
            pass
    
    def cleanup_orphan_containers(self) -> int:
        """
        ניקוי קונטיינרים יתומים (שכבר סיימו לרוץ אך לא נמחקו).
        
        חשוב: מנקה רק קונטיינרים בסטטוס `exited`, לא רצים!
        זה מונע Race Condition שבו נהרוג קונטיינר באמצע הרצה.
        
        Returns:
            מספר הקונטיינרים שנוקו
        """
        try:
            # חשוב: -a להציג גם קונטיינרים שסיימו
            # חשוב: status=exited לסנן רק קונטיינרים שכבר לא רצים
            # בלי זה, נהרוג קונטיינרים אקטיביים!
            cmd = [
                "docker", "ps", "-a", "-q",
                "-f", f"label={self.CONTAINER_LABEL}",
                "-f", "status=exited",
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=10,
            )
            container_ids = result.stdout.decode().strip().split()
            
            count = 0
            for cid in container_ids:
                if cid:
                    subprocess.run(
                        ["docker", "rm", "-f", cid],
                        capture_output=True,
                        timeout=5,
                    )
                    count += 1
            
            if count > 0:
                logger.info("Cleaned up %d orphan (exited) containers", count)
            return count
            
        except Exception as e:
            logger.warning("Failed to cleanup orphan containers: %s", e)
            return 0
    
    def _execute_subprocess(
        self,
        code: str,
        timeout: int,
    ) -> ExecutionResult:
        """
        הרצה ב-subprocess (לפיתוח בלבד!).
        
        ⚠️ אזהרה: שיטה זו פחות בטוחה מ-Docker.
        משמשת רק כש-CODE_EXEC_ALLOW_FALLBACK=true.
        
        הגנות (עקבי עם _execute_docker):
        - RAM: tempfile
        - Disk: ניטור גודל בזמן אמת
        - Time: timeout
        """
        logger.warning("Executing code via subprocess (fallback mode)")
        
        with tempfile.TemporaryFile() as stdout_f, tempfile.TemporaryFile() as stderr_f:
            start_time = time.monotonic()
            
            process = subprocess.Popen(
                ["python", "-c", code],
                stdout=stdout_f,
                stderr=stderr_f,
                env={
                    "PATH": "/usr/bin:/bin",
                    "PYTHONDONTWRITEBYTECODE": "1",
                },
            )
            
            exit_code = None
            output_truncated = False
            error_msg = None
            
            # לולאת ניטור
            while True:
                exit_code = process.poll()
                if exit_code is not None:
                    break
                
                elapsed = time.monotonic() - start_time
                if elapsed > timeout:
                    process.kill()
                    process.wait()
                    error_msg = f"תם הזמן להרצה ({timeout} שניות)"
                    break
                
                try:
                    out_size = os.fstat(stdout_f.fileno()).st_size
                    err_size = os.fstat(stderr_f.fileno()).st_size
                except OSError:
                    out_size = err_size = 0
                
                if out_size > self._max_output_bytes or err_size > self._max_output_bytes:
                    process.kill()
                    process.wait()
                    output_truncated = True
                    break
                
                time.sleep(0.05)
            
            stdout_f.seek(0)
            stderr_f.seek(0)
            
            read_limit = self._max_output_bytes + 100
            stdout_str = stdout_f.read(read_limit).decode("utf-8", errors="replace")
            stderr_str = stderr_f.read(read_limit).decode("utf-8", errors="replace")
        
        stdout, out_trunc = self._sanitize_output(stdout_str)
        stderr, err_trunc = self._sanitize_output(stderr_str)
        
        return ExecutionResult(
            success=(exit_code == 0) and (error_msg is None),
            stdout=stdout,
            stderr=stderr,
            exit_code=exit_code if exit_code is not None else -1,
            truncated=output_truncated or out_trunc or err_trunc,
            error_message=error_msg,
        )
    
    # ============== Helper Methods ==============
    
    def get_allowed_imports(self) -> List[str]:
        """רשימת imports מותרים."""
        return list(self.ALLOWED_IMPORTS)
    
    def get_limits(self) -> Dict[str, Any]:
        """מגבלות הרצה נוכחיות."""
        return {
            "max_timeout_seconds": self._max_timeout,
            "max_memory_mb": self._max_memory_mb,
            "max_code_length_bytes": self._max_code_length,
            "max_output_bytes": self._max_output_bytes,
            "docker_available": self._docker_available,
            "docker_required": self._use_docker,
            "fallback_allowed": self._allow_fallback,
        }


# ============== Singleton ==============

_service_instance: Optional[CodeExecutionService] = None


def get_code_execution_service() -> CodeExecutionService:
    """קבלת instance יחיד של השירות."""
    global _service_instance
    if _service_instance is None:
        _service_instance = CodeExecutionService()
    return _service_instance


def reset_service_instance() -> None:
    """איפוס ה-singleton (לטסטים בלבד)."""
    global _service_instance
    _service_instance = None
```

---

## 2. API Routes – הרחבת `code_tools_api.py`

### הוספה לקובץ: `webapp/code_tools_api.py`

> **הערה חשובה:** הרשאות Admin כבר נבדקות ב-`@code_tools_bp.before_request`.  
> לכן בנקודות הקצה החדשות אנחנו בודקים רק את ה-Feature Flag.

```python
# הוספה ל-imports בראש הקובץ:
from services.code_execution_service import (
    get_code_execution_service,
)

# ============================================================
# Code Execution Endpoint
# ============================================================

def _is_code_execution_enabled() -> bool:
    """
    בדיקה האם הרצת קוד מופעלת.
    נקרא בזמן ריצה (לא כ-global) כדי לאפשר monkeypatch בטסטים.
    """
    return os.getenv("FEATURE_CODE_EXECUTION", "false").lower() == "true"


@code_tools_bp.route("/run", methods=["POST"])
def run_code():
    """
    הרצת קוד Python בסביבה מבודדת.
    
    הערה: הרשאות Admin נבדקות כבר ב-before_request של ה-Blueprint.

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
    # בדיקת Feature Flag בלבד (Admin נבדק ב-before_request)
    if not _is_code_execution_enabled():
        return jsonify({
            "success": False,
            "error": "הרצת קוד מושבתת בשרת זה",
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
    
    # הלוג כבר נעשה בתוך service.execute()
    
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
                "docker_available": true,
                "docker_required": true,
                "fallback_allowed": false
            },
            "allowed_imports": ["math", "random", ...]
        }
    """
    service = get_code_execution_service()
    
    return jsonify({
        "enabled": _is_code_execution_enabled(),
        "limits": service.get_limits(),
        "allowed_imports": service.get_allowed_imports(),
    })
```

---

## 3. Frontend – הוספה ל-`code-tools-page.js`

### עדכון: `webapp/static/js/code-tools-page.js`

#### שלב 1: עדכון `setViewMode` לתמיכה ב-output

הפונקציה `setViewMode` הקיימת תומכת רק ב-`code/diff/issues`.  
יש לעדכן אותה להוסיף תמיכה ב-`output`:

```javascript
// מחליף את הפונקציה setViewMode הקיימת
function setViewMode(mode) {
  const viewButtons = Array.from(document.querySelectorAll('.view-btn[data-view]'));
  // הוספת 'output' לרשימה
  const views = ['code', 'diff', 'issues', 'output'];
  views.forEach((v) => {
    const el = document.getElementById(`${v}-view`);
    if (el) el.classList.toggle('active', v === mode);
  });
  viewButtons.forEach((btn) => btn.classList.toggle('active', btn.dataset.view === mode));
}
```

#### שלב 2: הוספת לוגיקת Code Execution

הוסף את הקוד הבא **בתוך פונקציית `init()`**, אחרי האתחולים הקיימים:

```javascript
// ============================================================
// Code Execution (Run Button)
// ============================================================

const btnRun = document.getElementById('btn-run');
const outputConsole = document.getElementById('run-output');
let executionLimits = null;

// בדיקה האם הרצת קוד מופעלת
async function checkExecutionEnabled() {
  try {
    const resp = await fetch('/api/code/run/limits');
    const data = await resp.json();
    executionLimits = data;
    
    if (data && data.enabled && btnRun) {
      btnRun.style.display = 'inline-flex';
      const timeout = data.limits?.max_timeout_seconds || 30;
      const dockerInfo = data.limits?.docker_available ? '🐳 Docker' : '⚠️ Subprocess';
      btnRun.title = `הרץ (Ctrl+Enter) · Timeout: ${timeout}s · ${dockerInfo}`;
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

  // נעילת הכפתור
  if (btnRun) {
    btnRun.disabled = true;
    btnRun.classList.add('running');
  }
  
  showStatus('מריץ...', 'loading');
  
  // הצגת פאנל פלט
  setViewMode('output');
  if (outputConsole) {
    outputConsole.innerHTML = '<div class="console-loading">⏳ מריץ קוד...</div>';
  }

  try {
    const timeout = executionLimits?.limits?.max_timeout_seconds || 10;
    const result = await postJson('/api/code/run', {
      code,
      timeout: Math.min(timeout, 10),  // ברירת מחדל 10 שניות
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
  } finally {
    // שחרור הכפתור
    if (btnRun) {
      btnRun.disabled = false;
      btnRun.classList.remove('running');
    }
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
FEATURE_CODE_EXECUTION=true           # הפעלת הפיצ'ר (false by default)
CODE_EXEC_USE_DOCKER=true             # שימוש ב-Docker (חובה בפרודקשן)
CODE_EXEC_ALLOW_FALLBACK=false        # false = fail-closed אם אין Docker
CODE_EXEC_MAX_TIMEOUT=30              # timeout מקסימלי בשניות
CODE_EXEC_MAX_MEMORY_MB=128           # זיכרון מקסימלי
CODE_EXEC_MAX_OUTPUT_BYTES=102400     # פלט מקסימלי (100KB)
CODE_EXEC_MAX_CODE_LENGTH=51200       # אורך קוד מקסימלי (50KB)
CODE_EXEC_DOCKER_IMAGE=python:3.11-slim  # Docker image להרצה
```

### טבלת ENV מלאה

| משתנה | ברירת מחדל | תיאור |
|-------|------------|-------|
| `FEATURE_CODE_EXECUTION` | `false` | הפעלת הפיצ'ר |
| `CODE_EXEC_USE_DOCKER` | `true` | שימוש ב-Docker |
| `CODE_EXEC_ALLOW_FALLBACK` | `false` | האם לאפשר subprocess fallback |
| `CODE_EXEC_MAX_TIMEOUT` | `30` | Timeout מקסימלי (שניות) |
| `CODE_EXEC_MAX_MEMORY_MB` | `128` | זיכרון מקסימלי (MB) |
| `CODE_EXEC_MAX_OUTPUT_BYTES` | `102400` | פלט מקסימלי (bytes) |
| `CODE_EXEC_MAX_CODE_LENGTH` | `51200` | אורך קוד מקסימלי (bytes) |
| `CODE_EXEC_DOCKER_IMAGE` | `python:3.11-slim` | Docker image |

---

## 7. Docker Setup

### וידוא Docker Image

לפני השימוש, יש לוודא שה-image קיים:

```bash
docker pull python:3.11-slim
```

### הרשאות Docker (Linux)

#### אפשרות 1: הוספה לקבוצת docker (מומלץ לפיתוח)

```bash
sudo usermod -aG docker $(whoami)
# או אם webapp רץ כ-www-data:
sudo usermod -aG docker www-data
```

#### אפשרות 2: Docker Socket Mount

> ⚠️ **אזהרה: זהו סיכון אבטחה משמעותי!**  
> Mount של `/var/run/docker.sock` נותן בפועל **הרשאות root על השרת**.
> כל מי שיכול לגשת ל-socket יכול להריץ קונטיינרים עם mount של `/` וכו'.

```yaml
# docker-compose.yml - זהיר!
code-keeper-bot:
  volumes:
    - /var/run/docker.sock:/var/run/docker.sock:ro
```

#### אפשרות 3: Runner נפרד (מומלץ לפרודקשן)

עדיפות לארכיטקטורה עם **שירות runner ייעודי**:

```
┌─────────────────┐         ┌─────────────────┐
│   Webapp        │──HTTP──▶│  Code Runner    │
│  (no docker)    │         │  (has docker)   │
└─────────────────┘         └─────────────────┘
```

זה מאפשר:
- הפרדת הרשאות
- Rate limiting ברמת השירות
- Scaling עצמאי
- Monitoring נפרד

מימוש מלא של Runner נפרד הוא מחוץ לסקופ של מדריך זה, אבל זו הדרך הבטוחה ביותר.

### ניקוי קונטיינרים יתומים

קונטיינרים עלולים להישאר "יתומים" אם ה-timeout נכשל. השירות מסמן אותם עם label.

> ⚠️ **חשוב:** יש לנקות רק קונטיינרים בסטטוס `exited`!  
> ניקוי קונטיינרים `running` יהרוג הרצות אקטיביות של משתמשים.

```bash
# ניקוי ידני - רק קונטיינרים שכבר סיימו
docker ps -a -q -f label=code_exec=1 -f status=exited | xargs -r docker rm -f

# ניקוי תקופתי (cron) - בטוח להרצות אקטיביות
*/5 * * * * docker ps -a -q -f label=code_exec=1 -f status=exited | xargs -r docker rm -f

# 🔴 לא לעשות! זה יהרוג הרצות באמצע:
# docker ps -q -f label=code_exec=1 | xargs -r docker rm -f
```

או דרך ה-API (בטוח - מסנן רק `exited`):

```python
from services.code_execution_service import get_code_execution_service
service = get_code_execution_service()
cleaned = service.cleanup_orphan_containers()
print(f"Cleaned {cleaned} containers")
```

---

## 8. אבטחה ✅

### שכבות הגנה

| שכבה | מה עושה | איפה |
|------|---------|------|
| **Feature Flag** | מכבה את הפיצ'ר כברירת מחדל | `FEATURE_CODE_EXECUTION` |
| **Admin Check** | רק אדמינים (ברמת Blueprint) | `@code_tools_bp.before_request` |
| **Fail-Closed** | לא fallback ל-subprocess בפרודקשן | `CODE_EXEC_ALLOW_FALLBACK=false` |
| **Keyword Blocking** | חסימת פקודות מסוכנות | `BLOCKED_KEYWORDS` |
| **Code Length** | הגבלת אורך קוד | 50KB |
| **Docker Sandbox** | בידוד מלא | `--network=none`, `--read-only` |
| **tmpfs** | /tmp מבודד עם noexec | `--tmpfs=/tmp:rw,noexec,nosuid,size=10m` |
| **Resource Limits** | הגבלת CPU/Memory/PIDs | `--memory`, `--cpus`, `--pids-limit` |
| **IPC Isolation** | בידוד IPC | `--ipc=none` |
| **Timeout** | מניעת infinite loops | 5-30 שניות |
| **Container Cleanup** | ניקוי קונטיינרים יתומים | `--name` + `--label` + cleanup |
| **Output Limit** | מניעת memory bomb | 100KB |
| **Popen + Polling** | ניטור בזמן אמת | `os.fstat()` + `process.kill()` |
| **Disk Protection** | עצירה לפני מילוי דיסק | בדיקת גודל כל 50ms |
| **No Privileges** | הרצה כ-nobody | `--user=nobody`, `--cap-drop=ALL` |

### Flags מלאים של Docker

```bash
docker run \
  --rm \
  --name=code-exec-<uuid> \
  --label=code_exec=1 \
  --network=none \
  --read-only \
  --tmpfs=/tmp:rw,noexec,nosuid,size=10m \
  --memory=128m \
  --memory-swap=128m \
  --cpus=0.5 \
  --pids-limit=50 \
  --ipc=none \
  --security-opt=no-new-privileges \
  --cap-drop=ALL \
  --user=nobody \
  python:3.11-slim \
  python -c "<code>"
```

### הקשחה נוספת (אופציונלי)

למי שרוצה אבטחה מקסימלית:

```bash
# Seccomp profile (מגביל syscalls)
--security-opt=seccomp=/path/to/seccomp-profile.json

# AppArmor profile (Linux)
--security-opt=apparmor=docker-code-exec

# Ulimits נוספים
--ulimit nproc=50:50
--ulimit nofile=100:100
```

### מה **לא** לעשות

❌ **אל תפעיל `CODE_EXEC_ALLOW_FALLBACK=true` בפרודקשן** – subprocess לא בטוח  
❌ **אל תעשה mount ל-docker.sock** אם אפשר להימנע (סיכון root)  
❌ **אל תשתמש ב-`capture_output=True`** – מאפשר OOM מפלט אינסופי  
❌ **אל תשתמש ב-`subprocess.run` לתהליכים ארוכים** – לא מאפשר ניטור בזמן אמת  
❌ **אל תנקה קונטיינרים `running`** – רק `exited` (Race Condition!)  
❌ אל תעלה את ה-timeout מעל 30 שניות  
❌ אל תאפשר גישה לרשת מתוך הקונטיינר  
❌ **אל תלוגג קוד או stdout/stderr** – עלולים להכיל סודות  
❌ אל תשמור קוד משתמשים ללא הצפנה  

### Logging – מה כן ומה לא

```python
# ✅ כן – מטא-דאטה בלבד
logger.info(
    "Code execution: docker=%s exit=%s time=%dms truncated=%s",
    used_docker, exit_code, execution_time_ms, truncated
)

# ❌ לא – לעולם לא לוגגים קוד או פלט
logger.info(f"Code: {code}")      # אסור!
logger.info(f"Output: {stdout}")  # אסור!
```

### Fail-Closed vs Fail-Open

```
Fail-Closed (ברירת מחדל):
  Docker לא זמין? → מחזירים שגיאה
  ENV: CODE_EXEC_ALLOW_FALLBACK=false
  
Fail-Open (לפיתוח בלבד):
  Docker לא זמין? → subprocess fallback
  ENV: CODE_EXEC_ALLOW_FALLBACK=true
```

### הגנה על RAM ו-Disk – Popen + Polling

**בעיה 1: `capture_output=True` → OOM (RAM)**
```python
# 🔴 מסוכן - טוען את כל הפלט ל-RAM
result = subprocess.run(cmd, capture_output=True)
# while True: print("x") → GB ב-RAM → OOM Kill
```

**בעיה 2: `subprocess.run` + TempFile → Disk Full**
```python
# 🔴 עדיין מסוכן - הדיסק יכול להתמלא
with tempfile.TemporaryFile() as f:
    subprocess.run(cmd, stdout=f)  # מחכה עד הסוף!
    # while True: print("x") → GB בדיסק לפני שנבדוק
```

**הפתרון: Popen + Polling בזמן אמת**
```python
# ✅ בטוח - מנטר ועוצר בזמן אמת
with tempfile.TemporaryFile() as stdout_f:
    process = subprocess.Popen(cmd, stdout=stdout_f)
    
    while process.poll() is None:
        # בדיקת גודל קובץ בזמן אמת
        size = os.fstat(stdout_f.fileno()).st_size
        if size > MAX_OUTPUT_BYTES:
            process.kill()  # עוצר מיד!
            break
        time.sleep(0.05)
    
    stdout_f.seek(0)
    raw = stdout_f.read(MAX_OUTPUT_BYTES)
```

**יתרונות:**
- RAM: הפלט בדיסק, לא בזיכרון
- Disk: עוצרים את התהליך לפני שהדיסק מתמלא
- Time: טיפול ב-timeout בלולאה אותה

---

### Defense in Depth – הגנה כפולה

הקוד מיישם **שתי שכבות הגנה** נגד הרצה לא מאובטחת:

```
שכבה 1: can_execute()
  └─ בודק: docker_required && !docker_available && !allow_fallback
  └─ נקרא לפני execute()
  └─ מחזיר (False, "Docker לא זמין...")

שכבה 2: בתוך execute()
  └─ if use_docker: _execute_docker()
  └─ elif _allow_fallback: _execute_subprocess()  ← רק אם מותר!
  └─ else: return error  ← הגנה לעומק
```

**למה צריך את שתי השכבות?**

אם מישהו בטעות קורא ל-`execute()` ישירות בלי `can_execute()`,
או אם יש באג בלוגיקה של `can_execute()`, השכבה הפנימית עדיין תגן.

זה עיקרון **Defense in Depth** – לעולם לא לסמוך על בדיקה אחת בלבד.

---

## 9. בדיקות (Tests)

### קובץ: `tests/test_code_execution_service.py`

> **הערה:** הטסטים מותאמים לקונבנציות הקיימות בפרויקט:
> - שימוש ב-`monkeypatch` להגדרת ENV
> - מימוש ה-execution ב-mock (לא באמת להריץ Docker בטסטים יחידה)
> - שימוש ב-`reset_service_instance()` לאיפוס ה-singleton

```python
"""Unit tests for CodeExecutionService."""

from unittest.mock import MagicMock, patch
import pytest
import os

from services.code_execution_service import (
    CodeExecutionService,
    ExecutionResult,
    get_code_execution_service,
    reset_service_instance,
)


class TestCodeExecutionService:
    """Test suite for CodeExecutionService."""

    def setup_method(self):
        """Setup test instance with fallback allowed."""
        reset_service_instance()  # איפוס singleton
        
    def teardown_method(self):
        """Cleanup after each test."""
        reset_service_instance()

    @pytest.fixture
    def service_no_docker(self, monkeypatch):
        """Service configured for subprocess fallback."""
        monkeypatch.setenv("CODE_EXEC_USE_DOCKER", "false")
        monkeypatch.setenv("CODE_EXEC_ALLOW_FALLBACK", "true")
        return CodeExecutionService()

    @pytest.fixture
    def service_docker_required(self, monkeypatch):
        """Service configured to require Docker (fail-closed)."""
        monkeypatch.setenv("CODE_EXEC_USE_DOCKER", "true")
        monkeypatch.setenv("CODE_EXEC_ALLOW_FALLBACK", "false")
        return CodeExecutionService()

    def test_validate_empty_code(self, service_no_docker):
        """Empty code should fail validation."""
        is_valid, error = service_no_docker.validate_code("")
        assert is_valid is False
        assert "ריק" in error

    def test_validate_blocked_keywords(self, service_no_docker):
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
            is_valid, error = service_no_docker.validate_code(code)
            assert is_valid is False, f"Should block: {code}"
            assert "לא מורשית" in error

    def test_validate_safe_code(self, service_no_docker):
        """Safe code should pass validation."""
        safe_codes = [
            "print('hello')",
            "x = 1 + 2",
            "import math\nprint(math.pi)",
            "for i in range(10): print(i)",
        ]
        
        for code in safe_codes:
            is_valid, error = service_no_docker.validate_code(code)
            assert is_valid is True, f"Should allow: {code}"
            assert error is None

    def test_validate_code_too_long(self, service_no_docker):
        """Code exceeding max length should fail."""
        long_code = "x = 1\n" * 100000
        is_valid, error = service_no_docker.validate_code(long_code)
        assert is_valid is False
        assert "ארוך" in error

    def test_fail_closed_without_docker(self, service_docker_required):
        """Without Docker and fallback=false, should fail at can_execute."""
        # מדמה מצב שאין Docker
        service_docker_required._docker_available = False
        
        can_exec, error = service_docker_required.can_execute()
        assert can_exec is False
        assert "Docker לא זמין" in error

    def test_fail_closed_defense_in_depth(self, monkeypatch):
        """
        Defense in depth: even if can_execute is bypassed,
        execute() should not fall back to subprocess when fallback=false.
        """
        monkeypatch.setenv("CODE_EXEC_USE_DOCKER", "true")
        monkeypatch.setenv("CODE_EXEC_ALLOW_FALLBACK", "false")
        
        service = CodeExecutionService()
        service._docker_available = False  # Simulate Docker failure
        
        # הקריאה ישירות ל-execute (כאילו can_execute עבר)
        # אפילו אם מישהו עקף את can_execute, ההגנה הפנימית צריכה לעבוד
        result = service.execute("print('should not run')")
        
        assert result.success is False
        assert "חסומה" in result.error_message or "Docker" in result.error_message
        assert result.used_docker is False

    def test_can_execute_docker_disabled_no_fallback(self, monkeypatch):
        """
        can_execute should return False when Docker is explicitly disabled
        and fallback is not allowed.
        """
        monkeypatch.setenv("CODE_EXEC_USE_DOCKER", "false")
        monkeypatch.setenv("CODE_EXEC_ALLOW_FALLBACK", "false")
        
        service = CodeExecutionService()
        can_exec, error = service.can_execute()
        
        assert can_exec is False
        assert "מושבתת" in error or "כבוי" in error

    def test_can_execute_docker_disabled_with_fallback(self, monkeypatch):
        """
        can_execute should return True when Docker is disabled
        but fallback is allowed.
        """
        monkeypatch.setenv("CODE_EXEC_USE_DOCKER", "false")
        monkeypatch.setenv("CODE_EXEC_ALLOW_FALLBACK", "true")
        
        service = CodeExecutionService()
        can_exec, error = service.can_execute()
        
        assert can_exec is True
        assert error is None

    @patch('subprocess.run')
    def test_execute_simple_code_mocked(self, mock_run, service_no_docker):
        """Test simple code execution with mocked subprocess."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=b"Hello World\n",
            stderr=b"",
        )
        
        result = service_no_docker.execute("print('Hello World')")
        
        assert result.success is True
        assert "Hello World" in result.stdout
        assert result.exit_code == 0

    @patch('subprocess.run')
    def test_execute_with_error_mocked(self, mock_run, service_no_docker):
        """Test code that raises an error with mocked subprocess."""
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout=b"",
            stderr=b"NameError: name 'x' is not defined\n",
        )
        
        result = service_no_docker.execute("print(x)")
        
        assert result.success is False
        assert "NameError" in result.stderr
        assert result.exit_code == 1

    @patch('subprocess.run')
    def test_execute_timeout_mocked(self, mock_run, service_no_docker):
        """Test timeout handling with mocked subprocess."""
        from subprocess import TimeoutExpired
        mock_run.side_effect = TimeoutExpired(cmd="python", timeout=5)
        
        result = service_no_docker.execute("while True: pass")
        
        assert result.success is False
        assert "תם הזמן" in result.error_message

    def test_sanitize_output_truncation(self, service_no_docker):
        """Long output should be truncated."""
        long_output = "x" * 200000
        sanitized, truncated = service_no_docker._sanitize_output(long_output)
        
        assert truncated is True
        assert len(sanitized) <= service_no_docker._max_output_bytes + 50
        assert "קוצץ" in sanitized

    def test_get_limits(self, service_no_docker):
        """Test limits getter."""
        limits = service_no_docker.get_limits()
        
        assert "max_timeout_seconds" in limits
        assert "max_memory_mb" in limits
        assert "docker_available" in limits
        assert "docker_required" in limits
        assert "fallback_allowed" in limits

    def test_get_allowed_imports(self, service_no_docker):
        """Test allowed imports list."""
        imports = service_no_docker.get_allowed_imports()
        
        assert "math" in imports
        assert "random" in imports
        assert "os" not in imports
    
    def test_env_config_respected(self, monkeypatch):
        """Test that ENV variables are respected."""
        monkeypatch.setenv("CODE_EXEC_MAX_TIMEOUT", "15")
        monkeypatch.setenv("CODE_EXEC_MAX_MEMORY_MB", "64")
        monkeypatch.setenv("CODE_EXEC_DOCKER_IMAGE", "python:3.10-slim")
        
        service = CodeExecutionService()
        limits = service.get_limits()
        
        assert limits["max_timeout_seconds"] == 15
        assert limits["max_memory_mb"] == 64
        assert service._docker_image == "python:3.10-slim"


class TestDockerExecution:
    """
    Integration tests for Docker-based execution.
    Skip if Docker is not available.
    """

    @pytest.fixture
    def docker_service(self, monkeypatch):
        """Service with Docker enabled."""
        monkeypatch.setenv("CODE_EXEC_USE_DOCKER", "true")
        monkeypatch.setenv("CODE_EXEC_ALLOW_FALLBACK", "false")
        service = CodeExecutionService()
        if not service.is_docker_available():
            pytest.skip("Docker not available")
        return service

    def test_docker_simple_execution(self, docker_service):
        """Test actual Docker execution."""
        result = docker_service.execute("print('Docker works!')")
        
        assert result.success is True
        assert "Docker works!" in result.stdout
        assert result.used_docker is True

    def test_docker_network_blocked(self, docker_service):
        """Network should be blocked in Docker."""
        result = docker_service.execute("""
import socket
try:
    socket.create_connection(("8.8.8.8", 53), timeout=1)
    print("NETWORK WORKS - BAD!")
except:
    print("Network blocked - Good!")
""")
        
        assert "blocked" in result.stdout.lower() or result.exit_code != 0


class TestAPIEndpoint:
    """
    Tests for the /api/code/run endpoint.
    Uses Flask test client with project conventions.
    """

    @pytest.fixture
    def client(self):
        """Flask test client."""
        import webapp.app as app_mod
        app_mod.app.config["TESTING"] = True
        return app_mod.app.test_client()

    @pytest.fixture
    def admin_session(self, client, monkeypatch):
        """Setup admin session."""
        admin_id = "12345"
        monkeypatch.setenv("ADMIN_USER_IDS", admin_id)
        monkeypatch.setenv("FEATURE_CODE_EXECUTION", "true")
        
        with client.session_transaction() as sess:
            sess["user_id"] = int(admin_id)
        
        return client

    def test_run_requires_auth(self, client):
        """Endpoint should require authentication."""
        response = client.post(
            '/api/code/run',
            json={"code": "print(1)"},
            content_type='application/json',
        )
        # 401 (not logged in) or 403 (not admin)
        assert response.status_code in (401, 403)

    def test_run_requires_feature_flag(self, client, monkeypatch):
        """Endpoint should check feature flag."""
        admin_id = "12345"
        monkeypatch.setenv("ADMIN_USER_IDS", admin_id)
        monkeypatch.setenv("FEATURE_CODE_EXECUTION", "false")  # disabled
        
        with client.session_transaction() as sess:
            sess["user_id"] = int(admin_id)
        
        response = client.post(
            '/api/code/run',
            json={"code": "print(1)"},
            content_type='application/json',
        )
        assert response.status_code == 403
        data = response.get_json()
        assert "מושבתת" in data.get("error", "")

    def test_run_requires_code(self, admin_session, monkeypatch):
        """Endpoint should require code parameter."""
        # Mock the execution to avoid actual run
        with patch('services.code_execution_service.CodeExecutionService.execute') as mock_exec:
            response = admin_session.post(
                '/api/code/run',
                json={},
                content_type='application/json',
            )
        
        assert response.status_code == 400
        data = response.get_json()
        assert "חסר קוד" in data.get("error", "")

    @patch('services.code_execution_service.CodeExecutionService.execute')
    def test_run_success(self, mock_execute, admin_session):
        """Test successful code execution."""
        mock_execute.return_value = ExecutionResult(
            success=True,
            stdout="42\n",
            stderr="",
            exit_code=0,
            execution_time_ms=50,
        )
        
        response = admin_session.post(
            '/api/code/run',
            json={"code": "print(42)"},
            content_type='application/json',
        )
        
        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        assert "42" in data["stdout"]
```

### הרצת הבדיקות

```bash
# Unit tests only (no Docker)
pytest tests/test_code_execution_service.py -v -k "not Docker"

# Full tests including Docker integration
pytest tests/test_code_execution_service.py -v

# With coverage
pytest tests/test_code_execution_service.py -v --cov=services.code_execution_service
```

---

## 10. צ'קליסט למימוש

### שלב 1: Backend

- [ ] יצירת `services/code_execution_service.py`
- [ ] הוספת endpoints ל-`webapp/code_tools_api.py`
- [ ] וידוא Docker image: `docker pull python:3.11-slim`
- [ ] הגדרת ENV:
  - [ ] `FEATURE_CODE_EXECUTION=true`
  - [ ] `CODE_EXEC_USE_DOCKER=true`
  - [ ] `CODE_EXEC_ALLOW_FALLBACK=false` (פרודקשן)

### שלב 2: Frontend

- [ ] עדכון `setViewMode()` להוסיף `output`
- [ ] הוספת כפתור Run ב-`webapp/templates/code_tools.html`
- [ ] הוספת tab "פלט" ב-view toggle
- [ ] הוספת `#output-view` ב-panel-body
- [ ] הוספת לוגיקת הרצה ל-`webapp/static/js/code-tools-page.js`
- [ ] הוספת CSS ל-`webapp/static/css/code-tools.css`

### שלב 3: בדיקות

- [ ] כתיבת unit tests (עם mock)
- [ ] כתיבת integration tests (עם Docker)
- [ ] הרצת `pytest tests/test_code_execution_service.py -v`

### שלב 4: אבטחה

- [ ] Review קוד - אין לוגים של קוד/פלט
- [ ] Review Docker flags - כל ההגנות קיימות
- [ ] בדיקה שאין fallback בפרודקשן
- [ ] בדיקה ידנית של blocked keywords
- [ ] בדיקת timeout עובד

### שלב 5: Deployment

- [ ] בדיקה בסביבת פיתוח
- [ ] Deploy לסביבת staging
- [ ] בדיקה ידנית ב-staging
- [ ] Deploy לפרודקשן
- [ ] הוספת cron לניקוי קונטיינרים (אופציונלי)

### שלב 6: תיעוד

- [ ] עדכון USER_GUIDE.md
- [ ] עדכון תיעוד API (אם יש)

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

---

## 15. היסטוריית עדכונים

| תאריך | שינוי |
|-------|-------|
| ינואר 2026 | גרסה ראשונית |
| ינואר 2026 | עדכון לפי code review: |
| | - הבהרה: Admin checks כבר קיימים ב-Blueprint |
| | - עדכון `setViewMode` להוסיף `output` |
| | - תיקון ניסוח "פלט בזמן אמת" ← "פלט אחרי סיום" |
| | - Fail-closed בפרודקשן (לא fallback) |
| | - אזהרה על docker.sock כסיכון root |
| | - Container cleanup עם `--name` ו-`--label` |
| | - הקשחת Docker: `--ipc=none`, `--tmpfs` |
| | - ENV נקרא בזמן `__init__` (לא global) |
| | - Logging: רק מטא-דאטה, לא קוד/פלט |
| | - טסטים מותאמים לקונבנציות הפרויקט |
| ינואר 2026 | **תיקון אבטחה קריטי (Fail-Closed):** |
| | - תיקון לוגיקת `execute()`: הוספת `elif self._allow_fallback` |
| | - הבטחה ש-subprocess לא ירוץ ללא אישור מפורש |
| | - הוספת הגנה לעומק (defense in depth) |
| | - הוספת טסט `test_fail_closed_defense_in_depth` |
| ינואר 2026 | **תיקוני אבטחה נוספים:** |
| | - תיקון `can_execute()`: לוגיקה חיובית (Whitelist) |
| | - הוספת כיסוי למצב Docker כבוי + Fallback אסור |
| | - **מניעת OOM**: שימוש ב-`tempfile` במקום `capture_output=True` |
| | - הגנה על זיכרון השרת מפלט אינסופי |
| | - טסטים: `test_can_execute_docker_disabled_*` |
| ינואר 2026 | **תיקון Race Condition ב-cleanup:** |
| | - הוספת `-a` ו-`status=exited` ל-`cleanup_orphan_containers()` |
| | - מונע הריגת קונטיינרים אקטיביים באמצע הרצה |
| | - עדכון פקודות cron לסינון בטוח |
| ינואר 2026 | **מניעת Disk Exhaustion:** |
| | - מעבר מ-`subprocess.run` ל-`subprocess.Popen` + polling |
| | - ניטור גודל קבצים בזמן אמת עם `os.fstat()` |
| | - עצירת תהליך מיידית אם פלט חורג מהמקסימום |
| | - הגנה על RAM, Disk ו-Time במקביל |
