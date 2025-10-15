# מדריך: הוספת תוכן עניינים צף לתצוגת Markdown

## סקירה כללית

המדריך הזה מסביר איך להוסיף תוכן עניינים (Table of Contents) צף לתצוגת הקבצים במרקדאון ב-webapp. התוכן עניינים יהיה חכם - יופיע רק כשיש כותרות במסמך, ויכלול אפשרויות לכיווץ/הרחבה וגלילה אוטומטית.

## איך זה עובד עכשיו?

כרגע, הקובץ `webapp/templates/md_preview.html` מציג קבצי markdown באמצעות:
- **markdown-it** - ספריית רינדור מרקדאון
- **markdown-it-anchor** - מוסיף עוגנים (anchors) לכותרות
- **markdown-it-toc-done-right** - תמיכה בתוכן עניינים (אבל כרגע לא בשימוש אקטיבי)

הקובץ כבר טוען את הספריות הנחוצות, אז כל מה שצריך זה להוסיף את רכיב התוכן עניינים עצמו!

## מה נוסיף?

1. **רכיב UI צף** - פאנל צד שמכיל את תוכן העניינים
2. **חילוץ כותרות** - קוד JS שיאסוף את כל הכותרות מהמסמך
3. **ניווט חכם** - קליק על כותרת יגלול אליה בצורה חלקה
4. **הדגשה פעילה** - הכותרת הנוכחית תודגש תוך כדי גלילה
5. **עיצוב מותאם** - תוכן עניינים שנראה טוב ועובד גם במובייל

## שלבים מפורטים

### שלב 1: הוספת המבנה HTML

פתח את הקובץ `webapp/templates/md_preview.html` והוסף את הקוד הזה מיד אחרי פתיחת תג `<div id="md-root">` (סביב שורה 216):

```html
<!-- תוכן עניינים צף -->
<div id="mdToc" class="md-toc" style="display:none;">
  <div class="md-toc-header">
    <h3 style="margin:0;font-size:1.1rem;display:flex;align-items:center;gap:0.5rem;">
      <i class="fas fa-list"></i>
      תוכן עניינים
    </h3>
    <button id="mdTocToggle" class="md-toc-toggle" title="כווץ/הרחב">
      <i class="fas fa-chevron-up"></i>
    </button>
  </div>
  <nav id="mdTocNav" class="md-toc-nav"></nav>
</div>
```

הוסף את הקוד הזה **לפני** השורה:
```html
<div class="file-header" style="display:flex;justify-content:space-between...">
```

### שלב 2: הוספת עיצוב CSS

הוסף את הסגנונות האלה בתוך תג `<style>` שבחלק `{% block extra_css %}` (אחרי השורה 212):

```css
/* === תוכן עניינים צף === */
.md-toc {
  position: fixed;
  top: 100px;
  left: 20px;
  max-width: 280px;
  min-width: 200px;
  max-height: calc(100vh - 140px);
  background: linear-gradient(135deg, rgba(255,255,255,0.95) 0%, rgba(250,250,252,0.95) 100%);
  backdrop-filter: blur(12px);
  border-radius: 12px;
  box-shadow: 0 8px 32px rgba(0,0,0,0.15);
  border: 1px solid rgba(255,255,255,0.3);
  z-index: 900;
  overflow: hidden;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}

.md-toc.collapsed .md-toc-nav {
  display: none;
}

.md-toc.collapsed {
  max-height: 60px;
}

.md-toc-header {
  padding: 1rem;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
  display: flex;
  justify-content: space-between;
  align-items: center;
  cursor: pointer;
  user-select: none;
}

.md-toc-toggle {
  background: rgba(255,255,255,0.2);
  border: 1px solid rgba(255,255,255,0.3);
  border-radius: 6px;
  padding: 0.4rem 0.6rem;
  cursor: pointer;
  color: white;
  transition: all 0.2s ease;
}

.md-toc-toggle:hover {
  background: rgba(255,255,255,0.3);
  transform: scale(1.05);
}

.md-toc-toggle i {
  transition: transform 0.3s ease;
}

.md-toc.collapsed .md-toc-toggle i {
  transform: rotate(180deg);
}

.md-toc-nav {
  padding: 0.75rem 0;
  overflow-y: auto;
  max-height: calc(100vh - 220px);
  scrollbar-width: thin;
  scrollbar-color: #667eea transparent;
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

.md-toc-item {
  padding: 0.5rem 1rem;
  cursor: pointer;
  color: #2d3748;
  transition: all 0.2s ease;
  border-right: 3px solid transparent;
  font-size: 0.9rem;
  display: block;
  text-decoration: none;
}

.md-toc-item:hover {
  background: rgba(102, 126, 234, 0.1);
  color: #667eea;
  border-right-color: #667eea;
  padding-right: 1.25rem;
}

.md-toc-item.active {
  background: rgba(102, 126, 234, 0.15);
  color: #667eea;
  border-right-color: #667eea;
  font-weight: 600;
}

/* הזחה לפי רמת כותרת */
.md-toc-item[data-level="2"] { padding-right: 1rem; }
.md-toc-item[data-level="3"] { padding-right: 1.75rem; font-size: 0.85rem; }
.md-toc-item[data-level="4"] { padding-right: 2.5rem; font-size: 0.8rem; }
.md-toc-item[data-level="5"] { padding-right: 3.25rem; font-size: 0.75rem; }
.md-toc-item[data-level="6"] { padding-right: 4rem; font-size: 0.75rem; }

/* התאמה למסכים קטנים */
@media (max-width: 1024px) {
  .md-toc {
    left: 10px;
    max-width: 240px;
    font-size: 0.85rem;
  }
}

@media (max-width: 768px) {
  .md-toc {
    display: none !important; /* מוסתר במובייל */
  }
}

/* במסך מלא - מסתיר את התוכן עניינים */
#mdCard:fullscreen ~ .md-toc,
#mdCard:-webkit-full-screen ~ .md-toc {
  display: none !important;
}
```

### שלב 3: הוספת לוגיקת JavaScript

הוסף את הקוד הזה בסוף תג ה-`<script>` הראשי (לפני הסגירה של `})();` בשורה 645):

```javascript
// === תוכן עניינים צף ===
(function initTableOfContents() {
  try {
    const container = document.getElementById('md-content');
    const tocElement = document.getElementById('mdToc');
    const tocNav = document.getElementById('mdTocNav');
    const tocToggle = document.getElementById('mdTocToggle');
    
    if (!container || !tocElement || !tocNav) return;

    // המתן שהתוכן ירונדר
    setTimeout(() => {
      // חילוץ כל הכותרות (h1-h6)
      const headings = Array.from(container.querySelectorAll('h1, h2, h3, h4, h5, h6'));
      
      // אם אין כותרות - לא מציגים את התוכן עניינים
      if (headings.length === 0) {
        tocElement.style.display = 'none';
        return;
      }

      // בניית רשימת תוכן העניינים
      tocNav.innerHTML = '';
      headings.forEach((heading, index) => {
        const level = parseInt(heading.tagName.substring(1)); // h2 -> 2
        const text = heading.textContent || '';
        
        // אם אין ID לכותרת, ניצור אחד
        if (!heading.id) {
          heading.id = `heading-${index}`;
        }

        // יצירת פריט בתוכן עניינים
        const item = document.createElement('a');
        item.className = 'md-toc-item';
        item.setAttribute('data-level', level);
        item.setAttribute('href', `#${heading.id}`);
        item.textContent = text.replace(/¶/g, '').trim(); // הסרת סמל ה-permalink
        
        // קליק -> גלילה חלקה לכותרת
        item.addEventListener('click', (e) => {
          e.preventDefault();
          heading.scrollIntoView({ 
            behavior: 'smooth', 
            block: 'start' 
          });
          
          // עדכון הפריט הפעיל
          tocNav.querySelectorAll('.md-toc-item').forEach(i => i.classList.remove('active'));
          item.classList.add('active');
        });

        tocNav.appendChild(item);
      });

      // הצגת תוכן העניינים
      tocElement.style.display = 'block';

      // כפתור כיווץ/הרחבה
      if (tocToggle) {
        tocToggle.addEventListener('click', (e) => {
          e.stopPropagation();
          tocElement.classList.toggle('collapsed');
        });
        
        // גם הכותרת עצמה תכווץ/תרחיב
        const tocHeader = document.querySelector('.md-toc-header');
        if (tocHeader) {
          tocHeader.addEventListener('click', () => {
            tocElement.classList.toggle('collapsed');
          });
        }
      }

      // הדגשה אוטומטית של הכותרת הנוכחית בעת גלילה
      let ticking = false;
      function updateActiveHeading() {
        if (ticking) return;
        ticking = true;
        
        requestAnimationFrame(() => {
          const scrollPos = window.scrollY + 120; // offset למעלה
          let activeHeading = null;

          // מציאת הכותרת הקרובה ביותר מלמעלה
          for (let i = headings.length - 1; i >= 0; i--) {
            const heading = headings[i];
            if (heading.offsetTop <= scrollPos) {
              activeHeading = heading;
              break;
            }
          }

          // עדכון הסימון הפעיל
          tocNav.querySelectorAll('.md-toc-item').forEach(item => {
            item.classList.remove('active');
            if (activeHeading && item.getAttribute('href') === `#${activeHeading.id}`) {
              item.classList.add('active');
            }
          });

          ticking = false;
        });
      }

      // האזנה לגלילה
      window.addEventListener('scroll', updateActiveHeading, { passive: true });
      
      // קריאה ראשונית
      updateActiveHeading();

    }, 500); // המתנה קצרה שהרינדור יסתיים

  } catch (e) {
    console.error('TOC init failed:', e);
  }
})();
```

### שלב 4: בדיקה

אחרי שתוסיף את כל הקוד:

1. **טען מחדש** את הדפדפן
2. **פתח קובץ markdown** עם כותרות (H1, H2, H3...)
3. **בדוק** שתוכן העניינים מופיע בצד שמאל
4. **נסה ללחוץ** על כותרת - הדף אמור לגלול אליה
5. **גלול במסמך** - הכותרת הנוכחית אמורה להיות מודגשת
6. **לחץ על כפתור הכיווץ** - התוכן עניינים אמור להתכווץ

## אפשרויות נוספות להתאמה אישית

### שינוי מיקום (ימין במקום שמאל)

אם אתה רוצה שתוכן העניינים יהיה בצד ימין במקום שמאל, שנה ב-CSS:

```css
.md-toc {
  left: auto;
  right: 20px;
}

/* וגם שנה את ההזחות: */
.md-toc-item {
  border-right: none;
  border-left: 3px solid transparent;
  padding-right: 1rem;
  padding-left: 1rem;
}

.md-toc-item:hover {
  border-left-color: #667eea;
  padding-left: 1.25rem;
}
```

### הוספת כפתור הצגה/הסתרה מלא

אם אתה רוצה אפשרות להסתיר לגמרי (לא רק לכווץ), הוסף כפתור נוסף:

```html
<button id="mdTocHide" class="btn btn-secondary btn-icon" 
        style="position:absolute;top:10px;left:300px;z-index:901;"
        title="הסתר תוכן עניינים">
  <i class="fas fa-times"></i>
</button>
```

והוסף ב-JS:

```javascript
const hideBtn = document.getElementById('mdTocHide');
if (hideBtn) {
  hideBtn.addEventListener('click', () => {
    tocElement.style.display = 'none';
  });
}
```

### סינון כותרות (רק H2 ו-H3)

אם אתה רוצה להציג רק כותרות ספציפיות, שנה את השורה:

```javascript
// במקום:
const headings = Array.from(container.querySelectorAll('h1, h2, h3, h4, h5, h6'));

// רשום:
const headings = Array.from(container.querySelectorAll('h2, h3'));
```

### שמירת מצב (פתוח/סגור) ב-localStorage

אם אתה רוצה לזכור את מצב הכיווץ בין טעינות:

```javascript
// טעינה
const isTocCollapsed = localStorage.getItem('mdTocCollapsed') === 'true';
if (isTocCollapsed) {
  tocElement.classList.add('collapsed');
}

// שמירה
tocToggle.addEventListener('click', (e) => {
  e.stopPropagation();
  tocElement.classList.toggle('collapsed');
  localStorage.setItem('mdTocCollapsed', tocElement.classList.contains('collapsed'));
});
```

## טיפים ושיקולים

### ביצועים
- הקוד משתמש ב-`requestAnimationFrame` לגלילה חלקה, זה חסכוני ויעיל
- האזנת הגלילה היא `passive` - לא חוסמת
- חילוץ הכותרות קורה פעם אחת, לא בכל גלילה

### נגישות (Accessibility)
- השתמש ב-`<nav>` סמנטי לתוכן עניינים
- הוסף `aria-label` לכפתורים
- וודא שהניגודיות טובה (WCAG 2.1)

### תאימות דפדפנים
- הקוד עובד על כל הדפדפנים המודרניים
- `scrollIntoView` נתמך בכל המקומות
- אם צריך תמיכה ב-IE11, תצטרך polyfill

### אינטגרציה עם חיפוש
תוכן העניינים לא יתנגש עם פיצ'ר החיפוש הקיים - הם עובדים יחד בהרמוניה!

## סיכום

עכשיו יש לך תוכן עניינים מקצועי וצף שמשתלב בצורה חלקה עם תצוגת המרקדאון הקיימת. המשתמשים שלך יוכלו לנווט במסמכים ארוכים בצורה נוחה ומהירה.

**זמן מימוש משוער**: 15-20 דקות  
**רמת קושי**: בינוני  
**תלות**: אין - כל הספריות כבר נטענות  

בהצלחה! 🚀
