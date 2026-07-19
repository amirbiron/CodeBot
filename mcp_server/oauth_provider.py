"""OAuth 2.1 authorization-server provider (implements the MCP SDK contract).

The MCP SDK mounts the protocol endpoints (``/.well-known/*``, ``/authorize``,
``/token``, ``/register``, ``/revoke``) and verifies PKCE. This class supplies the
storage + issuance logic those endpoints call into.

Identity bridge: ``authorize()`` does not log the user in itself (the Telegram
login widget is bound to the webapp's domain). Instead it stores a pending
transaction and redirects the browser to the webapp's identity endpoint, which
authenticates via Telegram and bounces back to our ``/oauth/consent`` route with
a signed ``user_id`` assertion; that route mints the authorization code.

``load_access_token`` is unified: it accepts both a Personal Access Token
(``ckmcp_…`` — Claude Code/Desktop) and an OAuth access token (``ckoat_…`` —
Claude.ai), so every tool call flows through one verification path.
"""

from __future__ import annotations

from datetime import datetime, UTC
from typing import Any
from collections.abc import Callable
from urllib.parse import quote

import anyio
from pydantic import AnyUrl

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    RefreshToken,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

from .oauth_store import (
    ACCESS_PREFIX,
    ACCESS_TTL_SECONDS,
    REFRESH_PREFIX,
    OAuthStore,
    new_secret,
)
from .token_store import TOKEN_PREFIX

# Callable that verifies a raw PAT -> {"user_id", "scopes"} | None
PatVerify = Callable[[str], "dict[str, Any] | None"]


def _epoch(dt: Any) -> int | None:
    if not isinstance(dt, datetime):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return int(dt.timestamp())


class CodeKeeperOAuthProvider:
    """Implements mcp.server.auth.provider.OAuthAuthorizationServerProvider."""

    def __init__(
        self,
        *,
        store: OAuthStore,
        pat_verify: PatVerify,
        identify_url: str,
        consent_url: str,
        default_scopes: tuple[str, ...] = ("read",),
    ) -> None:
        self._store = store
        self._pat_verify = pat_verify
        self._identify_url = identify_url
        self._consent_url = consent_url
        self._default_scopes = list(default_scopes)

    # -- clients -----------------------------------------------------------
    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        doc = await anyio.to_thread.run_sync(self._store.get_client, client_id)
        return OAuthClientInformationFull(**doc) if doc else None

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        data = client_info.model_dump(mode="json", exclude_none=True)
        await anyio.to_thread.run_sync(self._store.save_client, data)

    # -- authorize ---------------------------------------------------------
    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        txn = {
            "client_id": client.client_id,
            "redirect_uri": str(params.redirect_uri),
            "redirect_uri_provided_explicitly": bool(params.redirect_uri_provided_explicitly),
            "code_challenge": params.code_challenge,
            "scopes": list(params.scopes or self._default_scopes),
            "state": params.state,
            "resource": params.resource,
        }
        txn_id = await anyio.to_thread.run_sync(self._store.create_txn, txn)
        # Bounce to the webapp for Telegram login; it returns to /oauth/consent
        # with a signed user_id, which mints the authorization code.
        return f"{self._identify_url}?txn={quote(txn_id)}&return={quote(self._consent_url)}"

    # -- authorization codes ----------------------------------------------
    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        doc = await anyio.to_thread.run_sync(self._store.get_code, authorization_code)
        if not doc or doc.get("client_id") != client.client_id:
            return None
        return AuthorizationCode(
            code=authorization_code,
            scopes=list(doc.get("scopes") or []),
            expires_at=float(_epoch(doc.get("expires_at")) or 0),
            client_id=client.client_id,
            code_challenge=doc.get("code_challenge") or "",
            redirect_uri=AnyUrl(doc["redirect_uri"]),
            redirect_uri_provided_explicitly=bool(
                doc.get("redirect_uri_provided_explicitly", True)
            ),
            resource=doc.get("resource"),
            subject=doc.get("subject"),
        )

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        await anyio.to_thread.run_sync(self._store.delete_code, authorization_code.code)
        return await anyio.to_thread.run_sync(
            self._issue,
            client.client_id,
            authorization_code.subject,
            list(authorization_code.scopes),
        )

    # -- refresh tokens ----------------------------------------------------
    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> RefreshToken | None:
        doc = await anyio.to_thread.run_sync(
            lambda: self._store.get_token(refresh_token, kind="refresh")
        )
        if not doc or doc.get("client_id") != client.client_id:
            return None
        return RefreshToken(
            token=refresh_token,
            client_id=client.client_id,
            scopes=list(doc.get("scopes") or []),
            expires_at=_epoch(doc.get("expires_at")),
            subject=doc.get("subject"),
        )

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        # Rotate: invalidate the presented refresh token, issue a fresh pair.
        await anyio.to_thread.run_sync(self._store.revoke_token, refresh_token.token)
        use_scopes = list(scopes or refresh_token.scopes)
        return await anyio.to_thread.run_sync(
            self._issue, client.client_id, refresh_token.subject, use_scopes
        )

    # -- access tokens (verification on every tool call) -------------------
    async def load_access_token(self, token: str) -> AccessToken | None:
        if token.startswith(TOKEN_PREFIX):
            principal = await anyio.to_thread.run_sync(self._pat_verify, token)
            if not principal:
                return None
            return AccessToken(
                token=token,
                client_id="pat",
                scopes=list(principal.get("scopes") or []),
                expires_at=None,
                subject=str(principal["user_id"]),
            )
        doc = await anyio.to_thread.run_sync(lambda: self._store.get_token(token, kind="access"))
        if not doc:
            return None
        return AccessToken(
            token=token,
            client_id=doc.get("client_id") or "",
            scopes=list(doc.get("scopes") or []),
            expires_at=_epoch(doc.get("expires_at")),
            subject=doc.get("subject"),
        )

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        await anyio.to_thread.run_sync(self._store.revoke_token, token.token)

    # -- helpers -----------------------------------------------------------
    def _issue(self, client_id: str, subject: str | None, scopes: list[str]) -> OAuthToken:
        access = new_secret(ACCESS_PREFIX)
        refresh = new_secret(REFRESH_PREFIX)
        data = {"client_id": client_id, "subject": subject, "scopes": list(scopes)}
        self._store.save_token(access, kind="access", data=data)
        self._store.save_token(refresh, kind="refresh", data=data)
        return OAuthToken(
            access_token=access,
            token_type="Bearer",
            expires_in=ACCESS_TTL_SECONDS,
            refresh_token=refresh,
            scope=" ".join(scopes) if scopes else None,
        )
