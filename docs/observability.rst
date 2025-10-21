אובזרווביליות (Observability)
==============================

מטרות
------
- לוגים מובנים עם ``event`` ו-``error_code``.
- קורלציה בין אירועים באמצעות ``request_id`` ו-``trace_id``.
- מטריקות: ספירות, זמני תגובה, מצב מערכת.
- התראות: הגדרת ספים וזיהוי תקלות אוטומטי.
- פרטיות: טשטוש מידע רגיש (Redaction) ודגימה (Sampling).

קהלי יעד
--------
- סוכני AI: לזיהוי דפוסים וביצוע פעולות תיקון (Remediation).
- מפתחים: לדיבוג מהיר וניטור ביצועים.

תצורה
------
- Structured logging באמצעות ``structlog``.
- OpenTelemetry (אופציונלי): אתחול אוטומטי עם OTLP Exporter.
  
  משתני סביבה עיקריים:
  
  - ``OTEL_EXPORTER_OTLP_ENDPOINT``: ברירת מחדל ``http://localhost:4317``
  - ``OTEL_EXPORTER_INSECURE``: ``true``/``false`` (ברירת מחדל ``false``)
  - ``ENVIRONMENT`` / ``ENV``: שם סביבה לדיווח resource
  - ``APP_VERSION``: גרסה לשיוך ל-``service.version``
  
  אינסטרומנטציה אוטומטית:
  - Flask (כשקיים אובייקט ``app``)
  - Requests
  - PyMongo
  
  עבור Flask האתחול קורה ב-``webapp/app.py``. עבור תהליכים ללא Flask (למשל הבוט), האתחול קורה ב-``main.py`` ללא ``flask_app``.
- Prometheus דרך נקודת קצה ``/metrics``.
- Sentry לטיפול בשגיאות.

בחירת Backend ל־Traces
-----------------------
מומלץ להתחיל עם אחד מהבאים (כולם תומכים ב־OTLP):

- Jaeger (פשוט לפריסה מקומית/דוקר)
- Grafana Tempo (סקיילבל, מתאים לשילוב עם Grafana/Prometheus)
- Grafana Cloud (שירות מנוהל)

הגדרת OTLP לסביבות
--------------------
הגדירו משתני סביבה בכל סביבה:

.. code-block:: bash

    # Staging
    export ENVIRONMENT=staging
    export APP_VERSION=1.2.3
    export OTEL_EXPORTER_OTLP_ENDPOINT="http://tempo.staging.svc:4317"
    export OTEL_EXPORTER_INSECURE=true

    # Production
    export ENVIRONMENT=production
    export APP_VERSION=1.2.3
    export OTEL_EXPORTER_OTLP_ENDPOINT="https://otlp.prod.example.com:4317"
    export OTEL_EXPORTER_INSECURE=false

הערות:

- ב־gRPC ברירת המחדל היא יציאה 4317.
- כאשר עובדים מול TLS פרטי/מאולתר, ניתן להגדיר ``OTEL_EXPORTER_INSECURE=true``.
- ודאו פתיחת פיירוול/Ingress ליצוא ה־OTLP מהאפליקציה.

קישורים
--------
- :doc:`logging_schema`
- :doc:`metrics`
- :doc:`alerts`
- :doc:`sentry`
- :doc:`runbooks/logging-levels`


אינסטרומנטציה ידנית (Manual Instrumentation)
---------------------------------------------
בנוסף לאינסטרומנטציה האוטומטית של Flask/Requests/PyMongo, ניתן להוסיף טרייסים ומטריקות ידניות עם הדקורטור `@traced` מתוך המודול `observability_instrumentation`.

מאפיינים:

- בטוח להרצה בלי תלות ב־OpenTelemetry (No‑Op אם לא מותקן)
- יוצר Span בשם קבוע שניתן להגדיר
- מודד משך זמן ומסמן חריגות במטריקות (`request.duration`, `errors.total`, `requests.active`)

דוגמאות שימוש:

.. code-block:: python

    from observability_instrumentation import traced

    @traced("bookmarks.toggle")
    def toggle_bookmark(...):
        # קוד הפונקציה
        pass

    @traced("batch.reindex")
    async def reindex_all(...):
        # קוד אסינכרוני
        ...

הערות:

- הדקורטור פועל גם על פונקציות sync וגם על async.
- כאשר מתרחשת חריגה, משך הפעולה נרשם פעם אחת בלבד עם המאפיין ``error=True``.
- עבור Flask, האינסטרומנטציה האוטומטית מוסיפה טרייסים ברמת הבקשה; שימוש ב־`@traced` מומלץ סביב פעולות עסקיות קריטיות בתוך הידלרים או שירותים.
