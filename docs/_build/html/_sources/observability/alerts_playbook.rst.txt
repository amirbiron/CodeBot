Playbook קצר להתראות
======================

זרימה
-----

1. התקבלה התראה → רשמו ``alert_received`` עם ``request_id`` אם יש.
2. קשרו לוגים לפי ``request_id``/``trace_id``.
3. פעלו לפי ה-``remediation`` של ה-``error_code``.
4. בדקו השפעה בדשבורד (P95 / error rate). הסלימו אם אין שיפור.

קישורים בקוד
------------
- נקודת קצה: ``POST /alerts`` ב-``services/webserver.py``.
- מעביר התראות: ``alert_forwarder.py``.

דגשים
-----
- לא לכלול PII בלוגים.
- לשמור על ``event`` קנוני ו-``msg_he`` קצר.
