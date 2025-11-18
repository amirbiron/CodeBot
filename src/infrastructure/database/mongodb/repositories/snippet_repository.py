from __future__ import annotations

from typing import List, Optional, Dict, Any

from src.domain.entities.snippet import Snippet
from src.domain.interfaces.snippet_repository_interface import ISnippetRepository

# We depend on existing database layer without changing it
from database.manager import DatabaseManager  # type: ignore
from database.models import CodeSnippet  # type: ignore


class SnippetRepository(ISnippetRepository):
    """MongoDB-backed repository implementing the domain interface.

    Delegates to the existing database layer to avoid DB changes.
    """

    def __init__(self, db_manager: DatabaseManager) -> None:
        self._db = db_manager

    async def save(self, snippet: Snippet) -> Snippet:
        """Persist snippet and return the latest version as a domain entity."""
        db_model = self._to_db_model(snippet)
        ok = bool(self._db.save_code_snippet(db_model))
        if not ok:
            # Return the input on failure to keep contract simple; callers can raise if needed
            return snippet
        # Fetch latest version to reflect version increment and DB timestamps
        latest = self._db.get_latest_version(snippet.user_id, snippet.filename)
        return self._from_db_doc(latest) if isinstance(latest, dict) else snippet

    async def get_latest_version(self, user_id: int, filename: str) -> Optional[Snippet]:
        doc = self._db.get_latest_version(user_id, filename)
        if not isinstance(doc, dict):
            return None
        return self._from_db_doc(doc)

    async def search(self, user_id: int, query: str, language: Optional[str] = None, limit: int = 20) -> List[Snippet]:
        docs = self._db.search_code(user_id, query, programming_language=language, tags=None, limit=limit)
        results: List[Snippet] = []
        for d in docs or []:
            if isinstance(d, dict):
                try:
                    results.append(self._from_db_doc(d))
                except Exception:
                    continue
        return results

    # ---------- Mapping helpers ----------
    def _to_db_model(self, s: Snippet) -> CodeSnippet:
        return CodeSnippet(
            user_id=s.user_id,
            file_name=s.filename,
            code=s.code,
            programming_language=s.language,
            description=s.description,
            tags=list(s.tags or []),
            is_favorite=bool(s.is_favorite),
        )

    def _from_db_doc(self, d: Dict[str, Any]) -> Snippet:
        return Snippet(
            user_id=int(d.get("user_id", 0) or 0),
            filename=str(d.get("file_name", "") or ""),
            code=str(d.get("code", "") or ""),
            language=str(d.get("programming_language", "text") or "text"),
            description=str(d.get("description", "") or ""),
            tags=list(d.get("tags", []) or []),
            version=int(d.get("version", 1) or 1),
            is_favorite=bool(d.get("is_favorite", False)),
            created_at=d.get("created_at"),
            updated_at=d.get("updated_at"),
            favorited_at=d.get("favorited_at"),
            is_active=bool(d.get("is_active", True)),
        )
