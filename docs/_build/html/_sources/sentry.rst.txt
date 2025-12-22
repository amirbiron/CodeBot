Sentry
======

הפעלה (משתני סביבה)
--------------------
- ``SENTRY_DSN= https://xxx@o1234.ingest.sentry.io/5678``
- ``SENTRY_TRACES_SAMPLE_RATE=0.1`` (אופציונלי)
- ``SENTRY_PROFILES_SAMPLE_RATE=0.1`` (אופציונלי)

התראות ל־Telegram וללוח Observability
-------------------------------------
ברירת מחדל: Sentry מציג Issues בממשק ושולח מיילים, אבל **לא** מזרים את זה אוטומטית למערכת ההתראות הפנימית שלנו (Telegram + Observability).

כדי לקבל התראות Sentry גם אצלנו יש שתי אפשרויות:

- Polling (מומלץ): הבוט מושך Issues אחרונים מ-API של Sentry וממיר אותם ל-``internal_alerts`` עם ``alert_type=sentry_issue``.
- Webhook (אופציונלי): שירות ה-Web שמריץ את ``services/webserver.py`` מקבל ``POST`` ל-``/webhooks/sentry`` וממיר את ה-payload ל-``internal_alerts``.

איפה להגדיר משתנים
~~~~~~~~~~~~~~~~~~
- Polling: **בבוט** (תהליך ``main.py``).
- Webhook: **בשירות ה-Web** שמאזין ל-``/webhooks/sentry``.

מה צריך כדי שזה יופיע בלוח Observability
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
- ``ALERTS_DB_ENABLED=true`` (וגם חיבור MongoDB תקין: ``MONGODB_URL`` + ``DATABASE_NAME``)
- ברגע שמגיע ``internal_alert`` מסוג ``sentry_issue`` הוא יישמר ב-``alerts_log`` ויופיע בלוח.

מה צריך כדי שזה יישלח לטלגרם
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
- ``ALERT_TELEGRAM_BOT_TOKEN`` + ``ALERT_TELEGRAM_CHAT_ID``
- ודאו ש-``ALERT_TELEGRAM_MIN_SEVERITY`` לא גבוה מדי (לרוב ``warning``/``error``).

Polling – משתנים רלוונטיים
~~~~~~~~~~~~~~~~~~~~~~~~~~
הפעלה בסיסית:

- ``SENTRY_AUTH_TOKEN`` + ``SENTRY_ORG`` (ואופציונלי ``SENTRY_PROJECT`` לסינון)
- ``SENTRY_POLL_ENABLED=true``

שליטה על התזמון/רעש:

- ``SENTRY_POLL_INTERVAL_SECS``: כל כמה שניות לעשות Poll
- ``SENTRY_POLL_FIRST_SECS``: דיליי לפני הריצה הראשונה אחרי עלייה
- ``SENTRY_POLL_DEDUP_SECONDS``: חלון דה-דופליקציה לכל Issue
- ``SENTRY_POLL_SEED_SILENT=true``: מומלץ כדי לא “להציף” על Issues קיימים בעת עלייה

Webhook – אבטחה ודה-דופליקציה
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
אם מגדירים ``SENTRY_WEBHOOK_SECRET`` השירות יאמת את הבקשה באחת מהדרכים:

- ``Authorization: Bearer <secret>``
- או פרמטר ``?token=<secret>``
- או חתימת HMAC (כותרות כמו ``X-Sentry-Hook-Signature``/``X-Sentry-Hook-Timestamp`` כאשר קיימות)

כדי לצמצם הצפה יש ``SENTRY_WEBHOOK_DEDUP_WINDOW_SECONDS`` (ברירת מחדל 300).

עקרונות
--------
- Redaction מופעל אוטומטית.
- חברו ``error_code`` לקיבוץ חכם של שגיאות.
