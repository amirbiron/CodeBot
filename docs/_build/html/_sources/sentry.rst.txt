Sentry
======

הפעלה (משתני סביבה)
--------------------
- ``SENTRY_DSN= https://xxx@o1234.ingest.sentry.io/5678``
- ``SENTRY_TRACES_SAMPLE_RATE=0.1`` (אופציונלי)
- ``SENTRY_PROFILES_SAMPLE_RATE=0.1`` (אופציונלי)

עקרונות
--------
- Redaction מופעל אוטומטית.
- חברו ``error_code`` לקיבוץ חכם של שגיאות.
