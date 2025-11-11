import pytest


def test_basic_generation_png_signature():
    mod = __import__('services.image_generator', fromlist=['CodeImageGenerator'])
    G = getattr(mod, 'CodeImageGenerator')
    gen = G(style='monokai', theme='dark')
    out = gen.generate_image("print('Hello')", language='python', filename='a.py')
    assert isinstance(out, (bytes, bytearray))
    assert len(out) > 0
    assert bytes(out).startswith(b"\x89PNG")


def test_empty_code_raises():
    mod = __import__('services.image_generator', fromlist=['CodeImageGenerator'])
    G = getattr(mod, 'CodeImageGenerator')
    gen = G()
    with pytest.raises(ValueError):
        gen.generate_image("")


def test_multiline_and_width_limit():
    mod = __import__('services.image_generator', fromlist=['CodeImageGenerator'])
    G = getattr(mod, 'CodeImageGenerator')
    gen = G()
    code = "def x():\n    return 1+2+3\n" * 3
    out = gen.generate_image(code, language='python', max_width=800)
    assert isinstance(out, (bytes, bytearray))
    assert len(out) > 10
