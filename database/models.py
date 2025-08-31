import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List

logger = logging.getLogger(__name__)


@dataclass
class CodeSnippet:
    """ייצוג קטע קוד הנשמר במסד הנתונים."""

    user_id: int
    file_name: str
    code: str
    programming_language: str
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
            self.created_at = datetime.now(timezone.utc)
        if self.updated_at is None:
            self.updated_at = datetime.now(timezone.utc)


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
    tags: List[str] = None
    created_at: datetime = None
    updated_at: datetime = None
    is_active: bool = True

    def __post_init__(self):
        if self.tags is None:
            self.tags = []
        if self.created_at is None:
            self.created_at = datetime.now(timezone.utc)
        if self.updated_at is None:
            self.updated_at = datetime.now(timezone.utc)
        if self.content:
            self.file_size = len(self.content.encode("utf-8"))
            self.lines_count = len(self.content.split("\n"))
