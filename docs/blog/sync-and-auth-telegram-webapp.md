# סנכרון בזמן אמת בין Telegram Bot ל-Web App — ואיך מאמתים משתמשים בצורה מאובטחת

> איך דואגים שמה שמשתמש עושה ב-Web App יופיע מיד בבוט, ולהיפך?
> ואיך מוודאים שרק מי שמחובר בטלגרם יוכל להיכנס ל-Web App?

---

## חלק 1: סנכרון — "מקור אמת אחד"

### הבעיה

נניח שיש לכם בוט טלגרם שמאפשר למשתמשים לשמור קבצים, ולצדו Web App שנותן ממשק גרפי לאותם קבצים בדיוק. המשתמש עורך קובץ ב-Web App — ורוצה לראות את השינוי מיד כשהוא חוזר לבוט. והפוך: שמר משהו דרך הבוט? צריך שזה יופיע מיד ב-Web App.

הפתרון הנאיבי — לסנכרן בין שני מסדי נתונים נפרדים — הוא מתכון לצרות: race conditions, קונפליקטים, ונתונים שלא מסתנכרנים.

### הפתרון: Single Source of Truth

הרעיון פשוט: **שני הצדדים (בוט ו-Web App) קוראים וכותבים לאותו מסד נתונים בדיוק**.

```
┌──────────────┐       ┌──────────────┐
│  Telegram    │       │   Web App    │
│    Bot       │       │   (Flask)    │
└──────┬───────┘       └──────┬───────┘
       │                      │
       │    ┌────────────┐    │
       └───►│  MongoDB   │◄───┘
            │ (Shared DB)│
            └─────┬──────┘
                  │
          ┌───────┴────────┐
          │  Repository    │
          │  Layer         │
          └────────────────┘
```

אין שום "סנכרון" — כי אין מה לסנכרן. יש מסד נתונים אחד, ושכבת Repository אחת שמבצעת את כל הפעולות.

### איך זה נראה בפועל

שכבת ה-Repository חושפת פונקציה אחת לשמירה — `save_code_snippet`. גם הבוט וגם ה-Web App משתמשים בה:

```python
def save_code_snippet(self, snippet: CodeSnippet) -> bool:
    # בדיקה אם יש גרסה קודמת
    existing = self.get_latest_version(snippet.user_id, snippet.file_name)
    if existing:
        snippet.version = existing['version'] + 1

    # חישוב מטא-דאטה
    doc = asdict(snippet)
    doc["file_size"] = len(snippet.code.encode("utf-8"))
    doc["lines_count"] = len(snippet.code.split('\n'))

    # שמירה ל-DB
    result = self.collection.insert_one(doc)

    # ניקוי cache
    if result.inserted_id:
        cache.invalidate_user_cache(snippet.user_id)

    return bool(result.inserted_id)
```

שימו לב למספר דברים חשובים:

1. **Versioning אוטומטי** — כל שמירה בודקת את הגרסה הקודמת ומעלה מונה. לא משנה מאיפה הגיעה הפעולה.
2. **מטא-דאטה מחושבת בזמן שמירה** — `file_size` ו-`lines_count` מחושבים פעם אחת ב-write, במקום בכל read. זה חוסך עבודה כשמציגים רשימות.
3. **Cache invalidation** — אחרי כל שמירה, ה-cache של המשתמש מתנקה. זה מבטיח שקריאה הבאה (מהבוט או מה-Web App) תביא את הנתון העדכני.

### למה זה עובד טוב

- **אפס שכפול** — אין שני עותקים של אותו נתון שצריכים להישאר מסונכרנים.
- **עקביות מובנית** — שני הצדדים עוברים דרך אותה שכבת לוגיקה, אז כללים כמו versioning ומועדפים תמיד חלים.
- **פשטות** — אין צורך ב-message queue, webhooks פנימיים, או כל מנגנון סנכרון. פחות קוד = פחות באגים.

### ומה עם Cache?

כשעובדים עם cache (וצריך, בשביל ביצועים), הכלל הוא:

> **כל פעולת כתיבה מנקה את ה-cache הרלוונטי.**

```python
# אחרי שמירה
cache.invalidate_user_cache(snippet.user_id)

# אחרי מחיקה
cache.invalidate_user_cache(user_id)
cache.invalidate_file_related(file_id=str(file_name), user_id=user_id)
```

ככה, גם אם הבוט שמר קובץ חדש ו-Web App שולף רשימת קבצים שנייה אחר כך — הרשימה תהיה עדכנית, כי ה-cache כבר התנקה.

---

## חלק 2: אימות — "בוא נוודא שזה באמת אתה"

### האתגר

ל-Web App אין מערכת משתמשים משלו — אין רישום, אין סיסמאות. כל ה-identity של המשתמש נמצא בטלגרם. אז איך מאמתים?

טלגרם מציע שתי דרכים, ואפשר (וכדאי) לתמוך בשתיהן.

### דרך 1: Telegram Login Widget

זה ה-widget הרשמי של טלגרם — כפתור שמופיע ב-Web App ומאפשר למשתמש להתחבר עם חשבון הטלגרם שלו.

```html
<script async src="https://telegram.org/js/telegram-widget.js?22"
        data-telegram-login="your_bot_username"
        data-size="large"
        data-auth-url="/auth/telegram"
        data-request-access="write">
</script>
```

כשהמשתמש לוחץ, טלגרם שולח לשרת שלכם פרטים חתומים: `id`, `first_name`, `username`, `hash` ועוד.

#### אימות ה-hash בצד השרת

זה החלק הקריטי — לוודא שהנתונים באמת הגיעו מטלגרם ולא זויפו:

```python
import hashlib
import hmac

def verify_telegram_auth(auth_data: dict) -> bool:
    check_hash = auth_data.get("hash")
    if not check_hash:
        return False

    # בניית מחרוזת בדיקה — כל השדות (חוץ מ-hash) ממוינים
    data_check_string = "\n".join(
        f"{key}={value}"
        for key, value in sorted(auth_data.items())
        if key != "hash"
    )

    # המפתח הסודי = SHA256 של ה-bot token
    bot_token = os.getenv("BOT_TOKEN")
    secret_key = hashlib.sha256(bot_token.encode()).digest()

    # HMAC-SHA256
    calculated_hash = hmac.new(
        secret_key,
        data_check_string.encode(),
        hashlib.sha256
    ).hexdigest()

    # השוואה + בדיקת תוקף זמן (עד שעה)
    if calculated_hash != check_hash:
        return False

    auth_date = int(auth_data.get("auth_date", 0))
    if (time.time() - auth_date) > 3600:
        return False

    return True
```

**איך זה עובד:**
1. טלגרם חותם את הנתונים עם HMAC-SHA256, כשה-secret key הוא SHA256 של ה-bot token שלכם.
2. בצד השרת, אתם מחשבים את אותו hash ומשווים.
3. בנוסף, בודקים שה-`auth_date` לא ישן מדי (עד שעה) — כדי למנוע replay attacks.

**למה SHA256 של ה-token ולא ה-token עצמו?** כי טלגרם רוצים שה-secret יהיה באורך קבוע (32 bytes) ולא תלוי באורך ה-token.

### דרך 2: Token חד-פעמי מהבוט

לפעמים ה-Login Widget לא מתאים — למשל, כשהמשתמש כבר נמצא בשיחה עם הבוט ורוצה לעבור ל-Web App בלחיצה. בשביל זה יש מסלול שני:

```
משתמש → בוט: "אני רוצה להיכנס ל-Web App"
בוט → DB: שומר token חד-פעמי (תקף 5 דקות)
בוט → משתמש: קישור אישי עם ה-token
משתמש → Web App: לוחץ על הקישור
Web App → DB: מוצא את ה-token, מוודא תוקף
Web App → DB: מוחק את ה-token (חד-פעמי!)
Web App: יוצר session למשתמש
```

קוד יצירת ה-token בבוט:

```python
import hashlib
import time

def build_login_payload(user_id: int, username: str) -> dict:
    # יצירת token מ-hash של user_id + timestamp + secret
    secret = os.getenv("WEBAPP_LOGIN_SECRET")
    token_data = f"{user_id}:{int(time.time())}:{secret}"
    auth_token = hashlib.sha256(token_data.encode()).hexdigest()[:32]

    # שמירה ב-DB עם תאריך תפוגה
    token_doc = {
        "token": auth_token,
        "user_id": user_id,
        "username": username,
        "created_at": datetime.now(timezone.utc),
        "expires_at": datetime.now(timezone.utc) + timedelta(minutes=5),
    }
    db.webapp_tokens.insert_one(token_doc)

    login_url = f"https://your-app.com/auth/token?token={auth_token}&user_id={user_id}"
    return {"login_url": login_url}
```

ובצד ה-Web App, כשהמשתמש לוחץ על הקישור:

```python
@app.route("/auth/token")
def token_auth():
    token = request.args.get("token")
    user_id = request.args.get("user_id")

    # חיפוש ה-token ב-DB
    token_doc = db.webapp_tokens.find_one({
        "token": token,
        "user_id": int(user_id)
    })

    if not token_doc:
        return "קישור לא תקף", 401

    # בדיקת תוקף
    if token_doc["expires_at"] < datetime.now(timezone.utc):
        db.webapp_tokens.delete_one({"_id": token_doc["_id"]})
        return "קישור פג תוקף", 401

    # מחיקה אחרי שימוש — חד פעמי!
    db.webapp_tokens.delete_one({"_id": token_doc["_id"]})

    # יצירת session
    session["user_id"] = int(user_id)
    session.permanent = True  # 30 יום

    return redirect("/dashboard")
```

**עקרונות אבטחה:**
- **חד-פעמי** — ה-token נמחק מיד אחרי שימוש. אם מישהו יתפוס את הקישור, הוא כבר לא יעבוד.
- **תוקף קצר** — 5 דקות. אפילו אם ה-token דלף, יש חלון קטן מאוד לניצול.
- **Hash ולא random** — ה-token נגזר מ-`user_id + timestamp + secret`, מה שמקשה על ניחוש.

---

## שילוב של הכל ביחד

הנה תמונת המצב המלאה:

```
                        ┌─────────────────────────┐
                        │      Telegram Login      │
                        │    Widget (HMAC auth)     │
                        └───────────┬─────────────┘
                                    │
┌──────────┐   token    ┌───────────▼─────────────┐
│ Telegram │──────────► │       Web App           │
│   Bot    │            │    (Flask + Session)     │
└────┬─────┘            └───────────┬─────────────┘
     │                              │
     │   ┌──────────────────────┐   │
     └──►│    MongoDB           │◄──┘
         │  ┌────────────────┐  │
         │  │  code_snippets │  │  ◄── שני הצדדים קוראים/כותבים
         │  │  users         │  │
         │  │  webapp_tokens │  │  ◄── טוקנים חד-פעמיים
         │  └────────────────┘  │
         └──────────────────────┘
```

1. **אימות** — המשתמש מזדהה דרך טלגרם (widget או token מהבוט).
2. **Session** — ה-Web App שומר session ל-30 יום, אז לא צריך להתחבר כל פעם.
3. **סנכרון** — אין. שני הצדדים עובדים על אותו DB, דרך אותה שכבת Repository, עם cache invalidation אחרי כל כתיבה.

---

## טיפים למימוש

1. **השתמשו בשכבת Repository משותפת** — אל תכתבו שאילתות DB ישירות בבוט או ב-Web App. שכבת ביניים אחת = לוגיקה אחידה.

2. **Cache invalidation חייב להיות אטומי עם הכתיבה** — אם שכחתם לנקות cache במסלול אחד, תקבלו נתונים ישנים במסלול אחר.

3. **אל תשמרו את ה-bot token בקוד** — הוא משמש כמפתח קריפטוגרפי לאימות. שמרו אותו רק ב-environment variables.

4. **וודאו שאותו token בדיוק** משמש את הבוט ואת ה-Web App — אחרת אימות ה-HMAC ייכשל.

5. **בדקו סנכרון שעונים** — אם השרת של ה-Web App והשרת של טלגרם לא מסונכרנים, `auth_date` ייראה ישן מדי והאימות ייכשל.

---

## סיכום

| נושא | הפתרון | למה |
|-------|---------|-----|
| סנכרון בוט ↔ Web App | DB משותף + Repository אחיד | פשוט, אמין, אפס קונפליקטים |
| אימות Web App | Telegram Login Widget + Token חד-פעמי | שתי דרכי כניסה, אבטחה מובנית |
| Cache | Invalidation אחרי כל כתיבה | עדכניות מובטחת |
| Session | Flask session, 30 יום | חוויית משתמש חלקה |

הגישה הזאת עובדת מצוין כשיש לכם שירות אחד (בוט) ו-Web App שעובדים על אותם נתונים. זה יותר פשוט ממה שנדמה — ובדיוק בגלל הפשטות, זה עובד אמין.
