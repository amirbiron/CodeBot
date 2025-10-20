# On-call Rotation (Alertmanager)

מסמך קצר לתצורת תורנות ותהליכי התראה.

## בעלי תפקידים
- Primary: צוות פיתוח A (משמרת שבועית)
- Secondary: צוות פיתוח B
- Channel: Slack `#codebot-alerts` + Telegram (ALERT_TELEGRAM_CHAT_ID)

## חלונות זמן
- ימים א׳–ה׳: 08:00–22:00 — Primary
- לילות/סופ"ש: Secondary (on best effort), תיעוד post-mortem נדרש ביום העבודה הבא

## ניתוב Alertmanager (דוגמה)

- route: ברירת מחדל → Slack + Telegram
- סיווג לפי labels:
  - severity=critical → תיוג @here + escalation ל-Secondary אם לא אושר תוך 10 דק׳
  - severity=warning → Slack בלבד, ללא pager

## Playbook קצר
- קבלתם התראה? אשרו ב-Slack/Telegram (ack) והוסיפו תגובה קצרה.
- בדקו Grafana: דשבורד CodeBot Overview.
- אספו request_id/trace_id מהרשומות הרלוונטיות.
- אם נדרש rollback: תעדו בתיעוד PR והוסיפו קישור ל-git revert/rollback plan.
- לאחר הסגירה: הוסיפו Post-Mortem קצר (5 bullets) ל-`docs/incidents/`.
