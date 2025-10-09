import types


def test_manager_wrappers_exist_and_call():
    # Ensure DatabaseManager exposes favorites API and passes through to repo
    import database.manager as dm

    class _Repo:
        def __init__(self):
            self.called = {}
        def toggle_favorite(self, *a, **k):
            self.called['toggle_favorite'] = True
            return True
        def get_favorites(self, *a, **k):
            self.called['get_favorites'] = True
            return []
        def get_favorites_count(self, *a, **k):
            self.called['get_favorites_count'] = True
            return 0
        def is_favorite(self, *a, **k):
            self.called['is_favorite'] = True
            return False

    mgr = dm.DatabaseManager()
    # Inject fake repo
    mgr._repo = _Repo()

    assert mgr.toggle_favorite(1, 'a.py') is True
    assert isinstance(mgr.get_favorites(1), list)
    assert isinstance(mgr.get_favorites_count(1), int)
    assert mgr.is_favorite(1, 'a.py') is False
