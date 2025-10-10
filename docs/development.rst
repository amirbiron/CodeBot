Development Workflow
====================

הוספת Handler חדש
------------------

.. code-block:: python

   # handlers/my_feature.py
   async def my_command(update, context):
       await update.message.reply_text("Hello!")

   # main.py
   from handlers.my_feature import my_command
   app.add_handler(CommandHandler("mycommand", my_command))

   # tests/test_my_feature.py
   @pytest.mark.asyncio
   async def test_my_command():
       ...

הוספת Endpoint ל‑WebApp
------------------------

.. code-block:: python

   # webapp/app.py
   @app.route('/my-endpoint')
   @login_required
   def my_endpoint():
       return render_template('my_page.html')

עדכון Schema במסד הנתונים
--------------------------

.. code-block:: python

   # database/models.py
   class CodeSnippet:
       def __init__(self, new_field=None):
           self.new_field = new_field

   # migration script
   def migrate_add_new_field(db):
       db.code_snippets.update_many(
           {"new_field": {"$exists": False}},
           {"$set": {"new_field": None}}
       )

קישורים
-------

- :doc:`architecture`
- :doc:`conversation-handlers`
- :doc:`testing`
