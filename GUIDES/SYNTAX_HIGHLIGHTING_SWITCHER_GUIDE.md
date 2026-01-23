# מדריך מימוש: שינוי הדגשת תחביר בעמוד תצוגת הקוד

> **סטטוס:** מדריך למימוש  
> **קשור ל-PR:** שינוי הדגשת תחביר בקלות בעמוד תצוגת הקוד  
> **קבצים רלוונטיים:** `view_file.html`, `view-codemirror-toggle.js`, `codemirror.local.js`, `theme_parser_service.py`

---

## תוכן עניינים

1. [סקירה כללית](#סקירה-כללית)
2. [ארכיטקטורת המערכת הקיימת](#ארכיטקטורת-המערכת-הקיימת)
3. [תכנון הפיצ'ר](#תכנון-הפיצ'ר)
4. [שלבי מימוש](#שלבי-מימוש)
   - [שלב 0: שינויים ב-codemirror.local.js](#שלב-0-שינויים-ב-codemirrorlocaljs)
   - [שלב 1: הגדרת ערכות ההדגשה](#שלב-1-הגדרת-ערכות-ההדגשה)
   - [שלב 2: יצירת המודאל](#שלב-2-יצירת-המודאל)
   - [שלב 3: סגנונות המודאל](#שלב-3-סגנונות-המודאל)
   - [שלב 4: לוגיקת החלפת ערכה](#שלב-4-לוגיקת-החלפת-ערכה)
   - [שלב 5: אינטגרציה עם view-codemirror-toggle.js](#שלב-5-אינטגרציה-עם-view-codemirror-togglejs)
   - [שלב 6: סדר טעינת הקבצים](#שלב-6-סדר-טעינת-הקבצים)
5. [מיפוי צבעים: Tech Guide Dark](#מיפוי-צבעים-tech-guide-dark)
6. [ערכת One Dark](#ערכת-one-dark)
7. [בדיקות](#בדיקות)
8. [נספחים](#נספחים)

---

## סקירה כללית

### הרעיון

הוספת כפתור בעמוד תצוגת הקובץ (`view_file.html`) שיאפשר למשתמש להחליף בין שתי ערכות הדגשת תחביר:

1. **Tech Guide Dark** - ערכה מותאמת אישית לפי ה-JSON המצורף ב-PR
2. **One Dark** - ערכת ברירת המחדל של CodeMirror (מובנית)

### מיקום הכפתור

הכפתור יופיע ליד כפתור "מתקדם / בסיסי" הקיים:

```
┌─────────────────────────────────────────────────────┐
│  📄 קוד מקור                                         │
│  ┌─────────────┐  ┌─────────────┐  ┌──────────────┐ │
│  │ ⚡ מתקדם    │  │ 🎨 ערכה    │  │ ⛶ מסך מלא   │ │
│  └─────────────┘  └─────────────┘  └──────────────┘ │
└─────────────────────────────────────────────────────┘
```

---

## ארכיטקטורת המערכת הקיימת

### קבצים מרכזיים

| קובץ | תפקיד |
|------|-------|
| `webapp/templates/view_file.html` | תבנית עמוד תצוגת הקוד |
| `webapp/static/js/view-codemirror-toggle.js` | לוגיקת מעבר בין תצוגה בסיסית למתקדמת |
| `webapp/static/js/codemirror.local.js` | באנדל CodeMirror הכולל ערכת One Dark |
| `services/theme_parser_service.py` | מיפוי VS Code ל-CSS Variables |
| `docs/webapp/custom_themes_guide.rst` | מדריך ערכות מותאמות |

### זרימת הדגשת התחביר הנוכחית

```
┌─────────────────────┐
│   view_file.html    │
│   (Jinja Template)  │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────────────────────────────────┐
│   view-codemirror-toggle.js                      │
│   - מזהה את data-theme מה-HTML                   │
│   - קורא ל-resolveEffectiveThemeForEditorParity()│
│   - מחליט: custom → CSS classes, אחרת → oneDark  │
└──────────┬──────────────────────────────────────┘
           │
           ▼
┌─────────────────────────────────────────────────┐
│   codemirror.local.js                            │
│   - getSyntaxHighlighter() - dynamic/class       │
│   - oneDark - ערכה מובנית                        │
│   - HighlightStyle.define() - יצירת ערכה דינמית │
└─────────────────────────────────────────────────┘
```

### הבדל חשוב: Editor Theme vs Syntax Highlighting

> ⚠️ **חשוב להבין:** ב-CodeMirror 6 יש הפרדה בין שני סוגי ערכות:

| סוג | תיאור | Compartment |
|-----|-------|-------------|
| **Editor Theme** | צבעי רקע, גאטר, בחירה, פונט, קווי הפרדה | `themeCompartment` |
| **Syntax Highlighting** | צבעי טוקנים (keywords, strings, comments) | `syntaxCompartment` (חדש) |

ערכת `oneDark` המובנית כוללת **את שניהם** יחד. כשאנחנו רוצים להחליף רק את הדגשת התחביר, אנחנו צריכים **שני compartments נפרדים**.

### הפונקציות הקיימות הרלוונטיות

**`view-codemirror-toggle.js`:**
```javascript
function resolveEffectiveThemeForEditorParity() {
  // מחזיר 'custom' אם data-theme="custom"
  // אחרת מחזיר 'dark' (שמפעיל oneDark)
  const htmlTheme = document.documentElement.getAttribute('data-theme');
  if (htmlTheme === 'custom') return 'custom';
  if (['dark', 'dim', 'nebula'].includes(htmlTheme)) return 'dark';
  return 'dark';
}
```

**`codemirror.local.js`:**
```javascript
function createDynamicHighlightStyle(syntaxColors) {
  // יוצר HighlightStyle מאובייקט צבעים
  const specs = [];
  for (const [tagName, style] of Object.entries(syntaxColors)) {
    // ממפה tagName ל-tag של CodeMirror
    specs.push({ tag, ...style });
  }
  return HighlightStyle.define(specs);
}

function getSyntaxHighlighter() {
  // מחזיר dynamic highlighter אם theme=custom
  // אחרת classHighlighter
}
```

---

## תכנון הפיצ'ר

### מצבים אפשריים

| מצב | תיאור | אחסון |
|-----|-------|-------|
| `tech-guide-dark` | ערכת Tech Guide Dark המותאמת | `localStorage.ck_syntax_theme` |
| `one-dark` | ערכת One Dark המובנית | `localStorage.ck_syntax_theme` |

### התנהגות ברירת מחדל

- אם אין ערך שמור: **One Dark** (הערכה הקיימת)
- הערך נשמר ב-`localStorage` ומשותף לכל עמודי התצוגה
- סנכרון בין טאבים דרך `storage` event

### רספונסיביות

- במובייל: המודאל יוצג כ-bottom sheet
- בדסקטופ: מודאל ממורכז רגיל

### הפרדה בין UI Theme ל-Syntax Theme

> ⚠️ **חשוב:** הפיצ'ר הזה מחליף **רק** את הדגשת התחביר (Syntax Highlighting), ולא את ערכת האתר/עורך הכללית.

- `data-theme` של ה-HTML = ערכת UI (dark/light/custom)
- `ck_syntax_theme` ב-localStorage = ערכת syntax בלבד

לא לערבב בין השניים!

---

## שלבי מימוש

### שלב 0: שינויים ב-codemirror.local.js

> ⚠️ **שלב קריטי:** יש להוסיף `syntaxCompartment` נפרד כדי לאפשר החלפה דינמית של הדגשת תחביר.

**שינויים נדרשים בסוף הבאנדל (לפני ה-export):**

```javascript
// === SYNTAX THEME COMPARTMENT ===
// Compartment נפרד להדגשת תחביר (מאפשר החלפה דינמית)
const syntaxCompartment = new Compartment();

// ייצוא ה-compartment החדש
window.CodeMirror6.syntaxCompartment = syntaxCompartment;

// פונקציה ליצירת extensions עם syntax compartment
window.CodeMirror6.createSyntaxExtension = function(highlightStyle) {
  if (!highlightStyle) return syntaxCompartment.of([]);
  return syntaxCompartment.of(syntaxHighlighting(highlightStyle));
};

// פונקציה להחלפת syntax בזמן ריצה
window.CodeMirror6.reconfigureSyntax = function(view, highlightStyle) {
  if (!view || !view.dispatch) return false;
  try {
    const ext = highlightStyle 
      ? syntaxHighlighting(highlightStyle)
      : [];
    view.dispatch({
      effects: syntaxCompartment.reconfigure(ext)
    });
    return true;
  } catch (err) {
    console.error('[CM6] reconfigureSyntax failed:', err);
    return false;
  }
};
```

**עדכון ה-basicSetup להשתמש ב-syntaxCompartment:**

```javascript
// במקום להוסיף syntaxHighlighting ישירות ל-basicSetup,
// נעטוף אותו ב-compartment
const basicSetup = [
  // ... extensions קיימים ...
  syntaxCompartment.of(syntaxHighlighting(classHighlighter)),
  // ... extensions נוספים ...
];
```

---

### שלב 1: הגדרת ערכות ההדגשה

**קובץ חדש: `webapp/static/js/syntax-themes.js`**

```javascript
/**
 * Syntax Highlighting Themes for CodeMirror
 * מגדיר את ערכות ההדגשה הזמינות בעמוד תצוגת הקוד
 */

const SYNTAX_THEMES = {
  'one-dark': {
    id: 'one-dark',
    name: 'One Dark',
    description: 'ערכת ברירת המחדל של CodeMirror',
    type: 'builtin', // מובנית ב-codemirror.local.js
    preview: {
      background: '#282c34',
      keyword: '#c678dd',
      string: '#98c379',
      comment: '#5c6370',
    }
  },
  'tech-guide-dark': {
    id: 'tech-guide-dark',
    name: 'Tech Guide Dark',
    description: 'ערכה מותאמת עם טונים כחולים',
    type: 'custom',
    preview: {
      background: '#0f0f23',
      keyword: '#c586c0',
      string: '#ce9178',
      comment: '#6a9955',
    },
    // מיפוי מלא של tokenColors - ראה נספח א׳
    syntaxColors: null // יאותחל מ-TECH_GUIDE_DARK_SYNTAX
  }
};

// מיפוי Tech Guide Dark tokenColors ל-CodeMirror tags
// ⚠️ הערה: אין כפילויות של keys! כל key מופיע פעם אחת בלבד.
const TECH_GUIDE_DARK_SYNTAX = {
  // === Comments ===
  'comment': { color: '#6a9955', fontStyle: 'italic' },
  'docComment': { color: '#6a9955', fontStyle: 'italic' },
  
  // === Keywords ===
  'keyword': { color: '#c586c0' },
  'controlKeyword': { color: '#c586c0' },
  'moduleKeyword': { color: '#c586c0' },
  'definitionKeyword': { color: '#c586c0' },
  
  // === Types and Classes ===
  'typeName': { color: '#4ec9b0' },
  'className': { color: '#4ec9b0' },
  'definition(className)': { color: '#4ec9b0' },
  'namespace': { color: '#4ec9b0' },
  
  // === Strings ===
  'string': { color: '#ce9178' },
  'string2': { color: '#ce9178' },
  
  // === Numbers and Constants ===
  'number': { color: '#b5cea8' },
  'bool': { color: '#b5cea8' },
  'atom': { color: '#b5cea8' },
  'literal': { color: '#b5cea8' },
  
  // === Variables ===
  'variableName': { color: '#9cdcfe' },
  'local(variableName)': { color: '#9cdcfe', fontStyle: 'italic' },
  'definition(variableName)': { color: '#9cdcfe' },
  'self': { color: '#9cdcfe' },
  
  // === Functions ===
  'function(variableName)': { color: '#dcdcaa' },
  'function(definition(variableName))': { color: '#dcdcaa' },
  'standard(function(variableName))': { color: '#dcdcaa' },
  
  // === Operators and Punctuation ===
  'operator': { color: '#d4d4d4' },
  'punctuation': { color: '#d4d4d4' },
  
  // === Properties (כולל CSS properties ו-JSON keys) ===
  'propertyName': { color: '#9cdcfe' },
  'definition(propertyName)': { color: '#9cdcfe' },
  
  // === HTML/XML ===
  'tagName': { color: '#569cd6' },
  'attributeName': { color: '#9cdcfe' },
  'attributeValue': { color: '#ce9178' },
  'angleBracket': { color: '#808080' },
  
  // === Regex and Escapes ===
  'regexp': { color: '#d16969' },
  'escape': { color: '#d7ba7d' },
  
  // === Special ===
  'meta': { color: '#c586c0' },
  'invalid': { color: '#f44747', textDecoration: 'underline' },
  
  // === Markdown ===
  'heading': { color: '#0088cc', fontWeight: 'bold' },
  'emphasis': { fontStyle: 'italic' },
  'strong': { color: '#dcdcaa', fontWeight: 'bold' },
  'link': { color: '#0088cc' },
  'url': { color: '#0088cc' },
  'monospace': { color: '#7fdbca' },
  
  // === CSS Units ===
  'unit': { color: '#b5cea8' },
  
  // === JSON Labels ===
  'labelName': { color: '#9cdcfe' },
};

// איתחול syntaxColors
SYNTAX_THEMES['tech-guide-dark'].syntaxColors = TECH_GUIDE_DARK_SYNTAX;

// ייצוא
window.SYNTAX_THEMES = SYNTAX_THEMES;
window.TECH_GUIDE_DARK_SYNTAX = TECH_GUIDE_DARK_SYNTAX;
```

---

### שלב 2: יצירת המודאל

**שינויים ב-`view_file.html`:**

הוספת כפתור בתוך ה-`section-header`:

```html
<!-- בתוך div.section-header, אחרי כפתור viewModeToggleBtn -->
<button id="syntaxThemeBtn"
        type="button"
        class="btn btn-secondary btn-icon"
        title="שנה ערכת הדגשה">
  🎨 ערכה
</button>
```

הוספת המודאל לפני סגירת ה-`{% endblock content %}`:

```html
<!-- Syntax Theme Picker Modal -->
<div id="syntaxThemeModal" 
     class="syntax-theme-modal" 
     role="dialog" 
     aria-modal="true" 
     aria-labelledby="syntaxThemeModalTitle" 
     hidden>
  <div class="syntax-theme-modal__surface" role="document">
    <div class="syntax-theme-modal__header">
      <h3 id="syntaxThemeModalTitle">🎨 בחר ערכת הדגשה</h3>
      <button type="button" 
              class="syntax-theme-modal__close" 
              data-syntax-modal-close 
              aria-label="סגור">✕</button>
    </div>
    <div class="syntax-theme-modal__body">
      <p class="syntax-theme-modal__subtitle">
        בחרו את סגנון ההדגשה המועדף עליכם לתצוגת הקוד
      </p>
      <div class="syntax-theme-modal__grid" id="syntaxThemeGrid" role="listbox">
        <!-- יאוכלס דינמית -->
      </div>
    </div>
  </div>
</div>
```

---

### שלב 3: סגנונות המודאל

**הוספה ל-`view_file.html` (בתוך `{% block extra_css %}`)**:

```css
/* Syntax Theme Picker Modal */
.syntax-theme-modal {
  position: fixed;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(0, 0, 0, 0.6);
  z-index: 10000;
  padding: 1rem;
  opacity: 1;
  transition: opacity 0.15s ease;
}

.syntax-theme-modal[hidden] {
  display: none;
}

.syntax-theme-modal.is-closing {
  opacity: 0;
}

.syntax-theme-modal__surface {
  background: rgba(18, 26, 48, 0.96);
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 16px;
  width: min(440px, 100%);
  max-height: 90vh;
  padding: 1.25rem;
  display: flex;
  flex-direction: column;
  gap: 1rem;
  box-shadow: 0 20px 40px rgba(0, 0, 0, 0.4);
  transform: scale(1);
  transition: transform 0.15s ease;
}

.syntax-theme-modal.is-closing .syntax-theme-modal__surface {
  transform: scale(0.95);
}

.syntax-theme-modal__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
}

.syntax-theme-modal__header h3 {
  margin: 0;
  font-size: 1.25rem;
}

.syntax-theme-modal__close {
  border: none;
  background: transparent;
  color: rgba(255, 255, 255, 0.7);
  font-size: 1.1rem;
  cursor: pointer;
}

.syntax-theme-modal__close:hover,
.syntax-theme-modal__close:focus-visible {
  color: #fff;
}

.syntax-theme-modal__subtitle {
  margin: 0;
  font-size: 0.95rem;
  color: rgba(255, 255, 255, 0.75);
}

.syntax-theme-modal__grid {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  max-height: 50vh;
  overflow-y: auto;
}

/* Theme Card */
.syntax-theme-card {
  display: flex;
  align-items: stretch;
  gap: 1rem;
  padding: 1rem;
  border-radius: 12px;
  border: 2px solid rgba(255, 255, 255, 0.1);
  background: rgba(255, 255, 255, 0.03);
  cursor: pointer;
  transition: all 0.2s ease;
}

.syntax-theme-card:hover {
  border-color: rgba(255, 255, 255, 0.25);
  background: rgba(255, 255, 255, 0.06);
}

.syntax-theme-card:focus-visible {
  outline: 2px solid var(--primary, #569cd6);
  outline-offset: 2px;
}

.syntax-theme-card.is-active {
  border-color: var(--primary, #569cd6);
  background: rgba(86, 156, 214, 0.1);
}

.syntax-theme-card__preview {
  width: 80px;
  height: 60px;
  border-radius: 8px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  font-family: 'Fira Code', monospace;
  font-size: 9px;
  line-height: 1.4;
  padding: 6px;
  /* קוד תמיד LTR */
  direction: ltr;
  text-align: left;
}

.syntax-theme-card__info {
  flex: 1;
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 0.25rem;
}

.syntax-theme-card__name {
  font-weight: 600;
  font-size: 1rem;
}

.syntax-theme-card__desc {
  font-size: 0.85rem;
  opacity: 0.8;
}

.syntax-theme-card__check {
  align-self: center;
  width: 24px;
  height: 24px;
  border-radius: 50%;
  border: 2px solid rgba(255, 255, 255, 0.3);
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s ease;
}

.syntax-theme-card.is-active .syntax-theme-card__check {
  background: var(--primary, #569cd6);
  border-color: var(--primary, #569cd6);
}

.syntax-theme-card.is-active .syntax-theme-card__check::after {
  content: '✓';
  color: #fff;
  font-size: 14px;
}

@media (max-width: 500px) {
  .syntax-theme-modal {
    align-items: flex-end;
    padding: 0;
  }
  
  .syntax-theme-modal__surface {
    position: relative;
    width: 100%;
    max-height: 70vh;
    border-radius: 16px 16px 0 0;
    transform: translateY(0);
    animation: slideUp 0.25s ease-out;
  }
  
  .syntax-theme-modal.is-closing .syntax-theme-modal__surface {
    transform: translateY(100%);
  }
  
  @keyframes slideUp {
    from { transform: translateY(100%); }
    to { transform: translateY(0); }
  }
}
```

---

### שלב 4: לוגיקת החלפת ערכה

**קובץ חדש: `webapp/static/js/syntax-theme-picker.js`**

```javascript
/**
 * Syntax Theme Picker
 * מנהל את בחירת ערכת ההדגשה בעמוד תצוגת הקוד
 * 
 * ⚠️ תלויות:
 * - syntax-themes.js (window.SYNTAX_THEMES)
 * - codemirror.local.js (window.CodeMirror6)
 */

(function() {
  'use strict';
  
  const STORAGE_KEY = 'ck_syntax_theme';
  const DEFAULT_THEME = 'one-dark';
  const THEME_CHANGED_EVENT = 'ck:syntax-theme-changed';
  
  // State
  let currentTheme = DEFAULT_THEME;
  let modal = null;
  let grid = null;
  let triggerButton = null; // לשמירת focus בסגירה
  
  // ========================================
  // Storage & State
  // ========================================
  
  /**
   * קבלת הערכה השמורה
   */
  function getSavedTheme() {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      if (saved && window.SYNTAX_THEMES && window.SYNTAX_THEMES[saved]) {
        return saved;
      }
    } catch (_) {}
    return DEFAULT_THEME;
  }
  
  /**
   * שמירת הערכה
   */
  function saveTheme(themeId) {
    try {
      localStorage.setItem(STORAGE_KEY, themeId);
    } catch (_) {}
  }
  
  // ========================================
  // Theme Application
  // ========================================
  
  /**
   * הפעלת ערכה על CodeMirror
   */
  function applyTheme(themeId) {
    const theme = window.SYNTAX_THEMES && window.SYNTAX_THEMES[themeId];
    if (!theme) return;
    
    const CM = window.CodeMirror6;
    if (!CM) {
      console.warn('[SyntaxThemePicker] CodeMirror6 not loaded');
      return;
    }
    
    // יצירת HighlightStyle מתאים
    let highlightStyle = null;
    
    if (theme.type === 'builtin' || theme.id === 'one-dark') {
      // One Dark - משתמשים ב-oneDarkHighlightStyle המובנה
      highlightStyle = CM.oneDarkHighlightStyle || null;
    } else if (theme.type === 'custom' && theme.syntaxColors) {
      // ערכה מותאמת - יוצרים HighlightStyle דינמי
      if (CM.createDynamicHighlightStyle) {
        highlightStyle = CM.createDynamicHighlightStyle(theme.syntaxColors);
      }
    }
    
    // החלפת ה-syntax ב-view instance הפעיל (אם קיים)
    const viewInstance = window.__ck_view_cm_view;
    if (viewInstance && CM.reconfigureSyntax) {
      const success = CM.reconfigureSyntax(viewInstance, highlightStyle);
      if (success) {
        console.log('[SyntaxThemePicker] Applied theme:', themeId);
      }
    }
    
    // עדכון כפתור
    updateThemeButton();
    
    // שליחת event לרכיבים אחרים (כולל טאבים אחרים)
    dispatchThemeChangedEvent(themeId);
  }
  
  /**
   * שליחת event על שינוי ערכה
   */
  function dispatchThemeChangedEvent(themeId) {
    try {
      window.dispatchEvent(new CustomEvent(THEME_CHANGED_EVENT, {
        detail: { themeId, theme: window.SYNTAX_THEMES[themeId] }
      }));
    } catch (_) {}
  }
  
  // ========================================
  // UI Rendering
  // ========================================
  
  /**
   * יצירת תצוגה מקדימה לערכה
   */
  function createPreview(theme) {
    const preview = theme.preview || {};
    const bg = preview.background || '#1e1e1e';
    const keyword = preview.keyword || '#c678dd';
    const string = preview.string || '#98c379';
    const comment = preview.comment || '#5c6370';
    
    // dir="ltr" כדי שהקוד לא יתבלבל בממשק RTL
    return `
      <div class="syntax-theme-card__preview" dir="ltr" style="background: ${bg};">
        <span style="color: ${keyword}">def</span>
        <span style="color: #d4d4d4"> hello():</span>
        <span style="color: ${comment}">  # hi</span>
        <span style="color: ${string}">  "world"</span>
      </div>
    `;
  }
  
  /**
   * רינדור רשימת הערכות
   */
  function renderThemes() {
    if (!grid || !window.SYNTAX_THEMES) return;
    
    grid.innerHTML = '';
    
    for (const [id, theme] of Object.entries(window.SYNTAX_THEMES)) {
      const isActive = id === currentTheme;
      
      const card = document.createElement('div');
      card.className = `syntax-theme-card ${isActive ? 'is-active' : ''}`;
      card.dataset.themeId = id;
      card.setAttribute('role', 'option');
      card.setAttribute('tabindex', '0');
      card.setAttribute('aria-selected', isActive ? 'true' : 'false');
      
      card.innerHTML = `
        ${createPreview(theme)}
        <div class="syntax-theme-card__info">
          <div class="syntax-theme-card__name">${theme.name}</div>
          <div class="syntax-theme-card__desc">${theme.description}</div>
        </div>
        <div class="syntax-theme-card__check"></div>
      `;
      
      card.addEventListener('click', () => selectTheme(id));
      card.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          selectTheme(id);
        }
      });
      
      grid.appendChild(card);
    }
  }
  
  /**
   * עדכון טקסט כפתור הערכה
   */
  function updateThemeButton() {
    const btn = document.getElementById('syntaxThemeBtn');
    if (!btn) return;
    
    const theme = window.SYNTAX_THEMES && window.SYNTAX_THEMES[currentTheme];
    const name = theme ? theme.name : 'ערכה';
    
    btn.innerHTML = `🎨 ${name}`;
    btn.title = `ערכה נוכחית: ${name}`;
  }
  
  // ========================================
  // Theme Selection
  // ========================================
  
  /**
   * בחירת ערכה
   */
  function selectTheme(themeId) {
    if (!window.SYNTAX_THEMES || !window.SYNTAX_THEMES[themeId]) return;
    
    currentTheme = themeId;
    saveTheme(themeId);
    renderThemes();
    
    // הפעלת הערכה החדשה
    applyTheme(themeId);
    
    // סגירת המודאל עם אנימציה
    closeModalWithAnimation();
  }
  
  // ========================================
  // Modal Management
  // ========================================
  
  /**
   * פתיחת המודאל
   */
  function openModal() {
    if (!modal) return;
    
    // שמירת האלמנט שפתח את המודאל לצורך החזרת focus
    triggerButton = document.activeElement;
    
    modal.hidden = false;
    modal.classList.remove('is-closing');
    renderThemes();
    
    // Focus trap - התמקדות על הכרטיס הפעיל
    setTimeout(() => {
      const active = modal.querySelector('.syntax-theme-card.is-active');
      if (active) {
        active.focus();
      } else {
        const firstCard = modal.querySelector('.syntax-theme-card');
        if (firstCard) firstCard.focus();
      }
    }, 50);
  }
  
  /**
   * סגירת המודאל מיידית
   */
  function closeModal() {
    if (!modal) return;
    modal.hidden = true;
    modal.classList.remove('is-closing');
    
    // החזרת focus לכפתור שפתח את המודאל
    if (triggerButton && typeof triggerButton.focus === 'function') {
      try { triggerButton.focus(); } catch (_) {}
    }
    triggerButton = null;
  }
  
  /**
   * סגירת המודאל עם אנימציה
   */
  function closeModalWithAnimation() {
    if (!modal) return;
    
    modal.classList.add('is-closing');
    
    // המתנה לסיום האנימציה (150ms)
    setTimeout(() => {
      closeModal();
    }, 150);
  }
  
  /**
   * Focus Trap - מונע יציאה מהמודאל בטאב
   */
  function handleTabKey(e) {
    if (!modal || modal.hidden) return;
    
    const focusableElements = modal.querySelectorAll(
      'button, [tabindex]:not([tabindex="-1"])'
    );
    
    if (focusableElements.length === 0) return;
    
    const firstElement = focusableElements[0];
    const lastElement = focusableElements[focusableElements.length - 1];
    
    if (e.shiftKey && document.activeElement === firstElement) {
      e.preventDefault();
      lastElement.focus();
    } else if (!e.shiftKey && document.activeElement === lastElement) {
      e.preventDefault();
      firstElement.focus();
    }
  }
  
  // ========================================
  // Cross-Tab Sync
  // ========================================
  
  /**
   * סנכרון בין טאבים
   */
  function handleStorageChange(e) {
    if (e.key !== STORAGE_KEY) return;
    
    const newTheme = e.newValue;
    if (newTheme && window.SYNTAX_THEMES && window.SYNTAX_THEMES[newTheme]) {
      currentTheme = newTheme;
      applyTheme(newTheme);
      renderThemes(); // עדכון UI אם המודאל פתוח
    }
  }
  
  // ========================================
  // Initialization
  // ========================================
  
  /**
   * אתחול
   */
  function init() {
    modal = document.getElementById('syntaxThemeModal');
    grid = document.getElementById('syntaxThemeGrid');
    const btn = document.getElementById('syntaxThemeBtn');
    
    if (!btn) {
      // עמוד ללא כפתור ערכה - לא מאתחלים
      return;
    }
    
    // טעינת ערכה שמורה
    currentTheme = getSavedTheme();
    
    // עדכון כפתור
    updateThemeButton();
    
    // אירועי כפתור
    btn.addEventListener('click', openModal);
    
    if (modal) {
      // סגירה בלחיצה על רקע
      modal.addEventListener('click', (e) => {
        if (e.target === modal) closeModalWithAnimation();
      });
      
      // סגירה בכפתור X
      modal.querySelectorAll('[data-syntax-modal-close]').forEach((el) => {
        el.addEventListener('click', closeModalWithAnimation);
      });
      
      // מקלדת: Escape לסגירה, Tab ל-focus trap
      modal.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
          e.preventDefault();
          closeModalWithAnimation();
        } else if (e.key === 'Tab') {
          handleTabKey(e);
        }
      });
    }
    
    // סנכרון בין טאבים
    window.addEventListener('storage', handleStorageChange);
    
    // האזנה לשינויי ערכה מרכיבים אחרים
    window.addEventListener(THEME_CHANGED_EVENT, (e) => {
      const { themeId } = e.detail || {};
      if (themeId && themeId !== currentTheme) {
        currentTheme = themeId;
        updateThemeButton();
        renderThemes();
      }
    });
  }
  
  // ייצוא לשימוש חיצוני
  window.syntaxThemePicker = {
    open: openModal,
    close: closeModal,
    getCurrentTheme: () => currentTheme,
    setTheme: selectTheme,
    THEME_CHANGED_EVENT,
  };
  
  // הרצה בטעינת הדף
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
```

---

### שלב 5: אינטגרציה עם view-codemirror-toggle.js

**שינויים נדרשים ב-`view-codemirror-toggle.js`:**

> ⚠️ **חשוב:** שמירה על הפרדה בין UI theme ל-syntax theme!

```javascript
// === הוספה בראש הקובץ ===

/**
 * קבלת ערכת syntax פעילה מ-localStorage
 * נפרד מ-UI theme!
 */
function getActiveSyntaxThemeId() {
  try {
    const saved = localStorage.getItem('ck_syntax_theme');
    if (saved && window.SYNTAX_THEMES && window.SYNTAX_THEMES[saved]) {
      return saved;
    }
  } catch (_) {}
  return 'one-dark';
}

/**
 * יצירת HighlightStyle לפי ערכת syntax
 */
function getSyntaxHighlightStyle() {
  const syntaxThemeId = getActiveSyntaxThemeId();
  const CM = window.CodeMirror6;
  
  if (!CM) return null;
  
  if (syntaxThemeId === 'one-dark') {
    // One Dark - HighlightStyle מובנה
    return CM.oneDarkHighlightStyle || null;
  }
  
  // ערכה מותאמת
  const theme = window.SYNTAX_THEMES && window.SYNTAX_THEMES[syntaxThemeId];
  if (theme && theme.syntaxColors && CM.createDynamicHighlightStyle) {
    return CM.createDynamicHighlightStyle(theme.syntaxColors);
  }
  
  return null;
}

// === שינוי בפונקציה resolveEffectiveThemeForEditorParity ===
// ⚠️ פונקציה זו נשארת בלי שינוי! היא עוסקת רק ב-UI theme (רקע, גאטר וכו')
// ולא ב-syntax highlighting.

function resolveEffectiveThemeForEditorParity() {
  // לוגיקה קיימת - ללא שינוי
  try {
    const htmlTheme = document.documentElement.getAttribute('data-theme') || '';
    const t = String(htmlTheme).toLowerCase();
    if (t === 'custom') return 'custom';
    if (t === 'dark' || t === 'dim' || t === 'nebula') return 'dark';
  } catch (_) {}
  return 'dark';
}

// === שינוי בפונקציה createReadOnlyCodeMirror ===

async function createReadOnlyCodeMirror({ mountEl, docText, language }) {
  const ok = await ensureCodeMirrorLoaded();
  if (!ok) {
    throw new Error('codemirror_not_available');
  }

  const { EditorState, EditorView, languageCompartment, themeCompartment, syntaxCompartment } = window.CodeMirror6;
  const mods = (window.CodeMirror6 && window.CodeMirror6._mods) || {};
  const viewMod = mods.viewMod;

  // === UI Theme (רקע, גאטר) ===
  const uiThemeName = resolveEffectiveThemeForEditorParity();
  let themeExt = [];
  try {
    if (window.editorManager && typeof window.editorManager.getTheme === 'function') {
      themeExt = (await window.editorManager.getTheme(uiThemeName)) || [];
    }
  } catch (_) {
    themeExt = [];
  }

  // === Language Support ===
  let langSupport = [];
  try {
    if (window.editorManager && typeof window.editorManager.getLanguageSupport === 'function') {
      langSupport = (await window.editorManager.getLanguageSupport(language)) || [];
    }
  } catch (_) {
    langSupport = [];
  }

  // === Syntax Highlighting (נפרד מ-UI theme!) ===
  const syntaxHighlightStyle = getSyntaxHighlightStyle();
  let syntaxExt = [];
  if (syntaxHighlightStyle && window.CodeMirror6.syntaxHighlighting) {
    syntaxExt = [window.CodeMirror6.syntaxHighlighting(syntaxHighlightStyle)];
  }

  // === בניית Extensions ===
  const extensions = [
    ...(window.CodeMirror6.basicSetup || []),
    languageCompartment ? languageCompartment.of(langSupport || []) : (langSupport || []),
    themeCompartment ? themeCompartment.of(themeExt || []) : (themeExt || []),
    // Syntax Highlighting - ב-compartment נפרד לאפשר החלפה דינמית
    syntaxCompartment ? syntaxCompartment.of(syntaxExt) : syntaxExt,
    EditorView.lineWrapping,
    EditorState.readOnly.of(true),
    (viewMod && viewMod.EditorView && viewMod.EditorView.editable) 
      ? viewMod.EditorView.editable.of(false) 
      : EditorView.editable.of(false),
  ];

  const state = EditorState.create({
    doc: docText || '',
    extensions,
  });

  const view = new EditorView({ state, parent: mountEl });
  
  // שמירת ה-view instance לשימוש ע"י syntax-theme-picker
  window.__ck_view_cm_view = view;
  
  return view;
}

// === האזנה לשינויי syntax theme ===
// מוסיפים בסוף הקובץ, בתוך ready() או ב-init

window.addEventListener('ck:syntax-theme-changed', (e) => {
  // ה-syntax-theme-picker כבר מטפל בעדכון ה-view
  // אפשר להוסיף כאן לוגיקה נוספת אם צריך
});
```

---

### שלב 6: סדר טעינת הקבצים

> ⚠️ **קריטי:** סדר הטעינה חשוב לתפקוד תקין!

**ב-`view_file.html`, בתוך `{% block extra_js %}`:**

```html
{% block extra_js %}
<!-- 1. הגדרות ערכות (חייב להיות ראשון) -->
<script src="{{ url_for('static', filename='js/syntax-themes.js') }}?v={{ static_version }}" defer></script>

<!-- 2. לוגיקת המודאל (תלוי ב-syntax-themes.js) -->
<script src="{{ url_for('static', filename='js/syntax-theme-picker.js') }}?v={{ static_version }}" defer></script>

<!-- 3. לוגיקת CodeMirror toggle (תלוי ב-syntax-themes.js) -->
<script src="{{ url_for('static', filename='js/view-codemirror-toggle.js') }}?v={{ static_version }}" defer></script>
{% endblock %}
```

**דיאגרמת תלויות:**

```
┌─────────────────────┐
│   syntax-themes.js  │  ← חייב להיטען ראשון
│   (SYNTAX_THEMES)   │
└──────────┬──────────┘
           │
     ┌─────┴─────┐
     ▼           ▼
┌─────────────┐  ┌──────────────────────┐
│ syntax-     │  │ view-codemirror-     │
│ theme-      │  │ toggle.js            │
│ picker.js   │  │                      │
└─────────────┘  └──────────────────────┘
           │                │
           └────────┬───────┘
                    ▼
           ┌─────────────────┐
           │ codemirror.     │
           │ local.js        │  ← נטען ע"י editor-manager
           │ (CodeMirror6)   │
           └─────────────────┘
```

---

## מיפוי צבעים: Tech Guide Dark

### מיפוי VS Code Scopes ל-CodeMirror Tags

טבלת המיפוי המלאה מבוססת על ה-JSON מה-PR:

| VS Code Scope | CodeMirror Tag | צבע | סגנון |
|---------------|----------------|-----|-------|
| `comment` | `comment` | `#6a9955` | italic |
| `keyword` | `keyword` | `#c586c0` | - |
| `keyword.control` | `controlKeyword` | `#c586c0` | - |
| `storage.type` | `definitionKeyword` | `#c586c0` | - |
| `string` | `string` | `#ce9178` | - |
| `constant.numeric` | `number` | `#b5cea8` | - |
| `constant.language.boolean` | `bool` | `#b5cea8` | - |
| `variable` | `variableName` | `#9cdcfe` | - |
| `variable.parameter` | `local(variableName)` | `#9cdcfe` | italic |
| `entity.name.function` | `function(definition(variableName))` | `#dcdcaa` | - |
| `support.function` | `function(variableName)` | `#dcdcaa` | - |
| `entity.name.class` | `definition(className)` | `#4ec9b0` | - |
| `entity.name.type` | `typeName` | `#4ec9b0` | - |
| `keyword.operator` | `operator` | `#d4d4d4` | - |
| `punctuation` | `punctuation` | `#d4d4d4` | - |
| `entity.name.tag` | `tagName` | `#569cd6` | - |
| `entity.other.attribute-name` | `attributeName` | `#9cdcfe` | - |
| `string.regexp` | `regexp` | `#d16969` | - |
| `constant.character.escape` | `escape` | `#d7ba7d` | - |
| `markup.heading` | `heading` | `#0088cc` | bold |
| `markup.bold` | `strong` | `#dcdcaa` | bold |
| `markup.italic` | `emphasis` | - | italic |
| `markup.underline.link` | `link` | `#0088cc` | - |
| `markup.inline.raw` | `monospace` | `#7fdbca` | - |
| `support.type.property-name.css` | `propertyName` | `#9cdcfe` | - |
| `keyword.other.unit.css` | `unit` | `#b5cea8` | - |
| `support.type.property-name.json` | `labelName` | `#9cdcfe` | - |

---

## ערכת One Dark

ערכת One Dark מובנית ב-CodeMirror ונמצאת ב-`codemirror.local.js`:

```javascript
var oneDarkHighlightStyle = HighlightStyle.define([
  { tag: tags.keyword, color: "#c678dd" },
  { tag: tags.operator, color: "#abb2bf" },
  { tag: tags.string, color: "#98c379" },
  { tag: tags.comment, color: "#5c6370", fontStyle: "italic" },
  { tag: tags.function(tags.variableName), color: "#61afef" },
  { tag: tags.number, color: "#d19a66" },
  { tag: tags.typeName, color: "#e5c07b" },
  // ... ועוד
]);
```

אין צורך לממש אותה מחדש - היא זמינה דרך `window.CodeMirror6.oneDarkHighlightStyle`.

---

## בדיקות

### בדיקות ידניות

1. **פתיחת המודאל:**
   - לחיצה על כפתור "🎨 ערכה" פותחת את המודאל
   - המודאל מציג את שתי הערכות
   - הערכה הפעילה מסומנת
   - Focus נמצא על הכרטיס הפעיל

2. **החלפת ערכה:**
   - לחיצה על ערכה אחרת מחליפה אותה
   - **הקוד מתעדכן מיידית** (לא צריך רענון!)
   - ההעדפה נשמרת ב-localStorage
   - המודאל נסגר עם אנימציה

3. **שמירת העדפה:**
   - רענון העמוד שומר את הערכה שנבחרה
   - מעבר לעמוד קובץ אחר שומר את הערכה

4. **סנכרון בין טאבים:**
   - פתיחת עמוד קובץ בטאב חדש
   - שינוי ערכה בטאב אחד
   - הטאב השני מתעדכן אוטומטית

5. **רספונסיביות:**
   - במובייל המודאל עולה מלמטה (bottom sheet)
   - בדסקטופ המודאל ממורכז

6. **נגישות:**
   - ניווט במקלדת עובד (Tab, Enter, Escape)
   - Focus trap פעיל במודאל
   - Focus חוזר לכפתור בסגירה

### בדיקות אוטומטיות

```python
# tests/test_syntax_theme_picker.py (לדוגמה)

def test_syntax_themes_no_duplicate_keys():
    """וידוא שאין keys כפולים ב-TECH_GUIDE_DARK_SYNTAX"""
    # פרסור syntax-themes.js
    # בדיקה שכל key מופיע פעם אחת
    pass

def test_syntax_themes_defined():
    """וידוא שכל הערכות מוגדרות עם השדות הנדרשים"""
    # בדיקה שהקובץ syntax-themes.js קיים
    # בדיקה שיש לפחות 2 ערכות
    # בדיקה שלכל ערכה יש id, name, description, preview
    pass

def test_tech_guide_dark_colors():
    """וידוא שהצבעים של Tech Guide Dark תואמים ל-JSON"""
    expected = {
        'comment': '#6a9955',
        'keyword': '#c586c0',
        'string': '#ce9178',
        # ...
    }
    # בדיקה שהמיפוי ב-TECH_GUIDE_DARK_SYNTAX תואם
    pass

def test_codemirror_syntax_compartment_exists():
    """וידוא ש-syntaxCompartment קיים ב-codemirror.local.js"""
    # בדיקה שהקוד מייצא syntaxCompartment
    # בדיקה ש-reconfigureSyntax קיים
    pass
```

---

## נספחים

### נספח א׳: JSON מלא של Tech Guide Dark

ה-JSON המלא מה-PR נמצא בתיאור ה-PR. להלן המיפוי המרכזי של `tokenColors`:

```json
{
  "tokenColors": [
    { "scope": "comment", "settings": { "foreground": "#6a9955", "fontStyle": "italic" } },
    { "scope": "keyword", "settings": { "foreground": "#c586c0" } },
    { "scope": "storage", "settings": { "foreground": "#c586c0" } },
    { "scope": "string", "settings": { "foreground": "#ce9178" } },
    { "scope": "constant.numeric", "settings": { "foreground": "#b5cea8" } },
    { "scope": "variable", "settings": { "foreground": "#9cdcfe" } },
    { "scope": "entity.name.function", "settings": { "foreground": "#dcdcaa" } },
    { "scope": "entity.name.class", "settings": { "foreground": "#4ec9b0" } },
    { "scope": "entity.name.type", "settings": { "foreground": "#4ec9b0" } },
    { "scope": "entity.name.tag", "settings": { "foreground": "#569cd6" } },
    { "scope": "entity.other.attribute-name", "settings": { "foreground": "#9cdcfe" } }
  ]
}
```

### נספח ב׳: סיכום קבצים לשינוי/יצירה

| קובץ | פעולה | תיאור |
|------|-------|-------|
| `webapp/static/js/codemirror.local.js` | עריכה | הוספת `syntaxCompartment` ו-`reconfigureSyntax` |
| `webapp/templates/view_file.html` | עריכה | הוספת כפתור, מודאל, CSS, וטעינת scripts |
| `webapp/static/js/syntax-themes.js` | יצירה | הגדרת ערכות ההדגשה |
| `webapp/static/js/syntax-theme-picker.js` | יצירה | לוגיקת המודאל |
| `webapp/static/js/view-codemirror-toggle.js` | עריכה | אינטגרציה עם syntax themes |

### נספח ג׳: קישורים רלוונטיים

- [מדריך ערכות מותאמות](../docs/webapp/custom_themes_guide.rst)
- [מיפוי VS Code ל-CodeMirror](../services/theme_parser_service.py)
- [תיעוד CodeMirror HighlightStyle](https://codemirror.net/docs/ref/#language.HighlightStyle)
- [תיעוד CodeMirror Compartment](https://codemirror.net/docs/ref/#state.Compartment)

### נספח ד׳: טיפול בבעיות נפוצות

#### הקוד לא מתעדכן בהחלפת ערכה

**בעיה:** בחרתי ערכה חדשה אבל הצבעים לא השתנו.

**פתרון:** וודא ש:
1. `syntaxCompartment` קיים ב-`codemirror.local.js`
2. `reconfigureSyntax` מיוצא ב-`window.CodeMirror6`
3. `window.__ck_view_cm_view` מאותחל בזמן יצירת ה-view

#### ערכה לא נשמרת בין רענונים

**בעיה:** אחרי רענון העמוד, חוזרת ערכת ברירת המחדל.

**פתרון:** וודא ש-`localStorage` עובד (לא פרטי/incognito) ושהקוד קורא מ-`getSavedTheme()` בזמן init.

#### תצוגה מקדימה (Preview) הפוכה

**בעיה:** הקוד ב-preview מוצג מימין לשמאל.

**פתרון:** וודא שיש `dir="ltr"` על ה-preview element.

---

## סיכום

המדריך הזה מתאר את כל השלבים הנדרשים למימוש הפיצ'ר של שינוי הדגשת תחביר בעמוד תצוגת הקוד.

### נקודות מפתח:

1. **הפרדת Compartments** - `themeCompartment` לעיצוב עורך, `syntaxCompartment` להדגשת תחביר
2. **הפרדת Concerns** - UI theme (data-theme) נפרד מ-syntax theme (localStorage)
3. **תקשורת ע"י Events** - `ck:syntax-theme-changed` לסנכרון בין רכיבים
4. **סדר טעינה** - syntax-themes.js → syntax-theme-picker.js → view-codemirror-toggle.js

### המימוש כולל:

- **UI** - כפתור ומודאל עם אנימציות ונגישות
- **לוגיקה** - ניהול מצב, שמירת העדפות, סנכרון בין טאבים
- **אינטגרציה** - חיבור ל-CodeMirror עם החלפה דינמית
- **ערכות** - Tech Guide Dark מותאמת + One Dark מובנית
