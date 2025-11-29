# ✨ רעיונות פרקטיים ל-WebApp – דצמבר 2025
תאריך: 28/11/2025  
הקשר: Code Keeper Bot (Flask + Jinja + MongoDB + Redis). ניתחנו את `webapp/templates`, `webapp/static/js`, APIs כמו `collections_api.py`/`bookmarks_api.py` ואת מסמכי FEATURE_SUGGESTIONS הקיימים כדי לא לחזור על רעיונות קודמים. אין שימוש ברכיבי קהילה או סוכני AI – הכול ממוקד בפרודוקטיביות יומיומית.

---

## 1. Sticky Notes בכל תצוגה + לוח מעקב
**למה עכשיו:** מנגנון הפתקים (`webapp/static/js/sticky-notes.js`) מוגבל ל-`md_preview.html`, בעוד שמשתמשים עוברים רוב הזמן דרך `view_file.html` ו-`card-preview`. המשוב הנוסף נעלם כשחוזרים לעמוד הקבצים.

**מה מציעים:**
- הרחבת StickyNotesManager כך שיכיר עוגני שורה של Pygments ו-CodeMirror.
- טעינת הסקריפט גם ב-`view_file.html` ובתצוגות ההשוואה העתידיות.
- כרטיס "פתקים פתוחים" ב-`dashboard.html` שמאפשר לסגור/להמיר פתק לתזכורת (`push_api.py`).

**מימוש זריז:**
1. הוספת `data-line-anchor` ב-`view_file.html` (מספרי שורות כבר קיימים ב-`.highlighttable`).
2. הרחבת `sticky-notes.js` עם מצבי "per-line" ו-"per-heading" (שימור API קיים ל-Markdown).
3. רכיב JS קטן ב-`dashboard` שקורא `/api/sticky-notes/recent` ומציג מצב משימות.

**מדד הצלחה:** ≥70% מהפתקים נוצרים מתצוגות קוד (לא רק Markdown) בתוך חודש.

---

## 2. Smart Collections Rules + Focus Mode
**למה עכשיו:** `collections.html` + `webapp/static/js/collections.js` מציעים ממשק נוח, אבל כל האוספים נבנים ידנית. אין דרך לשחזר בקליק את אותם פילטרים שהמשתמש כבר מפעיל ב-`files.html`.

**מה מציעים:**
- הוספת שדה `rules` ב-`collections` (Mongo): שפה, טווח גודל, תגיות, owner/repo, regex בשם.
- טריגר רקע (`collections_manager.py`) שמרענן את האוסף אחת לכמה דקות ומוסיף/מסיר פריטים בהתאם לחוקים.
- Focus Mode: בחירת אוסף "חכם" מתוך `files.html` → מסנן אוטומטית את הגריד ומציג badge שהפילטר מופעל.

**מימוש:**
1. הרחבת `collections_api.py` עם CRUD לחוקים (JSON schema פשוט).
2. UI בסיידבר (`collections.js`): טופס יצירת חוק + תצוגה מיידית what-if (סופר כמה פריטים ייכנסו).
3. Endpoint חדש `/api/collections/<id>/resolve` שמחזיר רשימת קבצים לאחר יישום החוקים – אותו קוד יכול לשמש גם ל-Focus Mode ב-`files.html`.

**מדד הצלחה:** לפחות 40% מהאוספים החדשים מוגדרים כ-rule-based תוך רבעון.

---

## 3. Bulk Diff & Snapshot Compare מתוך הבחירה המרובה
**למה עכשיו:** ה-Toolbar ב-`files.html`/`webapp/static/js/multi-select.js` יודע לבצע מועדפים, תגיות ו-ZIP – אבל אין דרך להשוות שתי גרסאות במהירות, למרות שמידע היסטורי כבר זמין ב-DB.

**מה מציעים:**
- כאשר נבחרים בדיוק שני קבצים, כפתור "השווה" נחשף ומפנה לנתיב חדש `/compare/<idA>/<idB>`.
- העמוד החדש משתמש ב-logic הקיים של `view_file.html` (Pygments) ומציג diff side-by-side (אפשר להתחיל עם `difflib.HtmlDiff`).
- בעת בחירה של יותר משני קבצים: כפתור "צור Snapshot" – שומר רשימת קבצים + hash נוכחי ומאפשר לחזור אליה מהדשבורד.

**מימוש:**
1. הרחבת `multi-select.js` לזיהוי כמות פריטים ולשליחת המשתמש לנתיב compare.
2. תבנית Jinja חדשה `compare_files.html` שממחזרת חלקים מ-`view_file.html` (חשוב להוציא רכיבי קוד משותפים ל-`templates/partials/code_view.html`).
3. API קטן ב-`bookmarks_manager.py`/`repository.py` שמחזיר שתי גרסאות + metadata (שפה, גודל, owner).

**מדד הצלחה:** 25% מהמשתמשים שמפעילים multi-select ילחצו לפחות פעם בשבוע על Compare/Snapshot.

---

## 4. Dashboard Action Center
**למה עכשיו:** `dashboard.html` כבר כולל `activity_timeline`, נתוני Push ופתקים – אך הכול read-only. צוותי תמיכה ביקשו לראות "מה דורש פעולה" במקום לפזר את המבט בין תזכורות, פתקים ו-zip backups.

**מה מציעים:**
- טאבים "כרטיסים פתוחים" ו"נשלח/בוצע" בתוך ה-timeline.
- לכל אירוע (upload, share, reminder) כפתור "סמן כטופל" או "צור משימה" (שנשמרת ב-`reminders/` או ב-`sticky_notes`).
- Widget קטן שמציג חריגות מתוך ה-log aggregator (סומך על `observability.emit_event` שכבר קיים).

**מימוש:**
1. Endpoint `/api/dashboard/actions` שמאחד פתקים, תזכורות ו-share tokens שטרם נסגרו.
2. רכיב JS חדש (למשל `static/js/dashboard_actions.js`) שמאזין ללחיצות ומעדכן את השרת (PUT/POST ל-`push_api.py` / `sticky_notes_api.py`).
3. שינויי UI ב-`dashboard.html` כדי להוסיף אזור "Action Center" בתוך ה-grid הקיים.

**מדד הצלחה:** ירידה של 30% במספר התזכורות שפגות בלי טיפול (נמדד דרך `push_worker`).

---

## 5. Global Search Workbench & Query Pins
**למה עכשיו:** `global_search.js` מספק חיפוש רב-עוצמה (content/regex/fuzzy) אך מאבד את ההקשר ברגע שסוגרים את הדפדפן, ואין דרך לחזור ל-queries מורכבים.

**מה מציעים:**
- הוספת היסטוריית חיפושים + "Pin" ל-query (כולל סוג חיפוש, שפות, sort, regex).
- הזרקת רשימת pins מעל `#searchSuggestions`, עם קיצורים כמו "חפש פונקציות async ב-telegram".
- API `/api/search/pins` שנשמר ב-Redis או Mongo (collection קטנה per user).
- התאמה למקלדת: Cmd/Ctrl+Shift+K פותח Command Palette מינימלי (ללא סוכן AI) שמציג את הפינים ונתיבים.

**מימוש:**
1. הרחבת `global_search.js` לניהול local state + זימון API (POST/DELETE pin).
2. שרשור הנתונים ב-`webapp/app.py` (ה-Blueprint של החיפוש כבר קיים; פשוט מוסיפים endpoints JSON).
3. אפשרות לשתף Pin כאימבד (`/files?q=...&pin=`) כדי שצוות אחר יוכל לפתוח אותו בלחיצה אחת.

**מדד הצלחה:** לפחות 50% מהמשתמשים הכבדים (10+ חיפושים ביום) יחזיקו 3 Pins פעילים תוך חודש.

---

## 6. HTML Preview Insights & Safe Embeds
**למה עכשיו:** כפתור "🌐" ב-`files.html` כבר שולח ל-`html_preview.html`, אבל אין שכבת אבטחה/תובנות (למשל resource usage, קישורים שבורים). משתמשים מנסים להעריך תוצאות rendering בלי לדעת אם ה-CSS נטען או אם יש בקשות חיצוניות.

**מה מציעים:**
- ניתוח קליל של ה-HTML בצד השרת (BeautifulSoup) שמחפש `<script>`/`<link>` חיצוניים ומציג אזהרות לפני טעינה.
- תצוגת "Resources" בתוך `html_preview.html` שמראה זמן טעינת כל משאב + כפתור "פתח ב-tab נפרד".
- אופציה ליצור embed בטוח (iframe עם sandbox) לשילוב ב-documentation הפנימי.

**מימוש:**
1. הוספת שדה metadata ל-output של `/html/<file_id>` (scripts, styles, count).
2. רכיב JS ב-`static/js/html_preview.js` שמצייר טבלת משאבים + מד טיימינג (Performance API).
3. Endpoint `/html/<file_id>/embed` שמחזיר HTML מינימלי עם sandbox ו-Content-Security-Policy.

**מדד הצלחה:** ירידה של 80% בדיווחי "הדף נטען בלי סטיילים" + שימוש גובר ב-embed עבור דפי הנחיות.

---

## סיכום קצר
- כל רעיון נשען על קבצים ותשתיות שכבר קיימים (`sticky-notes`, `multi-select`, `collections`, `dashboard`, `global_search`, `html_preview`).
- אין הצעות לשיתוף קהילתי או לסוכני AI, בהתאם לבקשה.
- ההמלצה להתחלה: Sticky Notes בכל תצוגה + Bulk Diff – השילוב יוצר לולאת משוב מהירה על קוד בלי לצאת מהאפליקציה.
