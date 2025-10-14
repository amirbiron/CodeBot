"""
Bookmarks Manager - מנהל סימניות לקבצי קוד
"""
import hashlib
import re
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional, Tuple
from difflib import SequenceMatcher
from bson import ObjectId
from pymongo import ASCENDING, DESCENDING, IndexModel
from pymongo.errors import DuplicateKeyError, BulkWriteError

from database.bookmark import (
    FileBookmark, 
    MAX_BOOKMARKS_PER_FILE, 
    MAX_BOOKMARKS_PER_USER,
    MAX_NOTE_LENGTH,
    VALID_COLORS
)

logger = logging.getLogger(__name__)


class BookmarksManager:
    """מנהל סימניות בקבצים"""
    
    def __init__(self, db):
        """
        Initialize bookmarks manager
        
        Args:
            db: MongoDB database instance
        """
        self.db = db
        self.collection = db.file_bookmarks
        self.events_collection = db.bookmark_events
        # בקוד היישום קטעי הקוד נשמרים באוסף code_snippets (לא files)
        # שומרים תאימות לאחור במקרה נדיר של 'files'
        try:
            self.files_collection = db.code_snippets
        except Exception:
            self.files_collection = getattr(db, 'code_snippets', db.files)
        
        # יצירת indexes
        self._ensure_indexes()
    
    def _ensure_indexes(self):
        """יצירת אינדקסים לביצועים מיטביים"""
        try:
            indexes = [
                # אינדקס ייחודי למניעת כפילויות
                IndexModel(
                    [("user_id", ASCENDING), ("file_id", ASCENDING), ("line_number", ASCENDING)],
                    unique=True,
                    name="unique_user_file_line"
                ),
                # אינדקס לחיפוש מהיר לפי משתמש וקובץ
                IndexModel(
                    [("user_id", ASCENDING), ("file_id", ASCENDING)],
                    name="user_file_lookup"
                ),
                # אינדקס לחיפוש לפי משתמש בלבד
                IndexModel(
                    [("user_id", ASCENDING), ("created_at", DESCENDING)],
                    name="user_recent_bookmarks"
                ),
                # אינדקס לחיפוש טקסט בהערות
                IndexModel(
                    [("note", "text")],
                    name="note_text_search"
                ),
                # TTL index למחיקה אוטומטית של סימניות ישנות (אופציונלי - שנה)
                # IndexModel(
                #     "created_at",
                #     expireAfterSeconds=31536000,  # שנה בשניות
                #     name="ttl_old_bookmarks"
                # )
            ]
            
            self.collection.create_indexes(indexes)
            logger.info("Bookmarks indexes created successfully")
            
        except Exception as e:
            logger.warning(f"Failed to create some bookmarks indexes: {e}")
    
    # ==================== CRUD Operations ====================
    
    def toggle_bookmark(self, 
                       user_id: int,
                       file_id: str,
                       file_name: str,
                       file_path: str,
                       line_number: int,
                       line_text: str = "",
                       note: str = "",
                       color: str = "yellow") -> Dict[str, Any]:
        """
        הוספה/הסרה של סימנייה (toggle)
        
        Returns:
            dict: {
                "ok": bool,
                "action": "added" | "removed" | "error",
                "bookmark": dict | None,
                "error": str | None
            }
        """
        try:
            # ולידציה
            if line_number <= 0:
                return {"ok": False, "action": "error", "error": "מספר שורה לא תקין"}
            
            if len(note) > MAX_NOTE_LENGTH:
                note = note[:MAX_NOTE_LENGTH]
            
            # בדיקה אם הסימנייה קיימת
            existing = self.collection.find_one({
                "user_id": user_id,
                "file_id": file_id,
                "line_number": line_number
            })
            
            if existing:
                # הסרת סימנייה קיימת
                self.collection.delete_one({"_id": existing["_id"]})
                self._track_event(user_id, "removed", file_id, line_number)
                
                return {
                    "ok": True,
                    "action": "removed",
                    "bookmark": None
                }
            
            # בדיקת הגבלות לפני הוספה
            limits_check = self._check_limits(user_id, file_id)
            if not limits_check["ok"]:
                return {
                    "ok": False,
                    "action": "error",
                    "error": limits_check["error"]
                }
            
            # חישוב hash של הקובץ
            file_hash = self._calculate_file_hash(file_id)
            
            # יצירת סימנייה חדשה
            bookmark = FileBookmark(
                user_id=user_id,
                file_id=file_id,
                file_name=file_name,
                file_path=file_path,
                line_number=line_number,
                line_text_preview=line_text[:100] if line_text else "",
                note=note,
                color=color,
                file_hash=file_hash
            )
            
            # שמירה ב-DB
            result = self.collection.insert_one(bookmark.to_dict())
            bookmark._id = result.inserted_id
            
            # מעקב אירועים
            self._track_event(user_id, "added", file_id, line_number, {"note_length": len(note)})
            
            return {
                "ok": True,
                "action": "added",
                "bookmark": self._bookmark_to_response(bookmark)
            }
            
        except DuplicateKeyError:
            # במקרה של race condition
            return {
                "ok": False,
                "action": "error",
                "error": "הסימנייה כבר קיימת"
            }
        except Exception as e:
            logger.error(f"Error toggling bookmark: {e}", exc_info=True)
            return {
                "ok": False,
                "action": "error",
                "error": "שגיאה בשמירת הסימנייה"
            }
    
    def get_file_bookmarks(self, 
                          user_id: int, 
                          file_id: str,
                          include_invalid: bool = False) -> List[Dict[str, Any]]:
        """
        קבלת כל הסימניות של קובץ מסוים
        
        Args:
            user_id: מזהה המשתמש
            file_id: מזהה הקובץ
            include_invalid: האם לכלול סימניות לא תקפות
            
        Returns:
            רשימת סימניות ממוינות לפי מספר שורה
        """
        try:
            query = {
                "user_id": user_id,
                "file_id": file_id
            }
            
            if not include_invalid:
                query["valid"] = {"$ne": False}
            
            bookmarks = list(self.collection.find(query).sort("line_number", 1))
            
            # עדכון last_accessed
            if bookmarks:
                bookmark_ids = [b["_id"] for b in bookmarks]
                self.collection.update_many(
                    {"_id": {"$in": bookmark_ids}},
                    {"$set": {"last_accessed": datetime.now(timezone.utc)}}
                )
            
            return [self._bookmark_to_response(FileBookmark.from_dict(b)) for b in bookmarks]
            
        except Exception as e:
            logger.error(f"Error getting file bookmarks: {e}")
            return []
    
    def get_user_bookmarks(self,
                          user_id: int,
                          limit: int = 100,
                          skip: int = 0) -> Dict[str, Any]:
        """
        קבלת כל הסימניות של משתמש
        
        Returns:
            dict עם סימניות מקובצות לפי קבצים
        """
        try:
            # אגרגציה לקיבוץ לפי קבצים
            pipeline = [
                {"$match": {"user_id": user_id, "valid": {"$ne": False}}},
                {"$sort": {"created_at": -1}},
                {"$skip": skip},
                {"$limit": limit},
                {"$group": {
                    "_id": {
                        "file_id": "$file_id",
                        "file_name": "$file_name",
                        "file_path": "$file_path"
                    },
                    "bookmarks": {"$push": {
                        "line_number": "$line_number",
                        "note": "$note",
                        "color": "$color",
                        "created_at": "$created_at"
                    }},
                    "count": {"$sum": 1}
                }},
                {"$sort": {"count": -1}}
            ]
            
            result = list(self.collection.aggregate(pipeline))
            
            # עיבוד התוצאות
            files = []
            for item in result:
                files.append({
                    "file_id": item["_id"]["file_id"],
                    "file_name": item["_id"]["file_name"],
                    "file_path": item["_id"]["file_path"],
                    "bookmarks": sorted(item["bookmarks"], key=lambda x: x["line_number"]),
                    "count": item["count"]
                })
            
            # סטטיסטיקות כלליות
            total_count = self.collection.count_documents({"user_id": user_id})
            
            return {
                "ok": True,
                "files": files,
                "total_bookmarks": total_count,
                "files_count": len(files)
            }
            
        except Exception as e:
            logger.error(f"Error getting user bookmarks: {e}")
            return {
                "ok": False,
                "error": str(e),
                "files": []
            }
    
    def update_bookmark_note(self,
                            user_id: int,
                            file_id: str,
                            line_number: int,
                            note: str) -> Dict[str, Any]:
        """עדכון הערה של סימנייה"""
        try:
            if len(note) > MAX_NOTE_LENGTH:
                note = note[:MAX_NOTE_LENGTH]
            
            result = self.collection.update_one(
                {
                    "user_id": user_id,
                    "file_id": file_id,
                    "line_number": line_number
                },
                {
                    "$set": {
                        "note": note,
                        "updated_at": datetime.now(timezone.utc)
                    }
                }
            )
            
            if result.modified_count > 0:
                self._track_event(user_id, "note_updated", file_id, line_number)
                return {"ok": True, "message": "ההערה עודכנה"}
            else:
                return {"ok": False, "error": "הסימנייה לא נמצאה"}
                
        except Exception as e:
            logger.error(f"Error updating bookmark note: {e}")
            return {"ok": False, "error": "שגיאה בעדכון ההערה"}

    def update_bookmark_color(self,
                              user_id: int,
                              file_id: str,
                              line_number: int,
                              color: str) -> Dict[str, Any]:
        """עדכון צבע של סימנייה קיימת"""
        try:
            color_norm = (color or '').lower()
            if color_norm not in VALID_COLORS:
                return {"ok": False, "error": "צבע לא תקין"}

            result = self.collection.update_one(
                {
                    "user_id": user_id,
                    "file_id": file_id,
                    "line_number": line_number
                },
                {
                    "$set": {
                        "color": color_norm,
                        "updated_at": datetime.now(timezone.utc)
                    }
                }
            )

            if result.modified_count > 0:
                self._track_event(user_id, "color_updated", file_id, line_number, {"color": color_norm})
                return {"ok": True, "message": "הצבע עודכן", "color": color_norm}
            else:
                return {"ok": False, "error": "הסימנייה לא נמצאה"}
        except Exception as e:
            logger.error(f"Error updating bookmark color: {e}")
            return {"ok": False, "error": "שגיאה בעדכון הצבע"}
    
    def delete_bookmark(self,
                       user_id: int,
                       file_id: str,
                       line_number: int) -> Dict[str, Any]:
        """מחיקת סימנייה ספציפית"""
        try:
            result = self.collection.delete_one({
                "user_id": user_id,
                "file_id": file_id,
                "line_number": line_number
            })
            
            if result.deleted_count > 0:
                self._track_event(user_id, "deleted", file_id, line_number)
                return {"ok": True, "message": "הסימנייה נמחקה"}
            else:
                return {"ok": False, "error": "הסימנייה לא נמצאה"}
                
        except Exception as e:
            logger.error(f"Error deleting bookmark: {e}")
            return {"ok": False, "error": "שגיאה במחיקת הסימנייה"}
    
    def delete_file_bookmarks(self, user_id: int, file_id: str) -> Dict[str, Any]:
        """מחיקת כל הסימניות של קובץ"""
        try:
            result = self.collection.delete_many({
                "user_id": user_id,
                "file_id": file_id
            })
            
            if result.deleted_count > 0:
                self._track_event(user_id, "file_cleared", file_id, metadata={"count": result.deleted_count})
                return {"ok": True, "deleted": result.deleted_count}
            else:
                return {"ok": True, "deleted": 0}
                
        except Exception as e:
            logger.error(f"Error deleting file bookmarks: {e}")
            return {"ok": False, "error": "שגיאה במחיקת הסימניות"}
    
    # ==================== Sync Operations ====================
    
    def check_file_sync(self, 
                       file_id: str,
                       new_content: str) -> Dict[str, Any]:
        """
        בדיקת סנכרון סימניות עם שינויים בקובץ
        
        Returns:
            מידע על סימניות שהושפעו משינויים
        """
        try:
            # חישוב hash חדש
            new_hash = hashlib.sha256(new_content.encode()).hexdigest()
            
            # קבלת hash קודם
            file_doc = self.files_collection.find_one({"_id": ObjectId(file_id)})
            old_hash = file_doc.get("content_hash") if file_doc else None
            
            if old_hash == new_hash:
                return {"changed": False, "affected": []}
            
            # ניתוח השפעה על סימניות
            content_str = ""
            if file_doc:
                # תמיכה גם בשמות שדות שונים
                content_str = (
                    file_doc.get("code")
                    or file_doc.get("content")
                    or ""
                )
            old_lines = content_str.splitlines()
            new_lines = new_content.splitlines()
            
            affected = self._analyze_bookmark_changes(file_id, old_lines, new_lines)
            
            # עדכון hash בקובץ
            self.files_collection.update_one(
                {"_id": ObjectId(file_id)},
                {"$set": {
                    "content_hash": new_hash,
                    # שדה התוכן באוסף code_snippets נקרא 'code'
                    "code": new_content,
                    "last_sync": datetime.now(timezone.utc)
                }}
            )
            
            return {
                "changed": True,
                "old_hash": old_hash,
                "new_hash": new_hash,
                "affected": affected
            }
            
        except Exception as e:
            logger.error(f"Error checking file sync: {e}")
            return {"changed": False, "error": str(e)}
    
    def _analyze_bookmark_changes(self,
                                 file_id: str,
                                 old_lines: List[str],
                                 new_lines: List[str]) -> List[Dict[str, Any]]:
        """ניתוח השפעת שינויים על סימניות"""
        
        matcher = SequenceMatcher(None, old_lines, new_lines)
        bookmarks = list(self.collection.find({"file_id": file_id}))
        affected = []
        
        for bookmark in bookmarks:
            line_num = bookmark["line_number"]
            old_text = bookmark.get("line_text_preview", "")
            
            # בדיקת סטטוס השורה
            status = self._check_line_status(line_num, old_text, new_lines, matcher)
            
            if status["needs_update"]:
                affected.append({
                    "bookmark_id": str(bookmark["_id"]),
                    "user_id": bookmark["user_id"],
                    "old_line": line_num,
                    "new_line": status.get("new_line"),
                    "status": status["status"],
                    "confidence": status.get("confidence", 0)
                })
                
                # עדכון הסימנייה ב-DB
                self._update_bookmark_sync_status(
                    bookmark["_id"],
                    status
                )
        
        return affected
    
    def _check_line_status(self,
                          line_num: int,
                          old_text: str,
                          new_lines: List[str],
                          matcher: SequenceMatcher) -> Dict[str, Any]:
        """בדיקת סטטוס של שורה ספציפית"""
        
        # ספי דמיון
        SIMILARITY_MODIFIED_THRESHOLD = 0.7
        SIMILARITY_MOVED_THRESHOLD = 0.7

        # בדיקה אם השורה עדיין קיימת באותו מקום
        if 0 < line_num <= len(new_lines):
            new_text = new_lines[line_num - 1]
            
            # השורה לא השתנתה
            if old_text in new_text or new_text in old_text:
                return {"needs_update": False}
            
            # בדיקת "def <name>" בפייתון: אם שמות הפונקציות שונים לגמרי,
            # לא נסווג כ"modified" רק על בסיס דמיון טקסט כללי.
            try:
                old_def = re.match(r"\s*def\s+([A-Za-z_][\w]*)", old_text or "")
                new_def = re.match(r"\s*def\s+([A-Za-z_][\w]*)", new_text or "")
                if old_def and new_def:
                    old_name = old_def.group(1)
                    new_name = new_def.group(1)
                    names_close = (old_name == new_name) or old_name in new_name or new_name in old_name
                else:
                    names_close = True
            except Exception:
                names_close = True

            # השורה השתנתה מעט
            similarity = SequenceMatcher(None, old_text, new_text).ratio()
            if names_close and similarity >= SIMILARITY_MODIFIED_THRESHOLD:
                return {
                    "needs_update": True,
                    "status": "modified",
                    "new_line": line_num,
                    "confidence": similarity
                }
            # אם לא מספיק דומה במקום המקורי, נבדוק האם קיימת התאמה חזקה במקום אחר
            for i, candidate in enumerate(new_lines, 1):
                if i == line_num:
                    continue
                sim_other = SequenceMatcher(None, old_text, candidate).ratio()
                if sim_other >= SIMILARITY_MOVED_THRESHOLD:
                    return {
                        "needs_update": True,
                        "status": "moved",
                        "new_line": i,
                        "confidence": sim_other
                    }
        
        # חיפוש השורה במקום אחר
        best_match = None
        best_similarity = SIMILARITY_MOVED_THRESHOLD
        
        for i, new_line in enumerate(new_lines, 1):
            similarity = SequenceMatcher(None, old_text, new_line).ratio()
            if similarity > best_similarity:
                best_similarity = similarity
                best_match = i
        
        if best_match:
            # אם נמצא match במקום אחר, אך שם הפונקציה שונה לגמרי — העדף 'deleted'
            try:
                old_def = re.match(r"\s*def\s+([A-Za-z_][\w]*)", old_text or "")
                new_def = re.match(r"\s*def\s+([A-Za-z_][\w]*)", new_lines[best_match - 1] or "")
                if old_def and new_def:
                    old_name = old_def.group(1)
                    new_name = new_def.group(1)
                    names_far = (old_name != new_name) and (old_name not in new_name) and (new_name not in old_name)
                    if names_far:
                        return {
                            "needs_update": True,
                            "status": "deleted",
                            "new_line": None,
                            "confidence": 0
                        }
            except Exception:
                pass
            return {
                "needs_update": True,
                "status": "moved",
                "new_line": best_match,
                "confidence": best_similarity
            }
        
        # השורה נמחקה
        return {
            "needs_update": True,
            "status": "deleted",
            "new_line": None,
            "confidence": 0
        }
    
    def _update_bookmark_sync_status(self,
                                    bookmark_id: ObjectId,
                                    status: Dict[str, Any]):
        """עדכון סטטוס סנכרון של סימנייה"""
        
        update_data = {
            "sync_status": status["status"],
            "sync_confidence": status.get("confidence", 0),
            "updated_at": datetime.now(timezone.utc)
        }
        
        if status["status"] == "deleted":
            update_data["valid"] = False
        elif status["status"] in ["moved", "modified"]:
            if status.get("new_line"):
                update_data["line_number"] = status["new_line"]
        
        self.collection.update_one(
            {"_id": bookmark_id},
            {"$set": update_data}
        )
    
    # ==================== Helper Methods ====================
    
    def _check_limits(self, user_id: int, file_id: str) -> Dict[str, Any]:
        """בדיקת הגבלות לפני הוספת סימנייה"""
        
        # בדיקת מגבלה לקובץ
        file_count = self.collection.count_documents({
            "user_id": user_id,
            "file_id": file_id
        })
        
        if file_count >= MAX_BOOKMARKS_PER_FILE:
            return {
                "ok": False,
                "error": f"הגעת למגבלה של {MAX_BOOKMARKS_PER_FILE} סימניות לקובץ"
            }
        
        # בדיקת מגבלה כללית
        total_count = self.collection.count_documents({"user_id": user_id})
        
        if total_count >= MAX_BOOKMARKS_PER_USER:
            return {
                "ok": False,
                "error": f"הגעת למגבלה של {MAX_BOOKMARKS_PER_USER} סימניות סך הכל"
            }
        
        return {"ok": True}
    
    def _calculate_file_hash(self, file_id: str) -> str:
        """חישוב hash של תוכן הקובץ"""
        try:
            file_doc = self.files_collection.find_one({"_id": ObjectId(file_id)})
            if file_doc:
                text = file_doc.get("code") or file_doc.get("content")
                if isinstance(text, str):
                    return hashlib.sha256(text.encode()).hexdigest()
        except Exception as e:
            logger.warning(f"Failed to calculate file hash: {e}")
        
        return ""
    
    def _track_event(self,
                    user_id: int,
                    event_type: str,
                    file_id: str = None,
                    line_number: int = None,
                    metadata: Dict[str, Any] = None):
        """רישום אירוע למעקב"""
        try:
            event = {
                "user_id": user_id,
                "event_type": event_type,
                "file_id": file_id,
                "line_number": line_number,
                "metadata": metadata or {},
                "timestamp": datetime.now(timezone.utc)
            }
            
            self.events_collection.insert_one(event)
            
        except Exception as e:
            logger.debug(f"Failed to track event: {e}")
    
    def _bookmark_to_response(self, bookmark: FileBookmark) -> Dict[str, Any]:
        """המרת סימנייה לפורמט תגובה"""
        return {
            "id": str(bookmark._id) if bookmark._id else None,
            "line_number": bookmark.line_number,
            "line_text_preview": bookmark.line_text_preview,
            "note": bookmark.note,
            "color": bookmark.color,
            "valid": bookmark.valid,
            "sync_status": bookmark.sync_status,
            "created_at": bookmark.created_at.isoformat() if bookmark.created_at else None,
            "updated_at": bookmark.updated_at.isoformat() if bookmark.updated_at else None
        }
    
    # ==================== Analytics Methods ====================
    
    def get_user_stats(self, user_id: int) -> Dict[str, Any]:
        """קבלת סטטיסטיקות משתמש"""
        try:
            total_bookmarks = self.collection.count_documents({"user_id": user_id})
            
            # הקבצים עם הכי הרבה סימניות
            pipeline = [
                {"$match": {"user_id": user_id}},
                {"$group": {
                    "_id": "$file_name",
                    "count": {"$sum": 1}
                }},
                {"$sort": {"count": -1}},
                {"$limit": 5}
            ]
            
            top_files = list(self.collection.aggregate(pipeline))
            
            # סימניות שנוצרו השבוע
            week_ago = datetime.now(timezone.utc) - timedelta(days=7)
            recent_count = self.collection.count_documents({
                "user_id": user_id,
                "created_at": {"$gte": week_ago}
            })
            
            return {
                "total_bookmarks": total_bookmarks,
                "recent_bookmarks": recent_count,
                "top_files": top_files,
                "max_allowed": MAX_BOOKMARKS_PER_USER
            }
            
        except Exception as e:
            logger.error(f"Error getting user stats: {e}")
            return {}
    
    def cleanup_invalid_bookmarks(self, days_old: int = 30) -> int:
        """ניקוי סימניות לא תקפות ישנות"""
        try:
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_old)
            
            result = self.collection.delete_many({
                "valid": False,
                "updated_at": {"$lt": cutoff_date}
            })
            
            logger.info(f"Cleaned up {result.deleted_count} invalid bookmarks")
            return result.deleted_count
            
        except Exception as e:
            logger.error(f"Error cleaning up bookmarks: {e}")
            return 0
