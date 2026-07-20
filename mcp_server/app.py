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

from .backend import ProductionBackend
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
            # Offer "write" as an available scope; keep the default read-only so a
            # client that registers without asking (and every existing connection)
            # stays read-only. Write is granted only when a client explicitly
            # registers for and requests it, and the user approves it on consent.
            enabled=True,
            valid_scopes=["read", "write"],
            default_scopes=["read"],
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

    # Phase D: admin-only repo-browser tools (hidden + gated for non-admins).
    from .repo_backend import RepoBackend

    repo_backend = RepoBackend(db=mongo)

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
        )

    # Fallback: PAT-only (Claude Code/Desktop) — runs without OAuth config.
    return build_app(backend, MCPTokenStore(mongo), repo_backend=repo_backend, name=name)


app = create_app()
