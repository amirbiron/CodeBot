Google Drive Service
====================
:summary: שירות Google Drive: חיבור נפרד לבוט ולוובאפ (``owner``), אימות ב-Device Flow ובהפניה בדפדפן, ניהול טוקנים, יצירת ZIP והעלאה לתיקיות לפי קטגוריה. התאריך והגרסה נכנסים לשם קובץ ה-ZIP, לא למבנה התיקיות.

סקירה
-----
שירות גוגל דרייב אחראי לאימות (Device Flow), ניהול טוקנים, יצירת ZIP, והעלאה לתיקיות לפי קטגוריה.
אין קינון לפי תאריך: ``compute_subpath`` מחזיר את תווית הקטגוריה בלבד, ורק ב-``by_repo`` מתווספת תת-תיקייה
בשם הריפו. התאריך והגרסה נכנסים לשם קובץ ה-ZIP דרך ``compute_friendly_name``
(למשל ``BKP_zip_CodeBot_v7_26-08-2025.zip``).

.. _drive-owner:

חיבור נפרד לכל שירות (``owner``)
----------------------------------
לבוט ולוובאפ יש לכל אחד חיבור Drive משלו: טוקנים, העדפות (תזמון, תיקייה, גיבוי אחרון) ומתזמן. כל פונקציה בשירות שקוראת או כותבת את החיבור מקבלת ``owner`` כפרמטר חובה בלי ברירת מחדל, וכך גם שיטות ה-Drive של ``Repository``, ‏``DatabaseManager`` ו-``FilesFacade``. קורא ששכח את ``owner`` נכשל ב-``TypeError``, ו-``owner`` לא מוכר זורק ``ValueError``.

המיפוי משירות לשדות במסמך המשתמש נמצא במקום אחד, ``drive_owner.py``:

.. literalinclude:: ../../drive_owner.py
   :language: python
   :start-after: # docs:drive-owner-fields:start
   :end-before: # docs:drive-owner-fields:end
   :caption: drive_owner.py – _FIELDS

**למה.** כל שירות מתחבר עם OAuth client אחר — הבוט ב-Device Flow והוובאפ בהפניה בדפדפן — ו-refresh token עובד רק מול ה-client שהנפיק אותו (RFC 6749, סעיף 6). כשהשניים חלקו את אותם שדות, מי שהתחבר אחרון דרס את החיבור של השני, והשני נכשל בשקט בגיבוי הבא. גם הסורק של הוובאפ הריץ תזמונים שהבוט כתב.

- הבוט (``handlers/drive/menu.py``, ‏``bot_handlers.py``) עובד עם ``drive_owner.BOT``, על השדות ההיסטוריים.
- הוובאפ (``webapp/drive_auth.py``, ‏``webapp/drive_backup_api.py``, ‏``webapp/backup_scheduler.py``) והגיבוי האישי (``services/personal_backup_service.py``, שרץ רק בוובאפ) עובדים עם ``drive_owner.WEBAPP``.
- מטמון השירותים (``_SERVICE_CACHE``) שמור לפי ``(owner, user_id)``, ולכן שירות אחד לא מקבל אובייקט שנבנה מהטוקנים של השני. שירות מוחזר מהמטמון רק אם נבנה מהטוקנים שבמסד עכשיו (``_credentials_fingerprint``), כך שאחרי חיבור מחדש או רענון שנשמר נבנה שירות חדש.
- ``Repository.save_drive_prefs`` כותב רק את המפתחות שקיבל, כל אחד בנתיב משלו (``<field>.<key>``), בלי לקרוא קודם ולכתוב את כל ההעדפות חזרה — כך כתיבה אחת לא דורסת עדכון שנכתב במקביל, למשל תזמון שנקבע בזמן שגיבוי רץ. מפתח עם נקודה או ``$`` נדחה ב-``ValueError`` (``_drive_prefs_set_paths``).
- ניתוק בוובאפ מוחק את הטוקנים ומכבה את התזמון באותה כתיבה (``delete_drive_tokens`` עם ``prefs``), כך שכשל לא משאיר תזמון בלי חיבור.

``tests/test_drive_connection_separation.py`` בודק גם את המבנה: כל קריאה בריפו לפונקציה שדורשת ``owner`` מעבירה אותו, וכל שירות נוקב רק בשמות השדות שלו.

.. _drive-webapp-connect:

החיבור בוובאפ: קוד ה-state נשמר בשרת
---------------------------------------
הוובאפ מתחבר בהפניה לגוגל (``/api/drive/auth``), וגוגל מחזיר את הדפדפן ל-``/api/drive/callback``. קוד ה-state, שמוודא שהחזרה התחילה אצל אותו משתמש (RFC 6749, סעיף 10.12), נשמר במסמך המשתמש ולא ב-session: רק ה-hash שלו, לשימוש אחד, ועם תוקף.

.. literalinclude:: ../../webapp/drive_auth.py
   :language: python
   :start-after: # docs:drive-oauth-state:start
   :end-before: # docs:drive-oauth-state:end
   :caption: webapp/drive_auth.py – השדה והתוקף של ה-state

בחזרה מגוגל הבדיקה והמחיקה הן פעולה אחת (``find_one_and_update`` עם ``$unset``), ולכן כל state עובד פעם אחת בלבד, גם כששתי חזרות מגיעות יחד. ה-state נבדק מול המשתמש שב-session, ולכן state של משתמש אחד לא מחבר משתמש אחר.

**למה לא ב-session.** ה-session של הוובאפ הוא cookie, וב-session קבוע Flask שולח אותו מחדש בכל תשובה (Flask 3.1.2, ``SessionInterface.should_set_cookie``). כשה-state נשמר שם, בקשה שיצאה ברקע ברגע הלחיצה על "חבר" — שמירת מצב העבודה ב-``beforeunload`` ב-``base.html`` — החזירה את ה-cookie שלפני הלחיצה אחרי ההפניה לגוגל. הדפדפן שמר את ה-cookie שהגיע אחרון, ה-state נמחק, והחזרה מגוגל נדחתה בלי שורה בלוג.

כל דחייה בחזרה מגוגל נרשמת באירוע ``webapp_drive_callback_rejected`` עם הסיבה — ראו :ref:`drive-events`.

הערות OAuth
------------
- שימור refresh_token: בשמירה מתמזג עם הטוקנים הקיימים של אותו שירות (``owner``), כדי לא למחוק refresh token שלא הוחזר ברענון.
- רענון טוקן: ניסיון רענון עם טיפול כשלים שקט.
- **מלכודת: רענון שנכשל אינו** ``HttpError``. כשה-API עונה 401, ‏``google_auth_httplib2.AuthorizedHttp`` מרענן את הטוקן בעצמו, ואם הרענון נכשל (למשל ``invalid_grant`` — refresh token שבוטל, שפג או שהונפק ל-client אחר, RFC 6749 סעיף 5.2) נזרקת ``google.auth.exceptions.RefreshError`` (google-auth-httplib2 0.4.4, ``AuthorizedHttp.request``). בפונקציות ההעלאה הענף של 401 (``_is_auth_http_error`` ← ``_force_refresh_credentials``) נמצא תחת ``except HttpError``, ולכן הוא לא רץ על כשל כזה: החריגה נתפסת ב-``except Exception`` הכללי כתקלת רשת, וההעלאה מחזירה ``None``. בלוג נרשמת שורת ``drive_call_failed`` עם ``error_type=RefreshError``, אבל למשתמש אין סימן שצריך להתחבר מחדש. קוד שמטפל בכשלי אימות של Drive צריך לתפוס גם את ``RefreshError``.

כשלים שמוחזרים כ-``None``
--------------------------
``upload_bytes`` ו-``upload_file`` מחזירים ``None`` כשההעלאה נכשלת, והקורא בודק את הערך. כל ``return None`` בהן נרשם בשורת לוג אחת, ``drive_call_failed`` (``_log_drive_call_failed``): הפעולה שנכשלה (``op``, למשל ``upload_bytes.chunk``), השירות, המשתמש, סוג החריגה, סטטוס ה-HTTP וקוד השגיאה של Drive (``drive_reason``, למשל ``storageQuotaExceeded``). גם ``ensure_folder``, ובניית השירות ב-``get_drive_service``, רושמים כך חריגה שהם בולעים. כשהעלאה נכשלת כי אין שירות או אין תיקייה (``upload_bytes.no_service``, ‏``upload_bytes.no_folder``), הסיבה שמאחוריה נמצאת בשורה של השלב שנכשל: טוקנים חסרים או רענון שנכשל (השורות של ``_ensure_valid_credentials``), בניית השירות, או ``ensure_folder``. הטקסט של החריגה לא נרשם: ב-``HttpError`` הוא כתובת הבקשה והודעת השגיאה של גוגל כמו שהיא, וקוד שגיאה שאינו מילה אחת נרשם כ-``unrecognized``.

מבני קבצים
-----------
- שמות קבצים: BKP_{label}_{entity}_v{n}_{date}.zip
- נתיב משנה: ``{קטגוריה}`` בלבד, ובקטגוריית ``by_repo`` גם ``{קטגוריה}/{שם הריפו}``.
  אין קינון לפי תאריך — התאריך והגרסה נמצאים בשם הקובץ.

API (autodoc)
-------------
.. automodule:: services.google_drive_service
   :members:
   :undoc-members:
   :show-inheritance:
   :noindex:

