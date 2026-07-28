"""
Temporary MongoDB index/build audit script.

What it prints (as JSON):
1) currentOp filtered to active createIndexes commands (to verify background index builds).
2) db.users.getIndexes() - to verify an index on user_id exists.
3) db.note_reminders.getIndexes() - to verify the new index exists.

How to run:
  MONGODB_URL='mongodb://user:pass@host:27017/db?authSource=admin' python3 scripts/tmp_mongo_index_audit.py

Optional:
  DATABASE_NAME='code_keeper_bot' python3 scripts/tmp_mongo_index_audit.py
"""

from __future__ import annotations

import os
import sys
from typing import Any, Dict, List, Optional


def _print_section(title: str, payload: Any) -> None:
    print("\n" + "=" * 80)
    print(title)
    print("=" * 80)
    try:
        from bson import json_util  # type: ignore

        print(json_util.dumps(payload, indent=2, sort_keys=True))
    except Exception:
        # Fallback that won't crash on weird BSON types (best-effort).
        import json

        def _default(o: Any) -> str:
            return str(o)

        print(json.dumps(payload, indent=2, sort_keys=True, default=_default))


def _infer_db_name_from_uri(mongodb_url: str) -> Optional[str]:
    # Very small heuristic; if it fails, we require DATABASE_NAME explicitly.
    try:
        # mongodb://.../<db>?...
        after_slash = mongodb_url.split("/", 3)[3]
        db_part = after_slash.split("?", 1)[0]
        return db_part or None
    except Exception:
        return None


def _get_currentop_createindexes(admin_db: Any) -> Dict[str, Any]:
    """
    Best-effort implementation of:
      db.currentOp({"command.createIndexes": { "$exists": true }})
    """
    # Preferred: $currentOp aggregation (lets us $match like in the shell helper)
    try:
        cursor = admin_db.aggregate(
            [
                {
                    "$currentOp": {
                        "allUsers": True,
                        "idleConnections": False,
                        "idleCursors": False,
                        "idleSessions": False,
                    }
                },
                {"$match": {"command.createIndexes": {"$exists": True}}},
            ]
        )
        return {"ok": 1, "inprog": list(cursor)}
    except Exception as e_currentop_stage:
        # Fallback: plain currentOp command and filter client-side
        try:
            raw = admin_db.command({"currentOp": 1, "$all": True})
            inprog = raw.get("inprog", []) if isinstance(raw, dict) else []
            filtered = [
                op
                for op in inprog
                if isinstance(op, dict)
                and isinstance(op.get("command"), dict)
                and "createIndexes" in op.get("command", {})
            ]
            return {
                "ok": raw.get("ok", 1) if isinstance(raw, dict) else 1,
                "note": "Used fallback currentOp command; filtered client-side.",
                "error_currentOp_stage": str(e_currentop_stage),
                "inprog": filtered,
            }
        except Exception as e_cmd:
            return {
                "ok": 0,
                "error": "Failed to run currentOp (both $currentOp and command).",
                "error_currentOp_stage": str(e_currentop_stage),
                "error_currentOp_command": str(e_cmd),
            }


def main() -> int:
    mongodb_url = (os.getenv("MONGODB_URL") or os.getenv("MONGO_URI") or "").strip()
    if not mongodb_url:
        print(
            "Missing MONGODB_URL (or MONGO_URI). "
            "Set it like in .env.example, then re-run.\n"
            "Example:\n"
            "  MONGODB_URL='mongodb://localhost:27017/codebot' python3 scripts/tmp_mongo_index_audit.py",
            file=sys.stderr,
        )
        return 2

    database_name = (os.getenv("DATABASE_NAME") or "").strip() or _infer_db_name_from_uri(mongodb_url)
    if not database_name:
        print(
            "Could not infer DATABASE_NAME from MONGODB_URL. Please set DATABASE_NAME explicitly.",
            file=sys.stderr,
        )
        return 2

    try:
        from pymongo import MongoClient  # type: ignore
    except ModuleNotFoundError:
        print(
            "Missing dependency: pymongo.\n"
            "Install it (or install project requirements) and re-run:\n"
            "  python3 -m pip install -r requirements/base.txt\n"
            "Then:\n"
            "  MONGODB_URL='...' DATABASE_NAME='...' python3 scripts/tmp_mongo_index_audit.py",
            file=sys.stderr,
        )
        return 2

    client = MongoClient(mongodb_url, serverSelectionTimeoutMS=5000)
    db = client[database_name]
    admin_db = client["admin"]

    # 1) currentOp - active createIndexes
    current_op = _get_currentop_createindexes(admin_db)
    _print_section('1) db.currentOp({"command.createIndexes": {"$exists": true}})', current_op)

    # 2) users indexes
    try:
        users_indexes: List[Dict[str, Any]] = list(db["users"].list_indexes())
        _print_section("2) db.users.getIndexes()", users_indexes)
    except Exception as e:
        _print_section("2) db.users.getIndexes() - ERROR", {"ok": 0, "error": str(e)})

    # 3) note_reminders indexes
    try:
        note_reminders_indexes: List[Dict[str, Any]] = list(db["note_reminders"].list_indexes())
        _print_section("3) db.note_reminders.getIndexes()", note_reminders_indexes)
    except Exception as e:
        _print_section("3) db.note_reminders.getIndexes() - ERROR", {"ok": 0, "error": str(e)})

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

