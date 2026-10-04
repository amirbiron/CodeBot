Branch Protection & PR Rules
============================
:summary: לרכז נהלים ברורים להגנה על ענפים (Branch Protection) ולחוקי PR בפרויקט.

כללי ענפים
-----------
- שמות ענפים: ``feat/...``, ``fix/...``, ``chore/...``, ``docs/...``, ``refactor/...``
- אין ``push`` ישיר ל‑``main``; כל שינוי דרך PR בלבד
- דרישת בדיקות ירוקות לפני Merge

חוקי PR
--------
- Conventional Commits בהודעות קומיט
- תיאור PR בפורמט What/Why/Tests + Rollback
- לצרף קישור ל‑Docs Preview אם רלוונטי
- תוויות: ``type:docs`` לשינויי תיעוד בלבד, ``type:feat`` לפיצ׳רים

CI – Required Checks
--------------------
- אילו סטטוסים ה-PR חייב לעבור, ומתי סטטוס חדש מתחיל לחסום מיזוג — ב-:doc:`ci-cd`. העמוד הזה מפנה לשם במקום להחזיק עותק של הרשימה.

קישורים
-------
- :doc:`contributing`
- :doc:`ci-cd`
- :doc:`integrations`
