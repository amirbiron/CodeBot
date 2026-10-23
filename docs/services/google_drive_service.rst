:summary: שירות Google Drive: חיבור נפרד לבוט ולוובאפ (``owner``), אימות ב-Device Flow ובהפניה בדפדפן, ניהול טוקנים, יצירת ZIP והעלאה לתיקיות לפי קטגוריה. התאריך והגרסה נכנסים לשם קובץ ה-ZIP, לא למבנה התיקיות.

Google Drive Service
====================

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
- מטמון השירותים (``_SERVICE_CACHE``) שמור לפי ``(owner, user_id)``, ולכן שירות אחד לא מקבל אובייקט שנבנה מהטוקנים של השני. שירות מוחזר מהמטמון רק אם הוא עונה על הטוקנים שבמסד עכשיו (``_credentials_fingerprint``), כך שאחרי חיבור מחדש או רענון שנשמר נבנה שירות חדש. אחרי רענון כפוי שלא נשמר, השירות של הטוקן המרוענן נשמר עם הטביעה של הטוקנים שעדיין במסד (``_force_refresh_credentials``).
- ``Repository.save_drive_prefs`` כותב רק את המפתחות שקיבל, כל אחד בנתיב משלו (``<field>.<key>``), בלי לקרוא קודם ולכתוב את כל ההעדפות חזרה — כך כתיבה אחת לא דורסת עדכון שנכתב במקביל, למשל תזמון שנקבע בזמן שגיבוי רץ. מפתח עם נקודה, או שמתחיל ב-``$``, נדחה ב-``ValueError`` (``_drive_prefs_set_paths``).
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

**למה לא ב-session.** ה-session של הוובאפ הוא cookie, וב-session קבוע Flask שולח אותו מחדש בכל תשובה (Flask 3.1.2, ``SessionInterface.should_set_cookie``). כשה-state נשמר שם, בקשה שיצאה ברקע ברגע הלחיצה על "חבר" — שמירת מצב העבודה ב-``beforeunload`` ב-``base.html`` — החזירה את ה-cookie שלפני הלחיצה אחרי ההפניה לגוגל. הדפדפן שמר את ה-cookie שהגיע אחרון, ה-state נמחק, והחזרה מגוגל נדחתה בלי שורה בלוג. שמירת מצב העבודה הוסרה מאז מ-``base.html``, וההחלטה לשמור את ה-state בשרת נשארת: כל בקשה שתצא במקביל ללחיצה תחזיר את ה-cookie באותה צורה.

כל דחייה בחזרה מגוגל נרשמת באירוע ``webapp_drive_callback_rejected`` עם הסיבה — ראו :ref:`drive-events`.

.. _drive-privacy-page:

עמוד מדיניות הפרטיות (``/privacy``)
-------------------------------------
עמוד ציבורי באנגלית בוובאפ (``privacy_policy`` ב-``webapp/app.py``, התבנית ``webapp/templates/privacy.html``), שמתאר מה CodeKeeper עושה עם Google Drive. הכתובת שלו רשומה כקישור למדיניות הפרטיות בפרויקט ה-Google Cloud של חיבור ה-Drive. מדיניות הנתונים של גוגל דורשת את זה: *"You must list the privacy policy URL in your OAuth client configuration"* (`Google API Services User Data Policy <https://developers.google.com/terms/api-services-user-data-policy>`_). הקישור נקבע פעם אחת לפרויקט, ולכן העמוד מכסה גם את החיבור של הבוט. עמוד הבית ועמוד ההתחברות מקשרים אליו מהתחתית (``webapp/templates/_legal_footer.html``).

**מה אסור לשבור.** הנתיב רשום אצל גוגל, ולכן הוא לא משתנה. הוא חייב לענות בלי התחברות, כי גוגל ניגש אליו בלי סשן. הוא רשום ב-``webapp/app.py`` ולא ב-Blueprint: הרישום של ה-Blueprints עטוף ב-``except Exception: pass``, וכשל בייבוא היה מעלים את העמוד בשקט.

**כל משפט בעמוד הוא עובדה על הקוד.** אלה העובדות שהוא נשען עליהן, ומי מצמיד כל אחת (``tests/test_privacy_page.py``, אלא אם נכתב אחרת):

- **ה-scope.** העמוד נוקב ב-``drive.file`` ומסביר מה הוא מתיר. ``test_the_scope_the_page_names_is_the_one_both_connections_request`` משווה אותו לברירת המחדל בכל מקום בקוד שקובע את ה-scope, וקורא אותה מקוד המקור, כי חלק מהמקומות נקראים מ-``GOOGLE_OAUTH_SCOPES`` ב-ENV. ערך שהוגדר ב-ENV של הפרודקשן אינו נבדק שם. ב-17.10.2026 נבדק במסד של הפרודקשן ששני החיבורים השמורים קיבלו מגוגל רק ``drive.file``. הבדיקה נעשתה על השדה ``scope`` שנשמר עם הטוקנים, בלי לקרוא את הטוקנים עצמם.
- **אין הורדה מ-Drive.** העמוד אומר ש-CodeKeeper לא מוריד ולא קורא תוכן של קובץ ב-Drive. היום הקוד רק יוצר תיקיות ומעלה קבצים (``files().create``), וקורא מטא-דאטה של מה שהוא יצר (``files().list``, ‏``files().get``). ‏``test_no_code_downloads_file_content_from_drive`` נכשל על קוד שמוסיף הורדה, למשל ``get_media``.
- **ניתוק.** הניתוק מוחק את הטוקנים של אותו שירות. זה נבדק ב-``tests/test_drive_connection_separation.py`` וב-``tests/test_webapp_drive_auth_required.py``. בבוט התזמון נשאר בהעדפות, אבל בלי טוקנים ``get_drive_service`` מחזיר ``None`` ושום העלאה לא מתחילה. לכן העמוד אומר שהעלאות חדשות לא יתחילו, ו"מכבה את הגיבוי המתוזמן" נאמר רק על הוובאפ. הניתוק לא מבטל את ההרשאה אצל גוגל, כי אין בקוד קריאת revoke, והעמוד מפנה לדף ההרשאות של חשבון Google.
- **הצפנה.** העמוד לא אומר שהטוקנים מוצפנים. בלי ``TOKEN_ENC_KEY`` תקין, ``encrypt_secret`` (``secret_manager.py``) מחזיר ``None``, ו-``Repository.save_drive_tokens`` שומר אז את הטוקן כמו שהוא. המשתנה אינו חובה (:doc:`/environment-variables`). ‏``test_the_page_does_not_claim_encryption_while_tokens_can_be_saved_unencrypted`` נכשל אם העמוד יטען להצפנה כל עוד זה המצב. כשהשמירה תסרב לשמור בלי מפתח, הבדיקה הראשונה בטסט תיכשל, ואז אפשר להוסיף לעמוד את ההצהרה.
- **כתובת המייל.** אחרי החיבור הוובאפ מבקש מגוגל את כתובת החשבון, לתצוגה (``_fetch_google_email`` ב-``webapp/drive_auth.py``). עם ``drive.file`` בלבד גוגל עונה 401, כך שכתובת לא נשמרת. זה נמדד בשורת ``webapp_drive_userinfo_failed`` בלוג של Render, ב-17.10.2026. העמוד אומר רק שהאפליקציה לא מבקשת גישה לכתובת ולפרופיל, וזה נכון לפי ה-scope.

הערות OAuth
------------
- שימור refresh_token: בשמירה מתמזג עם הטוקנים הקיימים של אותו שירות (``owner``), כדי לא למחוק refresh token שלא הוחזר ברענון.
- רענון טוקן: בשני מסלולי הרענון (``_ensure_valid_credentials``, ‏``_force_refresh_credentials``) הטוקן שהתקבל נשמר דרך ``_save_refreshed_credentials``. שמירה שנכשלה נרשמת בשורת ``drive_refresh_not_saved``, והקריאה הנוכחית ממשיכה עם הטוקן החדש. אחרי 401, הניסיון החוזר מקבל מהמטמון את השירות של הטוקן המרוענן, ולכן גם כשהשמירה נכשלה הוא לא חוזר לטוקן שגוגל דחה.
- **מלכודת: רענון שנכשל אינו** ``HttpError``. כשה-API עונה 401, ‏``google_auth_httplib2.AuthorizedHttp`` מרענן את הטוקן בעצמו, ואם הרענון נכשל (למשל ``invalid_grant`` — refresh token שבוטל, שפג או שהונפק ל-client אחר, RFC 6749 סעיף 5.2) נזרקת ``google.auth.exceptions.RefreshError`` (google-auth-httplib2 0.4.4, ``AuthorizedHttp.request``). בפונקציות ההעלאה הענף של 401 (``_is_auth_http_error`` ← ``_force_refresh_credentials``) נמצא תחת ``except HttpError``, ולכן הוא לא רץ על כשל כזה: החריגה נתפסת ב-``except Exception`` הכללי כתקלת רשת, וההעלאה מחזירה ``None``. בלוג נרשמת שורת ``drive_call_failed`` עם ``error_type=RefreshError`` ועם קוד השגיאה של גוגל ב-``oauth_error``. קוד שמטפל בכשלי אימות של Drive צריך לתפוס גם את ``RefreshError`` — והגיבוי של הוובאפ לא מגיע לשם בכלל, כי הוא בודק את החיבור לפני העבודה (:ref:`drive-check-connection`).

.. _drive-check-connection:

בדיקת חיבור לפני גיבוי (``check_connection``)
-------------------------------------------------
``check_connection`` מחדש את הטוקן מול גוגל במפורש ומחזיר ``ConnectionCheck``: מצב אחד מ-``CONNECTION_*`` וקוד השגיאה של גוגל כשיש (``oauth_error``). הגיבוי של הוובאפ (``_perform_drive_backup`` ב-``webapp/backup_scheduler.py``) קורא לה **לפני** שהוא בונה את ה-ZIP, ולכן חיבור שמת עולה קריאה אחת לשרת הטוקנים ולא ייצוא מלא.

**למה צריך חידוש מפורש.** ``_credentials_from_tokens`` אינו מעביר ``expiry``, ובלי ``expiry`` הנכס ``expired`` מחזיר תמיד ``False`` (``google/auth/credentials.py``, google-auth 2.41.1). לכן ``_ensure_valid_credentials`` לא מחדש לעולם, ``get_drive_service`` בונה שירות גם מטוקנים שגוגל כבר דחה, והכשל מתגלה רק באמצע ההעלאה — כמתואר במלכודת שלמעלה.

הסיווג, ומה שהוא נשען עליו:

- ``CONNECTION_AUTH_REQUIRED`` — גוגל החזיר ``invalid_grant``: ה-refresh token *"invalid, expired, revoked"* (RFC 6749, סעיף 5.2), וניסיון חוזר עם אותו טוקן יחזיר אותה תשובה. גם חיבור שמור בלי refresh token נכנס לכאן. קוד השגיאה נקרא מגוף התשובה שבתוך ``RefreshError`` (``_refresh_error_code``; google-auth זורק ``RefreshError(error_details, response_data, retryable=...)``, ``google/oauth2/_client.py``).
- ``CONNECTION_TRANSIENT`` — ``TransportError`` (תקלת רשת), או ``RefreshError`` ש-google-auth סימן ``retryable``.
- ``CONNECTION_UNKNOWN`` — כל ``RefreshError`` אחר, למשל ``invalid_client`` (תקלת הגדרות, שחיבור מחדש לא יתקן), וגם אין טוקנים כלל: ``get_drive_tokens`` מחזיר ``None`` גם בלי חיבור וגם בכשל מסד, ותקלת מסד חולפת אסור שתבקש מהמשתמש להתחבר מחדש.

חריגה שאינה של google-auth עולה הלאה ולא מסווגת. בהצלחה הטוקן החדש נשמר (``_save_refreshed_credentials``), ו-``get_drive_service`` שאחרי הבדיקה בונה שירות מטוקן טרי. אבל השמירה יכולה להיכשל: ``save_tokens`` מחזיר ``False`` ולא זורק, והכשל רק נרשם בשורת ``drive_refresh_not_saved``. הבדיקה עדיין מחזירה ``CONNECTION_OK``, כי החיבור חי, ו-``get_drive_service`` טוען אז מהמסד את הטוקן שהיה שם לפני הבדיקה, ולא את הטוקן הטרי.

**מה הוובאפ עושה עם התשובה.** ב-``CONNECTION_AUTH_REQUIRED`` נכתב ``auth_required_at`` בהעדפות של הוובאפ, ו-``/api/drive/status`` מחזיר ``needs_reconnect`` — מסך ההגדרות מציג אז "החיבור ל-Google Drive פג" עם כפתור חיבור מחדש במקום "מחובר". בגיבוי מתוזמן גם ``schedule_next_at`` מתרוקן, והסורק מדלג על המשתמש (``_pause_drive_schedule``), במקום לנסות שוב בכל סריקה. ההשהיה כותבת את הסימון באותה כתיבה (או דורשת שהוא כבר שם), ולכן אין תזמון מושהה ש-``needs_reconnect`` שלו כבוי. חיבור מחדש (``/api/drive/callback``) מוחק את הסימון ומחזיר את התזמון לפעולה (``resume_drive_schedule_after_reconnect``), וגם בדיקה שעברה מוחקת אותו. האירועים: ``webapp_drive_backup_failed`` ב-:ref:`drive-events`.

כשלים שמוחזרים כ-``None``
--------------------------
``upload_bytes`` ו-``upload_file`` מחזירים ``None`` כשההעלאה נכשלת, והקורא בודק את הערך. כל ``return None`` בהן נרשם בשורת לוג אחת, ``drive_call_failed`` (``_log_drive_call_failed``): הפעולה שנכשלה (``op``, למשל ``upload_bytes.chunk``), השירות, המשתמש, סוג החריגה, סטטוס ה-HTTP, קוד השגיאה של Drive (``drive_reason``, למשל ``storageQuotaExceeded``) וקוד השגיאה של OAuth שבתוך ``RefreshError`` (``oauth_error``, למשל ``invalid_grant``; ``_refresh_error_code``). גם ``ensure_folder``, ובניית השירות ב-``get_drive_service``, רושמים כך חריגה שהם בולעים. כשהעלאה נכשלת כי אין שירות או אין תיקייה (``upload_bytes.no_service``, ‏``upload_bytes.no_folder``), הסיבה שמאחוריה נמצאת בשורה של השלב שנכשל: טוקנים חסרים או רענון שנכשל (השורות של ``_ensure_valid_credentials``), בניית השירות, או ``ensure_folder``. ``drive_reason`` הוא קוד בלבד — ``errors[0].reason`` או ``error.status``. כשאין קוד הוא ריק, והודעת השגיאה של גוגל (``error.message``) לא נרשמת גם אז (``_parse_http_error_status_reason`` עם ``include_message=False``). הטקסט של החריגה לא נרשם: ב-``HttpError`` הוא כתובת הבקשה והודעת השגיאה של גוגל כמו שהיא, וקוד שגיאה שאינו מילה אחת נרשם כ-``unrecognized``.

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

