import importlib


def test_html_formatter_present_but_highlight_none(monkeypatch):
    mod = importlib.import_module('code_processor')
    cp = mod.code_processor

    class DummyFmt:
        def __init__(self, *a, **k):
            pass

    monkeypatch.setattr(mod, 'HtmlFormatter', DummyFmt)
    monkeypatch.setattr(mod, 'highlight', None)
    # get_lexer_by_name מחזיר משהו כדי לא ליפול
    monkeypatch.setattr(mod, 'get_lexer_by_name', lambda name: object())

    out = cp.highlight_code("print('x')", programming_language='python', output_format='html')
    assert out == "<code>print('x')</code>"

