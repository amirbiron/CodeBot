import importlib


def test_detect_language_by_filename_extension():
    mod = importlib.import_module('code_processor')
    cp = mod.code_processor
    out = cp.detect_language("ignored", filename="file.py")
    assert out == 'python'

