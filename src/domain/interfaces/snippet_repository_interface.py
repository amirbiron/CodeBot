from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional

from src.domain.entities.snippet import Snippet


class ISnippetRepository(ABC):
    """Repository interface for Snippet domain entity.

    Domain defines the contract; infrastructure implements it.
    """

    @abstractmethod
    async def save(self, snippet: Snippet) -> Snippet:  # returns saved entity (latest version)
        raise NotImplementedError

    @abstractmethod
    async def get_latest_version(self, user_id: int, filename: str) -> Optional[Snippet]:
        raise NotImplementedError

    @abstractmethod
    async def search(self, user_id: int, query: str, language: Optional[str] = None, limit: int = 20) -> List[Snippet]:
        raise NotImplementedError
