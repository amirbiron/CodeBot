import importlib

def test_clear_all_respects_time_budget(monkeypatch):
    import cache_manager as cm
    importlib.reload(cm)

    # Tiny budget ensures we bail out early
    monkeypatch.setenv('CACHE_CLEAR_BUDGET_SECONDS', '0.000001')

    mgr = cm.CacheManager()
    mgr.is_enabled = True

    class _Client:
        def scan_iter(self, match='*', count=500):  # noqa: ARG002
            for i in range(1000):
                yield f"k{i}"
        def delete(self, key):  # noqa: ARG002
            return 1
        def keys(self, pattern):  # noqa: ARG002
            # not used in this branch
            return []

    mgr.redis_client = _Client()

    deleted = mgr.clear_all()
    # Should stop early due to the very small budget. Definitely << 1000
    assert 0 <= deleted <= 10
