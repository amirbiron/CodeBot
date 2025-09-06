# Code Keeper Web App 🌐

ממשק ווב מודרני ויפה לבוט Code Keeper שמאפשר למשתמשים לגשת לקבצי הקוד שלהם דרך הדפדפן.

## תכונות עיקריות ✨

- **התחברות מאובטחת** - התחברות באמצעות חשבון הטלגרם
- **לוח בקרה אישי** - סטטיסטיקות וסקירה כללית
- **ניהול קבצים** - צפייה, חיפוש והורדת קבצים
- **תצוגת קוד** - הדגשת תחביר ותמיכה במגוון שפות
- **ממשק מודרני** - עיצוב Glass Morphism עם אנימציות חלקות
- **תמיכה בעברית** - ממשק מלא בעברית עם RTL

## טכנולוגיות 🛠️

- **Backend**: Flask (Python)
- **Frontend**: HTML5, Tailwind CSS, JavaScript
- **Database**: MongoDB (משותף עם הבוט)
- **Authentication**: Telegram Login Widget + JWT
- **Syntax Highlighting**: Prism.js
- **Icons**: Font Awesome

## התקנה והרצה 🚀

### דרישות מקדימות
- Python 3.9+
- MongoDB
- חשבון בוט בטלגרם

### התקנה מקומית

1. **התקן תלויות:**
```bash
pip install flask flask-cors flask-session pyjwt werkzeug pymongo
```

2. **הגדר משתני סביבה:**
```bash
export MONGODB_URL="mongodb://localhost:27017/codekeeper"
export BOT_TOKEN="your_telegram_bot_token"
export BOT_USERNAME="YourBotUsername"
export WEBAPP_SECRET_KEY=$(python -c "import secrets; print(secrets.token_hex(32))")
export JWT_SECRET=$(python -c "import secrets; print(secrets.token_hex(32))")
```

3. **הרץ את האפליקציה:**
```bash
python webapp/app.py
```

4. **גש לאפליקציה:**
```
http://localhost:5000
```

## פריסה ב-Render 🌍

### הגדרת Web Service חדש

1. **צור Web Service חדש ב-Render**
2. **חבר את ה-GitHub repository**
3. **הגדר את המשתנים הבאים:**

```
WEBAPP_SECRET_KEY = [generate with: python -c "import secrets; print(secrets.token_hex(32))"]
JWT_SECRET = [generate with: python -c "import secrets; print(secrets.token_hex(32))"]
BOT_TOKEN = [your telegram bot token]
BOT_USERNAME = [your bot username without @]
MONGODB_URL = [your mongodb connection string]
FLASK_ENV = production
```

4. **הגדר Build Command:**
```bash
pip install --upgrade pip && pip install -r requirements.txt
```

5. **הגדר Start Command:**
```bash
gunicorn webapp.app:app --bind 0.0.0.0:$PORT --workers 2 --threads 4 --timeout 120
```

## מבנה הפרויקט 📁

```
webapp/
├── app.py              # Flask application
├── templates/          # HTML templates
│   ├── base.html      # Base template
│   ├── index.html     # Homepage
│   ├── login.html     # Login page
│   ├── dashboard.html # User dashboard
│   ├── files.html     # Files listing
│   ├── file_view.html # Single file view
│   ├── 404.html       # 404 error page
│   └── 500.html       # 500 error page
├── static/            # Static files (if needed)
└── README.md          # This file
```

## API Endpoints 🔌

### Public Endpoints
- `GET /` - Homepage
- `GET /login` - Login page
- `POST /auth/telegram` - Telegram authentication
- `GET /health` - Health check

### Protected Endpoints (require authentication)
- `GET /dashboard` - User dashboard
- `GET /files` - List user files
- `GET /file/<id>` - View specific file
- `GET /file/<id>/download` - Download file
- `GET /api/stats` - Get user statistics (JSON)
- `GET /api/files` - Get files list (JSON)
- `GET /api/file/<id>` - Get file details (JSON)
- `GET /api/search` - Search files (JSON)

## אבטחה 🔐

- **Telegram Authentication** - אימות מאובטח דרך טלגרם
- **JWT Tokens** - טוקנים מוצפנים לאימות API
- **Session Management** - ניהול סשנים מאובטח
- **HTTPS Only** - תקשורת מוצפנת (ב-production)
- **Input Validation** - בדיקת קלט בכל הנקודות
- **Rate Limiting** - הגבלת קצב בקשות (מומלץ להוסיף)

## תרומה 🤝

מוזמנים לתרום לפרויקט! 
1. Fork את הפרויקט
2. צור branch חדש
3. בצע את השינויים
4. שלח Pull Request

## רישיון 📄

MIT License - ראה קובץ LICENSE לפרטים נוספים

## תמיכה 💬

לשאלות ותמיכה:
- Telegram: @moominAmir
- Bot: @CodeKeeperBot

---

נוצר עם ❤️ על ידי הקהילה