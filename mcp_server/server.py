"""FastMCP server wiring: tools + resources + the authenticated ASGI app.

``build_mcp`` registers the read-only tools against an injected ``Backend``.
``build_app`` returns a Starlette ASGI app (Streamable HTTP) wrapped with PAT
auth plus an unauthenticated ``/healthz`` endpoint for platform health checks.

Tools are defined as **sync** functions on purpose: FastMCP runs sync tools in a
worker thread, so the blocking (pymongo) backend calls never stall the event
loop, and the tool can still read ``ctx.request_context.request.state``.
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import Context, FastMCP
from starlette.responses import JSONResponse
from starlette.routing import Route

from . import handlers
from .auth import PATAuthMiddleware, current_user_id

_INSTRUCTIONS = (
    "Access the current user's private code files and collections stored in "
    "CodeKeeper. Use search_code / list_files to find files (metadata only), "
    "and get_file to read full contents. All data is scoped to the "
    "authenticated user; this server is read-only."
)


def build_mcp(backend: Any, *, name: str = "CodeKeeper") -> FastMCP:
    mcp: FastMCP = FastMCP(name, instructions=_INSTRUCTIONS, stateless_http=True)

    @mcp.tool(description="List the user's saved code files (metadata only, no code).")
    def list_files(ctx: Context, page: int = 1, per_page: int = 50) -> dict:
        return handlers.list_files(backend, current_user_id(ctx), page=page, per_page=per_page)

    @mcp.tool(description="Search the user's code by text; returns file metadata (no content).")
    def search_code(ctx: Context, query: str, language: str | None = None, limit: int = 20) -> dict:
        results = handlers.search_code(
            backend, current_user_id(ctx), query=query, language=language, limit=limit
        )
        return {"query": query, "count": len(results), "results": results}

    @mcp.tool(description="Get a file's full content by name or id (optional version number).")
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

    @mcp.tool(description="List all saved versions of a file by file_name (metadata only).")
    def list_versions(ctx: Context, file_name: str) -> dict:
        versions = handlers.list_versions(backend, current_user_id(ctx), file_name=file_name)
        return {"file_name": file_name, "count": len(versions), "versions": versions}

    @mcp.tool(description="List the user's collections (named folders of files).")
    def list_collections(ctx: Context, limit: int = 100) -> dict:
        return handlers.list_collections(backend, current_user_id(ctx), limit=limit)

    @mcp.tool(description="Get a single collection by its id.")
    def get_collection(ctx: Context, collection_id: str) -> dict:
        return handlers.get_collection(backend, current_user_id(ctx), collection_id=collection_id)

    @mcp.tool(description="List files in a collection (paginated); optional folder filter.")
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


def build_app(backend: Any, token_store: Any, *, name: str = "CodeKeeper"):
    """Build the authenticated Streamable-HTTP ASGI app."""
    mcp = build_mcp(backend, name=name)
    app = mcp.streamable_http_app()  # Starlette app exposing POST/GET /mcp
    # Unauthenticated health endpoint for the hosting platform.
    app.router.routes.append(Route("/healthz", _healthz, methods=["GET"]))
    # Auth guards everything except the exempt paths (see PATAuthMiddleware).
    app.add_middleware(PATAuthMiddleware, token_store=token_store)
    return app
