class _Cfg:
    SENTRY_DSN = ""
    ENVIRONMENT = "test"
    RECYCLE_TTL_DAYS = 7
    MAX_CODE_SIZE = 100_000
    MAINTENANCE_MODE = False
    MAINTENANCE_MESSAGE = "🚀 אנחנו מעלים עדכון חדש!\nהבוט יחזור לפעול ממש בקרוב (1 - 3 דקות)"
    MAINTENANCE_AUTO_WARMUP_SECS = 30

config = _Cfg()
