# Runbooks – SLO Incidents

> תמצית. קצר, תכל'ס, בעברית פשוטה.

## HighErrorRate
- בדוק Grafana: פאנל Error Rate.
- בדוק פריסות אחרונות. אם נפרס – שקול rollback מהיר.
- בדוק תלויות חיצוניות (DB/Redis/חיבורים) ושגרות רקע.
- אם חריג זמני – עקוב 10 דק' והפעל rate‑limit עדין אם צריך.

PromQL לדוגמה:
```text
sum(rate(http_requests_total{status=~"5.."}[5m]))
  /
sum(rate(http_requests_total[5m]))
```

## SLOAvailabilityBreach (זמינות < 99.9%)
- בדוק ב‑Grafana זמינות מול תקלות 5xx.
- סקור לוגים לפי trace_id; חפש דפוס אחיד (endpoint ספציפי?).
- עקוף רכיב חולה (feature flag או ניתוק זמני) והורד עומס.
- פתח Incident אם נמשך > 30 דק'.

מדד זמינות משוער (על בסיס מונים סטנדרטיים):
```text
(1 - (sum(rate(http_requests_total{status=~"5.."}[5m]))
      / sum(rate(http_requests_total[5m])))) * 100
```

## SLOLatencyP95Breach (P95 > 0.5s)
- בדוק פאנל Latency P95 והיסטוגרמות endpoint.
- זהה צוואר בקבוק (DB/IO/חיצוני) דרך traces.
- פרוס cache/עלות חישובית מופחתת/הגדל משאבים זמנית.
- כתוב ממצא קצר ברנבוק בסיום.

PromQL לדוגמה (Histogram):
```text
histogram_quantile(0.95,
  sum(rate(http_request_duration_seconds_bucket[5m])) by (le, endpoint))
```

## תקלת התחברות ל‑DB (MongoDB) – קריטי
**מכסה שגיאות נפוצות:** `ReplicaSetNoPrimary`, `No replica set members`, `SSL handshake failed`, `OperationCancelled`

**חומרה:** 🔴 קריטית (הבוט מושבת חלקית/מלא בפעולות שדורשות DB)

### סימפטומים
- התראות/Issues ב‑Sentry סביב MongoDB/pymongo.
- פקודות שדורשות שמירה/שליפה לא עובדות (למשל `/stats`, רישום משתמש).
- זמן תגובה קופץ, או הרבה 5xx סביב פעולות DB.

### סדר פעולות (בקצרה)
1. **בדיקת ספק (Atlas Status)**: אם יש תקלה אצל הספק – לרוב אין מה “לתקן” אצלנו, רק לעקוב ולעדכן סטטוס.
   - MongoDB Status: [status.mongodb.com](https://status.mongodb.com/)
2. **בדיקת קונפיג בסיסי**: ודא ש‑`MONGODB_URL` מוגדר ונראה תקין (במיוחד אם זה `mongodb+srv://...`).
   - הערה: את `YOUR_MONGODB_HOST` קח מתוך ה‑URL (לרוב הדומיין אחרי `@`, למשל `cluster0.mongodb.net`).
3. **בדיקת DNS/TCP מהשרת** (מהיר, בלי תלות בכלים “אקזוטיים”):
   - DNS:
     - `getent hosts YOUR_MONGODB_HOST`
   - TCP (פורט 27017):
     - `timeout 5 bash -lc 'cat < /dev/null > /dev/tcp/YOUR_MONGODB_HOST/27017'`
     - אם זה נכשל: בעיית רשת/Firewall/NAT/ספק.
4. **בדיקת TLS** (אם השגיאה על SSL Handshake):
   - `timeout 8 openssl s_client -connect YOUR_MONGODB_HOST:27017 -servername YOUR_MONGODB_HOST -brief < /dev/null`
   - אם זה נכשל, בדוק: זמן מערכת (NTP), CA bundle במכונה, ותצורת TLS בארגון.
5. **Network Access / IP allowlist (Atlas)**:
   - ודא שה‑egress IP של השרת מורשה.
   - **המלצה:** להוסיף רק `x.x.x.x/32` של השרת.
   - **לא מומלץ** לפתוח `0.0.0.0/0`. אם חייבים לשלול חסימה באירוע קריטי:
     - לעשות זאת **רק לזמן קצר**, עם תיעוד, ורק אם זה עומד במדיניות האבטחה – ואז להחזיר מיד.
6. **Restart לשירות**:
   - לפעמים הדרייבר “נתקע” (pool/handshake). אתחל רק את שירות הבוט/ה‑worker הרלוונטי (Docker/Systemd), ואז עקוב ב‑Logs אם החיבור חוזר.

טיפ: אם יש `request_id` מאירוע משתמש – הרץ `/triage <request_id>` כדי לקפוץ ישר ללוגים/קישורי Sentry הרלוונטיים.

## איטיות/נפילה של שירות חיצוני – בינוני
**מכסה:** `External Service Degraded`, latency גבוה, timeouts, 429

**חומרה:** 🟡 בינונית (חווית משתמש נפגעת; לפעמים נראה כמו “הבוט חושב”)

### סימפטומים
- זמן תגובה עולה מעל כמה שניות (בעיקר ב‑P95/P99).
- Error Rate עולה (timeouts/429/5xx מהתלות).
- משתמשים מתלוננים על “הודעות נתקעות”.

### סדר פעולות
1. **זהה מי האיטי**: Grafana/Logs/Traces – האם זה OpenAI? Telegram? DB? או השרת עצמו.
2. **בדוק Status רשמי של הספק**:
   - OpenAI: [status.openai.com](https://status.openai.com/)
   - Telegram: [status.telegram.org](https://status.telegram.org/)
3. **אם הספק למטה/איטי**:
   - עדכן תקשורת למשתמשים (“יתכנו עיכובים עקב עומס אצל הספק”).
   - שקול להפעיל/להדק rate limit עדין, ולהגדיל timeouts בצורה שמרנית (רק אם זה לא מגדיל עומס).
4. **אם האיטיות פנימית**:
   - בדוק CPU/RAM/דיסק/תורים, ושגרות רקע.
   - נסה הקלה מהירה: הגדלת משאבים זמנית או restart לשחרור משאבים (אחרי שיש לך תמונת מצב בלוגים).

## באג אחרי Deploy / Release – משתנה
**מכסה:** exceptions חדשות מיד אחרי פריסה (למשל `TypeError` ב‑observability), `internal_alert`, 500 בפיצ'ר מסוים

**חומרה:** 🟠 משתנה (תלוי אם זה משבית זרימה מרכזית)

### סדר פעולות
1. **צמצום נזק מיידי**:
   - אם זה שובר פרודקשן: בצע rollback דרך ה‑CI/CD או החזרה לגרסת image/tag האחרונה שעבדה (לא “לעשות קסמים” ידנית ב‑git בפרודקשן).
2. **איסוף נתונים**:
   - פתח Sentry, קח traceback מלא וה‑fingerprint.
   - אסוף `request_id` ורוץ `/triage <request_id>` כדי לאמת את אותו דפוס בלוגים.
3. **Root Cause**:
   - בדוק שינויי קונפיג/ENV, שינויים ב‑schema/DB, ושינויי גרסאות של תלויות.
4. **Hotfix**:
   - תקן, הוסף בדיקה/כיסוי מינימלי כדי למנוע חזרה, והעלה גרסת תיקון.

דשבורד
-------
- דשבורד `codebot-slo-dashboard.json` מסופק תחת `docker/grafana/provisioning/dashboards/`.
- מומלץ לקשר אליו מתוך Grafana ולכוונן ספים לפי סביבת Staging/Prod.
