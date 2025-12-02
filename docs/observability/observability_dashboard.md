# 📡 Observability Dashboard & API

> קישורים מהירים: [README של Code Keeper Bot](https://github.com/amirbiron/CodeBot#-קוד-שומר) · [מדריך Config Radar](https://github.com/amirbiron/CodeBot/blob/main/GUIDES/CONFIG_RADAR_GUIDE.md)

מסך ה־Admin החדש (`/admin/observability`) מרכז נתוני ניטור בזמן אמת לטובת צוותי SRE והמפתחים. העמוד מתמקד בשלושה עקרונות:

1. **שקיפות** – כרטיסי מצב וגרפים קלים לקריאה עם קונטקסט של זמן.
2. **חקירה מהירה** – טבלת התראות עם סינון מתקדם ופג'ינציה חסכונית.
3. **API מתועד** – שלושה Endpoints סימטריים שניתנים לצריכה אוטומטית ע"י Grafana, Slack או סקריפטים.

המסמך הזה מתאר את מבנה המסך, את פרטי ה־API, שיקולי אבטחה וביצועים, וכן דוגמאות אינטגרציה לצריכה חיצונית.

## 🖥️ סקירת הממשק `/admin/observability`

### חלוקת הדף

- **סרגל טווחי זמן** – לחצני `1h`, `24h`, `7d`, `30d` מחליפים את פרמטר `timerange` בבקשות API ומעדכנים את סטרימינג הגרפים.
- **כרטיסי KPI** – ארבעה קלפים קבועים: Critical ב־24 שעות, Anomaly בטווח הנוכחי, כמות דיפלוימנטים, וגודל השפעת הדיפלוימנט (ממוצע העיכוב ב־request בזמן חלון Deployment).
- **גרפים** – Chart.js מציג:
  - ריבוד התראות לפי חומרה (`alerts_count`).
  - זמני תגובה ממוצעים ומקסימליים (`response_time`).
- **טבלת נקודות קצה איטיות** – Top N (ברירת מחדל 5) עם `avg_duration`, `max_duration`, `count` ונתיב/שיטה.
- **היסטוריית התראות** – טבלה עם עד 200 רשומות אחרונות+פג'ינציה. כל שורה כוללת timestamp, שם, חומרה, סיכום ומטא־דאטה שנשלף מה־payload.

### יכולות סינון

- **חומרה** – `critical | anomaly | warning | info` (או "כל החומרות").
- **סוג התראה** – שימושי לבקרות Deployment, חריגות Error Rate וכד'.
- **Endpoint / Path** – התאמה מלאה מול `endpoint` ששמור במסד.
- **חיפוש חופשי** – מחפש ב־`name`, `summary` ו־`metadata`.
- **פג'ינציה** – `page` ו־`per_page` עם בקרה דו־כיוונית (לחצני הבא/קודם מציגים מצב העמוד הנוכחי).

### מקרא ו־UI

- **צבעי חומרה** – ורוד (Critical), צהוב (Anomaly), כחול (Warning), ירוק (Info); צבעים זהים בטאב היסטוריית ההתראות ובגרף Chart.js כדי לשמור עקביות.
- **מצב "Last updated"** – מעודכן בכל רענון מקומי כדי להדגיש גישה בזמן אמת.
- **מצב טעינה/שגיאה** – כל מקטע מציג הודעת "טוען" או הודעת שגיאה ידידותית כאשר ה־API לא זמין.

## 📚 API Reference

כל ה־Endpoints מחייבים התחברות ב־WebApp ומשתמש עם הרשאת Admin. אם משתמש רגיל ינסה להיכנס הוא יקבל `403 {"ok": false, "error": "admin_only"}`.

### פרמטרי זמן משותפים

| פרמטר | ברירת מחדל | תיאור |
| --- | --- | --- |
| `timerange` | `24h` | טווח יחסי בפורמט `Xm`, `Xh`, `Xd`. ערך `custom` דורש `start_time`+`end_time`. |
| `start_time` / `end_time` | `None` | תאריכי ISO 8601 (כולל `Z`). אם סופקו שניהם – הם גוברים על `timerange`. |
| `range` | `None` | Alias ל-`timerange` עבור תאימות למרכיבים אחרים. |

כל הטפסים בווב נשלחים עם הפרמטרים הנ"ל, כך שקריאות ידניות יתנהגו זהה ל־UI.

### `GET /api/observability/alerts`

- **מטרה:** רשימת התראות מפורטת עם סיכומים, metadata ופג'ינציה.
- **פרמטרים נוספים:**
  - `severity`, `alert_type`, `endpoint`, `search` – סינון מדויק.
  - `page` (ברירת מחדל 1) ו־`per_page` (ברירת מחדל 50, מקסימום 200).

```bash
curl -H 'Accept: application/json' \
  'https://code-keeper-webapp.onrender.com/api/observability/alerts?timerange=24h&severity=critical&page=1&per_page=25'
```

דוגמת תגובה:

```json
{
  "ok": true,
  "page": 1,
  "per_page": 25,
  "total": 87,
  "alerts": [
    {
      "timestamp": "2025-12-02T08:27:14+00:00",
      "name": "deployment_event",
      "summary": "Render deploy finished",
      "severity": "anomaly",
      "alert_type": "deployment_event",
      "endpoint": "/admin/observability",
      "duration_seconds": 42.1,
      "source": "alerts_storage",
      "silenced": false,
      "metadata": {"request_id": "5c6c...", "actor": "deploy-bot"}
    }
  ]
}
```

### `GET /api/observability/aggregations`

- **מטרה:** קבלת אגרגציות מהירות עבור הקלפים והטבלאות בפאנל.
- **פרמטרים נוספים:** `limit` (ברירת מחדל 5, בין 1 ל־20) עבור כמות נקודות הקצה האיטיות.

```bash
curl -H 'Accept: application/json' \
  'https://code-keeper-webapp.onrender.com/api/observability/aggregations?timerange=7d&limit=8'
```

```json
{
  "ok": true,
  "summary": {"total": 410, "critical": 32, "anomaly": 11, "deployment": 5},
  "top_slow_endpoints": [
    {"endpoint": "/api/snippets", "method": "POST", "avg_duration": 1.82, "max_duration": 4.91, "count": 54}
  ],
  "deployment_correlation": {
    "avg_spike_during_deployment": 1.37,
    "anomalies_not_related_to_deployment_percent": 62.5
  }
}
```

### `GET /api/observability/timeseries`

- **מטרה:** הזנת הגרפים ומשיכת טבלאות Time Series לכל Metric נתמך.
- **פרמטרים נוספים:**
  - `granularity` – דגימה בפורמט `5m`, `1h`, `6h`, `12h` (ברירת מחדל `1h`). הערך מומר אוטומטית לשניות ומוחזר בשדה `granularity_seconds`.
  - `metric` – אחד מ-`alerts_count`, `response_time`, `error_rate` (ברירת מחדל `alerts_count`).

```bash
curl -H 'Accept: application/json' \
  'https://code-keeper-webapp.onrender.com/api/observability/timeseries?timerange=30d&granularity=6h&metric=error_rate'
```

```json
{
  "ok": true,
  "metric": "error_rate",
  "granularity_seconds": 21600,
  "data": [
    {"timestamp": "2025-11-30T06:00:00+00:00", "error_rate": 2.1, "count": 1880, "errors": 40},
    {"timestamp": "2025-11-30T12:00:00+00:00", "error_rate": 0.7, "count": 1475, "errors": 10}
  ]
}
```

**הערה:** עבור `metric=response_time` האובייקטים מכילים `avg_duration`, `max_duration`, `count`. עבור `alerts_count` תוחזר חלוקה לפי חומרה (`critical`, `anomaly`, `warning`, `info`, `total`).

## 🔐 אבטחה, Rate Limiting וקאש

- **Admin only:** כל הנתיבים משתמשים ב-`@login_required` ובבדיקת `_require_admin_user`, ולכן עליכם לוודא שהמשתמש מוגדר ב־ENV `ADMIN_USER_IDS`.
- **Rate limiting:** ברירת המחדל של Flask-Limiter (`50 per hour`, `200 per day` לכל משתמש) חלה גם על ה־Endpoints הללו. חריגה תחזיר `429` עם payload סטנדרטי.
- **Caching:** שירות `services/observability_dashboard` שומר Cache in-memory (alerts – ‎120s, aggregations/timeseries – ‎150s). כך, קריאות רציפות מדפדף המריץ auto-refresh לא יעמיסו על MongoDB.
- **Fail-open:** אם MongoDB או Prometheus אינם זמינים, המערכת תחזור ל־`internal_alerts`/מדדים מחושבים כדי למנוע 500. במקרה כזה ה־payload עדיין יסומן `ok: true` וה־source יהיה `buffer`.

## 🔌 אינטגרציות ודוגמאות שימוש

### Grafana / BI

1. הוסיפו Data Source מסוג *JSON API* והגדירו Header `Cookie: session=...` (או Reverse Proxy שמחזיק סשן Admin).
2. עבור גרף stacked alerts – בצעו קריאה ל-`/api/observability/timeseries?metric=alerts_count` עם `interval` דינמי שממפה ל־`granularity`.
3. עבור טבלת נקודות קצה – השתמשו ב־`aggregations.top_slow_endpoints` והציגו `avg_duration` + `max_duration` כהתראה מהירה.

### Slack / On-call Bot

- סקריפט cron יכול למשוך כל חמש דקות את `GET /api/observability/alerts?timerange=1h&severity=critical&per_page=10` ולהזרים הודעה ל־Slack כאשר `total` גדל.
- הוסיפו קישור חזרה לדשבורד (`https://code-keeper-webapp.onrender.com/admin/observability`) כדי שמי שמקבל את ההתראה יוכל להעמיק בגרפים.

### שילוב עם Config Radar

- לפני שמערכות חיצוניות יגיבו להתראה, מומלץ לוודא שהקונפיגורציה ב־[Config Radar](https://github.com/amirbiron/CodeBot/blob/main/GUIDES/CONFIG_RADAR_GUIDE.md) מעודכנת (למשל, `immediate_categories`).
- הדשבורד מציג נתוני אמת; Config Radar נותן את הסכמות. שימוש בשניהם ביחד מאפשר לזהות האם החריגה נובעת מהגדרה חסרה או מאירוע אמיתי.

### רפרנס ל־README

- ה־README כולל סקירה על כלל יכולות האנליטיקה (סעיף "📊 ניתוח ואבחון"). מומלץ להוסיף קישור ישיר מתוך README (ע"ע עדכון PR זה) כדי שהקהילה תמצא את הדשבורד גם מחוץ לדוקס.

## ✔️ מה הלאה?

- הרחיבו את ה־API בהתאם לרשימת metric-ים חדשה (למשל, `db_cpu` או `queue_backlog`).
- אם אתם משלבים Agent חיצוני – עדיף להסתמך על ה־API המתועד כאן מאשר על scraping של HTML.
- נשמח לקבל Pull Request עם צילומי מסך או וידאו של חיבור Grafana/Slack כדי להוסיף ל־Docs.
