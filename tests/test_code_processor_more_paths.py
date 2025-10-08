import importlib


def test_detect_language_and_stats_and_minify():
    mod = importlib.import_module('code_processor')
    cp = mod.code_processor

    ok, cleaned, msg = cp.validate_code_input("""
def f(x):
    # comment
    return x + 1
""", filename="f.py")
    assert ok and 'return' in cleaned

    # detect_language should at least return a string (fallbacks possible)
    lang = cp.detect_language(cleaned, filename="f.py")
    assert isinstance(lang, str)

    # highlight_code should return string; with small code may return same
    out = cp.highlight_code(cleaned, programming_language='python', output_format='html')
    assert isinstance(out, str)

    # create_code_image returns bytes or None (if PIL absent) — should not raise
    img = cp.create_code_image(cleaned, programming_language='python')
    assert (img is None) or isinstance(img, (bytes, bytearray))

    stats = cp.get_code_stats(cleaned)
    assert isinstance(stats, dict) and 'total_lines' in stats

    minified = cp.minify_code(cleaned, 'python')
    assert isinstance(minified, str) and len(minified) <= len(cleaned)

