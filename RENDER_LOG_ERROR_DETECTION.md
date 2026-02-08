## זיהוי שגיאות בלוגים של Render – הצעה פרקטית

### מטרות
- לזהות שגיאות ו"רמזים לשגיאות" בלוגים של Render בזמן-כמעט-אמת
- לצמצם רעש (false positives) ולהעלות פעולה ישימה (actionable) לכל התרעה
- לאפשר חיפוש, סינון וטריאג' מהיר מתוך CLI/ChatOps

### לוגים – פורמט מומלץ (מובנה/JSON)
העדיפו JSON מובנה עם השדות הבאים:
- `ts` (ISO8601), `level` (debug|info|warn|error|fatal)
- `service`, `region`, `instanceId`
- `requestId`/`traceId`, `route`, `method`, `status`, `latencyMs`
- `message`, `errorCode`, `stack`
- `dependency` (db|redis|github|telegram|http), `target` (hostname/uri)
- `sample` (true/false) – לדגימה בקצבים גבוהים

דוגמה לשורה:
```json
{"ts":"2025-10-30T10:10:10Z","level":"error","service":"doc-bot","requestId":"r-123","route":"/webhook","status":500,"latencyMs":812,"message":"DB timeout","dependency":"db","target":"postgres:5432","errorCode":"DB_TIMEOUT","stack":"..."}
```

### חתימות ודפוסים לזיהוי שגיאות ב-Render
להלן רשימת דפוסים (regex) יעילים לניתור בלוגים גולמיים (stdout/stderr):
- קריסות/יציאות תהליך: `(OOMKilled|Out of memory|SIGKILL|SIGTERM|Exited with code \d+)`
- Python: `Traceback \(most recent call last\):|ModuleNotFoundError|KeyError:|ValueError:|TimeoutError`
- Node/JS: `(UnhandledPromiseRejection|TypeError:|ReferenceError:|SyntaxError:|ENOMEM|EADDRINUSE|ECONNRESET|ETIMEDOUT|socket hang up)`
- HTTP/שרת: `5\d\d(\s|$)|HTTP 50\d|upstream timed out|Gateway Timeout|Bad Gateway`
- DB/קבצים: `(SQLITE_BUSY|deadlock|could not obtain lock|Too many open files|ENOSPC|No space left on device)`
- רשת/DNS/TLS: `(EAI_AGAIN|DNS|certificate verify failed|SSL routines|x509: .* expired)`
- אפליקציות Python נפוצות: `(gunicorn\[.*\] .* worker timeout|uvicorn.error|fastapi.exception_handlers)`
- קונטיינר/תשתית: `(memory limit exceeded|Back-off restarting failed container)`

המלצה: נהלו allowlist של דפוסים "ידועים-רועשים" לסינון (למשל שגיאות לקוח 499/400 ללא השפעה), עם TTL קצר כדי לא להסתיר תקלות אמיתיות.

### שאילתות/חיפושים מהירים
- Tail מקומי דרך ייצוא/Streaming: `render logs --service <name> --since 1h` והזנת הפלט ל-ripgrep
```bash
render logs --service $SERVICE --since 1h | rg -n "(error|fatal|Traceback|UnhandledPromiseRejection|5\\d\\d)"
```
- סינון לפי מזהה בקשה: `rg -n "requestId=R123"`
- חיתוך לפי אינסטנס: `rg -n "instanceId=inst-"`

אם יש Log Drain ליעד חיצוני (Datadog/Logtail/Elasticsearch):
- הגדירו Saved Queries: "Error Spike", "Crash Loop", "Dependency Timeout", "TLS/DNS Errors"
- הוסיפו פקדי threshold וחוקי rate (לדוגמה: >20 שגיאות 5xx/דקה מאותו `route`)

### כללי התראה (Rules) מומלצים
- ספייק שגיאות 5xx: `rate(5xx_per_minute) > baseline*3 AND count > 20`
- Crash loop: `>= 3 Exited with code != 0 ב-5 דקות`
- DB/Redis timeout: `>= 5 מופעים/דקה לשדה dependency=db|redis`
- TLS/DNS: כל הופעה ראשונה ביום לכל `target` → התראה בדרגת Warn
- OOM/משאבים: כל `Out of memory|Too many open files|ENOSPC` → דרגת High

### מנגנון הורדת רעש
- דה-דופליקציה: קבצו לפי (`errorCode`||canonical regex) + `route` + `target` בפרק זמן של 1–5 דק'
- סף מינימלי: אל תתריעו על פחות מ-`N=3` מופעים, אלא אם הסיווג High (OOM/TLS)
- דגימה: בלוגים בעומס גבוה – `sample=true` עם יחס 1:10 לאירועי info

### שיפורי לוגים באפליקציה לסיוע בזיהוי
- הוספת `requestId`/`traceId` עקבי בכל ספריות ה-HTTP/DB
- מיפוי רמות: הימנעו מ-console.log ל-errors; השתמשו ב-`logger.error` עם `errorCode`
- Prefix אחיד ל-service: `service=doc-bot` כדי להפריד מיקרו-שירותים
- השחרת נתונים רגישים אוטומטית (PII, טוקנים) לפני הדפסה

### אינטגרציות
- Sentry: קונפיגורציית SDK עם breadcrumbs מהלוגים ו-`fingerprint` מותאם (route+errorCode)
- OpenTelemetry: יצוא traces ל-OTel collector, צימוד לוגים→traceId
- ChatOps: פקודות
  - `/errors render 15m` – סיכום דפוסים ונתיבים מובילים
  - `/logs render grep <regex>` – חיפוש ממוקד בזמן אמת
  - `/errors explain <requestId>` – תמצית אירועים סביב הבקשה

### פלייבוק טריאג' מהיר
1) האם יש ספייק 5xx/Crash? אם כן → בדקו דיפלוימנט אחרון/תלויות
2) האם הדפוס תלוי בתלות (db/redis/http)? אם כן → בדקו זמני תגובה/timeouts
3) OOM/קבצים/דיסק: אשרו משאבים/קונפיג קונטיינר
4) TLS/DNS: תוקף תעודה, רזולוציית DNS, תלות חיצונית
5) כוונון ספים/פילטרים אם רעש לא ישים

### מדדים להערכת איכות הזיהוי
- Precision של התראות (יעד ≥ 0.8)
- זמן גילוי ממוצע (MTTD) – יעד < 2 דקות
- כיסוי חתימות קריטיות (OOM/TLS/DB) ≥ 95%
- ירידה ב"התראות ללא פעולה" ≥ 40%

### דוגמה לרשימת Regex ניתנת לתחזוקה
```yaml
critical:
  - "Out of memory|OOMKilled|memory limit exceeded"
  - "Too many open files|ENFILE|EMFILE"
  - "No space left on device|ENOSPC"
  - "certificate verify failed|x509: .* expired"
  - "Exited with code (?!0)\\d+"
network_db:
  - "ECONNRESET|ETIMEDOUT|EAI_AGAIN|socket hang up"
  - "SQLITE_BUSY|deadlock|could not obtain lock"
app_runtime:
  - "Traceback \\(|UnhandledPromiseRejection|TypeError:|ReferenceError:|gunicorn.*worker timeout|uvicorn.error"
noise_allowlist:
  - "client disconnected|Broken pipe|499|context canceled"
```

### יישום ב-Render
- השתמשו ב-`render logs --service ...` ל-PoC מקומי; לטווח ארוך, הגדירו Log Drain לספק observability
- בחרו יעד (Datadog/ELK/Logtail) לפי זמינות ארגונית והקימו Dashboards + Alerts
- תעדו Saved Queries ושתפו קישורים בפלייבוק

### פרטיות ואבטחה
- השחרת טוקנים ו-PII בלוגים, כולל URL query strings
- המנעו מהדפסת תוכן בקשות/תגובות מלא אלא אם דגום/מצונזר

### Roadmap קצר (2–3 שבועות)
- שבוע 1: פורמט JSON + requestId + Log Drain + Saved Queries
- שבוע 2: חבילת Regex + התראות בסיסיות + ChatOps `/errors render`
- שבוע 3: דה-דופליקציה, fine-tuning ספים, Dashboards (5xx, OOM, TLS, DB)
