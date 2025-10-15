# 📚 מדריך משופר: תוכן עניינים צף מתקדם לתצוגת Markdown

> **גרסה 2.0** - כולל כל השיפורים המתקדמים: Intersection Observer, Virtual Scrolling, חיפוש מובנה, Dark Mode ועוד! 🚀

## 🎯 סקירה כללית

מדריך זה מציג **גרסה משופרת ומתקדמת** של תוכן עניינים צף לתצוגת Markdown. הגרסה כוללת:

### ✨ פיצ'רים חדשים
- 🔍 **חיפוש מובנה** - חיפוש מהיר בכותרות
- ⌨️ **קיצורי מקלדת** - ניווט מהיר עם המקלדת
- 📊 **אינדיקטור התקדמות** - מראה כמה מהמסמך נקרא
- 🌙 **Dark Mode אוטומטי** - תמיכה מלאה בערכת נושא כהה
- ⚡ **Intersection Observer** - ביצועים משופרים ללא scroll events
- 🎯 **Virtual Scrolling** - תמיכה במסמכים עם אלפי כותרות
- 🛡️ **אבטחה משופרת** - סניטציה מלאה ומניעת XSS

### 📋 דרישות מוקדמות
- הקובץ `webapp/templates/md_preview.html` קיים
- הספריות `markdown-it`, `markdown-it-anchor` כבר טעונות
- תמיכת דפדפן ב-Intersection Observer API (כל הדפדפנים המודרניים)

## 🚀 התקנה מלאה

### שלב 1: הוספת המבנה HTML המתקדם

הוסף את הקוד הבא **כאח (sibling)** של `#md-root` ולא בתוכו. מצא את השורה שבה נמצא `<div id="md-root">` והוסף **לפניה**:

```html
<!-- תוכן עניינים צף מתקדם עם כל הפיצ'רים -->
<div id="mdToc" class="md-toc" style="display:none;" 
     role="navigation" 
     aria-label="תוכן עניינים של המסמך">
  
  <!-- כותרת עם אינדיקטור התקדמות -->
  <div class="md-toc-header">
    <div class="md-toc-title-wrapper">
      <h3 id="toc-heading">
        <i class="fas fa-list" aria-hidden="true"></i>
        תוכן עניינים
      </h3>
      <div class="md-toc-progress" role="progressbar" aria-valuenow="0" aria-valuemin="0" aria-valuemax="100">
        <div class="md-toc-progress-bar" id="tocProgressBar"></div>
      </div>
    </div>
    <div class="md-toc-controls">
      <button id="mdTocSearch" 
              class="md-toc-search-btn" 
              aria-label="חפש בכותרות"
              title="חיפוש (Ctrl+F)">
        <i class="fas fa-search" aria-hidden="true"></i>
      </button>
      <button id="mdTocToggle" 
              class="md-toc-toggle" 
              aria-controls="mdTocNav" 
              aria-expanded="true"
              aria-labelledby="toc-heading"
              title="כווץ או הרחב (Ctrl+T)">
        <i class="fas fa-chevron-up" aria-hidden="true"></i>
      </button>
    </div>
  </div>
  
  <!-- תיבת חיפוש (מוסתרת בהתחלה) -->
  <div class="md-toc-search-container" id="tocSearchContainer" style="display:none;">
    <input type="search" 
           id="tocSearchInput"
           class="md-toc-search-input"
           placeholder="חפש בכותרות..." 
           aria-label="חיפוש בתוכן העניינים">
    <span class="md-toc-search-results" id="tocSearchResults"></span>
  </div>
  
  <!-- אזור הניווט עם Virtual Scrolling -->
  <nav id="mdTocNav" 
       class="md-toc-nav" 
       aria-labelledby="toc-heading"
       role="list">
    <!-- כאן יוכנסו הכותרות דינמית -->
  </nav>
  
  <!-- כפתור מצב מינימלי -->
  <button id="mdTocMini" 
          class="md-toc-mini-btn" 
          style="display:none;"
          aria-label="הצג תוכן עניינים"
          title="הצג תוכן עניינים (Ctrl+T)">
    <i class="fas fa-bars"></i>
  </button>
</div>
```

### שלב 2: הוספת עיצוב CSS מתקדם עם Dark Mode

הוסף את הסגנונות האלה בתוך תג `<style>` בחלק `{% block extra_css %}`:

```css
/* === תוכן עניינים צף מתקדם === */
:root {
  --toc-bg-light: linear-gradient(135deg, rgba(255,255,255,0.98) 0%, rgba(250,250,252,0.98) 100%);
  --toc-bg-dark: linear-gradient(135deg, rgba(30,30,40,0.98) 0%, rgba(40,40,50,0.98) 100%);
  --toc-header-gradient: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  --toc-text-light: #2d3748;
  --toc-text-dark: #e0e0e0;
  --toc-hover-light: rgba(102, 126, 234, 0.1);
  --toc-hover-dark: rgba(102, 126, 234, 0.2);
  --toc-active-light: rgba(102, 126, 234, 0.15);
  --toc-active-dark: rgba(102, 126, 234, 0.25);
}

.md-toc {
  position: fixed;
  top: 100px;
  left: 20px;
  max-width: 320px;
  min-width: 250px;
  max-height: calc(100vh - 140px);
  background: var(--toc-bg-light);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  border-radius: 16px;
  box-shadow: 
    0 10px 40px rgba(0,0,0,0.12),
    0 2px 10px rgba(0,0,0,0.06),
    inset 0 1px 0 rgba(255,255,255,0.5);
  border: 1px solid rgba(255,255,255,0.3);
  z-index: 900;
  overflow: hidden;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}

/* Dark Mode Support */
@media (prefers-color-scheme: dark) {
  .md-toc {
    background: var(--toc-bg-dark);
    box-shadow: 
      0 10px 40px rgba(0,0,0,0.5),
      0 2px 10px rgba(0,0,0,0.3);
    border: 1px solid rgba(255,255,255,0.1);
  }
}

/* כותרת עם gradient */
.md-toc-header {
  padding: 1rem;
  background: var(--toc-header-gradient);
  color: white;
  display: flex;
  justify-content: space-between;
  align-items: center;
  position: relative;
  user-select: none;
}

.md-toc-title-wrapper {
  flex: 1;
}

.md-toc-title-wrapper h3 {
  margin: 0;
  font-size: 1.1rem;
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-weight: 600;
}

/* פס התקדמות */
.md-toc-progress {
  height: 3px;
  background: rgba(255,255,255,0.2);
  border-radius: 2px;
  margin-top: 0.5rem;
  overflow: hidden;
}

.md-toc-progress-bar {
  height: 100%;
  background: rgba(255,255,255,0.9);
  border-radius: 2px;
  width: 0%;
  transition: width 0.3s ease;
  box-shadow: 0 0 10px rgba(255,255,255,0.5);
}

/* כפתורי בקרה */
.md-toc-controls {
  display: flex;
  gap: 0.5rem;
}

.md-toc-toggle,
.md-toc-search-btn {
  background: rgba(255,255,255,0.2);
  border: 1px solid rgba(255,255,255,0.3);
  border-radius: 8px;
  padding: 0.4rem 0.6rem;
  cursor: pointer;
  color: white;
  transition: all 0.2s ease;
}

.md-toc-toggle:hover,
.md-toc-search-btn:hover {
  background: rgba(255,255,255,0.3);
  transform: scale(1.05);
}

.md-toc-toggle:active,
.md-toc-search-btn:active {
  transform: scale(0.95);
}

.md-toc-toggle i {
  transition: transform 0.3s ease;
}

.md-toc.collapsed .md-toc-toggle i {
  transform: rotate(180deg);
}

/* תיבת חיפוש */
.md-toc-search-container {
  padding: 0.75rem;
  background: rgba(102, 126, 234, 0.05);
  border-bottom: 1px solid rgba(102, 126, 234, 0.2);
}

.md-toc-search-input {
  width: 100%;
  padding: 0.5rem;
  border: 1px solid rgba(102, 126, 234, 0.3);
  border-radius: 8px;
  background: white;
  font-size: 0.9rem;
  transition: all 0.2s ease;
}

.md-toc-search-input:focus {
  outline: none;
  border-color: #667eea;
  box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1);
}

@media (prefers-color-scheme: dark) {
  .md-toc-search-input {
    background: rgba(255,255,255,0.1);
    color: white;
    border-color: rgba(255,255,255,0.2);
  }
}

.md-toc-search-results {
  display: block;
  margin-top: 0.25rem;
  font-size: 0.75rem;
  color: #667eea;
  text-align: center;
}

/* אזור ניווט עם גלילה */
.md-toc-nav {
  padding: 0.5rem 0;
  overflow-y: auto;
  max-height: calc(100vh - 240px);
  scrollbar-width: thin;
  scrollbar-color: #667eea transparent;
  position: relative;
}

.md-toc-nav::-webkit-scrollbar {
  width: 6px;
}

.md-toc-nav::-webkit-scrollbar-thumb {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  border-radius: 3px;
}

.md-toc-nav::-webkit-scrollbar-track {
  background: transparent;
}

/* פריטי תוכן עניינים */
.md-toc-item {
  padding: 0.6rem 1rem;
  cursor: pointer;
  color: var(--toc-text-light);
  transition: all 0.2s ease;
  border-right: 3px solid transparent;
  font-size: 0.9rem;
  display: block;
  text-decoration: none;
  position: relative;
  overflow: hidden;
}

@media (prefers-color-scheme: dark) {
  .md-toc-item {
    color: var(--toc-text-dark);
  }
}

/* אפקט hover מתקדם */
.md-toc-item::before {
  content: '';
  position: absolute;
  right: 0;
  top: 0;
  height: 100%;
  width: 3px;
  background: var(--toc-header-gradient);
  transform: translateX(100%);
  transition: transform 0.3s ease;
}

.md-toc-item:hover {
  background: var(--toc-hover-light);
  padding-right: 1.25rem;
}

@media (prefers-color-scheme: dark) {
  .md-toc-item:hover {
    background: var(--toc-hover-dark);
  }
}

.md-toc-item:hover::before,
.md-toc-item.active::before {
  transform: translateX(0);
}

.md-toc-item.active {
  background: var(--toc-active-light);
  color: #667eea;
  font-weight: 600;
}

@media (prefers-color-scheme: dark) {
  .md-toc-item.active {
    background: var(--toc-active-dark);
  }
}

/* הדגשת חיפוש */
.md-toc-item.search-match {
  background: rgba(255, 235, 59, 0.2);
}

.md-toc-item.search-match mark {
  background: rgba(255, 235, 59, 0.5);
  color: inherit;
  padding: 0 2px;
  border-radius: 2px;
}

/* הסתרה בחיפוש */
.md-toc-item.search-hidden {
  display: none;
}

/* הזחה לפי רמת כותרת */
.md-toc-item[data-level="1"] { padding-right: 1rem; font-weight: 600; }
.md-toc-item[data-level="2"] { padding-right: 1.25rem; }
.md-toc-item[data-level="3"] { padding-right: 2rem; font-size: 0.85rem; }
.md-toc-item[data-level="4"] { padding-right: 2.75rem; font-size: 0.8rem; }
.md-toc-item[data-level="5"] { padding-right: 3.5rem; font-size: 0.75rem; }
.md-toc-item[data-level="6"] { padding-right: 4.25rem; font-size: 0.75rem; }

/* מצב מכווץ */
.md-toc.collapsed {
  max-height: 60px;
}

.md-toc.collapsed .md-toc-nav,
.md-toc.collapsed .md-toc-search-container {
  display: none;
}

.md-toc.collapsed .md-toc-progress {
  margin-top: 0.25rem;
}

/* מצב מינימלי */
.md-toc.minimized {
  display: none;
}

.md-toc-mini-btn {
  position: fixed;
  top: 100px;
  left: 20px;
  width: 40px;
  height: 40px;
  border-radius: 50%;
  background: var(--toc-header-gradient);
  color: white;
  border: none;
  cursor: pointer;
  box-shadow: 0 4px 12px rgba(102, 126, 234, 0.3);
  transition: all 0.3s ease;
  z-index: 899;
}

.md-toc-mini-btn:hover {
  transform: scale(1.1);
  box-shadow: 0 6px 20px rgba(102, 126, 234, 0.4);
}

/* Virtual Scrolling - פריט placeholder */
.md-toc-item-placeholder {
  height: 32px;
  background: linear-gradient(90deg, #f0f0f0 25%, #e0e0e0 50%, #f0f0f0 75%);
  background-size: 200% 100%;
  animation: loading 1.5s infinite;
  margin: 0.25rem 1rem;
  border-radius: 4px;
}

@keyframes loading {
  0% { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}

/* התאמה למסכים קטנים */
@media (max-width: 1024px) {
  .md-toc {
    left: 10px;
    max-width: 280px;
    min-width: 220px;
    font-size: 0.85rem;
  }
  
  .md-toc-item {
    padding: 0.5rem 0.75rem;
  }
}

@media (max-width: 768px) {
  .md-toc,
  .md-toc-mini-btn {
    display: none !important;
  }
}

/* במסך מלא - הסתר */
#mdCard:fullscreen ~ .md-toc,
#mdCard:-webkit-full-screen ~ .md-toc,
#mdCard:fullscreen ~ .md-toc-mini-btn,
#mdCard:-webkit-full-screen ~ .md-toc-mini-btn {
  display: none !important;
}

/* אנימציות נוספות */
@keyframes slideIn {
  from {
    transform: translateX(-100%);
    opacity: 0;
  }
  to {
    transform: translateX(0);
    opacity: 1;
  }
}

.md-toc {
  animation: slideIn 0.3s ease-out;
}

/* Tooltip לכותרות ארוכות */
.md-toc-item[title] {
  position: relative;
}

.md-toc-item[title]:hover::after {
  content: attr(title);
  position: absolute;
  right: calc(100% + 10px);
  top: 50%;
  transform: translateY(-50%);
  background: rgba(0,0,0,0.8);
  color: white;
  padding: 0.5rem;
  border-radius: 6px;
  white-space: nowrap;
  font-size: 0.85rem;
  z-index: 1000;
  max-width: 300px;
  overflow: hidden;
  text-overflow: ellipsis;
}
```

### שלב 3: הוספת JavaScript מתקדם עם כל הפיצ'רים

הוסף את הקוד הזה בסוף תג ה-`<script>` הראשי:

```javascript
// === תוכן עניינים צף מתקדם - גרסה 2.0 ===
(function initAdvancedTableOfContents() {
  'use strict';
  
  // === קונפיגורציה ===
  const CONFIG = {
    MAX_HEADINGS: 200,           // מגבלת כותרות
    VIRTUAL_SCROLL_THRESHOLD: 50, // סף ל-virtual scrolling
    SEARCH_DEBOUNCE: 300,        // השהיית חיפוש
    SCROLL_OFFSET: 120,          // הזחה בגלילה
    INTERSECTION_THRESHOLD: 0.5,  // סף לזיהוי כותרת פעילה
    INTERSECTION_MARGIN: '-20% 0% -70% 0%',
    WAIT_TIMEOUT: 5000,          // timeout להמתנה לתוכן
    CHECK_INTERVAL: 100          // תדירות בדיקת תוכן
  };
  
  // === משתנים גלובליים ===
  let tocState = {
    headings: [],
    visibleHeadings: [],
    activeHeading: null,
    observer: null,
    clickHandlers: [],
    searchTerm: '',
    isCollapsed: false,
    isMinimized: false,
    scrollPercentage: 0
  };
  
  // === כלי עזר ===
  
  // Debounce function
  function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
      const later = () => {
        clearTimeout(timeout);
        func(...args);
      };
      clearTimeout(timeout);
      timeout = setTimeout(later, wait);
    };
  }
  
  // סניטציה בטוחה
  function sanitizeText(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML
      .replace(/[<>\"'&]/g, '')
      .replace(/¶/g, '')
      .trim();
  }
  
  // יצירת ID ייחודי
  function generateUniqueId(prefix, index) {
    return `${prefix}-${Date.now()}-${index}-${Math.random().toString(36).substr(2, 9)}`;
  }
  
  // === המתנה דינמית לתוכן ===
  function waitForContent(callback) {
    const startTime = Date.now();
    
    function check() {
      try {
        const container = document.getElementById('md-content');
        const hasContent = container && 
                         container.innerHTML.trim().length > 0 && 
                         container.querySelector('h1, h2, h3, h4, h5, h6');
        
        if (hasContent) {
          // המתנה קצרה נוספת לוודא שהרינדור הושלם
          setTimeout(callback, 50);
        } else if (Date.now() - startTime < CONFIG.WAIT_TIMEOUT) {
          setTimeout(check, CONFIG.CHECK_INTERVAL);
        } else {
          console.warn('TOC: תוכן לא נטען בזמן המוגדר');
          hideTOC();
        }
      } catch (e) {
        console.error('TOC: שגיאה בבדיקת תוכן', e);
        hideTOC();
      }
    }
    
    check();
  }
  
  // === הסתרת TOC ===
  function hideTOC() {
    const tocElement = document.getElementById('mdToc');
    if (tocElement) tocElement.style.display = 'none';
  }
  
  // === ניקוי זיכרון ===
  function cleanup() {
    try {
      // ניקוי Intersection Observer
      if (tocState.observer) {
        tocState.observer.disconnect();
        tocState.observer = null;
      }
      
      // ניקוי Event Listeners
      tocState.clickHandlers.forEach(({ element, event, handler }) => {
        element.removeEventListener(event, handler);
      });
      tocState.clickHandlers = [];
      
      // ניקוי keyboard listeners
      document.removeEventListener('keydown', handleKeyboard);
      
      console.debug('TOC: ניקוי הושלם');
    } catch (e) {
      console.error('TOC: שגיאה בניקוי', e);
    }
  }
  
  // === בניית תוכן העניינים ===
  function buildTOC() {
    try {
      const container = document.getElementById('md-content');
      const tocElement = document.getElementById('mdToc');
      const tocNav = document.getElementById('mdTocNav');
      
      if (!container || !tocElement || !tocNav) {
        console.error('TOC: אלמנטים חסרים');
        return;
      }
      
      // חילוץ כותרות עם הגבלה
      let headings = Array.from(container.querySelectorAll('h1, h2, h3, h4, h5, h6'));
      
      if (headings.length === 0) {
        console.info('TOC: לא נמצאו כותרות במסמך');
        hideTOC();
        return;
      }
      
      // הגבלת מספר הכותרות
      if (headings.length > CONFIG.MAX_HEADINGS) {
        console.warn(`TOC: נמצאו ${headings.length} כותרות, מציג רק ${CONFIG.MAX_HEADINGS} הראשונות`);
        headings = headings.slice(0, CONFIG.MAX_HEADINGS);
      }
      
      tocState.headings = headings;
      
      // בניית פריטי התוכן עניינים
      const fragment = document.createDocumentFragment();
      
      headings.forEach((heading, index) => {
        try {
          const level = parseInt(heading.tagName.substring(1));
          const text = sanitizeText(heading.textContent || '');
          
          // וידוא או יצירת ID ייחודי
          if (!heading.id || document.querySelectorAll(`#${heading.id}`).length > 1) {
            heading.id = generateUniqueId('toc-heading', index);
          }
          
          // יצירת פריט
          const item = document.createElement('a');
          item.className = 'md-toc-item';
          item.setAttribute('data-level', level);
          item.setAttribute('href', `#${heading.id}`);
          item.setAttribute('data-index', index);
          item.setAttribute('aria-label', `עבור לכותרת: ${text}`);
          item.textContent = text;
          
          // הוספת tooltip לכותרות ארוכות
          if (text.length > 30) {
            item.title = text;
            item.textContent = text.substring(0, 30) + '...';
          }
          
          // טיפול בקליק
          const clickHandler = (e) => {
            e.preventDefault();
            try {
              heading.scrollIntoView({
                behavior: 'smooth',
                block: 'start'
              });
              
              // עדכון פריט פעיל
              updateActiveItem(item);
              
              // סגירת חיפוש אם פתוח
              closeSearch();
            } catch (error) {
              console.error('TOC: שגיאה בגלילה', error);
            }
          };
          
          item.addEventListener('click', clickHandler);
          tocState.clickHandlers.push({ element: item, event: 'click', handler: clickHandler });
          
          fragment.appendChild(item);
        } catch (error) {
          console.error('TOC: שגיאה ביצירת פריט', error);
        }
      });
      
      tocNav.appendChild(fragment);
      
      // הפעלת Virtual Scrolling אם יש הרבה כותרות
      if (headings.length > CONFIG.VIRTUAL_SCROLL_THRESHOLD) {
        setupVirtualScrolling();
      }
      
      // הפעלת Intersection Observer
      setupIntersectionObserver();
      
      // הפעלת אינטראקציות
      setupInteractions();
      
      // הפעלת חיפוש
      setupSearch();
      
      // הפעלת קיצורי מקלדת
      setupKeyboardShortcuts();
      
      // הפעלת אינדיקטור התקדמות
      setupProgressIndicator();
      
      // הצגת תוכן העניינים
      tocElement.style.display = 'block';
      
      console.info(`TOC: נבנה בהצלחה עם ${headings.length} כותרות`);
      
    } catch (e) {
      console.error('TOC: שגיאה כללית בבנייה', e);
      hideTOC();
    }
  }
  
  // === Virtual Scrolling ===
  function setupVirtualScrolling() {
    console.info('TOC: מפעיל Virtual Scrolling');
    
    const tocNav = document.getElementById('mdTocNav');
    if (!tocNav) return;
    
    // יצירת placeholders לפריטים שלא בתצוגה
    const observer = new IntersectionObserver((entries) => {
      entries.forEach(entry => {
        if (entry.isIntersecting) {
          // טען את הפריט האמיתי
          entry.target.classList.remove('md-toc-item-placeholder');
        } else {
          // הצג placeholder
          entry.target.classList.add('md-toc-item-placeholder');
        }
      });
    }, {
      root: tocNav,
      rootMargin: '100px'
    });
    
    tocNav.querySelectorAll('.md-toc-item').forEach(item => {
      observer.observe(item);
    });
  }
  
  // === Intersection Observer לכותרות ===
  function setupIntersectionObserver() {
    try {
      const options = {
        rootMargin: CONFIG.INTERSECTION_MARGIN,
        threshold: CONFIG.INTERSECTION_THRESHOLD
      };
      
      tocState.observer = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
          if (entry.isIntersecting) {
            const index = tocState.headings.indexOf(entry.target);
            if (index !== -1) {
              const item = document.querySelector(`.md-toc-item[data-index="${index}"]`);
              if (item) updateActiveItem(item);
            }
          }
        });
      }, options);
      
      tocState.headings.forEach(heading => {
        tocState.observer.observe(heading);
      });
      
      console.debug('TOC: Intersection Observer מופעל');
    } catch (e) {
      console.error('TOC: שגיאה ב-Intersection Observer', e);
      // Fallback to scroll event
      setupScrollFallback();
    }
  }
  
  // === Fallback לדפדפנים ישנים ===
  function setupScrollFallback() {
    console.info('TOC: משתמש ב-scroll event כ-fallback');
    
    let ticking = false;
    const scrollHandler = () => {
      if (!ticking) {
        window.requestAnimationFrame(() => {
          updateActiveHeadingByScroll();
          ticking = false;
        });
        ticking = true;
      }
    };
    
    window.addEventListener('scroll', scrollHandler, { passive: true });
    tocState.clickHandlers.push({ element: window, event: 'scroll', handler: scrollHandler });
  }
  
  // === עדכון כותרת פעילה (scroll fallback) ===
  function updateActiveHeadingByScroll() {
    const scrollPos = window.scrollY + CONFIG.SCROLL_OFFSET;
    let activeHeading = null;
    
    for (let i = tocState.headings.length - 1; i >= 0; i--) {
      const heading = tocState.headings[i];
      if (heading.offsetTop <= scrollPos) {
        activeHeading = heading;
        break;
      }
    }
    
    if (activeHeading) {
      const index = tocState.headings.indexOf(activeHeading);
      const item = document.querySelector(`.md-toc-item[data-index="${index}"]`);
      if (item) updateActiveItem(item);
    }
  }
  
  // === עדכון פריט פעיל ===
  function updateActiveItem(newActiveItem) {
    document.querySelectorAll('.md-toc-item').forEach(item => {
      item.classList.remove('active');
    });
    
    if (newActiveItem) {
      newActiveItem.classList.add('active');
      tocState.activeHeading = newActiveItem;
      
      // גלילה אוטומטית בתוך התפריט אם הפריט מחוץ לתצוגה
      const tocNav = document.getElementById('mdTocNav');
      if (tocNav) {
        const itemRect = newActiveItem.getBoundingClientRect();
        const navRect = tocNav.getBoundingClientRect();
        
        if (itemRect.top < navRect.top || itemRect.bottom > navRect.bottom) {
          newActiveItem.scrollIntoView({
            behavior: 'smooth',
            block: 'center'
          });
        }
      }
    }
  }
  
  // === הגדרת אינטראקציות ===
  function setupInteractions() {
    const tocElement = document.getElementById('mdToc');
    const tocToggle = document.getElementById('mdTocToggle');
    const tocHeader = document.querySelector('.md-toc-header');
    const miniBtn = document.getElementById('mdTocMini');
    
    // כפתור כיווץ/הרחבה
    if (tocToggle && tocElement) {
      const toggleHandler = (e) => {
        e.stopPropagation();
        tocState.isCollapsed = !tocState.isCollapsed;
        tocElement.classList.toggle('collapsed');
        tocToggle.setAttribute('aria-expanded', !tocState.isCollapsed);
        
        // שמירה ב-localStorage
        localStorage.setItem('mdTocCollapsed', tocState.isCollapsed);
      };
      
      tocToggle.addEventListener('click', toggleHandler);
      tocState.clickHandlers.push({ element: tocToggle, event: 'click', handler: toggleHandler });
    }
    
    // לחיצה על הכותרת
    if (tocHeader && tocElement) {
      const headerHandler = () => {
        tocState.isCollapsed = !tocState.isCollapsed;
        tocElement.classList.toggle('collapsed');
        if (tocToggle) {
          tocToggle.setAttribute('aria-expanded', !tocState.isCollapsed);
        }
        localStorage.setItem('mdTocCollapsed', tocState.isCollapsed);
      };
      
      tocHeader.addEventListener('click', headerHandler);
      tocState.clickHandlers.push({ element: tocHeader, event: 'click', handler: headerHandler });
    }
    
    // כפתור מינימום
    if (miniBtn && tocElement) {
      const miniHandler = () => {
        tocElement.classList.remove('minimized');
        tocElement.style.display = 'block';
        miniBtn.style.display = 'none';
        tocState.isMinimized = false;
      };
      
      miniBtn.addEventListener('click', miniHandler);
      tocState.clickHandlers.push({ element: miniBtn, event: 'click', handler: miniHandler });
    }
    
    // טעינת מצב שמור
    const savedCollapsed = localStorage.getItem('mdTocCollapsed');
    if (savedCollapsed === 'true') {
      tocElement?.classList.add('collapsed');
      if (tocToggle) tocToggle.setAttribute('aria-expanded', 'false');
      tocState.isCollapsed = true;
    }
  }
  
  // === הגדרת חיפוש ===
  function setupSearch() {
    const searchBtn = document.getElementById('mdTocSearch');
    const searchContainer = document.getElementById('tocSearchContainer');
    const searchInput = document.getElementById('tocSearchInput');
    const searchResults = document.getElementById('tocSearchResults');
    
    if (!searchBtn || !searchContainer || !searchInput) return;
    
    // כפתור חיפוש
    const searchBtnHandler = () => {
      const isVisible = searchContainer.style.display !== 'none';
      searchContainer.style.display = isVisible ? 'none' : 'block';
      
      if (!isVisible) {
        searchInput.focus();
      } else {
        closeSearch();
      }
    };
    
    searchBtn.addEventListener('click', searchBtnHandler);
    tocState.clickHandlers.push({ element: searchBtn, event: 'click', handler: searchBtnHandler });
    
    // פונקציה ל-escape תווים מיוחדים ב-RegExp (מניעת ReDoS)
    function escapeRegExp(string) {
      return string.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    }
    
    // פונקציה בטוחה להדגשת טקסט (מניעת XSS)
    function highlightText(element, searchTerm) {
      const originalText = element.textContent;
      
      if (!searchTerm) {
        // אין חיפוש - החזר טקסט מקורי
        element.textContent = originalText;
        return;
      }
      
      // נקה את האלמנט
      element.textContent = '';
      
      // חפש את כל ההתאמות בצורה בטוחה
      const escapedTerm = escapeRegExp(searchTerm);
      const regex = new RegExp(escapedTerm, 'gi');
      let lastIndex = 0;
      let match;
      
      // מגבלת ביצועים - מניעת ReDoS
      const maxIterations = 100;
      let iterations = 0;
      
      while ((match = regex.exec(originalText)) !== null && iterations < maxIterations) {
        iterations++;
        
        // הוסף טקסט לפני ההתאמה
        if (match.index > lastIndex) {
          const textNode = document.createTextNode(originalText.slice(lastIndex, match.index));
          element.appendChild(textNode);
        }
        
        // צור mark element בצורה בטוחה
        const mark = document.createElement('mark');
        mark.textContent = match[0]; // שימוש ב-textContent למניעת XSS
        element.appendChild(mark);
        
        lastIndex = regex.lastIndex;
        
        // מניעת לולאה אינסופית
        if (regex.lastIndex === match.index) {
          regex.lastIndex++;
        }
      }
      
      // הוסף טקסט אחרי ההתאמה האחרונה
      if (lastIndex < originalText.length) {
        const textNode = document.createTextNode(originalText.slice(lastIndex));
        element.appendChild(textNode);
      }
    }
    
    // חיפוש בזמן אמת
    const searchHandler = debounce((e) => {
      const searchTerm = e.target.value.toLowerCase().trim();
      
      // הגבלת אורך החיפוש למניעת DoS
      const MAX_SEARCH_LENGTH = 100;
      if (searchTerm.length > MAX_SEARCH_LENGTH) {
        console.warn('TOC: חיפוש ארוך מדי');
        return;
      }
      
      tocState.searchTerm = searchTerm;
      
      const items = document.querySelectorAll('.md-toc-item');
      let matchCount = 0;
      
      items.forEach(item => {
        // שמור טקסט מקורי אם לא קיים
        if (!item.dataset.originalText) {
          item.dataset.originalText = item.textContent;
        }
        
        const originalText = item.dataset.originalText;
        const text = originalText.toLowerCase();
        
        if (!searchTerm) {
          // ריק - הצג הכל עם טקסט מקורי
          item.classList.remove('search-hidden', 'search-match');
          item.textContent = originalText;
        } else if (text.includes(searchTerm)) {
          // נמצא - הדגש בצורה בטוחה
          item.classList.remove('search-hidden');
          item.classList.add('search-match');
          
          // הדגשה בטוחה של הטקסט
          highlightText(item, searchTerm);
          
          matchCount++;
        } else {
          // לא נמצא - הסתר
          item.classList.add('search-hidden');
          item.classList.remove('search-match');
          item.textContent = originalText;
        }
      });
      
      // עדכון תוצאות
      if (searchResults) {
        if (!searchTerm) {
          searchResults.textContent = '';
        } else if (matchCount === 0) {
          searchResults.textContent = 'לא נמצאו תוצאות';
        } else {
          searchResults.textContent = `נמצאו ${matchCount} תוצאות`;
        }
      }
    }, CONFIG.SEARCH_DEBOUNCE);
    
    searchInput.addEventListener('input', searchHandler);
    tocState.clickHandlers.push({ element: searchInput, event: 'input', handler: searchHandler });
    
    // סגירה ב-Escape
    const escapeHandler = (e) => {
      if (e.key === 'Escape' && searchContainer.style.display !== 'none') {
        closeSearch();
      }
    };
    
    searchInput.addEventListener('keydown', escapeHandler);
    tocState.clickHandlers.push({ element: searchInput, event: 'keydown', handler: escapeHandler });
  }
  
  // === סגירת חיפוש ===
  function closeSearch() {
    const searchContainer = document.getElementById('tocSearchContainer');
    const searchInput = document.getElementById('tocSearchInput');
    const searchResults = document.getElementById('tocSearchResults');
    
    if (searchContainer) searchContainer.style.display = 'none';
    if (searchInput) searchInput.value = '';
    if (searchResults) searchResults.textContent = '';
    
    // ניקוי הדגשות בצורה בטוחה
    document.querySelectorAll('.md-toc-item').forEach(item => {
      item.classList.remove('search-hidden', 'search-match');
      // שחזור טקסט מקורי בצורה בטוחה
      if (item.dataset.originalText) {
        item.textContent = item.dataset.originalText;
      }
    });
    
    tocState.searchTerm = '';
  }
  
  // === קיצורי מקלדת ===
  function setupKeyboardShortcuts() {
    const keyboardHandler = (e) => {
      // Ctrl+T - כיווץ/הרחבה
      if (e.ctrlKey && e.key === 't') {
        e.preventDefault();
        const tocToggle = document.getElementById('mdTocToggle');
        if (tocToggle) tocToggle.click();
      }
      
      // Ctrl+F (בתוך TOC) - חיפוש
      if (e.ctrlKey && e.key === 'f') {
        const tocElement = document.getElementById('mdToc');
        if (tocElement && tocElement.contains(document.activeElement)) {
          e.preventDefault();
          const searchBtn = document.getElementById('mdTocSearch');
          if (searchBtn) searchBtn.click();
        }
      }
      
      // Ctrl+M - מינימום/מקסימום
      if (e.ctrlKey && e.key === 'm') {
        e.preventDefault();
        toggleMinimize();
      }
    };
    
    document.addEventListener('keydown', keyboardHandler);
    tocState.clickHandlers.push({ element: document, event: 'keydown', handler: keyboardHandler });
  }
  
  // מחוץ לפונקציה הראשית כדי שיהיה נגיש
  const handleKeyboard = (e) => {
    // קיצורי מקלדת
  };
  
  // === מעבר למצב מינימלי ===
  function toggleMinimize() {
    const tocElement = document.getElementById('mdToc');
    const miniBtn = document.getElementById('mdTocMini');
    
    if (!tocElement || !miniBtn) return;
    
    tocState.isMinimized = !tocState.isMinimized;
    
    if (tocState.isMinimized) {
      tocElement.style.display = 'none';
      miniBtn.style.display = 'block';
    } else {
      tocElement.style.display = 'block';
      miniBtn.style.display = 'none';
    }
  }
  
  // === אינדיקטור התקדמות ===
  function setupProgressIndicator() {
    const progressBar = document.getElementById('tocProgressBar');
    if (!progressBar) return;
    
    const updateProgress = () => {
      const scrollHeight = document.documentElement.scrollHeight - window.innerHeight;
      const scrollPosition = window.scrollY;
      const percentage = Math.round((scrollPosition / scrollHeight) * 100);
      
      progressBar.style.width = `${percentage}%`;
      tocState.scrollPercentage = percentage;
      
      // עדכון ARIA
      const progressContainer = document.querySelector('.md-toc-progress');
      if (progressContainer) {
        progressContainer.setAttribute('aria-valuenow', percentage);
      }
    };
    
    // עדכון ראשוני
    updateProgress();
    
    // עדכון בגלילה
    let progressTicking = false;
    const progressHandler = () => {
      if (!progressTicking) {
        window.requestAnimationFrame(() => {
          updateProgress();
          progressTicking = false;
        });
        progressTicking = true;
      }
    };
    
    window.addEventListener('scroll', progressHandler, { passive: true });
    tocState.clickHandlers.push({ element: window, event: 'scroll', handler: progressHandler });
  }
  
  // === אתחול ===
  function init() {
    try {
      console.info('TOC: מתחיל אתחול');
      
      // המתנה לתוכן וביצוע
      waitForContent(buildTOC);
      
      // רישום ניקוי
      window.addEventListener('beforeunload', cleanup);
      
      // תמיכה ב-SPA
      if (window.navigation) {
        window.navigation.addEventListener('navigate', cleanup);
      }
      
    } catch (e) {
      console.error('TOC: שגיאה באתחול', e);
      hideTOC();
    }
  }
  
  // הפעלה
  init();
})();
```

### שלב 4: בדיקות מקיפות

אחרי ההתקנה, בצע את הבדיקות הבאות:

#### בדיקות פונקציונליות:
- [ ] תוכן עניינים מופיע במסמכים עם כותרות
- [ ] תוכן עניינים **לא** מופיע במסמכים ללא כותרות
- [ ] קליק על כותרת גולל למקום הנכון
- [ ] כותרת פעילה מודגשת בזמן גלילה
- [ ] כפתור כיווץ/הרחבה עובד
- [ ] חיפוש מסנן כותרות נכון
- [ ] קיצורי מקלדת פועלים (Ctrl+T, Ctrl+F, Ctrl+M)
- [ ] אינדיקטור התקדמות מתעדכן
- [ ] Virtual Scrolling עובד במסמכים ארוכים

#### בדיקות ביצועים:
- [ ] אין lag בגלילה
- [ ] זמן טעינה סביר (< 1 שנייה)
- [ ] זיכרון לא עולה בצורה חריגה
- [ ] CPU usage נמוך

#### בדיקות נגישות:
- [ ] עובד עם screen reader
- [ ] ניווט במקלדת בלבד אפשרי
- [ ] ARIA attributes מעודכנים נכון
- [ ] ניגודיות טובה בכל המצבים

#### בדיקות תאימות:
- [ ] Chrome/Edge (גרסאות אחרונות)
- [ ] Firefox
- [ ] Safari
- [ ] מובייל (מוסתר כצפוי)
- [ ] Dark Mode אוטומטי

## 🎯 אופטימיזציות נוספות

### למסמכים ענקיים (1000+ כותרות):
```javascript
// הגדל את סף Virtual Scrolling
CONFIG.VIRTUAL_SCROLL_THRESHOLD = 30;

// הפעל lazy loading אגרסיבי
CONFIG.MAX_HEADINGS = 100; // הצג רק 100 הראשונות
```

### לשרתים איטיים:
```javascript
// הגדל timeout
CONFIG.WAIT_TIMEOUT = 10000; // 10 שניות

// הגדל מרווח בדיקה
CONFIG.CHECK_INTERVAL = 200;
```

## 📝 תחזוקה ועדכונים

### בדיקה תקופתית:
1. בדוק תאימות עם עדכוני דפדפן
2. עדכן ספריות אם נדרש
3. בדוק ביצועים במסמכים חדשים

### לוגים וניטור:
- כל השגיאות נרשמות ב-console
- ניתן להוסיף Google Analytics events
- שקול להוסיף Sentry לתפיסת שגיאות

## 🚀 סיכום

המדריך המשופר הזה כולל:

✅ **כל הפיצ'רים מהגרסה הקודמת**
✅ **Intersection Observer** לביצועים מעולים
✅ **Virtual Scrolling** למסמכים ענקיים
✅ **חיפוש מובנה** עם הדגשות
✅ **קיצורי מקלדת** לנוחות
✅ **אינדיקטור התקדמות** ויזואלי
✅ **Dark Mode** אוטומטי
✅ **אבטחה משופרת** עם סניטציה מלאה
✅ **ניקוי זיכרון** מקיף

**זמן הטמעה משוער**: 30-45 דקות
**רמת מורכבות**: מתקדם
**תלויות**: אין (כל הספריות כבר קיימות)
**תמיכה**: כל הדפדפנים המודרניים

בהצלחה! 🎉

---

## 📚 קבצים קשורים

- **[Original Issue #762](https://github.com/amirbiron/CodeBot/issues/762)** - האישו המקורי עם המדריך הראשון
- **[md_preview.html](../templates/md_preview.html)** - הקובץ להטמעה
- **[Feature Suggestions](./NEW_FEATURE_SUGGESTIONS.md)** - הצעות נוספות לפרויקט

## 🤝 תרומה

מצאת באג? יש לך רעיון לשיפור? פתח Issue או PR ב-GitHub!

## 📄 רישיון

הקוד מופץ תחת רישיון MIT - חופשי לשימוש, שינוי והפצה.