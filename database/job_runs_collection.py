JOB_RUNS_COLLECTION = "job_runs"

JOB_RUNS_INDEXES = [
    {"keys": [("job_id", 1), ("started_at", -1)]},
    {"keys": [("status", 1)]},
    {"keys": [("started_at", -1)], "expireAfterSeconds": 7 * 24 * 3600},  # TTL: 7 ימים
    {"keys": [("user_id", 1), ("job_id", 1)], "sparse": True},
]

