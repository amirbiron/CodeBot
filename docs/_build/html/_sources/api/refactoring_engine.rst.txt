refactoring\_engine module
==========================

מדיניות וקונפיגורציה
---------------------

המנוע מיישם קיבוץ לפי קוהזיה כדי למנוע Oversplitting ולהימנע מ-God Class:

- קיבוץ לפי דומיין (``io``, ``helpers``, ``compute``) + תתי-קבוצות לפי prefix
- מיזוג קבוצות קטנות לפי תלות (Affinity)
- יעד מספר קבוצות: 3–5, עם סף מינימלי של 2 פונקציות בקבוצה
- בסנריו של קובץ קטן עם פונקציה אחת בלבד אבל עם כותרות/מחלקות בסקשנים שונים, המנוע יוצר קבוצות סקאפולדינג לפי הסקשן כדי לשמר לפחות שני מודולי דומיין וכך לאפשר מנגנון מיזוג מעגלי הייבוא

שדות קונפיגורציה זמינים במחלקה ``RefactoringEngine``:

.. code-block:: python

   class RefactoringEngine:
       preferred_min_groups: int = 3
       preferred_max_groups: int = 5
       absolute_max_groups: int = 8
       min_functions_per_group: int = 2

מקרה מיוחד: Safe Decomposition ל‑``models.py``
-----------------------------------------------

כאשר קובץ הקלט הוא ``models.py`` והוא כולל מחלקות בלבד (אין פונקציות טופ‑לבל), המנוע מבצע פיצול בטוח לתת‑מודולים דומייניים תחת ``models/``:

- סיווג מחלקות לדומיינים: ``core``, ``billing``, ``inventory`` (ולפי צורך ``network``/``workflows``), על בסיס יוריסטיקות שם/סקשן.
- יצירת קבצים: ``models/core.py``, ``models/billing.py``, ``models/inventory.py``.
- יצירת ``models/__init__.py`` עם re‑exports לשמירת תאימות (ייבוא מ‑``models`` ימשיך לעבוד).
- הזרקת יבוא בין‑מודולי למחלקות נדרשות (למשל: ``from .core import User`` בתוך ``billing.py``).
- Dry‑Run Tarjan SCC לזיהוי מעגליות בתוך ``models/`` בלבד ומיזוג נקודתי במקרה של מעגל.

ממשק פנימי רלוונטי:

- ``_split_models_monolith()`` – בונה את חבילת ``models/`` והקבצים הדומייניים.
- ``_inject_cross_module_class_imports()`` – הזרקת imports למחלקות בין מודולים פנימיים.
- ``_resolve_circular_imports()`` – DRY‑Run לזיהוי ומיזוג נקודתי של מעגליות בייבוא.

.. automodule:: refactoring_engine
   :members:
   :undoc-members:
   :show-inheritance:
