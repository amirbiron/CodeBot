# ספריית Code Snippets - Observability ו-Monitoring

ספריית סניפטים אמיתית מהממשקים של Observability Dashboard, Job Monitor, Query Profiler, Config Inspector, Cache Inspector, וניטור בריאות מסד הנתונים.

כל סניפט מחוץ לפקודות מפתחה שהוא שימושי, כיצד השתמש בו, ומדוע זה חשוב.

---

## Job Tracking & Monitoring

### 1. Context Manager למעקב אחר Job עם Error Handling

**שם:** Job Tracker Context Manager
**שימוש:** מעקב פשוט אחר רצף job מ-התחלה לסוף תוך שמירת לוגים ותוצאות
**קוד:**

```python
@contextmanager
def track(
    self,
    job_id: str,
    trigger: str = "scheduled",
    user_id: Optional[int] = None,
):
    """Context manager למעקב אחרי הרצה"""
    run = self.start_run(job_id, trigger, user_id)
    try:
        yield run
        self.complete_run(run.run_id)
    except Exception as e:
        self.fail_run(run.run_id, str(e))
        raise
```

**שימוש:**

```python
from services.job_tracker import get_job_tracker

tracker = get_job_tracker()

with tracker.track(job_id="cleanup_users", trigger="manual") as run:
    # הקוד שלך כאן
    tracker.update_progress(run.run_id, processed=10, total=100)
    tracker.add_log(run.run_id, "info", "Processing user 10...")
    # אם יש exception, fail_run יקרא אוטומטית
```

---

## Query Performance Profiling

### 2. נרמול צורת Query בטוח (ללא דליפת PII)

**שם:** Query Shape Normalization with Security
**שימוש:** הצפנה של צורת שאילתה ללא דליפת מידע אישי (PII), מאפשר זיהוי דפוסי שאילתות דומים
**קוד:**

```python
def _normalize_query_shape(self, query: Dict[str, Any]) -> Dict[str, Any]:
    """
    נרמול צורת השאילתה - החלפת ערכים בפלייסהולדרים.
    🔒 אבטחה: פונקציה זו מונעת דליפת מידע אישי (PII) לדשבורד/לוגים
    """
    SORT_LIKE_KEYS = {"$sort", "$orderby"}

    def normalize_value(value: Any, parent_key: Optional[str] = None) -> Any:
        if isinstance(value, dict):
            result: Dict[str, Any] = {}
            for k, v in value.items():
                str_k = str(k)
                if str_k in SORT_LIKE_KEYS:
                    result[str_k] = normalize_value(v, parent_key=str_k)
                else:
                    result[str_k] = normalize_value(v, parent_key=parent_key)
            return result

        if isinstance(value, list):
            if not value:
                return []
            # שמירת אורך המערך, החלפת ערכים בפלייסהולדרים
            if all(isinstance(v, (str, int, float, bool, type(None))) for v in value):
                out: List[Any] = []
                for v in value:
                    if v is None:
                        out.append("<null>")
                    elif isinstance(v, str) and v.startswith("$"):
                        out.append(v)  # שמירת field-paths
                    elif parent_key in SORT_LIKE_KEYS and isinstance(v, (int, float)) and v in (1, -1, 1.0, -1.0):
                        out.append(int(v))  # שמירת כיוון מיון
                    else:
                        out.append("<value>")
                return out
            return [normalize_value(v, parent_key=parent_key) for v in value]

        if value is None:
            return "<null>"
        if isinstance(value, str):
            return value if value.startswith("$") else "<value>"
        if parent_key in SORT_LIKE_KEYS and isinstance(value, (int, float)) and value in (1, -1, 1.0, -1.0):
            return int(value)

        return "<value>"

    result: Dict[str, Any] = {}
    for k, v in (query or {}).items():
        str_k = str(k)
        if str_k in SORT_LIKE_KEYS:
            result[str_k] = normalize_value(v, parent_key=str_k)
        else:
            result[str_k] = normalize_value(v, parent_key=None)
    return result
```

**שימוש:**

```python
from services.query_profiler_service import QueryProfilerService

profiler = QueryProfilerService(db_manager)

# רישום שאילתה איטית
record = profiler.record_slow_query_sync(
    collection="users",
    operation="find",
    query={"email": "user@example.com", "status": "active"},
    execution_time_ms=1500.0
)

# הפרופיילר ינרמל את ה-query למשהו כמו:
# {"email": "<value>", "status": "<value>"}
# וזה לא יחשוף את ה-email של המשתמש בלוגים או דשבורד
```

---

## Configuration Management

### 3. Config Inspector - בדיקה מרכזית של קונפיגורציה

**שם:** Config Service with Sensitive Value Masking
**שימוש:** סקירה מלאה של כל משתני הסביבה עם הסתרה אוטומטית של ערכים רגישים
**קוד:**

```python
def get_config_overview(
    self,
    category_filter: Optional[str] = None,
    status_filter: Optional[ConfigStatus] = None,
) -> ConfigOverview:
    """קבלת סקירת קונפיגורציה מלאה"""
    entries: List[ConfigEntry] = []
    categories_set: set[str] = set()

    for definition in self.CONFIG_DEFINITIONS.values():
        entry = self.get_config_entry(definition)
        categories_set.add(entry.category)

        # סינון לפי קטגוריה וסטטוס
        if category_filter and entry.category != category_filter:
            continue
        if status_filter and entry.status != status_filter:
            continue

        entries.append(entry)

    # מיון לפי קטגוריה ואז לפי שם
    entries.sort(key=lambda e: (e.category, e.key))

    # חישוב סטטיסטיקות
    modified_count = sum(1 for e in entries if e.status == ConfigStatus.MODIFIED)
    missing_count = sum(1 for e in entries if e.status == ConfigStatus.MISSING)
    default_count = sum(1 for e in entries if e.status == ConfigStatus.DEFAULT)

    return ConfigOverview(
        entries=entries,
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        total_count=len(entries),
        modified_count=modified_count,
        missing_count=missing_count,
        default_count=default_count,
        categories=sorted(categories_set),
    )

def validate_required(self) -> List[str]:
    """בדיקת משתנים הכרחיים חסרים"""
    missing = []
    for definition in self.CONFIG_DEFINITIONS.values():
        if not definition.required:
            continue

        env_value = self.get_env_value(definition.key)
        default_str = str(definition.default) if definition.default is not None else None

        env_is_empty = self._is_empty_value(env_value)
        default_is_empty = self._is_empty_value(default_str)

        if env_is_empty and default_is_empty:
            missing.append(definition.key)

    return missing
```

**שימוש:**

```python
from services.config_inspector_service import get_config_service

config_svc = get_config_service()

# קבלת סקירה מלאה
overview = config_svc.get_config_overview()
print(f"Total configs: {overview.total_count}")
print(f"Modified: {overview.modified_count}")
print(f"Missing: {overview.missing_count}")

# בדיקת ערכים הכרחיים חסרים
missing = config_svc.validate_required()
if missing:
    print(f"❌ Missing required configs: {missing}")
else:
    print("✅ All required configs present")

# סינון לפי קטגוריה
db_config = config_svc.get_config_overview(category_filter="database")
```

---

## Cache Inspection & Management

### 4. Redis Inspector - סריקה בטוחה של Cache עם Sensitivity

**שם:** Cache Inspector with Safe Scanning
**שימוש:** סריקה בטוחה של Redis עם מטא-דאטה (TTL, size, status), הסתרת ערכים רגישים
**קוד:**

```python
def list_keys(
    self,
    pattern: str = "*",
    limit: int = DEFAULT_SCAN_LIMIT,
) -> Tuple[List[CacheEntry], int, bool]:
    """רשימת מפתחות עם מטא-דאטה"""
    if not self.is_enabled():
        return [], 0, False

    limit = min(max(1, limit), self.MAX_SCAN_LIMIT)
    entries: List[CacheEntry] = []
    scanned = 0
    has_more = False

    try:
        client = self.redis_client

        # סריקה בטוחה עם SCAN - לא חוסם ל-full key list
        for key in client.scan_iter(match=pattern, count=100):
            scanned += 1

            if len(entries) >= limit:
                has_more = True
                break

            try:
                ttl = client.ttl(key)
                try:
                    size = client.strlen(key)
                except Exception:
                    size = 0

                preview, value_type = self._get_value_preview(key)
                status = self._determine_status(ttl)

                entries.append(
                    CacheEntry(
                        key=key,
                        value_preview=preview,
                        ttl_seconds=ttl,
                        size_bytes=size,
                        status=status,
                        value_type=value_type,
                    )
                )

            except Exception as e:
                logger.warning(f"Error processing key {key}: {e}")
                continue

        entries.sort(key=lambda e: e.key)

    except Exception as e:
        logger.error(f"Error listing cache keys: {e}")

    return entries, scanned, has_more

def get_key_prefixes(self, sample_size: int = 1000) -> Dict[str, int]:
    """ניתוח תפוצת prefixes במפתחות - מודד דפוסי שימוש"""
    if not self.is_enabled():
        return {}

    prefixes: Dict[str, int] = {}

    try:
        client = self.redis_client
        count = 0

        for key in client.scan_iter(match="*", count=100):
            count += 1
            if count > sample_size:
                break

            # חילוץ prefix (עד ה-: הראשון)
            if ":" in key:
                prefix = key.split(":")[0]
            else:
                prefix = "(no-prefix)"

            prefixes[prefix] = prefixes.get(prefix, 0) + 1

    except Exception as e:
        logger.error(f"Error analyzing prefixes: {e}")

    return dict(sorted(prefixes.items(), key=lambda x: -x[1]))
```

**שימוש:**

```python
from services.cache_inspector_service import get_cache_inspector_service

cache_inspector = get_cache_inspector_service()

# סריקה עם pattern
entries, scanned, has_more = cache_inspector.list_keys(pattern="user:*", limit=100)
for entry in entries:
    print(f"{entry.key}: {entry.value_preview} (TTL: {entry.ttl_seconds}s, {entry.status})")

# ניתוח prefixes
prefixes = cache_inspector.get_key_prefixes(sample_size=500)
print("Cache distribution by prefix:")
for prefix, count in prefixes.items():
    print(f"  {prefix}: {count} keys")

# קבלת סקירה מלאה
overview = cache_inspector.get_overview(pattern="session:*", limit=50)
print(f"Cache stats: {overview.stats.hit_rate}% hit rate")
```

---

## Database Health Monitoring

### 5. Async Database Health Service - ניטור בריאות לא-חוסם

**שם:** Async DB Health Monitoring with Motor
**שימוש:** ניתור בריאות MongoDB אסינכרוני - pool status, slow queries, collection stats
**קוד:**

```python
async def get_health_summary(self) -> Dict[str, Any]:
    """סיכום בריאות כללי לדשבורד"""
    summary: Dict[str, Any] = {
        "timestamp": time.time(),
        "status": "unknown",
        "pool": None,
        "slow_queries_count": 0,
        "collections_count": 0,
        "errors": [],
    }

    # Pool status
    try:
        pool = await self.get_pool_status()
        summary["pool"] = pool.to_dict()
    except Exception as e:
        summary["errors"].append(f"pool: {e}")

    # Slow queries count
    try:
        ops = await self.get_current_operations()
        summary["slow_queries_count"] = len(ops)
    except Exception as e:
        summary["errors"].append(f"ops: {e}")

    # Collections count
    try:
        if self._db:
            coll_names = await self._db.list_collection_names()
            summary["collections_count"] = len([n for n in coll_names if not n.startswith("system.")])
    except Exception as e:
        summary["errors"].append(f"collections: {e}")

    # קביעת סטטוס כללי
    if summary["errors"]:
        summary["status"] = "error"
    elif (summary.get("pool") or {}).get("status") == "critical":
        summary["status"] = "critical"
    elif summary["slow_queries_count"] > 5:
        summary["status"] = "warning"
    elif (summary.get("pool") or {}).get("status") == "warning":
        summary["status"] = "warning"
    else:
        summary["status"] = "healthy"

    return summary

async def get_current_operations(
    self,
    threshold_ms: int = SLOW_QUERY_THRESHOLD_MS,
    include_system: bool = False,
) -> List[SlowOperation]:
    """זיהוי פעולות איטיות באמצעות currentOp"""
    if self._client is None:
        raise RuntimeError("No MongoDB client available - call connect() first")

    try:
        threshold_secs = threshold_ms / 1000.0
        result = await self._client.admin.command("currentOp", {"$all": True})

        slow_ops: List[SlowOperation] = []

        for op in result.get("inprog", []):
            # דילוג על פעולות מערכת אם לא התבקש
            if not include_system:
                ns = op.get("ns", "")
                if ns.startswith("admin.") or ns.startswith("local.") or ns.startswith("config."):
                    continue
                if op.get("desc", "").startswith("conn") and op.get("op") == "none":
                    continue

            # חישוב זמן ריצה
            secs_running = op.get("secs_running", 0)
            microsecs = op.get("microsecs_running", 0)
            if microsecs and not secs_running:
                secs_running = microsecs / 1_000_000

            if secs_running < threshold_secs:
                continue

            # חילוץ פרטי השאילתה
            command = op.get("command", {})
            query = command.get("filter", command.get("query", command))

            slow_ops.append(
                SlowOperation(
                    op_id=str(op.get("opid", "")),
                    operation_type=op.get("op", "unknown"),
                    namespace=op.get("ns", "unknown"),
                    running_secs=float(secs_running),
                    query=query if isinstance(query, dict) else {"raw": str(query)},
                    client_ip=op.get("client_s", op.get("client", "")),
                    description=op.get("desc", ""),
                )
            )

        slow_ops.sort(key=lambda x: x.running_secs, reverse=True)
        return slow_ops

    except Exception as e:
        logger.error(f"Failed to get current operations: {e}")
        raise RuntimeError(f"currentOp failed: {e}") from e
```

**שימוש:**

```python
from services.db_health_service import get_db_health_service

health_svc = await get_db_health_service()

# קבלת סיכום בריאות כללי
health = await health_svc.get_health_summary()
print(f"DB Status: {health['status']}")
print(f"Pool status: {health['pool']}")
print(f"Slow queries: {health['slow_queries_count']}")

# קבלת פעולות איטיות עם סף מותאם
slow_ops = await health_svc.get_current_operations(threshold_ms=500)
for op in slow_ops:
    print(f"🐢 {op.namespace}: {op.running_secs}s - {op.operation_type}")

# קבלת סטטיסטיקות collections
stats = await health_svc.get_collection_stats()
for stat in stats:
    print(f"📊 {stat.name}: {stat.count} docs, {stat.size_bytes / 1024 / 1024:.2f}MB")
```

---

## וסיכום

סניפטים אלה מהווים בסיס עבור developers שבונים בוטים וזרימות טלגרם עם צורך בניטור וcontexed מתקדם:

- **Job Tracking** - עקוב אחר Job עם logging ו-error handling אוטומטי
- **Query Profiling** - שמור צורת שאילתה בטוח ללא דליפת PII
- **Config Management** - סקור את כל הקונפיגורציה ודא ערכים הכרחיים
- **Cache Inspection** - סרוק Redis בטוח עם מטא-דאטה וטיפול בערכים רגישים
- **DB Health** - מנטר בריאות DB בעזרת API אסינכרוני

כל סניפט ניתן להשתמש ישירות באפליקציה שלך!
