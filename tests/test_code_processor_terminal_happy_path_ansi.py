import importlib


def test_terminal_happy_path_returns_ansi(monkeypatch):
    mod = importlib.import_module('code_processor')
    cp = mod.code_processor

    class DummyTF:
        def __init__(self, *a, **k):
            pass
    monkeypatch.setattr(mod, 'TerminalFormatter', DummyTF)
    monkeypatch.setattr(mod, 'get_lexer_by_name', lambda name: object())

    ansi_sample = "\x1b[36mprint\x1b[39;49;00m('x')\n"
    monkeypatch.setattr(mod, 'highlight', lambda code, lexer, fmt: ansi_sample)

    out = cp.highlight_code("print('x')\n", programming_language='python', output_format='terminal')
    assert out == ansi_sample

