# מדריך מימוש: היסטוריית Git ותצוגת Diff בדפדפן הקוד

## תוכן עניינים
1. [סקירת ארכיטקטורה](#1-סקירת-ארכיטקטורה)
2. [מימוש Backend](#2-מימוש-backend)
3. [מימוש Frontend](#3-מימוש-frontend)
4. [אבטחה וטיפול בשגיאות](#4-אבטחה-וטיפול-בשגיאות)
5. [אינטגרציה עם git_mirror_service](#5-אינטגרציה-עם-git_mirror_service)
6. [תמיכה ב-RTL](#6-תמיכה-ב-rtl)
7. [בדיקות](#7-בדיקות)

---

## 1. סקירת ארכיטקטורה

### מבנה קיים
```
webapp/
├── routes/
│   └── repo_browser.py          # Routes קיימים של דפדפן הריפו
├── services/
│   └── git_mirror_service.py    # שירות Git קיים
├── templates/repo/
│   ├── base_repo.html           # תבנית בסיס
│   └── index.html               # דף ראשי
└── static/
    ├── js/repo-browser.js       # JavaScript קיים
    └── css/repo-browser.css     # CSS קיים
```

### API Endpoints חדשים
| Endpoint | Method | תיאור |
|----------|--------|-------|
| `/repo/api/history/<path:file_path>` | GET | היסטוריית commits לקובץ |
| `/repo/api/file-at-commit/<commit>/<path:file_path>` | GET | תוכן קובץ ב-commit ספציפי |
| `/repo/api/diff/<commit1>/<commit2>/<path:file_path>` | GET | Diff בין שני commits |
| `/repo/api/commit/<commit>` | GET | פרטי commit בודד |

---

## 2. מימוש Backend

### שלב 2.1: הרחבת git_mirror_service.py

הוסף את המתודות הבאות ל-`GitMirrorService`:

```python
# webapp/services/git_mirror_service.py

import re
from datetime import datetime
from typing import Optional, List, Dict, Any

class GitMirrorService:
    # ... קוד קיים ...

    # ============================================
    # מתודות חדשות להיסטוריה ו-Diff
    # ============================================

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
            ref: Branch או commit להתחיל ממנו
            limit: מספר commits מקסימלי
            skip: כמה commits לדלג

        Returns:
            Dict עם רשימת commits או שגיאה
        """
        # וולידציה
        if not self._validate_repo_name(repo_name):
            return {"error": "invalid_repo_name", "message": "שם ריפו לא תקין"}

        if not self._validate_repo_file_path(file_path):
            return {"error": "invalid_file_path", "message": "נתיב קובץ לא תקין"}

        if not self._validate_repo_ref(ref):
            return {"error": "invalid_ref", "message": "Reference לא תקין"}

        # וולידציה נוספת ל-limit ו-skip
        if not isinstance(limit, int) or limit < 1 or limit > 100:
            limit = 20
        if not isinstance(skip, int) or skip < 0:
            skip = 0

        mirror_path = self._get_mirror_path(repo_name)
        if not mirror_path.exists():
            return {"error": "repo_not_found", "message": "ריפו לא נמצא"}

        try:
            # פורמט מיוחד לפענוח קל
            # %H = hash מלא
            # %h = hash קצר
            # %an = שם author
            # %ae = email author
            # %at = timestamp author (unix)
            # %s = subject (שורה ראשונה של הודעה)
            # %b = body (שאר ההודעה)
            format_str = "%H%x00%h%x00%an%x00%ae%x00%at%x00%s%x00%b%x1E"

            cmd = [
                "git", "-C", str(mirror_path),
                "log",
                "--follow",           # עקוב אחרי שינויי שם
                f"--max-count={limit}",
                f"--skip={skip}",
                f"--format={format_str}",
                ref,
                "--",
                file_path
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
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

                commits.append({
                    "hash": parts[0],
                    "short_hash": parts[1],
                    "author": parts[2],
                    "author_email": parts[3],
                    "timestamp": int(parts[4]),
                    "date": datetime.fromtimestamp(int(parts[4])).isoformat(),
                    "message": parts[5],
                    "body": parts[6] if len(parts) > 6 else ""
                })

            # בדיקה אם יש עוד commits
            has_more = len(commits) == limit

            return {
                "success": True,
                "file_path": file_path,
                "commits": commits,
                "total_returned": len(commits),
                "skip": skip,
                "limit": limit,
                "has_more": has_more
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
        commit: str
    ) -> Dict[str, Any]:
        """
        שליפת תוכן קובץ ב-commit ספציפי.

        Args:
            repo_name: שם הריפו
            file_path: נתיב הקובץ
            commit: Hash של ה-commit

        Returns:
            Dict עם תוכן הקובץ או שגיאה
        """
        # וולידציה
        if not self._validate_repo_name(repo_name):
            return {"error": "invalid_repo_name", "message": "שם ריפו לא תקין"}

        if not self._validate_repo_file_path(file_path):
            return {"error": "invalid_file_path", "message": "נתיב קובץ לא תקין"}

        if not self._validate_repo_ref(commit):
            return {"error": "invalid_commit", "message": "Commit hash לא תקין"}

        mirror_path = self._get_mirror_path(repo_name)
        if not mirror_path.exists():
            return {"error": "repo_not_found", "message": "ריפו לא נמצא"}

        try:
            # שימוש ב-git show לשליפת תוכן בcommit ספציפי
            cmd = [
                "git", "-C", str(mirror_path),
                "show",
                f"{commit}:{file_path}"
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=30
            )

            if result.returncode != 0:
                stderr = self._sanitize_output(result.stderr.decode('utf-8', errors='replace'))
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

            # ניסיון לפענח כ-UTF-8
            try:
                content = result.stdout.decode('utf-8')
            except UnicodeDecodeError:
                # קובץ בינארי או encoding אחר
                return {
                    "error": "binary_file",
                    "message": "זהו קובץ בינארי שלא ניתן להציג"
                }

            return {
                "success": True,
                "file_path": file_path,
                "commit": commit,
                "content": content,
                "size": len(content),
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
        unified: bool = True
    ) -> Dict[str, Any]:
        """
        יצירת diff בין שני commits.

        Args:
            repo_name: שם הריפו
            commit1: Commit ראשון (הישן יותר)
            commit2: Commit שני (החדש יותר)
            file_path: נתיב קובץ ספציפי (אופציונלי)
            context_lines: מספר שורות הקשר
            unified: האם להשתמש בפורמט unified

        Returns:
            Dict עם ה-diff או שגיאה
        """
        # וולידציה
        if not self._validate_repo_name(repo_name):
            return {"error": "invalid_repo_name", "message": "שם ריפו לא תקין"}

        if not self._validate_repo_ref(commit1):
            return {"error": "invalid_commit1", "message": "Commit ראשון לא תקין"}

        if not self._validate_repo_ref(commit2):
            return {"error": "invalid_commit2", "message": "Commit שני לא תקין"}

        if file_path and not self._validate_repo_file_path(file_path):
            return {"error": "invalid_file_path", "message": "נתיב קובץ לא תקין"}

        # וולידציה ל-context_lines
        if not isinstance(context_lines, int) or context_lines < 0 or context_lines > 20:
            context_lines = 3

        mirror_path = self._get_mirror_path(repo_name)
        if not mirror_path.exists():
            return {"error": "repo_not_found", "message": "ריפו לא נמצא"}

        try:
            cmd = [
                "git", "-C", str(mirror_path),
                "diff",
                f"-U{context_lines}",    # שורות הקשר
                "--no-color",            # ללא צבעים ANSI
                commit1,
                commit2
            ]

            if file_path:
                cmd.extend(["--", file_path])

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
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

            # פרסור ה-diff לפורמט מובנה
            parsed_diff = self._parse_diff(diff_output)

            return {
                "success": True,
                "commit1": commit1,
                "commit2": commit2,
                "file_path": file_path,
                "raw_diff": diff_output,
                "parsed": parsed_diff,
                "stats": {
                    "files_changed": len(parsed_diff.get("files", [])),
                    "additions": sum(f.get("additions", 0) for f in parsed_diff.get("files", [])),
                    "deletions": sum(f.get("deletions", 0) for f in parsed_diff.get("files", []))
                }
            }

        except subprocess.TimeoutExpired:
            return {"error": "timeout", "message": "הפעולה ארכה יותר מדי זמן"}
        except Exception as e:
            self.logger.error(f"Error getting diff: {e}")
            return {"error": "internal_error", "message": "שגיאה פנימית"}

    def _parse_diff(self, diff_output: str) -> Dict[str, Any]:
        """
        פרסור פלט diff לפורמט מובנה.

        Returns:
            Dict עם מבנה הdiff המפורסר
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
                        'deletions': 0
                    }
                else:
                    current_file = {
                        'old_path': '',
                        'new_path': '',
                        'status': 'modified',
                        'additions': 0,
                        'deletions': 0
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
            elif line.startswith('rename from'):
                if current_file:
                    current_file['status'] = 'renamed'

            # Header של hunk
            elif line.startswith('@@'):
                if current_hunk:
                    current_hunks.append(current_hunk)

                # פרסור header
                # @@ -start,count +start,count @@
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
            commit: Hash של ה-commit

        Returns:
            Dict עם פרטי ה-commit
        """
        # וולידציה
        if not self._validate_repo_name(repo_name):
            return {"error": "invalid_repo_name", "message": "שם ריפו לא תקין"}

        if not self._validate_repo_ref(commit):
            return {"error": "invalid_commit", "message": "Commit לא תקין"}

        mirror_path = self._get_mirror_path(repo_name)
        if not mirror_path.exists():
            return {"error": "repo_not_found", "message": "ריפו לא נמצא"}

        try:
            # פרטי commit
            format_str = "%H%x00%h%x00%an%x00%ae%x00%at%x00%cn%x00%ce%x00%ct%x00%s%x00%b%x00%P"
            cmd = [
                "git", "-C", str(mirror_path),
                "log", "-1",
                f"--format={format_str}",
                commit
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=10
            )

            if result.returncode != 0:
                stderr = self._sanitize_output(result.stderr)
                if "unknown revision" in stderr:
                    return {"error": "commit_not_found", "message": "Commit לא נמצא"}
                return {"error": "git_error", "message": stderr}

            parts = result.stdout.strip().split("\x00")
            if len(parts) < 11:
                return {"error": "parse_error", "message": "שגיאה בפענוח פרטי commit"}

            # רשימת קבצים שהשתנו
            files_cmd = [
                "git", "-C", str(mirror_path),
                "diff-tree", "--no-commit-id", "--name-status", "-r",
                commit
            ]

            files_result = subprocess.run(
                files_cmd,
                capture_output=True,
                text=True,
                timeout=10
            )

            changed_files = []
            if files_result.returncode == 0:
                for line in files_result.stdout.strip().split('\n'):
                    if '\t' in line:
                        status, path = line.split('\t', 1)
                        status_map = {
                            'A': 'added',
                            'M': 'modified',
                            'D': 'deleted',
                            'R': 'renamed',
                            'C': 'copied'
                        }
                        changed_files.append({
                            'path': path,
                            'status': status_map.get(status[0], 'modified')
                        })

            return {
                "success": True,
                "hash": parts[0],
                "short_hash": parts[1],
                "author": {
                    "name": parts[2],
                    "email": parts[3],
                    "timestamp": int(parts[4]),
                    "date": datetime.fromtimestamp(int(parts[4])).isoformat()
                },
                "committer": {
                    "name": parts[5],
                    "email": parts[6],
                    "timestamp": int(parts[7]),
                    "date": datetime.fromtimestamp(int(parts[7])).isoformat()
                },
                "message": parts[8],
                "body": parts[9],
                "parents": parts[10].split() if parts[10] else [],
                "changed_files": changed_files
            }

        except subprocess.TimeoutExpired:
            return {"error": "timeout", "message": "הפעולה ארכה יותר מדי זמן"}
        except Exception as e:
            self.logger.error(f"Error getting commit info: {e}")
            return {"error": "internal_error", "message": "שגיאה פנימית"}
```

### שלב 2.2: הוספת Routes חדשים

צור קובץ חדש או הוסף ל-`repo_browser.py`:

```python
# webapp/routes/repo_browser.py
# הוספה ל-routes קיימים

from flask import Blueprint, jsonify, request, current_app
from webapp.services.git_mirror_service import GitMirrorService

# הגדרות
DEFAULT_REPO_NAME = "CodeBot"  # או מקונפיג

# ============================================
# Routes חדשים - היסטוריה ו-Diff
# ============================================

@repo_bp.route('/api/history/<path:file_path>', methods=['GET'])
def get_file_history(file_path):
    """
    שליפת היסטוריית commits לקובץ ספציפי.

    Query params:
        - limit: מספר commits מקסימלי (default: 20, max: 100)
        - skip: כמה commits לדלג (default: 0)
        - ref: branch או commit להתחיל ממנו (default: HEAD)
    """
    try:
        # שליפת פרמטרים
        limit = request.args.get('limit', 20, type=int)
        skip = request.args.get('skip', 0, type=int)
        ref = request.args.get('ref', 'HEAD')

        # הגבלות
        limit = min(max(limit, 1), 100)
        skip = max(skip, 0)

        # שירות Git
        git_service: GitMirrorService = current_app.extensions.get('git_mirror_service')
        if not git_service:
            return jsonify({
                "success": False,
                "error": "service_unavailable",
                "message": "שירות Git לא זמין"
            }), 503

        # שליפת היסטוריה
        result = git_service.get_file_history(
            repo_name=DEFAULT_REPO_NAME,
            file_path=file_path,
            ref=ref,
            limit=limit,
            skip=skip
        )

        if "error" in result:
            status_codes = {
                "invalid_repo_name": 400,
                "invalid_file_path": 400,
                "invalid_ref": 400,
                "repo_not_found": 404,
                "file_not_found": 404,
                "timeout": 504,
                "git_error": 500,
                "internal_error": 500
            }
            return jsonify({
                "success": False,
                **result
            }), status_codes.get(result["error"], 500)

        return jsonify(result)

    except Exception as e:
        current_app.logger.error(f"Error in get_file_history: {e}")
        return jsonify({
            "success": False,
            "error": "internal_error",
            "message": "שגיאה פנימית"
        }), 500


@repo_bp.route('/api/file-at-commit/<commit>/<path:file_path>', methods=['GET'])
def get_file_at_commit(commit, file_path):
    """
    שליפת תוכן קובץ ב-commit ספציפי.
    """
    try:
        git_service: GitMirrorService = current_app.extensions.get('git_mirror_service')
        if not git_service:
            return jsonify({
                "success": False,
                "error": "service_unavailable",
                "message": "שירות Git לא זמין"
            }), 503

        result = git_service.get_file_at_commit(
            repo_name=DEFAULT_REPO_NAME,
            file_path=file_path,
            commit=commit
        )

        if "error" in result:
            status_codes = {
                "invalid_repo_name": 400,
                "invalid_file_path": 400,
                "invalid_commit": 400,
                "repo_not_found": 404,
                "file_not_in_commit": 404,
                "binary_file": 415,
                "timeout": 504,
                "git_error": 500,
                "internal_error": 500
            }
            return jsonify({
                "success": False,
                **result
            }), status_codes.get(result["error"], 500)

        return jsonify(result)

    except Exception as e:
        current_app.logger.error(f"Error in get_file_at_commit: {e}")
        return jsonify({
            "success": False,
            "error": "internal_error",
            "message": "שגיאה פנימית"
        }), 500


@repo_bp.route('/api/diff/<commit1>/<commit2>', methods=['GET'])
@repo_bp.route('/api/diff/<commit1>/<commit2>/<path:file_path>', methods=['GET'])
def get_diff(commit1, commit2, file_path=None):
    """
    שליפת diff בין שני commits.

    Query params:
        - context: מספר שורות הקשר (default: 3, max: 20)
    """
    try:
        context_lines = request.args.get('context', 3, type=int)
        context_lines = min(max(context_lines, 0), 20)

        git_service: GitMirrorService = current_app.extensions.get('git_mirror_service')
        if not git_service:
            return jsonify({
                "success": False,
                "error": "service_unavailable",
                "message": "שירות Git לא זמין"
            }), 503

        result = git_service.get_diff(
            repo_name=DEFAULT_REPO_NAME,
            commit1=commit1,
            commit2=commit2,
            file_path=file_path,
            context_lines=context_lines
        )

        if "error" in result:
            status_codes = {
                "invalid_repo_name": 400,
                "invalid_commit1": 400,
                "invalid_commit2": 400,
                "invalid_file_path": 400,
                "invalid_commits": 404,
                "repo_not_found": 404,
                "timeout": 504,
                "git_error": 500,
                "internal_error": 500
            }
            return jsonify({
                "success": False,
                **result
            }), status_codes.get(result["error"], 500)

        return jsonify(result)

    except Exception as e:
        current_app.logger.error(f"Error in get_diff: {e}")
        return jsonify({
            "success": False,
            "error": "internal_error",
            "message": "שגיאה פנימית"
        }), 500


@repo_bp.route('/api/commit/<commit>', methods=['GET'])
def get_commit_info(commit):
    """
    שליפת פרטי commit בודד.
    """
    try:
        git_service: GitMirrorService = current_app.extensions.get('git_mirror_service')
        if not git_service:
            return jsonify({
                "success": False,
                "error": "service_unavailable",
                "message": "שירות Git לא זמין"
            }), 503

        result = git_service.get_commit_info(
            repo_name=DEFAULT_REPO_NAME,
            commit=commit
        )

        if "error" in result:
            status_codes = {
                "invalid_repo_name": 400,
                "invalid_commit": 400,
                "commit_not_found": 404,
                "timeout": 504,
                "git_error": 500,
                "parse_error": 500,
                "internal_error": 500
            }
            return jsonify({
                "success": False,
                **result
            }), status_codes.get(result["error"], 500)

        return jsonify(result)

    except Exception as e:
        current_app.logger.error(f"Error in get_commit_info: {e}")
        return jsonify({
            "success": False,
            "error": "internal_error",
            "message": "שגיאה פנימית"
        }), 500
```

---

## 3. מימוש Frontend

### שלב 3.1: CSS - סגנונות חדשים

הוסף ל-`repo-browser.css`:

```css
/* ============================================
   היסטוריה ו-Diff Viewer
   ============================================ */

/* כפתור היסטוריה */
.file-history-btn {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 4px 10px;
    font-size: 12px;
    background: var(--bg-tertiary, #313244);
    border: 1px solid var(--border-color, #45475a);
    border-radius: 4px;
    color: var(--text-secondary, #bac2de);
    cursor: pointer;
    transition: all 0.2s ease;
}

.file-history-btn:hover {
    background: var(--accent-blue, #89b4fa);
    color: var(--bg-primary, #1e1e2e);
    border-color: var(--accent-blue, #89b4fa);
}

.file-history-btn i {
    font-size: 14px;
}

/* פאנל היסטוריה */
.history-panel {
    position: fixed;
    top: 0;
    left: 0;  /* RTL: שינוי מ-right ל-left */
    width: 400px;
    max-width: 90vw;
    height: 100vh;
    background: var(--bg-secondary, #181825);
    border-left: 1px solid var(--border-color, #45475a);  /* RTL */
    z-index: 1000;
    transform: translateX(-100%);  /* RTL */
    transition: transform 0.3s ease;
    display: flex;
    flex-direction: column;
}

.history-panel.open {
    transform: translateX(0);
}

.history-panel-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 16px;
    border-bottom: 1px solid var(--border-color, #45475a);
    background: var(--bg-primary, #1e1e2e);
}

.history-panel-header h3 {
    margin: 0;
    font-size: 16px;
    color: var(--text-primary, #cdd6f4);
    direction: rtl;
}

.history-panel-close {
    background: none;
    border: none;
    color: var(--text-secondary, #bac2de);
    font-size: 20px;
    cursor: pointer;
    padding: 4px;
    line-height: 1;
}

.history-panel-close:hover {
    color: var(--accent-red, #f38ba8);
}

/* רשימת commits */
.history-commits {
    flex: 1;
    overflow-y: auto;
    padding: 8px;
}

.history-commit {
    padding: 12px;
    margin-bottom: 8px;
    background: var(--bg-tertiary, #313244);
    border-radius: 6px;
    cursor: pointer;
    transition: all 0.2s ease;
    direction: rtl;
    text-align: right;
}

.history-commit:hover {
    background: var(--bg-hover, #45475a);
}

.history-commit.selected {
    border-right: 3px solid var(--accent-blue, #89b4fa);  /* RTL */
    background: var(--bg-hover, #45475a);
}

.commit-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 8px;
}

.commit-hash {
    font-family: 'JetBrains Mono', monospace;
    font-size: 12px;
    color: var(--accent-blue, #89b4fa);
    background: var(--bg-primary, #1e1e2e);
    padding: 2px 6px;
    border-radius: 4px;
}

.commit-date {
    font-size: 11px;
    color: var(--text-muted, #6c7086);
}

.commit-message {
    font-size: 13px;
    color: var(--text-primary, #cdd6f4);
    margin-bottom: 6px;
    line-height: 1.4;
    /* חיתוך טקסט ארוך */
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
}

.commit-author {
    font-size: 11px;
    color: var(--text-secondary, #bac2de);
    display: flex;
    align-items: center;
    gap: 4px;
}

.commit-author i {
    color: var(--accent-green, #a6e3a1);
}

/* פעולות commit */
.commit-actions {
    display: flex;
    gap: 8px;
    margin-top: 8px;
    padding-top: 8px;
    border-top: 1px solid var(--border-color, #45475a);
}

.commit-action-btn {
    flex: 1;
    padding: 6px 12px;
    font-size: 11px;
    border: 1px solid var(--border-color, #45475a);
    border-radius: 4px;
    background: transparent;
    color: var(--text-secondary, #bac2de);
    cursor: pointer;
    transition: all 0.2s ease;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 4px;
}

.commit-action-btn:hover {
    background: var(--accent-blue, #89b4fa);
    color: var(--bg-primary, #1e1e2e);
    border-color: var(--accent-blue, #89b4fa);
}

.commit-action-btn.diff-btn:hover {
    background: var(--accent-yellow, #f9e2af);
}

/* טעינת עוד */
.history-load-more {
    width: 100%;
    padding: 12px;
    margin-top: 8px;
    background: var(--bg-tertiary, #313244);
    border: 1px solid var(--border-color, #45475a);
    border-radius: 6px;
    color: var(--text-secondary, #bac2de);
    cursor: pointer;
    transition: all 0.2s ease;
}

.history-load-more:hover:not(:disabled) {
    background: var(--accent-blue, #89b4fa);
    color: var(--bg-primary, #1e1e2e);
}

.history-load-more:disabled {
    opacity: 0.5;
    cursor: not-allowed;
}

/* ============================================
   Diff Viewer
   ============================================ */

/* Modal Diff */
.diff-modal {
    position: fixed;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    background: rgba(0, 0, 0, 0.8);
    z-index: 2000;
    display: none;
    justify-content: center;
    align-items: center;
}

.diff-modal.open {
    display: flex;
}

.diff-modal-content {
    width: 90%;
    max-width: 1200px;
    height: 90%;
    background: var(--bg-secondary, #181825);
    border-radius: 8px;
    display: flex;
    flex-direction: column;
    overflow: hidden;
}

.diff-modal-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 16px;
    background: var(--bg-primary, #1e1e2e);
    border-bottom: 1px solid var(--border-color, #45475a);
}

.diff-modal-title {
    display: flex;
    align-items: center;
    gap: 12px;
    direction: rtl;
}

.diff-modal-title h3 {
    margin: 0;
    font-size: 16px;
    color: var(--text-primary, #cdd6f4);
}

.diff-commits-info {
    display: flex;
    gap: 8px;
    align-items: center;
    font-size: 12px;
}

.diff-commits-info .commit-badge {
    font-family: 'JetBrains Mono', monospace;
    padding: 2px 8px;
    border-radius: 4px;
    background: var(--bg-tertiary, #313244);
}

.diff-commits-info .commit-badge.old {
    color: var(--accent-red, #f38ba8);
}

.diff-commits-info .commit-badge.new {
    color: var(--accent-green, #a6e3a1);
}

.diff-commits-info .arrow {
    color: var(--text-muted, #6c7086);
}

.diff-modal-close {
    background: none;
    border: none;
    color: var(--text-secondary, #bac2de);
    font-size: 24px;
    cursor: pointer;
    padding: 4px;
}

.diff-modal-close:hover {
    color: var(--accent-red, #f38ba8);
}

/* Diff Stats */
.diff-stats {
    display: flex;
    gap: 16px;
    padding: 12px 16px;
    background: var(--bg-tertiary, #313244);
    border-bottom: 1px solid var(--border-color, #45475a);
    font-size: 13px;
    direction: rtl;
}

.diff-stat {
    display: flex;
    align-items: center;
    gap: 6px;
}

.diff-stat.additions {
    color: var(--accent-green, #a6e3a1);
}

.diff-stat.deletions {
    color: var(--accent-red, #f38ba8);
}

.diff-stat.files {
    color: var(--text-secondary, #bac2de);
}

/* Diff Content */
.diff-content {
    flex: 1;
    overflow: auto;
    padding: 0;
}

/* Unified Diff View */
.diff-unified {
    font-family: 'JetBrains Mono', monospace;
    font-size: 13px;
    line-height: 1.5;
    direction: ltr;  /* קוד תמיד LTR */
    text-align: left;
}

.diff-file {
    margin-bottom: 24px;
}

.diff-file-header {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 10px 16px;
    background: var(--bg-primary, #1e1e2e);
    border-bottom: 1px solid var(--border-color, #45475a);
    position: sticky;
    top: 0;
    z-index: 10;
}

.diff-file-status {
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 11px;
    font-weight: 500;
    text-transform: uppercase;
}

.diff-file-status.added {
    background: rgba(166, 227, 161, 0.2);
    color: var(--accent-green, #a6e3a1);
}

.diff-file-status.modified {
    background: rgba(249, 226, 175, 0.2);
    color: var(--accent-yellow, #f9e2af);
}

.diff-file-status.deleted {
    background: rgba(243, 139, 168, 0.2);
    color: var(--accent-red, #f38ba8);
}

.diff-file-status.renamed {
    background: rgba(137, 180, 250, 0.2);
    color: var(--accent-blue, #89b4fa);
}

.diff-file-path {
    color: var(--text-primary, #cdd6f4);
    font-weight: 500;
}

.diff-file-stats {
    margin-right: auto;  /* דחיפה לימין */
    margin-left: 16px;
    display: flex;
    gap: 8px;
    font-size: 12px;
}

.diff-file-stats .additions {
    color: var(--accent-green, #a6e3a1);
}

.diff-file-stats .deletions {
    color: var(--accent-red, #f38ba8);
}

/* Hunk Header */
.diff-hunk {
    border-bottom: 1px solid var(--border-color, #45475a);
}

.diff-hunk-header {
    padding: 8px 16px;
    background: rgba(137, 180, 250, 0.1);
    color: var(--accent-blue, #89b4fa);
    font-size: 12px;
}

/* Diff Lines */
.diff-line {
    display: flex;
    min-height: 22px;
}

.diff-line-number {
    min-width: 50px;
    padding: 0 8px;
    text-align: right;
    color: var(--text-muted, #6c7086);
    background: var(--bg-primary, #1e1e2e);
    user-select: none;
    border-left: 1px solid var(--border-color, #45475a);
}

.diff-line-number.old {
    border-left: none;
}

.diff-line-content {
    flex: 1;
    padding: 0 8px;
    white-space: pre-wrap;
    word-break: break-all;
}

/* Line Types */
.diff-line.addition {
    background: rgba(166, 227, 161, 0.15);
}

.diff-line.addition .diff-line-content::before {
    content: '+';
    color: var(--accent-green, #a6e3a1);
    margin-left: -8px;
    margin-right: 4px;
}

.diff-line.deletion {
    background: rgba(243, 139, 168, 0.15);
}

.diff-line.deletion .diff-line-content::before {
    content: '-';
    color: var(--accent-red, #f38ba8);
    margin-left: -8px;
    margin-right: 4px;
}

.diff-line.context {
    background: var(--bg-secondary, #181825);
}

.diff-line.context .diff-line-content::before {
    content: ' ';
    margin-left: -8px;
    margin-right: 4px;
}

.diff-line.info {
    background: var(--bg-tertiary, #313244);
    color: var(--text-muted, #6c7086);
    font-style: italic;
}

/* Side by Side View (אופציונלי) */
.diff-side-by-side {
    display: grid;
    grid-template-columns: 1fr 1fr;
    direction: ltr;
}

.diff-side {
    overflow-x: auto;
}

.diff-side.old {
    border-left: 1px solid var(--border-color, #45475a);
}

.diff-side.new {
    border-right: 1px solid var(--border-color, #45475a);
}

/* Loading State */
.diff-loading,
.history-loading {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 48px;
    color: var(--text-secondary, #bac2de);
}

.diff-loading .spinner,
.history-loading .spinner {
    width: 32px;
    height: 32px;
    border: 3px solid var(--border-color, #45475a);
    border-top-color: var(--accent-blue, #89b4fa);
    border-radius: 50%;
    animation: spin 1s linear infinite;
    margin-bottom: 12px;
}

@keyframes spin {
    to { transform: rotate(360deg); }
}

/* Error State */
.diff-error,
.history-error {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 48px;
    color: var(--accent-red, #f38ba8);
    text-align: center;
    direction: rtl;
}

.diff-error i,
.history-error i {
    font-size: 48px;
    margin-bottom: 16px;
}

/* Overlay */
.panel-overlay {
    position: fixed;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    background: rgba(0, 0, 0, 0.5);
    z-index: 999;
    opacity: 0;
    visibility: hidden;
    transition: all 0.3s ease;
}

.panel-overlay.visible {
    opacity: 1;
    visibility: visible;
}

/* View Mode Toggle */
.diff-view-toggle {
    display: flex;
    gap: 4px;
    padding: 4px;
    background: var(--bg-tertiary, #313244);
    border-radius: 6px;
}

.diff-view-toggle button {
    padding: 6px 12px;
    font-size: 12px;
    border: none;
    border-radius: 4px;
    background: transparent;
    color: var(--text-secondary, #bac2de);
    cursor: pointer;
    transition: all 0.2s ease;
}

.diff-view-toggle button.active {
    background: var(--accent-blue, #89b4fa);
    color: var(--bg-primary, #1e1e2e);
}

/* Compare Selector */
.compare-selector {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px 16px;
    background: var(--bg-tertiary, #313244);
    border-bottom: 1px solid var(--border-color, #45475a);
    direction: rtl;
}

.compare-selector label {
    font-size: 12px;
    color: var(--text-secondary, #bac2de);
}

.compare-selector select {
    padding: 6px 10px;
    font-size: 12px;
    background: var(--bg-primary, #1e1e2e);
    border: 1px solid var(--border-color, #45475a);
    border-radius: 4px;
    color: var(--text-primary, #cdd6f4);
    cursor: pointer;
}

.compare-btn {
    padding: 6px 16px;
    font-size: 12px;
    background: var(--accent-blue, #89b4fa);
    border: none;
    border-radius: 4px;
    color: var(--bg-primary, #1e1e2e);
    cursor: pointer;
    transition: all 0.2s ease;
}

.compare-btn:hover {
    background: var(--accent-lavender, #b4befe);
}

.compare-btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
}
```

### שלב 3.2: JavaScript - מודול היסטוריה ו-Diff

צור קובץ חדש `repo-history.js` או הוסף ל-`repo-browser.js`:

```javascript
// webapp/static/js/repo-history.js

/**
 * מודול להיסטוריית Git ותצוגת Diff
 */
const RepoHistory = (function() {
    'use strict';

    // State
    const state = {
        currentFile: null,
        commits: [],
        selectedCommits: [],  // לבחירת commits להשוואה
        isLoading: false,
        hasMore: true,
        skip: 0,
        limit: 20
    };

    // DOM Elements
    let historyPanel = null;
    let diffModal = null;
    let overlay = null;

    // ============================================
    // Initialization
    // ============================================

    function init() {
        createHistoryPanel();
        createDiffModal();
        createOverlay();
        bindGlobalEvents();
    }

    function createHistoryPanel() {
        historyPanel = document.createElement('div');
        historyPanel.className = 'history-panel';
        historyPanel.innerHTML = `
            <div class="history-panel-header">
                <h3>
                    <i class="bi bi-clock-history"></i>
                    היסטוריית קובץ
                </h3>
                <button class="history-panel-close" aria-label="סגור">
                    <i class="bi bi-x-lg"></i>
                </button>
            </div>
            <div class="compare-selector" style="display: none;">
                <label>השווה:</label>
                <select class="compare-from" title="מ-commit">
                    <option value="">בחר commit ישן</option>
                </select>
                <span class="arrow">←</span>
                <select class="compare-to" title="ל-commit">
                    <option value="">בחר commit חדש</option>
                </select>
                <button class="compare-btn" disabled>השווה</button>
            </div>
            <div class="history-commits"></div>
        `;
        document.body.appendChild(historyPanel);

        // Event listeners
        historyPanel.querySelector('.history-panel-close').addEventListener('click', closeHistoryPanel);
        historyPanel.querySelector('.compare-btn').addEventListener('click', compareSelected);

        // Compare selectors
        const compareFrom = historyPanel.querySelector('.compare-from');
        const compareTo = historyPanel.querySelector('.compare-to');
        [compareFrom, compareTo].forEach(select => {
            select.addEventListener('change', updateCompareButton);
        });
    }

    function createDiffModal() {
        diffModal = document.createElement('div');
        diffModal.className = 'diff-modal';
        diffModal.innerHTML = `
            <div class="diff-modal-content">
                <div class="diff-modal-header">
                    <div class="diff-modal-title">
                        <h3>
                            <i class="bi bi-file-diff"></i>
                            השוואת שינויים
                        </h3>
                        <div class="diff-commits-info">
                            <span class="commit-badge old"></span>
                            <span class="arrow">→</span>
                            <span class="commit-badge new"></span>
                        </div>
                    </div>
                    <div class="diff-view-toggle">
                        <button class="unified active" data-view="unified">Unified</button>
                        <button class="split" data-view="split">Side by Side</button>
                    </div>
                    <button class="diff-modal-close" aria-label="סגור">
                        <i class="bi bi-x-lg"></i>
                    </button>
                </div>
                <div class="diff-stats"></div>
                <div class="diff-content"></div>
            </div>
        `;
        document.body.appendChild(diffModal);

        // Event listeners
        diffModal.querySelector('.diff-modal-close').addEventListener('click', closeDiffModal);
        diffModal.addEventListener('click', (e) => {
            if (e.target === diffModal) closeDiffModal();
        });

        // View toggle
        diffModal.querySelectorAll('.diff-view-toggle button').forEach(btn => {
            btn.addEventListener('click', () => {
                diffModal.querySelectorAll('.diff-view-toggle button').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                // TODO: Switch view mode
            });
        });
    }

    function createOverlay() {
        overlay = document.createElement('div');
        overlay.className = 'panel-overlay';
        overlay.addEventListener('click', closeHistoryPanel);
        document.body.appendChild(overlay);
    }

    function bindGlobalEvents() {
        // Escape key closes panels
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                if (diffModal.classList.contains('open')) {
                    closeDiffModal();
                } else if (historyPanel.classList.contains('open')) {
                    closeHistoryPanel();
                }
            }
        });
    }

    // ============================================
    // History Panel
    // ============================================

    async function openHistoryPanel(filePath) {
        state.currentFile = filePath;
        state.commits = [];
        state.skip = 0;
        state.hasMore = true;
        state.selectedCommits = [];

        historyPanel.classList.add('open');
        overlay.classList.add('visible');

        // Update title
        const title = historyPanel.querySelector('.history-panel-header h3');
        title.innerHTML = `
            <i class="bi bi-clock-history"></i>
            היסטוריית: ${escapeHtml(getFileName(filePath))}
        `;

        await loadHistory();
    }

    function closeHistoryPanel() {
        historyPanel.classList.remove('open');
        overlay.classList.remove('visible');
    }

    async function loadHistory(append = false) {
        if (state.isLoading) return;
        state.isLoading = true;

        const container = historyPanel.querySelector('.history-commits');

        if (!append) {
            container.innerHTML = `
                <div class="history-loading">
                    <div class="spinner"></div>
                    <span>טוען היסטוריה...</span>
                </div>
            `;
        }

        try {
            const params = new URLSearchParams({
                limit: state.limit,
                skip: state.skip
            });

            const response = await fetch(
                `/repo/api/history/${encodeURIComponent(state.currentFile)}?${params}`
            );

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }

            const data = await response.json();

            if (!data.success) {
                throw new Error(data.message || 'שגיאה בטעינת היסטוריה');
            }

            state.commits = append ? [...state.commits, ...data.commits] : data.commits;
            state.hasMore = data.has_more;
            state.skip += data.commits.length;

            renderCommits(container, append);
            updateCompareSelectors();

        } catch (error) {
            console.error('Error loading history:', error);
            container.innerHTML = `
                <div class="history-error">
                    <i class="bi bi-exclamation-triangle"></i>
                    <p>${escapeHtml(error.message)}</p>
                    <button onclick="RepoHistory.loadHistory()">נסה שוב</button>
                </div>
            `;
        } finally {
            state.isLoading = false;
        }
    }

    function renderCommits(container, append = false) {
        if (!append) {
            container.innerHTML = '';
        } else {
            // Remove load more button if exists
            const loadMoreBtn = container.querySelector('.history-load-more');
            if (loadMoreBtn) loadMoreBtn.remove();
        }

        state.commits.slice(append ? -state.limit : 0).forEach((commit, index) => {
            const commitEl = createCommitElement(commit, index);
            container.appendChild(commitEl);
        });

        // Add load more button
        if (state.hasMore) {
            const loadMoreBtn = document.createElement('button');
            loadMoreBtn.className = 'history-load-more';
            loadMoreBtn.innerHTML = `
                <i class="bi bi-arrow-down-circle"></i>
                טען עוד commits
            `;
            loadMoreBtn.addEventListener('click', () => loadHistory(true));
            container.appendChild(loadMoreBtn);
        }
    }

    function createCommitElement(commit, index) {
        const el = document.createElement('div');
        el.className = 'history-commit';
        el.dataset.hash = commit.hash;

        const relativeDate = formatRelativeDate(commit.timestamp);
        const fullDate = new Date(commit.timestamp * 1000).toLocaleString('he-IL');

        el.innerHTML = `
            <div class="commit-header">
                <span class="commit-hash">${escapeHtml(commit.short_hash)}</span>
                <span class="commit-date" title="${fullDate}">${relativeDate}</span>
            </div>
            <div class="commit-message">${escapeHtml(commit.message)}</div>
            <div class="commit-author">
                <i class="bi bi-person-circle"></i>
                ${escapeHtml(commit.author)}
            </div>
            <div class="commit-actions">
                <button class="commit-action-btn view-btn" title="צפה בגרסה זו">
                    <i class="bi bi-eye"></i>
                    צפה
                </button>
                <button class="commit-action-btn diff-btn" title="השווה לגרסה הנוכחית">
                    <i class="bi bi-file-diff"></i>
                    השווה ל-HEAD
                </button>
                ${index > 0 ? `
                    <button class="commit-action-btn diff-prev-btn" title="השווה לcommit הקודם">
                        <i class="bi bi-arrow-left-right"></i>
                        השווה לקודם
                    </button>
                ` : ''}
            </div>
        `;

        // Event listeners
        el.querySelector('.view-btn').addEventListener('click', (e) => {
            e.stopPropagation();
            viewFileAtCommit(commit.hash);
        });

        el.querySelector('.diff-btn').addEventListener('click', (e) => {
            e.stopPropagation();
            showDiff(commit.hash, 'HEAD');
        });

        const diffPrevBtn = el.querySelector('.diff-prev-btn');
        if (diffPrevBtn) {
            diffPrevBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                const prevCommit = state.commits[index + 1];
                if (prevCommit) {
                    showDiff(prevCommit.hash, commit.hash);
                }
            });
        }

        return el;
    }

    function updateCompareSelectors() {
        const compareFrom = historyPanel.querySelector('.compare-from');
        const compareTo = historyPanel.querySelector('.compare-to');

        const options = state.commits.map(c =>
            `<option value="${c.hash}">${c.short_hash} - ${escapeHtml(truncate(c.message, 30))}</option>`
        ).join('');

        compareFrom.innerHTML = '<option value="">בחר commit ישן</option>' + options;
        compareTo.innerHTML = '<option value="">בחר commit חדש</option>' + options;

        // Show selector if we have commits
        const selector = historyPanel.querySelector('.compare-selector');
        selector.style.display = state.commits.length > 1 ? 'flex' : 'none';
    }

    function updateCompareButton() {
        const compareFrom = historyPanel.querySelector('.compare-from').value;
        const compareTo = historyPanel.querySelector('.compare-to').value;
        const compareBtn = historyPanel.querySelector('.compare-btn');

        compareBtn.disabled = !compareFrom || !compareTo || compareFrom === compareTo;
    }

    function compareSelected() {
        const compareFrom = historyPanel.querySelector('.compare-from').value;
        const compareTo = historyPanel.querySelector('.compare-to').value;

        if (compareFrom && compareTo && compareFrom !== compareTo) {
            showDiff(compareFrom, compareTo);
        }
    }

    // ============================================
    // File Viewer at Commit
    // ============================================

    async function viewFileAtCommit(commit) {
        try {
            const response = await fetch(
                `/repo/api/file-at-commit/${commit}/${encodeURIComponent(state.currentFile)}`
            );

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }

            const data = await response.json();

            if (!data.success) {
                throw new Error(data.message || 'שגיאה בטעינת קובץ');
            }

            // Update editor content
            // זה תלוי באיך העורך מוגדר בפרויקט
            if (window.RepoState && window.RepoState.editor) {
                const editor = window.RepoState.editor;
                editor.setValue(data.content);

                // Update file info to show it's a historical version
                const fileInfo = document.querySelector('.file-info');
                if (fileInfo) {
                    const shortHash = commit.substring(0, 7);
                    fileInfo.innerHTML = `
                        <span class="file-path">${escapeHtml(state.currentFile)}</span>
                        <span class="commit-badge" style="background: var(--accent-yellow); color: #1e1e2e; margin-right: 8px;">
                            @ ${shortHash}
                        </span>
                        <button class="btn-back-to-head" onclick="RepoHistory.backToHead()">
                            <i class="bi bi-arrow-counterclockwise"></i>
                            חזור ל-HEAD
                        </button>
                    `;
                }
            }

            // Optionally close history panel
            // closeHistoryPanel();

        } catch (error) {
            console.error('Error viewing file at commit:', error);
            alert('שגיאה: ' + error.message);
        }
    }

    async function backToHead() {
        if (!state.currentFile) return;

        // Reload current file from HEAD
        if (window.selectFile) {
            window.selectFile(state.currentFile);
        }
    }

    // ============================================
    // Diff Modal
    // ============================================

    async function showDiff(commit1, commit2) {
        diffModal.classList.add('open');

        const content = diffModal.querySelector('.diff-content');
        const stats = diffModal.querySelector('.diff-stats');
        const commitsInfo = diffModal.querySelector('.diff-commits-info');

        // Update header
        commitsInfo.querySelector('.commit-badge.old').textContent =
            commit1.substring(0, 7);
        commitsInfo.querySelector('.commit-badge.new').textContent =
            commit2 === 'HEAD' ? 'HEAD' : commit2.substring(0, 7);

        content.innerHTML = `
            <div class="diff-loading">
                <div class="spinner"></div>
                <span>טוען השוואה...</span>
            </div>
        `;
        stats.innerHTML = '';

        try {
            const url = state.currentFile
                ? `/repo/api/diff/${commit1}/${commit2}/${encodeURIComponent(state.currentFile)}`
                : `/repo/api/diff/${commit1}/${commit2}`;

            const response = await fetch(url);

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }

            const data = await response.json();

            if (!data.success) {
                throw new Error(data.message || 'שגיאה בטעינת diff');
            }

            renderDiffStats(stats, data.stats);
            renderDiff(content, data.parsed);

        } catch (error) {
            console.error('Error loading diff:', error);
            content.innerHTML = `
                <div class="diff-error">
                    <i class="bi bi-exclamation-triangle"></i>
                    <p>${escapeHtml(error.message)}</p>
                </div>
            `;
        }
    }

    function closeDiffModal() {
        diffModal.classList.remove('open');
    }

    function renderDiffStats(container, stats) {
        container.innerHTML = `
            <div class="diff-stat files">
                <i class="bi bi-file-earmark"></i>
                <span>${stats.files_changed} קבצים שונו</span>
            </div>
            <div class="diff-stat additions">
                <i class="bi bi-plus-lg"></i>
                <span>${stats.additions} שורות נוספו</span>
            </div>
            <div class="diff-stat deletions">
                <i class="bi bi-dash-lg"></i>
                <span>${stats.deletions} שורות נמחקו</span>
            </div>
        `;
    }

    function renderDiff(container, parsed) {
        const html = parsed.files.map(file => renderFileDiff(file)).join('');
        container.innerHTML = `<div class="diff-unified">${html}</div>`;
    }

    function renderFileDiff(file) {
        const statusClass = file.status || 'modified';
        const statusText = {
            added: 'חדש',
            modified: 'שונה',
            deleted: 'נמחק',
            renamed: 'שונה שם'
        }[statusClass] || statusClass;

        let hunksHtml = '';

        if (file.hunks && file.hunks.length > 0) {
            hunksHtml = file.hunks.map(hunk => {
                let oldLine = hunk.old_start;
                let newLine = hunk.new_start;

                const linesHtml = hunk.lines.map(line => {
                    let oldNum = '';
                    let newNum = '';

                    if (line.type === 'context') {
                        oldNum = oldLine++;
                        newNum = newLine++;
                    } else if (line.type === 'deletion') {
                        oldNum = oldLine++;
                    } else if (line.type === 'addition') {
                        newNum = newLine++;
                    }

                    return `
                        <div class="diff-line ${line.type}">
                            <span class="diff-line-number old">${oldNum}</span>
                            <span class="diff-line-number new">${newNum}</span>
                            <span class="diff-line-content">${escapeHtml(line.content)}</span>
                        </div>
                    `;
                }).join('');

                const headerInfo = hunk.header ? ` ${escapeHtml(hunk.header)}` : '';

                return `
                    <div class="diff-hunk">
                        <div class="diff-hunk-header">
                            @@ -${hunk.old_start},${hunk.old_count} +${hunk.new_start},${hunk.new_count} @@${headerInfo}
                        </div>
                        ${linesHtml}
                    </div>
                `;
            }).join('');
        }

        return `
            <div class="diff-file">
                <div class="diff-file-header">
                    <span class="diff-file-status ${statusClass}">${statusText}</span>
                    <span class="diff-file-path">${escapeHtml(file.new_path || file.old_path)}</span>
                    <div class="diff-file-stats">
                        <span class="additions">+${file.additions}</span>
                        <span class="deletions">-${file.deletions}</span>
                    </div>
                </div>
                ${hunksHtml}
            </div>
        `;
    }

    // ============================================
    // Utility Functions
    // ============================================

    function escapeHtml(text) {
        if (!text) return '';
        return String(text)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }

    function getFileName(path) {
        return path.split('/').pop();
    }

    function truncate(text, maxLength) {
        if (!text || text.length <= maxLength) return text;
        return text.substring(0, maxLength) + '...';
    }

    function formatRelativeDate(timestamp) {
        const now = Date.now() / 1000;
        const diff = now - timestamp;

        if (diff < 60) return 'הרגע';
        if (diff < 3600) return `לפני ${Math.floor(diff / 60)} דקות`;
        if (diff < 86400) return `לפני ${Math.floor(diff / 3600)} שעות`;
        if (diff < 604800) return `לפני ${Math.floor(diff / 86400)} ימים`;
        if (diff < 2592000) return `לפני ${Math.floor(diff / 604800)} שבועות`;
        if (diff < 31536000) return `לפני ${Math.floor(diff / 2592000)} חודשים`;
        return `לפני ${Math.floor(diff / 31536000)} שנים`;
    }

    // ============================================
    // Public API
    // ============================================

    return {
        init,
        openHistoryPanel,
        closeHistoryPanel,
        showDiff,
        closeDiffModal,
        viewFileAtCommit,
        backToHead,
        loadHistory,
        get state() { return state; }
    };
})();

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    RepoHistory.init();
});

// Export for use in other modules
window.RepoHistory = RepoHistory;
```

### שלב 3.3: הוספת כפתור היסטוריה לUI קיים

עדכן את `repo-browser.js` להוספת כפתור היסטוריה:

```javascript
// הוסף לפונקציה שמציגה פרטי קובץ (בתוך repo-browser.js)

function updateFileHeader(filePath) {
    const fileHeader = document.querySelector('.file-header');
    if (!fileHeader) return;

    const fileName = filePath.split('/').pop();

    fileHeader.innerHTML = `
        <div class="file-info">
            <i class="bi bi-file-earmark-code"></i>
            <span class="file-name">${escapeHtml(fileName)}</span>
            <span class="file-path-full" title="${escapeHtml(filePath)}">
                ${escapeHtml(filePath)}
            </span>
        </div>
        <div class="file-actions">
            <button class="file-history-btn" onclick="RepoHistory.openHistoryPanel('${escapeJsStr(filePath)}')" title="היסטוריית קובץ">
                <i class="bi bi-clock-history"></i>
                היסטוריה
            </button>
            <button class="file-copy-btn" onclick="copyFileContent()" title="העתק תוכן">
                <i class="bi bi-clipboard"></i>
            </button>
            <button class="file-raw-btn" onclick="openRawFile('${escapeJsStr(filePath)}')" title="צפה בקובץ גולמי">
                <i class="bi bi-file-text"></i>
            </button>
        </div>
    `;
}

function escapeJsStr(text) {
    return String(text).replace(/\\/g, '\\\\').replace(/'/g, "\\'");
}
```

### שלב 3.4: עדכון HTML Template

הוסף ל-`index.html` את ה-script החדש:

```html
<!-- לפני סגירת </body> -->
<script src="{{ url_for('static', filename='js/repo-history.js') }}"></script>
```

---

## 4. אבטחה וטיפול בשגיאות

### 4.1: וולידציות Backend

```python
# webapp/services/git_mirror_service.py

import re

class GitMirrorService:
    # Patterns קיימים - הוסף אם לא קיימים

    # תבנית לשם ריפו: a-z, 0-9, -, _ בלבד
    REPO_NAME_PATTERN = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9_-]{0,99}$')

    # תבנית לנתיב קובץ - ללא path traversal
    FILE_PATH_PATTERN = re.compile(
        r'^(?!.*\.\.)'           # No ..
        r'(?!.*//)'              # No //
        r'(?!/)'                 # No leading /
        r'[a-zA-Z0-9._/-]+'      # Allowed chars
        r'(?<!/)'                # No trailing /
        r'$'
    )

    # תבנית ל-ref (branch, tag, commit hash)
    REF_PATTERN = re.compile(
        r'^('
        r'HEAD|'                              # HEAD
        r'[a-f0-9]{4,40}|'                    # Commit hash (short or full)
        r'[a-zA-Z][a-zA-Z0-9._/-]{0,100}'     # Branch/tag name
        r')$'
    )

    def _validate_repo_name(self, name: str) -> bool:
        """וולידציה של שם ריפו."""
        if not name or not isinstance(name, str):
            return False
        if '\x00' in name:  # NUL byte check
            return False
        return bool(self.REPO_NAME_PATTERN.match(name))

    def _validate_repo_file_path(self, path: str) -> bool:
        """וולידציה של נתיב קובץ - מונע path traversal."""
        if not path or not isinstance(path, str):
            return False
        if '\x00' in path:  # NUL byte check
            return False
        # Normalize and check
        normalized = os.path.normpath(path)
        if normalized.startswith('..') or normalized.startswith('/'):
            return False
        return bool(self.FILE_PATH_PATTERN.match(path))

    def _validate_repo_ref(self, ref: str) -> bool:
        """וולידציה של Git reference."""
        if not ref or not isinstance(ref, str):
            return False
        if '\x00' in ref:  # NUL byte check
            return False
        if len(ref) > 150:
            return False
        return bool(self.REF_PATTERN.match(ref))

    def _sanitize_output(self, output: str) -> str:
        """הסרת מידע רגיש מפלט Git."""
        if not output:
            return ''
        # Remove tokens from output
        sanitized = re.sub(
            r'https://[^:]+:[^@]+@',
            'https://***:***@',
            output
        )
        return sanitized
```

### 4.2: Error Handling Frontend

```javascript
// repo-history.js - טיפול בשגיאות משופר

class HistoryError extends Error {
    constructor(code, message, details = {}) {
        super(message);
        this.code = code;
        this.details = details;
    }
}

const ERROR_MESSAGES = {
    'invalid_repo_name': 'שם ריפו לא תקין',
    'invalid_file_path': 'נתיב קובץ לא תקין',
    'invalid_ref': 'Reference לא תקין',
    'invalid_commit': 'Commit לא תקין',
    'repo_not_found': 'הריפו לא נמצא',
    'file_not_found': 'הקובץ לא נמצא',
    'file_not_in_commit': 'הקובץ לא קיים ב-commit זה',
    'commit_not_found': 'ה-commit לא נמצא',
    'binary_file': 'לא ניתן להציג קובץ בינארי',
    'timeout': 'הפעולה ארכה יותר מדי זמן - נסה שוב',
    'service_unavailable': 'השירות לא זמין כרגע',
    'network_error': 'שגיאת רשת - בדוק את החיבור',
    'internal_error': 'שגיאה פנימית - נסה שוב מאוחר יותר'
};

async function fetchWithErrorHandling(url, options = {}) {
    try {
        const response = await fetch(url, {
            ...options,
            headers: {
                'Accept': 'application/json',
                ...options.headers
            }
        });

        // Handle HTTP errors
        if (!response.ok) {
            let errorData;
            try {
                errorData = await response.json();
            } catch {
                errorData = { error: 'http_error', message: `HTTP ${response.status}` };
            }

            throw new HistoryError(
                errorData.error || 'http_error',
                ERROR_MESSAGES[errorData.error] || errorData.message || 'שגיאה לא ידועה',
                errorData
            );
        }

        const data = await response.json();

        // Handle API errors
        if (data.error || data.success === false) {
            throw new HistoryError(
                data.error || 'api_error',
                ERROR_MESSAGES[data.error] || data.message || 'שגיאה ב-API',
                data
            );
        }

        return data;

    } catch (error) {
        // Network errors
        if (error instanceof TypeError && error.message.includes('fetch')) {
            throw new HistoryError(
                'network_error',
                ERROR_MESSAGES.network_error
            );
        }

        // Re-throw HistoryError
        if (error instanceof HistoryError) {
            throw error;
        }

        // Unknown errors
        throw new HistoryError(
            'unknown_error',
            error.message || 'שגיאה לא ידועה'
        );
    }
}

function showErrorToast(message, duration = 5000) {
    const toast = document.createElement('div');
    toast.className = 'error-toast';
    toast.innerHTML = `
        <i class="bi bi-exclamation-triangle"></i>
        <span>${escapeHtml(message)}</span>
        <button onclick="this.parentElement.remove()">
            <i class="bi bi-x"></i>
        </button>
    `;
    document.body.appendChild(toast);

    // Auto remove
    setTimeout(() => {
        toast.classList.add('fade-out');
        setTimeout(() => toast.remove(), 300);
    }, duration);
}
```

CSS לtoast:

```css
/* Error Toast */
.error-toast {
    position: fixed;
    bottom: 24px;
    left: 50%;
    transform: translateX(-50%);
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 12px 20px;
    background: var(--accent-red, #f38ba8);
    color: var(--bg-primary, #1e1e2e);
    border-radius: 8px;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
    z-index: 9999;
    animation: slideUp 0.3s ease;
}

.error-toast.fade-out {
    animation: slideDown 0.3s ease forwards;
}

.error-toast button {
    background: none;
    border: none;
    color: inherit;
    cursor: pointer;
    padding: 4px;
    opacity: 0.7;
}

.error-toast button:hover {
    opacity: 1;
}

@keyframes slideUp {
    from {
        transform: translateX(-50%) translateY(100%);
        opacity: 0;
    }
    to {
        transform: translateX(-50%) translateY(0);
        opacity: 1;
    }
}

@keyframes slideDown {
    from {
        transform: translateX(-50%) translateY(0);
        opacity: 1;
    }
    to {
        transform: translateX(-50%) translateY(100%);
        opacity: 0;
    }
}
```

---

## 5. אינטגרציה עם git_mirror_service

### 5.1: רישום ה-service ב-Flask App

```python
# webapp/__init__.py או app.py

from webapp.services.git_mirror_service import GitMirrorService

def create_app(config=None):
    app = Flask(__name__)
    # ... config ...

    # Initialize Git Mirror Service
    git_service = GitMirrorService(
        mirrors_base_path=app.config.get('GIT_MIRRORS_PATH', '/data/git_mirrors'),
        github_token=app.config.get('GITHUB_TOKEN')
    )

    # Register as extension
    app.extensions['git_mirror_service'] = git_service

    # או באמצעות g context
    @app.before_request
    def inject_git_service():
        g.git_service = git_service

    return app
```

### 5.2: גישה ל-service ב-Routes

```python
# repo_browser.py

from flask import current_app, g

def get_git_service():
    """Helper לקבלת ה-Git service."""
    # אפשרות 1: מ-extensions
    service = current_app.extensions.get('git_mirror_service')
    if service:
        return service

    # אפשרות 2: מ-g context
    if hasattr(g, 'git_service'):
        return g.git_service

    # אפשרות 3: יצירה חדשה (fallback)
    from webapp.services.git_mirror_service import GitMirrorService
    return GitMirrorService(
        mirrors_base_path=current_app.config.get('GIT_MIRRORS_PATH'),
        github_token=current_app.config.get('GITHUB_TOKEN')
    )
```

### 5.3: שימוש במתודות קיימות

ה-`git_mirror_service` כבר מכיל מתודות שימושיות:

```python
# דוגמאות שימוש

# בדיקה אם ריפו קיים
if not git_service.mirror_exists(repo_name):
    return {"error": "repo_not_found"}

# קבלת תוכן קובץ נוכחי
content_result = git_service.get_file_content(repo_name, file_path, ref="HEAD")

# קבלת רשימת קבצים שהשתנו בין commits
changes = git_service.get_changed_files(repo_name, old_sha, new_sha)
# Returns: {"added": [...], "modified": [...], "removed": [...], "renamed": [...]}

# קבלת מידע על commit אחרון
last_commit = git_service.get_last_commit_info(repo_name, ref="HEAD")
```

---

## 6. תמיכה ב-RTL

### 6.1: כללי CSS ל-RTL

```css
/* ============================================
   RTL Support
   ============================================ */

/* General RTL direction */
.history-panel,
.history-commit,
.diff-stats,
.compare-selector,
.diff-modal-title,
.error-toast,
.history-error,
.diff-error {
    direction: rtl;
    text-align: right;
}

/* Code always LTR */
.diff-unified,
.diff-line-content,
.diff-file-path,
.commit-hash,
.diff-hunk-header,
.CodeMirror {
    direction: ltr;
    text-align: left;
}

/* Flip icons for RTL */
[dir="rtl"] .bi-arrow-left::before {
    content: "\F12F"; /* arrow-right */
}

[dir="rtl"] .bi-arrow-right::before {
    content: "\F130"; /* arrow-left */
}

/* Panel positioning for RTL */
html[dir="rtl"] .history-panel {
    left: auto;
    right: 0;
    border-left: none;
    border-right: 1px solid var(--border-color, #45475a);
    transform: translateX(100%);
}

html[dir="rtl"] .history-panel.open {
    transform: translateX(0);
}

/* Commit selected border */
html[dir="rtl"] .history-commit.selected {
    border-right: none;
    border-left: 3px solid var(--accent-blue, #89b4fa);
}

/* Line numbers alignment */
.diff-line-number {
    direction: ltr;
    text-align: right;
}

/* File stats alignment */
html[dir="rtl"] .diff-file-stats {
    margin-right: 0;
    margin-left: auto;
}

/* Responsive adjustments for RTL */
@media (max-width: 768px) {
    .history-panel {
        width: 100%;
        max-width: 100%;
    }

    .diff-modal-content {
        width: 100%;
        height: 100%;
        border-radius: 0;
    }
}
```

### 6.2: JavaScript RTL Detection

```javascript
// בדיקת כיוון המסמך
function isRTL() {
    return document.documentElement.dir === 'rtl' ||
           document.body.dir === 'rtl' ||
           getComputedStyle(document.body).direction === 'rtl';
}

// התאמת פוזיציה דינמית
function positionPanel(panel) {
    if (isRTL()) {
        panel.style.right = '0';
        panel.style.left = 'auto';
    } else {
        panel.style.left = '0';
        panel.style.right = 'auto';
    }
}
```

### 6.3: תאריכים בעברית

```javascript
// פורמט תאריך עברי
function formatHebrewDate(timestamp) {
    const date = new Date(timestamp * 1000);
    return date.toLocaleDateString('he-IL', {
        year: 'numeric',
        month: 'long',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit'
    });
}

// זמן יחסי בעברית
function formatRelativeDateHebrew(timestamp) {
    const now = Date.now() / 1000;
    const diff = now - timestamp;

    const units = [
        { limit: 60, singular: 'שנייה', plural: 'שניות' },
        { limit: 3600, divisor: 60, singular: 'דקה', plural: 'דקות' },
        { limit: 86400, divisor: 3600, singular: 'שעה', plural: 'שעות' },
        { limit: 604800, divisor: 86400, singular: 'יום', plural: 'ימים' },
        { limit: 2592000, divisor: 604800, singular: 'שבוע', plural: 'שבועות' },
        { limit: 31536000, divisor: 2592000, singular: 'חודש', plural: 'חודשים' },
        { divisor: 31536000, singular: 'שנה', plural: 'שנים' }
    ];

    for (const unit of units) {
        if (!unit.limit || diff < unit.limit) {
            const value = unit.divisor ? Math.floor(diff / unit.divisor) : 1;
            const word = value === 1 ? unit.singular : unit.plural;
            return `לפני ${value} ${word}`;
        }
    }

    return formatHebrewDate(timestamp);
}
```

---

## 7. בדיקות

### 7.1: בדיקות Backend (pytest)

```python
# tests/test_git_history.py

import pytest
from webapp.services.git_mirror_service import GitMirrorService

class TestGitHistory:
    """בדיקות למתודות היסטוריה ו-diff."""

    @pytest.fixture
    def git_service(self, tmp_path):
        """יצירת service לבדיקות."""
        return GitMirrorService(mirrors_base_path=str(tmp_path))

    # ============================================
    # Validation Tests
    # ============================================

    def test_validate_repo_name_valid(self, git_service):
        """שמות ריפו תקינים."""
        valid_names = ['repo', 'my-repo', 'repo_123', 'A1']
        for name in valid_names:
            assert git_service._validate_repo_name(name) is True

    def test_validate_repo_name_invalid(self, git_service):
        """שמות ריפו לא תקינים."""
        invalid_names = [
            '', None, 123,  # Empty/wrong type
            '-repo',  # Starts with -
            '../etc',  # Path traversal
            'repo\x00',  # NUL byte
            'a' * 200,  # Too long
        ]
        for name in invalid_names:
            assert git_service._validate_repo_name(name) is False

    def test_validate_file_path_valid(self, git_service):
        """נתיבי קבצים תקינים."""
        valid_paths = [
            'file.py',
            'src/main.py',
            'path/to/file.js',
            'file-name_123.txt'
        ]
        for path in valid_paths:
            assert git_service._validate_repo_file_path(path) is True

    def test_validate_file_path_invalid(self, git_service):
        """נתיבי קבצים לא תקינים - path traversal."""
        invalid_paths = [
            '../etc/passwd',
            'path/../../../etc',
            '/absolute/path',
            'path//double',
            '',
            None,
            'file\x00.txt'
        ]
        for path in invalid_paths:
            assert git_service._validate_repo_file_path(path) is False

    def test_validate_ref_valid(self, git_service):
        """References תקינים."""
        valid_refs = [
            'HEAD',
            'main',
            'feature/branch',
            'v1.0.0',
            'abc123',  # Short hash
            'a1b2c3d4e5f6789012345678901234567890abcd'  # Full hash
        ]
        for ref in valid_refs:
            assert git_service._validate_repo_ref(ref) is True

    def test_validate_ref_invalid(self, git_service):
        """References לא תקינים."""
        invalid_refs = [
            '',
            None,
            '-branch',
            'branch\x00',
            '../etc',
        ]
        for ref in invalid_refs:
            assert git_service._validate_repo_ref(ref) is False

    # ============================================
    # API Tests (with mock git)
    # ============================================

    def test_get_file_history_not_found(self, git_service):
        """היסטוריה לריפו שלא קיים."""
        result = git_service.get_file_history('nonexistent', 'file.py')
        assert 'error' in result
        assert result['error'] == 'repo_not_found'

    def test_get_file_history_invalid_path(self, git_service):
        """היסטוריה עם path traversal."""
        result = git_service.get_file_history('repo', '../etc/passwd')
        assert 'error' in result
        assert result['error'] == 'invalid_file_path'

    def test_get_diff_invalid_commits(self, git_service):
        """Diff עם commits לא תקינים."""
        result = git_service.get_diff('repo', '../evil', 'HEAD')
        assert 'error' in result

    # ============================================
    # Diff Parsing Tests
    # ============================================

    def test_parse_diff_simple(self, git_service):
        """פרסור diff פשוט."""
        diff_output = """diff --git a/file.txt b/file.txt
index 1234567..abcdefg 100644
--- a/file.txt
+++ b/file.txt
@@ -1,3 +1,4 @@
 line1
-old line
+new line
+added line
 line3
"""
        result = git_service._parse_diff(diff_output)

        assert len(result['files']) == 1
        file = result['files'][0]
        assert file['old_path'] == 'file.txt'
        assert file['new_path'] == 'file.txt'
        assert file['additions'] == 2
        assert file['deletions'] == 1

    def test_parse_diff_new_file(self, git_service):
        """פרסור diff של קובץ חדש."""
        diff_output = """diff --git a/newfile.txt b/newfile.txt
new file mode 100644
index 0000000..1234567
--- /dev/null
+++ b/newfile.txt
@@ -0,0 +1,2 @@
+line1
+line2
"""
        result = git_service._parse_diff(diff_output)

        assert len(result['files']) == 1
        file = result['files'][0]
        assert file['status'] == 'added'
        assert file['additions'] == 2
        assert file['deletions'] == 0


class TestRoutes:
    """בדיקות ל-API routes."""

    @pytest.fixture
    def client(self, app):
        """Flask test client."""
        return app.test_client()

    def test_history_endpoint_validation(self, client):
        """וולידציה של endpoint היסטוריה."""
        # Path traversal attempt
        response = client.get('/repo/api/history/../../../etc/passwd')
        assert response.status_code == 400
        data = response.get_json()
        assert data['error'] == 'invalid_file_path'

    def test_diff_endpoint_validation(self, client):
        """וולידציה של endpoint diff."""
        # Invalid commit hash
        response = client.get('/repo/api/diff/invalid!/HEAD/file.py')
        assert response.status_code == 400

    def test_file_at_commit_endpoint(self, client):
        """Endpoint של קובץ ב-commit."""
        # Non-existent commit
        response = client.get('/repo/api/file-at-commit/0000000/file.py')
        # Should return 404 for not found
        assert response.status_code in [400, 404]
```

### 7.2: בדיקות Frontend (Jest)

```javascript
// tests/repo-history.test.js

describe('RepoHistory', () => {
    beforeEach(() => {
        document.body.innerHTML = '';
        RepoHistory.init();
    });

    describe('escapeHtml', () => {
        it('should escape HTML entities', () => {
            expect(escapeHtml('<script>alert("xss")</script>'))
                .toBe('&lt;script&gt;alert(&quot;xss&quot;)&lt;/script&gt;');
        });

        it('should handle empty string', () => {
            expect(escapeHtml('')).toBe('');
        });

        it('should handle null', () => {
            expect(escapeHtml(null)).toBe('');
        });
    });

    describe('formatRelativeDate', () => {
        it('should return "הרגע" for recent timestamps', () => {
            const now = Date.now() / 1000;
            expect(formatRelativeDate(now - 30)).toBe('הרגע');
        });

        it('should return minutes for timestamps < 1 hour', () => {
            const now = Date.now() / 1000;
            expect(formatRelativeDate(now - 300)).toContain('דקות');
        });
    });

    describe('History Panel', () => {
        it('should create history panel on init', () => {
            expect(document.querySelector('.history-panel')).toBeTruthy();
        });

        it('should open panel when called', async () => {
            await RepoHistory.openHistoryPanel('test/file.py');
            expect(document.querySelector('.history-panel.open')).toBeTruthy();
        });

        it('should close panel on escape key', () => {
            RepoHistory.openHistoryPanel('test/file.py');
            document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
            expect(document.querySelector('.history-panel.open')).toBeFalsy();
        });
    });

    describe('Diff Modal', () => {
        it('should create diff modal on init', () => {
            expect(document.querySelector('.diff-modal')).toBeTruthy();
        });
    });
});
```

---

## סיכום

### רשימת קבצים לעריכה/יצירה:

1. **Backend:**
   - `webapp/services/git_mirror_service.py` - הוספת מתודות חדשות
   - `webapp/routes/repo_browser.py` - הוספת routes חדשים

2. **Frontend:**
   - `webapp/static/js/repo-history.js` - מודול חדש
   - `webapp/static/css/repo-browser.css` - הוספת סגנונות
   - `webapp/templates/repo/index.html` - הוספת script

3. **Tests:**
   - `tests/test_git_history.py` - בדיקות backend
   - `tests/repo-history.test.js` - בדיקות frontend

### שלבי מימוש מומלצים:

1. התחל עם מתודות ה-Backend והוולידציות
2. הוסף את ה-Routes ובדוק עם curl/Postman
3. מימוש ה-CSS (כי אפשר לראות מיד)
4. מימוש ה-JavaScript בהדרגה
5. הוספת בדיקות
6. שיפורי UX (אנימציות, כפתורי מקשים)

### אפשרויות הרחבה עתידיות:

- **Blame view** - מי כתב כל שורה
- **Branch comparison** - השוואה בין branches
- **Commit graph** - ויזואליזציה של היסטוריה
- **Monaco diff editor** - חווית עריכה כמו VSCode
- **Inline comments** - הערות על שורות ב-diff
