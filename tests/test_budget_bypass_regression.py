import importlib
import time


def test_clear_all_budget_not_bypassed_on_delete_exception(monkeypatch):
    import cache_manager as cm
    importlib.reload(cm)

    monkeypatch.setenv('CACHE_CLEAR_BUDGET_SECONDS', '0.000001')

    mgr = cm.CacheManager()
    mgr.is_enabled = True

    class _Client:
        def scan_iter(self, match='*', count=500):  # noqa: ARG002
            for i in range(1000):
                yield f"k{i}"
        def delete(self, key):  # noqa: ARG002
            raise RuntimeError("boom")

    mgr.redis_client = _Client()

    start = time.time()
    _ = mgr.clear_all()
    elapsed = time.time() - start

    assert elapsed < 0.5, f"clear_all took too long: {elapsed}s"
