# 🧠 Quick Fix חכם (Queue Delay + עומס/DB) – הנחיות למפתחים ולסוכני AI

המטרה של **Quick Fix** היא לתת המלצה קצרה, בטוחה ושימושית על “מה לעשות עכשיו”, לפי אותות שאנחנו כבר מודדים.

הדגש פה הוא על הבחנה בין:

- **Queueing (תשתיתי):** הבקשה *ממתינה לפני שהאפליקציה התחילה לטפל בה* (`queue_delay`).
- **Processing איטי (אפליקטיבי):** האפליקציה כבר מטפלת, אבל לוקח לה זמן (`duration_ms`).

## איפה זה מופיע

- **WebApp**: עמודת **Quick Fix** בהיסטוריית התראות בלוח Observability (`/admin/observability`).
- **Incident Replay**: בפאנל Runbook (רק כפתורי פעולה שמוגדרים ב־Runbook).
- **Telegram (התראות קריטיות)**: שורת “Quick Fix” בתוך הודעת ההתראה (best‑effort).

## מקור אמת: איפה החוקים חיים

החוקים הדינמיים מוגדרים ב־`config/observability_runbooks.yml` תחת:

- `quick_fix_rules.latency_v1`

הפורמט מאפשר:

- **ספים** (thresholds)
- **מיפוי פעולות** (actions) לכל תרחיש

בנוסף, יש שני מקורות נוספים לפעולות:

- **Runbooks** באותו YAML (פעולות שמוגדרות בתוך צעדים)
- **תאימות לאחור**: `config/alert_quick_fixes.json`

האלגוריתם בפועל:

1. אם יש מספיק אותות → מפיק Quick Fix דינמי.
2. מוסיף פעולות Runbook (אם קיימות).
3. אם אין Runbook / אין פעולות → נופל ל־`alert_quick_fixes.json`.

## טבלת החלטה (Latency / Slow Response)

ספי ברירת מחדל (ניתנים לשינוי ב־YAML):

- `queue_delay_ms`: **500ms**
- `duration_ms`: **3000ms**

כלל־על: קודם מזהים **Queueing** ורק אם הוא תקין עוברים ל־**Processing**.

| Detection | Quick Fix | למה |
|---|---|---|
| Queueing גבוה + DB utilization גבוה | 🔌 הגדל Connection Pool / Kill Slow Queries | אין מספיק חיבורים פנויים / שאילתות חוסמות |
| Queueing גבוה + CPU/RAM גבוה | 📈 Scale Up / Add Workers | השרת בתקרת משאבים |
| Queueing גבוה + שימוש נמוך + DB utilization נמוך | 🔄 Restart Service (Stuck Workers) | חשד ל־deadlock/worker תקוע |
| Queueing נמוך + Duration גבוה | 🔍 Optimize Query / Cache | בעיית קוד/שאילתה, לא תשתית |

## אילו שדות אנחנו משתמשים בהם (סכמת נתונים)

### אותות עיקריים

- **Queue Delay**
  - `metadata.queue_delay` (ms) – מגיע מלוגי `access_logs` (Headers `X-Queue-Start`/`X-Request-Start`).
  - במקרים מסוימים קיימים גם ערכים נגזרים: `queue_delay_ms_p95` / `queue_delay_ms_avg` (best‑effort).

- **Duration**
  - `metadata.duration_ms` (ms) – זמן טיפול/בקשה.

### עומס ומשאבים

- `metadata.cpu_percent` (אחוזים, best‑effort)
- `metadata.memory_percent` (אחוזים, best‑effort)
- `metadata.active_requests` (in‑flight requests, אינדיקציה מקומית לתהליך)

> הערה: חלק מהמדדים הם “best‑effort” ויכולים להשתנות בין תהליכים/פודים. לכן הם משמשים בעיקר כדי לבחור המלצה כללית, לא כדי להסיק מסקנות חדות.

### “DB Pool utilization”

בפועל אנו משתמשים היום ב־`metadata.db_pool_utilization_pct` שמחושב מה־Mongo `serverStatus.connections` (current/available).

- זה **לא בדיוק** utilization של client pool של PyMongo.
- אבל זה עדיין אינדיקציה טובה ללחץ על DB כשיש Queueing.

## עקרונות Safety (חשוב)

- **לא להציע פעולות מסוכנות כברירת מחדל** (מחיקות/kill/rollback) בלי “caution” ובלי נתיב ברור.
- העדפה לפעולות בטוחות:
  - `copy` של פקודות ChatOps (`/triage …`, `/errors`, `/status_worker`)
  - קישורים למסכים פנימיים (Replay / Dashboard)
- אם אין מספיק נתונים → **Fallback ברור** (למשל “Scale Up” או “הרץ /triage latency”).

## איך להוסיף/לשנות חוק (צ’קליסט למפתחים ול‑AI)

1. **עדכון קונפיג**
   - הוסיפו/שנו `quick_fix_rules.latency_v1.thresholds` ו/או `actions`.

2. **בדיקת שדות קיימים**
   - ודאו שהשדות שאתם רוצים קיימים ב־alert `metadata`.
   - אם לא: הוסיפו אותם בשכבת האינסטרומנטציה (לרוב `metrics.py`/`alert_manager.py`).

3. **מימוש לוגיקה (אם נדרש)**
   - הלוגיקה הדינמית נמצאת ב־`services/observability_dashboard.py` (פונקציה `_dynamic_quick_fix_actions`).
   - אם הוספתם אות חדש – הרחיבו את ה־extract/normalize שם בצורה fail‑open.

4. **טסטים**
   - כלל אצבע: **שורה בטבלת החלטה = טסט**.
   - לכסות:
     - queueing+pool גבוה
     - queueing+cpu/ram גבוה
     - queueing+usage נמוך
     - duration גבוה (processing)
     - חסר נתונים (fallback)

5. **UI/Bot**
   - UI מצייר את `alert.quick_fixes` כמו שהוא.
   - לבוט: ההמלצה נבנית best‑effort מתוך אותו מקור.

## הערות לסוכני AI (איך לעבוד נכון)

- כשצריך מידע בזמן אמת (למשל האם באמת יש לחץ DB) **לא מנחשים**.
- מבקשים להריץ פקודות ChatOps רלוונטיות:
  - `/triage latency`
  - `/triage db`
  - `/triage system`
  - `/errors`

והפלט של הבוט הוא מקור האמת.
