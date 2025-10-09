class _AppNoGroup:
    def __init__(self):
        self.handlers = []
    def add_handler(self, handler, **kwargs):
        if 'group' in kwargs:
            raise TypeError("unexpected 'group'")
        self.handlers.append((handler, kwargs))


def test_toggle_handler_registers_early_without_group_support():
    import bot_handlers as bh
    app = _AppNoGroup()
    bh.AdvancedBotHandlers(app)
    # Expect both catch-all and specific toggle handlers present (CallbackQueryHandler)
    kinds = [args[0].__class__.__name__ if isinstance(args, tuple) else args.__class__.__name__ for args, _ in app.handlers]
    assert any(k == 'CallbackQueryHandler' for k in kinds)
