#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
import threading
import time
from typing import Optional

# Local imports
try:
    from monitoring.log_analyzer import LogEventAggregator
except Exception as e:  # pragma: no cover
    sys.stderr.write(f"Failed to import LogEventAggregator: {e}\n")
    sys.exit(2)


def _to_bool(val: Optional[str]) -> bool:
    return str(val or "").strip().lower() in {"1", "true", "yes", "on"}


def main() -> int:
    sig_path = os.getenv("ERROR_SIGNATURES_PATH", "config/error_signatures.yml")
    grp_path = os.getenv("ALERTS_GROUPING_CONFIG", "config/alerts.yml")
    reload_sec = 60
    try:
        reload_sec = max(0, int(os.getenv("LOG_AGG_RELOAD_SECONDS", "60") or 60))
    except Exception:
        reload_sec = 60

    agg = LogEventAggregator(signatures_path=sig_path, alerts_config_path=grp_path)

    # Optional periodic reload of signatures/config
    stop = threading.Event()

    def _reloader() -> None:
        while not stop.wait(reload_sec if reload_sec > 0 else 1_000_000):
            try:
                agg.signatures.reload()
            except Exception:
                # best-effort
                pass

    if reload_sec > 0:
        t = threading.Thread(target=_reloader, name="log-agg-reloader", daemon=True)
        t.start()

    # Read lines from stdin
    if sys.stdin is None or sys.stdin.closed:
        sys.stderr.write("stdin is not available; pipe logs into this script.\n")
        return 3

    # Optional: echo matched lines for debugging
    echo = _to_bool(os.getenv("LOG_AGG_ECHO", "0"))

    try:
        for line in sys.stdin:
            if not line:
                continue
            try:
                out = agg.analyze_line(line)
                if echo and out is not None:
                    sys.stderr.write("[matched] " + line)
            except Exception:
                # never fail on a single line
                continue
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
