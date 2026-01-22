"""
Code Execution Service
======================
שירות להרצת קוד Python בסביבה מבודדת (Docker Sandbox).

⚠️ אזהרת אבטחה: שירות זה מאפשר הרצת קוד שרירותי.
   יש להפעיל רק עם הגנות מתאימות (Docker, Resource Limits, Premium/Admin בלבד).

קונפיגורציה דרך ENV:
    FEATURE_CODE_EXECUTION=false     # Feature flag ברמת ה-API (לא בשירות)
    CODE_EXEC_USE_DOCKER=true        # שימוש ב-Docker (חובה בפרודקשן)
    CODE_EXEC_ALLOW_FALLBACK=false   # false = fail-closed (אין fallback בפרודקשן)
    CODE_EXEC_MAX_TIMEOUT=30         # מקסימום timeout בשניות
    CODE_EXEC_MAX_MEMORY_MB=128      # מקסימום זיכרון
    CODE_EXEC_MAX_OUTPUT_BYTES=102400  # פלט מקסימלי (bytes)
    CODE_EXEC_MAX_CODE_LENGTH=51200  # אורך קוד מקסימלי (bytes)
    CODE_EXEC_DOCKER_IMAGE=python:3.11-slim
    CODE_EXEC_DOCKER_PULL_TIMEOUT=60  # timeout להורדת image כשחסר
"""

from __future__ import annotations

import ast
import logging
import os
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

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
    return val.strip().lower() in ("true", "1", "yes", "on")


@dataclass
class ExecutionResult:
    """תוצאת הרצת קוד."""

    success: bool
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    execution_time_ms: int = 0
    error_message: Optional[str] = None
    truncated: bool = False
    used_docker: bool = False

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
    """

    # מילות מפתח חסומות (אבטחה בסיסית - לא מספיקה לבד!)
    BLOCKED_KEYWORDS: Tuple[str, ...] = (
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

    # מודולים מותרים (Allowlist)
    ALLOWED_IMPORTS: Tuple[str, ...] = (
        "math",
        "random",
        "time",
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

    def __init__(self) -> None:
        # קונפיגורציה נקראת בזמן init כדי לאפשר monkeypatch בטסטים
        self._use_docker = _get_env_bool("CODE_EXEC_USE_DOCKER", True)
        self._allow_fallback = _get_env_bool("CODE_EXEC_ALLOW_FALLBACK", False)
        self._max_timeout = _get_env_int("CODE_EXEC_MAX_TIMEOUT", 30)
        self._max_memory_mb = _get_env_int("CODE_EXEC_MAX_MEMORY_MB", 128)
        self._max_output_bytes = _get_env_int("CODE_EXEC_MAX_OUTPUT_BYTES", 100 * 1024)
        self._max_code_length = _get_env_int("CODE_EXEC_MAX_CODE_LENGTH", 50 * 1024)
        self._docker_image = os.environ.get("CODE_EXEC_DOCKER_IMAGE", "python:3.11-slim")
        self._docker_pull_timeout = max(5, _get_env_int("CODE_EXEC_DOCKER_PULL_TIMEOUT", 60))
        self._docker_image_ready = False

        self._docker_available = self._check_docker()

        # לוג קונפיגורציה - ללא קוד/פלט
        logger.info(
            "CodeExecutionService initialized: docker=%s, available=%s, fallback=%s",
            self._use_docker,
            self._docker_available,
            self._allow_fallback,
        )

    # -------------------- Availability --------------------

    def _check_docker(self) -> bool:
        """בדיקה האם Docker זמין."""
        try:
            result = subprocess.run(
                ["docker", "version"],
                capture_output=True,
                timeout=5,
                check=False,
            )
            return result.returncode == 0
        except (subprocess.SubprocessError, FileNotFoundError):
            return False

    def _ensure_docker_image(self) -> Optional[str]:
        """מוודא שה-image קיים מקומית כדי למנוע timeout בזמן הרצה."""
        if self._docker_image_ready:
            return None
        if not self._docker_image:
            return "לא הוגדר Docker image להרצת קוד"

        try:
            inspect = subprocess.run(
                ["docker", "image", "inspect", self._docker_image],
                capture_output=True,
                timeout=5,
                check=False,
            )
            if inspect.returncode == 0:
                self._docker_image_ready = True
                return None
        except (subprocess.SubprocessError, FileNotFoundError):
            return "Docker אינו זמין לבדיקת image"

        try:
            pull = subprocess.run(
                ["docker", "pull", self._docker_image],
                capture_output=True,
                timeout=self._docker_pull_timeout,
                check=False,
            )
            if pull.returncode != 0:
                stderr = pull.stderr.decode("utf-8", errors="replace").strip()
                if len(stderr) > 200:
                    stderr = stderr[:200].rstrip() + "..."
                if stderr:
                    return f"שגיאה בהורדת Docker image: {stderr}"
                return "שגיאה בהורדת Docker image"
        except subprocess.TimeoutExpired:
            return f"תם הזמן להורדת Docker image ({self._docker_pull_timeout} שניות)"
        except (subprocess.SubprocessError, FileNotFoundError):
            return "שגיאה בהורדת Docker image"

        self._docker_image_ready = True
        return None

    def is_docker_available(self) -> bool:
        return self._docker_available

    def can_execute(self) -> Tuple[bool, Optional[str]]:
        """
        בדיקה האם אפשר להריץ קוד כרגע (fail-closed).

        Returns:
            (can_execute, error_message)
        """
        if self._use_docker and self._docker_available:
            return True, None

        if self._allow_fallback:
            return True, None

        if self._use_docker and not self._docker_available:
            return False, "Docker מוגדר אך אינו זמין בשרת"

        return False, "הרצת קוד מושבתת (Docker כבוי ו-Fallback אסור)"

    # -------------------- Validation --------------------

    def validate_code(self, code: str) -> Tuple[bool, Optional[str]]:
        """בדיקת תקינות קוד לפני הרצה (אורך, תווים, Blocklist + AST Allowlist)."""
        if not code or not str(code).strip():
            return False, "הקוד ריק"

        if len(code) > self._max_code_length:
            return False, f"הקוד ארוך מדי (מקסימום {self._max_code_length // 1024}KB)"

        try:
            code.encode("utf-8")
        except UnicodeEncodeError:
            return False, "קידוד תווים לא תקין"

        # 1) Blocklist מהירה על הטקסט
        code_lower = code.lower()
        for keyword in self.BLOCKED_KEYWORDS:
            if keyword.lower() in code_lower:
                return False, f"הקוד מכיל ביטוי אסור: {keyword}"

        # 2) AST Allowlist imports
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return False, f"שגיאת תחביר (Syntax Error): {e}"

        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                module_names: List[str] = []

                if isinstance(node, ast.Import):
                    module_names = [alias.name.split(".")[0] for alias in node.names]
                else:
                    if node.module:
                        module_names = [node.module.split(".")[0]]

                for mod in module_names:
                    if mod not in self.ALLOWED_IMPORTS:
                        allowed_str = ", ".join(sorted(self.ALLOWED_IMPORTS))
                        return False, f"המודול '{mod}' אינו מורשה. מודולים מותרים: {allowed_str}"

        return True, None

    def _sanitize_output(self, output: str) -> Tuple[str, bool]:
        """ניקוי וקיצוץ פלט לפי max bytes."""
        if not output:
            return "", False

        try:
            output = output.encode("utf-8", errors="replace").decode("utf-8")
        except Exception:
            output = str(output)

        truncated = len(output) > self._max_output_bytes
        if truncated:
            output = output[: self._max_output_bytes] + "\n... (הפלט קוצץ)"

        return output, truncated

    # -------------------- Execution --------------------

    def execute(self, code: str, timeout: int = 5, memory_limit_mb: int = 128) -> ExecutionResult:
        """
        הרצת קוד Python.

        ⚠️ לא ללוגג את הקוד או הפלט.
        """
        can_exec, exec_error = self.can_execute()
        if not can_exec:
            return ExecutionResult(success=False, error_message=exec_error, exit_code=-1)

        is_valid, error = self.validate_code(code)
        if not is_valid:
            return ExecutionResult(success=False, error_message=error, exit_code=-1)

        timeout = min(max(1, int(timeout)), self._max_timeout)
        memory_limit_mb = min(max(32, int(memory_limit_mb)), self._max_memory_mb)

        use_docker = self._use_docker and self._docker_available
        if use_docker:
            image_error = self._ensure_docker_image()
            if image_error:
                return ExecutionResult(
                    success=False,
                    error_message=image_error,
                    exit_code=-1,
                    used_docker=True,
                )

        start_time = time.monotonic()

        try:
            if use_docker:
                result = self._execute_docker(code, timeout, memory_limit_mb)
            elif self._allow_fallback:
                result = self._execute_subprocess(code, timeout)
            else:
                # defense-in-depth: לא אמור לקרות כי can_execute() תופס,
                # אבל שומרים fail-closed גם אם קראו ישירות ל-execute()
                logger.error(
                    "Code execution blocked: docker=%s available=%s fallback=%s",
                    self._use_docker,
                    self._docker_available,
                    self._allow_fallback,
                )
                return ExecutionResult(
                    success=False,
                    error_message="תצורת שרת שגויה: הרצה ללא Docker חסומה",
                    exit_code=-1,
                    used_docker=False,
                )

            result.execution_time_ms = int((time.monotonic() - start_time) * 1000)
            result.used_docker = use_docker

            # לוג מטא-דאטה בלבד
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
                exit_code=-1,
            )
        except Exception as e:
            # לא מלוגגים את החריגה המלאה (עלולה להדליף קלט)
            logger.error("Code execution error: %s", type(e).__name__)
            return ExecutionResult(
                success=False,
                error_message=f"שגיאה בהרצה: {type(e).__name__}",
                exit_code=-1,
            )

    def _execute_docker(self, code: str, timeout: int, memory_limit_mb: int) -> ExecutionResult:
        """
        הרצה בתוך Docker container עם הגנות מלאות (לפי המדריך).
        """
        container_name = f"code-exec-{uuid.uuid4().hex[:12]}"

        # נכתוב את הקוד לקובץ זמני ונמפה אותו ל-container כדי להימנע מהעברת הקוד כארגומנט שורת פקודה
        with tempfile.TemporaryDirectory() as code_dir:
            # חשוב: TemporaryDirectory נוצר כברירת מחדל עם הרשאות 0700.
            # מאחר שאנחנו מריצים את הקונטיינר עם --user=nobody, חייבים לאפשר קריאה/גישה לתיקייה ולקובץ.
            try:
                os.chmod(code_dir, 0o755)
            except Exception:
                return ExecutionResult(
                    success=False,
                    error_message="שגיאה בהכנת הרשאות לתיקיית הקוד להרצה",
                    exit_code=-1,
                )

            code_path = os.path.join(code_dir, "main.py")
            try:
                with open(code_path, "w", encoding="utf-8") as code_file:
                    code_file.write(code)
                # לאפשר ל-nobody לקרוא את הקובץ בתוך ה-mount
                try:
                    os.chmod(code_path, 0o644)
                except Exception:
                    return ExecutionResult(
                        success=False,
                        error_message="שגיאה בהכנת הרשאות לקובץ הקוד להרצה",
                        exit_code=-1,
                    )
            except Exception:
                # במקרה של כשל בכתיבה לדיסק נחזיר שגיאה בטוחה
                return ExecutionResult(
                    success=False,
                    error_message="שגיאה בהכנת קובץ הקוד להרצה",
                    exit_code=-1,
                )

            docker_cmd = [
                "docker",
                "run",
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
                "-v",
                f"{code_dir}:/app:ro",
                self._docker_image,
                "python",
                "/app/main.py",
            ]

            with tempfile.TemporaryFile() as stdout_f, tempfile.TemporaryFile() as stderr_f:
                started = time.monotonic()
                process = subprocess.Popen(docker_cmd, stdout=stdout_f, stderr=stderr_f)

                exit_code: Optional[int] = None
                output_truncated = False
                error_msg: Optional[str] = None

                while True:
                    exit_code = process.poll()
                    if exit_code is not None:
                        break

                    elapsed = time.monotonic() - started
                    # לפי המדריך: timeout + גרייס קצר ל-overhead של Docker
                    if elapsed > (timeout + 2):
                        process.kill()
                        process.wait()
                        self._cleanup_container(container_name)
                        error_msg = f"תם הזמן להרצה ({timeout} שניות)"
                        break

                    try:
                        out_size = os.fstat(stdout_f.fileno()).st_size
                        err_size = os.fstat(stderr_f.fileno()).st_size
                    except OSError:
                        out_size = 0
                        err_size = 0

                    if out_size > self._max_output_bytes or err_size > self._max_output_bytes:
                        process.kill()
                        process.wait()
                        self._cleanup_container(container_name)
                        output_truncated = True
                        logger.warning(
                            "Output limit exceeded: stdout=%d stderr=%d max=%d",
                            out_size,
                            err_size,
                            self._max_output_bytes,
                        )
                        break

                    time.sleep(0.05)

                stdout_f.seek(0)
                stderr_f.seek(0)
                read_limit = self._max_output_bytes + 100
                stdout_str = stdout_f.read(read_limit).decode("utf-8", errors="replace")
                stderr_str = stderr_f.read(read_limit).decode("utf-8", errors="replace")

        stdout, out_trunc = self._sanitize_output(stdout_str)
        stderr, err_trunc = self._sanitize_output(stderr_str)

        final_exit = exit_code if exit_code is not None else -1
        success = (final_exit == 0) and (error_msg is None) and not output_truncated

        return ExecutionResult(
            success=success,
            stdout=stdout,
            stderr=stderr,
            exit_code=final_exit,
            truncated=output_truncated or out_trunc or err_trunc,
            error_message=error_msg,
            used_docker=True,
        )

    def _execute_subprocess(self, code: str, timeout: int) -> ExecutionResult:
        """
        הרצה ב-subprocess (לפיתוח בלבד).
        """
        logger.warning("Executing code via subprocess (fallback mode)")

        with tempfile.TemporaryFile() as stdout_f, tempfile.TemporaryFile() as stderr_f:
            started = time.monotonic()
            process = subprocess.Popen(
                [sys.executable, "-c", code],
                stdout=stdout_f,
                stderr=stderr_f,
                env={
                    "PATH": "/usr/bin:/bin",
                    "PYTHONDONTWRITEBYTECODE": "1",
                },
            )

            exit_code: Optional[int] = None
            output_truncated = False
            error_msg: Optional[str] = None

            while True:
                exit_code = process.poll()
                if exit_code is not None:
                    break

                elapsed = time.monotonic() - started
                if elapsed > timeout:
                    process.kill()
                    process.wait()
                    error_msg = f"תם הזמן להרצה ({timeout} שניות)"
                    break

                try:
                    out_size = os.fstat(stdout_f.fileno()).st_size
                    err_size = os.fstat(stderr_f.fileno()).st_size
                except OSError:
                    out_size = 0
                    err_size = 0

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

        final_exit = exit_code if exit_code is not None else -1
        success = (final_exit == 0) and (error_msg is None) and not output_truncated

        return ExecutionResult(
            success=success,
            stdout=stdout,
            stderr=stderr,
            exit_code=final_exit,
            truncated=output_truncated or out_trunc or err_trunc,
            error_message=error_msg,
            used_docker=False,
        )

    # -------------------- Cleanup --------------------

    def _cleanup_container(self, container_name: str) -> None:
        """ניקוי קונטיינר יתום (best-effort)."""
        try:
            subprocess.run(
                ["docker", "rm", "-f", container_name],
                capture_output=True,
                timeout=5,
                check=False,
            )
            logger.info("Cleaned up container: %s", container_name)
        except Exception:
            # best-effort
            return

    def cleanup_orphan_containers(self) -> int:
        """
        ניקוי קונטיינרים יתומים שסיימו (status=exited) ומסומנים עם label.
        """
        try:
            cmd = [
                "docker",
                "ps",
                "-a",
                "-q",
                "-f",
                f"label={self.CONTAINER_LABEL}",
                "-f",
                "status=exited",
            ]
            result = subprocess.run(cmd, capture_output=True, timeout=10, check=False)
            container_ids = result.stdout.decode().strip().split()

            count = 0
            for cid in container_ids:
                if not cid:
                    continue
                subprocess.run(["docker", "rm", "-f", cid], capture_output=True, timeout=5, check=False)
                count += 1

            if count > 0:
                logger.info("Cleaned up %d orphan (exited) containers", count)
            return count
        except Exception:
            logger.warning("Failed to cleanup orphan containers")
            return 0

    # -------------------- Info --------------------

    def get_allowed_imports(self) -> List[str]:
        return list(self.ALLOWED_IMPORTS)

    def get_limits(self) -> Dict[str, Any]:
        return {
            "max_timeout_seconds": self._max_timeout,
            "max_memory_mb": self._max_memory_mb,
            "max_code_length_bytes": self._max_code_length,
            "max_output_bytes": self._max_output_bytes,
            "docker_available": self._docker_available,
            "docker_required": self._use_docker,
            "fallback_allowed": self._allow_fallback,
            "docker_image": self._docker_image,
            "docker_pull_timeout_seconds": self._docker_pull_timeout,
        }


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

