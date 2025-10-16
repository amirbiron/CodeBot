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
- OpenTelemetry IDs (אם קיימים).
- Prometheus דרך נקודת קצה ``/metrics``.
- Sentry לטיפול בשגיאות.

קישורים
--------
- :doc:`logging_schema`
- :doc:`metrics`
- :doc:`alerts`
- :doc:`sentry`
- :doc:`runbooks/logging-levels`
