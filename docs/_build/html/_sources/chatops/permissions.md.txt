# הרשאות ו-Rate Limit

- פקודות רגישות (מנהלים בלבד): `/errors`, `/triage`, `/rate_limit`, `/enable_backoff`, `/disable_backoff`.
- בעת Rate Limit: העדיפו פקודות ריכוזיות (`/status`) ודללו תדירות בדיקות.
- הגדרת אדמינים ב-ENV: `ADMIN_USER_IDS="123,456"`
- הגבלת צ'אטים: `ALLOWED_CHAT_IDS="-100123,-100456"`
- קירור לפקודות רגישות: `SENSITIVE_COMMAND_COOLDOWN_SEC` (ברירת מחדל: 5 שניות)
