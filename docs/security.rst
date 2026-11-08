:summary: ניקוי טוקנים וסודות מלוגים, מחריגות ומ-Sentry, הרצת קוד ב-Playground, הכותרת X-Content-Type-Options: nosniff בתשובות של הוובאפ, ודוגמאות להצפנת טוקנים, ל-CSRF ולמגבלת קצב.

Security Guide
==============

סודות ופרטיות
--------------

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

.. _security-nosniff:

סוג התוכן בלי ניחוש — ``X-Content-Type-Options: nosniff``
---------------------------------------------------------------

כל תשובה שהוובאפ מייצר דרך Flask נושאת את הכותרת ``X-Content-Type-Options: nosniff``: עמודים, ‏API, דפי שגיאה, קבצים סטטיים והורדות. היא נוספת במקום אחד, ``_add_nosniff`` ב-``webapp/app.py``, שרשום כ-``after_request``. ב-Flask 3.1.2 גם ``full_dispatch_request`` וגם ``handle_exception`` (ב-``flask/app.py``) מסיימים ב-``finalize_request``, שמריץ את פונקציות ה-``after_request`` — ולכן גם תשובה של מטפל שגיאות מקבלת את הכותרת.

**מה הכותרת עושה.** בלעדיה הדפדפן מנחש את סוג התוכן לפי התוכן עצמו. איתה הוא מאמין לסוג שהשרת הצהיר עליו: הוא מסרב להריץ סקריפט שהסוג שלו אינו JavaScript, ולהחיל גיליון סגנון שהסוג שלו אינו ``text/css`` (Fetch Standard, הסעיף "Should response to request be blocked due to nosniff?").

**למה זה נחוץ כאן.** ``/share/<id>/download`` מגיש כ-``text/plain`` את הטקסט שבעל השיתוף כתב. עמוד באתר שטוען את הכתובת הזו ב-``<script src>`` — למשל דרך HTML שהוזרק לעמוד — מריץ אותה, ו-``script-src 'self'`` לא עוצר את זה, כי הכתובת באמת מהאתר שלנו. ב-8.11.2026, ב-Chrome for Testing 153, הקוד רץ בלי הכותרת, ועם הכותרת הדפדפן סירב: ``Refused to execute script from '…' because its MIME type ('text/plain') is not executable, and strict MIME type checking is enabled.`` המדידה היא ``tests/test_nosniff_browser.py``, עם בקרה שמורידה את הכותרת מאותה תשובה בדיוק.

**נתיב שקבע את הכותרת בעצמו נשאר עם מה שקבע.** ``_add_nosniff`` משתמש ב-``setdefault``, ולכן ``raw_html`` ו-``raw_svg``, שקובעים אותה בעצמם, לא מקבלים עותק שני (``test_a_route_that_sets_the_header_itself_keeps_one_copy`` ב-``tests/test_nosniff.py``).

**מה שומר על הסקריפטים של האתר עצמו.** הסקריפטים וגיליונות הסגנון שהאתר מגיש בעצמו הם קבצים תחת ``webapp/static``, ו-Flask מגיש אותם בסוג שטבלת ``mimetypes`` נותנת לסיומת. ``/sw.js`` (``service_worker_js``) מצהיר על ``application/javascript`` בעצמו. ``test_every_static_script_and_stylesheet_is_served_with_a_type_the_browser_accepts_under_nosniff`` נכשל על קובץ סקריפט או ``.css`` שמוגש בסוג אחר, ו-``tests/test_nosniff_browser.py`` טוען את העורך הציבורי, עמוד שיתוף ועמוד קובץ ובודק שאף סקריפט או גיליון סגנון לא נחסם. **נתיב חדש שמגיש סקריפט או גיליון סגנון שנבנה בזמן ריצה חייב להצהיר על הסוג הנכון:** אחרת הדפדפן יחסום אותו בשקט — הודעה ב-console, ושום דבר בלוגים של השרת.

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
