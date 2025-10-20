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

GitHub – Scopes נדרשים
-----------------------

להפעלת פעולות שונות מול GitHub נדרש להגדיר לטוקן \(`GITHUB_TOKEN` או טוקן משתמש שנשמר במערכת\) את מרחבי ההרשאות המינימליים. הקפידו על עיקרון ההרשאות המצומצמות.

.. list-table:: Feature → Required Scopes
   :header-rows: 1

   * - Feature
     - Required Scopes
   * - Create Pull Request
     - ``repo``, ``workflow``
   * - Write files (Trees/Contents API)
     - ``repo``
   * - Read repository metadata (branches, commits, PRs)
     - ``repo``
   * - Trigger workflows / read checks status
     - ``workflow``

למידע נוסף וגרסה מסונכרנת של הטבלה ראו גם: :doc:`environment-variables`.

Troubleshooting GitHub – Rate limits
------------------------------------

בעת חריגה ממכסת ה‑API של GitHub, ייתכן ותקבלו שגיאות כמו ``403 Forbidden`` עם כותרות ``X-RateLimit-Remaining: 0`` או הודעה על ``secondary rate limit``. המערכת מיישמת Backoff עם ניסיונות חוזרים מדורגים, אך מומלץ:

- להפחית את קצב הבקשות ולצמצם סריקות
- לאגד פעולות ולנצל Cache פנימי
- להשתמש ב‑ChatOps לצפייה במצב מגבלות ובשגיאות

קישורים רלוונטיים:

- :doc:`api/chatops.ratelimit`
- :doc:`chatops/permissions`
- :doc:`troubleshooting`
- :doc:`git-lfs`
- :doc:`runbooks/github_backup_restore`

GitHub CLI (gh) – תקציר קצר
----------------------------

הכלי ``gh`` מקל על עבודה מול GitHub משורת הפקודה. דוגמאות נפוצות:

.. code-block:: bash

   # כניסה
   gh auth login

   # יצירת PR
   gh pr create --title "feat: update docs" --body "Why and test plan"

   # סטטוס/מעבר ל‑PR
   gh pr status
   gh pr checkout <PR_NUMBER>

ל‑Cheatsheet מלא ומקיף ראו: :doc:`quickstart-ai`.

Repository Providers
--------------------

תמיכה בספקי מאגרי קוד מפורטת כאן: :doc:`repository-integrations`. נכון לעכשיו: **נתמך – GitHub**; **לא נתמך – GitLab/Bitbucket**.

Best Practices – מאגרים גדולים/Monorepos
-----------------------------------------

- הגדירו דילוג על תיקיות כבדות בסריקות (למשל ``node_modules/``, ``dist/``, ``.venv/``)
- בצעו חיפושים ממוקדים לפי סוג קובץ/ספריות רלוונטיות
- חלקו תיעוד ותתי‑מודולים לפי תחומים כדי להקל ניווט
- ודאו ש‑CI ומנגנוני קאש מקומיים מוגדרים נכון למונוריפו (Artifacts, dependency caching)
