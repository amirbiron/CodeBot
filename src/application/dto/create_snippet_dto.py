from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, List


@dataclass
class CreateSnippetDTO:
    user_id: int
    filename: str
    code: str
    note: Optional[str] = None
    tags: Optional[List[str]] = None

    def __post_init__(self) -> None:
        if not isinstance(self.user_id, int) or self.user_id <= 0:
            raise ValueError("user_id must be positive int")
        if not self.filename:
            raise ValueError("filename is required")
        if not self.code:
            raise ValueError("code is required")
