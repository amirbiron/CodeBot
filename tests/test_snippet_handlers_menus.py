import types
import pytest

import conversation_handlers as ch


class _Msg:
    def __init__(self):
        self.sent = []

    async def reply_text(self, text, **kwargs):
        self.sent.append((text, kwargs))


class _Query:
    def __init__(self):
        self.edits = []
        self.data = ''

    async def answer(self):
        return None

    async def edit_message_text(self, text=None, reply_markup=None, parse_mode=None):
        self.edits.append((text, reply_markup, parse_mode))


@pytest.mark.asyncio
async def test_show_community_hub_menu(monkeypatch):
    upd = types.SimpleNamespace(message=_Msg(), effective_user=types.SimpleNamespace(id=1))
    ctx = types.SimpleNamespace()
    await ch.show_community_hub(upd, ctx)
    assert upd.message.sent


@pytest.mark.asyncio
async def test_snippets_submenu(monkeypatch):
    # neutralize TelegramUtils wrappers
    monkeypatch.setattr(ch, 'TelegramUtils', types.SimpleNamespace(safe_answer=lambda q: None), raising=False)
    q = _Query()
    upd = types.SimpleNamespace(callback_query=q, effective_user=types.SimpleNamespace(id=1))
    ctx = types.SimpleNamespace()
    await ch.snippets_menu(upd, ctx)
    assert q.edits  # edited a message


@pytest.mark.asyncio
async def test_community_catalog_submenu(monkeypatch):
    monkeypatch.setattr(ch, 'TelegramUtils', types.SimpleNamespace(safe_answer=lambda q: None), raising=False)
    q = _Query()
    upd = types.SimpleNamespace(callback_query=q, effective_user=types.SimpleNamespace(id=1))
    ctx = types.SimpleNamespace()
    await ch.community_catalog_menu(upd, ctx)
    assert q.edits
