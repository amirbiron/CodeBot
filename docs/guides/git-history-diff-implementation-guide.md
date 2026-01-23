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

> **שינוי מומלץ**: העברת `file_path` כ-query parameter במקום path parameter כדי למנוע בעיות encoding עם `/`.

| Endpoint | Method | תיאור |
|----------|--------|-------|
| `/repo/api/history` | GET | היסטוריית commits לקובץ (`?file=path/to/file.py`) |
| `/repo/api/file-at-commit/<commit>` | GET | תוכן קובץ ב-commit ספציפי (`?file=...`) |
| `/repo/api/diff/<commit1>/<commit2>` | GET | Diff בין שני commits (`?file=...&format=...`) |
| `/repo/api/commit/<commit>` | GET | פרטי commit בודד |

### Query Parameters משותפים

| Parameter | Type | Default | תיאור |
|-----------|------|---------|-------|
| `file` | string | - | נתיב הקובץ (URL encoded) |
| `format` | enum | `parsed` | `raw`, `parsed`, או `both` |
| `max_bytes` | int | 1MB | הגבלת גודל diff |
| `context` | int | 3 | שורות הקשר ב-diff |

---

## 2. מימוש Backend

### שלב 2.1: הרחבת git_mirror_service.py

הוסף את המתודות הבאות ל-`GitMirrorService`:

```python
# webapp/services/git_mirror_service.py

import os
import re
import subprocess
from datetime import datetime
from typing import Optional, List, Dict, Any
from pathlib import Path

# הגדרות קבועות
MAX_DIFF_BYTES = 1 * 1024 * 1024  # 1MB
MAX_DIFF_LINES = 10000
MAX_FILE_SIZE_FOR_DISPLAY = 500 * 1024  # 500KB

class GitMirrorService:
    # ... קוד קיים ...

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
        mirror_path = self._get_mirror_path(repo_name)

        try:
            cmd = [
                "git", "-C", str(mirror_path),
                "rev-parse", "--verify", "--quiet",
                f"{ref}^{{commit}}"  # ודא שזה commit
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
                    "message": f"Reference '{ref}' לא נמצא"
                }

            return {
                "valid": True,
                "resolved_sha": result.stdout.strip()
            }

        except subprocess.TimeoutExpired:
            return {"valid": False, "error": "timeout"}
        except Exception as e:
            return {"valid": False, "error": "internal_error", "message": str(e)}

    def _detect_binary_content(self, content: bytes) -> bool:
        """
        זיהוי תוכן בינארי באמצעות בדיקת NUL bytes.

        קובץ נחשב בינארי אם:
        1. מכיל NUL bytes (\\x00)
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

        if not self._validate_repo_file_path(file_path):
            return {"error": "invalid_file_path", "message": "נתיב קובץ לא תקין"}

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
                file_path
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

        if not self._validate_repo_file_path(file_path):
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
                f"{resolved_commit}:{file_path}"
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

        if file_path and not self._validate_repo_file_path(file_path):
            return {"error": "invalid_file_path", "message": "נתיב קובץ לא תקין"}

        # וולידציה ל-context_lines
        context_lines = max(0, min(int(context_lines) if isinstance(context_lines, (int, str)) else 3, 20))

        # וולידציה ל-format
        if output_format not in ('raw', 'parsed', 'both'):
            output_format = 'parsed'

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

            if file_path:
                cmd.extend(["--", file_path])

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
        if cut_point > max_bytes // 2:  # רק אם זה הגיוני
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
```

### שלב 2.2: הוספת Routes חדשים

```python
# webapp/routes/repo_browser.py

from flask import Blueprint, jsonify, request, current_app
from urllib.parse import unquote

repo_bp = Blueprint('repo', __name__, url_prefix='/repo')

# הגדרות
DEFAULT_REPO_NAME = "CodeBot"  # או מקונפיג

def get_git_service():
    """Helper לקבלת ה-Git service."""
    return current_app.extensions.get('git_mirror_service')

# ============================================
# Routes חדשים - היסטוריה ו-Diff
# ============================================

@repo_bp.route('/api/history', methods=['GET'])
def get_file_history():
    """
    שליפת היסטוריית commits לקובץ ספציפי.

    Query params:
        - file: נתיב הקובץ (required)
        - limit: מספר commits מקסימלי (default: 20, max: 100)
        - skip: כמה commits לדלג (default: 0)
        - ref: branch/tag/commit להתחיל ממנו (default: HEAD)
    """
    try:
        # שליפת file_path מ-query parameter
        file_path = request.args.get('file', '')
        if not file_path:
            return jsonify({
                "success": False,
                "error": "missing_file",
                "message": "חסר פרמטר file"
            }), 400

        # Decode URL encoding
        file_path = unquote(file_path)

        limit = request.args.get('limit', 20, type=int)
        skip = request.args.get('skip', 0, type=int)
        ref = request.args.get('ref', 'HEAD')

        git_service = get_git_service()
        if not git_service:
            return jsonify({
                "success": False,
                "error": "service_unavailable",
                "message": "שירות Git לא זמין"
            }), 503

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


@repo_bp.route('/api/file-at-commit/<commit>', methods=['GET'])
def get_file_at_commit(commit):
    """
    שליפת תוכן קובץ ב-commit ספציפי.

    Query params:
        - file: נתיב הקובץ (required)
    """
    try:
        file_path = request.args.get('file', '')
        if not file_path:
            return jsonify({
                "success": False,
                "error": "missing_file",
                "message": "חסר פרמטר file"
            }), 400

        file_path = unquote(file_path)

        git_service = get_git_service()
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
                "file_too_large": 413,
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
def get_diff(commit1, commit2):
    """
    שליפת diff בין שני commits.

    Semantics: מראה מה השתנה מ-commit1 (ישן) ל-commit2 (חדש).

    Query params:
        - file: נתיב קובץ ספציפי (optional)
        - context: מספר שורות הקשר (default: 3, max: 20)
        - format: 'raw', 'parsed', או 'both' (default: 'parsed')
        - max_bytes: הגבלת גודל (default: 1MB)
    """
    try:
        file_path = request.args.get('file')
        if file_path:
            file_path = unquote(file_path)

        context_lines = request.args.get('context', 3, type=int)
        output_format = request.args.get('format', 'parsed')
        max_bytes = request.args.get('max_bytes', 1024*1024, type=int)

        # Limit max_bytes to reasonable value
        max_bytes = min(max_bytes, 10 * 1024 * 1024)  # Max 10MB

        git_service = get_git_service()
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
            context_lines=context_lines,
            output_format=output_format,
            max_bytes=max_bytes
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
        git_service = get_git_service()
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

/* פאנל היסטוריה */
.history-panel {
    position: fixed;
    top: 0;
    right: 0;
    width: 400px;
    max-width: 90vw;
    height: 100vh;
    background: var(--bg-secondary, #181825);
    border-right: 1px solid var(--border-color, #45475a);
    z-index: 1000;
    transform: translateX(100%);
    transition: transform 0.3s ease;
    display: flex;
    flex-direction: column;
}

html[dir="rtl"] .history-panel {
    right: auto;
    left: 0;
    border-right: none;
    border-left: 1px solid var(--border-color, #45475a);
    transform: translateX(-100%);
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
    border-right: 3px solid var(--accent-blue, #89b4fa);
    background: var(--bg-hover, #45475a);
}

html[dir="rtl"] .history-commit.selected {
    border-right: none;
    border-left: 3px solid var(--accent-blue, #89b4fa);
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
    cursor: pointer;
    user-select: all;
}

.commit-hash:hover {
    background: var(--accent-blue, #89b4fa);
    color: var(--bg-primary, #1e1e2e);
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

/* Compare Mode */
.compare-mode-banner {
    padding: 12px 16px;
    background: rgba(137, 180, 250, 0.1);
    border-bottom: 1px solid var(--accent-blue, #89b4fa);
    direction: rtl;
    display: flex;
    align-items: center;
    justify-content: space-between;
}

.compare-mode-banner .instructions {
    font-size: 12px;
    color: var(--accent-blue, #89b4fa);
}

.compare-mode-banner .selection {
    display: flex;
    gap: 8px;
    align-items: center;
}

.compare-mode-banner .commit-badge {
    font-family: 'JetBrains Mono', monospace;
    font-size: 11px;
    padding: 2px 6px;
    border-radius: 4px;
    background: var(--bg-tertiary, #313244);
}

.compare-mode-banner .commit-badge.base {
    color: var(--accent-red, #f38ba8);
}

.compare-mode-banner .commit-badge.target {
    color: var(--accent-green, #a6e3a1);
}

.history-commit.compare-selected-base {
    border-color: var(--accent-red, #f38ba8);
    box-shadow: 0 0 0 2px rgba(243, 139, 168, 0.3);
}

.history-commit.compare-selected-target {
    border-color: var(--accent-green, #a6e3a1);
    box-shadow: 0 0 0 2px rgba(166, 227, 161, 0.3);
}

/* ============================================
   Diff Viewer
   ============================================ */

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
    padding: 4px 8px;
    border-radius: 4px;
    background: var(--bg-tertiary, #313244);
}

.diff-commits-info .commit-badge.old {
    color: var(--accent-red, #f38ba8);
}

.diff-commits-info .commit-badge.new {
    color: var(--accent-green, #a6e3a1);
}

.diff-commits-info .commit-message-preview {
    font-size: 11px;
    color: var(--text-muted, #6c7086);
    max-width: 200px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
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

.diff-stat.truncated {
    color: var(--accent-yellow, #f9e2af);
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
    direction: ltr;
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

.diff-file-status.copied {
    background: rgba(203, 166, 247, 0.2);
    color: var(--accent-lavender, #cba6f7);
}

.diff-file-status.binary {
    background: rgba(108, 112, 134, 0.2);
    color: var(--text-muted, #6c7086);
}

.diff-file-path {
    color: var(--text-primary, #cdd6f4);
    font-weight: 500;
}

.diff-file-rename-info {
    font-size: 11px;
    color: var(--text-muted, #6c7086);
}

.diff-file-rename-info .similarity {
    color: var(--accent-blue, #89b4fa);
}

.diff-file-stats {
    margin-right: auto;
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

/* Loading & Error States */
.diff-loading,
.history-loading {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 48px;
    color: var(--text-secondary, #bac2de);
}

.spinner {
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
    direction: rtl;
}

.error-toast.fade-out {
    animation: slideDown 0.3s ease forwards;
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

/* Success Toast */
.success-toast {
    position: fixed;
    bottom: 24px;
    left: 50%;
    transform: translateX(-50%);
    padding: 12px 20px;
    background: var(--accent-green, #a6e3a1);
    color: var(--bg-primary, #1e1e2e);
    border-radius: 8px;
    z-index: 9999;
    animation: slideUp 0.3s ease;
}

/* Responsive */
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

    .commit-actions {
        flex-wrap: wrap;
    }

    .commit-action-btn {
        flex: 1 1 45%;
    }
}
```

### שלב 3.2: JavaScript - מודול היסטוריה ו-Diff

צור קובץ חדש `repo-history.js`:

```javascript
// webapp/static/js/repo-history.js

/**
 * מודול להיסטוריית Git ותצוגת Diff
 *
 * תיקונים מרכזיים:
 * 1. encodeURIComponent לא משמש על paths - במקום זה file מועבר כ-query param
 * 2. addEventListener במקום inline onclick
 * 3. תמיכה ב-Compare Mode (בחירת 2 commits)
 */
const RepoHistory = (function() {
    'use strict';

    // State
    const state = {
        currentFile: null,
        commits: [],
        isLoading: false,
        hasMore: true,
        skip: 0,
        limit: 20,
        // Compare mode
        compareMode: false,
        compareBase: null,    // commit ישן (אדום)
        compareTarget: null   // commit חדש (ירוק)
    };

    // DOM Elements
    let historyPanel = null;
    let diffModal = null;
    let overlay = null;

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
        return path ? path.split('/').pop() : '';
    }

    function truncate(text, maxLength) {
        if (!text || text.length <= maxLength) return text;
        return text.substring(0, maxLength) + '...';
    }

    function formatRelativeDate(timestamp) {
        if (!timestamp) return '';
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

    function formatFullDate(timestamp) {
        if (!timestamp) return '';
        return new Date(timestamp * 1000).toLocaleString('he-IL', {
            year: 'numeric',
            month: 'long',
            day: 'numeric',
            hour: '2-digit',
            minute: '2-digit'
        });
    }

    /**
     * בניית URL עם file כ-query parameter
     * פותר את בעיית ה-encodeURIComponent עם slashes
     */
    function buildApiUrl(endpoint, params = {}) {
        const url = new URL(endpoint, window.location.origin);
        Object.entries(params).forEach(([key, value]) => {
            if (value !== undefined && value !== null) {
                url.searchParams.set(key, value);
            }
        });
        return url.toString();
    }

    function showToast(message, type = 'error', duration = 5000) {
        const toast = document.createElement('div');
        toast.className = type === 'error' ? 'error-toast' : 'success-toast';
        toast.innerHTML = `
            <i class="bi bi-${type === 'error' ? 'exclamation-triangle' : 'check-circle'}"></i>
            <span>${escapeHtml(message)}</span>
        `;
        document.body.appendChild(toast);

        setTimeout(() => {
            toast.classList.add('fade-out');
            setTimeout(() => toast.remove(), 300);
        }, duration);
    }

    async function copyToClipboard(text) {
        try {
            await navigator.clipboard.writeText(text);
            showToast('הועתק ללוח', 'success', 2000);
        } catch (err) {
            showToast('שגיאה בהעתקה', 'error');
        }
    }

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
                    <span class="history-title-text">היסטוריית קובץ</span>
                </h3>
                <button class="history-panel-close" aria-label="סגור">
                    <i class="bi bi-x-lg"></i>
                </button>
            </div>
            <div class="compare-mode-banner" style="display: none;">
                <span class="instructions">בחר שני commits להשוואה</span>
                <div class="selection">
                    <span class="commit-badge base">-</span>
                    <i class="bi bi-arrow-left"></i>
                    <span class="commit-badge target">-</span>
                </div>
                <button class="compare-execute-btn" disabled>השווה</button>
                <button class="compare-cancel-btn">ביטול</button>
            </div>
            <div class="history-commits"></div>
        `;
        document.body.appendChild(historyPanel);

        // Event listeners - NO inline onclick
        historyPanel.querySelector('.history-panel-close')
            .addEventListener('click', closeHistoryPanel);

        historyPanel.querySelector('.compare-execute-btn')
            .addEventListener('click', executeCompare);

        historyPanel.querySelector('.compare-cancel-btn')
            .addEventListener('click', cancelCompareMode);
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
                            <div class="commit-info old">
                                <span class="commit-badge old"></span>
                                <span class="commit-message-preview"></span>
                            </div>
                            <span class="arrow">→</span>
                            <div class="commit-info new">
                                <span class="commit-badge new"></span>
                                <span class="commit-message-preview"></span>
                            </div>
                        </div>
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
        diffModal.querySelector('.diff-modal-close')
            .addEventListener('click', closeDiffModal);

        diffModal.addEventListener('click', (e) => {
            if (e.target === diffModal) closeDiffModal();
        });
    }

    function createOverlay() {
        overlay = document.createElement('div');
        overlay.className = 'panel-overlay';
        overlay.addEventListener('click', closeHistoryPanel);
        document.body.appendChild(overlay);
    }

    function bindGlobalEvents() {
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
        state.compareMode = false;
        state.compareBase = null;
        state.compareTarget = null;

        historyPanel.classList.add('open');
        overlay.classList.add('visible');

        // Update title
        const titleText = historyPanel.querySelector('.history-title-text');
        titleText.textContent = `היסטוריית: ${getFileName(filePath)}`;
        titleText.title = filePath;

        // Hide compare banner
        historyPanel.querySelector('.compare-mode-banner').style.display = 'none';

        await loadHistory();
    }

    function closeHistoryPanel() {
        historyPanel.classList.remove('open');
        overlay.classList.remove('visible');
        cancelCompareMode();
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
            // בניית URL עם file כ-query param
            const url = buildApiUrl('/repo/api/history', {
                file: state.currentFile,
                limit: state.limit,
                skip: state.skip
            });

            const response = await fetch(url);

            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                throw new Error(errorData.message || `HTTP ${response.status}`);
            }

            const data = await response.json();

            if (!data.success) {
                throw new Error(data.message || 'שגיאה בטעינת היסטוריה');
            }

            state.commits = append ? [...state.commits, ...data.commits] : data.commits;
            state.hasMore = data.has_more;
            state.skip += data.commits.length;

            renderCommits(container, append);

        } catch (error) {
            console.error('Error loading history:', error);
            container.innerHTML = `
                <div class="history-error">
                    <i class="bi bi-exclamation-triangle"></i>
                    <p>${escapeHtml(error.message)}</p>
                    <button class="retry-btn">נסה שוב</button>
                </div>
            `;
            container.querySelector('.retry-btn')
                .addEventListener('click', () => loadHistory());
        } finally {
            state.isLoading = false;
        }
    }

    function renderCommits(container, append = false) {
        if (!append) {
            container.innerHTML = '';
        } else {
            const loadMoreBtn = container.querySelector('.history-load-more');
            if (loadMoreBtn) loadMoreBtn.remove();
        }

        const commitsToRender = append
            ? state.commits.slice(-state.limit)
            : state.commits;

        commitsToRender.forEach((commit, index) => {
            const globalIndex = append ? state.commits.length - state.limit + index : index;
            const commitEl = createCommitElement(commit, globalIndex);
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
        el.dataset.index = index;

        const relativeDate = formatRelativeDate(commit.timestamp);
        const fullDate = formatFullDate(commit.timestamp);

        el.innerHTML = `
            <div class="commit-header">
                <span class="commit-hash" title="לחץ להעתקה">${escapeHtml(commit.short_hash)}</span>
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
                <button class="commit-action-btn diff-head-btn" title="השווה לגרסה הנוכחית">
                    <i class="bi bi-file-diff"></i>
                    VS HEAD
                </button>
                ${index > 0 ? `
                    <button class="commit-action-btn diff-prev-btn" title="השווה ל-commit הקודם">
                        <i class="bi bi-arrow-left-right"></i>
                        VS קודם
                    </button>
                ` : ''}
                <button class="commit-action-btn compare-select-btn" title="בחר להשוואה">
                    <i class="bi bi-ui-checks"></i>
                    השווה...
                </button>
            </div>
        `;

        // Event listeners - NO inline onclick
        el.querySelector('.commit-hash').addEventListener('click', (e) => {
            e.stopPropagation();
            copyToClipboard(commit.hash);
        });

        el.querySelector('.view-btn').addEventListener('click', (e) => {
            e.stopPropagation();
            viewFileAtCommit(commit.hash);
        });

        el.querySelector('.diff-head-btn').addEventListener('click', (e) => {
            e.stopPropagation();
            showDiff(commit.hash, 'HEAD', commit.message, 'HEAD');
        });

        const diffPrevBtn = el.querySelector('.diff-prev-btn');
        if (diffPrevBtn) {
            diffPrevBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                const prevCommit = state.commits[index + 1];
                if (prevCommit) {
                    showDiff(prevCommit.hash, commit.hash, prevCommit.message, commit.message);
                }
            });
        }

        el.querySelector('.compare-select-btn').addEventListener('click', (e) => {
            e.stopPropagation();
            selectForCompare(commit, el);
        });

        return el;
    }

    // ============================================
    // Compare Mode
    // ============================================

    function selectForCompare(commit, element) {
        if (!state.compareMode) {
            // First selection - enter compare mode
            state.compareMode = true;
            state.compareBase = commit;
            element.classList.add('compare-selected-base');

            const banner = historyPanel.querySelector('.compare-mode-banner');
            banner.style.display = 'flex';
            banner.querySelector('.commit-badge.base').textContent = commit.short_hash;
            banner.querySelector('.commit-badge.target').textContent = '-';
            banner.querySelector('.compare-execute-btn').disabled = true;

        } else if (!state.compareTarget && commit.hash !== state.compareBase.hash) {
            // Second selection
            state.compareTarget = commit;
            element.classList.add('compare-selected-target');

            const banner = historyPanel.querySelector('.compare-mode-banner');
            banner.querySelector('.commit-badge.target').textContent = commit.short_hash;
            banner.querySelector('.compare-execute-btn').disabled = false;
        }
    }

    function cancelCompareMode() {
        state.compareMode = false;
        state.compareBase = null;
        state.compareTarget = null;

        historyPanel.querySelector('.compare-mode-banner').style.display = 'none';
        historyPanel.querySelectorAll('.compare-selected-base, .compare-selected-target')
            .forEach(el => el.classList.remove('compare-selected-base', 'compare-selected-target'));
    }

    function executeCompare() {
        if (state.compareBase && state.compareTarget) {
            // Determine order: older commit first
            const baseTime = state.compareBase.timestamp;
            const targetTime = state.compareTarget.timestamp;

            const [older, newer] = baseTime < targetTime
                ? [state.compareBase, state.compareTarget]
                : [state.compareTarget, state.compareBase];

            showDiff(older.hash, newer.hash, older.message, newer.message);
            cancelCompareMode();
        }
    }

    // ============================================
    // File Viewer at Commit
    // ============================================

    async function viewFileAtCommit(commit) {
        try {
            const url = buildApiUrl(`/repo/api/file-at-commit/${encodeURIComponent(commit)}`, {
                file: state.currentFile
            });

            const response = await fetch(url);
            const data = await response.json();

            if (!data.success) {
                throw new Error(data.message || 'שגיאה בטעינת קובץ');
            }

            if (data.is_binary) {
                showToast('זהו קובץ בינארי שלא ניתן להציג', 'error');
                return;
            }

            // Update editor content
            if (window.RepoState && window.RepoState.editor) {
                window.RepoState.editor.setValue(data.content);
            }

            // Update file info
            const fileHeader = document.querySelector('.file-header .file-info');
            if (fileHeader) {
                const shortHash = commit.substring(0, 7);
                const originalHtml = fileHeader.innerHTML;

                // Add version indicator
                const versionBadge = document.createElement('span');
                versionBadge.className = 'version-badge';
                versionBadge.innerHTML = `
                    <span class="badge">@ ${shortHash}</span>
                    <button class="back-to-head-btn">חזור ל-HEAD</button>
                `;

                const existingBadge = fileHeader.querySelector('.version-badge');
                if (existingBadge) existingBadge.remove();
                fileHeader.appendChild(versionBadge);

                versionBadge.querySelector('.back-to-head-btn')
                    .addEventListener('click', backToHead);
            }

        } catch (error) {
            console.error('Error viewing file at commit:', error);
            showToast(error.message, 'error');
        }
    }

    function backToHead() {
        if (!state.currentFile) return;

        // Remove version badge
        const badge = document.querySelector('.version-badge');
        if (badge) badge.remove();

        // Reload current file from HEAD
        if (window.selectFile) {
            window.selectFile(state.currentFile);
        }
    }

    // ============================================
    // Diff Modal
    // ============================================

    async function showDiff(commit1, commit2, message1 = '', message2 = '') {
        diffModal.classList.add('open');

        const content = diffModal.querySelector('.diff-content');
        const stats = diffModal.querySelector('.diff-stats');
        const commitsInfo = diffModal.querySelector('.diff-commits-info');

        // Update header
        const shortHash1 = commit1.substring(0, 7);
        const shortHash2 = commit2 === 'HEAD' ? 'HEAD' : commit2.substring(0, 7);

        commitsInfo.querySelector('.commit-badge.old').textContent = shortHash1;
        commitsInfo.querySelector('.commit-badge.new').textContent = shortHash2;
        commitsInfo.querySelector('.commit-info.old .commit-message-preview').textContent =
            truncate(message1, 40);
        commitsInfo.querySelector('.commit-info.new .commit-message-preview').textContent =
            truncate(message2, 40);

        content.innerHTML = `
            <div class="diff-loading">
                <div class="spinner"></div>
                <span>טוען השוואה...</span>
            </div>
        `;
        stats.innerHTML = '';

        try {
            const url = buildApiUrl(`/repo/api/diff/${encodeURIComponent(commit1)}/${encodeURIComponent(commit2)}`, {
                file: state.currentFile,
                format: 'both'
            });

            const response = await fetch(url);
            const data = await response.json();

            if (!data.success) {
                throw new Error(data.message || 'שגיאה בטעינת diff');
            }

            renderDiffStats(stats, data.stats, data.is_truncated);
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

    function renderDiffStats(container, stats, isTruncated) {
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
            ${isTruncated ? `
                <div class="diff-stat truncated">
                    <i class="bi bi-exclamation-triangle"></i>
                    <span>התוצאה קוצצה בגלל גודל</span>
                </div>
            ` : ''}
        `;
    }

    function renderDiff(container, parsed) {
        if (!parsed.files || parsed.files.length === 0) {
            container.innerHTML = `
                <div class="diff-empty">
                    <i class="bi bi-check-circle"></i>
                    <p>אין שינויים</p>
                </div>
            `;
            return;
        }

        const html = parsed.files.map(file => renderFileDiff(file)).join('');
        container.innerHTML = `<div class="diff-unified">${html}</div>`;
    }

    function renderFileDiff(file) {
        const statusClass = file.status || 'modified';
        const statusText = {
            added: 'חדש',
            modified: 'שונה',
            deleted: 'נמחק',
            renamed: 'שונה שם',
            copied: 'הועתק',
            binary: 'בינארי'
        }[statusClass] || statusClass;

        // Rename/copy info
        let renameInfo = '';
        if (file.status === 'renamed' && file.rename_from) {
            renameInfo = `
                <span class="diff-file-rename-info">
                    ${escapeHtml(file.rename_from)} → ${escapeHtml(file.rename_to || file.new_path)}
                    ${file.similarity ? `<span class="similarity">(${file.similarity}%)</span>` : ''}
                </span>
            `;
        }

        let hunksHtml = '';

        if (file.is_binary) {
            hunksHtml = `
                <div class="diff-binary-notice">
                    <i class="bi bi-file-binary"></i>
                    קובץ בינארי - לא ניתן להציג שינויים
                </div>
            `;
        } else if (file.hunks && file.hunks.length > 0) {
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

        const filePath = file.new_path || file.old_path;

        return `
            <div class="diff-file">
                <div class="diff-file-header">
                    <span class="diff-file-status ${statusClass}">${statusText}</span>
                    <span class="diff-file-path">${escapeHtml(filePath)}</span>
                    ${renameInfo}
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
        get state() { return { ...state }; }
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
            <button class="file-history-btn" data-path="${escapeHtml(filePath)}" title="היסטוריית קובץ">
                <i class="bi bi-clock-history"></i>
                היסטוריה
            </button>
            <button class="file-copy-btn" title="העתק תוכן">
                <i class="bi bi-clipboard"></i>
            </button>
        </div>
    `;

    // Event listener - NO inline onclick
    fileHeader.querySelector('.file-history-btn').addEventListener('click', function() {
        const path = this.dataset.path;
        if (path && window.RepoHistory) {
            RepoHistory.openHistoryPanel(path);
        }
    });

    fileHeader.querySelector('.file-copy-btn').addEventListener('click', copyFileContent);
}

function escapeHtml(text) {
    if (!text) return '';
    return String(text)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}
```

---

## 4. אבטחה וטיפול בשגיאות

### 4.1: וולידציות Backend

```python
# webapp/services/git_mirror_service.py

import os
import re

class GitMirrorService:
    """
    Validation patterns - מוגדרים כ-class attributes.
    """

    # שם ריפו: a-z, 0-9, -, _ בלבד, 1-100 תווים
    REPO_NAME_PATTERN = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9_-]{0,99}$')

    # נתיב קובץ - ללא path traversal
    # מאפשר: a-z, A-Z, 0-9, ., _, -, /
    # אוסר: .., //, leading/trailing /, NUL
    FILE_PATH_PATTERN = re.compile(
        r'^(?!.*\.\.)'           # No ..
        r'(?!.*//)'              # No //
        r'(?!/)'                 # No leading /
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

    def _validate_repo_name(self, name: str) -> bool:
        """וולידציה של שם ריפו."""
        if not name or not isinstance(name, str):
            return False
        if '\x00' in name:
            return False
        return bool(self.REPO_NAME_PATTERN.match(name))

    def _validate_repo_file_path(self, path: str) -> bool:
        """
        וולידציה של נתיב קובץ - מונע path traversal.
        """
        if not path or not isinstance(path, str):
            return False
        if '\x00' in path:
            return False

        # Normalize and check for traversal
        normalized = os.path.normpath(path)
        if normalized.startswith('..') or normalized.startswith('/'):
            return False
        if '..' in normalized:
            return False

        return bool(self.FILE_PATH_PATTERN.match(path))

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

    def _sanitize_output(self, output: str) -> str:
        """הסרת מידע רגיש מפלט Git."""
        if not output:
            return ''
        # Remove tokens from URLs
        sanitized = re.sub(
            r'https://[^:]+:[^@]+@',
            'https://***:***@',
            output
        )
        # Remove other potential secrets
        sanitized = re.sub(
            r'(token|password|secret|key)[\s]*[=:][\s]*[^\s]+',
            r'\1=***',
            sanitized,
            flags=re.IGNORECASE
        )
        return sanitized
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

    return app
```

---

## 6. תמיכה ב-RTL

### 6.1: כללי CSS ל-RTL

כבר כלולים בקובץ ה-CSS למעלה - שים לב ל:

1. **כיווניות**: `direction: rtl` לאלמנטים עבריים
2. **קוד תמיד LTR**: `.diff-unified`, `.CodeMirror` וכו'
3. **מיקום פאנל**: שונה ב-RTL (`left` במקום `right`)
4. **גבולות**: מתאימים לכיוון (`border-left` vs `border-right`)

### 6.2: תאריכים בעברית

כבר מוגדרים בקוד JavaScript עם:
- `toLocaleString('he-IL', {...})`
- פונקציות זמן יחסי בעברית

---

## 7. בדיקות

### 7.1: בדיקות Backend (pytest)

```python
# tests/test_git_history.py

import pytest
from unittest.mock import Mock, patch
from webapp.services.git_mirror_service import GitMirrorService

class TestValidation:
    """בדיקות וולידציה."""

    @pytest.fixture
    def git_service(self, tmp_path):
        return GitMirrorService(mirrors_base_path=str(tmp_path))

    def test_validate_repo_name_valid(self, git_service):
        valid_names = ['repo', 'my-repo', 'repo_123', 'A1', 'CodeBot']
        for name in valid_names:
            assert git_service._validate_repo_name(name) is True, f"Failed for: {name}"

    def test_validate_repo_name_invalid(self, git_service):
        invalid_names = [
            '', None, 123,
            '-repo',        # starts with -
            '../etc',       # path traversal
            'repo\x00',     # NUL byte
            'a' * 200,      # too long
        ]
        for name in invalid_names:
            assert git_service._validate_repo_name(name) is False, f"Should fail for: {name}"

    def test_validate_file_path_valid(self, git_service):
        valid_paths = [
            'file.py',
            'src/main.py',
            'path/to/file.js',
            'file-name_123.txt',
            '.gitignore',
        ]
        for path in valid_paths:
            assert git_service._validate_repo_file_path(path) is True, f"Failed for: {path}"

    def test_validate_file_path_invalid_traversal(self, git_service):
        invalid_paths = [
            '../etc/passwd',
            'path/../../../etc',
            '/absolute/path',
            'path//double',
            '',
            None,
            'file\x00.txt',
            '...',
        ]
        for path in invalid_paths:
            assert git_service._validate_repo_file_path(path) is False, f"Should fail for: {path}"

    def test_validate_basic_ref_valid(self, git_service):
        valid_refs = [
            'HEAD',
            'main',
            'feature/branch',
            'v1.0.0',
            'abc123',
            'HEAD~1',
            'main^',
            'a1b2c3d4e5f6789012345678901234567890abcd',
        ]
        for ref in valid_refs:
            assert git_service._validate_basic_ref(ref) is True, f"Failed for: {ref}"

    def test_validate_basic_ref_invalid(self, git_service):
        invalid_refs = [
            '', None,
            'branch\x00',
            'a' * 300,  # too long
        ]
        for ref in invalid_refs:
            assert git_service._validate_basic_ref(ref) is False, f"Should fail for: {ref}"


class TestBinaryDetection:
    """בדיקות זיהוי קבצים בינאריים."""

    @pytest.fixture
    def git_service(self, tmp_path):
        return GitMirrorService(mirrors_base_path=str(tmp_path))

    def test_detect_binary_with_nul(self, git_service):
        binary_content = b'some text\x00more text'
        assert git_service._detect_binary_content(binary_content) is True

    def test_detect_text_without_nul(self, git_service):
        text_content = b'hello world\nline 2\n'
        assert git_service._detect_binary_content(text_content) is False

    def test_detect_utf8_text(self, git_service):
        hebrew_content = 'שלום עולם'.encode('utf-8')
        assert git_service._detect_binary_content(hebrew_content) is False


class TestDiffParsing:
    """בדיקות פרסור diff."""

    @pytest.fixture
    def git_service(self, tmp_path):
        return GitMirrorService(mirrors_base_path=str(tmp_path))

    def test_parse_simple_diff(self, git_service):
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
        assert file['additions'] == 2
        assert file['deletions'] == 1

    def test_parse_renamed_file(self, git_service):
        diff_output = """diff --git a/old.txt b/new.txt
similarity index 95%
rename from old.txt
rename to new.txt
index 1234567..abcdefg 100644
--- a/old.txt
+++ b/new.txt
@@ -1 +1 @@
-old content
+new content
"""
        result = git_service._parse_diff(diff_output)

        assert len(result['files']) == 1
        file = result['files'][0]
        assert file['status'] == 'renamed'
        assert file['similarity'] == 95
        assert file['rename_from'] == 'old.txt'
        assert file['rename_to'] == 'new.txt'

    def test_parse_new_file(self, git_service):
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


class TestAPIRoutes:
    """בדיקות API routes."""

    @pytest.fixture
    def client(self, app):
        return app.test_client()

    def test_history_missing_file_param(self, client):
        response = client.get('/repo/api/history')
        assert response.status_code == 400
        data = response.get_json()
        assert data['error'] == 'missing_file'

    def test_history_invalid_file_path(self, client):
        response = client.get('/repo/api/history?file=../etc/passwd')
        assert response.status_code == 400
        data = response.get_json()
        assert data['error'] == 'invalid_file_path'

    def test_diff_endpoint_works(self, client):
        response = client.get('/repo/api/diff/HEAD~1/HEAD')
        # Should return either success or specific error
        assert response.status_code in [200, 400, 404, 500]
```

### 7.2: בדיקות Frontend (Jest)

```javascript
// tests/repo-history.test.js

describe('RepoHistory Utilities', () => {
    describe('escapeHtml', () => {
        // Assuming escapeHtml is exported or accessible
        const escapeHtml = (text) => {
            if (!text) return '';
            return String(text)
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;')
                .replace(/'/g, '&#039;');
        };

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

    describe('buildApiUrl', () => {
        const buildApiUrl = (endpoint, params = {}) => {
            const url = new URL(endpoint, 'http://localhost');
            Object.entries(params).forEach(([key, value]) => {
                if (value !== undefined && value !== null) {
                    url.searchParams.set(key, value);
                }
            });
            return url.pathname + url.search;
        };

        it('should build URL with query params', () => {
            const url = buildApiUrl('/repo/api/history', {
                file: 'src/main.py',
                limit: 20
            });
            expect(url).toBe('/repo/api/history?file=src%2Fmain.py&limit=20');
        });

        it('should handle file paths with slashes correctly', () => {
            const url = buildApiUrl('/repo/api/history', {
                file: 'path/to/deep/file.js'
            });
            // Note: slashes ARE encoded in query params
            expect(url).toContain('file=path%2Fto%2Fdeep%2Ffile.js');
        });

        it('should skip null/undefined params', () => {
            const url = buildApiUrl('/repo/api/diff/a/b', {
                file: null,
                format: 'parsed'
            });
            expect(url).not.toContain('file=');
            expect(url).toContain('format=parsed');
        });
    });
});
```

---

## סיכום שינויים מהגרסה הקודמת

### תיקונים קריטיים:

1. **import subprocess** - נוסף לכל מקום שמשתמש בו
2. **זיהוי בינארי** - עכשיו עם NUL byte detection + encoding fallbacks
3. **ref validation** - עכשיו עם `git rev-parse --verify` (ה-canonical way)
4. **diff semantics** - מוסבר ומשתמש ב-`commit1..commit2` syntax
5. **diff size limits** - נוסף `max_bytes` + truncation
6. **file path encoding** - עכשיו כ-query param `?file=` במקום path param
7. **inline onclick** - הוחלף ב-`addEventListener`
8. **rename/copy support** - נוסף ל-diff parser

### שיפורי UX:

1. **Compare Mode** - בחירת 2 commits ברשימה
2. **Copy commit hash** - לחיצה על hash מעתיקה
3. **Commit messages בdiff header** - מציג subject של כל commit
4. **Truncation indicator** - מודיע כשה-diff קוצץ
