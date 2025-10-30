import types
import sys
import types as _types
import pytest

import github_menu_handler as gh


@pytest.mark.asyncio
async def test_saved_upload_uses_resources_rate_limit(monkeypatch):
    handler = gh.GitHubMenuHandler()

    # session stub
    handler.get_user_session = lambda uid: {"selected_repo": "owner/repo", "selected_folder": None}

    # stub db + repo operations
    class _Repo:
        default_branch = "main"
        def get_contents(self, *a, **k):
            raise Exception("not exists")
        def create_file(self, *a, **k):
            return types.SimpleNamespace()
    class _Github:
        def __init__(self, token):
            pass
        def get_rate_limit(self):
            class _R:
                def __init__(self):
                    self.resources = {
                        "core": types.SimpleNamespace(remaining=1000, limit=1000)
                    }
            return _R()
        def get_repo(self, name):
            return _Repo()
    monkeypatch.setattr(gh, "Github", _Github, raising=False)

    # stub update/context
    class _Query:
        async def edit_message_text(self, *a, **k):
            return None
        async def answer(self, *a, **k):
            return None
        message = types.SimpleNamespace(reply_document=lambda *a, **k: None)
    class _Update:
        callback_query = _Query()
        effective_user = types.SimpleNamespace(id=1)
    class _Ctx:
        user_data = {"upload_target_branch": "main", "upload_target_folder": None}
        application = types.SimpleNamespace()

    # stub database.db and bson.ObjectId so imports inside function succeed
    class _DB:
        collection = types.SimpleNamespace(find_one=lambda *a, **k: {"file_name": "a.py", "content": "x"})
        def get_github_token(self, user_id):
            return "t"
    import database as _database
    monkeypatch.setattr(_database, 'db', _DB(), raising=False)
    bson_mod = _types.ModuleType('bson')
    bson_mod.ObjectId = lambda x: x
    monkeypatch.setitem(sys.modules, 'bson', bson_mod)

    # run (should not raise)
    await handler.handle_saved_file_upload(_Update(), _Ctx(), "507f1f77bcf86cd799439011")
