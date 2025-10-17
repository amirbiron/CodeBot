# מדריך מימוש: קטעים מתקפלים וכרטיסיות הסבר עם markdown-it

## 📋 סקירה כללית

מדריך זה מסביר איך להוסיף תמיכה בקטעים מתקפלים (collapsible sections) וכרטיסיות הסבר (admonitions) במערכת המבוססת על markdown-it, **ללא צורך בהפעלת HTML גולמי**.

### יתרונות הגישה:
- ✅ בטוח - אין סיכוני XSS
- ✅ תחביר נקי ופשוט
- ✅ עקבי עם תוספי markdown-it אחרים
- ✅ קל לתחזוקה ושדרוג

## 🔧 שלב 1: התקנת התוספים

```bash
# התקנת התוספים הנדרשים
npm install markdown-it-container markdown-it-admonition

# אופציונלי - לעיצוב משופר
npm install markdown-it-attrs
```

## ⚙️ שלב 2: הגדרת markdown-it

### קובץ הקונפיגורציה הבסיסי:

```javascript
// webapp/config/markdown-config.js
const markdownIt = require('markdown-it');
const container = require('markdown-it-container');
const admonition = require('markdown-it-admonition');

// יצירת instance של markdown-it
const md = markdownIt({
  html: false,  // נשאר false לבטיחות!
  linkify: true,
  typographer: true,
  breaks: true
});

// תוספים קיימים (שכבר יש לכם)
md.use(require('markdown-it-emoji'))
  .use(require('markdown-it-task-lists'))
  .use(require('markdown-it-anchor'))
  .use(require('markdown-it-footnote'))
  .use(require('markdown-it-toc'));

// הוספת תמיכה ב-admonitions
md.use(admonition);

// הוספת קטעים מתקפלים
md.use(container, 'details', {
  validate: function(params) {
    return params.trim().match(/^details\s+(.*)$/);
  },
  render: function(tokens, idx) {
    const match = tokens[idx].info.trim().match(/^details\s+(.*)$/);
    if (tokens[idx].nesting === 1) {
      // פתיחת הקטע המתקפל
      const summary = match ? md.utils.escapeHtml(match[1]) : 'לחץ להצגה';
      return '<details><summary>' + summary + '</summary>\n';
    } else {
      // סגירת הקטע המתקפל
      return '</details>\n';
    }
  }
});

// הוספת container כללי לתיבות מידע מותאמות
const admonitionTypes = ['note', 'tip', 'warning', 'danger', 'info', 'success'];

admonitionTypes.forEach(type => {
  md.use(container, type, {
    render: function(tokens, idx) {
      if (tokens[idx].nesting === 1) {
        const title = tokens[idx].info.replace(type, '').trim() || getDefaultTitle(type);
        return `<div class="admonition admonition-${type}">
                  <div class="admonition-title">${md.utils.escapeHtml(title)}</div>
                  <div class="admonition-content">`;
      } else {
        return '</div></div>\n';
      }
    }
  });
});

// פונקציה לכותרות ברירת מחדל
function getDefaultTitle(type) {
  const titles = {
    note: 'הערה',
    tip: 'טיפ',
    warning: 'אזהרה',
    danger: 'סכנה',
    info: 'מידע',
    success: 'הצלחה'
  };
  return titles[type] || type;
}

module.exports = md;
```

## 🎨 שלב 3: עיצוב CSS

```css
/* webapp/static/css/markdown-enhanced.css */

/* ========== קטעים מתקפלים ========== */
details {
  margin: 1rem 0;
  padding: 0;
  border: 1px solid #e0e0e0;
  border-radius: 8px;
  background: #ffffff;
  overflow: hidden;
}

details[open] {
  box-shadow: 0 2px 8px rgba(0,0,0,0.1);
}

details summary {
  padding: 12px 16px;
  background: linear-gradient(to right, #f8f9fa, #ffffff);
  cursor: pointer;
  user-select: none;
  font-weight: 600;
  color: #1a1a1a;
  border-bottom: 1px solid #e0e0e0;
  outline: none;
  transition: all 0.3s ease;
}

details[open] summary {
  background: linear-gradient(to right, #e3f2fd, #ffffff);
  border-bottom: 2px solid #2196f3;
}

details summary:hover {
  background: linear-gradient(to right, #e8eaf6, #ffffff);
}

details summary::before {
  content: '▶';
  display: inline-block;
  margin-left: 8px;
  transition: transform 0.3s ease;
  color: #666;
}

details[open] summary::before {
  transform: rotate(90deg);
}

details summary::-webkit-details-marker {
  display: none;
}

details > *:not(summary) {
  padding: 16px;
  animation: fadeIn 0.3s ease;
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(-10px); }
  to { opacity: 1; transform: translateY(0); }
}

/* ========== כרטיסיות הסבר (Admonitions) ========== */
.admonition {
  margin: 1.5rem 0;
  padding: 0;
  border-radius: 8px;
  overflow: hidden;
  box-shadow: 0 2px 4px rgba(0,0,0,0.08);
}

.admonition-title {
  padding: 10px 16px;
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 8px;
}

.admonition-title::before {
  font-size: 1.2em;
}

.admonition-content {
  padding: 16px;
  background: white;
}

/* סוגי admonitions */
.admonition-note {
  border-right: 4px solid #2196f3;
  background: #e3f2fd;
}

.admonition-note .admonition-title {
  background: #bbdefb;
  color: #0d47a1;
}

.admonition-note .admonition-title::before {
  content: 'ℹ️';
}

.admonition-tip {
  border-right: 4px solid #4caf50;
  background: #e8f5e9;
}

.admonition-tip .admonition-title {
  background: #c8e6c9;
  color: #1b5e20;
}

.admonition-tip .admonition-title::before {
  content: '💡';
}

.admonition-warning {
  border-right: 4px solid #ff9800;
  background: #fff3e0;
}

.admonition-warning .admonition-title {
  background: #ffe0b2;
  color: #e65100;
}

.admonition-warning .admonition-title::before {
  content: '⚠️';
}

.admonition-danger {
  border-right: 4px solid #f44336;
  background: #ffebee;
}

.admonition-danger .admonition-title {
  background: #ffcdd2;
  color: #b71c1c;
}

.admonition-danger .admonition-title::before {
  content: '🚨';
}

.admonition-info {
  border-right: 4px solid #00bcd4;
  background: #e0f7fa;
}

.admonition-info .admonition-title {
  background: #b2ebf2;
  color: #006064;
}

.admonition-info .admonition-title::before {
  content: '📌';
}

.admonition-success {
  border-right: 4px solid #4caf50;
  background: #e8f5e9;
}

.admonition-success .admonition-title {
  background: #c8e6c9;
  color: #1b5e20;
}

.admonition-success .admonition-title::before {
  content: '✅';
}

/* RTL support עבור עברית */
[dir="rtl"] .admonition {
  border-right: none;
  border-left: 4px solid;
}

[dir="rtl"] details summary::before {
  margin-left: 0;
  margin-right: 8px;
}

/* Dark mode support (אופציונלי) */
@media (prefers-color-scheme: dark) {
  details {
    background: #1e1e1e;
    border-color: #333;
  }
  
  details summary {
    background: linear-gradient(to right, #2a2a2a, #1e1e1e);
    color: #e0e0e0;
  }
  
  .admonition-content {
    background: #2a2a2a;
    color: #e0e0e0;
  }
}
```

## 📝 שלב 4: תחביר השימוש

### קטעים מתקפלים:

```markdown
::: details כותרת הקטע המתקפל
תוכן שיוסתר עד ללחיצה.
אפשר להוסיף כאן:
- רשימות
- קוד
- תמונות
- כל אלמנט Markdown אחר
:::

::: details התקנה מפורטת
\`\`\`bash
npm install
npm run build
npm start
\`\`\`
:::
```

### כרטיסיות הסבר (Admonitions):

```markdown
!!! note "כותרת אופציונלית"
    תוכן ההערה כאן.
    שים לב לרווחים בתחילת השורה.

!!! warning
    אזהרה ללא כותרת מותאמת.

!!! tip "טיפ חשוב"
    תוכן הטיפ.

!!! danger "זהירות!"
    מידע קריטי.

!!! info
    מידע כללי.

!!! success "הצלחה"
    הפעולה הושלמה.
```

### או עם תחביר containers:

```markdown
::: note הערה חשובה
תוכן ההערה
:::

::: warning
תוכן האזהרה
:::

::: tip טיפ מועיל
תוכן הטיפ
:::
```

## 🚀 שלב 5: אינטגרציה במערכת

### עדכון קובץ השרת:

```javascript
// webapp/app.js (או הקובץ הראשי שלכם)
const express = require('express');
const md = require('./config/markdown-config');

const app = express();

// פונקציה לעיבוד Markdown
function renderMarkdown(content) {
  return md.render(content);
}

// דוגמה לשימוש ב-route
app.get('/render', (req, res) => {
  const markdownContent = req.body.content;
  const html = renderMarkdown(markdownContent);
  res.json({ html });
});

// הוספת ה-CSS לעמוד
app.get('/markdown-styles', (req, res) => {
  res.sendFile(__dirname + '/static/css/markdown-enhanced.css');
});
```

### עדכון ה-HTML template:

```html
<!-- webapp/templates/base.html -->
<!DOCTYPE html>
<html dir="rtl" lang="he">
<head>
  <!-- ... -->
  <link rel="stylesheet" href="/static/css/markdown-enhanced.css">
</head>
<body>
  <!-- תוכן המסמך -->
</body>
</html>
```

## 🧪 שלב 6: בדיקה

### קובץ בדיקה:

```javascript
// webapp/test-markdown.js
const md = require('./config/markdown-config');

const testContent = `
# בדיקת תכונות חדשות

::: details ראה דוגמה
זה תוכן מוסתר שיופיע בלחיצה
:::

!!! note "הערה חשובה"
    זו הערה עם כותרת מותאמת

!!! warning
    זו אזהרה עם כותרת ברירת מחדל

::: tip טיפ מועיל
זה טיפ עם תחביר container
:::
`;

console.log(md.render(testContent));
```

הרצה:
```bash
node webapp/test-markdown.js
```

## 📊 שלב 7: דוגמאות שימוש מתקדמות

### קינון קטעים מתקפלים:

```markdown
::: details תיעוד API
## נקודות קצה

::: details GET /api/users
\`\`\`json
{
  "users": [...]
}
\`\`\`
:::

::: details POST /api/users
\`\`\`json
{
  "name": "string",
  "email": "string"
}
\`\`\`
:::
:::
```

### שילוב admonitions בקטעים מתקפלים:

```markdown
::: details הוראות בטיחות
!!! danger "אזהרה חמורה"
    אל תפעיל את המערכת ללא הכשרה!

!!! warning "זהירות"
    בדוק את כל החיבורים לפני הפעלה

!!! tip "טיפ"
    קרא את המדריך המלא לפני התחלה
:::
```

## ✅ שלב 8: רשימת בדיקה לפני העלאה

- [ ] התוספים הותקנו בהצלחה (`npm list | grep markdown-it`)
- [ ] הקונפיג מעודכן ועובד
- [ ] ה-CSS נטען בעמודים הרלוונטיים
- [ ] התחביר עובד בעורך שלכם
- [ ] הבדיקות עוברות בהצלחה
- [ ] העיצוב נראה טוב (כולל mobile)
- [ ] תמיכה ב-RTL לעברית
- [ ] אין שגיאות בקונסול

## 🎯 סיכום

עם הגדרות אלו תקבלו:
1. **קטעים מתקפלים** עם תחביר `::: details`
2. **כרטיסיות הסבר** עם תחביר `!!!` או `:::`
3. **בטיחות מלאה** - ללא HTML גולמי
4. **עיצוב יפה** ומותאם לעברית
5. **קל לתחזוקה** ולהרחבה

### יתרונות על פני HTML:
- ✅ אין סיכוני XSS
- ✅ תחביר נקי יותר
- ✅ עקביות עם שאר המערכת
- ✅ קל יותר לכתיבה ועריכה

## 📚 משאבים נוספים

- [markdown-it-container Documentation](https://github.com/markdown-it/markdown-it-container)
- [markdown-it-admonition Documentation](https://github.com/commenthol/markdown-it-admonition)
- [markdown-it Plugin Guide](https://github.com/markdown-it/markdown-it/tree/master/docs)

## 🆘 פתרון בעיות

### התוסף לא נטען:
```javascript
// בדיקה
console.log(md.renderer.rules);
// אם אין container - בדוק את ה-require
```

### העיצוב לא מופיע:
- ודא שה-CSS נטען (בדוק ב-DevTools)
- בדוק specificity של ה-selectors

### תחביר לא מזוהה:
- ודא רווחים נכונים (4 רווחים או טאב ל-admonitions)
- בדוק שה-container נסגר עם `:::`