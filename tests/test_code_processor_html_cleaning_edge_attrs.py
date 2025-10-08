import importlib


def test_html_cleaning_removes_style_and_class_without_span(monkeypatch):
    mod = importlib.import_module('code_processor')
    cp = mod.code_processor

    # פורמטור זמין אך highlight יחזיר div עם class/style ללא span
    class DummyFmt:
        def __init__(self, *a, **k):
            pass
    monkeypatch.setattr(mod, 'HtmlFormatter', DummyFmt)
    monkeypatch.setattr(mod, 'get_lexer_by_name', lambda name: object())

    dirty = '<div class="c" style="color:red">code</div>'
    monkeypatch.setattr(mod, 'highlight', lambda code, lexer, fmt: dirty)

    out = cp.highlight_code("code", programming_language='python', output_format='html')
    assert 'class=' not in out and 'style=' not in out
    # אין span ולכן לא יוחלף ל-code; אבל עדיין תהיה מחרוזת נקייה
    assert isinstance(out, str)

