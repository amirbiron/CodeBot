"""
Thin DB access wrapper.

This module exists to provide a stable import path (`database.db_manager.get_db`)
for services that should not depend on `webapp.app` during import time.
"""

from __future__ import annotations

from typing import Any


def get_db() -> Any:
    """
    Return a DB handle (PyMongo-like), lazily initialized.

    Delegates to `services.db_provider.get_db` which is designed to avoid circular imports.
    """

    from services.db_provider import get_db as _get_db

    return _get_db()

