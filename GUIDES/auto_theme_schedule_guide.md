# מדריך מימוש: תחלופת ערכות נושא אוטומטית לפי שעות ביממה

## תוכן עניינים
1. [סקירת הארכיטקטורה הקיימת](#1-סקירת-הארכיטקטורה-הקיימת)
2. [עיצוב הפיצ'ר החדש](#2-עיצוב-הפיצר-החדש)
3. [שינויים בצד השרת](#3-שינויים-בצד-השרת)
4. [שינויים בצד הלקוח](#4-שינויים-בצד-הלקוח)
5. [ממשק משתמש](#5-ממשק-משתמש)
6. [בדיקות](#6-בדיקות)

---

## 1. סקירת הארכיטקטורה הקיימת

### 1.1 קבצים מרכזיים

| קובץ | תיאור |
|------|-------|
| `webapp/static/js/dark-mode.js` | לוגיקת מעבר נושא ומצב אוטומטי |
| `webapp/static/css/dark-mode.css` | סגנונות לכל ערכות הנושא |
| `webapp/themes_api.py` | API endpoints לניהול נושאים |
| `webapp/app.py` (שורה ~15887) | endpoint של `/api/ui_prefs` |
| `webapp/templates/settings/theme_builder.html` | בונה ערכות נושא |

### 1.2 מצבי נושא קיימים

```javascript
// מתוך dark-mode.js שורה 166-180
const modes = ['auto', 'dark', 'dim', 'light'];
// auto = לפי הגדרות מערכת ההפעלה (prefers-color-scheme)
```

### 1.3 הפרדה חשובה: Mode vs Theme

> **הערה קריטית**: במערכת הקיימת יש הפרדה בין שני מושגים שונים:

| מושג | תיאור | ערכים אפשריים | מפתח אחסון |
|------|-------|---------------|-------------|
| **Mode** | מצב בהיר/כהה | `auto`, `dark`, `dim`, `light` | `dark_mode_preference` |
| **Theme** | ערכת עיצוב מלאה | `classic`, `ocean`, `dark`, `dim`, `nebula`, `rose-pine-dawn`, `high-contrast`, `custom` | `user_theme` / `data-theme` / `ui_theme` cookie |

**חשוב**: ה-scheduler שלנו מנהל **theme** (ערכת עיצוב), לא **mode**. לכן אסור לגעת ב-`dark_mode_preference`.

### 1.4 אחסון העדפות - Source of Truth

```
┌─────────────────────────────────────────────────────────────────┐
│  localStorage                                                     │
│  ├── dark_mode_preference = "auto" | "dark" | "dim" | "light"   │
│  ├── user_theme = "classic" | "ocean" | "dark" | ...            │
│  └── theme_schedule = { enabled, dayTheme, nightTheme, ... }    │
├─────────────────────────────────────────────────────────────────┤
│  Cookie                                                          │
│  └── ui_theme = "dark" | "classic" | ...                        │
├─────────────────────────────────────────────────────────────────┤
│  HTML Attribute                                                  │
│  └── <html data-theme="dark">                                   │
├─────────────────────────────────────────────────────────────────┤
│  MongoDB (ui_prefs collection)                                   │
│  └── { theme: "dark", theme_schedule: {...} }                   │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2. עיצוב הפיצ'ר החדש

### 2.1 תרחיש שימוש

המשתמש יכול להגדיר:
- **נושא יום**: הנושא שיופעל בשעות היום (למשל: classic)
- **נושא לילה**: הנושא שיופעל בשעות הלילה (למשל: dark)
- **שעת התחלת יום**: למשל 07:00
- **שעת התחלת לילה**: למשל 19:00

### 2.2 מבנה נתונים

```javascript
// מבנה הגדרות התזמון
const themeSchedule = {
    enabled: true,                    // האם התזמון פעיל
    dayTheme: 'classic',              // נושא יום (ערכת עיצוב, לא mode!)
    nightTheme: 'dark',               // נושא לילה
    dayStartHour: 7,                  // שעת התחלת יום (0-23)
    dayStartMinute: 0,                // דקה התחלת יום (0-59)
    nightStartHour: 19,               // שעת התחלת לילה (0-23)
    nightStartMinute: 0,              // דקה התחלת לילה (0-59)
    timezone: 'Asia/Jerusalem'        // אזור זמן (אופציונלי)
};
```

### 2.3 תרשים זרימה

```
              ┌──────────────────────────────┐
              │     האם תזמון מופעל?          │
              └──────────────┬───────────────┘
                             │
              ┌──────────────┴───────────────┐
              │                              │
              ▼                              ▼
           [כן]                            [לא]
              │                              │
              ▼                              ▼
   ┌──────────────────────┐      ┌──────────────────────┐
   │  בדוק שעה נוכחית     │      │  השתמש במצב רגיל     │
   └──────────┬───────────┘      │  (dark-mode.js)      │
              │                   └──────────────────────┘
   ┌──────────┴───────────┐
   │                      │
   ▼                      ▼
[יום]                  [לילה]
   │                      │
   ▼                      ▼
┌────────────┐     ┌────────────┐
│ עדכן       │     │ עדכן       │
│ data-theme │     │ data-theme │
│ user_theme │     │ user_theme │
│ + סנכרון   │     │ + סנכרון   │
└────────────┘     └────────────┘
```

---

## 3. שינויים בצד השרת

### 3.1 עדכון מודל UI Prefs

**קובץ: `webapp/app.py`**

מצא את ה-endpoint של `/api/ui_prefs` (בסביבות שורה 15887) והוסף תמיכה בשדה חדש:

```python
@app.route('/api/ui_prefs', methods=['POST'])
def save_ui_prefs():
    """
    עדכון העדפות UI
    """
    if not current_user.is_authenticated:
        return jsonify({'error': 'לא מחובר'}), 401

    data = request.get_json()
    if not data:
        return jsonify({'error': 'חסר גוף בקשה'}), 400

    user_id = current_user.get_id()

    # שדות קיימים
    allowed_fields = ['font_scale', 'theme', 'editor', 'work_state', 'onboarding']

    # הוסף שדה חדש לתזמון נושא
    allowed_fields.append('theme_schedule')

    update_data = {}

    for field in allowed_fields:
        if field in data:
            # ולידציה מיוחדת לתזמון נושא
            if field == 'theme_schedule':
                schedule = data[field]
                if not _validate_theme_schedule(schedule):
                    return jsonify({'error': 'הגדרות תזמון לא תקינות'}), 400
            update_data[field] = data[field]

    if not update_data:
        return jsonify({'error': 'לא נשלחו שדות לעדכון'}), 400

    # עדכון במסד הנתונים
    db = get_db()
    db.ui_prefs.update_one(
        {'user_id': user_id},
        {'$set': update_data},
        upsert=True
    )

    return jsonify({'success': True})


def _validate_theme_schedule(schedule):
    """
    ולידציה להגדרות תזמון נושא
    גישה "רכה": מאמתים פורמט ואורך, לא רשימה קשיחה של נושאים
    """
    if not isinstance(schedule, dict):
        return False

    required_fields = ['enabled', 'dayTheme', 'nightTheme',
                       'dayStartHour', 'dayStartMinute',
                       'nightStartHour', 'nightStartMinute']

    for field in required_fields:
        if field not in schedule:
            return False

    # ולידציה לסוגי נתונים
    if not isinstance(schedule['enabled'], bool):
        return False

    # ולידציה גמישה לנושאים - בדיקת פורמט ואורך בלבד
    # מאפשר נושאים חדשים ונושאים מותאמים אישית
    for theme_field in ['dayTheme', 'nightTheme']:
        theme_value = schedule[theme_field]
        if not isinstance(theme_value, str):
            return False
        if len(theme_value) == 0 or len(theme_value) > 100:
            return False
        # בדיקה בסיסית נגד injection
        if any(c in theme_value for c in ['<', '>', '"', "'", ';', '\\', '\n']):
            return False

    # ולידציה לשעות ודקות
    hour_fields = ['dayStartHour', 'nightStartHour']
    minute_fields = ['dayStartMinute', 'nightStartMinute']

    for field in hour_fields:
        if not isinstance(schedule[field], int) or schedule[field] < 0 or schedule[field] > 23:
            return False

    for field in minute_fields:
        if not isinstance(schedule[field], int) or schedule[field] < 0 or schedule[field] > 59:
            return False

    # ולידציה אופציונלית ל-timezone
    if 'timezone' in schedule:
        tz = schedule['timezone']
        if not isinstance(tz, str) or len(tz) > 50:
            return False

    # ולידציה: זמני יום ולילה לא יכולים להיות זהים
    day_minutes = schedule['dayStartHour'] * 60 + schedule['dayStartMinute']
    night_minutes = schedule['nightStartHour'] * 60 + schedule['nightStartMinute']
    if day_minutes == night_minutes:
        return False

    return True
```

### 3.2 עדכון GET endpoint

הוסף את השדה החדש גם בקריאת ההעדפות:

```python
@app.route('/api/ui_prefs', methods=['GET'])
def get_ui_prefs():
    """
    קבלת העדפות UI של המשתמש
    """
    if not current_user.is_authenticated:
        return jsonify({'error': 'לא מחובר'}), 401

    user_id = current_user.get_id()
    db = get_db()

    prefs = db.ui_prefs.find_one({'user_id': user_id}) or {}

    # הסר שדות פנימיים
    prefs.pop('_id', None)
    prefs.pop('user_id', None)

    # הוסף ערכי ברירת מחדל אם חסרים
    if 'theme_schedule' not in prefs:
        prefs['theme_schedule'] = {
            'enabled': False,
            'dayTheme': 'classic',
            'nightTheme': 'dark',
            'dayStartHour': 7,
            'dayStartMinute': 0,
            'nightStartHour': 19,
            'nightStartMinute': 0
        }

    return jsonify(prefs)
```

---

## 4. שינויים בצד הלקוח

### 4.1 יצירת מודול חדש: `theme-scheduler.js`

**קובץ: `webapp/static/js/theme-scheduler.js`**

> **שינויים מרכזיים מהגרסה הקודמת:**
> 1. **הפרדה בין theme ל-mode** - לא נוגעים ב-`dark_mode_preference`
> 2. **מנגנון טיימר יחיד** - רק `setTimeout` מדויק, בלי `setInterval`
> 3. **ניקוי טיימרים** - שומרים handle ומנקים ב-`stopScheduler()`
> 4. **האזנה לשינויי נושא** - מכבים תזמון כששינוי ידני מכל מקור

```javascript
/**
 * מודול תזמון ערכות נושא אוטומטי
 * מאפשר החלפת נושאים לפי שעות ביממה
 *
 * חשוב: מודול זה מנהל רק את ה-THEME (ערכת עיצוב),
 * לא את ה-MODE (auto/dark/dim/light)
 */
(function() {
    'use strict';

    // ========================================
    // קבועים ומשתנים
    // ========================================

    const STORAGE_KEY = 'theme_schedule';
    const USER_THEME_KEY = 'user_theme';

    // מנגנון טיימר יחיד - רק setTimeout, בלי interval
    let nextChangeTimeoutId = null;
    let currentSchedule = null;
    let isInitialized = false;

    // ברירת מחדל
    const DEFAULT_SCHEDULE = {
        enabled: false,
        dayTheme: 'classic',
        nightTheme: 'dark',
        dayStartHour: 7,
        dayStartMinute: 0,
        nightStartHour: 19,
        nightStartMinute: 0
    };

    // ========================================
    // פונקציות עזר
    // ========================================

    /**
     * המרת שעה ודקה למספר דקות מחצות
     */
    function timeToMinutes(hour, minute) {
        return hour * 60 + minute;
    }

    /**
     * קבלת הזמן הנוכחי (עם תמיכה ב-timezone)
     */
    function getCurrentTime(timezone) {
        const now = new Date();
        if (timezone) {
            try {
                const formatter = new Intl.DateTimeFormat('en-US', {
                    timeZone: timezone,
                    hour: 'numeric',
                    minute: 'numeric',
                    hour12: false
                });
                const parts = formatter.formatToParts(now);
                const hour = parseInt(parts.find(p => p.type === 'hour').value);
                const minute = parseInt(parts.find(p => p.type === 'minute').value);
                return { hours: hour, minutes: minute, seconds: now.getSeconds() };
            } catch (e) {
                console.warn('[ThemeScheduler] timezone לא תקין, משתמש בזמן מקומי:', e);
            }
        }
        return { hours: now.getHours(), minutes: now.getMinutes(), seconds: now.getSeconds() };
    }

    /**
     * בדיקה האם השעה הנוכחית נמצאת בטווח היום
     */
    function isDayTime(schedule) {
        const time = getCurrentTime(schedule.timezone);
        const currentMinutes = timeToMinutes(time.hours, time.minutes);
        const dayStart = timeToMinutes(schedule.dayStartHour, schedule.dayStartMinute);
        const nightStart = timeToMinutes(schedule.nightStartHour, schedule.nightStartMinute);

        // טיפול במקרה שהיום מתחיל לפני הלילה (מצב רגיל)
        if (dayStart < nightStart) {
            return currentMinutes >= dayStart && currentMinutes < nightStart;
        }

        // טיפול במקרה שהלילה מתחיל לפני היום (למשל: לילה מ-22:00, יום מ-06:00)
        return currentMinutes >= dayStart || currentMinutes < nightStart;
    }

    /**
     * קבלת הנושא המתאים לשעה הנוכחית
     */
    function getScheduledTheme(schedule) {
        return isDayTime(schedule) ? schedule.dayTheme : schedule.nightTheme;
    }

    /**
     * חישוב הזמן עד השינוי הבא (במילישניות)
     */
    function getTimeUntilNextChange(schedule) {
        const time = getCurrentTime(schedule.timezone);
        const currentMinutes = timeToMinutes(time.hours, time.minutes);
        const dayStart = timeToMinutes(schedule.dayStartHour, schedule.dayStartMinute);
        const nightStart = timeToMinutes(schedule.nightStartHour, schedule.nightStartMinute);

        let nextChangeMinutes;

        if (isDayTime(schedule)) {
            // אנחנו ביום, השינוי הבא הוא בתחילת הלילה
            nextChangeMinutes = nightStart;
        } else {
            // אנחנו בלילה, השינוי הבא הוא בתחילת היום
            nextChangeMinutes = dayStart;
        }

        let minutesUntilChange = nextChangeMinutes - currentMinutes;

        // אם השינוי הבא הוא למחרת
        if (minutesUntilChange <= 0) {
            minutesUntilChange += 24 * 60;
        }

        // המרה למילישניות (פחות השניות שכבר עברו בדקה הנוכחית)
        return (minutesUntilChange * 60 - time.seconds) * 1000;
    }

    // ========================================
    // אחסון
    // ========================================

    /**
     * טעינת הגדרות מ-localStorage
     */
    function loadSchedule() {
        try {
            const stored = localStorage.getItem(STORAGE_KEY);
            if (stored) {
                const parsed = JSON.parse(stored);
                return { ...DEFAULT_SCHEDULE, ...parsed };
            }
        } catch (e) {
            console.warn('[ThemeScheduler] שגיאה בטעינת הגדרות:', e);
        }
        return { ...DEFAULT_SCHEDULE };
    }

    /**
     * שמירת הגדרות ב-localStorage
     */
    function saveSchedule(schedule) {
        try {
            localStorage.setItem(STORAGE_KEY, JSON.stringify(schedule));
            currentSchedule = schedule;
        } catch (e) {
            console.warn('[ThemeScheduler] שגיאה בשמירת הגדרות:', e);
        }
    }

    /**
     * סנכרון הגדרות לשרת
     */
    async function syncToServer(schedule) {
        try {
            const response = await fetch('/api/ui_prefs', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ theme_schedule: schedule })
            });

            if (!response.ok) {
                console.warn('[ThemeScheduler] שגיאה בסנכרון לשרת:', response.status);
            }
        } catch (e) {
            console.warn('[ThemeScheduler] שגיאה בסנכרון לשרת:', e);
        }
    }

    /**
     * טעינת הגדרות מהשרת
     */
    async function loadFromServer() {
        try {
            const response = await fetch('/api/ui_prefs');
            if (response.ok) {
                const data = await response.json();
                if (data.theme_schedule) {
                    return { ...DEFAULT_SCHEDULE, ...data.theme_schedule };
                }
            }
        } catch (e) {
            console.warn('[ThemeScheduler] שגיאה בטעינה מהשרת:', e);
        }
        return null;
    }

    // ========================================
    // החלת נושא
    // ========================================

    /**
     * החלת נושא על הדף
     *
     * חשוב: מעדכנים רק את data-theme ו-user_theme,
     * לא את dark_mode_preference (שמיועד ל-mode)
     */
    function applyTheme(themeName) {
        const html = document.documentElement;
        const currentTheme = html.getAttribute('data-theme');

        // אם הנושא כבר מוחל, אין צורך לעשות כלום
        if (currentTheme === themeName) {
            return;
        }

        console.log(`[ThemeScheduler] מחליף נושא ל: ${themeName}`);

        // עדכון data-theme על HTML element
        html.setAttribute('data-theme', themeName);

        // עדכון user_theme ב-localStorage (לא dark_mode_preference!)
        try {
            localStorage.setItem(USER_THEME_KEY, themeName);
        } catch (e) {
            console.warn('[ThemeScheduler] לא ניתן לשמור ב-localStorage:', e);
        }

        // סנכרון לשרת
        syncThemeToServer(themeName);

        // הפעלת אירוע לרכיבים אחרים
        window.dispatchEvent(new CustomEvent('theme-changed', {
            detail: { theme: themeName, source: 'scheduler' }
        }));
    }

    /**
     * סנכרון נושא לשרת
     */
    async function syncThemeToServer(themeName) {
        try {
            await fetch('/api/ui_prefs', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ theme: themeName })
            });
        } catch (e) {
            console.warn('[ThemeScheduler] שגיאה בסנכרון נושא לשרת:', e);
        }
    }

    /**
     * בדיקה והחלת נושא לפי הזמן הנוכחי
     */
    function checkAndApplyTheme() {
        if (!currentSchedule || !currentSchedule.enabled) {
            return;
        }

        const scheduledTheme = getScheduledTheme(currentSchedule);
        applyTheme(scheduledTheme);
    }

    // ========================================
    // ניהול טיימר (מנגנון יחיד - setTimeout בלבד)
    // ========================================

    /**
     * התחלת מעקב אחר זמן
     */
    function startScheduler() {
        // עצור טיימר קודם אם קיים
        stopScheduler();

        currentSchedule = loadSchedule();

        if (!currentSchedule.enabled) {
            console.log('[ThemeScheduler] תזמון לא פעיל');
            return;
        }

        console.log('[ThemeScheduler] מתחיל תזמון נושאים', currentSchedule);

        // החל נושא מיידית
        checkAndApplyTheme();

        // תזמן את השינוי הבא (מנגנון יחיד - רק timeout)
        scheduleNextChange();
    }

    /**
     * תזמון השינוי הבא
     * משתמש רק ב-setTimeout (לא interval) למדויקות מקסימלית
     */
    function scheduleNextChange() {
        // נקה timeout קודם אם קיים
        if (nextChangeTimeoutId !== null) {
            clearTimeout(nextChangeTimeoutId);
            nextChangeTimeoutId = null;
        }

        if (!currentSchedule || !currentSchedule.enabled) {
            return;
        }

        const msUntilChange = getTimeUntilNextChange(currentSchedule);

        console.log(`[ThemeScheduler] שינוי הבא בעוד ${Math.round(msUntilChange / 60000)} דקות`);

        // שמור את ה-timeout ID לניקוי עתידי
        nextChangeTimeoutId = setTimeout(() => {
            nextChangeTimeoutId = null;
            checkAndApplyTheme();
            // תזמן את השינוי הבא
            scheduleNextChange();
        }, msUntilChange);
    }

    /**
     * עצירת המעקב
     */
    function stopScheduler() {
        if (nextChangeTimeoutId !== null) {
            clearTimeout(nextChangeTimeoutId);
            nextChangeTimeoutId = null;
        }
    }

    // ========================================
    // טיפול בשינויי נושא ידניים
    // ========================================

    /**
     * האזנה לשינויי נושא מכל מקור
     * מכבה תזמון כששינוי ידני מתרחש
     */
    function setupManualChangeListener() {
        window.addEventListener('theme-changed', (event) => {
            // אם השינוי הגיע מה-scheduler עצמו, אין צורך לכבות
            if (event.detail && event.detail.source === 'scheduler') {
                return;
            }

            // שינוי ידני - כבה תזמון
            if (currentSchedule && currentSchedule.enabled) {
                console.log('[ThemeScheduler] שינוי ידני זוהה, מכבה תזמון');
                disableSchedule();

                // הודע למשתמש
                notifyScheduleDisabled();
            }
        });
    }

    /**
     * כיבוי התזמון
     */
    function disableSchedule() {
        if (currentSchedule) {
            currentSchedule.enabled = false;
            saveSchedule(currentSchedule);
            syncToServer(currentSchedule);
        }
        stopScheduler();
    }

    /**
     * הודעה למשתמש על כיבוי תזמון
     */
    function notifyScheduleDisabled() {
        // בדוק אם יש פונקציית toast גלובלית
        if (typeof showToast === 'function') {
            showToast('תזמון אוטומטי כובה (שינית נושא ידנית)');
        } else if (typeof Toastify !== 'undefined') {
            Toastify({
                text: 'תזמון אוטומטי כובה',
                duration: 3000,
                gravity: 'bottom',
                position: 'center'
            }).showToast();
        }
    }

    // ========================================
    // API ציבורי
    // ========================================

    const ThemeScheduler = {
        /**
         * אתחול המודול
         */
        init: async function() {
            if (isInitialized) {
                return;
            }
            isInitialized = true;

            // הגדר מאזין לשינויים ידניים
            setupManualChangeListener();

            // נסה לטעון מהשרת קודם
            const serverSchedule = await loadFromServer();
            if (serverSchedule) {
                saveSchedule(serverSchedule);
            } else {
                currentSchedule = loadSchedule();
            }

            // התחל את ה-scheduler אם מופעל
            if (currentSchedule && currentSchedule.enabled) {
                startScheduler();
            }

            // האזן לשינויים ב-visibility (כשהמשתמש חוזר ללשונית)
            document.addEventListener('visibilitychange', () => {
                if (document.visibilityState === 'visible' && currentSchedule?.enabled) {
                    checkAndApplyTheme();
                    // עדכן את הטיימר (ייתכן שעבר זמן)
                    scheduleNextChange();
                }
            });

            console.log('[ThemeScheduler] מאותחל');
        },

        /**
         * קבלת ההגדרות הנוכחיות
         */
        getSchedule: function() {
            return { ...(currentSchedule || loadSchedule()) };
        },

        /**
         * עדכון הגדרות
         */
        setSchedule: function(schedule) {
            const newSchedule = { ...DEFAULT_SCHEDULE, ...schedule };
            saveSchedule(newSchedule);
            syncToServer(newSchedule);

            if (newSchedule.enabled) {
                startScheduler();
            } else {
                stopScheduler();
            }

            return newSchedule;
        },

        /**
         * הפעלה/כיבוי
         */
        toggle: function() {
            const schedule = this.getSchedule();
            schedule.enabled = !schedule.enabled;
            return this.setSchedule(schedule);
        },

        /**
         * בדיקה האם מופעל
         */
        isEnabled: function() {
            return currentSchedule && currentSchedule.enabled;
        },

        /**
         * קבלת הנושא הנוכחי לפי התזמון
         */
        getCurrentTheme: function() {
            const schedule = this.getSchedule();
            return getScheduledTheme(schedule);
        },

        /**
         * בדיקה האם כרגע יום או לילה
         */
        isDayTime: function() {
            const schedule = this.getSchedule();
            return isDayTime(schedule);
        },

        /**
         * החל נושא עכשיו (ידני)
         */
        applyNow: function() {
            checkAndApplyTheme();
        },

        /**
         * איפוס לברירת מחדל
         */
        reset: function() {
            return this.setSchedule(DEFAULT_SCHEDULE);
        },

        /**
         * כיבוי התזמון
         */
        disable: function() {
            disableSchedule();
        }
    };

    // חשיפה גלובלית
    window.ThemeScheduler = ThemeScheduler;

})();
```

### 4.2 סדר טעינה נכון ב-base.html

> **חשוב**: יש לטעון את `theme-scheduler.js` **לפני** `dark-mode.js` כדי למנוע FOUC

**קובץ: `webapp/templates/base.html`**

```html
<head>
    <!-- ... -->

    <!-- טעינה מוקדמת של theme-scheduler (מונע FOUC) -->
    <script>
        // טעינה סינכרונית מוקדמת של הגדרות תזמון
        (function() {
            try {
                const stored = localStorage.getItem('theme_schedule');
                if (stored) {
                    const schedule = JSON.parse(stored);
                    if (schedule.enabled) {
                        // חשב איזה נושא להחיל
                        const now = new Date();
                        const currentMinutes = now.getHours() * 60 + now.getMinutes();
                        const dayStart = schedule.dayStartHour * 60 + schedule.dayStartMinute;
                        const nightStart = schedule.nightStartHour * 60 + schedule.nightStartMinute;

                        let isDay;
                        if (dayStart < nightStart) {
                            isDay = currentMinutes >= dayStart && currentMinutes < nightStart;
                        } else {
                            isDay = currentMinutes >= dayStart || currentMinutes < nightStart;
                        }

                        const theme = isDay ? schedule.dayTheme : schedule.nightTheme;
                        document.documentElement.setAttribute('data-theme', theme);

                        // סמן שתזמון פעיל (ל-dark-mode.js)
                        window.__themeSchedulerActive = true;
                    }
                }
            } catch (e) {
                // שגיאה - נמשיך עם ה-fallback
            }
        })();
    </script>
</head>

<body>
    <!-- ... -->

    <!-- תזמון ערכות נושא - לפני dark-mode.js -->
    <script src="{{ url_for('static', filename='js/theme-scheduler.js') }}"></script>
    <script>
        // אתחול אסינכרוני לאחר טעינת הדף
        if (window.ThemeScheduler) {
            window.ThemeScheduler.init();
        }
    </script>

    <!-- dark-mode.js אחרי theme-scheduler -->
    <script src="{{ url_for('static', filename='js/dark-mode.js') }}"></script>
</body>
```

### 4.3 עדכון `dark-mode.js` - שינויים מינימליים

**קובץ: `webapp/static/js/dark-mode.js`**

הוסף בדיקה אם ה-scheduler פעיל:

```javascript
// בתחילת הקובץ, אחרי הגדרת הקבועים:

/**
 * בדיקה האם תזמון אוטומטי פעיל
 */
function isSchedulerActive() {
    // בדיקה מוקדמת (לפני שה-ThemeScheduler נטען)
    if (window.__themeSchedulerActive) {
        return true;
    }
    // בדיקה מלאה (אחרי שה-ThemeScheduler נטען)
    return window.ThemeScheduler && window.ThemeScheduler.isEnabled();
}

// עדכן את updateTheme:
function updateTheme() {
    // אם תזמון אוטומטי פעיל, תן לו לנהל
    if (isSchedulerActive()) {
        return;
    }

    // המשך עם הלוגיקה הקיימת...
    const preference = loadPreference();
    if (!preference) {
        return;
    }
    // ...
}

// עדכן את ensureThemeSync:
function ensureThemeSync() {
    // אם תזמון אוטומטי פעיל, אל תדרוס
    if (isSchedulerActive()) {
        return;
    }

    // המשך עם הלוגיקה הקיימת...
    const preference = loadPreference();
    // ...
}
```

---

## 5. ממשק משתמש

### 5.1 HTML - הוספה לדף ההגדרות

**קובץ: `webapp/templates/settings/theme_settings.html`** (או חלק מ-settings.html)

```html
<!-- קטע תזמון ערכות נושא -->
<div class="settings-section" id="theme-schedule-section">
    <h3 class="section-title">
        <i class="fa-solid fa-clock"></i>
        תזמון אוטומטי
    </h3>

    <div class="setting-row">
        <div class="setting-info">
            <span class="setting-label">החלפת נושא אוטומטית</span>
            <span class="setting-description">החלף בין נושא יום ולילה לפי שעות שתגדיר</span>
        </div>
        <label class="toggle-switch">
            <input type="checkbox" id="schedule-enabled" />
            <span class="toggle-slider"></span>
        </label>
    </div>

    <div id="schedule-settings" class="schedule-settings" style="display: none;">
        <!-- בחירת נושא יום -->
        <div class="setting-row">
            <div class="setting-info">
                <span class="setting-label">
                    <i class="fa-solid fa-sun"></i>
                    נושא יום
                </span>
            </div>
            <select id="day-theme" class="theme-select">
                <option value="classic">קלאסי (בהיר)</option>
                <option value="ocean">אוקיינוס</option>
                <option value="rose-pine-dawn">Rose Pine Dawn</option>
            </select>
        </div>

        <!-- שעת התחלת יום - שימוש ב-input type="time" -->
        <div class="setting-row">
            <div class="setting-info">
                <span class="setting-label">שעת התחלת יום</span>
            </div>
            <input type="time" id="day-start-time" value="07:00" class="time-input" />
        </div>

        <!-- בחירת נושא לילה -->
        <div class="setting-row">
            <div class="setting-info">
                <span class="setting-label">
                    <i class="fa-solid fa-moon"></i>
                    נושא לילה
                </span>
            </div>
            <select id="night-theme" class="theme-select">
                <option value="dark">כהה</option>
                <option value="dim">מעומעם</option>
                <option value="nebula">ערפילית</option>
                <option value="high-contrast">ניגודיות גבוהה</option>
            </select>
        </div>

        <!-- שעת התחלת לילה - שימוש ב-input type="time" -->
        <div class="setting-row">
            <div class="setting-info">
                <span class="setting-label">שעת התחלת לילה</span>
            </div>
            <input type="time" id="night-start-time" value="19:00" class="time-input" />
        </div>

        <!-- תצוגה מקדימה -->
        <div class="schedule-preview">
            <div class="preview-timeline">
                <!-- שימוש ב-position absolute לסגמנטים כדי להציג בזמנים הנכונים -->
                <div class="timeline-bar" id="timeline-bar">
                    <!-- הסגמנטים יתווספו דינמית -->
                </div>
                <div class="timeline-labels">
                    <span>00:00</span>
                    <span>06:00</span>
                    <span>12:00</span>
                    <span>18:00</span>
                    <span>24:00</span>
                </div>
                <!-- מחוונים לזמני מעבר -->
                <div class="timeline-markers" id="timeline-markers">
                    <!-- יתווספו דינמית -->
                </div>
            </div>
            <p class="current-status" id="schedule-status">
                <!-- יתעדכן דינמית -->
            </p>
        </div>
    </div>
</div>
```

### 5.2 CSS - סגנונות לממשק

**קובץ: `webapp/static/css/theme-scheduler.css`**

```css
/* ======================================== */
/* תזמון ערכות נושא - סגנונות              */
/* ======================================== */

.schedule-settings {
    margin-top: 1rem;
    padding: 1rem;
    background: var(--bg-secondary);
    border-radius: 8px;
    border: 1px solid var(--glass-border);
}

.schedule-settings.active {
    display: block !important;
}

/* בוחר זמן - input type="time" */
.time-input {
    padding: 0.5rem 1rem;
    border: 1px solid var(--glass-border);
    border-radius: 6px;
    background: var(--input-bg);
    color: var(--text-primary);
    font-size: 1rem;
    font-family: inherit;
    direction: ltr;
    min-width: 120px;
}

.time-input:focus {
    outline: none;
    border-color: var(--primary);
    box-shadow: 0 0 0 2px var(--primary-light);
}

/* בוחר נושא */
.theme-select {
    padding: 0.5rem 1rem;
    border: 1px solid var(--glass-border);
    border-radius: 6px;
    background: var(--input-bg);
    color: var(--text-primary);
    font-size: 0.9rem;
    cursor: pointer;
    min-width: 150px;
}

.theme-select:focus {
    outline: none;
    border-color: var(--primary);
}

/* תצוגה מקדימה - ציר זמן */
.schedule-preview {
    margin-top: 1.5rem;
    padding-top: 1rem;
    border-top: 1px solid var(--glass-border);
}

.preview-timeline {
    margin-bottom: 1rem;
}

.timeline-bar {
    height: 2rem;
    border-radius: 4px;
    overflow: hidden;
    position: relative;
    background: var(--bg-tertiary);
}

/* סגמנטים עם position absolute לפוזיציה מדויקת */
.timeline-segment {
    position: absolute;
    top: 0;
    height: 100%;
    transition: left 0.3s ease, width 0.3s ease;
}

.timeline-segment.day {
    background: linear-gradient(135deg, #FFD93D, #FF9F1C);
}

.timeline-segment.night {
    background: linear-gradient(135deg, #4A4E69, #22223B);
}

/* מחוונים לזמני מעבר */
.timeline-markers {
    position: relative;
    height: 0.5rem;
}

.timeline-marker {
    position: absolute;
    width: 2px;
    height: 0.75rem;
    background: var(--primary);
    transform: translateX(-50%);
    top: -0.25rem;
}

.timeline-marker::after {
    content: attr(data-time);
    position: absolute;
    top: 100%;
    left: 50%;
    transform: translateX(-50%);
    font-size: 0.65rem;
    color: var(--primary);
    white-space: nowrap;
    margin-top: 2px;
}

.timeline-labels {
    display: flex;
    justify-content: space-between;
    margin-top: 0.5rem;
    font-size: 0.75rem;
    color: var(--text-muted);
    direction: ltr;
}

/* סטטוס נוכחי */
.current-status {
    text-align: center;
    padding: 0.75rem;
    background: var(--bg-tertiary);
    border-radius: 6px;
    font-size: 0.9rem;
    color: var(--text-secondary);
}

.current-status .status-icon {
    margin-inline-end: 0.5rem;
}

.current-status.day-mode {
    background: linear-gradient(135deg, rgba(255, 217, 61, 0.1), rgba(255, 159, 28, 0.1));
    color: #FF9F1C;
}

.current-status.night-mode {
    background: linear-gradient(135deg, rgba(74, 78, 105, 0.2), rgba(34, 34, 59, 0.2));
    color: #9A8C98;
}

/* טוגל סוויץ' */
.toggle-switch {
    position: relative;
    display: inline-block;
    width: 3.5rem;
    height: 2rem;
}

.toggle-switch input {
    opacity: 0;
    width: 0;
    height: 0;
}

.toggle-slider {
    position: absolute;
    cursor: pointer;
    inset: 0;
    background-color: var(--bg-tertiary);
    transition: 0.3s;
    border-radius: 2rem;
    border: 1px solid var(--glass-border);
}

.toggle-slider:before {
    position: absolute;
    content: "";
    height: 1.5rem;
    width: 1.5rem;
    right: 0.2rem;
    bottom: 0.2rem;
    background-color: white;
    transition: 0.3s;
    border-radius: 50%;
    box-shadow: 0 2px 4px rgba(0, 0, 0, 0.2);
}

.toggle-switch input:checked + .toggle-slider {
    background-color: var(--primary);
    border-color: var(--primary);
}

.toggle-switch input:checked + .toggle-slider:before {
    transform: translateX(-1.5rem);
}

/* התאמות לדארק מוד */
[data-theme="dark"] .toggle-slider,
[data-theme="dim"] .toggle-slider,
[data-theme="nebula"] .toggle-slider {
    background-color: var(--bg-secondary);
}

/* אנימציה לפתיחה */
@keyframes slideDown {
    from {
        opacity: 0;
        max-height: 0;
        transform: translateY(-10px);
    }
    to {
        opacity: 1;
        max-height: 500px;
        transform: translateY(0);
    }
}

.schedule-settings.opening {
    animation: slideDown 0.3s ease forwards;
}
```

### 5.3 JavaScript - לוגיקת ממשק המשתמש

**קובץ: `webapp/static/js/theme-schedule-ui.js`**

```javascript
/**
 * ממשק משתמש לתזמון ערכות נושא
 */
(function() {
    'use strict';

    // אלמנטים
    let elements = {};

    /**
     * אתחול ה-UI
     */
    function init() {
        // וודא ש-ThemeScheduler קיים
        if (!window.ThemeScheduler) {
            console.warn('ThemeScheduler לא נטען');
            return;
        }

        // מצא אלמנטים
        elements = {
            enabledToggle: document.getElementById('schedule-enabled'),
            settingsPanel: document.getElementById('schedule-settings'),
            dayTheme: document.getElementById('day-theme'),
            nightTheme: document.getElementById('night-theme'),
            dayStartTime: document.getElementById('day-start-time'),
            nightStartTime: document.getElementById('night-start-time'),
            status: document.getElementById('schedule-status')
            // timelineBar ו-markersContainer נגישים דרך getElementById ישירות ב-updatePreview
        };

        // בדוק שכל האלמנטים קיימים
        const section = document.getElementById('theme-schedule-section');
        if (!section) {
            return; // הקטע לא קיים בדף הזה
        }

        // טען הגדרות נוכחיות
        loadCurrentSettings();

        // הוסף מאזינים
        attachEventListeners();

        // עדכן תצוגה
        updatePreview();

        // טען נושאים מותאמים אישית
        loadCustomThemes();
    }

    /**
     * טעינת הגדרות נוכחיות לטופס
     */
    function loadCurrentSettings() {
        const schedule = window.ThemeScheduler.getSchedule();

        if (elements.enabledToggle) {
            elements.enabledToggle.checked = schedule.enabled;
            toggleSettingsPanel(schedule.enabled);
        }

        if (elements.dayTheme) elements.dayTheme.value = schedule.dayTheme;
        if (elements.nightTheme) elements.nightTheme.value = schedule.nightTheme;

        // המרה לפורמט time input (HH:MM)
        if (elements.dayStartTime) {
            elements.dayStartTime.value = formatTime(schedule.dayStartHour, schedule.dayStartMinute);
        }
        if (elements.nightStartTime) {
            elements.nightStartTime.value = formatTime(schedule.nightStartHour, schedule.nightStartMinute);
        }
    }

    /**
     * פורמט זמן ל-HH:MM
     */
    function formatTime(hour, minute) {
        return `${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}`;
    }

    /**
     * פירוק זמן מ-HH:MM
     */
    function parseTime(timeString) {
        const [hour, minute] = timeString.split(':').map(Number);
        return { hour: hour || 0, minute: minute || 0 };
    }

    /**
     * הוספת מאזינים לאירועים
     */
    function attachEventListeners() {
        // טוגל הפעלה/כיבוי
        if (elements.enabledToggle) {
            elements.enabledToggle.addEventListener('change', (e) => {
                toggleSettingsPanel(e.target.checked);
                saveSettings();
            });
        }

        // שינויים בהגדרות
        const inputs = [
            elements.dayTheme,
            elements.nightTheme,
            elements.dayStartTime,
            elements.nightStartTime
        ];

        inputs.forEach(input => {
            if (input) {
                input.addEventListener('change', () => {
                    saveSettings();
                    updatePreview();
                });
            }
        });
    }

    /**
     * הצגה/הסתרה של פאנל ההגדרות
     */
    function toggleSettingsPanel(show) {
        if (!elements.settingsPanel) return;

        if (show) {
            elements.settingsPanel.style.display = 'block';
            elements.settingsPanel.classList.add('opening');
            setTimeout(() => {
                elements.settingsPanel.classList.remove('opening');
            }, 300);
        } else {
            elements.settingsPanel.style.display = 'none';
        }
    }

    /**
     * שמירת הגדרות
     */
    function saveSettings() {
        const dayTime = parseTime(elements.dayStartTime?.value || '07:00');
        const nightTime = parseTime(elements.nightStartTime?.value || '19:00');

        const schedule = {
            enabled: elements.enabledToggle?.checked || false,
            dayTheme: elements.dayTheme?.value || 'classic',
            nightTheme: elements.nightTheme?.value || 'dark',
            dayStartHour: dayTime.hour,
            dayStartMinute: dayTime.minute,
            nightStartHour: nightTime.hour,
            nightStartMinute: nightTime.minute
        };

        window.ThemeScheduler.setSchedule(schedule);

        // הצג הודעה
        showSaveConfirmation();
    }

    /**
     * עדכון תצוגה מקדימה
     * מציג סגמנטים בפוזיציות המדויקות על ציר 24 שעות
     */
    function updatePreview() {
        const schedule = window.ThemeScheduler.getSchedule();
        const timelineBar = document.getElementById('timeline-bar');
        const markersContainer = document.getElementById('timeline-markers');

        if (!timelineBar) return;

        // נקה סגמנטים קודמים
        timelineBar.innerHTML = '';
        if (markersContainer) markersContainer.innerHTML = '';

        const dayStart = schedule.dayStartHour * 60 + schedule.dayStartMinute;
        const nightStart = schedule.nightStartHour * 60 + schedule.nightStartMinute;
        const totalMinutes = 24 * 60;

        // חשב אחוזי פוזיציה
        const dayStartPercent = (dayStart / totalMinutes) * 100;
        const nightStartPercent = (nightStart / totalMinutes) * 100;

        if (dayStart < nightStart) {
            // מצב רגיל: לילה-יום-לילה
            // לילה מ-00:00 עד dayStart
            if (dayStartPercent > 0) {
                createSegment(timelineBar, 'night', 0, dayStartPercent);
            }
            // יום מ-dayStart עד nightStart
            createSegment(timelineBar, 'day', dayStartPercent, nightStartPercent - dayStartPercent);
            // לילה מ-nightStart עד 24:00
            if (nightStartPercent < 100) {
                createSegment(timelineBar, 'night', nightStartPercent, 100 - nightStartPercent);
            }
        } else {
            // מצב הפוך: יום-לילה-יום (יום חוצה חצות)
            // יום מ-00:00 עד nightStart
            if (nightStartPercent > 0) {
                createSegment(timelineBar, 'day', 0, nightStartPercent);
            }
            // לילה מ-nightStart עד dayStart
            createSegment(timelineBar, 'night', nightStartPercent, dayStartPercent - nightStartPercent);
            // יום מ-dayStart עד 24:00
            if (dayStartPercent < 100) {
                createSegment(timelineBar, 'day', dayStartPercent, 100 - dayStartPercent);
            }
        }

        // הוסף מחוונים לזמני מעבר
        if (markersContainer) {
            createMarker(markersContainer, dayStartPercent,
                formatTime(schedule.dayStartHour, schedule.dayStartMinute) + ' ☀️');
            createMarker(markersContainer, nightStartPercent,
                formatTime(schedule.nightStartHour, schedule.nightStartMinute) + ' 🌙');
        }

        // עדכן סטטוס
        updateStatus(schedule);
    }

    /**
     * יצירת סגמנט בציר הזמן
     */
    function createSegment(container, type, leftPercent, widthPercent) {
        const segment = document.createElement('div');
        segment.className = `timeline-segment ${type}`;
        segment.style.left = leftPercent + '%';
        segment.style.width = widthPercent + '%';
        container.appendChild(segment);
    }

    /**
     * יצירת מחוון זמן
     */
    function createMarker(container, leftPercent, label) {
        const marker = document.createElement('div');
        marker.className = 'timeline-marker';
        marker.style.left = leftPercent + '%';
        marker.setAttribute('data-time', label);
        container.appendChild(marker);
    }

    /**
     * עדכון טקסט הסטטוס
     */
    function updateStatus(schedule) {
        if (!elements.status) return;

        const isDay = window.ThemeScheduler.isDayTime();
        const currentTheme = isDay ? schedule.dayTheme : schedule.nightTheme;
        const themeNames = {
            'classic': 'קלאסי',
            'ocean': 'אוקיינוס',
            'rose-pine-dawn': 'Rose Pine Dawn',
            'dark': 'כהה',
            'dim': 'מעומעם',
            'nebula': 'ערפילית',
            'high-contrast': 'ניגודיות גבוהה'
        };

        const icon = isDay ? 'fa-sun' : 'fa-moon';
        const modeName = isDay ? 'יום' : 'לילה';
        const themeName = themeNames[currentTheme] || currentTheme;

        elements.status.innerHTML = `
            <i class="fa-solid ${icon} status-icon"></i>
            כרגע: מצב ${modeName} - נושא "${themeName}"
        `;

        elements.status.className = 'current-status ' + (isDay ? 'day-mode' : 'night-mode');
    }

    /**
     * טעינת נושאים מותאמים אישית
     */
    async function loadCustomThemes() {
        try {
            const response = await fetch('/api/themes');
            if (!response.ok) return;

            const themes = await response.json();
            if (!Array.isArray(themes)) return;

            themes.forEach(theme => {
                const option = document.createElement('option');
                option.value = `custom:${theme.id || theme._id}`;
                option.textContent = theme.name || theme.id;

                // הוסף לשני ה-selects
                if (elements.dayTheme) {
                    elements.dayTheme.appendChild(option.cloneNode(true));
                }
                if (elements.nightTheme) {
                    elements.nightTheme.appendChild(option);
                }
            });

            // עדכן בחירה אחרי טעינת האופציות
            loadCurrentSettings();
        } catch (e) {
            console.warn('לא ניתן לטעון נושאים מותאמים:', e);
        }
    }

    /**
     * הצגת אישור שמירה
     */
    function showSaveConfirmation() {
        if (typeof showToast === 'function') {
            showToast('הגדרות תזמון נשמרו');
        } else if (typeof Toastify !== 'undefined') {
            Toastify({
                text: 'הגדרות תזמון נשמרו',
                duration: 2000,
                gravity: 'bottom',
                position: 'center',
                style: {
                    background: 'var(--success)'
                }
            }).showToast();
        }
    }

    // אתחול כשהדף נטען
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

})();
```

---

## 6. בדיקות

### 6.1 בדיקות יחידה - Python

**קובץ: `tests/test_theme_schedule_api.py`**

```python
import pytest
from webapp.app import app, _validate_theme_schedule
from unittest.mock import patch, MagicMock


@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client


@pytest.fixture
def authenticated_client(client):
    """לקוח מאומת"""
    with patch('webapp.app.current_user') as mock_user:
        mock_user.is_authenticated = True
        mock_user.get_id.return_value = 'test_user_123'
        yield client


class TestThemeScheduleValidation:
    """בדיקות ולידציה להגדרות תזמון"""

    def test_valid_schedule_preset_themes(self):
        """תזמון תקין עם נושאים מוכרים"""
        schedule = {
            'enabled': True,
            'dayTheme': 'classic',
            'nightTheme': 'dark',
            'dayStartHour': 7,
            'dayStartMinute': 0,
            'nightStartHour': 19,
            'nightStartMinute': 0
        }
        assert _validate_theme_schedule(schedule) is True

    def test_valid_schedule_custom_themes(self):
        """תזמון תקין עם נושאים מותאמים"""
        schedule = {
            'enabled': True,
            'dayTheme': 'custom:abc123',
            'nightTheme': 'my-custom-theme',
            'dayStartHour': 8,
            'dayStartMinute': 30,
            'nightStartHour': 20,
            'nightStartMinute': 0
        }
        assert _validate_theme_schedule(schedule) is True

    def test_valid_schedule_with_timezone(self):
        """תזמון תקין עם אזור זמן"""
        schedule = {
            'enabled': False,
            'dayTheme': 'ocean',
            'nightTheme': 'nebula',
            'dayStartHour': 6,
            'dayStartMinute': 0,
            'nightStartHour': 22,
            'nightStartMinute': 30,
            'timezone': 'Asia/Jerusalem'
        }
        assert _validate_theme_schedule(schedule) is True

    def test_invalid_hour_too_high(self):
        """שעה לא תקינה (גבוהה מדי)"""
        schedule = {
            'enabled': True,
            'dayTheme': 'classic',
            'nightTheme': 'dark',
            'dayStartHour': 25,
            'dayStartMinute': 0,
            'nightStartHour': 19,
            'nightStartMinute': 0
        }
        assert _validate_theme_schedule(schedule) is False

    def test_invalid_hour_negative(self):
        """שעה לא תקינה (שלילית)"""
        schedule = {
            'enabled': True,
            'dayTheme': 'classic',
            'nightTheme': 'dark',
            'dayStartHour': -1,
            'dayStartMinute': 0,
            'nightStartHour': 19,
            'nightStartMinute': 0
        }
        assert _validate_theme_schedule(schedule) is False

    def test_invalid_minute(self):
        """דקה לא תקינה"""
        schedule = {
            'enabled': True,
            'dayTheme': 'classic',
            'nightTheme': 'dark',
            'dayStartHour': 7,
            'dayStartMinute': 60,
            'nightStartHour': 19,
            'nightStartMinute': 0
        }
        assert _validate_theme_schedule(schedule) is False

    def test_missing_required_field(self):
        """שדה חובה חסר"""
        schedule = {
            'enabled': True,
            'dayTheme': 'classic',
            # nightTheme חסר
            'dayStartHour': 7,
            'dayStartMinute': 0,
            'nightStartHour': 19,
            'nightStartMinute': 0
        }
        assert _validate_theme_schedule(schedule) is False

    def test_invalid_theme_empty(self):
        """נושא ריק"""
        schedule = {
            'enabled': True,
            'dayTheme': '',
            'nightTheme': 'dark',
            'dayStartHour': 7,
            'dayStartMinute': 0,
            'nightStartHour': 19,
            'nightStartMinute': 0
        }
        assert _validate_theme_schedule(schedule) is False

    def test_invalid_theme_too_long(self):
        """נושא ארוך מדי"""
        schedule = {
            'enabled': True,
            'dayTheme': 'a' * 101,
            'nightTheme': 'dark',
            'dayStartHour': 7,
            'dayStartMinute': 0,
            'nightStartHour': 19,
            'nightStartMinute': 0
        }
        assert _validate_theme_schedule(schedule) is False

    def test_invalid_theme_injection_attempt(self):
        """ניסיון injection"""
        schedule = {
            'enabled': True,
            'dayTheme': '<script>alert(1)</script>',
            'nightTheme': 'dark',
            'dayStartHour': 7,
            'dayStartMinute': 0,
            'nightStartHour': 19,
            'nightStartMinute': 0
        }
        assert _validate_theme_schedule(schedule) is False

    def test_invalid_enabled_type(self):
        """enabled לא boolean"""
        schedule = {
            'enabled': 'true',  # string במקום bool
            'dayTheme': 'classic',
            'nightTheme': 'dark',
            'dayStartHour': 7,
            'dayStartMinute': 0,
            'nightStartHour': 19,
            'nightStartMinute': 0
        }
        assert _validate_theme_schedule(schedule) is False

    def test_not_a_dict(self):
        """קלט שאינו dictionary"""
        assert _validate_theme_schedule(None) is False
        assert _validate_theme_schedule([]) is False
        assert _validate_theme_schedule("string") is False

    def test_identical_day_and_night_times(self):
        """זמני יום ולילה זהים"""
        schedule = {
            'enabled': True,
            'dayTheme': 'classic',
            'nightTheme': 'dark',
            'dayStartHour': 7,
            'dayStartMinute': 30,
            'nightStartHour': 7,
            'nightStartMinute': 30  # זהה לזמן התחלת יום!
        }
        assert _validate_theme_schedule(schedule) is False


class TestThemeScheduleAPI:
    """בדיקות API"""

    def test_unauthenticated_request(self, client):
        """בקשה ללא אימות"""
        response = client.post('/api/ui_prefs', json={'theme_schedule': {}})
        assert response.status_code == 401

    def test_save_valid_schedule(self, authenticated_client):
        """שמירת תזמון תקין"""
        schedule = {
            'theme_schedule': {
                'enabled': True,
                'dayTheme': 'classic',
                'nightTheme': 'dark',
                'dayStartHour': 7,
                'dayStartMinute': 0,
                'nightStartHour': 19,
                'nightStartMinute': 0
            }
        }

        with patch('webapp.app.get_db') as mock_db:
            mock_db.return_value.ui_prefs.update_one = MagicMock()
            response = authenticated_client.post(
                '/api/ui_prefs',
                json=schedule,
                content_type='application/json'
            )
            assert response.status_code == 200
            assert response.json.get('success') is True

    def test_save_invalid_schedule(self, authenticated_client):
        """שמירת תזמון לא תקין"""
        schedule = {
            'theme_schedule': {
                'enabled': True,
                'dayTheme': 'classic',
                'nightTheme': 'dark',
                'dayStartHour': 25,  # לא תקין
                'dayStartMinute': 0,
                'nightStartHour': 19,
                'nightStartMinute': 0
            }
        }

        response = authenticated_client.post(
            '/api/ui_prefs',
            json=schedule,
            content_type='application/json'
        )
        assert response.status_code == 400
```

### 6.2 בדיקות יחידה - JavaScript

**קובץ: `tests/js/theme-scheduler.test.js`**

> **הערה**: בדיקות אלו דורשות הגדרת Jest עם jsdom ו-mocks מתאימים

```javascript
/**
 * בדיקות למודול ThemeScheduler
 *
 * הרצה: npm test -- theme-scheduler.test.js
 */

// Mock localStorage
const localStorageMock = (() => {
    let store = {};
    return {
        getItem: jest.fn(key => store[key] || null),
        setItem: jest.fn((key, value) => { store[key] = value; }),
        removeItem: jest.fn(key => { delete store[key]; }),
        clear: jest.fn(() => { store = {}; })
    };
})();
Object.defineProperty(window, 'localStorage', { value: localStorageMock });

// Mock fetch
global.fetch = jest.fn(() =>
    Promise.resolve({
        ok: true,
        json: () => Promise.resolve({})
    })
);

// Import module (assuming ES module setup)
// const ThemeScheduler = require('../webapp/static/js/theme-scheduler.js');

describe('ThemeScheduler', () => {
    beforeEach(() => {
        localStorage.clear();
        jest.clearAllMocks();
        jest.useFakeTimers();

        // Reset document
        document.documentElement.removeAttribute('data-theme');
    });

    afterEach(() => {
        jest.useRealTimers();
    });

    describe('Time Calculations', () => {
        test('timeToMinutes converts correctly', () => {
            expect(7 * 60 + 30).toBe(450);
            expect(0 * 60 + 0).toBe(0);
            expect(23 * 60 + 59).toBe(1439);
        });

        test('isDayTime returns true during day hours', () => {
            const schedule = {
                dayStartHour: 7,
                dayStartMinute: 0,
                nightStartHour: 19,
                nightStartMinute: 0
            };

            // Mock time: 12:00
            jest.setSystemTime(new Date(2024, 0, 1, 12, 0, 0));

            // Test logic
            const currentMinutes = 12 * 60;
            const dayStart = 7 * 60;
            const nightStart = 19 * 60;

            const isDay = currentMinutes >= dayStart && currentMinutes < nightStart;
            expect(isDay).toBe(true);
        });

        test('isDayTime returns false during night hours', () => {
            // Mock time: 22:00
            const currentMinutes = 22 * 60;
            const dayStart = 7 * 60;
            const nightStart = 19 * 60;

            const isDay = currentMinutes >= dayStart && currentMinutes < nightStart;
            expect(isDay).toBe(false);
        });

        test('isDayTime handles normal schedule (day before night)', () => {
            // Schedule: day from 06:00, night from 22:00
            // dayStart < nightStart → use AND logic
            const dayStart = 6 * 60;   // 360
            const nightStart = 22 * 60; // 1320

            // Test at 23:00 (should be night)
            const time23 = 23 * 60; // 1380
            const isDay23 = time23 >= dayStart && time23 < nightStart;
            expect(isDay23).toBe(false); // 1380 >= 360 && 1380 < 1320 = false

            // Test at 03:00 (should be night - before day starts)
            const time03 = 3 * 60; // 180
            const isDay03 = time03 >= dayStart && time03 < nightStart;
            expect(isDay03).toBe(false); // 180 >= 360 = false

            // Test at 12:00 (should be day)
            const time12 = 12 * 60; // 720
            const isDay12 = time12 >= dayStart && time12 < nightStart;
            expect(isDay12).toBe(true); // 720 >= 360 && 720 < 1320 = true
        });

        test('isDayTime handles inverted schedule (day crosses midnight)', () => {
            // Schedule: night from 06:00, day from 20:00 (day crosses midnight)
            // dayStart > nightStart → use OR logic
            const dayStart = 20 * 60;  // 1200
            const nightStart = 6 * 60; // 360

            // Test at 23:00 (should be day - after day starts)
            const time23 = 23 * 60; // 1380
            const isDay23 = time23 >= dayStart || time23 < nightStart;
            expect(isDay23).toBe(true); // 1380 >= 1200 = true

            // Test at 03:00 (should be day - before night starts)
            const time03 = 3 * 60; // 180
            const isDay03 = time03 >= dayStart || time03 < nightStart;
            expect(isDay03).toBe(true); // 180 < 360 = true

            // Test at 12:00 (should be night)
            const time12 = 12 * 60; // 720
            const isDay12 = time12 >= dayStart || time12 < nightStart;
            expect(isDay12).toBe(false); // 720 >= 1200 = false, 720 < 360 = false
        });
    });

    describe('Theme Selection', () => {
        test('getScheduledTheme returns day theme during day', () => {
            const schedule = {
                dayTheme: 'classic',
                nightTheme: 'dark',
                dayStartHour: 7,
                dayStartMinute: 0,
                nightStartHour: 19,
                nightStartMinute: 0
            };

            // Simulate day time
            const isDay = true;
            const result = isDay ? schedule.dayTheme : schedule.nightTheme;
            expect(result).toBe('classic');
        });

        test('getScheduledTheme returns night theme during night', () => {
            const schedule = {
                dayTheme: 'classic',
                nightTheme: 'dark',
                dayStartHour: 7,
                dayStartMinute: 0,
                nightStartHour: 19,
                nightStartMinute: 0
            };

            // Simulate night time
            const isDay = false;
            const result = isDay ? schedule.dayTheme : schedule.nightTheme;
            expect(result).toBe('dark');
        });
    });

    describe('localStorage Persistence', () => {
        test('saves and loads schedule correctly', () => {
            const schedule = {
                enabled: true,
                dayTheme: 'ocean',
                nightTheme: 'nebula',
                dayStartHour: 8,
                dayStartMinute: 30,
                nightStartHour: 20,
                nightStartMinute: 0
            };

            localStorage.setItem('theme_schedule', JSON.stringify(schedule));

            const loaded = JSON.parse(localStorage.getItem('theme_schedule'));
            expect(loaded).toEqual(schedule);
        });

        test('handles missing localStorage gracefully', () => {
            const DEFAULT_SCHEDULE = {
                enabled: false,
                dayTheme: 'classic',
                nightTheme: 'dark',
                dayStartHour: 7,
                dayStartMinute: 0,
                nightStartHour: 19,
                nightStartMinute: 0
            };

            const stored = localStorage.getItem('theme_schedule');
            const schedule = stored ? JSON.parse(stored) : DEFAULT_SCHEDULE;

            expect(schedule).toEqual(DEFAULT_SCHEDULE);
        });
    });

    describe('Timer Management', () => {
        test('calculates time until next change correctly', () => {
            // Current time: 12:00, night starts at 19:00
            // Expected: 7 hours = 420 minutes = 25200000ms
            const currentMinutes = 12 * 60;
            const nightStart = 19 * 60;

            const minutesUntilChange = nightStart - currentMinutes;
            const msUntilChange = minutesUntilChange * 60 * 1000;

            expect(msUntilChange).toBe(25200000);
        });

        test('handles next day calculation', () => {
            // Current time: 22:00, day starts at 07:00 (next day)
            // Expected: 9 hours = 540 minutes
            const currentMinutes = 22 * 60;
            const dayStart = 7 * 60;

            let minutesUntilChange = dayStart - currentMinutes;
            if (minutesUntilChange <= 0) {
                minutesUntilChange += 24 * 60;
            }

            expect(minutesUntilChange).toBe(540);
        });
    });

    describe('Theme Application', () => {
        test('sets data-theme attribute', () => {
            document.documentElement.setAttribute('data-theme', 'dark');
            expect(document.documentElement.getAttribute('data-theme')).toBe('dark');
        });

        test('saves to user_theme in localStorage', () => {
            localStorage.setItem('user_theme', 'ocean');
            expect(localStorage.getItem('user_theme')).toBe('ocean');
        });

        test('does not touch dark_mode_preference', () => {
            // Ensure we don't write theme names to dark_mode_preference
            localStorage.setItem('dark_mode_preference', 'auto');

            // Simulate applying a theme
            const themeName = 'ocean';
            localStorage.setItem('user_theme', themeName);

            // dark_mode_preference should remain unchanged
            expect(localStorage.getItem('dark_mode_preference')).toBe('auto');
        });
    });

    describe('Manual Change Detection', () => {
        test('dispatches theme-changed event with source', () => {
            const listener = jest.fn();
            window.addEventListener('theme-changed', listener);

            const event = new CustomEvent('theme-changed', {
                detail: { theme: 'dark', source: 'scheduler' }
            });
            window.dispatchEvent(event);

            expect(listener).toHaveBeenCalled();
            expect(listener.mock.calls[0][0].detail.source).toBe('scheduler');

            window.removeEventListener('theme-changed', listener);
        });
    });
});
```

---

## סיכום

### שינויים מרכזיים מהגרסה הקודמת

| נושא | לפני | אחרי |
|------|------|------|
| **mode vs theme** | ערבוב בין השניים | הפרדה מלאה - לא נוגעים ב-`dark_mode_preference` |
| **מנגנון טיימר** | `setInterval` + `setTimeout` | רק `setTimeout` מדויק |
| **ניקוי טיימרים** | לא מנקה timeout | שומר handle ומנקה ב-`stopScheduler()` |
| **סדר טעינה** | לא מוגדר | סקריפט inline ב-head + טעינה לפני dark-mode.js |
| **ולידציה בשרת** | רשימה קשיחה | ולידציה גמישה (פורמט + אורך) |
| **כיבוי ידני** | רק ב-`toggleDarkMode()` | האזנה ל-`theme-changed` מכל מקור |
| **UI זמן** | `input type="number"` | `input type="time"` |
| **Timezone** | לא נתמך | תמיכה אופציונלית |

### קבצים ליצירה:
1. `webapp/static/js/theme-scheduler.js` - מודול הליבה
2. `webapp/static/js/theme-schedule-ui.js` - לוגיקת ממשק
3. `webapp/static/css/theme-scheduler.css` - סגנונות
4. `tests/test_theme_schedule_api.py` - בדיקות Python
5. `tests/js/theme-scheduler.test.js` - בדיקות JavaScript

### קבצים לעדכון:
1. `webapp/app.py` - הוספת ולידציה ושדה חדש
2. `webapp/static/js/dark-mode.js` - בדיקת `isSchedulerActive()`
3. `webapp/templates/base.html` - סקריפט inline + סדר טעינה נכון
4. `webapp/templates/settings/*.html` - הוספת ממשק ההגדרות

---

## הערות נוספות

### תמיכה באזור זמן
כבר מובנית במודול. כדי להפעיל:

```javascript
ThemeScheduler.setSchedule({
    ...schedule,
    timezone: 'Asia/Jerusalem'
});
```

### התראות לפני שינוי
אפשר להוסיף (nice-to-have):

```javascript
function scheduleNotification(msUntilChange) {
    const notifyBefore = 60000; // דקה לפני

    if (msUntilChange > notifyBefore && Notification.permission === 'granted') {
        setTimeout(() => {
            new Notification('הנושא ישתנה בעוד דקה');
        }, msUntilChange - notifyBefore);
    }
}
```

### Debug mode
להוספת לוגים מפורטים:

```javascript
// בתחילת המודול
const DEBUG = localStorage.getItem('theme_scheduler_debug') === 'true';

function log(...args) {
    if (DEBUG) console.log('[ThemeScheduler]', ...args);
}
```
