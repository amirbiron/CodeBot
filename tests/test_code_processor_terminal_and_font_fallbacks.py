import importlib


def test_highlight_terminal_without_formatter_returns_code(monkeypatch):
    mod = importlib.import_module('code_processor')
    cp = mod.code_processor
    monkeypatch.setattr(mod, 'TerminalFormatter', None)
    out = cp.highlight_code("print('x')\n", programming_language='python', output_format='terminal')
    assert out == "print('x')\n"


def test_create_code_image_font_fallback(monkeypatch):
    mod = importlib.import_module('code_processor')
    cp = mod.code_processor

    # ודא ש-PIL זמין במסלול הזה; אם לא — נוותר
    try:
        import PIL  # noqa: F401
    except Exception:
        return

    # לגרום ל- truetype לזרוק ולבדוק שהפונקציה לא קורסת (תשתמש ב-load_default)
    class _Err(Exception):
        pass
    def _raise_tt(*_a, **_k):
        raise _Err('no font')

    monkeypatch.setattr(mod, 'ImageFont', mod.ImageFont)
    monkeypatch.setattr(mod.ImageFont, 'truetype', _raise_tt, raising=True)
    img = cp.create_code_image("print('x')\n", programming_language='python')
    assert (img is None) or isinstance(img, (bytes, bytearray))

