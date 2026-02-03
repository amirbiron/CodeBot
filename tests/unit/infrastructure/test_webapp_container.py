"""
Tests for webapp_container module - validates proper instance retrieval
and singleton behavior for the webapp composition root.
"""
import sys
import types

from src.infrastructure.composition.webapp_container import (
    WebappContainer,
    get_files_facade,
    get_snippet_service,
    get_webapp_container,
)


class DummyDB:
    """Minimal stub for database operations."""

    def get_user_files(self, user_id, limit=50, *, skip=0, projection=None):
        return [{"file_name": "test.py", "user_id": user_id}]

    def get_latest_version(self, user_id, file_name):
        return {"user_id": user_id, "file_name": file_name, "code": "x"}


def _install_dummy_database(monkeypatch):
    """Install a minimal database stub into sys.modules."""
    dummy_db = DummyDB()
    db_mod = types.ModuleType("database")
    db_mod.db = dummy_db

    models_mod = types.ModuleType("database.models")

    class CodeSnippet:
        def __init__(self, user_id, file_name, code, programming_language, description="", tags=None):
            self.user_id = user_id
            self.file_name = file_name
            self.code = code
            self.programming_language = programming_language
            self.description = description
            self.tags = list(tags or [])

    class LargeFile:
        def __init__(self, user_id, file_name, content, programming_language, file_size, lines_count):
            self.user_id = user_id
            self.file_name = file_name
            self.content = content
            self.programming_language = programming_language
            self.file_size = file_size
            self.lines_count = lines_count

    models_mod.CodeSnippet = CodeSnippet
    models_mod.LargeFile = LargeFile
    db_mod.CodeSnippet = CodeSnippet
    db_mod.LargeFile = LargeFile

    monkeypatch.setitem(sys.modules, "database", db_mod)
    monkeypatch.setitem(sys.modules, "database.models", models_mod)
    return dummy_db


def test_webapp_container_returns_files_facade_instance(monkeypatch):
    """Verify get_files_facade returns a valid FilesFacade instance."""
    _install_dummy_database(monkeypatch)

    # Reset singleton for clean test
    import src.infrastructure.composition.webapp_container as wc
    monkeypatch.setattr(wc, "_files_facade_singleton", None)

    facade = get_files_facade()
    assert facade is not None
    assert hasattr(facade, "get_user_files")
    assert hasattr(facade, "get_latest_version")


def test_webapp_container_singleton_returns_same_instance(monkeypatch):
    """Verify get_files_facade returns the same singleton instance."""
    _install_dummy_database(monkeypatch)

    import src.infrastructure.composition.webapp_container as wc
    monkeypatch.setattr(wc, "_files_facade_singleton", None)

    facade1 = get_files_facade()
    facade2 = get_files_facade()
    assert facade1 is facade2


def test_webapp_container_class_provides_facade_access(monkeypatch):
    """Verify WebappContainer class provides access to files_facade."""
    _install_dummy_database(monkeypatch)

    import src.infrastructure.composition.webapp_container as wc
    monkeypatch.setattr(wc, "_files_facade_singleton", None)

    container = WebappContainer()
    facade = container.files_facade
    assert facade is not None
    assert hasattr(facade, "get_user_files")


def test_get_webapp_container_returns_singleton(monkeypatch):
    """Verify get_webapp_container returns the same singleton instance."""
    _install_dummy_database(monkeypatch)

    import src.infrastructure.composition.webapp_container as wc
    monkeypatch.setattr(wc, "_container", None)

    container1 = get_webapp_container()
    container2 = get_webapp_container()
    assert container1 is container2


def test_webapp_container_files_facade_can_call_methods(monkeypatch):
    """Verify the facade obtained via container can actually call DB methods."""
    _install_dummy_database(monkeypatch)

    import src.infrastructure.composition.webapp_container as wc
    monkeypatch.setattr(wc, "_files_facade_singleton", None)

    facade = get_files_facade()
    files = facade.get_user_files(123, limit=10)
    assert isinstance(files, list)
    assert len(files) > 0
    assert files[0]["user_id"] == 123


def test_import_from_init_works(monkeypatch):
    """Verify imports work from the package __init__ as well."""
    _install_dummy_database(monkeypatch)

    # These should import successfully
    from src.infrastructure.composition import (
        FilesFacade,
        WebappContainer,
        get_files_facade as init_get_files_facade,
        get_snippet_service as init_get_snippet_service,
        get_webapp_container as init_get_webapp_container,
    )

    assert init_get_files_facade is get_files_facade
    assert init_get_snippet_service is get_snippet_service
    assert init_get_webapp_container is get_webapp_container
    assert FilesFacade is not None
    assert WebappContainer is not None
