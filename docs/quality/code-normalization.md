---
summary: למה השמירה שומרת בדיוק את מה שנשלח, איפה בכל זאת יש ניקוי (קוד שמודבק בבוט), איפה מוצגת אזהרה על תווים שמשנים את סדר התצוגה ואיפה עוד לא, הפענוח של שליחת טופס בוובאפ, ומה עושים כשמוסיפים כניסה חדשה.
---

# ניקוי קוד מודבק (Pasted-code cleanup)

## הכלל: שמירה שומרת בדיוק את מה שנשלח

שכבת השמירה (`database/repository.py`), הוובאפ וה-MCP לא משנים את התוכן שנשמר. מה שנשלח הוא מה שנשמר, תו בתו: סימני כיווניות כמו LRM ו-RLM, רצפי escape שכתובים בתוך קוד (`"\u200f"` כטקסט), רווחים בסוף שורה, אמוג'י שמחוברים ב-ZWJ, וה-newline שבסוף הקובץ.

**למה זה כלל ולא ברירת מחדל.** עד ספטמבר 2026 ישב נרמול בשכבת השמירה עצמה (`Repository.save_code_snippet`, `save_file` ו-`save_large_file`), ולכן שכתב בשקט כל קובץ מכל כניסה: הוא מחק LRM ו-RLM ממסמכים בעברית, מחק רצפי escape טקסטואליים מקוד מקור כך שקבוע קיבל ערך אחר ורגקס נשבר, מחק את כל ה-newlines בסוף הקובץ ורווחים בסוף כל שורה, ופירק אמוג'י. עריכה של מילה אחת ב-`edit_file` של ה-MCP נרמלה את כל הקובץ, ו-`old_string` שהכיל RLM הפסיק למצוא התאמה. הנרמול נבנה בשביל קוד שמודבק בטלגרם, אבל ישב בשכבה שכל המוצר עובר בה.

השומר המבני, `tests/test_content_cleaning_stays_in_the_bot.py`, נופל אם קוד בשכבת השמירה, בוובאפ או ב-MCP (התיקיות שב-`GUARDED_DIRS`) משתמש בשם של פונקציית ניקוי: `clean_pasted_code`, או שם שנמחק (`FORBIDDEN`).

## החריג: קוד שמודבק בבוט

קוד שמודבק בטלגרם מגיע עם שאריות של הדרך: סופי שורה של Windows, ‏BOM, ורווחים מיוחדים שהעתקה מדפדפן או ממעבד תמלילים משאירה. חלק מהם שוברים קוד — נמדד על Python 3.11 ש-NBSP, ‏NNBSP, ‏THIN SPACE, ‏IDEOGRAPHIC SPACE ו-ZWSP בתוך קוד מרימים `SyntaxError`. לכן בבוט, ורק שם, רץ ניקוי מינימלי.

**המימוש האחד:** `clean_pasted_code` ב-`src/domain/services/code_normalizer.py`. ה-docstring שלה הוא המקום היחיד שבו כתוב מה מנוקה ומה לעולם לא, ולכן הרשימה לא מועתקת לכאן. בקבצי Markdown הניקוי מצומצם יותר, כי שם יש משמעות לדברים שבקוד הם רק שאריות: למשל, שני רווחים בסוף שורה הם Hard break. Markdown נקבע לפי סיומת השם, ב-`is_markdown_filename`, מול אותה רשימת סיומות שזיהוי השפה משתמש בה (`MARKDOWN_SUFFIXES` ב-`language_detector.py`).

**נקודה אחת לכל זרימה, ממש לפני השמירה.** בבוט אין שלב שבו הקוד מוצג לאישור, ושם הקובץ מגיע רק אחרי הקוד — ובלי השם אי אפשר לדעת אם זה Markdown. לכן כל זרימה קוראת ל-`code_service.clean_pasted_code` פעם אחת, כשגם הקוד וגם השם ידועים:

- שמירה רגילה ואיסוף ארוך — `handlers/save_flow.save_file_final`. היא מכסה גם את "החלף קובץ קיים".
- הפקודה `/save` — `_save_code_snippet` ב-`main.py`.
- עריכת קובץ ועריכת קובץ גדול — `conversation_handlers.receive_new_code`. המאמת (`code_processor.validate_code_input`) אינו מנקה תווים, והניקוי רץ לפניו. הוא רק מסיר גדרות ``` מקוד שאינו Markdown, כמו קודם.

ה-handlers עוברים דרך `services/code_service.py` ולא מייבאים את שכבת הדומיין, לפי [כללי השכבות](../ARCHITECTURE_LAYER_RULES.md).

**מה שנוקה נאמר למשתמש.** `code_service.format_cleanup_notice` בונה שורה להודעת ההצלחה, למשל "🧹 ניקיתי מהקוד: 3 סופי שורה של Windows ו-ZWSP אחד". ניקוי שאיש לא מספר עליו הוא בדיוק השכתוב השקט שהוחלף כאן.

## תווים שמשנים את סדר התצוגה

תווי ה-embedding, ה-override וה-isolate (תשעת התווים של Trojan Source, CVE-2021-42574) יכולים לגרום לקוד להיראות אחרת ממה שהוא עושה, אבל הם גם יכולים להיות שם בכוונה — למשל FSI ו-PDI סביב שם משתמש במחרוזת UI בעברית. לכן שום כניסה לא מוחקת אותם, גם לא הניקוי בבוט: מחיקה הייתה משנה את התוכן בשקט, ולא הייתה מגינה על כלום, כי אותו קובץ שמגיע מה-MCP או מהוובאפ נשמר איתם. במקום זה, מי שקורא את הקוד מקבל אזהרה עם מספרי השורות.

הזיהוי אחד, `explicit_bidi_control_lines`, והמשפט אחד, `format_bidi_warning`. התווים מזוהים לפי מחלקת הכיווניות שלהם בתקן (`unicodedata.bidirectional`) ולא לפי רשימת תווים.

### איפה מוצגת אזהרה

- **בבוט** — בהודעת ההצלחה אחרי שמירה או עריכה של קוד מודבק (`format_cleanup_notice`).
- **בוובאפ** — מעל הקוד בעמוד `view_file.html`, בראוטים שקוראים ל-`_bidi_warning_for_highlighted_code`:
  - `view_file` (`/file/<file_id>`) — תצוגת הבעלים.
  - `public_share` (`/share/<share_id>`) — שיתוף ציבורי, בתצוגת הקוד.

מספרי השורות בוובאפ הם אלה שהעמוד מציג: Pygments חותך שורות ריקות מתחילת הקוד והופך CR בודד לירידת שורה, ולכן המספרים נגזרים מהטקסט שהוא ממספר ולא מהקוד הגולמי.

### איפה עדיין אין אזהרה

הרשימה נכונה ל-27 בספטמבר 2026. היא נאספה מקריאה של הקוד: כל פונקציה ב-`webapp/` ובבוט שקוראת את הקוד של קובץ שמור ומציגה אותו. עמוד חדש שמציג קוד שמור לא ייכנס לכאן מעצמו — מי שמוסיף עמוד כזה מוסיף אותו לרשימה, או מוסיף לו אזהרה.

נדחו במכוון ב-PR #3469:

- **תצוגות Markdown, כולל HTML מעוצב.** `md_preview` (`/md/<file_id>`); תצוגת ה-Markdown של השיתוף הציבורי, `public_share` עם `?view=md`; מצב קריאה, `reader_mode` (`/read/<path:filename>`) ו-`public_reader_mode` (`/read/share/<share_id>`); ו-HTML מעוצב, `export_styled_html` (`/export/styled/<file_id>`) והשיתוף שלו, `public_shared_styled` (`/shared/styled/<token>`). בתצוגת ה-Markdown של שיתוף ציבורי יש גם כפתור ששומר עותק לחשבון, `api_save_shared_file` (`/api/shared/save`): הוא מעתיק את כל הקובץ בלי אזהרה, והעותק מקבל אזהרה כשפותחים אותו ב-`/file/<file_id>`.
- **תצוגות של קובץ שמור בבוט**, למשל `handlers/file_view.py` והפקודה `/show`.

עוד לא הוחלט:

- **העורך**, `edit_file_page` (`/edit/<file_id>`), והתצוגה החיה שלו, `api_live_preview` (`/api/preview/live`).
- **ההשוואות**, `compare_versions_page` (`/compare/<file_id>`) ו-`compare_files_page` (`/compare`). את ההבדלים הן מקבלות מ-`compare_versions` ומ-`compare_files` ב-`compare_bp`.
- **התצוגה המקדימה בכרטיס של קובץ**, `file_preview` (`/api/file/<file_id>/preview`).
- **הדף הציבורי של אוסף משותף**, `shared_collection_page` ב-`webapp/collections_ui.py`, שמציג קבצים מ-`get_shared_file` ב-`webapp/collections_api.py`.
- **קטעים קצרים מתוך קוד**: תוצאות החיפוש הגלובלי, `api_search_global` (`/api/search/global`), והשורה שנשמרת עם סימנייה (`line_text_preview`).

לא ברשימה, כי הם לא מציגים את הקובץ כקוד: הורדות, ייצוא ל-ZIP, ההעתקה ללוח מהתצוגה המקדימה בכרטיס, `api_file_content` (`/api/file/<file_id>/content`), ו-`raw_html`, `svg_preview` ו-`raw_svg`, שמרנדרים את הקובץ עצמו.

`tests/test_bidi_warning_pages_match_the_doc.py` משווה את שתי הרשימות לקוד: הראוטים ב"איפה מוצגת אזהרה" הם בדיוק אלה שקוראים ל-`_bidi_warning_for_highlighted_code`, אף ראוט ב"איפה עדיין אין אזהרה" לא קורא לה, והכתובות הן אלה שב-`@app.route` של כל ראוט. עמוד שלא מופיע באף רשימה — הטסט לא יודע עליו.

## הוובאפ: פענוח של השליחה, לא ניקוי

דפדפן ששולח טופס HTML הופך כל ירידת שורה בערך של textarea ל-CRLF — כך מגדיר HTML Living Standard, בסעיפים 4.10.22.6 ו-4.10.22.8, ונמדד ב-Chromium. בלי פענוח, כל קובץ שנשמר מהוובאפ היה נשמר עם CRLF, ו-`old_string` של סוכן עם `\n` לא היה מתאים לו. `decode_form_newlines` ב-`services/line_endings.py` מחזירה את ה-CRLF ל-LF, רק בשדה `code`, ורק ב-`/upload` וב-`/edit/<id>`. קובץ שמעלים (`code_file`) לא עובר את הקידוד הזה בדפדפן, ולכן גם לא את הפענוח. את הבתים שלו `upload_file_web` מפענח לטקסט: UTF-8, ואם הם אינם UTF-8 תקין — latin-1. מעבר לזה הוא נשמר כמו שהוא, כולל BOM ו-CRLF שהיו בו. קובץ בקידוד אחר, למשל עברית ב-Windows-1255, נשמר לכן כג'יבריש.

**מגבלה של HTML, לא משהו שאנחנו מנרמלים:** הערך של textarea אינו יכול להחזיק CR (נמדד). לכן קובץ שנשמר עם CRLF — למשל מסמך Windows שהועלה לבוט — ייצא עם LF אחרי שעורכים אותו בוובאפ.

## ה-MCP

כלי הכתיבה (`save_file`, `edit_file`, `append_file`) שומרים בדיוק את מה שנשלח. עריכה ב-`edit_file` משנה רק את הטקסט שהוחלף, ושאר הקובץ נשאר תו בתו.

ואם שכבה כלשהי תחזור לשנות תוכן בשקט, זה ייראה מיד: תשובת הכתיבה נושאת `content_sha256` של מה שנקרא חזרה מהאחסון, ו-`content_changed` שנדלק כשמה שנשמר שונה ממה שהכלי התכוון לשמור, עם סיכום של ההבדל. כשהקריאה החוזרת נכשלת אין בתשובה hash, ו-`content_changed` הוא `null`. `codekeeper_get_file` נושא את אותו `content_sha256`, כך שסוכן יכול להשוות אותו ל-hash שחישב בעצמו. ההמרה של CRLF ל-LF בעורך של הוובאפ (למטה) משנה את ה-hash באופן לגיטימי. הפירוט ב-[שרת ה-MCP](../mcp-server.rst), בסעיף "טביעת אצבע לתוכן".

## כשמוסיפים כניסה חדשה

1. אם הכניסה אינה קוד שמודבק בבוט — לא מנקים. זה נכון גם לייבוא, לשחזור ולכל API.
2. אם היא כן — קוראים ל-`code_service.clean_pasted_code` פעם אחת, ממש לפני השמירה, ומוסיפים את `code_service.format_cleanup_notice` להודעת ההצלחה.
3. טופס HTML בוובאפ — `decode_form_newlines` על ערך ה-textarea, ולא על קובץ שהועלה.

## טסטים

- `tests/unit/domain/services/test_code_normalizer.py` — מה `clean_pasted_code` מנקה ומה היא משאירה, והשוואה של מחלקות הכיווניות לתשעת התווים.
- `tests/test_code_service_cleanup_notice.py` — הודעת השקיפות והאזהרה.
- `tests/test_view_bidi_warning.py` — האזהרה בעמוד הקוד בוובאפ, בשיתוף הציבורי ובתצוגת הבעלים, ומספרי השורות לפי מה שהעמוד מציג.
- `tests/test_bidi_warning_pages_match_the_doc.py` — שתי הרשימות בסעיף על תווים שמשנים את סדר התצוגה, מול הקוד.
- `tests/test_content_cleaning_stays_in_the_bot.py` — השומר המבני.
- `tests/test_save_preserves_content_mcp.py`, ‏`tests/test_save_preserves_content_webapp.py` ו-`tests/test_bot_paste_cleanup_flows.py` — הכניסות עצמן, דרך הממשק של הצרכן. הטסטים של ה-MCP ושל הבוט שומרים דרך ה-`Repository`, ולכן טוענים את `config.py` האמיתי ולא את `tests/config.py` (`load_production_config` ב-`tests/_save_layer_harness.py`). הטסט של הוובאפ לא צריך את זה: `upload_file_web` ו-`edit_file_page` כותבים למסד ישירות, בלי ה-`Repository`.

## קישורים

- [זרימת שמירת קוד](../workflows/save-flow.rst)
- [What's New](../whats-new.rst)
