"""
Git Mirror Service - ניהול מראה Git מקומי על Render Disk

מספק:
- יצירת mirror ראשוני
- fetch עדכונים (delta)
- קריאת תוכן קבצים
- השוואת commits
- חיפוש עם git grep
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

# הגדרות קבועות
MAX_DIFF_BYTES = 1 * 1024 * 1024  # 1MB
MAX_DIFF_LINES = 10000
MAX_FILE_SIZE_FOR_DISPLAY = 500 * 1024  # 500KB


@dataclass
class GitCommandResult:
    """תוצאת פקודת Git"""

    success: bool
    stdout: str
    stderr: str
    return_code: int


@dataclass
class FileChange:
    """שינוי בקובץ"""

    status: str  # A=added, M=modified, D=deleted, R=renamed
    path: str
    old_path: Optional[str] = None  # למקרה של rename


class GitMirrorService:
    """
    שירות לניהול Git Mirror על Render Disk

    שימוש:
        service = GitMirrorService()
        service.init_mirror("https://github.com/user/repo.git", "repo")
        service.fetch_updates("repo")
        content = service.get_file_content("repo", "src/main.py")

    תמיכה ב-Private Repos:
        הגדר GITHUB_TOKEN בסביבה, והשירות יזריק אותו אוטומטית ל-URL.
    """

    # שם ריפו: a-z, 0-9, -, _ בלבד, 1-100 תווים
    REPO_NAME_PATTERN = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9_-]{0,99}$')

    # נתיב קובץ - ללא path traversal
    # מאפשר: a-z, A-Z, 0-9, ., _, -, /
    # אוסר: //, leading/trailing /, NUL
    # הערה: בדיקת ".." כקומפוננטה נעשית ב-_validate_repo_file_path
    #        עם os.path.normpath (לא כאן, כי a..b.txt הוא שם קובץ תקין)
    FILE_PATH_PATTERN = re.compile(
        r'^(?!.*//)'              # No //
        r'(?!/)'                 # No leading /
        r'(?!-)'                 # No leading '-' (avoid git flags)
        r'(?!.*\x00)'            # No NUL
        r'[a-zA-Z0-9._/-]+'      # Allowed chars
        r'(?<!/)'                # No trailing /
        r'$'
    )

    # Basic ref pattern - לבדיקה מקדימה בלבד
    # הבדיקה האמיתית נעשית עם git rev-parse
    BASIC_REF_PATTERN = re.compile(
        r'^[a-zA-Z0-9][a-zA-Z0-9._/^~-]{0,150}$'
    )

    _GITHUB_HTTPS_RE = re.compile(r"^https://github\.com/[^/\s]+/[^/\s]+(?:\.git)?/?$", re.IGNORECASE)
    _GITHUB_SSH_RE = re.compile(r"^git@github\.com:[^/\s]+/[^/\s]+(?:\.git)?$", re.IGNORECASE)

    def __init__(
        self,
        base_path: Optional[str] = None,
        mirrors_base_path: Optional[str] = None,
        github_token: Optional[str] = None,
    ):
        """
        Args:
            base_path: נתיב בסיסי לאחסון mirrors.
                       ברירת מחדל: REPO_MIRROR_PATH או /var/data/repos
        """
        self.base_path = Path(mirrors_base_path or base_path or os.getenv("REPO_MIRROR_PATH", "/var/data/repos"))
        self.github_token = github_token
        self.logger = logger
        self._ensure_base_path()

        # הגבלות best-effort כדי להקשיח הרצת subprocess מול קלט משתמש
        self._allowed_git_subcommands: Set[str] = {
            "clone",
            "fetch",
            "rev-parse",
            "diff-tree",
            "show",
            "ls-tree",
            "grep",
            "log",
            "rev-list",
        }

    def _validate_repo_name(self, name: str) -> bool:
        """וולידציה של שם ריפו."""
        if not name or not isinstance(name, str):
            return False
        if '\x00' in name:
            return False
        return bool(self.REPO_NAME_PATTERN.match(name))

    def _validate_repo_url(self, repo_url: str) -> bool:
        """ולידציה ל-URL ריפו. כרגע תומך ב-GitHub בלבד (תואם token injection)."""
        if not isinstance(repo_url, str):
            return False
        url = repo_url.strip()
        if not url:
            return False
        if len(url) > 2048:
            return False
        if "\x00" in url:
            return False
        if any(ch.isspace() for ch in url):
            return False
        if url.startswith("-"):
            return False
        return bool(self._GITHUB_HTTPS_RE.fullmatch(url) or self._GITHUB_SSH_RE.fullmatch(url))

    def _get_authenticated_url(self, url: str) -> str:
        """
        הזרקת GitHub Token ל-URL לתמיכה ב-Private Repos

        Args:
            url: URL מקורי של הריפו

        Returns:
            URL עם token (אם קיים) או URL מקורי

        Note:
            לא לרשום את ה-URL המאומת ללוגים!
        """
        token = self.github_token or os.getenv("GITHUB_TOKEN")

        if not token:
            return url

        # תמיכה ב-HTTPS URLs בלבד
        if url.startswith("https://github.com/"):
            # https://github.com/user/repo.git
            # -> https://oauth2:TOKEN@github.com/user/repo.git
            return url.replace("https://github.com/", f"https://oauth2:{token}@github.com/")
        elif url.startswith("https://"):
            # Generic HTTPS URL
            return url.replace("https://", f"https://oauth2:{token}@")

        return url

    def _sanitize_output(self, output: str) -> str:
        """הסרת מידע רגיש מפלט Git."""
        if not output:
            return ''
        # Remove tokens from URLs without regex-heavy parsing
        sanitized_parts: List[str] = []
        text = str(output)
        needle = "https://"
        i = 0
        n = len(text)
        while True:
            j = text.find(needle, i)
            if j == -1:
                sanitized_parts.append(text[i:])
                break
            sanitized_parts.append(text[i:j])
            k = j + len(needle)

            max_end = min(n, k + 2048)
            segment_end = max_end
            for ch in (" ", "\n", "\r", "\t"):
                p = text.find(ch, k, max_end)
                if p != -1 and p < segment_end:
                    segment_end = p
            slash_pos = text.find("/", k, segment_end)
            if slash_pos == -1:
                slash_pos = segment_end

            at_pos = text.find("@", k, slash_pos)
            if at_pos != -1:
                colon_pos = text.find(":", k, at_pos)
                if colon_pos != -1:
                    # Keep username, mask secret
                    sanitized_parts.append(needle)
                    sanitized_parts.append(text[k:colon_pos + 1])
                    sanitized_parts.append("***@")
                    i = at_pos + 1
                    continue

            sanitized_parts.append(needle)
            i = k

        sanitized = "".join(sanitized_parts)
        # Remove other potential secrets
        sanitized = re.sub(
            r'(token|password|secret|key)[\s]*[=:][\s]*[^\s]+',
            r'\1=***',
            sanitized,
            flags=re.IGNORECASE
        )
        return sanitized

    def _ensure_base_path(self) -> None:
        """יצירת תיקיית הבסיס אם לא קיימת"""
        try:
            self.base_path.mkdir(parents=True, exist_ok=True)
            logger.info(f"Mirror base path ready: {self.base_path}")
        except PermissionError:
            logger.error(f"Cannot create mirror path: {self.base_path}")
            raise

    def _get_repo_path(self, repo_name: str) -> Path:
        """נתיב ל-mirror של ריפו ספציפי"""
        return self.base_path / f"{repo_name}.git"

    def _get_mirror_path(self, repo_name: str) -> Path:
        """Alias לשם אחיד במדריך (mirror path)."""
        return self._get_repo_path(repo_name)

    def _is_valid_mirror(self, repo_path: Path) -> bool:
        """בדיקה שהספרייה היא bare git repository תקין (best-effort)."""
        try:
            result = self._run_git_command(["git", "rev-parse", "--is-bare-repository"], cwd=repo_path, timeout=10)
            return bool(result.success and result.stdout.strip().lower() == "true")
        except Exception:
            return False

    def _safe_rmtree(self, path: Path) -> bool:
        """מחיקה בטוחה של נתיב mirror (מוגבל תחת base_path בלבד)."""
        try:
            p = path.resolve()
            base = self.base_path.resolve()
        except Exception:
            return False

        # לעולם לא למחוק נתיבים מסוכנים
        if str(p) in {"/", "."}:
            return False
        try:
            if p == base or p == Path.cwd().resolve():
                return False
        except Exception:
            pass

        # חייב להיות תחת base_path
        try:
            if not str(p).startswith(str(base) + os.sep):
                return False
        except Exception:
            return False

        try:
            shutil.rmtree(p)
            return True
        except Exception:
            return False

    def _run_git_command(self, cmd: List[str], cwd: Optional[Path] = None, timeout: int = 60) -> GitCommandResult:
        """
        הרצת פקודת Git בצורה בטוחה

        Args:
            cmd: פקודת Git כרשימה
            cwd: תיקיית עבודה
            timeout: timeout בשניות

        Returns:
            GitCommandResult עם התוצאות

        Note:
            stdout/stderr מנוקים מטוקנים רגישים!
        """
        try:
            # hardening: לא מאפשרים להריץ פקודה שאינה git או תת-פקודה לא צפויה
            if not isinstance(cmd, list) or not cmd:
                return GitCommandResult(success=False, stdout="", stderr="Invalid git command", return_code=-2)
            if cmd[0] != "git":
                return GitCommandResult(success=False, stdout="", stderr="Refusing to run non-git command", return_code=-2)
            if len(cmd) < 2 or cmd[1] not in self._allowed_git_subcommands:
                return GitCommandResult(success=False, stdout="", stderr="Unsupported git subcommand", return_code=-2)
            if any("\x00" in str(part) for part in cmd):
                return GitCommandResult(success=False, stdout="", stderr="Invalid NUL in command", return_code=-2)

            result = subprocess.run(
                cmd,
                cwd=str(cwd) if cwd else None,
                capture_output=True,
                text=True,
                timeout=timeout,
            )

            success = result.returncode == 0

            # ניקוי טוקנים מהפלט וגם מהפקודה! (אבטחה קריטית!)
            safe_stdout = self._sanitize_output(result.stdout)
            safe_stderr = self._sanitize_output(result.stderr)
            safe_cmd = self._sanitize_output(" ".join(cmd))  # הפקודה יכולה להכיל את ה-URL עם הטוקן!

            if not success:
                # לוג מנוקה - גם הפקודה מנוקה מטוקנים
                logger.warning(
                    f"Git command returned {result.returncode}: " f"{safe_cmd}\nstderr: {safe_stderr[:500]}"
                )

            return GitCommandResult(
                success=success,
                stdout=safe_stdout,  # פלט נקי
                stderr=safe_stderr,  # שגיאה נקייה
                return_code=result.returncode,
            )

        except subprocess.TimeoutExpired:
            # גם כאן חובה לנקות את הפקודה לפני הלוג!
            safe_cmd = self._sanitize_output(" ".join(cmd))
            logger.error(f"Git command timeout ({timeout}s): {safe_cmd}")
            return GitCommandResult(
                success=False,
                stdout="",
                stderr=f"Command timed out after {timeout}s",
                return_code=-1,
            )

        except Exception as e:
            safe_cmd = self._sanitize_output(" ".join(cmd))
            logger.exception(f"Git command failed: {safe_cmd}")
            return GitCommandResult(
                success=False,
                stdout="",
                stderr=self._sanitize_output(str(e)),
                return_code=-1,
            )

    # ========== Mirror Management ==========

    def init_mirror(self, repo_url: str, repo_name: str, timeout: int = 600) -> Dict[str, Any]:
        """
        יצירת Git mirror ראשוני

        Args:
            repo_url: URL של הריפו ב-GitHub
            repo_name: שם הריפו (לתיקייה מקומית)
            timeout: timeout ל-clone (600 = 10 דקות)

        Returns:
            dict עם success, path, message

        Note:
            תומך ב-Private Repos אם GITHUB_TOKEN מוגדר בסביבה.
        """
        repo_url = str(repo_url or "").strip()
        repo_name = str(repo_name or "").strip()
        if not self._validate_repo_name(repo_name):
            return {"success": False, "path": None, "message": "Invalid repo name"}
        if not self._validate_repo_url(repo_url):
            return {"success": False, "path": None, "message": "Invalid repo URL"}

        repo_path = self._get_repo_path(repo_name)

        # בדיקה אם כבר קיים
        if repo_path.exists():
            if self._is_valid_mirror(repo_path):
                logger.info(f"Mirror already exists: {repo_path}")
                return {
                    "success": True,
                    "path": str(repo_path),
                    "message": "Mirror already exists",
                    "already_existed": True,
                }
            # mirror קיים אבל לא תקין -> לנקות כדי לא להיתקע עם "זומבי"
            logger.warning(f"Mirror directory exists but is invalid, cleaning up: {repo_path}")
            self._safe_rmtree(repo_path)

        # לוג ללא ה-token!
        logger.info(f"Creating mirror: {self._sanitize_output(repo_url)} -> {repo_path}")

        # הזרקת token ל-Private Repos
        auth_url = self._get_authenticated_url(repo_url)

        # Clone as bare mirror
        # שימוש ב-"--" כדי למנוע פרשנות של URL/נתיב כ-flag במקרה קצה
        result = self._run_git_command(["git", "clone", "--mirror", "--", auth_url, str(repo_path)], timeout=timeout)

        if result.success:
            logger.info(f"Mirror created successfully: {repo_path}")
            return {
                "success": True,
                "path": str(repo_path),
                "message": "Mirror created successfully",
                "already_existed": False,
            }
        else:
            logger.error(f"Failed to create mirror: {result.stderr}")
            # ניקוי שאריות של clone חלקי/שבור כדי לא להחזיר success בעתיד בגלל exists()
            if repo_path.exists():
                logger.warning(f"Cleaning up failed mirror clone directory: {repo_path}")
                self._safe_rmtree(repo_path)
            return {
                "success": False,
                "path": None,
                "message": f"Clone failed: {result.stderr[:200]}",
                "error": result.stderr,
            }

    def fetch_updates(self, repo_name: str, timeout: int = 120) -> Dict[str, Any]:
        """
        עדכון ה-mirror (fetch delta בלבד)

        Args:
            repo_name: שם הריפו
            timeout: timeout ל-fetch

        Returns:
            dict עם success, message, ופרטי שגיאה אם יש
        """
        repo_name = str(repo_name or "").strip()
        if not self._validate_repo_name(repo_name):
            return {"success": False, "error": "invalid_repo_name", "message": "Invalid repo name"}

        repo_path = self._get_repo_path(repo_name)

        if not repo_path.exists():
            return {
                "success": False,
                "error": "mirror_not_found",
                "message": f"Mirror does not exist: {repo_path}",
                "action_needed": "init_mirror",
            }

        logger.info(f"Fetching updates for {repo_name}")

        result = self._run_git_command(["git", "fetch", "--all", "--prune"], cwd=repo_path, timeout=timeout)

        if result.success:
            return {
                "success": True,
                "message": "Fetch completed",
                "output": result.stdout[:500] if result.stdout else "No output",
            }
        else:
            # זיהוי סוגי שגיאות
            error_type = self._classify_git_error(result.stderr)
            return {
                "success": False,
                "error_type": error_type,
                "message": result.stderr[:200],
                "retry_recommended": error_type == "network_error",
            }

    def _classify_git_error(self, stderr: str) -> str:
        """סיווג סוג שגיאת Git"""
        stderr_lower = stderr.lower()

        if "could not resolve host" in stderr_lower:
            return "network_error"
        elif "authentication failed" in stderr_lower:
            return "auth_error"
        elif "repository not found" in stderr_lower:
            return "repo_not_found"
        elif "permission denied" in stderr_lower:
            return "permission_error"
        else:
            return "unknown_error"

    def mirror_exists(self, repo_name: str) -> bool:
        """בדיקה אם mirror קיים"""
        return self._get_repo_path(repo_name).exists()

    def get_mirror_info(self, repo_name: str) -> Optional[Dict[str, Any]]:
        """קבלת מידע על mirror"""
        repo_path = self._get_repo_path(repo_name)

        if not repo_path.exists():
            return None

        # גודל התיקייה
        total_size = 0
        for f in repo_path.rglob("*"):
            if not f.is_file():
                continue
            try:
                total_size += f.stat().st_size
            except FileNotFoundError:
                # Race condition אפשרי בזמן git fetch/gc: הקובץ נמחק בין rglob ל-stat
                continue

        # SHA הנוכחי
        current_sha = self.get_current_sha(repo_name)

        return {
            "path": str(repo_path),
            "size_bytes": total_size,
            "size_mb": round(total_size / (1024 * 1024), 2),
            "current_sha": current_sha,
            "exists": True,
        }

    # ========== SHA & Commits ==========

    def get_current_sha(self, repo_name: str, branch: str = "main") -> Optional[str]:
        """
        קבלת SHA הנוכחי של branch

        **חשוב ל-Bare Mirror:**
        ב-`git clone --mirror`, ה-branches נמצאים תחת:
        - `refs/remotes/origin/{branch}` (הכי נפוץ)
        - או `origin/{branch}` (קיצור)

        **לא** תחת `refs/heads/{branch}` כמו ב-working repo רגיל!

        Args:
            repo_name: שם הריפו
            branch: שם ה-branch (main/master)

        Returns:
            SHA string או None
        """
        repo_path = self._get_repo_path(repo_name)

        # ב-Mirror, ה-Branch נמצא תחת refs/remotes/origin/
        # ננסה כמה אפשרויות לפי סדר עדיפות
        refs_to_try = [
            f"refs/heads/{branch}",  # נפוץ ב-mirror (refs מקומיים)
            branch,  # קיצור נפוץ (main / feature/foo)
            f"refs/remotes/origin/{branch}",  # fallback לסוגי clone אחרים
            f"origin/{branch}",  # fallback נוסף
        ]

        for ref in refs_to_try:
            result = self._run_git_command(["git", "rev-parse", ref], cwd=repo_path, timeout=10)
            if result.success and result.stdout.strip():
                return result.stdout.strip()

        # Fallback ל-HEAD רק אם הכל נכשל
        # הערה: HEAD במראה יכול להצביע על משהו לא צפוי!
        logger.warning(f"Could not find branch {branch}, falling back to HEAD")
        result = self._run_git_command(["git", "rev-parse", "HEAD"], cwd=repo_path, timeout=10)

        return result.stdout.strip() if result.success else None

    def get_changed_files(self, repo_name: str, old_sha: str, new_sha: str) -> Optional[Dict[str, List[str]]]:
        """
        קבלת רשימת קבצים ששונו בין שני commits

        Args:
            repo_name: שם הריפו
            old_sha: SHA ישן
            new_sha: SHA חדש

        Returns:
            dict עם added, modified, removed, renamed
        """
        repo_path = self._get_repo_path(repo_name)

        result = self._run_git_command(
            [
                "git",
                "diff-tree",
                "--no-commit-id",
                "--name-status",
                "-r",
                "-M",  # detect renames
                old_sha,
                new_sha,
            ],
            cwd=repo_path,
            timeout=60,
        )

        if not result.success:
            logger.error(f"Failed to get changes: {result.stderr}")
            return None

        changes: Dict[str, Any] = {"added": [], "modified": [], "removed": [], "renamed": []}

        for line in result.stdout.strip().split("\n"):
            if not line:
                continue

            parts = line.split("\t")
            if len(parts) < 2:
                continue

            status = parts[0]

            if status == "A":
                changes["added"].append(parts[1])
            elif status == "M":
                changes["modified"].append(parts[1])
            elif status == "D":
                changes["removed"].append(parts[1])
            elif status.startswith("R"):
                # Rename: R100 old_path new_path
                if len(parts) >= 3:
                    changes["renamed"].append({"old": parts[1], "new": parts[2]})

        return changes  # type: ignore[return-value]

    # ========== File Content ==========

    def _validate_repo_file_path(self, file_path: str) -> bool:
        """
        וולידציה של נתיב קובץ - מונע path traversal.
        """
        if not file_path or not isinstance(file_path, str):
            return False
        if '\x00' in file_path:
            return False
        if file_path.startswith('-'):
            return False

        # Normalize and check for traversal
        # normpath מנרמל ../foo ל-../foo, foo/../bar ל-bar
        # אם אחרי נורמליזציה יש .. בהתחלה = ניסיון traversal מעבר לroot
        normalized = os.path.normpath(file_path)
        if normalized == '..' or normalized.startswith('..' + os.sep) or normalized.startswith('/'):
            return False
        # הערה: לא בודקים '..' in normalized כי a..b.txt הוא שם קובץ תקין!

        return bool(self.FILE_PATH_PATTERN.match(file_path))

    def _validate_basic_ref(self, ref: str) -> bool:
        """
        בדיקה בסיסית של ref - לפני שליחה ל-git.
        הבדיקה המלאה נעשית עם _validate_ref_with_git.
        """
        if not ref or not isinstance(ref, str):
            return False
        if '\x00' in ref:
            return False
        if len(ref) > 200:
            return False

        # HEAD is always valid
        if ref == 'HEAD':
            return True

        return bool(self.BASIC_REF_PATTERN.match(ref))

    def _get_safe_file_path(self, file_path: str) -> Optional[str]:
        """החזרת נתיב קובץ תקין לשימוש בפקודות git."""
        if not self._validate_repo_file_path(file_path):
            return None
        match = self.FILE_PATH_PATTERN.fullmatch(file_path or "")
        if not match:
            return None
        return match.group(0)

    def _validate_repo_ref(self, ref: str) -> bool:
        """ולידציה בסיסית ל-ref לפני שילוב בפקודות git (best-effort)."""
        ref = ref.strip() if isinstance(ref, str) else ref
        return self._validate_basic_ref(ref)

    def get_file_content(self, repo_name: str, file_path: str, ref: str = "HEAD") -> Optional[str]:
        """
        קריאת תוכן קובץ מה-mirror

        Args:
            repo_name: שם הריפו
            file_path: נתיב הקובץ בריפו
            ref: commit SHA או branch (ברירת מחדל: HEAD)

        Returns:
            תוכן הקובץ או None
        """
        # נרמול קלט: הוולידציה עושה strip מקומי, אבל אנחנו חייבים להשתמש בערכים הנקיים בפועל בפקודת git.
        file_path = file_path.strip() if isinstance(file_path, str) else ""
        ref = ref.strip() if isinstance(ref, str) else ""
        if not ref:
            ref = "HEAD"

        # ולידציה חזקה של נתיב הקובץ לפני שילוב בפקודת git
        safe_file_path = self._get_safe_file_path(file_path)
        if not safe_file_path:
            logger.warning("Rejected invalid repo file path: %r", file_path)
            return None

        # ולידציה של ref לפני שילוב בפקודת git (מניעת uncontrolled command line)
        if not self._validate_repo_ref(ref):
            logger.warning("Rejected invalid repo ref: %r", ref)
            return None

        repo_path = self._get_repo_path(repo_name)

        # שימוש רק בערכים שעברו ולידציה בקומנד עצמו
        result = self._run_git_command(["git", "show", f"{ref}:{safe_file_path}"], cwd=repo_path, timeout=30)

        if result.success:
            return result.stdout

        return None

    def list_all_files(self, repo_name: str, ref: str = "HEAD") -> Optional[List[str]]:
        """
        רשימת כל הקבצים בריפו

        Returns:
            רשימת נתיבי קבצים
        """
        repo_name = str(repo_name or "").strip()
        ref = str(ref or "").strip() or "HEAD"
        if not self._validate_repo_name(repo_name):
            return None
        if not self._validate_repo_ref(ref):
            return None

        repo_path = self._get_repo_path(repo_name)

        result = self._run_git_command(["git", "ls-tree", "-r", "--name-only", ref], cwd=repo_path, timeout=60)

        if result.success:
            return [f for f in result.stdout.strip().split("\n") if f]

        return None

    def get_file_info(self, repo_name: str, file_path: str, ref: str = "HEAD") -> Optional[Dict[str, Any]]:
        """
        מידע על קובץ (גודל, סוג, וכו')
        """
        repo_path = self._get_repo_path(repo_name)

        # קבלת מידע עם ls-tree
        result = self._run_git_command(["git", "ls-tree", "-l", ref, "--", file_path], cwd=repo_path, timeout=10)

        if not result.success or not result.stdout.strip():
            return None

        # פורמט: mode type sha size path
        parts = result.stdout.strip().split()
        if len(parts) >= 5:
            return {
                "mode": parts[0],
                "type": parts[1],
                "sha": parts[2],
                "size": int(parts[3]) if parts[3] != "-" else 0,
                "path": parts[4],
            }

        return None

    # ============================================
    # מתודות חדשות להיסטוריה ו-Diff
    # ============================================

    def _validate_ref_with_git(self, repo_name: str, ref: str) -> Dict[str, Any]:
        """
        וולידציה של ref באמצעות git rev-parse.
        זו הדרך ה-canonical לוודא ש-ref תקין.

        Args:
            repo_name: שם הריפו
            ref: Reference לבדיקה

        Returns:
            Dict עם resolved_sha או error
        """
        safe_ref: Optional[str] = None
        if ref == 'HEAD':
            safe_ref = ref
        else:
            match = self.BASIC_REF_PATTERN.fullmatch(ref or "")
            if match:
                safe_ref = match.group(0)
        if not safe_ref:
            return {
                "valid": False,
                "error": "invalid_ref",
                "message": "Reference לא תקין"
            }
        mirror_path = self._get_mirror_path(repo_name)

        try:
            cmd = [
                "git", "-C", str(mirror_path),
                "rev-parse", "--verify", "--quiet",
                f"{safe_ref}^{{commit}}"  # ודא שזה commit
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=10
            )

            if result.returncode != 0:
                return {
                    "valid": False,
                    "error": "invalid_ref",
                    "message": f"Reference '{safe_ref}' לא נמצא"
                }

            return {
                "valid": True,
                "resolved_sha": result.stdout.strip()
            }

        except subprocess.TimeoutExpired:
            return {"valid": False, "error": "timeout"}
        except Exception as e:
            self.logger.exception(
                "Unexpected error validating ref %s in repo %s",
                ref,
                repo_name,
            )
            return {
                "valid": False,
                "error": "internal_error",
                "message": "שגיאה פנימית באימות ה-ref"
            }

    def _detect_binary_content(self, content: bytes) -> bool:
        """
        זיהוי תוכן בינארי באמצעות בדיקת NUL bytes.

        קובץ נחשב בינארי אם:
        1. מכיל NUL bytes (\x00)
        2. יחס גבוה של תווים לא-printable

        Args:
            content: תוכן הקובץ כ-bytes

        Returns:
            True אם הקובץ בינארי
        """
        # בדיקה מהירה: NUL bytes = בינארי
        if b'\x00' in content:
            return True

        # בדיקה משנית: יחס תווים לא-printable
        # (אופציונלי - ל-edge cases)
        if len(content) > 0:
            # דוגמה: בדיקת 8KB ראשונים
            sample = content[:8192]
            non_printable = sum(
                1 for byte in sample
                if byte < 32 and byte not in (9, 10, 13)  # tab, newline, CR
            )
            if non_printable / len(sample) > 0.3:  # יותר מ-30% non-printable
                return True

        return False

    def _try_decode_content(self, content: bytes) -> Dict[str, Any]:
        """
        ניסיון פענוח תוכן עם זיהוי encoding.

        Args:
            content: תוכן הקובץ כ-bytes

        Returns:
            Dict עם decoded content או סימון בינארי
        """
        # בדיקת בינארי קודם
        if self._detect_binary_content(content):
            return {
                "is_binary": True,
                "content": None,
                "encoding": None
            }

        # ניסיון encodings נפוצים
        encodings = ['utf-8', 'utf-8-sig', 'latin-1', 'cp1255']  # cp1255 לעברית

        for encoding in encodings:
            try:
                decoded = content.decode(encoding)
                return {
                    "is_binary": False,
                    "content": decoded,
                    "encoding": encoding
                }
            except (UnicodeDecodeError, LookupError):
                continue

        # Fallback: UTF-8 עם replacement
        return {
            "is_binary": False,
            "content": content.decode('utf-8', errors='replace'),
            "encoding": "utf-8 (with replacements)"
        }

    def get_file_history(
        self,
        repo_name: str,
        file_path: str,
        ref: str = "HEAD",
        limit: int = 20,
        skip: int = 0
    ) -> Dict[str, Any]:
        """
        שליפת היסטוריית commits לקובץ ספציפי.

        Args:
            repo_name: שם הריפו
            file_path: נתיב הקובץ
            ref: Branch, tag, commit או expressions כמו HEAD~5
            limit: מספר commits מקסימלי (1-100)
            skip: כמה commits לדלג

        Returns:
            Dict עם רשימת commits או שגיאה
        """
        # וולידציה בסיסית
        if not self._validate_repo_name(repo_name):
            return {"error": "invalid_repo_name", "message": "שם ריפו לא תקין"}
        safe_file_path = self._get_safe_file_path(file_path)
        if not safe_file_path:
            return {"error": "invalid_file_path", "message": "נתיב קובץ לא תקין"}
        if not self._validate_basic_ref(ref):
            return {"error": "invalid_ref", "message": "Reference לא תקין"}

        # וולידציה ל-limit ו-skip
        limit = max(1, min(int(limit) if isinstance(limit, (int, str)) else 20, 100))
        skip = max(0, int(skip) if isinstance(skip, (int, str)) else 0)

        mirror_path = self._get_mirror_path(repo_name)
        if not mirror_path.exists():
            return {"error": "repo_not_found", "message": "ריפו לא נמצא"}

        # וולידציה של ref באמצעות git
        ref_validation = self._validate_ref_with_git(repo_name, ref)
        if not ref_validation.get("valid"):
            return {
                "error": ref_validation.get("error", "invalid_ref"),
                "message": ref_validation.get("message", "Reference לא תקין")
            }

        resolved_ref = ref_validation["resolved_sha"]

        try:
            # פורמט מיוחד לפענוח קל
            # %H = hash מלא, %h = hash קצר
            # %an = שם author, %ae = email author
            # %at = timestamp author (unix)
            # %s = subject, %b = body
            format_str = "%H%x00%h%x00%an%x00%ae%x00%at%x00%s%x00%b%x1E"

            cmd = [
                "git", "-C", str(mirror_path),
                "log",
                "--follow",           # עקוב אחרי שינויי שם
                f"--max-count={limit}",
                f"--skip={skip}",
                f"--format={format_str}",
                resolved_ref,
                "--",
                safe_file_path
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                timeout=30
            )

            if result.returncode != 0:
                stderr = self._sanitize_output(result.stderr)
                if "does not exist" in stderr or "unknown revision" in stderr:
                    return {
                        "error": "file_not_found",
                        "message": "הקובץ לא נמצא בהיסטוריה"
                    }
                return {"error": "git_error", "message": stderr}

            # פענוח התוצאות
            commits = []
            raw_commits = result.stdout.strip().split("\x1E")

            for raw in raw_commits:
                raw = raw.strip()
                if not raw:
                    continue

                parts = raw.split("\x00")
                if len(parts) < 6:
                    continue

                try:
                    timestamp = int(parts[4])
                except ValueError:
                    timestamp = 0

                commits.append({
                    "hash": parts[0],
                    "short_hash": parts[1],
                    "author": parts[2],
                    "author_email": parts[3],
                    "timestamp": timestamp,
                    "date": datetime.fromtimestamp(timestamp).isoformat() if timestamp else None,
                    "message": parts[5],
                    "body": parts[6].strip() if len(parts) > 6 else ""
                })

            return {
                "success": True,
                "file_path": file_path,
                "ref": ref,
                "resolved_ref": resolved_ref,
                "commits": commits,
                "total_returned": len(commits),
                "skip": skip,
                "limit": limit,
                "has_more": len(commits) == limit
            }

        except subprocess.TimeoutExpired:
            return {"error": "timeout", "message": "הפעולה ארכה יותר מדי זמן"}
        except Exception as e:
            self.logger.error(f"Error getting file history: {e}")
            return {"error": "internal_error", "message": "שגיאה פנימית"}

    def get_file_at_commit(
        self,
        repo_name: str,
        file_path: str,
        commit: str,
        max_size: int = MAX_FILE_SIZE_FOR_DISPLAY
    ) -> Dict[str, Any]:
        """
        שליפת תוכן קובץ ב-commit ספציפי.

        Args:
            repo_name: שם הריפו
            file_path: נתיב הקובץ
            commit: Hash, tag, branch או expression
            max_size: גודל מקסימלי להחזרה (bytes)

        Returns:
            Dict עם תוכן הקובץ או שגיאה
        """
        # וולידציה
        if not self._validate_repo_name(repo_name):
            return {"error": "invalid_repo_name", "message": "שם ריפו לא תקין"}

        safe_file_path = self._get_safe_file_path(file_path)
        if not safe_file_path:
            return {"error": "invalid_file_path", "message": "נתיב קובץ לא תקין"}

        mirror_path = self._get_mirror_path(repo_name)
        if not mirror_path.exists():
            return {"error": "repo_not_found", "message": "ריפו לא נמצא"}

        # וולידציה של commit
        ref_validation = self._validate_ref_with_git(repo_name, commit)
        if not ref_validation.get("valid"):
            return {
                "error": "invalid_commit",
                "message": ref_validation.get("message", "Commit לא תקין")
            }

        resolved_commit = ref_validation["resolved_sha"]

        try:
            # שליפת תוכן כ-bytes (לא text) לזיהוי בינארי נכון
            cmd = [
                "git", "-C", str(mirror_path),
                "show",
                f"{resolved_commit}:{safe_file_path}"
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=30
            )

            if result.returncode != 0:
                stderr = result.stderr.decode('utf-8', errors='replace')
                stderr = self._sanitize_output(stderr)

                if "does not exist" in stderr or "exists on disk" in stderr:
                    return {
                        "error": "file_not_in_commit",
                        "message": "הקובץ לא קיים ב-commit זה"
                    }
                if "unknown revision" in stderr or "bad revision" in stderr:
                    return {
                        "error": "invalid_commit",
                        "message": "Commit לא נמצא"
                    }
                return {"error": "git_error", "message": stderr}

            raw_content = result.stdout
            file_size = len(raw_content)

            # בדיקת גודל
            if file_size > max_size:
                return {
                    "error": "file_too_large",
                    "message": f"הקובץ גדול מדי ({file_size:,} bytes)",
                    "size": file_size,
                    "max_size": max_size
                }

            # זיהוי וקידוד
            decode_result = self._try_decode_content(raw_content)

            if decode_result["is_binary"]:
                return {
                    "success": True,
                    "file_path": file_path,
                    "commit": commit,
                    "resolved_commit": resolved_commit,
                    "is_binary": True,
                    "content": None,
                    "size": file_size,
                    "message": "זהו קובץ בינארי"
                }

            content = decode_result["content"]

            return {
                "success": True,
                "file_path": file_path,
                "commit": commit,
                "resolved_commit": resolved_commit,
                "is_binary": False,
                "content": content,
                "encoding": decode_result["encoding"],
                "size": file_size,
                "lines": content.count('\n') + 1 if content else 0
            }

        except subprocess.TimeoutExpired:
            return {"error": "timeout", "message": "הפעולה ארכה יותר מדי זמן"}
        except Exception as e:
            self.logger.error(f"Error getting file at commit: {e}")
            return {"error": "internal_error", "message": "שגיאה פנימית"}

    def get_diff(
        self,
        repo_name: str,
        commit1: str,
        commit2: str,
        file_path: Optional[str] = None,
        context_lines: int = 3,
        output_format: str = "parsed",
        max_bytes: int = MAX_DIFF_BYTES
    ) -> Dict[str, Any]:
        """
        יצירת diff בין שני commits.

        סמנטיקה: מציג שינויים מ-commit1 ל-commit2.
        - commit1 = הגרסה הישנה (base)
        - commit2 = הגרסה החדשה (target)

        שימושים נפוצים:
        - "השווה X ל-HEAD": get_diff(X, "HEAD")
        - "מה השתנה ב-commit": get_diff("commit^", "commit")
        - "השווה branches": get_diff("main", "feature")

        Args:
            repo_name: שם הריפו
            commit1: Commit ראשון - base (הישן)
            commit2: Commit שני - target (החדש)
            file_path: נתיב קובץ ספציפי (אופציונלי)
            context_lines: מספר שורות הקשר (0-20)
            output_format: 'raw', 'parsed', או 'both'
            max_bytes: הגבלת גודל diff

        Returns:
            Dict עם ה-diff או שגיאה
        """
        # וולידציה
        if not self._validate_repo_name(repo_name):
            return {"error": "invalid_repo_name", "message": "שם ריפו לא תקין"}

        safe_file_path = None
        if file_path:
            if not self._validate_repo_file_path(file_path):
                return {"error": "invalid_file_path", "message": "נתיב קובץ לא תקין"}
            match = self.FILE_PATH_PATTERN.fullmatch(file_path or "")
            if not match:
                return {"error": "invalid_file_path", "message": "נתיב קובץ לא תקין"}
            safe_file_path = match.group(0)
        if not self._validate_basic_ref(commit1):
            return {"error": "invalid_commit1", "message": f"Commit ראשון לא תקין: {commit1}"}
        if not self._validate_basic_ref(commit2):
            return {"error": "invalid_commit2", "message": f"Commit שני לא תקין: {commit2}"}

        # וולידציה ל-context_lines
        context_lines = max(0, min(int(context_lines) if isinstance(context_lines, (int, str)) else 3, 20))

        # וולידציה ל-format
        if output_format not in ('raw', 'parsed', 'both'):
            output_format = 'parsed'
        if not isinstance(max_bytes, int):
            max_bytes = MAX_DIFF_BYTES
        max_bytes = max(1, max_bytes)

        mirror_path = self._get_mirror_path(repo_name)
        if not mirror_path.exists():
            return {"error": "repo_not_found", "message": "ריפו לא נמצא"}

        # וולידציה של commits
        ref1_validation = self._validate_ref_with_git(repo_name, commit1)
        if not ref1_validation.get("valid"):
            return {
                "error": "invalid_commit1",
                "message": f"Commit ראשון לא תקין: {commit1}"
            }

        ref2_validation = self._validate_ref_with_git(repo_name, commit2)
        if not ref2_validation.get("valid"):
            return {
                "error": "invalid_commit2",
                "message": f"Commit שני לא תקין: {commit2}"
            }

        resolved_commit1 = ref1_validation["resolved_sha"]
        resolved_commit2 = ref2_validation["resolved_sha"]

        try:
            # שימוש ב-commit1..commit2 לסמנטיקה ברורה
            cmd = [
                "git", "-C", str(mirror_path),
                "diff",
                f"-U{context_lines}",
                "--no-color",
                "--find-renames",      # זיהוי rename
                "--find-copies",       # זיהוי copy
                "--stat-width=120",
                f"{resolved_commit1}..{resolved_commit2}"  # סינטקס מפורש
            ]

            if safe_file_path:
                cmd.extend(["--", safe_file_path])

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                timeout=60
            )

            if result.returncode != 0:
                stderr = self._sanitize_output(result.stderr)
                if "unknown revision" in stderr or "bad revision" in stderr:
                    return {
                        "error": "invalid_commits",
                        "message": "אחד או יותר מה-commits לא נמצאו"
                    }
                return {"error": "git_error", "message": stderr}

            diff_output = result.stdout
            diff_size = len(diff_output.encode('utf-8'))

            # בדיקת גודל
            is_truncated = False
            if diff_size > max_bytes:
                # קיצוץ ושמירה על hunks שלמים
                diff_output = self._truncate_diff(diff_output, max_bytes)
                is_truncated = True

            # בניית response לפי format
            response = {
                "success": True,
                "commit1": commit1,
                "commit2": commit2,
                "resolved_commit1": resolved_commit1,
                "resolved_commit2": resolved_commit2,
                "file_path": file_path,
                "is_truncated": is_truncated,
                "diff_size_bytes": diff_size
            }

            if output_format in ('raw', 'both'):
                response["raw_diff"] = diff_output

            if output_format in ('parsed', 'both'):
                parsed_diff = self._parse_diff(diff_output)
                response["parsed"] = parsed_diff
                response["stats"] = {
                    "files_changed": len(parsed_diff.get("files", [])),
                    "additions": sum(f.get("additions", 0) for f in parsed_diff.get("files", [])),
                    "deletions": sum(f.get("deletions", 0) for f in parsed_diff.get("files", []))
                }

            return response

        except subprocess.TimeoutExpired:
            return {"error": "timeout", "message": "הפעולה ארכה יותר מדי זמן"}
        except Exception as e:
            self.logger.error(f"Error getting diff: {e}")
            return {"error": "internal_error", "message": "שגיאה פנימית"}

    def _truncate_diff(self, diff_output: str, max_bytes: int) -> str:
        """
        קיצוץ diff תוך שמירה על מבנה תקין.

        Args:
            diff_output: הdiff המלא
            max_bytes: גודל מקסימלי

        Returns:
            Diff מקוצץ עם הודעה
        """
        encoded = diff_output.encode('utf-8')
        if len(encoded) <= max_bytes:
            return diff_output

        # חתוך ומצא סוף hunk/file אחרון
        truncated = encoded[:max_bytes].decode('utf-8', errors='ignore')

        # נסה למצוא סוף קובץ או hunk
        last_diff = truncated.rfind('\ndiff --git')
        last_hunk = truncated.rfind('\n@@')

        cut_point = max(last_diff, last_hunk)
        if cut_point > -1:
            cut_bytes = len(truncated[:cut_point].encode('utf-8'))
            if cut_bytes > max_bytes // 2:  # רק אם זה הגיוני
                truncated = truncated[:cut_point]

        truncated += "\n\n... [Diff truncated due to size limit] ..."
        return truncated

    def _parse_diff(self, diff_output: str) -> Dict[str, Any]:
        """
        פרסור פלט diff לפורמט מובנה.

        תומך ב:
        - קבצים חדשים/מחוקים/משונים
        - rename עם similarity
        - copy
        - binary files

        Returns:
            Dict עם מבנה ה-diff המפורסר
        """
        files = []
        current_file = None
        current_hunks = []
        current_hunk = None

        lines = diff_output.split('\n')
        i = 0

        while i < len(lines):
            line = lines[i]

            # התחלת קובץ חדש
            if line.startswith('diff --git'):
                # שמור קובץ קודם
                if current_file:
                    if current_hunk:
                        current_hunks.append(current_hunk)
                    current_file['hunks'] = current_hunks
                    files.append(current_file)

                # התחל קובץ חדש
                match = re.match(r'diff --git a/(.+) b/(.+)', line)
                if match:
                    current_file = {
                        'old_path': match.group(1),
                        'new_path': match.group(2),
                        'status': 'modified',
                        'additions': 0,
                        'deletions': 0,
                        'is_binary': False,
                        'similarity': None,
                        'rename_from': None,
                        'rename_to': None
                    }
                else:
                    current_file = {
                        'old_path': '',
                        'new_path': '',
                        'status': 'modified',
                        'additions': 0,
                        'deletions': 0,
                        'is_binary': False
                    }
                current_hunks = []
                current_hunk = None

            # זיהוי סוג שינוי
            elif line.startswith('new file mode'):
                if current_file:
                    current_file['status'] = 'added'

            elif line.startswith('deleted file mode'):
                if current_file:
                    current_file['status'] = 'deleted'

            elif line.startswith('rename from '):
                if current_file:
                    current_file['status'] = 'renamed'
                    current_file['rename_from'] = line[12:]

            elif line.startswith('rename to '):
                if current_file:
                    current_file['rename_to'] = line[10:]

            elif line.startswith('similarity index '):
                if current_file:
                    match = re.match(r'similarity index (\d+)%', line)
                    if match:
                        current_file['similarity'] = int(match.group(1))

            elif line.startswith('copy from '):
                if current_file:
                    current_file['status'] = 'copied'
                    current_file['copy_from'] = line[10:]

            elif line.startswith('copy to '):
                if current_file:
                    current_file['copy_to'] = line[8:]

            elif 'Binary files' in line:
                if current_file:
                    current_file['is_binary'] = True
                    current_file['status'] = 'binary'

            # Header של hunk
            elif line.startswith('@@'):
                if current_hunk:
                    current_hunks.append(current_hunk)

                # @@ -start,count +start,count @@ optional context
                match = re.match(
                    r'@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)',
                    line
                )
                if match:
                    current_hunk = {
                        'old_start': int(match.group(1)),
                        'old_count': int(match.group(2) or 1),
                        'new_start': int(match.group(3)),
                        'new_count': int(match.group(4) or 1),
                        'header': match.group(5).strip(),
                        'lines': []
                    }
                else:
                    current_hunk = {
                        'old_start': 0,
                        'old_count': 0,
                        'new_start': 0,
                        'new_count': 0,
                        'header': '',
                        'lines': []
                    }

            # שורות תוכן ב-hunk
            elif current_hunk is not None:
                if line.startswith('+') and not line.startswith('+++'):
                    current_hunk['lines'].append({
                        'type': 'addition',
                        'content': line[1:]
                    })
                    if current_file:
                        current_file['additions'] += 1
                elif line.startswith('-') and not line.startswith('---'):
                    current_hunk['lines'].append({
                        'type': 'deletion',
                        'content': line[1:]
                    })
                    if current_file:
                        current_file['deletions'] += 1
                elif line.startswith(' '):
                    current_hunk['lines'].append({
                        'type': 'context',
                        'content': line[1:]
                    })
                elif line == '\\ No newline at end of file':
                    current_hunk['lines'].append({
                        'type': 'info',
                        'content': 'No newline at end of file'
                    })

            i += 1

        # שמור קובץ אחרון
        if current_file:
            if current_hunk:
                current_hunks.append(current_hunk)
            current_file['hunks'] = current_hunks
            files.append(current_file)

        return {'files': files}

    def get_commit_info(
        self,
        repo_name: str,
        commit: str
    ) -> Dict[str, Any]:
        """
        שליפת פרטי commit בודד.

        Args:
            repo_name: שם הריפו
            commit: Hash, tag, branch או expression

        Returns:
            Dict עם פרטי ה-commit
        """
        if not self._validate_repo_name(repo_name):
            return {"error": "invalid_repo_name", "message": "שם ריפו לא תקין"}

        mirror_path = self._get_mirror_path(repo_name)
        if not mirror_path.exists():
            return {"error": "repo_not_found", "message": "ריפו לא נמצא"}

        # וולידציה
        ref_validation = self._validate_ref_with_git(repo_name, commit)
        if not ref_validation.get("valid"):
            return {
                "error": "commit_not_found",
                "message": ref_validation.get("message", "Commit לא נמצא")
            }

        resolved_commit = ref_validation["resolved_sha"]

        try:
            # פרטי commit
            format_str = "%H%x00%h%x00%an%x00%ae%x00%at%x00%cn%x00%ce%x00%ct%x00%s%x00%b%x00%P"
            cmd = [
                "git", "-C", str(mirror_path),
                "log", "-1",
                f"--format={format_str}",
                resolved_commit
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                timeout=10
            )

            if result.returncode != 0:
                stderr = self._sanitize_output(result.stderr)
                return {"error": "git_error", "message": stderr}

            parts = result.stdout.strip().split("\x00")
            if len(parts) < 11:
                return {"error": "parse_error", "message": "שגיאה בפענוח פרטי commit"}

            # רשימת קבצים שהשתנו
            files_cmd = [
                "git", "-C", str(mirror_path),
                "diff-tree", "--no-commit-id",
                "--name-status", "-r", "-M", "-C",  # עם rename/copy detection
                resolved_commit
            ]

            files_result = subprocess.run(
                files_cmd,
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                timeout=10
            )

            changed_files = []
            if files_result.returncode == 0:
                for line in files_result.stdout.strip().split('\n'):
                    if not line:
                        continue
                    parts_file = line.split('\t')
                    if len(parts_file) >= 2:
                        status_code = parts_file[0]

                        # פענוח סטטוס (כולל rename/copy עם אחוזים)
                        status_map = {
                            'A': 'added',
                            'M': 'modified',
                            'D': 'deleted',
                        }

                        if status_code.startswith('R'):
                            status = 'renamed'
                            similarity = int(status_code[1:]) if len(status_code) > 1 else None
                            if len(parts_file) >= 3:
                                changed_files.append({
                                    'old_path': parts_file[1],
                                    'new_path': parts_file[2],
                                    'status': status,
                                    'similarity': similarity
                                })
                                continue
                        elif status_code.startswith('C'):
                            status = 'copied'
                            if len(parts_file) >= 3:
                                changed_files.append({
                                    'old_path': parts_file[1],
                                    'new_path': parts_file[2],
                                    'status': status
                                })
                                continue
                        else:
                            status = status_map.get(status_code[0], 'modified')

                        changed_files.append({
                            'path': parts_file[1],
                            'status': status
                        })

            try:
                author_ts = int(parts[4])
                committer_ts = int(parts[7])
            except ValueError:
                author_ts = committer_ts = 0

            return {
                "success": True,
                "hash": parts[0],
                "short_hash": parts[1],
                "author": {
                    "name": parts[2],
                    "email": parts[3],
                    "timestamp": author_ts,
                    "date": datetime.fromtimestamp(author_ts).isoformat() if author_ts else None
                },
                "committer": {
                    "name": parts[5],
                    "email": parts[6],
                    "timestamp": committer_ts,
                    "date": datetime.fromtimestamp(committer_ts).isoformat() if committer_ts else None
                },
                "message": parts[8],
                "body": parts[9].strip(),
                "parents": parts[10].split() if parts[10] else [],
                "changed_files": changed_files
            }

        except subprocess.TimeoutExpired:
            return {"error": "timeout", "message": "הפעולה ארכה יותר מדי זמן"}
        except Exception as e:
            self.logger.error(f"Error getting commit info: {e}")
            return {"error": "internal_error", "message": "שגיאה פנימית"}

    # ========== Search with git grep ==========

    def search_with_git_grep(
        self,
        repo_name: str,
        query: str,
        max_results: int = 100,
        timeout: int = 10,
        file_pattern: Optional[str] = None,
        case_sensitive: bool = True,
        ref: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        חיפוש בקוד עם git grep (מהיר מאוד!)

        **חשוב:** ב-Bare Repository (mirror) יש לשים לב לסדר הארגומנטים:
        git grep [options] <pattern> <revision> -- <pathspec>

        **Refs ב-Mirror:**
        ב-bare repo שנוצר עם `git clone --mirror`, ה-refs לרוב נמצאים תחת `refs/heads/<branch>`.
        אם לא מועבר ref, נשתמש ב-`HEAD` כברירת מחדל.

        Args:
            repo_name: שם הריפו
            query: מחרוזת/regex לחיפוש
            max_results: מקסימום תוצאות
            timeout: timeout בשניות
            file_pattern: סינון קבצים (למשל "*.py")
            case_sensitive: case sensitive?
            ref: revision לחיפוש (origin/main, SHA, וכו').
                 None = ברירת מחדל origin/main

        Returns:
            dict עם results, total_count, truncated
        """
        query = str(query or "").strip()
        file_pattern = file_pattern.strip() if isinstance(file_pattern, str) else None
        ref = ref.strip() if isinstance(ref, str) else None

        repo_name = str(repo_name or "").strip()
        if not self._validate_repo_name(repo_name):
            return {"error": "invalid_repo_name", "results": []}

        repo_path = self._get_repo_path(repo_name)

        if not repo_path.exists():
            return {"error": "mirror_not_found", "results": []}

        # קביעת ה-ref לחיפוש
        # ב-Mirror עדיף origin/{default_branch} על HEAD
        # הערה: ה-default_branch נשמר ב-repo_metadata במהלך initial_import
        if ref is None:
            # ברירת מחדל - אם לא הועבר ref, נשתמש ב-HEAD
            # אבל עדיף שהקורא יעביר את ה-ref הנכון מה-DB!
            ref = "HEAD"
        if not self._validate_repo_ref(ref):
            return {"error": "invalid_ref", "results": []}

        # בניית הפקודה - סדר נכון ל-Bare Repository!
        # git grep [options] <pattern> <revision> -- <pathspec>
        cmd = ["git", "grep", "-n", "-I", "--break", "--heading"]

        # *** הגבלת זיכרון: מגבילים את מספר ההתאמות לכל קובץ ***
        # זה מונע מצב שחיפוש מונח נפוץ (כמו "import") יחזיר
        # אלפי התאמות ויגרום לחריגת זיכרון (512MB limit on Render)
        # -m N = מקסימום N התאמות לכל קובץ
        matches_per_file = min(max_results, 20)  # מקסימום 20 התאמות לקובץ
        cmd.extend(["-m", str(matches_per_file)])

        # Case sensitivity
        if not case_sensitive:
            cmd.append("-i")

        # Regex או literal
        if self._is_regex(query):
            cmd.append("-E")  # Extended regex
        else:
            cmd.append("-F")  # Fixed string (מהיר יותר)

        # 1. הוספת ה-Pattern (Query)
        # אם מתחיל ב-"-", צריך להשתמש ב-"-e" כדי שגיט לא יחשוב שזה flag
        if query.startswith("-"):
            cmd.extend(["-e", query])
        else:
            cmd.append(query)

        # 2. הוספת ה-Revision (branch/SHA)
        cmd.append(ref)

        # 3. File pattern (pathspec)
        # ב-bare repo אין working directory, אז אם אין פילטר -
        # פשוט לא מוסיפים pathspec (git grep יחפש בכל העץ)
        if file_pattern:
            cmd.append("--")
            cmd.append(file_pattern)
        # אם אין file_pattern, לא צריך -- ולא צריך "."

        try:
            # שימוש בשיטת streaming כדי להגביל את צריכת הזיכרון
            # עוצרים מוקדם כשמגיעים למספיק תוצאות
            streaming_result = self._run_grep_with_streaming(cmd, repo_path, max_results, timeout)

            if "error" in streaming_result:
                return streaming_result

            results = streaming_result.get("results", [])
            truncated = streaming_result.get("truncated", False)
            truncation_reason = streaming_result.get("truncation_reason")

            return {
                "results": results,
                "total_count": len(results),
                "truncated": truncated,
                "truncation_reason": truncation_reason,
                "query": query,
            }

        except Exception as e:
            logger.exception(f"Search error: {e}")
            return {"error": "search_error", "results": []}

    def _run_grep_with_streaming(
        self,
        cmd: List[str],
        repo_path: Path,
        max_results: int,
        timeout: int
    ) -> Dict[str, Any]:
        """
        הרצת git grep עם streaming לצמצום צריכת זיכרון.

        במקום לקרוא את כל הפלט לזיכרון, קוראים שורה-שורה
        ועוצרים מוקדם כשמגיעים למספיק תוצאות.

        Args:
            cmd: פקודת git grep
            repo_path: נתיב לריפו
            max_results: מקסימום תוצאות
            timeout: timeout בשניות

        Returns:
            dict עם results, truncated, truncation_reason או error
        """
        # וולידציה בסיסית (ממומש כבר ב-_run_git_command אבל נבדוק גם פה)
        if not cmd or cmd[0] != "git":
            return {"error": "invalid_command", "results": []}

        results: List[Dict[str, Any]] = []
        current_file: Optional[str] = None
        lines_read = 0
        max_lines = max_results * 50  # הגבלת קריאה גם אם אין מספיק התאמות
        truncated = False
        truncation_reason: Optional[str] = None

        def _looks_like_git_sha(text: str) -> bool:
            t = (text or "").strip()
            if len(t) < 7 or len(t) > 64:
                return False
            return all(c in "0123456789abcdefABCDEF" for c in t)

        process: Optional[subprocess.Popen] = None
        try:
            process = subprocess.Popen(
                cmd,
                cwd=str(repo_path),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,  # Line buffered
            )

            # קריאה עם timeout
            import select
            import time

            start_time = time.time()

            while True:
                # בדיקת timeout
                elapsed = time.time() - start_time
                if elapsed >= timeout:
                    process.kill()
                    logger.warning(f"git grep timeout after {elapsed:.1f}s")
                    truncated = True
                    truncation_reason = "timeout"
                    break

                # בדיקה אם יש עוד פלט
                remaining_timeout = max(0.1, timeout - elapsed)

                # שימוש ב-select לבדוק אם יש נתונים לקריאה
                # (עובד על Linux/Mac)
                try:
                    ready, _, _ = select.select([process.stdout], [], [], min(0.5, remaining_timeout))
                except (ValueError, OSError):
                    # במקרה של בעיה, נמשיך בדרך הפשוטה
                    ready = [process.stdout]

                if not ready:
                    # בדיקה אם התהליך הסתיים
                    if process.poll() is not None:
                        break
                    continue

                line = process.stdout.readline()
                if not line:
                    # סוף הפלט
                    break

                lines_read += 1
                if lines_read > max_lines:
                    # הגבלת קריאה למקרה של פלט אינסופי
                    process.kill()
                    logger.warning(f"git grep output limit reached ({max_lines} lines)")
                    truncated = True
                    truncation_reason = "output_limit"
                    break

                # פרסור השורה
                line = line.rstrip('\n')
                if not line:
                    continue

                # בדיקה אם זו שורת תוצאה (מספר:תוכן)
                parts = line.split(":", 1)
                is_match_line = len(parts) == 2 and parts[0].strip().isdigit()

                if is_match_line:
                    if current_file:
                        try:
                            line_num = int(parts[0].strip())
                            content = parts[1]

                            results.append({
                                "path": current_file,
                                "line": line_num,
                                "content": content.strip()[:500]
                            })

                            if len(results) >= max_results:
                                # מספיק תוצאות - עוצרים מוקדם!
                                process.kill()
                                truncated = True
                                truncation_reason = "max_results"
                                break

                        except ValueError:
                            continue
                else:
                    # שורת Heading (שם קובץ)
                    file_line = line.strip()

                    # הסרת ref prefix אם קיים
                    if ":" in file_line:
                        colon_pos = file_line.find(":")
                        before_colon = file_line[:colon_pos]

                        if (
                            "/" in before_colon
                            or before_colon in ["HEAD", "main", "master", "develop"]
                            or before_colon.startswith("refs/")
                            or _looks_like_git_sha(before_colon)
                        ):
                            file_line = file_line[colon_pos + 1:]

                    current_file = file_line

            # בדיקת קוד יציאה - git grep מחזיר 1 כשאין תוצאות (תקין)
            # קוד יציאה אחר (2+) מציין שגיאה
            returncode = process.returncode
            if returncode is not None and returncode > 1:
                # קריאת stderr לקבלת הודעת השגיאה
                stderr_output = ""
                try:
                    stderr_output = process.stderr.read() if process.stderr else ""
                except Exception:
                    pass
                error_msg = stderr_output[:200] if stderr_output else f"git grep failed with code {returncode}"
                logger.warning(f"git grep error (code {returncode}): {error_msg}")
                return {"error": "search_failed", "message": error_msg, "results": []}

            return {
                "results": results,
                "truncated": truncated,
                "truncation_reason": truncation_reason
            }

        except FileNotFoundError:
            return {"error": "git_not_found", "results": []}
        except Exception as e:
            logger.exception(f"Streaming grep error: {e}")
            return {"error": "search_error", "message": str(e)[:200], "results": []}
        finally:
            # ניקוי subprocess בכל מקרה - מונע דליפות
            if process is not None:
                try:
                    # וידוא שהתהליך נהרג
                    if process.poll() is None:
                        process.kill()
                    process.wait(timeout=1)
                except Exception:
                    pass
                # סגירת file handles
                try:
                    if process.stdout:
                        process.stdout.close()
                    if process.stderr:
                        process.stderr.close()
                except Exception:
                    pass

    def _is_regex(self, query: str) -> bool:
        """בדיקה אם ה-query הוא regex"""
        regex_chars = r".*+?[]{}()^$|\\"
        return any(c in query for c in regex_chars)

    def _parse_grep_output(self, output: str, max_results: int) -> List[Dict[str, Any]]:
        """
        פרסור פלט git grep

        **חשוב:** כשמחפשים עם revision (למשל origin/main),
        הפלט של git grep כולל את ה-ref בשורת הקובץ:

        פורמט עם revision:
            origin/main:src/app.py      <-- שם קובץ עם ref prefix!
            10:content
            15:more content

            origin/main:utils/helper.py
            ...

        הפרסור חייב לזהות את זה ולחלץ רק את הנתיב.
        """
        results: List[Dict[str, Any]] = []
        current_file = None

        def _looks_like_git_sha(text: str) -> bool:
            t = (text or "").strip()
            # Git מאפשר SHA מקוצר (בד"כ 7+) או מלא (40), ובחלק מהמערכות גם SHA-256 (64)
            if len(t) < 7 or len(t) > 64:
                return False
            return all(c in "0123456789abcdefABCDEF" for c in t)

        for line in output.split("\n"):
            if not line:
                continue

            # בדיקה אם זו שורת תוצאה (מספר:תוכן)
            # שורת תוצאה מתחילה במספר ואז נקודתיים
            parts = line.split(":", 1)
            is_match_line = len(parts) == 2 and parts[0].strip().isdigit()

            if is_match_line:
                # שורת תוצאה: line_num:content
                if current_file:
                    try:
                        line_num = int(parts[0].strip())
                        content = parts[1]

                        results.append({"path": current_file, "line": line_num, "content": content.strip()[:500]})

                        if len(results) >= max_results:
                            return results

                    except ValueError:
                        continue
            else:
                # שורת Heading (שם קובץ)
                file_line = line.strip()

                # אם הפלט כולל ref prefix (למשל "origin/main:path/to/file.py")
                # צריך לחלץ רק את הנתיב
                if ":" in file_line:
                    # בדיקה אם זה ref:path או סתם נתיב עם נקודתיים
                    # ref בדרך כלל לא מכיל "/" לפני הנקודתיים הראשונות
                    colon_pos = file_line.find(":")
                    before_colon = file_line[:colon_pos]

                    # אם החלק לפני הנקודתיים נראה כמו ref (למשל "origin/main")
                    # ולא כמו נתיב (למשל "C:" ב-Windows, או "src")
                    if (
                        "/" in before_colon
                        or before_colon in ["HEAD", "main", "master", "develop"]
                        or _looks_like_git_sha(before_colon)
                    ):
                        # זה ref:path - לוקחים רק את הנתיב
                        file_line = file_line[colon_pos + 1 :]

                current_file = file_line

        return results

    # ========== Statistics ==========

    def get_repo_stats(self, repo_name: str) -> Optional[Dict[str, Any]]:
        """סטטיסטיקות על הריפו"""
        repo_path = self._get_repo_path(repo_name)

        if not repo_path.exists():
            return None

        # ספירת קבצים
        files = self.list_all_files(repo_name) or []

        # ספירת קומיטים
        result = self._run_git_command(["git", "rev-list", "--count", "HEAD"], cwd=repo_path, timeout=30)
        commit_count = int(result.stdout.strip()) if result.success else 0

        # גודל
        mirror_info = self.get_mirror_info(repo_name)

        # סטטיסטיקות לפי סוג קובץ
        file_types: Dict[str, int] = {}
        for f in files:
            ext = Path(f).suffix.lower() or "(no ext)"
            file_types[ext] = file_types.get(ext, 0) + 1

        return {
            "total_files": len(files),
            "commit_count": commit_count,
            "size_mb": mirror_info["size_mb"] if mirror_info else 0,
            "file_types": dict(sorted(file_types.items(), key=lambda x: x[1], reverse=True)[:20]),  # Top 20
        }

    def get_last_commit_info(
        self, repo_name: str, ref: str = "HEAD", offset: int = 0, max_files: int = 10
    ) -> Optional[Dict[str, Any]]:
        """
        קבלת מידע על הקומיט האחרון כולל רשימת קבצים שהשתנו.

        **שימוש בדשבורד:** הצגת שינויים אחרונים לאדמין.

        Args:
            repo_name: שם הריפו
            ref: branch/SHA (ברירת מחדל: HEAD)

        Returns:
            dict עם sha, message, author, date, files
            או None אם נכשל
        """
        repo_path = self._get_repo_path(repo_name)

        if not repo_path.exists():
            return None

        # ולידציה בסיסית ל-ref (מניעת שימוש ב-flag כ-ref)
        ref = str(ref or "").strip() or "HEAD"
        if not self._validate_repo_ref(ref):
            return None

        # 1. קבלת פרטי הקומיט האחרון
        # חשוב: לא להשתמש במפריד רגיל כמו "|" (יכול להופיע בשם מחבר/Subject).
        # נשתמש במפריד NUL (\x00) שלא יכול להופיע בשדות טקסט רגילים.
        result = self._run_git_command(
            ["git", "log", "-1", "--format=%H%x00%an%x00%aI%x00%s", ref],
            cwd=repo_path,
            timeout=10,
        )

        if not result.success or not result.stdout.strip():
            return None

        raw = (result.stdout or "").rstrip("\n")
        parts = raw.split("\x00")
        if len(parts) < 4:
            return None

        sha, author, date_str, message = parts[0], parts[1], parts[2], parts[3]

        # 2. קבלת רשימת קבצים שהשתנו בקומיט
        # הערה: עבור הקומיט הראשון (ללא parent), diff-tree עם ^! לא יעבוד.
        # נשתמש ב-show --name-status שעובד גם לקומיט יתום.
        files_result = self._run_git_command(["git", "show", "--name-status", "--format=", sha], cwd=repo_path, timeout=30)

        files = []
        if files_result.success:
            for line in files_result.stdout.strip().split("\n"):
                if not line.strip():
                    continue

                parts = line.split("\t")
                if len(parts) < 2:
                    continue

                status_code = (parts[0] or "").strip()

                old_path: Optional[str] = None
                file_path: str
                # Renames/Copies: git outputs "R100\told_path\tnew_path" / "C100\told_path\tnew_path" (3+ parts)
                if (status_code.startswith("R") or status_code.startswith("C")) and len(parts) >= 3:
                    old_path = (parts[1] or "").strip()
                    file_path = (parts[2] or "").strip()
                else:
                    file_path = (parts[1] or "").strip()

                if not file_path:
                    continue

                # מיפוי סטטוס לאייקון ותיאור
                status_map = {
                    "A": {"status": "added", "icon": "➕", "label": "נוסף"},
                    "M": {"status": "modified", "icon": "✏️", "label": "עודכן"},
                    "D": {"status": "deleted", "icon": "🗑️", "label": "נמחק"},
                }

                # R = Renamed (בדרך כלל R100, R095 וכו')
                if status_code.startswith("R"):
                    status_info = {"status": "renamed", "icon": "📝", "label": "שונה שם"}
                # C = Copied (בדרך כלל C100, C095 וכו')
                elif status_code.startswith("C"):
                    status_info = {"status": "copied", "icon": "📄", "label": "הועתק"}
                else:
                    status_info = status_map.get(status_code, {"status": "unknown", "icon": "❓", "label": "אחר"})

                # קבלת סיומת לאייקון שפה
                from pathlib import Path as PathLib

                ext = PathLib(file_path).suffix.lower()
                lang_icons = {
                    ".py": "🐍",
                    ".js": "📜",
                    ".ts": "📘",
                    ".html": "🌐",
                    ".css": "🎨",
                    ".json": "📋",
                    ".md": "📝",
                    ".yml": "⚙️",
                    ".yaml": "⚙️",
                    ".sh": "🔧",
                    ".sql": "🗄️",
                }
                file_icon = lang_icons.get(ext, "📄")

                files.append(
                    {
                        "path": file_path,
                        "name": PathLib(file_path).name,
                        "old_path": old_path,
                        "status": status_info["status"],
                        "status_icon": status_info["icon"],
                        "status_label": status_info["label"],
                        "file_icon": file_icon,
                    }
                )

        # הגבלת מספר הקבצים להצגה + תמיכה ב-"טען עוד"
        total_files = len(files)
        try:
            offset_i = int(offset)
        except Exception:
            offset_i = 0
        try:
            max_i = int(max_files)
        except Exception:
            max_i = 10

        offset_i = max(0, offset_i)
        max_i = max(1, min(200, max_i))

        start = offset_i
        end = offset_i + max_i
        truncated = end < total_files

        return {
            "sha": sha,
            "sha_short": sha[:7],
            "author": author,
            "date": date_str,
            "message": message,
            "files": files[start:end],
            "total_files": total_files,
            "truncated": truncated,
        }

    def search_history(
        self,
        repo_name: str,
        query: str,
        search_type: str = "message",
        file_path: Optional[str] = None,
        limit: int = 20
    ) -> Dict[str, Any]:
        """
        חיפוש בהיסטוריית commits.

        Args:
            repo_name: שם הריפו
            query: מילת חיפוש
            search_type: סוג החיפוש:
                - "message": חיפוש בהודעות commit
                - "code": חיפוש בקוד (pickaxe - מי הוסיף/הסיר את המילה)
            file_path: הגבלה לקובץ ספציפי (אופציונלי)
            limit: מספר תוצאות מקסימלי (1-50)

        Returns:
            Dict עם רשימת commits או שגיאה
        """
        # וולידציה בסיסית
        if not self._validate_repo_name(repo_name):
            return {"error": "invalid_repo_name", "message": "שם ריפו לא תקין"}

        if not query or len(query.strip()) < 2:
            return {"error": "invalid_query", "message": "מילת החיפוש קצרה מדי (מינימום 2 תווים)"}

        # ניקוי query מתווים מסוכנים
        safe_query = re.sub(r'[^\w\s\-_.@#]', '', query.strip())
        if not safe_query:
            return {"error": "invalid_query", "message": "מילת החיפוש מכילה תווים לא תקינים"}

        if search_type not in ("message", "code"):
            return {"error": "invalid_search_type", "message": "סוג חיפוש לא תקין"}

        limit = max(1, min(int(limit) if isinstance(limit, (int, str)) else 20, 50))

        mirror_path = self._get_mirror_path(repo_name)
        if not mirror_path.exists():
            return {"error": "repo_not_found", "message": "ריפו לא נמצא"}

        # וולידציה לנתיב קובץ אם צוין
        safe_file_path = None
        if file_path:
            safe_file_path = self._get_safe_file_path(file_path)
            if not safe_file_path:
                return {"error": "invalid_file_path", "message": "נתיב קובץ לא תקין"}

        try:
            # פורמט לפענוח קל
            format_str = "%H%x00%h%x00%an%x00%ae%x00%at%x00%s%x00%b%x1E"

            cmd = [
                "git", "-C", str(mirror_path),
                "log",
                f"--max-count={limit}",
                f"--format={format_str}",
            ]

            # הוספת פרמטר חיפוש לפי סוג
            if search_type == "message":
                cmd.extend(["--grep", safe_query, "-i"])  # case insensitive
            else:  # code
                cmd.extend([f"-S{safe_query}"])  # pickaxe

            # הוספת ref ברירת מחדל
            cmd.append("HEAD")

            # הגבלה לקובץ ספציפי
            if safe_file_path:
                cmd.extend(["--", safe_file_path])

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                timeout=60  # timeout ארוך יותר לחיפוש בקוד
            )

            if result.returncode != 0:
                stderr = self._sanitize_output(result.stderr)
                return {"error": "git_error", "message": stderr}

            # פענוח התוצאות
            commits = []
            raw_commits = result.stdout.strip().split("\x1E")

            for raw in raw_commits:
                raw = raw.strip()
                if not raw:
                    continue

                parts = raw.split("\x00")
                if len(parts) < 6:
                    continue

                try:
                    timestamp = int(parts[4])
                except ValueError:
                    timestamp = 0

                message = parts[5]
                # הדגשת מילת החיפוש בהודעה (לחיפוש בהודעות)
                highlighted_message = message
                if search_type == "message":
                    # הדגשה case-insensitive
                    pattern = re.compile(re.escape(safe_query), re.IGNORECASE)
                    highlighted_message = pattern.sub(
                        lambda m: f"<mark>{m.group()}</mark>",
                        message
                    )

                commits.append({
                    "hash": parts[0],
                    "short_hash": parts[1],
                    "author": parts[2],
                    "author_email": parts[3],
                    "timestamp": timestamp,
                    "date": datetime.fromtimestamp(timestamp).isoformat() if timestamp else None,
                    "message": message,
                    "highlighted_message": highlighted_message,
                    "body": parts[6].strip() if len(parts) > 6 else ""
                })

            return {
                "success": True,
                "query": query,
                "search_type": search_type,
                "file_path": file_path,
                "commits": commits,
                "total_returned": len(commits),
                "limit": limit
            }

        except subprocess.TimeoutExpired:
            return {"error": "timeout", "message": "החיפוש ארך יותר מדי זמן"}
        except Exception as e:
            self.logger.error(f"Error searching history: {e}")
            return {"error": "internal_error", "message": "שגיאה פנימית"}


# Singleton instance
_mirror_service: Optional[GitMirrorService] = None


def get_mirror_service() -> GitMirrorService:
    """קבלת instance יחיד של השירות"""
    global _mirror_service
    if _mirror_service is None:
        _mirror_service = GitMirrorService()
    return _mirror_service

