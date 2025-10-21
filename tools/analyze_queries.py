#!/usr/bin/env python3
"""
כלי ניתוח שאילתות MongoDB (best-effort) לשימוש מקומי/דב.
- מפעיל profiler (רמת 2) לזמן קצר, שולף שאילתות איטיות ומדפיס דו"ח ממוין.
- בודק אינדקסים פעילים ושימוש בהם.
- מספק explain() לשאילתות נפוצות.

הרצה:
  DISABLE_DB=0 MONGODB_URL=mongodb://localhost:27017 DATABASE_NAME=code_keeper_bot \
  python tools/analyze_queries.py --duration 60
"""
from __future__ import annotations

import argparse
import asyncio
import os
from typing import Any, Dict, List, Tuple

# fail-open import of motor
try:
    from motor.motor_asyncio import AsyncIOMotorClient  # type: ignore
except Exception:  # pragma: no cover
    AsyncIOMotorClient = None  # type: ignore


async def _get_db():
    if AsyncIOMotorClient is None:
        raise RuntimeError("motor is not available; install motor to use this tool")
    mongo_url = os.getenv("MONGODB_URL")
    if not mongo_url:
        raise RuntimeError("MONGODB_URL is not set")
    db_name = os.getenv("DATABASE_NAME") or "code_keeper_bot"
    client = AsyncIOMotorClient(mongo_url)
    return client[db_name]


async def analyze_slow_queries(db, min_ms: int = 100, sleep_sec: int = 30) -> List[Dict[str, Any]]:
    await db.command("profile", 2)
    try:
        await asyncio.sleep(max(1, int(sleep_sec)))
        cur = db.system.profile.find({"millis": {"$gt": int(min_ms)}}).sort("millis", -1).limit(50)
        return await cur.to_list(length=50)
    finally:
        try:
            await db.command("profile", 0)
        except Exception:
            pass


async def list_index_usage(db) -> List[Tuple[str, List[Dict[str, Any]]]]:
    coll_names = await db.list_collection_names()
    out: List[Tuple[str, List[Dict[str, Any]]]] = []
    for name in coll_names:
        try:
            stats = await db.command("collStats", name, indexDetails=True)
            out.append((name, [stats]))
        except Exception:
            continue
    return out


async def explain_query(db, collection: str, query: Dict[str, Any]) -> Dict[str, Any]:
    try:
        return await db[collection].find(query).explain()
    except Exception:
        return {"error": "explain failed"}


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", type=int, default=30, help="profiling duration in seconds")
    parser.add_argument("--min-ms", type=int, default=100, help="slow query threshold (ms)")
    args = parser.parse_args()

    db = await _get_db()
    print("Starting MongoDB profiling...")
    slow = await analyze_slow_queries(db, min_ms=args.min_ms, sleep_sec=args.duration)
    print(f"\n=== Slow Queries (>={args.min_ms}ms) ===")
    for q in slow:
        try:
            op = q.get("op")
            ns = q.get("ns")
            ms = q.get("millis")
            filt = (q.get("command", {}) or {}).get("filter")
            print(f"- {op} {ns} {ms}ms filter={filt}")
        except Exception:
            pass

    print("\n=== Index Usage (collStats excerpt) ===")
    usage = await list_index_usage(db)
    for name, details in usage:
        print(f"- {name}: indexes={details[0].get('nindexes') if details else 'n/a'}")

    print("\n=== Explain common queries ===")
    samples = [
        ("code_snippets", {"user_id": 12345}),
        ("code_snippets", {"programming_language": "python"}),
        ("code_snippets", {"tags": "repo:example"}),
    ]
    for coll, q in samples:
        exp = await explain_query(db, coll, q)
        exec_ms = (exp.get("executionStats", {}) or {}).get("executionTimeMillis") if isinstance(exp, dict) else None
        print(f"- {coll} {q} -> exec={exec_ms}ms")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"Error: {e}")
