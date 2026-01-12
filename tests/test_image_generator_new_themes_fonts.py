import pytest


@pytest.mark.asyncio
async def test_generator_supports_new_themes_and_fonts(monkeypatch):
    from services.image_generator import CodeImageGenerator

    gen = CodeImageGenerator(style='monokai', theme='gruvbox', font_family='cascadia')
    out = gen.generate_image("print('hi')", language='python', filename='a.py', max_width=600)
    assert isinstance(out, (bytes, bytearray)) and len(out) > 0


@pytest.mark.asyncio
async def test_generator_supports_banner_tech_theme_and_style(monkeypatch):
    from services.image_generator import CodeImageGenerator

    gen = CodeImageGenerator(style='banner_tech', theme='banner_tech', font_family='dejavu')
    out = gen.generate_image("print('hi')", language='python', filename='a.py', max_width=600)
    assert isinstance(out, (bytes, bytearray)) and len(out) > 0
    assert bytes(out).startswith(b"\x89PNG")
