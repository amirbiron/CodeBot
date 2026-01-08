import asyncio
import logging
import os
from types import SimpleNamespace
from datetime import timezone
from typing import Any, Callable, Dict, List, Optional, Tuple, Protocol

try:
    from pymongo import MongoClient, IndexModel, ASCENDING, DESCENDING, TEXT
    from pymongo import monitoring as _pymongo_monitoring
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
_MONGO_MONITORING_REGISTERED = False


class DatabaseManager:
    """אחראי על חיבור MongoDB והגדרת אינדקסים."""

    client: Optional[Any]
    db: Optional[DBLike]
    collection: CollectionLike
    large_files_collection: CollectionLike
    backup_ratings_collection: Optional[CollectionLike]
    internal_shares_collection: Optional[CollectionLike]
    community_library_collection: Optional[CollectionLike]
    snippets_collection: Optional[CollectionLike]
    shared_themes_collection: Optional[CollectionLike]
    _repo: Optional[Any]

    def __init__(self):
        self.client = None
        self.db = None
        # תאימות לשכבות שמצפות ל-db_name (למשל JobTracker במדריכים)
        self.db_name = ""
        # אתחול לאובייקטים שאינם None כדי לעמוד בטייפים
        self.collection = _StubCollection()
        self.large_files_collection = _StubCollection()
        self.backup_ratings_collection = _StubCollection()
        self.internal_shares_collection = _StubCollection()
        self.community_library_collection = _StubCollection()
        self.snippets_collection = _StubCollection()
        self.shared_themes_collection = _StubCollection()
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
            try:
                self.db_name = str(getattr(self.db, "name", "") or "noop_db")
            except Exception:
                self.db_name = "noop_db"
            self.collection = NoOpCollection()
            self.large_files_collection = NoOpCollection()
            self.backup_ratings_collection = NoOpCollection()
            self.community_library_collection = NoOpCollection()
            self.snippets_collection = NoOpCollection()
            self.shared_themes_collection = NoOpCollection()
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
            # Register slow command listener once (best-effort)
            global _MONGO_MONITORING_REGISTERED
            if not _MONGO_MONITORING_REGISTERED:
                try:
                    outer_self = self

                    def _profiler_enabled() -> bool:
                        try:
                            v = os.getenv("PROFILER_ENABLED", "true")
                            return str(v).strip().lower() in {"1", "true", "yes", "y", "on"}
                        except Exception:
                            return True

                    def _profiler_threshold_ms() -> float:
                        # PROFILER_SLOW_THRESHOLD_MS controls recording into the profiler.
                        # It should NOT control slow_mongo log emission (that is controlled by DB_SLOW_MS).
                        raw = os.getenv("PROFILER_SLOW_THRESHOLD_MS", "").strip()
                        if raw:
                            try:
                                return float(raw)
                            except Exception:
                                return 100.0
                        # Backward-compat: if profiler threshold isn't set but legacy DB_SLOW_MS is set (>0),
                        # use it as a reasonable profiler threshold.
                        raw2 = os.getenv("DB_SLOW_MS", "").strip()
                        if raw2:
                            try:
                                v = float(raw2)
                                if v > 0:
                                    return v
                            except Exception:
                                pass
                        # ברירת מחדל: 100ms (תואם docs ו-Config Inspector)
                        return 100.0

                    def _slow_mongo_log_threshold_ms() -> float:
                        # DB_SLOW_MS controls the slow_mongo warning log.
                        # Docs/Config Inspector define default as 0 (disabled).
                        raw = os.getenv("DB_SLOW_MS", "").strip()
                        if not raw:
                            return 0.0
                        try:
                            return float(raw)
                        except Exception:
                            return 0.0

                    def _get_profiler_service():
                        # Lazy import to avoid hard dependency / circular imports at startup
                        try:
                            from services.query_profiler_service import PersistentQueryProfilerService  # type: ignore
                        except Exception:
                            return None
                        svc = getattr(outer_self, "_profiler_service", None)
                        if svc is not None:
                            return svc
                        try:
                            svc = PersistentQueryProfilerService(
                                db_manager=outer_self,
                                slow_threshold_ms=int(_profiler_threshold_ms() or 100),
                            )
                            setattr(outer_self, "_profiler_service", svc)
                            return svc
                        except Exception:
                            return None

                    def _extract_collection_and_query(command_name: str, command: Dict[str, Any]) -> tuple[str, Dict[str, Any]]:
                        cmd = command or {}
                        coll = ""
                        query: Dict[str, Any] = {}

                        try:
                            if command_name in {"find", "aggregate", "count", "distinct"}:
                                coll = str(cmd.get(command_name) or "")
                            elif command_name in {"insert", "update", "delete", "findAndModify"}:
                                # These commands store collection name under the command key
                                coll = str(cmd.get(command_name) or "")
                        except Exception:
                            coll = ""

                        try:
                            if command_name == "find":
                                query = cmd.get("filter") or cmd.get("query") or {}
                            elif command_name == "aggregate":
                                pipeline = cmd.get("pipeline")
                                query = {"pipeline": pipeline} if isinstance(pipeline, list) else {}
                            elif command_name == "update":
                                updates = cmd.get("updates") or []
                                if isinstance(updates, list) and updates:
                                    first = updates[0] if isinstance(updates[0], dict) else {}
                                    query = first.get("q") or {}
                            elif command_name == "delete":
                                deletes = cmd.get("deletes") or []
                                if isinstance(deletes, list) and deletes:
                                    first = deletes[0] if isinstance(deletes[0], dict) else {}
                                    query = first.get("q") or {}
                            elif command_name == "findAndModify":
                                query = cmd.get("query") or {}
                        except Exception:
                            query = {}

                        if not isinstance(query, dict):
                            query = {"raw": str(query)}
                        return coll, query

                    class _SlowMongoListener(_pymongo_monitoring.CommandListener):  # type: ignore[attr-defined]
                        def __init__(self):
                            # שומר הקשר בין התחלת בקשה לסיומה
                            self._requests = {}

                        def started(self, event):  # type: ignore[override]
                            try:
                                request_id = getattr(event, "request_id", None)
                                if request_id is None:
                                    return

                                cmd_name = str(getattr(event, "command_name", "") or "")
                                if cmd_name.lower() == "explain":
                                    return

                                command = getattr(event, "command", None) or {}
                                if not isinstance(command, dict):
                                    return

                                # חילוץ המידע כבר בהתחלה - כשהוא זמין
                                coll, query = _extract_collection_and_query(cmd_name, command)

                                # שמירה בהקשר הבקשה
                                if coll:
                                    self._requests[request_id] = {
                                        "coll": coll,
                                        "query": query,
                                        "cmd_name": cmd_name,
                                        "db": str(getattr(event, "database_name", "") or ""),
                                    }
                            except Exception:
                                pass

                        def succeeded(self, event):  # type: ignore[override]
                            # שליפת הקשר הבקשה
                            request_id = getattr(event, "request_id", None)
                            req_data = self._requests.pop(request_id, None) if request_id is not None else None

                            try:
                                dur_ms = float(getattr(event, 'duration_micros', 0) or 0) / 1000.0
                                # --- slow_mongo warning log (controlled by DB_SLOW_MS) ---
                                slow_log_ms = float(_slow_mongo_log_threshold_ms() or 0.0)
                                if slow_log_ms and dur_ms > slow_log_ms:
                                    try:
                                        logger.warning(
                                            'slow_mongo',
                                            extra={
                                                'cmd': getattr(event, 'command_name', ''),
                                                'db': getattr(event, 'database_name', ''),
                                                'ms': round(dur_ms, 1),
                                            },
                                        )
                                    except Exception:
                                        pass

                                # --- Query Performance Profiler (independent of DB_SLOW_MS) ---
                                try:
                                    if not _profiler_enabled():
                                        return

                                    profiler_slow_ms = float(_profiler_threshold_ms() or 0.0)
                                    if profiler_slow_ms and dur_ms <= profiler_slow_ms:
                                        return

                                    # אם אין לנו את המידע מ-started, אי אפשר להקליט
                                    if not req_data:
                                        return

                                    coll = req_data["coll"]
                                    # מניעת רקורסיה
                                    if coll in {"slow_queries_log", "system.profile"}:
                                        return

                                    profiler = _get_profiler_service()
                                    if profiler is None:
                                        return

                                    client_info = {
                                        "db": req_data["db"],
                                        "cmd": req_data["cmd_name"],
                                    }

                                    # הרצה אסינכרונית
                                    try:
                                        loop = asyncio.get_running_loop()
                                    except RuntimeError:
                                        loop = None

                                    if loop is not None:
                                        loop.create_task(
                                            profiler.record_slow_query(
                                                collection=coll,
                                                operation=req_data["cmd_name"],
                                                query=req_data["query"],
                                                execution_time_ms=float(dur_ms),
                                                client_info=client_info,
                                            )
                                        )
                                    else:
                                        asyncio.run(
                                            profiler.record_slow_query(
                                                collection=coll,
                                                operation=req_data["cmd_name"],
                                                query=req_data["query"],
                                                execution_time_ms=float(dur_ms),
                                                client_info=client_info,
                                            )
                                        )
                                except Exception as e:
                                    # החזרת לוג שגיאה למקרה הצורך
                                    logger.error(f"Profiler Error: {str(e)}")
                            except Exception:
                                pass

                        def failed(self, event):  # type: ignore[override]
                            # ניקוי זיכרון במקרה של כישלון
                            request_id = getattr(event, "request_id", None)
                            if request_id is not None:
                                self._requests.pop(request_id, None)
                    _pymongo_monitoring.register(_SlowMongoListener())  # type: ignore[attr-defined]
                    _MONGO_MONITORING_REGISTERED = True
                except Exception:
                    pass
            # קריאת ערכים מה-ENV דרך config, עם ברירות מחדל שמרניות
            kwargs = dict(
                maxPoolSize=getattr(config, "MONGODB_MAX_POOL_SIZE", 50),
                minPoolSize=getattr(config, "MONGODB_MIN_POOL_SIZE", 5),
                maxIdleTimeMS=getattr(config, "MONGODB_MAX_IDLE_TIME_MS", 30_000),
                waitQueueTimeoutMS=getattr(config, "MONGODB_WAIT_QUEUE_TIMEOUT_MS", 5_000),
                serverSelectionTimeoutMS=getattr(config, "MONGODB_SERVER_SELECTION_TIMEOUT_MS", 3_000),
                socketTimeoutMS=getattr(config, "MONGODB_SOCKET_TIMEOUT_MS", 20_000),
                connectTimeoutMS=getattr(config, "MONGODB_CONNECT_TIMEOUT_MS", 10_000),
                retryWrites=getattr(config, "MONGODB_RETRY_WRITES", True),
                retryReads=getattr(config, "MONGODB_RETRY_READS", True),
                tz_aware=True,
                tzinfo=timezone.utc,
            )
            # אפשר appName אם ניתן
            appname = getattr(config, "MONGODB_APPNAME", None)
            if appname:
                kwargs["appname"] = appname

            # דחיסה (compressors) — רשימת קומפרסורים מופרדת בפסיקים
            try:
                compressors_raw = (
                    getattr(config, "MONGODB_COMPRESSORS", None)
                    or os.getenv("MONGODB_COMPRESSORS", "")
                )
                if compressors_raw:
                    compressors_list = [c.strip() for c in str(compressors_raw).split(",") if c and str(c).strip()]
                    if compressors_list:
                        kwargs["compressors"] = compressors_list
            except Exception:
                pass

            # heartbeatFrequencyMS — תדירות דופק השרת
            try:
                hb = int(getattr(config, "MONGODB_HEARTBEAT_FREQUENCY_MS", 10_000))
                if hb and hb > 0:
                    kwargs["heartbeatFrequencyMS"] = hb
            except Exception:
                pass

            mongo_url = getattr(config, "MONGODB_URL", None) or os.getenv("MONGODB_URL")
            if not mongo_url:
                raise RuntimeError("MONGODB_URL is not configured")

            database_name = getattr(config, "DATABASE_NAME", None) or os.getenv("DATABASE_NAME", "code_keeper_bot")
            try:
                self.db_name = str(database_name or "")
            except Exception:
                self.db_name = ""

            self.client = MongoClient(
                mongo_url,
                **kwargs,
            )
            self.db = self.client[database_name]
            self.collection = self.db.code_snippets
            self.large_files_collection = self.db.large_files
            self.backup_ratings_collection = self.db.backup_ratings
            self.internal_shares_collection = self.db.internal_shares
            # Shared Themes public catalog
            try:
                self.shared_themes_collection = self.db.shared_themes
            except Exception:
                self.shared_themes_collection = None
            # Community Library public catalog
            try:
                self.community_library_collection = self.db.community_library_items
            except Exception:
                self.community_library_collection = None
            # Snippets library collection
            try:
                self.snippets_collection = self.db.snippets
            except Exception:
                self.snippets_collection = None
            self.client.admin.command('ping')
            # יצירת אינדקסים קריטיים (בנייה ברקע) לשיפור ביצועים ולמניעת COLLSCAN
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

    def safe_create_index(
        self,
        collection_name: str,
        keys: List[Tuple[str, int]],
        *,
        name: Optional[str] = None,
        unique: bool = False,
        background: bool = True,
        enforce: bool = False,
        partial_filter_expression: Optional[Dict[str, Any]] = None,
    ) -> None:
        """יוצר אינדקס בצורה בטוחה וב-Background.

        מטרות:
        - להימנע מקריסה אם קיים אינדקס *זהה* עם שם אחר (IndexOptionsConflict / "already exists")
        - לא להסתיר תקלות אמיתיות (חיבור/הרשאות/duplicate keys וכו')
        - לאפשר "אכיפה" (drop+create) רק לאינדקסים קריטיים כשיש mismatch אמיתי

        Args:
            partial_filter_expression: אופציונלי - תנאי סינון לאינדקס חלקי (Partial Index).
                                       מאפשר לאנדקס רק חלק מהמסמכים לפי פילטר.
        """
        db = getattr(self, "db", None)
        if db is None:
            return

        try:
            collection = db[collection_name]
        except Exception as e:
            emit_event(
                "db_create_index_error",
                severity="warn",
                collection=collection_name,
                index_name=name or "",
                error=f"failed_to_get_collection: {e}",
            )
            return

        # ולידציה מקדימה של keys כדי לא לקרוס על int(v)
        desired_keys: List[Tuple[str, int]] = []
        invalid_count = 0
        for k, v in (keys or []):
            if k is None:
                continue
            try:
                direction = int(v)
            except (TypeError, ValueError):
                invalid_count += 1
                continue
            desired_keys.append((str(k), direction))

        if not desired_keys:
            emit_event(
                "db_create_index_skipped",
                severity="warn",
                collection=collection_name,
                index_name=name or "",
                reason="no_valid_keys",
                invalid_keys_count=invalid_count,
            )
            return

        if invalid_count:
            emit_event(
                "db_create_index_invalid_keys",
                severity="warn",
                collection=collection_name,
                index_name=name or "",
                invalid_keys_count=invalid_count,
            )

        def _existing_indexes() -> List[Dict[str, Any]]:
            try:
                out = list(collection.list_indexes())
                return [idx for idx in out if isinstance(idx, dict)]
            except Exception:
                return []

        def _index_matches(idx: Dict[str, Any]) -> bool:
            try:
                key_doc = idx.get("key", {})
                if isinstance(key_doc, dict):
                    existing_keys = [(str(k), int(v)) for k, v in list(key_doc.items())]
                else:
                    return False

                if existing_keys != desired_keys:
                    return False

                # unique הוא אופציה קריטית (אם אנחנו מבקשים unique חייב להיות unique)
                existing_unique = bool(idx.get("unique", False))
                if bool(unique) != existing_unique:
                    return False

                return True
            except Exception:
                return False

        try:
            index_kwargs: Dict[str, Any] = {
                "name": name,
                "unique": unique,
                "background": background,
            }
            if partial_filter_expression:
                index_kwargs["partialFilterExpression"] = partial_filter_expression
            collection.create_index(desired_keys, **index_kwargs)
            emit_event(
                "db_index_created",
                severity="info",
                collection=collection_name,
                index_name=name or "",
            )
            return
        except Exception as e:
            # ננסה לזהות "קונפליקט אופציות/שם" בצורה מדויקת, בלי לתפוס כל חריגה כ"הכל בסדר"
            code = getattr(e, "code", None)
            msg = str(e or "")
            msg_l = msg.lower()

            is_conflict = bool(
                code in {85, 86}
                or "indexoptionsconflict" in msg_l
                or "indexkeyspecsconflict" in msg_l
                or "already exists" in msg_l
            )

            if is_conflict:
                # אם כבר קיים אינדקס זהה (גם אם בשם אחר) — נחשב הצלחה ונמשיך
                for idx in _existing_indexes():
                    if _index_matches(idx):
                        emit_event(
                            "db_index_exists",
                            severity="info",
                            collection=collection_name,
                            index_name=str(idx.get("name", "")),
                        )
                        return

                # mismatch אמיתי: לאינדקסים קריטיים ננסה לאכוף drop+create לפי השם
                if enforce and name:
                    try:
                        collection.drop_index(name)
                        emit_event(
                            "db_index_dropped",
                            severity="warn",
                            collection=collection_name,
                            index_name=name,
                            reason="enforce_recreate_on_conflict",
                        )
                    except Exception as drop_e:
                        emit_event(
                            "db_drop_index_error",
                            severity="warn",
                            collection=collection_name,
                            index_name=name,
                            error=str(drop_e),
                        )

                    try:
                        recreate_kwargs: Dict[str, Any] = {
                            "name": name,
                            "unique": unique,
                            "background": background,
                        }
                        if partial_filter_expression:
                            recreate_kwargs["partialFilterExpression"] = partial_filter_expression
                        collection.create_index(desired_keys, **recreate_kwargs)
                        emit_event(
                            "db_index_created",
                            severity="info",
                            collection=collection_name,
                            index_name=name,
                        )
                        return
                    except Exception as e2:
                        emit_event(
                            "db_create_index_error",
                            severity="error",
                            collection=collection_name,
                            index_name=name,
                            error=str(e2),
                        )
                        return

                emit_event(
                    "db_create_index_conflict",
                    severity="warn",
                    collection=collection_name,
                    index_name=name or "",
                    error=msg,
                )
                return

            emit_event(
                "db_create_index_error",
                severity="warn",
                collection=collection_name,
                index_name=name or "",
                error=msg,
            )

    def _create_indexes(self):
        """צור *רק* את האינדקסים הקריטיים (ברקע) למניעת COLLSCAN.

        דרישה: להימנע מיצירת אינדקסים נוספים מעבר לרשימה האופטימלית שהוגדרה.
        """
        db = getattr(self, "db", None)

        if db is None:
            return

        # תאימות לטסטים: יש בדיקות שקוראות ל-DatabaseManager._create_indexes(self_like)
        # עם אובייקט דמה (למשל SimpleNamespace) שאין עליו safe_create_index.
        safe_create_index = getattr(self, "safe_create_index", None)
        if not callable(safe_create_index):
            def safe_create_index(*args: Any, **kwargs: Any) -> None:
                return DatabaseManager.safe_create_index(self, *args, **kwargs)

        # תיקון השגיאה ב-users: לא מבצעים בדיקה בוליאנית על Collection (PyMongo זורק חריגה)
        # note_reminders - אינדקס מותאם לשאילתת הפולינג החדשה
        # השאילתה מסננת לפי: ack_at=null, status in [pending, snoozed], remind_at <= now, needs_push != false
        # אינדקס חלקי (Partial Index) על ack_at=null ו-needs_push != false
        safe_create_index(
            "note_reminders",
            [("status", ASCENDING), ("remind_at", ASCENDING), ("needs_push", ASCENDING)],
            name="push_polling_optimized_idx",
            background=True,
            enforce=True,
            partial_filter_expression={"ack_at": None, "needs_push": {"$ne": False}},
        )
        # אינדקס חלקי פשוט יותר לתאימות
        safe_create_index(
            "note_reminders",
            [("status", ASCENDING), ("remind_at", ASCENDING)],
            name="push_polling_partial_idx",
            background=True,
            enforce=False,
            partial_filter_expression={"ack_at": None},
        )
        # אינדקס ישן לתאימות לאחור (לא חלקי)
        safe_create_index(
            "note_reminders",
            [("status", ASCENDING), ("remind_at", ASCENDING), ("last_push_success_at", ASCENDING)],
            name="push_polling_idx",
            background=True,
            enforce=False,  # לא לאכוף - אם קיים, לא למחוק
        )

        # service_metrics
        safe_create_index(
            "service_metrics",
            [("ts", DESCENDING), ("type", ASCENDING)],
            name="metrics_type_ts",
        )

        # job_runs
        safe_create_index(
            "job_runs",
            [("run_id", ASCENDING)],
            name="run_id_unique",
            unique=True,
        )

        # job_trigger_requests - אינדקס על status למניעת COLLSCAN בזמן polling
        safe_create_index(
            "job_trigger_requests",
            [("status", ASCENDING)],
            name="status_idx",
        )

        # announcements - אינדקס על is_active כדי למנוע COLLSCAN במסכים ציבוריים/אדמין
        safe_create_index(
            "announcements",
            [("is_active", ASCENDING)],
            name="announcements_is_active_idx",
        )

        # file_bookmarks - אינדקס משולב user_id+file_id לצמצום חיפושים לפי משתמש+קובץ
        safe_create_index(
            "file_bookmarks",
            [("user_id", ASCENDING), ("file_id", ASCENDING)],
            name="file_bookmarks_user_file_idx",
        )

        # recent_opens - אינדקס משולב user_id+file_name לשליפה מהירה של "נפתח לאחרונה"
        safe_create_index(
            "recent_opens",
            [("user_id", ASCENDING), ("file_name", ASCENDING)],
            name="recent_opens_user_file_name_idx",
        )

        # sticky_notes - שני אינדקסים: לפי user_id+_id ולפי file_id
        safe_create_index(
            "sticky_notes",
            [("user_id", ASCENDING), ("_id", ASCENDING)],
            name="sticky_notes_user_id_id_idx",
        )
        safe_create_index(
            "sticky_notes",
            [("file_id", ASCENDING)],
            name="sticky_notes_file_id_idx",
        )

        # markdown_images - אינדקס משולב snippet_id+user_id
        safe_create_index(
            "markdown_images",
            [("snippet_id", ASCENDING), ("user_id", ASCENDING)],
            name="markdown_images_snippet_user_idx",
        )

        # users
        safe_create_index(
            "users",
            [("drive_prefs.schedule", ASCENDING)],
            name="users_drive_schedule",
        )
        safe_create_index(
            "users",
            [("user_id", ASCENDING)],
            name="user_id_unique",
            unique=True,
        )

        # shared_themes - ערכות נושא ציבוריות
        safe_create_index("shared_themes", [("is_active", ASCENDING)], name="shared_themes_is_active_idx")
        safe_create_index("shared_themes", [("created_at", DESCENDING)], name="shared_themes_created_at_desc_idx")
        safe_create_index("shared_themes", [("created_by", ASCENDING)], name="shared_themes_created_by_idx")

        # הוספת אינדקסים קטנים שחונקים CPU (לפי התדירות/סינונים)
        safe_create_index("visual_rules", [("enabled", ASCENDING)], name="visual_rules_enabled_idx")
        safe_create_index(
            "alerts_silences",
            [("active", ASCENDING), ("until_ts", ASCENDING)],
            name="alerts_silences_active_until_idx",
        )
        safe_create_index("alerts_log", [("_key", ASCENDING)], name="alerts_log_key_idx")
        safe_create_index("alert_types_catalog", [("alert_type", ASCENDING)], name="alert_types_catalog_type_idx")

        # code_snippets - אינדקס מורכב לרשימות משתמש (משפר פילטר user_id+is_active ומיון לפי created_at)
        # אינדקס קריטי: אם יש mismatch אמיתי בשם הזה, ננסה drop+create בצורה מבוקרת.
        safe_create_index(
            "code_snippets",
            [("user_id", ASCENDING), ("is_active", ASCENDING), ("created_at", DESCENDING)],
            name="user_active_created_at_idx",
            enforce=True,
        )

        # code_snippets - אינדקס TEXT לחיפוש גלובלי ($text)
        # חשוב: זה אינדקס "כבד" כי הוא כולל גם code, אבל הוא קריטי כדי ש-$text יעבוד מהר
        # (ובמקום ליפול ל-$regex שמעמיס יותר).
        try:
            code_snippets = db.code_snippets
            code_snippets.create_indexes(
                [
                    IndexModel(
                        [("file_name", TEXT), ("description", TEXT), ("tags", TEXT), ("code", TEXT)],
                        name="search_text_idx",
                        background=True,
                    )
                ]
            )
            emit_event(
                "db_text_index_created",
                severity="info",
                collection="code_snippets",
                index_name="search_text_idx",
            )
        except Exception as e:
            msg = str(e or "")
            msg_l = msg.lower()
            code = getattr(e, "code", None)
            is_conflict = bool(
                code in {85, 86}
                or "indexoptionsconflict" in msg_l
                or "indexkeyspecsconflict" in msg_l
                or "already exists" in msg_l
            )
            if is_conflict:
                emit_event(
                    "db_text_index_exists",
                    severity="info",
                    collection="code_snippets",
                    index_name="search_text_idx",
                    error=msg,
                )
            else:
                emit_event(
                    "db_create_indexes_error",
                    severity="warn",
                    collection="code_snippets",
                    index_name="search_text_idx",
                    error=msg,
                )

        # Snippets library collection: שמירה על תאימות לטסטים/קוד שקיים.
        # לא מוסיפים אינדקסים נוספים מעבר לרשימה האופטימלית — כאן אנו רק מוודאים
        # קריאה ל-create_indexes באופן בטוח (האינדקס _id_ קיים תמיד).
        try:
            snippets_coll = getattr(self, "snippets_collection", None)
            if snippets_coll is not None:
                snippets_coll.create_indexes(
                    [
                        IndexModel(
                            [("_id", ASCENDING)],
                            name="_id_",
                            background=True,
                        )
                    ]
                )
        except Exception:
            # best-effort בלבד
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

    def get_user_files(
        self,
        user_id: int,
        limit: int = 50,
        *,
        skip: int = 0,
        projection: Optional[Dict[str, int]] = None,
    ) -> List[Dict]:
        return self._get_repo().get_user_files(user_id, limit, skip=skip, projection=projection)

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

    def save_selected_folder(self, user_id: int, folder_path: Optional[str]) -> bool:
        return self._get_repo().save_selected_folder(user_id, folder_path)

    def get_selected_folder(self, user_id: int) -> Optional[str]:
        return self._get_repo().get_selected_folder(user_id)

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

    def get_users_with_active_drive_schedule(self) -> List[Dict[str, Any]]:
        """Return all users who have an active drive backup schedule."""
        return self._get_repo().get_users_with_active_drive_schedule()

    # Image generation preferences (Telegram /image)
    def save_image_prefs(self, user_id: int, prefs: Dict[str, Any]) -> bool:
        return self._get_repo().save_image_prefs(user_id, prefs)

    def get_image_prefs(self, user_id: int) -> Optional[Dict[str, Any]]:
        return self._get_repo().get_image_prefs(user_id)

