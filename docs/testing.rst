Testing Guide
=============

עקרונות קריטיים
----------------

- כל IO בטסטים יתבצע תחת ``tmp_path`` בלבד
- שימוש ב‑``safe_rmtree`` למחיקות – אך ורק תחת ``/tmp``
- Mocking ל‑Telegram API כדי להימנע מקריאות אמתיות

דוגמת שימוש ב‑tmp_path
----------------------

.. code-block:: python

   def test_file_operations(tmp_path):
       test_file = tmp_path / "test.py"
       test_file.write_text("print('hello')")
       assert test_file.exists()

מחיקה בטוחה
-----------

.. code-block:: python

   from pathlib import Path
   import shutil

   def safe_rmtree(path: Path, allow_under: Path) -> None:
       p = path.resolve()
       base = allow_under.resolve()
       if not str(p).startswith(str(base)) or p in (Path('/'), base.parent, Path.cwd()):
           raise RuntimeError(f"Refusing to delete unsafe path: {p}")
       shutil.rmtree(p)

Mocking ל‑Telegram
------------------

.. code-block:: python

   from unittest.mock import AsyncMock, MagicMock
   from telegram import Update, Message, User, Chat

   def create_mock_update(text="test", user_id=123):
       update = MagicMock(spec=Update)
       update.effective_user = User(id=user_id, first_name="Test", is_bot=False)
       update.effective_chat = Chat(id=user_id, type="private")
       update.message = MagicMock(spec=Message)
       update.message.text = text
       update.message.reply_text = AsyncMock()
       return update

   def create_mock_context():
       context = MagicMock()
       context.bot = MagicMock()
       context.bot.send_message = AsyncMock()
       context.user_data = {}
       context.chat_data = {}
       return context

קישורים
-------

- :doc:`ci-cd`
- :doc:`ai-guidelines`
