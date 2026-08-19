זרימת שיתוף ב-Gist (Gist Flow)
================================

סקירה כללית
------------

שיתוף ב-GitHub Gist יוצר את ה-Gist **תחת החשבון האישי של המשתמש**, לא תחת חשבון המערכת. זו לא החלטה קוסמטית: Gist שנוצר בטוקן המערכת מופיע ברשימת ה-Gists של המערכת, מיוחס אליה, והמשתמש לא יכול לערוך או למחוק אותו. לכן ``GITHUB_TOKEN`` (משתנה הסביבה) אינו משמש ליצירת Gist באף מסלול — גם לא כמסלול נפילה בכשל.

המשמעות המעשית: משתמש שלא חיבר חשבון GitHub **לא יכול** לשתף ב-Gist, ומקבל הנחיה לחבר או להשתמש ב-Pastebin.

נקודות כניסה
-------------

ארבעה מסלולים מגיעים לאותה פונקציה, ``integrations.resolve_gist_for_user``:

.. list-table:: מסלולי הכניסה
   :header-rows: 1
   :widths: 35 30 35

   * - פונקציה
     - מודול
     - הקשר
   * - ``share_single_by_id``
     - ``conversation_handlers``
     - שיתוף קובץ בודד מתוך שיחה
   * - ``_share_to_gist``
     - ``bot_handlers``
     - כפתור ``🔗 שתף קוד`` על קובץ
   * - ``_share_to_gist_multi``
     - ``bot_handlers``
     - שיתוף מרובה קבצים
   * - ``_export_gist``
     - ``refactor_handlers``
     - ייצוא תוצאת ריפקטורינג

כל ארבעתם קוראים דרך ``asyncio.to_thread``. הקריאה חוסמת — היא נוגעת ב-MongoDB וברשת — ומתוך handler אסינכרוני היא הייתה תוקעת את ה-event loop לכל המשתמשים, לא רק למי שלחץ.

זרימת עבודה בסיסית
-------------------

.. mermaid::

   sequenceDiagram
       participant U as User
       participant H as Handler
       participant R as resolve_gist_for_user
       participant DB as MongoDB
       participant I as GitHubGistIntegration
       participant GH as GitHub API

       U->>H: 🔗 שתף קוד ← 🐙 GitHub Gist
       H->>R: asyncio.to_thread(resolve_gist_for_user, user_id)
       R->>DB: get_github_token(user_id)
       DB->>R: טוקן מפוענח או None

       alt אין טוקן
         R->>H: (None, GIST_NEEDS_GITHUB_MESSAGE)
         H->>U: "כדי לשתף ב-Gist צריך לחבר GitHub"
       else יש טוקן
         R->>I: GitHubGistIntegration(token=token)
         I->>GH: GET /user (דרך גישה ל-login)
         alt הטוקן נדחה
           GH->>I: 401 / 403 / 404
           I->>I: auth_failed = True
           R->>H: (None, GIST_NEEDS_GITHUB_MESSAGE)
           H->>U: "חבר מחדש"
         else תקלה זמנית
           GH->>I: 5xx / הגבלת קצב
           I->>I: auth_failed = False
           R->>H: (None, GIST_TEMPORARY_FAILURE_MESSAGE)
           H->>U: "נסה שוב בעוד רגע"
         else הצלחה
           GH->>I: 200
           R->>H: (integration, None)
           H->>I: asyncio.to_thread(create_gist, ...)
           I->>GH: POST /gists
           alt נוצר
             GH->>I: Gist
             I->>H: dict עם url
             H->>U: הקישור ל-Gist
           else נכשל
             I->>H: None
             H->>U: "השיתוף נכשל"
           end
         end
       end

אימות הטוקן — למה יש שורה שנראית מיותרת
-----------------------------------------

בבנאי של ``GitHubGistIntegration`` יש שורה שנראית כמו קוד מת:

.. code-block:: python

   user = self.github.get_user()
   _ = user.login
   self.user = user

היא לא מיותרת, והיא **חייבת** להישאר. ``Github.get_user()`` ללא ארגומנט מחזיר ``AuthenticatedUser`` עם ``completed=False`` — אובייקט עצל שלא שלח שום בקשה. ה-``GET /user`` יוצא רק בגישה הראשונה לשדה, דרך ``_completeIfNotSet``. בלי הגישה ל-``login``, טוקן שנשלל היה "מתחבר" בהצלחה, ``is_available()`` היה מחזיר אמת, וכל סיווג הכשלים למטה לא היה רץ לעולם. הכשל היה מתגלה רק בניסיון ליצור את ה-Gist, עם הודעה שלא מצביעה על המקור.

הערך עצמו לא נרשם ללוג: ``login`` הוא מזהה אישי. השורה הזו כבר נמחקה פעם אחת בתיקון PII, וזה הפיל את האימות — ראה ``bugbot-rules/side-effect-riding-on-log-line.md`` בריפו ``amir-bug-patterns``.

שלושת מצבי ``auth_failed``
---------------------------

``auth_failed`` הוא **לא** בוליאני. שלושת הערכים מבחינים בין שני סוגי כשל שמחייבים הודעות שונות:

.. list-table:: מצבי auth_failed
   :header-rows: 1
   :widths: 15 35 50

   * - ערך
     - משמעות
     - מה המשתמש רואה
   * - ``None``
     - לא ניסינו, או שההתחברות הצליחה
     - הזרימה ממשיכה
   * - ``True``
     - הטוקן עצמו פסול
     - ``GIST_NEEDS_GITHUB_MESSAGE`` — חבר מחדש
   * - ``False``
     - הכשל זמני; הטוקן תקין
     - ``GIST_TEMPORARY_FAILURE_MESSAGE`` — נסה שוב

הסיווג נעשה ב-``_is_auth_failure``, והוא נשען על תת-המחלקות של PyGithub ולא על קוד הסטטוס:

.. code-block:: python

   if isinstance(error, RateLimitExceededException):
       return False              # הטוקן תקין, המכסה נגמרה
   if isinstance(error, (BadCredentialsException, TwoFactorException)):
       return True
   return getattr(error, "status", None) in {401, 403, 404}

**למה לא לפי קוד סטטוס בלבד:** 403 הוא גם הגבלת קצב וגם הרשאה חסרה. טוקן fine-grained בלי הרשאת ``gist`` מחזיר 403 אמיתי שדורש חיבור מחדש, בעוד שמכסה שנגמרה מחזירה 403 שדורש רק המתנה. PyGithub כבר מבחין ביניהם ב-``Requester.createException``, ולכן נשענים על הסיווג שלו. לשלוח משתמש לחבר מחדש חשבון תקין, בגלל מכסה שתתאפס בעוד רבע שעה, זו הודעה שגורמת נזק.

למה שתי הודעות ולא אחת
------------------------

זו ההבחנה המרכזית בזרימה הזו. "לא חיברת GitHub" ו"GitHub לא זמין כרגע" נראים דומים בקוד ומובילים לפעולה הפוכה אצל המשתמש: הראשון דורש ממנו ללכת לתפריט ולחבר חשבון, השני דורש ממנו לא לעשות כלום ולנסות שוב. הודעה אחת גנרית הייתה שולחת משתמש מחובר לחבר חשבון שכבר מחובר — ואם הוא "יתקן" את זה, הוא עלול לנתק ולחבר מחדש בלי סיבה.

Fail-closed
------------

בכל מסלול כשל התוצאה זהה: **לא נוצר Gist**, ואין נפילה לטוקן המערכת. זה מכוון. ה-``except Exception`` סביב טעינת הטוקן רחב במכוון — כל כשל שכן נזרק מסתיים באי-יצירת Gist ולא בשיתוף תחת חשבון המערכת. ה-``logger.exception`` שם הוא מה שמונע בליעה שקטה: ה-traceback מגיע ל-Sentry גם כשהמשתמש רואה רק "נסה שוב".

Edge Cases
----------

**``user_id`` ריק או אפס**
   יציאה מוקדמת עם ``GIST_NEEDS_GITHUB_MESSAGE``, בלי פנייה ל-DB.

**``create_gist`` מחזירה ``None``**
   הפונקציה בולעת חריגות ומחזירה ``None`` בכשל — היא לא זורקת. לכן ``try/except`` סביבה לא מספיק, ו-``if not result:`` הוא הבדיקה היחידה שמונעת דיווח ✅ על Gist שלא נוצר. זה דפוס K11.

**כשל בטעינת הטוקן מ-MongoDB**
   ``get_github_token`` ב-``database/repository.py`` תופסת את החריגה בעצמה, רושמת ``db_get_github_token_error`` ומחזירה ``None``. כלומר תקלת DB אינה מגיעה כחריגה ל-``resolve_gist_for_user``, אלא נראית שם כמו "אין טוקן" — והמשתמש מקבל את הודעת החיבור ולא את הודעת התקלה הזמנית. ה-fail-closed נשמר, אבל ההבחנה בין שתי ההודעות מתבטלת במסלול הזה.

**הטוקן מוצפן ב-DB**
   ``get_github_token`` מפענחת דרך ``secret_manager.decrypt_secret``. אם הפענוח נכשל היא מחזירה את הערך המאוחסן כפי שהוא, וההתחברות ל-GitHub תיכשל עם 401 — כלומר תסווג כטוקן פסול.

קישורים
--------

- :doc:`/user/share_code`
- :doc:`/api/integrations`
- :doc:`/api/conversation_handlers`
- :doc:`/security`
