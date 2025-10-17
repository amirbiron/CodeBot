### FAQ ממוקד סוכנים

- **מטרה**: להפעיל/לבדוק את ה‑WebApp ואת ה‑API מהר, בבטחה וללא ניחושים.

- **איך מתחילים מהר**:
  - התקינו תלויות: `cd webapp && pip install -r ../requirements/production.txt`.
  - צרו קובץ קונפיג: `cp webapp/.env.example webapp/.env` ועדכנו ערכים.
  - הריצו מקומית: `python webapp/app.py` וגלשו ל‑`http://localhost:5000`.
  - מסמכי API: `http://localhost:5000/docs` (Swagger) או `http://localhost:5000/redoc`.

- **אימות**:
  - רוב ה‑API דורש סשן (cookie `session`). התחברו דרך ה‑UI ואז העתיקו את ה‑cookie לבדיקות curl/Postman.
  - אין OAuth/JWT בשכבה זו.

- **DB וקאש**:
  - MongoDB חובה (`MONGODB_URL`), Redis אופציונלי לקאש.
  - בדקו חיבור עם `GET /health` – רואים `database=connected` כשבסדר.

- **דוגמאות מהירות**:
  - curl: ראו `docs/api-examples.md`.
  - Postman: `docs/CodeKeeper.postman_collection.json` (שנו `{{base_url}}`, `{{session_cookie}}`).

- **תקלות נפוצות**:
  - `401 Unauthorized`: אין cookie `session`. התחברו בדפדפן.
  - `MONGODB_URL is not configured`: הגדירו `.env` או ENV בסביבת הרצה.
  - `uptime_unavailable`: הגדירו `UPTIME_*` או אל תשתמשו בנתיב.
  - "קובץ לא נמצא" בפעולות סימנייה: ודאו ש‑`file_id` הוא ObjectId תקין של מסמך ב‑`code_snippets`.

- **גבולות/מדיניות (מותר/אסור)**:
  - אין להזין סודות/PII ל‑repo או ללוגים. סודות רק ב‑ENV.
  - אין לבצע מחיקות מסוכנות בקבצים/DB; עבודה רק על נתיבי tmp, שימוש באישורי בטיחות.
  - אין להריץ פקודות מסוכנות (ללא sudo, ללא `git clean/reset` ב‑workspace).
  - כל שינוי אוטומטי עובר code review אנושי לפני merge.

- **כיסוי API**:
  - סימניות: `POST/PUT/DELETE/GET /api/bookmarks/...` + סטטיסטיקות ויצוא.
  - פעולות ליבה: `POST /api/share/{file_id}`, `POST /api/favorite/toggle/{file_id}`, `GET /api/stats`.
  - העדפות וחיבור קבוע: `POST /api/ui_prefs`, `POST /api/persistent_login`.
  - ציבורי: `GET /api/public_stats`, `GET /api/uptime`, `GET /health`.

- **איפה קוד ה‑API**:
  - Flask ראשי: `webapp/app.py`.
  - Bookmarks Blueprint: `webapp/bookmarks_api.py` (Mongo דרך `database/*`).

- **טיפים לייצור**:
  - השתמשו ב‑`gunicorn` והקפידו על `SECRET_KEY` חזק.
  - הגדירו `PUBLIC_BASE_URL` כדי שקישורי שיתוף יהיו מלאים ונכונים מאחורי פרוקסי.
