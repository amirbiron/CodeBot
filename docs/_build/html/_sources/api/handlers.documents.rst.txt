handlers.documents module
=========================

תיאור כללי
-----------

``handlers.documents`` מרכז את הטיפול במסמכים וקבצים שנשלחים לבוט (Facade). הוא אחראי לנתב בין מסלולי GitHub, ZIP וקבצים טקסטואליים, ולשמור מדדים ואירועי Observability לאורך הזרימה.

נקודות הרחבה עיקריות
---------------------

- ``DocumentHandler.handle_document`` – נקודת הכניסה; בודקת ``upload_mode`` ומפנה למסלול המתאים.
- ``DocumentHandler._handle_github_restore_zip_to_repo`` – שחזור ZIP לריפו קיים (Commit מרובה קבצים).
- ``DocumentHandler._handle_github_create_repo_from_zip`` – יצירת ריפו חדש והעלאת תכולת ה‑ZIP.
- ``DocumentHandler._handle_zip_import`` – יבוא ZIP פנימי (Backup) ושחזור קבצים לחשבון המשתמש.
- ``DocumentHandler._handle_zip_create`` – צבירת קבצים ל‑bundle ZIP לשימוש חוזר.
- ``DocumentHandler._handle_textual_file`` – נרמול, זיהוי קידוד ושמירה של קבצים טקסטואליים/קוד.

קישורים לטסטים רלוונטיים
-------------------------

- ``tests/handlers/test_documents.py`` – כיסוי למסלולי ``upload_mode`` ולתוצאות צפויות.

API Reference
-------------

.. automodule:: handlers.documents
   :members:
   :undoc-members:
   :show-inheritance:
