import io
import sys
import types
from collections import Counter

import pytest


def _install_fake_async_playwright(monkeypatch, size=(320, 180), color=(12, 34, 56)):
    from PIL import Image

    capture = {}
    counts = Counter()

    buf = io.BytesIO()
    Image.new('RGB', size, color).save(buf, format='PNG')
    png_bytes = buf.getvalue()

    class FakePage:
        def __init__(self):
            self.closed = False

        async def set_content(self, html_content, wait_until='load'):
            capture['html'] = html_content
            capture['wait_until'] = wait_until

        async def wait_for_timeout(self, ms):
            capture['timeout'] = ms

        async def screenshot(self, type='png', full_page=True):
            capture['screenshot_kwargs'] = {'type': type, 'full_page': full_page}
            return png_bytes

        async def close(self):
            self.closed = True
            counts['page'] += 1

    class FakeBrowser:
        def __init__(self):
            self.closed = False
            self.page = FakePage()

        async def new_page(self, **kwargs):
            capture['viewport'] = kwargs.get('viewport')
            capture['device_scale_factor'] = kwargs.get('device_scale_factor')
            return self.page

        async def close(self):
            self.closed = True
            counts['browser'] += 1

    class FakePlaywright:
        def __init__(self):
            self.chromium = self

        async def launch(self, headless=True):
            capture['headless'] = headless
            return FakeBrowser()

    class FakeAsyncContext:
        async def __aenter__(self):
            counts['ctx_enter'] += 1
            return FakePlaywright()

        async def __aexit__(self, exc_type, exc, tb):
            counts['ctx_exit'] += 1

    def fake_async_playwright():
        capture['factory_calls'] = capture.get('factory_calls', 0) + 1
        return FakeAsyncContext()

    fake_async_module = types.ModuleType('playwright.async_api')
    fake_async_module.async_playwright = fake_async_playwright

    fake_root = types.ModuleType('playwright')
    fake_root.async_api = fake_async_module

    monkeypatch.setitem(sys.modules, 'playwright', fake_root)
    monkeypatch.setitem(sys.modules, 'playwright.async_api', fake_async_module)

    return capture, counts, png_bytes, size


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


def test_render_html_with_playwright_outside_loop(monkeypatch):
    capture, counts, _png, size = _install_fake_async_playwright(monkeypatch, size=(360, 210))
    mod = __import__('services.image_generator', fromlist=['CodeImageGenerator'])
    G = getattr(mod, 'CodeImageGenerator')
    gen = G(style='monokai', theme='dark')

    run_calls = []
    original_run = mod.asyncio.run

    def tracking_run(coro):
        run_calls.append('called')
        return original_run(coro)

    monkeypatch.setattr(mod.asyncio, 'run', tracking_run, raising=False)

    img = gen._render_html_with_playwright("<div>בדיקה</div>", width=size[0], height=size[1])
    img.load()

    assert img.size == size
    assert capture['viewport'] == {'width': size[0], 'height': size[1]}
    assert capture['device_scale_factor'] == 2
    assert capture['wait_until'] == 'load'
    assert capture['timeout'] == 300
    assert capture['screenshot_kwargs'] == {'type': 'png', 'full_page': True}
    assert capture['headless'] is True
    assert counts['ctx_enter'] == 1
    assert counts['page'] == 1
    assert counts['browser'] == 1
    assert counts['ctx_exit'] == 1
    assert run_calls == ['called']


@pytest.mark.asyncio
async def test_render_html_with_playwright_running_loop(monkeypatch):
    capture, counts, _png, size = _install_fake_async_playwright(monkeypatch, size=(280, 160), color=(40, 50, 60))
    mod = __import__('services.image_generator', fromlist=['CodeImageGenerator'])
    G = getattr(mod, 'CodeImageGenerator')
    gen = G(style='monokai', theme='dark')

    run_calls = []
    original_run = mod.asyncio.run

    def tracking_run(coro):
        run_calls.append('called')
        return original_run(coro)

    monkeypatch.setattr(mod.asyncio, 'run', tracking_run, raising=False)

    from concurrent.futures import ThreadPoolExecutor as RealExecutor

    branch = {}

    class InstrumentedExecutor(RealExecutor):
        def __init__(self, *args, **kwargs):
            branch['thread_name_prefix'] = kwargs.get('thread_name_prefix')
            super().__init__(*args, **kwargs)

        def submit(self, fn, *args, **kwargs):
            branch['submitted'] = True
            return super().submit(fn, *args, **kwargs)

    monkeypatch.setattr(mod, 'ThreadPoolExecutor', InstrumentedExecutor, raising=True)

    img = gen._render_html_with_playwright("<div>לול</div>", width=size[0], height=size[1])
    img.load()

    assert img.size == size
    assert capture['viewport'] == {'width': size[0], 'height': size[1]}
    assert capture['device_scale_factor'] == 2
    assert counts['ctx_enter'] == 1
    assert counts['page'] == 1
    assert counts['browser'] == 1
    assert counts['ctx_exit'] == 1
    assert run_calls == ['called']
    assert branch.get('thread_name_prefix') == "code-image-playwright"
    assert branch.get('submitted') is True
