import types
import pytest

import conversation_handlers as ch


class _Capture:
    def __init__(self):
        self.text = None
        self.markup = None


@pytest.mark.asyncio
async def test_snippets_menu_back_goes_to_community_hub(monkeypatch):
    cap = _Capture()

    async def _fake_edit(query, text, reply_markup=None, parse_mode=None):
        cap.text, cap.markup = text, reply_markup
        return None

    monkeypatch.setattr(ch, '_safe_edit_message_text', _fake_edit, raising=True)
    monkeypatch.setattr(ch, '_safe_answer', lambda *a, **k: None, raising=False)

    q = types.SimpleNamespace()
    upd = types.SimpleNamespace(callback_query=q, effective_user=types.SimpleNamespace(id=1))
    ctx = types.SimpleNamespace()

    await ch.snippets_menu(upd, ctx)
    btn = cap.markup.inline_keyboard[-1][0]
    assert btn.text == '↩️ חזרה'
    assert btn.callback_data == 'community_hub'


@pytest.mark.asyncio
async def test_community_catalog_menu_back_goes_to_community_hub(monkeypatch):
    cap = _Capture()

    async def _fake_edit(query, text, reply_markup=None, parse_mode=None):
        cap.text, cap.markup = text, reply_markup
        return None

    monkeypatch.setattr(ch, '_safe_edit_message_text', _fake_edit, raising=True)
    monkeypatch.setattr(ch, '_safe_answer', lambda *a, **k: None, raising=False)

    q = types.SimpleNamespace()
    upd = types.SimpleNamespace(callback_query=q, effective_user=types.SimpleNamespace(id=1))
    ctx = types.SimpleNamespace()

    await ch.community_catalog_menu(upd, ctx)
    btn = cap.markup.inline_keyboard[-1][0]
    assert btn.text == '↩️ חזרה'
    assert btn.callback_data == 'community_hub'
