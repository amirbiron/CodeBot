"""
Code Indexer - אינדוקס קבצי קוד ב-MongoDB

מאנדקס metadata בלבד (לא את התוכן המלא!):
- נתיב, שפה, גודל
- imports, functions, classes
- search_text מצומצם
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class CodeIndexer:
    """
    אינדוקס metadata של קבצי קוד ב-MongoDB

    מה נשמר ב-DB:
    - path, language, size, lines
    - imports, functions, classes (semantic info)
    - search_text (לחיפוש מהיר)

    מה לא נשמר:
    - תוכן מלא (נקרא מ-git mirror)

    **הערה חשובה על Regex vs AST:**

    הקוד הזה משתמש ב-Regex לפשטות, אבל יש לזה חסרונות:
    - Regex יכול לתפוס מילים בתוך מחרוזות או הערות
    - `def` בתוך docstring יזוהה בטעות כפונקציה

    **לפרודקשן מומלץ:**
    - Python: להשתמש במודול `ast` המובנה (מהיר ומדויק 100%)
    - JavaScript/TypeScript: להשתמש ב-`@babel/parser` או `typescript`
    - שאר השפות: Regex מספיק טוב (או tree-sitter)

    דוגמה לשימוש ב-AST לפייתון:

    ```python
    import ast

    def extract_functions_with_ast(content: str) -> List[str]:
        try:
            tree = ast.parse(content)
            return [
                node.name for node in ast.walk(tree)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            ]
        except SyntaxError:
            return []  # fallback to regex
    ```
    """

    # דפוסים להתעלמות
    IGNORE_PATTERNS = [
        "node_modules/",
        "__pycache__/",
        ".git/",
        "venv/",
        ".venv/",
        ".pytest_cache/",
        "dist/",
        "build/",
        ".next/",
        ".nuxt/",
        "coverage/",
        ".coverage",
        "*.pyc",
        "*.pyo",
        "*.jpg",
        "*.jpeg",
        "*.png",
        "*.gif",
        "*.svg",
        "*.ico",
        "*.pdf",
        "*.mp4",
        "*.mp3",
        "*.zip",
        "*.tar",
        "*.gz",
        "*.exe",
        "*.dll",
        "*.so",
        "*.woff",
        "*.woff2",
        "*.ttf",
        "*.eot",
        "package-lock.json",
        "yarn.lock",
        "poetry.lock",
        "Pipfile.lock",
        ".DS_Store",
        "Thumbs.db",
    ]

    # סיומות קוד לאינדוקס
    CODE_EXTENSIONS = [
        ".py",
        ".pyi",
        ".pyx",
        ".js",
        ".jsx",
        ".mjs",
        ".ts",
        ".tsx",
        ".html",
        ".htm",
        ".css",
        ".scss",
        ".sass",
        ".less",
        ".json",
        ".jsonc",
        ".yml",
        ".yaml",
        ".md",
        ".rst",
        ".txt",
        ".sh",
        ".bash",
        ".zsh",
        ".sql",
        ".go",
        ".rs",
        ".java",
        ".kt",
        ".scala",
        ".c",
        ".cpp",
        ".h",
        ".hpp",
        ".rb",
        ".php",
        ".swift",
        ".r",
        ".R",
        ".vue",
        ".svelte",
        ".xml",
        ".xsl",
        ".ini",
        ".cfg",
        ".conf",
        ".toml",
        ".dockerfile",
        ".containerfile",
        ".tf",
        ".hcl",
        ".graphql",
        ".gql",
    ]

    # גודל מקסימלי לאינדוקס (500KB)
    MAX_FILE_SIZE = 500_000

    def __init__(self, db: Any = None):
        """
        Args:
            db: MongoDB database instance
        """
        self.db = db

    def should_index(self, file_path: str) -> bool:
        """
        האם לאנדקס קובץ זה?

        Args:
            file_path: נתיב הקובץ

        Returns:
            True אם צריך לאנדקס
        """
        # בדיקת דפוסי התעלמות
        for pattern in self.IGNORE_PATTERNS:
            pattern_clean = pattern.replace("*", "")
            if pattern_clean in file_path:
                return False

        # בדיקת סיומת
        path = Path(file_path)

        # קבצים ללא סיומת ספציפיים
        if path.name in ["Dockerfile", "Makefile", "Jenkinsfile", ".gitignore", ".env.example"]:
            return True

        # סיומות מותרות
        if path.suffix.lower() in self.CODE_EXTENSIONS:
            return True

        return False

    def index_file(self, repo_name: str, file_path: str, content: str, commit_sha: str = "HEAD") -> bool:
        """
        אינדוקס קובץ בודד ב-MongoDB

        Args:
            repo_name: שם הריפו
            file_path: נתיב הקובץ
            content: תוכן הקובץ
            commit_sha: SHA של הקומיט

        Returns:
            True אם הצליח
        """
        if not self.db:
            logger.error("No database connection")
            return False

        # בדיקת גודל
        if len(content) > self.MAX_FILE_SIZE:
            logger.info(f"Skipping large file ({len(content)} bytes): {file_path}")
            return False

        # זיהוי שפה
        language = self._detect_language(file_path)

        # חילוץ מידע סמנטי
        imports = self._extract_imports(content, language)
        functions = self._extract_functions(content, language)
        classes = self._extract_classes(content, language)

        # יצירת טקסט לחיפוש
        search_text = self._create_search_text(file_path, imports, functions, classes)

        # Document לשמירה
        doc: Dict[str, Any] = {
            "repo_name": repo_name,
            "path": file_path,
            "language": language,
            "size": len(content),
            "lines": content.count("\n") + 1,
            "commit_sha": commit_sha,
            "last_indexed": datetime.utcnow(),
            "imports": imports,
            "functions": functions,
            "classes": classes,
            "search_text": search_text,
        }

        try:
            self.db.repo_files.update_one(
                {"repo_name": repo_name, "path": file_path},
                {"$set": doc},
                upsert=True,
            )
            return True

        except Exception as e:
            logger.exception(f"Failed to index {file_path}: {e}")
            return False

    def remove_file(self, repo_name: str, file_path: str) -> bool:
        """מחיקת קובץ מהאינדקס"""
        if not self.db:
            return False

        try:
            result = self.db.repo_files.delete_one({"repo_name": repo_name, "path": file_path})
            return bool(getattr(result, "deleted_count", 0) > 0)

        except Exception as e:
            logger.exception(f"Failed to remove {file_path}: {e}")
            return False

    def remove_files(self, repo_name: str, file_paths: List[str]) -> int:
        """מחיקת מספר קבצים מהאינדקס"""
        if not self.db or not file_paths:
            return 0

        try:
            result = self.db.repo_files.delete_many({"repo_name": repo_name, "path": {"$in": file_paths}})
            return int(getattr(result, "deleted_count", 0) or 0)

        except Exception as e:
            logger.exception(f"Failed to remove files: {e}")
            return 0

    def _detect_language(self, file_path: str) -> str:
        """זיהוי שפת התכנות לפי הסיומת"""
        ext = Path(file_path).suffix.lower()

        LANGUAGE_MAP = {
            ".py": "python",
            ".pyi": "python",
            ".js": "javascript",
            ".jsx": "javascript",
            ".mjs": "javascript",
            ".ts": "typescript",
            ".tsx": "typescript",
            ".html": "html",
            ".htm": "html",
            ".css": "css",
            ".scss": "scss",
            ".sass": "sass",
            ".less": "less",
            ".json": "json",
            ".yml": "yaml",
            ".yaml": "yaml",
            ".md": "markdown",
            ".rst": "rst",
            ".sh": "shell",
            ".bash": "shell",
            ".sql": "sql",
            ".go": "go",
            ".rs": "rust",
            ".java": "java",
            ".kt": "kotlin",
            ".c": "c",
            ".cpp": "cpp",
            ".h": "c",
            ".hpp": "cpp",
            ".rb": "ruby",
            ".php": "php",
            ".swift": "swift",
            ".r": "r",
            ".vue": "vue",
            ".svelte": "svelte",
        }

        return LANGUAGE_MAP.get(ext, "text")

    def _extract_imports(self, content: str, language: str) -> List[str]:
        """חילוץ imports מהקוד"""
        imports: List[str] = []

        if language == "python":
            # import x, from x import y
            pattern = r"(?:from|import)\s+([\w.]+)"
            imports = re.findall(pattern, content)

        elif language in ["javascript", "typescript"]:
            # import x from 'y'
            # require('y')
            pattern1 = r'import\s+.+?\s+from\s+[\'"]([^"\']+)[\'"]'
            pattern2 = r'require\s*\(\s*[\'"]([^"\']+)[\'"]\s*\)'
            imports = re.findall(pattern1, content) + re.findall(pattern2, content)

        elif language == "go":
            # import "x"
            pattern = r'import\s+(?:"([^"]+)"|\(\s*"([^"]+)")'
            matches = re.findall(pattern, content)
            imports = [m[0] or m[1] for m in matches]

        # ייחודיים וחיתוך
        return list(set(imports))[:30]

    def _extract_functions(self, content: str, language: str) -> List[str]:
        """חילוץ שמות פונקציות"""
        functions: List[str] = []

        if language == "python":
            # def func_name(
            # async def func_name(
            pattern = r"(?:async\s+)?def\s+(\w+)\s*\("
            functions = re.findall(pattern, content)

        elif language in ["javascript", "typescript"]:
            # function name(
            # const name = (
            # const name = async (
            pattern1 = r"function\s+(\w+)\s*\("
            pattern2 = r"(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?\("
            pattern3 = r"(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?function"
            functions = re.findall(pattern1, content) + re.findall(pattern2, content) + re.findall(pattern3, content)

        elif language == "go":
            # func name(
            pattern = r"func\s+(?:\([^)]+\)\s+)?(\w+)\s*\("
            functions = re.findall(pattern, content)

        return list(set(functions))[:50]

    def _extract_classes(self, content: str, language: str) -> List[str]:
        """חילוץ שמות מחלקות"""
        classes: List[str] = []

        if language == "python":
            pattern = r"class\s+(\w+)"
            classes = re.findall(pattern, content)

        elif language in ["javascript", "typescript", "java", "kotlin"]:
            pattern = r"class\s+(\w+)"
            classes = re.findall(pattern, content)

        elif language == "go":
            # type Name struct
            pattern = r"type\s+(\w+)\s+struct"
            classes = re.findall(pattern, content)

        return list(set(classes))[:30]

    def _create_search_text(self, file_path: str, imports: List[str], functions: List[str], classes: List[str]) -> str:
        """
        יצירת טקסט אופטימלי לחיפוש

        הערה: לחיפוש מלא משתמשים ב-git grep,
        זה רק לחיפוש metadata מהיר.
        """
        parts: List[str] = []

        # שם הקובץ ורכיבי הנתיב
        parts.append(file_path)
        parts.extend(Path(file_path).parts)

        # imports, functions, classes
        parts.extend(imports)
        parts.extend(functions)
        parts.extend(classes)

        # הרכבת הטקסט
        text = " ".join(parts)

        # הגבלת גודל
        return text[:2000]


# Factory function
def create_indexer(db: Any = None) -> CodeIndexer:
    """יצירת instance של CodeIndexer"""
    return CodeIndexer(db)

