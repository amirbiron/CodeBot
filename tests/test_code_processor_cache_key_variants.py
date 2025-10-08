import importlib


def test_cache_key_diff_between_terminal_and_html(monkeypatch):
    mod = importlib.import_module('code_processor')
    cp = mod.code_processor

    # הבטחת מסלולי fallback קלים כדי לא להסתמך על Pygments
    monkeypatch.setattr(mod, 'TerminalFormatter', None)
    monkeypatch.setattr(mod, 'HtmlFormatter', None)
    monkeypatch.setattr(mod, 'highlight', None)

    code = "x\n"
    a = cp.highlight_code(code, programming_language='python', output_format='terminal')
    b = cp.highlight_code(code, programming_language='python', output_format='html')

    # terminal → קוד גולמי; html → עטוף ב-code
    assert a == code
    assert b == f"<code>{code}</code>"

