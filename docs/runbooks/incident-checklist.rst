Incident Checklist (On‑Call)
============================

בעת פתיחת Incident
-------------------
1. בדקו את קטגוריית השגיאה (``error_category``) ב‑Logs/ChatOps/Sentry.
2. פעלו לפי ה‑``policy`` המצורפת לקטגוריה:
   - ``retry``: בדקו מדיניות retry בפועל וגבולות circuit‑breaker.
   - ``notify``: עדכנו ערוצים רלוונטיים (טלגרם/Slack) והצמידו request_id.
   - ``escalate``: הסלימו לבעל התפקיד/צוות יעד, כולל הקשר (service, endpoint, recent changes).
3. קבעו חלון זמן לתצפית (5/30/120 דקות) ובדקו מגמות (Top Signatures).
4. אספו ``request_id`` וריצו ``/triage <request_id>`` לקבלת קישורי Grafana/Sentry.
5. אם יש 429 משירות חיצוני – שקלו הגדלת ``CIRCUIT_BREAKER_RECOVERY_SECONDS`` זמנית.

קישורים
-------
- :doc:`/observability/log_based_alerts`
- :doc:`/chatops/commands`
- :doc:`/resilience`
