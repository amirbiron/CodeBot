"""ASGI entrypoint for the CodeKeeper MCP server.

Run with::

    uvicorn mcp_server.app:app --host 0.0.0.0 --port $PORT

Importing this module connects to MongoDB (via the shared ``database`` layer),
so it is intentionally NOT imported by the unit tests — those exercise the
lighter ``handlers`` / ``backend`` / ``token_store`` modules directly.
"""

from __future__ import annotations

import os

from .backend import ProductionBackend
from .server import build_app
from .token_store import MCPTokenStore
from .wiring import resolve_mongo


def create_app():
    from database import db as db_manager  # lazy heavy import

    mongo = resolve_mongo(db_manager)
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
