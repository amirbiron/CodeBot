---
summary: 'מטרה: לקבוע תבנית ברורה ללוגים ולאירועים, להפחית רעש, ולאפשר תחקור מהיר בעזרת request_id.'
---

# 📊 הנחיות Observability ואירועים

## תבנית אירוע/לוג – שדות חובה
- request_id: מזהה מתואם לבקשה/פעולה
- user_id: אם קיים
- operation: שם פעולה תמציתי (למשל: toggle_bookmark)
- severity: info | warning | anomaly | error
- handled: true/false – האם השגיאה טופלה אוטומטית

דוגמה עם emit_event:

```python
emit_event(
    "alert_received",
    severity="anomaly",           # אירועי התראה תמיד anomaly
    handled=True,                  # טופל אוטומטית → לא ייחשב כשגיאה קשה
    request_id=request_id,
    operation="github_rate_limit_check",
    summary="repo=example, window=1h",
)
```

הימנעו מ-`print()`; השתמשו ב-`logger.info/warning/exception` וב-`emit_event` לשדות מובנים.

---

## עקרון Fail-Open
- מערכת observability לעולם לא מפילה את היישום.
- כשלי לוג/מטריקות → לוג רך והמשך עבודה.

```python
try:
    metrics.rate_limit_hits.labels(source="webapp", scope="route", limit="default", result="allowed").inc()
except Exception:
    logger.warning("metrics_increment_failed", exc_info=True, extra={"handled": True})
```

---

## הנחיות טיפול בשגיאות
- No bare except: החליפו `except:` ב-`except Exception as e:`
- חריגים שכדאי לתפוס ספציפית:
  - `PyMongoError` (שגיאות DB) – לוג + `handled=True` אם יש חלופה/ניסיון חוזר
  - `InvalidId` (BSON) – החזירו 400/404 לפי הקשר
  - `KeyError`/`ValueError` – החזירו 400 אם הקלט לא חוקי
- 404 לעומת 500:
  - 404: משאב לא נמצא/מזהה לא תקין
  - 500: שגיאה פנימית בלתי צפויה

דוגמה:

```python
try:
    doc = collection.find_one({"_id": oid})
    if not doc:
        return jsonify({"error": "not_found"}), 404
except InvalidId as e:
    logger.warning("invalid_object_id", extra={"handled": True, "error": str(e)})
    return jsonify({"error": "invalid_id"}), 400
except PyMongoError as e:
    logger.exception("db_error")
    return jsonify({"error": "db_error"}), 500
```

---

## קורלציה עם request_id
- תמיד קושרים `request_id` בהתחלה ומעבירים אותו הלאה.
- מוסיפים לכותרות HTTP/תגובה כשאפשר, כדי להקל על תחקור.
- **בבוט, כל יחידת עבודה מתחילה בהקשר ריק משלה.** עדכון מטלגרם וריצה של ג'וב רצים כל אחד ב-`isolated_observability_scope` (`observability.py`): ההקשר של structlog מתרוקן, ו-Sentry מקבל scope חדש, כך ששום `request_id`, משתמש או `command` לא עוברים מיחידה ליחידה. השרת הפנימי (`services/webserver.py`) עולה בהקשר ריק (`start_site_in_empty_context`), ו-aiohttp פותח כל בקשה במשימה משלה מתוך ההקשר הזה; את ה-scope של בקשה ב-Sentry פותח `AioHttpIntegration`, והוא גם זה שתופס חריגה של handler. עדכון מקבל `request_id` חדש, את המשתמש ואת הצ'אט, ו-`command=bot:<פקודה>` כשיש פקודה (`IsolatedUpdateApplication`). ריצה של ג'וב מקבלת `request_id` משלה ו-`command=job:<שם הפונקציה>`, ואת המשתמש רק אם הוא הועבר ל-`run_once` (או לחבריו) ב-`user_id` / `chat_id` (`IsolatedJobQueue`). שתי המחלקות ב-`services/telegram_observability_scope.py`. ג'וב **אינו** יורש את ההקשר של העדכון שתזמן אותו: מי שרוצה שהלוגים של ג'וב יישאו משתמש, מעביר אותו בתזמון. למה זה בנוי ככה — הרשומה ב-`docs/whats-new/2026-11.rst`, 2026-11-20.

```python
request_id = generate_request_id()
bind_request_id(request_id)
emit_event("request_started", severity="info", request_id=request_id)
```

---

## סטנדרטים נוספים
- אירועי `alert_received` → תמיד `severity="anomaly"`
- `handled=true` צובע לוגים בכתום ומסייע לסוכני triage להבדיל משגיאות קשות
- שדות מומלצים נוספים: `file_id`, `duration_ms`, `count`, `limit`, `scope`
