import types
import pytest

import github_menu_handler as gh


@pytest.mark.asyncio
async def test_show_upload_repos_counts_tags(monkeypatch):
    class _Btn:
        def __init__(self, text, callback_data=None):
            self.text = text
            self.callback_data = callback_data
    class _Markup:
        def __init__(self, keyboard):
            self.keyboard = keyboard
    class _Query:
        def __init__(self):
            self.edits = []
        async def edit_message_text(self, text, reply_markup=None):
            self.edits.append({"text": text, "reply_markup": reply_markup})
    class _Upd:
        def __init__(self):
            self.callback_query = _Query()
            self.effective_user = types.SimpleNamespace(id=1)

    # דמה DB שמחזיר file_name+tags כדי לאפשר repo ספירה
    fake_db = types.SimpleNamespace(
        get_user_files=lambda user_id, limit=500, projection=None: [
            {"file_name": "a.py", "tags": ["repo:owner/x"]},
            {"file_name": "b.py", "tags": ["misc"]},
            {"file_name": "c.py", "tags": ["repo:owner/x"]},
        ]
    )
    monkeypatch.setitem(__import__('sys').modules, 'database', types.SimpleNamespace(db=fake_db))

    # הזרקת רכיבי UI
    monkeypatch.setattr(gh, 'InlineKeyboardButton', _Btn, raising=True)
    monkeypatch.setattr(gh, 'InlineKeyboardMarkup', _Markup, raising=True)

    handler = gh.GitHubMenuHandler()
    upd = _Upd()
    ctx = types.SimpleNamespace()

    await handler.show_upload_repos(upd, ctx)
    assert upd.callback_query.edits, "expected an edit with repo list"
    # וידוא שקיים טקסט של repo אחד לפחות בכפתורים
    markup = upd.callback_query.edits[-1]['reply_markup']
    flat_texts = [btn.text for row in markup.keyboard for btn in row]
    assert any("repo:owner/x" in t for t in flat_texts)
