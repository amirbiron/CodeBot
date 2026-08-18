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
- טשטוש בלוגים (Redaction): `utils.py`
  - `SensitiveDataFilter` – מסנן שמחליף בלוגים ובחריגות (tracebacks):
    - `ghp_********` → `ghp_***REDACTED***`
    - `github_pat_********` → `github_pat_***REDACTED***`
    - `Bearer <token>` → `Bearer ***REDACTED***`
    - **טוקני בוט טלגרם** (`\d{5,16}:[A-Za-z0-9_-]{30,}`) → `<REDACTED>`
  - המסנן מותקן בתחילת הריצה ב-`main.py`.

המערכת מטפלת בניקוי טוקנים משלוש זוויות:
1. **הודעות לוג ו-tracebacks** – `SensitiveDataFilter` מנקה את שני המסלולים דרך רשימת דפוסים אחת (`_PATTERNS`), כולל טוקני טלגרם שמופיעים בכתובות API מהצורה `https://api.telegram.org/bot<TOKEN>/method`.
2. **אירועי Sentry** – הן הבוט (`observability.py`) והן הוובאפ (`webapp/app.py`) משתמשים ב-`before_send` ו-`before_send_transaction` שמנקים באמצעות `redact_bot_token_deep` מ-`telegram_api`. התהליך הוא fail-closed: כשל ניקוי זורק את האירוע במקום לשלוח אותו גולמי.
3. **חריגות בקוד** – `TelegramAPIError` מנקה את כל השדות שלה בהשמה, כך שכל מקומות הקריאה מקבלים נתונים מנוקים.

למידע מלא על מנגנון הניקוי ועל כללי הוספת סוגי סודות חדשים, ראו `docs/security.rst`.

## איך מפעילים הצפנה
- הגדירו משתנה סביבה `TOKEN_ENC_KEY` עם מפתח Fernet תקין (Base64).
- ללא מפתח: הטוקנים יישמרו כטקסט רגיל, אך תמיד יטושטשו בלוגים.

## הערות
- ההצפנה נעשית מקומית בלבד; הטוקן נשלח רק ל-GitHub API לפי פעולה שבחרת.
- ניתן למחוק את הטוקן בכל רגע מתפריט GitHub.