import types

import pytest

import conversation_handlers as ch


class _Msg:
    def __init__(self):
        self.texts = []
        self.text = None

    async def reply_text(self, t, **kwargs):  # noqa: D401
        self.texts.append(t)


@pytest.mark.asyncio
async def test_snippet_collect_reject_reason(monkeypatch):
    called = {}

    def _reject(item_id, admin_id, reason):
        called['args'] = (item_id, admin_id, reason)
        return True

    monkeypatch.setenv('ADMIN_USER_IDS', '1')
    monkeypatch.setattr('services.snippet_library_service.reject_snippet', _reject, raising=False)

    upd = types.SimpleNamespace(
        message=_Msg(),
        effective_user=types.SimpleNamespace(id=1),
    )
    ctx = types.SimpleNamespace(user_data={'sn_reject_id': 'abc'})

    # run
    await ch.snippet_collect_reject_reason(upd, ctx)

    assert called.get('args') == ('abc', 1, None)
    # state cleared
    assert 'sn_reject_id' not in ctx.user_data
