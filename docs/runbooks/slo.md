# Runbooks – SLO Incidents

> תמצית. קצר, תכל'ס, בעברית פשוטה.

## HighErrorRate
- בדוק Grafana: פאנל Error Rate.
- בדוק פריסות אחרונות. אם נפרס – שקול rollback מהיר.
- בדוק תלויות חיצוניות (DB/Redis/חיבורים) ושגרות רקע.
- אם חריג זמני – עקוב 10 דק' והפעל rate‑limit עדין אם צריך.

## SLOAvailabilityBreach (זמינות < 99.9%)
- בדוק ב‑Grafana זמינות מול תקלות 5xx.
- סקור לוגים לפי trace_id; חפש דפוס אחיד (endpoint ספציפי?).
- עקוף רכיב חולה (feature flag או ניתוק זמני) והורד עומס.
- פתח Incident אם נמשך > 30 דק'.

## SLOLatencyP95Breach (P95 > 0.5s)
- בדוק פאנל Latency P95 והיסטוגרמות endpoint.
- זהה צוואר בקבוק (DB/IO/חיצוני) דרך traces.
- פרוס cache/עלות חישובית מופחתת/הגדל משאבים זמנית.
- כתוב ממצא קצר ברנבוק בסיום.
