# ניטור מתקדם (Observability v3)

מסמך זה מתאר כיצד לחבר את Grafana ו-Prometheus ל-CodeBot, ולהשתמש בנתונים מ-`/metrics` ו-`/alerts`.

## Prometheus – איסוף מדדים

- נקודת קצה: `/metrics`
- מדדים חדשים:
  - `codebot_uptime_seconds_total` (Counter): זמן ריצה מצטבר של התהליך בשניות.
  - `codebot_alerts_total{source, severity}` (Counter): מונה התראות לפי מקור (`internal`/`webhook`) וחומרה.
  - `codebot_error_rate_percent` (Gauge): שיעור שגיאות מיידי באחוזים.
- מדדים קיימים שניתן להשתמש בהם:
  - `codebot_requests_total`, `codebot_failed_requests_total`
  - `codebot_avg_response_time_seconds`, `codebot_active_users_total`

דוגמה לשאילתות PromQL:

- Error rate מחושב מקאונטרים: `(1 - rate(codebot_failed_requests_total[5m]) / clamp_min(rate(codebot_requests_total[5m]), 1)) * 100`
- Avg RT: `codebot_avg_response_time_seconds`
- Uptime %: כמו למעלה (1 - failed/total) * 100

## Grafana – דשבורד בסיסי

- קובץ הדשבורד נמצא ב-`docs/grafana_dashboard.json`.
- פאנלים:
  - Error Rate (%)
  - Avg Response Time (s)
  - Uptime (%)
  - Active Users
  - Alerts table (מקור JSON API)

### חיבור Datasources

- Prometheus: להפנות ל-URL של Prometheus (למשל `http://prometheus:9090`).
- JSON API (תוסף Simpod): להגדיר כתובת הבסיס לשרות (`/`), והשאילתה של הטבלה מצביעה ל-`/alerts`.

## נקודות קצה חדשות

- `GET /alerts` – מחזיר JSON:
  ```json
  { "alerts": [ { "ts": "2025-10-17T10:00:00Z", "name": "...", "severity": "warn", "summary": "...", "details": {"...": "..."} } ] }
  ```
  פרמטר `limit` אופציונלי (1–100).

- `GET /uptime` – מחזיר זמינות ממוצעת וזמן ריצה של התהליך:
  ```json
  { "uptime_percent": 99.9, "process_uptime_seconds": 12345.6 }
  ```

## חיבור מהיר בדוקר (אופציונלי)

בקובץ `docker-compose.yml` קיימות שירותי Prometheus ו-Grafana (מושבתים כברירת מחדל בתיעוד). יש לוודא שמפות ה-ports וה-Volumes מוגדרות לפי הסביבה שלכם.

## פרטיות וסודות

- אין לשמור או להציג נתונים רגישים ב-logs ובמדדים. ערכים רגישים עוברים השחרה.
- כל המדדים תואמים את פורמט Prometheus עם labels תקניים.
