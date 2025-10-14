import sys
import types
import pytest


@pytest.mark.asyncio
async def test_show_by_repo_menu_and_multi_delete_flow(monkeypatch):
    sys.modules.pop('conversation_handlers', None)
    ch = __import__('conversation_handlers')

    # Stub DB methods used
    db_mod = __import__('database', fromlist=['db'])
    class _DB:
        def get_repo_tags_with_counts(self, user_id, max_tags=20):
            return [("repo:org/proj", 2)]
        def _get_repo(self):
            class _R:
                def list_regular_files(self, user_id, page=1, per_page=20, **k):
                    return ([{"_id":"1","file_name":"a.py","programming_language":"python","version":1,"updated_at":__import__('datetime').datetime.now(__import__('datetime').timezone.utc),"tags":["repo:org/proj"]}], 1)
                def move_file_to_trash_by_id(self, user_id, fid):
                    return True
            return _R()
    monkeypatch.setattr(db_mod, 'db', _DB(), raising=True)

    # Stubs for telegram bits
    class _Msg:
        async def reply_text(self, *a, **k):
            return None
    class _Q:
        data = ''
        async def answer(self, *a, **k):
            return None
        async def edit_message_text(self, *a, **k):
            return None
    class _User: id = 7
    class _Upd:
        effective_user = _User()
        message = _Msg()
        callback_query = _Q()
    class _Ctx:
        user_data = {}

    # show_by_repo_menu
    await ch.show_by_repo_menu(_Upd(), _Ctx())

    # הצגת תפריט לפי ריפו (callback by_repo_menu)
    _Upd.callback_query.data = 'by_repo_menu'
    await ch.show_by_repo_menu_callback(_Upd(), _Ctx())

    # הפעלה מצב מחיקה מרובה ואז אישור העברה לסל
    _Ctx.user_data['rf_multi_delete'] = True
    _Ctx.user_data['rf_selected_ids'] = ['1']
    _Upd.callback_query.data = 'rf_delete_confirm'
    await ch.handle_callback_query(_Upd(), _Ctx())

