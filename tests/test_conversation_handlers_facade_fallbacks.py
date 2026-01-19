import types
import pytest


@pytest.mark.asyncio
async def test_show_by_repo_menu_uses_facade_when_available(monkeypatch):
    import conversation_handlers as ch

    stub_facade = types.SimpleNamespace(
        get_repo_tags_with_counts=lambda user_id, max_tags=20: [
            {"tag": "repo:me/app", "count": 2},
        ]
    )
    monkeypatch.setattr(ch, "_get_files_facade_or_none", lambda: stub_facade)

    class DummyMessage:
        def __init__(self):
            self.text = None
            self.reply_markup = None

        async def reply_text(self, text=None, reply_markup=None):
            self.text = text
            self.reply_markup = reply_markup

    class DummyUpdate:
        def __init__(self):
            self.message = DummyMessage()

        @property
        def effective_user(self):
            return types.SimpleNamespace(id=42)

    upd = DummyUpdate()
    await ch.show_by_repo_menu(upd, types.SimpleNamespace(user_data={}))

    markup = upd.message.reply_markup
    assert markup is not None
    callbacks = [row[0].callback_data for row in markup.inline_keyboard[:-1]]
    assert "by_repo:repo:me/app" in callbacks


@pytest.mark.asyncio
async def test_show_by_repo_menu_empty_when_facade_has_no_tags(monkeypatch):
    import conversation_handlers as ch

    # Facade returns empty list to trigger fallback
    stub_facade = types.SimpleNamespace(
        get_repo_tags_with_counts=lambda *a, **k: []
    )
    monkeypatch.setattr(ch, "_get_files_facade_or_none", lambda: stub_facade)

    captured = {}

    class DummyMessage:
        async def reply_text(self, text=None, reply_markup=None):
            captured["text"] = text
            captured["reply_markup"] = reply_markup

    class DummyUpdate:
        def __init__(self):
            self.message = DummyMessage()

        @property
        def effective_user(self):
            return types.SimpleNamespace(id=99)

    await ch.show_by_repo_menu(DummyUpdate(), types.SimpleNamespace(user_data={}))

    assert captured.get("text") == "ℹ️ אין קבצים עם תגית ריפו."
