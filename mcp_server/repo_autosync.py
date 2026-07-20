"""Background auto-refresh of the MCP service's local bare mirrors (Phase D).

Same pattern as the webapp's sync worker — a lazily-started daemon thread inside
the existing service (no cron, no extra Render service) — but decoupled from the
webhook/job queue: the webapp keeps receiving GitHub webhooks and updating
``repo_metadata.last_synced_sha`` in the shared Mongo; this loop compares that
SHA to the local mirror and clones/fetches when they differ.

So a merge to main flows end-to-end automatically:
webhook → webapp sync (its own disk + SHA in Mongo) → this loop notices the
drift within one interval → ``git fetch`` into THIS service's disk. A repo that
was never mirrored here is self-cloned from ``repo_metadata.repo_url``
(``init_mirror`` is idempotent), so no manual ``initial_import`` is needed on
the MCP side. Private repos need ``GITHUB_TOKENS``/``GITHUB_TOKEN`` set here.

While a repo is being cloned/fetched, ``is_refreshing(repo)`` is True and the
read tools report ``sync_in_progress`` + ``retry_after`` instead of "not found".

Env:
- ``MCP_REPO_AUTOSYNC``          — "0"/"false" disables (default: enabled).
- ``MCP_REPO_AUTOSYNC_INTERVAL`` — seconds between passes (default 300, min 30).
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)

# Log redaction (defense-in-depth): the engine already sanitizes its own git
# stderr at the source (_run_git_command → _sanitize_output), but we log
# ``message`` values from a duck-typed dependency — so scrub credential shapes
# ourselves before anything reaches the logs (CLAUDE.md: no secrets in logs).
_URL_CRED_RE = re.compile(r"(https?://)[^/@\s]+@")
_GH_TOKEN_RE = re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b")


def _redact(text: Any) -> str:
    """Strip URL userinfo credentials + GitHub-token shapes from log-bound text.

    Fail-closed: on any internal error return a placeholder, never the raw text.
    """
    try:
        s = str(text or "")
        s = _URL_CRED_RE.sub(r"\1***@", s)
        return _GH_TOKEN_RE.sub("***", s)
    except Exception:
        return "<redacted>"


DEFAULT_INTERVAL_SECONDS = 300
_MIN_INTERVAL_SECONDS = 30
_STARTUP_DELAY_SECONDS = 10  # let the app finish booting before the first pass

_ENABLE_ENV = "MCP_REPO_AUTOSYNC"
_INTERVAL_ENV = "MCP_REPO_AUTOSYNC_INTERVAL"

_start_lock = threading.Lock()
_thread: threading.Thread | None = None

_active_lock = threading.Lock()
_active: set[str] = set()


def is_refreshing(repo_name: Any) -> bool:
    """True while this service is cloning/fetching ``repo_name`` locally."""
    with _active_lock:
        return str(repo_name or "") in _active


def _mark(repo_name: str, active: bool) -> None:
    with _active_lock:
        if active:
            _active.add(repo_name)
        else:
            _active.discard(repo_name)


def autosync_enabled() -> bool:
    return os.getenv(_ENABLE_ENV, "1").strip().lower() not in ("0", "false", "no", "off")


def _interval_seconds() -> int:
    try:
        return max(_MIN_INTERVAL_SECONDS, int(os.getenv(_INTERVAL_ENV, DEFAULT_INTERVAL_SECONDS)))
    except (TypeError, ValueError):
        return DEFAULT_INTERVAL_SECONDS


def refresh_once(db: Any, mirror: Any) -> dict[str, int]:
    """One refresh pass over every repo in ``repo_metadata``. Never raises.

    Per repo: missing mirror + known URL ⇒ clone; existing mirror whose local
    SHA differs from the webapp-written ``last_synced_sha`` (or when either SHA
    is unknown) ⇒ delta fetch; identical SHAs ⇒ skip.
    """
    stats = {"checked": 0, "cloned": 0, "fetched": 0, "skipped": 0, "errors": 0}
    try:
        repos = list(
            db["repo_metadata"].find(
                {},
                {
                    "_id": 0,
                    "repo_name": 1,
                    "repo_url": 1,
                    "default_branch": 1,
                    "last_synced_sha": 1,
                },
            )
        )
    except Exception:
        logger.warning("repo autosync: repo_metadata query failed", exc_info=True)
        return stats

    for meta in repos:
        name = str(meta.get("repo_name") or "").strip()
        if not name:
            continue
        stats["checked"] += 1
        _mark(name, True)
        try:
            if not mirror.mirror_exists(name):
                url = str(meta.get("repo_url") or "").strip()
                if not url:
                    stats["skipped"] += 1
                    continue
                res = mirror.init_mirror(url, name) or {}
                if res.get("success"):
                    stats["cloned"] += 1
                else:
                    stats["errors"] += 1
                    logger.warning(
                        "repo autosync: clone failed for %s: %s", name, _redact(res.get("message"))
                    )
                continue

            branch = str(meta.get("default_branch") or "main")
            db_sha = str(meta.get("last_synced_sha") or "").strip()
            local_sha = str(mirror.get_current_sha(name, branch) or "").strip()
            if db_sha and local_sha and db_sha == local_sha:
                stats["skipped"] += 1
                continue
            res = mirror.fetch_updates(name) or {}
            if res.get("success"):
                stats["fetched"] += 1
            else:
                stats["errors"] += 1
                logger.warning(
                    "repo autosync: fetch failed for %s: %s", name, _redact(res.get("message"))
                )
        except Exception:
            stats["errors"] += 1
            logger.warning("repo autosync: refresh failed for %s", name, exc_info=True)
        finally:
            _mark(name, False)
    return stats


def start_autosync(db: Any, *, interval: int | None = None) -> bool:
    """Start the daemon refresher (idempotent). Returns True if it is running.

    Mirrors the webapp's lazily-started worker-thread pattern; disabled cleanly
    via MCP_REPO_AUTOSYNC=0 (tools still work — reads just rely on whatever is
    on disk).
    """
    global _thread
    if not autosync_enabled():
        logger.info("repo autosync disabled via %s", _ENABLE_ENV)
        return False
    with _start_lock:
        if _thread is not None and _thread.is_alive():
            return True

        def _loop() -> None:
            time.sleep(_STARTUP_DELAY_SECONDS)
            while True:
                try:
                    from services.git_mirror_service import get_mirror_service  # lazy heavy import

                    stats = refresh_once(db, get_mirror_service())
                    if stats["cloned"] or stats["fetched"] or stats["errors"]:
                        logger.info("repo autosync pass: %s", stats)
                except Exception:
                    logger.warning("repo autosync pass failed", exc_info=True)
                time.sleep(interval or _interval_seconds())

        _thread = threading.Thread(target=_loop, daemon=True, name="mcp-repo-autosync")
        _thread.start()
        logger.info("repo autosync started (interval=%ss)", interval or _interval_seconds())
        return True
