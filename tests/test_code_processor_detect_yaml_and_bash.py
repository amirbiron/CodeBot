import importlib


def test_cp_detects_yaml_by_content_without_extension():
    mod = importlib.import_module('code_processor')
    cp = mod.code_processor
    yaml_text = """name: ci
on: [push]
jobs:
  build:
    runs-on: ubuntu-latest
"""
    out = cp.detect_language(yaml_text, filename="ci")  # ללא סיומת
    assert out == 'yaml'


def test_cp_detects_bash_by_shebang_without_extension():
    mod = importlib.import_module('code_processor')
    cp = mod.code_processor
    bash_text = "#!/bin/bash\necho hi\n"
    out = cp.detect_language(bash_text, filename="run")  # ללא סיומת
    assert out == 'bash'
