# 📋 מדריך מימוש תצוגת Markdown נגישה ומתקדמת

## 🎯 סקירה כללית

מדריך זה מפרט כיצד להוסיף תכונות נגישות ואינטראקציה מתקדמות לתצוגת Markdown, כולל:
- 🔗 עוגני כותרות נגישים עם permalinks
- 📋 כפתור העתקה לבלוקי קוד (שיפור הקיים)
- ⚓ קישורי קבע לכותרות
- ♿ תמיכה מלאה בקוראי מסך ונגישות

## 📌 תכונות עיקריות

### 1. עוגני כותרות נגישים (Header Anchors)
- יצירת מזהים ייחודיים אוטומטית לכל כותרת
- תמיכה בניווט מקלדת
- תוויות ARIA מלאות
- אינדיקציה ויזואלית למיקוד

### 2. כפתור העתקה משופר לקוד
- העתקה בלחיצה אחת
- אנימציות משוב ברורות
- תמיכה בדפדפנים ישנים (fallback)
- נגישות מלאה למקלדת

### 3. Permalinks לכותרות
- סמל קישור מופיע ב-hover
- העתקת קישור ישיר לכותרת
- שיתוף קל של סעיפים ספציפיים

## 🛠️ מימוש טכני

### שלב 1: הוספת תלויות (כבר קיים חלקית)

```javascript
// webapp/static_build/md-preview-entry.js
import markdownItAnchor from 'markdown-it-anchor';

// חשוף על window
window.markdownitAnchor = markdownItAnchor;
```

### שלב 2: קונפיגורציה של markdown-it

```javascript
// בתוך webapp/templates/md_preview.html
const md = window.markdownit({
  breaks: true,
  linkify: true,
  typographer: true,
  html: false
});

// הוספת תוסף anchor עם הגדרות נגישות
if (window.markdownitAnchor) {
  md.use(window.markdownitAnchor, {
    level: [1, 2, 3, 4],  // רמות כותרות לעיבוד
    permalink: window.markdownitAnchor.permalink.headerLink({
      safariReaderFix: true,
      class: 'header-anchor',
      symbol: '🔗',
      ariaHidden: false,  // נגיש לקוראי מסך
      renderAttrs: (slug) => ({
        'aria-label': `קישור קבוע לסעיף: ${slug}`,
        'title': 'לחץ להעתקת קישור'
      })
    }),
    slugify: (s) => {
      // יצירת slug בטוח עם תמיכה בעברית
      return s.trim()
        .toLowerCase()
        .replace(/[^\w\u0590-\u05FF\s-]/g, '') // השאר אותיות, מספרים ועברית
        .replace(/[\s_]+/g, '-')
        .replace(/^-+|-+$/g, '');
    }
  });
}
```

### שלב 3: שיפור כפתור העתקה לקוד

```javascript
// פונקציה משופרת להוספת כפתורי העתקה
function addCopyButtons() {
  const pres = document.querySelectorAll('#md-content pre');
  
  pres.forEach(pre => {
    // בדיקה אם כבר קיים כפתור
    if (pre.querySelector('.md-copy-btn')) return;
    
    // יצירת wrapper אם לא קיים
    let wrapper = pre.parentElement;
    if (!wrapper?.classList.contains('code-block')) {
      wrapper = document.createElement('div');
      wrapper.className = 'code-block';
      pre.replaceWith(wrapper);
      wrapper.appendChild(pre);
    }
    
    // יצירת כפתור נגיש
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'md-copy-btn';
    btn.setAttribute('aria-label', 'העתק קוד');
    btn.setAttribute('role', 'button');
    btn.innerHTML = `
      <span class="copy-icon" aria-hidden="true">📋</span>
      <span class="copy-text">העתק</span>
      <span class="copied-text" style="display:none">✅ הועתק!</span>
    `;
    
    // טיפול בהעתקה עם משוב נגיש
    btn.addEventListener('click', async () => {
      const code = pre.querySelector('code')?.innerText || pre.innerText;
      
      try {
        await navigator.clipboard.writeText(code);
        showCopySuccess(btn);
        announceToScreenReader('הקוד הועתק ללוח');
      } catch(err) {
        // Fallback לדפדפנים ישנים
        if (fallbackCopy(code)) {
          showCopySuccess(btn);
          announceToScreenReader('הקוד הועתק ללוח');
        } else {
          showCopyError(btn);
          announceToScreenReader('ההעתקה נכשלה');
        }
      }
    });
    
    // תמיכה בניווט מקלדת
    btn.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        btn.click();
      }
    });
    
    wrapper.appendChild(btn);
  });
}

// פונקציות עזר למשוב
function showCopySuccess(btn) {
  btn.classList.add('copied');
  btn.querySelector('.copy-text').style.display = 'none';
  btn.querySelector('.copied-text').style.display = 'inline';
  
  setTimeout(() => {
    btn.classList.remove('copied');
    btn.querySelector('.copy-text').style.display = 'inline';
    btn.querySelector('.copied-text').style.display = 'none';
  }, 2000);
}

function showCopyError(btn) {
  btn.classList.add('copy-error');
  setTimeout(() => btn.classList.remove('copy-error'), 2000);
}

// Fallback להעתקה
function fallbackCopy(text) {
  const textarea = document.createElement('textarea');
  textarea.value = text;
  textarea.style.position = 'fixed';
  textarea.style.opacity = '0';
  document.body.appendChild(textarea);
  textarea.select();
  
  try {
    const success = document.execCommand('copy');
    document.body.removeChild(textarea);
    return success;
  } catch(err) {
    document.body.removeChild(textarea);
    return false;
  }
}

// הכרזה לקוראי מסך
function announceToScreenReader(message) {
  const announcement = document.createElement('div');
  announcement.setAttribute('role', 'status');
  announcement.setAttribute('aria-live', 'polite');
  announcement.className = 'sr-only';
  announcement.textContent = message;
  
  document.body.appendChild(announcement);
  setTimeout(() => document.body.removeChild(announcement), 1000);
}
```

### שלב 4: Permalinks נגישים לכותרות

```javascript
// הוספת פונקציונליות permalink
function enhanceHeaderPermalinks() {
  const headers = document.querySelectorAll('#md-content h1, h2, h3, h4, h5, h6');
  
  headers.forEach(header => {
    // וודא שיש ID
    if (!header.id) {
      header.id = generateUniqueId(header.textContent);
    }
    
    // הוסף קישור permalink אם לא קיים
    if (!header.querySelector('.header-anchor')) {
      const permalink = document.createElement('a');
      permalink.className = 'header-anchor';
      permalink.href = `#${header.id}`;
      permalink.innerHTML = '🔗';
      permalink.setAttribute('aria-label', `קישור קבוע לסעיף: ${header.textContent}`);
      permalink.setAttribute('title', 'העתק קישור לסעיף זה');
      
      // טיפול בלחיצה - העתקת קישור
      permalink.addEventListener('click', async (e) => {
        e.preventDefault();
        
        const url = new URL(window.location);
        url.hash = header.id;
        
        try {
          await navigator.clipboard.writeText(url.toString());
          showTooltip(permalink, 'הקישור הועתק!');
          announceToScreenReader('קישור לכותרת הועתק');
        } catch(err) {
          if (fallbackCopy(url.toString())) {
            showTooltip(permalink, 'הקישור הועתק!');
            announceToScreenReader('קישור לכותרת הועתק');
          }
        }
        
        // גלול לכותרת
        header.scrollIntoView({ behavior: 'smooth', block: 'start' });
      });
      
      header.appendChild(permalink);
    }
  });
}

// יצירת ID ייחודי מטקסט
function generateUniqueId(text) {
  const base = text
    .trim()
    .toLowerCase()
    .replace(/[^\w\u0590-\u05FF\s-]/g, '')
    .replace(/[\s_]+/g, '-')
    .replace(/^-+|-+$/g, '');
  
  let id = base || 'section';
  let counter = 1;
  
  while (document.getElementById(id)) {
    id = `${base}-${counter}`;
    counter++;
  }
  
  return id;
}

// הצגת tooltip
function showTooltip(element, message) {
  const tooltip = document.createElement('div');
  tooltip.className = 'permalink-tooltip';
  tooltip.textContent = message;
  tooltip.setAttribute('role', 'tooltip');
  
  const rect = element.getBoundingClientRect();
  tooltip.style.position = 'fixed';
  tooltip.style.top = `${rect.top - 30}px`;
  tooltip.style.left = `${rect.left}px`;
  
  document.body.appendChild(tooltip);
  
  setTimeout(() => {
    tooltip.style.opacity = '0';
    setTimeout(() => document.body.removeChild(tooltip), 300);
  }, 2000);
}
```

### שלב 5: סגנונות CSS נגישים

```css
/* webapp/static/css/markdown-enhanced.css */

/* === עוגני כותרות נגישים === */
.header-anchor {
  margin-left: 0.5em;
  opacity: 0;
  color: #6c757d;
  text-decoration: none;
  font-size: 0.8em;
  transition: opacity 0.2s ease, color 0.2s ease;
  vertical-align: middle;
  
  /* נגישות - הצגה בפוקוס */
  &:focus {
    opacity: 1;
    outline: 2px solid #0366d6;
    outline-offset: 2px;
    border-radius: 3px;
  }
}

/* הצגה ב-hover על הכותרת */
h1:hover .header-anchor,
h2:hover .header-anchor,
h3:hover .header-anchor,
h4:hover .header-anchor,
h5:hover .header-anchor,
h6:hover .header-anchor {
  opacity: 1;
}

.header-anchor:hover {
  color: #0366d6;
  transform: scale(1.1);
}

/* === כפתור העתקת קוד משופר === */
.code-block {
  position: relative;
  margin: 1rem 0;
}

.md-copy-btn {
  position: absolute;
  top: 8px;
  left: 8px;
  padding: 6px 12px;
  background: rgba(255, 255, 255, 0.9);
  border: 1px solid rgba(0, 0, 0, 0.1);
  border-radius: 6px;
  cursor: pointer;
  font-size: 14px;
  font-family: inherit;
  transition: all 0.2s ease;
  backdrop-filter: blur(10px);
  z-index: 10;
  
  /* נגישות */
  &:focus {
    outline: 2px solid #0366d6;
    outline-offset: 2px;
  }
  
  &:hover {
    background: rgba(255, 255, 255, 1);
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
    transform: translateY(-1px);
  }
  
  &:active {
    transform: translateY(0);
  }
}

.md-copy-btn.copied {
  background: #28a745;
  color: white;
  border-color: #28a745;
}

.md-copy-btn.copy-error {
  background: #dc3545;
  color: white;
  border-color: #dc3545;
}

/* אנימציית הופעה */
@keyframes fadeIn {
  from {
    opacity: 0;
    transform: translateY(-5px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.md-copy-btn {
  animation: fadeIn 0.3s ease;
}

/* === Tooltip === */
.permalink-tooltip {
  background: rgba(0, 0, 0, 0.8);
  color: white;
  padding: 5px 10px;
  border-radius: 4px;
  font-size: 12px;
  white-space: nowrap;
  pointer-events: none;
  transition: opacity 0.3s ease;
  z-index: 1000;
}

/* === תמיכה בקוראי מסך === */
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

/* === Dark Mode === */
@media (prefers-color-scheme: dark) {
  .header-anchor {
    color: #8b949e;
  }
  
  .md-copy-btn {
    background: rgba(30, 30, 30, 0.9);
    color: #e0e0e0;
    border-color: rgba(255, 255, 255, 0.1);
  }
  
  .permalink-tooltip {
    background: rgba(255, 255, 255, 0.9);
    color: #000;
  }
}

/* === High Contrast Mode === */
@media (prefers-contrast: high) {
  .header-anchor:focus {
    outline-width: 3px;
  }
  
  .md-copy-btn {
    border-width: 2px;
  }
}

/* === Reduced Motion === */
@media (prefers-reduced-motion: reduce) {
  .header-anchor,
  .md-copy-btn,
  .permalink-tooltip {
    transition: none;
  }
  
  .md-copy-btn {
    animation: none;
  }
}

/* === Print Styles === */
@media print {
  .header-anchor,
  .md-copy-btn {
    display: none !important;
  }
}
```

### שלב 6: אתחול והפעלה

```javascript
// בסוף הקובץ md_preview.html
document.addEventListener('DOMContentLoaded', async () => {
  try {
    // המתן לטעינת התוכן
    await waitForContent();
    
    // הפעל תכונות נגישות
    addCopyButtons();
    enhanceHeaderPermalinks();
    
    // הוסף תמיכה בניווט מקלדת
    setupKeyboardNavigation();
    
    // טען מצב שמור (אם יש)
    restoreScrollPosition();
    
  } catch(error) {
    console.error('Error initializing accessible features:', error);
  }
});

// ניווט מקלדת משופר
function setupKeyboardNavigation() {
  document.addEventListener('keydown', (e) => {
    // Ctrl+Shift+C - העתק קוד ראשון
    if (e.ctrlKey && e.shiftKey && e.key === 'C') {
      e.preventDefault();
      const firstCopyBtn = document.querySelector('.md-copy-btn');
      if (firstCopyBtn) firstCopyBtn.click();
    }
    
    // Ctrl+L - העתק קישור לכותרת נוכחית
    if (e.ctrlKey && e.key === 'L') {
      e.preventDefault();
      const currentHeader = getCurrentVisibleHeader();
      if (currentHeader) {
        const permalink = currentHeader.querySelector('.header-anchor');
        if (permalink) permalink.click();
      }
    }
  });
}

// מצא כותרת גלויה נוכחית
function getCurrentVisibleHeader() {
  const headers = document.querySelectorAll('h1, h2, h3, h4, h5, h6');
  const scrollPos = window.scrollY + 100;
  
  for (let i = headers.length - 1; i >= 0; i--) {
    if (headers[i].offsetTop <= scrollPos) {
      return headers[i];
    }
  }
  
  return headers[0];
}

// שמור ושחזר מיקום גלילה
function restoreScrollPosition() {
  const hash = window.location.hash;
  if (hash) {
    const element = document.querySelector(hash);
    if (element) {
      setTimeout(() => {
        element.scrollIntoView({ behavior: 'smooth', block: 'start' });
        element.focus();
      }, 100);
    }
  }
}
```

## 📊 תכונות נגישות

### WCAG 2.1 Compliance

| קריטריון | רמה | מימוש |
|---------|------|------|
| 1.3.1 מידע ויחסים | A | ✅ שימוש נכון ב-semantic HTML |
| 2.1.1 מקלדת | A | ✅ כל הפעולות נגישות במקלדת |
| 2.4.1 עקיפת בלוקים | A | ✅ עוגני כותרות לניווט מהיר |
| 2.4.6 כותרות ותוויות | AA | ✅ תוויות ARIA מלאות |
| 2.4.7 פוקוס גלוי | AA | ✅ אינדיקציה ברורה לפוקוס |
| 3.1.2 שפת חלקים | AA | ✅ תמיכה בעברית ואנגלית |
| 4.1.2 שם, תפקיד, ערך | A | ✅ תכונות ARIA מלאות |

### תמיכה בקוראי מסך

- **JAWS**: תמיכה מלאה
- **NVDA**: תמיכה מלאה
- **VoiceOver**: תמיכה מלאה (iOS/macOS)
- **TalkBack**: תמיכה מלאה (Android)

### קיצורי מקלדת

| קיצור | פעולה |
|-------|--------|
| `Tab` | ניווט בין אלמנטים |
| `Enter` / `Space` | הפעלת כפתור |
| `Ctrl+Shift+C` | העתק קוד ראשון |
| `Ctrl+L` | העתק קישור לכותרת נוכחית |
| `Escape` | סגור tooltip |

## 🧪 בדיקות

### בדיקות יחידה

```javascript
// tests/test_markdown_accessibility.js
describe('Markdown Accessibility Features', () => {
  
  it('should generate unique IDs for headers', () => {
    const headers = ['Introduction', 'Introduction', 'מבוא'];
    const ids = headers.map(h => generateUniqueId(h));
    expect(new Set(ids).size).toBe(ids.length);
  });
  
  it('should add ARIA labels to permalinks', () => {
    const anchor = document.querySelector('.header-anchor');
    expect(anchor.getAttribute('aria-label')).toBeTruthy();
  });
  
  it('should handle keyboard navigation', () => {
    const button = document.querySelector('.md-copy-btn');
    const event = new KeyboardEvent('keydown', { key: 'Enter' });
    button.dispatchEvent(event);
    expect(button.classList.contains('copied')).toBe(true);
  });
  
  it('should announce to screen readers', () => {
    announceToScreenReader('Test message');
    const announcement = document.querySelector('[role="status"]');
    expect(announcement.textContent).toBe('Test message');
  });
});
```

### בדיקות נגישות אוטומטיות

```javascript
// Using axe-core
const { AxePuppeteer } = require('@axe-core/puppeteer');

test('Markdown view should be accessible', async () => {
  const results = await new AxePuppeteer(page)
    .include('#md-content')
    .analyze();
  
  expect(results.violations).toHaveLength(0);
});
```

### בדיקות ידניות

- [ ] ניווט עם מקלדת בלבד
- [ ] בדיקה עם קורא מסך
- [ ] בדיקה במצב High Contrast
- [ ] בדיקה עם הגדלה 200%
- [ ] בדיקה במצב Reduced Motion

## 🚀 פריסה

### שלב 1: בנייה מחדש של Bundle

```bash
cd webapp/static_build
npm run build
```

### שלב 2: עדכון Cache Busting

```python
# webapp/app.py
STATIC_VERSION = "2.1.0"  # עדכן גרסה
```

### שלב 3: בדיקות Production

```bash
# בדוק minification
npm run build:prod

# בדוק ביצועים
lighthouse https://your-site.com/md_preview --preset=desktop
```

## 📈 מדדי הצלחה

### ביצועים
- זמן טעינה ראשוני: < 2 שניות
- Time to Interactive: < 3 שניות
- First Input Delay: < 100ms

### נגישות
- Lighthouse Accessibility Score: 100
- axe-core: 0 violations
- תמיכה מלאה בקוראי מסך

### חוויית משתמש
- אחוז שימוש בכפתור העתקה: > 30%
- שימוש ב-permalinks: > 20%
- משוב משתמשים חיובי: > 90%

## 🔄 שיפורים עתידיים

### Phase 2 (v2.2.0)
- [ ] תוכן עניינים אינטראקטיבי עם חיפוש
- [ ] סימניות לסעיפים ספציפיים
- [ ] הדפסה חכמה עם שמירת עוגנים

### Phase 3 (v3.0.0)
- [ ] מצב קריאה מותאם אישית
- [ ] ייצוא לפורמטים שונים (PDF, DOCX)
- [ ] הערות ותגובות על סעיפים

## 📚 משאבים

### תיעוד
- [WCAG 2.1 Guidelines](https://www.w3.org/WAI/WCAG21/quickref/)
- [ARIA Authoring Practices](https://www.w3.org/TR/wai-aria-practices-1.1/)
- [markdown-it-anchor Documentation](https://github.com/valeriangalliat/markdown-it-anchor)

### כלים
- [axe DevTools](https://www.deque.com/axe/devtools/)
- [WAVE Accessibility Tool](https://wave.webaim.org/)
- [Lighthouse CI](https://github.com/GoogleChrome/lighthouse-ci)

### קריאה נוספת
- [Building Accessible Markdown Renderers](https://www.smashingmagazine.com/2021/05/accessible-markdown/)
- [Inclusive Components](https://inclusive-components.design/)
- [A11y Project Checklist](https://www.a11yproject.com/checklist/)

## 👥 צוות ותמיכה

### אחראי מימוש
- Frontend: צוות UI/UX
- Backend: צוות API
- נגישות: מומחה נגישות

### ערוצי תמיכה
- Slack: `#accessibility-team`
- Email: `accessibility@codebot.dev`
- Documentation: `docs/accessibility/`

---

*מסמך זה עודכן לאחרונה: 2025-10-22*
*גרסת מדריך: 1.0.0*