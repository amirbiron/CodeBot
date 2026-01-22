from __future__ import annotations

import threading
from typing import Optional


_snippet_service_singleton = None  # type: Optional["SnippetService"]
_singleton_lock = threading.Lock()


def get_snippet_service():
    """
    Composition Root: build and return a singleton SnippetService.
    Keeps construction inside infrastructure, so handlers only depend on the application layer.
    """
    global _snippet_service_singleton
    if _snippet_service_singleton is not None:
        return _snippet_service_singleton

    # Ensure singleton creation is thread-safe under concurrent first requests
    with _singleton_lock:
        if _snippet_service_singleton is not None:
            return _snippet_service_singleton

        # Lazy imports to avoid hard coupling at import time and ease tests/mocks
        from src.application.services.snippet_service import SnippetService  # type: ignore
        from src.domain.services.code_normalizer import CodeNormalizer  # type: ignore
        try:
            from src.domain.services.language_detector import LanguageDetector  # type: ignore
        except Exception:  # pragma: no cover - optional at runtime
            LanguageDetector = None  # type: ignore
        from src.infrastructure.database.mongodb.repositories.snippet_repository import (  # type: ignore
            SnippetRepository,
        )
        from database import db  # type: ignore

        repo = SnippetRepository(db)
        normalizer = CodeNormalizer()
        detector = LanguageDetector() if "LanguageDetector" in locals() and LanguageDetector else None  # type: ignore
        _snippet_service_singleton = SnippetService(
            snippet_repository=repo,
            code_normalizer=normalizer,
            language_detector=detector,
        )
        return _snippet_service_singleton

