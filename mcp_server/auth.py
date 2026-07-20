"""PAT (Bearer) authentication for the MCP HTTP app.

A Starlette middleware verifies ``Authorization: Bearer <token>`` against the
token store and injects the authenticated ``user_id`` onto ``request.state``.
Tools then read it via :func:`current_user_id` (same request object — no
contextvar propagation to worry about).

This is deliberately simple (Phase 0). Phase 1 replaces it with OAuth 2.1.
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


def _unauthorized(code: str) -> JSONResponse:
    return JSONResponse(
        {"error": code},
        status_code=401,
        headers={"WWW-Authenticate": _WWW_AUTH},
    )


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

        auth = request.headers.get("authorization", "")
        if not auth.lower().startswith("bearer "):
            return _unauthorized("missing_bearer_token")

        token = auth.split(" ", 1)[1].strip()
        try:
            # verify() is a sync DB call — keep it off the event loop.
            principal = await anyio.to_thread.run_sync(self._store.verify, token)
        except Exception:
            # Log the failure (never the token) so DB/connectivity issues are
            # diagnosable in production, then fail closed.
            logger.warning("MCP token verification raised an error", exc_info=True)
            principal = None

        if not principal:
            return _unauthorized("invalid_token")

        request.state.user_id = int(principal["user_id"])
        request.state.scopes = list(principal.get("scopes") or [])
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
