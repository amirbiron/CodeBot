import importlib


def test_detect_language_html_and_sql_and_unknown(monkeypatch):
    mod = importlib.import_module('code_processor')
    cp = mod.code_processor

    class StubLexer:
        def __init__(self, name):
            self.name = name

    # HTML mapping
    monkeypatch.setattr(mod, 'guess_lexer', lambda code: StubLexer('HTML 5'))
    assert cp.detect_language("no patterns here") == 'html'

    # SQL mapping
    monkeypatch.setattr(mod, 'guess_lexer', lambda code: StubLexer('SQL'))
    assert cp.detect_language("no patterns here") == 'sql'

    # Unknown — should return the lowercased name as-is
    monkeypatch.setattr(mod, 'guess_lexer', lambda code: StubLexer('Groovy'))
    out = cp.detect_language("no patterns here")
    assert isinstance(out, str) and 'groovy' in out

