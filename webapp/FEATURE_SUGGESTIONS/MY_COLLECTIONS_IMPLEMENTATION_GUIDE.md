# 📁 מדריך מימוש: "האוספים שלי" ב-WebApp

## 🌟 סקירה כללית

מדריך זה מתאר כיצד להוסיף פיצ'ר "האוספים שלי" (My Collections) ל-WebApp של CodeBot. הפיצ'ר יאפשר למשתמשים לארגן את הקבצים שלהם באוספים נושאיים, בדומה לתיקיות אך עם גמישות רבה יותר - קובץ יכול להיות בכמה אוספים במקביל.

## 🎯 מטרות הפיצ'ר

1. **ארגון מתקדם**: יצירת אוספים נושאיים לקבצים (מדריכי קוד, רעיונות, פיצ'רים בבנייה וכו')
2. **גמישות**: קובץ אחד יכול להיות בכמה אוספים
3. **נגישות מהירה**: גישה לאוספים מ-Sidebar ומתוך כל קובץ
4. **ניהול פשוט**: הוספה/הסרה/עריכת אוספים בקלות
5. **חווית משתמש מעולה**: ממשק אינטואיטיבי עם אנימציות חלקות

## ⚠️ הערות אבטחה חשובות

1. **מניעת XSS**: כל הנתונים שמגיעים מהמשתמש (שמות, תיאורים, אייקונים) חייבים לעבור escape לפני הצגה ב-DOM
2. **וולידציה של אייקונים**: רק אייקונים מרשימה מוגדרת מראש (whitelist) מותרים למניעת הזרקת קוד
3. **ניהול Cache**: השתמשנו ב-`cache.invalidate_user_cache()` במקום `delete_memoized` שאינה קיימת

---

## 📐 ארכיטקטורה

### מבנה הנתונים
- **Collection**: אוסף עם שם, תיאור ואייקון
- **Collection-File Mapping**: קשר רבים-לרבים בין אוספים לקבצים
- **User Ownership**: כל אוסף שייך למשתמש ספציפי

### רכיבים עיקריים
1. **Database Layer**: MongoDB collections ו-managers
2. **API Layer**: Flask endpoints לניהול אוספים
3. **Frontend**: UI components ב-JavaScript/CSS
4. **Caching**: אופטימיזציה עם cache_manager

---

## 🗄️ שכבת Database

### 1. מודלים חדשים

צור קובץ `database/collections_manager.py`:

```python
"""
Collections Manager - ניהול אוספים של קבצים
מאפשר למשתמשים לארגן קבצים באוספים נושאיים
"""
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from bson import ObjectId
from pymongo import ASCENDING, DESCENDING, IndexModel
from pymongo.errors import DuplicateKeyError

logger = logging.getLogger(__name__)

# קבועים
MAX_COLLECTIONS_PER_USER = 50  # מקסימום אוספים למשתמש
MAX_FILES_PER_COLLECTION = 200  # מקסימום קבצים באוסף
MAX_COLLECTION_NAME_LENGTH = 50
MAX_COLLECTION_DESCRIPTION_LENGTH = 200

# אייקונים דיפולטיביים לאוספים
DEFAULT_COLLECTION_ICONS = {
    'מדריכי קוד': '📘',
    'רעיונות עיצוב': '🎨',
    'פיצ'רים בבנייה': '🧩',
    'באגים לתיקון': '🐛',
    'סקריפטים': '⚙️',
    'תיעוד': '📝',
    'טסטים': '🧪',
    'דוגמאות': '💡',
    'ברירת מחדל': '📂'
}

# רשימת אייקונים מותרים (Whitelist)
ALLOWED_ICONS = {
    '📂', '📘', '🎨', '🧩', '🐛', '⚙️', '📝', '🧪', '💡',
    '📁', '📚', '🎯', '🚀', '⭐', '🔖', '🏆', '💼', '🎓',
    '🔬', '🛠️', '🎭', '🎪', '🎡', '🎢', '🎨', '🖼️', '🎬'
}

# צבעי רקע לאוספים (classes בעיצוב)
COLLECTION_COLORS = [
    'blue', 'green', 'purple', 'orange', 
    'red', 'teal', 'pink', 'yellow'
]

class CollectionsManager:
    """מנהל אוספים של קבצים"""
    
    def __init__(self, db):
        """
        Initialize collections manager
        
        Args:
            db: MongoDB database instance
        """
        self.db = db
        self.collections_coll = db.user_collections
        self.mappings_coll = db.collection_files
        # שימוש באוסף code_snippets הקיים לקבצים
        self.files_coll = db.code_snippets
        
        # יצירת indexes
        self._ensure_indexes()
    
    def _ensure_indexes(self):
        """יצירת אינדקסים לביצועים מיטביים"""
        try:
            # Indexes לאוסף user_collections
            self.collections_coll.create_index([
                ("user_id", ASCENDING),
                ("name", ASCENDING)
            ], unique=True, name="unique_user_collection_name")
            
            self.collections_coll.create_index([
                ("user_id", ASCENDING),
                ("created_at", DESCENDING)
            ], name="user_collections_recent")
            
            # Indexes לאוסף collection_files (מיפוי)
            self.mappings_coll.create_index([
                ("collection_id", ASCENDING),
                ("file_id", ASCENDING)
            ], unique=True, name="unique_collection_file")
            
            self.mappings_coll.create_index([
                ("file_id", ASCENDING)
            ], name="file_collections_lookup")
            
            self.mappings_coll.create_index([
                ("collection_id", ASCENDING),
                ("added_at", DESCENDING)
            ], name="collection_recent_files")
            
        except Exception as e:
            logger.warning(f"Failed to create collections indexes: {e}")
    
    # ==================== אוספים ====================
    
    def create_collection(self, user_id: int, name: str, 
                         description: str = "", icon: str = None,
                         color: str = None) -> Dict[str, Any]:
        """
        יצירת אוסף חדש
        
        Args:
            user_id: מזהה המשתמש
            name: שם האוסף
            description: תיאור (אופציונלי)
            icon: אייקון (אופציונלי)
            color: צבע (אופציונלי)
        
        Returns:
            dict עם פרטי האוסף החדש או שגיאה
        """
        try:
            # ולידציות
            if not name or len(name.strip()) == 0:
                return {"success": False, "error": "שם האוסף ריק"}
            
            name = name.strip()[:MAX_COLLECTION_NAME_LENGTH]
            description = description.strip()[:MAX_COLLECTION_DESCRIPTION_LENGTH]
            
            # בדיקת מגבלה
            count = self.collections_coll.count_documents({"user_id": user_id})
            if count >= MAX_COLLECTIONS_PER_USER:
                return {
                    "success": False, 
                    "error": f"הגעת למגבלה של {MAX_COLLECTIONS_PER_USER} אוספים"
                }
            
            # בחירת אייקון אוטומטית אם לא סופק או לא תקין
            if not icon or icon not in ALLOWED_ICONS:
                icon = DEFAULT_COLLECTION_ICONS.get(name, DEFAULT_COLLECTION_ICONS['ברירת מחדל'])
            
            # בחירת צבע אקראי אם לא סופק
            if not color or color not in COLLECTION_COLORS:
                import random
                color = random.choice(COLLECTION_COLORS)
            
            # יצירת האוסף
            collection_doc = {
                "user_id": user_id,
                "name": name,
                "description": description,
                "icon": icon,
                "color": color,
                "files_count": 0,  # מונה קבצים
                "created_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc),
                "is_favorite": False,  # האם מועדף
                "sort_order": count  # סדר תצוגה
            }
            
            result = self.collections_coll.insert_one(collection_doc)
            collection_doc["_id"] = result.inserted_id
            
            logger.info(f"Created collection '{name}' for user {user_id}")
            
            return {
                "success": True,
                "collection": self._serialize_collection(collection_doc)
            }
            
        except DuplicateKeyError:
            return {"success": False, "error": "כבר קיים אוסף עם שם זה"}
        except Exception as e:
            logger.error(f"Error creating collection: {e}")
            return {"success": False, "error": "שגיאה ביצירת האוסף"}
    
    def get_user_collections(self, user_id: int) -> List[Dict[str, Any]]:
        """
        קבלת כל האוספים של משתמש
        
        Returns:
            רשימת אוספים ממוינת לפי sort_order ו-created_at
        """
        try:
            collections = list(self.collections_coll.find(
                {"user_id": user_id}
            ).sort([
                ("is_favorite", DESCENDING),
                ("sort_order", ASCENDING),
                ("created_at", DESCENDING)
            ]))
            
            return [self._serialize_collection(c) for c in collections]
            
        except Exception as e:
            logger.error(f"Error getting user collections: {e}")
            return []
    
    def get_collection(self, user_id: int, collection_id: str) -> Optional[Dict[str, Any]]:
        """
        קבלת אוסף ספציפי
        """
        try:
            collection = self.collections_coll.find_one({
                "_id": ObjectId(collection_id),
                "user_id": user_id
            })
            
            if collection:
                return self._serialize_collection(collection)
            return None
            
        except Exception as e:
            logger.error(f"Error getting collection: {e}")
            return None
    
    def update_collection(self, user_id: int, collection_id: str,
                         name: str = None, description: str = None,
                         icon: str = None, color: str = None,
                         is_favorite: bool = None) -> bool:
        """
        עדכון פרטי אוסף
        """
        try:
            update_doc = {"updated_at": datetime.now(timezone.utc)}
            
            if name is not None:
                name = name.strip()[:MAX_COLLECTION_NAME_LENGTH]
                if not name:
                    return False
                update_doc["name"] = name
            
            if description is not None:
                update_doc["description"] = description.strip()[:MAX_COLLECTION_DESCRIPTION_LENGTH]
            
            if icon is not None:
                # בדיקת תקינות אייקון
                if icon in ALLOWED_ICONS:
                    update_doc["icon"] = icon
            
            if color is not None and color in COLLECTION_COLORS:
                update_doc["color"] = color
            
            if is_favorite is not None:
                update_doc["is_favorite"] = bool(is_favorite)
            
            result = self.collections_coll.update_one(
                {
                    "_id": ObjectId(collection_id),
                    "user_id": user_id
                },
                {"$set": update_doc}
            )
            
            return result.modified_count > 0
            
        except DuplicateKeyError:
            logger.error(f"Duplicate collection name for user {user_id}")
            return False
        except Exception as e:
            logger.error(f"Error updating collection: {e}")
            return False
    
    def delete_collection(self, user_id: int, collection_id: str) -> bool:
        """
        מחיקת אוסף וכל הקשרים שלו לקבצים
        """
        try:
            # מחיקת כל הקשרים לקבצים
            self.mappings_coll.delete_many({
                "collection_id": ObjectId(collection_id)
            })
            
            # מחיקת האוסף עצמו
            result = self.collections_coll.delete_one({
                "_id": ObjectId(collection_id),
                "user_id": user_id
            })
            
            if result.deleted_count > 0:
                logger.info(f"Deleted collection {collection_id} for user {user_id}")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error deleting collection: {e}")
            return False
    
    def reorder_collections(self, user_id: int, collection_ids: List[str]) -> bool:
        """
        שינוי סדר התצוגה של האוספים
        """
        try:
            for index, coll_id in enumerate(collection_ids):
                self.collections_coll.update_one(
                    {
                        "_id": ObjectId(coll_id),
                        "user_id": user_id
                    },
                    {"$set": {"sort_order": index}}
                )
            
            return True
            
        except Exception as e:
            logger.error(f"Error reordering collections: {e}")
            return False
    
    # ==================== קבצים באוספים ====================
    
    def add_file_to_collection(self, user_id: int, collection_id: str, 
                              file_id: str) -> Dict[str, Any]:
        """
        הוספת קובץ לאוסף
        """
        try:
            collection_id_obj = ObjectId(collection_id)
            file_id_obj = ObjectId(file_id)
            
            # בדיקת הרשאות - האוסף שייך למשתמש
            collection = self.collections_coll.find_one({
                "_id": collection_id_obj,
                "user_id": user_id
            })
            
            if not collection:
                return {"success": False, "error": "האוסף לא נמצא"}
            
            # בדיקת מגבלה
            if collection.get("files_count", 0) >= MAX_FILES_PER_COLLECTION:
                return {
                    "success": False,
                    "error": f"האוסף מכיל כבר {MAX_FILES_PER_COLLECTION} קבצים"
                }
            
            # בדיקה שהקובץ קיים ושייך למשתמש
            file_doc = self.files_coll.find_one({
                "_id": file_id_obj,
                "user_id": user_id
            })
            
            if not file_doc:
                return {"success": False, "error": "הקובץ לא נמצא"}
            
            # הוספת הקשר
            mapping = {
                "collection_id": collection_id_obj,
                "file_id": file_id_obj,
                "user_id": user_id,  # לבטיחות נוספת
                "added_at": datetime.now(timezone.utc)
            }
            
            try:
                self.mappings_coll.insert_one(mapping)
                
                # עדכון מונה הקבצים
                self.collections_coll.update_one(
                    {"_id": collection_id_obj},
                    {
                        "$inc": {"files_count": 1},
                        "$set": {"updated_at": datetime.now(timezone.utc)}
                    }
                )
                
                return {"success": True, "message": "הקובץ נוסף לאוסף"}
                
            except DuplicateKeyError:
                return {"success": False, "error": "הקובץ כבר נמצא באוסף זה"}
            
        except Exception as e:
            logger.error(f"Error adding file to collection: {e}")
            return {"success": False, "error": "שגיאה בהוספת הקובץ לאוסף"}
    
    def remove_file_from_collection(self, user_id: int, collection_id: str,
                                   file_id: str) -> bool:
        """
        הסרת קובץ מאוסף
        """
        try:
            collection_id_obj = ObjectId(collection_id)
            file_id_obj = ObjectId(file_id)
            
            # בדיקת הרשאות
            collection = self.collections_coll.find_one({
                "_id": collection_id_obj,
                "user_id": user_id
            })
            
            if not collection:
                return False
            
            # הסרת הקשר
            result = self.mappings_coll.delete_one({
                "collection_id": collection_id_obj,
                "file_id": file_id_obj
            })
            
            if result.deleted_count > 0:
                # עדכון מונה הקבצים
                self.collections_coll.update_one(
                    {"_id": collection_id_obj},
                    {
                        "$inc": {"files_count": -1},
                        "$set": {"updated_at": datetime.now(timezone.utc)}
                    }
                )
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error removing file from collection: {e}")
            return False
    
    def get_collection_files(self, user_id: int, collection_id: str,
                            limit: int = 100, skip: int = 0) -> Dict[str, Any]:
        """
        קבלת כל הקבצים באוסף
        """
        try:
            collection_id_obj = ObjectId(collection_id)
            
            # בדיקת הרשאות
            collection = self.collections_coll.find_one({
                "_id": collection_id_obj,
                "user_id": user_id
            })
            
            if not collection:
                return {"success": False, "files": [], "error": "האוסף לא נמצא"}
            
            # קבלת המיפויים
            mappings = list(self.mappings_coll.find({
                "collection_id": collection_id_obj
            }).sort("added_at", DESCENDING).skip(skip).limit(limit))
            
            # קבלת פרטי הקבצים
            file_ids = [m["file_id"] for m in mappings]
            files = list(self.files_coll.find({
                "_id": {"$in": file_ids}
            }))
            
            # יצירת מפה למיפוי מהיר
            files_dict = {str(f["_id"]): f for f in files}
            
            # בניית התוצאה עם שמירת סדר המיפויים
            result_files = []
            for mapping in mappings:
                file_id_str = str(mapping["file_id"])
                if file_id_str in files_dict:
                    file_doc = files_dict[file_id_str]
                    result_files.append({
                        "_id": file_id_str,
                        "file_name": file_doc.get("file_name", ""),
                        "programming_language": file_doc.get("programming_language", ""),
                        "size": len(file_doc.get("code", "").encode('utf-8')),
                        "added_to_collection": mapping["added_at"].isoformat(),
                        "created_at": file_doc.get("created_at", datetime.now(timezone.utc)).isoformat()
                    })
            
            return {
                "success": True,
                "collection": self._serialize_collection(collection),
                "files": result_files,
                "total": collection.get("files_count", 0)
            }
            
        except Exception as e:
            logger.error(f"Error getting collection files: {e}")
            return {"success": False, "files": [], "error": "שגיאה בטעינת קבצי האוסף"}
    
    def get_file_collections(self, user_id: int, file_id: str) -> List[Dict[str, Any]]:
        """
        קבלת כל האוספים שקובץ נמצא בהם
        """
        try:
            file_id_obj = ObjectId(file_id)
            
            # בדיקה שהקובץ שייך למשתמש
            file_doc = self.files_coll.find_one({
                "_id": file_id_obj,
                "user_id": user_id
            })
            
            if not file_doc:
                return []
            
            # קבלת כל המיפויים של הקובץ
            mappings = list(self.mappings_coll.find({
                "file_id": file_id_obj
            }))
            
            collection_ids = [m["collection_id"] for m in mappings]
            
            # קבלת פרטי האוספים
            collections = list(self.collections_coll.find({
                "_id": {"$in": collection_ids},
                "user_id": user_id  # בטיחות נוספת
            }))
            
            return [self._serialize_collection(c) for c in collections]
            
        except Exception as e:
            logger.error(f"Error getting file collections: {e}")
            return []
    
    def toggle_file_in_collections(self, user_id: int, file_id: str, 
                                  collection_ids: List[str]) -> Dict[str, Any]:
        """
        עדכון מלא של האוספים שקובץ נמצא בהם
        מסיר מאוספים שלא ברשימה ומוסיף לאוספים חדשים
        """
        try:
            file_id_obj = ObjectId(file_id)
            collection_ids_obj = [ObjectId(cid) for cid in collection_ids]
            
            # בדיקה שהקובץ שייך למשתמש
            file_doc = self.files_coll.find_one({
                "_id": file_id_obj,
                "user_id": user_id
            })
            
            if not file_doc:
                return {"success": False, "error": "הקובץ לא נמצא"}
            
            # קבלת האוספים הנוכחיים של הקובץ
            current_mappings = list(self.mappings_coll.find({
                "file_id": file_id_obj
            }))
            
            current_collection_ids = {m["collection_id"] for m in current_mappings}
            target_collection_ids = set(collection_ids_obj)
            
            # אוספים להסרה
            to_remove = current_collection_ids - target_collection_ids
            # אוספים להוספה
            to_add = target_collection_ids - current_collection_ids
            
            # הסרה מאוספים
            if to_remove:
                self.mappings_coll.delete_many({
                    "file_id": file_id_obj,
                    "collection_id": {"$in": list(to_remove)}
                })
                
                # עדכון מונים
                self.collections_coll.update_many(
                    {"_id": {"$in": list(to_remove)}},
                    {"$inc": {"files_count": -1}}
                )
            
            # הוספה לאוספים חדשים
            for coll_id in to_add:
                # בדיקה שהאוסף שייך למשתמש
                collection = self.collections_coll.find_one({
                    "_id": coll_id,
                    "user_id": user_id
                })
                
                if collection and collection.get("files_count", 0) < MAX_FILES_PER_COLLECTION:
                    try:
                        self.mappings_coll.insert_one({
                            "collection_id": coll_id,
                            "file_id": file_id_obj,
                            "user_id": user_id,
                            "added_at": datetime.now(timezone.utc)
                        })
                        
                        # עדכון מונה
                        self.collections_coll.update_one(
                            {"_id": coll_id},
                            {"$inc": {"files_count": 1}}
                        )
                    except DuplicateKeyError:
                        pass  # כבר קיים, נמשיך
            
            return {
                "success": True,
                "added": len(to_add),
                "removed": len(to_remove)
            }
            
        except Exception as e:
            logger.error(f"Error toggling file collections: {e}")
            return {"success": False, "error": "שגיאה בעדכון האוספים"}
    
    # ==================== סטטיסטיקות ====================
    
    def get_collections_stats(self, user_id: int) -> Dict[str, Any]:
        """
        קבלת סטטיסטיקות על האוספים
        """
        try:
            collections = list(self.collections_coll.find({"user_id": user_id}))
            
            total_collections = len(collections)
            total_files = sum(c.get("files_count", 0) for c in collections)
            favorite_count = sum(1 for c in collections if c.get("is_favorite", False))
            
            # אוסף הכי גדול
            largest = max(collections, key=lambda c: c.get("files_count", 0)) if collections else None
            
            # אוסף אחרון שעודכן
            latest = max(collections, key=lambda c: c.get("updated_at", datetime.min)) if collections else None
            
            return {
                "total_collections": total_collections,
                "total_files_in_collections": total_files,
                "favorite_collections": favorite_count,
                "largest_collection": self._serialize_collection(largest) if largest else None,
                "latest_updated": self._serialize_collection(latest) if latest else None,
                "remaining_collections": MAX_COLLECTIONS_PER_USER - total_collections
            }
            
        except Exception as e:
            logger.error(f"Error getting collections stats: {e}")
            return {}
    
    # ==================== עזרים פרטיים ====================
    
    def _serialize_collection(self, collection: Dict) -> Dict[str, Any]:
        """
        המרת מסמך אוסף לפורמט JSON-safe
        """
        if not collection:
            return None
            
        return {
            "_id": str(collection["_id"]),
            "name": collection.get("name", ""),
            "description": collection.get("description", ""),
            "icon": collection.get("icon", "📂"),
            "color": collection.get("color", "blue"),
            "files_count": collection.get("files_count", 0),
            "is_favorite": collection.get("is_favorite", False),
            "created_at": collection.get("created_at", datetime.now(timezone.utc)).isoformat(),
            "updated_at": collection.get("updated_at", datetime.now(timezone.utc)).isoformat()
        }
```

---

## 🔌 API Endpoints

צור קובץ `webapp/collections_api.py`:

```python
"""
Collections API Endpoints for WebApp
נקודות קצה לניהול אוספים של קבצים
"""
from flask import Blueprint, jsonify, request, session
from bson import ObjectId
from functools import wraps
from typing import Optional, Dict, List
import logging
import html

from database.collections_manager import CollectionsManager, ALLOWED_ICONS
from cache_manager import cache

logger = logging.getLogger(__name__)

# Blueprint
collections_bp = Blueprint('collections', __name__, url_prefix='/api/collections')

# ==================== Helpers ====================

def get_db():
    """Get database instance"""
    from webapp.app import get_db as _get_db
    return _get_db()

def get_collections_manager():
    """Get collections manager instance"""
    return CollectionsManager(get_db())

def require_auth(f):
    """Decorator to check if user is authenticated"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'success': False, 'error': 'Unauthorized'}), 401
        return f(*args, **kwargs)
    return decorated_function

# ==================== Collections CRUD ====================

@collections_bp.route('/', methods=['GET'])
@require_auth
def get_collections():
    """קבלת כל האוספים של המשתמש"""
    try:
        user_id = session['user_id']
        manager = get_collections_manager()
        collections = manager.get_user_collections(user_id)
        
        return jsonify({
            'success': True,
            'collections': collections
        })
        
    except Exception as e:
        logger.error(f"Error getting collections: {e}")
        return jsonify({'success': False, 'error': 'שגיאה בטעינת האוספים'}), 500

@collections_bp.route('/', methods=['POST'])
@require_auth
def create_collection():
    """יצירת אוסף חדש"""
    try:
        user_id = session['user_id']
        data = request.get_json()
        
        name = data.get('name', '').strip()
        if not name:
            return jsonify({'success': False, 'error': 'שם האוסף חסר'}), 400
        
        # וולידציה של אייקון
        icon = data.get('icon')
        if icon and icon not in ALLOWED_ICONS:
            icon = None  # יבחר אוטומטית במנג'ר
        
        manager = get_collections_manager()
        result = manager.create_collection(
            user_id=user_id,
            name=name,
            description=data.get('description', ''),
            icon=icon,
            color=data.get('color')
        )
        
        if result['success']:
            # נקה cache של המשתמש
            cache.invalidate_user_cache(user_id)
            return jsonify(result)
        else:
            return jsonify(result), 400
            
    except Exception as e:
        logger.error(f"Error creating collection: {e}")
        return jsonify({'success': False, 'error': 'שגיאה ביצירת האוסף'}), 500

@collections_bp.route('/<collection_id>', methods=['GET'])
@require_auth
def get_collection(collection_id):
    """קבלת פרטי אוסף ספציפי"""
    try:
        user_id = session['user_id']
        manager = get_collections_manager()
        collection = manager.get_collection(user_id, collection_id)
        
        if collection:
            return jsonify({
                'success': True,
                'collection': collection
            })
        else:
            return jsonify({'success': False, 'error': 'האוסף לא נמצא'}), 404
            
    except Exception as e:
        logger.error(f"Error getting collection: {e}")
        return jsonify({'success': False, 'error': 'שגיאה בטעינת האוסף'}), 500

@collections_bp.route('/<collection_id>', methods=['PUT'])
@require_auth
def update_collection(collection_id):
    """עדכון פרטי אוסף"""
    try:
        user_id = session['user_id']
        data = request.get_json()
        
        manager = get_collections_manager()
        success = manager.update_collection(
            user_id=user_id,
            collection_id=collection_id,
            name=data.get('name'),
            description=data.get('description'),
            icon=data.get('icon'),
            color=data.get('color'),
            is_favorite=data.get('is_favorite')
        )
        
        if success:
            # נקה cache
            cache.invalidate_user_cache(user_id)
            return jsonify({'success': True})
        else:
            return jsonify({'success': False, 'error': 'עדכון האוסף נכשל'}), 400
            
    except Exception as e:
        logger.error(f"Error updating collection: {e}")
        return jsonify({'success': False, 'error': 'שגיאה בעדכון האוסף'}), 500

@collections_bp.route('/<collection_id>', methods=['DELETE'])
@require_auth
def delete_collection(collection_id):
    """מחיקת אוסף"""
    try:
        user_id = session['user_id']
        manager = get_collections_manager()
        success = manager.delete_collection(user_id, collection_id)
        
        if success:
            # נקה cache
            cache.invalidate_user_cache(user_id)
            return jsonify({'success': True})
        else:
            return jsonify({'success': False, 'error': 'מחיקת האוסף נכשלה'}), 400
            
    except Exception as e:
        logger.error(f"Error deleting collection: {e}")
        return jsonify({'success': False, 'error': 'שגיאה במחיקת האוסף'}), 500

@collections_bp.route('/reorder', methods=['POST'])
@require_auth
def reorder_collections():
    """שינוי סדר האוספים"""
    try:
        user_id = session['user_id']
        data = request.get_json()
        collection_ids = data.get('collection_ids', [])
        
        manager = get_collections_manager()
        success = manager.reorder_collections(user_id, collection_ids)
        
        if success:
            cache.invalidate_user_cache(user_id)
            return jsonify({'success': True})
        else:
            return jsonify({'success': False, 'error': 'שינוי הסדר נכשל'}), 400
            
    except Exception as e:
        logger.error(f"Error reordering collections: {e}")
        return jsonify({'success': False, 'error': 'שגיאה בשינוי הסדר'}), 500

# ==================== Files in Collections ====================

@collections_bp.route('/<collection_id>/files', methods=['GET'])
@require_auth
def get_collection_files(collection_id):
    """קבלת קבצים באוסף"""
    try:
        user_id = session['user_id']
        limit = int(request.args.get('limit', 100))
        skip = int(request.args.get('skip', 0))
        
        manager = get_collections_manager()
        result = manager.get_collection_files(user_id, collection_id, limit, skip)
        
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"Error getting collection files: {e}")
        return jsonify({'success': False, 'error': 'שגיאה בטעינת הקבצים'}), 500

@collections_bp.route('/<collection_id>/files/<file_id>', methods=['POST'])
@require_auth
def add_file_to_collection(collection_id, file_id):
    """הוספת קובץ לאוסף"""
    try:
        user_id = session['user_id']
        manager = get_collections_manager()
        result = manager.add_file_to_collection(user_id, collection_id, file_id)
        
        if result['success']:
            return jsonify(result)
        else:
            return jsonify(result), 400
            
    except Exception as e:
        logger.error(f"Error adding file to collection: {e}")
        return jsonify({'success': False, 'error': 'שגיאה בהוספת הקובץ'}), 500

@collections_bp.route('/<collection_id>/files/<file_id>', methods=['DELETE'])
@require_auth
def remove_file_from_collection(collection_id, file_id):
    """הסרת קובץ מאוסף"""
    try:
        user_id = session['user_id']
        manager = get_collections_manager()
        success = manager.remove_file_from_collection(user_id, collection_id, file_id)
        
        if success:
            return jsonify({'success': True})
        else:
            return jsonify({'success': False, 'error': 'הסרת הקובץ נכשלה'}), 400
            
    except Exception as e:
        logger.error(f"Error removing file from collection: {e}")
        return jsonify({'success': False, 'error': 'שגיאה בהסרת הקובץ'}), 500

@collections_bp.route('/file/<file_id>', methods=['GET'])
@require_auth
def get_file_collections(file_id):
    """קבלת האוספים שקובץ נמצא בהם"""
    try:
        user_id = session['user_id']
        manager = get_collections_manager()
        collections = manager.get_file_collections(user_id, file_id)
        
        return jsonify({
            'success': True,
            'collections': collections
        })
        
    except Exception as e:
        logger.error(f"Error getting file collections: {e}")
        return jsonify({'success': False, 'error': 'שגיאה בטעינת האוספים'}), 500

@collections_bp.route('/file/<file_id>/toggle', methods=['POST'])
@require_auth
def toggle_file_collections(file_id):
    """עדכון האוספים של קובץ"""
    try:
        user_id = session['user_id']
        data = request.get_json()
        collection_ids = data.get('collection_ids', [])
        
        manager = get_collections_manager()
        result = manager.toggle_file_in_collections(user_id, file_id, collection_ids)
        
        if result['success']:
            return jsonify(result)
        else:
            return jsonify(result), 400
            
    except Exception as e:
        logger.error(f"Error toggling file collections: {e}")
        return jsonify({'success': False, 'error': 'שגיאה בעדכון האוספים'}), 500

@collections_bp.route('/stats', methods=['GET'])
@require_auth
def get_collections_stats():
    """קבלת סטטיסטיקות האוספים"""
    try:
        user_id = session['user_id']
        manager = get_collections_manager()
        stats = manager.get_collections_stats(user_id)
        
        return jsonify({
            'success': True,
            'stats': stats
        })
        
    except Exception as e:
        logger.error(f"Error getting collections stats: {e}")
        return jsonify({'success': False, 'error': 'שגיאה בטעינת הסטטיסטיקות'}), 500
```

### הוספה ל-`webapp/app.py`:

```python
# בתחילת הקובץ, אחרי ה-imports האחרים
from webapp.collections_api import collections_bp

# רישום ה-Blueprint (אחרי app.register_blueprint(bookmarks_bp))
app.register_blueprint(collections_bp)
```

---

## 🎨 ממשק משתמש (Frontend)

### 1. CSS לאוספים

צור קובץ `webapp/static/css/collections.css`:

```css
/* ==================== Collections Styles ==================== */

/* Sidebar Collections */
.sidebar-collections {
    padding: 1rem;
    border-top: 1px solid rgba(255, 255, 255, 0.1);
}

.sidebar-collections-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 1rem;
    padding: 0.5rem;
}

.sidebar-collections-title {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    font-weight: 600;
    font-size: 1.1rem;
    color: rgba(255, 255, 255, 0.9);
}

.sidebar-collections-add {
    background: rgba(255, 255, 255, 0.1);
    border: 1px solid rgba(255, 255, 255, 0.2);
    color: white;
    width: 28px;
    height: 28px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    transition: all 0.2s;
    font-size: 1.2rem;
}

.sidebar-collections-add:hover {
    background: rgba(255, 255, 255, 0.2);
    transform: scale(1.1);
}

.collections-list {
    max-height: 400px;
    overflow-y: auto;
    scrollbar-width: thin;
    scrollbar-color: rgba(255, 255, 255, 0.3) transparent;
}

.collections-list::-webkit-scrollbar {
    width: 6px;
}

.collections-list::-webkit-scrollbar-track {
    background: transparent;
}

.collections-list::-webkit-scrollbar-thumb {
    background: rgba(255, 255, 255, 0.3);
    border-radius: 3px;
}

.collection-item {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    padding: 0.75rem;
    margin-bottom: 0.5rem;
    background: rgba(255, 255, 255, 0.05);
    border-radius: 10px;
    cursor: pointer;
    transition: all 0.2s;
    position: relative;
    overflow: hidden;
}

.collection-item:hover {
    background: rgba(255, 255, 255, 0.1);
    transform: translateX(-5px);
}

.collection-item.active {
    background: rgba(255, 255, 255, 0.15);
    border-right: 3px solid var(--primary);
}

.collection-item-icon {
    font-size: 1.3rem;
    width: 32px;
    text-align: center;
}

.collection-item-info {
    flex: 1;
    min-width: 0;
}

.collection-item-name {
    font-weight: 500;
    color: rgba(255, 255, 255, 0.95);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    margin-bottom: 0.2rem;
}

.collection-item-count {
    font-size: 0.85rem;
    color: rgba(255, 255, 255, 0.6);
}

.collection-item-actions {
    display: flex;
    gap: 0.3rem;
    opacity: 0;
    transition: opacity 0.2s;
}

.collection-item:hover .collection-item-actions {
    opacity: 1;
}

.collection-action-btn {
    width: 24px;
    height: 24px;
    border-radius: 50%;
    background: rgba(255, 255, 255, 0.1);
    border: 1px solid rgba(255, 255, 255, 0.2);
    color: white;
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    transition: all 0.2s;
    font-size: 0.8rem;
}

.collection-action-btn:hover {
    background: rgba(255, 255, 255, 0.2);
}

/* Collection color indicators */
.collection-item.color-blue::before {
    content: '';
    position: absolute;
    top: 0;
    right: 0;
    bottom: 0;
    width: 3px;
    background: linear-gradient(180deg, #3182ce 0%, #2563eb 100%);
}

.collection-item.color-green::before {
    background: linear-gradient(180deg, #10b981 0%, #059669 100%);
}

.collection-item.color-purple::before {
    background: linear-gradient(180deg, #8b5cf6 0%, #7c3aed 100%);
}

.collection-item.color-orange::before {
    background: linear-gradient(180deg, #f97316 0%, #ea580c 100%);
}

.collection-item.color-red::before {
    background: linear-gradient(180deg, #ef4444 0%, #dc2626 100%);
}

.collection-item.color-teal::before {
    background: linear-gradient(180deg, #14b8a6 0%, #0d9488 100%);
}

.collection-item.color-pink::before {
    background: linear-gradient(180deg, #ec4899 0%, #db2777 100%);
}

.collection-item.color-yellow::before {
    background: linear-gradient(180deg, #eab308 0%, #ca8a04 100%);
}

/* Add to Collection Button */
.add-to-collection-btn {
    display: inline-flex;
    align-items: center;
    gap: 0.5rem;
    background: rgba(255, 255, 255, 0.1);
    border: 1px solid rgba(255, 255, 255, 0.2);
    color: white;
    padding: 0.5rem 1rem;
    border-radius: 8px;
    cursor: pointer;
    transition: all 0.2s;
    font-size: 0.9rem;
}

.add-to-collection-btn:hover {
    background: rgba(255, 255, 255, 0.15);
    transform: translateY(-2px);
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
}

/* Collections Modal */
.collections-modal {
    position: fixed;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    background: rgba(0, 0, 0, 0.7);
    backdrop-filter: blur(5px);
    display: none;
    align-items: center;
    justify-content: center;
    z-index: 10000;
    animation: fadeIn 0.2s ease;
}

.collections-modal.show {
    display: flex;
}

@keyframes fadeIn {
    from { opacity: 0; }
    to { opacity: 1; }
}

@keyframes slideUp {
    from {
        opacity: 0;
        transform: translateY(20px);
    }
    to {
        opacity: 1;
        transform: translateY(0);
    }
}

.collections-modal-content {
    background: linear-gradient(135deg, #2d4a7c 0%, #3d5a8c 100%);
    padding: 2rem;
    border-radius: 16px;
    max-width: 500px;
    width: 90%;
    max-height: 70vh;
    overflow-y: auto;
    box-shadow: 0 20px 60px rgba(0, 0, 0, 0.5);
    animation: slideUp 0.3s ease;
}

.collections-modal-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 1.5rem;
}

.collections-modal-title {
    font-size: 1.4rem;
    font-weight: 600;
    color: white;
    display: flex;
    align-items: center;
    gap: 0.5rem;
}

.collections-modal-close {
    background: rgba(255, 255, 255, 0.1);
    border: none;
    color: white;
    width: 32px;
    height: 32px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    transition: all 0.2s;
    font-size: 1.2rem;
}

.collections-modal-close:hover {
    background: rgba(255, 255, 255, 0.2);
    transform: rotate(90deg);
}

.collections-checkboxes {
    margin-bottom: 1.5rem;
    max-height: 300px;
    overflow-y: auto;
    padding-left: 0.5rem;
}

.collection-checkbox-item {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    padding: 0.75rem;
    margin-bottom: 0.5rem;
    background: rgba(255, 255, 255, 0.05);
    border-radius: 10px;
    cursor: pointer;
    transition: all 0.2s;
}

.collection-checkbox-item:hover {
    background: rgba(255, 255, 255, 0.1);
}

.collection-checkbox-item input[type="checkbox"] {
    width: 20px;
    height: 20px;
    accent-color: var(--primary);
    cursor: pointer;
}

.collection-checkbox-label {
    flex: 1;
    display: flex;
    align-items: center;
    gap: 0.5rem;
    cursor: pointer;
}

.collection-checkbox-icon {
    font-size: 1.2rem;
}

.collection-checkbox-name {
    color: rgba(255, 255, 255, 0.95);
    font-weight: 500;
}

.collection-checkbox-count {
    margin-right: auto;
    font-size: 0.85rem;
    color: rgba(255, 255, 255, 0.6);
}

/* Create New Collection Form */
.create-collection-form {
    margin-top: 1.5rem;
    padding-top: 1.5rem;
    border-top: 1px solid rgba(255, 255, 255, 0.1);
}

.create-collection-toggle {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    color: var(--primary);
    cursor: pointer;
    font-weight: 500;
    margin-bottom: 1rem;
}

.create-collection-fields {
    display: none;
}

.create-collection-fields.show {
    display: block;
    animation: slideDown 0.3s ease;
}

@keyframes slideDown {
    from {
        opacity: 0;
        max-height: 0;
    }
    to {
        opacity: 1;
        max-height: 300px;
    }
}

.form-group {
    margin-bottom: 1rem;
}

.form-group label {
    display: block;
    margin-bottom: 0.5rem;
    color: rgba(255, 255, 255, 0.9);
    font-size: 0.9rem;
    font-weight: 500;
}

.form-group input,
.form-group textarea {
    width: 100%;
    background: rgba(255, 255, 255, 0.1);
    border: 1px solid rgba(255, 255, 255, 0.2);
    border-radius: 8px;
    padding: 0.75rem;
    color: white;
    font-family: inherit;
}

.form-group input::placeholder,
.form-group textarea::placeholder {
    color: rgba(255, 255, 255, 0.5);
}

.form-group input:focus,
.form-group textarea:focus {
    outline: none;
    border-color: var(--primary);
    background: rgba(255, 255, 255, 0.15);
}

/* Icon Picker */
.icon-picker {
    display: flex;
    gap: 0.5rem;
    flex-wrap: wrap;
}

.icon-option {
    width: 40px;
    height: 40px;
    border-radius: 8px;
    background: rgba(255, 255, 255, 0.05);
    border: 2px solid transparent;
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    font-size: 1.4rem;
    transition: all 0.2s;
}

.icon-option:hover {
    background: rgba(255, 255, 255, 0.1);
}

.icon-option.selected {
    border-color: var(--primary);
    background: rgba(102, 126, 234, 0.2);
}

/* Color Picker */
.color-picker {
    display: flex;
    gap: 0.5rem;
    flex-wrap: wrap;
}

.color-option {
    width: 40px;
    height: 40px;
    border-radius: 8px;
    cursor: pointer;
    border: 2px solid transparent;
    transition: all 0.2s;
    position: relative;
}

.color-option:hover {
    transform: scale(1.1);
}

.color-option.selected {
    border-color: white;
}

.color-option.selected::after {
    content: '✓';
    position: absolute;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
    color: white;
    font-size: 1.2rem;
    font-weight: bold;
}

.color-option[data-color="blue"] {
    background: linear-gradient(135deg, #3182ce, #2563eb);
}

.color-option[data-color="green"] {
    background: linear-gradient(135deg, #10b981, #059669);
}

.color-option[data-color="purple"] {
    background: linear-gradient(135deg, #8b5cf6, #7c3aed);
}

.color-option[data-color="orange"] {
    background: linear-gradient(135deg, #f97316, #ea580c);
}

.color-option[data-color="red"] {
    background: linear-gradient(135deg, #ef4444, #dc2626);
}

.color-option[data-color="teal"] {
    background: linear-gradient(135deg, #14b8a6, #0d9488);
}

.color-option[data-color="pink"] {
    background: linear-gradient(135deg, #ec4899, #db2777);
}

.color-option[data-color="yellow"] {
    background: linear-gradient(135deg, #eab308, #ca8a04);
}

/* Modal Actions */
.collections-modal-actions {
    display: flex;
    gap: 0.75rem;
    justify-content: flex-end;
    margin-top: 1.5rem;
}

/* Collection View Page */
.collection-view-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 2rem;
    padding: 1.5rem;
    background: rgba(255, 255, 255, 0.05);
    border-radius: 12px;
}

.collection-info {
    display: flex;
    align-items: center;
    gap: 1rem;
}

.collection-icon-large {
    font-size: 3rem;
}

.collection-details h1 {
    margin: 0 0 0.5rem 0;
    font-size: 2rem;
}

.collection-meta {
    display: flex;
    gap: 1.5rem;
    color: rgba(255, 255, 255, 0.7);
}

.collection-actions {
    display: flex;
    gap: 0.75rem;
}

/* Files Grid in Collection */
.collection-files-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
    gap: 1.5rem;
}

.collection-file-card {
    background: rgba(255, 255, 255, 0.05);
    border-radius: 12px;
    padding: 1.5rem;
    transition: all 0.3s;
    cursor: pointer;
    position: relative;
}

.collection-file-card:hover {
    background: rgba(255, 255, 255, 0.1);
    transform: translateY(-4px);
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.2);
}

.remove-from-collection {
    position: absolute;
    top: 0.5rem;
    left: 0.5rem;
    width: 28px;
    height: 28px;
    border-radius: 50%;
    background: rgba(239, 68, 68, 0.2);
    border: 1px solid rgba(239, 68, 68, 0.4);
    color: #ef4444;
    display: none;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    transition: all 0.2s;
}

.collection-file-card:hover .remove-from-collection {
    display: flex;
}

.remove-from-collection:hover {
    background: rgba(239, 68, 68, 0.3);
    transform: scale(1.1);
}

/* Empty State */
.collection-empty-state {
    text-align: center;
    padding: 4rem 2rem;
    background: rgba(255, 255, 255, 0.03);
    border-radius: 12px;
    border: 2px dashed rgba(255, 255, 255, 0.1);
}

.collection-empty-icon {
    font-size: 4rem;
    margin-bottom: 1rem;
    opacity: 0.5;
}

.collection-empty-text {
    font-size: 1.2rem;
    color: rgba(255, 255, 255, 0.6);
    margin-bottom: 1.5rem;
}

.collection-empty-action {
    display: inline-flex;
    align-items: center;
    gap: 0.5rem;
    background: var(--primary);
    color: white;
    padding: 0.75rem 1.5rem;
    border-radius: 8px;
    text-decoration: none;
    transition: all 0.2s;
}

.collection-empty-action:hover {
    background: var(--primary-dark);
    transform: translateY(-2px);
}

/* Responsive */
@media (max-width: 768px) {
    .sidebar-collections {
        display: none;
    }
    
    .collections-modal-content {
        max-width: 95%;
        padding: 1.5rem;
    }
    
    .collection-files-grid {
        grid-template-columns: 1fr;
    }
}

/* Animations */
@keyframes pulse {
    0%, 100% {
        opacity: 1;
    }
    50% {
        opacity: 0.5;
    }
}

.loading-collections {
    animation: pulse 1.5s ease-in-out infinite;
}

/* Toast Notifications */
.collection-toast {
    position: fixed;
    bottom: 2rem;
    right: 2rem;
    background: linear-gradient(135deg, #10b981 0%, #059669 100%);
    color: white;
    padding: 1rem 1.5rem;
    border-radius: 12px;
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.3);
    display: flex;
    align-items: center;
    gap: 0.75rem;
    animation: slideInRight 0.3s ease;
    z-index: 10001;
}

@keyframes slideInRight {
    from {
        transform: translateX(100%);
        opacity: 0;
    }
    to {
        transform: translateX(0);
        opacity: 1;
    }
}

.collection-toast.error {
    background: linear-gradient(135deg, #ef4444 0%, #dc2626 100%);
}

.collection-toast-icon {
    font-size: 1.4rem;
}

.collection-toast-message {
    flex: 1;
}

.collection-toast-close {
    background: rgba(255, 255, 255, 0.2);
    border: none;
    color: white;
    width: 24px;
    height: 24px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    transition: all 0.2s;
}

.collection-toast-close:hover {
    background: rgba(255, 255, 255, 0.3);
}
```

### 2. JavaScript לניהול אוספים

צור קובץ `webapp/static/js/collections.js`:

```javascript
/**
 * Collections Manager for WebApp
 * מערכת ניהול אוספים של קבצים
 */

class CollectionsManager {
    constructor() {
        this.collections = [];
        this.currentFileId = null;
        this.api = new CollectionsAPI();
        this.ui = new CollectionsUI();
        
        this.init();
    }
    
    async init() {
        try {
            // טען אוספים
            await this.loadCollections();
            
            // הגדר event listeners
            this.setupEventListeners();
            
            // אם אנחנו בעמוד קובץ, טען את האוספים שלו
            const fileIdElement = document.querySelector('[data-file-id]');
            if (fileIdElement) {
                this.currentFileId = fileIdElement.getAttribute('data-file-id');
                await this.loadFileCollections();
            }
            
            console.log('CollectionsManager initialized');
            
        } catch (error) {
            console.error('Error initializing CollectionsManager:', error);
        }
    }
    
    setupEventListeners() {
        // כפתור הוספה לאוסף בקובץ
        const addToCollectionBtn = document.getElementById('addToCollectionBtn');
        if (addToCollectionBtn) {
            addToCollectionBtn.addEventListener('click', () => this.showCollectionsModal());
        }
        
        // כפתור יצירת אוסף חדש בסיידבר
        const createCollectionBtn = document.querySelector('.sidebar-collections-add');
        if (createCollectionBtn) {
            createCollectionBtn.addEventListener('click', () => this.showCreateCollectionModal());
        }
        
        // טופס יצירת אוסף במודל
        const toggleCreateForm = document.getElementById('toggleCreateCollection');
        if (toggleCreateForm) {
            toggleCreateForm.addEventListener('click', () => {
                const fields = document.getElementById('createCollectionFields');
                fields.classList.toggle('show');
            });
        }
        
        // סגירת מודל
        const closeModalBtns = document.querySelectorAll('.collections-modal-close');
        closeModalBtns.forEach(btn => {
            btn.addEventListener('click', () => this.closeModal());
        });
        
        // שמירת שינויים במודל
        const saveBtn = document.getElementById('saveCollectionsBtn');
        if (saveBtn) {
            saveBtn.addEventListener('click', () => this.saveFileCollections());
        }
        
        // בחירת אייקון
        const iconOptions = document.querySelectorAll('.icon-option');
        iconOptions.forEach(option => {
            option.addEventListener('click', (e) => {
                iconOptions.forEach(o => o.classList.remove('selected'));
                e.target.classList.add('selected');
            });
        });
        
        // בחירת צבע
        const colorOptions = document.querySelectorAll('.color-option');
        colorOptions.forEach(option => {
            option.addEventListener('click', (e) => {
                colorOptions.forEach(o => o.classList.remove('selected'));
                e.target.classList.add('selected');
            });
        });
    }
    
    async loadCollections() {
        try {
            const result = await this.api.getCollections();
            if (result.success) {
                this.collections = result.collections;
                this.ui.renderSidebarCollections(this.collections);
            }
        } catch (error) {
            console.error('Error loading collections:', error);
        }
    }
    
    async loadFileCollections() {
        if (!this.currentFileId) return;
        
        try {
            const result = await this.api.getFileCollections(this.currentFileId);
            if (result.success) {
                this.ui.updateFileCollectionsUI(result.collections);
            }
        } catch (error) {
            console.error('Error loading file collections:', error);
        }
    }
    
    showCollectionsModal() {
        this.ui.showModal('collections');
        this.ui.renderCollectionsCheckboxes(this.collections, this.currentFileId);
    }
    
    showCreateCollectionModal() {
        this.ui.showModal('create');
    }
    
    closeModal() {
        this.ui.closeModal();
    }
    
    async saveFileCollections() {
        if (!this.currentFileId) return;
        
        const selectedIds = this.ui.getSelectedCollectionIds();
        
        try {
            const result = await this.api.toggleFileCollections(this.currentFileId, selectedIds);
            if (result.success) {
                await this.loadFileCollections();
                await this.loadCollections(); // רענן מונים
                this.ui.showToast(`עודכנו ${result.added + result.removed} אוספים`, 'success');
                this.closeModal();
            } else {
                this.ui.showToast(result.error || 'שגיאה בעדכון האוספים', 'error');
            }
        } catch (error) {
            console.error('Error saving file collections:', error);
            this.ui.showToast('שגיאה בשמירת השינויים', 'error');
        }
    }
    
    async createCollection(data) {
        try {
            const result = await this.api.createCollection(data);
            if (result.success) {
                await this.loadCollections();
                this.ui.showToast('האוסף נוצר בהצלחה', 'success');
                
                // אם אנחנו במודל של קובץ, רענן את הרשימה
                if (this.currentFileId) {
                    this.ui.renderCollectionsCheckboxes(this.collections, this.currentFileId);
                }
                
                // נקה טופס
                this.ui.clearCreateForm();
                
                return result.collection;
            } else {
                this.ui.showToast(result.error || 'שגיאה ביצירת האוסף', 'error');
                return null;
            }
        } catch (error) {
            console.error('Error creating collection:', error);
            this.ui.showToast('שגיאה ביצירת האוסף', 'error');
            return null;
        }
    }
    
    async deleteCollection(collectionId) {
        if (!confirm('האם למחוק את האוסף? כל הקבצים יוסרו ממנו.')) {
            return;
        }
        
        try {
            const result = await this.api.deleteCollection(collectionId);
            if (result.success) {
                await this.loadCollections();
                this.ui.showToast('האוסף נמחק בהצלחה', 'success');
            } else {
                this.ui.showToast(result.error || 'שגיאה במחיקת האוסף', 'error');
            }
        } catch (error) {
            console.error('Error deleting collection:', error);
            this.ui.showToast('שגיאה במחיקת האוסף', 'error');
        }
    }
    
    async toggleFavorite(collectionId, currentState) {
        try {
            const result = await this.api.updateCollection(collectionId, {
                is_favorite: !currentState
            });
            
            if (result.success) {
                await this.loadCollections();
                this.ui.showToast(
                    !currentState ? 'האוסף הוגדר כמועדף' : 'האוסף הוסר מהמועדפים',
                    'success'
                );
            }
        } catch (error) {
            console.error('Error toggling favorite:', error);
            this.ui.showToast('שגיאה בעדכון המועדפים', 'error');
        }
    }
}

// API Class
class CollectionsAPI {
    constructor() {
        this.baseUrl = '/api/collections';
    }
    
    async request(method, endpoint, data = null) {
        const options = {
            method: method,
            headers: {
                'Content-Type': 'application/json'
            }
        };
        
        if (data) {
            options.body = JSON.stringify(data);
        }
        
        try {
            const response = await fetch(this.baseUrl + endpoint, options);
            return await response.json();
        } catch (error) {
            console.error('API request failed:', error);
            throw error;
        }
    }
    
    async getCollections() {
        return this.request('GET', '/');
    }
    
    async createCollection(data) {
        return this.request('POST', '/', data);
    }
    
    async updateCollection(collectionId, data) {
        return this.request('PUT', `/${collectionId}`, data);
    }
    
    async deleteCollection(collectionId) {
        return this.request('DELETE', `/${collectionId}`);
    }
    
    async getCollectionFiles(collectionId) {
        return this.request('GET', `/${collectionId}/files`);
    }
    
    async addFileToCollection(collectionId, fileId) {
        return this.request('POST', `/${collectionId}/files/${fileId}`);
    }
    
    async removeFileFromCollection(collectionId, fileId) {
        return this.request('DELETE', `/${collectionId}/files/${fileId}`);
    }
    
    async getFileCollections(fileId) {
        return this.request('GET', `/file/${fileId}`);
    }
    
    async toggleFileCollections(fileId, collectionIds) {
        return this.request('POST', `/file/${fileId}/toggle`, {
            collection_ids: collectionIds
        });
    }
    
    async getStats() {
        return this.request('GET', '/stats');
    }
}

// UI Class
class CollectionsUI {
    renderSidebarCollections(collections) {
        const container = document.getElementById('sidebarCollectionsList');
        if (!container) return;
        
        if (collections.length === 0) {
            container.innerHTML = '<p style="text-align: center; opacity: 0.6; padding: 1rem;">אין אוספים עדיין</p>';
            return;
        }
        
        container.innerHTML = collections.map(collection => `
            <div class="collection-item color-${this.escapeHtml(collection.color)}" 
                 data-collection-id="${this.escapeHtml(collection._id)}"
                 onclick="window.location.href='/collections/${this.escapeHtml(collection._id)}'">
                <span class="collection-item-icon">${this.escapeHtml(collection.icon)}</span>
                <div class="collection-item-info">
                    <div class="collection-item-name">${this.escapeHtml(collection.name)}</div>
                    <div class="collection-item-count">${collection.files_count} קבצים</div>
                </div>
                <div class="collection-item-actions">
                    ${collection.is_favorite 
                        ? '<button class="collection-action-btn" onclick="collectionsManager.toggleFavorite(\'' + this.escapeHtml(collection._id) + '\', true); event.stopPropagation();" title="הסר ממועדפים">⭐</button>'
                        : '<button class="collection-action-btn" onclick="collectionsManager.toggleFavorite(\'' + this.escapeHtml(collection._id) + '\', false); event.stopPropagation();" title="הוסף למועדפים">☆</button>'
                    }
                    <button class="collection-action-btn" 
                            onclick="collectionsManager.deleteCollection('${this.escapeHtml(collection._id)}'); event.stopPropagation();" 
                            title="מחק אוסף">🗑️</button>
                </div>
            </div>
        `).join('');
    }
    
    renderCollectionsCheckboxes(collections, fileId) {
        const container = document.getElementById('collectionsCheckboxes');
        if (!container) return;
        
        // קבל את האוספים הנוכחיים של הקובץ
        this.loadCurrentFileCollections(fileId).then(currentCollections => {
            const currentIds = currentCollections.map(c => c._id);
            
            container.innerHTML = collections.map(collection => `
                <div class="collection-checkbox-item">
                    <input type="checkbox" 
                           id="collection-${this.escapeHtml(collection._id)}"
                           value="${this.escapeHtml(collection._id)}"
                           ${currentIds.includes(collection._id) ? 'checked' : ''}>
                    <label for="collection-${this.escapeHtml(collection._id)}" class="collection-checkbox-label">
                        <span class="collection-checkbox-icon">${this.escapeHtml(collection.icon)}</span>
                        <span class="collection-checkbox-name">${this.escapeHtml(collection.name)}</span>
                        <span class="collection-checkbox-count">(${collection.files_count} קבצים)</span>
                    </label>
                </div>
            `).join('');
        });
    }
    
    async loadCurrentFileCollections(fileId) {
        try {
            const api = new CollectionsAPI();
            const result = await api.getFileCollections(fileId);
            return result.success ? result.collections : [];
        } catch (error) {
            console.error('Error loading current file collections:', error);
            return [];
        }
    }
    
    getSelectedCollectionIds() {
        const checkboxes = document.querySelectorAll('#collectionsCheckboxes input[type="checkbox"]:checked');
        return Array.from(checkboxes).map(cb => cb.value);
    }
    
    updateFileCollectionsUI(collections) {
        // עדכן תצוגת האוספים בעמוד הקובץ
        const indicator = document.getElementById('fileCollectionsIndicator');
        if (indicator) {
            if (collections.length > 0) {
                indicator.innerHTML = `
                    <span class="file-collections-badge">
                        📁 ${collections.length} אוספים
                    </span>
                `;
            } else {
                indicator.innerHTML = '';
            }
        }
    }
    
    showModal(type) {
        const modal = document.getElementById('collectionsModal');
        if (modal) {
            modal.classList.add('show');
            
            // הצג/הסתר אלמנטים לפי סוג המודל
            if (type === 'create') {
                document.getElementById('createCollectionFields').classList.add('show');
                document.getElementById('collectionsCheckboxes').style.display = 'none';
            } else {
                document.getElementById('createCollectionFields').classList.remove('show');
                document.getElementById('collectionsCheckboxes').style.display = 'block';
            }
        }
    }
    
    closeModal() {
        const modal = document.getElementById('collectionsModal');
        if (modal) {
            modal.classList.remove('show');
        }
    }
    
    clearCreateForm() {
        const form = document.getElementById('createCollectionForm');
        if (form) {
            form.reset();
            document.querySelectorAll('.icon-option.selected').forEach(el => {
                el.classList.remove('selected');
            });
            document.querySelectorAll('.color-option.selected').forEach(el => {
                el.classList.remove('selected');
            });
        }
    }
    
    showToast(message, type = 'success') {
        const toast = document.createElement('div');
        toast.className = `collection-toast ${type}`;
        toast.innerHTML = `
            <span class="collection-toast-icon">
                ${type === 'success' ? '✅' : '❌'}
            </span>
            <span class="collection-toast-message">${message}</span>
            <button class="collection-toast-close" onclick="this.parentElement.remove()">×</button>
        `;
        
        document.body.appendChild(toast);
        
        setTimeout(() => {
            toast.style.animation = 'slideOutRight 0.3s ease';
            setTimeout(() => toast.remove(), 300);
        }, 3000);
    }
    
    escapeHtml(text) {
        // פונקציה קריטית למניעת XSS - מחליפה תווים מסוכנים ב-HTML entities
        // חובה להשתמש בה על כל נתון שמגיע מהשרת לפני הכנסה ל-DOM
        if (text === null || text === undefined) {
            return '';
        }
        const str = String(text);
        const map = {
            '&': '&amp;',
            '<': '&lt;',
            '>': '&gt;',
            '"': '&quot;',
            "'": '&#039;'
        };
        return str.replace(/[&<>"']/g, m => map[m]);
    }
}

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    window.collectionsManager = new CollectionsManager();
});
```

### 3. הוספת HTML לתבניות

#### עדכון `webapp/templates/base.html`:

הוסף בתוך ה-sidebar (אחרי רשימת הקישורים הראשית):

```html
<!-- Collections Section -->
<div class="sidebar-collections">
    <div class="sidebar-collections-header">
        <div class="sidebar-collections-title">
            ⭐ האוספים שלי
        </div>
        <button class="sidebar-collections-add" title="צור אוסף חדש">
            ➕
        </button>
    </div>
    <div class="collections-list" id="sidebarCollectionsList">
        <p style="text-align: center; opacity: 0.6; padding: 1rem;">
            טוען אוספים...
        </p>
    </div>
</div>

<!-- Collections Modal -->
<div class="collections-modal" id="collectionsModal">
    <div class="collections-modal-content">
        <div class="collections-modal-header">
            <h3 class="collections-modal-title">
                📁 הוסף לאוסף
            </h3>
            <button class="collections-modal-close">×</button>
        </div>
        
        <!-- Collections Checkboxes -->
        <div class="collections-checkboxes" id="collectionsCheckboxes">
            <!-- Dynamic content -->
        </div>
        
        <!-- Create New Collection -->
        <div class="create-collection-form">
            <div class="create-collection-toggle" id="toggleCreateCollection">
                ➕ צור אוסף חדש
            </div>
            
            <div class="create-collection-fields" id="createCollectionFields">
                <form id="createCollectionForm">
                    <div class="form-group">
                        <label for="collectionName">שם האוסף</label>
                        <input type="text" id="collectionName" placeholder="למשל: מדריכי קוד" required>
                    </div>
                    
                    <div class="form-group">
                        <label for="collectionDescription">תיאור (אופציונלי)</label>
                        <textarea id="collectionDescription" rows="2" placeholder="תיאור קצר של האוסף..."></textarea>
                    </div>
                    
                    <div class="form-group">
                        <label>אייקון</label>
                        <div class="icon-picker">
                            <span class="icon-option selected" data-icon="📂">📂</span>
                            <span class="icon-option" data-icon="📘">📘</span>
                            <span class="icon-option" data-icon="🎨">🎨</span>
                            <span class="icon-option" data-icon="🧩">🧩</span>
                            <span class="icon-option" data-icon="🐛">🐛</span>
                            <span class="icon-option" data-icon="⚙️">⚙️</span>
                            <span class="icon-option" data-icon="📝">📝</span>
                            <span class="icon-option" data-icon="🧪">🧪</span>
                            <span class="icon-option" data-icon="💡">💡</span>
                        </div>
                    </div>
                    
                    <div class="form-group">
                        <label>צבע</label>
                        <div class="color-picker">
                            <span class="color-option selected" data-color="blue"></span>
                            <span class="color-option" data-color="green"></span>
                            <span class="color-option" data-color="purple"></span>
                            <span class="color-option" data-color="orange"></span>
                            <span class="color-option" data-color="red"></span>
                            <span class="color-option" data-color="teal"></span>
                            <span class="color-option" data-color="pink"></span>
                            <span class="color-option" data-color="yellow"></span>
                        </div>
                    </div>
                </form>
            </div>
        </div>
        
        <div class="collections-modal-actions">
            <button class="btn btn-secondary" onclick="collectionsManager.closeModal()">
                ביטול
            </button>
            <button class="btn btn-primary" id="saveCollectionsBtn">
                שמור שינויים
            </button>
        </div>
    </div>
</div>

<!-- Add CSS and JS -->
<link rel="stylesheet" href="{{ url_for('static', filename='css/collections.css') }}">
<script src="{{ url_for('static', filename='js/collections.js') }}"></script>
```

#### עדכון `webapp/templates/view_file.html`:

הוסף כפתור "הוסף לאוסף" בכותרת הקובץ:

```html
<!-- בתוך אזור הכותרת, אחרי שם הקובץ -->
<div class="file-actions" style="display: flex; gap: 1rem; margin-top: 1rem;">
    <button id="addToCollectionBtn" class="add-to-collection-btn" data-file-id="{{ file.id }}">
        📁 הוסף לאוסף
    </button>
    
    <!-- אינדיקטור אוספים -->
    <div id="fileCollectionsIndicator"></div>
    
    <!-- כפתורים קיימים אחרים... -->
</div>
```

---

## 🚀 הוראות הטמעה

### שלב 1: יצירת קבצי Backend
1. צור את `database/collections_manager.py`
2. צור את `webapp/collections_api.py`
3. עדכן את `webapp/app.py` להוספת ה-Blueprint

### שלב 2: יצירת קבצי Frontend
1. צור את `webapp/static/css/collections.css`
2. צור את `webapp/static/js/collections.js`

### שלב 3: עדכון תבניות HTML
1. עדכן את `webapp/templates/base.html`
2. עדכן את `webapp/templates/view_file.html`
3. (אופציונלי) צור עמוד תצוגת אוסף `webapp/templates/collection.html`

### שלב 4: בדיקות
1. הפעל את האפליקציה
2. בדוק יצירת אוסף חדש
3. בדוק הוספת קבצים לאוספים
4. בדוק ניווט ותצוגה

---

## 📊 סכמת מסד נתונים

### Collection: `user_collections`
```json
{
  "_id": ObjectId,
  "user_id": Integer,
  "name": String,
  "description": String,
  "icon": String,
  "color": String,
  "files_count": Integer,
  "is_favorite": Boolean,
  "sort_order": Integer,
  "created_at": DateTime,
  "updated_at": DateTime
}
```

### Collection: `collection_files`
```json
{
  "_id": ObjectId,
  "collection_id": ObjectId,
  "file_id": ObjectId,
  "user_id": Integer,
  "added_at": DateTime
}
```

---

## ✅ רשימת בדיקות

### פונקציונליות בסיסית
- [ ] יצירת אוסף חדש
- [ ] עריכת שם ותיאור אוסף
- [ ] מחיקת אוסף
- [ ] הוספת קובץ לאוסף
- [ ] הסרת קובץ מאוסף
- [ ] הצגת קבצים באוסף
- [ ] הצגת אוספים בסיידבר

### פונקציונליות מתקדמת
- [ ] קובץ במספר אוספים
- [ ] סימון אוספים כמועדפים
- [ ] שינוי סדר אוספים
- [ ] חיפוש בתוך אוסף
- [ ] סטטיסטיקות אוספים

### ממשק משתמש
- [ ] אנימציות חלקות
- [ ] תמיכה במובייל
- [ ] הודעות Toast
- [ ] עיצוב אחיד עם האפליקציה

### ביצועים ואבטחה
- [ ] אינדקסים ב-MongoDB
- [ ] הרשאות משתמש
- [ ] מגבלות על מספר אוספים וקבצים
- [ ] Cache לביצועים

---

## 🎯 הרחבות עתידיות

1. **שיתוף אוספים**: אפשרות לשתף אוסף עם משתמשים אחרים
2. **תגיות**: הוספת תגיות לאוספים לסינון מתקדם
3. **תבניות אוספים**: תבניות מוכנות לסוגי אוספים נפוצים
4. **ייצוא/ייבוא**: ייצוא אוסף כ-ZIP או ייבוא קבצים מרובים
5. **אוטומציה**: יצירת אוספים אוטומטית לפי כללים (תאריך, שפה, גודל)
6. **תצוגות מתקדמות**: תצוגת גלריה, תצוגת טבלה, תצוגת זמן
7. **חיפוש חכם**: חיפוש בתוכן כל הקבצים באוסף
8. **גיבוי אוטומטי**: גיבוי אוספים חשובים

---

## 📝 הערות חשובות

1. **תאימות לאחור**: הפיצ'ר לא משפיע על הפונקציונליות הקיימת
2. **מגבלות**: הגבלנו ל-50 אוספים למשתמש ו-200 קבצים לאוסף למניעת עומס
3. **ביצועים**: השתמשנו באינדקסים וב-caching לביצועים אופטימליים
4. **עיצוב**: העיצוב תואם לנושאים הקיימים (classic, ocean, forest)
5. **נגישות**: כל הפעולות נגישות גם במקלדת

## 🔐 סיכום שיפורי אבטחה שבוצעו

1. **תיקון Cache API**: שימוש ב-`cache.invalidate_user_cache()` במקום הפונקציה הלא קיימת `delete_memoized`
2. **מניעת Stored XSS באייקונים**:
   - הגדרת whitelist של אייקונים מותרים (`ALLOWED_ICONS`)
   - וולידציה בצד שרת לפני שמירה
   - Escape של כל הנתונים בצד לקוח לפני הכנסה ל-DOM
3. **Escape כללי**: שימוש בפונקציית `escapeHtml()` על כל הנתונים המוצגים בממשק

---

## 🤝 תמיכה

במידה ונתקלתם בבעיות או יש לכם שאלות:
1. בדקו את הלוגים ב-`webapp/logs/`
2. וודאו שכל התלויות מותקנות
3. בדקו את האינדקסים ב-MongoDB
4. צרו Issue ב-GitHub עם תיאור מפורט

**בהצלחה במימוש! 🚀**