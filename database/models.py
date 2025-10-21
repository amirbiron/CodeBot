import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class CodeSnippet:
    """ייצוג קטע קוד הנשמר במסד הנתונים."""
    user_id: int
    file_name: str
    code: str
    programming_language: str
    # שדות מועדפים
    is_favorite: bool = False
    favorited_at: Optional[datetime] = None
    description: str = ""
    tags: Optional[List[str]] = None
    version: int = 1
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    is_active: bool = True
    # שדות סל מיחזור: מתי נמחק ומתי יפוג התוקף למחיקה סופית
    deleted_at: Optional[datetime] = None
    deleted_expires_at: Optional[datetime] = None

    def __post_init__(self) -> None:
        if self.tags is None:
            self.tags = []
        if self.created_at is None:
            self.created_at = datetime.now(timezone.utc)
        if self.updated_at is None:
            self.updated_at = datetime.now(timezone.utc)
        # אם הפריט מוגדר כלא-פעיל אך אין timestamps למחיקה, השאר ריק — נקבע בזמן מחיקה


@dataclass
class LargeFile:
    """ייצוג מסמך עבור קובץ גדול הנשמר במסד הנתונים."""
    user_id: int
    file_name: str
    content: str
    programming_language: str
    file_size: int
    lines_count: int
    description: str = ""
    tags: Optional[List[str]] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    is_active: bool = True
    deleted_at: Optional[datetime] = None
    deleted_expires_at: Optional[datetime] = None

    def __post_init__(self) -> None:
        if self.tags is None:
            self.tags = []
        if self.created_at is None:
            self.created_at = datetime.now(timezone.utc)
        if self.updated_at is None:
            self.updated_at = datetime.now(timezone.utc)
        if self.content:
            self.file_size = len(self.content.encode('utf-8'))
            self.lines_count = len(self.content.split('\n'))

