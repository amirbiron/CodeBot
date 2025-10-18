"""
Cleanup utilities for predictive/observability artifacts (Session 5).

Rules:
- Never delete outside of the project `data/` directory.
- Fail-open: log and return on any unexpected error.
- Provide a CLI for manual cleanup in dev/CI.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable, Optional
import argparse
import os
import sys
import time

# Align with predictive_engine defaults
_DATA_DIR = Path("data")
_PREDICTIONS_FILE = _DATA_DIR / "predictions_log.json"
_INCIDENTS_FILE = _DATA_DIR / "incidents_log.json"

# Defaults for cleanup (24h)
_MAX_AGE_SEC_DEFAULT = int(os.getenv("PREDICTION_MAX_AGE_SECONDS", "86400") or 86400)


def _is_under(base: Path, target: Path) -> bool:
    try:
        b = base.resolve()
        t = target.resolve()
        return str(t).startswith(str(b) + os.sep)
    except Exception:
        return False


def _safe_rewrite_keep_recent(path: Path, min_ts: float) -> None:
    """Rewrite JSONL file keeping records whose ISO ts >= cutoff.

    We match naive ISO by substring to stay robust here; predictive_engine is stricter.
    """
    try:
        if not path.exists():
            return
        if not _is_under(_DATA_DIR, path):
            # refuse to touch anything outside data/
            return
        # Read all lines and filter by simple timestamp check when possible
        kept: list[str] = []
        cutoff = min_ts
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                s = (line or "").strip()
                if not s:
                    continue
                # Best-effort: keep lines that have an ISO timestamp >= cutoff
                try:
                    # fast path: find \"ts\": "YYYY-..."
                    import json
                    obj = json.loads(s)
                    ts_str = str(obj.get("ts") or "")
                    if not ts_str:
                        continue
                    from datetime import datetime, timezone
                    ts_dt = datetime.fromisoformat(ts_str)
                    if ts_dt.timestamp() >= cutoff:
                        kept.append(json.dumps(obj, ensure_ascii=False))
                except Exception:
                    # if parsing fails, drop the line (safer)
                    continue
        # Write back atomically-ish (simple write; acceptable for CI/dev)
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as out:
            for k in kept:
                out.write(k + "\n")
    except Exception:
        return


def cleanup_predictions(max_age_seconds: Optional[int] = None, now_ts: Optional[float] = None) -> None:
    """Cleanup old prediction records under data/.

    Keeps only records newer than now - max_age_seconds.
    """
    try:
        age = int(max_age_seconds if max_age_seconds is not None else _MAX_AGE_SEC_DEFAULT)
        t = float(now_ts if now_ts is not None else time.time())
        cutoff = t - float(age)
        _safe_rewrite_keep_recent(_PREDICTIONS_FILE, cutoff)
    except Exception:
        return


def cleanup_incidents(max_age_seconds: Optional[int] = None, now_ts: Optional[float] = None) -> None:
    """Cleanup old incident records under data/.

    Mirrors predictions cleanup for symmetry.
    """
    try:
        age = int(max_age_seconds if max_age_seconds is not None else _MAX_AGE_SEC_DEFAULT)
        t = float(now_ts if now_ts is not None else time.time())
        cutoff = t - float(age)
        _safe_rewrite_keep_recent(_INCIDENTS_FILE, cutoff)
    except Exception:
        return


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Cleanup predictive artifacts under data/")
    parser.add_argument("--predictions", action="store_true", help="Cleanup predictions_log.json")
    parser.add_argument("--incidents", action="store_true", help="Cleanup incidents_log.json")
    parser.add_argument("--all", action="store_true", help="Cleanup both predictions and incidents")
    parser.add_argument("--max-age-sec", type=int, default=_MAX_AGE_SEC_DEFAULT, help="Max age in seconds to keep")
    args = parser.parse_args(list(argv) if argv is not None else None)

    if not (args.predictions or args.incidents or args.all):
        parser.print_help()
        return 2

    if args.all or args.predictions:
        cleanup_predictions(max_age_seconds=args.max_age_sec)
    if args.all or args.incidents:
        cleanup_incidents(max_age_seconds=args.max_age_sec)
    return 0


if __name__ == "__main__":
    sys.exit(main())
