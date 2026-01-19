Asyncio תחת WSGI: הרצת קורוטינות בבטחה
======================================

רקע קצר
-------
ב-WebApp שמורץ תחת WSGI (Flask + Gunicorn/gevent), עלולה להיות לולאת Event
פעילה כבר בתוך ה-thread של הבקשה. במצב כזה קריאה ל-``asyncio.run`` תזרוק
חריגה ותפיל את הבקשה, ולעתים תשאיר קורוטינה "תלויה" ללא await.

תסמינים נפוצים
---------------
- ``RuntimeError: asyncio.run() cannot be called from a running event loop``
- ``RuntimeError: This event loop is already running``
- ``RuntimeWarning: coroutine was never awaited``

מתי זה קורה בפועל
-----------------
- בדיקות בריאות DB שמריצות קורוטינות מתוך בקשת WSGI.
- כל עטיפה שמריצה קורוטינה ב-thread "נקי" אבל מתנגש עם gevent.
- מצב מרוץ שבו ה-loop משתנה בין בדיקה להרצה.

דפוס בטוח מומלץ
---------------
- נסה לקבל loop קיים ב-thread הנוכחי.
- אם אין loop, צור חדש והגדר אותו ל-thread.
- הרץ עם ``run_until_complete``.
- אם מתקבלת שגיאת "event loop is already running", בצע fallback להרצה ב-threadpool.

דוגמה קצרה
----------
.. code-block:: python

   async def _runner():
       return await awaitable

   def _run_in_thread():
       try:
           loop = asyncio.get_event_loop()
       except RuntimeError:
           loop = asyncio.new_event_loop()
           asyncio.set_event_loop(loop)
       try:
           return loop.run_until_complete(_runner())
       except RuntimeError as e:
           err = str(e).lower()
           if "event loop is already running" in err:
               return threadpool.submit(_run_in_thread).result()
           raise

Checklist לפני דיפלוי
---------------------
- אין שימוש ישיר ב-``asyncio.run`` בתוך WSGI thread.
- קיימת שכבת fallback ל-threadpool במקרה של loop פעיל.
- הודעות השגיאה מכסות גם ``asyncio.run() cannot be called...`` וגם
  ``event loop is already running``.
