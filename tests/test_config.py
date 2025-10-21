import os
import sys
import importlib

import pytest


def _import_fresh_config():
    sys.modules.pop("config", None)
    import config as cfg  # noqa: F401
    return cfg


def test_load_config_minimal_env(monkeypatch):
    monkeypatch.setenv("BOT_TOKEN", "123:TEST")
    monkeypatch.setenv("MONGODB_URL", "mongodb://localhost:27017/test_db")
    # ברירות מחדל
    monkeypatch.delenv("CACHE_ENABLED", raising=False)
    monkeypatch.delenv("DRIVE_MENU_V2", raising=False)

    cfg = _import_fresh_config()

    conf = cfg.load_config()
    assert conf.BOT_TOKEN.startswith("123")
    assert conf.MONGODB_URL.startswith("mongodb://")
    assert conf.CACHE_ENABLED is False  # ברירת מחדל ל-false אם לא הוגדר
    assert conf.DRIVE_MENU_V2 is True   # ברירת מחדל לטקסט 'true'
    assert isinstance(conf.SUPPORTED_LANGUAGES, list) and len(conf.SUPPORTED_LANGUAGES) > 0


def test_load_config_missing_env(monkeypatch):
    # ננקה משתנים חובה כדי לוודא חריגה ברורה
    monkeypatch.delenv("BOT_TOKEN", raising=False)
    monkeypatch.delenv("MONGODB_URL", raising=False)

    # החריגה תיזרק בזמן import של המודול עצמו
    sys.modules.pop("config", None)
    with pytest.raises(ValueError):
        importlib.import_module("config")


def test_mongodb_url_validation(monkeypatch):
    # הגדרה של ערך לא תקין ל-MONGODB_URL אמורה להכשיל import
    monkeypatch.setenv("BOT_TOKEN", "x")
    monkeypatch.setenv("MONGODB_URL", "http://localhost:27017")
    sys.modules.pop("config", None)
    with pytest.raises(ValueError):
        importlib.import_module("config")

