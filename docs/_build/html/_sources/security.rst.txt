Security Guide
==============

סודות ופרטיות
--------------

אל תרשום סודות/PII בלוגים, השתמש ב‑ENV בלבד.

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
