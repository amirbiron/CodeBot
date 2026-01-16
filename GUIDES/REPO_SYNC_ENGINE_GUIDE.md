# מדריך מימוש: Repo Sync Engine עם Render Disk

> **מטרה:** סנכרון אוטומטי של כל קוד הריפו ל-WebApp עם Git Mirror מקומי

---

## תוכן עניינים

1. [סקירת הארכיטקטורה](#סקירת-הארכיטקטורה)
2. [הגדרת Render Disk](#הגדרת-render-disk)
3. [מימוש GitMirrorService](#מימוש-gitmirrorservice)
4. [מימוש CodeIndexer](#מימוש-codeindexer)
5. [מימוש SearchService עם git grep](#מימוש-searchservice-עם-git-grep)
6. [Webhook Handler](#webhook-handler)
7. [Background Tasks](#background-tasks)
8. [WebApp Routes](#webapp-routes)
9. [UI Components](#ui-components)
10. [הגדרות Render](#הגדרות-render)
11. [בדיקות](#בדיקות)
12. [Troubleshooting](#troubleshooting)

---

## סקירת הארכיטקטורה

```
┌─────────────────────────────────────────────────────────────┐
│                   GitHub Repository                          │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           │ Webhook (push event)
                           ↓
┌─────────────────────────────────────────────────────────────┐
│                  Flask App (Webhook Handler)                 │
│                  POST /api/webhooks/github                   │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           │ Trigger Background Job
                           ↓
┌─────────────────────────────────────────────────────────────┐
│              Background Worker (asyncio/threading)           │
│  ┌─────────────────────────────────────────────────────────┐│
│  │ 1. git fetch origin (delta only)                        ││
│  │ 2. git diff-tree old_sha..new_sha                       ││
│  │ 3. Update MongoDB metadata                              ││
│  └─────────────────────────────────────────────────────────┘│
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ↓
┌─────────────────────────────────────────────────────────────┐
│                     Storage Layer                            │
│  ┌───────────────────────┐    ┌────────────────────────────┐│
│  │    Render Disk        │    │       MongoDB              ││
│  │    /var/data/repos/   │    │                            ││
│  │                       │    │  repo_files:               ││
│  │  CodeBot.git/         │    │   - path                   ││
│  │   (bare mirror)       │    │   - language               ││
│  │                       │    │   - size, lines            ││
│  │  • Full git history   │    │   - imports, functions     ││
│  │  • Fast git grep      │    │   - commit_sha             ││
│  │  • Delta fetch        │    │                            ││
│  └───────────────────────┘    │  repo_metadata:            ││
│                               │   - last_synced_sha        ││
│                               │   - sync_status            ││
│                               └────────────────────────────┘│
└─────────────────────────────────────────────────────────────┘
                           │
                           ↓
┌─────────────────────────────────────────────────────────────┐
│                       WebApp UI                              │
│  • Tree View (metadata from MongoDB)                         │
│  • File Viewer (content from git show)                       │
│  • Search (git grep on mirror)                               │
└─────────────────────────────────────────────────────────────┘
```

### למה Render Disk?

| אפשרות | יתרונות | חסרונות |
|--------|---------|---------|
| **Render Disk** | Persistent, מהיר, פשוט | עלות (~$7/חודש ל-10GB) |
| MongoDB GridFS | כבר קיים | איטי, תופס מקום ב-DB |
| GitHub API בלבד | ללא אחסון מקומי | Rate limits, איטי |
| Volume mount | חינמי | לא persistent ב-Render |

**Render Disk הוא הפתרון המומלץ** כי:
- נשאר אחרי restart/deploy
- גישה מהירה לקבצים
- `git grep` עובד ישירות
- הפרדה מ-MongoDB

---

## הגדרת Render Disk

### 1. יצירת Disk ב-Render Dashboard

```yaml
# render.yaml (Blueprint)
services:
  - type: web
    name: codebot
    env: python
    plan: starter  # או גבוה יותר
    disk:
      name: repo-mirror
      mountPath: /var/data/repos
      sizeGB: 10  # התאם לגודל הריפו שלך
```

### 2. עדכון Environment Variables

```bash
# .env או Render Environment

# === Git Mirror ===
REPO_MIRROR_PATH=/var/data/repos
REPO_NAME=CodeBot
GITHUB_REPO_URL=https://github.com/amirbiron/CodeBot.git

# === Authentication ===
# חובה ל-Private Repos!
GITHUB_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxx

# === Webhook Security ===
GITHUB_WEBHOOK_SECRET=your-webhook-secret-here

# === Worker Configuration ===
# אופציה 1: Worker בודד (פשוט, מומלץ להתחלה)
WEB_CONCURRENCY=1

# אופציה 2: Multi-workers (scalable, דורש MongoDB-based queue)
# WEB_CONCURRENCY=2
```

> **חשוב:** אם `WEB_CONCURRENCY > 1`, חובה להשתמש ב-MongoDB-based Queue
> (כפי שמתואר בקוד `repo_sync_service.py`) כדי שכל ה-workers יראו את אותם jobs.

### 3. בדיקת הדיסק

```python
# בקוד או ב-shell
import os
from pathlib import Path

mirror_path = Path(os.getenv("REPO_MIRROR_PATH", "/var/data/repos"))
print(f"Disk exists: {mirror_path.exists()}")
print(f"Disk writable: {os.access(mirror_path, os.W_OK)}")
```

---

## מימוש GitMirrorService

צור קובץ `services/git_mirror_service.py`:

```python
"""
Git Mirror Service - ניהול מראה Git מקומי על Render Disk

מספק:
- יצירת mirror ראשוני
- fetch עדכונים (delta)
- קריאת תוכן קבצים
- השוואת commits
- חיפוש עם git grep
"""

import subprocess
import logging
import os
from pathlib import Path
from typing import Optional, Dict, List, Any
from dataclasses import dataclass
from functools import lru_cache

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
        self.base_path = Path(
            base_path or 
            os.getenv("REPO_MIRROR_PATH", "/var/data/repos")
        )
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
            return url.replace(
                "https://github.com/",
                f"https://oauth2:{token}@github.com/"
            )
        elif url.startswith("https://"):
            # Generic HTTPS URL
            return url.replace("https://", f"https://oauth2:{token}@")
        
        return url
    
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
    
    def _run_git_command(
        self,
        cmd: List[str],
        cwd: Optional[Path] = None,
        timeout: int = 60
    ) -> GitCommandResult:
        """
        הרצת פקודת Git בצורה בטוחה
        
        Args:
            cmd: פקודת Git כרשימה
            cwd: תיקיית עבודה
            timeout: timeout בשניות
            
        Returns:
            GitCommandResult עם התוצאות
        """
        try:
            result = subprocess.run(
                cmd,
                cwd=str(cwd) if cwd else None,
                capture_output=True,
                text=True,
                timeout=timeout
            )
            
            success = result.returncode == 0
            
            if not success:
                logger.warning(
                    f"Git command returned {result.returncode}: "
                    f"{' '.join(cmd)}\nstderr: {result.stderr[:500]}"
                )
            
            return GitCommandResult(
                success=success,
                stdout=result.stdout,
                stderr=result.stderr,
                return_code=result.returncode
            )
            
        except subprocess.TimeoutExpired:
            logger.error(f"Git command timeout ({timeout}s): {' '.join(cmd)}")
            return GitCommandResult(
                success=False,
                stdout="",
                stderr=f"Command timed out after {timeout}s",
                return_code=-1
            )
            
        except Exception as e:
            logger.exception(f"Git command failed: {' '.join(cmd)}")
            return GitCommandResult(
                success=False,
                stdout="",
                stderr=str(e),
                return_code=-1
            )
    
    # ========== Mirror Management ==========
    
    def init_mirror(
        self,
        repo_url: str,
        repo_name: str,
        timeout: int = 600
    ) -> Dict[str, Any]:
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
            logger.info(f"Mirror already exists: {repo_path}")
            return {
                "success": True,
                "path": str(repo_path),
                "message": "Mirror already exists",
                "already_existed": True
            }
        
        # לוג ללא ה-token!
        logger.info(f"Creating mirror: {repo_url} -> {repo_path}")
        
        # הזרקת token ל-Private Repos
        auth_url = self._get_authenticated_url(repo_url)
        
        # Clone as bare mirror
        result = self._run_git_command(
            ["git", "clone", "--mirror", auth_url, str(repo_path)],
            timeout=timeout
        )
        
        if result.success:
            logger.info(f"Mirror created successfully: {repo_path}")
            return {
                "success": True,
                "path": str(repo_path),
                "message": "Mirror created successfully",
                "already_existed": False
            }
        else:
            logger.error(f"Failed to create mirror: {result.stderr}")
            return {
                "success": False,
                "path": None,
                "message": f"Clone failed: {result.stderr[:200]}",
                "error": result.stderr
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
                "action_needed": "init_mirror"
            }
        
        logger.info(f"Fetching updates for {repo_name}")
        
        result = self._run_git_command(
            ["git", "fetch", "--all", "--prune"],
            cwd=repo_path,
            timeout=timeout
        )
        
        if result.success:
            return {
                "success": True,
                "message": "Fetch completed",
                "output": result.stdout[:500] if result.stdout else "No output"
            }
        else:
            # זיהוי סוגי שגיאות
            error_type = self._classify_git_error(result.stderr)
            return {
                "success": False,
                "error_type": error_type,
                "message": result.stderr[:200],
                "retry_recommended": error_type == "network_error"
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
        total_size = sum(
            f.stat().st_size for f in repo_path.rglob('*') if f.is_file()
        )
        
        # SHA הנוכחי
        current_sha = self.get_current_sha(repo_name)
        
        return {
            "path": str(repo_path),
            "size_bytes": total_size,
            "size_mb": round(total_size / (1024 * 1024), 2),
            "current_sha": current_sha,
            "exists": True
        }
    
    # ========== SHA & Commits ==========
    
    def get_current_sha(
        self,
        repo_name: str,
        branch: str = "main"
    ) -> Optional[str]:
        """
        קבלת SHA הנוכחי של branch
        
        Args:
            repo_name: שם הריפו
            branch: שם ה-branch (main/master)
            
        Returns:
            SHA string או None
        """
        repo_path = self._get_repo_path(repo_name)
        
        # ניסיון עם origin/branch
        result = self._run_git_command(
            ["git", "rev-parse", f"refs/heads/{branch}"],
            cwd=repo_path,
            timeout=10
        )
        
        if result.success:
            return result.stdout.strip()
        
        # fallback ל-HEAD
        result = self._run_git_command(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_path,
            timeout=10
        )
        
        return result.stdout.strip() if result.success else None
    
    def get_changed_files(
        self,
        repo_name: str,
        old_sha: str,
        new_sha: str
    ) -> Optional[Dict[str, List[str]]]:
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
        
        result = self._run_git_command([
            "git", "diff-tree",
            "--no-commit-id",
            "--name-status",
            "-r",
            "-M",  # detect renames
            old_sha, new_sha
        ], cwd=repo_path, timeout=60)
        
        if not result.success:
            logger.error(f"Failed to get changes: {result.stderr}")
            return None
        
        changes = {
            "added": [],
            "modified": [],
            "removed": [],
            "renamed": []
        }
        
        for line in result.stdout.strip().split('\n'):
            if not line:
                continue
            
            parts = line.split('\t')
            if len(parts) < 2:
                continue
            
            status = parts[0]
            
            if status == 'A':
                changes["added"].append(parts[1])
            elif status == 'M':
                changes["modified"].append(parts[1])
            elif status == 'D':
                changes["removed"].append(parts[1])
            elif status.startswith('R'):
                # Rename: R100 old_path new_path
                if len(parts) >= 3:
                    changes["renamed"].append({
                        "old": parts[1],
                        "new": parts[2]
                    })
        
        return changes
    
    # ========== File Content ==========
    
    def get_file_content(
        self,
        repo_name: str,
        file_path: str,
        ref: str = "HEAD"
    ) -> Optional[str]:
        """
        קריאת תוכן קובץ מה-mirror
        
        Args:
            repo_name: שם הריפו
            file_path: נתיב הקובץ בריפו
            ref: commit SHA או branch (ברירת מחדל: HEAD)
            
        Returns:
            תוכן הקובץ או None
        """
        repo_path = self._get_repo_path(repo_name)
        
        result = self._run_git_command(
            ["git", "show", f"{ref}:{file_path}"],
            cwd=repo_path,
            timeout=30
        )
        
        if result.success:
            return result.stdout
        
        return None
    
    def list_all_files(
        self,
        repo_name: str,
        ref: str = "HEAD"
    ) -> Optional[List[str]]:
        """
        רשימת כל הקבצים בריפו
        
        Returns:
            רשימת נתיבי קבצים
        """
        repo_path = self._get_repo_path(repo_name)
        
        result = self._run_git_command(
            ["git", "ls-tree", "-r", "--name-only", ref],
            cwd=repo_path,
            timeout=60
        )
        
        if result.success:
            return [f for f in result.stdout.strip().split('\n') if f]
        
        return None
    
    def get_file_info(
        self,
        repo_name: str,
        file_path: str,
        ref: str = "HEAD"
    ) -> Optional[Dict[str, Any]]:
        """
        מידע על קובץ (גודל, סוג, וכו')
        """
        repo_path = self._get_repo_path(repo_name)
        
        # קבלת מידע עם ls-tree
        result = self._run_git_command(
            ["git", "ls-tree", "-l", ref, "--", file_path],
            cwd=repo_path,
            timeout=10
        )
        
        if not result.success or not result.stdout.strip():
            return None
        
        # פורמט: mode type sha size path
        parts = result.stdout.strip().split()
        if len(parts) >= 5:
            return {
                "mode": parts[0],
                "type": parts[1],
                "sha": parts[2],
                "size": int(parts[3]) if parts[3] != '-' else 0,
                "path": parts[4]
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
        ref: str = "HEAD"
    ) -> Dict[str, Any]:
        """
        חיפוש בקוד עם git grep (מהיר מאוד!)
        
        **חשוב:** ב-Bare Repository (mirror) יש לשים לב לסדר הארגומנטים:
        git grep [options] <pattern> <revision> -- <pathspec>
        
        Args:
            repo_name: שם הריפו
            query: מחרוזת/regex לחיפוש
            max_results: מקסימום תוצאות
            timeout: timeout בשניות
            file_pattern: סינון קבצים (למשל "*.py")
            case_sensitive: case sensitive?
            ref: revision לחיפוש (HEAD, branch name, או SHA)
            
        Returns:
            dict עם results, total_count, truncated
        """
        repo_path = self._get_repo_path(repo_name)
        
        if not repo_path.exists():
            return {"error": "mirror_not_found", "results": []}
        
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
        # ב-Bare repo עדיף להשתמש ב-refs/heads/main במקום HEAD
        cmd.append(ref)
        
        # 3. הפרדה בין revision לבין pathspec
        cmd.append("--")
        
        # 4. File pattern (pathspec) - חייב לבוא אחרי "--"
        if file_pattern:
            cmd.append(file_pattern)
        else:
            cmd.append(".")  # כל הקבצים
        
        try:
            result = self._run_git_command(cmd, cwd=repo_path, timeout=timeout)
            
            if result.return_code == 1:
                # git grep מחזיר 1 כשאין תוצאות
                return {"results": [], "total_count": 0, "truncated": False}
            
            if not result.success:
                return {
                    "error": "search_failed",
                    "message": result.stderr[:200],
                    "results": []
                }
            
            # פרסור התוצאות
            results = self._parse_grep_output(result.stdout, max_results)
            
            return {
                "results": results,
                "total_count": len(results),
                "truncated": len(results) >= max_results,
                "query": query
            }
            
        except Exception as e:
            logger.exception(f"Search error: {e}")
            return {"error": str(e), "results": []}
    
    def _is_regex(self, query: str) -> bool:
        """בדיקה אם ה-query הוא regex"""
        regex_chars = r'.*+?[]{}()^$|\\'
        return any(c in query for c in regex_chars)
    
    def _parse_grep_output(
        self,
        output: str,
        max_results: int
    ) -> List[Dict[str, Any]]:
        """
        פרסור פלט git grep
        
        פורמט הפלט עם --break --heading:
        filename
        line_num:content
        line_num:content
        
        filename2
        ...
        """
        results = []
        current_file = None
        
        for line in output.split('\n'):
            if not line:
                continue
            
            # שורה ללא ":" היא שם קובץ (heading)
            if ':' not in line or (line[0] != ' ' and ':' not in line[:50]):
                # בדיקה אם זה נתיב קובץ
                if '/' in line or line.endswith(('.py', '.js', '.ts', '.html', '.css', '.md')):
                    current_file = line.strip()
                continue
            
            # שורת תוצאה: line_num:content
            if current_file:
                parts = line.split(':', 1)
                if len(parts) == 2:
                    try:
                        line_num = int(parts[0].strip())
                        content = parts[1]
                        
                        results.append({
                            "path": current_file,
                            "line": line_num,
                            "content": content.strip()[:500]  # הגבלת אורך
                        })
                        
                        if len(results) >= max_results:
                            return results
                            
                    except ValueError:
                        continue
        
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
        result = self._run_git_command(
            ["git", "rev-list", "--count", "HEAD"],
            cwd=repo_path,
            timeout=30
        )
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
            "file_types": dict(sorted(
                file_types.items(),
                key=lambda x: x[1],
                reverse=True
            )[:20])  # Top 20
        }


# Singleton instance
_mirror_service: Optional[GitMirrorService] = None

def get_mirror_service() -> GitMirrorService:
    """קבלת instance יחיד של השירות"""
    global _mirror_service
    if _mirror_service is None:
        _mirror_service = GitMirrorService()
    return _mirror_service
```

---

## מימוש CodeIndexer

צור קובץ `services/code_indexer.py`:

```python
"""
Code Indexer - אינדוקס קבצי קוד ב-MongoDB

מאנדקס metadata בלבד (לא את התוכן המלא!):
- נתיב, שפה, גודל
- imports, functions, classes
- search_text מצומצם
"""

import re
import logging
from typing import List, Optional, Dict, Any
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


class CodeIndexer:
    """
    אינדוקס metadata של קבצי קוד ב-MongoDB
    
    מה נשמר ב-DB:
    - path, language, size, lines
    - imports, functions, classes (semantic info)
    - search_text (לחיפוש מהיר)
    
    מה לא נשמר:
    - תוכן מלא (נקרא מ-git mirror)
    
    **הערה חשובה על Regex vs AST:**
    
    הקוד הזה משתמש ב-Regex לפשטות, אבל יש לזה חסרונות:
    - Regex יכול לתפוס מילים בתוך מחרוזות או הערות
    - `def` בתוך docstring יזוהה בטעות כפונקציה
    
    **לפרודקשן מומלץ:**
    - Python: להשתמש במודול `ast` המובנה (מהיר ומדויק 100%)
    - JavaScript/TypeScript: להשתמש ב-`@babel/parser` או `typescript`
    - שאר השפות: Regex מספיק טוב (או tree-sitter)
    
    דוגמה לשימוש ב-AST לפייתון:
    
    ```python
    import ast
    
    def extract_functions_with_ast(content: str) -> List[str]:
        try:
            tree = ast.parse(content)
            return [
                node.name for node in ast.walk(tree)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            ]
        except SyntaxError:
            return []  # fallback to regex
    ```
    """
    
    # דפוסים להתעלמות
    IGNORE_PATTERNS = [
        'node_modules/',
        '__pycache__/',
        '.git/',
        'venv/',
        '.venv/',
        '.pytest_cache/',
        'dist/',
        'build/',
        '.next/',
        '.nuxt/',
        'coverage/',
        '.coverage',
        '*.pyc',
        '*.pyo',
        '*.jpg',
        '*.jpeg',
        '*.png',
        '*.gif',
        '*.svg',
        '*.ico',
        '*.pdf',
        '*.mp4',
        '*.mp3',
        '*.zip',
        '*.tar',
        '*.gz',
        '*.exe',
        '*.dll',
        '*.so',
        '*.woff',
        '*.woff2',
        '*.ttf',
        '*.eot',
        'package-lock.json',
        'yarn.lock',
        'poetry.lock',
        'Pipfile.lock',
        '.DS_Store',
        'Thumbs.db',
    ]
    
    # סיומות קוד לאינדוקס
    CODE_EXTENSIONS = [
        '.py', '.pyi', '.pyx',
        '.js', '.jsx', '.mjs',
        '.ts', '.tsx',
        '.html', '.htm',
        '.css', '.scss', '.sass', '.less',
        '.json', '.jsonc',
        '.yml', '.yaml',
        '.md', '.rst', '.txt',
        '.sh', '.bash', '.zsh',
        '.sql',
        '.go',
        '.rs',
        '.java', '.kt', '.scala',
        '.c', '.cpp', '.h', '.hpp',
        '.rb',
        '.php',
        '.swift',
        '.r', '.R',
        '.vue', '.svelte',
        '.xml', '.xsl',
        '.ini', '.cfg', '.conf', '.toml',
        '.dockerfile', '.containerfile',
        '.tf', '.hcl',
        '.graphql', '.gql',
    ]
    
    # גודל מקסימלי לאינדוקס (500KB)
    MAX_FILE_SIZE = 500_000
    
    def __init__(self, db=None):
        """
        Args:
            db: MongoDB database instance
        """
        self.db = db
    
    def should_index(self, file_path: str) -> bool:
        """
        האם לאנדקס קובץ זה?
        
        Args:
            file_path: נתיב הקובץ
            
        Returns:
            True אם צריך לאנדקס
        """
        # בדיקת דפוסי התעלמות
        for pattern in self.IGNORE_PATTERNS:
            pattern_clean = pattern.replace('*', '')
            if pattern_clean in file_path:
                return False
        
        # בדיקת סיומת
        path = Path(file_path)
        
        # קבצים ללא סיומת ספציפיים
        if path.name in ['Dockerfile', 'Makefile', 'Jenkinsfile', '.gitignore', '.env.example']:
            return True
        
        # סיומות מותרות
        if path.suffix.lower() in self.CODE_EXTENSIONS:
            return True
        
        return False
    
    def index_file(
        self,
        repo_name: str,
        file_path: str,
        content: str,
        commit_sha: str = "HEAD"
    ) -> bool:
        """
        אינדוקס קובץ בודד ב-MongoDB
        
        Args:
            repo_name: שם הריפו
            file_path: נתיב הקובץ
            content: תוכן הקובץ
            commit_sha: SHA של הקומיט
            
        Returns:
            True אם הצליח
        """
        if not self.db:
            logger.error("No database connection")
            return False
        
        # בדיקת גודל
        if len(content) > self.MAX_FILE_SIZE:
            logger.info(f"Skipping large file ({len(content)} bytes): {file_path}")
            return False
        
        # זיהוי שפה
        language = self._detect_language(file_path)
        
        # חילוץ מידע סמנטי
        imports = self._extract_imports(content, language)
        functions = self._extract_functions(content, language)
        classes = self._extract_classes(content, language)
        
        # יצירת טקסט לחיפוש
        search_text = self._create_search_text(
            file_path, imports, functions, classes
        )
        
        # Document לשמירה
        doc = {
            "repo_name": repo_name,
            "path": file_path,
            "language": language,
            "size": len(content),
            "lines": content.count('\n') + 1,
            "commit_sha": commit_sha,
            "last_indexed": datetime.utcnow(),
            "imports": imports,
            "functions": functions,
            "classes": classes,
            "search_text": search_text
        }
        
        try:
            self.db.repo_files.update_one(
                {"repo_name": repo_name, "path": file_path},
                {"$set": doc},
                upsert=True
            )
            return True
            
        except Exception as e:
            logger.exception(f"Failed to index {file_path}: {e}")
            return False
    
    def remove_file(self, repo_name: str, file_path: str) -> bool:
        """מחיקת קובץ מהאינדקס"""
        if not self.db:
            return False
        
        try:
            result = self.db.repo_files.delete_one({
                "repo_name": repo_name,
                "path": file_path
            })
            return result.deleted_count > 0
            
        except Exception as e:
            logger.exception(f"Failed to remove {file_path}: {e}")
            return False
    
    def remove_files(self, repo_name: str, file_paths: List[str]) -> int:
        """מחיקת מספר קבצים מהאינדקס"""
        if not self.db or not file_paths:
            return 0
        
        try:
            result = self.db.repo_files.delete_many({
                "repo_name": repo_name,
                "path": {"$in": file_paths}
            })
            return result.deleted_count
            
        except Exception as e:
            logger.exception(f"Failed to remove files: {e}")
            return 0
    
    def _detect_language(self, file_path: str) -> str:
        """זיהוי שפת התכנות לפי הסיומת"""
        ext = Path(file_path).suffix.lower()
        
        LANGUAGE_MAP = {
            '.py': 'python',
            '.pyi': 'python',
            '.js': 'javascript',
            '.jsx': 'javascript',
            '.mjs': 'javascript',
            '.ts': 'typescript',
            '.tsx': 'typescript',
            '.html': 'html',
            '.htm': 'html',
            '.css': 'css',
            '.scss': 'scss',
            '.sass': 'sass',
            '.less': 'less',
            '.json': 'json',
            '.yml': 'yaml',
            '.yaml': 'yaml',
            '.md': 'markdown',
            '.rst': 'rst',
            '.sh': 'shell',
            '.bash': 'shell',
            '.sql': 'sql',
            '.go': 'go',
            '.rs': 'rust',
            '.java': 'java',
            '.kt': 'kotlin',
            '.c': 'c',
            '.cpp': 'cpp',
            '.h': 'c',
            '.hpp': 'cpp',
            '.rb': 'ruby',
            '.php': 'php',
            '.swift': 'swift',
            '.r': 'r',
            '.vue': 'vue',
            '.svelte': 'svelte',
        }
        
        return LANGUAGE_MAP.get(ext, 'text')
    
    def _extract_imports(self, content: str, language: str) -> List[str]:
        """חילוץ imports מהקוד"""
        imports = []
        
        if language == 'python':
            # import x, from x import y
            pattern = r'(?:from|import)\s+([\w.]+)'
            imports = re.findall(pattern, content)
            
        elif language in ['javascript', 'typescript']:
            # import x from 'y'
            # require('y')
            pattern1 = r'import\s+.+?\s+from\s+[\'"]([^"\']+)[\'"]'
            pattern2 = r'require\s*\(\s*[\'"]([^"\']+)[\'"]\s*\)'
            imports = re.findall(pattern1, content) + re.findall(pattern2, content)
            
        elif language == 'go':
            # import "x"
            pattern = r'import\s+(?:"([^"]+)"|\(\s*"([^"]+)")'
            matches = re.findall(pattern, content)
            imports = [m[0] or m[1] for m in matches]
        
        # ייחודיים וחיתוך
        return list(set(imports))[:30]
    
    def _extract_functions(self, content: str, language: str) -> List[str]:
        """חילוץ שמות פונקציות"""
        functions = []
        
        if language == 'python':
            # def func_name(
            # async def func_name(
            pattern = r'(?:async\s+)?def\s+(\w+)\s*\('
            functions = re.findall(pattern, content)
            
        elif language in ['javascript', 'typescript']:
            # function name(
            # const name = (
            # const name = async (
            pattern1 = r'function\s+(\w+)\s*\('
            pattern2 = r'(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?\('
            pattern3 = r'(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?function'
            functions = (
                re.findall(pattern1, content) +
                re.findall(pattern2, content) +
                re.findall(pattern3, content)
            )
            
        elif language == 'go':
            # func name(
            pattern = r'func\s+(?:\([^)]+\)\s+)?(\w+)\s*\('
            functions = re.findall(pattern, content)
        
        return list(set(functions))[:50]
    
    def _extract_classes(self, content: str, language: str) -> List[str]:
        """חילוץ שמות מחלקות"""
        classes = []
        
        if language == 'python':
            pattern = r'class\s+(\w+)'
            classes = re.findall(pattern, content)
            
        elif language in ['javascript', 'typescript', 'java', 'kotlin']:
            pattern = r'class\s+(\w+)'
            classes = re.findall(pattern, content)
            
        elif language == 'go':
            # type Name struct
            pattern = r'type\s+(\w+)\s+struct'
            classes = re.findall(pattern, content)
        
        return list(set(classes))[:30]
    
    def _create_search_text(
        self,
        file_path: str,
        imports: List[str],
        functions: List[str],
        classes: List[str]
    ) -> str:
        """
        יצירת טקסט אופטימלי לחיפוש
        
        הערה: לחיפוש מלא משתמשים ב-git grep,
        זה רק לחיפוש metadata מהיר.
        """
        parts = []
        
        # שם הקובץ ורכיבי הנתיב
        parts.append(file_path)
        parts.extend(Path(file_path).parts)
        
        # imports, functions, classes
        parts.extend(imports)
        parts.extend(functions)
        parts.extend(classes)
        
        # הרכבת הטקסט
        text = ' '.join(parts)
        
        # הגבלת גודל
        return text[:2000]


# Factory function
def create_indexer(db=None) -> CodeIndexer:
    """יצירת instance של CodeIndexer"""
    return CodeIndexer(db)
```

---

## מימוש SearchService עם git grep

צור קובץ `services/repo_search_service.py`:

```python
"""
Repository Search Service

חיפוש בקוד עם git grep (מהיר וחזק!)
"""

import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass

from services.git_mirror_service import get_mirror_service

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    """תוצאת חיפוש בודדת"""
    path: str
    line: int
    content: str
    context_before: List[str] = None
    context_after: List[str] = None


class RepoSearchService:
    """
    שירות חיפוש בקוד
    
    משלב:
    - git grep לחיפוש מלא בתוכן
    - MongoDB לחיפוש metadata
    """
    
    def __init__(self, db=None):
        self.db = db
        self.git_service = get_mirror_service()
    
    def search(
        self,
        repo_name: str,
        query: str,
        search_type: str = "content",  # content, filename, function, class
        file_pattern: Optional[str] = None,
        language: Optional[str] = None,
        case_sensitive: bool = False,
        max_results: int = 50
    ) -> Dict[str, Any]:
        """
        חיפוש מאוחד בקוד
        
        Args:
            repo_name: שם הריפו
            query: מחרוזת לחיפוש
            search_type: סוג החיפוש
            file_pattern: סינון קבצים (*.py)
            language: סינון לפי שפה
            case_sensitive: case sensitive?
            max_results: מקסימום תוצאות
            
        Returns:
            dict עם results, total, query info
        """
        if not query or len(query.strip()) < 2:
            return {
                "error": "Query too short",
                "results": []
            }
        
        query = query.strip()
        
        # בחירת שיטת חיפוש
        if search_type == "content":
            return self._search_content(
                repo_name, query, file_pattern,
                case_sensitive, max_results
            )
        elif search_type == "filename":
            return self._search_filename(repo_name, query, max_results)
        elif search_type == "function":
            return self._search_functions(repo_name, query, language, max_results)
        elif search_type == "class":
            return self._search_classes(repo_name, query, language, max_results)
        else:
            return {"error": f"Unknown search type: {search_type}", "results": []}
    
    def _search_content(
        self,
        repo_name: str,
        query: str,
        file_pattern: Optional[str],
        case_sensitive: bool,
        max_results: int
    ) -> Dict[str, Any]:
        """חיפוש תוכן עם git grep"""
        
        # המרת file pattern לפורמט git grep
        git_pattern = None
        if file_pattern:
            # "*.py" -> "*.py"
            git_pattern = file_pattern
        
        result = self.git_service.search_with_git_grep(
            repo_name=repo_name,
            query=query,
            max_results=max_results,
            timeout=10,
            file_pattern=git_pattern,
            case_sensitive=case_sensitive
        )
        
        if "error" in result:
            return result
        
        # העשרת התוצאות עם metadata מ-MongoDB
        if self.db and result.get("results"):
            paths = list(set(r["path"] for r in result["results"]))
            
            # שליפת metadata
            metadata_map = {}
            try:
                cursor = self.db.repo_files.find(
                    {"repo_name": repo_name, "path": {"$in": paths}},
                    {"path": 1, "language": 1, "size": 1}
                )
                for doc in cursor:
                    metadata_map[doc["path"]] = doc
            except Exception as e:
                logger.warning(f"Failed to fetch metadata: {e}")
            
            # הוספת metadata לתוצאות
            for r in result["results"]:
                meta = metadata_map.get(r["path"], {})
                r["language"] = meta.get("language", "unknown")
                r["size"] = meta.get("size", 0)
        
        return {
            "results": result["results"],
            "total": result.get("total_count", len(result["results"])),
            "truncated": result.get("truncated", False),
            "search_type": "content",
            "query": query
        }
    
    def _search_filename(
        self,
        repo_name: str,
        query: str,
        max_results: int
    ) -> Dict[str, Any]:
        """חיפוש לפי שם קובץ"""
        
        if not self.db:
            # Fallback ל-git ls-tree
            all_files = self.git_service.list_all_files(repo_name) or []
            query_lower = query.lower()
            
            results = [
                {"path": f, "line": 0, "content": ""}
                for f in all_files
                if query_lower in f.lower()
            ][:max_results]
            
            return {
                "results": results,
                "total": len(results),
                "search_type": "filename",
                "query": query
            }
        
        # חיפוש ב-MongoDB (מהיר יותר)
        try:
            cursor = self.db.repo_files.find(
                {
                    "repo_name": repo_name,
                    "path": {"$regex": query, "$options": "i"}
                },
                {"path": 1, "language": 1, "size": 1, "lines": 1}
            ).limit(max_results)
            
            results = [
                {
                    "path": doc["path"],
                    "language": doc.get("language", "unknown"),
                    "size": doc.get("size", 0),
                    "lines": doc.get("lines", 0)
                }
                for doc in cursor
            ]
            
            return {
                "results": results,
                "total": len(results),
                "search_type": "filename",
                "query": query
            }
            
        except Exception as e:
            logger.exception(f"Filename search failed: {e}")
            return {"error": str(e), "results": []}
    
    def _search_functions(
        self,
        repo_name: str,
        query: str,
        language: Optional[str],
        max_results: int
    ) -> Dict[str, Any]:
        """חיפוש פונקציות"""
        
        if not self.db:
            return {"error": "Database required for function search", "results": []}
        
        try:
            filter_query = {
                "repo_name": repo_name,
                "functions": {"$regex": query, "$options": "i"}
            }
            
            if language:
                filter_query["language"] = language
            
            cursor = self.db.repo_files.find(
                filter_query,
                {"path": 1, "language": 1, "functions": 1}
            ).limit(max_results)
            
            results = []
            for doc in cursor:
                # מציאת הפונקציות שמתאימות
                matching = [
                    f for f in doc.get("functions", [])
                    if query.lower() in f.lower()
                ]
                
                for func_name in matching:
                    results.append({
                        "path": doc["path"],
                        "function": func_name,
                        "language": doc.get("language", "unknown")
                    })
            
            return {
                "results": results[:max_results],
                "total": len(results),
                "search_type": "function",
                "query": query
            }
            
        except Exception as e:
            logger.exception(f"Function search failed: {e}")
            return {"error": str(e), "results": []}
    
    def _search_classes(
        self,
        repo_name: str,
        query: str,
        language: Optional[str],
        max_results: int
    ) -> Dict[str, Any]:
        """חיפוש מחלקות"""
        
        if not self.db:
            return {"error": "Database required for class search", "results": []}
        
        try:
            filter_query = {
                "repo_name": repo_name,
                "classes": {"$regex": query, "$options": "i"}
            }
            
            if language:
                filter_query["language"] = language
            
            cursor = self.db.repo_files.find(
                filter_query,
                {"path": 1, "language": 1, "classes": 1}
            ).limit(max_results)
            
            results = []
            for doc in cursor:
                matching = [
                    c for c in doc.get("classes", [])
                    if query.lower() in c.lower()
                ]
                
                for class_name in matching:
                    results.append({
                        "path": doc["path"],
                        "class": class_name,
                        "language": doc.get("language", "unknown")
                    })
            
            return {
                "results": results[:max_results],
                "total": len(results),
                "search_type": "class",
                "query": query
            }
            
        except Exception as e:
            logger.exception(f"Class search failed: {e}")
            return {"error": str(e), "results": []}


def create_search_service(db=None) -> RepoSearchService:
    """Factory function"""
    return RepoSearchService(db)
```

---

## Webhook Handler

צור קובץ `webapp/routes/webhooks.py`:

```python
"""
GitHub Webhook Handler

מטפל באירועי push מ-GitHub ומפעיל סנכרון
"""

import hmac
import hashlib
import logging
import os
from flask import Blueprint, request, jsonify, current_app

logger = logging.getLogger(__name__)

webhooks_bp = Blueprint('webhooks', __name__, url_prefix='/api/webhooks')


def verify_github_signature(payload_body: bytes, signature: str) -> bool:
    """
    אימות חתימת GitHub Webhook
    
    Args:
        payload_body: גוף הבקשה (bytes)
        signature: ערך X-Hub-Signature-256
        
    Returns:
        True אם החתימה תקינה
    """
    secret = os.getenv("GITHUB_WEBHOOK_SECRET", "")
    
    if not secret:
        logger.warning("GITHUB_WEBHOOK_SECRET not set!")
        return False
    
    if not signature or not signature.startswith("sha256="):
        return False
    
    expected_signature = hmac.new(
        secret.encode(),
        payload_body,
        hashlib.sha256
    ).hexdigest()
    
    received_signature = signature[7:]  # Remove "sha256=" prefix
    
    return hmac.compare_digest(expected_signature, received_signature)


@webhooks_bp.route('/github', methods=['POST'])
def handle_github_webhook():
    """
    Endpoint לקבלת webhooks מ-GitHub
    
    Events supported:
    - push: סנכרון שינויים
    - ping: בדיקת תקינות
    """
    # אימות חתימה
    signature = request.headers.get('X-Hub-Signature-256', '')
    
    if not verify_github_signature(request.data, signature):
        logger.warning("Invalid webhook signature")
        return jsonify({"error": "Invalid signature"}), 401
    
    # זיהוי סוג האירוע
    event_type = request.headers.get('X-GitHub-Event', '')
    delivery_id = request.headers.get('X-GitHub-Delivery', '')
    
    logger.info(f"Received webhook: {event_type} (delivery: {delivery_id})")
    
    # Ping event (בדיקת תקינות)
    if event_type == 'ping':
        return jsonify({
            "message": "pong",
            "delivery_id": delivery_id
        }), 200
    
    # Push event
    if event_type == 'push':
        return handle_push_event(request.json, delivery_id)
    
    # אירועים אחרים - מתעלמים
    return jsonify({
        "message": f"Event '{event_type}' ignored",
        "delivery_id": delivery_id
    }), 200


def handle_push_event(payload: dict, delivery_id: str):
    """
    טיפול באירוע push
    
    Args:
        payload: JSON מ-GitHub
        delivery_id: מזהה ייחודי לאירוע
    """
    try:
        # חילוץ מידע
        ref = payload.get('ref', '')
        repo_name = payload.get('repository', {}).get('name', '')
        new_sha = payload.get('after', '')
        old_sha = payload.get('before', '')
        
        # רק main/master branch
        if ref not in ['refs/heads/main', 'refs/heads/master']:
            logger.info(f"Ignoring push to {ref}")
            return jsonify({
                "message": f"Ignoring branch {ref}",
                "delivery_id": delivery_id
            }), 200
        
        # בדיקה ש-SHA תקין
        if new_sha == '0' * 40:
            # Branch deleted
            logger.info("Branch deleted, ignoring")
            return jsonify({"message": "Branch deleted"}), 200
        
        logger.info(f"Processing push: {repo_name} {old_sha[:7]}..{new_sha[:7]}")
        
        # הפעלת סנכרון ברקע
        from services.repo_sync_service import trigger_sync
        
        job_id = trigger_sync(
            repo_name=repo_name,
            new_sha=new_sha,
            old_sha=old_sha,
            trigger="webhook",
            delivery_id=delivery_id
        )
        
        return jsonify({
            "status": "queued",
            "job_id": job_id,
            "repo": repo_name,
            "sha": new_sha[:7],
            "delivery_id": delivery_id
        }), 202
        
    except Exception as e:
        logger.exception(f"Failed to process push event: {e}")
        return jsonify({
            "error": "Processing failed",
            "message": str(e)
        }), 500


@webhooks_bp.route('/github/test', methods=['POST'])
def test_webhook():
    """Endpoint לבדיקה ידנית (ללא אימות חתימה)"""
    if not current_app.debug:
        return jsonify({"error": "Only available in debug mode"}), 403
    
    return handle_push_event(request.json, "test-delivery")
```

---

## Background Tasks

צור קובץ `services/repo_sync_service.py`:

```python
"""
Repository Sync Service

ניהול סנכרון הריפו:
- Initial import
- Delta sync (מ-webhook)
- Manual sync

**חשוב לגבי Gunicorn Multi-Workers:**
ב-Render (ובכל סביבת פרודקשן), gunicorn מריץ מספר workers (processes).
כל worker הוא process נפרד עם זיכרון נפרד!

בעיה: אם משתמשים ב-Queue/Dict בזיכרון:
- Webhook מגיע ל-Worker A -> Job נשמר בזיכרון של A
- User עושה refresh -> מגיע ל-Worker B -> "Job not found" (404)

פתרונות:
1. **MongoDB-based Queue** (מומלץ) - Jobs נשמרים ב-DB, כל worker יכול לראות
2. **WEB_CONCURRENCY=1** - worker בודד (פשוט אבל לא scalable)
3. **Redis + Celery** - פתרון enterprise (מורכב יותר)

הקוד הזה משתמש ב-MongoDB-based Queue.
"""

import logging
import threading
import os
import time
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
import uuid

from services.git_mirror_service import get_mirror_service
from services.code_indexer import CodeIndexer

logger = logging.getLogger(__name__)

# Flag לוודא worker אחד per process
_worker_started = False
_worker_lock = threading.Lock()


def trigger_sync(
    repo_name: str,
    new_sha: str,
    old_sha: Optional[str] = None,
    trigger: str = "webhook",
    delivery_id: Optional[str] = None
) -> str:
    """
    הפעלת סנכרון ברקע - שומר ב-MongoDB
    
    Args:
        repo_name: שם הריפו
        new_sha: SHA החדש
        old_sha: SHA הישן (אופציונלי)
        trigger: מקור ההפעלה
        delivery_id: מזהה ייחודי
        
    Returns:
        job_id
    """
    from database.db_manager import get_db
    
    job_id = delivery_id or str(uuid.uuid4())[:8]
    
    # שמירת Job ב-MongoDB (לא בזיכרון!)
    db = get_db()
    
    job_doc = {
        "_id": job_id,
        "repo_name": repo_name,
        "new_sha": new_sha,
        "old_sha": old_sha,
        "trigger": trigger,
        "status": "pending",
        "created_at": datetime.utcnow(),
        "started_at": None,
        "completed_at": None,
        "result": None,
        "error": None,
        # TTL index - מחיקה אוטומטית אחרי 7 ימים
        "expire_at": datetime.utcnow() + timedelta(days=7)
    }
    
    # Upsert - אם אותו delivery_id כבר קיים, לא ליצור כפילות
    db.sync_jobs.update_one(
        {"_id": job_id},
        {"$setOnInsert": job_doc},
        upsert=True
    )
    
    logger.info(f"Sync job queued in MongoDB: {job_id}")
    
    # הפעלת worker (אם לא רץ)
    _ensure_worker_started()
    
    return job_id


def get_job_status(job_id: str) -> Optional[Dict]:
    """קבלת סטטוס משימה מ-MongoDB"""
    from database.db_manager import get_db
    
    db = get_db()
    job = db.sync_jobs.find_one({"_id": job_id})
    
    if not job:
        return None
    
    return {
        "job_id": job["_id"],
        "status": job["status"],
        "repo": job["repo_name"],
        "trigger": job["trigger"],
        "created_at": job["created_at"].isoformat() if job.get("created_at") else None,
        "started_at": job["started_at"].isoformat() if job.get("started_at") else None,
        "completed_at": job["completed_at"].isoformat() if job.get("completed_at") else None,
        "result": job.get("result"),
        "error": job.get("error")
    }


def _ensure_worker_started():
    """הפעלת worker thread אם לא פעיל (per process)"""
    global _worker_started
    
    with _worker_lock:
        if not _worker_started:
            worker = threading.Thread(target=_sync_worker, daemon=True)
            worker.start()
            _worker_started = True
            logger.info("Sync worker thread started")


def _sync_worker():
    """
    Worker thread - polling על MongoDB לחיפוש jobs
    
    Note: כל Gunicorn worker יריץ את ה-thread הזה.
    השימוש ב-findOneAndUpdate עם "$set": {"status": "running"}
    מבטיח שרק worker אחד יתפוס כל job (atomic operation).
    """
    from database.db_manager import get_db
    
    logger.info("Sync worker polling MongoDB...")
    
    while True:
        try:
            db = get_db()
            
            # Atomic: מצא job pending ותפוס אותו
            job = db.sync_jobs.find_one_and_update(
                {"status": "pending"},
                {
                    "$set": {
                        "status": "running",
                        "started_at": datetime.utcnow()
                    }
                },
                sort=[("created_at", 1)],  # FIFO - הישן קודם
                return_document=True  # מחזיר אחרי העדכון
            )
            
            if not job:
                # אין jobs - ישן 5 שניות
                time.sleep(5)
                continue
            
            job_id = job["_id"]
            logger.info(f"Processing sync job: {job_id}")
            
            try:
                result = _run_sync_from_doc(job, db)
                
                # עדכון סטטוס - completed
                db.sync_jobs.update_one(
                    {"_id": job_id},
                    {
                        "$set": {
                            "status": "completed",
                            "completed_at": datetime.utcnow(),
                            "result": result
                        }
                    }
                )
                
                logger.info(f"Job {job_id} completed successfully")
                
            except Exception as e:
                logger.exception(f"Sync job failed: {job_id}")
                
                # עדכון סטטוס - failed
                db.sync_jobs.update_one(
                    {"_id": job_id},
                    {
                        "$set": {
                            "status": "failed",
                            "completed_at": datetime.utcnow(),
                            "error": str(e)
                        }
                    }
                )
                
        except Exception as e:
            logger.exception(f"Worker error: {e}")
            time.sleep(10)  # backoff on error


def _run_sync_from_doc(job_doc: Dict, db) -> Dict[str, Any]:
    """
    הרצת סנכרון מ-document של MongoDB
    
    Args:
        job_doc: document מ-sync_jobs collection
        db: חיבור ל-MongoDB
        
    Returns:
        תוצאות הסנכרון
    """
    git_service = get_mirror_service()
    indexer = CodeIndexer(db)
    
    repo_name = job_doc["repo_name"]
    new_sha = job_doc["new_sha"]
    old_sha = job_doc.get("old_sha")
    
    # המשך הלוגיקה כמו ב-_run_sync המקורי...
    return _run_sync_logic(
        git_service, indexer, db,
        repo_name, new_sha, old_sha
    )


def _run_sync_logic(
    git_service,
    indexer,
    db,
    repo_name: str,
    new_sha: str,
    old_sha: Optional[str]
) -> Dict[str, Any]:
    """הלוגיקה של הסנכרון - מופרדת לשימוש חוזר"""


    # וידוא שה-mirror קיים
    if not git_service.mirror_exists(repo_name):
        return {"error": "Mirror not found. Run initial import first."}
    
    # Fetch עדכונים
    fetch_result = git_service.fetch_updates(repo_name)
    if not fetch_result["success"]:
        return {
            "error": "Fetch failed",
            "details": fetch_result
        }
    
    # אם אין old_sha, נשלוף מה-DB
    if not old_sha:
        metadata = db.repo_metadata.find_one({"repo_name": repo_name})
        old_sha = metadata.get("last_synced_sha") if metadata else None
    
    if not old_sha:
        return {"error": "No previous SHA. Run initial import first."}
    
    # אם ה-SHA זהה, אין מה לעדכן
    if old_sha == new_sha:
        return {"status": "up_to_date", "message": "No changes"}
    
    # קבלת רשימת שינויים
    changes = git_service.get_changed_files(repo_name, old_sha, new_sha)
    
    if changes is None:
        return {"error": "Failed to get changed files"}
    
    stats = {
        "added": 0,
        "modified": 0,
        "removed": 0,
        "renamed": 0,
        "indexed": 0,
        "skipped": 0
    }
    
    # מחיקת קבצים שנמחקו
    if changes["removed"]:
        removed_count = indexer.remove_files(repo_name, changes["removed"])
        stats["removed"] = removed_count
        logger.info(f"Removed {removed_count} files from index")
    
    # טיפול ב-RENAMED files (חשוב!)
    # git diff-tree עם -M מחזיר סטטוס R לקבצים ששונו שם
    files_to_process = changes["added"] + changes["modified"]
    
    if changes.get("renamed"):
        for rename_info in changes["renamed"]:
            old_path = rename_info["old"]
            new_path = rename_info["new"]
            
            # 1. מחיקת הקובץ הישן מהאינדקס
            indexer.remove_file(repo_name, old_path)
            
            # 2. הוספת הקובץ החדש לרשימת העיבוד
            files_to_process.append(new_path)
            stats["renamed"] += 1
            
            logger.debug(f"Renamed: {old_path} -> {new_path}")
    
    # עדכון/הוספת קבצים
    for file_path in files_to_process:
        if not indexer.should_index(file_path):
            stats["skipped"] += 1
            continue
        
        content = git_service.get_file_content(repo_name, file_path, new_sha)
        
        if content:
            if indexer.index_file(repo_name, file_path, content, new_sha):
                stats["indexed"] += 1
                if file_path in changes["added"]:
                    stats["added"] += 1
                elif file_path in changes["modified"]:
                    stats["modified"] += 1
    
    # עדכון metadata
    db.repo_metadata.update_one(
        {"repo_name": repo_name},
        {
            "$set": {
                "last_synced_sha": new_sha,
                "last_sync_time": datetime.utcnow(),
                "sync_status": "completed",
                "last_sync_stats": stats
            }
        },
        upsert=True
    )
    
    logger.info(f"Sync completed: {stats}")
    
    return {
        "status": "synced",
        "old_sha": old_sha[:7],
        "new_sha": new_sha[:7],
        "stats": stats
    }


def initial_import(repo_url: str, repo_name: str, db) -> Dict[str, Any]:
    """
    ייבוא ראשוני של ריפו
    
    Args:
        repo_url: URL של הריפו
        repo_name: שם הריפו
        db: חיבור ל-MongoDB
        
    Returns:
        תוצאות הייבוא
    """
    git_service = get_mirror_service()
    indexer = CodeIndexer(db)
    
    logger.info(f"Starting initial import: {repo_url}")
    
    # 1. יצירת mirror
    result = git_service.init_mirror(repo_url, repo_name)
    
    if not result["success"]:
        return {"error": "Failed to create mirror", "details": result}
    
    # 2. רשימת כל הקבצים
    all_files = git_service.list_all_files(repo_name) or []
    
    # 3. סינון קבצי קוד
    code_files = [f for f in all_files if indexer.should_index(f)]
    
    logger.info(f"Found {len(code_files)} code files out of {len(all_files)} total")
    
    # 4. אינדוקס
    indexed_count = 0
    error_count = 0
    
    current_sha = git_service.get_current_sha(repo_name) or "HEAD"
    
    for i, file_path in enumerate(code_files):
        if i % 100 == 0:
            logger.info(f"Indexing progress: {i}/{len(code_files)}")
        
        content = git_service.get_file_content(repo_name, file_path)
        
        if content:
            if indexer.index_file(repo_name, file_path, content, current_sha):
                indexed_count += 1
            else:
                error_count += 1
    
    # 5. שמירת metadata
    db.repo_metadata.update_one(
        {"repo_name": repo_name},
        {
            "$set": {
                "repo_url": repo_url,
                "last_synced_sha": current_sha,
                "last_sync_time": datetime.utcnow(),
                "total_files": len(code_files),
                "sync_status": "completed",
                "initial_import": True
            }
        },
        upsert=True
    )
    
    logger.info(f"Initial import completed: {indexed_count} files indexed")
    
    return {
        "status": "completed",
        "total_files": len(all_files),
        "code_files": len(code_files),
        "indexed": indexed_count,
        "errors": error_count,
        "sha": current_sha[:7]
    }
```

---

## WebApp Routes

צור קובץ `webapp/routes/repo_browser.py`:

```python
"""
Repository Browser Routes

UI לגלישה בקוד הריפו
"""

import logging
from flask import Blueprint, render_template, request, jsonify, abort
from functools import lru_cache

from services.git_mirror_service import get_mirror_service
from services.repo_search_service import create_search_service
from database.db_manager import get_db

logger = logging.getLogger(__name__)

repo_bp = Blueprint('repo', __name__, url_prefix='/repo')


@repo_bp.route('/')
def repo_index():
    """דף ראשי של דפדפן הקוד"""
    db = get_db()
    git_service = get_mirror_service()
    
    # מידע על הריפו
    repo_name = "CodeBot"  # או מ-config
    
    metadata = db.repo_metadata.find_one({"repo_name": repo_name})
    mirror_info = git_service.get_mirror_info(repo_name)
    
    return render_template(
        'repo/index.html',
        repo_name=repo_name,
        metadata=metadata,
        mirror_info=mirror_info
    )


@repo_bp.route('/browse')
@repo_bp.route('/browse/<path:dir_path>')
def browse_directory(dir_path: str = ""):
    """גלישה בתיקיות"""
    db = get_db()
    repo_name = "CodeBot"
    
    # בניית שאילתה לקבצים בתיקייה
    if dir_path:
        # קבצים בתיקייה ספציפית
        pattern = f"^{dir_path}/[^/]+$"
    else:
        # קבצים ב-root
        pattern = "^[^/]+$"
    
    # שליפת קבצים
    files = list(db.repo_files.find(
        {
            "repo_name": repo_name,
            "path": {"$regex": pattern}
        },
        {"path": 1, "language": 1, "size": 1, "lines": 1}
    ).sort("path", 1))
    
    # שליפת תיקיות
    if dir_path:
        dir_pattern = f"^{dir_path}/[^/]+/"
    else:
        dir_pattern = "^[^/]+/"
    
    all_paths = db.repo_files.distinct("path", {"repo_name": repo_name})
    
    # חילוץ תיקיות ייחודיות
    directories = set()
    for path in all_paths:
        if dir_path:
            if path.startswith(dir_path + "/"):
                remaining = path[len(dir_path) + 1:]
                if "/" in remaining:
                    directories.add(remaining.split("/")[0])
        else:
            if "/" in path:
                directories.add(path.split("/")[0])
    
    return render_template(
        'repo/browse.html',
        repo_name=repo_name,
        current_path=dir_path,
        files=files,
        directories=sorted(directories),
        breadcrumbs=_build_breadcrumbs(dir_path)
    )


@repo_bp.route('/file/<path:file_path>')
def view_file(file_path: str):
    """הצגת קובץ"""
    db = get_db()
    git_service = get_mirror_service()
    repo_name = "CodeBot"
    
    # metadata מ-MongoDB
    metadata = db.repo_files.find_one({
        "repo_name": repo_name,
        "path": file_path
    })
    
    if not metadata:
        abort(404)
    
    # תוכן מ-git mirror
    content = git_service.get_file_content(repo_name, file_path)
    
    if content is None:
        abort(404)
    
    return render_template(
        'repo/file.html',
        repo_name=repo_name,
        file_path=file_path,
        content=content,
        metadata=metadata,
        breadcrumbs=_build_breadcrumbs(file_path)
    )


@repo_bp.route('/search')
def search():
    """חיפוש בקוד"""
    query = request.args.get('q', '')
    search_type = request.args.get('type', 'content')
    file_pattern = request.args.get('pattern', '')
    
    if not query:
        return render_template(
            'repo/search.html',
            query='',
            results=[],
            total=0
        )
    
    db = get_db()
    search_service = create_search_service(db)
    repo_name = "CodeBot"
    
    result = search_service.search(
        repo_name=repo_name,
        query=query,
        search_type=search_type,
        file_pattern=file_pattern or None,
        max_results=100
    )
    
    return render_template(
        'repo/search.html',
        query=query,
        search_type=search_type,
        results=result.get('results', []),
        total=result.get('total', 0),
        truncated=result.get('truncated', False),
        error=result.get('error')
    )


@repo_bp.route('/api/file/<path:file_path>')
def api_get_file(file_path: str):
    """API לקבלת תוכן קובץ"""
    git_service = get_mirror_service()
    repo_name = "CodeBot"
    
    content = git_service.get_file_content(repo_name, file_path)
    
    if content is None:
        return jsonify({"error": "File not found"}), 404
    
    return jsonify({
        "path": file_path,
        "content": content
    })


@repo_bp.route('/api/search')
def api_search():
    """API לחיפוש"""
    query = request.args.get('q', '')
    search_type = request.args.get('type', 'content')
    
    if not query:
        return jsonify({"error": "Query required"}), 400
    
    db = get_db()
    search_service = create_search_service(db)
    repo_name = "CodeBot"
    
    result = search_service.search(
        repo_name=repo_name,
        query=query,
        search_type=search_type,
        max_results=50
    )
    
    return jsonify(result)


@repo_bp.route('/api/stats')
def api_stats():
    """API לסטטיסטיקות"""
    git_service = get_mirror_service()
    repo_name = "CodeBot"
    
    stats = git_service.get_repo_stats(repo_name)
    
    if stats is None:
        return jsonify({"error": "Stats not available"}), 404
    
    return jsonify(stats)


def _build_breadcrumbs(path: str) -> list:
    """בניית breadcrumbs לניווט"""
    if not path:
        return []
    
    parts = path.split('/')
    breadcrumbs = []
    
    for i, part in enumerate(parts):
        breadcrumbs.append({
            "name": part,
            "path": '/'.join(parts[:i + 1]),
            "is_last": i == len(parts) - 1
        })
    
    return breadcrumbs
```

---

## UI Components

צור תבנית `webapp/templates/repo/search.html`:

```html
{% extends "base.html" %}

{% block title %}חיפוש בקוד - {{ repo_name }}{% endblock %}

{% block content %}
<div class="container-fluid py-4">
    <h1 class="mb-4">
        <i class="bi bi-search"></i>
        חיפוש בקוד
    </h1>
    
    <!-- טופס חיפוש -->
    <form method="GET" class="mb-4">
        <div class="row g-3">
            <div class="col-md-6">
                <div class="input-group input-group-lg">
                    <input type="text" 
                           name="q" 
                           class="form-control" 
                           placeholder="חפש בקוד..."
                           value="{{ query }}"
                           autofocus>
                    <button type="submit" class="btn btn-primary">
                        <i class="bi bi-search"></i>
                        חפש
                    </button>
                </div>
            </div>
            
            <div class="col-md-3">
                <select name="type" class="form-select form-select-lg">
                    <option value="content" {% if search_type == 'content' %}selected{% endif %}>
                        תוכן קוד
                    </option>
                    <option value="filename" {% if search_type == 'filename' %}selected{% endif %}>
                        שם קובץ
                    </option>
                    <option value="function" {% if search_type == 'function' %}selected{% endif %}>
                        פונקציה
                    </option>
                    <option value="class" {% if search_type == 'class' %}selected{% endif %}>
                        מחלקה
                    </option>
                </select>
            </div>
            
            <div class="col-md-3">
                <input type="text" 
                       name="pattern" 
                       class="form-control form-control-lg"
                       placeholder="סינון (*.py)"
                       value="{{ request.args.get('pattern', '') }}">
            </div>
        </div>
    </form>
    
    {% if error %}
    <div class="alert alert-danger">
        <i class="bi bi-exclamation-triangle"></i>
        {{ error }}
    </div>
    {% endif %}
    
    {% if query %}
    <!-- תוצאות -->
    <div class="mb-3 text-muted">
        נמצאו <strong>{{ total }}</strong> תוצאות
        {% if truncated %}
        <span class="badge bg-warning">מוצגות 100 ראשונות</span>
        {% endif %}
    </div>
    
    <div class="list-group">
        {% for result in results %}
        <a href="{{ url_for('repo.view_file', file_path=result.path) }}{% if result.line %}#L{{ result.line }}{% endif %}"
           class="list-group-item list-group-item-action">
            <div class="d-flex justify-content-between align-items-start">
                <div>
                    <h6 class="mb-1">
                        <i class="bi bi-file-code"></i>
                        {{ result.path }}
                        {% if result.line %}
                        <span class="badge bg-secondary">שורה {{ result.line }}</span>
                        {% endif %}
                    </h6>
                    
                    {% if result.content %}
                    <pre class="mb-0 small text-muted bg-light p-2 rounded"><code>{{ result.content[:200] }}{% if result.content|length > 200 %}...{% endif %}</code></pre>
                    {% endif %}
                    
                    {% if result.function %}
                    <span class="badge bg-info">function: {{ result.function }}</span>
                    {% endif %}
                    
                    {% if result.class %}
                    <span class="badge bg-success">class: {{ result.class }}</span>
                    {% endif %}
                </div>
                
                {% if result.language %}
                <span class="badge bg-primary">{{ result.language }}</span>
                {% endif %}
            </div>
        </a>
        {% else %}
        <div class="text-center py-5 text-muted">
            <i class="bi bi-search" style="font-size: 3rem;"></i>
            <p class="mt-3">לא נמצאו תוצאות</p>
        </div>
        {% endfor %}
    </div>
    {% endif %}
</div>
{% endblock %}
```

---

## הגדרות Render

### render.yaml מלא

```yaml
services:
  - type: web
    name: codebot
    env: python
    plan: starter
    buildCommand: pip install -r requirements.txt
    
    # Gunicorn עם WEB_CONCURRENCY (או ברירת מחדל 1)
    # ב-Render, הם מגדירים WEB_CONCURRENCY אוטומטית לפי ה-plan
    # אבל אנחנו רוצים לשלוט בזה ידנית
    startCommand: gunicorn main:app --workers ${WEB_CONCURRENCY:-1} --threads 4 --bind 0.0.0.0:$PORT
    
    # Render Disk for Git Mirror
    disk:
      name: repo-mirror
      mountPath: /var/data/repos
      sizeGB: 10
    
    envVars:
      - key: REPO_MIRROR_PATH
        value: /var/data/repos
      - key: REPO_NAME
        value: CodeBot
      
      # מספר workers - התחל עם 1, הגדל אם צריך
      - key: WEB_CONCURRENCY
        value: "1"
      
      # הגדרות רגישות - מוגדרות ידנית ב-Dashboard
      - key: GITHUB_REPO_URL
        sync: false  # Set manually
      - key: GITHUB_TOKEN
        sync: false  # Set manually - REQUIRED for private repos!
      - key: GITHUB_WEBHOOK_SECRET
        sync: false  # Set manually
      - key: MONGODB_URI
        sync: false
    
    # Health check
    healthCheckPath: /health
```

> **חשוב:**
> - עם `WEB_CONCURRENCY=1` - פשוט ועובד, מתאים לרוב המקרים
> - עם `WEB_CONCURRENCY > 1` - צריך MongoDB-based queue (כמו בקוד למעלה)
> - אל תשכח להגדיר `GITHUB_TOKEN` ל-Private Repos!

### הגדרת Webhook ב-GitHub

1. לכו ל-Settings → Webhooks → Add webhook

2. הגדירו:
   - **Payload URL:** `https://your-app.onrender.com/api/webhooks/github`
   - **Content type:** `application/json`
   - **Secret:** (הערך מ-GITHUB_WEBHOOK_SECRET)
   - **Events:** Just the `push` event

3. שמרו ובדקו שה-ping עובד

---

## בדיקות

### בדיקת Mirror Service

```python
# tests/test_git_mirror_service.py
import pytest
from services.git_mirror_service import GitMirrorService


@pytest.fixture
def service(tmp_path):
    return GitMirrorService(base_path=str(tmp_path))


def test_init_mirror(service):
    # Skip if no network
    result = service.init_mirror(
        "https://github.com/octocat/Hello-World.git",
        "test-repo"
    )
    
    assert result["success"] or "already_existed" in result


def test_should_classify_errors(service):
    assert service._classify_git_error("Could not resolve host") == "network_error"
    assert service._classify_git_error("Authentication failed") == "auth_error"


def test_is_regex(service):
    assert service._is_regex(".*test") is True
    assert service._is_regex("simple") is False
```

### בדיקת Indexer

```python
# tests/test_code_indexer.py
import pytest
from services.code_indexer import CodeIndexer


@pytest.fixture
def indexer():
    return CodeIndexer()


def test_should_index_python(indexer):
    assert indexer.should_index("src/main.py") is True
    assert indexer.should_index("node_modules/pkg/index.js") is False


def test_detect_language(indexer):
    assert indexer._detect_language("test.py") == "python"
    assert indexer._detect_language("app.tsx") == "typescript"


def test_extract_imports_python(indexer):
    content = """
import os
from typing import Dict, List
from services.git import GitService
"""
    imports = indexer._extract_imports(content, "python")
    
    assert "os" in imports
    assert "typing" in imports
    assert "services.git" in imports


def test_extract_functions_python(indexer):
    content = """
def hello():
    pass

async def fetch_data():
    pass
"""
    functions = indexer._extract_functions(content, "python")
    
    assert "hello" in functions
    assert "fetch_data" in functions
```

---

## Troubleshooting

### בעיה: "Mirror not found"

**סיבה:** לא בוצע initial import

**פתרון:**
```python
from services.repo_sync_service import initial_import
from database.db_manager import get_db

result = initial_import(
    "https://github.com/amirbiron/CodeBot.git",
    "CodeBot",
    get_db()
)
print(result)
```

### בעיה: "Permission denied" על Render Disk

**סיבה:** הדיסק לא mounted כראוי

**פתרון:**
1. בדקו ב-Render Dashboard שה-Disk מחובר
2. ודאו שה-mountPath נכון
3. Redeploy אם צריך

### בעיה: Webhook לא מגיע

**בדיקות:**
1. בדקו ב-GitHub → Webhooks → Recent Deliveries
2. ודאו שה-Secret מוגדר נכון
3. בדקו שה-endpoint נגיש (לא 404)

### בעיה: חיפוש איטי

**פתרונות:**
1. הגדילו timeout ב-git grep
2. הוסיפו file pattern לצמצום
3. בדקו שהדיסק לא מלא

### בעיה: "Authentication failed" ב-Private Repo

**סיבה:** `GITHUB_TOKEN` לא מוגדר או לא תקף

**פתרון:**
1. צרו Personal Access Token ב-GitHub:
   - Settings → Developer settings → Personal access tokens → Fine-grained tokens
   - תנו הרשאת `Contents: Read-only` על הריפו הספציפי
2. הגדירו ב-Render: `GITHUB_TOKEN=ghp_xxxx`
3. אל תשכחו: הטוקן לא יופיע בלוגים (מוסתר אוטומטית)

### בעיה: Job נעלם / "Job not found"

**סיבה:** Multi-workers עם in-memory queue

**פתרון:**
1. **מהיר:** הגדירו `WEB_CONCURRENCY=1`
2. **נכון:** השתמשו ב-MongoDB-based queue (כמו בקוד למעלה)

**בדיקה:**
```bash
# ראו כמה workers רצים
ps aux | grep gunicorn
```

### בעיה: git grep מחזיר שגיאה על query עם מקף

**סיבה:** `-v` מזוהה כ-flag במקום כ-pattern

**פתרון:**
הקוד המעודכן כבר מטפל בזה:
```python
if query.startswith("-"):
    cmd.extend(["-e", query])
```

### בעיה: Renamed files לא מתעדכנים

**סיבה:** הקוד לא טיפל ב-`changes["renamed"]`

**פתרון:**
הקוד המעודכן מטפל בזה - ראו `_run_sync_logic`:
1. מוחק את הקובץ הישן מהאינדקס
2. מוסיף את הקובץ החדש לרשימת העיבוד

---

## MongoDB Indexes

כדי שה-sync jobs יעבדו מהר, הוסיפו אינדקסים:

```python
# scripts/create_repo_indexes.py
from database.db_manager import get_db

db = get_db()

# sync_jobs - לחיפוש pending jobs
db.sync_jobs.create_index([("status", 1), ("created_at", 1)])

# sync_jobs - TTL index למחיקה אוטומטית
db.sync_jobs.create_index("expire_at", expireAfterSeconds=0)

# repo_files - לחיפוש לפי path
db.repo_files.create_index([("repo_name", 1), ("path", 1)], unique=True)

# repo_files - לחיפוש טקסט
db.repo_files.create_index([("search_text", "text")])

# repo_files - לחיפוש לפי שפה
db.repo_files.create_index([("repo_name", 1), ("language", 1)])
```

---

## סיכום

מערכת ה-Repo Sync Engine מאפשרת:

1. **Git Mirror על Render Disk** - אחסון persistent ומהיר
2. **Delta Sync אוטומטי** - עדכונים בזמן אמת מ-Webhooks
3. **חיפוש עם git grep** - מהיר ומדויק
4. **MongoDB למטא-דאטה** - חיפוש functions, classes, filenames
5. **WebApp לגלישה** - UI לצפייה בקוד

**עלות משוערת:** ~$7/חודש עבור 10GB Render Disk

**ביצועים צפויים:**
- Initial import: ~20 דקות ל-5,000 קבצים
- Delta sync: ~5 שניות לקומיט רגיל
- חיפוש: < 100ms

---

*מסמך זה נכתב כחלק מפרויקט CodeBot*
