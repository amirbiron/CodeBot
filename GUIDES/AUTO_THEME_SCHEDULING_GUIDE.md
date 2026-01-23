# מדריך מימוש - תחלופת ערכות נושא אוטומטית לפי שעות ביממה

**תאריך**: ינואר 2026  
**גרסה**: 1.0  
**סטטוס**: מדריך מימוש

---

## 📋 תוכן עניינים

1. [סקירה כללית](#סקירה-כללית)
2. [ארכיטקטורה](#ארכיטקטורה)
3. [שלב 1: עדכון מבנה הנתונים](#שלב-1-עדכון-מבנה-הנתונים)
4. [שלב 2: יצירת API Backend](#שלב-2-יצירת-api-backend)
5. [שלב 3: מימוש הלוגיקה בצד הלקוח](#שלב-3-מימוש-הלוגיקה-בצד-הלקוח)
6. [שלב 4: עדכון ממשק המשתמש](#שלב-4-עדכון-ממשק-המשתמש)
7. [שלב 5: אינטגרציה עם המערכת הקיימת](#שלב-5-אינטגרציה-עם-המערכת-הקיימת)
8. [שלב 6: בדיקות](#שלב-6-בדיקות)
9. [שיקולי UX ונגישות](#שיקולי-ux-ונגישות)
10. [סיכום](#סיכום)

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
      "day_theme": "classic",     // ערכת יום
      "night_theme": "dark",      // ערכת לילה
      "day_start": "07:00",       // שעת התחלת יום (HH:MM)
      "day_end": "20:00"          // שעת סיום יום (HH:MM)
    }
  }
}
```

### 1.2 ערכי ברירת מחדל

```python
# services/constants.py או webapp/themes_api.py

DEFAULT_THEME_SCHEDULE = {
    "enabled": False,
    "day_theme": "classic",
    "night_theme": "dark",
    "day_start": "07:00",
    "day_end": "20:00",
}

# ערכות נושא מותרות (כולל shared וcustom)
ALLOWED_SCHEDULE_THEMES = {
    "classic", "dark", "dim", "nebula", "ocean", 
    "forest", "rose-pine-dawn", "high-contrast", "custom"
}
```

### 1.3 וולידציה

```python
import re
from datetime import datetime

def validate_time_format(time_str: str) -> bool:
    """בודק שפורמט השעה תקין (HH:MM)."""
    if not time_str or not isinstance(time_str, str):
        return False
    pattern = r"^([01]?[0-9]|2[0-3]):([0-5][0-9])$"
    return bool(re.match(pattern, time_str.strip()))

def validate_theme_schedule(schedule: dict) -> tuple[bool, str]:
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
            theme = schedule[key]
            if not isinstance(theme, str):
                return False, f"invalid_{key}"
            # אפשר גם ערכות shared:xxx או custom
            if not (theme in ALLOWED_SCHEDULE_THEMES or 
                    theme.startswith("shared:") or
                    theme == "custom"):
                return False, f"invalid_{key}"
    
    # בדיקת שעות
    for key in ("day_start", "day_end"):
        if key in schedule:
            if not validate_time_format(schedule[key]):
                return False, f"invalid_{key}_format"
    
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
        "day_theme": "classic",
        "night_theme": "dark",
        "day_start": "07:00",
        "day_end": "20:00"
    }
    
    Response:
    {
        "ok": true,
        "message": "הגדרות התזמון נשמרו",
        "schedule": { ... }
    }
    """
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    data = request.get_json(silent=True) or {}

    # וולידציה
    is_valid, error_msg = _validate_theme_schedule(data)
    if not is_valid:
        return jsonify({"ok": False, "error": error_msg}), 400

    try:
        db_ref = get_db()
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

        # שמירה
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

        # אם התזמון מופעל, עדכן גם את הערכה הנוכחית
        if new_schedule.get("enabled"):
            current_theme = _calculate_current_scheduled_theme(new_schedule)
            if current_theme:
                db_ref.users.update_one(
                    {"user_id": int(user_id)},
                    {"$set": {"ui_prefs.theme": current_theme}},
                )

        return jsonify({
            "ok": True,
            "message": "הגדרות התזמון נשמרו",
            "schedule": new_schedule,
        })

    except Exception as e:
        logger.exception("update_theme_schedule failed: %s", e)
        return jsonify({"ok": False, "error": "database_error"}), 500


@themes_bp.route("/schedule/current", methods=["GET"])
@require_auth
def get_current_scheduled_theme():
    """
    קבלת הערכה הנוכחית לפי התזמון (ללא שינוי ב-DB).
    שימושי ללוגיקה צד לקוח.
    
    Response:
    {
        "ok": true,
        "is_scheduled": true,
        "current_theme": "dark",
        "period": "night",
        "next_change_at": "07:00"
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

        schedule = (user_doc.get("ui_prefs") or {}).get("theme_schedule") or {}

        if not schedule.get("enabled"):
            return jsonify({
                "ok": True,
                "is_scheduled": False,
                "current_theme": None,
                "period": None,
                "next_change_at": None,
            })

        current_theme, period, next_change = _calculate_scheduled_theme_details(schedule)

        return jsonify({
            "ok": True,
            "is_scheduled": True,
            "current_theme": current_theme,
            "period": period,
            "next_change_at": next_change,
        })

    except Exception as e:
        logger.exception("get_current_scheduled_theme failed: %s", e)
        return jsonify({"ok": False, "error": "database_error"}), 500


def _calculate_current_scheduled_theme(schedule: dict) -> Optional[str]:
    """מחשב את הערכה הנוכחית לפי תזמון ושעה נוכחית."""
    if not schedule or not schedule.get("enabled"):
        return None

    try:
        from datetime import datetime

        now = datetime.now()
        current_time = now.strftime("%H:%M")

        day_start = schedule.get("day_start", "07:00")
        day_end = schedule.get("day_end", "20:00")

        # בדיקה אם אנחנו בטווח היום
        if day_start <= day_end:
            # טווח רגיל (למשל 07:00-20:00)
            is_day = day_start <= current_time < day_end
        else:
            # טווח עובר חצות (למשל 20:00-07:00 = לילה)
            is_day = current_time >= day_start or current_time < day_end

        if is_day:
            return schedule.get("day_theme", "classic")
        else:
            return schedule.get("night_theme", "dark")

    except Exception:
        return None


def _calculate_scheduled_theme_details(schedule: dict) -> tuple[str, str, str]:
    """
    מחשב פרטים מלאים על התזמון הנוכחי.
    
    Returns:
        (current_theme, period, next_change_time)
    """
    from datetime import datetime

    now = datetime.now()
    current_time = now.strftime("%H:%M")

    day_start = schedule.get("day_start", "07:00")
    day_end = schedule.get("day_end", "20:00")
    day_theme = schedule.get("day_theme", "classic")
    night_theme = schedule.get("night_theme", "dark")

    if day_start <= day_end:
        is_day = day_start <= current_time < day_end
        next_change = day_end if is_day else day_start
    else:
        is_day = current_time >= day_start or current_time < day_end
        next_change = day_end if is_day else day_start

    if is_day:
        return day_theme, "day", next_change
    else:
        return night_theme, "night", next_change
```

---

## שלב 3: מימוש הלוגיקה בצד הלקוח

### 3.1 יצירת `theme-scheduler.js`

צור קובץ חדש: `webapp/static/js/theme-scheduler.js`

```javascript
/**
 * Theme Scheduler - תזמון אוטומטי של ערכות נושא לפי שעות
 * 
 * הפיצ'ר מאפשר למשתמש להגדיר ערכת יום וערכת לילה,
 * והמערכת מחליפה ביניהן אוטומטית לפי השעות שהוגדרו.
 */

(function() {
    'use strict';

    const STORAGE_KEY = 'theme_schedule_cache';
    const CHECK_INTERVAL = 60000; // בדיקה כל דקה
    let checkTimer = null;
    let currentSchedule = null;

    /**
     * טעינת הגדרות תזמון מהשרת
     */
    async function loadSchedule() {
        try {
            const response = await fetch('/api/themes/schedule', {
                method: 'GET',
                credentials: 'same-origin',
            });

            if (!response.ok) {
                console.warn('Failed to load theme schedule');
                return null;
            }

            const data = await response.json();
            if (data.ok && data.schedule) {
                currentSchedule = data.schedule;
                // שמירה במטמון מקומי
                try {
                    localStorage.setItem(STORAGE_KEY, JSON.stringify(data.schedule));
                } catch (e) {
                    // ignore localStorage errors
                }
                return data.schedule;
            }
        } catch (e) {
            console.warn('Error loading theme schedule:', e);
        }

        // ניסיון לטעון ממטמון מקומי
        try {
            const cached = localStorage.getItem(STORAGE_KEY);
            if (cached) {
                currentSchedule = JSON.parse(cached);
                return currentSchedule;
            }
        } catch (e) {
            // ignore
        }

        return null;
    }

    /**
     * המרת מחרוזת שעה למספר דקות מתחילת היום
     * @param {string} timeStr - שעה בפורמט "HH:MM"
     * @returns {number} - מספר דקות מחצות
     */
    function timeToMinutes(timeStr) {
        if (!timeStr || typeof timeStr !== 'string') return 0;
        const parts = timeStr.split(':');
        const hours = parseInt(parts[0], 10) || 0;
        const minutes = parseInt(parts[1], 10) || 0;
        return hours * 60 + minutes;
    }

    /**
     * קבלת השעה הנוכחית כמספר דקות
     * @returns {number}
     */
    function getCurrentMinutes() {
        const now = new Date();
        return now.getHours() * 60 + now.getMinutes();
    }

    /**
     * חישוב אם אנחנו בתקופת יום או לילה
     * @param {Object} schedule - הגדרות התזמון
     * @returns {Object} - { period: 'day'|'night', theme: string, nextChangeIn: number }
     */
    function calculateCurrentPeriod(schedule) {
        if (!schedule || !schedule.enabled) {
            return { period: null, theme: null, nextChangeIn: null };
        }

        const currentMins = getCurrentMinutes();
        const dayStart = timeToMinutes(schedule.day_start || '07:00');
        const dayEnd = timeToMinutes(schedule.day_end || '20:00');
        const dayTheme = schedule.day_theme || 'classic';
        const nightTheme = schedule.night_theme || 'dark';

        let isDay;
        let nextChangeAt;

        if (dayStart <= dayEnd) {
            // טווח רגיל (למשל 07:00-20:00)
            isDay = currentMins >= dayStart && currentMins < dayEnd;
            nextChangeAt = isDay ? dayEnd : dayStart;
        } else {
            // טווח עובר חצות (למשל 22:00-06:00 = לילה)
            isDay = currentMins >= dayStart || currentMins < dayEnd;
            nextChangeAt = isDay ? dayEnd : dayStart;
        }

        // חישוב זמן עד השינוי הבא (בדקות)
        let nextChangeIn;
        if (nextChangeAt > currentMins) {
            nextChangeIn = nextChangeAt - currentMins;
        } else {
            // השינוי הבא מחר
            nextChangeIn = (24 * 60 - currentMins) + nextChangeAt;
        }

        return {
            period: isDay ? 'day' : 'night',
            theme: isDay ? dayTheme : nightTheme,
            nextChangeIn: nextChangeIn, // בדקות
            nextChangeAt: formatMinutesToTime(nextChangeAt),
        };
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
     * החלת ערכת נושא
     * @param {string} theme - שם הערכה
     */
    function applyTheme(theme) {
        if (!theme) return;

        const html = document.documentElement;
        const currentTheme = html.getAttribute('data-theme');

        // רק אם יש שינוי
        if (currentTheme === theme) return;

        console.log(`[ThemeScheduler] Switching to ${theme} theme`);

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
            detail: { theme, source: 'scheduler' }
        }));

        // עדכון ה-DarkMode module אם קיים
        if (window.DarkMode && typeof window.DarkMode.set === 'function') {
            // לא נקרא ל-set כדי למנוע לולאה אינסופית
            // רק נעדכן את ה-toggle button
            const toggleBtn = document.getElementById('darkModeToggle');
            const icon = document.getElementById('darkModeIcon');
            if (toggleBtn && icon) {
                const icons = {
                    'classic': 'fa-sun',
                    'dark': 'fa-moon',
                    'dim': 'fa-cloud-moon',
                };
                icon.className = 'fas ' + (icons[theme] || 'fa-palette');
            }
        }
    }

    /**
     * בדיקה ועדכון הערכה לפי התזמון
     */
    async function checkAndApply() {
        // טעינה ראשונית אם צריך
        if (!currentSchedule) {
            await loadSchedule();
        }

        if (!currentSchedule || !currentSchedule.enabled) {
            return;
        }

        const result = calculateCurrentPeriod(currentSchedule);
        if (result.theme) {
            applyTheme(result.theme);
        }

        // לוג לדיבוג
        if (result.nextChangeAt) {
            console.log(`[ThemeScheduler] Current: ${result.period}, Next change at: ${result.nextChangeAt}`);
        }
    }

    /**
     * התחלת מעקב אוטומטי
     */
    function startMonitoring() {
        // עצירת טיימר קיים
        if (checkTimer) {
            clearInterval(checkTimer);
        }

        // בדיקה ראשונית
        checkAndApply();

        // בדיקה תקופתית
        checkTimer = setInterval(checkAndApply, CHECK_INTERVAL);
    }

    /**
     * עצירת מעקב
     */
    function stopMonitoring() {
        if (checkTimer) {
            clearInterval(checkTimer);
            checkTimer = null;
        }
    }

    /**
     * עדכון הגדרות תזמון לשרת
     * @param {Object} schedule - הגדרות חדשות
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
                try {
                    localStorage.setItem(STORAGE_KEY, JSON.stringify(currentSchedule));
                } catch (e) {
                    // ignore
                }

                // הפעלה/כיבוי מעקב לפי הצורך
                if (currentSchedule.enabled) {
                    startMonitoring();
                } else {
                    stopMonitoring();
                }

                return { success: true, schedule: currentSchedule };
            } else {
                return { success: false, error: data.error };
            }
        } catch (e) {
            console.error('Error saving theme schedule:', e);
            return { success: false, error: 'network_error' };
        }
    }

    /**
     * אתחול
     */
    async function init() {
        // טעינת הגדרות
        await loadSchedule();

        // התחלת מעקב אם התזמון מופעל
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

    // האזנה לשינויי visibility (כשהמשתמש חוזר לטאב)
    document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'visible' && currentSchedule?.enabled) {
            checkAndApply();
        }
    });

    // חשיפת API גלובלי
    window.ThemeScheduler = {
        load: loadSchedule,
        save: saveSchedule,
        check: checkAndApply,
        getCurrentPeriod: () => calculateCurrentPeriod(currentSchedule),
        getSchedule: () => currentSchedule,
        start: startMonitoring,
        stop: stopMonitoring,
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
                        <option value="classic">קלאסי (בהיר)</option>
                        <option value="ocean">אוקיינוס</option>
                        <option value="forest">יער</option>
                        <option value="rose-pine-dawn">Rose Pine Dawn</option>
                    </select>
                </div>

                <!-- ערכת לילה -->
                <div class="form-group">
                    <label for="nightTheme">
                        <i class="fas fa-moon" style="color: #6366f1;"></i>
                        ערכת לילה
                    </label>
                    <select id="nightTheme" class="form-control theme-select">
                        <option value="dark">כהה</option>
                        <option value="dim">מעומעם</option>
                        <option value="nebula">ערפילית</option>
                        <option value="high-contrast">ניגודיות גבוהה</option>
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
                    <small class="text-muted">
                        כל השעות מחוץ לטווח זה ייחשבו כלילה
                    </small>
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
    const saveBtn = document.getElementById('saveScheduleBtn');
    const testBtn = document.getElementById('testScheduleBtn');
    const currentStatus = document.getElementById('currentStatus');
    const statusText = document.getElementById('statusText');
    const nextChangeText = document.getElementById('nextChangeText');

    // Theme names mapping
    const themeNames = {
        'classic': 'קלאסי',
        'dark': 'כהה',
        'dim': 'מעומעם',
        'nebula': 'ערפילית',
        'ocean': 'אוקיינוס',
        'forest': 'יער',
        'rose-pine-dawn': 'Rose Pine Dawn',
        'high-contrast': 'ניגודיות גבוהה',
    };

    // טעינת הגדרות קיימות
    async function loadSettings() {
        if (typeof ThemeScheduler !== 'undefined') {
            const schedule = await ThemeScheduler.load();
            if (schedule) {
                enabledToggle.checked = schedule.enabled;
                dayThemeSelect.value = schedule.day_theme || 'classic';
                nightThemeSelect.value = schedule.night_theme || 'dark';
                dayStartInput.value = schedule.day_start || '07:00';
                dayEndInput.value = schedule.day_end || '20:00';
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
        document.getElementById('dayPreviewTheme').textContent = themeNames[dayTheme] || dayTheme;
        document.getElementById('nightPreviewTheme').textContent = themeNames[nightTheme] || nightTheme;
    }

    // עדכון סטטוס נוכחי
    function updateCurrentStatus() {
        if (typeof ThemeScheduler !== 'undefined') {
            const result = ThemeScheduler.getCurrentPeriod();
            if (result && result.period) {
                currentStatus.style.display = 'flex';
                const periodName = result.period === 'day' ? 'יום' : 'לילה';
                const themeName = themeNames[result.theme] || result.theme;
                statusText.textContent = `כרגע: ערכת ${periodName} (${themeName})`;
                nextChangeText.textContent = `שינוי הבא: ${result.nextChangeAt}`;
            } else {
                currentStatus.style.display = 'none';
            }
        }
    }

    // שמירה
    async function saveSettings() {
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
                    showToast('שגיאה בשמירה: ' + (result.error || 'אנא נסה שוב'), 'error');
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
            ThemeScheduler.check();
            updateCurrentStatus();
            showToast('הערכה עודכנה לפי התזמון הנוכחי', 'success');
        }
    }

    // Toast
    function showToast(message, type = 'info') {
        const toast = document.createElement('div');
        toast.className = `toast toast-${type}`;
        toast.innerHTML = `<i class="fas fa-${type === 'success' ? 'check' : 'exclamation-circle'}"></i> ${message}`;
        toast.style.cssText = `
            position: fixed;
            bottom: 20px;
            left: 50%;
            transform: translateX(-50%);
            padding: 0.75rem 1.5rem;
            background: ${type === 'success' ? 'var(--success)' : 'var(--error)'};
            color: white;
            border-radius: 10px;
            z-index: 9999;
            animation: fadeInUp 0.3s ease-out;
        `;
        document.body.appendChild(toast);
        setTimeout(() => toast.remove(), 3000);
    }

    // Event Listeners
    enabledToggle.addEventListener('change', updateUI);
    dayThemeSelect.addEventListener('change', updatePreview);
    nightThemeSelect.addEventListener('change', updatePreview);
    dayStartInput.addEventListener('change', updatePreview);
    dayEndInput.addEventListener('change', updatePreview);
    saveBtn.addEventListener('click', saveSettings);
    testBtn.addEventListener('click', testNow);

    // טעינה ראשונית
    await loadSettings();
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

הוסף תמיכה בתזמון למודול הקיים:

```javascript
// הוסף בתוך הפונקציה updateTheme() ב-dark-mode.js

function updateTheme() {
    // בדיקה אם יש תזמון פעיל
    if (typeof ThemeScheduler !== 'undefined') {
        const schedule = ThemeScheduler.getSchedule();
        if (schedule && schedule.enabled) {
            // התזמון פעיל - לא נדרוס את הבחירה שלו
            return;
        }
    }
    
    // ... שאר הקוד הקיים ...
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
    (function() {
        try {
            var schedule = localStorage.getItem('theme_schedule_cache');
            if (schedule) {
                schedule = JSON.parse(schedule);
                if (schedule && schedule.enabled) {
                    var now = new Date();
                    var currentMins = now.getHours() * 60 + now.getMinutes();
                    
                    function timeTomins(t) {
                        var p = t.split(':');
                        return parseInt(p[0],10)*60 + parseInt(p[1],10);
                    }
                    
                    var dayStart = timeTomins(schedule.day_start || '07:00');
                    var dayEnd = timeTomins(schedule.day_end || '20:00');
                    var isDay = (dayStart <= dayEnd) 
                        ? (currentMins >= dayStart && currentMins < dayEnd)
                        : (currentMins >= dayStart || currentMins < dayEnd);
                    
                    var theme = isDay ? schedule.day_theme : schedule.night_theme;
                    if (theme) {
                        document.documentElement.setAttribute('data-theme', theme);
                    }
                }
            }
        } catch(e) {}
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


class TestThemeScheduleValidation:
    """בדיקות וולידציה."""

    def test_valid_time_format(self):
        from webapp.themes_api import _validate_time_format
        
        assert _validate_time_format("07:00") is True
        assert _validate_time_format("23:59") is True
        assert _validate_time_format("00:00") is True
        assert _validate_time_format("12:30") is True

    def test_invalid_time_format(self):
        from webapp.themes_api import _validate_time_format
        
        assert _validate_time_format("25:00") is False
        assert _validate_time_format("12:60") is False
        assert _validate_time_format("abc") is False
        assert _validate_time_format("") is False
        assert _validate_time_format(None) is False

    def test_valid_schedule(self):
        from webapp.themes_api import _validate_theme_schedule
        
        schedule = {
            "enabled": True,
            "day_theme": "classic",
            "night_theme": "dark",
            "day_start": "07:00",
            "day_end": "20:00",
        }
        
        is_valid, error = _validate_theme_schedule(schedule)
        assert is_valid is True
        assert error == ""

    def test_invalid_theme(self):
        from webapp.themes_api import _validate_theme_schedule
        
        schedule = {
            "day_theme": "invalid_theme",
        }
        
        is_valid, error = _validate_theme_schedule(schedule)
        assert is_valid is False
        assert "invalid_day_theme" in error


class TestThemeCalculation:
    """בדיקות חישוב ערכה נוכחית."""

    def test_daytime_normal_range(self):
        """בדיקה בטווח רגיל (יום בשעות בוקר)."""
        from webapp.themes_api import _calculate_current_scheduled_theme
        
        schedule = {
            "enabled": True,
            "day_theme": "classic",
            "night_theme": "dark",
            "day_start": "07:00",
            "day_end": "20:00",
        }
        
        # Mock datetime לשעה 12:00
        with patch('webapp.themes_api.datetime') as mock_dt:
            mock_now = MagicMock()
            mock_now.strftime.return_value = "12:00"
            mock_dt.now.return_value = mock_now
            
            result = _calculate_current_scheduled_theme(schedule)
            assert result == "classic"

    def test_nighttime_normal_range(self):
        """בדיקה בטווח רגיל (לילה)."""
        from webapp.themes_api import _calculate_current_scheduled_theme
        
        schedule = {
            "enabled": True,
            "day_theme": "classic",
            "night_theme": "dark",
            "day_start": "07:00",
            "day_end": "20:00",
        }
        
        with patch('webapp.themes_api.datetime') as mock_dt:
            mock_now = MagicMock()
            mock_now.strftime.return_value = "22:00"
            mock_dt.now.return_value = mock_now
            
            result = _calculate_current_scheduled_theme(schedule)
            assert result == "dark"

    def test_disabled_schedule(self):
        """בדיקה כשהתזמון מכובה."""
        from webapp.themes_api import _calculate_current_scheduled_theme
        
        schedule = {
            "enabled": False,
            "day_theme": "classic",
            "night_theme": "dark",
        }
        
        result = _calculate_current_scheduled_theme(schedule)
        assert result is None


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

    def test_update_schedule(self, client, logged_in_user):
        """בדיקת עדכון הגדרות."""
        response = client.post('/api/themes/schedule', json={
            "enabled": True,
            "day_theme": "classic",
            "night_theme": "dark",
            "day_start": "08:00",
            "day_end": "19:00",
        })
        assert response.status_code == 200
        data = response.get_json()
        assert data['ok'] is True
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

**נוצר על ידי**: Background Agent  
**תאריך**: ינואר 2026  
**גרסה**: 1.0
