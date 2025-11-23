from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple


class FilesFacade:
    """
    Transitional facade for handlers to access DB operations via infrastructure.
    This keeps handlers free from importing the database directly while we
    gradually move features into application services.
    """

    def __init__(self) -> None:
        # Lazy to avoid import-time failures in tests without DB
        from database import db  # type: ignore
        self._db = db

    # ---- Thin delegates to DatabaseManager ---------------------------------
    def rename_file(self, user_id: int, old_name: str, new_name: str) -> bool:
        return bool(self._db.rename_file(user_id, old_name, new_name))

    def get_latest_version(self, user_id: int, file_name: str) -> Optional[Dict[str, Any]]:
        return self._db.get_latest_version(user_id, file_name)

    def get_all_versions(self, user_id: int, file_name: str) -> List[Dict[str, Any]]:
        return list(self._db.get_all_versions(user_id, file_name) or [])

    def get_user_files(self, user_id: int, limit: int = 50, *, skip: int = 0) -> List[Dict[str, Any]]:
        return list(self._db.get_user_files(user_id, limit=limit, skip=skip) or [])

    def get_user_file_names(self, user_id: int, limit: int = 1000) -> List[str]:
        return list(self._db.get_user_file_names(user_id, limit) or [])

    def delete_file(self, user_id: int, file_name: str) -> bool:
        return bool(self._db.delete_file(user_id, file_name))

    def toggle_favorite(self, user_id: int, file_name: str) -> Optional[bool]:
        try:
            return self._db.toggle_favorite(user_id, file_name)
        except Exception:
            return None

    def get_favorites(self, user_id: int, language: Optional[str] = None, sort_by: str = "date", limit: int = 50) -> List[Dict[str, Any]]:
        return list(self._db.get_favorites(user_id, language=language, sort_by=sort_by, limit=limit) or [])

    def get_favorites_count(self, user_id: int) -> int:
        try:
            return int(self._db.get_favorites_count(user_id) or 0)
        except Exception:
            return 0

