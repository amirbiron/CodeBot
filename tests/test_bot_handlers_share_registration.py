import types


class _AppNoGroup:
    def __init__(self):
        self.handlers = []
    def add_handler(self, handler, **kwargs):
        if 'group' in kwargs:
            raise TypeError("unexpected 'group'")
        self.handlers.append((handler, kwargs))


def test_share_handler_registers_without_group_support(monkeypatch):
    import bot_handlers as bh
    # Build instance with app that rejects 'group'
    app = _AppNoGroup()
    adv = bh.AdvancedBotHandlers(app)
    # One of the handlers should be the share handler; ensure at least one CallbackQueryHandler was registered
    assert any(getattr(h[0][0], '__class__', type('x', (), {})).__name__ == 'CallbackQueryHandler' for h in app.handlers)
