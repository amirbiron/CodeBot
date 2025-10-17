# Smart Observability v6 – Predictive Health & Self‑Healing

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

## Predictive Health (v6)

- קובץ: `predictive_engine.py`
- המנוע שומר חלון נגלל של מדדים: `error_rate_percent`, `latency_seconds`, `memory_usage_percent`.
- לכל מדד מבוצעת רגרסיה לינארית פשוטה על פני זמן (בדקות) לחישוב שיפוע מגמה.
- אם החיזוי מראה שעוד בתוך 15 דקות יהיה חצייה של הסף האדפטיבי/קבוע – נוצרת תחזית אירוע (Predictive Incident) ונרשמת ב-`data/predictions_log.json`.
- מופעלות פעולות מניעה (Preemptive Actions):
  - עליה בלטנציה → `cache.clear_stale()` (ניקוי עדין, נפילה ל-`clear_all` אם צריך)
  - עליה בזיכרון → `gc.collect()` + אזהרה בלוג
  - עליה ב-Error Rate → ניסיון restart מבוקר של worker יחיד (לוג בלבד בסביבת dev)
- כל פעולה נרשמת בלוג כאירוע `PREDICTIVE_ACTION_TRIGGERED`.

### ChatOps

- `/predict` – מציג תחזיות ל-3 שעות הקרובות, כולל חיווי מגמה: 🔴 עליה, 🟢 ירידה, ⚪ יציב.
- `/incidents` – נוסף סעיף "תחזיות פעילות" המציג מספר תחזיות אחרונות.

## Grafana – Predicted vs Actual Incidents

- נוספו מטריקות Prometheus:
  - `predicted_incidents_total{metric="..."}`
  - `actual_incidents_total{metric="..."}`
- הדשבורד עודכן עם גרף "Predicted vs Actual Incidents" המשווה בקצב לשעה (`increase()` על 1h).

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

## Endpoints

- `/metrics` – נתוני Prometheus
- `/alerts` (GET) – JSON של ההתראות האחרונות לצרכי ChatOps/דשבורד
- `/incidents` (GET) – JSON של היסטוריית התקלות (Incident Memory)
- `/alerts` (POST) – Webhook של Alertmanager (קיים)
 - `/predict` (ChatOps) – סיכום תחזיות וטרנדים

## טיפים

- ודאו שאין דליפת סודות בלוגים/התראות (המודול מסנן מפתחות).
- בצעו בדיקות בסביבת Staging לפני ייצור.
