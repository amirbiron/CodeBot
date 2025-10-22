import importlib
import types


def _shim_flask(monkeypatch):
    class _Resp:
        def __init__(self, data):
            self._data = data
        def get_json(self, silent=False):  # noqa: ARG002
            return self._data
    class _Req:
        path = "/api/demo"
        query_string = b"a=1"
    class _Sess(dict):
        pass
    def _jsonify(x):
        return x
    fake = types.SimpleNamespace(request=_Req(), session=_Sess(), jsonify=_jsonify)
    monkeypatch.setitem(importlib.sys.modules, 'flask', fake)
    return _Resp


def test_dynamic_cache_decorator_stores_response_json(monkeypatch):
    import cache_manager as cm
    importlib.reload(cm)

    _Resp = _shim_flask(monkeypatch)

    stored = {}
    class _Dummy:
        def __init__(self):
            self.is_enabled = True
        def get(self, k):  # noqa: ARG002
            return None
        def set_dynamic(self, k, v, *a, **kw):  # noqa: ARG002
            stored[k] = v
            return True
    monkeypatch.setattr(cm, 'cache', _Dummy(), raising=True)

    @cm.dynamic_cache(content_type='x', key_prefix='demo')
    def handler():
        return _Resp({"ok": True})

    out = handler()
    assert isinstance(out, _Resp)
    assert any(v == {"ok": True} for v in stored.values())
