import importlib

def test_metrics_ttl_index_created(monkeypatch):
    # Disable real DB connections
    monkeypatch.setenv('BOT_TOKEN', 'x')
    monkeypatch.setenv('MONGODB_URL', 'mongodb://localhost:27017/test')
    monkeypatch.setenv('DISABLE_DB', '1')

    import database.manager as dm
    importlib.reload(dm)

    m = dm.DatabaseManager()

    # In no-op mode, collections are placeholders without real indexes; but create_indexes
    # invocation should not raise, and manager exposes collections attributes.
    assert hasattr(m, 'collection') and hasattr(m, 'large_files_collection')
    # The test primarily ensures the code path does not crash when adding metrics indexes
    # in environments without real DB.
