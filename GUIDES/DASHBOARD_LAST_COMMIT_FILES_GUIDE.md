# 📊 מדריך: הצגת קבצים מהקומיט האחרון בדשבורד (Admin Only)

## 🎯 מטרה
להחליף את הבלוק "קבצים אחרונים" בדשבורד בבלוק חדש שמציג **קבצים שהשתנו בקומיט האחרון** של הריפו, **לאדמין בלבד**.

> **הערה:** הבלוק "קבצים אחרונים" מיותר כי כבר יש את אותו מידע ב-"פיד אחרון" (Activity Timeline).

---

## 🏗️ ארכיטקטורה

```
┌─────────────────────────────────────────────────────────────────┐
│                         Dashboard Route                          │
│                       (webapp/app.py)                            │
├─────────────────────────────────────────────────────────────────┤
│  1. בדיקת is_admin(user_id)                                     │
│  2. אם אדמין: שליפת last_commit_changes מ-GitMirrorService       │
│  3. העברת הנתונים ל-Template                                    │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    GitMirrorService                              │
│               (services/git_mirror_service.py)                   │
├─────────────────────────────────────────────────────────────────┤
│  get_last_commit_info(repo_name) → {                             │
│      sha, message, author, date,                                │
│      files: [{path, status, icon}]                               │
│  }                                                               │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                       MongoDB                                    │
├─────────────────────────────────────────────────────────────────┤
│  repo_metadata: {                                                │
│      repo_name, default_branch,                                  │
│      last_synced_sha, last_sync_time                            │
│  }                                                               │
└─────────────────────────────────────────────────────────────────┘
```

---

## 📁 קבצים לשינוי

| קובץ | שינוי |
|------|-------|
| `services/git_mirror_service.py` | הוספת `get_last_commit_info()` |
| `webapp/app.py` | עדכון `dashboard()` route |
| `webapp/templates/dashboard.html` | החלפת בלוק "קבצים אחרונים" |

---

## 🔧 שלב 1: הוספת פונקציה ל-GitMirrorService

### קובץ: `services/git_mirror_service.py`

הוסף את הפונקציה הבאה **בסוף הקלאס `GitMirrorService`** (לפני `# Singleton instance`):

```python
def get_last_commit_info(self, repo_name: str, ref: str = "HEAD") -> Optional[Dict[str, Any]]:
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
    
    # 1. קבלת פרטי הקומיט האחרון
    # פורמט: SHA|Author|Date|Subject
    result = self._run_git_command(
        ["git", "log", "-1", "--format=%H|%an|%aI|%s", ref],
        cwd=repo_path,
        timeout=10
    )
    
    if not result.success or not result.stdout.strip():
        return None
    
    parts = result.stdout.strip().split("|", 3)
    if len(parts) < 4:
        return None
    
    sha, author, date_str, message = parts
    
    # 2. קבלת רשימת קבצים שהשתנו בקומיט
    # הערה: עבור הקומיט הראשון (ללא parent), diff-tree עם ^! לא יעבוד.
    # נשתמש ב-show --name-status שעובד גם לקומיט יתום.
    files_result = self._run_git_command(
        ["git", "show", "--name-status", "--format=", sha],
        cwd=repo_path,
        timeout=30
    )
    
    files = []
    if files_result.success:
        for line in files_result.stdout.strip().split("\n"):
            if not line.strip():
                continue
            
            file_parts = line.split("\t", 1)
            if len(file_parts) < 2:
                continue
            
            status_code = file_parts[0].strip()
            file_path = file_parts[1].strip()
            
            # מיפוי סטטוס לאייקון ותיאור
            status_map = {
                "A": {"status": "added", "icon": "➕", "label": "נוסף"},
                "M": {"status": "modified", "icon": "✏️", "label": "עודכן"},
                "D": {"status": "deleted", "icon": "🗑️", "label": "נמחק"},
            }
            
            # R = Renamed (בדרך כלל R100, R095 וכו')
            if status_code.startswith("R"):
                status_info = {"status": "renamed", "icon": "📝", "label": "שונה שם"}
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
            
            files.append({
                "path": file_path,
                "name": PathLib(file_path).name,
                "status": status_info["status"],
                "status_icon": status_info["icon"],
                "status_label": status_info["label"],
                "file_icon": file_icon,
            })
    
    # הגבלת מספר הקבצים להצגה (מקסימום 10)
    max_files = 10
    total_files = len(files)
    truncated = total_files > max_files
    
    return {
        "sha": sha,
        "sha_short": sha[:7],
        "author": author,
        "date": date_str,
        "message": message,
        "files": files[:max_files],
        "total_files": total_files,
        "truncated": truncated,
    }
```

---

## 🔧 שלב 2: עדכון Dashboard Route

### קובץ: `webapp/app.py`

#### 2.1 הוספת import (אם לא קיים)

בתחילת הקובץ, ודא שקיים:

```python
from services.git_mirror_service import get_mirror_service
```

#### 2.2 עדכון פונקציית `dashboard()`

מצא את הפונקציה `dashboard()` (בערך שורה 9432) ועדכן אותה:

**לפני:**
```python
@app.route('/dashboard')
@login_required
def dashboard():
    """דשבורד עם סטטיסטיקות"""
    try:
        db = get_db()
        user_id = session['user_id']
        
        # ... קוד קיים ...
        
        return render_template('dashboard.html', 
                             user=session['user_data'],
                             stats=stats,
                             activity_timeline=activity_timeline,
                             push_card=push_card,
                             notes_snapshot=notes_snapshot,
                             bot_username=BOT_USERNAME_CLEAN)
```

**אחרי:**
```python
import os  # אם לא קיים בתחילת הקובץ

@app.route('/dashboard')
@login_required
def dashboard():
    """דשבורד עם סטטיסטיקות"""
    try:
        db = get_db()
        user_id = session['user_id']
        
        # בדיקה אם המשתמש אדמין
        user_is_admin = is_admin(user_id)
        
        # --- קוד קיים לסטטיסטיקות ---
        # שליפת סטטיסטיקות - רק קבצים פעילים
        active_query = {
            'user_id': user_id,
            'is_active': True
        }
        total_files = db.code_snippets.count_documents(active_query)
        
        # ... (שאר הקוד הקיים) ...
        
        # ========== חדש: קבצים מהקומיט האחרון (אדמין בלבד) ==========
        last_commit = None
        if user_is_admin:
            try:
                repo_name = os.getenv("REPO_NAME", "CodeBot")
                git_service = get_mirror_service()
                
                if git_service.mirror_exists(repo_name):
                    last_commit = git_service.get_last_commit_info(repo_name)
                    
                    # הוספת מידע נוסף מה-DB
                    if last_commit:
                        metadata = db.repo_metadata.find_one({"repo_name": repo_name})
                        if metadata:
                            last_commit["sync_time"] = metadata.get("last_sync_time")
                            last_commit["sync_status"] = metadata.get("sync_status", "unknown")
            except Exception as e:
                logger.warning(f"Failed to get last commit info: {e}")
                last_commit = None
        # ================================================================
        
        # עדכון ה-stats dict
        stats = {
            'total_files': total_files,
            'total_size': format_file_size(total_size),
            'top_languages': [
                {
                    'name': lang['_id'] or 'לא מוגדר',
                    'count': lang['count'],
                    'icon': get_language_icon(lang['_id'] or '')
                }
                for lang in top_languages
            ],
            'recent_files': recent_files  # נשמר לתאימות אחורה
        }
        
        activity_timeline = _build_activity_timeline(db, user_id, active_query)
        push_card = _build_push_card(db, user_id)
        notes_snapshot = _build_notes_snapshot(db, user_id)

        return render_template('dashboard.html', 
                             user=session['user_data'],
                             stats=stats,
                             activity_timeline=activity_timeline,
                             push_card=push_card,
                             notes_snapshot=notes_snapshot,
                             bot_username=BOT_USERNAME_CLEAN,
                             # חדש:
                             user_is_admin=user_is_admin,
                             last_commit=last_commit)
```

> **שים לב:** יש לעדכן גם את ה-fallback template בחלק ה-`except` להעביר `user_is_admin=False` ו-`last_commit=None`.

---

## 🔧 שלב 3: עדכון Template

### קובץ: `webapp/templates/dashboard.html`

#### 3.1 החלפת בלוק "קבצים אחרונים"

מצא את הבלוק (בערך שורות 69-106):

```html
<div class="glass-card">
    <h2 class="section-title">
        <i class="fas fa-clock"></i>
        קבצים אחרונים
    </h2>
    {% if stats.recent_files %}
    ...
    {% endif %}
</div>
```

**החלף אותו ב:**

```html
{% if user_is_admin and last_commit %}
{# === בלוק קומיט אחרון (אדמין בלבד) === #}
<div class="glass-card last-commit-card">
    <h2 class="section-title">
        <i class="fas fa-code-commit"></i>
        קומיט אחרון
    </h2>
    
    <div class="commit-header">
        <div class="commit-info">
            <div class="commit-sha">
                <code>{{ last_commit.sha_short }}</code>
            </div>
            <div class="commit-message" title="{{ last_commit.message }}">
                {{ last_commit.message[:80] }}{% if last_commit.message|length > 80 %}...{% endif %}
            </div>
            <div class="commit-meta">
                <span class="commit-author">
                    <i class="fas fa-user"></i> {{ last_commit.author }}
                </span>
                <span class="commit-date">
                    <i class="fas fa-clock"></i> {{ last_commit.date[:10] }}
                </span>
            </div>
        </div>
    </div>
    
    {% if last_commit.files %}
    <div class="changed-files-list">
        <div class="files-header">
            <span>קבצים שהשתנו</span>
            <span class="files-count badge">{{ last_commit.total_files }}</span>
        </div>
        {% for file in last_commit.files %}
        <div class="changed-file-item status-{{ file.status }}">
            <div class="file-info">
                <span class="file-icon">{{ file.file_icon }}</span>
                <span class="file-name" title="{{ file.path }}">{{ file.name }}</span>
            </div>
            <div class="file-status">
                <span class="status-icon" title="{{ file.status_label }}">{{ file.status_icon }}</span>
            </div>
        </div>
        {% endfor %}
        
        {% if last_commit.truncated %}
        <div class="more-files">
            <span>ועוד {{ last_commit.total_files - last_commit.files|length }} קבצים...</span>
        </div>
        {% endif %}
    </div>
    {% else %}
    <p class="no-changes">אין קבצים שהשתנו</p>
    {% endif %}
    
    <div class="commit-actions">
        <a href="/repo/" class="btn btn-secondary btn-icon">
            <i class="fas fa-folder-tree"></i>
            דפדפן קוד
        </a>
        {% if last_commit.sync_time %}
        <small class="sync-time">
            סונכרן: {{ last_commit.sync_time.strftime('%d/%m %H:%M') if last_commit.sync_time else 'לא ידוע' }}
        </small>
        {% endif %}
    </div>
</div>
{% else %}
{# === בלוק קבצים אחרונים (משתמשים רגילים) === #}
<div class="glass-card">
    <h2 class="section-title">
        <i class="fas fa-clock"></i>
        קבצים אחרונים
    </h2>
    {% if stats.recent_files %}
    <div class="recent-files-list">
        {% for file in stats.recent_files %}
        <div class="file-item">
            <div style="display: flex; align-items: center; gap: 1rem;">
                <span style="font-size: 1.5rem;">{{ file.icon }}</span>
                <div>
                    <div style="font-weight: 500;">{{ file.file_name }}</div>
                    <div style="font-size: 0.85rem; opacity: 0.7;">{{ file.created_at_formatted }}</div>
                </div>
            </div>
            <a href="/file/{{ file._id }}" class="btn btn-secondary" style="padding: 0.5rem 1rem;">
                <i class="fas fa-eye"></i>
            </a>
        </div>
        {% endfor %}
    </div>
    <div style="margin-top: 1.5rem;">
        <a href="/files" class="btn btn-primary btn-icon">
            <i class="fas fa-folder-open"></i>
            צפה בכל הקבצים
        </a>
    </div>
    {% else %}
    <p style="opacity: 0.7;">אין עדיין קבצים</p>
    <div style="margin-top: 1.5rem;">
        <a href="https://t.me/{{ bot_username }}" target="_blank" class="btn btn-primary btn-icon">
            <i class="fab fa-telegram"></i>
            התחל לשמור קבצים בבוט
        </a>
    </div>
    {% endif %}
</div>
{% endif %}
```

#### 3.2 הוספת CSS (בתוך בלוק `<style>`)

הוסף בסוף הבלוק `<style>` הקיים:

```css
/* === Last Commit Card (Admin Only) === */
.last-commit-card {
    border-right: 3px solid #10b981;
}

.commit-header {
    margin-bottom: 1.5rem;
    padding-bottom: 1rem;
    border-bottom: 1px solid rgba(255,255,255,0.1);
}

.commit-sha code {
    background: rgba(16, 185, 129, 0.2);
    padding: 0.25rem 0.5rem;
    border-radius: 6px;
    font-family: monospace;
    font-size: 0.9rem;
    color: #10b981;
}

.commit-message {
    font-weight: 600;
    margin: 0.75rem 0 0.5rem;
    line-height: 1.4;
}

.commit-meta {
    display: flex;
    gap: 1.5rem;
    font-size: 0.85rem;
    opacity: 0.75;
}

.commit-meta i {
    margin-left: 0.25rem;
}

.changed-files-list {
    margin-top: 1rem;
}

.files-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 0.75rem;
    font-weight: 500;
}

.changed-file-item {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 0.5rem 0.75rem;
    background: rgba(255,255,255,0.03);
    border-radius: 8px;
    margin-bottom: 0.35rem;
    border-right: 3px solid transparent;
}

.changed-file-item.status-added {
    border-right-color: #10b981;
}

.changed-file-item.status-modified {
    border-right-color: #f59e0b;
}

.changed-file-item.status-deleted {
    border-right-color: #ef4444;
    opacity: 0.7;
}

.changed-file-item.status-renamed {
    border-right-color: #8b5cf6;
}

.file-info {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    overflow: hidden;
}

.file-icon {
    font-size: 1.1rem;
}

.file-name {
    font-family: monospace;
    font-size: 0.85rem;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    max-width: 200px;
}

.status-icon {
    font-size: 0.9rem;
}

.more-files {
    text-align: center;
    padding: 0.5rem;
    opacity: 0.7;
    font-size: 0.85rem;
}

.commit-actions {
    margin-top: 1.5rem;
    display: flex;
    justify-content: space-between;
    align-items: center;
}

.sync-time {
    opacity: 0.6;
    font-size: 0.8rem;
}

.no-changes {
    opacity: 0.7;
    text-align: center;
    padding: 1rem;
}

/* Rose Pine Dawn overrides */
:root[data-theme="rose-pine-dawn"] .commit-sha code {
    background: rgba(86, 148, 159, 0.15);
    color: #286983;
}

:root[data-theme="rose-pine-dawn"] .last-commit-card {
    border-right-color: #56949f;
}

:root[data-theme="rose-pine-dawn"] .changed-file-item {
    background: rgba(255,255,255,0.4);
}

:root[data-theme="rose-pine-dawn"] .changed-file-item.status-added {
    border-right-color: #56949f;
}

:root[data-theme="rose-pine-dawn"] .changed-file-item.status-modified {
    border-right-color: #ea9d34;
}

:root[data-theme="rose-pine-dawn"] .changed-file-item.status-deleted {
    border-right-color: #b4637a;
}

:root[data-theme="rose-pine-dawn"] .changed-file-item.status-renamed {
    border-right-color: #907aa9;
}
```

---

## ✅ בדיקות

### 1. בדיקת Unit Test ל-GitMirrorService

צור קובץ `tests/test_git_mirror_last_commit.py`:

```python
"""Tests for GitMirrorService.get_last_commit_info()"""

import pytest
from unittest.mock import MagicMock, patch

from services.git_mirror_service import GitMirrorService


@pytest.fixture
def mock_service(tmp_path):
    """Create a GitMirrorService with mocked git commands."""
    service = GitMirrorService(base_path=str(tmp_path))
    return service


class TestGetLastCommitInfo:
    """Tests for get_last_commit_info method."""

    def test_returns_none_when_mirror_not_exists(self, mock_service):
        """Should return None if mirror doesn't exist."""
        result = mock_service.get_last_commit_info("nonexistent-repo")
        assert result is None

    def test_parses_commit_info_correctly(self, mock_service, tmp_path):
        """Should correctly parse git log output."""
        # Create fake mirror directory
        repo_path = tmp_path / "test-repo.git"
        repo_path.mkdir()

        # Mock git commands
        log_output = "abc123def456|John Doe|2025-01-17T10:30:00+00:00|feat: add new feature"
        show_output = "A\tsrc/new_file.py\nM\tsrc/existing.py\nD\told_file.py"

        def mock_run_git(cmd, cwd=None, timeout=60):
            result = MagicMock()
            result.success = True
            result.return_code = 0

            if "log" in cmd:
                result.stdout = log_output
            elif "show" in cmd:
                result.stdout = show_output
            else:
                result.stdout = ""

            result.stderr = ""
            return result

        mock_service._run_git_command = mock_run_git

        result = mock_service.get_last_commit_info("test-repo")

        assert result is not None
        assert result["sha"] == "abc123def456"
        assert result["sha_short"] == "abc123d"
        assert result["author"] == "John Doe"
        assert result["message"] == "feat: add new feature"
        assert len(result["files"]) == 3

        # Check file statuses
        files_by_path = {f["path"]: f for f in result["files"]}
        assert files_by_path["src/new_file.py"]["status"] == "added"
        assert files_by_path["src/existing.py"]["status"] == "modified"
        assert files_by_path["old_file.py"]["status"] == "deleted"

    def test_truncates_files_over_limit(self, mock_service, tmp_path):
        """Should truncate file list and set truncated flag."""
        repo_path = tmp_path / "test-repo.git"
        repo_path.mkdir()

        log_output = "abc123|Author|2025-01-17T10:30:00+00:00|Big commit"
        # Generate 15 files
        files = [f"M\tfile{i}.py" for i in range(15)]
        show_output = "\n".join(files)

        def mock_run_git(cmd, cwd=None, timeout=60):
            result = MagicMock()
            result.success = True
            result.return_code = 0
            result.stdout = log_output if "log" in cmd else show_output
            result.stderr = ""
            return result

        mock_service._run_git_command = mock_run_git

        result = mock_service.get_last_commit_info("test-repo")

        assert result["total_files"] == 15
        assert len(result["files"]) == 10  # max_files limit
        assert result["truncated"] is True
```

### 2. בדיקה ידנית

1. התחבר כאדמין לדשבורד
2. ודא שהבלוק "קומיט אחרון" מופיע
3. ודא שאייקוני הסטטוס נכונים
4. התחבר כמשתמש רגיל
5. ודא שהבלוק "קבצים אחרונים" המקורי מופיע

---

## 📌 הערות חשובות

1. **אבטחה:** הנתונים מוצגים רק לאדמין (`is_admin` check).

2. **Performance:** 
   - הפונקציה `get_last_commit_info` מריצה שתי פקודות git (log + show)
   - זמן ריצה צפוי: < 100ms
   - אפשר להוסיף caching אם צריך

3. **Fallback:** אם ה-mirror לא קיים או יש שגיאה, הדשבורד ממשיך לעבוד ומציג את הבלוק המקורי.

4. **Theme Support:** ה-CSS כולל תמיכה ב-Rose Pine Dawn theme.

---

## 🔄 משתני סביבה

וודא שהמשתנים הבאים מוגדרים:

| משתנה | תיאור | ברירת מחדל |
|--------|--------|-------------|
| `REPO_NAME` | שם הריפו | `CodeBot` |
| `REPO_MIRROR_PATH` | נתיב ל-mirror | `/var/data/repos` |
| `ADMIN_USER_IDS` | מזהי אדמינים (CSV) | - |

---

## 📋 Checklist

- [ ] הוספת `get_last_commit_info()` ל-`GitMirrorService`
- [ ] עדכון `dashboard()` route עם בדיקת admin ושליפת commit
- [ ] עדכון Template עם בלוק מותנה
- [ ] הוספת CSS לעיצוב הבלוק החדש
- [ ] כתיבת unit tests
- [ ] בדיקה ידנית (admin + non-admin)
- [ ] עדכון fallback ב-except block
