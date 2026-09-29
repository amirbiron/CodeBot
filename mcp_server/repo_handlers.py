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

from .answer_size import ANSWER_TOO_LARGE, OUTPUT_BYTE_BUDGET, wire_json
from .handlers import _clamp, fit_line_range

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


#: ההפניה של קריאה מלאה שאינה נכנסת בתקציב. ``file.lines`` בסירוב הוא מספר השורות, ו-
#: ``outline`` הוא המפה שממנה בוחרים טווח — אותה שרשרת שתיאור הכלי מלמד.
_WHOLE_FILE_HINT = (
    "The whole file does not fit in one answer. Read it in parts with lines=[start, end] "
    "(file.lines is how many lines it has), or pass outline=true for a map of its "
    "definitions with their line ranges."
)
#: קובץ שכלי הסעיפים מגיש: ההפניה אליו, עם הארגומנטים המדויקים ב-``read_with_arguments``.
_WHOLE_FILE_SECTIONS_HINT = (
    " It is also served by the section tool: read_with and read_with_arguments call it "
    "for its heading map, then one section at a time."
)
#: שורה אחת שגם לבדה אינה נכנסת: אין טווח קטן יותר, אבל החיפוש מחזיר אותה כקטע חסום.
_LINE_TOO_LARGE_HINT = (
    "Line {line} alone does not fit in one answer. codekeeper_search_repo returns the "
    "lines that match a string, each clipped to a short snippet."
)


def fit_file_answer(read: dict[str, Any], *, repo: str, path: str, ref: str | None) -> dict[str, Any]:
    """התשובה של ``codekeeper_get_repo_file`` על קובץ, בתוך ``OUTPUT_BYTE_BUDGET`` בתים כפי שהיא נשלחת.

    ``read`` הוא מה ש-:func:`get_repo_file` החזיר. **התקציב חל כאן ולא ב-
    ``RepoBackend.get_file``**, כי אותה קריאה מזינה גם את כלי הסעיפים
    (``docs_handlers.load_document``) ואת פריטי הסעיף של ``codekeeper_read_batch``,
    שמפרסרים את הקובץ כולו — לא שולחים אותו. **ושני מקומות קוראים לפונקציה הזו,
    ורק הם:** גוף הכלי, ופריט קובץ בבאץ' (``read_batch._answer``) — כך שהתשובה של
    פריט קובץ נשארת זהה בית-בית לזו של הכלי הבודד. ``read`` עצמו אינו משתנה: הוא
    משותף בבאץ' לפריט קובץ ולפריט סעיף של אותו קובץ.

    * תשובה שאינה נושאת תוכן (אאוטליין, ``binary``, ``too_large``, סירוב) חוזרת כמו
      שהיא. האאוטליין מתאים את עצמו לתקציב במקום שבו הוא נבנה (``page_too_large``).
    * **טווח שאינו נכנס** נגמר מוקדם על גבול שורה (``handlers.fit_line_range``) —
      ``range.end`` האמיתי, ``range.truncated`` ו-``range.truncation_reason:
      "byte_budget"``, וממשיכים מ-``end + 1``. שורה ראשונה שגם לבדה אינה נכנסת —
      ``answer_too_large``.
    * **קריאה מלאה שאינה נכנסת** — ``answer_too_large`` עם ``bytes`` (התשובה שהייתה
      נשלחת, נמדדת), ``max``, ``file`` והפניה ל-``lines`` ול-``outline``. קובץ שכלי
      הסעיפים מגיש מקבל גם ``read_with``/``read_with_arguments`` אליו — אותם שמות של
      ``no_outline`` ושל ``item_too_large``, והארגומנטים נגזרים מהשער של אותו כלי
      (``docs_handlers.section_read_arguments``).

    עד #3460 קריאה מלאה נחסמה רק ב-500KB של המראה, ו-``docs/mcp-server.rst`` בקריאה
    מלאה יצא 299,038 בתים — מעל מה שהלקוח מקבל בלי לשמור לקובץ.
    """
    if read.get("ok") is not True or not isinstance(read.get("content"), str):
        return read
    rng = read.get("range")
    if isinstance(rng, dict):
        fitted, size = fit_line_range(
            read, text_paths=(("content",),), range_path=("range",), budget=OUTPUT_BYTE_BUDGET)
        if fitted is not None:
            return fitted
        return {"ok": False, "error": ANSWER_TOO_LARGE, "bytes": size, "max": OUTPUT_BYTE_BUDGET,
                "file": read.get("file"),
                "hint": _LINE_TOO_LARGE_HINT.format(line=rng.get("start"))}
    size = len(wire_json(read))
    if size <= OUTPUT_BYTE_BUDGET:
        return read
    refusal: dict[str, Any] = {"ok": False, "error": ANSWER_TOO_LARGE, "bytes": size,
                               "max": OUTPUT_BYTE_BUDGET, "file": read.get("file"),
                               "hint": _WHOLE_FILE_HINT}
    # עצל, כמו ב-``repo_backend._with_section_redirect``: ``docs_handlers`` מושך את
    # שני הפארסרים, וקריאה שנכנסת בתקציב אינה צריכה אותם.
    from . import docs_handlers

    # מנורמלים כמו ב-:func:`get_repo_file`, כדי שהכלי הבודד והבאץ' (שמקבץ לפי הנתיב
    # המנורמל) יפנו באותם ארגומנטים. ``read`` מוצלח אומר שהנרמול כבר עבר.
    target = file_target(repo, path)
    if isinstance(target, dict):
        return refusal
    arguments = docs_handlers.section_read_arguments(
        repo=target[0], path=target[1], ref=((ref or "").strip() or None))
    if arguments is not None:
        refusal["hint"] += _WHOLE_FILE_SECTIONS_HINT
        refusal["read_with"] = docs_handlers.SECTION_TOOL_NAME
        refusal["read_with_arguments"] = arguments
    return refusal


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
