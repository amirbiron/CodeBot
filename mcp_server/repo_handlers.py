"""Pure handlers for the admin-only repo-browser tools (Phase D).

Same contract as ``handlers.py``: plain functions, no MCP/Starlette imports,
clamped inputs, ``{"ok": False, "error": "..."}`` rejections. Server-side
defaults/maxima and the output byte budget follow the plan (FEATURE doc §13.4);
out-of-range values are **clamped** (the established ``_clamp`` pattern), never
rejected. The admin gate itself lives in the tool bodies (``require_admin``),
not here — handlers stay pure.
"""

from __future__ import annotations

from typing import Any

import pydantic_core

from .handlers import _clamp

REPOS_LIMIT_DEFAULT = 50
REPOS_LIMIT_MAX = 200
TREE_PER_PAGE_DEFAULT = 200
TREE_PER_PAGE_MAX = 1000
SEARCH_RESULTS_DEFAULT = 50
SEARCH_RESULTS_MAX = 100
# תקרת שורות ההקשר ב-``codekeeper_search_repo``. כל פגיעה גדלה פי ``2N+1``,
# ומול ``SEARCH_RESULTS_MAX`` ו-``OUTPUT_BYTE_BUDGET`` זו התקרה שמשאירה עמוד
# שלם בתקציב במקום להיחתך.
CONTEXT_LINES_MAX = 10
# עימוד האאוטליין. קבועים משלו ולא מיחזור של ``TREE_*``: רשומת סימבול
# נושאת שם מלא בנקודות ושתי שורות, ושוקלת יותר מנתיב. ``TREE_PER_PAGE_MAX``
# הוא 1000, ועמוד כזה של סימבולים היה חוצה את תקציב הפלט לבדו.
OUTLINE_PER_PAGE_DEFAULT = 100
OUTLINE_PER_PAGE_MAX = 500
OUTPUT_BYTE_BUDGET = 256_000

#: מתי המראה של שירות ה-MCP נמשכת, במשפט שהסוכן קורא. מקור אחד לשני מקומות:
#: תיאור הפרמטר ``ref`` בשלושת הכלים שמקבלים אותו (``server.py``), וההודעה של
#: ``ref_not_mirrored`` (``repo_backend.py``).
#:
#: **המשפט מתאר מדיניות שמוגדרת במקום אחר**, ולכן הוא נכון רק כל עוד היא לא
#: משתנה. הבעלים: ``handle_push_event`` ב-``webapp/routes/webhooks.py`` מסנכרן
#: רק push לענף הראשי, ו-``refresh_once`` ב-``mcp_server/repo_autosync.py``
#: מושך רק כשה-SHA של הענף הראשי במונגו שונה מזה שבמראה. שני טסטים מקבעים את
#: שני החצאים: ``test_the_refresh_note_matches_the_webhook_policy`` ב-
#: ``tests/test_mcp_ref_not_mirrored.py``, ו-``test_equal_shas_skip_fetch`` /
#: ``test_sha_drift_triggers_fetch`` ב-``tests/test_mcp_repo_autosync.py``. מי
#: שמשנה את המדיניות ורואה אותם נופלים — מעדכן גם את המשפט הזה.
MIRROR_REFRESH_NOTE = (
    "The mirror is refreshed only when the repo's default branch changes. "
    "A branch pushed after the last refresh is not in the mirror yet."
)


#: רווחי ההזחה של רמת קינון אחת בתשובה כפי שהיא נשלחת — ה-``indent=2`` ש-
#: ``_convert_to_content`` של ה-SDK מעביר ל-``pydantic_core.to_json`` (mcp 1.28.1).
#: :func:`wire_json` מסדרל בו, וכל עלות למטה נגזרת ממנו — כך שההזחה שנמדדת
#: וההזחה שנשלחת הן מספר אחד ולא שניים.
_WIRE_INDENT = 2


def wire_json(value: Any) -> bytes:
    """מה שה-SDK שולח על ``value`` — ``_convert_to_content`` ל-``dict`` (mcp 1.28.1).

    המדידה של :data:`OUTPUT_BYTE_BUDGET` **כפי שהתשובה נשלחת**, ולכן היא יושבת
    ליד התקציב ולא בכלי אחד: ``codekeeper_read_batch`` מודד בה את הבאץ', ו-
    ``docs_handlers`` את תשובת הסעיף. הצורה הזו לעולם אינה קטנה מ-``json.dumps``
    הדחוס (היא מוסיפה רק רווחים ושורות), ולכן תשובה שנכנסת בה נכנסת בשתיהן.
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
#: ב-4 רווחים, ולפניו פסיק ושורה. שני מקומות מודדים בדיוק את זה:
#: ``codekeeper_read_batch`` (פריט תחת ``items``) ו-``docs_handlers`` (פריט תחת
#: ``toc``/``suggestions``/``candidates``). בעלים אחד למדידה, שקוראים לו משניהם
#: (R6), במקום שני עותקים שיסחפו — ושלושת המספרים כאן נגזרים מאותה נוסחה של
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


def list_repos(backend: Any, *, limit: int = REPOS_LIMIT_DEFAULT) -> dict[str, Any]:
    return backend.list_repos(limit=_clamp(limit, 1, REPOS_LIMIT_MAX, REPOS_LIMIT_DEFAULT))


def list_repo_tree(
    backend: Any,
    *,
    repo: str,
    path: str | None = None,
    ref: str | None = None,
    page: int = 1,
    per_page: int = TREE_PER_PAGE_DEFAULT,
    include_stats: bool = False,
) -> dict[str, Any]:
    name = (repo or "").strip()
    if not name:
        return {"ok": False, "error": "missing_repo"}
    return backend.list_tree(
        repo=name,
        path=(path or None),
        ref=((ref or "").strip() or None),
        page=_clamp(page, 1, 10**9, 1),
        per_page=_clamp(per_page, 1, TREE_PER_PAGE_MAX, TREE_PER_PAGE_DEFAULT),
        byte_budget=OUTPUT_BYTE_BUDGET,
        include_stats=bool(include_stats),
    )


def file_target(repo: str, path: str) -> tuple[str, str] | dict[str, Any]:
    """‏``(repo, path)`` מנורמלים לקריאת קובץ — או הסירוב שהכלי מחזיר עליהם.

    **החלק הטהור של :func:`get_repo_file`, במקום אחד.** ``codekeeper_read_batch``
    מקבץ פריטים לפי הקובץ שהם קוראים לפני שהוא קורא אותו, ולכן הוא צריך את
    הנתיב המנורמל מראש; נרמול שני אצלו היה עותק של שתי השורות האלה (R6), ופריט
    ``" a.md"`` היה מקובץ אחרת ממה שהכלי הבודד היה קורא.
    """
    name = (repo or "").strip()
    file_path = (path or "").strip()
    if not name:
        return {"ok": False, "error": "missing_repo"}
    if not file_path:
        return {"ok": False, "error": "missing_path"}
    return name, file_path


def get_repo_file(
    backend: Any,
    *,
    repo: str,
    path: str,
    ref: str | None = None,
    lines: Any = None,
    outline: bool = False,
    symbol: str | None = None,
    page: int = 1,
    per_page: int = OUTLINE_PER_PAGE_DEFAULT,
    snapshot: Any = None,
) -> dict[str, Any]:
    """השער של ``codekeeper_get_repo_file``.

    ``snapshot`` מגיע רק מ-``codekeeper_read_batch`` (``RepoBackend.snapshot``),
    ומועבר ל-``backend.get_file`` **רק כשהוא קיים** — כך שהכלי הבודד קורא
    ל-backend בדיוק באותם ארגומנטים כמו לפני שהפרמטר נוסף.
    """
    target = file_target(repo, path)
    if isinstance(target, dict):
        return target
    name, file_path = target
    pinned = {"snapshot": snapshot} if snapshot is not None else {}
    return backend.get_file(
        repo=name,
        path=file_path,
        ref=((ref or "").strip() or None),
        lines=lines,
        outline=bool(outline),
        symbol=((symbol or "").strip() or None),
        page=_clamp(page, 1, 10_000, 1),
        per_page=_clamp(per_page, 1, OUTLINE_PER_PAGE_MAX, OUTLINE_PER_PAGE_DEFAULT),
        **pinned,
    )


def search_repo(
    backend: Any,
    *,
    repo: str,
    query: str,
    file_pattern: str | None = None,
    max_results: int = SEARCH_RESULTS_DEFAULT,
    context_lines: int = 0,
    regex: bool = False,
    case_sensitive: bool = False,
    include_vendored: bool = False,
) -> dict[str, Any]:
    """שער הקלט של ``codekeeper_search_repo``.

    **השאילתה אינה מקוצצת לפני החיפוש.** ה-``strip`` כאן מכריע ריקנות
    בלבד, והמחרוזת המקורית עוברת הלאה — חיפוש הזחה (``"    return"``)
    הוא שימוש אמיתי, וקיצוץ היה משנה בשקט את מה שביקשו. זו אותה הכרעה
    שכבר קיימת ב-:func:`mcp_server.handlers.file_query_error`, וכאן היא
    מיישרת את שני החיפושים לאותו חוזה.

    האורך נמדד על המחרוזת המקורית, ולכן ``" a"`` — רווח ואות — הוא
    שאילתה תקפה בת שני תווים.

    ``include_vendored`` הוא **בוליאני ולא נצמד**: קוד חיצוני מוחרג
    כברירת מחדל מהחיפוש ומהספירה, ו-``True`` מחזיר אותו. ההחרגה עצמה יושבת
    במנוע ולא כאן, כדי שגם החיפוש בוובאפ יקבל אותה.

    ‏``case_sensitive`` ברירת המחדל שלו ``False``, שזו ההתנהגות שהייתה כאן
    מאז ומתמיד (``git grep -i``). הוא מועבר הלאה **תמיד ובמפורש**, וזו לא
    קפדנות סגנון: שתי השכבות שמתחת מצהירות ברירות מחדל **הפוכות** —
    ``RepoSearchService.search`` הוא ``False`` ו-``search_with_git_grep``
    הוא ``True`` — ולכן ערך שנשען על ברירת מחדל משנה משמעות לפי השכבה
    שבה הוא נעצר.
    """
    name = (repo or "").strip()
    q = query or ""
    if not name:
        return {"ok": False, "error": "missing_repo"}
    if not q.strip() or len(q) < 2:
        return {"ok": False, "error": "query_too_short"}
    return backend.search(
        repo=name,
        query=q,
        file_pattern=((file_pattern or "").strip() or None),
        max_results=_clamp(max_results, 1, SEARCH_RESULTS_MAX, SEARCH_RESULTS_DEFAULT),
        byte_budget=OUTPUT_BYTE_BUDGET,
        context_lines=_clamp(context_lines, 0, CONTEXT_LINES_MAX, 0),
        regex=bool(regex),
        case_sensitive=bool(case_sensitive),
        include_vendored=bool(include_vendored),
    )
