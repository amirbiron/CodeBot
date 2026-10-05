"""Pure tool handlers.

These are plain functions (no MCP / no Starlette imports) that validate and
clamp inputs, then delegate to a ``Backend``. Keeping them separate from the
FastMCP wiring makes the business logic trivially unit-testable.

Every handler takes an authoritative, server-derived ``user_id`` — callers must
never pass a client-supplied user id here.
"""

from __future__ import annotations

import functools
import html
import itertools
import re
from typing import Annotated, Any, Callable, NamedTuple

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from .answer_size import BYTE_BUDGET_REASON, list_item_cost

# תקרת התוכן מיובאת ולא מוקלדת. עד היום MCP והוובאפ החזיקו כל אחד את המספר
# שלו, כך ששינוי באחד היה משאיר את השני אוכף ערך אחר — ואז אותו פתק נדחה
# בערוץ אחד ומתקבל בשני.
from sticky_notes_target import MAX_NOTE_CHARS as MAX_NOTE_CONTENT
from sticky_notes_target import DEFAULT_NOTE_COLOR_ID, resolve_note_color

# המפרט של העלאות ה-MCP — מודול שורש טהור, בלי מסד ובלי MCP, ולכן מותר כאן.
from mcp_uploads import UPLOAD_TTL_SECONDS, UploadStorageUnavailable, is_upload_id

# תקרת האורך של תיאור קובץ — מודול שורש טהור (``typing`` בלבד), ולכן מותר כאן. עד
# #3489 הקבוע ישב ב-``database.repository``, והמודול הזה לא יכול היה לייבא אותו
# בלי לגרור את חבילת המסד — ולכן ``codekeeper_save_file`` לא אכף אותו כלל.
from file_description import description_length_error

MAX_PER_PAGE = 200
MAX_SEARCH_LIMIT = 100
MAX_COLLECTIONS_LIMIT = 500
# Fallback when the app config isn't importable (kept in sync with config.MAX_CODE_SIZE).
DEFAULT_MAX_CODE_SIZE = 100_000


# ``strict=True`` על פרמטרים מסוג ``int`` ו-``list[int]`` — **ולא** על דגלים מסוג ``bool``;
# למה לא, בהערה שמתחת ל-``StrictLines`` (#3472).
#
# נמדד מול Pydantic דרך FastMCP: ``list[int]`` **מקבל** ``[True, 5]`` וממיר
# אותו ל-``[1, 5]``, וגם ``["3", "9"]`` ו-``[3.0, 9]`` עוברים. במצב כזה
# ``lines=[True, 5]`` היה מחזיר בשקט את שורות 1‑5. אי אפשר לתפוס את זה
# בוולידציה שלנו, כי הערך שמגיע לכאן הוא כבר ``int`` אמיתי — ההמרה קורית
# בגבול, לפני שהקוד הזה רץ. לכן ההגנה חייבת לשבת בהצהרת הטיפוס.
#
# ``strict`` דוחה את שלושתם, **והסכימה שהלקוח רואה נשארת זהה**:
# ``{"anyOf": [{"items": {"type": "integer"}, "type": "array"}, {"type": "null"}]}``
# — בלי ``prefixItems``, ולכן בלי סיכון תאימות מול לקוחות.
StrictInt = Annotated[int, Field(strict=True)]
StrictLines = Annotated[list[StrictInt], Field(strict=True)]
# **ולדגל בוליאני אין צורה strict כאן — בכוונה, וזו הכרעה ולא שכחה** (#3472, WARN-002).
# ``toc`` היה ``StrictBool`` מ-#3470 ועד #3472 — הדגל היחיד בשרת שהוצהר strict — והוא
# הוחזר ל-``bool`` רגיל כמו ``outline``. שתי עובדות, שתיהן נקראו במקור ונמדדו:
#
# * **ל-``bool`` אין קריאה שגויה מקבילה ל-``lines=[True, 5]``.** שם ה-strict מונע
#   ערך שנקרא כמשהו אחר ממה שהתכוונו אליו — שורה 1 במקום ``True``. בדגל, ההמרה של
#   pydantic נותנת בדיוק את המשמעות שהלקוח התכוון אליה: ``"true"``, ``"yes"``, ``1``
#   ← ``True``; ``"false"``, ``"no"``, ``0`` ← ``False``; וכל השאר (``2``,
#   ``"maybe"``) — שגיאת ולידציה (``pydantic 2.12.3``, נמדד).
# * **``"true"`` מגיע לכלי כמחרוזת.** ``pre_parse_json`` של ה-SDK מפענח אותה ל-
#   ``True``, ו-``True`` הוא ``int``, ולכן הוא זורק את הפענוח ומשאיר את המחרוזת
#   (``mcp 1.28.1``, ``func_metadata.py``: ``isinstance(pre_parsed, str | int | float)``).
#   כלומר strict על דגל אינו מונע קריאה שגויה אלא **חוסם לקוח ששולח בוליאני כמחרוזת**
#   — וב-``toc`` זה חסם אותו בכניסה לפיצ'ר, בזמן ש-``outline=true`` אצלו עבד.
#
# מה שכן נשאר: רשת ``isinstance`` ב-:func:`file_read_request_error`, לקורא שעוקף את
# הסכימה ומגיע עם משהו שאינו ``bool``. מי שמוסיף דגל חדש — ``bool`` רגיל, והנימוק
# כאן ובמוסכמות ב-Handoff ("הערך שהכלי מקבל אינו תמיד הערך שנשלח").

# קודי השגיאה של קריאת טווח. אותם קודים בדיוק בשני הכלים.
LINE_RANGE_INVALID = "invalid_line_range"
LINE_RANGE_OUT_OF_BOUNDS = "range_out_of_bounds"

# קודי השגיאה של חיפוש בתוך קובץ (``codekeeper_get_file`` עם ``query``).
# ``QUERY_TOO_SHORT`` הוא אותו קוד שכבר מחזיר ``codekeeper_search_repo`` על
# שאילתה שאין בה די, כי זו אותה שאלה ואין סיבה לאוצר מילים שני.
QUERY_AND_LINES = "query_and_lines"
QUERY_TOO_SHORT = "query_too_short"
QUERY_INVALID = "invalid_query"

# שאילתה שפרוסה על יותר משורה אחת נדחית, ולא מוחזרת כ"אפס מופעים". הסיבה
# מבנית ולא נוחות: כל רשומה בתשובה עוגנת לשורה אחת — ``line``, ``snippet``,
# וההמשך ב-``lines=[line, line]`` — ולהתאמה שחוצה שורות אין ``line`` מוגדר.
# בלי הדחייה הזו ``query in text`` יכול להיות אמת בעוד התשובה מדווחת
# ``total: 0`` **כהצלחה**, כלומר תשובה שקרית שנראית בטוחה ואין בה שגיאה.
QUERY_MULTILINE = "query_multiline"

# ``context_lines`` ו-``max_results`` נושאים משמעות רק יחד עם ``query``.
# העברתם בלעדיו מקבלת סירוב מפורש ולא התעלמות שקטה — אותה הכרעה שמאחורי
# ``QUERY_AND_LINES``: פרמטר שהתקבל ונזרק הוא אותה שתיקה בדיוק. שני קודים
# ולא אחד, כדי שהקורא ידע איזה משני הפרמטרים נדחה.
CONTEXT_LINES_WITHOUT_QUERY = "context_lines_without_query"
MAX_RESULTS_WITHOUT_QUERY = "max_results_without_query"

# קודי השגיאה של קריאה לפי סעיף (``codekeeper_get_file`` עם ``section`` או
# ``toc``). **קוד לכל זוג מצבים ולא קוד אחד לכולם**, מאותה סיבה ש-
# ``QUERY_AND_LINES`` קיים: הקורא צריך לדעת **איזה** שניים מהפרמטרים שלו אינם
# מצטברים, ולא רק ש"משהו התנגש". ארבעת מצבי הקריאה — ``toc``, ``section``,
# ``query`` ו-``lines`` — אינם מצטברים אף אחד עם אחר.
TOC_AND_SECTION = "toc_and_section"
TOC_AND_QUERY = "toc_and_query"
TOC_AND_LINES = "toc_and_lines"
SECTION_AND_QUERY = "section_and_query"
SECTION_AND_LINES = "section_and_lines"


class ReadMode(NamedTuple):
    """מצב קריאה אחד של ``codekeeper_get_file``: שם הפרמטר, והאם הוא דגל.

    ``flag`` קובע איך יודעים שהמצב התבקש: דגל — כשערכו אמת (``toc=false`` אינו
    מצב); כל השאר — כשהפרמטר נשלח בכלל (``is not None``), גם עם ערך שיידחה.
    """

    param: str
    flag: bool


#: ארבעת מצבי הקריאה של ``codekeeper_get_file``, **בסדר שבו הם נבדקים**. זה המקור
#: היחיד לסדר (#3472, SUGG-005): ממנו נגזרים גם הזוגות שנדחים (``_EXCLUSIVE_READ_MODES``
#: למטה) וגם התווית באנליטיקס (``read_mode_properties`` ב-``mcp_server/analytics.py``,
#: שמייבא את זה). עד #3472 הסדר היה כתוב פעמיים — כאן, ושרשרת ``if`` באנליטיקס —
#: וסוכם ביניהם רק טסט; מצב חמישי שהיה נכנס לאחד מהם במקום אחר היה מתייג בשקט קריאה
#: שנדחתה במצב הלא נכון.
FILE_READ_MODES = (
    ReadMode("toc", flag=True),
    ReadMode("section", flag=False),
    ReadMode("query", flag=False),
    ReadMode("lines", flag=False),
)

#: הקוד של כל זוג מצבים שאינם מצטברים. **הטבלה אינה קובעת סדר** — הסדר נגזר מ-
#: :data:`FILE_READ_MODES` — אלא רק איזה קוד שייך לאיזה זוג, כדי שהקודים יישארו
#: קבועים שאפשר לחפש ב-``grep`` ולא מחרוזות שנבנות בזמן ריצה.
_PAIR_CODES = {
    ("toc", "section"): TOC_AND_SECTION,
    ("toc", "query"): TOC_AND_QUERY,
    ("toc", "lines"): TOC_AND_LINES,
    ("section", "query"): SECTION_AND_QUERY,
    ("section", "lines"): SECTION_AND_LINES,
    ("query", "lines"): QUERY_AND_LINES,
}

#: כל זוג מצבים שאינם מצטברים, **בסדר שבו הם נבדקים** — בקשה שנוקבת בשלושה
#: מצבים מקבלת את הזוג הראשון כאן שתואם, ותמיד אותו אחד. הזוגות הם כל הצירופים של
#: :data:`FILE_READ_MODES` בסדר שלו (``itertools.combinations`` שומר אותו), ולכן
#: הזוג שבקשה מקבלת נפתח במצב שקודם בסדר — אותו מצב שהאנליטיקס רואה ראשון.
#: ``QUERY_AND_LINES`` אחרון, וזה לא משנה דבר לבקשה שנוקבת רק בשניהם: היא מקבלת
#: אותו כמו קודם. **מצב חדש בלי קוד בטבלה נופל בייבוא** (``KeyError``), ולא בבקשה.
_EXCLUSIVE_READ_MODES = tuple(
    (first.param, second.param, _PAIR_CODES[(first.param, second.param)])
    for first, second in itertools.combinations(FILE_READ_MODES, 2)
)

# ``max_chars`` ו-``offset`` מעמדים **סעיף**, ובלי ``section`` אין מה לעמד — אותה
# הכרעה בדיוק כמו ``CONTEXT_LINES_WITHOUT_QUERY``: פרמטר שהתקבל ונזרק הוא
# התעלמות שקטה. שני קודים ולא אחד, כדי שהקורא ידע איזה מהשניים נדחה.
MAX_CHARS_WITHOUT_SECTION = "max_chars_without_section"
OFFSET_WITHOUT_SECTION = "offset_without_section"

# ``section`` שאינו מחרוזת — רשת מאחורי הסכימה, כמו ``QUERY_INVALID``. ו-``section``
# ריק או רווחים בלבד **אינו** "בלי ``section``": ב-``codekeeper_docs_get_section``
# הוא מחזיר את מפת הכותרות, אבל כאן המפה היא מצב נפרד (``toc=true``), וקריאה
# שביקשה סעיף ולא נקבה באף כותרת מקבלת סירוב שמפנה אליה — לא מפה בשקט.
SECTION_INVALID = "invalid_section"
SECTION_EMPTY = "empty_section"
# ``toc`` שאינו ``bool`` — רשת לקורא שאינו עובר בסכימה. דרך הסכימה ``toc`` הוא ``bool``
# רגיל, שממיר ``"true"``/``"false"`` כמו כל דגל אחר (ראו ההערה מעל ``StrictInt``);
# מי שעוקף אותה ומגיע עם מחרוזת נדחה כאן, ולא נקרא כמצב המפה.
TOC_INVALID = "invalid_toc"

# הסירובים שקורים **אחרי** קריאת הקובץ, כשהבקשה עצמה תקינה: הקובץ אינו Markdown,
# או שהוא גדול מכדי לפרסר אותו. ``too_large_for_sections`` ולא ``too_large`` של
# מראת הריפואים: שם ``status`` הוא הצלחה בלי תוכן, וכאן זה סירוב של המצב בלבד —
# הקובץ עצמו קריא, בקריאה מלאה או ב-``lines``.
NOT_MARKDOWN = "not_markdown"
TOO_LARGE_FOR_SECTIONS = "too_large_for_sections"

#: ההפניה שכל סירוב של מצב הסעיפים נושא כשהקובץ עצמו קריא — ``not_markdown``,
#: ``too_large_for_sections`` וסירובי הפרסר. **בקובץ שמור אין ריפו לתקן בו**:
#: ``inconsistent_line_endings`` ב-``codekeeper_docs_get_section`` מפנה בפועל
#: לתיקון הקובץ, וכאן מה שהקורא יכול לעשות מיד הוא לקרוא בדרך אחרת.
SECTIONS_UNAVAILABLE_HINT = 'read this file with lines=[start, end] or query="..." instead'

#: הפניה לסירובי צורת הבקשה, רק היכן שיש לקורא צעד ברור אחד.
_REQUEST_ERROR_HINTS = {
    SECTION_EMPTY: "pass toc=true for the heading map, then one of its titles as section",
}

# התקרות של חיפוש בתוך קובץ. **אותם מספרים בדיוק** כמו ב-
# ``repo_handlers.SEARCH_RESULTS_DEFAULT`` / ``SEARCH_RESULTS_MAX`` /
# ``CONTEXT_LINES_MAX``, כי ``query`` מחזיר את צורת התשובה של
# ``codekeeper_search_repo`` — ושתי תקרות שונות לאותה צורת תשובה הן בדיוק הסוג
# של הפער שמייצר באגים.
#
# **משוכפלים כאן ולא מיובאים, וזו הגבלה אמיתית ולא העדפה:** ``repo_handlers``
# מייבא ``_clamp`` מהמודול הזה, וייבוא הפוך היה מעגלי. אותה מוסכמה שכבר קיימת
# בין ``analytics.py`` ל-``server.py``. **תקציב הבתים כבר אינו ביניהם:** עד #3474
# הוא היה עותק רביעי כאן (``QUERY_OUTPUT_BYTE_BUDGET``), ועכשיו שני החיפושים
# מייבאים אותו מ-``answer_size``, המודול שאין לו תלויות פנימיות.
#
# **ומה שסוגר את הפער הוא אכיפה, לא זיכרון:**
# ``tests/test_mcp_file_query.py`` משווה את שני העותקים **וגם** מעגן כל אחד
# למספר ליטרלי שכתוב בטסט. שוויון לבדו אינו מספיק — הוא נשאר ירוק גם אם שני
# העותקים ישונו יחד לערך שגוי, כלומר אוכף עקביות ולא נכונות.
QUERY_RESULTS_DEFAULT = 50
QUERY_RESULTS_MAX = 100
QUERY_CONTEXT_LINES_MAX = 10
#: ``truncation_reason`` של תשובת ``query`` שנחתכה בתקרת המופעים שביקשו — אותה מילה
#: של ``codekeeper_search_repo``. הסיבה השנייה היא ``byte_budget``
#: (``answer_size.BYTE_BUDGET_REASON``), כשתקציב הבתים עצר לפני התקרה.
MAX_RESULTS_REASON = "max_results"

# תקרת הטקסט של רשומה אחת — **בבתים, ולא בתווים**.
#
# ``codekeeper_search_repo`` חותך ``[:500]`` תווים (``git_mirror_service``),
# והמספר 500 נלקח משם. מה שהוחלף היא **היחידה**: תו עברי הוא שני בתים ותו CJK
# שלושה, ולכן חסם בתווים אינו אומר דבר על גודל התשובה בפועל — נמדד בפרויקט
# הזה שעמוד שנחסם ב-200 תווים לרשומה הגיע ל-323,000 בתים מול תקציב של 256,000.
# החיתוך עצמו נעשה על גבול תו ולעולם לא באמצע אחד; ראו :func:`clip_to_bytes`.
QUERY_SNIPPET_MAX_BYTES = 500


def normalize_line_range(lines: Any) -> tuple[int, int] | str:
    """מאמת ``lines=[start, end]`` ומחזיר ``(start, end)`` או קוד שגיאה.

    **הפונקציה הזו היא המקור היחיד לסמנטיקה של הטווח**, ושני הכלים
    (``codekeeper_get_file`` ו-``codekeeper_get_repo_file``) קוראים לה — כדי
    שלא תיווצר אסימטריה ביניהם. אימות האורך נעשה כאן ולא בהצהרת הטיפוס, כי
    ``strict`` אינו אוכף אורך (נמדד: ``[3, 9, 12]`` עובר).

    1-indexed וכולל את שני הקצוות. ``end`` שחורג מסוף הקובץ מקוצץ על ידי
    הקורא, אחרי שהוא יודע כמה שורות יש בפועל.
    """
    if not isinstance(lines, (list, tuple)) or len(lines) != 2:
        return LINE_RANGE_INVALID
    start, end = lines
    # ``bool`` הוא תת-מחלקה של ``int``; ההגנה האמיתית היא ב-``StrictLines``,
    # וזו רשת נוספת לקוראים שאינם עוברים דרך הסכימה.
    if isinstance(start, bool) or isinstance(end, bool):
        return LINE_RANGE_INVALID
    if not isinstance(start, int) or not isinstance(end, int):
        return LINE_RANGE_INVALID
    if start <= 0 or end <= 0 or start > end:
        return LINE_RANGE_INVALID
    return (start, end)


def count_lines(text: str) -> int:
    """ספירת השורות שכל שדות ה-``lines`` בתשובות ה-MCP מדווחים לפיה.

    ``split("\n")`` ולא ``splitlines()``, כדי שהמספר יתאים לשדות שכבר
    יושבים לצידו באותה תשובה: ``file.lines`` נספר ב-
    ``content.count("\n") + 1`` (``services/git_mirror_service.py``), ו-
    ``file.lines_count`` של קובץ שמור נספר ב-``len(content.split("\n"))``
    (``database/models.py``, ``database/repository.py``). שתי הצורות זהות
    לחלוטין — נמדד על כל מקרי הקצה, כולל מחרוזת ריקה ושורות ריקות רצופות.

    ``splitlines()`` היה נותן מספר קטן ב-1 לכל קובץ שנגמר בשורה ריקה, כלומר
    כמעט כל קובץ קוד, ואז אותה תשובה הייתה נושאת שני מספרים סותרים.

    **החיתוך חייב להשתמש באותה חלוקה** (ראו :func:`apply_line_range`):
    ספירה לפי ``split`` עם חיתוך לפי ``splitlines`` הייתה מדווחת על שורה
    אחרונה שקיימת ואז מסרבת להחזיר אותה.

    קובץ ריק הוא ``0`` ולא ``1``, גם זה כדי להתיישר: ``git_mirror_service``
    מגן ב-``if content else 0``, ו-``database/repository.py`` באותה צורה.
    """
    return len(text.split("\n")) if text else 0


def apply_line_range(text: str, start: int, end: int) -> dict[str, Any] | str:
    """חותך ``text`` לטווח ומחזיר את הקטע יחד עם בלוק ה-``range``.

    מחזיר קוד שגיאה כש-``start`` מעבר לסוף הקובץ — שם קיצוץ היה מחזיר קטע
    ריק שנראה כמו תשובה תקינה. ``end`` שחורג כן מקוצץ, ומסומן ב-``truncated``.

    החלוקה זהה לזו של :func:`count_lines`, כדי ש-``total_lines`` ומספר
    המשבצות שאפשר לבקש יהיו אותו מספר.
    """
    all_lines = text.split("\n") if text else []
    total = len(all_lines)
    if start > total:
        return LINE_RANGE_OUT_OF_BOUNDS
    clipped_end = min(end, total)
    return {
        "text": "\n".join(all_lines[start - 1 : clipped_end]),
        "range": {
            "start": start,
            "end": clipped_end,
            "total_lines": total,
            "truncated": clipped_end < end,
        },
    }


def clip_to_bytes(text: str, max_bytes: int) -> str:
    """חותך ``text`` לכל היותר ``max_bytes`` בתים ב-UTF-8, **על גבול תו**.

    ``text.encode("utf-8")[:n]`` לבדו מחזיר רצף בתים פגום כשהגבול נוחת באמצע
    תו רב-בייטי — והוא אינו זורק שם, אלא אצל הצרכן שמנסה לפענח אותו, רחוק
    מהמקום שגרם לזה. הפענוח כאן מיידי, ולכן מה שיוצא הוא תמיד מחרוזת תקינה.

    ``errors="ignore"`` מפיל **רק** את הסיומת החתוכה ולא יותר: הקלט הוא ``str``
    ולכן ה-UTF-8 שנוצר ממנו תקין לכל אורכו, והחלק הלא-תקין היחיד שיכול להיווצר
    מחיתוך הוא רצף חלקי בזנב.
    """
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    return encoded[:max_bytes].decode("utf-8", errors="ignore")


def file_query_error(query: Any) -> str | None:
    """מחזיר את **קוד השגיאה** של ``query``, או ``None`` כשהיא שמישה.

    הכיוון הזה נאמר במפורש כי הוא הפוך לאינטואיציה: ערך אמיתי פירושו סירוב,
    ו-``None`` פירושו שהכול תקין. הקורא כותב ``if err:`` ולא ``if not err:``.

    ``isinstance`` ולא הסתמכות על הסכימה: מול ``pydantic 2.12.3`` הטיפוס
    ``str | None`` אכן דוחה ``int``/``float``/``bool``/``list``/``dict``
    (נמדד), אבל זו רשת נוספת לקוראים שאינם עוברים דרך הסכימה — בדיוק כמו
    הבדיקה המקבילה ב-:func:`normalize_line_range`.

    **מחרוזת ריקה או רווחים בלבד נדחות, ולא נקראות כ"בלי פרמטר".** ``query``
    ריק מתאים לכל מיקום בקובץ ואינו מבקש דבר; קריאתו כהיעדר הייתה מחזירה את
    הקובץ המלא לקורא שביקש מופעים — כלומר תשובה תקינה שאין בה שום סימן שמה
    שביקש לא קרה.

    **מה שנבדק הוא ``strip()``, ומה שמחפשים הוא המקור.** ‏``query`` אינו מקוצץ
    לפני החיפוש: חיפוש של הזחה (``"    return"``) הוא שימוש אמיתי, וקיצוץ היה
    משנה בשקט את מה שהקורא ביקש. זו סטייה מכוונת מ-``codekeeper_search_repo``,
    שכן מקצץ.

    **שאילתה רב-שורתית נדחית כ-**\\ ``query_multiline``. ההתאמה ב-
    :func:`scan_file_query` נעשית שורה אחר שורה, ולכן מחרוזת שיש בה
    ``\\n`` אינה יכולה להתאים לעולם — ואפס מופעים הוא **הצלחה** מוצהרת.
    צירוף שתי ההחלטות האלה מייצר "לא נמצא" על ביטוי שכן נמצא בקובץ, וזה
    בדיוק מה שסוכן מייצר כשהוא מדביק קטע מקובץ שקרא לפני רגע. נבחרה דחייה
    ולא תמיכה, כי צורת התשובה עצמה עוגנת-שורה.
    """
    if not isinstance(query, str):
        return QUERY_INVALID
    if not query.strip():
        return QUERY_TOO_SHORT
    if "\n" in query:
        return QUERY_MULTILINE
    return None


def file_section_error(section: Any) -> str | None:
    """קוד השגיאה של ``section`` עצמו, או ``None`` כשהוא שמיש.

    אותו כיוון כמו :func:`file_query_error`, ומאותה סיבה ``isinstance`` ולא
    הסתמכות על הסכימה — רשת לקורא שאינו עובר דרכה. ו-``section`` ריק או רווחים
    בלבד נדחה, ולא נקרא כ"בלי ``section``": ראו ``SECTION_EMPTY``.

    **מה שאינו כאן: תקרת האורך.** היא נבדקת בפונקציה המשותפת שעונה על הסעיף
    (``mcp_server/docs_handlers.py``), כדי ש-``codekeeper_docs_get_section``,
    ``codekeeper_read_batch`` וכלי הקבצים יקבלו אותה ממקום אחד.

    **ולכן "ריק" נבדק רק עד התקרה — קודם אורך, אחר כך תוכן** (#3472, SUGG-001). זה
    הכלל המתועד של הבדיקה המשותפת ("המבחן הוא האורך, לא התוכן"), וב-
    ``codekeeper_docs_get_section`` ``section`` של רווחים ארוך מהתקרה הוא
    ``section_too_long``. עד #3472 הבדיקה כאן קדמה לה, ואותו קלט קיבל כאן
    ``empty_section`` — שני כלים שחולקים את אותה פונקציית מענה, ושתי שגיאות לאותו
    קלט. עכשיו רווחים שארוכים מהתקרה עוברים הלאה, ונדחים שם, כמו כל ``section``
    ארוך: ``section_too_long``, עם המטא-דאטה של הקובץ. רווחים קצרים — ``empty_section``
    כמו קודם, וזה ההבדל המכוון מכלי התיעוד (שם הם מפת הכותרות).

    ``MAX_SECTION_CHARS`` מיובא **בתוך הפונקציה**: ``docs_handlers`` מייבא את ``_clamp``
    מהמודול הזה, וייבוא ברמת המודול היה מעגלי. עותק שני של התקרה כאן — הדרך שבה
    הפתרון בקבועי ``QUERY_*`` — היה עוד מספר שצריך לזכור לסנכרן; התקרה נחוצה כאן רק
    בזמן ריצה, ורק על ``section`` של רווחים, ולכן ייבוא בזמן הקריאה פוטר מהעותק.
    """
    if not isinstance(section, str):
        return SECTION_INVALID
    if not section.strip():
        from .docs_handlers import MAX_SECTION_CHARS

        if len(section) <= MAX_SECTION_CHARS:
            return SECTION_EMPTY
    return None


def file_read_request_error(
    *,
    query: Any,
    lines: Any,
    context_lines: Any,
    max_results: Any,
    section: Any = None,
    toc: Any = False,
    max_chars: Any = None,
    offset: Any = None,
) -> str | None:
    """קוד השגיאה של **צורת הבקשה** של ``codekeeper_get_file``, או ``None`` אם היא תקינה.

    כל הסירובים של צורת הבקשה — ``query``, ``lines``, ``section`` ו-``toc`` —
    במקום אחד, כדי שיהיה להם בעל בית יחיד ולא שני עותקים שיכולים להיפרד.
    שתי השכבות קוראות לה: ``get_file`` כאן, ו-:meth:`ProductionBackend.get_file`
    בראש המתודה — כך שגם קורא שאינו עובר דרך שכבת ה-handlers מקבל סירוב ולא
    התעלמות שקטה מאחד הפרמטרים. (עד PR ג של "קריאה לפי סעיף" היא נקראה
    ``file_query_request_error``, כשהיא כיסתה רק את משפחת ``query``.)

    **הבדיקה הזו קודמת לשאלה איזה קובץ התבקש**, ובכוונה. בקשה פגומה פגומה
    בלי קשר לקובץ שהיא נוקבת בו, וקריאה בלי ``file_name`` ובלי ``file_id``
    מחזירה ``{"found": false}`` — תשובה על **קובץ**. מי שגם שכח לנקוב בקובץ
    וגם העביר ``query`` יחד עם ``lines`` היה מקבל "הקובץ אינו קיים" על קריאה
    שלא נקבה בשום קובץ, והולך לחפש קובץ במקום לתקן את הקריאה.

    **הסדר, והוא אינו שרירותי:** זוגות מצבים שאינם מצטברים
    (``_EXCLUSIVE_READ_MODES``), ואחריהם פרמטרים שבאו בלי המצב שלהם, ורק בסוף
    הערך של כל מצב. זה הסדר שהיה כאן למשפחת ``query`` לפני שהמצבים האחרים
    נוספו — ``query`` ריק יחד עם ``lines`` הוא ``query_and_lines`` ולא
    ``query_too_short`` — ולכן אף בקשה שנשלחה לפני התוספת אינה מקבלת תשובה
    אחרת. ``toc`` שאינו ``bool`` נדחה לפני כולם, כי בלעדיו אין איך לדעת אם
    המצב התבקש.

    **מה שאינו כאן:** אימות ``lines`` לבדו. ``range_out_of_bounds`` נגזר
    מאורך הקובץ, כלומר דורש את המסמך, ופיצול אימות הטווח לשתי נקודות היה
    גרוע משאיפתו למקום אחד. הוא נשאר ב-:func:`apply_line_range`. וגם מה
    שנגזר מהקובץ עצמו — ``not_markdown``, ``too_large_for_sections`` וסירובי
    הפרסר — נבדק ב-backend אחרי הקריאה.
    """
    if not isinstance(toc, bool):
        return TOC_INVALID
    # "התבקש" נגזר מ-``FILE_READ_MODES``, כמו הזוגות: דגל — כשהוא אמת, כל השאר — כשנשלח.
    # מצב שיתווסף שם בלי ערך כאן נופל ב-``KeyError`` בכל קריאה, ולא נבלע.
    sent = {"toc": toc, "section": section, "query": query, "lines": lines}
    requested = {
        mode.param: (sent[mode.param] is True) if mode.flag else (sent[mode.param] is not None)
        for mode in FILE_READ_MODES
    }
    for first, second, code in _EXCLUSIVE_READ_MODES:
        if requested[first] and requested[second]:
            return code

    if query is None:
        # ``context_lines`` ו-``max_results`` מתארים **איך להציג מופעים**,
        # ובלי ``query`` אין מופעים. ``None`` פירושו "לא נשלח": ההצמדה
        # ב-:func:`get_file` מדלגת עליו במכוון כדי שההבחנה תשרוד עד לכאן.
        if context_lines is not None:
            return CONTEXT_LINES_WITHOUT_QUERY
        if max_results is not None:
            return MAX_RESULTS_WITHOUT_QUERY
    if section is None:
        # אותו היגיון בדיוק ל-``max_chars`` ול-``offset``: הם מעמדים סעיף.
        if max_chars is not None:
            return MAX_CHARS_WITHOUT_SECTION
        if offset is not None:
            return OFFSET_WITHOUT_SECTION

    if query is not None:
        return file_query_error(query)
    if section is not None:
        return file_section_error(section)
    return None


def file_read_refusal(code: str) -> dict[str, Any]:
    """תשובת הסירוב על קוד שהחזירה :func:`file_read_request_error` — אותה צורה בשתי השכבות.

    ``{"ok": False, "error": code}``, ועם ``hint`` רק כשיש לקורא צעד ברור אחד
    (``_REQUEST_ERROR_HINTS``). פונקציה אחת ולא שני מילונים שנבנים ביד, כדי
    שההפניה לא תופיע בשכבה אחת ותיעדר בשנייה.
    """
    refusal: dict[str, Any] = {"ok": False, "error": code}
    hint = _REQUEST_ERROR_HINTS.get(code)
    if hint:
        refusal["hint"] = hint
    return refusal


def scan_file_query(
    text: str,
    query: str,
    *,
    max_results: int,
    context_lines: int,
    byte_budget: int,
) -> dict[str, Any]:
    """מוצא את השורות שבהן ``query`` מופיע, בצורת התשובה של ``search_repo``.

    מחזיר ``{"count", "total", "results", "truncated"}`` — אותם שמות שדות, ולכל
    פגיעה ``line`` ו-``snippet``, ועם ``context_lines`` גם ``context_before``
    ו-``context_after``. ``total`` הוא כל המופעים בקובץ ו-``count`` הוא כמה
    מהם הוחזרו בפועל — אותה משמעות בדיוק כמו שם. כש-``truncated`` דלוק מצטרף
    ``truncation_reason``: :data:`MAX_RESULTS_REASON` כשהתקרה שביקשו עצרה, ו-
    ``byte_budget`` כשהתקציב עצר לפניה — אותו כלל של החיפוש בריפו.

    **``byte_budget`` הוא המקום לרשומות בלבד**, כפי שהן יושבות ברשימה בראש
    התשובה (``list_item_cost``). את המעטפת — הקובץ, השאילתה, המונים והדגלים —
    הקורא בונה ומודד, ומוריד מהתקציב לפני שהוא קורא לכאן
    (``backend._apply_query_to_file``). עד #3474 נמדדו כאן רשומות דחוסות מול
    התקציב כולו, והתשובה שנשלחה עברה אותו.

    **ומה שאינו זהה, כדי שלא יוסק מהשורה שמעל:** כאן ``total`` קיים תמיד,
    כי סריקת קובץ בודד מסתיימת תמיד. ב-``codekeeper_search_repo`` הסריקה
    היא על ריפו שלם, ולכן יש לה תקרת ספירה ו-timeout — וכשהספירה נקטעת
    חוזר שם ``total_at_least`` במקום ``total``, עם סיבה משלה. ``total_at_least``
    אינו קיים כאן, ואין לו מה לתאר. חסר כאן גם ``path``, כי מדובר בקובץ אחד.

    **הנחת כניסה:** ``query`` עבר את :func:`file_query_error`. השער יושב בקורא,
    לפני הקריאה למסד, כדי ששאילתה פסולה לא תשלם קריאת מסמך שלם.

    **סריקת מחרוזת, לא רג'קס ולא stemming.** כאן תו מיוחד הוא תו, ותו לא —
    וזה גם החוזה של ``codekeeper_search_repo``, שמתאים מילולית כברירת מחדל
    ועובר ל-``-E`` רק כש-``regex=true`` נמסר במפורש. מה שנשאר שונה הוא
    ``codekeeper_search_code``, שהוא ``$text`` של מונגו ומתאים למילים שלמות.

    **ההתאמה אינה רגישה לרישיות**, כמו ב-``codekeeper_search_repo`` שמריץ
    ``git grep -i``. ‏``casefold`` ולא ``lower``, אותה בחירה כמו ``symbol=``
    באאוטליין. ‏``casefold`` יכול לשנות אורך (``ß`` ← ``ss``), וזה לא משנה
    כאן: מה שנבדק הוא הכלה בשורה, ואין שימוש במיקום שהוא מחזיר.

    **הפיצול לשורות זהה ל-**\\ :func:`count_lines` **ול-**\\
    :func:`apply_line_range` — ``split("\\n")``. זה מה שמבטיח שכל ``line``
    שחוזר מכאן הוא שורה שאפשר באמת לבקש ב-``lines=[line, line]``; פיצול אחר
    היה מייצר מפה שמצביעה לשומקום.
    """
    lines = text.split("\n") if text else []
    needle = query.casefold()
    hits = [i for i, line in enumerate(lines) if needle in line.casefold()]
    total = len(hits)

    results: list[dict[str, Any]] = []
    used = 0
    stopped_by_budget = False
    # חריגה מתקרת המופעים היא התנהגות מוצהרת ולא חיתוך שקט: ``truncated``
    # נדלק לפני הלולאה, כי הוא נגזר מ-``total`` ולא ממה שהספיק להיכנס.
    truncated = total > max_results
    for idx in hits[:max_results]:
        row: dict[str, Any] = {
            "line": idx + 1,
            "snippet": _snippet(lines[idx]),
        }
        # שני המפתחות מתווספים אך ורק כשביקשו הקשר, בדיוק כמו ב-
        # ``repo_backend.search`` — תשובה בלי ``context_lines`` נושאת את אותם
        # מפתחות בשני הכלים.
        if context_lines > 0:
            row["context_before"] = [_snippet(x) for x in lines[max(0, idx - context_lines) : idx]]
            row["context_after"] = [_snippet(x) for x in lines[idx + 1 : idx + 1 + context_lines]]
        # נמדד כפי שהרשומה יושבת בתשובה שנשלחת — ``list_item_cost``, עם ההזחה
        # והפסיק שלפניה — ולא ב-``json.dumps`` הדחוס. המדידה הדחוסה החטיאה את
        # ההזחה של כל שורה פנימית ברשומה, ותשובה שנמדדה בתוך התקציב יצאה
        # גדולה ממנו (#3474).
        used += list_item_cost(row)
        if used > byte_budget:
            truncated = True
            stopped_by_budget = True
            break
        results.append(row)

    answer: dict[str, Any] = {
        "count": len(results),
        "total": total,
        "results": results,
        "truncated": truncated,
    }
    # הסיבה רק כשמשהו באמת נחתך, ותמיד כשכן — אותו כלל של ``codekeeper_search_repo``.
    if truncated:
        answer["truncation_reason"] = (
            BYTE_BUDGET_REASON if stopped_by_budget else MAX_RESULTS_REASON
        )
    return answer


def _snippet(line: str) -> str:
    """שורה אחת כפי שהיא נכנסת לתשובה: מקוצצת ברווחים, ואז חסומה בבתים.

    ``strip()`` הוא מה ש-``codekeeper_search_repo`` עושה לכל שורה שהוא מחזיר
    (``git_mirror_service``), והטקסט המלא של השורה זמין ממילא ב-``lines=``.
    """
    return clip_to_bytes(line.strip(), QUERY_SNIPPET_MAX_BYTES)


def _clamp(value: Any, lo: int, hi: int, default: int) -> int:
    try:
        ivalue = int(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, ivalue))


def list_files(backend: Any, user_id: int, *, page: int = 1, per_page: int = 50) -> dict[str, Any]:
    return backend.list_files(
        user_id,
        page=_clamp(page, 1, 10**9, 1),
        per_page=_clamp(per_page, 1, MAX_PER_PAGE, 50),
    )


def search_code(
    backend: Any, user_id: int, *, query: str, language: str | None = None, limit: int = 20
) -> list[dict[str, Any]]:
    query = (query or "").strip()
    if not query:
        return []
    return backend.search_code(
        user_id,
        query=query,
        language=(language or None),
        limit=_clamp(limit, 1, MAX_SEARCH_LIMIT, 20),
    )


def get_file(
    backend: Any,
    user_id: int,
    *,
    file_name: str | None = None,
    file_id: str | None = None,
    version: int | None = None,
    lines: Any = None,
    query: Any = None,
    context_lines: Any = None,
    max_results: Any = None,
    section: Any = None,
    toc: Any = False,
    max_chars: Any = None,
    offset: Any = None,
) -> dict[str, Any] | None:
    # **צורת הבקשה נבדקת לפני השאלה איזה קובץ התבקש.** ראו
    # :func:`file_read_request_error` — שם גם הנימוק, וגם מה שאינו שם.
    # אותה פונקציה בדיוק נקראת שוב בראש ``ProductionBackend.get_file``,
    # כדי שקורא שאינו עובר דרך כאן יקבל את אותו סירוב; היא טהורה, ולכן
    # הקריאה הכפולה עולה השוואה אחת ולא נגיעה במסד.
    request_error = file_read_request_error(
        query=query,
        lines=lines,
        context_lines=context_lines,
        max_results=max_results,
        section=section,
        toc=toc,
        max_chars=max_chars,
        offset=offset,
    )
    if request_error:
        return file_read_refusal(request_error)
    if not file_name and not file_id:
        return None
    # ההצמדה יושבת כאן ולא ב-backend, כמו כל שאר ההצמדות בשכבה הזו: ערך מחוץ
    # לטווח נצמד ואינו מכשיל את הקריאה.
    #
    # **``None`` עובר כמות שהוא ואינו נצמד ל-0 או ל-50.** זה מה שמבדיל "לא
    # נשלח" מ"נשלח בדיוק הערך הזה", והסירוב ב-backend על ``context_lines``
    # או ``max_results`` בלי ``query`` נשען על ההבחנה הזו. הצמדה של ערך חסר
    # לברירת מחדל הייתה מוחקת אותה כאן, שורה אחת לפני מי שצריך אותה.
    return backend.get_file(
        user_id,
        file_name=file_name,
        file_id=file_id,
        version=version,
        lines=lines,
        query=query,
        context_lines=(
            None if context_lines is None else _clamp(context_lines, 0, QUERY_CONTEXT_LINES_MAX, 0)
        ),
        max_results=(
            None
            if max_results is None
            else _clamp(max_results, 1, QUERY_RESULTS_MAX, QUERY_RESULTS_DEFAULT)
        ),
        # ``max_chars`` ו-``offset`` עוברים **כמות שהם**, ובלי הצמדה כאן. הם נצמדים
        # בפונקציה שעונה על הסעיף — ``docs_handlers.answer_section``, אותה אחת ש-
        # ``codekeeper_docs_get_section`` עובר בה — והצמדה שנייה כאן הייתה עותק של
        # אותם גבולות. ``None`` נשמר מאותה סיבה כמו ``context_lines``.
        section=section,
        toc=toc,
        max_chars=max_chars,
        offset=offset,
    )


def list_versions(backend: Any, user_id: int, *, file_name: str) -> list[dict[str, Any]]:
    if not file_name:
        return []
    return backend.list_versions(user_id, file_name=file_name)


def list_collections(backend: Any, user_id: int, *, limit: int = 100) -> dict[str, Any]:
    return backend.list_collections(user_id, limit=_clamp(limit, 1, MAX_COLLECTIONS_LIMIT, 100))


def get_collection(backend: Any, user_id: int, *, collection_id: str) -> dict[str, Any]:
    if not collection_id:
        return {"ok": False, "error": "missing_collection_id"}
    return backend.get_collection(user_id, collection_id=collection_id)


def get_collection_items(
    backend: Any,
    user_id: int,
    *,
    collection_id: str,
    page: int = 1,
    per_page: int = 50,
    folder: str | None = None,
) -> dict[str, Any]:
    if not collection_id:
        return {"ok": False, "error": "missing_collection_id"}
    return backend.get_collection_items(
        user_id,
        collection_id=collection_id,
        page=_clamp(page, 1, 10**9, 1),
        per_page=_clamp(per_page, 1, MAX_PER_PAGE, 50),
        folder=folder,
    )


def max_code_size() -> int:
    """The app's per-file size gate (characters, not bytes), with a safe fallback.

    Public, because ``mcp_server/app.py`` derives the request-body cap from it
    (``limits.request_bytes_for``): one lookup of ``MAX_CODE_SIZE`` serves both
    gates, so the two cannot drift apart.
    """
    try:
        from config import config as _cfg

        return int(getattr(_cfg, "MAX_CODE_SIZE", DEFAULT_MAX_CODE_SIZE))
    except Exception:
        return DEFAULT_MAX_CODE_SIZE


# ---------------------------------------------------------------------------
# ``upload_id`` — תוכן שעלה ב-``PUT /api/agent/upload`` (``mcp_server/uploads.py``)
# במקום לעבור inline דרך המודל.
#
# **הסדר בגוף הכלי:** שם הקובץ ← בדיוק אחד מהשניים (התוכן או ``upload_id``) ←
# צורת המזהה ← **שליפה ובדיקת שלמות**, שאינן צורכות (העלאה משובשת מושלכת כאן,
# ונענית ``upload_corrupted``) ← המסלול הקיים כמו שהוא על הטקסט (תוכן ריק, התקרה,
# זיהוי שפה, ``file_exists``) ← **מחיקה, והיא השער** ← ורק אז השמירה.
#
# **המחיקה היא השער לחד-פעמיות.** ``delete_one`` אטומי, ולכן משתי צריכות של
# אותו מזהה — גם מקבילות, גם מחוץ לתור הכתיבה — רק אחת שומרת. ומכיוון שהשער בא
# אחרי כל הבדיקות, ``file_exists`` ו-``existence_check_unavailable`` אינם שורפים
# את ההעלאה. **המחיר**, בכוונה: כשל של השמירה עצמה אחרי המחיקה שורף אותה, והתשובה
# אומרת זאת (``upload_consumed``). החלופה — למחוק אחרי שמירה — משאירה העלאה חיה
# אחרי שמירה שהצליחה, ו-``append_file`` שנשלח שוב כי התשובה אבדה בדרך היה מוסיף
# את התוכן פעמיים, בשקט.
# ---------------------------------------------------------------------------


def _both_sent(param: str) -> dict[str, Any]:
    return {
        "ok": False,
        "error": f"{param}_and_upload_id",
        "hint": f"pass either the {param} parameter or upload_id, not both",
    }


def _invalid_upload_id(upload_id: Any) -> dict[str, Any] | None:
    """סירוב על ``upload_id`` שאינו בצורת מזהה — או ``None``. בלי להדהד את הערך."""
    if is_upload_id(upload_id):
        return None
    return {
        "ok": False,
        "error": "invalid_upload_id",
        "hint": "pass upload_id exactly as PUT /api/agent/upload returned it",
    }


def _upload_not_found() -> dict[str, Any]:
    """תשובה אחת לפגה, לנצרכה ולשל משתמש אחר — בלי לגלות איזו (כמו ``get_note``)."""
    return {
        "ok": False,
        "error": "upload_not_found",
        "hint": (
            "no pending upload with this id: an upload lasts "
            f"{UPLOAD_TTL_SECONDS // 60} minutes and the first save that uses it uses it up. "
            "Nothing was written. Upload the file again, or send the content inline."
        ),
    }


def _upload_storage_unavailable() -> dict[str, Any]:
    """אחסון ההעלאות לא ענה. אותה מילה של הראוט (503), כי זה אותו מצב."""
    return {
        "ok": False,
        "error": "upload_storage_unavailable",
        "hint": (
            "the upload storage did not answer; nothing was written. Retry in a minute — "
            "if it answers upload_not_found, upload the file again — or send the content inline."
        ),
    }


def _upload_corrupted() -> dict[str, Any]:
    """הטקסט שנשלף אינו מה שהגיע, ולכן לא נכתב כלום — ההחלטה של :func:`_load_upload`.

    ה-hint אינו טוען שההעלאה נמחקה: המחיקה היא ניקיון שתוצאתו לא תמיד ידועה
    (``ProductionBackend.discard_upload``), ומה שהסוכן צריך הוא מה שכן ודאי.
    """
    return {
        "ok": False,
        "error": "upload_corrupted",
        "hint": (
            "the stored upload does not match the hash taken when it arrived, so it was not "
            "used and nothing was written: upload the file again."
        ),
    }


class _PendingUpload(NamedTuple):
    """העלאה שנשלפה **ונבדקה** ועוד לא נצרכה — מה ש-:func:`_load_upload` מחזיר כשאין סירוב.

    נבנית רק שם, ורק אחרי שה-hash של ``text`` הושווה ל-hash שנשמר כשההעלאה הגיעה.
    לכן כל מה שבא אחריה בגוף הכלי — התקרה, ``file_exists``, ``conflict``, השער —
    רואה טקסט שכבר אומת. ``test_every_upload_is_checked_as_it_is_read_and_consumed_at_one_gate``
    מקבע שאין מקום אחר שבונה אותה.
    """

    upload_id: str
    text: str
    size_bytes: int


def _load_upload(
    backend: Any, user_id: int, upload_id: Any, *, tool: str
) -> _PendingUpload | dict[str, Any]:
    """ההעלאה, או הסירוב שיש להחזיר — לעולם לא שניהם. בודקת צורה, שולפת ומוודאת שלמות — **אינה צורכת**.

    שני טיפוסים שונים ולא זוג ``(העלאה, סירוב)``: הקורא מבחין ביניהם ב-``isinstance``,
    ולכן אין מצב שבו שניהם ``None`` או ששניהם קיימים.

    **השלמות נבדקת כאן, ברגע שהטקסט חוזר מהאחסון — לפני כל החלטה שנשענת עליו.**
    ``content_changed`` משווה את הטקסט שנשלף למה שנכתב, ולכן אינו רואה טקסט שהשתבש
    באחסון הזמני: שניהם כבר משובשים. כאן ה-hash של מה שנשלף מושווה לזה שחושב
    כשההעלאה הגיעה (:func:`_upload_integrity_problem`). הבדיקה הייתה קודם רק לפני
    המחיקה, אחרי השערים של הכלי, ושם טקסט משובש קיבל מהם תשובה על טקסט שלא נשלח
    (``code_too_large`` על אורך שאינו של ההעלאה, ``file_exists``, ``conflict``),
    וההעלאה נשארה חיה, בלי שורת לוג, עד שפקעה.

    **זה לא TOCTOU:** הבדיקה והשימוש הם על אותו עותק בזיכרון — מה שנשמר לבסוף הוא
    ``text`` שנבדק כאן — והשער (:func:`_consume_upload`) מכריע רק שההעלאה נצרכת
    פעם אחת, לא איזה טקסט נכתב.

    העלאה שאינה תואמת מושלכת (``discard_upload`` — ניקיון, לא השער), והתשובה
    ``upload_corrupted`` — בלי קשר למה שהמחיקה עשתה: העלאה משובשת נשארת משובשת גם
    אם צורך מקביל מחק אותה בינתיים, וגם אם האחסון לא ענה והיא תפקע ב-TTL. ``tool``
    הוא לשורת ה-``ERROR`` שלה.
    """
    bad = _invalid_upload_id(upload_id)
    if bad is not None:
        return bad
    try:
        found = backend.find_upload(user_id, upload_id)
    except UploadStorageUnavailable:
        return _upload_storage_unavailable()
    if found is None:
        return _upload_not_found()
    text = found["text"]
    size_bytes = found["bytes"]
    problem = _upload_integrity_problem(text, found["content_sha256"])
    if problem is not None:
        backend.discard_upload(
            user_id, upload_id, tool=tool, reason=problem, size_bytes=size_bytes, chars=len(text)
        )
        return _upload_corrupted()
    return _PendingUpload(upload_id=upload_id, text=text, size_bytes=size_bytes)


def _upload_integrity_problem(text: str, stored_sha256: object) -> str | None:
    """למה ``text`` שנשלף אינו מה שהגיע — או ``None`` כשהוא כן.

    ``stored_sha256`` — מה שנשמר עם ההעלאה כשהגיעה, **כמו שנקרא מהמסד ובלי בדיקה**:
    שם יכול לשבת כל דבר. הוא חושב בראוט על הטקסט שהגיע
    (``ProductionBackend.create_upload``), באותה פונקציה שמחשבת כאן,
    ``_content_sha256`` — ההגדרה של ``file.content_sha256``.
    ``"stored_hash_invalid"``: מה שנשמר אינו 64 ספרות הקס, ולכן אין מול מה לבדוק.
    ``"hash_mismatch"``: הטקסט שנשלף שונה ממה שהגיע. **ההשוואה מדויקת**, בלי רישיות:
    הערך נכתב רק ב-``create_upload``, מ-``hexdigest`` — כלומר תמיד באותיות קטנות — ומה
    שנשמר בצורה אחרת לא נכתב שם.
    """
    # ``backend`` מייבא את המודול הזה ברמה העליונה, ולכן הייבוא ההפוך בתוך הפונקציה —
    # כמו ``_file_meta`` למטה.
    from .backend import _content_sha256

    if not (isinstance(stored_sha256, str) and _SHA256_HEX.fullmatch(stored_sha256)):
        return "stored_hash_invalid"
    if stored_sha256 != _content_sha256(text):
        return "hash_mismatch"
    return None


def _consume_upload(
    backend: Any, user_id: int, upload: _PendingUpload, *, tool: str
) -> dict[str, Any] | None:
    """השער: ``None`` כשההעלאה נצרכה עכשיו, בקריאה הזו — אחרת הסירוב, ולא שומרים.

    הטקסט כבר אומת ב-:func:`_load_upload`, ו-:class:`_PendingUpload` נבנית רק שם.
    ``False`` מהמחיקה פירושו שמישהו צרך אותה בין השליפה לכאן, או שפקעה בינתיים.

    **זו הדרך היחידה לצרוך העלאה**, וכל כלי שמקבל ``upload_id`` עובר בה:
    ``test_every_upload_is_checked_as_it_is_read_and_consumed_at_one_gate`` מקבע.
    """
    try:
        consumed = backend.consume_upload(
            user_id, upload.upload_id, tool=tool, size_bytes=upload.size_bytes, chars=len(upload.text)
        )
    except UploadStorageUnavailable:
        return _upload_storage_unavailable()
    return None if consumed else _upload_not_found()


def _upload_used_up(res: dict[str, Any]) -> dict[str, Any]:
    """תשובת שמירה שנכשלה **אחרי** שהשער עבר: ההעלאה נשרפה, והתשובה אומרת זאת."""
    note = "this attempt used up the upload: upload the file again before you retry"
    hint = res.get("hint")
    return {
        **res,
        "upload_consumed": True,
        "hint": f"{hint}; {note}" if isinstance(hint, str) and hint else note,
    }


def _over_the_description_ceiling(refusal: dict[str, int]) -> str:
    """החצי המשותף של שתי ההודעות על תיאור ארוך מהתקרה — המספרים והיחידה.

    משפט אחד לשני הערוצים (הסימון של ``codekeeper_save_file`` והסירוב של
    ``codekeeper_update_file_description``), כי "תווים, לא בתים" הוא בדיוק מה שהיה חסר
    בסירוב עד #3489: סוכן עם 413 תווים עבריים (625 בתים) לא ידע מ-``max`` לבדו אם
    הטקסט המקוצר שלו נכנס. המספרים — מהמילון שהחזירה ``description_length_error``.
    את נושא המשפט ("the description is", "which is") מוסיף מי שקורא לפונקציה,
    כי כל הודעה פותחת אחרת.
    """
    return (
        f"{refusal['actual_chars']:,} characters, over the "
        f"{refusal['max_chars']:,}-character ceiling (characters, not bytes)"
    )


def _description_not_saved(refusal: dict[str, int]) -> dict[str, Any]:
    """מה ש-``codekeeper_save_file`` מוסיף כשהתיאור ארוך מהתקרה: הקובץ נשמר, התיאור לא.

    **סימון ולא סירוב**, באותה תבנית של ``content_changed``: הכתיבה קרתה, ו-``ok:
    false`` היה שולח את הסוכן לשלוח שוב את כל התוכן — עד ``MAX_CODE_SIZE`` תווים —
    בגלל מטא-דאטה, ולהתנגש ב-``file_exists`` על הקובץ שכבר נשמר. ולכן גם ההפניה היא
    לכלי שמעדכן תיאור בלבד, ולא לשמירה חוזרת.

    ``max_chars`` ו-``actual_chars`` מהפונקציה המשותפת, באותם שמות של הסירוב של
    ``codekeeper_update_file_description`` — ערוץ אחד לא אמור לדבר אחרת מהשני על
    אותה תקרה.
    """
    return {
        "description_saved": False,
        **refusal,
        "message": "The file was saved without this description, which is "
        + _over_the_description_ceiling(refusal) + ".",
        "hint": (
            f"Shorten it to at most {refusal['max_chars']:,} characters and set it with "
            "codekeeper_update_file_description; the file itself does not need to be saved again."
        ),
    }


def _saved_description(res: dict[str, Any], sent: str) -> dict[str, Any]:
    """``description_saved`` של שמירה שהתיאור שלה **נשלח** לכתיבה — לפי מה שנקרא חזרה.

    **קרא את המצב, אל תהדהד את הבקשה** (``CRITICAL-PATTERNS.md`` K11): ה-backend קרא
    את המסמך שנכתב לפי ה-``_id`` שה-insert החזיר, ו-``file.description`` הוא מה
    שנשמר בפועל. ``content_changed: null`` הוא הסימן שהקריאה החוזרת לא הצליחה
    (``ProductionBackend.save_file``) — ואז גם על התיאור אין מה לומר, ו-``null``
    כאן הוא אותו "לא ידוע", ולא ``true`` שנגזר מהבקשה. ``false`` כאן — בלי שדות
    התקרה — פירושו שמה שנקרא חזרה אינו מה שנשלח: עדכון תיאור מקביל שנחת בין
    הכתיבה לקריאה, או שכבה בדרך שמשנה אותו; ``file.description`` אומר מה כן נשמר.
    """
    if res.get("content_changed") is None:
        return {"description_saved": None}
    stored = (res.get("file") or {}).get("description")
    return {"description_saved": stored == sent}


def save_file(
    backend: Any,
    user_id: int,
    *,
    file_name: str,
    code: str = "",
    language: str | None = None,
    description: str = "",
    upload_id: str | None = None,
) -> dict[str, Any]:
    """Validate + normalize a save request, then delegate to the backend.

    All app imports are lazy/guarded so this module stays trivially importable
    (and unit-testable) without the config/services stack.

    ``upload_id`` — התוכן מהעלאה במקום ``code``; הסדר והשער — בהערה שמעל
    :func:`_both_sent`. התוכן עובר את **אותו** מסלול בדיוק: שום מסלול מקביל.

    **תקרת התיאור (#3489).** תיאור ארוך מ-``FILE_DESCRIPTION_MAX_CHARS`` תווים אינו
    נשמר, והקובץ כן: התשובה נושאת ``description_saved: false`` עם ``max_chars``,
    ``actual_chars``, ``message`` ו-``hint`` (:func:`_description_not_saved`). תיאור
    שנשלח לכתיבה נושא ``description_saved`` לפי מה שנקרא חזרה (:func:`_saved_description`).
    בלי תיאור — אין שדה, כי אין על מה לדווח. **ואין כאן תיאור קודם להשוות אליו**, כי
    הכלי יוצר קובץ חדש בלבד — שם תפוס נדחה ב-``file_exists`` עוד לפני שמגיעים לכאן.
    בשמירה מקבילה שעוקפת את הבדיקה (ראו "החסימה היא מעקה" למטה) התיאור ייפול גם
    כשהוא זהה לזה של הגרסה שנכתבה באמצע — הכיוון הזהיר, והתשובה אומרת אותו.
    """
    name = (file_name or "").strip()
    if not name:
        return {"ok": False, "error": "missing_file_name"}
    upload: _PendingUpload | None = None
    if upload_id is not None:
        if isinstance(code, str) and code != "":
            return _both_sent("code")
        loaded = _load_upload(backend, user_id, upload_id, tool="codekeeper_save_file")
        if isinstance(loaded, dict):
            return loaded
        upload = loaded
        code = upload.text
    if not isinstance(code, str) or code == "":
        return {
            "ok": False,
            "error": "empty_code",
            "hint": "send the content in the code parameter, or upload the file first and pass upload_id",
        }

    # Reject oversize content (the large-file path is non-versioned; out of scope
    # here). Mirror the app's own gate, which counts characters, not bytes.
    max_size = max_code_size()
    if len(code) > max_size:
        return {"ok": False, "error": "code_too_large", "max": max_size}

    # Auto-detect the language when the caller didn't specify one.
    lang = (language or "").strip()
    if not lang:
        try:
            from services.code_service import detect_language

            lang = detect_language(code, name) or "text"
        except Exception:
            lang = "text"

    # שמירה על שם שכבר קיים נחסמת, ובכוונה. היא הייתה יוצרת גרסה חדשה,
    # והתוכן הקודם היה נעלם משני המקומות שבהם מחפשים אותו: החיפוש מקבץ
    # לגרסה האחרונה לכל שם קובץ, וגם עמוד הקובץ מציג אותה בלבד. כלומר
    # קובץ ותיק שבמקרה חולק שם עם מה שנשמר עכשיו הופך לבלתי נגיש —
    # אובדן שקט, בלי שהכותב יודע שדרס משהו.
    #
    # לעריכה של קובץ קיים יש כלים ייעודיים, והם משמרים את ההיסטוריה.
    #
    # **החסימה היא מעקה, לא נעילה.** שתי בקשות מקבילות לאותו שם יכולות
    # שתיהן לראות שאין קובץ ולעבור. אין לכך תיקון אטומי במודל הזה: מסמכים
    # רבים חולקים ``(user_id, file_name)`` בכוונה — זה בדיוק מה שגרסה היא —
    # ולכן אינדקס ייחודי היה שובר את הגרסאות. גם לפני החסימה כל שמירה יצרה
    # גרסה חדשה, כך שתוצאת המרוץ אינה גרועה מהמצב הקודם.
    #
    # **וכשל בבדיקה אינו "אין קובץ".** ``None`` כאן משמעו שלא הצלחנו לברר,
    # והשמירה נחסמת עם קוד נפרד. זה הפוך מההתנהגות הראשונה שנכתבה כאן,
    # ובכוונה: המסלול המתירני מסתיר תוכן קיים בדיוק ברגע שההגנה אמורה
    # לפעול, ובתמורה הוא אינו באמת משאיר את הכלי עובד — שמירה בזמן שהמסד
    # אינו עונה נכשלת ממילא בשכבת ה-DB, שגם היא מסרבת לנחש מספר גרסה.
    try:
        # בדיקת קיום ולא טעינת הקובץ: ``get_file`` מחזיר את המסמך המלא
        # כולל התוכן, וזה מחיר מיותר על שאלת כן/לא בכל שמירה — אבל לא רק
        # מחיר. ``get_file`` בולע כשלים ומחזיר ``None`` גם על "אין קובץ"
        # וגם על "השאילתה נפלה", ולכן הוא **אינו** יכול לשמש כאן אפילו
        # כפולבק: backend שאינו יודע לענות בזול אינו יודע לענות באמינות.
        checker = getattr(backend, "file_exists", None)
        if not callable(checker):
            existing = None
        else:
            answer = checker(user_id, file_name=name)
            existing = None if answer is None else bool(answer)
    except Exception:
        existing = None
    if existing is None:
        return {
            "ok": False,
            "error": "existence_check_unavailable",
            "file_name": name,
            "message": (
                f"לא הצלחתי לברר אם '{name}' כבר קיים, ולכן לא שמרתי. זו "
                "תקלת בירור ולא תשובה — אל תסיקו שהקובץ אינו קיים. נסו שוב "
                "בעוד רגע, או השתמשו ב-codekeeper_edit_file / "
                "codekeeper_append_file אם התכוונתם לערוך קובץ קיים."
            ),
        }
    if existing:
        return {
            "ok": False,
            "error": "file_exists",
            "file_name": name,
            "message": (
                f"הקובץ '{name}' כבר קיים. שמירה עליו הייתה מסתירה את התוכן "
                "הקיים מהחיפוש ומעמוד הקובץ. לעריכה השתמשו ב-"
                "codekeeper_edit_file (החלפת קטע) או ב-codekeeper_append_file "
                "(הוספה בסוף), או שמרו בשם אחר. ואם רק התיאור הוא מה שרציתם "
                "לעדכן — codekeeper_update_file_description עושה זאת בלי "
                "לגעת בתוכן ובלי ליצור גרסה."
            ),
        }

    if upload is not None:
        refusal = _consume_upload(backend, user_id, upload, tool="codekeeper_save_file")
        if refusal is not None:
            return refusal
    # ``strip`` — אותה נורמליזציה של ``codekeeper_update_file_description`` ושל הראוט
    # בוובאפ, והתקרה נמדדת על מה שייכתב, כלומר אחריה. תיאור ארוך מהתקרה אינו
    # עוצר את השמירה: הקובץ נשמר בלי תיאור, והתשובה אומרת זאת (ה-docstring).
    sent_description = (description or "").strip()
    description_refusal = description_length_error(sent_description)
    res = backend.save_file(
        user_id,
        file_name=name,
        code=code,
        programming_language=lang,
        description=sent_description if description_refusal is None else "",
        tool="codekeeper_save_file",
    )
    if upload is not None and not res.get("ok"):
        return _upload_used_up(res)
    # בשמירה שנכשלה אין מה לומר על התיאור — ``ok: false`` כבר אומר ששום דבר לא נשמר.
    if not res.get("ok") or not sent_description:
        return res
    if description_refusal is not None:
        return {**res, **_description_not_saved(description_refusal)}
    return {**res, **_saved_description(res, sent_description)}


def _apply_edit(
    code: str,
    old_string: str,
    new_string: str,
    replace_all: bool,
    *,
    max_size: int,
) -> tuple[str | None, int, str | None]:
    """Pure exact find-and-replace (native Edit-tool semantics).

    Returns ``(new_code, occurrences, error)`` — exactly one of new_code/error
    is set. ``occurrences`` is how many matches were found, so an
    ``ambiguous_match`` error can report the count.

    **``max_size`` נבדק לפני שהתוצאה נבנית, ולא אחריה.** אורך התוצאה ידוע מראש:
    ``str.count`` ו-``str.replace`` סופרים את אותם מופעים שאינם חופפים משמאל
    לימין, ולכן הוא ``len(code) + count * (len(new_string) - len(old_string))``
    בדיוק — וזה גם החשבון שלפיו ``str.replace`` עצמו מקצה את התוצאה (``replace``
    ב-``Objects/unicodeobject.c``, נקרא ב-CPython 3.11.15). בדיקה אחרי ``replace``
    הייתה מגיעה מאוחר מדי: ``replace_all`` על ``"a"`` עם ``new_string`` של אלף
    תווים, בקובץ של מאה אלף ``a``, בונה מחרוזת של מאה מיליון תווים לפני שמישהו
    מודד אותה — בקשה של כמה קילובייטים שמכלה את הזיכרון של תהליך ה-MCP כולו.
    ובבאץ' של ``codekeeper_multi_edit_file`` הזוגות מוחלים זה על תוצאת זה, כך
    שבלי הבדיקה כאן זוג שמחליף את ``"a"`` ב-``"aa"`` כופל את הטקסט בכל שלב.
    ``code_too_large`` כאן הוא אותו קוד ש-:func:`_resave_edited` מחזיר על
    התוצאה הסופית, כי זו אותה תקרה; קורא שהתקרה שלו אחרת מתרגם אותו לקוד שלו.

    **``max_size`` הוא חובה, בלי ברירת מחדל** (#3495). כשהבדיקה נוספה (#3494)
    הוא היה אופציונלי, ו-``None`` פירושו היה "בלי תקרה" — ו-``note_str_replace``
    נשאר הקורא שלא העביר אותו, ובנה את התוצאה לפני שמדד אותה. עכשיו קורא ששכח
    נכשל בקריאה עצמה, ו-mypy מסמן אותו ב-``call-arg`` לפני שהקוד רץ (נמדד ב-1.18.2
    וב-2.4.0) — קוד שהשער של mypy ב-``.github/workflows/ci.yml`` חוסם עליו. כל
    קורא מעביר את התקרה שלו: ``max_code_size()`` בכלי הקבצים, ``MAX_NOTE_CONTENT``
    ב-``note_str_replace``.
    """
    if old_string == "":
        return None, 0, "empty_old_string"
    if old_string == new_string:
        return None, 0, "old_and_new_identical"
    count = code.count(old_string)
    if count == 0:
        return None, 0, "no_match"
    if count > 1 and not replace_all:
        return None, count, "ambiguous_match"
    if len(code) + count * (len(new_string) - len(old_string)) > max_size:
        return None, count, "code_too_large"
    return code.replace(old_string, new_string), count, None


def _load_editable(backend: Any, user_id: int, name: str) -> tuple[dict[str, Any] | None, str]:
    """Fetch the latest version of ``name`` for editing. Returns (doc, code)."""
    doc = backend.get_file(user_id, file_name=name, file_id=None, version=None)
    if not doc:
        return None, ""
    code = doc.get("code")
    return doc, code if isinstance(code, str) else ""


def _resave_edited(
    backend: Any,
    user_id: int,
    *,
    name: str,
    doc: dict[str, Any],
    new_code: str,
    tool: str,
    consume: Callable[[], dict[str, Any] | None] | None = None,
) -> dict[str, Any]:
    """Persist an edited body as a new version, preserving the file's metadata.

    Language, description and tags are carried over from the fetched version so
    an edit never resets them; the same size gate as ``save_file`` applies to
    the resulting body.

    ``new_code`` הוא מה שהכלי **מתכוון** לשמור, וה-backend משווה אליו את מה שנשמר
    בפועל (``content_changed``). ``tool`` הוא שם הכלי בשורת הלוג כשהשניים שונים.

    ``consume`` — שער החד-פעמיות של ``upload_id`` (:func:`_consume_upload`): רץ
    אחרי בדיקת התקרה ולפני השמירה, כך שהעלאה שהתוצאה שלה גדולה מדי אינה נשרפת.
    סירוב שלו חוזר כמו שהוא, ושמירה שנכשלת אחריו אומרת שההעלאה נצרכה.
    """
    max_size = max_code_size()
    if len(new_code) > max_size:
        return {"ok": False, "error": "code_too_large", "max": max_size}
    if consume is not None:
        refusal = consume()
        if refusal is not None:
            return refusal
    res = backend.save_file(
        user_id,
        file_name=name,
        code=new_code,
        programming_language=str(doc.get("programming_language") or doc.get("language") or "text"),
        description=str(doc.get("description") or ""),
        tags=list(doc.get("tags") or []),
        tool=tool,
    )
    if consume is not None and not res.get("ok"):
        return _upload_used_up(res)
    return res


#: מה שתשובת השמירה אומרת על **מה שנשמר**, ועובר כמות שהוא לתשובה של כל כלי
#: עריכה, לצד ``file`` (שנושא את ``content_sha256``).
_SAVE_VERIFICATION_FIELDS = ("content_changed", "content_diff")


def _resaved_answer(res: dict[str, Any], **fields: Any) -> dict[str, Any]:
    """תשובת ההצלחה של כלי העריכה: השדות של הכלי, ``file``, ומה שהשמירה אימתה.

    עוזר אחד לכל הכלים שעוברים ב-:func:`_resave_edited`, כי התשובה שלהם נבנית
    ביד ולא מועברת כמו שהיא: שדה שיתווסף לתשובת השמירה היה מגיע אחרת רק לכלי
    שמישהו זכר לעדכן. מפתח שתשובת השמירה לא החזירה לא מומצא כאן — ``None``
    שמופיע בלי שה-backend אמר אותו היה נקרא "לא הצלחנו לאמת".
    """
    answer: dict[str, Any] = {"ok": True, **fields, "file": res.get("file")}
    for key in _SAVE_VERIFICATION_FIELDS:
        if key in res:
            answer[key] = res[key]
    return answer


# ---------------------------------------------------------------------------
# השער האופטימי של כלי העריכה — ``expected_content_sha256``.
#
# **מה הוא סוגר.** סוכן קורא קובץ (לפעמים בכמה שלבים: מפה, סעיף, טווח), בונה
# עריכה, ושולח אותה. אם בינתיים נכתב הקובץ — סשן אחר, הוובאפ, הבוט — העריכה
# נבנית על בסיס שהסוכן לא ראה, בלי שום סימן. עם הפרמטר, מה שהסוכן ראה מושווה
# לגרסה שהעריכה עומדת להיבנות עליה, לפני שדבר מוחל.
#
# **למה hash ולא ``version``.** ה-hash משתנה בכל כתיבה לתוכן, גם כזו שאינה
# מעלה גרסה: ``check_file_sync`` ב-``database/bookmarks_manager.py`` כותב
# ``code`` במקום (``update_one``). ו-``codekeeper_get_file`` מחזיר אותו בכל מצב
# קריאה — גם ``toc`` ו-``section`` — כך שסוכן שקרא בכמה שלבים מחזיק אותו.
#
# **מה הוא אינו סוגר, במפורש.** גוף הכלי רץ על העובד היחיד של תור הכתיבה
# (``_WRITE_POOL`` ב-``mcp_server/server.py``), ולכן בין כותבי MCP הבדיקה
# והכתיבה אינן משתלבות. כתיבה מהוובאפ או מהבוט — תהליכים אחרים — עדיין יכולה
# לנחות בין הבדיקה ל-``insert``. זה מצמצם את החלון ואינו סוגר אותו; הסגירה
# היא אינדקס ייחודי ועדכון מותנה, הכיוון שמתואר ב-#3391.
# ---------------------------------------------------------------------------

#: הצורה של ``hexdigest()`` של sha256: 64 ספרות הקס. טווחים מפורשים ולא ``\d``,
#: כי ``\d`` על ``str`` תופס גם ספרות שאינן ASCII.
_SHA256_HEX = re.compile(r"[0-9a-fA-F]{64}")


def _invalid_expected_sha256(expected: Any) -> dict[str, Any] | None:
    """סירוב על ``expected_content_sha256`` שאינו בצורת hash — או ``None``.

    **קוד משלו ולא ``conflict``:** שגיאת כתיב הייתה נקראת אחרת כ"הקובץ השתנה",
    והסוכן היה קורא אותו מחדש ושולח שוב את אותו ערך שגוי. נבדק לפני כל קריאה
    מהמסד. ספרות הקס בשתי הרישיות מתקבלות — זה אותו מספר — וההשוואה ב-
    :func:`_changed_since_read` אינה תלויה ברישיות. הערך עצמו אינו מוחזר.
    """
    if expected is None:
        return None
    if isinstance(expected, str) and _SHA256_HEX.fullmatch(expected):
        return None
    return {
        "ok": False,
        "error": "invalid_expected_content_sha256",
        "hint": "pass file.content_sha256 exactly as codekeeper_get_file returned it: 64 hex "
        "digits",
    }


def _changed_since_read(doc: dict[str, Any], expected: str | None) -> dict[str, Any] | None:
    """``conflict`` כשהגרסה שהעריכה עומדת להיבנות עליה אינה זו שהסוכן קרא.

    רץ מיד אחרי :func:`_load_editable`, לפני שדבר מוחל. ה-hash שמושווה הוא
    ``content_sha256`` שה-backend כבר צירף ל-``doc`` — ``_full`` ב-
    ``mcp_server/backend.py``, הנקודה האחת שמחשבת אותו, ואותה פונקציה שממנה
    ``codekeeper_get_file`` מחזיר אותו — ולא חישוב שני כאן.

    ``doc`` בלי ``content_sha256`` הוא backend שהפר את החוזה, ולא "אין מה
    להשוות": ``TypeError`` בקול, כמו ``_full`` על תוכן שאינו מחרוזת. נפילה
    ל"עבור בלי בדיקה" הייתה כותבת בדיוק במקרה שבו הסוכן ביקש שלא.

    ``file`` בסירוב הוא המטא-דאטה בלי התוכן (``_file_meta`` — המקום היחיד שבונה
    ``file`` כזה), עם ``version`` ו-``content_sha256`` הנוכחיים. הייבוא עצל כי
    ``backend`` מייבא את המודול הזה בטעינה.
    """
    if expected is None:
        return None
    current = doc.get("content_sha256")
    if not isinstance(current, str):
        raise TypeError(
            "the stored version carries no content_sha256, so expected_content_sha256 "
            "cannot be checked"
        )
    if expected.lower() == current.lower():
        return None
    from .backend import _file_meta

    return {
        "ok": False,
        "error": "conflict",
        "file": _file_meta(doc),
        "hint": "the file changed since you read it; nothing was written. Re-read it with "
        "codekeeper_get_file (every mode carries file.content_sha256), rebuild the edit "
        "on the current content, and send it again",
    }


def edit_file(
    backend: Any,
    user_id: int,
    *,
    file_name: str,
    old_string: str,
    new_string: str,
    replace_all: bool = False,
    expected_content_sha256: str | None = None,
) -> dict[str, Any]:
    """Server-side find-and-replace on the latest version of an existing file.

    The client sends only the changed snippet (old/new) — never the whole file.
    The result goes through the same append-only versioned save path, so the
    pre-edit version stays recoverable via ``list_versions``.

    ``expected_content_sha256`` הוא השער האופטימי המשותף לכלי העריכה — ראו את
    ההערה מעל :func:`_invalid_expected_sha256`. בלעדיו אין שום בדיקה נוספת.
    """
    name = (file_name or "").strip()
    if not name:
        return {"ok": False, "error": "missing_file_name"}
    if not isinstance(old_string, str) or not isinstance(new_string, str):
        return {"ok": False, "error": "invalid_arguments"}
    bad_expected = _invalid_expected_sha256(expected_content_sha256)
    if bad_expected is not None:
        return bad_expected
    doc, code = _load_editable(backend, user_id, name)
    if doc is None:
        return {"ok": False, "error": "not_found"}
    if code == "":
        return {"ok": False, "error": "empty_file"}
    changed = _changed_since_read(doc, expected_content_sha256)
    if changed is not None:
        return changed
    max_size = max_code_size()
    new_code, occurrences, err = _apply_edit(
        code, old_string, new_string, bool(replace_all), max_size=max_size
    )
    if err is not None or new_code is None:
        out: dict[str, Any] = {"ok": False, "error": err or "edit_failed"}
        if err == "ambiguous_match":
            out["occurrences"] = occurrences
            out["hint"] = "pass a longer unique old_string, or set replace_all=true"
        if err == "code_too_large":
            out["max"] = max_size
        return out
    res = _resave_edited(
        backend, user_id, name=name, doc=doc, new_code=new_code, tool="codekeeper_edit_file"
    )
    if not res.get("ok"):
        return res
    return _resaved_answer(res, replacements=occurrences)


def append_file(
    backend: Any,
    user_id: int,
    *,
    file_name: str,
    content: str = "",
    expected_content_sha256: str | None = None,
    upload_id: str | None = None,
) -> dict[str, Any]:
    """Append ``content`` to the end of an existing file (as a new version).

    A newline separator is inserted when the current body doesn't end with one,
    so an appended section always starts on a fresh line.

    ``expected_content_sha256`` — אותו שער כמו ב-:func:`edit_file`.

    ``upload_id`` — הטקסט מהעלאה במקום ``content``, באותו סדר של
    :func:`save_file`; השער רץ בתוך :func:`_resave_edited`, אחרי בדיקת התקרה על
    הקובץ המלא. **כאן החד-פעמיות היא ההבטחה עצמה:** הוספה שנשלחה שוב כי התשובה
    אבדה בדרך נענית ``upload_not_found``, והקובץ מכיל את הטקסט פעם אחת.
    """
    name = (file_name or "").strip()
    if not name:
        return {"ok": False, "error": "missing_file_name"}
    upload: _PendingUpload | None = None
    if upload_id is not None:
        if isinstance(content, str) and content != "":
            return _both_sent("content")
        loaded = _load_upload(backend, user_id, upload_id, tool="codekeeper_append_file")
        if isinstance(loaded, dict):
            return loaded
        upload = loaded
        content = upload.text
    if not isinstance(content, str) or content == "":
        return {
            "ok": False,
            "error": "empty_content",
            "hint": "send the text in the content parameter, or upload the file first and pass upload_id",
        }
    bad_expected = _invalid_expected_sha256(expected_content_sha256)
    if bad_expected is not None:
        return bad_expected
    doc, code = _load_editable(backend, user_id, name)
    if doc is None:
        return {"ok": False, "error": "not_found"}
    if code == "":
        return {"ok": False, "error": "empty_file"}
    changed = _changed_since_read(doc, expected_content_sha256)
    if changed is not None:
        return changed
    sep = "" if code.endswith("\n") else "\n"
    res = _resave_edited(
        backend,
        user_id,
        name=name,
        doc=doc,
        new_code=code + sep + content,
        tool="codekeeper_append_file",
        consume=None
        if upload is None
        else functools.partial(_consume_upload, backend, user_id, upload, tool="codekeeper_append_file"),
    )
    if not res.get("ok"):
        return res
    return _resaved_answer(res, appended_chars=len(content))


# ---------------------------------------------------------------------------
# ``codekeeper_multi_edit_file`` — כמה עריכות בקובץ אחד, בגרסה אחת.
#
# **הסמנטיקה היא של כמה קריאות עוקבות ל-``codekeeper_edit_file``, מקופלות
# לשמירה אחת:** הזוגות מוחלים בסדר שנשלחו, כל זוג על התוצאה של קודמו, דרך אותו
# :func:`_apply_edit`, ורק בסוף יש :func:`_resave_edited` אחד. "כולם או כלום"
# אינו מנגנון נוסף אלא תוצאה של המבנה: כל התוצאה נבנית בזיכרון, ויש ``insert``
# אחד — זוג שנכשל, או שמירה שמסרבת, משאירים את המסד כמו שהיה.
# ---------------------------------------------------------------------------


def validation_problems(exc: ValidationError) -> list[dict[str, Any]]:
    """מה נכשל ואיפה — בלי להדהד את הערך שנשלח.

    הערך יכול להיות תוכן של קובץ, ו-``str(exc)`` של pydantic **כן** נושא אותו
    (``input_value=...``) — ולכן החריגה עצמה לעולם אינה יוצאת מכאן, רק הרשימה.
    **שתי שכבות, וכל אחת מהן לבדה מספיקה:** ``include_input=False`` מוריד את
    הערך מהרשומות, ומכל רשומה מועתקים רק ``loc`` (אינדקסים ושמות שדות) ו-``msg``
    (סוג הבעיה). נמדד במוטציות: ``include_input=True`` לבדו אינו מדליף, והעברת
    הרשומות כמו שהן, עם הערך, כן. משותף ל-``invalid_item`` של
    ``codekeeper_read_batch`` ול-``invalid_edit`` כאן, כדי ששני הסירובים לא
    יבנו את אותה רשימה בשני נוסחים.
    """
    return [
        {"loc": list(err.get("loc") or ()), "msg": err.get("msg")}
        for err in exc.errors(include_url=False, include_context=False, include_input=False)
    ]


# זוג עריכה אחד — הארגומנטים של ``codekeeper_edit_file`` בלי ``file_name``.
#
# ``extra="forbid"`` ו-``strict=True``, כמו ``SectionItem`` ב-``read_batch``: מפתח זר,
# ``replace_all`` שאינו בוליאני של JSON (``"true"``, ``1``), או מחרוזת שאינה מחרוזת —
# סירוב גלוי שמצביע על הזוג והשדה, ולא קריאה שגויה. זה שונה מהכלל של דגל ברמה העליונה
# (ההערה מעל ``StrictInt``): שם ה-SDK ממיר ``"true"`` לבוליאני בכוונה, וכאן הטיפוס מוצהר
# בתוך אובייקט JSON.
#
# **שטוח בכוונה** — בלי מודל מקונן ובלי ``Enum`` — כדי שהסכימה שלו לא תישא
# ``$defs``/``$ref``, שאף כלי בשרת הזה אינו מפרסם.
#
# **ההסבר כאן ולא ב-docstring, כי ה-docstring מתפרסם.** ``model_json_schema`` מעתיק
# אותו ל-``description`` של הסכימה שהלקוח רואה (נמדד, pydantic 2.12.3), ולכן הוא שורה
# אחת שמיועדת לסוכן, באנגלית כמו שאר תיאורי הכלים.
class EditPair(BaseModel):
    """One edit: the arguments of codekeeper_edit_file without file_name."""

    model_config = ConfigDict(extra="forbid", strict=True)

    old_string: str
    new_string: str
    replace_all: bool = False


#: המאמת של הרשימה כולה, בקריאה אחת — ולכן ``loc`` של כל שגיאה נפתח באינדקס
#: הזוג, וכל הבעיות המבניות חוזרות בתשובה אחת.
#:
#: **נבנה בייבוא, ונבדק במקור שהשימוש הראשון אינו בונה דבר לא מוגן** (K15). ב-
#: ``pydantic 2.12.3`` הבנאי קורא ל-``_init_core_attrs(force=False)``, ובלי
#: ``defer_build`` בונה שם את ה-validator ומסמן ``pydantic_complete``, ו-
#: ``validate_python`` רק קורא לו (``pydantic/type_adapter.py``). ב-``pydantic-core
#: 2.41.4`` השדה העצל היחיד במסלול הזה הוא השם של ``ListValidator``, ‏
#: ``OnceLock<String>`` שנבנה ב-``get_or_init`` (``src/validators/list.rs``) — ו-
#: ``OnceLock`` של Rust מבטיח שרק מאתחל אחד רץ גם כשכמה חוטים ניגשים יחד.
#: ב-``model.rs``, ‏``model_fields.rs``, ‏``string.rs`` ו-``bool.rs`` אין מצב עצל.
_EDITS_ADAPTER: TypeAdapter[list[EditPair]] = TypeAdapter(list[EditPair])

#: הסכימה שהלקוח רואה לזוג — **נגזרת מהמודל שהגוף מאמת לפיו**, כך שהחוזה
#: המוצהר והאכיפה אינם יכולים להיפרד (כמו ``ITEM_JSON_SCHEMA`` ב-``read_batch``).
EDIT_PAIR_JSON_SCHEMA: dict[str, Any] = EditPair.model_json_schema()

#: כמה זוגות קריאה אחת נושאת. **נדחה ולא נחתך** (``too_many_edits``): באץ' שנחתך
#: היה מחיל חלק מהעריכות ומדווח הצלחה — בדיוק החצי-מוחל שהכלי בא למנוע.
#:
#: **למה 50.** העבודה על כל זוג היא ``count`` ו-``replace`` על מחרוזת בזיכרון של
#: עד ``max_code_size()`` תווים — לינארית במספר הזוגות ובגודל הקובץ — ותקרת גוף
#: הבקשה (``limits.request_bytes_for``) כבר חוסמת את הקלט עצמו. הדיווח שהוליד את
#: הכלי היה ארבע עריכות לעדכון לוגי אחד; 50 גבוה מכל עדכון כזה, ונמוך מספיק
#: שאיש לא יבנה על הכלי מסלול כתיבה מלא. גם הצמיחה בין הזוגות חסומה: כל זוג
#: נבדק מול ``max_code_size()`` לפני שהתוצאה שלו נבנית (:func:`_apply_edit`).
#:
#: **ובמגבלת הקצב הקריאה שוקלת 1, לא מספר הזוגות** — בניגוד ל-
#: ``codekeeper_read_batch``, שנשקל כמספר הפריטים כי כל פריט שם הוא קריאה ופרסור.
#: כאן יש קריאה אחת מהמסד ושמירה אחת, והזוגות הם פעולות מחרוזת. לכן אין לכלי
#: הזה ענף ב-``AdminAwareFastMCP.call_tool``.
MAX_EDIT_PAIRS = 50

#: מה שכל סירוב של זוג אומר, מעבר לקוד שלו.
_NOTHING_WRITTEN = (
    "nothing was written: the batch is all or nothing. Fix this pair and send the whole "
    "batch again"
)


def refuse_edits(edits: list[Any]) -> dict[str, Any] | None:
    """הסירוב של הקריאה כולה על אורך הרשימה — או ``None``.

    אותה צורה כמו ``refuse_items`` של ``codekeeper_read_batch``: רשימה ריקה היא
    סירוב ולא באץ' ריק שהצליח, ורשימה מעל התקרה נדחית ולא נחתכת.
    """
    if not edits:
        return {"ok": False, "error": "missing_edits"}
    if len(edits) > MAX_EDIT_PAIRS:
        return {"ok": False, "error": "too_many_edits", "count": len(edits), "max": MAX_EDIT_PAIRS}
    return None


def _pair_refusal(
    index: int, err: str | None, occurrences: int, *, old_string: str, stored: str, max_size: int
) -> dict[str, Any]:
    """הסירוב של זוג שנכשל: הקוד של ``codekeeper_edit_file``, ``index``, והסבר.

    ב-``no_match`` וב-``ambiguous_match`` שני מספרים, ולעולם לא טקסט:
    ``occurrences`` — כמה פעמים ``old_string`` נמצא בטקסט **אחרי** הזוגות
    שלפניו, ו-``occurrences_in_stored_version`` — כמה פעמים בגרסה כפי שנשמרה.
    כשהם שונים, זוג קודם בבאץ' שינה את מה שהזוג הזה מחפש, וזה המקרה שסוכן יוצר
    בטעות: הוא מקבל "לא נמצא" על מחרוזת שהוא בטוח שקיימת. ה-``count`` הנוסף רץ
    רק כאן, במסלול הכשל.
    """
    out: dict[str, Any] = {"ok": False, "error": err or "edit_failed", "index": index}
    hint = _NOTHING_WRITTEN
    if err in ("no_match", "ambiguous_match"):
        in_stored = stored.count(old_string)
        out["occurrences"] = occurrences
        out["occurrences_in_stored_version"] = in_stored
        if occurrences != in_stored:
            hint += (". An earlier pair in this batch changed the text this pair looks for: "
                     "occurrences counts the text after the pairs before it, "
                     "occurrences_in_stored_version the file as stored")
        if err == "ambiguous_match":
            hint += ". Pass a longer unique old_string, or set replace_all=true on this pair"
    if err == "code_too_large":
        out["max"] = max_size
    out["hint"] = hint
    return out


def multi_edit_file(
    backend: Any,
    user_id: int,
    *,
    file_name: str,
    edits: list[Any],
    expected_content_sha256: str | None = None,
) -> dict[str, Any]:
    """Several exact find-and-replace edits on one existing file, saved as ONE new version.

    **הסדר, וזו כל ההכרעה:** כל מה שזול ומקומי רץ **לפני** הקריאה מהמסד —
    ``missing_file_name``, אורך הרשימה, המבנה של **כל** הזוגות, והצורה של
    ``expected_content_sha256`` — כך שקלט פגום אינו עולה קריאה, וזוג פגום
    במקום השלישי נענה מיד, לפני שזוג ראשון מוחל. אחרי הקריאה: ``not_found``,
    ``empty_file``, השער (צריך את התוכן), הזוגות בסדרם, ושמירה אחת. אותו סדר
    כמו ב-:func:`edit_file`.

    ``edits`` שאינו רשימה אינו נענה כאן: הסכימה של הכלי מבטיחה רשימה, וה-SDK
    דוחה כל דבר אחר לפני שהגוף רץ — כמו ``items`` של ``codekeeper_read_batch``.
    """
    name = (file_name or "").strip()
    if not name:
        return {"ok": False, "error": "missing_file_name"}
    if not isinstance(edits, list):
        raise TypeError("edits must be a list; the tool's schema guarantees one")
    refusal = refuse_edits(edits)
    if refusal is not None:
        return refusal
    try:
        pairs = _EDITS_ADAPTER.validate_python(edits)
    except ValidationError as exc:
        problems = validation_problems(exc)
        # ``loc`` של כל בעיה נפתח באינדקס הזוג (הרשימה אומתה כולה); ``index`` הוא
        # הזוג הראשון שנכשל, כמו בסירוב של זוג שלא התאים.
        return {
            "ok": False,
            "error": "invalid_edit",
            "index": min(problem["loc"][0] for problem in problems),
            "problems": problems,
        }
    bad_expected = _invalid_expected_sha256(expected_content_sha256)
    if bad_expected is not None:
        return bad_expected
    doc, stored = _load_editable(backend, user_id, name)
    if doc is None:
        return {"ok": False, "error": "not_found"}
    if stored == "":
        return {"ok": False, "error": "empty_file"}
    changed = _changed_since_read(doc, expected_content_sha256)
    if changed is not None:
        return changed
    max_size = max_code_size()
    code = stored
    replacements = 0
    for index, pair in enumerate(pairs):
        new_code, occurrences, err = _apply_edit(
            code, pair.old_string, pair.new_string, pair.replace_all, max_size=max_size
        )
        if err is not None or new_code is None:
            return _pair_refusal(
                index, err, occurrences, old_string=pair.old_string, stored=stored,
                max_size=max_size,
            )
        code = new_code
        # החלפות בפועל ולא זוגות: זוג עם ``replace_all`` שפגע בשבעה מופעים תורם
        # שבעה — בדיוק כמו ``replacements`` של ``codekeeper_edit_file``.
        replacements += occurrences
    res = _resave_edited(
        backend, user_id, name=name, doc=doc, new_code=code, tool="codekeeper_multi_edit_file"
    )
    if not res.get("ok"):
        return res
    return _resaved_answer(res, edits_applied=len(pairs), replacements=replacements)


def update_file_description(
    backend: Any, user_id: int, *, file_name: str, description: str
) -> dict[str, Any]:
    """Replace an existing file's ``description`` — **no new version is written**.

    Unlike :func:`edit_file` and :func:`append_file`, which round-trip the body
    through the versioned save path, this is a metadata ``$set`` on the file's
    latest version. Three consequences the caller has to know, and the tool
    description says all three out loud:

    - No version is created, so ``codekeeper_list_versions`` will not show this
      change and the **previous description is not recoverable** from anywhere.
      It is returned in the response precisely because that is the only place it
      will ever appear again.
    - Earlier versions keep the old description. Reading one back by number
      returns what it carried at the time.
    - The file's content and version number do not move.

    **It also stamps the description as checked.** The write sets
    ``description_set_at_version`` to the version being updated, which is
    what resets ``description_age_versions`` to 0 — even when the text
    sent is identical to the one stored. That is deliberate: calling this
    tool means someone compared the description against the current
    content, which is exactly what the age is a proxy for. An edit
    carrying the description forward makes no such claim, and there the
    stamp stays where it was. The reply says ``unchanged: true`` when the
    text did not move, so "only the stamp changed" is visible rather than
    inferred. Clearing the description removes the stamp instead of
    zeroing it — a file with no description has no age.

    **The length ceiling is enforced in the write, not here** (#3489). It is
    ``FILE_DESCRIPTION_MAX_CHARS`` in ``file_description.py``, and
    ``update_file_metadata_in`` refuses a longer description as
    ``description_too_long`` with ``max_chars`` and ``actual_chars`` — **unless it
    is the text already stored**, which passes at any length and resets the
    stamp like any identical text does. "Already stored" has to be decided
    against the document being updated, in the same atomic write, so it cannot
    be decided here; this handler only adds the ``message`` that names the unit
    (:func:`_over_the_description_ceiling`), the half the agent was missing.

    Rejecting rather than clipping is the same call :func:`_sanitize_note_text`
    makes: an agent does not see the stored result, so a silent truncation is
    data loss it will never learn about.
    """
    name = (file_name or "").strip()
    if not name:
        return {"ok": False, "error": "missing_file_name"}
    # mypy מסמן את השורה הבאה ``unreachable``, כי החתימה מצהירה ``str``.
    # הבדיקה נשארת מאותה סיבה שהיא נשארת ב-:func:`edit_file` וב-
    # :func:`append_file` — ושם היא מייצרת בדיוק את אותה הערה: ההצהרה
    # אינה אכיפה בזמן ריצה, והערך מגיע מחוץ לתהליך
    # (``bugbot-rules/external-input-isinstance.md``). כאן היא גם מגנה
    # קונקרטית על ה-``.strip()`` שמיד אחריה, שהיה זורק ``AttributeError``
    # במקום להחזיר קוד שגיאה.
    if not isinstance(description, str):
        return {"ok": False, "error": "invalid_description"}
    # ``strip`` בלבד, ובמכוון לא יותר: זו בדיוק הנורמליזציה שהראוט בוובאפ
    # מפעיל, ותיאור שנכתב בשני הערוצים צריך להיראות אותו דבר. מחרוזת ריקה
    # אחרי ה-strip היא בקשה תקפה — "נקה את התיאור" — ולא שגיאה.
    cleaned = description.strip()
    res = backend.update_file_description(
        user_id, file_name=name, description=cleaned
    )
    if not isinstance(res, dict) or not res.get("ok"):
        # ערוץ הכשל של מסלול הכתיבה הוא ערך ההחזרה ולא חריגה, ולכן הבדיקה
        # הזו היא מה שמפריד בין "עודכן" לבין "לא נזרקה חריגה"
        # (``CRITICAL-PATTERNS.md`` K11). ``isinstance`` כלול כי backend
        # שמחזיר ``None`` היה עובר ``.get`` בחריגה ולא בקוד שגיאה.
        if not isinstance(res, dict):
            return {"ok": False, "error": "update_failed"}
        if res.get("error") == "description_too_long":
            # המספרים מהכתיבה עצמה; ההודעה — היחידה, שהסוכן לא יכול לנחש.
            return {**res, "message": "Nothing was written: the description is "
                    + _over_the_description_ceiling(res) + "."}
        return res
    previous_description = (res.get("previous") or {}).get("description")
    return {
        "ok": True,
        "file_name": res.get("file_name") or name,
        # מספר הגרסה מוחזר כדי לומר במפורש שהוא **לא** זז. הוא נקרא
        # מהמסמך שנכתב, לא מהבקשה.
        "version": res.get("version"),
        "previous_description": previous_description,
        "description": cleaned,
        "version_created": False,
        # **הקריאה הזו מסמנת את התיאור כנבדק, גם כשהטקסט לא זז.** היא
        # מאפסת את ``description_age_versions``, כי היא אישור מפורש
        # שהתיאור הושווה לתוכן הנוכחי — בניגוד להעתקה האוטומטית שעריכה
        # עושה, שאינה אומרת דבר על התוכן. ``unchanged`` קיים כדי שההבדל
        # יהיה גלוי: ``true`` פירושו ששום דבר לא השתנה **מלבד** החותמת,
        # ולא שהקריאה לא עשתה כלום.
        #
        # ההשוואה היא מול הערך שנקרא מהמסמך שנכתב, ולא מול מה שהקורא
        # חשב שכתוב שם.
        "unchanged": previous_description == cleaned,
    }


# -- sticky notes ----------------------------------------------------------

MAX_NOTES_PER_SCOPE = 200
MAX_ANCHOR_TEXT = 256
MAX_NOTE_LINE = 1_000_000
#: ברירת המחדל היא **המזהה** ולא ה-``hex``. הגוון עצמו חי ב-
#: ``sticky_notes_target.NOTE_COLORS``, ולכן החלפתו אינה נוגעת כאן.
DEFAULT_NOTE_COLOR = DEFAULT_NOTE_COLOR_ID
# sentinel של הוובאפ לפתק "צף": בלעדיו ה-JS מעגן פתק חדש אוטומטית לשורה הקרובה
NOTE_FLOATING_ANCHOR = "__floating__"

_NOTE_ID_RE = re.compile(r"^[0-9a-fA-F]{24}$")
# עותק של webapp/sticky_notes_api.py:_CONTROL_CHARS_RE — לשמור מסונכרן
_NOTE_CONTROL_CHARS_RE = re.compile(r"[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F]")


def _clean_note_id(note_id: Any) -> str | None:
    """מזהה פתק בצורתו **הקנונית** — או ``None`` כשאינו בצורת ObjectId.

    ``_NOTE_ID_RE`` מקבל גם הקסה גדולה, ו-``str(ObjectId)`` היא תמיד קטנה —
    וזו הצורה ש-``sticky_note_versions.note_id`` מחזיק. מזהה שהוקלד באותיות
    גדולות עבר את השער, מצא את הפתק (``ObjectId`` סלחני) ואז חיפש היסטוריה
    שלעולם לא תימצא: ``version_not_found`` על גרסה שקיימת (נתפס בסקירה של
    #3456). אותה מלכודת בדיוק של ``_canonical_board_id`` ב-backend, ומאותו
    נימוק — ולכן שער אחד לכל כלי שמקבל ``note_id``, ולא ``.match`` בכל אחד.
    """
    nid = str(note_id or "").strip()
    if not _NOTE_ID_RE.match(nid):
        return None
    return nid.lower()


def _note_color_or_error(color: str | None, *, default: str | None) -> Any:
    """הצבע לכתיבה, או **תשובת שגיאה** כשסופק ערך שאי אפשר לפענח.

    עד כאן ערך לא תקין נבלע: ביצירה הוא הוחלף בברירת המחדל, ובעדכון הוא
    נשמט — ובשני המקרים הסוכן קיבל ``ok``. סוכן שמקבל ``ok`` על צבע שלא
    הוחל **מדווח למשתמש דבר לא נכון**, וזה בדיוק סוג האישור השקרי
    ש-``CRITICAL-PATTERNS`` K11 מתאר: ערוץ הכשל היה קיים, ואיש לא קרא בו.

    **ההבחנה היא בין "לא ביקשתי צבע" לבין "ביקשתי צבע שאינו קיים".**
    ``None`` ומחרוזת ריקה (או רווחים בלבד) הם הראשון, ולכן נופלים
    ל-``default`` בשקט — זה אינו בקשה שנכשלה. כל ערך אחר שאינו נפתר הוא
    השני, והוא חוזר כשגיאה **עם רשימת המזהים התקינים**, כדי שהסוכן יוכל
    לתקן בניסיון הבא במקום לנחש.

    הצורה זהה ל-``invalid_mode`` שלצידה — ``error`` עם ``allowed`` —
    ולא שם חדש לאותו סוג תשובה.

    :returns: מחרוזת הצבע, ``default``, או מילון שגיאה. הקורא מזהה את
        השלישי ב-``isinstance(..., dict)`` ומחזיר אותו מיד.
    """
    from sticky_notes_target import NOTE_COLOR_ORDER

    if not isinstance(color, str) or not color.strip():
        return default
    resolved = resolve_note_color(color, default=None)
    if not resolved:
        return {"ok": False, "error": "invalid_color", "allowed": list(NOTE_COLOR_ORDER)}
    return resolved


def _sanitize_note_text(text: Any) -> str:
    """Normalize note text like the webapp does — without truncating.

    Length is the caller's decision (reject, not clip): silent clipping is data
    loss an agent won't notice.
    """
    if text is None:
        return ""
    try:
        s = str(text)
    except Exception:
        return ""
    s = html.unescape(s)
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    return _NOTE_CONTROL_CHARS_RE.sub("", s)


def _valid_note_line(line: Any) -> int | None:
    """Coerce a 1-indexed source line; None on invalid."""
    try:
        line_i = int(line)
    except (TypeError, ValueError):
        return None
    if not 1 <= line_i <= MAX_NOTE_LINE:
        return None
    return line_i


def _clean_anchor_text(anchor_text: Any) -> str | None:
    text = _sanitize_note_text(anchor_text).strip()
    # קיטום קוסמטי בלבד (פריטת הוובאפ) — לא תוכן משתמש שאסור לאבד
    return text[:MAX_ANCHOR_TEXT] or None


def list_notes(
    backend: Any, user_id: int, *, file_name: str, include_content: bool = True
) -> dict[str, Any]:
    """List the user's sticky notes attached to ``file_name`` (read-only).

    ``include_content`` הוא פרמטר תוספתי: ברירת המחדל מחזירה בדיוק את מה
    שהכלי החזיר לפניו. **רק ``False`` מפורש** מוריד את הגוף מהשורות —
    ערך שאינו בוליאני נופל לצד המלא, שהוא ההתנהגות הישנה ולא הצורה החדשה.
    """
    name = (file_name or "").strip()
    if not name:
        return {"ok": False, "error": "missing_file_name"}
    return backend.list_notes(user_id, file_name=name, include_content=include_content is not False)


def create_note(
    backend: Any,
    user_id: int,
    *,
    file_name: str,
    content: str,
    line: int | None = None,
    color: str | None = None,
    anchor_text: str | None = None,
) -> dict[str, Any]:
    """Attach a sticky note to an existing file.

    With ``line`` the note anchors to that 1-indexed source line; without it the
    note is created floating (explicit sentinel — otherwise the web client
    auto-anchors it to the nearest line on first render).
    """
    name = (file_name or "").strip()
    if not name:
        return {"ok": False, "error": "missing_file_name"}

    clean = _sanitize_note_text(content).strip()
    if not clean:
        return {"ok": False, "error": "empty_content"}
    if len(clean) > MAX_NOTE_CONTENT:
        return {"ok": False, "error": "content_too_long", "max": MAX_NOTE_CONTENT}

    line_i: int | None = None
    if line is not None:
        line_i = _valid_note_line(line)
        if line_i is None:
            return {"ok": False, "error": "invalid_line", "min": 1, "max": MAX_NOTE_LINE}

    # מזהה מהפלטה **או** ``hex`` חופשי; ``hex`` שתואם גוון של הפלטה נשמר
    # כמזהה שלה. ערך שסופק ואינו נפתר עוצר את היצירה בשגיאה.
    color_s = _note_color_or_error(color, default=DEFAULT_NOTE_COLOR)
    if isinstance(color_s, dict):
        return color_s

    return backend.create_note(
        user_id,
        file_name=name,
        content=clean,
        line=line_i,
        color=color_s,
        anchor_text=_clean_anchor_text(anchor_text),
        anchor_id=None if line_i else NOTE_FLOATING_ANCHOR,
    )


#: מזהה לוח הוא ObjectId, בדיוק כמו ``note_id``.
_BOARD_ID_RE = _NOTE_ID_RE


def list_boards(backend: Any, user_id: int) -> dict[str, Any]:
    """List the user's note boards (read-only)."""
    return backend.list_boards(user_id)


def list_board_notes(
    backend: Any, user_id: int, *, board_id: str, include_content: bool = True
) -> dict[str, Any]:
    """List the sticky notes sitting on one board (read-only).

    ``include_content`` — אותו כלל בדיוק כמו ב-:func:`list_notes`.
    """
    bid = (board_id or "").strip()
    if not _BOARD_ID_RE.match(bid):
        return {"ok": False, "error": "invalid_board_id"}
    return backend.list_board_notes(
        user_id, board_id=bid, include_content=include_content is not False
    )


def create_board_note(
    backend: Any,
    user_id: int,
    *,
    board_id: str,
    content: str,
    color: str | None = None,
    mode: str | None = None,
    title: str | None = None,
) -> dict[str, Any]:
    """Attach a sticky note to a board (a surface that belongs to no file).

    ``mode`` בוחר בין ``surface`` (יושב על הלוח, ברירת המחדל) לבין
    ``screen`` (צף מול המסך). ``anchored`` אינו חוקי כאן — הוא דורש שורות
    מקור, ובלוח אין כאלה; פתק כזה היה מחשב מיקום מול עוגן שאינו קיים.
    """
    from sticky_notes_target import (
        DEFAULT_BOARD_MODE, is_valid_board_mode, normalize_mode, normalize_note_title,
    )

    bid = (board_id or "").strip()
    if not _BOARD_ID_RE.match(bid):
        return {"ok": False, "error": "invalid_board_id"}

    clean = _sanitize_note_text(content).strip()
    if not clean:
        return {"ok": False, "error": "empty_content"}
    if len(clean) > MAX_NOTE_CONTENT:
        return {"ok": False, "error": "content_too_long", "max": MAX_NOTE_CONTENT}

    if mode is not None and not is_valid_board_mode(mode):
        return {"ok": False, "error": "invalid_mode", "allowed": ["surface", "screen"]}

    # אותה ולידציה בדיוק כמו ב-``create_note``
    color_s = _note_color_or_error(color, default=DEFAULT_NOTE_COLOR)
    if isinstance(color_s, dict):
        return color_s

    return backend.create_board_note(
        user_id,
        board_id=bid,
        content=clean,
        color=color_s,
        mode=normalize_mode(mode, DEFAULT_BOARD_MODE),
        title=normalize_note_title(title),
    )


# -- פתקי ריפו: היעד השלישי ------------------------------------------------
#
# **ולידציית שם הריפו כאן היא בדיקת צורה, ולא הדפוס הקנוני.** המודול הזה
# טהור, ו-``REPO_NAME_PATTERN`` יושב במודול שמייבא ``subprocess``. הבדיקה
# הסמכותית ממילא ב-backend — מול רשימת הריפואים הממוררים בפועל, שהיא מקור
# אמת חזק מכל דפוס.
MAX_REPO_NAME = 100

#: תקרת תוצאות חיפוש. הכלי חוצה שלושה יעדים, ותשובה ארוכה מזו כבר לא
#: עוזרת לאתר פתק — היא רק דוחפת את השאר מהקשר.
MAX_NOTE_SEARCH_RESULTS = 50
DEFAULT_NOTE_SEARCH_RESULTS = 20


def _clean_repo_name(repo_name: Any) -> str | None:
    """שם ריפו כשהוא תקין בצורתו, אחרת ``None``.

    ``/`` נדחה כי שם עם לוכסן היה נראה כמו ``owner/repo`` ומייצר יעד שאינו
    מתלכד עם מה ש-``repo_metadata`` מחזיק — כלומר פתק שלעולם לא יימצא.
    """
    name = str(repo_name or "").strip()
    if not name or "/" in name or len(name) > MAX_REPO_NAME:
        return None
    return name


def list_repo_notes(backend: Any, user_id: int, *, repo_name: str, repo_path: str) -> dict[str, Any]:
    """List the sticky notes on one file inside a mirrored repository (read-only)."""
    from sticky_notes_target import normalize_repo_path

    name = _clean_repo_name(repo_name)
    if name is None:
        return {"ok": False, "error": "invalid_repo_name"}

    # **הנרמול קורה כאן, לפני ה-backend.** ``repo_files`` שומר נתיבים בצורת
    # git הגולמית, ו-``normalize_repo_path`` מתכנס בדיוק אליה — כולל דחיית
    # ``..``. בלי המעבר הזה נתיב שכתוב ``./a/../b.py`` היה שאילתה שאינה
    # מוצאת דבר, בלי שום שגיאה.
    path = normalize_repo_path(repo_path)
    if not path:
        return {"ok": False, "error": "invalid_repo_path"}

    return backend.list_repo_notes(user_id, repo_name=name, repo_path=path)


def create_repo_note(
    backend: Any,
    user_id: int,
    *,
    repo_name: str,
    repo_path: str,
    content: str,
    color: str | None = None,
    mode: str | None = None,
    title: str | None = None,
) -> dict[str, Any]:
    """Attach a sticky note to a file inside a mirrored repository.

    היעד הוא הזוג ``(repo_name, repo_path)`` **בלי ענף**: פתק שנרשם כשהיית
    על ``main`` מופיע גם כשאתה על ענף PR — זו אותה שורת קוד.

    ``mode`` זהה לזה של הלוח: ``surface``/``screen``. ``anchored`` אינו
    חוקי — התצוגה בדפדפן הריפו היא CodeMirror, שאינו מרנדר שורות מחוץ
    למסך, ולכן אין לו DOM להיצמד אליו.
    """
    from sticky_notes_target import (
        DEFAULT_BOARD_MODE, is_valid_board_mode, normalize_mode, normalize_note_title,
        normalize_repo_path,
    )

    # **אותם שערים בדיוק כמו במסלול הקריאה, ובאותו סדר.** שני מסלולים
    # שגוזרים שערים שונים הם שני מושגים שונים של "יעד חוקי".
    name = _clean_repo_name(repo_name)
    if name is None:
        return {"ok": False, "error": "invalid_repo_name"}
    path = normalize_repo_path(repo_path)
    if not path:
        return {"ok": False, "error": "invalid_repo_path"}

    clean = _sanitize_note_text(content).strip()
    if not clean:
        return {"ok": False, "error": "empty_content"}
    if len(clean) > MAX_NOTE_CONTENT:
        return {"ok": False, "error": "content_too_long", "max": MAX_NOTE_CONTENT}

    if mode is not None and not is_valid_board_mode(mode):
        return {"ok": False, "error": "invalid_mode", "allowed": ["surface", "screen"]}

    color_s = _note_color_or_error(color, default=DEFAULT_NOTE_COLOR)
    if isinstance(color_s, dict):
        return color_s

    return backend.create_repo_note(
        user_id,
        repo_name=name,
        repo_path=path,
        content=clean,
        color=color_s,
        mode=normalize_mode(mode, DEFAULT_BOARD_MODE),
        title=normalize_note_title(title),
    )


def list_repo_note_paths(backend: Any, user_id: int, *, repo_name: str) -> dict[str, Any]:
    """Which files inside a mirrored repo carry sticky notes (read-only).

    **מפה, לא תוכן.** ``list_repo_notes`` דורש ``repo_name`` **וגם**
    ``repo_path`` מדויק — כלומר צריך כבר לדעת איפה הפתק כדי למצוא אותו.
    בלי הכלי הזה כל פתקי הריפו הם לשימוש עצמי בלבד: מי שלא רשם אותם אינו
    יכול לגלות אותם.

    אותה ולידציית שם כמו ב-``list_repo_notes``, ומאותה סיבה: שם עם ``/``
    מייצר יעד שאינו מתלכד עם ``repo_metadata``, כלומר שאילתה שלעולם לא
    תמצא דבר.
    """
    name = _clean_repo_name(repo_name)
    if not name:
        return {"ok": False, "error": "invalid_repo_name"}
    return backend.list_repo_note_paths(user_id, repo_name=name)


def add_to_collection(
    backend: Any,
    user_id: int,
    *,
    collection_id: str,
    file_name: str,
    folder: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    """Attach an existing saved file to an existing collection.

    **כלי נפרד, ולא פרמטר ל-``save_file``.** שמירה שמצליחה ושיוך שנכשל
    הם הצלחה חלקית של שתי פעולות שנקשרו לאחת — ואז הודעת ההצלחה מתארת
    מחצית ממה שקרה. שני כלים נותנים לכל פעולה תשובה כנה משלה; המחיר הוא
    קריאה שנייה.

    האימות עצמו חי ב-backend, לצד השאילתה שהוא מגן עליה.
    """
    cid = (collection_id or "").strip()
    if not _NOTE_ID_RE.match(cid):
        return {"ok": False, "error": "invalid_collection_id"}
    name = (file_name or "").strip()
    if not name:
        return {"ok": False, "error": "missing_file_name"}
    return backend.add_to_collection(
        user_id, collection_id=cid, file_name=name, folder=folder, note=note
    )


def note_str_replace(
    backend: Any,
    user_id: int,
    *,
    note_id: str,
    old_string: str,
    new_string: str,
    replace_all: bool = False,
) -> dict[str, Any]:
    """Exact find-and-replace inside one sticky note.

    **אותו** ``_apply_edit`` **של** ``edit_file``, ובכוונה: שתי מימושים
    של "מצא והחלף" נבדלים בדיוק במקרי הקצה — התאמה מרובה, מחרוזת ריקה,
    ישן שווה לחדש — ואלה בדיוק המקרים שבהם ההבדל עולה בנתונים. גם נוסחי
    השגיאה זהים, כדי שסוכן שלמד אחד יכיר את השני.

    **התקרה נבדקת לפני שהתוצאה נבנית** — ``max_size=MAX_NOTE_CONTENT``, ו-
    ``code_too_large`` שחוזר מ-:func:`_apply_edit` נענה ``content_too_long`` עם
    ``max``, התשובה שהכלי נתן גם לפני #3495 על תוצאה ארוכה מדי שאינה רווחים בלבד.
    הבדיקה שאחרי ההחלפה נשארת כרשת על מה שנכתב, ואינה ההגנה: :func:`_apply_edit`
    מחשב את אורך התוצאה בדיוק, ולכן גוף שחוזר ממנו כבר בתוך התקרה. ומכאן הסדר בין
    שני הסירובים, וזה השינוי היחיד בתשובה: תוצאה של רווחים בלבד שארוכה מהתקרה היא
    ``content_too_long`` (עד #3495 — ``empty_content``, כי בדיקת הריקות רצה
    ראשונה), ורק בתוך התקרה ``empty_content``.

    הקריאה עוברת דרך ``update_note``, ולכן היא יורשת את הצילום שנשמר
    לפני הדריסה — וזו הסיבה שהסדר בין השניים אינו הפיך: ``str_replace``
    בלי היסטוריה היה מוסיף עוד מסלול שדורס בלי ממה לשחזר.

    **‏read-modify-write נושא שער אופטימי.** הגוף שנקרא כאן מועבר
    ל-``update_note`` כ-``expected_content``, והדריסה מותנית בכך שהוא
    עדיין הגוף שבמסד. בלעדיו שתי עריכות חופפות היו קוראות את אותו גוף,
    שתיהן מדווחות הצלחה, והאחרונה מוחקת את עריכת הראשונה — הצילום היה
    משמר את הגוף **הישן**, לא את העריכה שאבדה. המפסיד מקבל ``conflict``:
    קריאה חוזרת של הפתק וניסיון נוסף הם התשובה הנכונה, לא ניצחון שקרי.
    """
    nid = _clean_note_id(note_id)
    if nid is None:
        return {"ok": False, "error": "invalid_note_id"}
    if not isinstance(old_string, str) or not isinstance(new_string, str):
        return {"ok": False, "error": "invalid_arguments"}

    current = backend.get_note(user_id, note_id=nid)
    if not isinstance(current, dict) or not current.get("ok"):
        return {"ok": False, "error": str((current or {}).get("error") or "not_found")}
    body = str((current.get("note") or {}).get("content") or "")
    if body == "":
        return {"ok": False, "error": "empty_note"}

    # הקלט מנורמל כמו שהתוכן נורמל בכתיבה — אחרת ``old_string`` עם CRLF
    # לא היה תופס גוף שנשמר עם ``\n`` בלבד.
    old_clean = _sanitize_note_text(old_string)
    new_clean = _sanitize_note_text(new_string)
    new_body, occurrences, err = _apply_edit(
        body, old_clean, new_clean, bool(replace_all), max_size=MAX_NOTE_CONTENT
    )
    if err == "code_too_large":
        # אותה תקרה בקוד של הפתקים — התשובה של כל כלי פתק שמקבל תוכן ארוך מדי.
        return {"ok": False, "error": "content_too_long", "max": MAX_NOTE_CONTENT}
    if err is not None or new_body is None:
        out: dict[str, Any] = {"ok": False, "error": err or "edit_failed"}
        if err == "ambiguous_match":
            out["occurrences"] = occurrences
            out["hint"] = "pass a longer unique old_string, or set replace_all=true"
        return out
    if not new_body.strip():
        return {"ok": False, "error": "empty_content"}
    # רשת על מה שנכתב, כמו אצל כל כותב פתקים כאן: ``backend.update_note`` אינו
    # בודק אורך. היא אינה ההגנה — ``_apply_edit`` כבר סירב לפני שהתוצאה נבנתה,
    # וכל עוד החשבון שם מדויק השורה הזו אינה נדלקת.
    if len(new_body) > MAX_NOTE_CONTENT:
        return {"ok": False, "error": "content_too_long", "max": MAX_NOTE_CONTENT}

    res = backend.update_note(
        user_id, note_id=nid, fields={"content": new_body}, expected_content=body
    )
    if not res.get("ok"):
        if res.get("error") == "conflict":
            res = dict(res)
            res["hint"] = "the note changed since it was read — re-read it and retry"
        return res
    return {"ok": True, "replacements": occurrences, "note": res.get("note")}


def get_note(backend: Any, user_id: int, *, note_id: str, is_admin: bool) -> dict[str, Any]:
    """Read ONE sticky note by id — the current body, where it sits, and its version.

    **אותה קריאה-לפי-מזהה של** ``note_str_replace`` (``backend.get_note``),
    ולא מסלול שני: מה שהכלי הזה מחזיר הוא בדיוק הגוף שהעריכה תיבדק מולו.

    **ההרשאה נבדקת לפי סוג הפתק, לפני שתוכן כלשהו חוזר.** פתק על קובץ ועל
    לוח — של הקורא בלבד, וזה כבר במסנן של ``backend.get_note``. פתק על קובץ
    בריפו משוקף חסום לאדמין, כמו ``list_repo_notes``; מי שאינו אדמין מקבל
    ``not_found`` — אותה תשובה כמו לפתק של מישהו אחר ולמזהה שאינו קיים,
    כך שהסירוב אינו מגלה שהמזהה קיים. השער נסגר גם על מסמך שנושא רק חצי
    יעד ריפו (``target: "unknown"``): כל שדה ריפו שהוא הופך את הפתק לריפו
    לעניין השער, ולא רק יעד שלם.

    ``is_admin`` הוא **חובה ובלי ברירת מחדל** (K12 §3): קורא ששכח להחליט
    נופל בקריאה, לא לצד המתיר. ורק ``True`` ממש פותח — ערך "אמיתי" שאינו
    בוליאני נשאר סגור, כמו ``_declares_write``.

    **הגוף חוזר בדיוק כפי שהוא מאוחסן** (``stored_content``), ולא הגוף
    המפוענח שכלי הרשימה מציגים; הנימוק המלא ב-``ProductionBackend.get_note``.
    ``version`` הוא מספר הגוף **הנוכחי** — המספר ש-``get_note_version``
    יקרא אותו בו — ומגיע **מאותה קריאה** של הגוף (``with_version=True``):
    ה-backend מוכיח ששום כתיבה לא נגעה בפתק בין קריאת הגוף לקריאת
    ההיסטוריה, ופתק שזז ברצף חוזר כ-``conflict`` עם רמז — לא כזוג שאולי
    אינו תואם. גוף ריק נושא ``version: null``: ההיסטוריה אינה מצלמת אותו,
    ולכן אין מספר שיחזיר אותו. פתק ריפו נושא ``orphaned: true`` כשהנתיב
    כבר אינו בעץ המשוקף, באותו כלל של ``list_repo_notes``.
    """
    nid = _clean_note_id(note_id)
    if nid is None:
        return {"ok": False, "error": "invalid_note_id"}

    current = backend.get_note(user_id, note_id=nid, with_version=True)
    if not isinstance(current, dict) or not current.get("ok"):
        refused: dict[str, Any] = {
            "ok": False, "error": str((current or {}).get("error") or "not_found"),
        }
        if isinstance(current, dict) and current.get("hint"):
            refused["hint"] = str(current["hint"])
        return refused

    note = dict(current.get("note") or {})
    is_repo_note = (
        current.get("target") == "repo"
        or bool(note.get("repo_name"))
        or bool(note.get("repo_path"))
    )
    if is_repo_note and is_admin is not True:
        return {"ok": False, "error": "not_found"}

    stored = current.get("stored_content")
    if isinstance(stored, str):
        # רק מחרוזת מחליפה את הגוף המפוענח; גוף שאינו מחרוזת (אף כותב אינו
        # שומר כזה) נשאר כפי ש-``_as_note`` הציג אותו, זהה לכלי הרשימה.
        note["content"] = stored

    out: dict[str, Any] = {"ok": True, "note": note}
    # היעד, בדיוק בארגומנטים שכלי הרשימה המתאים דורש — כמו פגיעת חיפוש;
    # ו-``version`` שנקרא באותה קריאה תחומה כמו הגוף.
    out.update({k: v for k, v in current.items() if k not in ("ok", "note", "stored_content")})
    if is_repo_note and backend.repo_path_orphaned(
        repo_name=str(note.get("repo_name") or ""), repo_path=str(note.get("repo_path") or "")
    ):
        out["orphaned"] = True
    return out


def list_note_versions(backend: Any, user_id: int, *, note_id: str) -> dict[str, Any]:
    """Previous revisions of a note — metadata only, newest first."""
    nid = _clean_note_id(note_id)
    if nid is None:
        return {"ok": False, "error": "invalid_note_id"}
    return backend.list_note_versions(user_id, note_id=nid)


def get_note_version(backend: Any, user_id: int, *, note_id: str, version: int) -> dict[str, Any]:
    """Read the content of one previous revision."""
    nid = _clean_note_id(note_id)
    if nid is None:
        return {"ok": False, "error": "invalid_note_id"}
    try:
        ver = int(version)
    except (TypeError, ValueError):
        return {"ok": False, "error": "invalid_version"}
    if ver < 1:
        return {"ok": False, "error": "invalid_version"}
    return backend.get_note_version(user_id, note_id=nid, version=ver)


def search_notes(
    backend: Any,
    user_id: int,
    *,
    query: str,
    limit: int | None = None,
    search_content: bool = False,
) -> dict[str, Any]:
    """Find sticky notes across all three targets (read-only).

    **שם כברירת מחדל; תוכן בבקשה מפורשת.** חיפוש השם נשען על
    ``user_title_idx``; הרחבתו לתוכן מוסיפה פרדיקט שאין עליו אינדקס —
    מונגו מתיר אינדקס טקסט אחד לכל אוסף, וזו החלטה חד-כיוונית שלא נשרפת
    כאן. הסריקה נשארת חסומה ל-``user_id`` ולכן אינה COLLSCAN.

    **הדגל קיים בגלל פתק בלי שם.** רוב הפתקים נכתבים בלי כותרת, ולכן היו
    בלתי-נראים לחיפוש לחלוטין — לא "קשים למציאה", אלא בלתי-ניתנים
    למציאה.

    **אורך השאילתה נבדק מול היעד.** תקרת ``MAX_NOTE_TITLE`` נגזרת מכך
    ששאילתה ארוכה משם אפשרי לעולם לא תתפוס דבר — נימוק שאינו חל על
    התוכן, שמגיע עד ``MAX_NOTE_CONTENT``. בדיקה אחת לשני מרחבים הייתה
    פוסלת חיפושים לגיטימיים בגוף הפתק.

    ``limit`` **נחתך ולא נדחה**: מספר גדול מדי הוא בקשה לרוחב, לא שגיאה.
    """
    from sticky_notes_target import MAX_NOTE_TITLE, canonical_title_text

    # **מחט לכל יעד, כי היעדים נשמרו אחרת.**
    #
    # שם עובר ``canonical_title_text`` בכתיבה: כיווץ רצפי רווחים ואיחוד
    # לשורה אחת. תוכן עובר ``_sanitize_note_text``, ש**משמר** את שניהם.
    # מחט אחת לשני הפרדיקטים שוברת בדיוק אחד מהם: מחט קנונית מפספסת
    # תוכן רב-שורתי, ומחט גולמית מפספסת שם שנשמר מכווץ — כלומר הדלקת
    # הדגל הייתה **מורידה** התאמות-שם במקום רק להוסיף התאמות-גוף. זה
    # בדיוק הכשל השקט ש-``repo_notes_filter`` מתעד: נכתב בצורה אחת,
    # מחופש בצורה אחרת.
    #
    # **בלי קיצוץ** באף מחט, כי אחריו בדיקת האורך שמתחת הייתה תמיד
    # שקרית: ``normalize_note_title`` כבר חתך ל-80.
    title_needle = canonical_title_text(query)
    content_needle = _sanitize_note_text(query).strip() if search_content else ""
    # מחט השם נבדקת מול תקרת השם; ארוכה ממנה — אין שם כזה, והענף מושמט
    # (בחיפוש-שם-בלבד זו שאילתה שלעולם לא תתפוס, ולכן שגיאה מפורשת).
    if len(title_needle) > MAX_NOTE_TITLE:
        if not search_content:
            return {"ok": False, "error": "query_too_long", "max": MAX_NOTE_TITLE}
        title_needle = ""
    if search_content and len(content_needle) > MAX_NOTE_CONTENT:
        return {"ok": False, "error": "query_too_long", "max": MAX_NOTE_CONTENT}
    # בדיקת הריקנות רצה **אחרי** ההשמטות, לא לפניהן: שאילתה שמחט-השם שלה
    # הושמטה (ארוכה מדי) ומחט-התוכן שלה התרוקנה בניקוי הייתה עוברת בדיקה
    # מוקדמת — ומפילה את בונה השאילתה על שתי מחטים ריקות במקום להיענות
    # ב-``empty_query``.
    if not title_needle and not content_needle:
        return {"ok": False, "error": "empty_query"}

    return backend.search_notes(
        user_id,
        query=title_needle,
        limit=_clamp(limit, 1, MAX_NOTE_SEARCH_RESULTS, DEFAULT_NOTE_SEARCH_RESULTS),
        search_content=bool(search_content),
        content_query=content_needle or None,
    )


def update_note(
    backend: Any,
    user_id: int,
    *,
    note_id: str,
    content: str | None = None,
    line: int | None = None,
    color: str | None = None,
    anchor_text: str | None = None,
    is_minimized: bool | None = None,
) -> dict[str, Any]:
    """Partial update of a sticky note by its id (in-place, no version history)."""
    nid = _clean_note_id(note_id)
    if nid is None:
        return {"ok": False, "error": "invalid_note_id"}

    fields: dict[str, Any] = {}
    if content is not None:
        clean = _sanitize_note_text(content).strip()
        if not clean:
            return {"ok": False, "error": "empty_content"}
        if len(clean) > MAX_NOTE_CONTENT:
            return {"ok": False, "error": "content_too_long", "max": MAX_NOTE_CONTENT}
        fields["content"] = clean
    if line is not None:
        line_i = _valid_note_line(line)
        if line_i is None:
            return {"ok": False, "error": "invalid_line", "min": 1, "max": MAX_NOTE_LINE}
        # מעבר לעיגון-שורה מנקה עוגני כותרת/sentinel — כמו הקליינט של הוובאפ
        fields.update({"line_start": line_i, "anchor_id": None, "line_end": None})
    if color is not None:
        # **ולא "נשמט בשקט"**, שהיה משאיר את הפתק בצבעו הישן ומחזיר ``ok``.
        # ``default=None`` כאן פירושו מחרוזת ריקה = "לא ביקשתי לשנות צבע";
        # ערך שאינו נפתר עוצר את העדכון **כולו**, ולכן שום שדה אחר באותה
        # קריאה אינו נכתב למחצה.
        color_s = _note_color_or_error(color, default=None)
        if isinstance(color_s, dict):
            return color_s
        if color_s:
            fields["color"] = color_s
    if anchor_text is not None:
        fields["anchor_text"] = _clean_anchor_text(anchor_text)
    if is_minimized is not None:
        fields["is_minimized"] = bool(is_minimized)

    if not fields:
        return {"ok": False, "error": "no_fields_to_update"}
    return backend.update_note(user_id, note_id=nid, fields=fields)
