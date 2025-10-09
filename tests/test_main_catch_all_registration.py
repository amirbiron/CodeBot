import types


class _AppNoGroup:
    def __init__(self):
        self.handlers = []
    def add_handler(self, handler, **kwargs):
        # simulate environment without 'group' support
        if 'group' in kwargs:
            raise TypeError("add_handler() got an unexpected keyword argument 'group'")
        self.handlers.append((handler, kwargs))


def test_register_catch_all_without_group_support(monkeypatch):
    import main as m
    # Build a dummy callable to register
    def dummy_cb(*a, **k):
        return None
    app = _AppNoGroup()
    m._register_catch_all_callback(app, dummy_cb)
    assert len(app.handlers) == 1
    handler, kwargs = app.handlers[0]
    assert hasattr(handler, 'callback')  # CallbackQueryHandler wrapper


class _AppWithGroup:
    def __init__(self):
        self.handlers = []
    def add_handler(self, handler, **kwargs):
        self.handlers.append((handler, kwargs))


def test_register_catch_all_with_group_support():
    import main as m
    def dummy_cb(*a, **k):
        return None
    app = _AppWithGroup()
    m._register_catch_all_callback(app, dummy_cb)
    assert len(app.handlers) == 1
    _h, kwargs = app.handlers[0]
    assert kwargs.get('group') == 5
