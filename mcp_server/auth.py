"""PAT (Bearer) authentication for the MCP HTTP app.

A Starlette middleware verifies ``Authorization: Bearer <token>`` against the
token store and injects the authenticated ``user_id`` onto ``request.state``.
Tools then read it via :func:`current_user_id` (same request object — no
contextvar propagation to worry about).

This is deliberately simple (Phase 0). Phase 1 replaces it with OAuth 2.1.

:func:`authenticate_bearer` is the **single** entry point for verifying a Bearer
credential on a plain HTTP route. It matters because the two auth modes protect
requests differently:

- PAT-only mode: :class:`PATAuthMiddleware` wraps the whole app, so every route
  is covered automatically.
- OAuth mode (production): the middleware is NOT installed. The MCP SDK wraps
  only its own ``/mcp`` mount with ``RequireAuthMiddleware``, so any route added
  manually to ``app.router.routes`` (``/healthz``, ``/api/agent/primer``, …) is
  served **without authentication** unless it authenticates itself.

Any non-MCP route that must not be public therefore calls
:func:`authenticate_bearer` in its own body — it routes to the same verifier the
MCP transport uses (``MCPTokenStore.verify`` for ``ckmcp_`` PATs, and in OAuth
mode ``provider.load_access_token``, which handles both PATs and ``ckoat_``
access tokens). No second credential path is ever introduced.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any

import anyio
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

# Paths that must remain reachable without a token (health checks, etc.).
EXEMPT_PATHS = {"/healthz", "/health", "/"}

_WWW_AUTH = 'Bearer realm="CodeKeeper MCP"'


def unauthorized(code: str) -> JSONResponse:
    """The single 401 shape for this service (same body + ``WWW-Authenticate``)."""
    return JSONResponse(
        {"error": code},
        status_code=401,
        headers={"WWW-Authenticate": _WWW_AUTH},
    )


_unauthorized = unauthorized  # שם פנימי היסטורי — נשמר לתאימות


def extract_bearer_token(request: Request) -> str | None:
    """Return the raw credential from ``Authorization: Bearer <token>``, else None.

    ``None`` means *no* Bearer credential was presented (a different 401 code
    than a presented-but-rejected one), so callers can tell the two apart.
    """
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        return None
    token = auth.split(" ", 1)[1].strip()
    return token or None


async def verify_bearer_token(
    token: str, *, token_store: Any = None, auth_provider: Any = None
) -> dict[str, Any] | None:
    """Verify a raw credential and return ``{"user_id", "scopes"}`` or ``None``.

    Routes to whichever verifier this deployment is running:
    ``auth_provider.load_access_token`` in OAuth mode (accepts both ``ckmcp_``
    PATs and ``ckoat_`` OAuth tokens), otherwise ``token_store.verify``. Both end
    at :meth:`MCPTokenStore.verify` for a PAT — one credential path, two entries.

    Fails closed: any exception is logged (never the token) and treated as a
    rejection.
    """
    if not token:
        return None
    try:
        if auth_provider is not None:
            access = await auth_provider.load_access_token(token)
            subject = getattr(access, "subject", None) if access is not None else None
            if subject is None:
                return None
            return {"user_id": int(subject), "scopes": list(getattr(access, "scopes", None) or [])}
        if token_store is None:
            # לא הוגדר שום מאמת — פייל-קלוז'ד במקום לתת מעבר חופשי.
            logger.warning("verify_bearer_token called with no verifier configured")
            return None
        # verify() is a sync DB call — keep it off the event loop.
        principal = await anyio.to_thread.run_sync(token_store.verify, token)
    except Exception:
        # Log the failure (never the token) so DB/connectivity issues are
        # diagnosable in production, then fail closed.
        logger.warning("MCP token verification raised an error", exc_info=True)
        return None

    if not principal:
        return None
    return {
        "user_id": int(principal["user_id"]),
        "scopes": list(principal.get("scopes") or []),
    }


async def authenticate_bearer(
    request: Request, *, token_store: Any = None, auth_provider: Any = None
) -> dict[str, Any] | None:
    """Authenticate a request end-to-end. ``None`` ⇒ reject with 401.

    This is what a hand-mounted route calls; see the module docstring for why
    such a route cannot rely on the app being "already protected".
    """
    token = extract_bearer_token(request)
    if token is None:
        return None
    return await verify_bearer_token(token, token_store=token_store, auth_provider=auth_provider)


class PATAuthMiddleware(BaseHTTPMiddleware):
    """Authenticate every non-exempt request with a Personal Access Token."""

    def __init__(
        self, app: Any, token_store: Any, *, exempt_paths: Iterable[str] = EXEMPT_PATHS
    ) -> None:
        super().__init__(app)
        self._store = token_store
        self._exempt = set(exempt_paths)

    async def dispatch(self, request: Request, call_next):
        if request.url.path in self._exempt:
            return await call_next(request)

        token = extract_bearer_token(request)
        if token is None:
            return unauthorized("missing_bearer_token")

        principal = await verify_bearer_token(token, token_store=self._store)
        if not principal:
            return unauthorized("invalid_token")

        request.state.user_id = int(principal["user_id"])
        request.state.scopes = list(principal["scopes"])
        return await call_next(request)


def current_user_id(ctx: Any = None) -> int:
    """Return the authenticated user's id inside an MCP tool.

    Works in both auth modes:
    - OAuth mode: the SDK auth layer exposes the verified access token via
      ``get_access_token()`` (its ``subject`` carries the user id).
    - PAT-only mode: :class:`PATAuthMiddleware` injected the id onto
      ``request.state`` (reachable through the tool ``Context``).

    Fails closed with ``PermissionError`` if neither is present.
    """
    try:
        from mcp.server.auth.middleware.auth_context import get_access_token

        token = get_access_token()
    except Exception:
        token = None
    if token is not None and getattr(token, "subject", None) is not None:
        return int(token.subject)

    request = getattr(getattr(ctx, "request_context", None), "request", None)
    user_id = getattr(getattr(request, "state", None), "user_id", None)
    if user_id is None:
        raise PermissionError("unauthenticated")
    return int(user_id)


def _token_scopes(ctx: Any = None) -> list[str]:
    """Scopes granted to the current request — same OAuth→PAT fallback as above.

    OAuth mode: the verified access token (for both OAuth ``ckoat_`` and PAT
    ``ckmcp_`` tokens) exposes ``.scopes``. PAT-only mode has no auth context, so
    :class:`PATAuthMiddleware` put the scopes on ``request.state``.
    """
    try:
        from mcp.server.auth.middleware.auth_context import get_access_token

        token = get_access_token()
    except Exception:
        token = None
    if token is not None and getattr(token, "scopes", None) is not None:
        return list(token.scopes)

    request = getattr(getattr(ctx, "request_context", None), "request", None)
    return list(getattr(getattr(request, "state", None), "scopes", None) or [])


def require_write(ctx: Any = None) -> None:
    """Raise unless the caller's token carries the ``write`` scope.

    The MCP SDK has no per-tool scope gate, so write tools call this first. A
    raised ``PermissionError`` surfaces to the model as an error tool result
    whose text is this message (not an HTTP 403).
    """
    if "write" not in _token_scopes(ctx):
        raise PermissionError(
            "insufficient_scope: this action needs write permission. Reconnect "
            "CodeKeeper granting write access (re-add the connector, or use a "
            "write-enabled token)."
        )


def admin_user_ids() -> set[int]:
    """The canonical admin set: ``config.ADMIN_USER_IDS`` — and nothing else.

    Deliberately does NOT honor the ``CHATOPS_ALLOW_ALL_IF_NO_ADMINS`` escape
    hatch (chatops/permissions.py): for the admin-only repo tools an empty list
    must mean *nobody* is admin. Fail-closed: any error ⇒ empty set.
    """
    try:
        from config import config as _cfg

        return {int(x) for x in (getattr(_cfg, "ADMIN_USER_IDS", None) or [])}
    except Exception:
        return set()


def is_admin_user(user_id: Any) -> bool:
    try:
        return int(user_id) in admin_user_ids()
    except (TypeError, ValueError):
        return False


def require_admin(ctx: Any = None) -> int:
    """Return the verified admin ``user_id`` or raise (fail-closed).

    Identity comes from the token only (``current_user_id``); the admin check is
    membership in ``ADMIN_USER_IDS``. Like ``require_write``, a raised
    ``PermissionError`` reaches the model as an error tool result.
    """
    user_id = current_user_id(ctx)  # raises PermissionError when unauthenticated
    if not is_admin_user(user_id):
        raise PermissionError("admin_only: this tool is restricted to the CodeKeeper admin user.")
    return int(user_id)
