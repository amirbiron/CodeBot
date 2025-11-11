import pytest


def test_playwright_respects_max_height(monkeypatch):
    mod = __import__('services.image_generator', fromlist=['CodeImageGenerator'])
    G = getattr(mod, 'CodeImageGenerator')
    gen = G(style='monokai', theme='dark')

    # Force playwright usage and capture html
    html_capture = {}
    def fake_render(html_content: str, width: int, height: int):
        html_capture['html'] = html_content
        # Return a dummy PNG via PIL
        from PIL import Image
        import io
        im = Image.new('RGB', (width or 300, height or 200), (0, 0, 0))
        bio = io.BytesIO()
        im.save(bio, format='PNG')
        bio.seek(0)
        return Image.open(bio)

    monkeypatch.setattr(gen, '_has_playwright', True, raising=True)
    monkeypatch.setattr(gen, '_render_html_with_playwright', fake_render, raising=True)

    # Create 4 lines, force max_height to allow only 2 lines
    code = "L1\nL2\nL3\nL4\n"
    # Make LINE_HEIGHT small to control truncation math
    monkeypatch.setattr(gen, 'LINE_HEIGHT', 20, raising=True)
    # base_overhead ~ 144; with max_height=200 -> avail ~56 -> 2 lines at 20px
    out = gen.generate_image(code, language='text', filename='t.txt', max_width=600, max_height=200)

    assert bytes(out).startswith(b"\x89PNG")
    html = html_capture.get('html', '')
    # Only first two lines should appear
    assert 'L1' in html and 'L2' in html
    assert 'L3' not in html and 'L4' not in html
    # Line number count should be 2
    assert html.count('class="line-number"') == 2
