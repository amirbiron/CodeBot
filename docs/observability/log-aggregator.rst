מנוע ניתוח לוגים (Log Event Aggregator)
========================================

``monitoring/log_analyzer.py`` מרכז את כל האינטליגנציה שמטרתה להמיר זרם לוגים רועש להתראות פעולה. העמוד מפרט את רכיבי המערכת, הארכיטקטורה והקונפיגורציה שבין ``monitoring/log_analyzer.py``, ``monitoring/error_signatures.py`` ו-``scripts/run_log_aggregator.py``.

.. contents::
   :local:
   :depth: 2

ארכיטקטורה
-----------

1. **סינון רעשים** – השורה עוברת דרך ``noise_allowlist`` שמוגדר ב-``config/error_signatures.yml``. התאמה תעצור את העיבוד.
2. **התאמת חתימה** – ``ErrorSignatures.match()`` מחזיר קטגוריה, תקציר, מדיניות וסיווג על בסיס regex.
3. **Canonicalization + Fingerprint** – מנרמל מזהים דינמיים (UUID, timestamps, נתיבים) ומחשב fingerprint קצר (sha1/12).
4. **חלונות גלילה** – לכל fingerprint נשמר ``_Group`` עם מספר מופעים, דוגמאות אחרונות וטווח הזמנים.
5. **הפעלת מדיניות** – ``immediate_categories`` גורמות לאזעקה מיידית; אחרת נדרש min_count בתוך window_minutes.
6. **Cooldown** – לאחר התראה, אותו fingerprint לא ישלח שוב עד שיחלוף ``cooldown_minutes``.
7. **שליחה** – כברירת מחדל נשלח ל-``internal_alerts.emit_internal_alert``; במצב shadow (למשל בטסטים) נוצרת רק שורת לוג.

קונפיגורציה וקבצים
-------------------

- ``config/error_signatures.yml`` – מנהל קטגוריות (config/retryable/third_party/...) ורשימת חתימות בעלות ``pattern``. עדכון הקובץ משפיע ישירות על הדירוג והתיאור שנשלח למפעיל. מומלץ לקרוא את :ref:`קבצי קונפיגורציה ייעודיים <config-error-signatures>` ב-:doc:`configuration`.
- ``config/alerts.yml`` – קובע את חלונות הזמן, ספי הספירה וקטגוריות שחייבות לעבור גם בזמן cooldown. מודגם בפרק "alerts.yml" בעמוד הקונפיגורציה.
- ``config/alert_quick_fixes.json`` + ``config/alert_graph_sources.json`` – משמשים את ה-Observability Dashboard להצגת Quick Fixes וגרפים בהקשר של ההתראה שהופקה מהלוגים.

הרצת CLI מקומית
----------------

``scripts/run_log_aggregator.py`` מאפשר לצרף את המנוע ל-pipeline קיים (למשל tail של Docker). הוא טוען את אותם קבצים כמו הסרוויס הראשי ויכול לרענן חתימות אוטומטית.

.. code-block:: bash

   export ERROR_SIGNATURES_PATH="config/error_signatures.yml"
   export ALERTS_GROUPING_CONFIG="config/alerts.yml"
   LOG_AGG_ECHO=1 tail -F logs/app.log | python scripts/run_log_aggregator.py

דגלים חשובים:

- ``LOG_AGG_RELOAD_SECONDS`` – טעינה מחדש של חתימות/קונפיג בכל N שניות (ברירת מחדל 60).
- ``LOG_AGG_ECHO=1`` – מדפיס ל-stderr כל שורה שסווגה כדי לחקור false positives.
- ``ERROR_SIGNATURES_PATH`` / ``ALERTS_GROUPING_CONFIG`` – מצביעים על קובץ חלופי (למשל קובץ ניסוי ב-tmp).

שילוב במערכת
------------

- **Alert Storage** – התראות שמקורן בלוגים נשמרות יחד עם שאר ההתראות, ולכן מופיעות ב-Observability Dashboard, באינטגרציות Slack ובפקודות ChatOps כגון ``/triage``.
- **Quick Fixes** – כל התראה מקבלת רשימת פעולות מבוססת ``alert_quick_fixes.json`` (לדוגמה: ``/triage errors``, מעבר ל-Playbook).
- **Visual Context** – אם קיימת התאמה ל-``alert_graph_sources.json`` (לפי metric/category) יוצמד לגרף חיצוני מאושר.

עבודה בטוחה
-----------

- **שכפול לסביבות ניסוי** – לפני שינוי regex מהר, הריצו את כלי ה-CLI על snapshot לוגים היסטורי כדי לראות האם נוצרות התראות מיותרות.
- **בדיקות** – ``LogEventAggregator.snapshot()`` מאפשר לבדוק במבחנים האם fingerprint מסוים נאגר והאם הספירה התאפסה לאחר cooldown.
- **Shadow Mode** – בעת חיבור הסקריפט לסביבת production מומלץ להתחיל עם ``shadow=True`` (קוד מותאם אישית) כדי לוודא שאין הצפה בהתראות.

ניפוי תקלות נפוץ
----------------

- אין קבצי קונפיג? ודאו שהנתיבים יחסיים לשורש הפרויקט או שתעבירו נתיב מוחלט.
- התראות לא יוצאות? בדקו שהקטגוריה אינה ברשימת ``noise_allowlist`` וש-``min_count_default`` אינו גבוה מדי עבור השדה שנמדד.
- קלסיפיקציה שגויה? השתמשו ב-``LOG_AGG_ECHO`` כדי לגזור את ה-fingerprint ולהוסיף חתימה חדשה או להרחיב את ה-regex הקיים.
