import pytest

from src.application.dto.create_snippet_dto import CreateSnippetDTO
from src.application.services.snippet_service import SnippetService
from src.domain.entities.snippet import Snippet
from src.domain.services.code_normalizer import CodeNormalizer
from src.domain.interfaces.snippet_repository_interface import ISnippetRepository


class StubRepo(ISnippetRepository):
    def __init__(self):
        self._saved = []
        self._latest = None

    async def save(self, snippet: Snippet) -> Snippet:
        # mimic version increment
        snippet.version = (snippet.version or 1)
        self._latest = Snippet(
            user_id=snippet.user_id,
            filename=snippet.filename,
            code=snippet.code,
            language=snippet.language,
            description=snippet.description,
            tags=list(snippet.tags or []),
            version=snippet.version,
        )
        self._saved.append(self._latest)
        return self._latest

    async def get_latest_version(self, user_id: int, filename: str):
        return self._latest if (self._latest and self._latest.user_id == user_id and self._latest.filename == filename) else None

    async def search(self, user_id: int, query: str, language=None, limit: int = 20):
        return [s for s in self._saved if s.user_id == user_id and (language is None or s.language == language)]


@pytest.mark.asyncio
async def test_create_snippet_normalizes_and_detects_language_py():
    repo = StubRepo()
    service = SnippetService(snippet_repository=repo, code_normalizer=CodeNormalizer())

    dto = CreateSnippetDTO(user_id=1, filename="t.py", code="a\r\nb  \r\n")
    result = await service.create_snippet(dto)

    assert isinstance(result, Snippet)
    assert result.language == "python"
    assert result.code == "a\nb\n".rstrip("\n")  # service doesn't force newline


@pytest.mark.asyncio
async def test_get_snippet_delegates_to_repo():
    repo = StubRepo()
    service = SnippetService(snippet_repository=repo, code_normalizer=CodeNormalizer())

    dto = CreateSnippetDTO(user_id=2, filename="x.ts", code="let a=1\r\n")
    await service.create_snippet(dto)

    got = await service.get_snippet(2, "x.ts")
    assert got is not None
    assert got.filename == "x.ts"


@pytest.mark.asyncio
async def test_search_delegates_to_repo_with_language_filter():
    repo = StubRepo()
    service = SnippetService(snippet_repository=repo, code_normalizer=CodeNormalizer())

    await service.create_snippet(CreateSnippetDTO(user_id=3, filename="a.py", code="print(1)"))
    await service.create_snippet(CreateSnippetDTO(user_id=3, filename="b.js", code="console.log(1)"))

    py_results = await service.search_snippets(3, query="", language="python")
    assert len(py_results) == 1
    assert py_results[0].filename == "a.py"
