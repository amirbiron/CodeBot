#!/usr/bin/env python3
"""Issue a Personal Access Token (PAT) for the CodeKeeper MCP server.

This is ops/testing tooling — it lets you mint a token for a given Telegram
user id without going through the bot. The raw token is printed ONCE; store it
in your MCP client's ``Authorization: Bearer <token>`` header.

Usage:
    MONGODB_URL=... python scripts/mcp_issue_token.py --user-id 12345 \
        [--label "Claude Desktop"] [--ttl-days 90]
"""

from __future__ import annotations

import argparse
import os
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description="Issue a CodeKeeper MCP access token")
    parser.add_argument(
        "--user-id", type=int, required=True, help="Telegram user id (owner of the files)"
    )
    parser.add_argument("--label", default="Claude", help="Human label for this token")
    parser.add_argument(
        "--ttl-days", type=int, default=None, help="Optional expiry in days (default: no expiry)"
    )
    args = parser.parse_args()

    if not os.getenv("MONGODB_URL"):
        print("ERROR: MONGODB_URL is not set.", file=sys.stderr)
        return 2

    # Make the repo importable when run directly.
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    from database import db as db_manager  # noqa: E402
    from mcp_server.token_store import MCPTokenStore  # noqa: E402
    from mcp_server.wiring import resolve_mongo  # noqa: E402

    mongo = resolve_mongo(db_manager)
    if mongo is None:
        print("ERROR: could not connect to MongoDB.", file=sys.stderr)
        return 3

    store = MCPTokenStore(mongo)
    raw = store.issue(args.user_id, label=args.label, ttl_days=args.ttl_days)
    print(raw)
    print(
        f"\nIssued for user_id={args.user_id} (label={args.label!r}). "
        "Store it now — it will not be shown again.",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
