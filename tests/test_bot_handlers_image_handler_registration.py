class _AppCapture:
    def __init__(self):
        self.handlers = []

    def add_handler(self, handler, **kwargs):
        self.handlers.append((handler, dict(kwargs)))


class _AppNoGroup:
    def __init__(self):
        self.handlers = []

    def add_handler(self, handler, **kwargs):
        if 'group' in kwargs:
            raise TypeError("group unsupported")
        self.handlers.append((handler, dict(kwargs)))


def _is_image_handler(handler):
    pattern = getattr(handler, 'pattern', None)
    # ב-PTB אמיתי זה יכול להיות re.Pattern; בסטאבים זה לרוב מחרוזת
    if hasattr(pattern, "pattern"):
        try:
            pattern = pattern.pattern
        except Exception:
            pattern = None
    pattern = pattern or ''
    return isinstance(pattern, str) and 'regenerate_image_' in pattern and 'img_set_theme' in pattern


def test_image_handler_group_priority():
    import bot_handlers as bh

    app = _AppCapture()
    bh.AdvancedBotHandlers(app)

    matches = [
        (handler, kwargs)
        for handler, kwargs in app.handlers
        if _is_image_handler(handler)
    ]
    assert matches, "image handler not registered"
    for _, kwargs in matches:
        assert kwargs.get('group') == -5


def test_image_handler_registers_without_group_support():
    import bot_handlers as bh

    app = _AppNoGroup()
    bh.AdvancedBotHandlers(app)

    assert any(_is_image_handler(handler) for handler, _ in app.handlers)
