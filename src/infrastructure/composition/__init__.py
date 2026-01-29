from __future__ import annotations

import threading

# Public API of the composition root
from .container import get_snippet_service  # noqa: F401
from .files_facade import FilesFacade, BOOKMARK_VALID_COLORS  # noqa: F401

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

