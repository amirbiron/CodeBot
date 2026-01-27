from __future__ import annotations

import threading
from typing import Optional

from .container import get_snippet_service as _get_snippet_service
from .files_facade import FilesFacade

_files_facade_singleton: Optional[FilesFacade] = None
_files_facade_lock = threading.Lock()


def get_files_facade() -> FilesFacade:
    """
    Composition Root for the WebApp - provides a FilesFacade singleton.
    """
    global _files_facade_singleton
    if _files_facade_singleton is not None:
        return _files_facade_singleton
    # Ensure singleton creation is thread-safe under concurrent first requests
    with _files_facade_lock:
        if _files_facade_singleton is None:
            _files_facade_singleton = FilesFacade()
    return _files_facade_singleton


def get_snippet_service():
    """
    Re-export snippet service factory for webapp usage.
    """
    return _get_snippet_service()
