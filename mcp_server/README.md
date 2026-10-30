# CodeKeeper MCP Server

שרת [MCP](https://modelcontextprotocol.io) שחושף את **הקבצים והאוספים** השמורים של
המשתמש ל‑Claude — **Claude.ai** (Custom Connector דרך OAuth), שהמחבר שלו מגיע גם ל‑**Claude Desktop** ול‑**Claude Code** שמחובר עם החשבון, ו‑**Claude Code** שמחובר בדרך אחרת (טוקן אישי). קריאה זמינה תמיד; **כתיבה** (יצירה/עדכון קובץ) מאחורי
הרשאת `write` מפורשת. אין מחיקה.

> תכנון מלא: `FEATURE_SUGGESTIONS/FEATURE_MCP_CLAUDE_INTEGRATION.md`

---

## מה זה עושה

ניגש ישירות לשכבת ה‑DB הקיימת (`database.db` + `CollectionsManager`), מסונן תמיד לפי
ה‑`user_id` שנגזר מהטוקן. מכבד את חוק ה‑Smart Projection: רשימות/חיפוש לא מחזירים את
שדה ה‑`code` הכבד — תוכן מלא רק ב‑`get_file`.

### הכלים (Tools)

כל הכלים מקודמים ב‑`codekeeper_` (מונע התנגשות עם connectors אחרים). כולם read-only
פרט לכלי הכתיבה, שדורשים הרשאת `write`: על קבצים —
`codekeeper_save_file` (יצירת קובץ **חדש** בלבד)/`codekeeper_edit_file`/
`codekeeper_multi_edit_file`/`codekeeper_append_file`/`codekeeper_update_file_description`; על אוספים —
`codekeeper_add_to_collection`; ועל פתקים — `codekeeper_create_note`/
`codekeeper_create_board_note`/`codekeeper_create_repo_note`/`codekeeper_update_note`/
`codekeeper_note_str_replace`.

<!--
בלי מספר לפני "כלי הכתיבה", בכוונה. הספירה הקודמת ("תשעת") התיישנה ברגע
שנוסף כלי, וזו בדיוק "ספירת מופעים" ש-`docs/doc-authoring.rst` אוסר: מספר
שמשתנה בלי שאף בדיקה תתריע. הרשימה עצמה שימושית ונשארת; מה שהוסר הוא
המונה שאיש לא שומר עליו. מקור האמת לסיווג הוא `readOnlyHint` שכל כלי
מצהיר עליו, ו-`_declares_write` ב-`server.py` גוזר ממנו.
-->


| כלי | תיאור |
|-----|-------|
| `codekeeper_list_files` | רשימת קבצים (מטא‑דאטה בלבד), עם עימוד |
| `codekeeper_search_code` | חיפוש טקסט בקוד → מטא‑דאטה של קבצים תואמים |
| `codekeeper_get_file` | תוכן מלא של קובץ לפי `file_name` או `file_id` (אופציונלי: גרסה) — כשהתשובה נכנסת ב-`OUTPUT_BYTE_BUDGET`; אחרת `answer_too_large` עם הפניה ל-`lines`/`query` (וב-Markdown ל-`toc`/`section`). `lines=[start, end]` מחזיר רק את הטווח, וטווח שאינו נכנס נגמר מוקדם על גבול שורה (`range.truncation_reason: "byte_budget"`); `query="..."` מחזיר את **המופעים** של המחרוזת בקובץ במקום את התוכן, בצורת התשובה של `codekeeper_search_repo` (`count`/`total`/`results` עם `line` ו-`snippet`, ו-`context_lines`). ובקובץ Markdown: `toc=true` מחזיר את מפת הכותרות, ו-`section="..."` סעיף אחד עם `breadcrumb`, טווח שורות, תת-סעיפים ושכנים (עימוד ב-`max_chars`/`offset`, וכל עמוד בתוך `OUTPUT_BYTE_BUDGET` בבתים — עמוד של תווים רחבים נגמר מוקדם, עם `truncation_reason: "byte_budget"`; והמפה, ההצעות והמועמדים נחתכים מהסוף לאותו תקציב, עם הדגל `*_truncated` שלהם) — אותן פונקציות של `codekeeper_docs_get_section`. ארבעת המצבים אינם מצטברים, וכל זוג נדחה בקוד משלו (`query_and_lines`, `toc_and_section`, `section_and_query` וכו'); קובץ שאינו Markdown — `not_markdown`, וקובץ מעל `MAX_FILE_SIZE_FOR_DISPLAY` בבתים של UTF-8 — `too_large_for_sections`. ראו `docs/mcp-server-retrieval.rst` ("קריאה לפי סעיף בקובץ Markdown שמור") |
| `codekeeper_save_file` | **כתיבה:** יצירת קובץ **חדש** בלבד — שם שכבר תפוס נדחה ב‑`file_exists`, ולעדכון קובץ קיים יש `codekeeper_edit_file`/`codekeeper_multi_edit_file`/`codekeeper_append_file` (תוכן) או `codekeeper_update_file_description` (תיאור). בכפוף ל‑`MAX_CODE_SIZE`, ברירת מחדל 100K תווים וניתן להגדלה. `description` עד `FILE_DESCRIPTION_MAX_CHARS` תווים (`file_description.py`); ארוך ממנה — הקובץ נשמר בלי התיאור, ו‑`description_saved: false`. דורש `write` |
| `codekeeper_edit_file` | **כתיבה:** מצא‑והחלף מדויק (`old_string`→`new_string`, אופציונלית `replace_all`) בלי לשלוח את כל הקובץ; גרסה חדשה, משמר שפה/תיאור/תגיות. `expected_content_sha256` (ה-`file.content_sha256` שנקרא) מסרב ב-`conflict`, בלי לכתוב, אם הקובץ השתנה מאז. דורש `write` |
| `codekeeper_multi_edit_file` | **כתיבה:** כמה עריכות בקובץ אחד, **בגרסה אחת**: `edits` היא רשימת זוגות (`old_string`, `new_string`, `replace_all`), שמוחלים לפי הסדר, כל זוג על התוצאה של קודמו — הכל או כלום. זוג שנכשל מחזיר את הקוד של `codekeeper_edit_file` ואת ה-`index` שלו, ושום דבר לא נכתב. עד `MAX_EDIT_PAIRS` זוגות; `expected_content_sha256` כמו ב-`codekeeper_edit_file`. דורש `write` |
| `codekeeper_append_file` | **כתיבה:** הוספת טקסט לסוף קובץ קיים (מוסיף שורת‑הפרדה אם צריך); גרסה חדשה. `expected_content_sha256` כמו ב-`codekeeper_edit_file`. דורש `write` |
| `codekeeper_update_file_description` | **כתיבה:** החלפת ה‑`description` של קובץ קיים בלי לגעת בתוכן. **אינו יוצר גרסה**, ולכן התיאור הקודם אינו נשמר בהיסטוריה (הוא מוחזר בתשובה) ורק הגרסה האחרונה מתעדכנת. תיאור בלבד, בלי תגיות. עד `FILE_DESCRIPTION_MAX_CHARS` תווים — ארוך ממנה נדחה ב‑`description_too_long` (`max_chars`, `actual_chars`), חוץ מהטקסט שכבר שמור. דורש `write` |
| `codekeeper_list_versions` | היסטוריית גרסאות של קובץ (מטא‑דאטה) |
| `codekeeper_list_notes` | פתקים דביקים של קובץ (לפי `file_name`) — אותם פתקים שמוצגים ב‑UI של הוובאפ. `include_content=false` מחזיר את השורות בלי הגוף, עם `content_bytes` (בבתים של UTF-8). רשימה מלאה שאינה נכנסת ב-`OUTPUT_BYTE_BUDGET` — `answer_too_large` עם הפניה ל-`include_content=false`, ולא רשימה חתוכה |
| `codekeeper_get_note` | פתק **בודד** לפי `note_id`: הגוף הנוכחי בדיוק כפי שהוא מאוחסן, כותרת, צבע, `version` (המספר שבו `get_note_version` מחזיר את הגוף הזה — עכשיו, או אחרי הדריסה הבאה **דרך השרת הזה**; עריכה מהוובאפ אינה נכנסת להיסטוריה; נקרא באותה קריאה תחומה כמו הגוף; `null` לגוף ריק) ואיפה הפתק יושב, בארגומנטים שכלי הרשימה המתאים דורש (`orphaned` על פתק ריפו כמו ב-`list_repo_notes`). פתק של משתמש אחר, ופתק ריפו למי שאינו אדמין — `not_found`; פתק שנערך ממש ברגע הקריאה — `conflict` |
| `codekeeper_create_note` | **כתיבה:** יצירת פתק דביק על קובץ קיים; `line` אופציונלי מעגן לשורת מקור (בלעדיו הפתק צף). דורש `write` |
| `codekeeper_update_note` | **כתיבה:** עדכון חלקי של פתק לפי `note_id` (תוכן/שורה/צבע/מוזער) — דורס במקום, אבל התוכן הקודם נשמר כגרסה. דורש `write` |
| `codekeeper_note_str_replace` | **כתיבה:** מצא‑והחלף מדויק **בתוך פתק** (`old_string`→`new_string`, אופציונלית `replace_all`) בלי לשלוח את כל הגוף. אותה סמנטיקה ואותם נוסחי שגיאה כמו `edit_file`. על `conflict` — קוראים את הפתק מחדש ב-`codekeeper_get_note` ומנסים שוב. דורש `write` |
| `codekeeper_list_note_versions` | הגרסאות הקודמות של פתק (מטא‑דאטה בלבד: מספר, זמן, ואורך **בתווים**, לא בבתים כמו `content_bytes`), החדשה תחילה |
| `codekeeper_get_note_version` | תוכן של גרסה **קודמת** אחת; הגוף הנוכחי הוא `codekeeper_get_note`, שגם אומר באיזה מספר הוא ייקרא כאן כשיידרס דרך השרת הזה (עריכה מהוובאפ אינה נכנסת להיסטוריה). השחזור הוא `update_note` עם התוכן שנקרא |
| `codekeeper_list_boards` | הלוחות של המשתמש — משטחים שנושאים פתקים שאינם שייכים לשום קובץ. מייצר את לוח ברירת המחדל בקריאה הראשונה |
| `codekeeper_list_board_notes` | הפתקים שעל לוח יחיד (לפי `board_id` מ‑`codekeeper_list_boards`). `include_content=false` מחזיר אותם בלי הגוף, עם `content_bytes` — ואז `codekeeper_get_note` לפתק בודד; הזרימה ללוח גדול. רשימה מלאה שאינה נכנסת בתקציב — `answer_too_large` שמפנה לזרימה הזו |
| `codekeeper_create_board_note` | **כתיבה:** פתק חדש על לוח — בלי קובץ. `mode` הוא `surface` (יושב על הלוח, ברירת מחדל) או `screen` (צף מול המסך). `title` אופציונלי וייחודי בתוך הלוח. דורש `write` |
| `codekeeper_search_notes` | חיפוש פתקים בשלושת המקומות שפתק יכול לשבת בהם — קובץ, לוח, או קובץ בריפו משוקף. לפי שם כברירת מחדל; `search_content=true` מרחיב גם לגוף הפתק, וזו הדרך למצוא פתק **בלי כותרת**. כל תוצאה מציינת איפה הפתק יושב ולעולם אינה נושאת תוכן — את הפתק קוראים ב-`codekeeper_get_note` לפי המזהה |
| `codekeeper_list_collections` | האוספים של המשתמש |
| `codekeeper_get_collection` | אוסף בודד לפי id |
| `codekeeper_get_collection_items` | הקבצים בתוך אוסף (עם עימוד/סינון תיקייה) |
| `codekeeper_add_to_collection` | **כתיבה:** שיוך קובץ שמור קיים לאוסף קיים. `save_file` **אינו** משייך — זו הקריאה השנייה שמשלימה אותו. נכשל במפורש כשהאוסף או הקובץ אינם קיימים. דורש `write` |
| `codekeeper_docs_get_section` | סקשן בודד מקובץ תיעוד — RST (`docs/*.rst`) או Markdown (בריפו שמגיש `.md`, כמו `amir-bug-patterns`) — במקום קובץ שלם; בלי `section` מחזיר עץ כותרות. כולל breadcrumb/תת‑סקשנים/שכנים לניווט. **קובץ שלם:** `whole_document=true` — הקובץ כולו משורה 1, כולל front matter ומה שלפני הכותרת הראשונה, בלי פרסור (ולכן גם קובץ שמפת הכותרות מסרבת לו); לאדמין גם `codekeeper_read_batch` ו-`codekeeper_get_repo_file`. סעיף וקובץ מדופדפים באותה צורה — כל עוד `truncated` הוא `true` ממשיכים מ‑`next_offset`, וכל עמוד בתוך `OUTPUT_BYTE_BUDGET` בבתים (וגם עץ הכותרות, ההצעות והמועמדים, שנחתכים מהסוף). עדיף על `codekeeper_get_repo_file` לקריאת תיעוד לפי סעיפים |

> **היסטוריית פתקים.** כל עדכון **שמשנה** את ה‑`content` שומר את הגוף הקודם באוסף
> `sticky_note_versions` **לפני** הדריסה — עד 20 גרסאות לפתק (עדכון עם תוכן זהה אינו
> מייצר גרסה, כדי שכפילות לא תדחוף החוצה גרסה שעוד אפשר לשחזר). כשל צילום **עוצר**
> את העדכון (`snapshot_failed`): דריסה אחרי צילום שנכשל היא בדיוק אובדן הנתונים
> שהמנגנון בא למנוע; דריסה שלא קרתה אחרי צילום שהצליח מוחקת את הצילום בחזרה.
> `destructiveHint` נשאר `True` כי אחרי 20 עריכות המקור נדחף החוצה. אוסף נפרד ולא
> מערך מוטבע — שלוש פונקציות הרשימה קוראות בלי פרויקציה.

> **תקרת התשובה.** כלי שקורא תוכן — `codekeeper_get_file`, `codekeeper_list_notes`, `codekeeper_list_board_notes`, `codekeeper_docs_get_section`, וכלי הריפו — מצהיר ב-`tools/list` על `_meta["anthropic/maxResultSizeChars"]` (`OUTPUT_BYTE_BUDGET`, 256,000), כדי ש-Claude Code יכניס את התשובה להקשר ולא ישמור אותה לקובץ (#3460). כל כלי כזה מתאים את התשובה שלו בעצמו, ורשת ב-`AdminAwareFastMCP.call_tool` מסרבת לתשובה שעוברת את מה שהוצהר ורושמת `answer_size_net` בלוג — תפיסה שלה היא באג בכלי. חיתוך או סירוב שיצא ללקוח נרשם ברמת INFO כ-`answer_size_fit` (שם הכלי, שמות הארגומנטים, מספרים) — רק מה שיצא, לפי הכלל שליד `answer_fit.attempt`. תגיות ותיאור ענקיים של קובץ שמור יורדים גם מתשובה מוצלחת כשהם מה שלא נכנס, עם הפניה ל-`codekeeper_update_file_description`. `codekeeper_list_repo_notes` אינו מצהיר, בכוונה. ראו "תקרת התשובה" ב-`docs/mcp-server.rst`.

> **טביעת אצבע לתוכן.** `file.content_sha256` הוא SHA-256 בהקס על בתי ה-UTF-8 של התוכן, בדיוק כפי ש-`codekeeper_get_file` מחזיר אותו (`hashlib.sha256(text.encode("utf-8")).hexdigest()`). ב-`codekeeper_get_file` הוא של הגרסה כולה בכל מצב קריאה, ובכלי הכתיבה של קבצים הוא של מה שנקרא חזרה מהאחסון — לפי ה-`_id` שנכתב, בלי קאש. הסירוב `conflict` של כלי העריכה נושא את ה-hash של הגרסה הנוכחית. לצידו `content_changed`: `false`, או `true` עם `content_diff` ושורת `WARNING` בלי תוכן, או `null` כשהקריאה החוזרת נכשלה (ואז `file` מינימלי בלי hash). רשימות אינן נושאות hash. הפירוט ב-`docs/mcp-server-state.rst` ("טביעת אצבע לתוכן").

**ומה שאין** — כדי לחסוך חיפוש בטבלה אחרי כלי שלא קיים:

- **אין מחיקה בכלל.** לא לקובץ, לא לפתק, לא לפריט באוסף. זו החלטת עיצוב של השירות.
- **אין יצירת אוסף ואין יצירת לוח.** אפשר לקרוא אוספים ולשייך אליהם קובץ, ואפשר
  לכתוב פתק על לוח — אבל את המכולות עצמן יוצרים בוובאפ. חריג אחד: `list_boards`
  מייצר את **לוח ברירת המחדל** בקריאה הראשונה, אם למשתמש אין אף לוח.
- **אין כלי שמחזיר את כל פתקי הריפו בקריאה אחת.** `list_repo_note_paths` מחזיר את
  המפה (נתיב + כמה פתקים), ומשם קוראים כל קובץ בנפרד עם `list_repo_notes`.

### כלי אדמין — דפדפן הריפו ופתקי הריפו

שבעה כלים **לאדמין בלבד** (`ADMIN_USER_IDS`): ארבעה מעל ה‑Repo Sync Engine (bare
mirrors), ושלושה על פתקי ריפו שקוראים/כותבים ל‑`sticky_notes` בלבד. למשתמש שאינו
אדמין כולם גם מוסתרים מ‑`tools/list` וגם חסומים בגוף הכלי (fail‑closed).

**דפדפן הריפו עצמו הוא קריאה בלבד לצמיתות** — אין ולא תהיה עריכה/`commit`/`push`,
וה‑mirrors הם רפליקה חד‑כיוונית מ‑GitHub. `codekeeper_create_repo_note` אינו יוצא מן
הכלל: הפתק נכתב ל‑`sticky_notes` שב‑CodeKeeper והוא הערה **על** הקובץ, לא שינוי בו —
לא ב‑mirror ולא ב‑GitHub.

| כלי | תיאור |
|-----|-------|
| `codekeeper_list_repos` | רשימת הריפואים המשוקפים (מטא‑דאטה) |
| `codekeeper_list_repo_tree` | נתיבי קבצים בריפו (עימוד, סינון תיקייה/ref; בלי תוכן). עמוד שאינו נכנס בתקציב — `page_too_large`, ולא עמוד חתוך (#3481) |
| `codekeeper_get_repo_file` | תוכן קובץ בודד (עד 500KB לקובץ מלא, עד 10MB עם `lines`; בינארי ⇒ מטא‑דאטה בלבד). התשובה עצמה חסומה ב-`OUTPUT_BYTE_BUDGET`: קריאה מלאה גדולה ממנו — `answer_too_large` עם הפניה ל-`lines`/`outline`, ולקובץ שכלי התיעוד מגיש גם `read_with` ל-`codekeeper_docs_get_section` עם `whole_document=true` — הקובץ כולו שם, מדופדף; וטווח גדול ממנו נגמר מוקדם על גבול שורה (`range.truncation_reason: "byte_budget"`) |
| `codekeeper_search_repo` | חיפוש טקסט בריפו (snippet קצר, עם תקרות) |
| `codekeeper_list_repo_note_paths` | **מפת גילוי:** אילו קבצים בריפו נושאים פתקים, וכמה על כל אחד. בלעדיה `list_repo_notes` דורש לדעת את הנתיב מראש |
| `codekeeper_list_repo_notes` | הפתקים שעל קובץ בודד בריפו משוקף (`repo_name` + `repo_path`) — אותם פתקים שמוצגים בדפדפן הריפו בוובאפ. מחזיר `orphaned: true` כשהנתיב כבר אינו בעץ, והפתקים חוזרים בכל מקרה |
| `codekeeper_create_repo_note` | **כתיבה:** פתק חדש על קובץ בריפו משוקף. `mode` כמו בלוח; `title` אופציונלי וייחודי על אותו קובץ. עובר **שני** שערים ובסדר הזה — אדמין ואז כתיבה. דורש `write` |

- **מדיניות סודות (חובה):** נתיבים כמו `.env*`, `*.pem`, `id_rsa*` נחסמים/מושמטים בכל
  הכלים; הרחבה דרך `MCP_REPO_DENYLIST_EXTRA` (CSV globs).
- **sync רץ ברקע?** כלי שנכשל בזמן sync מחזיר `sync_in_progress` + `retry_after` —
  סימן לנסות שוב, לא להסיק שהקובץ לא קיים.

#### רענון אוטומטי (autosync) — בלי cron ובלי שירות נוסף

שירות ה‑MCP מריץ **thread רקע** (אותו דפוס כמו ה‑worker בוובאפ) שמחזיק את ה‑mirrors
המקומיים שלו טריים לבד:

```text
merge ל-main → GitHub webhook → הוובאפ מסנכרן את הדיסק שלו וכותב last_synced_sha ל-Mongo
            → ה-autosync ב-MCP מזהה שה-SHA המקומי שונה → git fetch לדיסק של ה-MCP
```

- ריפו שקיים ב‑`repo_metadata` אך חסר בדיסק המקומי — **משוכפל אוטומטית** מ‑`repo_url`
  (אין צורך ב‑`initial_import` ידני בצד ה‑MCP).
- מראה בדיסק המקומי שאין לה רשומה ב‑`repo_metadata` — **נמחקת** בסוף המעבר (`_prune_orphans` ב‑`repo_autosync.py`). כך ריפו שהוסר בוובאפ יוצא גם מהדיסק של ה‑MCP. לא נמחק כלום כשהשאילתה נכשלה, או כשאף שם ב‑`repo_metadata` אינו שם של מראה שבדיסק (כולל קריאה ריקה). כשיש בדיסק מראות שנחסכו כך, נרשמת אזהרה. לא נמחקים גם תיקייה שאינה מראה שהשירות יוצר (שם לא תקין, קישור סמלי) וריפו באמצע clone/fetch. מחיקה שנכשלה נספרת ב‑`errors`, והמראה נשארת עד המעבר הבא. הפירוט ב‑`docs/mcp-server.rst`, "רענון אוטומטי".
- שליטה: `MCP_REPO_AUTOSYNC` (ברירת מחדל פעיל; `0` מכבה), `MCP_REPO_AUTOSYNC_INTERVAL`
  (ברירת מחדל 300ש'). בזמן clone/fetch מקומי הכלים מחזירים `sync_in_progress`.
- **ENV נדרשים בשירות ה‑MCP:** `REPO_MIRROR_PATH` (+דיסק מצורף — ב‑Render דיסק הוא
  פר‑שירות; בלי דיסק זה עובד אבל משוכפל מחדש אחרי כל deploy), ו‑`GITHUB_TOKENS`/
  `GITHUB_TOKEN` לריפואים פרטיים. **אין צורך** ב‑`GITHUB_WEBHOOK_SECRET` כאן —
  ה‑webhook ממשיך להגיע לוובאפ בלבד.

---

## אימות — שני מסלולים (מאוחדים תחת `load_access_token`)

1. **OAuth 2.1** — עבור **Claude.ai** (Custom Connector). זרימה מלאה: DCR + PKCE +
   authorize + consent + token. הזהות נקבעת דרך **התחברות טלגרם בוובאפ**.
2. **Personal Access Token (PAT)** — עבור **Claude Code שלא מחובר עם החשבון ב‑claude.ai**, ועבור ההוק שטוען את הפריימר. `Authorization:
   Bearer ckmcp_…`, נשמר כ‑hash בקולקשן `mcp_tokens`, ניתן לביטול. (המחבר של מסלול 1 מגיע לבד גם ל‑Claude Desktop ול‑Claude Code שמחובר עם החשבון — ראו "חיבור מ‑Claude Desktop" למטה.)

ה‑`user_id` נגזר **תמיד** מהטוקן — לעולם לא מקלט הלקוח.

**הרשאות (scopes):** `read` (ברירת מחדל) ו‑`write`. כלי הכתיבה בודק `write` בזמן ריצה;
טוקן קריאה בלבד יקבל שגיאת `insufficient_scope` (ולא ייכתב דבר). איך משיגים כתיבה — ראו למטה.

> ⚠️ **ראוט שאינו `/mcp` אינו מוגן אוטומטית.** במצב OAuth ה‑`PATAuthMiddleware` לא
> מותקן כלל, וה‑SDK עוטף רק את ה‑mount של `/mcp` — ולכן ראוט שנרשם ידנית
> ל‑`app.router.routes` (כמו `/healthz`) מוגש **בלי אימות**. כל ראוט חדש שאסור שיהיה
> ציבורי חייב לקרוא ל‑`authenticate_bearer` בגוף שלו. ראו `auth.py` ו‑`primer.py`.

**ראוטים שמאמתים בעצמם, עם אותו מאמת של `/mcp`:**

- `GET /api/agent/primer` — טוקן תקין, בכל scope (במצב PAT המידלוור עונה לפניו).
- `PUT /api/agent/upload` — טוקן תקין, **ולא** `write`: הראוט רק מחזיק טקסט לעשר דקות, והכתיבה לקובץ נשארת קריאת כלי שדורשת `write`. במצב PAT הנתיב פטור מ‑`PATAuthMiddleware`, כדי שה‑401 יהיה של הראוט — עם `Connection: close` — בשני המצבים. ראו "העלאת תוכן" למטה.
- `GET /api/agent/download` — טוקן תקין, בכל scope: הורדה היא קריאה. במצב PAT הנתיב פטור מ‑`PATAuthMiddleware`, מאותה סיבה. ראו "הורדת קובץ" למטה.

`tests/test_mcp_uploads.py` מחזיק כל ראוט רשום ל‑401 בלי טוקן, חוץ מרשימה סגורה (`/healthz`, נקודות ה‑OAuth ועמוד ההסכמה).

---

## פריימר לסוכן — `GET /api/agent/primer`

אנדפוינט HTTP רגיל (לא כלי MCP) שמחזיר **טקסט חופשי** שהסוכן קורא בפתיחת סשן:

```bash
curl -sS -H "Authorization: Bearer $CODEKEEPER_PAT" \
  https://<MCP-HOST>/api/agent/primer
```

- **Content-Type:** `text/plain; charset=utf-8` — לא JSON. הגוף נקרא ע"י המודל כפי שהוא.
- **תוכן:** שדה "הוראות לסוכן" מעמוד ההגדרות בוובאפ, ואחריו שורת מצב קצרה עם שלושת
  הקבצים האחרונים שנשמרו ומתי.
- **`204`** כששדה ההוראות ריק (ולא `200` עם גוף ריק). **`401`** בלי טוקן תקין.
- **תקרת 24KB:** חריגה ⇒ חיתוך + שורה שמודיעה על כך. לעולם לא שגיאה.
- **Cache 60 שניות** לכל משתמש (`Cache-Control: private, max-age=60`).
- **סינון סודות** על כל הגוף לפני ההחזרה.

התקרה וה‑TTL קבועים בקוד ואינם משתני סביבה — ראו את ה‑docstring של `primer.py` להסבר.

> ⚠️ **ה‑URL הוא של ה‑MCP host, לא של הוובאפ.** הוובאפ יחזיר `404`. הוק שמושך את
> הפריימר בפתיחת סשן ושותק בכל כשל ייכשל לנצח בשקט — הבחינו בין `204` (אין פריימר,
> שתיקה נכונה) לבין `404`/`401` (תקלה).

### משיכה אוטומטית בפתיחת סשן

ההוק שמושך את הפריימר יושב בפלאגין `codekeeper-memory`, בריפו [`amirbiron/codekeeper-plugin`](https://github.com/amirbiron/codekeeper-plugin): הסקריפט `codekeeper-memory/hooks/session_start.sh`, ה‑`hooks.json` שמריץ אותו, הטסטים שלו וה‑CI. פלאגין שמופעל בחשבון ב‑claude.ai מגיע לכל סשן של Claude Code, גם בסשן שרץ בדפדפן, ולכן בריפו הזה אין עותק: עותק בריפו היה רץ לצד ההוק של הפלאגין, והפריימר היה נכנס להקשר פעמיים. ההסבר המלא — מה ההוק מדפיס, על מה הוא מנסה שוב, והחשבון מול ה‑`timeout` — ב‑README של הפלאגין. למה הוא עבר לשם: הסעיף "פריימר לסוכן" ב‑`docs/mcp-server.rst`.

> ⚠️ **גבול האבטחה.** הסקריפט רץ עם הסביבה של הסשן, כולל `CODEKEEPER_PAT`, ומי שמשנה אותו יכול להפנות את הטוקן ליעד אחר. להוק מסוג `http` הייתה הגנה ייעודית, `allowedHttpHookUrls` ב‑`~/.claude/settings.json` האישי; להוק מסוג `command` אין מקבילה. מאז שההוק עבר לפלאגין, הקוד הזה הוא הריפו `codekeeper-plugin`, ושם צריך לסקור כל שינוי באותה רמת קפדנות כמו קוד ייצור.

הכלל `Bash(curl:*)` אינו נדרש להוק ואינו מוגדר בכוונה: הוקים מורצים על ידי המעטפת ואינם עוברים דרך מנגנון ההרשאות של כלי ה‑Bash. הוספתו הייתה מרחיבה את מה שהמודל עצמו רשאי להריץ — עם `CODEKEEPER_PAT` בסביבה, זו דרך לשלוח את הטוקן ליעד שרירותי.

---

## העלאת תוכן בלי לעבור דרך המודל — `PUT /api/agent/upload`

תוכן שכבר קיים כקובץ בסביבת הסוכן (דוח, ניתוח, handoff) עולה בקריאת `curl` אחת, ו‑`codekeeper_save_file` / `codekeeper_append_file` מקבלים את `upload_id` במקום `code` / `content` — בלי לקרוא את הקובץ להקשר ולכתוב אותו שוב בקריאת הכלי:

```bash
curl -sS -T report.md -H "Authorization: Bearer $CODEKEEPER_PAT" \
  https://<MCP-HOST>/api/agent/upload
```

- **תשובה `201`:** `{"upload_id", "bytes", "chars", "content_sha256", "expires_in_seconds"}`. ה‑`content_sha256` הוא מה ש‑`file.content_sha256` יהיה אחרי `codekeeper_save_file`. אחרי `codekeeper_append_file`, ‏`file.content_sha256` הוא של הקובץ כולו, ומה שמראה שהטקסט נכנס בשלמותו הוא `content_changed: false`.
- **בדיקת שלמות עם השליפה:** ה‑hash של הטקסט שנשלף מושווה לזה שנשמר עם ההעלאה כשהגיעה (`_load_upload` ב‑`handlers.py`), לפני כל בדיקה אחרת של הכלי. לא תואם ← `upload_corrupted`: שום דבר לא נכתב, ההעלאה נמחקת (או פוקעת ב‑TTL, אם האחסון לא ענה למחיקה), ומעלים שוב.
- **חד‑פעמי, לעשר דקות** (`UPLOAD_TTL_SECONDS`), ועד `MAX_PENDING_UPLOADS` העלאות ממתינות למשתמש. **אינו מעלה את תקרת התוכן** — `max_code_size()` חל כמו על `code`.
- **אותה מכסת קצב של קריאות הכלים:** העלאה ושמירה הן שתי קריאות.
- **כל סירוב נושא `Connection: close`**, באוצר המילים של תשובות HTTP של השירות (`{"error": ...}` בלי `ok`).
- הפקודה רצה בכלי ה‑Bash של הסוכן, עם אישור הרשאה רגיל — `Bash(curl:*)` נשאר לא מוגדר, מאותה סיבה שלמעלה.
- בלי bash, בלי רשת או בלי `CODEKEEPER_PAT` (Claude.ai) — `code` כרגיל.

הקוד ב‑`uploads.py` (הראוט) וב‑`mcp_uploads.py` בשורש (האוסף, הקבועים והאינדקסים). הפירוט המלא — הסדר בראוט, "המחיקה היא השער", שער המוכנות על ה‑TTL ואוצר המילים — ב‑`docs/mcp-server.rst`, "העלאת תוכן בלי לעבור דרך המודל".

---

## הורדת קובץ לדיסק בלי לעבור דרך המודל — `GET /api/agent/download`

המראה של ההעלאה: קובץ שמור (סקריפט שהסוכן צריך להריץ, למשל) יורד בקריאת `curl` אחת ישר לקובץ בסביבת הסוכן, בלי לקרוא אותו להקשר ולהעתיק אותו לכלי הכתיבה:

```bash
curl -fsS -H "Authorization: Bearer $CODEKEEPER_PAT" -o script.py \
  'https://<MCP-HOST>/api/agent/download?file_id=<id>' && sha256sum script.py
```

- **`file_id`** — מזהה של גרסה: `file.id` מתשובה של `codekeeper_get_file`, או `id` מ‑`codekeeper_list_versions`. לפי שם (`file_name`, ו‑`version` אופציונלי) — רק מקודד, ב‑`-G --data-urlencode`.
- **הגוף הוא `code.encode("utf-8")` ותו לא**, ו‑`X-Content-SHA256` הוא `file.content_sha256` של אותה גרסה — ה‑hash ש‑`sha256sum` מדפיס. גם `X-File-Version`.
- **`-f` חובה:** בלעדיו גוף ה‑404 נכתב לקובץ היעד, curl יוצא ב‑0, ו‑`sha256sum` מחשב טביעת אצבע של הודעת השגיאה.
- **הכתובת מצוטטת ל‑shell** (`_shell_word` ב‑`server.py`, מעל `shlex.quote` — גם בפקודת ההעלאה): בתוך גרשיים כפולים `$(...)` ו‑backticks עדיין רצים, ו‑`"` בכתובת סוגר אותם.
- **אותה מכסת קצב של קריאות הכלים:** הורדה היא קריאה אחת. מזהה של אחר, מזהה שאינו קיים ומזהה פגום — `404` אחד. פרמטר לא מוכר, כפול או ריק, ו‑`version` לצד `file_id` — `400` עם קוד משלו.
- **כל סירוב של הראוט נושא `Connection: close`, וכל תשובה שהוא בונה — `Cache-Control: no-store`.**
- הפקודה רצה בכלי ה‑Bash של הסוכן, עם אישור הרשאה רגיל — `Bash(curl:*)` נשאר לא מוגדר, כמו בהעלאה.
- בלי bash, בלי רשת או בלי `CODEKEEPER_PAT` (Claude.ai) — `codekeeper_get_file` כרגיל.

הקוד ב‑`downloads.py`. הפקודה בתיאורי הכלים נבנית ב‑`server.py` (`_download_command`), וה‑host שלה מ‑`MCP_SERVER_URL` דרך `public_url.py` — אותה בדיקה של פקודת ההעלאה. הפירוט המלא — הסדר, הכותרות, טבלת התשובות ולמה לא קישור חתום — ב‑`docs/mcp-server.rst`, "הורדת קובץ לדיסק בלי לעבור דרך המודל".

---

## חיבור מ‑Claude.ai (OAuth)

ב‑Claude.ai → Settings → Connectors → **Add custom connector**: הזן **Name** ו‑
**Remote MCP server URL** = `https://<mcp-host>/mcp`. זהו — Claude יבצע DCR + OAuth
לבד, יפנה אותך להתחברות טלגרם ולמסך אישור, ויתחבר. (אין צורך למלא OAuth Client
ID/Secret.) דורש שמצב OAuth יהיה מוגדר בפריסה — ראו למטה.

## חיבור מ‑Claude Desktop
המחבר מהסעיף "חיבור מ‑Claude.ai" שייך לחשבון, ולכן הוא זמין לבד גם באפליקציית הדסקטופ, בלי JSON ובלי טוקן: בצ'אט, ובסשנים המקומיים וה‑SSH של טאב ה‑Code כשמחוברים בה עם חשבון Claude (לסשנים של WSL ב‑Windows המחברים עדיין בהטמעה). הקובץ `claude_desktop_config.json` מתועד לשרתים מקומיים, ולא נדרש כאן. מי שמעדיף רשומה ידנית: טאב ה‑Code קורא גם את `~/.claude.json`, והרשומה היא זו שבסעיף "חיבור מ‑Claude Code". (code.claude.com/docs/en/mcp, הסעיף How connectors reach Claude Code; code.claude.com/docs/en/desktop, הסעיף MCP servers from the Claude Desktop chat app; support.claude.com, Get started with custom connectors using remote MCP — נקראו ב‑2026-10-29.)

## חיבור מ‑Claude Code (PAT)
**קודם — ייתכן שלא צריך טוקן.** כש‑Claude Code מחובר עם חשבון claude.ai, המחבר מהסעיף "חיבור מ‑Claude.ai" נטען בו לבד, ו‑`/mcp` מסמן אותו כמחבר מ‑claude.ai. טוקן צריך כשהאימות הפעיל הוא אחר (למשל מפתח API, ספק ענן כמו Amazon Bedrock, או `CLAUDE_CODE_OAUTH_TOKEN` של `claude setup-token`), כשהמחברים כובו, או בתוכנית Team/Enterprise שבה האדמין לא הוסיף את המחבר. הרשימה המלאה, עם המקור, ב‑`docs/mcp-server.rst`, הסעיף "Claude Code (טוקן)".
```bash
claude mcp add --transport http codekeeper --scope user https://<mcp-host>/mcp \
  --header "Authorization: Bearer <token>"
```

**איפה הפקודה שומרת, והמקבילה הידנית.** זו הפקודה שהבוט מחזיר (`connect_claude_command` ב‑`main.py`; הטסט: `tests/test_connect_claude_command.py`). `--scope user` כותב את הרשומה ל‑`mcpServers` שבראש `~/.claude.json`, ולכן CodeKeeper זמין בכל הפרויקטים. בלי הדגל, `claude mcp add` שומר ב‑`local`, תחת הפרויקט שממנו הורצה הפקודה בלבד (code.claude.com/docs/en/mcp, ה‑Tips של `--scope`; נקרא ונמדד ב‑2026-10-29 ב‑Claude Code 2.1.312). מי שמעדיף לערוך את הקובץ ביד מוסיף את הרשומה הזו ל‑`mcpServers` הקיים, ולא מחליף את הקובץ, שיש בו עוד הגדרות רבות של Claude Code:
```json
{
  "mcpServers": {
    "codekeeper": {
      "type": "http",
      "url": "https://<mcp-host>/mcp",
      "headers": { "Authorization": "Bearer <token>" }
    }
  }
}
```

### הנפקת PAT
**מתוך הבוט:** `/connect_claude` בצ'אט פרטי → טוקן קריאה + פקודת חיבור מוכנה.
`/connect_claude write` → טוקן עם הרשאת **כתיבה** (יצירה/עדכון).
**CLI (אופס):** `MONGODB_URL="..." python scripts/mcp_issue_token.py --user-id <TELEGRAM_ID>`
(הוסיפו `--write` לטוקן כתיבה). הטוקן מוצג **פעם אחת בלבד**.

### הרשאת כתיבה ל‑Claude.ai
כדי ש‑Claude.ai יבקש `write`, ה‑connector צריך להירשם מחדש (DCR) עם ההרשאה — לא ניתן
לכפות זאת מצד השרת. אם כבר חיברת connector לקריאה, **הסר והוסף אותו מחדש** ואשר את מסך
ההרשאה (קריאה **וכתיבה**). מסלול ה‑PAT (`/connect_claude write`) מבטיח כתיבה ל‑Claude Code
ללא תלות בהתנהגות הלקוח.

---

## הרצה מקומית
```bash
pip install -r requirements/development.txt
MONGODB_URL="..." uvicorn mcp_server.app:app --host 0.0.0.0 --port 8000
```
- נקודת הקצה של MCP: `POST/GET /mcp` (Streamable HTTP).
- בריאות (ללא אימות): `GET /healthz`.

---

## פריסה (Render)

שירות web נפרד (ASGI). **חייב להתחבר לאותו MongoDB כמו הבוט/הוובאפ** — אחרת טוקנים
לא יימצאו.
```text
Start command:  uvicorn mcp_server.app:app --host 0.0.0.0 --port $PORT
Health check:   /healthz
```

**מצב PAT‑only (Claude Code דרך טוקן, והפריימר; מחבר ב‑Claude.ai, ואיתו Claude Desktop, דורש את מצב OAuth) — מינימלי:**
- `MONGODB_URL` + `DATABASE_NAME` — זהים לבוט/וובאפ (ברירת מחדל `code_keeper_bot`).
- `BOT_TOKEN` — נדרש רק כדי שמודול ה‑`config` המשותף ייטען.
- `MCP_SERVER_NAME` — אופציונלי.

**מצב OAuth (מוסיף תמיכה ב‑Claude.ai)** — נדלק אוטומטית כשמוגדרים גם:
- `MCP_SERVER_URL` = ה‑URL הציבורי (**https**) של שירות ה‑MCP (למשל `https://codekeepermcp.onrender.com`).
- `WEBAPP_URL` = ה‑URL הציבורי של הוובאפ (למסך התחברות הטלגרם).
- `SECRET_KEY` = **אותו ערך כמו הוובאפ** (חותם/מאמת את זהות המשתמש בין השירותים).

**בנוסף, על שירות הוובאפ** יש להגדיר `MCP_SERVER_URL` (לשער open‑redirect ב‑`/oauth/identify`),
ועל **שירות הבוט** `MCP_SERVER_URL` (עבור `/connect_claude`).

> `MCP_ALLOWED_HOSTS` (CSV, wildcard) אופציונלי לנעילת בדיקת ה‑Host; ריק = כבוי (מתאים לשרת ציבורי מוגן‑טוקן).

**מדידת שימוש (PostHog) — אופציונלי:**
- `POSTHOG_PROJECT_TOKEN` (`phc_...`) + `POSTHOG_HOST` (`https://us.i.posthog.com` / `https://eu.i.posthog.com`).
- חסר אחד מהם: בפרודקשן המדידה כבויה והשרת עולה רגיל; בפיתוח העלייה נכשלת ברעש. פרודקשן = `ENVIRONMENT`/`ENV` ששווה `production` או `prod`, או ששניהם לא מוגדרים.
- `report_missing` דלוק: כלי וירטואלי `get_more_tools` שהסוכן קורא לו כדי לדווח על יכולת חסרה. תוספת לרשימת הכלים בלבד; הכלים הקיימים לא נגעו.
- `context` דלוק: **מוסיף פרמטר `context` לסכימה המוצהרת של כל כלי**, כולל לרשימת ה-`required`. נמדד: קריאה בלי הפרמטר **אינה נדחית** והכלי רץ כרגיל. בלעדיו `$mcp_intent` אינו נוצר על קריאת כלי, וטור הכוונה ב-`/admin/mcp` נשאר ריק.
- הארגומנטים והתוצאות של הכלים (`$mcp_parameters`, `$mcp_response`) **אינם** נשלחים בשום מסלול — `analytics.py` מחזיק רשימת היתר של מאפייני `$mcp_*`, ומחליף כל `$exception_list[*].value` בכל אירוע (כולל חריגות שנתפסות ב-`threading.excepthook`).
- **כן** נשלחים שני שדות של טקסט חופשי, ורק כשהערך מחרוזת **ואחרי סינון סודות**: `$mcp_intent` (המשפט של הסוכן) ו-`$mcp_error_message` (הודעת החריגה, על כל סוג שגיאה). הסינון הוא `mcp_server/redaction.py` — אותה רשימת דפוסים שמסננת את הפריימר, במודול אחד ששניהם מייבאים. הוא תופס כל צורת סוד מוכרת בכל מקום במחרוזת, אבל הכלל לפי *שם* (`API_KEY=…`) מעוגן לתחילת שורה ולכן אינו יורה על הודעה חד-שורתית. הוא מצמצם חשיפה ואינו הופך את השדות לבטוחים — האזהרה המלאה והמדידה שמאחוריה: `docs/mcp-server.rst`.
- `$mcp_intent_source` נאכף כתווית סגורה: `context_parameter` או `inferred`, ותו לא.
- `ck_read_mode` הוא מאפיין משלנו: `outline` / `section` / `query` / `range` / `full`, נגזר מ**נוכחות** הפרמטרים ולא מערכיהם, ונאכף בשער מול קבוצה סגורה. `toc=true` של `codekeeper_get_file` מתויג `outline`. הדשבורד (`ck_mcp_navigation_cost_v2`) סופר את עמודות האאוטליין וקריאת התוכן רק ל-`codekeeper_get_repo_file`.

---

## זרימת ה‑OAuth (בקצרה)
```text
Claude.ai → /authorize → provider יוצר txn → הפניה ל-webapp /oauth/identify
   → התחברות טלגרם → חתימת HMAC של user_id → MCP /oauth/consent (מסך אישור)
   → מנפיק code → /token (SDK מאמת PKCE) → access+refresh tokens
   → קריאות tools עם ה-access token (subject = user_id)
```

---

## מבנה הקוד

| קובץ | תפקיד |
|------|-------|
| `token_store.py` | ניהול PAT מעל `mcp_tokens` |
| `backend.py` | גישה לנתונים + סריאליזציה (Smart Projection, בדיקת בעלות) |
| `handlers.py` | לוגיקת הכלים הטהורה — יעד הטסטים |
| `answer_size.py` | תקציב התשובה (`OUTPUT_BYTE_BUDGET`), המדידה שלה כפי שהיא נשלחת (`wire_json`), וההצהרה ללקוח (`declared_size_meta`). בלי תלויות פנימיות — ראו "תקרת התשובה" ב-`docs/mcp-server.rst` |
| `answer_fit.py` | מה עושים כשתשובה אינה נכנסת: ליבת הסירוב `answer_too_large` (`too_large`), השגרה האחת של קריאת קובץ (`fit_read`), טווח שורות (`fit_line_range`), חיתוך רשימות ומחרוזות בהקשר (`fit_lists`, `fit_refusal`), והרישום לשורת `answer_size_fit` בלוג. תלוי רק ב-`answer_size` |
| `auth.py` | `current_user_id` (OAuth/PAT) + PAT middleware (fallback) + `authenticate_bearer` לראוטים שאינם `/mcp` |
| `oauth_store.py` | אחסון clients/codes/tokens/txns (hash) |
| `oauth_provider.py` | מימוש חוזה ה‑OAuth של ה‑SDK (כולל PAT מאוחד) |
| `oauth_identity.py` | חתימת/אימות זהות HMAC (משותף עם הוובאפ) |
| `oauth_routes.py` | מסך ה‑consent + הנפקת code |
| `primer.py` | `GET /api/agent/primer` — פריימר טקסט לסוכן (24KB, cache 60ש׳, סינון סודות) |
| `uploads.py` | `PUT /api/agent/upload` — העלאת תוכן שנשמר אחר כך לפי `upload_id`. המפרט של האוסף ב‑`mcp_uploads.py` בשורש |
| `downloads.py` | `GET /api/agent/download` — הבתים של קובץ שמור, ישר לדיסק של הסוכן |
| `public_url.py` | הבסיס (מ‑`MCP_SERVER_URL`) של פקודות ההעלאה וההורדה בתיאורי הכלים — בדיקה אחת לשתיהן |
| `server.py` | חיווט FastMCP: כלים + OAuth + ASGI |
| `analytics.py` | PostHog MCP analytics + שער הפרטיות (`before_send` עם רשימת היתר) |
| `app.py` | נקודת כניסה: בוחר PAT/OAuth לפי ENV |

צד הוובאפ: `webapp/routes/auth_routes.py` → `/oauth/identify` (גשר הזהות).
טסטים: `tests/test_mcp_*.py` + `tests/test_webapp_oauth_identify.py` (fakes ידניים).
