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

