"""ASGI entrypoint for the CodeKeeper MCP server.

Run with::

    uvicorn mcp_server.app:app --host 0.0.0.0 --port $PORT

Importing this module connects to MongoDB (via the shared ``database`` layer),
so it is intentionally NOT imported by the unit tests — those exercise the
lighter ``handlers`` / ``backend`` / ``token_store`` modules directly.
"""

from __future__ import annotations

import os
from typing import Any

from .backend import ProductionBackend
from .server import build_app
from .token_store import MCPTokenStore


def _resolve_mongo(db_manager: Any) -> Any:
    """Return the pymongo Database handle, forcing a connection if needed."""
    mongo = getattr(db_manager, "db", None)
    if mongo is not None:
        return mongo
    # Some managers connect lazily; nudge them, then re-read.
    for attr in ("connect", "_get_repo", "ensure_connection"):
        fn = getattr(db_manager, attr, None)
        if callable(fn):
            try:
                fn()
            except Exception:
                pass
            mongo = getattr(db_manager, "db", None)
            if mongo is not None:
                return mongo
    return None


def create_app():
    from database import db as db_manager  # lazy heavy import

    mongo = _resolve_mongo(db_manager)
    if mongo is None:
        raise RuntimeError(
            "MongoDB is not available (database.db is None). "
            "Set MONGODB_URL for the MCP service."
        )

    token_store = MCPTokenStore(mongo)
    backend = ProductionBackend(db_manager=db_manager, mongo_db=mongo)
    name = os.getenv("MCP_SERVER_NAME", "CodeKeeper")
    return build_app(backend, token_store, name=name)


app = create_app()
