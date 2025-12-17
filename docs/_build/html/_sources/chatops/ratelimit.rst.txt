הגבלת קצב לפקודות רגישות
=========================

``chatops.ratelimit`` מרכז את שכבת ההגנה הקלה נגד ספאם לפקודות רגישות
במערכת ה-ChatOps (למשל `/deploy`, `/restart`, `/secrets`). במקום
ליישם Redis/DB עבור כל פקודה, אנחנו שומרים חותמת זמן אחרונה בזיכרון
ה-process ומוודאים שהמשתמש מחכה כמה שניות בין הרצות.

עקרונות מרכזיים
----------------

- **Cooldown דינמי** – ברירת מחדל 5 שניות, ניתנת לשינוי בעזרת
  ``SENSITIVE_COMMAND_COOLDOWN_SEC``.
- **Lock אסינכרוני** – נעילת ``asyncio.Lock`` מקיפה את המילון
  ``_last_call_ts`` כדי למנוע מרוצי קריאה.
- **תגובה ידידותית** – כאשר המשתמש חורג נקבל הודעת
  ``⏳ אנא נסה שוב בעוד X שניות`` שמדעכנת כמה להמתין.
- **Fail-open** – אם קרתה חריגה ברמת הלימיטר, הפקודה תרוץ (עדיף על
  חסימה שגויה).

שימוש בדקורטור
---------------

הדרך הפשוטה להוסיף Rate Limit היא לעטוף את הפקודה ב-``@limit_sensitive``:

.. code-block:: python

   from chatops.ratelimit import limit_sensitive

   @limit_sensitive("deploy-release")
   async def handle_deploy(update, context):
       await context.bot.send_message(
           chat_id=update.effective_chat.id,
           text="🚀 נשלח טריגר דיפלוי"
       )

השם (`deploy-release` בדוגמה) משמש כטאג פנימי, כך שניתן להגדיר מגבלות
נפרדות לכל פקודה גם אם הן חולקות את אותה פונקציה.

קונפיגורציה
-----------

.. list-table::
   :header-rows: 1
   :widths: 40 60

   * - משתנה
     - תיאור
   * - ``SENSITIVE_COMMAND_COOLDOWN_SEC``
     - זמן מינימלי בין שתי קריאות של אותו משתמש לאותה פקודה (ברירת
       מחדל 5). ערכים קטנים מ-1 מעוגלים ל-1.

ניתן גם לשנות את ה-cooldown בזמן ריצה:

.. code-block:: python

   from chatops.ratelimit import sensitive_limiter

   sensitive_limiter.cooldown_sec = 10  # העלאה זמנית בעת אירועי עומס

שילוב בבוט
----------

1. עטפו רק פקודות שמשנות מצב (Deploy, Cleanup, Rotate). פקודות קריאה
   בלבד יכולות לרוץ ללא דקורטור.
2. הפעלת הלימיטר אינה מחליפה Rate Limit ברמת Telegram/Redis – היא
   שכבה משלימה שמונעת לחיצות כפולות.
3. כשחוסמים משתמש, ההודעה נשלחת דרך ``update.message.reply_text``;
   ודאו שהפקודה נרשמת כ-handler של הודעות ולא Inline Query.

Autodoc
-------

.. automodule:: chatops.ratelimit
   :members:
   :undoc-members:
   :show-inheritance:
   :noindex:
