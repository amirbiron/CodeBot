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
