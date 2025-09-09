.. orphan

דוגמאות שימוש
=============

דף זה מכיל דוגמאות קוד לשימוש ב-API של Code Keeper Bot.

שימוש בסיסי
-----------

יצירת אפליקציית בוט
~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   from main import CodeKeeperBot
   from config import config
   
   # יצירת מופע של הבוט
   bot = CodeKeeperBot()
   
   # הפעלת הבוט
   bot.run()

שמירת קוד חדש
~~~~~~~~~~~~~~

.. code-block:: python

   from database import db, CodeSnippet
   
   # יצירת snippet חדש
   snippet = CodeSnippet(
       user_id=123456789,
       file_name="example.py",
       code="print('Hello, World!')",
       programming_language="python",
       note="דוגמה ראשונה"
   )
   
   # שמירה במסד הנתונים
   result = await db.save_snippet(snippet)
   print(f"נשמר עם ID: {result.inserted_id}")

חיפוש קוד
~~~~~~~~~

.. code-block:: python

   from database import db
   
   # חיפוש לפי טקסט
   results = await db.search_snippets(
       user_id=123456789,
       search_term="Hello"
   )
   
   for snippet in results:
       print(f"נמצא: {snippet['file_name']}")

שימוש ב-Handlers
----------------

יצירת Command Handler
~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   from telegram.ext import CommandHandler
   
   async def my_command(update, context):
       """פקודה מותאמת אישית"""
       await update.message.reply_text(
           "שלום! זו פקודה מותאמת אישית"
       )
   
   # הוספת הפקודה לבוט
   handler = CommandHandler("mycommand", my_command)
   application.add_handler(handler)

יצירת Conversation Handler
~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   from telegram.ext import ConversationHandler, MessageHandler, filters
   
   # מצבי שיחה
   WAITING_FOR_CODE = 1
   WAITING_FOR_NAME = 2
   
   async def start_save(update, context):
       await update.message.reply_text("שלח לי את הקוד:")
       return WAITING_FOR_CODE
   
   async def receive_code(update, context):
       context.user_data['code'] = update.message.text
       await update.message.reply_text("מה שם הקובץ?")
       return WAITING_FOR_NAME
   
   async def receive_name(update, context):
       context.user_data['filename'] = update.message.text
       # שמור את הקוד...
       await update.message.reply_text("נשמר בהצלחה!")
       return ConversationHandler.END
   
   # יצירת ה-handler
   conv_handler = ConversationHandler(
       entry_points=[CommandHandler('save', start_save)],
       states={
           WAITING_FOR_CODE: [MessageHandler(filters.TEXT, receive_code)],
           WAITING_FOR_NAME: [MessageHandler(filters.TEXT, receive_name)],
       },
       fallbacks=[]
   )

שימוש ב-Services
-----------------

זיהוי שפת תכנות
~~~~~~~~~~~~~~~~

.. code-block:: python

   from services import code_service
   
   code = '''
   def hello():
       print("Hello, World!")
   '''
   
   language = code_service.detect_language(code, "test.py")
   print(f"השפה שזוהתה: {language}")  # python

ניתוח קוד
~~~~~~~~~

.. code-block:: python

   from services import code_service
   
   analysis = code_service.analyze_code(code, "python")
   print(f"מספר שורות: {analysis['lines']}")
   print(f"מורכבות: {analysis['complexity']}")

אינטגרציה עם GitHub
--------------------

העלאת קוד ל-Gist
~~~~~~~~~~~~~~~~~

.. code-block:: python

   from github_menu_handler import GitHubMenuHandler
   
   github = GitHubMenuHandler()
   
   # יצירת Gist
   gist_url = await github.create_gist(
       filename="example.py",
       content="print('Hello from Gist!')",
       description="דוגמה לקוד Python",
       public=True
   )
   
   print(f"Gist נוצר: {gist_url}")

שליפת Gists של משתמש
~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   gists = await github.get_user_gists(username="octocat")
   
   for gist in gists:
       print(f"- {gist['description']}: {gist['html_url']}")

עבודה עם מסד הנתונים
---------------------

ביצוע שאילתות מורכבות
~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   from database import db
   from datetime import datetime, timedelta
   
   # חיפוש קבצים מהשבוע האחרון
   week_ago = datetime.now() - timedelta(days=7)
   
   recent_files = db.db.code_snippets.find({
       "user_id": 123456789,
       "created_at": {"$gte": week_ago}
   }).sort("created_at", -1)
   
   async for file in recent_files:
       print(f"{file['file_name']} - {file['created_at']}")

עדכון קבצים
~~~~~~~~~~~~

.. code-block:: python

   # עדכון הערה לקובץ
   result = db.db.code_snippets.update_one(
       {"_id": file_id},
       {"$set": {"note": "הערה מעודכנת"}}
   )
   
   if result.modified_count > 0:
       print("עודכן בהצלחה")

סטטיסטיקות
~~~~~~~~~~~

.. code-block:: python

   from database import db
   
   # קבלת סטטיסטיקות משתמש
   stats = await db.get_user_statistics(user_id=123456789)
   
   print(f"סה״כ קבצים: {stats['total_files']}")
   print(f"שפה פופולרית: {stats['most_used_language']}")
   print(f"גודל כולל: {stats['total_size']} bytes")

טיפול בשגיאות
--------------

טיפול בשגיאות בסיסי
~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   from telegram.error import TelegramError
   import logging
   
   logger = logging.getLogger(__name__)
   
   async def safe_handler(update, context):
       try:
           # קוד שעלול להיכשל
           result = await risky_operation()
           await update.message.reply_text(f"הצלחה: {result}")
       
       except TelegramError as e:
           logger.error(f"Telegram error: {e}")
           await update.message.reply_text("אירעה שגיאה, נסה שוב")
       
       except Exception as e:
           logger.exception("Unexpected error")
           await update.message.reply_text("משהו השתבש 😕")

Retry Logic
~~~~~~~~~~~

.. code-block:: python

   import asyncio
   from typing import Optional
   
   async def with_retry(func, max_attempts=3, delay=1):
       """ביצוע פונקציה עם ניסיונות חוזרים"""
       
       for attempt in range(max_attempts):
           try:
               return await func()
           except Exception as e:
               if attempt == max_attempts - 1:
                   raise
               await asyncio.sleep(delay * (attempt + 1))
   
   # שימוש
   result = await with_retry(
       lambda: db.save_snippet(snippet),
       max_attempts=3
   )

בדיקות
-------

בדיקת יחידה
~~~~~~~~~~~~

.. code-block:: python

   import pytest
   from services import code_service
   
   def test_language_detection():
       """בדיקת זיהוי שפה"""
       
       test_cases = [
           ("print('hello')", "test.py", "python"),
           ("console.log('hi')", "test.js", "javascript"),
           ("SELECT * FROM users", "query.sql", "sql"),
       ]
       
       for code, filename, expected in test_cases:
           result = code_service.detect_language(code, filename)
           assert result == expected

בדיקת אינטגרציה
~~~~~~~~~~~~~~~~

.. code-block:: python

   import pytest
   from unittest.mock import AsyncMock
   
   @pytest.mark.asyncio
   async def test_save_command():
       """בדיקת פקודת השמירה"""
       
       # יצירת mock objects
       update = AsyncMock()
       context = AsyncMock()
       
       # הגדרת התנהגות
       update.message.text = "/save"
       update.effective_user.id = 123456789
       
       # הפעלת הפקודה
       from bot_handlers import save_command
       result = await save_command(update, context)
       
       # בדיקת תוצאה
       assert update.message.reply_text.called
       assert "שלח לי" in update.message.reply_text.call_args[0][0]

דוגמאות מתקדמות
----------------

עיבוד באצווה
~~~~~~~~~~~~

.. code-block:: python

   from batch_processor import BatchProcessor
   
   processor = BatchProcessor()
   
   # הוספת משימות
   files = ["file1.py", "file2.js", "file3.go"]
   
   for filename in files:
       processor.add_task(
           process_file,
           filename=filename
       )
   
   # ביצוע באצווה
   results = await processor.execute_all()
   
   for result in results:
       if result.success:
           print(f"✓ {result.filename}")
       else:
           print(f"✗ {result.filename}: {result.error}")

קאשינג
~~~~~~

.. code-block:: python

   from cache_manager import CacheManager
   
   cache = CacheManager()
   
   # שמירה בקאש
   await cache.set(
       key="user_stats_123",
       value={"files": 42, "size": 1024},
       ttl=3600  # שעה
   )
   
   # קריאה מקאש
   stats = await cache.get("user_stats_123")
   if stats:
       print(f"מהקאש: {stats}")
   else:
       # חשב מחדש
       stats = await calculate_stats()
       await cache.set("user_stats_123", stats)