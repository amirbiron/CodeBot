from __future__ import annotations

from typing import Any, Dict, Optional, List

# מקור הנתונים: מנהל הקאש הקיים
from cache_manager import cache, cache_op_duration_seconds


def _hist_avg_seconds(operation: Optional[str] = None, backend: str = "redis") -> Optional[float]:
    """מחשב זמן ממוצע מ-Histogram של prometheus_client (best-effort).

    מחזיר None אם לא ניתן לחשב בבטחה.
    """
    try:
        if cache_op_duration_seconds is None:
            return None
        if operation:
            child = cache_op_duration_seconds.labels(operation=operation, backend=backend)
            # שימוש ב-counter הפנימי באופן זהיר (לצרכי תצוגה בלבד)
            get_count = getattr(getattr(child, "_count", None), "get", None)
            get_sum = getattr(getattr(child, "_sum", None), "get", None)
            if callable(get_count) and callable(get_sum):
                count = float(get_count())
                total = float(get_sum())
                if count > 0:
                    return total / count
            return None
        # ממוצע across operations בסיסיות אם לא צוין operation
        ops: List[str] = ["get", "set", "delete", "delete_pattern"]
        vals = [v for v in (_hist_avg_seconds(op, backend) for op in ops) if v is not None]
        if vals:
            return sum(vals) / float(len(vals))
        return None
    except Exception:
        return None


def collect_cache_metrics() -> Dict[str, Any]:
    """איסוף מטריקות קאש לתצוגה בדשבורד.

    כולל טיפול ב-Redis כבוי: ערכים 0 ומסר סטטוס ידידותי.
    """
    try:
        stats = cache.get_stats()
    except Exception:
        stats = {"enabled": False}

    enabled = bool(stats.get("enabled", False))
    hits = int(stats.get("keyspace_hits", 0) or 0)
    misses = int(stats.get("keyspace_misses", 0) or 0)
    hit_rate = float(stats.get("hit_rate", 0.0) or 0.0)
    used_memory = stats.get("used_memory", "0")

    # זמן תגובה ממוצע (ms) — העדפה ל-get; נפילה חזרה לממוצע כולל/אפס
    avg_get = _hist_avg_seconds("get") or 0.0
    avg_set = _hist_avg_seconds("set") or 0.0
    candidates = [x for x in (avg_get, avg_set) if (x or 0) > 0]
    avg_latency_ms = ((sum(candidates) / len(candidates)) * 1000.0) if candidates else 0.0

    return {
        "enabled": enabled,
        "status": "ok" if enabled else "disabled",
        "message": None if enabled else "Redis כבוי",
        "metrics": {
            "hit_rate": round(hit_rate, 2),
            "hits": hits,
            "misses": misses,
            "avg_latency_ms": round(avg_latency_ms, 2),
            "used_memory": used_memory,
        },
    }
