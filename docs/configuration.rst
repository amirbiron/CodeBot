הגדרות תצורה
============

מדריך מפורט להגדרת Code Keeper Bot.

קובץ התצורה הראשי
-----------------

הבוט משתמש בקובץ `config.py` להגדרות הראשיות:

.. automodule:: config
   :members:
   :undoc-members:
   :noindex:

משתני סביבה
-----------

רשימת כל משתני הסביבה הנתמכים:

**הגדרות בסיסיות:**

.. code-block:: bash

   # Telegram Bot
   BOT_TOKEN=your_bot_token_here
   BOT_USERNAME=@YourBotUsername
   
   # Database
   MONGODB_URL=mongodb://localhost:27017/code_keeper
   DATABASE_NAME=code_keeper
   
   # Admin Users
   ADMIN_USER_IDS=123456789,987654321

**הגדרות GitHub:**

.. code-block:: bash

   # GitHub Integration
   GITHUB_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxx
   GITHUB_USERNAME=your_username
   GITHUB_DEFAULT_REPO=code-snippets

**הגדרות אבטחה:**

.. code-block:: bash

   # Encryption
   ENCRYPTION_KEY=your-32-byte-encryption-key-here
   ENABLE_ENCRYPTION=true
   
   # Rate Limiting
   RATE_LIMIT_ENABLED=true
   MAX_REQUESTS_PER_MINUTE=30
   MAX_FILES_PER_USER=1000

**הגדרות ביצועים:**

.. code-block:: bash

   # Cache
   REDIS_URL=redis://localhost:6379
   CACHE_TTL=3600
   
   # Performance
   MAX_WORKERS=4
   CONNECTION_POOL_SIZE=10
   REQUEST_TIMEOUT=30

**הגדרות גיבוי:**

.. code-block:: bash

   # Backup
   BACKUP_ENABLED=true
   BACKUP_INTERVAL=3600
   BACKUP_PATH=/var/backups/code-keeper
   BACKUP_RETENTION_DAYS=30

הגדרות מתקדמות
---------------

**הגדרת Webhooks:**

.. code-block:: python

   # עבור production עם webhooks
   WEBHOOK_URL = "https://your-domain.com/webhook"
   WEBHOOK_PORT = 8443
   WEBHOOK_LISTEN = "0.0.0.0"

**הגדרת Logging:**

.. code-block:: python

   # רמות לוג
   LOG_LEVEL = "INFO"  # DEBUG, INFO, WARNING, ERROR, CRITICAL
   LOG_FILE = "/var/log/code-keeper/bot.log"
   LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

**הגדרת שפות תכנות נתמכות:**

.. code-block:: python

   SUPPORTED_LANGUAGES = [
       'python', 'javascript', 'java', 'cpp', 'c',
       'csharp', 'go', 'rust', 'ruby', 'php',
       'swift', 'kotlin', 'typescript', 'scala',
       'r', 'matlab', 'sql', 'bash', 'powershell'
   ]

**הגדרת גבולות:**

.. code-block:: python

   # גבולות גודל
   MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
   MAX_CODE_LENGTH = 100000  # תווים
   MAX_FILENAME_LENGTH = 255
   
   # גבולות כמות
   MAX_FILES_PER_USER = 1000
   MAX_SEARCH_RESULTS = 50
   MAX_BATCH_SIZE = 10

הגדרת MongoDB
-------------

**אינדקסים מומלצים:**

.. code-block:: javascript

   // אינדקס לחיפוש מהיר
   db.code_snippets.createIndex({ "user_id": 1, "created_at": -1 })
   db.code_snippets.createIndex({ "programming_language": 1 })
   db.code_snippets.createIndex({ "file_name": "text" })
   
   // אינדקס לחיפוש טקסט מלא
   db.code_snippets.createIndex({ "code": "text", "note": "text" })

**הגדרות ביצועים:**

.. code-block:: yaml

   # mongod.conf
   storage:
     wiredTiger:
       engineConfig:
         cacheSizeGB: 1
   
   net:
     maxIncomingConnections: 100

הגדרת Redis Cache
-----------------

**תצורת Redis:**

.. code-block:: ini

   # redis.conf
   maxmemory 256mb
   maxmemory-policy allkeys-lru
   
   # Persistence
   save 900 1
   save 300 10
   save 60 10000

**שימוש בקאש:**

.. code-block:: python

   # הפעלת קאש
   CACHE_ENABLED = True
   
   # מה לשמור בקאש
   CACHE_USER_DATA = True
   CACHE_SEARCH_RESULTS = True
   CACHE_STATISTICS = True

**עמידות לתקלות Redis ו-SAFE_MODE:**

- ניתן לקבוע timeouts ללקוח Redis דרך משתני סביבה:

  .. code-block:: bash

     REDIS_CONNECT_TIMEOUT=5   # או 1 כאשר SAFE_MODE=1
     REDIS_SOCKET_TIMEOUT=5    # או 1 כאשר SAFE_MODE=1

- פעולות ניקוי הקאש מוגבלות בזמן כדי שלא יחסמו את השרת אם Redis איטי/קפוא:

  .. code-block:: bash

     CACHE_CLEAR_BUDGET_SECONDS=1  # עבור clear_stale (ברירת מחדל 1)
     # clear_all משתמש בברירת מחדל 2 שניות

- ניתן לדלג לחלוטין על פעולות ניקוי/מנע ולרשום לוג בלבד:

  .. code-block:: bash

     DISABLE_CACHE_MAINTENANCE=1
     DISABLE_PREEMPTIVE_ACTIONS=1
     SAFE_MODE=1  # מפעיל ברירות מחדל שמרניות ודילוגים בטוחים

הגדרות אבטחה
-------------

**הצפנת נתונים:**

.. code-block:: python

   # הצפנת קוד בדאטאבייס
   ENCRYPT_CODE = True
   ENCRYPTION_ALGORITHM = "AES-256-GCM"
   
   # הצפנת תקשורת
   USE_HTTPS = True
   SSL_CERT_PATH = "/path/to/cert.pem"
   SSL_KEY_PATH = "/path/to/key.pem"

**הגנה מפני התקפות:**

.. code-block:: python

   # Anti-spam
   SPAM_DETECTION_ENABLED = True
   MAX_MESSAGES_PER_MINUTE = 10
   
   # Input validation
   STRICT_INPUT_VALIDATION = True
   SANITIZE_HTML = True
   
   # Session security
   SESSION_TIMEOUT = 3600
   REQUIRE_AUTHENTICATION = True

תצורה לסביבות שונות
--------------------

**Development:**

.. code-block:: python

   # .env.development
   DEBUG = True
   LOG_LEVEL = "DEBUG"
   MONGODB_URL = "mongodb://localhost:27017/code_keeper_dev"

**Staging:**

.. code-block:: python

   # .env.staging
   DEBUG = False
   LOG_LEVEL = "INFO"
   MONGODB_URL = "mongodb://staging-db:27017/code_keeper_staging"

**Production:**

.. code-block:: python

   # .env.production
   DEBUG = False
   LOG_LEVEL = "WARNING"
   MONGODB_URL = "mongodb://prod-db:27017/code_keeper"
   USE_WEBHOOK = True

דוגמת קובץ .env מלא
--------------------

.. code-block:: bash

   # === Telegram Configuration ===
   BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz
   BOT_USERNAME=@CodeKeeperBot
   
   # === Database Configuration ===
   MONGODB_URL=mongodb://localhost:27017/code_keeper
   DATABASE_NAME=code_keeper
   
   # === GitHub Integration ===
   GITHUB_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxx
   GITHUB_USERNAME=myusername
   
   # === Security ===
   ENCRYPTION_KEY=my-super-secret-32-byte-key-here!
   ADMIN_USER_IDS=123456789,987654321
   
   # === Performance ===
   REDIS_URL=redis://localhost:6379
   MAX_WORKERS=4
   
   # === Features ===
   BACKUP_ENABLED=true
   CACHE_ENABLED=true
   RATE_LIMIT_ENABLED=true

טיפים וטריקים
-------------

1. **שמור את קובץ .env מחוץ ל-Git:**

   .. code-block:: bash
   
      echo ".env" >> .gitignore

2. **השתמש בסיסמאות חזקות:**

   .. code-block:: python
   
      import secrets
      encryption_key = secrets.token_hex(32)

3. **בדוק הגדרות בהפעלה:**

   .. code-block:: python
   
      from config import config
      config.validate()

4. **גבה את ההגדרות:**

   .. code-block:: bash
   
      cp .env .env.backup