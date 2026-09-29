"""גודל התשובה של כלי — כפי שהיא נשלחת, ומה הכלי מצהיר עליו ללקוח.

**מודול עלה, בכוונה.** הוא מייבא רק את ``pydantic_core``, ואף מודול ב-
``mcp_server`` אינו מיובא ממנו. עד שנוצר, המדידה והתקציב ישבו ב-
``repo_handlers``, ו-``handlers`` לא יכול היה לייבא אותם בלי ייבוא מעגלי
(``repo_handlers`` מייבא ממנו את ``_clamp``) — ולכן החזיק עותק משלו של התקציב,
ומדד את חיפוש ה-``query`` בצורה אחרת מזו שנשלחת (#3474). כאן יש בעלים אחד לשלושה
דברים, וכל מודול שמודד תשובה מייבא אותם מכאן:

* :data:`OUTPUT_BYTE_BUDGET` — התקציב, בבתים;
* :func:`wire_json` ועזרי המסגרת — המדידה, בצורה שה-SDK שולח;
* :data:`DECLARED_MAX_RESULT_CHARS` ו-:func:`declared_size_meta` — מה שהכלי
  מצהיר עליו ב-``tools/list``, והמפתח שבו.

**בתים שנמדדים, לא מוערכים.** ``_convert_to_content`` של ה-SDK הופך תשובת
``dict`` ל-``pydantic_core.to_json(result, fallback=str, indent=2)`` — בלוק טקסט
אחד (``mcp/server/fastmcp/utilities/func_metadata.py``, mcp 1.28.1). :func:`wire_json`
הוא בדיוק הקריאה הזו, ולכן מה שנמדד כאן הוא מה שהלקוח מקבל, בית-בית. מדידה של
``json.dumps`` הדחוס, של ``str(...)`` או של חלון התוכן לבדו אינה חסם: ההזחה,
ה-escaping והמעטפת מתווספים אחריה, ונמדד בפרויקט הזה שהפער מגיע לעשרות אחוזים.
"""

from __future__ import annotations

from typing import Any, Mapping

import pydantic_core

#: תקציב הבתים של תשובת כלי אחת, **כפי שהיא נשלחת** (:func:`wire_json`).
#:
#: כל כלי שמצהיר על :data:`DECLARED_SIZE_KEY` עומד בו בעצמו — חותך עם דגל וסיבה,
#: או מסרב עם הגודל, התקרה ודרך להמשיך — והרשת ב-``AdminAwareFastMCP.call_tool``
#: היא רק ההגנה האחרונה. המספר נבחר לפני #3460 כתקציב של ``codekeeper_read_batch``
#: ושל ``codekeeper_search_repo``, והוא עדיין הערך שכל התשובות האמיתיות שנמדדו
#: נכנסות בו בשוליים: הקובץ מ-#3460 הוא 80,803 בתים.
OUTPUT_BYTE_BUDGET = 256_000

#: ``truncation_reason`` של תשובה שתקציב הבתים — ולא תקרה שהקורא ביקש — קיצר.
#: מילה אחת לכל הכלים: עמוד של סעיף, מופעי ``query``, טווח שורות, חיפוש בריפו, ו-
#: ``unread_reason`` של ``codekeeper_read_batch`` (אוצר המילים ב-``docs/mcp-server.rst``).
BYTE_BUDGET_REASON = "byte_budget"

#: קוד הסירוב של תשובה שאינה נכנסת בתקציב, גם כשכבר אין בה מה לקצר. מילה אחת לכל
#: הכלים — סעיף ומפה (``docs_handlers``), קריאה מלאה וטווח של קובץ, רשימת פתקים, והרשת
#: שב-``AdminAwareFastMCP.call_tool`` — ולא קוד חדש לכל כלי. בכל אחד מהם הסירוב נושא
#: ``bytes`` (המספר שהושווה לתקציב) ו-``max``, ולכן ``bytes > max`` תמיד.
ANSWER_TOO_LARGE = "answer_too_large"

#: רווחי ההזחה של רמת קינון אחת בתשובה כפי שהיא נשלחת — ה-``indent=2`` ש-
#: ``_convert_to_content`` של ה-SDK מעביר ל-``pydantic_core.to_json`` (mcp 1.28.1).
#: :func:`wire_json` מסדרל בו, וכל עלות למטה נגזרת ממנו — כך שההזחה שנמדדת
#: וההזחה שנשלחת הן מספר אחד ולא שניים.
_WIRE_INDENT = 2


def wire_json(value: Any) -> bytes:
    """מה שה-SDK שולח על ``value`` — ``_convert_to_content`` ל-``dict`` (mcp 1.28.1).

    המדידה של :data:`OUTPUT_BYTE_BUDGET` **כפי שהתשובה נשלחת**. הצורה הזו לעולם
    אינה קטנה מ-``json.dumps`` הדחוס (היא מוסיפה רק רווחים ושורות), ולכן תשובה
    שנכנסת בה נכנסת בשתיהן.
    """
    return pydantic_core.to_json(value, fallback=str, indent=_WIRE_INDENT)


def _list_item_indent(depth: int) -> int:
    """ההזחה של פריט ברשימה שיושבת ``depth`` רמות מתחת לאובייקט העליון של התשובה.

    ``depth`` 0 — הרשימה היא ערך של האובייקט העליון (``toc``, ``items``), ולכן
    הפריט בעומק 2: אובייקט עליון, רשימה, פריט. ``depth`` 1 — הרשימה היא ערך של
    אובייקט שהוא עצמו ערך של העליון (``file.tags``), והפריט בעומק 3.
    """
    return _WIRE_INDENT * (2 + depth)


#: עלות של פריט שמקונן בתוך רשימה תחת מפתח בראש התשובה (``depth`` 0 של
#: :func:`list_item_cost`), בבתים **כפי שהתשובה נשלחת**: כל שורה פנימית שלו מוזחת
#: ב-4 רווחים, ולפניו פסיק ושורה. בעלים אחד למדידה, שכל רשימה בתשובה נמדדת בו
#: (R6), במקום עותקים שיסחפו — ושלושת המספרים כאן נגזרים מאותה נוסחה של
#: :func:`list_item_cost`, ולא מוקלדים לצידה.
LIST_ITEM_INDENT_BYTES = _list_item_indent(0)
#: פסיק, שורה, וההזחה של עומק 2 שלפני הפריט הבא ברשימה.
LIST_ITEM_FRAME_BYTES = len(",\n") + LIST_ITEM_INDENT_BYTES


def nonempty_list_bytes(depth: int = 0) -> int:
    """מה ש-``[]`` מוסיף ברגע שיש בו פריט אחד לפחות: ``[`` ... ``\\n`` והזחת הסגירה.

    הסוגר נסגר ברמה של המפתח שמחזיק את הרשימה — רמה 1 כשהרשימה בראש התשובה
    (``depth`` 0), רמה 2 כשהיא בתוך אובייקט מקונן (``depth`` 1).
    """
    return len("\n") + _WIRE_INDENT * (1 + depth)


#: :func:`nonempty_list_bytes` לרשימה בראש התשובה — ``\\n  ]`` במקום ``]``.
NONEMPTY_LIST_BYTES = nonempty_list_bytes(0)


def list_item_cost(item: Any, *, depth: int = 0) -> int:
    """כמה בתים ``item`` מוסיף לתשובה כשהוא פריט ברשימה — כפי שהיא נשלחת.

    ``depth`` הוא כמה רמות מתחת לאובייקט העליון יושבת הרשימה (ראו
    :func:`_list_item_indent`); ברירת המחדל, 0, היא רשימה בראש התשובה, והמספרים
    שלה הם :data:`LIST_ITEM_INDENT_BYTES` ו-:data:`LIST_ITEM_FRAME_BYTES`.

    הפריט נמדד לבדו בעומק 0 (:func:`wire_json`), וכל שורה פנימית שלו מקבלת את
    ההזחה של העומק שבו הוא יושב. שורה חדשה בתוך מחרוזת נכתבת כ-``\\n`` ולא כבית 10,
    ולכן כל בית 10 בטקסט הוא שורה של המבנה. הנוסחה **מחמירה בפסיק אחד** (לפריט
    הראשון ברשימה אין פסיק מוביל), ולכן סכום על רשימה הוא חסם עליון על מה שהפריטים
    באמת מוסיפים — מה שמאפשר להחליט "נכנס" בלי לבנות את התשובה המלאה.
    ``tests/test_mcp_read_batch.py`` משווה אותה לתשובות שנבנו באמת בעומק 0, ו-
    ``tests/test_mcp_file_sections.py`` בעומק 1.
    """
    text = wire_json(item)
    indent = _list_item_indent(depth)
    return len(text) + indent * text.count(b"\n") + len(",\n") + indent


def with_values(answer: dict[str, Any], values: Mapping[tuple[str, ...], Any]) -> dict[str, Any]:
    """עותק של ``answer`` שבו כל מסלול ב-``values`` מקבל את ערכו — **בלי לגעת במקור**.

    רק האובייקטים שלאורך המסלולים מועתקים, עותק רדוד לכל רמה, וכל השאר משותף. זה
    לא נימוס: ``file`` של ההקשר הוא אותו אובייקט בהקשר ובכל תשובה שנבנתה ממנו, ו-
    מוטציה שלו כאן הייתה משנה גם אותם. ברשימה בראש התשובה זה ``{**answer, key: value}``
    בדיוק — אותו מקום לכל מפתח קיים, ומפתח חדש בסוף — ולכן אותה תשובה בבית.

    כאן ולא ב-``docs_handlers``, שבו נולדה: כל מי שמתאים תשובה לתקציב בונה בה את
    התשובה המותאמת — הרשימות והסירובים שם, וטווח השורות ב-``handlers.fit_line_range``
    — ו-``handlers`` אינו יכול לייבא את ``docs_handlers`` (ייבוא מעגלי).
    """
    out = dict(answer)
    for path, value in values.items():
        node = out
        for key in path[:-1]:
            child = dict(node[key])
            node[key] = child
            node = child
        node[path[-1]] = value
    return out


def envelope_bytes(envelope: dict[str, Any]) -> int:
    """כמה בתים המפתחות של ``envelope`` מוסיפים לתשובה שנבנית סביב גוף אחר.

    נמדד ב-:func:`wire_json` על המעטפת עצמה — ההפרש בין ``{**envelope, "_": 0}``
    ל-``{"_": 0}`` — ולא נספר ביד. מי שחותך גוף אל :data:`OUTPUT_BYTE_BUDGET`
    שומר את זה בצד, כך שהתשובה כפי שהיא יוצאת נכנסת בתקציב, ולא רק הגוף שלפני
    העטיפה.
    """
    return len(wire_json({**envelope, "_": 0})) - len(wire_json({"_": 0}))


#: המפתח ב-``_meta`` של כלי ב-``tools/list`` שבו Claude Code קורא את תקרת התשובה
#: של הכלי, בתווים (``code.claude.com/docs/en/mcp.md``, "Raise the limit for a
#: specific tool", נקרא ב-2026-09-29): כלי שמצהיר עליו מקבל את הערך הזה על בלוקי
#: הטקסט שלו במקום ``MAX_MCP_OUTPUT_TOKENS`` (ברירת מחדל 25,000 טוקנים), ובלי
#: הצהרה תשובה גדולה נשמרת לקובץ ומוחלפת בנתיב (#3460).
DECLARED_SIZE_KEY = "anthropic/maxResultSizeChars"

#: התקרה הקשיחה של הלקוח על הערך המוצהר — "up to a hard ceiling of 500,000
#: characters" (אותו עמוד). ``AdminAwareFastMCP.add_tool`` מסרב לרשום כלי שמצהיר
#: על יותר מזה, כי הלקוח לא יכבד את מה שמעבר לה.
CLIENT_CEILING_CHARS = 500_000

#: הערך שכלי מצהיר עליו ב-:data:`DECLARED_SIZE_KEY`.
#:
#: **בתים כתקרת תווים, ובכוונה.** התשובה חסומה ב-:data:`OUTPUT_BYTE_BUDGET`
#: **בתים**, נמדדים בדיוק כפי שהיא נשלחת. בכל טקסט UTF-8 מספר התווים אינו עולה על
#: מספר הבתים — וגם לא מספר יחידות ה-UTF-16 שבהן JavaScript סופר אורך — ולכן
#: מספר הבתים הוא חסם עליון בטוח על התווים, והתשובה לעולם אינה עוברת את מה
#: שהוצהר. הפוך זה לא עובד: תקרה בתווים אינה אומרת כמה בתים יצאו, ותקרה על
#: מדידה דחוסה אינה אומרת כלום על מה שנשלח. טוקנים אינם נמדדים כאן בכלל.
DECLARED_MAX_RESULT_CHARS = OUTPUT_BYTE_BUDGET


def declared_size_meta() -> dict[str, int]:
    """ה-``meta`` שכלי מעביר ל-``mcp.tool(...)`` כדי להצהיר על תקרת התשובה שלו.

    **ההצהרה היא חלק מהרישום של הכלי**, ולא רשימת שמות שמוחזקת בצד: הרשת ב-
    ``AdminAwareFastMCP.call_tool`` קוראת את התקרה מה-``Tool.meta`` של הכלי שנקרא,
    ו-``FastMCP.list_tools`` שולח ללקוח את אותו ``meta`` בדיוק (``_meta=info.meta``,
    mcp 1.28.1). כלי שמצהיר חייב לעמוד בתקרה בעצמו — ראו :data:`OUTPUT_BYTE_BUDGET`.
    """
    return {DECLARED_SIZE_KEY: DECLARED_MAX_RESULT_CHARS}
