import importlib


def test_detect_language_json_structure():
    mod = importlib.import_module('code_processor')
    cp = mod.code_processor
    code = '{"a": 1, "b": 2}'
    out = cp.detect_language(code)
    assert out == 'json'


def test_detect_language_javascript_structure():
    mod = importlib.import_module('code_processor')
    cp = mod.code_processor
    # הרבה שורות עם ; ו-{} כדי לעבור את הסף
    code = "\n".join([
        "function f(){ return 1; }",
        "let x = 1;",
        "if (x) { x = x + 1; };",
        "for (let i=0;i<3;i++){ x++; };",
        "console.log(x);",
    ])
    out = cp.detect_language(code)
    assert out == 'javascript'

