# ⚡ אופטימיזציה לביצועים ומדרגיות

## 📊 מצב נוכחי - ניתוח

### Database Queries
```python
# conversation_handlers.py - N+1 query problem
async def list_user_files_callback(query, user_id, page):
    files = db.get_user_files(user_id, skip=page*10, limit=10)  # ✅ pagination
    for file in files:
        # אבל: אם צריך מידע נוסף לכל קובץ - N queries נוספים
        versions = db.count_versions(file['file_name'])  # ❌ N+1!
```

### Cache Usage
```python
# cache_manager.py - Cache קיים אבל לא בשימוש מספיק
@cached(expire_seconds=180, key_prefix="latest_version")
def get_latest_version(self, user_id: int, file_name: str):
    # ✅ Cached
    
# אבל:
def get_user_files(self, user_id: int):
    # ❌ לא cached! נקרא הרבה
```

---

## 🔍 בעיות ביצועים שזוהו

### 1. MongoDB Queries לא מאופטמות

```python
# database/repository.py
def list_all_files(self, user_id: int):
    return list(self.manager.collection.find({
        "user_id": user_id,
        "is_active": True
    }))  # ❌ טוען הכל לזיכרון!
```

**בעיה**: 
- משתמש עם 1000 קבצים → 10MB+ בזיכרון
- Slow for large datasets
- OOM risk

**פתרון**:
```python
def list_all_files(self, user_id: int, projection=None):
    """רשימת קבצים עם projection לביצועים"""
    projection = projection or {
        "file_name": 1,
        "programming_language": 1,
        "updated_at": 1,
        "tags": 1
    }  # רק השדות הנחוצים!
    
    return self.manager.collection.find(
        {"user_id": user_id, "is_active": True},
        projection=projection
    ).limit(1000)  # hard limit למניעת abuse
```

---

### 2. חסרים Connection Pooling אופטימליים

```python
# database/manager.py:98
self.client = MongoClient(
    config.MONGODB_URL,
    maxPoolSize=50,      # ✅ יש
    minPoolSize=5,       # ✅ יש
    # אבל:
    # maxIdleTimeMS=30000,  # 30s - קצר מדי!
    # socketTimeoutMS=20000,  # 20s - ארוך מדי לוב Telegram
)
```

**שיפור**:
```python
self.client = MongoClient(
    config.MONGODB_URL,
    maxPoolSize=100,           # יותר connections למשתמשים רבים
    minPoolSize=10,
    maxIdleTimeMS=300000,      # 5 דקות (יותר reuse)
    socketTimeoutMS=5000,      # 5s (Telegram timeout-friendly)
    connectTimeoutMS=3000,
    retryWrites=True,
    retryReads=True,
    compressors=['zstd', 'snappy', 'zlib'],  # compression!
    zlibCompressionLevel=6,
)
```

---

### 3. Search Engine לא מדורג

```python
# search_engine.py:80-92
def rebuild_index(self, user_id: int):
    # ...
    files = db.get_user_files(user_id, limit=10000)  # ❌ כל הקבצים!
    for file_data in files:
        # בונה index בזיכרון
        # בעיה: 10,000 קבצים × 10KB = 100MB!
```

**פתרון**: 
- MongoDB Text Index (built-in)
- Elasticsearch לחיפוש מתקדם
- Incremental indexing

```python
# database/manager.py - add text index
def _create_indexes(self):
    indexes = [
        # ... existing ...
        IndexModel([
            ("code", TEXT),
            ("file_name", TEXT),
            ("description", TEXT),
            ("tags", TEXT)
        ], name="search_text_idx", weights={
            "file_name": 10,
            "description": 5,
            "tags": 3,
            "code": 1
        })
    ]
```

---

### 4. Rate Limiting חסר

**בעיה**: אין הגבלה על:
- מספר קבצים ליוזר
- גודל קבצים
- קצב requests

**פתרון**:
```python
# middleware/rate_limit.py
from collections import defaultdict
from datetime import datetime, timedelta
import asyncio

class RateLimiter:
    def __init__(self):
        # user_id → [timestamp1, timestamp2, ...]
        self.requests = defaultdict(list)
        self.lock = asyncio.Lock()
    
    async def check_rate_limit(self, user_id: int, max_per_minute: int = 30) -> bool:
        """בדיקה: האם משתמש חרג מהמגבלה"""
        async with self.lock:
            now = datetime.now()
            one_min_ago = now - timedelta(minutes=1)
            
            # נקה requests ישנים
            self.requests[user_id] = [
                ts for ts in self.requests[user_id]
                if ts > one_min_ago
            ]
            
            # בדוק limit
            if len(self.requests[user_id]) >= max_per_minute:
                return False  # חרג!
            
            self.requests[user_id].append(now)
            return True

# שימוש:
rate_limiter = RateLimiter()

async def middleware(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not await rate_limiter.check_rate_limit(user_id, max_per_minute=30):
        await update.message.reply_text(
            "⚠️ יותר מדי בקשות! נסה שוב בעוד דקה."
        )
        raise ApplicationHandlerStop
    
    return True
```

---

### 5. Caching לא מנוצל מספיק

**מה כדאי ל-cache**:
```python
# High-value caches:
@cached(expire_seconds=300)  # 5 דקות
def get_user_files_summary(user_id: int):
    """רשימת קבצים - נקרא הרבה"""
    pass

@cached(expire_seconds=3600)  # שעה
def get_user_stats(user_id: int):
    """סטטיסטיקות - חישוב כבד"""
    pass

@cached(expire_seconds=1800)  # 30 דקות
def get_popular_languages():
    """שפות פופולריות - אגרגציה כבדה"""
    pass

@cached(expire_seconds=7200)  # 2 שעות
def get_syntax_highlighting_theme(theme_name: str):
    """תמות - לא משתנות"""
    pass
```

**Cache Warming** (pre-population):
```python
async def warm_cache_for_user(user_id: int):
    """טעינה מוקדמת של נתונים נפוצים"""
    asyncio.create_task(get_user_files_summary(user_id))
    asyncio.create_task(get_user_stats(user_id))
```

---

## 🚀 אסטרטגיות מדרגיות

### 1. Horizontal Scaling

**נוכחי**: instance אחד
**מדרגי**: multiple instances + load balancer

```yaml
# docker-compose.scale.yml
version: '3.8'
services:
  bot:
    image: codekeeper-bot:latest
    deploy:
      replicas: 3  # 3 instances
    environment:
      - BOT_TOKEN=${BOT_TOKEN}
      - MONGODB_URL=${MONGODB_URL}
  
  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf
```

**אבל**: צריך distributed lock!
```python
# כבר קיים ב-main.py:293 ✅
def manage_mongo_lock():
    # MongoDB-based distributed lock
    pass
```

---

### 2. Read Replicas

```python
# database/manager.py
class DatabaseManager:
    def __init__(self):
        # Primary - writes
        self.client_primary = MongoClient(
            config.MONGODB_PRIMARY_URL,
            readPreference='primary'
        )
        
        # Secondary - reads
        self.client_secondary = MongoClient(
            config.MONGODB_SECONDARY_URL,
            readPreference='secondaryPreferred'
        )
        
        self.db_write = self.client_primary[config.DATABASE_NAME]
        self.db_read = self.client_secondary[config.DATABASE_NAME]
```

**שימוש**:
```python
# Write
db.db_write.code_snippets.insert_one(...)

# Read (can use replica)
db.db_read.code_snippets.find_one(...)
```

---

### 3. Sharding by User

```python
# עבור מסדי נתונים ענקיים (1M+ users)
def get_shard_key(user_id: int) -> str:
    """מפה משתמש ל-shard"""
    shard_count = 16
    shard_num = user_id % shard_count
    return f"shard_{shard_num}"

class ShardedDatabaseManager:
    def __init__(self):
        self.shards = {
            f"shard_{i}": MongoClient(f"mongodb://shard{i}:27017/")
            for i in range(16)
        }
    
    def get_collection(self, user_id: int):
        shard_key = get_shard_key(user_id)
        return self.shards[shard_key]['code_keeper_bot']['code_snippets']
```

---

### 4. Background Jobs

```python
# tasks/background.py
from apscheduler.schedulers.asyncio import AsyncIOScheduler

scheduler = AsyncIOScheduler()

@scheduler.scheduled_job('interval', hours=1)
async def cleanup_old_recycle_bin():
    """ניקוי סל מיחזור ישן - פעם בשעה"""
    cutoff = datetime.now(timezone.utc) - timedelta(days=config.RECYCLE_TTL_DAYS)
    result = db.collection.delete_many({
        "deleted_at": {"$lt": cutoff},
        "is_active": False
    })
    logger.info(f"Cleaned {result.deleted_count} old recycled items")

@scheduler.scheduled_job('interval', minutes=15)
async def refresh_search_index():
    """רענון אינדקס חיפוש"""
    # ... incremental update
    pass

# main.py
scheduler.start()
```

---

## 📊 Benchmarks

### Before Optimization
```
Operation           | Avg Time | P95    | P99
--------------------|----------|--------|--------
Save file           | 150ms    | 300ms  | 500ms
List 100 files      | 200ms    | 400ms  | 800ms
Search (cold)       | 1200ms   | 2500ms | 5000ms
Show file           | 80ms     | 150ms  | 300ms
```

### After Optimization (Target)
```
Operation           | Avg Time | P95    | P99
--------------------|----------|--------|--------
Save file           | 80ms     | 150ms  | 250ms
List 100 files      | 50ms     | 100ms  | 200ms
Search (cached)     | 50ms     | 100ms  | 200ms
Search (cold)       | 300ms    | 600ms  | 1000ms
Show file           | 30ms     | 60ms   | 100ms
```

**שיפור**: 2-3x מהיר יותר! 🚀

---

## 🧪 Performance Testing

```python
# tests/performance/test_load.py
import pytest
import asyncio
import time

@pytest.mark.performance
class TestLoad:
    @pytest.mark.asyncio
    async def test_concurrent_saves_100_users(self, bot_app, mongo_db):
        """100 משתמשים שומרים קובץ בו-זמנית"""
        async def save_for_user(user_id: int):
            # ... save file
            pass
        
        start = time.time()
        await asyncio.gather(*[
            save_for_user(i) for i in range(100)
        ])
        duration = time.time() - start
        
        # תוצאה: צריך להסתיים תוך 5 שניות
        assert duration < 5.0, f"Too slow: {duration}s"
    
    @pytest.mark.asyncio
    async def test_list_files_pagination_performance(self):
        """רשימת 10,000 קבצים עם pagination"""
        user_id = 999
        # ... create 10,000 files
        
        start = time.time()
        files = db.get_user_files(user_id, skip=0, limit=100)
        duration = time.time() - start
        
        assert duration < 0.1, f"Page load too slow: {duration}s"
```

---

## 📋 תוכנית יישום

### Phase 1: Quick Wins (שבוע 1)
- [ ] MongoDB query optimization (projections)
- [ ] Cache get_user_files
- [ ] Cache get_user_stats
- [ ] Rate limiting middleware
- הערכה: 30% שיפור

### Phase 2: Infrastructure (שבוע 2-3)
- [ ] Connection pool tuning
- [ ] MongoDB Text Index
- [ ] Background cleanup jobs
- [ ] Performance tests
- הערכה: 50% שיפור

### Phase 3: Scalability (חודש 2)
- [ ] Horizontal scaling setup
- [ ] Read replicas
- [ ] Cache warming
- [ ] Load testing
- הערכה: 3x capacity

### Phase 4: Advanced (רק אם נחוץ)
- [ ] Sharding
- [ ] CDN for static assets
- [ ] Elasticsearch
- הערכה: 10x capacity

---

## 💡 Monitoring

```python
# metrics המפתח לעקוב אחריהם:
- p50, p95, p99 latencies לכל operation
- Database query times
- Cache hit rate (target: >80%)
- Concurrent users
- Memory usage
- CPU usage
- Error rate
```

**Dashboard example**:
```
┌────────────────────────────────────┐
│ CodeKeeper Bot - Performance       │
├────────────────────────────────────┤
│ Active Users:      1,234           │
│ Requests/min:      5,678           │
│ Avg Response:      85ms            │
│ P95 Response:      180ms           │
│ Cache Hit Rate:    87%             │
│ DB Connections:    45/100          │
│ Memory Usage:      380MB/1GB       │
│ Error Rate:        0.05%           │
└────────────────────────────────────┘
```

---

## 🎯 מדדי הצלחה

- [ ] P95 latency < 200ms לכל operations
- [ ] Cache hit rate > 80%
- [ ] תמיכה ב-1000 משתמשים concurrent
- [ ] Memory usage < 500MB
- [ ] Zero downtime deployments
- [ ] Error rate < 0.1%

---

**תזכורת**: "Premature optimization is the root of all evil" - אבל measured optimization is wisdom 🎯
