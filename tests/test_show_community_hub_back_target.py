import types
import pytest

import conversation_handlers as ch


class _Msg:
    def __init__(self):
        self.kw = None
    async def reply_text(self, text, **kwargs):
        self.kw = {'text': text, **kwargs}


@pytest.mark.asyncio
async def test_show_community_hub_back_button_points_to_main_menu():
    upd = types.SimpleNamespace(message=_Msg(), effective_user=types.SimpleNamespace(id=1))
    ctx = types.SimpleNamespace()

    await ch.show_community_hub(upd, ctx)
    rm = upd.message.kw.get('reply_markup')
    # last row should be back to main menu
    btn = rm.inline_keyboard[-1][0]
    assert btn.text == '↩️ חזרה'
    assert btn.callback_data == 'main_menu'
