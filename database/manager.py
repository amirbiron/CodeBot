import logging
import os
from types import SimpleNamespace
from datetime import timezone
from typing import Any, Callable, Dict, List, Optional, Tuple, Protocol

try:
    from pymongo import MongoClient, IndexModel, ASCENDING, DESCENDING, TEXT
    _PYMONGO_AVAILABLE = True
except Exception:  # ModuleNotFoundError או כל שגיאה בזמן import
    _PYMONGO_AVAILABLE = False

    class MongoClient:  # runtime stub לשימוש במצבים ללא pymongo
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def __getitem__(self, name: str) -> Any:
            return SimpleNamespace()

        @property
        def admin(self) -> Any:
            class _Admin:
                def command(self, *_args: Any, **_kwargs: Any) -> Any:
                    return {"ok": 1}

            return _Admin()

    class IndexModel:  # runtime stub
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

    ASCENDING = 1
    DESCENDING = -1
    TEXT = "text"


class CollectionLike(Protocol):
    def insert_one(self, *args: Any, **kwargs: Any) -> Any: ...
    def update_one(self, *args: Any, **kwargs: Any) -> Any: ...
    def update_many(self, *args: Any, **kwargs: Any) -> Any: ...
    def delete_one(self, *args: Any, **kwargs: Any) -> Any: ...
    def delete_many(self, *args: Any, **kwargs: Any) -> Any: ...
    def find_one(self, *args: Any, **kwargs: Any) -> Any: ...
    def find(self, *args: Any, **kwargs: Any) -> Any: ...
    def aggregate(self, *args: Any, **kwargs: Any) -> Any: ...
    def count_documents(self, *args: Any, **kwargs: Any) -> int: ...
    def create_index(self, *args: Any, **kwargs: Any) -> Any: ...
    def create_indexes(self, *args: Any, **kwargs: Any) -> Any: ...
    def list_indexes(self, *args: Any, **kwargs: Any) -> Any: ...
    def drop_index(self, *args: Any, **kwargs: Any) -> Any: ...


class DBLike(Protocol):
    def __getitem__(self, name: str) -> CollectionLike: ...
    def __getattr__(self, name: str) -> CollectionLike: ...


class _StubCollection:
    """מימוש מינימלי שתואם את PyMongo לצורך אתחול מוקדם והימנעות מ-None."""

    def insert_one(self, *args: Any, **kwargs: Any) -> Any:
        return SimpleNamespace(inserted_id=None)

    def update_one(self, *args: Any, **kwargs: Any) -> Any:
        return SimpleNamespace(acknowledged=True, modified_count=0)

    def update_many(self, *args: Any, **kwargs: Any) -> Any:
        return SimpleNamespace(acknowledged=True, matched_count=0, modified_count=0)

    def delete_one(self, *args: Any, **kwargs: Any) -> Any:
        return SimpleNamespace(deleted_count=0)

    def delete_many(self, *args: Any, **kwargs: Any) -> Any:
        return SimpleNamespace(deleted_count=0)

    def find_one(self, *args: Any, **kwargs: Any) -> Any:
        return None

    def find_one_and_update(self, *args: Any, **kwargs: Any) -> Any:
        return None

    def aggregate(self, *args: Any, **kwargs: Any) -> Any:
        return []

    def count_documents(self, *args: Any, **kwargs: Any) -> int:
        return 0

    def create_index(self, *args: Any, **kwargs: Any) -> Any:
        return None

    def create_indexes(self, *args: Any, **kwargs: Any) -> Any:
        return None

    def list_indexes(self, *args: Any, **kwargs: Any) -> Any:
        return []

    def drop_index(self, *args: Any, **kwargs: Any) -> Any:
        return None

    def find(self, *args: Any, **kwargs: Any) -> Any:
        return []

from config import config
try:
    # Structured logging events
    from observability import emit_event
except Exception:  # pragma: no cover
    def emit_event(event: str, severity: str = "info", **fields):
        return None

logger = logging.getLogger(__name__)


class DatabaseManager:
    """אחראי על חיבור MongoDB והגדרת אינדקסים."""

    client: Optional[Any]
    db: Optional[DBLike]
    collection: CollectionLike
    large_files_collection: CollectionLike
    backup_ratings_collection: Optional[CollectionLike]
    internal_shares_collection: Optional[CollectionLike]
    _repo: Optional[Any]

    def __init__(self):
        self.client = None
        self.db = None
        # אתחול לאובייקטים שאינם None כדי לעמוד בטייפים
        self.collection = _StubCollection()
        self.large_files_collection = _StubCollection()
        self.backup_ratings_collection = _StubCollection()
        self.internal_shares_collection = _StubCollection()
        self._repo = None
        self.connect()

    def connect(self):
        # Docs build / CI: אפשר לנטרל חיבור למסד כדי למנוע שגיאות בזמן בניית דוקס
        disable_db = str(os.getenv("DISABLE_DB", "")).lower() in {"1", "true", "yes"} or \
                     str(os.getenv("SPHINX_MOCK_IMPORTS", "")).lower() in {"1", "true", "yes"}

        def _init_noop_collections():
            class NoOpCollection:
                def insert_one(self, *args, **kwargs):
                    return SimpleNamespace(inserted_id=None)
                def update_one(self, *args, **kwargs):
                    return SimpleNamespace(acknowledged=True, modified_count=0)
                def update_many(self, *args, **kwargs):
                    return SimpleNamespace(acknowledged=True, matched_count=0, modified_count=0)
                def delete_one(self, *args, **kwargs):
                    return SimpleNamespace(deleted_count=0)
                def delete_many(self, *args, **kwargs):
                    return SimpleNamespace(deleted_count=0)
                def find_one(self, *args, **kwargs):
                    return None
                def find_one_and_update(self, *args, **kwargs):
                    return None
                def aggregate(self, *args, **kwargs):
                    return []
                def count_documents(self, *args, **kwargs):
                    # Mimic PyMongo API; in no-op mode we report zero
                    return 0
                def create_index(self, *args, **kwargs):
                    return None
                def create_indexes(self, *args, **kwargs):
                    return None
                def list_indexes(self, *args, **kwargs):
                    return []
                def drop_index(self, *args, **kwargs):
                    return None
                def find(self, *args, **kwargs):
                    return []
            class NoOpDB:
                def __init__(self):
                    self._collections: Dict[str, NoOpCollection] = {}
                def __getitem__(self, name: str) -> NoOpCollection:
                    if name not in self._collections:
                        self._collections[name] = NoOpCollection()
                    return self._collections[name]
                def __getattr__(self, name: str) -> NoOpCollection:
                    # מאפשר גישה בסגנון נקודה: db.users, db.large_files, וכו'
                    if name.startswith('_'):
                        raise AttributeError(name)
                    return self.__getitem__(name)
                @property
                def name(self) -> str:
                    return "noop_db"

            self.client = None
            self.db = NoOpDB()
            self.collection = NoOpCollection()
            self.large_files_collection = NoOpCollection()
            self.backup_ratings_collection = NoOpCollection()
            emit_event("db_disabled", reason="docs_or_ci_mode")

        # אם pymongo לא מותקן (למשל בסביבת בדיקות קלה) — עבור למצב no-op
        if not _PYMONGO_AVAILABLE:
            _init_noop_collections()
            emit_event("db_disabled", reason="pymongo_not_available")
            return

        if disable_db:
            _init_noop_collections()
            return

        try:
            self.client = MongoClient(
                config.MONGODB_URL,
                maxPoolSize=50,
                minPoolSize=5,
                maxIdleTimeMS=30000,
                waitQueueTimeoutMS=5000,
                serverSelectionTimeoutMS=3000,
                socketTimeoutMS=20000,
                connectTimeoutMS=10000,
                retryWrites=True,
                retryReads=True,
                tz_aware=True,
                tzinfo=timezone.utc,
            )
            self.db = self.client[config.DATABASE_NAME]
            self.collection = self.db.code_snippets
            self.large_files_collection = self.db.large_files
            self.backup_ratings_collection = self.db.backup_ratings
            self.internal_shares_collection = self.db.internal_shares
            self.client.admin.command('ping')
            self._create_indexes()
            emit_event("db_connected", severity="info")
        except Exception as e:
            if disable_db:
                _init_noop_collections()
                emit_event("db_connection_fallback_noop", severity="warn", error=str(e))
                return
            emit_event("db_connection_failed", severity="error", error=str(e))
            raise

    # --- Lazy repository accessor to avoid circular imports ---
    def _get_repo(self):
        if self._repo is None:
            from .repository import Repository  # local import to avoid circular dependency
            self._repo = Repository(self)
        return self._repo

    def _create_indexes(self):
        indexes = [
            IndexModel([("user_id", ASCENDING)]),
            IndexModel([("file_name", ASCENDING)]),
            IndexModel([("programming_language", ASCENDING)]),
            IndexModel([("tags", ASCENDING)]),
            IndexModel([("created_at", DESCENDING)]),
            IndexModel([("user_id", ASCENDING), ("file_name", ASCENDING), ("version", DESCENDING)]),
            # אינדקס למועדפים: שליפה מהירה לפי משתמש ומועדפים, מיון לפי תאריך הוספה
            IndexModel([("user_id", ASCENDING), ("is_favorite", ASCENDING), ("favorited_at", DESCENDING)], name="user_favorites_idx"),
            # אינדקס משופר לתמיכה במיון file_name, version לאחר match על user_id,is_active
            IndexModel([
                ("user_id", ASCENDING),
                ("is_active", ASCENDING),
                ("file_name", ASCENDING),
                ("version", DESCENDING),
            ], name="user_active_file_latest_idx"),
            IndexModel([
                ("user_id", ASCENDING),
                ("programming_language", ASCENDING),
                ("created_at", DESCENDING),
            ], name="user_lang_date_idx"),
            IndexModel([
                ("user_id", ASCENDING),
                ("tags", ASCENDING),
                ("updated_at", DESCENDING),
            ], name="user_tags_updated_idx"),
            IndexModel([
                ("user_id", ASCENDING),
                ("is_active", ASCENDING),
                ("programming_language", ASCENDING),
            ], name="user_active_lang_idx"),
            IndexModel([
                ("user_id", ASCENDING),
                ("is_active", ASCENDING),
                ("updated_at", DESCENDING),
            ], name="user_active_recent_idx"),
            IndexModel([
                ("programming_language", ASCENDING),
                ("tags", ASCENDING),
                ("created_at", DESCENDING),
            ], name="lang_tags_date_idx"),
            IndexModel([("code", TEXT), ("description", TEXT), ("file_name", TEXT)], name="full_text_search_idx"),
            IndexModel([("deleted_expires_at", ASCENDING)], name="deleted_ttl", expireAfterSeconds=0),
        ]

        large_files_indexes = [
            IndexModel([("user_id", ASCENDING)]),
            IndexModel([("file_name", ASCENDING)]),
            IndexModel([("programming_language", ASCENDING)]),
            IndexModel([("created_at", DESCENDING)]),
            IndexModel([("file_size", ASCENDING)]),
            IndexModel([("lines_count", ASCENDING)]),
            IndexModel([("user_id", ASCENDING), ("file_name", ASCENDING)]),
            IndexModel([
                ("user_id", ASCENDING),
                ("programming_language", ASCENDING),
                ("file_size", ASCENDING),
            ], name="user_lang_size_idx"),
            IndexModel([
                ("user_id", ASCENDING),
                ("is_active", ASCENDING),
                ("created_at", DESCENDING),
            ], name="user_active_date_large_idx"),
            IndexModel([
                ("programming_language", ASCENDING),
                ("file_size", ASCENDING),
                ("lines_count", ASCENDING),
            ], name="lang_size_lines_idx"),
            IndexModel([
                ("user_id", ASCENDING),
                ("tags", ASCENDING),
                ("file_size", DESCENDING),
            ], name="user_tags_size_idx"),
            IndexModel([("deleted_expires_at", ASCENDING)], name="deleted_ttl", expireAfterSeconds=0),
        ]

        # users collection indexes
        users_indexes = [
            # כל משתמש מזוהה ע"י user_id – אינדקס ייחודי לביצועים ועקביות
            IndexModel([("user_id", ASCENDING)], name="user_id_unique", unique=True),
            # username ייחודי אם קיים (sparse/partial כדי לאפשר ערכים חסרים)
            IndexModel(
                [("username", ASCENDING)],
                name="username_unique",
                unique=True,
                sparse=True,
            ),
            # שימוש נפוץ לדוחות: מיון לפי פעילות אחרונה
            IndexModel([("last_activity", DESCENDING)], name="last_activity_desc"),
        ]

        # backup_ratings indexes
        backup_ratings_indexes = [
            IndexModel([("user_id", ASCENDING), ("backup_id", ASCENDING)], name="user_backup_unique", unique=True),
            IndexModel([("created_at", DESCENDING)], name="created_at_desc"),
        ]

        # metrics collection (service_metrics) TTL for automatic cleanup (e.g., 30 days)
        metrics_indexes = [
            IndexModel([("ts", DESCENDING)], name="ts_desc"),
            IndexModel([("ts", ASCENDING)], name="metrics_ttl", expireAfterSeconds=30 * 24 * 60 * 60),
        ]

        try:
            self.collection.create_indexes(indexes)
            self.large_files_collection.create_indexes(large_files_indexes)
            # users
            try:
                self.db.users.create_indexes(users_indexes)  # type: ignore[attr-defined]
            except Exception:
                # הגנה רכה בסביבות ללא users collection
                pass
            # metrics (best-effort if enabled)
            try:
                collection_name = getattr(config, 'METRICS_COLLECTION', 'service_metrics')
                self.db[collection_name].create_indexes(metrics_indexes)  # type: ignore[index]
            except Exception:
                pass
            if self.backup_ratings_collection is not None:
                self.backup_ratings_collection.create_indexes(backup_ratings_indexes)
            # אינדקסים לשיתופים פנימיים: TTL על expires_at + אינדקסים לשימוש
            if self.internal_shares_collection is not None:
                internal_shares_indexes = [
                    IndexModel([("share_id", ASCENDING)], name="share_id_unique", unique=True),
                    IndexModel([("created_at", DESCENDING)], name="created_at_desc"),
                    # TTL על expires_at (Date). אם יישמר כמחרוזת ISO, לא יעבוד — נוודא Date בצד הכותב
                    IndexModel([("expires_at", ASCENDING)], name="expires_ttl", expireAfterSeconds=0),
                ]
                self.internal_shares_collection.create_indexes(internal_shares_indexes)
        except Exception as e:
            msg = str(e)
            if 'IndexOptionsConflict' in msg or 'already exists with a different name' in msg:
                try:
                    existing = list(self.collection.list_indexes())
                    for idx in existing:
                        name = idx.get('name', '')
                        is_text_index = ('textIndexVersion' in idx) or name.endswith('_text')
                        if (
                            is_text_index or
                            name in {
                                'user_lang_date_idx',
                                'user_tags_updated_idx',
                                'user_active_lang_idx',
                                'user_active_recent_idx',
                                'lang_tags_date_idx',
                                'full_text_search_idx'
                            } or
                            name.startswith('user_id_') or name.startswith('file_name_')
                        ):
                            try:
                                self.collection.drop_index(name)
                            except Exception:
                                pass
                    try:
                        self.collection.drop_index([('code', 'text'), ('description', 'text'), ('file_name', 'text')])
                    except Exception:
                        pass
                    self.collection.create_indexes(indexes)
                    self.large_files_collection.create_indexes(large_files_indexes)
                    try:
                        self.db.users.create_indexes(users_indexes)  # type: ignore[attr-defined]
                    except Exception:
                        pass
                    try:
                        collection_name = getattr(config, 'METRICS_COLLECTION', 'service_metrics')
                        self.db[collection_name].create_indexes(metrics_indexes)  # type: ignore[index]
                    except Exception:
                        pass
                    if self.backup_ratings_collection is not None:
                        self.backup_ratings_collection.create_indexes(backup_ratings_indexes)
                except Exception as _e:
                    emit_event("db_indexes_conflict_update_failed", severity="warn", error=str(_e))
            else:
                emit_event("db_create_indexes_error", severity="warn", error=str(e))

        # עדכון מטריקה על מספר אינדקסים פעילים (best-effort)
        try:
            from metrics import active_indexes  # type: ignore
        except Exception:
            active_indexes = None  # type: ignore
        if active_indexes is not None:
            try:
                total = 0
                try:
                    total += len(list(self.collection.list_indexes()))
                except Exception:
                    pass
                try:
                    total += len(list(self.large_files_collection.list_indexes()))
                except Exception:
                    pass
                try:
                    total += len(list(self.db.users.list_indexes()))  # type: ignore[attr-defined]
                except Exception:
                    pass
                try:
                    if self.backup_ratings_collection is not None:
                        total += len(list(self.backup_ratings_collection.list_indexes()))
                except Exception:
                    pass
                try:
                    if self.internal_shares_collection is not None:
                        total += len(list(self.internal_shares_collection.list_indexes()))
                except Exception:
                    pass
                active_indexes.set(float(total))  # type: ignore[attr-defined]
            except Exception:
                pass

    def close(self):
        if self.client:
            self.client.close()

    def close_connection(self):
        self.close()

    # --- Backward-compatible CRUD API delegating to Repository ---
    # התאמות שמיות כדי להתאים לדוקס הישנים: שמרנו שמות מתודות היסטוריים
    # שממפות למימושים בפועל ב-Repository.

    # --- Aliases for "snippet" nomenclature ---
    def save_snippet(self, snippet) -> bool:
        return self._get_repo().save_code_snippet(snippet)

    def search_snippets(self, user_id: int, search_term: str = "", programming_language: Optional[str] = None, tags: Optional[List[str]] = None, limit: int = 20) -> List[Dict]:
        return self._get_repo().search_code(
            user_id,
            query=search_term,
            programming_language=programming_language,
            tags=tags,
            limit=limit,
        )

    def get_snippet(self, user_id: int, file_name: str) -> Optional[Dict]:
        return self._get_repo().get_file(user_id, file_name)

    def get_user_snippets(self, user_id: int, limit: int = 50) -> List[Dict]:
        return self._get_repo().get_user_files(user_id, limit)

    def delete_snippet(self, user_id: int, file_name: str) -> bool:
        return self._get_repo().delete_file(user_id, file_name)

    def delete_all_user_snippets(self, user_id: int) -> int:
        # מממש כמחיקה רכה של כל הקבצים הפעילים של המשתמש
        try:
            files = [doc.get('file_name') for doc in (self._get_repo().get_user_files(user_id, limit=1000) or []) if isinstance(doc, dict)]
            if not files:
                return 0
            return int(self._get_repo().soft_delete_files_by_names(user_id, files) or 0)
        except Exception:
            return 0

    def get_user_statistics(self, user_id: int) -> Dict[str, Any]:
        return self._get_repo().get_user_stats(user_id)

    def get_global_statistics(self) -> Dict[str, Any]:
        # מימוש בסיסי: אגרגציה גלובלית על כל הקבצים הפעילים
        try:
            pipeline = [
                {"$match": {"is_active": True}},
                {"$group": {
                    "_id": None,
                    "total_files": {"$sum": 1},
                    "languages": {"$addToSet": "$programming_language"},
                }},
            ]
            res = list(self.collection.aggregate(pipeline, allowDiskUse=True)) if self.collection else []
            if res:
                out = dict(res[0])
                out.pop('_id', None)
                return out
            return {"total_files": 0, "languages": []}
        except Exception:
            return {"total_files": 0, "languages": []}
    def save_code_snippet(self, snippet) -> bool:
        return self._get_repo().save_code_snippet(snippet)

    def save_file(self, user_id: int, file_name: str, code: str, programming_language: str, extra_tags: Optional[List[str]] = None) -> bool:
        return self._get_repo().save_file(user_id, file_name, code, programming_language, extra_tags)

    def get_latest_version(self, user_id: int, file_name: str) -> Optional[Dict]:
        return self._get_repo().get_latest_version(user_id, file_name)

    def get_file(self, user_id: int, file_name: str) -> Optional[Dict]:
        return self._get_repo().get_file(user_id, file_name)

    def get_all_versions(self, user_id: int, file_name: str) -> List[Dict]:
        return self._get_repo().get_all_versions(user_id, file_name)

    def get_version(self, user_id: int, file_name: str, version: int) -> Optional[Dict]:
        return self._get_repo().get_version(user_id, file_name, version)

    def get_user_files(self, user_id: int, limit: int = 50) -> List[Dict]:
        return self._get_repo().get_user_files(user_id, limit)

    def get_user_file_names(self, user_id: int, limit: int = 1000) -> List[str]:
        """עטיפה נוחה לשמות הקבצים הייחודיים של המשתמש (גרסה אחרונה לכל קובץ).

        משתמש ב־Repository למימוש בפועל.
        """
        return self._get_repo().get_user_file_names(user_id, limit)

    def search_code(self, user_id: int, query: str, programming_language: Optional[str] = None, tags: Optional[List[str]] = None, limit: int = 20) -> List[Dict]:
        return self._get_repo().search_code(user_id, query, programming_language, tags, limit)

    def get_user_files_by_repo(self, user_id: int, repo_tag: str, page: int = 1, per_page: int = 50) -> Tuple[List[Dict], int]:
        return self._get_repo().get_user_files_by_repo(user_id, repo_tag, page, per_page)

    # רשימת "שאר הקבצים" בעימוד אמיתי מה-DB (ללא repo:*)
    def get_regular_files_paginated(self, user_id: int, page: int = 1, per_page: int = 10) -> Tuple[List[Dict], int]:
        return self._get_repo().get_regular_files_paginated(user_id, page, per_page)

    # Repo tags helpers
    def get_repo_tags_with_counts(self, user_id: int, max_tags: int = 100) -> List[Dict]:
        return self._get_repo().get_repo_tags_with_counts(user_id, max_tags)

    def delete_file(self, user_id: int, file_name: str) -> bool:
        return self._get_repo().delete_file(user_id, file_name)

    def soft_delete_files_by_names(self, user_id: int, file_names: List[str]) -> int:
        return self._get_repo().soft_delete_files_by_names(user_id, file_names)

    def delete_file_by_id(self, file_id: str) -> bool:
        return self._get_repo().delete_file_by_id(file_id)

    def get_file_by_id(self, file_id: str) -> Optional[Dict]:
        return self._get_repo().get_file_by_id(file_id)

    def get_user_stats(self, user_id: int) -> Dict[str, Any]:
        return self._get_repo().get_user_stats(user_id)

    def rename_file(self, user_id: int, old_name: str, new_name: str) -> bool:
        return self._get_repo().rename_file(user_id, old_name, new_name)

    # Favorites API wrappers
    def toggle_favorite(self, user_id: int, file_name: str) -> Optional[bool]:
        return self._get_repo().toggle_favorite(user_id, file_name)

    def get_favorites(self, user_id: int, language: Optional[str] = None, sort_by: str = "date", limit: int = 50) -> List[Dict]:
        return self._get_repo().get_favorites(user_id, language=language, sort_by=sort_by, limit=limit)

    def get_favorites_count(self, user_id: int) -> int:
        return self._get_repo().get_favorites_count(user_id)

    def is_favorite(self, user_id: int, file_name: str) -> bool:
        return self._get_repo().is_favorite(user_id, file_name)

    # Large files API
    def save_large_file(self, large_file) -> bool:
        return self._get_repo().save_large_file(large_file)

    def get_large_file(self, user_id: int, file_name: str) -> Optional[Dict]:
        return self._get_repo().get_large_file(user_id, file_name)

    def get_large_file_by_id(self, file_id: str) -> Optional[Dict]:
        return self._get_repo().get_large_file_by_id(file_id)

    def get_user_large_files(self, user_id: int, page: int = 1, per_page: int = 8) -> Tuple[List[Dict], int]:
        return self._get_repo().get_user_large_files(user_id, page, per_page)

    def delete_large_file(self, user_id: int, file_name: str) -> bool:
        return self._get_repo().delete_large_file(user_id, file_name)

    def delete_large_file_by_id(self, file_id: str) -> bool:
        return self._get_repo().delete_large_file_by_id(file_id)

    def get_all_user_files_combined(self, user_id: int) -> Dict[str, List[Dict]]:
        return self._get_repo().get_all_user_files_combined(user_id)

    # Backup ratings API
    def save_backup_rating(self, user_id: int, backup_id: str, rating: str) -> bool:
        return self._get_repo().save_backup_rating(user_id, backup_id, rating)

    def get_backup_rating(self, user_id: int, backup_id: str) -> Optional[str]:
        return self._get_repo().get_backup_rating(user_id, backup_id)

    def delete_backup_ratings(self, user_id: int, backup_ids: List[str]) -> int:
        return self._get_repo().delete_backup_ratings(user_id, backup_ids)

    # Backup notes API (מאוחסן יחד עם דירוגים באותה קולקציה)
    def save_backup_note(self, user_id: int, backup_id: str, note: str) -> bool:
        return self._get_repo().save_backup_note(user_id, backup_id, note)

    def get_backup_note(self, user_id: int, backup_id: str) -> Optional[str]:
        return self._get_repo().get_backup_note(user_id, backup_id)

    # Users and tokens
    def save_github_token(self, user_id: int, token: str) -> bool:
        return self._get_repo().save_github_token(user_id, token)

    def get_github_token(self, user_id: int) -> Optional[str]:
        return self._get_repo().get_github_token(user_id)

    def delete_github_token(self, user_id: int) -> bool:
        return self._get_repo().delete_github_token(user_id)

    def save_selected_repo(self, user_id: int, repo_name: str) -> bool:
        return self._get_repo().save_selected_repo(user_id, repo_name)

    def get_selected_repo(self, user_id: int) -> Optional[str]:
        return self._get_repo().get_selected_repo(user_id)

    def save_user(self, user_id: int, username: Optional[str] = None) -> bool:
        return self._get_repo().save_user(user_id, username)

    # Google Drive tokens & preferences
    def save_drive_tokens(self, user_id: int, token_data: Dict[str, Any]) -> bool:
        return self._get_repo().save_drive_tokens(user_id, token_data)

    def get_drive_tokens(self, user_id: int) -> Optional[Dict[str, Any]]:
        return self._get_repo().get_drive_tokens(user_id)

    def delete_drive_tokens(self, user_id: int) -> bool:
        return self._get_repo().delete_drive_tokens(user_id)

    def save_drive_prefs(self, user_id: int, prefs: Dict[str, Any]) -> bool:
        return self._get_repo().save_drive_prefs(user_id, prefs)

    def get_drive_prefs(self, user_id: int) -> Optional[Dict[str, Any]]:
        return self._get_repo().get_drive_prefs(user_id)

