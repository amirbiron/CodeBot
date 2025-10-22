import importlib


def test_invalidate_file_related_patterns(monkeypatch):
    import cache_manager as cm
    importlib.reload(cm)

    # Spy redis client keys/delete usage
    class _FakeRedis:
        def __init__(self):
            self.deleted = []
            self.store = {
                'file_content:readme.md:xyz': '1',
                'markdown_render:readme.md:abc': '1',
                'user_files:get_user_files:<self>:7:50': '1',
                'latest_version:get_latest_version:<self>:7:main.py': '1',
            }
        def keys(self, pattern):
            import fnmatch
            return [k for k in self.store.keys() if fnmatch.fnmatch(k, pattern)]
        def delete(self, *keys):
            cnt = 0
            for k in keys:
                if k in self.store:
                    self.deleted.append(k)
                    del self.store[k]
                    cnt += 1
            return cnt
        def ping(self):
            return True
    r = _FakeRedis()

    cm.cache.is_enabled = True
    cm.cache.redis_client = r

    # Invalidate by file_id (here using file_name for simplicity)
    n = cm.cache.invalidate_file_related('readme.md', user_id=7)
    assert n >= 2  # at least file_content & markdown_render
    # Ensure some keys were deleted
    assert len(r.deleted) >= 2
