Integrations
============

GitHub API
----------

יצירת Gist (דוגמה)
~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   from github import Github
   from github.InputFileContent import InputFileContent

   g = Github(github_token)
   user = g.get_user()
   gist = user.create_gist(
       public=False,
       files={"example.py": InputFileContent("print('hello')")},
       description="Code snippet from bot"
   )
   print(gist.html_url)

Google Drive (OAuth Flow)
-------------------------

.. code-block:: python

   from google_auth_oauthlib.flow import Flow
   from googleapiclient.discovery import build

   flow = Flow.from_client_secrets_file(
       'credentials.json',
       scopes=['https://www.googleapis.com/auth/drive.file'],
       redirect_uri='http://localhost:5000/oauth2callback'
   )
   authorization_url, state = flow.authorization_url(
       access_type='offline',
       include_granted_scopes='true'
   )
   # ...

Telegram Webhooks vs Polling
----------------------------

.. code-block:: python

   # Polling
   app.run_polling()

.. code-block:: python

   # Webhook
   app.run_webhook(listen="0.0.0.0", port=8443, url_path="/webhook", webhook_url="https://your-domain.com/webhook")

קישורים
-------

- :doc:`services/index`
- :doc:`handlers/index`
