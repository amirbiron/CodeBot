סכמת לוגים
==========

שדות חובה
---------
- ``schema_version`` (למשל ``"1.0"``)
- ``event`` (שם קנוני ב-``snake_case``)
- ``severity`` (``info``/``warn``/``error``)
- ``timestamp`` (``ISO8601``)
- ``request_id``
- ``trace_id``/``span_id`` (אם OTel פעיל)

שדות מומלצים
------------
- ``user_ref`` (מזהה לא-PII)
- ``resource`` (``{type, id}``)
- ``attributes`` (שדות ייעודיים לאירוע)
- ``error_code`` (לפי טקסונומיית השגיאות)
- ``msg_he`` (טקסט קריא בעברית)

דוגמה
-----
.. code-block:: json

   {
     "schema_version": "1.0",
     "event": "file_saved",
     "severity": "info",
     "timestamp": "2025-10-15T10:23:45.123Z",
     "request_id": "a3f2c891",
     "trace_id": "0123abcd0123abcd0123abcd0123abcd",
     "span_id": "abcd0123abcd0123",
     "user_ref": "u_12345",
     "resource": {"type": "file", "id": "file_789"},
     "attributes": {"language": "python", "size_bytes": 1520},
     "msg_he": "קובץ נשמר בהצלחה"
   }

טקסונומיית שגיאות (Error codes)
--------------------------------
.. code-block:: yaml

   errors:
     E_FILE_DUPLICATE:
       category: storage
       severity: error
       remediation: "בדקו unique index; הציעו למשתמש שם חדש."
     E_SEARCH_TIMEOUT:
       category: search
       severity: warn
       remediation: "הקטינו טווח חיפוש; בדקו אינדקס/Cache."
     E_AUTH_INVALID_SESSION:
       category: auth
       severity: warn
       remediation: "ביצוע התחברות מחדש; בדיקת עוגייה."
