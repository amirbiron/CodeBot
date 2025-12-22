# מערכת Caching מתקדמת עם TTL דינמי

מסמך זה מרכז את ההמלצות והדוגמאות להטמעת מערכת caching חכמה עם TTL דינמי, כפי שגובש ב-Feature Suggestion. המטרה: שיפור מהיר של זמני תגובה, הורדת עומסים על DB, ושימור עקביות בין שרתים.

- **למה**: הפחתת זמן תגובה, עומס DB וצריכת רוחב-פס.
- **מה**: TTL דינמי לפי סוג תוכן וקונטקסט, warming, invalidation חכם, ו-sync בין שרתים.
- **איך**: הרחבות ל-`cache_manager.py` ודקורטורים לשימוש נוח ב-WebApp.

## עקרונות

- TTL מבוסס סוג תוכן + התאמות לפי קונטקסט (פופולריות, עדכון אחרון, tier משתמש).
- התאמות לפי שעות פעילות (שעות שיא/לילה).
- invalidation חכם באירועי שינוי, תמיכה ב-tags וגרסאות.
- סנכרון בין instances באמצעות Redis Pub/Sub.

## קוד לדוגמה

ראו קטעי קוד נרחבים במדריך היישום. דוגמאות מרכזיות:

- מחלקות `DynamicTTL` ו-`ActivityBasedTTL` לקביעת TTL דינמי.
- `EnhancedCacheManager.set_dynamic` ו-`get_with_refresh` להטמעה הדרגתית.
- דקורטור `@dynamic_cache` לשימוש ב-Flask endpoints.
- מנגנוני invalidation (patterns, tags, versions) ו-sync.

## דגשים תפעוליים

- מדדו Hit Rate וזמני תגובה; יעד Hit Rate > 80% לאחר warming.
- הוסיפו jitter ל-TTL למניעת thundering herd.
- fallback מקומי בעת תקלה ב-Redis.

## Warmup לנכסי Frontend

- לאחר שהשרת חולף על `/healthz`, `scripts/start_webapp.sh` יכול לבצע warmup יזום לדפי ה-Frontend ע״י משתנה הסביבה `WEBAPP_WARMUP_PATHS` (CSV כמו `/dashboard,/collections`).
- ניתן לשנות את בסיס הכתובת באמצעות `WEBAPP_WARMUP_BASE_URL` (ברירת מחדל `http://127.0.0.1:$PORT`) ואת ה-timeout לכל בקשה דרך `WEBAPP_WARMUP_REQUEST_TIMEOUT` (ברירת מחדל 2 שניות).
- כל ניסיון מחזיר לוג בסגנון `Warmup: /dashboard... OK/FAIL`, כך שניתן לעקוב אחרי CDN/Template Cache שמתמלא עוד לפני שהמשתמשים הראשונים מגיעים.
- כדי למנוע השפעה על זמני עלייה, ה-warmup רץ רק לאחר הצלחת בדיקת הבריאות, ונחשב best-effort (כישלון לא מפיל את התהליך).

## קישורים

- Issue המקור: [#975](https://github.com/amirbiron/CodeBot/issues/975)
- דף WebApp – Caching Validators: `webapp/caching`
