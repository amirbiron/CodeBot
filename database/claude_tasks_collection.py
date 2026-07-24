"""הצהרות ל-collection של משימות Claude Code (‎/claude‎ בבוט).

הרישום בפועל של האינדקסים נעשה ב-``DatabaseManager._create_indexes``;
הקובץ הזה הוא מקור אמת יחיד לשמות ולמבנה.
"""

CLAUDE_TASKS_COLLECTION = "claude_tasks"

CLAUDE_TASKS_INDEXES = [
    {"keys": [("request_id", 1)], "unique": True},
    {"keys": [("issue_number", -1)]},
    {"keys": [("user_id", 1), ("created_at", -1)]},
    {"keys": [("status", 1), ("created_at", -1)]},
]

# מצבי המשימה לאורך חייה
CLAUDE_TASK_STATUSES = (
    "pending_confirm",  # נוצר preview, ממתין ללחיצה על "שלח"
    "dispatched",       # ה-Issue נפתח ב-GitHub
    "running",          # ה-workflow זוהה כרץ
    "completed",        # Claude סיים
    "failed",           # הריצה נכשלה
    "cancelled",        # המשתמש ביטל
    "timeout",          # לא זוהתה ריצה בזמן סביר
)
