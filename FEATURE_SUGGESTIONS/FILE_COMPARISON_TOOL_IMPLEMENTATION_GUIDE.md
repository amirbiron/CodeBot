# מדריך מימוש: כלי השוואת קבצים (File Comparison Tool)

> **גרסה:** 1.0.0  
> **תאריך:** דצמבר 2025  
> **מטרה:** מימוש מערכת השוואת קבצים מתקדמת לבוט ול-WebApp

---

## 📖 תוכן עניינים

1. [סקירה כללית](#סקירה-כללית)
2. [ארכיטקטורה מוצעת](#ארכיטקטורה-מוצעת)
3. [שלב 1: Backend Service](#שלב-1-backend-service)
4. [שלב 2: API Endpoints](#שלב-2-api-endpoints)
5. [שלב 3: WebApp UI](#שלב-3-webapp-ui)
6. [שלב 4: Telegram Bot Integration](#שלב-4-telegram-bot-integration)
7. [שלב 5: מצבי תצוגה (Display Modes)](#שלב-5-מצבי-תצוגה)
8. [שלב 6: תכונות מתקדמות](#שלב-6-תכונות-מתקדמות)
9. [בדיקות](#בדיקות)
10. [משימות לפי סדר עדיפות](#משימות-לפי-סדר-עדיפות)

---

## סקירה כללית

### מה זה?

כלי להשוואה בין:
- **שתי גרסאות של אותו קובץ** (היסטוריית גרסאות קיימת)
- **שני קבצים שונים** של אותו משתמש
- **קובץ לקלט חיצוני** (טקסט שהודבק)

### למה זה חשוב?

1. **זיהוי שינויים** - מה השתנה בין גרסאות
2. **הבנת התפתחות הקוד** - מעקב אחר שינויים לאורך זמן
3. **Merge קוד** - שילוב שינויים מגרסאות שונות
4. **Code Review** - השוואה לפני אישור שינויים

### תאימות לקוד קיים

הפיצ'ר נשען על תשתיות קיימות:
- `database/repository.py` → `get_all_versions()`, `get_version()`
- `webapp/app.py` → תשתית Flask ו-API קיימת
- `pygments` → Syntax highlighting
- `CodeMirror` → עורך קוד ב-WebApp

---

## ארכיטקטורה מוצעת

```
┌─────────────────────────────────────────────────────────────────┐
│                        Presentation Layer                        │
├─────────────────────────────────────────────────────────────────┤
│  WebApp UI                    │  Telegram Bot                    │
│  ├── /compare/<file_id>       │  ├── /compare <filename>        │
│  ├── /compare?left=X&right=Y  │  ├── כפתור "השווה גרסאות"       │
│  └── Split View / Unified     │  └── תצוגת diff בהודעה          │
├─────────────────────────────────────────────────────────────────┤
│                          API Layer                               │
├─────────────────────────────────────────────────────────────────┤
│  /api/compare/versions/<file_id>                                │
│  /api/compare/files                                              │
│  /api/compare/diff                                               │
├─────────────────────────────────────────────────────────────────┤
│                        Service Layer                             │
├─────────────────────────────────────────────────────────────────┤
│  services/diff_service.py                                        │
│  ├── compute_diff()                                              │
│  ├── format_side_by_side()                                       │
│  ├── format_unified()                                            │
│  └── merge_changes()                                             │
├─────────────────────────────────────────────────────────────────┤
│                        Data Layer                                │
├─────────────────────────────────────────────────────────────────┤
│  database/repository.py                                          │
│  ├── get_all_versions() ✓ (קיים)                                │
│  ├── get_version() ✓ (קיים)                                     │
│  └── get_file_by_id() ✓ (קיים)                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## שלב 1: Backend Service

### קובץ חדש: `services/diff_service.py`

```python
"""
Diff Service - שירות השוואת קבצים
"""

import difflib
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Dict, Any, Tuple
import re

class DiffMode(Enum):
    """מצבי תצוגת ההשוואה"""
    UNIFIED = "unified"         # תצוגה אחודה (כמו git diff)
    SIDE_BY_SIDE = "side_by_side"  # תצוגה צד-לצד
    INLINE = "inline"           # הדגשה inline בתוך הטקסט


@dataclass
class DiffLine:
    """שורה בודדת בתוצאת ההשוואה"""
    line_num_left: Optional[int] = None
    line_num_right: Optional[int] = None
    content_left: Optional[str] = None
    content_right: Optional[str] = None
    change_type: str = "unchanged"  # unchanged, added, removed, modified
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "line_num_left": self.line_num_left,
            "line_num_right": self.line_num_right,
            "content_left": self.content_left,
            "content_right": self.content_right,
            "change_type": self.change_type,
        }


@dataclass
class DiffResult:
    """תוצאת השוואה מלאה"""
    lines: List[DiffLine] = field(default_factory=list)
    stats: Dict[str, int] = field(default_factory=dict)
    left_info: Dict[str, Any] = field(default_factory=dict)
    right_info: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "lines": [line.to_dict() for line in self.lines],
            "stats": self.stats,
            "left_info": self.left_info,
            "right_info": self.right_info,
        }


class DiffService:
    """שירות להשוואת קבצים וגרסאות"""
    
    def __init__(self, db_manager=None):
        self.db = db_manager
    
    def compute_diff(
        self,
        left_content: str,
        right_content: str,
        context_lines: int = 3,
    ) -> DiffResult:
        """
        חישוב ההבדלים בין שני טקסטים.
        
        Args:
            left_content: תוכן הקובץ השמאלי (ישן/מקורי)
            right_content: תוכן הקובץ הימני (חדש/משונה)
            context_lines: מספר שורות הקשר סביב שינויים
            
        Returns:
            DiffResult עם כל פרטי ההשוואה
        """
        left_lines = left_content.splitlines(keepends=True)
        right_lines = right_content.splitlines(keepends=True)
        
        # שימוש ב-difflib לחישוב ההבדלים
        matcher = difflib.SequenceMatcher(None, left_lines, right_lines)
        
        result_lines: List[DiffLine] = []
        stats = {"added": 0, "removed": 0, "modified": 0, "unchanged": 0}
        
        left_idx = 0
        right_idx = 0
        
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal":
                for i, j in zip(range(i1, i2), range(j1, j2)):
                    result_lines.append(DiffLine(
                        line_num_left=i + 1,
                        line_num_right=j + 1,
                        content_left=left_lines[i].rstrip('\n\r'),
                        content_right=right_lines[j].rstrip('\n\r'),
                        change_type="unchanged",
                    ))
                    stats["unchanged"] += 1
                    
            elif tag == "replace":
                # שורות שונות - נציג אותן כ-modified
                max_len = max(i2 - i1, j2 - j1)
                for k in range(max_len):
                    left_i = i1 + k if i1 + k < i2 else None
                    right_j = j1 + k if j1 + k < j2 else None
                    
                    result_lines.append(DiffLine(
                        line_num_left=(left_i + 1) if left_i is not None else None,
                        line_num_right=(right_j + 1) if right_j is not None else None,
                        content_left=left_lines[left_i].rstrip('\n\r') if left_i is not None else None,
                        content_right=right_lines[right_j].rstrip('\n\r') if right_j is not None else None,
                        change_type="modified",
                    ))
                    stats["modified"] += 1
                    
            elif tag == "delete":
                for i in range(i1, i2):
                    result_lines.append(DiffLine(
                        line_num_left=i + 1,
                        line_num_right=None,
                        content_left=left_lines[i].rstrip('\n\r'),
                        content_right=None,
                        change_type="removed",
                    ))
                    stats["removed"] += 1
                    
            elif tag == "insert":
                for j in range(j1, j2):
                    result_lines.append(DiffLine(
                        line_num_left=None,
                        line_num_right=j + 1,
                        content_left=None,
                        content_right=right_lines[j].rstrip('\n\r'),
                        change_type="added",
                    ))
                    stats["added"] += 1
        
        return DiffResult(
            lines=result_lines,
            stats=stats,
            left_info={"total_lines": len(left_lines)},
            right_info={"total_lines": len(right_lines)},
        )
    
    def compare_versions(
        self,
        user_id: int,
        file_name: str,
        version_left: int,
        version_right: int,
    ) -> Optional[DiffResult]:
        """
        השוואה בין שתי גרסאות של אותו קובץ.
        
        Args:
            user_id: מזהה המשתמש
            file_name: שם הקובץ
            version_left: מספר הגרסה השמאלית (ישנה)
            version_right: מספר הגרסה הימנית (חדשה)
            
        Returns:
            DiffResult או None אם לא נמצאו הגרסאות
        """
        if self.db is None:
            return None
            
        left_doc = self.db.get_version(user_id, file_name, version_left)
        right_doc = self.db.get_version(user_id, file_name, version_right)
        
        if not left_doc or not right_doc:
            return None
        
        left_content = left_doc.get("code", "")
        right_content = right_doc.get("code", "")
        
        result = self.compute_diff(left_content, right_content)
        
        # הוספת מטאדאטה על הגרסאות
        result.left_info.update({
            "version": version_left,
            "file_name": file_name,
            "updated_at": str(left_doc.get("updated_at", "")),
            "file_id": str(left_doc.get("_id", "")),
        })
        result.right_info.update({
            "version": version_right,
            "file_name": file_name,
            "updated_at": str(right_doc.get("updated_at", "")),
            "file_id": str(right_doc.get("_id", "")),
        })
        
        return result
    
    def compare_files(
        self,
        user_id: int,
        file_id_left: str,
        file_id_right: str,
    ) -> Optional[DiffResult]:
        """
        השוואה בין שני קבצים שונים.
        
        Args:
            user_id: מזהה המשתמש
            file_id_left: מזהה הקובץ השמאלי
            file_id_right: מזהה הקובץ הימני
            
        Returns:
            DiffResult או None אם לא נמצאו הקבצים
        """
        if self.db is None:
            return None
        
        left_doc = self.db.get_file_by_id(file_id_left)
        right_doc = self.db.get_file_by_id(file_id_right)
        
        if not left_doc or not right_doc:
            return None
        
        # וידוא שהקבצים שייכים למשתמש
        if left_doc.get("user_id") != user_id or right_doc.get("user_id") != user_id:
            return None
        
        left_content = left_doc.get("code", "")
        right_content = right_doc.get("code", "")
        
        result = self.compute_diff(left_content, right_content)
        
        # הוספת מטאדאטה על הקבצים
        result.left_info.update({
            "file_name": left_doc.get("file_name", ""),
            "file_id": file_id_left,
            "programming_language": left_doc.get("programming_language", ""),
            "version": left_doc.get("version", 1),
        })
        result.right_info.update({
            "file_name": right_doc.get("file_name", ""),
            "file_id": file_id_right,
            "programming_language": right_doc.get("programming_language", ""),
            "version": right_doc.get("version", 1),
        })
        
        return result
    
    def format_unified_diff(
        self,
        diff_result: DiffResult,
        context_lines: int = 3,
    ) -> str:
        """
        פורמט unified diff (כמו git diff).
        
        Returns:
            מחרוזת בפורמט unified diff
        """
        left_name = diff_result.left_info.get("file_name", "left")
        right_name = diff_result.right_info.get("file_name", "right")
        
        output_lines = [
            f"--- {left_name}",
            f"+++ {right_name}",
        ]
        
        # קיבוץ שינויים ל-hunks
        current_hunk = []
        hunk_start_left = None
        hunk_start_right = None
        
        for line in diff_result.lines:
            if line.change_type == "unchanged":
                if current_hunk:
                    current_hunk.append(f" {line.content_left or ''}")
                continue
            
            if hunk_start_left is None:
                hunk_start_left = line.line_num_left or 1
                hunk_start_right = line.line_num_right or 1
            
            if line.change_type == "removed":
                current_hunk.append(f"-{line.content_left or ''}")
            elif line.change_type == "added":
                current_hunk.append(f"+{line.content_right or ''}")
            elif line.change_type == "modified":
                if line.content_left:
                    current_hunk.append(f"-{line.content_left}")
                if line.content_right:
                    current_hunk.append(f"+{line.content_right}")
        
        if current_hunk:
            hunk_header = f"@@ -{hunk_start_left},? +{hunk_start_right},? @@"
            output_lines.append(hunk_header)
            output_lines.extend(current_hunk)
        
        return "\n".join(output_lines)
    
    def format_for_telegram(
        self,
        diff_result: DiffResult,
        max_lines: int = 50,
    ) -> str:
        """
        פורמט מותאם לתצוגה בטלגרם.
        
        Args:
            diff_result: תוצאת ההשוואה
            max_lines: מספר שורות מקסימלי להצגה
            
        Returns:
            מחרוזת מעוצבת לטלגרם
        """
        stats = diff_result.stats
        
        header = (
            f"📊 **סיכום השוואה**\n"
            f"➕ נוספו: {stats.get('added', 0)} שורות\n"
            f"➖ נמחקו: {stats.get('removed', 0)} שורות\n"
            f"🔄 שונו: {stats.get('modified', 0)} שורות\n"
            f"━━━━━━━━━━━━━━━━\n"
        )
        
        changes = []
        shown = 0
        
        for line in diff_result.lines:
            if shown >= max_lines:
                changes.append(f"\n... ועוד {len(diff_result.lines) - shown} שורות")
                break
            
            if line.change_type == "added":
                changes.append(f"+ {line.content_right}")
                shown += 1
            elif line.change_type == "removed":
                changes.append(f"- {line.content_left}")
                shown += 1
            elif line.change_type == "modified":
                changes.append(f"- {line.content_left}")
                changes.append(f"+ {line.content_right}")
                shown += 2
        
        if not changes:
            return header + "✅ הקבצים זהים - אין שינויים"
        
        return header + "```diff\n" + "\n".join(changes) + "\n```"


# Singleton instance
_diff_service: Optional[DiffService] = None


def get_diff_service(db_manager=None) -> DiffService:
    """קבלת instance של שירות ההשוואה."""
    global _diff_service
    if _diff_service is None:
        _diff_service = DiffService(db_manager)
    return _diff_service
```

---

## שלב 2: API Endpoints

### הוספה ל-`webapp/app.py` או קובץ חדש `webapp/compare_api.py`

```python
"""
Compare API - API להשוואת קבצים
נוסף ל-webapp/app.py או כקובץ נפרד עם Blueprint
"""

from flask import Blueprint, jsonify, request, render_template, abort
from services.diff_service import get_diff_service, DiffMode

# אם משתמשים ב-Blueprint:
compare_bp = Blueprint('compare', __name__, url_prefix='/api/compare')


@compare_bp.route('/versions/<file_id>', methods=['GET'])
def compare_versions(file_id: str):
    """
    השוואה בין גרסאות של קובץ.
    
    Query params:
        - left: מספר גרסה שמאלית (ברירת מחדל: גרסה אחרונה - 1)
        - right: מספר גרסה ימנית (ברירת מחדל: גרסה אחרונה)
        
    Returns:
        JSON עם תוצאת ההשוואה
    """
    user_id = get_current_user_id()  # פונקציה קיימת ב-app.py
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 401
    
    # קבלת הקובץ לפי ID
    file_doc = db.get_file_by_id(file_id)
    if not file_doc:
        return jsonify({"error": "File not found"}), 404
    
    if file_doc.get("user_id") != user_id:
        return jsonify({"error": "Forbidden"}), 403
    
    file_name = file_doc.get("file_name")
    current_version = file_doc.get("version", 1)
    
    # קבלת פרמטרים
    version_left = request.args.get('left', type=int, default=max(1, current_version - 1))
    version_right = request.args.get('right', type=int, default=current_version)
    
    # חישוב ההשוואה
    diff_service = get_diff_service(db)
    result = diff_service.compare_versions(user_id, file_name, version_left, version_right)
    
    if not result:
        return jsonify({"error": "Could not compare versions"}), 400
    
    return jsonify(result.to_dict())


@compare_bp.route('/files', methods=['POST'])
def compare_files():
    """
    השוואה בין שני קבצים שונים.
    
    Body (JSON):
        - left_file_id: מזהה קובץ שמאלי
        - right_file_id: מזהה קובץ ימני
        
    Returns:
        JSON עם תוצאת ההשוואה
    """
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 401
    
    data = request.get_json() or {}
    left_id = data.get('left_file_id')
    right_id = data.get('right_file_id')
    
    if not left_id or not right_id:
        return jsonify({"error": "Missing file IDs"}), 400
    
    diff_service = get_diff_service(db)
    result = diff_service.compare_files(user_id, left_id, right_id)
    
    if not result:
        return jsonify({"error": "Could not compare files"}), 400
    
    return jsonify(result.to_dict())


@compare_bp.route('/diff', methods=['POST'])
def compare_raw():
    """
    השוואה בין שני טקסטים גולמיים.
    
    Body (JSON):
        - left_content: תוכן שמאלי
        - right_content: תוכן ימני
        
    Returns:
        JSON עם תוצאת ההשוואה
    """
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 401
    
    data = request.get_json() or {}
    left_content = data.get('left_content', '')
    right_content = data.get('right_content', '')
    
    diff_service = get_diff_service()
    result = diff_service.compute_diff(left_content, right_content)
    
    return jsonify(result.to_dict())


# רישום ה-Blueprint ב-app.py:
# app.register_blueprint(compare_bp)
```

### הוספת Routes לדפי UI

```python
# הוספה ל-webapp/app.py

@app.route('/compare/<file_id>')
@login_required
def compare_versions_page(file_id: str):
    """דף השוואת גרסאות של קובץ."""
    user_id = get_current_user_id()
    
    file_doc = db.get_file_by_id(file_id)
    if not file_doc or file_doc.get("user_id") != user_id:
        abort(404)
    
    # קבלת כל הגרסאות
    all_versions = db.get_all_versions(user_id, file_doc.get("file_name"))
    
    return render_template(
        'compare.html',
        file=file_doc,
        versions=all_versions,
        current_version=file_doc.get("version", 1),
    )


@app.route('/compare')
@login_required
def compare_files_page():
    """דף השוואת קבצים שונים."""
    user_id = get_current_user_id()
    
    left_id = request.args.get('left')
    right_id = request.args.get('right')
    
    # קבלת רשימת הקבצים לבחירה
    user_files = db.get_user_files(user_id, limit=100)
    
    return render_template(
        'compare_files.html',
        files=user_files,
        selected_left=left_id,
        selected_right=right_id,
    )
```

---

## שלב 3: WebApp UI

### קובץ תבנית: `webapp/templates/compare.html`

```html
{% extends "base.html" %}

{% block title %}השוואת גרסאות - {{ file.file_name }}{% endblock %}

{% block extra_css %}
<link rel="stylesheet" href="{{ url_for('static', filename='css/compare.css') }}">
{% endblock %}

{% block content %}
<div class="container-fluid py-4">
    <!-- כותרת -->
    <div class="compare-header glass-card p-4 mb-4">
        <div class="d-flex justify-content-between align-items-center flex-wrap gap-3">
            <div>
                <h1 class="h3 mb-2">
                    <i class="fas fa-code-compare me-2"></i>
                    השוואת גרסאות: {{ file.file_name }}
                </h1>
                <p class="text-muted mb-0">בחר גרסאות להשוואה</p>
            </div>
            
            <!-- בקרות תצוגה -->
            <div class="btn-group" role="group" aria-label="מצב תצוגה">
                <button type="button" class="btn btn-outline-primary active" data-mode="side-by-side">
                    <i class="fas fa-columns"></i> צד לצד
                </button>
                <button type="button" class="btn btn-outline-primary" data-mode="unified">
                    <i class="fas fa-align-left"></i> אחיד
                </button>
                <button type="button" class="btn btn-outline-primary" data-mode="inline">
                    <i class="fas fa-highlighter"></i> Inline
                </button>
            </div>
        </div>
        
        <!-- בחירת גרסאות -->
        <div class="row mt-4">
            <div class="col-md-5">
                <label class="form-label">גרסה שמאלית (ישנה)</label>
                <select id="version-left" class="form-select">
                    {% for v in versions %}
                    <option value="{{ v.version }}" 
                            {% if v.version == current_version - 1 %}selected{% endif %}>
                        גרסה {{ v.version }} - {{ v.updated_at | format_datetime }}
                    </option>
                    {% endfor %}
                </select>
            </div>
            <div class="col-md-2 d-flex align-items-end justify-content-center">
                <button id="swap-versions" class="btn btn-secondary" title="החלף">
                    <i class="fas fa-exchange-alt"></i>
                </button>
            </div>
            <div class="col-md-5">
                <label class="form-label">גרסה ימנית (חדשה)</label>
                <select id="version-right" class="form-select">
                    {% for v in versions %}
                    <option value="{{ v.version }}"
                            {% if v.version == current_version %}selected{% endif %}>
                        גרסה {{ v.version }} - {{ v.updated_at | format_datetime }}
                    </option>
                    {% endfor %}
                </select>
            </div>
        </div>
    </div>
    
    <!-- סטטיסטיקות -->
    <div class="stats-bar glass-card p-3 mb-4">
        <div class="row text-center">
            <div class="col">
                <span class="badge bg-success fs-6" id="stat-added">
                    <i class="fas fa-plus"></i> +<span>0</span>
                </span>
            </div>
            <div class="col">
                <span class="badge bg-danger fs-6" id="stat-removed">
                    <i class="fas fa-minus"></i> -<span>0</span>
                </span>
            </div>
            <div class="col">
                <span class="badge bg-warning fs-6" id="stat-modified">
                    <i class="fas fa-pen"></i> ~<span>0</span>
                </span>
            </div>
            <div class="col">
                <span class="badge bg-secondary fs-6" id="stat-unchanged">
                    <i class="fas fa-equals"></i> =<span>0</span>
                </span>
            </div>
        </div>
    </div>
    
    <!-- אזור ההשוואה -->
    <div id="diff-container" class="diff-container glass-card">
        <!-- Side by Side View -->
        <div id="side-by-side-view" class="diff-view active">
            <div class="diff-pane left-pane">
                <div class="pane-header">
                    <span class="version-label">גרסה <span id="left-version-label"></span></span>
                </div>
                <div class="pane-content" id="left-content"></div>
            </div>
            <div class="diff-pane right-pane">
                <div class="pane-header">
                    <span class="version-label">גרסה <span id="right-version-label"></span></span>
                </div>
                <div class="pane-content" id="right-content"></div>
            </div>
        </div>
        
        <!-- Unified View -->
        <div id="unified-view" class="diff-view">
            <div class="unified-content" id="unified-content"></div>
        </div>
        
        <!-- Inline View -->
        <div id="inline-view" class="diff-view">
            <div class="inline-content" id="inline-content"></div>
        </div>
    </div>
    
    <!-- כפתורי פעולה -->
    <div class="action-bar glass-card p-3 mt-4">
        <div class="d-flex justify-content-between align-items-center flex-wrap gap-2">
            <a href="{{ url_for('view_file', file_id=file._id) }}" class="btn btn-secondary">
                <i class="fas fa-arrow-left"></i> חזור לקובץ
            </a>
            <div class="d-flex gap-2">
                <button id="btn-copy-diff" class="btn btn-outline-primary">
                    <i class="fas fa-copy"></i> העתק Diff
                </button>
                <button id="btn-download-diff" class="btn btn-outline-primary">
                    <i class="fas fa-download"></i> הורד Patch
                </button>
                <button id="btn-restore" class="btn btn-warning" data-bs-toggle="modal" data-bs-target="#restoreModal">
                    <i class="fas fa-history"></i> שחזר גרסה
                </button>
            </div>
        </div>
    </div>
</div>

<!-- Modal שחזור גרסה -->
<div class="modal fade" id="restoreModal" tabindex="-1">
    <div class="modal-dialog">
        <div class="modal-content glass-card">
            <div class="modal-header">
                <h5 class="modal-title">שחזור גרסה</h5>
                <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
            </div>
            <div class="modal-body">
                <p>האם לשחזר את הקובץ לגרסה <strong id="restore-version"></strong>?</p>
                <p class="text-warning">
                    <i class="fas fa-exclamation-triangle"></i>
                    פעולה זו תיצור גרסה חדשה עם התוכן של הגרסה הנבחרת.
                </p>
            </div>
            <div class="modal-footer">
                <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">ביטול</button>
                <button type="button" class="btn btn-warning" id="confirm-restore">
                    <i class="fas fa-check"></i> שחזר
                </button>
            </div>
        </div>
    </div>
</div>
{% endblock %}

{% block extra_js %}
<script src="{{ url_for('static', filename='js/compare.js') }}"></script>
<script>
    // אתחול עם נתוני הקובץ
    window.CompareView.init({
        fileId: '{{ file._id }}',
        fileName: '{{ file.file_name }}',
        language: '{{ file.programming_language }}',
        currentVersion: {{ current_version }},
    });
</script>
{% endblock %}
```

### קובץ CSS: `webapp/static/css/compare.css`

```css
/* =================================================================
   Compare View Styles - סגנונות תצוגת השוואה
   ================================================================= */

/* Container */
.diff-container {
    min-height: 400px;
    overflow: hidden;
    border-radius: 12px;
}

/* Views */
.diff-view {
    display: none;
}

.diff-view.active {
    display: flex;
}

/* Side by Side */
#side-by-side-view {
    display: none;
}

#side-by-side-view.active {
    display: flex;
    gap: 2px;
}

.diff-pane {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    background: var(--glass-bg, rgba(30, 30, 30, 0.8));
}

.pane-header {
    padding: 0.75rem 1rem;
    background: rgba(255, 255, 255, 0.05);
    border-bottom: 1px solid rgba(255, 255, 255, 0.1);
    font-weight: 600;
}

.left-pane .pane-header {
    border-left: 3px solid var(--bs-danger);
}

.right-pane .pane-header {
    border-left: 3px solid var(--bs-success);
}

.pane-content {
    flex: 1;
    overflow: auto;
    font-family: 'Fira Code', 'Consolas', monospace;
    font-size: 13px;
    line-height: 1.6;
    direction: ltr;
    text-align: left;
}

/* Diff Lines */
.diff-line {
    display: flex;
    min-height: 24px;
    padding: 0 0.5rem;
    border-bottom: 1px solid rgba(255, 255, 255, 0.03);
}

.diff-line:hover {
    background: rgba(255, 255, 255, 0.05);
}

.line-number {
    width: 50px;
    min-width: 50px;
    padding-right: 0.5rem;
    text-align: right;
    color: rgba(255, 255, 255, 0.4);
    user-select: none;
    border-right: 1px solid rgba(255, 255, 255, 0.1);
}

.line-content {
    flex: 1;
    padding-left: 0.5rem;
    white-space: pre-wrap;
    word-break: break-all;
}

/* Change Types */
.diff-line.added {
    background: rgba(40, 167, 69, 0.15);
}

.diff-line.added .line-content::before {
    content: '+';
    color: var(--bs-success);
    margin-right: 0.25rem;
}

.diff-line.removed {
    background: rgba(220, 53, 69, 0.15);
}

.diff-line.removed .line-content::before {
    content: '-';
    color: var(--bs-danger);
    margin-right: 0.25rem;
}

.diff-line.modified {
    background: rgba(255, 193, 7, 0.1);
}

.diff-line.empty {
    background: rgba(128, 128, 128, 0.1);
}

/* Unified View */
#unified-view {
    flex-direction: column;
}

.unified-content {
    padding: 1rem;
    font-family: 'Fira Code', 'Consolas', monospace;
    font-size: 13px;
    line-height: 1.6;
    direction: ltr;
    text-align: left;
    overflow: auto;
}

.unified-line {
    display: flex;
    padding: 2px 0.5rem;
}

.unified-line .line-numbers {
    width: 100px;
    min-width: 100px;
    display: flex;
    gap: 0.5rem;
    color: rgba(255, 255, 255, 0.4);
    user-select: none;
}

.unified-line .line-numbers span {
    width: 45px;
    text-align: right;
}

/* Inline View */
#inline-view {
    flex-direction: column;
}

.inline-content {
    padding: 1rem;
    font-family: 'Fira Code', 'Consolas', monospace;
    font-size: 13px;
    line-height: 1.6;
    direction: ltr;
    text-align: left;
    overflow: auto;
}

/* Inline highlights */
.inline-added {
    background: rgba(40, 167, 69, 0.3);
    border-radius: 2px;
    padding: 0 2px;
}

.inline-removed {
    background: rgba(220, 53, 69, 0.3);
    text-decoration: line-through;
    border-radius: 2px;
    padding: 0 2px;
}

/* Stats Bar */
.stats-bar .badge {
    min-width: 80px;
}

/* Responsive */
@media (max-width: 768px) {
    #side-by-side-view.active {
        flex-direction: column;
    }
    
    .diff-pane {
        max-height: 300px;
    }
    
    .pane-content {
        font-size: 11px;
    }
    
    .line-number {
        width: 35px;
        min-width: 35px;
        font-size: 10px;
    }
}

/* Dark/Light Theme Support */
[data-theme="light"] .diff-container,
[data-theme="light"] .diff-pane {
    background: rgba(255, 255, 255, 0.9);
}

[data-theme="light"] .line-number {
    color: rgba(0, 0, 0, 0.4);
    border-right-color: rgba(0, 0, 0, 0.1);
}

[data-theme="light"] .diff-line {
    border-bottom-color: rgba(0, 0, 0, 0.05);
}

[data-theme="light"] .diff-line:hover {
    background: rgba(0, 0, 0, 0.03);
}

/* Scrollbar sync indicator */
.scroll-synced {
    position: absolute;
    top: 0.5rem;
    right: 0.5rem;
    font-size: 0.75rem;
    color: var(--bs-success);
    opacity: 0;
    transition: opacity 0.3s;
}

.scroll-synced.active {
    opacity: 1;
}

/* Mini-map (optional future feature) */
.diff-minimap {
    position: absolute;
    right: 0;
    top: 0;
    bottom: 0;
    width: 60px;
    background: rgba(0, 0, 0, 0.2);
    overflow: hidden;
}

.minimap-change {
    position: absolute;
    left: 0;
    right: 0;
    height: 2px;
}

.minimap-change.added {
    background: var(--bs-success);
}

.minimap-change.removed {
    background: var(--bs-danger);
}

.minimap-change.modified {
    background: var(--bs-warning);
}
```

### קובץ JavaScript: `webapp/static/js/compare.js`

```javascript
/**
 * Compare View - מודול השוואת קבצים
 */

window.CompareView = (function() {
    'use strict';

    // State
    let state = {
        fileId: null,
        fileName: null,
        language: 'text',
        currentVersion: 1,
        leftVersion: null,
        rightVersion: null,
        diffData: null,
        viewMode: 'side-by-side', // side-by-side, unified, inline
        syncScroll: true,
    };

    // DOM Elements
    let elements = {};

    /**
     * אתחול המודול
     */
    function init(config) {
        Object.assign(state, config);
        state.leftVersion = Math.max(1, state.currentVersion - 1);
        state.rightVersion = state.currentVersion;

        cacheElements();
        bindEvents();
        loadDiff();
    }

    /**
     * שמירת הפניות ל-DOM elements
     */
    function cacheElements() {
        elements = {
            versionLeft: document.getElementById('version-left'),
            versionRight: document.getElementById('version-right'),
            swapBtn: document.getElementById('swap-versions'),
            modeButtons: document.querySelectorAll('[data-mode]'),
            
            // Views
            sideBySideView: document.getElementById('side-by-side-view'),
            unifiedView: document.getElementById('unified-view'),
            inlineView: document.getElementById('inline-view'),
            
            // Content containers
            leftContent: document.getElementById('left-content'),
            rightContent: document.getElementById('right-content'),
            unifiedContent: document.getElementById('unified-content'),
            inlineContent: document.getElementById('inline-content'),
            
            // Labels
            leftVersionLabel: document.getElementById('left-version-label'),
            rightVersionLabel: document.getElementById('right-version-label'),
            
            // Stats
            statAdded: document.querySelector('#stat-added span'),
            statRemoved: document.querySelector('#stat-removed span'),
            statModified: document.querySelector('#stat-modified span'),
            statUnchanged: document.querySelector('#stat-unchanged span'),
            
            // Actions
            copyDiffBtn: document.getElementById('btn-copy-diff'),
            downloadDiffBtn: document.getElementById('btn-download-diff'),
            restoreBtn: document.getElementById('btn-restore'),
            confirmRestoreBtn: document.getElementById('confirm-restore'),
            restoreVersionSpan: document.getElementById('restore-version'),
        };
    }

    /**
     * קישור אירועים
     */
    function bindEvents() {
        // שינוי גרסאות
        elements.versionLeft?.addEventListener('change', () => {
            state.leftVersion = parseInt(elements.versionLeft.value, 10);
            loadDiff();
        });

        elements.versionRight?.addEventListener('change', () => {
            state.rightVersion = parseInt(elements.versionRight.value, 10);
            loadDiff();
        });

        // החלפת גרסאות
        elements.swapBtn?.addEventListener('click', swapVersions);

        // מצבי תצוגה
        elements.modeButtons?.forEach(btn => {
            btn.addEventListener('click', () => setViewMode(btn.dataset.mode));
        });

        // סנכרון גלילה
        if (elements.leftContent && elements.rightContent) {
            elements.leftContent.addEventListener('scroll', () => {
                if (state.syncScroll) {
                    elements.rightContent.scrollTop = elements.leftContent.scrollTop;
                }
            });
            elements.rightContent.addEventListener('scroll', () => {
                if (state.syncScroll) {
                    elements.leftContent.scrollTop = elements.rightContent.scrollTop;
                }
            });
        }

        // פעולות
        elements.copyDiffBtn?.addEventListener('click', copyDiffToClipboard);
        elements.downloadDiffBtn?.addEventListener('click', downloadPatch);
        elements.confirmRestoreBtn?.addEventListener('click', restoreVersion);
    }

    /**
     * טעינת נתוני ההשוואה מהשרת
     */
    async function loadDiff() {
        try {
            showLoading();

            const url = `/api/compare/versions/${state.fileId}?left=${state.leftVersion}&right=${state.rightVersion}`;
            const response = await fetch(url);
            
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }

            state.diffData = await response.json();
            renderDiff();
            updateStats();
            updateLabels();

        } catch (error) {
            console.error('Error loading diff:', error);
            showError('שגיאה בטעינת ההשוואה');
        }
    }

    /**
     * רינדור ההשוואה בהתאם למצב התצוגה
     */
    function renderDiff() {
        if (!state.diffData) return;

        switch (state.viewMode) {
            case 'side-by-side':
                renderSideBySide();
                break;
            case 'unified':
                renderUnified();
                break;
            case 'inline':
                renderInline();
                break;
        }
    }

    /**
     * רינדור תצוגה צד-לצד
     */
    function renderSideBySide() {
        const leftLines = [];
        const rightLines = [];

        state.diffData.lines.forEach(line => {
            // צד שמאל
            leftLines.push(createDiffLineHTML(
                line.line_num_left,
                line.content_left,
                line.change_type === 'removed' ? 'removed' : 
                line.change_type === 'modified' ? 'modified' : 
                line.change_type === 'added' ? 'empty' : ''
            ));

            // צד ימין
            rightLines.push(createDiffLineHTML(
                line.line_num_right,
                line.content_right,
                line.change_type === 'added' ? 'added' : 
                line.change_type === 'modified' ? 'modified' : 
                line.change_type === 'removed' ? 'empty' : ''
            ));
        });

        elements.leftContent.innerHTML = leftLines.join('');
        elements.rightContent.innerHTML = rightLines.join('');
    }

    /**
     * רינדור תצוגה אחודה
     */
    function renderUnified() {
        const lines = [];

        state.diffData.lines.forEach(line => {
            const cssClass = line.change_type !== 'unchanged' ? line.change_type : '';
            
            lines.push(`
                <div class="unified-line ${cssClass}">
                    <div class="line-numbers">
                        <span>${line.line_num_left ?? ''}</span>
                        <span>${line.line_num_right ?? ''}</span>
                    </div>
                    <div class="line-content">${escapeHtml(
                        line.change_type === 'removed' ? line.content_left : 
                        line.change_type === 'added' ? line.content_right :
                        line.content_left ?? line.content_right ?? ''
                    )}</div>
                </div>
            `);
        });

        elements.unifiedContent.innerHTML = lines.join('');
    }

    /**
     * רינדור תצוגת inline
     */
    function renderInline() {
        const lines = [];

        state.diffData.lines.forEach(line => {
            if (line.change_type === 'modified') {
                // הדגשת ההבדלים בתוך השורה
                const highlighted = highlightInlineDiff(
                    line.content_left || '',
                    line.content_right || ''
                );
                lines.push(`
                    <div class="diff-line">
                        <div class="line-number">${line.line_num_right ?? ''}</div>
                        <div class="line-content">${highlighted}</div>
                    </div>
                `);
            } else {
                lines.push(createDiffLineHTML(
                    line.line_num_left ?? line.line_num_right,
                    line.content_left ?? line.content_right,
                    line.change_type
                ));
            }
        });

        elements.inlineContent.innerHTML = lines.join('');
    }

    /**
     * יצירת HTML לשורת diff
     */
    function createDiffLineHTML(lineNum, content, cssClass = '') {
        return `
            <div class="diff-line ${cssClass}">
                <div class="line-number">${lineNum ?? ''}</div>
                <div class="line-content">${escapeHtml(content ?? '')}</div>
            </div>
        `;
    }

    /**
     * הדגשת הבדלים בתוך שורה
     */
    function highlightInlineDiff(oldText, newText) {
        // אלגוריתם פשוט להדגשת הבדלים ברמת תווים
        let result = '';
        let i = 0, j = 0;

        while (i < oldText.length || j < newText.length) {
            if (i < oldText.length && j < newText.length && oldText[i] === newText[j]) {
                result += escapeHtml(newText[j]);
                i++;
                j++;
            } else if (i < oldText.length && (j >= newText.length || oldText[i] !== newText[j])) {
                result += `<span class="inline-removed">${escapeHtml(oldText[i])}</span>`;
                i++;
            } else if (j < newText.length) {
                result += `<span class="inline-added">${escapeHtml(newText[j])}</span>`;
                j++;
            }
        }

        return result;
    }

    /**
     * עדכון סטטיסטיקות
     */
    function updateStats() {
        if (!state.diffData?.stats) return;

        const stats = state.diffData.stats;
        elements.statAdded.textContent = stats.added || 0;
        elements.statRemoved.textContent = stats.removed || 0;
        elements.statModified.textContent = stats.modified || 0;
        elements.statUnchanged.textContent = stats.unchanged || 0;
    }

    /**
     * עדכון תוויות הגרסאות
     */
    function updateLabels() {
        elements.leftVersionLabel.textContent = state.leftVersion;
        elements.rightVersionLabel.textContent = state.rightVersion;
    }

    /**
     * החלפת גרסאות
     */
    function swapVersions() {
        const temp = state.leftVersion;
        state.leftVersion = state.rightVersion;
        state.rightVersion = temp;

        elements.versionLeft.value = state.leftVersion;
        elements.versionRight.value = state.rightVersion;

        loadDiff();
    }

    /**
     * שינוי מצב תצוגה
     */
    function setViewMode(mode) {
        state.viewMode = mode;

        // עדכון כפתורים
        elements.modeButtons.forEach(btn => {
            btn.classList.toggle('active', btn.dataset.mode === mode);
        });

        // הצגת התצוגה המתאימה
        elements.sideBySideView.classList.toggle('active', mode === 'side-by-side');
        elements.unifiedView.classList.toggle('active', mode === 'unified');
        elements.inlineView.classList.toggle('active', mode === 'inline');

        renderDiff();
    }

    /**
     * העתקת ה-diff ללוח
     */
    async function copyDiffToClipboard() {
        if (!state.diffData) return;

        const text = generateUnifiedDiffText();
        
        try {
            await navigator.clipboard.writeText(text);
            showToast('ה-Diff הועתק ללוח!', 'success');
        } catch (error) {
            console.error('Copy failed:', error);
            showToast('שגיאה בהעתקה', 'error');
        }
    }

    /**
     * יצירת טקסט diff בפורמט unified
     */
    function generateUnifiedDiffText() {
        const lines = [`--- ${state.fileName} (v${state.leftVersion})`, `+++ ${state.fileName} (v${state.rightVersion})`];

        state.diffData.lines.forEach(line => {
            if (line.change_type === 'unchanged') {
                lines.push(` ${line.content_left || ''}`);
            } else if (line.change_type === 'removed') {
                lines.push(`-${line.content_left || ''}`);
            } else if (line.change_type === 'added') {
                lines.push(`+${line.content_right || ''}`);
            } else if (line.change_type === 'modified') {
                lines.push(`-${line.content_left || ''}`);
                lines.push(`+${line.content_right || ''}`);
            }
        });

        return lines.join('\n');
    }

    /**
     * הורדת קובץ patch
     */
    function downloadPatch() {
        const text = generateUnifiedDiffText();
        const blob = new Blob([text], { type: 'text/plain' });
        const url = URL.createObjectURL(blob);
        
        const a = document.createElement('a');
        a.href = url;
        a.download = `${state.fileName}.v${state.leftVersion}-v${state.rightVersion}.patch`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    }

    /**
     * שחזור גרסה
     */
    async function restoreVersion() {
        const versionToRestore = state.leftVersion;
        elements.restoreVersionSpan.textContent = versionToRestore;

        try {
            const response = await fetch(`/api/file/${state.fileId}/restore`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ version: versionToRestore }),
            });

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }

            showToast(`גרסה ${versionToRestore} שוחזרה בהצלחה!`, 'success');
            
            // רענון הדף אחרי שחזור
            setTimeout(() => window.location.reload(), 1500);

        } catch (error) {
            console.error('Restore failed:', error);
            showToast('שגיאה בשחזור הגרסה', 'error');
        }
    }

    // Utility functions
    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    function showLoading() {
        // הצגת אינדיקטור טעינה
    }

    function showError(message) {
        showToast(message, 'error');
    }

    function showToast(message, type = 'info') {
        // שימוש במערכת ה-toasts הקיימת אם יש
        if (window.Toast) {
            window.Toast.show(message, type);
        } else {
            alert(message);
        }
    }

    // Public API
    return {
        init,
        setViewMode,
        swapVersions,
        loadDiff,
    };
})();
```

---

## שלב 4: Telegram Bot Integration

### הוספה ל-`bot_handlers.py` או handler ייעודי

```python
"""
Compare Handlers - טיפול בפקודות השוואה בבוט
"""

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from telegram.constants import ParseMode

from services.diff_service import get_diff_service


# States for conversation
COMPARE_SELECT_FILE = 1
COMPARE_SELECT_VERSION_LEFT = 2
COMPARE_SELECT_VERSION_RIGHT = 3


async def compare_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    פקודת /compare - התחלת זרימת השוואה.
    
    Usage:
        /compare                    - בחירת קובץ להשוואה
        /compare <filename>         - השוואת גרסאות של קובץ ספציפי
        /compare <file1> <file2>    - השוואה בין שני קבצים
    """
    user_id = update.effective_user.id
    args = context.args or []
    
    if len(args) == 0:
        # הצגת רשימת קבצים לבחירה
        return await show_file_selection(update, context)
    
    elif len(args) == 1:
        # השוואת גרסאות של קובץ אחד
        file_name = args[0]
        return await show_version_selection(update, context, file_name)
    
    elif len(args) == 2:
        # השוואה בין שני קבצים
        file1, file2 = args
        return await compare_two_files(update, context, file1, file2)
    
    else:
        await update.message.reply_text(
            "❌ שימוש לא נכון בפקודה.\n\n"
            "📖 **אפשרויות:**\n"
            "`/compare` - בחירת קובץ להשוואה\n"
            "`/compare <filename>` - השוואת גרסאות\n"
            "`/compare <file1> <file2>` - השוואה בין קבצים",
            parse_mode=ParseMode.MARKDOWN,
        )
        return ConversationHandler.END


async def show_version_selection(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    file_name: str,
):
    """הצגת בחירת גרסאות להשוואה."""
    user_id = update.effective_user.id
    
    # קבלת כל הגרסאות
    versions = db.get_all_versions(user_id, file_name)
    
    if not versions:
        await update.message.reply_text(f"❌ לא נמצא קובץ בשם: {file_name}")
        return ConversationHandler.END
    
    if len(versions) < 2:
        await update.message.reply_text(
            f"📄 לקובץ **{file_name}** יש רק גרסה אחת.\n"
            "צריך לפחות שתי גרסאות כדי להשוות.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return ConversationHandler.END
    
    # שמירת שם הקובץ בהקשר
    context.user_data['compare_file'] = file_name
    context.user_data['compare_versions'] = versions
    
    # יצירת כפתורי בחירת גרסה
    keyboard = []
    for v in versions[:10]:  # מקסימום 10 גרסאות
        version_num = v.get('version', 1)
        updated = v.get('updated_at', '')
        if hasattr(updated, 'strftime'):
            updated = updated.strftime('%d/%m/%Y %H:%M')
        
        keyboard.append([
            InlineKeyboardButton(
                f"📌 גרסה {version_num} ({updated})",
                callback_data=f"compare_v_left:{version_num}",
            )
        ])
    
    keyboard.append([
        InlineKeyboardButton("❌ ביטול", callback_data="compare_cancel")
    ])
    
    await update.message.reply_text(
        f"📊 **השוואת גרסאות: {file_name}**\n\n"
        f"נמצאו {len(versions)} גרסאות.\n"
        "בחר את הגרסה **השמאלית** (הישנה):",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    
    return COMPARE_SELECT_VERSION_LEFT


async def handle_version_left_selection(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    """טיפול בבחירת גרסה שמאלית."""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    if data == "compare_cancel":
        await query.edit_message_text("❌ ההשוואה בוטלה.")
        return ConversationHandler.END
    
    # חילוץ מספר הגרסה
    version_left = int(data.split(':')[1])
    context.user_data['compare_version_left'] = version_left
    
    # הצגת בחירת גרסה ימנית
    versions = context.user_data.get('compare_versions', [])
    
    keyboard = []
    for v in versions[:10]:
        version_num = v.get('version', 1)
        if version_num == version_left:
            continue  # לא להציג את הגרסה שכבר נבחרה
        
        updated = v.get('updated_at', '')
        if hasattr(updated, 'strftime'):
            updated = updated.strftime('%d/%m/%Y %H:%M')
        
        keyboard.append([
            InlineKeyboardButton(
                f"📌 גרסה {version_num} ({updated})",
                callback_data=f"compare_v_right:{version_num}",
            )
        ])
    
    keyboard.append([
        InlineKeyboardButton("⬅️ חזור", callback_data="compare_back"),
        InlineKeyboardButton("❌ ביטול", callback_data="compare_cancel"),
    ])
    
    await query.edit_message_text(
        f"✅ נבחרה גרסה שמאלית: **{version_left}**\n\n"
        "בחר את הגרסה **הימנית** (החדשה):",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    
    return COMPARE_SELECT_VERSION_RIGHT


async def handle_version_right_selection(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    """טיפול בבחירת גרסה ימנית והצגת ההשוואה."""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    if data == "compare_cancel":
        await query.edit_message_text("❌ ההשוואה בוטלה.")
        return ConversationHandler.END
    
    if data == "compare_back":
        # חזרה לבחירת גרסה שמאלית
        return await show_version_selection(
            update, context,
            context.user_data.get('compare_file', '')
        )
    
    # חילוץ מספר הגרסה
    version_right = int(data.split(':')[1])
    version_left = context.user_data.get('compare_version_left', 1)
    file_name = context.user_data.get('compare_file', '')
    user_id = update.effective_user.id
    
    await query.edit_message_text("⏳ מחשב השוואה...")
    
    # חישוב ההשוואה
    diff_service = get_diff_service(db)
    result = diff_service.compare_versions(user_id, file_name, version_left, version_right)
    
    if not result:
        await query.edit_message_text("❌ שגיאה בחישוב ההשוואה.")
        return ConversationHandler.END
    
    # עיצוב התוצאה לטלגרם
    formatted = diff_service.format_for_telegram(result, max_lines=40)
    
    # הוספת כפתור לצפייה ב-WebApp
    webapp_url = f"{WEBAPP_URL}/compare/{file_name}?left={version_left}&right={version_right}"
    
    keyboard = [
        [
            InlineKeyboardButton("🌐 צפה ב-WebApp", url=webapp_url),
        ],
        [
            InlineKeyboardButton("🔄 השווה גרסאות אחרות", callback_data="compare_restart"),
            InlineKeyboardButton("📄 חזור לקובץ", callback_data=f"view_file:{file_name}"),
        ],
    ]
    
    await query.edit_message_text(
        f"📊 **השוואה: {file_name}**\n"
        f"גרסה {version_left} ↔️ גרסה {version_right}\n\n"
        f"{formatted}",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    
    return ConversationHandler.END


async def compare_two_files(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    file1: str,
    file2: str,
):
    """השוואה בין שני קבצים שונים."""
    user_id = update.effective_user.id
    
    # קבלת הקבצים
    doc1 = db.get_file(user_id, file1)
    doc2 = db.get_file(user_id, file2)
    
    if not doc1:
        await update.message.reply_text(f"❌ לא נמצא קובץ: {file1}")
        return ConversationHandler.END
    
    if not doc2:
        await update.message.reply_text(f"❌ לא נמצא קובץ: {file2}")
        return ConversationHandler.END
    
    await update.message.reply_text("⏳ מחשב השוואה...")
    
    # חישוב ההשוואה
    diff_service = get_diff_service(db)
    result = diff_service.compare_files(
        user_id,
        str(doc1.get('_id')),
        str(doc2.get('_id')),
    )
    
    if not result:
        await update.message.reply_text("❌ שגיאה בחישוב ההשוואה.")
        return ConversationHandler.END
    
    # עיצוב התוצאה
    formatted = diff_service.format_for_telegram(result, max_lines=40)
    
    await update.message.reply_text(
        f"📊 **השוואה בין קבצים**\n"
        f"📄 {file1} ↔️ 📄 {file2}\n\n"
        f"{formatted}",
        parse_mode=ParseMode.MARKDOWN,
    )
    
    return ConversationHandler.END


# הוספת כפתור "השווה גרסאות" לתפריט הקובץ
def get_file_action_keyboard(file_name: str, file_id: str, **kwargs):
    """יצירת מקלדת פעולות עם כפתור השוואה."""
    keyboard = [
        # ... כפתורים קיימים ...
        [
            InlineKeyboardButton(
                "📊 השווה גרסאות",
                callback_data=f"compare_versions:{file_name}",
            ),
        ],
        # ... עוד כפתורים ...
    ]
    return InlineKeyboardMarkup(keyboard)
```

---

## שלב 5: מצבי תצוגה (Display Modes)

### 1. Side-by-Side (צד לצד)

```
┌────────────────────────────┬────────────────────────────┐
│ גרסה 1 (ישנה)              │ גרסה 2 (חדשה)              │
├────────────────────────────┼────────────────────────────┤
│  1 │ def hello():          │  1 │ def hello():          │
│  2 │     print("Hello")    │  2 │     print("Hello!")   │ ← שינוי
│  3 │                       │  3 │     return True       │ ← הוספה
│  4 │ def bye():            │  4 │ def bye():            │
│  5 │     print("Bye")      │    │                       │ ← מחיקה
└────────────────────────────┴────────────────────────────┘
```

### 2. Unified (אחיד)

```
--- v1
+++ v2
@@ -1,5 +1,4 @@
 def hello():
-    print("Hello")
+    print("Hello!")
+    return True
 def bye():
-    print("Bye")
```

### 3. Inline (תוך-שורתי)

```
def hello():
    print("Hello█!")  ← שינוי מודגש בתוך השורה
    return True       ← שורה חדשה
def bye():
```

---

## שלב 6: תכונות מתקדמות

### 6.1 Merge Tool

```python
# הוספה ל-diff_service.py

class MergeConflict:
    """ייצוג קונפליקט ב-merge"""
    start_line: int
    end_line: int
    left_content: List[str]
    right_content: List[str]
    resolution: Optional[str] = None  # 'left', 'right', 'custom'


class MergeService:
    """שירות מיזוג קוד."""
    
    def find_conflicts(
        self,
        left_content: str,
        right_content: str,
        base_content: Optional[str] = None,
    ) -> List[MergeConflict]:
        """זיהוי קונפליקטים בין שתי גרסאות."""
        # Three-way merge אם יש בסיס
        # או Two-way merge אחרת
        pass
    
    def apply_resolution(
        self,
        content: str,
        conflict: MergeConflict,
        resolution: str,
        custom_content: Optional[str] = None,
    ) -> str:
        """החלת פתרון לקונפליקט."""
        pass
    
    def auto_merge(
        self,
        left_content: str,
        right_content: str,
        base_content: Optional[str] = None,
    ) -> Tuple[str, List[MergeConflict]]:
        """מיזוג אוטומטי ככל האפשר, החזרת קונפליקטים שנותרו."""
        pass
```

### 6.2 Syntax-Aware Diff

```python
# diff חכם שמבין את מבנה הקוד

def compute_semantic_diff(
    left_content: str,
    right_content: str,
    language: str,
) -> DiffResult:
    """
    Diff שמתחשב במבנה הקוד:
    - זיהוי שינויים בפונקציות שלמות
    - התעלמות משינויי whitespace לא משמעותיים
    - קיבוץ שינויים קשורים
    """
    # ניתוח AST אם השפה נתמכת
    if language == 'python':
        return _python_semantic_diff(left_content, right_content)
    # ... שפות נוספות ...
    
    # Fallback ל-diff רגיל
    return compute_diff(left_content, right_content)
```

### 6.3 Mini-Map

```javascript
// מפה מזערית של השינויים

function renderMinimap(diffData, containerHeight) {
    const canvas = document.createElement('canvas');
    canvas.width = 60;
    canvas.height = containerHeight;
    
    const ctx = canvas.getContext('2d');
    const totalLines = diffData.lines.length;
    const lineHeight = containerHeight / totalLines;
    
    diffData.lines.forEach((line, i) => {
        const y = i * lineHeight;
        
        switch (line.change_type) {
            case 'added':
                ctx.fillStyle = '#28a745';
                break;
            case 'removed':
                ctx.fillStyle = '#dc3545';
                break;
            case 'modified':
                ctx.fillStyle = '#ffc107';
                break;
            default:
                return;
        }
        
        ctx.fillRect(0, y, 60, Math.max(1, lineHeight));
    });
    
    return canvas;
}
```

---

## בדיקות

### Unit Tests

```python
# tests/test_diff_service.py

import pytest
from services.diff_service import DiffService, DiffResult


class TestDiffService:
    """בדיקות לשירות ההשוואה."""
    
    @pytest.fixture
    def service(self):
        return DiffService()
    
    def test_compute_diff_identical(self, service):
        """קבצים זהים - אין שינויים."""
        content = "line1\nline2\nline3"
        result = service.compute_diff(content, content)
        
        assert result.stats['added'] == 0
        assert result.stats['removed'] == 0
        assert result.stats['modified'] == 0
        assert result.stats['unchanged'] == 3
    
    def test_compute_diff_added_lines(self, service):
        """זיהוי שורות שנוספו."""
        left = "line1\nline2"
        right = "line1\nline2\nline3"
        
        result = service.compute_diff(left, right)
        
        assert result.stats['added'] == 1
        assert result.stats['unchanged'] == 2
    
    def test_compute_diff_removed_lines(self, service):
        """זיהוי שורות שנמחקו."""
        left = "line1\nline2\nline3"
        right = "line1\nline3"
        
        result = service.compute_diff(left, right)
        
        assert result.stats['removed'] == 1
    
    def test_compute_diff_modified_lines(self, service):
        """זיהוי שורות ששונו."""
        left = "line1\nold content\nline3"
        right = "line1\nnew content\nline3"
        
        result = service.compute_diff(left, right)
        
        assert result.stats['modified'] == 1
    
    def test_format_unified_diff(self, service):
        """בדיקת פורמט unified."""
        left = "line1\nline2"
        right = "line1\nline2\nline3"
        
        result = service.compute_diff(left, right)
        unified = service.format_unified_diff(result)
        
        assert "+++" in unified
        assert "---" in unified
        assert "+line3" in unified
    
    def test_format_for_telegram(self, service):
        """בדיקת פורמט טלגרם."""
        left = "line1"
        right = "line1\nline2"
        
        result = service.compute_diff(left, right)
        telegram_text = service.format_for_telegram(result)
        
        assert "סיכום השוואה" in telegram_text
        assert "נוספו:" in telegram_text


class TestDiffServiceWithDB:
    """בדיקות עם מסד נתונים (mock)."""
    
    @pytest.fixture
    def mock_db(self, mocker):
        db = mocker.Mock()
        db.get_version.return_value = {
            "code": "test content",
            "version": 1,
            "file_name": "test.py",
            "updated_at": "2025-01-01",
        }
        db.get_file_by_id.return_value = {
            "user_id": 123,
            "code": "test content",
            "file_name": "test.py",
        }
        return db
    
    def test_compare_versions(self, mock_db):
        """השוואת גרסאות."""
        service = DiffService(mock_db)
        
        mock_db.get_version.side_effect = [
            {"code": "v1 content", "version": 1},
            {"code": "v2 content", "version": 2},
        ]
        
        result = service.compare_versions(123, "test.py", 1, 2)
        
        assert result is not None
        assert result.left_info['version'] == 1
        assert result.right_info['version'] == 2
```

### Integration Tests

```python
# tests/test_compare_api.py

import pytest
from flask import url_for


class TestCompareAPI:
    """בדיקות ל-API השוואה."""
    
    def test_compare_versions_unauthorized(self, client):
        """גישה ללא אימות."""
        response = client.get('/api/compare/versions/123')
        assert response.status_code == 401
    
    def test_compare_versions_not_found(self, client, auth_headers):
        """קובץ לא קיים."""
        response = client.get(
            '/api/compare/versions/nonexistent',
            headers=auth_headers,
        )
        assert response.status_code == 404
    
    def test_compare_versions_success(self, client, auth_headers, test_file):
        """השוואה מוצלחת."""
        # יצירת גרסה שנייה
        client.post(f'/api/file/{test_file["_id"]}/save', ...)
        
        response = client.get(
            f'/api/compare/versions/{test_file["_id"]}?left=1&right=2',
            headers=auth_headers,
        )
        
        assert response.status_code == 200
        data = response.get_json()
        assert 'lines' in data
        assert 'stats' in data
    
    def test_compare_files_success(self, client, auth_headers, test_files):
        """השוואה בין קבצים."""
        response = client.post(
            '/api/compare/files',
            json={
                'left_file_id': str(test_files[0]['_id']),
                'right_file_id': str(test_files[1]['_id']),
            },
            headers=auth_headers,
        )
        
        assert response.status_code == 200
```

---

## משימות לפי סדר עדיפות

### שלב 1: MVP (1-2 שבועות)

- [ ] **P0** יצירת `services/diff_service.py` עם `compute_diff()` בסיסי
- [ ] **P0** API endpoint: `/api/compare/versions/<file_id>`
- [ ] **P0** תבנית `compare.html` עם תצוגה צד-לצד
- [ ] **P0** CSS בסיסי להשוואה
- [ ] **P0** JavaScript לטעינה והצגה
- [ ] **P1** סטטיסטיקות שינויים (added/removed/modified)
- [ ] **P1** בדיקות unit בסיסיות

### שלב 2: תכונות נוספות (1 שבוע)

- [ ] **P1** תצוגה unified
- [ ] **P1** תצוגה inline
- [ ] **P1** סנכרון גלילה
- [ ] **P1** העתקת diff ללוח
- [ ] **P1** הורדת קובץ patch
- [ ] **P2** השוואה בין קבצים שונים

### שלב 3: Telegram Bot (1 שבוע)

- [ ] **P1** פקודת `/compare`
- [ ] **P1** כפתור "השווה גרסאות" בתפריט קובץ
- [ ] **P1** פורמט תצוגה לטלגרם
- [ ] **P2** Conversation handler מלא

### שלב 4: תכונות מתקדמות (2 שבועות)

- [ ] **P2** Mini-map
- [ ] **P2** Syntax highlighting בתוך ה-diff
- [ ] **P3** Merge tool בסיסי
- [ ] **P3** Semantic diff (לפייתון)
- [ ] **P3** קיצורי מקלדת

### שלב 5: שיפורים (Ongoing)

- [ ] **P2** ביצועים לקבצים גדולים (virtualization)
- [ ] **P2** מטמון לתוצאות diff
- [ ] **P3** Word-level diff
- [ ] **P3** תמיכה בכל ערכות הנושא

---

## סיכום

המדריך מספק תוכנית מפורטת למימוש כלי השוואת קבצים ב-CodeBot:

1. **Backend** - שירות `DiffService` עם אלגוריתם מבוסס `difflib`
2. **API** - נקודות קצה ל-WebApp ולטלגרם
3. **WebApp** - ממשק משתמש עם 3 מצבי תצוגה
4. **Telegram** - פקודות ושילוב בתפריט הקבצים
5. **בדיקות** - Unit ו-Integration tests

הפיצ'ר משתלב עם התשתית הקיימת:
- מערכת הגרסאות (`get_all_versions`, `get_version`)
- Syntax highlighting (Pygments)
- עורך קוד (CodeMirror)
- ממשק glass-morphism

---

---

## נספח א': השלמות למימוש - השוואת קבצים וסנכרון גלילה

### א.1 קובץ `compare_files.html` - מימוש מלא

הקובץ `webapp/templates/compare_files.html` כולל:

**מבנה Grid רספונסיבי:**
```css
.file-selection-grid {
    display: grid;
    grid-template-columns: 1fr auto 1fr;
    gap: 1.5rem;
    align-items: end;
}

@media (max-width: 768px) {
    .file-selection-grid {
        grid-template-columns: 1fr;
    }
}
```

**עיצוב Glassmorphism ל-Selects:**
```css
.file-select {
    background: var(--glass-bg, rgba(255, 255, 255, 0.08));
    border: 1px solid var(--glass-border, rgba(255, 255, 255, 0.18));
    backdrop-filter: blur(10px);
    -webkit-backdrop-filter: blur(10px);
    appearance: none;
}
```

**כפתור השוואה עם אנימציית Loading:**
```html
<button type="submit" id="btn-compare" class="btn-compare">
    <span class="spinner"></span>
    <span class="btn-text">
        <i class="fas fa-code-compare"></i> השווה קבצים
    </span>
</button>
```

### א.2 לוגיקה משותפת ב-`compare.js`

ה-JavaScript מאוחד לשני המצבים:

```javascript
// אתחול לפי מצב
window.CompareView.init(config);        // מצב גרסאות
window.CompareView.initFilesMode(config); // מצב קבצים

// State משותף
const state = {
    mode: 'versions', // או 'files'
    viewMode: 'side-by-side',
    diffData: null,
    // ...
};
```

**מבנה מודולרי:**
1. `bindCommonEvents()` - אירועים משותפים (מצבי תצוגה, פעולות)
2. `bindVersionsEvents()` - אירועים ייחודיים לגרסאות
3. `bindFilesEvents()` - אירועים ייחודיים לקבצים
4. `loadDiff()` / `loadFilesDiff()` - טעינה לפי מצב
5. `generateUnifiedDiffText()` - יצירת patch (משותף)

### א.3 סנכרון גלילה ויישור מושלם

**הבעיה:** כאשר שורה אחת ארוכה וגולשת (wrap), או יש רצף שורות ריקות, השורות בשני הצדדים יוצאות מסנכרון.

**הפתרון - שלושה רכיבים:**

#### 1. סנכרון לפי אחוז גלילה

```javascript
function handleScroll(source, target) {
    if (scrollSyncState.isScrolling) return;
    scrollSyncState.isScrolling = true;
    
    // חישוב אחוז הגלילה
    const scrollRatio = source.scrollTop / 
        (source.scrollHeight - source.clientHeight || 1);
    
    // החלה על היעד
    const targetScrollTop = scrollRatio * 
        (target.scrollHeight - target.clientHeight);
    target.scrollTop = targetScrollTop;
    
    requestAnimationFrame(() => {
        scrollSyncState.isScrolling = false;
    });
}
```

#### 2. יישור גבהי שורות (Pixel-Perfect)

```javascript
function alignRowHeights() {
    if (state.viewMode !== 'side-by-side') return;
    
    const leftRows = elements.leftContent?.querySelectorAll('.diff-line');
    const rightRows = elements.rightContent?.querySelectorAll('.diff-line');
    
    const rowCount = Math.max(leftRows.length, rightRows.length);
    
    for (let i = 0; i < rowCount; i++) {
        const leftRow = leftRows[i];
        const rightRow = rightRows[i];
        if (!leftRow || !rightRow) continue;
        
        // איפוס גובה קודם
        leftRow.style.minHeight = '';
        rightRow.style.minHeight = '';
        
        // חישוב הגובה הטבעי
        const leftHeight = leftRow.getBoundingClientRect().height;
        const rightHeight = rightRow.getBoundingClientRect().height;
        
        // קביעת הגובה המקסימלי לשתיהן
        const maxHeight = Math.max(leftHeight, rightHeight);
        
        if (leftHeight !== rightHeight) {
            leftRow.style.minHeight = `${maxHeight}px`;
            rightRow.style.minHeight = `${maxHeight}px`;
        }
    }
}
```

#### 3. CSS תומך

```css
.diff-line {
    display: flex;
    min-height: 24px;
    box-sizing: border-box;
}

.line-content {
    flex: 1;
    min-width: 0;
    word-break: break-all;
    white-space: pre-wrap;
    overflow-wrap: break-word;
}

.line-content pre {
    margin: 0;
    white-space: pre-wrap;
    word-break: break-all;
}

/* שורות ריקות חייבות לשמור על גובה */
.diff-line.empty .line-content {
    min-height: 1em;
}
```

### א.4 Character-Level Diff (Inline Mode)

אלגוריתם LCS להדגשת הבדלים ברמת תווים:

```javascript
function highlightInlineDiff(oldText, newText) {
    const lcs = computeLCS([...oldText], [...newText]);
    const result = [];
    
    let oldIdx = 0, newIdx = 0, lcsIdx = 0;
    
    while (oldIdx < oldText.length || newIdx < newText.length) {
        // תווים שנמחקו
        while (oldIdx < oldText.length && 
               (lcsIdx >= lcs.length || oldText[oldIdx] !== lcs[lcsIdx])) {
            result.push(`<span class="inline-removed">${escape(oldText[oldIdx])}</span>`);
            oldIdx++;
        }
        
        // תווים שנוספו
        while (newIdx < newText.length && 
               (lcsIdx >= lcs.length || newText[newIdx] !== lcs[lcsIdx])) {
            result.push(`<span class="inline-added">${escape(newText[newIdx])}</span>`);
            newIdx++;
        }
        
        // תו משותף
        if (lcsIdx < lcs.length) {
            result.push(escape(lcs[lcsIdx]));
            oldIdx++; newIdx++; lcsIdx++;
        }
    }
    
    return result.join('');
}
```

### א.5 תזכורת - רישום Routes

הוסף ל-`webapp/app.py`:

```python
@app.route('/compare/<file_id>')
@login_required
def compare_versions_page(file_id: str):
    # ... קוד מהמדריך המקורי ...

@app.route('/compare')
@login_required
def compare_files_page():
    user_id = get_current_user_id()
    
    left_id = request.args.get('left')
    right_id = request.args.get('right')
    
    # קבלת רשימת הקבצים
    user_files = db.get_user_files(user_id, limit=100)
    
    # חישוב שפות מובילות לסינון מהיר
    lang_counts = {}
    for f in user_files:
        lang = f.get('programming_language', 'other')
        lang_counts[lang] = lang_counts.get(lang, 0) + 1
    top_languages = sorted(lang_counts.keys(), key=lambda x: -lang_counts[x])[:5]
    
    return render_template(
        'compare_files.html',
        files=user_files,
        selected_left=left_id,
        selected_right=right_id,
        top_languages=top_languages,
    )
```

---

## נספח ב': בדיקות סנכרון גלילה

```python
# tests/test_compare_alignment.py

import pytest
from playwright.sync_api import Page

class TestCompareAlignment:
    """בדיקות E2E ליישור שורות."""
    
    def test_long_line_alignment(self, page: Page, auth):
        """שורה ארוכה שגולשת נשארת מיושרת."""
        # יצירת קבצים עם שורה ארוכה
        # ...
        
        page.goto('/compare?left=X&right=Y')
        page.click('#btn-compare')
        page.wait_for_selector('.diff-line')
        
        # בדיקת גבהים
        left_heights = page.eval_on_selector_all(
            '#left-content .diff-line',
            'els => els.map(e => e.getBoundingClientRect().height)'
        )
        right_heights = page.eval_on_selector_all(
            '#right-content .diff-line',
            'els => els.map(e => e.getBoundingClientRect().height)'
        )
        
        assert left_heights == right_heights, "Row heights should match"
    
    def test_scroll_sync(self, page: Page, auth):
        """גלילה בצד אחד מסנכרנת את הצד השני."""
        page.goto('/compare/existing-file-id')
        
        # גלילה בצד שמאל
        page.evaluate('document.getElementById("left-content").scrollTop = 500')
        
        # בדיקה שהצד הימני התעדכן
        right_scroll = page.evaluate(
            'document.getElementById("right-content").scrollTop'
        )
        
        assert abs(right_scroll - 500) < 5, "Scroll should be synced"
```

---

**נוצר ב:** דצמבר 2025  
**מחבר:** CodeBot Team  
**קישורים קשורים:**
- [FEATURES_SUMMARY.md](/workspace/FEATURES_SUMMARY.md) - סיכום כל הפיצ'רים
- [תיעוד CodeBot](https://amirbiron.github.io/CodeBot/)
