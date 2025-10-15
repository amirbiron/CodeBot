import types
import pytest


@pytest.mark.asyncio
async def test_save_command_emits_file_saved(monkeypatch):
    import main as mod

    # Stub dependencies
    class _Msg:
        async def reply_text(self, *a, **k):
            return None
    class _EU:
        id = 7
    class _Upd:
        def __init__(self):
            self.message = _Msg()
            self.effective_user = _EU()
    class _Ctx:
        def __init__(self):
            self.user_data = {}
            self.args = ["foo.py"]
    upd = _Upd()
    ctx = _Ctx()

    # Arrange state for saving
    ctx.user_data["saving_file"] = {"file_name": "foo.py", "tags": [], "user_id": 7, "note_asked": True}

    # Patch track_file_saved to capture call
    captured = {}
    def _track_file_saved(user_id, language, size_bytes):
        captured.update({"user_id": user_id, "language": language, "size_bytes": size_bytes})
    monkeypatch.setattr(mod, "track_file_saved", _track_file_saved)

    # Patch db.save_code_snippet to succeed
    class _Snippet:
        def __init__(self, user_id, file_name, code, programming_language, description=None, tags=None):
            self.user_id = user_id
            self.file_name = file_name
            self.code = code
            self.programming_language = programming_language
            self.description = description
            self.tags = tags or []
    def _save(snippet):
        return True
    monkeypatch.setattr(mod, "CodeSnippet", _Snippet)
    monkeypatch.setattr(mod.db, "save_code_snippet", _save)

    # Patch language detection
    monkeypatch.setattr(mod.code_processor, "detect_language", lambda code, name: "python")

    # Call the private save helper directly
    bot = mod.CodeKeeperBot()
    await bot._save_code_snippet(upd, ctx, code="print(1)")

    assert captured.get("user_id") == 7
    assert captured.get("language") == "python"
    assert captured.get("size_bytes") == len("print(1)")


@pytest.mark.asyncio
async def test_search_command_emits_search_metric(monkeypatch):
    import main as mod

    # Build bot and stub context
    class _Msg:
        async def reply_text(self, *a, **k):
            return None
    class _EU:
        id = 8
    class _Upd:
        def __init__(self):
            self.message = _Msg()
            self.effective_user = _EU()
    class _Ctx:
        def __init__(self):
            self.user_data = {}
            self.args = ["hello"]
    upd = _Upd()
    ctx = _Ctx()

    # Patch db.search_code to return some dummy results
    monkeypatch.setattr(mod.db, "search_code", lambda uid, q, tags=None, programming_language="": [{"file_name": "a", "programming_language": "python"}])

    # Capture metric call
    captured = {}
    def _track_search_performed(user_id, query, results_count):
        captured.update({"user_id": user_id, "query": query, "results_count": results_count})
    monkeypatch.setattr(mod, "track_search_performed", _track_search_performed)

    bot = mod.CodeKeeperBot()
    await bot.search_command(upd, ctx)

    assert captured.get("user_id") == 8
    assert captured.get("results_count") == 1
    assert isinstance(captured.get("query"), str)
