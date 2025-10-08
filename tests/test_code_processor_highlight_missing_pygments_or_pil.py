import importlib


def test_highlight_without_pygments_returns_code(monkeypatch):
    mod = importlib.import_module('code_processor')
    cp = mod.code_processor
    # השבתת highlight ו-HtmlFormatter
    monkeypatch.setattr(mod, 'highlight', None)
    monkeypatch.setattr(mod, 'HtmlFormatter', None)
    out = cp.highlight_code("print('x')", programming_language='python', output_format='html')
    assert out == "<code>print('x')</code>"


def test_create_code_image_without_pil_returns_none(monkeypatch):
    mod = importlib.import_module('code_processor')
    cp = mod.code_processor
    monkeypatch.setattr(mod, 'Image', None)
    monkeypatch.setattr(mod, 'ImageDraw', None)
    img = cp.create_code_image("print('x')", programming_language='python')
    assert img is None

