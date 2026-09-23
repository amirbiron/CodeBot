התקנה והגדרה
=============
:summary: דף זה מכיל הוראות התקנה מפורטות עבור Code Keeper Bot.

דרישות מערכת
-------------

**דרישות תוכנה:**

* Python 3.9 או גרסה חדשה יותר
* MongoDB 5.2 או גרסה חדשה יותר. רשימות הקבצים בוובאפ בוחרות את הגרסה האחרונה של כל קובץ עם ``$top`` (``_latest_version_per_file_stages`` ב-``webapp/app.py``), ו-`האופרטור הזה נוסף ב-MongoDB 5.2 <https://www.mongodb.com/docs/manual/reference/operator/aggregation/top/>`_. עמודים אחרים מפנים לכאן ולא חוזרים על המספר, כדי שיהיה מקום אחד לעדכן כשקוד חדש נשען על אופרטור חדש יותר.
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

3. שדרוג volume קיים מ-MongoDB 6.0
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. warning::
   **יש volume שנוצר בזמן של mongo:6.0? העלייה הראשונה ל-mongo:8.0 תיכשל.** מונגו אינה מרשה לדלג על גרסה ראשית: מונגו 8 מסרבת לעלות על קבצי נתונים שה-``featureCompatibilityVersion`` שלהם ``6.0``, יוצאת בקוד 62, ומכיוון שהשירות מוגדר ``restart: unless-stopped`` היא נכנסת ללופ נפילות. ה-healthcheck לעולם אינו נעשה ירוק, ולכן ``code-keeper-bot`` — שתלוי ב-``condition: service_healthy`` — פשוט אינו עולה, בלי שגיאה שמסבירה למה. בלוג של הקונטיינר רואים ``UPGRADE PROBLEM: Found an invalid featureCompatibilityVersion document``. אותו דבר בדיוק חל על ``docker-compose.dev.yml`` (השירות ``mongodb-dev`` וה-volume ``mongodb_dev_data``).

   ``<user>`` ו-``<pass>`` בפקודות הם ``MONGO_USERNAME`` ו-``MONGO_PASSWORD`` מה-``.env`` (ברירת המחדל: ``admin`` ו-``password123``), ושם ה-volume הוא ``<שם הפרויקט>_mongodb_data`` — ``docker volume ls`` מראה את השם המדויק.

   **א. הנתונים אינם חשובים — זה המצב הרגיל בפיתוח:**

   .. code-block:: bash

      docker compose down -v   # ⚠️ מוחק את כל ה-volumes של ה-compose, כולל mongodb_data. בלתי הפיך
      docker compose up -d

   **ב. הנתונים חשובים — עוברים דרך 7.0 פעם אחת:**

   .. code-block:: bash

      # 1. מרימים 7.0 על אותו volume ומעלים את ה-FCV
      docker compose down
      docker run --rm -d --name ck-mongo-upgrade -v <שם הפרויקט>_mongodb_data:/data/db \
          -e MONGO_INITDB_ROOT_USERNAME=<user> -e MONGO_INITDB_ROOT_PASSWORD=<pass> \
          mongo:7.0 mongod --auth
      docker exec ck-mongo-upgrade mongosh -u <user> -p <pass> \
          --eval 'db.adminCommand({setFeatureCompatibilityVersion: "7.0", confirm: true})'
      docker stop ck-mongo-upgrade

      # 2. עולים ל-8.0 כרגיל, ואחרי שהשירות בריא מעלים את ה-FCV ל-8.0
      docker compose up -d
      docker compose exec mongodb mongosh -u <user> -p <pass> \
          --eval 'db.adminCommand({setFeatureCompatibilityVersion: "8.0", confirm: true})'

   המסלול הזה נמדד מקצה לקצה על volume שנוצר ב-6.0: ‏7.0 עולה על נתוני 6.0, ``setFeatureCompatibilityVersion`` מחזיר ``{ok: 1}``, ואז 8.0 עולה בלי נפילה והנתונים במקומם. ``confirm: true`` נדרש מ-7.0 ומעלה.

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