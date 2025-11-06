import types
import pytest

import conversation_handlers as ch


class _Msg:
    def __init__(self):
        self.texts = []

    async def reply_text(self, t, **kwargs):
        self.texts.append(t)


@pytest.mark.asyncio
async def test_snippet_admin_commands(monkeypatch):
    monkeypatch.setenv('ADMIN_USER_IDS', '1')

    # queue
    monkeypatch.setattr('services.snippet_library_service.list_pending_snippets', lambda **k: [{'_id': '1', 'title': 'A'}], raising=False)
    upd = types.SimpleNamespace(message=_Msg(), effective_user=types.SimpleNamespace(id=1))
    ctx = types.SimpleNamespace()
    await ch.snippet_queue_command(upd, ctx)
    assert upd.message.texts

    # approve
    called = {}
    monkeypatch.setattr('services.snippet_library_service.approve_snippet', lambda *a, **k: called.update({'ok': True}) or True, raising=False)
    upd2 = types.SimpleNamespace(message=_Msg(), effective_user=types.SimpleNamespace(id=1))
    ctx2 = types.SimpleNamespace(args=['1'])
    await ch.snippet_approve_command(upd2, ctx2)
    assert called.get('ok') is True

    # reject
    called2 = {}
    monkeypatch.setattr('services.snippet_library_service.reject_snippet', lambda *a, **k: called2.update({'ok': True}) or True, raising=False)
    upd3 = types.SimpleNamespace(message=_Msg(), effective_user=types.SimpleNamespace(id=1))
    ctx3 = types.SimpleNamespace(args=['1', 'bad'])
    await ch.snippet_reject_command(upd3, ctx3)
    assert called2.get('ok') is True
