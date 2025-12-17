# מדריך מימוש Config Inspector

> **מטרה:** דשבורד אדמין שמציג את כל משתני הסביבה הפעילים, משווה אותם לערכי ברירת מחדל, ומסתיר ערכים רגישים.

---

## סקירה כללית

### מה הפיצ'ר עושה?

Config Inspector הוא דף אדמין שמאפשר לראות במבט אחד:

| עמודה | תיאור |
|-------|-------|
| **Key** | שם משתנה הסביבה |
| **Active Value** | הערך הפעיל כרגע (מוסתר אם רגיש) |
| **Default Value** | ערך ברירת המחדל שהוגדר בקוד |
| **Source** | מאיפה הגיע הערך: `Environment` / `Default` |
| **Status** | `Modified` / `Default` / `Missing` |

### למה זה שימושי?

- **דיבאג**: לראות מה באמת פעיל בפרודקשן
- **אבטחה**: לוודא שסודות לא נחשפים בטעות
- **תחזוקה**: לזהות קונפיגורציות חסרות או שגויות
- **נוחות**: העתקה מהירה של ערכים ללוח (לערכים לא-רגישים)

---

## ארכיטקטורה

```
┌─────────────────────────────────────────────────────────────┐
│                      Browser (Admin)                         │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                  /admin/config-inspector                     │
│                     (Protected Route)                        │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                     ConfigService                            │
│  ┌─────────────────────────────────────────────────────────┐│
│  │ CONFIG_DEFINITIONS = {                                  ││
│  │   "MONGODB_MIN_POOL_SIZE": {"default": 5, ...},        ││
│  │   "API_TIMEOUT": {"default": 30, ...},                 ││
│  │   ...                                                   ││
│  │ }                                                       ││
│  └─────────────────────────────────────────────────────────┘│
│                              │                               │
│                              ▼                               │
│  ┌─────────────────────────────────────────────────────────┐│
│  │ get_config_overview()                                   ││
│  │   → os.getenv() לכל מפתח                                ││
│  │   → השוואה לדיפולט                                       ││
│  │   → הסתרת ערכים רגישים                                   ││
│  │   → קביעת סטטוס                                          ││
│  └─────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│              admin_config_inspector.html                     │
│                  (Jinja2 Template)                           │
└─────────────────────────────────────────────────────────────┘
```

---

## 1. Service Layer – `ConfigService`

### קובץ: `services/config_inspector_service.py`

```python
"""
Config Inspector Service
========================
שירות לסקירת קונפיגורציית האפליקציה.
מספק תמונת מצב של כל משתני הסביבה הפעילים
תוך הסתרת ערכים רגישים.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class ConfigStatus(str, Enum):
    """סטטוס של משתנה קונפיגורציה."""
    DEFAULT = "Default"      # משתמש בערך ברירת המחדל
    MODIFIED = "Modified"    # ערך שונה מברירת המחדל
    MISSING = "Missing"      # משתנה לא מוגדר וגם אין דיפולט


class ConfigSource(str, Enum):
    """מקור הערך של הקונפיגורציה."""
    ENVIRONMENT = "Environment"  # נלקח ממשתנה סביבה
    DEFAULT = "Default"          # נלקח מברירת המחדל


@dataclass
class ConfigDefinition:
    """הגדרת משתנה קונפיגורציה יחיד."""
    key: str
    default: Any = None
    description: str = ""
    category: str = "general"
    sensitive: bool = False  # האם להסתיר את הערך
    required: bool = False   # האם המשתנה הכרחי


@dataclass
class ConfigEntry:
    """ערך קונפיגורציה בודד עם מטא-דאטה."""
    key: str
    active_value: str
    default_value: str
    source: ConfigSource
    status: ConfigStatus
    description: str = ""
    category: str = "general"
    is_sensitive: bool = False


@dataclass
class ConfigOverview:
    """סקירת קונפיגורציה מלאה."""
    entries: List[ConfigEntry] = field(default_factory=list)
    generated_at: str = ""
    total_count: int = 0
    modified_count: int = 0
    missing_count: int = 0
    default_count: int = 0
    categories: List[str] = field(default_factory=list)


class ConfigService:
    """
    שירות לניהול וסקירת קונפיגורציית האפליקציה.
    
    שימוש:
        service = ConfigService()
        overview = service.get_config_overview()
    """
    
    # מילים רגישות בשמות משתנים - ערכים אלו יוסתרו
    SENSITIVE_PATTERNS: tuple[str, ...] = (
        "TOKEN",
        "KEY",
        "PASSWORD",
        "SECRET",
        "URI",
        "URL",
        "CREDENTIALS",
        "API_KEY",
        "AUTH",
        "PRIVATE",
        "CERT",
        "DSN",
        "CONNECTION_STRING",
    )
    
    # ערך ההסתרה לערכים רגישים
    MASKED_VALUE: str = "********"
    
    # הגדרות כל משתני הקונפיגורציה באפליקציה
    CONFIG_DEFINITIONS: Dict[str, ConfigDefinition] = {
        # ========== Database ==========
        "MONGODB_URI": ConfigDefinition(
            key="MONGODB_URI",
            default="mongodb://localhost:27017/codebot",
            description="כתובת חיבור למסד הנתונים MongoDB",
            category="database",
            sensitive=True,
            required=True,
        ),
        "MONGODB_MIN_POOL_SIZE": ConfigDefinition(
            key="MONGODB_MIN_POOL_SIZE",
            default="5",
            description="מספר חיבורים מינימלי לפול",
            category="database",
        ),
        "MONGODB_MAX_POOL_SIZE": ConfigDefinition(
            key="MONGODB_MAX_POOL_SIZE",
            default="20",
            description="מספר חיבורים מקסימלי לפול",
            category="database",
        ),
        "DB_TIMEOUT_MS": ConfigDefinition(
            key="DB_TIMEOUT_MS",
            default="5000",
            description="זמן המתנה מקסימלי לפעולות DB (מילישניות)",
            category="database",
        ),
        
        # ========== API Settings ==========
        "API_TIMEOUT": ConfigDefinition(
            key="API_TIMEOUT",
            default="30",
            description="זמן מקסימלי לבקשות API (שניות)",
            category="api",
        ),
        "API_RATE_LIMIT": ConfigDefinition(
            key="API_RATE_LIMIT",
            default="100",
            description="מספר בקשות מקסימלי לדקה",
            category="api",
        ),
        "API_MAX_RETRIES": ConfigDefinition(
            key="API_MAX_RETRIES",
            default="3",
            description="מספר ניסיונות חוזרים בכישלון",
            category="api",
        ),
        
        # ========== Telegram Bot ==========
        "TELEGRAM_BOT_TOKEN": ConfigDefinition(
            key="TELEGRAM_BOT_TOKEN",
            default="",
            description="טוקן הבוט של טלגרם",
            category="telegram",
            sensitive=True,
            required=True,
        ),
        "TELEGRAM_ADMIN_CHAT_ID": ConfigDefinition(
            key="TELEGRAM_ADMIN_CHAT_ID",
            default="",
            description="מזהה הצ'אט של האדמין",
            category="telegram",
            sensitive=True,
        ),
        "TELEGRAM_WEBHOOK_URL": ConfigDefinition(
            key="TELEGRAM_WEBHOOK_URL",
            default="",
            description="כתובת ה-Webhook לטלגרם",
            category="telegram",
        ),
        
        # ========== External Services ==========
        "OPENAI_API_KEY": ConfigDefinition(
            key="OPENAI_API_KEY",
            default="",
            description="מפתח API ל-OpenAI",
            category="external",
            sensitive=True,
        ),
        "SENTRY_DSN": ConfigDefinition(
            key="SENTRY_DSN",
            default="",
            description="DSN ל-Sentry לניטור שגיאות",
            category="external",
            sensitive=True,
        ),
        "GITHUB_TOKEN": ConfigDefinition(
            key="GITHUB_TOKEN",
            default="",
            description="טוקן גישה ל-GitHub",
            category="external",
            sensitive=True,
        ),
        "GOOGLE_DRIVE_CREDENTIALS": ConfigDefinition(
            key="GOOGLE_DRIVE_CREDENTIALS",
            default="",
            description="נתיב לקובץ credentials של Google Drive",
            category="external",
            sensitive=True,
        ),
        
        # ========== Web Server ==========
        "WEB_HOST": ConfigDefinition(
            key="WEB_HOST",
            default="0.0.0.0",
            description="כתובת ה-Host לשרת הווב",
            category="webserver",
        ),
        "WEB_PORT": ConfigDefinition(
            key="WEB_PORT",
            default="8080",
            description="פורט השרת",
            category="webserver",
        ),
        "WEB_SECRET_KEY": ConfigDefinition(
            key="WEB_SECRET_KEY",
            default="",
            description="מפתח סודי לסשנים",
            category="webserver",
            sensitive=True,
            required=True,
        ),
        "WEB_DEBUG": ConfigDefinition(
            key="WEB_DEBUG",
            default="false",
            description="מצב דיבאג (true/false)",
            category="webserver",
        ),
        "WEB_WORKERS": ConfigDefinition(
            key="WEB_WORKERS",
            default="4",
            description="מספר Worker processes",
            category="webserver",
        ),
        
        # ========== Caching ==========
        "REDIS_URL": ConfigDefinition(
            key="REDIS_URL",
            default="",
            description="כתובת Redis לקאש",
            category="cache",
            sensitive=True,
        ),
        "CACHE_TTL_SECONDS": ConfigDefinition(
            key="CACHE_TTL_SECONDS",
            default="3600",
            description="זמן חיים לקאש (שניות)",
            category="cache",
        ),
        "CACHE_MAX_SIZE": ConfigDefinition(
            key="CACHE_MAX_SIZE",
            default="1000",
            description="גודל מקסימלי של הקאש",
            category="cache",
        ),
        
        # ========== Logging & Monitoring ==========
        "LOG_LEVEL": ConfigDefinition(
            key="LOG_LEVEL",
            default="INFO",
            description="רמת הלוגים (DEBUG/INFO/WARNING/ERROR)",
            category="logging",
        ),
        "LOG_FORMAT": ConfigDefinition(
            key="LOG_FORMAT",
            default="json",
            description="פורמט הלוגים (json/text)",
            category="logging",
        ),
        "ENABLE_METRICS": ConfigDefinition(
            key="ENABLE_METRICS",
            default="true",
            description="הפעלת מטריקות Prometheus",
            category="logging",
        ),
        
        # ========== Features ==========
        "FEATURE_AI_EXPLAIN": ConfigDefinition(
            key="FEATURE_AI_EXPLAIN",
            default="true",
            description="הפעלת הסברי AI",
            category="features",
        ),
        "FEATURE_CODE_SHARING": ConfigDefinition(
            key="FEATURE_CODE_SHARING",
            default="true",
            description="הפעלת שיתוף קוד",
            category="features",
        ),
        "FEATURE_IMAGE_GENERATION": ConfigDefinition(
            key="FEATURE_IMAGE_GENERATION",
            default="true",
            description="הפעלת יצירת תמונות קוד",
            category="features",
        ),
        
        # ========== Limits ==========
        "MAX_FILE_SIZE_MB": ConfigDefinition(
            key="MAX_FILE_SIZE_MB",
            default="10",
            description="גודל קובץ מקסימלי (MB)",
            category="limits",
        ),
        "MAX_CODE_LINES": ConfigDefinition(
            key="MAX_CODE_LINES",
            default="5000",
            description="מספר שורות קוד מקסימלי",
            category="limits",
        ),
        "MAX_SNIPPETS_PER_USER": ConfigDefinition(
            key="MAX_SNIPPETS_PER_USER",
            default="500",
            description="מספר סניפטים מקסימלי למשתמש",
            category="limits",
        ),
    }
    
    def __init__(self) -> None:
        """אתחול השירות."""
        self._sensitive_regex = self._compile_sensitive_pattern()
    
    def _compile_sensitive_pattern(self) -> re.Pattern:
        """יצירת Regex לזיהוי משתנים רגישים."""
        patterns = "|".join(re.escape(p) for p in self.SENSITIVE_PATTERNS)
        return re.compile(patterns, re.IGNORECASE)
    
    def is_sensitive_key(self, key: str) -> bool:
        """
        בדיקה האם מפתח מכיל מידע רגיש.
        
        Args:
            key: שם המפתח לבדיקה
            
        Returns:
            True אם המפתח רגיש
        """
        # בדיקת ההגדרה הראשית
        definition = self.CONFIG_DEFINITIONS.get(key)
        if definition and definition.sensitive:
            return True
        
        # בדיקה לפי תבניות
        return bool(self._sensitive_regex.search(key))
    
    def mask_value(self, value: str, key: str) -> str:
        """
        הסתרת ערך רגיש.
        
        Args:
            value: הערך להסתרה
            key: שם המפתח (לבדיקת רגישות)
            
        Returns:
            ערך מוסתר או המקורי
        """
        if not value:
            return value
        
        if self.is_sensitive_key(key):
            return self.MASKED_VALUE
        
        return value
    
    def get_env_value(self, key: str, default: Any = None) -> Optional[str]:
        """
        שליפת ערך ממשתנה סביבה.
        
        Args:
            key: שם המשתנה
            default: ערך ברירת מחדל
            
        Returns:
            הערך מהסביבה או ברירת המחדל
        """
        return os.getenv(key, default)
    
    def determine_status(
        self,
        env_value: Optional[str],
        default_value: Any,
        is_required: bool = False,
    ) -> ConfigStatus:
        """
        קביעת סטטוס הקונפיגורציה.
        
        Args:
            env_value: ערך מהסביבה
            default_value: ערך ברירת המחדל
            is_required: האם המשתנה הכרחי
            
        Returns:
            סטטוס המשתנה
        """
        # אם אין ערך בסביבה
        if env_value is None:
            # אם גם אין דיפולט והמשתנה הכרחי - Missing
            if default_value is None or (is_required and not default_value):
                return ConfigStatus.MISSING
            # יש דיפולט - משתמשים בו
            return ConfigStatus.DEFAULT
        
        # יש ערך בסביבה
        # השוואה לדיפולט
        default_str = str(default_value) if default_value is not None else ""
        if env_value == default_str:
            return ConfigStatus.DEFAULT
        
        return ConfigStatus.MODIFIED
    
    def determine_source(self, env_value: Optional[str]) -> ConfigSource:
        """
        קביעת מקור הערך.
        
        Args:
            env_value: ערך מהסביבה
            
        Returns:
            מקור הערך
        """
        if env_value is not None:
            return ConfigSource.ENVIRONMENT
        return ConfigSource.DEFAULT
    
    def get_config_entry(self, definition: ConfigDefinition) -> ConfigEntry:
        """
        יצירת רשומת קונפיגורציה יחידה.
        
        Args:
            definition: הגדרת המשתנה
            
        Returns:
            רשומת הקונפיגורציה
        """
        key = definition.key
        default = definition.default
        
        # שליפת הערך מהסביבה
        env_value = self.get_env_value(key)
        
        # קביעת מקור וסטטוס
        source = self.determine_source(env_value)
        status = self.determine_status(env_value, default, definition.required)
        
        # הערך הפעיל (מהסביבה או דיפולט)
        active_value = env_value if env_value is not None else str(default or "")
        
        # הסתרת ערכים רגישים
        is_sensitive = self.is_sensitive_key(key) or definition.sensitive
        display_value = self.mask_value(active_value, key) if is_sensitive else active_value
        
        return ConfigEntry(
            key=key,
            active_value=display_value,
            default_value=str(default) if default is not None else "",
            source=source,
            status=status,
            description=definition.description,
            category=definition.category,
            is_sensitive=is_sensitive,
        )
    
    def get_config_overview(
        self,
        category_filter: Optional[str] = None,
        status_filter: Optional[ConfigStatus] = None,
    ) -> ConfigOverview:
        """
        קבלת סקירת קונפיגורציה מלאה.
        
        Args:
            category_filter: סינון לפי קטגוריה
            status_filter: סינון לפי סטטוס
            
        Returns:
            סקירה מלאה של כל הקונפיגורציות
        """
        entries: List[ConfigEntry] = []
        categories_set: set[str] = set()
        
        for definition in self.CONFIG_DEFINITIONS.values():
            entry = self.get_config_entry(definition)
            categories_set.add(entry.category)
            
            # סינון
            if category_filter and entry.category != category_filter:
                continue
            if status_filter and entry.status != status_filter:
                continue
            
            entries.append(entry)
        
        # מיון לפי קטגוריה ואז לפי שם
        entries.sort(key=lambda e: (e.category, e.key))
        
        # חישוב סטטיסטיקות
        modified_count = sum(1 for e in entries if e.status == ConfigStatus.MODIFIED)
        missing_count = sum(1 for e in entries if e.status == ConfigStatus.MISSING)
        default_count = sum(1 for e in entries if e.status == ConfigStatus.DEFAULT)
        
        return ConfigOverview(
            entries=entries,
            generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            total_count=len(entries),
            modified_count=modified_count,
            missing_count=missing_count,
            default_count=default_count,
            categories=sorted(categories_set),
        )
    
    def get_category_summary(self) -> Dict[str, Dict[str, int]]:
        """
        קבלת סיכום לפי קטגוריות.
        
        Returns:
            מילון עם ספירה לכל קטגוריה
        """
        overview = self.get_config_overview()
        summary: Dict[str, Dict[str, int]] = {}
        
        for entry in overview.entries:
            cat = entry.category
            if cat not in summary:
                summary[cat] = {"total": 0, "modified": 0, "missing": 0, "default": 0}
            
            summary[cat]["total"] += 1
            if entry.status == ConfigStatus.MODIFIED:
                summary[cat]["modified"] += 1
            elif entry.status == ConfigStatus.MISSING:
                summary[cat]["missing"] += 1
            else:
                summary[cat]["default"] += 1
        
        return summary
    
    def validate_required(self) -> List[str]:
        """
        בדיקת משתנים הכרחיים חסרים.
        
        Returns:
            רשימת שמות משתנים חסרים
        """
        missing = []
        for definition in self.CONFIG_DEFINITIONS.values():
            if not definition.required:
                continue
            
            env_value = self.get_env_value(definition.key)
            if not env_value and not definition.default:
                missing.append(definition.key)
        
        return missing


# Singleton instance
_config_service: Optional[ConfigService] = None


def get_config_service() -> ConfigService:
    """קבלת instance יחיד של השירות."""
    global _config_service
    if _config_service is None:
        _config_service = ConfigService()
    return _config_service
```

---

## 2. API/Routes – Handler לדף

### הוספה לקובץ: `services/webserver.py`

```python
# הוספה בראש הקובץ (imports)
from services.config_inspector_service import (
    get_config_service,
    ConfigStatus,
)

# הוספת הראוט (בתוך setup_routes או אזור הראוטים)
@routes.get("/admin/config-inspector")
async def admin_config_inspector_handler(request: web.Request) -> web.Response:
    """
    דף Config Inspector לאדמינים.
    מציג סקירה של כל משתני הסביבה והקונפיגורציה.
    """
    # בדיקת הרשאות אדמין
    session = await get_session(request)
    if not session.get("is_admin"):
        raise web.HTTPForbidden(text="Admin access required")
    
    # קבלת פרמטרים לסינון
    category = request.query.get("category", "")
    status = request.query.get("status", "")
    
    # המרת סטטוס לאנום
    status_filter = None
    if status:
        try:
            status_filter = ConfigStatus(status)
        except ValueError:
            pass
    
    # קבלת הנתונים מהשירות
    service = get_config_service()
    overview = service.get_config_overview(
        category_filter=category or None,
        status_filter=status_filter,
    )
    category_summary = service.get_category_summary()
    missing_required = service.validate_required()
    
    # רינדור התבנית
    return render_template(
        "admin_config_inspector.html",
        request,
        overview=overview,
        category_summary=category_summary,
        missing_required=missing_required,
        selected_category=category,
        selected_status=status,
        statuses=[s.value for s in ConfigStatus],
    )
```

### פונקציית עזר (אם לא קיימת)

```python
def render_template(template_name: str, request: web.Request, **context) -> web.Response:
    """רינדור תבנית Jinja2."""
    # הנח שיש לך כבר מנגנון Jinja2 מוגדר
    # אם לא, הנה דוגמה בסיסית:
    import aiohttp_jinja2
    return aiohttp_jinja2.render_template(
        template_name,
        request,
        context,
    )
```

---

## 3. Frontend Template – `admin_config_inspector.html`

### קובץ: `webapp/templates/admin_config_inspector.html`

```html
{% extends "base.html" %}

{% block title %}Config Inspector{% endblock %}

{% block extra_css %}
<style>
/* ================================
   Config Inspector – Glassmorphism Dark Theme
   ================================ */

.config-page {
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
  color: #fff;
  max-width: 1400px;
  margin: 0 auto;
  padding: 1rem;
}

.config-page .page-title {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  font-size: 1.8rem;
  font-weight: 600;
}

.config-page .page-title i {
  color: #64ffda;
}

/* ================================
   Summary Cards (Glassmorphism)
   ================================ */
.config-summary-cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 1rem;
}

.summary-card {
  background: rgba(18, 24, 38, 0.75);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 16px;
  padding: 1.25rem;
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.25);
  transition: transform 0.2s ease, box-shadow 0.2s ease;
}

.summary-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 14px 40px rgba(0, 0, 0, 0.35);
}

.summary-card h3 {
  font-size: 0.85rem;
  margin: 0;
  opacity: 0.7;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.summary-card .card-value {
  font-size: 2.2rem;
  font-weight: 600;
  margin: 0.5rem 0 0;
}

.summary-card .card-value.modified {
  color: #ffa34f;
}

.summary-card .card-value.missing {
  color: #ff627c;
}

.summary-card .card-value.default {
  color: #64ffda;
}

/* ================================
   Filters Bar
   ================================ */
.config-filters {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
  align-items: center;
  padding: 1rem 1.25rem;
  background: rgba(18, 24, 38, 0.6);
  backdrop-filter: blur(10px);
  border-radius: 14px;
  border: 1px solid rgba(255, 255, 255, 0.06);
}

.config-filters label {
  font-size: 0.9rem;
  opacity: 0.8;
}

.config-filters select {
  background: rgba(255, 255, 255, 0.08);
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 999px;
  color: #fff;
  padding: 0.4rem 1rem;
  font-size: 0.9rem;
  cursor: pointer;
  transition: background 0.2s ease;
}

.config-filters select:hover {
  background: rgba(255, 255, 255, 0.12);
}

.config-filters select:focus {
  outline: none;
  border-color: #64ffda;
}

.config-filters select option {
  background: #1a1f2e;
  color: #fff;
}

.filter-btn {
  border: none;
  border-radius: 999px;
  padding: 0.45rem 1.2rem;
  background: linear-gradient(135deg, #64ffda, #4dd0e1);
  color: #0c1725;
  font-weight: 600;
  cursor: pointer;
  transition: box-shadow 0.2s ease, transform 0.2s ease;
}

.filter-btn:hover {
  transform: translateY(-1px);
  box-shadow: 0 8px 20px rgba(100, 255, 218, 0.3);
}

.reset-btn {
  background: rgba(255, 255, 255, 0.08);
  color: #fff;
}

.reset-btn:hover {
  background: rgba(255, 255, 255, 0.15);
  box-shadow: none;
}

/* ================================
   Alerts for Missing Required
   ================================ */
.config-alert {
  display: flex;
  align-items: flex-start;
  gap: 0.75rem;
  padding: 1rem 1.25rem;
  border-radius: 14px;
  font-size: 0.95rem;
}

.config-alert.warning {
  background: rgba(255, 99, 132, 0.12);
  border: 1px solid rgba(255, 99, 132, 0.3);
  color: #ff9bb6;
}

.config-alert i {
  font-size: 1.1rem;
  margin-top: 0.1rem;
}

.config-alert strong {
  color: #fff;
}

.config-alert code {
  background: rgba(0, 0, 0, 0.3);
  padding: 0.15rem 0.4rem;
  border-radius: 4px;
  font-family: monospace;
  font-size: 0.85rem;
}

/* ================================
   Config Table
   ================================ */
.config-table-wrapper {
  background: rgba(18, 24, 38, 0.72);
  backdrop-filter: blur(14px);
  border-radius: 18px;
  padding: 1.25rem;
  border: 1px solid rgba(255, 255, 255, 0.05);
  box-shadow: 0 18px 32px rgba(0, 0, 0, 0.35);
  overflow-x: auto;
}

.config-table-wrapper h2 {
  margin: 0 0 1rem;
  font-size: 1.15rem;
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.config-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.92rem;
}

.config-table thead th {
  text-align: right;
  padding: 0.75rem 0.6rem;
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
  font-weight: 500;
  opacity: 0.8;
  white-space: nowrap;
}

.config-table tbody td {
  padding: 0.7rem 0.6rem;
  border-bottom: 1px solid rgba(255, 255, 255, 0.04);
  vertical-align: middle;
}

.config-table tbody tr:hover {
  background: rgba(255, 255, 255, 0.03);
}

/* Row status highlighting */
.config-table tbody tr.status-modified {
  background: rgba(255, 163, 79, 0.06);
}

.config-table tbody tr.status-modified:hover {
  background: rgba(255, 163, 79, 0.1);
}

.config-table tbody tr.status-missing {
  background: rgba(255, 99, 132, 0.06);
}

.config-table tbody tr.status-missing:hover {
  background: rgba(255, 99, 132, 0.1);
}

/* Key column */
.config-key {
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
  font-size: 0.88rem;
  color: #a5d6ff;
}

.config-key .category-badge {
  display: inline-block;
  font-size: 0.7rem;
  padding: 0.15rem 0.45rem;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.08);
  color: rgba(255, 255, 255, 0.6);
  margin-right: 0.5rem;
  font-family: inherit;
  text-transform: uppercase;
}

/* Value columns */
.config-value {
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
  font-size: 0.85rem;
  word-break: break-all;
  max-width: 300px;
}

.config-value.masked {
  color: #888;
  font-style: italic;
}

.config-value.empty {
  color: #666;
  font-style: italic;
}

/* Source badge */
.source-badge {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  padding: 0.2rem 0.6rem;
  border-radius: 999px;
  font-size: 0.8rem;
}

.source-badge.environment {
  background: rgba(100, 255, 218, 0.12);
  color: #64ffda;
}

.source-badge.default {
  background: rgba(255, 255, 255, 0.08);
  color: rgba(255, 255, 255, 0.6);
}

/* Status pill */
.status-pill {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  padding: 0.25rem 0.7rem;
  border-radius: 999px;
  font-size: 0.8rem;
  font-weight: 500;
}

.status-pill.modified {
  background: rgba(255, 163, 79, 0.18);
  color: #ffa34f;
}

.status-pill.default {
  background: rgba(100, 255, 218, 0.12);
  color: #64ffda;
}

.status-pill.missing {
  background: rgba(255, 99, 132, 0.18);
  color: #ff627c;
}

.status-pill i {
  font-size: 0.75rem;
}

/* Description tooltip */
.config-desc {
  font-size: 0.8rem;
  color: rgba(255, 255, 255, 0.55);
  max-width: 200px;
}

/* ================================
   Copy Button
   ================================ */
.value-wrapper {
  display: flex;
  align-items: center;
  gap: 0.4rem;
}

.copy-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  border: none;
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.06);
  color: rgba(255, 255, 255, 0.5);
  cursor: pointer;
  opacity: 0;
  transition: opacity 0.15s ease, background 0.15s ease, color 0.15s ease;
  flex-shrink: 0;
}

.config-table tbody tr:hover .copy-btn {
  opacity: 1;
}

.copy-btn:hover {
  background: rgba(100, 255, 218, 0.15);
  color: #64ffda;
}

.copy-btn:active {
  transform: scale(0.92);
}

.copy-btn.copied {
  background: rgba(100, 255, 218, 0.2);
  color: #64ffda;
}

.copy-btn i {
  font-size: 0.75rem;
}

/* Toast Notification */
.copy-toast {
  position: fixed;
  bottom: 24px;
  left: 50%;
  transform: translateX(-50%) translateY(100px);
  background: rgba(18, 24, 38, 0.95);
  backdrop-filter: blur(10px);
  color: #64ffda;
  padding: 0.6rem 1.2rem;
  border-radius: 999px;
  font-size: 0.9rem;
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.4);
  border: 1px solid rgba(100, 255, 218, 0.2);
  z-index: 9999;
  opacity: 0;
  transition: transform 0.3s ease, opacity 0.3s ease;
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.copy-toast.show {
  transform: translateX(-50%) translateY(0);
  opacity: 1;
}

.copy-toast i {
  font-size: 0.85rem;
}

/* ================================
   Category Summary Section
   ================================ */
.category-summary {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 0.75rem;
}

.category-card {
  background: rgba(18, 24, 38, 0.6);
  border-radius: 12px;
  padding: 0.9rem 1rem;
  border: 1px solid rgba(255, 255, 255, 0.05);
}

.category-card h4 {
  margin: 0 0 0.5rem;
  font-size: 0.9rem;
  text-transform: capitalize;
  display: flex;
  align-items: center;
  gap: 0.4rem;
}

.category-card h4 i {
  opacity: 0.7;
}

.category-stats {
  display: flex;
  gap: 0.75rem;
  font-size: 0.8rem;
}

.category-stats span {
  display: flex;
  align-items: center;
  gap: 0.25rem;
}

.category-stats .modified { color: #ffa34f; }
.category-stats .missing { color: #ff627c; }
.category-stats .default { color: #64ffda; }

/* ================================
   Footer / Meta
   ================================ */
.config-meta {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 0.85rem;
  opacity: 0.7;
  padding-top: 0.5rem;
}

/* ================================
   Responsive
   ================================ */
@media (max-width: 768px) {
  .config-page .page-title {
    font-size: 1.4rem;
  }
  
  .summary-card .card-value {
    font-size: 1.8rem;
  }
  
  .config-filters {
    flex-direction: column;
    align-items: stretch;
  }
  
  .config-filters select,
  .filter-btn {
    width: 100%;
  }
  
  .config-table {
    font-size: 0.85rem;
  }
  
  .config-value {
    max-width: 150px;
  }
}

/* ================================
   Rose Pine Dawn Theme Support
   ================================ */
:root[data-theme="rose-pine-dawn"] .config-page {
  color: var(--text-primary);
}

:root[data-theme="rose-pine-dawn"] .summary-card,
:root[data-theme="rose-pine-dawn"] .config-table-wrapper,
:root[data-theme="rose-pine-dawn"] .config-filters {
  background: color-mix(in srgb, #ffffff 75%, var(--bg-secondary) 25%);
  border-color: var(--glass-border);
}

:root[data-theme="rose-pine-dawn"] .config-table thead th,
:root[data-theme="rose-pine-dawn"] .config-table tbody td {
  border-color: rgba(87, 82, 121, 0.2);
}

:root[data-theme="rose-pine-dawn"] .config-key {
  color: #286983;
}

:root[data-theme="rose-pine-dawn"] .copy-btn {
  background: rgba(87, 82, 121, 0.08);
  color: rgba(87, 82, 121, 0.5);
}

:root[data-theme="rose-pine-dawn"] .copy-btn:hover {
  background: rgba(40, 105, 131, 0.15);
  color: #286983;
}

:root[data-theme="rose-pine-dawn"] .copy-toast {
  background: rgba(250, 244, 237, 0.95);
  color: #286983;
  border-color: rgba(40, 105, 131, 0.3);
}
</style>
{% endblock %}

{% block content %}
<div class="config-page" dir="rtl">
  <!-- Page Title -->
  <div class="page-title">
    <i class="fas fa-cogs"></i>
    Config Inspector
  </div>

  <!-- Alert for Missing Required Variables -->
  {% if missing_required %}
  <div class="config-alert warning">
    <i class="fas fa-exclamation-triangle"></i>
    <div>
      <strong>אזהרה:</strong> משתני סביבה הכרחיים חסרים:
      {% for key in missing_required %}
        <code>{{ key }}</code>{% if not loop.last %}, {% endif %}
      {% endfor %}
    </div>
  </div>
  {% endif %}

  <!-- Summary Cards -->
  <div class="config-summary-cards">
    <div class="summary-card">
      <h3>סה"כ משתנים</h3>
      <div class="card-value">{{ overview.total_count }}</div>
    </div>
    <div class="summary-card">
      <h3>שונו מדיפולט</h3>
      <div class="card-value modified">{{ overview.modified_count }}</div>
    </div>
    <div class="summary-card">
      <h3>חסרים</h3>
      <div class="card-value missing">{{ overview.missing_count }}</div>
    </div>
    <div class="summary-card">
      <h3>ברירת מחדל</h3>
      <div class="card-value default">{{ overview.default_count }}</div>
    </div>
  </div>

  <!-- Filters -->
  <form class="config-filters" method="get" action="">
    <label for="categoryFilter">קטגוריה:</label>
    <select name="category" id="categoryFilter">
      <option value="">הכל</option>
      {% for cat in overview.categories %}
        <option value="{{ cat }}" {% if selected_category == cat %}selected{% endif %}>
          {{ cat | capitalize }}
        </option>
      {% endfor %}
    </select>
    
    <label for="statusFilter">סטטוס:</label>
    <select name="status" id="statusFilter">
      <option value="">הכל</option>
      {% for s in statuses %}
        <option value="{{ s }}" {% if selected_status == s %}selected{% endif %}>
          {{ s }}
        </option>
      {% endfor %}
    </select>
    
    <button type="submit" class="filter-btn">
      <i class="fas fa-filter"></i> סנן
    </button>
    <a href="?" class="filter-btn reset-btn">
      <i class="fas fa-redo"></i> איפוס
    </a>
  </form>

  <!-- Category Summary -->
  {% if category_summary %}
  <div class="category-summary">
    {% for cat, stats in category_summary.items() %}
    <div class="category-card">
      <h4>
        {% if cat == 'database' %}<i class="fas fa-database"></i>
        {% elif cat == 'api' %}<i class="fas fa-plug"></i>
        {% elif cat == 'telegram' %}<i class="fab fa-telegram"></i>
        {% elif cat == 'external' %}<i class="fas fa-cloud"></i>
        {% elif cat == 'webserver' %}<i class="fas fa-server"></i>
        {% elif cat == 'cache' %}<i class="fas fa-memory"></i>
        {% elif cat == 'logging' %}<i class="fas fa-file-alt"></i>
        {% elif cat == 'features' %}<i class="fas fa-toggle-on"></i>
        {% elif cat == 'limits' %}<i class="fas fa-tachometer-alt"></i>
        {% else %}<i class="fas fa-cog"></i>
        {% endif %}
        {{ cat | capitalize }}
      </h4>
      <div class="category-stats">
        <span class="modified" title="שונו">
          <i class="fas fa-pen"></i> {{ stats.modified }}
        </span>
        <span class="missing" title="חסרים">
          <i class="fas fa-times"></i> {{ stats.missing }}
        </span>
        <span class="default" title="ברירת מחדל">
          <i class="fas fa-check"></i> {{ stats.default }}
        </span>
      </div>
    </div>
    {% endfor %}
  </div>
  {% endif %}

  <!-- Config Table -->
  <div class="config-table-wrapper">
    <h2>
      <i class="fas fa-list"></i>
      פירוט משתנים
    </h2>
    
    {% if overview.entries %}
    <table class="config-table">
      <thead>
        <tr>
          <th>Key</th>
          <th>Active Value</th>
          <th>Default Value</th>
          <th>Source</th>
          <th>Status</th>
          <th>תיאור</th>
        </tr>
      </thead>
      <tbody>
        {% for entry in overview.entries %}
        <tr class="status-{{ entry.status.value | lower }}">
          <td>
            <div class="config-key">
              <span class="category-badge">{{ entry.category }}</span>
              {{ entry.key }}
            </div>
          </td>
          <td>
            <div class="value-wrapper">
              <div class="config-value {% if entry.is_sensitive %}masked{% endif %} {% if not entry.active_value %}empty{% endif %}">
                {% if entry.is_sensitive %}
                  {{ entry.active_value }}
                  <i class="fas fa-lock" style="margin-right: 0.3rem; font-size: 0.75rem; opacity: 0.6;" title="ערך מוסתר"></i>
                {% elif entry.active_value %}
                  {{ entry.active_value }}
                {% else %}
                  (ריק)
                {% endif %}
              </div>
              {% if not entry.is_sensitive and entry.active_value %}
              <button 
                type="button" 
                class="copy-btn" 
                data-copy="{{ entry.active_value }}"
                title="העתק ללוח"
                aria-label="העתק ערך ללוח">
                <i class="fas fa-copy"></i>
              </button>
              {% endif %}
            </div>
          </td>
          <td>
            <div class="config-value {% if not entry.default_value %}empty{% endif %}">
              {% if entry.default_value %}
                {{ entry.default_value }}
              {% else %}
                (ללא)
              {% endif %}
            </div>
          </td>
          <td>
            <span class="source-badge {{ entry.source.value | lower }}">
              {% if entry.source.value == 'Environment' %}
                <i class="fas fa-terminal"></i>
              {% else %}
                <i class="fas fa-code"></i>
              {% endif %}
              {{ entry.source.value }}
            </span>
          </td>
          <td>
            <span class="status-pill {{ entry.status.value | lower }}">
              {% if entry.status.value == 'Modified' %}
                <i class="fas fa-pen"></i>
              {% elif entry.status.value == 'Missing' %}
                <i class="fas fa-exclamation-circle"></i>
              {% else %}
                <i class="fas fa-check"></i>
              {% endif %}
              {{ entry.status.value }}
            </span>
          </td>
          <td>
            <div class="config-desc">{{ entry.description or '—' }}</div>
          </td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
    {% else %}
    <div style="text-align: center; padding: 2rem; opacity: 0.7;">
      <i class="fas fa-inbox" style="font-size: 2rem; margin-bottom: 0.5rem;"></i>
      <p>לא נמצאו משתנים התואמים לסינון</p>
    </div>
    {% endif %}
  </div>

  <!-- Meta Footer -->
  <div class="config-meta">
    <span>
      <i class="fas fa-clock"></i>
      נוצר ב: {{ overview.generated_at }}
    </span>
    <span>
      סה"כ: {{ overview.total_count }} משתנים
    </span>
  </div>
</div>

<script>
(function() {
  // ================================
  // Copy to Clipboard functionality
  // ================================
  
  // Create toast element
  const toast = document.createElement('div');
  toast.className = 'copy-toast';
  toast.innerHTML = '<i class="fas fa-check"></i> <span>הועתק ללוח!</span>';
  document.body.appendChild(toast);
  
  let toastTimeout = null;
  
  function showToast(message = 'הועתק ללוח!') {
    toast.querySelector('span').textContent = message;
    toast.classList.add('show');
    
    if (toastTimeout) {
      clearTimeout(toastTimeout);
    }
    
    toastTimeout = setTimeout(() => {
      toast.classList.remove('show');
    }, 2000);
  }
  
  async function copyToClipboard(text, button) {
    try {
      await navigator.clipboard.writeText(text);
      
      // Visual feedback on button
      button.classList.add('copied');
      const icon = button.querySelector('i');
      icon.className = 'fas fa-check';
      
      showToast();
      
      // Reset button after animation
      setTimeout(() => {
        button.classList.remove('copied');
        icon.className = 'fas fa-copy';
      }, 1500);
      
    } catch (err) {
      console.error('Copy failed:', err);
      showToast('שגיאה בהעתקה');
    }
  }
  
  // Attach click handlers to all copy buttons
  document.querySelectorAll('.copy-btn').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      const value = btn.dataset.copy;
      if (value) {
        copyToClipboard(value, btn);
      }
    });
  });
  
  // ================================
  // Filter functionality
  // ================================
  
  const form = document.querySelector('.config-filters');
  const selects = form.querySelectorAll('select');
  
  selects.forEach(select => {
    select.addEventListener('change', () => {
      // Optional: auto-submit on filter change
      // form.submit();
    });
  });
  
  // Highlight rows on hover with smooth transition
  const rows = document.querySelectorAll('.config-table tbody tr');
  rows.forEach(row => {
    row.style.transition = 'background 0.15s ease';
  });
  
  // ================================
  // Keyboard shortcut: Ctrl+F to focus search
  // ================================
  document.addEventListener('keydown', (e) => {
    // Escape closes toast
    if (e.key === 'Escape' && toast.classList.contains('show')) {
      toast.classList.remove('show');
    }
  });
})();
</script>
{% endblock %}
```

---

## 4. שימוש והרחבה

### הוספת משתנים חדשים

להוספת משתנה קונפיגורציה חדש, הוסף אותו ל-`CONFIG_DEFINITIONS` ב-`ConfigService`:

```python
"MY_NEW_VAR": ConfigDefinition(
    key="MY_NEW_VAR",
    default="default_value",
    description="תיאור המשתנה",
    category="general",  # או קטגוריה אחרת
    sensitive=False,     # True אם צריך להסתיר
    required=False,      # True אם הכרחי
),
```

### הוספת קטגוריות

פשוט השתמש בשם קטגוריה חדש ב-`category` - הוא יופיע אוטומטית בסינון ובסיכום.

### התאמה אישית של תבניות רגישות

הוסף מילים ל-`SENSITIVE_PATTERNS`:

```python
SENSITIVE_PATTERNS: tuple[str, ...] = (
    "TOKEN",
    "KEY",
    # הוסף כאן...
    "MY_CUSTOM_SECRET",
)
```

---

## 5. אבטחה ✅

### מה מוגן?

1. **הסתרת ערכים רגישים** – ערכים שמכילים מילים כמו TOKEN, KEY, PASSWORD וכו' מוחלפים ב-`********`
2. **הגנת Admin** – הראוט מוגן ודורש `is_admin=True` בסשן
3. **אין חשיפה ב-API** – הדף הוא HTML בלבד, אין JSON endpoint שחושף את הנתונים
4. **לוגים** – הקונפיגורציה לא נרשמת ללוגים

### מה **לא** לעשות

❌ אל תוסיף API endpoint שמחזיר JSON עם ערכים רגישים  
❌ אל תשלח את הנתונים ללוגים  
❌ אל תשמור את הסקירה לקובץ  

---

## 6. בדיקות (Tests)

### קובץ: `tests/test_config_inspector_service.py`

```python
"""Unit tests for ConfigService."""

import os
from unittest.mock import patch

import pytest

from services.config_inspector_service import (
    ConfigService,
    ConfigDefinition,
    ConfigStatus,
    ConfigSource,
)


class TestConfigService:
    """Test suite for ConfigService."""

    def setup_method(self):
        """Setup test instance."""
        self.service = ConfigService()

    def test_is_sensitive_key_by_pattern(self):
        """Test sensitive key detection by pattern."""
        assert self.service.is_sensitive_key("API_TOKEN") is True
        assert self.service.is_sensitive_key("DB_PASSWORD") is True
        assert self.service.is_sensitive_key("SECRET_KEY") is True
        assert self.service.is_sensitive_key("MONGODB_URI") is True
        assert self.service.is_sensitive_key("LOG_LEVEL") is False
        assert self.service.is_sensitive_key("MAX_RETRIES") is False

    def test_is_sensitive_key_by_definition(self):
        """Test sensitive key detection by definition."""
        # TELEGRAM_BOT_TOKEN is defined as sensitive
        assert self.service.is_sensitive_key("TELEGRAM_BOT_TOKEN") is True

    def test_mask_value(self):
        """Test value masking."""
        assert self.service.mask_value("my-secret", "API_KEY") == "********"
        assert self.service.mask_value("debug", "LOG_LEVEL") == "debug"
        assert self.service.mask_value("", "API_KEY") == ""

    def test_determine_status_default(self):
        """Test status determination - default case."""
        status = self.service.determine_status(None, "default_val")
        assert status == ConfigStatus.DEFAULT

    def test_determine_status_modified(self):
        """Test status determination - modified case."""
        status = self.service.determine_status("custom_val", "default_val")
        assert status == ConfigStatus.MODIFIED

    def test_determine_status_same_as_default(self):
        """Test status when env value equals default."""
        status = self.service.determine_status("default_val", "default_val")
        assert status == ConfigStatus.DEFAULT

    def test_determine_status_missing(self):
        """Test status determination - missing required."""
        status = self.service.determine_status(None, None, is_required=True)
        assert status == ConfigStatus.MISSING

    def test_determine_source(self):
        """Test source determination."""
        assert self.service.determine_source("value") == ConfigSource.ENVIRONMENT
        assert self.service.determine_source(None) == ConfigSource.DEFAULT

    @patch.dict(os.environ, {"LOG_LEVEL": "DEBUG"})
    def test_get_config_entry_from_env(self):
        """Test config entry retrieval from environment."""
        definition = ConfigDefinition(
            key="LOG_LEVEL",
            default="INFO",
            description="Log level",
            category="logging",
        )
        entry = self.service.get_config_entry(definition)
        
        assert entry.key == "LOG_LEVEL"
        assert entry.active_value == "DEBUG"
        assert entry.default_value == "INFO"
        assert entry.source == ConfigSource.ENVIRONMENT
        assert entry.status == ConfigStatus.MODIFIED

    def test_get_config_entry_with_default(self):
        """Test config entry using default value."""
        definition = ConfigDefinition(
            key="NONEXISTENT_VAR",
            default="fallback",
            description="Test var",
            category="test",
        )
        entry = self.service.get_config_entry(definition)
        
        assert entry.active_value == "fallback"
        assert entry.source == ConfigSource.DEFAULT
        assert entry.status == ConfigStatus.DEFAULT

    def test_get_config_entry_sensitive_masked(self):
        """Test that sensitive values are masked."""
        with patch.dict(os.environ, {"MY_SECRET_KEY": "super-secret-123"}):
            definition = ConfigDefinition(
                key="MY_SECRET_KEY",
                default="",
                description="Secret",
                category="security",
                sensitive=True,
            )
            entry = self.service.get_config_entry(definition)
            
            assert entry.active_value == "********"
            assert entry.is_sensitive is True

    def test_get_config_overview(self):
        """Test full config overview generation."""
        overview = self.service.get_config_overview()
        
        assert overview.total_count > 0
        assert overview.generated_at != ""
        assert isinstance(overview.entries, list)
        assert len(overview.categories) > 0

    def test_get_config_overview_with_category_filter(self):
        """Test overview with category filter."""
        overview = self.service.get_config_overview(category_filter="database")
        
        for entry in overview.entries:
            assert entry.category == "database"

    def test_get_config_overview_with_status_filter(self):
        """Test overview with status filter."""
        overview = self.service.get_config_overview(
            status_filter=ConfigStatus.DEFAULT
        )
        
        for entry in overview.entries:
            assert entry.status == ConfigStatus.DEFAULT

    def test_validate_required_empty_env(self):
        """Test validation of required variables."""
        # Clear relevant env vars for test
        with patch.dict(os.environ, {}, clear=True):
            missing = self.service.validate_required()
            # Should contain required vars without defaults
            assert isinstance(missing, list)

    def test_category_summary(self):
        """Test category summary generation."""
        summary = self.service.get_category_summary()
        
        assert isinstance(summary, dict)
        for cat, stats in summary.items():
            assert "total" in stats
            assert "modified" in stats
            assert "missing" in stats
            assert "default" in stats
```

### הרצת הבדיקות

```bash
pytest tests/test_config_inspector_service.py -v
```

---

## 7. צ'קליסט למימוש

- [ ] יצירת `services/config_inspector_service.py`
- [ ] הוספת הראוט ל-`services/webserver.py`
- [ ] יצירת `webapp/templates/admin_config_inspector.html`
- [ ] הוספת קישור בתפריט האדמין
- [ ] כתיבת בדיקות
- [ ] בדיקה ידנית בסביבת פיתוח
- [ ] Review אבטחה (ערכים רגישים מוסתרים)
- [ ] Deploy לסביבת staging

---

## 8. תוצאה צפויה

לאחר המימוש, תקבל דף אדמין שנראה כך:

```
┌─────────────────────────────────────────────────────────────────┐
│ ⚙️ Config Inspector                                             │
├─────────────────────────────────────────────────────────────────┤
│ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐            │
│ │ 42       │ │ 8        │ │ 2        │ │ 32       │            │
│ │ סה"כ     │ │ שונו     │ │ חסרים    │ │ ברירת    │            │
│ │ משתנים   │ │ מדיפולט  │ │          │ │ מחדל     │            │
│ └──────────┘ └──────────┘ └──────────┘ └──────────┘            │
├─────────────────────────────────────────────────────────────────┤
│ קטגוריה: [כל ▼]  סטטוס: [כל ▼]  [סנן] [איפוס]                  │
├─────────────────────────────────────────────────────────────────┤
│ Key                │ Active        │ Default │ Source │ Status │
│────────────────────┼───────────────┼─────────┼────────┼────────│
│ [db] MONGODB_URI   │ ******** 🔒  │ mongo.. │ Env    │ Modified│
│ [db] DB_TIMEOUT_MS │ 10000    [📋]│ 5000    │ Env    │ Modified│
│ [api] API_TIMEOUT  │ 30       [📋]│ 30      │ Default│ Default │
│ ...                │               │         │        │         │
└─────────────────────────────────────────────────────────────────┘
                           ↑
                  כפתור העתקה (לערכים לא-רגישים)
```

**לגנדה:**
- 🔒 = ערך רגיש (מוסתר, ללא כפתור העתקה)
- 📋 = כפתור העתקה (מופיע ב-hover)

---

---

## 9. פיצ'רים נוספים

### כפתור העתקה (Copy to Clipboard) 📋

לכל ערך שאינו רגיש מופיע כפתור העתקה קטן:

```
┌────────────────────────────────────────────────────┐
│ LOG_LEVEL    │  DEBUG  [📋]  │  INFO  │ Env │ ...  │
└────────────────────────────────────────────────────┘
                      ↑
              כפתור העתקה (מופיע ב-hover)
```

**התנהגות:**
- הכפתור מופיע רק כש-hover על השורה
- לחיצה מעתיקה את הערך ללוח
- מוצגת הודעת Toast "הועתק ללוח!" למשך 2 שניות
- הכפתור **לא מופיע** לערכים רגישים (מוסתרים)

**קוד ה-JavaScript:**
```javascript
async function copyToClipboard(text, button) {
  try {
    await navigator.clipboard.writeText(text);
    showToast('הועתק ללוח!');
  } catch (err) {
    showToast('שגיאה בהעתקה');
  }
}
```

---

## שאלות נפוצות

### ש: איך מוסיפים משתנה חדש?

הוסף `ConfigDefinition` ל-`CONFIG_DEFINITIONS` בשירות.

### ש: מה קורה אם משתנה לא מוגדר?

אם יש `default` - יוצג הדיפולט עם סטטוס "Default".  
אם אין ויש `required=True` - יוצג סטטוס "Missing" עם אזהרה.

### ש: האם אפשר לערוך ערכים מהדף?

לא. הדף הוא **קריאה בלבד** מטעמי אבטחה.  
שינוי קונפיגורציה נעשה דרך משתני סביבה או קבצי config.

### ש: איך מוסיפים אייקון לקטגוריה חדשה?

בתבנית HTML, הוסף תנאי `{% elif cat == 'my_category' %}` עם האייקון הרצוי.
