# 🔒 אבטחת טוקנים – תקציר קצר

הבוט תומך בהצפנת טוקני GitHub ושמירתם בצורה בטוחה, ובנוסף מטשטש טוקנים בלוגים.

## מה מוצפן
- טוקני GitHub של המשתמשים נשמרים מוצפנים במסד הנתונים אם מוגדר משתנה סביבה `TOKEN_ENC_KEY`.
- כאשר ההצפנה פעילה, הערך הנשמר מתחיל במחרוזת `enc:` ומפוענח בזמן שימוש בלבד.

## היכן בקוד
- הצפנה/פענוח: `secret_manager.py`
  - `encrypt_secret(plaintext)` – מצפין מחרוזת ומחזיר `enc:<טוקן מוצפן>`.
  - `decrypt_secret(stored)` – מפענח ערך שמתחיל ב-`enc:`. אם אין מפתח, מחזיר `None`.
- שימוש בשמירה/שליפה:
  - `database.py`:
    - `save_github_token(user_id, token)` – קורא ל-`encrypt_secret(...)` לפני השמירה.
    - `get_github_token(user_id)` – קורא ל-`decrypt_secret(...)` בעת שליפה.
- טשטוש בלוגים (Redaction): `utils.py` ו-`telegram_api.py`
  - `SensitiveDataFilter` – מסנן שמחליף בלוגים:
    - `ghp_********` → `ghp_***REDACTED***`
    - `github_pat_********` → `github_pat_***REDACTED***`
    - `Bearer <token>` → `Bearer ***REDACTED***`
    - טוקני בוט טלגרם (`\d{5,}:[A-Za-z0-9_-]{20,}`) → `<REDACTED>` (קורא ל-`redact_bot_token` מ-`telegram_api.py`)
  - המסנן מותקן בתחילת הריצה ב-`main.py`.
  - פונקציות ניקוי טוקני טלגרם: `telegram_api.py`
    - `redact_bot_token(value)` – מחליף טוקן בוט בטקסט עם `<REDACTED>`. מקבל מחרוזת ומחזיר `None` כפי שהוא.
    - `redact_bot_token_deep(obj, _depth=0)` – ניקוי עומק על מבנים מקוננים (dict/list/tuple), נועד למסנני Sentry. עומק מוגבל ל-12 רמות כדי למנוע מעגליות.
    - תבנית הטוקן: `\d{5,}:[A-Za-z0-9_-]{20,}` (מבנה טוקן טלגרם).
  - נקודות שימוש בניקוי:
    - `TelegramAPIError` ב-`telegram_api.py` – מנקה את `url`, `description` ו-`payload` בזמן אתחול החריגה.
    - `SensitiveDataFilter` ב-`utils.py` – קורא ל-`redact_bot_token` על הודעות לוג.
    - `_before_send` ב-`observability.py` – קורא ל-`redact_bot_token_deep` על כל אירוע Sentry לפני שליחה.
    - `_sentry_before_send` ב-`webapp/app.py` – קורא ל-`redact_bot_token_deep` על אירועי Sentry מהאפליקציה.
  - זה מונע דליפת טוקנים דרך:
    - הודעות שגיאה (כתובות API מכילות את הטוקן: `https://api.telegram.org/bot<TOKEN>/method`)
    - לוגים של האפליקציה
    - דיווחי Sentry (exception messages, breadcrumbs, extra fields)

## איך מפעילים הצפנה
- הגדירו משתנה סביבה `TOKEN_ENC_KEY` עם מפתח Fernet תקין (Base64).
- ללא מפתח: הטוקנים יישמרו כטקסט רגיל, אך תמיד יטושטשו בלוגים.

## הערות
- ההצפנה נעשית מקומית בלבד; הטוקן נשלח רק ל-GitHub API לפי פעולה שבחרת.
- ניתן למחוק את הטוקן בכל רגע מתפריט GitHub.
