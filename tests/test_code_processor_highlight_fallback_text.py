import importlib


def test_highlight_fallback_to_text_when_lexers_fail(monkeypatch):
    mod = importlib.import_module('code_processor')
    cp = mod.code_processor

    class DummyFmt:
        def __init__(self, *a, **k):
            pass

    # get_lexer_by_name('python') יזרוק, גם guess_lexer יזרוק; לבסוף get_lexer_by_name('text') יחזור
    class CNF(mod.ClassNotFound):
        pass

    def raise_cnf(*_a, **_k):
        raise CNF('no lexer')

    calls = {"text": 0}

    def get_lexer_by_name_stub(name):
        if name == 'text':
            calls["text"] += 1
            return object()
        raise CNF('no lexer')

    monkeypatch.setattr(mod, 'get_lexer_by_name', get_lexer_by_name_stub)
    monkeypatch.setattr(mod, 'guess_lexer', raise_cnf)
    monkeypatch.setattr(mod, 'HtmlFormatter', DummyFmt)

    html = '<span class="x">hello world !!!</span>'
    monkeypatch.setattr(mod, 'highlight', lambda code, lexer, fmt: html)

    out = cp.highlight_code("hello world !!!", programming_language='python', output_format='html')
    # וידוא שהגענו ל-text ולניקוי
    assert calls["text"] >= 1
    assert '<span' not in out and '<code>' in out

