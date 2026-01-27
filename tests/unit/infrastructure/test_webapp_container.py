import sys
import types

from src.infrastructure.composition import get_files_facade as composition_get_files_facade
from src.infrastructure.composition import webapp_container


def _install_dummy_database(monkeypatch):
    dummy_db = object()
    db_mod = types.ModuleType("database")
    db_mod.db = dummy_db
    monkeypatch.setitem(sys.modules, "database", db_mod)
    return dummy_db


def _reset_singleton(monkeypatch):
    monkeypatch.setattr(webapp_container, "_files_facade_singleton", None, raising=False)


def test_webapp_container_get_files_facade_singleton(monkeypatch):
    _reset_singleton(monkeypatch)
    _install_dummy_database(monkeypatch)

    f1 = webapp_container.get_files_facade()
    f2 = webapp_container.get_files_facade()
    f3 = composition_get_files_facade()

    assert f1 is f2
    assert f1 is f3
