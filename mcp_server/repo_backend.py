"""Read-only data access for the repo-browser tools (Phase D, admin-only).

Wraps the existing Repo Sync Engine in-process (``GitMirrorService`` +
``RepoSearchService`` + the ``repo_metadata``/``sync_jobs`` collections) —
no new persistence logic. Keyed by logical ``repo_name``, not ``user_id``.

Resilience contract: the sync worker may run ``git fetch``/``gc`` concurrently
(there are no read locks), so a failed read checks for a *running* sync job and
returns ``{"error": "sync_in_progress", "retry_after": N}`` — telling the
calling model to retry shortly instead of concluding the repo/file is missing.

The secrets policy (``repo_policy``) is applied on every surface: tree omits,
search skips, get blocks. Heavy content is returned only by ``get_file``
(Smart Projection).
"""

from __future__ import annotations

import logging
from typing import Any

from .backend import _json_safe
from .repo_handlers import TREE_PER_PAGE_MAX
from .repo_policy import is_denied

logger = logging.getLogger(__name__)

SYNC_RETRY_AFTER_SECONDS = 30


def _safe_int(value: Any, default: int) -> int:
    """Best-effort int conversion; invalid input ⇒ default (clamp policy, 13.4)."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


_REPOS_PROJECTION = {
    "_id": 0,
    "repo_name": 1,
    "repo_url": 1,
    "default_branch": 1,
    "last_sync_time": 1,
    "last_synced_sha": 1,
    "total_files": 1,
    "sync_status": 1,
}


class RepoBackend:
    """Duck-typed backend over a pymongo handle + the mirror/search services.

    ``mirror`` / ``search_service`` are injectable for tests and lazily resolved
    in production (importing the services stack only when a repo tool runs).
    """

    def __init__(self, db: Any = None, mirror: Any = None, search_service: Any = None) -> None:
        self._db = db
        self._mirror = mirror
        self._search = search_service
        self._ensure_indexes()

    # -- wiring ------------------------------------------------------------
    def _require_mirror(self) -> Any:
        if self._mirror is None:
            from services.git_mirror_service import get_mirror_service  # lazy heavy import

            self._mirror = get_mirror_service()
        return self._mirror

    def _require_search(self) -> Any:
        if self._search is None:
            from services.repo_search_service import create_search_service  # lazy

            self._search = create_search_service(self._db)
        return self._search

    def _ensure_indexes(self) -> None:
        # list_repos runs on repo_metadata on every call, and the collection had
        # no index at all — closing that gap is part of this phase, not "later".
        try:
            if self._db is not None:
                self._db["repo_metadata"].create_index("repo_name", unique=True)
        except Exception:
            logger.warning("repo_metadata index creation failed (non-fatal)", exc_info=True)

    # -- helpers -----------------------------------------------------------
    def _sync_running(self, repo_name: str) -> bool:
        try:
            if self._db is None:
                return False
            doc = self._db["sync_jobs"].find_one({"repo_name": repo_name, "status": "running"})
            return doc is not None
        except Exception:
            return False

    def _transient_error(self, repo_name: str, fallback: str) -> dict[str, Any]:
        """Map a failed read to sync_in_progress (retryable) when a sync runs."""
        if self._sync_running(repo_name):
            return {
                "ok": False,
                "error": "sync_in_progress",
                "retry_after": SYNC_RETRY_AFTER_SECONDS,
                "message": (
                    "A sync is running for this repo right now; the repo/file may "
                    "exist — retry after a short wait instead of assuming absence."
                ),
            }
        return {"ok": False, "error": fallback}

    def _default_ref(self, repo_name: str) -> str:
        try:
            meta = (
                self._db["repo_metadata"].find_one({"repo_name": repo_name})
                if self._db is not None
                else None
            )
        except Exception:
            meta = None
        branch = (meta or {}).get("default_branch")
        return f"refs/heads/{branch}" if branch else "HEAD"

    # -- tools -------------------------------------------------------------
    def list_repos(self, *, limit: int = 50) -> dict[str, Any]:
        try:
            cursor = (
                self._db["repo_metadata"]
                .find({}, _REPOS_PROJECTION)
                .sort("repo_name", 1)
                .limit(int(limit))
            )
            repos = [_json_safe(dict(doc)) for doc in cursor]
        except Exception:
            logger.warning("list_repos query failed", exc_info=True)
            return {"ok": False, "error": "db_error"}
        return {"ok": True, "count": len(repos), "repos": repos}

    def list_tree(
        self,
        *,
        repo: str,
        path: str | None = None,
        ref: str | None = None,
        page: int = 1,
        per_page: int = 200,
        byte_budget: int = 256_000,
    ) -> dict[str, Any]:
        use_ref = ref or self._default_ref(repo)
        try:
            files = self._require_mirror().list_all_files(repo, use_ref)
        except Exception:
            logger.warning("list_tree read failed", exc_info=True)
            files = None
        if files is None:
            return self._transient_error(repo, "repo_or_ref_not_found")

        prefix = (path or "").strip().strip("/")
        if prefix:
            files = [f for f in files if f == prefix or f.startswith(prefix + "/")]
        files = [f for f in files if not is_denied(f)]  # policy: omit
        total = len(files)

        # Defense-in-depth: the handler already clamps, but this method is a
        # public API — normalize again so a direct caller can't slice with a
        # negative start or crash on a non-numeric value.
        page_i = max(1, _safe_int(page, 1))
        per_page_i = min(max(1, _safe_int(per_page, 200)), TREE_PER_PAGE_MAX)

        start = (page_i - 1) * per_page_i
        page_items = files[start : start + per_page_i]
        # Output byte budget: never let one page blow up the response.
        out: list[str] = []
        used = 0
        truncated = False
        for item in page_items:
            used += len(item.encode("utf-8")) + 8
            if used > byte_budget:
                truncated = True
                break
            out.append(item)
        return {
            "ok": True,
            "repo": repo,
            "ref": use_ref,
            "path": prefix or None,
            "total": total,
            "page": page_i,
            "per_page": per_page_i,
            "paths": out,
            "truncated": truncated,
        }

    def get_file(self, *, repo: str, path: str, ref: str | None = None) -> dict[str, Any]:
        if is_denied(path):  # policy: block, before touching the mirror
            return {"ok": False, "error": "path_denied"}
        use_ref = ref or self._default_ref(repo)
        try:
            res = self._require_mirror().get_file_at_commit(repo, path, use_ref)
        except Exception:
            logger.warning("get_file read failed", exc_info=True)
            res = {"error": "internal_error"}

        if res.get("success"):
            file_meta: dict[str, Any] = {
                "path": res.get("file_path", path),
                "ref": use_ref,
                "resolved_commit": res.get("resolved_commit"),
                "size": res.get("size"),
            }
            if res.get("is_binary"):
                return {"ok": True, "status": "binary", "file": file_meta}
            file_meta["lines"] = res.get("lines")
            file_meta["encoding"] = res.get("encoding")
            return {"ok": True, "status": "ok", "file": file_meta, "content": res.get("content")}

        err = str(res.get("error") or "internal_error")
        if err == "file_too_large":
            return {
                "ok": True,
                "status": "too_large",
                "file": {"path": path, "ref": use_ref, "size": res.get("size")},
                "max": res.get("max_size"),
            }
        if err == "file_not_in_commit":
            return {"ok": False, "error": "not_found"}
        if err in ("invalid_repo_name", "invalid_file_path"):
            return {"ok": False, "error": "invalid_input"}
        # repo_not_found / invalid_commit / git_error / timeout / internal_error:
        # possibly a transient race with a running sync — say so if it is.
        fallback = "not_found" if err in ("repo_not_found", "invalid_commit") else "read_failed"
        return self._transient_error(repo, fallback)

    def search(
        self,
        *,
        repo: str,
        query: str,
        file_pattern: str | None = None,
        max_results: int = 50,
        byte_budget: int = 256_000,
    ) -> dict[str, Any]:
        try:
            res = self._require_search().search(
                repo,
                query,
                search_type="content",
                file_pattern=(file_pattern or None),
                max_results=int(max_results),
            )
        except Exception:
            logger.warning("search failed", exc_info=True)
            return self._transient_error(repo, "search_failed")
        if res.get("error") and not res.get("results"):
            return self._transient_error(repo, "search_failed")

        # total reflects what we can actually serve: the policy-filtered matches
        # (NOT the engine's raw total, which may count denied paths).
        filtered = [r for r in (res.get("results") or []) if not is_denied(r.get("path", ""))]
        total = len(filtered)
        capped = filtered[: max(0, _safe_int(max_results, 50))]  # cap TOTAL matches
        cap_truncated = total > len(capped)

        out: list[dict[str, Any]] = []
        used = 0
        budget_truncated = False
        for r in capped:
            row = {
                "path": r.get("path"),
                "line": r.get("line"),
                "snippet": str(r.get("content") or "")[:500],
            }
            used += len(str(row).encode("utf-8"))
            if used > byte_budget:
                budget_truncated = True
                break
            out.append(row)
        return {
            "ok": True,
            "repo": repo,
            "query": query,
            "count": len(out),
            "total": total,
            "results": out,
            "truncated": bool(cap_truncated or budget_truncated or res.get("truncated")),
        }
