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

כיוונון רעש
-----------
- ``ALERT_TELEGRAM_MIN_SEVERITY`` – מגדיר מאיזה דרגת חומרה (``anomaly``/``info``/``warn``/``error``/``critical``) בכלל נשלחות הודעות לטלגרם. הערך חל גם במסלול הגיבוי של ``internal_alerts`` כך שאם תציבו ``warn`` תקבלו רק אירועים משמעותיים גם כשה-forwarder אינו זמין.
- ``ALERT_ANOMALY_BATCH_WINDOW_SECONDS`` – חלון מתגלגל (ברירת מחדל 180 שניות) שמאפשר לקבץ כמה התראות ``anomaly`` דומות להודעת טלגרם אחת עם טקסט בסגנון ``"N מופעים ב-X דקות"``. העלאת הערך מפחיתה רעש בזמני עומס ידועים.
- ``ALERT_AVG_RESPONSE_TIME`` – רף ה-EWMA שמוגדר ב-``metrics.py`` להתראת ``anomaly_detected``. ברירת המחדל עודכנה ל-``3.0`` שניות (קודם ``2.0``) כדי לא להפנות תשומת לב על תנודות קלות. הציבו ``0`` כדי לנטרל או ערך גבוה/נמוך יותר לפי SLA.

טיפים מהירים
------------
- בקבוצות עם ספייקים ידועים, העלו את ``ALERT_ANOMALY_BATCH_WINDOW_SECONDS`` ל-600–900 שניות ושמרו על ``ALERT_TELEGRAM_MIN_SEVERITY=warn``.
- אם רוצים שהמדידה תמשיך להופיע בלוגים/Slack אבל לא בטלגרם, הוסיפו ``ALERT_TELEGRAM_MIN_SEVERITY=error`` מבלי לשנות את דשבורדי Grafana.
