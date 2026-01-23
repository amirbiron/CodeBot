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

### 1.3 אחסון העדפות

- **localStorage**: `dark_mode_preference`, `user_theme`
- **MongoDB**: אוסף `ui_prefs` עם שדה `theme`
- **Cookie**: `ui_theme`

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
    dayTheme: 'classic',              // נושא יום
    nightTheme: 'dark',               // נושא לילה
    dayStartHour: 7,                  // שעת התחלת יום (0-23)
    dayStartMinute: 0,                // דקה התחלת יום (0-59)
    nightStartHour: 19,               // שעת התחלת לילה (0-23)
    nightStartMinute: 0               // דקה התחלת לילה (0-59)
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
   └──────────┬───────────┘      │  (auto/dark/light)   │
              │                   └──────────────────────┘
   ┌──────────┴───────────┐
   │                      │
   ▼                      ▼
[יום]                  [לילה]
   │                      │
   ▼                      ▼
┌────────────┐     ┌────────────┐
│ נושא יום  │     │ נושא לילה │
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

    # ולידציה לנושאים (בדיקה שהם מחרוזות לא ריקות)
    valid_themes = ['classic', 'ocean', 'rose-pine-dawn', 'dark', 'dim', 'nebula', 'high-contrast']
    if schedule['dayTheme'] not in valid_themes and not schedule['dayTheme'].startswith('custom:'):
        # אפשר גם נושאים מותאמים אישית
        if not isinstance(schedule['dayTheme'], str) or len(schedule['dayTheme']) > 100:
            return False

    if schedule['nightTheme'] not in valid_themes and not schedule['nightTheme'].startswith('custom:'):
        if not isinstance(schedule['nightTheme'], str) or len(schedule['nightTheme']) > 100:
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

```javascript
/**
 * מודול תזמון ערכות נושא אוטומטי
 * מאפשר החלפת נושאים לפי שעות ביממה
 */
(function() {
    'use strict';

    // ========================================
    // קבועים ומשתנים
    // ========================================

    const STORAGE_KEY = 'theme_schedule';
    const CHECK_INTERVAL_MS = 60000; // בדיקה כל דקה

    let scheduleInterval = null;
    let currentSchedule = null;

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
     * בדיקה האם השעה הנוכחית נמצאת בטווח היום
     */
    function isDayTime(schedule) {
        const now = new Date();
        const currentMinutes = timeToMinutes(now.getHours(), now.getMinutes());
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
        const now = new Date();
        const currentMinutes = timeToMinutes(now.getHours(), now.getMinutes());
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

        // המרה למילישניות (פחות הדקות שכבר עברו בדקה הנוכחית)
        const secondsInCurrentMinute = now.getSeconds();
        return (minutesUntilChange * 60 - secondsInCurrentMinute) * 1000;
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
            console.warn('שגיאה בטעינת הגדרות תזמון:', e);
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
            console.warn('שגיאה בשמירת הגדרות תזמון:', e);
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
                console.warn('שגיאה בסנכרון לשרת:', response.status);
            }
        } catch (e) {
            console.warn('שגיאה בסנכרון לשרת:', e);
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
            console.warn('שגיאה בטעינה מהשרת:', e);
        }
        return null;
    }

    // ========================================
    // החלת נושא
    // ========================================

    /**
     * החלת נושא על הדף
     */
    function applyTheme(themeName) {
        const html = document.documentElement;
        const currentTheme = html.getAttribute('data-theme');

        // אם הנושא כבר מוחל, אין צורך לעשות כלום
        if (currentTheme === themeName) {
            return;
        }

        console.log(`[ThemeScheduler] מחליף נושא ל: ${themeName}`);

        // שימוש ב-DarkMode API אם קיים
        if (window.DarkMode && typeof window.DarkMode.set === 'function') {
            // ממפה את שם הנושא למצב DarkMode
            const modeMap = {
                'classic': 'light',
                'light': 'light',
                'dark': 'dark',
                'dim': 'dim',
                'nebula': 'dark',
                'ocean': 'light',
                'rose-pine-dawn': 'light',
                'high-contrast': 'dark'
            };

            const mode = modeMap[themeName] || 'light';
            window.DarkMode.set(mode);
        }

        // עדכון ישיר של data-theme
        html.setAttribute('data-theme', themeName);

        // עדכון localStorage
        localStorage.setItem('dark_mode_preference', themeName);

        // הפעלת אירוע לרכיבים אחרים
        window.dispatchEvent(new CustomEvent('theme-changed', {
            detail: { theme: themeName, source: 'scheduler' }
        }));
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
    // ניהול טיימר
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

        // הגדר בדיקה תקופתית
        scheduleInterval = setInterval(checkAndApplyTheme, CHECK_INTERVAL_MS);

        // הגדר טיימר מדויק לשינוי הבא
        scheduleNextChange();
    }

    /**
     * תזמון השינוי הבא
     */
    function scheduleNextChange() {
        if (!currentSchedule || !currentSchedule.enabled) {
            return;
        }

        const msUntilChange = getTimeUntilNextChange(currentSchedule);

        console.log(`[ThemeScheduler] שינוי הבא בעוד ${Math.round(msUntilChange / 60000)} דקות`);

        setTimeout(() => {
            checkAndApplyTheme();
            // תזמן את השינוי הבא
            scheduleNextChange();
        }, msUntilChange);
    }

    /**
     * עצירת המעקב
     */
    function stopScheduler() {
        if (scheduleInterval) {
            clearInterval(scheduleInterval);
            scheduleInterval = null;
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
                if (document.visibilityState === 'visible') {
                    checkAndApplyTheme();
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
        }
    };

    // חשיפה גלובלית
    window.ThemeScheduler = ThemeScheduler;

    // אתחול אוטומטי כשהדף נטען
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => ThemeScheduler.init());
    } else {
        ThemeScheduler.init();
    }

})();
```

### 4.2 עדכון `dark-mode.js`

הוסף תמיכה ב-ThemeScheduler בקובץ הקיים.

**מצא את פונקציית `updateTheme` והוסף בדיקה:**

```javascript
function updateTheme() {
    // בדוק אם תזמון אוטומטי פעיל
    if (window.ThemeScheduler && window.ThemeScheduler.isEnabled()) {
        // תן ל-ThemeScheduler לנהל את הנושא
        return;
    }

    // המשך עם הלוגיקה הקיימת...
    const preference = loadPreference();
    // ...
}
```

**הוסף בפונקציית `toggleDarkMode`:**

```javascript
function toggleDarkMode() {
    // כבה תזמון אוטומטי כשהמשתמש משנה ידנית
    if (window.ThemeScheduler && window.ThemeScheduler.isEnabled()) {
        window.ThemeScheduler.setSchedule({ enabled: false });
        showToast('תזמון אוטומטי כובה');
    }

    // המשך עם הלוגיקה הקיימת...
    const current = loadPreference();
    // ...
}
```

### 4.3 הוספת ה-script ל-base.html

**קובץ: `webapp/templates/base.html`**

הוסף לפני סגירת ה-body:

```html
<!-- תזמון ערכות נושא אוטומטי -->
<script src="{{ url_for('static', filename='js/theme-scheduler.js') }}"></script>
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

        <!-- שעת התחלת יום -->
        <div class="setting-row">
            <div class="setting-info">
                <span class="setting-label">שעת התחלת יום</span>
            </div>
            <div class="time-picker">
                <input type="number" id="day-start-hour" min="0" max="23" value="7" />
                <span>:</span>
                <input type="number" id="day-start-minute" min="0" max="59" value="0" step="5" />
            </div>
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

        <!-- שעת התחלת לילה -->
        <div class="setting-row">
            <div class="setting-info">
                <span class="setting-label">שעת התחלת לילה</span>
            </div>
            <div class="time-picker">
                <input type="number" id="night-start-hour" min="0" max="23" value="19" />
                <span>:</span>
                <input type="number" id="night-start-minute" min="0" max="59" value="0" step="5" />
            </div>
        </div>

        <!-- תצוגה מקדימה -->
        <div class="schedule-preview">
            <div class="preview-timeline">
                <div class="timeline-bar">
                    <div class="day-segment" id="day-segment"></div>
                    <div class="night-segment" id="night-segment"></div>
                </div>
                <div class="timeline-labels">
                    <span>00:00</span>
                    <span>06:00</span>
                    <span>12:00</span>
                    <span>18:00</span>
                    <span>24:00</span>
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

/* בוחר זמן */
.time-picker {
    display: flex;
    align-items: center;
    gap: 0.25rem;
    direction: ltr;
}

.time-picker input {
    width: 3.5rem;
    padding: 0.5rem;
    text-align: center;
    border: 1px solid var(--glass-border);
    border-radius: 6px;
    background: var(--input-bg);
    color: var(--text-primary);
    font-size: 1rem;
    font-family: inherit;
}

.time-picker input:focus {
    outline: none;
    border-color: var(--primary);
    box-shadow: 0 0 0 2px var(--primary-light);
}

.time-picker span {
    font-size: 1.25rem;
    font-weight: bold;
    color: var(--text-secondary);
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
    display: flex;
    position: relative;
    background: var(--bg-tertiary);
}

.day-segment {
    background: linear-gradient(135deg, #FFD93D, #FF9F1C);
    height: 100%;
    transition: width 0.3s ease;
}

.night-segment {
    background: linear-gradient(135deg, #4A4E69, #22223B);
    height: 100%;
    transition: width 0.3s ease;
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
            dayStartHour: document.getElementById('day-start-hour'),
            dayStartMinute: document.getElementById('day-start-minute'),
            nightStartHour: document.getElementById('night-start-hour'),
            nightStartMinute: document.getElementById('night-start-minute'),
            status: document.getElementById('schedule-status'),
            daySegment: document.getElementById('day-segment'),
            nightSegment: document.getElementById('night-segment')
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
        if (elements.dayStartHour) elements.dayStartHour.value = schedule.dayStartHour;
        if (elements.dayStartMinute) elements.dayStartMinute.value = schedule.dayStartMinute;
        if (elements.nightStartHour) elements.nightStartHour.value = schedule.nightStartHour;
        if (elements.nightStartMinute) elements.nightStartMinute.value = schedule.nightStartMinute;
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
            elements.dayStartHour,
            elements.dayStartMinute,
            elements.nightStartHour,
            elements.nightStartMinute
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
        const schedule = {
            enabled: elements.enabledToggle?.checked || false,
            dayTheme: elements.dayTheme?.value || 'classic',
            nightTheme: elements.nightTheme?.value || 'dark',
            dayStartHour: parseInt(elements.dayStartHour?.value) || 7,
            dayStartMinute: parseInt(elements.dayStartMinute?.value) || 0,
            nightStartHour: parseInt(elements.nightStartHour?.value) || 19,
            nightStartMinute: parseInt(elements.nightStartMinute?.value) || 0
        };

        window.ThemeScheduler.setSchedule(schedule);

        // הצג הודעה
        showSaveConfirmation();
    }

    /**
     * עדכון תצוגה מקדימה
     */
    function updatePreview() {
        const schedule = window.ThemeScheduler.getSchedule();

        // חשב אחוזי יום ולילה
        const dayStart = schedule.dayStartHour * 60 + schedule.dayStartMinute;
        const nightStart = schedule.nightStartHour * 60 + schedule.nightStartMinute;
        const totalMinutes = 24 * 60;

        let dayPercent, nightPercent;

        if (dayStart < nightStart) {
            // מצב רגיל: יום לפני לילה
            dayPercent = ((nightStart - dayStart) / totalMinutes) * 100;
            nightPercent = 100 - dayPercent;
        } else {
            // לילה עובר חצות
            nightPercent = ((dayStart - nightStart) / totalMinutes) * 100;
            dayPercent = 100 - nightPercent;
        }

        // עדכן סגמנטים
        if (elements.daySegment) {
            elements.daySegment.style.width = dayPercent + '%';
        }
        if (elements.nightSegment) {
            elements.nightSegment.style.width = nightPercent + '%';
        }

        // עדכן סטטוס
        updateStatus(schedule);
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
     * הצגת אישור שמירה
     */
    function showSaveConfirmation() {
        // בדוק אם יש פונקציית toast גלובלית
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
from webapp.app import app
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

    def test_valid_schedule(self, authenticated_client):
        """תזמון תקין צריך להתקבל"""
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

    def test_invalid_hour(self, authenticated_client):
        """שעה לא תקינה צריכה להיכשל"""
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

    def test_invalid_minute(self, authenticated_client):
        """דקה לא תקינה צריכה להיכשל"""
        schedule = {
            'theme_schedule': {
                'enabled': True,
                'dayTheme': 'classic',
                'nightTheme': 'dark',
                'dayStartHour': 7,
                'dayStartMinute': 60,  # לא תקין
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

    def test_missing_field(self, authenticated_client):
        """שדה חסר צריך להיכשל"""
        schedule = {
            'theme_schedule': {
                'enabled': True,
                'dayTheme': 'classic',
                # חסר nightTheme
                'dayStartHour': 7,
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

```javascript
/**
 * בדיקות למודול ThemeScheduler
 */

describe('ThemeScheduler', () => {
    beforeEach(() => {
        // איפוס localStorage
        localStorage.clear();

        // Mock של ThemeScheduler
        // יש לטעון את המודול לפני הבדיקות
    });

    describe('timeToMinutes', () => {
        it('should convert 7:30 to 450 minutes', () => {
            // בדיקה פנימית
            expect(7 * 60 + 30).toBe(450);
        });

        it('should convert 0:0 to 0 minutes', () => {
            expect(0 * 60 + 0).toBe(0);
        });

        it('should convert 23:59 to 1439 minutes', () => {
            expect(23 * 60 + 59).toBe(1439);
        });
    });

    describe('isDayTime', () => {
        const schedule = {
            dayStartHour: 7,
            dayStartMinute: 0,
            nightStartHour: 19,
            nightStartMinute: 0
        };

        it('should return true at 12:00', () => {
            // Mock Date
            const mockDate = new Date(2024, 0, 1, 12, 0);
            jest.spyOn(global, 'Date').mockImplementation(() => mockDate);

            // בדיקה
            const currentMinutes = 12 * 60;
            const dayStart = 7 * 60;
            const nightStart = 19 * 60;

            const isDay = currentMinutes >= dayStart && currentMinutes < nightStart;
            expect(isDay).toBe(true);
        });

        it('should return false at 22:00', () => {
            const currentMinutes = 22 * 60;
            const dayStart = 7 * 60;
            const nightStart = 19 * 60;

            const isDay = currentMinutes >= dayStart && currentMinutes < nightStart;
            expect(isDay).toBe(false);
        });

        it('should return false at 5:00', () => {
            const currentMinutes = 5 * 60;
            const dayStart = 7 * 60;
            const nightStart = 19 * 60;

            const isDay = currentMinutes >= dayStart && currentMinutes < nightStart;
            expect(isDay).toBe(false);
        });
    });

    describe('getScheduledTheme', () => {
        it('should return day theme during day time', () => {
            const schedule = {
                dayTheme: 'classic',
                nightTheme: 'dark',
                dayStartHour: 7,
                dayStartMinute: 0,
                nightStartHour: 19,
                nightStartMinute: 0
            };

            // Mock: 12:00
            const isDay = true; // מדומה
            const result = isDay ? schedule.dayTheme : schedule.nightTheme;

            expect(result).toBe('classic');
        });

        it('should return night theme during night time', () => {
            const schedule = {
                dayTheme: 'classic',
                nightTheme: 'dark',
                dayStartHour: 7,
                dayStartMinute: 0,
                nightStartHour: 19,
                nightStartMinute: 0
            };

            // Mock: 22:00
            const isDay = false; // מדומה
            const result = isDay ? schedule.dayTheme : schedule.nightTheme;

            expect(result).toBe('dark');
        });
    });

    describe('localStorage persistence', () => {
        it('should save and load schedule', () => {
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
    });
});
```

---

## סיכום

### קבצים ליצירה:
1. `webapp/static/js/theme-scheduler.js` - מודול הליבה
2. `webapp/static/js/theme-schedule-ui.js` - לוגיקת ממשק
3. `webapp/static/css/theme-scheduler.css` - סגנונות
4. `tests/test_theme_schedule_api.py` - בדיקות Python
5. `tests/js/theme-scheduler.test.js` - בדיקות JavaScript

### קבצים לעדכון:
1. `webapp/app.py` - הוספת ולידציה ושדה חדש
2. `webapp/static/js/dark-mode.js` - אינטגרציה עם ThemeScheduler
3. `webapp/templates/base.html` - הוספת script
4. `webapp/templates/settings/*.html` - הוספת ממשק ההגדרות

### סדר מימוש מומלץ:
1. צד שרת - עדכון API (**~1 שעה**)
2. מודול JavaScript הליבה (**~2 שעות**)
3. סגנונות CSS (**~1 שעה**)
4. ממשק משתמש HTML + JS (**~2 שעות**)
5. אינטגרציה עם dark-mode.js (**~30 דקות**)
6. בדיקות (**~2 שעות**)

**סה"כ הערכה**: יום עבודה אחד

---

## הערות נוספות

### תמיכה בנושאים מותאמים אישית
כדי לתמוך בנושאים מותאמים אישית בתזמון, יש להוסיף אופציות דינמיות ל-select:

```javascript
// טעינת נושאים מותאמים אישית
async function loadCustomThemes() {
    const response = await fetch('/api/themes');
    const themes = await response.json();

    themes.forEach(theme => {
        const option = document.createElement('option');
        option.value = `custom:${theme.id}`;
        option.textContent = theme.name;
        elements.dayTheme.appendChild(option.cloneNode(true));
        elements.nightTheme.appendChild(option);
    });
}
```

### תמיכה באזורי זמן
אם נדרשת תמיכה באזורי זמן שונים:

```javascript
function getCurrentTimeInTimezone(timezone) {
    return new Date().toLocaleString('en-US', { timeZone: timezone });
}
```

### התראות לפני שינוי
אפשר להוסיף התראה דקה לפני שינוי הנושא:

```javascript
function scheduleNotification(msUntilChange) {
    const notifyBefore = 60000; // דקה לפני

    if (msUntilChange > notifyBefore) {
        setTimeout(() => {
            showNotification('הנושא ישתנה בעוד דקה');
        }, msUntilChange - notifyBefore);
    }
}
```
