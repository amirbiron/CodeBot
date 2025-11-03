import sys
import importlib


def _import_fresh_config():
    """Load the root config module without disturbing the tests stub."""
    from pathlib import Path
    import importlib.util

    project_root = Path(__file__).resolve().parent.parent
    config_path = project_root / "config.py"

    previous = sys.modules.pop("config", None)

    spec = importlib.util.spec_from_file_location("config", config_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load config from path {config_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules["config"] = module
    try:
        spec.loader.exec_module(module)  # type: ignore[union-attr]
    finally:
        if previous is not None:
            sys.modules["config"] = previous
        else:
            sys.modules.pop("config", None)

    return module


def test_admin_user_ids_parsing_csv_env(monkeypatch):
    # Required env for successful import
    monkeypatch.setenv("BOT_TOKEN", "123:TEST")
    monkeypatch.setenv("MONGODB_URL", "mongodb://localhost:27017/test_db")
    # Include spaces, blanks and an invalid token to exercise the parser's skip path
    # Invalid token 'x' should now raise ValueError (strict parsing)
    monkeypatch.setenv("ADMIN_USER_IDS", "1, 2, , x, 3 ,, ")

    import pytest
    with pytest.raises(ValueError):
        _import_fresh_config()


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
    import pytest
    with pytest.raises(ValueError):
        BotConfig(
            BOT_TOKEN="x",
            MONGODB_URL="mongodb://localhost:27017/db",
            ADMIN_USER_IDS=["1", 2, " 3 ", "bad", ""],
        )

    # Single integer input
    conf_int = BotConfig(
        BOT_TOKEN="x",
        MONGODB_URL="mongodb://localhost:27017/db",
        ADMIN_USER_IDS=1,
    )
    assert conf_int.ADMIN_USER_IDS == [1]


def test_admin_user_ids_json_string_and_csv(monkeypatch):
    # Ensure successful import
    monkeypatch.setenv("BOT_TOKEN", "x")
    monkeypatch.setenv("MONGODB_URL", "mongodb://localhost:27017/db")

    cfg = _import_fresh_config()
    BotConfig = cfg.BotConfig

    # JSON list string
    conf_json_list = BotConfig(
        BOT_TOKEN="x",
        MONGODB_URL="mongodb://localhost:27017/db",
        ADMIN_USER_IDS="[1, 2, 3]",
    )
    assert conf_json_list.ADMIN_USER_IDS == [1, 2, 3]

    # JSON integer string
    conf_json_int = BotConfig(
        BOT_TOKEN="x",
        MONGODB_URL="mongodb://localhost:27017/db",
        ADMIN_USER_IDS="1",
    )
    assert conf_json_int.ADMIN_USER_IDS == [1]

    # CSV string
    conf_csv = BotConfig(
        BOT_TOKEN="x",
        MONGODB_URL="mongodb://localhost:27017/db",
        ADMIN_USER_IDS="10,20,30",
    )
    assert conf_csv.ADMIN_USER_IDS == [10, 20, 30]

    # CSV with empty tokens is allowed (ignored)
    conf_csv_with_blanks = BotConfig(
        BOT_TOKEN="x",
        MONGODB_URL="mongodb://localhost:27017/db",
        ADMIN_USER_IDS="4,,5",
    )
    assert conf_csv_with_blanks.ADMIN_USER_IDS == [4, 5]

    # Invalid JSON content type should raise
    import pytest
    with pytest.raises(ValueError):
        BotConfig(
            BOT_TOKEN="x",
            MONGODB_URL="mongodb://localhost:27017/db",
            ADMIN_USER_IDS="{}",
        )


def test_admin_user_ids_tuple_and_set_handling(monkeypatch):
    # Ensure successful import
    monkeypatch.setenv("BOT_TOKEN", "x")
    monkeypatch.setenv("MONGODB_URL", "mongodb://localhost:27017/db")

    cfg = _import_fresh_config()
    BotConfig = cfg.BotConfig

    conf_tuple = BotConfig(
        BOT_TOKEN="x",
        MONGODB_URL="mongodb://localhost:27017/db",
        ADMIN_USER_IDS=(1, "2", " 3 "),
    )
    assert conf_tuple.ADMIN_USER_IDS == [1, 2, 3]

    conf_set = BotConfig(
        BOT_TOKEN="x",
        MONGODB_URL="mongodb://localhost:27017/db",
        ADMIN_USER_IDS={1, "2"},
    )
    assert set(conf_set.ADMIN_USER_IDS) == {1, 2}

    # Empty string provided directly should resolve to []
    conf_empty_str = BotConfig(
        BOT_TOKEN="x",
        MONGODB_URL="mongodb://localhost:27017/db",
        ADMIN_USER_IDS="",
    )
    assert conf_empty_str.ADMIN_USER_IDS == []
