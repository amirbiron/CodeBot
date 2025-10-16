מילון קודי שגיאה (Error Codes)
===============================

.. admonition:: DoD
   :class: important

   קודים אלה משמשים לקיבוץ חכם (Sentry) ולמיפוי Remediation. יש לוודא כיסוי בשגיאות קריטיות.

דוגמאות מיפוי
--------------

.. code-block:: yaml

   errors:
     E_METRICS_VIEW:
       category: web
       severity: error
       remediation: "בדקו זמינות /metrics והרשאות; נסו שוב."
     E_ALERTS_PARSE:
       category: alerts
       severity: warn
       remediation: "בדקו את ה-JSON/Content-Type המגיע מה-Alertmanager."
     E_SHARE_VIEW:
       category: web
       severity: error
       remediation: "בדקו מזהה שיתוף וקישור פג תוקף."
     E_BACKUP_CREATE:
       category: backup
       severity: error
       remediation: "ודאו הרשאות/דיסק; נסו שוב; עדכנו משתמש."
     E_FILE_UNREADABLE:
       category: io
       severity: error
       remediation: "נסו קידוד חלופי; עדכנו את המשתמש."
     E_FILE_PROCESS:
       category: io
       severity: error
       remediation: "אספו request_id, בצעו ניסיון נוסף, דווחו ל-Sentry."

הנחיות
-------
- הוסיפו ``error_code`` לכל שגיאה קריטית.
- התאימו את הקוד לקטגוריה יציבה (``db``/``web``/``github``/``io``/``alerts``/``backup``).
- הקפידו על שמות עקביים כדי לא לפצל קבוצות שגיאה.
