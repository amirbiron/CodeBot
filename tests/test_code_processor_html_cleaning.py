import importlib


def test_highlight_html_triggers_cleaning(monkeypatch):
    mod = importlib.import_module('code_processor')
    cp = mod.code_processor

    # Fake lexer and HtmlFormatter so that HTML branch נבחר
    monkeypatch.setattr(mod, 'get_lexer_by_name', lambda name: object())

    class DummyFmt:
        def __init__(self, *a, **k):
            pass
    monkeypatch.setattr(mod, 'HtmlFormatter', DummyFmt)

    # החזר HTML עם span + style + class כדי להפעיל ניקוי
    dirty_html = '<span class="x" style="color:red">code</span>'
    monkeypatch.setattr(mod, 'highlight', lambda code, lexer, fmt: dirty_html)

    out = cp.highlight_code("print('x')", programming_language='python', output_format='html')
    # ודא שניקינו style/class והחלפנו span ל-code
    assert '<span' not in out
    assert 'style=' not in out
    assert 'class=' not in out
    assert '<code>' in out and '</code>' in out

