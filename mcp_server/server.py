"""FastMCP server wiring: tools + resources + the authenticated ASGI app.

``build_mcp`` registers the read-only tools against an injected ``Backend``.
``build_app`` returns a Starlette ASGI app (Streamable HTTP) wrapped with PAT
auth plus an unauthenticated ``/healthz`` endpoint for platform health checks.

Tools are defined as **sync** functions on purpose, and :class:`AdminAwareFastMCP`
moves each one onto a worker thread at registration — see
:func:`_offload_to_thread`. Read tools go to the loop's default executor via
``asyncio.to_thread`` — a pool this module installs at ASGI startup and sizes
from the container's **memory** quota (:func:`attach_read_pool`,
:func:`_read_pool_size`), not from ``os.cpu_count()``; write tools go to
:data:`_WRITE_POOL`, a pool of one worker, so exactly one write body runs at a
time and the queue hands them over in the order they arrived.

Until #3379 this docstring claimed the SDK ran sync tools on a worker thread by
itself. **It does not**, and that wrong belief is why nobody looked: measured
against ``mcp 1.28.1``, ``func_metadata.call_fn_with_arg_validation`` calls a
sync tool as ``return fn(**arguments_parsed_dict)`` — on the event loop, with no
``to_thread`` anywhere on the path. Keeping this paragraph accurate is not
housekeeping: the wrong version of it is the whole reason the bug survived.
"""

from __future__ import annotations

import asyncio
import contextlib
import contextvars
import functools
import inspect
import logging
import os
import pathlib
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Annotated, Any, NamedTuple

import pydantic_core
from mcp.server.fastmcp import Context, FastMCP
from mcp.types import CallToolResult, TextContent
from pydantic import Field
from mcp.server.transport_security import TransportSecuritySettings
from starlette.responses import JSONResponse
from starlette.routing import Route

from services import doc_sections
# The ceiling on one full-file read, and therefore on one parse — imported
# rather than copied so the read pool's memory budget follows it. The module
# imports only the standard library at top level (checked), so this does not
# pull anything heavy into the MCP process at import.
from services.git_mirror_service import MAX_FILE_SIZE_FOR_DISPLAY

from . import docs_handlers, handlers, read_batch, repo_handlers
from .backend import LEAN_NOTE_FIELDS
from .handlers import StrictInt, StrictLines
from .limits import (
    BODY_TOO_LARGE,
    DEFAULT_MAX_REQUEST_BYTES,
    DEFAULT_RATE_LIMIT_PER_MINUTE,
    RATE_LIMITED,
    BodySizeLimitMiddleware,
    ToolRateLimiter,
)
from .analytics import attach_shutdown_drain, instrument_mcp_server
from .auth import (
    PATAuthMiddleware,
    current_user_id,
    is_admin_user,
    require_admin,
    require_write,
)
from .primer import agent_primer_route

_INSTRUCTIONS = (
    "Access the current user's private code files and collections stored in "
    "CodeKeeper. Use codekeeper_search_code / codekeeper_list_files to find files "
    "(metadata only), and codekeeper_get_file to read full contents — or, when "
    "you only need one part of a file, codekeeper_get_file with lines=[start, "
    'end] for a range and query="..." for the lines that contain a string. Use '
    "codekeeper_save_file to create a NEW file — it refuses a name that is already "
    "taken — and codekeeper_edit_file / codekeeper_append_file to change an "
    "existing file, which is also cheaper because the whole file is not resent "
    "(write tools require write permission). "
    "Sticky notes live on a file, on a board (a surface that belongs to no file), or "
    "on a file inside a mirrored repository. "
    "codekeeper_list_notes reads a file's notes; codekeeper_list_boards and "
    "codekeeper_list_board_notes read boards. codekeeper_create_note / "
    "codekeeper_create_board_note / codekeeper_update_note add or change them (write "
    "permission; notes appear in the CodeKeeper web UI). "
    "codekeeper_search_notes finds a note across all three — by title, or with "
    "search_content=true also by body text, which is how untitled notes (most notes) "
    "are found — and codekeeper_get_note reads ONE note by its id: the way to reach a "
    "note a search found, and the read to repeat when codekeeper_note_str_replace "
    "answers conflict. "
    "All data is scoped to the authenticated user."
)

# תיאור הפרמטר ``lines``, משותף לשני הכלים שתומכים בקריאת טווח.
# מוגדר פעם אחת כדי ששני הכלים לא יתארו את אותה סמנטיקה בשתי גרסאות —
# אסימטריה בין הקבצים השמורים לבין הריפואים היא בדיוק מה שהפרמטר הזה
# נועד להימנע ממנו.
_RANGE_DOC = (
    "Pass lines=[start, end] to read only that range (1-indexed, both ends "
    "included) instead of the whole file; the reply then carries a `range` "
    "block with the file's total_lines so you know what you did not get. "
    "An `end` past the end of the file is clipped; a start past it is an error."
)

# תיאור הפרמטר ``outline``, ותיאור הפרמטר ``symbol``.
#
# **למה הם כאן ולא בתוך תיאור הכלי.** שני הבלוקים האלה ישבו בתוך
# ``description`` של ``codekeeper_get_repo_file``, והביאו אותו ל-2,482 תווים —
# פי 3.8 מהכלי השני בגודלו (652) ופי שמונה מהחציון (303). לקוח MCP שחותך
# תיאור ארוך חותך את **הסוף**, ונמדד בפועל שהתיאור הגיע לסוכן חתוך באמצע
# המשפט על RST ועל ``symbol=`` — כלומר שני פיצ'רים עבדו ואף לקוח לא קרא
# עליהם. תיאור פרמטר יושב ב-``inputSchema`` ולא ב-``description``, ולכן
# הוא אינו מתחרה על אותו תקציב.
#
# **וזו העברה, לא קיצור.** אף משפט לא נמחק: סך שלושת השדות גדול מהתיאור
# שקדם להם. כל משפט כאן נולד מבאג אמיתי ויש עליו טסט ב-
# ``tests/test_mcp_server_build.py`` — מחיקה הייתה מחזירה את מחלקת הכשל.
#
# .. warning::
#
#    **מה שנמדד הוא שהשרת שולח את התיאורים האלה במלואם** ב-``inputSchema``
#    (‏``mcp==1.28.1``, עם ריצת בקרה שבלי ``Field`` השדה חוזר ``None``) —
#    ולא מה שלקוח מציג מהם. נצפה לקוח שמקצר תיאור פרמטר לכ-120 תווים
#    בשורת סיכום, ובאותו לקוח תיאור כלי בן 2,482 תווים הגיע שלם. אם
#    יתברר שזו ההתנהגות הרווחת, הפיצול הזה אינו הפתרון והחלופה היא כלי
#    אאוטליין נפרד, שם הטקסט חוזר להיות תיאור כלי.
#
# הסיומות נקובות במפורש ולא רק "Python only": סוכן ששואל אם ``.pyi`` נתמך
# לא יכול היה לענות מהתיאור, בזמן ש-``docs/mcp-server.rst`` כן מפרט אותן.
# הרשימה נאכפת מול ``outline._SCANNERS`` בטסט, כדי ששפה שתתווסף לטבלה בלי
# שהתיאור יעודכן לא תהפוך לפיצ'ר שאף לקוח קורא לו.
#
# ``page/per_page`` נאמר כאן ראשון ובמפורש, כי הוא היה המשפט היחיד בתיאור
# שלא היה עליו אף טסט — ומשום כך נשמט בטיוטה הראשונה של הפיצול בלי שאף
# בדיקה שמה לב. עמוד ראשון שנראה כמו כל המפה הוא כשל שקט:
# ``OUTLINE_PER_PAGE_DEFAULT`` הוא 100, ולכן 486 הסימבולים שנמדדו על
# הקובץ הצפוף בקורפוס הם חמישה עמודים.


# תיאור פרמטר הצבע, **נגזר מהפלטה ולא מוקלד**. הפלטה חיה ב-
# ``sticky_notes_target.NOTE_COLORS``, וטקסט שמונה את הצבעים ביד היה
# מתיישן בשקט בצבע הבא שיתווסף — הסוכן היה ממשיך לראות רשימה חלקית בלי
# שאף בדיקה תשים לב. כאן הוא מתעדכן מאליו.
def _build_note_color_doc() -> str:
    from sticky_notes_target import NOTE_COLOR_ORDER

    names = ", ".join(NOTE_COLOR_ORDER)
    return (
        "Note colour: a palette id (" + names + ") or any CSS hex. A hex that "
        "matches a palette shade is stored as its id. Notes read back carry "
        "color (hex) and color_id (palette id, or empty). An invalid value is "
        "refused with the list of valid ids."
    )


_NOTE_COLOR_PARAM_DOC = _build_note_color_doc()

# תיאור הפרמטר ``include_content``, משותף לשני כלי הרשימה שמקבלים אותו
# (``codekeeper_list_notes`` ו-``codekeeper_list_board_notes``). קבוע אחד,
# מאותו נימוק שמאחורי ``_RANGE_DOC``: שני נוסחים לאותה סמנטיקה נסחפים.
#
# **למה הפרמטר קיים.** לוח של 18 פתקים חזר ב-64,691–66,416 תווים — כ-130KB,
# מתחת ל-``OUTPUT_BYTE_BUDGET`` של השרת, ומעל מה שלקוח מציג — כדי להגיע
# לפתק אחד של 4,997 תווים. סוכן בלי shell לא יכול היה לקרוא את הפתק בכלל.
# הזרימה שהפרמטר פותח היא רשימה קטנה ואחריה ``codekeeper_get_note``.
#
# **היחידה נקובה במפורש, ובבתים.** הכלל בפרויקט הוא בתים נמדדים על המטען
# האמיתי ולא ספירת תווים — בפתק עברי ההפרש הוא פי שניים (ראו
# ``backend._as_note_summary``).
#
# **רשימת השדות נגזרת מ-``LEAN_NOTE_FIELDS`` ולא מוקלדת**, מאותו נימוק שמאחורי
# ``_build_note_color_doc``: רשימה שמוקלדת ביד מתיישנת בשקט בשדה הבא
# שיתווסף, והסוכן ממשיך לקרוא רשימה חלקית בלי שאף בדיקה תשים לב.
_LEAN_NOTE_FIELDS_DOC = ", ".join(LEAN_NOTE_FIELDS)

_INCLUDE_CONTENT_PARAM_DOC = (
    "true, the default, returns every note with its content — exactly what the "
    "tool returned before this parameter existed. false returns each note without "
    "its body: only " + _LEAN_NOTE_FIELDS_DOC + ". content_bytes is the size of the "
    "stored body in UTF-8 BYTES (a Hebrew note is about twice its character count), "
    "which is exactly the size of the content codekeeper_get_note returns for it. "
    "Use false on a board or file you have not read yet — a full listing of a large "
    "board can exceed what a client shows — then read the notes you need one at a "
    "time with codekeeper_get_note by id."
)

_OUTLINE_PARAM_DOC = (
    "A map of the file instead of its content, paged with page/per_page — a "
    "long map runs to several pages, and page 1 alone is not the whole file. "
    "Python (.py, .pyi) gives functions and classes with dotted names "
    "(Class.method, outer.inner); HTML/Jinja templates (.html, .htm, .jinja, "
    ".jinja2, .j2) give flat names — {% block %} and {% macro %}, elements "
    "with an id as tag#id, and the definitions inside a <script> or <style> "
    "block, so a long block is a map and not just a boundary; CSS (.css) "
    "names each block by its selector or at-rule text, so @media "
    "(max-width: 768px) is findable with its own line range, and a minified "
    "file gives every block the one line it really sits on; RST (.rst) gives "
    "the heading tree with dotted names — the hierarchy comes from the order "
    "the adornment characters appear in that file, not from the character "
    "itself — plus every .. _label: target as its own one-line symbol named "
    "_label, so a broken :ref: is findable by the name it points at. Any "
    "other suffix returns status no_outline."
)

# ``symbol=`` ישב בתוך המשפט של פייתון, ומיד אחריו בא המשפט שאומר ש-HTML
# נותן שמות **שטוחים** — סוכן שקרא את זה קשר את הפילטר לשמות מנוקדים ולא
# ניסה אותו על ``@media``. נמדד שעל הקובץ הצפוף בקורפוס ``symbol="@media"``
# מצמצם 486 סימבולים בחמישה עמודים לשישה בעמוד אחד, ובכל זאת הפילטר נשכח
# בסשן שבו הוא תועד. הדוגמאות הן מה שגורם לסוכן להשתמש בזה, ולכן הן נבדקות
# ולא רק המילה ``symbol=``.
#
# **וההבטחה היא הכלה ולא תחילית.** ניסוח קודם אמר ש-``symbol="_"`` מחזיר
# "only the RST label targets", ונמדד שהוא מחזיר 29 תוויות **ו-133 שורות
# שאינן תוויות** ב-79 קבצים. הבטחה שהקוד אינו מקיים גרועה מהיעדר הבטחה.
#
# ה-escape ב-``services.backup\\_service`` הוא תו אמיתי בכותרת של עמוד
# autodoc, ולא קישוט: בלעדיו ``symbol="backup_service"`` נראה כאילו הוא
# אמור למצוא את העמוד, והוא אינו מוצא.
_SYMBOL_PARAM_DOC = (
    # ``full name`` נשמר במפורש מהניסוח הקודם ("symbol= filters on that full
    # name"), כי הוא נושא מידע: הסינון הוא על השם המנוקד השלם ולא על החלק
    # האחרון שלו, ולכן ``symbol="method"`` מוצא גם ``Class.method``.
    # ההשוואה משפט-משפט מול הנוסח הישן היא מה שהעלתה שהוא נשמט.
    "Narrows the outline to entries whose full name contains this substring, "
    "case-insensitively. It works on every language's names, not just the "
    "dotted Python ones: symbol=\"@media\" returns only the media queries "
    "with their ranges, and symbol=\"#\" only the names carrying an id. "
    "Matching is by substring in every language, so on RST symbol=\"_\" "
    "returns the .. _label: targets and also any heading containing an "
    "underscore; and an RST heading is the source text rather than the "
    "rendered text, so an autodoc page is named services.backup\\_service "
    "module and symbol=\"backup_service\" does not match it."
)

# תיאור פרמטר ה-``path`` של ``codekeeper_docs_get_section``, **נגזר מטבלת
# המדיניות ולא מוקלד לצידה**. אותו נימוק בדיוק שמעל ``_build_note_color_doc``:
# רשימה שנכתבת ביד מתיישנת בשקט בריפו הבא שיתווסף, והסוכן ממשיך לראות רשימה
# חלקית בלי שאף בדיקה תשים לב.
#
# **והגזירה מהטבלה הסטטית ולא מ-``MCP_DOCS_REPO``.** קריאת משתנה סביבה בזמן
# ייבוא היא ``import-time-side-effects``, ותיאור הכלי היה משתנה בין פריסות —
# כלומר שני לקוחות היו קוראים שני חוזים שונים לאותו כלי. מה שה-ENV קובע
# נאמר בתיאור במילים, בלי למנות ממנו.


def _build_docs_path_doc() -> str:
    parts = []
    for repo, policy in docs_handlers.DOCS_PATH_POLICY.items():
        root = policy.root
        where = f"under {root}/" if root else "at the repo root"
        parts.append(f"{repo} — {where}, {policy.suffix}")
    return (
        "Which file to read. Each repo decides where its docs live and in what "
        "format: " + "; ".join(parts) + ". Give a full path "
        "(docs/mcp-server.rst, bugbot-rules/race-toctou.md) or a bare slug "
        "(mcp-server, CRITICAL-PATTERNS) and the root and the suffix are "
        "filled in. A slug that already contains a slash is taken as written, "
        "so a file in a sub-directory of a repo rooted at docs/ needs its full "
        "path. Asking a repo for the format it does not serve is refused with "
        "suffix_not_allowed plus the list it does serve — it is never looked "
        "up silently under the other suffix. Which repos are reachable at all "
        "is MCP_DOCS_REPO, and its first entry is the default; a repo that "
        "env allows but this tool has no path rule for is refused with "
        "repo_not_configured. A path longer than "
        f"{docs_handlers.MAX_PATH_CHARS} characters is refused with "
        "path_too_long before anything reads it — the longest real path in "
        "any served repo is under 120 characters. A path that resolves outside "
        "the repo's docs root is refused with path_outside_root (the root is "
        "in the answer), and a repo this host has no mirror of with "
        "repo_not_mirrored — an operator matter, not a wrong file name."
    )


_DOCS_PATH_PARAM_DOC = _build_docs_path_doc()

#: תיאור הפרמטר ``section`` של ``codekeeper_docs_get_section``.
#:
#: **הפירוט יושב כאן ולא בתיאור הכלי, וזו הכרעה שנמדדה.** תיאור הכלי נחתך
#: אצל הלקוח, והתקרה ב-``tests/test_mcp_server_build.py`` חלה עליו בלבד —
#: כלומר טקסט שעובר לתיאור פרמטר יוצא מהספירה. זה אותו תיקון בדיוק שנעשה
#: ל-``codekeeper_get_repo_file`` כשהתיאור שלו הגיע ל-2,482 תווים ונחתך
#: בדיוק בקטעים על RST ועל ``symbol=``: **העברה, לא מחיקה.**
#:
#: **ומה שההעברה אינה מבטיחה, כי ההסתייגות כתובה באותו מקום שממנו לקחנו
#: את התקרה.** האזהרה ליד ``_TOOL_DESCRIPTION_MAX_CHARS`` מתעדת לקוח
#: שמקצר **תיאורי פרמטרים** לכ-120 תווים בשורת סיכום. המחרוזת כאן ארוכה
#: בהרבה, וסעיף הבקטיקים יושב הרחק אחרי התו ה-120 — כלומר אצל אותו לקוח
#: הוא אינו מגיע. ההעברה מוציאה את הטקסט מתקציב **תיאור הכלי**, ולא
#: מכל חיתוך שקיים בעולם. מכאן גם סדר המשפטים: מה שקריטי ראשון, כי אצל
#: לקוח שחותך רק הוא מגיע.
_SECTION_PARAM_DOC = (
    "The heading to return. Matching is full equality on the heading text "
    "after normalization (surrounding and repeated whitespace, dash "
    "variants, case) — a substring of a heading matches nothing. "
    "Two things surprise callers, so they are spelled out here. "
    "(1) IDENTIFIERS: when the query is itself an identifier — one to "
    "three letters followed by one to three digits, with an optional "
    "trailing dot, such as K11, K11., U3 or P3 — and full equality found "
    "nothing, the heading that OPENS with that identifier is returned "
    "(the identifier must be followed by a dot, a space, or the end of "
    "the heading). The identifier is parsed, not prefix-matched, so K1 "
    "returns K1 alone and never K10-K15, and a dot that starts a "
    "sub-number is not a boundary either: K11 never returns K11.1, and a "
    "sub-numbered heading is reachable by its full name only. "
    "An identifier that repeats in "
    "the file is ambiguous_section with candidates, like any duplicate "
    "heading — at most 50 of them, in document order, with "
    "candidates_truncated: true only when more were cut. A query that is "
    "not shaped like an identifier never takes "
    "this path. (2) BACKTICKS: headings are returned as raw source, so a "
    "heading written with ``literal`` markup needs those backticks in the "
    "query too — section=\"MissingGreenlet\" finds nothing when the "
    "heading reads ``MissingGreenlet``. The same holds on a Markdown page, "
    "where a heading written `K11` or **K11** needs those characters in "
    "the query as well. When a query misses, suggestions "
    "holds a heading that is close to what you typed, whenever the file has "
    "one. ONLY when nothing is close does it instead hold the identifiers "
    f"that DO exist in the file (at most "
    f"{doc_sections.MAX_IDENTIFIER_SUGGESTIONS}; "
    "suggestions_truncated says so when it was cut). So an identifier query "
    "can come back with a heading rather than with identifiers — do not read "
    "the field as always being identifiers."
)


# תיאור השדה ``description_age_versions``, משותף לשלושת הכלים שמחזירים אותו.
#
# **קבוע אחד ולא שלושה נוסחים**, מאותה סיבה שכל השאר כאן הם קבועים: תיאור
# שדה שנכתב שלוש פעמים נערך פעם אחת, ואז שני הכלים האחרים מבטיחים משהו
# אחר מהשלישי על אותו מספר בדיוק.
#
# **הנוסח נזהר משתי טעויות הפוכות.** האחת היא לקרוא לגיל גבוה "תיאור
# שגוי" — הוא אינו: עשר עריכות של שורת קוד לא הופכות תיאור לשגוי, ועריכה
# אחת גדולה כן יכולה, ולכן זה רמז לבדוק ולא פסק דין. השנייה היא לקרוא
# ל-``null`` "עדכני". הוא אומר "לא ידוע".
_DESCRIPTION_AGE_DOC = (
    " Files carry description_age_versions: how many versions the file has "
    "moved since its description was last set. 0 means it was set on the "
    "current version, null means unknown, and the field is absent when the "
    "file has no description. Read a high number as a hint to check, not as "
    "a verdict: ten small edits do not make a description wrong, one large "
    "edit can. It subtracts version numbers, so versions that went to the "
    "recycle bin inflate it a little. Refresh a stale description with "
    "codekeeper_update_file_description."
)


# תיאור הפרמטר ``query`` של ``codekeeper_get_file``.
#
# ``lines`` עונה על "תן לי את החלק הזה" ו-``query`` עונה על "איפה בקובץ זה
# יושב" — ולכן שני התיאורים נקראים יחד, והמשפט על השרשור ביניהם הוא העיקר:
# סוכן שקיבל ``line`` בלי לדעת מה לעשות איתו ימשוך שוב את הקובץ המלא, וזה
# בדיוק מה שהפרמטר בא למנוע. הדוגמה נקובה בצורתה המלאה ולא כ"טווח סביבו",
# כי ``line`` הוא מספר בודד ו-``lines`` דורש זוג.
def _build_query_doc() -> str:
    """התיאור שהסוכן קורא על ``query``.

    **פונקציה ולא קבוע, כדי שהקישור לקבועים יהיה בר-הפרכה.** המספרים
    נשתלים מ-``handlers`` ואינם נכתבים כטקסט, ולכן שינוי תקרה אינו יכול
    להשאיר את התיאור מבטיח מספר ישן. הצורה הזו היא מה שמאפשר לבדיקה
    להריץ את הבנייה עם קבועים אחרים ולראות שהטקסט זז — טענת "נשתל" שאי
    אפשר להפריך אינה שונה מטקסט קשיח שבמקרה נכון היום.
    """
    return (
        'Pass query="needle" to get the matching lines INSTEAD of the content, '
        "when you want one field or one rule out of a file and would otherwise "
        "pull the whole thing. The reply carries count, total, truncated and a "
        "results list whose entries have a `line` and a `snippet` — the same "
        "field names codekeeper_search_repo returns, and "
        f"context_lines=N (0-{handlers.QUERY_CONTEXT_LINES_MAX}) "
        "adds context_before / context_after around each hit exactly as it does "
        "there. Each `line` is the anchor for the next call: read around it with "
        "lines=[line - 20, line + 20], or lines=[line, line] for that one line. "
        "Matching is plain case-insensitive substring — no regex, no stemming, no "
        "word boundaries, so a special character is just a character. Zero "
        "matches is a success with an empty results list, never an error. At most "
        f"{handlers.QUERY_RESULTS_DEFAULT} hits come back by default, and "
        f"max_results raises that as far as {handlers.QUERY_RESULTS_MAX}; "
        "truncated tells you matches were left out, and total says how many there "
        "were in the file. Matching runs line by line, so a query containing a "
        "newline is refused as query_multiline instead of reported as zero "
        "matches — search one line, then read around the hit. Passing "
        "query and lines together is refused as query_and_lines — ask where, then "
        "read the range. context_lines and max_results describe how matches are "
        "shown, so passing either one without query is refused as "
        "context_lines_without_query or max_results_without_query."
    )


_QUERY_DOC = _build_query_doc()


# תיאור הכלי ``codekeeper_read_batch`` ותיאור הפרמטר ``items`` שלו.
#
# **בתיאור הכלי רק מה שסוכן חייב לדעת לפני שהוא קורא לו** — מה הוא מקבל,
# שכישלון פריט אינו מפיל את הקריאה, שכל פריט נספר מול מכסת הקצב, והתקרה.
# כל השאר ב-``items``, מאותו נימוק שמעל ``_OUTLINE_PARAM_DOC``: תיאור כלי
# נחתך אצל הלקוח, ו-``tests/test_mcp_server_build.py`` אוכף את התקרה שלו.
#
# **והמספרים נשתלים מהקבועים ולא מוקלדים** — פרוזה שרצה בזמן ריצה נבנית
# מהקבוע עצמו (``prose-restates-code-fact``), כמו ``MAX_PATH_CHARS`` בתיאור
# הנתיב של ``codekeeper_docs_get_section``.
def _build_read_batch_description() -> str:
    return (
        "[Admin] Read many documentation sections and repo files in ONE call "
        "instead of one call each — e.g. every pattern a review round must read. "
        "`items` is a list; each item is {kind: \"section\", path, section?, repo?} "
        "(the arguments of codekeeper_docs_get_section) or {kind: \"file\", repo, "
        "path, lines?} (those of codekeeper_get_repo_file). Answers come back in "
        "request order as {index, request, result}, and each `result` is exactly "
        "what that single tool returns for the same arguments, errors included — "
        "a missing file or section fails only its own item. Each repo is read at "
        "ONE commit for the whole call. Every item counts as one call against the "
        "per-minute rate limit, and a batch holds at most "
        f"{read_batch.MAX_BATCH_ITEMS} items. Items are read one after another, "
        "never in parallel, and never cut: an item bigger than a whole answer may "
        "be gets item_too_large, and items that did not fit or were not reached "
        "in time are listed in `unread` with `unread_reason` — send those again. "
        "The `items` parameter has the details."
    )


def _build_read_batch_items_doc() -> str:
    return (
        "The items to read, in the order the answers should come back. A SECTION "
        "item {\"kind\": \"section\", \"path\", \"section\", \"repo\"} reads like "
        "codekeeper_docs_get_section with only those arguments: path and repo "
        "mean what they mean there (repo defaults to the first MCP_DOCS_REPO "
        "entry), no section returns the page's table of contents, and paging "
        f"stays at that tool's defaults (max_chars {docs_handlers.MAX_CHARS_DEFAULT}, "
        "offset 0) — page a longer section with codekeeper_docs_get_section "
        "itself. A FILE item {\"kind\": \"file\", \"repo\", \"path\", \"lines\"} "
        "reads like codekeeper_get_repo_file with those arguments; without lines "
        "it is the whole file. Items take no ref: every repo is read at its "
        "default branch, pinned to one commit for the whole call, and an item "
        "whose answer came from a commit carries it as resolved_commit. Any other "
        "key, or a value of the wrong type, answers invalid_item with the "
        "problems, for that item only. The whole answer is at most "
        f"{repo_handlers.OUTPUT_BYTE_BUDGET} bytes as sent: items fill it in "
        "request order, the first one that does not fit stops the answer, and it "
        "and every item after it are listed in unread with unread_reason "
        "byte_budget. An item larger than that on its own answers item_too_large "
        "with its bytes, the max, and read_with — the single tool to read it "
        "with (a file item can narrow itself with lines). Nothing is read later "
        f"than {read_batch.DEADLINE_SECONDS:g} seconds after the server received "
        "the call: the items not reached by then are listed in unread with "
        "unread_reason timeout. Duplicate items are allowed, and items that read "
        "the same file share one read and one parse. A batch of N items costs N "
        "calls of the per-minute rate limit, decided before anything is read; "
        f"more than {read_batch.MAX_BATCH_ITEMS} items (fewer where that limit is "
        "lower) is refused as too_many_items, and an empty list as missing_items."
    )


_READ_BATCH_DESCRIPTION = _build_read_batch_description()
_READ_BATCH_ITEMS_DOC = _build_read_batch_items_doc()

# Shared annotations: every tool here is a non-destructive, idempotent read over
# the user's own bounded data store (service-prefixed to avoid cross-connector
# collisions on generic names like get_file / list_files).
_READ_ONLY_TOOL = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": False,
}

# File-write tools (save/edit/append/create-note). These saves are append-only
# or additive (a file update creates a new version and never overwrites), so
# they are non-destructive; not idempotent because repeating one adds another
# version/note each time.
_WRITE_TOOL = {
    "readOnlyHint": False,
    "destructiveHint": False,
    "idempotentHint": False,
    "openWorldHint": False,
}

# In-place update: overwrites a stored value rather than appending a version.
# Idempotent (same input twice ⇒ same final state). Two tools carry it —
# ``codekeeper_update_note`` and ``codekeeper_update_file_description`` — and
# ``destructiveHint`` is ``True`` for each for a *different* reason:
#
# - **פתק:** ``destructiveHint`` נשאר ``True`` גם אחרי שנוספה היסטוריה.
#   השחזור חסום ל-``NOTE_VERSION_RETENTION`` גרסאות אחרונות, ולכן אחרי
#   מספיק עריכות המקור נדחף החוצה — כלומר אובדן עדיין אפשרי. ההנחיה
#   ללקוח מתארת את המקרה הגרוע, לא את הרגיל.
# - **תיאור קובץ:** אין היסטוריה **בכלל**. העדכון הוא ``$set`` על מסמך
#   הגרסה האחרונה ואינו יוצר גרסה, ולכן התיאור הקודם נעלם ברגע הכתיבה
#   ואינו ניתן לשחזור משום מקום. כאן ``True`` אינו המקרה הגרוע אלא המקרה
#   היחיד.
#
# כלומר הערכים משותפים והנימוק אינו — ולכן הוא כתוב לשניהם ולא לאחד.
_UPDATE_IN_PLACE_TOOL = {
    "readOnlyHint": False,
    "destructiveHint": True,
    "idempotentHint": True,
    "openWorldHint": False,
}

# מצא-והחלף בפתק: דורס כמו ``_UPDATE_IN_PLACE_TOOL``, אבל **אינו
# אידמפוטנטי** — וזה נמדד, לא הונח. ``_apply_edit`` על גוף ``"a"`` עם
# ``old="a"``/``new="aa"`` ו-``replace_all`` נותן ``"aa"`` ← ``"aaaa"`` ←
# ``"aaaaaaaa"``: כל קריאה חוזרת משנה את המצב שוב. גם בלי ``replace_all``
# הקריאה השנייה אינה no-op אלא ``no_match``.
#
# ההבדל אינו סמנטי בלבד: ``idempotentHint`` שגוי מזמין לקוח לנסות שוב
# אחרי timeout, וניסיון חוזר כאן מכפיל את ההחלפה על גוף שכבר הוחלף.
_REPLACE_IN_PLACE_TOOL = {
    "readOnlyHint": False,
    "destructiveHint": True,
    "idempotentHint": False,
    "openWorldHint": False,
}

# Admin-only repo-browser tools (Phase D). Registered ONLY when a repo_backend
# is supplied — they read the mirror.
_REPO_BROWSER_TOOLS = frozenset(
    {
        "codekeeper_list_repos",
        "codekeeper_list_repo_tree",
        "codekeeper_get_repo_file",
        "codekeeper_search_repo",
        # אדמין **בהחלטה ולא בירושה**: פריטי הסעיף שלו משקפים כלי ציבורי,
        # אבל הצורך נולד מסוכן הריוויו של האדמין, פריטי הקובץ ממילא דורשים
        # אדמין, ומשטח ציבורי שמכפיל עלות פרסור בקריאה אחת אינו נחוץ היום.
        read_batch.TOOL_NAME,
    }
)

# Admin-only repo *note* tools. Also admin-gated, but registered ALWAYS: a note
# lives in ``sticky_notes`` and needs only the notes backend. That difference is
# exactly why the set is split — a single set could not express both "hidden
# from non-admins" and "registered unconditionally".
_REPO_NOTE_TOOLS = frozenset(
    {
        "codekeeper_list_repo_notes",
        "codekeeper_list_repo_note_paths",
        "codekeeper_create_repo_note",
    }
)

# What AdminAwareFastMCP hides from tools/list for non-admins — but hiding is UX
# only, NOT access control: every one of these also calls require_admin(ctx) in
# its body.
_ADMIN_TOOLS = _REPO_BROWSER_TOOLS | _REPO_NOTE_TOOLS


logger = logging.getLogger(__name__)


#: The pool the write tools run on. One worker, so exactly one write body is in
#: flight at a time — the ordering the tools had while every body sat on the
#: event loop, and which #3379 would otherwise have taken away. Claude Code does
#: send tool calls in parallel, so that is a live case and not a thought
#: experiment.
#:
#: **Why a pool and not a lock.** The first version of this took a
#: ``threading.Lock`` inside the worker thread. That kept writes mutually
#: exclusive but cost two things, both measured afterwards. A writer waiting on
#: the lock still occupied a slot in the loop's single default executor, so once
#: enough writes were in flight the *reads* queued behind them — the class of
#: failure this whole change exists to remove, moved from the loop to the pool.
#: And a lock grants in no defined order, so above that executor's size the
#: writes themselves finished out of the order they were sent in, which is the
#: one property the lock was there to restore.
#:
#: A pool of one worker gives both back without a lock at all. A waiting write
#: sits in this pool's queue instead of holding a thread the readers need, and
#: ``ThreadPoolExecutor`` feeds its worker from a ``queue.SimpleQueue``
#: (CPython ``concurrent/futures/thread.py``), so the worker takes them in
#: submit order.
#:
#: **The price, said plainly.** One queue means writes by *different* users wait
#: for each other, and a write body is seconds long. Reads never wait for a
#: write — they keep going to ``asyncio.to_thread`` and the shared executor.
#: Narrowing this to a queue per user is a real option; it is not this change,
#: and :data:`_SLOW_WRITE_QUEUE_WAIT` is what will say whether it is needed.
#:
#: **It is not a substitute for atomic writes, and must not be read as one.**
#: The check-then-act gaps in the write path (version allocation in
#: ``save_code_snippet``, ``update_note`` without ``expected_content``) are
#: races against the **bot and the webapp**, which run in other processes
#: entirely and never touch this queue. A queue inside one process cannot close
#: a cross-process race. It closes exactly the window this change would
#: otherwise have opened inside the MCP process, no more. The real fix — a
#: unique index with retry, plus conditional update returning ``conflict`` — is
#: tracked separately.
#:
#: **What cancellation does to a queued write — measured, both ways.** A write
#: that is cancelled while still waiting its turn **never runs**: asyncio
#: cancels the underlying ``concurrent.futures.Future`` through
#: ``_chain_future``, and ``_WorkItem.run`` checks
#: ``set_running_or_notify_cancel()`` before it calls anything. A write that is
#: cancelled **after** its body started runs to completion regardless — a
#: synchronous body cannot be interrupted, on a thread or on the loop — and the
#: caller simply stops waiting for it. Both were measured against this code, not
#: read off the documentation. The practical consequence is worth stating: a
#: client that times out and retries can have the first write still land, so the
#: retry is a second write and not a replacement for the first.
#:
#: **At shutdown the in-flight write finishes.** ``ThreadPoolExecutor`` worker
#: threads are not daemons and the interpreter joins them on the way out, so a
#: deploy that stops the process waits for the write that is running rather than
#: cutting it in half. A deep queue therefore delays shutdown; that is the right
#: trade for a write path, and it is a property worth knowing before someone
#: widens the queue.
#:
#: **Built at import, not lazily.** A lazily built shared resource has to
#: publish a guard and a value, and whoever arrives between the two gets the
#: empty one; building it here removes that shape instead of guarding against
#: it.
#:
#: **Do not import this module into a gevent process.** After
#: ``monkey.patch_all`` a ``ThreadPoolExecutor`` produces greenlets rather than
#: OS threads (``docs/observability/asyncio-loop-safety.rst``), and this queue
#: would stop being a thread boundary at all. The MCP service runs under
#: uvicorn, and the gevent webapp reaches ``mcp_server`` only through
#: ``oauth_identity`` and ``token_store`` — neither of which imports this
#: module. That was checked, and it is an assumption a future import can break.
_WRITE_POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mcp-write")

#: How long a write may wait for the queue before the wait is worth a WARNING.
#:
#: Picked against this service's own numbers rather than a round figure. A
#: ``save_file`` body ran 7.5s at p95 when this was set (before the service
#: moved to Frankfurt, next to Mongo, on 2026-09-16), so a threshold below one
#: whole body would fire every time two writes from the same agent arrive
#: together — the ordinary case, and an alert that fires on the ordinary case
#: is noise. Past this, the caller waited for more than one complete write
#: ahead of it, which is the shape of a queue that is not draining rather than
#: of a busy moment. **The 7.5s figure is stale:** the Frankfurt service's logs
#: (2026-09-16 to 2026-09-21) show ``ran`` between 0.012s and 1.993s over 30
#: writes, so today the threshold sits well above five whole bodies — still a
#: queue that is not draining, and not worth lowering until a slow write shows
#: up in those logs.
_SLOW_WRITE_QUEUE_WAIT = 10.0

#: ``FastMCP.add_tool``'s own signature, read once at import so that the
#: position of ``annotations`` is never a number written down here.
_ADD_TOOL_SIGNATURE = inspect.signature(FastMCP.add_tool)


def _cpu_budget() -> str:
    """What the container is actually allowed, as opposed to what Python sees.

    ``os.cpu_count()`` is the machine's CPU count, and CPython says so in as
    many words: *"This number is not equivalent to the number of CPUs the
    current process can use."* Inside a container it is the host's, while the
    service may be allowed a fraction of one core — and until #3391 the read
    pool was sized from the former. Printing the quota beside it is what turned
    that gap from a suspicion into a number, and it stays on the capacity line
    because the quota is still what the pool's threads share.

    cgroup v2 keeps it in ``cpu.max`` as ``"<quota|max> <period>"``; v1 splits
    it across two files, with ``-1`` meaning unlimited. Neither is guaranteed to
    exist, and reading them is best effort: this runs during startup, and a
    missing or unreadable file must not be the reason a deploy fails.
    """
    try:
        raw = pathlib.Path("/sys/fs/cgroup/cpu.max").read_text().split()
        quota, period = raw[0], raw[1]
        if quota == "max":
            return "cgroup v2: unlimited"
        return f"cgroup v2: {int(quota) / int(period):.2f} cpu"
    except (OSError, ValueError, IndexError):
        pass
    try:
        quota = int(pathlib.Path("/sys/fs/cgroup/cpu/cpu.cfs_quota_us").read_text())
        period = int(pathlib.Path("/sys/fs/cgroup/cpu/cpu.cfs_period_us").read_text())
        if quota < 0:
            return "cgroup v1: unlimited"
        return f"cgroup v1: {quota / period:.2f} cpu"
    except (OSError, ValueError, ZeroDivisionError):
        return "unavailable"


def _mib(n: int) -> str:
    """Bytes as mebibytes with one decimal — the unit Render's plan names use.

    Not ``webapp/size_format.py`` on purpose: that formatter prints decimal
    ``KB``/``MB`` for UI text and wraps the value in bidi isolation marks, which
    a log line must not carry; this one prints binary ``MiB``, the unit the
    plan and the cgroup limit are stated in.
    """
    return f"{n / (1024 * 1024):.1f}MiB"


#: The value at or above which a cgroup v1 memory limit means "no limit".
#:
#: v2 says it in a word — ``memory.max`` reads ``max`` — but v1 has no word
#: for it: ``memory.limit_in_bytes`` is reset to unlimited by writing ``-1``
#: (``Documentation/admin-guide/cgroup-v1/memory.rst``) and then reads back as
#: the counter's ceiling, ``PAGE_COUNTER_MAX * PAGE_SIZE`` with
#: ``PAGE_COUNTER_MAX = LONG_MAX / PAGE_SIZE`` on 64-bit
#: (``include/linux/page_counter.h``) — ``LONG_MAX`` rounded down to a page,
#: 9223372036854771712 on the CI image this repository runs on. Anything at or
#: above 2**62 (four exbibytes) is that sentinel, not a limit a machine has.
_CGROUP_V1_UNLIMITED_FLOOR = 2**62


def _memory_limit() -> tuple[int | None, str]:
    """The memory this container may use, in bytes — or ``None`` when no finite limit is readable.

    Read the way :func:`_cpu_budget` reads the CPU quota, and for the same
    reason: this is the number the read pool is sized from, and it has to come
    from the container in front of us rather than from a constant in the
    repository. The service already moved plans and regions once (#3391), and
    a hard-coded 512MB would have described the old one.

    cgroup v2 keeps it in ``/sys/fs/cgroup/memory.max`` as a single value — an
    integer, or the word ``max`` for no limit (``admin-guide/cgroup-v2``).
    cgroup v1 keeps it in ``memory/memory.limit_in_bytes``, where "no limit"
    reads as a number next to ``LONG_MAX`` — see
    :data:`_CGROUP_V1_UNLIMITED_FLOOR`. The second value returned is what the
    capacity line prints: the limit with its cgroup version, ``unlimited``, or
    ``unavailable`` when neither file could be read.

    The file contents are external input. Every parse sits under the same
    narrow ``except`` the CPU reader uses, and a shape that does not parse is
    "unavailable" — never an exception on the startup path. ``None`` is the one
    answer for "no file", "cannot parse" and "no limit", deliberately: in all
    three the formula has no budget to work from and the caller takes the
    conservative fallback either way. The display string is what keeps the
    three apart in the log.
    """
    try:
        raw = pathlib.Path("/sys/fs/cgroup/memory.max").read_text().split()
        value = raw[0]
        if value == "max":
            return None, "cgroup v2: unlimited"
        limit = int(value)
        return limit, f"cgroup v2: {_mib(limit)}"
    except (OSError, ValueError, IndexError):
        pass
    try:
        limit = int(pathlib.Path("/sys/fs/cgroup/memory/memory.limit_in_bytes").read_text())
        if limit >= _CGROUP_V1_UNLIMITED_FLOOR:
            return None, "cgroup v1: unlimited"
        return limit, f"cgroup v1: {_mib(limit)}"
    except (OSError, ValueError):
        return None, "unavailable"


# ---------------------------------------------------------------------------
# The read pool is sized from the container's **memory** quota. The constants
# below are the measurements it is sized from, and each names where its number
# came from and when — a number without that is a number nobody can re-check.
#
# Why memory and not CPU: for a Mongo or disk read, twelve threads on half a
# core are fine, they sleep. For pure-Python parsing there is no CPU
# parallelism at all under the GIL, so what a wider pool buys is only *memory*
# parallelism — N parse trees alive at once, with nothing to show for it in
# throughput. The memory budget is the binding constraint; the CPU quota is
# printed beside the result on the capacity line, not used in it.
# ---------------------------------------------------------------------------

#: The smallest pool this service runs with, and the size it falls back to when
#: no memory limit is readable.
#:
#: Two, not one: the floor exists so that one Mongo read stuck on the network
#: cannot stall every other read, and two is the smallest size with that
#: property. Every unit above it is memory the formula said the container does
#: not have. The same value is the fallback because, with the limit unknown,
#: the cost of being too narrow is visible — slow reads, and the capacity line
#: says why — while the cost of being too wide is an OOM kill nobody can
#: attribute. That is the fail-closed choice :func:`_declares_write` makes, for
#: the same reason; and it is explicitly not ``os.cpu_count() + 4``, the number
#: this sizing exists to stop relying on.
_READ_POOL_FLOOR = 2

#: The largest pool this service runs with, whatever the plan: the width
#: production already ran before #3391 (``read pool 12 threads`` on the
#: capacity line), so a move to a larger plan cannot widen the pool past a
#: width the service has survived without somebody deciding it. Two reasons
#: it is a hard bound and not just a formula: above it, more threads are only
#: more concurrent parses of a GIL-bound parser; and the per-thread cost the
#: formula divides by is the parse, which understates what an admin range read
#: holds (see :data:`_PARSE_COST_BYTES`), so the formula must not be allowed
#: to scale that understatement up with the plan. The first version used
#: CPython's own default-executor ceiling of 32; the review of #3429 brought it
#: down to the measured production width.
_READ_POOL_CAP = 12

#: RSS of the idle service in production: 91.5MB, flat for seven hours on the
#: Frankfurt service (Render metrics ``memory_usage``, 2026-09-19). Higher than
#: the 54.5MB a bare ``build_app`` measures locally, because production carries
#: the Mongo connection pool, the PostHog client and the mirror autosync
#: thread — which is why the production number is the one used.
_PROCESS_BASELINE_BYTES = 92 * 1024 * 1024

#: Everything the process holds beyond the baseline that is *not* the parse
#: being budgeted for: Mongo results, grep output up to the byte budget, the
#: autosync fetch, the one write in flight. Sized from what was observed, not
#: guessed: over a full day of agent traffic the working set peaked at
#: 152–157MB against the 92MB baseline (Render metrics, 2026-09-20), so the
#: margin is that gap.
_NON_PARSE_MARGIN_BYTES = 64 * 1024 * 1024

#: RSS growth per byte of input while a parse is alive — the **peak** during
#: the parse (``VmHWM`` above the pre-parse high-water mark), because that is
#: what N parses in flight hold at once; what ``parse_document`` retains
#: afterwards is smaller.
#:
#: **Which parser this number describes.** It was measured on
#: ``services.md_parser`` (the pinned ``markdown-it-py``), one parse per fresh
#: process, on 2026-09-20 — the parser the Markdown tool runs, so
#: the pool is sized ahead of that tool. The tool that parses **today**,
#: ``codekeeper_docs_get_section``, runs ``services.rst_parser`` on
#: ``docs/*.rst`` only, and that parser is far cheaper by the same method:
#: its RST corpus at the read ceiling adds nothing above the process's
#: pre-parse high-water mark (2.7 bytes per input byte retained), its densest
#: page (``docs/modules/index.rst``) tiled to the ceiling peaks at 6.4, and a
#: hostile shape of one-character headings at 90.2 **without a ceiling** —
#: 44.0MiB for one parse, above the 35.2MiB the formula grants a thread. That
#: is why ``docs_get_section`` passes the outline's section ceiling (50,000)
#: to the parser since the review of #3429: the same shape then stops at
#: 20.1MiB (41.1 bytes per input byte), inside the allowance, and no real
#: page comes near the ceiling. ``scripts/measure_md_parse_cost.py`` measures
#: both parsers; run it when either of them changes.
#:
#: The cost scales with the document's **density**, not its size: the
#: repository's Markdown corpus peaks at 21 bytes per input byte at its median
#: density of ~27 block tokens per KB, and its densest real document
#: (``CLOUD.md``, ~170 tokens per KB) tiled to the read ceiling peaks at 70.7.
#: The constant, 72, is the earlier reading of that shape (71.7, before the
#: script learned to subtract the pre-parse high-water mark) rounded up; the
#: gap is margin, and re-running the script is what moves the constant, not
#: an edit by hand. The 110 recorded in #3391 is not directly comparable to
#: it: that figure came from a denser corpus (~250 tokens per KB) **and** from
#: markdown-it-py 4.2.0, while the density curve above was measured on the
#: pinned 3.0.0 only, and the old corpus was not re-measured on 3.0.0. So a
#: parser upgrade re-runs the script; it does not assume the constant survives.
#:
#: What the constant is **not**: the adversarial bound. A 500KB file of
#: one-line bullets peaks at ~290 bytes per input byte — 141MiB for a single
#: parse — which no pool width can absorb (three such parses exceed the plan
#: at any width above the floor). The tool reads only the mirrored,
#: allow-listed docs repositories, so the densest document it actually serves
#: is the honest budget, and a ceiling inside the parser itself is the
#: instrument for the hostile shape: in place for RST (the section ceiling
#: above), still pending for Markdown, whose bullet shape has no headings for
#: ``MAX_SECTIONS`` to count — a token ceiling, tracked in #3391, not here.
_PARSE_RSS_PER_INPUT_BYTE = 72

#: What one parse can cost at most — the divisor of the memory budget. The
#: largest input a parse can receive is
#: :data:`~services.git_mirror_service.MAX_FILE_SIZE_FOR_DISPLAY`:
#: ``codekeeper_docs_get_section`` reads through ``RepoBackend.get_file``
#: without ``lines`` and therefore without ``max_size``, and refuses
#: ``too_large`` before it parses anything. Computed from the imported ceiling
#: rather than copied, so a change to the read ceiling moves the budget with it.
#:
#: **A decision, recorded (review of #3429): the divisor is priced by the
#: parse, and the parse is not the largest thing a read thread holds.** The
#: admin-only ``codekeeper_get_repo_file`` with ``outline=true`` or ``lines=``
#: reads up to ``RANGE_READ_MAX_BYTES`` (10MiB), and the mirror buffers the
#: whole blob before its size check. Measured on 2026-09-20 by the same
#: method: an outline of a 10MB RST file holds 61–77MiB over the whole path
#: (realistic tiling / hostile headings, both ending in ``TooManySections``;
#: the script's ``outline_densest_real`` line shows the parse alone above the
#: pre-parse high-water mark, 51MiB, the rest being the 10MB of text already
#: in memory), and a ``lines=`` read of the real 7MB
#: ``webapp/static/js/md_preview.bundle.js`` holds ~37MiB — 1.1 to 2.2 times
#: the 35.2MiB this divisor grants a thread. It stays priced
#: by the parse because: the parse is what the public tool can cost at any
#: moment, while the range tools sit behind ``require_admin``; the largest hold
#: on a file that exists in the mirrors today (37MiB) fits the plan even at
#: full width — 92 + 10 × 37.2 = 464MiB of 512MiB; and the 61–77MiB shape needs
#: a 10MB RST file that no mirrored repository has (the largest here is 169KB).
#: Pricing by ``RANGE_READ_MAX_BYTES`` would have cut the public path to 4
#: threads (at 77MiB) or 9 (at 37MiB) for a shape without a source. What did
#: change because of this is :data:`_READ_POOL_CAP`; the root fix — bounding
#: the read at its source with a size probe before ``git show`` (#3433) — has
#: landed in ``get_file_at_commit``: a blob over ``max_size`` is refused from
#: ``git cat-file -s`` without being read (12MB: 20MiB peak before, 0 after,
#: measured), so the hold above is now only what a file *under* the cap costs.
_PARSE_COST_BYTES = _PARSE_RSS_PER_INPUT_BYTE * MAX_FILE_SIZE_FOR_DISPLAY


class _ReadPoolSizing(NamedTuple):
    """What the read pool was sized to, and why — the why goes on the capacity line."""

    workers: int
    #: ``memory`` when the formula decided; ``floor`` or ``cap`` when a bound
    #: overrode it; ``fallback`` when no memory limit was readable.
    source: str
    detail: str


def _read_pool_size(memory_limit: int | None) -> _ReadPoolSizing:
    """How many read threads the memory budget allows, bounded below and above.

    ``(limit - baseline - margin) // cost_of_one_parse``: what is left after
    the process itself and its non-parse work, divided by what one largest
    allowed parse costs. On the production plan that is
    ``(512MiB - 92MiB - 64MiB) / 35.2MiB = 10``. The old pool was 12 on the same
    plan, from ``min(32, os.cpu_count() + 4)`` with ``os.cpu_count()``
    reporting the host's eight cores against a quota of half a core.

    Pure: takes the limit, returns the size and the arithmetic behind it. A
    limit of ``None`` means no finite limit was readable, and the answer is
    the floor — :data:`_READ_POOL_FLOOR` says why the fallback is the
    conservative end.
    """
    if memory_limit is None:
        return _ReadPoolSizing(
            _READ_POOL_FLOOR,
            "fallback",
            f"fallback {_READ_POOL_FLOOR}: no memory limit readable",
        )
    budget = memory_limit - _PROCESS_BASELINE_BYTES - _NON_PARSE_MARGIN_BYTES
    allowed = budget // _PARSE_COST_BYTES
    arithmetic = (
        f"({_mib(memory_limit)} - {_mib(_PROCESS_BASELINE_BYTES)} baseline - "
        f"{_mib(_NON_PARSE_MARGIN_BYTES)} margin) / {_mib(_PARSE_COST_BYTES)} "
        f"per parse = {allowed}"
    )
    if allowed < _READ_POOL_FLOOR:
        return _ReadPoolSizing(
            _READ_POOL_FLOOR, "floor", f"floor {_READ_POOL_FLOOR}: memory budget allowed {arithmetic}"
        )
    if allowed > _READ_POOL_CAP:
        return _ReadPoolSizing(
            _READ_POOL_CAP, "cap", f"cap {_READ_POOL_CAP}: memory budget allowed {arithmetic}"
        )
    return _ReadPoolSizing(int(allowed), "memory", f"sized from memory: {arithmetic}")


def _installed_width(pool: ThreadPoolExecutor) -> int | None:
    """The width the executor actually has — or ``None`` when this Python no longer exposes it.

    ``ThreadPoolExecutor._max_workers`` is private to CPython, and it is read
    on purpose (``state-record-without-state-change``: the capacity line
    describes the pool that exists, not the one that was requested). Private
    means it can go away. When it does, the answer here is ``None`` — not the
    requested width, which would be exactly the echo the line exists to avoid
    — and the callers print that they do not know, with a warning, instead of
    failing the startup of the service over a log line (#3433, SUGG-004).
    """
    return getattr(pool, "_max_workers", None)


def _width_label(pool: ThreadPoolExecutor, sizing: _ReadPoolSizing) -> str:
    """What the capacity line prints for the read pool: the installed width, or an honest "unreadable"."""
    width = _installed_width(pool)
    if width is not None:
        return str(width)
    return f"{sizing.workers} (requested; installed width unreadable)"


def _log_dispatch_capacity(
    read_pool: ThreadPoolExecutor, memory_display: str, sizing: _ReadPoolSizing
) -> None:
    """One line at startup naming the concurrency the dispatch model actually has.

    The number printed for the read pool is read off the executor that was
    installed — ``ThreadPoolExecutor._max_workers``, the attribute the pool
    sizes itself from (``concurrent/futures/thread.py``) — and not recomputed
    here. A line that computed its own number would describe the pool it
    expected rather than the pool that exists, and the two would part ways
    the day someone changed one of them; the previous version of this function
    did exactly that with ``min(32, os.cpu_count() + 4)``, which is why it is
    now handed the pool. ``os.cpu_count()`` and the affinity count stay on the
    line because the gap between them and the quota is the whole story of
    #3391, and the memory limit joins the CPU quota because it is now the
    number the pool is sized from.

    Every value is computed before the call rather than inside it, so a level
    guard or a deleted line takes the line and nothing else with it. And the
    private attribute is read through :func:`_installed_width`: should it
    vanish, the line says "unreadable" beside the requested width and a
    warning names the reason — a log line never fails the startup.
    """
    detected = os.cpu_count() or 1
    try:
        usable = len(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        usable = detected
    quota = _cpu_budget()
    if _installed_width(read_pool) is None:
        logger.warning(
            "mcp read pool width is not readable on this Python "
            "(ThreadPoolExecutor._max_workers is gone); the capacity line reports "
            "the requested width %d instead of the installed one",
            sizing.workers,
        )
    logger.info(
        "mcp dispatch capacity: read pool %s threads (%s; os.cpu_count=%d, "
        "usable=%d), write pool 1 thread, cpu quota %s, memory limit %s",
        _width_label(read_pool, sizing),
        sizing.detail,
        detected,
        usable,
        quota,
        memory_display,
    )


def attach_read_pool(app: Any) -> None:
    """Install the sized read pool as the loop's default executor at ASGI startup.

    ``asyncio.to_thread`` — where every read tool runs, see
    :func:`_offload_to_thread` — submits to the loop's default executor
    (``asyncio/threads.py`` ends in ``loop.run_in_executor(None, ...)``), so
    replacing that executor is what sizes the reads, with no change to the
    dispatch path. Two constraints decide where this happens, both read off
    CPython and the SDK rather than assumed:

    * ``loop.set_default_executor`` needs a running loop and accepts only a
      ``ThreadPoolExecutor`` — ``asyncio/base_events.py`` raises ``TypeError``
      for anything else. ``build_app`` runs at import, before uvicorn has a
      loop, so the call cannot live there.
    * ``FastMCP.streamable_http_app()`` builds its Starlette app with an
      explicit ``lifespan=`` (``mcp 1.28.1``), so Starlette's ``Router``
      ignores ``on_startup`` entirely and wrapping ``router.lifespan_context``
      is the only seam — the one
      :func:`~mcp_server.analytics.attach_shutdown_drain` already uses, and
      this wrapper has the same shape.

    The pool is built complete, in a local, and published by one assignment;
    its threads are spawned lazily by the executor under its own lock
    (``_adjust_thread_count``), which is the library's contract and not a
    guard of ours. The capacity line is emitted right here, from the pool that
    was installed, so the line and the state it describes cannot drift apart.

    **What this does not do.** It does not shut the pool down on lifespan
    exit: the default executor belongs to the loop, and uvicorn's
    ``asyncio.run`` ends with ``loop.shutdown_default_executor()``
    (``asyncio/runners.py``), which joins the workers with ``wait=True`` — so
    a read in flight finishes on a deploy, the property :data:`_WRITE_POOL`
    has. A second entry into the same lifespan on the same loop would install
    a second pool and leave the first idle until interpreter exit
    (``concurrent.futures.thread._python_exit`` wakes and joins it); that is
    not a production path and is not guarded. And when the app carries no
    lifespan at all, the executor is **not** replaced and reads keep CPython's
    default of ``min(32, os.cpu_count() + 4)`` — logged as a warning, because
    a pool sized from the host's core count is exactly what this function
    exists to remove.
    """
    router = getattr(app, "router", None)
    original = getattr(router, "lifespan_context", None)
    if original is None:
        logger.warning(
            "no lifespan on the ASGI app; the read pool was not installed and reads "
            "run on the loop's default executor, sized from os.cpu_count()"
        )
        return

    @contextlib.asynccontextmanager
    async def _lifespan_with_read_pool(scope_app: Any):
        loop = asyncio.get_running_loop()
        memory_limit, memory_display = _memory_limit()
        sizing = _read_pool_size(memory_limit)
        pool = ThreadPoolExecutor(max_workers=sizing.workers, thread_name_prefix="mcp-read")
        loop.set_default_executor(pool)
        _log_dispatch_capacity(pool, memory_display, sizing)
        if sizing.source == "fallback":
            # A narrower pool than the plan allows is a worse path, and a worse
            # path nobody reports is the one that stays. The capacity line says
            # the size; this says that it was not chosen.
            logger.warning(
                "mcp read pool fell back to %s threads: memory limit %s — reads are "
                "narrower than the plan allows until the cgroup limit is readable",
                _width_label(pool, sizing),
                memory_display,
            )
        async with original(scope_app) as state:
            yield state

    router.lifespan_context = _lifespan_with_read_pool


def _declares_write(annotations: Any) -> bool:
    """True unless a tool's annotations say it is read-only.

    **Fail-closed, and the phrasing is the whole point.** The protocol's default
    for a missing ``readOnlyHint`` is ``false`` — "If true, the tool does not
    modify its environment. Default: false" (``mcp/types.py``,
    ``ToolAnnotations``) — so an absent hint describes a tool that *may* modify.
    Reading an absent hint as read-only would drop the queue for the next write
    tool someone adds without the key: no error, no failing test, and nothing in
    the schema to show for it. The cost of erring the other way is a read tool
    that queues needlessly, which is slow and visible rather than silent.

    Derived from the annotation the tool already declares rather than from a
    list of tool names: a name list is a second place to keep in sync, and the
    tool added next week is exactly the one that would be missing from it.
    Accepts a dict or a ``ToolAnnotations``, because the SDK takes either.
    """
    if annotations is None:
        return True
    hint = (
        annotations.get("readOnlyHint")
        if isinstance(annotations, dict)
        else getattr(annotations, "readOnlyHint", None)
    )
    return hint is not True


def _annotations_of(args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any:
    """The annotations of a registration, however they were passed.

    Every registration in this module passes ``annotations`` by keyword, but the
    SDK declares it as an ordinary parameter and accepts it positionally too.
    Reading only ``kwargs`` would let a positional call register a write tool
    with no queue, no error, and an identical schema — the same silent shape the
    rest of this file exists to remove. Binding against the SDK's real signature
    keeps the answer correct if a release inserts a parameter ahead of it.
    """
    try:
        bound = _ADD_TOOL_SIGNATURE.bind_partial(None, None, *args, **kwargs)
    except TypeError:
        return kwargs.get("annotations")
    return bound.arguments.get("annotations")


def _is_async_callable(obj: Any) -> bool:
    """Async in the same sense the SDK means it when it decides how to dispatch.

    Copied rather than imported: the SDK's version is private
    (``_is_async_callable`` in ``mcp/server/fastmcp/tools/base.py``, absent from
    ``__all__``), and importing a private name is a dependency on something
    nobody promised to keep. What keeps the copy honest is a test that asserts
    the two agree shape by shape, so an SDK change fails loudly instead of
    splitting the two definitions in silence.

    ``inspect.iscoroutinefunction`` alone is narrower: it does not recognise an
    object whose ``__call__`` is ``async def``. The SDK would dispatch such a
    tool with ``await`` while we had wrapped it as though it were sync.
    """
    while isinstance(obj, functools.partial):
        obj = obj.func
    # Kept expression-for-expression identical to the SDK's, because a test
    # asserts the two agree and a "tidier" rewrite is how they drift apart.
    # B004 reads ``getattr(obj, "__call__")`` as a callability test; here it
    # fetches the method so ``iscoroutinefunction`` can look at it, and the
    # callability test is the ``callable(obj)`` beside it.
    return inspect.iscoroutinefunction(obj) or (
        callable(obj)
        and inspect.iscoroutinefunction(getattr(obj, "__call__", None))  # noqa: B004
    )


def _log_write_timing(tool: str, waited: float, ran: float | None) -> None:
    """One line per write, splitting the wait for the queue from the work.

    The split is the point. A total duration cannot tell a slow save apart from
    a fast save that sat behind three others, and those two have different
    fixes: one is the write path, the other is :data:`_WRITE_POOL` being too
    narrow. Without this line the only signal is end-to-end duration from
    PostHog, which makes neither distinction and is off unless a token is set.

    ``ran`` is ``None`` for a write that was cancelled while still in the queue
    and therefore never started. **That case needs the line most and is the one
    a timer inside the body cannot produce**, because the body is what does the
    timing and it never runs: a queue deep enough that callers give up would
    otherwise be invisible in exactly the way this logging exists to prevent.

    **Why the ordinary case is ``info`` and not ``debug``.** The service
    configures logging at ``INFO`` (``mcp_server/app.py``, from ``LOG_LEVEL``),
    so a ``debug`` line is not quiet — it is *absent*, which is the failure this
    whole area was just fixed for. Against that, the volume cannot run away:
    one worker runs one write at a time, so this line is bounded by how many
    writes a minute one worker can finish — thirteen at the 4.3-4.9s p50 this
    was written against (before the 2026-09-16 move to Frankfurt; the service's
    logs since then show 0.012-1.993s, so the bound is higher now, and it is
    still one line per write, never more). And logging only the slow case would
    say when the wait is bad
    without ever saying what it normally is, which is the number any decision
    about the queue's width depends on.

    These go through the standard library logger like everything else in
    ``mcp_server``, which also keeps them clear of ``LOG_INFO_SAMPLE_RATE`` —
    that sampling is a ``structlog`` processor and applies to ``emit_event``
    records, not to these.

    Both numbers are measured by the caller and passed in already computed. They
    are deliberately not expressions inside the logging call: work that rides on
    a log line disappears the day someone removes the line or puts a level guard
    in front of it, and the failure then surfaces somewhere else entirely.
    """
    slow = waited >= _SLOW_WRITE_QUEUE_WAIT
    if ran is None:
        if slow:
            logger.warning(
                "mcp write %s waited %.2fs for the write queue and was cancelled before it ran",
                tool,
                waited,
            )
        else:
            logger.info(
                "mcp write %s: queued %.3fs, cancelled before it ran", tool, waited
            )
        return
    if slow:
        logger.warning(
            "mcp write %s waited %.2fs for the write queue, then ran %.2fs",
            tool,
            waited,
            ran,
        )
    else:
        logger.info("mcp write %s: queued %.3fs, ran %.3fs", tool, waited, ran)


def _offload_to_thread(fn: Any, *, serialize: bool = False) -> Any:
    """Wrap a sync tool body so it runs on a worker thread instead of the loop.

    **Why this exists (#3379).** Measured against ``mcp 1.28.1``:
    ``func_metadata.call_fn_with_arg_validation`` dispatches a tool with
    ``await fn(...)`` when it is a coroutine function and ``return fn(...)``
    otherwise — so every sync tool body ran **on the event loop**, and one slow
    call stalled every other session rather than only its own caller. The
    heaviest measured bodies are seconds long, which makes this a shared-outage
    class and not a slow request.

    **Why at registration and not in each tool body.** One rule needs one
    definition: a call site per tool is a chance per tool to forget, and the
    next tool would start life on the loop again. ``FastMCP.tool()`` funnels
    into ``add_tool`` (verified in the SDK), so wrapping there covers every tool
    that exists and every tool that will exist — and
    ``tests/test_mcp_to_thread.py`` asserts that *every* registered tool is a
    coroutine function, so a regression fails loudly instead of quietly running
    on the loop again.

    **Two destinations, not one.** A read goes to ``asyncio.to_thread`` and the
    loop's default executor, where several reads run at once — the pool
    :func:`attach_read_pool` installs at ASGI startup, sized from the memory
    quota (:func:`_read_pool_size`) rather than from the host's core count. A write
    goes to :data:`_WRITE_POOL` and its single worker, which is what keeps write
    bodies from interleaving and what hands them to the worker in the order they
    were sent. The reason writes do not simply take a lock on the shared
    executor is written at :data:`_WRITE_POOL`; the short version is that a
    writer blocked on a lock still holds a thread the readers need.

    **What survives the hop, measured and not assumed:**

    - ``functools.wraps`` keeps ``__wrapped__``, so ``inspect.signature`` — and
      with it the advertised input schema — is byte-identical to the unwrapped
      tool, ``Context`` injection included.
    - ``ctx.request_context`` is an **instance attribute** on the ``Context``
      object that ``FastMCP.call_tool`` builds on the loop, so it travels into
      the thread untouched.
    - ``get_access_token()`` reads ``auth_context_var``, a ``ContextVar``.
      ``asyncio.to_thread`` copies the current ``contextvars.Context`` for us
      (``asyncio/threads.py``); ``loop.run_in_executor`` does **not**
      (``asyncio/base_events.py``), which is why the write path copies it
      explicitly below. Verified both ways: without the copy,
      ``get_access_token()`` returns ``None`` inside the worker and
      ``require_admin`` / ``require_write`` stop seeing who is asking.

    **What this changes about concurrency, said out loud.** Running on the loop
    serialized every tool body, reads included: two calls from the same token
    could not interleave, because the first ran to completion before the second
    started. Reads can interleave now, and that is the intended result — the
    serialization was an accident of the bug rather than a design. Writes still
    cannot, because they share one worker; what they no longer have is the
    shared-outage cost of getting there.

    The read-then-write version pick in :meth:`Backend.save_file` (``U1``
    variation *b*: read, branch, write, with no CAS) is **not** made wrong by
    this change — the webapp and the bot already call ``save_code_snippet``
    concurrently under gunicorn, from processes this queue does not reach. It
    does stop being hidden from the MCP path. It is a pre-existing gap, out of
    scope here, and it wants its own fix rather than a thread model chosen to
    paper over it.

    **Thread-safety of what the bodies touch — what was checked, and what that
    does and does not cover.** Checked and clear: ``pymongo`` is thread-safe by
    contract and is the only driver on this path (no ``motor`` anywhere in
    ``mcp_server``), the module-level state in this file is read-only constants,
    there is no ``threading.local``, and the MCP service runs under uvicorn with
    no gevent monkey-patching.

    That sweep looked at module-level state. It did **not** look at the lazily
    built fields on the backend objects the bodies call into, and a review
    caught the gap: with reads now running side by side, every
    ``if self._x is None: self._x = ...`` in ``mcp_server/backend.py`` and
    ``mcp_server/repo_backend.py`` is reachable by two threads at once, where
    the event loop used to make the question impossible. Each was then read
    against ``lazy-init-guard-publish-order``: all publish the value before the
    guard (the guard *is* the value), so none can hand out a half-built object;
    two build something cheap enough to build twice and say so in place; two
    build something that touches Mongo and are locked. The details live next to
    each one rather than here, because that is where the next person changing
    them will be.

    Nothing outside ``mcp_server`` was swept the same way. ``get_mirror_service``
    was read because the read path reaches it directly, and it carries its own
    note; anything else a body reaches transitively has not been audited for
    this, and saying so is more useful than implying it has.

    An ``async def`` read tool is returned untouched: it is already off the
    blocking path, and wrapping it would add a pointless thread hop. An ``async
    def`` **write** tool is refused outright — see below.
    """
    if _is_async_callable(fn):
        if serialize:
            raise TypeError(
                f"{getattr(fn, '__name__', fn)!r} declares a write but is async. "
                "Write tools are serialized by running on a single-worker pool, "
                "which only orders sync bodies: an async body would hand the "
                "worker a coroutine and run on the loop, unserialized and "
                "unqueued, with nothing to show that it had. Make the body "
                "sync, or give the write path an async lock of its own."
            )
        return fn

    if not serialize:

        @functools.wraps(fn)
        async def _run_on_shared_pool(*args: Any, **kwargs: Any) -> Any:
            return await asyncio.to_thread(fn, *args, **kwargs)

        return _run_on_shared_pool

    tool_name = getattr(fn, "__name__", repr(fn))

    @functools.wraps(fn)
    async def _run_on_write_pool(*args: Any, **kwargs: Any) -> Any:
        submitted = time.perf_counter()

        def _timed() -> Any:
            started = time.perf_counter()
            waited = started - submitted
            try:
                return fn(*args, **kwargs)
            finally:
                ran = time.perf_counter() - started
                _log_write_timing(tool_name, waited, ran)

        loop = asyncio.get_running_loop()
        # ``loop.run_in_executor`` is ``wrap_future(executor.submit(...))`` and
        # nothing else (``asyncio/base_events.py``); submitting directly keeps a
        # handle on the ``concurrent.futures.Future``, which is the only
        # authoritative answer to "did this body run". It also takes positional
        # arguments only and does not carry the ``contextvars.Context`` across
        # the way ``to_thread`` does, so the copy is explicit and ``_timed``
        # closes over the call's own arguments.
        context = contextvars.copy_context()
        pending = _WRITE_POOL.submit(context.run, _timed)
        try:
            return await asyncio.wrap_future(pending, loop=loop)
        except asyncio.CancelledError:
            # ``cancelled()`` is true only when the cancellation reached the
            # work item before it started, which is the same state
            # ``_WorkItem.run`` checks before calling anything — so the body
            # definitely never ran and definitely never logged. Asking the
            # future rather than a flag set by the body is what keeps this from
            # claiming "cancelled before it ran" about a write that was already
            # running, and from printing a second line about one that was.
            if pending.cancelled():
                _log_write_timing(tool_name, time.perf_counter() - submitted, None)
            raise

    return _run_on_write_pool


def _refusal_result(refusal: dict[str, Any]) -> CallToolResult:
    """A rate-limit refusal as the whole ``CallToolResult`` — the one shape every tool can return.

    ``FastMCP.call_tool`` normally returns what the tool's own ``convert_result``
    built for its return type, and the low-level ``tools/call`` handler then
    validates structured content against the tool's ``outputSchema``: a bare
    content list for a tool that declares one becomes an ``isError`` result
    ("outputSchema defined but no structured output returned"). A
    ``CallToolResult`` is returned by that handler as it is
    (``if isinstance(results, types.CallToolResult): return
    types.ServerResult(results)`` — ``mcp/server/lowlevel/server.py``, mcp
    1.28.1), so it serves a ``dict`` tool, a typed tool and an unknown name
    alike. Until the seven-PR review (SUGG-009) the refusal went through the
    refused tool's ``convert_result``, which turned the throttle of a tool
    annotated ``-> list[str]`` into a ``pydantic.ValidationError`` exactly when
    it fired, and an unknown name into the SDK's unknown-tool error.

    The text is built the way ``_convert_to_content`` builds it for a ``dict``
    (``mcp/server/fastmcp/utilities/func_metadata.py``:
    ``pydantic_core.to_json(result, fallback=str, indent=2)``), so the client
    reads the same block a body's own refusal produces. ``isError`` stays
    ``False``: a refusal is a regular protocol answer, not a server incident —
    the rule ``docs/mcp-server.rst`` states for every refusal.
    """
    text = pydantic_core.to_json(refusal, fallback=str, indent=2).decode()
    return CallToolResult(content=[TextContent(type="text", text=text)], isError=False)


class AdminAwareFastMCP(FastMCP):
    """FastMCP that hides the admin-only tools from non-admin tools/list, and
    keeps every tool body off the event loop.

    The SDK's tools/list is static (one ToolManager), but the auth context IS
    available inside the handler, so we filter per request. Fail-closed: any
    doubt (no request context, unauthenticated, lookup error) ⇒ non-admin view.
    """

    def __init__(
        self, *args: Any, tool_rate_limiter: ToolRateLimiter | None = None, **kwargs: Any
    ) -> None:
        # Set before ``super().__init__`` so the attribute exists whatever the
        # SDK's constructor does; ``call_tool`` below reads it on every call.
        # ``is None`` and not ``or``: ``ToolRateLimiter(0)`` is the documented
        # kill switch, and ``or`` kept it only because the class defines neither
        # ``__bool__`` nor ``__len__`` — the first one added would have swapped a
        # switched-off limiter for the 60/min default in silence (K12 §3).
        if tool_rate_limiter is None:
            tool_rate_limiter = ToolRateLimiter(DEFAULT_RATE_LIMIT_PER_MINUTE)
        self._tool_rate_limiter = tool_rate_limiter
        super().__init__(*args, **kwargs)

    def add_tool(self, fn: Any, *args: Any, **kwargs: Any) -> Any:  # type: ignore[override]
        """Register a tool, moving a sync body onto a worker thread first.

        Both registration paths land here — ``@mcp.tool(...)`` builds a
        decorator that calls ``self.add_tool``, and ``mcp.add_tool(...)`` is
        called directly — so this is the single place where the guarantee is
        made. ``*args``/``**kwargs`` pass through untouched so that a new
        keyword in a future SDK release does not need a change here.

        A tool whose annotations do not say it is read-only is routed to
        :data:`_WRITE_POOL` instead of the shared executor, so the write path
        keeps the one-at-a-time ordering it had while it lived on the event
        loop. The annotations are read through :func:`_annotations_of` rather
        than straight out of ``kwargs``, because the SDK accepts them
        positionally as well.
        """
        serialize = _declares_write(_annotations_of(args, kwargs))
        return super().add_tool(_offload_to_thread(fn, serialize=serialize), *args, **kwargs)

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:  # type: ignore[override]
        """Decide the per-identity rate limit here, and nowhere else (#3431).

        The SDK registers this method as the low-level ``tools/call`` handler
        (``FastMCP._setup_handlers`` — ``self._mcp_server.call_tool(...)(self.call_tool)``,
        mcp 1.28.1), so every tool call passes through it: sync bodies before
        they are handed to a worker, async bodies before they run on the loop.
        A refused call therefore costs no thread. And the registered functions
        stay exactly what ``add_tool`` built — the routing tests read
        ``fn.__code__.co_name`` off them, which an outer wrapper would hide.

        The refusal is a whole ``CallToolResult`` (:func:`_refusal_result`), so
        the client sees the same text block a body's own refusal has
        (``{"ok": false, "error": ...}``), whatever the tool's return type is
        and whether or not the name exists — the budget is charged before the
        name is looked up, so an identity over budget cannot probe tool names
        for free.

        **``codekeeper_read_batch`` weighs as many calls as it has items**
        (``mcp_server/read_batch.py``), and three things about it happen here:

        * **The moment the call arrived is recorded first**, before the limiter
          and before the wait for a read thread, and handed to the body through
          :data:`read_batch.ENTERED_AT` — the batch deadline is measured from
          it, because the client's clock started then too.
        * **The empty list and the item cap are refused before the weighing**,
          so a request that could never pass hears why (``missing_items``,
          ``too_many_items``) instead of ``rate_limited`` with a wait that would
          not help. Only for an admin: anyone else is charged one call and
          refused by the body's ``require_admin``, without learning the cap of a
          tool they cannot see.
        * **The weight is all or nothing** (``RateLimiter.check_rate_limit``): a
          batch that does not fit whole is refused before any of it is read.

        No units come back for items the batch did not read (``unread``). That
        case is rare — the review round that created the tool fits well inside
        both the byte budget and the deadline, measured in production and by
        ``scripts/measure_read_batch.py``; the numbers live in
        ``docs/mcp-server.rst`` (``codekeeper_read_batch``) — and a refund would
        be a second mechanism with nothing today to justify it.
        """
        entered_at = read_batch.clock() if name == read_batch.TOOL_NAME else None
        user_id = self._caller_identity()
        weight = 1
        if entered_at is not None and user_id is not None and is_admin_user(user_id):
            items = arguments.get("items") if isinstance(arguments, dict) else None
            refusal = read_batch.refuse_items(items, cap=self.batch_item_cap())
            if refusal is not None:
                return _refusal_result(refusal)
            weight = read_batch.weight_of(items)
        if user_id is not None:
            refusal = await self._tool_rate_limiter.admit(user_id, weight=weight)
            if refusal is not None:
                return _refusal_result(refusal)
        if entered_at is None:
            return await super().call_tool(name, arguments)
        token = read_batch.ENTERED_AT.set(entered_at)
        try:
            return await super().call_tool(name, arguments)
        finally:
            read_batch.ENTERED_AT.reset(token)

    def batch_item_cap(self) -> int:
        """How many items one ``codekeeper_read_batch`` call may carry on this server.

        One answer for the refusal here and for the tool body, read off the one
        limiter this server charges — see :func:`read_batch.item_cap`.
        """
        return read_batch.item_cap(self._tool_rate_limiter.per_minute)

    def _caller_identity(self) -> int | None:
        """Whose budget a call is charged to — or ``None`` when there is nobody to charge.

        Outside a request ``Server.request_context`` raises ``LookupError``
        ("If called outside of a request context, this will raise a
        LookupError" — ``mcp/server/lowlevel/server.py``): no client, nothing
        to count, and the tool bodies keep answering as they do in the tests
        that call them directly. Inside a request the identity is
        ``current_user_id`` on the SDK's context — the same function every gate
        uses, in both auth modes. Its documented failure, ``PermissionError``
        (no identity on the request), is unreachable for a ``tools/call`` in
        production, because both auth modes reject an unauthenticated request
        upstream: ``RequireAuthMiddleware`` on the ``/mcp`` mount in OAuth
        mode, ``PATAuthMiddleware`` in PAT mode. So answering ``None`` there is
        not a way past the limiter; the test that reaches it does so by
        monkeypatching ``current_user_id``.
        """
        try:
            self._mcp_server.request_context
        except LookupError:
            return None
        try:
            return current_user_id(self.get_context())
        except PermissionError:
            return None

    async def list_tools(self):  # type: ignore[override]
        tools = await super().list_tools()
        if self._request_is_admin():
            return tools
        return [t for t in tools if t.name not in _ADMIN_TOOLS]

    def _request_is_admin(self) -> bool:
        try:
            return is_admin_user(current_user_id(self.get_context()))
        except Exception:
            return False


def _transport_security() -> TransportSecuritySettings:
    """DNS-rebinding protection config for the Streamable-HTTP transport.

    That protection targets *localhost* servers (a malicious web page tricking a
    browser into calling 127.0.0.1). This server is public and Bearer-token
    gated, so the default host check only blocks legitimate access behind a real
    domain (HTTP 421 "Invalid Host header"). Default: OFF. Set MCP_ALLOWED_HOSTS
    (comma-separated; wildcards like ``*.onrender.com`` allowed) to lock it down.
    """
    hosts = [h.strip() for h in os.getenv("MCP_ALLOWED_HOSTS", "").split(",") if h.strip()]
    origins = [o.strip() for o in os.getenv("MCP_ALLOWED_ORIGINS", "").split(",") if o.strip()]
    # Gate on hosts only. The host allow-list is what enforces the check; turning
    # protection on with an empty allowed_hosts (e.g. only MCP_ALLOWED_ORIGINS
    # set) would reject every request with HTTP 421. Origins refine an
    # already-locked-down server, so they ride along but never enable it alone.
    if hosts:
        return TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=hosts,
            allowed_origins=origins,
        )
    return TransportSecuritySettings(enable_dns_rebinding_protection=False)


def build_mcp(
    backend: Any,
    *,
    name: str = "CodeKeeper",
    auth_provider: Any = None,
    auth_settings: Any = None,
    repo_backend: Any = None,
    rate_limit_per_minute: int = DEFAULT_RATE_LIMIT_PER_MINUTE,
) -> FastMCP:
    kwargs: dict[str, Any] = {
        "instructions": _INSTRUCTIONS,
        "stateless_http": True,
        "transport_security": _transport_security(),
    }
    if auth_provider is not None and auth_settings is not None:
        # Enables the SDK's OAuth endpoints (.well-known / authorize / token /
        # register) plus the auth layer that calls provider.load_access_token.
        kwargs["auth_server_provider"] = auth_provider
        kwargs["auth"] = auth_settings
    mcp: FastMCP = AdminAwareFastMCP(
        name, tool_rate_limiter=ToolRateLimiter(rate_limit_per_minute), **kwargs
    )
    # PostHog MCP analytics. Additive: no tool is changed and no tool schema is
    # touched. Must run before ``streamable_http_app()`` below, which the same
    # call also wraps. See ``mcp_server/analytics.py`` for the privacy gate.
    instrument_mcp_server(mcp)

    @mcp.tool(
        name="codekeeper_list_files",
        description=(
            "List the user's saved code files (metadata only, no code)."
            + _DESCRIPTION_AGE_DOC
        ),
        annotations=_READ_ONLY_TOOL,
    )
    def list_files(ctx: Context, page: int = 1, per_page: int = 50) -> dict:
        return handlers.list_files(backend, current_user_id(ctx), page=page, per_page=per_page)

    @mcp.tool(
        name="codekeeper_search_code",
        # התיאור היה משפט אחד שלא אמר דבר על סמנטיקת ההתאמה, ולכן סוכן
        # הניח substring כמו בשני החיפושים האחרים, חיפש ``**`` או שם
        # חלקי, קיבל אפס — והסיק שהמחרוזת אינה קיימת. המנוע כאן הוא
        # ``$text`` של מונגו, והוא מתאים מילים שלמות. נמדד: ``handof``
        # מחזיר אפס בזמן ש-``handoff`` מחזיר שלוש תוצאות.
        description=(
            "Search the user's saved files by text; returns file metadata "
            "(no content). Matching is by whole words, not substrings: "
            "`handof` does not find `handoff`, and a query of punctuation "
            "alone — `**`, `[`, `()` — matches nothing at all, because "
            "punctuation is not indexed as a word. This is the one search "
            "tool that does NOT do substring matching; for a literal string "
            "inside a mirrored repo use codekeeper_search_repo, and inside "
            "one saved file use the query parameter of codekeeper_get_file."
            + _DESCRIPTION_AGE_DOC
        ),
        annotations=_READ_ONLY_TOOL,
    )
    def search_code(ctx: Context, query: str, language: str | None = None, limit: int = 20) -> dict:
        results = handlers.search_code(
            backend, current_user_id(ctx), query=query, language=language, limit=limit
        )
        return {"query": query, "count": len(results), "results": results}

    @mcp.tool(
        name="codekeeper_get_file",
        description=(
            "Get a file's full content by name or id (optional version number). "
            + _RANGE_DOC
            # **הפירוט על ``query`` יושב בתיאור הפרמטר ולא כאן**, מאותה סיבה
            # שהפירוט על ``outline`` ועל ``symbol`` עבר משם: צירופו לכאן הביא
            # את התיאור ל-1,726 תווים, מעל התקרה שהלקוח מגיש. מה שנשאר כאן
            # הוא **ההפניה** — סוכן שלא יֵדע ש-``query`` קיים לא יפתח את סכמת
            # הפרמטרים כדי לגלות אותו, וזה בדיוק הפיצ'ר שאף אחד לא קורא לו.
            # ההפניה נאכפת בטסט, בשני קצותיה.
            + ' Or pass query="..." to get only the lines that contain a'
            " string, instead of the content — see the query parameter."
            + _DESCRIPTION_AGE_DOC
        ),
        annotations=_READ_ONLY_TOOL,
    )
    def get_file(
        ctx: Context,
        file_name: str | None = None,
        file_id: str | None = None,
        version: int | None = None,
        lines: StrictLines | None = None,
        query: Annotated[str | None, Field(description=_QUERY_DOC)] = None,
        context_lines: StrictInt | None = None,
        max_results: int | None = None,
    ) -> dict:
        doc = handlers.get_file(
            backend,
            current_user_id(ctx),
            file_name=file_name,
            file_id=file_id,
            version=version,
            lines=lines,
            query=query,
            context_lines=context_lines,
            max_results=max_results,
        )
        if doc is None:
            return {"found": False}
        # מעטפת שגיאה של טווח לא חוקי אינה "קובץ" — היא מוחזרת כפי שהיא,
        # באותה צורה שבה ``codekeeper_get_repo_file`` מדווח על אותה שגיאה.
        if doc.get("ok") is False:
            return doc
        # תשובת ``query`` היא כבר מעטפת שלמה — ``found`` ו-``file`` בתוכה,
        # ולצידם המופעים. עטיפה נוספת הייתה קוברת אותה תחת ``file``.
        #
        # התנאי הוא **מה שביקשנו** ולא צורת מה שחזר: בדיקה על
        # ``doc["status"]`` הייתה מסתעפת לפי שדה במסמך של המשתמש, ומסמך
        # שנושא במקרה שדה בשם הזה היה משנה את צורת התשובה.
        if query is not None:
            return doc
        return {"found": True, "file": doc}

    @mcp.tool(
        name="codekeeper_save_file",
        description=(
            "Create a NEW file. Refuses with file_exists when file_name is already "
            "taken: saving over it would bury the old content, which the search and "
            "the file page both show by latest version only. Change an existing file "
            "with codekeeper_edit_file / codekeeper_append_file — those keep the old "
            "versions. The description set here applies to a new file only; to "
            "refresh a stale description on a file that already exists, use "
            "codekeeper_update_file_description, which changes nothing else. "
            "Requires write permission."
        ),
        annotations=_WRITE_TOOL,
    )
    def save_file(
        ctx: Context,
        file_name: str,
        code: str,
        language: str | None = None,
        description: str = "",
    ) -> dict:
        require_write(ctx)  # reject a read-only token before touching anything
        return handlers.save_file(
            backend,
            current_user_id(ctx),
            file_name=file_name,
            code=code,
            language=language,
            description=description,
        )

    @mcp.tool(
        name="codekeeper_edit_file",
        description=(
            "Edit an existing file by exact find-and-replace (old_string -> new_string) "
            "without resending the whole file; saved as a new non-destructive version. "
            "old_string must match exactly, whitespace included; if it occurs more than "
            "once, pass a longer unique snippet or set replace_all=true. "
            "Requires write permission."
        ),
        annotations=_WRITE_TOOL,
    )
    def edit_file(
        ctx: Context,
        file_name: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> dict:
        require_write(ctx)  # reject a read-only token before touching anything
        return handlers.edit_file(
            backend,
            current_user_id(ctx),
            file_name=file_name,
            old_string=old_string,
            new_string=new_string,
            replace_all=replace_all,
        )

    @mcp.tool(
        name="codekeeper_append_file",
        description=(
            "Append text to the end of an existing file without resending it (a newline "
            "separator is inserted first when the file doesn't end with one); saved as "
            "a new non-destructive version. Requires write permission."
        ),
        annotations=_WRITE_TOOL,
    )
    def append_file(ctx: Context, file_name: str, content: str) -> dict:
        require_write(ctx)  # reject a read-only token before touching anything
        return handlers.append_file(
            backend, current_user_id(ctx), file_name=file_name, content=content
        )

    @mcp.tool(
        name="codekeeper_update_file_description",
        # **התיאור קצר בכוונה, והקיצור עצמו הוא החלטה.** גרסה קודמת שלו
        # עמדה על כמעט 1,000 תווים ונשאה שישה דברים שסוכן אינו צריך: מה
        # הוובאפ מציע (הוא לא שם), ש-``codekeeper_list_versions`` לא יראה
        # את השינוי (נגזר מ"לא נוצרת גרסה"), מה תחזיר קריאה של גרסה ישנה
        # (פירוט יתר של המשפט על הגרסה האחרונה), שתגיות אינן נוגעות (שם
        # הכלי אומר ``description``), שאין התראה (לא קיים בעולם של הסוכן),
        # ושתיאור ארוך נדחה עם המגבלה (הודעת השגיאה אומרת זאת כשהיא
        # מגיעה, ולפני כן היא רעש).
        #
        # מה שנשאר הוא מה שמשנה **בזמן הבחירה**: מה הכלי עושה, מתי לבחור
        # בו על פני האחרים, ומה בלתי הפיך. הפירוט המלא חי ב-
        # ``docs/mcp-server.rst`` (``mcp-update-description``) — שם יש מקום,
        # וכאן כל משפט מתחרה על תשומת הלב של הסוכן.
        description=(
            "Replace an existing file's description without changing its "
            "content. Use it when the stored description no longer matches the "
            "file: codekeeper_save_file sets a description only on a new file, "
            "and the edit tools keep the old one. No new version is created, so "
            "the previous description is not kept in history. The reply returns "
            "it, and that is the only copy. Only the latest version is updated. "
            "An empty description clears it. Calling it marks the description "
            "as checked and resets description_age_versions to 0, so sending "
            "the same text says it still fits. Requires write permission."
        ),
        annotations=_UPDATE_IN_PLACE_TOOL,
    )
    def update_file_description(ctx: Context, file_name: str, description: str) -> dict:
        require_write(ctx)  # reject a read-only token before touching anything
        return handlers.update_file_description(
            backend,
            current_user_id(ctx),
            file_name=file_name,
            description=description,
        )

    @mcp.tool(
        name="codekeeper_list_versions",
        description="List all saved versions of a file by file_name (metadata only).",
        annotations=_READ_ONLY_TOOL,
    )
    def list_versions(ctx: Context, file_name: str) -> dict:
        versions = handlers.list_versions(backend, current_user_id(ctx), file_name=file_name)
        return {"file_name": file_name, "count": len(versions), "versions": versions}

    @mcp.tool(
        name="codekeeper_list_collections",
        description="List the user's collections (named folders of files).",
        annotations=_READ_ONLY_TOOL,
    )
    def list_collections(ctx: Context, limit: int = 100) -> dict:
        return handlers.list_collections(backend, current_user_id(ctx), limit=limit)

    @mcp.tool(
        name="codekeeper_get_collection",
        description="Get a single collection by its id.",
        annotations=_READ_ONLY_TOOL,
    )
    def get_collection(ctx: Context, collection_id: str) -> dict:
        return handlers.get_collection(backend, current_user_id(ctx), collection_id=collection_id)

    @mcp.tool(
        name="codekeeper_get_collection_items",
        description="List files in a collection (paginated); optional folder filter.",
        annotations=_READ_ONLY_TOOL,
    )
    def get_collection_items(
        ctx: Context,
        collection_id: str,
        page: int = 1,
        per_page: int = 50,
        folder: str | None = None,
    ) -> dict:
        return handlers.get_collection_items(
            backend,
            current_user_id(ctx),
            collection_id=collection_id,
            page=page,
            per_page=per_page,
            folder=folder,
        )

    @mcp.tool(
        name="codekeeper_list_notes",
        description=(
            "List the user's sticky notes attached to a file (by file_name): content, "
            "color (hex) and color_id (palette id, or empty when not in the "
            "palette), anchored line, timestamps. Same notes shown in the web UI. "
            "include_content=false lists them without their bodies (with the size of "
            "each), and codekeeper_get_note reads one note by its id."
        ),
        annotations=_READ_ONLY_TOOL,
    )
    def list_notes(
        ctx: Context,
        file_name: str,
        include_content: Annotated[bool, Field(description=_INCLUDE_CONTENT_PARAM_DOC)] = True,
    ) -> dict:
        return handlers.list_notes(
            backend, current_user_id(ctx), file_name=file_name, include_content=include_content
        )

    @mcp.tool(
        name="codekeeper_create_note",
        description=(
            "Attach a sticky note to an existing saved file. Optional line anchors it to "
            "a 1-indexed source line (as read via codekeeper_get_file); without line the "
            "note floats at a default position. Notes appear in the CodeKeeper web UI. "
            "Requires write permission."
        ),
        annotations=_WRITE_TOOL,
    )
    def create_note(
        ctx: Context,
        file_name: str,
        content: str,
        line: int | None = None,
        color: Annotated[str | None, Field(description=_NOTE_COLOR_PARAM_DOC)] = None,
        anchor_text: str | None = None,
    ) -> dict:
        require_write(ctx)  # דחיית טוקן קריאה-בלבד לפני כל נגיעה בנתונים
        return handlers.create_note(
            backend,
            current_user_id(ctx),
            file_name=file_name,
            content=content,
            line=line,
            color=color,
            anchor_text=anchor_text,
        )

    @mcp.tool(
        name="codekeeper_list_boards",
        description=(
            "List the user's note boards — surfaces that hold sticky notes belonging to "
            "no file (a to-do list, ideas, anything without a natural home in a file). "
            "Returns id, name, whether it is the default board, and a note count. "
            "Creates the default board on first call."
        ),
        annotations=_READ_ONLY_TOOL,
    )
    def list_boards(ctx: Context) -> dict:
        return handlers.list_boards(backend, current_user_id(ctx))

    @mcp.tool(
        name="codekeeper_list_board_notes",
        description=(
            "List the sticky notes on one board (by board_id from codekeeper_list_boards). "
            "Same notes shown on the board page in the web UI. Use codekeeper_list_notes "
            "instead for notes attached to a file. On a large board a full listing can "
            "exceed what a client shows: pass include_content=false to list the notes "
            "without their bodies (" + _LEAN_NOTE_FIELDS_DOC + "), then read the "
            "ones you need with codekeeper_get_note by id."
        ),
        annotations=_READ_ONLY_TOOL,
    )
    def list_board_notes(
        ctx: Context,
        board_id: str,
        include_content: Annotated[bool, Field(description=_INCLUDE_CONTENT_PARAM_DOC)] = True,
    ) -> dict:
        return handlers.list_board_notes(
            backend, current_user_id(ctx), board_id=board_id, include_content=include_content
        )

    @mcp.tool(
        name="codekeeper_create_board_note",
        description=(
            "Add a sticky note to a board (board_id from codekeeper_list_boards). Unlike "
            "codekeeper_create_note this needs no file. mode is 'surface' (sits on the "
            "board, default) or 'screen' (floats against the viewport). An optional title "
            "labels the note and must be unique on that board. Requires write permission."
        ),
        annotations=_WRITE_TOOL,
    )
    def create_board_note(
        ctx: Context,
        board_id: str,
        content: str,
        color: Annotated[str | None, Field(description=_NOTE_COLOR_PARAM_DOC)] = None,
        mode: str | None = None,
        title: str | None = None,
    ) -> dict:
        require_write(ctx)  # דחיית טוקן קריאה-בלבד לפני כל נגיעה בנתונים
        return handlers.create_board_note(
            backend,
            current_user_id(ctx),
            board_id=board_id,
            content=content,
            color=color,
            mode=mode,
            title=title,
        )

    @mcp.tool(
        name="codekeeper_update_note",
        description=(
            "Update an existing sticky note by note_id (from codekeeper_list_notes or "
            "codekeeper_get_note): any "
            "of content, line, color, anchor_text, is_minimized. Overwrites in place; "
            "when the content changes, the previous body is kept as a version (up to a "
            "fixed number of recent revisions), readable with "
            "codekeeper_list_note_versions. Requires write permission."
        ),
        annotations=_UPDATE_IN_PLACE_TOOL,
    )
    def update_note(
        ctx: Context,
        note_id: str,
        content: str | None = None,
        line: int | None = None,
        color: Annotated[str | None, Field(description=_NOTE_COLOR_PARAM_DOC)] = None,
        anchor_text: str | None = None,
        is_minimized: bool | None = None,
    ) -> dict:
        require_write(ctx)  # דחיית טוקן קריאה-בלבד לפני כל נגיעה בנתונים
        return handlers.update_note(
            backend,
            current_user_id(ctx),
            note_id=note_id,
            content=content,
            line=line,
            color=color,
            anchor_text=anchor_text,
            is_minimized=is_minimized,
        )

    # -- פתקי ריפו + חיפוש -------------------------------------------------
    #
    # שני כלי פתקי הריפו הם **אדמין בלבד**, כמו ארבעת כלי דפדפן הריפו — אבל
    # נרשמים כאן ולא ב-``_register_repo_tools``, כי הם אינם נוגעים במראה
    # אלא ב-``sticky_notes``. פריסה בלי ``repo_backend`` עדיין מחזיקה אותם.
    @mcp.tool(
        name="codekeeper_list_repo_notes",
        description=(
            "[Admin] List the sticky notes on one file inside a mirrored repository "
            "(repo_name + repo_path, the path as it appears in the repo tree). The same "
            "notes shown in the repo browser in the web UI. The target carries no branch: "
            "a note written on main also shows on a PR branch. Returns orphaned=true when "
            "the path is no longer in the mirrored tree — the notes are still returned."
        ),
        annotations=_READ_ONLY_TOOL,
    )
    def list_repo_notes(ctx: Context, repo_name: str, repo_path: str) -> dict:
        # ערך ההחזרה של ``require_admin`` **הוא** המזהה המאומת. שימוש בו —
        # במקום קריאה שנייה ל-``current_user_id`` — מונע מצב שבו הזהות
        # ששימשה לשער נבדלת מזו ששימשה לשאילתה.
        user_id = require_admin(ctx)
        return handlers.list_repo_notes(
            backend, user_id, repo_name=repo_name, repo_path=repo_path
        )

    @mcp.tool(
        name="codekeeper_list_repo_note_paths",
        description=(
            "[Admin] Map which files inside a mirrored repository carry sticky notes: "
            "returns the repo_path of each, with how many notes sit on it. Start here — "
            "codekeeper_list_repo_notes needs the exact path up front, so without this "
            "map a note can only be found by whoever wrote it. Feed a returned repo_path "
            "straight into codekeeper_list_repo_notes to read the notes themselves."
        ),
        annotations=_READ_ONLY_TOOL,
    )
    def list_repo_note_paths(ctx: Context, repo_name: str) -> dict:
        # ערך ההחזרה של ``require_admin`` **הוא** המזהה המאומת — כמו
        # ב-``list_repo_notes``, ומאותה סיבה.
        user_id = require_admin(ctx)
        return handlers.list_repo_note_paths(backend, user_id, repo_name=repo_name)

    @mcp.tool(
        name="codekeeper_create_repo_note",
        description=(
            "[Admin] Attach a sticky note to a file inside a mirrored repository "
            "(repo_name + repo_path). The note is a remark ABOUT the file — it is stored "
            "in CodeKeeper and never touches the mirror or the GitHub repo. mode is "
            "'surface' (default) or 'screen'. An optional title labels the note and must "
            "be unique on that file. Requires write permission."
        ),
        annotations=_WRITE_TOOL,
    )
    def create_repo_note(
        ctx: Context,
        repo_name: str,
        repo_path: str,
        content: str,
        color: Annotated[str | None, Field(description=_NOTE_COLOR_PARAM_DOC)] = None,
        mode: str | None = None,
        title: str | None = None,
    ) -> dict:
        # **אדמין לפני כתיבה, ולא ההפך.** בסדר ההפוך משתמש רגיל היה מקבל
        # "צריך טוקן כתיבה" — רמז שטוקן אחר יפתח לו את הכלי, וזה שקר.
        user_id = require_admin(ctx)
        require_write(ctx)
        return handlers.create_repo_note(
            backend,
            user_id,
            repo_name=repo_name,
            repo_path=repo_path,
            content=content,
            color=color,
            mode=mode,
            title=title,
        )

    @mcp.tool(
        name="codekeeper_add_to_collection",
        description=(
            "Add an existing saved file to an existing collection (collection_id from "
            "codekeeper_list_collections). Use after codekeeper_save_file: saving does not "
            "place a file in a collection. Optional folder and note label it inside the "
            "collection. Fails loudly if the collection or the file does not exist. "
            "Requires write permission."
        ),
        annotations=_WRITE_TOOL,
    )
    def add_to_collection(
        ctx: Context,
        collection_id: str,
        file_name: str,
        folder: str | None = None,
        note: str | None = None,
    ) -> dict:
        require_write(ctx)  # דחיית טוקן קריאה-בלבד לפני כל נגיעה בנתונים
        return handlers.add_to_collection(
            backend,
            current_user_id(ctx),
            collection_id=collection_id,
            file_name=file_name,
            folder=folder,
            note=note,
        )

    @mcp.tool(
        name="codekeeper_note_str_replace",
        description=(
            "Exact find-and-replace inside ONE sticky note (note_id from "
            "codekeeper_get_note, codekeeper_list_notes or codekeeper_search_notes) — send "
            "only the changed snippet, never the whole note. Same semantics as "
            "codekeeper_edit_file: an old_string matching more than once is refused "
            "unless replace_all=true. The write is guarded: if the note changed since "
            "it was read, the answer is conflict — read it again with codekeeper_get_note, "
            "take old_string from that body, and call this tool again. The previous body "
            "is kept as a version, readable with codekeeper_list_note_versions. NOT "
            "idempotent — do not blindly retry: a repeated call re-applies the "
            "replacement to the already-edited body. Requires write permission."
        ),
        annotations=_REPLACE_IN_PLACE_TOOL,
    )
    def note_str_replace(
        ctx: Context,
        note_id: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> dict:
        require_write(ctx)  # דחיית טוקן קריאה-בלבד לפני כל נגיעה בנתונים
        return handlers.note_str_replace(
            backend,
            current_user_id(ctx),
            note_id=note_id,
            old_string=old_string,
            new_string=new_string,
            replace_all=replace_all,
        )

    @mcp.tool(
        name="codekeeper_list_note_versions",
        description=(
            "Previous revisions of one sticky note (metadata only: version number, when "
            "it was saved, its length in characters — not bytes), newest first. A "
            "revision is kept every time "
            "the note's content is overwritten, up to a fixed number of the most recent "
            "ones. Read one with codekeeper_get_note_version; the current body is "
            "codekeeper_get_note."
        ),
        annotations=_READ_ONLY_TOOL,
    )
    def list_note_versions(ctx: Context, note_id: str) -> dict:
        return handlers.list_note_versions(backend, current_user_id(ctx), note_id=note_id)

    @mcp.tool(
        name="codekeeper_get_note_version",
        description=(
            "Read the content of one PREVIOUS revision of a sticky note (version number "
            "from codekeeper_list_note_versions). The current body is codekeeper_get_note, "
            "which also says which number that body carries — the number this tool will "
            "read it by once it is overwritten through this server (a web-app edit is "
            "not kept in history). To restore a revision, pass its content back to "
            "codekeeper_update_note."
        ),
        annotations=_READ_ONLY_TOOL,
    )
    def get_note_version(ctx: Context, note_id: str, version: int) -> dict:
        return handlers.get_note_version(
            backend, current_user_id(ctx), note_id=note_id, version=version
        )

    # קריאה טהורה — ``readOnlyHint`` אמיתי, לא כמו ``list_boards`` שמוצהר
    # קריאה ובכל זאת יוצר לוח ברירת מחדל (שם זו הכרעה מנומקת, לא תקדים).
    # **אינו** כלי אדמין ואינו ב-``_ADMIN_TOOLS``: פתק ריפו חסום לאדמין בתוך
    # הגוף, ומי שאינו אדמין מקבל עליו ``not_found`` — לא סירוב שמגלה שהמזהה
    # קיים, ולכן גם לא ``require_admin`` שזורק.
    @mcp.tool(
        name="codekeeper_get_note",
        description=(
            "Read ONE sticky note by note_id — the id every note carries in "
            "codekeeper_list_notes, codekeeper_list_board_notes and codekeeper_search_notes. "
            "Use it instead of listing a whole board or file, which can exceed what a client "
            "shows; one note is bounded. The reply carries the note (content, title, color, "
            "color_id, timestamps); version — the number of the CURRENT body (null for an "
            "empty body), which codekeeper_get_note_version reads back by that number once "
            "the body has been overwritten through this server (a web-app edit is not kept in "
            "history); and where the note sits, in exactly the arguments the matching list "
            "tool takes: target with file_name, board_id, or repo_name + repo_path (a repo "
            "note also says orphaned=true when its path is no longer in the mirrored tree). "
            "content is the stored text, byte for byte: copy an old_string for "
            "codekeeper_note_str_replace from it, and repeat this read when that tool answers "
            "conflict. A note you do not own answers not_found, and so does a note on a "
            "mirrored repository unless you are the admin; a note being edited right now "
            "answers conflict — read it again."
        ),
        annotations=_READ_ONLY_TOOL,
    )
    def get_note(ctx: Context, note_id: str) -> dict:
        # זהות אחת לשער ולשאילתה: ``is_admin`` נגזר מאותו ``user_id`` שנשלח
        # ל-handler, ולא מקריאה שנייה ל-``current_user_id`` — אותה הכרעה
        # שמאחורי השימוש בערך ההחזרה של ``require_admin`` ב-``list_repo_notes``.
        user_id = current_user_id(ctx)
        return handlers.get_note(
            backend, user_id, note_id=note_id, is_admin=is_admin_user(user_id)
        )

    # החיפוש **אינו** אדמין: הוא ``user_id``-scoped ולכן יכול להחזיר רק
    # פתקים של הקורא עצמו, ומשתמש רגיל אינו יכול ליצור פתק ריפו מלכתחילה.
    @mcp.tool(
        name="codekeeper_search_notes",
        description=(
            "Find your sticky notes across all three places a note can sit: a file, a "
            "board, or a file in a mirrored repository. Matches part of the title, "
            "case-insensitively. Set search_content=true to ALSO match the note body — "
            "needed to find the many notes that carry no title at all, and slower because "
            "no index covers the body. Each hit says where the note sits, with exactly the "
            "arguments the matching list tool needs (file_name, board_id, or repo_name + "
            "repo_path) and carries the note's id — read the note itself with "
            "codekeeper_get_note; hits never carry content."
        ),
        annotations=_READ_ONLY_TOOL,
    )
    def search_notes(
        ctx: Context,
        query: str,
        limit: int | None = None,
        search_content: bool = False,
    ) -> dict:
        return handlers.search_notes(
            backend,
            current_user_id(ctx),
            query=query,
            limit=limit,
            search_content=search_content,
        )

    if repo_backend is not None:
        _register_repo_tools(mcp, repo_backend)
        _register_docs_tools(mcp, repo_backend)

    return mcp


def _register_repo_tools(mcp: FastMCP, repo_backend: Any) -> None:
    """Admin-only, read-only repo-browser tools (Phase D).

    Every body calls require_admin FIRST (fail-closed) — the tools/list hiding
    in AdminAwareFastMCP is visibility only. Names must stay in _ADMIN_TOOLS.
    """

    @mcp.tool(
        name="codekeeper_list_repos",
        description="[Admin] List the mirrored repositories (metadata only).",
        annotations=_READ_ONLY_TOOL,
    )
    def list_repos(ctx: Context, limit: int = 50) -> dict:
        require_admin(ctx)
        return repo_handlers.list_repos(repo_backend, limit=limit)

    @mcp.tool(
        name="codekeeper_list_repo_tree",
        description=(
            "[Admin] List file paths in a mirrored repo (paginated; optional "
            "subdirectory/ref filter; paths only, no content). Set "
            "include_stats=true to also get an `entries` list with each path's "
            "byte size and line count, so you can tell a 40-line file from a "
            "2,400-line one before reading it. `lines` comes from the code index "
            "and is null when a file was never indexed; `lines_commit_sha` says "
            "which commit it was counted at, because the index is refreshed by "
            "the webapp's sync rather than by this service."
        ),
        annotations=_READ_ONLY_TOOL,
    )
    def list_repo_tree(
        ctx: Context,
        repo: str,
        path: str | None = None,
        ref: str | None = None,
        page: int = 1,
        per_page: int = 200,
        include_stats: bool = False,
    ) -> dict:
        require_admin(ctx)
        return repo_handlers.list_repo_tree(
            repo_backend,
            repo=repo,
            path=path,
            ref=ref,
            page=page,
            per_page=per_page,
            include_stats=include_stats,
        )

    @mcp.tool(
        name="codekeeper_get_repo_file",
        description=(
            "[Admin] Read one file from a mirrored repo. On sync_in_progress, "
            "retry after retry_after seconds — the file may exist. " + _RANGE_DOC
            # התקרה יושבת בסוף, אחרי הסבר הטווח, ולא לפניו — וכשהיא הופיעה
            # ראשונה היא נקראה יחד עם "instead of the whole file" כאילו הטווח
            # עוקף אותה. עכשיו הוא באמת עוקף, אבל **שתי תקרות שונות**, ולכן
            # שני המספרים חייבים להופיע: סוכן שקיבל ``too_large`` צריך לדעת
            # אם ``lines`` יעזור לו או שהקובץ מעבר לגבול בכל מקרה.

            # התיאור הסביר איך לקרוא טווח, ולא **מאיפה משיגים את המספר**.
            # סוכן שעבד מול המראה יום שלם משך קבצים שלמים כדי להפנות לכלל
            # בודד, וביקש כלי אאוטליין שכבר היה קיים — כלומר לא כלי חסר
            # אלא כלי שלא נמצא. המשפט מתאר את הצעד הבא ולא את האפשרות,
            # ויושב כאן, לפני ``outline=true``, כי שני המשפטים הם שתי
            # התשובות לאותה שאלה: "אני לא יודע איפה בקובץ זה".
            # ``line`` הוא **מספר בודד**, ו-``lines`` דורש זוג: ראו
            # ``handlers.normalize_line_range``, שמחזיר ``invalid_line_range``
            # על כל אורך שאינו 2 (נמדד: ``172`` ו-``[172]`` שניהם נדחים).
            # ולכן הדוגמה נקובה במפורש ולא נאמרת כ"בנה טווח סביבו" — תיאור
            # שקורא לשורה החוזרת "הטווח" שולח את הקורא לקריאה שנדחית.
            + " When you do not know where in the file your target sits, "
            "codekeeper_search_repo returns a `line` for every match — a single "
            "number, so read around it with lines=[line - 20, line + 20], or "
            "lines=[line, line] for that one line."
            # **הפירוט על השפות ועל הסינון יושב בתיאורי הפרמטרים** ``outline``
            # ו-``symbol`` (‏``_OUTLINE_PARAM_DOC`` / ``_SYMBOL_PARAM_DOC``),
            # ולא כאן — הנימוק המלא שם. מה שכן חייב להישאר כאן הוא **ההפניה
            # אליהם**: סוכן שקורא רק את תיאור הכלי ולא יֵדע ש-``symbol=``
            # קיים הוא בדיוק הכשל שהפירוט ההוא נכתב כדי למנוע, רק במיקום
            # אחר. הפניה זו נאכפת בטסט.
            + " Set outline=true for a map instead of content: every definition "
            "with its start and end line, so you can follow up with an exact "
            "lines= range — the outline and symbol parameters say which "
            "languages have a map and how to narrow it. "
            # ``A file type with no map`` ולא ``Anything else``: הניסוח הקודם
            # בא מיד אחרי רשימת השפות, ולכן "else" היה ברור. כאן הרשימה כבר
            # אינה מעליו, ו"anything else" היה מאבד את מה שהוא מתייחס אליו.
            "A file type with no map returns status no_outline. "
            "Size "
            "limits differ by mode: 500KB for a whole file, 10MB with lines or "
            "outline; a file over 50000 symbols returns status no_outline with "
            "reason too_many_symbols and no partial list. "
            "Binary files return metadata only."
        ),
        annotations=_READ_ONLY_TOOL,
    )
    def get_repo_file(
        ctx: Context,
        repo: str,
        path: str,
        ref: str | None = None,
        lines: StrictLines | None = None,
        outline: Annotated[bool, Field(description=_OUTLINE_PARAM_DOC)] = False,
        symbol: Annotated[str | None, Field(description=_SYMBOL_PARAM_DOC)] = None,
        page: int = 1,
        per_page: int = repo_handlers.OUTLINE_PER_PAGE_DEFAULT,
    ) -> dict:
        require_admin(ctx)
        return repo_handlers.get_repo_file(
            repo_backend,
            repo=repo,
            path=path,
            ref=ref,
            lines=lines,
            outline=outline,
            symbol=symbol,
            page=page,
            per_page=per_page,
        )

    @mcp.tool(
        name="codekeeper_search_repo",
        # **שני דברים בתיאור הזה נאכפים בבדיקה, וכל ניסוח מחדש חייב לשמור
        # עליהם:** מה חוזר בכל פגיעה, ומשפט שאומר מה הצעד הבא איתו
        # (``codekeeper_get_repo_file`` עם ``lines=[line - 20, line + 20]``).
        # הפער שנולד ממנו ``test_the_descriptions_name_the_search_to_range_chain``
        # היה תיאור שפירט *מה חוזר* בלי לומר *מה לעשות עם זה*.
        description=(
            "[Admin] Text-search inside a mirrored repo. Returns hits with path, "
            "line and a short snippet; context_lines=N (0-10) adds the lines "
            "around each hit. The next step on a hit is codekeeper_get_repo_file "
            "on that path with lines=[line - 20, line + 20] — the passage, not "
            "the file. The query is literal: no character is special, and "
            "leading/trailing whitespace counts, so \"    return\" finds the "
            "indented line (regex=true for a pattern). Case is ignored unless "
            "case_sensitive=true. `count` is how many hits came back. `total` is "
            "how many exist in what was searched, and appears only when exact; "
            "when counting stopped early the reply carries `total_at_least` and "
            "`truncation_reason` instead. Vendored and compiled code "
            "(node_modules, *.bundle.js, *.min.js, *.min.css, *.map) is "
            "skipped by default, so zero results does not mean the string is "
            "absent; include_vendored=true searches it too."
        ),
        annotations=_READ_ONLY_TOOL,
    )
    def search_repo(
        ctx: Context,
        repo: str,
        query: str,
        file_pattern: str | None = None,
        max_results: int = 50,
        context_lines: StrictInt = 0,
        case_sensitive: Annotated[
            bool,
            Field(
                description=(
                    "false (the default) ignores case, so Config matches "
                    "config. true matches case exactly. It applies with "
                    "regex=true as well, and to `total` — a match the flag "
                    "excludes is not counted either."
                )
            ),
        ] = False,
        include_vendored: Annotated[
            bool,
            Field(
                description=(
                    "false (the default) skips vendored and compiled code — "
                    "node_modules at any depth, plus *.bundle.js, *.min.js, "
                    "*.min.css and *.map — in both the results and the `total`. "
                    "true searches it as well. Those files stay readable through "
                    "codekeeper_get_repo_file either way; this only decides "
                    "what the search looks at."
                )
            ),
        ] = False,
        regex: Annotated[
            bool,
            Field(
                description=(
                    "false (the default) matches the query literally. true reads it "
                    "as a POSIX extended regular expression — use it when you mean "
                    "`.` as any-char or `|` as alternation, and expect "
                    "error `invalid_pattern` when git rejects the pattern."
                )
            ),
        ] = False,
    ) -> dict:
        require_admin(ctx)
        return repo_handlers.search_repo(
            repo_backend,
            repo=repo,
            query=query,
            file_pattern=file_pattern,
            max_results=max_results,
            context_lines=context_lines,
            regex=regex,
            case_sensitive=case_sensitive,
            include_vendored=include_vendored,
        )

    # **נקרא כאן, בזמן הרישום**: אותה תשובה ש-``call_tool`` מסרב לפיה לפני
    # השקילה, כך שהגוף והשער אינם יכולים להחזיק שתי תקרות שונות.
    item_cap = mcp.batch_item_cap()

    @mcp.tool(
        name=read_batch.TOOL_NAME,
        description=_READ_BATCH_DESCRIPTION,
        # ``readOnlyHint: True`` מפורש — בלעדיו ``_declares_write`` (fail-closed)
        # היה שולח את הבאץ' לתור הכתיבה של העובד היחיד, מאחורי כל שמירה.
        annotations=_READ_ONLY_TOOL,
        # Claude Code שומר לקובץ תשובה שעוברת את הסף שלו ומחליף אותה בנתיב;
        # בלי ההצהרה הזו באץ' של סבב ריוויו היה מגיע כקובץ ולא להקשר. הערך
        # והנימוק ליחידות — ליד ``read_batch.MAX_RESULT_CHARS``.
        meta={"anthropic/maxResultSizeChars": read_batch.MAX_RESULT_CHARS},
    )
    def read_batch_items(
        ctx: Context,
        items: Annotated[
            list[Any],
            Field(
                description=_READ_BATCH_ITEMS_DOC,
                # הסכימה של פריט נגזרת מהמודלים שהגוף מאמת לפיהם (``read_batch``),
                # ולכן ה-SDK מקבל כאן ``list[Any]``: פריט פגום נענה כ-``invalid_item``
                # של אותו פריט, ולא מפיל את הקריאה כולה בשגיאת ולידציה.
                json_schema_extra={"items": read_batch.ITEM_JSON_SCHEMA},
            ),
        ],
    ) -> dict:
        # ``def`` ולא ``async def``, בכוונה: ``add_tool`` מעביר גוף סינכרוני
        # ל-``asyncio.to_thread`` — חוט אחד של מאגר הקריאות, שגודלו נגזר
        # ממכסת הזיכרון — והבאץ' רץ כולו בחוט הזה, בלי חוטים פנימיים.
        require_admin(ctx)
        return read_batch.read_batch(
            repo_backend,
            items,
            item_cap=item_cap,
            entered_at=read_batch.ENTERED_AT.get(),
        )


def _register_docs_tools(mcp: FastMCP, repo_backend: Any) -> None:
    """Public, read-only docs tool — return ONE RST section instead of a whole file.

    NOT admin-gated: the body calls ``current_user_id`` (identity only, fail-closed on
    no token), never ``require_admin`` / ``require_write``, and the name is deliberately
    kept OUT of ``_ADMIN_TOOLS``. Reads via ``repo_backend`` (the mirror) like the repo
    tools, but serves public documentation to any authenticated user.
    """

    @mcp.tool(
        name="codekeeper_docs_get_section",
        description=(
            "Read ONE section from a CodeKeeper documentation file — RST or "
            "Markdown — instead of the whole file. Prefer this over "
            "codekeeper_get_repo_file for docs: it returns a single section with "
            "navigation (breadcrumb, direct subsections, prev/next siblings) rather "
            "than a 77KB file. Call with NO `section` to get the page's table of "
            "contents (heading tree) and pick one. To read a whole document, pass its "
            "title (the first TOC entry) as section: you get that heading's subtree, "
            "paged like any section — while truncated is true, continue from "
            "next_offset — or (admin) read it with codekeeper_get_repo_file. Which repo "
            "serves which paths, "
            "in which format, is per-repo — see the `path` parameter. `ref` is a git "
            "ref (default: repo default branch). For large sections, page with "
            "`offset`/`max_chars`. Never returns a bare 'not found': a missing "
            "section returns the full TOC + suggestions; a duplicate heading returns "
            "candidates with breadcrumbs. See the `section` parameter for how a "
            "heading is matched — identifier shortcuts (K11, U3) and headings that "
            "carry backticks."
        ),
        annotations=_READ_ONLY_TOOL,
    )
    def docs_get_section(
        ctx: Context,
        path: Annotated[str, Field(description=_DOCS_PATH_PARAM_DOC)],
        section: Annotated[str | None, Field(description=_SECTION_PARAM_DOC)] = None,
        include_subsections: bool = True,
        max_chars: int = 12000,
        offset: int = 0,
        repo: str | None = None,
        ref: str | None = None,
    ) -> dict:
        current_user_id(ctx)  # מזהה בלבד — public, בלי require_admin
        return docs_handlers.docs_get_section(
            repo_backend,
            path=path,
            section=section,
            include_subsections=include_subsections,
            max_chars=max_chars,
            offset=offset,
            repo=repo,
            ref=ref,
        )


async def _healthz(_request):
    return JSONResponse({"status": "ok", "service": "codekeeper-mcp"})


def build_app(
    backend: Any,
    token_store: Any = None,
    *,
    auth_provider: Any = None,
    auth_settings: Any = None,
    consent_routes: Any = None,
    repo_backend: Any = None,
    name: str = "CodeKeeper",
    max_request_bytes: int = DEFAULT_MAX_REQUEST_BYTES,
    rate_limit_per_minute: int = DEFAULT_RATE_LIMIT_PER_MINUTE,
):
    """Build the authenticated Streamable-HTTP ASGI app.

    Two auth modes:
    - OAuth (auth_provider + auth_settings given): the SDK mounts the OAuth
      endpoints and verifies via provider.load_access_token — which also accepts
      PATs, so Claude Code and Claude.ai both work. ``consent_routes`` are mounted.
    - PAT-only (fallback): the custom ``PATAuthMiddleware`` guards the app.
    """
    oauth = auth_provider is not None and auth_settings is not None
    mcp = build_mcp(
        backend,
        name=name,
        auth_provider=auth_provider if oauth else None,
        auth_settings=auth_settings if oauth else None,
        repo_backend=repo_backend,
        rate_limit_per_minute=rate_limit_per_minute,
    )
    app = mcp.streamable_http_app()  # Starlette app exposing POST/GET /mcp
    # Drain analytics on ASGI shutdown, before uvicorn's event loop closes.
    attach_shutdown_drain(app)
    # Size and install the read pool at ASGI startup, and emit the capacity
    # line from there. **After ``attach_shutdown_drain``, on purpose:** the
    # wrapper attached last is the outermost, so the pool exists before the
    # SDK's session manager starts, and at shutdown the PostHog drain — which
    # uses ``asyncio.to_thread`` — still runs on a live pool before this
    # wrapper exits. The capacity line used to be emitted right here, after
    # ``build_mcp``, and that ordering was the fix for #3393: before
    # ``FastMCP.__init__`` nothing had configured logging and the record was
    # dropped where it stood. The lifespan runs later still, so that property
    # is kept — and the line now describes a pool that exists rather than one
    # it expected.
    attach_read_pool(app)
    # Unauthenticated health endpoint for the hosting platform.
    app.router.routes.append(Route("/healthz", _healthz, methods=["GET"]))
    # GET /api/agent/primer. Authenticates INSIDE its own handler, in both modes:
    # in OAuth mode the SDK's RequireAuthMiddleware wraps only the /mcp mount, so
    # a route appended here would otherwise be served with no auth at all. It is
    # handed the same verifier the MCP transport uses — never a second one.
    app.router.routes.append(
        agent_primer_route(
            backend,
            token_store=token_store,
            auth_provider=auth_provider if oauth else None,
        )
    )
    # Request-body cap for every route, in both auth modes (#3431). Added
    # before ``PATAuthMiddleware`` on purpose: ``add_middleware`` inserts at the
    # front of the stack (``starlette/applications.py``, Starlette 1.6.0), so the
    # middleware added last is the outermost — the PAT check stays outside, and an
    # unauthenticated oversized POST is a 401 before it is a 413. In OAuth mode
    # the SDK's auth wraps only the ``/mcp`` mount, so here the cap is the
    # outermost app-level layer: it refuses a declared 20MB body before any
    # credential is looked at, and hands a declared body under the cap on
    # *unread*, so the SDK's 401 still comes without a byte of it read
    # (SEC-001 in the seven-PR review; the drain that remains, for a body with
    # no declared length, is bounded by the cap and by a deadline —
    # ``mcp_server/limits.py``). ``/healthz`` is a GET, and GET is not a
    # method the cap looks at, so a spoofed ``Content-Length`` there is not a
    # 413; both modes pin that in ``tests/test_mcp_limits.py``.
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=max_request_bytes)
    if oauth:
        for route in consent_routes or []:
            app.router.routes.append(route)
    else:
        app.add_middleware(PATAuthMiddleware, token_store=token_store)
    logger.info(
        "mcp request limits: body <= %d bytes (413 %s), tool calls <= %s per identity "
        "per minute (%s); /healthz sits outside both",
        max_request_bytes,
        BODY_TOO_LARGE,
        rate_limit_per_minute if rate_limit_per_minute > 0 else "unlimited",
        RATE_LIMITED,
    )
    return app
