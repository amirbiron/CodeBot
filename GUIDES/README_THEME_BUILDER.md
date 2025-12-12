# 🎨 מדריכי Theme Builder

ברוכים הבאים למדריכי מימוש ה-Theme Builder עבור CodeBot!

---

## 📚 רשימת המדריכים

### 1. [מדריך מימוש מלא](./THEME_BUILDER_IMPLEMENTATION_GUIDE.md)
**לקריאה ראשונה - חובה! 📖**

מדריך מקיף ומפורט שמכסה:
- סקירה כללית ואדריכלות
- כל שלבי המימוש (Backend, Frontend, Integration)
- קוד מלא לכל קובץ
- בדיקות ונגישות
- FAQ ופתרון בעיות

**מומלץ למי?**
- מפתחים שרוצים הבנה עמוקה
- צוות QA שצריך לבדוק
- מי שמבצע code review

**זמן קריאה:** 20-30 דקות

---

### 2. [מדריך התחלה מהירה](./THEME_BUILDER_QUICK_START.md)
**למימוש מהיר! ⚡**

מדריך תמציתי שמראה:
- מה כבר קיים בפרויקט
- מה צריך להוסיף (רשימת משימות)
- קטעי קוד מוכנים להעתקה
- זרימת עבודה ודיאגרמות
- בדיקות חובה

**מומלץ למי?**
- מפתחים מנוסים שרוצים להתחיל מהר
- מי שכבר קרא את המדריך המלא
- צוות שצריך לעקוב אחרי התקדמות

**זמן קריאה:** 10-15 דקות

---

## 🗺️ מפת דרכים מומלצת

### אם זו הפעם הראשונה שלך:

```
1. קרא את המדריך המלא (THEME_BUILDER_IMPLEMENTATION_GUIDE.md)
   ↓
2. הבן את הארכיטקטורה הקיימת (חלק 2)
   ↓
3. עבור לפי השלבים (חלקים 3-6)
   ↓
4. השתמש במדריך המהיר כ-Checklist
   ↓
5. בצע בדיקות (חלק 7)
```

### אם אתה מפתח מנוסה:

```
1. סריקה מהירה של המדריך המלא (5 דקות)
   ↓
2. קפוץ למדריך ההתחלה המהירה
   ↓
3. העתק והדבק קוד לפי הצורך
   ↓
4. השתמש במדריך המלא כ-Reference
```

---

## 📋 תלויות נדרשות

### Backend
- Python 3.11+
- Flask
- MongoDB (PyMongo)

### Frontend
- Pickr.js ([GitHub](https://github.com/Simonwep/pickr))
- Font Awesome (כבר קיים בפרויקט)

### אופציונלי
- ספריית בדיקת ניגודיות (למשל `colour`)

---

## 🛠️ סדר המימוש המומלץ

### יום 1: Backend (3-4 שעות)
1. הוסף נתיב `/settings/theme-builder`
2. צור API `/api/themes/save`
3. צור API `/api/themes/custom` (DELETE)
4. הוסף "custom" ל-`ALLOWED_UI_THEMES`
5. צור context processor `inject_db()`
6. בדיקות עם curl/Postman

### יום 2: Frontend (4-5 שעות)
1. צור `theme_builder.html`
2. אתחל Pickr לכל השדות
3. בנה את ה-Live Preview
4. חבר את הכפתורים (שמור, איפוס, מחק)
5. בדיקות בדפדפן

### יום 3: Integration + Testing (2-3 שעות)
1. הזרק `<style id="user-custom-theme">` ב-`base.html`
2. הוסף לינק ב-`settings.html`
3. בדיקות פונקציונליות
4. בדיקות נגישות
5. בדיקות דפדפנים שונים

**סה"כ:** 9-12 שעות (כולל בדיקות)

---

## 🧪 בדיקות מהירות

### בדיקה 1: Backend עובד?

```bash
# שמירת Theme
curl -X POST http://localhost:5000/api/themes/save \
  -H "Content-Type: application/json" \
  -H "Cookie: session=YOUR_SESSION" \
  -d '{
    "name": "Test Theme",
    "colors": {"background": "#1a1a2e", "primary": "#667eea", ...},
    "glass": {"rgba": "rgba(255,255,255,0.1)", ...},
    "markdown": {"surface": "#1b1e24", "text": "#f0f0f0"}
  }'

# מחיקת Theme
curl -X DELETE http://localhost:5000/api/themes/custom \
  -H "Cookie: session=YOUR_SESSION"
```

### בדיקה 2: Frontend עובד?

1. פתח `/settings/theme-builder`
2. פתח DevTools → Console
3. הקלד: `pickers.primary.getColor().toRGBA().toString()`
4. אמור להחזיר צבע תקין

### בדיקה 3: Integration עובד?

1. שמור Theme חדש ב-Builder
2. סמן "הפעל כתמה ברירת מחדל"
3. רענן את הדף
4. בדוק ב-Elements שיש `<style id="user-custom-theme">`
5. בדוק ש-`<html data-theme="custom">`

---

## 🐛 פתרון בעיות מהיר

| תסמין | גורם אפשרי | פתרון |
|-------|-----------|--------|
| דף Builder לא נטען | נתיב לא הוגדר | בדוק ש-`@app.route('/settings/theme-builder')` קיים |
| Pickr לא נפתח | CDN לא נטען | בדוק ב-Network שה-CDN זמין |
| Preview לא מתעדכן | טעות ב-JS | בדוק Console לשגיאות |
| Theme לא נשמר | ולידציה נכשלה | בדוק שכל הצבעים תקינים |
| Theme לא מופיע אחרי רענון | `inject_db()` לא פועל | בדוק שה-context processor הוגדר |
| Toast לא מופיע | CSS חסר | בדוק ש-`.toast` כולל את כל הסגנונות |

---

## 📚 משאבים נוספים

### מסמכים פנימיים
- `docs/webapp/theming_and_css.rst` – תיעוד מערכת הטוקנים
- `FEATURE_SUGGESTIONS/css_refactor_plan.md` – תוכנית רפקטור CSS
- `FEATURE_SUGGESTIONS/webapp_theme_palettes.md` – פלטות צבעים

### ספריות חיצוניות
- [Pickr Documentation](https://github.com/Simonwep/pickr)
- [CSS Variables (MDN)](https://developer.mozilla.org/en-US/docs/Web/CSS/Using_CSS_custom_properties)
- [WCAG 2.1 Guidelines](https://www.w3.org/WAI/WCAG21/quickref/)

### כלים מועילים
- [Contrast Checker](https://webaim.org/resources/contrastchecker/)
- [Color Picker (Chrome DevTools)](https://developer.chrome.com/docs/devtools/css/color/)

---

## 💬 שאלות ותמיכה

- **שאלות טכניות:** פתח Issue ב-GitHub
- **באגים:** דווח עם קוד לשחזור
- **הצעות שיפור:** פנה לצוות הפיתוח

---

## 📝 רשיון ותרומה

הקוד הוא חלק מפרויקט CodeBot.  
תרומות מתקבלות בברכה! עקוב אחרי ההנחיות ב-`.cursorrules`.

---

**בהצלחה עם המימוש! 🚀**

נ.ב. אם מצאת טעות במדריכים או יש לך הצעה לשיפור, אל תהסס לעדכן את הקבצים.
