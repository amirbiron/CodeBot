"""ASGI entrypoint for the CodeKeeper MCP server.

Run with::

    uvicorn mcp_server.app:app --host 0.0.0.0 --port $PORT

Importing this module connects to MongoDB (via the shared ``database`` layer),
so it is intentionally NOT imported by the unit tests — those exercise the
lighter ``handlers`` / ``backend`` / ``token_store`` / ``oauth_*`` modules directly.

Auth mode is chosen from the environment:
- If both ``MCP_SERVER_URL`` and ``WEBAPP_URL`` are set → full OAuth 2.1 (Claude.ai
  connectors), which also accepts PATs (Claude Code/Desktop).
- Otherwise → PAT-only fallback (Phase 0), so the service still runs without the
  OAuth configuration.
"""

from __future__ import annotations

import os
from typing import Any

# Configure logging before anything else in this process can log. **This module
# is the only place in the service where that happens**, and until it did,
# nothing logged here was visible at all: measured in a fresh process, the root
# logger sits at ``WARNING`` with **zero handlers**, so every ``logger.info`` in
# ``mcp_server`` went nowhere and ``stdout``/``stderr`` stayed empty. The
# configuration lived in ``main.py``, ``webapp/app.py`` and
# ``services/webserver.py`` — none of which this process loads.
#
# ``setup_structlog_logging`` is the repository's one entry point for this and
# it does both halves: it calls ``basicConfig`` when the root logger has no
# handlers, which is this process's state, and it configures ``structlog``.
# Calling it rather than reaching for ``basicConfig`` here is the difference
# between using the mechanism and building a second one beside it.
#
# Wrapped exactly as ``services/webserver.py`` wraps it: ``observability``
# imports ``structlog`` at module level and every caller in this repository
# treats that import as something that may not be there. A service that cannot
# configure logging should still serve.
try:  # pragma: no cover - exercised by tests/test_mcp_logging_visible.py
    from observability import get_log_level_from_env, setup_structlog_logging

    setup_structlog_logging(get_log_level_from_env("INFO"))
except Exception:  # noqa: BLE001 - see above: logging must not gate the service
    import logging as _logging

    _logging.getLogger(__name__).warning(
        "structured logging setup unavailable; records from this process may be invisible",
        exc_info=True,
    )

from .backend import ProductionBackend
from .handlers import max_code_size
from .limits import (
    DEFAULT_RATE_LIMIT_PER_MINUTE,
    MAX_REQUEST_BYTES_ENV,
    MIN_MAX_REQUEST_BYTES,
    RATE_LIMIT_ENV,
    limit_from_env,
    request_bytes_for,
)
from .server import build_app
from .token_store import MCPTokenStore
from .wiring import resolve_mongo


def _build_oauth(mongo: Any, *, mcp_base: str, webapp_base: str) -> tuple[Any, Any, Any]:
    """Assemble the OAuth provider, AuthSettings, and consent routes."""
    from mcp.server.auth.settings import (
        AuthSettings,
        ClientRegistrationOptions,
        RevocationOptions,
    )
    from pydantic import AnyHttpUrl

    from .oauth_identity import assert_strong_secret
    from .oauth_provider import CodeKeeperOAuthProvider
    from .oauth_routes import oauth_consent_routes
    from .oauth_store import OAuthStore

    store = OAuthStore(mongo)
    token_store = MCPTokenStore(mongo)
    # Fail fast: OAuth signs the user-identity assertion with SECRET_KEY, so a
    # missing or well-known-default key is a security hole, not a soft default.
    secret = os.getenv("SECRET_KEY", "")
    assert_strong_secret(secret)

    provider = CodeKeeperOAuthProvider(
        store=store,
        pat_verify=token_store.verify,
        identify_url=f"{webapp_base}/oauth/identify",
        consent_url=f"{mcp_base}/oauth/consent",
    )
    settings = AuthSettings(
        issuer_url=AnyHttpUrl(mcp_base),
        resource_server_url=AnyHttpUrl(mcp_base),
        client_registration_options=ClientRegistrationOptions(
            # Default new registrations to BOTH read+write. A client that registers
            # without naming a scope (Claude.ai does exactly this) then gets the
            # write ceiling at DCR, so it *can* be granted write. This is not a
            # silent grant: the user still approves the shown scopes on the consent
            # screen, which is the real gate. A read-only default capped every
            # Claude.ai connection at read and made write unreachable.
            enabled=True,
            valid_scopes=["read", "write"],
            default_scopes=["read", "write"],
        ),
        revocation_options=RevocationOptions(enabled=True),
        required_scopes=[],
    )
    consent = oauth_consent_routes(store, secret)
    return provider, settings, consent


def create_app():
    from database import db as db_manager  # lazy heavy import

    mongo = resolve_mongo(db_manager)
    if mongo is None:
        raise RuntimeError(
            "MongoDB is not available (database.db is None). "
            "Set MONGODB_URL for the MCP service."
        )

    backend = ProductionBackend(db_manager=db_manager, mongo_db=mongo)
    name = os.getenv("MCP_SERVER_NAME", "CodeKeeper")
    # Request limits (#3431) — read here, at the service entry, not at import.
    # The body cap is derived from the code-size ceiling the service actually
    # runs with (``MAX_CODE_SIZE`` from the config, or the handlers' fallback),
    # so raising one can never leave the other behind; ``MCP_MAX_REQUEST_BYTES``
    # is the way to raise the cap further without a deploy, not a kill switch.
    max_request_bytes = limit_from_env(
        MAX_REQUEST_BYTES_ENV, request_bytes_for(max_code_size()), minimum=MIN_MAX_REQUEST_BYTES
    )
    rate_limit_per_minute = limit_from_env(
        RATE_LIMIT_ENV, DEFAULT_RATE_LIMIT_PER_MINUTE, minimum=1, zero_disables=True
    )

    # Phase D: admin-only repo-browser tools (hidden + gated for non-admins).
    from .repo_backend import RepoBackend

    repo_backend = RepoBackend(db=mongo, db_manager=db_manager)

    # Keep this service's local mirrors fresh automatically (webapp-worker
    # pattern: background daemon thread; no cron/extra service). Merges to main
    # reach the webapp webhook → shared Mongo SHA → this loop fetches locally.
    try:
        from .repo_autosync import start_autosync

        start_autosync(mongo)
    except Exception:
        import logging

        logging.getLogger(__name__).warning("repo autosync failed to start", exc_info=True)

    mcp_base = (os.getenv("MCP_SERVER_URL") or "").rstrip("/")
    webapp_base = (os.getenv("WEBAPP_URL") or "").rstrip("/")

    if mcp_base and webapp_base:
        provider, settings, consent = _build_oauth(
            mongo, mcp_base=mcp_base, webapp_base=webapp_base
        )
        return build_app(
            backend,
            auth_provider=provider,
            auth_settings=settings,
            consent_routes=consent,
            repo_backend=repo_backend,
            name=name,
            max_request_bytes=max_request_bytes,
            rate_limit_per_minute=rate_limit_per_minute,
        )

    # Fallback: PAT-only (Claude Code/Desktop) — runs without OAuth config.
    return build_app(
        backend,
        MCPTokenStore(mongo),
        repo_backend=repo_backend,
        name=name,
        max_request_bytes=max_request_bytes,
        rate_limit_per_minute=rate_limit_per_minute,
    )


app = create_app()
