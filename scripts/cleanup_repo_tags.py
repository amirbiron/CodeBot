#!/usr/bin/env python3
"""
Cleanup tool to normalize repo:* tags on code_snippets documents and backfill
favorites fields for legacy documents.

- Keeps only the latest repo:* tag per document (preserving non-repo tags)
- Optionally clear all repo:* tags for specific filenames (e.g., index.html)
- Backfills missing fields: is_favorite=False, favorited_at=None for documents
  without these fields

Usage:
  python scripts/cleanup_repo_tags.py --user-id 123456 --apply
  python scripts/cleanup_repo_tags.py --user-id 123456 --clear-index --apply

Env:
  MONGODB_URL (required)
  DATABASE_NAME (default: code_keeper_bot)
"""
from __future__ import annotations

import os
import sys
import argparse
from datetime import datetime, timezone
from typing import List

from pymongo import MongoClient

# Observability (fail-open):
try:  # type: ignore
    from observability import emit_event  # type: ignore
except Exception:  # pragma: no cover
    def emit_event(event: str, severity: str = "info", **fields):  # type: ignore
        return None
try:  # type: ignore
    from internal_alerts import emit_internal_alert  # type: ignore
except Exception:  # pragma: no cover
    def emit_internal_alert(name: str, severity: str = "info", summary: str = "", **details):  # type: ignore
        return None


def normalize_tags(tags: List[str]) -> List[str]:
    if not isinstance(tags, list):
        return []
    non_repo: List[str] = []
    repo_tags: List[str] = []
    for t in tags:
        if not isinstance(t, str):
            continue
        ts = t.strip()
        if not ts:
            continue
        if ts.lower().startswith('repo:'):
            repo_tags.append(ts)
        else:
            if ts not in non_repo:
                non_repo.append(ts)
    last_repo = repo_tags[-1] if repo_tags else None
    return non_repo + ([last_repo] if last_repo else [])


def main() -> int:
    parser = argparse.ArgumentParser(description="Normalize repo:* tags for user's code_snippets")
    parser.add_argument('--user-id', type=int, required=True, help='User ID to clean')
    parser.add_argument('--apply', action='store_true', help='Apply changes (otherwise dry-run)')
    parser.add_argument('--clear-index', action='store_true', help='Remove repo:* tags for files named index.html')
    args = parser.parse_args()

    mongo_url = os.getenv('MONGODB_URL')
    if not mongo_url:
        try:
            emit_event(
                'cleanup_repo_tags_missing_mongo_url',
                severity='anomaly',
                operation='cleanup_repo_tags',
                handled=True,
            )
            emit_internal_alert(
                name='cleanup_repo_tags_missing_mongo_url',
                severity='anomaly',
                summary='MONGODB_URL is not set',
            )
        except Exception:
            pass
        print('ERROR: MONGODB_URL is not set', file=sys.stderr)
        return 2
    dbname = os.getenv('DATABASE_NAME', 'code_keeper_bot')

    client = MongoClient(mongo_url, tz_aware=True, tzinfo=timezone.utc)
    db = client[dbname]
    coll = db.code_snippets

    user_id = int(args.user_id)
    q = {'user_id': user_id}
    cursor = coll.find(q, projection={'file_name': 1, 'tags': 1, 'updated_at': 1})
    total = 0
    changed = 0
    index_cleared = 0
    for doc in cursor:
        total += 1
        tags = doc.get('tags') or []
        fname = doc.get('file_name') or ''
        new_tags: List[str]
        if args.clear_index and fname.strip().lower().endswith('index.html'):
            # Remove all repo:* tags for index.html
            new_tags = [t for t in tags if isinstance(t, str) and not t.strip().lower().startswith('repo:')]
            if new_tags != tags:
                index_cleared += 1
        else:
            new_tags = normalize_tags(tags)
        if new_tags != tags:
            changed += 1
            if args.apply:
                coll.update_one({'_id': doc['_id']}, {'$set': {'tags': new_tags, 'updated_at': datetime.now(timezone.utc)}})

    # Backfill favorites fields (optional global, not only user-specific)
    try:
        if args.apply:
            res = coll.update_many(
                {"is_favorite": {"$exists": False}},
                {"$set": {"is_favorite": False, "favorited_at": None}},
            )
            backfilled = getattr(res, 'modified_count', 0)
        else:
            backfilled = coll.count_documents({"is_favorite": {"$exists": False}})
    except Exception:
        backfilled = 0

    try:
        emit_event(
            'cleanup_repo_tags_summary',
            severity='info',
            operation='cleanup_repo_tags',
            total=int(total),
            changed=int(changed),
            index_cleared=int(index_cleared),
            favorites_backfilled=int(backfilled),
            apply=bool(args.apply),
        )
    except Exception:
        pass
    print(f"Scanned: {total} docs; Changed: {changed}; Index cleared: {index_cleared}; Favorites backfilled: {backfilled}; Apply: {args.apply}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

