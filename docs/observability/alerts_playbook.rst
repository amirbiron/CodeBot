Playbook קצר להתראות
======================

זרימה
-----

1. התקבלה התראה → רשמו ``alert_received`` עם ``request_id`` אם יש.
2. קשרו לוגים לפי ``request_id``/``trace_id``.
3. פעלו לפי ה-``remediation`` של ה-``error_code``.
4. בדקו השפעה בדשבורד (P95 / error rate). הסלימו אם אין שיפור.

דיאגרמת מערכת התראות חכמות
--------------------------

התרשים הבא מציג את הזרימה המלאה של מערכת ההתראות - מזיהוי האירוע ועד לשליחת ההתראה:

.. mermaid::

   graph TD
       subgraph "Detection Layer"
           M1[Error Rate Monitor]
           M2[Latency Monitor]
           M3[Rate Limit Monitor]
           M4[System Health Monitor]
       end

       subgraph "Analysis Layer"
           M1 --> AE[Alert Engine]
           M2 --> AE
           M3 --> AE
           M4 --> AE
           AE --> TA{Threshold Analysis}
       end

       subgraph "Decision Layer"
           TA -->|Critical| C[Create Alert]
           TA -->|Warning| W[Create Warning]
           TA -->|Normal| N[No Action]
           C --> ES[Enrich with Suggestions]
           W --> ES
           ES --> GL[Add Grafana Links]
           GL --> RP[Add Runbook]
       end

       subgraph "Delivery Layer"
           RP --> TN[Telegram Notification]
           RP --> DB[(Store Alert)]
           RP --> WH[Webhook]
           TN --> U[User]
       end

**הסבר השכבות:**

- **Detection Layer**: זיהוי אירועים - מעקב אחר שגיאות, latency, rate limits ובריאות המערכת
- **Analysis Layer**: ניתוח הסף - האם האירוע חורג מהערכים המוגדרים
- **Decision Layer**: קבלת החלטות - יצירת התראה/אזהרה, העשרה בהמלצות וקישורים
- **Delivery Layer**: משלוח - Telegram, אחסון ב-DB, Webhook

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
- ``ANOMALY_IGNORE_ENDPOINTS`` – רשימת נתיבי URL (CSV/JSON list) שמוחרגים מעדכון ה-EWMA ומדגימת ``slow_endpoints`` (כדי למנוע false positives מנתיבים “כבדים” כמו דשבורד Observability). חשוב: המטריקות הרגילות (``http_requests_total``/``http_request_duration_seconds``) עדיין נרשמות לגרפים, אבל ההחרגה **לא** פותרת חסימת main-thread/Starvation אם קיימת.
- ``ALERT_AVG_RESPONSE_TIME_DEPLOY`` – רף חלופי (ברירת מחדל ``10.0`` שניות) שנכנס לפעולה בזמן חלון החסד אחרי Deploy. מאפשר להתעלם מפיקים לגיטימיים בלי להעלות את הרף הגלובלי.
- ``DEPLOY_GRACE_PERIOD_SECONDS`` – אורך חלון החסד אחרי Deploy (ברירת מחדל ``120`` שניות). בתוך החלון הזה האלגוריתם ישתמש ב-``ALERT_AVG_RESPONSE_TIME_DEPLOY`` במקום הרף הרגיל.

טיפים מהירים
------------
- בקבוצות עם ספייקים ידועים, העלו את ``ALERT_ANOMALY_BATCH_WINDOW_SECONDS`` ל-600–900 שניות ושמרו על ``ALERT_TELEGRAM_MIN_SEVERITY=warn``.
- אם רוצים שהמדידה תמשיך להופיע בלוגים/Slack אבל לא בטלגרם, הוסיפו ``ALERT_TELEGRAM_MIN_SEVERITY=error`` מבלי לשנות את דשבורדי Grafana.
