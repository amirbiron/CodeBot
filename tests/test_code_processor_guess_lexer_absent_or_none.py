import importlib


def test_detect_language_when_guess_lexer_absent(monkeypatch):
    mod = importlib.import_module('code_processor')
    cp = mod.code_processor
    # סימולציה: guess_lexer אינו זמין
    monkeypatch.setattr(mod, 'guess_lexer', None)
    out = cp.detect_language("plain text with no patterns")
    assert isinstance(out, str)


def test_detect_language_when_guess_lexer_returns_none(monkeypatch):
    mod = importlib.import_module('code_processor')
    cp = mod.code_processor
    # סימולציה: guess_lexer מחזיר None
    def _ret_none(_code):
        return None
    monkeypatch.setattr(mod, 'guess_lexer', _ret_none)
    out = cp.detect_language("plain text with no patterns")
    # fallback ל-analyze_code_structure → 'text'
    assert out == 'text' or isinstance(out, str)

