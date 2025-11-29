# אפיון מצבי תצוגה (Display Modes) – WebApp

> **גרסה:** 1.0  
> **תאריך:** נובמבר 2025  
> **סטטוס:** טיוטה לאישור

---

## 📋 תוכן עניינים

1. [מה זה בכלל?](#מה-זה-בכלל)
2. [למה צריך את זה?](#למה-צריך-את-זה)
3. [שלושת המצבים](#שלושת-המצבים)
4. [איך זה עובד מבחינה טכנית](#איך-זה-עובד-מבחינה-טכנית)
5. [מה המשתמש רואה](#מה-המשתמש-רואה)
6. [שיקולי נגישות](#שיקולי-נגישות)
7. [תוכנית יישום](#תוכנית-יישום)
8. [הרחבות עתידיות](#הרחבות-עתידיות)

---

## מה זה בכלל?

**מצבי תצוגה** הם דרך לאפשר לכל משתמש לבחור איך הוא רואה את התוכן – בלי לשנות את התוכן עצמו.

תחשוב על זה ככה:
- 📖 יש את מי שרוצה לקרוא קוד בנוחות, כמו ספר
- 🔹 יש את מי שמשתמש ביומיום ורוצה ניווט נוח ומהיר
- ⚡ ויש את מי שצריך לראות הרבה מידע טכני במקום אחד (אדמינים, דיבאג)

במקום לבנות 3 ממשקים שונים לגמרי, אנחנו בונים **ממשק אחד חכם** שמתאים את עצמו למצב הנבחר.

---

## למה צריך את זה?

### הבעיה היום

| מצב | מה קורה |
|-----|---------|
| קריאת קוד | יש יותר מדי כפתורים מסביב, קשה להתרכז |
| ניווט רגיל | בסדר, אבל לא מותאם לצרכים מיוחדים |
| דיבאג/אדמין | חסר מידע חשוב – צריך להיכנס לכל קובץ בנפרד |

### מה נרוויח

✅ **חוויה מותאמת אישית** – כל אחד עובד איך שנוח לו  
✅ **יעילות** – פחות קליקים למי שצריך  
✅ **נגישות** – מצב קריאה נוח לכולם  
✅ **קוד נקי** – לא מכפילים קומפוננטות, רק מחליפים סגנון

---

## שלושת המצבים

### 🧘 מצב פוקוס (Focus Mode) – "המינימליסט"

> **מתי משתמשים:** קריאת מאמרים, למידה, הצגת קוד במסך גדול

#### מה רואים

```
┌────────────────────────────────────────────────────┐
│                                                    │
│        כותרת הקובץ גדולה ונעימה לעין              │
│                                                    │
│    ┌─────────────────────────────────────────┐    │
│    │                                         │    │
│    │   תוכן הקוד / טקסט                     │    │
│    │   ריווח נדיב                           │    │
│    │   פונט גדול (1.1em)                    │    │
│    │   line-height: 1.8                     │    │
│    │                                         │    │
│    └─────────────────────────────────────────┘    │
│                                                    │
│                    [ חזור למצב רגיל ]              │
│                                                    │
└────────────────────────────────────────────────────┘
```

#### מה מוסתר

- תאריך עדכון, מזהים, תגיות משניות
- טופס פעולות (עריכה, מחיקה)
- סרגל צד / תפריטים צפים
- Navbar מצטמצם לאייקון קטן

#### איך נראה הקוד

```css
/* Focus Mode Variables */
.mode-focus {
  --focus-padding: 2.5rem;
  --focus-font-size: 1.1em;
  --focus-line-height: 1.8;
  --focus-max-width: 800px;
  --focus-bg-overlay: rgba(0, 0, 0, 0.4);
}

.mode-focus .glass-card {
  max-width: var(--focus-max-width);
  margin: 0 auto;
  padding: var(--focus-padding);
  font-size: var(--focus-font-size);
  line-height: var(--focus-line-height);
}

/* הסתרת אלמנטים מיותרים */
.mode-focus .file-meta,
.mode-focus .file-actions,
.mode-focus .filters-section,
.mode-focus .categories-section,
.mode-focus .badge:not(.badge-language) {
  display: none !important;
}

/* רקע מטושטש מסביב לכרטיס */
.mode-focus .focus-overlay {
  position: fixed;
  inset: 0;
  background: var(--focus-bg-overlay);
  backdrop-filter: blur(8px);
  z-index: 99;
}

.mode-focus .glass-card.focused {
  position: relative;
  z-index: 100;
}
```

#### קיצורי דרך

| פעולה | קיצור |
|-------|-------|
| כניסה/יציאה | `Shift + F` |
| גלילה חלקה | `Space` / `Shift + Space` |

---

### 🔹 מצב קלאסי (Classic Mode) – "ברירת מחדל"

> **מתי משתמשים:** רוב הזמן – ניווט רגיל בקבצים

#### מה רואים

**העיצוב הנוכחי כפי שהוא** – בלי שינויים:
- כותרת, תיאור קצר, שפה
- תאריך עדכון בפורמט יחסי ("לפני שעה")
- כפתורי פעולה: צפייה, הורדה, עריכה
- תגיות ובאדג'ים

#### הקוד (כמעט לא משתנה)

```css
/* Classic Mode – ברירת מחדל */
.mode-classic {
  /* משתמש בכל הערכים הקיימים מ-base.html */
}

/* אין הסתרה של שום דבר */
.mode-classic .file-meta,
.mode-classic .file-actions,
.mode-classic .badge {
  display: inherit;
}
```

---

### ⚡ מצב כוח (Power User Mode) – "הדחוס"

> **מתי משתמשים:** אדמינים, דיבאג, עבודה עם הרבה קבצים במקביל

#### מה רואים

```
┌─────────────────────────────────────────────────────────────────────────┐
│ 🔍 חיפוש...                    [סינון] [מיין] [⚙️ Power Mode פעיל]     │
├───────┬────────────────────┬─────────┬──────────────────┬───────────────┤
│ ☐     │ שם קובץ            │ שפה     │ עדכון           │ פעולות        │
├───────┼────────────────────┼─────────┼──────────────────┼───────────────┤
│ ☐     │ main.py            │ Python  │ 24/11/25 14:32  │ 👁 ✏ ⬇ 🗑    │
│       │ ID: 6742a1b2c...   │         │ 1.2KB • 45 שורות│               │
├───────┼────────────────────┼─────────┼──────────────────┼───────────────┤
│ ☑     │ utils.js           │ JS      │ 23/11/25 09:15  │ 👁 ✏ ⬇ 🗑    │
│       │ ID: 6741b2c3d...   │ [Draft] │ 856B • 28 שורות │               │
├───────┼────────────────────┼─────────┼──────────────────┼───────────────┤
│ ☐     │ styles.css         │ CSS     │ 22/11/25 18:45  │ 👁 ✏ ⬇ 🗑    │
│       │ ID: 6740c3d4e...   │         │ 2.4KB • 89 שורות│               │
└───────┴────────────────────┴─────────┴──────────────────┴───────────────┘
│ נבחרו: 1    │ [הוסף למועדפים] [הוסף לאוסף] [מחק] [הורד ZIP]           │
└─────────────────────────────────────────────────────────────────────────┘
```

#### מה מתווסף

| שדה | הסבר |
|-----|------|
| **מזהה קובץ** | `ID: 6742a1b2c...` – קיצור של MongoDB ObjectId |
| **תאריך מלא** | `24/11/25 14:32:05` במקום "לפני שעה" |
| **סטטוס** | תגיות: `[Draft]`, `[Error]`, `[Synced]` |
| **בחירה מרובה** | Checkbox בכל שורה |
| **פעולות מהירות** | כפתורים קומפקטיים ללא טקסט |

#### הקוד

```css
/* Power Mode Variables */
.mode-power {
  --power-font-size: 0.9em;
  --power-line-height: 1.35;
  --power-row-padding: 0.5rem 0.75rem;
  --power-gap: 0.25rem;
}

.mode-power body {
  font-size: var(--power-font-size);
  line-height: var(--power-line-height);
}

/* תצוגת טבלה */
.mode-power .files-grid {
  display: table;
  width: 100%;
  border-collapse: collapse;
}

.mode-power .file-card {
  display: table-row;
  padding: var(--power-row-padding);
  margin: 0;
  border-radius: 0;
  border-bottom: 1px solid var(--glass-border);
}

.mode-power .file-card:hover {
  background: var(--glass-hover);
  transform: none; /* בטל אנימציית hover */
}

/* שדות נוספים שמוצגים רק ב-Power Mode */
.mode-power .file-id,
.mode-power .file-status,
.mode-power .file-full-date {
  display: inline-block !important;
}

/* הסתר שדות לא רלוונטיים */
.mode-power .file-description,
.mode-power .file-relative-date {
  display: none;
}

/* כפתורים קומפקטיים */
.mode-power .btn {
  padding: 0.35rem 0.5rem;
  font-size: 0.85em;
}

.mode-power .btn .btn-text {
  display: none; /* רק אייקון */
}
```

---

## איך זה עובד מבחינה טכנית

### 1. מבנה State

```javascript
// displayModeStore.js
const DisplayModes = {
  FOCUS: 'focus',
  CLASSIC: 'classic', 
  POWER: 'power'
};

const displayModeState = {
  current: DisplayModes.CLASSIC, // ברירת מחדל
  
  // שומרים העדפה
  setMode(mode) {
    this.current = mode;
    document.body.className = document.body.className
      .replace(/mode-\w+/g, '')
      .trim() + ` mode-${mode}`;
    
    // שמירה ל-localStorage
    localStorage.setItem('display_mode', mode);
    
    // שמירה לשרת (אם מחובר)
    this.syncToServer(mode);
  },
  
  getMode() {
    return this.current;
  },
  
  async syncToServer(mode) {
    try {
      await fetch('/api/ui_prefs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ display_mode: mode })
      });
    } catch (e) { /* ignore */ }
  },
  
  // טעינה בעת אתחול
  init() {
    const saved = localStorage.getItem('display_mode');
    if (saved && Object.values(DisplayModes).includes(saved)) {
      this.setMode(saved);
    }
  }
};

// הפעלה בטעינת הדף
document.addEventListener('DOMContentLoaded', () => {
  displayModeState.init();
});
```

### 2. מתג UI

```html
<!-- מתג מצב תצוגה בפינת המסך -->
<div class="display-mode-toggle" role="radiogroup" aria-label="מצב תצוגה">
  <button 
    class="mode-btn" 
    data-mode="focus"
    aria-label="מצב פוקוס"
    title="מצב קריאה מרוכזת (Shift+F)">
    🧘
  </button>
  <button 
    class="mode-btn active" 
    data-mode="classic"
    aria-label="מצב קלאסי"
    title="תצוגה רגילה">
    🔹
  </button>
  <button 
    class="mode-btn" 
    data-mode="power"
    aria-label="מצב כוח"
    title="תצוגה מורחבת לאדמינים">
    ⚡
  </button>
</div>
```

```css
/* עיצוב המתג */
.display-mode-toggle {
  position: fixed;
  bottom: 20px;
  left: 20px; /* RTL: צד ימין */
  display: flex;
  gap: 4px;
  background: var(--glass);
  backdrop-filter: blur(20px);
  border: 1px solid var(--glass-border);
  border-radius: 30px;
  padding: 4px;
  z-index: 1000;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.15);
}

.mode-btn {
  width: 40px;
  height: 40px;
  border: none;
  border-radius: 50%;
  background: transparent;
  cursor: pointer;
  font-size: 1.2rem;
  transition: all 0.2s ease;
  display: flex;
  align-items: center;
  justify-content: center;
}

.mode-btn:hover {
  background: var(--glass-hover);
  transform: scale(1.1);
}

.mode-btn.active {
  background: var(--primary);
  color: white;
  box-shadow: 0 2px 8px rgba(102, 126, 234, 0.4);
}

/* הסתרה במובייל – במקום מתג קבוע, דרופדאון בהגדרות */
@media (max-width: 480px) {
  .display-mode-toggle {
    display: none;
  }
}
```

### 3. קיצורי מקלדת

```javascript
// keyboard-shortcuts.js
document.addEventListener('keydown', (e) => {
  // Shift + F = Toggle Focus Mode
  if (e.shiftKey && e.key === 'F') {
    e.preventDefault();
    const current = displayModeState.getMode();
    displayModeState.setMode(
      current === 'focus' ? 'classic' : 'focus'
    );
    showToast(
      current === 'focus' 
        ? 'חזרת למצב רגיל' 
        : 'מצב פוקוס פעיל – Shift+F ליציאה'
    );
  }
  
  // Ctrl + 1/2/3 = Switch modes
  if (e.ctrlKey && ['1', '2', '3'].includes(e.key)) {
    e.preventDefault();
    const modes = ['focus', 'classic', 'power'];
    displayModeState.setMode(modes[parseInt(e.key) - 1]);
  }
});
```

### 4. אנימציות מעבר

```css
/* מעברים חלקים בין מצבים */
body {
  transition: 
    font-size 0.3s ease,
    line-height 0.3s ease;
}

.glass-card {
  transition:
    padding 0.3s ease,
    max-width 0.3s ease,
    transform 0.2s ease;
}

/* Focus Mode – כניסה דרמטית */
@keyframes focusEnter {
  from {
    opacity: 0;
    transform: scale(0.95);
  }
  to {
    opacity: 1;
    transform: scale(1);
  }
}

.mode-focus .glass-card.focused {
  animation: focusEnter 0.4s ease-out;
}
```

---

## מה המשתמש רואה

### תרשים זרימה

```
┌──────────────────┐
│   משתמש נכנס    │
│   ל-WebApp      │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐     ┌─────────────────────────────┐
│ יש העדפה שמורה? │──✗──▶│ טוען מצב Classic (ברירת    │
│                  │      │ מחדל)                       │
└────────┬─────────┘      └─────────────────────────────┘
         │✓
         ▼
┌──────────────────────┐
│ טוען מצב שמור       │
│ (localStorage/server)│
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│ משתמש לוחץ על מתג   │
│ או קיצור מקלדת       │
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│ CSS class משתנה     │◀──┐
│ על ה-body            │    │
└──────────┬───────────┘    │
           │                 │
           ▼                 │
┌──────────────────────┐    │
│ UI מתעדכן מיידית    │    │
│ עם אנימציה           │    │
└──────────┬───────────┘    │
           │                 │
           ▼                 │
┌──────────────────────┐    │
│ העדפה נשמרת         │────┘
│ (localStorage + API) │
└──────────────────────┘
```

### הודעות Toast

| מצב | הודעה |
|-----|-------|
| כניסה ל-Focus | "🧘 מצב פוקוס פעיל – Shift+F ליציאה" |
| יציאה מ-Focus | "🔹 חזרת למצב רגיל" |
| כניסה ל-Power | "⚡ מצב כוח פעיל – פרטים מורחבים זמינים" |

---

## שיקולי נגישות

### ✅ מה חייבים לשמור

| דרישה | יישום |
|-------|-------|
| **יחס ניגודיות** | מינימום 4.5:1 לטקסט רגיל |
| **גודל פונט מינימלי** | לא פחות מ-14px גם ב-Power Mode |
| **פוקוס מקלדת** | outline ברור בכל המצבים |
| **קריאות למסך** | aria-labels על כל הכפתורים |
| **Reduced Motion** | כיבוד `prefers-reduced-motion` |

### קוד לדוגמה

```css
/* פוקוס מקלדת ברור */
.mode-power .file-card:focus-within,
.mode-focus .glass-card:focus-within {
  outline: 2px solid var(--primary);
  outline-offset: 2px;
}

/* כיבוד העדפת אנימציה מופחתת */
@media (prefers-reduced-motion: reduce) {
  body,
  .glass-card,
  .mode-btn {
    transition: none !important;
    animation: none !important;
  }
}

/* מינימום גודל נגיע */
.mode-power {
  font-size: max(0.9em, 14px);
}
```

---

## תוכנית יישום

### שלב 1: תשתית (1-2 ימים)

- [ ] הוספת קובץ CSS חדש: `display-modes.css`
- [ ] הוספת קובץ JS: `display-mode-store.js`
- [ ] הוספת endpoint: `POST /api/ui_prefs` (אם לא קיים)
- [ ] הוספת שדה `display_mode` למודל User

### שלב 2: מצב Classic (0.5 יום)

- [ ] וידוא שכל הסגנונות הקיימים עובדים עם `.mode-classic`
- [ ] אין שבירה כשאין class על body

### שלב 3: מצב Focus (2-3 ימים)

- [ ] CSS להסתרת אלמנטים
- [ ] Focus Overlay רקע מטושטש
- [ ] קיצור מקלדת `Shift+F`
- [ ] הודעת Toast

### שלב 4: מצב Power (3-4 ימים)

- [ ] CSS לתצוגת טבלה
- [ ] הוספת שדות: File ID, תאריך מלא, סטטוס
- [ ] בדיקה שה-API מחזיר את כל השדות הנדרשים
- [ ] בחירה מרובה (כבר קיים – לבדוק תאימות)

### שלב 5: UI ואינטגרציה (1-2 ימים)

- [ ] מתג מצבים בפינת המסך
- [ ] הוספה להגדרות משתמש
- [ ] בדיקות נגישות
- [ ] בדיקות responsive

### שלב 6: בדיקות ותיקונים (2 ימים)

- [ ] בדיקות ידניות בכל המצבים
- [ ] בדיקות עם קורא מסך
- [ ] תיקון באגים
- [ ] עדכון תיעוד

---

## הרחבות עתידיות

### 🎯 רעיונות לעתיד

1. **מצב Focus ברמת אפליקציה**
   - הסתרת Navbar לגמרי
   - מצב "קריאת ספר" עם ניווט בחיצים

2. **מצב ברירת מחדל לפי תיקייה**
   ```
   הצגות ← Focus Mode
   דיבאג ← Power Mode  
   שאר ← Classic Mode
   ```

3. **אינטגרציה עם ChatOps**
   ```
   /mode focus  – עובר למצב פוקוס
   /mode power  – עובר למצב כוח
   /mode        – מציג מצב נוכחי
   ```

4. **מצבים מותאמים אישית**
   - המשתמש יכול ליצור מצב משלו
   - בוחר אילו שדות להציג/להסתיר

5. **Zen Mode**
   - כמו Focus אבל גם בלי כותרת
   - רק הקוד על מסך שחור
   - לצפייה בפרזנטציות

---

## קבצים שייווצרו/ישתנו

| קובץ | פעולה |
|------|-------|
| `static/css/display-modes.css` | חדש |
| `static/js/display-mode-store.js` | חדש |
| `templates/base.html` | הוספת מתג + import |
| `templates/files.html` | הוספת classes לאלמנטים |
| `templates/settings.html` | הוספת בורר מצב |
| `app.py` | הוספת route לשמירת העדפה |

---

## סיכום

מצבי התצוגה יאפשרו **חוויה מותאמת אישית** בלי לסבך את הקוד.
הגישה של **CSS classes על body** היא פשוטה, יעילה ומתאימה לארכיטקטורה הקיימת.

**המלצה:** להתחיל עם Focus Mode שהוא הכי מבוקש ונותן ערך מיידי למשתמשים.

---

*נכתב בהתאם לכללי הפרויקט – [CodeBot Docs](https://amirbiron.github.io/CodeBot/)*
