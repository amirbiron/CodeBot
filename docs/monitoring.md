# Smart Observability v7 – Predictive Health & Adaptive Feedback

## חיבור Grafana → Telegram (Webhook)

- בחרו Channel/Chat לקבלת התראות.
- הגדירו ב-ENV:
  - `ALERT_TELEGRAM_BOT_TOKEN`
  - `ALERT_TELEGRAM_CHAT_ID`
- מערכת ההתראות תשלח הודעות קריטיות ישירות לטלגרם דרך `alert_manager.py`.

## Grafana Annotations

- הגדירו ב-ENV:
  - `GRAFANA_URL` (למשל: https://grafana.example.com)
  - `GRAFANA_API_TOKEN` (Bearer Token עם הרשאות כתיבה ל-Annotations)
- בעת התראה קריטית נשלחת גם Annotation ל-`/api/annotations` עם טקסט: `<name>: <summary>`.
- בעת Auto‑Remediation מתווסף Annotation נוסף עם הפעולה שבוצעה.

## Adaptive Thresholds (ספים דינמיים)

- המודול `alert_manager.py` שומר חלון נגלל של 3 שעות של דגימות בקשות (סטטוס/לטנציה).
- אחת ל-5 דקות מתבצע חישוב סטטיסטי:
  - `threshold = mean + 3*sigma` עבור error rate (%) ו-latency (sec).
- במקרה חריגה בחלון 5 דקות נשלחת התראה `critical` לטלגרם ולגרפנה, ונקרא מנגנון Auto‑Remediation.
- המטריקות הבאות זמינות ב-/metrics:
  - `adaptive_error_rate_threshold_percent`
  - `adaptive_latency_threshold_seconds`
  - `adaptive_current_error_rate_percent`
  - `adaptive_current_latency_avg_seconds`

## Predictive Health (v7)

- קובץ: `predictive_engine.py`
- המנוע שומר חלון נגלל של מדדים: `error_rate_percent`, `latency_seconds`, `memory_usage_percent`.
- חיזוי מבוסס Exponential Smoothing (משוקלל אקספוננציאלית), עם נפילה לרגרסיה לינארית במקרה הצורך.
- לולאת Feedback אדפטיבית: השוואת תחזיות לאירועים בפועל והטמעת הדיוק חזרה למודל (טיונינג של halflife).
- אם החיזוי מראה שעוד בתוך 15 דקות יהיה חצייה של הסף האדפטיבי/קבוע – נוצרת תחזית אירוע (Predictive Incident) ונרשמת ב-`data/predictions_log.json`.
- מופעלות פעולות מניעה (Preemptive Actions):
  - עליה בלטנציה → `cache.clear_stale()` (ניקוי עדין, נפילה ל-`clear_all` אם צריך)
  - עליה בזיכרון → `gc.collect()` + אזהרה בלוג
  - עליה ב-Error Rate → ניסיון restart מבוקר של worker יחיד (לוג בלבד בסביבת dev)
- כל פעולה נרשמת בלוג כאירוע `PREDICTIVE_ACTION_TRIGGERED`.
- ניקוי אוטומטי: תחזיות ישנות (מעל 24 שעות) נמחקות באופן אוטומטי מקובץ `predictions_log.json`.

### SAFE_MODE ודילוג על פעולות מנע

- כאשר `SAFE_MODE=1` או `DISABLE_PREEMPTIVE_ACTIONS=1` — פעולות המנע לא ירוצו, ויירשם אירוע `PREDICTIVE_ACTION_SKIPPED`.
- ניקוי הקאש (`clear_stale`/`clear_all`) מוגבל בתקציב זמן (`CACHE_CLEAR_BUDGET_SECONDS`) כדי למנוע תקיעות במקרה ש-Redis אינו מגיב.

### ChatOps

- `/predict` – מציג תחזיות ל-3 שעות הקרובות, כולל חיווי מגמה: 🔴 עליה, 🟢 ירידה, ⚪ יציב.
- `/incidents` – נוסף סעיף "תחזיות פעילות" המציג מספר תחזיות אחרונות.
- `/accuracy` – מציג דיוק חיזוי נוכחי (%) ומספר אירועים שנמנעו (הערכה).
- `/observe -v` – תצוגה מפורטת של Observability בזמן אמת, עם:
  - Uptime/Error Rate/Latency + ספים אדפטיביים (memory)
  - Alerts (DB/memory) לפי חלון `window=5m|1h|24h`, כולל de-dup מול Dispatch Log
  - Recent Errors (N<=5)
  - Cooling & Health (cooldown פעיל וסטטוס sinks)
- `/observe -vv` – כולל גם רשימת N=10 מזהי התראות האחרונות מה-DB.

### הרשאות ChatOps ו-Rate Limit

- פקודות רגישות (למשל: `/errors`, `/triage`, `/rate_limit`, `/enable_backoff`, `/disable_backoff`) מוגבלות למנהלים בלבד.
- הגדירו אדמינים דרך ENV: `ADMIN_USER_IDS="123,456"`.
- ניתן להגביל הפעלה לצ'אטים ספציפיים דרך ENV: `ALLOWED_CHAT_IDS="-100123,-100456"`.
- Rate-limit עדין לפקודות רגישות: קירור ברירת מחדל 5 שניות בין הפעלות לאותו משתמש. ניתן לשינוי דרך `SENSITIVE_COMMAND_COOLDOWN_SEC`.

### Grafana – ייבוא דשבורד לדוגמה

- קובץ דשבורד לדוגמה קיים ב-`docs/grafana_dashboard.json`.
- ייבוא ל-Grafana: Dashboards → Import → העלו את הקובץ ובחרו מקור נתונים Prometheus.

## Grafana – Accuracy & Prevention Panels

- מטריקות Prometheus:
  - `predicted_incidents_total{metric="..."}`
  - `actual_incidents_total{metric="..."}`
  - `prediction_accuracy_percent` (Gauge) – מציג את דיוק החיזוי ב-% לחלון אחרון (~24h)
  - `prevented_incidents_total{metric="..."}` – סך הערכות לאירועים שנמנעו בעקבות פעולות מניעה
- פאנלים מומלצים ב-Grafana:
  - "Prediction Accuracy (%)" – SingleStat/Gauge על `prediction_accuracy_percent`
  - "Prevented Incidents Timeline" – גרף קצב לפי שעה: `increase(prevented_incidents_total[1h])`
  - "Predicted vs Actual Incidents" – השוואה בקצב: `increase(predicted_incidents_total[1h])` מול `increase(actual_incidents_total[1h])`

### תרשים זרימת Feedback Loop

```
Samples (status, latency) → Adaptive Thresholds (mean+3σ)
         ↓                              ↑
   Sliding Windows                Thresholds Snapshot
         ↓                              │
 Exponential Smoothing  ─────►  Prediction (horizon)
         │                              │
         ├─► Preemptive Actions         │
         │                              │
      Predictions Log ──────►  Compare with Incidents (24h)
                                   │
                                   ├─► Update Accuracy Gauge
                                   └─► Tune Halflife (↑ when noisy, ↓ when misses)
```

## Auto‑Remediation (v5)

- קובץ: `remediation_manager.py`
- בהתראה קריטית המערכת:
  - מתעדת אירוע ל־`data/incidents_log.json` (JSON Lines)
  - מפעילה פעולה בהתאם לסוג:
    - High Error Rate → ניסיון restart לשירות (רישום בלבד בסביבה זו)
    - High Latency → ניקוי cache פנימי
    - DB Connection Errors → ניסיון פתיחה מחודשת ל‑MongoDB
  - כותבת `AUTO_REMEDIATION_EXECUTED` ללוג עם `incident_id`
  - מוסיפה Grafana Annotation עם פירוט הפעולה

### Incident Memory

- היסטוריה נשמרת ב־`data/incidents_log.json`.
- ממשקי צפייה:
  - ChatOps: `/incidents` – מציג 5 תקלות אחרונות
  - API: `GET /incidents` – מחזיר JSON של היסטוריית אירועים (limit)

### Feedback Loop לאירועים חוזרים

- אם אותה בעיה חוזרת תוך פחות מ־15 דקות:
  - מעלה את הסף האדפטיבי פי `1.2`
  - מסמן `recurring_issue: true` בלוג

## ChatOps – /observe

- פקודה חדשה בבוט מציגה:
  - Uptime (ממחלקת `metrics.get_uptime_percentage`)
  - Error Rate (5m)
  - Active Users (אומדן)
  - Alerts (24h): סך הכל, ומתוכן קריטיות

### הרחבות מצב מפורט

- `-v` – הרחבה כולל מקורות והצלבת נתונים (DB/Memory), חלון `window`, וסיכומי sinks.
- `-vv` – מוסיף 10 מזהי התראות אחרונות מה-DB (אם זמין).

## Endpoints

- `/metrics` – נתוני Prometheus
- `/alerts` (GET) – JSON של ההתראות האחרונות לצרכי ChatOps/דשבורד
- `/incidents` (GET) – JSON של היסטוריית התקלות (Incident Memory)
- `/alerts` (POST) – Webhook של Alertmanager (קיים)
 - `/predict` (ChatOps) – סיכום תחזיות וטרנדים

## קישורים לתיעוד ChatOps

- ראו את פרק ChatOps המלא:
  - [ChatOps – סקירה כללית](chatops/overview)
  - [פקודות ChatOps](chatops/commands)
  - [Playbooks](chatops/playbooks)
  - [הרשאות ו-Rate Limit](chatops/permissions)
  - [פתרון תקלות](chatops/troubleshooting)
  - [שאלות נפוצות](chatops/faq)

## טיפים

- ודאו שאין דליפת סודות בלוגים/התראות (המודול מסנן מפתחות).
- בצעו בדיקות בסביבת Staging לפני ייצור.
