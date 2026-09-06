# מדריך מימוש: דפדפן ריפו מרובים (Multi-Repo Browser)

> מדריך מפורט ליצירת ווב אפליקציה שמאפשרת בחירת ריפוים מ-GitHub, דפדפון קבצים, חיפוש גלובלי, וצפייה בהיסטוריית commits - מבוסס על הארכיטקטורה של CodeBot.

---

## 📋 תוכן העניינים

1. [סקירת ארכיטקטורה](#1-סקירת-ארכיטקטורה)
2. [מבנה הפרויקט](#2-מבנה-הפרויקט)
3. [Backend - שכבת השירותים](#3-backend---שכבת-השירותים)
4. [Backend - API Routes](#4-backend---api-routes)
5. [Frontend - ממשק משתמש](#5-frontend---ממשק-משתמש)
6. [מסד נתונים](#6-מסד-נתונים)
7. [תכונות מרכזיות](#7-תכונות-מרכזיות)
8. [אבטחה](#8-אבטחה)
9. [ביצועים ואופטימיזציות](#9-ביצועים-ואופטימיזציות)
10. [הגדרות והתקנה](#10-הגדרות-והתקנה)

---

## 1. סקירת ארכיטקטורה

### איך CodeBot עובד

```
┌─────────────────────────────────────────────────────────────────┐
│                         Web Browser                              │
├─────────────────────────────────────────────────────────────────┤
│  repo-browser.js    │    repo-history.js    │   CodeMirror      │
│  (Tree + Search)    │    (Git History)      │   (Code Viewer)   │
└──────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Flask API Routes                            │
│  /repo/api/tree  │  /repo/api/file  │  /repo/api/search         │
│  /repo/api/history  │  /repo/api/diff  │  /repo/api/commit      │
└─────────────────────────────────────────────────────────────────┘
                              │
                ┌─────────────┴─────────────┐
                ▼                           ▼
┌──────────────────────────┐   ┌──────────────────────────┐
│   GitMirrorService       │   │      MongoDB             │
│   (git bare mirror)      │   │   repo_files collection  │
│                          │   │   repo_metadata          │
│   - git grep (search)    │   │                          │
│   - git show (content)   │   │   - path, language       │
│   - git log (history)    │   │   - functions, classes   │
│   - git diff             │   │   - size, lines          │
└──────────────────────────┘   └──────────────────────────┘
```

### הרחבה ל-Multi-Repo

```
┌─────────────────────────────────────────────────────────────────┐
│                      Multi-Repo Browser                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  1. Repo Selector UI (בחירת ריפוים)                              │
│     └─ GitHub API / Manual URL                                   │
│                                                                  │
│  2. Unified Tree View (עץ קבצים מאוחד)                           │
│     └─ repo1/                                                   │
│     └─ repo2/                                                   │
│     └─ repo3/                                                   │
│                                                                  │
│  3. Cross-Repo Search (חיפוש גלובלי בכל הריפוים)                 │
│                                                                  │
│  4. File Viewer (CodeMirror)                                    │
│                                                                  │
│  5. History & Diff per repo                                     │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2. מבנה הפרויקט

### מבנה תיקיות מומלץ

```
multi-repo-browser/
├── app.py                     # Flask application entry point
├── config.py                  # Configuration
├── requirements.txt           # Python dependencies
│
├── services/
│   ├── __init__.py
│   ├── git_mirror_service.py  # Git operations (מקורי מ-CodeBot)
│   ├── repo_search_service.py # Search service (מקורי מ-CodeBot)
│   ├── repo_manager.py        # NEW: Multi-repo management
│   └── github_api_service.py  # NEW: GitHub API integration
│
├── database/
│   ├── __init__.py
│   ├── db_manager.py          # MongoDB connection
│   └── models.py              # Data models
│
├── routes/
│   ├── __init__.py
│   ├── repo_browser.py        # API routes (מותאם מ-CodeBot)
│   ├── repo_selector.py       # NEW: Repo selection API
│   └── webhooks.py            # Optional: GitHub webhooks
│
├── templates/
│   ├── base.html
│   └── repo/
│       ├── index.html         # Main browser page
│       ├── base_repo.html     # Base template
│       └── selector.html      # NEW: Repo selector
│
├── static/
│   ├── css/
│   │   └── repo-browser.css
│   └── js/
│       ├── repo-browser.js    # Main browser logic
│       ├── repo-history.js    # Git history module
│       └── repo-selector.js   # NEW: Selection logic
│
└── scripts/
    ├── initial_import.py      # Import/sync repos
    └── cleanup.py             # Cleanup old mirrors
```

---

## 3. Backend - שכבת השירותים

### 3.1 GitMirrorService (קוד מקור מ-CodeBot)

השירות המרכזי לניהול Git mirrors. הקוד המלא נמצא ב-`services/git_mirror_service.py`.

**יכולות עיקריות:**

```python
class GitMirrorService:
    """
    שירות לניהול Git Mirror על דיסק מקומי
    
    שימוש:
        service = GitMirrorService()
        service.init_mirror("https://github.com/user/repo.git", "repo")
        service.fetch_updates("repo")
        content = service.get_file_content("repo", "src/main.py")
    """
    
    def __init__(self, base_path: str = None, github_token: str = None):
        """
        Args:
            base_path: נתיב לאחסון mirrors (ברירת מחדל: /var/data/repos)
            github_token: טוקן לגישה ל-Private repos
        """
        
    # === Mirror Management ===
    def init_mirror(self, repo_url: str, repo_name: str, timeout: int = 600) -> Dict:
        """Clone ראשוני של ריפו כ-bare mirror"""
        
    def fetch_updates(self, repo_name: str, timeout: int = 120) -> Dict:
        """עדכון delta בלבד (fetch --all --prune)"""
        
    def mirror_exists(self, repo_name: str) -> bool:
        """בדיקה אם mirror קיים"""
        
    def get_mirror_info(self, repo_name: str) -> Optional[Dict]:
        """קבלת מידע על mirror (גודל, SHA נוכחי)"""
    
    # === File Operations ===
    def get_file_content(self, repo_name: str, file_path: str, ref: str = "HEAD") -> Optional[str]:
        """קריאת תוכן קובץ"""
        
    def list_all_files(self, repo_name: str, ref: str = "HEAD") -> Optional[List[str]]:
        """רשימת כל הקבצים בריפו"""
        
    def get_file_info(self, repo_name: str, file_path: str, ref: str = "HEAD") -> Optional[Dict]:
        """מידע על קובץ (גודל, סוג)"""
    
    # === History & Diff ===
    def get_file_history(self, repo_name: str, file_path: str, 
                         ref: str = "HEAD", limit: int = 20, skip: int = 0) -> Dict:
        """היסטוריית commits לקובץ"""
        
    def get_file_at_commit(self, repo_name: str, file_path: str, 
                           commit: str, max_size: int = 500*1024) -> Dict:
        """תוכן קובץ ב-commit ספציפי"""
        
    def get_diff(self, repo_name: str, commit1: str, commit2: str,
                 file_path: Optional[str] = None, context_lines: int = 3) -> Dict:
        """Diff בין commits"""
        
    def get_commit_info(self, repo_name: str, commit: str) -> Dict:
        """פרטי commit בודד"""
        
    def search_history(self, repo_name: str, query: str, 
                       search_type: str = "message", limit: int = 20) -> Dict:
        """חיפוש בהיסטוריית commits"""
    
    # === Search ===
    def search_with_git_grep(self, repo_name: str, query: str,
                             max_results: int = 100, file_pattern: str = None,
                             case_sensitive: bool = True, ref: str = None) -> Dict:
        """חיפוש בקוד עם git grep (מהיר מאוד!)"""
```

### 3.2 RepoSearchService (קוד מקור מ-CodeBot)

שירות חיפוש משולב:

```python
class RepoSearchService:
    """
    שירות חיפוש בקוד
    
    משלב:
    - git grep לחיפוש תוכן (מהיר!)
    - MongoDB לחיפוש metadata (שמות קבצים, פונקציות, מחלקות)
    """
    
    def __init__(self, db: Any = None):
        self.db = db
        self.git_service = get_mirror_service()
    
    def search(self, repo_name: str, query: str,
               search_type: str = "content",  # content, filename, function, class
               file_pattern: str = None,
               language: str = None,
               case_sensitive: bool = False,
               max_results: int = 50) -> Dict:
        """
        חיפוש מאוחד בקוד
        
        search_types:
        - content: חיפוש בתוכן קבצים (git grep)
        - filename: חיפוש בשמות קבצים
        - function: חיפוש שמות פונקציות
        - class: חיפוש שמות מחלקות
        """
```

### 3.3 RepoManagerService (חדש - להרחבה)

שירות חדש לניהול ריפוים מרובים:

```python
# services/repo_manager.py

from typing import List, Dict, Optional
from dataclasses import dataclass
from datetime import datetime

@dataclass
class RepoConfig:
    """הגדרות ריפו"""
    name: str
    url: str
    default_branch: str = "main"
    is_private: bool = False
    last_sync: Optional[datetime] = None
    sync_status: str = "pending"  # pending, syncing, synced, error


class RepoManagerService:
    """
    ניהול ריפוים מרובים
    
    אחראי על:
    - הוספה/הסרה של ריפוים
    - סנכרון אוטומטי
    - מעקב סטטוס
    """
    
    def __init__(self, db, git_service: GitMirrorService):
        self.db = db
        self.git_service = git_service
        self.repos_collection = db.repos
        
    def add_repo(self, url: str, name: str = None) -> Dict:
        """
        הוספת ריפו חדש
        
        Args:
            url: GitHub URL (https://github.com/owner/repo)
            name: שם ייחודי (ברירת מחדל: נגזר מה-URL)
            
        Returns:
            Dict עם success, repo_info או error
        """
        # Validate URL
        if not self._validate_github_url(url):
            return {"success": False, "error": "Invalid GitHub URL"}
            
        # Extract name if not provided
        if not name:
            name = self._extract_repo_name(url)
            
        # Check if already exists
        if self.repos_collection.find_one({"name": name}):
            return {"success": False, "error": "Repo already exists"}
            
        # Create mirror
        result = self.git_service.init_mirror(url, name)
        if not result["success"]:
            return result
            
        # Save to DB
        repo_config = {
            "name": name,
            "url": url,
            "default_branch": "main",  # Will be updated after first sync
            "created_at": datetime.utcnow(),
            "last_sync": datetime.utcnow(),
            "sync_status": "synced"
        }
        self.repos_collection.insert_one(repo_config)
        
        # Index files
        self._index_repo_files(name)
        
        return {"success": True, "repo": repo_config}
        
    def remove_repo(self, name: str) -> Dict:
        """הסרת ריפו"""
        # Remove from DB
        self.repos_collection.delete_one({"name": name})
        self.db.repo_files.delete_many({"repo_name": name})
        
        # Remove mirror directory (safely!)
        mirror_path = self.git_service._get_repo_path(name)
        self.git_service._safe_rmtree(mirror_path)
        
        return {"success": True}
        
    def list_repos(self) -> List[Dict]:
        """רשימת כל הריפוים"""
        repos = list(self.repos_collection.find({}, {"_id": 0}))
        
        # Enrich with mirror info
        for repo in repos:
            mirror_info = self.git_service.get_mirror_info(repo["name"])
            if mirror_info:
                repo["size_mb"] = mirror_info.get("size_mb", 0)
                repo["current_sha"] = mirror_info.get("current_sha")
                
        return repos
        
    def sync_repo(self, name: str) -> Dict:
        """סנכרון ריפו (fetch updates)"""
        # Update status
        self.repos_collection.update_one(
            {"name": name},
            {"$set": {"sync_status": "syncing"}}
        )
        
        try:
            result = self.git_service.fetch_updates(name)
            
            if result["success"]:
                # Re-index files if needed
                self._index_repo_files(name)
                
                self.repos_collection.update_one(
                    {"name": name},
                    {"$set": {
                        "sync_status": "synced",
                        "last_sync": datetime.utcnow()
                    }}
                )
            else:
                self.repos_collection.update_one(
                    {"name": name},
                    {"$set": {
                        "sync_status": "error",
                        "last_error": result.get("message", "Unknown error")
                    }}
                )
                
            return result
            
        except Exception as e:
            self.repos_collection.update_one(
                {"name": name},
                {"$set": {"sync_status": "error", "last_error": str(e)}}
            )
            return {"success": False, "error": str(e)}
            
    def sync_all_repos(self) -> Dict:
        """סנכרון כל הריפוים"""
        results = {}
        for repo in self.list_repos():
            results[repo["name"]] = self.sync_repo(repo["name"])
        return results
        
    def _index_repo_files(self, repo_name: str):
        """אינדוקס קבצי הריפו ל-MongoDB"""
        files = self.git_service.list_all_files(repo_name)
        if not files:
            return
            
        # Delete old entries
        self.db.repo_files.delete_many({"repo_name": repo_name})
        
        # Batch insert
        docs = []
        for file_path in files:
            info = self.git_service.get_file_info(repo_name, file_path)
            
            docs.append({
                "repo_name": repo_name,
                "path": file_path,
                "language": self._detect_language(file_path),
                "size": info.get("size", 0) if info else 0,
                "lines": 0  # Will be calculated on demand
            })
            
        if docs:
            self.db.repo_files.insert_many(docs)
            
    def _detect_language(self, file_path: str) -> str:
        """זיהוי שפת תכנות לפי סיומת"""
        ext_map = {
            '.py': 'python',
            '.js': 'javascript',
            '.jsx': 'javascript',
            '.ts': 'typescript',
            '.tsx': 'typescript',
            '.html': 'html',
            '.css': 'css',
            '.scss': 'css',
            '.json': 'json',
            '.yaml': 'yaml',
            '.yml': 'yaml',
            '.md': 'markdown',
            '.sh': 'shell',
            '.bash': 'shell',
            '.sql': 'sql',
            '.go': 'go',
            '.rs': 'rust',
            '.java': 'java',
            '.kt': 'kotlin',
            '.rb': 'ruby',
            '.php': 'php',
        }
        
        from pathlib import Path
        ext = Path(file_path).suffix.lower()
        return ext_map.get(ext, 'text')
        
    def _validate_github_url(self, url: str) -> bool:
        """Validate GitHub URL format"""
        import re
        pattern = r'^https://github\.com/[^/]+/[^/]+(?:\.git)?/?$'
        return bool(re.match(pattern, url, re.IGNORECASE))
        
    def _extract_repo_name(self, url: str) -> str:
        """Extract repo name from URL"""
        # https://github.com/owner/repo.git -> owner_repo
        parts = url.rstrip('/').rstrip('.git').split('/')
        if len(parts) >= 2:
            owner = parts[-2]
            repo = parts[-1]
            return f"{owner}_{repo}"
        return "unknown_repo"
```

### 3.4 Cross-Repo Search Service (חדש)

```python
# services/cross_repo_search.py

class CrossRepoSearchService:
    """
    חיפוש גלובלי בכל הריפוים
    """
    
    def __init__(self, db, git_service: GitMirrorService):
        self.db = db
        self.git_service = git_service
        self.repo_search = RepoSearchService(db)
        
    def search_all_repos(
        self,
        query: str,
        search_type: str = "content",
        repos: List[str] = None,  # None = all repos
        file_pattern: str = None,
        language: str = None,
        max_results_per_repo: int = 20,
        total_max_results: int = 100
    ) -> Dict:
        """
        חיפוש בכל הריפוים
        
        Returns:
            {
                "results": [
                    {"repo": "repo1", "path": "...", "line": 10, "content": "..."},
                    ...
                ],
                "by_repo": {
                    "repo1": {"count": 5, "results": [...]},
                    "repo2": {"count": 3, "results": [...]}
                },
                "total": 8,
                "query": "...",
                "truncated": False
            }
        """
        # Get list of repos to search
        if repos is None:
            repo_list = [r["name"] for r in self.db.repos.find({}, {"name": 1})]
        else:
            repo_list = repos
            
        all_results = []
        by_repo = {}
        
        for repo_name in repo_list:
            if len(all_results) >= total_max_results:
                break
                
            result = self.repo_search.search(
                repo_name=repo_name,
                query=query,
                search_type=search_type,
                file_pattern=file_pattern,
                language=language,
                max_results=max_results_per_repo
            )
            
            if result.get("error"):
                continue
                
            repo_results = result.get("results", [])
            
            # Add repo name to each result
            for r in repo_results:
                r["repo"] = repo_name
                
            by_repo[repo_name] = {
                "count": len(repo_results),
                "results": repo_results
            }
            
            all_results.extend(repo_results)
            
        # Truncate if needed
        truncated = len(all_results) > total_max_results
        all_results = all_results[:total_max_results]
        
        return {
            "results": all_results,
            "by_repo": by_repo,
            "total": len(all_results),
            "query": query,
            "search_type": search_type,
            "truncated": truncated
        }
```

---

## 4. Backend - API Routes

### 4.1 Repo Browser Routes (מותאם מ-CodeBot)

```python
# routes/repo_browser.py

from flask import Blueprint, request, jsonify
from services.git_mirror_service import get_mirror_service
from services.repo_search_service import create_search_service
from services.cross_repo_search import CrossRepoSearchService
from database.db_manager import get_db

repo_bp = Blueprint('repo', __name__, url_prefix='/repo')


# ========================================
# Tree API
# ========================================

@repo_bp.route('/api/tree')
def api_tree():
    """
    API לקבלת עץ הקבצים
    
    Query params:
        repo: שם הריפו (חובה ב-multi-repo mode)
        path: נתיב לתיקייה ספציפית
        types: סינון לפי סוגי קבצים
    """
    db = get_db()
    repo_name = request.args.get('repo', '')
    path = request.args.get('path', '')
    types_param = request.args.get('types', '').strip()
    
    if not repo_name:
        # Multi-repo mode: return list of repos as root
        repos = list(db.repos.find({}, {"name": 1, "url": 1, "_id": 0}))
        return jsonify([
            {
                "name": r["name"],
                "path": r["name"],
                "type": "directory",
                "is_repo_root": True
            }
            for r in repos
        ])
    
    # Build tree (same as CodeBot)
    # ... (existing implementation)


@repo_bp.route('/api/file/<repo_name>/<path:file_path>')
def api_get_file(repo_name: str, file_path: str):
    """API לקבלת תוכן קובץ"""
    git_service = get_mirror_service()
    db = get_db()
    
    # Get content
    content = git_service.get_file_content(repo_name, file_path)
    
    if content is None:
        return jsonify({"error": "File not found"}), 404
    
    # Get metadata
    metadata = db.repo_files.find_one({
        "repo_name": repo_name,
        "path": file_path
    })
    
    return jsonify({
        "repo": repo_name,
        "path": file_path,
        "content": content,
        "language": metadata.get("language", "text") if metadata else "text",
        "size": len(content),
        "lines": content.count("\n") + 1
    })


# ========================================
# Search API
# ========================================

@repo_bp.route('/api/search')
def api_search():
    """
    API לחיפוש
    
    Query params:
        q: מילת החיפוש
        type: סוג החיפוש (content, filename, function, class)
        repo: שם ריפו ספציפי (ריק = כל הריפוים)
        pattern: סינון קבצים (*.py)
        language: סינון לפי שפה
    """
    query = request.args.get('q', '')
    search_type = request.args.get('type', 'content')
    repo_name = request.args.get('repo', '')
    file_pattern = request.args.get('pattern', '')
    language = request.args.get('language', '')
    
    if not query or len(query) < 2:
        return jsonify({"error": "Query too short", "results": []})
    
    db = get_db()
    
    if repo_name:
        # Single repo search
        search_service = create_search_service(db)
        return jsonify(search_service.search(
            repo_name=repo_name,
            query=query,
            search_type=search_type,
            file_pattern=file_pattern or None,
            language=language or None
        ))
    else:
        # Cross-repo search
        cross_search = CrossRepoSearchService(db, get_mirror_service())
        return jsonify(cross_search.search_all_repos(
            query=query,
            search_type=search_type,
            file_pattern=file_pattern or None,
            language=language or None
        ))


# ========================================
# History API
# ========================================

@repo_bp.route('/api/history')
def api_history():
    """
    היסטוריית קובץ
    
    Query params:
        repo: שם הריפו
        file: נתיב הקובץ
        limit: מספר commits
        skip: offset
    """
    repo_name = request.args.get('repo', '')
    file_path = request.args.get('file', '')
    limit = request.args.get('limit', 20, type=int)
    skip = request.args.get('skip', 0, type=int)
    
    if not repo_name or not file_path:
        return jsonify({"error": "Missing repo or file parameter"}), 400
    
    git_service = get_mirror_service()
    return jsonify(git_service.get_file_history(
        repo_name=repo_name,
        file_path=file_path,
        limit=limit,
        skip=skip
    ))


@repo_bp.route('/api/file-at-commit/<repo_name>/<commit>')
def api_file_at_commit(repo_name: str, commit: str):
    """תוכן קובץ ב-commit ספציפי"""
    file_path = request.args.get('file', '')
    
    if not file_path:
        return jsonify({"error": "Missing file parameter"}), 400
    
    git_service = get_mirror_service()
    return jsonify(git_service.get_file_at_commit(
        repo_name=repo_name,
        file_path=file_path,
        commit=commit
    ))


@repo_bp.route('/api/diff/<repo_name>/<commit1>/<commit2>')
def api_diff(repo_name: str, commit1: str, commit2: str):
    """Diff בין commits"""
    file_path = request.args.get('file')
    context = request.args.get('context', 3, type=int)
    
    git_service = get_mirror_service()
    return jsonify(git_service.get_diff(
        repo_name=repo_name,
        commit1=commit1,
        commit2=commit2,
        file_path=file_path,
        context_lines=context
    ))


@repo_bp.route('/api/search-history')
def api_search_history():
    """חיפוש בהיסטוריה"""
    repo_name = request.args.get('repo', '')
    query = request.args.get('q', '')
    search_type = request.args.get('type', 'message')  # message or code
    file_path = request.args.get('file')
    limit = request.args.get('limit', 20, type=int)
    
    if not repo_name or not query:
        return jsonify({"error": "Missing repo or query"}), 400
    
    git_service = get_mirror_service()
    return jsonify(git_service.search_history(
        repo_name=repo_name,
        query=query,
        search_type=search_type,
        file_path=file_path,
        limit=limit
    ))
```

### 4.2 Repo Selector Routes (חדש)

```python
# routes/repo_selector.py

from flask import Blueprint, request, jsonify
from services.repo_manager import RepoManagerService
from services.git_mirror_service import get_mirror_service
from database.db_manager import get_db

selector_bp = Blueprint('selector', __name__, url_prefix='/repos')


@selector_bp.route('/', methods=['GET'])
def list_repos():
    """רשימת כל הריפוים"""
    manager = RepoManagerService(get_db(), get_mirror_service())
    return jsonify(manager.list_repos())


@selector_bp.route('/', methods=['POST'])
def add_repo():
    """הוספת ריפו חדש"""
    data = request.json or {}
    url = data.get('url', '')
    name = data.get('name')
    
    if not url:
        return jsonify({"error": "URL is required"}), 400
    
    manager = RepoManagerService(get_db(), get_mirror_service())
    result = manager.add_repo(url, name)
    
    if result["success"]:
        return jsonify(result), 201
    else:
        return jsonify(result), 400


@selector_bp.route('/<name>', methods=['DELETE'])
def remove_repo(name: str):
    """הסרת ריפו"""
    manager = RepoManagerService(get_db(), get_mirror_service())
    result = manager.remove_repo(name)
    return jsonify(result)


@selector_bp.route('/<name>/sync', methods=['POST'])
def sync_repo(name: str):
    """סנכרון ריפו"""
    manager = RepoManagerService(get_db(), get_mirror_service())
    result = manager.sync_repo(name)
    return jsonify(result)


@selector_bp.route('/sync-all', methods=['POST'])
def sync_all():
    """סנכרון כל הריפוים"""
    manager = RepoManagerService(get_db(), get_mirror_service())
    result = manager.sync_all_repos()
    return jsonify(result)


@selector_bp.route('/validate-url', methods=['POST'])
def validate_url():
    """בדיקת תקינות URL"""
    data = request.json or {}
    url = data.get('url', '')
    
    manager = RepoManagerService(get_db(), get_mirror_service())
    is_valid = manager._validate_github_url(url)
    
    return jsonify({
        "valid": is_valid,
        "suggested_name": manager._extract_repo_name(url) if is_valid else None
    })
```

---

## 5. Frontend - ממשק משתמש

### 5.1 מבנה HTML בסיסי (מותאם מ-CodeBot)

```html
<!-- templates/repo/index.html -->
{% extends "repo/base_repo.html" %}

{% block tree_content %}
<div class="tree-view" id="file-tree">
    <!-- Tree will be populated by JavaScript -->
</div>
{% endblock %}

{% block code_content %}
<div class="code-viewer-container" id="code-viewer-container">
    <!-- Breadcrumbs -->
    <div class="code-header" id="code-header" style="display: none;">
        <div class="file-header"></div>
        <nav aria-label="breadcrumb" class="file-breadcrumb">
            <ol class="breadcrumb" id="file-breadcrumb"></ol>
        </nav>
        <div class="file-actions">
            <button class="btn-icon" id="search-in-file" title="Search in file (Ctrl+F)">
                <i class="bi bi-search"></i>
            </button>
            <button class="btn-icon" id="copy-path" title="Copy path">
                <i class="bi bi-clipboard"></i>
            </button>
            <a class="btn-icon" id="github-link" href="#" target="_blank" title="View on GitHub">
                <i class="bi bi-github"></i>
            </a>
        </div>
    </div>

    <!-- In-file Search Bar -->
    <div class="in-file-search" id="in-file-search" style="display: none;">
        <input type="text" id="in-file-search-input" placeholder="Search in file...">
        <span id="in-file-search-count"></span>
        <button class="btn-icon" onclick="findPrevMatch()" title="Previous">
            <i class="bi bi-chevron-up"></i>
        </button>
        <button class="btn-icon" onclick="findNextMatch()" title="Next">
            <i class="bi bi-chevron-down"></i>
        </button>
        <button class="btn-icon" onclick="closeInFileSearch()" title="Close">
            <i class="bi bi-x"></i>
        </button>
    </div>

    <!-- Code Editor Container -->
    <div class="code-editor-wrapper" id="code-editor-wrapper" style="display: none;">
        <textarea id="code-editor"></textarea>
    </div>

    <!-- File Info Footer -->
    <div class="code-footer" id="code-footer" style="display: none;">
        <span class="file-info" id="file-info"></span>
    </div>

    <!-- Welcome Screen -->
    <div class="welcome-screen" id="welcome-screen">
        <div class="welcome-icon">
            <i class="bi bi-code-square"></i>
        </div>
        <h3>ברוכים הבאים לדפדפן הקוד</h3>
        <p>בחר ריפו מהרשימה, או הוסף ריפו חדש</p>
        <div class="quick-actions">
            <button class="btn btn-primary" onclick="openRepoSelector()">
                <i class="bi bi-plus-lg"></i>
                הוסף ריפו
            </button>
            <button class="btn btn-outline-primary" onclick="focusSearch()">
                <i class="bi bi-search"></i>
                חפש (Ctrl+K)
            </button>
        </div>
    </div>
</div>
{% endblock %}
```

### 5.2 JavaScript - Multi-Repo Logic

```javascript
// static/js/repo-browser.js (התאמות ל-multi-repo)

const CONFIG = {
    apiBase: '/repo/api',
    selectorsApiBase: '/repos',
    maxRecentFiles: 5,
    searchDebounceMs: 300,
    // ... mode map for CodeMirror
};

let state = {
    currentRepo: null,    // NEW: currently selected repo
    currentFile: null,
    treeData: null,
    editor: null,
    expandedFolders: new Set(),
    selectedElement: null,
    // ... other state
};

// ========================================
// Multi-Repo Tree
// ========================================

async function initTree() {
    const treeContainer = document.getElementById('file-tree');
    if (!treeContainer) return;

    try {
        let url = `${CONFIG.apiBase}/tree`;
        
        // If repo is selected, show its tree
        if (state.currentRepo) {
            url += `?repo=${encodeURIComponent(state.currentRepo)}`;
        }
        // Else show list of repos
        
        const response = await fetch(url);
        const data = await response.json();
        state.treeData = data;
        renderTree(treeContainer, data);
    } catch (error) {
        console.error('Failed to load tree:', error);
        treeContainer.innerHTML = `
            <div class="error-message">
                <i class="bi bi-exclamation-triangle"></i>
                <span>Failed to load file tree</span>
            </div>
        `;
    }
}

function createTreeNode(item, level) {
    const node = document.createElement('div');
    node.className = 'tree-node';
    node.dataset.path = item.path;
    node.dataset.type = item.type;
    
    // NEW: Mark repo root nodes
    if (item.is_repo_root) {
        node.dataset.repo = item.name;
        node.classList.add('repo-root');
    }

    const itemEl = document.createElement('div');
    itemEl.className = 'tree-item';
    itemEl.style.paddingLeft = `${8 + level * 16}px`;

    // Icon - special icon for repo roots
    const icon = document.createElement('span');
    icon.className = `tree-icon ${item.is_repo_root ? 'repo-icon' : getIconClass(item)}`;
    icon.innerHTML = item.is_repo_root 
        ? '<i class="bi bi-github"></i>'
        : getIcon(item);

    // Name
    const name = document.createElement('span');
    name.className = 'tree-name';
    name.textContent = item.name;

    // Sync status badge for repos
    if (item.is_repo_root && item.sync_status) {
        const badge = document.createElement('span');
        badge.className = `sync-badge ${item.sync_status}`;
        badge.title = item.sync_status;
        name.appendChild(badge);
    }

    // ... rest of node creation

    // Click handler
    if (item.is_repo_root) {
        // Clicking repo root: select it and expand
        itemEl.addEventListener('click', (e) => {
            e.stopPropagation();
            selectRepo(item.name);
        });
    } else if (item.type === 'directory') {
        itemEl.addEventListener('click', (e) => {
            e.stopPropagation();
            toggleFolder(node, item);
        });
    } else {
        itemEl.addEventListener('click', (e) => {
            e.stopPropagation();
            selectFile(state.currentRepo, item.path, itemEl);
        });
    }

    return node;
}

function selectRepo(repoName) {
    state.currentRepo = repoName;
    
    // Update UI to show selected repo
    document.querySelectorAll('.repo-root').forEach(el => {
        el.classList.remove('selected');
    });
    const selectedNode = document.querySelector(`[data-repo="${repoName}"]`);
    if (selectedNode) {
        selectedNode.classList.add('selected');
    }
    
    // Reload tree with repo's files
    initTree();
    
    // Update search placeholder
    const searchInput = document.getElementById('global-search');
    if (searchInput) {
        searchInput.placeholder = `חפש ב-${repoName}... (Ctrl+K)`;
    }
}

// ========================================
// File Selection (modified for multi-repo)
// ========================================

async function selectFile(repoName, path, element) {
    // ... same as before, but include repoName in API calls
    
    const response = await fetch(
        `${CONFIG.apiBase}/file/${encodeURIComponent(repoName)}/${encodeURIComponent(path)}`
    );
    // ...
}

// ========================================
// Search (multi-repo support)
// ========================================

async function performSearch(query) {
    const dropdown = document.getElementById('search-results-dropdown');
    const resultsList = dropdown.querySelector('.search-results-list');
    
    if (query.length < 2) {
        dropdown.classList.add('hidden');
        return;
    }

    dropdown.classList.remove('hidden');
    resultsList.innerHTML = '<div class="search-loading">מחפש...</div>';

    try {
        // Build URL - include repo if one is selected
        let url = `${CONFIG.apiBase}/search?q=${encodeURIComponent(query)}&type=content`;
        if (state.currentRepo) {
            url += `&repo=${encodeURIComponent(state.currentRepo)}`;
        }

        const response = await fetch(url);
        const data = await response.json();

        renderSearchResults(resultsList, data.results || [], query, !state.currentRepo);
    } catch (error) {
        console.error('Search failed:', error);
        resultsList.innerHTML = '<div class="search-error">שגיאה בחיפוש</div>';
    }
}

function renderSearchResults(container, results, query, showRepo = false) {
    if (results.length === 0) {
        container.innerHTML = '<div class="no-results">לא נמצאו תוצאות</div>';
        return;
    }

    container.innerHTML = results.slice(0, 50).map(result => {
        const repoDisplay = showRepo && result.repo 
            ? `<span class="result-repo">${escapeHtml(result.repo)}/</span>` 
            : '';
        
        return `
            <div class="search-result-item" 
                 onclick="selectFile('${escapeJsStr(result.repo || state.currentRepo)}', '${escapeJsStr(result.path)}')">
                <div class="search-result-path">
                    ${repoDisplay}
                    <span>${escapeHtml(result.path)}</span>
                    ${result.line ? `<span class="line-num">L${result.line}</span>` : ''}
                </div>
                ${result.content ? `<div class="search-result-content">${highlightMatch(escapeHtml(result.content), query)}</div>` : ''}
            </div>
        `;
    }).join('');
}

// ========================================
// Repo Selector
// ========================================

function openRepoSelector() {
    // Show modal to add/manage repos
    const modal = document.getElementById('repo-selector-modal');
    if (modal) {
        modal.classList.remove('hidden');
        loadRepoList();
    }
}

async function loadRepoList() {
    const container = document.getElementById('repo-list');
    if (!container) return;
    
    container.innerHTML = '<div class="loading">טוען...</div>';
    
    try {
        const response = await fetch(`${CONFIG.selectorsApiBase}/`);
        const repos = await response.json();
        
        if (repos.length === 0) {
            container.innerHTML = `
                <div class="empty-state">
                    <p>אין ריפוים. הוסף ריפו ראשון!</p>
                </div>
            `;
            return;
        }
        
        container.innerHTML = repos.map(repo => `
            <div class="repo-item" data-name="${escapeHtml(repo.name)}">
                <div class="repo-info">
                    <i class="bi bi-github"></i>
                    <span class="repo-name">${escapeHtml(repo.name)}</span>
                    <span class="repo-size">${repo.size_mb || 0} MB</span>
                    <span class="sync-status ${repo.sync_status}">${repo.sync_status}</span>
                </div>
                <div class="repo-actions">
                    <button class="btn-icon" onclick="syncRepo('${escapeJsStr(repo.name)}')" title="סנכרן">
                        <i class="bi bi-arrow-repeat"></i>
                    </button>
                    <button class="btn-icon btn-danger" onclick="removeRepo('${escapeJsStr(repo.name)}')" title="הסר">
                        <i class="bi bi-trash"></i>
                    </button>
                </div>
            </div>
        `).join('');
    } catch (error) {
        console.error('Failed to load repos:', error);
        container.innerHTML = '<div class="error">שגיאה בטעינת ריפוים</div>';
    }
}

async function addRepo() {
    const urlInput = document.getElementById('new-repo-url');
    const nameInput = document.getElementById('new-repo-name');
    const url = urlInput?.value.trim();
    const name = nameInput?.value.trim() || null;
    
    if (!url) {
        showToast('יש להזין URL');
        return;
    }
    
    try {
        const response = await fetch(`${CONFIG.selectorsApiBase}/`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url, name })
        });
        
        const result = await response.json();
        
        if (result.success) {
            showToast('הריפו נוסף בהצלחה!', 'success');
            urlInput.value = '';
            nameInput.value = '';
            loadRepoList();
            initTree();  // Refresh tree
        } else {
            showToast(result.error || 'שגיאה בהוספת ריפו');
        }
    } catch (error) {
        showToast('שגיאה בהוספת ריפו');
    }
}

async function removeRepo(name) {
    if (!confirm(`האם למחוק את הריפו ${name}?`)) return;
    
    try {
        const response = await fetch(`${CONFIG.selectorsApiBase}/${encodeURIComponent(name)}`, {
            method: 'DELETE'
        });
        
        if (response.ok) {
            showToast('הריפו נמחק', 'success');
            
            // If deleted repo was selected, clear selection
            if (state.currentRepo === name) {
                state.currentRepo = null;
            }
            
            loadRepoList();
            initTree();
        }
    } catch (error) {
        showToast('שגיאה במחיקת ריפו');
    }
}

async function syncRepo(name) {
    const repoItem = document.querySelector(`.repo-item[data-name="${name}"]`);
    const syncBtn = repoItem?.querySelector('.bi-arrow-repeat');
    
    if (syncBtn) {
        syncBtn.classList.add('spinning');
    }
    
    try {
        const response = await fetch(`${CONFIG.selectorsApiBase}/${encodeURIComponent(name)}/sync`, {
            method: 'POST'
        });
        
        const result = await response.json();
        
        if (result.success) {
            showToast('הסנכרון הושלם', 'success');
        } else {
            showToast(result.error || 'שגיאה בסנכרון');
        }
        
        loadRepoList();
    } catch (error) {
        showToast('שגיאה בסנכרון');
    } finally {
        if (syncBtn) {
            syncBtn.classList.remove('spinning');
        }
    }
}
```

### 5.3 Repo History Module (מ-CodeBot)

המודול `repo-history.js` כולל:

- פאנל היסטוריה עם רשימת commits
- חיפוש בהיסטוריה (הודעות commit / קוד)
- Compare Mode - השוואת commits
- Diff viewer מתקדם

הקוד המלא קיים ב-`webapp/static/js/repo-history.js`.

---

## 6. מסד נתונים

### 6.1 MongoDB Collections

```javascript
// repos - מידע על ריפוים
{
    "_id": ObjectId("..."),
    "name": "owner_repo",
    "url": "https://github.com/owner/repo",
    "default_branch": "main",
    "created_at": ISODate("..."),
    "last_sync": ISODate("..."),
    "sync_status": "synced",  // pending, syncing, synced, error
    "last_error": null
}

// repo_files - אינדקס קבצים
{
    "_id": ObjectId("..."),
    "repo_name": "owner_repo",
    "path": "src/main.py",
    "language": "python",
    "size": 1234,
    "lines": 50,
    "functions": ["main", "helper"],  // optional
    "classes": ["MyClass"],           // optional
    "commit_sha": "abc123..."         // last indexed commit
}

// repo_metadata - מטאדאטה לכל ריפו
{
    "_id": ObjectId("..."),
    "repo_name": "owner_repo",
    "total_files": 150,
    "total_size": 1234567,
    "default_branch": "main",
    "last_sync_time": ISODate("..."),
    "file_types": {
        "python": 45,
        "javascript": 30,
        "html": 20
    }
}
```

### 6.2 Indexes

```javascript
// repos
db.repos.createIndex({ "name": 1 }, { unique: true });
db.repos.createIndex({ "sync_status": 1 });

// repo_files
db.repo_files.createIndex({ "repo_name": 1, "path": 1 }, { unique: true });
db.repo_files.createIndex({ "repo_name": 1, "language": 1 });
db.repo_files.createIndex({ "repo_name": 1 }, { background: true });

// Text index for filename search
db.repo_files.createIndex({ "path": "text" });
```

---

## 7. תכונות מרכזיות

### 7.1 דפדפון עץ קבצים

| תכונה | תיאור | מימוש |
|-------|-------|-------|
| Lazy Loading | טעינת תיקיות לפי דרישה | `api/tree?path=...` |
| File Type Filter | סינון לפי סוג קובץ | `types=python,javascript` |
| Collapse All | קיפול כל התיקיות | Client-side |
| Recent Files | קבצים אחרונים | localStorage |

### 7.2 חיפוש

| סוג חיפוש | תיאור | שירות |
|----------|-------|-------|
| Content | חיפוש בתוכן קבצים | `git grep` (מהיר!) |
| Filename | חיפוש בשמות קבצים | MongoDB regex |
| Function | חיפוש שמות פונקציות | MongoDB (pre-indexed) |
| Class | חיפוש שמות מחלקות | MongoDB (pre-indexed) |
| Cross-Repo | חיפוש בכל הריפוים | Loop over repos |

### 7.3 היסטוריה ו-Diff

| תכונה | תיאור | API |
|-------|-------|-----|
| File History | היסטוריית commits לקובץ | `/api/history?file=...` |
| File at Commit | תוכן קובץ ב-commit ספציפי | `/api/file-at-commit/<commit>` |
| Diff | השוואת commits | `/api/diff/<c1>/<c2>` |
| Search History | חיפוש בהודעות/קוד | `/api/search-history` |
| Compare Mode | השוואת 2 commits שנבחרו | Client-side |

### 7.4 צפייה בקוד

| תכונה | תיאור | טכנולוגיה |
|-------|-------|----------|
| Syntax Highlighting | צביעת תחביר | CodeMirror 5/6 |
| Line Numbers | מספרי שורות | CodeMirror |
| Code Folding | קיפול קוד | CodeMirror addon |
| In-file Search | חיפוש בקובץ (Ctrl+F) | Custom + CM |
| Copy Content | העתקת תוכן | Clipboard API |

---

## 8. אבטחה

### 8.1 וולידציות קריטיות (מ-CodeBot)

```python
# GitMirrorService - וולידציות

# שם ריפו: a-z, 0-9, -, _ בלבד
REPO_NAME_PATTERN = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9_-]{0,99}$')

# נתיב קובץ - מניעת path traversal
FILE_PATH_PATTERN = re.compile(
    r'^(?!.*//)'              # No //
    r'(?!/)'                 # No leading /
    r'(?!-)'                 # No leading '-' (avoid git flags)
    r'(?!.*\x00)'            # No NUL
    r'[a-zA-Z0-9._/-]+'      # Allowed chars
    r'(?<!/)'                # No trailing /
    r'$'
)

def _validate_repo_file_path(self, file_path: str) -> bool:
    """וולידציה של נתיב קובץ - מונע path traversal"""
    if not file_path or '\x00' in file_path:
        return False
    if file_path.startswith('-'):
        return False
    
    # Normalize and check for traversal
    normalized = os.path.normpath(file_path)
    if normalized == '..' or normalized.startswith('..' + os.sep):
        return False
    if normalized.startswith('/'):
        return False
        
    return bool(self.FILE_PATH_PATTERN.match(file_path))
```

### 8.2 הגנות נוספות

1. **Token Handling**
   - טוקנים לא נרשמים ללוגים
   - Sanitization של פלט Git

2. **Safe Delete**
   - מחיקה רק תחת base_path
   - בדיקת נתיבים מסוכנים (/, ., cwd)

3. **XSS Prevention (Frontend)**
   ```javascript
   function escapeHtml(text) {
       return String(text)
           .replace(/&/g, "&amp;")
           .replace(/</g, "&lt;")
           .replace(/>/g, "&gt;")
           .replace(/"/g, "&quot;")
           .replace(/'/g, "&#039;");
   }
   ```

4. **Rate Limiting** (מומלץ להוסיף)
   - הגבלת בקשות API
   - הגבלת גודל חיפוש

---

## 9. ביצועים ואופטימיזציות

### 9.1 Git Operations

1. **Bare Mirror**
   - `git clone --mirror` - חוסך מקום
   - `git fetch --all --prune` - עדכון delta בלבד

2. **Streaming git grep**
   - קריאת תוצאות שורה-שורה
   - עצירה מוקדמת כשמגיעים ל-max_results
   - מונע חריגת זיכרון

3. **Timeout על פקודות Git**
   - ברירת מחדל: 30 שניות
   - Clone: 10 דקות
   - Search: 10 שניות

### 9.2 MongoDB

1. **Smart Projection**
   - לא מושכים תוכן בשאילתות רשימה
   - `{"path": 1, "language": 1, "size": 1}`

2. **Indexes**
   - Compound index על `repo_name` + `path`
   - Text index לחיפוש שמות קבצים

3. **Batch Operations**
   - `insert_many` לאינדוקס קבצים

### 9.3 Frontend

1. **Lazy Loading**
   - טעינת עץ לפי דרישה
   - Debounce על חיפוש

2. **AbortController**
   - ביטול בקשות קודמות
   - מניעת race conditions

3. **localStorage**
   - שמירת קבצים אחרונים
   - שמירת העדפות פילטר

---

## 10. הגדרות והתקנה

### 10.1 Dependencies

```txt
# requirements.txt

flask>=2.0
pymongo>=4.0
python-dotenv>=0.19

# Optional
gunicorn>=20.1  # Production server
```

### 10.2 Environment Variables

```bash
# .env

# MongoDB
MONGODB_URI=mongodb://localhost:27017/multi_repo_browser

# Git Mirror Storage
REPO_MIRROR_PATH=/var/data/repos

# GitHub (for private repos)
GITHUB_TOKEN=ghp_...

# Flask
FLASK_SECRET_KEY=your-secret-key
FLASK_ENV=development
```

### 10.3 התקנה מהירה

```bash
# 1. Clone הפרויקט
git clone https://github.com/your/multi-repo-browser
cd multi-repo-browser

# 2. יצירת virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
# או: venv\Scripts\activate  # Windows

# 3. התקנת dependencies
pip install -r requirements.txt

# 4. הגדרת סביבה
cp .env.example .env
# ערוך את .env עם הערכים שלך

# 5. יצירת תיקיות
mkdir -p /var/data/repos

# 6. הרצה
flask run --debug
```

### 10.4 Docker (אופציונלי)

```dockerfile
# Dockerfile
FROM python:3.11-slim

# Install git
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Create repos directory
RUN mkdir -p /var/data/repos

EXPOSE 5000

CMD ["gunicorn", "-b", "0.0.0.0:5000", "app:app"]
```

```yaml
# docker-compose.yml
version: '3.8'

services:
  app:
    build: .
    ports:
      - "5000:5000"
    environment:
      - MONGODB_URI=mongodb://mongo:27017/multi_repo_browser
      - REPO_MIRROR_PATH=/var/data/repos
    volumes:
      - repos_data:/var/data/repos
    depends_on:
      - mongo

  mongo:
    image: mongo:6
    volumes:
      - mongo_data:/data/db

volumes:
  repos_data:
  mongo_data:
```

---

## 🎯 סיכום

הפרויקט מבוסס על הארכיטקטורה המוכחת של CodeBot, עם הרחבות ל:

1. **ניהול ריפוים מרובים** - הוספה/הסרה/סנכרון
2. **חיפוש גלובלי** - חיפוש בכל הריפוים במקביל
3. **UI מותאם** - בחירת ריפו, עץ מאוחד

הקוד המרכזי (`GitMirrorService`, `RepoSearchService`) כבר קיים ב-CodeBot ומוכן לשימוש - צריך רק להוסיף את שכבת ה-Multi-Repo מעליו.

---

**קישורים:**
- [CodeBot Docs](https://amirbiron.github.io/CodeBot/)
- קוד מקור: `services/git_mirror_service.py`, `services/repo_search_service.py`
- Templates: `webapp/templates/repo/`
- Static: `webapp/static/js/repo-browser.js`, `webapp/static/js/repo-history.js`
