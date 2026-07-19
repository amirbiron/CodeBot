שרת ה-MCP — חיבור Claude ל-CodeKeeper
======================================

שרת `MCP <https://modelcontextprotocol.io>`_ (Model Context Protocol) שחושף את
CodeKeeper ל-Claude: הקבצים והאוספים האישיים של כל משתמש, ולאדמין — גם **דפדפן
הריפו** מעל ה-Repo Sync Engine. עובד גם מול **Claude.ai** (Custom Connector דרך
OAuth 2.1) וגם מול **Claude Code / Claude Desktop** (טוקן אישי).

**קוד:** ``mcp_server/`` · **תכנון מלא:**
``FEATURE_SUGGESTIONS/FEATURE_MCP_CLAUDE_INTEGRATION.md``

מה זה נותן
-----------

- Claude קורא ומחפש בקבצים השמורים שלך ישירות — בלי העתק-הדבק ובלי צילומי מסך.
- שמירה (יצירה/עדכון) מאחורי הרשאת ``write`` מפורשת — עדכון תמיד יוצר
  **גרסה חדשה**
  (append-only), אף פעם לא דורס.
- לאדמין: קריאה וחיפוש בכל הריפואים המשוקפים (תיעוד, קוד, מסמכי תכנון).

ארכיטקטורה בקצרה
------------------

.. code-block:: text

   Claude.ai / Claude Code
        │  Streamable HTTP (+OAuth 2.1 או Bearer PAT)
        ▼
   שירות MCP נפרד (ASGI, uvicorn)  ── import ישיר ──▶  database/ → MongoDB
        │                                              (code_snippets, collections)
        └── דפדפן ריפו (אדמין) ──▶ bare mirrors בדיסק המקומי (REPO_MIRROR_PATH)

- ה-``user_id`` נגזר **תמיד מהטוקן** — לעולם לא מקלט הלקוח.
- מכבד את חוק ה-Smart Projection: רשימות/חיפוש מחזירים מטא-דאטה בלבד;
  תוכן מלא רק
  בבקשה מפורשת לקובץ בודד.

הכלים
------

כלי משתמש (לכל משתמש מחובר):

.. list-table::
   :header-rows: 1
   :widths: 35 65

   * - כלי
     - תיאור
   * - ``codekeeper_list_files``
     - רשימת קבצים (מטא-דאטה, עם עימוד)
   * - ``codekeeper_search_code``
     - חיפוש טקסט → מטא-דאטה של קבצים תואמים
   * - ``codekeeper_get_file``
     - תוכן מלא של קובץ (לפי שם/מזהה, אופציונלית גרסה)
   * - ``codekeeper_save_file``
     - **כתיבה:** יצירה/עדכון קובץ (גרסה חדשה; עד 100KB). דורש ``write``
   * - ``codekeeper_list_versions``
     - היסטוריית גרסאות של קובץ
   * - ``codekeeper_list_collections`` / ``codekeeper_get_collection`` / ``codekeeper_get_collection_items``
     - האוספים והקבצים שבתוכם

כלי אדמין (דפדפן הריפו — מוסתרים וחסומים לכל משתמש אחר):

.. list-table::
   :header-rows: 1
   :widths: 35 65

   * - כלי
     - תיאור
   * - ``codekeeper_list_repos``
     - הריפואים המשוקפים (מטא-דאטה)
   * - ``codekeeper_list_repo_tree``
     - נתיבי קבצים בריפו (עימוד, סינון תיקייה/ref; בלי תוכן)
   * - ``codekeeper_get_repo_file``
     - תוכן קובץ בודד (עד 500KB; קובץ בינארי → מטא-דאטה בלבד)
   * - ``codekeeper_search_repo``
     - חיפוש טקסט בריפו (קטעים קצרים עם path+line, עם תקרות)

אימות והרשאות
--------------

שני מסלולים, מאוחדים באותו שרת:

1. **OAuth 2.1** — עבור Claude.ai (Custom Connector). זרימה מלאה: רישום
   לקוח דינמי
   (DCR) + PKCE + מסך אישור. הזהות נקבעת דרך התחברות הטלגרם בוובאפ.
2. **טוקן אישי (PAT)** — עבור Claude Code / Desktop. מונפק מהבוט בפקודת
   ``/connect_claude`` (או ``/connect_claude write`` לטוקן עם הרשאת כתיבה),
   נשמר כ-hash בלבד וניתן לביטול.

שכבות ההרשאה:

- ``read`` — ברירת המחדל לכל חיבור.
- ``write`` — נדרש ל-``codekeeper_save_file``; ניתן רק באישור מפורש
  (מסך ההרשאה ב-Claude.ai או טוקן ``write`` מהבוט).
- **אדמין** — כלי הריפו זמינים רק למשתמשים שב-``ADMIN_USER_IDS``; לכל אחד
  אחר הם
  גם לא מופיעים ברשימת הכלים וגם נחסמים בקריאה ישירה (fail-closed).

הפעלה — צעד אחר צעד
--------------------

שלב 1 — שירות חדש
~~~~~~~~~~~~~~~~~~

שירות web נפרד (ASGI) ב-Render, שמתחבר **לאותו MongoDB** של הבוט והוובאפ:

.. code-block:: text

   Start command:  uvicorn mcp_server.app:app --host 0.0.0.0 --port $PORT
   Health check:   /healthz

שלב 2 — מצב בסיס (PAT בלבד)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

מספיק כדי לעבוד מול Claude Code / Desktop:

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - משתנה
     - הערה
   * - ``MONGODB_URL`` + ``DATABASE_NAME``
     - זהים לבוט/וובאפ
   * - ``BOT_TOKEN``
     - נדרש רק לטעינת מודול ה-config המשותף

שלב 3 — מצב OAuth (מוסיף את Claude.ai)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

נדלק אוטומטית כשמוגדרים **בשירות ה-MCP**:

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - משתנה
     - הערה
   * - ``MCP_SERVER_URL``
     - ה-URL הציבורי (https) של שירות ה-MCP
   * - ``WEBAPP_URL``
     - ה-URL הציבורי של הוובאפ (למסך התחברות הטלגרם)
   * - ``SECRET_KEY``
     - **זהה לוובאפ**, ערך אקראי חזק (≥16 תווים) — חותם את זהות המשתמש בין השירותים

בנוסף: על **הוובאפ** להגדיר ``MCP_SERVER_URL`` (+אותו ``SECRET_KEY``), ועל
**הבוט** ``MCP_SERVER_URL`` (לפקודת ``/connect_claude``).

שלב 4 — דפדפן הריפו (אדמין, אופציונלי)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - משתנה
     - הערה
   * - ``ADMIN_USER_IDS``
     - מזהה הטלגרם של האדמין (CSV). ריק = הכלים כבויים לכולם
   * - ``REPO_MIRROR_PATH`` + דיסק מצורף
     - ב-Render דיסק הוא פר-שירות; בלי דיסק ה-mirrors משוכפלים מחדש אחרי כל deploy
   * - ``GITHUB_TOKENS`` / ``GITHUB_TOKEN``
     - רק לריפואים פרטיים (אימות ל-clone/fetch)

אין צורך ב-``GITHUB_WEBHOOK_SECRET`` בשירות ה-MCP — ה-webhook ממשיך להגיע
לוובאפ
בלבד, וה-MCP מתעדכן לבד (ראו "רענון אוטומטי" למטה).

הרשימה המלאה של המשתנים: :doc:`environment-variables`.

חיבור לקוחות
-------------

Claude.ai (Custom Connector)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Settings → Connectors → **Add custom connector** → הזינו את הכתובת::

   https://<mcp-host>/mcp

זהו — Claude מבצע DCR + OAuth לבד, מפנה להתחברות טלגרם ולמסך אישור. אין צורך
ב-Client ID/Secret. כדי לקבל **write**, ה-connector צריך להירשם עם ההרשאה — אם
כבר חיברתם לקריאה בלבד, הסירו והוסיפו מחדש ואשרו "קריאה וכתיבה".

Claude Code (טוקן)
~~~~~~~~~~~~~~~~~~~

שלחו לבוט בצ'אט פרטי ``/connect_claude`` (או ``/connect_claude write``), ואז:

.. code-block:: bash

   claude mcp add --transport http codekeeper https://<mcp-host>/mcp \
     --header "Authorization: Bearer <token>"

Claude Desktop
~~~~~~~~~~~~~~~

ב-``claude_desktop_config.json``:

.. code-block:: json

   {
     "mcpServers": {
       "codekeeper": {
         "type": "http",
         "url": "https://<mcp-host>/mcp",
         "headers": { "Authorization": "Bearer <token>" }
       }
     }
   }

דפדפן הריפו — איך זה עובד
---------------------------

רענון אוטומטי (autosync)
~~~~~~~~~~~~~~~~~~~~~~~~~

שירות ה-MCP מריץ thread רקע (אותו דפוס כמו ה-worker בוובאפ) ששומר על ה-mirrors
המקומיים טריים — בלי cron ובלי שירות נוסף:

.. code-block:: text

   merge ל-main → GitHub webhook → הוובאפ מסנכרן את הדיסק שלו וכותב SHA ל-Mongo
               → ה-autosync ב-MCP מזהה שה-SHA המקומי שונה → git fetch מקומי

- ריפו שקיים ב-``repo_metadata`` אך חסר בדיסק המקומי — **משוכפל אוטומטית**
  (אין צורך ב-import ידני בצד ה-MCP).
- שליטה: ``MCP_REPO_AUTOSYNC`` (ברירת מחדל פעיל),
  ``MCP_REPO_AUTOSYNC_INTERVAL``
  (ברירת מחדל 300 שניות).

מדיניות סינון סודות
~~~~~~~~~~~~~~~~~~~~

נתיבים רגישים (``.env*``, ``*.pem``, ``*.key``, ``id_rsa*``, ``secrets.*``,
``credentials*`` ועוד) **נחסמים** בקריאת קובץ, **מושמטים** מרשימות ו**מדולגים**
בחיפוש — בכל הריפואים, תמיד. ההתאמה case-insensitive על הנתיב המלא וה-basename
(תופסת גם ``config/.env`` מקונן). הרחבת הרשימה: ``MCP_REPO_DENYLIST_EXTRA``
(CSV של תבניות glob). על שגיאה פנימית המדיניות **נכשלת סגור** (חוסמת).

התנהגות בזמן sync
~~~~~~~~~~~~~~~~~~

אין נעילת קריאה מול ה-sync, ולכן קריאה שנכשלת בזמן ש-sync רץ מחזירה::

   {"ok": false, "error": "sync_in_progress", "retry_after": 30}

זה סימן **לנסות שוב אחרי המתנה קצרה** — לא להסיק שהקובץ או הריפו לא קיימים.

אבטחה — עקרונות
----------------

- זהות תמיד מהטוקן; טוקנים נשמרים כ-hash בלבד ומוצגים פעם אחת.
- קוד הרשאה ו-refresh token חד-פעמיים (זיהוי replay); refresh לא מרחיב הרשאות.
- ``SECRET_KEY`` חלש/ריק/ברירת-מחדל — מצב OAuth מסרב לעלות (fail-closed).
- מסך האישור מציג במדויק קריאה בלבד לעומת קריאה וכתיבה.
- כלי האדמין: הסתרה מ-tools/list היא נוחות בלבד — האכיפה האמיתית היא בגוף
  כל כלי.

פתרון תקלות
------------

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - סימפטום
     - כיוון
   * - ``401 invalid_token``
     - הטוקן בוטל/פג או ששירות ה-MCP מחובר ל-MongoDB אחר מזה שהנפיק אותו
   * - ``421 Invalid Host header``
     - ``MCP_ALLOWED_HOSTS`` מגדיר host שלא תואם; ריק = הבדיקה כבויה
   * - ``bad_assertion`` במסך האישור
     - ``SECRET_KEY`` לא זהה בין הוובאפ לשירות ה-MCP
   * - ``insufficient_scope`` בשמירה
     - חיבור בקריאה בלבד — חברו מחדש עם write (או ``/connect_claude write``)
   * - ``admin_only`` בכלי ריפו
     - ה-user_id אינו ב-``ADMIN_USER_IDS`` בשירות ה-MCP
   * - ``sync_in_progress``
     - רענון רץ ברגע זה — נסו שוב לפי ``retry_after``
   * - ``repo_or_ref_not_found``
     - ה-mirror עוד לא שוכפל מקומית (המתינו למעבר autosync) או שאין דיסק/``REPO_MIRROR_PATH``

ראו גם
-------

- :doc:`environment-variables` — כל משתני הסביבה (כולל קטגוריית MCP)
- ``mcp_server/README.md`` — תיעוד תפעולי קצר בתוך הריפו
- ``FEATURE_SUGGESTIONS/FEATURE_MCP_CLAUDE_INTEGRATION.md`` — מסמך התכנון המלא
- :doc:`security` — מדיניות האבטחה הכללית
