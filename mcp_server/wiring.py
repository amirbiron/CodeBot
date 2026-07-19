"""Small wiring helpers shared between the ASGI entrypoint and CLI scripts.

Kept free of heavy/side-effecting imports so both ``mcp_server.app`` and
``scripts/mcp_issue_token.py`` can reuse it without triggering a Mongo connect.
"""

from __future__ import annotations

from typing import Any


def resolve_mongo(db_manager: Any) -> Any:
    """Return the pymongo Database handle, forcing a lazy connection if needed."""
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
