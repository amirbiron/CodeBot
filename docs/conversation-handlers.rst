Conversation Handlers & States
==============================

סקירה
-----
מסמך זה מרכז את הזרימות העיקריות של ה‑ConversationHandlers וה‑states.

רשימת States (דוגמה)
---------------------

.. code-block:: python

   class States:
       # Save flow
       WAITING_FOR_FILENAME = 1
       WAITING_FOR_CODE = 2
       WAITING_FOR_NOTE = 3

       # Edit flow
       EDITING_CODE = 10
       EDITING_FILENAME = 11

       # GitHub flow
       GITHUB_MENU = 20
       GITHUB_REPO_SELECT = 21
       GITHUB_FILE_BROWSE = 22

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

קישורים
-------

- :doc:`handlers/index`
- :doc:`architecture`
- :doc:`api/index`
