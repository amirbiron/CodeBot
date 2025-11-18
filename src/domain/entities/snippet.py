from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional


@dataclass
class Snippet:
    """Domain entity: code snippet (minimal version).

    Kept framework-free to allow use across layers.
    """

    user_id: int
    filename: str
    code: str
    language: str
    description: str = ""
    tags: List[str] = field(default_factory=list)
    version: int = 1
    is_favorite: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    favorited_at: Optional[datetime] = None
    is_active: bool = True
