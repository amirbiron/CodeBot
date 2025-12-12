Coverage Report (Runbooks / Quick Fixes)
========================================

מטרה
-----
עמוד ה-Coverage נועד להיות **Gap Analysis קבוע**: To‑Do List לצוות שמראה אילו ``alert_type`` נצפו במערכת **ועדיין חסר להם Runbook/Quick Fix**, ואילו הגדרות בקונפיג הפכו ליתומות.

בניגוד לדוחות "לפי חלון זמן", כאן ברירת המחדל היא **All‑time** — כדי שחוב תיעודי לא ייעלם רק כי ההתראה לא קפצה לאחרונה.

מקור האמת (Catalog / Registry)
------------------------------
בכל ``record_alert`` נשמרת/מתעדכנת רשומה ב-DB ב-collection ``alert_types_catalog`` (או לפי ``ALERT_TYPES_CATALOG_COLLECTION``):

- ``first_seen_dt`` — פעם ראשונה שההתראה נצפתה
- ``last_seen_dt`` — פעם אחרונה שההתראה נצפתה
- ``total_count`` — כמה פעמים ההתראה נצפתה (ב‑All‑time)

.. note::
   Drill alerts (``is_drill: true``) **לא נכנסים לקטלוג**, כדי לא לזהם את ה-To‑Do.

הגדרות כיסוי (Matching)
------------------------
Runbooks
~~~~~~~~
Runbook נחשב "קיים" עבור ``alert_type`` אם יש התאמה ל:

- Runbook key בקובץ ``config/observability_runbooks.yml``
- או אחד ה-``aliases`` של אותו Runbook

.. important::
   Runbook ברירת מחדל (``default``) **לא נחשב כיסוי**. אם אין Runbook ייעודי — ההתראה תופיע כ-Missing Runbook גם אם היא נופלת ל-default.

Quick Fixes
~~~~~~~~~~~
Quick Fix נחשב "קיים" עבור ``alert_type`` אם קיימת לפחות פעולה אחת **פר-התראה** באחד מהמקורות:

- ``action`` בתוך אחד ה-steps של ה-Runbook הייעודי
- או ``by_alert_type.<alert_type>`` בקובץ ``config/alert_quick_fixes.json``

.. note::
   כללים כלליים כמו ``by_severity`` או ``fallback`` אינם נחשבים כ-"כיסוי" פר-התראה עבור הרשימה Missing Quick Fixes.

מה מוצג בדוח
------------
- **Missing Runbooks**: כל ``alert_type`` מהקטלוג שאין לו Runbook ייעודי (key/alias), כולל **Last Seen** ו-**Count (All‑time)**.
- **Missing Quick Fixes**: ``alert_type`` שיש לו Runbook ייעודי, אבל אין לו פעולות פר-התראה.
- **Orphan Runbooks**: Runbooks/aliases בקונפיג שלא תואמים לשום ``alert_type`` בקטלוג (default מוחרג).
- **Orphan Quick Fixes**: מפתחות תחת ``by_alert_type`` בקונפיג שלא תואמים לשום ``alert_type`` בקטלוג.

API
---
``GET /api/observability/coverage`` (Admin only)

Query params:
- ``min_count``: מינימום הופעות בקטלוג (All‑time). ברירת מחדל: ``1``.

Response (תקציר):
- ``missing_runbooks`` / ``missing_quick_fixes``: כולל ``alert_type``, ``count``, ``last_seen_ts``, ``sample_title``
- ``orphan_runbooks`` / ``orphan_quick_fixes``
- ``meta.mode``: ``catalog``

