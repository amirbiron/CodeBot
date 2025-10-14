import pytest


@pytest.mark.asyncio
async def test_show_batch_files_menu_repo(monkeypatch):
    ch = __import__('conversation_handlers')

    class _Q:
        async def answer(self, *a, **k):
            return None
        async def edit_message_text(self, *a, **k):
            return None
    class _Upd:
        def __init__(self):
            self.callback_query = _Q()
            class _U: id = 3
            self.effective_user = _U()
    class _Ctx:
        def __init__(self):
            self.user_data = {'batch_target': {'type': 'repo', 'tag': 'repo:foo/bar'}}

    # stub db.search_code
    db_mod = __import__('database', fromlist=['db'])
    class _DB:
        def search_code(self, user_id, query, tags, limit):
            return [{'file_name': 'a.py'}, {'file_name': 'b.py'}]
    monkeypatch.setattr(db_mod, 'db', _DB(), raising=True)

    await ch.show_batch_files_menu(_Upd(), _Ctx())

