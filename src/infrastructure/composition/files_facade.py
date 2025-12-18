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

    def _get_db(self):
        """
        Return current DatabaseManager, refreshing if the runtime `database.db` changed.

        Why: tests often monkeypatch `sys.modules['database']` (or its `db`) between tests.
        The composition root keeps a singleton `FilesFacade`, so we must re-bind to the
        current db object on each call to avoid stale references.
        """
        try:
            from database import db as current  # type: ignore
            if current is not None and current is not self._db:
                self._db = current
        except Exception:
            pass
        return self._db

    # ---- Thin delegates to DatabaseManager ---------------------------------
    def rename_file(self, user_id: int, old_name: str, new_name: str) -> bool:
        db = self._get_db()
        return bool(db.rename_file(user_id, old_name, new_name))

    def get_latest_version(self, user_id: int, file_name: str) -> Optional[Dict[str, Any]]:
        db = self._get_db()
        return db.get_latest_version(user_id, file_name)

    def get_all_versions(self, user_id: int, file_name: str) -> List[Dict[str, Any]]:
        db = self._get_db()
        return list(db.get_all_versions(user_id, file_name) or [])

    def get_user_files(
        self,
        user_id: int,
        limit: int = 50,
        *,
        skip: int = 0,
        projection: Optional[Dict[str, int]] = None,
    ) -> List[Dict[str, Any]]:
        db = self._get_db()
        return list(
            db.get_user_files(user_id, limit=limit, skip=skip, projection=projection) or []
        )
    def get_user_large_files(self, user_id: int, page: int = 1, per_page: int = 8) -> Tuple[List[Dict[str, Any]], int]:
        try:
            db = self._get_db()
            return db.get_user_large_files(user_id, page=page, per_page=per_page)
        except Exception:
            return ([], 0)

    def get_user_file_names(self, user_id: int, limit: int = 1000) -> List[str]:
        db = self._get_db()
        return list(db.get_user_file_names(user_id, limit) or [])

    def delete_file(self, user_id: int, file_name: str) -> bool:
        db = self._get_db()
        return bool(db.delete_file(user_id, file_name))

    def toggle_favorite(self, user_id: int, file_name: str) -> Optional[bool]:
        try:
            db = self._get_db()
            return db.toggle_favorite(user_id, file_name)
        except Exception:
            return None

    def get_favorites(self, user_id: int, language: Optional[str] = None, sort_by: str = "date", limit: int = 50) -> List[Dict[str, Any]]:
        db = self._get_db()
        return list(db.get_favorites(user_id, language=language, sort_by=sort_by, limit=limit) or [])

    def get_favorites_count(self, user_id: int) -> int:
        try:
            db = self._get_db()
            return int(db.get_favorites_count(user_id) or 0)
        except Exception:
            return 0
    def is_favorite(self, user_id: int, file_name: str) -> bool:
        try:
            db = self._get_db()
            return bool(db.is_favorite(user_id, file_name))
        except Exception:
            return False

    # ---- Save/update operations -------------------------------------------
    def save_file(self, user_id: int, file_name: str, code: str, programming_language: str, extra_tags: Optional[List[str]] = None) -> bool:
        db = self._get_db()
        return bool(db.save_file(user_id, file_name, code, programming_language, extra_tags))

    def save_code_snippet(self, *, user_id: int, file_name: str, code: str, programming_language: str, description: str = "", tags: Optional[List[str]] = None) -> bool:
        """Persist a CodeSnippet including description field (for notes)."""
        try:
            from database.models import CodeSnippet  # type: ignore
        except Exception:
            # Older path (if available)
            try:
                from database import CodeSnippet  # type: ignore
            except Exception:
                CodeSnippet = None  # type: ignore
        if CodeSnippet is None:  # type: ignore
            return False
        snippet = CodeSnippet(
            user_id=user_id,
            file_name=file_name,
            code=code,
            programming_language=programming_language,
            description=description,
            tags=list(tags or []),
        )
        db = self._get_db()
        return bool(db.save_code_snippet(snippet))

    # ---- Large files -------------------------------------------------------
    def save_large_file(self, *, user_id: int, file_name: str, content: str, programming_language: str, file_size: int, lines_count: int) -> bool:
        try:
            from database.models import LargeFile  # type: ignore
        except Exception:
            try:
                from database import LargeFile  # type: ignore
            except Exception:
                LargeFile = None  # type: ignore
        if LargeFile is None:  # type: ignore
            return False
        lf = LargeFile(
            user_id=user_id,
            file_name=file_name,
            content=content,
            programming_language=programming_language,
            file_size=file_size,
            lines_count=lines_count,
        )
        db = self._get_db()
        return bool(db.save_large_file(lf))

    # ---- Direct lookups by id/name (for view/share flows) ------------------
    def get_file_by_id(self, file_id: str) -> Optional[Dict[str, Any]]:
        try:
            db = self._get_db()
            return db.get_file_by_id(file_id)
        except Exception:
            return None

    def get_large_file_by_id(self, file_id: str) -> Optional[Dict[str, Any]]:
        try:
            db = self._get_db()
            return db.get_large_file_by_id(file_id)
        except Exception:
            return None

    def get_large_file(self, user_id: int, file_name: str) -> Optional[Dict[str, Any]]:
        try:
            db = self._get_db()
            return db.get_large_file(user_id, file_name)
        except Exception:
            return None

    # ---- GitHub / Drive related convenience wrappers ----------------------
    def save_selected_repo(self, user_id: int, repo_full: str) -> bool:
        try:
            db = self._get_db()
            return bool(db.save_selected_repo(user_id, repo_full))
        except Exception:
            return False

    def get_drive_tokens(self, user_id: int) -> Optional[Dict[str, Any]]:
        try:
            db = self._get_db()
            return db.get_drive_tokens(user_id) or {}
        except Exception:
            return {}

    def get_drive_prefs(self, user_id: int) -> Optional[Dict[str, Any]]:
        try:
            db = self._get_db()
            return db.get_drive_prefs(user_id) or {}
        except Exception:
            return {}

    def save_drive_prefs(self, user_id: int, update_prefs: Dict[str, Any]) -> bool:
        try:
            db = self._get_db()
            return bool(db.save_drive_prefs(user_id, update_prefs))
        except Exception:
            return False

    def delete_drive_tokens(self, user_id: int) -> bool:
        try:
            db = self._get_db()
            return bool(db.delete_drive_tokens(user_id))
        except Exception:
            return False

    # ---- Additional helpers used by legacy handlers -------------------------
    def save_user(self, user_id: int, username: Optional[str] = None) -> bool:
        try:
            db = self._get_db()
            return bool(db.save_user(user_id, username))
        except Exception:
            return False

    def get_repo_tags_with_counts(self, user_id: int, max_tags: int = 100) -> List[Dict[str, Any]]:
        try:
            db = self._get_db()
            return list(db.get_repo_tags_with_counts(user_id, max_tags=max_tags) or [])
        except Exception:
            return []

    def get_regular_files_paginated(
        self,
        user_id: int,
        page: int = 1,
        per_page: int = 10,
    ) -> Tuple[List[Dict[str, Any]], int]:
        try:
            db = self._get_db()
            return db.get_regular_files_paginated(user_id, page=page, per_page=per_page)
        except Exception:
            return ([], 0)

    def _repo(self):
        db = self._get_db()
        repo_getter = getattr(db, "_get_repo", None)
        if callable(repo_getter):
            try:
                return repo_getter()
            except Exception:
                return None
        return None

    def list_deleted_files(self, user_id: int, page: int = 1, per_page: int = 10) -> Tuple[List[Dict[str, Any]], int]:
        repo = self._repo()
        if repo is None:
            return ([], 0)
        try:
            return repo.list_deleted_files(user_id, page=page, per_page=per_page)
        except Exception:
            return ([], 0)

    def restore_file_by_id(self, user_id: int, file_id: str) -> bool:
        repo = self._repo()
        if repo is None:
            return False
        try:
            return bool(repo.restore_file_by_id(user_id, file_id))
        except Exception:
            return False

    def purge_file_by_id(self, user_id: int, file_id: str) -> bool:
        repo = self._repo()
        if repo is None:
            return False
        try:
            return bool(repo.purge_file_by_id(user_id, file_id))
        except Exception:
            return False

    def delete_file_by_id(self, file_id: str) -> bool:
        try:
            db = self._get_db()
            return bool(db.delete_file_by_id(file_id))
        except Exception:
            return False

    def get_user_files_by_repo(
        self,
        user_id: int,
        repo_tag: str,
        page: int = 1,
        per_page: int = 50,
    ) -> Tuple[List[Dict[str, Any]], int]:
        try:
            db = self._get_db()
            return db.get_user_files_by_repo(user_id, repo_tag, page=page, per_page=per_page)
        except Exception:
            return ([], 0)

    def search_code(
        self,
        user_id: int,
        query: str,
        *,
        programming_language: Optional[str] = None,
        tags: Optional[List[str]] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        try:
            return list(
                self._get_db().search_code(
                    user_id,
                    query,
                    programming_language=programming_language,
                    tags=tags,
                    limit=limit,
                )
                or []
            )
        except Exception:
            return []

    def get_version(self, user_id: int, file_name: str, version: int) -> Optional[Dict[str, Any]]:
        try:
            db = self._get_db()
            return db.get_version(user_id, file_name, version)
        except Exception:
            return None

    def get_backup_rating(self, user_id: int, backup_id: str) -> Optional[str]:
        try:
            db = self._get_db()
            return db.get_backup_rating(user_id, backup_id)
        except Exception:
            return None

    @staticmethod
    def _doc_belongs_to_user(doc: Dict[str, Any], user_id: int) -> bool:
        try:
            return int(doc.get("user_id")) == int(user_id)
        except Exception:
            try:
                return str(doc.get("user_id")) == str(user_id)
            except Exception:
                return False

    def get_user_document_by_id(self, user_id: int, file_id: str) -> Tuple[Optional[Dict[str, Any]], bool]:
        """
        Return (document, is_large_file) ensuring the file belongs to the user.
        """
        try:
            db = self._get_db()
            doc = db.get_file_by_id(file_id)
        except Exception:
            doc = None
        if isinstance(doc, dict) and self._doc_belongs_to_user(doc, user_id):
            return doc, False
        try:
            db = self._get_db()
            large_doc = db.get_large_file_by_id(file_id)
        except Exception:
            large_doc = None
        if isinstance(large_doc, dict) and self._doc_belongs_to_user(large_doc, user_id):
            return large_doc, True
        return None, False

