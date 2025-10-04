# 🔐 ממצאי אבטחה דחופים

## ⚠️ חשיפת Credentials בקוד

### מיקומים שנמצאו:
1. `bot_handlers.py` - שורה 32
2. `conversation_handlers.py` - שורה 106

### הבעיה:
MongoDB connection string עם סיסמה בטקסט גלוי:
```
mongodb+srv://mumin:M43M2TFgLfGvhBwY@muminai.tm6x81b.mongodb.net/...
```

### השלכות:
- גישה בלתי מורשית למסד הנתונים
- חשיפת נתוני משתמשים
- הפרת תקנות GDPR/אבטחת מידע

---

## ✅ פתרון מומלץ

### שלב 1: החלף את הסיסמה מיד
1. היכנס ל-MongoDB Atlas
2. החלף את סיסמת המשתמש `mumin`
3. עדכן את משתנה הסביבה `REPORTER_MONGODB_URI`

### שלב 2: הסר מהקוד
החלף בשני הקבצים:
```python
# ❌ לא טוב
reporter = create_reporter(
    mongodb_uri="mongodb+srv://mumin:PASSWORD@...",
    ...
)

# ✅ טוב
reporter = create_reporter(
    mongodb_uri=os.getenv('REPORTER_MONGODB_URI') or config.MONGODB_URL,
    ...
)
```

### שלב 3: סרוק היסטוריית Git
```bash
# בדוק אם הסיסמה הייתה בהיסטוריה
git log -S "M43M2TFgLfGvhBwY" --all

# אם נמצאה, שקול:
# 1. BFG Repo-Cleaner להסרה מהיסטוריה
# 2. או לפחות החלף סיסמה והוסף warning ב-README
```

### שלב 4: הוסף pre-commit hook
```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/Yelp/detect-secrets
    rev: v1.4.0
    hooks:
      - id: detect-secrets
        args: ['--baseline', '.secrets.baseline']
```

---

## 📋 תוכנית פעולה מלאה

- [ ] **מיידי**: החלף סיסמת MongoDB
- [ ] **מיידי**: עדכן `bot_handlers.py` להשתמש ב-env var
- [ ] **מיידי**: עדכן `conversation_handlers.py` להשתמש ב-env var
- [ ] היום: סרוק git history
- [ ] השבוע: הוסף detect-secrets pre-commit hook
- [ ] השבוע: סקירת אבטחה מלאה של כל משתני הסביבה

---

## 🔒 שיטות עבודה מומלצות

1. **לעולם לא** לשים credentials בקוד
2. **תמיד** להשתמש במשתני סביבה
3. **להוסיף** `.env` ל-`.gitignore`
4. **להריץ** סריקות אבטחה אוטומטיות ב-CI
5. **לסובב** סודות לפחות פעם ברבעון
