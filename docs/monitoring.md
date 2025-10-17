# Smart Observability v4 – מדריך חיבורים

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

## Adaptive Thresholds (ספים דינמיים)

- המודול `alert_manager.py` שומר חלון נגלל של 3 שעות של דגימות בקשות (סטטוס/לטנציה).
- אחת ל-5 דקות מתבצע חישוב סטטיסטי:
  - `threshold = mean + 3*sigma` עבור error rate (%) ו-latency (sec).
- במקרה חריגה בחלון 5 דקות נשלחת התראה `critical` לטלגרם ולגרפנה.
- המטריקות הבאות זמינות ב-/metrics:
  - `adaptive_error_rate_threshold_percent`
  - `adaptive_latency_threshold_seconds`
  - `adaptive_current_error_rate_percent`
  - `adaptive_current_latency_avg_seconds`

## ChatOps – /observe

- פקודה חדשה בבוט מציגה:
  - Uptime (ממחלקת `metrics.get_uptime_percentage`)
  - Error Rate (5m)
  - Active Users (אומדן)
  - Alerts (24h): סך הכל, ומתוכן קריטיות

## Endpoints

- `/metrics` – נתוני Prometheus
- `/alerts` (GET) – JSON של ההתראות האחרונות לצרכי ChatOps/דשבורד
- `/alerts` (POST) – Webhook של Alertmanager (קיים)

## טיפים

- ודאו שאין דליפת סודות בלוגים/התראות (המודול מסנן מפתחות).
- בצעו בדיקות בסביבת Staging לפני ייצור.
