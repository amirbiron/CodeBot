import importlib


def test_lexer_detection_fails_then_get_text_fallback(monkeypatch):
    mod = importlib.import_module('code_processor')
    cp = mod.code_processor

    class CNF(mod.ClassNotFound):
        pass

    def raise_cnf(_code):
        raise CNF('no lexer')

    # get_lexer_by_name('text') יזרוק — נוודא שהקוד מחזיר code ולא קורס
    monkeypatch.setattr(mod, 'get_lexer_by_name', lambda name: (_ for _ in ()).throw(Exception('fail text')))
    monkeypatch.setattr(mod, 'guess_lexer', raise_cnf)

    out = cp.highlight_code("plain", programming_language='text', output_format='terminal')
    assert out == "plain"

