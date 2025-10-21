Rate Limiting
=============

Environment variables
---------------------

- ``RATE_LIMIT_ENABLED``: Enable rate limiting globally (default: ``true``)
- ``RATE_LIMIT_SHADOW_MODE``: Count-only mode, no blocking (default: ``false``). Recommended to start with ``true`` in staging.
- ``RATE_LIMIT_STRATEGY``: ``moving-window`` or ``fixed-window`` (default: ``moving-window``)
- ``REDIS_URL``: Redis connection string. Use ``rediss://`` with TLS in production.
- ``ADMIN_USER_IDS``: Comma-separated Telegram user IDs that bypass some limits.

Flask
-----

- Uses Flask-Limiter with ``storage_uri`` pointing to ``REDIS_URL`` when set, otherwise in-memory fallback.
- 429 handler returns JSON with ``error``, ``message``, and ``retry_after`` fields.
- Health and metrics endpoints are exempt from limiting.

Telegram Bot
------------

- Keeps the existing lightweight in-memory limiter for a fast gate.
- If ``limits`` + Redis are available and ``REDIS_URL`` is set, a per-user global limiter runs in shadow mode for visibility.

Metrics
-------

- ``rate_limit_hits_total{source,scope,limit,result}``
- ``rate_limit_blocked_total{source,scope,limit}``

Security
--------

- Always use ``rediss://`` in production (Render Redis supports TLS).
- Keep ``ADMIN_USER_IDS`` minimal.

Config via Pydantic Settings
============================

הפרויקט משתמש ב-``pydantic-settings`` לטעינת קונפיגורציה בצורה עקבית בכל השכבות (בוט/ווב/שירותים).

היררכיית טעינה
---------------

- שרשור קבצים/ENV לפי הסדר: ``.env.local`` → ``.env`` → משתני סביבה
- טיפוסים מאומתים אוטומטית בזמן טעינה (Validation)

דוגמה (מצומצם) מתוך ``config.py``::

   class BotConfig(BaseSettings):
       BOT_TOKEN: str
       MONGODB_URL: str
       REDIS_URL: str | None = None
       RATE_LIMIT_ENABLED: bool = True
       RATE_LIMIT_SHADOW_MODE: bool = False

   def load_config() -> BotConfig:
       return BotConfig()

ולידציות
---------

- ``MONGODB_URL`` חייב להתחיל ב-``mongodb://`` או ``mongodb+srv://`` – אחרת תיזרק שגיאת ולידציה.

.env.example
------------

מומלץ לעדכן קובץ דוגמה ``.env.example`` עם השדות העיקריים (ללא סודות):

::

   BOT_TOKEN=changeme
   MONGODB_URL=mongodb://localhost:27017/codebot
   REDIS_URL=
   RATE_LIMIT_ENABLED=true
   RATE_LIMIT_SHADOW_MODE=true
   ADMIN_USER_IDS=

שימוש לסוכנים
-------------

- סוכן AI צריך להסתמך על API אחיד של ``config`` כדי למנוע פערים בין שכבות.
- אין להטמיע סודות בקוד; שימוש ב-ENV בלבד.
