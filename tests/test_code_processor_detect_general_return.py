import importlib


def test_detect_language_general_return_lowercased(monkeypatch):
    mod = importlib.import_module('code_processor')
    cp = mod.code_processor

    class StubLexer:
        def __init__(self, name):
            self.name = name

    # שם לא מכוסה במיפויים — אמור לחזור כפי שהוא (lowercase)
    monkeypatch.setattr(mod, 'guess_lexer', lambda code: StubLexer('GroovyDSL'))
    out = cp.detect_language("no patterns here")
    assert isinstance(out, str) and out == 'groovydsl'

