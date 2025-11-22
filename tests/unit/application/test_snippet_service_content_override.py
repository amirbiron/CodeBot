from unittest.mock import MagicMock


def _make_service():
    from src.application.services.snippet_service import SnippetService
    repo = MagicMock()
    norm = MagicMock()
    norm.normalize = lambda x: x
    return SnippetService(snippet_repository=repo, code_normalizer=norm)


def test_md_with_strong_python_signals_overrides_to_python():
    svc = _make_service()
    code = "def foo():\n    import os\n    return 1\n"
    assert svc._detect_language(code, "block.md") == "python"


def test_md_plain_markdown_stays_markdown():
    svc = _make_service()
    md = "# כותרת\n\n- פריט\n\nקישור: [דוגמה](https://example.com)\n"
    assert svc._detect_language(md, "doc.md") == "markdown"


def test_md_with_code_fence_stays_markdown():
    svc = _make_service()
    md = "# Title\n\n```python\ndef foo():\n    pass\n```\n"
    assert svc._detect_language(md, "doc.md") == "markdown"


def test_md_with_python_shebang_overrides_to_python():
    svc = _make_service()
    code = "#!/usr/bin/env python3\nprint(1)\n"
    assert svc._detect_language(code, "notes.md") == "python"


def test_txt_with_python_signals_becomes_python():
    svc = _make_service()
    code = "import sys\n\ndef main():\n    pass\n"
    assert svc._detect_language(code, "readme.txt") == "python"


def test_no_extension_with_python_signals_becomes_python():
    svc = _make_service()
    code = "class A:\n    def x(self):\n        return 1\n"
    assert svc._detect_language(code, "script") == "python"


def test_special_filenames_supported():
    svc = _make_service()
    assert svc._detect_language("", "Dockerfile") == "dockerfile"
    assert svc._detect_language("", "Makefile") == "makefile"
    assert svc._detect_language("", ".gitignore") == "gitignore"
    assert svc._detect_language("", ".dockerignore") == "dockerignore"


def test_non_generic_extension_keeps_priority():
    svc = _make_service()
    assert svc._detect_language("not code at all", "app.py") == "python"
