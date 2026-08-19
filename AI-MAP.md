# מפת התיעוד לסוכני AI

<!-- קובץ זה נוצר אוטומטית על ידי scripts/generate_ai_map.py — אל תערכו ידנית; עריכה תידרס. -->

שורה לכל עמוד ידני באתר התיעוד: נתיב, כותרת ותקציר מהפסקה הראשונה. ההיררכיה נגזרת מה-toctree. עמודי פיגום של autodoc (ללא פרוזה) מסוננים — התוכן שלהם נוצר רק בזמן בנייה; לחתימות קראו את הקוד עצמו.

## למפתחים ולסוכני AI

- `docs/quickstart-ai.rst` — **התחלה מהירה - סוכני AI**: מסמך זה נועד לאפשר לסוכן AI להתחיל לעבוד על הריפו במהירות ובבטחה, בהתאם למדיניות הפרויקט.
- `docs/quickstart.rst` — **התחלה מהירה - מפתחים**: שלושה צעדים כדי להריץ מקומית במהירות.
- `docs/quickstart-contrib.rst` — **Quickstart לתרומה**: דף קצר שמאפשר להתחיל לתרום במהירות ובבטחה.
- `docs/ai-guidelines.rst` — **הנחיות מלאות לסוכני AI**: השתמשו בכלים המובנים
- `docs/agents/rate-limiting.md` — **🚦 מערכת Rate Limiting לסוכני AI ולווב**: מטרה: להסביר איך מפעילים ומנטרים Rate Limiting בבוט ובווב, עם דגש על Shadow Mode, ניטור וקונפיג.
- `docs/doc-authoring.rst` — **Doc Authoring Guide (Sphinx/RTD)**
- `docs/style-glossary.rst` — **Style & Naming Glossary**
- `docs/versioning-stable-anchors.rst` — **Versioning & Stable Anchors**
- `docs/whats-new.rst` — **What's New**: קישורים ל‑Issues רלוונטיים: `#1198`, `#1239`.
- `docs/architecture.rst` — **ארכיטקטורה**: המערכת מורכבת מבוט Telegram, שכבת שירותים (services), שכבת נתונים (MongoDB) ואפליקציית Web. הזרימה העיקרית: Handlers → Services → Database.
  - `docs/architecture/clean-architecture.rst` — **Clean Architecture ב-src**: ארכיטקטורה זו מפרידה בין לוגיקה עסקית, תזמור יישומי ותשתיות כך שניתן לבדוק יחידות קוד בנפרד, להחליף מקורות נתונים בלי לשבור את שאר המערכת ולרוץ גם בסביבות ללא MongoDB.
- `docs/contributing.rst` — **מדריך תרומה**: לתת מסלול ברור לתרומות קוד, עם דגש על סוכני AI ו-CI.
- `docs/branch-protection-and-pr-rules.rst` — **Branch Protection & PR Rules**: לרכז נהלים ברורים להגנה על ענפים (Branch Protection) ולחוקי PR בפרויקט.

## מדריכים בסיסיים

- `docs/installation.rst` — **התקנה והגדרה**: דף זה מכיל הוראות התקנה מפורטות עבור Code Keeper Bot.
- `docs/configuration.rst` — **Rate Limiting**: בעת ביצוע קריאות א-סינכרוניות השתמשו ב‑http_async המספק aiohttp.ClientSession משותף עם הגדרות מ‑ENV.
- `docs/environment-variables.rst` — **משתני סביבה - רפרנס**: הערה: הקפידו להעניק הרשאות מינימליות בלבד. לפרטים נוספים ראו integrations.
- `docs/performance-bible.md` — **🚀 The Performance Bible: CodeKeeper Optimization Guide**: המדריך הזה נכתב לאחר ה-Refactor הגדול של דצמבר 2025, שבו הורדנו את ה-p95 של המערכת מ-1.8 שניות ל-200ms. אלו העקרונות שחייבים להישמר
- `docs/performance-scaling.rst` — **ביצועים והרחבה (Performance & Scaling)**: בדקו לוגים ומדדים לאחר עדכון ערכי Pool/Timeout
- `docs/performance-sticky-notes.rst` — **Sticky Notes Warmup – פתרון ביצועים משולב**: מבצע "Sticky Notes Warmup" מחולק לשני נדבכים משלימים: העלאת timeout מידית (מוכחת בשטח) וחימום אינדקסים לפני שה-process מקבל תעבורה (שיפור קוד שעדיין נבחן). המסמך מרכז את כל ההנחיות התפעוליות כך שהצוות ידע מה עובד ומה…
- `docs/large-files-runbook.rst` — **טיפול בקבצים גדולים (Large Files)**

## API Reference

- `docs/api/index.rst` — **API Reference**: תיעוד מלא של ה-API של Code Keeper Bot.
  - `docs/api/handlers.documents.rst` — **handlers.documents module**: handlers.documents מרכז את הטיפול במסמכים וקבצים שנשלחים לבוט (Facade). הוא אחראי לנתב בין מסלולי GitHub, ZIP וקבצים טקסטואליים, ולשמור מדדים ואירועי Observability לאורך הזרימה.
  - `docs/api/modules.rst` — **workspace**
    - `docs/api/refactoring_engine.rst` — **refactoring\_engine module**: המנוע מיישם קיבוץ לפי קוהזיה כדי למנוע Oversplitting ולהימנע מ-God Class
- `docs/modules/index.rst` — **מודולים ראשיים**: תיעוד מפורט של המודולים הראשיים בפרויקט.
- `docs/handlers/index.rst` — **Handlers**: תיעוד של כל ה-handlers בפרויקט.
  - `docs/handlers/show.rst` — **Show Command**
  - `docs/handlers/drive_menu.rst` — **Drive Menu V2**: תפריט הגיבוי ל‑Google Drive (גרסת V2) כולל בחירה מהירה (קבצי גיבוי/הכל/מתקדם), בחירת תיקיית יעד (אוטומטי/ברירת מחדל/מותאם), תזמון גיבוי, וטיפול שגיאות ברור.
  - `docs/handlers/document-flow.rst` — **זרימת הטיפול במסמכים (Document Flow)**: נדרשות להזנת הבנאי של DocumentHandler
- `docs/services/index.rst` — **Services**: תיעוד של שירותי הליבה של המערכת.
  - `docs/services/google_drive_service.rst` — **Google Drive Service**: שירות גוגל דרייב אחראי לאימות (Device Flow), ניהול טוקנים, יצירת ZIP, והעלאות לתיקיות ממוסלות לפי קטגוריה/תאריך/ריפו.
- `docs/database/index.rst` — **Database**: תיעוד של מערכת מסד הנתונים והמודלים.
  - `docs/database/bookmarks-manager.rst` — **מנהל סימניות – BookmarksManager**: database.bookmarks_manager.BookmarksManager הוא שכבת ה-DB הראשית שמאחורי פיצ'ר הסימניות. הוא דואג לולידציה, לאכיפת מגבלות, ליצירת אינדקסים ולסנכרון הסימניות מול שינויים בקבצי הקוד.
  - `docs/database/collections-manager.rst` — **מנהל אוספים – CollectionsManager**: פיצ'ר "הקולקציות שלי" נשען על database.collections_manager.CollectionsManager – שכבת שירות שמספקת CRUD מלא, חוקים חכמים, שיתוף ציבורי, ניהול פריטים ופעילות שיתופים. העמוד מסכם את המבנה כדי שיהיה קל לחבר פיצ'רים חדשים.
- `docs/database/indexing.rst` — **MongoDB Indexing Cookbook**: הדוגמאות מתייחסות לקולקציה לדוגמה בשם code_snippets (התאימו לשם אצלכם)
- `docs/database/cursor-pagination.rst` — **Cursor-based Pagination (created_at / _id)**: הבא דף נוסף לאחר last_dt, last_id
- `docs/database-schema.rst` — **Database Schema**
- `docs/database/detailed-schema.rst` — **מבנה נתונים מפורט (Detailed Database Schema)**: מסמך זה מתאר בפירוט את כל האוספים, השדות, האילוצים והאינדקסים במסד הנתונים.

## עזרה ודוגמאות

- `docs/examples.rst` — **דוגמאות שימוש**: דף זה מכיל דוגמאות קוד לשימוש ב-API של Code Keeper Bot.
- `docs/testing.rst` — **Testing Guide**: כדי להריץ טסטים ללא python-telegram-bot, קיימים stubs ב-tests/_telegram_stubs.py והם נטענים אוטומטית דרך tests/conftest.py
- `docs/testing-rate-limit-examples.rst` — **דוגמאות טסטים – Rate Limiting ואסינכרוניות**
- `docs/performance-tests.rst` — **בדיקות ביצועים (Performance Tests)**: להריץ בדיקות ביצועים בצורה בטוחה וגמישה: ברירת מחדל מריצים את כולן; ב‑PR Draft עם תווית מתאימה מריצים רק "קלים".
- `docs/ci-cd.rst` — **CI/CD Guide**
- `docs/conversation-handlers.rst` — **Conversation Handlers & States**: מסמך זה מרכז את הזרימות העיקריות של ה‑ConversationHandlers וה‑states.
- `docs/troubleshooting.rst` — **Troubleshooting Guide**: ModuleNotFoundError: No module named 'telegram'
- `docs/development.rst` — **Development Workflow**
- `docs/development/pre-commit.rst` — **Pre-commit Hooks**: להבטיח איכות קוד עקבית לפני קומיט/PR.
- `docs/development/tools.rst` — **כלי עזר למפתחים**: עמוד זה מרכז שני כלים ייעודיים שנמצאים תחת tools/ ונועדו לסייע באיתור צווארי בקבוק במאגר ובסדר הקוד. לפני השימוש ודאו שהקבצים אינם מתועדים במקום אחר כדי למנוע כפילות.
- `docs/development/scripts.rst` — **סקריפטים שימושיים**: תיקיית scripts/ מכילה כלים חד-פעמיים ותהליכי תחזוקה. לפני ההרצה ודאו שסביבת ה-DB היא סביבת ניסוי/פיתוח ושיש גיבוי עדכני.
- `docs/development/i18n.rst` — **בינאום ותמיכה בשפות**: מודול i18n/ מספק שכבת תרגום פשוטה לבוט הטלגרם וה-WebApp. נכון לעכשיו קיימת חבילת מחרוזות בעברית (strings_he.py), אך המבנה מאפשר הוספת שפות חדשות ללא שינוי בלוגיקה העסקית.
- `docs/integrations.rst` — **Integrations**: להפעלת פעולות שונות מול GitHub נדרש להגדיר לטוקן \(`GITHUB_TOKEN` או טוקן משתמש שנשמר במערכת\) את מרחבי ההרשאות המינימליים. הקפידו על עיקרון ההרשאות המצומצמות.
- `docs/mcp-server.rst` — **שרת ה-MCP — חיבור Claude ל-CodeKeeper**: שרת MCP (Model Context Protocol) שחושף את CodeKeeper ל-Claude: הקבצים והאוספים האישיים של כל משתמש, ולאדמין — גם דפדפן הריפו מעל ה-Repo Sync Engine. עובד גם מול Claude.ai (Custom Connector דרך OAuth 2.1) וגם מול Claude…
- `docs/repository-integrations.rst` — **Repository Integrations**: מסמך זה מרכז את התמיכה בספקי מאגרי קוד. מטרתו למנוע בלבול ולהבהיר מה נתמך ומה לא.
- `docs/security.rst` — **Security Guide**: אל תרשום סודות/PII בלוגים, השתמש ב‑ENV בלבד.
- `docs/monitoring.md` — **Smart Observability v7 – Predictive Health & Adaptive Feedback**
- `docs/git-lfs.rst` — **Git LFS Integration**: להסביר מתי ואיך להשתמש ב‑Git Large File Storage (LFS) עבור קבצים גדולים.
- `docs/user/bookmarks.rst` — **סימניות (Bookmarks)**: תכונת הסימניות מאפשרת לשמור "קיצורי דרך" לנקודות ספציפיות בקבצים, עם הדגשה ויזואלית בצבעים והוספת הערות (Annotations). סימנייה יכולה להיות מבוססת על מספר שורה בקובץ קוד או על "עוגן" יציב כמו כותרת ב‑Markdown או מזהה id…
- `docs/user/sticky_notes.rst` — **פתקים דביקים (Sticky Notes)**: פתקים דביקים מאפשרים להצמיד הערות קצרות ומודגשות על‑גבי תצוגת קובץ (קוד/Markdown/HTML), כך שאפשר לסמן נקודות חשובות, משימות או תזכורות ישירות במקום הרלוונטי בתוכן. הפתק "ננעל" לעוגן יציב כאשר ניתן (כותרת ב‑Markdown או…
- `docs/user/reminders.rst` — **תזכורות בבוט**: מערכת התזכורות מאפשרת למשתמשי הבוט ליצור, לדחות ולנהל תזכורות אישיות דרך שיחה אינטראקטיבית או פקודות קצרות. המידע נשמר ב-MongoDB (`reminders/database.py`) ומנוהל דרך ישויות `Reminder` ו-`ReminderConfig`.
- `docs/user/my_collections.rst` — **האוספים שלי (My Collections)**: אוספים מאפשרים לאגד יחד קבצים/קטעי קוד/סימניות תחת נושא משותף (פרויקט, משימה, מודול), כדי לשתף, לנווט ולעקוב בקלות. כל אוסף כולל שם, תיאור קצר ורשימת פריטים עם סדר מותאם.
- `docs/user/share_code.rst` — **שיתוף קוד (חשוב)**: כפתור "🔗 שתף קוד" מאפשר ליצור שיתוף מהיר של קובץ קוד דרך GitHub Gist או Pastebin. השיתוף נוצר לפי מזהה הקובץ במסד (ObjectId), כך שתמיד משתף את התוכן העדכני ביותר.
- `docs/user/github_browse.rst` — **עיון בקוד GitHub (כולל חיפוש בשם קובץ)**
- `docs/user/download_repo.rst` — **הורדת ריפו**: בתפריט /github ← 📥 הורד קובץ מריפו, נווטו לתיקייה הרצויה. בתחתית הרשימה יופיע כפתור שמציין במפורש מה ייארז, למשל 📦 הורד תיקייה כ־ZIP: "logo-designer".
- `docs/BOT_TEST_PLAN_CONTAINER.md` — **תכנית בדיקות לבוט – Composition Root (Container) לשירות Snippet**: מסמך זה מתאר בדיקות ידניות מהירות לבוט לאחר העברת יצירת התלויות ל־Container דומייני/אפליקטיבי. המטרה: לוודא שה־handlers צורכים את השירות מאותה נקודת אמת, בלי לשנות לוגיקה.

## זרימות עבודה

- `docs/workflows/index.rst` — **זרימות עבודה (Workflows)**: מסמכים אלה מתארים את הזרימות המרכזיות במערכת.
  - `docs/workflows/save-flow.rst` — **זרימת שמירת קוד (Save Flow)**: זרימת השמירה מאפשרת למשתמשים לשמור קטעי קוד בבוט דרך מספר מסלולים
  - `docs/workflows/search-flow.rst` — **זרימת חיפוש (Search Flow)**: מנוע החיפוש תומך במספר סוגי חיפוש
  - `docs/workflows/refactor-flow.rst` — **זרימת רפקטורינג (Refactor Flow)**: מנוע הרפקטורינג מאפשר שינוי מבנה קוד בצורה בטוחה עם אימות לפני ואחרי.
  - `docs/workflows/backup-flow.rst` — **זרימת גיבוי ושחזור (Backup Flow)**: מערכת הגיבויים מאפשרת
  - `docs/workflows/gist-flow.rst` — **זרימת שיתוף ב-Gist (Gist Flow)**: שיתוף ב-GitHub Gist יוצר את ה-Gist תחת החשבון האישי של המשתמש, לא תחת חשבון המערכת. זו לא החלטה קוסמטית: Gist שנוצר בטוקן המערכת מופיע ברשימת ה-Gists של המערכת, מיוחס אליה, והמשתמש לא יכול לערוך או למחוק אותו. לכן…

## מנועי המערכת

- `docs/engines/overview.rst` — **מנועי המערכת (System Engines)**: מסמך זה מתאר את המנועים המרכזיים במערכת וכיצד הם עובדים.

## Edge Cases וטיפול בשגיאות

- `docs/edge-cases.rst` — **Edge Cases וטיפול בשגיאות**: מסמך זה מתאר Edge Cases נפוצים במערכת וכיצד לטפל בהם.

## איכות וקונבנציות

- `docs/quality/type-safety.md` — **📝 Type Hints – Best Practices**: מטרה: לשמר בטיחות טיפוסים ברורה, להקשיח מודולים בהדרגה, ולא להסתמך על `type: ignore`.
- `docs/quality/code-normalization.md` — **נרמול קוד (Code Normalization)**: מסמך זה מרכז את כל מה שסוכן או מפתח צריך לדעת על מנגנון נרמול הקוד של Code Keeper Bot – למה הוא קיים, איך הוא עובד ואיך משתמשים בו ביום־יום.
- `docs/ARCHITECTURE_LAYER_RULES.md` — **כללי שכבות – CodeBot**: מטרה: לשמור גבולות שכבות ברורים ולמנוע תלות מעגלית/דליפת תשתית.

## WebApp

- `docs/webapp/overview.rst` — **המיני Web App (סקירה)**: מאוגוסט 2026 האייקונים אינם אמוג'ים אלא 28 אייקונים מצוירים (SVG) בסגנון אחיד, שנשלפים מספרייט אחד. המבנה המלא, הגדלים, אופן ההוספה והמלכודות מתועדים בנפרד: language-icons.
- `docs/webapp/code-browser.rst` — **דפדפן קוד (Code Browser)**: דפדפן הקוד מאפשר צפייה וניווט בריפוזיטורים מ-GitHub ישירות בממשק ה-WebApp.
- `docs/DEV_WEB_PUSH.md` — **Web Push – Sticky Notes Reminders**: מסמך זה מסביר כיצד להפעיל ולבדוק התראות Web Push עבור תזכורות של Sticky Notes.
- `docs/webapp/user-interfaces.rst` — **ממשקי משתמשים (Web)**: "ממשקי משתמשים" הם אוסף מסכים ותהליכים אינטראקטיביים ב‑WebApp שמאפשרים לבצע פעולות מורכבות בנוחות: טפסים ממוקדים, אשפים רב‑שלביים, ותצוגות מצב. הפיצ'ר מיועד גם לשימוש ישיר ע"י משתמשי קצה וגם להפעלה מונחית ע"י סוכני AI.
- `docs/webapp/snippet-library.rst` — **ספריית סניפטים (Web)**: "ספריית סניפטים" היא גלריית קטעי קוד קצרים עם הדגשת תחביר, חיפוש וסינון. הספרייה מציגה גם סניפטים שהוגשו ע"י משתמשים (לאחר אישור אדמין), וגם סניפטים מובנים (Curated) שמסופקים כחלק מהמערכת.
- `docs/webapp/onboarding.md` — **🧭 WebApp Onboarding – Welcome Modal, Interactive Tour & Theme Wizard**: תהליך ה-Onboarding של ה-WebApp מורכב משלושה רכיבים תלויים שמופעלים עבור משתמשים חדשים בלבד: Welcome Modal, סיור אינטראקטיבי מבוסס Driver.js וה-Theme Picker Wizard שמסיים את החוויה עם התאמה אישית. העמוד מרכז את ההסברים…
- `docs/webapp/caching.rst` — **Caching & HTTP Validators (ETag / Last-Modified / 304)**: להקטין רוחב‑פס וזמני תגובה: אם התוכן לא השתנה, נחזיר 304 Not Modified במקום גוף מלא. כך דפדפנים ולקוחות יכולים להשתמש במטמון מקומי בצורה בטוחה ויעילה.
- `docs/webapp/advanced-caching.md` — **מערכת Caching מתקדמת עם TTL דינמי**: מסמך זה מרכז את ההמלצות והדוגמאות להטמעת מערכת caching חכמה עם TTL דינמי, כפי שגובש ב-Feature Suggestion. המטרה: שיפור מהיר של זמני תגובה, הורדת עומסים על DB, ושימור עקביות בין שרתים.
- `docs/webapp/cache-inspector.rst` — **Cache Inspector (לוח בקרה של Redis)**: Cache Inspector הוא כלי אדמין שמאפשר לצפות ולנהל את ה-Redis cache בצורה בטוחה. הכלי נותן נראות ל
- `docs/webapp/config-inspector.rst` — **Config Inspector (סקירת משתני סביבה)**: Config Inspector הוא כלי אדמין שמציג תמונת מצב של הקונפיגורציה: אילו משתני סביבה מוגדרים, מה הערך הפעיל שלהם, מה ברירת המחדל בקוד, והאם הערך שונה מברירת המחדל.
- `docs/webapp/static-checklist.rst` — **Static Performance & Security Checklist (gzip/br, Cache, SRI)**: להבטיח טעינה מהירה ובטוחה של נכסים סטטיים (CSS/JS/Images).
- `docs/webapp/commands-catalog.rst` — **תחזוקת קטלוג הפקודות (``commands.json``)**: קטלוג הפקודות ב-webapp/static/data/commands.json מזין את כרטיסי ה-"קיצורי דרך" שנראים בחיפוש הגלובלי (קיצור מקלדת Ctrl/Cmd+K). בכל טעינת דף, ה-frontend מושך את הקובץ דרך /static/data/commands.json ומוסיף את הכרטיסים…
- `docs/webapp/code-execution.rst` — **הרצת קוד (Code Execution Playground)**: ב‑WebApp יש כלי שמאפשר להריץ קוד Python מתוך הדפדפן, דרך API ייעודי.
- `docs/webapp/api-reference.rst` — **WebApp API Reference**
- `docs/webapp/bulk-actions.rst` — **Bulk actions (בחירה מרובה)**: דף זה מתאר את יכולות הבחירה המרובה והפעולות הקבוצתיות בממשק הווב.
- `docs/webapp/editor.md` — **⌨️ עורך קוד (WebApp Editor)**: תוכן זה מסביר את טעינת העורך, מנגנון הגיבוי, וניהול העדפות.
- `docs/webapp/markdown-folding.rst` — **Markdown – מצב מצומצם (קיפול כותרות ###) – אדמין בלבד**: מטרת הפיצ'ר: לאפשר לעורכים לקפל מקומית סעיפים לפי כותרות ### (H3) בתצוגת Markdown, בלי לשנות את קובץ ה־Markdown ובלי להשפיע על תצוגה ציבורית.
- `docs/markdown_style_guide.rst` — **מדריך סגנונות וארכיטקטורת Markdown**: המסמך הזה הוא Source of Truth לעיצוב וארכיטקטורת Markdown בפרויקט. הוא מיועד למפתחים ול‑QA ויזואלי.
- `docs/webapp/smooth-scrolling.rst` — **Smooth Scrolling (WebApp) — מדריך תמציתי לסוכני AI**: מדריך זה מסביר את יכולות הגלילה החלקה שהוטמעו ב‑WebApp, כיצד להשתמש בהן באופן בטוח, ומה הדגשים לסוכני AI כדי לשמור על נגישות וביצועים.
- `docs/webapp/system-modules.rst` — **מודולים פנימיים ב-WebApp**: הקבצים הבאים בתיקיית webapp/ מנהלים תשתיות שאינן מכוסות במדריכים קודמים. העמוד מסביר את ה‑API, התלויות והסיבות לכל רכיב כדי שיהיה אפשר להרחיב או לדבג במהירות.

## Frontend > Theming

- `docs/webapp/theming_and_css.rst` — **מערכת ערכות הנושא והטוקנים החדשה**: הדף מרכז את כל הידע המעשי על ארכיטקטורת הצבעים, משתני ה‑CSS והבדיקות שנדרשות לשימור חוויית הממשק בכל שמונה הערכות. זהו מקור האמת עבור כל שינוי עתידי ב‑CSS של ה‑WebApp.
- `docs/webapp/custom_themes_guide.rst` — **ערכות נושא מותאמות אישית – מדריך מקיף**: מדריך זה מכסה את כל היבטי מערכת ערכות הנושא המותאמות אישית (Custom Themes) – מייבוא VS Code themes ועד יצירה ידנית, הגדרות מתקדמות והדגשת תחביר.
- `docs/webapp/language-icons.rst` — **אייקוני שפות התכנות**: כל קובץ ב-Web App מוצג עם אייקון שמייצג את שפת התכנות שלו. עד אוגוסט 2026 אלה היו אמוג'ים (🐍 לפייתון, 📜 ל-JavaScript); היום אלה 28 אייקונים מצוירים בסגנון אחיד — אריח ריבועי עם גרדיאנט וסימן לבן.

## Observability

- `docs/observability.rst` — **אובזרווביליות (Observability)**: מומלץ להתחיל עם אחד מהבאים (כולם תומכים ב־OTLP)
- `docs/observability/background-jobs-monitor.rst` — **Background Jobs Monitor**: פיצ'ר ה-Background Jobs Monitor מספק נראות (Observability) מלאה לכל ה-Jobs הרצים ברקע במערכת, כולל פעולות משתמש דינמיות (Drive, Reminders, Batch Operations).
- `docs/observability/observability_dashboard.md` — **📡 Observability Dashboard & API**: מסך ה־Admin החדש (`/admin/observability`) מרכז נתוני ניטור בזמן אמת לטובת צוותי SRE והמפתחים. העמוד מתמקד בשלושה עקרונות
- `docs/observability/query-performance-profiler.rst` — **Query Performance Profiler**: Query Performance Profiler הוא כלי ניטור לשאילתות MongoDB איטיות, המספק
- `docs/observability/quick_fix_rules.md` — **🧠 Quick Fix חכם (Queue Delay + עומס/DB) – הנחיות למפתחים ולסוכני AI**: המטרה של Quick Fix היא לתת המלצה קצרה, בטוחה ושימושית על “מה לעשות עכשיו”, לפי אותות שאנחנו כבר מודדים.
- `docs/observability/asyncio-loop-safety.rst` — **Asyncio תחת WSGI: הרצת קורוטינות בבטחה**: ב-WebApp שמורץ תחת WSGI (Flask + Gunicorn/gevent), עלולה להיות לולאת Event פעילה כבר בתוך ה-thread של הבקשה. במצב כזה קריאה ל-asyncio.run תזרוק חריגה ותפיל את הבקשה, ולעתים תשאיר קורוטינה "תלויה" ללא await.
- `docs/visual-rule-engine.rst` — **Visual Rule Engine - מנוע כללים ויזואלי**: ה-Visual Rule Engine מאפשר ליצור כללים מורכבים להתראות (Alerts) בממשק גרפי, ללא צורך בכתיבת קוד. כל כלל מורכב מ
- `docs/observability/coverage_report.rst` — **Coverage Report (Runbooks / Quick Fixes)**: עמוד ה-Coverage נועד להיות Gap Analysis קבוע: To‑Do List לצוות שמראה אילו alert_type נצפו במערכת ועדיין חסר להם Runbook/Quick Fix, ואילו הגדרות בקונפיג הפכו ליתומות.
- `docs/api/ai_explain.md` — **🧠 Observability AI Explain API**: שירות זה מספק שכבת AI רשמית שמתרגמת הקשרי התראות (Context) להסבר קצר בשפה טבעית, כולל שורש הבעיה, פעולות מומלצות ואותות תומכים. השירות נפרס כחלק מה־`webserver` (AioHTTP) תחת הנתיב `POST /api/ai/explain` ומשמש את לוח…
- `docs/rate-limiting.rst` — **Rate Limiting**: מערכת הגבלת קצב אחודה לבוט ולווב, עם Shadow Mode, Soft‑Warning ב‑80% ועקיפת מנהלים.
- `docs/observability/guidelines.md` — **📊 הנחיות Observability ואירועים**: מטרה: לקבוע תבנית ברורה ללוגים ולאירועים, להפחית רעש, ולאפשר תחקור מהיר בעזרת request_id.
- `docs/logging_schema.rst` — **סכמת לוגים**
- `docs/metrics.rst` — **מדדים (Metrics)**: נקודת הקצה ל-Prometheus: /metrics
- `docs/resilience.rst` — **Resilience לשירותים חיצוניים**: המעבר למודול resilience.py יוצר אחידות: כל קריאה החוצה עוברת דרך אותה מדיניות Retry + Circuit Breaker. התוצאה: פחות רעשים זמניים, ניטור ברור יותר, ויכולת להבין בזמן אמת מתי שירות חוץ "שורף" אותנו.
- `docs/alerts.rst` — **התראות (Alerts)**: החוקים המוגדרים כרגע מכסים שגיאות, זמני תגובה ועמידה ב-SLO
- `docs/observability/log_based_alerts.rst` — **התראות מבוססות לוגים (Log‑based Alerts)**: מערכת התראות המבוססת על לוגים מנתחת את זרם האירועים של האפליקציה ומזהה תקלות בצורה חכמה באמצעות
- `docs/observability/log-aggregator.rst` — **מנוע ניתוח לוגים (Log Event Aggregator)**: monitoring/log_analyzer.py מרכז את כל האינטליגנציה שמטרתה להמיר זרם לוגים רועש להתראות פעולה. העמוד מפרט את רכיבי המערכת, הארכיטקטורה והקונפיגורציה שבין monitoring/log_analyzer.py, monitoring/error_signatures.py…
- `docs/sentry.rst` — **Sentry**: ברירת מחדל: Sentry מציג Issues בממשק ושולח מיילים, אבל לא מזרים את זה אוטומטית למערכת ההתראות הפנימית שלנו (Telegram + Observability).
- `docs/runbooks/incident-checklist.rst` — **Incident Checklist (On‑Call)**
- `docs/runbooks/logging-levels.rst` — **שינוי רמות לוגים**
- `docs/runbooks/github_backup_restore.rst` — **GitHub Backup & Restore Runbook**: מדריך צעד‑אחר‑צעד לגיבוי ושחזור מאגר GitHub, כולל יצירת נקודת בדיקה (Checkpoint Tag) ושחזור בטוח.
- `docs/runbooks/slo.md` — **Runbooks – SLO Incidents**: מדד זמינות משוער (על בסיס מונים סטנדרטיים)

## פריסה ו-Workers

- `docs/deployment/workers.rst` — **עובדי Push**: ל-Code Keeper Bot יש שני מסלולים לשליחת Web Push

## ChatOps

- `docs/chatops/overview.md` — **ChatOps – סקירה כללית**
- `docs/chatops/commands.md` — **פקודות ChatOps**: להלן מבנה אחיד לכל פקודה: מתי להשתמש, פרמטרים, הרשאות, מה לחפש בפלט, ודוגמה קצרה אם יש ערך מוסף.
- `docs/chatops/observe.md` — **ChatOps – /observe: הרחבות -v ו- -vv**: מסמך זה מפרט את מצב ההרחבה של הפקודה `/observe` לצורכי תחקור ומהירות תגובה בזמן אמת.
- `docs/chatops/ratelimit.rst` — **הגבלת קצב לפקודות רגישות**: chatops.ratelimit מרכז את שכבת ההגנה הקלה נגד ספאם לפקודות רגישות במערכת ה-ChatOps (למשל `/deploy`, `/restart`, `/secrets`). במקום ליישם Redis/DB עבור כל פקודה, אנחנו שומרים חותמת זמן אחרונה בזיכרון ה-process ומוודאים…
- `docs/chatops/playbooks.md` — **Playbooks – תרחישים נפוצים**
- `docs/chatops/permissions.md` — **הרשאות ו-Rate Limit**
- `docs/chatops/troubleshooting.md` — **פתרון תקלות (FAQ)**
- `docs/chatops/faq.md` — **שאלות נפוצות**: איך נמנעים מדליפת סודות?

## סוכני AI

- `docs/ai-agents/guide.md` — **🤖 מדריך לסוכני AI**: מטרה: לקצר זמן חיבור של סוכנים לפרויקט, לשמור על איכות ועמידה במדיניות.

## Observability – Advanced

- `docs/observability/events_catalog.rst` — **קטלוג אירועים קנוניים**
- `docs/observability/error_codes.rst` — **מילון קודי שגיאה (Error Codes)**
- `docs/observability/tracing_hotspots.rst` — **Tracing ממוקד בנקודות חמות**: מדריך קצר להתמקדות ב‑Tracing בנקודות בעלות השפעה גבוהה (Hotspots) בבוט וב‑WebApp.
- `docs/observability/metrics_promql.rst` — **שאילתות PromQL שימושיות**
- `docs/observability/alerts_playbook.rst` — **Playbook קצר להתראות**: התרשים הבא מציג את הזרימה המלאה של מערכת ההתראות - מזיהוי האירוע ועד לשליחת ההתראה

---

עמודי פיגום autodoc שסוננו: 92. עמודים שנסרקו: 228.
