from __future__ import annotations

# Public API of the composition root
# Import from webapp_container which is the authoritative source for webapp DI
from .container import get_snippet_service  # noqa: F401
from .files_facade import FilesFacade  # noqa: F401
from .webapp_container import (  # noqa: F401
    WebappContainer,
    get_files_facade,
    get_webapp_container,
)

__all__ = [
    "FilesFacade",
    "WebappContainer",
    "get_files_facade",
    "get_snippet_service",
    "get_webapp_container",
]
