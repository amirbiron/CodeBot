שאילתות PromQL שימושיות
=========================

ראו גם :doc:`../metrics`.

זמן תגובה (Latency)
--------------------

.. code-block:: text

   # P95 לפי פעולה
   histogram_quantile(0.95, sum(rate(operation_latency_seconds_bucket[5m])) by (le, operation))

שיעור שגיאות
-------------

.. code-block:: text

   # שגיאות לפי קוד (5 דקות)
   sum(rate(errors_total[5m])) by (code)

אירועי ביזנס
-------------

.. code-block:: text

   # קצב file_saved לדקה
   rate(business_events_total{metric="file_saved"}[1m])
