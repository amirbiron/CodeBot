Rate Limiting
=============

מבוא
----
מערכת הגבלת קצב אחודה לבוט ולווב, עם Shadow Mode, Soft‑Warning ב‑80% ועקיפת מנהלים.

Shadow Mode
-----------
- ``RATE_LIMIT_SHADOW_MODE=true``: סופר חריגות לימיט אך לא חוסם.
- שימוש: התחילו בפריסה מדורגת ב‑staging; עקבו במטריקות.

Soft‑Warning (80%)
------------------
- אזהרה ידידותית למשתמש כאשר ניצול מגיע ל‑80% מהסף.
- מונע ספאם: מוגבל להתראה אחת לדקה למשתמש.

Admin Bypass
------------
- ``ADMIN_USER_IDS``: מזהי טלגרם בעלי עקיפה חלקית של לימיטים.

Monitoring
----------
- ``rate_limit_hits_total{source,scope,limit,result}``
- ``rate_limit_blocked_total{source,scope,limit}``

Troubleshooting
---------------
- ודאו ``REDIS_URL`` עם TLS ב‑Prod (``rediss://``).
- ב‑Shadow Mode לא אמורה להיות חסימה – בדקו לוגים/מטריקות.

קישורים
-------
- :doc:`agents/rate-limiting`
- קוד: ``bot_rate_limiter.py``, ``metrics.py``
