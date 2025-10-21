import sys
import importlib


def _import_fresh_config():
    sys.modules.pop("config", None)
    import config as cfg  # noqa: F401
    return cfg


def test_admin_user_ids_parsing_csv_env(monkeypatch):
    # Required env for successful import
    monkeypatch.setenv("BOT_TOKEN", "123:TEST")
    monkeypatch.setenv("MONGODB_URL", "mongodb://localhost:27017/test_db")
    # Include spaces, blanks and an invalid token to exercise the parser's skip path
    monkeypatch.setenv("ADMIN_USER_IDS", "1, 2, , x, 3 ,, ")

    cfg = _import_fresh_config()
    conf = cfg.load_config()

    assert conf.ADMIN_USER_IDS == [1, 2, 3]


def test_admin_user_ids_empty_env(monkeypatch):
    monkeypatch.setenv("BOT_TOKEN", "123:TEST")
    monkeypatch.setenv("MONGODB_URL", "mongodb://localhost:27017/test_db")
    monkeypatch.delenv("ADMIN_USER_IDS", raising=False)

    cfg = _import_fresh_config()
    conf = cfg.load_config()

    assert conf.ADMIN_USER_IDS == []


def test_admin_user_ids_accept_list_and_int(monkeypatch):
    # Ensure module can be imported (module-level config instantiation)
    monkeypatch.setenv("BOT_TOKEN", "x")
    monkeypatch.setenv("MONGODB_URL", "mongodb://localhost:27017/db")

    # Import module and get class
    cfg = _import_fresh_config()
    BotConfig = cfg.BotConfig

    # List with mixed types and invalid entries
    conf_list = BotConfig(
        BOT_TOKEN="x",
        MONGODB_URL="mongodb://localhost:27017/db",
        ADMIN_USER_IDS=["1", 2, " 3 ", "bad", ""],
    )
    assert conf_list.ADMIN_USER_IDS == [1, 2, 3]

    # Single integer input
    conf_int = BotConfig(
        BOT_TOKEN="x",
        MONGODB_URL="mongodb://localhost:27017/db",
        ADMIN_USER_IDS=1,
    )
    assert conf_int.ADMIN_USER_IDS == [1]
