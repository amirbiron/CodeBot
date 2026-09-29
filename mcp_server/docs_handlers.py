"""Section answering for documents — the public docs tool and the two tools that reuse it.

**Three tools answer through this module**, and a change here reaches all of them:

* ``codekeeper_docs_get_section`` (:func:`docs_get_section`) — the public docs tool,
  reading RST or Markdown from the git mirrors.
* ``codekeeper_read_batch`` (``mcp_server/read_batch.py``) — admin; its section items
  go through :func:`resolve_docs_target`, :func:`load_document` and
  :func:`answer_section`, one read and one parse per file.
* ``codekeeper_get_file`` with ``toc`` or ``section`` (``mcp_server/backend.py``) — a
  **saved** Markdown file, which has nothing to do with the mirrors: it goes through
  :func:`parse_with_refusals` and :func:`answer_section` with a ``{"file": ...}``
  context instead of ``repo``/``path``/``ref``.

Same contract as ``repo_handlers.py``: plain functions, no MCP/Starlette imports,
clamped inputs, ``{"ok": False, "error": "..."}`` rejections. **Not** admin-gated —
the docs tool is public; its body deliberately omits ``require_admin``.

The docs tool reuses ``RepoBackend.get_file`` to read the raw text from the mirror (that
already handles ref-default, secrets policy, and the ``sync_in_progress`` retry contract),
then the parser that matches the file's suffix — ``services.rst_parser`` for ``.rst``,
``services.md_parser`` for ``.md``. **שני הפארסרים ממלאים את אותו מודל**
(``services.doc_sections``), ולכן מעבר לבחירת המודול אין כאן מסלול קוד שני: כל
פונקציות העץ נקראות מ-``doc_sections`` ישירות. Guiding rule: never return only
"not found" — no section ⇒ TOC; missing ⇒ TOC + suggestions; duplicate ⇒
candidates with breadcrumb.
"""

from __future__ import annotations

import logging
import os
import posixpath
from dataclasses import dataclass
from types import MappingProxyType, ModuleType
from typing import Any, Callable, Mapping, NamedTuple

from services import doc_sections, md_parser, rst_parser
from .handlers import _clamp
from .answer_size import BYTE_BUDGET_REASON, OUTPUT_BYTE_BUDGET, wire_json
from .answer_fit import Cut, cut, fit_lists, fit_refusal, too_large

logger = logging.getLogger(__name__)

#: שם הכלי שהמודול הזה משרת. מקום אחד לשלושה שמשתמשים בו: הרישום של הכלי
#: ב-``server.py``, ``read_with`` של ``item_too_large`` ב-``read_batch.py``,
#: וההפניה מ-``outline`` ב-``RepoBackend.get_file`` (:func:`section_read_arguments`).
#: הפניה עם שם שאינו רשום שולחת את הסוכן לכלי שאינו קיים.
SECTION_TOOL_NAME = "codekeeper_docs_get_section"

MAX_CHARS_DEFAULT = 12_000
MAX_CHARS_MAX = 100_000
MAX_CHARS_MIN = 500

#: תקרת אורך ל-``path``, **הקלט החיצוני היחיד כאן שלא הייתה עליו תקרה**.
#: ``max_chars`` ו-``offset`` עוברים ``_clamp``; המחרוזת לא עברה כלום,
#: ולכן העבודה שנעשית עליה במורד הזרם גדלה עם מה שהקורא שולח.
#:
#: **מה נמדד.** ``repo_policy.is_denied`` — ההוראה הראשונה ב-
#: ``RepoBackend.get_file`` — סורקת כל רכיב בנתיב מול כל תבנית, ולכן
#: נתיב של 400KB עלה 608ms לעומת 2.4ms לפני שסריקת הרכיבים נוספה. הכלי
#: הזה ציבורי (אין ``require_admin``), ולשרת אין תקרת גוף בקשה ואין
#: הגבלת קצב — אישו #3430.
#:
#: **והמספר נגזר ממדידה ולא נבחר.** הנתיב הארוך ביותר בשלוש המראות
#: שהמדיניות חלה עליהן: ``amir-bug-patterns`` 53 תווים, CodeBot 97,
#: ו-Han 117. התקרה כאן היא פי 35 מהארוך שבהם, והיא גם ``PATH_MAX``
#: של לינוקס — כלומר גבול שכלי גיט וקבצים ממילא חיים בתוכו. אפס קבצים
#: אמיתיים נחסמים.
#:
#: זו הקטנת משטח ולא תחליף להגבלת קצב: היא חוסמת את ההגברה לכל בקשה,
#: ולא את מספר הבקשות.
MAX_PATH_CHARS = 4096

#: תקרת אורך ל-``section``, בתווים (``len`` של פייתון — נקודות קוד), כמו
#: :data:`MAX_PATH_CHARS`. ארוך ממנה נדחה ב-``section_too_long`` עם
#: ``max_chars`` ו-``actual_chars`` — אותם שמות שדות כמו ``path_too_long``.
#:
#: **מה נמדד (2026-09-28, על ``docs/mcp-server.rst``, 61 סעיפים):** ההתאמה של
#: שאילתה שאינה נמצאת — השוואה מלאה, ואז ההצעות של ``difflib`` מול כל כותרת —
#: גדלה עם אורך השאילתה, והשאילתה חוזרת במלואה ב-``requested``. ‏90 תווים:
#: 1.7ms ותשובה של 21,048 בתים. ‏4,096: 2.8ms ו-25,054. ‏170,000 תווים עבריים:
#: 82.8ms ו-360,958 בתים. ‏1,000,000 תווים: 321ms ו-1,020,958 בתים. גוף בקשה
#: יכול לשאת את זה (``DEFAULT_MAX_REQUEST_BYTES`` הוא 1MiB), ושני דברים נשברים
#: בלי התקרה: תשובת ``section_not_found`` עוברת את ``OUTPUT_BYTE_BUDGET``
#: (256,000) — ואותה אי אפשר לקצר כמו עמוד של סעיף (:func:`_fit_page`), כי
#: מה שמנפח אותה הוא ההד של השאילתה; והטענה ש-``DEFAULT_RATE_LIMIT_PER_MINUTE``
#: שומר עליה — שקריאה אחת אינה עולה יותר מ-``WORST_CASE_CPU_SECONDS`` — מפסיקה
#: להחזיק, כי ההתאמה מתווספת על הפרסור.
#:
#: **והמספר נגזר ממדידה ולא נבחר.** הכותרת הארוכה ביותר: 71 תווים בעמודי ה-RST
#: של ``docs/``, ‏87 בקובצי ה-Markdown של הריפו הזה (623 ב-README מסופק תחת
#: ``node_modules/`` — כותרת שנושאת קישור HTML), ו-90 ב-``amir-bug-patterns``.
#: בקבצים השמורים (``code_snippets``, 1,082 מסמכי Markdown כולל סל המיחזור,
#: קריאה בלבד) — כותרת ATX של עד 292 תווים, וחסם עליון שמרני של 1,219: הוא סופר
#: גם רצף שורות לפני קו setext כאילו היה כותרת אחת, והרצפים המובילים שם הם בלוקי
#: YAML ו-front matter ולא כותרות. 4,096 הוא פי 3.36 מהחסם השמרני — אפס כותרות
#: אמיתיות נחסמות — ובו ההתאמה עולה 2.8ms והתשובה 25KB.
#:
#: **הבדיקה בפונקציה שבונה את התשובה** (:func:`_answer_from_document`), כדי ש-
#: ``codekeeper_docs_get_section``, ``codekeeper_read_batch`` ו-
#: ``codekeeper_get_file`` יקבלו אותה ממקום אחד. היא רצה אחרי הקריאה והפרסור:
#: שניהם חסומים בתקרות משלהם ומתומחרים בחשבון של מגבלת הקצב, ומה שהתקרה הזו
#: מונעת הוא העבודה שמתווספת **עליהם**. ו-``section`` ריק או רווחים בלבד אינו
#: חריג: המבחן הוא האורך, לא התוכן.
#:
#: זו הקטנת משטח ולא תחליף להגבלת קצב: היא חוסמת את ההגברה לכל בקשה, ולא את
#: מספר הבקשות.
MAX_SECTION_CHARS = 4_096

DEFAULT_DOCS_REPO = "CodeBot"
_TOC_MAX = 400  # תקרת פריטי TOC בתשובה (הגנת גודל)

#: תקרת המועמדים בתשובת ``ambiguous_section``. **אותו מספר כמו
#: ``doc_sections.MAX_IDENTIFIER_SUGGESTIONS``, ומאותה סיבה:** רשימת המועמדים
#: היא מלאי בסדר הופעה ולא דירוג, ולכן חיתוך שלה מסתיר פריטים בלי קריטריון —
#: והתקרה גבוהה מספיק כדי שכל עמוד אמיתי ייענה במלואו (כותרת כפולה בקורפוס
#: חוזרת פעמיים או שלוש). מה שהיא עוצרת נמדד בסקירת #3425: עמוד סינתטי של
#: 512KB עם 13,030 כותרות שנפתחות ב-``K11.`` החזיר 13,030 מועמדים — 1,393,787
#: בתים ושיא הקצאה של 12.6MB — על שאילתה בת שלושה תווים, וזה היה השדה היחיד
#: בתשובה בלי גבול (``toc`` ב-``_TOC_MAX``, ‏``suggestions``
#: ב-``MAX_IDENTIFIER_SUGGESTIONS``). הענף נדלק רק מכותרות שנושאות מזהה, ומאז
#: #3428 הקורפוס שנושא מזהים (``amir-bug-patterns``) מוגש. אותו מספר ממש —
#: מיובא ולא מוקלד שוב (הכיוון ``services`` ← ``mcp_server`` מותר; ההפוך לא),
#: והטסט שומר שלא יוקלד מחדש. אישו #3426.
_CANDIDATES_MAX = doc_sections.MAX_IDENTIFIER_SUGGESTIONS

#: קוד הסירוב כשגם עמוד **ריק** של סעיף אינו נכנס בתקציב הבתים (ראו
#: :func:`_fit_page`): הכותרות שהתשובה נושאת — הסעיף עצמו, ה-breadcrumb, עד
#: :data:`_TOC_MAX` תת-סעיפים והשכנים — גדולות ממנו לבדן, כלומר כותרות באורך
#: של פסקאות. ``_too_large`` כמו ``page_too_large`` ו-``item_too_large``, שגם
#: הם תשובה שאינה נכנסת, ולא ``section_too_long``, שהוא השאילתה שנדחתה. מיוצא,
#: כי ``codekeeper_get_file`` מוסיף לו את ההפניה ל-``lines``/``query``.
#:
#: **``bytes`` ו-``max`` באותה יחידה, ולכן ``bytes > max`` תמיד** (כך גם ב-
#: ``answer_too_large``): ``max`` הוא ``OUTPUT_BYTE_BUDGET`` עצמו — המספר
#: המתועד, ואותו מספר בכל כלי ובכל מצב — ו-``bytes`` הוא מה שהושווה לתקציב: מה
#: שהעמוד הקטן ביותר שנושא תוכן — תו אחד — היה צריך, במדידה של ההחלטה
#: (:func:`_fit_page`), כולל מה שהקורא מוסיף סביבו (``reserve_bytes`` של
#: :func:`answer_section`: ``found``/``status`` של ``codekeeper_get_file``). עד
#: #3472 (SUGG-008) ``max`` היה התקציב פחות המעטפת — 255,960 במצב ``section`` של
#: ``codekeeper_get_file`` — ו-``bytes`` בלי המעטפת: מספר שאינו מופיע בשום
#: תיעוד, ומשתנה לפי המצב. ו-``bytes`` נמדד על צורה אחרת מזו שההחלטה מדדה, כך שבסף
#: ההחלטה הוא יצא קטן מ-``max`` — ראו :func:`_fit_page`.
SECTION_TOO_LARGE = "section_too_large"

#: קוד הסירוב כשתשובה שנושאת רשימות — מפת הכותרות, ``section_not_found``
#: או ``ambiguous_section`` — אינה נכנסת בתקציב הבתים **גם כשכל הרשימות שלה
#: ריקות** (ראו ``answer_fit.fit_lists``). מה שמונע ממנה להיכנס אז הוא החלק הקבוע של
#: **התשובה**: ההקשר (המטא-דאטה של קובץ שמור, או ``repo``/``path``/``ref``),
#: ``includes`` ו-``requested``. ‏``requested`` חסום ב-:data:`MAX_SECTION_CHARS`,
#: אבל שני האחרים אינם חסומים בקוד: ``update_file_metadata_in`` בודק שהתגיות הן
#: רשימת מחרוזות ולא כמה או כמה ארוכות, לשם הקובץ אין תקרה בשכבת ה-MCP, והתיאור
#: חסום ב-``FILE_DESCRIPTION_MAX_CHARS`` רק במסלולי העדכון (#3489); ו-``includes``
#: של עמוד RST חסום רק בגודל הקובץ. כלומר הענף **ניתן להגעה**, ולכן הוא סירוב
#: מפורש ולא תנאי מת. בקבצים של היום הוא רחוק — המדידה על הקבצים השמורים, עם
#: השאילתה שהריצה אותה, בגוף PR #3470.
#:
#: **ומה שהסירוב עצמו נושא — זה, ולא יותר:** ``ok``, ההקשר, ``includes``,
#: ``error``, ``bytes`` ו-``max`` (:func:`_fit_or_refuse`). **הוא אינו מהדהד את
#: ``requested``** ואינו נושא אף אחת מהרשימות: ``requested`` נמנה למעלה כחלק ממה
#: שלא נכנס, לא כשדה של הסירוב. ``bytes`` ו-``max`` באותה יחידה, כמו ב-
#: :data:`SECTION_TOO_LARGE`: ``bytes`` הוא המספר שהושווה לתקציב — גודל התשובה כשכל
#: הרשימות שלה ריקות, ועוד ``reserve_bytes``. במפת הכותרות זה בדיוק מה שהיה נשלח.
#: ``section_not_found`` ו-``ambiguous_section`` יוצאים מ-``codekeeper_get_file`` בלי
#: ``found``/``status``, ובהם ``bytes`` גדול ממה שהיה נשלח ב-``reserve_bytes`` — כי
#: התקציב פחות המעטפת חל על כל הצורות (:func:`answer_section`), וזה המספר שההחלטה
#: נשענה עליו.
#:
#: **ההקשר נוסע גם על הסירוב, ולכן גם בו יש מה לקצר.** רשימה שיושבת בתוך ההקשר
#: ונמסרה ב-``refusal_cuts`` של :func:`answer_section` — בקובץ שמור ``file.tags``
#: — מוותרת על פריטים מהסוף עד שהסירוב נכנס, עם הדגל שלה לצידה (``file.tags_truncated``),
#: באותו ``answer_fit.fit_lists`` (#3472, SUGG-002). מחרוזת בהקשר אינה נחתכת: כשהסירוב
#: עדיין גדול, תיאור של קובץ שמור יורד שלם ובמקומו ``file.description_bytes``
#: (``answer_fit.fit_refusal``); השורש, כותבים שאינם אוכפים תקרה, ב-#3489. שם קובץ אינו
#: יורד — הוא הזהות של הסירוב. ``_too_large`` כמו :data:`SECTION_TOO_LARGE`:
#: ``codekeeper_get_file`` מוסיף לו את ההפניה ל-``lines``/``query``. **והוא גם הקוד של
#: כל סירוב אחר על תשובה שאינה נכנסת בתקציב** — קריאה מלאה של קובץ, רשימת פתקים, והרשת
#: שב-``AdminAwareFastMCP.call_tool`` — ולכן המילה מוגדרת ב-``answer_size``, והליבה של
#: הסירוב (``error``/``bytes``/``max``) נבנית ב-``answer_fit.too_large``. כל מודול
#: מייבא אותם משם בשמם, בלי שם שני (``tests/test_mcp_answer_size.py`` אוכף).

#: הסיומת ← **המודול** שמפרסר אותה. זהו המקום היחיד שאומר איזה פורמט הכלי
#: יודע לקרוא בכלל, ו-``DOCS_PATH_POLICY`` למטה אומר מי מהם מוגש בכל ריפו.
#: שתי שאלות שונות, ולכן שתי טבלאות — ו-``_validate_policy_tables`` קושר
#: ביניהן בייבוא כדי ששתיהן לא ייסחפו בשקט.
#:
#: **מודול ולא פונקציה, וזה נושא משקל.** ``parser.parse_document`` נפתר בזמן
#: הקריאה, ולכן ``monkeypatch.setattr(docs_handlers.rst_parser, "parse_document",
#: spy)`` בטסטים נתפס. טבלה שהייתה מחזיקה ``rst_parser.parse_document`` הייתה
#: קופאת על הפונקציה המקורית וה-spy היה נעקף **בשקט** — בלי שאף טסט קיים
#: ייפול. ``tests/test_mcp_docs_handlers.py::test_the_parser_table_holds_modules_
#: so_a_monkeypatch_on_the_module_is_seen`` מקבע את זה.
_PARSER_TABLE: dict[str, ModuleType] = {".rst": rst_parser, ".md": md_parser}
#: **מה שמיוצא אינו ניתן לשינוי** (#3432, SUGG-021): ``_validate_policy_tables``
#: רץ פעם אחת בייבוא, ושינוי של הטבלה אחריו עוקף אותו בשקט. ``MappingProxyType``
#: הופך את ההבטחה לתכונה — ``_PARSERS[".txt"] = x`` הוא ``TypeError`` — והטבלה
#: שמתחת, ``_PARSER_TABLE``, נשארת התפר לטסטים (``monkeypatch.setitem`` עליה
#: נראה דרך הפרוקסי מיד, ומוחזר בסוף הטסט).
_PARSERS: Mapping[str, ModuleType] = MappingProxyType(_PARSER_TABLE)


@dataclass(frozen=True)
class _DocsPathPolicy:
    """איפה גרים קובצי התיעוד של ריפו אחד, ובאיזו צורה.

    **שדה אחד לכל שאלה, ולא רשימה.** הגרסה הראשונה הצהירה על ``roots``
    ו-``suffixes`` כרשימות ועל מוסכמה ש"אינדקס 0 הוא ברירת המחדל". אף
    רשומה לא החזיקה יותר מערך אחד, והריבוי גבה מחיר אמיתי: שתי
    ``@property`` שכל תפקידן לתת שם לאינדקס 0, שתי לולאות שרצו איטרציה
    אחת, ותיאור הפרמטר ב-``server.py`` שנגזר מ-``roots[0]`` בלבד — כלומר
    שורש שני היה **נעלם מהתיאור שהסוכן קורא** בלי שאף בדיקה תשים לב.
    היום יש שני שדות, אין מוסכמת סדר, ואין מאיפה לסחוף.

    ``root`` ריק פירושו **שורש הריפו**: כל נתיב יחסי שאינו יוצא החוצה.
    זו אינה "בלי מדיניות" — הסיומת עדיין מסננת, וזה מה שמונע
    מ-``.claude/settings.json`` להיות נגיש.

    ריפו שיצטרך באמת שני שורשים או שני פורמטים ירחיב את זה ביום שהוא
    יתווסף, עם הצרכן שמצדיק את ההרחבה מול העיניים.
    """

    root: str
    suffix: str


#: הריפו ← איפה התיעוד שלו. **הטבלה הזאת היא מה שהקוד יודע לקרוא**;
#: ``MCP_DOCS_REPO`` הוא מה שהפריסה **מתירה**. ריפו חייב לעבור את שניהם,
#: וריפו שנמצא ב-ENV ואינו כאן נדחה ב-``repo_not_configured`` — הוא אינו
#: נופל לברירת מחדל מתירנית, מאותו נימוק שבגללו ``is_denied`` נכשל-סגור.
#:
#: .. danger::
#:
#:    **הרחבת גבול ה-IDOR כאן היא מכוונת, ולא תוצר לוואי.** הכלי ציבורי —
#:    כל משתמש מאומת קורא לו, בלי ``require_admin`` — ומה ששמר על הגבול עד
#:    היום היה ה**צירוף** של רשימת ההיתר ושל ההגבלה ל-``docs/*.rst``.
#:    ``amir-bug-patterns`` מקבל כאן את **שורש הריפו** עם ``**/*.md``, כלומר
#:    כל קובץ ``.md`` בו, בכל עומק, כולל תחת ``.claude/``. זה אושר על ידי
#:    בעל הפרויקט, והריפו ציבורי ב-GitHub. נספר לפני ההחלטה: 95 קבצים, 93
#:    מהם ``.md`` וכולם מסמכי דפוסים שנועדו לקריאה על ידי סוכן; שני הקבצים
#:    שאינם ``.md`` מסוננים ממילא על ידי הסיומת.
#:
#:    **ומה שהטבלה הזאת סומכת עליו הוא שם, ולא כתובת.** ``RepoBackend``
#:    פותר מראה לפי **שם**; הקשר בין השם ל-URL חי ברשומת ``repo_metadata``
#:    במונגו, ו-``mcp_server/repo_autosync.py`` משכפל ממנה. כלומר מי
#:    שיכול לכתוב לאוסף הזה — בעל הפריסה — יכול גם להחליף את מה שמוגש
#:    תחת השם הזה, והכלי הציבורי יגיש אותו בלי לשאול. זה מקובל כאן כי
#:    מדובר באותו אדם שמחליט מה נכנס לטבלה למעלה; מה שאינו מקובל הוא
#:    שההסתמכות תישאר לא כתובה.
#:
#:    מה ש**לא** משתנה: ``mcp_server.repo_policy.is_denied`` הוא ההוראה
#:    הראשונה ב-``RepoBackend.get_file`` וחל על המסלול הזה במלואו, כך
#:    ש-``secrets.md``, ``credentials.md`` ו-``.env*`` חסומים גם כאן.
_DOCS_PATH_POLICY_TABLE: dict[str, _DocsPathPolicy] = {
    "CodeBot": _DocsPathPolicy(root="docs", suffix=".rst"),
    "amir-bug-patterns": _DocsPathPolicy(root="", suffix=".md"),
}
#: קריאה בלבד, מאותו נימוק שכתוב ליד ``_PARSERS``: הוולידציה בייבוא היא הבטחה
#: רק אם הטבלה אינה משתנה אחריה. הטסטים שמוסיפים ריפו סינתטי עושים זאת על
#: ``_DOCS_PATH_POLICY_TABLE``.
DOCS_PATH_POLICY: Mapping[str, _DocsPathPolicy] = MappingProxyType(_DOCS_PATH_POLICY_TABLE)


def _validate_policy_tables() -> None:
    """נופל **בזמן הייבוא** על טבלה פגומה, ולא בתוך בקשה של משתמש.

    התקדים הוא ``md_parser._build_parser``: ``ruler.before("front_matter", ...)``
    נופל ב-``KeyError`` בייבוא כשהתוסף לא נרשם, וה-docstring שם מנמק במפורש
    למה זה עדיף על כשל שקט בזמן פרסור. כאן הכשל השקט היה ``KeyError`` על
    ``_PARSERS`` באמצע קריאה — כלומר 500 למשתמש, במקום שרת שלא עולה.

    ``RuntimeError`` ולא ``assert``, כי ``assert`` נמחק תחת ``-O``.

    **מה שהצמצום לשדות סקלריים כבר לקח מכאן:** בדיקת "רשימה ריקה" נעלמה,
    כי אין רשימה, ושתי הלולאות הפכו לבדיקות בודדות. מה שנשאר הוא הבדיקה
    היחידה שיש לה מצב כשל אמיתי — סיומת שמוצהרת ואין לה פארסר, כלומר
    סחיפה בין שתי טבלאות — ושתי בדיקות נרמול שמגינות מפני הקלדה בקבוע
    שלוש שורות מכאן.
    """
    for repo, policy in DOCS_PATH_POLICY.items():
        suffix = policy.suffix
        if not suffix.startswith(".") or suffix != suffix.casefold():
            raise RuntimeError(f"סיומת לא מנורמלת ב-{repo!r}: {suffix!r}")
        if suffix not in _PARSERS:
            raise RuntimeError(
                f"{repo!r} מצהיר על {suffix!r} ואין לו פארסר ב-_PARSERS")
        root = policy.root
        if root and (root.startswith("/") or root != posixpath.normpath(root)):
            raise RuntimeError(f"שורש לא מנורמל ב-{repo!r}: {root!r}")


_validate_policy_tables()


class _ResolvedPath(NamedTuple):
    """או נתיב **עם הסיומת שהוכרעה לו**, או קוד סירוב.

    ``str | None`` הספיק כל עוד הייתה סיבת דחייה אחת. הצורה
    ``value-or-error-string`` שב-``repo_backend.normalize_line_range`` אינה
    עובדת כאן, כי הנתיב וקוד השגיאה שניהם ``str`` ו-``isinstance`` אינו
    מבדיל ביניהם. ארבעה קודים חיים כאן היום, אחד לכל דחייה: ``missing_path``
    (אין נתיב — ריק או עם NUL), ``path_too_long``, ``suffix_not_allowed``,
    ו-``path_outside_root`` (הנתיב תקין בצורתו ופותר אל מחוץ לשורש התיעוד;
    עד #3432 הוא חלק קוד עם ``missing_path``, והקורא לא ידע אם שכח נתיב או
    ניסה לצאת מהשורש).

    **ו-``suffix`` נישא ולא נגזר מחדש, וזה תיקון לבאג שנתפס בבדיקה.**
    הגרסה הראשונה קראה ל-``_suffix_of`` פעם שנייה על הנתיב המוגמר כדי
    לבחור פארסר — כלומר אותה שאלה נענתה משתי מחרוזות שונות, וזה בדיוק מה
    ש-``_suffix_of`` מצהיר שהוא בא למנוע. נמדד: ``path=".."`` הופך
    ל-``"...md"``, ו-``posixpath.splitext("...md")`` מחזיר סיומת **ריקה**
    (נקודות מובילות אינן מפריד סיומת), ולכן הגזירה השנייה נתנה תשובה
    אחרת מהראשונה והפילה ``KeyError`` מתוך בקשה של משתמש.
    """

    path: str | None
    suffix: str | None
    error: str | None


def _allowed_docs_repos() -> list[str]:
    """רשימת הריפואים המותרים לכלי (CSV ב-MCP_DOCS_REPO), עם fallback ל-CodeBot."""
    raw = os.getenv("MCP_DOCS_REPO", DEFAULT_DOCS_REPO) or DEFAULT_DOCS_REPO
    repos = [r.strip() for r in raw.split(",") if r.strip()]
    return repos or [DEFAULT_DOCS_REPO]


def served_docs_repos() -> list[str]:
    """הריפואים ש-``codekeeper_docs_get_section`` מגיש בפועל, בסדר של ``MCP_DOCS_REPO``.

    **שני השערים של הכלי, ולא אחד מהם:** ריפו חייב להיות גם מותר בסביבה
    (:func:`_allowed_docs_repos`) וגם מוכר ל-:data:`DOCS_PATH_POLICY` — ריפו
    שמותר ואין לו מדיניות נדחה ב-``repo_not_configured`` (:func:`resolve_docs_target`),
    ולכן אינו "מוגש". הצרכן הוא בלוק ה-``instructions`` של השרת
    (``server.build_instructions``), שמונה את הריפואים האלה בשמם; רשימה שהייתה
    נגזרת מהסביבה בלבד הייתה מבטיחה לסוכן ריפו שהכלי מסרב לו.

    הסביבה נקראת בכל קריאה, כמו בכלי עצמו. כפילות ברשימה נספרת פעם אחת.
    """
    served: list[str] = []
    for repo in _allowed_docs_repos():
        if repo in DOCS_PATH_POLICY and repo not in served:
            served.append(repo)
    return served


def _resolve_docs_repo(repo: str | None) -> str | None:
    """ברירת מחדל = הריפו הראשון ב-allowlist; repo מפורש מותר רק אם ב-allowlist (אחרת None).

    הכלי ציבורי — בלי האכיפה הזו כל משתמש מאומת יכול לקרוא מכל ריפו ב-mirror (IDOR).

    **והכניסה הראשונה ב-ENV קובעת יותר ממה שנראה:** מאז שלכל ריפו יש מדיניות
    נתיבים משלו, היא קובעת גם את השורש וגם את הפורמט של קריאה שלא נקבה בריפו.
    שינוי סדר ב-``MCP_DOCS_REPO`` הוא שינוי התנהגות, לא סידור.
    """
    allowed = _allowed_docs_repos()
    r = (repo or "").strip()
    if not r:
        return allowed[0]
    return r if r in allowed else None


def _suffix_of(path: str) -> str:
    """סיומת הנתיב, מנורמלת ברישיות; ``""`` כשאין.

    **מקור אחד לשתי השאלות** — "האם הריפו מגיש את הצורה הזאת" ו"איזה מודול
    מפרסר אותה". שתי גזירות של אותה סיומת היו נסחפות זו מזו ברישיות.

    ``casefold`` ולא השוואה רגישת-רישיות, וזו הקונבנציה שכבר קיימת בריפו:
    ``mcp_server/outline.py::_scanner_for`` מנרמל באותה צורה בדיוק, וההערה
    מעל ``_SCANNERS`` מנמקת אותה. הערך המנורמל משמש **רק** לחיפוש בטבלאות
    ולעולם לא לחיתוך הנתיב עצמו, ולכן ``casefold`` שמשנה אורך (``ß`` ←
    ``ss``) אינו יכול להזיז שום אינדקס.
    """
    return posixpath.splitext(path)[1].casefold()


def _is_under(norm: str, root: str) -> bool:
    """האם נתיב **מנורמל** יושב תחת ``root``. ``root`` ריק = שורש הריפו.

    **הגבול נבדק כיחידה ולא כרצף תווים.** זו מחלקת הבאג ``K16`` ב-
    ``amir-bug-patterns`` (``path-prefix-not-boundary``): ``norm.startswith("docs")``
    לבדו מקבל את ``docsecret.rst``, שאין לו שום קשר היררכי ל-``docs/``.
    המפריד כתוב במפורש, וזרוע השוויון היא ההגדרה של "התיקייה עצמה".

    **ושורש ריק אינו "הכול".** נתיב מוחלט, ``..``, ונתיב שמטפס מעל שורש
    הריפו — כולם נדחים כאן. זה מה שהופך אותו ל"כל דבר בתוך הריפו" ולא
    ל"כל דבר בדיסק".
    """
    if not root:
        return (not norm.startswith("/")
                and norm != ".."
                and not norm.startswith("../"))
    return norm == root or norm.startswith(root + "/")


def _resolve_docs_path(path: str, policy: _DocsPathPolicy) -> _ResolvedPath:
    """נתיב מלא או slug קצר ← נתיב מנורמל שהריפו הזה מגיש.

    **סדר הפעולות אינו שרירותי, ושתי נקודות בו הן באגי אבטחה אם יזוזו:**

    1. ``strip``, דחיית ``\\x00``, **ודחיית אורך** — הערך מגיע מחוץ
       לתהליך, ושלוש הבדיקות האלה הן מה שמותר להניח עליו מכאן והלאה.
    2. הכרעת הסיומת: מותרת ← כמו שהיא; **פורמט אחר שהכלי מכיר** ← סירוב
       מפורש; כל דבר אחר ← חלק מה-slug, והסיומת מתווספת.
    3. **עגינה, על המחרוזת שלפני הנרמול.** זו הנקודה הראשונה:
       ``docs/../secrets`` נושא ``/`` ולכן אינו נעגן, ואחרי הנרמול הוא
       ``secrets.rst`` — מחוץ ל-``docs/``, ונדחה. מי ש"ינקה" את הקוד
       ויקדים את ``normpath`` יקבל ``secrets.rst`` בלי ``/``, יעגן אותו
       ל-``docs/secrets.rst``, **ויגיש אותו**.
    4. ``normpath`` — כאן, ורק כאן.
    5. הגבול מול השורש. זו הנקודה השנייה: ``startswith`` חשוף הוא
       ``K16``, ולכן הוא עטוף ב-``_is_under`` — ונתיב שנופל בה נדחה
       ב-``path_outside_root``, בשמו, ולא כ"נתיב חסר".
    """
    p = (path or "").strip().strip("/")
    if not p or "\x00" in p:
        return _ResolvedPath(None, None, "missing_path")
    if len(p) > MAX_PATH_CHARS:
        # **קוד משלו ולא ``missing_path``.** סירוב שאינו נוקב בסיבתו הוא
        # בדיוק ``blanket-policy-silent-block``: מבחוץ הוא נראה כמו נתיב
        # שגוי, והקורא מחפש את הטעות בשם הקובץ. ו-``silent-truncation-
        # at-sink`` אוסר את החלופה השנייה — לחתוך את הנתיב ולהמשיך
        # כאילו כלום. סירוב מוצהר הוא הצורה שהשארנו.
        return _ResolvedPath(None, None, "path_too_long")

    suffix = _suffix_of(p)
    if suffix != policy.suffix:
        if suffix in _PARSERS:
            # פורמט שהכלי מכיר, אבל לא זה שהריפו הזה מגיש. השלמה שקטה של
            # הסיומת כאן הייתה בונה ``docs/CRITICAL-PATTERNS.md.rst``
            # ומחזירה ``not_found`` על קובץ שקיים — כלומר סירוב שמתחזה
            # להיעדר, והקורא היה מחפש את הבאג במקום הלא נכון.
            return _ResolvedPath(None, None, "suffix_not_allowed")
        p = p + policy.suffix
        suffix = policy.suffix

    if policy.root and "/" not in p:
        p = policy.root + "/" + p

    norm = posixpath.normpath(p)
    if _is_under(norm, policy.root):
        return _ResolvedPath(norm, suffix, None)
    return _ResolvedPath(None, None, "path_outside_root")


def _capped(items: list, limit: int) -> tuple[list, bool]:
    """‏``(items, truncated)`` — הרשימה עד ``limit``, והאם באמת נחתכה.

    **פונקציה אחת לשני הגבולות של התשובה** (``toc`` ו-``candidates``), כדי
    שהשאלה "מתי הדגל נכון" תיענה במקום אחד: ``True`` רק כשהיו יותר מהתקרה,
    ולעולם לא על רשימה שבדיוק בגודלה — אותו גבול כמו ``Capped.append``
    ב-``_ceiling`` וכמו ``max_sections`` בפארסר.
    """
    if len(items) > limit:
        return items[:limit], True
    return items, False


def _toc(doc: doc_sections.Document) -> tuple[list, bool]:
    return _capped(doc_sections.build_toc(doc), _TOC_MAX)


def _line_of(exc: BaseException) -> dict:
    """``{"line": N}`` כשהחריגה נושאת מספר שורה, ו-``{}`` כשלא.

    **הצורה המותנית ולא שדה שקיים תמיד**, ומאותו נימוק בדיוק שבגללו
    ``suggestions_truncated`` ו-``remaining_chars`` מותנים: שדה שיופיע
    גם כשאין מה לשים בו מלמד את הקורא ש-``line: null`` הוא מצב אפשרי,
    והוא אינו.

    ``args`` ולא אטריביוט ייעודי, כי זה מה ששלוש החריגות שנושאות שורה
    באמת מחזיקות: ``InconsistentLineEndings`` ו-``TooManySections`` נבנות
    ב-``raise X(n)``, ו-``TooManyTokens`` שמה את השורה ב-``args[0]`` — או
    ``None`` כשעוד לא נוצר טוקן עם מיקום, ואז אין שדה. בדיקת הטיפוס אינה
    נימוס: ``args`` יכול להיות ריק אם מישהו יעלה אותן בלי ארגומנט, ואז
    ``args[0]`` היה מפיל את הבקשה במקום להחזיר סירוב.

    **ולא ל-``TooManyLines``**: ה-``args[0]`` שלה הוא **מספר השורות** ולא שורה
    שבה נעצרנו, והמטפל קורא אותה בשמות.
    """
    args = getattr(exc, "args", ())
    if args and isinstance(args[0], int):
        return {"line": args[0]}
    return {}


def _title_flag(sec: doc_sections.Section) -> dict:
    """``{"title_truncated": True}`` כשכותרת הסעיף נחתכה ל-``MAX_TITLE_CHARS``, אחרת ``{}``.

    בעלים אחד לדגל בכל צורות התשובה בצד ה-``mcp_server`` שנושאות כותרת של סעיף:
    ``_section_ref`` (תת-סעיפים ושכנים), מועמדי ``ambiguous_section``, ותשובת הסעיף.
    כך שם חתוך לעולם אינו מופיע בלי הסימן שהוא חלקי — אחרת שתי כותרות שחולקות קידומת
    מעל התקרה נראות זהות. מותנה, ולא ``False`` תמידי: לכותרת אמיתית הוא אינו נדלק,
    וכך אפס-הדיף נשמר. (``doc_sections.build_toc`` נושא עותק משלו של אותו דגל על
    רשומות המפה — שכבת ``services`` אינה מייבאת מ-``mcp_server`` — וזהות הדגל בין
    השניים נשמרת: אותו שם מפתח, אותו תנאי.)
    """
    return {"title_truncated": True} if sec.title_truncated else {}


def _section_ref(sec: doc_sections.Section) -> dict:
    return {"title": sec.title, "level": sec.level,
            "line_range": [sec.heading_line, sec.end_line], **_title_flag(sec)}


class DocsTarget(NamedTuple):
    """קובץ תיעוד מוכרע — מה שידוע אחרי השער הטהור, ולפני שנקרא בית אחד.

    ``repo`` הוא הריפו אחרי רשימת ההיתר, ``path`` הנתיב המנורמל שהמדיניות של
    הריפו מגישה, ו-``suffix`` הסיומת **שהוכרעה לו** — היא שבוחרת את הפארסר,
    ולעולם אינה נגזרת שוב מהנתיב (ראו :class:`_ResolvedPath`).
    """

    repo: str
    path: str
    suffix: str


class LoadedDocument(NamedTuple):
    """מסמך שנקרא ופורסר, וההקשר שכל תשובה עליו נושאת.

    ``context`` נכנס לכל תשובה על המסמך, גם לסירוב, **כמו שהוא** — ויש לו שתי
    צורות, לפי מי שקרא את המסמך:

    * **מראה** (``codekeeper_docs_get_section``, ``codekeeper_read_batch``):
      ``repo``/``path``/``ref``/``resolved_commit`` — :func:`document_from_read`.
    * **קובץ שמור** (``codekeeper_get_file`` עם ``toc`` או ``section``): ``{"file":
      <המטא-דאטה של הקובץ בלי התוכן>}`` — ``_apply_sections_to_file`` ב-
      ``mcp_server/backend.py``. **אין בה ``repo`` ולא ``path``.**

    ולכן קוד שעובד על ``LoadedDocument`` אינו מניח אחת מהן: הוא מעביר את ``context``
    הלאה כמו שהוא (``**context``), כמו :func:`_answer_from_document`.
    """

    doc: doc_sections.Document
    context: dict[str, Any]


def resolve_docs_target(*, path: str, repo: str | None = None) -> DocsTarget | dict[str, Any]:
    """השער הטהור של ``codekeeper_docs_get_section``: ריפו, מדיניות ונתיב — בלי לקרוא דבר.

    מחזיר :class:`DocsTarget`, או את **אותה** תשובת סירוב שהכלי מחזיר:
    ``repo_not_allowed``, ``repo_not_configured``, ``suffix_not_allowed``,
    ``path_too_long``, ``path_outside_root`` או ``missing_path``.

    **למה זה חלק נפרד.** ``codekeeper_read_batch`` מקבץ פריטים לפי הקובץ שהם
    קוראים, כדי לקרוא ולפרסר כל קובץ פעם אחת — ולכן הוא צריך את הנתיב
    המוכרע **לפני** הקריאה. ``docs_get_section`` עובר באותה פונקציה, כך שאין
    שני נוסחים של השער. ``scripts/docs_section_zero_diff.py`` הוא מה שמראה
    שהפיצול לא שינה אף תשובה, כולל תשובות הסירוב.
    """
    # **הריפו נבדק לפני הנתיב.** אחרת קורא שנקב בריפו שאינו רשאי לגעת בו
    # היה לומד ממנו משהו: ``suffix_not_allowed`` מול ``missing_path`` מספר
    # לו מה הפורמט שהריפו ההוא מגיש.
    repo_name = _resolve_docs_repo(repo)
    if not repo_name:
        return {"ok": False, "error": "repo_not_allowed", "requested_repo": repo}
    policy = DOCS_PATH_POLICY.get(repo_name)
    if policy is None:
        # fail-closed: ה-ENV מתיר, והקוד אינו יודע איפה גר התיעוד שם. זו
        # תקלת הפעלה שרק מי שמחזיק את ההגדרות יכול לתקן, ולכן גם שורת לוג
        # ולא רק תשובה לקורא — התשובה מגיעה לסוכן, הלוג מגיע למפעיל.
        logger.warning(
            "MCP_DOCS_REPO מתיר ריפו שאין לו מדיניות נתיבים: %r", repo_name)
        return {"ok": False, "error": "repo_not_configured", "repo": repo_name}

    resolved = _resolve_docs_path(path, policy)
    if resolved.error == "suffix_not_allowed":
        # ``allowed_suffixes`` נשאר **רשימה** אף שהמדיניות מחזיקה סיומת
        # אחת: זה החוזה שהלקוח כבר קורא, וצמצום שדה בתשובה כדי להתאים
        # אותו לצורה הפנימית הוא שינוי שובר בלי שום תמורה לקורא.
        return {"ok": False, "error": "suffix_not_allowed", "repo": repo_name,
                "requested_path": path, "allowed_suffixes": [policy.suffix]}
    if resolved.error == "path_too_long":
        return {"ok": False, "error": "path_too_long", "repo": repo_name,
                "max_chars": MAX_PATH_CHARS, "actual_chars": len(path or "")}
    if resolved.error == "path_outside_root":
        # השורש כבר כתוב בתיאור הכלי לכל ריפו, ולכן אמירתו כאן אינה מגלה
        # דבר — היא רק חוסכת לקורא לחפש את הטעות בשם הקובץ.
        return {"ok": False, "error": "path_outside_root", "repo": repo_name,
                "root": policy.root}
    # ``suffix`` תמיד מוכרע כשיש ``path`` (ראו ``_resolve_docs_path``); הבדיקה
    # כאן רק מצמצמת את הטיפוס, ואינה מסלול שאפשר להגיע אליו.
    if not resolved.path or resolved.suffix is None:
        return {"ok": False, "error": "missing_path"}
    return DocsTarget(repo_name, resolved.path, resolved.suffix)


def section_read_arguments(*, repo: str, path: str, ref: str | None = None) -> dict[str, Any] | None:
    """הארגומנטים שבהם ``codekeeper_docs_get_section`` קורא **את אותו קובץ** — או ``None``.

    הצרכן הוא ``outline`` של ``codekeeper_get_repo_file``: על קובץ שאין לו מפה
    (``no_outline`` / ``unsupported_language``) התשובה מפנה לכלי הזה, שמחזיר את
    עץ הכותרות של אותו קובץ — אבל רק כשהכלי הזה באמת מגיש אותו.

    **נגזר מהשער של הכלי עצמו** (:func:`resolve_docs_target`), ולא מרשימה שנייה
    או מכלל כמו "כל ``.md``": ב-CodeBot הכלי מגיש רק ``docs/*.rst``, והפניה
    קבועה הייתה שולחת את הסוכן לכלי שיחזיר גם הוא "לא נמצא". כשהמדיניות תשתנה,
    ההפניה משתנה איתה.

    **ורק כשהשער מחזיר בדיוק את הריפו והנתיב שהתבקשו.** השער גם משלים: לנתיב
    עם סיומת שאינה מוכרת הוא מוסיף את הסיומת של הריפו, ו-slug בלי ``/`` הוא
    מעגן לשורש. ``.claude/hooks/codekeeper-primer.sh`` ב-``amir-bug-patterns``
    היה נהיה ``...primer.sh.md`` — קובץ אחר — ולכן השוואה מלאה ולא "השער קיבל".

    ``ref`` נכנס רק כשהקורא העביר אחד, וכמו שהוא: בלעדיו שני הכלים קוראים את
    הענף הראשי, ואיתו הפניה בלי ``ref`` הייתה קוראת ענף אחר מזה שהתבקש.
    """
    target = resolve_docs_target(path=path, repo=repo)
    if not isinstance(target, DocsTarget):
        return None
    if target.repo != repo or target.path != path:
        return None
    arguments: dict[str, Any] = {"repo": target.repo, "path": target.path}
    if ref:
        arguments["ref"] = ref
    return arguments


def load_document(
    backend: Any,
    target: DocsTarget,
    *,
    ref: str | None = None,
    snapshot: Any = None,
) -> LoadedDocument | dict[str, Any]:
    """קריאה ופרסור של קובץ מוכרע אחד — כל מה שהכלי עושה חוץ מבחירת הסעיף.

    ``snapshot`` מגיע רק מ-``codekeeper_read_batch`` (``RepoBackend.snapshot``),
    ומועבר ל-``backend.get_file`` **רק כשהוא קיים** — כך שהכלי הבודד קורא
    ל-backend בדיוק באותם ארגומנטים כמו לפני שהפרמטר נוסף.
    """
    # קריאה — reuse מלא של RepoBackend.get_file (ref default, מדיניות סודות, sync_in_progress).
    # **בלי ``lines`` ובלי ``outline`` בכוונה:** כך ``wants_slice`` הוא False, לא מועבר
    # ``max_size``, ותקרת 500KB של שירות המראה נשארת ההגנה היחידה על הפרסור.
    pinned = {"snapshot": snapshot} if snapshot is not None else {}
    res = backend.get_file(repo=target.repo, path=target.path,
                           ref=((ref or "").strip() or None), **pinned)
    return document_from_read(res, target)


def document_from_read(res: dict[str, Any], target: DocsTarget) -> LoadedDocument | dict[str, Any]:
    """מה שהכלי עושה עם תשובת ``backend.get_file``: סירוב בהקשר, או מסמך מפורסר.

    **נפרד מ-:func:`load_document` בשביל קריאה משותפת.** ``codekeeper_read_batch``
    קורא קובץ פעם אחת גם כשפריט קובץ ופריטי סעיף מבקשים אותו יחד, ואז מעביר
    לכאן את מה שכבר נקרא במקום לקרוא שוב.

    **מוטציה, ובכוונה:** בכשל ``res`` עצמו מקבל ``repo`` ו-``path`` ומוחזר — זו
    התשובה שהכלי מחזיר תמיד. מי שמחזיק את ``res`` גם לשימוש אחר מעביר לכאן
    עותק.
    """
    if not res.get("ok"):
        # not_found / ref_not_mirrored / invalid_ref / invalid_input / path_denied /
        # sync_in_progress — מוסיפים הקשר ומעבירים הלאה. ``ref`` ו-``resolved_commit``
        # של ``not_found`` כבר באים מ-``RepoBackend.get_file``, כמו בכלי הקבצים, ולא
        # נבנים כאן שוב.
        res.setdefault("repo", target.repo)
        res.setdefault("path", target.path)
        return res
    if res.get("status") != "ok":
        # binary / too_large — אין תוכן טקסט לפרסר
        return {"ok": False, "error": f"unreadable_{res.get('status')}",
                "repo": target.repo, "path": target.path, "file": res.get("file")}

    content = res.get("content") or ""
    file_meta = res.get("file") or {}
    # ההקשר נבנה **לפני** הפרסור, כי גם סירוב צריך לומר איזה קובץ, באיזה ריפו
    # ובאיזה commit. ``{"error": "too_many_sections"}`` לבדו אינו ניתן לפעולה.
    context: dict[str, Any] = {
        "repo": target.repo, "path": target.path,
        "ref": file_meta.get("ref"),
        "resolved_commit": file_meta.get("resolved_commit"),
    }

    # ``target.suffix`` ולא גזירה שנייה מ-``target.path``: ראו :class:`_ResolvedPath`.
    parser = _PARSERS[target.suffix]  # לעולם לא KeyError: ראו _validate_policy_tables

    parsed = parse_with_refusals(parser, content, context)
    if isinstance(parsed, dict):
        return parsed
    return LoadedDocument(parsed, context)


def parse_with_refusals(
    parser: ModuleType, content: str, context: Mapping[str, Any]
) -> doc_sections.Document | dict[str, Any]:
    """פרסור אחד, וכל חריגות הסירוב של הפרסר ממופות לתשובת ``error`` — מקום אחד לשני הכלים.

    ``codekeeper_docs_get_section`` מגיע לכאן דרך :func:`document_from_read`, ו-
    ``codekeeper_get_file`` עם ``section`` או ``toc`` מגיע לכאן ישירות, על קובץ
    שמור. **פונקציה אחת ולא שני עותקים של אותו מיפוי**, כי הסירובים הם חוזה עם
    הקורא — אותם שמות, אותם שדות — וסירוב חדש שהפרסר ילמד להרים היה נכנס לעותק
    אחד ונבלע בשני כשגיאה כללית. ``tests/test_mcp_file_sections.py`` מקבע ששני
    הכלים באמת עוברים כאן.

    ``context`` הוא מה שכל תשובה על הקובץ הזה נושאת, גם סירוב: ל-docs
    ``repo``/``path``/``ref``/``resolved_commit``, ולקובץ שמור ``file`` — המטא-דאטה
    שלו בלי התוכן. מה שנוסף לסירוב אחרי שחזר (הפניה ל-``lines``/``query`` בקובץ
    שמור) הוא עניינו של הקורא, ולא נכנס לכאן.
    """
    # **שני הפרסרים רצים על ברירת המחדל שלהם, והכלי אינו מעביר תקרה.**
    # ברירת המחדל של ``max_sections`` בשניהם היא ``doc_sections.MAX_SECTIONS``
    # (50,000; מיושרת מאז #3420 — בין #3429 ל-#3420 ברירת המחדל של
    # ``rst_parser`` הייתה ``None`` והכלי העביר לו את ``_ceiling.MAX_SYMBOLS``
    # במפורש). העברה מפורשת מכאן הייתה עותק שני של החלטה שהפארסר כבר הכריע,
    # ו-``parser is rst_parser`` היה מקום שלישי שבו סמנטיקת הסיומת חיה. הטסט
    # שמקטין את התקרה עושה זאת בפרסר (``functools.partial``), לא כאן.
    #
    # מה שהתקרה עוצרת ב-RST (סקירת #3429): כותרת בת תו אחד בכל שורה ב-500KB
    # עולה בלעדיה יותר ממה שמאגר הקריאות מקצה לחוט (``_PARSE_COST_BYTES`` ב-
    # ``server.py``), ואיתה פחות. המספרים, התאריך והסקריפט שמודד אותם — ליד
    # ``_PARSE_RSS_PER_INPUT_BYTE``, ולא כאן, כדי שמדידה חוזרת תשנה מקום אחד.
    # אף עמוד אמיתי אינו מתקרב: 500KB של העמוד הצפוף ביותר הם כ-3,300 סקשנים.
    #
    # **ובמסלול ה-Markdown עוד שתי תקרות, מאז #3391**, כי תקרת הכותרות לבדה
    # אינה נוגעת בקובץ עוין בלי כותרות: ``MAX_LINES`` לפני הפרסור, ו-``MAX_TOKENS``
    # בכל טוקן שנוצר — גם באמצע טבלה ובאמצע רשימה. שתיהן ברירות מחדל של
    # ``md_parser.parse_document``, וגם אותן הכלי אינו מעביר. מה הן עוצרות, ואיך
    # נבחרו המספרים — ליד הקבועים ב-``services/md_parser.py``.

    # **ה-``try`` הזה אינו ``K11``, וזה נכתב כדי שסקירה עתידית לא תגזור זאת
    # מחדש.** ``parse_document`` מתועד כ"ערוץ הכשל הוא חריגה בלבד": הוא אינו
    # מחזיר ``None`` ואינו מחזיר ``Document`` חלקי בכשל, ומפה ריקה היא הצלחה
    # תקינה של קובץ בלי כותרות. זה ה-false-positive ש-K11 מונה במפורש —
    # "פונקציות raise-on-error מתועדות, שם try/except הוא הערוץ הנכון".
    #
    # **וכל חריגות הסירוב מיובאות מ-``doc_sections`` ולא מ-``parser.X``.**
    # ``rst_parser`` אינו מרים לעולם את ``InconsistentLineEndings``,
    # ``TooManyLines`` ו-``TooManyTokens`` ואינו מייצא אותן, וייצוא משם היה
    # מצהיר על סירוב שאינו קיים. התפיסה אינה מותנית במי שפרסר, כי תנאי כזה היה
    # רשימה שנייה לסנכרן.
    #
    # **ומה שלא נתפס כאן, בכוונה:** ``TypeError`` של שני הפרסרים (מאז #3421
    # גם ``rst_parser`` מרים אותה, דרך ``doc_sections.require_str``) ו-
    # ``RuntimeError`` של ``md_parser``. שניהם אומרים "חוזה נשבר" ולא "הקלט
    # נדחה", ועטיפתם הייתה בדיוק ``widened-exception-scope``. ``content`` הוא
    # תמיד מחרוזת בשני המסלולים: ב-docs, כי ``binary`` ו-``too_large`` נחסמו
    # ב-:func:`document_from_read`; ובקובץ שמור, כי הקורא מוודא ש-``code`` הוא
    # מחרוזת לפני שהוא מגיע לכאן.
    #
    # תקרת המקביליות על הפרסור אינה כאן ואינה צריכה להיות: היא נגזרת מגודל
    # מאגר הקריאות, ומקומה ב-lifespan של השרת — נחת ב-#3429.
    #
    # **והמופע נקשר, כי הוא נושא את מה שאפשר לפעול לפיו.** שלוש מהחריגות
    # נושאות ב-``args[0]`` את השורה (1-מבוססת) שבה הפרסור עצר, וזו כל הסיבה
    # שהן חריגות ולא דגל. ``except X:`` בלי ``as`` זרק בדיוק את הערך היחיד
    # שאפשר לפעול לפיו, בתוך הבלוק שההערה מעליו מסבירה למה קוד שגיאה לבדו
    # אינו ניתן לפעולה. **הרביעית, ``TooManyLines``, אינה נושאת שורה** — הפרסור
    # לא התחיל — ולכן היא נקראת בשמות (``total_lines``, ``limit``) ולא דרך
    # ``_line_of``, שהיה הופך את מספר השורות לשורה שלא קיימת.
    #
    # ``_line_of`` ולא ``exc.args[0]`` ישירות: חריגה שתיבנה מחר בלי
    # ארגומנט לא תפיל כאן ``IndexError`` באמצע בקשה.
    #
    # ``"max"`` הוא המספר שהפרסר באמת השתמש בו, ולא עותק שלו ממודול אחר:
    # ל-``too_many_sections`` זה ``doc_sections.MAX_SECTIONS`` (אותה ברירת מחדל
    # בשני המסלולים), ולשתי התקרות של ``md_parser`` — ``exc.limit``, התקרה
    # שהחריגה נבנתה איתה.
    try:
        return parser.parse_document(content)
    except doc_sections.InconsistentLineEndings as exc:
        return {"ok": False, "error": "inconsistent_line_endings",
                **context, **_line_of(exc)}
    except doc_sections.TooManyLines as exc:
        return {"ok": False, "error": "too_many_lines",
                "max": exc.limit, **context, "total_lines": exc.total_lines}
    except doc_sections.TooManyTokens as exc:
        return {"ok": False, "error": "too_many_tokens",
                "max": exc.limit, **context, **_line_of(exc)}
    except doc_sections.TooManySections as exc:
        return {"ok": False, "error": "too_many_sections",
                "max": doc_sections.MAX_SECTIONS, **context, **_line_of(exc)}


def _paging(max_chars: Any, offset: Any) -> tuple[int, int]:
    """``max_chars`` ו-``offset`` אחרי ההידוק — מקום אחד לשני הקוראים שלמטה."""
    return (_clamp(max_chars, MAX_CHARS_MIN, MAX_CHARS_MAX, MAX_CHARS_DEFAULT),
            _clamp(offset, 0, 10 ** 9, 0))


def answer_section(
    loaded: LoadedDocument,
    *,
    section: str | None = None,
    include_subsections: bool = True,
    max_chars: int = MAX_CHARS_DEFAULT,
    offset: int = 0,
    reserve_bytes: int = 0,
    refusal_cuts: tuple[Cut, ...] = (),
    refusal_notes: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """מה ש-:func:`docs_get_section` עונה על ``section``, מתוך מסמך שכבר נקרא ופורסר.

    ``codekeeper_read_batch`` קורא לזה פעם לכל פריט סעיף, על מסמך אחד שנקרא
    ופורסר פעם אחת לכל הפריטים מאותו קובץ. **ברירות המחדל הן של
    ``docs_get_section``**, כי פריט סעיף בבאץ' הוא בדיוק הכלי הבודד בלי
    הפרמטרים האלה; ``tests/test_mcp_read_batch.py`` מקבע ששתי החתימות לא נפרדו.

    ו-``codekeeper_get_file`` עם ``section`` או ``toc`` קורא לזה על קובץ שמור
    (``mcp_server/backend.py``), עם ``{"file": <מטא-דאטה>}`` כהקשר — כך שהתאמת
    הכותרת, החיתוך, העימוד ובניית התשובה הם **אותה פונקציה** בשני הכלים, ולא
    עותק שני. הוא אינו מעביר ``include_subsections``, ולכן תת-הסעיפים תמיד כלולים
    אצלו.

    ``reserve_bytes`` — מה שהקורא עוד יוסיף סביב התשובה לפני שהיא נשלחת. כל צורה
    של התשובה נחתכת אל ``OUTPUT_BYTE_BUDGET`` פחות זה — עמוד הסעיף ב-:func:`_fit_page`
    והרשימות ב-``answer_fit.fit_lists`` — כדי שהתשובה **כפי שהיא יוצאת** תיכנס.
    ``codekeeper_get_file`` מוסיף ``found`` ו-``status`` ושומר להם מקום; הבאץ' אינו
    עוטף את התשובה אלא מקנן אותה, ומודד את זה בעצמו. ובסירובים שנולדים מהתקציב
    (:data:`SECTION_TOO_LARGE`, ``answer_too_large``) ``bytes`` כולל אותו, ו-``max``
    הוא ``OUTPUT_BYTE_BUDGET`` — אותה יחידה.

    ``refusal_cuts`` — רשימות בתוך ``context`` שסירוב מוותר עליהן כדי להיכנס בתקציב
    (:func:`fit_refusal`), בסדר הוויתור. בקובץ שמור זה ``file.tags``; ב-docs ובבאץ'
    אין כאלה, ולכן ברירת המחדל ריקה והתשובות שלהם לא משתנות. **רק סירוב** מוותר עליהן
    — תשובה מוצלחת נושאת את ההקשר כמו שהוא — וב-``section_not_found`` וב-
    ``ambiguous_section`` הן **הראשונות** שמוותרים עליהן, לפני המפה, ההצעות
    והמועמדים: מטא-דאטה שווה פחות מהתשובה עצמה.
    """
    max_chars, offset = _paging(max_chars, offset)
    return _answer_from_document(loaded.doc, context=loaded.context, section=section,
                                 include_subsections=include_subsections,
                                 max_chars=max_chars, offset=offset,
                                 reserve_bytes=reserve_bytes, refusal_cuts=refusal_cuts,
                                 refusal_notes=refusal_notes)


def docs_get_section(
    backend: Any,
    *,
    path: str,
    section: str | None = None,
    include_subsections: bool = True,
    max_chars: int = MAX_CHARS_DEFAULT,
    offset: int = 0,
    repo: str | None = None,
    ref: str | None = None,
) -> dict[str, Any]:
    """``codekeeper_docs_get_section``: שער, הידוק, קריאה ופרסור, ואז תשובה.

    הסדר הוא הסדר שהיה כאן לפני שהפונקציה פוצלה ל-:func:`resolve_docs_target`,
    :func:`load_document` ו-:func:`answer_section`, כולל ההידוק **לפני** הקריאה.
    """
    target = resolve_docs_target(path=path, repo=repo)
    if isinstance(target, dict):
        return target
    max_chars, offset = _paging(max_chars, offset)
    loaded = load_document(backend, target, ref=ref)
    if isinstance(loaded, dict):
        return loaded
    return _answer_from_document(loaded.doc, context=loaded.context, section=section,
                                 include_subsections=include_subsections,
                                 max_chars=max_chars, offset=offset)


def _answer_from_document(
    doc: doc_sections.Document,
    *,
    context: dict[str, Any],
    section: str | None,
    include_subsections: bool,
    max_chars: int,
    offset: int,
    reserve_bytes: int = 0,
    refusal_cuts: tuple[Cut, ...] = (),
    refusal_notes: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """ארבע צורות התשובה של הכלי, מתוך מסמך שכבר נפרסר.

    **מה שנפרד מ-``docs_get_section`` (#3432, SUGG-020):** הפונקציה ההיא —
    מאז ``codekeeper_read_batch`` דרך :func:`resolve_docs_target` ו-
    :func:`load_document` — פותרת ריפו, פותרת נתיב, קוראת קובץ ובוחרת
    פארסר — ארבע החלטות שכל אחת מהן יכולה לסרב — ומכאן והלאה יש רק מסמך
    ושאלה. הזנב הזה הוא החלק שנפרד
    הכי נקי, ואפס-דיף על 208 קובצי ה-RST (``scripts/docs_section_zero_diff.py``)
    הוא מה שמוכיח שהוא רק זז.

    ארבע הצורות: ``toc`` כשאין ``section``; ``section_not_found`` עם הצעות;
    ``ambiguous_section`` עם מועמדים; ו-``section`` עם התוכן, השכנים
    ותת-הסקשנים. ``context`` הוא ``repo``/``path``/``ref``/``resolved_commit``
    שכל תשובה נושאת — או ``file`` כשהקורא הוא ``codekeeper_get_file`` (שתי הצורות —
    :class:`LoadedDocument`). ולפניהן סירוב חמישי, ``section_too_long`` (ראו
    :data:`MAX_SECTION_CHARS`).

    ``reserve_bytes`` ו-``refusal_cuts`` — ראו :func:`answer_section`. כל סירוב שנבנה
    כאן עובר :func:`fit_refusal` עם ``refusal_cuts``, ו-``section_not_found`` ו-
    ``ambiguous_section`` מוותרים עליהן לפני הרשימות שלהם.

    **התקציב — ``OUTPUT_BYTE_BUDGET`` פחות ``reserve_bytes`` — חל על כל ארבע הצורות**,
    בבתים כפי שהתשובה נשלחת (``wire_json``), ובשתי דרכים:

    * **עמוד של סעיף** נגמר מוקדם יותר ואינו מאבד דבר, כי העימוד לפי ``offset``
      ממשיך בדיוק משם (:func:`_fit_page`); ``truncation_reason`` אומר למה.
    * **הרשימות של שלוש הצורות האחרות** — ``toc``, ‏``suggestions`` ו-``candidates``
      — נחתכות מהסוף עד שהתשובה נכנסת (``answer_fit.fit_lists``). את אלה אי אפשר
      לעמד, ולכן הדגל של כל רשימה (``toc_truncated``, ‏``suggestions_truncated``,
      ‏``candidates_truncated``) נושא **שתי סיבות**: התקרה במספר פריטים
      (:data:`_TOC_MAX`, ‏``MAX_IDENTIFIER_SUGGESTIONS``, :data:`_CANDIDATES_MAX`),
      או התקציב — ואז נחתך מוקדם יותר. בשני המקרים הקורא עושה אותו דבר: מבקש
      סעיף בשמו, או קורא טווח שורות. ב-``section_not_found`` המפה נחתכת לפני
      ההצעות, כי המפה היא מלאי וההצעות הן התשובה לשאלה. המועמדים נשארים בסדר
      המסמך, ולכן מה שחסר הוא תמיד הסוף.

    תשובה שאינה נכנסת גם כשכל הרשימות שלה ריקות — ``answer_too_large``; ועמוד
    שאינו נכנס גם בלי תוכן — :data:`SECTION_TOO_LARGE`.
    """
    # ``includes`` הוא שדה של פארסר: ``rst_parser`` ממלא אותו מיעדי
    # ``.. include::``, ול-Markdown אין צורה כזאת ולכן הוא **תמיד ריק**.
    # הוא נשאר ללא תנאי — אפס כאן אינו "לא בדקנו" אלא "אין מה לבדוק",
    # והשמטה הייתה שוברת קורא שכותב ``res["includes"]`` וגם הייתה מקום
    # שלישי שבו סמנטיקת הסיומת חיה.
    base: dict[str, Any] = {"ok": True, **context, "includes": list(doc.includes)}
    budget = OUTPUT_BYTE_BUDGET - reserve_bytes
    fitting = {"budget": budget, "reserve_bytes": reserve_bytes, "context": context,
               "doc": doc, "refusal_cuts": refusal_cuts, "refusal_notes": refusal_notes}

    # **לפני כל עבודה שגדלה עם ``section``** — ההתאמה, ההצעות, וההד ב-``requested``.
    # בלי ``requested`` ובלי TOC: התשובה אינה מהדהדת את מה שנדחה בגלל גודלו.
    if section is not None and len(section) > MAX_SECTION_CHARS:
        base.update({"ok": False, "error": "section_too_long",
                     "max_chars": MAX_SECTION_CHARS, "actual_chars": len(section)})
        return fit_refusal(base, refusal_cuts, refusal_notes)

    toc_items, toc_truncated = _toc(doc)

    # בלי section → עץ כותרות (הכלי משמש גם לניווט)
    if not (section or "").strip():
        # ``section_count`` נשאר מספר הכותרות כולן גם כשהמפה נחתכת — כך הקורא יודע
        # כמה חסר. **בלי ``refusal_cuts`` ב-``cuts``:** זו תשובה מוצלחת, והיא נושאת
        # את ההקשר כמו שהוא; רק ``answer_too_large`` שבמקומה מוותר עליהן.
        base.update({"mode": "toc", "toc": toc_items, "toc_truncated": toc_truncated,
                     "section_count": len(doc.sections)})
        return _fit_or_refuse(base, cuts=(("toc", "toc_truncated"),), **fitting)

    matches = doc_sections.find_sections(doc, section)

    # לא נמצא → TOC מלא + הצעות קרובות (לעולם לא רק "לא נמצא")
    if not matches:
        # ``n`` מפורש, וזו אמירה ולא מספר שרירותי: **התשובה הזאת היא מלאי,
        # לא קיצור.** ``suggest`` מגיש שני סוגי תשובה — דירוג קצר של כותרות
        # קרובות, ורשימת המזהים שקיימים בעמוד — ולשני הסוגים מתאימה כמות
        # אחרת. לשאלה "ביקשת מזהה שאינו קיים, אלה שכן" אין דירוג: חיתוך
        # שרירותי שלה מסתיר פריטים בלי שום קריטריון, ולסוכן אין פרמטר לבקש
        # את השאר. נמדד: עם ברירת המחדל (5), עמוד עם 16 מזהים החזיר את חמשת
        # הראשונים **בסדר הופעה**, וסוכן ששאל ``K11`` לא ראה אותו כלל.
        #
        # ה-handler הוא המקום היחיד שיודע איזו שאלה נשאלה, ולכן הבקשה יושבת
        # כאן ולא כברירת מחדל של הפונקציה.
        suggestions = doc_sections.suggest(
            doc, section, n=doc_sections.MAX_IDENTIFIER_SUGGESTIONS)
        base.update({
            "ok": False, "error": "section_not_found", "requested": section,
            # ``.titles`` ולא האובייקט: ``suggest`` מחזיר ``NamedTuple`` בן שני
            # שדות, ומי שישכח את זה ישלח לקורא ``[[...], false]`` בלי שום שגיאה.
            "suggestions": list(suggestions.titles),
            "toc": toc_items, "toc_truncated": toc_truncated,
        })
        if suggestions.truncated:
            # רק כשנחתכה, ולא שדה שקיים תמיד — ``remaining_chars`` ו-``next_offset``
            # למטה הם אותו תקדים בדיוק. וזו גם הסיבה המעשית: שדה שיופיע בכל תשובת
            # ``section_not_found`` היה משנה את הפלט על כל 208 קובצי ה-RST בלי ששום
            # התנהגות השתנתה, ושובר את הוכחת אפס-הדיף שהשינוי הזה נשען עליה.
            base["suggestions_truncated"] = True
        # המפה לפני ההצעות: המפה היא מלאי, וההצעות הן התשובה לשאלה שנשאלה. ולפני
        # שתיהן — הרשימות שבהקשר (``refusal_cuts``): זה סירוב, והמטא-דאטה שווה בו פחות
        # מהתשובה לשאלה.
        return _fit_or_refuse(
            base, cuts=refusal_cuts + (("toc", "toc_truncated"),
                                       ("suggestions", "suggestions_truncated")),
            **fitting)

    # כותרת כפולה → כל המועמדים עם breadcrumb (בלי לנחש). ``line_range`` ו-``breadcrumb``
    # אינם קישוט: כותרת ששמה המלא חוזר לעולם אינה נענית בשמה, והם הדרך אליה — בטווח
    # השורות, או דרך הורה. התיאור שהסוכן קורא על זה הוא ``_SECTION_PARAM_DOC``.
    if len(matches) > 1:
        candidates, candidates_truncated = _capped(matches, _CANDIDATES_MAX)
        base.update({
            "ok": False, "error": "ambiguous_section", "requested": section,
            "candidates": [{
                "title": s.title, "breadcrumb": list(s.breadcrumb),
                "level": s.level, "line_range": [s.heading_line, s.end_line],
                **_title_flag(s),
            } for s in candidates],
        })
        if candidates_truncated:
            # רק כשנחתך — אותה מוסכמה של ``suggestions_truncated`` ו-``remaining_chars``:
            # שדה שקיים תמיד היה משנה כל תשובת ``ambiguous_section`` בתצלום
            # אפס-הדיף בלי ששום התנהגות השתנתה.
            base["candidates_truncated"] = True
        # **בסדר המסמך, והחיתוך מהסוף** — גם כאן וגם בתקרה שלמעלה. כך מה שחסר הוא
        # תמיד המועמדים האחרונים, והדרך אליהם כתובה במקום אחד, ``_SECTION_PARAM_DOC``
        # ב-``server.py``. בלי הסדר הקבוע חיתוך היה מעלים מועמד שרירותי, וסירוב שמסתיר
        # את מה שחיפשו בלי לומר איך מגיעים אליו הוא סירוב מטעה. הרשימות שבהקשר
        # (``refusal_cuts``) קודמות למועמדים, מאותו נימוק כמו ב-``section_not_found``.
        return _fit_or_refuse(
            base, cuts=refusal_cuts + (("candidates", "candidates_truncated"),), **fitting)

    # התאמה יחידה → הסקשן + ניווט (שכנים ותת-סקשנים)
    sec = matches[0]
    full = doc_sections.section_text(doc, sec, include_subsections)
    total = len(full)
    chunk = full[offset:offset + max_chars]
    truncated = (offset + len(chunk)) < total
    prev, nxt = doc_sections.neighbors(doc, sec)
    # **תת-הסעיפים חסומים באותה תקרה של המפה** — הם שורות מאותה מפה, רק של ענף
    # אחד. בלעדיה זה היה השדה היחיד בתשובה בלי גבול, כמו ``candidates`` לפני
    # #3426, וסעיף עם אלפי תת-סעיפים עבר בגללו לבדו את ``OUTPUT_BYTE_BUDGET``.
    subsections, subsections_truncated = _capped(
        doc_sections.direct_subsections(doc, sec), _TOC_MAX)

    base.update({
        "mode": "section",
        "section": sec.title,
        "breadcrumb": list(sec.breadcrumb),
        "level": sec.level,
        "line_range": [sec.heading_line, sec.end_line],
        "include_subsections": bool(include_subsections),
        "offset": offset,
        "content": chunk,
        "truncated": truncated,
        "subsections": [_section_ref(s) for s in subsections],
        "neighbors": {
            "prev": _section_ref(prev) if prev else None,
            "next": _section_ref(nxt) if nxt else None,
        },
    })
    if subsections_truncated:
        # רק כשנחתכה — אותה מוסכמה של ``candidates_truncated`` ושל ``remaining_chars``.
        base["subsections_truncated"] = True
    # הכותרת עצמה נחתכה ל-``MAX_TITLE_CHARS`` (מקרה פתולוגי, לא בקורפוס). ``section``
    # כאן הוא כבר הצורה החתוכה, וזו גם הצורה שמתאימה בהתאמה — כך שהדבקתה חזרה מוצאת
    # את הסעיף. אותו ``_title_flag`` בדיוק כמו במועמדים, בתת-הסעיפים ובשכנים; מותנה,
    # ולכן אפס-דיף לכותרת אמיתית.
    base.update(_title_flag(sec))
    if truncated:
        base["remaining_chars"] = total - (offset + len(chunk))
        base["next_offset"] = offset + len(chunk)

    page, size = _fit_page(base, total=total, budget=budget)
    if page is None:
        # ``bytes`` הוא מה שהושווה לתקציב, ועוד המעטפת; ``max`` — התקציב המתועד. אותה
        # יחידה, ולכן ``bytes > max`` (ראו :data:`SECTION_TOO_LARGE`).
        return fit_refusal(
            {"ok": False, **context, "includes": list(doc.includes),
             "error": SECTION_TOO_LARGE, "bytes": size + reserve_bytes,
             "max": OUTPUT_BYTE_BUDGET, "line_range": [sec.heading_line, sec.end_line]},
            refusal_cuts, refusal_notes)
    return page


def _fit_page(
    page: dict[str, Any], *, total: int, budget: int
) -> tuple[dict[str, Any] | None, int]:
    """עמוד הסעיף בתוך ``budget`` בתים **כפי שהוא נשלח** — וגודלו.

    ``max_chars`` סופר תווים, והתקציב הוא בתים: תו עברי הוא שני בתים, תו CJK
    שלושה ואימוג'י ארבעה, וב-JSON שורה חדשה או מירכאה הן שני תווים. לכן עמוד
    של ``MAX_CHARS_MAX`` תווי CJK הוא פי שלושה בתים, ועבר את
    ``OUTPUT_BYTE_BUDGET`` עד שהפונקציה הזו נוספה (ריוויו על PR #3470). חסם
    בתווים אינו חסם בבתים — אותה טעות כבר נפלה פעם בעמוד האאוטליין (ההערה ליד
    ``QUERY_SNIPPET_MAX_BYTES`` ב-``handlers.py``).

    **עמוד שאינו נכנס נגמר מוקדם יותר — ולא נדחה.** בעימוד לפי ``offset`` זה
    חיתוך בלי אובדן: ``truncated`` נדלק, ``next_offset`` הוא איפה שהעמוד באמת
    נגמר, והקריאה הבאה ממשיכה בדיוק משם. ``truncation_reason: "byte_budget"``
    אומר לקורא למה קיבל פחות מ-``max_chars``, ומופיע רק אז. זה ההפך מ-
    ``page_too_large`` באאוטליין, ששם עימוד אריתמטי (``per_page``) היה מאבד
    סימבולים — כאן אין מה לאבד.

    **המדידה היא על התשובה כולה, בצורה שה-SDK שולח** (:func:`~mcp_server.
    answer_size.wire_json`). קודם נמדד העמוד **בלי תוכן**, עם כל השדות שעמוד
    חתוך נושא — ``truncated``, הסיבה, ו-``remaining_chars``/``next_offset`` בערך
    הגדול ביותר שהם יכולים לקבל (``total``), כך שהערכים האמיתיים לעולם אינם
    ארוכים ממה שנמדד. מה שנשאר עד התקציב הוא המקום לתוכן, ו-
    :func:`_longest_prefix_within` מוצא כמה תווים ממנו נכנסים בו.

    **ולא חיתוך לפי בתי UTF-8, וזה נמדד.** הגרסה הראשונה הורידה את העודף בבתי
    UTF-8 (``clip_to_bytes``), מתוך ההנחה שכל תו עולה ב-JSON לפחות את בתי ה-UTF-8
    שלו. ההנחה נכונה — אבל היא חוסמת מלמטה בלבד: תו בקרה הוא בית אחד ב-UTF-8
    ושישה ב-JSON (``\\u0001``), והעודף של עמוד כזה גדול מכל בתי ה-UTF-8 שלו.
    הקיצוץ מחק את כל התוכן, וסעיף שעמוד של 42,915 תווים ממנו נכנס בתקציב חזר
    כ-``section_too_large`` עם ``bytes`` של 610 (``tests/test_mcp_file_sections.py``,
    המקרה ``control``).

    ``(None, size)`` — כשאין עמוד **לא ריק** שנכנס: מה שנשאר בתשובה בלי שום
    תוכן, ועוד התו הראשון, גדול מהתקציב. עמוד ריק עם ``next_offset`` שלא זז היה
    שולח קורא ממושמע ללולאה אינסופית, ולכן זה סירוב (:data:`SECTION_TOO_LARGE`)
    ולא עמוד.

    **ו-``size`` שם הוא בדיוק מה שהושווה לתקציב** (#3472): העמוד בלי תוכן **במדידה
    של ההחלטה** — עם ``remaining_chars``/``next_offset`` בערך ``total`` — ועוד העלות
    של התו הראשון, באותה מדידה של :func:`_longest_prefix_within`. כלומר: כמה היה
    צריך העמוד הקטן ביותר שנושא תוכן. לכן ``size > budget`` תמיד כשהעמוד נדחה, וב-
    :data:`SECTION_TOO_LARGE` ``bytes > max``. עד #3472 ``size`` נמדד על צורה אחרת —
    אותו עמוד ריק אחרי שהשדות קיבלו את ערכם הסופי (``next_offset: 0``), שקצרה בכמה
    ספרות מהצורה שההחלטה מדדה, ובלי התו — וכשהסעיף היה בבתים ספורים מהתקציב, הסירוב
    אמר ``bytes`` קטן מ-``max`` (נמדד בסף ההחלטה: 255,997 מול 256,000).
    """
    size = len(wire_json(page))
    if size <= budget:
        return page, size
    content = page["content"]
    offset = page["offset"]
    fitted = {**page, "content": "", "truncated": True, "remaining_chars": total,
              "next_offset": total, "truncation_reason": BYTE_BUDGET_REASON}
    measured = len(wire_json(fitted))
    keep = _longest_prefix_within(content, budget - measured)
    if not keep:
        return None, measured + len(wire_json(content[:1])) - 2
    end = offset + keep
    fitted.update({"content": content[:keep], "remaining_chars": total - end,
                   "next_offset": end, "truncation_reason": cut(returned=keep, of=total - offset)})
    return fitted, len(wire_json(fitted))


def _longest_prefix_within(text: str, room: int) -> int:
    """כמה תווים מתחילת ``text`` נכנסים ב-``room`` בתים — כמחרוזת JSON, כפי שנשלחת.

    חיפוש בינארי על מספר התווים, וכל ניסיון נמדד באותה סריאליזציה של התשובה
    (``wire_json`` על מחרוזת הוא המחרוזת במירכאות, ולכן מינוס 2). העלות של
    קידומת עולה עם אורכה — לכל תו יש עלות קבועה משלו — ולכן החיפוש נכון. והחיתוך
    הוא על גבול תו, כי מה שנחתך הוא ``str`` ולא בתים. ``room`` שלילי — אפס.
    """
    return _longest_fitting_prefix(len(text), lambda keep: len(wire_json(text[:keep])) - 2 <= room)


def _fit_or_refuse(
    answer: dict[str, Any],
    *,
    cuts: tuple[Cut, ...],
    budget: int,
    reserve_bytes: int,
    context: dict[str, Any],
    doc: doc_sections.Document,
    refusal_cuts: tuple[Cut, ...],
    refusal_notes: Mapping[str, str] | None,
) -> dict[str, Any]:
    """התשובה אחרי ``answer_fit.fit_lists`` — או ``answer_too_large`` כשגם ריקה אינה נכנסת.

    מקום אחד לצורת הסירוב, לשלוש הצורות שנושאות רשימות. הסירוב נושא את ההקשר
    ואת ``includes`` כמו כל תשובה של הכלי, ואת ``bytes`` — גודל התשובה אחרי שכל
    הרשימות רוקנו, ועוד ``reserve_bytes``: כמה גם המינימום גדול, במספר שהושווה
    לתקציב (ראו ``answer_too_large``) — ואת ``max``, שהוא ``OUTPUT_BYTE_BUDGET``:
    אותה יחידה, ולכן ``bytes > max`` תמיד. ``requested`` והרשימות אינם בו. והסירוב
    עצמו עובר :func:`fit_refusal`, כמו כל סירוב שנושא את ההקשר.
    """
    fitted, size = fit_lists(answer, cuts=cuts, budget=budget, record=True)
    if fitted is None:
        return fit_refusal(
            {"ok": False, **context, "includes": list(doc.includes), **too_large(size + reserve_bytes)},
            refusal_cuts, refusal_notes)
    return fitted


def _longest_fitting_prefix(limit: int, fits: Callable[[int], bool]) -> int:
    """הגדול מבין ``1..limit`` ש-``fits`` מקבל, או 0 — חיפוש בינארי.

    הקורא הוא :func:`_longest_prefix_within`, שמחפש כמה תווים של תוכן העמוד נכנסים
    בתקציב — כל ניסיון נמדד ב-``wire_json``, ומובא לכאן כ-``fits``. (חיתוך הרשימות
    ב-``answer_fit.fit_lists`` אינו עובר כאן: הוא מצטבר לפי עלות פר-פריט, בלי חיפוש.)
    ההנחה היחידה היא ש-``fits`` מונוטוני — אם קידומת נכנסת, גם כל קידומת קצרה ממנה
    — וזה נכון, כי כל תו מוסיף בתים ואף אחד לא מוריד. 0 חוזר גם כשאף קידומת לא
    נכנסת, בלי לבדוק את 0 עצמו: הקורא בודק אותו, כי רק הוא יודע מה לעשות אז.
    """
    lo, hi = 0, limit
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if fits(mid):
            lo = mid
        else:
            hi = mid - 1
    return lo
