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
    def _is_cq(entry):
        args = entry[0]
        handler = args[0] if isinstance(args, tuple) else args
        return getattr(handler, '__class__', type('x', (), {})).__name__ == 'CallbackQueryHandler'
    assert any(_is_cq(h) for h in app.handlers)
