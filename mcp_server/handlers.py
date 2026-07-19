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
    try:
        from config import config as _cfg

        max_size = int(getattr(_cfg, "MAX_CODE_SIZE", DEFAULT_MAX_CODE_SIZE))
    except Exception:
        max_size = DEFAULT_MAX_CODE_SIZE
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
