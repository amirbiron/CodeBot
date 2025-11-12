import types
import os
import pytest

import conversation_handlers as ch


class _Cap:
    def __init__(self):
        self.calls = []
    async def edit(self, query, text, reply_markup=None, parse_mode=None):
        self.calls.append((text, reply_markup, parse_mode))


@pytest.mark.asyncio
async def test_community_reject_start_prompts_reason(monkeypatch):
    os.environ.setdefault("CHATOPS_ALLOW_ALL_IF_NO_ADMINS", "1")
    cap = _Cap()
    monkeypatch.setattr(ch, '_safe_edit_message_text', cap.edit, raising=True)
    monkeypatch.setattr(ch, '_safe_answer', lambda *a, **k: None, raising=False)

    q = types.SimpleNamespace(data='community_reject:abc')
    upd = types.SimpleNamespace(callback_query=q, effective_user=types.SimpleNamespace(id=1))
    ctx = types.SimpleNamespace(user_data={})

    state = await ch.community_reject_start(upd, ctx)
    assert state == ch.CL_REJECT_REASON
    assert ctx.user_data.get('cl_reject_id') == 'abc'
    assert cap.calls and 'סיבת דחייה' in (cap.calls[-1][0] or '')


class _Msg:
    def __init__(self):
        self.sent = []
    async def reply_text(self, text, **kwargs):
        self.sent.append(text)

class _Bot:
    def __init__(self):
        self.sent = []
    async def send_message(self, chat_id=None, text=None, **kwargs):
        self.sent.append((chat_id, text))


@pytest.mark.asyncio
async def test_community_collect_reject_reason_success_path(monkeypatch):
    os.environ.setdefault("CHATOPS_ALLOW_ALL_IF_NO_ADMINS", "1")
    # הפוך את reject_item להצלחה
    import services.community_library_service as svc
    monkeypatch.setattr(svc, 'reject_item', lambda *a, **k: True, raising=True)

    # ספק DB מזויף שמחזיר user_id עבור האייטם
    class _Coll:
        def find_one(self, q):
            return {'user_id': 777}
    class _DB:
        community_library_collection = _Coll()
    import database as db_mod
    monkeypatch.setattr(db_mod, 'db', _DB(), raising=True)

    msg = _Msg()
    upd = types.SimpleNamespace(message=msg, effective_user=types.SimpleNamespace(id=1))
    ctx = types.SimpleNamespace(user_data={'cl_reject_id': 'abc'}, bot=_Bot())

    state = await ch.community_collect_reject_reason(upd, ctx)
    # נוקתה המזהה מהקשר והסתיים
    assert 'cl_reject_id' not in ctx.user_data
    assert state == ch.ConversationHandler.END
