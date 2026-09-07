# מדריך מימוש תמיכה במספר ריפויים בדפדפן הקוד

## סקירה כללית

מדריך זה מתאר את כל השינויים הנדרשים להוספת תמיכה בצפייה במספר ריפויים בדפדפן הקוד (`/repo/`).

**החדשות הטובות:** התשתית כבר קיימת!
- `GitMirrorService` כבר מקבל `repo_name` כפרמטר בכל הפונקציות
- MongoDB מאורגן נכון עם אינדקסים על `repo_name`
- יש פונקציות `save_selected_repo` ו-`get_selected_repo` ב-DB

---

## שלב 1: Backend - עדכון `repo_browser.py`

### 1.1 הוספת API לרשימת ריפויים זמינים

```python
# הוסף לאחר הייבואים הקיימים
from flask import session

# הוסף API חדש לרשימת ריפויים
@repo_bp.route('/api/repos')
def api_list_repos():
    """
    API לקבלת רשימת ריפויים זמינים.
    
    Returns:
        רשימת ריפויים עם מטאדטה בסיסית
    """
    db = get_db()
    
    try:
        # שליפת כל הריפויים מ-repo_metadata
        repos = list(db.repo_metadata.find(
            {},
            {
                "repo_name": 1,
                "total_files": 1,
                "default_branch": 1,
                "last_sync_time": 1,
                "sync_status": 1
            }
        ).sort("repo_name", 1))
        
        result = []
        for repo in repos:
            result.append({
                "name": repo.get("repo_name", "Unknown"),
                "total_files": repo.get("total_files", 0),
                "default_branch": repo.get("default_branch", "main"),
                "last_sync": repo.get("last_sync_time"),
                "sync_status": repo.get("sync_status", "unknown")
            })
        
        return jsonify(result)
    except Exception as e:
        logger.exception(f"List repos API error: {e}")
        return jsonify({"error": "Internal server error"}), 500
```

### 1.2 פונקציית עזר לקבלת הריפו הנבחר

```python
def get_selected_repo_name() -> str:
    """
    קבלת שם הריפו הנבחר לפי סדר עדיפות:
    1. Query parameter (?repo=...)
    2. Session (selected_repo)
    3. ברירת מחדל: CodeBot
    """
    # 1. מ-query string
    repo_from_query = request.args.get('repo', '').strip()
    if repo_from_query:
        # שמירה ב-session לשימוש עתידי
        session['selected_repo'] = repo_from_query
        return repo_from_query
    
    # 2. מ-session
    repo_from_session = session.get('selected_repo', '').strip()
    if repo_from_session:
        return repo_from_session
    
    # 3. ברירת מחדל
    return DEFAULT_REPO_NAME
```

### 1.3 עדכון כל ה-Routes להשתמש בפונקציה

**עדכן את `repo_index()`:**

```python
@repo_bp.route('/')
def repo_index():
    """דף ראשי של דפדפן הקוד"""
    try:
        db = get_db()
        git_service = get_mirror_service()
        
        # שימוש בפונקציה הדינמית במקום hardcoded
        repo_name = get_selected_repo_name()
        
        # ... המשך הקוד ללא שינוי ...
```

**עדכן את `api_tree()`:**

```python
@repo_bp.route('/api/tree')
def api_tree():
    """API לקבלת עץ הקבצים"""
    db = get_db()
    
    # שימוש בפונקציה הדינמית
    repo_name = get_selected_repo_name()
    
    # ... המשך הקוד ללא שינוי ...
```

**עדכן את `api_get_file()`:**

```python
@repo_bp.route('/api/file/<path:file_path>')
def api_get_file(file_path: str):
    """API לקבלת תוכן קובץ"""
    db = get_db()
    git_service = get_mirror_service()
    
    # שימוש בפונקציה הדינמית
    repo_name = get_selected_repo_name()
    
    # ... המשך הקוד ללא שינוי ...
```

### 1.4 רשימת כל ה-Routes שצריך לעדכן

| Route | שורה | מה לשנות |
|-------|------|----------|
| `repo_index()` | 56-104 | `repo_name = "CodeBot"` → `repo_name = get_selected_repo_name()` |
| `api_tree()` | 107-209 | שורה 118 |
| `api_get_file()` | 212-246 | שורה 217 |
| `get_file_history()` | 253-326 | שורה 294 (DEFAULT_REPO_NAME) |
| `get_file_at_commit()` | 328-391 | שורה 360 |
| `get_diff()` | 394-468 | שורה 433 |
| `get_commit_info()` | 471-513 | שורה 485 |
| `api_search_history()` | 516-588 | שורה 557 |
| `api_search()` | 591-640 | שורה 605 |
| `api_file_types()` | 643-673 | שורה 652 |
| `api_stats()` | 676-695 | שורה 681 |

---

## שלב 2: Frontend - עדכון `repo-browser.js`

### 2.1 הוספת state לריפו הנבחר

```javascript
// עדכן את CONFIG (שורות 16-36)
const CONFIG = {
    // הסר את repoName הקשיח
    // repoName: 'CodeBot',  // <-- למחוק
    apiBase: '/repo/api',
    maxRecentFiles: 5,
    searchDebounceMs: 300,
    // ... שאר ההגדרות ...
};

// הוסף לאחר state (שורה 42)
let currentRepo = localStorage.getItem('selectedRepo') || 'CodeBot';
```

### 2.2 פונקציה לקבלת פרמטר הריפו

```javascript
// הוסף פונקציה חדשה
function getRepoParam() {
    return `repo=${encodeURIComponent(currentRepo)}`;
}

// פונקציה לבניית URL עם repo parameter
function buildApiUrl(endpoint, params = {}) {
    const url = new URL(`${CONFIG.apiBase}/${endpoint}`, window.location.origin);
    url.searchParams.set('repo', currentRepo);
    
    for (const [key, value] of Object.entries(params)) {
        if (value !== undefined && value !== null && value !== '') {
            url.searchParams.set(key, value);
        }
    }
    
    return url.toString();
}
```

### 2.3 עדכון פונקציות fetch להעביר repo

**עדכן `initTree()`:**

```javascript
async function initTree() {
    // ... קוד קיים עד שורה 145 ...
    
    try {
        // שימוש ב-buildApiUrl במקום string interpolation
        const url = buildApiUrl('tree', {
            types: getFilterQueryParam() || undefined
        });
        
        const response = await fetch(url, { signal });
        // ... המשך ללא שינוי ...
```

**עדכן `toggleFolder()`:**

```javascript
async function toggleFolder(node, item) {
    // ... קוד קיים עד שורה 260 ...
    
    // שימוש ב-buildApiUrl
    const url = buildApiUrl('tree', {
        path: item.path,
        types: getFilterQueryParam() || undefined
    });
    
    const response = await fetch(url);
    // ... המשך ללא שינוי ...
```

**עדכן `selectFile()`:**

```javascript
async function selectFile(path, element) {
    // ... קוד קיים עד שורה 656 ...
    
    // שימוש ב-buildApiUrl
    const response = await fetch(buildApiUrl(`file/${encodeURIComponent(path)}`));
    // ... המשך ללא שינוי ...
```

**עדכן `performRepoSearch()`:**

```javascript
async function performRepoSearch(query) {
    // ... קוד קיים עד שורה 1013 ...
    
    const response = await fetch(buildApiUrl('search', {
        q: clean,
        type: 'content'
    }), { signal: controller.signal });
    // ... המשך ללא שינוי ...
```

**עדכן `loadFileTypes()`:**

```javascript
async function loadFileTypes() {
    // ... קוד קיים עד שורה 429 ...
    
    const response = await fetch(buildApiUrl('file-types'), { signal });
    // ... המשך ללא שינוי ...
```

### 2.4 רשימת כל קריאות ה-API לעדכון

| פונקציה | שורה | URL נוכחי | URL חדש |
|---------|------|-----------|---------|
| `initTree()` | 152 | `/repo/api/tree` | `buildApiUrl('tree', {...})` |
| `toggleFolder()` | 261-264 | `/repo/api/tree?path=...` | `buildApiUrl('tree', {path: ...})` |
| `selectFile()` | 658 | `/repo/api/file/...` | `buildApiUrl('file/...')` |
| `performRepoSearch()` | 1014 | `/repo/api/search?q=...` | `buildApiUrl('search', {q: ...})` |
| `loadFileTypes()` | 429 | `/repo/api/file-types` | `buildApiUrl('file-types')` |

---

## שלב 3: UI - בורר ריפויים

### 3.1 הוספת Dropdown ל-HTML

**עדכן `base_repo.html` (בתוך `repo-search-bar`, לפני `search-wrapper`):**

```html
<!-- Repo Selector Dropdown -->
<div class="repo-selector" id="repo-selector">
    <button class="repo-selector-btn" id="repo-selector-btn" title="בחר ריפו">
        <i class="bi bi-folder2"></i>
        <span class="repo-selector-name" id="repo-selector-name">{{ repo_name }}</span>
        <i class="bi bi-chevron-down"></i>
    </button>
    <div class="repo-selector-dropdown" id="repo-selector-dropdown" style="display: none;">
        <div class="repo-selector-header">
            <span>בחר ריפו</span>
        </div>
        <div class="repo-selector-list" id="repo-selector-list">
            <div class="loading-repos">
                <div class="spinner-border spinner-border-sm" role="status"></div>
                <span>טוען...</span>
            </div>
        </div>
    </div>
</div>
```

### 3.2 הוספת JavaScript לבורר

```javascript
// הוסף לסוף repo-browser.js

// ========================================
// Repo Selector
// ========================================

let availableRepos = [];
let reposLoaded = false;

async function initRepoSelector() {
    const selectorBtn = document.getElementById('repo-selector-btn');
    const dropdown = document.getElementById('repo-selector-dropdown');
    const nameSpan = document.getElementById('repo-selector-name');
    
    if (!selectorBtn || !dropdown) return;
    
    // עדכון שם הריפו הנוכחי
    if (nameSpan) {
        nameSpan.textContent = currentRepo;
    }
    
    // Toggle dropdown
    selectorBtn.addEventListener('click', async (e) => {
        e.stopPropagation();
        const isOpen = dropdown.style.display !== 'none';
        
        if (isOpen) {
            dropdown.style.display = 'none';
        } else {
            dropdown.style.display = 'block';
            
            // טעינת רשימת ריפויים אם לא נטענה
            if (!reposLoaded) {
                await loadAvailableRepos();
            }
        }
    });
    
    // סגירת dropdown בלחיצה מחוץ
    document.addEventListener('click', (e) => {
        if (!e.target.closest('.repo-selector')) {
            dropdown.style.display = 'none';
        }
    });
}

async function loadAvailableRepos() {
    const listEl = document.getElementById('repo-selector-list');
    if (!listEl) return;
    
    try {
        const response = await fetch(`${CONFIG.apiBase}/repos`);
        const data = await response.json();
        
        if (Array.isArray(data)) {
            availableRepos = data;
            reposLoaded = true;
            renderRepoList();
        }
    } catch (error) {
        console.error('Failed to load repos:', error);
        listEl.innerHTML = `
            <div class="error-message" style="padding: 12px; color: var(--text-muted);">
                שגיאה בטעינת רשימת ריפויים
            </div>
        `;
    }
}

function renderRepoList() {
    const listEl = document.getElementById('repo-selector-list');
    if (!listEl) return;
    
    if (availableRepos.length === 0) {
        listEl.innerHTML = '<div class="no-repos">אין ריפויים זמינים</div>';
        return;
    }
    
    listEl.innerHTML = availableRepos.map(repo => {
        const isSelected = repo.name === currentRepo;
        return `
            <div class="repo-selector-item ${isSelected ? 'selected' : ''}" 
                 data-repo="${escapeHtml(repo.name)}"
                 onclick="selectRepo('${escapeJsStr(repo.name)}')">
                <div class="repo-item-info">
                    <i class="bi ${isSelected ? 'bi-check-circle-fill' : 'bi-folder2'}"></i>
                    <span class="repo-item-name">${escapeHtml(repo.name)}</span>
                </div>
                <span class="repo-item-files">${repo.total_files || 0} files</span>
            </div>
        `;
    }).join('');
}

function selectRepo(repoName) {
    if (repoName === currentRepo) {
        // אותו ריפו - רק סוגרים את הdropdown
        document.getElementById('repo-selector-dropdown').style.display = 'none';
        return;
    }
    
    // שמירה ב-localStorage
    currentRepo = repoName;
    localStorage.setItem('selectedRepo', repoName);
    
    // עדכון UI
    const nameSpan = document.getElementById('repo-selector-name');
    if (nameSpan) {
        nameSpan.textContent = repoName;
    }
    
    // סגירת dropdown
    document.getElementById('repo-selector-dropdown').style.display = 'none';
    
    // רענון הדפדפן עם הריפו החדש
    // ניקוי state קיים
    state.currentFile = null;
    state.treeData = null;
    state.expandedFolders.clear();
    state.selectedTypes.clear();
    
    // טעינה מחדש של העץ וסוגי הקבצים
    initTree();
    loadFileTypes().then(() => renderFilterList());
    
    // עדכון ה-URL
    const url = new URL(window.location.href);
    url.searchParams.set('repo', repoName);
    history.replaceState(null, '', url.toString());
    
    // הצגת מסך פתיחה
    document.getElementById('welcome-screen').style.display = 'flex';
    document.getElementById('code-editor-wrapper').style.display = 'none';
    document.getElementById('code-header').style.display = 'none';
    document.getElementById('code-footer').style.display = 'none';
    
    // עדכון רשימת הריפויים
    renderRepoList();
    
    showToast(`נבחר ריפו: ${repoName}`);
}

// הוסף לאתחול
document.addEventListener('DOMContentLoaded', () => {
    // ... קוד קיים ...
    
    // קריאת repo מ-URL אם קיים
    const urlParams = new URLSearchParams(window.location.search);
    const repoFromUrl = urlParams.get('repo');
    if (repoFromUrl) {
        currentRepo = repoFromUrl;
        localStorage.setItem('selectedRepo', repoFromUrl);
    }
    
    initRepoSelector();
});

// חשיפה גלובלית
window.selectRepo = selectRepo;
```

### 3.3 הוספת CSS לבורר

**הוסף ל-`repo-browser.css`:**

```css
/* ========================================
   Repo Selector
   ======================================== */

.repo-selector {
    position: relative;
    margin-left: 12px;
}

.repo-selector-btn {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 6px 12px;
    background: var(--bg-secondary);
    border: 1px solid var(--border-color);
    border-radius: 6px;
    color: var(--text-primary);
    cursor: pointer;
    transition: all 0.2s ease;
    font-size: 14px;
}

.repo-selector-btn:hover {
    background: var(--bg-tertiary);
    border-color: var(--accent-primary);
}

.repo-selector-btn i.bi-chevron-down {
    font-size: 12px;
    transition: transform 0.2s ease;
}

.repo-selector-btn:hover i.bi-chevron-down {
    transform: translateY(2px);
}

.repo-selector-name {
    max-width: 150px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.repo-selector-dropdown {
    position: absolute;
    top: calc(100% + 4px);
    left: 0;
    min-width: 250px;
    max-width: 350px;
    background: var(--bg-primary);
    border: 1px solid var(--border-color);
    border-radius: 8px;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
    z-index: 1000;
    overflow: hidden;
}

.repo-selector-header {
    padding: 10px 12px;
    border-bottom: 1px solid var(--border-color);
    font-weight: 500;
    color: var(--text-secondary);
    font-size: 13px;
}

.repo-selector-list {
    max-height: 300px;
    overflow-y: auto;
}

.repo-selector-item {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 10px 12px;
    cursor: pointer;
    transition: background 0.15s ease;
}

.repo-selector-item:hover {
    background: var(--bg-secondary);
}

.repo-selector-item.selected {
    background: var(--bg-tertiary);
}

.repo-selector-item.selected i {
    color: var(--accent-green);
}

.repo-item-info {
    display: flex;
    align-items: center;
    gap: 8px;
}

.repo-item-name {
    font-weight: 500;
}

.repo-item-files {
    font-size: 12px;
    color: var(--text-muted);
}

.loading-repos,
.no-repos {
    padding: 20px;
    text-align: center;
    color: var(--text-muted);
}

/* Mobile adjustments */
@media (max-width: 768px) {
    .repo-selector-name {
        display: none;
    }
    
    .repo-selector-btn {
        padding: 6px 10px;
    }
    
    .repo-selector-dropdown {
        left: auto;
        right: 0;
        min-width: 200px;
    }
}
```

---

## שלב 4: עדכון Breadcrumbs והקישורים

### 4.1 עדכון קישור GitHub

```javascript
// עדכן את updateBreadcrumbs() (שורה 911-948)
function updateBreadcrumbs(path) {
    // ... קוד קיים ...
    
    // עדכון קישור GitHub - דינמי לפי ריפו
    const githubLink = document.getElementById('github-link');
    if (githubLink) {
        // TODO: צריך לקבל את ה-GitHub URL מה-API או מה-metadata
        // לעת עתה, נניח שהריפו נמצא תחת amirbiron
        const encodedPath = path.split('/').map(segment => encodeURIComponent(segment)).join('/');
        githubLink.href = `https://github.com/amirbiron/${currentRepo}/blob/main/${encodedPath}`;
    }
}
```

### 4.2 הוספת שם ריפו ל-Breadcrumb

```javascript
function updateBreadcrumbs(path) {
    const breadcrumb = document.getElementById('file-breadcrumb');
    const parts = path.split('/');
    
    if (breadcrumb) {
        // הוסף את שם הריפו כפריט ראשון
        let html = `<li class="breadcrumb-item">
            <a href="#" onclick="goToRepoRoot()">${escapeHtml(currentRepo)}</a>
        </li>`;
        
        html += parts.map((part, index) => {
            const isLast = index === parts.length - 1;
            const partPath = parts.slice(0, index + 1).join('/');
            const safePart = escapeHtml(part);
            const safeJsPartPath = escapeJsStr(partPath);
            
            if (isLast) {
                return `<li class="breadcrumb-item active">${safePart}</li>`;
            }
            return `<li class="breadcrumb-item"><a href="#" onclick="navigateToFolder('${safeJsPartPath}')">${safePart}</a></li>`;
        }).join('');
        
        breadcrumb.innerHTML = html;
    }
    
    // ... המשך הקוד ...
}

function goToRepoRoot() {
    // ניקוי הקובץ הנבחר וחזרה למסך הפתיחה
    state.currentFile = null;
    document.getElementById('welcome-screen').style.display = 'flex';
    document.getElementById('code-editor-wrapper').style.display = 'none';
    document.getElementById('code-header').style.display = 'none';
    document.getElementById('code-footer').style.display = 'none';
    
    // עדכון URL
    history.replaceState(null, '', `/repo/?repo=${encodeURIComponent(currentRepo)}`);
}

window.goToRepoRoot = goToRepoRoot;
```

---

## שלב 5: עדכון History API

### 5.1 עדכון `repo-history.js`

```javascript
// הוסף פונקציה לקבלת repo parameter
function getHistoryRepoParam() {
    // שימוש ב-currentRepo מ-repo-browser.js
    return window.currentRepo || localStorage.getItem('selectedRepo') || 'CodeBot';
}

// עדכן את כל קריאות ה-API להעביר repo
// למשל ב-fetchFileHistory:
async function fetchFileHistory(filePath, limit = 20, skip = 0) {
    const repo = getHistoryRepoParam();
    const url = `/repo/api/history?file=${encodeURIComponent(filePath)}&repo=${encodeURIComponent(repo)}&limit=${limit}&skip=${skip}`;
    // ...
}
```

---

## שלב 6: Session Management ב-Flask

### 6.1 עדכון Config להפעלת Session

ודא ש-`SECRET_KEY` מוגדר ב-`config.py`:

```python
# Flask session secret
SECRET_KEY = os.getenv('SECRET_KEY', 'your-secure-secret-key-here')
```

### 6.2 עדכון API לשמירת הבחירה ב-DB (אופציונלי)

```python
@repo_bp.route('/api/select-repo', methods=['POST'])
def api_select_repo():
    """
    שמירת הריפו הנבחר ב-session וב-DB (אם המשתמש מחובר).
    """
    data = request.get_json() or {}
    repo_name = data.get('repo', '').strip()
    
    if not repo_name:
        return jsonify({"error": "Missing repo name"}), 400
    
    # שמירה ב-session
    session['selected_repo'] = repo_name
    
    # שמירה ב-DB אם המשתמש מחובר
    # user_id = get_current_user_id()  # תלוי במערכת האימות שלכם
    # if user_id:
    #     db = get_db()
    #     db.users.update_one(
    #         {"user_id": user_id},
    #         {"$set": {"selected_repo": repo_name}},
    #         upsert=True
    #     )
    
    return jsonify({"success": True, "repo": repo_name})
```

---

## סיכום השינויים

### קבצים לעדכון

| קובץ | סוג שינוי | מורכבות |
|------|----------|----------|
| `webapp/routes/repo_browser.py` | הוספת API + עדכון routes | בינונית |
| `webapp/static/js/repo-browser.js` | State + API calls + UI | בינונית |
| `webapp/static/js/repo-history.js` | עדכון קריאות API | קלה |
| `webapp/templates/repo/base_repo.html` | הוספת dropdown | קלה |
| `webapp/static/css/repo-browser.css` | סטיילים לבורר | קלה |

### סדר מימוש מומלץ

1. **Backend API** - הוסף את `/api/repos` ואת `get_selected_repo_name()`
2. **עדכון Routes** - שנה את כל ה-hardcoded `"CodeBot"` לפונקציה
3. **Frontend State** - הוסף את `currentRepo` ו-`buildApiUrl()`
4. **עדכון Fetch** - שנה את כל קריאות ה-API
5. **UI Dropdown** - הוסף את ה-HTML, JS, ו-CSS
6. **בדיקות** - בדוק כל פונקציונליות

### בדיקות מומלצות

- [ ] טעינת עץ קבצים לריפויים שונים
- [ ] חיפוש בריפו ספציפי
- [ ] היסטוריית קבצים
- [ ] diff בין commits
- [ ] שמירת בחירה ב-localStorage
- [ ] החלפת ריפו ורענון העץ
- [ ] breadcrumbs עם שם ריפו
- [ ] קישור GitHub נכון לכל ריפו

---

## נספח: קוד מלא לעדכון `repo_browser.py`

```python
# הוסף בתחילת הקובץ אחרי הייבואים
from flask import session

# הוסף לאחר הגדרת DEFAULT_REPO_NAME (שורה 21)
def get_selected_repo_name() -> str:
    """קבלת שם הריפו הנבחר."""
    repo_from_query = request.args.get('repo', '').strip()
    if repo_from_query:
        session['selected_repo'] = repo_from_query
        return repo_from_query
    
    repo_from_session = session.get('selected_repo', '').strip()
    if repo_from_session:
        return repo_from_session
    
    return DEFAULT_REPO_NAME


# הוסף API חדש (לפני או אחרי api_stats)
@repo_bp.route('/api/repos')
def api_list_repos():
    """API לקבלת רשימת ריפויים זמינים."""
    db = get_db()
    
    try:
        repos = list(db.repo_metadata.find(
            {},
            {"repo_name": 1, "total_files": 1, "default_branch": 1, 
             "last_sync_time": 1, "sync_status": 1}
        ).sort("repo_name", 1))
        
        return jsonify([{
            "name": r.get("repo_name", "Unknown"),
            "total_files": r.get("total_files", 0),
            "default_branch": r.get("default_branch", "main"),
            "last_sync": r.get("last_sync_time"),
            "sync_status": r.get("sync_status", "unknown")
        } for r in repos])
    except Exception as e:
        logger.exception(f"List repos API error: {e}")
        return jsonify({"error": "Internal server error"}), 500
```

ואז החלף כל מופע של `repo_name = "CodeBot"` ב-`repo_name = get_selected_repo_name()`.
