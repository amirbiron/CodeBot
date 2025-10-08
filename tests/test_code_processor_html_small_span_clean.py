import importlib


def test_html_small_code_with_span_gets_cleaned(monkeypatch):
    mod = importlib.import_module('code_processor')
    cp = mod.code_processor

    class DummyFmt:
        def __init__(self, *a, **k):
            pass
    monkeypatch.setattr(mod, 'HtmlFormatter', DummyFmt)
    monkeypatch.setattr(mod, 'get_lexer_by_name', lambda name: object())

    # קוד קצר מאוד (שגם עובר סף <10 תווים במסלול הראשי), אבל כאן אנחנו עוקפים את בדיקת האורך
    # כי highlight מוחזר ישירות
    highlighted = '<span class="x" style="color:red">x</span>'
    monkeypatch.setattr(mod, 'highlight', lambda code, lexer, fmt: highlighted)

    out = cp.highlight_code("x", programming_language='python', output_format='html')
    assert '<span' not in out and 'style=' not in out and 'class=' not in out
    assert '<code>' in out and '</code>' in out

