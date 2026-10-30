from database.db_manager import get_db

db = get_db()

# sync_jobs - התפיסה, ה-TTL של expire_at, וג'וב רץ אחד לכל ריפו. ההגדרות חיות ב-ensure_sync_jobs_indexes, שה-worker
# של הסנכרון מריץ בעצמו לפני התפיסה הראשונה; כאן קוראים לאותה פונקציה, כדי שלא יהיו שתי הגדרות שנסחפות.
from services.repo_sync_service import ensure_sync_jobs_indexes  # noqa: E402

print("sync_jobs indexes:", ensure_sync_jobs_indexes(db))

# repo_files - לחיפוש לפי path
db.repo_files.create_index([("repo_name", 1), ("path", 1)], unique=True)

# repo_files - לחיפוש טקסט
db.repo_files.create_index([("search_text", "text")])

# repo_files - לחיפוש לפי שפה
db.repo_files.create_index([("repo_name", 1), ("language", 1)])

# repo_metadata - מפתח לוגי יחיד; list_repos (MCP) רץ עליו בכל קריאה.
# בדיקת כפילויות קודם: כפילות קיימת תפיל את יצירת ה-unique (ואת שאר הסקריפט אחריה) -
# במקרה כזה מדווחים ומדלגים, כדי שהניקוי ייעשה במודע ולא באמצע ריצת אינדקסים.
_dupes = list(
    db.repo_metadata.aggregate(
        [
            {"$group": {"_id": "$repo_name", "count": {"$sum": 1}}},
            {"$match": {"count": {"$gt": 1}}},
        ]
    )
)
if _dupes:
    print(
        "WARNING: duplicate repo_name values in repo_metadata - "
        f"skipping unique index until cleaned: {sorted(d['_id'] for d in _dupes)}"
    )
else:
    db.repo_metadata.create_index("repo_name", unique=True)

# code_snippets - base index for attention widget
db.code_snippets.create_index(
    [("user_id", 1), ("is_active", 1), ("updated_at", -1)], name="idx_attention_base"
)

# code_snippets - stale files with tags index
db.code_snippets.create_index(
    [("user_id", 1), ("is_active", 1), ("updated_at", 1), ("tags.0", 1)],
    name="idx_attention_stale_with_tags",
)

# attention_dismissals - unique index
db.attention_dismissals.create_index(
    [("user_id", 1), ("file_id", 1)], unique=True, name="idx_attention_dismissals_unique"
)

# attention_dismissals - TTL index
db.attention_dismissals.create_index(
    [("expires_at", 1)], expireAfterSeconds=0, name="idx_attention_dismissals_ttl"
)
