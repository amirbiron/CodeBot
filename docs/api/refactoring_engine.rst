refactoring\_engine module
==========================

מדיניות וקונפיגורציה
---------------------

המנוע מיישם קיבוץ לפי קוהזיה כדי למנוע Oversplitting ולהימנע מ-God Class:

- קיבוץ לפי דומיין (``io``, ``helpers``, ``compute``) + תתי-קבוצות לפי prefix
- מיזוג קבוצות קטנות לפי תלות (Affinity)
- יעד מספר קבוצות: 3–5, עם סף מינימלי של 2 פונקציות בקבוצה

שדות קונפיגורציה זמינים במחלקה ``RefactoringEngine``:

.. code-block:: python

   class RefactoringEngine:
       preferred_min_groups: int = 3
       preferred_max_groups: int = 5
       absolute_max_groups: int = 8
       min_functions_per_group: int = 2

.. automodule:: refactoring_engine
   :members:
   :undoc-members:
   :show-inheritance:
