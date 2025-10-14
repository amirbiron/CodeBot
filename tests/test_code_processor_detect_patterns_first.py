import importlib


def test_detect_language_patterns_python_before_pygments(monkeypatch):
    mod = importlib.import_module('code_processor')
    cp = mod.code_processor

    # החזרת לקסר 'Groovy' כדי לאלץ מצב שבו אם מגיעים ל-Pygments נקבל לא-python
    class StubLexer:
        def __init__(self, name):
            self.name = name
    monkeypatch.setattr(mod, 'guess_lexer', lambda code: StubLexer('Groovy'))

    code = """
def func(x):
    return x + 1
"""
    # יש דפוסי Python ברורים — אמור לזהות python לפני Pygments
    out = cp.detect_language(code, filename=None)
    assert out == 'python'

