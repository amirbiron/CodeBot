# מדריך מימוש: תמיכה במספר ריפויים בדפדפן הקוד

## סקירת המצב הקיים

### מה כבר עובד
1. **GitMirrorService** - כבר מקבל `repo_name` כפרמטר בכל הפונקציות
2. **MongoDB** - הנתונים כבר מאונדקסים לפי `repo_name` ב-collections:
   - `repo_files` - קבצי הריפו
   - `repo_metadata` - מטא-דאטה של הריפו
3. **פונקציות בסיס קיימות** ב-`database/repository.py`:
   - `save_selected_repo(user_id, repo_name)` - שורה 1705
   - `get_selected_repo(user_id)` - שורה 1720

---

## שלב 1: Backend - עדכון repo_browser.py

### 1.1 הוספת פונקציית עזר לקבלת repo_name דינמי

**קובץ:** `webapp/routes/repo_browser.py`

**הוסף אחרי שורה 30 (אחרי `get_git_service`):**

```python
def get_current_repo_name() -> str:
    """
    מחזיר את שם הריפו הנוכחי לפי סדר עדיפויות:
    1. Query parameter 'repo' מה-URL
    2. Session (אם המשתמש מחובר)
    3. ברירת מחדל: CodeBot
    """
    from flask import session
    from flask_login import current_user
    from database.repository import RepositoryManager

    # 1. מ-query parameter
    repo_from_query = request.args.get('repo', '').strip()
    if repo_from_query:
        # ולידציה בסיסית של שם ריפו
        if re.match(r'^[a-zA-Z0-9][a-zA-Z0-9_-]{0,99}$', repo_from_query):
            return repo_from_query

    # 2. מה-session (למשתמש מחובר)
    if hasattr(current_user, 'is_authenticated') and current_user.is_authenticated:
        try:
            repo_manager = RepositoryManager()
            saved_repo = repo_manager.get_selected_repo(current_user.id)
            if saved_repo:
                return saved_repo
        except Exception as e:
            logger.warning(f"Could not get saved repo: {e}")

    # 3. ברירת מחדל
    return DEFAULT_REPO_NAME
```

### 1.2 הוספת API לרשימת ריפויים זמינים

**הוסף בסוף הקובץ (לפני סגירת הקובץ):**

```python
@repo_bp.route('/api/repos')
def api_list_repos():
    """
    API לקבלת רשימת כל הריפויים הזמינים.

    Returns:
        רשימת ריפויים עם מטא-דאטה בסיסי
    """
    db = get_db()

    try:
        repos = list(db.repo_metadata.find(
            {},  # כל הריפויים
            {
                "repo_name": 1,
                "repo_url": 1,
                "total_files": 1,
                "last_sync_time": 1,
                "sync_status": 1,
                "_id": 0
            }
        ).sort("repo_name", 1))

        return jsonify({
            "success": True,
            "repos": repos,
            "current": get_current_repo_name()
        })
    except Exception as e:
        logger.exception(f"List repos API error: {e}")
        return jsonify({
            "success": False,
            "error": "Failed to fetch repos",
            "repos": []
        }), 500


@repo_bp.route('/api/select-repo', methods=['POST'])
def api_select_repo():
    """
    API לשמירת הריפו הנבחר למשתמש מחובר.
    """
    from flask_login import current_user
    from database.repository import RepositoryManager

    if not hasattr(current_user, 'is_authenticated') or not current_user.is_authenticated:
        return jsonify({
            "success": False,
            "error": "Authentication required"
        }), 401

    data = request.get_json() or {}
    repo_name = data.get('repo_name', '').strip()

    if not repo_name or not re.match(r'^[a-zA-Z0-9][a-zA-Z0-9_-]{0,99}$', repo_name):
        return jsonify({
            "success": False,
            "error": "Invalid repo name"
        }), 400

    # בדיקה שהריפו קיים
    db = get_db()
    if not db.repo_metadata.find_one({"repo_name": repo_name}):
        return jsonify({
            "success": False,
            "error": "Repo not found"
        }), 404

    try:
        repo_manager = RepositoryManager()
        success = repo_manager.save_selected_repo(current_user.id, repo_name)

        return jsonify({
            "success": success,
            "repo_name": repo_name
        })
    except Exception as e:
        logger.exception(f"Select repo error: {e}")
        return jsonify({
            "success": False,
            "error": "Failed to save selection"
        }), 500
```

### 1.3 עדכון כל ה-routes להשתמש ב-repo דינמי

**החלף את כל המופעים של `repo_name = "CodeBot"` ב-`repo_name = get_current_repo_name()`**

| שורה | מקורי | חדש |
|------|-------|-----|
| 62 | `repo_name = "CodeBot"` | `repo_name = get_current_repo_name()` |
| 100 | `repo_name="CodeBot"` | `repo_name=get_current_repo_name()` |
| 118 | `repo_name = "CodeBot"` | `repo_name = get_current_repo_name()` |
| 217 | `repo_name = "CodeBot"` | `repo_name = get_current_repo_name()` |
| 294 | `repo_name=DEFAULT_REPO_NAME` | `repo_name=get_current_repo_name()` |
| 361 | `repo_name=DEFAULT_REPO_NAME` | `repo_name=get_current_repo_name()` |
| 434 | `repo_name=DEFAULT_REPO_NAME` | `repo_name=get_current_repo_name()` |
| 486 | `repo_name=DEFAULT_REPO_NAME` | `repo_name=get_current_repo_name()` |
| 557 | `repo_name=DEFAULT_REPO_NAME` | `repo_name=get_current_repo_name()` |
| 605 | `repo_name = "CodeBot"` | `repo_name = get_current_repo_name()` |
| 652 | `repo_name = "CodeBot"` | `repo_name = get_current_repo_name()` |
| 681 | `repo_name = "CodeBot"` | `repo_name = get_current_repo_name()` |

---

## שלב 2: Frontend - עדכון repo-browser.js

### 2.1 עדכון CONFIG לתמיכה בריפו דינמי

**קובץ:** `webapp/static/js/repo-browser.js`

**החלף את ה-CONFIG (שורות 16-36):**

```javascript
// ========================================
// Configuration
// ========================================

const CONFIG = {
    // repoName יוגדר דינמית מה-HTML או מ-localStorage
    get repoName() {
        // 1. מ-HTML (הוזרק מה-template)
        const fromHtml = document.getElementById('current-repo-name')?.dataset?.repo;
        if (fromHtml) return fromHtml;

        // 2. מ-localStorage
        const fromStorage = localStorage.getItem('selectedRepo');
        if (fromStorage) return fromStorage;

        // 3. ברירת מחדל
        return 'CodeBot';
    },
    apiBase: '/repo/api',
    maxRecentFiles: 5,
    searchDebounceMs: 300,
    modeMap: {
        'python': 'python',
        'javascript': 'javascript',
        'typescript': 'javascript',
        'html': 'htmlmixed',
        'css': 'css',
        'scss': 'css',
        'json': 'javascript',
        'yaml': 'yaml',
        'markdown': 'markdown',
        'shell': 'shell',
        'bash': 'shell',
        'sql': 'sql',
        'text': 'null'
    }
};

// Current repo state (can change during session)
let currentRepo = CONFIG.repoName;
```

### 2.2 הוספת פונקציות לניהול ריפויים

**הוסף אחרי הגדרת ה-state (אחרי שורה 59):**

```javascript
// ========================================
// Repo Management
// ========================================

/**
 * טוען את רשימת הריפויים הזמינים
 */
async function loadAvailableRepos() {
    try {
        const response = await fetch(`${CONFIG.apiBase}/repos`);
        const data = await response.json();

        if (data.success && data.repos) {
            renderRepoSelector(data.repos, data.current);
        }
    } catch (error) {
        console.error('Failed to load repos:', error);
    }
}

/**
 * מרנדר את בורר הריפויים
 */
function renderRepoSelector(repos, currentRepoName) {
    const container = document.getElementById('repo-selector');
    if (!container) return;

    if (repos.length <= 1) {
        // אם יש רק ריפו אחד, אין צורך בבורר
        container.style.display = 'none';
        return;
    }

    container.innerHTML = `
        <div class="repo-dropdown">
            <button class="repo-dropdown-toggle" id="repo-dropdown-toggle">
                <i class="bi bi-github"></i>
                <span class="current-repo-name">${escapeHtml(currentRepoName)}</span>
                <i class="bi bi-chevron-down"></i>
            </button>
            <div class="repo-dropdown-menu" id="repo-dropdown-menu">
                ${repos.map(repo => `
                    <div class="repo-dropdown-item ${repo.repo_name === currentRepoName ? 'active' : ''}"
                         data-repo="${escapeHtml(repo.repo_name)}">
                        <div class="repo-item-name">
                            <i class="bi bi-folder2"></i>
                            ${escapeHtml(repo.repo_name)}
                        </div>
                        <div class="repo-item-stats">
                            <span>${repo.total_files || 0} files</span>
                        </div>
                    </div>
                `).join('')}
            </div>
        </div>
    `;

    // Event listeners
    const toggle = container.querySelector('#repo-dropdown-toggle');
    const menu = container.querySelector('#repo-dropdown-menu');

    toggle?.addEventListener('click', (e) => {
        e.stopPropagation();
        menu.classList.toggle('open');
    });

    // סגירה בלחיצה מחוץ ל-dropdown
    document.addEventListener('click', () => {
        menu?.classList.remove('open');
    });

    // בחירת ריפו
    container.querySelectorAll('.repo-dropdown-item').forEach(item => {
        item.addEventListener('click', async () => {
            const repoName = item.dataset.repo;
            if (repoName && repoName !== currentRepo) {
                await switchRepo(repoName);
            }
            menu?.classList.remove('open');
        });
    });
}

/**
 * מחליף לריפו אחר
 */
async function switchRepo(repoName) {
    if (!repoName || repoName === currentRepo) return;

    // שמירה ב-localStorage
    localStorage.setItem('selectedRepo', repoName);
    currentRepo = repoName;

    // שמירה בשרת (למשתמש מחובר)
    try {
        await fetch(`${CONFIG.apiBase}/select-repo`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ repo_name: repoName })
        });
    } catch (e) {
        // לא קריטי - localStorage מספיק
        console.warn('Could not save repo selection to server:', e);
    }

    // עדכון UI
    updateRepoDisplay(repoName);

    // איפוס state
    state.currentFile = null;
    state.expandedFolders.clear();
    state.selectedTypes.clear();

    // טעינה מחדש של העץ
    await initTree();
    await loadFileTypes();

    // הצגת מסך פתיחה
    showWelcomeScreen();

    showToast(`Switched to ${repoName}`);
}

/**
 * עדכון תצוגת שם הריפו ב-UI
 */
function updateRepoDisplay(repoName) {
    // עדכון בכותרת
    const repoNameEl = document.querySelector('.repo-name');
    if (repoNameEl) {
        repoNameEl.innerHTML = `<i class="bi bi-github"></i> ${escapeHtml(repoName)}`;
    }

    // עדכון ב-dropdown
    const currentNameEl = document.querySelector('.current-repo-name');
    if (currentNameEl) {
        currentNameEl.textContent = repoName;
    }

    // עדכון ה-active item
    document.querySelectorAll('.repo-dropdown-item').forEach(item => {
        item.classList.toggle('active', item.dataset.repo === repoName);
    });
}

/**
 * מציג מסך פתיחה
 */
function showWelcomeScreen() {
    const welcome = document.getElementById('welcome-screen');
    const wrapper = document.getElementById('code-editor-wrapper');
    const header = document.getElementById('code-header');
    const footer = document.getElementById('code-footer');

    if (welcome) welcome.style.display = 'block';
    if (wrapper) wrapper.style.display = 'none';
    if (header) header.style.display = 'none';
    if (footer) footer.style.display = 'none';
}

/**
 * מחזיר פרמטר repo לקריאות API
 */
function getRepoParam() {
    return `repo=${encodeURIComponent(currentRepo)}`;
}
```

### 2.3 עדכון כל קריאות ה-API להעביר repo

**עדכן את הפונקציות הבאות:**

#### initTree (שורה 133)
```javascript
async function initTree() {
    const treeContainer = document.getElementById('file-tree');
    if (!treeContainer) return;

    if (state.treeAbortController) {
        state.treeAbortController.abort();
    }
    state.treeAbortController = new AbortController();
    const signal = state.treeAbortController.signal;

    try {
        // Build URL with repo and filter parameters
        let url = `${CONFIG.apiBase}/tree?${getRepoParam()}`;
        const filterParam = getFilterQueryParam();
        if (filterParam) {
            url += `&types=${encodeURIComponent(filterParam)}`;
        }

        const response = await fetch(url, { signal });
        const data = await response.json();
        state.treeData = data;
        renderTree(treeContainer, data);
    } catch (error) {
        if (error.name === 'AbortError') return;
        console.error('Failed to load tree:', error);
        treeContainer.innerHTML = `
            <div class="error-message">
                <i class="bi bi-exclamation-triangle"></i>
                <span>Failed to load file tree</span>
            </div>
        `;
    }
}
```

#### toggleFolder (שורה 260)
```javascript
// בתוך toggleFolder, עדכן את ה-URL:
let url = `${CONFIG.apiBase}/tree?${getRepoParam()}&path=${encodeURIComponent(item.path)}`;
const filterParam = getFilterQueryParam();
if (filterParam) {
    url += `&types=${encodeURIComponent(filterParam)}`;
}
```

#### loadFileTypes (שורה 429)
```javascript
const response = await fetch(`${CONFIG.apiBase}/file-types?${getRepoParam()}`, { signal });
```

#### selectFile (שורה 658)
```javascript
const response = await fetch(`${CONFIG.apiBase}/file/${encodeURIComponent(path)}?${getRepoParam()}`);
```

#### performRepoSearch (שורה 1014)
```javascript
const response = await fetch(
    `${CONFIG.apiBase}/search?${getRepoParam()}&q=${encodeURIComponent(clean)}&type=content`,
    { signal: controller.signal }
);
```

### 2.4 עדכון Initialization

**עדכן את DOMContentLoaded (שורה 65):**

```javascript
document.addEventListener('DOMContentLoaded', () => {
    // טען ריפויים זמינים
    loadAvailableRepos();

    // המשך אתחול רגיל
    initFileTypeFilter();
    initTree();
    initSearch();
    initResizer();
    initKeyboardShortcuts();
    initMobileSidebar();
    loadRecentFiles();
    applyInitialNavigationFromUrl();
});
```

### 2.5 עדכון updateBreadcrumbs להציג שם ריפו

**עדכן את updateBreadcrumbs (שורה 911):**

```javascript
function updateBreadcrumbs(path) {
    const breadcrumb = document.getElementById('file-breadcrumb');
    const parts = path.split('/');

    if (breadcrumb) {
        // הוסף שם ריפו כקישור ראשון
        const repoLink = `<li class="breadcrumb-item"><a href="#" onclick="showWelcomeScreen(); return false;">${escapeHtml(currentRepo)}</a></li>`;

        const pathLinks = parts.map((part, index) => {
            const isLast = index === parts.length - 1;
            const partPath = parts.slice(0, index + 1).join('/');
            const safePart = escapeHtml(part);
            const safeJsPartPath = escapeJsStr(partPath);

            if (isLast) {
                return `<li class="breadcrumb-item active">${safePart}</li>`;
            }
            return `<li class="breadcrumb-item"><a href="#" onclick="navigateToFolder('${safeJsPartPath}')">${safePart}</a></li>`;
        }).join('');

        breadcrumb.innerHTML = repoLink + pathLinks;
    }

    // Update copy path button
    document.getElementById('copy-path').onclick = () => {
        navigator.clipboard.writeText(`${currentRepo}/${path}`);
        showToast('Path copied!');
    };

    // Update GitHub link dynamically based on repo
    const githubLink = document.getElementById('github-link');
    if (githubLink) {
        const encodedPath = path.split('/').map(segment => encodeURIComponent(segment)).join('/');
        // TODO: לשלוף את ה-repo_url מה-metadata
        githubLink.href = `https://github.com/amirbiron/${currentRepo}/blob/main/${encodedPath}`;
    }
}
```

---

## שלב 3: עדכון Template

### 3.1 הוספת בורר ריפויים ל-base_repo.html

**קובץ:** `webapp/templates/repo/base_repo.html`

**הוסף אחרי שורה 48 (אחרי search-shortcuts):**

```html
<!-- Repo Selector (will be populated by JS if multiple repos exist) -->
<div id="repo-selector" class="repo-selector"></div>
```

**הוסף לפני סגירת repo-info (שורה 59):**

```html
<!-- Hidden element to pass repo name to JS -->
<span id="current-repo-name" data-repo="{{ repo_name }}" style="display: none;"></span>
```

---

## שלב 4: CSS לבורר ריפויים

**קובץ:** `webapp/static/css/repo-browser.css`

**הוסף בסוף הקובץ:**

```css
/* ========================================
   Repo Selector Dropdown
   ======================================== */

.repo-selector {
    margin-right: 12px;
}

.repo-dropdown {
    position: relative;
}

.repo-dropdown-toggle {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 6px 12px;
    background: var(--bg-tertiary);
    border: 1px solid var(--border-color);
    border-radius: 6px;
    color: var(--text-primary);
    cursor: pointer;
    font-size: 14px;
    transition: all 0.2s ease;
}

.repo-dropdown-toggle:hover {
    background: var(--bg-hover);
    border-color: var(--accent-color);
}

.repo-dropdown-toggle .bi-chevron-down {
    font-size: 10px;
    transition: transform 0.2s ease;
}

.repo-dropdown-menu.open + .repo-dropdown-toggle .bi-chevron-down,
.repo-dropdown-toggle:focus + .repo-dropdown-menu .bi-chevron-down {
    transform: rotate(180deg);
}

.repo-dropdown-menu {
    position: absolute;
    top: calc(100% + 4px);
    left: 0;
    min-width: 220px;
    max-height: 300px;
    overflow-y: auto;
    background: var(--bg-secondary);
    border: 1px solid var(--border-color);
    border-radius: 8px;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
    z-index: 1000;
    opacity: 0;
    visibility: hidden;
    transform: translateY(-8px);
    transition: all 0.2s ease;
}

.repo-dropdown-menu.open {
    opacity: 1;
    visibility: visible;
    transform: translateY(0);
}

.repo-dropdown-item {
    display: flex;
    flex-direction: column;
    gap: 4px;
    padding: 10px 14px;
    cursor: pointer;
    transition: background 0.15s ease;
}

.repo-dropdown-item:hover {
    background: var(--bg-hover);
}

.repo-dropdown-item.active {
    background: var(--accent-color-alpha);
    border-right: 3px solid var(--accent-color);
}

.repo-item-name {
    display: flex;
    align-items: center;
    gap: 8px;
    font-weight: 500;
    color: var(--text-primary);
}

.repo-item-stats {
    font-size: 12px;
    color: var(--text-muted);
    padding-left: 24px;
}

/* Mobile adjustments */
@media (max-width: 768px) {
    .repo-selector {
        display: none; /* הסתר במובייל - יוצג בסיידבר */
    }

    .sidebar-header .repo-selector {
        display: block;
        margin: 8px 0;
    }
}
```

---

## שלב 5: בדיקות

### 5.1 בדיקות ידניות

1. **בדיקת טעינת רשימת ריפויים:**
   ```bash
   curl http://localhost:5000/repo/api/repos
   ```

2. **בדיקת טעינת עץ קבצים עם פרמטר repo:**
   ```bash
   curl "http://localhost:5000/repo/api/tree?repo=OtherRepo"
   ```

3. **בדיקת החלפת ריפו:**
   - פתח את דפדפן הקוד
   - בחר ריפו אחר מה-dropdown
   - ודא שהעץ נטען מחדש
   - רענן את הדף וודא שהבחירה נשמרה

### 5.2 בדיקות אוטומטיות (pytest)

```python
# tests/test_repo_browser_multi.py

import pytest
from webapp.routes.repo_browser import get_current_repo_name

class TestMultiRepoSupport:

    def test_api_list_repos(self, client):
        """בדיקה שה-API מחזיר רשימת ריפויים"""
        response = client.get('/repo/api/repos')
        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True
        assert 'repos' in data
        assert isinstance(data['repos'], list)

    def test_tree_with_repo_param(self, client):
        """בדיקה שעץ הקבצים עובד עם פרמטר repo"""
        response = client.get('/repo/api/tree?repo=CodeBot')
        assert response.status_code == 200
        data = response.get_json()
        assert isinstance(data, list)

    def test_tree_invalid_repo(self, client):
        """בדיקה שריפו לא קיים מחזיר רשימה ריקה"""
        response = client.get('/repo/api/tree?repo=NonExistent')
        assert response.status_code == 200
        data = response.get_json()
        assert data == []  # אין קבצים לריפו שלא קיים

    def test_file_with_repo_param(self, client):
        """בדיקה שקריאת קובץ עובדת עם פרמטר repo"""
        response = client.get('/repo/api/file/README.md?repo=CodeBot')
        assert response.status_code in [200, 404]  # תלוי אם הקובץ קיים

    def test_select_repo_unauthenticated(self, client):
        """בדיקה שבחירת ריפו דורשת אותנטיקציה"""
        response = client.post('/repo/api/select-repo',
                               json={'repo_name': 'CodeBot'})
        assert response.status_code == 401
```

---

## סיכום השינויים

| קובץ | סוג שינוי | מורכבות |
|------|-----------|---------|
| `repo_browser.py` | הוספת `get_current_repo_name()` | קל |
| `repo_browser.py` | API חדשים (`/repos`, `/select-repo`) | בינוני |
| `repo_browser.py` | החלפת hardcoded repo (12 מקומות) | קל |
| `repo-browser.js` | CONFIG דינמי | קל |
| `repo-browser.js` | פונקציות ניהול ריפויים | בינוני |
| `repo-browser.js` | עדכון כל קריאות API (5 מקומות) | קל |
| `base_repo.html` | הוספת בורר ריפויים | קל |
| `repo-browser.css` | סגנונות ל-dropdown | קל |

**זמן מוערך:** 2-4 שעות עבודה

---

## שיקולים נוספים

### אבטחה
- כל שם ריפו עובר ולידציה עם regex
- משתמשים יכולים לראות רק ריפויים שקיימים ב-DB

### ביצועים
- שם הריפו נשמר ב-localStorage להפחתת בקשות לשרת
- ה-API `/repos` נקרא פעם אחת בטעינה ראשונית

### תאימות לאחור
- אם לא מועבר פרמטר `repo`, ברירת המחדל היא `CodeBot`
- קישורים ישנים ימשיכו לעבוד

### הרחבות עתידיות
- הוספת הרשאות גישה לריפויים ספציפיים
- תמיכה בסינכרון מריפויים חיצוניים נוספים
- הצגת סטטיסטיקות השוואתיות בין ריפויים
