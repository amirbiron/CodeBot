"""
Webapp Composition Root - entry point for dependency injection in the webapp layer.

This module provides a clean, centralized access point for all services
and facades that the webapp routes need. Instead of importing directly from
multiple places, webapp code should import from here.

Usage in webapp routes:
    from src.infrastructure.composition.webapp_container import (
        get_files_facade,
        get_snippet_service,
    )

    # In a route handler:
    facade = get_files_facade()
    files = facade.get_user_files(user_id, limit=50)

Architecture:
    Route -> WebappContainer -> Facade/Service -> Repository -> DB
"""
from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from src.application.services.snippet_service import SnippetService

# Import singleton factory from sibling module (avoiding __init__ circular import)
from .container import get_snippet_service  # noqa: F401
from .files_facade import FilesFacade

__all__ = [
    "get_files_facade",
    "get_snippet_service",
    "get_webapp_container",
    "WebappContainer",
]

# Thread-safe singleton for FilesFacade
_files_facade_singleton: Optional[FilesFacade] = None
_files_facade_lock = threading.Lock()


def get_files_facade() -> FilesFacade:
    """
    Get the singleton FilesFacade instance (thread-safe).

    Returns a FilesFacade that provides access to all file/snippet
    operations without direct database imports.
    """
    global _files_facade_singleton
    if _files_facade_singleton is not None:
        return _files_facade_singleton
    # Ensure singleton creation is thread-safe under concurrent first requests
    with _files_facade_lock:
        if _files_facade_singleton is None:
            _files_facade_singleton = FilesFacade()
    return _files_facade_singleton


class WebappContainer:
    """
    Convenience class for webapp routes that prefer an object-oriented access pattern.

    Provides lazy access to all facades and services via properties.
    Useful for dependency injection in class-based views or testing scenarios.

    Example:
        container = WebappContainer()
        files = container.files_facade.get_user_files(user_id)
        snippet = container.snippet_service.get_snippet(user_id, filename)
    """

    @property
    def files_facade(self) -> FilesFacade:
        """Get the singleton FilesFacade instance."""
        return get_files_facade()

    @property
    def snippet_service(self) -> "SnippetService":
        """Get the singleton SnippetService instance."""
        return get_snippet_service()


# Module-level singleton for convenience
_container: Optional[WebappContainer] = None
_container_lock = threading.Lock()


def get_webapp_container() -> WebappContainer:
    """
    Get the webapp container singleton (thread-safe).

    Returns a WebappContainer instance that provides access to all
    infrastructure services needed by webapp routes.
    """
    global _container
    if _container is not None:
        return _container
    with _container_lock:
        if _container is None:
            _container = WebappContainer()
    return _container
