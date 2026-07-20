"""Pure tool handlers.

These are plain functions (no MCP / no Starlette imports) that validate and
clamp inputs, then delegate to a ``Backend``. Keeping them separate from the
FastMCP wiring makes the business logic trivially unit-testable.

Every handler takes an authoritative, server-derived ``user_id`` — callers must
never pass a client-supplied user id here.
"""

from __future__ import annotations

import html
import re
from typing import Any

MAX_PER_PAGE = 200
MAX_SEARCH_LIMIT = 100
MAX_COLLECTIONS_LIMIT = 500
# Fallback when the app config isn't importable (kept in sync with config.MAX_CODE_SIZE).
DEFAULT_MAX_CODE_SIZE = 100_000


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
) -> dict[str, Any] | None:
    if not file_name and not file_id:
        return None
    return backend.get_file(user_id, file_name=file_name, file_id=file_id, version=version)


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


def _max_code_size() -> int:
    """The app's per-file size gate (characters, not bytes), with a safe fallback."""
    try:
        from config import config as _cfg

        return int(getattr(_cfg, "MAX_CODE_SIZE", DEFAULT_MAX_CODE_SIZE))
    except Exception:
        return DEFAULT_MAX_CODE_SIZE


def save_file(
    backend: Any,
    user_id: int,
    *,
    file_name: str,
    code: str,
    language: str | None = None,
    description: str = "",
) -> dict[str, Any]:
    """Validate + normalize a save request, then delegate to the backend.

    All app imports are lazy/guarded so this module stays trivially importable
    (and unit-testable) without the config/services stack.
    """
    name = (file_name or "").strip()
    if not name:
        return {"ok": False, "error": "missing_file_name"}
    if not isinstance(code, str) or code == "":
        return {"ok": False, "error": "empty_code"}

    # Reject oversize content (the large-file path is non-versioned; out of scope
    # here). Mirror the app's own gate, which counts characters, not bytes.
    max_size = _max_code_size()
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

    return backend.save_file(
        user_id,
        file_name=name,
        code=code,
        programming_language=lang,
        description=(description or "").strip(),
    )


def _apply_edit(
    code: str, old_string: str, new_string: str, replace_all: bool
) -> tuple[str | None, int, str | None]:
    """Pure exact find-and-replace (native Edit-tool semantics).

    Returns ``(new_code, occurrences, error)`` — exactly one of new_code/error
    is set. ``occurrences`` is how many matches were found, so an
    ``ambiguous_match`` error can report the count.
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
    return code.replace(old_string, new_string), count, None


def _load_editable(backend: Any, user_id: int, name: str) -> tuple[dict[str, Any] | None, str]:
    """Fetch the latest version of ``name`` for editing. Returns (doc, code)."""
    doc = backend.get_file(user_id, file_name=name, file_id=None, version=None)
    if not doc:
        return None, ""
    code = doc.get("code")
    return doc, code if isinstance(code, str) else ""


def _resave_edited(
    backend: Any, user_id: int, *, name: str, doc: dict[str, Any], new_code: str
) -> dict[str, Any]:
    """Persist an edited body as a new version, preserving the file's metadata.

    Language, description and tags are carried over from the fetched version so
    an edit never resets them; the same size gate as ``save_file`` applies to
    the resulting body.
    """
    max_size = _max_code_size()
    if len(new_code) > max_size:
        return {"ok": False, "error": "code_too_large", "max": max_size}
    return backend.save_file(
        user_id,
        file_name=name,
        code=new_code,
        programming_language=str(doc.get("programming_language") or doc.get("language") or "text"),
        description=str(doc.get("description") or ""),
        tags=list(doc.get("tags") or []),
    )


def edit_file(
    backend: Any,
    user_id: int,
    *,
    file_name: str,
    old_string: str,
    new_string: str,
    replace_all: bool = False,
) -> dict[str, Any]:
    """Server-side find-and-replace on the latest version of an existing file.

    The client sends only the changed snippet (old/new) — never the whole file.
    The result goes through the same append-only versioned save path, so the
    pre-edit version stays recoverable via ``list_versions``.
    """
    name = (file_name or "").strip()
    if not name:
        return {"ok": False, "error": "missing_file_name"}
    if not isinstance(old_string, str) or not isinstance(new_string, str):
        return {"ok": False, "error": "invalid_arguments"}
    doc, code = _load_editable(backend, user_id, name)
    if doc is None:
        return {"ok": False, "error": "not_found"}
    if code == "":
        return {"ok": False, "error": "empty_file"}
    new_code, occurrences, err = _apply_edit(code, old_string, new_string, bool(replace_all))
    if err is not None or new_code is None:
        out: dict[str, Any] = {"ok": False, "error": err or "edit_failed"}
        if err == "ambiguous_match":
            out["occurrences"] = occurrences
            out["hint"] = "pass a longer unique old_string, or set replace_all=true"
        return out
    res = _resave_edited(backend, user_id, name=name, doc=doc, new_code=new_code)
    if not res.get("ok"):
        return res
    return {"ok": True, "replacements": occurrences, "file": res.get("file")}


def append_file(backend: Any, user_id: int, *, file_name: str, content: str) -> dict[str, Any]:
    """Append ``content`` to the end of an existing file (as a new version).

    A newline separator is inserted when the current body doesn't end with one,
    so an appended section always starts on a fresh line.
    """
    name = (file_name or "").strip()
    if not name:
        return {"ok": False, "error": "missing_file_name"}
    if not isinstance(content, str) or content == "":
        return {"ok": False, "error": "empty_content"}
    doc, code = _load_editable(backend, user_id, name)
    if doc is None:
        return {"ok": False, "error": "not_found"}
    if code == "":
        return {"ok": False, "error": "empty_file"}
    sep = "" if code.endswith("\n") else "\n"
    res = _resave_edited(backend, user_id, name=name, doc=doc, new_code=code + sep + content)
    if not res.get("ok"):
        return res
    return {"ok": True, "appended_chars": len(content), "file": res.get("file")}


# -- sticky notes ----------------------------------------------------------

MAX_NOTE_CONTENT = 5000
MAX_NOTES_PER_SCOPE = 200
MAX_ANCHOR_TEXT = 256
MAX_NOTE_LINE = 1_000_000
DEFAULT_NOTE_COLOR = "#FFFFCC"
# sentinel של הוובאפ לפתק "צף": בלעדיו ה-JS מעגן פתק חדש אוטומטית לשורה הקרובה
NOTE_FLOATING_ANCHOR = "__floating__"

_NOTE_ID_RE = re.compile(r"^[0-9a-fA-F]{24}$")
_NOTE_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{3,8}$")
# עותק של webapp/sticky_notes_api.py:_CONTROL_CHARS_RE — לשמור מסונכרן
_NOTE_CONTROL_CHARS_RE = re.compile(r"[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F]")


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


def list_notes(backend: Any, user_id: int, *, file_name: str) -> dict[str, Any]:
    """List the user's sticky notes attached to ``file_name`` (read-only)."""
    name = (file_name or "").strip()
    if not name:
        return {"ok": False, "error": "missing_file_name"}
    return backend.list_notes(user_id, file_name=name)


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

    color_s = (color or "").strip()
    if not _NOTE_COLOR_RE.match(color_s):
        color_s = DEFAULT_NOTE_COLOR  # ביצירה: צבע לא חוקי נופל לברירת המחדל

    return backend.create_note(
        user_id,
        file_name=name,
        content=clean,
        line=line_i,
        color=color_s,
        anchor_text=_clean_anchor_text(anchor_text),
        anchor_id=None if line_i else NOTE_FLOATING_ANCHOR,
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
    nid = (note_id or "").strip()
    if not _NOTE_ID_RE.match(nid):
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
        color_s = (color or "").strip()
        if _NOTE_COLOR_RE.match(color_s):
            fields["color"] = color_s  # בעדכון: צבע לא חוקי נשמט, לא מוחלף בברירת מחדל
    if anchor_text is not None:
        fields["anchor_text"] = _clean_anchor_text(anchor_text)
    if is_minimized is not None:
        fields["is_minimized"] = bool(is_minimized)

    if not fields:
        return {"ok": False, "error": "no_fields_to_update"}
    return backend.update_note(user_id, note_id=nid, fields=fields)
