from __future__ import annotations

# Public API of the composition root
from .container import get_snippet_service  # noqa: F401
from .files_facade import FilesFacade  # noqa: F401

_files_facade_singleton = None


def get_files_facade() -> FilesFacade:
    global _files_facade_singleton
    if _files_facade_singleton is None:
        _files_facade_singleton = FilesFacade()
    return _files_facade_singleton

