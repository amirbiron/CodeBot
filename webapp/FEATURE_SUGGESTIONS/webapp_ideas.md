# 💡 רעיונות טריים ל־WebApp של CodeBot
תאריך: 23/11/2025  
מקור: סריקה מלאה של `webapp/` – API‑ים (כמו `bookmarks_api.py`, `collections_api.py`, `snippet_library_ui.py`), תבניות Jinja תחת `templates/`, הבילדים הסטטיים ב־`static_build/` והנחיות הקוד בתוך `FEATURE_SUGGESTIONS/`.  
מטרה: להוסיף הצעות חדשות שלא קיימות במסמכים הקיימים, בלי להציע שיתופי קהילה או סוכן AI לבוט.

---

## ⚡ TL;DR – חמש הצעות שלא הופיעו במסמכים אחרים

| # | רעיון | למה עכשיו | מאמץ משוער |
|---|-------|-----------|------------|
| 1 | Recovery Capsules | שומר טיוטות לא שמורות וטוען אותן אחרי נפילה | בינוני |
| 2 | Markdown Layout Sentinel | בודק שה־Markdown מתאים לכל התבניות לפני פרסום | בינוני |
| 3 | Workspace Blueprints | מסכי דשבורד אישיים שמבוססים על רכיבים קיימים | בינוני‑גבוה |
| 4 | Request Replay Sandbox | חנות בקשות API שנשמרות ומורצות מחדש לבדיקה | גבוה |
| 5 | Attachment Locker | ספריית נכסים פר קובץ שמסנכרנת בין `upload.html` ל־`files.html` | בינוני |

כל אחד מהפיצ'רים נבדק מול כל המסמכים שב־`webapp/FEATURE_SUGGESTIONS/` כדי לוודא ייחודיות.

---

## 1. Recovery Capsules – שחזור אוטומטי של עבודה בעורך
**בעיה:** קבצים שנערכים דרך `templates/edit_file.html` ו־`snippet_library_ui.py` הולכים לאיבוד אם יש ניתוק או רענון. אין שכבת auto‑save לפני שהמשתמש לוחץ "שמור".

**פתרון:**  
- שמירת snapshot מוצפן ב־IndexedDB + Redis בכל X שניות, לצד checksum קצר שמתקבל מ־`bookmarks_api.py`.  
- כפתור "שחזר טיוטה" שמופיע אם `created_at` ב־DB ישן מהסנאפשוט.  
- עטיפה דקה ב־`static_build/build-cm.mjs` שמנטרת keypress ומשגרת debounced save ל־`/api/drafts`.

**יתרונות:** חוסך כתיבה מחדש, מאפשר החזרת שינויים מקריסת דפדפן, מקל על עבודה במובייל.  
**בדיקת הצלחה:** לפחות 90% מטיוטות שנשמרו נטענות בהצלחה; פחות מ־200ms latency להחזרת snapshot.

---

## 2. Markdown Layout Sentinel – בדיקת פריסות לפני שיתוף
**בעיה:** `md_preview.html`, `html_preview.html` ו־`view_file.html` משתמשים באותן תבניות בסיס, אבל אין כלי שבודק מראש עוגנים שבורים, תמונות חיצוניות בלתי זמינות או שילוב רכיבי RTL.

**פתרון:**  
- CLI קטן ב־`static_build/md-preview-entry.js` שמריץ את אותו render pipeline כמו בשרת, כולל חוקים מותאמים (לדוגמה `markdown-it` plugins שכבר נטענים).  
- דוח inline שמוצמד לעורך ומציף שגיאות כמו "כותרת H2 בלי עוגן" או "קישור חיצוני 404".  
- רשימת "תיקונים אוטומטיים" – הזרקה של `aria-label` חסר או השלמת טבלאות.

**יתרונות:** חוסך רנדורים שבורים, משמר ציון Lighthouse, מגן מפני Markdown שפוגע ב־`base.html`.  
**מדדי הצלחה:** 0 תקלות Markdown בסשן deploy; ירידה של 30% בזמן שמושקע בתיקון פריסות.

---

## 3. Workspace Blueprints – דשבורדים אישיים מאבני בניין קיימות
**בעיה:** `dashboard.html` מציג תצוגה קבועה. משתמשים שונים צריכים לוחות אחרים (לדוגמה התמקדות ב־bookmarks לעומת snippets).

**פתרון:**  
- מנוע Blueprint שמאפשר לבחור ווידג'טים קיימים (`collections_api` stats, `bookmarks_manager` counters, רשימות מ־`snippet_library_ui`).  
- אחסון ההרכב ב־`user_preferences` שכבר נקרא ב־`settings.html`.  
- Render צד שרת עם Jinja macro חדש (`{% blueprint_layout %}`) כדי לשמור על SEO וללא בנדלר.

**יתרונות:** התאמה אישית ללא בניית UI מאפס, שיפור מעורבות.  
**מאמץ:** פיתוח שרת + UI ≈ 2.5 שבועות (רוב הקוד כבר קיים כרכיבים).  
**KPI:** עליה של 20% בזמן השהייה בדשבורד, ירידה בכמות הניווטים החוזרים לתפריטים.

---

## 4. Request Replay Sandbox – שחזור בקשות API לצורך באגים
**בעיה:** בעת בדיקת תקלות ב־`bookmarks_api.py`/`collections_api.py` צריך לשחזר payload ידנית. אין כלי ששומר את ה־requests האמיתיים מה־WebApp.

**פתרון:**  
- תיעוד מובנה (structured log) ב־`services/webserver.py` לכל בקשה שמגיעה מה־UI, כולל גוף הבקשה לאחר סינון נתונים רגישים.  
- UI תחת `admin_snippets_import.html` (או עמוד חדש) שמאפשר לבחור בקשה שנשמרה ולהריץ אותה מול סביבות dev/stage עם כפתור "Replay".  
- שילוב עם `tmp/` בלבד לצורך פלטים, בהתאם למדיניות מחיקה בטוחה.

**יתרונות:** מאיץ דיבוג, מאפשר שיחזור בעיות ביצועים והבדלי נתונים, בלי לגרום לשיתופי קהילה.  
**מדדי הצלחה:** זמן ממוצע לשחזור תקלה יורד ב־40%, לכל הפחות 50 בקשות שמורות לשבוע.

---

## 5. Attachment Locker – ניהול נכסים צמודים לקבצים
**בעיה:** `upload.html` ו־`files.html` מנהלים קבצי טקסט, אבל אין דרך לצרף אליהם תמונות, דיאגרמות או JSON נלווה בלי לערב ידנית את `static/`. התוצאה: קישורים שבורים ומעקב מסורבל.

**פתרון:**  
- תת־תיקיה ייעודית per file (`/attachments/<file_id>/`) שנשלטת על ידי API חדש ב־`bookmarks_api.py`.  
- תצוגה בתוך `view_file.html` שמראה את כל הקבצים המצורפים, כולל checksum ו־preview אם זה SVG/PNG.  
- הסבת קישורי Markdown כדי שיתייחסו לנתיב חתום (`/attachments/...`), כך שאין צורך לסמוך על CDN חיצוני.

**יתרונות:** סדר בקבצים, פחות שבירת קישורים, ניהול הרשאות ברור.  
**מאמץ:** בינוני (DB + UI + אחסון).  
**KPI:** 0 קישורים שבורים שנמדדו ע"י Lighthouse, וצמצום של 25% בתקלות "קובץ חסר".

---

## למה זה לא חופף למסמכים אחרים
- עברתי על כל הקבצים תחת `webapp/FEATURE_SUGGESTIONS/` (כולל `NEW_FEATURE_SUGGESTIONS.md`, `webapp_improvement_ideas.md`, `DARK_MODE_IMPLEMENTATION_GUIDE.md`, והמסמכים שב־`Archive/`). אף אחד מהמסמכים האלה לא מציע שחזור טיוטות, Sentinel ל־Markdown המותאם לתבניות, Blueprints לדשבורד, sandbox לשחזור בקשות או ספריית קבצים מצורפים משולבת.
- בנוסף, הדרתי במפורש רעיונות של שיתופי קהילה או סוכן AI, בהתאם לבקשה.

---

## צעדים מוצעים
1. **Poc ל־Recovery Capsules** – hooks בצד לקוח + endpoint שממפה טיוטות ל־`file_id`.  
2. **Lint ל־Markdown** – שימוש ב־`markdown_it` הקיים והוספת בדיקות snapshot לטמפלטים `md_preview.html` ו־`html_preview.html`.  
3. **אפיון Blueprint DSL** – טבלת `user_blueprints` עם רשימת ווידג'טים ואחוזי רוחב.  
4. **תיעוד structured** – הרחבת `services/webserver.py` כדי לשמור מטא־דטה לכל בקשה לשימוש ב־Replay.  
5. **Avro/Parquet attachments** – בחירת פורמט אחסון והוספת בדיקות הרשאה ב־`repository.py`.

---

## נספח – בדיקות ועוגנים
- **בדיקות יחידה:** להוסיף כיסויים ל־Recovery Capsules (Redis + fallback), ול־Markdown Sentinel (סימולציית קובץ בעייתי).  
- **Migrations:** Attachment Locker מחייב שדה חדש ב־`database/models.py` (לספירת קבצים מצורפים).  
- **אבטחה:** Request Replay חייב לטשטש נתונים רגישים (token, file body) לפני אחסון.  
- **נגישות:** כל הווידג'טים ב־Blueprints מחויבים לשמור על `aria-label` כדי לא לפגוע בתבניות הקיימות.

---

נכתב בצניעות לאחר סריקה ידנית של `webapp/` ומיועד לשמש בסיס להמשך עבודה. אשמח להרחיב על כל רעיון במידת הצורך.
