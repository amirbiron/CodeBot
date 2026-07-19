"""FastMCP server wiring: tools + resources + the authenticated ASGI app.

``build_mcp`` registers the read-only tools against an injected ``Backend``.
``build_app`` returns a Starlette ASGI app (Streamable HTTP) wrapped with PAT
auth plus an unauthenticated ``/healthz`` endpoint for platform health checks.

Tools are defined as **sync** functions on purpose: FastMCP runs sync tools in a
worker thread, so the blocking (pymongo) backend calls never stall the event
loop, and the tool can still read ``ctx.request_context.request.state``.
"""

from __future__ import annotations

import os
from typing import Any

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.responses import JSONResponse
from starlette.routing import Route

from . import handlers
from .auth import PATAuthMiddleware, current_user_id

_INSTRUCTIONS = (
    "Access the current user's private code files and collections stored in "
    "CodeKeeper. Use codekeeper_search_code / codekeeper_list_files to find files "
    "(metadata only), and codekeeper_get_file to read full contents. All data is "
    "scoped to the authenticated user; this server is read-only."
)

# Shared annotations: every tool here is a non-destructive, idempotent read over
# the user's own bounded data store (service-prefixed to avoid cross-connector
# collisions on generic names like get_file / list_files).
_READ_ONLY_TOOL = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": False,
}


def _transport_security() -> TransportSecuritySettings:
    """DNS-rebinding protection config for the Streamable-HTTP transport.

    That protection targets *localhost* servers (a malicious web page tricking a
    browser into calling 127.0.0.1). This server is public and Bearer-token
    gated, so the default host check only blocks legitimate access behind a real
    domain (HTTP 421 "Invalid Host header"). Default: OFF. Set MCP_ALLOWED_HOSTS
    (comma-separated; wildcards like ``*.onrender.com`` allowed) to lock it down.
    """
    hosts = [h.strip() for h in os.getenv("MCP_ALLOWED_HOSTS", "").split(",") if h.strip()]
    origins = [o.strip() for o in os.getenv("MCP_ALLOWED_ORIGINS", "").split(",") if o.strip()]
    if hosts or origins:
        return TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=hosts,
            allowed_origins=origins,
        )
    return TransportSecuritySettings(enable_dns_rebinding_protection=False)


def build_mcp(
    backend: Any,
    *,
    name: str = "CodeKeeper",
    auth_provider: Any = None,
    auth_settings: Any = None,
) -> FastMCP:
    kwargs: dict[str, Any] = {
        "instructions": _INSTRUCTIONS,
        "stateless_http": True,
        "transport_security": _transport_security(),
    }
    if auth_provider is not None and auth_settings is not None:
        # Enables the SDK's OAuth endpoints (.well-known / authorize / token /
        # register) plus the auth layer that calls provider.load_access_token.
        kwargs["auth_server_provider"] = auth_provider
        kwargs["auth"] = auth_settings
    mcp: FastMCP = FastMCP(name, **kwargs)

    @mcp.tool(
        name="codekeeper_list_files",
        description="List the user's saved code files (metadata only, no code).",
        annotations=_READ_ONLY_TOOL,
    )
    def list_files(ctx: Context, page: int = 1, per_page: int = 50) -> dict:
        return handlers.list_files(backend, current_user_id(ctx), page=page, per_page=per_page)

    @mcp.tool(
        name="codekeeper_search_code",
        description="Search the user's code by text; returns file metadata (no content).",
        annotations=_READ_ONLY_TOOL,
    )
    def search_code(ctx: Context, query: str, language: str | None = None, limit: int = 20) -> dict:
        results = handlers.search_code(
            backend, current_user_id(ctx), query=query, language=language, limit=limit
        )
        return {"query": query, "count": len(results), "results": results}

    @mcp.tool(
        name="codekeeper_get_file",
        description="Get a file's full content by name or id (optional version number).",
        annotations=_READ_ONLY_TOOL,
    )
    def get_file(
        ctx: Context,
        file_name: str | None = None,
        file_id: str | None = None,
        version: int | None = None,
    ) -> dict:
        doc = handlers.get_file(
            backend, current_user_id(ctx), file_name=file_name, file_id=file_id, version=version
        )
        if doc is None:
            return {"found": False}
        return {"found": True, "file": doc}

    @mcp.tool(
        name="codekeeper_list_versions",
        description="List all saved versions of a file by file_name (metadata only).",
        annotations=_READ_ONLY_TOOL,
    )
    def list_versions(ctx: Context, file_name: str) -> dict:
        versions = handlers.list_versions(backend, current_user_id(ctx), file_name=file_name)
        return {"file_name": file_name, "count": len(versions), "versions": versions}

    @mcp.tool(
        name="codekeeper_list_collections",
        description="List the user's collections (named folders of files).",
        annotations=_READ_ONLY_TOOL,
    )
    def list_collections(ctx: Context, limit: int = 100) -> dict:
        return handlers.list_collections(backend, current_user_id(ctx), limit=limit)

    @mcp.tool(
        name="codekeeper_get_collection",
        description="Get a single collection by its id.",
        annotations=_READ_ONLY_TOOL,
    )
    def get_collection(ctx: Context, collection_id: str) -> dict:
        return handlers.get_collection(backend, current_user_id(ctx), collection_id=collection_id)

    @mcp.tool(
        name="codekeeper_get_collection_items",
        description="List files in a collection (paginated); optional folder filter.",
        annotations=_READ_ONLY_TOOL,
    )
    def get_collection_items(
        ctx: Context,
        collection_id: str,
        page: int = 1,
        per_page: int = 50,
        folder: str | None = None,
    ) -> dict:
        return handlers.get_collection_items(
            backend,
            current_user_id(ctx),
            collection_id=collection_id,
            page=page,
            per_page=per_page,
            folder=folder,
        )

    return mcp


async def _healthz(_request):
    return JSONResponse({"status": "ok", "service": "codekeeper-mcp"})


def build_app(
    backend: Any,
    token_store: Any = None,
    *,
    auth_provider: Any = None,
    auth_settings: Any = None,
    consent_routes: Any = None,
    name: str = "CodeKeeper",
):
    """Build the authenticated Streamable-HTTP ASGI app.

    Two auth modes:
    - OAuth (auth_provider + auth_settings given): the SDK mounts the OAuth
      endpoints and verifies via provider.load_access_token — which also accepts
      PATs, so Claude Code and Claude.ai both work. ``consent_routes`` are mounted.
    - PAT-only (fallback): the custom ``PATAuthMiddleware`` guards the app.
    """
    oauth = auth_provider is not None and auth_settings is not None
    mcp = build_mcp(
        backend,
        name=name,
        auth_provider=auth_provider if oauth else None,
        auth_settings=auth_settings if oauth else None,
    )
    app = mcp.streamable_http_app()  # Starlette app exposing POST/GET /mcp
    # Unauthenticated health endpoint for the hosting platform.
    app.router.routes.append(Route("/healthz", _healthz, methods=["GET"]))
    if oauth:
        for route in consent_routes or []:
            app.router.routes.append(route)
    else:
        app.add_middleware(PATAuthMiddleware, token_store=token_store)
    return app
