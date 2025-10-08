import importlib


def test_code_processor_imports_without_optional_deps(monkeypatch):
    # נוודא שמודולים אופציונליים לא יפילו import
    # מסירים מודולים מה-sys.modules כדי לאלץ מסלולי fallback
    import sys
    for name in [
        'cairosvg', 'textstat', 'PIL', 'PIL.Image', 'PIL.ImageDraw', 'PIL.ImageFont',
        'pygments', 'pygments.lexers', 'pygments.formatters', 'pygments.styles', 'pygments.util',
        'langdetect']:
        sys.modules.pop(name, None)

    mod = importlib.import_module('code_processor')
    assert hasattr(mod, 'code_processor')

    # בדיקה שקריאה ל-API בסיסי לא קורסת (fallback)
    cp = mod.code_processor
    ok, cleaned, msg = cp.validate_code_input("print('hi')", filename="x.py")
    assert ok is True
    # highlight עשוי להחזיר את הקוד המקורי כשאין Pygments — לא אמור לקרוס
    res = cp.highlight_code("print('ok')", "python", output_format='html')
    assert isinstance(res, str)
