import importlib


def test_highlight_unknown_format_returns_code():
    mod = importlib.import_module('code_processor')
    cp = mod.code_processor
    out = cp.highlight_code("print('x')\n", programming_language='python', output_format='ansi')
    assert out == "print('x')\n"


def test_html_cleaning_exception_path(monkeypatch):
    mod = importlib.import_module('code_processor')
    cp = mod.code_processor

    class DummyFmt:
        def __init__(self, *a, **k):
            pass
    monkeypatch.setattr(mod, 'HtmlFormatter', DummyFmt)
    monkeypatch.setattr(mod, 'get_lexer_by_name', lambda name: object())

    class Weird:
        pass

    # highlight יחזיר אובייקט לא-מחרוזת → re.sub יזרוק, נתפוס ונחזיר את ה"HTML" כמות שהוא
    monkeypatch.setattr(mod, 'highlight', lambda code, lexer, fmt: Weird())
    res = cp.highlight_code("print('x')", programming_language='python', output_format='html')
    # במסלול שגיאה ב-HTML — מצפים לעטיפה ב-<code>...</code>
    assert isinstance(res, str)
    assert res == "<code>print('x')</code>"

