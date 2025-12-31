Tracing ממוקד בנקודות חמות
===========================

מדריך קצר להתמקדות ב‑Tracing בנקודות בעלות השפעה גבוהה (Hotspots) בבוט וב‑WebApp.

תרשימי זרימה
-------------

זרימת bot.update
~~~~~~~~~~~~~~~~~
.. mermaid::

   graph TD
       A[bot.update Request] --> B[Process Update]
       B --> C[DB Operations]
       C --> D[External APIs]
       D --> E[Response]

       style A fill:#e1f5fe
       style E fill:#c8e6c9

מאפיינים מומלצים ל‑Spans (bot.update)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
- ``status``: "ok"/"error"
- ``user_id_hash``: מזהה מוצפן
- ``chat_id_hash``: מזהה צ'אט מוצפן
- ``retry_count``: 0–3
- ``duration_ms``
- ``update_type``: message/callback/inline

זרימת web.request
~~~~~~~~~~~~~~~~~~
.. mermaid::

   graph LR
       A[HTTP Request] --> B[Flask WebApp]
       B --> C[Search with Cache]
       C --> D[Response]

       style A fill:#fff3e0
       style D fill:#f3e5f5

מאפיינים מומלצים ל‑Spans (web.request)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
- ``http.status_code``
- ``component``: "flask.webapp"
- ``cache_hit``: true/false
- ``user_id_hash``
- ``method``: GET/POST/PUT/DELETE
- ``path``

טבלת "היכן עוטפים"
-------------------

.. list-table:: כיסוי דקורטור
   :header-rows: 1

   * - מודול
     - פונקציה
     - דקורטור
     - מאפיינים נרשמים
     - סטטוס
   * - ``search_engine``
     - ``search()``
     - ``@traced("search")``
     - query, results_count, status
     - מיושם
   * - ``database``
     - ``get_user_files()``
     - ``@traced("db.get_user_files")``
     - user_id_hash, file_count, status
     - מיושם
   * - ``integration``
     - ``share_code()``
     - ``@traced("integration.share_code")``
     - platform, code_size, status
     - מיושם
   * - ``services/code_service``
     - ``validate_code_input()``, ``analyze_code()``, ``extract_functions()``
     - ``@traced("code_service.*")``
     - language, code.length, status
     - מיושם
   * - ``http_sync``
     - ``request()``
     - ``@traced("http_sync.request")``
     - http.status_code, status, duration_ms, retry_count
     - מיושם
   * - ``auth``
     - ``verify_token()``
     - ``@traced("auth")``
     - token_type, valid, user_role
     - בפייפליין
   * - ``cache``
     - ``get/set()``
     - ``@traced("cache")``
     - key, hit/miss, ttl
     - בפייפליין

דוגמת Trace Viewer
-------------------

לפני השיפור::

   [REQUEST] ────────────────────────── 2500ms
     └── [HANDLER] ──────────────────── 2400ms

אחרי השיפור::

   [bot.update] ────────────────────────── 2500ms
     ├── [db.get_user_files] ─ 200ms
     │   └── attributes: {status: "ok", user_id_hash: "a3f2...", file_count: 5}
     ├── [search_engine.search] ────── 1800ms
     │   └── attributes: {status: "ok", query: "python", results: 42}
     └── [integration.share_code] ── 400ms
         └── attributes: {status: "ok", platform: "github"}

   [web.request] ────────────────────────── 1200ms
     ├── attributes: {component: "flask.webapp", http.status_code: 200}
     └── [search] ─────── 900ms
         └── attributes: {cache_hit: true, status: "ok"}

הטמעת דקורטור ושימוש בפונקציות עזר
------------------------------------

.. code-block:: python

   from observability_instrumentation import traced, start_span, set_current_span_attributes

   # שימוש בדקורטור
   @traced("search_engine.search")
   async def search(query: str):
       set_current_span_attributes({
           "query": query,
           "status": "in_progress"
       })
       try:
           results = await perform_search(query)
           set_current_span_attributes({
               "results_count": len(results),
               "status": "ok"
           })
           return results
       except Exception as e:
           set_current_span_attributes({
               "status": "error",
               "error_message": str(e)
           })
           raise

   # Span ידני
   async def complex_operation():
       with start_span("custom_operation") as span:
           set_current_span_attributes({"step": "processing"})
           # ... לוגיקה ...

Best Practices
--------------
1. **מתי להוסיף Span**: פעולות I/O, לוגיקה עסקית >100ms, נקודות כשל.
2. **מאפיינים חשובים**: תמיד `status`, `user_id_hash`; לפי הקשר: `cache_hit`, `retry_count`, `error_message`.
3. **טיפ**: השתמשו ב‑``set_current_span_attributes()`` לעדכון מאפיינים לאורך הפעולה.
4. **אל תעשה**: אל תעטפו פונקציות קטנות (<10ms), אל תכללו מידע רגיש, אל תיצרו spans בתוך לולאות טייטות.

ראו גם
------
- :doc:`/observability`
- :doc:`/observability/log_based_alerts`
- :doc:`/sentry`
