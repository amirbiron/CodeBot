import types
import pytest

import conversation_handlers as ch


class _Msg:
    def __init__(self, text=''):
        self.text = text
        self.calls = []

    async def reply_text(self, t, **kwargs):
        self.calls.append((t, kwargs))


def _main_btn():
    # Pick any visible button text from the main keyboard
    for row in ch.MAIN_KEYBOARD:
        for t in row:
            if isinstance(t, str) and t.strip():
                return t
    return '📚 הצג את כל הקבצים שלי'


@pytest.mark.asyncio
async def test_autocancel_snippet_collect_title_on_main_menu_press():
    ctx = types.SimpleNamespace(user_data={'sn_item': {}})
    upd = types.SimpleNamespace(message=_Msg(_main_btn()))
    state = await ch.snippet_collect_title(upd, ctx)
    assert state == ch.ConversationHandler.END
    assert ctx.user_data == {}
    assert upd.message.calls, 'expected cancel reply'


@pytest.mark.asyncio
async def test_autocancel_snippet_collect_description_on_main_menu_press():
    ctx = types.SimpleNamespace(user_data={'sn_item': {'title': 't'}})
    upd = types.SimpleNamespace(message=_Msg(_main_btn()))
    state = await ch.snippet_collect_description(upd, ctx)
    assert state == ch.ConversationHandler.END
    assert ctx.user_data == {}


@pytest.mark.asyncio
async def test_autocancel_snippet_collect_code_on_main_menu_press():
    ctx = types.SimpleNamespace(user_data={'sn_item': {'title': 't', 'description': 'd'}})
    upd = types.SimpleNamespace(message=_Msg(_main_btn()))
    state = await ch.snippet_collect_code(upd, ctx)
    assert state == ch.ConversationHandler.END


@pytest.mark.asyncio
async def test_autocancel_snippet_collect_language_on_main_menu_press():
    ctx = types.SimpleNamespace(user_data={'sn_item': {'title': 't', 'description': 'd', 'code': 'print(1)'}})
    upd = types.SimpleNamespace(message=_Msg(_main_btn()))
    state = await ch.snippet_collect_language(upd, ctx)
    assert state == ch.ConversationHandler.END


@pytest.mark.asyncio
async def test_autocancel_snippet_long_collect_receive_on_main_menu_press():
    ctx = types.SimpleNamespace(user_data={'sn_long_parts': []})
    upd = types.SimpleNamespace(message=_Msg(_main_btn()))
    state = await ch.snippet_long_collect_receive(upd, ctx)
    assert state == ch.ConversationHandler.END


@pytest.mark.asyncio
async def test_autocancel_community_collect_title_on_main_menu_press():
    ctx = types.SimpleNamespace(user_data={'cl_item': {}})
    upd = types.SimpleNamespace(message=_Msg(_main_btn()))
    state = await ch.community_collect_title(upd, ctx)
    assert state == ch.ConversationHandler.END
    assert ctx.user_data == {}


@pytest.mark.asyncio
async def test_autocancel_community_collect_description_on_main_menu_press():
    ctx = types.SimpleNamespace(user_data={'cl_item': {'title': 'x'}})
    upd = types.SimpleNamespace(message=_Msg(_main_btn()))
    state = await ch.community_collect_description(upd, ctx)
    assert state == ch.ConversationHandler.END


@pytest.mark.asyncio
async def test_autocancel_community_collect_url_on_main_menu_press():
    ctx = types.SimpleNamespace(user_data={'cl_item': {'title': 'x', 'description': 'd'}})
    upd = types.SimpleNamespace(message=_Msg(_main_btn()))
    state = await ch.community_collect_url(upd, ctx)
    assert state == ch.ConversationHandler.END


@pytest.mark.asyncio
async def test_autocancel_community_collect_logo_on_main_menu_press():
    ctx = types.SimpleNamespace(user_data={'cl_item': {'title': 'x', 'description': 'd', 'url': 'http://e'}})
    upd = types.SimpleNamespace(message=_Msg(_main_btn()), effective_user=types.SimpleNamespace(id=1))
    state = await ch.community_collect_logo(upd, ctx)
    assert state == ch.ConversationHandler.END
