from __future__ import annotations

import threading
from typing import TYPE_CHECKING

# Public API of the composition root
from .container import get_snippet_service  # noqa: F401
from .files_facade import FilesFacade  # noqa: F401

if TYPE_CHECKING:
    from database.bookmarks_manager import BookmarksManager
    from database.collections_manager import CollectionsManager
    from services.rules_storage import RulesStorage
    from services.shared_theme_service import SharedThemeService

_files_facade_singleton = None
_files_facade_lock = threading.Lock()


def get_files_facade() -> FilesFacade:
    global _files_facade_singleton
    if _files_facade_singleton is not None:
        return _files_facade_singleton
    # Ensure singleton creation is thread-safe under concurrent first requests
    with _files_facade_lock:
        if _files_facade_singleton is None:
            _files_facade_singleton = FilesFacade()
    return _files_facade_singleton


# ---- Manager/Service Factory Functions ----------------------------------------
# These provide a clean composition root for WebApp to access legacy managers
# without importing `database.*` directly.


def get_bookmarks_manager() -> "BookmarksManager":
    """
    Factory for BookmarksManager.

    Usage in WebApp:
        from src.infrastructure.composition import get_bookmarks_manager
        manager = get_bookmarks_manager()
    """
    from database.bookmarks_manager import BookmarksManager
    from database import db

    return BookmarksManager(db)


def get_collections_manager() -> "CollectionsManager":
    """
    Factory for CollectionsManager.

    Usage in WebApp:
        from src.infrastructure.composition import get_collections_manager
        manager = get_collections_manager()
    """
    from database.collections_manager import CollectionsManager
    from database import db

    return CollectionsManager(db)


def get_rules_storage() -> "RulesStorage":
    """
    Factory for RulesStorage.

    Usage in WebApp:
        from src.infrastructure.composition import get_rules_storage
        storage = get_rules_storage()
    """
    from services.rules_storage import get_rules_storage as _get_rules_storage

    return _get_rules_storage()


def get_shared_theme_service() -> "SharedThemeService":
    """
    Factory for SharedThemeService (singleton).

    Usage in WebApp:
        from src.infrastructure.composition import get_shared_theme_service
        service = get_shared_theme_service()
    """
    from services.shared_theme_service import get_shared_theme_service as _get_shared_theme_service

    return _get_shared_theme_service()

