# 🧠 Observability AI Explain API

שירות זה מספק שכבת AI רשמית שמתרגמת הקשרי התראות (Context) להסבר קצר בשפה טבעית, כולל שורש הבעיה, פעולות מומלצות ואותות תומכים. השירות נפרס כחלק מה־`webserver` (AioHTTP) תחת הנתיב `POST /api/ai/explain` ומשמש את לוח ה-Observability דרך המשתנה `OBS_AI_EXPLAIN_URL`.

> **TL;DR:** הלקוח שולח `context` מסונן → השירות מפעיל את Claude Sonnet → מחזיר JSON תקין בלבד. במקרה של כשל, הלקוח חוזר לפתרון ההיוריסטי הקיים.

---

## 🔐 אימות ובקרות

- **כותרת חובה (אם הוגדר טוקן):** `Authorization: Bearer ${OBS_AI_EXPLAIN_TOKEN}`
- **Timeout שרת:** `OBS_AI_EXPLAIN_TIMEOUT` (ברירת מחדל 10 שניות, גבול SLA 8–10 שניות)
- **PII Masking:** ההקשר כבר מסונן בצד ה־Dashboard, אך השירות מבצע Masking נוסף (סיסמאות, טוקנים, מזהים ארוכים).
- **ניטור:** `emit_event("ai_explain_request_success|failure", …)` כולל `duration_ms`, `alert_uid`, `provider`.

---

## 📥 בקשה (`POST /api/ai/explain`)

```json
{
  "context": {
    "alert_uid": "12345-abcde",
    "alert_name": "High Latency on /checkout",
    "severity": "critical",
    "summary": "Response time > 3s for 5m",
    "timestamp": "2025-12-07T09:30:00Z",
    "endpoint": "/api/checkout",
    "metadata": {
      "region": "us-east-1",
      "log_excerpt": "Error: Connection timeout..."
    },
    "auto_actions": [],
    "quick_fixes": [],
    "graph": {
      "metric": "latency",
      "spike_value": 5000
    }
  },
  "expected_sections": ["root_cause", "actions", "signals"]
}
```

- `context` – אובייקט חובה. כל ערך שאינו מילון יגרור `400`.
- `expected_sections` – אופציונלי. כיום נתמכים `root_cause`, `actions`, `signals`. שדות לא מוכרים מתעלמים.

---

## 📤 תגובה מוצלחת (`200 OK`)

```json
{
  "alert_uid": "12345-abcde",
  "alert_name": "High Latency on /checkout",
  "severity": "critical",
  "root_cause": "נראה שהעומס נובע מנעילות בבסיס הנתונים לאחר deploy ב-09:25.",
  "actions": [
    "בדוק שאילתות ארוכות ב-RDS סביב 09:25.",
    "שקול Rollback לגרסה האחרונה אם בוצעה מיגרציה."
  ],
  "signals": [
    "latency spike במקביל לעלייה ב-error logs",
    "חריגה של 3 שניות לאורך 5 דקות"
  ],
  "provider": "claude-sonnet-4.5",
  "model": "claude-3-5-sonnet-20241022",
  "generated_at": "2025-12-07T09:32:11Z",
  "cached": false
}
```

תמיד יוחזר JSON תקין. אם Claude החזיר ערכים חסרים, השירות ממלא fallback מבוסס הקשר (אותן פונקציות היוריסטיות מהדשבורד).

---

## ❗ קודי שגיאה

| סטטוס | `error`                        | מתי זה קורה?                                      | טיפול מומלץ |
|-------|--------------------------------|----------------------------------------------------|-------------|
| 400   | `bad_request` / `invalid_context` | גוף לא חוקי או `context` שאינו אובייקט            | תקן את הקריאה מצד הלקוח |
| 401   | `unauthorized`                 | חסר/שגוי `Authorization` כשהטוקן מוגדר              | ודא ש-`OBS_AI_EXPLAIN_TOKEN` מסונכרן בין הלקוח לשרת |
| 502   | `provider_error`               | Claude החזיר שגיאה או JSON שבור                     | הלקוח ייפול ל־fallback |
| 503   | `anthropic_api_key_missing`    | חסר `ANTHROPIC_API_KEY` בצד השירות                  | השלם הגדרה/Secret |
| 504   | `timeout`                      | הבקשה חרגה מ-`OBS_AI_EXPLAIN_TIMEOUT`               | הלקוח יציג fallback |

כל השגיאות מחזירות גוף JSON בסיסי: `{"error": "...", "message": "..."}`.

---

## ⚙️ קונפיגורציה נדרשת

| משתנה | תפקיד | ברירת מחדל |
|-------|-------|------------|
| `ANTHROPIC_API_KEY` | מפתח API של Claude Sonnet | — |
| `OBS_AI_EXPLAIN_URL` | כתובת השירות (בדרך כלל `http://<host>:10000/api/ai/explain`) | ריק (מבטל AI) |
| `OBS_AI_EXPLAIN_TOKEN` | Bearer token הדדי בין Dashboard ↔︎ שירות | ריק (ללא אימות) |
| `OBS_AI_EXPLAIN_TIMEOUT` | Timeout גם ללקוח וגם לשירות | `10` שניות |
| `OBS_AI_EXPLAIN_MODEL` *(אופציונלי)* | שם הדגם המדויק (למשל `claude-3-5-sonnet-20241022`) | Sonnet יציב |
| `OBS_AI_EXPLAIN_MAX_TOKENS` *(אופציונלי)* | מגבלת טוקנים לתשובת Claude | `800` |

> חשוב: אם החיבור לשירות נפל, הדשבורד ימשיך לספק הסבר יוריסטי כך שה-UX לא נשבר.

---

## 🧪 בדיקות

- `tests/unit/services/test_ai_explain_service.py` – בודק Masking, fallback ותקינות פלט.
- `tests/test_webserver_ai_explain_endpoint.py` – בודק אימות Bearer, החזרת JSON והידרדרות לשגיאות.

 להפעלת בדיקות ממוקדות:

```bash
pytest tests/unit/services/test_ai_explain_service.py tests/test_webserver_ai_explain_endpoint.py
```

---

## 📝 טיפים לפריסה

1. חשוף את ה־webserver (AioHTTP) דרך פורט ייעודי או behind-ingress.
2. קבע את `OBS_AI_EXPLAIN_URL` בצד ה-WebApp כדי שיפנה לשירות.
3. אחסן את `OBS_AI_EXPLAIN_TOKEN` וגם את `ANTHROPIC_API_KEY` ב-Secret Manager (Render/Heroku/K8s).
4. נטר את האירועים `ai_explain_request_*` ב-Observability כדי לוודא SLA < 10 שניות.
