"""Pure tool handlers.

These are plain functions (no MCP / no Starlette imports) that validate and
clamp inputs, then delegate to a ``Backend``. Keeping them separate from the
FastMCP wiring makes the business logic trivially unit-testable.

Every handler takes an authoritative, server-derived ``user_id`` — callers must
never pass a client-supplied user id here.
"""

from __future__ import annotations

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
