# רעיונות WebApp יעילים – נובמבר 2025

תאריך: 2025-11-15  
מקורות: `webapp/app.py`, כל קובצי `webapp/templates/`, `webapp/static/js/`, `webapp/static/css/`, `webapp/static/manifest.json`, `webapp/static/sw.js`, ספריית `webapp/FEATURE_SUGGESTIONS`, ועוד.  
הערה: בתיקיית `webapp/` אין כיום תתי-תיקיות בשם `components/`, `scripts/`, `routes/` או `config/`, לכן עברתי על התיקים המקבילים (templates = components, `app.py` = routes, `static/js` = scripts, `config.py` ברוט). כמו כן בדקתי את כל מסמכי `FEATURE_SUGGESTIONS` הקיימים כדי להימנע מכפילויות.

המיקוד: שיפורים שמייצרים ערך מיידי למשתמשי CodeBot ללא פיצ'רי קהילה או "סוכני AI".

---

## TL;DR
- Split Compose Mode: עריכה + תצוגה חיה באותו מסך לכל קובץ.
- Workspace Snapshots: שמירת סדרי עבודה (פילטרים, קבצים פתוחים, בחירות מרובות) לשחזור מהיר.
- Anchor Mini-Map: מפת גלילה אנכית שמציגה סימניות, Sticky Notes ותוצאות חיפוש בקוד.
- Bulk Metadata Studio: סטודיו לעריכת שם/שפה/תגיות/Repo לקבוצות קבצים בבת אחת.
- HTML Preview Bundles: תצוגה שמצרפת נכסים (CSS/JS) מקבצים אחרים בלי להוציא מהארגז החולי הקיים.
- Offline Reading Kit: שדרוג ה-Service Worker להחזקת "Last Known Good" של קבצים וצפייני Markdown.
- Guided Review Timeline: ציר זמן שמחבר בין סימניות, Sticky Notes ותזכורות כדי לעבור על קובץ לפי הקשר.
- Upload Guardrails: צ'ק-ליסט בזמן העלאה שמזהה בעיות סינטקס, מטא-דאטה חסר וחשיפת סודות לפני שמירה.

---

## טבלת עדיפויות (הערכה ראשונית)

| # | רעיון | ערך למשתמש | מאמץ | Touchpoints עיקריים |
|---|--------|--------------|-------|----------------------|
| 1 | Split Compose Mode | גבוה – חוסך מעבר בין דפים, מביא בהירות מיידית | בינוני | `templates/edit_file.html`, `templates/md_preview.html`, `static/js/editor-manager.js` |
| 2 | Workspace Snapshots | גבוה – שחזור סביבת עבודה נפוצה בלחיצה אחת | בינוני | `templates/files.html`, `static/js/multi-select.js`, `static/js/global_search.js`, API חדש | 
| 3 | Anchor Mini-Map | בינוני-גבוה – ניווט מהיר בקבצים ארוכים | בינוני | `templates/view_file.html`, `static/js/bookmarks.js`, `static/css/*.css` |
| 4 | Bulk Metadata Studio | גבוה – מפחית עבודת יד על עשרות קבצים | בינוני-גבוה | `templates/files.html`, `static/js/bulk-actions.js`, `app.py` (bulk endpoints) |
| 5 | HTML Preview Bundles | בינוני – בנייה אמינה של דפי HTML מרובי נכסים | בינוני | `templates/html_preview.html`, `community_library_ui.py`, API חדש להזרקת נכסים |
| 6 | Offline Reading Kit | בינוני – גישה לקוד אחרון גם בלי רשת | בינוני | `static/sw.js`, `app.py` (manifest/versioning), `static/js/card-preview.js` |
| 7 | Guided Review Timeline | בינוני – סקירות קוד עקביות עם סדר ברור | בינוני | `static/js/bookmarks.js`, `static/js/sticky-notes.js`, `templates/view_file.html`, endpoints קיימים של סימניות/פתקים |
| 8 | Upload Guardrails | גבוה – מונע טעויות נפוצות בזמן העלאה | נמוך-בינוני | `templates/upload.html`, `app.py` (upload route), `code_processor.py` (ולידציות קיימות) |

---

## פירוט הפיצ'רים

### 1. Split Compose Mode (עריכה + תצוגה באותו מסך)
- **הצורך**: כיום משתמשים מחליפים בין `edit_file.html`, `md_preview.html` ו-`html_preview.html` כדי לראות תוצאה. זה שובר את ה-flow במיוחד ב-Telegram Mini App.
- **הצעה**: להוסיף בלחיצת כפתור חלוקה לשני טורים: עורך `CodeMirror` (כבר נטען דרך `static/js/editor-manager.js`) ובצד השני iframe תצוגה.* עבור Markdown נשתמש ב-renderer הקיים (`/md/<id>`), עבור HTML נשתמש ב-`/html/<id>` עם sandbox. קבצי קוד רגילים יציגו diff מול הגרסה האחרונה או render של Pygments.
- **כיוון טכני**:
  - יצירת API קל `/api/preview/live` שמקבל טקסט ומחזיר HTML בטוח (render markdown-it / pygments בצד שרת).
  - שימוש ב-Web Workers כדי לבצע debounce ולמנוע שליחה בכל הקשה.
  - התאמות RTL ב-`static/css/` כדי שהספליט יישאר רספונסיבי בטלגרם.
  - תמיכת keyboard shortcut (Ctrl+Shift+Enter לפתיחת מצב כפול).

### 2. Workspace Snapshots (סדרי עבודה נשמרים)
- **הצורך**: `templates/files.html` מספקת פילטרים, חיפוש גלובלי ו-Multi Select (`static/js/multi-select.js`), אבל לאחר רענון הכל מתאפס. משתמשים חוזרים שוב ושוב על אותם צירופים.
- **הצעה**: כפתור "שמור סביבה" ששומר לשרת (או לפחות ל-Redis) את: ערך החיפוש, שפות מסומנות, קטגוריה, רשימת קבצים פתוחים, בחירות מרובות ומצב פאנל סימניות. לחיצה על Snapshot פותחת מחדש את כל ההקשר (כולל כרטיסי preview שנפתחו דרך `card-preview.js`).
- **כיוון טכני**:
  - Endpoint חדש `/api/workspaces` עם CRUD פשוט ואחסון ב-Mongo (collection קטנה per user).
  - ב-Frontend להשתמש ב-`sessionStorage` כ-cache ולתמוך באייקון pin ליד כל snapshot.
  - אפשרות Export/Import JSON קל עבור משתמשים שרוצים לשמור snapshot חיצוני.

### 3. Anchor Mini-Map (מפת קוד אנכית)
- **הצורך**: בקבצים ארוכים קשה לראות איפה נמצאות סימניות (`static/js/bookmarks.js`) או תווים שסומנו בחיפוש. אין מינימפ כמו בכלים מודרניים.
- **הצעה**: פס אנכי דק בצד ימין של `view_file.html` שמראה נקודות צבע: צהוב = סימניה, כחול = תוצאת חיפוש, ורוד = Sticky Note (כשנרחיב אותו בקוד). לחיצה על הנקודה מקפיצה לשורה.
- **כיוון טכני**:
  - שימוש ב-`IntersectionObserver` כדי לסנכרן את המפה ל-scroll.
  - חשיפה של API קטן מ-`BookmarkManager` שמחזיר רשימת line numbers כדי לייצר UI.
  - CSS קל (Gradient + absolute positioning) וללא ספריות חדשות.

### 4. Bulk Metadata Studio
- **הצורך**: ה-Toolbar הקיים (`bulk-actions.js`) מטפל במועדפים/תגיות, אך אי אפשר לשנות שפה, repo tags, רמות אבטחה או custom fields בבת אחת.
- **הצעה**: לפתוח Modal עם טופס מרוכז: שינוי Language (כולל "זהה לפי סיומת"), הוספת/הסרת תגיות, עדכון `repo:` ו-`path:`, סימון "סודי" שמפעיל הגבלות שיתוף, והחלת תבנית תיאור על עשרות קבצים.
- **כיוון טכני**:
  - Endpoint חדש `/api/files/bulk-metadata` שמבצע ולידציה דרך `code_processor.py`/`database/models.py`.
  - חלוקה לקטגוריות בטופס (tabs) כדי לשמור על פשטות במובייל.
  - שימוש ב-optimistic UI: עדכון כרטיסים במסך עוד לפני שהבקשה חוזרת (עם rollback במקרה כישלון).

### 5. HTML Preview Bundles
- **הצורך**: `html_preview.html` מריץ קובץ יחיד בסנדבוקס. כאשר קובץ תלוי בקובצי CSS/JS אחרים במערכת, צריך להוריד ידנית או להדביק inline.
- **הצעה**: Modal שמאפשר לבחור קבצי CSS/JS שכבר שמורים בחשבון ולהוסיף אותם כ-resources זמניים ל-iframe. ניתן גם להגדיר data JSON כתשובה ל-fetch (mock).
- **כיוון טכני**:
  - Endpoint `/api/html-preview/bundle` שמרכיב חבילת HTML+Assets וקושר אותה עם token זמני (נמחק תוך X דקות).
  - תמיכה בפרופילים מוכנים ("Preview Tailwind", "Preview Bootstrap") כדי לאפשר למשתמש לבחור סט קבוע.
  - שמירת רשימת הנכסים שנבחרו ב-LocalStorage להמשך עבודה.

### 6. Offline Reading Kit
- **הצורך**: `static/sw.js` מטפל רק בהתראות Sticky Notes. אין cache לסטטיקה או לקבצים שנפתחו, כך שבחוסר רשת המשתמש נתקע.
- **הצעה**: לשדרג את ה-Service Worker שיישמור את 10 הקבצים האחרונים שנצפו (`/file/<id>`, `/md/<id>`, `/html/<id>`) + ה-`static/css`/`js` הרלוונטיים. במצב offline מוצגת הבקשה האחרונה עם חיווי ברור שזוהי גרסה קודמת.
- **כיוון טכני**:
  - Cache Storage עם strategy של Stale-While-Revalidate עבור סטטיקה, ו-Cache First עם TTL של שעות בודדות עבור קבצים.
  - שימוש ב-`_STATIC_VERSION` מ-`app.py` כדי לנקות cache ישן אוטומטית.
  - פקודת `navigator.onLine` להצגת badge "Offline" בפינה.

### 7. Guided Review Timeline
- **הצורך**: יש סימניות צבעוניות והודעות Sticky Notes, אך אין דרך לעבור על קובץ בסדר קבוע (Useful ל-Code Review עצמי).
- **הצעה**: בצד `view_file.html` יוצג ציר זמן שממזג: סימניות עם הערות (`bookmarks.js`), Sticky Notes (`sticky-notes.js`) ותזכורות עתידיות (מגיעות מהפוש). המשתמש לוחץ Next/Prev ועובר בין המוקדים לפי סדר עדיפות שהגדיר (לדוגמה: פתקים דחופים קודם).
- **כיוון טכני**:
  - Endpoint `/api/review-plan/<file_id>` שמחזיר את כל העצמים עם timestamp/priority.
  - UI מבוסס `aria-live` שיספר מה המוקד הבא, לרבות שילוב מקלדת (Alt+J/K למעבר).
  - אפשרות "סמן כהושלם" כדי להוריד אלמנט מהזרימה.

### 8. Upload Guardrails
- **הצורך**: טופס `upload.html` לא מזהיר מפני בעיות כמו JSON שבור, סודות בתוכן או קבצים גדולים מדי.
- **הצעה**: לפני שליחה מריצים Valdiation קל בצד הלקוח (לפי language שנבחר) ומציגים צ'ק-ליסט: ✅ שם קובץ, ✅ שפה, ⚠️ חשד ל-API key. אפשר גם להציע תיאור אוטומטי (מתוך השורות הראשונות) ושיוך תגיות נפוצות.
- **כיוון טכני**:
  - הוספת worker קל ב-JS שמריץ בדיקות (JSON.parse, YAML parser מינימלי, regex ל-secrets).
  - שימוש בפונקציית `normalize_code` בשרת כדי לאכוף אותו דבר גם בצד שרת.
  - הצעה לשמור כתבנית עם כפתור "הפוך לברירת מחדל".

---

## צעדים מומלצים
1. לאשר את Split Compose Mode + Upload Guardrails (Quick wins, אפקט משתמשי תחזוקה מידי).
2. להתחיל ב-Workspace Snapshots כדי ללמוד את דפוסי השימוש ולוודא שגם Anchor Mini-Map וגיידד ריוויו יישארו קלים לאימוץ.
3. לבדוק את ההשלכות על אחסון (Snapshots + Offline Cache) ולהגדיר שמירה פר משתמש כדי להימנע מניפוח DB.

---

מסמך זה מחליף גרסאות קודמות של `webapp_ideas.md` ומוסיף רק רעיונות שלא הופיעו ב-`NEW_FEATURE_SUGGESTIONS.md`, `webapp_improvement_ideas.md` או במדריכי היישום הייעודיים האחרים בתיקיית `webapp/FEATURE_SUGGESTIONS/`.
