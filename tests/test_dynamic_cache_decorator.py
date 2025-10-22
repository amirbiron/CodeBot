import importlib

import types


def _install_flask_shim(monkeypatch):
    # Minimal shim to import the decorator without a full Flask app
    class _Req:
        path = "/api/demo"
        query_string = b"q=1"

    class _Sess(dict):
        pass

    def _jsonify(x):
        return x

    fake = types.SimpleNamespace(request=_Req(), session=_Sess(), jsonify=_jsonify)
    monkeypatch.setitem(importlib.import_module('sys').modules, 'flask', fake)


def test_dynamic_cache_decorator_basic_hit_miss(monkeypatch):
    import cache_manager as cm
    importlib.reload(cm)

    # Replace global cache with a dummy that records set/get
    class _Dummy:
        def __init__(self):
            self.store = {}
            self.is_enabled = True
        def get(self, k):
            return self.store.get(k)
        def set_dynamic(self, k, v, *_a, **_k):
            self.store[k] = v
            return True

    monkeypatch.setattr(cm, 'cache', _Dummy(), raising=True)
    _install_flask_shim(monkeypatch)

    calls = {"n": 0}

    @cm.dynamic_cache(content_type='test', key_prefix='demo')
    def handler():
        calls["n"] += 1
        return {"ok": True}

    # First call: miss -> compute and store
    out1 = handler()
    assert out1 == {"ok": True}
    assert calls["n"] == 1

    # Second call: hit -> no compute
    out2 = handler()
    assert out2 == {"ok": True}
    assert calls["n"] == 1
