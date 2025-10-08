import importlib


def test_detect_language_with_pygments_variants(monkeypatch):
    mod = importlib.import_module('code_processor')
    cp = mod.code_processor

    class StubLexer:
        def __init__(self, name):
            self.name = name

    # Python variant
    monkeypatch.setattr(mod, 'guess_lexer', lambda code: StubLexer('Python 3'))
    assert cp.detect_language("no patterns here") == 'python'

    # JavaScript variant
    monkeypatch.setattr(mod, 'guess_lexer', lambda code: StubLexer('JavaScript'))
    assert cp.detect_language("no patterns here") == 'javascript'

    # Bash variant (avoid language pattern matches to ensure Pygments path)
    monkeypatch.setattr(mod, 'guess_lexer', lambda code: StubLexer('Bash'))
    out = cp.detect_language("no patterns here")
    assert out == 'bash'

    # ClassNotFound path
    class CNF(mod.ClassNotFound):
        pass
    def raise_cnf(_):
        raise CNF('x')
    monkeypatch.setattr(mod, 'guess_lexer', raise_cnf)
    res = cp.detect_language("plain text only")
    assert isinstance(res, str)

