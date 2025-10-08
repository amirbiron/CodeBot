from database.manager import DatabaseManager


def test_manager_get_repo_tags_with_counts_delegates(monkeypatch):
    mgr = DatabaseManager()

    class DummyRepo:
        def get_repo_tags_with_counts(self, user_id, max_tags=100):
            return [{"tag": "repo:me/app", "count": 7}]

    monkeypatch.setattr(mgr, "_get_repo", lambda: DummyRepo())
    res = mgr.get_repo_tags_with_counts(1, max_tags=5)
    assert isinstance(res, list)
    assert res and res[0].get("tag") == "repo:me/app"
