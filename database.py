import logging
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import pymongo
from pymongo import ASCENDING, DESCENDING, TEXT, IndexModel, MongoClient

from config import config
from cache_manager import cache, cached

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

@dataclass
class LargeFile:
    """מחלקה לייצוג קובץ גדול"""
    user_id: int
    file_name: str
    content: str
    programming_language: str
    file_size: int  # גודל בבתים
    lines_count: int  # מספר שורות
    description: str = ""
    tags: List[str] = None
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
        # חישוב אוטומטי של גודל ומספר שורות
        if self.content:
            self.file_size = len(self.content.encode('utf-8'))
            self.lines_count = len(self.content.split('\n'))

class DatabaseManager:
    """מנהל מסד הנתונים"""
    
    def __init__(self):
        self.client = None
        self.db = None
        self.collection = None
        self.connect()
    
    def connect(self):
        """יוצר חיבור למסד הנתונים עם Connection Pooling מתקדם"""
        try:
            # הגדרות Connection Pooling מתקדמות
            self.client = MongoClient(
                config.MONGODB_URL,
                # הגדרות Connection Pool
                maxPoolSize=50,              # מקסימום 50 חיבורים בו-זמנית
                minPoolSize=5,               # מינימום 5 חיבורים תמיד פתוחים
                maxIdleTimeMS=30000,         # סגירת חיבורים לא פעילים אחרי 30 שניות
                waitQueueTimeoutMS=5000,     # זמן המתנה מקסימלי לחיבור פנוי
                
                # הגדרות Timeout
                serverSelectionTimeoutMS=3000,  # זמן המתנה לבחירת שרת
                socketTimeoutMS=20000,          # timeout לפעולות socket
                connectTimeoutMS=10000,         # timeout להתחברות
                
                # הגדרות Retry
                retryWrites=True,               # חזרה אוטומטית על כתיבות כושלות
                retryReads=True,                # חזרה אוטומטית על קריאות כושלות
                
                # הגדרות נוספות
                compressors='snappy,zlib',      # דחיסת נתונים לחיסכון ברוחב פס
                zlibCompressionLevel=6          # רמת דחיסה מאוזנת
            )
            
            self.db = self.client[config.DATABASE_NAME]
            self.collection = self.db.code_snippets
            self.large_files_collection = self.db.large_files  # קולקשן חדש לקבצים גדולים
            
            # בדיקת חיבור
            self.client.admin.command('ping')
            
            # יצירת אינדקסים לחיפוש מהיר
            self._create_indexes()
            
            logger.info("התחברות למסד הנתונים הצליחה עם Connection Pooling מתקדם")
            logger.info(f"Pool settings: maxPoolSize=50, minPoolSize=5, maxIdleTime=30s")
            
        except Exception as e:
            logger.error(f"שגיאה בהתחברות למסד הנתונים: {e}")
            raise
    
    def _create_indexes(self):
        """יוצר אינדקסים מתקדמים לשיפור ביצועי החיפוש"""
        indexes = [
            # אינדקסים בסיסיים
            IndexModel([("user_id", ASCENDING)]),
            IndexModel([("file_name", ASCENDING)]),
            IndexModel([("programming_language", ASCENDING)]),
            IndexModel([("tags", ASCENDING)]),
            IndexModel([("created_at", DESCENDING)]),
            
            # אינדקס מורכב קיים (טוב!)
            IndexModel([("user_id", ASCENDING), ("file_name", ASCENDING), ("version", DESCENDING)]),
            
            # אינדקסים מורכבים חדשים לביצועים מתקדמים
            IndexModel([
                ("user_id", ASCENDING), 
                ("programming_language", ASCENDING), 
                ("created_at", DESCENDING)
            ], name="user_lang_date_idx"),  # חיפוש קבצים לפי משתמש ושפה
            
            IndexModel([
                ("user_id", ASCENDING), 
                ("tags", ASCENDING), 
                ("updated_at", DESCENDING)
            ], name="user_tags_updated_idx"),  # חיפוש לפי תגיות ועדכון אחרון
            
            IndexModel([
                ("user_id", ASCENDING), 
                ("is_active", ASCENDING), 
                ("programming_language", ASCENDING)
            ], name="user_active_lang_idx"),  # חיפוש קבצים פעילים לפי שפה
            
            IndexModel([
                ("user_id", ASCENDING), 
                ("is_active", ASCENDING), 
                ("updated_at", DESCENDING)
            ], name="user_active_recent_idx"),  # קבצים פעילים אחרונים
            
            IndexModel([
                ("programming_language", ASCENDING), 
                ("tags", ASCENDING), 
                ("created_at", DESCENDING)
            ], name="lang_tags_date_idx"),  # חיפוש גלובלי לפי שפה ותגיות
            
            # אינדקס טקסט משופר
            IndexModel([("code", TEXT), ("description", TEXT), ("file_name", TEXT)], 
                      name="full_text_search_idx")
        ]
        
        # אינדקסים מתקדמים לקבצים גדולים
        large_files_indexes = [
            # אינדקסים בסיסיים
            IndexModel([("user_id", ASCENDING)]),
            IndexModel([("file_name", ASCENDING)]),
            IndexModel([("programming_language", ASCENDING)]),
            IndexModel([("created_at", DESCENDING)]),
            IndexModel([("file_size", ASCENDING)]),
            IndexModel([("lines_count", ASCENDING)]),
            
            # אינדקסים מורכבים לקבצים גדולים
            IndexModel([("user_id", ASCENDING), ("file_name", ASCENDING)]),
            
            IndexModel([
                ("user_id", ASCENDING), 
                ("programming_language", ASCENDING), 
                ("file_size", ASCENDING)
            ], name="user_lang_size_idx"),  # מיון לפי גודל בתוך שפה
            
            IndexModel([
                ("user_id", ASCENDING), 
                ("is_active", ASCENDING), 
                ("created_at", DESCENDING)
            ], name="user_active_date_large_idx"),  # קבצים גדולים פעילים אחרונים
            
            IndexModel([
                ("programming_language", ASCENDING), 
                ("file_size", ASCENDING), 
                ("lines_count", ASCENDING)
            ], name="lang_size_lines_idx"),  # ניתוח לפי שפה וגודל
            
            IndexModel([
                ("user_id", ASCENDING), 
                ("tags", ASCENDING), 
                ("file_size", DESCENDING)
            ], name="user_tags_size_idx")  # חיפוש בתגיות עם מיון לפי גודל
        ]
        
        try:
            self.collection.create_indexes(indexes)
            self.large_files_collection.create_indexes(large_files_indexes)
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
                snippet.version = existing['version'] + 1
            
            snippet.updated_at = datetime.now()
            
            # שמירה במסד הנתונים
            result = self.collection.insert_one(asdict(snippet))
            
            if result.inserted_id:
                # ביטול cache של המשתמש אחרי שמירה
                cache.invalidate_user_cache(snippet.user_id)
                logger.info(f"קטע קוד נשמר: {snippet.file_name} (גרסה {snippet.version})")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"שגיאה בשמירת קטע קוד: {e}")
            return False
    
    def save_file(self, user_id: int, file_name: str, code: str, programming_language: str) -> bool:
        """A convenience wrapper that builds a CodeSnippet and delegates to save_code_snippet."""
        snippet = CodeSnippet(
            user_id=user_id,
            file_name=file_name,
            code=code,
            programming_language=programming_language,
        )
        return self.save_code_snippet(snippet)
    
    @cached(expire_seconds=180, key_prefix="latest_version")  # cache ל-3 דקות
    def get_latest_version(self, user_id: int, file_name: str) -> Optional[Dict]:
        """מחזיר את הגרסה האחרונה של קטע קוד"""
        try:
            return self.collection.find_one(
                {"user_id": user_id, "file_name": file_name, "is_active": True},
                sort=[("version", DESCENDING)]
            )
        except Exception as e:
            logger.error(f"שגיאה בקבלת גרסה אחרונה: {e}")
            return None

    def get_file(self, user_id: int, file_name: str) -> Optional[Dict]:
        """מחזיר קובץ ספציפי של משתמש"""
        try:
            return self.collection.find_one(
                {"user_id": user_id, "file_name": file_name, "is_active": True},
                sort=[("version", DESCENDING)]
            )
        except Exception as e:
            logger.error(f"שגיאה בקבלת קובץ: {e}")
            return None
    
    def get_all_versions(self, user_id: int, file_name: str) -> List[Dict]:
        """מחזיר את כל הגרסאות של קטע קוד"""
        try:
            return list(self.collection.find(
                {"user_id": user_id, "file_name": file_name, "is_active": True},
                sort=[("version", DESCENDING)]
            ))
        except Exception as e:
            logger.error(f"שגיאה בקבלת כל הגרסאות: {e}")
            return []
    
    def get_version(self, user_id: int, file_name: str, version: int) -> Optional[Dict]:
        """מחזיר מסמך של גרסה ספציפית של קובץ"""
        try:
            return self.collection.find_one(
                {"user_id": user_id, "file_name": file_name, "version": version, "is_active": True}
            )
        except Exception as e:
            logger.error(f"שגיאה בקבלת גרסה {version} עבור {file_name}: {e}")
            return None

    @cached(expire_seconds=120, key_prefix="user_files")  # cache ל-2 דקות
    def get_user_files(self, user_id: int, limit: int = 50) -> List[Dict]:
        """מחזיר את כל הקבצים של משתמש (גרסה אחרונה בלבד)"""
        try:
            pipeline = [
                {"$match": {"user_id": user_id, "is_active": True}},
                {"$sort": {"version": -1}},
                {"$group": {
                    "_id": "$file_name",
                    "latest": {"$first": "$$ROOT"}
                }},
                {"$replaceRoot": {"newRoot": "$latest"}},
                {"$sort": {"updated_at": -1}},
                {"$limit": limit}
            ]
            
            return list(self.collection.aggregate(pipeline))
            
        except Exception as e:
            logger.error(f"שגיאה בקבלת קבצי משתמש: {e}")
            return []
    
    @cached(expire_seconds=300, key_prefix="search_code")  # cache ל-5 דקות
    def search_code(self, user_id: int, query: str, programming_language: str = None, 
                   tags: List[str] = None, limit: int = 20) -> List[Dict]:
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
                {"$group": {
                    "_id": "$file_name",
                    "latest": {"$first": "$$ROOT"}
                }},
                {"$replaceRoot": {"newRoot": "$latest"}},
                {"$sort": {"updated_at": -1}},
                {"$limit": limit}
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
                {"$set": {"is_active": False, "updated_at": datetime.now()}}
            )
            
            if result.modified_count > 0:
                # ביטול cache של המשתמש אחרי מחיקה
                cache.invalidate_user_cache(user_id)
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
                {"$group": {
                    "_id": "$file_name",
                    "versions": {"$sum": 1},
                    "programming_language": {"$first": "$programming_language"},
                    "latest_update": {"$max": "$updated_at"}
                }},
                {"$group": {
                    "_id": None,
                    "total_files": {"$sum": 1},
                    "total_versions": {"$sum": "$versions"},
                    "languages": {"$addToSet": "$programming_language"},
                    "latest_activity": {"$max": "$latest_update"}
                }}
            ]
            
            result = list(self.collection.aggregate(pipeline))
            
            if result:
                stats = result[0]
                stats.pop('_id')
                return stats
            
            return {
                "total_files": 0,
                "total_versions": 0,
                "languages": [],
                "latest_activity": None
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

    def rename_file(self, user_id: int, old_name: str, new_name: str) -> bool:
        """שינוי שם קובץ"""
        try:
            # בדיקה אם השם החדש כבר קיים
            existing = self.get_latest_version(user_id, new_name)
            if existing and new_name != old_name:
                logger.warning(f"File {new_name} already exists for user {user_id}")
                return False
            
            # עדכון שם הקובץ בכל הגרסאות
            result = self.collection.update_many(
                {"user_id": user_id, "file_name": old_name, "is_active": True},
                {"$set": {"file_name": new_name, "updated_at": datetime.now()}}
            )
            
            if result.modified_count > 0:
                logger.info(f"Renamed file {old_name} to {new_name} for user {user_id}")
                return True
            else:
                logger.warning(f"No files renamed - file {old_name} not found for user {user_id}")
                return False
                
        except Exception as e:
            logger.error(f"Error renaming file {old_name} to {new_name} for user {user_id}: {e}")
            return False

    # פונקציות לניהול קבצים גדולים
    def save_large_file(self, large_file: LargeFile) -> bool:
        """שומר קובץ גדול במסד הנתונים"""
        try:
            # בדיקה אם קיים קובץ עם אותו שם
            existing = self.get_large_file(large_file.user_id, large_file.file_name)
            
            if existing:
                # מחיקת הגרסה הקודמת
                self.delete_large_file(large_file.user_id, large_file.file_name)
            
            # שמירה במסד הנתונים
            result = self.large_files_collection.insert_one(asdict(large_file))
            
            if result.inserted_id:
                logger.info(f"קובץ גדול נשמר: {large_file.file_name} ({large_file.file_size} בתים)")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"שגיאה בשמירת קובץ גדול: {e}")
            return False
    
    def get_large_file(self, user_id: int, file_name: str) -> Optional[Dict]:
        """מחזיר קובץ גדול ספציפי"""
        try:
            return self.large_files_collection.find_one(
                {"user_id": user_id, "file_name": file_name, "is_active": True}
            )
        except Exception as e:
            logger.error(f"שגיאה בקבלת קובץ גדול: {e}")
            return None
    
    def get_large_file_by_id(self, file_id: str) -> Optional[Dict]:
        """מחזיר קובץ גדול לפי ID"""
        try:
            from bson import ObjectId
            return self.large_files_collection.find_one({"_id": ObjectId(file_id)})
        except Exception as e:
            logger.error(f"שגיאה בקבלת קובץ גדול לפי ID: {e}")
            return None
    
    def get_user_large_files(self, user_id: int, page: int = 1, per_page: int = 8) -> Tuple[List[Dict], int]:
        """מחזיר רשימת קבצים גדולים של משתמש עם pagination"""
        try:
            # חישוב skip
            skip = (page - 1) * per_page
            
            # ספירת סה"כ קבצים
            total_count = self.large_files_collection.count_documents(
                {"user_id": user_id, "is_active": True}
            )
            
            # קבלת הקבצים לעמוד הנוכחי
            files = list(self.large_files_collection.find(
                {"user_id": user_id, "is_active": True},
                sort=[("created_at", DESCENDING)]
            ).skip(skip).limit(per_page))
            
            return files, total_count
            
        except Exception as e:
            logger.error(f"שגיאה בקבלת קבצים גדולים: {e}")
            return [], 0
    
    def delete_large_file(self, user_id: int, file_name: str) -> bool:
        """מוחק קובץ גדול"""
        try:
            result = self.large_files_collection.update_many(
                {"user_id": user_id, "file_name": file_name, "is_active": True},
                {"$set": {"is_active": False, "updated_at": datetime.now()}}
            )
            
            if result.modified_count > 0:
                logger.info(f"קובץ גדול נמחק: {file_name} ({result.modified_count} מסמכים עודכנו)")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"שגיאה במחיקת קובץ גדול: {e}")
            return False
    
    def delete_large_file_by_id(self, file_id: str) -> bool:
        """מוחק קובץ גדול לפי ID"""
        try:
            from bson import ObjectId
            result = self.large_files_collection.delete_one({"_id": ObjectId(file_id)})
            return result.deleted_count > 0
        except Exception as e:
            logger.error(f"שגיאה במחיקת קובץ גדול לפי ID: {e}")
            return False
    
    def get_all_user_files_combined(self, user_id: int) -> Dict[str, List[Dict]]:
        """מחזיר את כל הקבצים של משתמש - גם רגילים וגם גדולים"""
        try:
            regular_files = self.get_user_files(user_id, limit=100)
            large_files, _ = self.get_user_large_files(user_id, page=1, per_page=100)
            
            return {
                "regular_files": regular_files,
                "large_files": large_files
            }
        except Exception as e:
            logger.error(f"שגיאה בקבלת כל הקבצים: {e}")
            return {"regular_files": [], "large_files": []}
    
    def save_github_token(self, user_id: int, token: str) -> bool:
        """שומר טוקן GitHub למשתמש במסד הנתונים"""
        try:
            # יצירת קולקשן users אם לא קיים
            users_collection = self.db.users
            
            # עדכון או יצירת רשומת משתמש
            result = users_collection.update_one(
                {"user_id": user_id},
                {
                    "$set": {
                        "github_token": token,
                        "updated_at": datetime.now()
                    },
                    "$setOnInsert": {
                        "created_at": datetime.now()
                    }
                },
                upsert=True
            )
            
            return result.acknowledged
        except Exception as e:
            logger.error(f"שגיאה בשמירת טוקן GitHub: {e}")
            return False
    
    def get_github_token(self, user_id: int) -> str:
        """מחזיר טוקן GitHub של משתמש מהמסד נתונים"""
        try:
            users_collection = self.db.users
            user = users_collection.find_one({"user_id": user_id})
            
            if user and "github_token" in user:
                return user["github_token"]
            
            return None
        except Exception as e:
            logger.error(f"שגיאה בקבלת טוקן GitHub: {e}")
            return None

    def delete_github_token(self, user_id: int) -> bool:
        """מוחק את טוקן ה-GitHub של המשתמש מהמסד נתונים"""
        try:
            users_collection = self.db.users
            result = users_collection.update_one(
                {"user_id": user_id},
                {
                    "$unset": {"github_token": ""},
                    "$set": {"updated_at": datetime.now()}
                }
            )
            return result.acknowledged
        except Exception as e:
            logger.error(f"שגיאה במחיקת טוקן GitHub: {e}")
            return False

    def save_selected_repo(self, user_id: int, repo_name: str) -> bool:
        """שומר את הריפו הנבחר של המשתמש במסד הנתונים"""
        try:
            users_collection = self.db.users
            
            result = users_collection.update_one(
                {"user_id": user_id},
                {
                    "$set": {
                        "selected_repo": repo_name,
                        "updated_at": datetime.now()
                    },
                    "$setOnInsert": {
                        "created_at": datetime.now()
                    }
                },
                upsert=True
            )
            
            return result.acknowledged
        except Exception as e:
            logger.error(f"שגיאה בשמירת ריפו נבחר: {e}")
            return False
    
    def get_selected_repo(self, user_id: int) -> str:
        """מחזיר את הריפו הנבחר של המשתמש מהמסד נתונים"""
        try:
            users_collection = self.db.users
            user = users_collection.find_one({"user_id": user_id})
            
            if user and "selected_repo" in user:
                return user["selected_repo"]
            
            return None
        except Exception as e:
            logger.error(f"שגיאה בקבלת ריפו נבחר: {e}")
            return None
    
    def save_user(self, user_id: int, username: str = None) -> bool:
        """שומר משתמש במסד הנתונים (INSERT OR IGNORE)"""
        try:
            users_collection = self.db.users
            
            # עדכון או יצירת רשומת משתמש
            result = users_collection.update_one(
                {"user_id": user_id},
                {
                    "$setOnInsert": {
                        "user_id": user_id,
                        "username": username,
                        "created_at": datetime.now()
                    },
                    "$set": {
                        "last_activity": datetime.now()
                    }
                },
                upsert=True
            )
            
            return result.acknowledged
        except Exception as e:
            logger.error(f"שגיאה בשמירת משתמש: {e}")
            return False

# יצירת אינסטנס גלובלי
db = DatabaseManager()
