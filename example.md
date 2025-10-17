# דוגמה חיה: שימוש בקטעים מתקפלים וכרטיסיות הסבר

## פרויקט לדוגמה: מערכת ניהול ספרייה 📚

> [!NOTE]
> דף זה מדגים שימוש מעשי בקטעים מתקפלים וכרטיסיות הסבר.
> בדוק איך זה נראה בפלטפורמה שלך (GitHub, GitLab, וכו').

---

## 🎯 סקירת הפרויקט

מערכת ניהול ספרייה המאפשרת:
- ניהול מלאי ספרים
- מעקב אחר השאלות
- ניהול קוראים
- הפקת דוחות

> [!IMPORTANT]
> המערכת דורשת Node.js 16+ ו-MongoDB 5.0+

---

## 📦 התקנה והגדרה

<details open>
<summary>🚀 התחלה מהירה (3 דקות)</summary>

### שלב 1: שיבוט הפרויקט
```bash
git clone https://github.com/example/library-system.git
cd library-system
```

### שלב 2: התקנת תלויות
```bash
npm install
```

### שלב 3: הגדרת משתני סביבה
```bash
cp .env.example .env
# ערוך את הקובץ .env עם הנתונים שלך
```

### שלב 4: הפעלת המערכת
```bash
npm start
```

> [!TIP]
> השתמש ב-`npm run dev` למצב פיתוח עם רענון אוטומטי

</details>

<details>
<summary>⚙️ הגדרות מתקדמות</summary>

### הגדרת מסד נתונים

> [!WARNING]
> ודא שיש לך גיבוי לפני שינוי הגדרות מסד הנתונים!

```javascript
// config/database.js
module.exports = {
  mongodb: {
    uri: process.env.MONGODB_URI || 'mongodb://localhost:27017',
    database: 'library_system',
    options: {
      useNewUrlParser: true,
      useUnifiedTopology: true,
      maxPoolSize: 10
    }
  },
  redis: {
    host: process.env.REDIS_HOST || 'localhost',
    port: process.env.REDIS_PORT || 6379,
    ttl: 3600 // שניות
  }
};
```

### הגדרות אבטחה

```javascript
// config/security.js
module.exports = {
  jwt: {
    secret: process.env.JWT_SECRET,
    expiresIn: '24h'
  },
  bcrypt: {
    saltRounds: 10
  },
  rateLimit: {
    windowMs: 15 * 60 * 1000, // 15 דקות
    max: 100 // מקסימום בקשות
  }
};
```

</details>

<details>
<summary>🐳 הפעלה עם Docker</summary>

### בניית התמונה
```bash
docker build -t library-system .
```

### הפעלת המערכת
```bash
docker-compose up -d
```

### בדיקת לוגים
```bash
docker-compose logs -f app
```

> [!CAUTION]
> אל תשתמש בהגדרות ברירת המחדל בסביבת ייצור!

</details>

---

## 📖 תיעוד API

<details>
<summary>📚 ניהול ספרים</summary>

### רשימת כל הספרים
```http
GET /api/books
```

תגובה לדוגמה:
```json
{
  "success": true,
  "data": [
    {
      "id": "123",
      "title": "הנסיך הקטן",
      "author": "אנטואן דה סנט-אכזופרי",
      "isbn": "978-965-07-0000-0",
      "available": true
    }
  ],
  "pagination": {
    "page": 1,
    "limit": 10,
    "total": 150
  }
}
```

### הוספת ספר חדש
```http
POST /api/books
Content-Type: application/json

{
  "title": "שם הספר",
  "author": "שם המחבר",
  "isbn": "ISBN-13",
  "publishYear": 2024,
  "quantity": 5
}
```

> [!NOTE]
> נדרשת הרשאת מנהל להוספת ספרים

### עדכון פרטי ספר
```http
PUT /api/books/:id
```

### מחיקת ספר
```http
DELETE /api/books/:id
```

> [!WARNING]
> מחיקת ספר תמחק גם את היסטוריית ההשאלות שלו

</details>

<details>
<summary>👥 ניהול קוראים</summary>

### רישום קורא חדש
```http
POST /api/readers/register
Content-Type: application/json

{
  "firstName": "ישראל",
  "lastName": "ישראלי",
  "email": "israel@example.com",
  "phone": "050-1234567",
  "idNumber": "123456789"
}
```

### חיפוש קורא
```http
GET /api/readers/search?q=ישראל
```

### היסטוריית השאלות של קורא
```http
GET /api/readers/:id/loans
```

</details>

<details>
<summary>📋 השאלות והחזרות</summary>

### יצירת השאלה חדשה
```http
POST /api/loans
Content-Type: application/json

{
  "readerId": "reader123",
  "bookId": "book456",
  "dueDate": "2024-02-01"
}
```

### החזרת ספר
```http
PUT /api/loans/:id/return
```

### השאלות באיחור
```http
GET /api/loans/overdue
```

> [!IMPORTANT]
> המערכת שולחת תזכורות אוטומטיות 3 ימים לפני תאריך ההחזרה

</details>

---

## 🔍 פתרון בעיות נפוצות

<details>
<summary>❌ שגיאה: Cannot connect to MongoDB</summary>

### סיבות אפשריות:
1. **MongoDB לא פועל** - הפעל את השירות:
   ```bash
   # Linux/Mac
   sudo systemctl start mongod
   
   # Windows
   net start MongoDB
   ```

2. **כתובת שגויה** - בדוק את ה-URI ב-.env:
   ```
   MONGODB_URI=mongodb://localhost:27017/library
   ```

3. **חומת אש חוסמת** - ודא שפורט 27017 פתוח

> [!TIP]
> השתמש ב-`npm run test:db` לבדיקת החיבור

</details>

<details>
<summary>⚠️ אזהרה: JWT Secret not defined</summary>

### פתרון:
1. צור מפתח סודי חזק:
   ```bash
   node -e "console.log(require('crypto').randomBytes(32).toString('hex'))"
   ```

2. הוסף ל-.env:
   ```
   JWT_SECRET=המפתח_שיצרת
   ```

3. הפעל מחדש את השרת

> [!CAUTION]
> אל תשתף את המפתח הסודי או תעלה אותו ל-Git!

</details>

<details>
<summary>🐛 באג: ספרים לא מופיעים ברשימה</summary>

### צעדי איתור:
1. **בדוק את הלוגים**:
   ```bash
   tail -f logs/app.log
   ```

2. **בדוק אינדקסים ב-DB**:
   ```javascript
   // במונגו shell
   db.books.getIndexes()
   ```

3. **נקה את המטמון**:
   ```bash
   npm run cache:clear
   ```

4. **בדוק הרשאות**:
   ```bash
   GET /api/auth/me
   ```

</details>

---

## 🚦 בדיקות

<details>
<summary>🧪 הרצת בדיקות</summary>

### בדיקות יחידה
```bash
npm test
```

### בדיקות אינטגרציה
```bash
npm run test:integration
```

### בדיקות E2E
```bash
npm run test:e2e
```

### כיסוי קוד
```bash
npm run test:coverage
```

> [!NOTE]
> יעד כיסוי מינימלי: 80%

</details>

<details>
<summary>✅ בדיקות ידניות מומלצות</summary>

### רשימת בדיקות לפני העלאה לייצור:

- [ ] **אותנטיקציה**
  - [ ] רישום משתמש חדש
  - [ ] התחברות עם אימייל וסיסמה
  - [ ] שחזור סיסמה
  - [ ] יציאה מהמערכת

- [ ] **ניהול ספרים**
  - [ ] הוספת ספר חדש
  - [ ] עריכת פרטי ספר
  - [ ] חיפוש ספרים
  - [ ] מחיקת ספר

- [ ] **השאלות**
  - [ ] השאלת ספר
  - [ ] החזרת ספר
  - [ ] הארכת השאלה
  - [ ] חישוב קנסות

- [ ] **דוחות**
  - [ ] דוח השאלות חודשי
  - [ ] ספרים פופולריים
  - [ ] קוראים פעילים

</details>

---

## 📈 ביצועים ואופטימיזציה

<details>
<summary>⚡ טיפים לשיפור ביצועים</summary>

### 1. הפעל מטמון Redis
```javascript
// config/cache.js
const redis = require('redis');
const client = redis.createClient();

module.exports = {
  get: async (key) => {
    return await client.get(key);
  },
  set: async (key, value, ttl = 3600) => {
    await client.setex(key, ttl, JSON.stringify(value));
  }
};
```

### 2. אינדקס מסד נתונים
```javascript
// במונגו shell
db.books.createIndex({ title: "text", author: "text" });
db.loans.createIndex({ dueDate: 1, returned: 1 });
```

### 3. דחיסת תגובות
```javascript
// app.js
const compression = require('compression');
app.use(compression());
```

### 4. הגבלת קצב (Rate Limiting)
```javascript
const rateLimit = require("express-rate-limit");
const limiter = rateLimit({
  windowMs: 15 * 60 * 1000,
  max: 100
});
app.use('/api', limiter);
```

> [!TIP]
> השתמש ב-`npm run analyze` לניתוח ביצועים

</details>

---

## 🆘 תמיכה ועזרה

<details>
<summary>📞 דרכי יצירת קשר</summary>

### תמיכה טכנית
- 📧 **אימייל**: support@library-system.com
- 💬 **צ'אט חי**: [פתח צ'אט](https://chat.library-system.com)
- 📱 **טלפון**: 1-800-LIBRARY (08:00-17:00)

### קהילה
- 💻 [פורום משתמשים](https://forum.library-system.com)
- 🐛 [דיווח על באגים](https://github.com/example/library-system/issues)
- 💡 [הצעות לשיפור](https://feedback.library-system.com)

### משאבים נוספים
- 📖 [תיעוד מלא](https://docs.library-system.com)
- 🎥 [סרטוני הדרכה](https://youtube.com/@library-system)
- 📝 [בלוג טכני](https://blog.library-system.com)

</details>

---

## 📝 רישיון

<details>
<summary>📜 פרטי רישיון MIT</summary>

```
MIT License

Copyright (c) 2024 Library System

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

</details>

---

> [!SUCCESS]
> 🎉 **מזל טוב!** השלמת את קריאת התיעוד.
> 
> עכשיו אתה מוכן להתחיל לעבוד עם המערכת.
> 
> בהצלחה! 🚀