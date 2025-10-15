# שאלות ותשובות נפוצות (FAQ) - תוכן עניינים צף

## 🤔 שאלות כלליות

### ש: למה תוכן העניינים לא מופיע?

יש כמה סיבות אפשריות:

1. **אין כותרות במסמך** - תוכן העניינים מופיע רק אם יש H1-H6 במרקדאון
   ```markdown
   # זו כותרת H1
   ## זו כותרת H2
   ```

2. **אתה במובייל** - תוכן העניינים מוסתר אוטומטית במסכים קטנים מ-768px
   
3. **אתה במסך מלא** - כשהמסמך במצב fullscreen, תוכן העניינים מוסתר

4. **הקוד לא הוסף נכון** - בדוק ב-Console (F12) אם יש שגיאות

### ש: איך אני בודק אם זה עובד?

פתח את Console (F12) וחפש הודעות אלה:

```javascript
// אם הכל תקין:
(שום דבר - אין הודעות שגיאה)

// אם יש בעיה:
"TOC: אלמנטים חסרים" = ה-HTML לא הוסף
"TOC: לא נמצאו כותרות במסמך" = אין כותרות להציג
"TOC: תוכן לא נטען בזמן המוגדר" = הרינדור לוקח יותר מ-5 שניות
```

### ש: למה הגלילה לא עובדת?

אם קליק על כותרת לא גולל, בדוק:

1. **יש JS errors?** פתח Console וחפש שגיאות אדומות
2. **CSS conflicts?** אולי יש `overflow: hidden` על `body` או `html`
3. **הכותרות אין להן ID?** הקוד אמור ליצור IDs אוטומטית, אבל בדוק

פתרון זמני:
```javascript
// בדוק אם הכותרות קיבלו IDs:
document.querySelectorAll('h1, h2, h3, h4, h5, h6').forEach((h, i) => {
  console.log(h.id || 'NO ID', h.textContent);
});
```

---

## ⚙️ שאלות טכניות

### ש: איך אני יודע אם יש Memory Leak?

פתח **Chrome DevTools** → **Performance** → **Record** → גלול במסמך → **Stop**:

```
אם יש memory leak:
- ה-Heap Size ימשיך לעלות
- ה-Event Listeners יצטברו (תראה מספרים גדלים)

אם הכל תקין:
- ה-Heap Size יישאר יציב
- מספר ה-Event Listeners קבוע
```

### ש: למה הגרסה המשופרת יותר טובה מהמקורית?

**בקצרה**: בטיחות, מהירות, נגישות.

| תכונה | מקורי | משופר |
|-------|-------|-------|
| Error handling | חלקי | מלא |
| טעינה | 500ms תמיד | 50-500ms דינמי |
| נגישות | בסיסי | WCAG 2.1 |
| Memory | דליפות | נקי |
| ביצועים | 60 calls/sec | 10 calls/sec |

**פירוט מלא**: ראה `TOC_IMPROVEMENTS_SUMMARY.md`

### ש: מה זה Throttle ולמה אני צריך אותו?

**Throttle** = הגבלת קצב הפעלה של פונקציה.

**דוגמה ללא Throttle**:
```
גלילה → אירוע
גלילה → אירוע
גלילה → אירוע (100 פעמים בשנייה!)
```

**עם Throttle (100ms)**:
```
גלילה → אירוע
גלילה → ❌ (נחסם)
גלילה → ❌ (נחסם)
גלילה → ❌ (נחסם)
גלילה → ❌ (נחסם)
גלילה → ❌ (נחסם)
גלילה → ❌ (נחסם)
גלילה → ❌ (נחסם)
גלילה → ❌ (נחסם)
גלילה → אירוע (100ms עברו)
```

**תוצאה**: 90% פחות עומס על הדפדפן = חלק וזורם! 🚀

### ש: מה ההבדל בין Throttle ל-Debounce?

```javascript
// Debounce = ממתין עד שהמשתמש "מפסיק"
const debounce = (func, delay) => {
  let timeoutId;
  return (...args) => {
    clearTimeout(timeoutId);
    timeoutId = setTimeout(() => func(...args), delay);
  };
};

// Throttle = מריץ כל X זמן
const throttle = (func, delay) => {
  let lastRun = 0;
  return (...args) => {
    const now = Date.now();
    if (now - lastRun >= delay) {
      func(...args);
      lastRun = now;
    }
  };
};
```

**מתי להשתמש במה?**
- **Throttle**: גלילה, resize, mousemove (רוצים עדכון בזמן אמת)
- **Debounce**: חיפוש, autocomplete (רוצים לחכות שהמשתמש יסיים)

---

## 🎨 שאלות עיצוב

### ש: איך אני משנה את הצבעים?

עדכן את ה-CSS:

```css
/* צבע הכותרת */
.md-toc-header {
  background: linear-gradient(135deg, #FF6B6B 0%, #4ECDC4 100%);
}

/* צבע הפריטים */
.md-toc-item {
  color: #2c3e50;
}

/* צבע hover */
.md-toc-item:hover {
  background: rgba(78, 205, 196, 0.1);
  color: #4ECDC4;
  border-right-color: #4ECDC4;
}

/* צבע פריט פעיל */
.md-toc-item.active {
  background: rgba(78, 205, 196, 0.2);
  color: #4ECDC4;
  border-right-color: #4ECDC4;
}
```

### ש: איך אני משנה את המיקום לצד ימין?

```css
.md-toc {
  left: auto;       /* ביטול שמאל */
  right: 20px;      /* מיקום ימין */
}

/* שינוי כיוון הגבול */
.md-toc-item {
  border-right: none;
  border-left: 3px solid transparent;
}

.md-toc-item:hover,
.md-toc-item.active {
  border-left-color: #667eea;
  padding-left: 1.25rem;
  padding-right: 1rem;
}
```

### ש: איך אני מסתיר את תוכן העניינים בטאבלט?

```css
/* הסתרה במסכים עד 1024px */
@media (max-width: 1024px) {
  .md-toc {
    display: none !important;
  }
}
```

### ש: איך אני מוסיף אייקונים לכותרות?

```javascript
// בפונקציה buildTOC, שנה את:
item.textContent = text.replace(/¶/g, '').trim();

// ל:
const icon = document.createElement('i');
icon.className = 'fas fa-angle-left';
icon.style.marginLeft = '0.5rem';
item.textContent = text.replace(/¶/g, '').trim();
item.insertBefore(icon, item.firstChild);
```

---

## 🐛 פתרון בעיות

### בעיה: "Cannot read property 'querySelectorAll' of null"

**סיבה**: הקוד רץ לפני שה-DOM מוכן.

**פתרון**:
```javascript
// ודא שהקוד בתוך:
document.addEventListener('DOMContentLoaded', () => {
  // הקוד כאן
});

// או בתוך async IIFE עם המתנה:
(async function() {
  await new Promise(resolve => {
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', resolve);
    } else {
      resolve();
    }
  });
  
  // הקוד כאן
})();
```

### בעיה: תוכן העניינים מופיע אבל ריק

**סיבה**: הכותרות נטענות אחרי שהקוד רץ.

**פתרון**: הקוד המשופר כבר מטפל בזה עם `waitForContent()`:
```javascript
// הקוד בודק כל 100ms עד 5 שניות
function waitForContent(callback, maxWait = 5000) {
  // ... (כבר קיים בגרסה המשופרת)
}
```

### בעיה: הגלילה "קופצת" במקום חלקה

**סיבה**: CSS Scroll Behavior לא מוגדר.

**פתרון**:
```css
/* הוסף ל-CSS הכללי */
html {
  scroll-behavior: smooth;
}

/* או ב-JS: */
heading.scrollIntoView({ 
  behavior: 'smooth',  /* ← חשוב! */
  block: 'start' 
});
```

### בעיה: ההדגשה לא משתנה בגלילה

**סיבה**: הפונקציה `updateActiveHeading` לא רצה.

**בדיקה**:
```javascript
// הוסף בתוך updateActiveHeading:
console.log('Scroll pos:', window.scrollY);
console.log('Active heading:', activeHeading?.textContent);
```

**פתרון אפשרי**: שנה את ה-offset:
```javascript
// במקום:
const scrollPos = window.scrollY + 120;

// נסה:
const scrollPos = window.scrollY + 200;  // הגדל את המספר
```

---

## 📱 שאלות מובייל

### ש: למה תוכן העניינים לא מופיע במובייל?

**תשובה**: זה מכוון! במסכים קטנים זה תופס יותר מדי מקום.

אם בכל זאת רוצה להציג:
```css
/* הסר את השורה הזו: */
@media (max-width: 768px) {
  .md-toc {
    display: none !important;  /* ← מחק את זה */
  }
}

/* והוסף: */
@media (max-width: 768px) {
  .md-toc {
    position: fixed;
    bottom: 20px;
    right: 20px;
    left: auto;
    top: auto;
    max-width: 200px;
    font-size: 0.8rem;
  }
}
```

### ש: איך אני מוסיף כפתור toggle במובייל?

```html
<!-- הוסף כפתור צף: -->
<button id="mdTocMobileToggle" 
        style="position:fixed;bottom:20px;right:20px;z-index:1000;"
        class="btn btn-primary">
  <i class="fas fa-list"></i>
</button>

<script>
const mobileToggle = document.getElementById('mdTocMobileToggle');
const toc = document.getElementById('mdToc');

if (mobileToggle && toc) {
  mobileToggle.addEventListener('click', () => {
    toc.classList.toggle('mobile-visible');
  });
}
</script>

<style>
@media (max-width: 768px) {
  .md-toc {
    display: none;
  }
  
  .md-toc.mobile-visible {
    display: block !important;
    position: fixed;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
    max-height: 80vh;
    z-index: 999;
  }
}
</style>
```

---

## 🔧 שאלות מתקדמות

### ש: איך אני מוסיף מספור לכותרות?

```javascript
// בתוך buildTOC, שנה:
headings.forEach((heading, index) => {
  // ... קוד קיים
  
  // הוסף מספור:
  const number = document.createElement('span');
  number.className = 'toc-number';
  number.textContent = `${index + 1}. `;
  number.style.marginLeft = '0.5rem';
  number.style.fontWeight = 'bold';
  number.style.color = '#667eea';
  
  item.insertBefore(number, item.firstChild);
});
```

### ש: איך אני מסנן רק H2 ו-H3?

```javascript
// שנה:
const headings = Array.from(container.querySelectorAll('h1, h2, h3, h4, h5, h6'));

// ל:
const headings = Array.from(container.querySelectorAll('h2, h3'));
```

### ש: איך אני שומר את מצב הכיווץ?

```javascript
// בפונקציה cleanupTOC או בסוף הקוד:
const isCollapsed = tocElement.classList.contains('collapsed');
localStorage.setItem('mdTocCollapsed', isCollapsed);

// בתחילת buildTOC:
const savedCollapsed = localStorage.getItem('mdTocCollapsed') === 'true';
if (savedCollapsed) {
  tocElement.classList.add('collapsed');
  tocToggle.setAttribute('aria-expanded', 'false');
}
```

### ש: איך אני מוסיף progress bar?

```javascript
// הוסף ל-HTML:
<div class="md-toc-progress" style="height:3px;background:#667eea;width:0;transition:width 0.3s;"></div>

// בתוך updateActiveHeading:
const progress = document.querySelector('.md-toc-progress');
if (progress) {
  const winHeight = window.innerHeight;
  const docHeight = document.documentElement.scrollHeight;
  const scrolled = window.scrollY;
  const percentage = (scrolled / (docHeight - winHeight)) * 100;
  progress.style.width = percentage + '%';
}
```

---

## 💡 טיפים ונקודות חכמות

### טיפ 1: הוספת מקש קיצור (Ctrl+T)

```javascript
document.addEventListener('keydown', (e) => {
  if (e.ctrlKey && e.key === 't') {
    e.preventDefault();
    const toc = document.getElementById('mdToc');
    if (toc) {
      toc.classList.toggle('collapsed');
    }
  }
});
```

### טיפ 2: אנימציה נחמדה לפתיחה

```css
.md-toc {
  animation: slideIn 0.3s ease-out;
}

@keyframes slideIn {
  from {
    opacity: 0;
    transform: translateX(-20px);
  }
  to {
    opacity: 1;
    transform: translateX(0);
  }
}
```

### טיפ 3: סימון כמה כותרות קרובות

```javascript
// במקום להדגיש רק אחת, הדגש את הקרובות ביותר:
const PROXIMITY_RANGE = 200; // פיקסלים
tocNav.querySelectorAll('.md-toc-item').forEach(item => {
  const headingId = item.getAttribute('href').substring(1);
  const heading = document.getElementById(headingId);
  if (heading) {
    const distance = Math.abs(heading.offsetTop - scrollPos);
    if (distance < PROXIMITY_RANGE) {
      item.style.opacity = 1 - (distance / PROXIMITY_RANGE) * 0.5;
    } else {
      item.style.opacity = 0.5;
    }
  }
});
```

---

## 📚 משאבים נוספים

### קבצי המדריך:
1. **[FLOATING_TOC_IMPLEMENTATION_GUIDE.md](FLOATING_TOC_IMPLEMENTATION_GUIDE.md)** - מדריך יישום מלא
2. **[TOC_IMPROVEMENTS_SUMMARY.md](TOC_IMPROVEMENTS_SUMMARY.md)** - השוואה בין גרסאות
3. **[TOC_FAQ.md](TOC_FAQ.md)** (הקובץ הזה) - שאלות ותשובות נפוצות

### קישורים חיצוניים:
- [ARIA Best Practices](https://www.w3.org/WAI/ARIA/apg/)
- [Intersection Observer API](https://developer.mozilla.org/en-US/docs/Web/API/Intersection_Observer_API) - חלופה מתקדמת יותר
- [WCAG 2.1 Guidelines](https://www.w3.org/WAI/WCAG21/quickref/)
- [Web Performance Best Practices](https://web.dev/performance/)

---

**לא מצאת תשובה?** פתח issue או צור קשר! 📧
