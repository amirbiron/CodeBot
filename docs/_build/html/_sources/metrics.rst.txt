מדדים (Metrics)
================

נקודת קצה
---------
נקודת הקצה ל-Prometheus: ``/metrics``

מטריקות קיימות
--------------
- Counters: ``errors_total{code}``, ``telegram_updates_total{type,status}``
- Histograms: ``operation_latency_seconds{operation}``
- Gauges: ``active_indexes``

דוגמאות PromQL
---------------
.. code-block:: text

   # שיעור שגיאות
   rate(errors_total[5m])

   # P95 לזמן פעולה
   histogram_quantile(0.95, rate(operation_latency_seconds_bucket[5m]))
