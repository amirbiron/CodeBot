#!/usr/bin/env python3
"""
סקריפט לבדיקת ביצועים של dashboard route.
הרץ מ-Render shell:
    python scripts/profile_dashboard.py
"""
import os
import sys
import time

# הגדרת סביבה
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def measure(name, func):
    """מדוד זמן ביצוע של פונקציה"""
    start = time.perf_counter()
    result = func()
    elapsed = time.perf_counter() - start
    print(f"  {name}: {elapsed:.3f}s")
    return result, elapsed

def main():
    print("=" * 50)
    print("Dashboard Performance Profile")
    print("=" * 50)

    total_start = time.perf_counter()
    timings = {}

    # 1. בדיקת lazy imports
    print("\n[1] Lazy Imports:")

    def load_helpers():
        from webapp.routes.dashboard_routes import _get_app_helpers
        return _get_app_helpers()

    helpers, timings['helpers'] = measure("_get_app_helpers()", load_helpers)

    # 2. חיבור ל-DB
    print("\n[2] Database Connection:")
    db, timings['db_connect'] = measure("get_db()", helpers.get_db)

    # 3. שאילתות - נשתמש ב-user_id לדוגמה
    # קח user_id מה-ENV או השתמש ב-1 לבדיקה
    test_user_id = int(os.getenv("TEST_USER_ID", "1"))
    print(f"\n[3] Database Queries (user_id={test_user_id}):")

    active_query = {"user_id": test_user_id, "is_active": True}

    # count
    _, timings['count'] = measure(
        "count_documents",
        lambda: db.code_snippets.count_documents(active_query)
    )

    # aggregate - size
    size_pipeline = [
        {"$match": {"user_id": test_user_id, "is_active": True}},
        {"$project": {"code_size": {"$cond": {"if": {"$and": [{"$ne": ["$code", None]}, {"$eq": [{"$type": "$code"}, "string"]}]}, "then": {"$strLenBytes": "$code"}, "else": 0}}}},
        {"$group": {"_id": None, "total_size": {"$sum": "$code_size"}}},
    ]
    _, timings['aggregate_size'] = measure(
        "aggregate (size)",
        lambda: list(db.code_snippets.aggregate(size_pipeline))
    )

    # aggregate - languages
    lang_pipeline = [
        {"$match": {"user_id": test_user_id, "is_active": True}},
        {"$group": {"_id": "$programming_language", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 5},
    ]
    _, timings['aggregate_lang'] = measure(
        "aggregate (languages)",
        lambda: list(db.code_snippets.aggregate(lang_pipeline))
    )

    # find recent
    _, timings['find_recent'] = measure(
        "find (recent files)",
        lambda: list(db.code_snippets.find(
            active_query,
            {"file_name": 1, "programming_language": 1, "created_at": 1}
        ).sort("created_at", -1).limit(5))
    )

    # 4. סיכום
    total_elapsed = time.perf_counter() - total_start

    print("\n" + "=" * 50)
    print("SUMMARY")
    print("=" * 50)

    db_total = sum(v for k, v in timings.items() if k not in ['helpers'])

    print(f"\n  Lazy imports:     {timings['helpers']:.3f}s")
    print(f"  DB operations:    {db_total:.3f}s")
    print(f"  ─────────────────────────")
    print(f"  Total measured:   {total_elapsed:.3f}s")

    print("\n[Breakdown by query]:")
    for name, elapsed in sorted(timings.items(), key=lambda x: -x[1]):
        pct = (elapsed / total_elapsed) * 100
        bar = "█" * int(pct / 5)
        print(f"  {name:20s} {elapsed:.3f}s ({pct:5.1f}%) {bar}")

    # המלצות
    print("\n" + "=" * 50)
    print("RECOMMENDATIONS")
    print("=" * 50)

    if timings['helpers'] > 0.1:
        print("  ⚠️  Lazy imports איטיים - שקול caching")

    if timings.get('aggregate_size', 0) > 0.5:
        print("  ⚠️  Aggregation לגודל איטי - שקול שדה file_size מחושב מראש")

    if db_total > 2.0:
        print("  ⚠️  שאילתות DB איטיות - בדוק אינדקסים על user_id + is_active")

    if total_elapsed < 1.0:
        print("  ✅  ביצועים תקינים!")

if __name__ == "__main__":
    main()
