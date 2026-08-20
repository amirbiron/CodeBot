Security Guide
==============
:summary: אל תרשום סודות/PII בלוגים, השתמש ב‑ENV בלבד.

סודות ופרטיות
--------------

אל תרשום סודות/PII בלוגים, השתמש ב‑ENV בלבד.

ניקוי טוקן הבוט מלוגים, חריגות ו‑Sentry
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

כתובות ה‑API של טלגרם נבנות כ‑``https://api.telegram.org/bot<TOKEN>/method`` —
כלומר **כל טקסט שנגזר מכתובת כזו נושא את הטוקן במלואו**: הודעת חריגה, שורת לוג,
traceback או אירוע Sentry. בעקבות אירוע אבטחה (אוגוסט 2026) קיימת נקודת ניקוי
מרכזית ב‑``telegram_api``:

- ``redact_bot_token(text)`` — מנקה טוקן ממחרוזת בודדת.
- ``redact_bot_token_deep(obj)`` — מנקה מבנה מקונן שלם (dict כולל מפתחות, list,
  tuple/namedtuple, set, bytes, ואובייקטים זרים שהייצוג שלהם נושא טוקן). עמיד
  למבנים מעגליים, וכשל ניקוי מחזיר placeholder — לעולם לא את הערך הגולמי.

השכבות שנשענות על הנקודה הזו:

- ``TelegramAPIError`` מנקה את ``url``/``description``/``payload`` **בהשמה**, כך
  שכל מקומות הקריאה מכוסים בלי לגעת בהם — כולל כאלה שיתווספו בעתיד.
- ``SensitiveDataFilter`` (ב‑``utils``) מנקה את ההודעה **ואת ה‑traceback** דרך
  רשימת דפוסים אחת (טלגרם, GitHub, Bearer). ``exc_info`` נשמר — ה‑Formatter
  משתמש בקאש ``exc_text`` המנוקה, ו‑Sentry מנקה את החריגה המובנית בעצמו.
- ``before_send`` בבוט (``observability``) ובוובאפ הוא **fail-closed**: אם
  הניקוי נכשל, האירוע נזרק ונרשמת אזהרת ``sentry_redaction_failed`` — עדיף
  לאבד אירוע מאשר להדליף טוקן.

כללים לקוד חדש:

- אין לשרשר URL של Bot API לתוך הודעת שגיאה או לוג כמות שהוא — להעביר דרך
  ``redact_bot_token`` קודם.
- סוג סוד חדש דורש עדכון בשתי נקודות: ``SensitiveDataFilter._PATTERNS`` (מכסה
  הודעות לוג ו‑traceback) **וגם** נקודת הניקוי ב‑``telegram_api`` (מכסה חריגות
  ו‑before_send של Sentry). עדכון של אחת בלבד משאיר את המסלול השני חשוף.
- הטסטים ב‑``tests/test_telegram_token_redaction.py`` נועלים את ההתנהגות; שינוי
  במנגנון חייב לעבור אותם.

הרצת קוד (Code Execution Playground)
------------------------------------
ה‑WebApp כולל Playground בכתובת ``/tools/code`` (פתוח לכל משתמש מחובר), כאשר **הרצת קוד בפועל** זמינה רק ל‑Premium/Admin.

הדגשים החשובים:
- בפרודקשן מומלץ להריץ **רק** בתוך Docker sandbox ולהשאיר ``CODE_EXEC_ALLOW_FALLBACK=false`` (Fail‑Closed).
- לא ללוגג קוד או פלט, רק מטא‑דאטה.

ראו עמוד ייעודי עם אבטחה/מגבלות/Troubleshooting:
- :doc:`/webapp/code-execution`

הצפנת טוקנים (דוגמה)
----------------------

.. code-block:: python

   from cryptography.fernet import Fernet

   def encrypt_token(token: str, key: bytes) -> str:
       return Fernet(key).encrypt(token.encode()).decode()

   def decrypt_token(encrypted_token: str, key: bytes) -> str:
       return Fernet(key).decrypt(encrypted_token.encode()).decode()

CSRF ב‑WebApp
-------------

.. code-block:: python

   from flask_wtf.csrf import CSRFProtect

   app = Flask(__name__)
   app.config['SECRET_KEY'] = os.getenv('SECRET_KEY')
   csrf = CSRFProtect(app)

Rate Limiting (דוגמה)
----------------------

.. code-block:: python

   from functools import wraps
   from time import time

   def rate_limit(max_calls=10, period=60):
       calls = {}
       def decorator(func):
           @wraps(func)
           async def wrapper(update, context):
               user_id = update.effective_user.id
               now = time()
               if user_id not in calls:
                   calls[user_id] = []
               calls[user_id] = [t for t in calls[user_id] if now - t < period]
               if len(calls[user_id]) >= max_calls:
                   await update.message.reply_text("Too many requests!")
                   return
               calls[user_id].append(now)
               return await func(update, context)
           return wrapper
       return decorator

קישורים
-------

- :doc:`environment-variables`
- :doc:`ci-cd`

אבטחת הודעות בטלגרם
---------------------

- HTML Escaping: יש לבצע `escape` לכל תוכן שמגיע מהמשתמש (כולל קוד ושמות קבצים) טרם שליחה כ-HTML.
- Callback Data: להגביל את אורך `callback_data` ל-64 בתים (כולל קידומת). במקרה חריגה:
  - העדיפו שימוש במזהה מסד (`_id`) אם אורך ההודעה מאפשר.
  - אחרת, צרו טוקן קצר (למשל `token_urlsafe(6)` חתוך ל~24 תווים), שמרו מיפוי בטוח ב-`user_data`, והשתמשו ב-`fav_toggle_tok:<token>`.
  - יש להימנע מתווים בעייתיים ולשמור על קידומות יציבות עבור ניתוב ה-handlers.
