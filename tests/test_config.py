import os
import sys
import importlib

import pytest


def _import_fresh_config():
    """Load the real root config module while preserving the tests stub."""
    from pathlib import Path
    import importlib.util

    project_root = Path(__file__).resolve().parent.parent
    config_path = project_root / "config.py"

    previous = sys.modules.pop("config", None)

    spec = importlib.util.spec_from_file_location("config", config_path)
    if spec is None or spec.loader is None:  # הגנה במקרה והקובץ לא נמצא
        raise RuntimeError(f"לא ניתן לטעון את המודול config מהנתיב {config_path}")

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

    # החריגה תיזרק בעת טעינת המודול האמיתי
    with pytest.raises(ValueError):
        _import_fresh_config()


def test_mongodb_url_validation(monkeypatch):
    # הגדרה של ערך לא תקין ל-MONGODB_URL אמורה להכשיל import
    monkeypatch.setenv("BOT_TOKEN", "x")
    monkeypatch.setenv("MONGODB_URL", "http://localhost:27017")
    with pytest.raises(ValueError):
        _import_fresh_config()

