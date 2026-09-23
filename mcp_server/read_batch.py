"""``codekeeper_read_batch`` — כמה סעיפים וקבצים מהמראות, בקריאת כלי אחת (admin).

**למה הכלי קיים.** סוכן ריוויו חייב לקרוא לפני כל סבב את כל המסמכים
ב-``amir-bug-patterns`` שהטריגר שלהם נדלק על הדיף — בסבב שהוליד את הכלי
הזה היו אלה 16 קריאות. הן הגיעו לשרת אחת אחרי השנייה ולא יחד, במרווחים של
כשנייה, בזמן שהשרת עבד על כל אחת עשרות אלפיות שנייה: המחיר של סבב משולם
לכל קריאה, ורובו מחוץ לשרת. המספרים, ומאיפה הם, ב-``docs/mcp-server.rst``
(``codekeeper_read_batch``).

**מה פריט הוא, ודרך מה הוא עובר.** שני סוגים, וכל אחד עובר **בדיוק** דרך
ה-handler של הכלי שהוא משקף — אין כאן מסלול קריאה שני:

* פריט סעיף ``{"kind": "section", "path", "section"?, "repo"?}`` —
  ``docs_handlers.resolve_docs_target`` ← ``load_document`` ← ``answer_section``,
  החלקים ש-``docs_get_section`` עצמו עשוי מהם, עם ברירות המחדל שלו.
* פריט קובץ ``{"kind": "file", "repo", "path", "lines"?}`` —
  ``repo_handlers.get_repo_file``.

ולכן ה-``result`` של כל פריט זהה בית-בית למה שהכלי הבודד מחזיר על אותם
ארגומנטים, כולל תשובות הסירוב. כישלון של פריט אינו כישלון של הקריאה.

**commit אחד לכל ריפו.** ``RepoBackend.snapshot`` פותר את הענף הראשי של כל
ריפו פעם אחת ומקבע אותו ל-SHA, וכל הפריטים של אותו ריפו נקראים ממנו (ראו
``ReadSnapshot`` — וגם מה קורה כשהקיבוע נכשל).

**קריאה ופרסור אחד לכל קובץ, ומסמך אחד בזיכרון.** הפריטים מקובצים לפי
``(repo, path, lines)`` — הקובץ שהם קוראים — וכל קבוצה נקראת ומפורסרת פעם
אחת, כשהמעבר מגיע לפריט הראשון שלה. המסמך משתחרר כשהקבוצה נענתה, לפני
שהקבוצה הבאה נקראת. אין מטמון ואין פינוי: ההחלטה נגזרה מהסבב האמיתי
(``REVIEW_ROUND`` ב-``scripts/measure_read_batch.py``), שבו רק שני זוגות של
פריטים חלקו קובץ — ולכן מטמון עם תקרה ופינוי היה מנגנון שאין לו עבודה.

**שני סדרים, ואיך הם חיים יחד.** הקריאה מהמראה נעשית לפי הקבוצות, אבל
התשובה נבנית ונמדדת **לפי סדר הבקשה**: המעבר הולך על האינדקסים 0, 1, 2...
וכשהוא מגיע לפריט שהקבוצה שלו עוד לא נקראה, הוא קורא אותה — ועונה באותה
הזדמנות על כל הפריטים שלה, גם על אלה שיבואו בהמשך. תשובה כזו מחכה עד
שהמעבר יגיע לאינדקס שלה, ורק אז נכנסת לתקציב. כלומר התשובה היא תמיד
**רצף מתחילת הבקשה**: כשפריט אינו נכנס בתקציב הבתים, או שהגיע הדדליין לפני
שהקבוצה שלו נקראה, המעבר נעצר, והפריט הזה וכל מה שאחריו מדווחים
ב-``unread`` — גם פריט שכבר נענה כחלק מקבוצה, כי תשובה שכבר חושבה אבל
מופיעה אחרי החור לא תיכנס. זה מה שמאפשר ``unread_reason`` אחד: הוא אומר
למה המעבר נעצר, והלקוח שולח שוב את כל הרשימה שב-``unread``. ובזיכרון: מה
שכבר נכנס, ועוד כל תשובה שמחכה לתורה, אינם עוברים יחד את
``OUTPUT_BYTE_BUDGET`` — ראו :func:`_keep`, שזו התקרה על כל מה שנשמר בין
פריטים, ושמפנה תשובה שמחכה ברגע שתשובה חדשה לפניה דוחקת אותה החוצה.

**תקציב הבתים נמדד בצורה שה-SDK שולח.** ``pydantic_core.to_json(...,
indent=2)`` — ``_convert_to_content`` ב-``mcp/server/fastmcp/utilities/
func_metadata.py`` (mcp 1.28.1) הופך תשובת ``dict`` בדיוק לזה. הצורה הזו לעולם
אינה קטנה מהנוסחה של הריפו (``json.dumps`` בלי ``indent``): היא מוסיפה רק
רווחים ושורות. כך התשובה נכנסת ב-``OUTPUT_BYTE_BUDGET`` בשתי המדידות, ו-
:data:`MAX_RESULT_CHARS` יכול להבטיח ללקוח תקרה שהשרת באמת מקיים.

**מה הכלי אינו עושה:** הפריטים **אינם** נקראים במקביל — חוט אחד של מאגר
הקריאות, פריט אחרי פריט; ואין **חיתוך בתוך פריט** — פריט נכנס שלם או לא
בכלל. פריט שגדול מהתקציב לבדו מקבל ``item_too_large`` עם הגודל והתקרה.

**מה נשקל ואיפה.** ``AdminAwareFastMCP.call_tool`` שוקל באץ' כמספר הפריטים
שלו, לפני שעבודה כלשהי מתחילה, ובודק את התקרה ואת הרשימה הריקה **לפני**
השקילה — בקשה שלעולם לא תעבור מקבלת את הסיבה שלה ולא ``rate_limited``.
המודול הזה מייבא רק תלויות קלות ברמת המודול, כמו כל ``mcp_server``.
"""

from __future__ import annotations

import contextvars
import copy
import logging
import time
from typing import Annotated, Any, Literal, NamedTuple, Union

import pydantic_core
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from . import docs_handlers, repo_handlers
from .handlers import StrictLines
from .repo_handlers import OUTPUT_BYTE_BUDGET

logger = logging.getLogger(__name__)

TOOL_NAME = "codekeeper_read_batch"

#: כמה פריטים באץ' אחד יכול לשאת. **נגזר מהשימוש, ומוגבל מלמעלה במכסת הקצב.**
#:
#: הסבב שהוליד את הכלי קרא 15 מסמכים (``REVIEW_ROUND`` ב-
#: ``scripts/measure_read_batch.py``; PostHog, סשן ``ses_01a0cd48``,
#: 2026-09-23), והסוכן עצמו תיאר סבב כ"בדרך כלל 10 עד 20 קבצים". השיאים של
#: 30 הימים שלפני (45, 29, 29 קריאות בחלון של חמש דקות) פרושים על כמה תורות
#: של המודל, ואינם באץ' אחד. ומהצד השני: באץ' שוקל כמספר הפריטים שלו, ולכן
#: התקרה חייבת להיות קטנה מ-``DEFAULT_RATE_LIMIT_PER_MINUTE`` — אחרת באץ' מלא
#: היה נדחה תמיד. 20 מול 60 הם שלושה באצ'ים מלאים בדקה. כשהמכסה בפריסה נמוכה
#: יותר, :func:`item_cap` מוריד את התקרה איתה.
MAX_BATCH_ITEMS = 20

#: הדדליין של באץ', בשניות קיר, **מהרגע שהקריאה נכנסה ל-``call_tool``** — כולל
#: ההמתנה בתור של מאגר הקריאות, כי גם היא חלק מהשעון של הלקוח.
#:
#: **מול איזו מגבלה של הלקוח.** ל-Claude Code שתי מגבלות על קריאת כלי לשרת
#: HTTP (``code.claude.com/docs/en/mcp.md``, נקרא ב-2026-09-23): טיימר של 60
#: שניות שמכסה את הבקשה "עד הבית הראשון של התשובה", וחלון idle של חמש דקות
#: בלי תשובה ובלי הודעת התקדמות. השרת הזה עונה ב-SSE, וה-SDK שולח את הכותרות
#: לפני שהגוף רץ — ולכן היום הטיימר נסגר מיד, וחלון ה-idle הוא שמגביל. בתשובות
#: JSON (``json_response=True``) הבית הראשון הוא התשובה עצמה, ואז 60 השניות
#: מכסות את כל הריצה. **הדדליין נבחר מול המחמירה מבין השתיים.**
#:
#: **והנחה אחת שהחשבון נשען עליה:** הדדליין נבדק **בין פריטים בלבד** — פריט
#: שהתחיל רץ עד סופו — ולכן החריגה במקרה הגרוע היא הפריט היקר ביותר. היקר
#: ביותר שנמדד הוא Markdown עוין של 500KB: 2.3 שניות מעבד, שהן 46 שניות קיר
#: כשעשרה חוטים חולקים חצי מעבד. 10 + 46 = 56, מתחת ל-60. דדליין של 15 כבר
#: היה 61. הפירוט, והמדידה של הכותרות שנשלחות מיד — ב-``docs/mcp-server.rst``.
DEADLINE_SECONDS = 10.0

#: ``_meta["anthropic/maxResultSizeChars"]`` שהכלי מצהיר עליו ב-``tools/list``.
#:
#: **בתים כתקרת תווים, ובכוונה.** Claude Code שומר לקובץ כל תשובת כלי שעוברת
#: את הסף שלו (ברירת המחדל 25,000 טוקנים), ומחליף אותה בנתיב; כלי יכול להעלות
#: את הסף לעצמו עד 500,000 **תווים** (``code.claude.com/docs/en/mcp.md``, "Raise
#: the limit for a specific tool"). התשובה של הכלי הזה חסומה ב-
#: ``OUTPUT_BYTE_BUDGET`` **בתים**, נמדדים בדיוק כפי שהיא נשלחת (ראו את
#: ה-docstring של המודול). בכל טקסט UTF-8 מספר התווים אינו עולה על מספר
#: הבתים — וגם לא מספר יחידות ה-UTF-16 שבהן JavaScript סופר אורך — ולכן
#: מספר הבתים הוא חסם עליון בטוח על התווים, והתשובה לעולם אינה עוברת את מה
#: שהוצהר. תוספת ה-``indent=2`` אינה מתווספת כאן, כי היא כבר בתוך המדידה.
MAX_RESULT_CHARS = OUTPUT_BYTE_BUDGET

#: הסיבות ל-``unread`` — ממוחזרות מאוצר המילים של ``truncation_reason``
#: ב-``codekeeper_search_repo``, ולא שמות חדשים.
UNREAD_BYTE_BUDGET = "byte_budget"
UNREAD_TIMEOUT = "timeout"

#: לאן לשלוח פריט שגדול מהתקציב לבדו — הכלי הבודד שהפריט משקף.
_SINGLE_TOOL = {
    "section": "codekeeper_docs_get_section",
    "file": "codekeeper_get_repo_file",
}

#: רגע הכניסה ל-``AdminAwareFastMCP.call_tool``, שהדדליין נמדד ממנו.
#: ``asyncio.to_thread`` מעתיק את ה-``contextvars.Context`` אל חוט הקריאה
#: (``asyncio/threads.py``), ולכן הגוף רואה את מה ש-``call_tool`` קבע על הלולאה.
ENTERED_AT: contextvars.ContextVar[float | None] = contextvars.ContextVar(
    "codekeeper_read_batch_entered_at", default=None
)


def clock() -> float:
    """השעון היחיד שהדדליין קורא — ``time.monotonic``, שעון קיר שאינו זז אחורה.

    שעון קיר ולא זמן מעבד: הלקוח מוותר לפי שעון הקיר, ובמכסה של חצי מעבד
    שעשרה חוטים חולקים זמן הקיר גדול בהרבה מזמן המעבד. פונקציה ולא הפניה
    ישירה, כדי שטסט יחליף אותה במקום אחד ו-``call_tool`` והגוף יראו את אותו
    שעון.
    """
    return time.monotonic()


class SectionItem(BaseModel):
    """פריט סעיף — הארגומנטים של ``codekeeper_docs_get_section`` בלי הפרמטרים של העימוד."""

    model_config = ConfigDict(extra="forbid", strict=True)

    kind: Literal["section"]
    path: str
    section: str | None = None
    repo: str | None = None


class FileItem(BaseModel):
    """פריט קובץ — הארגומנטים של ``codekeeper_get_repo_file`` בלי ``ref`` ובלי האאוטליין."""

    model_config = ConfigDict(extra="forbid", strict=True)

    kind: Literal["file"]
    repo: str
    path: str
    lines: StrictLines | None = None


#: המאמת של פריט בודד. **נבנה בייבוא, ושלם כשהוא נבנה:** ``TypeAdapter.__init__``
#: בונה את ה-validator מיד אלא אם ``defer_build`` מוגדר, ו-``validate_python``
#: רק קורא ל-validator שנבנה (pydantic 2.12.3, ``pydantic/type_adapter.py``,
#: ``_init_core_attrs``) — כלומר השימוש הראשון אינו בונה כלום, וחוטים שמאמתים
#: במקביל אינם יכולים לראות אותו חצי-בנוי (K15).
_ITEM_ADAPTER: TypeAdapter[SectionItem | FileItem] = TypeAdapter(
    Annotated[Union[SectionItem, FileItem], Field(discriminator="kind")]
)

#: הסכימה שהלקוח רואה לפריט — **נגזרת משני המודלים שמאמתים אותו**, כך
#: שהחוזה המוצהר והאכיפה אינם יכולים להיפרד (R6). ``oneOf`` מקונן בתוך
#: ``properties`` נשלח ל-API כמות שהוא (``code.claude.com/docs/en/mcp.md``,
#: "Tool input schemas with a root-level combinator"), ואין בו ``$defs``/``$ref``
#: שאף כלי אחר בשרת הזה אינו מפרסם.
ITEM_JSON_SCHEMA: dict[str, Any] = {
    "oneOf": [SectionItem.model_json_schema(), FileItem.model_json_schema()]
}


def item_cap(per_minute: int) -> int:
    """כמה פריטים מותרים בבאץ' אחד מול מכסת קצב נתונה.

    :data:`MAX_BATCH_ITEMS`, או המכסה לדקה כשהיא קטנה ממנו — באץ' שמשקלו
    גדול מהמכסה לעולם לא היה עובר, והוא צריך לשמוע ``too_many_items`` ולא
    ``rate_limited`` עם זמן המתנה לשווא. ``0`` הוא מגביל כבוי (``ToolRateLimiter``),
    ואז נשארת רק התקרה של הכלי.
    """
    if per_minute > 0:
        return min(MAX_BATCH_ITEMS, per_minute)
    return MAX_BATCH_ITEMS


def refuse_items(items: Any, *, cap: int) -> dict[str, Any] | None:
    """הסירוב של הקריאה כולה על צורת ``items`` — או ``None`` כשאין מה לסרב.

    אותה פונקציה רצה ב-``call_tool`` לפני השקילה, ובגוף אחרי ``require_admin``,
    כדי ששני המקומות לא ינסחו את אותו כלל פעמיים. **ערך שאינו רשימה אינו
    נענה כאן:** ה-SDK מאמת את ``items`` מול ``list`` לפני שהגוף רץ, ומחרוזת
    כמו ``"U1,U3"`` נדחית שם בשגיאת הוולידציה הרגילה של כל כלי.
    """
    if not isinstance(items, list):
        return None
    if not items:
        return {"ok": False, "error": "missing_items"}
    if len(items) > cap:
        return {"ok": False, "error": "too_many_items", "count": len(items), "max": cap}
    return None


def weight_of(items: Any) -> int:
    """כמה יחידות קצב הקריאה עולה: מספר הפריטים, או 1 כשאין רשימה לספור.

    כל פריט הוא קריאה ופרסור אפשריים, ולכן הוא נספר כמו קריאת כלי. ערך
    שאינו רשימה ייפול בוולידציה של ה-SDK בלי לקרוא דבר, ולכן הוא עולה כמו
    כל קריאה אחרת.
    """
    if isinstance(items, list) and items:
        return len(items)
    return 1


class _Plan(NamedTuple):
    """מה שידוע על פריט אחרי השער הטהור, לפני כל קריאה מהמראה."""

    request: Any
    #: ``"section"``, ``"file"``, או ``None`` לפריט שאינו תואם לסכימה.
    kind: str | None
    #: ``DocsTarget`` לפריט סעיף, ``(repo, path)`` לפריט קובץ.
    target: Any = None
    #: הקובץ שהפריט קורא — ``(repo, path, lines)`` — או ``None`` כשהוא אינו קורא.
    key: tuple | None = None
    #: התשובה, כשהיא ידועה בלי לקרוא דבר (סירוב של השער).
    immediate: dict[str, Any] | None = None
    #: ``section`` של פריט סעיף ו-``lines`` של פריט קובץ, כפי שאומתו.
    section: str | None = None
    lines: list[int] | None = None


def _invalid_item(exc: ValidationError) -> dict[str, Any]:
    """פריט שאינו תואם לסכימה: איפה ומה, בלי להדהד את הערך שנשלח."""
    problems = [
        {"loc": list(err.get("loc") or ()), "msg": err.get("msg")}
        for err in exc.errors(include_url=False, include_context=False, include_input=False)
    ]
    return {"ok": False, "error": "invalid_item", "problems": problems}


def _plan(raw: Any) -> _Plan:
    try:
        item = _ITEM_ADAPTER.validate_python(raw)
    except ValidationError as exc:
        return _Plan(raw, None, immediate=_invalid_item(exc))
    if isinstance(item, SectionItem):
        docs_target = docs_handlers.resolve_docs_target(path=item.path, repo=item.repo)
        if isinstance(docs_target, dict):
            return _Plan(raw, "section", immediate=docs_target)
        return _Plan(raw, "section", target=docs_target, section=item.section,
                     key=(docs_target.repo, docs_target.path, None))
    file_target = repo_handlers.file_target(item.repo, item.path)
    if isinstance(file_target, dict):
        return _Plan(raw, "file", immediate=file_target)
    # **המפתח הוא כל ארגומנט שמשנה את מה ש-``get_file`` מחזיר**, ו-``lines`` הוא
    # גם מה שמכריע את תקרת הגודל: קריאה מלאה נשפטת מול 500KB, קריאת טווח מול
    # ``RANGE_READ_MAX_BYTES`` (``wants_slice`` ב-``RepoBackend.get_file``). פריט
    # סעיף הוא תמיד קריאה מלאה (``None`` כאן), ולכן הוא חולק קבוצה רק עם קריאה
    # מלאה — ולעולם אינו מפרסר טקסט שנקרא תחת התקרה של טווח. תקרת 500KB היא
    # ההגנה היחידה על הפרסור (``docs_handlers.load_document``).
    lines_key = tuple(item.lines) if item.lines is not None else None
    return _Plan(raw, "file", target=file_target, lines=item.lines,
                 key=(file_target[0], file_target[1], lines_key))


# ---------------------------------------------------------------------------
# מדידה — בצורה שה-SDK שולח
# ---------------------------------------------------------------------------

#: מה שכל פריט מוסיף סביב עצמו כשהוא בתוך ``"items": [...]``: פסיק, שורה,
#: וארבעה רווחים של שתי רמות הזחה (האובייקט העליון והרשימה).
_ENTRY_FRAME_BYTES = len(",\n    ")
#: ההזחה שכל שורה פנימית של פריט מקבלת כשהוא מקונן בעומק 2.
_NESTED_INDENT_BYTES = 4
#: ``"items": []`` הופך ל-``"items": [`` ... ``\n  ]`` כשיש בו פריט אחד לפחות.
_NON_EMPTY_LIST_BYTES = len("\n  ")


def _wire(value: Any) -> bytes:
    """מה שה-SDK שולח על ``value`` — ``_convert_to_content`` ל-``dict`` (mcp 1.28.1)."""
    return pydantic_core.to_json(value, fallback=str, indent=2)


def _entry_cost(entry: dict[str, Any]) -> int:
    """כמה בתים הפריט תופס בתשובה כפי שהיא נשלחת, כשהוא מקונן בתוך ``items``.

    פריט שנמדד לבדו כתוב בעומק 0; בתוך התשובה כל אחת מהשורות הפנימיות שלו
    מוזחת בארבעה רווחים נוספים, ולפניו פסיק ושורה חדשה. שורה חדשה בתוך
    מחרוזת נכתבת כ-``\\n`` ולא כבית 10, ולכן כל בית 10 בטקסט הוא שורה של
    המבנה. הנוסחה מחמירה בפסיק אחד (לפריט הראשון אין), ו-
    ``tests/test_mcp_read_batch.py`` משווה אותה לתשובות שנבנו באמת.
    """
    text = _wire(entry)
    return len(text) + _NESTED_INDENT_BYTES * text.count(b"\n") + _ENTRY_FRAME_BYTES


def _reserve(count: int) -> int:
    """המעטפת במקרה הגרוע, **לפני** שנכנס פריט אחד: כל האינדקסים ב-``unread``.

    ``unread`` בפועל הוא תמיד סיפא של הבקשה או חסר, ``count`` אינו עולה על
    מספר הפריטים, והסיבה הארוכה משתי הסיבות נמדדת — כך שהמעטפת האמיתית
    לעולם אינה גדולה מהשמורה.
    """
    worst = {
        "ok": True,
        "count": count,
        "items": [],
        "unread": list(range(count)),
        "unread_reason": max((UNREAD_BYTE_BUDGET, UNREAD_TIMEOUT), key=len),
    }
    return len(_wire(worst)) + _NON_EMPTY_LIST_BYTES


def _commit_of(result: dict[str, Any]) -> str | None:
    """ה-commit שהתוכן של הפריט בא ממנו, כשהתשובה נושאת כזה.

    שני המקומות שהכלים הבודדים כותבים אותו בהם: ``resolved_commit`` בראש
    תשובת סעיף, ו-``file.resolved_commit`` בתשובת קובץ. תשובה שלא נקרא בה
    תוכן (סירוב של השער, קובץ שלא נמצא) אינה נושאת commit, ואין מה להמציא לה.
    """
    commit = result.get("resolved_commit")
    if not isinstance(commit, str):
        file_meta = result.get("file")
        commit = file_meta.get("resolved_commit") if isinstance(file_meta, dict) else None
    return commit if isinstance(commit, str) and commit else None


def _entry(index: int, plan: _Plan, result: dict[str, Any], per_item_max: int) -> tuple[dict[str, Any], int]:
    """הפריט כפי שייכנס לתשובה, ומחירו — או ``item_too_large`` כשהוא גדול מדי לבדו.

    ``request`` הוא הפריט כפי שנשלח, ו-``resolved_commit`` מצטרף כשהתוכן בא
    מ-commit ידוע. פריט שגדול מ-``per_item_max`` לבדו אינו נחתך: התשובה שלו
    מוחלפת ב-``item_too_large`` עם הגודל שהיה לו, התקרה, והכלי הבודד שיקרא
    אותו. ורק כשגם זה אינו נכנס — כלומר הבקשה עצמה גדולה מפריט שלם — ההדהוד
    שלה נשמט.
    """
    entry: dict[str, Any] = {"index": index, "request": plan.request}
    commit = _commit_of(result)
    if commit is not None:
        entry["resolved_commit"] = commit
    entry["result"] = result
    cost = _entry_cost(entry)
    if cost <= per_item_max:
        return entry, cost

    too_large: dict[str, Any] = {"ok": False, "error": "item_too_large", "bytes": cost, "max": per_item_max}
    if plan.kind in _SINGLE_TOOL:
        too_large["read_with"] = _SINGLE_TOOL[plan.kind]
    entry = {"index": index, "request": plan.request, "result": too_large}
    cost = _entry_cost(entry)
    if cost <= per_item_max:
        return entry, cost
    entry = {"index": index, "result": too_large}
    return entry, _entry_cost(entry)


# ---------------------------------------------------------------------------
# קבוצה: קובץ אחד, קריאה אחת, פרסור אחד
# ---------------------------------------------------------------------------


def _load_group(backend: Any, snapshot: Any, plans: list[_Plan], indices: list[int]) -> tuple[Any, Any]:
    """הקריאה המשותפת של קבוצה: ``(read, loaded)``.

    ``read`` — תשובת ``get_repo_file`` כשיש בקבוצה פריט קובץ; פריטי קובץ באותה
    קבוצה זהים זה לזה (אותו ריפו, נתיב ו-``lines``), ולכן כולם מקבלים אותה.
    ``loaded`` — המסמך המפורסר כשיש בקבוצה פריט סעיף: מאותה קריאה כשיש גם
    פריט קובץ (``get_file`` באותם ארגומנטים שהכלי הבודד היה מעביר, ולכן אותה
    תשובה), ואחרת מקריאה משלו. **עותק** של ``read`` עובר לפרסור, כי
    ``document_from_read`` מוסיף לו שדות בכשל, ו-``read`` עצמו הוא תשובה של
    פריט קובץ שחייבת להישאר כמו שהיא.
    """
    first_file = next((j for j in indices if plans[j].kind == "file"), None)
    first_section = next((j for j in indices if plans[j].kind == "section"), None)
    read = None
    loaded = None
    if first_file is not None:
        plan = plans[first_file]
        read = repo_handlers.get_repo_file(
            backend, repo=plan.target[0], path=plan.target[1], lines=plan.lines,
            snapshot=snapshot,
        )
    if first_section is not None:
        target = plans[first_section].target
        if read is not None:
            loaded = docs_handlers.document_from_read(copy.deepcopy(read), target)
        else:
            loaded = docs_handlers.load_document(backend, target, snapshot=snapshot)
    return read, loaded


def _answer(plan: _Plan, read: Any, loaded: Any) -> dict[str, Any]:
    if plan.kind == "file":
        return read
    if isinstance(loaded, dict):
        return loaded
    return docs_handlers.answer_section(loaded, section=plan.section)


def _lower_bound(used: int, ready: dict[int, tuple[dict[str, Any], int]], index: int) -> int:
    """כמה בתים יהיו בתשובה לכל הפחות כשהמעבר יגיע ל-``index``.

    כל מה שכבר נכנס, ועוד כל תשובה מוכנה שממתינה לפני ``index`` — אם המעבר
    מגיע ל-``index`` בכלל, כולן נכנסו לפניו. פריטים שעוד לא נקראו רק מוסיפים,
    ולכן תשובה שאינה נכנסת מעל החסם הזה לא תיכנס לעולם. **זה חסם על מה שלפני
    ``index`` בלבד**, ולא על מה שנשמר: את זה אוכף :func:`_keep`.
    """
    return used + sum(cost for j, (_, cost) in ready.items() if j < index)


def _drop_from(ready: dict[int, tuple[dict[str, Any], int]], first: int) -> None:
    """מפנה כל תשובה שמחכה מ-``first`` והלאה — המעבר ייעצר לפניהן."""
    for later in [j for j in ready if j >= first]:
        del ready[later]


def _keep(
    ready: dict[int, tuple[dict[str, Any], int]],
    cut: set[int],
    used: int,
    index: int,
    entry: dict[str, Any],
    cost: int,
) -> None:
    """שומר את התשובה של ``index`` עד שהמעבר יגיע אליה — רק אם היא עוד יכולה להישלח.

    **האינווריאנט: מה שכבר נכנס, ועוד כל מה שמחכה לתורו, אינם עוברים יחד את
    ``OUTPUT_BYTE_BUDGET``.** זו התקרה על מה שהבאץ' מחזיק בין פריטים. בדיקה של
    תשובה רק מול מה שלפניה (:func:`_lower_bound`) אינה מספיקה לזה: קבוצה שנקראת
    עונה גם על פריטים רחוקים בבקשה, וכשהקבוצות נקראות בסדר הפוך לפריטים
    הרחוקים שלהן — סעיפים של עשרה קבצים ואחריהם עשרת הקבצים עצמם, מהאחרון
    לראשון — כל תשובה רחוקה נכנסת לבדה, ויחד הן פי כמה מהתקציב.
    ``tests/test_mcp_read_batch.py`` בונה בדיוק את זה.

    שני מקרים:

    * **התשובה לא תיכנס** — מה שלפניה, ועוד היא, כבר עוברים את התקציב.
      ``index`` נכנס ל-``cut``, וכל מה שמחכה אחריו מפונה.
    * **התשובה נכנסת** — ואז היא דוחקת כל מה שמחכה אחריה. התשובה הראשונה שכבר
      לא נכנסת נכנסת ל-``cut``, ומפונה יחד עם כל מה שאחריה.

    **ההכרעה לעולם אינה מוקדמת מדי.** פריטים שעוד לא נקראו רק מוסיפים לפני
    ``index``, ולכן תשובה שנחתכה כאן הייתה נעצרת גם במעבר עצמו: התשובה שהלקוח
    מקבל זהה לזו שהייתה נבנית בלי הפינוי. מה שהפינוי משנה הוא רק מה שנשאר
    בזיכרון עד שהמעבר מגיע. (תשובה לפריט שאחרי ``min(cut)`` אינה נבנית מלכתחילה
    — ``_run_group`` מדלג עליו.)
    """
    if _lower_bound(used, ready, index) + cost > OUTPUT_BYTE_BUDGET:
        cut.add(index)
        _drop_from(ready, index + 1)
        return
    ready[index] = (entry, cost)
    total = _lower_bound(used, ready, index) + cost
    for later in sorted(j for j in ready if j > index):
        total += ready[later][1]
        if total > OUTPUT_BYTE_BUDGET:
            cut.add(later)
            _drop_from(ready, later)
            return


def _run_group(
    backend: Any,
    snapshot: Any,
    plans: list[_Plan],
    key: tuple,
    indices: list[int],
    *,
    used: int,
    ready: dict[int, tuple[dict[str, Any], int]],
    cut: set[int],
    per_item_max: int,
) -> None:
    """קורא את הקבוצה ``key`` ועונה על כל הפריטים שלה, בסדר האינדקסים. המסמך משתחרר ביציאה."""
    repo, path = key[0], key[1]
    try:
        read, loaded = _load_group(backend, snapshot, plans, indices)
    except Exception:
        # גבול במכוון (החלטה 7): חריגה לא צפויה בקריאה של קבוצה אחת היא
        # ``internal_error`` לכל פריטיה, והקריאה כולה ממשיכה. הלוג הוא מה
        # שהמפעיל צריך — הכלי הבודד היה נופל על אותה חריגה בדיוק.
        logger.exception(
            "%s: reading %s:%s for items %s raised; answered internal_error",
            TOOL_NAME, repo, path, indices,
        )
        read, loaded = None, None
        failed = True
    else:
        failed = False

    for j in indices:
        if cut and j > min(cut):
            continue  # המעבר ייעצר לפניו — אין טעם לבנות תשובה שלא תישלח
        if _lower_bound(used, ready, j) >= OUTPUT_BYTE_BUDGET:
            cut.add(j)
            continue
        # בביטוי אחד, בלי משתנה מקומי שמחזיק את התשובה: תשובה ש-``_keep`` אינו
        # שומר משתחררת מיד, ולא נשארת בזיכרון עד שהאיבר הבא בלולאה נבנה לצידה.
        _keep(ready, cut, used, j, *_entry(
            j, plans[j], _item_result(plans[j], read, loaded, failed=failed, index=j, repo=repo, path=path),
            per_item_max,
        ))


def _item_result(
    plan: _Plan, read: Any, loaded: Any, *, failed: bool, index: int, repo: str, path: str
) -> dict[str, Any]:
    """התשובה של פריט אחד בקבוצה — או ``internal_error`` כשהקבוצה או הפריט נפלו."""
    if failed:
        return {"ok": False, "error": "internal_error"}
    try:
        return _answer(plan, read, loaded)
    except Exception:
        logger.exception(
            "%s: item %d (%s %s:%s) raised; answered internal_error",
            TOOL_NAME, index, plan.kind, repo, path,
        )
        return {"ok": False, "error": "internal_error"}


def read_batch(
    backend: Any,
    items: list[Any],
    *,
    item_cap: int,
    entered_at: float | None = None,
) -> dict[str, Any]:
    """הגוף של ``codekeeper_read_batch``, אחרי ``require_admin``.

    ``backend`` הוא ``RepoBackend`` — הכלי צריך ממנו את ``snapshot``, ושני
    ה-handlers שהפריטים עוברים בהם קוראים ממנו. ``entered_at`` הוא רגע הכניסה
    ל-``call_tool`` (:data:`ENTERED_AT`); בלעדיו — קריאה ישירה, מחוץ לשרת —
    הדדליין נמדד מתחילת הפונקציה.

    מחזיר ``{"ok": true, "count", "items": [...]}``, ורק כשמשהו לא נקרא גם
    ``unread`` (האינדקסים, סיפא של הבקשה) ו-``unread_reason``. ראו את
    ה-docstring של המודול על שני הסדרים, התקציב והדדליין.
    """
    if not isinstance(items, list):
        raise TypeError("items must be a list; the tool's schema guarantees one")
    refusal = refuse_items(items, cap=item_cap)
    if refusal is not None:
        return refusal

    started = entered_at if entered_at is not None else clock()
    deadline = started + DEADLINE_SECONDS
    snapshot = backend.snapshot()
    count = len(items)
    plans = [_plan(raw) for raw in items]
    reserve = _reserve(count)
    per_item_max = OUTPUT_BYTE_BUDGET - reserve

    groups: dict[tuple, list[int]] = {}
    group_of: dict[int, tuple] = {}
    for index, plan in enumerate(plans):
        if plan.key is not None:
            groups.setdefault(plan.key, []).append(index)
            group_of[index] = plan.key

    # כל תשובה נשמרת דרך ``_keep``, גם סירוב של השער: מה שנכנס ועוד מה שמחכה
    # לתורו אינם עוברים יחד את התקציב, ולכן מה שנשמר כאן תמיד ייכנס כשהמעבר
    # יגיע אליו — והמעבר למטה אינו צריך לבדוק את התקציב שוב.
    used = reserve
    ready: dict[int, tuple[dict[str, Any], int]] = {}
    cut: set[int] = set()
    for index, plan in enumerate(plans):
        if plan.immediate is not None:
            entry, cost = _entry(index, plan, plan.immediate, per_item_max)
            _keep(ready, cut, used, index, entry, cost)

    entries: list[dict[str, Any]] = []
    stopped_at: int | None = None
    reason: str | None = None
    for index in range(count):
        if index not in ready and index not in cut:
            # הדדליין נבדק כאן ורק כאן: לפני קריאה מהמראה. פריט שכבר נענה
            # (סירוב של השער, או חבר בקבוצה שכבר נקראה) נכנס גם אחרי הדדליין,
            # כי העבודה שלו כבר נעשתה.
            if clock() >= deadline:
                stopped_at, reason = index, UNREAD_TIMEOUT
                break
            key = group_of[index]
            _run_group(
                backend, snapshot, plans, key, groups[key],
                used=used, ready=ready, cut=cut, per_item_max=per_item_max,
            )
        if index in cut:
            stopped_at, reason = index, UNREAD_BYTE_BUDGET
            break
        entry, cost = ready.pop(index)
        entries.append(entry)
        used += cost

    answer: dict[str, Any] = {"ok": True, "count": len(entries), "items": entries}
    if stopped_at is not None:
        answer["unread"] = list(range(stopped_at, count))
        answer["unread_reason"] = reason
    return answer
