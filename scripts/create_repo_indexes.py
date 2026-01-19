from database.db_manager import get_db

db = get_db()

# sync_jobs - לחיפוש pending jobs
db.sync_jobs.create_index([("status", 1), ("created_at", 1)])

# sync_jobs - TTL index למחיקה אוטומטית
db.sync_jobs.create_index("expire_at", expireAfterSeconds=0)

# repo_files - לחיפוש לפי path
db.repo_files.create_index([("repo_name", 1), ("path", 1)], unique=True)

# repo_files - לחיפוש טקסט
db.repo_files.create_index([("search_text", "text")])

# repo_files - לחיפוש לפי שפה
db.repo_files.create_index([("repo_name", 1), ("language", 1)])

# code_snippets - base index for attention widget
db.code_snippets.create_index(
    [
        ('user_id', 1),
        ('is_active', 1),
        ('updated_at', -1)
    ],
    name='idx_attention_base'
)

# code_snippets - stale files with tags index
db.code_snippets.create_index(
    [
        ('user_id', 1),
        ('is_active', 1),
        ('updated_at', 1),
        ('tags.0', 1)
    ],
    name='idx_attention_stale_with_tags'
)

# attention_dismissals - unique index
db.attention_dismissals.create_index(
    [
        ('user_id', 1),
        ('file_id', 1)
    ],
    unique=True,
    name='idx_attention_dismissals_unique'
)

# attention_dismissals - TTL index
db.attention_dismissals.create_index(
    [('expires_at', 1)],
    expireAfterSeconds=0,
    name='idx_attention_dismissals_ttl'
)

