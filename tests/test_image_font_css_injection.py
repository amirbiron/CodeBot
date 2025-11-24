import io
import pytest


@pytest.mark.asyncio
async def test_selected_font_family_is_injected_into_html(monkeypatch):
    from services.image_generator import CodeImageGenerator

    captured = {}

    def fake_render(html_content: str, width: int, height: int):
        captured['html'] = html_content
        # Return a minimal valid PNG via PIL
        from PIL import Image
        im = Image.new('RGB', (max(width, 50) or 50, max(height, 30) or 30), (0, 0, 0))
        bio = io.BytesIO()
        im.save(bio, format='PNG')
        bio.seek(0)
        return Image.open(bio)

    gen = CodeImageGenerator(style='monokai', theme='dark', font_family='jetbrains')
    # Force playwright path and stub renderer
    monkeypatch.setattr(gen, '_has_playwright', True, raising=True)
    monkeypatch.setattr(gen, '_render_html_with_playwright', fake_render, raising=True)

    out = gen.generate_image("print('ok')", language='python', filename='x.py', max_width=400)

    assert bytes(out).startswith(b"\x89PNG")
    html = captured.get('html') or ''
    # Ensure selected font and Hebrew-friendly fallback appear
    assert "JetBrains Mono" in html
    assert "DejaVu Sans Mono" in html
    # Ensure we did not inject a Python tuple like ("...") into CSS
    assert "font-family:(" not in html.replace(" ", "")


@pytest.mark.asyncio
async def test_user_style_tag_is_escaped(monkeypatch):
    from services.image_generator import CodeImageGenerator

    captured = {}

    def fake_render(html_content: str, width: int, height: int):
        captured['html'] = html_content
        from PIL import Image
        im = Image.new('RGB', (max(width, 50) or 50, max(height, 30) or 30), (0, 0, 0))
        bio = io.BytesIO()
        im.save(bio, format='PNG')
        bio.seek(0)
        return Image.open(bio)

    gen = CodeImageGenerator(style='monokai', theme='dark')
    monkeypatch.setattr(gen, '_has_playwright', True, raising=True)
    monkeypatch.setattr(gen, '_render_html_with_playwright', fake_render, raising=True)

    snippet = "<style> body { display: none; } </style>"
    _ = gen.generate_image(snippet, language='html', max_width=320)

    html_doc = captured.get('html') or ''
    # אין תגית style אמיתית בתוך אזור הקוד (היא הומרה ל-span-ים בטוחים)
    assert '<div class="code"><pre><code><style>' not in html_doc
    assert '&lt;style&gt;' in html_doc  # וידוא שהתווים הומרו ל-entities
