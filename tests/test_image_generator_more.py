import pytest


def _get_gen():
    mod = __import__('services.image_generator', fromlist=['CodeImageGenerator'])
    G = getattr(mod, 'CodeImageGenerator')
    return G(style='monokai', theme='dark')


def test_html_to_text_colors_basic():
    gen = _get_gen()
    html = (
        "<style>.x{}</style><script>bad()</script>"
        "<span style=\"color: red\">Hello</span> World"
    )
    pairs = gen._html_to_text_colors(html)
    # should include the colored span text
    assert any(t == 'Hello' and c.strip().lower() == 'red' for t, c in pairs)


def test_detect_language_heuristics():
    gen = _get_gen()
    py = gen._detect_language_from_content("def x():\n    return 1\n")
    js = gen._detect_language_from_content("function a(){return 1}")
    assert py == 'python'
    assert js == 'javascript'
