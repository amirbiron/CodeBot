def test_manager_image_prefs_passthrough(monkeypatch):
    from database.manager import DatabaseManager

    class _Repo:
        def __init__(self):
            self.saved = None
        def save_image_prefs(self, user_id, prefs):
            self.saved = (user_id, prefs)
            return True
        def get_image_prefs(self, user_id):
            # echo saved prefs for assertion path
            return {"theme": "dracula", "font": "cascadia", "width": 800}

    mgr = DatabaseManager()
    # Monkeypatch instance _get_repo to return our stub
    monkeypatch.setattr(mgr, "_get_repo", lambda: _Repo(), raising=False)

    assert mgr.save_image_prefs(7, {"theme": "dracula"}) is True
    prefs = mgr.get_image_prefs(7)
    assert prefs and prefs.get("theme") == "dracula"
