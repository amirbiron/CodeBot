import pytest


def _pil_image_bytes(w=200, h=120, color=(10, 20, 30)):
    mod_pil = __import__('PIL.Image', fromlist=['Image'])
    Image = getattr(mod_pil, 'Image')
    img = Image.new('RGB', (w, h), color)
    import io
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return buf.getvalue()


def test_playwright_path_is_used(monkeypatch):
    mod = __import__('services.image_generator', fromlist=['CodeImageGenerator'])
    G = getattr(mod, 'CodeImageGenerator')

    # Force playwright path and capture HTML
    html_captured = {}
    def fake_render(html_content: str, width: int, height: int):
        html_captured['content'] = html_content
        # Return a small valid PNG rendered via PIL
        mod_pil = __import__('PIL.Image', fromlist=['Image'])
        Image = getattr(mod_pil, 'Image')
        import io
        im = Image.new('RGB', (width or 200, height or 120), (0, 0, 0))
        bio = io.BytesIO()
        im.save(bio, format='PNG')
        bio.seek(0)
        return Image.open(bio)

    gen = G(style='monokai', theme='dark')
    monkeypatch.setattr(gen, '_has_playwright', True, raising=True)
    monkeypatch.setattr(gen, '_render_html_with_playwright', fake_render, raising=True)

    out = gen.generate_image("print('x')", language='python', filename='a.py')
    assert bytes(out).startswith(b"\x89PNG")
    assert 'class="line-number"' in html_captured.get('content', '')
    assert '@my_code_keeper_bot' in html_captured.get('content', '')


def test_weasyprint_path_is_used(monkeypatch):
    mod = __import__('services.image_generator', fromlist=['CodeImageGenerator'])
    G = getattr(mod, 'CodeImageGenerator')
    gen = G(style='monokai', theme='dark')

    html_seen = {}
    def fake_weasy(html_content: str, width: int, height: int):
        html_seen['ok'] = True
        # Return a PIL image
        mod_pil = __import__('PIL.Image', fromlist=['Image'])
        Image = getattr(mod_pil, 'Image')
        import io
        im = Image.new('RGB', (width or 160, height or 90), (1, 2, 3))
        bio = io.BytesIO()
        im.save(bio, format='PNG')
        bio.seek(0)
        return Image.open(bio)

    # Force playwright off, weasyprint on
    monkeypatch.setattr(gen, '_has_playwright', False, raising=True)
    monkeypatch.setattr(gen, '_has_weasyprint', True, raising=True)
    monkeypatch.setattr(gen, '_render_html_with_weasyprint', fake_weasy, raising=True)

    out = gen.generate_image("console.log('x')", language='javascript', filename='a.js')
    assert bytes(out).startswith(b"\x89PNG")
    assert html_seen.get('ok') is True


def test_pil_fallback_path(monkeypatch):
    mod = __import__('services.image_generator', fromlist=['CodeImageGenerator'])
    G = getattr(mod, 'CodeImageGenerator')
    gen = G(style='monokai', theme='dark')

    # Disable html renderers
    monkeypatch.setattr(gen, '_has_playwright', False, raising=True)
    monkeypatch.setattr(gen, '_has_weasyprint', False, raising=True)

    code = "def a():\n\treturn 1\n"
    out = gen.generate_image(code, language='python', filename='b.py', max_width=600)
    assert bytes(out).startswith(b"\x89PNG")


def test_html_to_text_colors_preserves_leading_spaces():
    mod = __import__('services.image_generator', fromlist=['CodeImageGenerator'])
    G = getattr(mod, 'CodeImageGenerator')
    gen = G(style='monokai', theme='dark')
    html = '<span style="color: #ff0000">    indented</span>'
    pairs = gen._html_to_text_colors(html)
    assert any(t.startswith('    ') for t, _ in pairs)
