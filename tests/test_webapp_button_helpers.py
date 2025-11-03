import types

import pytest


class _Btn:
    def __init__(self, text, callback_data=None, url=None, **_):
        self.text = text
        self.callback_data = callback_data
        self.url = url


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    monkeypatch.delenv('WEBAPP_URL', raising=False)
    yield
    monkeypatch.delenv('WEBAPP_URL', raising=False)


@pytest.mark.parametrize(
    "config_values, env_value, expected",
    [
        ({"WEBAPP_URL": "https://cfg.example", "PUBLIC_BASE_URL": None}, None, "https://cfg.example/file/abc"),
        ({"WEBAPP_URL": None, "PUBLIC_BASE_URL": "https://public.example"}, None, "https://public.example/file/abc"),
        ({"WEBAPP_URL": None, "PUBLIC_BASE_URL": None}, "https://env.example", "https://env.example/file/abc"),
    ],
)
def test_file_view_webapp_button_prefers_available_source(monkeypatch, config_values, env_value, expected):
    import handlers.file_view as fv

    stub_cfg = types.SimpleNamespace(**config_values)
    monkeypatch.setattr(fv, 'config', stub_cfg, raising=False)
    monkeypatch.setattr(fv, 'InlineKeyboardButton', _Btn, raising=True)
    if env_value is not None:
        monkeypatch.setattr(fv.os, 'getenv', lambda key, default=None: env_value if key == 'WEBAPP_URL' else default, raising=True)
    else:
        monkeypatch.setattr(fv.os, 'getenv', lambda key, default=None: None, raising=True)

    row = fv._get_webapp_button_row('abc', None)
    assert row[0].url == expected


def test_file_view_webapp_button_falls_back_to_default(monkeypatch):
    import handlers.file_view as fv

    class Boom:
        def __getattr__(self, name):
            raise RuntimeError('boom')

    monkeypatch.setattr(fv, 'config', Boom(), raising=False)
    monkeypatch.setattr(fv, 'InlineKeyboardButton', _Btn, raising=True)
    monkeypatch.setattr(fv.os, 'getenv', lambda key, default=None: None, raising=True)

    row = fv._get_webapp_button_row('xyz', None)
    assert row[0].url == f"{fv.DEFAULT_WEBAPP_URL}/file/xyz"


def test_file_view_webapp_button_search_fallback(monkeypatch):
    import handlers.file_view as fv

    stub_cfg = types.SimpleNamespace(WEBAPP_URL=None, PUBLIC_BASE_URL=None)
    monkeypatch.setattr(fv, 'config', stub_cfg, raising=False)
    monkeypatch.setattr(fv, 'InlineKeyboardButton', _Btn, raising=True)
    monkeypatch.setattr(fv.os, 'getenv', lambda key, default=None: None, raising=True)

    row = fv._get_webapp_button_row(None, 'demo file.py')
    assert row[0].url == f"{fv.DEFAULT_WEBAPP_URL}/files?q=demo+file.py#results"


def test_file_view_webapp_button_returns_none_if_base_missing(monkeypatch):
    import handlers.file_view as fv

    monkeypatch.setattr(fv, 'InlineKeyboardButton', _Btn, raising=True)
    monkeypatch.setattr(fv, '_resolve_webapp_base_url', lambda: None, raising=True)
    assert fv._get_webapp_button_row('id', 'name.py') is None


@pytest.mark.parametrize(
    "config_values, env_value, expected",
    [
        ({"WEBAPP_URL": "https://cfg.conv"}, None, "https://cfg.conv/file/FOO"),
        ({"WEBAPP_URL": None, "PUBLIC_BASE_URL": "https://public.conv"}, None, "https://public.conv/file/FOO"),
        ({"WEBAPP_URL": None, "PUBLIC_BASE_URL": None}, "https://env.conv", "https://env.conv/file/FOO"),
    ],
)
def test_conversation_webapp_button_sources(monkeypatch, config_values, env_value, expected):
    import conversation_handlers as ch

    stub_cfg = types.SimpleNamespace(WEBAPP_URL=config_values.get('WEBAPP_URL'), PUBLIC_BASE_URL=config_values.get('PUBLIC_BASE_URL'))
    monkeypatch.setattr(ch, 'config', stub_cfg, raising=False)
    monkeypatch.setattr(ch, 'InlineKeyboardButton', _Btn, raising=True)
    if env_value is not None:
        monkeypatch.setattr(ch.os, 'getenv', lambda key, default=None: env_value if key == 'WEBAPP_URL' else default, raising=True)
    else:
        monkeypatch.setattr(ch.os, 'getenv', lambda key, default=None: None, raising=True)

    row = ch._get_webapp_button_row('FOO', None)
    assert row[0].url == expected


def test_conversation_webapp_button_default_on_exception(monkeypatch):
    import conversation_handlers as ch

    class Boom:
        def __getattr__(self, name):
            raise RuntimeError('boom')

    monkeypatch.setattr(ch, 'config', Boom(), raising=False)
    monkeypatch.setattr(ch, 'InlineKeyboardButton', _Btn, raising=True)
    monkeypatch.setattr(ch.os, 'getenv', lambda key, default=None: None, raising=True)

    row = ch._get_webapp_button_row('BAR', None)
    assert row[0].url == f"{ch.DEFAULT_WEBAPP_URL}/file/BAR"


def test_conversation_webapp_button_search_path(monkeypatch):
    import conversation_handlers as ch

    stub_cfg = types.SimpleNamespace(WEBAPP_URL=None, PUBLIC_BASE_URL=None)
    monkeypatch.setattr(ch, 'config', stub_cfg, raising=False)
    monkeypatch.setattr(ch, 'InlineKeyboardButton', _Btn, raising=True)
    monkeypatch.setattr(ch.os, 'getenv', lambda key, default=None: None, raising=True)

    row = ch._get_webapp_button_row(None, 'space name.txt')
    assert row[0].url == f"{ch.DEFAULT_WEBAPP_URL}/files?q=space+name.txt#results"
