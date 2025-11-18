import pytest


@pytest.mark.asyncio
async def test_generator_supports_new_themes_and_fonts(monkeypatch):
    from services.image_generator import CodeImageGenerator

    gen = CodeImageGenerator(style='monokai', theme='gruvbox', font_family='cascadia')
    out = gen.generate_image("print('hi')", language='python', filename='a.py', max_width=600)
    assert isinstance(out, (bytes, bytearray)) and len(out) > 0
