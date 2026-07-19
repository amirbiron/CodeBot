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
    )


def get_repo_file(backend: Any, *, repo: str, path: str, ref: str | None = None) -> dict[str, Any]:
    name = (repo or "").strip()
    file_path = (path or "").strip()
    if not name:
        return {"ok": False, "error": "missing_repo"}
    if not file_path:
        return {"ok": False, "error": "missing_path"}
    return backend.get_file(repo=name, path=file_path, ref=((ref or "").strip() or None))


def search_repo(
    backend: Any,
    *,
    repo: str,
    query: str,
    file_pattern: str | None = None,
    max_results: int = SEARCH_RESULTS_DEFAULT,
) -> dict[str, Any]:
    name = (repo or "").strip()
    q = (query or "").strip()
    if not name:
        return {"ok": False, "error": "missing_repo"}
    if len(q) < 2:
        return {"ok": False, "error": "query_too_short"}
    return backend.search(
        repo=name,
        query=q,
        file_pattern=((file_pattern or "").strip() or None),
        max_results=_clamp(max_results, 1, SEARCH_RESULTS_MAX, SEARCH_RESULTS_DEFAULT),
        byte_budget=OUTPUT_BYTE_BUDGET,
    )
