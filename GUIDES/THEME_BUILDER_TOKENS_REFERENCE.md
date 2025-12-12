# Theme Builder – רפרנס טוקנים מלא

> **מסמך טכני:** רשימה מפורטת של כל הטוקנים שה-Theme Builder מטפל בהם  
> **תאריך:** דצמבר 2024  
> **גרסה:** 1.0

---

## 📋 סקירה כללית

Theme Builder מאפשר עריכה של **13 טוקנים CSS** המחולקים ל-5 קבוצות:
1. רקעים (3)
2. אקסנטים (2)
3. טקסט (2)
4. Glass Effects (4)
5. Markdown (2)

כל טוקן ממופה לשדה בטופס ולמשתנה CSS ב-Preview.

---

## 1️⃣ קבוצת רקעים (Backgrounds)

### `--bg-primary`
**תיאור:** רקע ראשי של הדף  
**שדה בטופס:** `bgPrimary`  
**דוגמאות ערכים:**
- HEX: `#1a1a2e`
- RGB: `rgb(26, 26, 46)`
- RGBA: `rgba(26, 26, 46, 1)`

**שימוש ב-UI:**
- רקע `<body>`
- רקע containers ראשיים
- רקע modals

**דוגמה בתצוגה מקדימה:**
```css
.preview-panel {
    background: var(--bg-primary);
}
```

**טיפים:**
- בתמות כהות: צבע כהה (#1a1a2e)
- בתמות בהירות: צבע בהיר (#f7fafc)
- שמור על ניגודיות עם `--text-primary`

---

### `--bg-secondary`
**תיאור:** רקע משני לאזורים מוגבהים  
**שדה בטופס:** `bgSecondary`  
**דוגמאות ערכים:**
- `#16213e` (כהה יותר או בהיר יותר מ-`--bg-primary`)
- `rgba(255, 255, 255, 0.05)`

**שימוש ב-UI:**
- רקע navbar
- רקע sidebar
- רקע של קטעים מודגשים

**דוגמה:**
```css
.navbar {
    background: var(--bg-secondary);
}
```

**טיפים:**
- צריך להיות שונה מעט מ-`--bg-primary` (לא אותו ערך!)
- בתמות כהות: כהה יותר או בהיר יותר ב-5-10%
- בתמות בהירות: בהיר יותר או כהה יותר ב-5-10%

---

### `--card-bg`
**תיאור:** רקע כרטיסים, מודלים ואלמנטים מורמים  
**שדה בטופס:** `cardBg`  
**דוגמאות ערכים:**
- `rgba(255, 255, 255, 0.08)` (שכבת זכוכית)
- `#2d3748` (צבע אטום)

**שימוש ב-UI:**
- כרטיסי קבצים
- מודלים
- dropdowns
- tooltips

**דוגמה:**
```css
.file-card {
    background: var(--card-bg);
}
```

**טיפים:**
- בתמות Glass: השתמש ב-RGBA עם שקיפות (0.08-0.15)
- בתמות אטומות: צבע אטום שונה מהרקע הראשי
- חייב להיות ניגודיות ≥3:1 מול `--bg-primary`

---

## 2️⃣ קבוצת אקסנטים (Accent Colors)

### `--primary`
**תיאור:** צבע מותג ראשי, משמש לכפתורים, קישורים, הדגשות  
**שדה בטופס:** `primary`  
**דוגמאות ערכים:**
- `#667eea` (סגול-כחול)
- `#3182ce` (כחול)
- `#48bb78` (ירוק)

**שימוש ב-UI:**
- כפתורים ראשיים (`.btn-primary`)
- קישורים (`<a>`)
- focus states
- progress bars
- badges חשובים

**דוגמה:**
```css
.btn-primary {
    background: var(--primary);
    color: white;
}

a {
    color: var(--primary);
}
```

**טיפים:**
- צבע בולט שנבדל מהרקע
- ניגודיות ≥4.5:1 עם טקסט לבן
- זהה במכל התמות שלך

---

### `--secondary`
**תיאור:** צבע מותג משני, משלים את הראשי  
**שדה בטופס:** `secondary`  
**דוגמאות ערכים:**
- `#764ba2` (סגול)
- `#2c5282` (כחול כהה)
- `#38a169` (ירוק כהה)

**שימוש ב-UI:**
- כפתורים משניים
- גרדיאנטים (עם `--primary`)
- הדגשות משניות
- אייקונים

**דוגמה:**
```css
.btn-secondary {
    background: var(--secondary);
}

.gradient-bg {
    background: linear-gradient(135deg, var(--primary), var(--secondary));
}
```

**טיפים:**
- משלים את `--primary` (לא זהה!)
- בדרך כלל כהה יותר או בהיר יותר
- נראה טוב בגרדיאנט עם `--primary`

---

## 3️⃣ קבוצת טקסט (Text Colors)

### `--text-primary`
**תיאור:** צבע טקסט ראשי לכל התוכן  
**שדה בטופס:** `textPrimary`  
**דוגמאות ערכים:**
- `#f5f5f5` (בהיר, לתמות כהות)
- `#1a202c` (כהה, לתמות בהירות)
- `rgba(255, 255, 255, 0.95)`

**שימוש ב-UI:**
- כל הטקסט הרגיל
- כותרות
- תפריטים
- labels

**דוגמה:**
```css
body {
    color: var(--text-primary);
}

h1, h2, h3, h4, h5, h6 {
    color: var(--text-primary);
}
```

**טיפים:**
- ניגודיות חובה ≥4.5:1 עם `--bg-primary`
- בתמות כהות: לבן או אפור בהיר מאוד
- בתמות בהירות: שחור או אפור כהה מאוד

---

### `--text-secondary`
**תיאור:** צבע טקסט משני לתיאורים ומידע פחות חשוב  
**שדה בטופס:** `textSecondary`  
**דוגמאות ערכים:**
- `rgba(255, 255, 255, 0.8)` (פחות אטום)
- `#718096` (אפור בינוני)

**שימוש ב-UI:**
- תיאורים
- תאריכים
- metadata
- טקסט עזר

**דוגמה:**
```css
.file-meta {
    color: var(--text-secondary);
}

small {
    color: var(--text-secondary);
}
```

**טיפים:**
- ניגודיות מומלצת ≥3:1 (לא חובה WCAG AA)
- פחות בולט מ-`--text-primary`
- עדיין קריא

---

## 4️⃣ קבוצת Glass Effects

### `--glass`
**תיאור:** רקע בסיסי לאפקט זכוכית (Glassmorphism)  
**שדה בטופס:** `glass`  
**דוגמאות ערכים:**
- `rgba(255, 255, 255, 0.1)` (בהיר, לתמות כהות)
- `rgba(0, 0, 0, 0.05)` (כהה, לתמות בהירות)

**שימוש ב-UI:**
- navbar עם backdrop-filter
- modals
- badges
- tooltips

**דוגמה:**
```css
.glass-card {
    background: var(--glass);
    backdrop-filter: blur(var(--glass-blur));
    border: 1px solid var(--glass-border);
}
```

**טיפים:**
- חייב להיות RGBA עם Alpha < 0.3
- עובד הכי טוב עם `backdrop-filter: blur()`
- סליידר Blur ב-Theme Builder שולט על `--glass-blur`

---

### `--glass-border`
**תיאור:** צבע גבול לאלמנטים עם Glass  
**שדה בטופס:** `glassBorder`  
**דוגמאות ערכים:**
- `rgba(255, 255, 255, 0.2)`
- `rgba(0, 0, 0, 0.1)`

**שימוש ב-UI:**
- גבולות כרטיסים
- גבולות modals
- separators

**דוגמה:**
```css
.modal {
    border: 1px solid var(--glass-border);
}
```

**טיפים:**
- בהיר יותר מ-`--glass` (בדרך כלל פי 2)
- שומר על קונסיסטנטיות בגבולות
- RGBA עם Alpha 0.15-0.3

---

### `--glass-hover`
**תיאור:** רקע Glass במצב hover  
**שדה בטופס:** `glassHover`  
**דוגמאות ערכים:**
- `rgba(255, 255, 255, 0.15)` (בהיר יותר מ-`--glass`)
- `rgba(0, 0, 0, 0.08)`

**שימוש ב-UI:**
- כפתורים במצב hover
- כרטיסים במצב hover
- פריטי תפריט במצב hover

**דוגמה:**
```css
.glass-card:hover {
    background: var(--glass-hover);
}
```

**טיפים:**
- בהיר יותר מ-`--glass` (הבדל של ~0.05 ב-Alpha)
- יוצר feedback חזותי לאינטראקציה
- עדיין שומר על שקיפות

---

### `--glass-blur`
**תיאור:** עוצמת הטשטוש ל-backdrop-filter  
**שדה בטופס:** `glassBlur` (סליידר)  
**ערכים תקינים:** `0px` עד `50px` (מומלץ 15-25)  
**ערך ברירת מחדל:** `20px`

**שימוש ב-UI:**
- backdrop-filter של Glass elements

**דוגמה:**
```css
.glass-navbar {
    backdrop-filter: blur(var(--glass-blur));
}
```

**טיפים:**
- ערכים נמוכים (5-10px): עדין, מינימלי
- ערכים בינוניים (15-25px): מאוזן, מומלץ
- ערכים גבוהים (30-50px): דרמטי, עלול להכביד

---

## 5️⃣ קבוצת Markdown

### `--md-surface`
**תיאור:** רקע למצב Markdown Viewer ו-Code blocks  
**שדה בטופס:** `mdSurface`  
**דוגמאות ערכים:**
- `#1b1e24` (כהה, גם בתמות בהירות!)
- `#0d1117`

**שימוש ב-UI:**
- Markdown Preview
- Split View
- Code blocks
- רקע עורך קוד

**דוגמה:**
```css
.preview-code {
    background: var(--md-surface);
    color: var(--md-text);
}
```

**טיפים:**
- **נשאר כהה גם בתמות בהירות** (לפי spec)
- ניגודיות עם `--md-text` חובה
- מתאים לסינטקס הייטינג

---

### `--md-text`
**תיאור:** צבע טקסט ב-Markdown Viewer  
**שדה בטופס:** `mdText`  
**דוגמאות ערכים:**
- `#f0f0f0` (בהיר)
- `#e0e0e0`

**שימוש ב-UI:**
- טקסט ב-Markdown Preview
- קוד ב-Code blocks

**דוגמה:**
```css
.markdown-body {
    color: var(--md-text);
}
```

**טיפים:**
- ניגודיות ≥4.5:1 עם `--md-surface`
- בהיר מספיק לקריאה ממושכת
- מתאים לקריאת קוד

---

## 📊 טבלת סיכום

| טוקן | שדה | דוגמה (כהה) | דוגמה (בהיר) | חובה? |
|------|-----|-------------|--------------|-------|
| `--bg-primary` | `bgPrimary` | `#1a1a2e` | `#f7fafc` | ✅ |
| `--bg-secondary` | `bgSecondary` | `#16213e` | `#edf2f7` | ✅ |
| `--card-bg` | `cardBg` | `rgba(255,255,255,0.08)` | `#ffffff` | ✅ |
| `--primary` | `primary` | `#667eea` | `#667eea` | ✅ |
| `--secondary` | `secondary` | `#764ba2` | `#764ba2` | ✅ |
| `--text-primary` | `textPrimary` | `#f5f5f5` | `#1a202c` | ✅ |
| `--text-secondary` | `textSecondary` | `rgba(255,255,255,0.8)` | `#718096` | ✅ |
| `--glass` | `glass` | `rgba(255,255,255,0.1)` | `rgba(0,0,0,0.05)` | ✅ |
| `--glass-border` | `glassBorder` | `rgba(255,255,255,0.2)` | `rgba(0,0,0,0.1)` | ✅ |
| `--glass-hover` | `glassHover` | `rgba(255,255,255,0.15)` | `rgba(0,0,0,0.08)` | ✅ |
| `--glass-blur` | `glassBlur` | `20px` | `20px` | ✅ |
| `--md-surface` | `mdSurface` | `#1b1e24` | `#1b1e24` ⚠️ | ✅ |
| `--md-text` | `mdText` | `#f0f0f0` | `#f0f0f0` | ✅ |

**⚠️ שים לב:** `--md-surface` ו-`--md-text` נשארים כהים גם בתמות בהירות!

---

## 🎯 הנחיות בחירת ערכים

### 1. ניגודיות (Contrast)
- **טקסט רגיל:** ≥ 4.5:1
- **טקסט גדול (18px+):** ≥ 3:1
- **אלמנטים UI:** ≥ 3:1

**כלי בדיקה:**
- [WebAIM Contrast Checker](https://webaim.org/resources/contrastchecker/)
- Chrome DevTools → Color Picker → Contrast Ratio

---

### 2. עקביות
- שמור על משפחת צבעים אחידה
- `--primary` ו-`--secondary` צריכים להשתלב זה עם זה
- רקעים צריכים להיות בגווני אפור או בטון אחד

---

### 3. נגישות
- תמיד בדוק עם קורא מסך
- ניגודיות היא חובה, לא אופציה
- בדוק גם במצב high-contrast של ה-OS

---

### 4. Glass Effects
- שמור על שקיפות (Alpha < 0.3)
- Blur לא מדי חזק (15-25px מיטבי)
- בדוק שה-Glass נראה טוב גם על תמונות רקע

---

## 🔧 דוגמת Theme מלאה

```json
{
  "name": "Midnight Purple",
  "description": "תמה כהה עם סגול עמוק",
  "is_active": true,
  "variables": {
    "--bg-primary": "#0f0e17",
    "--bg-secondary": "#1a1825",
    "--card-bg": "rgba(138, 104, 207, 0.08)",
    "--primary": "#8a68cf",
    "--secondary": "#5f4b8b",
    "--text-primary": "#f5f3ff",
    "--text-secondary": "rgba(245, 243, 255, 0.75)",
    "--glass": "rgba(138, 104, 207, 0.12)",
    "--glass-border": "rgba(138, 104, 207, 0.25)",
    "--glass-hover": "rgba(138, 104, 207, 0.18)",
    "--glass-blur": "22px",
    "--md-surface": "#16141f",
    "--md-text": "#e8e6f0"
  }
}
```

---

## 📚 משאבים נוספים

- **מדריך מלא:** `THEME_BUILDER_IMPLEMENTATION_GUIDE.md`
- **תיעוד מערכת:** `docs/webapp/theming_and_css.rst`
- **CSS Variables Spec:** [MDN](https://developer.mozilla.org/en-US/docs/Web/CSS/Using_CSS_custom_properties)
- **WCAG 2.1:** [W3C Guidelines](https://www.w3.org/WAI/WCAG21/quickref/)

---

**גרסה:** 1.0  
**עדכון אחרון:** דצמבר 2024  
**מחבר:** AI Assistant (לפי Issue #2097)
