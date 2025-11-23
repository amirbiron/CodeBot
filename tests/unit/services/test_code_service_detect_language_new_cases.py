import importlib


def test_detects_bash_by_env_shebang_no_extension():
    svc = importlib.import_module('services.code_service')
    code = "#!/usr/bin/env bash\necho hi\n"
    out = svc.detect_language(code, filename="run")
    assert out == "bash"


def test_detects_python_by_env_shebang_no_extension():
    svc = importlib.import_module('services.code_service')
    code = "#!/usr/bin/env python3\nprint('x')\n"
    out = svc.detect_language(code, filename="script")
    assert out == "python"


def test_taskfile_maps_to_yaml_by_name():
    svc = importlib.import_module('services.code_service')
    code = "version: '3'\n\ntasks:\n  run:\n    cmds:\n      - echo hello\n"
    out = svc.detect_language(code, filename="Taskfile")
    assert out == "yaml"


def test_env_file_maps_to_env():
    svc = importlib.import_module('services.code_service')
    code = "BOT_TOKEN=\nSERVICE_ID=\n"
    out = svc.detect_language(code, filename=".env")
    assert out == "env"


def test_block_md_with_strong_python_overrides_to_python():
    svc = importlib.import_module('services.code_service')
    code = (
        '""" Docstring """\n'
        "import os, asyncio\n"
        "def acquire_lock():\n"
        "    pass\n"
    )
    out = svc.detect_language(code, filename="Block.md")
    assert out == "python"


def test_doc_md_with_plain_markdown_stays_markdown():
    svc = importlib.import_module('services.code_service')
    md = "# כותרת Markdown\n\n- רשימה\n- פריט נוסף\n"
    out = svc.detect_language(md, filename="doc.md")
    assert out == "markdown"


def test_notes_py_with_markdown_content_stays_python_due_to_strong_extension():
    svc = importlib.import_module('services.code_service')
    md_like = "# כותרת Markdown\n\n- רשימה\n- פריט נוסף\n"
    out = svc.detect_language(md_like, filename="notes.py")
    assert out == "python"


def test_yaml_without_extension_detected_by_content():
    svc = importlib.import_module('services.code_service')
    yaml_text = "name: ci\non: [push]\n"
    out = svc.detect_language(yaml_text, filename="ci")
    assert out == "yaml"


def test_plain_text_without_signals_is_text():
    svc = importlib.import_module('services.code_service')
    out = svc.detect_language("hello world", filename="readme")
    assert out in {"text", "markdown"}  # allow markdown if heuristics consider it

