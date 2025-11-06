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
async def test_snippet_submission_flow(monkeypatch):
    # stub service
    called = {}
    monkeypatch.setattr(ch, '_sn_submit', lambda **kw: called.update(kw) or {'ok': True, 'id': '1'}, raising=False)
    # neutralize safe edit
    monkeypatch.setattr(ch, '_safe_edit_message_text', lambda *a, **k: None, raising=False)

    # start
    q = types.SimpleNamespace()
    upd_start = types.SimpleNamespace(callback_query=q)
    ctx = types.SimpleNamespace(user_data={})
    state = await ch.snippet_submit_start(upd_start, ctx)
    assert state == ch.SN_COLLECT_TITLE

    # title too short
    upd_t1 = types.SimpleNamespace(message=_Msg())
    state = await ch.snippet_collect_title(upd_t1, ctx)
    assert state == ch.SN_COLLECT_TITLE

    # valid title => description
    upd_t2 = types.SimpleNamespace(message=_Msg())
    upd_t2.message.text = 'Valid Title'
    state = await ch.snippet_collect_title(upd_t2, ctx)
    assert state == ch.SN_COLLECT_DESCRIPTION

    # description => code
    upd_d = types.SimpleNamespace(message=_Msg())
    upd_d.message.text = 'desc'
    state = await ch.snippet_collect_description(upd_d, ctx)
    assert state == ch.SN_COLLECT_CODE

    # code required
    upd_c_bad = types.SimpleNamespace(message=_Msg())
    upd_c_bad.message.text = ''
    state = await ch.snippet_collect_code(upd_c_bad, ctx)
    assert state == ch.SN_COLLECT_CODE

    # code ok => language, then submit
    upd_c = types.SimpleNamespace(message=_Msg())
    upd_c.message.text = 'print(1)'
    state = await ch.snippet_collect_code(upd_c, ctx)
    assert state == ch.SN_COLLECT_LANGUAGE

    upd_l = types.SimpleNamespace(message=_Msg(), effective_user=types.SimpleNamespace(id=5, username='u'))
    upd_l.message.text = 'py'
    state = await ch.snippet_collect_language(upd_l, ctx)
    assert state == ch.ConversationHandler.END
    assert called['title'] == 'Valid Title'
    assert called['language'] == 'py'
