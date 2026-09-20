# INTEGRATION — איך הידע מהריפו הזה מגיע לסשנים בזמן אמת

הספרייה הזו שווה בדיוק כמה שהיא נקראת **בזמן המימוש**. המסמך הזה מגדיר
שלושה מנגנונים שמחברים אותה לעבודה השוטפת, ותהליך אחד שמונע ממנה להתיישן.

**עקרון החלוקה:** `CLAUDE.md` של פרויקט מכיל *טריגרים* — מתי לקרוא ומה.
הריפו הזה מכיל את *הידע* — למה, איך מזהים, ומה false positive. לא מעתיקים
את הידע לפרויקטים (הוא מתיישן שם); מעתיקים רק את ההפניה.

---

## 1. בלוק הטריגרים ל-CLAUDE.md (לכל פרויקט פעיל)

מדביקים ב-`CLAUDE.md` של הפרויקט את התבנית שלמטה, ואת שורות הטבלה שבתוכה
ממלאים מ-**§2** לפי ה-stack של הפרויקט. שני החלקים יחד הם הבלוק — התבנית
לבדה חסרה את הטריגרים, והשורות לבדן חסרות את הוראת הקריאה.

דרכי קריאה, לפי מה שזמין בסשן: mirror של הריפו הזה ב-CodeKeeper
(`codekeeper_search_repo` / `codekeeper_get_repo_file`), או ישירות
מ-GitHub (`amirbiron/amir-bug-patterns` הוא ריפו ציבורי).

### תבנית הבלוק

```markdown
## דפוסי באגים — amir-bug-patterns

לפני שאתה נוגע באחד מהנושאים בטבלה — קרא את הקובץ המתאים ב-`amirbiron/amir-bug-patterns` (דרך MCP של CodeKeeper אם יש mirror, אחרת מ-GitHub).
אלה דפוסים שכבר עלו לי בפרודקשן — לא תיאוריה.

| כשאתה נוגע ב... | קרא |
|---|---|
| <נושא> | <קובץ> |
<!-- מלא את השורה הזו משורות הנתונים של הפרויקט שלך ב-§2, ומחק הערה זו. -->

תמיד, בכל פרויקט:
- לפני עטיפת קריאה ב-try/except → `CRITICAL-PATTERNS.md` K11 (כשל בערך החזרה)
- כותב `except` שבולע — `pass`, ערך falsy, או המשך כאילו הצליח → לוג, או הערה שאומרת למה הכשל הזה אינו מעניין. בלעדיהם זה ממצא, גם כשאין ✅ למשתמש במסלול. ‏(`raise` מחדש אינו בליעה) (K11, הצד ההפוך)
- לפני כתיבת טסט חדש → `claude-md-snippets/testing.md`
- אחרי שטסט נופל על חריגה → `bugbot-rules/widened-exception-scope.md` (אל תרחיב except)
- לפני העברת סוד כפרמטר URL (`params={"key": ...}`) → `CRITICAL-PATTERNS.md` K14. ה-SDK של הניטור רושם את השאילתה בעצמו, בכל בקשה מוצלחת.

### סגירת הלולאה (חובה, לא רשות)
1. **ריוויוור (cubic/qodo/CodeRabbit/claude) תפס דפוס אמיתי** שאינו ב-amir-bug-patterns → פתח שם PR שמוסיף אותו (מסמך מקור + הצלבה לפי ה-README), **וגם** הוסף שורת טריגר לטבלה כאן.
2. **אתה בעצמך זיהית דפוס חוזר אצלך** (תיקנת פעמיים את אותו סוג טעות) → אותו תהליך בדיוק.
3. דפוס בלי שורת טריגר = דפוס שלא ייקרא. שני הצעדים הם צעד אחד.
4. **טריגר מזהה מה אתה מקליד, לא באיזה מצב אתה נמצא.** ‏`LOCK_FAIL_OPEN` ו-`0.0.0.0` רואים על המסך; "מסלול שרץ גם ברקע" ו"אחד מארבעת הנתיבים האלה" הם דברים שצריך **לדעת**. שורה שדורשת את הידע הזה כתנאי כניסה דורשת בדיוק את התשובה שהיא אמורה לתת, ולכן לא תידלק — התנאי שייך למסמך, לא לשורה. ומאותה סיבה: לתאר **מחלקה** ולא למנות מופעים, כי רשימה מתיישנת ברגע שנוסף המופע הבא.

> [!IMPORTANT]
> **שורה ממופתחת לפי מה שיהיה מול העיניים, לא לפי הקטגוריה של הדפוס.**
> ‏U3 היה מתועד, והייתה לו שורה — `PyGithub / קריאות SDK חיצוני` — והיא לא
> נדלקה על ולידציה של ערך שהגיע מגוף JSON. הסיבה: השורה ממופתחת לפי מה
> שאתה **קורא לו**, והדפוס הוא על מאיפה ה**נתון** הגיע. רוב הדוגמאות של
> U3 אינן קריאות SDK בכלל. מי שכותב את הקוד מסתכל בטבלה, לא מוצא שורה,
> וממשיך.
>
> ולכן גם: **השורה מצביעה על הכלל הכללי ישירות.** הפניה לקובץ סטאק
> שמצליב לכלל היא קפיצה שנייה, ואותה עושים רק אחרי שכבר החלטת שהמקרה
> שלך בצורת אותו סטאק — כלומר בדיוק ההחלטה שהטבלה אמורה לחסוך.
>
> המבחן לפני שכותבים שורה: **האם מי שעומד לכתוב את הקוד יזהה את עצמו
> בניסוח הזה, לפני שהוא יודע מה הבאג?** אם לא — הניסוח לפי הקטגוריה, לא
> לפי המשימה.

התהליך המלא והמיפוי לשאר הפרויקטים: `INTEGRATION.md` באותו ריפו.
```

### למה זה עובד
- `CLAUDE.md` נקרא בכל סשן ממילא — אין תלות בזיכרון של אף אחד.
- הטבלה קצרה (שורות בודדות) — לא מנפחת את הקובץ.
- הידע נשאר במקום אחד ומתעדכן במקום אחד.

### והסניפטים האוניברסליים (universal / critical / testing)?

ה-README (סעיף "איך להחיל על **פרויקט חדש**") אומר להדביק את שלושתם —
~70 שורות (עם `hebrew.md` — ~90, המספר שב-README). שני המסמכים לא סותרים, כי הם מדברים על שני מצבים:

- **פרויקט חדש**: מדביקים את שלושת הסניפטים במלואם (צעד 1 ב-§4 כאן).
  אין עדיין CLAUDE.md גדול, וה-70 שורות הן ה-baseline שכל השאר נבנה עליו.
- **פרויקט קיים עם CLAUDE.md מבוסס**: לא מדביקים אף אחד מהם במלואו — זה מנפח קובץ שכבר עמוס ויוצר עותק שמתיישן. מה כן, פר-סניפט: `testing.md` כבר מופנה מבלוק הטריגרים (שורת "לפני כתיבת טסט חדש") — ההפניה מספיקה; `universal.md` ו-`critical.md` נשארים בהפניה דרך הטריגרים של §2, ו**כלל בודד מתוכם שהדפוס שלו כבר עלה בפרויקט נפרס inline בבלוק** — כמו K11 ב-`CLAUDE.md` של CodeBot, שנכתב שם בגוף הטקסט כי הוא תפס את הריפו הזה שלוש פעמים. עלה דפוס נוסף בפרויקט ← מוסיפים גם את הכלל שלו inline, לא את כל הסניפט.

---

## 2. מיפוי פר-פרויקט — מה ממלא את הטבלה שב-§1

> ⚠️ **מה שלמטה הוא רק שורות הטבלה, לא הבלוק להדבקה.**
> הטבלאות כאן נראות שלמות (יש להן כותרת ושורת מפריד) — אבל הן רק החלק
> שמשתנה בין פרויקטים. אם תדביק רק אותן, סוכן יראה `CRITICAL-PATTERNS.md`
> ולא יידע שזה ריפו אחר, ולא יקבל את הכללים הקבועים ולא את סגירת הלולאה.

**איך מרכיבים, בשני צעדים:**

1. קח את **התבנית המלאה מ-§1** — היא נותנת את המעטפת: הוראת הקריאה
   (מאיפה מביאים את הקבצים), שלושת הכללים שחלים תמיד, וסגירת הלולאה.
2. החלף בה את שורת ה-placeholder `| <נושא> | <קובץ> |` בשורות של הפרויקט
   שלך מהרשימה כאן — **רק שורות הנתונים**. אל תעתיק את שורת הכותרת
   (`| כשאתה נוגע ב... | קרא |`) ואת שורת המפריד (`|---|---|`): הן כבר
   קיימות בתבנית, והעתקה שלהן תיצור כותרת כפולה באמצע הטבלה.

**דוגמה חיה, כבר מודבקת בפועל:** הסעיף *"דפוסי באגים — amir-bug-patterns"*
בסוף [`CLAUDE.md` של CodeBot](https://github.com/amirbiron/CodeBot/blob/main/CLAUDE.md).
שם רואים את התוצאה המורכבת — כולל התאמות מקומיות שהתבנית לא מכתיבה
(שורת "מתי להשתמש" בסגנון הריפו, וכלל K11 שנפרס בגוף הטקסט כי הוא זה
שכבר עלה שם שלוש פעמים). התבנית היא בסיס, לא חוזה נוקשה.

השורות עצמן, לפי ה-stack של כל פרויקט:

### CodeBot = CodeKeeper — ריפו אחד: `amirbiron/CodeBot`
(בוט טלגרם + webapp + MongoDB/GridFS + MCP + ChatOps + Sphinx docs.
CodeKeeper הוא שם המוצר, CodeBot הוא שם הריפו — לא שני פרויקטים.)

| כשאתה נוגע ב... | קרא |
|---|---|
| שמירה/מחיקה שמסתיימת בהודעת ✅ למשתמש | `CRITICAL-PATTERNS.md` K11 |
| קאש / invalidation | `bugbot-rules/return-value-failure-unchecked.md` §4 |
| דגל שמצהיר "מטא-דאטה בלבד" (`npm install --package-lock-only`, `django-admin migrate --fake`), או רשומה שמתעדכנת בנפרד מהעבודה שהיא מתארת | `bugbot-rules/state-record-without-state-change.md` |
| callbacks / handlers מקביליים, מזהים מבוססי-זמן | `CORE-PATTERNS.md` U1 |
| `find_one_and_update` / `upsert` / תפיסת ג'וב | `CORE-PATTERNS.md` U1 + `bugbot-rules/race-toctou.md` |
| PyGithub / קריאות SDK חיצוני | `BY-STACK/external-sdk.md` |
| **ערך שהגיע מחוץ לתהליך** — גוף JSON, payload, כותרת, ENV, פלט של LLM, CSV, או ערך שמשתמש הקליד | `CORE-PATTERNS.md` U3 + `bugbot-rules/external-input-isinstance.md` |
| חיתוך או מדידת אורך של טקסט (`$substrBytes`, `$strLenBytes`, `encode()[a:b]`, תקרת אורך שנשלחת החוצה) | `BY-STACK/hebrew-source.md` H6 + `bugbot-rules/hebrew-source-and-data.md` §6 |
| הרכבת URL/מחרוזת שמכילה סוד, הודעות חריגה, ניקוי לוגים/Sentry | `CRITICAL-PATTERNS.md` K13 + `bugbot-rules/secret-in-derived-text.md` |
| קריאה ל-API עם מפתח/טוקן בפרמטרים, או שינוי ברשימת דפוסי הניקוי | `CRITICAL-PATTERNS.md` K14 + `bugbot-rules/secret-in-url-query.md` |
| מסיר שורת לוג, או עוטף אותה ב-guard שמונע הערכת ארגומנטים (הטריגר הנפוץ: תיקון PII) | `bugbot-rules/side-effect-riding-on-log-line.md` |
| גייטינג אדמין — רשימת היתר, התחזות (`/admin/impersonate/*`), או דגל שמרחיב הרשאה בהיעדר קונפיג (`CHATOPS_ALLOW_ALL_IF_NO_ADMINS`) | `CRITICAL-PATTERNS.md` K3 + `bugbot-rules/privilege-escalation-unverified.md`; לדגל עצמו — K12 סעיף 3 (fail-closed, בלי default שקט) |
| `LOCK_FAIL_OPEN` — מריץ polling בלי מנעול ה-singleton, כלומר שני מריצים במקום אחד | `CORE-PATTERNS.md` U1 |
| העלאת שרת HTTP או שינוי כתובת האזנה (`0.0.0.0`) | `CRITICAL-PATTERNS.md` K5 + `bugbot-rules/network-exposed-without-auth.md` |
| `docs/**/*.rst` | `bugbot-rules/line-number-coupling.md` |
| טסטים עם סטאבים ידניים | `TESTING-PATTERNS.md` + `bugbot-rules/widened-exception-scope.md` |
| אתחול עצל של משאב משותף (חיבור, לקוח, pool, קאש) — או **הסרה** של התנהגות מנוונת שקיימת מזמן | `CRITICAL-PATTERNS.md` K15 + `bugbot-rules/lazy-init-guard-publish-order.md` |
| `getattr(x, "y", None)` או `except` שאחריו **מסלול חלופי בגלל כשל** — לא ערך ברירת מחדל, ולא זיהוי יכולת סטטי | `bugbot-rules/silent-fallback-to-worse-path.md` |
| CSP, כותרות תגובה, או עמוד שנגיש בלי התחברות | `BY-STACK/browser-policy.md` |
| `create_index` — ובמיוחד `partialFilterExpression` או `sparse=True` | `BY-STACK/mongodb.md` דפוס 1 + `bugbot-rules/mongo-index-and-operator-traps.md` — אופרטורים שהפילטר החלקי לא מקבל, ואתחול שבולע את השגיאה |
| צינור `aggregate` — `$project`, `$sort`, `$group` — או `find_one` בתוך לולאה | `RECURRING-PATTERNS.md` R8 + `bugbot-rules/work-disproportionate-to-answer.md` |
| `startswith` / `endswith` על נתיב, URL או דומיין | `CRITICAL-PATTERNS.md` K16 |
| `replace(tzinfo=` · `datetime.now()` **בלי** אזור זמן · כל `date.today()` · הצגת תאריך למשתמש | `RECURRING-PATTERNS.md` R7 |
| **ברמה העליונה של מודול** (מחוץ לכל פונקציה): `Thread(`, `.start()`, `scheduler`, `asyncio.create_task`, לקוח או חיבור שנבנה מ-`os.environ`, או קריאת רשת, מסד או קובץ | `bugbot-rules/import-time-side-effects.md` |
| שינוי שנעשה כדי לספק לינטר: הזזת `import`, ניקוי אזהרת escape, הרחבת `except` | `bugbot-rules/linter-fix-changes-runtime-behavior.md` |
| מחיקה / שיתוף / שינוי שם לפי `_id` שהגיע מהממשק, ‏`created_at`, או פעולה גורפת על `code_snippets` ו-`large_files` | `bugbot-rules/logical-entity-vs-version-document.md` |
| שליחה לספק עם תקרת קלט (טוקנים, אורך שדה), או `value[:LIMIT]` לפני שמירה | `bugbot-rules/silent-truncation-at-sink.md` |
| `clientX` בחיסור, ‏`left`/`right`, גרירה, שינוי גודל, או הצמדה ל-viewport | `BY-STACK/hebrew-source.md` H7 + `bugbot-rules/rtl-geometry-and-clamp.md` |
| `EWMA` / `_ewma`, ‏`anomaly_detected`, ‏`cooldown`, ‏`first_ts`, ‏`adaptive_*_threshold_*` | `RECURRING-PATTERNS.md` R9 + `BY-STACK/observability.md` |
| הרצה ראשונה של ג'וב סנכרון: `baseline`, `last_*_check_time`, `if not last_seen` | `BY-STACK/cron-jobs.md` דפוס 10 — מה ההרצה הראשונה שולחת |
| תגית `<script>` / `<link>` חדשה בתבנית, או כתיבת `Cache-Control` | `BY-STACK/browser-policy.md` B4–B5 + `bugbot-rules/stale-asset-cache-policy.md` |
| **לפני כתיבת פונקציה חדשה** שמפרמטת, מסננת, מחשבת או ממפה — גודל, תאריך, אייקון, שם שפה, רשימת ערכים, שאילתה | `RECURRING-PATTERNS.md` R6: `grep` על שם התופעה לפני שכותבים. יש עותק — מאחדים |
| `except TypeError` / `except AttributeError` סביב קריאה ל-SDK חיצוני | `bugbot-rules/dead-parameter-external-api.md` |
| route ב-`GET` שגופו מוחק, מאפס או מריץ פעולה בלתי הפיכה | `bugbot-rules/auth-before-irreversible-action.md` §5 |
| `errorhandler(Exception)` גורף, או מגבלת קצב שחלה על `/` ועל `/health` | `bugbot-rules/blanket-policy-silent-block.md` §7–8 |

**המימוש הנכון של K11 בריפו הזה — להעתיק ממנו, לא רק להיזהר:** `mcp_server/backend.py:save_file` מחזיר `{"ok": False, "error": "save_failed"}` **כשמסלול השמירה מחזיר false** (חריגת מסד עולה הלאה ואינה מומרת לתשובת כשל), ובהצלחה קורא את המסמך מחדש מהמסד במקום להחזיר את מה שביקשנו לכתוב. הלקח הוא *קרא את המצב, אל תהדהד את הבקשה* — ולא שזה אטומי: הקריאה החוזרת היא לפי שם הקובץ ולא לפי המזהה שנכתב, ומספר הגרסה נבחר ב-read-then-write, ולכן שתי שמירות מקבילות לאותו שם יכולות להחזיר זו את הגרסה של זו. זה עצמו מופע של U1 בתוך הקוד שמשמש כדוגמה ל-K11. ולכן אין כאן שורת טריגר על "כלי MCP שכותבים": K11 כבר תמיד-דלוק ב-§1, והאתר הזה כבר עומד בו — שורה שמצביעה על כלל שחל תמיד, באתר שכבר תקין, מלמדת לדלג על הטבלה.

### ai-business-bot (Flask + SQLite WAL + OpenAI/Gemini + Twilio/Meta + multi-tenant)

| כשאתה נוגע ב... | קרא |
|---|---|
| webhook handlers (Twilio/Meta/Telegram) | `BY-STACK/webhooks.md` |
| קריאות OpenAI/Gemini/Graph API | `BY-STACK/external-sdk.md` |
| jobs מתוזמנים (תזכורות, purge תיקון 13) | `BY-STACK/cron-jobs.md` |
| לוגים בנתיב שיחות לקוח | `bugbot-rules/pii-in-logs.md` (CRITICAL — שיחות = PII) |
| בידוד tenant / ContextVar / שאילתות בטבלאות רב-דייריות | `CRITICAL-PATTERNS.md` K12 + `bugbot-rules/tenant-row-scoping.md` |
| threads של בוט/worker לצד ה-webapp | `bugbot-rules/background-thread-liveness.md` |
| שליחת הודעה + עדכון סטטוס | `claude-md-snippets/universal.md` §5 (linked-field atomicity) |

### Campaign AI (FastAPI + Supabase/Postgres + Meta Marketing API + סליקה)

| כשאתה נוגע ב... | קרא |
|---|---|
| `date.today()` / `datetime.now()` / השוואת תאריך מול קלט משתמש | `RECURRING-PATTERNS.md` R7 |
| baseline, חלון השוואה, או מדד שמפעיל פעולה אוטומטית | `RECURRING-PATTERNS.md` R9 + `BY-STACK/observability.md` |
| רשימת ערכים או קבוע שמופיע גם ב-Python וגם ב-SQL / JS | `RECURRING-PATTERNS.md` R6 — טסט שמשווה, לא הערה שמבקשת לזכור |
| `/health` או כל endpoint שנדגם בתדירות גבוהה | `bugbot-rules/work-disproportionate-to-answer.md` §6 |
| migrations / שאילתות / pagination | `BY-STACK/postgres.md` |
| webhook Upay→Summit, חיוב פר-קמפיין | `BY-STACK/webhooks.md` + `CORE-PATTERNS.md` U1 (כסף = strict) |
| Meta Marketing API / OpenAI | `BY-STACK/external-sdk.md` |
| endpoints של auth / roles | `claude-md-snippets/critical.md` (K1, K3, K10) |
| סטטוסים של קמפיין/חיוב | `BY-STACK/state-machine.md` |
| jobs מתוזמנים (חיוב מחזורי, סיום trial, סנכרון קמפיינים) | `BY-STACK/cron-jobs.md` |

### Noa_Leads (FastAPI + Next.js + Supabase + Calendar/Gmail)
הפרויקט הוא מקור P1..P14 — רוב הדפוסים כבר נולדו כאן. הטריגרים:

| כשאתה נוגע ב... | קרא |
|---|---|
| React forms / dropdowns מסונכרני-backend | `BY-STACK/react-frontend.md` |
| sync tokens / webhooks של Calendar/Gmail | `BY-STACK/webhooks.md` + `CORE-PATTERNS.md` U1 |
| סטטוסים ו-activity log | `BY-STACK/state-machine.md` |
| SQLAlchemy async | `BY-STACK/async-orm.md` |

### פרויקטים קטנים (TaskFlow, myAgent, APIWatchBot...)
מספיק הבלוק האוניברסלי: K11 + testing + הכלל הרלוונטי היחיד לפי ה-stack
(myAgent: webhooks; TaskFlow: cron-jobs לתזכורות; סורק לידים / Social Publisher: `bugbot-rules/content-hash-normalization.md` — dedup של תוכן חיצוני).

---

## 3. נוסח ל-Code Review Instructions של הבאגבוטים

להדבקה בממשק הווב של cubic / qodo / CodeRabbit (שדה custom instructions /
review guidelines). מנוסח תמציתי כי הוא מוזרק לכל ריוויו.

### הבלוק להדבקה

```text
בנוסף לבדיקות הרגילות, אכוף את הכללים האלה — כולם דפוסים שכבר גרמו
לבאגים אמיתיים בפרויקטים שלי (ריפו הרפרנס: github.com/amirbiron/amir-bug-patterns):

1. ערך החזרה ככשל: לכל קריאה עטופה ב-try/except או שאחריה דיווח הצלחה — ודא שהקורא בודק את הערך החוזר אם הפונקציה מחזירה None/False/0 בכשל במקום לזרוק. דגל אדום: `saved = True` קבוע אחרי קריאה, או הודעת ✅ למשתמש בלי תנאי. (בפרט: save_backup_bytes, delete_pattern, rowcount.)

2. הרחבת except: כל דיף שמרחיב `except X` ל-`except Exception` או עוטף קוד קיים ב-try/except חדש — דרוש נימוק. אם באותו PR יש טסט שנופל בלי ההרחבה, השורש כנראה בסטאב/fixture של הטסט, לא בקוד.

3. race/TOCTOU: קריאה חיצונית בלתי-הפיכה (שליחה, תשלום, draft) לפני INSERT מקומי עם UNIQUE — דגל. מזהה ייחודי מבוסס-timestamp ברזולוציית שניות — דגל (התנגשות בכתיבות מקבילות).

4. טסטים: טסט חדש שנוסף עם תיקון חייב להיכשל בלי התיקון — אם ה-assert מתקיים גם בקוד הישן (למשל בודק תוצאה ריקה שנכונה בשני המקרים), דגל. הבדיקה עוברת דרך הממשק של הצרכן האמיתי, לא דרך המפרט.

5. הפניות שורה: `literalinclude` עם `:lines:` כשיש חלופת `:pyobject:` — דגל. הפניית file.py:123 בתיעוד ארוך-חיים — דגל.

6. אבטחה (strict תמיד): PII בלוגים (email/phone/message body), secrets ב-response, innerHTML בלי sanitizer, X-Forwarded-For להחלטות security, קרדנציאל שנשלח לפני שנשמר (fail closed), ובטבלה רב-דיירית — SELECT/UPDATE/DELETE עם predicate על ה-tenant המאומת (כולל get-by-id ו-exports), INSERT/UPSERT עם tenant שנגזר מה-context המאומת ולא מהלקוח (ו-conflict key שכולל tenant), ו-context של tenant בלי default שקט.

7. קלט חיצוני ופילטרים: לפני `.get()`/`.strip()`/iteration על ערך מ-API /  webhook / output של LLM — `isinstance` guard; מספר חיצוני — `isfinite`.  פילטר על ערוץ/type יחיד כשיש לישות כמה variants — דגל. סדר הפילטרים: security/deny קודם, business/override אחריו — לא הפוך. פיצ'ר שנחסם בשקט (blocklist במקום allowlist, CSP `'none'` בלי היתר לחריג) נראה למשתמש ככפתור שבור — דגל.

עברית בהערות קוד היא המוסכמה בריפו — אל תדגל עליה.
```

### הערות
- **cubic** מוגבל באורך ההוראות — אם צריך לקצר, סעיפים 1, 2, 4 הם
  העדיפות (הדפוסים שחזרו בפועל); 6 מכוסה חלקית על ידי הסורקים שלו ממילא.
- **qodo** תומך ב-best practices file ברמת ריפו (`best_practices.md`) —
  אפשר במקום ההדבקה בממשק.
- **הבלוק הוא הליבה הכללית, לא כל הכללים שבתיקייה.** הוא מכסה את הדפוסים
  שחלים על כל stack (סעיפים 1–7) ואת ה-CRITICAL של אבטחה שכבר כלולים בסעיף 6.
  כללי stack מהתיקייה — `postgres-null-cas`, `react-stale-state-on-prop`,
  `cron-terminal-state`, `pagination-tiebreaker`, וכו' — **לא** נכנסים
  לכאן; הם מוזרקים רק בריפו עם ה-stack התואם, לפי המיפוי ב-§2. הזרקת
  **כולם** לכל ריוויו מדללת את תשומת הלב לכל כלל בודד — לכן הבלוק מכוון
  ולא ממצה. (בכוונה בלי מספר: הוא מתיישן בכל כלל שנוסף, וזה בדיוק R6.)
- כלל שמתווסף לריפו הזה → לעדכן גם את הבלוק הזה, אם הוא מספיק כללי.

---

## 4. תהליך פתיחת פרויקט חדש

צ'קליסט, בסדר הזה — כ-20 דקות סה"כ:

1. **CLAUDE.md ראשוני**: להדביק את שלושת הסניפטים האוניברסליים —
   `claude-md-snippets/universal.md`, `claude-md-snippets/critical.md`,
   `claude-md-snippets/testing.md` (שלושת הסניפטים יחד ≈ 70 שורות). בפרויקט עברי: גם
   `claude-md-snippets/hebrew.md`.
2. **decision tree של ה-stack** (README §2): לכל "כן" — להדביק את
   ה-snippet המתאים ולרשום את קובץ ה-BY-STACK בטבלת הטריגרים.
3. **בלוק הטריגרים** (סעיף 1 כאן): להדביק את התבנית עם השורות של
   ה-stack + כללי סגירת הלולאה.
4. **באגבוטים**: לחבר את הריפו ל-cubic/qodo ולהדביק את הבלוק מסעיף 3.
5. **Day-1 defaults** (`MIGRATION-NOTES.md` §3): להחליט אסטרטגיית
   idempotency, convention ל-React state sync (אם רלוונטי), ו-guards
   לקלט חיצוני — ולרשום את ההחלטות ב-CLAUDE.md.
6. **mirror ב-CodeKeeper** לריפו החדש (אם הוא הולך להיות פעיל) — כדי
   שכלי ה-MCP יראו אותו.
7. **שורה ב-INTEGRATION.md** (הקובץ הזה): להוסיף את הפרויקט למיפוי
   בסעיף 2.

---

## 5. מה נשאר ידני בכוונה

- **אין הזרקה אוטומטית של דפוסים בכל סשן** (primer/hook גלובלי): סט
  הדפוסים רחב מדי להזרקה קבועה, והרלוונטיות תלוית-משימה. הטריגרים
  ב-CLAUDE.md הם הפשרה הנכונה — נטענים תמיד, שוקלים כמעט כלום, ומפנים
  לקריאה רק כשנוגעים בנושא.
- **אפשרות עתידית** אם הטריגרים לא יספיקו: PreToolUse hook פר-ריפו
  שמזהה עריכה בקובץ "רגיש" (למשל `*webhook*`, `*handler*`) ומדפיס
  תזכורת חד-פעמית לקרוא את הדפוס המתאים. לא ממומש — קודם רואים אם
  השכבה הפשוטה עובדת.
