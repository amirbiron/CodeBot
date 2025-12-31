התקנה והגדרה
=============

דף זה מכיל הוראות התקנה מפורטות עבור Code Keeper Bot.

דרישות מערכת
-------------

**דרישות תוכנה:**

* Python 3.9 או גרסה חדשה יותר
* MongoDB 4.4 או גרסה חדשה יותר
* Redis 6.0+ (אופציונלי, לקאש)
* Git

**דרישות חומרה מינימליות:**

* RAM: 512MB
* דיסק: 1GB פנוי
* מעבד: 1 Core

התקנה מהירה
------------

1. שכפל את הריפוזיטורי
~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

   git clone https://github.com/amirbiron/CodeBot.git
   cd CodeBot

2. התקן תלויות
~~~~~~~~~~~~~~

.. code-block:: bash

   pip install -r requirements/production.txt

3. הגדר משתני סביבה
~~~~~~~~~~~~~~~~~~~

צור קובץ `.env` עם ההגדרות הבאות:

.. code-block:: bash

   # Telegram Bot Token
   BOT_TOKEN=your_bot_token_here
   
   # MongoDB Connection
   MONGODB_URL=mongodb://localhost:27017/code_keeper
   
   # GitHub Integration (אופציונלי)
   GITHUB_TOKEN=your_github_token
   
   # Redis Cache (אופציונלי)
   REDIS_URL=redis://localhost:6379

4. הפעל את הבוט
~~~~~~~~~~~~~~~

.. code-block:: bash

   python main.py

התקנה עם Docker
----------------

1. בנה את ה-Image
~~~~~~~~~~~~~~~~~

.. code-block:: bash

   docker build -t code-keeper-bot .

2. הפעל עם Docker Compose
~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

   docker-compose up -d

הגדרת MongoDB
-------------

**התקנת MongoDB:**

.. code-block:: bash

   # Ubuntu/Debian
   sudo apt-get install mongodb
   
   # macOS
   brew install mongodb-community

**יצירת אינדקסים:**

הבוט יוצר אינדקסים אוטומטית בהפעלה הראשונה.

הגדרת Telegram Bot
-------------------

1. צור בוט חדש דרך `@BotFather <https://t.me/botfather>`_
2. קבל את ה-Token
3. הגדר את הפקודות:

.. code-block:: text

   /start - התחל שיחה עם הבוט
   /save - שמור קוד חדש
   /list - הצג רשימת קבצים
   /search - חפש בקבצים
   /stats - הצג סטטיסטיקות
   /help - עזרה

הגדרות מתקדמות
---------------

**הגדרת הצפנה:**

.. code-block:: python

   # בקובץ config.py
   ENCRYPTION_KEY = os.getenv('ENCRYPTION_KEY')
   ENABLE_ENCRYPTION = True

**הגדרת גיבויים אוטומטיים:**

.. code-block:: python

   # בקובץ config.py
   BACKUP_ENABLED = True
   BACKUP_INTERVAL = 3600  # בשניות
   BACKUP_PATH = '/path/to/backups'

**הגדרת Rate Limiting:**

.. code-block:: python

   # בקובץ config.py
   RATE_LIMIT_ENABLED = True
   MAX_REQUESTS_PER_MINUTE = 30

בדיקת התקנה
------------

לאחר ההתקנה, ודא שהכל עובד:

.. code-block:: bash

   # בדוק חיבור למונגו
   python -c "from database import db; print(db.test_connection())"
   
   # בדוק את הבוט
   python test_basic.py

פתרון בעיות
-----------

**הבוט לא מתחבר לטלגרם:**

* ודא שה-Token נכון
* בדוק חיבור לאינטרנט
* ודא שאין חומת אש חוסמת

**MongoDB לא זמין:**

* ודא שהשירות פועל: `sudo systemctl status mongodb`
* בדוק את ה-URL בקובץ `.env`

**שגיאות בהתקנת תלויות:**

.. code-block:: bash

   # נסה עם pip מעודכן
   pip install --upgrade pip
   pip install -r requirements/production.txt

תמיכה
------

לתמיכה נוספת:

* פתח Issue ב-GitHub
* שלח הודעה בקבוצת התמיכה
* עיין בתיעוד המלא