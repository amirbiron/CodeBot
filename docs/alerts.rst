התראות (Alerts)
================

סקירה מהירה
-----------

- ``docker/prometheus/prometheus.yml`` מחבר את Prometheus לקובץ החוקים ואל Alertmanager.
- ``docker/prometheus/alerts.yml`` שומר את חוקי ברירת המחדל שלנו.
- ``docker/alertmanager/alertmanager.yml`` מטפל במסלולי המסירה (webhook, Slack וכו').

חוקי ברירת המחדל
-----------------

החוקים המוגדרים כרגע מכסים שגיאות, זמני תגובה ועמידה ב-SLO:

.. code-block:: yaml

   groups:
     - name: codebot_alerts
       rules:
         - alert: HighErrorRate
           expr: rate(errors_total[5m]) > 0.05
           for: 5m
           labels:
             severity: warning
           annotations:
             summary: "שיעור שגיאות גבוה (>5% בדקה)"

         - alert: SlowOperationsP95
           expr: (histogram_quantile(0.95, rate(operation_latency_seconds_bucket[5m])) > 2) and on(job, instance) (time() - process_start_time_seconds > 300)
           for: 10m
           labels:
             severity: warning
           annotations:
             summary: "פעולות איטיות: P95 > 2 שניות"

         - alert: SLOAvailabilityBreach
           expr: |
             (
               sum(rate(http_requests_total{status!~"5.."}[5m]))
               /
               sum(rate(http_requests_total[5m]))
             ) < 0.999
           for: 1h
           labels:
             severity: warning
           annotations:
             summary: "ירידה בזמינות (SLO 99.9%)"

         - alert: SLOLatencyP95Breach
           expr: |
             (
               histogram_quantile(
                 0.95,
                 sum by (job, instance, le) (rate(http_request_duration_seconds_bucket{endpoint!~"(metrics|health|static.*|favicon.*)"}[5m]))
               ) > 1.5
             )
             and on(job, instance) (time() - process_start_time_seconds > 300)
           for: 15m
           labels:
             severity: warning
             component: webapp
           annotations:
             summary: "זמן תגובה גבוה ב-P95 מעל 1.5 שניות (מתמשך)"

         - alert: SLOLatencyP95Critical
           expr: |
             (
               histogram_quantile(
                 0.95,
                 sum by (job, instance, le) (rate(http_request_duration_seconds_bucket{endpoint!~"(metrics|health|static.*|favicon.*)"}[5m]))
               ) > 3
             )
             and on(job, instance) (time() - process_start_time_seconds > 300)
           for: 30m
           labels:
             severity: critical
             component: webapp
           annotations:
             summary: "קריטי: זמן תגובה P95 מעל 3 שניות לאורך זמן"

התאמה לצרכים שלך
-----------------

- מטריקות: ודא שהשירות חושף ``errors_total`` ו-``http_request_duration_seconds_bucket``. אם השם שונה, עדכן את הביטוי.
- ספים: 5% שגיאות או 0.5 שניות P95 אולי לא מתאימים. החלף את המספרים למה שאתה מצפה בפועל.
- תוויות: הוסף ``team``, ``service`` או ``environment`` כדי לסנן טוב יותר ב-Alertmanager.

מדדי Health ו-Startup ל-Prometheus
-----------------------------------

התאמת ``/healthz`` ל-Prometheus מאפשרת לנו לסמן חריגות בזמן אמת ובעזרת טרנדים היסטוריים. החוקים הבאים מתווספים ל-``docker/prometheus/alerts.yml`` ומשתמשים ב-``offset`` ו-``predict_linear`` כדי להשוות מול בסיס יציב:

.. code-block:: yaml

   - alert: SlowMongoConnection
     expr: (min_over_time(health_ping_ms[5m]) > 100) and on(job, instance) (time() - process_start_time_seconds > 300)
     for: 0m
     labels:
       severity: warning
       component: mongo
     annotations:
       summary: "זמן פינג למונגו חוצה 100ms"

   - alert: MongoLatencyRegressionVsBaseline
     expr: |
       (
         avg_over_time(health_ping_ms[30m] offset 6h) > 0
       )
       and
       (
         avg_over_time(health_ping_ms[30m])
           > avg_over_time(health_ping_ms[30m] offset 6h) * 1.5
       )
       and on(job, instance) (time() - process_start_time_seconds > 300)
     for: 10m
     labels:
       severity: warning
       component: mongo
     annotations:
       summary: "הממוצע הנוכחי גבוה ב־50% מה-baseline שלפני 6 שעות"

   - alert: MongoLatencyPredictiveSpike
     expr: (predict_linear(health_ping_ms[1h], 10m) > 120) and on(job, instance) (time() - process_start_time_seconds > 300)
     for: 0m
     labels:
       severity: critical
       component: mongo
     annotations:
       summary: "חיזוי: פינג למונגו יעלה מעל 120ms"

   - alert: MongoDisconnected
     expr: health_mongo_status == 0
     for: 2m
     labels:
       severity: critical
       component: mongo
     annotations:
       summary: "מונגו לא זמין"

   - alert: AppLatencyEWMARegression
     expr: |
       (
         health_latency_ewma
           > predict_linear(health_latency_ewma[2h], 15m) * 1.2
       )
       and on(job, instance) (time() - process_start_time_seconds > 300)
     for: 10m
     labels:
       severity: warning
       component: webapp
     annotations:
       summary: "EWMA של האפליקציה מזנקת ביחס לטרנד"

החוקים עם ``offset`` משווים בין חצי שעה אחרונה לבין אותו חלון בדיוק שש שעות אחורה, כדי לזהות סטיה ביחס לשגרה היומית. הוספנו תנאי בסיס שדורש שה-baseline יהיה גדול מאפס כדי למנוע false positives אחרי חזרה מתקלה שבה ה-ping הוחזק כ-0. החוקים המבוססים על ``predict_linear`` נותנים heads-up לפני שהערך באמת חוצה את הסף ולכן מקבלים ``severity`` גבוה יותר ו-``for`` קצר לצמצום זמן התגובה. בנוסף הוספנו "תקופת חסד" של 5 דקות אחרי עליית התהליך (``time() - process_start_time_seconds > 300``) כדי למנוע התראות שווא בזמן cold start אחרי דיפלוי.

קונפיגורציית ``alert_manager`` באפליקציה
-----------------------------------------

הקוד של הבוט מחשב ספים אדפטיביים ומחליט האם להדליק התראה לפי הנתונים שנאגרו בחלון של 5 דקות. ניתן לכייל את ההתנהגות בלי לשנות קוד בעזרת משתני סביבה:

- ``ALERT_COOLDOWN_SEC`` – כמה זמן חייב לעבור בין שתי התראות מאותו סוג (ברירת מחדל: 300 שניות).
- ``ALERT_THRESHOLD_SCALE`` – פקטור כללי להרחבת "טווח הנורמה". אפשר גם להגדיר ``ALERT_ERROR_THRESHOLD_SCALE`` או ``ALERT_LATENCY_THRESHOLD_SCALE`` כדי לשלוט בכל מדד בנפרד. לדוגמה, ערך ``2`` יכפיל את הסף שמחושב מאליו.
- ``ALERT_MIN_SAMPLE_COUNT`` – כמה דגימות מינימליות חייבות להיות בחלון טרם נשלחת התראה (ברירת מחדל: 15). ניתן לחדד עם ``ALERT_ERROR_MIN_SAMPLE_COUNT`` או ``ALERT_LATENCY_MIN_SAMPLE_COUNT``.

מומלץ להתחיל מהברירות מחדל ולהעלות את הערכים רק אם אתם חווים רעש. אפשר לשלב בין הגדלת מספר הדגימות המינימלי לבין הרחבת הסף כדי לתת לבוט "להירגע" בספייקים קצרים.

טעינת שינויים
--------------

אחרי עריכה של ``alerts.yml`` או ``prometheus.yml``:

1. הרץ ``docker compose up -d prometheus alertmanager`` כדי לטעון את הקבצים מחדש.
2. לחלופין, ``docker compose exec prometheus kill -HUP 1`` יבקש reload בלי עצירה מלאה.
3. בדוק שהכול תקין עם ``docker compose exec prometheus promtool check rules /etc/prometheus/alerts.yml``.

בדיקת הזרימה בקצה השני
------------------------

- Alertmanager שולח כרגע ל-webhook בכתובת ``http://code-keeper-bot:8000/alertmanager/webhook``. ודא שהיעד נקרא כמו שצריך.
- להוספת Slack או יעד נוסף, ערוך את ``docker/alertmanager/alertmanager.yml`` והפעל את ``slack_configs`` עם הסוד המתאים.
- השתמש ב-``amtool`` (אם מותקן) או בממשק ה-Web של Alertmanager כדי לוודא שההתראות מתקבלות.

טיפים אחרונים
--------------

- אם תוסיף הרבה חוקים, שקול לפצל אותם לקבצים שונים ולעדכן את ``rule_files``.
- עבור כל חוק, כתוב ``summary`` קצר וברור – זה הטקסט שמופיע בהתראה.
- אפשר להוסיף ``promtool test rules`` עם דוגמאות של מטריקות כדי לתפוס שגיאות לוגיקה מראש.

ראו גם
-------

- :doc:`observability/log_based_alerts`

התראות מערכת – דיסק כמעט מלא
-------------------------------

בנוסף לחוקי Prometheus, הבוט מפעיל התרעת מערכת פנימית לפני שמירת קובצי ZIP כאשר המקום הפנוי בדיסק נמוך מהסף.

- שם אירוע: ``disk_low_space`` (נרשם גם ב‑observability)
- ערוץ: Internal Alerts (Telegram/Slack אם מוגדרים ``ALERT_TELEGRAM_*``)
- DM למנהלים: אם מוגדרים ``BOT_TOKEN`` ו‑``ADMIN_USER_IDS`` — נשלחת הודעה פרטית לכל אדמין
- סף ברירת מחדל: 200MB; ניתן לשנות בעזרת ``BACKUPS_DISK_MIN_FREE_BYTES``
- Rate‑limit: התרעה אחת לכל 10 דקות כדי למנוע הצפה

ראו גם בטבלת ENV: ``BACKUPS_DISK_MIN_FREE_BYTES``.
