הרצת קוד (Code Execution Playground)
====================================

ב‑WebApp יש כלי שמאפשר להריץ קוד Python מתוך הדפדפן, דרך API ייעודי.

.. important::

   זה פיצ׳ר "מסוכן" מטבעו: הוא מריץ קוד שמגיע מהמשתמש. בפרודקשן **מומלץ להריץ רק בתוך Docker sandbox**
   ולהשאיר את ``CODE_EXEC_ALLOW_FALLBACK=false`` (Fail‑Closed).

איפה זה ב‑UI?
-------------
- כתובת: ``/tools/code``
- כפתור **▶️ הרץ** (מופיע רק כשהפיצ׳ר פעיל ולמשתמש יש הרשאה)
- קיצור מקלדת: ``Ctrl+Enter`` / ``Cmd+Enter``
- לשונית **"פלט"** מציגה:
  - ``stdout``, ``stderr``
  - ``exit_code``
  - זמן ריצה (``execution_time_ms``)
  - אינדיקציה אם הפלט קוצץ (``truncated``)

הרשאות (Premium/Admin)
----------------------
הכלל במערכת הוא ש‑Code Tools הם Admin‑only, אבל **הרצת קוד היא חריג**:

- **Premium + Admin** יכולים:
  - ``GET /api/code/run/limits``
  - ``POST /api/code/run``
- משתמש רגיל יקבל ``403`` עם הודעת שגיאה בסגנון ``Premium/Admin בלבד``.
- משתמש לא מחובר יקבל ``401`` עם הודעת שגיאה בסגנון ``נדרש להתחבר``.

Feature Flag (זמינות הפיצ׳ר)
----------------------------
- ``FEATURE_CODE_EXECUTION`` שולט האם הפיצ׳ר פעיל בשרת (default: ``false``).
- כשהדגל כבוי:
  - ה‑UI מסתיר את כפתור **"הרץ"**.
  - הקריאה ל‑``POST /api/code/run`` תחזיר ``403`` עם ``"הרצת קוד מושבתת בשרת זה"``.

API
---

GET ``/api/code/run/limits``
^^^^^^^^^^^^^^^^^^^^^^^^^^^^
מחזיר זמינות, מגבלות, ורשימת imports מותרים.

דוגמה:

.. code-block:: sh

   curl -sS -H "Cookie: session=<...>" \
     "https://<host>/api/code/run/limits"

Response (shape):

.. code-block:: json

   {
     "enabled": true,
     "limits": {
       "max_timeout_seconds": 30,
       "max_memory_mb": 128,
       "max_code_length_bytes": 51200,
       "max_output_bytes": 102400,
       "docker_available": false,
       "docker_required": true,
       "fallback_allowed": false,
       "docker_image": "python:3.11-slim"
     },
     "allowed_imports": ["math", "random", "..."]
   }

POST ``/api/code/run``
^^^^^^^^^^^^^^^^^^^^^^
מריץ קוד Python ומחזיר פלט בסוף הריצה (לא streaming).

Request:

.. code-block:: json

   {
     "code": "import math\nprint(math.pi)\n",
     "timeout": 5,
     "memory_limit_mb": 128
   }

Response (shape):

.. code-block:: json

   {
     "success": true,
     "stdout": "3.141592653589793\n",
     "stderr": "",
     "exit_code": 0,
     "execution_time_ms": 12,
     "truncated": false,
     "error": null
   }

.. note::

   השרת מהדק את הערכים לפי המגבלות שלו (לדוגמה: ``timeout`` לא יעלה על ``max_timeout_seconds``).

אבטחה: מה יש ומה חשוב להבין
----------------------------

Docker sandbox (מומלץ)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
כאשר Docker זמין והוגדר לשימוש, ההרצה מתבצעת בקונטיינר עם הגנות כמו:

- ``--network none`` (ללא רשת)
- ``--read-only`` + ``--tmpfs /tmp`` (מערכת קבצים קריאה בלבד + tmp קטן)
- ``--cap-drop=ALL`` + ``--security-opt=no-new-privileges``
- ``--user=nobody``
- מגבלות משאבים: CPU / Memory / PIDs
- Timeout (עם גרייס קצר ל-overhead של Docker)

חסימת קוד "מסוכן"
^^^^^^^^^^^^^^^^^
יש שכבת סינון לפני הרצה:

- **Blocklist בסיסית** על טקסט (למשל ``import os``, ``eval(``, ``exec(`` וכו׳).
- **Allowlist ל-imports דרך AST**: רק מודולים מתוך רשימת ``allowed_imports`` מותרים.

.. warning::

   הסינון הזה הוא שכבת הגנה נוספת, אבל הוא **לא** תחליף לבידוד (Docker / Runner).

לוגים ופרטיות
^^^^^^^^^^^^^
- השרת **לא אמור** ללוגג את הקוד או את הפלט.
- כן נרשם לוג מטא‑דאטה (למשל זמן ריצה, exit code, האם Docker שימש, האם הפלט קוצץ).

Fail‑Closed מול Fallback
----------------------------
ברירת המחדל המומלצת בפרודקשן היא Fail‑Closed:

- ``CODE_EXEC_USE_DOCKER=true``
- ``CODE_EXEC_ALLOW_FALLBACK=false``

אם Docker לא זמין (למשל בסביבות כמו Render) – ההרצה תיחסם.

.. warning::

   ``CODE_EXEC_ALLOW_FALLBACK=true`` מאפשר fallback להרצה ב‑subprocess (ללא Docker).
   זה עשוי להיות שימושי לפיתוח, אבל מוריד משמעותית את רמת הבידוד ולכן **לא מומלץ בפרודקשן**.

.. important::

   **Delta תפעולי (נוכחי/זמני):** בזמן כתיבת שורות אלו, בפרודקשן הופעל זמנית
   ``CODE_EXEC_ALLOW_FALLBACK=true`` כדי שהפיצ׳ר יעבוד גם בלי Docker.
   זה פתרון זמני בלבד ומומלץ לחזור ל‑Fail‑Closed בהקדם.

תפעול מומלץ בפרודקשן (Runner נפרד)
----------------------------------
הפתרון הבטוח והמומלץ הוא להריץ את ה‑Docker sandbox בשירות Runner ייעודי שבו Docker זמין,
וה‑WebApp עושה אליו קריאה (כמו שמוסבר במדריך המימוש).

ראו גם:
- :doc:`/environment-variables`
- ``GUIDES/WEB_APP_CODE_EXECUTION_GUIDE.md`` (בריפו)

Troubleshooting
---------------

"אין כפתור Run"
^^^^^^^^^^^^^^^
בדרך כלל זה אחד מהבאים:

- ``FEATURE_CODE_EXECUTION=false`` ⇒ ה‑UI מסתיר את הכפתור.
- המשתמש **לא** Premium/Admin ⇒ ``/api/code/run/limits`` יחזיר ``403`` והכפתור יוסתר.
- בעיית רשת/שגיאת שרת ⇒ הקריאה ל‑limits נכשלת והכפתור יוסתר.

``enabled=false`` ב‑``/api/code/run/limits``
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
- המשמעות: הפיצ׳ר כבוי ברמת השרת. הפעילו ``FEATURE_CODE_EXECUTION=true``.

``docker_available=false`` ב‑``limits``
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
- המשמעות: Docker לא זמין בסביבה.
- אם ``fallback_allowed=false`` ⇒ זה מצב Fail‑Closed תקין (הרצה לא תתאפשר).
- אם חייבים לאפשר הרצה זמנית בלי Docker (לא מומלץ בפרודקשן) ⇒ ``CODE_EXEC_ALLOW_FALLBACK=true``.

Known Limitations
-----------------
- הפלט מוחזר **בסוף הריצה** (אין streaming בזמן אמת).
- יש מגבלות קשיחות על זמן/זיכרון/אורך קוד/גודל פלט.
- בסביבות שאין בהן Docker, במצב Fail‑Closed ההרצה לא תעבוד (בכוונה).

