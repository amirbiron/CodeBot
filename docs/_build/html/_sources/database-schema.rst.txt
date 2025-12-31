Database Schema
===============

Collections
-----------

``code_snippets``
~~~~~~~~~~~~~~~~~

.. code-block:: javascript

   {
     _id: ObjectId("..."),
     user_id: 123456789,
     file_name: "example.py",
     programming_language: "python",
     code: "def hello():\n    pass",
     note: "Example function",
     tags: ["python", "example"],
     created_at: ISODate("2025-10-10T10:30:00Z"),
     updated_at: ISODate("2025-10-10T10:30:00Z"),
     version: 1,
     is_deleted: false,
     file_size: 1234,
     line_count: 10
   }

``users``
~~~~~~~~~

.. code-block:: javascript

   {
     _id: ObjectId("..."),
     user_id: 123456789,
     username: "john_doe",
     first_name: "John",
     last_name: "Doe",
     created_at: ISODate("2025-01-01T00:00:00Z"),
     last_active: ISODate("2025-10-10T10:30:00Z"),
     settings: { language: "he", notifications: true },
     stats: { total_files: 156, total_searches: 45 }
   }

``bookmarks``
~~~~~~~~~~~~~

.. code-block:: javascript

   {
     _id: ObjectId("..."),
     user_id: 123456789,
     file_id: ObjectId("..."),
     bookmark_name: "Important code",
     created_at: ISODate("2025-10-10T10:30:00Z"),
     tags: ["important", "review"]
   }

``sessions`` (WebApp)
~~~~~~~~~~~~~~~~~~~~~

.. code-block:: javascript

   {
     _id: "session_id_here",
     user_id: 123456789,
     created_at: ISODate("2025-10-10T10:30:00Z"),
     expires_at: ISODate("2025-10-11T10:30:00Z"),
     data: { }
   }

Indexes
-------

.. code-block:: javascript

   // code_snippets
   db.code_snippets.createIndex({ "user_id": 1, "created_at": -1 })
   db.code_snippets.createIndex({ "programming_language": 1 })
   db.code_snippets.createIndex({ "file_name": "text", "code": "text", "note": "text" })
   db.code_snippets.createIndex({ "tags": 1 })
   db.code_snippets.createIndex({ "is_deleted": 1 })

   // users
   db.users.createIndex({ "user_id": 1 }, { unique: true })
   db.users.createIndex({ "username": 1 })

   // bookmarks
   db.bookmarks.createIndex({ "user_id": 1, "file_id": 1 })

   // sessions
   db.sessions.createIndex({ "expires_at": 1 }, { expireAfterSeconds: 0 })

Relationships
-------------

.. code-block:: none

   users (user_id)
     ├─→ code_snippets (user_id)
     └─→ bookmarks (user_id)
             └─→ code_snippets (_id via file_id)

קישורים
-------

- :doc:`database/index`
- :doc:`architecture`
