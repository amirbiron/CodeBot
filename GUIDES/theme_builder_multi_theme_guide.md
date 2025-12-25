# מדריך מימוש Theme Builder – חלק ב': תמיכה בריבוי ערכות (Multi-Theme Support)

> **מטרה:** שדרוג Theme Builder לתמיכה ביצירה, שמירה וניהול של מספר ערכות נושא מותאמות אישית למשתמש.
> **מבוסס על:** [חלק א' – מדריך מימוש Theme Builder](./theme_builder_implementation_guide.md)

---

## תוכן עניינים

1. [סקירת השינוי](#סקירת-השינוי)
2. [שינוי סכמה (MongoDB)](#שינוי-סכמה-mongodb)
3. [עדכון Backend & API](#עדכון-backend--api)
4. [שדרוג ממשק המשתמש](#שדרוג-ממשק-המשתמש)
5. [מיגרציה מהמבנה הקודם](#מיגרציה-מהמבנה-הקודם)
6. [בדיקות](#בדיקות)
7. [צ'קליסט למימוש](#צקליסט-למימוש)

---

## סקירת השינוי

### מצב קיים (חלק א')

```python
# מבנה נוכחי – ערכה בודדת
{
    "_id": user_id,
    "ui_prefs": {...},
    "custom_theme": {          # ← אובייקט בודד
        "name": "My Theme",
        "is_active": True,
        "updated_at": datetime,
        "variables": {...}
    }
}
```

### מצב חדש (חלק ב')

```python
# מבנה חדש – מערך ערכות
{
    "_id": user_id,
    "ui_prefs": {...},
    "custom_themes": [         # ← מערך של ערכות
        {
            "id": "uuid-1",
            "name": "ערכה כהה שלי",
            "is_active": True,     # רק אחת יכולה להיות פעילה
            "created_at": datetime,
            "updated_at": datetime,
            "variables": {...}
        },
        {
            "id": "uuid-2",
            "name": "ערכה בהירה",
            "is_active": False,
            "created_at": datetime,
            "updated_at": datetime,
            "variables": {...}
        }
    ]
}
```

### יתרונות המבנה החדש

- ✅ משתמש יכול לשמור מספר ערכות ולעבור ביניהן
- ✅ אפשרות לנסות ערכות חדשות בלי לאבד את הקודמות
- ✅ ניהול קל יותר (עריכה, מחיקה, שכפול)
- ✅ תשתית להרחבות עתידיות (שיתוף, ייבוא/ייצוא)

---

## שינוי סכמה (MongoDB)

### 2.1 מבנה מסמך Theme

```python
from datetime import datetime, timezone
import uuid

def create_theme_document(name: str, variables: dict, description: str = "") -> dict:
    """יצירת מסמך ערכה חדשה."""
    return {
        "id": str(uuid.uuid4()),           # מזהה ייחודי
        "name": name,
        "description": description[:200],   # תיאור קצר (אופציונלי)
        "is_active": False,                 # ברירת מחדל: לא פעיל
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        "variables": variables,
    }
```

### 2.2 אינדקסים מומלצים

```python
# אינדקס לחיפוש ערכה פעילה במהירות
db.users.create_index([
    ("_id", 1),
    ("custom_themes.is_active", 1)
])

# אינדקס לחיפוש לפי ID של ערכה
db.users.create_index([
    ("_id", 1),
    ("custom_themes.id", 1)
])
```

### 2.3 לוגיקת `is_active` – ערכה פעילה יחידה

**עיקרון:** רק ערכה אחת יכולה להיות פעילה בכל רגע נתון.

```python
def activate_theme(user_id: str, theme_id: str) -> bool:
    """
    הפעלת ערכה ספציפית וביטול כל השאר.
    משתמש ב-arrayFilters לעדכון אטומי.
    """
    result = db.users.update_one(
        {"_id": user_id, "custom_themes.id": theme_id},
        {
            "$set": {
                # בטל את כולן
                "custom_themes.$[].is_active": False,
            }
        }
    )
    
    # הפעל רק את הנבחרת
    result = db.users.update_one(
        {"_id": user_id, "custom_themes.id": theme_id},
        {
            "$set": {
                "custom_themes.$[elem].is_active": True,
                "ui_prefs.theme": "custom"
            }
        },
        array_filters=[{"elem.id": theme_id}]
    )
    
    return result.modified_count > 0
```

**פתרון אלטרנטיבי (פשוט יותר, שתי שאילתות):**

```python
def activate_theme_simple(user_id: str, theme_id: str) -> bool:
    """גרסה פשוטה עם שתי שאילתות."""
    # שלב 1: בטל את כל הערכות
    db.users.update_one(
        {"_id": user_id},
        {"$set": {"custom_themes.$[].is_active": False}}
    )
    
    # שלב 2: הפעל את הערכה הנבחרת
    result = db.users.update_one(
        {"_id": user_id, "custom_themes.id": theme_id},
        {
            "$set": {
                "custom_themes.$.is_active": True,
                "ui_prefs.theme": "custom"
            }
        }
    )
    
    return result.modified_count > 0
```

### 2.4 קבועים והגבלות

```python
# קבועים חדשים להוסיף ב-app.py
MAX_THEMES_PER_USER = 10          # מגבלת ערכות למשתמש
MAX_THEME_NAME_LENGTH = 50        # אורך שם מקסימלי
MAX_THEME_DESCRIPTION_LENGTH = 200
```

---

## עדכון Backend & API

### 3.1 קבלת רשימת ערכות – `GET /api/themes`

```python
@app.route('/api/themes', methods=['GET'])
@login_required
def get_user_themes():
    """קבלת רשימת כל הערכות השמורות של המשתמש."""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    
    try:
        user_doc = db.users.find_one(
            {"_id": user_id},
            {"custom_themes": 1}
        )
        
        themes = []
        if user_doc and user_doc.get("custom_themes"):
            for theme in user_doc["custom_themes"]:
                themes.append({
                    "id": theme.get("id"),
                    "name": theme.get("name"),
                    "description": theme.get("description", ""),
                    "is_active": theme.get("is_active", False),
                    "created_at": theme.get("created_at").isoformat() if theme.get("created_at") else None,
                    "updated_at": theme.get("updated_at").isoformat() if theme.get("updated_at") else None,
                    # לא מחזירים variables ברשימה – רק בבקשה ספציפית
                })
        
        return jsonify({
            "ok": True,
            "themes": themes,
            "count": len(themes),
            "max_allowed": MAX_THEMES_PER_USER
        })
        
    except Exception as e:
        app.logger.error(f"get_user_themes failed: {e}")
        return jsonify({"ok": False, "error": "database_error"}), 500


@app.route('/api/themes/<theme_id>', methods=['GET'])
@login_required
def get_theme_details(theme_id: str):
    """קבלת פרטי ערכה ספציפית כולל variables."""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    
    try:
        user_doc = db.users.find_one(
            {"_id": user_id, "custom_themes.id": theme_id},
            {"custom_themes.$": 1}
        )
        
        if not user_doc or not user_doc.get("custom_themes"):
            return jsonify({"ok": False, "error": "theme_not_found"}), 404
        
        theme = user_doc["custom_themes"][0]
        
        return jsonify({
            "ok": True,
            "theme": {
                "id": theme.get("id"),
                "name": theme.get("name"),
                "description": theme.get("description", ""),
                "is_active": theme.get("is_active", False),
                "created_at": theme.get("created_at").isoformat() if theme.get("created_at") else None,
                "updated_at": theme.get("updated_at").isoformat() if theme.get("updated_at") else None,
                "variables": theme.get("variables", {}),
            }
        })
        
    except Exception as e:
        app.logger.error(f"get_theme_details failed: {e}")
        return jsonify({"ok": False, "error": "database_error"}), 500
```

### 3.2 יצירת ערכה חדשה – `POST /api/themes`

```python
@app.route('/api/themes', methods=['POST'])
@login_required
def create_theme():
    """יצירת ערכת נושא חדשה (במקום לדרוס)."""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    
    data = request.get_json() or {}
    
    # בדיקת מגבלת ערכות
    try:
        user_doc = db.users.find_one(
            {"_id": user_id},
            {"custom_themes": 1}
        )
        current_count = len(user_doc.get("custom_themes", [])) if user_doc else 0
        
        if current_count >= MAX_THEMES_PER_USER:
            return jsonify({
                "ok": False,
                "error": "max_themes_reached",
                "message": f"ניתן לשמור עד {MAX_THEMES_PER_USER} ערכות"
            }), 400
            
    except Exception as e:
        app.logger.error(f"create_theme count check failed: {e}")
        return jsonify({"ok": False, "error": "database_error"}), 500
    
    # ולידציית שם
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"ok": False, "error": "missing_name"}), 400
    if len(name) > MAX_THEME_NAME_LENGTH:
        return jsonify({"ok": False, "error": "name_too_long"}), 400
    
    # ולידציית variables
    variables = data.get("variables") or {}
    if not isinstance(variables, dict):
        return jsonify({"ok": False, "error": "invalid_variables"}), 400
    
    validated_vars = {}
    for var_name, var_value in variables.items():
        if var_name not in ALLOWED_VARIABLES:
            continue
        if not _validate_color(var_value):
            return jsonify({
                "ok": False,
                "error": "invalid_color",
                "field": var_name
            }), 400
        validated_vars[var_name] = var_value
    
    # יצירת מסמך ערכה
    theme_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    
    theme_doc = {
        "id": theme_id,
        "name": name,
        "description": (data.get("description") or "").strip()[:MAX_THEME_DESCRIPTION_LENGTH],
        "is_active": False,  # ערכה חדשה לא פעילה כברירת מחדל
        "created_at": now,
        "updated_at": now,
        "variables": validated_vars,
    }
    
    try:
        db.users.update_one(
            {"_id": user_id},
            {"$push": {"custom_themes": theme_doc}}
        )
        
        # אם המשתמש ביקש להפעיל מיד
        if data.get("activate", False):
            activate_theme_simple(user_id, theme_id)
        
        return jsonify({
            "ok": True,
            "theme_id": theme_id,
            "message": "הערכה נוצרה בהצלחה"
        })
        
    except Exception as e:
        app.logger.error(f"create_theme failed: {e}")
        return jsonify({"ok": False, "error": "database_error"}), 500
```

### 3.3 עדכון ערכה קיימת – `PUT /api/themes/<id>`

```python
@app.route('/api/themes/<theme_id>', methods=['PUT'])
@login_required
def update_theme(theme_id: str):
    """עדכון ערכת נושא קיימת."""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    
    data = request.get_json() or {}
    
    # בדיקה שהערכה קיימת
    user_doc = db.users.find_one(
        {"_id": user_id, "custom_themes.id": theme_id},
        {"custom_themes.$": 1}
    )
    
    if not user_doc or not user_doc.get("custom_themes"):
        return jsonify({"ok": False, "error": "theme_not_found"}), 404
    
    # בניית אובייקט העדכון
    update_fields = {"custom_themes.$.updated_at": datetime.now(timezone.utc)}
    
    # עדכון שם (אם סופק)
    if "name" in data:
        name = (data["name"] or "").strip()
        if not name:
            return jsonify({"ok": False, "error": "missing_name"}), 400
        if len(name) > MAX_THEME_NAME_LENGTH:
            return jsonify({"ok": False, "error": "name_too_long"}), 400
        update_fields["custom_themes.$.name"] = name
    
    # עדכון תיאור (אם סופק)
    if "description" in data:
        update_fields["custom_themes.$.description"] = (data["description"] or "").strip()[:MAX_THEME_DESCRIPTION_LENGTH]
    
    # עדכון variables (אם סופקו)
    if "variables" in data:
        variables = data["variables"]
        if not isinstance(variables, dict):
            return jsonify({"ok": False, "error": "invalid_variables"}), 400
        
        validated_vars = {}
        for var_name, var_value in variables.items():
            if var_name not in ALLOWED_VARIABLES:
                continue
            if not _validate_color(var_value):
                return jsonify({
                    "ok": False,
                    "error": "invalid_color",
                    "field": var_name
                }), 400
            validated_vars[var_name] = var_value
        
        update_fields["custom_themes.$.variables"] = validated_vars
    
    try:
        result = db.users.update_one(
            {"_id": user_id, "custom_themes.id": theme_id},
            {"$set": update_fields}
        )
        
        if result.modified_count == 0:
            return jsonify({"ok": False, "error": "no_changes"}), 400
        
        return jsonify({"ok": True, "message": "הערכה עודכנה בהצלחה"})
        
    except Exception as e:
        app.logger.error(f"update_theme failed: {e}")
        return jsonify({"ok": False, "error": "database_error"}), 500
```

### 3.4 הפעלת ערכה – `POST /api/themes/<id>/activate`

```python
@app.route('/api/themes/<theme_id>/activate', methods=['POST'])
@login_required
def activate_theme_endpoint(theme_id: str):
    """החלת ערכה ספציפית (הפיכתה לפעילה)."""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    
    # בדיקה שהערכה קיימת
    user_doc = db.users.find_one(
        {"_id": user_id, "custom_themes.id": theme_id},
        {"custom_themes.$": 1}
    )
    
    if not user_doc or not user_doc.get("custom_themes"):
        return jsonify({"ok": False, "error": "theme_not_found"}), 404
    
    try:
        success = activate_theme_simple(user_id, theme_id)
        
        if success:
            return jsonify({
                "ok": True,
                "message": "הערכה הופעלה בהצלחה",
                "active_theme_id": theme_id
            })
        else:
            return jsonify({"ok": False, "error": "activation_failed"}), 500
            
    except Exception as e:
        app.logger.error(f"activate_theme_endpoint failed: {e}")
        return jsonify({"ok": False, "error": "database_error"}), 500


@app.route('/api/themes/deactivate', methods=['POST'])
@login_required
def deactivate_all_themes():
    """ביטול כל הערכות המותאמות וחזרה לערכה רגילה."""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    
    try:
        db.users.update_one(
            {"_id": user_id},
            {
                "$set": {
                    "custom_themes.$[].is_active": False,
                    "ui_prefs.theme": "classic"
                }
            }
        )
        
        return jsonify({
            "ok": True,
            "message": "הערכות המותאמות בוטלו",
            "reset_to": "classic"
        })
        
    except Exception as e:
        app.logger.error(f"deactivate_all_themes failed: {e}")
        return jsonify({"ok": False, "error": "database_error"}), 500
```

### 3.5 מחיקת ערכה – `DELETE /api/themes/<id>`

```python
@app.route('/api/themes/<theme_id>', methods=['DELETE'])
@login_required
def delete_theme(theme_id: str):
    """מחיקת ערכה ספציפית."""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    
    # בדיקה שהערכה קיימת
    user_doc = db.users.find_one(
        {"_id": user_id, "custom_themes.id": theme_id},
        {"custom_themes.$": 1}
    )
    
    if not user_doc or not user_doc.get("custom_themes"):
        return jsonify({"ok": False, "error": "theme_not_found"}), 404
    
    theme = user_doc["custom_themes"][0]
    was_active = theme.get("is_active", False)
    
    try:
        # הסרת הערכה מהמערך
        db.users.update_one(
            {"_id": user_id},
            {"$pull": {"custom_themes": {"id": theme_id}}}
        )
        
        # אם הערכה שנמחקה הייתה פעילה – חזור ל-classic
        if was_active:
            db.users.update_one(
                {"_id": user_id},
                {"$set": {"ui_prefs.theme": "classic"}}
            )
        
        return jsonify({
            "ok": True,
            "message": "הערכה נמחקה בהצלחה",
            "was_active": was_active,
            "reset_to": "classic" if was_active else None
        })
        
    except Exception as e:
        app.logger.error(f"delete_theme failed: {e}")
        return jsonify({"ok": False, "error": "database_error"}), 500
```

### 3.6 עדכון `get_custom_theme()` לתמיכה במערך

```python
def get_custom_theme(user_id) -> dict | None:
    """
    טען את הערכה המותאמת הפעילה של המשתמש.
    תומך גם במבנה הישן (custom_theme) וגם בחדש (custom_themes[]).
    """
    if not user_id:
        return None
    
    try:
        user_doc = db.users.find_one(
            {"_id": user_id},
            {"custom_theme": 1, "custom_themes": 1}
        )
        
        if not user_doc:
            return None
        
        # מבנה חדש (מערך) – עדיפות
        if user_doc.get("custom_themes"):
            for theme in user_doc["custom_themes"]:
                if theme.get("is_active"):
                    return theme
        
        # Fallback למבנה ישן (אובייקט בודד)
        old_theme = user_doc.get("custom_theme")
        if old_theme and old_theme.get("is_active"):
            return old_theme
        
        return None
        
    except Exception as e:
        app.logger.warning(f"get_custom_theme failed: {e}")
        return None
```

### 3.7 סיכום נקודות קצה (API)

| Method | Endpoint | תיאור |
|--------|----------|--------|
| `GET` | `/api/themes` | רשימת כל הערכות של המשתמש |
| `GET` | `/api/themes/<id>` | פרטי ערכה ספציפית כולל variables |
| `POST` | `/api/themes` | יצירת ערכה חדשה |
| `PUT` | `/api/themes/<id>` | עדכון ערכה קיימת |
| `POST` | `/api/themes/<id>/activate` | הפעלת ערכה ספציפית |
| `POST` | `/api/themes/deactivate` | ביטול כל הערכות המותאמות |
| `DELETE` | `/api/themes/<id>` | מחיקת ערכה |

---

## שדרוג ממשק המשתמש

### 4.1 תרשים ממשק חדש

```
┌──────────────────────────────────────────────────────────────────────────┐
│                    /settings/theme-builder                                │
├───────────────┬──────────────────────────────┬───────────────────────────┤
│  MY THEMES    │     CONTROL PANEL (40%)      │   LIVE PREVIEW (35%)      │
│   SIDEBAR     │                              │                           │
│    (25%)      │  ┌────────────────────────┐  │  ┌─────────────────────┐  │
│               │  │  Theme Name Input      │  │  │  Navbar Preview     │  │
│ ┌───────────┐ │  ├────────────────────────┤  │  ├─────────────────────┤  │
│ │ + חדש     │ │  │  Color Picker Group    │  │  │  Card Preview       │  │
│ ├───────────┤ │  │  ├─ bg-primary         │  │  │  ├─ File Card       │  │
│ │ ⚫ ערכה 1 │ │  │  ├─ bg-secondary       │  │  │  └─ Code Block      │  │
│ │   (פעיל)  │ │  │  ├─ primary            │  │  ├─────────────────────┤  │
│ ├───────────┤ │  │  └─ ...                │  │  │  Button Preview     │  │
│ │ ○ ערכה 2  │ │  ├────────────────────────┤  │  │  ├─ Primary         │  │
│ ├───────────┤ │  │  Glass Controls        │  │  │  └─ Secondary       │  │
│ │ ○ ערכה 3  │ │  │  ├─ Opacity slider     │  │  ├─────────────────────┤  │
│ └───────────┘ │  │  └─ Blur slider        │  │  │  Glass Card         │  │
│               │  ├────────────────────────┤  │  └─────────────────────┘  │
│ ───────────── │  │ [💾 שמור] [🔄 איפוס]  │  │                           │
│               │  │ [✓ הפעל] [🗑️ מחק]     │  │                           │
│               │  └────────────────────────┘  │                           │
└───────────────┴──────────────────────────────┴───────────────────────────┘
```

### 4.2 שינויים ב-HTML – סרגל צד

הוסף את הסרגל הצד בתחילת `.theme-builder-layout`:

```html
<div class="theme-builder-layout">
    <!-- Sidebar: My Themes -->
    <aside class="theme-builder-sidebar glass-card">
        <div class="sidebar-header">
            <h3>
                <i class="fas fa-palette"></i>
                הערכות שלי
            </h3>
            <button type="button" id="createNewThemeBtn" class="btn btn-primary btn-sm">
                <i class="fas fa-plus"></i>
                ערכה חדשה
            </button>
        </div>
        
        <div id="themesList" class="themes-list">
            <!-- יאוכלס דינמית -->
            <div class="themes-loading">
                <i class="fas fa-spinner fa-spin"></i>
                טוען...
            </div>
        </div>
        
        <div class="sidebar-footer">
            <small>
                <span id="themesCount">0</span>/<span id="themesMax">10</span> ערכות
            </small>
        </div>
    </aside>

    <!-- Control Panel (קיים) -->
    <div class="theme-builder-controls glass-card">
        <!-- ... הטופס הקיים ... -->
    </div>

    <!-- Live Preview (קיים) -->
    <div class="theme-builder-preview glass-card">
        <!-- ... התצוגה המקדימה הקיימת ... -->
    </div>
</div>
```

### 4.3 CSS לסרגל צד

```css
/* Theme Builder Layout - Updated for Sidebar */
.theme-builder-layout {
    display: grid;
    grid-template-columns: 280px 1fr 1fr;
    gap: 1.5rem;
    align-items: start;
}

@media (max-width: 1200px) {
    .theme-builder-layout {
        grid-template-columns: 240px 1fr;
    }
    .theme-builder-preview {
        grid-column: 1 / -1;
    }
}

@media (max-width: 768px) {
    .theme-builder-layout {
        grid-template-columns: 1fr;
    }
    .theme-builder-sidebar {
        order: -1;
    }
}

/* Sidebar Styles */
.theme-builder-sidebar {
    position: sticky;
    top: 1rem;
    max-height: calc(100vh - 2rem);
    overflow: hidden;
    display: flex;
    flex-direction: column;
}

.sidebar-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding-bottom: 1rem;
    border-bottom: 1px solid var(--glass-border);
    margin-bottom: 1rem;
}

.sidebar-header h3 {
    margin: 0;
    font-size: 1rem;
    display: flex;
    align-items: center;
    gap: 0.5rem;
}

.sidebar-header .btn-sm {
    padding: 0.4rem 0.8rem;
    font-size: 0.85rem;
}

/* Themes List */
.themes-list {
    flex: 1;
    overflow-y: auto;
    padding-right: 0.5rem; /* Space for scrollbar */
}

.themes-loading {
    text-align: center;
    padding: 2rem;
    color: var(--text-secondary);
}

.theme-item {
    display: flex;
    align-items: center;
    padding: 0.75rem;
    margin-bottom: 0.5rem;
    border-radius: 10px;
    background: var(--glass);
    border: 1px solid transparent;
    cursor: pointer;
    transition: all 0.2s ease;
}

.theme-item:hover {
    background: var(--glass-hover);
    border-color: var(--glass-border);
}

.theme-item.active {
    border-color: var(--primary);
    background: color-mix(in srgb, var(--primary) 15%, transparent);
}

.theme-item.selected {
    border-color: var(--secondary);
    box-shadow: 0 0 0 2px color-mix(in srgb, var(--secondary) 30%, transparent);
}

.theme-item-indicator {
    width: 12px;
    height: 12px;
    border-radius: 50%;
    margin-left: 0.75rem;
    flex-shrink: 0;
}

.theme-item.active .theme-item-indicator {
    background: var(--success);
    box-shadow: 0 0 6px var(--success);
}

.theme-item:not(.active) .theme-item-indicator {
    background: var(--glass-border);
}

.theme-item-content {
    flex: 1;
    min-width: 0;
}

.theme-item-name {
    font-weight: 600;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    color: var(--text-primary);
}

.theme-item-meta {
    font-size: 0.75rem;
    color: var(--text-secondary);
    margin-top: 0.25rem;
}

.theme-item-actions {
    display: flex;
    gap: 0.25rem;
    opacity: 0;
    transition: opacity 0.2s;
}

.theme-item:hover .theme-item-actions {
    opacity: 1;
}

.theme-item-btn {
    width: 28px;
    height: 28px;
    border-radius: 6px;
    border: none;
    background: var(--glass);
    color: var(--text-secondary);
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 0.8rem;
    transition: all 0.2s;
}

.theme-item-btn:hover {
    background: var(--glass-hover);
    color: var(--text-primary);
}

.theme-item-btn.danger:hover {
    background: var(--danger);
    color: white;
}

/* Sidebar Footer */
.sidebar-footer {
    padding-top: 1rem;
    border-top: 1px solid var(--glass-border);
    margin-top: auto;
    text-align: center;
    color: var(--text-secondary);
}

/* Empty State */
.themes-empty {
    text-align: center;
    padding: 2rem 1rem;
    color: var(--text-secondary);
}

.themes-empty i {
    font-size: 2rem;
    margin-bottom: 1rem;
    opacity: 0.5;
}

.themes-empty p {
    margin: 0;
}
```

### 4.4 JavaScript – ניהול ריבוי ערכות

```javascript
(function() {
    'use strict';
    
    // ========== State ==========
    let currentThemes = [];          // רשימת כל הערכות
    let selectedThemeId = null;      // הערכה שנבחרה לעריכה
    let isNewTheme = false;          // האם יוצרים ערכה חדשה
    let hasUnsavedChanges = false;   // שינויים שלא נשמרו
    
    // ========== DOM Elements ==========
    const themesList = document.getElementById('themesList');
    const themesCount = document.getElementById('themesCount');
    const themesMax = document.getElementById('themesMax');
    const createNewBtn = document.getElementById('createNewThemeBtn');
    
    // ========== API Functions ==========
    async function fetchThemes() {
        try {
            const res = await fetch('/api/themes');
            const data = await res.json();
            
            if (!res.ok || !data.ok) {
                throw new Error(data.error || 'fetch_failed');
            }
            
            currentThemes = data.themes || [];
            themesMax.textContent = data.max_allowed;
            
            renderThemesList();
            
            // בחר את הערכה הפעילה (או הראשונה)
            const activeTheme = currentThemes.find(t => t.is_active);
            if (activeTheme) {
                selectTheme(activeTheme.id);
            } else if (currentThemes.length > 0) {
                selectTheme(currentThemes[0].id);
            }
            
        } catch (err) {
            console.error('Failed to fetch themes:', err);
            showToast('שגיאה בטעינת הערכות', 'error');
        }
    }
    
    async function fetchThemeDetails(themeId) {
        try {
            const res = await fetch(`/api/themes/${themeId}`);
            const data = await res.json();
            
            if (!res.ok || !data.ok) {
                throw new Error(data.error || 'fetch_failed');
            }
            
            return data.theme;
            
        } catch (err) {
            console.error('Failed to fetch theme details:', err);
            showToast('שגיאה בטעינת פרטי הערכה', 'error');
            return null;
        }
    }
    
    async function createNewTheme(themeData) {
        try {
            const res = await fetch('/api/themes', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(themeData)
            });
            
            const data = await res.json();
            
            if (!res.ok || !data.ok) {
                throw new Error(data.error || 'create_failed');
            }
            
            showToast('הערכה נוצרה בהצלחה!', 'success');
            return data.theme_id;
            
        } catch (err) {
            console.error('Failed to create theme:', err);
            let msg = 'שגיאה ביצירת הערכה';
            if (err.message === 'max_themes_reached') msg = `הגעת למגבלת הערכות (${themesMax.textContent})`;
            if (err.message === 'invalid_color') msg = 'אחד הצבעים אינו תקין';
            showToast(msg, 'error');
            return null;
        }
    }
    
    async function updateExistingTheme(themeId, themeData) {
        try {
            const res = await fetch(`/api/themes/${themeId}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(themeData)
            });
            
            const data = await res.json();
            
            if (!res.ok || !data.ok) {
                throw new Error(data.error || 'update_failed');
            }
            
            showToast('הערכה עודכנה בהצלחה!', 'success');
            return true;
            
        } catch (err) {
            console.error('Failed to update theme:', err);
            showToast('שגיאה בעדכון הערכה', 'error');
            return false;
        }
    }
    
    async function activateTheme(themeId) {
        try {
            const res = await fetch(`/api/themes/${themeId}/activate`, {
                method: 'POST'
            });
            
            const data = await res.json();
            
            if (!res.ok || !data.ok) {
                throw new Error(data.error || 'activate_failed');
            }
            
            showToast('הערכה הופעלה! מרענן...', 'success');
            setTimeout(() => location.reload(), 1000);
            
        } catch (err) {
            console.error('Failed to activate theme:', err);
            showToast('שגיאה בהפעלת הערכה', 'error');
        }
    }
    
    async function deleteTheme(themeId) {
        if (!confirm('האם למחוק את הערכה? פעולה זו אינה ניתנת לביטול.')) {
            return;
        }
        
        try {
            const res = await fetch(`/api/themes/${themeId}`, {
                method: 'DELETE'
            });
            
            const data = await res.json();
            
            if (!res.ok || !data.ok) {
                throw new Error(data.error || 'delete_failed');
            }
            
            showToast('הערכה נמחקה', 'success');
            
            if (data.was_active) {
                setTimeout(() => location.reload(), 1000);
            } else {
                await fetchThemes();
            }
            
        } catch (err) {
            console.error('Failed to delete theme:', err);
            showToast('שגיאה במחיקת הערכה', 'error');
        }
    }
    
    // ========== Render Functions ==========
    function renderThemesList() {
        themesCount.textContent = currentThemes.length;
        
        if (currentThemes.length === 0) {
            themesList.innerHTML = `
                <div class="themes-empty">
                    <i class="fas fa-palette"></i>
                    <p>עדיין אין לך ערכות מותאמות</p>
                    <p><small>לחץ "ערכה חדשה" ליצירת הראשונה</small></p>
                </div>
            `;
            return;
        }
        
        themesList.innerHTML = currentThemes.map(theme => `
            <div class="theme-item ${theme.is_active ? 'active' : ''} ${selectedThemeId === theme.id ? 'selected' : ''}"
                 data-theme-id="${theme.id}">
                <div class="theme-item-indicator" 
                     title="${theme.is_active ? 'ערכה פעילה' : 'לחץ להפעלה'}"></div>
                <div class="theme-item-content">
                    <div class="theme-item-name">${escapeHtml(theme.name)}</div>
                    <div class="theme-item-meta">
                        ${theme.is_active ? '<i class="fas fa-check-circle"></i> פעילה' : ''}
                        ${!theme.is_active && theme.updated_at ? formatDate(theme.updated_at) : ''}
                    </div>
                </div>
                <div class="theme-item-actions">
                    ${!theme.is_active ? `
                        <button type="button" class="theme-item-btn activate-btn" 
                                title="הפעל ערכה" data-action="activate">
                            <i class="fas fa-check"></i>
                        </button>
                    ` : ''}
                    <button type="button" class="theme-item-btn danger delete-btn" 
                            title="מחק ערכה" data-action="delete">
                        <i class="fas fa-trash"></i>
                    </button>
                </div>
            </div>
        `).join('');
        
        // Bind events
        themesList.querySelectorAll('.theme-item').forEach(item => {
            item.addEventListener('click', (e) => {
                const action = e.target.closest('[data-action]')?.dataset.action;
                const themeId = item.dataset.themeId;
                
                if (action === 'activate') {
                    activateTheme(themeId);
                } else if (action === 'delete') {
                    deleteTheme(themeId);
                } else {
                    selectTheme(themeId);
                }
            });
        });
    }
    
    async function selectTheme(themeId) {
        // בדיקת שינויים שלא נשמרו
        if (hasUnsavedChanges && !confirm('יש שינויים שלא נשמרו. להמשיך?')) {
            return;
        }
        
        selectedThemeId = themeId;
        isNewTheme = false;
        
        // עדכון ה-UI
        themesList.querySelectorAll('.theme-item').forEach(item => {
            item.classList.toggle('selected', item.dataset.themeId === themeId);
        });
        
        // טעינת פרטי הערכה
        const theme = await fetchThemeDetails(themeId);
        if (theme) {
            loadThemeIntoForm(theme);
        }
        
        hasUnsavedChanges = false;
        updateFormButtons();
    }
    
    function loadThemeIntoForm(theme) {
        // שם הערכה
        document.getElementById('themeName').value = theme.name || '';
        
        // טעינת צבעים ל-pickers
        const variables = theme.variables || {};
        
        Object.entries(VAR_MAP).forEach(([pickrId, varName]) => {
            const textInput = document.getElementById(pickrId + 'Text');
            const value = variables[varName] || DEFAULT_VALUES[varName];
            
            if (textInput) {
                textInput.value = value;
            }
            
            if (pickrInstances[pickrId]) {
                try {
                    pickrInstances[pickrId].setColor(value);
                } catch (e) {
                    // ignore invalid colors
                }
            }
            
            updatePreview(varName, value);
        });
        
        // Glass sliders
        if (variables['--glass']) {
            const match = variables['--glass'].match(/[\d.]+(?=\))/);
            if (match) {
                const opacitySlider = document.getElementById('glassOpacity');
                opacitySlider.value = Math.round(parseFloat(match[0]) * 100);
                document.getElementById('glassOpacityValue').textContent = opacitySlider.value + '%';
            }
        }
        
        if (variables['--glass-blur']) {
            const blurSlider = document.getElementById('glassBlur');
            blurSlider.value = parseInt(variables['--glass-blur']);
            document.getElementById('glassBlurValue').textContent = blurSlider.value + 'px';
        }
    }
    
    function clearFormForNewTheme() {
        // בדיקת שינויים שלא נשמרו
        if (hasUnsavedChanges && !confirm('יש שינויים שלא נשמרו. להמשיך?')) {
            return;
        }
        
        selectedThemeId = null;
        isNewTheme = true;
        
        // הסר selection מרשימת הערכות
        themesList.querySelectorAll('.theme-item').forEach(item => {
            item.classList.remove('selected');
        });
        
        // נקה את השם
        document.getElementById('themeName').value = '';
        document.getElementById('themeName').focus();
        
        // אפס לברירות מחדל
        Object.entries(VAR_MAP).forEach(([pickrId, varName]) => {
            const textInput = document.getElementById(pickrId + 'Text');
            const value = DEFAULT_VALUES[varName];
            
            if (textInput) {
                textInput.value = value;
            }
            
            if (pickrInstances[pickrId]) {
                try {
                    pickrInstances[pickrId].setColor(value);
                } catch (e) {}
            }
            
            updatePreview(varName, value);
        });
        
        // Reset glass sliders
        const opacitySlider = document.getElementById('glassOpacity');
        opacitySlider.value = 10;
        document.getElementById('glassOpacityValue').textContent = '10%';
        
        const blurSlider = document.getElementById('glassBlur');
        blurSlider.value = 20;
        document.getElementById('glassBlurValue').textContent = '20px';
        
        updatePreview('--glass', 'rgba(255, 255, 255, 0.10)');
        updatePreview('--glass-blur', '20px');
        
        hasUnsavedChanges = false;
        updateFormButtons();
    }
    
    function updateFormButtons() {
        const saveBtn = document.getElementById('saveThemeBtn');
        const activateBtn = document.getElementById('activateThemeBtn');
        const deleteBtn = document.getElementById('deleteThemeBtn');
        
        if (isNewTheme) {
            saveBtn.innerHTML = '<i class="fas fa-plus"></i> צור ערכה';
            if (activateBtn) activateBtn.disabled = true;
            if (deleteBtn) deleteBtn.disabled = true;
        } else {
            saveBtn.innerHTML = '<i class="fas fa-save"></i> שמור שינויים';
            if (activateBtn) activateBtn.disabled = false;
            if (deleteBtn) deleteBtn.disabled = false;
        }
    }
    
    // ========== Save Handler ==========
    async function handleSave(e) {
        e.preventDefault();
        
        const name = document.getElementById('themeName').value.trim();
        if (!name) {
            showToast('נא להזין שם לערכה', 'error');
            document.getElementById('themeName').focus();
            return;
        }
        
        const variables = collectThemeValues();
        
        if (isNewTheme) {
            // יצירת ערכה חדשה
            const newId = await createNewTheme({
                name: name,
                variables: variables,
                activate: false
            });
            
            if (newId) {
                isNewTheme = false;
                selectedThemeId = newId;
                await fetchThemes();
                selectTheme(newId);
            }
        } else {
            // עדכון ערכה קיימת
            const success = await updateExistingTheme(selectedThemeId, {
                name: name,
                variables: variables
            });
            
            if (success) {
                await fetchThemes();
            }
        }
        
        hasUnsavedChanges = false;
    }
    
    // ========== Utilities ==========
    function escapeHtml(str) {
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }
    
    function formatDate(isoString) {
        try {
            const date = new Date(isoString);
            return date.toLocaleDateString('he-IL', { 
                day: 'numeric', 
                month: 'short' 
            });
        } catch (e) {
            return '';
        }
    }
    
    // ========== Init ==========
    function initMultiTheme() {
        // טען רשימת ערכות
        fetchThemes();
        
        // כפתור ערכה חדשה
        createNewBtn.addEventListener('click', clearFormForNewTheme);
        
        // מעקב אחר שינויים
        document.querySelectorAll('.color-text, #themeName').forEach(input => {
            input.addEventListener('input', () => {
                hasUnsavedChanges = true;
            });
        });
        
        document.querySelectorAll('input[type="range"]').forEach(slider => {
            slider.addEventListener('input', () => {
                hasUnsavedChanges = true;
            });
        });
        
        // עדכון handler השמירה
        document.getElementById('themeBuilderForm').removeEventListener('submit', saveTheme);
        document.getElementById('themeBuilderForm').addEventListener('submit', handleSave);
        
        // כפתור הפעלה
        const activateBtn = document.getElementById('activateThemeBtn');
        if (activateBtn) {
            activateBtn.addEventListener('click', () => {
                if (selectedThemeId) {
                    activateTheme(selectedThemeId);
                }
            });
        }
        
        // כפתור מחיקה
        const deleteBtn = document.getElementById('deleteThemeBtn');
        if (deleteBtn) {
            deleteBtn.addEventListener('click', () => {
                if (selectedThemeId) {
                    deleteTheme(selectedThemeId);
                }
            });
        }
        
        // אזהרה לפני יציאה עם שינויים שלא נשמרו
        window.addEventListener('beforeunload', (e) => {
            if (hasUnsavedChanges) {
                e.preventDefault();
                e.returnValue = '';
            }
        });
    }
    
    // Start
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initMultiTheme);
    } else {
        initMultiTheme();
    }
})();
```

### 4.5 עדכון כפתורי הפעולות בטופס

עדכן את סקשן `.form-actions` בתבנית:

```html
<!-- Actions - Updated for Multi-Theme -->
<div class="form-actions">
    <button type="submit" class="btn btn-primary" id="saveThemeBtn">
        <i class="fas fa-save"></i>
        שמור שינויים
    </button>
    <button type="button" class="btn btn-success" id="activateThemeBtn">
        <i class="fas fa-check"></i>
        הפעל ערכה זו
    </button>
    <button type="button" class="btn btn-secondary" id="resetThemeBtn">
        <i class="fas fa-undo"></i>
        איפוס לברירות מחדל
    </button>
    <button type="button" class="btn btn-danger" id="deleteThemeBtn">
        <i class="fas fa-trash"></i>
        מחק ערכה
    </button>
</div>
```

---

## מיגרציה מהמבנה הקודם

### 5.1 סקריפט מיגרציה

```python
"""
scripts/migrate_custom_themes.py
מיגרציה מ-custom_theme (אובייקט) ל-custom_themes (מערך)
"""
import uuid
from datetime import datetime, timezone
from pymongo import MongoClient

# התחבר ל-DB
client = MongoClient("mongodb://localhost:27017")
db = client.codebot  # שנה לשם ה-DB שלך

def migrate_single_theme_to_array():
    """העבר משתמשים עם custom_theme בודד למבנה המערך החדש."""
    
    # מצא משתמשים עם המבנה הישן
    users_to_migrate = db.users.find(
        {
            "custom_theme": {"$exists": True},
            "custom_themes": {"$exists": False}
        },
        {"_id": 1, "custom_theme": 1}
    )
    
    migrated = 0
    errors = 0
    
    for user in users_to_migrate:
        try:
            old_theme = user.get("custom_theme")
            if not old_theme:
                continue
            
            # בנה ערכה חדשה במבנה המערך
            new_theme = {
                "id": str(uuid.uuid4()),
                "name": old_theme.get("name", "הערכה שלי"),
                "description": old_theme.get("description", ""),
                "is_active": old_theme.get("is_active", True),
                "created_at": old_theme.get("updated_at", datetime.now(timezone.utc)),
                "updated_at": old_theme.get("updated_at", datetime.now(timezone.utc)),
                "variables": old_theme.get("variables", {}),
            }
            
            # עדכן את המשתמש
            db.users.update_one(
                {"_id": user["_id"]},
                {
                    "$set": {"custom_themes": [new_theme]},
                    "$unset": {"custom_theme": ""}
                }
            )
            
            migrated += 1
            print(f"✓ Migrated user {user['_id']}")
            
        except Exception as e:
            errors += 1
            print(f"✗ Error migrating user {user['_id']}: {e}")
    
    print(f"\n=== Migration Complete ===")
    print(f"Migrated: {migrated}")
    print(f"Errors: {errors}")

def verify_migration():
    """בדוק שהמיגרציה הצליחה."""
    
    # ספור משתמשים עם המבנה הישן
    old_count = db.users.count_documents({"custom_theme": {"$exists": True}})
    
    # ספור משתמשים עם המבנה החדש
    new_count = db.users.count_documents({"custom_themes": {"$exists": True}})
    
    print(f"Users with old schema (custom_theme): {old_count}")
    print(f"Users with new schema (custom_themes): {new_count}")
    
    if old_count == 0:
        print("✓ All users migrated successfully!")
    else:
        print(f"⚠ {old_count} users still need migration")

if __name__ == "__main__":
    print("=== Theme Migration Script ===\n")
    
    # הרץ מיגרציה
    migrate_single_theme_to_array()
    
    # אמת
    verify_migration()
```

### 5.2 הרצת המיגרציה

```bash
# גיבוי לפני מיגרציה
mongodump --db codebot --collection users --out ./backup_before_theme_migration

# הרץ את הסקריפט
python scripts/migrate_custom_themes.py

# אמת
python -c "from scripts.migrate_custom_themes import verify_migration; verify_migration()"
```

---

## בדיקות

### 6.1 Unit Tests

```python
# tests/test_multi_theme_api.py
import pytest
import uuid
from unittest.mock import MagicMock, patch
from webapp.app import app

@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client

@pytest.fixture
def mock_db():
    with patch('webapp.app.db') as mock:
        yield mock

@pytest.fixture
def logged_in_session(client):
    with client.session_transaction() as sess:
        sess['user_id'] = 'test_user_123'
    return client


class TestGetThemes:
    def test_unauthorized(self, client):
        res = client.get('/api/themes')
        assert res.status_code == 401
    
    def test_empty_list(self, logged_in_session, mock_db):
        mock_db.users.find_one.return_value = {"custom_themes": []}
        
        res = logged_in_session.get('/api/themes')
        data = res.get_json()
        
        assert res.status_code == 200
        assert data['ok'] == True
        assert data['themes'] == []
        assert data['count'] == 0
    
    def test_with_themes(self, logged_in_session, mock_db):
        mock_db.users.find_one.return_value = {
            "custom_themes": [
                {"id": "abc", "name": "Theme 1", "is_active": True},
                {"id": "def", "name": "Theme 2", "is_active": False}
            ]
        }
        
        res = logged_in_session.get('/api/themes')
        data = res.get_json()
        
        assert res.status_code == 200
        assert len(data['themes']) == 2
        assert data['themes'][0]['name'] == "Theme 1"


class TestCreateTheme:
    def test_max_themes_limit(self, logged_in_session, mock_db):
        # סימולציה של 10 ערכות קיימות
        mock_db.users.find_one.return_value = {
            "custom_themes": [{"id": str(i)} for i in range(10)]
        }
        
        res = logged_in_session.post('/api/themes', json={
            "name": "New Theme",
            "variables": {}
        })
        
        assert res.status_code == 400
        assert res.get_json()['error'] == 'max_themes_reached'
    
    def test_missing_name(self, logged_in_session, mock_db):
        mock_db.users.find_one.return_value = {"custom_themes": []}
        
        res = logged_in_session.post('/api/themes', json={
            "variables": {"--primary": "#ff0000"}
        })
        
        assert res.status_code == 400
        assert res.get_json()['error'] == 'missing_name'
    
    def test_success(self, logged_in_session, mock_db):
        mock_db.users.find_one.return_value = {"custom_themes": []}
        mock_db.users.update_one.return_value = MagicMock(modified_count=1)
        
        res = logged_in_session.post('/api/themes', json={
            "name": "My New Theme",
            "variables": {"--primary": "#667eea"}
        })
        
        data = res.get_json()
        assert res.status_code == 200
        assert data['ok'] == True
        assert 'theme_id' in data


class TestUpdateTheme:
    def test_not_found(self, logged_in_session, mock_db):
        mock_db.users.find_one.return_value = None
        
        res = logged_in_session.put('/api/themes/nonexistent', json={
            "name": "Updated Name"
        })
        
        assert res.status_code == 404
        assert res.get_json()['error'] == 'theme_not_found'
    
    def test_success(self, logged_in_session, mock_db):
        mock_db.users.find_one.return_value = {
            "custom_themes": [{"id": "abc", "name": "Old Name"}]
        }
        mock_db.users.update_one.return_value = MagicMock(modified_count=1)
        
        res = logged_in_session.put('/api/themes/abc', json={
            "name": "New Name"
        })
        
        assert res.status_code == 200
        assert res.get_json()['ok'] == True


class TestActivateTheme:
    def test_not_found(self, logged_in_session, mock_db):
        mock_db.users.find_one.return_value = None
        
        res = logged_in_session.post('/api/themes/nonexistent/activate')
        
        assert res.status_code == 404
    
    def test_success(self, logged_in_session, mock_db):
        mock_db.users.find_one.return_value = {
            "custom_themes": [{"id": "abc", "is_active": False}]
        }
        mock_db.users.update_one.return_value = MagicMock(modified_count=1)
        
        res = logged_in_session.post('/api/themes/abc/activate')
        
        assert res.status_code == 200
        assert res.get_json()['active_theme_id'] == 'abc'


class TestDeleteTheme:
    def test_delete_active_theme(self, logged_in_session, mock_db):
        mock_db.users.find_one.return_value = {
            "custom_themes": [{"id": "abc", "is_active": True}]
        }
        mock_db.users.update_one.return_value = MagicMock(modified_count=1)
        
        res = logged_in_session.delete('/api/themes/abc')
        data = res.get_json()
        
        assert res.status_code == 200
        assert data['was_active'] == True
        assert data['reset_to'] == 'classic'
```

### 6.2 Integration Tests

```python
# tests/test_multi_theme_integration.py
import pytest
from datetime import datetime, timezone

class TestMultiThemeFlow:
    """בדיקת זרימה מלאה: יצירה → עדכון → הפעלה → מחיקה"""
    
    def test_full_flow(self, client, logged_in_user, real_db):
        # 1. יצירת ערכה ראשונה
        res1 = client.post('/api/themes', json={
            "name": "ערכה כהה",
            "variables": {"--bg-primary": "#1a1a2e", "--primary": "#e94560"}
        })
        assert res1.status_code == 200
        theme1_id = res1.get_json()['theme_id']
        
        # 2. יצירת ערכה שנייה
        res2 = client.post('/api/themes', json={
            "name": "ערכה בהירה",
            "variables": {"--bg-primary": "#ffffff", "--primary": "#007bff"}
        })
        assert res2.status_code == 200
        theme2_id = res2.get_json()['theme_id']
        
        # 3. בדיקת רשימה
        res_list = client.get('/api/themes')
        assert res_list.get_json()['count'] == 2
        
        # 4. הפעלת ערכה ראשונה
        res_activate = client.post(f'/api/themes/{theme1_id}/activate')
        assert res_activate.status_code == 200
        
        # 5. וידוא שרק ערכה אחת פעילה
        res_check = client.get('/api/themes')
        themes = res_check.get_json()['themes']
        active_count = sum(1 for t in themes if t['is_active'])
        assert active_count == 1
        
        # 6. עדכון ערכה
        res_update = client.put(f'/api/themes/{theme2_id}', json={
            "name": "ערכה בהירה מעודכנת"
        })
        assert res_update.status_code == 200
        
        # 7. מחיקת ערכה לא פעילה
        res_delete = client.delete(f'/api/themes/{theme2_id}')
        assert res_delete.status_code == 200
        assert res_delete.get_json()['was_active'] == False
        
        # 8. וידוא מחיקה
        res_final = client.get('/api/themes')
        assert res_final.get_json()['count'] == 1
```

### 6.3 E2E Tests (Playwright)

```javascript
// tests/e2e/theme-builder-multi.spec.ts
import { test, expect } from '@playwright/test';

test.describe('Multi-Theme Builder', () => {
    test.beforeEach(async ({ page }) => {
        // התחבר ונווט לדף
        await page.goto('/login');
        await page.fill('#username', 'testuser');
        await page.fill('#password', 'testpass');
        await page.click('button[type="submit"]');
        await page.goto('/settings/theme-builder');
    });
    
    test('should display themes sidebar', async ({ page }) => {
        const sidebar = page.locator('.theme-builder-sidebar');
        await expect(sidebar).toBeVisible();
        await expect(sidebar.locator('h3')).toContainText('הערכות שלי');
    });
    
    test('should create new theme', async ({ page }) => {
        // לחץ על "ערכה חדשה"
        await page.click('#createNewThemeBtn');
        
        // מלא שם
        await page.fill('#themeName', 'ערכת הבדיקה שלי');
        
        // שנה צבע
        await page.click('#primary');
        await page.fill('.pcr-result', '#ff5500');
        await page.click('.pcr-save');
        
        // שמור
        await page.click('#saveThemeBtn');
        
        // בדוק toast הצלחה
        await expect(page.locator('.theme-toast')).toContainText('נוצרה בהצלחה');
        
        // בדוק שהערכה מופיעה ברשימה
        await expect(page.locator('.theme-item')).toContainText('ערכת הבדיקה שלי');
    });
    
    test('should switch between themes', async ({ page }) => {
        // צור שתי ערכות
        await page.click('#createNewThemeBtn');
        await page.fill('#themeName', 'ערכה 1');
        await page.click('#saveThemeBtn');
        await page.waitForSelector('.theme-toast');
        
        await page.click('#createNewThemeBtn');
        await page.fill('#themeName', 'ערכה 2');
        await page.click('#saveThemeBtn');
        await page.waitForSelector('.theme-toast');
        
        // לחץ על ערכה 1
        await page.click('.theme-item:has-text("ערכה 1")');
        
        // בדוק שהשם נטען לטופס
        await expect(page.locator('#themeName')).toHaveValue('ערכה 1');
    });
    
    test('should activate theme', async ({ page }) => {
        // בחר ערכה קיימת
        await page.click('.theme-item:first-child');
        
        // הפעל
        await page.click('#activateThemeBtn');
        
        // בדוק שהדף מתרענן והערכה מסומנת כפעילה
        await page.waitForNavigation();
        await expect(page.locator('.theme-item.active')).toBeVisible();
    });
    
    test('should warn about unsaved changes', async ({ page }) => {
        // בחר ערכה
        await page.click('.theme-item:first-child');
        
        // שנה משהו
        await page.fill('#themeName', 'שם חדש');
        
        // נסה לעבור לערכה אחרת
        page.on('dialog', dialog => {
            expect(dialog.message()).toContain('שינויים שלא נשמרו');
            dialog.dismiss();
        });
        
        await page.click('.theme-item:last-child');
    });
    
    test('should delete theme', async ({ page }) => {
        // בחר ערכה
        await page.click('.theme-item:first-child');
        
        // מחק
        page.on('dialog', dialog => dialog.accept());
        await page.click('#deleteThemeBtn');
        
        // בדוק toast
        await expect(page.locator('.theme-toast')).toContainText('נמחקה');
    });
});
```

---

## צ'קליסט למימוש

### Backend & Database
- [ ] הוסף קבועים: `MAX_THEMES_PER_USER`, מגבלות אורך
- [ ] מימוש `GET /api/themes` – רשימת ערכות
- [ ] מימוש `GET /api/themes/<id>` – פרטי ערכה
- [ ] מימוש `POST /api/themes` – יצירת ערכה חדשה
- [ ] מימוש `PUT /api/themes/<id>` – עדכון ערכה
- [ ] מימוש `POST /api/themes/<id>/activate` – הפעלת ערכה
- [ ] מימוש `POST /api/themes/deactivate` – ביטול כל הערכות
- [ ] מימוש `DELETE /api/themes/<id>` – מחיקת ערכה
- [ ] עדכון `get_custom_theme()` לתמוך במערך
- [ ] הוספת אינדקסים ל-MongoDB
- [ ] כתיבת סקריפט מיגרציה

### Frontend – Sidebar
- [ ] הוסף HTML לסרגל צד
- [ ] הוסף CSS לסרגל צד ורשימת ערכות
- [ ] אינדיקציה לערכה פעילה (עיגול ירוק)
- [ ] אינדיקציה לערכה נבחרת (מסגרת)
- [ ] כפתור "ערכה חדשה"

### Frontend – JavaScript
- [ ] State management: `currentThemes`, `selectedThemeId`, `isNewTheme`
- [ ] `fetchThemes()` – טעינת רשימה
- [ ] `renderThemesList()` – רינדור הרשימה
- [ ] `selectTheme()` – בחירת ערכה לעריכה
- [ ] `clearFormForNewTheme()` – ניקוי טופס לערכה חדשה
- [ ] `handleSave()` – שמירה (יצירה או עדכון)
- [ ] מעקב שינויים שלא נשמרו (`hasUnsavedChanges`)
- [ ] אזהרת `beforeunload`

### Frontend – UX
- [ ] עדכון כפתורי פעולות (הפעל/מחק)
- [ ] מונה ערכות (X/10)
- [ ] Empty state כשאין ערכות
- [ ] Loading state בטעינה ראשונית
- [ ] Toast notifications לכל פעולה

### בדיקות
- [ ] Unit tests ל-API
- [ ] Integration tests לזרימה מלאה
- [ ] E2E tests (Playwright)
- [ ] בדיקת מיגרציה על נתונים קיימים

### תיעוד
- [ ] עדכון `docs/webapp/theming_and_css.rst`
- [ ] הוספת סעיף "ניהול ריבוי ערכות"
- [ ] עדכון API reference

---

## הערות נוספות

### תאימות לאחור

- הקוד תומך גם במבנה הישן (`custom_theme`) וגם בחדש (`custom_themes`)
- `get_custom_theme()` בודק קודם את המבנה החדש, ואז fallback לישן
- מומלץ להריץ מיגרציה אחרי הפריסה

### הרחבות עתידיות (מחוץ לסקופ)

❌ שיתוף ערכות עם משתמשים אחרים  
❌ ספריית ערכות קהילתית  
❌ ייבוא/ייצוא JSON  
❌ שכפול ערכה קיימת  
❌ מיון/סינון ערכות

### ביצועים

- רשימת הערכות לא כוללת `variables` (חוסך bandwidth)
- `variables` נטענים רק בבחירת ערכה ספציפית
- אינדקסים על `custom_themes.id` ו-`custom_themes.is_active`

---

> **קישור למדריך הקודם:** [חלק א' – מימוש Theme Builder](./theme_builder_implementation_guide.md)
