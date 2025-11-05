# פקודות ChatOps

להלן מבנה אחיד לכל פקודה: מתי להשתמש, פרמטרים, הרשאות, מה לחפש בפלט, ודוגמה.

## /status
- מתי להשתמש: כשצריך תמונת מצב מהירה של השירות.
- פרמטרים: ללא (אופציונלי: `service=<name>`)
- הרשאות: כולם
- מה לחפש בפלט: מצב כללי (OK/DEGRADED), p95, וקצב שגיאות
- דוגמה:
```
/status
OK | p95: 320ms | errors: 0.2% | request_id: 2f3a...
```

## /errors
- מתי להשתמש: לקבלת שגיאות פעילות אחרונות.
- פרמטרים: אופציונלי `since=<minutes>`
- הרשאות: מנהלים בלבד
- מה לחפש בפלט: קוד/מסר שגיאה חוזרים, request_id

## /triage
- מתי להשתמש: תחקור מהיר של תקלה פעילה.
- פרמטרים: `request_id=<id>` אופציונלי
- הרשאות: מנהלים בלבד
- מה לחפש בפלט: סיבת שורש משוערת וצעדי המשך

## /predict
- מתי להשתמש: כשצריך תחזית אירועים/חריגות ב-3 שעות הקרובות.
- פרמטרים: ללא
- הרשאות: כולם
- מה לחפש בפלט: מגמת לטנציה/שגיאות (🔴/🟢/⚪) והתרעות צפויות

## /observe -v (מפורט)
- מתי להשתמש: כשצריך תמונת מצב מפורטת בזמן אמת.
- פרמטרים: אופציונליים `source=db|memory|all` (ברירת מחדל: all), `window=5m|1h|24h` (ברירת מחדל: 24h)
- הרשאות: מנהלים בלבד
- מה לחפש בפלט:
  - Uptime/Error Rate/Latency – כולל ציון מקור הנתונים (memory) והספים האדפטיביים
  - Alerts (DB) – סך הכל ו-Critical לפי חלון הזמן, עם ציון מקור
  - Alerts (Memory) – ספירה מה-buffer הפנימי והשוואה ל-Dispatch Log לצורך de-dup
  - Recent Errors – רשימה קצרה של שגיאות אחרונות (מזיכרון)
  - Cooling & Health – מצב cooldown להתראות ומצב משלוח ל-sinks (Telegram/Grafana)
- דוגמאות:
```
/observe -v window=5m source=all
/observe -v source=memory
```

**פלט לדוגמה:**
```
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

## /observe -vv (מפורט מאוד)
- מתי להשתמש: כשצריך לזהות מזהי התראות אחרונות מה-DB לצורך מעקב/חקירה.
- פרמטרים: כמו `-v`.
- הרשאות: מנהלים בלבד
- מה לחפש בפלט: בנוסף לכל הנ"ל, יוצגו N=10 מזהי התראות אחרונות מה-DB.
- דוגמה:
```
/observe -vv source=db
```

**פלט לדוגמה:**
```
🔍 Observability – verbose
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

## /rate_limit
- מתי להשתמש: בדיקת ועידכון מגבלות קצב.
- פרמטרים: ללא
- הרשאות: מנהלים בלבד
- מה לחפש בפלט: מצב נוכחי והמלצות דילול

## /dm
- מתי להשתמש: שליחת הודעה פרטית למשתמש בודד (למשל להודיע על סטטוס ״פרימיום 💎״)
- פרמטרים: `<user_id|@username> <message...>`
- הרשאות: מנהלים בלבד (`ADMIN_USER_IDS`)
- התנהגות: ההודעה נשלחת ב‑HTML עם עטיפת `<pre>` כדי לשמר רווחים ושורות
- דוגמאות:
```
/dm 123456789 היי! עשיתי בדיקה קטנה בשרת וגיליתי שאתה המשתמש הכי פעיל לאחרונה.
אז הוספתי לך סטטוס “משתמש פרימיום 💎” 🙂

מה זה נותן?
• אפשרות לבקש פריוולגיות מיוחדות לפי הצורך

אם יש משהו שבא לך שנוסיף - תרגיש חופשי לכתוב לי.
תודה שאתה משתמש בבוט באופן קבוע 🙌
```
או לפי שם משתמש:
```
/dm @someuser היי! נוספה לך גישה לפרימיום 💎
```
‑ הפקודה מחזירה משוב הצלחה/כישלון למנהל; במקרה של חסימה ע״י המשתמש – יסומן `blocked` במסד.
