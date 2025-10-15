import types
import pytest


def _fake_emit_capture(target_module):
    captured = {"events": []}
    def _emit(event, severity="info", **fields):
        captured["events"].append((event, severity, fields))
    # monkeypatch will replace target_module.emit_event in tests
    return captured, _emit


def test_repository_save_code_snippet_error_emits(monkeypatch):
    import database.repository as repo_mod
    captured, _emit = _fake_emit_capture(repo_mod)
    monkeypatch.setattr(repo_mod, "emit_event", _emit, raising=False)

    class _Mgr:
        def __init__(self):
            self.collection = types.SimpleNamespace(insert_one=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db fail")))
    r = repo_mod.Repository(types.SimpleNamespace(collection=_Mgr().collection))

    # Build minimal snippet
    from database.models import CodeSnippet
    snippet = CodeSnippet(user_id=1, file_name="a.py", code="print(1)", programming_language="python")

    ok = r.save_code_snippet(snippet)
    assert ok is False
    assert any(e[0] == "db_save_code_snippet_error" for e in captured["events"])  # event emitted


def test_repository_get_latest_version_error_emits(monkeypatch):
    import database.repository as repo_mod
    captured, _emit = _fake_emit_capture(repo_mod)
    monkeypatch.setattr(repo_mod, "emit_event", _emit, raising=False)

    class _BadColl:
        def find_one(self, *a, **k):
            raise RuntimeError("find one boom")
    mgr = types.SimpleNamespace(collection=_BadColl())
    r = repo_mod.Repository(mgr)
    out = r.get_latest_version(1, "a.py")
    assert out is None
    assert any(e[0] == "db_get_latest_version_error" for e in captured["events"])  # event emitted


def test_repository_user_files_by_repo_error_emits(monkeypatch):
    import database.repository as repo_mod
    captured, _emit = _fake_emit_capture(repo_mod)
    monkeypatch.setattr(repo_mod, "emit_event", _emit, raising=False)

    class _BadColl:
        def aggregate(self, *a, **k):
            raise RuntimeError("agg fail")
    mgr = types.SimpleNamespace(collection=_BadColl())
    r = repo_mod.Repository(mgr)
    items, total = r.get_user_files_by_repo(1, "repo:foo/bar")
    assert items == [] and total == 0
    assert any(e[0] == "db_get_user_files_by_repo_error" for e in captured["events"])  # event emitted
