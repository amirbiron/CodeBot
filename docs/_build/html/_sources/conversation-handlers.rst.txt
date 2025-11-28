Conversation Handlers & States
==============================

סקירה
-----
מסמך זה מרכז את הזרימות העיקריות של ה‑ConversationHandlers וה‑states.

רשימת States (מבחר בפועל)
--------------------------

.. code-block:: python

   # handlers/states.py
   GET_CODE, GET_FILENAME, GET_NOTE, EDIT_CODE, EDIT_NAME, WAIT_ADD_CODE_MODE, LONG_COLLECT = range(7)

   # ספריית סניפטים – זרימת הגשה
   CL_COLLECT_TITLE, CL_COLLECT_DESCRIPTION, CL_COLLECT_URL, CL_COLLECT_LOGO = range(7, 11)
   SN_COLLECT_TITLE, SN_COLLECT_DESCRIPTION, SN_COLLECT_CODE, SN_COLLECT_LANGUAGE = range(11, 15)
   SN_REJECT_REASON = 15
   SN_LONG_COLLECT = 16

   # github_menu_handler.py (שיחות העלאה)
   REPO_SELECT, FILE_UPLOAD, FOLDER_SELECT = range(3)

Save Flow (תרשים מצבים)
------------------------

.. mermaid::

   stateDiagram-v2
       [*] --> WAITING_FOR_FILENAME: /save
       WAITING_FOR_FILENAME --> WAITING_FOR_CODE: שם קובץ התקבל
       WAITING_FOR_CODE --> WAITING_FOR_NOTE: קוד התקבל
       WAITING_FOR_NOTE --> [*]: הערה התקבלה/דילוג
       WAITING_FOR_FILENAME --> [*]: /cancel
       WAITING_FOR_CODE --> [*]: /cancel
       WAITING_FOR_NOTE --> [*]: /cancel

GitHub Flow (תרשים מצבים)
-------------------------

ספריית סניפטים – זרימת הגשה (Bot)
-----------------------------------

.. list-table:: Snippet Submit Flow
   :header-rows: 1

   * - שלב
     - תיאור
   * - בחירת מצב
     - "🧩 קוד רגיל" או "✍️ קוד ארוך" (מצב איסוף רב־חלקי, סיום ב־/done)
   * - SN_COLLECT_TITLE
     - קבלת כותרת (3–180)
   * - SN_COLLECT_DESCRIPTION
     - קבלת תיאור קצר (עד 1000)
   * - SN_COLLECT_CODE / SN_LONG_COLLECT
     - קבלת קוד (חד־חלקי או רב־חלקי)
   * - SN_COLLECT_LANGUAGE
     - קבלת שפה (python/js/…)

ביטול הוגן
~~~~~~~~~~~
- כפתור ``❌ ביטול`` מסיים את הזרימה ומנקה ``context.user_data``.
- לחיצה על כל כפתור אחר בזמן הזרימה מבטלת אוטומטית את ההקשר (אין "הידבקות" של כפתורים לטקסט הקלט).

התראות אדמין והודעת משתמש
~~~~~~~~~~~~~~~~~~~~~~~~~~
- אדמין מקבל Inline Keyboard לאישור/דחייה + כפתור "👁️ הצג סניפט" (ווב־אפ).
- המשתמש מקבל הודעה ידידותית בעת אישור/דחייה (כולל סיבת דחייה אם צוינה).

.. mermaid::

   stateDiagram-v2
       [*] --> GITHUB_MENU: /github
       GITHUB_MENU --> GITHUB_REPO_SELECT: "בחר ריפו"
       GITHUB_REPO_SELECT --> GITHUB_FILE_BROWSE: ריפו נבחר
       GITHUB_FILE_BROWSE --> GITHUB_FILE_BROWSE: ניווט בתיקיות
       GITHUB_FILE_BROWSE --> [*]: קובץ נשמר
       GITHUB_MENU --> [*]: חזרה
       GITHUB_REPO_SELECT --> GITHUB_MENU: חזרה
       GITHUB_FILE_BROWSE --> GITHUB_REPO_SELECT: חזרה

דוגמת Handler תמציתית
----------------------

.. code-block:: python

   save_conversation = ConversationHandler(
       entry_points=[CommandHandler('save', start_save)],
       states={
           States.WAITING_FOR_FILENAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_filename)],
           States.WAITING_FOR_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_code)],
           States.WAITING_FOR_NOTE: [
               MessageHandler(filters.TEXT & ~filters.COMMAND, receive_note),
               CallbackQueryHandler(skip_note, pattern='^skip_note$')
           ],
       },
       fallbacks=[CommandHandler('cancel', cancel)],
       name="save_conversation",
       persistent=True,
   )

טבלת זרימות מלאה
-----------------

.. list-table:: Flows Summary
   :header-rows: 1
   :widths: 12 18 28 24 18

   * - פקודה / טריגר
     - Entry Point
     - States מרכזיים
     - Handlers עיקריים
     - קישורי קוד
   * - ``/save``
     - ``/save`` (פקודה) ו/או כפתור "➕ הוסף קוד חדש"
     - ``GET_CODE → GET_FILENAME → GET_NOTE``
     - ``handlers.save_flow``: ``start_save_flow``, ``get_code``, ``get_filename``, ``get_note``, ``save_file_final``
     - `save_flow.py (start_save_flow) <https://github.com/amirbiron/CodeBot/blob/2a57121371c4d99ecec93160d6f78100976026cf/handlers/save_flow.py#L123-L137>`_ ·
       `get_code <https://github.com/amirbiron/CodeBot/blob/2a57121371c4d99ecec93160d6f78100976026cf/handlers/save_flow.py#L279-L304>`_ ·
       `get_filename <https://github.com/amirbiron/CodeBot/blob/2a57121371c4d99ecec93160d6f78100976026cf/handlers/save_flow.py#L307-L338>`_ ·
       `get_note <https://github.com/amirbiron/CodeBot/blob/2a57121371c4d99ecec93160d6f78100976026cf/handlers/save_flow.py#L341-L349>`_ ·
       `save_file_final <https://github.com/amirbiron/CodeBot/blob/2a57121371c4d99ecec93160d6f78100976026cf/handlers/save_flow.py#L352-L401>`_
   * - ``/github`` + ``upload_file``
     - ``github_menu_command`` (תפריט), ``upload_conv_handler`` (שיחת העלאה)
     - ``FILE_UPLOAD → REPO_SELECT → FOLDER_SELECT`` (העלאה); תפריט GitHub מתנהל ב־CallbackQuery
     - ``github_menu_handler.GitHubMenuHandler``: ``github_menu_command``, ``handle_menu_callback``, ``handle_file_upload``, ``handle_text_input``
     - `github_menu_command <https://github.com/amirbiron/CodeBot/blob/2a57121371c4d99ecec93160d6f78100976026cf/github_menu_handler.py#L697-L792>`_ ·
       `upload_conv_handler (main.py) <https://github.com/amirbiron/CodeBot/blob/2a57121371c4d99ecec93160d6f78100976026cf/main.py#L739-L759>`_
   * - ``/backup``
     - ``BackupMenuHandler.show_backup_menu``
     - — (דיאלוג כפתורים באמצעות ``CallbackQuery`` בלבד)
     - ``BackupMenuHandler.handle_callback_query``
     - `show_backup_menu <https://github.com/amirbiron/CodeBot/blob/2a57121371c4d99ecec93160d6f78100976026cf/backup_menu_handler.py#L146-L160>`_ ·
       `handle_callback_query <https://github.com/amirbiron/CodeBot/blob/2a57121371c4d99ecec93160d6f78100976026cf/backup_menu_handler.py#L162-L306>`_
   * - ``/drive``
     - ``GoogleDriveMenuHandler.menu``
     - — (דיאלוג כפתורים באמצעות ``CallbackQuery`` בלבד)
     - ``GoogleDriveMenuHandler.handle_callback``
     - `menu <https://github.com/amirbiron/CodeBot/blob/2a57121371c4d99ecec93160d6f78100976026cf/handlers/drive/menu.py#L142-L187>`_ ·
       `handle_callback <https://github.com/amirbiron/CodeBot/blob/2a57121371c4d99ecec93160d6f78100976026cf/handlers/drive/menu.py#L188-L210>`_

הערות וקישורי API רלוונטיים:

- **שירותים**: :mod:`services.code_service`, :mod:`services.github_service`, :mod:`services.backup_service`, :mod:`services.google_drive_service`
- **שיחת שמירה מרכזית**: `conversation_handlers.get_save_conversation_handler <https://github.com/amirbiron/CodeBot/blob/2a57121371c4d99ecec93160d6f78100976026cf/conversation_handlers.py#L2998-L3048>`_
- **פקודת /save** (זרימה מקוצרת): `main.py: save_command <https://github.com/amirbiron/CodeBot/blob/2a57121371c4d99ecec93160d6f78100976026cf/main.py#L1074-L1121>`_

קישורים
-------

- :doc:`handlers/index`
- :doc:`architecture`
- :doc:`api/index`

דוגמאות קוד תמציתיות (ממשיות)
--------------------------------

Save – שלבים עיקריים
~~~~~~~~~~~~~~~~~~~~~

.. literalinclude:: ../handlers/save_flow.py
   :language: python
   :lines: 123-137
   :caption: handlers/save_flow.py – start_save_flow

.. literalinclude:: ../handlers/save_flow.py
   :language: python
   :lines: 279-304
   :caption: handlers/save_flow.py – get_code

.. literalinclude:: ../handlers/save_flow.py
   :language: python
   :lines: 307-338
   :caption: handlers/save_flow.py – get_filename

.. literalinclude:: ../handlers/save_flow.py
   :language: python
   :lines: 341-349
   :caption: handlers/save_flow.py – get_note

.. literalinclude:: ../handlers/save_flow.py
   :language: python
   :lines: 352-401
   :caption: handlers/save_flow.py – save_file_final

GitHub – תפריט ושיחת העלאה
~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. literalinclude:: ../github_menu_handler.py
   :language: python
   :lines: 697-792
   :caption: github_menu_handler.py – github_menu_command

.. literalinclude:: ../main.py
   :language: python
   :lines: 739-759
   :caption: main.py – הגדרת upload_conv_handler (FILE_UPLOAD/REPO_SELECT/FOLDER_SELECT)

Backup – תפריט
~~~~~~~~~~~~~~~

.. literalinclude:: ../backup_menu_handler.py
   :language: python
   :lines: 146-160
   :caption: backup_menu_handler.py – show_backup_menu

.. literalinclude:: ../backup_menu_handler.py
   :language: python
   :lines: 162-210
   :caption: backup_menu_handler.py – handle_callback_query (קטע ראשון)

Drive – תפריט
~~~~~~~~~~~~~~

.. literalinclude:: ../handlers/drive/menu.py
   :language: python
   :lines: 142-187
   :caption: handlers/drive/menu.py – GoogleDriveMenuHandler.menu

.. literalinclude:: ../handlers/drive/menu.py
   :language: python
   :lines: 188-210
   :caption: handlers/drive/menu.py – GoogleDriveMenuHandler.handle_callback (קטע ראשון)

מוקשים נפוצים ופתרונות
-----------------------

``query.answer()``
~~~~~~~~~~~~~~~~~~

.. code-block:: python

   # ❌ טעות נפוצה: חסר await
   query.answer()

   # ✅ נכון
   await query.answer()

עריכת הודעות בבטחה – "Message is not modified"
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

השתמשו ב־``TelegramUtils.safe_edit_message_text`` / ``safe_edit_message_reply_markup`` כדי לבלוע את החריגה הספציפית בלבד.

.. code-block:: python

   from utils import TelegramUtils

   await TelegramUtils.safe_edit_message_text(query, "טקסט", reply_markup=kb)

Filters
~~~~~~~

במכונות מצבים: המנעו מללכוד פקודות בתור טקסט חופשי.

.. code-block:: python

   MessageHandler(filters.TEXT & ~filters.COMMAND, get_code)

Persistent data (``context.user_data``)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

שמרו דגלים זמניים ובנקודות מעבר (למשל ב־GitHub paste/upload):

.. code-block:: python

   context.user_data["waiting_for_paste_content"] = True
   context.user_data.pop("waiting_for_paste_filename", None)

דוגמאות טסטים קצרות
---------------------

Save – התחלה וזרימה בסיסית
~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   import pytest

   @pytest.mark.asyncio
   async def test_save_flow_happy_path(mock_update, mock_context):
       # Arrange – התחלת זרימה
       from handlers import save_flow
       state = await save_flow.start_save_flow(mock_update, mock_context)
       assert state == save_flow.GET_CODE

       # Act – קבלת קוד ושם
       mock_update.message.text = "print('hi')\n"
       state = await save_flow.get_code(mock_update, mock_context)
       assert state == save_flow.GET_FILENAME

       mock_update.message.text = "script.py"
       state = await save_flow.get_filename(mock_update, mock_context)
       assert state == save_flow.GET_NOTE

       mock_update.message.text = "תיאור"
       state = await save_flow.get_note(mock_update, mock_context)
       # Assert – השיחה מסתיימת לאחר שמירה מוצלחת
       from telegram.ext import ConversationHandler
       assert state in (ConversationHandler.END,)

GitHub – upload_conv_handler
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   @pytest.mark.asyncio
   async def test_github_upload_conversation(mock_update_cb, mock_context):
       # סימולציית כניסה למסך העלאה ובדיקת רישום ה-handlers
       from main import create_application
       app = create_application("dummy")
       # קיימים states FILE_UPLOAD/REPO_SELECT/FOLDER_SELECT – אין צורך להריץ בוט אמיתי בטסט זה
       assert any("ConversationHandler" in type(h).__name__ for h in app.handlers)
