class _AppWithGroup:
    def __init__(self):
        self.handlers = []
    def add_handler(self, handler, **kwargs):
        # Simulate full support for 'group'
        self.handlers.append((handler, kwargs))


class _AppNoGroup:
    def __init__(self):
        self.handlers = []
    def add_handler(self, handler, **kwargs):
        # Simulate environment that rejects 'group' kwarg
        if 'group' in kwargs:
            raise TypeError("unexpected 'group'")
        self.handlers.append((handler, kwargs))


def test_setup_favorites_with_group_support():
    import conversation_handlers as ch
    app = _AppWithGroup()
    ch.setup_favorites_category_handlers(app)
    # Expect two registrations with group=-5
    assert len(app.handlers) == 2
    for _handler, kwargs in app.handlers:
        assert kwargs.get('group') == -5
        # Ensure handler type is CallbackQueryHandler
        assert _handler.__class__.__name__ == 'CallbackQueryHandler'


def test_setup_favorites_without_group_support():
    import conversation_handlers as ch
    app = _AppNoGroup()
    ch.setup_favorites_category_handlers(app)
    # Expect two registrations without group kwarg
    assert len(app.handlers) == 2
    for _handler, kwargs in app.handlers:
        assert 'group' not in kwargs
        assert _handler.__class__.__name__ == 'CallbackQueryHandler'
