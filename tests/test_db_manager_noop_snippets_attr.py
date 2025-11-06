import os
import importlib

def test_db_manager_has_snippets_collection_noop(monkeypatch):
    monkeypatch.setenv('DISABLE_DB', '1')
    # reload database package to re-init manager in noop mode
    if 'database' in list(importlib.sys.modules):
        importlib.reload(importlib.import_module('database.manager'))
        importlib.reload(importlib.import_module('database'))
    from database import db
    assert hasattr(db, 'snippets_collection')
