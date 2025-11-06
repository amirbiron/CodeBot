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

מדדי CodeBot ייעודיים (Handlers/Commands/DB)
---------------------------------------------
מטריקות ברירת מחדל ל־Handlers (ווב), Commands (בוט טלגרם) ו־DB. שמות ולייבלים:

- ``codebot_handler_requests_total{handler,status,cache_hit}`` – Counter
- ``codebot_handler_latency_seconds_bucket{handler,status,cache_hit,le}`` – Histogram
- ``codebot_command_requests_total{command,status,cache_hit}`` – Counter
- ``codebot_command_latency_seconds_bucket{command,status,cache_hit,le}`` – Histogram
- ``codebot_db_requests_total{operation,status}`` – Counter
- ``codebot_db_latency_seconds_bucket{operation,status,le}`` – Histogram

הערות לייבלים:

- ``status``: ``2xx``/``3xx``/``4xx``/``5xx`` או ערך לוגי שהוזן ידנית (למשל ``cancelled``/``error``).
- ``cache_hit``: ``hit``/``miss``/``unknown`` (או ערכי ביניים כמו ``warm``/``cold`` אם סופקו).
- ``handler``/``command``/``operation``: שמות מנורמלים (ללא רווחים, עד 120 תווים).

דוגמאות PromQL:

.. code-block:: text

   # קצב בקשות לפי Handler (1m)
   sum by (handler) (rate(codebot_handler_requests_total[1m]))

   # P95 לזמן Handler (5m)
   histogram_quantile(0.95, sum by (handler, le) (rate(codebot_handler_latency_seconds_bucket[5m])))

   # קצב פקודות טלגרם לפי Command (5m)
   sum by (command) (rate(codebot_command_requests_total[5m]))

   # P95 לזמן פקודות (5m)
   histogram_quantile(0.95, sum by (command, le) (rate(codebot_command_latency_seconds_bucket[5m])))

   # קצב אופרטציות DB לפי operation (5m)
   sum by (operation) (rate(codebot_db_requests_total[5m]))

   # P95 לזמן DB (5m)
   histogram_quantile(0.95, sum by (operation, le) (rate(codebot_db_latency_seconds_bucket[5m])))

מטריקות OpenTelemetry (אם זמינות)
----------------------------------
בעת שימוש ב־`observability_instrumentation.@traced` נרשמות המטריקות הבאות:

- ``request.duration`` (Histogram) — משך פעולה בשניות
- ``errors.total`` (Counter) — ספירת שגיאות
- ``requests.active`` (UpDownCounter) — מספר בקשות פעילות

דוגמאות PromQL
---------------
.. code-block:: text

   # שיעור שגיאות
   rate(errors_total[5m])

   # P95 לזמן פעולה
   histogram_quantile(0.95, rate(operation_latency_seconds_bucket[5m]))

   # שיעור שגיאות לבקשות HTTP
   sum by (status) (rate(http_requests_total{job="webapp"}[5m]))

   # P90 למשכי פעולות ידניות דרך OTel
   histogram_quantile(0.90, sum by (le) (rate(request_duration_bucket{job="webapp"}[10m])))

Tracing ב-Grafana
------------------
- הוגדר datasource מסוג ``Jaeger`` תחת ``docker/grafana/provisioning/datasources/prometheus.yml`` (URL: ``http://jaeger:16686``).
- ניתן לחפש שירותים ``code-keeper-webapp``/``code-keeper-bot`` ולצלול ל-spans שנרשמים דרך ``@traced``.

SLO/SLI לדוגמה
---------------
- זמינות שירות API: 99.9% חודשית
- זמן תגובה P95 לחיפוש: ≤ 1.5s
- שיעור שגיאות חיפוש: ≤ 1%

התראות (Prometheus alerting rules)
----------------------------------
ניתן להוסיף כללים לקובץ הכללים של Prometheus:

.. code-block:: yaml

    groups:
    - name: codebot-webapp
      rules:
      - alert: HighErrorRate
        expr: sum(rate(errors_total[5m])) / sum(rate(http_requests_total[5m])) > 0.05
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "שיעור שגיאות גבוה"
          description: ">5% שגיאות ב־10 הדקות האחרונות"

      - alert: SlowSearchP95
        expr: histogram_quantile(0.95, rate(search_duration_seconds_bucket[5m])) > 1.5
        for: 15m
        labels:
          severity: warning
        annotations:
          summary: "חיפוש איטי (P95)"
          description: "P95 לזמן חיפוש גבוה מ־1.5s"
