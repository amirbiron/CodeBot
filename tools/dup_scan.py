#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from duplicate_detector import scan_duplicates


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan for exact duplicate files")
    parser.add_argument("--path", default=".", help="Base path to scan")
    parser.add_argument("--include", action="append", default=[], help="Glob pattern to include (can repeat)")
    parser.add_argument("--min-lines", type=int, default=5, help="Minimum lines per file to consider")
    parser.add_argument("--max-files", type=int, default=500, help="Maximum files to scan")
    parser.add_argument("--timeout-sec", type=int, default=120, help="Timeout seconds (unused; for compatibility)")
    parser.add_argument("--json", action="store_true", help="Output JSON instead of text")
    args = parser.parse_args()

    base = Path(args.path).resolve()
    if not base.exists():
        print(f"Base path not found: {base}", file=sys.stderr)
        return 2

    results = scan_duplicates(str(base), includes=args.include, min_lines=args.min_lines, max_files=args.max_files)

    if args.json:
        print(json.dumps(results, indent=2, sort_keys=True))
    else:
        if not results:
            print("No duplicates found")
        else:
            print("Duplicate groups:")
            for h, paths in results.items():
                print(f"- hash {h[:12]}: {len(paths)} files")
                for p in paths:
                    print(f"  • {p}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
