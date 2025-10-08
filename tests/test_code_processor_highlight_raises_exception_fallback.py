import importlib


def test_highlight_raises_exception_returns_fallback(monkeypatch):
    mod = importlib.import_module('code_processor')
    cp = mod.code_processor

    # ודא שיש פורמטור כדי להגיע לשורת highlight ואז לזרוק
    class DummyFmt:
        def __init__(self, *a, **k):
            pass
    monkeypatch.setattr(mod, 'HtmlFormatter', DummyFmt)

    # get_lexer_by_name יחזיר משהו לא None
    monkeypatch.setattr(mod, 'get_lexer_by_name', lambda name: object())

    class _Err(Exception):
        pass
    def _raise(*_a, **_k):
        raise _Err('boom')

    monkeypatch.setattr(mod, 'highlight', _raise)

    out = cp.highlight_code("print('x')", programming_language='python', output_format='html')
    # במסלול HTML fallback מחזיר עטיפה ב-code
    assert out == "<code>print('x')</code>"

