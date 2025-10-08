import importlib


def test_terminal_formatter_present_but_highlight_missing(monkeypatch):
    mod = importlib.import_module('code_processor')
    cp = mod.code_processor

    class DummyTF:
        def __init__(self, *a, **k):
            pass

    monkeypatch.setattr(mod, 'TerminalFormatter', DummyTF)
    monkeypatch.setattr(mod, 'highlight', None)

    code = "print('x')\n"
    out = cp.highlight_code(code, programming_language='python', output_format='terminal')
    assert out == code

