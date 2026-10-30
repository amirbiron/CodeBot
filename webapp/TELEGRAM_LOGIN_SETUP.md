# הגדרת Telegram Login Widget 🔐

## בעיות נפוצות ופתרונות

### 1. ה-Widget לא מופיע / לא עובד

#### בדיקות נדרשות:

1. **הגדר את הדומיין ב-BotFather:**
   ```
   /mybots
   בחר את הבוט שלך
   Bot Settings
   Domain
   הזן: codekeeper-webapp.onrender.com
   ```

2. **ודא שה-BOT_USERNAME נכון:**
   - בקובץ `.env` או במשתני הסביבה ב-Render
   - צריך להיות **בלי @** - לדוגמה: `my_code_keeper_bot`
   - לא: `@my_code_keeper_bot`

3. **בדוק את ה-BOT_TOKEN:**
   - חייב להיות אותו טוקן גם בבוט וגם ב-Web App
   - אחרת האימות ייכשל

### 2. שגיאת "Invalid authentication"

זה קורה כאשר:
- ה-BOT_TOKEN לא תואם
- החתימה לא עוברת אימות
- הזמן על השרת לא מסונכרן

**פתרון:**
```bash
# בדוק את הזמן בשרת
date

# אם לא מסונכרן:
sudo ntpdate -s time.nist.gov
```

### 3. התחברות דרך הבוט

כשלוחצים על "פתח את הבוט בטלגרם":
1. הבוט מקבל פקודה `/start webapp_login`
2. יוצר טוקן זמני (תקף ל-5 דקות)
3. שולח קישור התחברות אישי
4. המשתמש לוחץ ומתחבר

### הגדרות במשתני סביבה (Render)

```env
# בבוט הראשי
BOT_TOKEN=1234567890:ABCdefGHIjklMNOpqrsTUVwxyz
SECRET_KEY=your-secret-key-32-chars-minimum
WEBAPP_URL=https://codekeeper-webapp.onrender.com

# ב-Web App
BOT_TOKEN=1234567890:ABCdefGHIjklMNOpqrsTUVwxyz  # אותו טוקן!
BOT_USERNAME=my_code_keeper_bot  # בלי @
SECRET_KEY=your-secret-key-32-chars-minimum  # אותו מפתח!
MONGODB_URL=mongodb+srv://...
WEBAPP_URL=https://codekeeper-webapp.onrender.com
```

### בדיקת תקינות

1. **בדיקת Widget:**
   - פתח את: `https://codekeeper-webapp.onrender.com/login`
   - אמור להופיע כפתור "Log in with Telegram"
   - אם לא - בדוק את הדומיין ב-BotFather

2. **בדיקת התחברות דרך בוט:**
   - שלח לבוט: `/start webapp_login`
   - אמור לקבל קישור התחברות
   - לחץ ובדוק שמתחבר

3. **בדיקת לוגים:**
   ```bash
   # ב-Render Dashboard
   # בדוק את הלוגים של שני השירותים
   ```

### סקריפט בדיקה

```python
# test_auth.py
import os
import hashlib
import hmac

BOT_TOKEN = os.getenv('BOT_TOKEN')
test_data = {
    'id': '123456',
    'first_name': 'Test',
    'username': 'testuser',
    'auth_date': '1234567890'
}

# יצירת data-check-string
data_items = []
for key, value in sorted(test_data.items()):
    data_items.append(f"{key}={value}")
data_check_string = '\n'.join(data_items)

# חישוב hash
secret_key = hashlib.sha256(BOT_TOKEN.encode()).digest()
calculated_hash = hmac.new(
    secret_key,
    data_check_string.encode(),
    hashlib.sha256
).hexdigest()

print(f"Hash: {calculated_hash}")
print(f"Data: {data_check_string}")
```

## צעדים לתיקון מלא:

1. **עדכן את הקוד** - ✅ כבר עשינו
2. **Push ל-GitHub:**
   ```bash
   git add .
   git commit -m "fix: Add token authentication for webapp"
   git push
   ```

3. **הגדר ב-BotFather:**
   - Domain: `codekeeper-webapp.onrender.com`

4. **עדכן משתני סביבה ב-Render:**
   - וודא שכל המשתנים מוגדרים נכון
   - במיוחד `SECRET_KEY` - חייב להיות זהה בשני השירותים

5. **Deploy מחדש:**
   - Manual Deploy בשני השירותים

## תמיכה

אם עדיין יש בעיות:
1. בדוק את הלוגים ב-Render
2. ודא שה-MongoDB זמין ומחובר
3. בדוק שאין שגיאות JavaScript בקונסול של הדפדפן