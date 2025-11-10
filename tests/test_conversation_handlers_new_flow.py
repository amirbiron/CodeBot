import types
import pytest
import conversation_handlers as ch


class _Msg:
    def __init__(self):
        self.replies = []
        self.text = ''

    async def reply_text(self, t, **kwargs):
        self.replies.append(t)


@pytest.mark.asyncio
async def test_snippet_mode_selection_and_long_collect(monkeypatch):
    # neutralize safe edit
    monkeypatch.setattr(ch, '_safe_edit_message_text', lambda *a, **k: None, raising=False)
    # stub submit
    submitted = {}
    monkeypatch.setattr(ch, '_sn_submit', lambda **kw: submitted.update(kw) or {'ok': True, 'id': 'X'}, raising=False)

    q = types.SimpleNamespace()
    upd_cb = types.SimpleNamespace(callback_query=q, effective_user=types.SimpleNamespace(id=7, username='uu'))
    ctx = types.SimpleNamespace(user_data={})

    # start – shows mode menu and ends
    state = await ch.snippet_submit_start(upd_cb, ctx)
    assert state == ch.ConversationHandler.END

    # long mode
    state = await ch.snippet_mode_long_start(upd_cb, ctx)
    assert state == ch.SN_LONG_COLLECT
    # send two parts
    upd1 = types.SimpleNamespace(message=_Msg())
    upd1.message.text = 'part1'
    assert (await ch.snippet_long_collect_receive(upd1, ctx)) == ch.SN_LONG_COLLECT
    upd2 = types.SimpleNamespace(message=_Msg())
    upd2.message.text = 'part2'
    assert (await ch.snippet_long_collect_receive(upd2, ctx)) == ch.SN_LONG_COLLECT

    # done -> moves to title
    upd_done = types.SimpleNamespace(message=_Msg())
    state = await ch.snippet_long_collect_done(upd_done, ctx)
    assert state == ch.SN_COLLECT_TITLE

    # provide title -> description (code already present skips to language next)
    upd_t = types.SimpleNamespace(message=_Msg())
    upd_t.message.text = 'My Snippet'
    assert (await ch.snippet_collect_title(upd_t, ctx)) == ch.SN_COLLECT_DESCRIPTION

    upd_desc = types.SimpleNamespace(message=_Msg())
    upd_desc.message.text = 'desc'
    # should jump to language since code exists
    assert (await ch.snippet_collect_description(upd_desc, ctx)) == ch.SN_COLLECT_LANGUAGE

    upd_lang = types.SimpleNamespace(message=_Msg(), effective_user=types.SimpleNamespace(id=7, username='uu'))
    upd_lang.message.text = 'python'
    assert (await ch.snippet_collect_language(upd_lang, ctx)) == ch.ConversationHandler.END
    assert submitted.get('code') == 'part1\npart2'
