import importlib
import types
import pytest


def _reload_module():
    # טען את המודול מחדש כדי לוודא ש-monkeypatch משפיע כנדרש
    return importlib.import_module('code_processor')


def test_sanitize_code_blocks_variants():
    mod = _reload_module()
    cp = mod.code_processor

    text_with_lang = "before\n```python\nprint(1)\n```\nafter\n"
    out = cp.sanitize_code_blocks(text_with_lang)
    assert "```" not in out
    assert "before" in out and "after" in out
    assert "print(1)" in out

    text_no_lang = "```\nconst x = 1;\n```"
    out2 = cp.sanitize_code_blocks(text_no_lang)
    assert out2 == "const x = 1;"

    plain = "no code fences here"
    assert cp.sanitize_code_blocks(plain) == plain


def test_validate_code_input_non_str_empty_long_and_unicode_error(monkeypatch):
    mod = _reload_module()
    cp = mod.code_processor

    ok, cleaned, msg = cp.validate_code_input(123)  # not a string
    assert ok is False and cleaned == ""

    ok, cleaned, msg = cp.validate_code_input("```python\n \n```", filename="x.py")
    assert ok is False and "ריק" in msg

    ok, cleaned, msg = cp.validate_code_input("a" * 50001)
    assert ok is False and "ארוך מדי" in msg

    # גרום ל-UnicodeEncodeError בעזרת סורוגייט לא מזווג
    bad = "bad surrogate: " + "\ud800"
    ok, cleaned, msg = cp.validate_code_input(bad)
    assert ok is False and "לא חוקיים" in msg

    # נרמול שמתרסק — נוודא שמתבצע fallback ולא קורס
    def boom(*args, **kwargs):
        raise RuntimeError("normalize fail")

    monkeypatch.setattr(mod, 'normalize_code', boom, raising=True)
    ok, cleaned, msg = cp.validate_code_input("print('hi')", filename="x.py")
    assert ok is True and "print('hi')" in cleaned


def test_detect_language_patterns_guess_and_structure(monkeypatch):
    mod = _reload_module()
    cp = mod.code_processor

    # דפוסים ללא סיומת
    css_code = "body { color: red; }"
    assert cp.detect_language(css_code) == 'css'

    # הכרחה למסלול guess_lexer
    class _Lexer:  # stub
        name = 'Python 3'

    monkeypatch.setattr(mod, 'get_lexer_by_name', lambda *_a, **_k: (_ for _ in ()).throw(mod.ClassNotFound('x')))
    monkeypatch.setattr(mod, 'guess_lexer', lambda _c: _Lexer())
    assert cp.detect_language("def f():\n  return 1") == 'python'

    # כשגם guess נכשל — ניפול לניתוח מבני
    monkeypatch.setattr(mod, 'guess_lexer', lambda _c: (_ for _ in ()).throw(mod.ClassNotFound('x')))
    structured = "\n".join(["    a", "    b", "    c", "    d"])  # indent_ratio גבוה
    assert cp.detect_language(structured) == 'python'


def test_highlight_code_fallbacks_and_terminal_unavailable(monkeypatch):
    mod = _reload_module()
    cp = mod.code_processor

    # קוד קצר ב-HTML — עטיפת <code>
    assert cp.highlight_code("foo", 'python', 'html') == "<code>foo</code>"

    # Terminal ללא formatter/pygments
    monkeypatch.setattr(mod, 'TerminalFormatter', None, raising=True)
    term = cp.highlight_code("print('x')" * 2, 'python', 'terminal')
    assert term == "print('x')" * 2


def test_highlight_code_cached_with_clean_html(monkeypatch):
    mod = _reload_module()
    cp = mod.code_processor

    # Stubs ל-Pygments כדי להחזיר HTML עם span/class/style שדורשים ניקוי
    class _Fmt:
        def __init__(self, *a, **k):
            pass

    class _Lx:  # lexer stub
        pass

    monkeypatch.setattr(mod, 'HtmlFormatter', _Fmt, raising=True)
    monkeypatch.setattr(mod, 'get_lexer_by_name', lambda name: _Lx(), raising=True)

    def _fake_highlight(code, lexer, formatter):
        return '<span class="x" style="y">hello</span>'

    monkeypatch.setattr(mod, 'highlight', _fake_highlight, raising=True)

    out = cp.highlight_code("print(1234)", 'python', 'html')
    assert '<span' not in out and 'class="' not in out and 'style="' not in out
    assert '<code>' in out and '</code>' in out and 'hello' in out


def test_highlight_code_cached_total_lexer_failure(monkeypatch):
    mod = _reload_module()
    cp = mod.code_processor

    # כשלא ניתן להשיג אפילו lexer של 'text' וגם guess נכשל — נחזיר את הקוד כמו שהוא
    def _raise_any(*_a, **_k):
        raise Exception('no lexer')

    monkeypatch.setattr(mod, 'get_lexer_by_name', _raise_any, raising=True)
    monkeypatch.setattr(mod, 'guess_lexer', lambda _c: (_ for _ in ()).throw(mod.ClassNotFound('x')))

    code = "some code that will fall back"
    out = cp.highlight_code(code, 'unknownlang', 'html')
    # עקביות: במצבי כשל מוחזר HTML עטוף ב-<code>...</code>
    assert out == f"<code>{code}</code>"


def test_create_code_image_with_stubbed_pil(monkeypatch):
    mod = _reload_module()
    cp = mod.code_processor

    class _StubImage:
        def __init__(self, width, height):
            self.width = width
            self.height = height

        def save(self, io, format='PNG'):
            io.write(b'PNG')

        @staticmethod
        def new(_mode, size, _color):
            return _StubImage(size[0], size[1])

    class _StubImageDraw:
        class _Drawer:
            def __init__(self, _img):
                pass

            def text(self, *_a, **_k):
                return None

        @staticmethod
        def Draw(img):
            return _StubImageDraw._Drawer(img)

    class _StubImageFont:
        @staticmethod
        def truetype(*_a, **_k):
            raise RuntimeError('no font')

        @staticmethod
        def load_default():
            return object()

    monkeypatch.setattr(mod, 'Image', _StubImage, raising=True)
    monkeypatch.setattr(mod, 'ImageDraw', _StubImageDraw, raising=True)
    monkeypatch.setattr(mod, 'ImageFont', _StubImageFont, raising=True)

    img_bytes = cp.create_code_image("line1\nline2\nline3", 'python')
    assert isinstance(img_bytes, (bytes, bytearray)) and img_bytes.startswith(b'PNG')


def test_get_code_stats_with_textstat_present(monkeypatch):
    mod = _reload_module()
    cp = mod.code_processor

    class _TS:
        @staticmethod
        def flesch_reading_ease(_t):
            return 55

    monkeypatch.setattr(mod, 'textstat', _TS(), raising=True)
    stats = cp.get_code_stats("def x():\n    return 1\n")
    assert stats.get('readability_score') == 55


def test_analyze_code_python_smells_and_syntax():
    mod = _reload_module()
    cp = mod.code_processor

    report = cp.analyze_code("def x(:\n    eval('1')\n", 'python')
    assert isinstance(report, dict)
    assert report.get('quality_score', 100) < 90
    smells = report.get('code_smells', [])
    assert any('eval' in s for s in smells)
    assert any('תחביר' in s for s in smells)


def test_extract_functions_python():
    mod = _reload_module()
    cp = mod.code_processor

    funcs = cp.extract_functions("""
def foo(x):
    return x

def bar():
    pass
""", 'python')
    names = {f['name'] for f in funcs}
    assert {'foo', 'bar'} <= names


def test_validate_syntax_json_error():
    mod = _reload_module()
    cp = mod.code_processor

    res = cp.validate_syntax("{bad: json}", 'json')
    assert res.get('is_valid') is False
    assert any(e.get('type') == 'JSONDecodeError' for e in res.get('errors', []))


def test_batch_highlight_and_analyze_with_error_handling(monkeypatch):
    mod = _reload_module()
    cp = mod.code_processor

    # highlight_code_batch: כשקריאה פנימית נכשלת, מוחזרים הקודים עצמם
    def boom_highlight(self, code, programming_language, output_format='html'):
        raise RuntimeError('boom')

    monkeypatch.setattr(mod.CodeProcessor, 'highlight_code', boom_highlight, raising=True)
    res = cp.highlight_code_batch([
        {'file_name': 'a.py', 'code': 'print(1)', 'programming_language': 'python'},
        {'file_name': 'b.js', 'code': 'console.log(1);', 'programming_language': 'javascript'},
    ], output_format='html')
    assert res['a.py'] == 'print(1)'
    assert res['b.js'] == 'console.log(1);'

    # analyze_code_batch: החזר תוצאות בסיסיות
    out = cp.analyze_code_batch([
        {'file_name': 'x.py', 'code': 'def f():\n  return 1', 'programming_language': 'python'},
        {'file_name': 'y.sql', 'code': 'SELECT * FROM t', 'programming_language': 'sql'},
    ])
    assert 'x.py' in out and isinstance(out['x.py'], dict)
    assert 'y.sql' in out and isinstance(out['y.sql'], dict)

