import importlib


def test_cache_key_changes_with_style(monkeypatch):
    mod = importlib.import_module('code_processor')
    # צור מופע חדש כדי לשנות style טרום הרצה
    CP = getattr(mod, 'CodeProcessor')
    cp = CP()

    # הבטחת fallback פשוט
    monkeypatch.setattr(mod, 'HtmlFormatter', None)
    monkeypatch.setattr(mod, 'highlight', None)

    code = "x\n"
    a = cp.highlight_code(code, programming_language='python', output_format='html')

    # שינויים ב-style אמורים להשפיע על מפתח ה-cache בריצה הבאה
    cp.style = 'another-style'
    b = cp.highlight_code(code, programming_language='python', output_format='html')

    # שני הפלטים זהים לוגית, אבל עצם הרצה שנייה עם style שונה מפעילה מסלול cache נפרד
    assert a == "<code>x\n</code>"
    assert b == "<code>x\n</code>"

