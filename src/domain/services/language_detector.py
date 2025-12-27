from __future__ import annotations

import re
from pathlib import Path
from typing import Optional


class LanguageDetector:
    """
    Domain-level language detector.
    Pure heuristics combining filename and content, independent of infrastructure.
    """

    def detect_language(self, code: Optional[str], filename: Optional[str]) -> str:
        """
        Detect programming language from code and filename.
        Heuristics:
        - Special well-known filenames without extension (Dockerfile/Makefile/Taskfile/.env/.gitignore/.dockerignore)
        - Shebang detection (#!/usr/bin/env bash|sh|python, #!/bin/sh, etc.)
        - Non-generic extensions mapping (fast path)
        - Generic/ambiguous extensions (.md/.markdown, .txt, or no extension) may be overridden by strong content signals
        - Basic YAML/JSON/XML fallbacks
        """
        text = code or ""
        name = (filename or "").strip()
        name_lower = name.lower()
        ext = Path(name_lower).suffix  # includes leading dot or '' when no extension

        # 1) Special filenames without extension
        base = Path(name_lower).name
        if base in {"dockerfile"}:
            return "dockerfile"
        if base in {"makefile"}:
            return "makefile"
        if base in {"taskfile"} or base.startswith("taskfile"):
            return "yaml"  # go-task Taskfile is YAML
        if base in {".gitignore"}:
            return "gitignore"
        if base in {".dockerignore"}:
            return "dockerignore"
        if base in {".env"} or base.startswith(".env."):
            return "env"

        # 2) Shebang detection (take precedence for extensionless/generic files)
        first_line = (text.splitlines()[0] if text else "").strip().lower()
        if first_line.startswith("#!"):
            if "bash" in first_line or first_line.endswith("/sh") or " env sh" in first_line or " env bash" in first_line:
                return "bash"
            if "python" in first_line:
                return "python"

        # 3) Non-generic extension mapping (fast path)
        non_generic_map = {
            # Python
            ".py": "python",
            ".pyw": "python",
            ".pyx": "python",
            ".pyi": "python",
            # JavaScript/TypeScript
            ".js": "javascript",
            ".jsx": "javascript",
            ".ts": "typescript",
            ".tsx": "typescript",
            ".mjs": "javascript",
            # Web
            ".html": "html",
            ".htm": "html",
            ".css": "css",
            ".scss": "scss",
            ".sass": "sass",
            ".less": "less",
            # JVM
            ".java": "java",
            # C/C++
            ".cpp": "cpp",
            ".cxx": "cpp",
            ".cc": "cpp",
            ".hpp": "cpp",
            ".hxx": "cpp",
            ".c": "c",
            # Other languages
            ".cs": "csharp",
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
        }
        if ext in non_generic_map:
            return non_generic_map[ext]

        # 4) Generic extensions: consider content signals
        generic_md_exts = {".md", ".markdown", ".mdown", ".mkd", ".mkdn"}
        generic_text_exts = {".txt", ""}

        def looks_like_markdown(content: str) -> bool:
            # Ignore leading shebang so code lines are not mistaken for headings
            view = content or ""
            if view.startswith("#!"):
                nl = view.find("\n")
                view = "" if nl == -1 else view[nl + 1 :]
            # Headings (#) with up to 3 leading spaces and single '#'
            if re.search(r"(^|\n)\s{0,3}#[^#]", view):
                return True
            # Lists (-/*/+) with up to 2 leading spaces
            if re.search(r"(^|\n)\s{0,2}[-*+]\s+\S", view):
                return True
            # Markdown links
            if re.search(r"\[.+?\]\(.+?\)", view):
                return True
            return False

        def looks_like_markdown_structural(content: str) -> bool:
            """
            בדיקת Markdown "חזקה" בלבד (ללא כותרות).

            למה: בקוד פייתון יש הרבה שורות שמתחילות ב-`#` (comments),
            ואנחנו לא רוצים שזה ימנע override ל-python עבור קבצי `.md`
            כשהתוכן הוא בפועל קוד.

            שים לב: אנחנו *לא* מחשיבים רשימות (`- item`) כסמן חזק כאן,
            כי זה מופיע הרבה בתוך Docstrings/הערות, וזה בדיוק המקרה של `block.md`
            שבו התוכן הוא קוד אבל הסיומת גנרית.
            """
            view = content or ""
            if view.startswith("#!"):
                nl = view.find("\n")
                view = "" if nl == -1 else view[nl + 1 :]
            # Markdown links / images
            if re.search(r"\[.+?\]\(.+?\)", view):
                return True
            if re.search(r"(^|\n)!\[.*?\]\(.+?\)", view):
                return True
            # Code fences: אם יש ``` *וגם* לא מדובר במקרה של "כל הקובץ הוא fence יחיד"
            # (שנלכד כבר קודם), זה כמעט תמיד מסמך Markdown ולא קובץ קוד.
            if "```" in view:
                return True
            # Simple tables (very common in markdown docs)
            if re.search(r"(^|\n)\s*\|.+\|\s*$", view):
                return True
            return False

        def _extract_single_fenced_block(content: str) -> tuple[str, Optional[str]] | None:
            """אם כל הקובץ הוא בלוק ``` אחד – החזר (inner, fence_lang).

            זה חשוב כדי לא לטעות ולשמור קוד כ-Markdown רק בגלל שהמשתמש עטף אותו ב-``` בטלגרם.
            """
            try:
                stripped = (content or "").strip()
                if not stripped:
                    return None
                lines = stripped.splitlines()
                if not lines:
                    return None
                # מצא שורות fence: ```... (מתעלמים מרווחים בתחילת/סוף שורה)
                fence_lines = [i for i, ln in enumerate(lines) if (ln.strip().startswith("```"))]
                if len(fence_lines) != 2:
                    return None
                if fence_lines[0] != 0 or fence_lines[1] != (len(lines) - 1):
                    return None
                first = lines[0].strip()
                # language אחרי ה-``` (למשל ```python)
                fence_lang = (first[3:].strip().split()[:1] or [None])[0]
                inner = "\n".join(lines[1:-1])
                return inner, (str(fence_lang).lower() if fence_lang else None)
            except Exception:
                return None

        def _looks_like_markdown_without_fences(content: str) -> bool:
            """וריאנט שמתעלם מכותרות, כדי לא לחסום override לקוד עם #comments."""
            return looks_like_markdown_structural(content)

        def strong_python_signal(content: str) -> bool:
            if re.search(r"^#!.*\bpython(\d+(?:\.\d+)*)?\b", content, flags=re.IGNORECASE | re.MULTILINE):
                return True
            signals = 0
            if re.search(r"^\s*def\s+\w+\s*\(", content, flags=re.MULTILINE):
                signals += 1
            if re.search(r"^\s*class\s+\w+\s*\(?", content, flags=re.MULTILINE):
                signals += 1
            if re.search(r"^\s*import\s+\w+", content, flags=re.MULTILINE):
                signals += 1
            if "__name__" in content and "__main__" in content:
                signals += 1
            if re.search(r":\s*(#.*)?\n\s{4,}\S", content, flags=re.MULTILINE):
                signals += 1
            return signals >= 2

        # Markdown: prefer markdown unless the content is clearly Python and no strong markdown markers
        if ext in generic_md_exts:
            fenced = _extract_single_fenced_block(text)
            if fenced is not None:
                inner, fence_lang = fenced
                # אם מצוין שפה על ה-fence – נכבד (בעדיפות ל-python לפי הדרישה)
                if fence_lang in {"python", "py"}:
                    return "python"
                if strong_python_signal(inner):
                    return "python"
                # אחרת נשאר markdown (קובץ markdown עם בלוק יחיד)
                return "markdown"

            # אם זה .md אבל התוכן "קוד בלבד" (גם אם יש ```), נעדיף python.
            if strong_python_signal(text) and not _looks_like_markdown_without_fences(text):
                return "python"
            return "markdown"

        # Plain text or no extension: allow content override
        if ext in generic_text_exts:
            # Prefer strong Python signals first to avoid misclassifying typed hints like `result: int`
            if strong_python_signal(text):
                return "python"
            # Heuristic YAML (common in config/Taskfile without extension)
            if re.search(r"(?m)^\s*-\s+\S", text) or re.search(r"(?m)^\s*\w+\s*:", text):
                return "yaml"
            return "text"

        # 5) Config/data formats
        if ext in {".json"}:
            return "json"
        if ext in {".yaml", ".yml"}:
            return "yaml"
        if ext in {".xml"}:
            return "xml"

        # 6) Fallback
        return "text"

