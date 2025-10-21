import types
import pytest

import batch_commands as bc
import conversation_handlers as ch


@pytest.mark.asyncio
async def test_batch_analyze_command_uses_projection(monkeypatch):
    # DB שמחזיר רק file_name (projection), ומוודאים שאין קריסה
    fake_db = types.SimpleNamespace(
        get_user_files=lambda user_id, limit=500, projection=None: [
            {"file_name": "a.py"}, {"file_name": "b.py"}
        ]
    )
    monkeypatch.setattr(bc, 'db', fake_db, raising=True)
    monkeypatch.setattr(bc, 'batch_processor', types.SimpleNamespace(
        analyze_files_batch=lambda user_id, files: "job-1"
    ), raising=True)

    class _Msg:
        async def reply_text(self, *a, **k):
            return None
    upd = types.SimpleNamespace(effective_user=types.SimpleNamespace(id=1), message=_Msg())
    ctx = types.SimpleNamespace(args=["all"], application=None)
    await bc.batch_analyze_command(upd, ctx)


@pytest.mark.asyncio
async def test_conversation_handlers_batch_menu_projection(monkeypatch):
    # ודא שהקריאה עם projection לא קורסת בסינון other
    fake_db = types.SimpleNamespace(
        get_user_files=lambda user_id, limit=500, projection=None: [
            {"file_name": "a.py", "tags": ["repo:x/y"]},
            {"file_name": "b.py", "tags": ["misc"]},
        ]
    )
    # הזרקה לתוך המודול
    monkeypatch.setitem(__import__('sys').modules, 'database', types.SimpleNamespace(db=fake_db))

    # סטאבים ל־UI
    class _Btn:
        def __init__(self, text, callback_data=None):
            self.text = text
            self.callback_data = callback_data
    class _Markup:
        def __init__(self, keyboard):
            self.keyboard = keyboard
    async def _ans():
        return None

    monkeypatch.setattr(ch, 'InlineKeyboardButton', _Btn, raising=True)
    monkeypatch.setattr(ch, 'InlineKeyboardMarkup', _Markup, raising=True)

    # קריאה לפונקציה שממקמת את התפריט לפי קטגוריה 'other'
    upd = types.SimpleNamespace(callback_query=types.SimpleNamespace(answer=_ans, edit_message_text=lambda *a, **k: None), effective_user=types.SimpleNamespace(id=1))
    ctx = types.SimpleNamespace(user_data={"batch_target": {"type": "other"}})
    await ch.show_batch_files_menu(upd, ctx)