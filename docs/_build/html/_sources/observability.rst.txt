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

קישורים
--------
- :doc:`logging_schema`
- :doc:`metrics`
- :doc:`alerts`
- :doc:`sentry`
- :doc:`runbooks/logging-levels`
