# מדריך מימוש מערכת הפצת ערכות נושא (Shared Theme Library) 🎨

> **מטרה:** לאפשר למנהלי מערכת לפרסם ערכות נושא לכלל המשתמשים
> 
> **מבוסס על:** קוד קיים של Theme Builder, מבנה API קיים, ו-MongoDB

---

## תוכן עניינים

1. [סקירת מצב קיים](#סקירת-מצב-קיים)
2. [ארכיטקטורה מוצעת](#ארכיטקטורה-מוצעת)
3. [שלב 1: מסד נתונים (MongoDB)](#שלב-1-מסד-נתונים-mongodb)
4. [שלב 2: Backend Service](#שלב-2-backend-service)
5. [שלב 3: API Routes](#שלב-3-api-routes)
6. [שלב 4: עדכון Theme Builder](#שלב-4-עדכון-theme-builder)
7. [שלב 5: עדכון דף הגדרות](#שלב-5-עדכון-דף-הגדרות)
8. [שלב 6: בדיקות](#שלב-6-בדיקות)
9. [צ'קליסט למימוש](#צקליסט-למימוש)
10. [🔑 אינטגרציה עם VS Code Import](#אינטגרציה-עם-vs-code-import)
11. [🎨 מערכת CSS לערכות משותפות](#מערכת-css-לערכות-משותפות)

---

## סקירת מצב קיים

### מבנה הפרויקט הרלוונטי

```
webapp/
├── app.py                           # Flask application - Theme API שורות 11094-11501
├── templates/
│   ├── base.html                    # תבנית בסיס – CSS variables + theme injection
│   ├── settings.html                # דף הגדרות (כולל בחירת ערכה)
│   └── settings/
│       └── theme_builder.html       # בונה ערכות נושא
database/
├── repository.py                    # Repository pattern לגישה ל-DB
├── manager.py                       # Database Manager
services/
├── (כאן יווצר SharedThemeService)
tests/
└── test_theme_builder_api.py        # טסטים קיימים ל-theme API
```

### API קיים לערכות נושא

```python
# webapp/app.py שורות 11094-11501
GET    /api/themes               # רשימת ערכות המשתמש
GET    /api/themes/<id>          # פרטי ערכה ספציפית
POST   /api/themes               # יצירת ערכה חדשה
PUT    /api/themes/<id>          # עדכון ערכה קיימת
POST   /api/themes/<id>/activate # הפעלת ערכה
DELETE /api/themes/<id>          # מחיקת ערכה
```

### מבנה users collection (קיים)

```python
{
    "_id": user_id,
    "ui_prefs": {
        "theme": "classic",        # classic/ocean/custom/shared:<id>
        ...
    },
    "custom_themes": [             # ערכות אישיות של המשתמש
        {
            "id": "uuid-1",
            "name": "הערכה שלי",
            "is_active": True,
            "variables": {...}
        }
    ]
}
```

### בדיקת הרשאת Admin (קיים)

```python
# webapp/app.py שורות 3177-3184
def is_admin(user_id: int) -> bool:
    """בודק אם משתמש הוא אדמין"""
    admin_ids_env = os.getenv('ADMIN_USER_IDS', '')
    admin_ids_list = admin_ids_env.split(',') if admin_ids_env else []
    ...
```

---

## ארכיטקטורה מוצעת

### תרשים זרימה

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        Admin Flow (Theme Builder)                        │
├─────────────────────────────────────────────────────────────────────────┤
│  1. Admin יוצר ערכה ב-Theme Builder                                      │
│  2. לוחץ "פרסם לכולם" (Publish to All)                                   │
│  3. מזין slug (cyber_purple) ושם לתצוגה (Cyber Purple)                  │
│  4. API שומר ל-shared_themes collection                                  │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                          MongoDB: shared_themes                          │
├─────────────────────────────────────────────────────────────────────────┤
│  {                                                                       │
│    "_id": "cyber_purple",         // slug ייחודי                        │
│    "name": "Cyber Purple",        // שם לתצוגה                          │
│    "colors": { "--primary": "#...", ... },                              │
│    "created_by": 6865105071,      // user_id של Admin                   │
│    "created_at": ISODate(...),                                          │
│    "is_active": true              // אפשרות להסתיר                      │
│  }                                                                       │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                        User Flow (Settings Page)                         │
├─────────────────────────────────────────────────────────────────────────┤
│  GET /api/themes/list מחזיר:                                             │
│  ┌────────────────┐  ┌────────────────┐  ┌────────────────┐             │
│  │  Built-in      │  │  Shared        │  │  Custom        │             │
│  │  • Classic     │  │  • Cyber Purple│  │  • הערכה שלי   │             │
│  │  • Ocean       │  │  • Winter      │  │                │             │
│  │  • Dark        │  │    Featured ⭐  │  │                │             │
│  └────────────────┘  └────────────────┘  └────────────────┘             │
└─────────────────────────────────────────────────────────────────────────┘
```

### עקרונות מפתח

1. **Collection נפרד** – `shared_themes` מנותק מ-`users` לביצועים וניהול
2. **Slug-based ID** – שם באנגלית כ-`_id` במקום UUID (יותר קריא)
3. **Admin-only לפרסום/מחיקה** – משתמשים רגילים רק צופים
4. **Merge בצד שרת** – API אחד מחזיר את כל הסוגים מאוחדים

---

## שלב 1: מסד נתונים (MongoDB)

### 1.1 יצירת Collection חדש

הוסף `shared_themes` ל-Database Manager:

```python
# database/manager.py - הוסף ל-__init__

class DatabaseManager:
    def __init__(self, connection_string: Optional[str] = None):
        # ... קוד קיים ...
        
        # קולקשנים קיימים
        self.collection = self.db.code_snippets
        self.large_files_collection = self.db.large_files
        # ...
        
        # קולקשן חדש לערכות נושא ציבוריות
        self.shared_themes_collection = self.db.shared_themes
```

### 1.2 מבנה מסמך SharedTheme

```python
# מבנה מסמך ב-shared_themes collection
{
    "_id": "cyber_purple",              # slug באנגלית (מזהה ייחודי)
    "name": "Cyber Purple",             # שם לתצוגה (עברית/אנגלית)
    "description": "ערכה סגולה חדשנית", # תיאור קצר (אופציונלי)
    "colors": {                         # CSS Variables
        "--bg-primary": "#0d0221",
        "--bg-secondary": "#1a0a2e",
        "--primary": "#7b2cbf",
        "--secondary": "#c77dff",
        "--text-primary": "#e0aaff",
        "--card-bg": "rgba(123, 44, 191, 0.15)",
        "--glass": "rgba(199, 125, 255, 0.1)",
        "--glass-border": "rgba(199, 125, 255, 0.2)",
        "--glass-blur": "20px",
        "--md-surface": "#0d0221",
        "--md-text": "#e0aaff",
        "--btn-primary-bg": "#7b2cbf",
        "--btn-primary-color": "#ffffff"
    },
    "created_by": 6865105071,           # user_id של מי שיצר
    "created_at": ISODate("2025-01-01T00:00:00Z"),
    "updated_at": ISODate("2025-01-01T00:00:00Z"),
    "is_active": true,                  # אפשרות להסתיר זמנית
    "is_featured": false,               # תגית "מומלץ" (אופציונלי)
    "order": 0                          # סדר תצוגה (אופציונלי)
}
```

### 1.3 אינדקסים מומלצים

```python
# scripts/create_shared_themes_indexes.py
from database.manager import db

# אינדקס לסינון ערכות פעילות בלבד
db.shared_themes.create_index([("is_active", 1)])

# אינדקס למיון לפי תאריך יצירה
db.shared_themes.create_index([("created_at", -1)])

# אינדקס לחיפוש לפי יוצר
db.shared_themes.create_index([("created_by", 1)])
```

---

## שלב 2: Backend Service

### 2.1 יצירת SharedThemeService

צור קובץ חדש `services/shared_theme_service.py`:

```python
"""
services/shared_theme_service.py
שירות לניהול ערכות נושא ציבוריות (Shared Themes)
"""
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ============= קבועים =============

# Regex לבדיקת slug תקין (אותיות קטנות, מספרים, קו תחתון)
VALID_SLUG_REGEX = re.compile(r'^[a-z][a-z0-9_]{2,29}$')

# שדות צבע מותרים (מבוסס על ALLOWED_VARIABLES מ-app.py)
ALLOWED_COLOR_VARIABLES = {
    '--bg-primary', '--bg-secondary', '--card-bg',
    '--primary', '--secondary',
    '--text-primary', '--text-secondary',
    '--glass', '--glass-border', '--glass-hover', '--glass-blur',
    '--md-surface', '--md-text',
    '--btn-primary-bg', '--btn-primary-color',
}

# Regex לבדיקת צבע תקין (מותאם מ-app.py)
VALID_COLOR_REGEX = re.compile(
    r'^('
    r'#[0-9a-fA-F]{6}'
    r'|#[0-9a-fA-F]{8}'
    r'|rgba?\(\s*\d{1,3}\s*,\s*\d{1,3}\s*,\s*\d{1,3}\s*(,\s*[\d.]+\s*)?\)'
    r'|var\(--[a-zA-Z0-9_-]+\)'
    r'|color-mix\(in\s+srgb\s*,\s*[^)]+\)'
    r')$'
)

MAX_NAME_LENGTH = 50
MAX_DESCRIPTION_LENGTH = 200

# ערכות מובנות (Built-in) – קבועות בקוד
BUILTIN_THEMES = [
    {"id": "classic", "name": "קלאסי", "type": "builtin"},
    {"id": "ocean", "name": "אוקיינוס", "type": "builtin"},
    {"id": "nebula", "name": "נבולה", "type": "builtin"},
    {"id": "dark", "name": "כהה", "type": "builtin"},
    {"id": "dim", "name": "עמום", "type": "builtin"},
    {"id": "rose-pine-dawn", "name": "Rose Pine Dawn", "type": "builtin"},
    {"id": "high-contrast", "name": "ניגודיות גבוהה", "type": "builtin"},
]


class SharedThemeService:
    """שירות לניהול ערכות נושא ציבוריות."""
    
    def __init__(self, db_manager):
        """
        אתחול השירות.
        
        Args:
            db_manager: DatabaseManager instance
        """
        self.db_manager = db_manager
        self.collection = db_manager.shared_themes_collection
    
    # ============= Validation =============
    
    def _validate_slug(self, slug: str) -> bool:
        """בדיקה ש-slug תקין."""
        if not slug or not isinstance(slug, str):
            return False
        return bool(VALID_SLUG_REGEX.match(slug))
    
    def _validate_color(self, value: str) -> bool:
        """בדיקה שהערך הוא צבע CSS תקין."""
        if not value or not isinstance(value, str):
            return False
        value = value.strip()
        # blur יכול להיות ערך px
        if value.endswith('px'):
            try:
                float(value[:-2])
                return True
            except ValueError:
                return False
        return bool(VALID_COLOR_REGEX.match(value))
    
    def _validate_colors(self, colors: Dict[str, str]) -> tuple[bool, Optional[str]]:
        """
        בדיקת כל הצבעים באובייקט.
        
        Returns:
            (is_valid, error_field) – אם לא תקין, מחזיר את שם השדה הבעייתי
        """
        if not isinstance(colors, dict):
            return False, "colors_not_dict"
        
        for var_name, var_value in colors.items():
            if var_name not in ALLOWED_COLOR_VARIABLES:
                continue  # התעלם ממשתנים לא מוכרים
            if not self._validate_color(var_value):
                return False, var_name
        
        return True, None
    
    # ============= CRUD Operations =============
    
    def get_all_active(self) -> List[Dict[str, Any]]:
        """
        קבלת כל הערכות הפעילות.
        
        Returns:
            רשימת ערכות (ללא colors – רק מטא-דאטה)
        """
        try:
            cursor = self.collection.find(
                {"is_active": True},
                {
                    "_id": 1,
                    "name": 1,
                    "description": 1,
                    "is_featured": 1,
                    "created_at": 1,
                    "order": 1
                }
            ).sort([("order", 1), ("created_at", -1)])
            
            themes = []
            for doc in cursor:
                themes.append({
                    "id": doc.get("_id"),
                    "name": doc.get("name"),
                    "description": doc.get("description", ""),
                    "is_featured": doc.get("is_featured", False),
                    "created_at": doc.get("created_at").isoformat() if doc.get("created_at") else None,
                    "type": "shared"
                })
            
            return themes
            
        except Exception as e:
            logger.error(f"get_all_active failed: {e}")
            return []
    
    def get_by_id(self, theme_id: str) -> Optional[Dict[str, Any]]:
        """
        קבלת ערכה ספציפית לפי ID (כולל colors).
        
        Args:
            theme_id: ה-slug של הערכה
            
        Returns:
            אובייקט הערכה המלא או None
        """
        try:
            doc = self.collection.find_one({"_id": theme_id, "is_active": True})
            if not doc:
                return None
            
            return {
                "id": doc.get("_id"),
                "name": doc.get("name"),
                "description": doc.get("description", ""),
                "colors": doc.get("colors", {}),
                "is_featured": doc.get("is_featured", False),
                "created_by": doc.get("created_by"),
                "created_at": doc.get("created_at").isoformat() if doc.get("created_at") else None,
                "type": "shared"
            }
            
        except Exception as e:
            logger.error(f"get_by_id failed: {e}")
            return None
    
    def create(
        self,
        slug: str,
        name: str,
        colors: Dict[str, str],
        created_by: int,
        description: str = "",
        is_featured: bool = False
    ) -> tuple[bool, str]:
        """
        יצירת ערכה ציבורית חדשה.
        
        Args:
            slug: מזהה באנגלית (יהפוך ל-_id)
            name: שם לתצוגה
            colors: אובייקט CSS variables
            created_by: user_id של Admin
            description: תיאור (אופציונלי)
            is_featured: האם מומלצת
            
        Returns:
            (success, error_or_id)
        """
        # Validation
        if not self._validate_slug(slug):
            return False, "invalid_slug"
        
        name = (name or "").strip()
        if not name:
            return False, "missing_name"
        if len(name) > MAX_NAME_LENGTH:
            return False, "name_too_long"
        
        is_valid, error_field = self._validate_colors(colors)
        if not is_valid:
            return False, f"invalid_color:{error_field}"
        
        # בדיקה שה-slug לא תפוס
        try:
            existing = self.collection.find_one({"_id": slug})
            if existing:
                return False, "slug_exists"
        except Exception as e:
            logger.error(f"create check existing failed: {e}")
            return False, "database_error"
        
        # סינון רק משתנים מותרים
        filtered_colors = {
            k: v for k, v in colors.items() 
            if k in ALLOWED_COLOR_VARIABLES
        }
        
        now = datetime.now(timezone.utc)
        doc = {
            "_id": slug,
            "name": name,
            "description": (description or "").strip()[:MAX_DESCRIPTION_LENGTH],
            "colors": filtered_colors,
            "created_by": int(created_by),
            "created_at": now,
            "updated_at": now,
            "is_active": True,
            "is_featured": bool(is_featured),
            "order": 0
        }
        
        try:
            self.collection.insert_one(doc)
            logger.info(f"Created shared theme: {slug} by user {created_by}")
            return True, slug
            
        except Exception as e:
            logger.error(f"create failed: {e}")
            return False, "database_error"
    
    def update(
        self,
        theme_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        colors: Optional[Dict[str, str]] = None,
        is_featured: Optional[bool] = None,
        is_active: Optional[bool] = None
    ) -> tuple[bool, str]:
        """
        עדכון ערכה קיימת.
        
        Returns:
            (success, error_message)
        """
        # בדיקה שהערכה קיימת
        try:
            existing = self.collection.find_one({"_id": theme_id})
            if not existing:
                return False, "theme_not_found"
        except Exception as e:
            logger.error(f"update check existing failed: {e}")
            return False, "database_error"
        
        update_fields = {"updated_at": datetime.now(timezone.utc)}
        
        if name is not None:
            name = (name or "").strip()
            if not name:
                return False, "missing_name"
            if len(name) > MAX_NAME_LENGTH:
                return False, "name_too_long"
            update_fields["name"] = name
        
        if description is not None:
            update_fields["description"] = (description or "").strip()[:MAX_DESCRIPTION_LENGTH]
        
        if colors is not None:
            is_valid, error_field = self._validate_colors(colors)
            if not is_valid:
                return False, f"invalid_color:{error_field}"
            filtered_colors = {
                k: v for k, v in colors.items() 
                if k in ALLOWED_COLOR_VARIABLES
            }
            update_fields["colors"] = filtered_colors
        
        if is_featured is not None:
            update_fields["is_featured"] = bool(is_featured)
        
        if is_active is not None:
            update_fields["is_active"] = bool(is_active)
        
        try:
            result = self.collection.update_one(
                {"_id": theme_id},
                {"$set": update_fields}
            )
            
            if result.modified_count == 0:
                return False, "no_changes"
            
            logger.info(f"Updated shared theme: {theme_id}")
            return True, "ok"
            
        except Exception as e:
            logger.error(f"update failed: {e}")
            return False, "database_error"
    
    def delete(self, theme_id: str) -> tuple[bool, str]:
        """
        מחיקת ערכה (מחיקה קשה).
        
        Returns:
            (success, error_message)
        """
        try:
            result = self.collection.delete_one({"_id": theme_id})
            
            if result.deleted_count == 0:
                return False, "theme_not_found"
            
            logger.info(f"Deleted shared theme: {theme_id}")
            return True, "ok"
            
        except Exception as e:
            logger.error(f"delete failed: {e}")
            return False, "database_error"
    
    # ============= Merged List =============
    
    def get_all_themes_merged(self, user_custom_themes: List[Dict] = None) -> List[Dict]:
        """
        קבלת רשימה משולבת של כל סוגי הערכות.
        
        Args:
            user_custom_themes: ערכות אישיות של המשתמש (אם יש)
            
        Returns:
            רשימה מאוחדת: [builtin...] + [shared...] + [custom...]
        """
        merged = []
        
        # 1. ערכות מובנות
        merged.extend(BUILTIN_THEMES)
        
        # 2. ערכות ציבוריות
        shared = self.get_all_active()
        merged.extend(shared)
        
        # 3. ערכות אישיות של המשתמש
        if user_custom_themes:
            for theme in user_custom_themes:
                merged.append({
                    "id": theme.get("id"),
                    "name": theme.get("name"),
                    "is_active": theme.get("is_active", False),
                    "type": "custom"
                })
        
        return merged


# ============= Singleton Factory =============

_shared_theme_service: Optional[SharedThemeService] = None


def get_shared_theme_service() -> SharedThemeService:
    """
    קבלת instance של SharedThemeService (Singleton).
    """
    global _shared_theme_service
    
    if _shared_theme_service is None:
        from database.manager import get_db_manager
        db_manager = get_db_manager()
        _shared_theme_service = SharedThemeService(db_manager)
    
    return _shared_theme_service
```

---

## שלב 3: API Routes

### 3.1 הוספת Routes ל-app.py

הוסף את הנתיבים הבאים ב-`webapp/app.py` (אחרי ה-theme routes הקיימים, בסביבות שורה 11501):

```python
# ============= Shared Themes API =============
# שורות להוסיף ב-webapp/app.py

from services.shared_theme_service import get_shared_theme_service

# --- GET /api/themes/list - רשימה משולבת ---
@app.route('/api/themes/list', methods=['GET'])
@login_required
def get_all_themes_list():
    """
    קבלת רשימה משולבת של כל הערכות:
    - Built-in (קבועות בקוד)
    - Shared (ציבוריות מה-DB)
    - Custom (אישיות של המשתמש)
    """
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    
    try:
        # קבלת ערכות אישיות של המשתמש
        user_doc = get_db().users.find_one(
            {"_id": user_id},
            {"custom_themes": 1}
        )
        user_themes = user_doc.get("custom_themes", []) if user_doc else []
        
        # קבלת רשימה משולבת
        service = get_shared_theme_service()
        merged = service.get_all_themes_merged(user_themes)
        
        return jsonify({
            "ok": True,
            "themes": merged,
            "count": len(merged)
        })
        
    except Exception as e:
        app.logger.error(f"get_all_themes_list failed: {e}")
        return jsonify({"ok": False, "error": "database_error"}), 500


# --- GET /api/themes/shared/<id> - פרטי ערכה ציבורית ---
@app.route('/api/themes/shared/<theme_id>', methods=['GET'])
@login_required
def get_shared_theme(theme_id: str):
    """קבלת פרטי ערכה ציבורית כולל colors."""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    
    try:
        service = get_shared_theme_service()
        theme = service.get_by_id(theme_id)
        
        if not theme:
            return jsonify({"ok": False, "error": "theme_not_found"}), 404
        
        return jsonify({
            "ok": True,
            "theme": theme
        })
        
    except Exception as e:
        app.logger.error(f"get_shared_theme failed: {e}")
        return jsonify({"ok": False, "error": "database_error"}), 500


# --- POST /api/themes/publish - פרסום ערכה ציבורית (Admin בלבד) ---
@app.route('/api/themes/publish', methods=['POST'])
@login_required
def publish_shared_theme():
    """
    פרסום ערכה ציבורית חדשה.
    זמין רק לאדמינים.
    """
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    
    # בדיקת הרשאת Admin
    if not is_admin(int(user_id)):
        return jsonify({"ok": False, "error": "admin_required"}), 403
    
    data = request.get_json() or {}
    
    slug = (data.get("slug") or "").strip().lower()
    name = (data.get("name") or "").strip()
    colors = data.get("colors") or {}
    description = data.get("description", "")
    is_featured = data.get("is_featured", False)
    
    if not slug:
        return jsonify({"ok": False, "error": "missing_slug"}), 400
    if not name:
        return jsonify({"ok": False, "error": "missing_name"}), 400
    if not colors:
        return jsonify({"ok": False, "error": "missing_colors"}), 400
    
    try:
        service = get_shared_theme_service()
        success, result = service.create(
            slug=slug,
            name=name,
            colors=colors,
            created_by=int(user_id),
            description=description,
            is_featured=is_featured
        )
        
        if not success:
            error_map = {
                "invalid_slug": ("slug חייב להיות 3-30 תווים באנגלית קטנה", 400),
                "slug_exists": ("slug כבר קיים", 409),
                "missing_name": ("חסר שם לתצוגה", 400),
                "name_too_long": ("שם ארוך מדי (עד 50 תווים)", 400),
            }
            
            if result.startswith("invalid_color:"):
                field = result.split(":")[1]
                return jsonify({"ok": False, "error": "invalid_color", "field": field}), 400
            
            msg, status = error_map.get(result, ("שגיאה לא ידועה", 500))
            return jsonify({"ok": False, "error": result, "message": msg}), status
        
        return jsonify({
            "ok": True,
            "theme_id": result,
            "message": "הערכה פורסמה בהצלחה!"
        })
        
    except Exception as e:
        app.logger.error(f"publish_shared_theme failed: {e}")
        return jsonify({"ok": False, "error": "database_error"}), 500


# --- PUT /api/themes/shared/<id> - עדכון ערכה ציבורית (Admin בלבד) ---
@app.route('/api/themes/shared/<theme_id>', methods=['PUT'])
@login_required
def update_shared_theme(theme_id: str):
    """עדכון ערכה ציבורית. זמין רק לאדמינים."""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    
    if not is_admin(int(user_id)):
        return jsonify({"ok": False, "error": "admin_required"}), 403
    
    data = request.get_json() or {}
    
    try:
        service = get_shared_theme_service()
        success, result = service.update(
            theme_id=theme_id,
            name=data.get("name"),
            description=data.get("description"),
            colors=data.get("colors"),
            is_featured=data.get("is_featured"),
            is_active=data.get("is_active")
        )
        
        if not success:
            if result == "theme_not_found":
                return jsonify({"ok": False, "error": result}), 404
            return jsonify({"ok": False, "error": result}), 400
        
        return jsonify({"ok": True, "message": "הערכה עודכנה"})
        
    except Exception as e:
        app.logger.error(f"update_shared_theme failed: {e}")
        return jsonify({"ok": False, "error": "database_error"}), 500


# --- DELETE /api/themes/shared/<id> - מחיקת ערכה ציבורית (Admin בלבד) ---
@app.route('/api/themes/shared/<theme_id>', methods=['DELETE'])
@login_required
def delete_shared_theme(theme_id: str):
    """מחיקת ערכה ציבורית. זמין רק לאדמינים."""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    
    if not is_admin(int(user_id)):
        return jsonify({"ok": False, "error": "admin_required"}), 403
    
    try:
        service = get_shared_theme_service()
        success, result = service.delete(theme_id)
        
        if not success:
            if result == "theme_not_found":
                return jsonify({"ok": False, "error": result}), 404
            return jsonify({"ok": False, "error": result}), 500
        
        return jsonify({"ok": True, "message": "הערכה נמחקה"})
        
    except Exception as e:
        app.logger.error(f"delete_shared_theme failed: {e}")
        return jsonify({"ok": False, "error": "database_error"}), 500


# --- POST /api/themes/shared/<id>/apply - החלת ערכה ציבורית ---
@app.route('/api/themes/shared/<theme_id>/apply', methods=['POST'])
@login_required
def apply_shared_theme(theme_id: str):
    """
    החלת ערכה ציבורית על המשתמש.
    שומר את ui_prefs.theme = "shared:<theme_id>"
    """
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    
    try:
        # וודא שהערכה קיימת
        service = get_shared_theme_service()
        theme = service.get_by_id(theme_id)
        
        if not theme:
            return jsonify({"ok": False, "error": "theme_not_found"}), 404
        
        # עדכן את ui_prefs של המשתמש
        db = get_db()
        
        # בטל את כל הערכות האישיות
        db.users.update_one(
            {"_id": user_id},
            {"$set": {"custom_themes.$[].is_active": False}}
        )
        
        # הגדר את הערכה הציבורית כפעילה
        db.users.update_one(
            {"_id": user_id},
            {"$set": {"ui_prefs.theme": f"shared:{theme_id}"}}
        )
        
        return jsonify({
            "ok": True,
            "message": "הערכה הוחלה!",
            "applied_theme": theme_id
        })
        
    except Exception as e:
        app.logger.error(f"apply_shared_theme failed: {e}")
        return jsonify({"ok": False, "error": "database_error"}), 500
```

### 3.2 סיכום נקודות קצה (API)

| Method | Endpoint | תיאור | הרשאה |
|--------|----------|--------|--------|
| `GET` | `/api/themes/list` | רשימה משולבת (builtin+shared+custom) | משתמש |
| `GET` | `/api/themes/shared/<id>` | פרטי ערכה ציבורית | משתמש |
| `POST` | `/api/themes/publish` | פרסום ערכה חדשה | **Admin** |
| `PUT` | `/api/themes/shared/<id>` | עדכון ערכה ציבורית | **Admin** |
| `DELETE` | `/api/themes/shared/<id>` | מחיקת ערכה ציבורית | **Admin** |
| `POST` | `/api/themes/shared/<id>/apply` | החלת ערכה על המשתמש | משתמש |

---

## שלב 4: עדכון Theme Builder

### 4.1 הוספת כפתור "פרסם לכולם"

עדכן את `webapp/templates/settings/theme_builder.html`:

```html
<!-- הוסף בתוך .form-actions (אחרי כפתור מחיקה) -->
{% if is_admin %}
<button type="button" class="btn btn-warning" id="publishThemeBtn" disabled>
    <i class="fas fa-share-alt"></i>
    פרסם לכולם
</button>
{% endif %}
```

### 4.2 הוספת מודאל פרסום

```html
<!-- הוסף לפני </div> האחרון של theme-builder-layout -->
{% if is_admin %}
<!-- Publish Modal -->
<div id="publishModal" class="modal" hidden>
    <div class="modal-content glass-card">
        <div class="modal-header">
            <h3>
                <i class="fas fa-share-alt"></i>
                פרסום ערכה לכולם
            </h3>
            <button type="button" class="modal-close" id="closePublishModal">
                <i class="fas fa-times"></i>
            </button>
        </div>
        
        <form id="publishForm">
            <div class="form-group">
                <label for="publishSlug">
                    מזהה באנגלית (Slug)
                    <span class="required">*</span>
                </label>
                <input 
                    type="text" 
                    id="publishSlug" 
                    placeholder="cyber_purple"
                    pattern="[a-z][a-z0-9_]{2,29}"
                    required
                />
                <small>3-30 תווים, אותיות קטנות ומספרים בלבד, מתחיל באות</small>
            </div>
            
            <div class="form-group">
                <label for="publishName">
                    שם לתצוגה
                    <span class="required">*</span>
                </label>
                <input 
                    type="text" 
                    id="publishName" 
                    placeholder="Cyber Purple"
                    maxlength="50"
                    required
                />
            </div>
            
            <div class="form-group">
                <label for="publishDescription">תיאור קצר</label>
                <textarea 
                    id="publishDescription" 
                    placeholder="ערכה סגולה בהשראת סייברפאנק"
                    maxlength="200"
                    rows="2"
                ></textarea>
            </div>
            
            <div class="form-group">
                <label>
                    <input type="checkbox" id="publishFeatured" />
                    סמן כמומלצת (Featured)
                </label>
            </div>
            
            <div class="modal-actions">
                <button type="submit" class="btn btn-primary">
                    <i class="fas fa-upload"></i>
                    פרסם
                </button>
                <button type="button" class="btn btn-secondary" id="cancelPublish">
                    ביטול
                </button>
            </div>
        </form>
    </div>
</div>
{% endif %}
```

### 4.3 CSS למודאל

```css
/* הוסף לתוך ה-<style> של theme_builder.html */

/* Modal */
.modal {
    position: fixed;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    background: rgba(0, 0, 0, 0.7);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 10000;
    backdrop-filter: blur(4px);
}

.modal[hidden] {
    display: none;
}

.modal-content {
    width: 90%;
    max-width: 500px;
    max-height: 90vh;
    overflow-y: auto;
    animation: modalFadeIn 0.2s ease;
}

@keyframes modalFadeIn {
    from {
        opacity: 0;
        transform: translateY(-20px);
    }
    to {
        opacity: 1;
        transform: translateY(0);
    }
}

.modal-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 1.5rem;
    padding-bottom: 1rem;
    border-bottom: 1px solid var(--glass-border);
}

.modal-header h3 {
    margin: 0;
    display: flex;
    align-items: center;
    gap: 0.5rem;
}

.modal-close {
    background: none;
    border: none;
    color: var(--text-secondary);
    cursor: pointer;
    font-size: 1.2rem;
    padding: 0.5rem;
    border-radius: 6px;
    transition: all 0.2s;
}

.modal-close:hover {
    background: var(--glass);
    color: var(--text-primary);
}

.form-group {
    margin-bottom: 1.25rem;
}

.form-group label {
    display: block;
    margin-bottom: 0.5rem;
    font-weight: 500;
}

.form-group input[type="text"],
.form-group textarea {
    width: 100%;
    padding: 0.75rem;
    border-radius: 8px;
    border: 1px solid var(--glass-border);
    background: var(--glass);
    color: var(--text-primary);
    font-size: 1rem;
}

.form-group input:focus,
.form-group textarea:focus {
    outline: none;
    border-color: var(--primary);
    box-shadow: 0 0 0 2px color-mix(in srgb, var(--primary) 30%, transparent);
}

.form-group small {
    display: block;
    margin-top: 0.4rem;
    color: var(--text-secondary);
    font-size: 0.85rem;
}

.form-group input[type="checkbox"] {
    margin-left: 0.5rem;
}

.required {
    color: var(--danger);
}

.modal-actions {
    display: flex;
    gap: 1rem;
    justify-content: flex-end;
    margin-top: 1.5rem;
    padding-top: 1rem;
    border-top: 1px solid var(--glass-border);
}
```

### 4.4 JavaScript לפרסום

```javascript
// הוסף בתוך ה-IIFE הקיים ב-theme_builder.html

{% if is_admin %}
// ========== Publish Logic (Admin Only) ==========

const publishBtn = document.getElementById('publishThemeBtn');
const publishModal = document.getElementById('publishModal');
const publishForm = document.getElementById('publishForm');
const closePublishModal = document.getElementById('closePublishModal');
const cancelPublish = document.getElementById('cancelPublish');

// הפעל את כפתור הפרסום רק אם יש ערכה נבחרת
function updatePublishButton() {
    if (publishBtn) {
        publishBtn.disabled = isNewTheme || !selectedThemeId;
    }
}

// פתיחת המודאל
if (publishBtn) {
    publishBtn.addEventListener('click', () => {
        if (!selectedThemeId) {
            showToast('יש לבחור ערכה קודם', 'error');
            return;
        }
        
        // מלא את השם אוטומטית
        const currentName = document.getElementById('themeName').value;
        document.getElementById('publishName').value = currentName;
        
        // הצע slug אוטומטי (המר לאנגלית קטנה, החלף רווחים ב-_)
        const suggestedSlug = currentName
            .toLowerCase()
            .replace(/[^a-z0-9]+/g, '_')
            .replace(/^_|_$/g, '')
            .slice(0, 30);
        document.getElementById('publishSlug').value = suggestedSlug || '';
        
        publishModal.hidden = false;
    });
}

// סגירת המודאל
function hidePublishModal() {
    publishModal.hidden = true;
    publishForm.reset();
}

if (closePublishModal) {
    closePublishModal.addEventListener('click', hidePublishModal);
}
if (cancelPublish) {
    cancelPublish.addEventListener('click', hidePublishModal);
}

// סגירה בלחיצה על הרקע
publishModal?.addEventListener('click', (e) => {
    if (e.target === publishModal) {
        hidePublishModal();
    }
});

// שליחת הטופס
if (publishForm) {
    publishForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        
        const slug = document.getElementById('publishSlug').value.trim().toLowerCase();
        const name = document.getElementById('publishName').value.trim();
        const description = document.getElementById('publishDescription').value.trim();
        const isFeatured = document.getElementById('publishFeatured').checked;
        
        // אסוף את הצבעים הנוכחיים
        const colors = collectThemeValues();
        
        try {
            const res = await fetch('/api/themes/publish', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    slug: slug,
                    name: name,
                    colors: colors,
                    description: description,
                    is_featured: isFeatured
                })
            });
            
            const data = await res.json();
            
            if (!res.ok || !data.ok) {
                throw new Error(data.message || data.error || 'publish_failed');
            }
            
            hidePublishModal();
            showToast(`הערכה "${name}" פורסמה בהצלחה! 🎉`, 'success');
            
        } catch (err) {
            console.error('Publish failed:', err);
            showToast(err.message || 'שגיאה בפרסום הערכה', 'error');
        }
    });
}

// עדכן את מצב כפתור הפרסום כשמשהו משתנה
const originalUpdateFormButtons = updateFormButtons;
updateFormButtons = function() {
    originalUpdateFormButtons();
    updatePublishButton();
};
{% endif %}
```

---

## שלב 5: עדכון דף הגדרות

### 5.1 עדכון לוגיקת טעינת ערכות

עדכן את `webapp/templates/settings.html` לטעון ערכות דינמית מה-API במקום hardcoded:

```javascript
// הוסף ב-<script> של settings.html (בסקשן של theme selection)

// ========== Theme Selection ==========
async function loadThemesList() {
    try {
        const res = await fetch('/api/themes/list');
        const data = await res.json();
        
        if (!res.ok || !data.ok) {
            console.error('Failed to load themes:', data.error);
            return;
        }
        
        renderThemeCards(data.themes);
        
    } catch (err) {
        console.error('Error loading themes:', err);
    }
}

function renderThemeCards(themes) {
    const container = document.getElementById('themeCardsContainer');
    if (!container) return;
    
    // קבוצות לפי סוג
    const builtin = themes.filter(t => t.type === 'builtin');
    const shared = themes.filter(t => t.type === 'shared');
    const custom = themes.filter(t => t.type === 'custom');
    
    let html = '';
    
    // Built-in
    html += '<div class="theme-group"><h4>ערכות מובנות</h4><div class="theme-cards">';
    for (const theme of builtin) {
        html += renderThemeCard(theme);
    }
    html += '</div></div>';
    
    // Shared (אם יש)
    if (shared.length > 0) {
        html += '<div class="theme-group"><h4>ערכות ציבוריות</h4><div class="theme-cards">';
        for (const theme of shared) {
            html += renderThemeCard(theme, true);
        }
        html += '</div></div>';
    }
    
    // Custom (אם יש)
    if (custom.length > 0) {
        html += '<div class="theme-group"><h4>הערכות שלי</h4><div class="theme-cards">';
        for (const theme of custom) {
            html += renderThemeCard(theme);
        }
        html += '</div></div>';
    }
    
    container.innerHTML = html;
    
    // Bind click events
    container.querySelectorAll('.theme-card').forEach(card => {
        card.addEventListener('click', () => selectTheme(card.dataset.themeId, card.dataset.themeType));
    });
}

function renderThemeCard(theme, isShared = false) {
    const isActive = isThemeActive(theme);
    const badges = [];
    
    if (theme.is_featured) {
        badges.push('<span class="badge featured">⭐ מומלץ</span>');
    }
    if (isShared) {
        badges.push('<span class="badge shared">ציבורי</span>');
    }
    
    return `
        <div class="theme-card ${isActive ? 'active' : ''}" 
             data-theme-id="${theme.id}" 
             data-theme-type="${theme.type}">
            <div class="theme-card-preview" style="background: var(--theme-preview-${theme.id}, var(--bg-primary))">
                ${isActive ? '<i class="fas fa-check-circle"></i>' : ''}
            </div>
            <div class="theme-card-info">
                <div class="theme-card-name">${escapeHtml(theme.name)}</div>
                ${badges.length > 0 ? '<div class="theme-card-badges">' + badges.join('') + '</div>' : ''}
            </div>
        </div>
    `;
}

function isThemeActive(theme) {
    const currentTheme = document.documentElement.getAttribute('data-theme');
    
    if (theme.type === 'custom') {
        return theme.is_active === true;
    }
    if (theme.type === 'shared') {
        return currentTheme === `shared:${theme.id}`;
    }
    return currentTheme === theme.id;
}

async function selectTheme(themeId, themeType) {
    try {
        let endpoint;
        let body = {};
        
        if (themeType === 'shared') {
            endpoint = `/api/themes/shared/${themeId}/apply`;
        } else if (themeType === 'custom') {
            endpoint = `/api/themes/${themeId}/activate`;
        } else {
            // Built-in theme
            endpoint = '/api/ui_prefs';
            body = { theme: themeId };
        }
        
        const res = await fetch(endpoint, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body)
        });
        
        if (res.ok) {
            location.reload();
        } else {
            const data = await res.json();
            alert(data.message || 'שגיאה בהחלפת ערכה');
        }
        
    } catch (err) {
        console.error('Error selecting theme:', err);
        alert('שגיאה בהחלפת ערכה');
    }
}

function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

// טען את הרשימה בעליית הדף
document.addEventListener('DOMContentLoaded', loadThemesList);
```

### 5.2 CSS לכרטיסי ערכות

```css
/* הוסף ל-settings.html או לקובץ CSS נפרד */

.theme-group {
    margin-bottom: 2rem;
}

.theme-group h4 {
    margin-bottom: 1rem;
    color: var(--text-secondary);
    font-size: 0.9rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
}

.theme-cards {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
    gap: 1rem;
}

.theme-card {
    background: var(--glass);
    border: 2px solid transparent;
    border-radius: 12px;
    padding: 0.75rem;
    cursor: pointer;
    transition: all 0.2s ease;
}

.theme-card:hover {
    background: var(--glass-hover);
    transform: translateY(-2px);
}

.theme-card.active {
    border-color: var(--primary);
    background: color-mix(in srgb, var(--primary) 15%, transparent);
}

.theme-card-preview {
    height: 60px;
    border-radius: 8px;
    margin-bottom: 0.75rem;
    display: flex;
    align-items: center;
    justify-content: center;
    color: white;
    font-size: 1.5rem;
}

.theme-card-info {
    text-align: center;
}

.theme-card-name {
    font-weight: 600;
    color: var(--text-primary);
    font-size: 0.9rem;
}

.theme-card-badges {
    margin-top: 0.5rem;
    display: flex;
    gap: 0.25rem;
    justify-content: center;
    flex-wrap: wrap;
}

.badge {
    display: inline-block;
    padding: 0.2rem 0.5rem;
    border-radius: 4px;
    font-size: 0.7rem;
    font-weight: 600;
}

.badge.featured {
    background: linear-gradient(135deg, #fbbf24, #f59e0b);
    color: #000;
}

.badge.shared {
    background: var(--primary);
    color: white;
}
```

### 5.3 עדכון base.html לתמיכה בערכות ציבוריות

הוסף ב-`webapp/templates/base.html` (אחרי ה-custom theme injection):

```html
{% if shared_theme and shared_theme.colors %}
<!-- Shared Theme Override -->
<style id="shared-theme-override">
:root[data-theme^="shared:"] {
    {% for var_name, var_value in shared_theme.colors.items() %}
    {{ var_name }}: {{ var_value }};
    {% endfor %}
}
</style>
{% endif %}
```

ועדכן את ה-`make_base_context()` ב-`webapp/app.py`:

```python
def get_shared_theme_for_user(user_id) -> Optional[Dict]:
    """טען ערכה ציבורית אם המשתמש בחר באחת."""
    if not user_id:
        return None
    
    try:
        user_doc = get_db().users.find_one({"_id": user_id}, {"ui_prefs.theme": 1})
        if not user_doc:
            return None
        
        theme_pref = user_doc.get("ui_prefs", {}).get("theme", "")
        if not theme_pref.startswith("shared:"):
            return None
        
        theme_id = theme_pref.replace("shared:", "")
        service = get_shared_theme_service()
        return service.get_by_id(theme_id)
        
    except Exception as e:
        app.logger.warning(f"get_shared_theme_for_user failed: {e}")
        return None

# בתוך make_base_context או before_request:
shared_theme = get_shared_theme_for_user(session.get('user_id'))
# העבר ל-template
```

---

## שלב 6: בדיקות

### 6.1 Unit Tests לשירות

```python
# tests/test_shared_theme_service.py
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

from services.shared_theme_service import SharedThemeService, BUILTIN_THEMES


class MockCollection:
    def __init__(self):
        self.docs = []
        self.calls = []
    
    def find(self, query, projection=None):
        self.calls.append(('find', query, projection))
        return iter(self.docs)
    
    def find_one(self, query):
        self.calls.append(('find_one', query))
        for doc in self.docs:
            if doc.get('_id') == query.get('_id'):
                return doc
        return None
    
    def insert_one(self, doc):
        self.calls.append(('insert_one', doc))
        self.docs.append(doc)
        return MagicMock(inserted_id=doc.get('_id'))
    
    def update_one(self, query, update):
        self.calls.append(('update_one', query, update))
        return MagicMock(modified_count=1)
    
    def delete_one(self, query):
        self.calls.append(('delete_one', query))
        return MagicMock(deleted_count=1)


class MockDBManager:
    def __init__(self):
        self.shared_themes_collection = MockCollection()


class TestSharedThemeServiceValidation:
    def test_valid_slug(self):
        service = SharedThemeService(MockDBManager())
        assert service._validate_slug("cyber_purple") is True
        assert service._validate_slug("a12") is True
        assert service._validate_slug("theme_v2_final") is True
    
    def test_invalid_slug(self):
        service = SharedThemeService(MockDBManager())
        assert service._validate_slug("") is False
        assert service._validate_slug("ab") is False  # too short
        assert service._validate_slug("123") is False  # starts with number
        assert service._validate_slug("CamelCase") is False  # uppercase
        assert service._validate_slug("with-dash") is False  # has dash
        assert service._validate_slug("a" * 31) is False  # too long
    
    def test_valid_color(self):
        service = SharedThemeService(MockDBManager())
        assert service._validate_color("#ff0000") is True
        assert service._validate_color("#FF0000") is True
        assert service._validate_color("#ff000080") is True
        assert service._validate_color("rgba(255, 0, 0, 0.5)") is True
        assert service._validate_color("20px") is True  # blur value
    
    def test_invalid_color(self):
        service = SharedThemeService(MockDBManager())
        assert service._validate_color("") is False
        assert service._validate_color("red") is False  # named color
        assert service._validate_color("not-a-color") is False
        assert service._validate_color("#fff") is False  # 3-digit hex


class TestSharedThemeServiceCreate:
    def test_create_success(self):
        db = MockDBManager()
        service = SharedThemeService(db)
        
        success, result = service.create(
            slug="cyber_purple",
            name="Cyber Purple",
            colors={"--primary": "#7b2cbf"},
            created_by=12345
        )
        
        assert success is True
        assert result == "cyber_purple"
        assert len(db.shared_themes_collection.docs) == 1
    
    def test_create_duplicate_slug(self):
        db = MockDBManager()
        db.shared_themes_collection.docs = [{"_id": "cyber_purple"}]
        service = SharedThemeService(db)
        
        success, result = service.create(
            slug="cyber_purple",
            name="Cyber Purple 2",
            colors={"--primary": "#7b2cbf"},
            created_by=12345
        )
        
        assert success is False
        assert result == "slug_exists"
    
    def test_create_invalid_slug(self):
        service = SharedThemeService(MockDBManager())
        
        success, result = service.create(
            slug="Bad Slug!",
            name="Test",
            colors={"--primary": "#7b2cbf"},
            created_by=12345
        )
        
        assert success is False
        assert result == "invalid_slug"
    
    def test_create_invalid_color(self):
        service = SharedThemeService(MockDBManager())
        
        success, result = service.create(
            slug="test_theme",
            name="Test",
            colors={"--primary": "not-valid"},
            created_by=12345
        )
        
        assert success is False
        assert "invalid_color" in result


class TestSharedThemeServiceMerged:
    def test_merged_list_includes_all_types(self):
        db = MockDBManager()
        db.shared_themes_collection.docs = [
            {"_id": "shared1", "name": "Shared 1", "is_active": True}
        ]
        service = SharedThemeService(db)
        
        user_themes = [{"id": "custom1", "name": "My Theme", "is_active": False}]
        merged = service.get_all_themes_merged(user_themes)
        
        # בדוק שיש builtin
        builtin_count = len([t for t in merged if t.get("type") == "builtin"])
        assert builtin_count == len(BUILTIN_THEMES)
        
        # בדוק שיש shared
        shared_count = len([t for t in merged if t.get("type") == "shared"])
        assert shared_count >= 1
        
        # בדוק שיש custom
        custom_count = len([t for t in merged if t.get("type") == "custom"])
        assert custom_count == 1
```

### 6.2 API Tests

```python
# tests/test_shared_theme_api.py
import types
import pytest
from webapp import app as webapp_app


class _StubSharedThemes:
    def __init__(self):
        self.docs = []
        self.calls = []
    
    def find(self, query, projection=None):
        self.calls.append(("find", query, projection))
        for doc in self.docs:
            if query.get("is_active") and not doc.get("is_active"):
                continue
            yield doc
    
    def find_one(self, query):
        self.calls.append(("find_one", query))
        for doc in self.docs:
            if doc.get("_id") == query.get("_id"):
                if query.get("is_active") and not doc.get("is_active"):
                    return None
                return doc
        return None
    
    def insert_one(self, doc):
        self.calls.append(("insert_one", doc))
        self.docs.append(doc)
        return types.SimpleNamespace(inserted_id=doc.get("_id"))
    
    def delete_one(self, query):
        self.calls.append(("delete_one", query))
        for i, doc in enumerate(self.docs):
            if doc.get("_id") == query.get("_id"):
                self.docs.pop(i)
                return types.SimpleNamespace(deleted_count=1)
        return types.SimpleNamespace(deleted_count=0)


class _StubUsers:
    def __init__(self):
        self.docs = []
    
    def find_one(self, query, projection=None):
        return {"custom_themes": []}
    
    def update_one(self, query, update, **kwargs):
        return types.SimpleNamespace(acknowledged=True, modified_count=1)


class _StubDB:
    def __init__(self):
        self.shared_themes = _StubSharedThemes()
        self.users = _StubUsers()


def _login(client, user_id=42, is_admin=False):
    with client.session_transaction() as sess:
        sess["user_id"] = int(user_id)
        sess["user_data"] = {"id": int(user_id), "first_name": "Tester"}


@pytest.fixture
def stub_db(monkeypatch):
    db = _StubDB()
    monkeypatch.setattr(webapp_app, "get_db", lambda: db)
    return db


@pytest.fixture
def client(stub_db):
    webapp_app.app.testing = True
    return webapp_app.app.test_client()


# --- GET /api/themes/list ---

def test_get_themes_list_unauthorized(client):
    resp = client.get("/api/themes/list")
    assert resp.status_code == 401


def test_get_themes_list_success(client, stub_db, monkeypatch):
    _login(client)
    
    # Mock the service
    stub_db.shared_themes.docs = [
        {"_id": "cyber", "name": "Cyber", "is_active": True}
    ]
    
    resp = client.get("/api/themes/list")
    data = resp.get_json()
    
    assert resp.status_code == 200
    assert data["ok"] is True
    assert data["count"] > 0


# --- POST /api/themes/publish ---

def test_publish_theme_not_admin(client, stub_db, monkeypatch):
    _login(client, user_id=999)
    monkeypatch.setattr(webapp_app, "is_admin", lambda uid: False)
    
    resp = client.post("/api/themes/publish", json={
        "slug": "test_theme",
        "name": "Test Theme",
        "colors": {"--primary": "#ff0000"}
    })
    
    assert resp.status_code == 403
    assert resp.get_json()["error"] == "admin_required"


def test_publish_theme_success(client, stub_db, monkeypatch):
    _login(client, user_id=6865105071)
    monkeypatch.setattr(webapp_app, "is_admin", lambda uid: True)
    
    resp = client.post("/api/themes/publish", json={
        "slug": "new_theme",
        "name": "New Theme",
        "colors": {"--primary": "#ff0000", "--bg-primary": "#000000"}
    })
    
    data = resp.get_json()
    
    assert resp.status_code == 200
    assert data["ok"] is True
    assert data["theme_id"] == "new_theme"


def test_publish_theme_invalid_slug(client, stub_db, monkeypatch):
    _login(client)
    monkeypatch.setattr(webapp_app, "is_admin", lambda uid: True)
    
    resp = client.post("/api/themes/publish", json={
        "slug": "Bad Slug!",
        "name": "Test",
        "colors": {"--primary": "#ff0000"}
    })
    
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "invalid_slug"


# --- DELETE /api/themes/shared/<id> ---

def test_delete_shared_theme_not_admin(client, stub_db, monkeypatch):
    _login(client)
    monkeypatch.setattr(webapp_app, "is_admin", lambda uid: False)
    
    resp = client.delete("/api/themes/shared/cyber")
    
    assert resp.status_code == 403


def test_delete_shared_theme_success(client, stub_db, monkeypatch):
    _login(client)
    monkeypatch.setattr(webapp_app, "is_admin", lambda uid: True)
    stub_db.shared_themes.docs = [{"_id": "cyber", "name": "Cyber"}]
    
    resp = client.delete("/api/themes/shared/cyber")
    data = resp.get_json()
    
    assert resp.status_code == 200
    assert data["ok"] is True
```

---

## צ'קליסט למימוש

### Database
- [ ] הוסף `shared_themes_collection` ל-`database/manager.py`
- [ ] צור אינדקסים (`is_active`, `created_at`, `created_by`)
- [ ] בדוק חיבור ל-collection החדש

### Backend Service
- [ ] צור `services/shared_theme_service.py`
- [ ] מימוש validation (slug, colors, name)
- [ ] מימוש CRUD: `get_all_active`, `get_by_id`, `create`, `update`, `delete`
- [ ] מימוש `get_all_themes_merged`
- [ ] Singleton factory

### API Routes
- [ ] `GET /api/themes/list` – רשימה משולבת
- [ ] `GET /api/themes/shared/<id>` – פרטי ערכה
- [ ] `POST /api/themes/publish` – פרסום (Admin)
- [ ] `PUT /api/themes/shared/<id>` – עדכון (Admin)
- [ ] `DELETE /api/themes/shared/<id>` – מחיקה (Admin)
- [ ] `POST /api/themes/shared/<id>/apply` – החלה על משתמש

### Theme Builder
- [ ] כפתור "פרסם לכולם" (Admin בלבד)
- [ ] מודאל פרסום (slug, name, description, featured)
- [ ] JavaScript לפרסום
- [ ] CSS למודאל

### Settings Page
- [ ] עדכון לטעינה דינמית מ-API
- [ ] רינדור כרטיסי ערכות לפי סוג
- [ ] תגיות (Featured, ציבורי)
- [ ] פונקציית בחירה/החלפה

### base.html Integration
- [ ] Injection של shared theme CSS
- [ ] תמיכה ב-`data-theme="shared:xxx"`

### Tests
- [ ] Unit tests ל-SharedThemeService
- [ ] API tests לנתיבים חדשים
- [ ] בדיקת הרשאות Admin

---

## 🔑 אינטגרציה עם VS Code Import

### הבעיה: אובדן משתנים בפרסום

כשמפרסמים ערכה שיובאה מ-VS Code, קיים סיכון לאובדן משתנים:

```
┌─────────────────────────────────────────────────────────────────────┐
│                     VS Code Theme Import Flow                        │
├─────────────────────────────────────────────────────────────────────┤
│  1. קובץ JSON של VS Code (colors, tokenColors)                      │
│                              ↓                                       │
│  2. parse_vscode_theme() - מיפוי ל-40+ משתני CSS                    │
│     • --bg-primary, --bg-secondary, --bg-tertiary                   │
│     • --text-primary, --text-secondary, --text-muted                │
│     • --primary, --primary-hover, --primary-light                   │
│     • --code-bg, --code-text, --code-border                         │
│     • --btn-primary-bg, --btn-primary-color                         │
│     • --glass, --glass-border, --glass-hover                        │
│     • --md-surface, --md-text                                        │
│     • syntax_css (CodeMirror + Pygments CSS)                        │
│                              ↓                                       │
│  3. נשמר ב-DB: { variables: {...}, syntax_css: "..." }              │
└─────────────────────────────────────────────────────────────────────┘
```

### הבעיה הקודמת

ב-Theme Builder, הטופס מציג רק **10 משתנים** עם color pickers:

```javascript
const VAR_MAP = {
    'bgPrimary': '--bg-primary',
    'bgSecondary': '--bg-secondary',
    'cardBg': '--card-bg',
    'primary': '--primary',
    'secondary': '--secondary',
    'textPrimary': '--text-primary',
    'mdSurface': '--md-surface',
    'mdText': '--md-text',
    'btnPrimaryBg': '--btn-primary-bg',
    'btnPrimaryColor': '--btn-primary-color',
};
```

כשמפרסמים ערכה, `collectThemeValues()` אספה רק את 10 המשתנים האלה - והשאר נעלמו!

### הפתרון: שמירת כל המשתנים המקוריים

```javascript
// State - שמירת כל המשתנים של הערכה המקורית
let currentThemeAllVariables = {};

// כשטוענים ערכה לטופס
function loadThemeIntoForm(theme) {
    const variables = theme.variables || {};
    
    // 🔑 שמירת כל המשתנים (לא רק מה שבטופס!)
    currentThemeAllVariables = { ...variables };
    
    // ... טעינת הטופס הרגילה
}

// כשמפרסמים ערכה
async function handlePublish() {
    const formColors = collectThemeValues();  // 10 משתנים מהטופס
    
    // 🔑 מיזוג: כל המשתנים המקוריים + שינויים מהטופס
    const colors = { ...currentThemeAllVariables, ...formColors };
    
    await fetch('/api/themes/publish', {
        method: 'POST',
        body: JSON.stringify({
            slug,
            name,
            colors,  // כל 40+ המשתנים!
            syntax_css: currentThemeSyntaxCss,  // CodeMirror/Pygments CSS
        })
    });
}
```

### תמיכה ב-syntax_css

ערכות VS Code מכילות גם `tokenColors` - הגדרות צבע לקוד:

```python
# מבנה מסמך ב-shared_themes collection (מעודכן)
{
    "_id": "dracula_pro",
    "name": "Dracula Pro",
    "colors": {
        "--bg-primary": "#282a36",
        "--text-primary": "#f8f8f2",
        "--primary": "#bd93f9",
        # ... 40+ משתנים נוספים
    },
    "syntax_css": """
        /* CodeMirror syntax highlighting */
        .tok-keyword { color: #ff79c6; }
        .tok-string { color: #f1fa8c; }
        .tok-comment { color: #6272a4; }
        .tok-number { color: #bd93f9; }
        .tok-function { color: #50fa7b; }
        
        /* Pygments fallback (לתצוגת קבצים) */
        .source .k { color: #ff79c6; }
        .source .s { color: #f1fa8c; }
        .source .c { color: #6272a4; }
    """,
    "created_by": 6865105071,
    "is_active": true
}
```

### הזרקה ב-base.html

```html
{% if shared_theme %}
<!-- Shared Theme CSS Variables -->
<style id="shared-theme-override">
:root[data-theme^="shared:"] {
    {% for var_name, var_value in shared_theme.colors.items() %}
    {{ var_name }}: {{ var_value }};
    {% endfor %}
}
</style>

<!-- Shared Theme Syntax Highlighting -->
{% if shared_theme.syntax_css %}
<style id="shared-theme-syntax">
{{ shared_theme.syntax_css | safe | replace('data-theme="custom"', 'data-theme-type="custom"') }}
</style>
{% endif %}
{% endif %}
```

---

## 🎨 מערכת CSS לערכות משותפות

### הבעיה: CSS Selectors

ערכות מותאמות אישיות משתמשות ב-`data-theme="custom"`, אבל ערכות משותפות משתמשות ב-`data-theme="shared:slug"`. זה יוצר בעיה:

```css
/* זה עובד רק לערכות custom, לא ל-shared */
[data-theme="custom"] .btn-primary {
    background: var(--btn-primary-bg);
    color: var(--btn-primary-color);
}
```

### הפתרון: data-theme-type

ב-`base.html`, כשטוענים ערכה משותפת, מוסיפים שני attributes:

```javascript
// base.html - script לאתחול ערכה
if (serverTheme.indexOf('shared:') === 0) {
    html.setAttribute('data-theme', serverTheme);  // "shared:dracula_pro"
    html.setAttribute('data-theme-type', 'custom');  // 🔑 מאפשר CSS selectors
}
```

כעת ה-CSS יכול לתפוס גם ערכות custom וגם shared:

```css
/* עובד לשני הסוגים! */
[data-theme="custom"] .btn-primary,
[data-theme-type="custom"] .btn-primary {
    background: var(--btn-primary-bg);
    color: var(--btn-primary-color);
}
```

### רשימת קבצי CSS שצריך לעדכן

| קובץ | אלמנטים |
|------|---------|
| `dark-mode.css` | כפתורים, inputs, קוד, טבלאות, inline code, Mermaid |
| `markdown-enhanced.css` | details, admonitions, tooltips |
| `codemirror-custom.css` | עורך CodeMirror |
| `split-view.css` | תצוגת עורך מפוצלת |

### דוגמאות קוד CSS

#### כפתורים (dark-mode.css)

```css
[data-theme="dark"] .btn-primary,
[data-theme="dim"] .btn-primary,
[data-theme="nebula"] .btn-primary,
[data-theme-type="custom"] .btn-primary {
    background: var(--btn-primary-bg);
    color: var(--btn-primary-color);
    border: 1px solid var(--btn-primary-border, transparent);
}

/* מצבי אינטראקציה */
[data-theme-type="custom"] .btn-primary:hover {
    background: var(--btn-primary-hover-bg, var(--btn-primary-bg));
}

[data-theme-type="custom"] .btn-primary:disabled,
[data-theme-type="custom"] .btn-primary.disabled {
    opacity: 0.6;
    cursor: not-allowed;
}
```

#### טבלאות Markdown

```css
[data-theme="custom"] table,
[data-theme-type="custom"] table {
    border-collapse: collapse;
    width: 100%;
    background: var(--bg-tertiary, var(--card-bg));
    border: 1px solid var(--glass-border);
    border-radius: 8px;
}

[data-theme-type="custom"] table th {
    padding: 0.75rem 1rem;
    font-weight: 600;
    color: var(--text-primary);
    background: var(--bg-secondary);
    border-bottom: 2px solid var(--glass-border);
}

[data-theme-type="custom"] table td {
    padding: 0.6rem 1rem;
    color: var(--text-secondary);
    border-bottom: 1px solid var(--glass-border);
}
```

#### Inline Code

```css
[data-theme="custom"] :not(pre) > code,
[data-theme-type="custom"] :not(pre) > code {
    background: var(--md-surface, var(--code-bg));
    color: var(--md-text, var(--text-primary));
    padding: 0.15em 0.4em;
    border-radius: 4px;
    font-size: 0.9em;
}
```

#### Mermaid Diagrams

```css
[data-theme-type="custom"] .mermaid {
    background: var(--bg-tertiary);
    border-radius: 8px;
    padding: 1rem;
}

[data-theme-type="custom"] .mermaid text {
    fill: var(--text-primary) !important;
}

[data-theme-type="custom"] .mermaid .node rect {
    fill: var(--bg-secondary) !important;
    stroke: var(--glass-border) !important;
}
```

### מסכת מעבר (Theme Mask)

כשמחליפים ערכה, יש רגע של "מסך לבן" בגלל `location.reload()`. הפתרון - מסכה:

```css
/* theme-mask.css */
#theme-mask {
    position: fixed;
    inset: 0;
    z-index: 99999;
    opacity: 0;
    pointer-events: none;
    transition: opacity 0.3s ease;
}

#theme-mask.active {
    opacity: 1;
    pointer-events: all;
}
```

```javascript
// settings.html
function activateThemeMask() {
    const mask = document.getElementById('theme-mask');
    if (mask) {
        // הגדר את צבע הרקע לפי הערכה הנוכחית
        const bgColor = getComputedStyle(document.documentElement)
            .getPropertyValue('--bg-primary').trim() || '#1a1a2e';
        mask.style.background = bgColor;
        mask.classList.add('active');
        sessionStorage.setItem('theme-mask-active', '1');
    }
}

async function selectTheme(themeId, themeType) {
    activateThemeMask();  // הצג מסכה לפני הרענון
    // ... fetch API ...
    location.reload();  // המסכה תישאר עד שהדף ייטען
}

// בטעינת הדף - בדוק אם צריך להסיר מסכה
(function checkThemeMaskOnLoad() {
    if (sessionStorage.getItem('theme-mask-active') === '1') {
        sessionStorage.removeItem('theme-mask-active');
        const mask = document.getElementById('theme-mask');
        if (mask) {
            mask.classList.add('active');
            setTimeout(() => mask.classList.remove('active'), 100);
        }
    }
})();
```

---

## נספח: ערכות נושא לדוגמה

```json
[
  {
    "_id": "cyber_purple",
    "name": "Cyber Purple",
    "description": "ערכה סגולה בהשראת סייברפאנק",
    "colors": {
      "--bg-primary": "#0d0221",
      "--bg-secondary": "#1a0a2e",
      "--primary": "#7b2cbf",
      "--secondary": "#c77dff",
      "--text-primary": "#e0aaff",
      "--card-bg": "rgba(123, 44, 191, 0.15)",
      "--glass": "rgba(199, 125, 255, 0.1)",
      "--glass-border": "rgba(199, 125, 255, 0.2)",
      "--glass-blur": "20px",
      "--md-surface": "#0d0221",
      "--md-text": "#e0aaff",
      "--btn-primary-bg": "#7b2cbf",
      "--btn-primary-color": "#ffffff"
    },
    "is_featured": true
  },
  {
    "_id": "winter_blue",
    "name": "Winter Blue",
    "description": "ערכת חורף כחולה רגועה",
    "colors": {
      "--bg-primary": "#1a1a2e",
      "--bg-secondary": "#16213e",
      "--primary": "#0f4c75",
      "--secondary": "#3282b8",
      "--text-primary": "#bbe1fa",
      "--card-bg": "rgba(15, 76, 117, 0.2)",
      "--glass": "rgba(187, 225, 250, 0.1)",
      "--glass-border": "rgba(187, 225, 250, 0.2)",
      "--glass-blur": "20px",
      "--md-surface": "#1a1a2e",
      "--md-text": "#bbe1fa",
      "--btn-primary-bg": "#0f4c75",
      "--btn-primary-color": "#ffffff"
    },
    "is_featured": false
  }
]
```

---

> **הערה חשובה:** מדריך זה מבוסס על מצב הקוד הקיים נכון לתאריך כתיבתו.
> לפני התחלת המימוש, מומלץ לעיין ב:
> - [Theme Builder Implementation Guide](./theme_builder_implementation_guide.md)
> - [Multi-Theme Support Guide](./theme_builder_multi_theme_guide.md)
