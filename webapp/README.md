# Code Keeper Bot - Web Application 🌐

אפליקציית ווב מלאה לניהול וצפייה בקטעי הקוד שנשמרו בבוט.

## תכונות 🚀

### 🔐 אימות וניהול משתמשים
- **התחברות מאובטחת** - עם Telegram Login Widget או אסימון חד-פעמי מהבוט
- **כניסה מתמשכת** - זכור אותי (30 יום)
- **תפקידי משתמש** - Regular, Premium, Admin

### 📊 דשבורד וסטטיסטיקות
- **דשבורד מלא** - סטטיסטיקות וסקירה כללית
- **ספירת קבצים** - סה"כ קבצים פעילים
- **אחסון כולל** - גודל מצטבר
- **שפות מובילות** - 5 השפות הנפוצות ביותר
- **פעילות אחרונה** - 5 הקבצים האחרונים

### 📁 ניהול קבצים
- **חיפוש מתקדם** - Text, Regex, Fuzzy, Full-Text, Function Search
- **סינון ומיון** - לפי שפה, תגיות, תאריך, גודל
- **תצוגות קטגוריות** - כל הקבצים, נפתחו לאחרונה, לפי Repository, מועדפים, אוספים, קבצים גדולים
- **צפייה בקוד** - עם הדגשת syntax ומספרי שורות (100+ שפות)
- **עריכת קבצים** - עורך קוד בדפדפן
- **הורדת קבצים** - שמירה מקומית של הקוד
- **שיתוף קבצים** - יצירת קישורי שיתוף מאובטחים
- **פעולות Bulk** - הורדה, מחיקה, תגיות, מועדפים מרובים

### 📝 תצוגת Markdown מתקדמת
- **GFM מלא** - כותרות, הדגשות, רשימות, ציטוטים, קישורים/תמונות, קוד inline/בלוקים
- **Task Lists אינטראקטיביות** - שמירה ב‑localStorage לכל קובץ
- **טבלאות, strikethrough, autolinks, emoji**
- **נוסחאות KaTeX** - inline/block
- **דיאגרמות Mermaid** - fenced ```mermaid
- **הדגשת קוד** - עם Highlight.js
- **Lazy‑loading** - תמונות ו‑virtualization למסמכים ארוכים

### 🔖 סימניות (Bookmarks)
- **סימון שורות** - הוספה/הסרה של סימניות בשורות ספציפיות
- **צבעים מותאמים** - צהוב, אדום, ירוק, כחול, סגול
- **הערות אישיות** - הוספת הערות לכל סימניה
- **עיגון שורות** - סנכרון אוטומטי לשינויי קובץ
- **ניהול סימניות** - צפייה, עדכון, מחיקה

### 📌 פתקים דביקים (Sticky Notes)
- **הערות Markdown** - פתקים אינטראקטיביים על תצוגת Markdown
- **מיקום מותאם** - גרירה ושינוי גודל
- **עוגן שורה** - קישור לשורה ספציפית
- **צבעים מותאמים** - התאמת צבע לכל פתק
- **סנכרון** - תמיכה במכשירים מרובים

### 📚 אוספים (Collections)
- **יצירת אוספים** - ידני או חכם (מבוסס כללים)
- **ארגון קבצים** - קיבוץ בקבוצות מותאמות אישית
- **שיתוף אוספים** - יצירת קישורי שיתוף ציבוריים
- **ניהול פריטים** - הוספה, הסרה, סידור מחדש
- **Workspace** - אוסף ברירת מחדל אוטומטי

### 🔍 חיפוש מתקדם
- **סוגי חיפוש** - Content, Text, Regex, Fuzzy, Function
- **פילטרים** - שפה, תגיות, תאריכים, גודל, פונקציות/מחלקות
- **השלמה אוטומטית** - הצעות בזמן אמת
- **הדגשת תוצאות** - הדגשת התאמות בקוד
- **תצוגות מקדימות** - קטעים עם הקשר

### 🌐 ספריית קהילה וסניפטים
- **ספריית סניפטים** - עיון בקטעי קוד מאושרים
- **חיפוש סניפטים** - לפי כותרת/שפה
- **ספריית קהילה** - משאבים משותפים מהקהילה
- **הגשת סניפטים** - שיתוף קוד לשימוש חוזר

### ⚙️ הגדרות והעדפות
- **העדפות תצוגה** - גודל פונט, ערכת נושא (Classic, Ocean, Forest, High Contrast)
- **ניהול Session** - כניסה מתמשכת, יציאה מכל המכשירים
- **כלי מנהל** - ניהול ספריית סניפטים, סטטיסטיקות מערכת

### 🎨 עיצוב וחוויית משתמש
- **עיצוב מודרני** - Glass Morphism responsive
- **תמיכה RTL/LTR** - מותאם למובייל וטאבלט
- **אנימציות** - מעברי עמודים חלקים
- **PWA** - התקנה למסך הבית, מצב אפליקציה עצמאית

## התקנה מקומית 💻

### דרישות מקדימות
- Python 3.11+ (מומלץ 3.12)
- MongoDB (מקומי או Atlas)
- Redis (אופציונלי, מומלץ לביצועים)
- Telegram Bot Token

### שלבי התקנה

1. **התקן את החבילות:**
```bash
cd webapp
pip install -r ../requirements/production.txt
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
   - Build Command: `cd webapp && pip install -r ../requirements/production.txt`
   - Start Command: `cd webapp && gunicorn app:app --bind 0.0.0.0:$PORT`

2. **הגדר משתני סביבה:**
   - `SECRET_KEY` - מפתח סודי ל-Flask sessions
   - `MONGODB_URL` - חיבור ל-MongoDB
   - `BOT_TOKEN` - טוקן של הבוט
   - `BOT_USERNAME` - שם המשתמש של הבוט
   - `WEBAPP_URL` - כתובת ה-Web App
   - `UPTIME_PROVIDER` - ספק מעקב זמינות חיצוני (`betteruptime`/`uptimerobot`)
   - `UPTIME_API_KEY` - מפתח API לספק שבחרתם (אם נדרש)
   - `UPTIME_MONITOR_ID` - מזהה monitor בספק (אם נדרש)
   - `UPTIME_STATUS_URL` - קישור ציבורי לדף סטטוס (אופציונלי)
   - `UPTIME_WIDGET_ID` - מזהה widget להטמעה (Better Stack) (אופציונלי)
   - `UPTIME_WIDGET_SCRIPT_URL` - כתובת הסקריפט ל-widget (ברירת מחדל Better Stack)
   - `UPTIME_CACHE_TTL_SECONDS` - מטמון לתוצאות ה‑API בשניות (ברירת מחדל: 120)

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
| `UPTIME_PROVIDER` | ספק זמינות חיצוני (`betteruptime`/`uptimerobot`) | ❌ | - |
| `UPTIME_API_KEY` | מפתח API ל‑uptime | ❌ | - |
| `UPTIME_MONITOR_ID` | מזהה monitor | ❌ | - |
| `UPTIME_STATUS_URL` | קישור דף סטטוס ציבורי | ❌ | - |
| `UPTIME_WIDGET_ID` | מזהה widget (Better Stack) | ❌ | - |
| `UPTIME_WIDGET_SCRIPT_URL` | URL סקריפט widget | ❌ | `https://uptime.betterstack.com/widgets/announcement.js` |
| `UPTIME_CACHE_TTL_SECONDS` | TTL מטמון לתוצאות | ❌ | `120` |
| `ADMIN_USER_IDS` | מזהי משתמש (טלגרם) עם הרשאות אדמין (CSV) | ❌ | - |
| `PREMIUM_USER_IDS` | מזהי משתמש (טלגרם) לסטטוס פרימיום (CSV) | ❌ | - |

## מבנה הפרויקט 📁

```
webapp/
├── app.py                    # האפליקציה הראשית (Flask)
├── bookmarks_api.py          # API סימניות
├── collections_api.py        # API אוספים
├── sticky_notes_api.py       # API פתקים דביקים
├── requirements.txt          # חבילות Python
├── .env.example             # דוגמת משתני סביבה
├── README.md                # קובץ זה
├── static/                  # קבצים סטטיים
│   ├── css/                # עיצובים
│   ├── js/                 # JavaScript
│   ├── manifest.json       # PWA manifest
│   └── ...
└── templates/               # תבניות HTML
    ├── base.html           # תבנית בסיס
    ├── index.html          # דף בית
    ├── login.html          # התחברות
    ├── dashboard.html      # דשבורד
    ├── files.html          # רשימת קבצים
    ├── view_file.html      # צפייה בקובץ
    ├── html_preview.html   # תצוגת HTML ב‑iframe בטוח
    ├── md_preview.html     # תצוגת Markdown עשירה
    ├── collections.html    # ניהול אוספים
    ├── snippets.html       # ספריית סניפטים
    ├── settings.html       # הגדרות
    ├── 404.html            # שגיאה 404
    └── 500.html            # שגיאה 500
```

## API Endpoints 🛣️

### דפים ראשיים
| Endpoint | Method | תיאור | דורש אימות |
|----------|--------|-------|-------------|
| `/` | GET | דף הבית | ❌ |
| `/login` | GET | דף התחברות | ❌ |
| `/auth/telegram` | POST | אימות Telegram | ❌ |
| `/auth/token` | POST | אימות מבוסס אסימון | ❌ |
| `/logout` | GET | התנתקות | ✅ |
| `/dashboard` | GET | דשבורד | ✅ |
| `/files` | GET | רשימת קבצים | ✅ |
| `/file/<id>` | GET | צפייה בקובץ | ✅ |
| `/settings` | GET | הגדרות משתמש | ✅ |

### קבצים
| Endpoint | Method | תיאור | דורש אימות |
|----------|--------|-------|-------------|
| `/download/<id>` | GET | הורדת קובץ | ✅ |
| `/html/<id>` | GET | תצוגת HTML בטוחה | ✅ |
| `/md/<id>` | GET | תצוגת Markdown עשירה | ✅ |
| `/api/files/recent` | GET | קבצים אחרונים | ✅ |
| `/api/files/bulk-favorite` | POST | הוספת מועדפים מרובים | ✅ |
| `/api/files/bulk-delete` | POST | מחיקה מרובה | ✅ |
| `/api/files/create-zip` | POST | יצירת ZIP | ✅ |

### חיפוש
| Endpoint | Method | תיאור | דורש אימות |
|----------|--------|-------|-------------|
| `/api/search/global` | POST | חיפוש גלובלי | ✅ |
| `/api/search/suggestions` | GET | השלמה אוטומטית | ✅ |

### סימניות
| Endpoint | Method | תיאור | דורש אימות |
|----------|--------|-------|-------------|
| `/api/bookmarks/<file_id>/toggle` | POST | החלפת סימניה | ✅ |
| `/api/bookmarks/<file_id>` | GET | סימניות לקובץ | ✅ |
| `/api/bookmarks/all` | GET | כל הסימניות | ✅ |
| `/api/bookmarks/stats` | GET | סטטיסטיקות | ✅ |

### פתקים דביקים
| Endpoint | Method | תיאור | דורש אימות |
|----------|--------|-------|-------------|
| `/api/sticky-notes/<file_id>` | POST/GET | יצירה/צפייה | ✅ |
| `/api/sticky-notes/note/<note_id>` | PUT/DELETE | עדכון/מחיקה | ✅ |
| `/api/sticky-notes/batch` | POST | פעולות מרובות | ✅ |

### אוספים
| Endpoint | Method | תיאור | דורש אימות |
|----------|--------|-------|-------------|
| `/api/collections/` | GET/POST | רשימה/יצירה | ✅ |
| `/api/collections/<id>` | GET/PUT/DELETE | צפייה/עדכון/מחיקה | ✅ |
| `/api/collections/<id>/items` | GET/POST/DELETE | ניהול פריטים | ✅ |
| `/api/collections/<id>/share` | POST | שיתוף אוסף | ✅ |
| `/collections/shared/<token>` | GET | צפייה באוסף משותף | ❌ |

### ספריית סניפטים
| Endpoint | Method | תיאור | דורש אימות |
|----------|--------|-------|-------------|
| `/snippets` | GET | עיון בסניפטים | ❌ |
| `/api/snippets` | GET | API סניפטים | ❌ |
| `/api/snippets/submit` | POST | הגשת סניפט | ✅ |
| `/admin/snippets/pending` | GET | סניפטים ממתינים | ✅ (Admin) |

### סטטיסטיקות
| Endpoint | Method | תיאור | דורש אימות |
|----------|--------|-------|-------------|
| `/api/stats` | GET | סטטיסטיקות JSON | ✅ |
| `/api/me` | GET | מידע משתמש | ✅ |
| `/api/uptime` | GET | זמן פעילות מערכת | ❌ |

## בעיות נפוצות ופתרונות 🔧

### ModuleNotFoundError: No module named 'pygments'
**פתרון:** ודא שהתקנת את כל החבילות:
```bash
cd webapp
pip install -r ../requirements/production.txt
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