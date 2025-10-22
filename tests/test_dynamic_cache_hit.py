import importlib
import types


def _shim_flask(monkeypatch):
    class _Req:
        path = "/api/bookmarks/123"
        query_string = b""
    class _Sess(dict):
        pass
    def _jsonify(x):
        return x
    fake = types.SimpleNamespace(request=_Req(), session=_Sess(), jsonify=_jsonify)
    monkeypatch.setitem(importlib.sys.modules, 'flask', fake)


def test_dynamic_cache_hit_returns_cached_without_call(monkeypatch):
    import cache_manager as cm
    importlib.reload(cm)

    _shim_flask(monkeypatch)

    calls = {"n": 0}

    class _Dummy:
        def __init__(self):
            self.is_enabled = True
        def get(self, k):  # noqa: ARG001
            return {"ok": True}
        def set_dynamic(self, *a, **k):  # noqa: ARG002
            raise AssertionError("should not set on hit")
    monkeypatch.setattr(cm, 'cache', _Dummy(), raising=True)

    @cm.dynamic_cache(content_type='bookmarks', key_prefix='bookmarks_file')
    def handler():
        calls["n"] += 1
        return {"ok": False}

    out = handler()
    assert out == {"ok": True}
    assert calls["n"] == 0


def test_dynamic_cache_hit_with_string(monkeypatch):
    import cache_manager as cm
    importlib.reload(cm)

    _shim_flask(monkeypatch)

    class _Dummy:
        def __init__(self):
            self.is_enabled = True
        def get(self, k):  # noqa: ARG001
            return "cached"
        def set_dynamic(self, *a, **k):  # noqa: ARG002
            raise AssertionError("should not set on hit")
    monkeypatch.setattr(cm, 'cache', _Dummy(), raising=True)

    @cm.dynamic_cache(content_type='bookmarks', key_prefix='bookmarks_file')
    def handler():
        return "fresh"

    out = handler()
    assert out == "cached"
