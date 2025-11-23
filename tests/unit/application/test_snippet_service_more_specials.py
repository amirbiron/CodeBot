from unittest.mock import MagicMock
import importlib


def _make_service():
    from src.application.services.snippet_service import SnippetService
    repo = MagicMock()
    norm = MagicMock()
    norm.normalize = lambda x: x
    return SnippetService(snippet_repository=repo, code_normalizer=norm)


def test_taskfile_maps_to_yaml():
    svc = _make_service()
    assert svc._detect_language("version: '3'\n", "Taskfile") == "yaml"


def test_env_special_filename_maps_to_env():
    svc = _make_service()
    assert svc._detect_language("BOT_TOKEN=\n", ".env") == "env"


def test_shebang_bash_no_extension_detected():
    svc = _make_service()
    code = "#!/usr/bin/env bash\necho hi\n"
    assert svc._detect_language(code, "start") == "bash"


def test_yaml_without_extension_detected_by_content():
    svc = _make_service()
    code = "name: ci\non: [push]\n"
    assert svc._detect_language(code, "ci") == "yaml"


def test_strong_extension_py_wins_over_markdown_content():
    svc = _make_service()
    md_like = "# Title\n\n- item\n"
    assert svc._detect_language(md_like, "notes.py") == "python"

