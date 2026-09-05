Asyncio תחת WSGI: הרצת קורוטינות בבטחה
======================================
:summary: ב-WebApp שרץ כ-Flask על WSGI עם worker של gevent, קוד סינכרוני אינו יכול להריץ לולאת asyncio בבטחה — גרינלטים חולקים OS thread, ו-asyncio שומר את מצב הלולאה הרצה ברמת ה-thread. העמוד מסביר את המנגנון, את התסמינים, ואת הכיוון הנכון: שירות סינכרוני.

רקע קצר
-------
ה-WebApp רץ כ-Flask על WSGI, עם gunicorn ו-``worker_class=gevent``. ה-worker
הזה מריץ ``monkey.patch_all()`` בעליית התהליך, וכל הבקשות שלו רצות כגרינלטים
**באותו OS thread**.

asyncio, לעומת זאת, שומר את מצב "הלולאה הרצה" ברמת ה-thread ולא ברמת הגרינלט.
מכאן נובע הכל: ברגע שגרינלט אחד נמצא בתוך ``run_until_complete``, **כל גרינלט
אחר באותו worker רואה את הלולאה שלו כרצה** — ונופל.

.. warning::

   העמוד הזה תיאר בעבר "דפוס בטוח מומלץ" שמנסה לגשר על הפער: לתפוס את השגיאה
   ולעשות fallback ל-threadpool, ואז ל-thread "נקי". **הדפוס הזה אינו עובד,
   והוסר מהקוד.** הסיבה מתועדת למטה.

התסמינים
--------
- ``RuntimeError: Cannot run the event loop while another loop is running``
- ``RuntimeError: asyncio.run() cannot be called from a running event loop``
- ``RuntimeError: This event loop is already running``
- ``RuntimeWarning: coroutine ... was never awaited``

התסמין המבלבל ביותר הוא **שהתקלה נראית אקראית**: בקשה בודדת עוברת, ורק בקשות
חופפות נופלות. רענון של הדף בדרך כלל "מתקן", וזה בדיוק מה שמסתיר את הבעיה.

למה ה-fallback ל-thread לא עוזר
-------------------------------
המעטפת שהוסרה ניסתה שלוש שכבות: לולאה חדשה ← threadpool ← thread "נקי" שהתקבל
מ-``monkey.get_original("threading", "Thread")``. **שלושתן חיות באותו OS thread**:

- ``ThreadPoolExecutor`` שנוצר אחרי ה-monkey patching מייצר גרינלטים, לא threads.
- ``get_original("threading", "Thread")`` מחזיר את המחלקה המקורית — אבל
  ``Thread.start()`` שלה קוראת ל-``threading._start_new_thread``, ש-gevent דרס
  **במקום**. התוצאה היא גרינלט, לא thread.

לכן כל שלוש השכבות רואות את אותה לולאה ונופלות ברצף, עם אותה שגיאה שלוש פעמים.

הכיוון הנכון
------------
**אל תריצו asyncio מתוך קוד סינכרוני שרץ תחת WSGI.** תחת gevent, קריאת I/O
סינכרונית (pymongo, HTTP) ממילא אינה חוסמת — ה-monkey patching הופך אותה
לקואופרטיבית. כלומר ה-``asyncio.to_thread`` לא קונה כלום כאן, ורק מכניס לולאה
למקום שאין בו לולאה.

- **שירות שנצרך מ-WSGI נכתב סינכרוני.** ראו ``services/query_profiler_service.py``
  ו-``SyncDatabaseHealthService`` ב-``services/db_health_service.py``.
- **צרכן אסינכרוני אמיתי מתאים את עצמו לשירות**, לא להפך: מתוך event loop קיים
  עוטפים את הקריאה הסינכרונית ב-``asyncio.to_thread``. זה הכיוון ההפוך מהדפוס
  השבור, וזה מה ש-``ThreadPoolDatabaseHealthService`` עושה.
- **ראוטים של Flask נכתבים ``def``, לא ``async def``.** Flask מריץ ראוט אסינכרוני
  דרך ``asgiref``, שפותח לולאה משלו ב-``ThreadPoolExecutor`` — כלומר בגרינלט —
  והלולאה הזו דולפת לכל שאר הבקשות באותו worker.

Checklist לפני דיפלוי
---------------------
- אין ``asyncio.run`` / ``run_until_complete`` / ``loop.create_task`` בשום מסלול
  שנקרא מבקשת WSGI.
- אין ``async def`` על ראוט של Flask.
- שירות חדש שנצרך מה-WebApp — סינכרוני.
- אם נדרשת בכל זאת אסינכרוניות: היא חיה אצל הצרכן האסינכרוני, ועוטפת את השירות
  הסינכרוני ב-``asyncio.to_thread``.

איך בודקים את זה
----------------
``conftest.py`` מכבה את ה-monkey patching של gevent בכל סוויטת הטסטים
(``CODEBOT_DISABLE_GEVENT_PATCH``), ולכן **טסט רגיל אינו מסוגל לשחזר את הבאג**.
בדיקה אמיתית חייבת לרוץ בתת-תהליך שמפעיל gevent בעצמו, מרים
``gevent.pywsgi.WSGIServer`` (אותו שרת שה-worker של gunicorn מריץ), ויורה בקשות
**חופפות**. ראו ``tests/test_profiler_sync_under_gevent.py`` ואת עוזר התת-תהליך
לידו.
