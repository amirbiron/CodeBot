import importlib


def test_highlight_html_empty_and_small():
    mod = importlib.import_module('code_processor')
    cp = mod.code_processor

    out_empty = cp.highlight_code("", programming_language='python', output_format='html')
    assert out_empty == "<code></code>"

    out_small = cp.highlight_code("x\n", programming_language='python', output_format='html')
    assert out_small == "<code>x\n</code>"


def test_highlight_terminal_empty_and_small(monkeypatch):
    mod = importlib.import_module('code_processor')
    cp = mod.code_processor
    # אם יש TerminalFormatter, ננטרל כדי לבדוק fallback
    monkeypatch.setattr(mod, 'TerminalFormatter', None)

    out_empty = cp.highlight_code("", programming_language='python', output_format='terminal')
    assert out_empty == ""

    out_small = cp.highlight_code("x\n", programming_language='python', output_format='terminal')
    assert out_small == "x\n"

