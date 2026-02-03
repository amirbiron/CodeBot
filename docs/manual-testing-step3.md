# בדיקות ידניות - Step 3: The Great Split

## סקירה כללית
מסמך זה מפרט את הבדיקות הידניות הנדרשות לאחר מיגרציית Routes לארכיטקטורה השכבתית (Issue #2871 Step 3).

---

## 1. Auth Routes (`/login`, `/logout`, `/auth/*`)

### 1.1 התחברות דרך Telegram Widget
- [ ] גש ל-`/login` וודא שהדף נטען כראוי עם כפתור Telegram
- [ ] לחץ על הכפתור והתחבר דרך Telegram
- [ ] וודא הפנייה ל-`/dashboard` לאחר התחברות מוצלחת
- [ ] וודא ש-session נשמר (user_data מכיל first_name, is_admin, is_premium)

### 1.2 התחברות דרך Token (מהבוט)
- [ ] בקש קישור התחברות מהבוט
- [ ] לחץ על הקישור וודא כניסה אוטומטית
- [ ] וודא שהקישור לא עובד פעם שנייה (one-time use)
- [ ] וודא שקישור שפג תוקפו מציג הודעת שגיאה מתאימה

### 1.3 התנתקות
- [ ] לחץ על Logout
- [ ] וודא הפנייה לעמוד הבית
- [ ] וודא ש-session נמחק (ניסיון גישה ל-`/dashboard` מפנה ל-login)
- [ ] וודא ש-remember_me cookie נמחק (אם היה קיים)

### 1.4 שמירת URL מקורי
- [ ] גש ל-`/settings` ללא התחברות
- [ ] וודא הפנייה ל-`/login?next=/settings`
- [ ] התחבר וודא הפנייה חזרה ל-`/settings` (לא ל-dashboard)

---

## 2. Settings Routes (`/settings/*`)

### 2.1 עמוד הגדרות ראשי
- [ ] גש ל-`/settings` כמשתמש מחובר
- [ ] וודא שהדף נטען עם כל הסקציות
- [ ] וודא שהגדרות persistent login מוצגות נכון
- [ ] וודא שכפתור Push notifications מופיע (אם מאופשר)

### 2.2 עמוד Push Debug (Admin Only)
- [ ] גש ל-`/settings/push-debug` כמשתמש רגיל - וודא הפנייה ל-`/settings#push`
- [ ] גש ל-`/settings/push-debug` כאדמין - וודא שהדף נטען
- [ ] וודא שמידע הקונפיגורציה מוצג (VAPID keys set, versions)
- [ ] וודא שמספר הsubscriptions מוצג

### 2.3 Theme Builder & Gallery
- [ ] גש ל-`/settings/theme-builder` וודא טעינת הדף
- [ ] גש ל-`/settings/theme-gallery` וודא טעינת הדף
- [ ] וודא שהרשאות admin/premium מוצגות נכון

### 2.4 API - עדכון הגדרות Attention Widget
```bash
# בדיקת עדכון הגדרות
curl -X PUT http://localhost:5000/api/settings/attention \
  -H "Content-Type: application/json" \
  -d '{"enabled": true, "stale_days": 30}' \
  --cookie "session=<YOUR_SESSION>"
```
- [ ] וודא שהעדכון מחזיר `{"ok": true}`
- [ ] וודא ש-stale_days מוגבל לטווח 7-365
- [ ] וודא ש-max_items_per_group מוגבל לטווח 3-50
- [ ] וודא שערכים לא תקינים מחזירים שגיאה 400

---

## 3. Dashboard Routes (`/dashboard`, `/api/dashboard/*`)

### 3.1 עמוד Dashboard ראשי
- [ ] גש ל-`/dashboard` כמשתמש מחובר
- [ ] וודא שהדף נטען עם skeleton loaders
- [ ] וודא שהסטטיסטיקות נטענות (total files, collections count)
- [ ] וודא שהתצוגה הנכונה מוצגת (תלוי בקיום קבצים)

### 3.2 API - מה חדש
```bash
curl http://localhost:5000/api/dashboard/whats-new?max_days=14 \
  --cookie "session=<YOUR_SESSION>"
```
- [ ] וודא שהתגובה מכילה מבנה תקין עם `ok`, `files`, `repos`
- [ ] וודא ש-max_days מוגבל לטווח 7-180
- [ ] וודא שתאריכים מופיעים בפורמט ISO

### 3.3 API - קבצי הקומיט האחרון
```bash
curl http://localhost:5000/api/dashboard/last-commit-files?offset=0&limit=10 \
  --cookie "session=<YOUR_SESSION>"
```
- [ ] וודא שהתגובה מכילה `ok`, `files`, `has_more`
- [ ] וודא שהדפדוף עובד נכון (שינוי offset)
- [ ] וודא שבמצב שאין קומיטים מוחזר status 404 עם הודעה מתאימה

### 3.4 API - פעילות אחרונה
```bash
curl http://localhost:5000/api/dashboard/activity \
  --cookie "session=<YOUR_SESSION>"
```
- [ ] וודא שהתגובה מכילה `ok`, `events`
- [ ] וודא שאירועים מוגבלים ל-7 ימים אחרונים
- [ ] וודא שסוגי האירועים נכונים (file_saved, tag_added, etc.)

### 3.5 API - קבצים לפי פעילות
```bash
curl http://localhost:5000/api/dashboard/activity-files \
  --cookie "session=<YOUR_SESSION>"
```
- [ ] וודא שהתגובה מכילה `files` עם תאריכי פעילות
- [ ] וודא שהקבצים מסוננים ל-7 ימים אחרונים

---

## 4. בדיקות אבטחה

### 4.1 הרשאות
- [ ] וודא שכל ה-endpoints דורשים התחברות (מחזירים 401 ללא session)
- [ ] וודא ש-push-debug נגיש רק לאדמינים
- [ ] וודא ש-impersonation מסתיר הרשאות admin/premium

### 4.2 מניעת דליפת מידע
- [ ] וודא ששגיאות שרת מחזירות `"internal_error"` ולא stack trace
- [ ] וודא שמפתחות VAPID פרטיים לא נחשפים ב-push-debug

### 4.3 Telegram Auth
- [ ] וודא ש-hash לא תקין מחזיר 401
- [ ] וודא שהתחברות עם auth_date ישן (יותר משעה) נכשלת
- [ ] וודא שללא BOT_TOKEN השרת מסרב לאמת (לא משתמש ב-hash ריק)

---

## 5. בדיקות אינטגרציה

### 5.1 Session Consistency
- [ ] התחבר וגש לכמה עמודים שונים
- [ ] וודא ש-user_data עקבי בכל העמודים
- [ ] וודא ש-is_admin ו-is_premium נשמרים ב-cache בסשן

### 5.2 Blueprint Registration
- [ ] הפעל את השרת וודא שאין שגיאות import
- [ ] וודא שכל ה-routes רשומים (בדוק ב-Flask debug output)

### 5.3 Lazy Imports
- [ ] וודא שאין circular import errors בהפעלה
- [ ] וודא ש-_get_app_helpers() עובד נכון בכל ה-routes

---

## 6. Performance

### 6.1 Smart Projection
- [ ] וודא ש-API calls לא מחזירים שדות כבדים (code, content) ברשימות
- [ ] בדוק זמן תגובה של `/api/dashboard/whats-new` (צריך להיות < 500ms)

### 6.2 Skeleton Loaders
- [ ] וודא שהדף הראשי של dashboard נטען מהר (< 200ms)
- [ ] וודא שה-API calls נטענים ברקע

---

## רשימת פקודות מהירות לבדיקה

```bash
# בדיקת health של כל ה-routes
curl -I http://localhost:5000/login
curl -I http://localhost:5000/settings
curl -I http://localhost:5000/dashboard

# בדיקת 401 ללא session
curl http://localhost:5000/api/dashboard/whats-new
curl http://localhost:5000/api/settings/attention -X PUT

# בדיקת admin-only
curl http://localhost:5000/settings/push-debug
```

---

## הערות
- כל הבדיקות מניחות שהשרת רץ על `localhost:5000`
- יש להחליף `<YOUR_SESSION>` ב-cookie session אמיתי
- לבדיקות admin יש להשתמש במשתמש עם הרשאות מתאימות
