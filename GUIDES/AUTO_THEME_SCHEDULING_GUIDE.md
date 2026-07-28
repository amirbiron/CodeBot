# מדריך מימוש - תחלופת ערכות נושא אוטומטית לפי שעות ביממה

**תאריך**: ינואר 2026  
**גרסה**: 1.1  
**סטטוס**: מדריך מימוש

---

## 📋 תוכן עניינים

1. [סקירה כללית](#סקירה-כללית)
2. [החלטות עיצוב מרכזיות](#החלטות-עיצוב-מרכזיות)
3. [ארכיטקטורה](#ארכיטקטורה)
4. [שלב 1: עדכון מבנה הנתונים](#שלב-1-עדכון-מבנה-הנתונים)
5. [שלב 2: יצירת API Backend](#שלב-2-יצירת-api-backend)
6. [שלב 3: מימוש הלוגיקה בצד הלקוח](#שלב-3-מימוש-הלוגיקה-בצד-הלקוח)
7. [שלב 4: עדכון ממשק המשתמש](#שלב-4-עדכון-ממשק-המשתמש)
8. [שלב 5: אינטגרציה עם המערכת הקיימת](#שלב-5-אינטגרציה-עם-המערכת-הקיימת)
9. [שלב 6: בדיקות](#שלב-6-בדיקות)
10. [שיקולי UX ונגישות](#שיקולי-ux-ונגישות)
11. [סיכום](#סיכום)

---

## סקירה כללית

### מה הפיצ'ר עושה?

מאפשר למשתמשים להגדיר תחלופה אוטומטית בין ערכות נושא לפי שעות ביממה:

- **ערכת יום** (Day Theme): מופעלת בשעות היום שהמשתמש הגדיר
- **ערכת לילה** (Night Theme): מופעלת בשעות הלילה שהמשתמש הגדיר
- **מצב ידני**: המשתמש יכול לכבות את האוטומציה ולבחור ערכה קבועה

### דוגמה לתרחיש שימוש

> יוסי מעדיף ערכה בהירה (Classic) ביום כדי לעבוד בסביבה מוארת,  
> ובלילה הוא עובר לערכה כהה (Dark) כדי להפחית עומס על העיניים.  
> הוא מגדיר: יום = 07:00-20:00, לילה = 20:00-07:00.

### יתרונות

- ✅ הפחתת עומס על העיניים בשעות הלילה
- ✅ התאמה אוטומטית ללא צורך בהחלפה ידנית
- ✅ גמישות מלאה לבחירת שעות וערכות
- ✅ תמיכה בכל סוגי הערכות (Built-in, Shared, Custom)

---

## החלטות עיצוב מרכזיות

לפני המימוש, חשוב להגדיר מספר החלטות מוצריות:

### 1. מקור האמת לזמן: הלקוח (Client-Side)

**הבעיה**: השרת רץ ב-UTC, אבל המשתמש רואה שעון מקומי.

**ההחלטה**: 
- **הלקוח** הוא מקור האמת לחישוב התקופה הנוכחית (יום/לילה)
- השרת **לא מחשב** ולא מעדכן את `ui_prefs.theme` בזמן שמירת הגדרות
- השרת רק שומר את ההגדרות ומחזיר אותן ללקוח

**יתרונות**:
- ✅ המשתמש רואה את מה שהוא מצפה לראות לפי השעון שלו
- ✅ אין צורך לשמור timezone בהעדפות
- ✅ פשוט יותר למימוש ולתחזוקה

### 2. טווח שעות יום: ללא חציית חצות

**הבעיה**: אם המשתמש מגדיר יום = `20:00 → 07:00`, זה מבלבל - האם זה "יום" או "לילה"?

**ההחלטה**:
- **שעות יום חייבות להיות רציפות** (day_start < day_end)
- לא מאפשרים הגדרת יום שחוצה חצות
- וולידציה חוסמת: אם `day_start >= day_end` → שגיאה

**דוגמאות חוקיות**:
- יום: 06:00 → 20:00 ✅
- יום: 08:00 → 18:00 ✅
- יום: 00:00 → 12:00 ✅ (משמרת לילה הפוכה)

**דוגמאות לא חוקיות**:
- יום: 20:00 → 07:00 ❌ (חוצה חצות)
- יום: 12:00 → 12:00 ❌ (0 דקות)

### 3. התנהגות בעת שינוי ידני (Override)

**הבעיה**: מה קורה אם המשתמש לוחץ ידנית על "כהה" בזמן שהתזמון פעיל?

**ההחלטה**: **Override זמני עד המעבר הבא**
- המשתמש יכול לשנות ידנית בכל רגע
- השינוי הידני נשמר ב-`localStorage` כ-`manual_override`
- ברגע שמגיע זמן המעבר הבא, ה-override מתבטל והתזמון חוזר לפעול
- הודעת UI מיידעת: "התזמון פעיל. השינוי יחזיק עד XX:XX"

### 4. שמירת מזהה ערכה מלא

**הבעיה**: "custom" הוא לא מזהה ערכה אמיתי, אלא קטגוריה.

**ההחלטה**:
- לשמור תמיד את המזהה המלא של הערכה
- פורמט: `builtin:<name>`, `shared:<id>`, `custom:<id>`
- לוולידציה מול DB אם הערכה קיימת (shared/custom)

**דוגמאות**:
```json
{
  "day_theme": "builtin:classic",
  "night_theme": "builtin:dark"
}
// או
{
  "day_theme": "shared:abc123",
  "night_theme": "custom:my-theme-uuid"
}
```

### 5. טיימר חכם במקום Polling

**הבעיה**: `setInterval` כל דקה זה עובד, אבל לא אופטימלי.

**ההחלטה**:
- לחשב את הזמן המדויק עד המעבר הבא
- להגדיר `setTimeout` לאירוע הספציפי
- לאחר כל מעבר, לחשב מחדש את הטיימר הבא
- Timer גיבוי כל 5 דקות למקרה של drift

---

## ארכיטקטורה

### תרשים זרימה

```
┌─────────────────────────────────────────────────────────────┐
│                    User Settings Page                        │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │ Enable Auto │  │ Day Theme   │  │ Start/End Hours     │  │
│  │   Toggle    │  │ Selector    │  │ Time Pickers        │  │
│  └──────┬──────┘  └──────┬──────┘  └──────────┬──────────┘  │
│         │                │                     │             │
└─────────┼────────────────┼─────────────────────┼─────────────┘
          │                │                     │
          ▼                ▼                     ▼
┌─────────────────────────────────────────────────────────────┐
│                    API Layer (Flask)                         │
│                                                              │
│  POST /api/theme-schedule                                    │
│  GET  /api/theme-schedule                                    │
│                                                              │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                    MongoDB                                   │
│                                                              │
│  users.ui_prefs.theme_schedule: {                           │
│    enabled: true,                                            │
│    day_theme: "classic",                                     │
│    night_theme: "dark",                                      │
│    day_start: "07:00",                                       │
│    day_end: "20:00"                                          │
│  }                                                           │
└─────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│               Client-Side Logic (JavaScript)                 │
│                                                              │
│  1. Load schedule settings on page load                      │
│  2. Calculate current period (day/night)                     │
│  3. Apply appropriate theme                                  │
│  4. Set timer for next transition                            │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### מבנה הקבצים

```
webapp/
├── themes_api.py              # הוספת endpoints חדשים
├── static/
│   └── js/
│       └── theme-scheduler.js # לוגיקה צד לקוח (קובץ חדש)
└── templates/
    └── settings/
        └── theme_schedule.html # ממשק הגדרות (קובץ חדש)
```

---

## שלב 1: עדכון מבנה הנתונים

### 1.1 סכמת MongoDB

הוסף לאובייקט `ui_prefs` של המשתמש:

```javascript
// users collection - ui_prefs schema extension
{
  "user_id": 123456,
  "ui_prefs": {
    "theme": "classic",           // ערכה נוכחית (קיים)
    "font_scale": 1.0,            // (קיים)
    
    // 🆕 הגדרות תזמון ערכות
    "theme_schedule": {
      "enabled": false,           // האם התזמון מופעל
      "day_theme": "builtin:classic",   // ערכת יום (מזהה מלא)
      "night_theme": "builtin:dark",    // ערכת לילה (מזהה מלא)
      "day_start": "07:00",       // שעת התחלת יום (HH:MM)
      "day_end": "20:00"          // שעת סיום יום (HH:MM) - חייב להיות > day_start
    }
  }
}
```

**פורמט מזהה ערכה**:
- `builtin:<name>` - ערכות מובנות (classic, dark, dim, etc.)
- `shared:<id>` - ערכות ציבוריות מהספרייה
- `custom:<uuid>` - ערכות מותאמות אישית של המשתמש

### 1.2 ערכי ברירת מחדל

```python
# services/constants.py או webapp/themes_api.py

DEFAULT_THEME_SCHEDULE = {
    "enabled": False,
    "day_theme": "builtin:classic",
    "night_theme": "builtin:dark",
    "day_start": "07:00",
    "day_end": "20:00",
}

# ערכות נושא מובנות (Built-in)
BUILTIN_THEMES = {
    "classic", "dark", "dim", "nebula", "ocean", 
    "forest", "rose-pine-dawn", "high-contrast"
}

# Prefixes חוקיים למזהה ערכה
VALID_THEME_PREFIXES = ("builtin:", "shared:", "custom:")
```

### 1.3 וולידציה

```python
import re
from datetime import datetime
from typing import Optional

def validate_time_format(time_str: str) -> bool:
    """בודק שפורמט השעה תקין (HH:MM)."""
    if not time_str or not isinstance(time_str, str):
        return False
    pattern = r"^([01]?[0-9]|2[0-3]):([0-5][0-9])$"
    return bool(re.match(pattern, time_str.strip()))


def time_to_minutes(time_str: str) -> int:
    """ממיר מחרוזת שעה למספר דקות מחצות."""
    parts = time_str.strip().split(":")
    return int(parts[0]) * 60 + int(parts[1])


def validate_theme_identifier(theme_id: str, db=None, user_id: Optional[int] = None) -> tuple[bool, str]:
    """
    מאמת מזהה ערכה מלא.
    
    Args:
        theme_id: מזהה בפורמט prefix:value
        db: חיבור ל-DB (אופציונלי, לבדיקת קיום)
        user_id: מזהה משתמש (נדרש לבדיקת custom themes)
    
    Returns:
        (is_valid, error_message)
    """
    if not theme_id or not isinstance(theme_id, str):
        return False, "missing_theme_id"
    
    theme_id = theme_id.strip().lower()
    
    # בדיקת prefix
    if not any(theme_id.startswith(p) for p in VALID_THEME_PREFIXES):
        return False, "invalid_theme_prefix"
    
    # בדיקת builtin
    if theme_id.startswith("builtin:"):
        name = theme_id.split(":", 1)[1]
        if name not in BUILTIN_THEMES:
            return False, "unknown_builtin_theme"
        return True, ""
    
    # בדיקת shared (אופציונלי - נגד DB)
    if theme_id.startswith("shared:"):
        if db is not None:
            shared_id = theme_id.split(":", 1)[1]
            exists = db.shared_themes.find_one(
                {"_id": shared_id, "is_active": True},
                {"_id": 1}
            )
            if not exists:
                return False, "shared_theme_not_found"
        return True, ""
    
    # בדיקת custom (אופציונלי - נגד DB)
    if theme_id.startswith("custom:"):
        if db is not None and user_id:
            custom_id = theme_id.split(":", 1)[1]
            exists = db.users.find_one(
                {"user_id": user_id, "custom_themes.id": custom_id},
                {"_id": 1}
            )
            if not exists:
                return False, "custom_theme_not_found"
        return True, ""
    
    return False, "invalid_theme_id"


def validate_theme_schedule(schedule: dict, db=None, user_id: Optional[int] = None) -> tuple[bool, str]:
    """
    מאמת את הגדרות תזמון הערכות.
    
    Returns:
        (is_valid, error_message)
    """
    if not isinstance(schedule, dict):
        return False, "invalid_format"
    
    # בדיקת enabled
    if "enabled" in schedule and not isinstance(schedule["enabled"], bool):
        return False, "invalid_enabled_value"
    
    # בדיקת ערכות נושא
    for key in ("day_theme", "night_theme"):
        if key in schedule:
            is_valid, error = validate_theme_identifier(
                schedule[key], db=db, user_id=user_id
            )
            if not is_valid:
                return False, f"{key}_{error}"
    
    # בדיקת שעות
    day_start = schedule.get("day_start")
    day_end = schedule.get("day_end")
    
    if day_start is not None:
        if not validate_time_format(day_start):
            return False, "invalid_day_start_format"
    
    if day_end is not None:
        if not validate_time_format(day_end):
            return False, "invalid_day_end_format"
    
    # 🔒 וולידציה קריטית: day_start חייב להיות קטן מ-day_end
    if day_start and day_end:
        start_mins = time_to_minutes(day_start)
        end_mins = time_to_minutes(day_end)
        
        if start_mins >= end_mins:
            return False, "day_start_must_be_before_day_end"
        
        # מינימום שעה אחת של יום
        if end_mins - start_mins < 60:
            return False, "day_range_too_short"
    
    return True, ""
```

---

## שלב 2: יצירת API Backend

### 2.1 הוספה ל-`themes_api.py`

הוסף את הקוד הבא לקובץ `webapp/themes_api.py`:

```python
# ============================================================
# Theme Schedule API - תזמון ערכות לפי שעות
# ============================================================

DEFAULT_THEME_SCHEDULE = {
    "enabled": False,
    "day_theme": "classic",
    "night_theme": "dark",
    "day_start": "07:00",
    "day_end": "20:00",
}

ALLOWED_SCHEDULE_THEMES = {
    "classic", "dark", "dim", "nebula", "ocean",
    "forest", "rose-pine-dawn", "high-contrast", "custom"
}


def _validate_time_format(time_str: str) -> bool:
    """בודק שפורמט השעה תקין (HH:MM)."""
    if not time_str or not isinstance(time_str, str):
        return False
    import re
    pattern = r"^([01]?[0-9]|2[0-3]):([0-5][0-9])$"
    return bool(re.match(pattern, time_str.strip()))


def _validate_theme_schedule(schedule: dict) -> tuple[bool, str]:
    """מאמת את הגדרות תזמון הערכות."""
    if not isinstance(schedule, dict):
        return False, "invalid_format"

    if "enabled" in schedule and not isinstance(schedule["enabled"], bool):
        return False, "invalid_enabled_value"

    for key in ("day_theme", "night_theme"):
        if key in schedule:
            theme = schedule[key]
            if not isinstance(theme, str):
                return False, f"invalid_{key}"
            theme_lower = theme.lower().strip()
            if not (theme_lower in ALLOWED_SCHEDULE_THEMES or 
                    theme_lower.startswith("shared:") or
                    theme_lower == "custom"):
                return False, f"invalid_{key}"

    for key in ("day_start", "day_end"):
        if key in schedule:
            if not _validate_time_format(schedule[key]):
                return False, f"invalid_{key}_format"

    return True, ""


@themes_bp.route("/schedule", methods=["GET"])
@require_auth
def get_theme_schedule():
    """
    קבלת הגדרות תזמון ערכות הנושא.
    
    Response:
    {
        "ok": true,
        "schedule": {
            "enabled": false,
            "day_theme": "classic",
            "night_theme": "dark",
            "day_start": "07:00",
            "day_end": "20:00"
        }
    }
    """
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    try:
        db_ref = get_db()
        user_doc = db_ref.users.find_one(
            {"user_id": int(user_id)},
            {"ui_prefs.theme_schedule": 1}
        ) or {}

        ui_prefs = user_doc.get("ui_prefs") or {}
        schedule = ui_prefs.get("theme_schedule") or {}

        # מיזוג עם ברירות מחדל
        merged_schedule = {**DEFAULT_THEME_SCHEDULE, **schedule}

        return jsonify({"ok": True, "schedule": merged_schedule})

    except Exception as e:
        logger.exception("get_theme_schedule failed: %s", e)
        return jsonify({"ok": False, "error": "database_error"}), 500


@themes_bp.route("/schedule", methods=["POST"])
@require_auth
def update_theme_schedule():
    """
    עדכון הגדרות תזמון ערכות הנושא.
    
    Request body:
    {
        "enabled": true,
        "day_theme": "builtin:classic",
        "night_theme": "builtin:dark",
        "day_start": "07:00",
        "day_end": "20:00"
    }
    
    Response:
    {
        "ok": true,
        "message": "הגדרות התזמון נשמרו",
        "schedule": { ... }
    }
    
    הערה חשובה:
    - השרת לא מחשב את הערכה הנוכחית ולא מעדכן ui_prefs.theme
    - הלקוח הוא מקור האמת לזמן (שעון מקומי של המשתמש)
    - day_start חייב להיות קטן מ-day_end (אין תמיכה בטווח שחוצה חצות)
    """
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    data = request.get_json(silent=True) or {}

    try:
        db_ref = get_db()
        
        # וולידציה מלאה כולל בדיקת קיום ערכות ב-DB
        is_valid, error_msg = _validate_theme_schedule(
            data, db=db_ref, user_id=int(user_id)
        )
        if not is_valid:
            # מיפוי שגיאות לעברית
            error_messages = {
                "invalid_format": "פורמט לא תקין",
                "invalid_enabled_value": "ערך enabled לא תקין",
                "day_theme_missing_theme_id": "חסר מזהה ערכת יום",
                "day_theme_invalid_theme_prefix": "פורמט ערכת יום לא תקין",
                "day_theme_unknown_builtin_theme": "ערכת יום לא קיימת",
                "day_theme_shared_theme_not_found": "ערכת יום שיתופית לא נמצאה",
                "day_theme_custom_theme_not_found": "ערכת יום מותאמת לא נמצאה",
                "night_theme_missing_theme_id": "חסר מזהה ערכת לילה",
                "night_theme_invalid_theme_prefix": "פורמט ערכת לילה לא תקין",
                "night_theme_unknown_builtin_theme": "ערכת לילה לא קיימת",
                "night_theme_shared_theme_not_found": "ערכת לילה שיתופית לא נמצאה",
                "night_theme_custom_theme_not_found": "ערכת לילה מותאמת לא נמצאה",
                "invalid_day_start_format": "פורמט שעת התחלה לא תקין (נדרש HH:MM)",
                "invalid_day_end_format": "פורמט שעת סיום לא תקין (נדרש HH:MM)",
                "day_start_must_be_before_day_end": "שעת התחלה חייבת להיות לפני שעת הסיום",
                "day_range_too_short": "טווח היום חייב להיות לפחות שעה",
            }
            message = error_messages.get(error_msg, error_msg)
            return jsonify({"ok": False, "error": error_msg, "message": message}), 400

        now_utc = datetime.now(timezone.utc)

        # קריאה קודמת לקבלת ערכים קיימים
        user_doc = db_ref.users.find_one(
            {"user_id": int(user_id)},
            {"ui_prefs.theme_schedule": 1}
        ) or {}

        existing_schedule = (user_doc.get("ui_prefs") or {}).get("theme_schedule") or {}

        # מיזוג: ברירות מחדל <- קיים <- חדש
        new_schedule = {
            **DEFAULT_THEME_SCHEDULE,
            **existing_schedule,
        }

        # עדכון רק שדות שנשלחו
        if "enabled" in data:
            new_schedule["enabled"] = bool(data["enabled"])
        if "day_theme" in data:
            new_schedule["day_theme"] = str(data["day_theme"]).strip().lower()
        if "night_theme" in data:
            new_schedule["night_theme"] = str(data["night_theme"]).strip().lower()
        if "day_start" in data:
            new_schedule["day_start"] = str(data["day_start"]).strip()
        if "day_end" in data:
            new_schedule["day_end"] = str(data["day_end"]).strip()

        # שמירה - ללא עדכון ui_prefs.theme (הלקוח יעשה זאת)
        db_ref.users.update_one(
            {"user_id": int(user_id)},
            {
                "$set": {
                    "ui_prefs.theme_schedule": new_schedule,
                    "updated_at": now_utc,
                }
            },
            upsert=True,
        )

        return jsonify({
            "ok": True,
            "message": "הגדרות התזמון נשמרו",
            "schedule": new_schedule,
        })

    except Exception as e:
        logger.exception("update_theme_schedule failed: %s", e)
        return jsonify({"ok": False, "error": "database_error"}), 500


def _extract_theme_name(theme_id: str) -> str:
    """
    מחלץ את שם הערכה מהמזהה המלא.
    לדוגמה: "builtin:dark" -> "dark", "shared:abc123" -> "shared:abc123"
    """
    if not theme_id:
        return "classic"
    
    if theme_id.startswith("builtin:"):
        return theme_id.split(":", 1)[1]
    
    # עבור shared/custom, מחזירים את המזהה המלא (ה-JS יטפל בזה)
    return theme_id
```

**הערה חשובה**: השרת לא מחשב את הערכה הנוכחית לפי זמן. כל החישובים מתבצעים בצד הלקוח (ראה שלב 3).

---

## שלב 3: מימוש הלוגיקה בצד הלקוח

### 3.1 יצירת `theme-scheduler.js`

צור קובץ חדש: `webapp/static/js/theme-scheduler.js`

```javascript
/**
 * Theme Scheduler - תזמון אוטומטי של ערכות נושא לפי שעות
 * 
 * עקרונות מרכזיים:
 * 1. הלקוח הוא מקור האמת לזמן (שעון מקומי)
 * 2. day_start < day_end תמיד (אין חציית חצות)
 * 3. טיימר חכם - setTimeout לאירוע הבא, לא polling
 * 4. תמיכה ב-override ידני זמני
 */

(function() {
    'use strict';

    // === קבועים ===
    const STORAGE_KEY = 'theme_schedule_cache';
    const OVERRIDE_KEY = 'theme_manual_override';
    const CACHE_MAX_AGE_MS = 24 * 60 * 60 * 1000; // 24 שעות
    const BACKUP_CHECK_INTERVAL = 5 * 60 * 1000; // גיבוי כל 5 דקות

    // === מצב ===
    let currentSchedule = null;
    let nextChangeTimer = null;
    let backupTimer = null;

    // === עזר: זמן ===

    /**
     * המרת מחרוזת שעה למספר דקות מחצות
     */
    function timeToMinutes(timeStr) {
        if (!timeStr || typeof timeStr !== 'string') return 0;
        const parts = timeStr.split(':');
        return (parseInt(parts[0], 10) || 0) * 60 + (parseInt(parts[1], 10) || 0);
    }

    /**
     * המרת דקות לפורמט שעה
     */
    function formatMinutesToTime(minutes) {
        const hours = Math.floor(minutes / 60) % 24;
        const mins = minutes % 60;
        return `${String(hours).padStart(2, '0')}:${String(mins).padStart(2, '0')}`;
    }

    /**
     * קבלת השעה הנוכחית כמספר דקות
     */
    function getCurrentMinutes() {
        const now = new Date();
        return now.getHours() * 60 + now.getMinutes();
    }

    /**
     * חישוב מספר מילישניות עד שעה מסוימת
     */
    function getMillisecondsUntil(targetMinutes) {
        const now = new Date();
        const currentMins = now.getHours() * 60 + now.getMinutes();
        const currentSecs = now.getSeconds();
        
        let diffMins;
        if (targetMinutes > currentMins) {
            diffMins = targetMinutes - currentMins;
        } else {
            // מחר
            diffMins = (24 * 60 - currentMins) + targetMinutes;
        }
        
        // המרה למילישניות, מינוס השניות שכבר עברו
        return (diffMins * 60 - currentSecs) * 1000;
    }

    // === עזר: מזהה ערכה ===

    /**
     * חילוץ שם הערכה מהמזהה המלא
     * "builtin:dark" -> "dark"
     * "shared:abc123" -> נשאר כמו שהוא (נטפל ב-applyTheme)
     */
    function extractThemeName(themeId) {
        if (!themeId) return 'classic';
        
        if (themeId.startsWith('builtin:')) {
            return themeId.split(':', 2)[1];
        }
        // shared/custom - מחזירים את ה-id המלא
        return themeId;
    }

    // === לוגיקה מרכזית ===

    /**
     * חישוב התקופה הנוכחית (יום/לילה) והערכה המתאימה
     * 
     * הנחה: day_start < day_end (כבר עבר וולידציה בשרת)
     */
    function calculateCurrentPeriod(schedule) {
        if (!schedule || !schedule.enabled) {
            return { period: null, theme: null, nextChangeIn: null, nextChangeAt: null };
        }

        const currentMins = getCurrentMinutes();
        const dayStart = timeToMinutes(schedule.day_start || '07:00');
        const dayEnd = timeToMinutes(schedule.day_end || '20:00');
        
        // לוגיקה פשוטה: יום = בתוך הטווח [dayStart, dayEnd)
        const isDay = currentMins >= dayStart && currentMins < dayEnd;
        
        // הערכה הנוכחית
        const themeId = isDay ? schedule.day_theme : schedule.night_theme;
        const theme = extractThemeName(themeId || (isDay ? 'builtin:classic' : 'builtin:dark'));
        
        // זמן המעבר הבא
        const nextChangeAt = isDay ? dayEnd : dayStart;
        const nextChangeIn = getMillisecondsUntil(nextChangeAt);

        return {
            period: isDay ? 'day' : 'night',
            theme: theme,
            themeId: themeId, // המזהה המלא
            nextChangeIn: nextChangeIn, // במילישניות
            nextChangeAt: formatMinutesToTime(nextChangeAt),
        };
    }

    // === Override ידני ===

    /**
     * בדיקה אם יש override ידני פעיל
     */
    function getManualOverride() {
        try {
            const data = localStorage.getItem(OVERRIDE_KEY);
            if (!data) return null;
            
            const override = JSON.parse(data);
            const now = Date.now();
            
            // בדיקה אם ה-override עדיין תקף
            if (override.expiresAt && override.expiresAt > now) {
                return override;
            }
            
            // פג תוקף - מוחקים
            localStorage.removeItem(OVERRIDE_KEY);
            return null;
        } catch (e) {
            return null;
        }
    }

    /**
     * הגדרת override ידני (זמני עד המעבר הבא)
     */
    function setManualOverride(theme) {
        if (!currentSchedule || !currentSchedule.enabled) return;
        
        const result = calculateCurrentPeriod(currentSchedule);
        if (!result.nextChangeIn) return;
        
        const override = {
            theme: theme,
            setAt: Date.now(),
            expiresAt: Date.now() + result.nextChangeIn,
            expiresAtFormatted: result.nextChangeAt,
        };
        
        try {
            localStorage.setItem(OVERRIDE_KEY, JSON.stringify(override));
        } catch (e) {
            // ignore
        }
        
        // הודעה למשתמש
        showOverrideNotification(result.nextChangeAt);
    }

    /**
     * ביטול override ידני
     */
    function clearManualOverride() {
        try {
            localStorage.removeItem(OVERRIDE_KEY);
        } catch (e) {
            // ignore
        }
    }

    /**
     * הצגת הודעה על override
     */
    function showOverrideNotification(expiresAt) {
        // בדיקה אם כבר יש toast
        const existing = document.querySelector('.theme-override-toast');
        if (existing) existing.remove();
        
        const toast = document.createElement('div');
        toast.className = 'theme-override-toast';
        toast.innerHTML = `
            <i class="fas fa-info-circle"></i>
            <span>התזמון האוטומטי פעיל. השינוי הידני יתבטל ב-${expiresAt}</span>
            <button onclick="this.parentElement.remove()" class="toast-close">&times;</button>
        `;
        toast.style.cssText = `
            position: fixed;
            bottom: 20px;
            left: 50%;
            transform: translateX(-50%);
            background: var(--warning, #f59e0b);
            color: #000;
            padding: 0.75rem 1rem;
            border-radius: 10px;
            z-index: 9999;
            display: flex;
            align-items: center;
            gap: 0.5rem;
            box-shadow: 0 4px 12px rgba(0,0,0,0.2);
            animation: fadeInUp 0.3s ease-out;
        `;
        document.body.appendChild(toast);
        setTimeout(() => toast.remove(), 5000);
    }

    // === החלת ערכה ===

    /**
     * החלת ערכת נושא
     */
    function applyTheme(theme, options = {}) {
        if (!theme) return;
        
        const { source = 'scheduler', force = false } = options;
        const html = document.documentElement;
        const currentTheme = html.getAttribute('data-theme');

        // בדיקת override ידני (רק אם לא force)
        if (!force && source === 'scheduler') {
            const override = getManualOverride();
            if (override) {
                // יש override פעיל - לא משנים
                console.log(`[ThemeScheduler] Manual override active until ${override.expiresAtFormatted}`);
                return;
            }
        }

        // רק אם יש שינוי
        if (currentTheme === theme && !force) return;

        console.log(`[ThemeScheduler] Applying theme: ${theme} (source: ${source})`);

        // עדכון ה-HTML attribute
        html.setAttribute('data-theme', theme);

        // עדכון cookie (לטעינה הבאה)
        try {
            document.cookie = `ui_theme=${theme}; path=/; max-age=31536000; SameSite=Lax`;
        } catch (e) {
            // ignore
        }

        // אירוע לעדכון קומפוננטים אחרים
        window.dispatchEvent(new CustomEvent('themeChanged', {
            detail: { theme, source }
        }));

        // עדכון ה-DarkMode toggle button
        updateToggleButton(theme);
    }

    /**
     * עדכון כפתור toggle
     */
    function updateToggleButton(theme) {
        const toggleBtn = document.getElementById('darkModeToggle');
        const icon = document.getElementById('darkModeIcon');
        if (!toggleBtn || !icon) return;
        
        const icons = {
            'classic': 'fa-sun',
            'dark': 'fa-moon',
            'dim': 'fa-cloud-moon',
            'ocean': 'fa-water',
            'forest': 'fa-tree',
            'nebula': 'fa-star',
        };
        icon.className = 'fas ' + (icons[theme] || 'fa-palette');
    }

    // === מטמון ===

    /**
     * שמירה במטמון מקומי
     */
    function saveToCache(schedule) {
        try {
            const cacheData = {
                schedule: schedule,
                fetchedAt: Date.now(),
            };
            localStorage.setItem(STORAGE_KEY, JSON.stringify(cacheData));
        } catch (e) {
            // ignore
        }
    }

    /**
     * טעינה ממטמון מקומי
     */
    function loadFromCache() {
        try {
            const data = localStorage.getItem(STORAGE_KEY);
            if (!data) return null;
            
            const cached = JSON.parse(data);
            
            // בדיקת תוקף (24 שעות)
            if (cached.fetchedAt && (Date.now() - cached.fetchedAt) > CACHE_MAX_AGE_MS) {
                console.log('[ThemeScheduler] Cache expired, will fetch fresh data');
                return null;
            }
            
            return cached.schedule;
        } catch (e) {
            return null;
        }
    }

    // === תקשורת עם השרת ===

    /**
     * טעינת הגדרות מהשרת
     */
    async function loadSchedule() {
        try {
            const response = await fetch('/api/themes/schedule', {
                method: 'GET',
                credentials: 'same-origin',
            });

            if (!response.ok) {
                console.warn('[ThemeScheduler] Failed to load schedule, using cache');
                return loadFromCache();
            }

            const data = await response.json();
            if (data.ok && data.schedule) {
                currentSchedule = data.schedule;
                saveToCache(data.schedule);
                return data.schedule;
            }
        } catch (e) {
            console.warn('[ThemeScheduler] Network error, using cache:', e.message);
        }

        // Fallback למטמון
        const cached = loadFromCache();
        if (cached) {
            currentSchedule = cached;
        }
        return cached;
    }

    /**
     * שמירת הגדרות לשרת
     */
    async function saveSchedule(schedule) {
        try {
            const response = await fetch('/api/themes/schedule', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'same-origin',
                body: JSON.stringify(schedule),
            });

            const data = await response.json();
            if (data.ok) {
                currentSchedule = data.schedule || schedule;
                saveToCache(currentSchedule);
                
                // ביטול override קודם
                clearManualOverride();

                // עדכון מעקב
                if (currentSchedule.enabled) {
                    startMonitoring();
                } else {
                    stopMonitoring();
                }

                return { success: true, schedule: currentSchedule };
            } else {
                return { success: false, error: data.error, message: data.message };
            }
        } catch (e) {
            console.error('[ThemeScheduler] Save error:', e);
            return { success: false, error: 'network_error' };
        }
    }

    // === ניהול טיימרים ===

    /**
     * הגדרת טיימר לאירוע הבא
     */
    function scheduleNextChange() {
        // ניקוי טיימר קודם
        if (nextChangeTimer) {
            clearTimeout(nextChangeTimer);
            nextChangeTimer = null;
        }

        if (!currentSchedule || !currentSchedule.enabled) return;

        const result = calculateCurrentPeriod(currentSchedule);
        if (!result.nextChangeIn) return;

        console.log(`[ThemeScheduler] Next change in ${Math.round(result.nextChangeIn / 60000)} minutes (at ${result.nextChangeAt})`);

        // טיימר לאירוע הבא
        nextChangeTimer = setTimeout(() => {
            console.log(`[ThemeScheduler] Time to switch!`);
            
            // ביטול override (הגיע זמן המעבר)
            clearManualOverride();
            
            // החלת הערכה החדשה
            const newResult = calculateCurrentPeriod(currentSchedule);
            if (newResult.theme) {
                applyTheme(newResult.theme, { force: true });
            }
            
            // תזמון האירוע הבא
            scheduleNextChange();
            
        }, result.nextChangeIn + 1000); // +1 שנייה לוודא שעברנו את נקודת המעבר
    }

    /**
     * התחלת מעקב
     */
    function startMonitoring() {
        // עצירת טיימרים קודמים
        stopMonitoring();

        if (!currentSchedule || !currentSchedule.enabled) return;

        // החלת הערכה הנוכחית
        const result = calculateCurrentPeriod(currentSchedule);
        if (result.theme) {
            applyTheme(result.theme);
        }

        // תזמון המעבר הבא
        scheduleNextChange();

        // Timer גיבוי (למקרה של drift או חזרה מ-sleep)
        backupTimer = setInterval(() => {
            if (!currentSchedule?.enabled) return;
            
            const override = getManualOverride();
            if (override) {
                // בדיקה אם ה-override פג
                if (override.expiresAt <= Date.now()) {
                    clearManualOverride();
                    const newResult = calculateCurrentPeriod(currentSchedule);
                    if (newResult.theme) {
                        applyTheme(newResult.theme, { force: true });
                    }
                }
                return;
            }
            
            // בדיקת התאמה
            const result = calculateCurrentPeriod(currentSchedule);
            const currentTheme = document.documentElement.getAttribute('data-theme');
            if (result.theme && result.theme !== currentTheme) {
                console.log('[ThemeScheduler] Backup check detected mismatch, fixing...');
                applyTheme(result.theme);
                scheduleNextChange();
            }
        }, BACKUP_CHECK_INTERVAL);
    }

    /**
     * עצירת מעקב
     */
    function stopMonitoring() {
        if (nextChangeTimer) {
            clearTimeout(nextChangeTimer);
            nextChangeTimer = null;
        }
        if (backupTimer) {
            clearInterval(backupTimer);
            backupTimer = null;
        }
    }

    // === אתחול ===

    async function init() {
        console.log('[ThemeScheduler] Initializing...');
        
        // טעינת הגדרות
        await loadSchedule();

        // התחלת מעקב אם מופעל
        if (currentSchedule && currentSchedule.enabled) {
            startMonitoring();
        }
    }

    // הפעלה בטעינת הדף
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    // האזנה לשינויי visibility (חזרה לטאב)
    document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'visible' && currentSchedule?.enabled) {
            // בדיקה אם צריך לעדכן
            const override = getManualOverride();
            if (!override) {
                const result = calculateCurrentPeriod(currentSchedule);
                const currentTheme = document.documentElement.getAttribute('data-theme');
                if (result.theme && result.theme !== currentTheme) {
                    applyTheme(result.theme);
                }
            }
            // רענון טיימר
            scheduleNextChange();
        }
    });

    // === API גלובלי ===

    window.ThemeScheduler = {
        // פעולות בסיסיות
        load: loadSchedule,
        save: saveSchedule,
        
        // מצב נוכחי
        getSchedule: () => currentSchedule,
        getCurrentPeriod: () => calculateCurrentPeriod(currentSchedule),
        isEnabled: () => currentSchedule?.enabled ?? false,
        
        // מעקב
        start: startMonitoring,
        stop: stopMonitoring,
        
        // Override ידני
        setOverride: setManualOverride,
        clearOverride: clearManualOverride,
        getOverride: getManualOverride,
        
        // החלת ערכה (לשימוש חיצוני)
        applyTheme: (theme) => applyTheme(theme, { source: 'manual' }),
    };

})();
```

### 3.2 הוספה ל-`base.html`

הוסף את הקובץ אחרי `dark-mode.js`:

```html
<!-- Theme Scheduler - תזמון ערכות לפי שעות -->
{% if session.user_id %}
<script src="{{ url_for('static', filename='js/theme-scheduler.js') }}?v={{ static_version }}" defer></script>
{% endif %}
```

---

## שלב 4: עדכון ממשק המשתמש

### 4.1 יצירת `theme_schedule.html`

צור קובץ חדש: `webapp/templates/settings/theme_schedule.html`

```html
{% extends "base.html" %}

{% block title %}תזמון ערכות נושא - Code Keeper Bot{% endblock %}

{% block content %}
<h1 class="page-title">
    <i class="fas fa-clock"></i>
    תזמון ערכות נושא אוטומטי
</h1>

<div class="theme-schedule-container">
    <div class="glass-card schedule-card">
        <div class="schedule-header">
            <h2>
                <i class="fas fa-sun"></i>
                <i class="fas fa-moon"></i>
                החלפה אוטומטית יום/לילה
            </h2>
            <p class="text-muted">
                הגדר ערכות נושא שונות לשעות היום והלילה.
                המערכת תחליף ביניהן אוטומטית.
            </p>
        </div>

        <div class="schedule-form">
            <!-- הפעלה/כיבוי -->
            <div class="form-group toggle-group">
                <label class="toggle-label" for="scheduleEnabled">
                    <span class="toggle-text">הפעל תזמון אוטומטי</span>
                    <div class="toggle-switch">
                        <input type="checkbox" id="scheduleEnabled" class="toggle-input">
                        <span class="toggle-slider"></span>
                    </div>
                </label>
            </div>

            <!-- הגדרות (מוצגות רק כשהתזמון מופעל) -->
            <div id="scheduleSettings" class="schedule-settings" style="display: none;">
                
                <!-- ערכת יום -->
                <div class="form-group">
                    <label for="dayTheme">
                        <i class="fas fa-sun" style="color: #f59e0b;"></i>
                        ערכת יום
                    </label>
                    <select id="dayTheme" class="form-control theme-select">
                        <optgroup label="ערכות בהירות">
                            <option value="builtin:classic">קלאסי (בהיר)</option>
                            <option value="builtin:ocean">אוקיינוס</option>
                            <option value="builtin:forest">יער</option>
                            <option value="builtin:rose-pine-dawn">Rose Pine Dawn</option>
                        </optgroup>
                        <optgroup label="ערכות כהות">
                            <option value="builtin:dark">כהה</option>
                            <option value="builtin:dim">מעומעם</option>
                            <option value="builtin:nebula">ערפילית</option>
                        </optgroup>
                        <!-- ערכות מותאמות/שיתופיות יתווספו דינמית -->
                    </select>
                </div>

                <!-- ערכת לילה -->
                <div class="form-group">
                    <label for="nightTheme">
                        <i class="fas fa-moon" style="color: #6366f1;"></i>
                        ערכת לילה
                    </label>
                    <select id="nightTheme" class="form-control theme-select">
                        <optgroup label="ערכות כהות">
                            <option value="builtin:dark">כהה</option>
                            <option value="builtin:dim">מעומעם</option>
                            <option value="builtin:nebula">ערפילית</option>
                            <option value="builtin:high-contrast">ניגודיות גבוהה</option>
                        </optgroup>
                        <optgroup label="ערכות בהירות">
                            <option value="builtin:classic">קלאסי (בהיר)</option>
                            <option value="builtin:ocean">אוקיינוס</option>
                            <option value="builtin:forest">יער</option>
                        </optgroup>
                        <!-- ערכות מותאמות/שיתופיות יתווספו דינמית -->
                    </select>
                </div>

                <!-- טווח שעות יום -->
                <div class="form-group time-range-group">
                    <label>
                        <i class="fas fa-clock"></i>
                        שעות יום
                    </label>
                    <div class="time-range">
                        <div class="time-input-wrapper">
                            <label for="dayStart" class="time-label">מ־</label>
                            <input type="time" id="dayStart" class="form-control time-input" value="07:00">
                        </div>
                        <span class="time-separator">עד</span>
                        <div class="time-input-wrapper">
                            <label for="dayEnd" class="time-label">עד</label>
                            <input type="time" id="dayEnd" class="form-control time-input" value="20:00">
                        </div>
                    </div>
                    <small class="text-muted" id="timeRangeHint">
                        כל השעות מחוץ לטווח זה ייחשבו כלילה
                    </small>
                    <div id="timeRangeError" class="form-error" style="display: none;">
                        <i class="fas fa-exclamation-triangle"></i>
                        <span>שעת ההתחלה חייבת להיות לפני שעת הסיום</span>
                    </div>
                </div>

                <!-- תצוגה מקדימה -->
                <div class="schedule-preview">
                    <div class="preview-item day-preview">
                        <div class="preview-icon">
                            <i class="fas fa-sun"></i>
                        </div>
                        <div class="preview-info">
                            <strong>יום</strong>
                            <span id="dayPreviewTime">07:00 - 20:00</span>
                        </div>
                        <div class="preview-theme" id="dayPreviewTheme">
                            קלאסי
                        </div>
                    </div>
                    <div class="preview-item night-preview">
                        <div class="preview-icon">
                            <i class="fas fa-moon"></i>
                        </div>
                        <div class="preview-info">
                            <strong>לילה</strong>
                            <span id="nightPreviewTime">20:00 - 07:00</span>
                        </div>
                        <div class="preview-theme" id="nightPreviewTheme">
                            כהה
                        </div>
                    </div>
                </div>

                <!-- סטטוס נוכחי -->
                <div class="current-status" id="currentStatus" style="display: none;">
                    <i class="fas fa-info-circle"></i>
                    <span id="statusText">כרגע: ערכת יום (קלאסי)</span>
                    <span id="nextChangeText" class="next-change">שינוי הבא: 20:00</span>
                </div>
            </div>

            <!-- כפתורים -->
            <div class="form-actions">
                <button type="button" id="saveScheduleBtn" class="btn btn-primary">
                    <i class="fas fa-save"></i>
                    שמור הגדרות
                </button>
                <button type="button" id="testScheduleBtn" class="btn btn-secondary" style="display: none;">
                    <i class="fas fa-play"></i>
                    בדוק עכשיו
                </button>
            </div>
        </div>
    </div>

    <!-- מידע נוסף -->
    <div class="glass-card info-card">
        <h3>
            <i class="fas fa-lightbulb"></i>
            איך זה עובד?
        </h3>
        <ul class="info-list">
            <li>
                <i class="fas fa-check"></i>
                בחר ערכת נושא בהירה לשעות היום
            </li>
            <li>
                <i class="fas fa-check"></i>
                בחר ערכת נושא כהה לשעות הלילה
            </li>
            <li>
                <i class="fas fa-check"></i>
                הגדר את טווח השעות לפי ההעדפה שלך
            </li>
            <li>
                <i class="fas fa-check"></i>
                המערכת תחליף אוטומטית בין הערכות
            </li>
        </ul>
        <p class="text-muted small">
            <i class="fas fa-info-circle"></i>
            השעות מבוססות על השעון המקומי של הדפדפן שלך.
        </p>
    </div>
</div>

<style>
.theme-schedule-container {
    display: grid;
    grid-template-columns: 1fr 320px;
    gap: 1.5rem;
    max-width: 1000px;
    margin: 0 auto;
}

@media (max-width: 800px) {
    .theme-schedule-container {
        grid-template-columns: 1fr;
    }
}

.schedule-card {
    padding: 1.5rem;
}

.schedule-header h2 {
    margin: 0 0 0.5rem 0;
    display: flex;
    align-items: center;
    gap: 0.5rem;
}

.schedule-header h2 i {
    font-size: 1.1em;
}

.schedule-header h2 i.fa-sun {
    color: #f59e0b;
}

.schedule-header h2 i.fa-moon {
    color: #6366f1;
}

/* Toggle Switch */
.toggle-group {
    margin: 1.5rem 0;
}

.toggle-label {
    display: flex;
    align-items: center;
    justify-content: space-between;
    cursor: pointer;
    padding: 1rem;
    background: var(--glass);
    border: 1px solid var(--glass-border);
    border-radius: 12px;
    transition: all 0.2s;
}

.toggle-label:hover {
    background: var(--glass-hover);
}

.toggle-text {
    font-weight: 600;
    color: var(--text-primary);
}

.toggle-switch {
    position: relative;
    width: 52px;
    height: 28px;
}

.toggle-input {
    opacity: 0;
    width: 0;
    height: 0;
}

.toggle-slider {
    position: absolute;
    cursor: pointer;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    background: var(--bg-tertiary);
    transition: 0.3s;
    border-radius: 28px;
    border: 1px solid var(--glass-border);
}

.toggle-slider:before {
    position: absolute;
    content: "";
    height: 20px;
    width: 20px;
    left: 3px;
    bottom: 3px;
    background: white;
    transition: 0.3s;
    border-radius: 50%;
    box-shadow: 0 2px 4px rgba(0,0,0,0.2);
}

.toggle-input:checked + .toggle-slider {
    background: var(--primary);
    border-color: var(--primary);
}

.toggle-input:checked + .toggle-slider:before {
    transform: translateX(24px);
}

/* Schedule Settings */
.schedule-settings {
    animation: slideDown 0.3s ease-out;
}

@keyframes slideDown {
    from {
        opacity: 0;
        transform: translateY(-10px);
    }
    to {
        opacity: 1;
        transform: translateY(0);
    }
}

.form-group {
    margin-bottom: 1.25rem;
}

.form-group label {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    margin-bottom: 0.5rem;
    font-weight: 500;
    color: var(--text-primary);
}

.theme-select {
    width: 100%;
    padding: 0.75rem 1rem;
    border-radius: 10px;
    border: 1px solid var(--glass-border);
    background: var(--glass);
    color: var(--text-primary);
    font-size: 1rem;
    cursor: pointer;
}

.theme-select:focus {
    outline: none;
    border-color: var(--primary);
    box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.2);
}

/* Time Range */
.time-range {
    display: flex;
    align-items: center;
    gap: 0.75rem;
}

.time-input-wrapper {
    flex: 1;
}

.time-label {
    display: none;
}

.time-input {
    width: 100%;
    padding: 0.75rem;
    border-radius: 10px;
    border: 1px solid var(--glass-border);
    background: var(--glass);
    color: var(--text-primary);
    font-size: 1rem;
}

.time-input:focus {
    outline: none;
    border-color: var(--primary);
}

.time-separator {
    color: var(--text-muted);
    font-weight: 500;
}

/* Preview */
.schedule-preview {
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
    margin: 1.5rem 0;
    padding: 1rem;
    background: var(--bg-secondary);
    border-radius: 12px;
}

.preview-item {
    display: flex;
    align-items: center;
    gap: 1rem;
    padding: 0.75rem;
    border-radius: 10px;
    background: var(--glass);
}

.day-preview {
    border-left: 3px solid #f59e0b;
}

.night-preview {
    border-left: 3px solid #6366f1;
}

.preview-icon {
    width: 36px;
    height: 36px;
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: 50%;
    background: var(--bg-tertiary);
}

.day-preview .preview-icon {
    color: #f59e0b;
}

.night-preview .preview-icon {
    color: #6366f1;
}

.preview-info {
    flex: 1;
}

.preview-info strong {
    display: block;
    color: var(--text-primary);
}

.preview-info span {
    font-size: 0.85rem;
    color: var(--text-muted);
}

.preview-theme {
    padding: 0.35rem 0.75rem;
    border-radius: 20px;
    background: var(--primary);
    color: white;
    font-size: 0.85rem;
    font-weight: 500;
}

/* Current Status */
.current-status {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    padding: 1rem;
    background: rgba(99, 102, 241, 0.1);
    border: 1px solid rgba(99, 102, 241, 0.3);
    border-radius: 10px;
    color: var(--text-primary);
    margin-top: 1rem;
}

.current-status i {
    color: var(--primary);
}

.next-change {
    margin-right: auto;
    font-size: 0.85rem;
    color: var(--text-muted);
}

/* Actions */
.form-actions {
    display: flex;
    gap: 1rem;
    margin-top: 1.5rem;
}

.form-actions .btn {
    flex: 1;
}

/* Info Card */
.info-card {
    padding: 1.5rem;
    height: fit-content;
}

.info-card h3 {
    margin: 0 0 1rem 0;
    display: flex;
    align-items: center;
    gap: 0.5rem;
}

.info-card h3 i {
    color: #f59e0b;
}

.info-list {
    list-style: none;
    padding: 0;
    margin: 0;
}

.info-list li {
    display: flex;
    align-items: flex-start;
    gap: 0.75rem;
    margin-bottom: 0.75rem;
    color: var(--text-secondary);
}

.info-list li i {
    color: var(--success);
    margin-top: 0.2em;
}
</style>
{% endblock %}

{% block extra_js %}
<script>
document.addEventListener('DOMContentLoaded', async function() {
    const enabledToggle = document.getElementById('scheduleEnabled');
    const settingsDiv = document.getElementById('scheduleSettings');
    const dayThemeSelect = document.getElementById('dayTheme');
    const nightThemeSelect = document.getElementById('nightTheme');
    const dayStartInput = document.getElementById('dayStart');
    const dayEndInput = document.getElementById('dayEnd');
    const timeRangeError = document.getElementById('timeRangeError');
    const timeRangeHint = document.getElementById('timeRangeHint');
    const saveBtn = document.getElementById('saveScheduleBtn');
    const testBtn = document.getElementById('testScheduleBtn');
    const currentStatus = document.getElementById('currentStatus');
    const statusText = document.getElementById('statusText');
    const nextChangeText = document.getElementById('nextChangeText');

    // Theme names mapping
    const themeNames = {
        'builtin:classic': 'קלאסי',
        'builtin:dark': 'כהה',
        'builtin:dim': 'מעומעם',
        'builtin:nebula': 'ערפילית',
        'builtin:ocean': 'אוקיינוס',
        'builtin:forest': 'יער',
        'builtin:rose-pine-dawn': 'Rose Pine Dawn',
        'builtin:high-contrast': 'ניגודיות גבוהה',
    };

    // המרת שעה למספר דקות לצורך השוואה
    function timeToMinutes(timeStr) {
        if (!timeStr) return 0;
        const parts = timeStr.split(':');
        return parseInt(parts[0], 10) * 60 + parseInt(parts[1], 10);
    }

    // וולידציה של טווח שעות
    function validateTimeRange() {
        const startMins = timeToMinutes(dayStartInput.value);
        const endMins = timeToMinutes(dayEndInput.value);
        
        const isValid = startMins < endMins;
        const isTooShort = (endMins - startMins) < 60;
        
        if (!isValid) {
            timeRangeError.style.display = 'flex';
            timeRangeError.querySelector('span').textContent = 
                'שעת ההתחלה חייבת להיות לפני שעת הסיום';
            timeRangeHint.style.display = 'none';
            saveBtn.disabled = true;
            return false;
        }
        
        if (isTooShort) {
            timeRangeError.style.display = 'flex';
            timeRangeError.querySelector('span').textContent = 
                'טווח היום חייב להיות לפחות שעה אחת';
            timeRangeHint.style.display = 'none';
            saveBtn.disabled = true;
            return false;
        }
        
        timeRangeError.style.display = 'none';
        timeRangeHint.style.display = 'block';
        saveBtn.disabled = false;
        return true;
    }

    // טעינת ערכות מותאמות/שיתופיות לתוך ה-select
    async function loadCustomThemes() {
        try {
            // טעינת ערכות מותאמות אישית
            const customResp = await fetch('/api/themes', { credentials: 'same-origin' });
            if (customResp.ok) {
                const customData = await customResp.json();
                if (customData.ok && customData.themes?.length > 0) {
                    addThemesToSelect(customData.themes, 'custom', 'ערכות מותאמות אישית');
                }
            }
        } catch (e) {
            console.warn('Failed to load custom themes:', e);
        }
    }

    // הוספת ערכות ל-select
    function addThemesToSelect(themes, prefix, groupLabel) {
        const optgroup = document.createElement('optgroup');
        optgroup.label = groupLabel;
        
        themes.forEach(theme => {
            const option = document.createElement('option');
            option.value = `${prefix}:${theme.id}`;
            option.textContent = theme.name;
            optgroup.appendChild(option);
            
            // הוספה למיפוי שמות
            themeNames[`${prefix}:${theme.id}`] = theme.name;
        });
        
        dayThemeSelect.appendChild(optgroup.cloneNode(true));
        nightThemeSelect.appendChild(optgroup);
    }

    // טעינת הגדרות קיימות
    async function loadSettings() {
        if (typeof ThemeScheduler !== 'undefined') {
            const schedule = await ThemeScheduler.load();
            if (schedule) {
                enabledToggle.checked = schedule.enabled;
                dayThemeSelect.value = schedule.day_theme || 'builtin:classic';
                nightThemeSelect.value = schedule.night_theme || 'builtin:dark';
                dayStartInput.value = schedule.day_start || '07:00';
                dayEndInput.value = schedule.day_end || '20:00';
                validateTimeRange();
                updateUI();
            }
        }
    }

    // עדכון ממשק
    function updateUI() {
        const enabled = enabledToggle.checked;
        settingsDiv.style.display = enabled ? 'block' : 'none';
        testBtn.style.display = enabled ? 'inline-flex' : 'none';
        
        if (enabled) {
            updatePreview();
            updateCurrentStatus();
        }
    }

    // עדכון תצוגה מקדימה
    function updatePreview() {
        const dayStart = dayStartInput.value || '07:00';
        const dayEnd = dayEndInput.value || '20:00';
        const dayTheme = dayThemeSelect.value;
        const nightTheme = nightThemeSelect.value;

        document.getElementById('dayPreviewTime').textContent = `${dayStart} - ${dayEnd}`;
        document.getElementById('nightPreviewTime').textContent = `${dayEnd} - ${dayStart}`;
        document.getElementById('dayPreviewTheme').textContent = 
            themeNames[dayTheme] || dayTheme.split(':').pop();
        document.getElementById('nightPreviewTheme').textContent = 
            themeNames[nightTheme] || nightTheme.split(':').pop();
    }

    // עדכון סטטוס נוכחי
    function updateCurrentStatus() {
        if (typeof ThemeScheduler !== 'undefined' && ThemeScheduler.isEnabled()) {
            const result = ThemeScheduler.getCurrentPeriod();
            const override = ThemeScheduler.getOverride();
            
            if (result && result.period) {
                currentStatus.style.display = 'flex';
                const periodName = result.period === 'day' ? 'יום' : 'לילה';
                const themeName = themeNames[result.themeId] || result.theme;
                
                if (override) {
                    statusText.innerHTML = `
                        <span style="color: var(--warning);">
                            <i class="fas fa-hand-paper"></i>
                            שינוי ידני פעיל
                        </span>`;
                    nextChangeText.textContent = `יתבטל ב-${override.expiresAtFormatted}`;
                } else {
                    statusText.textContent = `כרגע: ערכת ${periodName} (${themeName})`;
                    nextChangeText.textContent = `שינוי הבא: ${result.nextChangeAt}`;
                }
            } else {
                currentStatus.style.display = 'none';
            }
        } else {
            currentStatus.style.display = 'none';
        }
    }

    // שמירה
    async function saveSettings() {
        // וולידציה לפני שמירה
        if (!validateTimeRange()) {
            showToast('אנא תקן את טווח השעות', 'error');
            return;
        }
        
        const schedule = {
            enabled: enabledToggle.checked,
            day_theme: dayThemeSelect.value,
            night_theme: nightThemeSelect.value,
            day_start: dayStartInput.value,
            day_end: dayEndInput.value,
        };

        saveBtn.disabled = true;
        saveBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> שומר...';

        try {
            if (typeof ThemeScheduler !== 'undefined') {
                const result = await ThemeScheduler.save(schedule);
                if (result.success) {
                    showToast('ההגדרות נשמרו בהצלחה!', 'success');
                    updateCurrentStatus();
                } else {
                    showToast(result.message || result.error || 'שגיאה בשמירה', 'error');
                }
            }
        } catch (e) {
            showToast('שגיאה בשמירה', 'error');
        }

        saveBtn.disabled = false;
        saveBtn.innerHTML = '<i class="fas fa-save"></i> שמור הגדרות';
    }

    // בדיקה עכשיו
    function testNow() {
        if (typeof ThemeScheduler !== 'undefined') {
            // ביטול override אם יש
            ThemeScheduler.clearOverride();
            
            // החלת הערכה לפי התזמון
            const result = ThemeScheduler.getCurrentPeriod();
            if (result.theme) {
                ThemeScheduler.applyTheme(result.theme);
            }
            
            updateCurrentStatus();
            showToast('הערכה עודכנה לפי התזמון הנוכחי', 'success');
        }
    }

    // Toast
    function showToast(message, type = 'info') {
        // הסרת toast קודם
        document.querySelectorAll('.schedule-toast').forEach(t => t.remove());
        
        const toast = document.createElement('div');
        toast.className = `schedule-toast toast-${type}`;
        toast.innerHTML = `
            <i class="fas fa-${type === 'success' ? 'check-circle' : 'exclamation-circle'}"></i> 
            ${message}
        `;
        toast.style.cssText = `
            position: fixed;
            bottom: 20px;
            left: 50%;
            transform: translateX(-50%);
            padding: 0.75rem 1.5rem;
            background: ${type === 'success' ? 'var(--success, #22c55e)' : 'var(--error, #ef4444)'};
            color: white;
            border-radius: 10px;
            z-index: 9999;
            display: flex;
            align-items: center;
            gap: 0.5rem;
            animation: fadeInUp 0.3s ease-out;
        `;
        document.body.appendChild(toast);
        setTimeout(() => toast.remove(), 4000);
    }

    // Event Listeners
    enabledToggle.addEventListener('change', updateUI);
    dayThemeSelect.addEventListener('change', updatePreview);
    nightThemeSelect.addEventListener('change', updatePreview);
    dayStartInput.addEventListener('change', () => {
        validateTimeRange();
        updatePreview();
    });
    dayEndInput.addEventListener('change', () => {
        validateTimeRange();
        updatePreview();
    });
    saveBtn.addEventListener('click', saveSettings);
    testBtn.addEventListener('click', testNow);

    // טעינה ראשונית
    await loadCustomThemes();
    await loadSettings();
    
    // עדכון סטטוס כל 30 שניות
    setInterval(updateCurrentStatus, 30000);
});
</script>

<style>
@keyframes fadeInUp {
    from {
        opacity: 0;
        transform: translateX(-50%) translateY(10px);
    }
    to {
        opacity: 1;
        transform: translateX(-50%) translateY(0);
    }
}

.form-error {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    margin-top: 0.5rem;
    padding: 0.5rem 0.75rem;
    background: rgba(239, 68, 68, 0.1);
    border: 1px solid rgba(239, 68, 68, 0.3);
    border-radius: 8px;
    color: var(--error, #ef4444);
    font-size: 0.85rem;
}

.form-error i {
    flex-shrink: 0;
}
</style>
{% endblock %}
```

### 4.2 הוספת Route ב-`app.py`

```python
@app.route('/settings/theme-schedule')
def theme_schedule_page():
    """דף הגדרות תזמון ערכות נושא."""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return render_template('settings/theme_schedule.html')
```

### 4.3 הוספת קישור בתפריט ההגדרות

עדכן את `settings.html` או את התפריט הראשי:

```html
<a href="/settings/theme-schedule" class="settings-link">
    <i class="fas fa-clock"></i>
    תזמון ערכות נושא
    <span class="badge badge-new">חדש</span>
</a>
```

---

## שלב 5: אינטגרציה עם המערכת הקיימת

### 5.1 עדכון `dark-mode.js`

הוסף תמיכה בתזמון ו-override למודול הקיים:

```javascript
// עדכן את הפונקציה toggleDarkMode() ב-dark-mode.js

function toggleDarkMode() {
    const current = loadPreference();
    let next;
    switch (current) {
        case 'auto': next = 'dark'; break;
        case 'dark': next = 'dim'; break;
        case 'dim': next = 'light'; break;
        case 'light':
        default: next = 'auto'; break;
    }
    
    savePreference(next);
    
    // 🆕 אם יש תזמון פעיל, הגדר override זמני
    if (typeof ThemeScheduler !== 'undefined' && ThemeScheduler.isEnabled()) {
        const themeName = (next === 'auto') 
            ? (getSystemPreference() === 'dark' ? 'dark' : 'classic')
            : (next === 'light' ? 'classic' : next);
        
        ThemeScheduler.setOverride(themeName);
        applyTheme(themeName);
    } else {
        // התנהגות רגילה
        if (loadPreference()) { updateTheme(); }
    }
    
    updateToggleButton(next);
    syncToServer(next);
}

// עדכן את הפונקציה updateTheme()

function updateTheme() {
    // 🆕 בדיקה אם יש תזמון פעיל (ולא override)
    if (typeof ThemeScheduler !== 'undefined' && ThemeScheduler.isEnabled()) {
        const override = ThemeScheduler.getOverride();
        if (!override) {
            // התזמון פעיל ואין override - ה-scheduler מטפל בזה
            return;
        }
        // יש override - נמשיך לטפל כרגיל
    }
    
    const preference = loadPreference();
    if (!preference) {
        return; // אין העדפה שמורה - נכבד את ערך השרת
    }
    
    if (preference === 'auto') {
        applyTheme('auto');
        // ... האזנה לשינויי מערכת ...
    } else {
        const normalized = normalizePreferenceValue(preference);
        applyTheme(normalized || preference);
    }
}
```

### 5.2 עדכון `_inject_globals` ב-`app.py`

הוסף את הגדרות התזמון ל-template context:

```python
def _inject_globals():
    # ... קוד קיים ...
    
    # Theme Schedule
    theme_schedule = None
    try:
        if user_id and user_doc:
            ts = (user_doc.get('ui_prefs') or {}).get('theme_schedule')
            if isinstance(ts, dict) and ts.get('enabled'):
                theme_schedule = ts
    except Exception:
        theme_schedule = None
    
    return {
        # ... שאר המשתנים ...
        'theme_schedule': theme_schedule,
    }
```

### 5.3 הוספת Script ב-`base.html` למניעת FOUC

הוסף ב-`<head>` לפני טעינת CSS:

```html
<script>
    // Theme Schedule - מניעת FOUC
    // הערה: הלוגיקה מניחה ש-day_start < day_end תמיד (אין חציית חצות)
    (function() {
        try {
            // בדיקת override ידני קודם
            var override = localStorage.getItem('theme_manual_override');
            if (override) {
                override = JSON.parse(override);
                if (override && override.expiresAt > Date.now() && override.theme) {
                    document.documentElement.setAttribute('data-theme', override.theme);
                    return;
                }
            }
            
            // טעינת הגדרות תזמון
            var cached = localStorage.getItem('theme_schedule_cache');
            if (!cached) return;
            
            var data = JSON.parse(cached);
            var schedule = data.schedule || data; // תמיכה בפורמט ישן וחדש
            
            if (!schedule || !schedule.enabled) return;
            
            // בדיקת תוקף cache (24 שעות)
            if (data.fetchedAt && (Date.now() - data.fetchedAt) > 86400000) return;
            
            var now = new Date();
            var currentMins = now.getHours() * 60 + now.getMinutes();
            
            function timeToMins(t) {
                if (!t) return 0;
                var p = t.split(':');
                return parseInt(p[0], 10) * 60 + parseInt(p[1], 10);
            }
            
            var dayStart = timeToMins(schedule.day_start || '07:00');
            var dayEnd = timeToMins(schedule.day_end || '20:00');
            
            // לוגיקה פשוטה: יום = בתוך הטווח [dayStart, dayEnd)
            var isDay = currentMins >= dayStart && currentMins < dayEnd;
            
            var themeId = isDay ? schedule.day_theme : schedule.night_theme;
            if (!themeId) return;
            
            // חילוץ שם הערכה מהמזהה המלא
            var theme = themeId.indexOf(':') > -1 
                ? themeId.split(':')[1] 
                : themeId;
            
            // עבור shared/custom, נשתמש במזהה כמו שהוא (ה-CSS יטפל)
            if (themeId.startsWith('shared:') || themeId.startsWith('custom:')) {
                theme = themeId;
            }
            
            if (theme) {
                document.documentElement.setAttribute('data-theme', theme);
            }
        } catch(e) {
            // שקט - לא נרצה לשבור את הדף
        }
    })();
</script>
```

---

## שלב 6: בדיקות

### 6.1 Unit Tests

צור קובץ: `tests/test_theme_schedule.py`

```python
"""בדיקות למערכת תזמון ערכות נושא."""

import pytest
from datetime import datetime
from unittest.mock import patch, MagicMock


class TestTimeValidation:
    """בדיקות וולידציה של שעות."""

    def test_valid_time_format(self):
        from webapp.themes_api import validate_time_format
        
        assert validate_time_format("07:00") is True
        assert validate_time_format("23:59") is True
        assert validate_time_format("00:00") is True
        assert validate_time_format("12:30") is True
        assert validate_time_format("9:00") is True  # חד-ספרתי

    def test_invalid_time_format(self):
        from webapp.themes_api import validate_time_format
        
        assert validate_time_format("25:00") is False
        assert validate_time_format("12:60") is False
        assert validate_time_format("abc") is False
        assert validate_time_format("") is False
        assert validate_time_format(None) is False
        assert validate_time_format("12:00:00") is False  # עם שניות


class TestThemeIdentifierValidation:
    """בדיקות וולידציה של מזהי ערכות."""

    def test_valid_builtin_themes(self):
        from webapp.themes_api import validate_theme_identifier
        
        assert validate_theme_identifier("builtin:classic")[0] is True
        assert validate_theme_identifier("builtin:dark")[0] is True
        assert validate_theme_identifier("builtin:dim")[0] is True
        assert validate_theme_identifier("builtin:nebula")[0] is True

    def test_invalid_builtin_theme(self):
        from webapp.themes_api import validate_theme_identifier
        
        is_valid, error = validate_theme_identifier("builtin:nonexistent")
        assert is_valid is False
        assert error == "unknown_builtin_theme"

    def test_invalid_prefix(self):
        from webapp.themes_api import validate_theme_identifier
        
        is_valid, error = validate_theme_identifier("invalid:theme")
        assert is_valid is False
        assert error == "invalid_theme_prefix"

    def test_shared_theme_format(self):
        from webapp.themes_api import validate_theme_identifier
        
        # בלי DB, מחזיר תקין (לא יכולים לבדוק קיום)
        assert validate_theme_identifier("shared:abc123")[0] is True

    def test_custom_theme_format(self):
        from webapp.themes_api import validate_theme_identifier
        
        # בלי DB, מחזיר תקין
        assert validate_theme_identifier("custom:my-uuid")[0] is True


class TestScheduleValidation:
    """בדיקות וולידציה של תזמון מלא."""

    def test_valid_schedule(self):
        from webapp.themes_api import _validate_theme_schedule
        
        schedule = {
            "enabled": True,
            "day_theme": "builtin:classic",
            "night_theme": "builtin:dark",
            "day_start": "07:00",
            "day_end": "20:00",
        }
        
        is_valid, error = _validate_theme_schedule(schedule)
        assert is_valid is True
        assert error == ""

    def test_day_start_after_day_end_rejected(self):
        """וולידציה: day_start חייב להיות לפני day_end."""
        from webapp.themes_api import _validate_theme_schedule
        
        schedule = {
            "day_start": "20:00",
            "day_end": "07:00",  # לפני day_start!
        }
        
        is_valid, error = _validate_theme_schedule(schedule)
        assert is_valid is False
        assert error == "day_start_must_be_before_day_end"

    def test_day_range_too_short(self):
        """וולידציה: טווח יום מינימלי שעה."""
        from webapp.themes_api import _validate_theme_schedule
        
        schedule = {
            "day_start": "12:00",
            "day_end": "12:30",  # רק 30 דקות
        }
        
        is_valid, error = _validate_theme_schedule(schedule)
        assert is_valid is False
        assert error == "day_range_too_short"

    def test_same_start_and_end_rejected(self):
        """וולידציה: אותה שעה התחלה וסיום."""
        from webapp.themes_api import _validate_theme_schedule
        
        schedule = {
            "day_start": "12:00",
            "day_end": "12:00",
        }
        
        is_valid, error = _validate_theme_schedule(schedule)
        assert is_valid is False
        assert error == "day_start_must_be_before_day_end"


class TestAPIEndpoints:
    """בדיקות API."""

    @pytest.fixture
    def client(self, app):
        return app.test_client()

    def test_get_schedule_unauthorized(self, client):
        """בדיקה שנדרש לוגין."""
        response = client.get('/api/themes/schedule')
        assert response.status_code == 401

    def test_get_schedule_authorized(self, client, logged_in_user):
        """בדיקת קבלת הגדרות."""
        response = client.get('/api/themes/schedule')
        assert response.status_code == 200
        data = response.get_json()
        assert data['ok'] is True
        assert 'schedule' in data
        # בדיקת ערכי ברירת מחדל
        assert data['schedule']['enabled'] is False
        assert data['schedule']['day_theme'] == 'builtin:classic'

    def test_update_schedule_valid(self, client, logged_in_user):
        """בדיקת עדכון הגדרות תקינות."""
        response = client.post('/api/themes/schedule', json={
            "enabled": True,
            "day_theme": "builtin:ocean",
            "night_theme": "builtin:dim",
            "day_start": "08:00",
            "day_end": "19:00",
        })
        assert response.status_code == 200
        data = response.get_json()
        assert data['ok'] is True
        assert data['schedule']['enabled'] is True

    def test_update_schedule_invalid_time_range(self, client, logged_in_user):
        """בדיקת דחיית טווח שעות לא תקין."""
        response = client.post('/api/themes/schedule', json={
            "day_start": "20:00",
            "day_end": "08:00",  # לפני day_start
        })
        assert response.status_code == 400
        data = response.get_json()
        assert data['ok'] is False
        assert "day_start_must_be_before_day_end" in data['error']

    def test_update_schedule_invalid_theme(self, client, logged_in_user):
        """בדיקת דחיית ערכה לא קיימת."""
        response = client.post('/api/themes/schedule', json={
            "day_theme": "builtin:nonexistent",
        })
        assert response.status_code == 400
        data = response.get_json()
        assert data['ok'] is False
        assert "unknown_builtin_theme" in data['error']
```

### 6.2 Integration Tests

```python
"""בדיקות אינטגרציה לתזמון ערכות."""

import pytest
from playwright.sync_api import Page


class TestThemeScheduleUI:
    """בדיקות ממשק משתמש."""

    def test_schedule_page_loads(self, page: Page, logged_in_session):
        """בדיקה שדף ההגדרות נטען."""
        page.goto('/settings/theme-schedule')
        assert page.locator('h1').text_content() == 'תזמון ערכות נושא אוטומטי'

    def test_toggle_enables_settings(self, page: Page, logged_in_session):
        """בדיקה שההפעלה מציגה את ההגדרות."""
        page.goto('/settings/theme-schedule')
        
        settings = page.locator('#scheduleSettings')
        assert settings.is_hidden()
        
        page.locator('#scheduleEnabled').click()
        assert settings.is_visible()

    def test_save_schedule(self, page: Page, logged_in_session):
        """בדיקת שמירת הגדרות."""
        page.goto('/settings/theme-schedule')
        
        page.locator('#scheduleEnabled').click()
        page.locator('#dayTheme').select_option('ocean')
        page.locator('#nightTheme').select_option('dim')
        page.locator('#saveScheduleBtn').click()
        
        # בדיקה שהודעת הצלחה מוצגת
        toast = page.locator('.toast-success')
        assert toast.is_visible()
```

---

## שיקולי UX ונגישות

### 7.1 נגישות (A11y)

```html
<!-- הוסף תכונות נגישות -->
<input 
    type="checkbox" 
    id="scheduleEnabled" 
    class="toggle-input"
    role="switch"
    aria-checked="false"
    aria-label="הפעל תזמון אוטומטי של ערכות נושא">

<select 
    id="dayTheme" 
    class="form-control theme-select"
    aria-label="בחר ערכת נושא לשעות היום">
```

### 7.2 הודעות למשתמש

```javascript
// הודעה כשהתזמון משתנה
window.addEventListener('themeChanged', (e) => {
    if (e.detail.source === 'scheduler') {
        const theme = e.detail.theme;
        const isDay = ['classic', 'ocean', 'forest', 'rose-pine-dawn'].includes(theme);
        
        // הצג הודעה עדינה (optional)
        console.log(`ערכת נושא עודכנה ל${isDay ? 'יום' : 'לילה'}: ${theme}`);
    }
});
```

### 7.3 התאמה למובייל

```css
@media (max-width: 600px) {
    .time-range {
        flex-direction: column;
    }
    
    .time-separator {
        padding: 0.5rem 0;
    }
    
    .schedule-preview {
        padding: 0.75rem;
    }
    
    .preview-item {
        flex-wrap: wrap;
    }
    
    .preview-theme {
        width: 100%;
        text-align: center;
        margin-top: 0.5rem;
    }
}
```

---

## סיכום

### קבצים שצריך ליצור/לערוך:

| קובץ | פעולה | תיאור |
|------|-------|-------|
| `webapp/themes_api.py` | עריכה | הוספת API endpoints |
| `webapp/static/js/theme-scheduler.js` | יצירה | לוגיקה צד לקוח |
| `webapp/templates/settings/theme_schedule.html` | יצירה | ממשק הגדרות |
| `webapp/templates/base.html` | עריכה | Script למניעת FOUC + טעינת JS |
| `webapp/app.py` | עריכה | Route + inject globals |
| `webapp/static/js/dark-mode.js` | עריכה | אינטגרציה עם התזמון |
| `tests/test_theme_schedule.py` | יצירה | בדיקות |

### תרשים זרימה מסכם:

```
User enables schedule → Settings saved to DB
                              ↓
Page loads → JS checks schedule → Calculates current period
                              ↓
                   Applies correct theme
                              ↓
Timer runs every minute → Checks if period changed
                              ↓
              If changed → Applies new theme
```

### תכונות עתידיות אפשריות:

1. **תזמון מבוסס מיקום**: שימוש ב-Geolocation API לחישוב זריחה/שקיעה
2. **ערכות לפי יום בשבוע**: ערכות שונות לסופ"ש
3. **תזמון מתקדם**: יותר משני פרקי זמן (בוקר/צהריים/ערב/לילה)
4. **סנכרון עם מערכת ההפעלה**: שימוש ב-`prefers-color-scheme-schedule` (עתידי)

---

## Changelog

### v1.1 (ינואר 2026)
- **תיקון**: הלקוח הוא מקור האמת לזמן (לא השרת)
- **תיקון**: חסימת טווח יום שחוצה חצות בוולידציה
- **שיפור**: טיימר חכם (`setTimeout`) במקום polling
- **שיפור**: תמיכה ב-override ידני זמני
- **שיפור**: מזהה ערכה מלא (builtin:/shared:/custom:)
- **שיפור**: cache עם last_fetched_at
- **שיפור**: הודעות שגיאה בעברית

### v1.0 (ינואר 2026)
- מימוש ראשוני

---

**נוצר על ידי**: Background Agent  
**תאריך**: ינואר 2026  
**גרסה**: 1.1
