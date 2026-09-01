"""FastMCP server wiring: tools + resources + the authenticated ASGI app.

``build_mcp`` registers the read-only tools against an injected ``Backend``.
``build_app`` returns a Starlette ASGI app (Streamable HTTP) wrapped with PAT
auth plus an unauthenticated ``/healthz`` endpoint for platform health checks.

Tools are defined as **sync** functions on purpose: FastMCP runs sync tools in a
worker thread, so the blocking (pymongo) backend calls never stall the event
loop, and the tool can still read ``ctx.request_context.request.state``.
"""

from __future__ import annotations

import os
from typing import Any

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.responses import JSONResponse
from starlette.routing import Route

from . import docs_handlers, handlers, repo_handlers
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
    "(metadata only), and codekeeper_get_file to read full contents. Use "
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


class AdminAwareFastMCP(FastMCP):
    """FastMCP that hides the admin-only tools from non-admin tools/list.

    The SDK's tools/list is static (one ToolManager), but the auth context IS
    available inside the handler, so we filter per request. Fail-closed: any
    doubt (no request context, unauthenticated, lookup error) ⇒ non-admin view.
    """

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
        description="Get a file's full content by name or id (optional version number).",
        annotations=_READ_ONLY_TOOL,
    )
    def get_file(
        ctx: Context,
        file_name: str | None = None,
        file_id: str | None = None,
        version: int | None = None,
    ) -> dict:
        doc = handlers.get_file(
            backend, current_user_id(ctx), file_name=file_name, file_id=file_id, version=version
        )
        if doc is None:
            return {"found": False}
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
            "subdirectory/ref filter; paths only, no content)."
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
    ) -> dict:
        require_admin(ctx)
        return repo_handlers.list_repo_tree(
            repo_backend, repo=repo, path=path, ref=ref, page=page, per_page=per_page
        )

    @mcp.tool(
        name="codekeeper_get_repo_file",
        description=(
            "[Admin] Read one file from a mirrored repo (max 500KB; binary files "
            "return metadata only). On sync_in_progress, retry after retry_after "
            "seconds — the file may exist."
        ),
        annotations=_READ_ONLY_TOOL,
    )
    def get_repo_file(ctx: Context, repo: str, path: str, ref: str | None = None) -> dict:
        require_admin(ctx)
        return repo_handlers.get_repo_file(repo_backend, repo=repo, path=path, ref=ref)

    @mcp.tool(
        name="codekeeper_search_repo",
        description=(
            "[Admin] Text-search inside a mirrored repo; returns short snippets "
            "(path+line), capped and truncated-flagged."
        ),
        annotations=_READ_ONLY_TOOL,
    )
    def search_repo(
        ctx: Context,
        repo: str,
        query: str,
        file_pattern: str | None = None,
        max_results: int = 50,
    ) -> dict:
        require_admin(ctx)
        return repo_handlers.search_repo(
            repo_backend,
            repo=repo,
            query=query,
            file_pattern=file_pattern,
            max_results=max_results,
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
