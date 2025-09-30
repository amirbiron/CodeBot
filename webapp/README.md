# Code Keeper Bot - Web Application 🌐

אפליקציית ווב מלאה לניהול וצפייה בקטעי הקוד שנשמרו בבוט.

## תכונות 🚀

- **התחברות מאובטחת** - עם Telegram Login Widget
- **דשבורד מלא** - סטטיסטיקות וסקירה כללית
- **ניהול קבצים** - חיפוש, סינון ומיון מתקדם
- **צפייה בקוד** - עם הדגשת syntax ומספרי שורות
- **תצוגת Markdown מתקדמת (🌐)** לקבצי `.md`:
  - GFM: כותרות, הדגשות, רשימות, ציטוטים, קישורים/תמונות, קוד inline/בלוקים
  - Task Lists אינטראקטיביות (שמירה ב‑localStorage לכל קובץ)
  - טבלאות, strikethrough, autolinks, emoji
  - נוסחאות KaTeX (inline/block)
  - דיאגרמות Mermaid (fenced ```mermaid)
  - הדגשת קוד עם Highlight.js
  - Lazy‑loading לתמונות ו‑virtualization בסיסי למסמכים ארוכים
- **הורדת קבצים** - שמירה מקומית של הקוד
- **עיצוב מודרני** - Glass Morphism responsive

## התקנה מקומית 💻

### דרישות מקדימות
- Python 3.9+
- MongoDB (מקומי או Atlas)
- Telegram Bot Token

### שלבי התקנה

1. **התקן את החבילות:**
```bash
cd webapp
pip install -r requirements.txt
```

2. **צור קובץ .env:**
```bash
cp .env.example .env
# ערוך את .env והוסף את הפרטים שלך
```

3. **הפעל את האפליקציה:**
```bash
python app.py
# או עם gunicorn:
gunicorn app:app --bind 0.0.0.0:5000
```

4. **פתח בדפדפן:**
```
http://localhost:5000
```

## פריסה ב-Render 🚀

### אפשרות 1: פריסה אוטומטית עם render.yaml

1. העלה את הקוד ל-GitHub
2. התחבר ל-Render עם GitHub
3. צור Blueprint חדש מה-repo
4. Render יזהה את render.yaml ויצור את השירותים אוטומטית

### אפשרות 2: פריסה ידנית

1. **צור Web Service חדש ב-Render:**
   - Name: `code-keeper-webapp`
   - Environment: Python
   - Build Command: `cd webapp && pip install -r requirements.txt`
   - Start Command: `cd webapp && gunicorn app:app --bind 0.0.0.0:$PORT`

2. **הגדר משתני סביבה:**
   - `SECRET_KEY` - מפתח סודי ל-Flask sessions
   - `MONGODB_URL` - חיבור ל-MongoDB
   - `BOT_TOKEN` - טוקן של הבוט
   - `BOT_USERNAME` - שם המשתמש של הבוט
   - `WEBAPP_URL` - כתובת ה-Web App

3. **Deploy!**

## משתני סביבה 🔐

| משתנה | תיאור | חובה | ברירת מחדל |
|--------|--------|------|-------------|
| `SECRET_KEY` | מפתח הצפנה ל-Flask | ✅ | - |
| `MONGODB_URL` | חיבור ל-MongoDB | ✅ | - |
| `BOT_TOKEN` | טוקן הבוט מ-BotFather | ✅ | - |
| `BOT_USERNAME` | שם המשתמש של הבוט | ❌ | `my_code_keeper_bot` |
| `DATABASE_NAME` | שם מסד הנתונים | ❌ | `code_keeper_bot` |
| `WEBAPP_URL` | כתובת ה-Web App | ❌ | `https://code-keeper-webapp.onrender.com` |

## מבנה הפרויקט 📁

```
webapp/
├── app.py              # האפליקציה הראשית
├── requirements.txt    # חבילות Python
├── .env.example       # דוגמת משתני סביבה
├── README.md          # קובץ זה
└── templates/         # תבניות HTML
    ├── base.html      # תבנית בסיס
    ├── index.html     # דף בית
    ├── login.html     # התחברות
    ├── dashboard.html # דשבורד
    ├── files.html     # רשימת קבצים
    ├── view_file.html # צפייה בקובץ (כולל כפתור 🌐 ל‑HTML/Markdown)
    ├── html_preview.html # תצוגת HTML ב‑iframe בטוח
    └── md_preview.html   # תצוגת Markdown עשירה בצד לקוח
    ├── 404.html       # שגיאה 404
    └── 500.html       # שגיאה 500
```

## API Endpoints 🛣️

| Endpoint | Method | תיאור | דורש אימות |
|----------|--------|-------|-------------|
| `/` | GET | דף הבית | ❌ |
| `/login` | GET | דף התחברות | ❌ |
| `/auth/telegram` | POST | אימות Telegram | ❌ |
| `/logout` | GET | התנתקות | ✅ |
| `/dashboard` | GET | דשבורד | ✅ |
| `/files` | GET | רשימת קבצים | ✅ |
| `/file/<id>` | GET | צפייה בקובץ | ✅ |
| `/download/<id>` | GET | הורדת קובץ | ✅ |
| `/html/<id>` | GET | תצוגת HTML בטוחה | ✅ |
| `/md/<id>` | GET | תצוגת Markdown עשירה | ✅ |
| `/api/stats` | GET | סטטיסטיקות JSON | ✅ |

## בעיות נפוצות ופתרונות 🔧

### ModuleNotFoundError: No module named 'pygments'
**פתרון:** ודא שהתקנת את כל החבילות:
```bash
cd webapp
pip install -r requirements.txt
```

### שגיאת חיבור ל-MongoDB
**פתרון:** בדוק ש:
1. ה-`MONGODB_URL` נכון
2. ה-IP של Render מורשה ב-MongoDB Atlas
3. הסיסמה לא מכילה תווים מיוחדים בעייתיים

### Telegram Login לא עובד
**פתרון:** ודא ש:
1. ה-`BOT_TOKEN` נכון
2. ה-`BOT_USERNAME` תואם לשם הבוט
3. הדומיין מוגדר נכון ב-BotFather

## תמיכה 💬

לשאלות ובעיות:
1. בדוק את ה-[Documentation](https://amirbiron.github.io/CodeBot/)
2. פתח Issue ב-GitHub
3. צור קשר דרך הבוט בטלגרם

## רישיון 📄

MIT License - ראה קובץ LICENSE לפרטים נוספים.