# 🌱 רעיונות טריים לווב־אפליקציה (דצמבר 2025)

תאריך: 29/11/2025  \\
מיקוד: פיצ'רים ממוקדי משתמש שמבוססים על הסריקה של `webapp/` (templates, static, collections_ui.py, scripts/, config/).  \\
לא חופף למסמכים קיימים ב-`FEATURE_SUGGESTIONS/` ולא כולל שיתופי קהילה או סוכן AI לבוט.

---

## 🔎 צילום מצב קצר
- `templates/files.html` ו-`static/js/*` מציגים כמות גדולה של פילטרים, אך אין דרך לשמור מצבי עבודה.
- `dashboard.html` ו-`settings.html` מספקים דשבורד וסטטיסטיקות בסיסיות בלבד – אין מעקב אחרי "רשימת קריאה" או סשנים ממוקדים.
- קיים `config/error_signatures.yml` אך לא מוצג חיווי למשתמשים/אדמין בקבצים בעייתיים.
- תיקיית `scripts/` מלאה בכלי תחזוקה (cleanup tags, import snippets, migrate collections) שמריצים רק בטרמינל.
- `collections_ui.py` ו-`templates/collections.html` מנהלים אוספים כטבלאות – אין תצוגת Kanban או גרירה מהירה.
- `services/image_generator.py` + `config/image_settings.yaml` מציעים תשתית ליצירת תמונות קוד, אבל אין UI נגיש לכך.

---

## 📋 תקציר רעיונות
| # | רעיון | למה זה שווה | מאמץ מוערך |
|---|-------|-------------|-------------|
| 1 | Workspace Scenes | חילוף מהיר בין פילטרים/מצבי תצוגה חוזרים | בינוני |
| 2 | Workspace Shelf Upgrades | משדרג את \"שולחן העבודה\" הקיים לארגון חכם | בינוני |
| 3 | File Activity Heatmap | מדגיש קבצים פעילים/רדומים דרך הנתונים הקיימים | בינוני |
| 4 | Maintenance Console | הרצת סקריפטי תחזוקה דרך UI מאובטח | בינוני-גבוה |
| 5 | Collections Kanban View | גרירה בין אוספים וארגון חזותי | בינוני |
| 6 | CodeShot Presets | יצירת תמונות קוד בקליק אחד | נמוך-בינוני |

---

## 1. 🗂️ Workspace Scenes (מצבי עבודה שמורים)
**הבעיה:** דף `files.html` מלא בפילטרים, מצבי תצוגה והגדרות. משתמשים קופצים בין "ניקוי קוד", "סינון repo" ו"Power Mode" אבל צריכים להגדיר הכול מחדש בכל פעם.

**הפתרון:** לאפשר לשמור "Scene" – חבילה שמכילה קטגוריה, פילטרים, בחירות multi-select, `display_mode`, `sortOrder` ועוד. בלחיצה אחת נטען scene אחר (למשל "תיעוד לקריאה" או "ניקוי JS"), כולל התאמת המחלקות על `<body>`.

**איך לממש:**
- Backend: להרחיב את `ui_prefs` ב-`users` עם `workspace_scenes` (שם, אייקון, payload). Endpoint חדש: `GET/POST/DELETE /api/ui_prefs/scenes` (נשען על אותו Blueprint של שמירת העדפות).
- Frontend: מודול JS חדש (`static/js/workspace_scenes.js`) שפועל על `files.html`, קורא/שומר scenes ב-LocalStorage ובשרת. אינטגרציה עם `displayModeState` כדי להוסיף/להסיר קלאסים (`mode-focus` וכו').
- UI: רכיב mini-drawer מעל כפתורי הקטגוריות עם כרטיסיות Scene, כולל קיצור `Ctrl+Number` לטעינה מהירה (מעל קיצורי התצוגה).

**מדדי הצלחה:**
- ≥40% מהמשתמשים הפעילים שומרים לפחות Scene אחד.
- ירידה של 30% בזמן הממוצע בין החלפת הקטגוריות (מדיד דרך telemetry בצד לקוח).

---

## 2. 🧱 Workspace Shelf Upgrades (מצב שולחן העבודה הקיים)
**הבעיה:** ב-`files.html` כבר יש קיצור ל"שולחן עבודה" (Workspace) כחלק ממערכת האוספים, אך הוא מתפקד כרשימה שטוחה. קשה לראות באיזה שלב נמצא כל קובץ, אין קיצורי דרך, ואי אפשר לחבר את Focus Mode ישירות לשולחן העבודה.

**הפתרון:** להפוך את ה-Workspace הקיים ל"מדף" אינטראקטיבי:
- חלוקה לשלושה מצבים קבועים (למשל: "לבדיקה", "בתהליך", "הושלם") + תמיכה ביצירת עמודות מותאמות.
- טיימר Focus intégré: כשעוברים למצב פוקוס על קובץ שנמצא ב-Workspace, מוצג mini-widget שמתחיל מדידה ושומר את התוצאה על הפריט עצמו.
- Quick Actions: גרירת קובץ מלוח התוצאות ישירות ל-Workspace, קיצורי מקלדת (`Shift+W`) להוספה/הסרה, ותצוגת badge על הכרטיס שמראה כמה זמן הושקע בו.

**איך לממש:**
- DB: להרחיב את המסמך של ה-Workspace (כפי שמנוהל באוספים) עם שדות `workspace_state`, `focus_minutes`, `last_focus_at`. אין צורך באוסף חדש, רק הרחבה של הקיים.
- API: ב-`collections_api` קיימת כבר לוגיקה להוספה/הסרה. מוסיפים endpoints ייעודיים ל-Workspace: `POST /api/workspace/items`, `PUT /api/workspace/<item_id>/state`, וקריאה שמחזירה את הסיכום לטובת הטיימר.
- Frontend: מודול `static/js/collections.js` יכול לקבל מצב חדש של Board (בדומה לרעיון Kanban) אבל מוגבל ל-Workspace בלבד. המשך ישיר ל-`navigateToWorkspace()` שכבר קיים ב-`files.html`.

**מדדים:**
- לפחות 60% ממשתמשי Workspace מעדכנים את הסטטוס של פריט פעם בשבוע.
- זמן ממוצע להחלפת סטטוס יורד מתהליך של 3 קליקים לקיצור אחד (נמדד דרך telemetry).

---

## 3. 🔥 File Activity Heatmap
**הבעיה:** `dashboard.html` כבר מציג סטטיסטיקות ו-"פיד אחרון", אבל אין דרך להבין במהירות אילו קבצים זוכים להרבה פעילות ואילו הוזנחו. המשתמש צריך לעבור בין כמה כרטיסים כדי לקבל תמונת מצב.

**הפתרון:** להוסיף לוח Heatmap שמבוסס על הנתונים שכבר נאספים (`stats.recent_files`, `activity_timeline`). כל קובץ יקבל ניקוד פעילות (צפיות, עריכות, פתקים, שיתופים). נציג את החום הזה ב:
- כרטיס ייעודי בדשבורד שמציג טבלה/מטריצה קטנה (Top Active vs. Cold Files).
- Badge קטן על כרטיסי הקבצים ב-`files.html`/`Power Mode` עם אינדיקטור פעילות (🟢 פעיל, 🟡 פושר, ⚫ הוזנח).
- פילטר חדש "הצג רק קבצים שלא נגעתי בהם X ימים" כדי לעודד ריענון.

**איך לממש:**
- Backend: cron job (או reuse של `scripts/run_log_aggregator.py`) שרץ פעם בשעה, סופר אינטראקציות מתוך `activity_timeline`/`notes`/`bookmarks` ושומר טבלה `file_activity_cache` (user_id, file_name, score, last_event). ה-API יחשוף `GET /api/files/activity-summary`.
- Frontend: ב-`dashboard.html` מוסיפים קומפוננט חדש עם Chart.js (כבר נטען ב-CDN במקומות אחרים) וב-`files.html` ממשיכים להשתמש ב-badges קיימים כדי לא להעמיס HTML חדש.
- נגישות: לכל Badge תהיה תווית `aria-label` שמסבירה מתי עבר האירוע האחרון.

**מדדים:**
- ≥50% ממשתמשי הדשבורד פותחים את heatmap לפחות פעם ביום (נמדד באירוע JS).
- ירידה של 20% במספר הקבצים שלא נפתחו יותר מחודש – סימן שה-heatmap מעודד ריענון.

---

## 4. 🛠️ Maintenance Console (UI לכלי סקריפט)
**הבעיה:** אדמין נדרש להריץ ידנית סקריפטים כגון `scripts/cleanup_repo_tags.py`, `import_snippets_from_markdown.py`, `migrate_workspace_collections.py`. אין תיעוד להרצות, אין לוגים באפליקציה, ומסוכן להריץ על פרודקשן.

**הפתרון:** להפוך את קטע "כלי אדמין" ב-`settings.html` לממשק תחזוקה:
- כפתורים עם טפסים (פרמטרים בסיסיים) להרצה.
- תור משימות (קל לעטוף ב-`RQ`/`Celery`) שמריץ את הסקריפטים בתוך הסביבה הקיימת ומזרים את ה-output חזרה כ-log (SSE/WebSocket).
- הרשאות: רק `is_admin`. כל פעולה דורשת אישור כפול + הצגת dry-run.

**איך לממש:**
- Blueprint חדש `maintenance_bp` (`/api/maintenance`) עם פעולות: `cleanup_repo_tags`, `import_snippets`, `migrate_collections`, `run_log_aggregator`. כל פעולה מריצה פקודה מודולרית (אפשר לייבא את הסקריפט כמודול ולהחזיק פונקציית `run_from_ui(**kwargs)`).
- Frontend: כרטיסיות חדשות בתוך `settings.html` > כלי אדמין, עם טופס + ניהול סטטוס (Pending / Running / Done / Failed).
- Observability: שימוש ב-`emit_event`/`emit_internal_alert` (קיים בסקריפטים) כדי לתעד כל טריגר.

**מדדים:**
- 100% מהרצות הסקריפטים מתועדות בטבלת audit.
- ירידה ב-tickets מהצוות בנושא "אין לי גישה להריץ script".

---

## 5. 🧩 Collections Kanban View
**הבעיה:** מסך `collections.html` (rendered דרך `collections_ui.py`) מציג רשימות ארוכות. העברת קובץ מאוסף אחד לאחר דורשת מודל או חיפוש ידני. אין visual grouping.

**הפתרון:** מצב תצוגה חדש ל-Collections:
- כל אוסף הוא עמודה, הקבצים הם כרטיסים הניתנים לגרירה (Drag & Drop) בין עמודות.
- כרטיס מציג אייקון, שפה, תגיות, Badge של פתקים/סימניות.
- תמיכה ב"חוקים חכמים": קבצים שמגיעים מאוסף חכם יסומנו כ-ghost card שאי אפשר לגרור (מתועד).

**איך לממש:**
- API קיים (`collections_api`) מספק `add/remove`. יש להוסיף Endpoint `POST /api/collections/move` שמבצע remove+add אטומי.
- Frontend: מודול JS חדש (`static/js/collections_board.js`) שמשתמש ב-HTML templates קיימים (`collections.html`). יתכן שימוש ב-HTML5 Drag Events ללא ספרייה.
- UI Toggle: כפתור "Board" בפינה העליונה של העמוד. זיכרון במקומי (localStorage) כדי לזכור את המצב.

**מדדים:**
- 70% פחות קליקים בממוצע להעברת קובץ בין אוספים (Telemetry).
- שביעות רצון משתמשים (סקר קצר) ≥4.5/5 לגבי ארגון אוספים.

---

## 6. 🖼️ CodeShot Presets (תמונות קוד בקליק)
**הבעיה:** למרות שקיים שירות `services/image_generator.py` והגדרות ב-`config/image_settings.yaml`, אין ממשק מהיר להפוך קוד לתמונה לשיתוף בסליידים/טלגרם. משתמשים עושים צילום מסך ידני.

**הפתרון:**
- להוסיף כפתור "ייצא תמונה" ב-`view_file.html` ובתצוגת Markdown. לחיצה פותחת מודל עם Presets ("Slack", "מצגת", "Dark Tweet").
- המשתמש בוחר preset → השרת יוצר משימה (`POST /api/code-image`) שמריצה את `CodeImageGenerator` עם theme וגודל תואמים להגדרות בקובץ הקונפיג.
- לאחר יצירה – הצגת preview ושמירת history (אפשר להחזיק ב-`tmp/` עם TTL ולהציע "העתק URL"/"הורד").

**איך לממש:**
- Backend: Blueprint חדש `code_image_bp` או הרחבה ל-`code_service`. שימוש ב-ThreadPool שכבר קיים במחלקה (ראה `ThreadPoolExecutor` ב-`image_generator.py`).
- Frontend: מודול קטן ב-`static/js/card-preview.js` שמגיב ללחיצה ופותח מודל (אפשר reuse מרכיב ההעלאה). אפשר להוסיף גם קיצור `Shift+I`.
- הגדרות: מיפוי preset→theme→width נשען על `config/image_settings.yaml` כדי לשמור אחידות.

**מדדים:**
- ≥30% מהמשתמשים הפעילים משתפים לפחות תמונה אחת בשבוע.
- מדד NPS למשתמשי מצגות/בלוגרים עולה (מדידה איכותית).

---

## ✔️ סיכום והמלצות
1. להתחיל ב-Workspace Scenes ו-Reading Queue – שינויי UI בלבד עם ערך מיידי.
2. במקביל להרים את Error Badges + Maintenance Console עבור אדמין (מקטין סיכון תקלות).
3. בהמשך להוסיף Collections Kanban ו-CodeShot Presets כתוספי חוויית משתמש.

כך נשיג גם יעילות יומיומית למשתמש הקצה וגם כלים טובים יותר לצוות שמתחזק את המערכת.