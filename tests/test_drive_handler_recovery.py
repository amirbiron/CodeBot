from main import get_drive_handler_from_application


class _FakeApp:
    def __init__(self):
        self.bot_data = {}


def test_get_drive_handler_prefers_bot_data():
    app = _FakeApp()
    handler = object()
    app.bot_data["drive_handler"] = handler

    result, restored = get_drive_handler_from_application(app)

    assert result is handler
    assert restored is False


def test_get_drive_handler_restores_from_application_attr():
    app = _FakeApp()
    handler = object()
    app._drive_handler = handler  # noqa: SLF001 - attribute used intentionally

    result, restored = get_drive_handler_from_application(app)

    assert result is handler
    assert restored is True
    assert app.bot_data["drive_handler"] is handler


def test_get_drive_handler_returns_none_when_missing():
    app = _FakeApp()

    result, restored = get_drive_handler_from_application(app)

    assert result is None
    assert restored is False
