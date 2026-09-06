# מפת התיעוד לסוכני AI

<!-- קובץ זה נוצר אוטומטית על ידי scripts/generate_ai_map.py — אל תערכו ידנית; עריכה תידרס. -->

שורה לכל עמוד ידני באתר התיעוד: נתיב, כותרת, והתקציר שהעמוד מצהיר עליו בראשו (`:summary:` ב-rst, `summary` ב-front matter). עמוד בלי הצהרה מופיע עם הכותרת בלבד. ההיררכיה נגזרת מה-toctree. עמודי פיגום של autodoc מסוננים — התוכן שלהם נוצר רק בזמן בנייה; לחתימות קראו את הקוד עצמו.

## סמכות התיעוד

התיעוד הוא **התמצאות, לא סמכות**. כל טענה עובדתית בו — התנהגות, נתיב, פרמטר, "נתמך" — קודם תאמת מול הקוד לפני שתסתמך עליה. התיעוד אינו תנ"ך; ייתכן שאינו מעודכן. אמת מול הקוד.

שני חריגים: בלוקי `literalinclude` ועמודי autodoc, שנמשכים מהמקור בזמן הבנייה. סתירה בין פרוזה לקוד ← הקוד צודק, והסתירה ממצא לדיווח.

## למפתחים ולסוכני AI

- `docs/quickstart-ai.rst` — **התחלה מהירה - סוכני AI**: מסמך זה נועד לאפשר לסוכן AI להתחיל לעבוד על הריפו במהירות ובבטחה, בהתאם למדיניות הפרויקט.
- `docs/quickstart.rst` — **התחלה מהירה - מפתחים**: הצעדים להרצה מקומית מהירה של הבוט, מהתקנה ועד הפעלה.
- `docs/quickstart-contrib.rst` — **Quickstart לתרומה**: דף קצר שמאפשר להתחיל לתרום במהירות ובבטחה.
- `docs/ai-guidelines.rst` — **הנחיות מלאות לסוכני AI**: ההנחיות המלאות לסוכני AI שעובדים בריפו: המגבלות הקריטיות, איך מריצים פקודות, אילו כלי קבצים מאושרים, עקרונות עריכת קוד, ומדיניות הקומיטים וה-Pull Requests.
- `docs/agents/rate-limiting.md` — **🚦 מערכת Rate Limiting לסוכני AI ולווב**: מטרה: להסביר איך מפעילים ומנטרים Rate Limiting בבוט ובווב, עם דגש על Shadow Mode, ניטור וקונפיג.
- `docs/doc-authoring.rst` — **Doc Authoring Guide (Sphinx/RTD)**: כללי כתיבת תיעוד בפרויקט — הצהרת תקציר בראש כל עמוד, הטמעת קוד לפי שם או סימון ולא לפי מספרי שורות, ההבחנה בין ספירת מופעים לערך שנאכף, ובנייה ללא אזהרות.
- `docs/style-glossary.rst` — **Style & Naming Glossary**: מילון המונחים והשמות בפרויקט: מיפוי בין מונחים מקבילים, כללי הניסוח, ועוגני התיעוד שמפנים אליהם.
- `docs/versioning-stable-anchors.rst` — **Versioning & Stable Anchors**: מדיניות הגרסאות והעוגנים היציבים בתיעוד: אילו עוגנים מובטחים לא להישבר, איך מתעדים שינוי ב-What's New, ודוגמאות.
- `docs/whats-new.rst` — **What's New**: יומן השינויים של הבוט וה-WebApp לפי תאריך — מה נוסף, מה השתנה ומה תוקן בכל עדכון, עם קישורים ל-Issues הרלוונטיים.
- `docs/architecture.rst` — **ארכיטקטורה**: המערכת מורכבת מבוט Telegram, שכבת שירותים (services), שכבת נתונים (MongoDB) ואפליקציית Web. הזרימה העיקרית: Handlers → Services → Database.
  - `docs/architecture/clean-architecture.rst` — **Clean Architecture ב-src**: ארכיטקטורה זו מפרידה בין לוגיקה עסקית, תזמור יישומי ותשתיות כך שניתן לבדוק יחידות קוד בנפרד, להחליף מקורות נתונים בלי לשבור את שאר המערכת ולרוץ גם בסביבות ללא MongoDB.
- `docs/dev/sticky_notes_extending.rst` — **עקרונות להוספת פיצ'ר לסטיקי-נוטס**: המלכודות החוזרות של הפתקים הדביקים: יעד יחיד ב-build_note_target, מכסה fail-closed והפטור-לאדמין, flush לפני פעולה הרסנית, אינדקס ממוספר שנבנה לפני שמפילים, נורמליזציה בשני הקצוות, יתומים בקריאה, ועדכון עמוד המשתמש.
- `docs/contributing.rst` — **מדריך תרומה**: לתת מסלול ברור לתרומות קוד, עם דגש על סוכני AI ו-CI.
- `docs/branch-protection-and-pr-rules.rst` — **Branch Protection & PR Rules**: לרכז נהלים ברורים להגנה על ענפים (Branch Protection) ולחוקי PR בפרויקט.

## מדריכים בסיסיים

- `docs/installation.rst` — **התקנה והגדרה**: דף זה מכיל הוראות התקנה מפורטות עבור Code Keeper Bot.
- `docs/configuration.rst` — **Rate Limiting**: רפרנס הקונפיגורציה של המערכת: Rate Limiting, משתני סביבה, Pooling ו-Timeouts למסדי הנתונים ול-Redis, לקוחות ה-HTTP הסינכרוני והאסינכרוני, Flask, הבוט והמדדים.
- `docs/environment-variables.rst` — **משתני סביבה - רפרנס**: רפרנס משתני הסביבה: הטבלה המרכזית, משתני התראות וניטור, מדדים ו-OTEL, תפעול ואינטגרציות, דגלי בדיקות, ודוגמאות קונפיגורציה כולל טבלת ה-Scopes של GitHub.
- `docs/performance-bible.md` — **🚀 The Performance Bible: CodeKeeper Optimization Guide**: עקרונות הביצועים של המערכת אחרי הרפקטור שהוריד את ה-p95 מ-1.8 שניות ל-200ms: Cache First, Projection, חישוב ב-DB, אינדקסים מורכבים, ו-Lazy Loading.
- `docs/performance-scaling.rst` — **ביצועים והרחבה (Performance & Scaling)**: עימוד, Projection, כוונון Connection Pooling ו-Timeouts, לוגי איטיות לאיתור צווארי בקבוק, והנחיות לפי סביבה.
- `docs/performance-sticky-notes.rst` — **Sticky Notes Warmup – פתרון ביצועים משולב**: העלאת timeout שכבר הוכחה בשטח, וחימום אינדקסים לפני שהתהליך מקבל תעבורה — נדבך שעדיין נבחן. כולל מה לאמת לפני rollout מלא.
- `docs/large-files-runbook.rst` — **טיפול בקבצים גדולים (Large Files)**: ראנבוק לטיפול בקבצים גדולים: המגבלות והפולבקים, הנחיות ההפעלה, ומה לנטר.

## API Reference

- `docs/api/index.rst` — **API Reference**: תיעוד מלא של ה-API של Code Keeper Bot.
  - `docs/api/handlers.documents.rst` — **handlers.documents module**: מנתב קבצים שנשלחים לבוט לפי ``upload_mode``: שחזור ZIP לריפו GitHub, ייבוא ZIP, וקבצי טקסט שנשמרים דרך שכבת הקבצים. כולל ולידציה והגנות מפני 'פצצת ZIP'.
  - `docs/api/modules.rst` — **workspace**: אינדקס המודולים של התיעוד האוטומטי — נקודת הכניסה לעמודי ה-API שנוצרים מ-autodoc בזמן הבנייה.
    - `docs/api/refactoring_engine.rst` — **refactoring\_engine module**: מנוע הרפקטורינג: המדיניות והקונפיגורציה, קיבוץ לפי קוהזיה שמונע Oversplitting ו-God Class, והמקרה המיוחד של פירוק בטוח ל-models.py.
- `docs/modules/index.rst` — **מודולים ראשיים**: תיעוד מפורט של המודולים הראשיים בפרויקט.
- `docs/handlers/index.rst` — **Handlers**: תיעוד של כל ה-handlers בפרויקט.
  - `docs/handlers/show.rst` — **Show Command**: מפרט פקודת /show: מבנה תגובת ה-HTML, שורות הכפתורים (מחיקה, עריכה, הערה, הורדה, שיתוף ומועדפים), והערות יישום.
  - `docs/handlers/drive_menu.rst` — **Drive Menu V2**: תפריט הגיבוי ל‑Google Drive (גרסת V2) כולל בחירה מהירה (קבצי גיבוי/הכל/מתקדם), בחירת תיקיית יעד (אוטומטי/ברירת מחדל/מותאם), תזמון גיבוי, וטיפול שגיאות ברור.
  - `docs/handlers/document-flow.rst` — **זרימת הטיפול במסמכים (Document Flow)**: המפה בין הרכיבים שמטפלים בקובץ שנשלח לבוט, מצבי upload_mode, התלויות שמוזרקות ל-DocumentHandler, ושכבת האחסון (FilesFacade מול ה-DB הישן).
- `docs/services/index.rst` — **Services**: תיעוד של שירותי הליבה של המערכת.
  - `docs/services/google_drive_service.rst` — **Google Drive Service**: שירות Google Drive: אימות ב-Device Flow, ניהול טוקנים, יצירת ZIP והעלאה לתיקיות לפי קטגוריה (ובקטגוריית 'לפי ריפו' גם תת-תיקייה לשם הריפו). התאריך והגרסה נכנסים לשם קובץ ה-ZIP, לא למבנה התיקיות.
- `docs/database/index.rst` — **Database**: תיעוד של מערכת מסד הנתונים והמודלים.
  - `docs/database/bookmarks-manager.rst` — **מנהל סימניות – BookmarksManager**: database.bookmarks_manager.BookmarksManager הוא שכבת ה-DB הראשית שמאחורי פיצ'ר הסימניות. הוא דואג לולידציה, לאכיפת מגבלות, ליצירת אינדקסים ולסנכרון הסימניות מול שינויים בקבצי הקוד.
  - `docs/database/collections-manager.rst` — **מנהל אוספים – CollectionsManager**: פיצ'ר "הקולקציות שלי" נשען על database.collections_manager.CollectionsManager – שכבת שירות שמספקת CRUD מלא, חוקים חכמים, שיתוף ציבורי, ניהול פריטים ופעילות שיתופים. העמוד מסכם את המבנה כדי שיהיה קל לחבר פיצ'רים חדשים.
- `docs/database/indexing.rst` — **MongoDB Indexing Cookbook**: ספר מתכונים לאינדקסים ב-MongoDB: אילו אינדקסים מומלצים, מתכוני PyMongo, קריאת explain, ובדיקת קיום אינדקסים.
- `docs/database/cursor-pagination.rst` — **Cursor-based Pagination (created_at / _id)**: דפדוף מבוסס קורסור על created_at ו-_id: עקרונות מיון יציב, קידוד ופענוח הקורסור, תבניות שאילתה לשני הכיוונים, ודוגמת PyMongo מלאה.
- `docs/database-schema.rst` — **Database Schema**: סכמת מסד הנתונים: האוספים code_snippets, users, bookmarks ו-sessions, השדות בכל אחד, והאינדקסים.
- `docs/database/detailed-schema.rst` — **מבנה נתונים מפורט (Detailed Database Schema)**: מסמך זה מתאר בפירוט את כל האוספים, השדות, האילוצים והאינדקסים במסד הנתונים.

## עזרה ודוגמאות

- `docs/examples.rst` — **דוגמאות שימוש**: דף זה מכיל דוגמאות קוד לשימוש ב-API של Code Keeper Bot.
- `docs/testing.rst` — **Testing Guide**: Quickstart להרצת טסטים, ההנחיות הקריטיות, טעינת ה-stubs לטלגרם, עבודה עם tmp_path ומתכון מחיקה מוגבל ל-allowlist, ו-mocking של HTTP.
- `docs/testing-rate-limit-examples.rst` — **דוגמאות טסטים – Rate Limiting ואסינכרוניות**: קטעי דוגמה לכתיבת טסטים ל-Rate Limiting מול Redis מדומה ולקוד אסינכרוני. הקטעים אינם ניתנים להרצה כמות שהם — הם מדלגים על הקשר עם ``...`` ומניחים פונקציות מקומיות.
- `docs/performance-tests.rst` — **בדיקות ביצועים (Performance Tests)**: להריץ בדיקות ביצועים בצורה בטוחה וגמישה: ברירת מחדל מריצים את כולן; ב‑PR Draft עם תווית מתאימה מריצים רק "קלים".
- `docs/ci-cd.rst` — **CI/CD Guide**: מדריך ה-CI/CD: החוקים הקשיחים, הסטטוסים הנדרשים ב-PR, ריכוז ה-workflows, הבדיקות המומלצות ובניית התיעוד.
- `docs/conversation-handlers.rst` — **Conversation Handlers & States**: מסמך זה מרכז את הזרימות העיקריות של ה‑ConversationHandlers וה‑states.
- `docs/troubleshooting.rst` — **Troubleshooting Guide**: מדריך פתרון תקלות: שגיאות ייבוא בזמן טסטים, שגיאות parse_mode, בעיות event loop של asyncio, וכלים לדיבוג מהיר כולל בדיקת חיבור ל-MongoDB.
- `docs/development.rst` — **Development Workflow**: זרימת העבודה בפיתוח: הוספת handler חדש לבוט, הוספת endpoint ל-WebApp, ועדכון סכמה במסד הנתונים.
- `docs/development/pre-commit.rst` — **Pre-commit Hooks**: להבטיח איכות קוד עקבית לפני קומיט/PR.
- `docs/development/tools.rst` — **כלי עזר למפתחים**: הכלים שתחת tools/: ניתוח שאילתות איטיות ואיתור קוד כפול, מתי להריץ כל אחד ומה לקרוא בפלט.
- `docs/development/scripts.rst` — **סקריפטים שימושיים**: תיקיית scripts/ מכילה כלים חד-פעמיים ותהליכי תחזוקה. לפני ההרצה ודאו שסביבת ה-DB היא סביבת ניסוי/פיתוח ושיש גיבוי עדכני.
- `docs/development/i18n.rst` — **בינאום ותמיכה בשפות**: מודול i18n/ מספק שכבת תרגום פשוטה לבוט הטלגרם וה-WebApp. נכון לעכשיו קיימת חבילת מחרוזות בעברית (strings_he.py), אך המבנה מאפשר הוספת שפות חדשות ללא שינוי בלוגיקה העסקית.
- `docs/integrations.rst` — **Integrations**: להפעלת פעולות שונות מול GitHub נדרש להגדיר לטוקן \(`GITHUB_TOKEN` או טוקן משתמש שנשמר במערכת\) את מרחבי ההרשאות המינימליים. הקפידו על עיקרון ההרשאות המצומצמות.
- `docs/mcp-server.rst` — **שרת ה-MCP — חיבור Claude ל-CodeKeeper**: שרת ה-MCP שחושף את CodeKeeper ל-Claude: הכלים, האימות וההרשאות, פריימר הסוכן, עריכה מהדפדפן, מדידת השימוש ושער הפרטיות שלה, וההפעלה צעד אחר צעד מול Claude.ai ומול Claude Code.
- `docs/repository-integrations.rst` — **Repository Integrations**: מסמך זה מרכז את התמיכה בספקי מאגרי קוד. מטרתו למנוע בלבול ולהבהיר מה נתמך ומה לא.
- `docs/security.rst` — **Security Guide**: אל תרשום סודות/PII בלוגים, השתמש ב‑ENV בלבד.
- `docs/monitoring.md` — **Smart Observability v7 – Predictive Health & Adaptive Feedback**: חיבור Grafana לטלגרם דרך Webhook, אנוטציות, ספים דינמיים, הפרדה בין שגיאות פנימיות לחיצוניות, ו-Predictive Health.
- `docs/git-lfs.rst` — **Git LFS Integration**: להסביר מתי ואיך להשתמש ב‑Git Large File Storage (LFS) עבור קבצים גדולים.
- `docs/user/bookmarks.rst` — **סימניות (Bookmarks)**: סימניות בקבצים: איך מוסיפים, פאנל הסימניות, העוגן היציב שמחזיק אותן גם כשהקוד זז, ומגבלות הפרטיות והאבטחה.
- `docs/user/sticky_notes.rst` — **פתקים דביקים (Sticky Notes)**: הצמדת הערות קצרות על תצוגת קובץ (Markdown), על לוח פתקים, או על קובץ בדפדפן הריפו הממורר: הוספה וניהול, עיגון יציב לעומת מיקום קבוע, מארקדאון, תזכורות, ויתומים.
- `docs/user/reminders.rst` — **תזכורות בבוט**: מערכת התזכורות מאפשרת למשתמשי הבוט ליצור, לדחות ולנהל תזכורות אישיות דרך שיחה אינטראקטיבית או פקודות קצרות. המידע נשמר ב-MongoDB (`reminders/database.py`) ומנוהל דרך ישויות `Reminder` ו-`ReminderConfig`.
- `docs/user/my_collections.rst` — **האוספים שלי (My Collections)**: אוספים מאפשרים לאגד יחד קבצים/קטעי קוד/סימניות תחת נושא משותף (פרויקט, משימה, מודול), כדי לשתף, לנווט ולעקוב בקלות. כל אוסף כולל שם, תיאור קצר ורשימת פריטים עם סדר מותאם.
- `docs/user/share_code.rst` — **שיתוף קוד (חשוב)**: כפתור "🔗 שתף קוד" יוצר שיתוף מהיר של קובץ דרך GitHub Gist או Pastebin. הכפתור נושא את ה-ObjectId של הגרסה שהייתה קיימת כשהוא נוצר, ולכן הוא מצמיד גרסה ואינו מבטיח את התוכן העדכני.
- `docs/user/github_browse.rst` — **עיון בקוד GitHub (כולל חיפוש בשם קובץ)**: שורת הכלים, חיפוש לפי שם קובץ, וניווט בעץ הריפו — הכול מתוך הבוט.
- `docs/user/download_repo.rst` — **הורדת ריפו**: בתפריט /github ← 📥 הורד קובץ מריפו, נווטו לתיקייה הרצויה. בתחתית הרשימה יופיע כפתור שמציין במפורש מה ייארז, למשל 📦 הורד תיקייה כ־ZIP: "logo-designer".
- `docs/BOT_TEST_PLAN_CONTAINER.md` — **תכנית בדיקות לבוט – Composition Root (Container) לשירות Snippet**: מסמך זה מתאר בדיקות ידניות מהירות לבוט לאחר העברת יצירת התלויות ל־Container דומייני/אפליקטיבי. המטרה: לוודא שה־handlers צורכים את השירות מאותה נקודת אמת, בלי לשנות לוגיקה.

## זרימות עבודה

- `docs/workflows/index.rst` — **זרימות עבודה (Workflows)**: מסמכים אלה מתארים את הזרימות המרכזיות במערכת.
  - `docs/workflows/save-flow.rst` — **זרימת שמירת קוד (Save Flow)**: מצבי השמירה, מצב האיסוף הארוך, זיהוי סודות, טיפול בכפילויות, ונרמול הקוד לפני השמירה.
  - `docs/workflows/search-flow.rst` — **זרימת חיפוש (Search Flow)**: סוגי החיפוש בזרימת הבוט — טקסט, Regex, Fuzzy, פונקציות ותוכן — עם מבנה ה-SearchIndex, הפילטרים, הטיפול בשגיאות Regex ומיון התוצאות. החיפוש הסמנטי הוא מסלול נפרד ב-WebApp.
  - `docs/workflows/refactor-flow.rst` — **זרימת רפקטורינג (Refactor Flow)**: מנוע הרפקטורינג מאפשר שינוי מבנה קוד בצורה בטוחה עם אימות לפני ואחרי.
  - `docs/workflows/backup-flow.rst` — **זרימת גיבוי ושחזור (Backup Flow)**: זרימת הגיבוי והשחזור מקצה לקצה: סוגי הגיבויים, יצירת גיבוי מלא, שחזור, העלאה ל-Google Drive, ניהול הגיבויים הקיימים, וייבוא ZIP חיצוני.
  - `docs/workflows/gist-flow.rst` — **זרימת שיתוף ב-Gist (Gist Flow)**: נקודות הכניסה לשיתוף ב-Gist, למה ה-Gist נוצר תחת חשבון ה-GitHub של המשתמש ולא של המערכת, מצבי auth_failed, וההתנהגות fail-closed בכל מסלול כשל.

## מנועי המערכת

- `docs/engines/overview.rst` — **מנועי המערכת (System Engines)**: מסמך זה מתאר את המנועים המרכזיים במערכת וכיצד הם עובדים.

## Edge Cases וטיפול בשגיאות

- `docs/edge-cases.rst` — **Edge Cases וטיפול בשגיאות**: מסמך זה מתאר Edge Cases נפוצים במערכת וכיצד לטפל בהם.

## איכות וקונבנציות

- `docs/quality/type-safety.md` — **📝 Type Hints – Best Practices**: מטרה: לשמר בטיחות טיפוסים ברורה, להקשיח מודולים בהדרגה, ולא להסתמך על `type: ignore`.
- `docs/quality/code-normalization.md` — **נרמול קוד (Code Normalization)**: מסמך זה מרכז את כל מה שסוכן או מפתח צריך לדעת על מנגנון נרמול הקוד של Code Keeper Bot – למה הוא קיים, איך הוא עובד ואיך משתמשים בו ביום־יום.
- `docs/ARCHITECTURE_LAYER_RULES.md` — **כללי שכבות – CodeBot**: מטרה: לשמור גבולות שכבות ברורים ולמנוע תלות מעגלית/דליפת תשתית.

## WebApp

- `docs/webapp/overview.rst` — **המיני Web App (סקירה)**: מאוגוסט 2026 האייקונים אינם אמוג'ים אלא אייקונים מצוירים (SVG) בסגנון אחיד, שנשלפים מספרייט אחד. המבנה המלא, הגדלים, אופן ההוספה והמלכודות מתועדים בנפרד: language-icons.
- `docs/webapp/code-browser.rst` — **דפדפן קוד (Code Browser)**: דפדפן הקוד מאפשר צפייה וניווט בריפוזיטורים מ-GitHub ישירות בממשק ה-WebApp.
- `docs/webapp/user-interfaces.rst` — **ממשקי משתמשים (Web)**: אוסף המסכים והתהליכים האינטראקטיביים ב-WebApp, איפה כל אחד נמצא, ומה הוא עושה.
- `docs/webapp/snippet-library.rst` — **ספריית סניפטים (Web)**: גלריית קטעי קוד קצרים עם הדגשת תחביר, מאפייני ה-UI, והפעולות שאפשר לבצע עליה.
- `docs/webapp/onboarding.md` — **🧭 WebApp Onboarding – Welcome Modal, Interactive Tour & Theme Wizard**: תהליך ה-Onboarding ב-WebApp: Welcome Modal, סיור אינטראקטיבי מבוסס Driver.js, ואשף בחירת ערכת הנושא — כולל מנגנוני האיפוס והנקודות למפתחים.
- `docs/webapp/caching.rst` — **Caching & HTTP Validators (ETag / Last-Modified / 304)**: להקטין רוחב‑פס וזמני תגובה: אם התוכן לא השתנה, נחזיר 304 Not Modified במקום גוף מלא. כך דפדפנים ולקוחות יכולים להשתמש במטמון מקומי בצורה בטוחה ויעילה.
- `docs/webapp/advanced-caching.md` — **מערכת Caching מתקדמת עם TTL דינמי**: מסמך זה מרכז את ההמלצות והדוגמאות להטמעת מערכת caching חכמה עם TTL דינמי, כפי שגובש ב-Feature Suggestion. המטרה: שיפור מהיר של זמני תגובה, הורדת עומסים על DB, ושימור עקביות בין שרתים.
- `docs/webapp/cache-inspector.rst` — **Cache Inspector (לוח בקרה של Redis)**: כלי אדמין לצפייה ולניהול של ה-Redis cache: סטטיסטיקות כלליות, חיפוש מפתחות, הצגת TTL וסטטוס, ומחיקה בטוחה של מפתחות.
- `docs/webapp/config-inspector.rst` — **Config Inspector (סקירת משתני סביבה)**: כלי אדמין שמציג תמונת מצב של הקונפיגורציה ומשתני הסביבה, עם הסתרת ערכים רגישים.
- `docs/webapp/mcp-analytics.rst` — **MCP Analytics (מדידת השימוש בכלי ה-MCP)**: מסך אדמין שמציג את נתוני השימוש בכלי ה-MCP מתוך PostHog — בריאות הכלים, עלות הניווט בריפו, ויכולות שסוכנים ביקשו — עם מצבי הכשל ומשתני הסביבה שהוא דורש.
- `docs/webapp/static-checklist.rst` — **Static Performance & Security Checklist (gzip/br, Cache, SRI)**: להבטיח טעינה מהירה ובטוחה של נכסים סטטיים (CSS/JS/Images).
- `docs/webapp/commands-catalog.rst` — **תחזוקת קטלוג הפקודות (``commands.json``)**: תחזוקת commands.json — הקטלוג שמזין את כרטיסי "קיצורי הדרך" בחיפוש הגלובלי. global_search.js טוען אותו רק בדפים שמכילים את globalSearchInput ואת searchBtn, ומוסיף כרטיסים לפי סוג (chatops/cli/playbook).
- `docs/webapp/code-execution.rst` — **הרצת קוד (Code Execution Playground)**: ב‑WebApp יש כלי שמאפשר להריץ קוד Python מתוך הדפדפן, דרך API ייעודי.
- `docs/webapp/api-reference.rst` — **WebApp API Reference**: רפרנס ה-API של ה-WebApp: ה-endpoints, זרימת האימות מול Telegram, מבנה התשובה, וקודי השגיאה הנפוצים.
- `docs/webapp/bulk-actions.rst` — **Bulk actions (בחירה מרובה)**: דף זה מתאר את יכולות הבחירה המרובה והפעולות הקבוצתיות בממשק הווב.
- `docs/webapp/editor.md` — **⌨️ עורך קוד (WebApp Editor)**: תוכן זה מסביר את טעינת העורך, מנגנון הגיבוי, וניהול העדפות.
- `docs/webapp/markdown-folding.rst` — **Markdown – מצב מצומצם (קיפול כותרות ###) – אדמין בלבד**: מטרת הפיצ'ר: לאפשר לעורכים לקפל מקומית סעיפים לפי כותרות ### (H3) בתצוגת Markdown, בלי לשנות את קובץ ה־Markdown ובלי להשפיע על תצוגה ציבורית.
- `docs/markdown_style_guide.rst` — **מדריך סגנונות וארכיטקטורת Markdown**: המסמך הזה הוא Source of Truth לעיצוב וארכיטקטורת Markdown בפרויקט. הוא מיועד למפתחים ול‑QA ויזואלי.
- `docs/webapp/smooth-scrolling.rst` — **Smooth Scrolling (WebApp) — מדריך תמציתי לסוכני AI**: מנגנון הגלילה החלקה של ה‑WebApp כבוי כברירת מחדל ואינו מופיע בהגדרות; העמוד מסביר למה, מה נשאר פעיל דרך CSS נייטיבי, ואיך מדליקים אותו לניפוי בלבד.
- `docs/webapp/system-modules.rst` — **מודולים פנימיים ב-WebApp**: הקבצים הבאים בתיקיית webapp/ מנהלים תשתיות שאינן מכוסות במדריכים קודמים. העמוד מסביר את ה‑API, התלויות והסיבות לכל רכיב כדי שיהיה אפשר להרחיב או לדבג במהירות.

## Frontend > Theming

- `docs/webapp/theming_and_css.rst` — **מערכת ערכות הנושא והטוקנים החדשה**: ארכיטקטורת הצבעים, משתני ה-CSS והבדיקות שנדרשות לשימור חוויית הממשק בכל ערכות הנושא. מקור האמת לכל שינוי ב-CSS של ה-WebApp.
- `docs/webapp/custom_themes_guide.rst` — **ערכות נושא מותאמות אישית – מדריך מקיף**: מדריך זה מכסה את כל היבטי מערכת ערכות הנושא המותאמות אישית (Custom Themes) – מייבוא VS Code themes ועד יצירה ידנית, הגדרות מתקדמות והדגשת תחביר.
- `docs/webapp/language-icons.rst` — **אייקוני שפות התכנות**: כל קובץ ב-Web App מוצג עם אייקון שמייצג את שפת התכנות שלו. עד אוגוסט 2026 אלה היו אמוג'ים (🐍 לפייתון, 📜 ל-JavaScript); היום אלה אייקונים מצוירים בסגנון אחיד — אריח ריבועי עם גרדיאנט וסימן לבן.

## Observability

- `docs/observability.rst` — **אובזרווביליות (Observability)**: המטרות וקהלי היעד, התצורה, בחירת Backend ל-Traces, הגדרת OTLP לסביבות, ואינסטרומנטציה ידנית.
- `docs/observability/background-jobs-monitor.rst` — **Background Jobs Monitor**: פיצ'ר ה-Background Jobs Monitor מספק נראות (Observability) מלאה לכל ה-Jobs הרצים ברקע במערכת, כולל פעולות משתמש דינמיות (Drive, Reminders, Batch Operations).
- `docs/observability/observability_dashboard.md` — **📡 Observability Dashboard & API**: מסך ה-Admin ב-/admin/observability מרכז נתוני ניטור בזמן אמת ל-SRE ולמפתחים: כרטיסי מצב וגרפים, טבלת התראות עם סינון, ו-API מתועד למסלולי alerts, timeseries, aggregations, export, replay, runbook, quickfix ו-ai_explain.
- `docs/observability/query-performance-profiler.rst` — **Query Performance Profiler**: כלי ניטור לשאילתות MongoDB איטיות: דשבורד ב-WebApp שמציג את השאילתות הכבדות, ה-API שמאחוריו, ומה הכלי במפורש אינו עושה.
- `docs/observability/quick_fix_rules.md` — **🧠 Quick Fix חכם (Queue Delay + עומס/DB) – הנחיות למפתחים ולסוכני AI**: המטרה של Quick Fix היא לתת המלצה קצרה, בטוחה ושימושית על “מה לעשות עכשיו”, לפי אותות שאנחנו כבר מודדים.
- `docs/observability/asyncio-loop-safety.rst` — **Asyncio תחת WSGI: הרצת קורוטינות בבטחה**: ב-WebApp שרץ כ-Flask על WSGI עם worker של gevent, קוד סינכרוני אינו יכול להריץ לולאת asyncio בבטחה — גרינלטים חולקים OS thread, ו-asyncio שומר את מצב הלולאה הרצה ברמת ה-thread. העמוד מסביר את המנגנון, את התסמינים, ואת…
- `docs/visual-rule-engine.rst` — **Visual Rule Engine - מנוע כללים ויזואלי**: מנוע כללים ויזואלי ליצירת התראות מורכבות מהממשק בלי לכתוב קוד: זרימת ההחלטה, מסך הכללים, יצירה והפעלה, וסכמת ה-JSON של כלל.
- `docs/observability/coverage_report.rst` — **Coverage Report (Runbooks / Quick Fixes)**: עמוד ה-Coverage נועד להיות Gap Analysis קבוע: To‑Do List לצוות שמראה אילו alert_type נצפו במערכת ועדיין חסר להם Runbook/Quick Fix, ואילו הגדרות בקונפיג הפכו ליתומות.
- `docs/api/ai_explain.md` — **🧠 Observability AI Explain API**: שירות ה-AI שמתרגם הקשר של התראה להסבר קצר בשפה טבעית: הבקשה והתגובה של POST /api/ai/explain, האימות והבקרות, וקודי השגיאה.
- `docs/rate-limiting.rst` — **Rate Limiting**: מערכת הגבלת קצב אחודה לבוט ולווב, עם Shadow Mode, Soft‑Warning ב‑80% ועקיפת מנהלים.
- `docs/observability/guidelines.md` — **📊 הנחיות Observability ואירועים**: מטרה: לקבוע תבנית ברורה ללוגים ולאירועים, להפחית רעש, ולאפשר תחקור מהיר בעזרת request_id.
- `docs/logging_schema.rst` — **סכמת לוגים**: סכמת הלוגים: שדות החובה והשדות המומלצים בכל רשומה, דוגמה מלאה, וטקסונומיית קודי השגיאה.
- `docs/metrics.rst` — **מדדים (Metrics)**: המדדים שהמערכת חושפת ב-/metrics: המטריקות הקיימות, מדדי ה-handlers והפקודות, מטריקות OpenTelemetry, ודוגמאות PromQL ו-SLO.
- `docs/resilience.rst` — **Resilience לשירותים חיצוניים**: שכבת Retry ו-Circuit Breaker לקריאות חוץ. היא חלה על קריאות שעוברות דרך http_sync.py ו-http_async.py; שירותים שקוראים ישירות ל-requests, httpx או aiohttp אינם מכוסים עדיין.
- `docs/alerts.rst` — **התראות (Alerts)**: מערכת ההתראות: חוקי ברירת המחדל, איך מתאימים אותם, מדדי Health ו-Startup ל-Prometheus, קונפיגורציית alert_manager, ובדיקת הזרימה מקצה לקצה.
- `docs/observability/log_based_alerts.rst` — **התראות מבוססות לוגים (Log‑based Alerts)**: התראות שנגזרות מזרם הלוגים של האפליקציה: סיווג שגיאות לפי חתימות, Allowlist, קיבוץ אירועים ו-Cooldown, עם קבצי הקונפיג ומשתני הסביבה שמפעילים אותן.
- `docs/observability/log-aggregator.rst` — **מנוע ניתוח לוגים (Log Event Aggregator)**: הארכיטקטורה, קבצי הקונפיג, הרצה מקומית ב-CLI, השילוב במערכת, וניפוי התקלות הנפוצות.
- `docs/sentry.rst` — **Sentry**: ברירת מחדל: Sentry מציג Issues בממשק ושולח מיילים, אבל לא מזרים את זה אוטומטית למערכת ההתראות הפנימית שלנו (Telegram + Observability).
- `docs/runbooks/incident-checklist.rst` — **Incident Checklist (On‑Call)**: צ'קליסט לתורן בעת פתיחת Incident, וסטטוסי המעקב האחידים שבהם מדווחים עליו.
- `docs/runbooks/logging-levels.rst` — **שינוי רמות לוגים**: איך משנים רמות לוג בזמן ריצה, ומתי כדאי להעלות ל-DEBUG.
- `docs/runbooks/github_backup_restore.rst` — **GitHub Backup & Restore Runbook**: מדריך צעד‑אחר‑צעד לגיבוי ושחזור מאגר GitHub, כולל יצירת נקודת בדיקה (Checkpoint Tag) ושחזור בטוח.
- `docs/runbooks/slo.md` — **Runbooks – SLO Incidents**: ראנבוקים לתקלות SLO: HighErrorRate, חריגת זמינות מתחת ל-99.9%, וחריגת P95 מעל חצי שנייה — עם שאילתות ה-PromQL של כל אחת.

## פריסה ו-Workers

- `docs/deployment/workers.rst` — **עובדי Push**: Web Push מקצה לקצה — דרישות ומפתחות VAPID, המסלול המקומי ב-pywebpush מול עובד ה-Node, החיבור ל-WebApp, מי שולח את התזכורות, צד הלקוח, ובדיקות.

## ChatOps

- `docs/chatops/overview.md` — **ChatOps – סקירה כללית**: העקרונות שמאחורי ChatOps — פלט הבוט כמקור אמת, פקודה אחת לכל החלטה, ואיסור על סודות בפלטים — עם קישורים לעמודי Monitoring, Observability, Git LFS ו-Backup/Restore.
- `docs/chatops/commands.md` — **פקודות ChatOps**: להלן מבנה אחיד לכל פקודה: מתי להשתמש, פרמטרים, הרשאות, מה לחפש בפלט, ודוגמה קצרה אם יש ערך מוסף.
- `docs/chatops/observe.md` — **ChatOps – /observe: הרחבות -v ו- -vv**: מסמך זה מפרט את מצב ההרחבה של הפקודה `/observe` לצורכי תחקור ומהירות תגובה בזמן אמת.
- `docs/chatops/ratelimit.rst` — **הגבלת קצב לפקודות רגישות**: העקרונות מאחורי הגבלת הקצב לפקודות רגישות, הדקורטור שמפעיל אותה, הקונפיגורציה, והשילוב בבוט.
- `docs/chatops/playbooks.md` — **Playbooks – תרחישים נפוצים**: פלייבוקים לתרחישים נפוצים: עלייה ב-p95, שיעור שגיאות מעל אחוז, זיכרון שמטפס, שירות חיצוני איטי, ותקלה חוזרת בתוך רבע שעה.
- `docs/chatops/permissions.md` — **הרשאות ו-Rate Limit**: מי מורשה להריץ אילו פקודות ChatOps, ומהן מגבלות הקצב עליהן.
- `docs/chatops/troubleshooting.md` — **פתרון תקלות (FAQ)**: שאלות נפוצות ופתרון תקלות בהפעלת פקודות ChatOps.
- `docs/chatops/faq.md` — **שאלות נפוצות**: איך נמנעים מדליפת סודות?

## סוכני AI

- `docs/ai-agents/guide.md` — **🤖 מדריך לסוכני AI**: מטרה: לקצר זמן חיבור של סוכנים לפרויקט, לשמור על איכות ועמידה במדיניות.

## Observability – Advanced

- `docs/observability/events_catalog.rst` — **קטלוג אירועים קנוניים**: הקטלוג הקנוני של שמות האירועים — GitHub, שיתוף ווב, התראות, Repo Analyzer ואירועי ביזנס — עם הכלל לשמות ב-snake_case ובלי PII.
- `docs/observability/error_codes.rst` — **מילון קודי שגיאה (Error Codes)**: הקודים הקנוניים, דוגמאות מיפוי מחריגה לקוד, והנחיות לשימוש בהם.
- `docs/observability/tracing_hotspots.rst` — **Tracing ממוקד בנקודות חמות**: מדריך קצר להתמקדות ב‑Tracing בנקודות בעלות השפעה גבוהה (Hotspots) בבוט וב‑WebApp.
- `docs/observability/metrics_promql.rst` — **שאילתות PromQL שימושיות**: שאילתות מוכנות לזמן תגובה, לשיעור שגיאות ולאירועי ביזנס.
- `docs/observability/alerts_playbook.rst` — **Playbook קצר להתראות**: הזרימה מזיהוי האירוע ועד שליחת ההתראה, הקישורים בקוד, וכיוונון רעש.

---

עמודי פיגום autodoc שסוננו: 92. עמודים שנסרקו: 229.
