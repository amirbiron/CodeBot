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
   - [שלב 1: הגדרת ערכות ההדגשה](#שלב-1-הגדרת-ערכות-ההדגשה)
   - [שלב 2: יצירת המודאל](#שלב-2-יצירת-המודאל)
   - [שלב 3: לוגיקת החלפת ערכה](#שלב-3-לוגיקת-החלפת-ערכה)
   - [שלב 4: אינטגרציה עם CodeMirror](#שלב-4-אינטגרציה-עם-codemirror)
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

### רספונסיביות

- במובייל: המודאל יוצג כ-bottom sheet
- בדסקטופ: מודאל ממורכז רגיל

---

## שלבי מימוש

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
const TECH_GUIDE_DARK_SYNTAX = {
  // Comments
  'comment': { color: '#6a9955', fontStyle: 'italic' },
  'docComment': { color: '#6a9955', fontStyle: 'italic' },
  
  // Keywords
  'keyword': { color: '#c586c0' },
  'controlKeyword': { color: '#c586c0' },
  'moduleKeyword': { color: '#c586c0' },
  'definitionKeyword': { color: '#c586c0' },
  
  // Storage (def, class, function)
  'typeName': { color: '#4ec9b0' },
  'className': { color: '#4ec9b0' },
  'definition(className)': { color: '#4ec9b0' },
  'namespace': { color: '#4ec9b0' },
  
  // Strings
  'string': { color: '#ce9178' },
  'string2': { color: '#ce9178' },
  
  // Numbers and Constants
  'number': { color: '#b5cea8' },
  'bool': { color: '#b5cea8' },
  'atom': { color: '#b5cea8' },
  'literal': { color: '#b5cea8' },
  
  // Variables
  'variableName': { color: '#9cdcfe' },
  'local(variableName)': { color: '#9cdcfe', fontStyle: 'italic' },
  'definition(variableName)': { color: '#9cdcfe' },
  'self': { color: '#9cdcfe' },
  
  // Functions
  'function(variableName)': { color: '#dcdcaa' },
  'function(definition(variableName))': { color: '#dcdcaa' },
  'standard(function(variableName))': { color: '#dcdcaa' },
  
  // Operators and Punctuation
  'operator': { color: '#d4d4d4' },
  'punctuation': { color: '#d4d4d4' },
  
  // Properties
  'propertyName': { color: '#9cdcfe' },
  'definition(propertyName)': { color: '#9cdcfe' },
  
  // HTML/XML
  'tagName': { color: '#569cd6' },
  'attributeName': { color: '#9cdcfe' },
  'attributeValue': { color: '#ce9178' },
  'angleBracket': { color: '#808080' },
  
  // Regex
  'regexp': { color: '#d16969' },
  'escape': { color: '#d7ba7d' },
  
  // Special
  'meta': { color: '#c586c0' },
  'invalid': { color: '#f44747', textDecoration: 'underline' },
  
  // Markdown
  'heading': { color: '#0088cc', fontWeight: 'bold' },
  'emphasis': { fontStyle: 'italic' },
  'strong': { color: '#dcdcaa', fontWeight: 'bold' },
  'link': { color: '#0088cc' },
  'url': { color: '#0088cc' },
  'monospace': { color: '#7fdbca' },
  
  // CSS
  'propertyName': { color: '#9cdcfe' },
  'unit': { color: '#b5cea8' },
  
  // JSON
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
  <div class="syntax-theme-modal__surface">
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
      <div class="syntax-theme-modal__grid" id="syntaxThemeGrid">
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
}

.syntax-theme-modal[hidden] {
  display: none;
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
  .syntax-theme-modal__surface {
    position: fixed;
    bottom: 0;
    left: 0;
    right: 0;
    width: 100%;
    max-height: 70vh;
    border-radius: 16px 16px 0 0;
    animation: slideUp 0.25s ease-out;
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
 */

(function() {
  'use strict';
  
  const STORAGE_KEY = 'ck_syntax_theme';
  const DEFAULT_THEME = 'one-dark';
  
  // State
  let currentTheme = DEFAULT_THEME;
  let modal = null;
  let grid = null;
  
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
  
  /**
   * יצירת תצוגה מקדימה לערכה
   */
  function createPreview(theme) {
    const preview = theme.preview || {};
    const bg = preview.background || '#1e1e1e';
    const keyword = preview.keyword || '#c678dd';
    const string = preview.string || '#98c379';
    const comment = preview.comment || '#5c6370';
    
    return `
      <div class="syntax-theme-card__preview" style="background: ${bg};">
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
      card.setAttribute('role', 'button');
      card.setAttribute('tabindex', '0');
      card.setAttribute('aria-pressed', isActive ? 'true' : 'false');
      
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
   * בחירת ערכה
   */
  function selectTheme(themeId) {
    if (!window.SYNTAX_THEMES || !window.SYNTAX_THEMES[themeId]) return;
    
    currentTheme = themeId;
    saveTheme(themeId);
    renderThemes();
    
    // הפעלת הערכה החדשה
    applyTheme(themeId);
    
    // סגירת המודאל אחרי עיכוב קצר
    setTimeout(() => closeModal(), 200);
  }
  
  /**
   * הפעלת ערכה על CodeMirror
   */
  function applyTheme(themeId) {
    const theme = window.SYNTAX_THEMES[themeId];
    if (!theme) return;
    
    // עדכון משתנה גלובלי שישמש את CodeMirror
    window.__ck_active_syntax_theme = themeId;
    
    // אם יש view instance פעיל, נרענן אותו
    const viewInstance = window.__ck_view_cm_view;
    if (viewInstance && window.CodeMirror6) {
      try {
        reloadCodeMirrorWithTheme(viewInstance, theme);
      } catch (err) {
        console.error('[SyntaxThemePicker] Failed to apply theme:', err);
      }
    }
    
    // עדכון כפתור הערכה
    updateThemeButton();
  }
  
  /**
   * טעינה מחדש של CodeMirror עם הערכה החדשה
   */
  function reloadCodeMirrorWithTheme(view, theme) {
    const CM = window.CodeMirror6;
    if (!CM || !CM.themeCompartment) {
      console.warn('[SyntaxThemePicker] CodeMirror6 not fully loaded');
      return;
    }
    
    let themeExt = [];
    let syntaxExt = [];
    
    if (theme.type === 'builtin' || theme.id === 'one-dark') {
      // ערכת One Dark מובנית
      if (CM.oneDark) {
        themeExt = CM.oneDark;
      }
    } else if (theme.type === 'custom' && theme.syntaxColors) {
      // ערכה מותאמת
      if (CM.createDynamicHighlightStyle) {
        const dynamicStyle = CM.createDynamicHighlightStyle(theme.syntaxColors);
        if (dynamicStyle && CM.syntaxHighlighting) {
          syntaxExt = [CM.syntaxHighlighting(dynamicStyle)];
        }
      }
    }
    
    // החלפת ה-compartment
    if (CM.themeCompartment && view.dispatch) {
      view.dispatch({
        effects: CM.themeCompartment.reconfigure(themeExt)
      });
    }
    
    // אם יש syntax extension חדש, נצטרך ליצור state חדש
    // (זה מורכב יותר, לכן בגרסה ראשונה נעשה reload)
    if (syntaxExt.length > 0) {
      // Trigger re-render by dispatching empty transaction
      view.dispatch({});
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
  
  /**
   * פתיחת המודאל
   */
  function openModal() {
    if (!modal) return;
    modal.hidden = false;
    renderThemes();
    
    // Focus על הכרטיס הפעיל
    setTimeout(() => {
      const active = modal.querySelector('.syntax-theme-card.is-active');
      if (active) active.focus();
    }, 100);
  }
  
  /**
   * סגירת המודאל
   */
  function closeModal() {
    if (!modal) return;
    modal.hidden = true;
  }
  
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
    window.__ck_active_syntax_theme = currentTheme;
    
    // עדכון כפתור
    updateThemeButton();
    
    // אירועים
    btn.addEventListener('click', openModal);
    
    if (modal) {
      // סגירה בלחיצה על רקע
      modal.addEventListener('click', (e) => {
        if (e.target === modal) closeModal();
      });
      
      // סגירה בכפתור X
      modal.querySelectorAll('[data-syntax-modal-close]').forEach((el) => {
        el.addEventListener('click', closeModal);
      });
      
      // סגירה ב-Escape
      document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && !modal.hidden) {
          e.preventDefault();
          closeModal();
        }
      });
    }
  }
  
  // ייצוא לשימוש חיצוני
  window.syntaxThemePicker = {
    open: openModal,
    close: closeModal,
    getCurrentTheme: () => currentTheme,
    setTheme: selectTheme,
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

```javascript
// הוספה בראש הקובץ
function getActiveSyntaxTheme() {
  return window.__ck_active_syntax_theme || 'one-dark';
}

// שינוי בפונקציה resolveEffectiveThemeForEditorParity
function resolveEffectiveThemeForEditorParity() {
  // בדיקת ערכת syntax פעילה
  const syntaxTheme = getActiveSyntaxTheme();
  
  // אם נבחרה ערכה מותאמת (לא one-dark) - נחזיר 'custom'
  if (syntaxTheme && syntaxTheme !== 'one-dark') {
    return 'custom';
  }
  
  // לוגיקה קיימת
  const htmlTheme = document.documentElement.getAttribute('data-theme');
  if (htmlTheme === 'custom') return 'custom';
  if (['dark', 'dim', 'nebula'].includes(htmlTheme)) return 'dark';
  return 'dark';
}

// עדכון createReadOnlyCodeMirror
async function createReadOnlyCodeMirror({ mountEl, docText, language }) {
  // ... קוד קיים ...
  
  // הוספת תמיכה בערכת syntax מותאמת
  const syntaxTheme = getActiveSyntaxTheme();
  let customSyntaxHighlighter = null;
  
  if (syntaxTheme !== 'one-dark' && window.SYNTAX_THEMES) {
    const theme = window.SYNTAX_THEMES[syntaxTheme];
    if (theme && theme.syntaxColors && window.CodeMirror6.createDynamicHighlightStyle) {
      const dynamicStyle = window.CodeMirror6.createDynamicHighlightStyle(theme.syntaxColors);
      if (dynamicStyle && window.CodeMirror6.syntaxHighlighting) {
        customSyntaxHighlighter = window.CodeMirror6.syntaxHighlighting(dynamicStyle);
      }
    }
  } else if (themeName === 'custom' && window.CodeMirror6.getSyntaxHighlighter) {
    // לוגיקה קיימת לערכות custom מהמערכת
    customSyntaxHighlighter = window.CodeMirror6.getSyntaxHighlighter();
  }
  
  // ... המשך קוד קיים ...
}
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

אין צורך לממש אותה מחדש - היא זמינה דרך `window.CodeMirror6.oneDark`.

---

## בדיקות

### בדיקות ידניות

1. **פתיחת המודאל:**
   - לחיצה על כפתור "🎨 ערכה" פותחת את המודאל
   - המודאל מציג את שתי הערכות
   - הערכה הפעילה מסומנת

2. **החלפת ערכה:**
   - לחיצה על ערכה אחרת מחליפה אותה
   - הקוד מתעדכן מיידית
   - ההעדפה נשמרת ב-localStorage

3. **שמירת העדפה:**
   - רענון העמוד שומר את הערכה שנבחרה
   - מעבר לעמוד קובץ אחר שומר את הערכה

4. **רספונסיביות:**
   - במובייל המודאל עולה מלמטה (bottom sheet)
   - בדסקטופ המודאל ממורכז

### בדיקות אוטומטיות

```python
# tests/test_syntax_theme_picker.py (לדוגמה)

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
| `webapp/templates/view_file.html` | עריכה | הוספת כפתור ומודאל |
| `webapp/static/js/syntax-themes.js` | יצירה | הגדרת הערכות |
| `webapp/static/js/syntax-theme-picker.js` | יצירה | לוגיקת המודאל |
| `webapp/static/js/view-codemirror-toggle.js` | עריכה | אינטגרציה |

### נספח ג׳: קישורים רלוונטיים

- [מדריך ערכות מותאמות](../docs/webapp/custom_themes_guide.rst)
- [מיפוי VS Code ל-CodeMirror](../services/theme_parser_service.py)
- [תיעוד CodeMirror HighlightStyle](https://codemirror.net/docs/ref/#language.HighlightStyle)

---

## סיכום

המדריך הזה מתאר את כל השלבים הנדרשים למימוש הפיצ'ר של שינוי הדגשת תחביר בעמוד תצוגת הקוד. המימוש כולל:

1. **UI** - כפתור ומודאל לבחירת ערכה
2. **לוגיקה** - ניהול מצב ושמירת העדפות
3. **אינטגרציה** - חיבור ל-CodeMirror הקיים
4. **ערכות** - Tech Guide Dark מותאמת + One Dark מובנית

המימוש משתמש בתשתית הקיימת ואינו דורש שינויים מבניים גדולים.
