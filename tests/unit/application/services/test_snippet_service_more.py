import pytest

from src.application.dto.create_snippet_dto import CreateSnippetDTO
from src.application.services.snippet_service import SnippetService
from src.domain.services.code_normalizer import CodeNormalizer
from src.domain.interfaces.snippet_repository_interface import ISnippetRepository
from src.domain.entities.snippet import Snippet


class StubRepo(ISnippetRepository):
    def __init__(self):
        self._last = None

    async def save(self, snippet: Snippet) -> Snippet:
        self._last = snippet
        return snippet

    async def get_latest_version(self, user_id: int, filename: str):
        return self._last if (self._last and self._last.user_id == user_id and self._last.filename == filename) else None

    async def search(self, user_id: int, query: str, language=None, limit: int = 20):
        return []


@pytest.mark.asyncio
async def test_detects_javascript_by_extension():
    repo = StubRepo()
    svc = SnippetService(snippet_repository=repo, code_normalizer=CodeNormalizer())
    dto = CreateSnippetDTO(user_id=1, filename="app.js", code="console.log('hi')\r\n")
    saved = await svc.create_snippet(dto)
    assert saved.language == 'javascript'


@pytest.mark.asyncio
async def test_detects_text_for_unknown_extension():
    repo = StubRepo()
    svc = SnippetService(snippet_repository=repo, code_normalizer=CodeNormalizer())
    dto = CreateSnippetDTO(user_id=1, filename="README", code="some text")
    saved = await svc.create_snippet(dto)
    assert saved.language == 'text'
