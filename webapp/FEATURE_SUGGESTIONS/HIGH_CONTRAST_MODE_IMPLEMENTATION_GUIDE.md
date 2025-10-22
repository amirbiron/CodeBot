# מדריך מימוש מצב ניגודיות גבוהה (High Contrast Mode) 🎨

## סקירה כללית

מצב ניגודיות גבוהה הוא תכונת נגישות חיונית שמשפרת את קריאות הטקסט והאלמנטים החזותיים עבור משתמשים עם לקויות ראייה או רגישות לאור. המדריך הזה מפרט איך לממש את התכונה בצורה מקיפה ונגישה.

## יעדים עיקריים

- ✅ **ניגודיות מקסימלית**: שחור/לבן טהור במקום גווני אפור
- ✅ **מסגרות בולטות**: גבולות ברורים וחדים בין אלמנטים
- ✅ **צבעי syntax בהירים**: הבחנה ברורה בין סוגי קוד שונים
- ✅ **תמיכה במערכת**: זיהוי אוטומטי של העדפות מערכת
- ✅ **שמירת העדפות**: זכירת בחירת המשתמש

## 1. מבנה CSS למצב High Contrast

### 1.1 הגדרת משתני CSS בסיסיים

```css
/* webapp/static/css/high-contrast.css */

:root {
  /* צבעי בסיס רגילים */
  --bg-primary: #ffffff;
  --bg-secondary: #f5f5f5;
  --text-primary: #212121;
  --text-secondary: #757575;
  --border-color: #e0e0e0;
  --link-color: #1976d2;
  --link-hover: #1565c0;
  
  /* צבעי הדגשה */
  --success-color: #4caf50;
  --warning-color: #ff9800;
  --error-color: #f44336;
  --info-color: #2196f3;
}

/* מצב High Contrast */
[data-theme="high-contrast"] {
  /* צבעי בסיס - שחור/לבן טהור */
  --bg-primary: #000000;
  --bg-secondary: #000000;
  --text-primary: #ffffff;
  --text-secondary: #ffffff;
  --border-color: #ffffff;
  --link-color: #ffff00;
  --link-hover: #ffcc00;
  
  /* צבעי הדגשה בניגודיות גבוהה */
  --success-color: #00ff00;
  --warning-color: #ffff00;
  --error-color: #ff0000;
  --info-color: #00ffff;
  
  /* משתנים נוספים למצב High Contrast */
  --border-width: 2px;
  --focus-outline-width: 3px;
  --focus-outline-color: #ffff00;
  --selection-bg: #ffff00;
  --selection-text: #000000;
}
```

### 1.2 סגנונות בסיסיים

```css
/* החלת המשתנים על אלמנטים בסיסיים */
body {
  background-color: var(--bg-primary);
  color: var(--text-primary);
  transition: background-color 0.3s ease, color 0.3s ease;
}

a {
  color: var(--link-color);
  text-decoration: underline;
}

a:hover,
a:focus {
  color: var(--link-hover);
  text-decoration: underline;
  outline: var(--focus-outline-width) solid var(--focus-outline-color);
  outline-offset: 2px;
}

/* מסגרות בולטות במצב High Contrast */
[data-theme="high-contrast"] * {
  border-color: var(--border-color) !important;
}

[data-theme="high-contrast"] button,
[data-theme="high-contrast"] input,
[data-theme="high-contrast"] textarea,
[data-theme="high-contrast"] select,
[data-theme="high-contrast"] .card,
[data-theme="high-contrast"] .panel {
  border: var(--border-width) solid var(--border-color);
}

/* הדגשת פוקוס חזקה */
[data-theme="high-contrast"] *:focus {
  outline: var(--focus-outline-width) solid var(--focus-outline-color) !important;
  outline-offset: 2px;
}

/* טקסט נבחר */
[data-theme="high-contrast"] ::selection {
  background-color: var(--selection-bg);
  color: var(--selection-text);
}
```

## 2. צבעי Syntax Highlighting בניגודיות גבוהה

### 2.1 הגדרות CodeMirror

```css
/* צבעי syntax למצב High Contrast */
[data-theme="high-contrast"] .cm-editor {
  background-color: #000000;
  color: #ffffff;
}

[data-theme="high-contrast"] .cm-editor .cm-line {
  caret-color: #ffff00;
}

/* מילות מפתח */
[data-theme="high-contrast"] .cm-keyword {
  color: #ff00ff !important;
  font-weight: bold;
}

/* מחרוזות */
[data-theme="high-contrast"] .cm-string {
  color: #00ff00 !important;
}

/* הערות */
[data-theme="high-contrast"] .cm-comment {
  color: #00ffff !important;
  font-style: italic;
}

/* מספרים */
[data-theme="high-contrast"] .cm-number {
  color: #ffff00 !important;
}

/* פונקציות */
[data-theme="high-contrast"] .cm-function {
  color: #ff9900 !important;
  font-weight: bold;
}

/* משתנים */
[data-theme="high-contrast"] .cm-variable {
  color: #ffffff !important;
}

/* שגיאות */
[data-theme="high-contrast"] .cm-error {
  background-color: #ff0000;
  color: #000000;
  text-decoration: underline wavy;
}
```

### 2.2 הגדרות Prism.js (אם בשימוש)

```css
[data-theme="high-contrast"] code[class*="language-"],
[data-theme="high-contrast"] pre[class*="language-"] {
  background: #000000;
  color: #ffffff;
}

[data-theme="high-contrast"] .token.keyword {
  color: #ff00ff;
  font-weight: bold;
}

[data-theme="high-contrast"] .token.string {
  color: #00ff00;
}

[data-theme="high-contrast"] .token.comment {
  color: #00ffff;
  font-style: italic;
}

[data-theme="high-contrast"] .token.number {
  color: #ffff00;
}

[data-theme="high-contrast"] .token.function {
  color: #ff9900;
  font-weight: bold;
}

[data-theme="high-contrast"] .token.operator {
  color: #ff00ff;
}

[data-theme="high-contrast"] .token.punctuation {
  color: #ffffff;
}
```

## 3. JavaScript לניהול המצב

### 3.1 מנהל Theme

```javascript
// webapp/static/js/theme-manager.js

class ThemeManager {
  constructor() {
    this.STORAGE_KEY = 'webapp-theme-preference';
    this.THEMES = {
      LIGHT: 'light',
      DARK: 'dark',
      HIGH_CONTRAST: 'high-contrast',
      AUTO: 'auto'
    };
    
    this.init();
  }
  
  init() {
    // בדיקת העדפת משתמש שמורה
    const savedTheme = this.getSavedTheme();
    
    if (savedTheme === this.THEMES.AUTO) {
      this.detectSystemPreference();
    } else if (savedTheme) {
      this.applyTheme(savedTheme);
    } else {
      // ברירת מחדל - בדיקת העדפת מערכת
      this.detectSystemPreference();
    }
    
    // האזנה לשינויי העדפות מערכת
    this.watchSystemPreferences();
    
    // הוספת כפתור החלפת מצב
    this.createThemeToggle();
  }
  
  getSavedTheme() {
    return localStorage.getItem(this.STORAGE_KEY);
  }
  
  saveTheme(theme) {
    localStorage.setItem(this.STORAGE_KEY, theme);
  }
  
  applyTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    
    // עדכון meta tags לנגישות
    this.updateMetaTags(theme);
    
    // שידור אירוע לרכיבים אחרים
    window.dispatchEvent(new CustomEvent('themeChanged', { 
      detail: { theme } 
    }));
  }
  
  detectSystemPreference() {
    // בדיקת העדפת ניגודיות גבוהה במערכת
    if (window.matchMedia('(prefers-contrast: high)').matches) {
      this.applyTheme(this.THEMES.HIGH_CONTRAST);
      return;
    }
    
    // בדיקת מצב כהה
    if (window.matchMedia('(prefers-color-scheme: dark)').matches) {
      this.applyTheme(this.THEMES.DARK);
      return;
    }
    
    // ברירת מחדל - מצב בהיר
    this.applyTheme(this.THEMES.LIGHT);
  }
  
  watchSystemPreferences() {
    // האזנה לשינויי ניגודיות
    const contrastQuery = window.matchMedia('(prefers-contrast: high)');
    contrastQuery.addEventListener('change', (e) => {
      if (this.getSavedTheme() === this.THEMES.AUTO) {
        if (e.matches) {
          this.applyTheme(this.THEMES.HIGH_CONTRAST);
        } else {
          this.detectSystemPreference();
        }
      }
    });
    
    // האזנה לשינויי צבע
    const colorQuery = window.matchMedia('(prefers-color-scheme: dark)');
    colorQuery.addEventListener('change', () => {
      if (this.getSavedTheme() === this.THEMES.AUTO) {
        this.detectSystemPreference();
      }
    });
  }
  
  updateMetaTags(theme) {
    // עדכון meta tag לצבע theme
    let themeColor = '#ffffff';
    if (theme === this.THEMES.DARK) {
      themeColor = '#1a1a1a';
    } else if (theme === this.THEMES.HIGH_CONTRAST) {
      themeColor = '#000000';
    }
    
    let metaThemeColor = document.querySelector('meta[name="theme-color"]');
    if (!metaThemeColor) {
      metaThemeColor = document.createElement('meta');
      metaThemeColor.name = 'theme-color';
      document.head.appendChild(metaThemeColor);
    }
    metaThemeColor.content = themeColor;
  }
  
  createThemeToggle() {
    // יצירת כפתור החלפת מצב
    const toggleContainer = document.createElement('div');
    toggleContainer.className = 'theme-toggle-container';
    toggleContainer.innerHTML = `
      <button 
        id="theme-toggle" 
        class="theme-toggle-btn"
        aria-label="החלף מצב תצוגה"
        title="החלף מצב תצוגה">
        <span class="theme-icon"></span>
        <span class="theme-label">מצב תצוגה</span>
      </button>
      <div id="theme-menu" class="theme-menu" role="menu" hidden>
        <button role="menuitem" data-theme="light">
          ☀️ מצב בהיר
        </button>
        <button role="menuitem" data-theme="dark">
          🌙 מצב כהה
        </button>
        <button role="menuitem" data-theme="high-contrast">
          ⚡ ניגודיות גבוהה
        </button>
        <button role="menuitem" data-theme="auto">
          🔄 אוטומטי
        </button>
      </div>
    `;
    
    // הוספה לדף
    document.body.appendChild(toggleContainer);
    
    // הוספת אירועים
    this.setupToggleEvents();
  }
  
  setupToggleEvents() {
    const toggleBtn = document.getElementById('theme-toggle');
    const menu = document.getElementById('theme-menu');
    
    // פתיחה/סגירה של התפריט
    toggleBtn.addEventListener('click', () => {
      const isOpen = !menu.hidden;
      menu.hidden = isOpen;
      toggleBtn.setAttribute('aria-expanded', !isOpen);
      
      if (!isOpen) {
        // מיקוד על האופציה הנוכחית
        const currentTheme = this.getSavedTheme() || 'auto';
        const currentOption = menu.querySelector(`[data-theme="${currentTheme}"]`);
        if (currentOption) currentOption.focus();
      }
    });
    
    // בחירת theme
    menu.querySelectorAll('[data-theme]').forEach(btn => {
      btn.addEventListener('click', () => {
        const theme = btn.dataset.theme;
        
        if (theme === this.THEMES.AUTO) {
          this.saveTheme(this.THEMES.AUTO);
          this.detectSystemPreference();
        } else {
          this.saveTheme(theme);
          this.applyTheme(theme);
        }
        
        menu.hidden = true;
        toggleBtn.setAttribute('aria-expanded', false);
        toggleBtn.focus();
        
        // הודעה למשתמש
        this.announceThemeChange(theme);
      });
    });
    
    // סגירת התפריט בלחיצה מחוץ
    document.addEventListener('click', (e) => {
      if (!toggleContainer.contains(e.target)) {
        menu.hidden = true;
        toggleBtn.setAttribute('aria-expanded', false);
      }
    });
    
    // ניווט במקלדת
    this.setupKeyboardNavigation(menu);
  }
  
  setupKeyboardNavigation(menu) {
    const items = menu.querySelectorAll('[role="menuitem"]');
    
    menu.addEventListener('keydown', (e) => {
      const currentIndex = Array.from(items).indexOf(document.activeElement);
      
      switch(e.key) {
        case 'ArrowDown':
          e.preventDefault();
          const nextIndex = (currentIndex + 1) % items.length;
          items[nextIndex].focus();
          break;
          
        case 'ArrowUp':
          e.preventDefault();
          const prevIndex = currentIndex === 0 ? items.length - 1 : currentIndex - 1;
          items[prevIndex].focus();
          break;
          
        case 'Escape':
          menu.hidden = true;
          document.getElementById('theme-toggle').focus();
          break;
          
        case 'Home':
          e.preventDefault();
          items[0].focus();
          break;
          
        case 'End':
          e.preventDefault();
          items[items.length - 1].focus();
          break;
      }
    });
  }
  
  announceThemeChange(theme) {
    // יצירת הודעה לקורא מסך
    const announcement = document.createElement('div');
    announcement.setAttribute('role', 'status');
    announcement.setAttribute('aria-live', 'polite');
    announcement.className = 'sr-only';
    
    const themeNames = {
      'light': 'מצב בהיר',
      'dark': 'מצב כהה',
      'high-contrast': 'ניגודיות גבוהה',
      'auto': 'אוטומטי'
    };
    
    announcement.textContent = `מצב התצוגה שונה ל${themeNames[theme]}`;
    document.body.appendChild(announcement);
    
    setTimeout(() => {
      document.body.removeChild(announcement);
    }, 1000);
  }
  
  // API ציבורי
  toggle() {
    const currentTheme = document.documentElement.getAttribute('data-theme');
    const themes = [
      this.THEMES.LIGHT,
      this.THEMES.DARK,
      this.THEMES.HIGH_CONTRAST
    ];
    
    const currentIndex = themes.indexOf(currentTheme);
    const nextIndex = (currentIndex + 1) % themes.length;
    const nextTheme = themes[nextIndex];
    
    this.saveTheme(nextTheme);
    this.applyTheme(nextTheme);
  }
  
  setTheme(theme) {
    if (Object.values(this.THEMES).includes(theme)) {
      this.saveTheme(theme);
      
      if (theme === this.THEMES.AUTO) {
        this.detectSystemPreference();
      } else {
        this.applyTheme(theme);
      }
    }
  }
  
  getCurrentTheme() {
    return document.documentElement.getAttribute('data-theme');
  }
}

// אתחול בטעינת הדף
document.addEventListener('DOMContentLoaded', () => {
  window.themeManager = new ThemeManager();
});
```

## 4. סגנונות לכפתור החלפת מצב

```css
/* webapp/static/css/theme-toggle.css */

.theme-toggle-container {
  position: fixed;
  top: 20px;
  right: 20px;
  z-index: 1000;
}

.theme-toggle-btn {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 16px;
  background: var(--bg-secondary);
  color: var(--text-primary);
  border: 2px solid var(--border-color);
  border-radius: 8px;
  cursor: pointer;
  font-size: 14px;
  font-weight: 500;
  transition: all 0.3s ease;
}

.theme-toggle-btn:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 8px rgba(0, 0, 0, 0.2);
}

.theme-toggle-btn:focus {
  outline: 3px solid var(--focus-outline-color);
  outline-offset: 2px;
}

.theme-menu {
  position: absolute;
  top: calc(100% + 8px);
  right: 0;
  background: var(--bg-primary);
  border: 2px solid var(--border-color);
  border-radius: 8px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
  min-width: 200px;
  overflow: hidden;
}

.theme-menu button {
  display: block;
  width: 100%;
  padding: 12px 16px;
  text-align: right;
  background: transparent;
  color: var(--text-primary);
  border: none;
  cursor: pointer;
  font-size: 14px;
  transition: background 0.2s ease;
}

.theme-menu button:hover {
  background: var(--bg-secondary);
}

.theme-menu button:focus {
  outline: 2px solid var(--focus-outline-color);
  outline-offset: -2px;
}

/* סגנונות למצב High Contrast */
[data-theme="high-contrast"] .theme-toggle-btn {
  border-width: 3px;
  font-weight: bold;
}

[data-theme="high-contrast"] .theme-menu {
  border-width: 3px;
}

[data-theme="high-contrast"] .theme-menu button {
  font-weight: bold;
  border-bottom: 1px solid var(--border-color);
}

[data-theme="high-contrast"] .theme-menu button:last-child {
  border-bottom: none;
}

/* הסתרה מקוראי מסך */
.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}
```

## 5. שילוב עם רכיבי Bootstrap (אם בשימוש)

```css
/* התאמות Bootstrap למצב High Contrast */

[data-theme="high-contrast"] .btn {
  border: 2px solid var(--border-color);
  font-weight: bold;
}

[data-theme="high-contrast"] .btn-primary {
  background-color: #0000ff;
  color: #ffffff;
  border-color: #ffffff;
}

[data-theme="high-contrast"] .btn-primary:hover {
  background-color: #000099;
  border-color: #ffff00;
}

[data-theme="high-contrast"] .btn-danger {
  background-color: #ff0000;
  color: #ffffff;
  border-color: #ffffff;
}

[data-theme="high-contrast"] .btn-success {
  background-color: #00ff00;
  color: #000000;
  border-color: #000000;
}

[data-theme="high-contrast"] .form-control {
  background-color: #000000;
  color: #ffffff;
  border: 2px solid #ffffff;
}

[data-theme="high-contrast"] .form-control:focus {
  border-color: #ffff00;
  box-shadow: 0 0 0 0.2rem rgba(255, 255, 0, 0.5);
}

[data-theme="high-contrast"] .card {
  background-color: #000000;
  border: 2px solid #ffffff;
}

[data-theme="high-contrast"] .modal-content {
  background-color: #000000;
  border: 3px solid #ffffff;
}

[data-theme="high-contrast"] .table {
  color: #ffffff;
  border: 2px solid #ffffff;
}

[data-theme="high-contrast"] .table td,
[data-theme="high-contrast"] .table th {
  border: 1px solid #ffffff;
}

[data-theme="high-contrast"] .table-striped tbody tr:nth-of-type(odd) {
  background-color: #111111;
}

[data-theme="high-contrast"] .alert {
  border: 2px solid;
  font-weight: bold;
}

[data-theme="high-contrast"] .alert-danger {
  background-color: #330000;
  color: #ff0000;
  border-color: #ff0000;
}

[data-theme="high-contrast"] .alert-warning {
  background-color: #333300;
  color: #ffff00;
  border-color: #ffff00;
}

[data-theme="high-contrast"] .alert-success {
  background-color: #003300;
  color: #00ff00;
  border-color: #00ff00;
}

[data-theme="high-contrast"] .alert-info {
  background-color: #003333;
  color: #00ffff;
  border-color: #00ffff;
}
```

## 6. בדיקות נגישות

### 6.1 סקריפט בדיקה אוטומטי

```javascript
// webapp/static/js/contrast-checker.js

class ContrastChecker {
  constructor() {
    this.WCAG_AA_NORMAL = 4.5;
    this.WCAG_AA_LARGE = 3;
    this.WCAG_AAA_NORMAL = 7;
    this.WCAG_AAA_LARGE = 4.5;
  }
  
  // חישוב Luminance יחסי
  relativeLuminance(rgb) {
    const [r, g, b] = rgb.map(val => {
      const sRGB = val / 255;
      return sRGB <= 0.03928 
        ? sRGB / 12.92 
        : Math.pow((sRGB + 0.055) / 1.055, 2.4);
    });
    
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  }
  
  // חישוב יחס ניגודיות
  contrastRatio(color1, color2) {
    const lum1 = this.relativeLuminance(color1);
    const lum2 = this.relativeLuminance(color2);
    
    const lighter = Math.max(lum1, lum2);
    const darker = Math.min(lum1, lum2);
    
    return (lighter + 0.05) / (darker + 0.05);
  }
  
  // המרת hex ל-RGB
  hexToRgb(hex) {
    const result = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex);
    return result ? [
      parseInt(result[1], 16),
      parseInt(result[2], 16),
      parseInt(result[3], 16)
    ] : null;
  }
  
  // בדיקת כל האלמנטים בדף
  checkAllElements() {
    const results = [];
    const elements = document.querySelectorAll('*');
    
    elements.forEach(element => {
      const style = window.getComputedStyle(element);
      const bgColor = style.backgroundColor;
      const textColor = style.color;
      
      if (bgColor !== 'rgba(0, 0, 0, 0)' && textColor) {
        const bg = this.parseColor(bgColor);
        const text = this.parseColor(textColor);
        
        if (bg && text) {
          const ratio = this.contrastRatio(bg, text);
          const fontSize = parseFloat(style.fontSize);
          const fontWeight = style.fontWeight;
          
          const isLargeText = fontSize >= 18 || 
            (fontSize >= 14 && parseInt(fontWeight) >= 700);
          
          const passesAA = isLargeText 
            ? ratio >= this.WCAG_AA_LARGE 
            : ratio >= this.WCAG_AA_NORMAL;
            
          const passesAAA = isLargeText 
            ? ratio >= this.WCAG_AAA_LARGE 
            : ratio >= this.WCAG_AAA_NORMAL;
          
          if (!passesAA) {
            results.push({
              element,
              ratio: ratio.toFixed(2),
              required: isLargeText ? this.WCAG_AA_LARGE : this.WCAG_AA_NORMAL,
              passesAA,
              passesAAA,
              bgColor,
              textColor
            });
          }
        }
      }
    });
    
    return results;
  }
  
  // פענוח צבע מ-CSS
  parseColor(color) {
    if (color.startsWith('rgb')) {
      const matches = color.match(/\d+/g);
      if (matches && matches.length >= 3) {
        return matches.slice(0, 3).map(Number);
      }
    } else if (color.startsWith('#')) {
      return this.hexToRgb(color);
    }
    return null;
  }
  
  // הצגת דוח
  generateReport() {
    const issues = this.checkAllElements();
    
    if (issues.length === 0) {
      console.log('✅ כל האלמנטים עוברים את דרישות WCAG AA לניגודיות!');
      return;
    }
    
    console.group('⚠️ בעיות ניגודיות נמצאו:');
    issues.forEach(issue => {
      console.log(
        `Element: ${issue.element.tagName}.${issue.element.className}`,
        `\nContrast Ratio: ${issue.ratio}:1 (Required: ${issue.required}:1)`,
        `\nColors: ${issue.bgColor} on ${issue.textColor}`,
        `\nWCAG AA: ${issue.passesAA ? '✅' : '❌'}`,
        `\nWCAG AAA: ${issue.passesAAA ? '✅' : '❌'}`
      );
      console.log(issue.element);
    });
    console.groupEnd();
    
    return issues;
  }
}

// שימוש
const checker = new ContrastChecker();
// הרצת בדיקה לאחר טעינת הדף
window.addEventListener('load', () => {
  if (window.location.search.includes('debug=contrast')) {
    checker.generateReport();
  }
});
```

### 6.2 בדיקות ידניות מומלצות

```markdown
## צ'קליסט בדיקות ידניות

### 1. בדיקת ניגודיות
- [ ] טקסט רגיל: יחס ניגודיות מינימום 4.5:1
- [ ] טקסט גדול (18px+): יחס ניגודיות מינימום 3:1
- [ ] רכיבים אינטראקטיביים: יחס ניגודיות מינימום 3:1
- [ ] הודעות שגיאה: ברורות וקריאות

### 2. ניווט במקלדת
- [ ] כל האלמנטים נגישים באמצעות Tab
- [ ] סדר הניווט הגיוני
- [ ] אינדיקטור פוקוס ברור (outline)
- [ ] אין מלכודות מקלדת

### 3. קוראי מסך
- [ ] כל האלמנטים מתוארים כראוי
- [ ] כפתורים עם aria-label תיאורי
- [ ] הודעות סטטוס עם aria-live
- [ ] מבנה כותרות הירארכי

### 4. בדיקת זום
- [ ] הממשק נשאר שמיש ב-200% zoom
- [ ] אין חיתוך טקסט
- [ ] אין חפיפות בין אלמנטים

### 5. הגדרות מערכת
- [ ] זיהוי נכון של prefers-contrast: high
- [ ] זיהוי נכון של prefers-color-scheme
- [ ] זיהוי נכון של prefers-reduced-motion

### 6. בדיקת דפדפנים
- [ ] Chrome/Edge
- [ ] Firefox
- [ ] Safari
- [ ] Chrome עם הרחבות נגישות

### 7. בדיקת מכשירים
- [ ] Desktop
- [ ] Tablet
- [ ] Mobile
- [ ] עם מגדיל מסך
```

## 7. שילוב עם קוד קיים

### 7.1 הוספה ל-base.html

```html
<!-- webapp/templates/base.html -->
<!DOCTYPE html>
<html lang="he" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="theme-color" content="#ffffff">
    
    <!-- CSS בסיסי -->
    <link rel="stylesheet" href="{{ url_for('static', filename='css/style.css') }}">
    
    <!-- CSS למצב High Contrast -->
    <link rel="stylesheet" href="{{ url_for('static', filename='css/high-contrast.css') }}">
    <link rel="stylesheet" href="{{ url_for('static', filename='css/theme-toggle.css') }}">
    
    <title>{% block title %}WebApp{% endblock %}</title>
</head>
<body>
    <!-- תוכן הדף -->
    {% block content %}{% endblock %}
    
    <!-- JavaScript -->
    <script src="{{ url_for('static', filename='js/theme-manager.js') }}"></script>
    
    {% if debug %}
    <script src="{{ url_for('static', filename='js/contrast-checker.js') }}"></script>
    {% endif %}
</body>
</html>
```

### 7.2 אינטגרציה עם Python Backend

```python
# webapp/utils/theme_utils.py

from flask import session, request

class ThemeUtils:
    """כלים לניהול מצב Theme בצד השרת"""
    
    THEMES = {
        'light': 'מצב בהיר',
        'dark': 'מצב כהה',
        'high-contrast': 'ניגודיות גבוהה',
        'auto': 'אוטומטי'
    }
    
    @staticmethod
    def get_user_theme():
        """קבלת Theme המועדף של המשתמש"""
        # בדיקה ב-session
        if 'theme' in session:
            return session['theme']
        
        # בדיקה ב-cookie
        theme_cookie = request.cookies.get('webapp-theme-preference')
        if theme_cookie in ThemeUtils.THEMES:
            return theme_cookie
        
        # בדיקת header של העדפת המערכת
        prefer_contrast = request.headers.get('Sec-CH-Prefers-Contrast')
        if prefer_contrast == 'high':
            return 'high-contrast'
        
        prefer_color = request.headers.get('Sec-CH-Prefers-Color-Scheme')
        if prefer_color == 'dark':
            return 'dark'
        
        return 'light'  # ברירת מחדל
    
    @staticmethod
    def set_user_theme(theme):
        """שמירת Theme המועדף של המשתמש"""
        if theme in ThemeUtils.THEMES:
            session['theme'] = theme
            return True
        return False
    
    @staticmethod
    def get_theme_class():
        """קבלת מחלקת CSS עבור ה-Theme הנוכחי"""
        theme = ThemeUtils.get_user_theme()
        return f'theme-{theme}'
    
    @staticmethod
    def generate_css_variables(theme):
        """יצירת משתני CSS דינמיים לפי Theme"""
        variables = {}
        
        if theme == 'high-contrast':
            variables = {
                '--bg-primary': '#000000',
                '--bg-secondary': '#000000',
                '--text-primary': '#ffffff',
                '--text-secondary': '#ffffff',
                '--border-color': '#ffffff',
                '--link-color': '#ffff00',
                '--link-hover': '#ffcc00',
                '--success-color': '#00ff00',
                '--warning-color': '#ffff00',
                '--error-color': '#ff0000',
                '--info-color': '#00ffff'
            }
        elif theme == 'dark':
            variables = {
                '--bg-primary': '#1a1a1a',
                '--bg-secondary': '#2d2d2d',
                '--text-primary': '#e0e0e0',
                '--text-secondary': '#b0b0b0',
                '--border-color': '#404040',
                '--link-color': '#64b5f6',
                '--link-hover': '#42a5f5'
            }
        else:  # light
            variables = {
                '--bg-primary': '#ffffff',
                '--bg-secondary': '#f5f5f5',
                '--text-primary': '#212121',
                '--text-secondary': '#757575',
                '--border-color': '#e0e0e0',
                '--link-color': '#1976d2',
                '--link-hover': '#1565c0'
            }
        
        return variables

# webapp/app.py - הוספת endpoint
from flask import Flask, jsonify, request, make_response
from .utils.theme_utils import ThemeUtils

@app.route('/api/theme', methods=['GET', 'POST'])
def theme_api():
    """API לניהול Theme"""
    if request.method == 'POST':
        data = request.get_json()
        theme = data.get('theme')
        
        if ThemeUtils.set_user_theme(theme):
            resp = make_response(jsonify({'success': True, 'theme': theme}))
            # שמירה גם ב-cookie
            resp.set_cookie('webapp-theme-preference', theme, 
                          max_age=60*60*24*365,  # שנה
                          httponly=True,
                          samesite='Lax')
            return resp
        
        return jsonify({'success': False, 'error': 'Invalid theme'}), 400
    
    # GET
    current_theme = ThemeUtils.get_user_theme()
    return jsonify({
        'current': current_theme,
        'available': list(ThemeUtils.THEMES.keys())
    })

@app.context_processor
def inject_theme():
    """הזרקת Theme לכל התבניות"""
    return {
        'current_theme': ThemeUtils.get_user_theme(),
        'theme_class': ThemeUtils.get_theme_class()
    }
```

## 8. טיפים וטריקים

### 8.1 אופטימיזציות ביצועים

```javascript
// שימוש ב-CSS containment לשיפור ביצועים
[data-theme="high-contrast"] .complex-component {
  contain: layout style paint;
}

// דחיית טעינת CSS לא קריטי
<link rel="preload" href="high-contrast.css" as="style" 
      onload="this.onload=null;this.rel='stylesheet'">
```

### 8.2 תמיכה ב-Reduced Motion

```css
/* הפחתת אנימציות למשתמשים שמעדיפים */
@media (prefers-reduced-motion: reduce) {
  * {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
  }
}
```

### 8.3 Print Styles

```css
/* סגנונות הדפסה אוטומטיים בניגודיות גבוהה */
@media print {
  * {
    background: white !important;
    color: black !important;
    border-color: black !important;
  }
  
  a {
    text-decoration: underline !important;
  }
  
  .no-print {
    display: none !important;
  }
}
```

## 9. משאבים נוספים

### כלי בדיקה מומלצים
- [WAVE WebAIM](https://wave.webaim.org/)
- [axe DevTools](https://www.deque.com/axe/devtools/)
- [Lighthouse](https://developers.google.com/web/tools/lighthouse)
- [Colour Contrast Analyser](https://www.tpgi.com/color-contrast-checker/)

### תקנים ומדריכים
- [WCAG 2.1 Guidelines](https://www.w3.org/WAI/WCAG21/quickref/)
- [MDN Accessibility](https://developer.mozilla.org/en-US/docs/Web/Accessibility)
- [WebAIM Contrast Checker](https://webaim.org/resources/contrastchecker/)

### ספריות עזר
- [tinycolor2](https://github.com/bgrins/TinyColor) - מניפולציה של צבעים
- [color2k](https://github.com/ricokahler/color2k) - כלים לצבעים
- [a11y-color-tokens](https://github.com/primer/primitives) - טוקנים נגישים

## סיכום

מימוש מצב ניגודיות גבוהה הוא לא רק תכונת נגישות - זה שיפור משמעותי בחוויית המשתמש עבור כולם. המדריך הזה מספק בסיס מוצק למימוש מלא ומקיף של התכונה, כולל:

- ✅ תמיכה מלאה בתקני WCAG
- ✅ ניהול מצבים גמיש
- ✅ זיהוי אוטומטי של העדפות מערכת
- ✅ ממשק ידידותי ונגיש
- ✅ בדיקות אוטומטיות
- ✅ תיעוד מלא

המימוש הזה מבטיח שהאפליקציה תהיה נגישה לכל המשתמשים, ללא קשר ליכולות הראייה שלהם.

---

*נכתב עבור פרויקט WebApp | מעודכן: 2025*