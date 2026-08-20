---
summary: מסמך זה מפרט את מצב ההרחבה של הפקודה `/observe` לצורכי תחקור ומהירות תגובה בזמן אמת.
---

# ChatOps – /observe: הרחבות -v ו- -vv

- **מתי להשתמש**: כשצריך תמונת Observability עמוקה (ברמת מערכת) בזמן אמת, כולל הצלבת מקורות נתונים וזיהוי מגמות/חריגות.
- **הרשאות**: מנהלים בלבד.

## תחביר ופרמטרים

- `-v` – מצב מפורט (Verbose)
- `-vv` – מצב מפורט מאוד (Very Verbose)
- פרמטרים אופציונליים:
  - `source=db|memory|all` – מקור הנתונים לסיכומים (ברירת מחדל: `all`)
  - `window=5m|1h|24h` – חלון זמן לסיכומי התראות (ברירת מחדל: `24h`)

## דוגמאות

```text
/observe -v window=5m source=all
/observe -v source=memory
/observe -vv source=db
```

## פלט לדוגמה – ‎-v

```text
🔍 Observability – verbose
Uptime: 99.87% (source: memory)
Error Rate (5m): curr=0.12% | thr=4.85% (source: memory)
Latency (5m): curr=0.210s | thr=1.740s (source: memory)
Alerts (DB, window=5m): total=2 | critical=1
Alerts (Memory, window=5m): total=3 | critical=1; unique_critical_ids=1
Recent Errors (memory, N≤5):
- [API_002] github_rate_limit_exceeded — 2025-10-23T03:55:12+00:00
- [DB_001] db_connection_timeout — 2025-10-23T03:54:08+00:00
Cooling:
- error_rate_percent: idle
- latency_seconds: active (~120s left)
Sinks:
- telegram: 9/9 ok
- grafana: 8/9 ok
```

## פלט לדוגמה – ‎-vv

```text
🔍 Observability – very verbose
Uptime: 99.87% (source: memory)
Error Rate (5m): curr=0.20% | thr=4.60% (source: memory)
Latency (5m): curr=0.180s | thr=1.520s (source: memory)
Alerts (DB, window=24h): total=12 | critical=3
Alerts (Memory, window=24h): total=10 | critical=3; unique_critical_ids=3
Recent Errors (memory, N≤5):
- [CONN_001] Database connection timeout — 2025-10-23T02:02:31+00:00
- [API_002] GitHub rate limit exceeded — 2025-10-23T01:49:12+00:00
Cooling:
- error_rate_percent: idle
- latency_seconds: idle
Sinks:
- telegram: 5/5 ok
- grafana: 5/5 ok
Recent Alert IDs (DB, N≤10):
- id:58f3e3f8-1a62-4c34-8a90-4fb3a1a6c0a1
- id:1c2d3e4f-5a6b-7c8d-9e0f-123456789abc
- h:3a6f5e...
```

## הערות שימוש

- `-vv` מוסיף פירוט מזהי התראות אחרונות מה-DB, שימושי לטרייסינג מול מקורות חיצוניים.
- `window` קובע את חלון החישוב הסטטיסטי להתראות; נתונים תפקודיים (latency/error rate) מוצגים לפי חלון קצר (לרוב 5 דקות).
- במערכות רועשות, מומלץ להתחיל מ־`-v` ורק בעת הצורך להעמיק ל־`-vv`.

## קישורים רלוונטיים

- Issue הפקודות: [#1021](https://github.com/amirbiron/CodeBot/issues/1021)
- סקירת Observability כללית: `monitoring`
- פקודות ChatOps נוספות: `chatops/commands`
