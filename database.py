import logging
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

import pymongo
from pymongo import ASCENDING, DESCENDING, TEXT, IndexModel, MongoClient

from config import config

logger = logging.getLogger(__name__)


@dataclass
class CodeSnippet:
    """מחלקה לייצוג קטע קוד"""

    user_id: int
    file_name: str
    code: str
    programming_language: str  # שם השדה שונה כדי למנוע קונפליקט
    description: str = ""
    tags: List[str] = None
    version: int = 1
    created_at: datetime = None
    updated_at: datetime = None
    is_active: bool = True

    def __post_init__(self):
        if self.tags is None:
            self.tags = []
        if self.created_at is None:
            self.created_at = datetime.now()
        if self.updated_at is None:
            self.updated_at = datetime.now()


class DatabaseManager:
    """מנהל מסד הנתונים"""

    def __init__(self):
        self.client = None
        self.db = None
        self.collection = None
        self.connect()

    def connect(self):
        """יוצר חיבור למסד הנתונים"""
        try:
            self.client = MongoClient(config.MONGODB_URL)
            self.db = self.client[config.DATABASE_NAME]
            self.collection = self.db.code_snippets

            # יצירת אינדקסים לחיפוש מהיר
            self._create_indexes()

            logger.info("התחברות למסד הנתונים הצליחה")

        except Exception as e:
            logger.error(f"שגיאה בהתחברות למסד הנתונים: {e}")
            raise

    def _create_indexes(self):
        """יוצר אינדקסים לשיפור ביצועי החיפוש"""
        indexes = [
            IndexModel([("user_id", ASCENDING)]),
            IndexModel([("file_name", ASCENDING)]),
            IndexModel([("programming_language", ASCENDING)]),  # עודכן כאן
            IndexModel([("tags", ASCENDING)]),
            IndexModel([("created_at", DESCENDING)]),
            IndexModel(
                [
                    ("user_id", ASCENDING),
                    ("file_name", ASCENDING),
                    ("version", DESCENDING),
                ]
            ),
            IndexModel([("code", TEXT), ("description", TEXT), ("file_name", TEXT)]),
        ]

        try:
            self.collection.create_indexes(indexes)
            logger.info("אינדקסים נוצרו בהצלחה")
        except Exception as e:
            logger.warning(f"שגיאה ביצירת אינדקסים: {e}")

    def save_code_snippet(self, snippet: CodeSnippet) -> bool:
        """שומר קטע קוד חדש או מעדכן קיים"""
        try:
            # בדיקה אם קיים קטע עם אותו שם
            existing = self.get_latest_version(snippet.user_id, snippet.file_name)

            if existing:
                # יצירת גרסה חדשה
                snippet.version = existing["version"] + 1

            snippet.updated_at = datetime.now()

            # שמירה במסד הנתונים
            result = self.collection.insert_one(asdict(snippet))

            if result.inserted_id:
                logger.info(
                    f"קטע קוד נשמר: {snippet.file_name} (גרסה {snippet.version})"
                )
                return True

            return False

        except Exception as e:
            logger.error(f"שגיאה בשמירת קטע קוד: {e}")
            return False

    def save_file(
        self, user_id: int, file_name: str, code: str, programming_language: str
    ) -> bool:
        """A convenience wrapper that builds a CodeSnippet and delegates to save_code_snippet."""
        snippet = CodeSnippet(
            user_id=user_id,
            file_name=file_name,
            code=code,
            programming_language=programming_language,
        )
        return self.save_code_snippet(snippet)

    def get_latest_version(self, user_id: int, file_name: str) -> Optional[Dict]:
        """מחזיר את הגרסה האחרונה של קטע קוד"""
        try:
            return self.collection.find_one(
                {"user_id": user_id, "file_name": file_name, "is_active": True},
                sort=[("version", DESCENDING)],
            )
        except Exception as e:
            logger.error(f"שגיאה בקבלת גרסה אחרונה: {e}")
            return None

    def get_file(self, user_id: int, file_name: str) -> Optional[Dict]:
        """מחזיר קובץ ספציפי של משתמש"""
        try:
            return self.collection.find_one(
                {"user_id": user_id, "file_name": file_name, "is_active": True},
                sort=[("version", DESCENDING)],
            )
        except Exception as e:
            logger.error(f"שגיאה בקבלת קובץ: {e}")
            return None

    def get_all_versions(self, user_id: int, file_name: str) -> List[Dict]:
        """מחזיר את כל הגרסאות של קטע קוד"""
        try:
            return list(
                self.collection.find(
                    {"user_id": user_id, "file_name": file_name, "is_active": True},
                    sort=[("version", DESCENDING)],
                )
            )
        except Exception as e:
            logger.error(f"שגיאה בקבלת כל הגרסאות: {e}")
            return []

    def get_user_files(self, user_id: int, limit: int = 50) -> List[Dict]:
        """מחזיר את כל הקבצים של משתמש (גרסה אחרונה בלבד)"""
        try:
            pipeline = [
                {"$match": {"user_id": user_id, "is_active": True}},
                {"$sort": {"version": -1}},
                {"$group": {"_id": "$file_name", "latest": {"$first": "$$ROOT"}}},
                {"$replaceRoot": {"newRoot": "$latest"}},
                {"$sort": {"updated_at": -1}},
                {"$limit": limit},
            ]

            return list(self.collection.aggregate(pipeline))

        except Exception as e:
            logger.error(f"שגיאה בקבלת קבצי משתמש: {e}")
            return []

    def search_code(
        self,
        user_id: int,
        query: str,
        programming_language: str = None,
        tags: List[str] = None,
        limit: int = 20,
    ) -> List[Dict]:
        """חיפוש מתקדם בקטעי קוד"""
        try:
            search_filter = {"user_id": user_id, "is_active": True}

            # חיפוש טקסט
            if query:
                search_filter["$text"] = {"$search": query}

            # סינון לפי שפה
            if programming_language:
                search_filter["programming_language"] = programming_language

            # סינון לפי תגיות
            if tags:
                search_filter["tags"] = {"$in": tags}

            # חיפוש עם עדיפות לגרסה אחרונה
            pipeline = [
                {"$match": search_filter},
                {"$sort": {"version": -1}},
                {"$group": {"_id": "$file_name", "latest": {"$first": "$$ROOT"}}},
                {"$replaceRoot": {"newRoot": "$latest"}},
                {"$sort": {"updated_at": -1}},
                {"$limit": limit},
            ]

            return list(self.collection.aggregate(pipeline))

        except Exception as e:
            logger.error(f"שגיאה בחיפוש קוד: {e}")
            return []

    def delete_file(self, user_id: int, file_name: str) -> bool:
        """מוחק קובץ (מסמן כלא פעיל)"""
        try:
            result = self.collection.update_many(
                {"user_id": user_id, "file_name": file_name},
                {"$set": {"is_active": False, "updated_at": datetime.now()}},
            )

            if result.modified_count > 0:
                logger.info(f"קובץ נמחק: {file_name}")
                return True

            return False

        except Exception as e:
            logger.error(f"שגיאה במחיקת קובץ: {e}")
            return False

    def delete_file_by_id(self, file_id: str) -> int:
        """Delete a file document by its MongoDB _id. Returns the number of deleted documents."""
        try:
            from bson import ObjectId

            result = self.collection.delete_one({"_id": ObjectId(file_id)})
            return result.deleted_count  # type: ignore[attr-defined]
        except Exception as e:
            logger.error(f"שגיאה במחיקת קובץ לפי _id: {e}")
            return 0

    def get_file_by_id(self, file_id: str) -> Optional[Dict]:
        """Fetch a single file document by its MongoDB _id"""
        try:
            from bson import ObjectId

            return self.collection.find_one({"_id": ObjectId(file_id)})
        except Exception as e:
            logger.error(f"שגיאה בקבלת קובץ לפי _id: {e}")
            return None

    def get_user_stats(self, user_id: int) -> Dict[str, Any]:
        """מחזיר סטטיסטיקות של משתמש"""
        try:
            pipeline = [
                {"$match": {"user_id": user_id, "is_active": True}},
                {
                    "$group": {
                        "_id": "$file_name",
                        "versions": {"$sum": 1},
                        "programming_language": {"$first": "$programming_language"},
                        "latest_update": {"$max": "$updated_at"},
                    }
                },
                {
                    "$group": {
                        "_id": None,
                        "total_files": {"$sum": 1},
                        "total_versions": {"$sum": "$versions"},
                        "languages": {"$addToSet": "$programming_language"},
                        "latest_activity": {"$max": "$latest_update"},
                    }
                },
            ]

            result = list(self.collection.aggregate(pipeline))

            if result:
                stats = result[0]
                stats.pop("_id")
                return stats

            return {
                "total_files": 0,
                "total_versions": 0,
                "languages": [],
                "latest_activity": None,
            }

        except Exception as e:
            logger.error(f"שגיאה בקבלת סטטיסטיקות: {e}")
            return {}

    def close(self):
        """סוגר את החיבור למסד הנתונים"""
        if self.client:
            self.client.close()
            logger.info("חיבור למסד הנתונים נסגר")

    def close_connection(self):
        """Alias for close() kept for backward compatibility."""
        self.close()


# יצירת אינסטנס גלובלי
db = DatabaseManager()
