import logging
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

try:
    from bson import ObjectId  # type: ignore
except Exception:
    class ObjectId(str):  # minimal stub for tests without bson
        pass

from cache_manager import cache, cached
from .manager import DatabaseManager
from utils import normalize_code
from config import config
from .models import CodeSnippet, LargeFile

logger = logging.getLogger(__name__)


class Repository:
    """CRUD נקי עבור אוספים במאגר הנתונים."""

    def __init__(self, manager: DatabaseManager):
        self.manager = manager

    def save_code_snippet(self, snippet: CodeSnippet) -> bool:
        try:
            # Normalize code before persisting
            try:
                if config.NORMALIZE_CODE_ON_SAVE:
                    snippet.code = normalize_code(snippet.code)
            except Exception:
                pass
            existing = self.get_latest_version(snippet.user_id, snippet.file_name)
            if existing:
                snippet.version = existing['version'] + 1
            snippet.updated_at = datetime.now(timezone.utc)
            result = self.manager.collection.insert_one(asdict(snippet))
            if result.inserted_id:
                cache.invalidate_user_cache(snippet.user_id)
                from autocomplete_manager import autocomplete
                autocomplete.invalidate_cache(snippet.user_id)
                return True
            return False
        except Exception as e:
            logger.error(f"שגיאה בשמירת קטע קוד: {e}")
            return False

    def save_file(self, user_id: int, file_name: str, code: str, programming_language: str, extra_tags: Optional[List[str]] = None) -> bool:
        # Preserve existing description and tags when creating a new version during edits
        try:
            existing = self.get_latest_version(user_id, file_name)
        except Exception:
            existing = None
        prev_description = ""
        prev_tags: List[str] = []
        if isinstance(existing, dict) and existing:
            try:
                prev_description = (existing.get('description') or "")
            except Exception:
                prev_description = ""
            try:
                prev_tags = list(existing.get('tags') or [])
            except Exception:
                prev_tags = []
        # Merge tags with special handling for repo:* —
        # keep exactly one repo tag: prefer the last from extra_tags if present, otherwise keep the existing one
        merged_tags: List[str] = []
        try:
            prev_list: List[str] = list(prev_tags or [])
            extra_list: List[str] = list(extra_tags or [])

            # Split previous tags
            prev_non_repo: List[str] = []
            prev_repo: List[str] = []
            for tag in prev_list:
                if not isinstance(tag, str):
                    continue
                ts = tag.strip()
                if not ts:
                    continue
                if ts.lower().startswith('repo:'):
                    prev_repo.append(ts)
                else:
                    if ts not in prev_non_repo:
                        prev_non_repo.append(ts)

            # Split extra tags
            extra_non_repo: List[str] = []
            extra_repo: List[str] = []
            for tag in extra_list:
                if not isinstance(tag, str):
                    continue
                ts = tag.strip()
                if not ts:
                    continue
                if ts.lower().startswith('repo:'):
                    extra_repo.append(ts)
                else:
                    if ts not in extra_non_repo:
                        extra_non_repo.append(ts)

            # Compose non-repo tags: previous + extra (deduplicated, order preserved)
            composed_non_repo: List[str] = []
            for ts in prev_non_repo + extra_non_repo:
                if ts not in composed_non_repo:
                    composed_non_repo.append(ts)

            # Choose repo tag: prefer extra last, else keep existing last
            chosen_repo = extra_repo[-1] if extra_repo else (prev_repo[-1] if prev_repo else None)
            merged_tags = composed_non_repo + ([chosen_repo] if chosen_repo else [])
        except Exception:
            # Fallback: keep previous tags as-is on error
            try:
                merged_tags = list(prev_tags or [])
            except Exception:
                merged_tags = []
        # Normalize code before constructing snippet
        try:
            if config.NORMALIZE_CODE_ON_SAVE:
                code = normalize_code(code)
        except Exception:
            pass
        snippet = CodeSnippet(
            user_id=user_id,
            file_name=file_name,
            code=code,
            programming_language=programming_language,
            description=prev_description,
            tags=merged_tags,
        )
        return self.save_code_snippet(snippet)

    @cached(expire_seconds=180, key_prefix="latest_version")
    def get_latest_version(self, user_id: int, file_name: str) -> Optional[Dict]:
        try:
            return self.manager.collection.find_one(
                {"user_id": user_id, "file_name": file_name, "is_active": True},
                sort=[("version", -1)],
            )
        except Exception as e:
            logger.error(f"שגיאה בקבלת גרסה אחרונה: {e}")
            return None

    def get_file(self, user_id: int, file_name: str) -> Optional[Dict]:
        try:
            return self.manager.collection.find_one(
                {"user_id": user_id, "file_name": file_name, "is_active": True},
                sort=[("version", -1)],
            )
        except Exception as e:
            logger.error(f"שגיאה בקבלת קובץ: {e}")
            return None

    def get_all_versions(self, user_id: int, file_name: str) -> List[Dict]:
        try:
            return list(self.manager.collection.find(
                {"user_id": user_id, "file_name": file_name, "is_active": True},
                sort=[("version", -1)],
            ))
        except Exception as e:
            logger.error(f"שגיאה בקבלת כל הגרסאות: {e}")
            return []

    def get_version(self, user_id: int, file_name: str, version: int) -> Optional[Dict]:
        try:
            return self.manager.collection.find_one(
                {"user_id": user_id, "file_name": file_name, "version": version, "is_active": True}
            )
        except Exception as e:
            logger.error(f"שגיאה בקבלת גרסה {version} עבור {file_name}: {e}")
            return None

    @cached(expire_seconds=120, key_prefix="user_files")
    def get_user_files(self, user_id: int, limit: int = 50) -> List[Dict]:
        try:
            pipeline = [
                {"$match": {"user_id": user_id, "is_active": True}},
                {"$sort": {"file_name": 1, "version": -1}},
                {"$group": {"_id": "$file_name", "latest": {"$first": "$$ROOT"}}},
                {"$replaceRoot": {"newRoot": "$latest"}},
                {"$sort": {"updated_at": -1}},
                {"$limit": limit},
            ]
            return list(self.manager.collection.aggregate(pipeline, allowDiskUse=True))
        except Exception as e:
            logger.error(f"שגיאה בקבלת קבצי משתמש: {e}")
            return []

    @cached(expire_seconds=300, key_prefix="search_code")
    def search_code(self, user_id: int, query: str, programming_language: str = None, tags: List[str] = None, limit: int = 20) -> List[Dict]:
        try:
            search_filter: Dict[str, Any] = {"user_id": user_id, "is_active": True}
            if query:
                search_filter["$text"] = {"$search": query}
            if programming_language:
                search_filter["programming_language"] = programming_language
            if tags:
                search_filter["tags"] = {"$in": tags}
            pipeline = [
                {"$match": search_filter},
                {"$sort": {"file_name": 1, "version": -1}},
                {"$group": {"_id": "$file_name", "latest": {"$first": "$$ROOT"}}},
                {"$replaceRoot": {"newRoot": "$latest"}},
                {"$sort": {"updated_at": -1}},
                {"$limit": limit},
            ]
            return list(self.manager.collection.aggregate(pipeline, allowDiskUse=True))
        except Exception as e:
            logger.error(f"שגיאה בחיפוש קוד: {e}")
            return []

    def get_user_files_by_repo(self, user_id: int, repo_tag: str, page: int = 1, per_page: int = 50) -> Tuple[List[Dict], int]:
        """מחזיר קבצים לפי תגית ריפו עם דפדוף, וכן ספירת סה"כ קבצים (distinct לפי file_name)."""
        try:
            skip = max(0, (page - 1) * per_page)
            match_stage = {"user_id": user_id, "is_active": True, "tags": repo_tag}

            # שלוף פריטים בעמוד
            items_pipeline = [
                {"$match": match_stage},
                {"$sort": {"file_name": 1, "version": -1}},
                {"$group": {"_id": "$file_name", "latest": {"$first": "$$ROOT"}}},
                {"$replaceRoot": {"newRoot": "$latest"}},
                {"$sort": {"updated_at": -1}},
                {"$skip": skip},
                {"$limit": per_page},
            ]
            items = list(self.manager.collection.aggregate(items_pipeline, allowDiskUse=True))

            # ספירת סה"כ (distinct שמות קבצים)
            count_pipeline = [
                {"$match": match_stage},
                {"$group": {"_id": "$file_name"}},
                {"$count": "count"},
            ]
            cnt_res = list(self.manager.collection.aggregate(count_pipeline, allowDiskUse=True))
            total = int((cnt_res[0]["count"]) if cnt_res else 0)
            return items, total
        except Exception as e:
            logger.error(f"שגיאה בקבלת קבצי ריפו: {e}")
            return [], 0

    def delete_file(self, user_id: int, file_name: str) -> bool:
        try:
            result = self.manager.collection.update_many(
                {"user_id": user_id, "file_name": file_name},
                {"$set": {"is_active": False, "updated_at": datetime.now(timezone.utc)}},
            )
            if result.modified_count > 0:
                cache.invalidate_user_cache(user_id)
                return True
            return False
        except Exception as e:
            logger.error(f"שגיאה במחיקת קובץ: {e}")
            return False

    def soft_delete_files_by_names(self, user_id: int, file_names: List[str]) -> int:
        """מחיקה רכה (is_active=false) למספר קבצים לפי שמות."""
        if not file_names:
            return 0
        try:
            result = self.manager.collection.update_many(
                {"user_id": user_id, "file_name": {"$in": list(set(file_names))}},
                {"$set": {"is_active": False, "updated_at": datetime.now(timezone.utc)}},
            )
            cache.invalidate_user_cache(user_id)
            return int(result.modified_count or 0)
        except Exception as e:
            logger.error(f"שגיאה במחיקה רכה מרובה: {e}")
            return 0

    def delete_file_by_id(self, file_id: str) -> int:
        try:
            result = self.manager.collection.delete_one({"_id": ObjectId(file_id)})
            return int(result.deleted_count or 0)
        except Exception as e:
            logger.error(f"שגיאה במחיקת קובץ לפי _id: {e}")
            return 0

    def get_file_by_id(self, file_id: str) -> Optional[Dict]:
        try:
            return self.manager.collection.find_one({"_id": ObjectId(file_id)})
        except Exception as e:
            logger.error(f"שגיאה בקבלת קובץ לפי _id: {e}")
            return None

    def get_user_stats(self, user_id: int) -> Dict[str, Any]:
        try:
            pipeline = [
                {"$match": {"user_id": user_id, "is_active": True}},
                {"$group": {
                    "_id": "$file_name",
                    "versions": {"$sum": 1},
                    "programming_language": {"$first": "$programming_language"},
                    "latest_update": {"$max": "$updated_at"},
                }},
                {"$group": {
                    "_id": None,
                    "total_files": {"$sum": 1},
                    "total_versions": {"$sum": "$versions"},
                    "languages": {"$addToSet": "$programming_language"},
                    "latest_activity": {"$max": "$latest_update"},
                }},
            ]
            result = list(self.manager.collection.aggregate(pipeline, allowDiskUse=True))
            if result:
                stats = result[0]
                stats.pop('_id', None)
                return stats
            return {"total_files": 0, "total_versions": 0, "languages": [], "latest_activity": None}
        except Exception as e:
            logger.error(f"שגיאה בקבלת סטטיסטיקות: {e}")
            return {}

    def rename_file(self, user_id: int, old_name: str, new_name: str) -> bool:
        try:
            existing = self.get_latest_version(user_id, new_name)
            if existing and new_name != old_name:
                logger.warning(f"File {new_name} already exists for user {user_id}")
                return False
            result = self.manager.collection.update_many(
                {"user_id": user_id, "file_name": old_name, "is_active": True},
                {"$set": {"file_name": new_name, "updated_at": datetime.now(timezone.utc)}},
            )
            return bool(result.modified_count and result.modified_count > 0)
        except Exception as e:
            logger.error(f"Error renaming file {old_name} to {new_name} for user {user_id}: {e}")
            return False

    # Large files operations
    def save_large_file(self, large_file: LargeFile) -> bool:
        try:
            # Normalize content before persist
            try:
                if config.NORMALIZE_CODE_ON_SAVE:
                    large_file.content = normalize_code(large_file.content)
            except Exception:
                pass
            existing = self.get_large_file(large_file.user_id, large_file.file_name)
            if existing:
                self.delete_large_file(large_file.user_id, large_file.file_name)
            result = self.manager.large_files_collection.insert_one(asdict(large_file))
            return bool(result.inserted_id)
        except Exception as e:
            logger.error(f"שגיאה בשמירת קובץ גדול: {e}")
            return False

    def get_large_file(self, user_id: int, file_name: str) -> Optional[Dict]:
        try:
            return self.manager.large_files_collection.find_one(
                {"user_id": user_id, "file_name": file_name, "is_active": True}
            )
        except Exception as e:
            logger.error(f"שגיאה בקבלת קובץ גדול: {e}")
            return None

    def get_large_file_by_id(self, file_id: str) -> Optional[Dict]:
        try:
            return self.manager.large_files_collection.find_one({"_id": ObjectId(file_id)})
        except Exception as e:
            logger.error(f"שגיאה בקבלת קובץ גדול לפי ID: {e}")
            return None

    def get_user_large_files(self, user_id: int, page: int = 1, per_page: int = 8) -> Tuple[List[Dict], int]:
        try:
            skip = (page - 1) * per_page
            total_count = self.manager.large_files_collection.count_documents({"user_id": user_id, "is_active": True})
            files = list(
                self.manager.large_files_collection.find(
                    {"user_id": user_id, "is_active": True},
                    sort=[("created_at", -1)],
                ).skip(skip).limit(per_page)
            )
            return files, int(total_count)
        except Exception as e:
            logger.error(f"שגיאה בקבלת קבצים גדולים: {e}")
            return [], 0

    def delete_large_file(self, user_id: int, file_name: str) -> bool:
        try:
            result = self.manager.large_files_collection.update_many(
                {"user_id": user_id, "file_name": file_name, "is_active": True},
                {"$set": {"is_active": False, "updated_at": datetime.now(timezone.utc)}},
            )
            return bool(result.modified_count and result.modified_count > 0)
        except Exception as e:
            logger.error(f"שגיאה במחיקת קובץ גדול: {e}")
            return False

    def delete_large_file_by_id(self, file_id: str) -> bool:
        try:
            result = self.manager.large_files_collection.delete_one({"_id": ObjectId(file_id)})
            return bool(result.deleted_count and result.deleted_count > 0)
        except Exception as e:
            logger.error(f"שגיאה במחיקת קובץ גדול לפי ID: {e}")
            return False

    def get_all_user_files_combined(self, user_id: int) -> Dict[str, List[Dict]]:
        try:
            regular_files = self.get_user_files(user_id, limit=100)
            large_files, _ = self.get_user_large_files(user_id, page=1, per_page=100)
            return {"regular_files": regular_files, "large_files": large_files}
        except Exception as e:
            logger.error(f"שגיאה בקבלת כל הקבצים: {e}")
            return {"regular_files": [], "large_files": []}

    # Users auxiliary data
    def save_github_token(self, user_id: int, token: str) -> bool:
        try:
            from secret_manager import encrypt_secret
            enc = encrypt_secret(token)
            stored = enc if enc else token
            users_collection = self.manager.db.users
            result = users_collection.update_one(
                {"user_id": user_id},
                {"$set": {"github_token": stored, "updated_at": datetime.now(timezone.utc)},
                 "$setOnInsert": {"created_at": datetime.now(timezone.utc)}},
                upsert=True,
            )
            return bool(result.acknowledged)
        except Exception as e:
            logger.error(f"שגיאה בשמירת טוקן GitHub: {e}")
            return False

    def get_github_token(self, user_id: int) -> Optional[str]:
        try:
            users_collection = self.manager.db.users
            user = users_collection.find_one({"user_id": user_id})
            if user and "github_token" in user:
                stored = user["github_token"]
                try:
                    from secret_manager import decrypt_secret
                    dec = decrypt_secret(stored)
                    return dec if dec else stored
                except Exception:
                    return stored
            return None
        except Exception as e:
            logger.error(f"שגיאה בקבלת טוקן GitHub: {e}")
            return None

    def delete_github_token(self, user_id: int) -> bool:
        try:
            users_collection = self.manager.db.users
            result = users_collection.update_one(
                {"user_id": user_id},
                {"$unset": {"github_token": ""}, "$set": {"updated_at": datetime.now(timezone.utc)}},
            )
            return bool(result.acknowledged)
        except Exception as e:
            logger.error(f"שגיאה במחיקת טוקן GitHub: {e}")
            return False

        
    def save_selected_repo(self, user_id: int, repo_name: str) -> bool:
        try:
            users_collection = self.manager.db.users
            result = users_collection.update_one(
                {"user_id": user_id},
                {"$set": {"selected_repo": repo_name, "updated_at": datetime.now(timezone.utc)},
                 "$setOnInsert": {"created_at": datetime.now(timezone.utc)}},
                upsert=True,
            )
            return bool(result.acknowledged)
        except Exception as e:
            logger.error(f"שגיאה בשמירת ריפו נבחר: {e}")
            return False

    def get_selected_repo(self, user_id: int) -> Optional[str]:
        try:
            users_collection = self.manager.db.users
            user = users_collection.find_one({"user_id": user_id})
            if user and "selected_repo" in user:
                return user["selected_repo"]
            return None
        except Exception as e:
            logger.error(f"שגיאה בקבלת ריפו נבחר: {e}")
            return None

    def save_user(self, user_id: int, username: str = None) -> bool:
        try:
            users_collection = self.manager.db.users
            result = users_collection.update_one(
                {"user_id": user_id},
                {"$setOnInsert": {"user_id": user_id, "username": username, "created_at": datetime.now(timezone.utc)},
                 "$set": {"last_activity": datetime.now(timezone.utc)}},
                upsert=True,
            )
            return bool(result.acknowledged)
        except Exception as e:
            logger.error(f"שגיאה בשמירת משתמש: {e}")
            return False

    # --- Google Drive tokens & preferences ---
    def save_drive_tokens(self, user_id: int, token_data: Dict[str, Any]) -> bool:
        try:
            users_collection = self.manager.db.users
            # Encrypt sensitive fields
            from secret_manager import encrypt_secret
            enc_access = encrypt_secret(token_data.get("access_token", "") or "")
            enc_refresh = encrypt_secret(token_data.get("refresh_token", "") or "")
            stored = {
                "access_token": enc_access if enc_access else token_data.get("access_token"),
                "refresh_token": enc_refresh if enc_refresh else token_data.get("refresh_token"),
                "token_type": token_data.get("token_type"),
                "expiry": token_data.get("expiry"),
                "scope": token_data.get("scope"),
                "expires_in": token_data.get("expires_in"),
                "obtained_at": datetime.now(timezone.utc).isoformat(),
            }
            result = users_collection.update_one(
                {"user_id": user_id},
                {"$set": {"drive_tokens": stored, "updated_at": datetime.now(timezone.utc)}},
                upsert=True,
            )
            return bool(result.acknowledged)
        except Exception as e:
            logger.error(f"Failed to save Drive tokens: {e}")
            return False

    def get_drive_tokens(self, user_id: int) -> Optional[Dict[str, Any]]:
        try:
            users_collection = self.manager.db.users
            user = users_collection.find_one({"user_id": user_id})
            if not user:
                return None
            data = user.get("drive_tokens")
            if not data:
                return None
            # Decrypt
            from secret_manager import decrypt_secret
            acc = data.get("access_token")
            ref = data.get("refresh_token")
            acc_dec = decrypt_secret(acc) if acc else None
            ref_dec = decrypt_secret(ref) if ref else None
            out = dict(data)
            if acc_dec:
                out["access_token"] = acc_dec
            if ref_dec:
                out["refresh_token"] = ref_dec
            return out
        except Exception as e:
            logger.error(f"Failed to get Drive tokens: {e}")
            return None

    def delete_drive_tokens(self, user_id: int) -> bool:
        try:
            users_collection = self.manager.db.users
            res = users_collection.update_one(
                {"user_id": user_id}, {"$unset": {"drive_tokens": ""}, "$set": {"updated_at": datetime.now(timezone.utc)}}
            )
            return bool(res.acknowledged)
        except Exception as e:
            logger.error(f"Failed to delete Drive tokens: {e}")
            return False

    def save_drive_prefs(self, user_id: int, prefs: Dict[str, Any]) -> bool:
        try:
            users_collection = self.manager.db.users
            # merge with existing prefs
            existing = users_collection.find_one({"user_id": user_id}) or {}
            merged = dict(existing.get("drive_prefs") or {})
            merged.update(prefs or {})
            res = users_collection.update_one(
                {"user_id": user_id},
                {"$set": {"drive_prefs": merged, "updated_at": datetime.now(timezone.utc)}},
                upsert=True,
            )
            return bool(res.acknowledged)
        except Exception as e:
            logger.error(f"Failed to save Drive prefs: {e}")
            return False

    def get_drive_prefs(self, user_id: int) -> Optional[Dict[str, Any]]:
        try:
            users_collection = self.manager.db.users
            user = users_collection.find_one({"user_id": user_id})
            if not user:
                return None
            return user.get("drive_prefs")
        except Exception as e:
            logger.error(f"Failed to get Drive prefs: {e}")
            return None

    # --- Backup ratings ---
    def save_backup_rating(self, user_id: int, backup_id: str, rating: str) -> bool:
        try:
            coll = self.manager.backup_ratings_collection
            if coll is None:
                logger.warning("backup_ratings_collection is not initialized")
                return False
            doc = {
                "user_id": user_id,
                "backup_id": backup_id,
                "rating": rating,
                "created_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc),
            }
            coll.update_one(
                {"user_id": user_id, "backup_id": backup_id},
                {"$set": {"rating": rating, "updated_at": datetime.now(timezone.utc)},
                 "$setOnInsert": {"created_at": datetime.now(timezone.utc)}},
                upsert=True,
            )
            return True
        except Exception as e:
            logger.error(f"Failed to save backup rating: {e}")
            return False

    def get_backup_rating(self, user_id: int, backup_id: str) -> Optional[str]:
        try:
            coll = self.manager.backup_ratings_collection
            if coll is None:
                return None
            doc = coll.find_one({"user_id": user_id, "backup_id": backup_id})
            if doc:
                return doc.get("rating")
            return None
        except Exception as e:
            logger.error(f"Failed to get backup rating: {e}")
            return None

    def delete_backup_ratings(self, user_id: int, backup_ids: List[str]) -> int:
        try:
            coll = self.manager.backup_ratings_collection
            if coll is None:
                return 0
            res = coll.delete_many({"user_id": user_id, "backup_id": {"$in": backup_ids}})
            return int(res.deleted_count or 0)
        except Exception as e:
            logger.error(f"Failed to delete backup ratings: {e}")
            return 0

    # --- Backup notes ---
    def save_backup_note(self, user_id: int, backup_id: str, note: str) -> bool:
        """שומר או מעדכן הערה עבור גיבוי (מאוחד עם מסמך הדירוג)."""
        try:
            coll = self.manager.backup_ratings_collection
            if coll is None:
                logger.warning("backup_ratings_collection is not initialized")
                return False
            now = datetime.now(timezone.utc)
            coll.update_one(
                {"user_id": user_id, "backup_id": backup_id},
                {"$set": {"note": (note or "")[:1000], "updated_at": now}, "$setOnInsert": {"created_at": now}},
                upsert=True,
            )
            return True
        except Exception as e:
            logger.error(f"Failed to save backup note: {e}")
            return False

    def get_backup_note(self, user_id: int, backup_id: str) -> Optional[str]:
        try:
            coll = self.manager.backup_ratings_collection
            if coll is None:
                return None
            doc = coll.find_one({"user_id": user_id, "backup_id": backup_id})
            if doc:
                return doc.get("note")
            return None
        except Exception as e:
            logger.error(f"Failed to get backup note: {e}")
            return None

