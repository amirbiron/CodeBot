# 💡 רעיונות חדשים ל־WebApp (דצמבר 2025)

## למה הכנתי את המסמך?
- עברתי על עצי הקוד הרלוונטיים: `webapp/templates/`, `webapp/static/`, `webapp/static_build/`, `webapp/FEATURE_SUGGESTIONS/` וגם קבצי הקונפיג ב-`/config` יחד עם המחלקה `webapp/config_radar.py`.
- מיפיתי את הסקריפטים המשמעותיים: `static/js/editor-manager.js`, `static/js/sticky-notes.js`, `static/js/global_search.js`, את באנדל ה-Markdown (`static_build/md-preview-entry.js`) ואת ה-templates הגדולים כגון `dashboard.html`, `md_preview.html`, `settings.html`, `admin_observability.html` ו-`observability_replay.html`.
- חיפשתי כפילויות במסמכי ההצעות הקיימים בתיקיית `FEATURE_SUGGESTIONS` כדי להבטיח שהרעיונות כאן אינם מכסים שוב נושאים שכבר הוגדרו (לדוגמה: Floating TOC, Quick Access Menu, Dark Mode, Smart Search).
- הערה קטנה: לא מצאתי קבצים בשם `editor.js` או `shortcuts.js`; בפועל ניהול העורך נעשה דרך `static/js/editor-manager.js` וקיצורי דרך מפוזרים בקבצי JS אחרים.

> המיקוד בכל סעיף הוא ערך מיידי למשתמשים קיימים, ללא פיצ'רים של "קבוצות קהילה" או "סוכן AI" כפי שהתבקשה הגבלה.

---

## 1. מצב "Split Workspace" לעריכה ותצוגה סימולטנית
**הכאב היום:** ב-`edit_file.html` ובמיוחד בקבצי Markdown צריך לקפוץ בין עריכה לתצוגה (`/md/<id>`), מה שמקטין את הפידבק המיידי ופוגע בריכוז.

**מה מציעים:**
- כפתור "פצל מסך" בחלק העליון של כרטיס העריכה שמאפשר שתי פריסות:
  1. עורך + תצוגת Markdown חיה (iframe מינימלי של `md_preview.html`).
  2. עורך + קובץ שני (למשל קובץ הגדרות או טסט) בסשן CodeMirror נוסף, לצורך השוואה צד-לצד.
- לכל פריסה יהיה זיכרון למשתמש (נשמר דרך `window.editorManager.savePreference`).

**איך לממש (בקווים כללים):**
1. להרחיב את `templates/edit_file.html` עם toolbar שמכיל toggles לפיצול, בחירה בין "Preview" ל"File", וכן חיפוש מהיר של קובץ שני (אפשר למחזר את לוגיקת `global_search.js`).
2. להוסיף מחלקה חדשה ב-`static/js/editor-manager.js` (למשל `SplitWorkspaceController`) שתנהל אינסטנציה שנייה של CodeMirror או iframe, כולל סנכרון גלילה בין הפאנלים.
3. ב-`static_build/md-preview-entry.js` להוסיף API שמרנדר markdown ללא ה-header של `base.html` (כדי שה-iframe יהיה קליל). אפשר לחשוף פונקציה גלובלית `window.renderMarkdownLite` שתיקרא מהעורך במקום בקשה לרשת כשעובדים אופליין.
4. להוסיף CSS Grid ייעודי ב-`static/css` (או בתוך `edit_file.html`) שמבוסס על מחלקות `split-mode`/`single-mode`.
5. להזרים את בחירת הפריסה כערך נוסף ב-`/api/ui_prefs` כדי שהמשתמש יקבל את אותו מצב בכל מכשיר.

**מאמץ / אימפקט:** בינוני-גבוה (כשבועיים) / גבוה — חוסך קפיצות בין טאבים ומאפשר Diff ידני ללא מסך נוסף.

**מדדי הצלחה:** ירידה בכמות הניווטים לעמוד `md_preview` אחרי עריכה, עלייה בזמן שהייה בעמוד עריכה, ומשוב חיובי על חוויית Markdown.

---

## 2. Sticky Notes Flowboard – ניהול פתקים כמשימות
**הכאב היום:** `static/js/sticky-notes.js` מספק פקד עשיר בדף Markdown, אבל ברמת המערכת אין מבט אחד על כל הפתקים/התזכורות; בלוח הבקרה (`dashboard.html`) מוצג רק snapshot שטוח.

**מה מציעים:**
- לוח Kanban קטן בדף הבית ובמובייל שמחלק פתקים לקטגוריות: "בסקירה", "מחכים לתזכורת", "נסגרו".
- חלון צד ב-`md_preview.html` שמציג את כל הפתקים של הקובץ עם חיפוש, קיבוץ לפי כותרת Markdown ואפשרות לסמן "בוצע".
- סנכרון עם התראות ה-Push שכבר קיימות ב-`settings.html` (כפתורי `pushEnableBtn`/`pushTestBtn`).

**איך לממש:**
1. להוסיף שדות סטטוס ותאריך יעד ל-API הקיים (`/api/sticky-notes/<file_id>`) לצד אחסון קאש ב-Redis (קיים כבר בתשתית) לצורך טעינה מהירה של "Flowboard".
2. ליצור endpoint מסכם חדש (למשל `/api/sticky-notes/summary`) שמחזיר נתונים עבור הדשבורד — כמה פתקים בכל סטטוס, קישורים לקבצים, ושרשרת התזכורות הקרובה.
3. להרחיב את רכיב ה-Notes ב-`dashboard.html` כך שיציג עמודות, drag & drop (אפשר להשתמש ב-SortableJS שמוטען דרך CDN כמו שאר הספריות), וחיבור ישיר לקובץ (`/file/<id>`).
4. ב-`static/js/sticky-notes.js` להוסיף API `markAsDone` ויכולת לייצא פתק כ-task ל-activity timeline (כדי שיופיע ב-`activity_tracker`).
5. להוסיף עוקב ב-`global_search.js`: כאשר מציגים תוצאות, לציין badge קטן אם לקובץ יש פתקים פתוחים.

**מאמץ / אימפקט:** בינוני (כשבוע) / גבוה — מחליף TODO-ים חיצוניים ומפיק ערך מידי למשתמש ששומר הרבה פתקים.

**מדדי הצלחה:** מספר פתקים שנסגרים דרך הלוח החדש, זמן תגובה לפתקים עם תזכורות, ופידבק משתמשים על ריכוז המשימות במקום אחד.

---

## 3. Config Radar Control Room
**המצב הקיים:** ב-`settings.html` יש קלף יפהפה של "Config Radar" אך הוא מציג placeholder בלבד, למרות ש-`config_radar.py` כבר יודע לטעון/לאמת את `config/alerts.yml`, `config/error_signatures.yml`, `config/image_settings.yaml`.

**מה מציעים:**
- להפוך את הקלף למסך ניהול מלא שמציג snapshot חי, השוואה לארבע ההרצות האחרונות, וממשק פעולה (כפתורי "פתח בקובץ", "שמור zip גרסה אחרונה").
- הוספת "drift alerts" – אם הקובץ השתנה ב-Git אך לא עבר Validate.

**איך לממש:**
1. ליצור שכבת שירות (`services/config_radar_service.py`) שמסתמכת על `config_radar.build_config_radar_snapshot()` ושומרת את הממצאים במסמך Mongo (כולל hash של התוכן). להריץ אותה ב-cron או ידנית דרך כפתור "Validate".
2. להוסיף נתיב API מאובטח `/admin/api/config-radar` שמחזיר JSON עשיר: סטטוס כל קובץ, בעיות, מי העדכן האחרון, והפרש מול snapshot קודם.
3. ב-`settings.html` (חלק האדמין) להחליף את הטקסט "בקרוב" ב-tabs אמיתיים עם טבלאות: רשימת Issues, רשימת קטגוריות Error Signatures, ונקודות השקה ל-`image_settings`.
4. לכתוב קובץ JS קטן (`static/js/config-radar.js`) שמאזין ללחיצות על הכפתורים, מפעיל spinner, ומציג diff מינימלי (אפשר להשתמש ב-`diff2html` מ-CDN כי ממילא אנחנו נטולי בנדלר).
5. להרחיב את `config_radar.py` כך שיחזיר גם "פעולות מומלצות" (למשל "הוסף immediate category"), כדי להקל על השילוב בדשבורד.

**מאמץ / אימפקט:** בינוני / גבוה — סוף סוף מנגישים קבצי קונפיג רגישים בממשק אחד ולא מפספסים שגיאות YAML.

**מדדי הצלחה:** ירידה במספר התקלות שנובעות מקבצי קונפיג, זמן מענה ממוצע לבעיה שמזוהה ב-Radar, ושימוש תדיר בכפתור ה-Validate.

---

## 4. Incident Clips & Bookmarks
**הכאב היום:** `admin_observability.html` ו-`observability_replay.html` מספקים נתונים רבים, אבל כאשר מוצאים "רגע" מעניין (spike, deploy, כשל), אין דרך לשמור אותו כמקבץ מתועד ולשתף אותו הלאה.

**מה מציעים:**
- לאפשר סימון קטע זמן ב-Incident Replay (Start/End) עם הערה קצרה; הקטע נשמר כ"Clip" שניתן לשתף בלינק ייעודי או לצרף לדשבורד.
- להציג לוח "Incident Clips" בדף הדשבורד האדמיני עם פילטר לפי חומרה/שירות.

**איך לממש:**
1. להוסיף ל-`observability_replay.html` פאנל קטן שמציג טיימליין בזמן אמת וכולל כפתורים "Set Start" / "Set End" / "Add Note" / "Save Clip". לשמירה לקרוא ל-`/admin/api/incidents/clips` (endpoint חדש) ששומר ב-Mongo את טווח הזמן, הסוג, והשדות ההקשריים (request_id, service, deployment sha).
2. להרחיב את ה-JS של `admin_observability.html` כך שיכלול קריאה ל-Clip API ויציג רשימה מצומצמת + כפתור "Replay" שמדפדף ל-`observability_replay.html?clip=<id>`.
3. להשתמש בנתוני `config/alerts.yml` כדי לסווג כל Clip לפי קטגוריית alert (critical/anomaly וכו').
4. להוסיף קישור לכל Clip ל-export Markdown שמייצר תקציר: סיבת האירוע, גרף PNG (למשל יצוא Chart.js דרך `toBase64Image`), ציר הזמן והערות.
5. ליצור אינטגרציה עם `activity_tracker.py`: כל Clip חדש מזין אירוע "Incident clip saved" שיופיע בפיד בדשבורד הראשי (כבר יש כרטיס "פיד אחרון").

**מאמץ / אימפקט:** בינוני / גבוה — משפר את חוויית on-call ומאפשר לשמור ידע בצורה מהירה.

**מדדי הצלחה:** מספר Clips שנשמרו לשבוע, חיסכון בזמן חקירה (מדווח ע"י הצוות), וכמות צפיות בדשבורד Clip חדש.

---

## 5. Session Warm Start (Workspace Scenes)
**הכאב היום:** למרות שיש `ui_prefs` לעורך והצעת "שמירת פילטרים" במסמך אחר, עדיין אין דרך לחזור לסשן שלם (קובץ פתוח + סינונים + מצב Markdown + Sticky Notes) ברגע שמתחברים שוב.

**מה מציעים:**
- מנגנון "Scenes" ששומר נקודת זמן במערכת (קובץ פעיל, scroll במקדש Markdown, פילטרים ב-`files`, פריסת Multi-Select, מצב Dark/Dim, notes פתוחים) ומאפשר לשחזר אותה מהמסך הראשי או מהודעת Telegram.

**איך לממש:**
1. ליצור רכיב JS קטן (`static/js/session-recorder.js`) שמאזין לאירועים מהקבצים המרכזיים (`editor-manager`, `global_search`, `collections.js`, `multi-select.js`, `sticky-notes.js`) ושומר snapshot ב-IndexedDB + שולח אותו ל-`/api/ui_sessions` (endpoint חדש עם rate-limit).
2. להרחיב את backend (`services/code_service.py` או מודול ייעודי) שיישמור עד 5 Scenes אחרונים למשתמש עם checksum והקשר (לדוגמה "Markdown review of README").
3. בדף `dashboard.html` להוסיף קומפוננטה "המשך מאיפה שהפסקתי" שמראה את הסצנה האחרונה, עם כפתור "שחזר"; במובייל להציג זאת בסיידר קיים.
4. בעת שחזור: לפתוח את הקובץ בעורך, להחיל את בחירת Theme (`data-theme` ב-`base.html`), להדליק Split Workspace אם היה, להפעיל את אותו פילטר ב-`/files`, ולגלול ל-heading במידה ומדובר ב-`md_preview` (אפשר להשתמש ב-anchor כבר קיים בקובץ).
5. לחבר את זה ל-activity timeline (אירוע "Scene restored") כדי שנוכל לנתח שימוש.

**מאמץ / אימפקט:** גבוה (2–3 שבועות, כולל אחסון בצד שרת) / גבוה — חוסך למשתמשים זמן יקר בחזרה להקשר, במיוחד כשעובדים במקביל דרך הטלגרם והווב.

**מדדי הצלחה:** אחוז המשתמשים שלוחצים "שחזר", ירידה בכמות הפעולות הראשונות (חיפוש/פתיחת קובץ) אחרי התחברות, ו-NPS איכותני לגבי "המשך עבודה".

---

## סיכום קצר
- כל רעיון כאן נשען על רכיבים קיימים בקוד ומוסיף שכבה שימושית ולא רק קוסמטיקה.
- אפשר להתחיל בקרוס-קאט קטן (למשל Flowboard שמצריך backend קל ו-UI קצר), ולהתקדם לפיצ'רים עמוקים יותר (Config Control Room / Warm Start) בהתאם ל-capacity.
- בסיום כל מימוש כדאי לעדכן את [CodeBot Docs](https://amirbiron.github.io/CodeBot/) כך שיהיה תיעוד רשמי, ולוודא שה-templates החדשים נשמרים בהתאם לכללי ה-HTML/Jinja (ללא Prettier על `webapp/templates`).
