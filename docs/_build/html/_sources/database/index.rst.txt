Database
========

תיעוד של מערכת מסד הנתונים והמודלים.

Database Manager
----------------

.. automodule:: database
   :members:
   :undoc-members:
   :show-inheritance:

Models
------

CodeSnippet Model
~~~~~~~~~~~~~~~~~

.. autoclass:: database.CodeSnippet
   :members:
   :undoc-members:
   :show-inheritance:

DatabaseManager Class
~~~~~~~~~~~~~~~~~~~~~

.. autoclass:: database.DatabaseManager
   :members:
   :undoc-members:
   :show-inheritance:

Database Operations
-------------------

Save Operations
~~~~~~~~~~~~~~~

.. automethod:: database.DatabaseManager.save_snippet

Search Operations
~~~~~~~~~~~~~~~~~

.. automethod:: database.DatabaseManager.search_snippets
.. automethod:: database.DatabaseManager.get_snippet
.. automethod:: database.DatabaseManager.get_user_snippets

Delete Operations
~~~~~~~~~~~~~~~~~

.. automethod:: database.DatabaseManager.delete_snippet
.. automethod:: database.DatabaseManager.delete_all_user_snippets

Statistics Operations
~~~~~~~~~~~~~~~~~~~~~

.. automethod:: database.DatabaseManager.get_user_statistics
.. automethod:: database.DatabaseManager.get_global_statistics