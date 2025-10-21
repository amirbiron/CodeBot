# 🚦 מערכת Rate Limiting לסוכני AI ולווב

מטרה: להסביר איך מפעילים ומנטרים Rate Limiting בבוט ובווב, עם דגש על Shadow Mode, ניטור וקונפיג.

---

## אסטרטגיה – Shadow Mode תחילה
- הפעילו תחילה ב־Shadow Mode: סופרים פגיעות בלימיט אך לא חוסמים.
- עקבו אחרי המטריקות, כיילו ספים, ורק אז עברו לחסימה אמיתית.
- מנהלים (ADMIN_USER_IDS) יכולים לעקוף הגבלות קריטיות בעת הצורך.

```text
RATE_LIMIT_ENABLED=true
RATE_LIMIT_SHADOW_MODE=true   # מומלץ בסביבת staging / rollout ראשוני
RATE_LIMIT_STRATEGY=moving-window  # או fixed-window
ADMIN_USER_IDS=12345,67890
```

---

## משתני סביבה וקונפיג
- `RATE_LIMIT_ENABLED`: הפעלת המערכת גלובלית (ברירת מחדל: true)
- `RATE_LIMIT_SHADOW_MODE`: מצב ספירה בלבד, ללא חסימה (ברירת מחדל: false)
- `RATE_LIMIT_STRATEGY`: `moving-window` או `fixed-window`
- `ADMIN_USER_IDS`: רשימת מזהי משתמש (טלגרם) שמורשים לעקוף חלק מההגבלות
- `REDIS_URL`: חיבור לאחסון משותף (TLS: `rediss://` בפרוד)

הטענה מתבצעת דרך Pydantic Settings ו־`.env(.local)` – ראו "Config via Pydantic Settings" בעמוד הקונפיגורציה.

---

## אינטגרציה – בוט טלגרם
המערכת משתמשת ב־`limits` + Redis (אם זמין). במצב Shadow לא נחסום, רק נמדוד ונדווח.

```python
from bot_rate_limiter import rate_limit

@rate_limit(scope="commands", limit_name="sensitive", bypass_admins=True)
async def handle_sensitive(update, context):
    await update.message.reply_text("בוצע בהצלחה ✨")
```

- ב־Shadow Mode, חריגה מהלימיט תתועד במטריקות/לוגים אך לא תיחסם.
- מנהלים ב־`ADMIN_USER_IDS` מדולגים כברירת מחדל (`bypass_admins=True`).

---

## אינטגרציה – Flask/WebApp
בצד הווב נעשה שימוש ב־Flask-Limiter כשזמין. נתיבי `health` ו־`metrics` מוחרגים.

דוגמת מחזיר 429 מובנה (תמצית):

```python
# מספרי הדגמה בלבד
return jsonify({
  "error": "rate_limit_exceeded",
  "message": "Too many requests",
  "retry_after": 60
}), 429
```

הערה: ב־Flask-Limiter 3.x אין API יציב לשאילת ניצול – נסתמך על אירועים/מטריקות בזמן 429.

---

## החרגות חשובות
- אל תגביל נתיבי בריאות/מדדים: `/health`, `/metrics`.
- דפי סטטיים/נכסים קריטיים – החרגה לפי צורך.

---

## ניטור ומדדים (Prometheus)
- `rate_limit_hits_total{source,scope,limit,result}` – כל ניסיון (allowed/blocked)
- `rate_limit_blocked_total{source,scope,limit}` – ספירת חסימות בפועל

המלצות:
- התחילו ב־Shadow (`result=blocked` יסומן אך לא ייחסם בפועל).
- הגדירו אלרטים רכים על עלייה חדה בפגיעות.
- עברו לחסימה אמיתית רק לאחר כיול ושבוע יציב.

---

## אבטחה והגנות
- השתמשו ב־`rediss://` בפרודקשן.
- צמצמו `ADMIN_USER_IDS` למינימום.
- מערכת הלימיטים היא Fail-Open: אם Redis נופל – לא חוסמים משתמשים.

---

## תקלות נפוצות
- אין `REDIS_URL`: המערכת תרוץ In-Memory – מומלץ רק ל־dev.
- עומס חריג: העלו לימיטים זמנית, ודווחו בהתראה עם הקשר (`scope`, `limit`).

---

## קישורים
- קובץ: `bot_rate_limiter.py`
- ווב: `webapp/app.py` (Flask-Limiter, חריגות 429)
- מדדים: `metrics.py` (`rate_limit_hits_total`, `rate_limit_blocked_total`)
