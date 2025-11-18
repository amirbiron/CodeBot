from __future__ import annotations

from typing import Optional, List

from src.application.dto.create_snippet_dto import CreateSnippetDTO
from src.domain.entities.snippet import Snippet
from src.domain.services.code_normalizer import CodeNormalizer
from src.domain.interfaces.snippet_repository_interface import ISnippetRepository


class SnippetService:
    """Application service orchestrating snippet operations.

    Thin orchestration over domain + repository. No DB/Telegram here.
    """

    def __init__(
        self,
        snippet_repository: ISnippetRepository,
        code_normalizer: CodeNormalizer,
    ) -> None:
        self._repo = snippet_repository
        self._normalizer = code_normalizer

    async def create_snippet(self, dto: CreateSnippetDTO) -> Snippet:
        normalized = self._normalizer.normalize(dto.code)
        entity = Snippet(
            user_id=dto.user_id,
            filename=dto.filename,
            code=normalized,
            language=self._detect_language(normalized, dto.filename),
            description=dto.note or "",
            tags=list(dto.tags or []),
        )
        saved = await self._repo.save(entity)
        return saved

    async def get_snippet(self, user_id: int, filename: str) -> Optional[Snippet]:
        return await self._repo.get_latest_version(user_id, filename)

    async def search_snippets(self, user_id: int, query: str, language: Optional[str] = None, limit: int = 20) -> List[Snippet]:
        return await self._repo.search(user_id, query, language=language, limit=limit)

    def _detect_language(self, code: str, filename: str) -> str:
        # Minimal heuristic for now; can be replaced with domain LanguageDetector later
        fname = filename.lower()
        # Markdown and variants first (סיומת גוברת)
        if fname.endswith(('.md', '.markdown', '.mdown', '.mkd', '.mkdn')):
            return 'markdown'
        if fname.endswith('.py'):
            return 'python'
        if fname.endswith(('.js', '.jsx')):
            return 'javascript'
        if fname.endswith(('.ts', '.tsx')):
            return 'typescript'
        if fname.endswith('.java'):
            return 'java'
        if fname.endswith(('.cpp', '.cxx', '.cc', '.hpp', '.hxx')):
            return 'cpp'
        if fname.endswith('.c'):
            return 'c'
        if fname.endswith('.go'):
            return 'go'
        if fname.endswith('.rs'):
            return 'rust'
        if fname.endswith(('.rb', '.rake')):
            return 'ruby'
        if fname.endswith(('.php', '.phtml')):
            return 'php'
        if fname.endswith('.swift'):
            return 'swift'
        if fname.endswith(('.sh', '.bash', '.zsh', '.fish')):
            return 'bash'
        if fname.endswith('.sql'):
            return 'sql'
        if fname.endswith(('.html', '.htm')):
            return 'html'
        if fname.endswith('.css'):
            return 'css'
        return 'text'
