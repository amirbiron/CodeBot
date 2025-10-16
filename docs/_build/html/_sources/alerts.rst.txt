התראות (Alerts)
================

חוקי התראה לדוגמה
------------------
.. code-block:: yaml

   groups:
     - name: codebot_alerts
       rules:
         - alert: HighErrorRate
           expr: rate(errors_total[5m]) > 0.05
           for: 5m
           annotations:
             summary: "שיעור שגיאות גבוה: {{ $value }}"
         - alert: SlowOperations
           expr: histogram_quantile(0.95, rate(operation_latency_seconds_bucket[5m])) > 2
           for: 10m
           annotations:
             summary: "פעולות איטיות: 95p > 2s"
