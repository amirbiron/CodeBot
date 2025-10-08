import pytest


@pytest.mark.asyncio
async def test_view_back_to_search(monkeypatch):
    gh = __import__('github_menu_handler')

    class _Q:
        data = 'view_back'
        class _User:
            id = 1
        from_user = _User()
        async def answer(self, *a, **k):
            return None
        async def edit_message_text(self, *a, **k):
            return None
    class _User:
        id = 1
    class _Upd:
        def __init__(self):
            self.callback_query = _Q()
            self.effective_user = _User()
    class _Ctx:
        user_data = {'last_results_were_search': True}

    h = gh.GitHubMenuHandler()

    async def _show_search(update, context):
        # stub search results rendering
        return None
    monkeypatch.setattr(h, 'show_browse_search_results', _show_search, raising=True)

    await h._render_file_view(_Upd, _Ctx())

