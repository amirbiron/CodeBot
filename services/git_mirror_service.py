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
import subprocess
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


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

    def __init__(self, base_path: Optional[str] = None):
        """
        Args:
            base_path: נתיב בסיסי לאחסון mirrors.
                       ברירת מחדל: REPO_MIRROR_PATH או /var/data/repos
        """
        self.base_path = Path(base_path or os.getenv("REPO_MIRROR_PATH", "/var/data/repos"))
        self._ensure_base_path()

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
        token = os.getenv("GITHUB_TOKEN")

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

    def _sanitize_output(self, text: str) -> str:
        """
        מחיקת טוקנים רגישים מפלט/לוגים

        חשוב! אם git clone/fetch נכשל, stderr יכול להכיל את ה-URL
        כולל הטוקן. חובה לנקות לפני לוג/החזרה ל-API.

        Args:
            text: טקסט שעלול להכיל טוקן

        Returns:
            טקסט נקי (הטוקן מוחלף ב-***)
        """
        if not text:
            return ""
        # הימנעות מ-regex כאן (CodeQL: ReDoS). נבצע סניטציה לינארית על טקסט.
        # נזהה תבניות של credentials ב-URL בסגנון:
        #   https://user:SECRET@host/...
        # ונחליף את SECRET ב-*** (נשמור את user ואת ה-host).
        s = str(text)
        out: list[str] = []
        i = 0
        needle = "https://"
        n = len(s)

        while True:
            j = s.find(needle, i)
            if j == -1:
                out.append(s[i:])
                break

            out.append(s[i:j])
            k = j + len(needle)

            # חיפוש '@' רק בתוך ה-authority (לפני '/'), ובתוך חלון מוגבל.
            # זה מונע מצב של סריקה עד סוף טקסט ענק.
            max_end = min(n, k + 2048)

            # עצירה גם על whitespace (URLs בפלט לרוב לא חוצים רווחים)
            ws_positions = []
            for ch in (" ", "\n", "\r", "\t"):
                p = s.find(ch, k, max_end)
                if p != -1:
                    ws_positions.append(p)
            segment_end = min(ws_positions) if ws_positions else max_end

            slash_pos = s.find("/", k, segment_end)
            at_pos = s.find("@", k, segment_end)

            # credentials קיימים רק אם יש '@' לפני ה-slash הראשון (או שאין slash)
            if at_pos != -1 and (slash_pos == -1 or at_pos < slash_pos):
                colon_pos = s.rfind(":", k, at_pos)
                if colon_pos != -1:
                    # נשמור את "https://user:" ונחליף את הסיסמה/טוקן
                    out.append(s[j : colon_pos + 1])
                    out.append("***@")
                    i = at_pos + 1
                    continue

            # אין תבנית credentials מוכרת — נשמור את הסכמה ונמשיך.
            out.append(needle)
            i = k

        return "".join(out)

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
        logger.info(f"Creating mirror: {repo_url} -> {repo_path}")

        # הזרקת token ל-Private Repos
        auth_url = self._get_authenticated_url(repo_url)

        # Clone as bare mirror
        result = self._run_git_command(["git", "clone", "--mirror", auth_url, str(repo_path)], timeout=timeout)

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
        """ולידציה בסיסית לנתיב קובץ בריפו לפני שימוש בפקודות git.

        המטרה היא למנוע נתיבים מסוכנים (למשל כאלה שיכולים להתפרש כאופציות של git
        או להכיל ניסיון traversal).
        """
        if not isinstance(file_path, str):
            return False

        file_path = file_path.strip()
        if not file_path:
            return False

        # מניעת תווים בעייתיים בסיסיים
        if "\x00" in file_path or "\\" in file_path:
            return False

        # לא לאפשר שהנתיב יתחיל ב-'-' כדי שלא יתפרש כאופציה של git
        if file_path.startswith("-"):
            return False

        # מניעת path traversal וקטעי נתיב ריקים (//)
        parts = file_path.split("/")
        for part in parts:
            if part in ("", ".", ".."):
                return False

        return True

    def _validate_repo_ref(self, ref: str) -> bool:
        """ולידציה בסיסית ל-ref לפני שילוב בפקודות git (best-effort)."""
        if not isinstance(ref, str):
            return False
        ref = ref.strip()
        if not ref:
            return False
        if "\x00" in ref:
            return False
        # מניעת מצב שבו ref מזוהה כ-flag
        if ref.startswith("-"):
            return False
        # הימנעות מרווחים/תווי שליטה
        if any(ch.isspace() for ch in ref):
            return False
        return True

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

        # ולידציה של נתיבים לפני הרצת git (מניעת uncontrolled command line)
        if not self._validate_repo_file_path(file_path):
            logger.warning("Rejected invalid repo file path: %r", file_path)
            return None
        if not self._validate_repo_ref(ref):
            logger.warning("Rejected invalid repo ref: %r", ref)
            return None

        repo_path = self._get_repo_path(repo_name)

        result = self._run_git_command(["git", "show", f"{ref}:{file_path}"], cwd=repo_path, timeout=30)

        if result.success:
            return result.stdout

        return None

    def list_all_files(self, repo_name: str, ref: str = "HEAD") -> Optional[List[str]]:
        """
        רשימת כל הקבצים בריפו

        Returns:
            רשימת נתיבי קבצים
        """
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

        # בניית הפקודה - סדר נכון ל-Bare Repository!
        # git grep [options] <pattern> <revision> -- <pathspec>
        cmd = ["git", "grep", "-n", "-I", "--break", "--heading"]

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
            result = self._run_git_command(cmd, cwd=repo_path, timeout=timeout)

            if result.return_code == 1:
                # git grep מחזיר 1 כשאין תוצאות
                return {"results": [], "total_count": 0, "truncated": False}

            if not result.success:
                return {"error": "search_failed", "message": result.stderr[:200], "results": []}

            # פרסור התוצאות
            results = self._parse_grep_output(result.stdout, max_results)

            return {
                "results": results,
                "total_count": len(results),
                "truncated": len(results) >= max_results,
                "query": query,
            }

        except Exception as e:
            logger.exception(f"Search error: {e}")
            return {"error": "search_error", "results": []}

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


# Singleton instance
_mirror_service: Optional[GitMirrorService] = None


def get_mirror_service() -> GitMirrorService:
    """קבלת instance יחיד של השירות"""
    global _mirror_service
    if _mirror_service is None:
        _mirror_service = GitMirrorService()
    return _mirror_service

