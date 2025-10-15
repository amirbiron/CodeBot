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