import importlib


def test_detect_language_pygments_css_and_java(monkeypatch):
    mod = importlib.import_module('code_processor')
    cp = mod.code_processor

    class StubLexer:
        def __init__(self, name):
            self.name = name

    # CSS
    monkeypatch.setattr(mod, 'guess_lexer', lambda code: StubLexer('CSS'))
    assert cp.detect_language("no patterns here") == 'css'

    # Java
    monkeypatch.setattr(mod, 'guess_lexer', lambda code: StubLexer('Java'))
    assert cp.detect_language("no patterns here") == 'java'

