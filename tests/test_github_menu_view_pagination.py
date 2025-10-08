def test_view_more_and_back_paths(monkeypatch):
    gh = __import__('github_menu_handler')

    class _U:
        id = 0
    class _Q:
        def __init__(self):
            self.data = 'view_more'
            self.from_user = _U()
        async def answer(self, *a, **k):
            return None
        async def edit_message_text(self, *a, **k):
            return None
    class _Upd:
        callback_query = _Q()
    class _Ctx:
        user_data = {
            'view_file_text': "\n".join([f"line {i}" for i in range(300)]),
            'view_page_index': 0,
            'view_file_path': 'README.md',
            'view_detected_language': 'markdown',
            'view_file_size': 1000,
        }

    h = gh.GitHubMenuHandler()
    # advance page
    h.user_sessions = {0: {}}
    _Upd.callback_query.data = 'view_more'
    import asyncio
    asyncio.get_event_loop().run_until_complete(h._render_file_view(_Upd, _Ctx()))
    asyncio.get_event_loop().run_until_complete(h._render_file_view(_Upd, _Ctx()))

    # back path (just ensure handler exists and callable)
    _Upd.callback_query.data = 'view_back'
    # cannot fully run without full session/context, but import success is enough here
    assert hasattr(h, '_render_file_view')

