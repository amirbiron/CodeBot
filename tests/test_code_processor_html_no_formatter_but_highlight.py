import importlib


def test_html_no_formatter_but_highlight_present(monkeypatch):
    mod = importlib.import_module('code_processor')
    cp = mod.code_processor

    # אין HtmlFormatter, יש highlight → fallback ל-<code>...></code>
    monkeypatch.setattr(mod, 'HtmlFormatter', None)
    monkeypatch.setattr(mod, 'highlight', lambda code, lexer, fmt: code)

    out = cp.highlight_code("print('x')", programming_language='python', output_format='html')
    assert out == "<code>print('x')</code>"

