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

The other direction is pruning: a mirror on THIS disk whose repo has no
``repo_metadata`` record is deleted at the end of the pass
(:func:`_prune_orphans`). Removing a repo in the webapp (``unmirror_repo`` in
``services/repo_sync_service.py``) deletes the webapp's own mirror and the
records, and nothing there can reach this service's disk — so before this step
the removed repo stayed here for good, and the read tools kept serving it.

Env:
- ``MCP_REPO_AUTOSYNC``          — "0"/"false" disables (default: enabled).
- ``MCP_REPO_AUTOSYNC_INTERVAL`` — seconds between passes (default 300, min 30).
"""

from __future__ import annotations

import contextlib
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
    is unknown) ⇒ delta fetch; identical SHAs ⇒ skip. Then every local mirror
    without a record in that same read is deleted (:func:`_prune_orphans`). A
    failed read returns before both steps, so it deletes nothing.

    Logs one ``repo autosync pass:`` line when the pass cloned, fetched,
    pruned or failed anything.
    """
    stats = {"checked": 0, "cloned": 0, "fetched": 0, "skipped": 0, "pruned": 0, "errors": 0}
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

    known: set[str] = set()
    for meta in repos:
        name = str(meta.get("repo_name") or "").strip()
        if not name:
            continue
        # Before anything that can fail: a repo whose clone or fetch fails in
        # this pass still has a record, and its mirror must survive the pruning.
        known.add(name)
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

    _prune_orphans(mirror, known, stats)
    if stats["cloned"] or stats["fetched"] or stats["pruned"] or stats["errors"]:
        logger.info("repo autosync pass: %s", stats)
    return stats


def _prune_orphans(mirror: Any, known: set[str], stats: dict[str, int]) -> None:
    """Delete every local mirror whose repo has no ``repo_metadata`` record.

    ``known`` holds the names from the read the pass just worked from, and its
    age does not matter: on this service's disk ``init_mirror`` is called only
    from :func:`refresh_once`, and only for names in that read, so no mirror
    made since the read is missing from it. A record removed during the pass
    is pruned one pass later; a record added during the pass for an old
    leftover mirror of the same name costs one clone in the next pass.

    Never deleted:

    - anything at all while ``known`` is empty — an empty ``repo_metadata``
      points at the wrong database more often than at every repo being removed;
    - a directory whose name ``init_mirror`` would refuse (``_validate_repo_name``),
      because this service did not create it;
    - a symbolic link, because ``_safe_rmtree`` (behind ``delete_mirror``)
      resolves the path before it deletes: it would remove the directory the
      link points to and leave the link itself;
    - a repo that :func:`is_refreshing` reports, i.e. one being cloned or fetched.

    Deletion goes through ``delete_mirror`` (``_safe_rmtree``, confined to the
    mirror directory). A mirror counts as ``pruned`` only after
    ``mirror_exists`` says it is gone. Any failure counts in ``errors`` and the
    loop moves on to the next mirror.
    """
    try:
        on_disk = mirror.list_mirror_names()
    except OSError:
        logger.warning("repo autosync: could not list the local mirrors; nothing pruned", exc_info=True)
        return
    if not known:
        if on_disk:
            logger.warning(
                "repo autosync: repo_metadata lists no repo names; not pruning %d local mirror(s) — "
                "an empty result points at the wrong database more often than at every repo being removed",
                len(on_disk),
            )
        return

    for name in on_disk:
        if name in known:
            continue
        try:
            if not mirror._validate_repo_name(name):
                continue  # not a name this service creates — see the docstring
            if mirror._get_repo_path(name).is_symlink():
                continue  # deleting would follow the link — see the docstring
            if is_refreshing(name):
                logger.info(
                    "repo autosync: %s has no repo_metadata record but is being cloned or fetched; "
                    "not pruned this pass",
                    name,
                )
                continue
            res = mirror.delete_mirror(name) or {}
            if not res.get("success"):
                stats["errors"] += 1
                logger.warning(
                    "repo autosync: could not prune the local mirror of %s: %s",
                    name,
                    _redact(res.get("message")),
                )
                continue
            # The state, not the report: the count and the log line below are
            # what the operator reads to know the directory is gone.
            if mirror.mirror_exists(name):
                stats["errors"] += 1
                logger.warning(
                    "repo autosync: delete_mirror reported the mirror of %s deleted, but it is still on disk",
                    name,
                )
                continue
            if res.get("existed"):
                stats["pruned"] += 1
                logger.info("repo autosync: pruned the local mirror of %s (no repo_metadata record)", name)
            # ``existed`` false: the directory went away between the listing and
            # the delete, so nothing was deleted here and there is nothing to count.
        except Exception:
            stats["errors"] += 1
            logger.warning("repo autosync: pruning the local mirror of %s failed", name, exc_info=True)


def attach_credential_sweep(app: Any) -> bool:
    """Run the mirror credential sweep (#3480) once, when the ASGI app starts.

    **At server startup, never at import.** ``mcp_server/app.py`` builds the app
    at module level (``app = create_app()``), so anything ``create_app`` starts
    directly also starts on every ``import mcp_server.app`` — in tests, tooling,
    a REPL — and this sweep rewrites ``remote.origin.url`` on every mirror under
    ``REPO_MIRROR_PATH``. Wrapping ``router.lifespan_context`` is the seam the
    service already uses for startup work (:func:`mcp_server.server.attach_read_pool`,
    :func:`mcp_server.analytics.attach_shutdown_drain`): uvicorn enters the
    lifespan when it serves, an import does not.

    The sweep itself runs on a daemon thread
    (:func:`services.mirror_credentials.start_credential_sweep`), so startup
    does not wait for it. Returns False — and says so — when the app has no
    lifespan to attach to; then the sweep does not run here, and the missing
    ``mirror credential sweep:`` log line is the signal.
    """
    router = getattr(app, "router", None)
    original = getattr(router, "lifespan_context", None)
    if router is None or original is None:
        logger.warning("no lifespan on the ASGI app; the mirror credential sweep will not run")
        return False

    @contextlib.asynccontextmanager
    async def _lifespan_with_credential_sweep(scope_app: Any):
        try:
            from services.mirror_credentials import start_credential_sweep  # lazy: only when serving

            start_credential_sweep()
        except Exception:
            # The service must still come up; fetches stay guarded by
            # transfer.credentialsInUrl=die and the per-fetch cleaning.
            logger.warning("mirror credential sweep failed to start", exc_info=True)
        async with original(scope_app) as state:
            yield state

    router.lifespan_context = _lifespan_with_credential_sweep
    return True


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

                    refresh_once(db, get_mirror_service())  # logs its own summary line
                except Exception:
                    logger.warning("repo autosync pass failed", exc_info=True)
                time.sleep(interval or _interval_seconds())

        _thread = threading.Thread(target=_loop, daemon=True, name="mcp-repo-autosync")
        _thread.start()
        logger.info("repo autosync started (interval=%ss)", interval or _interval_seconds())
        return True
