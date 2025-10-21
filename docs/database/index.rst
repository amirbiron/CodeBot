Database
========

תיעוד של מערכת מסד הנתונים והמודלים.

Database Manager
----------------

.. automodule:: database
   :members:
   :undoc-members:
   :show-inheritance:
   :noindex:

Models
------

CodeSnippet Model
~~~~~~~~~~~~~~~~~

.. autoclass:: database.CodeSnippet
   :members:
   :undoc-members:
   :show-inheritance:
   :noindex:

DatabaseManager Class
~~~~~~~~~~~~~~~~~~~~~

.. autoclass:: database.DatabaseManager
   :members:
   :undoc-members:
   :show-inheritance:
   :noindex:

Database Operations
-------------------

Save Operations
~~~~~~~~~~~~~~~

.. automethod:: database.DatabaseManager.save_snippet
   :noindex:

Search Operations
~~~~~~~~~~~~~~~~~

.. automethod:: database.DatabaseManager.search_snippets
   :noindex:
.. automethod:: database.DatabaseManager.get_snippet
   :noindex:
.. automethod:: database.DatabaseManager.get_user_snippets
   :noindex:

Delete Operations
~~~~~~~~~~~~~~~~~

.. automethod:: database.DatabaseManager.delete_snippet
   :noindex:
.. automethod:: database.DatabaseManager.delete_all_user_snippets
   :noindex:

Statistics Operations
~~~~~~~~~~~~~~~~~~~~~

.. automethod:: database.DatabaseManager.get_user_statistics
   :noindex:
.. automethod:: database.DatabaseManager.get_global_statistics
   :noindex:

אינדקסים בקולקציית users
-------------------------
האינדקסים מוגדרים אוטומטית בעת אתחול ``database.manager.DatabaseManager``:

- ``user_id_unique`` – אינדקס ייחודי על ``user_id``
- ``username_unique`` – אינדקס ייחודי, ``sparse`` על ``username`` (מאפשר ערכים חסרים)
- ``last_activity_desc`` – אינדקס מיון לפי פעילות אחרונה (``last_activity`` יורד)

הדבר מאפשר:
- שליפה מהירה לפי מזהה משתמש
- אכיפת ייחודיות שמות משתמש כשקיימים
- דוחות וטבלאות פעילות מסודרות לפי זמן פעילות אחרון

ראו גם: :doc:`indexing` למדריך מפורט והסברים על ``explain()``.