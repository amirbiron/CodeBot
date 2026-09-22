# מדריך מימוש: תמיכה במספר ריפויים בדפדפן הקוד

> **רמת מורכבות:** בינונית  
> **זמן משוער:** יום עבודה מרוכז  
> **תלויות:** אין תלויות חיצוניות חדשות

---

## 📋 תוכן עניינים

1. [סקירת הארכיטקטורה הנוכחית](#סקירת-הארכיטקטורה-הנוכחית)
2. [מה כבר מוכן](#מה-כבר-מוכן)
3. [שלב 1: Backend API](#שלב-1-backend-api)
4. [שלב 2: Frontend JavaScript](#שלב-2-frontend-javascript)
5. [שלב 3: UI Templates](#שלב-3-ui-templates)
6. [שלב 4: CSS](#שלב-4-css)
7. [בדיקות](#בדיקות)
8. [Checklist למימוש](#checklist-למימוש)

---

## סקירת הארכיטקטורה הנוכחית

### קבצים רלוונטיים

```
webapp/
├── routes/
│   └── repo_browser.py      # Backend routes (Flask)
├── templates/repo/
│   ├── base_repo.html       # Template בסיס
│   └── index.html           # דף ראשי
├── static/
│   ├── js/repo-browser.js   # Frontend logic
│   └── css/repo-browser.css # Styles

services/
└── git_mirror_service.py    # Git service (כבר תומך multi-repo!)

database/
├── repository.py            # save_selected_repo, get_selected_repo
└── manager.py               # Facade
```

### הבעיה הנוכחית

כל המערכת hardcoded ל-`"CodeBot"`:

```python
# repo_browser.py
DEFAULT_REPO_NAME = "CodeBot"
repo_name = "CodeBot"  # מופיע ~15 פעמים
```

```javascript
// repo-browser.js
const CONFIG = {
    repoName: 'CodeBot',  // קשיח
    ...
};
```

---

## מה כבר מוכן

### ✅ GitMirrorService - תומך מלא במספר ריפויים

```python
# כל הפונקציות מקבלות repo_name כפרמטר:
service.init_mirror(repo_url, repo_name)
service.get_file_content(repo_name, file_path)
service.get_file_history(repo_name, file_path, ...)
service.get_diff(repo_name, commit1, commit2, ...)
```

### ✅ MongoDB - מאונדקס נכון

```python
# repo_files collection
{"repo_name": "CodeBot", "path": "src/main.py", ...}
{"repo_name": "OtherRepo", "path": "src/main.py", ...}

# repo_metadata collection
{"repo_name": "CodeBot", "total_files": 500, ...}
{"repo_name": "OtherRepo", "total_files": 200, ...}
```

### ✅ Database - פונקציות לבחירת ריפו

```python
# database/repository.py - כבר קיים!
def save_selected_repo(self, user_id: int, repo_name: str) -> bool
def get_selected_repo(self, user_id: int) -> Optional[str]
```

---

## שלב 1: Backend API

### 1.1 הוספת API לרשימת ריפויים

**קובץ:** `webapp/routes/repo_browser.py`

```python
@repo_bp.route('/api/repos')
def api_list_repos():
    """
    API לקבלת רשימת כל הריפויים הזמינים
    
    Returns:
        [{"name": "CodeBot", "total_files": 500, "last_sync": "..."}, ...]
    """
    try:
        db = get_db()
        
        # שליפת כל הריפויים מ-metadata
        repos = list(db.repo_metadata.find(
            {},
            {
                "repo_name": 1,
                "total_files": 1,
                "last_sync_time": 1,
                "default_branch": 1,
                "sync_status": 1,
                "_id": 0
            }
        ).sort("repo_name", 1))
        
        # המרה לפורמט אחיד
        result = []
        for repo in repos:
            result.append({
                "name": repo.get("repo_name"),
                "total_files": repo.get("total_files", 0),
                "last_sync": repo.get("last_sync_time"),
                "default_branch": repo.get("default_branch", "main"),
                "status": repo.get("sync_status", "unknown")
            })
        
        return jsonify(result)
        
    except Exception as e:
        logger.exception(f"List repos error: {e}")
        return jsonify({"error": "Failed to list repos"}), 500
```

### 1.2 הוספת פונקציית עזר לשליפת ריפו נבחר

**קובץ:** `webapp/routes/repo_browser.py`

```python
# בראש הקובץ - הוסף import
from flask import session

# הוסף פונקציית עזר
def get_current_repo() -> str:
    """
    שליפת הריפו הנוכחי לפי סדר עדיפויות:
    1. Query parameter (?repo=X)
    2. Session
    3. Default (CodeBot)
    """
    # 1. Query parameter - עדיפות עליונה
    repo = request.args.get('repo', '').strip()
    if repo:
        # וולידציה בסיסית
        if len(repo) <= 100 and repo.isalnum() or '-' in repo or '_' in repo:
            return repo
    
    # 2. Session
    repo = session.get('selected_repo', '').strip()
    if repo:
        return repo
    
    # 3. Default
    return DEFAULT_REPO_NAME


@repo_bp.route('/api/select-repo', methods=['POST'])
def api_select_repo():
    """
    API לבחירת ריפו (שמירה ב-session)
    
    Body: {"repo": "RepoName"}
    """
    try:
        data = request.get_json() or {}
        repo_name = data.get('repo', '').strip()
        
        if not repo_name:
            return jsonify({"error": "Missing repo name"}), 400
        
        # בדיקה שהריפו קיים
        db = get_db()
        exists = db.repo_metadata.find_one({"repo_name": repo_name})
        if not exists:
            return jsonify({"error": "Repo not found"}), 404
        
        # שמירה ב-session
        session['selected_repo'] = repo_name
        
        return jsonify({"success": True, "repo": repo_name})
        
    except Exception as e:
        logger.exception(f"Select repo error: {e}")
        return jsonify({"error": "Failed to select repo"}), 500
```

### 1.3 עדכון כל ה-Routes להשתמש ב-repo דינמי

**קובץ:** `webapp/routes/repo_browser.py`

שנה כל מופע של `repo_name = "CodeBot"` ל:

```python
# לפני:
repo_name = "CodeBot"

# אחרי:
repo_name = get_current_repo()
```

**רשימת פונקציות לעדכון:**

| פונקציה | שורה (בערך) | שינוי |
|---------|-------------|-------|
| `repo_index()` | 62 | `repo_name = get_current_repo()` |
| `api_tree()` | 118 | `repo_name = get_current_repo()` |
| `api_get_file()` | 217 | `repo_name = get_current_repo()` |
| `api_search()` | 605 | `repo_name = get_current_repo()` |
| `api_file_types()` | 652 | `repo_name = get_current_repo()` |
| `api_stats()` | 681 | `repo_name = get_current_repo()` |

**דוגמה מלאה - `api_tree`:**

```python
@repo_bp.route('/api/tree')
def api_tree():
    """API לקבלת עץ הקבצים"""
    db = get_db()
    repo_name = get_current_repo()  # <-- שינוי
    path = request.args.get('path', '')
    types_param = request.args.get('types', '').strip()
    
    # ... שאר הקוד נשאר זהה ...
```

### 1.4 עדכון repo_index להעביר repo ל-template

```python
@repo_bp.route('/')
def repo_index():
    """דף ראשי של דפדפן הקוד"""
    try:
        db = get_db()
        git_service = get_mirror_service()
        
        repo_name = get_current_repo()  # <-- שינוי
        
        # ... קוד קיים ...
        
        # שליפת רשימת ריפויים זמינים
        available_repos = list(db.repo_metadata.find(
            {},
            {"repo_name": 1, "_id": 0}
        ).sort("repo_name", 1))
        available_repos = [r["repo_name"] for r in available_repos]
        
        return render_template(
            'repo/index.html',
            repo_name=repo_name,
            available_repos=available_repos,  # <-- חדש
            metadata=metadata,
            mirror_info=mirror_info
        )
    except Exception as e:
        # ...
```

---

## שלב 2: Frontend JavaScript

### 2.1 עדכון CONFIG להיות דינמי

**קובץ:** `webapp/static/js/repo-browser.js`

```javascript
// ========================================
// Configuration
// ========================================

const CONFIG = {
    apiBase: '/repo/api',
    maxRecentFiles: 5,
    searchDebounceMs: 300,
    modeMap: {
        'python': 'python',
        'javascript': 'javascript',
        // ... שאר המיפוי
    }
};

// ========================================
// State - הוספת currentRepo
// ========================================

let state = {
    currentRepo: null,  // <-- חדש: יאותחל מ-HTML או localStorage
    currentFile: null,
    treeData: null,
    editor: null,
    // ... שאר ה-state
};

// ========================================
// Repo Selection
// ========================================

/**
 * אתחול הריפו הנבחר
 * עדיפות: 1. URL param  2. localStorage  3. HTML default
 */
function initCurrentRepo() {
    // 1. URL parameter
    const urlParams = new URLSearchParams(window.location.search);
    const urlRepo = urlParams.get('repo');
    if (urlRepo) {
        state.currentRepo = urlRepo;
        saveRepoPreference(urlRepo);
        return;
    }
    
    // 2. localStorage
    const savedRepo = localStorage.getItem('selectedRepo');
    if (savedRepo) {
        state.currentRepo = savedRepo;
        return;
    }
    
    // 3. HTML default (מועבר מ-Jinja)
    const repoNameEl = document.querySelector('.repo-name');
    if (repoNameEl) {
        const match = repoNameEl.textContent.trim();
        if (match) {
            state.currentRepo = match;
            return;
        }
    }
    
    // 4. Fallback
    state.currentRepo = 'CodeBot';
}

/**
 * שמירת העדפת ריפו
 */
function saveRepoPreference(repoName) {
    try {
        localStorage.setItem('selectedRepo', repoName);
    } catch (e) {
        console.warn('Failed to save repo preference:', e);
    }
}

/**
 * החלפת ריפו
 */
async function switchRepo(repoName) {
    if (repoName === state.currentRepo) return;
    
    try {
        // עדכון ב-server (session)
        const response = await fetch(`${CONFIG.apiBase}/select-repo`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ repo: repoName })
        });
        
        if (!response.ok) {
            throw new Error('Failed to switch repo');
        }
        
        // עדכון local state
        state.currentRepo = repoName;
        saveRepoPreference(repoName);
        
        // Reset state
        state.currentFile = null;
        state.expandedFolders.clear();
        state.selectedTypes.clear();
        
        // עדכון UI
        updateRepoSelector(repoName);
        
        // טעינה מחדש של עץ הקבצים
        await initTree();
        
        // איפוס תצוגת הקוד
        showWelcomeScreen();
        
        // עדכון URL
        updateUrlWithRepo(repoName);
        
        showToast(`Switched to ${repoName}`);
        
    } catch (error) {
        console.error('Failed to switch repo:', error);
        showToast('Failed to switch repository');
    }
}

/**
 * עדכון URL עם הריפו הנוכחי
 */
function updateUrlWithRepo(repoName) {
    const url = new URL(window.location.href);
    url.searchParams.set('repo', repoName);
    history.replaceState(null, '', url.toString());
}

/**
 * עדכון UI של בורר הריפויים
 */
function updateRepoSelector(repoName) {
    const selector = document.getElementById('repo-selector');
    if (selector) {
        selector.value = repoName;
    }
    
    const repoNameDisplay = document.querySelector('.repo-name-text');
    if (repoNameDisplay) {
        repoNameDisplay.textContent = repoName;
    }
}

/**
 * הצגת מסך פתיחה
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
```

### 2.2 עדכון פונקציית initTree

```javascript
async function initTree() {
    const treeContainer = document.getElementById('file-tree');
    if (!treeContainer) return;

    // ביטול בקשה קודמת
    if (state.treeAbortController) {
        state.treeAbortController.abort();
    }
    state.treeAbortController = new AbortController();
    const signal = state.treeAbortController.signal;

    try {
        // בניית URL עם repo parameter
        let url = `${CONFIG.apiBase}/tree`;
        const params = new URLSearchParams();
        
        // הוספת repo
        if (state.currentRepo) {
            params.set('repo', state.currentRepo);
        }
        
        // הוספת filter
        const filterParam = getFilterQueryParam();
        if (filterParam) {
            params.set('types', filterParam);
        }
        
        if (params.toString()) {
            url += '?' + params.toString();
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

### 2.3 עדכון כל קריאות ה-API

**Helper function:**

```javascript
/**
 * בניית URL עם repo parameter
 */
function buildApiUrl(endpoint, params = {}) {
    const url = new URL(`${CONFIG.apiBase}/${endpoint}`, window.location.origin);
    
    // תמיד הוסף repo
    if (state.currentRepo) {
        url.searchParams.set('repo', state.currentRepo);
    }
    
    // הוסף פרמטרים נוספים
    for (const [key, value] of Object.entries(params)) {
        if (value !== undefined && value !== null && value !== '') {
            url.searchParams.set(key, value);
        }
    }
    
    return url.toString();
}
```

**עדכון selectFile:**

```javascript
async function selectFile(path, element) {
    // ... קוד קיים ...
    
    try {
        // שינוי: שימוש ב-buildApiUrl
        const url = buildApiUrl(`file/${encodeURIComponent(path)}`);
        const response = await fetch(url);
        const data = await response.json();
        // ...
    }
    // ...
}
```

**עדכון performRepoSearch:**

```javascript
async function performRepoSearch(query) {
    // ... קוד קיים ...
    
    try {
        const url = buildApiUrl('search', {
            q: clean,
            type: 'content'
        });
        const response = await fetch(url, { signal: controller.signal });
        // ...
    }
    // ...
}
```

### 2.4 עדכון אתחול

```javascript
document.addEventListener('DOMContentLoaded', () => {
    // חדש: אתחול ריפו קודם לכל
    initCurrentRepo();
    
    // קיים
    initFileTypeFilter();
    initTree();
    initSearch();
    initResizer();
    initKeyboardShortcuts();
    initMobileSidebar();
    loadRecentFiles();
    applyInitialNavigationFromUrl();
    
    // חדש: אתחול בורר ריפויים
    initRepoSelector();
});

/**
 * אתחול בורר ריפויים
 */
function initRepoSelector() {
    const selector = document.getElementById('repo-selector');
    if (!selector) return;
    
    selector.addEventListener('change', (e) => {
        const newRepo = e.target.value;
        if (newRepo) {
            switchRepo(newRepo);
        }
    });
}
```

---

## שלב 3: UI Templates

### 3.1 הוספת בורר ריפויים ל-base_repo.html

**קובץ:** `webapp/templates/repo/base_repo.html`

מצא את הקטע:
```html
<div class="repo-info">
    <span class="repo-name">
        <i class="bi bi-github"></i>
        {{ repo_name }}
    </span>
```

והחלף ב:
```html
<div class="repo-info">
    <!-- בורר ריפויים -->
    <div class="repo-selector-wrapper">
        <i class="bi bi-github"></i>
        {% if available_repos and available_repos|length > 1 %}
        <select id="repo-selector" class="repo-selector" title="בחר ריפו">
            {% for repo in available_repos %}
            <option value="{{ repo }}" {% if repo == repo_name %}selected{% endif %}>
                {{ repo }}
            </option>
            {% endfor %}
        </select>
        {% else %}
        <span class="repo-name-text">{{ repo_name }}</span>
        {% endif %}
    </div>
```

### 3.2 עדכון קישור GitHub

מצא:
```html
<a class="btn-icon" id="github-link" href="#" target="_blank" title="View on GitHub">
```

הקישור יעודכן דינמית ב-JS (כבר קיים), אבל צריך לעדכן את `updateBreadcrumbs`:

```javascript
// בתוך updateBreadcrumbs - עדכון קישור GitHub
const githubLink = document.getElementById('github-link');
if (githubLink && state.currentRepo) {
    const encodedPath = path.split('/').map(segment => encodeURIComponent(segment)).join('/');
    // שימוש ב-repo הנוכחי במקום hardcoded
    githubLink.href = `https://github.com/amirbiron/${state.currentRepo}/blob/main/${encodedPath}`;
}
```

---

## שלב 4: CSS

### 4.1 סגנונות לבורר ריפויים

**קובץ:** `webapp/static/css/repo-browser.css`

הוסף בסוף הקובץ:

```css
/* ========================================
   Repo Selector
   ======================================== */

.repo-selector-wrapper {
    display: flex;
    align-items: center;
    gap: 8px;
}

.repo-selector {
    background: var(--bg-tertiary, #2a2a3e);
    border: 1px solid var(--border-color, #3a3a4e);
    border-radius: 6px;
    color: var(--text-primary, #fff);
    padding: 6px 28px 6px 10px;
    font-size: 14px;
    font-weight: 500;
    cursor: pointer;
    appearance: none;
    -webkit-appearance: none;
    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' fill='%23888' viewBox='0 0 16 16'%3E%3Cpath d='M7.247 11.14L2.451 5.658C1.885 5.013 2.345 4 3.204 4h9.592a1 1 0 0 1 .753 1.659l-4.796 5.48a1 1 0 0 1-1.506 0z'/%3E%3C/svg%3E");
    background-repeat: no-repeat;
    background-position: right 8px center;
    min-width: 120px;
    max-width: 200px;
    transition: border-color 0.2s, box-shadow 0.2s;
}

.repo-selector:hover {
    border-color: var(--accent-primary, #7c3aed);
}

.repo-selector:focus {
    outline: none;
    border-color: var(--accent-primary, #7c3aed);
    box-shadow: 0 0 0 3px rgba(124, 58, 237, 0.2);
}

.repo-selector option {
    background: var(--bg-secondary, #1e1e2e);
    color: var(--text-primary, #fff);
    padding: 8px;
}

.repo-name-text {
    font-weight: 500;
    color: var(--text-primary, #fff);
}

/* Mobile adjustments */
@media (max-width: 768px) {
    .repo-selector {
        min-width: 100px;
        max-width: 150px;
        font-size: 13px;
        padding: 5px 24px 5px 8px;
    }
}
```

---

## בדיקות

### בדיקות ידניות

1. **בחירת ריפו:**
   - [ ] בורר ריפויים מופיע כשיש יותר מריפו אחד
   - [ ] החלפת ריפו מעדכנת את עץ הקבצים
   - [ ] הבחירה נשמרת ב-localStorage
   - [ ] רענון הדף שומר על הבחירה

2. **ניווט:**
   - [ ] פתיחת קובץ עובדת בכל ריפו
   - [ ] חיפוש עובד בריפו הנבחר
   - [ ] היסטוריית קובץ עובדת
   - [ ] קישור GitHub מצביע לריפו הנכון

3. **URL:**
   - [ ] `?repo=X` עובד בכניסה ישירה
   - [ ] URL מתעדכן בהחלפת ריפו

### בדיקות אוטומטיות (pytest)

```python
# tests/test_repo_browser_multi.py

import pytest
from webapp.app import create_app

@pytest.fixture
def client():
    app = create_app(testing=True)
    with app.test_client() as client:
        yield client

def test_api_repos_list(client):
    """בדיקת API רשימת ריפויים"""
    response = client.get('/repo/api/repos')
    assert response.status_code == 200
    data = response.get_json()
    assert isinstance(data, list)

def test_api_tree_with_repo_param(client):
    """בדיקת API עץ עם פרמטר repo"""
    response = client.get('/repo/api/tree?repo=CodeBot')
    assert response.status_code == 200

def test_api_select_repo(client):
    """בדיקת API בחירת ריפו"""
    response = client.post(
        '/repo/api/select-repo',
        json={'repo': 'CodeBot'},
        content_type='application/json'
    )
    assert response.status_code == 200
    data = response.get_json()
    assert data.get('success') is True

def test_api_select_nonexistent_repo(client):
    """בדיקת API בחירת ריפו שלא קיים"""
    response = client.post(
        '/repo/api/select-repo',
        json={'repo': 'NonExistentRepo'},
        content_type='application/json'
    )
    assert response.status_code == 404
```

---

## Checklist למימוש

### Backend (repo_browser.py)

- [ ] הוספת `from flask import session`
- [ ] הוספת פונקציה `get_current_repo()`
- [ ] הוספת route `api_list_repos()`
- [ ] הוספת route `api_select_repo()`
- [ ] עדכון `repo_index()` - שימוש ב-`get_current_repo()`
- [ ] עדכון `repo_index()` - העברת `available_repos` ל-template
- [ ] עדכון `api_tree()` - שימוש ב-`get_current_repo()`
- [ ] עדכון `api_get_file()` - שימוש ב-`get_current_repo()`
- [ ] עדכון `get_file_history()` - שימוש ב-`get_current_repo()` (אם רלוונטי)
- [ ] עדכון `api_search()` - שימוש ב-`get_current_repo()`
- [ ] עדכון `api_file_types()` - שימוש ב-`get_current_repo()`
- [ ] עדכון `api_stats()` - שימוש ב-`get_current_repo()`

### Frontend (repo-browser.js)

- [ ] הוספת `state.currentRepo`
- [ ] הוספת `initCurrentRepo()`
- [ ] הוספת `saveRepoPreference()`
- [ ] הוספת `switchRepo()`
- [ ] הוספת `updateRepoSelector()`
- [ ] הוספת `buildApiUrl()` helper
- [ ] הוספת `initRepoSelector()`
- [ ] עדכון `initTree()` - הוספת repo param
- [ ] עדכון `toggleFolder()` - הוספת repo param
- [ ] עדכון `selectFile()` - שימוש ב-`buildApiUrl`
- [ ] עדכון `performRepoSearch()` - שימוש ב-`buildApiUrl`
- [ ] עדכון `loadFileTypes()` - הוספת repo param
- [ ] עדכון `updateBreadcrumbs()` - קישור GitHub דינמי
- [ ] עדכון `DOMContentLoaded` - קריאה ל-`initCurrentRepo()`

### Templates

- [ ] עדכון `base_repo.html` - הוספת בורר ריפויים
- [ ] עדכון `base_repo.html` - העברת `available_repos` ל-select

### CSS

- [ ] הוספת סגנונות `.repo-selector-wrapper`
- [ ] הוספת סגנונות `.repo-selector`
- [ ] הוספת סגנונות responsive

### בדיקות

- [ ] בדיקת החלפת ריפו ידנית
- [ ] בדיקת שמירה ב-localStorage
- [ ] בדיקת URL params
- [ ] כתיבת unit tests

---

## הערות חשובות

1. **Session vs localStorage:**
   - Session משמש לצד השרת (Python)
   - localStorage משמש לצד הלקוח (JS)
   - שניהם צריכים להיות מסונכרנים

2. **Backwards Compatibility:**
   - אם אין `?repo=X` ואין בחירה שמורה, ברירת המחדל היא `CodeBot`
   - URLs ישנים ימשיכו לעבוד

3. **ביצועים:**
   - בהחלפת ריפו, נטען רק עץ השורש (lazy loading)
   - Recent files נשמרים לכל ריפו בנפרד (אופציונלי)

4. **אבטחה:**
   - וולידציה של `repo_name` בצד השרת
   - בדיקה שהריפו קיים לפני החלפה
