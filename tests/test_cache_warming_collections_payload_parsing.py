import asyncio
import importlib
import types


def test_cache_warming_handles_collections_list_dict_return(monkeypatch):
    """
    Regression test:
    webapp.collections_api.list_collections() returns dict directly on cache-miss,
    while dynamic_cache returns Flask Response on cache-hit.

    Cache warming must handle both, otherwise Desktop ("שולחן עבודה") warming is skipped.
    """

    # Capture events (optional)
    captured = {"evts": []}
    fake_obs = types.SimpleNamespace(
        setup_structlog_logging=lambda *_a, **_k: None,
        init_sentry=lambda: None,
        bind_request_id=lambda *_a, **_k: None,
        generate_request_id=lambda: "",
        emit_event=lambda evt, severity="info", **kw: captured["evts"].append((evt, severity, kw)),
    )
    monkeypatch.setitem(importlib.sys.modules, "observability", fake_obs)

    # Fake cache_manager with build_cache_key available
    class _Cache:
        is_enabled = True

        def __init__(self):
            self.store = {}

        def get(self, key):  # noqa: ANN001
            return self.store.get(key)

        def set_dynamic(self, key, value, *_a, **_k):  # noqa: ANN001
            self.store[str(key)] = value
            return True

    def _build_cache_key(*parts):  # noqa: ANN001
        return ":".join(str(p) for p in parts if p not in (None, ""))

    monkeypatch.setitem(importlib.sys.modules, "cache_manager", types.SimpleNamespace(cache=_Cache(), build_cache_key=_build_cache_key))

    # Fake DB with enough surface for cache warming
    import datetime as _dt

    class _CodeSnippets:
        def aggregate(self, pipeline, allowDiskUse=False):  # noqa: ANN001, ARG002
            # top_users aggregation (group by user_id)
            if any(isinstance(s, dict) and "$group" in s and s["$group"].get("_id") == "$user_id" for s in pipeline):
                return [{"_id": 7, "cnt": 1}]
            # tags aggregation
            return []

        def count_documents(self, _q):  # noqa: ANN001
            return 1

        def distinct(self, _field, _q):  # noqa: ANN001
            return ["python"]

        def find(self, *_a, **_k):  # noqa: ANN001
            class _C:
                def sort(self, *_a, **_k):  # noqa: ANN001
                    return self

                def limit(self, *_a, **_k):  # noqa: ANN001
                    return [{"file_name": "a.py", "created_at": _dt.datetime.now(_dt.timezone.utc)}]

            return _C()

    class _Users:
        def find_one(self, *_a, **_k):  # noqa: ANN001
            return {"user_id": 7, "first_name": "A", "last_name": "B", "username": "u", "photo_url": "", "has_seen_welcome_modal": True}

    class _DB:
        code_snippets = _CodeSnippets()
        users = _Users()

    def _get_db():
        return _DB()

    # Fake minimal "flask" module (CI may have flask; local env might not).
    # We only need `session` used by the cache warming code.
    class _FakeSession(dict):
        permanent: bool = False

    fake_flask = types.ModuleType("flask")
    fake_flask.session = _FakeSession()
    monkeypatch.setitem(importlib.sys.modules, "flask", fake_flask)

    # Fake Flask app object with test_request_context()
    class _Ctx:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):  # noqa: ANN001
            return False

    class _FakeApp:
        def test_request_context(self, _path):  # noqa: ANN001
            return _Ctx()

    flask_app = _FakeApp()

    def _files_page():  # minimal /files handler
        return "<html>files</html>"

    # Fake collections_api endpoints; list_collections returns dict (cache miss shape)
    calls = {"get_collection": 0, "get_items": 0}

    def list_collections():
        return {"ok": True, "collections": [{"id": "cid1", "name": "שולחן עבודה"}]}

    def get_collection(collection_id):  # noqa: ANN001
        calls["get_collection"] += 1
        assert str(collection_id) == "cid1"
        return {"ok": True, "collection": {"id": "cid1", "name": "שולחן עבודה"}}

    def get_items(collection_id):  # noqa: ANN001
        calls["get_items"] += 1
        assert str(collection_id) == "cid1"
        return {"ok": True, "items": []}

    webapp_app_mod = types.ModuleType("webapp.app")
    webapp_app_mod.get_db = _get_db
    webapp_app_mod.search_engine = None
    webapp_app_mod.app = flask_app
    webapp_app_mod.files = _files_page
    monkeypatch.setitem(importlib.sys.modules, "webapp.app", webapp_app_mod)

    webapp_collections_mod = types.ModuleType("webapp.collections_api")
    webapp_collections_mod.list_collections = list_collections
    webapp_collections_mod.get_collection = get_collection
    webapp_collections_mod.get_items = get_items
    monkeypatch.setitem(importlib.sys.modules, "webapp.collections_api", webapp_collections_mod)

    # Import main after shimming modules
    import main as m

    monkeypatch.setenv("CACHE_WARMING_ENABLED", "1")
    monkeypatch.setenv("CACHE_WARMING_BUDGET_SECONDS", "5")

    class _JobQ:
        def run_repeating(self, fn, interval, first, name=None):  # noqa: ANN001, ARG002
            asyncio.get_event_loop().run_until_complete(fn(None))

    class _Bot:
        async def delete_my_commands(self):
            return None

        async def set_my_commands(self, *_a, **_k):  # noqa: ANN001
            return None

    class _App:
        job_queue = _JobQ()
        bot = _Bot()

    app = _App()
    monkeypatch.delenv("DISABLE_BACKGROUND_CLEANUP", raising=False)

    asyncio.get_event_loop().run_until_complete(m.setup_bot_data(app))

    assert calls["get_collection"] == 1
    assert calls["get_items"] == 1

