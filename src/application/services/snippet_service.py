from __future__ import annotations

from typing import Optional, List

from src.application.dto.create_snippet_dto import CreateSnippetDTO
from src.domain.entities.snippet import Snippet
from src.domain.services.code_normalizer import CodeNormalizer
from src.domain.interfaces.snippet_repository_interface import ISnippetRepository
import re
from pathlib import Path


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
        """
        Heuristic language detection combining filename and content.
        - Non-generic extensions keep priority (backward compatible).
        - Generic/ambiguous extensions (.txt, .md, no extension) may be overridden
          by strong content signals (e.g., clear Python code).
        - Special filenames (Dockerfile/Makefile/dotfiles) are supported.
        """
        fname = (filename or "").strip()
        fname_lower = fname.lower()
        ext = Path(fname_lower).suffix  # includes leading dot or '' if no extension

        # Special well-known filenames (no extension)
        if fname_lower == "dockerfile" or fname_lower.endswith("/dockerfile"):
            return "dockerfile"
        if fname_lower == "makefile" or fname_lower.endswith("/makefile"):
            return "makefile"
        if fname_lower in {".gitignore", ".dockerignore"}:
            return "gitignore" if fname_lower == ".gitignore" else "dockerignore"

        # Fast path by non-generic extension (keeps legacy behavior)
        non_generic_map = {
            # Python
            ".py": "python",
            ".pyw": "python",
            ".pyx": "python",
            ".pyi": "python",
            # JS/TS
            ".js": "javascript",
            ".jsx": "javascript",
            ".ts": "typescript",
            ".tsx": "typescript",
            ".mjs": "javascript",
            # Web
            ".html": "html",
            ".htm": "html",
            ".css": "css",
            # JVM
            ".java": "java",
            # C/C++
            ".cpp": "cpp",
            ".cxx": "cpp",
            ".cc": "cpp",
            ".hpp": "cpp",
            ".hxx": "cpp",
            ".c": "c",
            # Other
            ".go": "go",
            ".rs": "rust",
            ".rb": "ruby",
            ".rake": "ruby",
            ".php": "php",
            ".phtml": "php",
            ".swift": "swift",
            ".sh": "bash",
            ".bash": "bash",
            ".zsh": "bash",
            ".fish": "bash",
            ".sql": "sql",
            ".scss": "scss",
            ".sass": "sass",
            ".less": "less",
        }
        if ext in non_generic_map:
            return non_generic_map[ext]

        # Generic/ambiguous: consider content signals
        generic_md_exts = {".md", ".markdown", ".mdown", ".mkd", ".mkdn"}
        generic_text_exts = {".txt", ""}

        def looks_like_markdown(text: str) -> bool:
            content = text or ""
            # Ignore leading shebang so code blocks are not mistaken for headings
            if content.startswith("#!"):
                newline_idx = content.find("\n")
                content = "" if newline_idx == -1 else content[newline_idx + 1 :]
            # Basic markdown markers
            if re.search(r"(^|\n)\s{0,3}#[^#]", content):
                return True
            if re.search(r"(^|\n)\s{0,2}[-*+]\s+\S", content):
                return True
            if re.search(r"\[.+?\]\(.+?\)", content):
                return True
            if "```" in content:
                return True
            return False

        def strong_python_signal(text: str) -> bool:
            # Strong indicators of Python source
            if re.search(r"^#!.*\bpython(\d+(?:\.\d+)*)?\b", text, flags=re.IGNORECASE | re.MULTILINE):
                return True
            signals = 0
            if re.search(r"^\s*def\s+\w+\s*\(", text, flags=re.MULTILINE):
                signals += 1
            if re.search(r"^\s*class\s+\w+\s*\(?", text, flags=re.MULTILINE):
                signals += 1
            if re.search(r"^\s*import\s+\w+", text, flags=re.MULTILINE):
                signals += 1
            if "__name__" in text and "__main__" in text:
                signals += 1
            # Colon-based blocks and indentation patterns
            if re.search(r":\s*(#.*)?\n\s{4,}\S", text, flags=re.MULTILINE):
                signals += 1
            return signals >= 2

        # If markdown extension: prefer markdown unless code is clearly Python
        if ext in generic_md_exts:
            return "python" if strong_python_signal(code or "") and not looks_like_markdown(code or "") else "markdown"

        # For pure text/no extension: allow strong content override
        if ext in generic_text_exts:
            if strong_python_signal(code or ""):
                return "python"
            return "text"

        # Fallbacks for other configs and files
        if ext in {".json"}:
            return "json"
        if ext in {".yaml", ".yml"}:
            return "yaml"
        if ext in {".xml"}:
            return "xml"
        return "text"
