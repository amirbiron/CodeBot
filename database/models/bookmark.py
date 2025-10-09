"""
Bookmark Model for file line bookmarks
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from bson import ObjectId


@dataclass
class FileBookmark:
    """מודל סימנייה לשורה בקובץ קוד"""
    
    # Required fields
    user_id: int                    # Telegram user ID
    file_id: str                     # MongoDB ObjectId של הקובץ
    file_name: str                   # שם הקובץ לחיפוש מהיר
    file_path: str                   # נתיב הקובץ המלא
    line_number: int                 # מספר השורה (1-based)
    
    # Content preview
    line_text_preview: str = ""     # 100 התווים הראשונים של השורה
    code_context: str = ""           # 3 שורות לפני ואחרי (אופציונלי)
    
    # User content
    note: str = ""                   # הערת המשתמש (עד 500 תווים)
    color: str = "yellow"            # צבע הסימנייה (yellow/red/green/blue)
    
    # Sync metadata
    file_hash: str = ""              # SHA256 של הקובץ בזמן היצירה
    valid: bool = True               # האם הסימנייה עדיין תקפה
    sync_status: str = "synced"      # synced/moved/modified/deleted
    sync_confidence: float = 1.0     # רמת הביטחון בסנכרון (0-1)
    
    # Timestamps
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_accessed: Optional[datetime] = None
    
    # MongoDB ID
    _id: Optional[ObjectId] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """המרה ל-dictionary לשמירה ב-MongoDB"""
        data = {
            "user_id": self.user_id,
            "file_id": self.file_id,
            "file_name": self.file_name,
            "file_path": self.file_path,
            "line_number": self.line_number,
            "line_text_preview": self.line_text_preview[:100],  # הגבלה ל-100 תווים
            "code_context": self.code_context[:500],            # הגבלה ל-500 תווים
            "note": self.note[:500],                            # הגבלה ל-500 תווים
            "color": self.color,
            "file_hash": self.file_hash,
            "valid": self.valid,
            "sync_status": self.sync_status,
            "sync_confidence": self.sync_confidence,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "last_accessed": self.last_accessed
        }
        
        if self._id:
            data["_id"] = self._id
            
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FileBookmark":
        """יצירה מ-dictionary שהגיע מ-MongoDB"""
        bookmark = cls(
            user_id=data["user_id"],
            file_id=data["file_id"],
            file_name=data["file_name"],
            file_path=data.get("file_path", ""),
            line_number=data["line_number"],
            line_text_preview=data.get("line_text_preview", ""),
            code_context=data.get("code_context", ""),
            note=data.get("note", ""),
            color=data.get("color", "yellow"),
            file_hash=data.get("file_hash", ""),
            valid=data.get("valid", True),
            sync_status=data.get("sync_status", "synced"),
            sync_confidence=data.get("sync_confidence", 1.0),
            created_at=data.get("created_at", datetime.now(timezone.utc)),
            updated_at=data.get("updated_at", datetime.now(timezone.utc)),
            last_accessed=data.get("last_accessed")
        )
        
        if "_id" in data:
            bookmark._id = data["_id"]
            
        return bookmark
    
    def __str__(self) -> str:
        return f"Bookmark({self.file_name}:{self.line_number})"
    
    def __repr__(self) -> str:
        return (f"FileBookmark(user={self.user_id}, file={self.file_name}, "
                f"line={self.line_number}, note='{self.note[:20]}...')")


# Constants for validation
MAX_BOOKMARKS_PER_FILE = 50
MAX_BOOKMARKS_PER_USER = 500
MAX_NOTE_LENGTH = 500
MAX_CONTEXT_LENGTH = 500
VALID_COLORS = ["yellow", "red", "green", "blue", "purple", "orange"]