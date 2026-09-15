"""FastMCP server wiring: tools + resources + the authenticated ASGI app.

``build_mcp`` registers the read-only tools against an injected ``Backend``.
``build_app`` returns a Starlette ASGI app (Streamable HTTP) wrapped with PAT
auth plus an unauthenticated ``/healthz`` endpoint for platform health checks.

Tools are defined as **sync** functions on purpose, and :class:`AdminAwareFastMCP`
moves each one onto a worker thread at registration — see
:func:`_offload_to_thread`. Read tools go to the loop's shared default executor
via ``asyncio.to_thread``; write tools go to :data:`_WRITE_POOL`, a pool of one
worker, so exactly one write body runs at a time and the queue hands them over
in the order they arrived.

Until #3379 this docstring claimed the SDK ran sync tools on a worker thread by
itself. **It does not**, and that wrong belief is why nobody looked: measured
against ``mcp 1.28.1``, ``func_metadata.call_fn_with_arg_validation`` calls a
sync tool as ``return fn(**arguments_parsed_dict)`` — on the event loop, with no
``to_thread`` anywhere on the path. Keeping this paragraph accurate is not
housekeeping: the wrong version of it is the whole reason the bug survived.
"""

from __future__ import annotations

import asyncio
import contextvars
import functools
import inspect
import logging
import os
import pathlib
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Annotated, Any

from mcp.server.fastmcp import Context, FastMCP
from pydantic import Field
from mcp.server.transport_security import TransportSecuritySettings
from starlette.responses import JSONResponse
from starlette.routing import Route

from . import docs_handlers, handlers, repo_handlers
from .handlers import StrictInt, StrictLines
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
    "are found. "
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

# In-place update (sticky-note edit): overwrites the note. Idempotent (same
# input twice ⇒ same final state).
#
# **``destructiveHint`` נשאר ``True`` גם אחרי שנוספה היסטוריה.** השחזור
# חסום ל-``NOTE_VERSION_RETENTION`` גרסאות אחרונות, ולכן אחרי מספיק עריכות
# המקור נדחף החוצה — כלומר אובדן עדיין אפשרי. ההנחיה ללקוח מתארת את המקרה
# הגרוע, לא את הרגיל.
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
#: ``save_file`` body runs 7.5s at p95, so a threshold below one whole body
#: would fire every time two writes from the same agent arrive together — the
#: ordinary case, and an alert that fires on the ordinary case is noise. Past
#: this, the caller waited for more than one complete write ahead of it, which
#: is the shape of a queue that is not draining rather than of a busy moment.
_SLOW_WRITE_QUEUE_WAIT = 10.0

#: ``FastMCP.add_tool``'s own signature, read once at import so that the
#: position of ``annotations`` is never a number written down here.
_ADD_TOOL_SIGNATURE = inspect.signature(FastMCP.add_tool)


def _cpu_budget() -> str:
    """What the container is actually allowed, as opposed to what Python sees.

    ``os.cpu_count()`` is the machine's CPU count, and CPython says so in as
    many words: *"This number is not equivalent to the number of CPUs the
    current process can use."* Inside a container it is the host's, while the
    service may be allowed a fraction of one core — and the read pool is sized
    from the former. Printing the quota beside it is what turns that gap from a
    suspicion into a number.

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


def _log_dispatch_capacity() -> None:
    """One line at startup naming the concurrency the dispatch model actually has.

    The read pool's size is ``min(32, os.cpu_count() + 4)`` and nothing in the
    service reported it, so the ceiling on concurrent reads was a number nobody
    could look up — including while reasoning about whether it needed one. Every
    value is computed before the call rather than inside it, so a level guard or
    a deleted line takes the line and nothing else with it.
    """
    detected = os.cpu_count() or 1
    try:
        usable = len(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        usable = detected
    read_pool = min(32, detected + 4)
    quota = _cpu_budget()
    logger.info(
        "mcp dispatch capacity: read pool %d threads (os.cpu_count=%d, "
        "usable=%d), write pool 1 thread, cpu quota %s",
        read_pool,
        detected,
        usable,
        quota,
    )


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
    one worker runs one write at a time and a write body is 4.3-4.9s at p50, so
    this line is bounded at roughly thirteen a minute no matter how much load
    arrives. And logging only the slow case would say when the wait is bad
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
    loop's shared default executor, where several reads run at once. A write
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


class AdminAwareFastMCP(FastMCP):
    """FastMCP that hides the admin-only tools from non-admin tools/list, and
    keeps every tool body off the event loop.

    The SDK's tools/list is static (one ToolManager), but the auth context IS
    available inside the handler, so we filter per request. Fail-closed: any
    doubt (no request context, unauthenticated, lookup error) ⇒ non-admin view.
    """

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
    mcp: FastMCP = AdminAwareFastMCP(name, **kwargs)
    # PostHog MCP analytics. Additive: no tool is changed and no tool schema is
    # touched. Must run before ``streamable_http_app()`` below, which the same
    # call also wraps. See ``mcp_server/analytics.py`` for the privacy gate.
    instrument_mcp_server(mcp)

    @mcp.tool(
        name="codekeeper_list_files",
        description="List the user's saved code files (metadata only, no code).",
        annotations=_READ_ONLY_TOOL,
    )
    def list_files(ctx: Context, page: int = 1, per_page: int = 50) -> dict:
        return handlers.list_files(backend, current_user_id(ctx), page=page, per_page=per_page)

    @mcp.tool(
        name="codekeeper_search_code",
        description="Search the user's code by text; returns file metadata (no content).",
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
            "versions. Requires write permission."
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
            "color, anchored line, timestamps. Same notes shown in the web UI."
        ),
        annotations=_READ_ONLY_TOOL,
    )
    def list_notes(ctx: Context, file_name: str) -> dict:
        return handlers.list_notes(backend, current_user_id(ctx), file_name=file_name)

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
        color: str | None = None,
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
            "instead for notes attached to a file."
        ),
        annotations=_READ_ONLY_TOOL,
    )
    def list_board_notes(ctx: Context, board_id: str) -> dict:
        return handlers.list_board_notes(backend, current_user_id(ctx), board_id=board_id)

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
        color: str | None = None,
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
            "Update an existing sticky note by note_id (from codekeeper_list_notes): any "
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
        color: str | None = None,
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
        color: str | None = None,
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
            "codekeeper_list_notes or codekeeper_search_notes) — send only the changed "
            "snippet, never the whole note. Same semantics as codekeeper_edit_file: an "
            "old_string matching more than once is refused unless replace_all=true. The "
            "previous body is kept as a version, readable with "
            "codekeeper_list_note_versions. NOT idempotent — do not blindly retry: a "
            "repeated call re-applies the replacement to the already-edited body. "
            "Requires write permission."
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
            "it was saved, how long it was), newest first. A revision is kept every time "
            "the note's content is overwritten, up to a fixed number of the most recent "
            "ones. Read one with codekeeper_get_note_version."
        ),
        annotations=_READ_ONLY_TOOL,
    )
    def list_note_versions(ctx: Context, note_id: str) -> dict:
        return handlers.list_note_versions(backend, current_user_id(ctx), note_id=note_id)

    @mcp.tool(
        name="codekeeper_get_note_version",
        description=(
            "Read the content of one previous revision of a sticky note (version number "
            "from codekeeper_list_note_versions). To restore it, pass the content back to "
            "codekeeper_update_note."
        ),
        annotations=_READ_ONLY_TOOL,
    )
    def get_note_version(ctx: Context, note_id: str, version: int) -> dict:
        return handlers.get_note_version(
            backend, current_user_id(ctx), note_id=note_id, version=version
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
            "repo_path) — read the note itself with that tool; hits never carry content."
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
        description=(
            "[Admin] Text-search inside a mirrored repo; returns short snippets "
            "(path+line), capped and truncated-flagged. Set context_lines=N "
            "(0-10, default 0) to get N lines before and after each hit as "
            "context_before / context_after, instead of fetching the whole file "
            "just to see the surroundings. "
            # ``path+line`` כבר הופיע לעיל, אבל כתיאור של מה שחוזר ולא של
            # מה לעשות איתו — וזה בדיוק מה שלא נקרא. השרשור נאמר במפורש.
            "Every result carries a `line`, so the next step on a hit is "
            # הדוגמה נקובה בצורתה המלאה ולא כ"טווח סביבו": ``line`` הוא מספר
            # בודד, ו-``normalize_line_range`` דוחה כל אורך שאינו 2. סוכן
            # שקורא רק את התיאור הזה, בלי זה של ``get_repo_file``, לא יכול
            # היה לדעת מכאן שהפרמטר הוא זוג.
            "codekeeper_get_repo_file on that path with lines=[line - 20, "
            "line + 20] — the passage itself, not the file."
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
    ) -> dict:
        require_admin(ctx)
        return repo_handlers.search_repo(
            repo_backend,
            repo=repo,
            query=query,
            file_pattern=file_pattern,
            max_results=max_results,
            context_lines=context_lines,
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
            "Read ONE section from a CodeKeeper documentation RST file instead of the "
            "whole file. Prefer this over codekeeper_get_repo_file for docs/*.rst: it "
            "returns a single section with navigation (breadcrumb, direct subsections, "
            "prev/next siblings) rather than a 77KB file. Call with NO `section` to get "
            "the page's table of contents (heading tree) and pick one. Accepts a full "
            "path (docs/x.rst) or short slug (x). `ref` is a git ref (default: repo "
            "default branch). For large sections, page with `offset`/`max_chars`. Never "
            "returns a bare 'not found': a missing section returns the full TOC + "
            "suggestions; a duplicate heading returns candidates with breadcrumbs."
        ),
        annotations=_READ_ONLY_TOOL,
    )
    def docs_get_section(
        ctx: Context,
        path: str,
        section: str | None = None,
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
    )
    # **After ``build_mcp``, and that ordering is the whole point.** The first
    # version of this line ran before it and never appeared in production: at
    # that moment nothing in the process had configured logging, so the root
    # logger was still at ``WARNING`` with no handlers and the record was
    # dropped where it stood. ``FastMCP.__init__`` ends with
    # ``configure_logging(self.settings.log_level)`` (verified in the installed
    # SDK), so by the time ``build_mcp`` returns there is certainly a handler —
    # whoever installed it. ``mcp_server/app.py`` also configures logging on
    # import, which is the fix that makes every other record in this package
    # visible; emitting here as well means this line does not depend on that
    # having happened.
    _log_dispatch_capacity()
    app = mcp.streamable_http_app()  # Starlette app exposing POST/GET /mcp
    # Drain analytics on ASGI shutdown, before uvicorn's event loop closes.
    attach_shutdown_drain(app)
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
    if oauth:
        for route in consent_routes or []:
            app.router.routes.append(route)
    else:
        app.add_middleware(PATAuthMiddleware, token_store=token_store)
    return app
