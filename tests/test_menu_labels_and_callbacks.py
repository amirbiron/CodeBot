import types
import pytest

import conversation_handlers as ch


@pytest.fixture(autouse=True)
def _webapp_url(monkeypatch):
    """כפתורי ה-web בתפריטים נבנים מ-WEBAPP_URL בלבד, בלי ברירת מחדל — הכתובת נקבעת כאן במפורש."""
    monkeypatch.setenv("WEBAPP_URL", "https://webapp.test")


class _Captured:
    def __init__(self):
        self.last_markup = None
        self.last_text = None


@pytest.mark.asyncio
async def test_snippets_menu_labels(monkeypatch):
    cap = _Captured()
    async def _fake_edit(query, text, reply_markup=None, parse_mode=None):
        cap.last_text = text
        cap.last_markup = reply_markup
        return None
    monkeypatch.setattr(ch, '_safe_edit_message_text', _fake_edit, raising=True)
    monkeypatch.setattr(ch, '_safe_answer', lambda *a, **k: None, raising=False)

    q = types.SimpleNamespace()
    upd = types.SimpleNamespace(callback_query=q, effective_user=types.SimpleNamespace(id=1))
    ctx = types.SimpleNamespace()

    await ch.snippets_menu(upd, ctx)
    assert 'ספריית סניפטים' in (cap.last_text or '')
    # verify buttons texts
    btn_texts = [b.text for row in cap.last_markup.inline_keyboard for b in row]
    assert 'ספריית סניפטים (🌐 web)' in btn_texts
    assert '↩️ חזרה' in btn_texts


@pytest.mark.asyncio
async def test_community_catalog_menu_labels(monkeypatch):
    cap = _Captured()
    async def _fake_edit(query, text, reply_markup=None, parse_mode=None):
        cap.last_text = text
        cap.last_markup = reply_markup
        return None
    monkeypatch.setattr(ch, '_safe_edit_message_text', _fake_edit, raising=True)
    monkeypatch.setattr(ch, '_safe_answer', lambda *a, **k: None, raising=False)

    q = types.SimpleNamespace()
    upd = types.SimpleNamespace(callback_query=q, effective_user=types.SimpleNamespace(id=1))
    ctx = types.SimpleNamespace()

    await ch.community_catalog_menu(upd, ctx)
    assert 'ממשקי משתמשים' in (cap.last_text or '')
    btn_texts = [b.text for row in cap.last_markup.inline_keyboard for b in row]
    assert 'ממשקי משתמשים (🌐 web)' in btn_texts
    assert '↩️ חזרה' in btn_texts
