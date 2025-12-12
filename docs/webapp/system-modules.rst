מודולים פנימיים ב-WebApp
=========================

הקבצים הבאים בתיקיית ``webapp/`` מנהלים תשתיות שאינן מכוסות במדריכים קודמים. העמוד מסביר את ה‑API, התלויות והסיבות לכל רכיב כדי שיהיה אפשר להרחיב או לדבג במהירות.

.. contents::
   :local:
   :depth: 2

``activity_tracker.py`` – דגימת פעילות משתמשים
----------------------------------------------

- פונקציה יחידה ``log_user_event(user_id, username=None)`` שנועדה לרשום פעילות מה-WebApp לאותם counters של הבוט.
- מבצעת דגימה הסתברותית ב־25% כדי לשמור על עקביות מול מנגנון הבוט ולא להעמיס על MongoDB.
- במידה והקריאה ל-``user_stats.log_user`` נכשלת (למשל כשהחתימה הישנה אינה תומכת ב-``weight``) הקוד נופל חזרה ל־API הישן ללא חריגות.
- שימוש מומלץ: קראו לה לאחר פעולה משמעותית (התחברות, פתיחת קובץ, ביצוע Bulk Action) במקום לנסות לעקוב אחר כל בקשה.

``community_library_api.py`` – REST עבור אוסף הקהילה
-----------------------------------------------------

- Blueprint בנתיב ``/api/community-library`` שמאפשר:

  - ``GET /api/community-library`` – חיפוש פריטי ספרייה (שדות ``q``, ``tags``, ``page``, ``per_page``). נשען על ``services.community_library_service.list_public`` והוגן עם ``cache_manager.dynamic_cache``.
  - ``GET /api/community-library/logo/<file_id>`` – פרוקסי מאובטח לקבצי לוגו המאוחסנים בטלגרם (ללא חשיפת ה-BOT_TOKEN לדפדפן).

- טיפול בשגיאות: מחזיר 500 עם ``{"ok": false, "error": "internal_error"}`` ומתעד את החריגה בלוג.
- קונפיגורציה: דורש ``BOT_TOKEN`` עבור פרוקסי הלוגו; מומלץ להגדיר ``BOT_TOKEN`` גם בסביבת staging כדי למנוע 404.

``community_library_ui.py`` – תצוגת Web
---------------------------------------

- Blueprint ``/community-library`` שמבצע בדיקת אדמין לפי ``ADMIN_USER_IDS`` כדי להחליט האם להציג כפתורי ניהול וייבוא מהירים.
- משתמש בתבנית ``community_library.html`` ומספק ל־Jinja את הדגל ``is_admin`` בלבד – שאר הנתונים נשלפים ב-JS דרך ה-API שתואר לעיל.
- נדרש סשן מאומת (ה-WebApp כבר מכניס ``user_id`` ל-session לאחר /start).

``snippet_library_api.py`` ו-``snippet_library_ui.py``
------------------------------------------------------

- **API**:

  - ``GET /api/snippets`` – חשיפה זהה לזו שמתועדת ב-:doc:`/webapp/snippet-library`, אך חשוב לזכור שהקוד ב-``snippet_library_api.py`` מטפל גם בסריאליזציה של תאריכים (``approved_at``) וב-caching.
  - ``GET /api/snippets/languages`` – סורק עד ~1000 פריטים כדי לבנות רשימת שפות ייחודית לצורך פילטרים בצד הלקוח.
  - ``POST /api/snippets/submit`` – מקבל הצעת סניפט חדשות מה-WebApp (דורש session מאומת) ומשגר התראה למנהלים דרך Telegram (``_notify_admins_new_snippet``).

- **UI**:

  - ``GET /snippets`` – מציג את הספרייה, עם ``is_admin`` כדי לאפשר כפתורי אדמין (מחיקה/עריכה) למורשים.
  - ``GET /snippets/submit`` ו-``/snippets/submit/thanks`` – טפסי הגשה ותודה.

- חיבורים נוספים: ``services.snippet_library_service`` מספק את שכבת ה-DB והאישורים; ``cache_manager.dynamic_cache`` מונע עומס על API הציבורי.

``push_api.py`` – Web Push Subscriptions
----------------------------------------

- Blueprint ``/api/push`` הכולל:

  - ``GET /api/push/public-key`` – החזרת מפתח VAPID ציבורי (או ריק אם לא הוגדר).
  - ``GET /api/push/diagnose`` – בדיקת קישוריות ללנדינגים הנפוצים (FCM, Mozilla). מסייעת להבין אם המארח חוסם תעבורת יוצא.
  - ``POST /api/push/subscribe`` / ``DELETE /api/push/subscribe`` – ניהול מנויי Web Push לפי ``user_id`` מה-session. דואג לאינדקסים על ``push_subscriptions`` ומוציא Telemetry.
  - ``POST /api/push/test`` – שליחת הודעת בדיקה למנויים הקיימים (משתמש נוכחי בלבד), כולל תמיכה ב־Worker חיצוני (``PUSH_REMOTE_DELIVERY_ENABLED``) או שליחה ישירה עם ``pywebpush``.

- תלות ב-ENV:

  - ``VAPID_PUBLIC_KEY`` / ``VAPID_PRIVATE_KEY`` / ``VAPID_SUB_EMAIL`` – לשליחה ישירה.
  - ``PUSH_REMOTE_DELIVERY_*`` – עבור תרחיש Worker חיצוני.
  - ``PUSH_DELIVERY_TTL_SECONDS``, ``PUSH_DELIVERY_URGENCY`` – שליטה על הודעות תזכורות.

- אבטחה: כל מסלולי המנויים מוגנים ב-``require_auth`` (session). נתוני המפתח הפרטי לא נחשפים לעולם אל הדפדפן.

``workspace_api.py`` – ניהול Kanban (Workspaces)
-------------------------------------------------

- Blueprint ``/workspace`` שמרחיב את ``webapp.collections_api``:

  - ``PATCH /workspace/items/<item_id>/state`` – מעדכן מצב פריט (``todo``, ``in_progress``, ``done``). השירות הממשי מגיע מ-``CollectionsManager``.
  - מחזיר קודי שגיאה מדויקים: 400 עבור ערכים חסרים/לא חוקיים, 404 אם הפריט לא קיים, 401 כשאין session, 500 בחריגות אחרות.
  - Telemetry: שולח אירועים ל-``observability.emit_event`` על הצלחות ושגיאות, כולל ``request_id`` מתוך ``collections_api``.

- שימוש מומלץ: כאשר מוסיפים כרטיס Kanban חדש או פעולה אוטומטית בסגנון "Complete reminder" – קראו ל-API הזה במקום לעדכן את ה-DB ישירות, כדי לשמור על אחידות לוגים וולידציות.

``config_radar.py`` – רנטגן קונפיגורציה
---------------------------------------

- פונקציה ``build_config_radar_snapshot()`` מאחדת את ``config/alerts.yml``, ``config/error_signatures.yml``, ``config/image_settings.yaml``, ``config/alert_quick_fixes.json`` ו-``config/observability_runbooks.yml``.
- חשופה דרך ``GET /api/config/radar`` (דורש אדמין) ומספקת:

  - סיכום ערכים לכל קובץ (כולל ``window_minutes``, ``default_theme`` וכו').
  - רשימת בעיות מאומתת (regex שגוי, ערך חסר, פורמט פסול).
  - מטא-דאטה מגיט (commit אחרון, מחבר, timestamp).

- התממשקות: מסך Config Radar ב-WebApp משתמש בנתונים כדי להתריע על חוסרים בקבצי קונפיגורציה עוד לפני שהם מגיעים לקוד.
- טיפים:

  - ניתן להצביע לקבצים חלופיים ע"י ENV (``ALERTS_GROUPING_CONFIG``, ``ERROR_SIGNATURES_PATH``, ``IMAGE_SETTINGS_PATH``).
  - במקרה שאין PyYAML מותקן, הקריאה נופלת חזרה ל-JSON ותחזיר issue שמסביר כיצד להתקין.

איך להשתמש בעמוד זה
-------------------

- **בדיקות מקומיות** – השתמשו בנתיבים המתועדים כדי לבצע curl/Postman לפני שפותחים PR (למשל ``curl -X PATCH /workspace/items/<id>/state``).
- **הרחבות** – כאשר מוסיפים פיצ'ר חדש ב-WebApp, החליטו האם הוא שייך לקטגוריה קיימת (קהילה, פוש, קונפיג) וציינו אותו בעמוד זה כדי לשמור על תיעוד מרוכז.
- **סוכני AI** – הפנו לכאן כדי להבין איך לנצל API פנימיים (לדוגמה להפעיל Push Test או לקרוא Config Radar) במקום לנחש מתוך הקוד.
