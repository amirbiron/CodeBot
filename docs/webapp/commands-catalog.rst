תחזוקת קטלוג הפקודות (``commands.json``)
=========================================

מבוא
----
קטלוג הפקודות ב-``webapp/static/data/commands.json`` מזין את כרטיסי ה-"קיצורי דרך"
שנראים בחיפוש הגלובלי (קיצור מקלדת ``Ctrl/Cmd+K``). בכל טעינת דף, ה-frontend מושך את
הקובץ דרך ``/static/data/commands.json`` ומוסיף את הכרטיסים שזוהו ברמת הטייפ
(``chatops``/``cli``/``playbook``) על בסיס הקוד ב-``webapp/static/js/global_search.js``.

.. important::

   אי-אפשר להוסיף כלי חדש או פקודת ChatOps למערכת בלי לעדכן גם את
   ``commands.json``. כל פיצ'ר שמציג קיצור דרך חייב לכלול עדכון קטלוג
   + בדיקה ידנית שהפריט החדש מופיע בחיפוש.

מבנה הנתונים (Schema)
----------------------
- ``name`` – שם ייחודי כפי שהוא מוקלד על ידי המשתמש (כלל: ChatOps מתחיל ב-``/``,
  CLI בדרך כלל ``./scripts/...`` או שם בינארי, Playbook הוא נתיב ``playbooks/*.yml``).
- ``type`` – אחד מהערכים ``chatops``, ``cli`` או ``playbook``.
- ``description`` – משפט קצר בעברית, עד 80 תווים, שמסביר למה להפיץ את הכלי.
- ``arguments`` – רשימת מחרוזות. כל ערך הוא placeholder אחד בדיוק כמו שמופיע בדוקומנטציה.
- ``doc_link`` – קישור HTTPS לעמוד התיעוד המקורי (אפשר עם עוגן ``#section``).

.. note::
   שמרו על סדר כניסות יציב (ממויין לפי ``name`` או לפי קיבוץ הסוג) כדי להפחית קונפליקטים
   ולמנוע היסטוריית Git עמוסה.

דוגמת JSON
-----------

.. code-block:: json

   [
     {
       "name": "/triage",
       "type": "chatops",
       "description": "פותח סשן חקירה מהיר ומציג חריגות פעילות",
       "arguments": [
         "--service=<שם שירות>",
         "--severity=<low|high>"
       ],
       "doc_link": "https://amirbiron.github.io/CodeBot/chatops/commands.html#triage"
     },
     {
       "name": "./scripts/start_webapp.sh",
       "type": "cli",
       "description": "מרים מקומית את ה-WebApp עם ASSET_VERSION מחושב ואפשרות warmup",
       "arguments": [
         "PORT=5000",
         "WEBAPP_WARMUP_PATHS=/dashboard,/collections"
       ],
       "doc_link": "https://amirbiron.github.io/CodeBot/development/scripts.html#scripts-start_webapp-sh"
     },
     {
       "name": "playbooks/github_backup_restore.yml",
       "type": "playbook",
       "description": "הפעלה סדורה של גיבוי GitHub ושחזור מלא דרך runbook",
       "arguments": [
         "--dry-run",
         "--region=<eu|us>"
       ],
       "doc_link": "https://amirbiron.github.io/CodeBot/runbooks/github_backup_restore.html"
     }
   ]

הנחיות סיווג (Taxonomy)
-----------------------
- **ChatOps** – פקודות שמתחילות ב-``/`` ונצרכות דרך הבוט (ראו :doc:`/chatops/commands`).
  הן מוצגות תמיד לפני שאר הכרטיסים כדי לעודד שימוש מהיר ב-Telegram.
- **CLI** – סקריפטים/בינארים מקומיים (למשל קבצים תחת ``./scripts`` או `make` ייעודי).
  הערך ``name`` חייב להיות בדיוק הפקודה שהמפתח יריץ במסוף.
- **Playbook** – קבצי YAML להפעלת תרחישים (Ansible, Runbooks). ה-frontend מחפש את המחרוזת
  ``playbooks/`` כדי להוסיף אייקון ייעודי.

טיפים לזיהוי אוטומטי
^^^^^^^^^^^^^^^^^^^^
- התחלה ב-``/`` ⇒ ``type=chatops``.
- התחלה ב-``./`` או ``scripts/`` ⇒ ``type=cli``.
- שם שמכיל ``playbooks/`` או שמסתיים ב-``.yml`` ⇒ ``type=playbook``.
- אם הזיהוי האוטומטי לא חד-משמעי, קובע הערך שכתבתם ב-JSON – וודאו שהוא עקבי עם ההנחיות.

צ'ק-ליסט להוספת פקודה
----------------------
1. הוסיפו ערך חדש ל-``webapp/static/data/commands.json`` עם כל השדות הנ"ל.
2. ודאו שהקישור ב-``doc_link`` מחזיר 200:

   .. code-block:: sh

      curl -I https://amirbiron.github.io/CodeBot/chatops/commands.html

3. שמרו על תיאור קצר, ללא HTML, והוסיפו placeholders ברורים בארגומנטים (``--flag=<value>``).
4. עדכנו גרסת נכסים סטטיים: בכל פיתוח/פריסה הציבו ערך חדש ל-``ASSET_VERSION`` (ראו
   ``scripts/start_webapp.sh``) כדי שהדפדפנים יורידו את הקטלוג המעודכן.
5. הריצו את החיפוש הגלובלי ובדקו שהכרטיס מופיע ומתויג בסוג הנכון (ראו סעיף "בדיקות").

בדיקות
------
1. הפעילו את ה-WebApp מקומית:

   .. code-block:: sh

      ./scripts/start_webapp.sh

2. פתחו ``http://localhost:5000`` (או הפורט שבחרתם) ולחצו ``Ctrl/Cmd+K`` כדי לפתוח חיפוש.
3. חפשו פקודה קיימת כגון ``/triage`` כדי לוודא שהקטלוג נטען.
4. חפשו את הפקודה החדשה ובדקו:
   - שהטקסט והטיפוס נכונים.
   - שלחיצה על הכרטיס פותחת את ``doc_link`` בחלון חדש.
   - שכרטיסי CLI ו-Playbook מתויגים באייקון הנכון (כדי ללכוד תקלות טקסונומיה).
5. אם נעשה שימוש בקבצים סטטיים מקאש, רעננו עם ``Ctrl+Shift+R`` או פתחו חלון פרטי כדי לנקות
   Service Worker/Cache.

לסיכום – כל פיצ'ר שמוסיף כלי חדש חייב לעבור דרך הקטלוג, לעבור את הצ'ק-ליסט הזה ולהשאיר עקבות
בדוקומנטציה (הקישור בד"כ מצביע על העמוד שבו תיארתם את הפיצ'ר).
