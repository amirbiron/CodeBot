Edge Cases וטיפול בשגיאות
===========================
:summary: מסמך זה מתאר Edge Cases נפוצים במערכת וכיצד לטפל בהם.

קבצים גדולים
-------------

**מגבלות:**
- קבצים רגילים: עד 20MB
- מצב LONG_COLLECT: עד 300KB להודעה, ללא מגבלה כוללת

**טיפול:**

.. code-block:: python

   MAX_FILE_SIZE = 20 * 1024 * 1024  # 20MB
   
   if file_size > MAX_FILE_SIZE:
       await update.message.reply_text(
           "❌ הקובץ גדול מדי (מעל 20MB).\n"
           "💡 נסה:\n"
           "• להעלות ל-GitHub\n"
           "• להשתמש ב-Google Drive\n"
           "• לפצל את הקובץ"
       )
       return

**קבצים גדולים מאוד (>100MB):**
- מוצע להשתמש ב-GitHub או Google Drive
- לא נשמרים במסד הנתונים

קידודים לא סטנדרטיים
----------------------

**קידודים נתמכים:**
- UTF-8 (ברירת מחדל)
- Windows-1255 (עברית)
- ISO-8859-8 (עברית)

**טיפול:**

.. code-block:: python

   ENCODINGS_TO_TRY = ['utf-8', 'windows-1255', 'iso-8859-8', 'latin-1']
   
   def detect_encoding(file_bytes: bytes) -> Tuple[str, str]:
       for encoding in ENCODINGS_TO_TRY:
           try:
               decoded = file_bytes.decode(encoding)
               return encoding, decoded
           except (UnicodeDecodeError, LookupError):
               continue
       
       # נפילה ל-UTF-8 עם errors='replace'
       return 'utf-8', file_bytes.decode('utf-8', errors='replace')

**Edge Case - קידוד לא מזוהה:**
- ניסיון עם כל הקידודים הנתמכים
- אם כולם נכשלים, שימוש ב-UTF-8 עם ``errors='replace'``
- המשתמש מקבל אזהרה

GitHub Rate Limits
------------------

**מגבלות:**
- Authenticated: 5,000 requests/hour
- Unauthenticated: 60 requests/hour
- Secondary rate limit: 1 request/second

**טיפול:**

.. code-block:: python

   from tenacity import retry, stop_after_attempt, wait_exponential
   
   @retry(
       stop=stop_after_attempt(3),
       wait=wait_exponential(multiplier=1, min=4, max=10)
   )
   async def github_api_call(func, *args, **kwargs):
       try:
           return await func(*args, **kwargs)
       except GithubException as e:
           if e.status == 403 and 'rate limit' in str(e).lower():
               # בדיקת rate limit
               rate_limit = github.get_rate_limit()
               reset_time = rate_limit.core.reset
               
               # הפעלת backoff
               await enable_github_backoff(user_id)
               
               # התראת מנהלים
               await notify_admins(
                   f"GitHub rate limit exceeded for user {user_id}. "
                   f"Reset at {reset_time}"
               )
               
               raise RateLimitError(f"Rate limit. Reset at {reset_time}")
           raise

**Backoff Strategy:**

.. code-block:: python

   async def enable_github_backoff(user_id: int):
       """הפעלת backoff למשתמש"""
       await db.set_user_setting(
           user_id,
           'github_backoff_enabled',
           True
       )
       await db.set_user_setting(
           user_id,
           'github_backoff_until',
           datetime.now() + timedelta(hours=1)
       )

MongoDB Connection Errors
-------------------------

**טיפול:**

.. code-block:: python

   from motor.motor_asyncio import AsyncIOMotorClient
   from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError
   
   async def safe_db_operation(operation, *args, **kwargs):
       max_retries = 3
       for attempt in range(max_retries):
           try:
               return await operation(*args, **kwargs)
           except (ConnectionFailure, ServerSelectionTimeoutError) as e:
               if attempt == max_retries - 1:
                   # התראת מנהלים
                   await notify_admins(
                       f"MongoDB connection failed after {max_retries} attempts: {e}"
                   )
                   emit_event(
                       "db_connection_failed",
                       severity="error",
                       error=str(e)
                   )
                   raise
               
               # המתנה לפני ניסיון חוזר
               await asyncio.sleep(2 ** attempt)
               continue

**Connection Pooling:**

.. code-block:: python

   # הגדרת connection pool
   client = AsyncIOMotorClient(
       MONGODB_URL,
       maxPoolSize=50,
       minPoolSize=10,
       maxIdleTimeMS=45000,
       serverSelectionTimeoutMS=5000
   )

Redis Unavailability
--------------------

**טיפול עם Fallback:**

.. code-block:: python

   class CacheManager:
       def __init__(self):
           self.redis_available = True
       
       async def get(self, key: str):
           if not self.redis_available:
               return None
           
           try:
               return await redis_client.get(key)
           except Exception as e:
               logger.warning(f"Redis unavailable: {e}")
               self.redis_available = False
               return None
       
       async def set(self, key: str, value: str, expire: int = 300):
           if not self.redis_available:
               return False
           
           try:
               await redis_client.setex(key, expire, value)
               return True
           except Exception as e:
               logger.warning(f"Redis unavailable: {e}")
               self.redis_available = False
               return False

**התנהגות:**
- אם Redis לא זמין, המערכת ממשיכה לעבוד ללא cache
- ביצועים עלולים להיות איטיים יותר
- האירוע נרשם ב-Observability

שגיאות Parsing
---------------

**AST Parsing Errors:**

.. code-block:: python

   try:
       tree = ast.parse(code)
   except SyntaxError as e:
       logger.error(f"Syntax error in code: {e}")
       return {
           'valid': False,
           'error': f"שגיאת תחביר בשורה {e.lineno}: {e.msg}"
       }
   except Exception as e:
       logger.error(f"Unexpected parsing error: {e}", exc_info=True)
       return {
           'valid': False,
           'error': f"שגיאה לא צפויה בניתוח הקוד: {str(e)}"
       }

**Regex Parsing Errors:**

.. code-block:: python

   def safe_regex_search(pattern: str, text: str):
       try:
           # רק בדיקת תקינות תחבירית
           compiled = re.compile(pattern)
           return compiled.search(text)
       except re.error as e:
           logger.warning(f"Invalid regex pattern: {pattern}, error: {e}")
           raise ValueError(f"תבנית regex לא תקינה: {str(e)}")
       except Exception as e:
           logger.error(f"Unexpected regex error: {e}")
           raise

**הערה - ReDoS:**
כרגע הקוד **לא כולל** הגנת ReDoS. רק בדיקת תקינות תחבירית מתבצעת.
מומלץ להוסיף הגנת ReDoS בעתיד (הגבלת אורך, nesting depth, quantifiers מסוכנים).

שגיאות File I/O
----------------

**טיפול בטעינת קבצים:**

.. code-block:: python

   async def safe_file_read(file_path: Path) -> Optional[bytes]:
       try:
           async with aiofiles.open(file_path, 'rb') as f:
               return await f.read()
       except FileNotFoundError:
           logger.warning(f"File not found: {file_path}")
           return None
       except PermissionError:
           logger.error(f"Permission denied: {file_path}")
           return None
       except Exception as e:
           logger.error(f"Unexpected file read error: {e}", exc_info=True)
           return None

**טיפול בכתיבת קבצים:**

.. code-block:: python

   async def safe_file_write(file_path: Path, content: bytes) -> bool:
       try:
           # יצירת תיקייה אם לא קיימת
           file_path.parent.mkdir(parents=True, exist_ok=True)
           
           async with aiofiles.open(file_path, 'wb') as f:
               await f.write(content)
           return True
       except PermissionError:
           logger.error(f"Permission denied: {file_path}")
           return False
       except OSError as e:
           logger.error(f"OS error writing file: {e}")
           return False
       except Exception as e:
           logger.error(f"Unexpected file write error: {e}", exc_info=True)
           return False

שגיאות Network
---------------

**Timeout Handling:**

.. code-block:: python

   import aiohttp
   from aiohttp import ClientTimeout
   
   timeout = ClientTimeout(total=30, connect=10)
   
   async with aiohttp.ClientSession(timeout=timeout) as session:
       try:
           async with session.get(url) as response:
               return await response.json()
       except asyncio.TimeoutError:
           logger.warning(f"Request timeout: {url}")
           raise
       except aiohttp.ClientError as e:
           logger.error(f"Client error: {e}")
           raise

**Retry Logic:**

.. code-block:: python

   from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
   
   @retry(
       stop=stop_after_attempt(3),
       wait=wait_exponential(multiplier=1, min=2, max=10),
       retry=retry_if_exception_type((aiohttp.ClientError, asyncio.TimeoutError))
   )
   async def fetch_with_retry(url: str):
       async with aiohttp.ClientSession() as session:
           async with session.get(url) as response:
               response.raise_for_status()
               return await response.json()

שגיאות Validation
------------------

**קלט לא תקין:**

.. code-block:: python

   def validate_user_input(input_data: Dict) -> Tuple[bool, Optional[str]]:
       # בדיקת סוג
       if not isinstance(input_data, dict):
           return False, "קלט חייב להיות dictionary"
       
       # בדיקת שדות חובה
       required_fields = ['user_id', 'file_name', 'code']
       for field in required_fields:
           if field not in input_data:
               return False, f"שדה חובה חסר: {field}"
       
       # בדיקת ערכים
       if not isinstance(input_data['user_id'], int):
           return False, "user_id חייב להיות מספר"
       
       if not input_data['file_name'] or len(input_data['file_name']) > 255:
           return False, "שם קובץ לא תקין"
       
       if not input_data['code']:
           return False, "קוד לא יכול להיות ריק"
       
       return True, None

**Sanitization:**

.. code-block:: python

   def sanitize_filename(filename: str) -> str:
       # הסרת תווים מסוכנים
       dangerous_chars = ['/', '\\', '..', '<', '>', ':', '"', '|', '?', '*']
       for char in dangerous_chars:
           filename = filename.replace(char, '_')
       
       # הגבלת אורך
       if len(filename) > 255:
           filename = filename[:255]
       
       return filename

שגיאות Concurrent Access
-------------------------

**Race Conditions:**

.. code-block:: python

   import asyncio
   
   # Lock לכל משתמש
   user_locks: Dict[int, asyncio.Lock] = {}
   
   async def safe_user_operation(user_id: int, operation):
       if user_id not in user_locks:
           user_locks[user_id] = asyncio.Lock()
       
       async with user_locks[user_id]:
           return await operation()

**Database Transactions:**

.. code-block:: python

   async def safe_db_transaction(operations: List[Callable]):
       async with await db.client.start_session() as session:
           async with session.start_transaction():
               try:
                   results = []
                   for op in operations:
                       result = await op(session=session)
                       results.append(result)
                   return results
               except Exception as e:
                   await session.abort_transaction()
                   raise

Best Practices
--------------

1. **תמיד השתמש ב-try/except** סביב פעולות שעלולות להיכשל
2. **לוג כל שגיאה** עם הקשר מלא
3. **התראת מנהלים** על שגיאות קריטיות
4. **Fallback mechanisms** לשרותים חיצוניים
5. **Retry logic** עם exponential backoff
6. **Validation** של כל קלט משתמש
7. **Sanitization** של כל קלט לפני שימוש
8. **Timeout** על כל פעולת network
9. **Connection pooling** למסדי נתונים
10. **Graceful degradation** כאשר שירותים לא זמינים

קישורים
--------

- :doc:`/observability/error_codes`
- :doc:`/resilience`
- :doc:`/troubleshooting`
